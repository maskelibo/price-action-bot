"""sec13.3 - Ingest top universe expansion candidates (5y * 1d OHLCV).

Pre-registered 9 yeni sembol (vol+listing filtreleri uygulanmis hali — tam liste
icin reports/lab/sec13_3_top25_universe.md PROSEDUR bolumune bkz):

  Tier-1 (perp 30d avg vol >= $100M):  FIL, AAVE, NEAR
  Tier-2 (perp 30d avg vol >= $50M):   ENJ, BCH, DASH, LTC, AXS, TRX

Brief'te 14 sembol istendi ama 14 aday icinde sadece 2 tanesi (FIL, AAVE) sert
$100M perp vol esigini geciyor; geri kalanlar ya post-2021 listed (APT, ARB, OP,
SUI) ya da $100M altinda kaliyor. 50M tabanina inerek 9 sembol toplandi (tam
gerekce: reports/lab/sec13_3_top25_universe.md).

Kaynak: Binance public spot API (1d klines).
Hedef: data/market.duckdb -> ohlcv tablosu (mevcut 11 sym ile ayni schema).
Tarih: 2021-05-15 -> 2026-05-15 (5 yil).
Beklenen bar: ~1825 bar/sym * 9 sym = ~16400 bar.
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

os.environ["PA_LOG_QUIET"] = "1"

import duckdb
import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[1]

# Pre-registered universe expansion (9 sym — bkz docstring gerekce)
NEW_SYMBOLS = [
    # Tier-1 perp >=$100M
    ("FIL/USDT", "FILUSDT"),
    ("AAVE/USDT", "AAVEUSDT"),
    ("NEAR/USDT", "NEARUSDT"),
    # Tier-2 perp >=$50M (5y listed gercegi)
    ("ENJ/USDT", "ENJUSDT"),
    ("BCH/USDT", "BCHUSDT"),
    ("DASH/USDT", "DASHUSDT"),
    ("LTC/USDT", "LTCUSDT"),
    ("AXS/USDT", "AXSUSDT"),
    ("TRX/USDT", "TRXUSDT"),
]

START_TS_MS = int(pd.Timestamp("2021-05-15", tz="UTC").timestamp() * 1000)
END_TS_MS = int(pd.Timestamp("2026-05-15", tz="UTC").timestamp() * 1000)


def fetch_klines(binance_sym: str, interval: str, start_ms: int, end_ms: int) -> pd.DataFrame:
    """Binance spot klines fetch (paginated, 1000 bar/req)."""
    rows: list[list] = []
    cur = start_ms
    while cur < end_ms:
        try:
            r = requests.get(
                "https://api.binance.com/api/v3/klines",
                params={
                    "symbol": binance_sym,
                    "interval": interval,
                    "startTime": cur,
                    "endTime": end_ms,
                    "limit": 1000,
                },
                timeout=15,
            )
            r.raise_for_status()
            batch = r.json()
        except Exception as e:
            print(f"    [WARN] {binance_sym} fetch err {e}, retry 3s...")
            time.sleep(3)
            continue
        if not batch:
            break
        rows.extend(batch)
        last_ts = batch[-1][0]
        if last_ts <= cur:
            break
        cur = last_ts + 1
        time.sleep(0.25)
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows, columns=[
        "open_time", "open", "high", "low", "close", "volume",
        "close_time", "quote_vol", "n_trades", "taker_buy_base",
        "taker_buy_quote", "ignore",
    ])
    df["ts"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
    for c in ["open", "high", "low", "close", "volume"]:
        df[c] = pd.to_numeric(df[c])
    df = df[["ts", "open", "high", "low", "close", "volume"]]
    df = df.drop_duplicates(subset="ts").sort_values("ts").reset_index(drop=True)
    return df


def main() -> None:
    db_path = ROOT / "data" / "market.duckdb"
    print(f"Ingest baslangic: {pd.Timestamp.utcnow().isoformat()}")
    print(f"DB: {db_path}")
    print(f"Sembol sayisi: {len(NEW_SYMBOLS)}")
    print(f"Tarih: {pd.Timestamp(START_TS_MS, unit='ms', tz='UTC').date()} -> "
          f"{pd.Timestamp(END_TS_MS, unit='ms', tz='UTC').date()}")

    con = duckdb.connect(str(db_path))

    # Mevcut sembolleri kontrol et (idempotency)
    existing = {r[0] for r in con.execute(
        "SELECT DISTINCT symbol FROM ohlcv WHERE venue=? AND timeframe=?",
        ["binance", "1d"]
    ).fetchall()}
    print(f"\nMevcut 1d sembolu: {sorted(existing)}")

    t0_total = time.time()
    for ccxt_sym, bin_sym in NEW_SYMBOLS:
        if ccxt_sym in existing:
            print(f"\n  [SKIP] {ccxt_sym} zaten DB'de")
            continue
        print(f"\n  {ccxt_sym} ({bin_sym}) ingest...", end=" ", flush=True)
        t0 = time.time()
        df = fetch_klines(bin_sym, "1d", START_TS_MS, END_TS_MS)
        if df.empty:
            print("BOS — atlandi")
            continue
        df["venue"] = "binance"
        df["symbol"] = ccxt_sym
        df["timeframe"] = "1d"
        # Match schema: venue, symbol, timeframe, ts, open, high, low, close, volume
        df = df[["venue", "symbol", "timeframe", "ts", "open", "high", "low", "close", "volume"]]
        # INSERT OR IGNORE (PK = venue, symbol, timeframe, ts)
        con.execute("""
            CREATE TEMP TABLE _ingest_buf AS SELECT * FROM df WHERE 1=0
        """)
        con.register("df_view", df)
        con.execute("INSERT INTO _ingest_buf SELECT * FROM df_view")
        n_inserted = con.execute("""
            INSERT INTO ohlcv
            SELECT * FROM _ingest_buf
            WHERE NOT EXISTS (
                SELECT 1 FROM ohlcv o
                WHERE o.venue=_ingest_buf.venue
                  AND o.symbol=_ingest_buf.symbol
                  AND o.timeframe=_ingest_buf.timeframe
                  AND o.ts=_ingest_buf.ts
            )
        """).fetchall()
        con.execute("DROP TABLE _ingest_buf")
        con.unregister("df_view")
        n_db = con.execute(
            "SELECT COUNT(*) FROM ohlcv WHERE venue=? AND symbol=? AND timeframe=?",
            ["binance", ccxt_sym, "1d"]).fetchone()[0]
        print(f"fetched n={len(df)}, DB total n={n_db}  ({time.time()-t0:.1f}s)")

    # Final summary
    print(f"\n{'='*60}")
    print("Final 1d coverage:")
    rows = con.execute("""
        SELECT symbol, COUNT(*) AS n, MIN(ts) AS first_ts, MAX(ts) AS last_ts
        FROM ohlcv WHERE venue='binance' AND timeframe='1d'
        GROUP BY symbol ORDER BY symbol
    """).fetchall()
    for sym, n, st, en in rows:
        marker = " (NEW)" if sym in {s[0] for s in NEW_SYMBOLS} else ""
        print(f"  {sym:12s}  n={n:5d}  {pd.Timestamp(st).date()} -> {pd.Timestamp(en).date()}{marker}")
    con.close()
    print(f"\nIngest done ({time.time()-t0_total:.1f}s total)")


if __name__ == "__main__":
    main()
