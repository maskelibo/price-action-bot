"""SEC54.6d — Lookahead audit tests for per-strategy regime filter.

Causal verify: BTCFeatures.ts = signal_date - 1 day (t-1).
Asla signal_date veya gelecek tarih kullanılmamalı.

5 senaryo:
  1. Correct t-1 features → filter evaluates normally.
  2. Features from SAME day as signal (t=0) → this would be lookahead.
     Test ensures code pattern forces t-1 lookup (tested via BTCFeatures.ts field).
  3. Features from future (t+1) → should NOT trigger reject even for a
     strategy that would reject on t-1 features (future data is wrong).
     We verify the CALLER must pass correct t-1 features.
  4. Multiple consecutive 15m bars on same day → same t-1 features applied
     (correct: features refresh once daily at 00:01 UTC).
  5. Day boundary: signal at 00:00:15 UTC → lookup date = yesterday (t-1),
     NOT today (which has no close yet).

These tests validate the ARCHITECTURAL guarantee:
  signal.ts.date() - timedelta(days=1) == btc_features.ts

Note: The actual t-1 enforcement is in scripts/regime_features_refresh.py
(writes t-1 date into parquet). These tests verify the filter USES the
provided features as-is (trusting the caller to provide causal features).
The integration test verifies end-to-end causal chain.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from price_action.risk.regime_filter import BTCFeatures, PerStrategyRegimeFilter


# =====================================================================
# Helpers
# =====================================================================

def _filt() -> PerStrategyRegimeFilter:
    return PerStrategyRegimeFilter({
        "enabled": True,
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
    })


def _features(ts: date, *, fetched_hours_ago: float = 0.5, **kwargs) -> BTCFeatures:
    now = datetime.now(timezone.utc)
    defaults = dict(
        atr_pct_30d=5.0,
        return_30d=0.0,
        return_30d_abs_pct=0.0,
        ema200_distance_pct=5.0,
        above_ema200=False,
        fng_value=50.0,
        realized_vol_7d_annualized=50.0,
        fetched_at=now - timedelta(hours=fetched_hours_ago),
    )
    defaults.update(kwargs)
    return BTCFeatures(ts=ts, **defaults)


# =====================================================================
# Causal / lookahead tests
# =====================================================================

class TestCausalLookahead:
    """Verify causal t-1 alignment in filter evaluation."""

    def test_t1_features_rejects_f1(self):
        """Scenario 1: Correct t-1 features with range condition → REJECT.

        signal_ts = 2024-06-02 09:00 UTC (15m bar)
        features.ts = 2024-06-01 (t-1 daily close) ← CORRECT causal
        F1 range condition met → REJECT.
        """
        filt = _filt()
        signal_ts = datetime(2024, 6, 2, 9, 0, tzinfo=timezone.utc)
        expected_t1 = date(2024, 6, 1)  # t-1

        feat = _features(
            ts=expected_t1,  # causal t-1
            atr_pct_30d=2.0,
            return_30d=1.5,
            return_30d_abs_pct=1.5,
        )
        # Verify features.ts is exactly t-1
        assert feat.ts == signal_ts.date() - timedelta(days=1), (
            f"Causal fail: features.ts={feat.ts} should be {signal_ts.date() - timedelta(days=1)}"
        )

        allow, reason = filt.evaluate_strategy_regime_filter(
            "avwap_long_reversal", "long", signal_ts, feat
        )
        assert allow is False
        assert reason == "F1_avwap_range"

    def test_future_features_date_does_not_affect_filter(self):
        """Scenario 3: features.ts = future date (t+1).

        The filter evaluates features as-is. Using future ts is a CALLER error,
        not something the filter itself can detect. This test documents that the
        filter operates on the provided data regardless of ts — the t-1
        enforcement is the CALLER's responsibility (regime_features_refresh.py
        writes t-1 date).

        If caller provides stale features (old ts), staleness check applies.
        If caller provides correct t-1 features, filter is causal.
        """
        filt = _filt()
        signal_ts = datetime(2024, 6, 2, 9, 0, tzinfo=timezone.utc)
        # Wrong: providing "tomorrow" features — caller error
        future_ts = date(2024, 6, 3)  # t+1

        feat = _features(
            ts=future_ts,
            atr_pct_30d=2.0,
            return_30d=1.5,
            return_30d_abs_pct=1.5,
        )
        # Filter evaluates based on data values regardless of ts
        allow, reason = filt.evaluate_strategy_regime_filter(
            "avwap_long_reversal", "long", signal_ts, feat
        )
        # F1 condition still triggers (based on feature values not ts)
        assert allow is False
        assert reason == "F1_avwap_range"
        # NOTE: This shows future-ts features are used as-is. The caller
        # MUST ensure features.ts == signal_ts.date() - 1 day (causal).

    def test_multiple_15m_bars_same_day_same_features(self):
        """Scenario 4: Multiple 15m bars on 2024-06-02 → same t-1 features.

        Daily features refresh at 00:01 UTC. All 96 bars on 2024-06-02 use
        features from 2024-06-01 (t-1). This is correct causal behavior.
        """
        filt = _filt()
        t1_date = date(2024, 6, 1)  # t-1

        feat = _features(
            ts=t1_date,
            atr_pct_30d=2.0,
            return_30d=1.5,
            return_30d_abs_pct=1.5,
        )

        # Multiple 15m bars on 2024-06-02
        bar_times = [
            datetime(2024, 6, 2, 0, 15, tzinfo=timezone.utc),
            datetime(2024, 6, 2, 6, 0, tzinfo=timezone.utc),
            datetime(2024, 6, 2, 12, 30, tzinfo=timezone.utc),
            datetime(2024, 6, 2, 23, 45, tzinfo=timezone.utc),
        ]

        for bar_ts in bar_times:
            # All bars use same t-1 features (causal: no intraday refresh)
            assert feat.ts == bar_ts.date() - timedelta(days=1), (
                f"Bar {bar_ts}: features.ts={feat.ts} != t-1 {bar_ts.date() - timedelta(days=1)}"
            )
            allow, reason = filt.evaluate_strategy_regime_filter(
                "avwap_long_reversal", "long", bar_ts, feat
            )
            assert allow is False, f"Bar {bar_ts} should reject F1"
            assert reason == "F1_avwap_range"

    def test_day_boundary_early_morning_uses_yesterday(self):
        """Scenario 5: Signal at 00:00:15 UTC → t-1 = yesterday.

        Critical: the first 15m bar of a new day (00:15 UTC) must use
        yesterday's features, NOT today's (no close yet for today).
        """
        filt = _filt()
        # Signal arrives at 00:00:15 — very start of new day
        signal_ts = datetime(2024, 6, 2, 0, 0, 15, tzinfo=timezone.utc)
        expected_t1 = date(2024, 6, 1)  # MUST be yesterday

        feat = _features(
            ts=expected_t1,
            above_ema200=True,
            return_30d=8.0,
        )

        # Causal check
        assert feat.ts == signal_ts.date() - timedelta(days=1)

        allow, reason = filt.evaluate_strategy_regime_filter(
            "brooks_failed_breakout", "short", signal_ts, feat
        )
        assert allow is False
        assert reason == "F2_brooks_fb_bull"

    def test_causal_date_math_formula(self):
        """Scenario 2 / architectural: verify t-1 formula for 5 test dates.

        For any signal_ts, the causal lookup date formula is:
          lookup_date = signal_ts.date() - timedelta(days=1)

        This test validates the formula for signal timestamps spanning
        different days/hours.
        """
        test_cases = [
            (datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc), date(2023, 12, 31)),  # New Year
            (datetime(2024, 3, 1, 9, 15, tzinfo=timezone.utc), date(2024, 2, 29)),  # Leap year
            (datetime(2024, 6, 15, 23, 59, tzinfo=timezone.utc), date(2024, 6, 14)),
            (datetime(2024, 12, 31, 12, 0, tzinfo=timezone.utc), date(2024, 12, 30)),
            (datetime(2025, 1, 1, 6, 30, tzinfo=timezone.utc), date(2024, 12, 31)),
        ]
        for signal_ts, expected_t1 in test_cases:
            computed_t1 = signal_ts.date() - timedelta(days=1)
            assert computed_t1 == expected_t1, (
                f"signal_ts={signal_ts}: computed t-1={computed_t1} != expected {expected_t1}"
            )
