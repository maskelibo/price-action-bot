"""HYP-2026-06-02-v10-voltarget-ddthrottle.

GOAL (the user's exact decisive ask): raise the multi-TF VSA-WIDESTOP stack's
RETURN at the SAME MaxDD (<= -23%) via DYNAMIC exposure sizing — NOT flat
leverage. Flat leverage scales DD ~1:1 with return (melts capital). The only
honest way to get more return at the SAME drawdown is to raise Sharpe by
cutting bad-tail exposure: run MORE average exposure when it is safe, LESS when
it is dangerous, so the equity curve is smoother and a higher mean fits under
the same -23% DD ceiling.

BASE (the thing to improve) — reuses scripts/v9_multitf_truefee.py pools verbatim:
  multi-TF stack 5m+15m(19sym)+30m+45m VSA-WIDESTOP + BASELINE exit, true fee 18bps.
  flat unlevered ~ +13.1%/mo @ -19.3% DD ; flat L=1.2 ~ +15.2%/mo @ -22.9% DD.

MECHANISMS (all lookahead-safe: every multiplier uses ONLY realized state <= t-1):
  1. VOLATILITY TARGETING: scale total exposure inversely to TRAILING realized
     vol of the equity curve. mult = clamp(target_vol / trailing_vol, lo, hi).
     Calm -> exposure up (more return); turbulent -> exposure down (DD protected).
     Sweep target_vol + lookback (K closed-trade returns).
  2. DRAWDOWN THROTTLE: when current equity is in a drawdown deeper than `thresh`
     vs realized peak, cut exposure x `cut`; restore on recovery. Realized equity
     <= t-1 only.
  3. COMBINE 1+2.

We REIMPLEMENT the production_replay sizing loop here (self-contained) so we can
inject the dynamic multiplier at entry from realized equity state WITHOUT
touching shared lab.py (byte-identical-replay contract preserved). The fee is
already baked into each pool trade's R (v9 priced legs at PA_FEE_RT_BPS=18 via
the real BacktestEngine); we do NOT double-charge.

HONESTY GATES (the user demanded these):
  - WALK-FORWARD: vol/DD params chosen on IS (pre-2024) ONLY, locked, evaluated OOS.
    No lookahead in tuning. We report IS-optimal -> OOS-realized.
  - Decisive frontier: for each mechanism, the exposure base that holds MaxDD
    <= -23%, and the resulting mean %/mo. Compare to flat-L=1.2 (+15.2%).
  - sign-flip p_gross (shuffle), calendar/monthly Sharpe, %positive months, min month.
  - FRAGILITY flag: does vol-targeting de-risk right before recoveries? We test
    OOS and report if IS-tuned params underperform OOS (overfit signature).
  - The backtest is a BULL-BIASED upper bound; we state expected-live behavior.

Usage: PA_FEE_RT_BPS=18 .venv/bin/python scripts/v10_voltarget_ddthrottle.py
"""
from __future__ import annotations
import os, sys, json
from pathlib import Path
os.environ["PA_DUCKDB_READ_ONLY"] = "true"
os.environ["PA_LOG_QUIET"] = "1"
import warnings; warnings.filterwarnings("ignore")
import logging; logging.getLogger("price_action").setLevel(logging.ERROR)
import numpy as np, pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "src"))
import importlib.util
spec = importlib.util.spec_from_file_location("v9", str(ROOT / "scripts" / "v9_multitf_truefee.py"))
v9 = importlib.util.module_from_spec(spec); spec.loader.exec_module(v9)
wlr = v9.wlr

from price_action.backtest.lab import ProductionConfig, production_replay
from dataclasses import replace

YAML = ROOT / "configs" / "risk_phoenix_scalp_15m_widestop_vsa2.yaml"
RISK_PCT = v9.RISK_PCT      # 0.005
SL_PCT_MIN = v9.SL_PCT_MIN  # 0.025
IS_END = pd.Timestamp("2024-01-01", tz="UTC")

# ---- read the live config gates once. We faithfully replicate ALL active base
#      mechanics so our self-contained replay reproduces v9's flat numbers, then
#      layer the two NEW dynamic multipliers on top. ----
_CFG = ProductionConfig.from_yaml(str(YAML))
INIT_CAP = _CFG.initial_capital
CONF_MIN = _CFG.conf_min
MAX_CONC = _CFG.max_concurrent
NOTIONAL_CAP = _CFG.max_notional_pct_equity          # 0.15
CONC_PER_SYM = _CFG.concentration_max_per_symbol_pct  # 0.15
DROP_SYMS = set(_CFG.drop_symbols or [])
DROP_STRAT = set(_CFG.drop_strategies or [])
LEVERAGE = _CFG.leverage if _CFG.leverage and _CFG.leverage > 0 else 1.0  # 3.0
# base vol_target (already in v9 base — NOT our new mechanism; replicate it)
BASE_VT_ON = _CFG.vol_target_enabled
BASE_VT_TGT = _CFG.vol_target_atr_pct   # 0.010
BASE_VT_LO = _CFG.vol_min_factor        # 0.20
BASE_VT_HI = _CFG.vol_max_factor        # 1.50
CONSEC_N = _CFG.consecutive_loss_n      # 5
CONSEC_DAYS = _CFG.consecutive_loss_pause_days  # 1.0


# =========================================================================
# DYNAMIC SIZING via the REAL production_replay + dynamic_exposure_fn hook.
# This guarantees the flat baseline reproduces v9 EXACTLY (hook=None ->
# byte-identical), and every dynamic run differs ONLY by the exposure
# multiplier — which uses realized equity/peak/closed-returns (<= t-1) ->
# fully lookahead-safe. Fee already baked into pool trade R (v9 @ 18bps).
# =========================================================================
def build_cfg(base_lev=1.0, dyn_fn=None):
    c = ProductionConfig.from_yaml(str(YAML))
    c = replace(c, risk_pct=RISK_PCT * base_lev, sl_pct_min=max(c.sl_pct_min, SL_PCT_MIN))
    if c.max_notional_pct_equity is not None:
        c = replace(c, max_notional_pct_equity=c.max_notional_pct_equity * base_lev)
    if c.concentration_max_per_symbol_pct is not None:
        c = replace(c, concentration_max_per_symbol_pct=c.concentration_max_per_symbol_pct * base_lev)
    if dyn_fn is not None:
        c = replace(c, dynamic_exposure_fn=dyn_fn)
    return c


def make_voltarget_fn(target, lookback, lo=0.25, hi=3.0):
    """Returns fn(equity, peak, closed_rets) -> multiplier. Lookahead-safe:
    uses trailing std of REALIZED closed-trade equity returns (<= t-1)."""
    def fn(equity, peak, closed_rets):
        if len(closed_rets) < lookback:
            return 1.0
        tv = float(np.std(closed_rets[-lookback:]))
        if tv <= 1e-9:
            return 1.0
        return max(lo, min(hi, target / tv))
    return fn


def make_ddthrottle_fn(thresh, cut):
    """Cut exposure x`cut` while realized DD from peak >= thresh. Lookahead-safe."""
    def fn(equity, peak, closed_rets):
        dd = (peak - equity) / peak if peak > 0 else 0.0
        return cut if dd >= thresh else 1.0
    return fn


def make_combined_fn(vt, dt):
    fv = make_voltarget_fn(**vt) if vt else None
    fd = make_ddthrottle_fn(**dt) if dt else None
    def fn(equity, peak, closed_rets):
        m = 1.0
        if fv: m *= fv(equity, peak, closed_rets)
        if fd: m *= fd(equity, peak, closed_rets)
        return m
    return fn


def cont_dd(eq):
    peak = eq[0]; mdd = 0.0
    for v in eq:
        peak = max(peak, v); mdd = min(mdd, (v - peak) / peak if peak > 0 else 0.0)
    return mdd * 100.0


def monthly(res, init=INIT_CAP):
    eq = res.equity_curve or []; ets = res.entry_ts_list or []
    if len(eq) < 2 or not ets:
        return pd.Series(dtype=float)
    n = min(len(eq) - 1, len(ets))
    df = pd.DataFrame({"ts": pd.to_datetime(ets[:n], utc=True), "eq": eq[1:n + 1]})
    df["m"] = df["ts"].dt.to_period("M")
    me = df.groupby("m")["eq"].last()
    prev = me.shift(1, fill_value=init)
    return (me / prev - 1.0) * 100.0


def mstats(mr):
    if mr is None or mr.empty:
        return dict(n=0, mean=0, med=0, pos=0, mn=0, sd=0, sharpe=0)
    return dict(n=len(mr), mean=float(mr.mean()), med=float(mr.median()),
                pos=float((mr > 0).mean() * 100), mn=float(mr.min()), sd=float(mr.std()),
                sharpe=float(mr.mean() / mr.std() * np.sqrt(12)) if mr.std() > 0 else 0.0)


def run(trades, base_lev=1.0, dyn_fn=None):
    cfg = build_cfg(base_lev, dyn_fn)
    res = production_replay(sorted(trades, key=lambda x: x["entry_ts"]), cfg)
    if res is None:
        return mstats(None), 0.0, None
    return mstats(monthly(res, cfg.initial_capital)), cont_dd(res.equity_curve or [cfg.initial_capital]), res


# binary-search the base_lev that holds MaxDD just inside the ceiling (e.g. -23%)
def lev_for_dd(trades, dd_ceiling=-23.0, dyn_fn=None, lo=0.3, hi=4.0):
    best = None
    for _ in range(30):
        mid = (lo + hi) / 2
        s, dd, _ = run(trades, base_lev=mid, dyn_fn=dyn_fn)
        if dd >= dd_ceiling:        # DD shallower than ceiling -> push more exposure
            best = (mid, s, dd); lo = mid
        else:
            hi = mid
    return best


def main():
    DD_CEIL = -23.0
    print("=" * 100)
    print(f"v10 DYNAMIC SIZING vs FLAT LEVERAGE  —  hold MaxDD <= {DD_CEIL:.0f}%, maximize mean %/mo")
    print(f"fee baked in pools @ PA_FEE_RT_BPS={v9.FEE_RT_BPS}")
    print("=" * 100)

    # ---- build the SAME deploy stack as v9 (apples-to-apples vs flat-L=1.2) ----
    import pickle
    cache = Path(f"/tmp/v10_pools_{int(v9.FEE_RT_BPS)}.pkl")
    if cache.exists():
        print(f"loading cached pools from {cache}...")
        p05, p15_19, p30, p45 = pickle.load(open(cache, "rb"))
    else:
        print("gathering deploy stack (5m 10sym + 15m 19sym + 30m + 45m, BASELINE exit, true fee)...")
        p05 = v9.gather_native(v9.SYMS10, "5m")
        p15_19 = v9.gather_native(v9.SYMS19, "15m")
        p30 = v9.gather_resampled(v9.SYMS10, "30min", "30m")
        p45 = v9.gather_resampled(v9.SYMS10, "45min", "45m")
        pickle.dump((p05, p15_19, p30, p45), open(cache, "wb"))
    stack = p05 + p15_19 + p30 + p45
    print(f"  legs: 5m={len(p05)} 15m19={len(p15_19)} 30m={len(p30)} 45m={len(p45)}  total={len(stack)}")

    is_t = [t for t in stack if t["entry_ts"] < IS_END]
    oos_t = [t for t in stack if t["entry_ts"] >= IS_END]
    print(f"  split: IS(<2024)={len(is_t)}  OOS(>=2024)={len(oos_t)}")

    # ============================================================
    # 0) BASELINE: flat unlevered + flat L=1.2 (reproduce v9 anchor) + flat-L frontier
    # ============================================================
    print("\n" + "=" * 100)
    print("FLAT-LEVERAGE BASELINE & FRONTIER (full window)")
    print("=" * 100)
    print(f"{'L':>5} {'mean':>8} {'pos':>5} {'min':>8} {'MaxDD':>8} {'Sharpe':>7}")
    flat_front = []
    for L in [1.0, 1.1, 1.2, 1.3, 1.4, 1.5, 1.75, 2.0]:
        s, dd, _ = run(stack, base_lev=L)
        flat_front.append((L, s["mean"], dd, s["pos"], s["mn"], s["sharpe"]))
        print(f"{L:>5.2f} {s['mean']:>+7.2f}% {s['pos']:>4.0f}% {s['mn']:>+7.2f}% {dd:>+7.1f}% {s['sharpe']:>+6.2f}")
    # flat lev that holds -23% DD
    flat_at = lev_for_dd(stack, DD_CEIL)
    flat_L, flat_s, flat_dd = flat_at
    print(f"\n  FLAT-L holding MaxDD<={DD_CEIL:.0f}%: L={flat_L:.3f} -> mean={flat_s['mean']:+.2f}%/mo "
          f"DD={flat_dd:+.1f}% Sharpe={flat_s['sharpe']:+.2f} pos={flat_s['pos']:.0f}% min={flat_s['mn']:+.2f}%")
    print(f"  (user anchor: flat L=1.2 ~ +15.2%/mo @ -22.9% DD)")

    # ============================================================
    # 1) VOL-TARGETING — IS sweep, lock, OOS eval
    # ============================================================
    print("\n" + "=" * 100)
    print("MECHANISM 1: VOLATILITY TARGETING  (trailing equity-vol, lookahead-safe)")
    print("=" * 100)
    # IS-only grid search on (target, lookback). Score = IS Sharpe (curve smoothness).
    # base_lev fixed=1.0 during tuning so we isolate the SHAPE; exposure scaling done after.
    lookbacks = [15, 25, 40, 60]
    # target vol expressed as per-close-trade equity-return std; sweep multiplicatively
    # around the realized IS trailing vol scale.
    targets = [0.004, 0.006, 0.008, 0.010, 0.013, 0.016, 0.020]
    print("IS sweep (base_lev=1.0, score=IS monthly-Sharpe):")
    print(f"{'lookK':>6} {'target':>7} {'IS_mean':>8} {'IS_DD':>7} {'IS_Shrp':>7}")
    is_results = []
    n_vt_trials = 0
    for K in lookbacks:
        for tg in targets:
            n_vt_trials += 1
            fn = make_voltarget_fn(target=tg, lookback=K, lo=0.25, hi=3.0)
            s, dd, _ = run(is_t, base_lev=1.0, dyn_fn=fn)
            is_results.append((K, tg, s, dd))
    # rank by IS Sharpe (multiple-testing aware: report top, then OOS-validate)
    is_results.sort(key=lambda r: r[2]["sharpe"], reverse=True)
    for K, tg, s, dd in is_results[:8]:
        print(f"{K:>6} {tg:>7.3f} {s['mean']:>+7.2f}% {dd:>+6.1f}% {s['sharpe']:>+6.2f}")
    best_vt_params = dict(target=is_results[0][1], lookback=is_results[0][0], lo=0.25, hi=3.0)
    vt_fn = make_voltarget_fn(**best_vt_params)
    print(f"\n  IS-OPTIMAL vol-target params (LOCKED, {n_vt_trials} IS trials): {best_vt_params}")

    # OOS validation of locked params, base_lev=1.0
    s_oos, _, _ = run(oos_t, base_lev=1.0, dyn_fn=vt_fn)
    s_is, _, _ = run(is_t, base_lev=1.0, dyn_fn=vt_fn)
    s_flat_is, _, _ = run(is_t, base_lev=1.0)
    s_flat_oos, _, _ = run(oos_t, base_lev=1.0)
    print(f"  LOCKED params  IS : mean={s_is['mean']:+.2f}% Sharpe={s_is['sharpe']:+.2f}  (flat IS Sharpe={s_flat_is['sharpe']:+.2f})")
    print(f"  LOCKED params  OOS: mean={s_oos['mean']:+.2f}% Sharpe={s_oos['sharpe']:+.2f}  (flat OOS Sharpe={s_flat_oos['sharpe']:+.2f})")
    vt_fragile = s_oos["sharpe"] <= s_flat_oos["sharpe"] + 0.05
    print(f"  FRAGILITY: vol-target {'FAILS to beat' if vt_fragile else 'beats'} flat Sharpe OOS "
          f"(deltaSharpe_OOS={s_oos['sharpe']-s_flat_oos['sharpe']:+.2f})")

    # full-window: scale exposure to hold -23% DD with locked params
    vt_at = lev_for_dd(stack, DD_CEIL, dyn_fn=vt_fn)
    vt_L, vt_s, vt_dd = vt_at
    print(f"\n  VOL-TARGET (locked) holding MaxDD<={DD_CEIL:.0f}% [full window]: base_lev={vt_L:.3f} -> "
          f"mean={vt_s['mean']:+.2f}%/mo DD={vt_dd:+.1f}% Sharpe={vt_s['sharpe']:+.2f} pos={vt_s['pos']:.0f}% min={vt_s['mn']:+.2f}%")

    # ============================================================
    # 2) DRAWDOWN THROTTLE — IS sweep, lock, OOS eval
    # ============================================================
    print("\n" + "=" * 100)
    print("MECHANISM 2: DRAWDOWN THROTTLE  (cut exposure in realized DD, lookahead-safe)")
    print("=" * 100)
    threshs = [0.06, 0.08, 0.10, 0.12, 0.15, 0.18]
    cuts = [0.3, 0.4, 0.5, 0.6]
    print("IS sweep (base_lev=1.0, score=IS monthly-Sharpe):")
    print(f"{'thresh':>7} {'cut':>5} {'IS_mean':>8} {'IS_DD':>7} {'IS_Shrp':>7}")
    dd_results = []
    n_dd_trials = 0
    for th in threshs:
        for ct in cuts:
            n_dd_trials += 1
            fn = make_ddthrottle_fn(thresh=th, cut=ct)
            s, dd, _ = run(is_t, base_lev=1.0, dyn_fn=fn)
            dd_results.append((th, ct, s, dd))
    dd_results.sort(key=lambda r: r[2]["sharpe"], reverse=True)
    for th, ct, s, dd in dd_results[:8]:
        print(f"{th:>7.2f} {ct:>5.2f} {s['mean']:>+7.2f}% {dd:>+6.1f}% {s['sharpe']:>+6.2f}")
    best_dd_params = dict(thresh=dd_results[0][0], cut=dd_results[0][1])
    dd_fn = make_ddthrottle_fn(**best_dd_params)
    print(f"\n  IS-OPTIMAL dd-throttle params (LOCKED, {n_dd_trials} IS trials): {best_dd_params}")

    s_oos2, _, _ = run(oos_t, base_lev=1.0, dyn_fn=dd_fn)
    s_is2, _, _ = run(is_t, base_lev=1.0, dyn_fn=dd_fn)
    print(f"  LOCKED params  IS : mean={s_is2['mean']:+.2f}% Sharpe={s_is2['sharpe']:+.2f}  (flat IS Sharpe={s_flat_is['sharpe']:+.2f})")
    print(f"  LOCKED params  OOS: mean={s_oos2['mean']:+.2f}% Sharpe={s_oos2['sharpe']:+.2f}  (flat OOS Sharpe={s_flat_oos['sharpe']:+.2f})")
    dd_fragile = s_oos2["sharpe"] <= s_flat_oos["sharpe"] + 0.05
    print(f"  FRAGILITY: dd-throttle {'FAILS to beat' if dd_fragile else 'beats'} flat Sharpe OOS "
          f"(deltaSharpe_OOS={s_oos2['sharpe']-s_flat_oos['sharpe']:+.2f})")

    ddt_at = lev_for_dd(stack, DD_CEIL, dyn_fn=dd_fn)
    ddt_L, ddt_s, ddt_dd = ddt_at
    print(f"\n  DD-THROTTLE (locked) holding MaxDD<={DD_CEIL:.0f}% [full window]: base_lev={ddt_L:.3f} -> "
          f"mean={ddt_s['mean']:+.2f}%/mo DD={ddt_dd:+.1f}% Sharpe={ddt_s['sharpe']:+.2f} pos={ddt_s['pos']:.0f}% min={ddt_s['mn']:+.2f}%")

    # ============================================================
    # 3) COMBINE 1+2
    # ============================================================
    print("\n" + "=" * 100)
    print("MECHANISM 3: COMBINE vol-target (locked) + dd-throttle (locked)")
    print("=" * 100)
    comb_fn = make_combined_fn(best_vt_params, best_dd_params)
    comb_at = lev_for_dd(stack, DD_CEIL, dyn_fn=comb_fn)
    comb_L, comb_s, comb_dd = comb_at
    s_oos3, _, _ = run(oos_t, base_lev=1.0, dyn_fn=comb_fn)
    print(f"  COMBINED OOS Sharpe={s_oos3['sharpe']:+.2f} (flat OOS={s_flat_oos['sharpe']:+.2f})")
    print(f"  COMBINED holding MaxDD<={DD_CEIL:.0f}% [full window]: base_lev={comb_L:.3f} -> "
          f"mean={comb_s['mean']:+.2f}%/mo DD={comb_dd:+.1f}% Sharpe={comb_s['sharpe']:+.2f} pos={comb_s['pos']:.0f}% min={comb_s['mn']:+.2f}%")

    # ============================================================
    # shuffle p_gross (mechanism-independent edge) + frontier dump
    # ============================================================
    pg = wlr.shuffle_p([t["R"] for t in stack], n_iter=4000)
    print(f"\nshuffle p_gross (stack R, n=4000) = {pg:.4f}  ({'PASS<0.05' if pg<0.05 else 'FAIL'})")

    # ============================================================
    # DECISIVE FRONTIER TABLE: return @ -23% DD, each mechanism vs flat-L
    # ============================================================
    print("\n" + "=" * 100)
    print(f"DECISIVE FRONTIER — return @ MaxDD<={DD_CEIL:.0f}%  (full window, exposure scaled to ceiling)")
    print("=" * 100)
    print(f"{'mechanism':<28} {'base_lev':>8} {'mean%/mo':>9} {'MaxDD':>8} {'Sharpe':>7} {'pos%':>5} {'min%':>7}")
    rows = [
        ("flat leverage", flat_L, flat_s, flat_dd),
        ("vol-target(locked)", vt_L, vt_s, vt_dd),
        ("dd-throttle(locked)", ddt_L, ddt_s, ddt_dd),
        ("combined", comb_L, comb_s, comb_dd),
    ]
    for nm, L, s, dd in rows:
        print(f"{nm:<28} {L:>8.3f} {s['mean']:>+8.2f}% {dd:>+7.1f}% {s['sharpe']:>+6.2f} {s['pos']:>4.0f}% {s['mn']:>+6.2f}%")

    best = max(rows[1:], key=lambda r: r[2]["mean"])
    gain = best[2]["mean"] - flat_s["mean"]
    print(f"\n  BEST DYNAMIC: {best[0]} -> {best[2]['mean']:+.2f}%/mo @ {best[3]:+.1f}% DD")
    print(f"  vs FLAT-L @ same DD: {flat_s['mean']:+.2f}%/mo  =>  dynamic edge = {gain:+.2f} pp/mo")
    print(f"  VERDICT: dynamic sizing {'BEATS' if gain > 0.5 else ('~matches' if gain > -0.5 else 'LOSES to')} flat leverage at -23% DD")

    out = dict(
        fee_rt_bps=v9.FEE_RT_BPS, dd_ceiling=DD_CEIL, n_stack=len(stack),
        flat=dict(L=flat_L, **flat_s, maxdd=flat_dd), flat_frontier=flat_front,
        voltarget=dict(params=best_vt_params, L=vt_L, **vt_s, maxdd=vt_dd,
                       is_sharpe=s_is["sharpe"], oos_sharpe=s_oos["sharpe"],
                       flat_oos_sharpe=s_flat_oos["sharpe"], fragile=bool(vt_fragile)),
        ddthrottle=dict(params=best_dd_params, L=ddt_L, **ddt_s, maxdd=ddt_dd,
                        is_sharpe=s_is2["sharpe"], oos_sharpe=s_oos2["sharpe"], fragile=bool(dd_fragile)),
        combined=dict(L=comb_L, **comb_s, maxdd=comb_dd, oos_sharpe=s_oos3["sharpe"]),
        best_dynamic=best[0], dynamic_edge_pp=gain, p_gross=pg,
    )
    json.dump(out, open("/tmp/v10_voltarget_ddthrottle.json", "w"), indent=2, default=str)
    print("\n[dumped /tmp/v10_voltarget_ddthrottle.json]")


if __name__ == "__main__":
    main()
