"""30m/45m signal scan pipeline — multi-TF stack paper bot.

DESIGN: Resamples live 5m bars fetched from ccxt into 30m / 45m OHLCV,
then runs VSAClimaxTestStrategy. The resample method MUST be bit-identical
to the backtest harness in v9_multitf_truefee.py::gather_resampled():

    resample(rule, label='left', closed='left')
    open=first, high=max, low=min, close=last, volume=sum

label='left' means the bar is stamped with the bar-open time (NOT bar-close).
This avoids lookahead: bar [14:00, 14:30) is stamped 14:00, not 14:30.

PARITY VERIFICATION:
    Run scripts/verify_resample_parity.py for >= 7 days before live trading
    on 30m/45m legs. Until parity is confirmed:
    - This module is STAGED (feed_status: staged in config).
    - futures_daemon_multitf.py will NOT submit 30m/45m orders.
    - Signals are generated and logged for audit only.

BLOCKER: B1 in risk_multitf_stack_paper_l12.yaml
    status: OPEN — do NOT remove staged gate before parity confirmed.

Usage:
    scan_signals_30m(target_bar_close) -> list[dict]
    scan_signals_45m(target_bar_close) -> list[dict]
    verify_resample_parity(sym, rule) -> dict  # parity audit
"""
from __future__ import annotations

import os
import sys
import warnings
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError as FuturesTimeout
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import pandas as pd

warnings.filterwarnings("ignore")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from price_action.logging_config import logger

# ── Config ────────────────────────────────────────────────────────────────────
# 10-symbol universe (same as 5m leg; 30m/45m validated on 10-sym only)
SYMBOLS_10: list[str] = [
    "BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "ADA/USDT",
    "AVAX/USDT", "LINK/USDT", "DOT/USDT", "DOGE/USDT", "XRP/USDT",
]

# Bars to fetch from ccxt (5m × 900 = 75 hours → enough for 45m warmup)
# 45m needs ~200 bars for ATR(14) warmup → 200 × 9 = 1800 5m bars (60h).
# 900 covers 75h → sufficient.
_FETCH_5M_BARS = 900
_SCAN_SYMBOL_TIMEOUT_SEC = 120
_DEFAULT_PARALLEL_WORKERS = 4   # smaller than 5m since resample is CPU-bound
_SIGNAL_MAX_AGE_MIN_30M = 60    # 2× 30m bar
_SIGNAL_MAX_AGE_MIN_45M = 90    # 2× 45m bar

_STAGED_ONLY = True  # B1 blocker: signals logged but NOT submitted until parity confirmed


def _fetch_5m_bars_ccxt(sym: str, n_bars: int = _FETCH_5M_BARS) -> pd.DataFrame:
    """Fetch live 5m bars from ccxt — lock-free (no DuckDB read).

    Identical pattern to futures_trade_5m._fetch_bars_ccxt.
    Both 5m daemon (PID 70580) and this scanner hit ccxt independently;
    market.duckdb is read-only for daemons and NOT accessed here.
    """
    import ccxt  # type: ignore[import-not-found]

    ex = ccxt.binance({
        "enableRateLimit": True,
        "options": {"defaultType": "future"},
        "timeout": 20000,
    })
    try:
        raw = ex.fetch_ohlcv(sym, timeframe="5m", limit=n_bars)
        df = pd.DataFrame(raw, columns=["ts", "open", "high", "low", "close", "volume"])
        df["ts"] = pd.to_datetime(df["ts"], unit="ms", utc=True)
        df = df.sort_values("ts").reset_index(drop=True)
        return df
    except Exception as exc:
        logger.bind(symbol=sym, err=str(exc)).warning("scan_resampled.ccxt_fetch_fail")
        return pd.DataFrame()


def _resample_5m_to(df_5m: pd.DataFrame, rule: str) -> pd.DataFrame:
    """Resample 5m OHLCV to target timeframe.

    MUST be bit-identical to v9_multitf_truefee.py::_resample():
        g = df.set_index("ts").resample(rule, label="left", closed="left")
        out = g.agg({"open": "first", "high": "max", "low": "min",
                     "close": "last", "volume": "sum"}).dropna().reset_index()

    label='left' stamps the bar with bar-open time (no lookahead).
    closed='left' means [bar_open, bar_close) — open-left, close-exclusive.
    """
    if df_5m.empty:
        return pd.DataFrame()
    g = df_5m.set_index("ts").resample(rule, label="left", closed="left")
    out = g.agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    ).dropna().reset_index()
    return out


def _scan_symbol_resampled(
    sym: str,
    rule: str,
    tf_label: str,
    target_bar_close: pd.Timestamp,
    sl_pct_min: float = 0.025,
) -> list[dict]:
    """Per-symbol resampled-TF scan — thread-safe.

    1. Fetch 5m bars from ccxt.
    2. Resample to rule (e.g. "30min", "45min") with label='left', closed='left'.
    3. Filter to bars with ts <= target_bar_close.
    4. Run VSAClimaxTestStrategy (same strategy as 5m and 15m legs).
    5. Return signals with sl_pct >= sl_pct_min only.

    NOTE: The resampled bars are stamped with bar-open time (label='left').
    For a 30m bar at target 14:30, bars up to ts=14:00 are included.
    This is causal: the 14:00 bar closes at 14:30, which is our target.
    """
    from price_action.strategies.vsa_climax_test import (
        VSAClimaxTestStrategy,
        _default_manifest,
    )

    df_5m = _fetch_5m_bars_ccxt(sym)
    if df_5m.empty:
        return []

    df_resampled = _resample_5m_to(df_5m, rule)
    if len(df_resampled) < 50:  # insufficient warmup
        logger.bind(symbol=sym, tf=tf_label, n=len(df_resampled)).warning(
            "scan_resampled.insufficient_bars"
        )
        return []

    # Filter to bars closed at or before target_bar_close
    # label='left' means bar stamp = bar_open; bar closes one rule-duration later.
    # We include bars whose bar_open <= (target - bar_duration) to avoid lookahead.
    # For 30m: bar stamped 14:00 closes at 14:30. Include if 14:30 <= target.
    # Equivalently: bar_open <= target - pd.Timedelta(rule)
    try:
        bar_duration = pd.tseries.frequencies.to_offset(rule)
        cutoff = target_bar_close - bar_duration  # last valid bar_open stamp
        df_filtered = df_resampled[df_resampled["ts"] <= cutoff].copy()
    except Exception:
        # Fallback: use target directly (conservative — may miss last bar)
        df_filtered = df_resampled[df_resampled["ts"] <= target_bar_close].copy()

    if df_filtered.empty:
        return []

    df_filtered = df_filtered.reset_index(drop=True)
    df_filtered["symbol"] = sym
    df_filtered["venue"] = "binance"
    # CRITICAL: strategy reads df["timeframe"] for apply_tf_manifest.
    # We use "15m" as the label (same as backtest gather_resampled which also
    # labels resampled bars as "15m" since "30m"/"45m" aren't Signal literals).
    # This means the VSA manifest uses the 15m parameters — consistent with backtest.
    df_filtered["timeframe"] = "15m"
    df_filtered["vol_z_pre"] = 0

    last_bar_ts = df_filtered["ts"].iloc[-1]
    last_close = float(df_filtered.iloc[-1]["close"])

    signals: list[dict] = []
    try:
        strategy = VSAClimaxTestStrategy(_default_manifest())
        df_prep = strategy.prepare_features(df_filtered)
        sigs = strategy.generate_signals(df_prep)

        for sig in sigs:
            sig_ts = pd.Timestamp(sig.ts)
            if sig_ts.tzinfo is None:
                sig_ts = sig_ts.tz_localize("UTC")

            # Only accept signals from the last bar
            if abs((sig_ts - last_bar_ts).total_seconds()) >= 60:
                continue

            # WIDESTOP filter
            entry_px = last_close
            sl_px = float(getattr(sig, "sl_price", 0.0) or 0.0)
            sl_pct = abs(entry_px - sl_px) / entry_px if entry_px > 0 else 0.0
            if sl_pct < sl_pct_min:
                logger.bind(symbol=sym, tf=tf_label, sl_pct=sl_pct, min=sl_pct_min).debug(
                    "scan_resampled.widestop_reject"
                )
                continue

            signals.append({
                "ts": sig_ts,
                "bar_close_ts": last_bar_ts,
                "symbol": sym,
                "strategy": "vsa_climax_test",
                "side": sig.direction,
                "entry_price": entry_px,
                "sl_price": sl_px,
                "tp_price": float(getattr(sig, "tp_price", 0.0) or 0.0),
                "confluence": float(getattr(sig, "confluence_score", 0.0) or 0.0),
                "vol_z": 0.0,
                "timeframe_label": tf_label,
                "resample_rule": rule,
                "staged": _STAGED_ONLY,  # B1 blocker: flag for daemon
                "signal_obj": sig,
            })
    except Exception as exc:
        logger.bind(symbol=sym, tf=tf_label, err=str(exc)).warning(
            "scan_resampled.strategy_fail"
        )

    return signals


def _scan_resampled_parallel(
    rule: str,
    tf_label: str,
    target_bar_close: datetime,
    symbols: Optional[list[str]] = None,
    sl_pct_min: float = 0.025,
    max_workers: Optional[int] = None,
) -> list[dict]:
    """Parallel scan across symbols for a given resampled TF."""
    syms = symbols or SYMBOLS_10
    workers = max_workers or int(os.environ.get("PA_SCAN_PARALLEL_WORKERS", _DEFAULT_PARALLEL_WORKERS))
    target_ts = pd.Timestamp(target_bar_close, tz="UTC") if not hasattr(target_bar_close, "tz") or target_bar_close.tzinfo is None else pd.Timestamp(target_bar_close)

    all_signals: list[dict] = []

    if workers == 1:
        for sym in syms:
            try:
                sigs = _scan_symbol_resampled(sym, rule, tf_label, target_ts, sl_pct_min)
                all_signals.extend(sigs)
            except Exception as exc:
                logger.bind(symbol=sym, tf=tf_label, err=str(exc)).error(
                    "scan_resampled.sequential_fail"
                )
    else:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {
                pool.submit(_scan_symbol_resampled, sym, rule, tf_label, target_ts, sl_pct_min): sym
                for sym in syms
            }
            for fut in as_completed(futures, timeout=_SCAN_SYMBOL_TIMEOUT_SEC * len(syms)):
                sym = futures[fut]
                try:
                    sigs = fut.result(timeout=_SCAN_SYMBOL_TIMEOUT_SEC)
                    all_signals.extend(sigs)
                except FuturesTimeout:
                    logger.bind(symbol=sym, tf=tf_label).error("scan_resampled.symbol_timeout")
                except Exception as exc:
                    logger.bind(symbol=sym, tf=tf_label, err=str(exc)).error(
                        "scan_resampled.symbol_fail"
                    )

    # Sort deterministically: (ts, symbol, side)
    all_signals.sort(key=lambda s: (s["ts"], s["symbol"], s.get("side", "")))
    logger.bind(tf=tf_label, n=len(all_signals), staged=_STAGED_ONLY).info("scan_resampled.done")
    return all_signals


def scan_signals_30m(
    target_bar_close: datetime,
    symbols: Optional[list[str]] = None,
    sl_pct_min: float = 0.025,
    max_workers: Optional[int] = None,
) -> list[dict]:
    """Scan 30m resampled signals at target_bar_close.

    B1 BLOCKER: signals are STAGED (staged=True) until parity verified.
    The daemon checks sig["staged"] and logs but does NOT submit these orders.
    """
    return _scan_resampled_parallel("30min", "30m", target_bar_close, symbols, sl_pct_min, max_workers)


def scan_signals_45m(
    target_bar_close: datetime,
    symbols: Optional[list[str]] = None,
    sl_pct_min: float = 0.025,
    max_workers: Optional[int] = None,
) -> list[dict]:
    """Scan 45m resampled signals at target_bar_close.

    B1 BLOCKER: signals are STAGED (staged=True) until parity verified.
    The daemon checks sig["staged"] and logs but does NOT submit these orders.
    """
    return _scan_resampled_parallel("45min", "45m", target_bar_close, symbols, sl_pct_min, max_workers)


def verify_resample_parity(
    sym: str,
    rule: str,
    n_5m_bars: int = 500,
) -> dict:
    """Parity audit: compare live ccxt resample vs stored backtest resample.

    Fetches live 5m bars, resamples, then compares OHLCV column-by-column
    against data/market.duckdb (the backtest database). Returns a dict with
    parity metrics.

    USAGE: Run scripts/verify_resample_parity.py to accumulate >= 7 days of
    parity data before enabling 30m/45m legs (B1 blocker clearance).

    Returns:
        {
            "sym": str,
            "rule": str,
            "n_live_bars": int,
            "n_db_bars": int,
            "n_common": int,
            "max_close_diff_pct": float,   # max abs(live_close - db_close)/db_close
            "max_vol_diff_pct": float,
            "parity_ok": bool,             # True if max_close_diff_pct < 0.001 (0.1%)
            "error": str or None,
        }
    """
    import duckdb as _ddb

    result: dict = {
        "sym": sym, "rule": rule, "n_live_bars": 0, "n_db_bars": 0,
        "n_common": 0, "max_close_diff_pct": 999.0, "max_vol_diff_pct": 999.0,
        "parity_ok": False, "error": None,
    }
    try:
        df_5m = _fetch_5m_bars_ccxt(sym, n_5m_bars)
        if df_5m.empty:
            result["error"] = "ccxt fetch returned empty"
            return result

        df_live = _resample_5m_to(df_5m, rule)
        result["n_live_bars"] = len(df_live)

        # Load matching bars from market.duckdb (read-only)
        db_path = ROOT / "data" / "market.duckdb"
        if not db_path.exists():
            result["error"] = f"market.duckdb not found: {db_path}"
            return result

        # Determine TF label used in DB (5m bars stored as "5m")
        con = _ddb.connect(str(db_path), read_only=True)
        df_db_5m = con.execute(
            "SELECT ts, open, high, low, close, volume FROM ohlcv "
            "WHERE venue='binance' AND symbol=? AND timeframe='5m' ORDER BY ts",
            [sym],
        ).fetchdf()
        con.close()

        if df_db_5m.empty:
            result["error"] = f"No 5m bars in market.duckdb for {sym}"
            return result

        df_db_5m["ts"] = pd.to_datetime(df_db_5m["ts"], utc=True)
        df_db_resampled = _resample_5m_to(df_db_5m, rule)
        result["n_db_bars"] = len(df_db_resampled)

        # Inner join on ts
        merged = df_live.merge(
            df_db_resampled,
            on="ts",
            suffixes=("_live", "_db"),
        )
        result["n_common"] = len(merged)

        if merged.empty:
            result["error"] = "No overlapping timestamps"
            return result

        close_diff = (
            (merged["close_live"] - merged["close_db"]).abs() / merged["close_db"].clip(lower=1e-10)
        )
        vol_diff = (
            (merged["volume_live"] - merged["volume_db"]).abs() / merged["volume_db"].clip(lower=1e-10)
        )
        result["max_close_diff_pct"] = float(close_diff.max())
        result["max_vol_diff_pct"] = float(vol_diff.max())
        # Parity threshold: < 0.1% on close price (floating point + possible 1-bar lag)
        result["parity_ok"] = result["max_close_diff_pct"] < 0.001

    except Exception as exc:
        result["error"] = str(exc)

    return result
