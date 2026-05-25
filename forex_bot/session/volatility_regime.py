"""Session-aware ATR percentile regime."""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..indicators.ohlc import atr
from .tagger import tag_session_series


def session_atr_regime(df: pd.DataFrame, atr_period: int = 14, lookback_days: int = 60) -> pd.DataFrame:
    """For each bar, compute session-conditional ATR percentile.

    Returns columns: session, atr, atr_pct (percentile of ATR within same-session bars over lookback).
    """
    a = atr(df, atr_period)
    sess = tag_session_series(pd.DatetimeIndex(df.index))
    bars_per_day = 96  # 15m
    window = lookback_days * bars_per_day
    grouped = []
    for sname in ("asia", "london", "london_ny_overlap", "ny", "off"):
        mask = sess == sname
        sub = a.where(mask)
        rolled = sub.rolling(window, min_periods=int(window * 0.2)).apply(
            lambda x: (x.iloc[-1] <= x.dropna()).mean() if x.dropna().size else np.nan, raw=False
        )
        grouped.append(rolled.rename(sname))
    pct_df = pd.concat(grouped, axis=1)
    atr_pct = pct_df.bfill(axis=1).iloc[:, 0]
    return pd.DataFrame({"session": sess, "atr": a, "atr_pct": atr_pct})
