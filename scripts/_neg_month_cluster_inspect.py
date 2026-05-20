"""Cluster signal inspection — neg aylarda aynı 15-30 dk içinde çoklu trade'ler.

Hipotez: TOP4 stratejiler benzer setup'larda bir tek 15m barda 4-7 farklı
sembolde aynı side'da sinyal üretiyor; biri yanlışsa hepsi yanlış.
"""
from __future__ import annotations

import io
import os
import pickle
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path

if __name__ == "__main__":
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    except Exception:
        pass

os.environ["PA_LOG_QUIET"] = "1"
import warnings
warnings.filterwarnings("ignore")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

POOL_15M = Path("data/sec31_15m_pool.pkl")
TOP4 = {"vsa_climax_test", "brooks_failed_breakout",
        "anchored_vwap_reversal", "engulfing_continuation"}
SYMS = {"BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "ADA/USDT",
        "AVAX/USDT", "LINK/USDT", "DOT/USDT", "DOGE/USDT", "XRP/USDT"}

NEG_MONTHS = ["2025-07", "2026-02", "2024-02", "2025-01", "2026-03", "2024-10"]
POS_MONTHS_SAMPLE = ["2021-09", "2024-04", "2024-08", "2024-12", "2025-11", "2026-04"]


def to_utc(ts):
    if hasattr(ts, "tz_localize"):
        if ts.tzinfo is None:
            return ts.tz_localize("UTC")
        return ts.tz_convert("UTC")
    return ts


def month_bounds(yyyy_mm):
    y, m = map(int, yyyy_mm.split("-"))
    start = datetime(y, m, 1, tzinfo=timezone.utc)
    if m == 12:
        end = datetime(y+1, 1, 1, tzinfo=timezone.utc)
    else:
        end = datetime(y, m+1, 1, tzinfo=timezone.utc)
    return start, end


def cluster_stats(trades, window_sec=900):
    """For each trade entry, count how many other (sym,side) raw-pool trades
    were open within +/- window seconds. Cluster = >= 5 simultaneous signals."""
    sorted_t = sorted(trades, key=lambda x: to_utc(x["entry_ts"]))
    cluster_sizes = []
    cluster_R_means = []
    for i, t in enumerate(sorted_t):
        ts = to_utc(t["entry_ts"])
        # find all trades within +/- window
        cluster = [t]
        for j in range(i+1, len(sorted_t)):
            other_ts = to_utc(sorted_t[j]["entry_ts"])
            if (other_ts - ts).total_seconds() > window_sec:
                break
            cluster.append(sorted_t[j])
        for j in range(i-1, -1, -1):
            other_ts = to_utc(sorted_t[j]["entry_ts"])
            if (ts - other_ts).total_seconds() > window_sec:
                break
            cluster.append(sorted_t[j])
        cluster_sizes.append(len(cluster))
        cluster_R_means.append(sum(c["R"] for c in cluster) / len(cluster))
    return cluster_sizes, cluster_R_means


def main():
    print("=" * 100)
    print("CLUSTER INSPECTION — concurrent signal trade dynamics")
    print("=" * 100)

    with POOL_15M.open("rb") as fh:
        pool_raw = pickle.load(fh)
    pool = [t for t in pool_raw if t.get("strategy") in TOP4 and t.get("symbol") in SYMS]
    print(f"\n[pool] {len(pool):,} trade")

    print(f"\n--- NEG MONTHS cluster stats (window=15min) ---")
    for ym in NEG_MONTHS:
        start, end = month_bounds(ym)
        m_t = [t for t in pool if start <= to_utc(t["entry_ts"]) < end]
        if not m_t:
            continue
        sizes, R_means = cluster_stats(m_t, 900)
        large = [(s, r) for s, r in zip(sizes, R_means) if s >= 5]
        very_large = [(s, r) for s, r in zip(sizes, R_means) if s >= 8]
        n_in_large = sum(1 for s in sizes if s >= 5)
        n_in_vl = sum(1 for s in sizes if s >= 8)
        avg_size = sum(sizes) / len(sizes)
        # cluster R mean — average per-trade R when in cluster of >= 5
        in_cluster_R = [r for s, r in zip(sizes, R_means) if s >= 5]
        out_cluster_R = [r for s, r in zip(sizes, R_means) if s < 5]
        print(f"  {ym}: n={len(m_t)} avg_cluster={avg_size:.1f} "
              f"in_5plus={n_in_large}({n_in_large/len(sizes)*100:.0f}%) "
              f"in_8plus={n_in_vl}({n_in_vl/len(sizes)*100:.0f}%) "
              f"cluster5+ mean_R={sum(in_cluster_R)/len(in_cluster_R) if in_cluster_R else 0:+.3f} "
              f"vs solo mean_R={sum(out_cluster_R)/len(out_cluster_R) if out_cluster_R else 0:+.3f}")

    print(f"\n--- POS MONTHS sample cluster stats (window=15min) ---")
    for ym in POS_MONTHS_SAMPLE:
        start, end = month_bounds(ym)
        m_t = [t for t in pool if start <= to_utc(t["entry_ts"]) < end]
        if not m_t:
            continue
        sizes, R_means = cluster_stats(m_t, 900)
        n_in_large = sum(1 for s in sizes if s >= 5)
        in_cluster_R = [r for s, r in zip(sizes, R_means) if s >= 5]
        out_cluster_R = [r for s, r in zip(sizes, R_means) if s < 5]
        avg_size = sum(sizes) / len(sizes)
        print(f"  {ym}: n={len(m_t)} avg_cluster={avg_size:.1f} "
              f"in_5plus={n_in_large}({n_in_large/len(sizes)*100:.0f}%) "
              f"cluster5+ mean_R={sum(in_cluster_R)/len(in_cluster_R) if in_cluster_R else 0:+.3f} "
              f"vs solo mean_R={sum(out_cluster_R)/len(out_cluster_R) if out_cluster_R else 0:+.3f}")


if __name__ == "__main__":
    main()
