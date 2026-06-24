"""Backfill 5-year historical OHLCV data (2021-05 → 2023-05 gap).

Targets 10 core symbols on Binance, timeframes 1d and 1w.
Idempotent: existing rows are preserved via upsert (delete+insert on PK).
Symbols that didn't exist on Binance before 2021-05 start from their
earliest available date; failures are logged and skipped cleanly.
"""
from __future__ import annotations

import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

# Make src importable when running as script
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import ccxt
import pandas as pd

from price_action.data.store import OHLCVStore
from price_action.logging_config import logger

# ── Config ────────────────────────────────────────────────────────────────────

VENUE = "binance"

# 10 target symbols + known earliest Binance listing dates
# We start from 2021-05-01 or listing date, whichever is later
SYMBOLS_EARLIEST: dict[str, datetime] = {
    "BTC/USDT":  datetime(2017, 8, 17, tzinfo=timezone.utc),
    "ETH/USDT":  datetime(2017, 8, 17, tzinfo=timezone.utc),
    "XRP/USDT":  datetime(2018, 5, 4,  tzinfo=timezone.utc),
    "BNB/USDT":  datetime(2017, 11, 6, tzinfo=timezone.utc),
    "ADA/USDT":  datetime(2018, 4, 17, tzinfo=timezone.utc),
    "DOGE/USDT": datetime(2019, 7, 5,  tzinfo=timezone.utc),
    "LINK/USDT": datetime(2019, 1, 16, tzinfo=timezone.utc),
    "MATIC/USDT":datetime(2019, 4, 26, tzinfo=timezone.utc),
    "DOT/USDT":  datetime(2020, 8, 18, tzinfo=timezone.utc),
    "SOL/USDT":  datetime(2020, 8, 11, tzinfo=timezone.utc),
    "AVAX/USDT": datetime(2020, 9, 22, tzinfo=timezone.utc),
}

# Gap window: we want data from 5y ago up to (but not past) current DB start
BACKFILL_START = datetime(2021, 5, 1, tzinfo=timezone.utc)  # 5y target start
# We'll fetch up to 2023-05-10 (current DB earliest) to cover the gap
BACKFILL_END   = datetime(2023, 5, 10, tzinfo=timezone.utc)

TIMEFRAMES = ["1d", "1w"]

_TF_MS: dict[str, int] = {
    "1d": 24 * 60 * 60_000,
    "1w": 7 * 24 * 60 * 60_000,
}

PAGE_LIMIT = 1000
SLEEP_BETWEEN_PAGES = 0.3  # seconds — respect rate limits
MAX_RETRIES = 5


# ── Helpers ───────────────────────────────────────────────────────────────────

def _to_ms(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)


def _from_ms(ms: int) -> datetime:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc)


def _fetch_page(
    exchange: Any,
    symbol: str,
    tf: str,
    since_ms: int,
    limit: int = PAGE_LIMIT,
) -> list[list[Any]]:
    attempt = 0
    while True:
        try:
            return exchange.fetch_ohlcv(symbol, timeframe=tf, since=since_ms, limit=limit)
        except Exception as exc:
            cls = exc.__class__.__name__.lower()
            transient = "ratelimit" in cls or "timeout" in cls or "ddos" in cls or "networkerror" in cls
            attempt += 1
            if attempt > MAX_RETRIES or not transient:
                raise
            delay = 1.0 * (2 ** (attempt - 1))
            print(f"  [backoff] {symbol} {tf} attempt={attempt} delay={delay:.1f}s — {exc}")
            time.sleep(delay)


def _to_df(raw: list[list[Any]], venue: str, symbol: str, tf: str) -> pd.DataFrame:
    if not raw:
        return pd.DataFrame(columns=["venue", "symbol", "timeframe", "ts", "open", "high", "low", "close", "volume"])
    df = pd.DataFrame(raw, columns=["ts_ms", "open", "high", "low", "close", "volume"])
    df["ts"] = pd.to_datetime(df["ts_ms"], unit="ms", utc=True)
    df["venue"] = venue
    df["symbol"] = symbol
    df["timeframe"] = tf
    return df[["venue", "symbol", "timeframe", "ts", "open", "high", "low", "close", "volume"]]


def backfill_symbol(
    exchange: Any,
    store: OHLCVStore,
    symbol: str,
    tf: str,
    since: datetime,
    until: datetime,
) -> dict[str, Any]:
    """Fetch [since, until) for symbol/tf and upsert into store.

    Returns summary dict with rows_written, first_ts, last_ts, error.
    """
    tf_ms = _TF_MS[tf]
    since_ms = _to_ms(since)
    until_ms = _to_ms(until)

    total_rows = 0
    all_first_ts = None
    all_last_ts = None
    pages = 0
    error = None

    try:
        cur_ms = since_ms
        while cur_ms < until_ms:
            raw = _fetch_page(exchange, symbol, tf, cur_ms)
            if not raw:
                break

            # Filter to only rows within [since_ms, until_ms)
            raw_filtered = [r for r in raw if since_ms <= r[0] < until_ms]
            if raw_filtered:
                df = _to_df(raw_filtered, VENUE, symbol, tf)
                written = store.upsert(df)
                total_rows += written
                ts_values = df["ts"]
                if all_first_ts is None or ts_values.min() < all_first_ts:
                    all_first_ts = ts_values.min()
                if all_last_ts is None or ts_values.max() > all_last_ts:
                    all_last_ts = ts_values.max()

            pages += 1
            last_ms_in_page = int(raw[-1][0])
            next_ms = last_ms_in_page + tf_ms

            # Stop if we've passed the target window or if ccxt returned fewer than limit rows
            if next_ms >= until_ms:
                break
            if len(raw) < PAGE_LIMIT:
                break

            cur_ms = next_ms
            if SLEEP_BETWEEN_PAGES > 0:
                time.sleep(SLEEP_BETWEEN_PAGES)

    except Exception as exc:
        error = str(exc)
        print(f"  [ERROR] {symbol} {tf}: {error}")

    return {
        "symbol": symbol,
        "timeframe": tf,
        "rows_written": total_rows,
        "pages": pages,
        "first_ts": str(all_first_ts)[:10] if all_first_ts is not None else None,
        "last_ts": str(all_last_ts)[:10] if all_last_ts is not None else None,
        "error": error,
    }


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    print("=" * 70)
    print("BACKFILL 5Y -- 2021-05-01 -> 2023-05-10 (gap fill)")
    print(f"Venue: {VENUE}  |  Timeframes: {TIMEFRAMES}")
    print(f"Symbols: {len(SYMBOLS_EARLIEST)}")
    print("=" * 70)
    print()

    # DQ-04 FIX (SEC54.5): futures endpoint — perp OHLCV, doğru contractSize/tickSize
    exchange = ccxt.binance({"enableRateLimit": True, "options": {"defaultType": "future"}})
    store = OHLCVStore()

    results: list[dict] = []

    for symbol, listing_date in SYMBOLS_EARLIEST.items():
        # Actual start: max(BACKFILL_START, listing_date)
        effective_start = max(BACKFILL_START, listing_date)

        for tf in TIMEFRAMES:
            print(f"  >> {symbol:15s} {tf:4s}  [{effective_start.date()} -> {BACKFILL_END.date()}]")
            result = backfill_symbol(
                exchange=exchange,
                store=store,
                symbol=symbol,
                tf=tf,
                since=effective_start,
                until=BACKFILL_END,
            )
            results.append(result)
            status = "OK" if result["error"] is None else "FAIL"
            print(f"     {status}  bars_written={result['rows_written']}  "
                  f"range={result['first_ts']} → {result['last_ts']}  "
                  f"pages={result['pages']}")
            if result["error"]:
                print(f"     ERROR: {result['error'][:120]}")

    # ── Final DB verification ─────────────────────────────────────────────────
    print()
    print("=" * 70)
    print("POST-BACKFILL VERIFICATION")
    print("=" * 70)

    # Use the store's pooled connection for read (avoids DuckDB re-open conflict)
    import duckdb
    from price_action.settings import get_settings
    from price_action.data.store import _get_pooled_connection
    s = get_settings()
    con, lock = _get_pooled_connection(str(s.duckdb_path))
    with lock:
        rows = con.execute("""
            SELECT symbol, timeframe, COUNT(*) as bars,
                   MIN(ts) as first_bar, MAX(ts) as last_bar
            FROM ohlcv
            WHERE timeframe IN ('1d', '1w')
            GROUP BY symbol, timeframe
            ORDER BY symbol, timeframe
        """).fetchall()

    print()
    print(f"{'SYMBOL':<15} {'TF':<5} {'BARS':>6} {'FIRST':>12} {'LAST':>12}  {'COVERS_2022?'}")
    print("-" * 70)

    bear_2022_start = pd.Timestamp("2022-01-01", tz="UTC")
    bear_2022_end   = pd.Timestamp("2022-12-31", tz="UTC")

    symbols_5y: list[str] = []
    symbols_short: list[str] = []
    target_start = pd.Timestamp("2021-05-01", tz="UTC")

    for row in rows:
        sym, tf, bars, first, last = row
        first_ts = pd.Timestamp(first)
        last_ts  = pd.Timestamp(last)
        covers_2022 = (first_ts <= bear_2022_start and last_ts >= bear_2022_end)
        has_5y = (first_ts <= target_start + timedelta(days=60))  # within 2 months tolerance
        mark = "YES" if covers_2022 else " NO"
        print(f"{sym:<15} {tf:<5} {bars:>6} {str(first_ts)[:10]:>12} {str(last_ts)[:10]:>12}  {mark}")
        if tf == "1d":
            if has_5y:
                symbols_5y.append(sym)
            else:
                symbols_short.append(sym)

    with lock:
        total = con.execute("SELECT COUNT(*) FROM ohlcv WHERE timeframe IN ('1d','1w')").fetchone()[0]

    print()
    print(f"TOTAL bars (1d+1w): {total:,}")
    print()
    print(f"Symbols with ~5y data (1d): {sorted(set(symbols_5y))}")
    print(f"Symbols with shorter data : {sorted(set(symbols_short))}")

    # Backfill summary
    total_written = sum(r["rows_written"] for r in results)
    failed = [r for r in results if r["error"]]
    print()
    print(f"Backfill written this run: {total_written:,} new bars")
    print(f"Failures: {len(failed)}")
    for f in failed:
        print(f"  {f['symbol']} {f['timeframe']}: {f['error'][:100]}")


if __name__ == "__main__":
    main()
