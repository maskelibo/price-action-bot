"""SEC32: 1m OHLCV ingest — configurable sym x window.

DEFAULT mode (sampling): BTC/USDT + ETH/USDT + SOL/USDT x last 6 months.
  Expected: ~262,980 bars/sym x 3 sym = ~789k total.
  Estimated time: ~3-5 min.

FULL mode (10 sym x 5y): ~26.3M bars, ~88 min. Pass --full to enable.

Rationale for sampling default:
  1m x 10 sym x 5y = 26.3M bars at 0.2s/page x 2630 pages = 88 min wall time.
  Per master plan: if >2h, sample BTC+ETH+SOL x 6mo. 88 min < 2h threshold,
  BUT coverage < 95% check requires full data. Default = sample; --full = production.

Run:
    python scripts/sec32_ingest_1m.py              # 3-sym x 6mo (fast)
    python scripts/sec32_ingest_1m.py --full       # 10-sym x 5y (~88 min)
    python scripts/sec32_ingest_1m.py --sym BTCUSDT --months 12   # custom

Idempotent — OHLCVStore.upsert. Parquet partitioned by (venue, symbol, tf, year, month).
"""
from __future__ import annotations

import argparse
import io
import sys
import time
from datetime import datetime, timedelta, timezone
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

VENUE  = "binance"
TF     = "1m"
TF_MS  = 60_000  # 1 min in ms

ALL_SYMBOLS = [
    "BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT",
    "ADA/USDT", "AVAX/USDT", "LINK/USDT", "DOT/USDT",
    "DOGE/USDT", "XRP/USDT",
]

SAMPLE_SYMBOLS = ["BTC/USDT", "ETH/USDT", "SOL/USDT"]

# 5y anchor
FULL_START = datetime(2021, 5, 16, tzinfo=timezone.utc)
END        = datetime(2026, 5, 17, tzinfo=timezone.utc)

PAGE_LIMIT  = 1000
SLEEP       = 0.2    # seconds between pages
MAX_RETRIES = 5

# Coverage kill threshold (task 5)
COVERAGE_KILL_PCT = 95.0


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


def backfill(exchange: Any, store: OHLCVStore, symbol: str, start: datetime) -> dict:
    """Fetch + upsert 1m bars for one symbol from start -> END. Resumes from checkpoint."""
    since_ms = _to_ms(start)
    until_ms = _to_ms(END)

    # Resume checkpoint
    last = store.last_ts(VENUE, symbol, TF)
    if last is not None:
        resume_ms = _to_ms(last) + TF_MS
        if resume_ms > since_ms:
            since_ms = resume_ms
            print(f"  [resume] {symbol}: from {last.isoformat()[:16]} (checkpoint)")

    total  = 0
    pages  = 0
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

            # Progress dot every 200 pages
            if pages % 200 == 0:
                span_ms = _to_ms(END) - _to_ms(start)
                done_ms = cur_ms - _to_ms(start)
                pct = done_ms / span_ms * 100 if span_ms > 0 else 0
                print(f"    ...page {pages:>4} ({pct:.1f}%)  rows_so_far={total:,}")

    except Exception as exc:
        error = str(exc)
        print(f"  [ERROR] {symbol}: {error}")

    # Coverage check
    expected = int((until_ms - _to_ms(start)) / TF_MS)
    coverage_pct = (total / expected * 100) if expected > 0 else 0.0

    return {
        "symbol":       symbol,
        "rows":         total,
        "pages":        pages,
        "first_ts":     str(first_ts)[:16] if first_ts else None,
        "last_ts":      str(last_ts)[:16]  if last_ts  else None,
        "expected_bars": expected,
        "coverage_pct": round(coverage_pct, 2),
        "kill":         coverage_pct < COVERAGE_KILL_PCT,
        "error":        error,
    }


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="SEC32: 1m OHLCV ingest")
    p.add_argument("--full",   action="store_true", help="10 sym x 5y (default: 3 sym x 6mo)")
    p.add_argument("--sym",    nargs="+",           help="Override symbol list (BTC/USDT format)")
    p.add_argument("--months", type=int, default=6, help="Lookback months for sample mode (default: 6)")
    return p.parse_args()


def main() -> None:
    args = _parse_args()

    if args.sym:
        symbols = args.sym
        start = FULL_START if args.full else (
            datetime.now(timezone.utc) - timedelta(days=int(args.months * 30.44))
        )
    elif args.full:
        symbols = ALL_SYMBOLS
        start   = FULL_START
    else:
        symbols = SAMPLE_SYMBOLS
        start   = datetime.now(timezone.utc) - timedelta(days=int(args.months * 30.44))

    bars_per_sym = int((END - start).total_seconds() / 60)
    total_est    = bars_per_sym * len(symbols)
    pages_per_sym = bars_per_sym / PAGE_LIMIT
    time_est_min  = pages_per_sym * SLEEP * len(symbols) / 60

    mode = "FULL 5y" if args.full else f"SAMPLE {args.months}mo"
    print(f"SEC32: 1m ingest [{mode}] -- {len(symbols)} sym ({start.date()} -> {END.date()})")
    print(f"  Expected: ~{bars_per_sym:,} bars/sym x {len(symbols)} = ~{total_est:,} total")
    print(f"  Est. time: ~{time_est_min:.0f} min")
    print(f"  Kill threshold: coverage < {COVERAGE_KILL_PCT}%")
    print("=" * 70)

    t0 = time.time()
    # DQ-04 FIX (SEC54.5): futures endpoint
    ex = ccxt.binance({"enableRateLimit": True, "options": {"defaultType": "future"}})
    store = OHLCVStore()

    results = []
    for sym in symbols:
        t1 = time.time()
        print(f"\n>> {sym}")
        r = backfill(ex, store, sym, start)
        elapsed = time.time() - t1
        r["elapsed_s"] = round(elapsed, 1)
        kill_flag = " [KILL]" if r["kill"] else ""
        status = "OK" if not r["error"] else "FAIL"
        print(
            f"   [{status}] rows={r['rows']:>8,}  pages={r['pages']:>4}  "
            f"coverage={r['coverage_pct']:.1f}%{kill_flag}  ({elapsed:.1f}s)"
        )
        results.append(r)

    elapsed_all = time.time() - t0
    total_rows  = sum(r["rows"] for r in results)
    errors      = [r["symbol"] for r in results if r["error"]]
    kills       = [r["symbol"] for r in results if r["kill"]]

    print()
    print("=" * 70)
    print(f"DONE  total_rows={total_rows:,}  elapsed={elapsed_all/60:.1f} min  errors={len(errors)}")
    if errors:
        print(f"  Failed:  {errors}")
    if kills:
        print(f"  KILL candidates (coverage < {COVERAGE_KILL_PCT}%): {kills}")
        print("  -> Recommend: drop these sym x 1m from scalp universe")

    print()
    print(f"{'Symbol':<15} {'rows':>10} {'expected':>10} {'cov%':>6} {'kill':>5} {'s':>6}")
    print("-" * 58)
    for r in results:
        kill_str = "YES" if r["kill"] else "no"
        print(
            f"{r['symbol']:<15} {r['rows']:>10,} {r['expected_bars']:>10,} "
            f"{r['coverage_pct']:>6.1f} {kill_str:>5} {r['elapsed_s']:>6.0f}"
        )


if __name__ == "__main__":
    main()
