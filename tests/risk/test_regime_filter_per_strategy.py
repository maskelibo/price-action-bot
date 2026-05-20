"""SEC54.6d — Per-strategy regime filter unit tests.

Tests PerStrategyRegimeFilter.evaluate_strategy_regime_filter() with all 4
filter scenarios (F1-F4), edge cases, and fail-safe behavior.

Pre-reg: memory/researcher/hypotheses/2026-05-18-regime-conditional-filters.md
Researcher report: reports/researcher/2026-05-19_sec54_6d_regime_filter.md
Backtest result: annual +1935.9% / neg 8/61 / mandate 5/5.

Filter reference (pre-reg thresholds, NOT tuned post-hoc):
  F1: anchored_vwap_reversal BOTH: ATR%<3.0 AND |ret30|<3.0 → SKIP
  F2: brooks_failed_breakout SHORT: above_ema200 AND ret30>+5.0 → SKIP
  F3: vsa_climax_test LONG: fng<15 AND ret30<-10.0 → SKIP
  F4: engulfing_continuation BOTH: vol7d_ann>100.0 → SKIP
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from price_action.risk.regime_filter import BTCFeatures, PerStrategyRegimeFilter


# =====================================================================
# Helpers
# =====================================================================

def _make_features(
    *,
    ts: date | None = None,
    atr_pct_30d: float = 5.0,       # default: NOT range (>3)
    return_30d: float = 0.0,
    return_30d_abs_pct: float | None = None,
    ema200_distance_pct: float = 5.0,
    above_ema200: bool = False,
    fng_value: float = 50.0,
    realized_vol_7d_annualized: float = 50.0,  # default: NOT high-vol (<100)
    fetched_at: datetime | None = None,
    age_hours: float = 0.0,         # fetched_at = now - age_hours
) -> BTCFeatures:
    """Build a BTCFeatures snapshot for testing."""
    now = datetime.now(timezone.utc)
    if fetched_at is None:
        fetched_at = now - timedelta(hours=age_hours)
    if ts is None:
        ts = (now - timedelta(days=1)).date()
    if return_30d_abs_pct is None:
        return_30d_abs_pct = abs(return_30d)
    return BTCFeatures(
        ts=ts,
        atr_pct_30d=atr_pct_30d,
        return_30d=return_30d,
        return_30d_abs_pct=return_30d_abs_pct,
        ema200_distance_pct=ema200_distance_pct,
        above_ema200=above_ema200,
        fng_value=fng_value,
        realized_vol_7d_annualized=realized_vol_7d_annualized,
        fetched_at=fetched_at,
    )


def _make_filter(enabled: bool = True, **overrides) -> PerStrategyRegimeFilter:
    """Build PerStrategyRegimeFilter with default pre-reg thresholds."""
    cfg = {
        "enabled": enabled,
        "features_max_age_hours": 24,
        "filters": {
            "F1_avwap_range": {
                "btc_atr_pct_lt": 3.0,
                "btc_return_30d_abs_lt_pct": 3.0,
            },
            "F2_brooks_fb_bull": {
                "btc_ema200_above": True,
                "btc_return_30d_gt_pct": 5.0,
            },
            "F3_vsa_bear": {
                "btc_fng_lt": 15.0,
                "btc_return_30d_lt_pct": -10.0,
            },
            "F4_engulfing_high_vol": {
                "btc_realized_vol_7d_annualized_gt_pct": 100.0,
            },
        },
    }
    cfg.update(overrides)
    return PerStrategyRegimeFilter(cfg)


_NOW_TS = datetime(2024, 6, 2, 9, 0, tzinfo=timezone.utc)  # 15m bar signal time


# =====================================================================
# F1: anchored_vwap_reversal — range rejim skip
# =====================================================================

class TestF1AvwapRange:
    """F1: anchored_vwap_reversal BOTH sides — range condition."""

    def test_f1_range_long_rejects(self):
        """F1 PASS: AVWAP LONG in range piyasa → REJECT."""
        filt = _make_filter()
        feat = _make_features(atr_pct_30d=2.5, return_30d=1.5)  # ATR<3, |ret|<3
        allow, reason = filt.evaluate_strategy_regime_filter(
            "avwap_long_reversal", "long", _NOW_TS, feat
        )
        assert allow is False
        assert reason == "F1_avwap_range"

    def test_f1_range_short_rejects(self):
        """F1 PASS: AVWAP SHORT in range piyasa → REJECT."""
        filt = _make_filter()
        feat = _make_features(atr_pct_30d=2.0, return_30d=-2.0)  # ATR<3, |ret|<3
        allow, reason = filt.evaluate_strategy_regime_filter(
            "avwap_short_reversal", "short", _NOW_TS, feat
        )
        assert allow is False
        assert reason == "F1_avwap_range"

    def test_f1_trend_allows(self):
        """F1 FAIL: AVWAP in trend piyasa → ALLOW."""
        filt = _make_filter()
        feat = _make_features(atr_pct_30d=4.5, return_30d=12.0)  # ATR>=3, |ret|>=3
        allow, reason = filt.evaluate_strategy_regime_filter(
            "avwap_long_reversal", "long", _NOW_TS, feat
        )
        assert allow is True
        assert reason is None

    def test_f1_atr_above_threshold_allows(self):
        """F1 FAIL: ATR>=3 even if ret small → ALLOW (AND condition)."""
        filt = _make_filter()
        feat = _make_features(atr_pct_30d=3.5, return_30d=1.0)  # ATR>=3 → no range
        allow, reason = filt.evaluate_strategy_regime_filter(
            "avwap_long_reversal", "long", _NOW_TS, feat
        )
        assert allow is True

    def test_f1_ret_above_threshold_allows(self):
        """F1 FAIL: |ret|>=3 even if ATR small → ALLOW (AND condition)."""
        filt = _make_filter()
        feat = _make_features(atr_pct_30d=2.0, return_30d=5.0)  # |ret|>=3 → not flat
        allow, reason = filt.evaluate_strategy_regime_filter(
            "avwap_long_reversal", "long", _NOW_TS, feat
        )
        assert allow is True


# =====================================================================
# F2: brooks_failed_breakout — SHORT only — strong bull skip
# =====================================================================

class TestF2BrooksFbBull:
    """F2: brooks_failed_breakout SHORT — bull condition."""

    def test_f2_short_bull_rejects(self):
        """F2 PASS: brooks_fb SHORT in bull → REJECT."""
        filt = _make_filter()
        feat = _make_features(above_ema200=True, return_30d=8.0)  # above + ret>5
        allow, reason = filt.evaluate_strategy_regime_filter(
            "brooks_failed_breakout", "short", _NOW_TS, feat
        )
        assert allow is False
        assert reason == "F2_brooks_fb_bull"

    def test_f2_short_bear_allows(self):
        """F2 FAIL: brooks_fb SHORT in bear → ALLOW."""
        filt = _make_filter()
        feat = _make_features(above_ema200=False, return_30d=-5.0)  # below + ret<5
        allow, reason = filt.evaluate_strategy_regime_filter(
            "brooks_failed_breakout", "short", _NOW_TS, feat
        )
        assert allow is True
        assert reason is None

    def test_f2_long_bull_allows(self):
        """F2 FAIL-2: brooks_fb LONG in bull → ALLOW (F2 only blocks SHORT)."""
        filt = _make_filter()
        feat = _make_features(above_ema200=True, return_30d=10.0)
        allow, reason = filt.evaluate_strategy_regime_filter(
            "brooks_failed_breakout", "long", _NOW_TS, feat
        )
        assert allow is True
        assert reason is None

    def test_f2_short_below_ema200_allows(self):
        """F2 FAIL: below EMA200 even if ret>5 → ALLOW (AND condition)."""
        filt = _make_filter()
        feat = _make_features(above_ema200=False, return_30d=7.0)
        allow, reason = filt.evaluate_strategy_regime_filter(
            "brooks_failed_breakout", "short", _NOW_TS, feat
        )
        assert allow is True

    def test_f2_short_ret_below_threshold_allows(self):
        """F2 FAIL: above EMA200 but ret<5 → ALLOW (AND condition)."""
        filt = _make_filter()
        feat = _make_features(above_ema200=True, return_30d=3.0)
        allow, reason = filt.evaluate_strategy_regime_filter(
            "brooks_failed_breakout", "short", _NOW_TS, feat
        )
        assert allow is True


# =====================================================================
# F3: vsa_climax_test — LONG only — deep bear capitulation skip
# =====================================================================

class TestF3VsaBear:
    """F3: vsa_climax_test LONG — deep bear condition."""

    def test_f3_long_deep_bear_rejects(self):
        """F3 PASS: vsa LONG in deep bear → REJECT."""
        filt = _make_filter()
        feat = _make_features(fng_value=10.0, return_30d=-15.0)  # fng<15, ret<-10
        allow, reason = filt.evaluate_strategy_regime_filter(
            "vsa_climax_test", "long", _NOW_TS, feat
        )
        assert allow is False
        assert reason == "F3_vsa_bear"

    def test_f3_long_mild_fear_allows(self):
        """F3 FAIL: vsa LONG with moderate fear → ALLOW."""
        filt = _make_filter()
        feat = _make_features(fng_value=25.0, return_30d=-8.0)  # fng>=15 or ret>-10
        allow, reason = filt.evaluate_strategy_regime_filter(
            "vsa_climax_test", "long", _NOW_TS, feat
        )
        assert allow is True
        assert reason is None

    def test_f3_short_deep_bear_allows(self):
        """F3 FAIL: vsa SHORT in deep bear → ALLOW (F3 only blocks LONG)."""
        filt = _make_filter()
        feat = _make_features(fng_value=5.0, return_30d=-20.0)
        allow, reason = filt.evaluate_strategy_regime_filter(
            "vsa_climax_test", "short", _NOW_TS, feat
        )
        assert allow is True

    def test_f3_long_fng_missing_allows(self):
        """F3 FAIL-SAFE: fng_value=-1 (missing data) → ALLOW."""
        filt = _make_filter()
        feat = _make_features(fng_value=-1.0, return_30d=-20.0)  # sentinel
        allow, reason = filt.evaluate_strategy_regime_filter(
            "vsa_climax_test", "long", _NOW_TS, feat
        )
        assert allow is True

    def test_f3_fng_above_threshold_allows(self):
        """F3 FAIL: fng>=15 even if ret<-10 → ALLOW (AND condition)."""
        filt = _make_filter()
        feat = _make_features(fng_value=20.0, return_30d=-15.0)
        allow, reason = filt.evaluate_strategy_regime_filter(
            "vsa_climax_test", "long", _NOW_TS, feat
        )
        assert allow is True

    def test_f3_ret_above_threshold_allows(self):
        """F3 FAIL: ret>-10 even if fng<15 → ALLOW (AND condition)."""
        filt = _make_filter()
        feat = _make_features(fng_value=5.0, return_30d=-5.0)
        allow, reason = filt.evaluate_strategy_regime_filter(
            "vsa_climax_test", "long", _NOW_TS, feat
        )
        assert allow is True


# =====================================================================
# F4: engulfing_continuation — both sides — extreme vol skip
# =====================================================================

class TestF4EngulfingHighVol:
    """F4: engulfing_continuation BOTH sides — extreme vol condition."""

    def test_f4_high_vol_long_rejects(self):
        """F4 PASS: engulfing LONG in extreme vol → REJECT."""
        filt = _make_filter()
        feat = _make_features(realized_vol_7d_annualized=120.0)  # >100
        allow, reason = filt.evaluate_strategy_regime_filter(
            "engulfing_continuation", "long", _NOW_TS, feat
        )
        assert allow is False
        assert reason == "F4_engulfing_high_vol"

    def test_f4_high_vol_short_rejects(self):
        """F4 PASS: engulfing SHORT in extreme vol → REJECT."""
        filt = _make_filter()
        feat = _make_features(realized_vol_7d_annualized=150.0)
        allow, reason = filt.evaluate_strategy_regime_filter(
            "engulfing_continuation", "short", _NOW_TS, feat
        )
        assert allow is False
        assert reason == "F4_engulfing_high_vol"

    def test_f4_normal_vol_allows(self):
        """F4 FAIL: engulfing in normal vol → ALLOW."""
        filt = _make_filter()
        feat = _make_features(realized_vol_7d_annualized=60.0)  # <100
        allow, reason = filt.evaluate_strategy_regime_filter(
            "engulfing_continuation", "long", _NOW_TS, feat
        )
        assert allow is True
        assert reason is None

    def test_f4_at_threshold_allows(self):
        """F4 boundary: vol exactly at threshold → ALLOW (not strictly greater)."""
        filt = _make_filter()
        feat = _make_features(realized_vol_7d_annualized=100.0)
        allow, reason = filt.evaluate_strategy_regime_filter(
            "engulfing_continuation", "long", _NOW_TS, feat
        )
        assert allow is True


# =====================================================================
# Fail-safe / edge cases
# =====================================================================

class TestFailSafe:
    """Stale features, missing data, disabled filter."""

    def test_disabled_filter_always_allows(self):
        """enabled=False → ALLOW for any strategy/condition."""
        filt = _make_filter(enabled=False)
        # F3 deep bear condition — should still allow
        feat = _make_features(fng_value=5.0, return_30d=-20.0)
        allow, reason = filt.evaluate_strategy_regime_filter(
            "vsa_climax_test", "long", _NOW_TS, feat
        )
        assert allow is True
        assert reason is None

    def test_none_features_allows(self):
        """BTCFeatures=None → fail-safe ALLOW."""
        filt = _make_filter()
        allow, reason = filt.evaluate_strategy_regime_filter(
            "avwap_long_reversal", "long", _NOW_TS, None
        )
        assert allow is True
        assert reason is None

    def test_stale_features_allows(self):
        """Features age > 24h → fail-safe ALLOW (stale data)."""
        filt = _make_filter()
        # Build features that would trigger F1, but make them stale
        feat = _make_features(
            atr_pct_30d=2.0, return_30d=1.0,
            age_hours=25.0,  # > 24h max_age
        )
        allow, reason = filt.evaluate_strategy_regime_filter(
            "avwap_long_reversal", "long", _NOW_TS, feat
        )
        assert allow is True
        assert reason is None

    def test_unknown_strategy_allows(self):
        """Unknown strategy not in any filter → ALLOW."""
        filt = _make_filter()
        feat = _make_features(
            atr_pct_30d=1.0,
            return_30d=-20.0,
            return_30d_abs_pct=20.0,
            fng_value=5.0,
            above_ema200=True,
            realized_vol_7d_annualized=200.0,
        )
        allow, reason = filt.evaluate_strategy_regime_filter(
            "some_other_strategy", "long", _NOW_TS, feat
        )
        assert allow is True

    def test_pattern_id_prefix_resolution_avwap(self):
        """Signal.pattern_id prefix → strategy name resolution (anchored_vwap)."""
        filt = _make_filter()
        feat = _make_features(atr_pct_30d=2.0, return_30d=1.5)
        # pattern_id = "avwap_long_reversal" → resolves to "anchored_vwap_reversal"
        allow, reason = filt.evaluate_strategy_regime_filter(
            "avwap_long_reversal", "long", _NOW_TS, feat
        )
        assert allow is False
        assert reason == "F1_avwap_range"

    def test_pattern_id_prefix_resolution_brooks(self):
        """Signal.pattern_id prefix → strategy name resolution (brooks_fb)."""
        filt = _make_filter()
        feat = _make_features(above_ema200=True, return_30d=9.0)
        # pattern_id = "brooks_failed_breakout" → resolves directly
        allow, reason = filt.evaluate_strategy_regime_filter(
            "brooks_failed_breakout", "short", _NOW_TS, feat
        )
        assert allow is False
        assert reason == "F2_brooks_fb_bull"

    def test_all_filters_combo_worst_case_allows_unaffected_strategy(self):
        """Combo extreme condition: non-filtered strategy → ALLOW regardless."""
        filt = _make_filter()
        feat = _make_features(
            atr_pct_30d=1.0,
            return_30d=15.0,
            return_30d_abs_pct=15.0,
            above_ema200=True,
            fng_value=5.0,
            realized_vol_7d_annualized=200.0,
        )
        allow, reason = filt.evaluate_strategy_regime_filter(
            "pin_bar_round_numbers", "long", _NOW_TS, feat
        )
        assert allow is True
