"""Bias / sanity kontrolleri — Analyst günlük raporda kullanır.

- Concentration: gelir kaç sembolde toplandı?
- Recency: son 7g vs trailing 30g performans karşılaştırması.
- Outlier: 3σ dışı PnL'li trade'ler.
"""
from __future__ import annotations

from datetime import timedelta
from typing import Any

import numpy as np
import pandas as pd

from price_action.logging_config import logger


def check_concentration(
    trades_df: pd.DataFrame,
    *,
    pnl_col: str = "realized_pnl_usdt",
    symbol_col: str = "symbol",
    top_n: int = 3,
) -> dict[str, Any]:
    """Toplam pozitif gelirin yüzde kaçı top-N sembolden geldi?

    Çıktı:
        {
            "top_n_share": 0.65,     # toplam pozitif PnL'in %65'i top-N'de
            "top_symbols": ["BTCUSDT", "ETHUSDT", ...],
            "n_unique_symbols": 12,
            "warning": True/False,    # share > 0.7 ise uyarı
        }
    """
    if trades_df is None or trades_df.empty or symbol_col not in trades_df.columns:
        return {"top_n_share": 0.0, "top_symbols": [], "n_unique_symbols": 0, "warning": False}

    df = trades_df.copy()
    df[pnl_col] = pd.to_numeric(df[pnl_col], errors="coerce").fillna(0.0)
    positive = df[df[pnl_col] > 0]
    total_positive = float(positive[pnl_col].sum())
    if total_positive <= 0:
        return {
            "top_n_share": 0.0,
            "top_symbols": [],
            "n_unique_symbols": int(df[symbol_col].nunique()),
            "warning": False,
        }
    by_symbol = positive.groupby(symbol_col)[pnl_col].sum().sort_values(ascending=False)
    top = by_symbol.head(top_n)
    share = float(top.sum() / total_positive)
    warning = share > 0.7
    if warning:
        logger.warning(
            "bias.concentration_high",
            extra={"share": share, "top": list(top.index)},
        )
    return {
        "top_n_share": share,
        "top_symbols": list(top.index),
        "n_unique_symbols": int(df[symbol_col].nunique()),
        "warning": warning,
    }


def check_recency(
    trades_df: pd.DataFrame,
    *,
    pnl_col: str = "realized_pnl_usdt",
    ts_col: str = "exit_ts",
    short_days: int = 7,
    long_days: int = 30,
) -> dict[str, Any]:
    """Son `short_days` performansı, trailing `long_days` ortalamasından sapıyor mu?"""
    if trades_df is None or trades_df.empty or ts_col not in trades_df.columns:
        return {"short_avg": 0.0, "long_avg": 0.0, "deviation_sigma": 0.0, "warning": False}

    df = trades_df.copy()
    df[ts_col] = pd.to_datetime(df[ts_col])
    df[pnl_col] = pd.to_numeric(df[pnl_col], errors="coerce").fillna(0.0)
    if df[ts_col].isna().all():
        return {"short_avg": 0.0, "long_avg": 0.0, "deviation_sigma": 0.0, "warning": False}

    cutoff = df[ts_col].max()
    short_window = df[df[ts_col] >= cutoff - timedelta(days=short_days)]
    long_window = df[df[ts_col] >= cutoff - timedelta(days=long_days)]

    short_avg = float(short_window[pnl_col].mean()) if not short_window.empty else 0.0
    long_avg = float(long_window[pnl_col].mean()) if not long_window.empty else 0.0
    long_std = float(long_window[pnl_col].std(ddof=1)) if len(long_window) > 1 else 0.0

    if long_std == 0:
        sigma = 0.0
    else:
        sigma = (short_avg - long_avg) / long_std
    warning = abs(sigma) > 2.0
    if warning:
        logger.warning("bias.recency_drift", extra={"sigma": sigma})
    return {
        "short_avg": short_avg,
        "long_avg": long_avg,
        "deviation_sigma": float(sigma),
        "warning": warning,
        "n_short": int(len(short_window)),
        "n_long": int(len(long_window)),
    }


def check_outlier_pnl(
    trades_df: pd.DataFrame,
    *,
    pnl_col: str = "realized_pnl_usdt",
    threshold_sigma: float = 3.0,
) -> list[dict[str, Any]]:
    """3σ dışı PnL'li trade'leri liste olarak döner.

    Her eleman: {"trade_id": ..., "symbol": ..., "pnl": ..., "z": ...}
    """
    if trades_df is None or trades_df.empty:
        return []
    pnl = pd.to_numeric(trades_df[pnl_col], errors="coerce")
    finite = pnl.dropna()
    if len(finite) < 5:
        return []
    mu = float(finite.mean())
    sd = float(finite.std(ddof=1))
    if sd == 0 or not np.isfinite(sd):
        return []
    z = (pnl - mu) / sd
    mask = z.abs() > threshold_sigma
    out: list[dict[str, Any]] = []
    for idx, is_out in mask.items():
        if not is_out:
            continue
        row = trades_df.loc[idx]
        out.append(
            {
                "trade_id": str(row.get("trade_id", idx)),
                "symbol": str(row.get("symbol", "?")),
                "pnl": float(pnl.loc[idx]),
                "z": float(z.loc[idx]),
            }
        )
    if out:
        logger.info("bias.outliers_found", extra={"n": len(out)})
    return out
