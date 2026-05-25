"""Volume proxy for forex (no real volume).

Three components:
1. tick_volume_zscore — Z-score of broker tick volume over rolling window.
2. range_expansion — current bar range vs ATR(14).
3. spread_widening — current spread vs typical (rolling median).

Combined into a "participation score" approximating real volume signal.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .ohlc import atr


def tick_volume_zscore(df: pd.DataFrame, window: int = 96) -> pd.Series:
    if "tick_volume" not in df.columns:
        return pd.Series(np.nan, index=df.index)
    tv = df["tick_volume"].astype(float)
    mu = tv.rolling(window, min_periods=window).mean()
    sd = tv.rolling(window, min_periods=window).std(ddof=0)
    z = (tv - mu) / sd.replace(0.0, np.nan)
    return z


def range_expansion(df: pd.DataFrame, atr_period: int = 14) -> pd.Series:
    a = atr(df, atr_period)
    rng = df["high"] - df["low"]
    return rng / a


def spread_widening(df: pd.DataFrame, window: int = 96) -> pd.Series:
    if "spread_pips" not in df.columns:
        return pd.Series(np.nan, index=df.index)
    s = df["spread_pips"].astype(float)
    med = s.rolling(window, min_periods=window).median()
    return s / med.replace(0.0, np.nan)


def participation_score(
    df: pd.DataFrame,
    tv_weight: float = 0.5,
    range_weight: float = 0.35,
    spread_weight: float = 0.15,
) -> pd.Series:
    """Combined volume-proxy score 0..1+. Higher = stronger participation.

    For ENTRY confluence: > 1.2 means above-average participation.
    """
    z = tick_volume_zscore(df).clip(-3, 5)
    rng = range_expansion(df).clip(0, 5)
    spr = spread_widening(df).clip(0.3, 3)
    z_norm = (z + 3.0) / 8.0
    rng_norm = rng / 2.5
    spr_inv = 1.0 / spr  # tight spread = good participation
    score = tv_weight * z_norm + range_weight * rng_norm + spread_weight * spr_inv
    return score
