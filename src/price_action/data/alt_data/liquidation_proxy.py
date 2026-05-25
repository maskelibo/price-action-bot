"""Liquidation proxy — OHLCV + ATR + volume_z-score tabanlı sentetik proxy.

Gerçek tarihsel liquidation verisi ücretsiz API'lerde bulunmuyor:
  - CoinGlass: $29+/ay (tarihsel liquidation aggregates)
  - Binance forceOrders: decommissioned (HTTP 400)
  - Bybit liquidation: sadece real-time WebSocket, REST tarihsel yok
  - OKX: sadece son 48h

Bu modül OHLCV verisiyle hesaplanabilen sentetik proxy kolonları üretir.
Strateji katmanında `liquidation_fade.py` bu kolonları kullanır.

Proxy tanımı (literatür: Deribit/research papers):
  Volume spike + büyük bar range = forced liquidation ihtimalini artırır.

  cascade_proxy = volume_z_bar AND atr_z_bar
    volume_z_bar  : volume rolling z-score > threshold
    atr_z_bar     : bar range / ATR z-score > threshold (büyük hareket)

  Direction:
    long_cascade  : bearish bar (close < open) AND volume_z AND atr_z
                    → proxy for long liquidation (forced sell)
    short_cascade : bullish bar (close > open) AND volume_z AND atr_z
                    → proxy for short liquidation (forced buy)

Sınırlılıklar (surface don't hide):
  - Proxy precision: yüksek-volume hareketlerin ancak bir kısmı liquidation
  - Daily resolution: intraday cascade timing kaybolur
  - Her büyük habersel hareket proxy'yi tetikler (news vs liquidation ayrıştırması yok)
  - Bu kolonlar strategy için HYPOTETİK sinyal; real data olmadan edge belirsiz

Hard limits:
  - No forward-fill: eksik OHLCV → NaN proxy kolonları
  - No clip: ham değerler korunur, z-score hesabında bile
  - UTC consistent
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from price_action.logging_config import logger

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Volume z-score threshold for cascade proxy (rolling window)
DEFAULT_VOL_Z_THRESHOLD: float = 2.0

# ATR (bar range / ATR rolling) z-score threshold
DEFAULT_ATR_Z_THRESHOLD: float = 1.5

# Rolling window for z-score computation
DEFAULT_ROLLING_WINDOW: int = 30

# Minimum bars needed before proxy is meaningful
MIN_BARS: int = 10


# ---------------------------------------------------------------------------
# Feature helpers (all lookahead-free)
# ---------------------------------------------------------------------------

def _rolling_zscore(series: pd.Series, window: int, min_periods: int | None = None) -> pd.Series:
    """Rolling z-score — lookahead-free.

    At bar t: uses [t-window .. t-1] (shift(1) before rolling).
    NaN returned for first (window) bars.

    No clip: raw z-scores preserved.
    """
    if min_periods is None:
        min_periods = max(5, window // 4)
    lagged = series.shift(1)
    roll = lagged.rolling(window, min_periods=min_periods)
    mean = roll.mean()
    std = roll.std(ddof=0).replace(0.0, float("nan"))
    return (series - mean) / std


def _atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Wilder ATR — lookahead-free (uses shift(1) for prev close)."""
    hi = df["high"]
    lo = df["low"]
    pc = df["close"].shift(1)
    tr = pd.concat(
        [hi - lo, (hi - pc).abs(), (lo - pc).abs()], axis=1
    ).max(axis=1)
    return tr.ewm(span=period, adjust=False).mean()


def _bar_range_ratio(df: pd.DataFrame, atr: pd.Series) -> pd.Series:
    """Bar range / ATR ratio (current bar vs recent volatility).

    ratio > 1 → unusually large bar.
    """
    rng = df["high"] - df["low"]
    return rng / atr.replace(0.0, float("nan"))


# ---------------------------------------------------------------------------
# Main: compute_liquidation_proxy
# ---------------------------------------------------------------------------

def compute_liquidation_proxy(
    df: pd.DataFrame,
    *,
    vol_z_threshold: float = DEFAULT_VOL_Z_THRESHOLD,
    atr_z_threshold: float = DEFAULT_ATR_Z_THRESHOLD,
    rolling_window: int = DEFAULT_ROLLING_WINDOW,
    atr_period: int = 14,
) -> pd.DataFrame:
    """OHLCV DataFrame'ine liquidation proxy kolonları ekle.

    Input:
        df: standart OHLCV (ts, open, high, low, close, volume)
            ts: UTC tz-aware veya naive (UTC olarak kabul edilir)

    Output:
        df + kolonlar:
            volume_z          : rolling z-score of volume (lookahead-free)
            atr14             : ATR(14)
            bar_range_ratio   : (high - low) / ATR14
            bar_rr_z          : rolling z-score of bar_range_ratio
            is_bearish        : close < open (bool)
            is_bullish        : close > open (bool)
            liq_proxy_long    : proxy for long liquidation cascade (bool, float safe)
            liq_proxy_short   : proxy for short liquidation cascade (bool, float safe)
            liq_proxy_score   : combined intensity score (0.0–2.0+, higher = stronger signal)

    Garantiler:
        - No forward-fill: NaN korunur
        - No clip/winsorize: ham değerler dahil
        - Lookahead-free: shift(1) kullanılır
        - ts UTC naive → UTC tz-aware dönüşümü (belirtilir)

    İlk (rolling_window) bar için proxy kolonları NaN/False döner (yeterli geçmiş yok).
    """
    if df.empty:
        for col in ["volume_z", "atr14", "bar_range_ratio", "bar_rr_z",
                    "is_bearish", "is_bullish", "liq_proxy_long", "liq_proxy_short",
                    "liq_proxy_score"]:
            df[col] = float("nan")
        return df

    df = df.copy()
    df = df.sort_values("ts").reset_index(drop=True)

    # Ensure UTC (surface, don't silently convert — log if naive)
    if "ts" in df.columns:
        if not pd.api.types.is_datetime64_any_dtype(df["ts"]):
            df["ts"] = pd.to_datetime(df["ts"], utc=True, errors="coerce")
        elif df["ts"].dt.tz is None:
            logger.warning(
                "liq_proxy.ts_naive_converted_to_utc",
                extra={"n_rows": len(df)},
            )
            df["ts"] = df["ts"].dt.tz_localize("UTC")
        else:
            df["ts"] = df["ts"].dt.tz_convert("UTC")

    n = len(df)
    if n < MIN_BARS:
        logger.warning("liq_proxy.insufficient_bars", extra={"n": n, "min": MIN_BARS})

    # --- ATR ---
    df["atr14"] = _atr(df, atr_period)

    # --- Volume z-score (lookahead-free) ---
    if "volume" in df.columns:
        vol = pd.to_numeric(df["volume"], errors="coerce")
        df["volume_z"] = _rolling_zscore(vol, rolling_window)
    else:
        df["volume_z"] = float("nan")

    # --- Bar range ratio + z-score ---
    df["bar_range_ratio"] = _bar_range_ratio(df, df["atr14"])
    df["bar_rr_z"] = _rolling_zscore(df["bar_range_ratio"], rolling_window)

    # --- Direction ---
    df["is_bearish"] = (df["close"] < df["open"]).fillna(False)
    df["is_bullish"] = (df["close"] > df["open"]).fillna(False)

    # --- Proxy: volume spike AND large bar AND directional ---
    # Using lagged z-scores (already shift(1)-based in _rolling_zscore)
    vol_spike = (df["volume_z"] > vol_z_threshold).fillna(False)
    large_bar = (df["bar_rr_z"] > atr_z_threshold).fillna(False)

    # Long cascade proxy: bearish bar + volume spike + large range
    df["liq_proxy_long"] = (df["is_bearish"] & vol_spike & large_bar).astype(float)

    # Short cascade proxy: bullish bar + volume spike + large range
    df["liq_proxy_short"] = (df["is_bullish"] & vol_spike & large_bar).astype(float)

    # Intensity score: sum of z-scores where proxy fires
    # Higher = stronger proxy signal
    vol_z_pos = df["volume_z"].clip(lower=0.0).fillna(0.0)
    rr_z_pos = df["bar_rr_z"].clip(lower=0.0).fillna(0.0)
    df["liq_proxy_score"] = (
        ((df["liq_proxy_long"] + df["liq_proxy_short"]) > 0).astype(float)
        * (vol_z_pos + rr_z_pos)
    )

    return df


def add_proxy_to_ohlcv(
    ohlcv_df: pd.DataFrame,
    *,
    vol_z_threshold: float = DEFAULT_VOL_Z_THRESHOLD,
    atr_z_threshold: float = DEFAULT_ATR_Z_THRESHOLD,
    rolling_window: int = DEFAULT_ROLLING_WINDOW,
) -> pd.DataFrame:
    """Single-call wrapper: compute_liquidation_proxy ile OHLCV'ye proxy ekle.

    Bu fonksiyon BacktestEngine wrapper'larında veya strateji prepare_features'da
    doğrudan çağrılabilir.

    Returns:
        ohlcv_df + proxy kolonları (in-place değil, kopya döner)
    """
    return compute_liquidation_proxy(
        ohlcv_df,
        vol_z_threshold=vol_z_threshold,
        atr_z_threshold=atr_z_threshold,
        rolling_window=rolling_window,
    )


# ---------------------------------------------------------------------------
# Quality check for proxy
# ---------------------------------------------------------------------------

def validate_proxy(df: pd.DataFrame) -> dict[str, Any]:
    """Proxy kolonlarının sağlık kontrolü.

    Döndürür:
        {
            "n_rows": int,
            "long_cascade_count": int,
            "short_cascade_count": int,
            "long_cascade_pct": float,
            "short_cascade_pct": float,
            "volume_z_nan_pct": float,
            "bar_rr_z_nan_pct": float,
            "note": str (uyarı varsa)
        }

    Kurallar:
        - liq_proxy_long + liq_proxy_short toplam > %5 → gürültü uyarısı
        - NaN oranı > %30 → yetersiz geçmiş uyarısı
    """
    n = len(df)
    if n == 0:
        return {"n_rows": 0, "note": "empty"}

    result: dict[str, Any] = {"n_rows": n}
    notes: list[str] = []

    for col, key in [
        ("liq_proxy_long", "long_cascade_count"),
        ("liq_proxy_short", "short_cascade_count"),
    ]:
        if col in df.columns:
            count = int((df[col] > 0).sum())
            result[key] = count
            result[f"{key.replace('_count', '_pct')}"] = round(count / n * 100, 2)
        else:
            result[key] = 0
            result[f"{key.replace('_count', '_pct')}"] = 0.0

    total_proxy_pct = result.get("long_cascade_pct", 0.0) + result.get("short_cascade_pct", 0.0)
    if total_proxy_pct > 10.0:
        notes.append(f"high_proxy_rate:{total_proxy_pct:.1f}% (check thresholds)")

    for col, key in [("volume_z", "volume_z_nan_pct"), ("bar_rr_z", "bar_rr_z_nan_pct")]:
        if col in df.columns:
            nan_pct = round(df[col].isna().sum() / n * 100, 2)
            result[key] = nan_pct
            if nan_pct > 30.0:
                notes.append(f"{col}_nan:{nan_pct:.1f}% (insufficient history?)")
        else:
            result[key] = 100.0
            notes.append(f"{col}_missing")

    result["note"] = "; ".join(notes) if notes else "ok"
    return result
