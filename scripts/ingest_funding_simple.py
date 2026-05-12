"""Simple alt-data ingest — Binance funding + alternative.me F&G + Binance OI/liq-proxy.

Hizli, CSV cache. Backtest ile beslemek icin yeterli.

Output:
    data/alt_data/funding_BTCUSDT.csv  (ts, fundingRate, markPrice)
    data/alt_data/fng_daily.csv         (date, value, classification)
    data/alt_data/oi_BTCUSDT.csv        (ts, sumOpenInterest, sumOpenInterestValue)

Kullanim:
    python scripts/ingest_funding_simple.py
"""
from __future__ import annotations

import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "alt_data"
OUT.mkdir(parents=True, exist_ok=True)

BINANCE_FUNDING_URL = "https://fapi.binance.com/fapi/v1/fundingRate"
BINANCE_OI_URL = "https://fapi.binance.com/futures/data/openInterestHist"
FNG_URL = "https://api.alternative.me/fng/"


def fetch_funding_history(symbol: str = "BTCUSDT", years: int = 5) -> pd.DataFrame:
    """Binance funding rate history — paginate 1000 per call."""
    end_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    start_ms = int((datetime.now(timezone.utc) - timedelta(days=365 * years)).timestamp() * 1000)

    all_rows = []
    cur_start = start_ms
    page = 0
    while cur_start < end_ms:
        params = {
            "symbol": symbol,
            "startTime": cur_start,
            "endTime": end_ms,
            "limit": 1000,
        }
        try:
            r = requests.get(BINANCE_FUNDING_URL, params=params, timeout=30)
            r.raise_for_status()
            data = r.json()
        except Exception as e:
            print(f"  funding fetch err page {page}: {e}")
            break
        if not data:
            break
        all_rows.extend(data)
        last_ts = int(data[-1]["fundingTime"])
        if last_ts <= cur_start:
            break
        cur_start = last_ts + 1
        page += 1
        if len(data) < 1000:
            break
        time.sleep(0.15)
    print(f"  funding fetched: {len(all_rows)} rows in {page+1} pages")

    df = pd.DataFrame(all_rows)
    if df.empty:
        return df
    df["ts"] = pd.to_datetime(df["fundingTime"], unit="ms", utc=True)
    df["fundingRate"] = pd.to_numeric(df["fundingRate"])
    df["markPrice"] = pd.to_numeric(df["markPrice"], errors="coerce")
    df = df[["ts", "fundingRate", "markPrice"]].sort_values("ts").reset_index(drop=True)
    return df


def fetch_fng(limit: int = 2000) -> pd.DataFrame:
    """alternative.me Crypto Fear & Greed."""
    r = requests.get(FNG_URL, params={"limit": limit, "format": "json"}, timeout=30)
    r.raise_for_status()
    payload = r.json()
    rows = []
    for it in payload.get("data", []):
        ts_unix = int(it.get("timestamp", 0))
        rows.append({
            "ts": datetime.fromtimestamp(ts_unix, tz=timezone.utc),
            "value": int(it.get("value", 0)),
            "classification": it.get("value_classification", ""),
        })
    df = pd.DataFrame(rows).sort_values("ts").reset_index(drop=True)
    df["date"] = df["ts"].dt.date
    return df[["date", "ts", "value", "classification"]]


def fetch_oi_history(symbol: str = "BTCUSDT", days: int = 30 * 12) -> pd.DataFrame:
    """Binance OI hist — daily, max 30d per call. Paginate."""
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days)
    # Binance OI: 30 days max window per request, period=1d, limit 500
    all_rows = []
    cur_end = end
    while cur_end > start:
        cur_start = max(start, cur_end - timedelta(days=30))
        params = {
            "symbol": symbol,
            "period": "1d",
            "startTime": int(cur_start.timestamp() * 1000),
            "endTime": int(cur_end.timestamp() * 1000),
            "limit": 500,
        }
        try:
            r = requests.get(BINANCE_OI_URL, params=params, timeout=30)
            r.raise_for_status()
            data = r.json()
        except Exception as e:
            print(f"  OI fetch err {cur_start.date()}: {e}")
            break
        if not data:
            break
        all_rows.extend(data)
        cur_end = cur_start - timedelta(seconds=1)
        time.sleep(0.2)
    df = pd.DataFrame(all_rows)
    if df.empty:
        return df
    df["ts"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    df["sumOpenInterest"] = pd.to_numeric(df["sumOpenInterest"], errors="coerce")
    df["sumOpenInterestValue"] = pd.to_numeric(df["sumOpenInterestValue"], errors="coerce")
    df = df[["ts", "sumOpenInterest", "sumOpenInterestValue"]].drop_duplicates(subset=["ts"]).sort_values("ts").reset_index(drop=True)
    return df


def main():
    print("=" * 60)
    print("ALT-DATA INGEST")
    print("=" * 60)

    print("\n[1/3] Funding rate BTCUSDT (5y)...")
    fdf = fetch_funding_history("BTCUSDT", years=5)
    if not fdf.empty:
        out = OUT / "funding_BTCUSDT.csv"
        fdf.to_csv(out, index=False)
        print(f"  wrote {len(fdf)} rows -> {out}")
        print(f"  range: {fdf['ts'].min()} -> {fdf['ts'].max()}")
    else:
        print("  EMPTY")

    print("\n[2/3] Fear & Greed (2000d)...")
    gdf = fetch_fng(2000)
    if not gdf.empty:
        out = OUT / "fng_daily.csv"
        gdf.to_csv(out, index=False)
        print(f"  wrote {len(gdf)} rows -> {out}")
        print(f"  range: {gdf['ts'].min()} -> {gdf['ts'].max()}")
    else:
        print("  EMPTY")

    print("\n[3/3] Open Interest BTCUSDT (1y — OI hist limit)...")
    odf = fetch_oi_history("BTCUSDT", days=365)
    if not odf.empty:
        out = OUT / "oi_BTCUSDT.csv"
        odf.to_csv(out, index=False)
        print(f"  wrote {len(odf)} rows -> {out}")
        print(f"  range: {odf['ts'].min()} -> {odf['ts'].max()}")
    else:
        print("  EMPTY")

    print("\nDone.")


if __name__ == "__main__":
    main()
