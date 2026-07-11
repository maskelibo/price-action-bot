"""Manifest Loader — timeframe-aware YAML overlay.

API:
    load_manifest(strategy_name, timeframe) -> dict[str, Any]

Sozlesme:
  - YAML path: src/price_action/strategies/manifests/{strategy_name}_{tf}.yaml
  - TF normalizasyonu: "15m" / "15M" / "15min" -> "15m"
  - Manifest varsa -> `parameters:` blogu YOKSA -> tum kok anahtarlari donerler
  - Manifest yoksa -> bos dict (caller 1d default'a duser)
  - Cache: process-lifetime LRU (functools.lru_cache, key=(name, tf))
  - Bozuk YAML -> logger warning + bos dict (no crash)
  - Determinizm: aynı input -> aynı output (saf fonksiyon, dosya degismezse)

Lookahead: Bu modul herhangi bir fiyat verisi islemez; sadece YAML okur.
Magic number: YAML'daki tum parametreler manifest'ten gelir, buraya hardcode yok.
"""
from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from price_action.logging_config import logger

# Manifests klasoru: bu dosyanin yaninda
_MANIFEST_DIR = Path(__file__).parent / "manifests"

# TF normalize icin bilinen takma adlar
_TF_ALIASES: dict[str, str] = {
    # 1 dakikaliklar
    "1min": "1m",
    "1minute": "1m",
    # 3 dakikaliklar
    "3min": "3m",
    # 5 dakikaliklar
    "5min": "5m",
    "5minute": "5m",
    # 15 dakikaliklar
    "15min": "15m",
    "15minute": "15m",
    # 30 dakikaliklar
    "30m": "30m",
    "30min": "30m",
    "30minute": "30m",
    # 1 saatlikler
    "1h": "1h",
    "1hour": "1h",
    "60m": "1h",
    # 4 saatlikler
    "4h": "4h",
    "4hour": "4h",
    "240m": "4h",
    # gunluk
    "1d": "1d",
    "1day": "1d",
    "d": "1d",
    "daily": "1d",
    # haftalik
    "1w": "1w",
    "1week": "1w",
    "w": "1w",
}


def normalize_tf(tf: str) -> str:
    """Timeframe string'i standart forma donustur.

    "15M" -> "15m", "15min" -> "15m", "1H" -> "1h" vb.
    Bilinmeyen format -> kucuk harfe donusturulmus ham deger.
    """
    if not tf:
        return "1d"
    normalized = tf.strip().lower()
    if normalized in _TF_ALIASES:
        return _TF_ALIASES[normalized]
    # Ust harfleri kucuk yap (ornegin "15M" -> "15m")
    return normalized


@lru_cache(maxsize=256)
def _load_yaml_cached(path_str: str) -> dict[str, Any]:
    """YAML dosyasini oku ve cache'e al (process-lifetime).

    Cache key: dosya yolu (string). Ayni yol -> ayni dict.
    Bozuk YAML -> bos dict, no crash.
    """
    path = Path(path_str)
    if not path.exists():
        return {}
    try:
        text = path.read_text(encoding="utf-8")
        raw = yaml.safe_load(text)
        if not isinstance(raw, dict):
            logger.bind(path=path_str).warning("manifest_loader.yaml_not_dict")
            return {}
        return raw
    except yaml.YAMLError as exc:
        logger.bind(path=path_str, err=str(exc)).warning("manifest_loader.yaml_parse_error")
        return {}
    except OSError as exc:
        logger.bind(path=path_str, err=str(exc)).warning("manifest_loader.yaml_read_error")
        return {}


def load_manifest(strategy_name: str, timeframe: str) -> dict[str, Any]:
    """Strateji + timeframe icin YAML manifest yukle.

    Dondurulen deger `parameters:` bloku ise o blok; yoksa tum kok dict.
    Manifest yoksa -> bos dict (caller 1d default'a duser).

    Ornekler
    --------
    >>> params = load_manifest("engulfing_continuation", "15m")
    >>> params.get("signals", {}).get("filters", {}).get("atr_min_pct")

    Parametreler
    ------------
    strategy_name:
        Strateji adi (ornegin "engulfing_continuation").
        Bosluk/buyuk harf -> kucuk+alt_cizgi normalize.
    timeframe:
        TF string (ornegin "15m", "5m", "1h").
        normalize_tf() ile standart forma getirilir.

    Cache
    -----
    LRU cache ile process-lifetime sureklilik — disk IO her cagri tekrarlanmaz.
    Cache'i temizlemek icin: load_manifest.cache_clear()
    """
    # Normalize
    name = strategy_name.strip().lower().replace(" ", "_").replace("-", "_")
    tf = normalize_tf(timeframe)

    # Dosya yolu
    fname = f"{name}_{tf}.yaml"
    path = _MANIFEST_DIR / fname
    path_str = str(path)

    raw = _load_yaml_cached(path_str)
    if not raw:
        # Manifest yok veya bos — caller 1d default kullanir
        return {}

    # `parameters:` blogu varsa onu don; yoksa tum dict
    if "parameters" in raw:
        params = raw["parameters"]
        if isinstance(params, dict):
            return params
        logger.bind(path=path_str).warning(
            "manifest_loader.parameters_not_dict — tam root donduruluyor"
        )

    return raw


def load_manifest_full(strategy_name: str, timeframe: str) -> dict[str, Any]:
    """Tam YAML icerigini don (parametreler dahil tum root dict).

    Strategy class'lari icin: signals/risk/filters gibi bloklar direkt erisim.
    load_manifest() ile ayni cache altyapisi.
    """
    name = strategy_name.strip().lower().replace(" ", "_").replace("-", "_")
    tf = normalize_tf(timeframe)
    fname = f"{name}_{tf}.yaml"
    path = _MANIFEST_DIR / fname
    return dict(_load_yaml_cached(str(path)))  # shallow copy — caller mutasyonu izole et


def get_param(
    strategy_name: str,
    timeframe: str,
    *keys: str,
    default: Any = None,
) -> Any:
    """YAML manifest'inden nested key degeri al.

    Ornekler
    --------
    >>> atr_min = get_param("engulfing_continuation", "15m",
    ...                     "signals", "filters", "atr_min_pct",
    ...                     default=0.005)
    """
    d = load_manifest_full(strategy_name, timeframe)
    for k in keys:
        if not isinstance(d, dict):
            return default
        d = d.get(k, None)
        if d is None:
            return default
    return d if d is not None else default


# ---------------------------------------------------------------------------
# Diagnostic
# ---------------------------------------------------------------------------

def list_available_manifests() -> list[tuple[str, str]]:
    """Mevcut tum manifest dosyalarini (name, tf) ciftleri olarak listele."""
    result: list[tuple[str, str]] = []
    if not _MANIFEST_DIR.exists():
        return result
    for p in sorted(_MANIFEST_DIR.glob("*.yaml")):
        stem = p.stem  # "engulfing_continuation_15m"
        # Son segment TF, geri kalan name
        parts = stem.rsplit("_", 1)
        if len(parts) == 2:
            # Ama "engulfing_continuation" icin "15m" son tek parcadir
            # Daha guvenli: bilinen TF'lerden biri mi son parca?
            name_part, tf_part = parts[0], parts[1]
            # "15m", "5m", "1d", "4h" vb. -> rakam + harf
            if re.match(r"^\d+[mhdw]$", tf_part):
                result.append((name_part, tf_part))
            else:
                # Belki "1h" gibi: tum stem name
                result.append((stem, "unknown"))
        else:
            result.append((stem, "unknown"))
    return result
