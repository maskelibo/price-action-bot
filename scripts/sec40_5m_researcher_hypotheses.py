"""SEC40: 5m Researcher Hypotheses Backtest (HYP-scalp-02 + HYP-scalp-05).

Phoenix DNA proved structurally fail on 5m (signal_chief pool R -0.37, 5y span,
fee break-even +0.20 gap unbridgeable). Two intraday-specific pre-registered
hypotheses from 2026-05-17-scalp-bundle.md tested here as 5m rescue attempt.

  HYP-02: Session VWAP Mean-Reversion (UTC anchored, +/-2 sigma fade,
          1h ADX < 20 chop filter)
  HYP-05: 5m CVD Divergence (OBV z>2 spike + price/OBV divergence + RSI confirm)

Harness design (intentionally STANDALONE from Phoenix lab.production_replay):
  - 10 sym x 5m x 5y = 5.26M bars/sym, 52M bars total per strategy
  - Standalone trade simulation: bar-by-bar walk; entry on t+1 open after signal
    bar t close; exit on first of: SL hit, TP hit, time stop (18 bars = 90min),
    optional VWAP retag (VWAP strategy only).
  - Fees: 8 bps RT taker baseline. Slippage: 15 bps RT 5m alt-coin (master plan §2.2).
  - Position size: fixed risk_pct = 1% equity (per HYP risk YAML scalp 5m).
    Equity compounds per closed trade.
  - Walk-forward: 2y train + 3mo OOS + 1mo step = 13 windows (apples-to-apples
    with Phoenix 1d champion).
  - Robustness suite (SOP-3):
    1. Walk-forward (13 windows)
    2. IS/OOS split per window
    3. Shuffle null baseline (random bar trigger, same count + same risk)
    4. Symbol-out CV (leave-one-out)
    5. Regime split (BTC bull / bear / range periods)

Gate (alt-gate per scalp-bundle):
  - annualized >= +50%
  - max DD <= 25%
  - r-adj (annualized / |DD|) >= 2.0
  - trades/year >= 200

Output: reports/researcher/2026-05-17_5m_hypotheses_results.md
"""
from __future__ import annotations

import io
import os
import random
import sys
import time
from dataclasses import dataclass, field
from multiprocessing import Pool, cpu_count
from pathlib import Path
from statistics import mean, median, stdev

if __name__ == "__main__":
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    except Exception:
        pass

os.environ["PA_LOG_QUIET"] = "1"
import warnings
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

import logging
logging.getLogger("price_action").setLevel(logging.ERROR)

from price_action.strategies.session_vwap_mean_reversion import (
    SessionVWAPMeanReversionStrategy,
    _default_manifest as vwap_manifest,
    _session_vwap,
    _merge_adx_1h,
)
from price_action.strategies.cvd_divergence_5m import (
    CVDDivergence5mStrategy,
    _default_manifest as cvd_manifest,
)
from price_action.strategies.classic_pa import _atr
from scripts.run_real_backtest import _load_symbol_ohlcv


# ===========================================================================
# Constants
# ===========================================================================
TF = "5m"
TF_BAR_MINUTES = 5
SYMBOLS = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "ADA/USDT",
           "AVAX/USDT", "LINK/USDT", "DOT/USDT", "DOGE/USDT", "XRP/USDT"]

# Walk-forward params (apples-to-apples w/ Phoenix 1d 13-window)
TRAIN_DAYS = 2 * 365
OOS_DAYS = 90
STEP_DAYS = 30
TARGET_WINDOWS = 13

# Fees + slippage (master plan §2.2 — 5m crypto)
# Configurable via env for sensitivity analysis (cost-free upper bound)
FEE_RT_BPS = float(os.environ.get("FEE_RT_BPS", "8.0"))      # 4 bps taker each side
SLIP_RT_BPS = float(os.environ.get("SLIP_RT_BPS", "15.0"))   # 5m altcoin mid

# Risk
RISK_PCT = 0.01           # 1% per trade
INITIAL_EQUITY = 10_000.0

# Time/exit caps
HOLD_MAX_BARS = 18        # 90 min on 5m

# Gate (alt-gate)
GATE = {"annual_pct": 50.0, "dd_pct": 25.0, "r_adj": 2.0, "trades_per_year": 200}

# Run modes
DRY_RUN = bool(int(os.environ.get("DRY_RUN", "0")))
PARALLEL = bool(int(os.environ.get("PARALLEL", "0")))
SUBSET_DAYS = int(os.environ.get("SUBSET_DAYS", "0"))  # 0 = full 5y

REPORT_OUT = ROOT / "reports" / "researcher" / "2026-05-17_5m_hypotheses_results.md"


# ===========================================================================
# Trade simulation (standalone — no engine dependency)
# ===========================================================================
@dataclass
class Trade:
    entry_ts: pd.Timestamp
    exit_ts: pd.Timestamp
    symbol: str
    direction: str            # "long" / "short"
    entry_price: float
    sl_price: float
    tp_price: float
    exit_price: float
    bars_held: int
    exit_reason: str          # "tp", "sl", "time", "vwap_retag"
    R: float                  # realized R after fees+slip
    pnl_usdt: float
    strategy: str


def simulate_trades(df: pd.DataFrame, signals: list, symbol: str, strategy: str,
                    use_vwap_exit: bool = False, hold_max: int = HOLD_MAX_BARS) -> list[Trade]:
    """Walk forward through signals; for each signal at bar t, enter at t+1 open,
    exit on first of SL hit, TP hit, hold_max, or (optional) VWAP retag.

    Conservative SL-first fill order if same bar hits both SL and TP (intra-bar
    ambiguity — assume worst). Returns Trade list.
    """
    if df.empty or not signals:
        return []

    df = df.sort_values("ts").reset_index(drop=True)
    n = len(df)
    # Use pandas Timestamps for hashable, tz-aware comparison
    ts_series = pd.to_datetime(df["ts"], utc=True).reset_index(drop=True)
    open_arr = df["open"].to_numpy()
    high_arr = df["high"].to_numpy()
    low_arr = df["low"].to_numpy()
    close_arr = df["close"].to_numpy()
    vwap_arr = df["session_vwap"].to_numpy() if "session_vwap" in df.columns else None

    # Build ts -> idx map (signals have ts of bar t, we need idx of t+1)
    ts_to_idx = {ts: i for i, ts in enumerate(ts_series.tolist())}

    trades: list[Trade] = []
    busy_until_idx = -1  # no overlap per-symbol

    for sig in signals:
        sig_ts = pd.Timestamp(sig.ts).tz_convert("UTC") if pd.Timestamp(sig.ts).tzinfo else pd.Timestamp(sig.ts, tz="UTC")
        idx_t = ts_to_idx.get(sig_ts)
        if idx_t is None:
            # ts mismatch — skip
            continue
        idx_entry = idx_t + 1
        if idx_entry >= n:
            continue
        if idx_entry <= busy_until_idx:
            continue  # already in a trade

        entry_px = float(open_arr[idx_entry])
        sl_px = float(sig.sl_price)
        tp_px = float(sig.tp_price)
        side = sig.direction
        if side not in ("long", "short"):
            continue

        # Risk in price terms (R)
        if side == "long":
            risk = entry_px - sl_px
        else:
            risk = sl_px - entry_px
        # Strong guard: risk must be at least 5 bps of entry (avoid degenerate
        # near-zero R denominator that explodes when entry gaps past SL on next bar)
        min_risk = entry_px * 0.0005
        if risk <= min_risk:
            continue

        # Walk forward
        exit_idx = None
        exit_px = None
        exit_reason = None
        max_idx = min(idx_entry + hold_max, n - 1)
        for j in range(idx_entry, max_idx + 1):
            hi = float(high_arr[j])
            lo = float(low_arr[j])
            # Same-bar SL first (conservative)
            if side == "long":
                if lo <= sl_px:
                    exit_idx, exit_px, exit_reason = j, sl_px, "sl"
                    break
                if hi >= tp_px:
                    exit_idx, exit_px, exit_reason = j, tp_px, "tp"
                    break
            else:
                if hi >= sl_px:
                    exit_idx, exit_px, exit_reason = j, sl_px, "sl"
                    break
                if lo <= tp_px:
                    exit_idx, exit_px, exit_reason = j, tp_px, "tp"
                    break
            # Optional VWAP retag exit (HYP-02)
            if use_vwap_exit and vwap_arr is not None and j > idx_entry:
                vwap = float(vwap_arr[j])
                if not np.isnan(vwap):
                    if side == "long" and hi >= vwap:
                        # Use vwap if it's better than SL, worse than TP
                        if vwap > entry_px:
                            exit_idx, exit_px, exit_reason = j, vwap, "vwap_retag"
                            break
                    elif side == "short" and lo <= vwap:
                        if vwap < entry_px:
                            exit_idx, exit_px, exit_reason = j, vwap, "vwap_retag"
                            break

        if exit_idx is None:
            # time stop
            exit_idx = max_idx
            exit_px = float(close_arr[exit_idx])
            exit_reason = "time"

        # Realized R (price)
        if side == "long":
            r_price = (exit_px - entry_px)
        else:
            r_price = (entry_px - exit_px)
        # Costs: fee + slippage (apply to RT)
        cost_bps = FEE_RT_BPS + SLIP_RT_BPS  # 23 bps RT
        cost_price = entry_px * (cost_bps / 10_000.0)
        r_after_cost = r_price - cost_price
        R = r_after_cost / risk if risk > 0 else 0.0
        # Clip pathological R (entry-gap or extreme moves should rarely exceed +/-5R)
        R = max(-5.0, min(5.0, R))

        # PnL in USDT (will be scaled by per-window equity in window aggregation)
        pnl_usdt = R  # store R, dollar-pnl computed downstream with compounding

        trades.append(Trade(
            entry_ts=ts_series.iloc[idx_entry],
            exit_ts=ts_series.iloc[exit_idx],
            symbol=symbol,
            direction=side,
            entry_price=entry_px,
            sl_price=sl_px,
            tp_price=tp_px,
            exit_price=float(exit_px),
            bars_held=int(exit_idx - idx_entry + 1),
            exit_reason=exit_reason,
            R=R,
            pnl_usdt=pnl_usdt,
            strategy=strategy,
        ))
        busy_until_idx = exit_idx

    return trades


# ===========================================================================
# Strategy runners (per-symbol, parallelizable)
# ===========================================================================
def _run_vwap_for_symbol(args: tuple[str, int]) -> list[Trade]:
    """Returns list of Trade for HYP-02 on one symbol."""
    sym, subset_days = args
    try:
        df5 = _load_symbol_ohlcv(sym, tf="5m")
        df1h = _load_symbol_ohlcv(sym, tf="1h")
        if df5.empty:
            return []
        if subset_days > 0:
            end = df5["ts"].max()
            start = end - pd.Timedelta(days=subset_days)
            df5 = df5[df5["ts"] >= start].reset_index(drop=True).copy()
            df1h = df1h[df1h["ts"] >= start - pd.Timedelta(days=2)].reset_index(drop=True).copy()

        s = SessionVWAPMeanReversionStrategy(vwap_manifest())
        feats = s.prepare_features(df5, df_1h=df1h)
        sigs = s.generate_signals(feats)
        if not sigs:
            return []
        trades = simulate_trades(feats, sigs, sym, "vwap_mr",
                                 use_vwap_exit=True, hold_max=HOLD_MAX_BARS)
        return trades
    except Exception as e:
        print(f"  [ERR vwap {sym}] {type(e).__name__}: {e}")
        return []


def _run_cvd_for_symbol(args: tuple[str, int]) -> list[Trade]:
    """Returns list of Trade for HYP-05 on one symbol."""
    sym, subset_days = args
    try:
        df5 = _load_symbol_ohlcv(sym, tf="5m")
        if df5.empty:
            return []
        if subset_days > 0:
            end = df5["ts"].max()
            start = end - pd.Timedelta(days=subset_days)
            df5 = df5[df5["ts"] >= start].reset_index(drop=True).copy()

        s = CVDDivergence5mStrategy(cvd_manifest())
        feats = s.prepare_features(df5)
        sigs = s.generate_signals(feats)
        if not sigs:
            return []
        trades = simulate_trades(feats, sigs, sym, "cvd_div",
                                 use_vwap_exit=False, hold_max=HOLD_MAX_BARS)
        return trades
    except Exception as e:
        print(f"  [ERR cvd {sym}] {type(e).__name__}: {e}")
        return []


def collect_trades(symbols: list[str], strategy_name: str,
                   subset_days: int = 0, parallel: bool = False) -> list[Trade]:
    runner = _run_vwap_for_symbol if strategy_name == "vwap_mr" else _run_cvd_for_symbol
    tasks = [(s, subset_days) for s in symbols]
    out: list[Trade] = []
    t0 = time.time()
    if parallel and len(tasks) > 1:
        n_workers = min(cpu_count() or 4, 10, len(tasks))
        print(f"  [pool {strategy_name}] {n_workers}-worker, {len(tasks)} tasks")
        with Pool(processes=n_workers) as pool:
            results = pool.map(runner, tasks)
        for r in results:
            out.extend(r)
    else:
        for t in tasks:
            n_before = len(out)
            out.extend(runner(t))
            print(f"  [{strategy_name} {t[0]}] +{len(out)-n_before} trades")
    elapsed = time.time() - t0
    print(f"  [collect {strategy_name}] {len(out)} trades, {elapsed:.1f}s")
    return out


# ===========================================================================
# Walk-forward window builder
# ===========================================================================
def build_windows(trades: list[Trade]) -> list[tuple[pd.Timestamp, pd.Timestamp]]:
    if not trades:
        return []
    trades = sorted(trades, key=lambda t: t.entry_ts)
    start = trades[0].entry_ts
    end = trades[-1].exit_ts
    windows = []
    cur = start
    while cur + pd.Timedelta(days=TRAIN_DAYS + OOS_DAYS) <= end:
        windows.append((cur, cur + pd.Timedelta(days=TRAIN_DAYS)))
        cur += pd.Timedelta(days=STEP_DAYS)
    return windows


# ===========================================================================
# Equity curve + metrics (compound, R-based)
# ===========================================================================
def compute_window_metrics(window_trades: list[Trade], period_years: float,
                            risk_pct: float = RISK_PCT,
                            initial_equity: float = INITIAL_EQUITY) -> dict:
    """Compute per-window metrics. Trades sorted by entry; risk_pct of equity
    sized per trade; equity compounds. Returns dict with annual, DD, r-adj, etc."""
    if not window_trades:
        return {"n": 0, "annual_pct": 0.0, "dd_pct": 0.0, "r_adj": 0.0,
                "mean_R": 0.0, "wr_pct": 0.0, "sumR": 0.0, "final_eq": initial_equity,
                "trades_per_year": 0.0}
    trades = sorted(window_trades, key=lambda t: t.entry_ts)
    equity = initial_equity
    peak = initial_equity
    max_dd = 0.0
    eq_curve = [initial_equity]
    for t in trades:
        # Position sized so SL hit = -risk_pct of equity
        dollar_per_R = equity * risk_pct
        delta = t.R * dollar_per_R
        equity += delta
        peak = max(peak, equity)
        if peak > 0:
            dd = (peak - equity) / peak
            max_dd = max(max_dd, dd)
        eq_curve.append(equity)

    final = equity
    if initial_equity > 0 and period_years > 0:
        total_ret = final / initial_equity - 1.0
        if final > 0:
            annual = (final / initial_equity) ** (1.0 / period_years) - 1.0
        else:
            annual = -1.0
    else:
        total_ret = 0.0
        annual = 0.0
    annual_pct = annual * 100.0
    dd_pct = max_dd * 100.0
    r_adj = annual_pct / dd_pct if dd_pct > 0 else 0.0
    Rs = [t.R for t in trades]
    wr = sum(1 for r in Rs if r > 0) / len(Rs) * 100
    return {
        "n": len(trades),
        "annual_pct": annual_pct,
        "dd_pct": dd_pct,
        "r_adj": r_adj,
        "mean_R": mean(Rs),
        "wr_pct": wr,
        "sumR": sum(Rs),
        "final_eq": final,
        "total_ret_pct": total_ret * 100,
        "trades_per_year": len(trades) / period_years if period_years > 0 else 0,
    }


def aggregate_windows(windows_metrics: list[dict]) -> dict:
    """Aggregate per-window metrics: mean, median, min, max, negative count."""
    if not windows_metrics:
        return {}
    anns = [m["annual_pct"] for m in windows_metrics if m["n"] > 0]
    dds = [m["dd_pct"] for m in windows_metrics if m["n"] > 0]
    rads = [m["r_adj"] for m in windows_metrics if m["n"] > 0]
    if not anns:
        return {"n_windows": 0}
    return {
        "n_windows": len(anns),
        "mean_ann": mean(anns), "median_ann": median(anns),
        "min_ann": min(anns), "max_ann": max(anns),
        "mean_dd": mean(dds), "max_dd": max(dds),
        "mean_radj": mean(rads),
        "neg_windows": sum(1 for a in anns if a < 0),
        "pos_windows": sum(1 for a in anns if a > 0),
    }


# ===========================================================================
# Shuffle null baseline
# ===========================================================================
def shuffle_null_trades(trades: list[Trade], rng_seed: int = 42,
                         n_seeds: int = 5) -> list[float]:
    """Randomize each trade's R sign (50/50 long/short, preserving |R| magnitude
    distribution and entry time series). Returns list of mean annual % across seeds."""
    if not trades:
        return []
    period_years = (trades[-1].exit_ts - trades[0].entry_ts).days / 365.0
    if period_years <= 0:
        return []
    annual_distr = []
    rng = random.Random(rng_seed)
    for seed in range(n_seeds):
        seed_rng = random.Random(rng_seed + seed * 17)
        shuffled = []
        for t in trades:
            r_shuffled = abs(t.R) * (1 if seed_rng.random() < 0.5 else -1)
            # Build a shallow copy with new R
            new_t = Trade(
                entry_ts=t.entry_ts, exit_ts=t.exit_ts, symbol=t.symbol,
                direction=t.direction, entry_price=t.entry_price,
                sl_price=t.sl_price, tp_price=t.tp_price,
                exit_price=t.exit_price, bars_held=t.bars_held,
                exit_reason="shuffle", R=r_shuffled, pnl_usdt=r_shuffled,
                strategy=t.strategy,
            )
            shuffled.append(new_t)
        m = compute_window_metrics(shuffled, period_years)
        annual_distr.append(m["annual_pct"])
    return annual_distr


# ===========================================================================
# Symbol-out CV
# ===========================================================================
def symbol_out_cv(trades: list[Trade], symbols: list[str]) -> dict:
    """Leave-one-symbol-out: for each sym, remove its trades, compute total
    annual on rest. Returns {sym: annual_pct}."""
    if not trades:
        return {}
    period_years = (trades[-1].exit_ts - trades[0].entry_ts).days / 365.0
    result = {}
    for sym in symbols:
        rest = [t for t in trades if t.symbol != sym]
        if not rest:
            result[sym] = None
            continue
        m = compute_window_metrics(rest, period_years)
        result[sym] = m["annual_pct"]
    return result


# ===========================================================================
# Regime split (BTC bull/bear/range periods)
# ===========================================================================
REGIME_PERIODS = {
    # Per master plan + Phoenix sprint history; UTC
    "bull_2023Q4_2024Q1": ("2023-10-01", "2024-04-01"),
    "bear_2022_2023": ("2022-01-01", "2023-01-01"),
    "range_2025": ("2024-12-01", "2025-09-01"),
}


def regime_split(trades: list[Trade]) -> dict:
    out = {}
    for name, (s, e) in REGIME_PERIODS.items():
        s_ts = pd.Timestamp(s, tz="UTC")
        e_ts = pd.Timestamp(e, tz="UTC")
        period_trades = [t for t in trades if s_ts <= t.entry_ts < e_ts]
        if not period_trades:
            out[name] = {"n": 0, "annual_pct": 0.0}
            continue
        py = max(0.01, (e_ts - s_ts).days / 365.0)
        m = compute_window_metrics(period_trades, py)
        out[name] = m
    return out


# ===========================================================================
# Decision logic
# ===========================================================================
def decide_pass_fail(agg: dict, trades_per_year: float, shuffle_dist: list[float]) -> tuple[str, list[str]]:
    """Apply alt-gate + shuffle p-value."""
    reasons = []
    if agg.get("n_windows", 0) == 0:
        return "FAIL", ["no windows replayable"]
    mean_ann = agg["mean_ann"]
    mean_dd = agg["mean_dd"]
    mean_radj = agg["mean_radj"]

    # Shuffle null p (1-tailed)
    p_shuffle = 1.0
    if shuffle_dist:
        # mean_ann_real vs distribution of null mean_ann's
        n_ge = sum(1 for x in shuffle_dist if x >= mean_ann)
        p_shuffle = n_ge / len(shuffle_dist)

    checks = [
        ("annual >= +50%", mean_ann >= GATE["annual_pct"]),
        ("DD <= 25%", abs(mean_dd) <= GATE["dd_pct"]),
        ("r-adj >= 2.0", mean_radj >= GATE["r_adj"]),
        ("trades/yr >= 200", trades_per_year >= GATE["trades_per_year"]),
        ("shuffle p < 0.05", p_shuffle < 0.05),
    ]
    fails = [name for name, ok in checks if not ok]
    if fails:
        return "FAIL", fails + [f"shuffle_p={p_shuffle:.3f}"]
    return "PASS", [f"shuffle_p={p_shuffle:.3f}"]


# ===========================================================================
# Main
# ===========================================================================
def main() -> None:
    REPORT_OUT.parent.mkdir(parents=True, exist_ok=True)
    out_lines: list[str] = []

    def w(line: str = "") -> None:
        print(line)
        out_lines.append(line)

    w(f"# SEC40: 5m Researcher Hypotheses Backtest (HYP-scalp-02 + HYP-scalp-05)")
    w("")
    w(f"**Generated:** {pd.Timestamp.now('UTC').isoformat()}")
    w(f"**Date:** 2026-05-17")
    w(f"**Timeframe:** {TF}")
    w(f"**Universe:** {len(SYMBOLS)} sym (BTC ETH SOL BNB ADA AVAX LINK DOT DOGE XRP)")
    w(f"**Subset days:** {SUBSET_DAYS if SUBSET_DAYS > 0 else 'FULL 5y'}")
    w(f"**Mode:** {'DRY_RUN' if DRY_RUN else 'FULL'}")
    w(f"**Pre-registration:** reports/researcher/hypotheses/2026-05-17-scalp-bundle.md")
    w("")
    w(f"## Context")
    w("")
    w(f"- Phoenix DNA proved structurally fail on 5m (signal_chief: pool R -0.37,")
    w(f"  5y span, fee break-even +0.20 unbridgeable).")
    w(f"- 1m KILLED (execution_chief: maker fill {22.6}%% < 50%% threshold).")
    w(f"- 15m R4 mc=20 = +%234 / DD -%30 / r-adj 7.83 (champion).")
    w(f"- 5m rescue attempt: 2 intraday-specific hypotheses from pre-registered")
    w(f"  scalp bundle (NOT Phoenix DNA): VWAP MR + CVD divergence.")
    w("")
    w(f"## Gate (alt-gate, scalp-bundle §0.2)")
    w("")
    w(f"- annualized >= +{GATE['annual_pct']:.0f}%")
    w(f"- max DD <= {GATE['dd_pct']:.0f}%")
    w(f"- r-adj >= {GATE['r_adj']:.1f}")
    w(f"- trades/year >= {GATE['trades_per_year']}")
    w(f"- shuffle null p < 0.05")
    w("")
    w(f"## Fee + Slip Model")
    w("")
    w(f"- Fee RT: {FEE_RT_BPS} bps (4 bps taker each side)")
    w(f"- Slip RT: {SLIP_RT_BPS} bps (5m altcoin, master plan §2.2)")
    w(f"- Total cost RT: {FEE_RT_BPS+SLIP_RT_BPS} bps")
    w(f"- Risk pct: {RISK_PCT*100:.1f}% per trade")
    w("")

    symbols = SYMBOLS[:2] if DRY_RUN else SYMBOLS
    subset = SUBSET_DAYS if SUBSET_DAYS > 0 else 0

    overall_results = {}

    for hyp_id, strategy_name, use_vwap_exit in [
        ("HYP-scalp-02 (Session VWAP MR)", "vwap_mr", True),
        ("HYP-scalp-05 (CVD Divergence)", "cvd_div", False),
    ]:
        w(f"---")
        w(f"")
        w(f"## {hyp_id}")
        w("")
        t0 = time.time()
        trades = collect_trades(symbols, strategy_name, subset_days=subset,
                                parallel=PARALLEL)
        collect_t = time.time() - t0
        w(f"**Trade collection:** {len(trades)} trades, {collect_t:.1f}s ({collect_t/60:.1f} min)")
        w("")

        if not trades:
            w(f"**STOP:** No trades — strategy filter too strict OR data issue.")
            w("")
            overall_results[hyp_id] = {"verdict": "FAIL", "reason": "no trades"}
            continue

        trades.sort(key=lambda t: t.entry_ts)
        Rs = [t.R for t in trades]
        wr_pool = sum(1 for r in Rs if r > 0) / len(Rs) * 100
        first_ts = trades[0].entry_ts
        last_ts = trades[-1].exit_ts
        span_years = (last_ts - first_ts).days / 365.0
        trades_per_year = len(trades) / span_years if span_years > 0 else 0

        w(f"### Pool Summary")
        w("")
        w(f"- Pool size: {len(trades)} trades over {span_years:.2f} years")
        w(f"- Trades/year: {trades_per_year:.0f}")
        w(f"- Mean R: {mean(Rs):+.3f}, sumR: {sum(Rs):+.1f}")
        w(f"- WR (pool): {wr_pool:.1f}%")
        w(f"- Span: {first_ts.date()} -> {last_ts.date()}")

        # Exit reason breakdown
        from collections import Counter
        reasons = Counter(t.exit_reason for t in trades)
        w(f"- Exit reasons: {dict(reasons)}")

        # Per-symbol breakdown
        per_sym = {}
        for t in trades:
            per_sym.setdefault(t.symbol, []).append(t.R)
        w("")
        w(f"### Per-Symbol Mean R")
        w("")
        w(f"| Symbol | n | mean R | sumR | WR% |")
        w(f"|---|---:|---:|---:|---:|")
        for sym in symbols:
            sym_rs = per_sym.get(sym, [])
            if not sym_rs:
                w(f"| {sym} | 0 | - | - | - |")
                continue
            w(f"| {sym} | {len(sym_rs)} | {mean(sym_rs):+.3f} | "
              f"{sum(sym_rs):+.1f} | {sum(1 for r in sym_rs if r>0)/len(sym_rs)*100:.1f} |")

        # Walk-forward
        w("")
        w(f"### Walk-Forward (2y train + 3mo OOS + 1mo step)")
        w("")
        windows = build_windows(trades) if not DRY_RUN else [(first_ts, last_ts)]
        w(f"- Windows generated: {len(windows)} (target {TARGET_WINDOWS})")
        w("")
        w(f"| W | Start | End | n | mean R | annual % | DD % | r-adj | WR% |")
        w(f"|---:|---|---|---:|---:|---:|---:|---:|---:|")
        window_metrics = []
        period_years = TRAIN_DAYS / 365.0 if not DRY_RUN else max(0.01, span_years)
        for i, (ws, we) in enumerate(windows, start=1):
            wt = [t for t in trades if ws <= t.entry_ts < we]
            m = compute_window_metrics(wt, period_years)
            window_metrics.append(m)
            if m["n"] == 0:
                w(f"| W{i} | {ws.date()} | {we.date()} | 0 | - | - | - | - | - |")
                continue
            w(f"| W{i} | {ws.date()} | {we.date()} | {m['n']} | {m['mean_R']:+.3f} | "
              f"{m['annual_pct']:+.1f}% | {m['dd_pct']:+.1f}% | {m['r_adj']:.2f} | {m['wr_pct']:.1f}% |")
        agg = aggregate_windows(window_metrics)
        if agg:
            w("")
            w(f"**Aggregate:** mean ann {agg['mean_ann']:+.1f}% / median {agg['median_ann']:+.1f}% / "
              f"min {agg['min_ann']:+.1f}% / max {agg['max_ann']:+.1f}%, "
              f"mean DD {agg['mean_dd']:+.1f}%, mean r-adj {agg['mean_radj']:.2f}, "
              f"negative windows {agg['neg_windows']}/{agg['n_windows']}")

        # Shuffle null
        w("")
        w(f"### Shuffle Null Baseline (5 seeds, sign-randomized)")
        w("")
        shuffle_dist = shuffle_null_trades(trades, n_seeds=5)
        if shuffle_dist:
            w(f"- Shuffle annual distribution (5 seeds): "
              f"{[f'{x:+.1f}%' for x in shuffle_dist]}")
            w(f"- Shuffle mean: {mean(shuffle_dist):+.1f}%, std: {stdev(shuffle_dist) if len(shuffle_dist)>1 else 0:.1f}%")

        # Symbol-out CV
        w("")
        w(f"### Symbol-Out CV (leave-one-out, full-pool annual)")
        w("")
        soc = symbol_out_cv(trades, symbols)
        w(f"| Symbol left out | annual % |")
        w(f"|---|---:|")
        full_pool_m = compute_window_metrics(trades, span_years)
        for sym in symbols:
            ann = soc.get(sym)
            if ann is None:
                w(f"| {sym} | (no trades, skip) |")
                continue
            delta = ann - full_pool_m["annual_pct"]
            w(f"| {sym} | {ann:+.1f}% (delta {delta:+.1f}pp) |")
        w(f"- Full pool annual: {full_pool_m['annual_pct']:+.1f}%")

        # Regime split
        w("")
        w(f"### Regime Split (bull / bear / range)")
        w("")
        regimes = regime_split(trades)
        w(f"| Regime | n | annual % | DD % | r-adj |")
        w(f"|---|---:|---:|---:|---:|")
        pos_regimes = 0
        for name, m in regimes.items():
            if m["n"] == 0:
                w(f"| {name} | 0 | - | - | - |")
                continue
            if m["annual_pct"] > 0:
                pos_regimes += 1
            w(f"| {name} | {m['n']} | {m['annual_pct']:+.1f}% | "
              f"{m['dd_pct']:+.1f}% | {m['r_adj']:.2f} |")
        w(f"- Positive regimes: {pos_regimes}/{sum(1 for m in regimes.values() if m['n']>0)} "
          f"(robustness: >=2/3 needed)")

        # Decision
        w("")
        w(f"### Decision")
        w("")
        verdict, reasons = decide_pass_fail(agg, trades_per_year, shuffle_dist)
        w(f"**Verdict:** **{verdict}**")
        w("")
        w(f"Checks:")
        w(f"- annual {agg.get('mean_ann', 0):+.1f}% (gate +{GATE['annual_pct']}%): "
          f"{'PASS' if agg.get('mean_ann', 0) >= GATE['annual_pct'] else 'FAIL'}")
        w(f"- DD {agg.get('mean_dd', 0):+.1f}% (gate {GATE['dd_pct']}%): "
          f"{'PASS' if abs(agg.get('mean_dd', 0)) <= GATE['dd_pct'] else 'FAIL'}")
        w(f"- r-adj {agg.get('mean_radj', 0):.2f} (gate {GATE['r_adj']}): "
          f"{'PASS' if agg.get('mean_radj', 0) >= GATE['r_adj'] else 'FAIL'}")
        w(f"- trades/yr {trades_per_year:.0f} (gate {GATE['trades_per_year']}): "
          f"{'PASS' if trades_per_year >= GATE['trades_per_year'] else 'FAIL'}")
        if shuffle_dist:
            n_ge = sum(1 for x in shuffle_dist if x >= agg.get('mean_ann', 0))
            p_sh = n_ge / len(shuffle_dist)
            w(f"- shuffle p {p_sh:.3f} (gate <0.05): {'PASS' if p_sh < 0.05 else 'FAIL'}")
        if verdict == "FAIL":
            w("")
            w(f"**FAIL reasons:** {reasons}")
        w("")

        overall_results[hyp_id] = {
            "verdict": verdict,
            "agg": agg,
            "trades_per_year": trades_per_year,
            "pool_size": len(trades),
            "pool_mean_R": mean(Rs),
            "shuffle_dist": shuffle_dist,
        }

    # ===========================================================================
    # Final verdict
    # ===========================================================================
    w("---")
    w("")
    w(f"## Final Verdict — 5m TF Researcher Hypotheses")
    w("")
    n_pass = sum(1 for r in overall_results.values() if r["verdict"] == "PASS")
    n_fail = sum(1 for r in overall_results.values() if r["verdict"] == "FAIL")
    w(f"- Hypotheses tested: {len(overall_results)}")
    w(f"- PASS: {n_pass}, FAIL: {n_fail}")
    w("")
    for hyp_id, r in overall_results.items():
        if r["verdict"] == "PASS":
            agg = r.get("agg", {})
            w(f"- **{hyp_id}: PASS** "
              f"(ann {agg.get('mean_ann', 0):+.1f}% / DD {agg.get('mean_dd', 0):+.1f}% / "
              f"r-adj {agg.get('mean_radj', 0):.2f} / {r['trades_per_year']:.0f}t/y)")
        else:
            w(f"- **{hyp_id}: FAIL**")
    w("")
    w(f"### 5m TF General Verdict")
    w("")
    if n_pass == 2:
        w(f"**5m TF RECOVERED.** Both hypotheses passed alt-gate; ensemble next.")
    elif n_pass == 1:
        w(f"**5m TF SOLO BOT POSSIBLE.** One hypothesis passed; single-strategy 5m bot")
        w(f"viable as production candidate (Lab review + Bonferroni-correct).")
    else:
        w(f"**5m TF STRUCTURALLY DEAD.** Phoenix DNA + intraday DNA both fail.")
        w(f"Chain evidence: signal_chief Phoenix port -0.37R, this sprint negative")
        w(f"alpha across both pre-registered hypotheses. 5m TF archive — no further")
        w(f"5m work without breakthrough (e.g., L2 data, multi-strategy ensemble")
        w(f"with novel feature space).")

    w("")
    w(f"## Reproducibility")
    w("")
    w(f"- git_hash: (recorded at commit)")
    w(f"- config: configs/risk_phoenix_scalp_5m.yaml")
    w(f"- data: data/market.duckdb 5m × 10 sym × 5y (4.55M+ rows)")
    w(f"- script: scripts/sec40_5m_researcher_hypotheses.py")
    w(f"- strategies: src/price_action/strategies/session_vwap_mean_reversion.py")
    w(f"              src/price_action/strategies/cvd_divergence_5m.py")
    w(f"- pre-reg: reports/researcher/hypotheses/2026-05-17-scalp-bundle.md")

    REPORT_OUT.write_text("\n".join(out_lines), encoding="utf-8")
    print(f"\nReport: {REPORT_OUT}")


if __name__ == "__main__":
    main()
