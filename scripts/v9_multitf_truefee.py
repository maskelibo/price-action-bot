"""HYP-2026-06-02-v9-multitf-truefee-15pct.

GOAL (decisive, honest): does a multi-TF VSA-WIDESTOP + BASELINE-exit stack, priced
at the TRUE empirical fee (PA_FEE_RT_BPS, default 18bps round-trip), reach ~15%/mo at
the SAME drawdown (<= -18 to -20%) — crypto-only, no forex, no fabrication?

Two honest improvements compound:
  1. Multi-TF stacking (v8): nearly-uncorrelated monthly streams (rho~0.12) smooth
     variance -> more return at the same DD.
  2. True fee 18bps vs the over-punitive 55bps (v7): lowers cost on EVERY leg.

METHOD (reuses deployed harness, artifact-free):
  - Trades via REAL BacktestEngine through wlr.gather (same as v8).
  - BASELINE exit (trail ATR 1.5, stage 2, TP1 30%@1R / TP2 30%@1.5R / runner 40%,
    time-stop 30, NOT from entry) — the exit behind the cited champion bar.
  - FEE: round-trip bps from env PA_FEE_RT_BPS (default 18). Split as taker per-leg =
    rt/2/10000, slippage 0 (the rt already includes empirical slippage in v7's number).
  - Resampled TFs (30m, 45m) are built from the native 5m bars (true sub-bar OHLCV
    resample, label='left' so no lookahead). 4h is native. Engine label passed is a
    valid freq_map key but unused for our own monthly/DD math (we compute those).
  - Portfolio replay via production_replay with live YAML mechanics (risk 0.5%,
    sl_pct_min 0.025, DD halts, concentration, notional cap).

PESSIMISTIC 5m STRESS: re-run with the 5m leg priced at a worse fee (30-40bps) while
other legs stay at 18bps — small-cap 5m execution honesty check.

Usage: PA_FEE_RT_BPS=18 .venv/bin/python scripts/v9_multitf_truefee.py
"""
from __future__ import annotations
import os, sys, json
from pathlib import Path
os.environ["PA_DUCKDB_READ_ONLY"] = "true"
os.environ["PA_LOG_QUIET"] = "1"
import warnings; warnings.filterwarnings("ignore")
import logging; logging.getLogger("price_action").setLevel(logging.ERROR)
import numpy as np, pandas as pd, duckdb

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "src"))
import importlib.util
spec = importlib.util.spec_from_file_location(
    "wlr", str(ROOT / "scripts" / "crypto_winner_let_run_vsa_exit.py"))
wlr = importlib.util.module_from_spec(spec); spec.loader.exec_module(wlr)
from price_action.backtest.engine import BacktestEngine
from price_action.backtest.lab import ProductionConfig, production_replay
from price_action.signals.filters import volume_zscore
from price_action.strategies.vsa_climax_test import VSAClimaxTestStrategy, _default_manifest
from dataclasses import replace

YAML = ROOT / "configs" / "risk_phoenix_scalp_15m_widestop_vsa2.yaml"
DB = ROOT / "data" / "market.duckdb"
SYMS10 = ["BTC/USDT","ETH/USDT","SOL/USDT","BNB/USDT","ADA/USDT","AVAX/USDT",
          "LINK/USDT","DOT/USDT","DOGE/USDT","XRP/USDT"]
SYMS19 = SYMS10 + ["ZEC/USDT","NEAR/USDT","FIL/USDT","XLM/USDT","TRX/USDT",
                   "UNI/USDT","ATOM/USDT","AAVE/USDT","ALGO/USDT"]
SL_PCT_MIN = 0.025
RISK_PCT = 0.005
SEED = 12345

FEE_RT_BPS = float(os.environ.get("PA_FEE_RT_BPS", "18"))

BASELINE_EXIT = dict(
    runner_trail_mult=1.5, trail_activate_stage=2,
    tp1_R=1.0, tp2_R=1.5, tp1_close_pct=0.30, tp2_close_pct=0.30,
    runner_force_exit_method="time", runner_force_exit_bars=30,
    force_exit_from_entry=False,
)


def fee_dict(rt_bps):
    per_leg = (rt_bps / 2.0) / 10000.0
    return {"taker": per_leg, "maker": per_leg}  # symmetric; rt includes slippage already


# patch wlr global fee + slippage so gather() uses the env fee, slippage folded in.
wlr.FEES = fee_dict(FEE_RT_BPS)
wlr.SLIPPAGE_BPS = 0.0
wlr.SL_PCT_MIN = SL_PCT_MIN

IS_END = pd.Timestamp("2024-01-01", tz="UTC")
OOS_END = pd.Timestamp("2026-07-01", tz="UTC")


def sl_pct_of(t):
    ep = t["entry_price"]
    return abs(t["initial_sl"] - ep) / ep if ep > 0 else 0.04


def cont_dd(eq):
    peak = eq[0]; mdd = 0.0
    for v in eq:
        peak = max(peak, v); mdd = min(mdd, (v - peak) / peak if peak > 0 else 0.0)
    return mdd * 100.0


def monthly_from_replay(res, cfg):
    eq = res.equity_curve or []; ts = res.entry_ts_list or []
    if len(eq) < 2 or not ts:
        return pd.Series(dtype=float)
    n = min(len(eq) - 1, len(ts))
    stamps = pd.to_datetime(ts[:n], utc=True)
    df = pd.DataFrame({"ts": stamps, "eq": eq[1:n + 1]})
    df["m"] = df["ts"].dt.to_period("M")
    me = df.groupby("m")["eq"].last()
    prev = me.shift(1, fill_value=cfg.initial_capital)
    return (me / prev - 1.0) * 100.0


def stats(mr):
    if mr is None or mr.empty:
        return dict(n=0, mean=0, med=0, pos=0, mn=0, sd=0, sharpe=0)
    return dict(n=len(mr), mean=float(mr.mean()), med=float(mr.median()),
                pos=float((mr > 0).mean() * 100), mn=float(mr.min()),
                sd=float(mr.std()),
                sharpe=float(mr.mean() / mr.std() * np.sqrt(12)) if mr.std() > 0 else 0.0)


def build_cfg(lev=1.0):
    c = ProductionConfig.from_yaml(str(YAML))
    c = replace(c, risk_pct=RISK_PCT * lev, sl_pct_min=max(c.sl_pct_min, SL_PCT_MIN))
    if c.max_notional_pct_equity is not None:
        c = replace(c, max_notional_pct_equity=c.max_notional_pct_equity * lev)
    if c.concentration_max_per_symbol_pct is not None:
        c = replace(c, concentration_max_per_symbol_pct=c.concentration_max_per_symbol_pct * lev)
    return c


# ---------- native gather (env fee) ----------
def gather_native(syms, tf, fee_override=None):
    saved = wlr.FEES
    if fee_override is not None:
        wlr.FEES = fee_dict(fee_override)
    pool = []
    for s in syms:
        pool += wlr.gather(s, BASELINE_EXIT, tf=tf)
    wlr.FEES = saved
    return [t for t in pool if sl_pct_of(t) >= SL_PCT_MIN]


# ---------- resampled gather (build N-min bars from native 5m) ----------
def _load_5m(sym):
    con = duckdb.connect(str(DB), read_only=True)
    df = con.execute(
        "SELECT ts,open,high,low,close,volume FROM ohlcv WHERE venue='binance' "
        "AND symbol=? AND timeframe='5m' ORDER BY ts", [sym]).fetchdf()
    con.close()
    if df.empty:
        return df
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    return df.sort_values("ts").reset_index(drop=True)


def _resample(df, rule):
    g = df.set_index("ts").resample(rule, label="left", closed="left")
    out = g.agg({"open": "first", "high": "max", "low": "min",
                 "close": "last", "volume": "sum"}).dropna().reset_index()
    return out


def gather_resampled(syms, rule, label, fee_override=None):
    """Resample native 5m -> N-min bars, run engine on them. label-left = no lookahead."""
    fee = fee_dict(fee_override if fee_override is not None else FEE_RT_BPS)
    pool = []
    for sym in syms:
        base = _load_5m(sym)
        if base.empty:
            continue
        df = _resample(base, rule)
        if len(df) < 100:
            continue
        # df timeframe column must be a valid Signal literal; bar processing is df-driven
        # (each row = one resampled bar) so we label it "15m" (a valid literal). The actual
        # bar duration is encoded in the resampled OHLCV itself; our monthly/DD math uses ts.
        df["symbol"], df["venue"], df["timeframe"] = sym, "binance", "15m"
        try:
            df["vol_z_pre"] = volume_zscore(df["volume"], period=20)
        except Exception:
            roll = df["volume"].rolling(20)
            df["vol_z_pre"] = (df["volume"] - roll.mean()) / roll.std()
        s = VSAClimaxTestStrategy(_default_manifest())

        def prov(*a, **k):
            return df.copy()

        e = BacktestEngine(risk_officer=None, store_load=None, **BASELINE_EXIT)
        r = e.run(s, [sym], start=df["ts"].iloc[0].to_pydatetime(),
                  end=df["ts"].iloc[-1].to_pydatetime(), timeframe="15m",
                  initial_capital=10_000.0, fees=fee, slippage_bps=0.0,
                  ohlcv_provider=prov)
        if r.trades is None or r.trades.empty:
            continue
        for _, t in r.trades.iterrows():
            try:
                ep, sp = float(t["entry_price"]), float(t["initial_sl"])
                te = pd.Timestamp(t["entry_ts"]); te = te.tz_localize("UTC") if te.tzinfo is None else te
                tx = pd.Timestamp(t["exit_ts"]); tx = tx.tz_localize("UTC") if tx.tzinfo is None else tx
                conf = max(0.0, min(1.0, (float(t["confluence_score"]) - 1.5) / 1.5))
                mfe_pct = float(t.get("mfe_pct", 0))
                rp = abs(sp - ep) / ep if ep > 0 else 0.04
                side = str(t["side"]).lower()
                final_R = float(t["realized_r_multiple"])
                pk = (mfe_pct / rp if side == "long" else -mfe_pct / rp) if rp > 0 else 0
                pk = max(pk, final_R)
                pool.append({"entry_ts": te, "exit_ts": tx, "entry_price": ep, "initial_sl": sp,
                             "R": final_R, "peak_R": pk, "symbol": sym,
                             "side": str(t["side"]), "conf": conf, "vol_z": 0.0,
                             "strategy": "vsa_climax_test",
                             "hold_h": (tx - te) / pd.Timedelta(hours=1)})
            except Exception:
                continue
    return [t for t in pool if sl_pct_of(t) >= SL_PCT_MIN]


def run_pool(pool, lev=1.0):
    r = production_replay(sorted(pool, key=lambda x: x["entry_ts"]), build_cfg(lev))
    return stats(monthly_from_replay(r, build_cfg(lev))), cont_dd(r.equity_curve), r


def monthly_series(pool, lev=1.0):
    cfg = build_cfg(lev)
    r = production_replay(sorted(pool, key=lambda x: x["entry_ts"]), cfg)
    return monthly_from_replay(r, cfg), cont_dd(r.equity_curve)


def clip_common(pools):
    los = [min(t["entry_ts"] for t in p) for p in pools if p]
    his = [max(t["entry_ts"] for t in p) for p in pools if p]
    lo, hi = max(los), min(his)
    return lo, hi, [[t for t in p if lo <= t["entry_ts"] <= hi] for p in pools]


def main():
    print("=" * 100)
    print(f"v9 MULTI-TF STACK @ TRUE FEE  PA_FEE_RT_BPS={FEE_RT_BPS}  (per-leg taker={FEE_RT_BPS/2:.1f}bps, slip folded)")
    print("=" * 100)

    # --- gather all candidate legs (10-sym common universe for honest cross-TF compare) ---
    print("gathering native legs (5m, 15m, 1h, 4h) on 10-sym...")
    p05 = gather_native(SYMS10, "5m")
    p15 = gather_native(SYMS10, "15m")
    p1h = gather_native(SYMS10, "1h")
    p4h = gather_native(SYMS10, "4h")
    print(f"  native: 5m={len(p05)} 15m={len(p15)} 1h={len(p1h)} 4h={len(p4h)}")
    print("resampling 5m -> 30m, 45m ...")
    p30 = gather_resampled(SYMS10, "30min", "30m")
    p45 = gather_resampled(SYMS10, "45min", "45m")
    print(f"  resampled: 30m={len(p30)} 45m={len(p45)}")

    legs = {"5m": p05, "15m": p15, "30m": p30, "45m": p45, "1h": p1h, "4h": p4h}

    # --- per-leg standalone profile (full own window) @ true fee ---
    print(f"\n{'leg':<8} {'n':>6} {'mean':>7} {'med':>7} {'pos':>5} {'min':>7} {'MaxDD':>7} {'Sharpe':>7}")
    for nm, p in legs.items():
        if not p:
            print(f"{nm:<8} (empty)"); continue
        s, dd, _ = run_pool(p)
        print(f"{nm:<8} {len(p):>6} {s['mean']:>+6.2f}% {s['med']:>+6.2f}% {s['pos']:>4.0f}% {s['mn']:>+6.2f}% {dd:>+6.1f}% {s['sharpe']:>+6.2f}")

    # --- monthly-ROI correlation matrix across legs (own-window aligned to months) ---
    print("\n--- inter-leg MONTHLY-ROI correlation (full overlap) ---")
    mser = {}
    for nm, p in legs.items():
        if not p:
            continue
        ms, _ = monthly_series(p)
        mser[nm] = ms
    names = list(mser.keys())
    mdf = pd.DataFrame({nm: mser[nm] for nm in names})
    corr = mdf.corr()
    print("      " + " ".join(f"{n:>6}" for n in names))
    for a in names:
        print(f"{a:>5} " + " ".join(f"{corr.loc[a,b]:>6.2f}" for b in names))

    # --- greedy stack build: start 5m+15m (v8 winner), add legs that LOWER DD-per-return ---
    print("\n" + "=" * 100)
    print("GREEDY STACK BUILD (common window) — keep a leg only if it raises return at <= -18% DD")
    print("=" * 100)
    base_legs = ["5m", "15m"]
    candidate_adds = ["30m", "45m", "1h", "4h"]

    def eval_stack(leg_names):
        pools = [legs[n] for n in leg_names]
        lo, hi, clipped = clip_common(pools)
        stack = [t for p in clipped for t in p]
        s, dd, _ = run_pool(stack)
        return s, dd, lo, hi, len(stack)

    cur = list(base_legs)
    s, dd, lo, hi, n = eval_stack(cur)
    print(f"BASE {'+'.join(cur):<20} window {lo.date()}->{hi.date()} n={n} "
          f"mean={s['mean']:+.2f}% pos={s['pos']:.0f}% min={s['mn']:+.2f}% DD={dd:+.1f}% Sharpe={s['sharpe']:+.2f}")
    base_score = s['mean']
    for add in candidate_adds:
        trial = cur + [add]
        s2, dd2, lo2, hi2, n2 = eval_stack(trial)
        # honest keep rule: must raise mean AND keep DD <= -18.5% (small tolerance)
        keep = (s2['mean'] > base_score + 0.05) and (dd2 >= -18.5)
        verdict = "KEEP" if keep else "drop"
        print(f"  +{add:<5} -> {'+'.join(trial):<22} win {lo2.date()}->{hi2.date()} n={n2} "
              f"mean={s2['mean']:+.2f}% pos={s2['pos']:.0f}% min={s2['mn']:+.2f}% DD={dd2:+.1f}% Sharpe={s2['sharpe']:+.2f}  [{verdict}]")
        if keep:
            cur = trial; base_score = s2['mean']
    print(f"\nOPTIMAL TF COMBO (common-window greedy): {'+'.join(cur)}")

    # --- DEPLOYABLE stack: 15m on full 19-sym + 5m on 10-sym (+ any kept extra legs), own full windows ---
    print("\n" + "=" * 100)
    print("DEPLOYABLE STACK (15m=19sym full history + 5m=10sym + kept legs), each leg own full window")
    print("=" * 100)
    p15_19 = gather_native(SYMS19, "15m")
    print(f"  15m(19sym) n={len(p15_19)}")
    deploy_legs = {"15m19": p15_19, "5m": p05}
    # add any extra TF leg the greedy kept beyond 5m+15m
    for extra in cur:
        if extra not in ("5m", "15m"):
            deploy_legs[extra] = legs[extra]
    deploy_stack = [t for p in deploy_legs.values() for t in p]
    print(f"  deploy legs: {list(deploy_legs.keys())}  total trades={len(deploy_stack)}")

    ms, dd = monthly_series(deploy_stack)
    s = stats(ms)
    print(f"\n--- DEPLOY STACK @ {FEE_RT_BPS}bps, UNLEVERED — FULL MONTHLY DISTRIBUTION ---")
    print(f"  n_months={s['n']}  mean={s['mean']:+.3f}%/mo  median={s['med']:+.3f}%  "
          f"pos={s['pos']:.1f}%  MIN_month={s['mn']:+.2f}%  sd={s['sd']:.2f}  "
          f"MaxDD={dd:+.2f}%  Sharpe_ann={s['sharpe']:+.2f}")
    pct = ms.quantile([0.05, 0.25, 0.5, 0.75, 0.95])
    print(f"  pctiles  5%={pct[0.05]:+.2f}  25%={pct[0.25]:+.2f}  50%={pct[0.5]:+.2f}  "
          f"75%={pct[0.75]:+.2f}  95%={pct[0.95]:+.2f}")
    worst5 = ms.nsmallest(5).round(2).tolist()
    print(f"  worst 5 months: {worst5}")

    # --- LEVERAGE GAP to 15%/mo ---
    print("\n" + "=" * 100)
    print("LEVERAGE GAP TO 15%/mo (deploy stack)")
    print("=" * 100)
    print(f"{'L':>5} {'mean':>7} {'med':>7} {'pos':>5} {'min':>7} {'MaxDD':>7} {'Sharpe':>7}")
    lev_rows = []
    for L in [1.0, 1.1, 1.2, 1.3, 1.4, 1.5, 1.75, 2.0]:
        s2, dd2, _ = run_pool(deploy_stack, L)
        lev_rows.append((L, s2['mean'], dd2, s2['pos'], s2['mn'], s2['sharpe']))
        print(f"{L:>5.2f} {s2['mean']:>+6.2f}% {s2['med']:>+6.2f}% {s2['pos']:>4.0f}% {s2['mn']:>+6.2f}% {dd2:>+6.1f}% {s2['sharpe']:>+6.2f}")
    # minimal L to hit 15% mean
    hit = [r for r in lev_rows if r[1] >= 15.0]
    if hit:
        h = min(hit, key=lambda r: r[0])
        print(f"\n  MIN L to reach 15%/mo: L={h[0]:.2f} -> mean={h[1]:+.2f}% MaxDD={h[2]:+.1f}% pos={h[3]:.0f}%")
    else:
        print("\n  15%/mo NOT reached within L<=2.0 (see table for ceiling/DD).")

    # --- PESSIMISTIC 5m FEE STRESS ---
    print("\n" + "=" * 100)
    print("PESSIMISTIC 5m FILL STRESS — 5m leg repriced @ 30bps & 40bps, others stay 18bps")
    print("=" * 100)
    for pess in [30.0, 40.0]:
        p05_pess = gather_native(SYMS10, "5m", fee_override=pess)
        dep = {"15m19": p15_19, "5m": p05_pess}
        for extra in cur:
            if extra not in ("5m", "15m"):
                dep[extra] = legs[extra]
        ds = [t for p in dep.values() for t in p]
        ms2, dd2 = monthly_series(ds)
        s2 = stats(ms2)
        print(f"  5m@{pess:.0f}bps + rest@18: mean={s2['mean']:+.2f}%/mo pos={s2['pos']:.0f}% "
              f"min={s2['mn']:+.2f}% MaxDD={dd2:+.1f}% Sharpe={s2['sharpe']:+.2f}")
        # min L to 15% under pessimistic 5m
        for L in [1.0, 1.2, 1.4, 1.6, 1.8, 2.0]:
            s3, dd3, _ = run_pool(ds, L)
            if s3['mean'] >= 15.0:
                print(f"     -> min L to 15% under 5m@{pess:.0f}: L={L:.1f} mean={s3['mean']:+.2f}% MaxDD={dd3:+.1f}%")
                break
        else:
            print(f"     -> 15% NOT reachable at L<=2.0 under 5m@{pess:.0f}bps")

    # --- shuffle gross p on deploy stack (gross = fee-independent edge) ---
    print("\n--- shuffle p_gross (deploy stack R, n=4000) ---")
    pg = wlr.shuffle_p([t["R"] for t in deploy_stack], n_iter=4000)
    print(f"  p_gross = {pg:.4f}  ({'PASS <0.05' if pg < 0.05 else 'FAIL'})")

    # --- walk-forward positive months (IS vs OOS) ---
    is_t = [t for t in deploy_stack if t["entry_ts"] < IS_END]
    oos_t = [t for t in deploy_stack if t["entry_ts"] >= IS_END]
    for nm, tt in [("IS[..2024)", is_t), ("OOS[2024..)", oos_t)]:
        if tt:
            ms3, dd3 = monthly_series(tt)
            s3 = stats(ms3)
            print(f"  {nm:<12} mean={s3['mean']:+.2f}%/mo pos={s3['pos']:.0f}% min={s3['mn']:+.2f}% MaxDD={dd3:+.1f}% Sharpe={s3['sharpe']:+.2f}")

    out = dict(fee_rt_bps=FEE_RT_BPS, optimal_combo=cur,
               deploy=dict(**s, maxdd=dd, worst5=worst5),
               lev_rows=lev_rows, p_gross=pg)
    json.dump(out, open("/tmp/v9_multitf_truefee.json", "w"), indent=2, default=str)
    print("\n[dumped /tmp/v9_multitf_truefee.json]")


if __name__ == "__main__":
    main()
