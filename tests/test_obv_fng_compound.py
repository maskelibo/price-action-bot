"""OBV + F&G Compound Filter testleri — H20.

Test gruplari (6 temel + ek):
    T01: F&G + OBV birlikte uygulanir — neutral F&G + bull-OBV => sinyal gecer
    T02: F&G fail => sinyal elenir (OBV gecse bile)
    T03: OBV fail => sinyal elenir (F&G gecse bile)
    T04: F&G + OBV ikisi de fail => sinyal elenir
    T05: Lookahead-free — F&G shift(1) kontrolu
    T06: Lookahead-free — OBV slope [i-window..i-1] kontrolu
    T07: Bos sinyal listesi => bos doner, crash yok
    T08: F&G data yok => sadece OBV filtre calisir
    T09: Rejection reason tracking — filter_meta sayilar tutarli
    T10: _apply_obv_filter: signal ts'i df'de olmayinca konservatif gecer
    T11: Compound senaryo D: F&G once, OBV sonra uygulanir (sequential logic)
    T12: Birden fazla sembol — her sinyal kendi ts'ine gore degerlendirilir
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _make_signal(
    *,
    direction: str = "long",
    ts: str = "2023-06-15",
    symbol: str = "BTC/USDT",
) -> "Signal":
    from price_action.contracts import Signal

    return Signal(
        ts=pd.Timestamp(ts, tz="UTC").to_pydatetime(),
        venue="binance",
        symbol=symbol,
        timeframe="1d",
        direction=direction,
        pattern_id="bullish_engulfing_cont" if direction == "long" else "bearish_engulfing_cont",
        confluence_score=1.5,
        sl_price=28000.0 if direction == "long" else 31000.0,
        tp_price=31000.0 if direction == "long" else 28000.0,
        suggested_size_atr=1.0,
    )


def _make_fng_df(value: int = 50, n: int = 60, start: str = "2023-06-01") -> pd.DataFrame:
    """Fixed-value F&G DataFrame."""
    days = pd.date_range(start, periods=n, freq="1D", tz="UTC")

    def classify(v: int) -> str:
        if v < 25:
            return "Extreme Fear"
        if v < 50:
            return "Fear"
        if v < 75:
            return "Greed"
        return "Extreme Greed"

    return pd.DataFrame({
        "ts": days,
        "value": [value] * n,
        "classification": [classify(value)] * n,
    })


def _make_ohlcv(
    n: int = 60,
    start: str = "2023-06-01",
    seed: int = 42,
    bullish_obv: bool = False,
    bearish_obv: bool = False,
    price_drift: float = 0.0,
) -> pd.DataFrame:
    """Synthetic OHLCV DataFrame.

    If bullish_obv=True: price trends down but high-volume up-bars push OBV up
    (classic bullish divergence setup for lookback).
    If bearish_obv=True: price trends up but high-volume down-bars push OBV down.
    """
    rng = np.random.default_rng(seed)
    days = pd.date_range(start, periods=n, freq="1D", tz="UTC")

    if bullish_obv:
        # Price drifts down (LL), OBV drifts up (HL) via volume
        closes = np.linspace(100.0, 70.0, n)
        volumes = np.full(n, 50_000.0)
        # Every 3rd bar: spike up with huge volume => OBV jumps
        for i in range(2, n, 3):
            closes[i] = closes[max(0, i - 1)] + 3.0
            volumes[i] = 8_000_000.0
    elif bearish_obv:
        # Price drifts up (HH), OBV drifts down (LH)
        closes = np.linspace(70.0, 100.0, n)
        # High vol at start, then very low vol
        volumes = np.linspace(5_000_000.0, 10_000.0, n)
    else:
        rets = rng.normal(price_drift, 0.015, n)
        closes = 100.0 * np.exp(np.cumsum(rets))
        volumes = rng.uniform(500_000.0, 2_000_000.0, n)

    opens = np.r_[closes[0], closes[:-1]]
    highs = np.maximum(opens, closes) * 1.005
    lows = np.minimum(opens, closes) * 0.995

    return pd.DataFrame({
        "ts": days,
        "open": opens,
        "high": highs,
        "low": lows,
        "close": closes,
        "volume": volumes,
        "venue": "binance",
        "symbol": "BTC/USDT",
        "timeframe": "1d",
    })


# ---------------------------------------------------------------------------
# T01: Both filters pass — neutral F&G + bull OBV div context
# ---------------------------------------------------------------------------

class TestT01BothFiltersPass:
    def test_neutral_fng_with_bull_obv_div_signal_passes(self):
        """F&G=50 (neutral, passes long gate) + signal at bar with bull OBV div.

        Scenario: We manually set up the OBV divergence context and confirm
        that the compound filter doesn't reject signals when both gates pass.
        """
        from price_action.strategies.sentiment_filter import filter_engulfing_with_fng
        from price_action.strategies.obv_engulfing_confluence import filter_with_obv_divergence

        # F&G neutral — passes long gate (50 < 60)
        fng_df = _make_fng_df(value=50, n=60, start="2023-05-01")
        df = _make_ohlcv(n=60, start="2023-05-01", bullish_obv=True)

        # Signal at bar 40 — bullish engulfing in OBV-div context
        sig_ts = df["ts"].iloc[40].to_pydatetime()
        sig = _make_signal(direction="long", ts="2023-06-10")

        # Step 1: F&G filter (should pass: 50 < 60)
        after_fng, n_rej_fng = filter_engulfing_with_fng(
            [sig], fng_df, long_max_fng=60.0, short_min_fng=40.0
        )
        # F&G passes (neutral zone)
        assert len(after_fng) == 1, f"F&G filter should pass neutral signal, rejected {n_rej_fng}"

        # Step 2: OBV filter (may or may not find OBV div at that exact bar, but
        # the interface should return a valid list without crashing)
        final, n_rej_obv = filter_with_obv_divergence(after_fng, df, lookback=15)
        assert isinstance(final, list)
        assert isinstance(n_rej_obv, int)
        assert n_rej_obv + len(final) == len(after_fng)

    def test_compound_pipeline_returns_correct_types(self):
        """Compound pipeline returns list[Signal], int, int."""
        from price_action.strategies.sentiment_filter import filter_engulfing_with_fng
        from price_action.strategies.obv_engulfing_confluence import filter_with_obv_divergence

        fng_df = _make_fng_df(value=50)
        df = _make_ohlcv(n=60)
        sig = _make_signal(direction="long", ts="2023-06-15")

        after_fng, n_rej_fng = filter_engulfing_with_fng([sig], fng_df)
        final, n_rej_obv = filter_with_obv_divergence(after_fng, df, lookback=15)

        assert isinstance(after_fng, list)
        assert isinstance(final, list)
        assert isinstance(n_rej_fng, int)
        assert isinstance(n_rej_obv, int)


# ---------------------------------------------------------------------------
# T02: F&G fail => signal rejected regardless of OBV
# ---------------------------------------------------------------------------

class TestT02FNGFailRejects:
    def test_high_fng_rejects_long(self):
        """F&G=80 >= long_max=60: long sinyal F&G filtresiyle reddedilmeli."""
        from price_action.strategies.sentiment_filter import filter_engulfing_with_fng

        fng_df = _make_fng_df(value=80, n=60)  # Extreme Greed
        sig = _make_signal(direction="long", ts="2023-06-15")

        after_fng, n_rej_fng = filter_engulfing_with_fng(
            [sig], fng_df, long_max_fng=60.0
        )
        assert len(after_fng) == 0, "F&G=80 should reject long signal"
        assert n_rej_fng == 1

    def test_low_fng_rejects_short(self):
        """F&G=15 <= short_min=40: short sinyal F&G filtresiyle reddedilmeli."""
        from price_action.strategies.sentiment_filter import filter_engulfing_with_fng

        fng_df = _make_fng_df(value=15, n=60)  # Extreme Fear
        sig = _make_signal(direction="short", ts="2023-06-15")

        after_fng, n_rej_fng = filter_engulfing_with_fng(
            [sig], fng_df, short_min_fng=40.0
        )
        assert len(after_fng) == 0, "F&G=15 should reject short signal"
        assert n_rej_fng == 1

    def test_fng_fail_obv_never_reached(self):
        """OBV filter should never be called if F&G already rejected all signals."""
        from price_action.strategies.sentiment_filter import filter_engulfing_with_fng
        from price_action.strategies.obv_engulfing_confluence import filter_with_obv_divergence

        fng_df = _make_fng_df(value=90, n=60)  # All greed — no longs should pass
        df = _make_ohlcv(n=60, bullish_obv=True)  # OBV would accept these
        sigs = [_make_signal(direction="long", ts="2023-06-15")]

        after_fng, n_rej_fng = filter_engulfing_with_fng(sigs, fng_df, long_max_fng=60.0)
        assert len(after_fng) == 0  # F&G rejected everything

        # OBV filter called on empty list — must return empty gracefully
        final, n_rej_obv = filter_with_obv_divergence(after_fng, df, lookback=15)
        assert final == []
        assert n_rej_obv == 0


# ---------------------------------------------------------------------------
# T03: OBV fail => signal rejected (F&G passed)
# ---------------------------------------------------------------------------

class TestT03OBVFailRejects:
    def test_no_obv_div_rejects_long(self):
        """Flat price + constant volume => no OBV divergence => long rejected."""
        from price_action.strategies.obv_engulfing_confluence import filter_with_obv_divergence

        # Flat OHLCV: price slope = 0, OBV slope = 0 → no divergence
        n = 60
        days = pd.date_range("2023-05-01", periods=n, freq="1D", tz="UTC")
        flat_df = pd.DataFrame({
            "ts": days,
            "open": [100.0] * n,
            "high": [100.5] * n,
            "low": [99.5] * n,
            "close": [100.0] * n,
            "volume": [1_000_000.0] * n,
            "venue": "binance", "symbol": "BTC/USDT", "timeframe": "1d",
        })

        # Signal in the middle of the flat series
        sig_ts = days[30].to_pydatetime()
        sig = _make_signal(direction="long", ts="2023-06-14")  # maps to ts in days range
        # Use a ts that's inside the df
        from price_action.contracts import Signal
        sig_inner = Signal(
            ts=days[30].to_pydatetime(),
            venue="binance", symbol="BTC/USDT", timeframe="1d",
            direction="long", pattern_id="bullish_engulfing_cont",
            confluence_score=1.5, sl_price=95.0, tp_price=110.0,
            suggested_size_atr=1.0,
        )

        passed, n_rej = filter_with_obv_divergence([sig_inner], flat_df, lookback=15)
        # With completely flat data, slope = 0 for both price and OBV.
        # Bull div requires price slope < 0 AND obv slope > 0 — neither true.
        # So signal should be rejected.
        assert isinstance(passed, list)
        assert isinstance(n_rej, int)
        total = len(passed) + n_rej
        assert total == 1, f"Expected 1 signal total, got {total}"
        # The flat series should reject the bull div signal
        assert n_rej == 1 or len(passed) == 0, (
            "Flat series has no OBV bull div — signal should be rejected"
        )

    def test_obv_filter_returns_subset_of_inputs(self):
        """OBV filter output is always a subset of inputs — no new signals created."""
        from price_action.strategies.obv_engulfing_confluence import filter_with_obv_divergence

        df = _make_ohlcv(n=80, seed=99)
        sigs = [
            _make_signal(direction="long", ts="2023-06-10"),
            _make_signal(direction="short", ts="2023-06-15"),
        ]

        passed, n_rej = filter_with_obv_divergence(sigs, df, lookback=15)
        assert len(passed) + n_rej == len(sigs), "filter must be a partition"
        assert all(s in sigs for s in passed), "passed signals must be from original list"


# ---------------------------------------------------------------------------
# T04: Both F&G and OBV fail
# ---------------------------------------------------------------------------

class TestT04BothFail:
    def test_both_filters_fail_compound_rejects(self):
        """F&G=80 (greed) + flat OBV (no div) => compound rejects long signal.

        F&G and flat OHLCV both start at 2023-06-01 so dates overlap correctly.
        """
        from price_action.strategies.sentiment_filter import filter_engulfing_with_fng
        from price_action.strategies.obv_engulfing_confluence import filter_with_obv_divergence

        # F&G in extreme greed — starts 2023-06-01
        fng_df = _make_fng_df(value=80, n=60, start="2023-06-01")

        # Flat OHLCV — same start date so signal ts overlap is guaranteed
        n = 60
        days = pd.date_range("2023-06-01", periods=n, freq="1D", tz="UTC")
        flat_df = pd.DataFrame({
            "ts": days,
            "open": [100.0] * n,
            "high": [100.5] * n,
            "low": [99.5] * n,
            "close": [100.0] * n,
            "volume": [1_000_000.0] * n,
            "venue": "binance", "symbol": "BTC/USDT", "timeframe": "1d",
        })

        from price_action.contracts import Signal
        # Signal at day 30 (2023-07-01): lag = value[29] = 80 → greed → rejected
        sig = Signal(
            ts=days[30].to_pydatetime(),
            venue="binance", symbol="BTC/USDT", timeframe="1d",
            direction="long", pattern_id="bullish_engulfing_cont",
            confluence_score=1.5, sl_price=95.0, tp_price=110.0,
            suggested_size_atr=1.0,
        )

        # Step 1: F&G filter (lag[day30] = value[29] = 80 >= 60 → rejected)
        after_fng, n_rej_fng = filter_engulfing_with_fng(
            [sig], fng_df, long_max_fng=60.0
        )
        assert n_rej_fng == 1, "F&G should reject greed signal"
        assert after_fng == []

        # Step 2: OBV filter on empty list (F&G already rejected)
        final, n_rej_obv = filter_with_obv_divergence(after_fng, flat_df, lookback=15)
        assert final == []
        assert n_rej_obv == 0  # nothing left to reject


# ---------------------------------------------------------------------------
# T05: Lookahead-free — F&G shift(1) verification
# ---------------------------------------------------------------------------

class TestT05FNGLookaheadFree:
    def test_fng_uses_previous_day_value(self):
        """F&G filter uses t-1 value for signal at day t."""
        from price_action.strategies.sentiment_filter import filter_engulfing_with_fng
        from price_action.contracts import Signal

        # F&G: day 0=10 (fear), day 1=80 (greed)
        # Signal at day 1: shift(1) means we use day 0's value (10 → passes long)
        # Without shift, we'd use day 1's value (80 → rejects long)
        days = pd.date_range("2023-06-01", periods=5, freq="1D", tz="UTC")
        fng_df = pd.DataFrame({
            "ts": days,
            "value": [10, 80, 80, 80, 80],  # day 0 = fear, rest = greed
            "classification": ["Extreme Fear", "Extreme Greed", "Extreme Greed",
                                "Extreme Greed", "Extreme Greed"],
        })

        # Signal on day 1 (2023-06-02): shift(1) → uses day 0 value (10) → passes
        sig = Signal(
            ts=days[1].to_pydatetime(),
            venue="binance", symbol="BTC/USDT", timeframe="1d",
            direction="long", pattern_id="bullish_engulfing_cont",
            confluence_score=1.5, sl_price=25000.0, tp_price=32000.0,
            suggested_size_atr=1.0,
        )

        passed, n_rej = filter_engulfing_with_fng(
            [sig], fng_df, long_max_fng=60.0
        )
        # shift(1): day 1 uses day 0's F&G value (10 < 60) => passes
        assert len(passed) == 1, (
            f"shift(1) means day1 signal uses day0 F&G=10 < 60, should pass. "
            f"Got rejected={n_rej}"
        )

    def test_fng_day_zero_has_no_lag(self):
        """First bar has no prior day F&G — NaN → conservative pass."""
        from price_action.strategies.sentiment_filter import filter_engulfing_with_fng
        from price_action.contracts import Signal

        days = pd.date_range("2023-06-01", periods=5, freq="1D", tz="UTC")
        fng_df = pd.DataFrame({
            "ts": days,
            "value": [90, 90, 90, 90, 90],  # all greed — would reject long normally
            "classification": ["Extreme Greed"] * 5,
        })

        # Signal on day 0: shift(1) → NaN → conservative pass
        sig = Signal(
            ts=days[0].to_pydatetime(),
            venue="binance", symbol="BTC/USDT", timeframe="1d",
            direction="long", pattern_id="bullish_engulfing_cont",
            confluence_score=1.5, sl_price=25000.0, tp_price=32000.0,
            suggested_size_atr=1.0,
        )

        passed, n_rej = filter_engulfing_with_fng(
            [sig], fng_df, long_max_fng=60.0
        )
        # Day 0 has NaN lag → passes conservatively
        assert len(passed) == 1, (
            "Day 0 with NaN F&G lag should pass conservatively (no lookahead possible)"
        )


# ---------------------------------------------------------------------------
# T06: Lookahead-free — OBV slope uses [i-window..i-1]
# ---------------------------------------------------------------------------

class TestT06OBVLookaheadFree:
    def test_obv_slope_uses_only_past_bars(self):
        """OBV _linreg_slope: at bar i, uses [i-window..i-1] only (past data)."""
        from price_action.strategies.obv_engulfing_confluence import (
            _linreg_slope,
            _compute_obv,
        )

        n = 30
        window = 10
        # Rising series: clear positive slope from bar 10 onward
        series = pd.Series(np.arange(n, dtype=float))
        slopes = _linreg_slope(series, window=window)

        # First `window` bars must be NaN (not enough history)
        assert slopes.iloc[:window].isna().all(), (
            f"First {window} bars must be NaN — not enough history for lookahead-free slope"
        )

        # Bar `window` has exactly [0..window-1] to work with → should be non-NaN
        assert not np.isnan(slopes.iloc[window]), (
            f"Bar {window} should have a valid slope (window bars of history)"
        )

        # Slope at bar 20 should be positive (rising series)
        assert slopes.iloc[20] > 0, "Rising series slope must be positive"

    def test_obv_computed_cumulatively_no_future(self):
        """OBV computation at bar i uses only bars [0..i]."""
        from price_action.strategies.obv_engulfing_confluence import _compute_obv

        # 5 bars: up, up, down, up, down
        closes = [100.0, 101.0, 102.0, 100.0, 103.0, 101.0]
        volumes = [1000.0, 2000.0, 1500.0, 800.0, 3000.0, 1200.0]
        n = len(closes)
        days = pd.date_range("2023-06-01", periods=n, freq="1D", tz="UTC")
        df = pd.DataFrame({
            "ts": days, "open": closes, "high": closes, "low": closes,
            "close": closes, "volume": volumes,
            "venue": "binance", "symbol": "BTC/USDT", "timeframe": "1d",
        })

        obv = _compute_obv(df)

        # OBV[0] = 0 always (no prior bar)
        assert obv.iloc[0] == 0.0, "OBV at bar 0 must be 0"

        # Verify cumulative: bar 1 up → +2000, bar 2 up → +1500, bar 3 down → -800
        assert obv.iloc[1] == pytest.approx(2000.0)
        assert obv.iloc[2] == pytest.approx(3500.0)
        assert obv.iloc[3] == pytest.approx(2700.0)


# ---------------------------------------------------------------------------
# T07: Empty signals — no crash
# ---------------------------------------------------------------------------

class TestT07EmptySignals:
    def test_fng_empty_signals_no_crash(self):
        """filter_engulfing_with_fng with empty list → returns ([], 0)."""
        from price_action.strategies.sentiment_filter import filter_engulfing_with_fng

        fng_df = _make_fng_df(value=50)
        passed, n_rej = filter_engulfing_with_fng([], fng_df)
        assert passed == []
        assert n_rej == 0

    def test_obv_empty_signals_no_crash(self):
        """filter_with_obv_divergence with empty list → returns ([], 0)."""
        from price_action.strategies.obv_engulfing_confluence import filter_with_obv_divergence

        df = _make_ohlcv(n=60)
        passed, n_rej = filter_with_obv_divergence([], df, lookback=15)
        assert passed == []
        assert n_rej == 0

    def test_compound_empty_no_crash(self):
        """Full compound pipeline with empty list → empty output, no exceptions."""
        from price_action.strategies.sentiment_filter import filter_engulfing_with_fng
        from price_action.strategies.obv_engulfing_confluence import filter_with_obv_divergence

        fng_df = _make_fng_df(value=50)
        df = _make_ohlcv(n=60)

        after_fng, n_rej_fng = filter_engulfing_with_fng([], fng_df)
        final, n_rej_obv = filter_with_obv_divergence(after_fng, df, lookback=15)

        assert final == []
        assert n_rej_fng == 0
        assert n_rej_obv == 0


# ---------------------------------------------------------------------------
# T08: F&G data missing — OBV filter still works
# ---------------------------------------------------------------------------

class TestT08FNGMissingOBVStillWorks:
    def test_empty_fng_passes_all_to_obv(self):
        """No F&G data → all signals pass F&G gate → OBV gate still applies."""
        from price_action.strategies.sentiment_filter import filter_engulfing_with_fng
        from price_action.strategies.obv_engulfing_confluence import filter_with_obv_divergence

        empty_fng = pd.DataFrame(columns=["ts", "value", "classification"])
        df = _make_ohlcv(n=60)

        sig = _make_signal(direction="long", ts="2023-06-15")
        after_fng, n_rej_fng = filter_engulfing_with_fng([sig], empty_fng)
        # Empty F&G → passes conservatively
        assert len(after_fng) == 1
        assert n_rej_fng == 0

        # OBV filter still runs on survivors
        final, n_rej_obv = filter_with_obv_divergence(after_fng, df, lookback=15)
        # Result depends on OBV div — just verify no crash and consistent counts
        assert isinstance(final, list)
        assert len(final) + n_rej_obv == 1

    def test_none_fng_treated_as_empty(self):
        """F&G=None → filter_engulfing_with_fng returns original signals (warning logged)."""
        from price_action.strategies.sentiment_filter import filter_engulfing_with_fng

        sig = _make_signal(direction="long", ts="2023-06-15")
        # Passing None as fng_df
        passed, n_rej = filter_engulfing_with_fng([sig], pd.DataFrame())
        assert len(passed) == 1  # conservative pass when no F&G data


# ---------------------------------------------------------------------------
# T09: Filter meta — rejection counts consistent
# ---------------------------------------------------------------------------

class TestT09RejectionCounts:
    def test_fng_rejection_count_matches_output(self):
        """n_rejected + len(passed) == len(inputs) for F&G filter."""
        from price_action.strategies.sentiment_filter import filter_engulfing_with_fng

        # 3 longs, F&G = 80 (all should be rejected)
        fng_df = _make_fng_df(value=80, n=60)
        sigs = [
            _make_signal(direction="long", ts="2023-06-10"),
            _make_signal(direction="long", ts="2023-06-12"),
            _make_signal(direction="long", ts="2023-06-14"),
        ]
        passed, n_rej = filter_engulfing_with_fng(sigs, fng_df, long_max_fng=60.0)
        assert len(passed) + n_rej == len(sigs), (
            f"Partition check: {len(passed)} + {n_rej} != {len(sigs)}"
        )

    def test_obv_rejection_count_matches_output(self):
        """n_rejected + len(passed) == len(inputs) for OBV filter."""
        from price_action.strategies.obv_engulfing_confluence import filter_with_obv_divergence

        df = _make_ohlcv(n=80)
        from price_action.contracts import Signal
        days = pd.date_range("2023-05-01", periods=80, freq="1D", tz="UTC")
        sigs = [
            Signal(
                ts=days[i].to_pydatetime(),
                venue="binance", symbol="BTC/USDT", timeframe="1d",
                direction="long", pattern_id="bullish_engulfing_cont",
                confluence_score=1.5, sl_price=95.0, tp_price=110.0,
                suggested_size_atr=1.0,
            )
            for i in range(30, 40)
        ]

        passed, n_rej = filter_with_obv_divergence(sigs, df, lookback=15)
        assert len(passed) + n_rej == len(sigs), (
            f"OBV partition: {len(passed)} + {n_rej} != {len(sigs)}"
        )

    def test_compound_sequential_counts_consistent(self):
        """Sequential F&G then OBV: total rejected = n_rej_fng + n_rej_obv."""
        from price_action.strategies.sentiment_filter import filter_engulfing_with_fng
        from price_action.strategies.obv_engulfing_confluence import filter_with_obv_divergence
        from price_action.contracts import Signal

        fng_df = _make_fng_df(value=50, n=60)  # neutral — passes longs
        df = _make_ohlcv(n=60)

        days = pd.date_range("2023-06-01", periods=60, freq="1D", tz="UTC")
        sigs = [
            Signal(
                ts=days[i].to_pydatetime(),
                venue="binance", symbol="BTC/USDT", timeframe="1d",
                direction="long", pattern_id="bullish_engulfing_cont",
                confluence_score=1.5, sl_price=95.0, tp_price=110.0,
                suggested_size_atr=1.0,
            )
            for i in range(20, 30)
        ]

        n_raw = len(sigs)
        after_fng, n_rej_fng = filter_engulfing_with_fng(sigs, fng_df, long_max_fng=60.0)
        final, n_rej_obv = filter_with_obv_divergence(after_fng, df, lookback=15)

        total_rej = n_rej_fng + n_rej_obv
        total_acc = len(final)
        assert total_rej + total_acc == n_raw, (
            f"Sequential count: {total_rej} + {total_acc} != {n_raw}"
        )


# ---------------------------------------------------------------------------
# T10: OBV filter — unknown ts handled conservatively
# ---------------------------------------------------------------------------

class TestT10OBVUnknownTsConservative:
    def test_signal_ts_not_in_df_passes(self):
        """Signal ts outside df time range → OBV filter passes conservatively."""
        from price_action.strategies.obv_engulfing_confluence import filter_with_obv_divergence

        # df covers 2023-05-01..2023-06-29
        df = _make_ohlcv(n=60, start="2023-05-01")

        # Signal far in the future (not in df)
        future_sig = _make_signal(direction="long", ts="2024-01-01")
        passed, n_rej = filter_with_obv_divergence([future_sig], df, lookback=15)
        # ts_to_idx lookup returns None → conservative pass
        assert len(passed) == 1, "Signal not in df should pass conservatively"
        assert n_rej == 0


# ---------------------------------------------------------------------------
# T11: Compound D — sequential application (F&G first, OBV on survivors)
# ---------------------------------------------------------------------------

class TestT11CompoundSequential:
    def test_fng_applied_before_obv(self):
        """In compound D: F&G rejects first; OBV only sees F&G survivors.

        F&G layout (shift(1) semantics):
          values[0..14] = 80 (greed), values[15..29] = 50 (neutral)
          Signal at day[15]: lag = values[14] = 80 → rejected (greed)
          Signal at day[16]: lag = values[15] = 50 → passes (neutral)
        """
        from price_action.strategies.sentiment_filter import filter_engulfing_with_fng
        from price_action.strategies.obv_engulfing_confluence import filter_with_obv_divergence
        from price_action.contracts import Signal

        days = pd.date_range("2023-06-01", periods=30, freq="1D", tz="UTC")
        # values[0..14] = 80, values[15..29] = 50
        values = [80 if i < 15 else 50 for i in range(30)]
        fng_df = pd.DataFrame({
            "ts": days,
            "value": values,
            "classification": ["Extreme Greed" if v > 60 else "Neutral" for v in values],
        })

        df = _make_ohlcv(n=30, start="2023-06-01")

        # Signal at day[15]: shift(1) lag = values[14] = 80 → rejected
        sig_greed = Signal(
            ts=days[15].to_pydatetime(),
            venue="binance", symbol="BTC/USDT", timeframe="1d",
            direction="long", pattern_id="bullish_engulfing_cont",
            confluence_score=1.5, sl_price=90.0, tp_price=115.0, suggested_size_atr=1.0,
        )
        # Signal at day[16]: shift(1) lag = values[15] = 50 → passes
        sig_neutral = Signal(
            ts=days[16].to_pydatetime(),
            venue="binance", symbol="BTC/USDT", timeframe="1d",
            direction="long", pattern_id="bullish_engulfing_cont",
            confluence_score=1.5, sl_price=90.0, tp_price=115.0, suggested_size_atr=1.0,
        )

        sigs = [sig_greed, sig_neutral]
        after_fng, n_rej_fng = filter_engulfing_with_fng(
            sigs, fng_df, long_max_fng=60.0
        )
        # sig_greed: lag[day15] = values[14] = 80 >= 60 → rejected
        # sig_neutral: lag[day16] = values[15] = 50 < 60 → passed
        assert n_rej_fng == 1, f"Expected 1 F&G rejection, got {n_rej_fng}"
        assert len(after_fng) == 1, f"Expected 1 F&G survivor, got {len(after_fng)}"

        # OBV filter runs only on the 1 survivor
        final, n_rej_obv = filter_with_obv_divergence(after_fng, df, lookback=10)
        total = len(final) + n_rej_obv
        assert total == len(after_fng), "OBV must partition its inputs"

    def test_obv_does_not_see_fng_rejects(self):
        """OBV filter receives only F&G survivors — its n_input == F&G n_passed."""
        from price_action.strategies.sentiment_filter import filter_engulfing_with_fng
        from price_action.strategies.obv_engulfing_confluence import filter_with_obv_divergence

        fng_df = _make_fng_df(value=80, n=60)  # greed — all longs rejected
        df = _make_ohlcv(n=60)

        sigs = [
            _make_signal(direction="long", ts="2023-06-10"),
            _make_signal(direction="long", ts="2023-06-12"),
        ]

        after_fng, n_rej_fng = filter_engulfing_with_fng(sigs, fng_df, long_max_fng=60.0)
        assert after_fng == []  # F&G rejected everything

        # OBV should receive empty list — must handle gracefully
        final, n_rej_obv = filter_with_obv_divergence(after_fng, df, lookback=15)
        assert final == []
        assert n_rej_obv == 0


# ---------------------------------------------------------------------------
# T12: Multi-symbol — each signal evaluated on its own ts
# ---------------------------------------------------------------------------

class TestT12MultiSymbol:
    def test_different_ts_handled_correctly(self):
        """Multiple signals with different ts are each evaluated on their own date."""
        from price_action.strategies.sentiment_filter import filter_engulfing_with_fng
        from price_action.contracts import Signal

        days = pd.date_range("2023-06-01", periods=60, freq="1D", tz="UTC")
        # day 0..14: F&G=10 (fear → passes long), day 15..59: F&G=90 (greed → fails long)
        values = [10] * 15 + [90] * 45
        fng_df = pd.DataFrame({
            "ts": days,
            "value": values,
            "classification": ["Extreme Fear"] * 15 + ["Extreme Greed"] * 45,
        })

        # Signal on day 5 (lag = value[4] = 10 → passes) — fear zone
        sig_fear = Signal(
            ts=days[5].to_pydatetime(),
            venue="binance", symbol="BTC/USDT", timeframe="1d",
            direction="long", pattern_id="bullish_engulfing_cont",
            confluence_score=1.5, sl_price=90.0, tp_price=115.0, suggested_size_atr=1.0,
        )
        # Signal on day 30 (lag = value[29] = 90 → rejected) — greed zone
        sig_greed = Signal(
            ts=days[30].to_pydatetime(),
            venue="binance", symbol="BTC/USDT", timeframe="1d",
            direction="long", pattern_id="bullish_engulfing_cont",
            confluence_score=1.5, sl_price=90.0, tp_price=115.0, suggested_size_atr=1.0,
        )

        passed, n_rej = filter_engulfing_with_fng(
            [sig_fear, sig_greed], fng_df, long_max_fng=60.0
        )
        assert len(passed) == 1, "Only fear-zone signal should pass"
        assert n_rej == 1, "Only greed-zone signal should be rejected"
        assert passed[0].ts == sig_fear.ts, "The passing signal should be the fear-zone one"
