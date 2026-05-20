"""Quick incremental 1d ingest for TOP_11 Phoenix pool — fix 9-day data gap."""
from __future__ import annotations
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import ccxt
import pandas as pd
import duckdb

# TOP_11 production pool — backfill_5y.py listesi
SYMBOLS = [
    "BTC/USDT", "ETH/USDT", "XRP/USDT", "BNB/USDT", "ADA/USDT",
    "DOGE/USDT", "LINK/USDT", "MATIC/USDT", "DOT/USDT", "SOL/USDT", "AVAX/USDT",
]

VENUE = "binance"
TF = "1d"
DAYS_BACK = 15  # son 15 gün, gap 9g (idempotent overwrite)

DB_PATH = ROOT / "data" / "market.duckdb"


def main() -> int:
    ex = ccxt.binance({"enableRateLimit": True, "options": {"defaultType": "spot"}})
    since = datetime.now(timezone.utc) - timedelta(days=DAYS_BACK)
    since_ms = int(since.timestamp() * 1000)

    con = duckdb.connect(str(DB_PATH))
    # ensure ohlcv schema
    cols = [c[1] for c in con.execute("PRAGMA table_info('ohlcv')").fetchall()]
    print(f"ohlcv columns: {cols}")

    total_new = 0
    for sym in SYMBOLS:
        try:
            print(f"[{sym}] fetching since {since.isoformat()}...", flush=True)
            bars = ex.fetch_ohlcv(sym, TF, since=since_ms, limit=50)
            if not bars:
                print(f"  -> 0 bars")
                continue
            df = pd.DataFrame(bars, columns=["ts_ms", "open", "high", "low", "close", "volume"])
            df["ts"] = pd.to_datetime(df["ts_ms"], unit="ms", utc=True)
            df["symbol"] = sym
            df["venue"] = VENUE
            df["timeframe"] = TF
            df = df[["venue", "symbol", "timeframe", "ts", "open", "high", "low", "close", "volume"]]

            # idempotent upsert: delete + insert by PK (venue, symbol, timeframe, ts)
            ts_min = df["ts"].min().isoformat()
            ts_max = df["ts"].max().isoformat()
            con.execute(
                "DELETE FROM ohlcv WHERE venue=? AND symbol=? AND timeframe=? AND ts BETWEEN ? AND ?",
                [VENUE, sym, TF, ts_min, ts_max],
            )
            con.register("df_tmp", df)
            con.execute("INSERT INTO ohlcv SELECT * FROM df_tmp")
            con.unregister("df_tmp")
            new_max = df["ts"].max()
            print(f"  -> {len(df)} bars, last_bar={new_max}")
            total_new += len(df)
            time.sleep(0.3)
        except Exception as e:
            print(f"  ERR: {e}")

    # verify
    print()
    print("=== verification ===")
    df = con.execute(
        "SELECT symbol, MAX(ts) AS last_bar FROM ohlcv WHERE venue='binance' AND timeframe='1d' "
        "AND symbol IN ({}) GROUP BY symbol ORDER BY symbol".format(
            ",".join([f"'{s}'" for s in SYMBOLS])
        )
    ).fetchdf()
    print(df.to_string())
    con.close()
    print(f"\nDONE total_inserted_or_replaced={total_new}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
