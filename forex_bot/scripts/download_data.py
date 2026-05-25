"""Bulk Dukascopy downloader for forex pairs.

Usage:
    python -m forex_bot.scripts.download_data --pair EURUSD --start 2021-01-01 --end 2026-01-01 --tf 15m
    python -m forex_bot.scripts.download_data --all --start 2022-01-01 --end 2026-01-01 --tf 15m
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone

from ..data.dukascopy import DukascopyClient, backfill_pair
from ..data.store import OHLCVStore
from ..settings import DUCKDB_PATH, PAIRS, PARQUET_DIR


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--pair", default=None, help="single pair (e.g. EURUSD)")
    p.add_argument("--all", action="store_true", help="download all 10 pairs")
    p.add_argument("--start", required=True, help="YYYY-MM-DD UTC")
    p.add_argument("--end", required=True, help="YYYY-MM-DD UTC")
    p.add_argument("--tf", default="15m")
    args = p.parse_args(argv)

    pairs = PAIRS if args.all else [args.pair] if args.pair else []
    if not pairs:
        print("specify --pair or --all", file=sys.stderr)
        return 2

    start = datetime.fromisoformat(args.start).replace(tzinfo=timezone.utc)
    end = datetime.fromisoformat(args.end).replace(tzinfo=timezone.utc)
    store = OHLCVStore(DUCKDB_PATH, PARQUET_DIR)
    client = DukascopyClient()

    def progress(pair, done, total):
        print(f"[{pair}] {done}/{total} hours", flush=True)

    for pair in pairs:
        n = backfill_pair(pair, start, end, store, timeframe=args.tf, client=client, progress_cb=progress)
        print(f"[{pair}] wrote {n} bars")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
