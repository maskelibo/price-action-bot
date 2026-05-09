"""Compound Sentiment Filter — F&G + On-Chain MVRV double filter on engulfing.

HYPOTHESIS (H19):
    Combining two independent orthogonal filters improves signal quality:
    - F&G (Fear & Greed Index) → retail sentiment
    - MVRV (Market Value to Realized Value) → whale/macro positioning

    Compound logic:
        LONG  : engulfing + F&G[t-1] < fng_long_max (60)
                           + MVRV[t-1] < mvrv_long_max (2.5)
                (avoid greed extremes AND avoid macro overvaluation)
        SHORT : engulfing + F&G[t-1] > fng_short_min (40)
                           + MVRV[t-1] > mvrv_short_min (1.5)
                (avoid fear extremes AND avoid macro undervaluation)

MVRV availability:
    - BTC/USDT: real MVRV from Coin Metrics (CapMVRVCur)
    - Alt coins: MVRV unavailable → skip MVRV filter, apply F&G only (defensive)
    - Compound filter fully active on BTC only

Lookahead protection:
    Both F&G and MVRV use shift(1) — each bar uses the PREVIOUS day's value.
    This matches the existing sentinel contract (filter_engulfing_with_fng).

Rejection tracking:
    Each rejected signal carries a reason: "fng" | "mvrv" | "both"
    This enables post-hoc analysis of which filter is doing the work.

Usage:
    from price_action.strategies.compound_sentiment_filter import (
        compound_filter_engulfing,
        build_mvrv_lookup,
    )
    filtered, stats = compound_filter_engulfing(signals, fng_df, mvrv_df)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import NamedTuple

import numpy as np
import pandas as pd

from price_action.contracts import Signal
from price_action.logging_config import logger


# =====================================================================
# Rejection record — carries reason for downstream analysis
# =====================================================================

class RejectedSignal(NamedTuple):
    """A signal that was blocked by the compound filter."""
    signal: Signal
    reason: str  # "fng" | "mvrv" | "both"
    fng_value: float | None
    mvrv_value: float | None


@dataclass
class CompoundFilterStats:
    """Summary statistics from one compound_filter_engulfing() call."""
    total: int = 0
    passed: int = 0
    rejected_fng: int = 0       # F&G alone caused rejection
    rejected_mvrv: int = 0      # MVRV alone caused rejection
    rejected_both: int = 0      # Both filters fired
    mvrv_skipped: int = 0       # Signal was on a non-BTC asset → MVRV not applied

    @property
    def n_rejected(self) -> int:
        return self.rejected_fng + self.rejected_mvrv + self.rejected_both

    @property
    def rejection_rate(self) -> float:
        return self.n_rejected / max(1, self.total)

    def to_dict(self) -> dict:
        return {
            "total": self.total,
            "passed": self.passed,
            "rejected_fng": self.rejected_fng,
            "rejected_mvrv": self.rejected_mvrv,
            "rejected_both": self.rejected_both,
            "mvrv_skipped": self.mvrv_skipped,
            "n_rejected": self.n_rejected,
            "rejection_rate": self.rejection_rate,
        }


# =====================================================================
# MVRV lookup builder
# =====================================================================

def build_mvrv_lookup(mvrv_df: pd.DataFrame | None) -> dict[pd.Timestamp, float]:
    """Build a date → lagged MVRV lookup dict (shift-1, lookahead-free).

    Parameters
    ----------
    mvrv_df:
        On-chain DataFrame with columns: ts (datetime UTC) and CapMVRVCur (float).
        Can also be None or empty → returns empty dict (MVRV filter disabled).

    Returns
    -------
    dict mapping UTC-midnight Timestamp → MVRV[t-1] value.
    The shift(1) mirrors the same convention used in onchain_signals.py (mvrv_lag1).
    """
    if mvrv_df is None or mvrv_df.empty:
        return {}
    if "CapMVRVCur" not in mvrv_df.columns:
        logger.warning("compound_filter.mvrv_col_missing — MVRV filter disabled")
        return {}

    oc = mvrv_df[["ts", "CapMVRVCur"]].copy()
    # Normalize ts → UTC midnight
    ts_col = oc["ts"]
    if not pd.api.types.is_datetime64_any_dtype(ts_col):
        ts_col = pd.to_datetime(ts_col, utc=True)
    elif ts_col.dt.tz is None:
        ts_col = ts_col.dt.tz_localize("UTC")
    else:
        ts_col = ts_col.dt.tz_convert("UTC")

    oc["_date"] = ts_col.dt.normalize()
    oc = oc.sort_values("_date").drop_duplicates("_date", keep="last")
    # Lookahead-free shift: each date gets previous day's MVRV
    oc["mvrv_lag"] = oc["CapMVRVCur"].shift(1)

    return dict(zip(oc["_date"], oc["mvrv_lag"]))


# =====================================================================
# F&G lookup builder (mirrors filter_engulfing_with_fng internals)
# =====================================================================

def build_fng_lookup(fng_df: pd.DataFrame | None) -> dict[pd.Timestamp, float]:
    """Build a date → lagged F&G lookup dict (shift-1, lookahead-free).

    Parameters
    ----------
    fng_df:
        F&G DataFrame with columns: ts (datetime UTC), value (int 0-100).
        None or empty → returns empty dict.
    """
    if fng_df is None or fng_df.empty:
        return {}

    fng = fng_df[["ts", "value"]].copy()
    ts_col = fng["ts"]
    if not pd.api.types.is_datetime64_any_dtype(ts_col):
        ts_col = pd.to_datetime(ts_col, utc=True)
    elif ts_col.dt.tz is None:
        ts_col = ts_col.dt.tz_localize("UTC")
    else:
        ts_col = ts_col.dt.tz_convert("UTC")

    fng["_date"] = ts_col.dt.normalize()
    fng = fng.sort_values("_date").drop_duplicates("_date", keep="last")
    fng["fng_lag"] = fng["value"].shift(1)

    return dict(zip(fng["_date"], fng["fng_lag"]))


# =====================================================================
# BTC symbol detection
# =====================================================================

_BTC_SYMBOLS: frozenset[str] = frozenset([
    "BTC/USDT", "BTC/USD", "BTC/BUSD", "BTC/USDC",
    "BTCUSDT", "BTCUSD", "BTC",
])


def _is_btc_symbol(symbol: str) -> bool:
    """True if the symbol is Bitcoin (MVRV applicable)."""
    return symbol.upper().strip() in _BTC_SYMBOLS


# =====================================================================
# Core compound filter
# =====================================================================

def compound_filter_engulfing(
    signals: list[Signal],
    fng_df: pd.DataFrame | None,
    mvrv_df: pd.DataFrame | None,
    *,
    fng_long_max: float = 60.0,
    fng_short_min: float = 40.0,
    mvrv_long_max: float = 2.5,
    mvrv_short_min: float = 1.5,
    btc_only_mvrv: bool = True,
) -> tuple[list[Signal], CompoundFilterStats, list[RejectedSignal]]:
    """Filter engulfing signals with F&G + MVRV compound filter.

    Both conditions must pass for a signal to survive:
        LONG  : F&G[t-1] < fng_long_max  AND  MVRV[t-1] < mvrv_long_max
        SHORT : F&G[t-1] > fng_short_min  AND  MVRV[t-1] > mvrv_short_min

    If F&G data is unavailable for a bar → signal passes (conservative).
    If MVRV data is unavailable for a bar (non-BTC or no data) → MVRV gate
    is skipped; only F&G gate applies (defensive, per-symbol MVRV availability).

    Parameters
    ----------
    signals:
        Raw engulfing (or any) Signal list.
    fng_df:
        Fear & Greed DataFrame: ts (UTC), value (int 0-100), classification (str).
        None or empty → F&G gate disabled (all pass on F&G dimension).
    mvrv_df:
        On-chain DataFrame: ts (UTC), CapMVRVCur (float).
        None or empty → MVRV gate disabled.
    fng_long_max:
        Max F&G for long entries (default 60 — avoid greed top).
    fng_short_min:
        Min F&G for short entries (default 40 — avoid fear bottom).
    mvrv_long_max:
        Max MVRV for long entries (default 2.5 — avoid macro top).
    mvrv_short_min:
        Min MVRV for short entries (default 1.5 — avoid macro bottom).
    btc_only_mvrv:
        If True (default), MVRV gate is only applied to BTC symbols.
        Non-BTC signals have MVRV gate skipped automatically.

    Returns
    -------
    tuple[list[Signal], CompoundFilterStats, list[RejectedSignal]]
        (filtered_signals, stats, rejections)
        - filtered_signals: signals that passed both gates
        - stats: aggregate counts with rejection_reason breakdown
        - rejections: full list of rejected signals with reason metadata
    """
    stats = CompoundFilterStats()
    rejections: list[RejectedSignal] = []

    if not signals:
        return [], stats, rejections

    # Pre-build lookups (O(N) once, then O(1) per signal)
    fng_lookup = build_fng_lookup(fng_df)
    mvrv_lookup = build_mvrv_lookup(mvrv_df)

    has_fng = bool(fng_lookup)
    has_mvrv = bool(mvrv_lookup)

    passed: list[Signal] = []
    stats.total = len(signals)

    for sig in signals:
        # Normalize signal date to UTC midnight (matches lookup keys)
        sig_ts = pd.Timestamp(sig.ts)
        if sig_ts.tzinfo is None:
            sig_ts = sig_ts.tz_localize("UTC")
        else:
            sig_ts = sig_ts.tz_convert("UTC")
        sig_date = sig_ts.normalize()

        # --- F&G gate ---
        fng_val: float | None = None
        fng_fail = False
        if has_fng:
            raw = fng_lookup.get(sig_date, np.nan)
            if not (isinstance(raw, float) and np.isnan(raw)):
                fng_val = float(raw)
                if sig.direction == "long" and fng_val >= fng_long_max:
                    fng_fail = True
                elif sig.direction == "short" and fng_val <= fng_short_min:
                    fng_fail = True
        # If fng_val is NaN (unknown date) → conservative: pass

        # --- MVRV gate ---
        mvrv_val: float | None = None
        mvrv_fail = False
        apply_mvrv = has_mvrv
        if btc_only_mvrv and not _is_btc_symbol(sig.symbol):
            apply_mvrv = False
            stats.mvrv_skipped += 1

        if apply_mvrv:
            raw_m = mvrv_lookup.get(sig_date, np.nan)
            if not (isinstance(raw_m, float) and np.isnan(raw_m)):
                mvrv_val = float(raw_m)
                if sig.direction == "long" and mvrv_val >= mvrv_long_max:
                    mvrv_fail = True
                elif sig.direction == "short" and mvrv_val <= mvrv_short_min:
                    mvrv_fail = True
        # If mvrv_val is NaN (unknown date) → conservative: pass

        # --- Compound decision ---
        if fng_fail and mvrv_fail:
            stats.rejected_both += 1
            rejections.append(RejectedSignal(sig, "both", fng_val, mvrv_val))
        elif fng_fail:
            stats.rejected_fng += 1
            rejections.append(RejectedSignal(sig, "fng", fng_val, mvrv_val))
        elif mvrv_fail:
            stats.rejected_mvrv += 1
            rejections.append(RejectedSignal(sig, "mvrv", fng_val, mvrv_val))
        else:
            passed.append(sig)

    stats.passed = len(passed)

    logger.bind(
        total=stats.total,
        passed=stats.passed,
        rejected_fng=stats.rejected_fng,
        rejected_mvrv=stats.rejected_mvrv,
        rejected_both=stats.rejected_both,
        mvrv_skipped=stats.mvrv_skipped,
        fng_long_max=fng_long_max,
        fng_short_min=fng_short_min,
        mvrv_long_max=mvrv_long_max,
        mvrv_short_min=mvrv_short_min,
    ).info("compound_filter.applied")

    return passed, stats, rejections
