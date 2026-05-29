"""Trade-level moving-block bootstrap MaxDD tail for the 2x2 cells.

The monthly-min tail in _combined_2x2_analyze.py is too coarse (this config is
near-monotone monthly -> p95==p99). The REAL tail risk lives in intra-month
drawdown clustering. Here we resample the time-ordered trade R-stream with
MOVING BLOCKS (preserves serial / volatility-cluster structure -> NOT iid),
re-run the SAME production_replay sizing logic via a fast vectorized R->equity
proxy, and report the bootstrap MaxDD distribution (p95/p99) + worst-month.

Block length chosen in TRADE units to span ~ a few days of clustered signals.
NO iid MC. Read-only, no daemon touch.
"""
from __future__ import annotations
import os, sys, pickle
from pathlib import Path

os.environ["PA_DUCKDB_READ_ONLY"] = "true"
os.environ["PA_LOG_QUIET"] = "1"
import warnings; warnings.filterwarnings("ignore")
import numpy as np, pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "src"))
import importlib.util
spec = importlib.util.spec_from_file_location(
    "wlr", str(ROOT / "scripts" / "crypto_winner_let_run_vsa_exit.py"))
wlr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wlr)

ALIGN = pd.Timestamp("2021-05-16", tz="UTC")
END = pd.Timestamp("2026-07-01", tz="UTC")
SEED = 12345
RISK = 0.005  # per-trade risk fraction (matches cfg.risk_pct)


def clip(tr):
    return [t for t in tr if ALIGN <= t["entry_ts"] < END and wlr.sl_pct_of(t) >= 0.025]


def realized_dd_from_R(Rs, risk=RISK):
    """Fixed-fractional equity path from ordered R stream; returns MaxDD%."""
    eq = 1.0; peak = 1.0; mdd = 0.0
    for r in Rs:
        eq *= (1.0 + risk * r)
        peak = max(peak, eq)
        mdd = min(mdd, (eq - peak) / peak)
    return mdd * 100.0


def block_boot_dd(Rs, n_iter=4000, block=24, seed=SEED, risk=RISK):
    """Moving-block bootstrap on the ordered R stream -> MaxDD distribution.
    block=24 trades ~ a clustered burst at portfolio level."""
    a = np.asarray(Rs, dtype=float); n = len(a)
    if n < block + 1:
        return dict(realized=np.nan, p50=np.nan, p95=np.nan, p99=np.nan)
    rng = np.random.default_rng(seed)
    nb = int(np.ceil(n / block))
    starts_pool = np.arange(0, n - block + 1)
    dds = np.empty(n_iter)
    for it in range(n_iter):
        starts = rng.choice(starts_pool, size=nb, replace=True)
        seq = np.concatenate([a[s:s + block] for s in starts])[:n]
        eq = np.cumprod(1.0 + risk * seq)
        peak = np.maximum.accumulate(eq)
        dds[it] = ((eq - peak) / peak).min() * 100.0
    return dict(realized=realized_dd_from_R(a, risk),
                p50=float(np.percentile(dds, 50)),
                p95=float(np.percentile(dds, 5)),   # 5th pct = 95% worst
                p99=float(np.percentile(dds, 1)))


def main():
    V10 = pickle.load(open("/tmp/wlr_vsa_variants.pkl", "rb"))
    E4 = pickle.load(open("/tmp/expansion_4sym_2variants.pkl", "rb"))
    new4 = ["ZEC/USDT", "NEAR/USDT", "FIL/USDT", "XLM/USDT"]

    def flat(d):
        return [t for s in d for t in d[s]]

    cells = {
        "10/1.5": flat({s: V10["B_baseline"][s] for s in wlr.SYMS}),
        "10/3.0": flat({s: V10["V1a_trail3.0"][s] for s in wlr.SYMS}),
        "14/1.5": flat({s: V10["B_baseline"][s] for s in wlr.SYMS}) +
                  flat({s: E4["trail1.5"][s] for s in new4}),
        "14/3.0": flat({s: V10["V1a_trail3.0"][s] for s in wlr.SYMS}) +
                  flat({s: E4["trail3.0"][s] for s in new4}),
    }
    print("=" * 100)
    print("TRADE-LEVEL block-bootstrap MaxDD (moving block=24 trades, 4000 iter, NOT iid)")
    print("  R stream = time-ordered portfolio trades, fixed-frac risk=0.5%")
    print("=" * 100)
    print(f"{'cell':<10}| {'n_R':>6} {'realDD%':>8} {'bsDD_p50':>9} {'bsDD_p95':>9} {'bsDD_p99':>9}")
    print("-" * 70)
    res = {}
    for k, tr in cells.items():
        pool = sorted(clip(tr), key=lambda x: x["entry_ts"])
        Rs = [t["R"] for t in pool]
        d = block_boot_dd(Rs)
        res[k] = d
        print(f"{k:<10}| {len(Rs):>6} {d['realized']:>+8.1f} {d['p50']:>+9.1f} "
              f"{d['p95']:>+9.1f} {d['p99']:>+9.1f}")

    print("\n--- tail decomposition (bsDD_p99, baseline=10/1.5) ---")
    b = res["10/1.5"]["p99"]
    print(f"  base p99 {b:+.1f} | +symexp {res['14/1.5']['p99']-b:+.1f}pp "
          f"| +trail {res['10/3.0']['p99']-b:+.1f}pp "
          f"| combined {res['14/3.0']['p99']-b:+.1f}pp")
    add = (res['14/1.5']['p99']-b) + (res['10/3.0']['p99']-b)
    print(f"  additive-pred {add:+.1f}pp  vs  combined {res['14/3.0']['p99']-b:+.1f}pp  "
          f"interaction {(res['14/3.0']['p99']-b)-add:+.1f}pp")


if __name__ == "__main__":
    main()
