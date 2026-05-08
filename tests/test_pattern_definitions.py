"""Regression tests that compare pattern detector code against book definitions.

Sources:
  - Brooks: "Reading Price Charts Bar by Bar" — reversal bar, inside bar ii/iii,
    outside bar, swing high/low definitions.
  - Grimes: "The Art and Science of Technical Analysis" — pin bar wick:body ≥ 2:1,
    body ≤ 1/3 range, close in opposite 1/3.
  - Volman: "Forex Price Action Scalping" — inside bar full containment.

All tests use hand-crafted synthetic OHLCV DataFrames (deterministic, no random).
"""
from __future__ import annotations

import pandas as pd
import pytest

from price_action.signals.candles import (
    bearish_engulfing,
    bearish_pin_bar,
    bullish_engulfing,
    bullish_pin_bar,
    inside_bar,
)
from price_action.signals.structure import swing_highs, swing_lows


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _df(*rows: tuple) -> pd.DataFrame:
    """Build a minimal OHLCV DataFrame from (o, h, l, c) tuples."""
    data = [{"open": o, "high": h, "low": l, "close": c} for o, h, l, c in rows]
    return pd.DataFrame(data)


# ---------------------------------------------------------------------------
# 1. test_pin_bar_brooks_grimes_definition
# ---------------------------------------------------------------------------
# Grimes (p.52-54 notes): wick:body ≥ 2:1, body ≤ 1/3 range, close in opposite 1/3.
# Brooks: "tail length / range > 0.5, close opposite end ≤ 25% of range."
# Current code parameters (defaults):
#   body_to_range_max = 0.33   ← covers "body ≤ 1/3 range"
#   upper_wick_to_range_min = 0.60  (bearish pin)
#   lower_wick_to_range_max = 0.15  (bearish pin)
#
# Grimes strict interpretation adds: wick ≥ 2× body.
# We test both the passing case and the boundary case.

class TestPinBarBrooksGrimesDefinition:
    """Pin bar tests against Brooks + Grimes definitions."""

    def test_bearish_pin_bar_clear_case(self):
        """
        Bearish pin bar at structural high.
        Bar: o=100, h=110, l=99, c=100.5
          range = 11
          body  = |100.5 - 100| = 0.5    (body/range ≈ 0.045  → ≤ 0.33 ✓)
          upper_wick = h - max(o,c) = 110 - 100.5 = 9.5
          lower_wick = min(o,c) - l = 100 - 99 = 1.0
          upper_wick/range ≈ 0.864  → ≥ 0.60 ✓
          lower_wick/range ≈ 0.091  → ≤ 0.15 ✓
          Grimes wick:body = 9.5 / 0.5 = 19  → ≥ 2 ✓
        Should detect bearish pin, should NOT detect bullish pin.
        """
        df = _df(
            (100.0, 101.0, 99.5, 100.3),   # bar 0: neutral
            (100.0, 110.0, 99.0, 100.5),   # bar 1: bearish pin
        )
        bear = bearish_pin_bar(df)
        bull = bullish_pin_bar(df)
        assert bool(bear.iloc[1]), "Clear bearish pin bar should be detected"
        assert not bool(bull.iloc[1]), "Bearish pin should NOT trigger bullish pin detector"

    def test_bearish_pin_bar_grimes_2to1_wick_body_boundary(self):
        """
        Grimes requires wick:body ≥ 2:1.
        Bar with wick exactly 2× body — should pass.
        Bar with wick 1.5× body — should fail Grimes criterion.

        The current code does NOT explicitly check wick:body ratio;
        it uses wick/range and body/range thresholds. We verify whether
        those thresholds are equivalent to Grimes 2:1 requirement.

        Construction:
          range = 10.0
          body  = 2.0  (body/range = 0.20 → ≤ 0.33 ✓)
          upper_wick = 4.0  → wick:body = 2.0 ✓ (exactly 2:1)
          lower_wick = 4.0  (too big — not a valid bearish pin)

        For a valid bearish pin (upper dominant):
          range = 10, body = 2, upper_wick = 7, lower_wick = 1
          body/range = 0.20, upper_wick/range = 0.70, lower_wick/range = 0.10
          wick:body = 7/2 = 3.5 ≥ 2 ✓ → PASS
        """
        # Valid: wick:body = 3.5:1, well above 2:1 threshold
        # o=100, c=102, h=109, l=101  → upper_wick = 109-102=7, lower_wick = 100-101? no
        # Let's be precise:
        # bearish bar: o > c so body = o - c
        # o=102, c=100 → body_abs=2, max(o,c)=102, min(o,c)=100
        # h=109, l=101 → upper_wick = 109-102=7, lower_wick = 100-101 = -1 → clipped to 0
        # Wait: lower_wick = min(o,c) - l = 100 - 101 = -1 which is wrong
        # Correct: l must be <= min(o,c)
        # o=102, c=100, h=109, l=99 → upper_wick=7, lower_wick=1, range=10, body=2
        df_valid = _df(
            (100.0, 101.0, 99.5, 100.3),   # neutral
            (102.0, 109.0, 99.0, 100.0),   # bearish pin: body=2, upper=7, lower=1
        )
        assert bool(bearish_pin_bar(df_valid).iloc[1]), (
            "Bearish pin with wick:body=3.5:1 should pass"
        )

        # Borderline: wick 1.5× body.
        # Range = 10, body = 4 (body/range=0.40 → >0.33 → fails body check)
        # So let's use range=10, body=3 (body/range=0.30 ≤ 0.33 OK)
        # upper_wick = 4.5, lower_wick = 2.5
        # upper/range = 0.45 → below the 0.60 threshold → should NOT detect
        # o=103, c=100, h=107.5, l=97.5 → upper_wick=107.5-103=4.5, lower_wick=100-97.5=2.5
        # range=10, body=3, body/range=0.30, upper/range=0.45, lower/range=0.25
        df_invalid = _df(
            (100.0, 101.0, 99.5, 100.3),   # neutral
            (103.0, 107.5, 97.5, 100.0),   # wick:body = 4.5/3 = 1.5 — should NOT detect
        )
        assert not bool(bearish_pin_bar(df_invalid).iloc[1]), (
            "Bearish pin with wick:body=1.5:1 (upper_wick/range=0.45 < 0.60) "
            "should NOT be detected — code threshold aligns with ≥2:1 intent"
        )

    def test_bullish_pin_bar_grimes_2to1_at_structural_low(self):
        """
        Bullish pin bar: long lower wick at a structural low.
        o=100, c=101, h=101.5, l=91 →
          range=10.5, body=1, lower_wick=9, upper_wick=0.5
          body/range≈0.095 ≤ 0.33 ✓
          lower_wick/range≈0.857 ≥ 0.60 ✓
          upper_wick/range≈0.048 ≤ 0.15 ✓
          wick:body = 9/1 = 9 ≥ 2 ✓
        """
        df = _df(
            (100.0, 101.0, 99.0, 100.5),   # neutral
            (100.0, 101.5, 91.0, 101.0),   # bullish pin
        )
        assert bool(bullish_pin_bar(df).iloc[1]), "Clear bullish pin should be detected"
        assert not bool(bearish_pin_bar(df).iloc[1]), "Should not trigger bearish pin"

    def test_pin_bar_insufficient_wick_not_detected(self):
        """
        Bar with wick only 1.4× range (not dominant enough).
        o=100, c=101, h=101, l=96 →
          range=5, body=1, lower_wick=4, upper_wick=0
          lower/range=0.80 ≥ 0.60 ✓ but body/range=0.20 ≤ 0.33 ✓
          → Actually this SHOULD detect — let's build one that genuinely fails.

        A bar with body ≈ 35% of range should be rejected:
          o=100, c=103.5, h=104, l=96  → range=8, body=3.5, body/range=0.4375 > 0.33
          lower_wick = min(100,103.5)-96=4, upper_wick=104-103.5=0.5
          → body too large → should NOT detect bullish pin
        """
        df = _df(
            (100.0, 101.0, 99.0, 100.5),   # neutral
            (100.0, 104.0, 96.0, 103.5),   # body/range=0.4375 > 0.33 → reject
        )
        assert not bool(bullish_pin_bar(df).iloc[1]), (
            "Bar with body/range > 0.33 should NOT be detected as bullish pin"
        )


# ---------------------------------------------------------------------------
# 2. test_engulfing_strict
# ---------------------------------------------------------------------------
# Brooks + Grimes: Body of bar N must FULLY engulf body of bar N-1, opposite color.
# Current code (bullish_engulfing): open <= prev_close AND close >= prev_open
#   This is body-to-body engulfment (not range-to-range).
#   prev_bearish: prev_close < prev_open
#   cur_bullish: close > open
#   engulf: open <= prev_close AND close >= prev_open
# Tests: boundary (equal close), 1-pip overlap.

class TestEngulfingStrict:
    """Engulfing pattern tests against strict book definitions."""

    def test_bullish_engulfing_clear(self):
        """
        Clear bullish engulfing:
          bar 0: bearish o=105, c=100  (body 100..105)
          bar 1: bullish o=99, c=106   (body 99..106 fully engulfs 100..105)
        """
        df = _df(
            (105.0, 106.0, 99.0, 100.0),   # bar 0: bearish
            (99.0, 107.0, 98.5, 106.0),    # bar 1: bullish engulfing
        )
        result = bullish_engulfing(df)
        assert bool(result.iloc[1]), "Clear bullish engulfing should be detected"
        assert not bool(result.iloc[0]), "First bar should not trigger (no prev)"

    def test_bullish_engulfing_equal_close_boundary(self):
        """
        Boundary: current open == prev close (exactly touching).
        o_cur = prev_close, c_cur > prev_open → should still engulf.
        Current code: o <= prev_c → o == prev_c passes (≤).
        """
        df = _df(
            (105.0, 106.0, 99.0, 100.0),   # bearish: o=105, c=100
            (100.0, 107.0, 99.5, 106.0),   # o=100 == prev_c=100, c=106 >= prev_o=105 ✓
        )
        result = bullish_engulfing(df)
        assert bool(result.iloc[1]), (
            "Bullish engulfing with open == prev_close boundary should be detected"
        )

    def test_bullish_engulfing_one_pip_insufficient(self):
        """
        Bullish engulfing requires close >= prev_open.
        If close is just BELOW prev_open, it does NOT engulf.
        prev: o=105, c=100; current: o=99, c=104.99 (below prev_o=105)
        → NOT an engulfing bar.
        """
        df = _df(
            (105.0, 106.0, 99.0, 100.0),   # bearish: o=105, c=100
            (99.0, 105.5, 98.5, 104.99),   # c=104.99 < prev_o=105 → not engulfing
        )
        result = bullish_engulfing(df)
        assert not bool(result.iloc[1]), (
            "Bullish bar that does not close above prev_open should NOT engulf"
        )

    def test_bearish_engulfing_clear(self):
        """
        Clear bearish engulfing:
          bar 0: bullish o=100, c=105
          bar 1: bearish o=106, c=99 (body 99..106 engulfs 100..105)
        """
        df = _df(
            (100.0, 106.0, 99.0, 105.0),   # bullish
            (106.0, 107.0, 98.5, 99.0),    # bearish engulfing
        )
        result = bearish_engulfing(df)
        assert bool(result.iloc[1]), "Clear bearish engulfing should be detected"

    def test_bearish_engulfing_equal_open_boundary(self):
        """
        Boundary: current open == prev close.
        o_cur = prev_close, c_cur < prev_open → engulfing.
        """
        df = _df(
            (100.0, 106.0, 99.0, 105.0),   # bullish: o=100, c=105
            (105.0, 106.0, 98.5, 99.0),    # o=105==prev_c=105, c=99 <= prev_o=100 ✓
        )
        result = bearish_engulfing(df)
        assert bool(result.iloc[1]), (
            "Bearish engulfing with open == prev_close should be detected"
        )

    def test_same_color_does_not_engulf(self):
        """Both bars same color → not engulfing."""
        # Two bullish bars — bullish_engulfing requires prev bearish
        df = _df(
            (100.0, 106.0, 99.0, 105.0),   # bullish
            (104.0, 108.0, 103.0, 107.0),  # bullish again
        )
        assert not bool(bullish_engulfing(df).iloc[1]), (
            "Bullish engulfing requires prev bar to be bearish"
        )
        assert not bool(bearish_engulfing(df).iloc[1]), (
            "Bearish engulfing requires prev bar to be bullish"
        )

    def test_first_bar_never_engulfs(self):
        """First bar has no previous bar — must return False."""
        df = _df((105.0, 107.0, 98.0, 99.0))
        assert not bool(bullish_engulfing(df).iloc[0])
        assert not bool(bearish_engulfing(df).iloc[0])


# ---------------------------------------------------------------------------
# 3. test_inside_bar_ii_iii
# ---------------------------------------------------------------------------
# Brooks: Inside bar = high < prev high AND low > prev low (strict inequality).
# "ii" = two consecutive inside bars.
# "iii" = three consecutive inside bars.

class TestInsideBarIiIii:
    """Inside bar, ii and iii setup tests against Brooks definition."""

    def test_single_inside_bar(self):
        """Basic inside bar: bar1.high < bar0.high AND bar1.low > bar0.low."""
        df = _df(
            (100.0, 110.0, 90.0, 105.0),    # bar 0: mother bar (wide)
            (103.0, 108.0, 95.0, 104.0),    # bar 1: inside (108<110, 95>90) ✓
            (104.0, 112.0, 94.0, 111.0),    # bar 2: not inside (112>110)
        )
        flags = inside_bar(df)
        assert not bool(flags.iloc[0]), "First bar has no prev → False"
        assert bool(flags.iloc[1]), "Bar 1 should be inside bar"
        assert not bool(flags.iloc[2]), "Bar 2 is not inside (high > prev high)"

    def test_ii_two_consecutive_inside_bars(self):
        """
        Brooks 'ii': bar2 inside bar1, AND bar1 inside bar0.
        Both bar1 and bar2 should show True in inside_bar().
        The ii setup's effective range is bar2 (the final inside bar).
        """
        df = _df(
            (100.0, 110.0, 90.0, 105.0),    # bar 0: mother
            (103.0, 108.0, 95.0, 104.0),    # bar 1: inside bar0 ✓
            (103.5, 106.0, 96.0, 104.5),    # bar 2: inside bar1 ✓ (ii)
            (105.0, 115.0, 102.0, 114.0),   # bar 3: breakout
        )
        flags = inside_bar(df)
        assert bool(flags.iloc[1]), "Bar 1 is inside bar 0"
        assert bool(flags.iloc[2]), "Bar 2 is inside bar 1 — ii formation complete"
        assert not bool(flags.iloc[3]), "Bar 3 breaks out — not inside"

        # Detect ii: two consecutive inside bar flags
        consecutive_count = 0
        max_consecutive = 0
        for val in flags:
            if val:
                consecutive_count += 1
                max_consecutive = max(max_consecutive, consecutive_count)
            else:
                consecutive_count = 0
        assert max_consecutive >= 2, "Should detect 2 consecutive inside bars (ii)"

    def test_iii_three_consecutive_inside_bars(self):
        """Brooks 'iii': three consecutive inside bars, each inside the previous."""
        df = _df(
            (100.0, 110.0, 90.0, 105.0),    # bar 0: mother
            (103.0, 108.0, 95.0, 104.0),    # bar 1: inside bar0
            (103.5, 106.0, 96.0, 104.5),    # bar 2: inside bar1
            (103.8, 105.0, 97.0, 104.2),    # bar 3: inside bar2 (iii)
            (105.5, 112.0, 103.5, 111.0),   # bar 4: breakout
        )
        flags = inside_bar(df)
        assert bool(flags.iloc[1])
        assert bool(flags.iloc[2])
        assert bool(flags.iloc[3]), "Bar 3 should be inside bar 2 — iii formation"
        assert not bool(flags.iloc[4]), "Bar 4 breaks out"

        # Count max consecutive
        consecutive_count = 0
        max_consecutive = 0
        for val in flags:
            if val:
                consecutive_count += 1
                max_consecutive = max(max_consecutive, consecutive_count)
            else:
                consecutive_count = 0
        assert max_consecutive >= 3, "Should detect 3 consecutive inside bars (iii)"

    def test_inside_bar_equal_high_is_not_inside(self):
        """
        Brooks: strict inequality — equal high means NOT inside.
        bar1.high == bar0.high → not inside (fails high < prev_high).
        """
        df = _df(
            (100.0, 110.0, 90.0, 105.0),    # bar 0
            (103.0, 110.0, 95.0, 104.0),    # bar 1: high == prev_high → NOT inside
        )
        flags = inside_bar(df)
        assert not bool(flags.iloc[1]), (
            "Equal high (bar1.high == bar0.high) should NOT be inside bar "
            "(Brooks uses strict <)"
        )

    def test_inside_bar_equal_low_is_not_inside(self):
        """Equal low → NOT inside bar (strict > required)."""
        df = _df(
            (100.0, 110.0, 90.0, 105.0),    # bar 0
            (103.0, 108.0, 90.0, 104.0),    # bar 1: low == prev_low → NOT inside
        )
        flags = inside_bar(df)
        assert not bool(flags.iloc[1]), (
            "Equal low (bar1.low == bar0.low) should NOT be inside bar "
            "(Brooks uses strict >)"
        )

    def test_one_inside_bar_not_ii(self):
        """
        A single inside bar is NOT an ii setup.
        The next bar must also be inside for ii to form.
        """
        df = _df(
            (100.0, 110.0, 90.0, 105.0),    # bar 0: mother
            (103.0, 108.0, 95.0, 104.0),    # bar 1: single inside bar
            (104.0, 112.0, 93.0, 111.0),    # bar 2: NOT inside (wide)
        )
        flags = inside_bar(df)
        # Only bar 1 is inside; bar 2 is not → max consecutive = 1, not ii
        consecutive_count = 0
        max_consecutive = 0
        for val in flags:
            if val:
                consecutive_count += 1
                max_consecutive = max(max_consecutive, consecutive_count)
            else:
                consecutive_count = 0
        assert max_consecutive < 2, "Single inside bar should NOT qualify as ii"


# ---------------------------------------------------------------------------
# 4. test_outside_bar
# ---------------------------------------------------------------------------
# Brooks: outside bar = high > prev_high AND low < prev_low (strict).
# Boundary: equal high → NOT outside.

def _outside_bar(df: pd.DataFrame) -> pd.Series:
    """Outside bar: current high > prev high AND current low < prev low."""
    h = df["high"]
    l = df["low"]
    flag = (h > h.shift(1)) & (l < l.shift(1))
    return flag.fillna(False).astype(bool)


class TestOutsideBar:
    """Outside bar detection against Brooks strict definition."""

    def test_outside_bar_clear(self):
        """Clear outside bar: high > prev_high AND low < prev_low."""
        df = _df(
            (100.0, 105.0, 95.0, 102.0),    # bar 0
            (101.0, 107.0, 93.0, 103.0),    # bar 1: 107>105 and 93<95 → outside ✓
        )
        flags = _outside_bar(df)
        assert bool(flags.iloc[1]), "Clear outside bar should be detected"
        assert not bool(flags.iloc[0]), "First bar has no prev"

    def test_outside_bar_equal_high_not_outside(self):
        """
        Brooks: strict inequality. Equal high → NOT outside.
        bar1.high == bar0.high → fails outside bar criterion.
        """
        df = _df(
            (100.0, 105.0, 95.0, 102.0),    # bar 0
            (101.0, 105.0, 93.0, 103.0),    # bar 1: high == prev (not strictly >)
        )
        flags = _outside_bar(df)
        assert not bool(flags.iloc[1]), (
            "Equal high should NOT qualify as outside bar (Brooks strict >)"
        )

    def test_outside_bar_equal_low_not_outside(self):
        """Equal low → NOT outside bar."""
        df = _df(
            (100.0, 105.0, 95.0, 102.0),
            (101.0, 107.0, 95.0, 103.0),    # low == prev_low → not outside
        )
        flags = _outside_bar(df)
        assert not bool(flags.iloc[1]), (
            "Equal low should NOT qualify as outside bar (Brooks strict <)"
        )

    def test_inside_bar_is_not_outside_bar(self):
        """An inside bar cannot be an outside bar (mutually exclusive)."""
        df = _df(
            (100.0, 110.0, 90.0, 105.0),
            (103.0, 108.0, 95.0, 104.0),    # inside bar
        )
        outside_flags = _outside_bar(df)
        inside_flags = inside_bar(df)
        # Both should never be True for the same bar
        overlap = outside_flags & inside_flags
        assert not bool(overlap.any()), (
            "Inside bar and outside bar should never be True simultaneously"
        )

    def test_multi_bar_outside_detection(self):
        """Test outside bar detection in a multi-bar series."""
        df = _df(
            (100.0, 105.0, 95.0, 102.0),    # bar 0: neutral
            (101.0, 107.0, 93.0, 104.0),    # bar 1: outside (>105, <95)
            (103.0, 106.0, 94.0, 105.0),    # bar 2: NOT outside (106<107 or 94>93)
            (104.0, 109.0, 91.0, 106.0),    # bar 3: outside (>107? no, >106 yes; <93? yes)
        )
        # bar 3: h=109 > prev_h=106? yes; l=91 < prev_l=94? yes → outside
        flags = _outside_bar(df)
        assert bool(flags.iloc[1]), "Bar 1 should be outside"
        assert not bool(flags.iloc[0])
        assert bool(flags.iloc[3]), "Bar 3 should be outside vs bar 2"


# ---------------------------------------------------------------------------
# 5. test_lookahead_bias
# ---------------------------------------------------------------------------
# Critical: signal at bar t must only use data up to bar t.
# Method: detect on full series, then truncate at t+1, re-detect → must match.

class TestLookaheadBias:
    """Verify that no pattern detector uses future bars (lookahead bias)."""

    def _run_lookahead_check(self, detector_fn, df: pd.DataFrame, target_bar: int):
        """
        Run detector on full df and on df[:target_bar+1].
        The signal at target_bar must be identical in both runs.
        """
        full_result = detector_fn(df)
        truncated = df.iloc[: target_bar + 1].copy()
        trunc_result = detector_fn(truncated)
        return full_result.iloc[target_bar], trunc_result.iloc[target_bar]

    def test_bullish_pin_bar_no_lookahead(self):
        """Bullish pin bar signal at bar 2 must not depend on bar 3+."""
        df = _df(
            (100.0, 101.0, 99.5, 100.3),
            (100.0, 101.5, 91.0, 101.0),    # bullish pin at bar 1
            (101.0, 102.0, 100.0, 101.5),   # bar 2: future
            (101.5, 103.0, 101.0, 102.5),   # bar 3: future
        )
        full, trunc = self._run_lookahead_check(bullish_pin_bar, df, target_bar=1)
        assert full == trunc, (
            f"Lookahead bias detected in bullish_pin_bar: "
            f"full={full}, truncated={trunc}"
        )

    def test_bearish_pin_bar_no_lookahead(self):
        """Bearish pin bar at bar 1 must not depend on bars 2+."""
        df = _df(
            (100.0, 101.0, 99.5, 100.3),
            (102.0, 109.0, 99.0, 100.0),    # bearish pin at bar 1
            (100.0, 101.0, 98.5, 99.0),
            (99.0, 100.0, 97.0, 97.5),
        )
        full, trunc = self._run_lookahead_check(bearish_pin_bar, df, target_bar=1)
        assert full == trunc, (
            f"Lookahead bias in bearish_pin_bar: full={full}, trunc={trunc}"
        )

    def test_inside_bar_no_lookahead(self):
        """Inside bar at bar 1 must not depend on bar 2+."""
        df = _df(
            (100.0, 110.0, 90.0, 105.0),
            (103.0, 108.0, 95.0, 104.0),    # inside bar at 1
            (103.5, 106.0, 96.0, 104.5),    # inside bar at 2 (ii)
            (105.0, 115.0, 102.0, 114.0),   # breakout
        )
        full, trunc = self._run_lookahead_check(inside_bar, df, target_bar=1)
        assert full == trunc, (
            f"Lookahead bias in inside_bar: full={full}, trunc={trunc}"
        )

    def test_bullish_engulfing_no_lookahead(self):
        """Bullish engulfing at bar 2 must not depend on bar 3+."""
        df = _df(
            (100.0, 101.0, 99.0, 100.5),
            (105.0, 106.0, 99.0, 100.0),    # bearish
            (99.0, 107.0, 98.5, 106.0),     # bullish engulfing at bar 2
            (106.0, 108.0, 105.0, 107.5),   # future
        )
        full, trunc = self._run_lookahead_check(bullish_engulfing, df, target_bar=2)
        assert full == trunc, (
            f"Lookahead bias in bullish_engulfing: full={full}, trunc={trunc}"
        )

    def test_bearish_engulfing_no_lookahead(self):
        """Bearish engulfing at bar 2 must not depend on bar 3+."""
        df = _df(
            (100.0, 101.0, 99.0, 100.5),
            (100.0, 106.0, 99.0, 105.0),    # bullish
            (106.0, 107.0, 98.5, 99.0),     # bearish engulfing at bar 2
            (99.0, 100.5, 97.0, 97.5),      # future
        )
        full, trunc = self._run_lookahead_check(bearish_engulfing, df, target_bar=2)
        assert full == trunc, (
            f"Lookahead bias in bearish_engulfing: full={full}, trunc={trunc}"
        )

    def test_swing_high_lookahead_awareness(self):
        """
        Swing highs by definition require future bars (n bars to the right).
        For n=2, bar t is confirmed a swing high only at t+2.
        Truncating to t+1 should NOT show bar t as swing high (incomplete data).

        This documents expected behavior: swing_highs IS intentionally "lookahead"
        in the sense that confirmation requires future bars, but this is design-by-
        contract (labeled in structure.py comments).
        """
        df_full = pd.DataFrame({
            "open":  [1.0, 2.0, 5.0, 3.0, 2.0],
            "high":  [1.5, 2.5, 5.5, 3.5, 2.5],
            "low":   [0.5, 1.5, 4.5, 2.5, 1.5],
            "close": [1.2, 2.2, 5.2, 3.2, 2.2],
        })
        sh_full = swing_highs(df_full, n=2)
        # Bar index 2 (h=5.5) should be swing high in full series
        assert bool(sh_full.iloc[2]), "Bar 2 should be swing high with n=2 (2 bars right available)"

        # Truncate to bar 3 (only 1 bar to the right of bar 2)
        df_partial = df_full.iloc[:4].copy()
        sh_partial = swing_highs(df_partial, n=2)
        # With only 1 bar to the right, the rolling right_max needs n=2 bars,
        # so bar 2 should NOT be detected as swing high yet.
        assert not bool(sh_partial.iloc[2]), (
            "Swing high at bar 2 should NOT be confirmed with only 1 right bar "
            "(requires n=2 right bars; this is expected behavior per structure.py)"
        )


# ---------------------------------------------------------------------------
# 6. test_swing_high_low
# ---------------------------------------------------------------------------
# Brooks: n-bar fractal swing high = middle bar high > n bars left + n bars right.
# Default n=2: bar t.high > max(t-1.high, t-2.high) AND > max(t+1.high, t+2.high).

class TestSwingHighLow:
    """Swing high/low fractal tests (n=2 default — 5-bar window)."""

    def test_5bar_fractal_swing_high(self):
        """
        5-bar fractal (n=2): middle bar (index 2) has the highest high.
        Must be detected as swing high.
        """
        df = pd.DataFrame({
            "open":  [1.0, 2.0, 5.0, 2.0, 1.0],
            "high":  [1.5, 2.5, 5.5, 2.5, 1.5],
            "low":   [0.5, 1.5, 4.5, 1.5, 0.5],
            "close": [1.2, 2.2, 5.2, 2.2, 1.2],
        })
        sh = swing_highs(df, n=2)
        assert bool(sh.iloc[2]), "Bar 2 should be swing high (highest in 5-bar window)"
        # Bars 0,1,3,4 should NOT be swing highs
        assert not bool(sh.iloc[0])
        assert not bool(sh.iloc[1])
        assert not bool(sh.iloc[3])
        assert not bool(sh.iloc[4])

    def test_5bar_fractal_swing_low(self):
        """5-bar fractal swing low: middle bar has the lowest low."""
        df = pd.DataFrame({
            "open":  [5.0, 4.0, 1.0, 4.0, 5.0],
            "high":  [5.5, 4.5, 1.5, 4.5, 5.5],
            "low":   [4.5, 3.5, 0.5, 3.5, 4.5],
            "close": [5.2, 4.2, 1.2, 4.2, 5.2],
        })
        sl = swing_lows(df, n=2)
        assert bool(sl.iloc[2]), "Bar 2 should be swing low (lowest in 5-bar window)"
        assert not bool(sl.iloc[0])
        assert not bool(sl.iloc[1])
        assert not bool(sl.iloc[3])
        assert not bool(sl.iloc[4])

    def test_swing_high_equal_adjacent_not_swing(self):
        """
        If bar t.high == any adjacent bar's high, it is NOT a strict swing high
        (must be STRICTLY greater than all neighbors).
        """
        df = pd.DataFrame({
            "open":  [1.0, 2.0, 5.0, 5.0, 1.0],
            "high":  [1.5, 2.5, 5.5, 5.5, 1.5],  # bar 2 and bar 3 tie
            "low":   [0.5, 1.5, 4.5, 4.5, 0.5],
            "close": [1.2, 2.2, 5.2, 5.2, 1.2],
        })
        sh = swing_highs(df, n=2)
        # Bar 2's right neighbor (bar 3) has equal high → NOT strictly greater
        # Code: h > right_max — if right_max == h, fails
        assert not bool(sh.iloc[2]), (
            "Bar with equal adjacent high should NOT be swing high (requires strict >)"
        )

    def test_swing_high_multiple_in_series(self):
        """Multiple swing highs in a longer series."""
        df = pd.DataFrame({
            "open":  [1, 2, 5, 2, 1, 3, 7, 3, 2],
            "high":  [1, 2, 5, 2, 1, 3, 7, 3, 2],
            "low":   [0, 1, 4, 1, 0, 2, 6, 2, 1],
            "close": [1, 2, 5, 2, 1, 3, 7, 3, 2],
        }, dtype=float)
        sh = swing_highs(df, n=2)
        assert bool(sh.iloc[2]), "Bar 2 (h=5) is swing high"
        assert bool(sh.iloc[6]), "Bar 6 (h=7) is swing high"
        # Non-swing bars
        assert not bool(sh.iloc[0])
        assert not bool(sh.iloc[4])

    def test_swing_low_multiple_in_series(self):
        """Multiple swing lows in a longer series.

        Series: l = [5, 4, 1, 4, 5, 3, 7, 3, 5]
          bar2 (l=1): left=[5,4], right=[4,5] → 1 < min(4,5)=4 ✓ → swing low
          bar5 (l=3): left=[4,5], right=[7,3] → right_min=3 → 3 < 3 fails (strict)
          bar7 (l=3): left=[3,7], right=[3,5] → left_min=3 → 3 < 3 fails (strict)

        Better: l = [5, 4, 1, 4, 5, 2, 7, 2, 5]
          bar2 (l=1): left=[5,4], right=[4,5] → 1 < 4 ✓ → swing low ✓
          bar5 (l=2): left=[4,5], right=[7,2] → right_min=2 → 2 < 2 fails

        Use: l = [5, 4, 1, 4, 5, 2, 6, 4, 5]
          bar2 (l=1): left_min=min(5,4)=4, right_min=min(4,5)=4 → 1<4 ✓, 1<4 ✓
          bar5 (l=2): left_min=min(4,5)=4, right_min=min(6,4)=4 → 2<4 ✓, 2<4 ✓
        """
        df = pd.DataFrame({
            "open":  [5, 4, 1, 4, 5, 2, 6, 4, 5],
            "high":  [5, 4, 1, 4, 5, 2, 6, 4, 5],
            "low":   [5, 4, 1, 4, 5, 2, 6, 4, 5],
            "close": [5, 4, 1, 4, 5, 2, 6, 4, 5],
        }, dtype=float)
        sl = swing_lows(df, n=2)
        assert bool(sl.iloc[2]), "Bar 2 (l=1) is swing low"
        assert bool(sl.iloc[5]), "Bar 5 (l=2) is swing low"

    def test_swing_high_minimum_series_length(self):
        """Series shorter than 2n+1 bars cannot produce a confirmed swing high."""
        df = pd.DataFrame({
            "open":  [1.0, 5.0, 1.0],
            "high":  [1.5, 5.5, 1.5],
            "low":   [0.5, 4.5, 0.5],
            "close": [1.2, 5.2, 1.2],
        })
        # n=2 requires 2 bars to the right of the candidate; only 1 available → NaN/False
        sh = swing_highs(df, n=2)
        assert not bool(sh.iloc[1]), (
            "With only 1 bar to the right, n=2 swing high cannot be confirmed"
        )

    def test_n1_fractal_3bar_window(self):
        """With n=1: simple 3-bar fractal (higher than immediate neighbors)."""
        df = pd.DataFrame({
            "open":  [1.0, 5.0, 1.0],
            "high":  [1.5, 5.5, 1.5],
            "low":   [0.5, 4.5, 0.5],
            "close": [1.2, 5.2, 1.2],
        })
        sh = swing_highs(df, n=1)
        assert bool(sh.iloc[1]), "3-bar fractal with n=1 should detect center bar"


# ---------------------------------------------------------------------------
# 7. Additional edge cases: book-specific rules
# ---------------------------------------------------------------------------

class TestBookSpecificRules:
    """Edge cases derived directly from book definitions."""

    def test_brooks_doji_definition(self):
        """
        Brooks: doji body/range < 0.25.
        Grimes: body/range < 0.05 (strict).
        Current code uses 0.05 as default.
        Test: body/range = 0.10 → fails code default (0.05) but passes Brooks (0.25).
        This is flagged as a potential mismatch — code is STRICTER than Brooks.
        """
        from price_action.signals.candles import doji

        # body = 0.20, range = 2.0 → body/range = 0.10
        df = _df((100.0, 101.5, 99.5, 100.2))  # body=0.2, range=2, ratio=0.10

        # With code default (0.05): should NOT detect
        result_default = doji(df)
        assert not bool(result_default.iloc[0]), (
            "With default threshold 0.05, body/range=0.10 should NOT detect doji"
        )

        # With Brooks threshold (0.25): should detect
        result_brooks = doji(df, {"body_to_range_max": 0.25})
        assert bool(result_brooks.iloc[0]), (
            "With Brooks threshold 0.25, body/range=0.10 should detect doji — "
            "NOTE: default code threshold (0.05) is STRICTER than Brooks (0.25)"
        )

    def test_brooks_reversal_bar_close_in_opposite_third(self):
        """
        Brooks: reversal bar close should be in the opposite ≤25% of range.
        Grimes: close in opposite 1/3 of range.
        Current bearish_pin_bar does NOT explicitly check close position.
        This tests whether the existing range-ratio checks implicitly enforce it.

        Bearish pin: upper wick dominant, close near the bottom.
        If close is near the TOP (not near the bottom), the bar has upper wick
        but doesn't close opposite → body would be small AND upper wick dominates,
        so body_ratio check still passes. But it's not a "true" reversal per Brooks.

        Example: o=99, h=110, l=98.5, c=109.5 (close near top, small upper wick)
          body = |109.5-99| = 10.5, range = 11.5, body/range ≈ 0.91 > 0.33 → FAILS
          So the body check prevents false bearish pin when close is at top. ✓

        Example: o=100, c=100.5 (bearish? no, c>o → bullish)
        True test: bearish bar with small body and big wick but close NOT near bottom:
          o=108, c=107, h=110, l=106 → body=1, upper=2, lower=1, range=4
          body/range=0.25 ≤ 0.33 ✓, upper/range=0.50 < 0.60 → FAILS upper check
        """
        # Bar with moderate upper wick (not dominant enough)
        df = _df(
            (100.0, 101.0, 99.5, 100.3),
            (108.0, 110.0, 106.0, 107.0),  # upper_wick=2, range=4, upper/range=0.50 < 0.60
        )
        result = bearish_pin_bar(df)
        assert not bool(result.iloc[1]), (
            "Bar with upper_wick/range=0.50 should NOT detect bearish pin "
            "(threshold is 0.60 minimum)"
        )

    def test_volman_inside_bar_full_containment(self):
        """
        Volman: inside bar is 'full containment' — same as Brooks.
        high < prev_high AND low > prev_low (strict).
        """
        # Valid full containment
        df_valid = _df(
            (100.0, 110.0, 90.0, 105.0),
            (103.0, 108.0, 95.0, 104.0),
        )
        assert bool(inside_bar(df_valid).iloc[1])

        # Partial overlap (only one side inside) — NOT inside bar
        df_partial = _df(
            (100.0, 110.0, 90.0, 105.0),
            (103.0, 112.0, 95.0, 104.0),   # high > prev_high → not inside
        )
        assert not bool(inside_bar(df_partial).iloc[1])

    def test_engulfing_body_vs_range_distinction(self):
        """
        Grimes distinguishes body engulfing vs range engulfing.
        Current code: body engulfing (uses open/close, not high/low).
        This test verifies: a bar that engulfs the BODY but not the full range
        is still correctly detected as engulfing by current code.
        """
        # Bar 0: bearish, range [99..106], body [100..105]
        # Bar 1: bullish, range [99.5..105.5], body [99..106]
        # Bar 1 body engulfs bar 0 body, but bar 1 range does NOT engulf bar 0 range
        df = _df(
            (105.0, 106.0, 99.0, 100.0),   # bearish: body 100..105
            (99.0, 105.5, 99.5, 106.0),    # bullish: body 99..106 engulfs 100..105
        )
        result = bullish_engulfing(df)
        assert bool(result.iloc[1]), (
            "Body engulfing (not range engulfing) should be detected — "
            "current code uses body-to-body comparison which aligns with Grimes"
        )
