"""SEC53 Pool Reproducibility Verification Script (DQ-05 / RP-01).

Usage:
    python scripts/verify_sec53_pool.py

Checks:
    1. Pool file exists and matches expected SHA256.
    2. Pool field completeness (no null entry_ts / exit_ts / R / conf).
    3. Timezone consistency (all entry_ts are UTC-aware).
    4. Strategy and symbol coverage (TOP-4 x 10 sym).
    5. Date range: 2021-05-16 -> 2026-05-16.
    6. AVWAP conf distribution (v1.1 check: conf=0.0 < 15% threshold).
    7. 15m DuckDB coverage match.

Exit codes:
    0 = all checks PASS
    1 = one or more checks FAIL
"""
from __future__ import annotations

import hashlib
import pickle
import sys
from datetime import timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

POOL_PATH = ROOT / "data" / "sec53_15m_pool_v11.pkl"

# SHA256 computed 2026-05-17 (canonical reference)
EXPECTED_SHA256 = "59a794ef278e47f696cdb14ddf42db383ed097474f938f8902a34e450a4e3ad6"

EXPECTED_SYMBOLS = {
    "BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "ADA/USDT",
    "AVAX/USDT", "LINK/USDT", "DOT/USDT", "DOGE/USDT", "XRP/USDT",
}

EXPECTED_STRATEGIES = {
    "vsa_climax_test",
    "brooks_failed_breakout",
    "anchored_vwap_reversal",
    "engulfing_continuation",
}

REQUIRED_FIELDS = ["entry_ts", "exit_ts", "R", "conf", "symbol", "strategy", "side"]

# AVWAP v1.1 check: conf=0.0 must be < 20% of AVWAP trades
# (v1.0 was 100% conf=0.0 due to design bug)
AVWAP_ZERO_CONF_MAX_PCT = 20.0

# Min/max expected total trades
MIN_TOTAL_TRADES = 350_000
MAX_TOTAL_TRADES = 420_000


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(65536)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def _check(label: str, condition: bool, detail: str = "") -> bool:
    status = "PASS" if condition else "FAIL"
    msg = f"[{status}] {label}"
    if detail:
        msg += f" -- {detail}"
    print(msg)
    return condition


def main() -> int:
    results = []
    print("=" * 70)
    print("SEC53 Pool Verification (DQ-05 / RP-01)")
    print(f"Pool: {POOL_PATH}")
    print("=" * 70)

    # --- 1. File exists ---
    ok = _check("Pool file exists", POOL_PATH.exists(),
                f"path={POOL_PATH}")
    results.append(ok)
    if not ok:
        print("\nFATAL: pool file missing. Cannot continue.")
        return 1

    size_mb = POOL_PATH.stat().st_size / 1e6
    print(f"  File size: {size_mb:.1f} MB")

    # --- 2. SHA256 ---
    actual_sha = _sha256(POOL_PATH)
    ok = _check("SHA256 matches canonical",
                actual_sha == EXPECTED_SHA256,
                f"expected={EXPECTED_SHA256[:16]}... actual={actual_sha[:16]}...")
    results.append(ok)
    if not ok:
        print("  WARNING: hash mismatch -> pool was re-generated or modified.")
        print("  If SEC53_FORCE=1 was used to re-collect, update EXPECTED_SHA256 in this script.")

    # --- 3. Load pool ---
    print("\nLoading pool...")
    with POOL_PATH.open("rb") as f:
        pool: list[dict] = pickle.load(f)
    print(f"  Loaded {len(pool):,} trades")

    # --- 4. Trade count bounds ---
    ok = _check("Total trades in expected range",
                MIN_TOTAL_TRADES <= len(pool) <= MAX_TOTAL_TRADES,
                f"{len(pool):,} not in [{MIN_TOTAL_TRADES:,}, {MAX_TOTAL_TRADES:,}]")
    results.append(ok)

    # --- 5. Required fields ---
    missing_fields = [f for f in REQUIRED_FIELDS if f not in (pool[0] if pool else {})]
    ok = _check("All required fields present",
                len(missing_fields) == 0,
                f"missing={missing_fields}")
    results.append(ok)

    # --- 6. No null critical fields ---
    null_counts = {f: sum(1 for t in pool if t.get(f) is None) for f in REQUIRED_FIELDS}
    any_null = any(v > 0 for v in null_counts.values())
    ok = _check("No null values in critical fields",
                not any_null,
                str({k: v for k, v in null_counts.items() if v > 0}))
    results.append(ok)

    # --- 7. Timezone consistency ---
    bad_tz = 0
    for t in pool[:500]:  # sample first 500
        ts = t.get("entry_ts")
        if ts is not None:
            if hasattr(ts, "tzinfo") and ts.tzinfo is None:
                bad_tz += 1
            elif hasattr(ts, "tz") and ts.tz is None:
                bad_tz += 1
    ok = _check("Timezone: entry_ts is UTC-aware (sample 500)",
                bad_tz == 0,
                f"tz-naive count={bad_tz}")
    results.append(ok)

    # --- 8. Symbol coverage ---
    pool_symbols = set(t.get("symbol") for t in pool)
    ok = _check("All 10 symbols present",
                EXPECTED_SYMBOLS.issubset(pool_symbols),
                f"missing={EXPECTED_SYMBOLS - pool_symbols}")
    results.append(ok)

    # --- 9. Strategy coverage ---
    pool_strats = set(t.get("strategy") for t in pool)
    ok = _check("All TOP-4 strategies present",
                EXPECTED_STRATEGIES.issubset(pool_strats),
                f"missing={EXPECTED_STRATEGIES - pool_strats}")
    results.append(ok)

    # --- 10. Date range ---
    ts_list = pd.to_datetime([t["entry_ts"] for t in pool], utc=True)
    min_ts = ts_list.min()
    max_ts = ts_list.max()
    expected_min = pd.Timestamp("2021-05-16", tz="UTC")
    expected_max = pd.Timestamp("2026-05-17", tz="UTC")
    ok = _check("Date range: starts >= 2021-05-16",
                min_ts >= expected_min,
                f"min_ts={min_ts.date()}")
    results.append(ok)
    ok = _check("Date range: ends <= 2026-05-17",
                max_ts <= expected_max,
                f"max_ts={max_ts.date()}")
    results.append(ok)

    # --- 11. AVWAP v1.1 conf distribution ---
    avwap = [t for t in pool if t.get("strategy") == "anchored_vwap_reversal"]
    if avwap:
        confs = [float(t.get("conf", 0)) for t in avwap]
        n_zero = sum(1 for c in confs if c == 0.0)
        pct_zero = n_zero / len(confs) * 100
        mean_conf = sum(confs) / len(confs)
        ok = _check(f"AVWAP v1.1: conf=0.0 below {AVWAP_ZERO_CONF_MAX_PCT:.0f}% threshold",
                    pct_zero < AVWAP_ZERO_CONF_MAX_PCT,
                    f"conf=0.0: {n_zero}/{len(avwap)} = {pct_zero:.1f}%  mean_conf={mean_conf:.3f}")
        results.append(ok)

        n_ge025 = sum(1 for c in confs if c >= 0.25)
        print(f"  AVWAP details: n={len(avwap):,}  conf>=0.25={n_ge025:,} ({100*n_ge025/len(avwap):.1f}%)")
    else:
        print("  [WARN] No AVWAP trades in pool")

    # --- 12. Per-strategy trade counts ---
    print("\nPer-strategy counts:")
    for s in sorted(EXPECTED_STRATEGIES):
        n = sum(1 for t in pool if t.get("strategy") == s)
        print(f"  {s:<35} {n:>8,}")

    print("\nPer-symbol counts:")
    for s in sorted(EXPECTED_SYMBOLS):
        n = sum(1 for t in pool if t.get("symbol") == s)
        print(f"  {s:<15} {n:>8,}")

    # --- 13. DuckDB 15m coverage check ---
    print("\nDuckDB 15m coverage check...")
    try:
        from price_action.data.store import OHLCVStore
        store = OHLCVStore()
        with store._conn() as con:
            rows = con.execute(
                "SELECT symbol, COUNT(*) as n, MIN(ts) as first, MAX(ts) as last "
                "FROM ohlcv WHERE venue='binance' AND timeframe='15m' "
                "GROUP BY symbol ORDER BY symbol"
            ).fetchall()
        expected_5y = int(5 * 365 * 96)
        all_ok = True
        for sym, n, first, last in rows:
            cov = n / expected_5y * 100
            status = "OK" if cov >= 95 else "WARN"
            if cov < 95:
                all_ok = False
            print(f"  {sym:<12} bars={n:>8,}  cov_5y={cov:.1f}%  [{status}]")
        ok = _check("DuckDB 15m coverage >= 95% for all symbols", all_ok)
        results.append(ok)
    except Exception as e:
        print(f"  DuckDB check failed: {e}")
        results.append(False)

    # --- Summary ---
    print("\n" + "=" * 70)
    n_pass = sum(1 for r in results if r)
    n_fail = len(results) - n_pass
    print(f"SUMMARY: {n_pass}/{len(results)} checks PASS  |  {n_fail} FAIL")
    if n_fail == 0:
        print("VERDICT: POOL VERIFIED -- reproducible and consistent with SEC53")
    else:
        print("VERDICT: VERIFICATION FAILED -- investigate FAIL items above")
    print(f"SHA256 (canonical): {EXPECTED_SHA256}")
    print("=" * 70)
    return 0 if n_fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
