"""SEC47: S3 Bidirectional Shorts Standalone Backtest.

PHOENIX-SCALP v2.1 / D5-sec49 / 2026-05-17.

Test 2 dedicated short-only stratejisi:
  - HYP-S3-A: VSABuyingClimaxStrategy (BC + immediate distribution test)
  - HYP-S3-B: BrooksFailedHighStrategy (failed-approach reversal)

Standalone harness — sec40 patternine paralel:
  - 10 sym x 5m x 5y data
  - per-symbol trade collection (signals -> simulate -> R)
  - per-year breakdown (5 buckets: 2021-05/2022-05 ... 2025-05/2026-05)
  - shuffle null baseline (random ts permute, 50 iter)
  - gate kontrol: standalone mean R >= +0.10, shuffle p < 0.025

Output: reports/researcher/2026-05-17_s3_bidirectional_shorts_results.md

Compute: 2 strat x 10 sym x 5m x 5y. Serial ~10-20 min.
"""
from __future__ import annotations

import io
import os
import random
import sys
import time
from dataclasses import dataclass
from datetime import timezone
from multiprocessing import Pool, cpu_count
from pathlib import Path
from statistics import mean, median

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

from price_action.strategies.vsa_buying_climax import (
    VSABuyingClimaxStrategy,
    _default_manifest as vsa_bc_manifest,
)
from price_action.strategies.brooks_failed_high import (
    BrooksFailedHighStrategy,
    _default_manifest as brooks_fh_manifest,
)
from scripts.run_real_backtest import _load_symbol_ohlcv


# =============================================================================
# Constants
# =============================================================================
TF = "5m"
SYMBOLS = [
    "BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "ADA/USDT",
    "AVAX/USDT", "LINK/USDT", "DOT/USDT", "DOGE/USDT", "XRP/USDT",
]

# Fee + slip model (master plan §2.2; sec40 paritesi)
FEE_RT_BPS = float(os.environ.get("FEE_RT_BPS", "8.0"))
SLIP_RT_BPS = float(os.environ.get("SLIP_RT_BPS", "15.0"))

# Risk + exit
RISK_PCT = 0.01
INITIAL_EQUITY = 10_000.0
HOLD_MAX_BARS = 18  # 90 min (5m bar)

# Gate (pre-reg S3 bundle)
GATE_MEAN_R = float(os.environ.get("GATE_MEAN_R", "0.10"))
GATE_SHUFFLE_P = float(os.environ.get("GATE_SHUFFLE_P", "0.025"))  # Bonferroni 2-test

# Shuffle null iterations
SHUFFLE_ITERS = int(os.environ.get("SHUFFLE_ITERS", "50"))

# Run modes
DRY_RUN = bool(int(os.environ.get("DRY_RUN", "0")))
PARALLEL = bool(int(os.environ.get("PARALLEL", "0")))
SUBSET_DAYS = int(os.environ.get("SUBSET_DAYS", "0"))  # 0 = full 5y

REPORT_OUT = (
    ROOT / "reports" / "researcher" /
    "2026-05-17_s3_bidirectional_shorts_results.md"
)


# =============================================================================
# Trade simulation (sec40 pattern, short-only consciousness)
# =============================================================================
@dataclass
class Trade:
    entry_ts: pd.Timestamp
    exit_ts: pd.Timestamp
    symbol: str
    direction: str
    entry_price: float
    sl_price: float
    tp_price: float
    exit_price: float
    bars_held: int
    exit_reason: str
    R: float
    strategy: str


def simulate_trades(
    df: pd.DataFrame,
    signals: list,
    symbol: str,
    strategy: str,
    hold_max: int = HOLD_MAX_BARS,
) -> list[Trade]:
    if df.empty or not signals:
        return []

    df = df.sort_values("ts").reset_index(drop=True)
    n = len(df)
    ts_series = pd.to_datetime(df["ts"], utc=True).reset_index(drop=True)
    open_arr = df["open"].to_numpy()
    high_arr = df["high"].to_numpy()
    low_arr = df["low"].to_numpy()
    close_arr = df["close"].to_numpy()

    ts_to_idx = {ts: i for i, ts in enumerate(ts_series.tolist())}

    trades: list[Trade] = []
    busy_until_idx = -1

    for sig in signals:
        sig_ts = (
            pd.Timestamp(sig.ts).tz_convert("UTC")
            if pd.Timestamp(sig.ts).tzinfo
            else pd.Timestamp(sig.ts, tz="UTC")
        )
        idx_t = ts_to_idx.get(sig_ts)
        if idx_t is None:
            continue
        idx_entry = idx_t + 1
        if idx_entry >= n:
            continue
        if idx_entry <= busy_until_idx:
            continue

        entry_px = float(open_arr[idx_entry])
        sl_px = float(sig.sl_price)
        tp_px = float(sig.tp_price)
        side = sig.direction
        if side not in ("long", "short"):
            continue

        if side == "long":
            risk = entry_px - sl_px
        else:
            risk = sl_px - entry_px
        min_risk = entry_px * 0.0005
        if risk <= min_risk:
            continue

        exit_idx = None
        exit_px = None
        exit_reason = None
        max_idx = min(idx_entry + hold_max, n - 1)
        for j in range(idx_entry, max_idx + 1):
            hi = float(high_arr[j])
            lo = float(low_arr[j])
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

        if exit_idx is None:
            exit_idx = max_idx
            exit_px = float(close_arr[exit_idx])
            exit_reason = "time"

        if side == "long":
            r_price = exit_px - entry_px
        else:
            r_price = entry_px - exit_px
        cost_bps = FEE_RT_BPS + SLIP_RT_BPS
        cost_price = entry_px * (cost_bps / 10_000.0)
        r_after_cost = r_price - cost_price
        R = r_after_cost / risk if risk > 0 else 0.0
        R = max(-5.0, min(5.0, R))

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
            strategy=strategy,
        ))
        busy_until_idx = exit_idx

    return trades


# =============================================================================
# Per-symbol strategy runner
# =============================================================================
def _run_strategy_for_symbol(args: tuple[str, str, int]) -> list[Trade]:
    """Run one strategy on one symbol. Returns Trade list."""
    sym, strategy_name, subset_days = args
    try:
        df = _load_symbol_ohlcv(sym, tf=TF)
        if df is None or df.empty:
            return []
        df = df.sort_values("ts").reset_index(drop=True).copy()
        df["symbol"] = sym
        df["venue"] = "binance"
        df["timeframe"] = TF

        if subset_days > 0:
            end = df["ts"].max()
            start = end - pd.Timedelta(days=subset_days)
            df = df[df["ts"] >= start].reset_index(drop=True).copy()

        if strategy_name == "vsa_buying_climax":
            s = VSABuyingClimaxStrategy(vsa_bc_manifest())
        elif strategy_name == "brooks_failed_high":
            s = BrooksFailedHighStrategy(brooks_fh_manifest())
        else:
            return []

        feats = s.prepare_features(df)
        sigs = s.generate_signals(feats)
        if not sigs:
            return []
        trades = simulate_trades(feats, sigs, sym, strategy_name,
                                 hold_max=HOLD_MAX_BARS)
        return trades
    except Exception as e:
        print(f"  [ERR {strategy_name}/{sym}] {type(e).__name__}: {e}")
        return []


def collect_trades(
    symbols: list[str],
    strategy_name: str,
    subset_days: int = 0,
    parallel: bool = False,
) -> list[Trade]:
    tasks = [(s, strategy_name, subset_days) for s in symbols]
    out: list[Trade] = []
    t0 = time.time()
    if parallel and len(tasks) > 1:
        n_workers = min(cpu_count() or 4, 10, len(tasks))
        print(f"  [pool {strategy_name}] {n_workers}-worker, {len(tasks)} tasks")
        with Pool(processes=n_workers) as pool:
            results = pool.map(_run_strategy_for_symbol, tasks)
        for r in results:
            out.extend(r)
    else:
        for t in tasks:
            n_before = len(out)
            out.extend(_run_strategy_for_symbol(t))
            print(f"  [{strategy_name} {t[0]}] +{len(out)-n_before} trades")
    elapsed = time.time() - t0
    print(f"  [collect {strategy_name}] {len(out)} trades, {elapsed:.1f}s ({elapsed/60:.1f} min)")
    return out


# =============================================================================
# Year buckets + per-year stats
# =============================================================================
def _to_utc(ts):
    return ts.replace(tzinfo=timezone.utc) if ts.tzinfo is None else ts.astimezone(timezone.utc)


def per_year_breakdown(trades: list[Trade]) -> list[dict]:
    if not trades:
        return []
    trades = sorted(trades, key=lambda t: t.entry_ts)
    start = _to_utc(trades[0].entry_ts.to_pydatetime())
    end = _to_utc(trades[-1].entry_ts.to_pydatetime())
    out = []
    cur = start
    while cur < end:
        nxt = cur + pd.Timedelta(days=365)
        bucket = [t for t in trades if cur <= _to_utc(t.entry_ts.to_pydatetime()) < nxt]
        if bucket:
            Rs = [t.R for t in bucket]
            longs = [t for t in bucket if t.direction == "long"]
            shorts = [t for t in bucket if t.direction == "short"]
            out.append({
                "start": cur.date().isoformat(),
                "end": nxt.date().isoformat(),
                "n": len(bucket),
                "n_long": len(longs),
                "n_short": len(shorts),
                "mean_R": sum(Rs) / len(Rs),
                "sumR": sum(Rs),
                "wr_pct": sum(1 for r in Rs if r > 0) / len(Rs) * 100,
                "mean_R_long": (
                    sum(t.R for t in longs) / len(longs) if longs else 0.0
                ),
                "mean_R_short": (
                    sum(t.R for t in shorts) / len(shorts) if shorts else 0.0
                ),
            })
        cur = nxt
    return out


# =============================================================================
# Shuffle null baseline
# =============================================================================
def _simulate_shuffled(
    df: pd.DataFrame,
    n_sigs: int,
    side: str,
    sl_atr_mult: float,
    tp_R: float,
    hold_max: int,
    rng: random.Random,
) -> list[float]:
    """Shuffle null: pick n_sigs random bars on df, build same-side trades
    with ATR-based SL and R-multiple TP, simulate, return list of R."""
    if df.empty or n_sigs <= 0:
        return []
    n = len(df)
    # 60 bar warmup
    valid_idx = list(range(60, n - hold_max - 1))
    if len(valid_idx) < n_sigs:
        n_sigs = len(valid_idx)
    if n_sigs <= 0:
        return []

    sample_idx = rng.sample(valid_idx, n_sigs)
    sample_idx.sort()

    # ATR(14) for SL sizing
    high = df["high"].to_numpy()
    low = df["low"].to_numpy()
    close = df["close"].to_numpy()
    open_ = df["open"].to_numpy()
    prev_close = np.concatenate([[close[0]], close[:-1]])
    tr = np.maximum(
        high - low,
        np.maximum(
            np.abs(high - prev_close),
            np.abs(low - prev_close),
        ),
    )
    atr14 = pd.Series(tr).rolling(14, min_periods=14).mean().to_numpy()

    Rs: list[float] = []
    for idx_t in sample_idx:
        idx_entry = idx_t + 1
        if idx_entry >= n:
            continue
        atr = float(atr14[idx_t])
        if np.isnan(atr) or atr <= 0:
            continue
        entry_px = float(open_[idx_entry])
        if side == "short":
            sl_px = entry_px + sl_atr_mult * atr
            risk = sl_px - entry_px
            tp_px = entry_px - tp_R * risk
        else:
            sl_px = entry_px - sl_atr_mult * atr
            risk = entry_px - sl_px
            tp_px = entry_px + tp_R * risk

        if risk <= entry_px * 0.0005:
            continue

        exit_idx = None
        exit_px = None
        max_idx = min(idx_entry + hold_max, n - 1)
        for j in range(idx_entry, max_idx + 1):
            hi = float(high[j])
            lo = float(low[j])
            if side == "short":
                if hi >= sl_px:
                    exit_idx, exit_px = j, sl_px
                    break
                if lo <= tp_px:
                    exit_idx, exit_px = j, tp_px
                    break
            else:
                if lo <= sl_px:
                    exit_idx, exit_px = j, sl_px
                    break
                if hi >= tp_px:
                    exit_idx, exit_px = j, tp_px
                    break
        if exit_idx is None:
            exit_idx = max_idx
            exit_px = float(close[exit_idx])

        if side == "short":
            r_price = entry_px - exit_px
        else:
            r_price = exit_px - entry_px
        cost_price = entry_px * ((FEE_RT_BPS + SLIP_RT_BPS) / 10_000.0)
        R = (r_price - cost_price) / risk
        R = max(-5.0, min(5.0, R))
        Rs.append(R)
    return Rs


def shuffle_null_p_value(
    real_mean_R: float,
    n_real: int,
    side: str,
    sl_atr_mult: float,
    tp_R: float,
    symbols: list[str],
    iters: int = SHUFFLE_ITERS,
    seed: int = 42,
) -> tuple[float, float, float]:
    """Returns (p_value, mean_of_null_means, std_of_null_means).

    p_value = (n_null_mean >= real_mean_R) / iters  (one-sided right)
    """
    rng = random.Random(seed)
    null_means: list[float] = []
    # Distribute n_real among symbols proportional to data length (approx equal)
    per_sym = max(1, n_real // len(symbols))

    # Pre-load dfs (small overhead)
    dfs: dict[str, pd.DataFrame] = {}
    for sym in symbols:
        try:
            d = _load_symbol_ohlcv(sym, tf=TF)
            if d is not None and not d.empty:
                dfs[sym] = d.sort_values("ts").reset_index(drop=True).copy()
        except Exception:
            continue

    for it in range(iters):
        iter_Rs: list[float] = []
        for sym in symbols:
            if sym not in dfs:
                continue
            iter_Rs.extend(_simulate_shuffled(
                dfs[sym], per_sym, side, sl_atr_mult, tp_R, HOLD_MAX_BARS, rng,
            ))
        if iter_Rs:
            null_means.append(sum(iter_Rs) / len(iter_Rs))

    if not null_means:
        return 1.0, 0.0, 0.0

    null_mean = sum(null_means) / len(null_means)
    null_std = (
        (sum((x - null_mean) ** 2 for x in null_means) / len(null_means)) ** 0.5
        if len(null_means) > 1 else 0.0
    )
    p = sum(1 for m in null_means if m >= real_mean_R) / len(null_means)
    return p, null_mean, null_std


# =============================================================================
# Main
# =============================================================================
def main() -> None:
    REPORT_OUT.parent.mkdir(parents=True, exist_ok=True)
    out_lines: list[str] = []

    def w(line: str = "") -> None:
        print(line)
        out_lines.append(line)

    w(f"# SEC47: S3 Bidirectional Shorts Standalone Backtest")
    w("")
    w(f"**Generated:** {pd.Timestamp.now(tz='UTC').isoformat()}")
    w(f"**TF:** {TF}")
    w(f"**Universe:** {len(SYMBOLS)} sym ({', '.join(s.split('/')[0] for s in SYMBOLS)})")
    w(f"**Span:** {'SUBSET '+str(SUBSET_DAYS)+'d' if SUBSET_DAYS else 'FULL ~5y'}")
    w(f"**Fee RT:** {FEE_RT_BPS} bps + slip {SLIP_RT_BPS} bps = {FEE_RT_BPS+SLIP_RT_BPS} bps total")
    w(f"**Risk:** {RISK_PCT*100}% per trade, hold cap {HOLD_MAX_BARS} bar (90 min)")
    w(f"**Pre-reg:** reports/researcher/hypotheses/2026-05-17-bidirectional-shorts.md")
    w(f"**Gate:** mean R >= {GATE_MEAN_R:+.2f}, shuffle null p < {GATE_SHUFFLE_P} (Bonferroni 2-test)")
    w(f"**Shuffle iters:** {SHUFFLE_ITERS}")
    w("")
    w("---")
    w("")

    strategies = [
        ("vsa_buying_climax", "HYP-S3-A — VSA Buying Climax + Distribution Test"),
        ("brooks_failed_high", "HYP-S3-B — Brooks Failed High (failed-approach)"),
    ]

    syms = SYMBOLS[:1] if DRY_RUN else SYMBOLS

    summary_rows: list[dict] = []
    for strat_name, strat_title in strategies:
        w(f"## {strat_title}")
        w("")
        t0 = time.time()
        trades = collect_trades(syms, strat_name,
                                subset_days=SUBSET_DAYS, parallel=PARALLEL)
        elapsed = time.time() - t0
        w(f"- Collection time: {elapsed:.1f}s ({elapsed/60:.1f} min)")
        w(f"- Pool size: **{len(trades)}** trades")
        if not trades:
            w(f"- **STOP:** no trades. Strategy generated 0 signals — check params/data.")
            w("")
            summary_rows.append({
                "strat": strat_name,
                "n": 0, "mean_R": 0.0, "wr": 0.0,
                "shuffle_p": 1.0, "verdict": "NO_TRADES",
            })
            continue

        Rs = [t.R for t in trades]
        n_total = len(Rs)
        mR = sum(Rs) / n_total
        sumR = sum(Rs)
        wr = sum(1 for r in Rs if r > 0) / n_total * 100
        n_short = sum(1 for t in trades if t.direction == "short")
        n_long = n_total - n_short

        span_days = (trades[-1].entry_ts - trades[0].entry_ts).days or 1
        per_year = n_total / span_days * 365

        w(f"- Span: {trades[0].entry_ts.date()} -> {trades[-1].entry_ts.date()} ({span_days/365:.2f} yr)")
        w(f"- Side mix: {n_short} short, {n_long} long")
        w(f"- Mean R: **{mR:+.3f}**, sumR: {sumR:+.1f}, WR: {wr:.1f}%, trades/yr: {per_year:.0f}")
        w(f"- Exit reasons: {dict((er, sum(1 for t in trades if t.exit_reason == er)) for er in ('tp', 'sl', 'time'))}")

        # Per-symbol breakdown
        w("")
        w("### Per-Symbol")
        w("")
        w("| Symbol | n | mean R | sumR | WR% |")
        w("|---|---:|---:|---:|---:|")
        for sym in syms:
            sym_tr = [t for t in trades if t.symbol == sym]
            if not sym_tr:
                w(f"| {sym} | 0 | - | - | - |")
                continue
            sRs = [t.R for t in sym_tr]
            w(f"| {sym} | {len(sym_tr)} | {sum(sRs)/len(sRs):+.3f} | {sum(sRs):+.1f} | {sum(1 for r in sRs if r > 0)/len(sRs)*100:.1f} |")

        # Per-year breakdown
        w("")
        w("### Per-Year (365-day buckets from first trade)")
        w("")
        yrs = per_year_breakdown(trades)
        if yrs:
            w("| Year start | Year end | n | n_long | n_short | mean R | mean R long | mean R short | WR% |")
            w("|---|---|---:|---:|---:|---:|---:|---:|---:|")
            for y in yrs:
                w(f"| {y['start']} | {y['end']} | {y['n']} | {y['n_long']} | {y['n_short']} | "
                  f"{y['mean_R']:+.3f} | {y['mean_R_long']:+.3f} | {y['mean_R_short']:+.3f} | "
                  f"{y['wr_pct']:.1f} |")

        # Bear vs bull tahmini (Y1+Y2 = bear, Y3+Y4 = bull, Y5 = normaliz)
        if len(yrs) >= 4:
            y0_start = pd.Timestamp(yrs[0]['start'], tz='UTC')
            y1_end = pd.Timestamp(yrs[1]['end'], tz='UTC')
            y2_start = pd.Timestamp(yrs[2]['start'], tz='UTC')
            y3_end = pd.Timestamp(yrs[3]['end'], tz='UTC')
            bear_Rs = [t.R for t in trades
                       if y0_start <= _to_utc(t.entry_ts.to_pydatetime()) < y1_end]
            bull_Rs = [t.R for t in trades
                       if y2_start <= _to_utc(t.entry_ts.to_pydatetime()) < y3_end]
            if bear_Rs and bull_Rs:
                w("")
                w(f"**Bear yil (Y1+Y2) mean R:** {sum(bear_Rs)/len(bear_Rs):+.3f} (n={len(bear_Rs)})")
                w(f"**Bull yil (Y3+Y4) mean R:** {sum(bull_Rs)/len(bull_Rs):+.3f} (n={len(bull_Rs)})")
                w(f"**Bear vs bull spread:** {sum(bear_Rs)/len(bear_Rs) - sum(bull_Rs)/len(bull_Rs):+.3f}")

        # Shuffle null
        w("")
        w("### Shuffle Null Baseline")
        w("")
        # Estimate avg SL/TP for null sim — use median across trades
        sl_atr_mults = []
        for tr in trades[:500]:
            risk_pct = abs(tr.sl_price - tr.entry_price) / tr.entry_price
            # ATR pct ~0.005-0.02 on 5m crypto; back-calculate SL ATR mult
            # If risk_pct ~= sl_atr_factor * atr_pct, assume atr_pct ~0.01 (typical)
            sl_atr_mults.append(risk_pct / 0.01)
        sl_atr_med = float(np.median(sl_atr_mults)) if sl_atr_mults else 0.8
        # Use trade's actual side
        side = "short"  # both S3 strategies are short-only

        tp_R = 1.5 if strat_name == "vsa_buying_climax" else 1.2

        t0_shuf = time.time()
        p_val, null_mean, null_std = shuffle_null_p_value(
            real_mean_R=mR,
            n_real=n_total,
            side=side,
            sl_atr_mult=sl_atr_med,
            tp_R=tp_R,
            symbols=syms,
            iters=SHUFFLE_ITERS,
            seed=42,
        )
        shuf_elapsed = time.time() - t0_shuf
        w(f"- Real mean R: **{mR:+.3f}**")
        w(f"- Null mean (across {SHUFFLE_ITERS} iters): {null_mean:+.3f} +- {null_std:.3f}")
        w(f"- p-value (one-sided): **{p_val:.4f}** (gate < {GATE_SHUFFLE_P})")
        w(f"- Shuffle time: {shuf_elapsed:.1f}s")

        # Verdict
        pass_mR = mR >= GATE_MEAN_R
        pass_shuf = p_val < GATE_SHUFFLE_P
        verdict = "PASS" if (pass_mR and pass_shuf) else "RED"
        w("")
        w(f"### Verdict: **{verdict}**")
        if verdict == "RED":
            failed = []
            if not pass_mR:
                failed.append(f"mean R {mR:+.3f} < {GATE_MEAN_R:+.2f}")
            if not pass_shuf:
                failed.append(f"shuffle p {p_val:.4f} >= {GATE_SHUFFLE_P}")
            w(f"- Failed gates: {failed}")
        w("")
        w("---")
        w("")

        summary_rows.append({
            "strat": strat_name,
            "n": n_total,
            "mean_R": mR,
            "wr": wr,
            "shuffle_p": p_val,
            "verdict": verdict,
        })

    # Summary
    w("## Summary Matrix")
    w("")
    w("| Strategy | n trades | mean R | WR% | shuffle p | Verdict |")
    w("|---|---:|---:|---:|---:|:---:|")
    for r in summary_rows:
        w(f"| {r['strat']} | {r['n']} | {r['mean_R']:+.3f} | "
          f"{r['wr']:.1f} | {r['shuffle_p']:.4f} | **{r['verdict']}** |")

    # Decision matrix
    n_pass = sum(1 for r in summary_rows if r["verdict"] == "PASS")
    w("")
    w("## Decision (S3 Bundle)")
    w("")
    if n_pass == 2:
        w("**2/2 PASS** -> Lab tournament candidates + ensemble TOP-4 test sec48 GO.")
    elif n_pass == 1:
        w(f"**1/2 PASS** -> Tek PASS strategy ensemble candidate (sec48 limited).")
    else:
        w("**0/2 PASS** -> Archive both. Yapisal prior (5m fee-grave) dogrulandi. "
          "Sprint v2 backlog: regime-conditional sizing / ML meta-labeling.")
    w("")
    w("## Bear Yil Uplift Tahmini")
    w("")
    w("Y1 (bear-start 2021-05/2022-05) ve Y2 (bear-bottom 2022-05/2023-05)")
    w("short edge per-year breakdown tablolarinda raporlandi.")
    w("Ensemble uplift hesabi sec48 sprint'inde (TOP-2 + S3-PASS) yapilir.")
    w("")
    w("---")
    w("")
    w("**Reproducibility:**")
    w(f"- Strategy code: src/price_action/strategies/{{vsa_buying_climax, brooks_failed_high}}.py")
    w(f"- Manifests: src/price_action/strategies/manifests/{{name}}_5m.yaml")
    w(f"- Pre-reg: reports/researcher/hypotheses/2026-05-17-bidirectional-shorts.md")
    w(f"- Fee {FEE_RT_BPS}bps + slip {SLIP_RT_BPS}bps RT, hold cap {HOLD_MAX_BARS} bar")
    w(f"- Risk {RISK_PCT*100}%, shuffle {SHUFFLE_ITERS} iters seed 42")

    REPORT_OUT.write_text("\n".join(out_lines), encoding="utf-8")
    print(f"\nReport: {REPORT_OUT}")


if __name__ == "__main__":
    main()
