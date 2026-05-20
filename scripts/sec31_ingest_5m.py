"""SEC31: 5m OHLCV ingest — 10 sym x 5y (2021-05-16 -> 2026-05-17).

Expected bars: ~525,960/sym x 10 sym = ~5.26M total.
Estimated time: ~18-22 min (0.2s/page x 526 pages x 10 sym).

Binance free API supports 5m history to at least 2021-01-01.
Idempotent — OHLCVStore.upsert. Parquet partitioned by (venue, symbol, tf, year, month).

Run:
    python scripts/sec31_ingest_5m.py

Resume: already-ingested pages are skipped automatically (last_ts checkpoint).
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
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    except Exception:
        pass

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import ccxt
import pandas as pd

from price_action.data.store import OHLCVStore

VENUE = "binance"
TF = "5m"
TF_MS = 5 * 60_000

SYMBOLS = [
    "BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT",
    "ADA/USDT", "AVAX/USDT", "LINK/USDT", "DOT/USDT",
    "DOGE/USDT", "XRP/USDT",
]

# 5y window: 2021-05-16 -> 2026-05-17
START = datetime(2021, 5, 16, tzinfo=timezone.utc)
END   = datetime(2026, 5, 17, tzinfo=timezone.utc)

PAGE_LIMIT  = 1000   # Binance max per call
SLEEP       = 0.2    # seconds between pages (ccxt rate-limit handles bursts)
MAX_RETRIES = 5


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
                k in cls for k in ("ratelimit", "timeout", "ddos", "networkerror")
            )
            attempt += 1
            if attempt > MAX_RETRIES or not transient:
                raise
            delay = 1.0 * (2 ** (attempt - 1))
            print(f"  [backoff] attempt={attempt} delay={delay:.1f}s -- {exc}")
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


def backfill(exchange: Any, store: OHLCVStore, symbol: str) -> dict:
    """Fetch + upsert full 5y history for one symbol. Resumes from last_ts checkpoint."""
    since_ms = _to_ms(START)
    until_ms = _to_ms(END)

    # Resume checkpoint: skip already-ingested bars
    last = store.last_ts(VENUE, symbol, TF)
    if last is not None:
        resume_ms = _to_ms(last) + TF_MS
        if resume_ms > since_ms:
            since_ms = resume_ms
            print(f"  [resume] {symbol}: from {last.isoformat()[:16]} (checkpoint)")

    total = 0
    pages = 0
    first_ts = None
    last_ts  = None
    error    = None

    try:
        cur_ms = since_ms
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

            if SLEEP > 0:
                time.sleep(SLEEP)

            # Progress dot every 50 pages (~250k bars)
            if pages % 50 == 0:
                pct = (cur_ms - _to_ms(START)) / (_to_ms(END) - _to_ms(START)) * 100
                print(f"    ...page {pages:>4} ({pct:.1f}%)  rows_so_far={total:,}")

    except Exception as exc:
        error = str(exc)
        print(f"  [ERROR] {symbol}: {error}")

    return {
        "symbol":   symbol,
        "rows":     total,
        "pages":    pages,
        "first_ts": str(first_ts)[:16] if first_ts else None,
        "last_ts":  str(last_ts)[:16]  if last_ts  else None,
        "error":    error,
    }


def main() -> None:
    print(f"SEC31: 5m ingest -- {len(SYMBOLS)} sym x 5y ({START.date()} -> {END.date()})")
    print(f"  Expected: ~525,960 bars/sym x {len(SYMBOLS)} sym = ~5.26M total")
    print(f"  Est. time: ~18-22 min (526 pages/sym x 0.2s x {len(SYMBOLS)} sym)")
    print("=" * 70)
    t0 = time.time()
    # DQ-04 FIX (SEC54.5): futures endpoint
    ex = ccxt.binance({"enableRateLimit": True, "options": {"defaultType": "future"}})
    store = OHLCVStore()

    results = []
    for sym in SYMBOLS:
        t1 = time.time()
        print(f"\n>> {sym}")
        r = backfill(ex, store, sym)
        elapsed = time.time() - t1
        r["elapsed_s"] = round(elapsed, 1)
        status = "OK" if not r["error"] else "FAIL"
        print(
            f"   [{status}] rows={r['rows']:>8,}  pages={r['pages']:>4}  "
            f"range={r['first_ts']} -> {r['last_ts']}  ({elapsed:.1f}s)"
        )
        results.append(r)

    elapsed_all = time.time() - t0
    total_rows = sum(r["rows"] for r in results)
    errors = [r["symbol"] for r in results if r["error"]]

    print()
    print("=" * 70)
    print(f"DONE  total_rows={total_rows:,}  elapsed={elapsed_all/60:.1f} min  errors={len(errors)}")
    if errors:
        print(f"  Failed: {errors}")

    # Summary table
    print()
    print(f"{'Symbol':<15} {'rows':>10} {'pages':>6} {'first':>16} {'last':>16} {'s':>6}")
    print("-" * 75)
    for r in results:
        print(
            f"{r['symbol']:<15} {r['rows']:>10,} {r['pages']:>6} "
            f"{str(r['first_ts']):>16} {str(r['last_ts']):>16} {r['elapsed_s']:>6.0f}"
        )


if __name__ == "__main__":
    main()
