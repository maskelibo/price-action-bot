"""Forward Paper-Sim Harness — Champion (15m VSA-WIDESTOP) vs V13 Candidate.

PURPOSE
-------
Side-by-side forward simulation of two strategy legs on LIVE Binance price
data (read-only) so we can compare equity curves over weeks without placing
any real orders and without touching the running champion daemon.

KEY DESIGN DECISIONS
---------------------
1.  NO real orders, NO PA_LIVE_CONFIRM, NO testnet account writes.
    Fills are SIMULATED at the next-bar open price.
2.  FIXED-FRACTION sizing: risk = RISK_PCT * E0_FIXED (E0 never grows).
    This eliminates the compounding inflation bug identified in v12/v13 research.
3.  TRUE ~18 bps round-trip fee (entry 9 bps + exit 9 bps).
    Conservative 10 bps additional slippage on 5m small-cap legs.
4.  SEPARATE DuckDB tables: champion_sim / v13_sim in data/forward_sim.duckdb.
    Running champion's journals (futures_journal*.duckdb) are never touched.
5.  Daemon PIDs 53708 / 70580 are not disturbed — this process uses its own
    ccxt exchange connection (read-only market data fetch only).

CHAMPION LEG
-----------
Strategy  : single-TF 15m VSA-WIDESTOP (vsa_climax_test) + top-4 strategies
Entry      : sl_pct >= 0.025 filter (WIDESTOP gate)
Exit       : BASELINE — trail 1.5, stage 2, TP1 30%@1R / TP2 30%@1.5R, time-stop 30 bars
             force_exit_from_entry=False
Symbols   : 19 symbols (SYMS19)

V13 LEG
-------
Strategy  : multi-TF (5m entry confirmation + 15m signal) VSA-WIDESTOP
HTF filter: 1d EMA50 alignment (V12's surviving OOS lever)
Entry      : sl_pct >= 0.025, htf_1d EMA50 aligned
Exit       : BASELINE exit (same as champion)
Symbols   : 5m=10 sym, 15m=19 sym
30m/45m   : DROPPED (V11 finding: resampled MTF hurt performance)

HONEST SIM NOTE
---------------
This is a SIMULATION — fills are modeled at next-bar open with a fee+slippage
estimate. It is NOT real testnet execution. The comparison measures strategy
LOGIC quality (signal generation + exit rules), not real fill economics.
Real-fill confirmation requires a 2nd testnet account (future work).

Usage
-----
    # One-shot (test a single bar cycle):
    python scripts/forward_sim_compare.py --once

    # Daemon mode (runs until killed — designed for launchd):
    python scripts/forward_sim_compare.py

    # Status check (print daily comparison):
    python scripts/forward_sim_compare.py --report
"""
from __future__ import annotations

import argparse
import os
import sys
import time
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

os.environ["PA_DUCKDB_READ_ONLY"] = "true"
os.environ["PA_LOG_QUIET"] = "1"

import warnings
warnings.filterwarnings("ignore")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

# ---------------------------------------------------------------------------
# Lazy imports — allow --report to work without all deps present
# ---------------------------------------------------------------------------
import numpy as np
import pandas as pd
import duckdb

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DB_MARKET = ROOT / "data" / "market.duckdb"
DB_SIM    = ROOT / "data" / "forward_sim.duckdb"

# Fee model: TRUE 18 bps round-trip.
# Binance USDM futures VIP-0: ~7.5 bps taker/leg × 2 legs = 15 bps.
# +3 bps conservative slippage margin = 18 bps round-trip.
FEE_RT_BPS = 18.0            # round-trip, 9 bps entry + 9 bps exit
SLIP_BPS_15M = 5.0           # additional slippage on 15m legs (large/mid cap)
SLIP_BPS_5M  = 10.0          # additional slippage on 5m legs (smaller notional, tighter spread)

# Fixed-fraction parameters — non-compounding.
# Size every trade as RISK_PCT of E0_FIXED.  E0 NEVER changes.
E0_FIXED   = 10_000.0        # fixed starting equity for both legs ($10k)
RISK_PCT   = 0.005           # 0.5% risk per trade (same as champion backtest)
MAX_NOTIONAL_PCT = 0.15      # per YAML: max notional = 15% of E0
CONC_PCT   = 0.15            # per-symbol concentration cap: 15% of E0

# WIDESTOP gate
SL_PCT_MIN_15M = 0.025
SL_PCT_MIN_5M  = 0.030       # 5m uses tighter minimum (per deployed config)

# Warmup bars needed before first signal
STRATEGY_WARMUP_BARS = 500

# V13 HTF 1d EMA period
HTF_EMA_PERIOD = 50

# Symbols
SYMS10 = [
    "BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "ADA/USDT",
    "AVAX/USDT", "LINK/USDT", "DOT/USDT", "DOGE/USDT", "XRP/USDT",
]
SYMS19 = SYMS10 + [
    "ZEC/USDT", "NEAR/USDT", "FIL/USDT", "XLM/USDT",
    "TRX/USDT", "UNI/USDT", "ATOM/USDT", "AAVE/USDT", "ALGO/USDT",
]

# BASELINE exit config (from v13 research — force_exit_from_entry=False keeps runner tail)
BASELINE_EXIT = dict(
    runner_trail_mult=1.5,
    trail_activate_stage=2,
    tp1_R=1.0,
    tp2_R=1.5,
    tp1_close_pct=0.30,
    tp2_close_pct=0.30,
    runner_force_exit_method="time",
    runner_force_exit_bars=30,
    force_exit_from_entry=False,
)

# Heartbeat / timing
BAR_SECONDS_15M = 15 * 60
BAR_SECONDS_5M  = 5 * 60
LOOP_POLL_SLEEP = 10          # seconds between "are we at a new bar?" checks
REPORT_PATH     = ROOT / "reports" / "forward_sim" / "daily.md"

# Strategy catalog (champion = 4-strategy top set, same as live daemon)
_CHAMPION_STRATEGIES_15M = [
    ("vsa_climax_test",           "VSAClimaxTestStrategy"),
    ("brooks_failed_breakout",    "BrooksFailedBreakoutStrategy"),
    ("anchored_vwap_reversal",    "AnchoredVWAPReversalStrategy"),
    ("engulfing_continuation",    "EngulfingContinuationStrategy"),
]
_V13_STRATEGIES_15M = _CHAMPION_STRATEGIES_15M   # same strategies, HTF filter added on top


# ---------------------------------------------------------------------------
# Journal schema
# ---------------------------------------------------------------------------

SCHEMA_SIM_TRADES = """
CREATE TABLE IF NOT EXISTS {table} (
    trade_id        VARCHAR PRIMARY KEY,
    leg             VARCHAR,          -- 'champion' or 'v13'
    symbol          VARCHAR,
    tf              VARCHAR,          -- '15m' or '5m'
    strategy        VARCHAR,
    side            VARCHAR,          -- 'long' or 'short'
    entry_ts        TIMESTAMP,
    entry_bar_ts    TIMESTAMP,        -- bar that generated the signal
    entry_price     DOUBLE,           -- simulated fill: next-bar open + slippage
    sl_price        DOUBLE,
    tp1_price       DOUBLE,
    tp2_price       DOUBLE,
    initial_sl_pct  DOUBLE,
    risk_dollars    DOUBLE,           -- FIXED_FRACTION: RISK_PCT * E0_FIXED (after notional cap)
    notional_usdt   DOUBLE,
    status          VARCHAR,          -- 'open' | 'closed_tp1' | 'closed_tp2' | 'closed_sl' | 'closed_ts'
    exit_ts         TIMESTAMP,
    exit_price      DOUBLE,
    pnl_usdt        DOUBLE,           -- net of fees (both legs)
    r_multiple      DOUBLE,
    fee_usdt        DOUBLE,
    confluence      DOUBLE,
    htf_aligned     DOUBLE,           -- v13 only: 1.0=aligned, 0.0=against, -1.0=no data
    notes           VARCHAR,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
"""

SCHEMA_EQUITY = """
CREATE TABLE IF NOT EXISTS {table}_equity (
    snap_id     VARCHAR PRIMARY KEY,
    leg         VARCHAR,
    ts          TIMESTAMP,
    equity      DOUBLE,          -- E0 + cumulative closed PnL (fixed-fraction, no compounding)
    open_pnl    DOUBLE,          -- unrealized mark-to-market on open positions
    total_pnl   DOUBLE,          -- realized closed PnL (equity - E0)
    n_open      INTEGER,
    n_trades    INTEGER,
    notes       VARCHAR
)
"""


def init_db(db_path: Path) -> None:
    """Create tables if not present. Idempotent."""
    con = duckdb.connect(str(db_path))
    try:
        for leg in ("champion_sim", "v13_sim"):
            con.execute(SCHEMA_SIM_TRADES.format(table=leg))
            con.execute(SCHEMA_EQUITY.format(table=leg))
        con.commit()
    finally:
        con.close()


# ---------------------------------------------------------------------------
# Market data helpers (READ-ONLY)
# ---------------------------------------------------------------------------

def _fetch_ohlcv_from_db(sym: str, tf: str, n_bars: int = STRATEGY_WARMUP_BARS) -> pd.DataFrame | None:
    """Read last n_bars of OHLCV from market.duckdb (read-only)."""
    try:
        con = duckdb.connect(str(DB_MARKET), read_only=True)
        df = con.execute(
            "SELECT ts, open, high, low, close, volume FROM ohlcv "
            "WHERE venue='binance' AND symbol=? AND timeframe=? ORDER BY ts DESC LIMIT ?",
            [sym, tf, n_bars]
        ).fetchdf()
        con.close()
        if df.empty:
            return None
        df["ts"] = pd.to_datetime(df["ts"], utc=True)
        df = df.sort_values("ts").reset_index(drop=True)
        df["symbol"]    = sym
        df["venue"]     = "binance"
        df["timeframe"] = tf
        return df
    except Exception as exc:
        print(f"[forward_sim] DB read fail {sym}/{tf}: {exc}")
        return None


def _fetch_fresh_bars_ccxt(sym: str, tf: str, n_bars: int = 60) -> pd.DataFrame | None:
    """Fetch fresh bars from Binance via ccxt (read-only, no write).
    Used as fallback when DB data is stale (>30 min old).
    """
    try:
        import ccxt
        ex = ccxt.binance({"enableRateLimit": True, "options": {"defaultType": "future"}})
        tf_seconds = {"5m": 300, "15m": 900, "1d": 86400}
        since_ms = int((datetime.now(UTC) - timedelta(seconds=tf_seconds.get(tf, 900) * n_bars)).timestamp() * 1000)
        raw = ex.fetch_ohlcv(sym, timeframe=tf, since=since_ms, limit=n_bars)
        if not raw:
            return None
        df = pd.DataFrame(raw, columns=["ts_ms", "open", "high", "low", "close", "volume"])
        df["ts"] = pd.to_datetime(df["ts_ms"], unit="ms", utc=True)
        df = df.drop(columns=["ts_ms"])
        for col in ("open", "high", "low", "close", "volume"):
            df[col] = pd.to_numeric(df[col], errors="coerce")
        df["symbol"]    = sym
        df["venue"]     = "binance"
        df["timeframe"] = tf
        return df.sort_values("ts").reset_index(drop=True)
    except Exception as exc:
        print(f"[forward_sim] ccxt fetch fail {sym}/{tf}: {exc}")
        return None


def _get_bars(sym: str, tf: str) -> pd.DataFrame | None:
    """Get bars: prefer DB, fall back to ccxt if stale."""
    df = _fetch_ohlcv_from_db(sym, tf)
    if df is not None and not df.empty:
        last_ts = df["ts"].iloc[-1]
        if last_ts.tzinfo is None:
            last_ts = last_ts.tz_localize("UTC")
        age_min = (datetime.now(UTC) - last_ts.to_pydatetime()).total_seconds() / 60
        if age_min > 30:
            # DB stale — refresh in memory from ccxt (no DB write)
            fresh = _fetch_fresh_bars_ccxt(sym, tf, n_bars=60)
            if fresh is not None and not fresh.empty:
                df = pd.concat([df, fresh], ignore_index=True)
                df = df.drop_duplicates(subset=["ts"], keep="last")
                df = df.sort_values("ts").reset_index(drop=True)
    elif df is None or df.empty:
        df = _fetch_fresh_bars_ccxt(sym, tf, n_bars=STRATEGY_WARMUP_BARS)
    return df


def _load_htf_1d_ema(sym: str) -> pd.DataFrame | None:
    """Load 1d bars and compute EMA50 for HTF alignment filter (V13 leg)."""
    try:
        con = duckdb.connect(str(DB_MARKET), read_only=True)
        df = con.execute(
            "SELECT ts, close FROM ohlcv WHERE venue='binance' AND symbol=? "
            "AND timeframe='1d' ORDER BY ts",
            [sym]
        ).fetchdf()
        con.close()
        if df.empty:
            return None
        df["ts"] = pd.to_datetime(df["ts"], utc=True)
        df = df.sort_values("ts").reset_index(drop=True)
        df["ema50"] = df["close"].ewm(span=HTF_EMA_PERIOD, adjust=False).mean()
        return df
    except Exception:
        return None


_HTF_CACHE: dict[str, pd.DataFrame] = {}


def _htf_aligned(sym: str, entry_ts: pd.Timestamp, side: str) -> float:
    """1.0 = 1d daily close on trade side of EMA50 (lookahead-free).
    -1.0 = no HTF data. 0.0 = against trend.
    """
    if sym not in _HTF_CACHE:
        d1 = _load_htf_1d_ema(sym)
        if d1 is None or d1.empty:
            return -1.0
        _HTF_CACHE[sym] = d1
    d1 = _HTF_CACHE[sym]
    if d1.empty or "ts" not in d1.columns:
        return -1.0
    # Use bar at or before entry (lookahead-free: search sorted)
    te = entry_ts
    if te.tzinfo is not None:
        te_naive = te.tz_convert("UTC").tz_localize(None)
    else:
        te_naive = te
    d1_ts    = d1["ts"]
    d1_naive = d1_ts.dt.tz_localize(None) if d1_ts.dt.tz is not None else d1_ts
    j = int(np.searchsorted(d1_naive.values, np.datetime64(te_naive), side="right")) - 1
    if j < 0 or j >= len(d1):
        return -1.0
    ema = d1["ema50"].iloc[j]
    close = d1["close"].iloc[j]
    if np.isnan(ema) or np.isnan(close):
        return -1.0
    above = close > ema
    return 1.0 if ((side == "long" and above) or (side == "short" and not above)) else 0.0


# ---------------------------------------------------------------------------
# Signal scanning (re-uses champion's scan pipeline)
# ---------------------------------------------------------------------------

def _scan_signals_for_sym(
    sym: str,
    tf: str,
    target_bar_close: pd.Timestamp,
    strategy_pairs: list[tuple[str, str]],
    sl_pct_min: float,
) -> list[dict]:
    """Scan one symbol/TF for signals at target_bar_close."""
    df = _get_bars(sym, tf)
    if df is None or df.empty:
        return []

    # Apply warmup window
    if len(df) > STRATEGY_WARMUP_BARS:
        df = df.tail(STRATEGY_WARMUP_BARS).reset_index(drop=True)

    df["symbol"]    = sym
    df["venue"]     = "binance"
    df["timeframe"] = tf
    if "vol_z_pre" not in df.columns:
        df["vol_z_pre"] = 0

    # Causal: only bars up to target_bar_close
    df_filtered = df[df["ts"] <= target_bar_close]
    if df_filtered.empty:
        return []

    last_bar_ts  = df_filtered["ts"].iloc[-1]
    last_close   = float(df_filtered.iloc[-1]["close"])

    results: list[dict] = []
    for module_name, class_name in strategy_pairs:
        try:
            mod = __import__(
                f"price_action.strategies.{module_name}",
                fromlist=[class_name, "_default_manifest"],
            )
            cls = getattr(mod, class_name)
            manifest_fn = getattr(mod, "_default_manifest", None)
            if not manifest_fn:
                continue
            strategy = cls(manifest_fn())
            df_prep  = strategy.prepare_features(df_filtered.copy())
            sigs     = strategy.generate_signals(df_prep)

            for sig in sigs:
                sig_ts = pd.Timestamp(sig.ts)
                if sig_ts.tzinfo is None:
                    sig_ts = sig_ts.tz_localize("UTC")
                # Only signals emitted on the last bar
                if abs((sig_ts - last_bar_ts).total_seconds()) > 60:
                    continue

                # WIDESTOP gate
                ep = last_close
                sl = sig.sl_price
                sl_pct = abs(sl - ep) / ep if ep > 0 else 0.0
                if sl_pct < sl_pct_min:
                    continue

                results.append({
                    "ts":           sig_ts,
                    "bar_close_ts": last_bar_ts,
                    "symbol":       sym,
                    "tf":           tf,
                    "strategy":     module_name,
                    "side":         sig.direction,
                    "entry_price":  ep,           # approximate; refined at next-bar open
                    "sl_price":     sig.sl_price,
                    "tp_price":     sig.tp_price,
                    "sl_pct":       sl_pct,
                    "confluence":   sig.confluence_score,
                    "signal_obj":   sig,
                })
        except Exception as exc:
            print(f"[forward_sim] scan fail {sym}/{tf}/{module_name}: {type(exc).__name__}: {exc}")

    return results


def scan_champion_signals(target_bar_close: pd.Timestamp) -> list[dict]:
    """Scan all 19 symbols on 15m for champion leg."""
    signals = []
    for sym in SYMS19:
        try:
            sigs = _scan_signals_for_sym(
                sym, "15m", target_bar_close,
                _CHAMPION_STRATEGIES_15M, SL_PCT_MIN_15M,
            )
            for s in sigs:
                s["leg"] = "champion"
                s["htf_aligned"] = -1.0   # champion does not use HTF filter
            signals.extend(sigs)
        except Exception as exc:
            print(f"[forward_sim] champion scan fail {sym}: {exc}")
    return signals


def scan_v13_signals(target_bar_close_15m: pd.Timestamp) -> list[dict]:
    """Scan for V13 leg: 15m(19sym) + 5m(10sym), with HTF 1d alignment filter."""
    signals = []

    # 15m signals (same strategies as champion)
    for sym in SYMS19:
        try:
            sigs = _scan_signals_for_sym(
                sym, "15m", target_bar_close_15m,
                _V13_STRATEGIES_15M, SL_PCT_MIN_15M,
            )
            for s in sigs:
                s["leg"] = "v13"
                htf = _htf_aligned(sym, pd.Timestamp(s["bar_close_ts"]), s["side"])
                s["htf_aligned"] = htf
            signals.extend(sigs)
        except Exception as exc:
            print(f"[forward_sim] v13/15m scan fail {sym}: {exc}")

    # 5m signals (10 sym subset — same VSA strategies)
    target_bar_close_5m = target_bar_close_15m   # trigger on 15m boundary; 5m has its own bar count
    for sym in SYMS10:
        try:
            # Find last closed 5m bar at or before the 15m boundary
            tbc_5m = pd.Timestamp(target_bar_close_15m)
            sigs = _scan_signals_for_sym(
                sym, "5m", tbc_5m,
                _V13_STRATEGIES_15M, SL_PCT_MIN_5M,
            )
            for s in sigs:
                s["leg"] = "v13"
                htf = _htf_aligned(sym, pd.Timestamp(s["bar_close_ts"]), s["side"])
                s["htf_aligned"] = htf
            signals.extend(sigs)
        except Exception as exc:
            print(f"[forward_sim] v13/5m scan fail {sym}: {exc}")

    return signals


# ---------------------------------------------------------------------------
# Fixed-fraction position admission (prevents infinite-capital inflation)
# ---------------------------------------------------------------------------

class FixedFractionLedger:
    """Tracks open sim positions for a single leg to enforce sizing caps.

    Sizing is FIXED against E0_FIXED (never compounds).
    All caps are vs E0_FIXED so the sim is conservative under any run length.
    """

    def __init__(self, leg: str, e0: float = E0_FIXED) -> None:
        self.leg = leg
        self.e0  = e0
        # open positions: list of dict with exit tracking state
        self._open: list[dict] = []
        self._realized_pnl = 0.0   # cumulative closed PnL

    def equity(self) -> float:
        return self.e0 + self._realized_pnl

    def open_pnl(self) -> float:
        return sum(p.get("unrealized_pnl", 0.0) for p in self._open)

    def n_open(self) -> int:
        return len(self._open)

    def can_admit(self, sym: str, sl_pct: float, tf: str) -> tuple[bool, float, float]:
        """Returns (admitted, risk_dollars, notional_usdt).

        FIXED-FRACTION: sizing is always off E0_FIXED (never current equity).
        This is the core non-compounding invariant.

          risk_dollars = RISK_PCT * E0_FIXED   ← FIXED, never compounds
          notional     = risk_dollars / sl_pct
          capped at MAX_NOTIONAL_PCT * E0_FIXED
          rejected if per-symbol notional would exceed CONC_PCT * E0_FIXED
        """
        if sl_pct <= 0:
            return False, 0.0, 0.0
        # CRITICAL: always size off E0_FIXED, not self.e0 (which includes realized PnL)
        risk_d       = RISK_PCT * E0_FIXED
        notional     = risk_d / sl_pct
        notional_cap = MAX_NOTIONAL_PCT * E0_FIXED
        if notional > notional_cap:
            notional = notional_cap
            risk_d   = notional * sl_pct
        # per-symbol concentration cap vs E0_FIXED (not current equity)
        sym_exposure = sum(p["notional"] for p in self._open if p["symbol"] == sym)
        if sym_exposure + notional > CONC_PCT * E0_FIXED:
            return False, 0.0, 0.0
        return True, risk_d, notional

    def open_position(self, pos: dict) -> None:
        self._open.append(pos)

    def close_position(self, trade_id: str, exit_price: float, exit_ts: datetime, reason: str) -> dict | None:
        """Close a tracked position. Returns updated position dict or None if not found."""
        for i, p in enumerate(self._open):
            if p["trade_id"] == trade_id:
                pos = self._open.pop(i)
                ep    = pos["entry_price"]
                qty   = pos["notional"] / ep if ep > 0 else 0.0
                side  = pos["side"]
                raw_pnl = (exit_price - ep) * qty if side == "long" else (ep - exit_price) * qty
                # Subtract fee both legs
                fee_entry = pos.get("fee_entry_usdt", 0.0)
                fee_exit  = pos["notional"] * (FEE_RT_BPS / 2.0 / 10_000)
                net_pnl   = raw_pnl - fee_exit
                r_mult    = net_pnl / pos["risk_dollars"] if pos["risk_dollars"] > 0 else 0.0
                pos.update({
                    "status":      reason,
                    "exit_ts":     exit_ts,
                    "exit_price":  exit_price,
                    "pnl_usdt":    net_pnl,
                    "r_multiple":  r_mult,
                    "fee_usdt":    fee_entry + fee_exit,
                    "unrealized_pnl": 0.0,
                })
                self._realized_pnl += net_pnl
                return pos
        return None

    def update_marks(self, prices: dict[str, float]) -> None:
        """Update unrealized PnL for open positions given current prices."""
        for p in self._open:
            sym = p["symbol"]
            if sym in prices:
                ep    = p["entry_price"]
                qty   = p["notional"] / ep if ep > 0 else 0.0
                px    = prices[sym]
                if p["side"] == "long":
                    p["unrealized_pnl"] = (px - ep) * qty
                else:
                    p["unrealized_pnl"] = (ep - px) * qty

    def check_exits(self, prices: dict[str, float], current_ts: datetime) -> list[dict]:
        """Check TP1 / TP2 / SL conditions against current prices.
        Returns list of closed position dicts.
        """
        closed = []
        still_open = []
        for p in self._open:
            sym = p["symbol"]
            px  = prices.get(sym)
            if px is None:
                still_open.append(p)
                continue

            side  = p["side"]
            sl    = p["sl_price"]
            tp1   = p.get("tp1_price")
            tp2   = p.get("tp2_price")
            status_now = p.get("status_partial", "open")

            triggered_reason = None

            if side == "long":
                if px <= sl:
                    triggered_reason = "closed_sl"
                elif tp2 and px >= tp2 and status_now == "partial_tp1":
                    triggered_reason = "closed_tp2"
                elif tp1 and px >= tp1 and status_now == "open":
                    # TP1 hit: partially close (30%), keep runner
                    triggered_reason = "partial_tp1"
            else:
                if px >= sl:
                    triggered_reason = "closed_sl"
                elif tp2 and px <= tp2 and status_now == "partial_tp1":
                    triggered_reason = "closed_tp2"
                elif tp1 and px <= tp1 and status_now == "open":
                    triggered_reason = "partial_tp1"

            # Time-stop: 30 bars × TF
            tf_sec = 900 if p["tf"] == "15m" else 300
            max_duration = 30 * tf_sec
            elapsed = (current_ts - p["entry_ts"]).total_seconds()
            if elapsed >= max_duration and triggered_reason is None:
                triggered_reason = "closed_ts"

            if triggered_reason == "partial_tp1":
                p["status_partial"] = "partial_tp1"
                still_open.append(p)
            elif triggered_reason is not None:
                pos = p.copy()
                ep    = pos["entry_price"]
                qty   = pos["notional"] / ep if ep > 0 else 0.0
                sign  = 1.0 if side == "long" else -1.0
                raw_pnl = sign * (px - ep) * qty
                fee_exit = pos["notional"] * (FEE_RT_BPS / 2.0 / 10_000)
                net_pnl  = raw_pnl - pos.get("fee_entry_usdt", 0.0) - fee_exit
                r_mult   = net_pnl / pos["risk_dollars"] if pos["risk_dollars"] > 0 else 0.0
                pos.update({
                    "status":      triggered_reason,
                    "exit_ts":     current_ts,
                    "exit_price":  px,
                    "pnl_usdt":    net_pnl,
                    "r_multiple":  r_mult,
                    "fee_usdt":    pos.get("fee_entry_usdt", 0.0) + fee_exit,
                    "unrealized_pnl": 0.0,
                })
                self._realized_pnl += net_pnl
                closed.append(pos)
            else:
                still_open.append(p)

        self._open = still_open
        return closed


# ---------------------------------------------------------------------------
# Simulated fill at next-bar open
# ---------------------------------------------------------------------------

def _sim_fill_price(entry_price: float, side: str, tf: str) -> float:
    """Simulate fill at next-bar open with conservative slippage.
    ENTRY ONLY — fee accounted separately.
    """
    slip_bps = SLIP_BPS_5M if tf == "5m" else SLIP_BPS_15M
    slip = slip_bps / 10_000.0
    if side == "long":
        return entry_price * (1.0 + slip)
    else:
        return entry_price * (1.0 - slip)


def _compute_tp_levels(fill_price: float, sl_price: float, side: str) -> tuple[float, float]:
    """Compute TP1 and TP2 prices from BASELINE exit config."""
    tp1_R = BASELINE_EXIT["tp1_R"]
    tp2_R = BASELINE_EXIT["tp2_R"]
    risk  = abs(fill_price - sl_price)
    if side == "long":
        tp1 = fill_price + tp1_R * risk
        tp2 = fill_price + tp2_R * risk
    else:
        tp1 = fill_price - tp1_R * risk
        tp2 = fill_price - tp2_R * risk
    return tp1, tp2


# ---------------------------------------------------------------------------
# Journal persistence
# ---------------------------------------------------------------------------

def _write_trade(con: duckdb.DuckDBPyConnection, table: str, pos: dict) -> None:
    """Upsert a trade record to the sim journal."""
    con.execute(f"""
        INSERT INTO {table} (
            trade_id, leg, symbol, tf, strategy, side,
            entry_ts, entry_bar_ts, entry_price, sl_price, tp1_price, tp2_price,
            initial_sl_pct, risk_dollars, notional_usdt,
            status, exit_ts, exit_price, pnl_usdt, r_multiple, fee_usdt,
            confluence, htf_aligned, notes
        ) VALUES (
            ?, ?, ?, ?, ?, ?,
            ?, ?, ?, ?, ?, ?,
            ?, ?, ?,
            ?, ?, ?, ?, ?, ?,
            ?, ?, ?
        )
        ON CONFLICT (trade_id) DO UPDATE SET
            status=EXCLUDED.status, exit_ts=EXCLUDED.exit_ts,
            exit_price=EXCLUDED.exit_price, pnl_usdt=EXCLUDED.pnl_usdt,
            r_multiple=EXCLUDED.r_multiple, fee_usdt=EXCLUDED.fee_usdt
    """, [
        pos["trade_id"],
        pos["leg"],
        pos["symbol"],
        pos["tf"],
        pos["strategy"],
        pos["side"],
        pos["entry_ts"],
        pos.get("entry_bar_ts"),
        pos["entry_price"],
        pos["sl_price"],
        pos.get("tp1_price"),
        pos.get("tp2_price"),
        pos["sl_pct"],
        pos["risk_dollars"],
        pos["notional"],
        pos.get("status", "open"),
        pos.get("exit_ts"),
        pos.get("exit_price"),
        pos.get("pnl_usdt"),
        pos.get("r_multiple"),
        pos.get("fee_usdt"),
        pos.get("confluence"),
        pos.get("htf_aligned"),
        pos.get("notes"),
    ])


def _write_equity_snap(con: duckdb.DuckDBPyConnection, table: str, leg: str,
                        ledger: FixedFractionLedger, ts: datetime, n_trades: int) -> None:
    snap_id = uuid.uuid4().hex[:16]
    equity  = ledger.equity()
    open_pnl = ledger.open_pnl()
    con.execute(f"""
        INSERT INTO {table}_equity (snap_id, leg, ts, equity, open_pnl, total_pnl, n_open, n_trades)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, [snap_id, leg, ts, equity, open_pnl, equity - E0_FIXED, ledger.n_open(), n_trades])


# ---------------------------------------------------------------------------
# Idempotency: skip signals we already have an open position on same symbol+side
# ---------------------------------------------------------------------------

def _already_open(ledger: FixedFractionLedger, sym: str, side: str) -> bool:
    return any(p["symbol"] == sym and p["side"] == side for p in ledger._open)


# ---------------------------------------------------------------------------
# Fetch current prices for mark-to-market
# ---------------------------------------------------------------------------

_ccxt_exchange: Any = None


def _get_ccxt_exchange() -> Any:
    global _ccxt_exchange
    if _ccxt_exchange is not None:
        return _ccxt_exchange
    try:
        import ccxt
        _ccxt_exchange = ccxt.binance({
            "enableRateLimit": True,
            "options": {"defaultType": "future"},
        })
    except Exception as exc:
        print(f"[forward_sim] ccxt init fail: {exc}")
        return None
    return _ccxt_exchange


def _fetch_current_prices(symbols: list[str]) -> dict[str, float]:
    """Fetch last prices for a list of symbols. Returns {sym: price}."""
    ex = _get_ccxt_exchange()
    if ex is None:
        return {}
    prices = {}
    for sym in symbols:
        try:
            t = ex.fetch_ticker(sym)
            px = float(t.get("last") or t.get("close") or 0.0)
            if px > 0:
                prices[sym] = px
        except Exception:
            pass
    return prices


# ---------------------------------------------------------------------------
# Main simulation tick
# ---------------------------------------------------------------------------

def _run_tick(
    champion_ledger: FixedFractionLedger,
    v13_ledger:      FixedFractionLedger,
    target_bar_close: datetime,
) -> dict:
    """Process one 15m bar close.
    1. Scan signals for both legs.
    2. Fetch next-bar open prices (≈ current bid/ask).
    3. Simulate fills (with slippage, fixed-fraction sizing).
    4. Check exit conditions on open positions.
    5. Persist to forward_sim.duckdb.
    Returns summary dict.
    """
    tbc = pd.Timestamp(target_bar_close, tz="UTC") if not hasattr(target_bar_close, "tzinfo") \
          else pd.Timestamp(target_bar_close)
    if tbc.tzinfo is None:
        tbc = tbc.tz_localize("UTC")

    now_utc = datetime.now(UTC)
    print(f"\n[forward_sim] tick bar_close={tbc.strftime('%Y-%m-%d %H:%M')} UTC  now={now_utc.strftime('%H:%M:%S')}")

    # Collect all symbols we need prices for
    all_syms = list(set(
        [p["symbol"] for p in champion_ledger._open] +
        [p["symbol"] for p in v13_ledger._open] +
        SYMS19
    ))
    prices = _fetch_current_prices(all_syms)
    print(f"  prices fetched: {len(prices)}/{len(all_syms)}")

    # Update unrealized PnL
    champion_ledger.update_marks(prices)
    v13_ledger.update_marks(prices)

    # Check exits on open positions
    champion_exits = champion_ledger.check_exits(prices, now_utc)
    v13_exits      = v13_ledger.check_exits(prices, now_utc)
    print(f"  exits — champion:{len(champion_exits)} v13:{len(v13_exits)}")

    # Scan new signals
    champion_signals = scan_champion_signals(tbc)
    v13_signals      = scan_v13_signals(tbc)

    # V13: apply HTF alignment filter
    v13_signals_htf = [s for s in v13_signals if s.get("htf_aligned", -1.0) == 1.0]
    print(f"  signals — champion:{len(champion_signals)} v13_raw:{len(v13_signals)} v13_htf_pass:{len(v13_signals_htf)}")

    def _process_signals(signals: list[dict], ledger: FixedFractionLedger, leg: str) -> list[dict]:
        new_positions = []
        for sig in signals:
            sym  = sig["symbol"]
            side = sig["side"]
            tf   = sig["tf"]
            sl   = sig["sl_price"]
            sl_pct = sig["sl_pct"]

            # Idempotency: skip if already have open position same sym+side
            if _already_open(ledger, sym, side):
                continue

            # Fetch next-bar open price (approximate as current price)
            cur_px = prices.get(sym)
            if cur_px is None or cur_px <= 0:
                continue

            # Simulate fill at next-bar open + slippage
            fill_px = _sim_fill_price(cur_px, side, tf)
            sl_abs  = abs(fill_px - sl)

            # Recalculate sl_pct from fill price
            sl_pct_fill = sl_abs / fill_px if fill_px > 0 else sl_pct
            if sl_pct_fill < (SL_PCT_MIN_5M if tf == "5m" else SL_PCT_MIN_15M):
                continue

            # Fixed-fraction sizing
            ok, risk_d, notional = ledger.can_admit(sym, sl_pct_fill, tf)
            if not ok:
                continue

            tp1, tp2 = _compute_tp_levels(fill_px, sl, side)
            fee_entry = notional * (FEE_RT_BPS / 2.0 / 10_000)

            trade_id = uuid.uuid4().hex[:20]
            pos = {
                "trade_id":       trade_id,
                "leg":            leg,
                "symbol":         sym,
                "tf":             tf,
                "strategy":       sig["strategy"],
                "side":           side,
                "entry_ts":       now_utc,
                "entry_bar_ts":   sig["bar_close_ts"],
                "entry_price":    fill_px,
                "sl_price":       sl,
                "tp1_price":      tp1,
                "tp2_price":      tp2,
                "sl_pct":         sl_pct_fill,
                "risk_dollars":   risk_d,
                "notional":       notional,
                "fee_entry_usdt": fee_entry,
                "confluence":     sig["confluence"],
                "htf_aligned":    sig.get("htf_aligned", -1.0),
                "status":         "open",
                "status_partial": "open",
                "unrealized_pnl": 0.0,
                "notes":          f"bar={tbc.strftime('%H:%M')}",
            }
            ledger.open_position(pos)
            new_positions.append(pos)
        return new_positions

    new_champion = _process_signals(champion_signals, champion_ledger, "champion")
    new_v13      = _process_signals(v13_signals_htf, v13_ledger, "v13")

    print(f"  new positions — champion:{len(new_champion)} v13:{len(new_v13)}")

    # Persist to DB
    con = duckdb.connect(str(DB_SIM))
    try:
        # Champion: write new entries and exits
        for pos in new_champion:
            _write_trade(con, "champion_sim", pos)
        for pos in champion_exits:
            _write_trade(con, "champion_sim", pos)

        # V13: write new entries and exits
        for pos in new_v13:
            _write_trade(con, "v13_sim", pos)
        for pos in v13_exits:
            _write_trade(con, "v13_sim", pos)

        # Equity snapshots
        n_champ_trades = _count_closed_trades(con, "champion_sim")
        n_v13_trades   = _count_closed_trades(con, "v13_sim")
        _write_equity_snap(con, "champion_sim", "champion", champion_ledger, now_utc, n_champ_trades)
        _write_equity_snap(con, "v13_sim",      "v13",      v13_ledger,      now_utc, n_v13_trades)
        con.commit()
    finally:
        con.close()

    return {
        "bar":           tbc.isoformat(),
        "new_champion":  len(new_champion),
        "new_v13":       len(new_v13),
        "exits_champion": len(champion_exits),
        "exits_v13":     len(v13_exits),
        "equity_champion": champion_ledger.equity(),
        "equity_v13":    v13_ledger.equity(),
    }


def _count_closed_trades(con: duckdb.DuckDBPyConnection, table: str) -> int:
    row = con.execute(f"SELECT COUNT(*) FROM {table} WHERE status != 'open'").fetchone()
    return int(row[0]) if row else 0


# ---------------------------------------------------------------------------
# Daily comparison report
# ---------------------------------------------------------------------------

def _load_equity_curve(table: str) -> pd.DataFrame:
    try:
        con = duckdb.connect(str(DB_SIM), read_only=True)
        df = con.execute(
            f"SELECT ts, equity, open_pnl, total_pnl, n_open, n_trades FROM {table}_equity ORDER BY ts"
        ).fetchdf()
        con.close()
        return df
    except Exception:
        return pd.DataFrame()


def _load_trades(table: str) -> pd.DataFrame:
    try:
        con = duckdb.connect(str(DB_SIM), read_only=True)
        df = con.execute(
            f"SELECT * FROM {table} WHERE status != 'open' ORDER BY exit_ts"
        ).fetchdf()
        con.close()
        return df
    except Exception:
        return pd.DataFrame()


def write_daily_report() -> str:
    """Generate daily comparison markdown and write to reports/forward_sim/daily.md."""
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    now_tr = datetime.now(UTC) + timedelta(hours=3)   # UTC+3 per memory rule

    champ_eq  = _load_equity_curve("champion_sim")
    v13_eq    = _load_equity_curve("v13_sim")
    champ_tr  = _load_trades("champion_sim")
    v13_tr    = _load_trades("v13_sim")

    def _curve_stats(eq_df: pd.DataFrame, tr_df: pd.DataFrame, label: str) -> dict:
        if eq_df.empty:
            return {"label": label, "equity": E0_FIXED, "ret_pct": 0.0, "dd_pct": 0.0,
                    "n_closed": 0, "win_pct": 0.0, "mean_r": 0.0}
        latest_eq = float(eq_df["equity"].iloc[-1])
        ret_pct   = (latest_eq - E0_FIXED) / E0_FIXED * 100.0

        # Drawdown on equity curve
        eq_arr = eq_df["equity"].to_numpy(dtype=float)
        peak   = np.maximum.accumulate(eq_arr)
        dd_arr = (eq_arr - peak) / peak * 100.0
        max_dd = float(dd_arr.min())

        if tr_df.empty:
            return {"label": label, "equity": latest_eq, "ret_pct": ret_pct,
                    "dd_pct": max_dd, "n_closed": 0, "win_pct": 0.0, "mean_r": 0.0}

        n_closed = len(tr_df)
        wins     = (tr_df["pnl_usdt"] > 0).sum()
        win_pct  = wins / n_closed * 100.0 if n_closed > 0 else 0.0
        mean_r   = float(tr_df["r_multiple"].mean()) if "r_multiple" in tr_df else 0.0

        return {"label": label, "equity": latest_eq, "ret_pct": ret_pct,
                "dd_pct": max_dd, "n_closed": n_closed, "win_pct": win_pct, "mean_r": mean_r}

    cs = _curve_stats(champ_eq, champ_tr, "CHAMPION (15m VSA-WIDESTOP)")
    vs = _curve_stats(v13_eq,   v13_tr,   "V13 (multi-TF + HTF-1d aligned)")

    # Daily P&L (last 7 days)
    def _daily_pnl_table(tr_df: pd.DataFrame) -> str:
        if tr_df.empty or "exit_ts" not in tr_df.columns:
            return "  No closed trades yet.\n"
        tr_df = tr_df.copy()
        tr_df["exit_ts"] = pd.to_datetime(tr_df["exit_ts"], utc=True)
        tr_df["date"] = tr_df["exit_ts"].dt.date
        daily = tr_df.groupby("date")["pnl_usdt"].sum().tail(7)
        rows = []
        for d, pnl in daily.items():
            rows.append(f"  {d}  {pnl:+.2f} USDT")
        return "\n".join(rows) + "\n" if rows else "  No data.\n"

    lines = [
        f"# Forward Sim Daily Comparison",
        f"",
        f"**Generated:** {now_tr.strftime('%Y-%m-%d %H:%M')} TR (UTC+3)",
        f"**Note:** This is a SIMULATION. Fills are modeled at next-bar open",
        f"with ~{FEE_RT_BPS:.0f} bps fee + {SLIP_BPS_15M:.0f}/{SLIP_BPS_5M:.0f} bps slippage",
        f"(15m/5m). Fixed-fraction sizing vs E0=${E0_FIXED:,.0f} (non-compounding).",
        f"NOT real testnet execution — comparison measures strategy logic only.",
        f"",
        f"---",
        f"",
        f"## Summary",
        f"",
        f"| Metric | {cs['label']} | {vs['label']} |",
        f"|--------|-------------|-----------|",
        f"| Equity | ${cs['equity']:,.2f} | ${vs['equity']:,.2f} |",
        f"| Cumulative Return | {cs['ret_pct']:+.2f}% | {vs['ret_pct']:+.2f}% |",
        f"| Max Drawdown | {cs['dd_pct']:+.2f}% | {vs['dd_pct']:+.2f}% |",
        f"| Closed Trades | {cs['n_closed']} | {vs['n_closed']} |",
        f"| Win Rate | {cs['win_pct']:.1f}% | {vs['win_pct']:.1f}% |",
        f"| Mean R | {cs['mean_r']:+.3f} | {vs['mean_r']:+.3f} |",
        f"",
        f"---",
        f"",
        f"## Champion — Last 7 Days PnL",
        f"",
        _daily_pnl_table(champ_tr),
        f"",
        f"## V13 — Last 7 Days PnL",
        f"",
        _daily_pnl_table(v13_tr),
        f"",
        f"---",
        f"",
        f"## Real Orders: NONE",
        f"Running champion daemons are UNTOUCHED.",
        f"V13 leg is pure simulation — no orders placed on any account.",
        f"",
    ]

    report_text = "\n".join(lines)
    REPORT_PATH.write_text(report_text, encoding="utf-8")
    print(f"[forward_sim] report written: {REPORT_PATH}")
    return report_text


# ---------------------------------------------------------------------------
# Bar boundary helpers
# ---------------------------------------------------------------------------

def _last_closed_15m_bar() -> datetime:
    """Returns the most recent fully-closed 15m bar boundary (UTC)."""
    now = datetime.now(UTC)
    total_min = int(now.timestamp() // 60)
    bar_floor_min = (total_min // 15) * 15
    return datetime.fromtimestamp(bar_floor_min * 60, tz=UTC)


def _next_15m_boundary_in(current_bar: datetime) -> float:
    """Seconds until the NEXT 15m bar close after current_bar."""
    next_bar = current_bar + timedelta(minutes=15)
    now      = datetime.now(UTC)
    return max(0.0, (next_bar - now).total_seconds())


# ---------------------------------------------------------------------------
# State persistence across restarts (last processed bar)
# ---------------------------------------------------------------------------

_STATE_FILE = ROOT / "data" / "state" / "forward_sim_last_bar.txt"


def _load_last_bar() -> datetime | None:
    try:
        if _STATE_FILE.exists():
            txt = _STATE_FILE.read_text().strip()
            if txt:
                return datetime.fromisoformat(txt).replace(tzinfo=UTC)
    except Exception:
        pass
    return None


def _save_last_bar(bar: datetime) -> None:
    try:
        _STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        _STATE_FILE.write_text(bar.isoformat())
    except Exception as exc:
        print(f"[forward_sim] state save fail: {exc}")


# ---------------------------------------------------------------------------
# Restore ledger state from DB on restart
# ---------------------------------------------------------------------------

def _restore_ledger(leg: str) -> FixedFractionLedger:
    """Re-hydrate open positions from DB into ledger on restart."""
    ledger = FixedFractionLedger(leg=leg)
    table  = f"{leg}_sim"
    try:
        con = duckdb.connect(str(DB_SIM), read_only=True)
        rows = con.execute(
            f"SELECT trade_id, symbol, tf, side, entry_ts, entry_price, sl_price, "
            f"tp1_price, tp2_price, initial_sl_pct, risk_dollars, notional_usdt, "
            f"strategy, fee_usdt, confluence, htf_aligned "
            f"FROM {table} WHERE status='open'"
        ).fetchdf()
        con.close()
        # Also load partial_tp1 positions
        con2 = duckdb.connect(str(DB_SIM), read_only=True)
        rows2 = con2.execute(
            f"SELECT trade_id, symbol, tf, side, entry_ts, entry_price, sl_price, "
            f"tp1_price, tp2_price, initial_sl_pct, risk_dollars, notional_usdt, "
            f"strategy, fee_usdt, confluence, htf_aligned "
            f"FROM {table} WHERE status='closed_tp1'"
        ).fetchdf()
        con2.close()

        for _, r in pd.concat([rows, rows2], ignore_index=True).iterrows():
            pos = {
                "trade_id":       r["trade_id"],
                "leg":            leg,
                "symbol":         r["symbol"],
                "tf":             r["tf"],
                "strategy":       r["strategy"],
                "side":           r["side"],
                "entry_ts":       r["entry_ts"],
                "entry_bar_ts":   None,
                "entry_price":    float(r["entry_price"]),
                "sl_price":       float(r["sl_price"]),
                "tp1_price":      float(r["tp1_price"]) if r["tp1_price"] else None,
                "tp2_price":      float(r["tp2_price"]) if r["tp2_price"] else None,
                "sl_pct":         float(r["initial_sl_pct"]) if r["initial_sl_pct"] else 0.025,
                "risk_dollars":   float(r["risk_dollars"]),
                "notional":       float(r["notional_usdt"]),
                "fee_entry_usdt": float(r["fee_usdt"]) / 2.0 if r["fee_usdt"] else 0.0,
                "confluence":     float(r["confluence"]) if r["confluence"] else 0.0,
                "htf_aligned":    float(r["htf_aligned"]) if r["htf_aligned"] else -1.0,
                "status":         "open",
                "status_partial": "partial_tp1" if "tp1" in str(r.get("status", "")) else "open",
                "unrealized_pnl": 0.0,
                "notes":          "restored",
            }
            ledger.open_position(pos)
        print(f"[forward_sim] restored {len(ledger._open)} open positions for {leg}")
    except Exception as exc:
        print(f"[forward_sim] ledger restore fail ({leg}): {exc}")
    return ledger


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------

def run_once() -> None:
    """Single tick — for testing."""
    init_db(DB_SIM)
    champion_ledger = _restore_ledger("champion")
    v13_ledger      = _restore_ledger("v13")
    bar = _last_closed_15m_bar()
    result = _run_tick(champion_ledger, v13_ledger, bar)
    print(f"\n[forward_sim] tick result: {result}")
    _save_last_bar(bar)
    write_daily_report()


def run_daemon() -> None:
    """Continuous daemon — processes every closed 15m bar."""
    print("[forward_sim] starting daemon mode")
    print(f"  DB: {DB_SIM}")
    print(f"  Fee: {FEE_RT_BPS} bps round-trip")
    print(f"  Sizing: FIXED-FRACTION {RISK_PCT*100:.1f}% of E0=${E0_FIXED:,.0f}")
    print(f"  NO real orders. Running daemons untouched.")

    init_db(DB_SIM)
    champion_ledger = _restore_ledger("champion")
    v13_ledger      = _restore_ledger("v13")
    last_processed  = _load_last_bar()
    report_counter  = 0

    while True:
        try:
            current_bar = _last_closed_15m_bar()

            if last_processed is None or current_bar > last_processed:
                result = _run_tick(champion_ledger, v13_ledger, current_bar)
                _save_last_bar(current_bar)
                last_processed = current_bar
                report_counter += 1

                # Write report every 96 bars (= 24h) or every 4 bars initially
                if report_counter % max(4, 96) == 0:
                    write_daily_report()

                # Print equity after each tick
                print(
                    f"  equity: champion=${champion_ledger.equity():.2f} "
                    f"({(champion_ledger.equity()-E0_FIXED)/E0_FIXED*100:+.2f}%)  "
                    f"v13=${v13_ledger.equity():.2f} "
                    f"({(v13_ledger.equity()-E0_FIXED)/E0_FIXED*100:+.2f}%)"
                )

            # Sleep until near next bar boundary
            wait_sec = _next_15m_boundary_in(current_bar)
            # Wake up 5s after bar close (same pattern as champion daemon)
            sleep_sec = max(5, wait_sec + 5)
            sleep_sec = min(sleep_sec, 60)   # never sleep > 60s (heartbeat)
            time.sleep(sleep_sec)

        except KeyboardInterrupt:
            print("\n[forward_sim] interrupted — writing final report")
            write_daily_report()
            break
        except Exception as exc:
            print(f"[forward_sim] tick error: {type(exc).__name__}: {exc}")
            time.sleep(30)


def main() -> None:
    parser = argparse.ArgumentParser(description="Forward paper-sim harness: champion vs v13")
    parser.add_argument("--once",   action="store_true", help="Run one tick and exit")
    parser.add_argument("--report", action="store_true", help="Print daily report and exit")
    args = parser.parse_args()

    if args.report:
        if DB_SIM.exists():
            print(write_daily_report())
        else:
            print(f"[forward_sim] no DB at {DB_SIM} — run at least one tick first")
        return

    if args.once:
        run_once()
    else:
        run_daemon()


if __name__ == "__main__":
    main()
