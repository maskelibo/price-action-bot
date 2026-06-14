"""DECISIVE — Can a DIVERSIFIED, levered portfolio hit CONSISTENT ~15%/mo
(min month >= +8-10%, LOW variance)?  Honest build, no artifacts.

Ingredients (validated, gated this session — reused verbatim):
  - Champion: crypto VSA-WIDESTOP + BASELINE exit, 19-sym 15m pool
    (data/sec53_15m_pool_v11.pkl), production_replay equity-reset monthly.
  - Multi-FX Brooks: brooks_failed_breakout 4H across ALL 8 FX majors in
    data/forex_market.duckdb, equal-risk, pooled single account, same engine.

Method:
  1. Multi-FX Brooks return stream (equal-risk across 8 majors) -> monthly %.
     Report combined edge, capacity, rho to champion.
  2. Portfolio = champion + multi-FX Brooks on common monthly series. Find the
     risk-budget split that MAX portfolio Sharpe. Report unlevered stats.
  3. Lever to mean ~15%/mo. Full monthly distribution.
  4. Judge vs bar (mean ~15, min >= +8-10, low var). Compare champion-ALONE
     levered to 15% (the rejected "savruk" profile).

Repro: .venv/bin/python scripts/portfolio_leverage_15pct.py
"""
from __future__ import annotations
import io, os, sys, math, pickle, subprocess
from datetime import datetime, timezone
from pathlib import Path

try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
except Exception:
    pass
os.environ["PA_LOG_QUIET"] = "1"
os.environ["PA_DUCKDB_READ_ONLY"] = "true"
import warnings; warnings.filterwarnings("ignore")
import logging; logging.getLogger("price_action").setLevel(logging.ERROR)

import numpy as np
import pandas as pd
import duckdb

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "src"))

from price_action.backtest.engine import BacktestEngine
from price_action.backtest.lab import ProductionConfig, production_replay

import importlib.util
spec = importlib.util.spec_from_file_location("fx", str(ROOT / "scripts" / "forex_4h_research.py"))
fx = importlib.util.module_from_spec(spec); spec.loader.exec_module(fx)

SEED = 12345
np.random.seed(SEED)
GIT = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT,
                     capture_output=True, text=True).stdout.strip()

FX_MAJORS = ["EUR/USD", "GBP/USD", "USD/JPY", "USD/CHF",
             "USD/CAD", "AUD/USD", "NZD/USD", "EUR/GBP"]
FX_TF = "4h"


# ---------------------------------------------------------------------------
def to_utc(ts):
    ts = pd.Timestamp(ts)
    return ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")


def stats(series):
    a = np.array(series, dtype=float)
    if len(a) == 0:
        return dict(n=0, mean=0, med=0, sd=0, sharpe_m=0, sharpe_ann=0, neg=0, maxdd=0, ann=0, mn=0)
    mean = a.mean(); med = float(np.median(a)); sd = a.std(ddof=1) if len(a) > 1 else 0.0
    sharpe_m = mean / sd if sd > 0 else 0.0
    eq = np.cumprod(1 + a / 100.0)
    peak = np.maximum.accumulate(eq)
    dd = (eq / peak - 1.0).min() * 100.0
    ann = (eq[-1] ** (12.0 / len(a)) - 1.0) * 100.0 if eq[-1] > 0 else -100.0
    return dict(n=len(a), mean=mean, med=med, sd=sd, sharpe_m=sharpe_m,
                sharpe_ann=sharpe_m * math.sqrt(12), neg=int((a < 0).sum()),
                maxdd=dd, ann=ann, mn=float(a.min()))


# ---------------------------------------------------------------------------
# Multi-FX Brooks: load any major, gather brooks trades (reuse fx module logic).
# fx.load_ohlcv()/gather() hardcode fx.SYMBOL — monkeypatch per pair.
# ---------------------------------------------------------------------------
def load_major(symbol):
    con = duckdb.connect(str(fx.DB), read_only=True)
    df = con.execute(
        "SELECT ts, open, high, low, close, volume FROM ohlcv "
        "WHERE symbol=? AND timeframe=? ORDER BY ts", [symbol, FX_TF]).fetchdf()
    con.close()
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    df = df.sort_values("ts").reset_index(drop=True)
    df["symbol"] = symbol; df["venue"] = "forex"; df["timeframe"] = FX_TF
    return df


def gather_major(symbol, slippage_bps):
    """Reuse fx.gather but for arbitrary symbol (patch module-level SYMBOL)."""
    df = load_major(symbol)
    strat = fx.build_strategy("brooks_failed_breakout", "BrooksFailedBreakoutStrategy")
    old = fx.SYMBOL
    fx.SYMBOL = symbol
    try:
        trades = fx.gather(strat, df, slippage_bps=slippage_bps, apply_swap=True)
    finally:
        fx.SYMBOL = old
    for t in trades:
        t["symbol"] = symbol
    return trades


def multi_fx_pool(slippage_bps):
    pool, per_sym = [], {}
    for s in FX_MAJORS:
        tr = gather_major(s, slippage_bps)
        per_sym[s] = tr
        pool += tr
    pool.sort(key=lambda x: to_utc(x["entry_ts"]))
    return pool, per_sym


# ---------------------------------------------------------------------------
# Per-month equity-reset replay (honest comparable footing). Fresh $ each month.
# ---------------------------------------------------------------------------
def monthly_returns(trades, cfg, min_trades=1):
    if not trades:
        return {}
    pool = sorted(trades, key=lambda x: to_utc(x["entry_ts"]))
    start, end = to_utc(pool[0]["entry_ts"]), to_utc(pool[-1]["entry_ts"])
    out = {}
    cy, cm = start.year, start.month
    while True:
        ms = datetime(cy, cm, 1, tzinfo=timezone.utc)
        ny, nm = (cy + 1, 1) if cm == 12 else (cy, cm + 1)
        me = datetime(ny, nm, 1, tzinfo=timezone.utc)
        if ms > end:
            break
        m_tr = [t for t in pool if ms <= to_utc(t["entry_ts"]) < me]
        if len(m_tr) >= min_trades:
            r = production_replay(m_tr, cfg)
            if r is not None:
                out[f"{cy:04d}-{cm:02d}"] = r.total_return * 100.0
        cy, cm = ny, nm
    return out


def champion_monthly():
    with open(ROOT / "data" / "sec53_15m_pool_v11.pkl", "rb") as f:
        pool = pickle.load(f)
    # filter to widestop (sl_pct >= 0.025) consistent with the champion characterization
    def sl_pct(t):
        ep = float(t.get("entry_price", 0)); sp = float(t.get("initial_sl", 0))
        return abs(ep - sp) / ep if ep > 0 else 0.0
    ws = [t for t in pool if sl_pct(t) >= 0.025]
    cfg = ProductionConfig(risk_pct=0.005, sl_pct_min=0.025, fee_bps_per_trade=55.0,
                           conf_min=0.0, leverage=3.0)
    return monthly_returns(ws, cfg, min_trades=10)


# ---------------------------------------------------------------------------
def lever_distribution(monthly_pct, target_mean=15.0, max_lev=10.0):
    """Find leverage L s.t. L*mean ~ target_mean (linear on % returns), then
    report the FULL distribution of L*r. DD recomputed on levered compounding."""
    a = np.array(monthly_pct, dtype=float)
    m = a.mean()
    if m <= 0:
        return None
    L = min(max_lev, target_mean / m)
    lev = a * L
    return L, stats(list(lev))


def main():
    print(f"git={GIT} seed={SEED}")
    print("=" * 78)

    # ---- [1] MULTI-FX BROOKS STREAM ----
    print("\n[1] MULTI-FX BROOKS (brooks_failed_breakout, 4H, 8 majors, equal-risk)")
    pool, per_sym = multi_fx_pool(fx.SLIPPAGE_BPS)
    print(f"    {'symbol':<9} {'n':>4} {'net_mR':>8} {'gross_mR':>9} {'win%':>6} {'sumR':>8}")
    for s in FX_MAJORS:
        tr = per_sym[s]
        if not tr:
            print(f"    {s:<9}    0 (no trades)"); continue
        R = np.array([t["R"] for t in tr]); G = np.array([t["gross_R"] for t in tr])
        print(f"    {s:<9} {len(tr):>4} {R.mean():>+8.3f} {G.mean():>+9.3f} "
              f"{(R>0).mean()*100:>5.1f}% {R.sum():>+8.1f}")
    Rall = np.array([t["R"] for t in pool])
    print(f"    {'POOL':<9} {len(pool):>4} {Rall.mean():>+8.3f} "
          f"{np.array([t['gross_R'] for t in pool]).mean():>+9.3f} "
          f"{(Rall>0).mean()*100:>5.1f}% {Rall.sum():>+8.1f}")

    # shuffle null on pooled trade-R
    rng = np.random.default_rng(SEED); obs = Rall.mean(); cnt = 0
    absR = np.abs(Rall)
    for _ in range(5000):
        if (absR * rng.choice([-1.0, 1.0], size=len(Rall))).mean() >= obs:
            cnt += 1
    p_shuf = (cnt + 1) / 5001
    print(f"    shuffle null p={p_shuf:.4f}  (pooled net mR={obs:+.3f})")

    # FX leg: no crypto fee; net R already includes spread+swap
    cfg_fx = ProductionConfig(risk_pct=0.005, sl_pct_min=0.0, fee_bps_per_trade=0.0,
                              conf_min=0.0, leverage=3.0, max_concurrent=8)
    fx_bm = monthly_returns(pool, cfg_fx, min_trades=1)
    sfx = stats(list(fx_bm.values()))
    print(f"    monthly: n={sfx['n']} mean={sfx['mean']:+.2f}% med={sfx['med']:+.2f}% "
          f"sd={sfx['sd']:.2f} Sharpe_ann={sfx['sharpe_ann']:+.2f} "
          f"maxDD={sfx['maxdd']:.1f}% neg={sfx['neg']}/{sfx['n']} ann={sfx['ann']:+.1f}%")
    # capacity note: 8 majors @ 0.5% risk, max 8 concurrent -> small notional
    print(f"    capacity: equal-risk 0.5%/trade, 8 majors pooled, max_concurrent=8")

    # ---- [2] CHAMPION STREAM ----
    print("\n[2] CRYPTO VSA-WIDESTOP CHAMPION (19-sym 15m, widestop, 55bps)")
    champ_bm = champion_monthly()
    sc = stats(list(champ_bm.values()))
    print(f"    monthly: n={sc['n']} mean={sc['mean']:+.2f}% med={sc['med']:+.2f}% "
          f"sd={sc['sd']:.2f} Sharpe_ann={sc['sharpe_ann']:+.2f} "
          f"maxDD={sc['maxdd']:.1f}% neg={sc['neg']}/{sc['n']} ann={sc['ann']:+.1f}%")

    # ---- [3] OVERLAP + rho ----
    common = sorted(set(fx_bm) & set(champ_bm))
    print(f"\n[3] OVERLAP: {len(common)} common months "
          f"({common[0] if common else '-'}..{common[-1] if common else '-'})")
    bx = np.array([fx_bm[m] for m in common])
    cx = np.array([champ_bm[m] for m in common])
    rho = float(np.corrcoef(bx, cx)[0, 1]) if len(common) >= 3 else float("nan")
    print(f"    rho(multiFX, champion) = {rho:+.3f}")
    # OOS-only rho
    oos = [m for m in common if m >= "2024-01"]
    if len(oos) >= 3:
        bxo = np.array([fx_bm[m] for m in oos]); cxo = np.array([champ_bm[m] for m in oos])
        print(f"    rho OOS(2024-25, n={len(oos)}) = {float(np.corrcoef(bxo,cxo)[0,1]):+.3f}")

    sc_o = stats(list(cx)); sb_o = stats(list(bx))
    print(f"    champion(overlap): mean={sc_o['mean']:+.2f}% sd={sc_o['sd']:.2f} "
          f"Sharpe_ann={sc_o['sharpe_ann']:+.2f} maxDD={sc_o['maxdd']:.1f}% min={sc_o['mn']:+.2f}%")
    print(f"    multiFX (overlap): mean={sb_o['mean']:+.2f}% sd={sb_o['sd']:.2f} "
          f"Sharpe_ann={sb_o['sharpe_ann']:+.2f} maxDD={sb_o['maxdd']:.1f}% min={sb_o['mn']:+.2f}%")

    # ---- [4] PORTFOLIO: max-Sharpe risk-budget split (vol-matched, equal-risk capable) ----
    print("\n[4] PORTFOLIO — risk-budget split, MAX Sharpe (overlap monthly series)")
    # capital-split (raw $) view
    print("  (a) capital-split blends w*champ + (1-w)*fx:")
    print(f"      {'w_ch':>5} {'w_fx':>5} {'mean%':>7} {'sd':>6} {'Sh_ann':>7} {'maxDD%':>8} {'min%':>7}")
    best = None
    for w in np.arange(0.0, 1.01, 0.05):
        port = w * cx + (1 - w) * bx
        sp = stats(list(port))
        if best is None or sp["sharpe_ann"] > best[2]["sharpe_ann"]:
            best = (w, 1 - w, sp)
    for w in (1.0, best[0], 0.7, 0.5, 0.0):
        port = w * cx + (1 - w) * bx; sp = stats(list(port))
        tag = "  <-MAX" if abs(w - best[0]) < 1e-9 else ""
        print(f"      {w:>5.2f} {1-w:>5.2f} {sp['mean']:>+7.2f} {sp['sd']:>6.2f} "
              f"{sp['sharpe_ann']:>+7.2f} {sp['maxdd']:>8.1f} {sp['mn']:>+7.2f}{tag}")

    # vol-matched: scale FX to champion vol so it contributes EQUAL risk
    k = sc_o["sd"] / sb_o["sd"] if sb_o["sd"] > 0 else 0.0
    bx_s = bx * k
    print(f"\n  (b) vol-matched (FX scaled x{k:.1f} to champ vol), equal-risk blends:")
    print(f"      {'w_ch':>5} {'w_fx':>5} {'mean%':>7} {'sd':>6} {'Sh_ann':>7} {'maxDD%':>8} {'min%':>7}")
    vbest = None
    for w in np.arange(0.0, 1.01, 0.05):
        port = w * cx + (1 - w) * bx_s; sp = stats(list(port))
        if vbest is None or sp["sharpe_ann"] > vbest[2]["sharpe_ann"]:
            vbest = (w, 1 - w, sp)
    for w in (1.0, vbest[0], 0.6, 0.5):
        port = w * cx + (1 - w) * bx_s; sp = stats(list(port))
        tag = "  <-MAX" if abs(w - vbest[0]) < 1e-9 else ""
        print(f"      {w:>5.2f} {1-w:>5.2f} {sp['mean']:>+7.2f} {sp['sd']:>6.2f} "
              f"{sp['sharpe_ann']:>+7.2f} {sp['maxdd']:>8.1f} {sp['mn']:>+7.2f}{tag}")

    # choose the MAX-Sharpe vol-matched portfolio as the diversified base
    w_ch = vbest[0]
    port_base = w_ch * cx + (1 - w_ch) * bx_s
    pstat = stats(list(port_base))
    print(f"\n  -> DIVERSIFIED BASE (vol-matched, w_champ={w_ch:.2f}): "
          f"mean={pstat['mean']:+.2f}% sd={pstat['sd']:.2f} Sharpe_ann={pstat['sharpe_ann']:+.2f} "
          f"maxDD={pstat['maxdd']:.1f}% min={pstat['mn']:+.2f}% pos={pstat['n']-pstat['neg']}/{pstat['n']}")

    # ---- [5] LEVER DIVERSIFIED PORTFOLIO TO 15%/mo ----
    print("\n[5] LEVER DIVERSIFIED PORTFOLIO -> mean ~15%/mo")
    Ld, dstat = lever_distribution(list(port_base), 15.0)
    lev_div = np.array(port_base) * Ld
    print(f"    leverage L={Ld:.2f}x  (on the diversified base)")
    print(f"    mean={dstat['mean']:+.2f}% median={dstat['med']:+.2f}% sd={dstat['sd']:.2f}")
    print(f"    %positive={ (dstat['n']-dstat['neg'])/dstat['n']*100:.1f}%  "
          f"MIN month={dstat['mn']:+.2f}%  maxDD={dstat['maxdd']:.1f}%")
    below8 = int((lev_div < 8).sum())
    print(f"    consistency: std={dstat['sd']:.2f}%  #months<+8%={below8}/{dstat['n']}  "
          f"#neg={dstat['neg']}/{dstat['n']}  Sharpe_ann={dstat['sharpe_ann']:+.2f}")

    # ---- [6] CHAMPION-ALONE LEVERED TO 15% (the rejected savruk profile) ----
    print("\n[6] CHAMPION-ALONE levered -> mean ~15%/mo (diversification benefit check)")
    Lc, cstat = lever_distribution(list(cx), 15.0)
    lev_c = np.array(cx) * Lc
    print(f"    leverage L={Lc:.2f}x  (champion alone, no diversification)")
    print(f"    mean={cstat['mean']:+.2f}% median={cstat['med']:+.2f}% sd={cstat['sd']:.2f}")
    print(f"    %positive={(cstat['n']-cstat['neg'])/cstat['n']*100:.1f}%  "
          f"MIN month={cstat['mn']:+.2f}%  maxDD={cstat['maxdd']:.1f}%")
    below8c = int((lev_c < 8).sum())
    print(f"    consistency: std={cstat['sd']:.2f}%  #months<+8%={below8c}/{cstat['n']}  "
          f"#neg={cstat['neg']}/{cstat['n']}  Sharpe_ann={cstat['sharpe_ann']:+.2f}")

    # ---- monthly listing for the levered diversified ----
    print("\n[7] LEVERED DIVERSIFIED — full monthly series:")
    for i, m in enumerate(common):
        flag = " *<8" if lev_div[i] < 8 else ("  NEG" if lev_div[i] < 0 else "")
        print(f"    {m}  {lev_div[i]:>+7.2f}%{flag}")

    return dict(common=common, fx_bm=fx_bm, champ_bm=champ_bm, rho=rho,
                w_ch=w_ch, Ld=Ld, dstat=dstat, Lc=Lc, cstat=cstat,
                pstat=pstat, sfx=sfx, sc=sc, p_shuf=p_shuf)


if __name__ == "__main__":
    main()
