"""Vectorized price action patterns (lookahead-free; decisions on t use t close only)."""
from __future__ import annotations

import numpy as np
import pandas as pd


def _bar_metrics(df: pd.DataFrame):
    o, h, l, c = df["open"], df["high"], df["low"], df["close"]
    rng = (h - l).replace(0.0, np.nan)
    body = (c - o).abs()
    upper_wick = h - c.where(c >= o, o)
    lower_wick = c.where(c <= o, o) - l
    body_pct = body / rng
    upper_pct = upper_wick / rng
    lower_pct = lower_wick / rng
    return o, h, l, c, rng, body, upper_wick, lower_wick, body_pct, upper_pct, lower_pct


def bullish_pin_bar(
    df: pd.DataFrame,
    body_max_pct: float = 0.33,
    lower_wick_min_pct: float = 0.55,
    upper_wick_max_pct: float = 0.25,
) -> pd.Series:
    _o, _h, _l, _c, _rng, _body, _uw, _lw, body_pct, upper_pct, lower_pct = _bar_metrics(df)
    cond = (body_pct <= body_max_pct) & (lower_pct >= lower_wick_min_pct) & (upper_pct <= upper_wick_max_pct)
    return cond.fillna(False)


def bearish_pin_bar(
    df: pd.DataFrame,
    body_max_pct: float = 0.33,
    upper_wick_min_pct: float = 0.55,
    lower_wick_max_pct: float = 0.25,
) -> pd.Series:
    _o, _h, _l, _c, _rng, _body, _uw, _lw, body_pct, upper_pct, lower_pct = _bar_metrics(df)
    cond = (body_pct <= body_max_pct) & (upper_pct >= upper_wick_min_pct) & (lower_pct <= lower_wick_max_pct)
    return cond.fillna(False)


def bullish_engulfing(df: pd.DataFrame) -> pd.Series:
    o, c = df["open"], df["close"]
    o_prev, c_prev = o.shift(1), c.shift(1)
    cur_bull = c > o
    prev_bear = c_prev < o_prev
    engulfs = (o <= c_prev) & (c >= o_prev)
    return (cur_bull & prev_bear & engulfs).fillna(False)


def bearish_engulfing(df: pd.DataFrame) -> pd.Series:
    o, c = df["open"], df["close"]
    o_prev, c_prev = o.shift(1), c.shift(1)
    cur_bear = c < o
    prev_bull = c_prev > o_prev
    engulfs = (o >= c_prev) & (c <= o_prev)
    return (cur_bear & prev_bull & engulfs).fillna(False)


def inside_bar(df: pd.DataFrame) -> pd.Series:
    """Current bar's high <= prev high AND low >= prev low."""
    h_prev = df["high"].shift(1)
    l_prev = df["low"].shift(1)
    return ((df["high"] <= h_prev) & (df["low"] >= l_prev)).fillna(False)


def fakey(df: pd.DataFrame) -> pd.Series:
    """Inside bar at t-1, false breakout + reversal at t.

    Pattern (Nial Fuller / Volman):
      t-2: mother bar
      t-1: inside bar
      t: high > t-1.high (or low < t-1.low) but close back inside mother bar range.
    """
    ib_prev = inside_bar(df).shift(1).fillna(False)
    mother_high = df["high"].shift(2)
    mother_low = df["low"].shift(2)
    h_prev = df["high"].shift(1)
    l_prev = df["low"].shift(1)
    h, l, c = df["high"], df["low"], df["close"]
    bull_fake = (l < l_prev) & (c >= l_prev) & (c <= mother_high)
    bear_fake = (h > h_prev) & (c <= h_prev) & (c >= mother_low)
    return (ib_prev & (bull_fake | bear_fake)).fillna(False)


def bullish_fakey(df: pd.DataFrame) -> pd.Series:
    ib_prev = inside_bar(df).shift(1).fillna(False)
    l_prev = df["low"].shift(1)
    mother_high = df["high"].shift(2)
    cond = ib_prev & (df["low"] < l_prev) & (df["close"] >= l_prev) & (df["close"] <= mother_high)
    return cond.fillna(False)


def bearish_fakey(df: pd.DataFrame) -> pd.Series:
    ib_prev = inside_bar(df).shift(1).fillna(False)
    h_prev = df["high"].shift(1)
    mother_low = df["low"].shift(2)
    cond = ib_prev & (df["high"] > h_prev) & (df["close"] <= h_prev) & (df["close"] >= mother_low)
    return cond.fillna(False)
