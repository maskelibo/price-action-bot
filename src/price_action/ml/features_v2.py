"""ML Meta-Labeling v2 — 5 yeni feature (multi-TF + alt-data continuous).

Pre-reg: memory/researcher/hypotheses/2026-05-17-feature-space-v2.md

Yeni feature'lar (TUM SABIT, sweep YASAK):
  1. atr_pct_4h        — en son tamamlanmis 4h bar atr14/close
  2. rsi_14_4h         — en son tamamlanmis 4h bar RSI(14)
  3. vol_z_1h          — son 24 1h bar volume z-score (signal_ts'e en yakin)
  4. funding_z_24h     — son funding (BTCUSDT) 60d rolling z-score
  5. fng_value         — en son daily FnG (0-100 raw)

Causality invariant: tum feature'lar trade signal_ts'den **once** tamamlanmis bar/event.
NaN: median imputation (column-wise, train-only median).
"""
from __future__ import annotations

from pathlib import Path
import pickle

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]


def _atr14(df: pd.DataFrame) -> pd.Series:
    high, low, close = df["high"], df["low"], df["close"]
    prev_close = close.shift(1)
    tr = pd.concat([(high-low).abs(), (high-prev_close).abs(), (low-prev_close).abs()], axis=1).max(axis=1)
    return tr.rolling(14).mean()


def _rsi14(close: pd.Series) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = -delta.clip(upper=0).rolling(14).mean()
    rs = gain / loss.replace(0, np.nan)
    return (100 - (100 / (1 + rs))).fillna(50.0)


def precompute_4h_features(df_4h: pd.DataFrame) -> pd.DataFrame:
    """4h DataFrame'e atr_pct + rsi_14 ekle."""
    df = df_4h.copy().sort_values("ts").reset_index(drop=True)
    atr = _atr14(df)
    df["atr_pct_4h"] = atr / df["close"]
    df["rsi_14_4h"] = _rsi14(df["close"])
    return df


def precompute_1h_features(df_1h: pd.DataFrame) -> pd.DataFrame:
    """1h DataFrame'e vol_z_24 ekle."""
    df = df_1h.copy().sort_values("ts").reset_index(drop=True)
    vol = df["volume"]
    vol_mean = vol.rolling(24).mean()
    vol_std = vol.rolling(24).std().replace(0, np.nan)
    df["vol_z_1h"] = (vol - vol_mean) / vol_std
    return df


def precompute_funding_z(df_funding: pd.DataFrame) -> pd.DataFrame:
    """Funding'e 60d (180 funding event) rolling z-score ekle."""
    df = df_funding.copy()
    df["ts"] = pd.to_datetime(df["ts"], utc=True, format="ISO8601")
    df = df.sort_values("ts").reset_index(drop=True)
    fr = pd.to_numeric(df["fundingRate"], errors="coerce")
    fr_mean = fr.rolling(180, min_periods=10).mean()
    fr_std = fr.rolling(180, min_periods=10).std().replace(0, np.nan)
    df["funding_z_24h"] = (fr - fr_mean) / fr_std
    return df


def load_alt_data(root: Path | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    root = root or ROOT
    funding = pd.read_csv(root / "data" / "alt_data" / "funding_BTCUSDT.csv")
    funding = precompute_funding_z(funding)
    fng = pd.read_csv(root / "data" / "alt_data" / "fng_daily.csv")
    fng["ts"] = pd.to_datetime(fng["ts"], utc=True, format="ISO8601")
    fng = fng.sort_values("ts").reset_index(drop=True)
    return funding, fng


def load_mtf_caches(root: Path | None = None) -> tuple[dict[str, pd.DataFrame], dict[str, pd.DataFrame]]:
    root = root or ROOT
    with (root / "data" / "mtf_4h_cache.pkl").open("rb") as f:
        cache_4h = pickle.load(f)
    with (root / "data" / "mtf_1h_cache.pkl").open("rb") as f:
        cache_1h = pickle.load(f)
    # Precompute features per symbol
    out_4h = {sym: precompute_4h_features(df) for sym, df in cache_4h.items()}
    out_1h = {sym: precompute_1h_features(df) for sym, df in cache_1h.items()}
    return out_4h, out_1h


def _last_before(df: pd.DataFrame, ts: pd.Timestamp, col: str) -> float:
    """En son ts'den onceki tamamlanmis bar/event'in col degeri."""
    mask = df["ts"] < ts
    if not mask.any():
        return np.nan
    val = df.loc[mask, col].iloc[-1]
    return float(val) if pd.notna(val) else np.nan


def build_v2_features(
    trades: list[dict],
    cache_4h: dict[str, pd.DataFrame],
    cache_1h: dict[str, pd.DataFrame],
    df_funding: pd.DataFrame,
    df_fng: pd.DataFrame,
) -> pd.DataFrame:
    """4787 trade icin 5 yeni feature.

    trades: dict list with keys: signal_ts (UTC), symbol
    Returns DataFrame indexed by trade order (0..n-1) with columns:
        atr_pct_4h, rsi_14_4h, vol_z_1h, funding_z_24h, fng_value
    """
    rows: list[dict] = []
    for t in trades:
        sig_ts = pd.Timestamp(t["signal_ts"])
        if sig_ts.tzinfo is None:
            sig_ts = sig_ts.tz_localize("UTC")
        sym = t["symbol"]
        df_4h = cache_4h.get(sym)
        df_1h = cache_1h.get(sym)
        atr_4h = rsi_4h = vol_z_1h = np.nan
        if df_4h is not None and not df_4h.empty:
            atr_4h = _last_before(df_4h, sig_ts, "atr_pct_4h")
            rsi_4h = _last_before(df_4h, sig_ts, "rsi_14_4h")
        if df_1h is not None and not df_1h.empty:
            vol_z_1h = _last_before(df_1h, sig_ts, "vol_z_1h")
        funding_z = _last_before(df_funding, sig_ts, "funding_z_24h")
        fng_val = _last_before(df_fng, sig_ts, "value")
        if np.isnan(fng_val):
            fng_val = 50.0  # neutral fallback

        rows.append({
            "atr_pct_4h": atr_4h,
            "rsi_14_4h": rsi_4h,
            "vol_z_1h": vol_z_1h,
            "funding_z_24h": funding_z,
            "fng_value": fng_val,
        })
    return pd.DataFrame(rows)


__all__ = [
    "precompute_4h_features",
    "precompute_1h_features",
    "precompute_funding_z",
    "load_alt_data",
    "load_mtf_caches",
    "build_v2_features",
]
