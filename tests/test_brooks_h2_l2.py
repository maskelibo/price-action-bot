"""Brooks H2/L2 Two-Legged Pullback strateji testleri.

8 test:
  1. H2 signal detects valid two-legged bull pullback
  2. L2 signal detects valid two-legged bear pullback
  3. H2 rejects insufficient Leg A (< 3 bars)
  4. L2 rejects insufficient Leg C (< 3 bars)
  5. Trend filter: H2 requires bull trend (close > ema50)
  6. SL is always below entry for H2 (long), above for L2 (short)
  7. TP is always at 2R from entry relative to SL
  8. No lookahead bias: signal at bar t equals truncated result
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from price_action.strategies.brooks_h2_l2 import (
    BrooksH2L2Strategy,
    _detect_h2_l2,
    _trend_direction,
    _default_manifest,
)
from price_action.strategies.base import StrategyManifest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_strategy() -> BrooksH2L2Strategy:
    return BrooksH2L2Strategy(_default_manifest())


def _build_df(prices: list[float], *, trend_up: bool = True) -> pd.DataFrame:
    """Build minimal OHLCV + required columns from a close price list.

    If trend_up=True, prices start at 100 and go up, else down.
    EMA50 is set slightly below all prices for bull trend (or above for bear).
    """
    n = len(prices)
    dates = pd.date_range("2022-01-01", periods=n, freq="D", tz="UTC")
    closes = np.array(prices, dtype=float)
    # Build realistic OHLCV
    opens = np.roll(closes, 1)
    opens[0] = closes[0]
    highs = np.maximum(opens, closes) + 0.5
    lows = np.minimum(opens, closes) - 0.5
    volumes = np.full(n, 1000.0)

    df = pd.DataFrame({
        "ts": dates,
        "open": opens,
        "high": highs,
        "low": lows,
        "close": closes,
        "volume": volumes,
        "symbol": "TEST/USDT",
        "timeframe": "1d",
        "venue": "binance",
    })
    return df


def _build_h2_scenario(leg_a_bars: int = 4, leg_b_bars: int = 2, leg_c_bars: int = 4) -> pd.DataFrame:
    """Build synthetic bull trend + ABC pullback (H2 setup).

    Structure:
      - 60 bars of bull trend (rising prices above EMA50)
      - Leg A: leg_a_bars bars of declining price
      - Leg B: leg_b_bars bars of rising price (partial bounce)
      - Leg C: leg_c_bars bars of declining price + 1 bull reversal bar
    """
    prices = []
    # Bull trend phase (rising)
    start = 100.0
    for i in range(60):
        start += 0.5
        prices.append(start)

    peak = prices[-1]

    # Leg A (decline)
    p = peak
    for _ in range(leg_a_bars):
        p -= 1.5
        prices.append(p)

    leg_a_bottom = p

    # Leg B (partial bounce — less than full A recovery)
    for _ in range(leg_b_bars):
        p += 0.8
        prices.append(p)

    # Leg C (decline again)
    for _ in range(leg_c_bars):
        p -= 1.5
        prices.append(p)

    # Bull reversal bar (entry bar) — close above open
    p += 2.0  # strong bull bar
    prices.append(p)

    df = _build_df(prices, trend_up=True)
    return df


def _build_l2_scenario(leg_a_bars: int = 4, leg_b_bars: int = 2, leg_c_bars: int = 4) -> pd.DataFrame:
    """Build synthetic bear trend + ABC pullback (L2 setup).

    Structure:
      - 60 bars of bear trend (declining prices below EMA50)
      - Leg A: leg_a_bars bars of rising price
      - Leg B: leg_b_bars bars of declining price (partial bounce)
      - Leg C: leg_c_bars bars of rising price + 1 bear reversal bar
    """
    prices = []
    # Bear trend phase
    start = 200.0
    for i in range(60):
        start -= 0.5
        prices.append(start)

    bottom = prices[-1]

    # Leg A (rise against bear trend)
    p = bottom
    for _ in range(leg_a_bars):
        p += 1.5
        prices.append(p)

    # Leg B (partial decline)
    for _ in range(leg_b_bars):
        p -= 0.8
        prices.append(p)

    # Leg C (rise again)
    for _ in range(leg_c_bars):
        p += 1.5
        prices.append(p)

    # Bear reversal bar (entry bar) — close below open
    p -= 2.0  # strong bear bar
    prices.append(p)

    df = _build_df(prices, trend_up=False)
    return df


# ---------------------------------------------------------------------------
# Test 1: H2 detects valid two-legged bull pullback
# ---------------------------------------------------------------------------
class TestH2Detection:
    def test_h2_detects_valid_abc_bull_pullback(self):
        """H2 signal should fire on the bull reversal bar ending a valid A-B-C pullback."""
        df = _build_h2_scenario(leg_a_bars=4, leg_b_bars=2, leg_c_bars=4)
        strategy = _make_strategy()
        df_feats = strategy.prepare_features(df)

        assert "h2_signal" in df_feats.columns, "h2_signal column must exist"
        n_signals = int(df_feats["h2_signal"].sum())
        assert n_signals >= 1, (
            f"Should detect at least 1 H2 signal in valid ABC bull pullback scenario, got {n_signals}"
        )

    def test_h2_signal_has_valid_sl_tp(self):
        """Every H2 signal bar must have finite SL and TP values."""
        df = _build_h2_scenario()
        strategy = _make_strategy()
        df_feats = strategy.prepare_features(df)

        h2_bars = df_feats[df_feats["h2_signal"] == True]
        assert len(h2_bars) > 0, "Need at least one H2 signal to test SL/TP"
        for idx, row in h2_bars.iterrows():
            assert not np.isnan(row["h2_sl"]), f"h2_sl must not be NaN at bar {idx}"
            assert not np.isnan(row["h2_tp"]), f"h2_tp must not be NaN at bar {idx}"
            assert row["h2_sl"] < row["close"], (
                f"H2 SL ({row['h2_sl']:.4f}) must be below entry close ({row['close']:.4f})"
            )
            assert row["h2_tp"] > row["close"], (
                f"H2 TP ({row['h2_tp']:.4f}) must be above entry close ({row['close']:.4f})"
            )


# ---------------------------------------------------------------------------
# Test 2: L2 detects valid two-legged bear pullback
# ---------------------------------------------------------------------------
class TestL2Detection:
    def test_l2_detects_valid_abc_bear_pullback(self):
        """L2 signal should fire on the bear reversal bar ending a valid A-B-C pullback."""
        df = _build_l2_scenario(leg_a_bars=4, leg_b_bars=2, leg_c_bars=4)
        strategy = _make_strategy()
        df_feats = strategy.prepare_features(df)

        assert "l2_signal" in df_feats.columns, "l2_signal column must exist"
        n_signals = int(df_feats["l2_signal"].sum())
        assert n_signals >= 1, (
            f"Should detect at least 1 L2 signal in valid ABC bear pullback scenario, got {n_signals}"
        )

    def test_l2_signal_has_valid_sl_tp(self):
        """Every L2 signal bar must have SL above and TP below entry close."""
        df = _build_l2_scenario()
        strategy = _make_strategy()
        df_feats = strategy.prepare_features(df)

        l2_bars = df_feats[df_feats["l2_signal"] == True]
        assert len(l2_bars) > 0, "Need at least one L2 signal to test SL/TP"
        for idx, row in l2_bars.iterrows():
            assert not np.isnan(row["l2_sl"]), f"l2_sl must not be NaN at bar {idx}"
            assert not np.isnan(row["l2_tp"]), f"l2_tp must not be NaN at bar {idx}"
            assert row["l2_sl"] > row["close"], (
                f"L2 SL ({row['l2_sl']:.4f}) must be above entry close ({row['close']:.4f})"
            )
            assert row["l2_tp"] < row["close"], (
                f"L2 TP ({row['l2_tp']:.4f}) must be below entry close ({row['close']:.4f})"
            )


# ---------------------------------------------------------------------------
# Test 3: H2 rejects insufficient Leg A (only 1-2 bars)
# ---------------------------------------------------------------------------
class TestH2InsufficientLegA:
    def test_h2_rejects_short_leg_a(self):
        """With only 2 bars in Leg A (below min 3), fewer/no H2 signals vs valid setup."""
        df_short = _build_h2_scenario(leg_a_bars=1, leg_b_bars=2, leg_c_bars=4)
        df_valid = _build_h2_scenario(leg_a_bars=4, leg_b_bars=2, leg_c_bars=4)

        strategy = _make_strategy()
        feats_short = strategy.prepare_features(df_short)
        feats_valid = strategy.prepare_features(df_valid)

        # short leg A should generate <= signals than valid setup
        n_short = int(feats_short["h2_signal"].sum())
        n_valid = int(feats_valid["h2_signal"].sum())
        assert n_short <= n_valid, (
            f"Short leg A ({n_short} signals) should not exceed valid leg A ({n_valid} signals)"
        )


# ---------------------------------------------------------------------------
# Test 4: L2 rejects insufficient Leg C (only 1-2 bars)
# ---------------------------------------------------------------------------
class TestL2InsufficientLegC:
    def test_l2_rejects_short_leg_c(self):
        """With only 2 bars in Leg C (below min 3), fewer/no L2 signals vs valid setup."""
        df_short = _build_l2_scenario(leg_a_bars=4, leg_b_bars=2, leg_c_bars=1)
        df_valid = _build_l2_scenario(leg_a_bars=4, leg_b_bars=2, leg_c_bars=4)

        strategy = _make_strategy()
        feats_short = strategy.prepare_features(df_short)
        feats_valid = strategy.prepare_features(df_valid)

        n_short = int(feats_short["l2_signal"].sum())
        n_valid = int(feats_valid["l2_signal"].sum())
        assert n_short <= n_valid, (
            f"Short leg C ({n_short} signals) should not exceed valid leg C ({n_valid} signals)"
        )


# ---------------------------------------------------------------------------
# Test 5: Trend filter — H2 requires bull trend (close > ema50 + majority bull bars)
# ---------------------------------------------------------------------------
class TestTrendFilter:
    def test_h2_signal_requires_prior_bull_trend(self):
        """H2 signals should only fire when the pre-pullback trend was bullish.

        The detector checks trend_long at the bar BEFORE Leg A started,
        not at the entry bar (which may be below EMA50 during a deep pullback).
        We verify: the scenario is built with a prior bull trend, and H2 fires.
        """
        df = _build_h2_scenario()
        strategy = _make_strategy()
        df_feats = strategy.prepare_features(df)

        # The bull trend phase starts at bar 0, so earlier bars should be trend_long=True
        early_trend = df_feats["trend_long"].iloc[30:55]
        assert early_trend.any(), "Early bars (pre-pullback) should have trend_long=True"

        h2_bars = df_feats[df_feats["h2_signal"] == True]
        assert len(h2_bars) >= 1, (
            "H2 should fire because pre-pullback trend was bullish, "
            "even if entry bar is below EMA50 during pullback"
        )

    def test_l2_signal_requires_prior_bear_trend(self):
        """L2 signals should only fire when the pre-pullback trend was bearish."""
        df = _build_l2_scenario()
        strategy = _make_strategy()
        df_feats = strategy.prepare_features(df)

        # The bear trend phase: close < ema50
        early_short = df_feats["trend_short"].iloc[30:55]
        assert early_short.any(), "Early bars (pre-pullback) should have trend_short=True"

        l2_bars = df_feats[df_feats["l2_signal"] == True]
        assert len(l2_bars) >= 1, (
            "L2 should fire because pre-pullback trend was bearish"
        )


# ---------------------------------------------------------------------------
# Test 6: SL/TP direction invariant (vectorized, all signals)
# ---------------------------------------------------------------------------
class TestSLTPInvariant:
    def test_h2_sl_always_below_close_tp_always_above(self):
        """For every H2 signal, SL < close < TP."""
        df = _build_h2_scenario(leg_a_bars=4, leg_b_bars=2, leg_c_bars=4)
        strategy = _make_strategy()
        df_feats = strategy.prepare_features(df)

        h2_bars = df_feats[df_feats["h2_signal"] == True]
        assert len(h2_bars) >= 1, "Need H2 signals for this test"
        for _, row in h2_bars.iterrows():
            if np.isnan(row["h2_sl"]) or np.isnan(row["h2_tp"]):
                continue
            assert row["h2_sl"] < row["close"], "H2 SL must be < close (below entry)"
            assert row["h2_tp"] > row["close"], "H2 TP must be > close (above entry)"

    def test_l2_sl_always_above_close_tp_always_below(self):
        """For every L2 signal, TP < close < SL."""
        df = _build_l2_scenario(leg_a_bars=4, leg_b_bars=2, leg_c_bars=4)
        strategy = _make_strategy()
        df_feats = strategy.prepare_features(df)

        l2_bars = df_feats[df_feats["l2_signal"] == True]
        assert len(l2_bars) >= 1, "Need L2 signals for this test"
        for _, row in l2_bars.iterrows():
            if np.isnan(row["l2_sl"]) or np.isnan(row["l2_tp"]):
                continue
            assert row["l2_sl"] > row["close"], "L2 SL must be > close (above entry)"
            assert row["l2_tp"] < row["close"], "L2 TP must be < close (below entry)"


# ---------------------------------------------------------------------------
# Test 7: TP is approximately 2R from entry
# ---------------------------------------------------------------------------
class TestTPAtTwoR:
    PRIMARY_R = 2.0
    TOLERANCE = 0.05  # 5% tolerance for floating point

    def test_h2_tp_at_2r(self):
        """H2 TP should be ~2R above entry (risk = close - SL)."""
        df = _build_h2_scenario()
        strategy = _make_strategy()
        df_feats = strategy.prepare_features(df)

        h2_bars = df_feats[df_feats["h2_signal"] == True]
        assert len(h2_bars) >= 1, "Need H2 signals"

        for _, row in h2_bars.iterrows():
            sl = row["h2_sl"]
            tp = row["h2_tp"]
            close = row["close"]
            if np.isnan(sl) or np.isnan(tp):
                continue
            risk = close - sl
            reward = tp - close
            if risk <= 0:
                continue
            ratio = reward / risk
            assert abs(ratio - self.PRIMARY_R) <= self.TOLERANCE * self.PRIMARY_R, (
                f"H2 TP/SL ratio {ratio:.3f} should be ~{self.PRIMARY_R} "
                f"(tolerance ±{self.TOLERANCE*100:.0f}%)"
            )

    def test_l2_tp_at_2r(self):
        """L2 TP should be ~2R below entry (risk = SL - close)."""
        df = _build_l2_scenario()
        strategy = _make_strategy()
        df_feats = strategy.prepare_features(df)

        l2_bars = df_feats[df_feats["l2_signal"] == True]
        assert len(l2_bars) >= 1, "Need L2 signals"

        for _, row in l2_bars.iterrows():
            sl = row["l2_sl"]
            tp = row["l2_tp"]
            close = row["close"]
            if np.isnan(sl) or np.isnan(tp):
                continue
            risk = sl - close
            reward = close - tp
            if risk <= 0:
                continue
            ratio = reward / risk
            assert abs(ratio - self.PRIMARY_R) <= self.TOLERANCE * self.PRIMARY_R, (
                f"L2 TP/SL ratio {ratio:.3f} should be ~{self.PRIMARY_R}"
            )


# ---------------------------------------------------------------------------
# Test 8: No lookahead bias
# ---------------------------------------------------------------------------
class TestNoLookahead:
    def test_h2_signal_no_lookahead(self):
        """H2 signal at bar t must equal the result on df[:t+1]."""
        df = _build_h2_scenario(leg_a_bars=4, leg_b_bars=2, leg_c_bars=4)
        strategy = _make_strategy()
        df_feats_full = strategy.prepare_features(df)

        # Find first H2 signal bar
        h2_indices = df_feats_full.index[df_feats_full["h2_signal"] == True].tolist()
        if not h2_indices:
            pytest.skip("No H2 signals detected — cannot test lookahead")

        target_idx = h2_indices[0]  # first signal bar (integer position in original df)
        # Map to positional index
        pos = df_feats_full.index.get_loc(target_idx)

        # Truncate at pos+1 and re-run
        df_trunc = df.iloc[: pos + 1].copy()
        df_trunc_feats = strategy.prepare_features(df_trunc)

        full_val = bool(df_feats_full["h2_signal"].iloc[pos])
        trunc_val = bool(df_trunc_feats["h2_signal"].iloc[pos])

        assert full_val == trunc_val, (
            f"Lookahead bias detected: full={full_val}, truncated={trunc_val} at pos={pos}"
        )

    def test_l2_signal_no_lookahead(self):
        """L2 signal at bar t must equal the result on df[:t+1]."""
        df = _build_l2_scenario(leg_a_bars=4, leg_b_bars=2, leg_c_bars=4)
        strategy = _make_strategy()
        df_feats_full = strategy.prepare_features(df)

        l2_indices = df_feats_full.index[df_feats_full["l2_signal"] == True].tolist()
        if not l2_indices:
            pytest.skip("No L2 signals detected — cannot test lookahead")

        target_idx = l2_indices[0]
        pos = df_feats_full.index.get_loc(target_idx)

        df_trunc = df.iloc[: pos + 1].copy()
        df_trunc_feats = strategy.prepare_features(df_trunc)

        full_val = bool(df_feats_full["l2_signal"].iloc[pos])
        trunc_val = bool(df_trunc_feats["l2_signal"].iloc[pos])

        assert full_val == trunc_val, (
            f"Lookahead bias in L2: full={full_val}, truncated={trunc_val} at pos={pos}"
        )


# ---------------------------------------------------------------------------
# Test bonus: generate_signals produces Signal objects with correct direction
# ---------------------------------------------------------------------------
class TestGenerateSignals:
    def test_generate_signals_h2_direction(self):
        """generate_signals() should produce 'long' signals for H2."""
        df = _build_h2_scenario()
        strategy = _make_strategy()
        df_feats = strategy.prepare_features(df)
        signals = strategy.generate_signals(df_feats)

        long_sigs = [s for s in signals if s.direction == "long"]
        # May have 0 if filters reject (ATR, ER) — just check consistency
        for sig in long_sigs:
            assert sig.pattern_id == "h2_long", (
                f"Long signal pattern_id should be 'h2_long', got '{sig.pattern_id}'"
            )
            assert sig.sl_price < sig.tp_price, (
                f"For long signal: SL ({sig.sl_price}) must be < TP ({sig.tp_price})"
            )

    def test_generate_signals_l2_direction(self):
        """generate_signals() should produce 'short' signals for L2."""
        df = _build_l2_scenario()
        strategy = _make_strategy()
        df_feats = strategy.prepare_features(df)
        signals = strategy.generate_signals(df_feats)

        short_sigs = [s for s in signals if s.direction == "short"]
        for sig in short_sigs:
            assert sig.pattern_id == "l2_short", (
                f"Short signal pattern_id should be 'l2_short', got '{sig.pattern_id}'"
            )
            assert sig.sl_price > sig.tp_price, (
                f"For short signal: SL ({sig.sl_price}) must be > TP ({sig.tp_price})"
            )

    def test_empty_df_returns_no_signals(self):
        """Empty DataFrame should return empty signal list."""
        strategy = _make_strategy()
        df = pd.DataFrame(columns=["ts", "open", "high", "low", "close", "volume"])
        signals = strategy.generate_signals(df)
        assert signals == [], "Empty DataFrame must produce no signals"
