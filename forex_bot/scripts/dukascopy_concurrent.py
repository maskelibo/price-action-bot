"""Concurrent Dukascopy downloader — proof-of-concept real tick data ingestion.

For a single pair, downloads N months of hourly .bi5 files concurrently (10 workers),
parses ticks → resamples to 15m bars → writes to OHLCVStore.

Demonstrates the real-data pipeline works end-to-end. Full 4-5y × 10 pair run
takes 1-3 hours wall time (~350k HTTP requests) — best done off-hours.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone

import pandas as pd

from ..data.dukascopy import DukascopyClient, bars_from_ticks
from ..data.store import OHLCVStore
from ..settings import DUCKDB_PATH, PARQUET_DIR


def fetch_hour_safe(client: DukascopyClient, pair: str, hour: datetime) -> pd.DataFrame:
    try:
        raw = client.download_hour(pair, hour)
        if raw:
            return client.parse_hour(pair, hour, raw)
    except Exception:
        pass
    return pd.DataFrame()


def is_weekend_utc(h: datetime) -> bool:
    return h.weekday() == 5 or (h.weekday() == 6 and h.hour < 21) or (h.weekday() == 4 and h.hour >= 21)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--pair", default="EURUSD")
    p.add_argument("--start", default="2024-01-01")
    p.add_argument("--end", default="2024-04-01")
    p.add_argument("--workers", type=int, default=10)
    p.add_argument("--cache-only", action="store_true",
                   help="download .bi5 to cache only; skip DuckDB write (avoids multi-process DB lock)")
    args = p.parse_args()

    start = datetime.fromisoformat(args.start).replace(tzinfo=timezone.utc)
    end = datetime.fromisoformat(args.end).replace(tzinfo=timezone.utc)
    client = DukascopyClient()
    store = None if args.cache_only else OHLCVStore(DUCKDB_PATH, PARQUET_DIR)

    hours = []
    cur = start.replace(minute=0, second=0, microsecond=0)
    while cur < end:
        if not is_weekend_utc(cur):
            hours.append(cur)
        cur += timedelta(hours=1)

    print(f"[{args.pair}] {len(hours)} trading hours to fetch ({args.start} -> {args.end})")
    print(f"workers: {args.workers}")

    all_ticks = []
    done = 0
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(fetch_hour_safe, client, args.pair, h): h for h in hours}
        for fut in as_completed(futs):
            df = fut.result()
            done += 1
            if not df.empty:
                all_ticks.append(df)
            if done % 100 == 0:
                print(f"  {done}/{len(hours)} hours done, ticks gathered: {sum(len(d) for d in all_ticks)}")

    if args.cache_only:
        print(f"\n[{args.pair}] cache-only mode: {len(all_ticks)} non-empty hour files cached. DB write skipped.")
        return
    if not all_ticks:
        print("NO TICKS")
        return
    df_all = pd.concat(all_ticks, ignore_index=True)
    print(f"\n[{args.pair}] total ticks: {len(df_all):,}")
    bars = bars_from_ticks(df_all, timeframe="15m", pair=args.pair)
    bars = bars.reset_index()
    bars["pair"] = args.pair
    bars["timeframe"] = "15m"
    print(f"[{args.pair}] 15m bars: {len(bars):,}")
    print(f"[{args.pair}] price range: {bars['low'].min():.5f} -> {bars['high'].max():.5f}")
    print(f"[{args.pair}] sample first bar: {bars.iloc[0].to_dict()}")
    n = store.write_ohlcv(bars[["pair", "timeframe", "ts", "open", "high", "low", "close", "tick_volume", "spread_pips"]])
    print(f"[{args.pair}] wrote {n} bars to DuckDB + Parquet")


if __name__ == "__main__":
    main()
