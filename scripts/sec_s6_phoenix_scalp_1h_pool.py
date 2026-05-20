"""SEC-S6: Phoenix-Scalp 1h TOP-4 pool collect (Lab Scientist 1h pivot feasibility).

15m R4 v3.1 production candidate'a paralel 1h test. TOP-4 strateji × 10 sym × 3y.
1h data: data/market.duckdb (10 sym × 26,280 bar × 2023-05-10 → 2026-05-09).

Output: data/sec_s6_1h_top4_pool.pkl

Patern: sec31_phoenix_scalp_15m_rolling.collect_all_trades() ama TF=1h, TOP-4 only.
"""
from __future__ import annotations

import io
import os
import pickle
import sys
import time
from pathlib import Path

if __name__ == "__main__":
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    except Exception:
        pass

os.environ["PA_LOG_QUIET"] = "1"
import warnings
warnings.filterwarnings("ignore")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

import logging
logging.getLogger("price_action").setLevel(logging.ERROR)

# 15m pattern reuse — _gather_peakR_single TF-parametric
from scripts.sec31_phoenix_scalp_15m_rolling import _gather_peakR_single

TF = "1h"
CACHE_OUT = ROOT / "data" / "sec_s6_1h_top4_pool.pkl"

# TOP-4 (15m R4 paterni)
TOP4_STRATEGIES = [
    ("vsa_climax_test", "VSAClimaxTestStrategy"),
    ("brooks_failed_breakout", "BrooksFailedBreakoutStrategy"),
    ("anchored_vwap_reversal", "AnchoredVWAPReversalStrategy"),
    ("engulfing_continuation", "EngulfingContinuationStrategy"),
]

SYMBOLS_10 = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT",
              "ADA/USDT", "AVAX/USDT", "LINK/USDT", "DOT/USDT",
              "DOGE/USDT", "XRP/USDT"]


def main():
    print(f"SEC-S6: Phoenix-Scalp 1h TOP-4 pool collect")
    print(f"=" * 70)
    print(f"TF: {TF}")
    print(f"Strategies: {[s[0] for s in TOP4_STRATEGIES]}")
    print(f"Symbols: {len(SYMBOLS_10)}")
    print(f"Tasks: {len(TOP4_STRATEGIES) * len(SYMBOLS_10)}")
    print(f"Cache out: {CACHE_OUT}")
    print()

    tasks = [(m, c, sym, TF) for m, c in TOP4_STRATEGIES for sym in SYMBOLS_10]
    all_trades = []
    t0 = time.time()
    for i, task in enumerate(tasks, start=1):
        t1 = time.time()
        print(f"[{i:2d}/{len(tasks)}] {task[0]:30s} / {task[2]:10s} ...", end=" ", flush=True)
        trades = _gather_peakR_single(task)
        all_trades.extend(trades)
        dt = time.time() - t1
        print(f"n={len(trades):5d}  ({dt:.1f}s)")

    elapsed = time.time() - t0
    print()
    print(f"=" * 70)
    print(f"Total trades: {len(all_trades):,}")
    print(f"Elapsed: {elapsed:.1f}s ({elapsed/60:.1f} min)")

    if not all_trades:
        print(f"\n[FATAL] pool empty — feature/manifest sorun var")
        return

    all_trades.sort(key=lambda x: x["entry_ts"])
    Rs = [t["R"] for t in all_trades]
    wr = sum(1 for r in Rs if r > 0) / len(Rs) * 100
    print(f"Pool stats:")
    print(f"  mean R   : {sum(Rs)/len(Rs):+.3f}")
    print(f"  sumR     : {sum(Rs):+.1f}")
    print(f"  WR       : {wr:.1f}%")
    print(f"  Range    : {all_trades[0]['entry_ts']} → {all_trades[-1]['exit_ts']}")

    # Strategy + symbol breakdown
    from collections import Counter
    s_cnt = Counter(t["strategy"] for t in all_trades)
    sym_cnt = Counter(t["symbol"] for t in all_trades)
    print(f"\nPer-strategy:")
    for s, c in s_cnt.most_common():
        Rs_s = [t["R"] for t in all_trades if t["strategy"] == s]
        print(f"  {s:30s}  n={c:5d}  mR={sum(Rs_s)/len(Rs_s):+.3f}")
    print(f"\nPer-symbol (first 5):")
    for s, c in sym_cnt.most_common(5):
        print(f"  {s:10s}  n={c:5d}")

    # Save
    CACHE_OUT.parent.mkdir(parents=True, exist_ok=True)
    with CACHE_OUT.open("wb") as fh:
        pickle.dump(all_trades, fh, protocol=pickle.HIGHEST_PROTOCOL)
    print(f"\n[SAVED] {CACHE_OUT} ({CACHE_OUT.stat().st_size/1e6:.1f} MB)")


if __name__ == "__main__":
    main()
