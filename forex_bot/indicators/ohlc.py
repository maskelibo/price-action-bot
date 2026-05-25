"""OHLC base indicators: ATR, EMA, SMA, RSI, swings, true range."""
from __future__ import annotations

import numpy as np
import pandas as pd


def true_range(df: pd.DataFrame) -> pd.Series:
    h, l, c = df["high"], df["low"], df["close"]
    prev_c = c.shift(1)
    tr = pd.concat([
        (h - l).abs(),
        (h - prev_c).abs(),
        (l - prev_c).abs(),
    ], axis=1).max(axis=1)
    return tr


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    tr = true_range(df)
    return tr.ewm(span=period, adjust=False, min_periods=period).mean()


def ema(s: pd.Series, period: int) -> pd.Series:
    return s.ewm(span=period, adjust=False, min_periods=period).mean()


def sma(s: pd.Series, period: int) -> pd.Series:
    return s.rolling(period, min_periods=period).mean()


def rsi(s: pd.Series, period: int = 14) -> pd.Series:
    delta = s.diff()
    up = delta.clip(lower=0.0)
    dn = -delta.clip(upper=0.0)
    roll_up = up.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()
    roll_dn = dn.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()
    rs = roll_up / roll_dn.replace(0.0, np.nan)
    return 100.0 - (100.0 / (1.0 + rs))


def swing_highs(h: pd.Series, n: int = 2, causal: bool = True) -> pd.Series:
    """Fractal swing high. Causal (default): only look BACK (i-n .. i-1).
    Non-causal (causal=False): look both sides (i±n) — uses future bars; only for analytics.

    Causal version flags bar i when h[i] is the max of the last n+1 bars (i-n..i).
    Lookahead-safe.
    """
    arr = h.to_numpy()
    out = np.zeros(len(arr), dtype=bool)
    if causal:
        for i in range(n, len(arr)):
            center = arr[i]
            left = arr[i - n: i]
            if center > left.max():
                out[i] = True
    else:
        for i in range(n, len(arr) - n):
            center = arr[i]
            left = arr[i - n: i]
            right = arr[i + 1: i + n + 1]
            if center > left.max() and center > right.max():
                out[i] = True
    return pd.Series(out, index=h.index)


def swing_lows(l: pd.Series, n: int = 2, causal: bool = True) -> pd.Series:
    """Causal-default swing low (mirror of swing_highs)."""
    arr = l.to_numpy()
    out = np.zeros(len(arr), dtype=bool)
    if causal:
        for i in range(n, len(arr)):
            center = arr[i]
            left = arr[i - n: i]
            if center < left.min():
                out[i] = True
    else:
        for i in range(n, len(arr) - n):
            center = arr[i]
            left = arr[i - n: i]
            right = arr[i + 1: i + n + 1]
            if center < left.min() and center < right.min():
                out[i] = True
    return pd.Series(out, index=l.index)
