"""Sinyal filtreleri: ATR eşiği, hacim z-score, EMA trend, volatilite rejimi."""
from __future__ import annotations

from typing import Literal

import numpy as np
import pandas as pd

from price_action.logging_config import logger
from price_action.signals.structure import ema

_ = logger


def atr_threshold(
    atr_series: pd.Series,
    min_pct: float,
    prices: pd.Series,
) -> pd.Series:
    """ATR / price oranı min_pct'in üzerinde mi?

    Args:
        atr_series: ATR değerleri
        min_pct: 0.005 = %0.5
        prices: aynı indeks üzerinde fiyat (close)
    """
    if min_pct <= 0:
        return pd.Series(True, index=atr_series.index)
    p = prices.astype(float).where(prices != 0, np.nan)
    ratio = atr_series.astype(float) / p
    return (ratio >= min_pct).fillna(False).astype(bool)


def volume_zscore(
    volume: pd.Series,
    period: int = 20,
    min_z: float = 0.0,
) -> pd.Series:
    """Hacim z-score >= min_z. period rolling pencere."""
    if period <= 1:
        raise ValueError("period > 1 olmalı")
    v = volume.astype(float)
    mean = v.rolling(period, min_periods=period).mean()
    std = v.rolling(period, min_periods=period).std(ddof=0)
    z = (v - mean) / std.replace(0, np.nan)
    if min_z <= 0:
        return pd.Series(True, index=volume.index)
    return (z >= min_z).fillna(False).astype(bool)


def ema_trend_filter(
    close: pd.Series,
    period: int = 50,
    side: Literal["long", "short"] = "long",
) -> pd.Series:
    """close > EMA → long taraf izinli; close < EMA → short taraf izinli."""
    e = ema(close.astype(float), period=period)
    if side == "long":
        return (close > e).fillna(False).astype(bool)
    return (close < e).fillna(False).astype(bool)


def kaufman_efficiency_ratio(close: pd.Series, period: int = 14) -> pd.Series:
    """Kaufman Efficiency Ratio = |close[t] - close[t-period]| / sum(|diff|).

    ER ≈ 1.0 → strong directional move; ER ≈ 0.0 → choppy.
    Forward-looking-safe.
    """
    change = (close - close.shift(period)).abs()
    volatility = close.diff().abs().rolling(period, min_periods=period).sum()
    er = change / volatility.replace(0, np.nan)
    return er.fillna(0.0).clip(0.0, 1.0)


def always_in_flags(
    df: pd.DataFrame, n_confirm: int = 3
) -> tuple[pd.Series, pd.Series]:
    """Brooks 'always-in' trend confirmation flags (long, short)."""
    close = df["close"]
    high = df["high"]
    low = df["low"]
    bullish = (close > close.shift(1)).rolling(n_confirm).sum()
    bearish = (close < close.shift(1)).rolling(n_confirm).sum()
    prev_high = high.shift(1).rolling(n_confirm).max()
    prev_low = low.shift(1).rolling(n_confirm).min()
    long_flag = (bullish >= n_confirm - 1) & (close > prev_high)
    short_flag = (bearish >= n_confirm - 1) & (close < prev_low)
    return long_flag.fillna(False), short_flag.fillna(False)


def rolling_sharpe(close: pd.Series, period: int = 60) -> pd.Series:
    """Rolling Sharpe of daily returns (annualized × sqrt(365))."""
    rets = close.pct_change()
    mean_r = rets.rolling(period, min_periods=period // 2).mean()
    std_r = rets.rolling(period, min_periods=period // 2).std(ddof=0)
    sharpe = (mean_r / std_r.replace(0, np.nan)) * np.sqrt(365)
    return sharpe.fillna(0.0)


def volatility_regime(
    atr_series: pd.Series,
    period: int = 30,
) -> pd.Series:
    """Rolling-period medyan üstü → 'high', altı → 'low'.

    Returns Series[Literal['high','low']].
    """
    a = atr_series.astype(float)
    median = a.rolling(period, min_periods=period).median()
    out = pd.Series(np.where(a > median, "high", "low"), index=a.index, dtype=object)
    # Yetersiz veri olan satırlarda NaN değer yerine 'low' verelim ama genelde NaN kalır
    out = out.where(median.notna(), other="low")
    return out
