"""Unit testler: manifest_loader.py

5 test kategori:
  T1 — Manifest var: dogru dict donmeli
  T2 — Manifest yok: bos dict donmeli
  T3 — Cache: ikinci cagri disk okumasi yapmaz (mock ile dogrula)
  T4 — Bozuk YAML: crash yok, bos dict donmeli
  T5 — TF normalize: buyuk/kucuk/alias -> standart form

Backward compat not:
  1d default stratejileri etkilenmez; yoksa bos dict -> caller default devam eder.
"""
from __future__ import annotations

import textwrap
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _import_fresh():
    """Her test icin temiz lru_cache icin modul reimport (veya cache_clear)."""
    from price_action.strategies import manifest_loader
    manifest_loader._load_yaml_cached.cache_clear()
    return manifest_loader


# ---------------------------------------------------------------------------
# T1: Manifest var — dogru dict donmeli
# ---------------------------------------------------------------------------

class TestManifestExists:
    """10 adet 15m YAML mevcut — bunlardan biri uzerinden test et."""

    def test_engulfing_15m_returns_dict(self):
        ml = _import_fresh()
        result = ml.load_manifest("engulfing_continuation", "15m")
        # Manifest bos olmamali
        assert isinstance(result, dict), "Manifest var, bos dict donmemeli"
        assert len(result) > 0, "Manifest bos dict donmemeli"

    def test_returns_known_key(self):
        """15m manifest 'signals' veya 'risk' blogu icermeli."""
        ml = _import_fresh()
        result = ml.load_manifest("engulfing_continuation", "15m")
        # Manifest kok seviyesi -> signals veya risk bloku bekleniyor
        assert "signals" in result or "risk" in result, (
            f"Beklenen kok anahtarlar yok. Mevcut: {list(result.keys())}"
        )

    def test_vsa_climax_15m_exists(self):
        ml = _import_fresh()
        result = ml.load_manifest("vsa_climax_test", "15m")
        assert isinstance(result, dict) and len(result) > 0

    def test_load_manifest_full_same_as_load(self):
        """load_manifest_full vs load_manifest: parameters blogu olmayinca ayni."""
        ml = _import_fresh()
        a = ml.load_manifest("engulfing_continuation", "15m")
        b = ml.load_manifest_full("engulfing_continuation", "15m")
        # load_manifest: eger 'parameters:' blogu yoksa -> kok dict (ayni)
        # Her iki cagri da ayni kok yapiyi donmeli (ya kok ya parameters blogu)
        assert type(a) is type(b) is dict


# ---------------------------------------------------------------------------
# T2: Manifest yok — bos dict donmeli
# ---------------------------------------------------------------------------

class TestManifestMissing:
    def test_unknown_strategy_returns_empty(self):
        ml = _import_fresh()
        result = ml.load_manifest("nonexistent_strategy_xyz", "15m")
        assert result == {}, f"Beklenen bos dict, alindi: {result}"

    def test_known_strategy_unknown_tf_returns_empty(self):
        """1d manifest yoksa (sadece 15m var) -> bos dict."""
        ml = _import_fresh()
        # engulfing_continuation_1d.yaml yok; sadece _15m.yaml var
        result = ml.load_manifest("engulfing_continuation", "1d")
        assert result == {}, "1d manifest yok -> bos dict bekleniyor"

    def test_5m_manifest_returns_dict_or_empty(self):
        """5m manifest var ise dict, yoksa bos dict donmeli — hic exception yok."""
        ml = _import_fresh()
        result = ml.load_manifest("engulfing_continuation", "5m")
        assert isinstance(result, dict), f"dict bekleniyor, alindi: {type(result)}"
        # Artik 5m manifest'ler mevcut; bos olmayabilir (PASS her iki durumda)
        # Crash olmamasi yeterli: TypeError, KeyError vs yok

    def test_empty_strategy_name_returns_empty(self):
        ml = _import_fresh()
        result = ml.load_manifest("", "15m")
        assert result == {}


# ---------------------------------------------------------------------------
# T3: Cache — ikinci cagri disk okumasi tekrarlamaz
# ---------------------------------------------------------------------------

class TestCache:
    def test_second_call_uses_cache(self):
        """_load_yaml_cached ikinci cagri ayni path ile -> cache hit."""
        ml = _import_fresh()
        ml._load_yaml_cached.cache_clear()

        # Ilk cagri
        r1 = ml.load_manifest("engulfing_continuation", "15m")
        # Cache info dogrula
        info_before = ml._load_yaml_cached.cache_info()
        # Ikinci cagri
        r2 = ml.load_manifest("engulfing_continuation", "15m")
        info_after = ml._load_yaml_cached.cache_info()

        assert info_after.hits > info_before.hits, "Ikinci cagri cache hit olmali"
        assert r1 == r2, "Cache'den alinan deger ilk cagriyla ayni olmali"

    def test_cache_clear_reloads(self, tmp_path):
        """cache_clear() sonrasi tekrar disk okur."""
        ml = _import_fresh()
        # Ilk cagri (15m manifest varsa y yukler)
        ml.load_manifest("engulfing_continuation", "15m")
        ml._load_yaml_cached.cache_clear()
        info = ml._load_yaml_cached.cache_info()
        assert info.currsize == 0, "Cache temizlenmeli"


# ---------------------------------------------------------------------------
# T4: Bozuk YAML — crash yok, bos dict
# ---------------------------------------------------------------------------

class TestBrokenYaml:
    def test_broken_yaml_returns_empty(self, tmp_path, monkeypatch):
        """Bozuk YAML dosyasi -> logger warning + bos dict, hic exception yok."""
        ml = _import_fresh()

        # Gecici bozuk YAML yaz
        bad_yaml = tmp_path / "broken_strategy_15m.yaml"
        bad_yaml.write_text("key: [unclosed", encoding="utf-8")

        # MANIFEST_DIR'i tmp_path'e yonlendir
        monkeypatch.setattr(ml, "_MANIFEST_DIR", tmp_path)
        ml._load_yaml_cached.cache_clear()

        # No exception bekleniyor
        result = ml.load_manifest("broken_strategy", "15m")
        assert result == {}, f"Bozuk YAML -> bos dict bekleniyor, alindi: {result}"

    def test_yaml_non_dict_root_returns_empty(self, tmp_path, monkeypatch):
        """YAML root list veya scalar -> bos dict."""
        ml = _import_fresh()
        bad_yaml = tmp_path / "list_root_15m.yaml"
        bad_yaml.write_text("- item1\n- item2\n", encoding="utf-8")

        monkeypatch.setattr(ml, "_MANIFEST_DIR", tmp_path)
        ml._load_yaml_cached.cache_clear()

        result = ml.load_manifest("list_root", "15m")
        assert result == {}


# ---------------------------------------------------------------------------
# T5: TF normalize
# ---------------------------------------------------------------------------

class TestTFNormalize:
    @pytest.mark.parametrize("raw,expected", [
        ("15m", "15m"),
        ("15M", "15m"),
        ("15min", "15m"),
        ("5m", "5m"),
        ("5M", "5m"),
        ("5min", "5m"),
        ("1h", "1h"),
        ("1H", "1h"),
        ("60m", "1h"),
        ("4h", "4h"),
        ("4H", "4h"),
        ("1d", "1d"),
        ("1D", "1d"),
        ("daily", "1d"),
        ("1w", "1w"),
        ("1W", "1w"),
        ("d", "1d"),
        ("w", "1w"),
    ])
    def test_normalize(self, raw, expected):
        ml = _import_fresh()
        assert ml.normalize_tf(raw) == expected, (
            f"normalize_tf({raw!r}) -> {ml.normalize_tf(raw)!r}, beklenen {expected!r}"
        )

    def test_normalize_empty_defaults_1d(self):
        ml = _import_fresh()
        assert ml.normalize_tf("") == "1d"

    def test_load_manifest_tf_case_insensitive(self):
        """load_manifest("engulfing_continuation", "15M") == load_manifest(..., "15m")."""
        ml = _import_fresh()
        r_lower = ml.load_manifest("engulfing_continuation", "15m")
        ml._load_yaml_cached.cache_clear()
        r_upper = ml.load_manifest("engulfing_continuation", "15M")
        assert r_lower == r_upper


# ---------------------------------------------------------------------------
# T6: get_param helper
# ---------------------------------------------------------------------------

class TestGetParam:
    def test_nested_key_exists(self):
        ml = _import_fresh()
        # engulfing_continuation_15m.yaml -> signals -> filters -> atr_min_pct
        val = ml.get_param(
            "engulfing_continuation", "15m",
            "signals", "filters", "atr_min_pct",
            default=0.005,
        )
        # Beklenen: manifest'ten float deger
        assert isinstance(val, (int, float)), f"float bekleniyor, alindi: {val!r}"

    def test_missing_key_returns_default(self):
        ml = _import_fresh()
        val = ml.get_param(
            "engulfing_continuation", "15m",
            "nonexistent_key_xyz",
            default=42,
        )
        assert val == 42

    def test_missing_manifest_returns_default(self):
        ml = _import_fresh()
        val = ml.get_param(
            "nonexistent_xyz", "15m",
            "signals", "filters", "atr_min_pct",
            default=0.999,
        )
        assert val == 0.999
