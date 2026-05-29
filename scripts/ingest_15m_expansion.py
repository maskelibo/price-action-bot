"""15m OHLCV expansion backfill — ISOLATED DB (symbol-universe expansion backtest).

GÜVENLİK: market.duckdb / market_ingest.duckdb'ye DOKUNMAZ. Tamamen ayrı
dosyaya yazar: data/market_expansion_15m.duckdb. Snapshot döngüsü ve canlı
daemon'lardan tamamen izole. Shared parquet tree'ye de DOKUNMAZ
(also_parquet=False).

Semboller: ZEC, SUI, NEAR, FIL, XLM (USDM perp, Binance, bare "X/USDT" form —
canlı 15m bot semantiği ile birebir).

Davranış:
    - Binance USDM Futures (defaultType=future), bare symbol form.
    - Mümkün olduğunca geriye backfill (paginate, forward iteration).
    - 429 → exponential backoff (mevcut _fetch_with_retry reuse).
    - Forward-fill / clip / winsorize YOK. Ham veri korunur.
    - Idempotent upsert (DELETE+INSERT PK pattern).
"""
from __future__ import annotations

import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import pandas as pd  # noqa: E402

from price_action.data.ingest_ccxt import (  # noqa: E402
    _build_ccxt,
    _fetch_with_retry,
    _ohlcv_to_df,
    _TF_MS,
)
from price_action.data.store import OHLCVStore  # noqa: E402

VENUE = "binance"
TF = "15m"
SYMBOLS = ["ZEC/USDT", "SUI/USDT", "NEAR/USDT", "FIL/USDT", "XLM/USDT"]
DB_PATH = ROOT / "data" / "market_expansion_15m.duckdb"
YEARS_BACK = 6  # exchange listing'i kadar geriye iner; fazlası boş döner, zararsız
PAGE_LIMIT = 1000


def backfill_symbol(exchange, store: OHLCVStore, symbol: str) -> dict:
    start = datetime.now(timezone.utc) - timedelta(days=365 * YEARS_BACK)
    since_ms = int(start.timestamp() * 1000)
    total = 0
    pages = 0
    first_ts = None
    last_ts = None
    t0 = time.perf_counter()
    while True:
        raw = _fetch_with_retry(exchange, symbol, TF, since_ms, limit=PAGE_LIMIT)
        if not raw:
            break
        df = _ohlcv_to_df(raw, venue=VENUE, symbol=symbol, timeframe=TF)
        # ISOLATED: also_parquet=False → shared parquet tree'ye dokunma
        written = store.upsert(df, also_parquet=False)
        total += written
        pages += 1
        if first_ts is None:
            first_ts = raw[0][0]
        last_ts = raw[-1][0]
        next_ms = int(raw[-1][0]) + _TF_MS[TF]
        if len(raw) < PAGE_LIMIT:
            break
        since_ms = next_ms
        if pages % 20 == 0:
            print(f"  [{symbol}] {pages} pages, {total} rows, "
                  f"at {datetime.fromtimestamp(last_ts/1000, timezone.utc)}", flush=True)
    elapsed = time.perf_counter() - t0
    return {
        "symbol": symbol,
        "rows": total,
        "pages": pages,
        "first": datetime.fromtimestamp(first_ts / 1000, timezone.utc) if first_ts else None,
        "last": datetime.fromtimestamp(last_ts / 1000, timezone.utc) if last_ts else None,
        "elapsed_s": round(elapsed, 1),
    }


def main() -> None:
    print(f"[EXPANSION-15M] target DB: {DB_PATH}", flush=True)
    print(f"[EXPANSION-15M] symbols: {SYMBOLS}", flush=True)
    # ISOLATED store — ayrı dosya, force_write=False (canlı env'den bağımsız zaten)
    store = OHLCVStore(path=DB_PATH)
    exchange = _build_ccxt(VENUE, market_type="future")
    results = []
    for sym in SYMBOLS:
        print(f"[EXPANSION-15M] >>> {sym}", flush=True)
        r = backfill_symbol(exchange, store, sym)
        print(f"[EXPANSION-15M] DONE {sym}: {r['rows']} rows, "
              f"{r['first']} -> {r['last']} ({r['elapsed_s']}s)", flush=True)
        results.append(r)
    print("[EXPANSION-15M] ALL DONE", flush=True)
    for r in results:
        print(r, flush=True)


if __name__ == "__main__":
    main()
