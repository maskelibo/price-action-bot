"""MTF Data Cache — 4h ve 1h OHLCV indir (11 sym × 5y).

Sec2 (HYP-2026-05-17 feature space v2) icin gerekli.

Binance public API (no auth, no rate-limit user-agent gerek yok ama yine de
0.3s delay between requests, polite).

5y * 365d * 6 (4h bar/day) = ~10950 bar/sym  -> Binance limit 1000/req → 11 req/sym
5y * 365d * 24 (1h bar/day) = ~43800 bar/sym -> 44 req/sym

Toplam ~605 req → ~3.5 dakika @ 0.3s delay.

Cache: data/mtf_4h_cache.pkl, data/mtf_1h_cache.pkl
"""
from __future__ import annotations

import os
import pickle
import sys
import time
import warnings
from pathlib import Path

os.environ["PA_LOG_QUIET"] = "1"
warnings.filterwarnings("ignore")

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[1]

SYMBOLS_11 = [
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "ADAUSDT",
    "AVAXUSDT", "LINKUSDT", "DOTUSDT", "DOGEUSDT", "XRPUSDT", "MATICUSDT",
]

# 5 yil = 2021-05-15 -> 2026-05-15 (ML v1 trade pool ile uyumlu)
START_TS_MS = int(pd.Timestamp("2021-05-15", tz="UTC").timestamp() * 1000)
END_TS_MS = int(pd.Timestamp("2026-05-15", tz="UTC").timestamp() * 1000)


def fetch_klines(symbol: str, interval: str, start_ms: int, end_ms: int) -> pd.DataFrame:
    """Binance klines fetch with pagination (1000 bar/req limit)."""
    all_rows: list[list] = []
    cur = start_ms
    while cur < end_ms:
        try:
            r = requests.get(
                "https://api.binance.com/api/v3/klines",
                params={
                    "symbol": symbol,
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
            print(f"    [WARN] {symbol} {interval} fetch err {e}, retry 3s...")
            time.sleep(3)
            continue
        if not batch:
            break
        all_rows.extend(batch)
        last_ts = batch[-1][0]
        if last_ts <= cur:
            break
        cur = last_ts + 1
        time.sleep(0.3)
    if not all_rows:
        return pd.DataFrame()
    df = pd.DataFrame(all_rows, columns=[
        "open_time", "open", "high", "low", "close", "volume",
        "close_time", "quote_vol", "n_trades", "taker_buy_base",
        "taker_buy_quote", "ignore",
    ])
    df["ts"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
    for c in ["open", "high", "low", "close", "volume", "taker_buy_base", "taker_buy_quote"]:
        df[c] = pd.to_numeric(df[c])
    df = df[["ts", "open", "high", "low", "close", "volume", "taker_buy_base"]]
    df = df.drop_duplicates(subset="ts").sort_values("ts").reset_index(drop=True)
    return df


def main() -> None:
    print(f"MTF cache build START: {pd.Timestamp.utcnow().isoformat()}")
    print(f"Sembol sayisi: {len(SYMBOLS_11)}")
    print(f"Tarih: {pd.Timestamp(START_TS_MS, unit='ms', tz='UTC')} -> {pd.Timestamp(END_TS_MS, unit='ms', tz='UTC')}")

    for interval, cache_name in [("4h", "mtf_4h_cache.pkl"), ("1h", "mtf_1h_cache.pkl")]:
        cache_path = ROOT / "data" / cache_name
        if cache_path.exists():
            print(f"  [SKIP] {cache_name} mevcut, atliyor.")
            continue
        print(f"\n--- {interval} fetch ---")
        d: dict[str, pd.DataFrame] = {}
        t0 = time.time()
        for sym in SYMBOLS_11:
            print(f"  {sym} {interval}...", end=" ", flush=True)
            ts0 = time.time()
            df = fetch_klines(sym, interval, START_TS_MS, END_TS_MS)
            sym_key = sym.replace("USDT", "/USDT")
            d[sym_key] = df
            print(f"n={len(df)} ({time.time()-ts0:.1f}s)")
        with cache_path.open("wb") as f:
            pickle.dump(d, f)
        print(f"  Cache kaydedildi: {cache_path} (toplam {time.time()-t0:.1f}s)")

    print(f"\nMTF cache build DONE: {pd.Timestamp.utcnow().isoformat()}")


if __name__ == "__main__":
    main()
