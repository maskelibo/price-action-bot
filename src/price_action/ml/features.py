"""Feature builder — OHLCV + sinyal metadata'sından ML feature matrix.

ML filter (XGBoost) bu feature'ları kullanır. Tüm hesaplar geçmiş bar'lara
bakar (lookahead-bias-free). Feature listesi:
- ATR(14) %
- RSI(14)
- BB %B (20, 2σ)
- volume z-score (20)
- volatility regime (vol_20 < median → range)
- trend slope (close üzerinde lineer regresyon eğimi, 20 bar)
- support/resistance distance (ATR cinsinden, sinyal metadata'sından)
- pattern_id one-hot
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from price_action.logging_config import logger


@dataclass(frozen=True)
class FeatureSpec:
    """Feature pipeline parametreleri."""

    atr_period: int = 14
    rsi_period: int = 14
    bb_period: int = 20
    bb_std: float = 2.0
    vol_window: int = 20
    vol_zscore_window: int = 20
    trend_slope_window: int = 20
    pattern_ids: tuple[str, ...] = field(default=(
        "bullish_pin_bar",
        "bearish_pin_bar",
        "bullish_engulfing",
        "bearish_engulfing",
        "inside_bar_breakout",
    ))


# =====================================================================
# Düşük seviye indicator'lar (vektörize)
# =====================================================================

def _atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high = df["high"]
    low = df["low"]
    close = df["close"]
    prev_close = close.shift(1)
    tr = pd.concat(
        [
            (high - low).abs(),
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()


def _rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    return rsi.fillna(50.0)


def _bb_pct_b(close: pd.Series, period: int = 20, n_std: float = 2.0) -> pd.Series:
    mid = close.rolling(period, min_periods=period).mean()
    sd = close.rolling(period, min_periods=period).std(ddof=1)
    upper = mid + n_std * sd
    lower = mid - n_std * sd
    rng = (upper - lower).replace(0, np.nan)
    return (close - lower) / rng


def _volume_zscore(volume: pd.Series, window: int = 20) -> pd.Series:
    mu = volume.rolling(window, min_periods=window).mean()
    sd = volume.rolling(window, min_periods=window).std(ddof=1).replace(0, np.nan)
    return (volume - mu) / sd


def _trend_slope(close: pd.Series, window: int = 20) -> pd.Series:
    """Pencere içinde log(close) üzerinde basit lineer regresyon eğimi."""
    log_c = np.log(close.replace(0, np.nan))
    x = np.arange(window, dtype=float)
    x_mean = x.mean()
    denom = ((x - x_mean) ** 2).sum()

    def _slope(arr: np.ndarray) -> float:
        if np.isnan(arr).any():
            return np.nan
        y_mean = arr.mean()
        return float(((x - x_mean) * (arr - y_mean)).sum() / denom)

    return log_c.rolling(window, min_periods=window).apply(_slope, raw=True)


def _vol_regime(close: pd.Series, window: int = 20) -> pd.Series:
    """1 = düşük volatilite (range), 0 = yüksek (trending). NaN safe."""
    rets = close.pct_change()
    vol = rets.rolling(window, min_periods=window).std(ddof=1)
    median = vol.expanding(min_periods=window).median()
    return (vol < median).astype(float)


# =====================================================================
# Üst seviye builder
# =====================================================================

def build_features(
    ohlcv: pd.DataFrame,
    signals: pd.DataFrame | None = None,
    *,
    spec: FeatureSpec | None = None,
) -> pd.DataFrame:
    """OHLCV + sinyal metadata'sından feature matrix üret.

    `ohlcv` kolonları: open, high, low, close, volume (index = DateTime).
    `signals` opsiyonel; eğer verilirse her sinyal için kendi feature satırı
    döner (signals.index ohlcv.index'e hizalanır). Aksi halde tüm bar'lar.

    Çıktı kolonları:
        atr_pct, rsi, bb_pct_b, vol_z, vol_regime, trend_slope,
        sr_distance_atr, pattern_<id> (one-hot)
    """
    spec = spec or FeatureSpec()
    if ohlcv is None or ohlcv.empty:
        return pd.DataFrame()

    df = ohlcv.copy()
    df.index = pd.to_datetime(df.index)
    df = df.sort_index()

    atr = _atr(df, spec.atr_period)
    feat = pd.DataFrame(index=df.index)
    feat["atr_pct"] = atr / df["close"]
    feat["rsi"] = _rsi(df["close"], spec.rsi_period)
    feat["bb_pct_b"] = _bb_pct_b(df["close"], spec.bb_period, spec.bb_std)
    feat["vol_z"] = _volume_zscore(df["volume"], spec.vol_zscore_window)
    feat["vol_regime"] = _vol_regime(df["close"], spec.vol_window)
    feat["trend_slope"] = _trend_slope(df["close"], spec.trend_slope_window)

    # Pattern one-hot — başlangıçta sıfır, sinyalden gelir
    for pid in spec.pattern_ids:
        feat[f"pattern_{pid}"] = 0.0
    feat["sr_distance_atr"] = np.nan
    feat["confluence_score"] = np.nan

    if signals is not None and not signals.empty:
        s = signals.copy()
        s.index = pd.to_datetime(s.index)
        s = s.reindex(feat.index, method=None)
        # Pattern kolonu varsa one-hot doldur
        if "pattern_id" in s.columns:
            for pid in spec.pattern_ids:
                feat[f"pattern_{pid}"] = (s["pattern_id"] == pid).astype(float).fillna(0.0)
        if "sr_distance_atr" in s.columns:
            feat["sr_distance_atr"] = pd.to_numeric(s["sr_distance_atr"], errors="coerce")
        if "confluence_score" in s.columns:
            feat["confluence_score"] = pd.to_numeric(s["confluence_score"], errors="coerce")
        # Yalnızca sinyal olan satırları döndür
        sig_idx = s.dropna(how="all").index
        feat = feat.loc[feat.index.intersection(sig_idx)]

    feat = feat.replace([np.inf, -np.inf], np.nan)
    n_before = len(feat)
    feat = feat.dropna(how="any")
    n_after = len(feat)
    if n_before != n_after:
        logger.debug(
            "features.dropna",
            extra={"n_before": n_before, "n_after": n_after},
        )
    return feat
