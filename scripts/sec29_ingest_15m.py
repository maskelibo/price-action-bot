"""SEC29: 15m OHLCV ingest — 10 sym × 6 ay (2025-11-16 → 2026-05-16).

~17,280 bar/sym × 10 sym = ~172k bar.
Time: ~3-5 dk.
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
TF = "15m"
TF_MS = 15 * 60_000

SYMBOLS = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT",
           "ADA/USDT", "AVAX/USDT", "LINK/USDT", "DOT/USDT",
           "DOGE/USDT", "XRP/USDT"]

START = datetime(2025, 11, 16, tzinfo=timezone.utc)
END = datetime(2026, 5, 17, tzinfo=timezone.utc)  # 6 ay

PAGE_LIMIT = 1000
SLEEP = 0.2
MAX_RETRIES = 5


def _to_ms(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)


def _fetch_page(exchange: Any, symbol: str, since_ms: int) -> list:
    attempt = 0
    while True:
        try:
            return exchange.fetch_ohlcv(symbol, timeframe=TF, since=since_ms, limit=PAGE_LIMIT)
        except Exception as exc:
            cls = exc.__class__.__name__.lower()
            transient = "ratelimit" in cls or "timeout" in cls or "ddos" in cls or "networkerror" in cls
            attempt += 1
            if attempt > MAX_RETRIES or not transient:
                raise
            delay = 1.0 * (2 ** (attempt - 1))
            print(f"  [backoff] attempt={attempt} delay={delay:.1f}s — {exc}")
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
    since_ms = _to_ms(START)
    until_ms = _to_ms(END)

    total = 0
    pages = 0
    first_ts = None
    last_ts = None
    error = None

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
    except Exception as exc:
        error = str(exc)
        print(f"  [ERROR] {symbol}: {error}")

    return {
        "symbol": symbol,
        "rows": total,
        "pages": pages,
        "first_ts": str(first_ts)[:16] if first_ts else None,
        "last_ts": str(last_ts)[:16] if last_ts else None,
        "error": error,
    }


def main() -> None:
    print(f"SEC29: 15m ingest — {len(SYMBOLS)} sym x 6mo ({START.date()} - {END.date()})")
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
        print(f"   rows={r['rows']:>6}  pages={r['pages']:>3}  range={r['first_ts']} - {r['last_ts']}  ({elapsed:.1f}s)")
        results.append(r)

    elapsed_all = time.time() - t0
    total_rows = sum(r["rows"] for r in results)
    errors = [r["symbol"] for r in results if r["error"]]
    print()
    print("=" * 70)
    print(f"DONE  total_rows={total_rows:,}  elapsed={elapsed_all/60:.1f} min  errors={len(errors)}")
    if errors:
        print(f"  Failed: {errors}")


if __name__ == "__main__":
    main()
