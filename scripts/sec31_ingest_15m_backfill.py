"""SEC31b: 15m OHLCV backfill — 10 sym x 4.5y historical extension.

Purpose:
    sec29_ingest_15m.py only covered 6 months (2025-11-16 -> 2026-05-17).
    Phoenix-Scalp v1.0 backtest requires 3y rolling windows (13 windows = ~5y span).
    This script fills the gap: 2021-05-16 -> 2025-11-16 (4.5y historical).

Window:
    START = 2021-05-16 00:00 UTC  (earliest Binance 15m available)
    END   = 2025-11-16 00:00 UTC  (where sec29 starts — no overlap)

Total expected bars:
    ~236,160 bars/sym x 10 sym = ~2.36M bars
    (4.5y x 365d x 24h x 4 bars/h = ~157,680 — actual: 2021-05-16 to 2025-11-16 = 1645d x 96 = 157,920/sym)

Rate limits:
    Binance REST: 1200 req/min weight budget. fetch_ohlcv weight=2.
    PAGE_LIMIT=1000 bars => 0.67s/page safe budget => we use 0.4s sleep (ccxt enableRateLimit handles bursts).
    Sequential per-symbol: no parallel fetch to avoid rate limit.
    Expected: ~160 pages/sym x 10 sym x 0.4s = ~10.7 min + upsert overhead ~20 min total.

Resume:
    Uses first_ts checkpoint: if a symbol already has 15m data before 2025-11-16,
    starts from the earliest existing ts and extends backwards.
    Actually: fetches START..END window, upsert is idempotent — safe to rerun.
    No forward re-fetch (does not touch the 6mo existing data).

Run:
    python scripts/sec31_ingest_15m_backfill.py 2>&1 | Tee-Object logs/sec31_ingest_15m_backfill.log

Log:
    logs/sec31_ingest_15m_backfill.log (append via Tee-Object or redirect)
"""
from __future__ import annotations

import io
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

if __name__ == "__main__":
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    except Exception:
        pass

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import ccxt
import pandas as pd

from price_action.data.store import OHLCVStore

VENUE = "binance"
TF = "15m"
TF_MS = 15 * 60_000  # 900_000 ms

SYMBOLS = [
    "BTC/USDT",
    "ETH/USDT",
    "SOL/USDT",
    "BNB/USDT",
    "ADA/USDT",
    "AVAX/USDT",
    "LINK/USDT",
    "DOT/USDT",
    "DOGE/USDT",
    "XRP/USDT",
]

# Historical window: 4.5y gap that sec29 did NOT fill
# sec29 covered 2025-11-16 -> 2026-05-17
# This covers 2021-05-16 -> 2025-11-16 (exclusive end, no overlap)
START = datetime(2021, 5, 16, tzinfo=timezone.utc)
END = datetime(2025, 11, 16, tzinfo=timezone.utc)

PAGE_LIMIT = 1000
# 0.4s between pages: ~2.5 req/s vs Binance 2 weight/call => well inside 1200 weight/min
SLEEP = 0.4
MAX_RETRIES = 6

# Progress reporting every N pages
PROGRESS_EVERY = 20


def _to_ms(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)


def _fetch_page(exchange: Any, symbol: str, since_ms: int) -> list:
    attempt = 0
    while True:
        try:
            return exchange.fetch_ohlcv(
                symbol, timeframe=TF, since=since_ms, limit=PAGE_LIMIT
            )
        except Exception as exc:
            cls = exc.__class__.__name__.lower()
            transient = any(
                k in cls
                for k in ("ratelimit", "timeout", "ddos", "networkerror", "requesttimeout")
            )
            attempt += 1
            if attempt > MAX_RETRIES or not transient:
                raise
            delay = 2.0 * (2 ** (attempt - 1))  # 2, 4, 8, 16, 32, 64s
            print(
                f"  [backoff] attempt={attempt} delay={delay:.0f}s -- {exc}",
                flush=True,
            )
            time.sleep(delay)


def _to_df(raw: list, symbol: str) -> pd.DataFrame:
    if not raw:
        return pd.DataFrame()
    df = pd.DataFrame(raw, columns=["ts_ms", "open", "high", "low", "close", "volume"])
    df["ts"] = pd.to_datetime(df["ts_ms"], unit="ms", utc=True)
    df["venue"] = VENUE
    df["symbol"] = symbol
    df["timeframe"] = TF
    return df[["venue", "symbol", "timeframe", "ts", "open", "high", "low", "close", "volume"]]


def backfill_symbol(exchange: Any, store: OHLCVStore, symbol: str) -> dict:
    """Fetch + upsert 4.5y historical 15m bars for one symbol.

    Resume logic:
        Check if symbol already has 15m data earlier than END.
        If existing first_ts < START, symbol is already complete — skip.
        Otherwise fetch full START..END window (upsert idempotent).
    """
    since_ms = _to_ms(START)
    until_ms = _to_ms(END)

    # Check existing coverage for this symbol in the historical window
    # SEC-SCALP-DB1: DuckDB internal bug — any aggregate query with ts-filter
    # (parametrized OR literal) raises InternalException. Workaround: split
    # MIN/COUNT into two queries WITHOUT ts filter, do END comparison in Python.
    with store._conn() as con:
        row_min = con.execute(
            "SELECT MIN(ts) FROM ohlcv WHERE venue=? AND symbol=? AND timeframe=?",
            [VENUE, symbol, TF],
        ).fetchone()
        row_total = con.execute(
            "SELECT COUNT(*) FROM ohlcv WHERE venue=? AND symbol=? AND timeframe=?",
            [VENUE, symbol, TF],
        ).fetchone()
    # Count bars strictly before END in Python (cheap: ohlcv per-symbol is bounded)
    existing_first_raw = row_min[0] if row_min and row_min[0] else None
    if existing_first_raw is not None:
        with store._conn() as con:
            all_ts = con.execute(
                "SELECT ts FROM ohlcv WHERE venue=? AND symbol=? AND timeframe=?",
                [VENUE, symbol, TF],
            ).fetchall()
        count_before_end = sum(1 for (t,) in all_ts if t < END)
    else:
        count_before_end = 0
    row = (existing_first_raw, count_before_end)

    existing_first = row[0] if row and row[0] else None
    existing_count_before_end = row[1] if row and row[1] else 0

    expected_bars = int((until_ms - since_ms) / TF_MS) + 1

    if existing_first is not None:
        # Convert to UTC-aware
        if hasattr(existing_first, "tzinfo") and existing_first.tzinfo is None:
            existing_first = existing_first.replace(tzinfo=timezone.utc)
        existing_first_ms = int(existing_first.timestamp() * 1000)

        if existing_first_ms <= since_ms + TF_MS:
            # Already covers the full window — check bar count
            if existing_count_before_end >= int(expected_bars * 0.98):
                print(
                    f"  [SKIP] {symbol}: already has {existing_count_before_end:,} bars "
                    f"(expected ~{expected_bars:,}) up to {END.date()} — skipping.",
                    flush=True,
                )
                return {
                    "symbol": symbol,
                    "rows": 0,
                    "pages": 0,
                    "first_ts": str(existing_first)[:16],
                    "last_ts": None,
                    "skipped": True,
                    "error": None,
                }
        # Partial: resume from the earliest gap
        # We still fetch from START to be safe (idempotent upsert)
        print(
            f"  [resume] {symbol}: existing first={str(existing_first)[:10]}, "
            f"bars_before_end={existing_count_before_end:,} — re-fetching from {START.date()}",
            flush=True,
        )

    total = 0
    pages = 0
    first_ts: Any = None
    last_ts: Any = None
    error = None

    try:
        cur_ms = since_ms
        t_sym_start = time.time()
        while cur_ms < until_ms:
            raw = _fetch_page(exchange, symbol, cur_ms)
            if not raw:
                break

            raw_filt = [r for r in raw if since_ms <= r[0] < until_ms]
            if raw_filt:
                df = _to_df(raw_filt, symbol)
                written = store.upsert(df)
                total += written
                ts_min = df["ts"].min()
                ts_max = df["ts"].max()
                if first_ts is None or ts_min < first_ts:
                    first_ts = ts_min
                if last_ts is None or ts_max > last_ts:
                    last_ts = ts_max

            pages += 1
            last_ms_in_page = int(raw[-1][0])
            next_ms = last_ms_in_page + TF_MS

            if next_ms >= until_ms or len(raw) < PAGE_LIMIT:
                break
            cur_ms = next_ms

            if pages % PROGRESS_EVERY == 0:
                pct = (cur_ms - since_ms) / (until_ms - since_ms) * 100
                elapsed_sym = time.time() - t_sym_start
                remaining_pct = 100.0 - pct
                eta_s = (elapsed_sym / max(pct, 0.01)) * remaining_pct if pct > 0 else 0
                print(
                    f"    ...{symbol} page={pages:>4} ({pct:.1f}%)  "
                    f"rows={total:,}  ETA={eta_s/60:.1f}min",
                    flush=True,
                )

            if SLEEP > 0:
                time.sleep(SLEEP)

    except Exception as exc:
        error = str(exc)
        print(f"  [ERROR] {symbol}: {error}", flush=True)

    return {
        "symbol":   symbol,
        "rows":     total,
        "pages":    pages,
        "first_ts": str(first_ts)[:16] if first_ts else None,
        "last_ts":  str(last_ts)[:16]  if last_ts  else None,
        "skipped":  False,
        "error":    error,
    }


def coverage_summary(store: OHLCVStore) -> None:
    """Print post-backfill coverage matrix for 15m."""
    print("\n--- 15m Coverage Post-Backfill ---", flush=True)
    with store._conn() as con:
        rows = con.execute(
            "SELECT symbol, COUNT(*) as n, MIN(ts) as first, MAX(ts) as last "
            "FROM ohlcv WHERE venue=? AND timeframe=? "
            "GROUP BY symbol ORDER BY symbol",
            [VENUE, TF],
        ).fetchall()

    expected_5y = int((5 * 365 * 24 * 4))  # ~175,200 bars per sym for 5y
    print(f"{'Symbol':<12} {'bars':>8} {'first':>12} {'last':>12} {'cov_5y':>8} {'status':>10}", flush=True)
    print("-" * 70, flush=True)
    for sym, n, first, last in rows:
        cov = n / expected_5y * 100
        status = "OK" if cov >= 95 else ("WARN" if cov >= 80 else "KILL")
        print(
            f"  {sym:<12} {n:>8,}  {str(first)[:10]:>12}  {str(last)[:10]:>12}  "
            f"{cov:>6.1f}%  {status:>10}",
            flush=True,
        )


def main() -> None:
    span_days = (END - START).days
    expected_per_sym = span_days * 24 * 4  # 15m bars per day = 96
    expected_total = expected_per_sym * len(SYMBOLS)
    pages_per_sym = -(-expected_per_sym // PAGE_LIMIT)  # ceil division
    est_min = pages_per_sym * len(SYMBOLS) * (SLEEP + 0.05) / 60

    print(f"SEC31b: 15m backfill (historical extension)", flush=True)
    print(f"  Window : {START.date()} -> {END.date()} ({span_days} days = {span_days/365:.1f}y)", flush=True)
    print(f"  Symbols: {len(SYMBOLS)}", flush=True)
    print(f"  Expected: ~{expected_per_sym:,} bars/sym x {len(SYMBOLS)} = ~{expected_total:,} total", flush=True)
    print(f"  Pages  : ~{pages_per_sym} pages/sym x {len(SYMBOLS)} sym", flush=True)
    print(f"  Est.   : ~{est_min:.0f} min ({est_min/60:.1f}h) at {SLEEP}s/page", flush=True)
    print(f"  Rate   : sequential fetch, ccxt enableRateLimit=True, {SLEEP}s inter-page sleep", flush=True)
    print(f"  Idempotent: YES (upsert, skip if already >=98% coverage)", flush=True)
    print("=" * 70, flush=True)

    t0 = time.time()
    # DQ-04 FIX (SEC54.5): futures endpoint
    ex = ccxt.binance({"enableRateLimit": True, "options": {"defaultType": "future"}})
    store = OHLCVStore()

    results = []
    for sym in SYMBOLS:
        t1 = time.time()
        print(f"\n>> {sym}", flush=True)
        r = backfill_symbol(ex, store, sym)
        elapsed = time.time() - t1
        r["elapsed_s"] = round(elapsed, 1)
        status = "SKIP" if r.get("skipped") else ("FAIL" if r["error"] else "OK")
        print(
            f"   [{status}] rows={r['rows']:>8,}  pages={r['pages']:>4}  "
            f"range={r['first_ts']} -> {r['last_ts']}  ({elapsed:.0f}s)",
            flush=True,
        )
        results.append(r)

    elapsed_all = time.time() - t0
    total_rows = sum(r["rows"] for r in results)
    errors = [r["symbol"] for r in results if r["error"]]
    skipped = [r["symbol"] for r in results if r.get("skipped")]

    print("\n" + "=" * 70, flush=True)
    print(
        f"DONE  total_new_rows={total_rows:,}  elapsed={elapsed_all/60:.1f} min  "
        f"errors={len(errors)}  skipped={len(skipped)}",
        flush=True,
    )
    if errors:
        print(f"  FAILED: {errors}", flush=True)
    if skipped:
        print(f"  SKIPPED (already complete): {skipped}", flush=True)

    print("\nSummary table:", flush=True)
    print(f"{'Symbol':<15} {'new_rows':>10} {'pages':>6} {'first':>12} {'last':>12} {'s':>6}", flush=True)
    print("-" * 65, flush=True)
    for r in results:
        print(
            f"  {r['symbol']:<15} {r['rows']:>10,} {r['pages']:>6} "
            f"{str(r['first_ts']):>12} {str(r['last_ts']):>12} {r['elapsed_s']:>6.0f}",
            flush=True,
        )

    # Post-backfill coverage summary
    coverage_summary(store)

    print(f"\nLog: logs/sec31_ingest_15m_backfill.log", flush=True)
    print(
        f"Coverage check: python scripts/sec31_coverage_check.py",
        flush=True,
    )


if __name__ == "__main__":
    main()
