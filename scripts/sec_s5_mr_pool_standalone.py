"""SEC-S5 MR Pool — Standalone backtest of 3 MR strategies on 15m × 10 sym × 5y.

Hypotheses (pre-registered 2026-05-17):
  1. bollinger_fade_mr
  2. rsi_extreme_mr
  3. range_bo_failure_mr

Pipeline:
  1. Collect trades per (strategy, symbol) using BacktestEngine (sec31 pattern)
  2. Per-strategy stats: n trade, mean R, WR%, sumR
  3. Per-symbol stats (10 sym leave-one-out)
  4. Regime split: 2022 (bear), 2024 (bull), 2025-2026 (range)
  5. Shuffle null (n=100) p-value
  6. Pre-registered gate evaluation

Output:
  - data/sec_s5_mr_pool.pkl  (cached trade pool for ensemble retest)
  - reports/researcher/2026-05-17_sec_s5_mr_pool_standalone.md
"""
from __future__ import annotations
import io, os, pickle, sys, time
from pathlib import Path
from statistics import mean, median, stdev

if __name__ == "__main__":
    try: sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    except Exception: pass

os.environ["PA_LOG_QUIET"] = "1"
import warnings; warnings.filterwarnings("ignore")
import logging; logging.getLogger("price_action").setLevel(logging.ERROR)

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "src"))

import numpy as np
import pandas as pd

from price_action.backtest.engine import BacktestEngine
from price_action.signals.filters import volume_zscore
from scripts.run_real_backtest import _load_symbol_ohlcv

SYMBOLS_10 = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT",
              "ADA/USDT", "AVAX/USDT", "LINK/USDT", "DOT/USDT",
              "DOGE/USDT", "XRP/USDT"]

TF = "15m"
CACHE_PATH = ROOT / "data" / "sec_s5_mr_pool.pkl"
REPORT_OUT = ROOT / "reports" / "researcher" / "2026-05-17_sec_s5_mr_pool_standalone.md"


# Pre-registered gate
GATE = {
    "min_n_trades_bb_rsi": 1000,
    "min_n_trades_bof": 500,
    "min_mean_R": 0.10,
    "min_WR": 0.48,
    "max_pvalue": 0.10,
}


MR_STRATEGIES = [
    ("bollinger_fade_mr", "BollingerFadeMRStrategy"),
    ("rsi_extreme_mr", "RSIExtremeMRStrategy"),
    ("range_bo_failure_mr", "RangeBOFailureMRStrategy"),
]


def _gather_trades(module_name: str, class_name: str, sym: str, tf: str = TF) -> list[dict]:
    try:
        mod = __import__(
            f"price_action.strategies.{module_name}",
            fromlist=[class_name, "_default_manifest"],
        )
        cls = getattr(mod, class_name, None)
        manifest_fn = getattr(mod, "_default_manifest", None)
        if not cls or not manifest_fn:
            return []
        s = cls(manifest_fn())
    except Exception as e:
        print(f"  [SKIP] {module_name}/{sym}: import {e}")
        return []

    try:
        df = _load_symbol_ohlcv(sym, tf=tf)
        if df is None or df.empty:
            return []
        df = df.sort_values("ts").reset_index(drop=True)
        df["symbol"] = sym
        df["venue"] = "binance"
        df["timeframe"] = tf
        try:
            df["vol_z_pre"] = volume_zscore(df["volume"], period=20)
        except Exception:
            rolling = df["volume"].rolling(20)
            df["vol_z_pre"] = (df["volume"] - rolling.mean()) / rolling.std()

        def prov(*a, **k):
            return df.copy()

        e = BacktestEngine(risk_officer=None, store_load=None)
        r = e.run(
            s, [sym],
            start=df["ts"].iloc[0].to_pydatetime(),
            end=df["ts"].iloc[-1].to_pydatetime(),
            timeframe=tf,
            initial_capital=10_000.0,
            fees={"taker": 0.00075, "maker": -0.00010},
            slippage_bps=5.0,
            ohlcv_provider=prov,
        )
    except Exception as ex:
        print(f"  [ERR] {module_name}/{sym}: run {ex}")
        return []

    out = []
    ts_map = pd.to_datetime(df["ts"], utc=True)
    for _, t in r.trades.iterrows():
        try:
            conf = max(0.0, min(1.0, (float(t["confluence_score"]) - 1.5) / 1.5))
            entry_price = float(t["entry_price"])
            initial_sl = float(t["initial_sl"])
            mfe_pct = float(t.get("mfe_pct", 0))
            risk_pct = abs(initial_sl - entry_price) / entry_price if entry_price > 0 else 0.04
            side = str(t["side"]).lower()
            if side == "long":
                peak_R = mfe_pct / risk_pct if risk_pct > 0 else 0
            else:
                peak_R = -mfe_pct / risk_pct if risk_pct > 0 else 0
            final_R = float(t["realized_r_multiple"])
            peak_R = max(peak_R, final_R)

            ts_e = pd.Timestamp(t["entry_ts"])
            if ts_e.tzinfo is None:
                ts_e = ts_e.tz_localize("UTC")
            ts_x = pd.Timestamp(t["exit_ts"])
            if ts_x.tzinfo is None:
                ts_x = ts_x.tz_localize("UTC")

            mask = ts_map < ts_e
            vz = 0.0
            if mask.any():
                idx = ts_map[mask].index[-1]
                vz_val = df["vol_z_pre"].iloc[idx]
                vz = float(vz_val) if not pd.isna(vz_val) else 0.0

            out.append({
                "entry_ts": ts_e,
                "exit_ts": ts_x,
                "entry_price": entry_price,
                "initial_sl": initial_sl,
                "R": final_R,
                "peak_R": peak_R,
                "symbol": sym,
                "side": str(t["side"]),
                "conf": conf,
                "strategy": module_name,
                "vol_z": vz,
            })
        except Exception:
            continue
    return out


def shuffle_null_pvalue(trades: list[dict], n_iter: int = 100, seed: int = 7) -> tuple[float, float]:
    """Shuffle null: random sign-flip R; compare observed mean R vs null distribution.

    Returns (p_value, observed_mean_R).
    """
    rng = np.random.default_rng(seed)
    Rs = np.array([t["R"] for t in trades], dtype=float)
    obs_mean = float(np.mean(Rs))
    n = len(Rs)
    if n == 0:
        return 1.0, 0.0
    null_means = []
    for _ in range(n_iter):
        flips = rng.choice([-1, 1], size=n)
        null_means.append(float(np.mean(Rs * flips)))
    null_arr = np.array(null_means)
    # one-sided p-value: P(null mean >= obs mean)
    p = float((null_arr >= obs_mean).mean())
    return p, obs_mean


def regime_split(trades: list[dict]) -> dict[str, dict]:
    """Split trades into bear/range/bull buckets by year."""
    buckets = {"bear_2022": [], "bull_2023_2024": [], "range_2025_2026": []}
    for t in trades:
        ts = t["entry_ts"]
        if ts.year == 2022:
            buckets["bear_2022"].append(t)
        elif ts.year in (2023, 2024):
            buckets["bull_2023_2024"].append(t)
        elif ts.year >= 2025:
            buckets["range_2025_2026"].append(t)
    out = {}
    for k, v in buckets.items():
        if not v:
            out[k] = {"n": 0, "mR": 0.0, "wr": 0.0}
        else:
            Rs = [t["R"] for t in v]
            out[k] = {
                "n": len(v),
                "mR": sum(Rs) / len(Rs),
                "wr": sum(1 for r in Rs if r > 0) / len(Rs),
            }
    return out


def symbol_out_stats(trades: list[dict], syms: list[str]) -> dict[str, dict]:
    """Leave-one-out CV: stats with each symbol removed."""
    out = {}
    for excl in syms:
        sub = [t for t in trades if t["symbol"] != excl]
        if not sub:
            continue
        Rs = [t["R"] for t in sub]
        out[excl] = {
            "n": len(sub),
            "mR": sum(Rs) / len(Rs),
            "wr": sum(1 for r in Rs if r > 0) / len(Rs),
        }
    return out


def evaluate_strategy(strat: str, trades: list[dict]) -> dict:
    n = len(trades)
    if n == 0:
        return {
            "strategy": strat,
            "n": 0,
            "mR": 0.0,
            "wr": 0.0,
            "sumR": 0.0,
            "p_value": 1.0,
            "regime": {},
            "symout": {},
            "verdict": "RED (n=0)",
        }
    Rs = [t["R"] for t in trades]
    mR = sum(Rs) / n
    wr = sum(1 for r in Rs if r > 0) / n
    sumR = sum(Rs)
    p, _ = shuffle_null_pvalue(trades, n_iter=200)

    regime = regime_split(trades)
    symout = symbol_out_stats(trades, SYMBOLS_10)

    # Gate evaluation
    min_n = GATE["min_n_trades_bof"] if strat == "range_bo_failure_mr" else GATE["min_n_trades_bb_rsi"]

    fails = []
    if n < min_n:
        fails.append(f"n<{min_n}")
    if mR < GATE["min_mean_R"]:
        fails.append(f"mR<{GATE['min_mean_R']:.2f}")
    if wr < GATE["min_WR"]:
        fails.append(f"WR<{GATE['min_WR']:.2f}")
    if p >= GATE["max_pvalue"]:
        fails.append(f"p>={GATE['max_pvalue']:.2f}")

    pos_regimes = sum(1 for v in regime.values() if v["mR"] > 0)
    if pos_regimes < 2:
        fails.append(f"only {pos_regimes}/3 regime positive")

    # Symbol-out worst sapma
    if symout:
        worst_mr = min(s["mR"] for s in symout.values())
        sapma_pct = abs(worst_mr - mR) / max(abs(mR), 1e-9) * 100
        if sapma_pct > 50:
            fails.append(f"symout sapma {sapma_pct:.0f}%>50%")

    verdict = "PASS" if not fails else f"RED ({'; '.join(fails)})"

    return {
        "strategy": strat,
        "n": n,
        "mR": mR,
        "wr": wr,
        "sumR": sumR,
        "p_value": p,
        "regime": regime,
        "symout": symout,
        "verdict": verdict,
        "fails": fails,
    }


def main():
    REPORT_OUT.parent.mkdir(parents=True, exist_ok=True)
    out_lines: list[str] = []

    def w(line: str = ""):
        print(line)
        out_lines.append(line)

    w("# SEC-S5 MR Pool — Standalone Backtest")
    w("")
    w(f"**Generated:** {pd.Timestamp.now('UTC').isoformat()}")
    w(f"**Timeframe:** {TF}")
    w(f"**Universe:** {len(SYMBOLS_10)} sym × 5y")
    w(f"**Pre-registered hypotheses:** 3 (memory/researcher/hypotheses/2026-05-17-*)")
    w("")
    w("## Pre-Registered Gate")
    w(f"- n trades >= {GATE['min_n_trades_bb_rsi']} (BB, RSI), >= {GATE['min_n_trades_bof']} (BOF)")
    w(f"- mean R >= +{GATE['min_mean_R']:.2f}")
    w(f"- WR >= {GATE['min_WR']:.0%}")
    w(f"- shuffle p-value < {GATE['max_pvalue']:.2f}")
    w(f"- >= 2/3 regime positive (bear_2022, bull_2023_2024, range_2025_2026)")
    w(f"- symbol-out worst mR sapma <= 50%")
    w("")

    # ========================================================================
    # Collect trades
    # ========================================================================
    all_trades_by_strat: dict[str, list[dict]] = {}
    t0 = time.time()
    for module_name, class_name in MR_STRATEGIES:
        print(f"\n[collect] {module_name}")
        trades_s: list[dict] = []
        for sym in SYMBOLS_10:
            t1 = time.time()
            tr = _gather_trades(module_name, class_name, sym)
            print(f"  {sym}: {len(tr)} trades ({time.time()-t1:.1f}s)")
            trades_s.extend(tr)
        all_trades_by_strat[module_name] = trades_s
    elapsed = time.time() - t0
    print(f"\n[done] {elapsed:.1f}s ({elapsed/60:.1f} min)")

    # Cache pool
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with CACHE_PATH.open("wb") as f:
        pickle.dump(all_trades_by_strat, f)
    print(f"[cache] {CACHE_PATH}")

    # ========================================================================
    # Per-strategy evaluation
    # ========================================================================
    w("## Standalone Results")
    w("")
    w("| Strategy | n | mean R | sumR | WR | p-value (shuffle) | Verdict |")
    w("|---|---:|---:|---:|---:|---:|---|")
    results = {}
    for module_name, _ in MR_STRATEGIES:
        trades = all_trades_by_strat.get(module_name, [])
        res = evaluate_strategy(module_name, trades)
        results[module_name] = res
        w(f"| {module_name} | {res['n']:,} | {res['mR']:+.4f} | {res['sumR']:+.1f} | "
          f"{res['wr']:.1%} | {res['p_value']:.3f} | {res['verdict']} |")
    w("")

    # ========================================================================
    # Regime breakdown
    # ========================================================================
    w("## Regime Split")
    w("")
    for module_name, _ in MR_STRATEGIES:
        res = results[module_name]
        w(f"### {module_name}")
        w("")
        w("| Regime | n | mean R | WR |")
        w("|---|---:|---:|---:|")
        for r_name, r_stats in res["regime"].items():
            w(f"| {r_name} | {r_stats['n']:,} | {r_stats['mR']:+.4f} | {r_stats['wr']:.1%} |")
        w("")

    # ========================================================================
    # Symbol-out CV
    # ========================================================================
    w("## Symbol-Out CV (leave-one-out)")
    w("")
    for module_name, _ in MR_STRATEGIES:
        res = results[module_name]
        if not res["symout"]:
            continue
        w(f"### {module_name}")
        w("")
        w("| Excluded | n | mean R | WR |")
        w("|---|---:|---:|---:|")
        for sym, stats in res["symout"].items():
            w(f"| {sym} | {stats['n']:,} | {stats['mR']:+.4f} | {stats['wr']:.1%} |")
        w("")

    # ========================================================================
    # Verdict summary
    # ========================================================================
    w("## Verdict Summary")
    w("")
    pass_count = 0
    for module_name, _ in MR_STRATEGIES:
        res = results[module_name]
        emoji = "PASS" if res["verdict"] == "PASS" else "RED"
        w(f"- **{module_name}**: {emoji} - {res['verdict']}")
        if res["verdict"] == "PASS":
            pass_count += 1
    w("")
    w(f"**PASS count:** {pass_count}/3")
    w("")
    if pass_count == 0:
        w("**MR POOL VERDICT: RED** — none of the 3 strategies cleared the gate.")
        w("No standalone PASS -> ensemble retest skipped, hypothesis archived.")
    elif pass_count >= 1:
        w(f"**MR POOL VERDICT: PARTIAL/PASS** — {pass_count} strategy(s) cleared gate.")
        w("Proceed to ensemble retest (15m R4 + PASS strategies).")

    REPORT_OUT.write_text("\n".join(out_lines), encoding="utf-8")
    print(f"\n[report] {REPORT_OUT}")


if __name__ == "__main__":
    main()
