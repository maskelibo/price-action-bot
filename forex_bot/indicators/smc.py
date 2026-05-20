"""Smart Money Concepts: order blocks, fair value gaps, liquidity sweeps, BOS, CHoCH, premium/discount.

Calibrated for forex microstructure (less aggressive wicks than crypto):
- OB: last opposite-direction candle before a strong impulsive leg.
- FVG: gap between candle t-2 high and candle t low (bullish) — 3-candle pattern.
- Liquidity sweep: wick through prior equal-high/low cluster + close back inside.
- BOS: break of prior swing high/low in trending direction.
- CHoCH: opposite-direction break of internal swing (trend reversal hint).
- Premium/Discount: midpoint of dealing range.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .ohlc import atr, swing_highs, swing_lows


def bullish_order_block(df: pd.DataFrame, impulse_atr_mult: float = 1.2, lookback: int = 30) -> pd.Series:
    """Last bearish candle before bullish impulse (close > t-1 high + impulse_atr_mult*ATR)."""
    a = atr(df, 14)
    impulse = df["close"] > (df["high"].shift(1) + impulse_atr_mult * a.shift(1))
    bearish_prev = df["close"].shift(1) < df["open"].shift(1)
    return (impulse & bearish_prev).fillna(False)


def bearish_order_block(df: pd.DataFrame, impulse_atr_mult: float = 1.2, lookback: int = 30) -> pd.Series:
    a = atr(df, 14)
    impulse = df["close"] < (df["low"].shift(1) - impulse_atr_mult * a.shift(1))
    bullish_prev = df["close"].shift(1) > df["open"].shift(1)
    return (impulse & bullish_prev).fillna(False)


def fair_value_gap(df: pd.DataFrame, min_size_atr: float = 0.3) -> pd.DataFrame:
    """Detect FVG (Imbalance): 3-bar pattern where t-2 high < t low (bullish FVG) or t-2 low > t high (bearish).

    Returns DataFrame with columns: bull_fvg, bear_fvg, fvg_size_atr.
    """
    a = atr(df, 14)
    h_2 = df["high"].shift(2)
    l_2 = df["low"].shift(2)
    h_0 = df["high"]
    l_0 = df["low"]
    bull_gap = l_0 - h_2
    bear_gap = l_2 - h_0
    bull = (bull_gap > min_size_atr * a)
    bear = (bear_gap > min_size_atr * a)
    return pd.DataFrame({
        "bull_fvg": bull.fillna(False),
        "bear_fvg": bear.fillna(False),
        "fvg_size_atr": pd.concat([bull_gap, bear_gap], axis=1).max(axis=1) / a,
    }, index=df.index)


def liquidity_sweep_high(df: pd.DataFrame, lookback: int = 20, close_pullback_pct: float = 0.5) -> pd.Series:
    """Sweep of prior swing-high: high > rolling-max(prior n) but close < that level."""
    prior_max = df["high"].rolling(lookback, min_periods=lookback).max().shift(1)
    pierce = df["high"] > prior_max
    close_back = df["close"] < (prior_max - (df["high"] - prior_max) * close_pullback_pct)
    return (pierce & close_back).fillna(False)


def liquidity_sweep_low(df: pd.DataFrame, lookback: int = 20, close_pullback_pct: float = 0.5) -> pd.Series:
    prior_min = df["low"].rolling(lookback, min_periods=lookback).min().shift(1)
    pierce = df["low"] < prior_min
    close_back = df["close"] > (prior_min + (prior_min - df["low"]) * close_pullback_pct)
    return (pierce & close_back).fillna(False)


def bos_bullish(df: pd.DataFrame, swing_n: int = 3) -> pd.Series:
    """Break of structure (bullish): close > most recent swing high (CAUSAL).

    Uses causal swing_highs (only looks back). No future leak.
    """
    swh = swing_highs(df["high"], n=swing_n, causal=True)
    last_swh = df["high"].where(swh).ffill().shift(1)
    return (df["close"] > last_swh).fillna(False)


def bos_bearish(df: pd.DataFrame, swing_n: int = 3) -> pd.Series:
    swl = swing_lows(df["low"], n=swing_n, causal=True)
    last_swl = df["low"].where(swl).ffill().shift(1)
    return (df["close"] < last_swl).fillna(False)


def choch_bullish(df: pd.DataFrame, swing_n: int = 3) -> pd.Series:
    """CHoCH bull: after lower-highs sequence, close breaks the most recent swing high (CAUSAL)."""
    swh = swing_highs(df["high"], n=swing_n, causal=True)
    swh_levels = df["high"].where(swh).ffill().shift(1)
    last2_swh = swh_levels.where(swh.shift(swing_n + 1)).ffill().shift(1)
    lower_high_seq = swh_levels < last2_swh
    return ((df["close"] > swh_levels) & lower_high_seq.fillna(False)).fillna(False)


def choch_bearish(df: pd.DataFrame, swing_n: int = 3) -> pd.Series:
    swl = swing_lows(df["low"], n=swing_n, causal=True)
    swl_levels = df["low"].where(swl).ffill().shift(1)
    last2_swl = swl_levels.where(swl.shift(swing_n + 1)).ffill().shift(1)
    higher_low_seq = swl_levels > last2_swl
    return ((df["close"] < swl_levels) & higher_low_seq.fillna(False)).fillna(False)


def premium_discount_zone(df: pd.DataFrame, lookback: int = 40) -> pd.DataFrame:
    """Compute dealing range midpoint over lookback; classify price into premium / equilibrium / discount.

    Returns columns: zone (str), midpoint, range_high, range_low.
    """
    rh = df["high"].rolling(lookback, min_periods=lookback).max()
    rl = df["low"].rolling(lookback, min_periods=lookback).min()
    mid = (rh + rl) / 2.0
    zone = pd.Series("equilibrium", index=df.index)
    zone[df["close"] > mid + 0.2 * (rh - mid)] = "premium"
    zone[df["close"] < mid - 0.2 * (mid - rl)] = "discount"
    return pd.DataFrame({"zone": zone, "midpoint": mid, "range_high": rh, "range_low": rl})
