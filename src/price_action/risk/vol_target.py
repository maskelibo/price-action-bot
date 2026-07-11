"""Stop-distance-targeted position sizing — kayıp koruma katmanı.

``vol_target`` adı geriye uyumluluk için korunur, fakat mevcut backtest ve canlı
uygulamanın girdisi bağımsız bir ATR ölçümü değildir: giriş fiyatı ile ilk stop
arasındaki yüzde mesafedir. Stop daha genişken risk bütçesini küçültür, stop daha
darken sınırlandırılmış biçimde büyütür. Bu nedenle bu modül gerçek portföy
volatilitesi veya realized-vol targeting iddiasında bulunmaz.

Konfig (risk.yaml):
  vol_target:
    enabled: true
    input_metric: entry_stop_distance_pct
    target_atr_pct: 0.04   # legacy anahtar: %4 giriş-stop mesafesi hedefi
    min_factor: 0.20       # max %80 size azaltma (extrem high-vol koruma)
    max_factor: 1.50       # max %50 size büyütme (extrem low-vol fırsat)

Kullanım: ``abs(entry - initial_stop) / entry`` değerinden factor hesapla ve
risk_per_trade'e çarp. ``target_atr_pct`` alan adı yalnız eski config'lerle
uyumluluk içindir.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass
class VolTargetConfig:
    """Legacy-named stop-distance target sizing parametreleri."""

    enabled: bool = False
    target_atr_pct: float = 0.04
    min_factor: float = 0.20
    max_factor: float = 1.50


def vol_target_factor(
    atr_pct_at_entry: float,
    config: VolTargetConfig,
) -> float:
    """Verilen giriş-stop mesafesine göre risk-per-trade çarpanını hesapla.

    Formül: factor = target_atr / current_atr (clamped to [min, max])

    Örnek:
      target=0.04, current_atr=0.08 → factor = 0.5 (yarı pozisyon)
      target=0.04, current_atr=0.02 → factor = 2.0 → clamp 1.5 (extreme low-vol max boost)
      target=0.04, current_atr=0.04 → factor = 1.0 (normal)

    Args:
        atr_pct_at_entry: legacy parametre adı; fiilî girdi giriş-stop yüzde
            mesafesidir (0.04 = %4)
        config: VolTargetConfig — disabled ise 1.0 döner

    Returns:
        risk_per_trade çarpanı, [min_factor, max_factor] aralığında
    """
    if not config.enabled or config.target_atr_pct <= 0 or atr_pct_at_entry <= 0:
        return 1.0
    raw = config.target_atr_pct / atr_pct_at_entry
    return max(config.min_factor, min(config.max_factor, raw))


def apply_vol_target(
    base_risk_dollars: float,
    atr_pct_at_entry: float,
    config: VolTargetConfig,
) -> float:
    """Risk dollar miktarını vol-target factor ile çarp.

    Args:
        base_risk_dollars: orijinal risk_pct × equity hesabı (ör. $100)
        atr_pct_at_entry: legacy parametre adı; giriş-stop yüzde mesafesi
        config: VolTargetConfig

    Returns:
        ayarlanmış risk_dollars
    """
    factor = vol_target_factor(atr_pct_at_entry, config)
    return base_risk_dollars * factor


def from_risk_yaml(risk_cfg: dict) -> VolTargetConfig:
    """risk.yaml'dan VolTargetConfig parse et."""
    vt = risk_cfg.get("vol_target", {}) or {}
    return VolTargetConfig(
        enabled=bool(vt.get("enabled", False)),
        target_atr_pct=float(vt.get("target_atr_pct", 0.04)),
        min_factor=float(vt.get("min_factor", 0.20)),
        max_factor=float(vt.get("max_factor", 1.50)),
    )


def from_live_risk_yaml(risk_cfg: dict) -> VolTargetConfig:
    """Parse live sizing config with fail-closed validation.

    Research helpers keep their historical permissive semantics.  Live sizing
    cannot: an invalid enabled block must never silently increase exposure or
    fall back to the unscaled risk.  ``RiskOfficer`` catches ``ValueError`` and
    rejects new entries while existing positions remain untouched.
    """

    vt = risk_cfg.get("vol_target", {}) or {}
    enabled = vt.get("enabled", False)
    if not isinstance(enabled, bool):
        raise ValueError("vol_target.enabled must be a boolean")
    if not enabled:
        return VolTargetConfig(enabled=False)

    if "input_metric" not in vt:
        raise ValueError(
            "enabled live vol_target requires explicit input_metric=entry_stop_distance_pct"
        )
    input_metric = vt.get("input_metric")
    if input_metric != "entry_stop_distance_pct":
        raise ValueError(
            "vol_target.input_metric must be entry_stop_distance_pct; "
            "realized/ATR volatility is not wired into live sizing"
        )

    try:
        config = VolTargetConfig(
            enabled=True,
            target_atr_pct=float(vt.get("target_atr_pct", 0.04)),
            min_factor=float(vt.get("min_factor", 0.20)),
            max_factor=float(vt.get("max_factor", 1.50)),
        )
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid numeric vol_target value: {exc}") from exc

    values = (config.target_atr_pct, config.min_factor, config.max_factor)
    if not all(math.isfinite(value) for value in values):
        raise ValueError("vol_target values must be finite")
    if config.target_atr_pct <= 0:
        raise ValueError("vol_target.target_atr_pct must be > 0")
    if config.min_factor <= 0 or config.max_factor <= 0:
        raise ValueError("vol_target factors must be > 0")
    if config.min_factor > config.max_factor:
        raise ValueError("vol_target.min_factor must be <= max_factor")
    return config
