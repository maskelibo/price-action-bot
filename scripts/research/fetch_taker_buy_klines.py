"""Binance fapi taker-buy klines çek → bar-bazlı signed delta cache.

HYP-2026-06-01-fabio-delta-cvd-valuearea-crypto destek verisi.

fapi klines response (12 alan):
  [0]=openTime [1]=open [2]=high [3]=low [4]=close [5]=volume(base)
  [6]=closeTime [7]=quoteVol [8]=trades [9]=takerBuyBase [10]=takerBuyQuote [11]=ignore

delta_bar = takerBuyBase - (volume - takerBuyBase) = 2*takerBuyBase - volume
(taker buy = piyasa alımı agresif; taker sell = piyasa satımı agresif → signed flow proxy)

Cache: data/_fabio_delta_klines/<SYM>_<TF>.parquet (READ sonrası backtest hızlı).
Canlı config/daemon DOKUNULMAZ. Deploy YOK.
"""
from __future__ import annotations
import sys, time
from pathlib import Path
import numpy as np
import pandas as pd
import ccxt

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "data" / "_fabio_delta_klines"
OUT.mkdir(parents=True, exist_ok=True)

SYMS = {"BTC/USDT": "BTCUSDT", "ETH/USDT": "ETHUSDT", "SOL/USDT": "SOLUSDT"}
TFS = ["5m", "15m"]
DAYS = 400  # ~13 ay, biraz pay
LIMIT = 1500


def fetch_tf(ex, ccxt_sym, fsym, tf):
    end_ms = ex.milliseconds()
    start_ms = end_ms - DAYS * 86400 * 1000
    cur = start_ms
    rows = []
    while cur < end_ms:
        try:
            r = ex.fapiPublicGetKlines({
                "symbol": fsym, "interval": tf,
                "startTime": cur, "limit": LIMIT,
            })
        except Exception as e:
            print(f"    retry {fsym} {tf} @ {cur}: {e}")
            time.sleep(2)
            continue
        if not r:
            break
        for k in r:
            rows.append((
                int(k[0]), float(k[1]), float(k[2]), float(k[3]), float(k[4]),
                float(k[5]), float(k[9]),  # volume, takerBuyBase
            ))
        last_open = int(r[-1][0])
        if len(r) < LIMIT:
            break
        cur = last_open + 1
        time.sleep(ex.rateLimit / 1000.0)
    df = pd.DataFrame(rows, columns=["openTime", "open", "high", "low", "close",
                                     "volume", "taker_buy"])
    df = df.drop_duplicates("openTime").sort_values("openTime").reset_index(drop=True)
    df["ts"] = pd.to_datetime(df["openTime"], unit="ms", utc=True)
    df["delta"] = 2.0 * df["taker_buy"] - df["volume"]  # signed agresif akış
    return df


def main():
    ex = ccxt.binanceusdm({"enableRateLimit": True})
    for ccxt_sym, fsym in SYMS.items():
        for tf in TFS:
            t0 = time.time()
            df = fetch_tf(ex, ccxt_sym, fsym, tf)
            fn = OUT / f"{fsym}_{tf}.parquet"
            df.to_parquet(fn)
            print(f"{fsym} {tf}: n={len(df)} {df['ts'].min()}→{df['ts'].max()} "
                  f"({time.time()-t0:.0f}s) → {fn.name}")
    print("DONE.")


if __name__ == "__main__":
    main()
