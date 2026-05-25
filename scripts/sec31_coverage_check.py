"""SEC31/32 Coverage Check — sym x TF gap detection + quality audit.

Checks:
  (a) start/end ts per (sym, TF)
  (b) bar count
  (c) expected vs actual bar count -> gap count + gap %
  (d) gap > 24h detection (contiguous ts diff > TF * 1440 thresholds)
  (e) duplicate ts purge (upsert already idempotent but audit here)
  (f) OHLCV invariant: high >= max(o,c), low <= min(o,c,h), volume >= 0

Run after ingest completes:
    python scripts/sec31_coverage_check.py

Outputs a JSON coverage matrix to reports/data_engineer/YYYY-MM-DD_scalp_coverage.json
and prints a human-readable table.
"""
from __future__ import annotations

import io
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

if __name__ == "__main__":
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    except Exception:
        pass

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import duckdb
import numpy as np
import pandas as pd

from price_action.data.store import OHLCVStore

VENUE = "binance"

# TF -> expected interval in minutes
TF_INTERVALS = {
    "1m":  1,
    "5m":  5,
    "15m": 15,
    "1h":  60,
    "4h":  240,
    "1d":  1440,
    "1w":  10080,
}

SYMBOLS = [
    "BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT",
    "ADA/USDT", "AVAX/USDT", "LINK/USDT", "DOT/USDT",
    "DOGE/USDT", "XRP/USDT",
]

COVERAGE_KILL_PCT  = 95.0   # below this -> kill recommendation
LARGE_GAP_HOURS    = 24.0   # gaps larger than this flagged


def check_sym_tf(store: OHLCVStore, symbol: str, tf: str) -> dict:
    """Full quality audit for one (symbol, TF) pair."""
    result = {
        "symbol":        symbol,
        "tf":            tf,
        "venue":         VENUE,
        "bar_count":     0,
        "first_ts":      None,
        "last_ts":       None,
        "expected_bars": 0,
        "gap_count":     0,
        "gap_pct":       0.0,
        "large_gap_count": 0,
        "large_gap_max_h": 0.0,
        "dup_count":     0,
        "ohlc_violations": 0,
        "volume_neg_count": 0,
        "coverage_pct":  0.0,
        "kill":          False,
        "status":        "empty",
        "errors":        [],
    }

    df = store.read(symbol=symbol, tf=tf, venue=VENUE)
    if df.empty:
        result["status"] = "empty"
        return result

    result["bar_count"] = len(df)
    result["first_ts"]  = str(df["ts"].min())[:19]
    result["last_ts"]   = str(df["ts"].max())[:19]

    # (b) expected bars from ts span
    tf_min = TF_INTERVALS.get(tf, 0)
    if tf_min > 0:
        span_min = (df["ts"].max() - df["ts"].min()).total_seconds() / 60
        expected = int(span_min / tf_min) + 1
        result["expected_bars"] = expected
        actual = len(df)
        gap_count = max(0, expected - actual)
        result["gap_count"] = gap_count
        result["gap_pct"]   = round(gap_count / expected * 100, 3) if expected > 0 else 0.0
        cov = actual / expected * 100 if expected > 0 else 0.0
        result["coverage_pct"] = round(cov, 2)

    # (d) large gap detection (> LARGE_GAP_HOURS)
    ts_sorted = df["ts"].sort_values().reset_index(drop=True)
    if len(ts_sorted) > 1:
        diffs_h = ts_sorted.diff().dt.total_seconds().dropna() / 3600.0
        large_gaps = diffs_h[diffs_h > LARGE_GAP_HOURS]
        result["large_gap_count"] = int(len(large_gaps))
        result["large_gap_max_h"] = round(float(large_gaps.max()), 1) if len(large_gaps) > 0 else 0.0

    # (e) duplicate ts
    dup_mask = df.duplicated(subset=["venue", "symbol", "timeframe", "ts"], keep=False)
    result["dup_count"] = int(dup_mask.sum())

    # (f) OHLC sanity: high >= max(open, close) and low <= min(open, close)
    if {"open", "high", "low", "close"}.issubset(df.columns):
        h_violation = (df["high"] < df[["open", "close"]].max(axis=1)).sum()
        l_violation = (df["low"]  > df[["open", "close"]].min(axis=1)).sum()
        result["ohlc_violations"] = int(h_violation + l_violation)

    # volume >= 0
    if "volume" in df.columns:
        result["volume_neg_count"] = int((df["volume"] < 0).sum())

    # Kill flag
    result["kill"] = result["coverage_pct"] < COVERAGE_KILL_PCT

    # Status
    if result["ohlc_violations"] > 0 or result["volume_neg_count"] > 0:
        result["status"] = "warn_quality"
    elif result["kill"]:
        result["status"] = "warn_coverage"
    elif result["large_gap_count"] > 0:
        result["status"] = "warn_gaps"
    else:
        result["status"] = "ok"

    return result


def main() -> None:
    print("SEC31/32 Coverage Check")
    print("=" * 80)
    t0 = time.time()
    store = OHLCVStore()

    # Determine which TFs actually have data
    with store._conn() as con:
        avail = con.execute(
            "SELECT DISTINCT timeframe FROM ohlcv WHERE venue=? ORDER BY timeframe",
            [VENUE]
        ).fetchall()
    avail_tfs = [r[0] for r in avail]
    print(f"Available TFs in store: {avail_tfs}")

    # Focus on scalp TFs + existing TFs
    check_tfs = [tf for tf in ["1m", "5m", "15m", "1h", "4h"] if tf in avail_tfs]
    if not check_tfs:
        print("  No scalp TF data found. Run sec31_ingest_5m.py + sec32_ingest_1m.py first.")
        check_tfs = avail_tfs  # fallback: check whatever exists

    all_results = []
    for sym in SYMBOLS:
        for tf in check_tfs:
            r = check_sym_tf(store, sym, tf)
            all_results.append(r)
            kill_str = " [KILL]" if r["kill"] else ""
            print(
                f"  {sym:<12} {tf:<4} bars={r['bar_count']:>8,}  "
                f"cov={r['coverage_pct']:>6.1f}%  "
                f"gaps={r['gap_count']:>6,}  "
                f"large_gaps={r['large_gap_count']:>3}  "
                f"dups={r['dup_count']:>3}  "
                f"ohlc_viol={r['ohlc_violations']:>3}  "
                f"{r['status']}{kill_str}"
            )

    # Kill summary
    kills = [(r["symbol"], r["tf"]) for r in all_results if r["kill"]]
    print()
    print("=" * 80)
    if kills:
        print(f"KILL CANDIDATES (coverage < {COVERAGE_KILL_PCT}%):")
        for sym, tf in kills:
            print(f"  -> DROP {sym} x {tf} from scalp universe")
    else:
        print("No kill candidates.")

    # OHLC violations
    viols = [(r["symbol"], r["tf"], r["ohlc_violations"]) for r in all_results if r["ohlc_violations"] > 0]
    if viols:
        print("OHLC VIOLATIONS (surface, keep raw):")
        for sym, tf, n in viols:
            print(f"  {sym} {tf}: {n} bars violate high>=max(o,c) or low<=min(o,c)")

    # Write JSON manifest
    out_dir = ROOT / "reports" / "data_engineer"
    out_dir.mkdir(parents=True, exist_ok=True)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    out_path = out_dir / f"{today}_scalp_coverage.json"
    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "venue": VENUE,
        "tfs_checked": check_tfs,
        "symbols": SYMBOLS,
        "coverage_kill_threshold_pct": COVERAGE_KILL_PCT,
        "kill_candidates": [{"symbol": s, "tf": t} for s, t in kills],
        "results": all_results,
    }
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, default=str)

    elapsed = time.time() - t0
    print()
    print(f"Manifest written: {out_path}")
    print(f"Elapsed: {elapsed:.1f}s")


if __name__ == "__main__":
    main()
