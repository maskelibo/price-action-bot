"""SEC-S1: Regime-conditional daily DD unit tests.

5 test:
  1. Default OFF → sabit daily_pct (backward-compat)
  2. Persantil <= regime_percentile_low → base threshold (normal rejim)
  3. Persantil >= regime_percentile_high → volatile threshold (full multiplier)
  4. Blend smooth (percentile 75 → arası, no cliff)
  5. Calendar missing / None → conservative fallback (sabit daily_pct)

DDBreaker._get_dynamic_daily_threshold doğrudan test edilir (lab._effective_daily_dd
ile aynı mantık). ProductionConfig._effective_daily_dd ayrı parametrik test edilir.
"""
from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from price_action.risk.breaker import DDBreaker
from price_action.backtest.lab import ProductionConfig, _effective_daily_dd


# ===================================================================
# Fixtures
# ===================================================================

BASE_DATE = date(2024, 6, 15)
T0 = datetime(2024, 6, 15, 12, 0, tzinfo=timezone.utc)

# Minimal config — sadece daily breaker parametreleri
REGIME_OFF_CFG = {
    "daily_loss_pct": 0.03,
    "weekly_loss_pct": 0.99,
    "monthly_loss_pct": 0.99,
    "consecutive_losses": 99,
    "daily_loss_pct_regime_aware": False,
}

REGIME_ON_CFG = {
    "daily_loss_pct": 0.03,
    "weekly_loss_pct": 0.99,
    "monthly_loss_pct": 0.99,
    "consecutive_losses": 99,
    "daily_loss_pct_regime_aware": True,
    "daily_loss_pct_volatile_multiplier": 2.0,
    "regime_percentile_low": 60,   # YAML girişi tamsayı (÷100 yapılır)
    "regime_percentile_high": 90,
}


def _make_breaker(cfg: dict, calendar: dict | None, tmp_path) -> DDBreaker:
    """DDBreaker oluşturur, sonra calendar'ı inject eder (test izolayon)."""
    br = DDBreaker(cfg, state_path=tmp_path / "br.json")
    br._btc_atr_percentile_calendar = calendar
    return br


def _make_cfg_with_calendar(calendar: dict | None) -> ProductionConfig:
    """ProductionConfig oluşturur, btc_atr_percentile_calendar inject eder."""
    cfg = ProductionConfig(
        daily_dd=0.03,
        daily_dd_regime_aware=True,
        daily_dd_volatile_multiplier=2.0,
        regime_percentile_low=0.60,   # ProductionConfig float (0-1)
        regime_percentile_high=0.90,
        btc_atr_percentile_calendar=calendar,
    )
    return cfg


# ===================================================================
# Test 1: Default OFF → sabit daily_pct (backward-compat)
# ===================================================================

def test_regime_off_returns_base_threshold(tmp_path):
    """regime_aware=False → _get_dynamic_daily_threshold daima cfg.daily_pct döner.

    Calendar olsa bile ignore edilir.
    """
    calendar = {BASE_DATE: 0.99}  # extreme volatile persantil — ama feature OFF
    br = _make_breaker(REGIME_OFF_CFG, calendar, tmp_path)

    result = br._get_dynamic_daily_threshold(T0)
    assert result == pytest.approx(0.03), (
        f"Feature OFF iken beklenen 0.03, gelen {result}"
    )

    # ProductionConfig seviyesinde de test
    cfg = ProductionConfig(daily_dd=0.03, daily_dd_regime_aware=False)
    assert _effective_daily_dd(cfg, BASE_DATE) == pytest.approx(0.03)


# ===================================================================
# Test 2: Persantil <= %60 → base threshold (normal rejim)
# ===================================================================

def test_low_percentile_returns_base_threshold(tmp_path):
    """Persantil <= regime_percentile_low → sakin rejim, base threshold."""
    # Persantil %50 (sakin)
    calendar = {BASE_DATE: 0.50}
    br = _make_breaker(REGIME_ON_CFG, calendar, tmp_path)

    result = br._get_dynamic_daily_threshold(T0)
    assert result == pytest.approx(0.03), (
        f"Persantil 0.50 <= 0.60 → base 0.03 bekleniyor, gelen {result}"
    )

    # Sınır değer: tam 0.60
    calendar_at_boundary = {BASE_DATE: 0.60}
    br2 = _make_breaker(REGIME_ON_CFG, calendar_at_boundary, tmp_path)
    result2 = br2._get_dynamic_daily_threshold(T0)
    assert result2 == pytest.approx(0.03)

    # ProductionConfig seviyesinde de test
    cfg = _make_cfg_with_calendar({BASE_DATE: 0.50})
    assert _effective_daily_dd(cfg, BASE_DATE) == pytest.approx(0.03)


# ===================================================================
# Test 3: Persantil >= %90 → volatile threshold (full multiplier)
# ===================================================================

def test_high_percentile_returns_volatile_threshold(tmp_path):
    """Persantil >= regime_percentile_high → volatile rejim, eşik ×2."""
    # Persantil %95 (çok volatil)
    calendar = {BASE_DATE: 0.95}
    br = _make_breaker(REGIME_ON_CFG, calendar, tmp_path)

    result = br._get_dynamic_daily_threshold(T0)
    expected = 0.03 * 2.0  # = 0.06
    assert result == pytest.approx(expected), (
        f"Persantil 0.95 >= 0.90 → volatile 0.06 bekleniyor, gelen {result}"
    )

    # Sınır değer: tam 0.90
    calendar_at_boundary = {BASE_DATE: 0.90}
    br2 = _make_breaker(REGIME_ON_CFG, calendar_at_boundary, tmp_path)
    result2 = br2._get_dynamic_daily_threshold(T0)
    assert result2 == pytest.approx(0.06)

    # ProductionConfig seviyesinde de test
    cfg = _make_cfg_with_calendar({BASE_DATE: 0.95})
    assert _effective_daily_dd(cfg, BASE_DATE) == pytest.approx(0.06)


# ===================================================================
# Test 4: Blend smooth (persantil 75 → arası, cliff yok)
# ===================================================================

def test_mid_percentile_smooth_blend(tmp_path):
    """Persantil %75 (regime_percentile_low=60, high=90) → linear blend.

    blend = (0.75 - 0.60) / (0.90 - 0.60) = 0.15 / 0.30 = 0.5
    threshold = 0.03 + 0.5 * (0.06 - 0.03) = 0.03 + 0.015 = 0.045
    """
    calendar = {BASE_DATE: 0.75}
    br = _make_breaker(REGIME_ON_CFG, calendar, tmp_path)

    result = br._get_dynamic_daily_threshold(T0)
    expected = 0.03 + 0.5 * (0.06 - 0.03)  # = 0.045
    assert result == pytest.approx(expected, abs=1e-9), (
        f"Persantil 0.75 → blend 0.045 bekleniyor, gelen {result}"
    )

    # Monotonluk: persantil arttıkça eşik artar (no cliff)
    percentiles = [0.0, 0.30, 0.60, 0.70, 0.75, 0.80, 0.90, 0.95, 1.0]
    thresholds = []
    for p in percentiles:
        cal = {BASE_DATE: p}
        br_t = _make_breaker(REGIME_ON_CFG, cal, tmp_path)
        thresholds.append(br_t._get_dynamic_daily_threshold(T0))

    for i in range(len(thresholds) - 1):
        assert thresholds[i] <= thresholds[i + 1] + 1e-12, (
            f"Monotonluk ihlali: p={percentiles[i]} → {thresholds[i]}, "
            f"p={percentiles[i+1]} → {thresholds[i+1]}"
        )


# ===================================================================
# Test 5: Calendar missing / None → conservative fallback (sabit daily_pct)
# ===================================================================

def test_missing_calendar_falls_back_to_base(tmp_path):
    """Calendar None veya tarih bulunamazsa → sabit daily_pct (conservative)."""
    # Calendar None
    br_none = _make_breaker(REGIME_ON_CFG, None, tmp_path)
    assert br_none._get_dynamic_daily_threshold(T0) == pytest.approx(0.03)

    # Calendar var ama tarih yok (farklı gün)
    different_date = date(2023, 1, 1)
    calendar_no_entry = {different_date: 0.95}
    br_miss = _make_breaker(REGIME_ON_CFG, calendar_no_entry, tmp_path)
    assert br_miss._get_dynamic_daily_threshold(T0) == pytest.approx(0.03)

    # ProductionConfig seviyesinde de test
    cfg_none = _make_cfg_with_calendar(None)
    assert _effective_daily_dd(cfg_none, BASE_DATE) == pytest.approx(0.03)

    cfg_miss = _make_cfg_with_calendar({different_date: 0.95})
    assert _effective_daily_dd(cfg_miss, BASE_DATE) == pytest.approx(0.03)
