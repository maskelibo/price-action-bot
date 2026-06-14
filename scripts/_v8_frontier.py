"""v8 follow-up: clean return-at-matched-DD frontier + inter-TF correlation +
regime-timing 'is it a free lunch?' test. Reuses harness, monkeypatched 55bps."""
from __future__ import annotations
import os, sys
from pathlib import Path
os.environ["PA_DUCKDB_READ_ONLY"] = "true"; os.environ["PA_LOG_QUIET"] = "1"
import warnings; warnings.filterwarnings("ignore")
import logging; logging.getLogger("price_action").setLevel(logging.ERROR)
import numpy as np, pandas as pd
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "src"))
import importlib.util
spec = importlib.util.spec_from_file_location("wlr", str(ROOT/"scripts"/"crypto_winner_let_run_vsa_exit.py"))
wlr = importlib.util.module_from_spec(spec); spec.loader.exec_module(wlr)
from price_action.backtest.lab import ProductionConfig, production_replay
from dataclasses import replace

YAML = ROOT/"configs"/"risk_phoenix_scalp_15m_widestop_vsa2.yaml"
SYMS10 = ["BTC/USDT","ETH/USDT","SOL/USDT","BNB/USDT","ADA/USDT","AVAX/USDT","LINK/USDT","DOT/USDT","DOGE/USDT","XRP/USDT"]
SYMS19 = SYMS10 + ["ZEC/USDT","NEAR/USDT","FIL/USDT","XLM/USDT","TRX/USDT","UNI/USDT","ATOM/USDT","AAVE/USDT","ALGO/USDT"]
EXIT = dict(runner_trail_mult=1.5,trail_activate_stage=2,tp1_R=1.0,tp2_R=1.5,tp1_close_pct=0.30,tp2_close_pct=0.30,runner_force_exit_method="time",runner_force_exit_bars=30,force_exit_from_entry=False)
wlr.FEES={"taker":0.00275,"maker":-0.00010}; wlr.SLIPPAGE_BPS=0.0; wlr.SL_PCT_MIN=0.025

def slp(t):
    ep=t["entry_price"]; return abs(t["initial_sl"]-ep)/ep if ep>0 else 0.04
def gu(syms,tf):
    p=[]; [p.extend(wlr.gather(s,EXIT,tf=tf)) for s in syms]; return [t for t in p if slp(t)>=0.025]
def cfg(L):
    c=ProductionConfig.from_yaml(str(YAML)); c=replace(c,risk_pct=0.005*L,sl_pct_min=max(c.sl_pct_min,0.025))
    if c.max_notional_pct_equity is not None: c=replace(c,max_notional_pct_equity=c.max_notional_pct_equity*L)
    if c.concentration_max_per_symbol_pct is not None: c=replace(c,concentration_max_per_symbol_pct=c.concentration_max_per_symbol_pct*L)
    return c
def cdd(eq):
    pk=eq[0]; m=0.0
    for v in eq: pk=max(pk,v); m=min(m,(v-pk)/pk if pk>0 else 0)
    return m*100
def monthly(res,c):
    eq=res.equity_curve or []; ts=res.entry_ts_list or []
    n=min(len(eq)-1,len(ts))
    if n<2: return pd.Series(dtype=float)
    df=pd.DataFrame({"ts":pd.to_datetime(ts[:n],utc=True),"eq":eq[1:n+1]}); df["m"]=df["ts"].dt.to_period("M")
    me=df.groupby("m")["eq"].last(); prev=me.shift(1,fill_value=c.initial_capital); return (me/prev-1)*100
def run(pool,L):
    c=cfg(L); r=production_replay(sorted(pool,key=lambda x:x["entry_ts"]),c); mr=monthly(r,c)
    return mr, cdd(r.equity_curve)
def lev_for_dd(pool, target_dd=-18.0, lo=1.0, hi=4.0):
    # bisection: find max L with MaxDD >= target_dd (closest from above)
    best=None
    for _ in range(18):
        mid=(lo+hi)/2; mr,dd=run(pool,mid)
        if dd>=target_dd: best=(mid,mr,dd); lo=mid
        else: hi=mid
    return best

print("=== inter-TF monthly correlation (common-10, common window) + return@-18%DD frontier ===")
p15f=gu(SYMS10,"15m"); p05=gu(SYMS10,"5m"); p1h=gu(SYMS10,"1h")
sp=lambda p:(min(t["entry_ts"] for t in p),max(t["entry_ts"] for t in p))
lo=max(sp(p15f)[0],sp(p05)[0],sp(p1h)[0]); hi=min(sp(p15f)[1],sp(p05)[1],sp(p1h)[1])
clip=lambda p:[t for t in p if lo<=t["entry_ts"]<=hi]
p15,p05c,p1hc=clip(p15f),clip(p05),clip(p1h); stack=p15+p05c+p1hc
m15,_=run(p15,1.0); m5,_=run(p05c,1.0); m1,_=run(p1hc,1.0)
df=pd.DataFrame({"m15":m15,"m5":m5,"m1h":m1}).dropna()
print("monthly ROI correlation matrix (TF legs):"); print(df.corr().round(2).to_string())

print("\n=== RETURN at MaxDD<=-18% — apples-to-apples (common-10, 2023-05->2026-04) ===")
print(f"{'approach':<26} {'L*':>5} {'mean':>7} {'med':>7} {'pos':>5} {'min':>7} {'MaxDD':>7} {'Sharpe':>7}")
for nm,pool in [("15m-only (10s)",p15),("STACK 5m+15m+1h",stack)]:
    L,mr,dd=lev_for_dd(pool,-18.0)
    sh=mr.mean()/mr.std()*np.sqrt(12) if mr.std()>0 else 0
    print(f"{nm:<26} {L:>4.2f} {mr.mean():>+6.2f}% {mr.median():>+6.2f}% {(mr>0).mean()*100:>4.0f}% {mr.min():>+6.2f}% {dd:>+6.1f}% {sh:>+6.2f}")

print("\n=== full-universe 19s @-18%DD (the deployable champion universe) ===")
p19=gu(SYMS19,"15m")
L,mr,dd=lev_for_dd(p19,-18.0); sh=mr.mean()/mr.std()*np.sqrt(12) if mr.std()>0 else 0
print(f"{'flat 19s @-18%DD':<26} {L:>4.2f} {mr.mean():>+6.2f}% {mr.median():>+6.2f}% {(mr>0).mean()*100:>4.0f}% {mr.min():>+6.2f}% {dd:>+6.1f}% {sh:>+6.2f}")

# regime-timing free-lunch test: compare regime schedule vs flat AT THE SAME MaxDD.
# If regime timing is real, regime-version has HIGHER mean at the same DD.
print("\n=== REGIME-TIMING free-lunch test (19s, matched MaxDD ~ flat-2x's -35.5%) ===")
import duckdb
def btc_frame():
    con=duckdb.connect(str(ROOT/"data"/"market.duckdb"),read_only=True)
    b=con.execute("SELECT ts,close FROM ohlcv WHERE venue='binance' AND symbol='BTC/USDT' AND timeframe='15m' ORDER BY ts").fetchdf(); con.close()
    b["ts"]=pd.to_datetime(b["ts"],utc=True); b=b.sort_values("ts").reset_index(drop=True)
    b["rv"]=np.log(b["close"]).diff().rolling(96).std()
    b["q33"]=b["rv"].rolling(96*90,min_periods=96*20).quantile(1/3).shift(1)
    b["q67"]=b["rv"].rolling(96*90,min_periods=96*20).quantile(2/3).shift(1)
    return b.dropna(subset=["rv"]).reset_index(drop=True)
b=btc_frame(); ts_arr=b["ts"].values
for t in p19:
    i=np.searchsorted(ts_arr,np.datetime64(t["entry_ts"]))-1
    if i<0 or i>=len(b) or np.isnan(b["q33"].iloc[i]): t["regime"]="unk"; continue
    rv=b["rv"].iloc[i]; t["regime"]="low" if rv<=b["q33"].iloc[i] else ("high" if rv>=b["q67"].iloc[i] else "mid")
# schedule: lever low+high (best IS), cut mid. Tuned so MaxDD ~ flat-2x (-35.5%) for fair mean compare.
sch={"low":2.6,"high":2.6,"mid":1.0,"unk":1.5}
wpool=[{**t,"risk_weight":sch.get(t["regime"],1.0)} for t in p19]
c=replace(cfg(max(sch.values())),risk_pct=0.005)
r=production_replay(sorted(wpool,key=lambda x:x["entry_ts"]),c); mrr=monthly(r,c); ddr=cdd(r.equity_curve)
# flat at the leverage that matches THAT same DD
Lf,mrf,ddf=lev_for_dd(p19,ddr); shf=mrf.mean()/mrf.std()*np.sqrt(12)
shr=mrr.mean()/mrr.std()*np.sqrt(12)
print(f"regime(low/high 2.6x, mid 1x): mean={mrr.mean():+.2f}% MaxDD={ddr:+.1f}% Sharpe={shr:+.2f} pos={(mrr>0).mean()*100:.0f}% min={mrr.min():+.2f}%")
print(f"flat at SAME DD (L={Lf:.2f}):     mean={mrf.mean():+.2f}% MaxDD={ddf:+.1f}% Sharpe={shf:+.2f} pos={(mrf>0).mean()*100:.0f}% min={mrf.min():+.2f}%")
print(f"REGIME EDGE at matched DD: Δmean={mrr.mean()-mrf.mean():+.2f} pp/mo, ΔSharpe={shr-shf:+.2f}")
