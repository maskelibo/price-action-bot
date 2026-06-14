"""Fair comparison under LIVE widestop mechanism (sl_pct_min=0.025).

Canli 15m bot edge'i = sl_pct_min=0.025 filtresi (tight-stop = fee-erozyon trade'leri
REJECT). Bu olmadan ham VSA sinyal havuzu fee-kaybedeni. Adaylari AYNI fair filtre
ile kiyasla: her strateji icin entry sl_pct = |entry - initial_sl| / entry hesapla,
sl_pct >= 0.025 alt-kumesinde mean_R_after_fees + aylik ROI raporla.

Bu, sizing'den bagimsiz (mean_R) ve canli mekanizmaya hizali tek dürüst kiyas.
"""
from __future__ import annotations
import os, sys, warnings
from datetime import datetime, timezone
from pathlib import Path
warnings.filterwarnings("ignore"); os.environ.setdefault("PA_LOG_QUIET", "1")
ROOT = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT / "src"))
import logging; logging.getLogger("price_action").setLevel(logging.ERROR)
import numpy as np, pandas as pd, duckdb
from price_action.backtest.engine import BacktestEngine
from price_action.strategies.vsa_climax_test import VSAClimaxTestStrategy, _default_manifest as vsa_mf
from price_action.strategies.donchian_breakout import DonchianBreakoutStrategy
from price_action.strategies.session_orb import SessionORBStrategy, _default_manifest as orb_mf
from price_action.strategies.base import StrategyManifest

SYMBOLS = ["BTC/USDT","ETH/USDT","SOL/USDT","BNB/USDT","XRP/USDT","DOGE/USDT","ADA/USDT","AVAX/USDT","LINK/USDT","DOT/USDT"]
TF="15m"; START=datetime(2021,5,16,tzinfo=timezone.utc); END=datetime(2026,5,22,tzinfo=timezone.utc); CAP=10_000.0
_DB=Path("/tmp/market_snapshot.duckdb"); _DB=_DB if _DB.exists() else ROOT/"data"/"market.duckdb"
_C={}
def loader(sym,tf,start,end):
    k=(sym,tf)
    if k not in _C:
        con=duckdb.connect(str(_DB),read_only=True)
        df=con.execute("SELECT ts,open,high,low,close,volume FROM ohlcv WHERE venue='binance' AND symbol=? AND timeframe=? ORDER BY ts",[sym,tf]).fetchdf()
        con.close()
        if not df.empty: df["ts"]=pd.to_datetime(df["ts"],utc=True)
        _C[k]=df
    df=_C[k]
    if df.empty: return df
    out=df[(df["ts"]>=pd.Timestamp(start))&(df["ts"]<=pd.Timestamp(end))].copy()
    out["symbol"]=sym; out["timeframe"]=tf; out["venue"]="binance"; return out

def don_mf():
    return StrategyManifest.model_validate({"name":"donchian_breakout","version":"15m",
        "signals":{"patterns":[{"id":"donchian_breakout","enabled":True,"weight":1.0,
        "params":{"entry_period":55,"exit_period":20,"squeeze_required":False}}],
        "filters":{"atr_min_pct":0.003,"kaufman_er_min":0.30},"confluence":{"min_score":1.0}},
        "risk":{"take_profit":{"method":"r_multiple","primary_R":1.5}},"backtest":{"initial_capital_usdt":CAP}})

def build(nm):
    return {"vsa_climax_test":lambda:VSAClimaxTestStrategy(vsa_mf()),
            "donchian_breakout":lambda:DonchianBreakoutStrategy(don_mf()),
            "session_orb":lambda:SessionORBStrategy(orb_mf())}[nm]()

def get_trades(nm,taker,slip):
    res=BacktestEngine().run(build(nm),SYMBOLS,start=START,end=END,
        fees={"taker":taker,"maker":-0.00010},slippage_bps=slip,initial_capital=CAP,
        timeframe=TF,ohlcv_provider=loader)
    return res.trades

def subset_stats(tr,slpct_min):
    if tr.empty: return None
    t=tr.copy()
    t["sl_pct"]=(t["entry_price"]-t["initial_sl"]).abs()/t["entry_price"]
    sub=t[t["sl_pct"]>=slpct_min] if slpct_min>0 else t
    if sub.empty: return dict(n=0,mean_R=0.0,win=0.0,mROI=0.0,neg=0,mn=0)
    # equity from R-multiples with fixed 1% risk per trade, sequential by exit_ts
    sub=sub.sort_values("exit_ts")
    r=sub["realized_r_multiple"].to_numpy()
    eq=CAP*np.cumprod(1+0.005*r)  # 0.5% risk/trade (live risk_pct)
    idx=pd.to_datetime(sub["exit_ts"].to_numpy(),utc=True)
    s=pd.Series(eq,index=idx)
    m=s.resample("ME").last(); mret=(m/m.shift(1,fill_value=CAP)-1).dropna()
    peak=s.cummax(); dd=((s-peak)/peak).min()
    return dict(n=len(sub),mean_R=float(sub["realized_r_multiple"].mean()),
        win=float((sub["realized_r_multiple"]>0).mean())*100,
        mROI=float(mret.mean())*100,neg=int((mret<0).sum()),mn=int(len(mret)),
        maxdd=float(dd)*100)

def main():
    print("="*86)
    print("FAIR WIDESTOP COMPARISON (sl_pct_min=0.025, risk_pct=0.5% sequential, 55bps)")
    print("="*86)
    names=["vsa_climax_test","donchian_breakout","session_orb"]
    hdr=f"{'strategy':<20}{'filter':<10}{'n':>7}{'mean_R':>9}{'win%':>7}{'mROI%':>8}{'maxDD%':>9}{'neg':>7}"
    print(hdr); print("-"*len(hdr),flush=True)
    for nm in names:
        tr=get_trades(nm,0.00275,5.0)
        for lbl,flt in [("all",0.0),("widestop",0.025)]:
            r=subset_stats(tr,flt)
            if r is None: print(f"{nm:<20}{lbl:<10}{'no trades':>7}");continue
            print(f"{nm:<20}{lbl:<10}{r['n']:>7}{r['mean_R']:>9.3f}{r['win']:>7.1f}"
                  f"{r['mROI']:>8.2f}{r.get('maxdd',0):>9.1f}{r['neg']:>4}/{r['mn']:<2}",flush=True)
    print("\nNOT: mROI/maxDD = R-multiple havuzundan 0.5% risk/trade sequential compounding;")
    print("canli engine'in partial-TP/trail makinesi DEGIL -> yon gostergesi, birebir degil.")
    print("DONE.")

if __name__=="__main__": main()
