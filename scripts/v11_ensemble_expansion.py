"""HYP-2026-06-02-v11-ensemble-expansion.

GOAL (decisive, honest): can we raise the multi-TF VSA-WIDESTOP stack's SHARPE
(=> more return at the SAME -23% DD) by adding GENUINELY-uncorrelated legs?
No leverage as the source of return; leverage only used afterwards to scale to the
-23% DD cap for an apples-to-apples return comparison.

We reuse v9's deployed harness (true engine, BASELINE exit, true fee 18bps, production
replay with live YAML mechanics) and test three diversification EXTENSIONS:

  EXT-1  More symbols / breadth.
         - 5m is data-capped at 10 syms; 15m at 19.
         - Build 30m & 45m legs by resampling 15m's 19-sym universe (broader than the
           v9 30m/45m which resampled 5m's 10-sym universe). More independent trades.

  EXT-2  Parameter ensemble of VSA-WIDESTOP: same signal, different sl_pct_min thresholds
         (0.025 / 0.030 / 0.035) as separate legs. HONEST RISK: param variants of the
         SAME signal are usually highly monthly-correlated => NO real diversification.
         We MEASURE inter-leg monthly rho and only count a leg if rho is genuinely low.

  EXT-3  Exit ensemble: BASELINE exit + a tighter R-target exit variant as a parallel leg
         on the same TF. Measure monthly rho; keep only if uncorrelated.

DECISIVE METRIC: for each addition that genuinely lowers portfolio monthly correlation,
report new portfolio Sharpe + return, then lever to the -23% DD cap and compare the
return-at(-23%DD) vs the current stack. Gate: inter-leg rho < ~0.5, shuffle p_gross<0.05,
walk-forward IS/OOS, % positive months.

Usage: PA_FEE_RT_BPS=18 .venv/bin/python scripts/v11_ensemble_expansion.py
"""
from __future__ import annotations
import os, sys, json
from pathlib import Path
os.environ["PA_DUCKDB_READ_ONLY"] = "true"
os.environ["PA_LOG_QUIET"] = "1"
import warnings; warnings.filterwarnings("ignore")
import logging; logging.getLogger("price_action").setLevel(logging.ERROR)
import numpy as np, pandas as pd, duckdb
from dataclasses import replace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "src"))
import importlib.util
# reuse v9 module wholesale (it imports wlr, engine, replay, builds resampled legs)
spec = importlib.util.spec_from_file_location("v9", str(ROOT / "scripts" / "v9_multitf_truefee.py"))
v9 = importlib.util.module_from_spec(spec); spec.loader.exec_module(v9)
wlr = v9.wlr
from price_action.backtest.engine import BacktestEngine
from price_action.signals.filters import volume_zscore
from price_action.strategies.vsa_climax_test import VSAClimaxTestStrategy, _default_manifest

SYMS10 = v9.SYMS10
SYMS19 = v9.SYMS19
FEE = v9.FEE_RT_BPS
IS_END = v9.IS_END

# tighter R-target exit variant for EXT-3 (closes more at TP1/TP2, no runner-stretch)
TIGHT_EXIT = dict(
    runner_trail_mult=1.0, trail_activate_stage=1,
    tp1_R=0.8, tp2_R=1.2, tp1_close_pct=0.50, tp2_close_pct=0.30,
    runner_force_exit_method="time", runner_force_exit_bars=20,
    force_exit_from_entry=False,
)


def sl_pct_of(t):  # noqa
    return v9.sl_pct_of(t)


def slice_slpct(pool, lo):
    return [t for t in pool if sl_pct_of(t) >= lo]


def msr(pool, lev=1.0):
    """monthly series + maxdd"""
    return v9.monthly_series(pool, lev)


def stats(ms):
    return v9.stats(ms)


def lever_to_dd(pool, dd_cap=-23.0, lmax=2.5):
    """Find the largest leverage keeping MaxDD >= dd_cap; return (L, mean, dd, sharpe, pos)."""
    best = None
    for L in np.arange(1.0, lmax + 1e-9, 0.05):
        ms, dd = msr(pool, float(L))
        s = stats(ms)
        if dd >= dd_cap:
            best = (float(L), s["mean"], dd, s["sharpe"], s["pos"])
        else:
            break
    if best is None:  # even L=1 breaches cap
        ms, dd = msr(pool, 1.0); s = stats(ms)
        return (1.0, s["mean"], dd, s["sharpe"], s["pos"])
    return best


def gather_resampled_from(syms, rule, src_tf, fee_override=None):
    """Resample a SOURCE timeframe (e.g. 15m -> 30m) for broader-breadth legs.
    label-left, closed-left => no lookahead. Mirrors v9.gather_resampled but lets us
    pick the source TF so 30m/45m can use 15m's 19-sym universe."""
    fee = v9.fee_dict(fee_override if fee_override is not None else FEE)
    pool = []
    con = duckdb.connect(str(v9.DB), read_only=True)
    for sym in syms:
        df0 = con.execute(
            "SELECT ts,open,high,low,close,volume FROM ohlcv WHERE venue='binance' "
            "AND symbol=? AND timeframe=? ORDER BY ts", [sym, src_tf]).fetchdf()
        if df0.empty:
            continue
        df0["ts"] = pd.to_datetime(df0["ts"], utc=True)
        df0 = df0.sort_values("ts").reset_index(drop=True)
        g = df0.set_index("ts").resample(rule, label="left", closed="left")
        df = g.agg({"open": "first", "high": "max", "low": "min",
                    "close": "last", "volume": "sum"}).dropna().reset_index()
        if len(df) < 100:
            continue
        df["symbol"], df["venue"], df["timeframe"] = sym, "binance", "15m"
        try:
            df["vol_z_pre"] = volume_zscore(df["volume"], period=20)
        except Exception:
            roll = df["volume"].rolling(20)
            df["vol_z_pre"] = (df["volume"] - roll.mean()) / roll.std()
        s = VSAClimaxTestStrategy(_default_manifest())

        def prov(*a, **k):
            return df.copy()

        e = BacktestEngine(risk_officer=None, store_load=None, **v9.BASELINE_EXIT)
        r = e.run(s, [sym], start=df["ts"].iloc[0].to_pydatetime(),
                  end=df["ts"].iloc[-1].to_pydatetime(), timeframe="15m",
                  initial_capital=10_000.0, fees=fee, slippage_bps=0.0, ohlcv_provider=prov)
        if r.trades is None or r.trades.empty:
            continue
        for _, t in r.trades.iterrows():
            try:
                ep, sp = float(t["entry_price"]), float(t["initial_sl"])
                te = pd.Timestamp(t["entry_ts"]); te = te.tz_localize("UTC") if te.tzinfo is None else te
                tx = pd.Timestamp(t["exit_ts"]); tx = tx.tz_localize("UTC") if tx.tzinfo is None else tx
                rp = abs(sp - ep) / ep if ep > 0 else 0.04
                pool.append({"entry_ts": te, "exit_ts": tx, "entry_price": ep, "initial_sl": sp,
                             "R": float(t["realized_r_multiple"]), "peak_R": float(t["realized_r_multiple"]),
                             "symbol": sym, "side": str(t["side"]), "conf": 0.5, "vol_z": 0.0,
                             "strategy": "vsa_climax_test",
                             "hold_h": (tx - te) / pd.Timedelta(hours=1)})
            except Exception:
                continue
    con.close()
    return slice_slpct(pool, v9.SL_PCT_MIN)


def gather_native_exit(syms, tf, exit_cfg):
    pool = []
    for s in syms:
        pool += wlr.gather(s, exit_cfg, tf=tf)
    return slice_slpct(pool, v9.SL_PCT_MIN)


def inter_leg_rho(leg_pools: dict):
    mser = {}
    for nm, p in leg_pools.items():
        if not p:
            continue
        ms, _ = msr(p)
        mser[nm] = ms
    mdf = pd.DataFrame(mser)
    return mdf.corr()


def print_rho(corr, title):
    names = list(corr.columns)
    print(f"\n--- {title} (monthly-ROI rho) ---")
    print("        " + " ".join(f"{n:>8}" for n in names))
    for a in names:
        print(f"{a:>7} " + " ".join(f"{corr.loc[a,b]:>8.2f}" for b in names))


def main():
    print("=" * 100)
    print(f"v11 ENSEMBLE EXPANSION @ true fee {FEE}bps — diversify for Sharpe at -23% DD cap")
    print("=" * 100)

    # ---- BASE: reconstruct v9 deploy stack (5m@10 + 15m@19 + resampled 30m/45m from 5m@10) ----
    print("\ngathering base legs ...")
    p05 = v9.gather_native(SYMS10, "5m")
    p15 = v9.gather_native(SYMS19, "15m")
    p30_5 = v9.gather_resampled(SYMS10, "30min", "30m")  # from 5m, 10 sym (v9 way)
    p45_5 = v9.gather_resampled(SYMS10, "45min", "45m")
    print(f"  5m@10={len(p05)}  15m@19={len(p15)}  30m(<-5m@10)={len(p30_5)}  45m(<-5m@10)={len(p45_5)}")

    base_legs = {"5m": p05, "15m": p15, "30m5": p30_5, "45m5": p45_5}
    base_stack = [t for p in base_legs.values() for t in p]
    ms_b, dd_b = msr(base_stack); s_b = stats(ms_b)
    Lb, mb, ddb, shb, posb = lever_to_dd(base_stack)
    print(f"\nBASE STACK (v9 deploy)  n={len(base_stack)}  unlev mean={s_b['mean']:+.2f}%/mo "
          f"DD={dd_b:+.1f}% Sharpe={s_b['sharpe']:+.2f} pos={s_b['pos']:.0f}%")
    print(f"  -> levered to -23% DD: L={Lb:.2f} mean={mb:+.2f}%/mo DD={ddb:+.1f}% Sharpe={shb:+.2f}")
    print_rho(inter_leg_rho(base_legs), "BASE inter-leg")

    # ============ EXT-1: broader-breadth resampled legs (30m/45m FROM 15m's 19-sym) ============
    print("\n" + "=" * 100)
    print("EXT-1  BROADER BREADTH: 30m & 45m resampled from 15m's 19-sym universe")
    print("=" * 100)
    p30_19 = gather_resampled_from(SYMS19, "30min", "15m")
    p45_19 = gather_resampled_from(SYMS19, "45min", "15m")
    p60_19 = gather_resampled_from(SYMS19, "60min", "15m")
    p90_19 = gather_resampled_from(SYMS19, "90min", "15m")
    print(f"  30m@19={len(p30_19)} 45m@19={len(p45_19)} 60m@19={len(p60_19)} 90m@19={len(p90_19)}")
    ext1_legs = {"5m": p05, "15m": p15, "30m19": p30_19, "45m19": p45_19, "60m19": p60_19, "90m19": p90_19}
    print_rho(inter_leg_rho(ext1_legs), "EXT-1 inter-leg")
    for nm in ["30m19", "45m19", "60m19", "90m19"]:
        ms, dd = msr(ext1_legs[nm]); s = stats(ms)
        print(f"  standalone {nm:<6} n={len(ext1_legs[nm]):>4} mean={s['mean']:+.2f}% DD={dd:+.1f}% Sharpe={s['sharpe']:+.2f} pos={s['pos']:.0f}%")

    # greedy: start from broader-breadth core 5m+15m, add 30/45/60/90@19 if Sharpe-at-23DD rises
    print("\n  greedy add (keep if levered-to-23%DD return rises):")
    cur = {"5m": p05, "15m": p15}
    cur_stack = [t for p in cur.values() for t in p]
    _, mcur, _, shcur, _ = lever_to_dd(cur_stack)
    print(f"  core 5m+15m: L-to-23DD return={mcur:+.2f}%/mo Sharpe={shcur:+.2f}")
    for nm, p in [("30m19", p30_19), ("45m19", p45_19), ("60m19", p60_19), ("90m19", p90_19)]:
        trial = dict(cur); trial[nm] = p
        ts = [t for pp in trial.values() for t in pp]
        L, m, dd, sh, pos = lever_to_dd(ts)
        keep = m > mcur + 0.10
        print(f"    +{nm:<6} -> L={L:.2f} ret@23DD={m:+.2f}%/mo Sharpe={sh:+.2f} pos={pos:.0f}%  [{'KEEP' if keep else 'drop'}]")
        if keep:
            cur = trial; cur_stack = ts; mcur = m; shcur = sh
    ext1_final = cur
    print(f"  EXT-1 final legs: {list(ext1_final.keys())}")
    ext1_stack = [t for p in ext1_final.values() for t in p]
    L1, m1, dd1, sh1, pos1 = lever_to_dd(ext1_stack)
    ms1u, dd1u = msr(ext1_stack); s1u = stats(ms1u)
    print(f"  EXT-1 stack: unlev mean={s1u['mean']:+.2f}% Sharpe={s1u['sharpe']:+.2f} DD={dd1u:+.1f}%  |  "
          f"@23DD L={L1:.2f} ret={m1:+.2f}%/mo Sharpe={sh1:+.2f} pos={pos1:.0f}%")

    # ============ EXT-2: parameter ensemble (sl_pct thresholds as legs) on 15m@19 ============
    print("\n" + "=" * 100)
    print("EXT-2  PARAM ENSEMBLE: 15m@19 sliced at sl_pct_min 0.025 / 0.030 / 0.035 as legs")
    print("=" * 100)
    # gather once at lowest threshold then slice
    p15_raw = []
    for s in SYMS19:
        p15_raw += wlr.gather(s, v9.BASELINE_EXIT, tf="15m")
    leg_025 = slice_slpct(p15_raw, 0.025)
    leg_030 = slice_slpct(p15_raw, 0.030)
    leg_035 = slice_slpct(p15_raw, 0.035)
    print(f"  sl>=.025 n={len(leg_025)}  sl>=.030 n={len(leg_030)}  sl>=.035 n={len(leg_035)}")
    print("  NOTE: these are NESTED subsets of the same trades -> expect VERY high monthly rho")
    ext2_legs = {"sl025": leg_025, "sl030": leg_030, "sl035": leg_035}
    print_rho(inter_leg_rho(ext2_legs), "EXT-2 inter-leg (param)")

    # ============ EXT-3: exit ensemble (BASELINE + TIGHT) on 15m@19 ============
    print("\n" + "=" * 100)
    print("EXT-3  EXIT ENSEMBLE: 15m@19 BASELINE exit + TIGHT R-target exit as parallel legs")
    print("=" * 100)
    p15_tight = gather_native_exit(SYMS19, "15m", TIGHT_EXIT)
    print(f"  BASELINE n={len(p15)}  TIGHT n={len(p15_tight)}")
    ext3_legs = {"base15": p15, "tight15": p15_tight}
    print_rho(inter_leg_rho(ext3_legs), "EXT-3 inter-leg (exit)")
    for nm, p in ext3_legs.items():
        ms, dd = msr(p); s = stats(ms)
        print(f"  standalone {nm:<8} mean={s['mean']:+.2f}% Sharpe={s['sharpe']:+.2f} DD={dd:+.1f}% pos={s['pos']:.0f}%")

    # ============ BEST EXPANDED ENSEMBLE ============
    # Combine only genuinely-uncorrelated additions: broader-breadth TF legs (EXT-1) +,
    # if exit leg rho<0.5, the tight exit leg. Param ensemble dropped if nested-correlated.
    print("\n" + "=" * 100)
    print("BEST EXPANDED ENSEMBLE — combine only legs with monthly rho < 0.5 vs the stack")
    print("=" * 100)
    best = dict(ext1_final)
    # try adding tight-exit leg
    rho_exit = inter_leg_rho(ext3_legs).loc["base15", "tight15"]
    L0, m0, dd0, sh0, pos0 = lever_to_dd([t for p in best.values() for t in p])
    trial = dict(best); trial["tight15"] = p15_tight
    Lt, mt, ddt, sht, post = lever_to_dd([t for p in trial.values() for t in p])
    keep_exit = (abs(rho_exit) < 0.5) and (mt > m0 + 0.10)
    print(f"  +tight-exit leg: base-tight rho={rho_exit:.2f}  ret@23DD {m0:+.2f}->{mt:+.2f}%/mo  [{'KEEP' if keep_exit else 'drop'}]")
    if keep_exit:
        best = trial
    best_stack = [t for p in best.values() for t in p]
    Lf, mf, ddf, shf, posf = lever_to_dd(best_stack)
    msfu, ddfu = msr(best_stack); sfu = stats(msfu)
    print(f"\n  BEST legs: {list(best.keys())}  n={len(best_stack)}")
    print(f"  unlev: mean={sfu['mean']:+.2f}%/mo Sharpe={sfu['sharpe']:+.2f} DD={ddfu:+.1f}% pos={sfu['pos']:.0f}%")
    print(f"  @23%DD: L={Lf:.2f} ret={mf:+.2f}%/mo DD={ddf:+.1f}% Sharpe={shf:+.2f} pos={posf:.0f}%")

    # ---- gates on BEST ----
    print("\n--- GATES on BEST expanded ensemble ---")
    pg = wlr.shuffle_p([t["R"] for t in best_stack], n_iter=4000)
    print(f"  shuffle p_gross={pg:.4f} ({'PASS' if pg<0.05 else 'FAIL'})")
    is_t = [t for t in best_stack if t["entry_ts"] < IS_END]
    oos_t = [t for t in best_stack if t["entry_ts"] >= IS_END]
    for nm, tt in [("IS[..2024)", is_t), ("OOS[2024..)", oos_t)]:
        if tt:
            ms3, dd3 = msr(tt); s3 = stats(ms3)
            print(f"  {nm:<12} mean={s3['mean']:+.2f}%/mo pos={s3['pos']:.0f}% DD={dd3:+.1f}% Sharpe={s3['sharpe']:+.2f}")

    # ---- final comparison table @ -23% DD ----
    print("\n" + "=" * 100)
    print("VERDICT TABLE — return at MaxDD <= -23% (levered to cap)")
    print("=" * 100)
    print(f"{'stack':<28} {'unlevSharpe':>11} {'L':>5} {'ret@23DD':>9} {'DD':>7} {'pos':>5}")
    for nm, st in [("BASE (v9 deploy)", base_stack),
                   ("EXT-1 broad-breadth", ext1_stack),
                   ("BEST expanded", best_stack)]:
        msu, ddu = msr(st); su = stats(msu)
        L, m, dd, sh, pos = lever_to_dd(st)
        print(f"{nm:<28} {su['sharpe']:>11.2f} {L:>5.2f} {m:>+8.2f}% {dd:>+6.1f}% {pos:>4.0f}%")

    out = dict(fee=FEE,
               base=dict(sharpe=s_b["sharpe"], L=Lb, ret23=mb, dd23=ddb),
               ext1=dict(legs=list(ext1_final.keys()), sharpe=s1u["sharpe"], L=L1, ret23=m1, dd23=dd1),
               ext2_rho=inter_leg_rho(ext2_legs).round(3).to_dict(),
               ext3_rho=float(rho_exit),
               best=dict(legs=list(best.keys()), sharpe=sfu["sharpe"], L=Lf, ret23=mf, dd23=ddf, pos=posf),
               p_gross=pg)
    json.dump(out, open("/tmp/v11_ensemble_expansion.json", "w"), indent=2, default=str)
    print("\n[dumped /tmp/v11_ensemble_expansion.json]")


if __name__ == "__main__":
    main()
