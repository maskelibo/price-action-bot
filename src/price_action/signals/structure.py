"""Yapı analizi: swing fractal, S/R, trendline, ATR, EMA.

Tüm fonksiyonlar saf vektörize ve lookahead-free.
`rolling().center=True` ve `shift(-k)` kullanılmaz.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from price_action.logging_config import logger

_ = logger


def ema(series: pd.Series, period: int) -> pd.Series:
    """Exponential moving average — pandas adjust=False (gerçek tradingview EMA)."""
    if period <= 0:
        raise ValueError("EMA period > 0 olmalı")
    return series.astype(float).ewm(span=period, adjust=False, min_periods=period).mean()


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Average True Range (Wilder smoothing)."""
    if period <= 0:
        raise ValueError("ATR period > 0 olmalı")
    h = df["high"].astype(float)
    l = df["low"].astype(float)
    c = df["close"].astype(float)
    prev_c = c.shift(1)
    tr = pd.concat(
        [
            h - l,
            (h - prev_c).abs(),
            (l - prev_c).abs(),
        ],
        axis=1,
    ).max(axis=1)
    # Wilder: ilk değeri SMA, sonra EWMA alpha=1/period
    sma = tr.rolling(period, min_periods=period).mean()
    wilder = tr.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()
    out = wilder.copy()
    out.iloc[:period] = sma.iloc[:period]
    return out


# ---------------------------------------------------------------------------
# Swing high/low (n-bar fractal)
# ---------------------------------------------------------------------------
def swing_highs(df: pd.DataFrame, n: int = 2) -> pd.Series:
    """n-bar fractal swing high.

    Bir bar `t` swing high'tır iff `t-n..t-1` ve `t+1..t+n`'deki tüm high'lar
    `df.high[t]`'den küçüktür.

    UYARI: Tanım gereği swing'i `t` anında BİLEMEYİZ; ancak `t+n` anında
    bakıldığında geçmişe doğru "evet, t bir swing'di" denebilir. Bu fonksiyon
    sadece geçmişe yönelik etiketler üretir; `t+n+...` zamanına kadar kullanılan
    karar alıcı kod, mevcut anki bar `t` için `swing[t]` flag'ini OKUYAMAZ
    (çünkü `t+n` anında biliniyor olur). Lookahead-paranoya: confluence/
    trade kodu swing'leri sadece geçmiş bar `t-n` içinde işaretliyse kullanmalı.
    """
    if n < 1:
        raise ValueError("n >= 1 olmalı")
    h = df["high"].astype(float)
    left_max = h.shift(1).rolling(n, min_periods=n).max()
    right_max = h.shift(-n).rolling(n, min_periods=n).max()
    is_swing = (h > left_max) & (h > right_max)
    return is_swing.fillna(False).astype(bool)


def swing_lows(df: pd.DataFrame, n: int = 2) -> pd.Series:
    if n < 1:
        raise ValueError("n >= 1 olmalı")
    l = df["low"].astype(float)
    left_min = l.shift(1).rolling(n, min_periods=n).min()
    right_min = l.shift(-n).rolling(n, min_periods=n).min()
    is_swing = (l < left_min) & (l < right_min)
    return is_swing.fillna(False).astype(bool)


# ---------------------------------------------------------------------------
# Support / Resistance
# ---------------------------------------------------------------------------
def support_resistance(
    df: pd.DataFrame,
    lookback: int = 200,
    min_touches: int = 2,
    cluster_atr_mult: float = 0.5,
    n_swing: int = 2,
    atr_period: int = 14,
) -> pd.DataFrame:
    """Son `lookback` bar içindeki swing'leri ATR'ye göre kümele.

    Returns DataFrame:
        columns: level (float), strength (int — touches), last_touch_ts (Timestamp)
    """
    if df.empty:
        return pd.DataFrame(columns=["level", "strength", "last_touch_ts"])

    sub = df.tail(lookback).copy()
    a = atr(sub, period=atr_period)
    last_atr = float(a.dropna().iloc[-1]) if a.dropna().size else float(sub["close"].std() or 0.0)
    radius = max(last_atr * cluster_atr_mult, 1e-9)

    sh = swing_highs(sub, n=n_swing)
    sl = swing_lows(sub, n=n_swing)
    points: list[tuple[pd.Timestamp | int, float]] = []
    for idx in sub.index[sh.values]:
        points.append((idx, float(sub.loc[idx, "high"])))
    for idx in sub.index[sl.values]:
        points.append((idx, float(sub.loc[idx, "low"])))
    if not points:
        return pd.DataFrame(columns=["level", "strength", "last_touch_ts"])

    # 1D kümeleme: sırala, ardışık nokta farkı ≤ radius ise aynı kümeye koy
    points.sort(key=lambda x: x[1])
    clusters: list[list[tuple[Any, float]]] = [[points[0]]]
    for ts_, price in points[1:]:
        if abs(price - clusters[-1][-1][1]) <= radius:
            clusters[-1].append((ts_, price))
        else:
            clusters.append([(ts_, price)])

    rows = []
    for cl in clusters:
        if len(cl) < min_touches:
            continue
        prices = [p for _, p in cl]
        timestamps = [t for t, _ in cl]
        rows.append(
            {
                "level": float(np.mean(prices)),
                "strength": len(cl),
                "last_touch_ts": max(timestamps),
            }
        )
    return pd.DataFrame(rows).sort_values("strength", ascending=False).reset_index(drop=True)


# ---------------------------------------------------------------------------
# Trendline (basit doğrusal regresyon)
# ---------------------------------------------------------------------------
def trendline(df: pd.DataFrame, window: int = 20) -> pd.DataFrame:
    """Son `window` bardaki close'a doğrusal regresyon.

    Returns DataFrame (tek satır):
        slope, intercept, r2, age (window)
    """
    if df.empty or len(df) < window:
        return pd.DataFrame([{"slope": np.nan, "intercept": np.nan, "r2": np.nan, "age": 0}])
    y = df["close"].astype(float).tail(window).to_numpy()
    x = np.arange(len(y), dtype=float)
    x_mean = x.mean()
    y_mean = y.mean()
    cov = ((x - x_mean) * (y - y_mean)).sum()
    var = ((x - x_mean) ** 2).sum()
    slope = cov / var if var > 0 else 0.0
    intercept = y_mean - slope * x_mean
    y_pred = slope * x + intercept
    ss_res = ((y - y_pred) ** 2).sum()
    ss_tot = ((y - y_mean) ** 2).sum()
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0
    return pd.DataFrame(
        [{"slope": float(slope), "intercept": float(intercept), "r2": float(r2), "age": window}]
    )
