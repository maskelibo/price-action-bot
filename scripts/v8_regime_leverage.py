"""HYP-2026-06-02-v8-regime-conditional-leverage.

GENUINELY NEW ANGLE: raise champion monthly return toward ~15% at MaxDD ~= -17.6%
WITHOUT a diversifier, via (1) regime-conditional dynamic leverage and (2) multi-TF
stacking of the SAME champion edge. Brutally honest: if it just shuffles risk
(higher return => proportionally higher DD), say so.

CHAMPION BAR (reproduce exactly): VSA-WIDESTOP + BASELINE exit @ 55bps, 19-sym 15m.
  Target: +7.58%/mo, MaxDD -17.6%, Sharpe ~1.98, 85% pos months.

METHOD (artifact-free, reuses deployed harness):
  - Trades via REAL BacktestEngine (wlr.gather, exit = engine constructor knobs).
  - BASELINE exit: trail ATR 1.5, stage 2, TP1 30%@1R / TP2 30%@1.5R / runner 40%,
    time-stop 30 (NOT from entry).
  - 55bps honest fees: engine taker 27.5bps/leg x2 = 55bps round-trip, slippage 0.
  - Portfolio replay via production_replay (live YAML mechanics, risk 0.5%,
    sl_pct_min 0.025, DD halts, side-concentration, notional cap).

LEVERAGE MECHANICS (honest):
  - To test L>1 cleanly we scale risk_pct by L AND raise max_notional_pct_equity by L
    so the notional cap (0.15) does not silently clip. DD halts + compounding stay live
    -> aggressive sizing in a bad regime DOES trip halts (that's the honest part).
  - Regime-conditional: per-trade risk_weight set by a LOOKAHEAD-SAFE BTC regime
    signal. WALK-FORWARD: regime tertile cutoffs computed from a TRAILING window only
    (rolling 90d), never future. The leverage SCHEDULE (which regime gets which L) is
    fit on IS[2021,2024) per-regime meanR, then applied frozen to OOS[2024,2026.5).

Usage: .venv/bin/python scripts/v8_regime_leverage.py
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
from price_action.backtest.lab import ProductionConfig, production_replay
from dataclasses import replace

YAML = ROOT / "configs" / "risk_phoenix_scalp_15m_widestop_vsa2.yaml"
DB = ROOT / "data" / "market.duckdb"
SYMS19 = ["BTC/USDT","ETH/USDT","SOL/USDT","BNB/USDT","ADA/USDT","AVAX/USDT",
          "LINK/USDT","DOT/USDT","DOGE/USDT","XRP/USDT","ZEC/USDT","NEAR/USDT",
          "FIL/USDT","XLM/USDT","TRX/USDT","UNI/USDT","ATOM/USDT","AAVE/USDT","ALGO/USDT"]
SYMS10 = ["BTC/USDT","ETH/USDT","SOL/USDT","BNB/USDT","ADA/USDT","AVAX/USDT",
          "LINK/USDT","DOT/USDT","DOGE/USDT","XRP/USDT"]
SL_PCT_MIN = 0.025
RISK_PCT = 0.005
SEED = 12345

# BASELINE exit @ 55bps (the champion bar). Engine fee override: taker 27.5bps/leg,
# slippage 0 -> exactly 55bps round-trip. (wlr.gather hardcodes FEES/SLIPPAGE, so we
# monkeypatch them for the 55bps run.)
BASELINE_EXIT = dict(
    runner_trail_mult=1.5, trail_activate_stage=2,
    tp1_R=1.0, tp2_R=1.5, tp1_close_pct=0.30, tp2_close_pct=0.30,
    runner_force_exit_method="time", runner_force_exit_bars=30,
    force_exit_from_entry=False,
)
wlr.FEES = {"taker": 0.00275, "maker": -0.00010}  # 27.5bps/leg => 55bps round-trip
wlr.SLIPPAGE_BPS = 0.0
wlr.SL_PCT_MIN = SL_PCT_MIN

IS_START = pd.Timestamp("2021-01-01", tz="UTC")
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
    """Champion live cfg. To test leverage L cleanly: scale risk_pct by L and raise
    the notional cap by L so the cap does not clip. DD halts/compounding stay live."""
    c = ProductionConfig.from_yaml(str(YAML))
    c = replace(c, risk_pct=RISK_PCT * lev, sl_pct_min=max(c.sl_pct_min, SL_PCT_MIN))
    if c.max_notional_pct_equity is not None:
        c = replace(c, max_notional_pct_equity=c.max_notional_pct_equity * lev)
    # also relax per-symbol concentration cap proportionally (else clips at L>1.2)
    if c.concentration_max_per_symbol_pct is not None:
        c = replace(c, concentration_max_per_symbol_pct=c.concentration_max_per_symbol_pct * lev)
    return c


# ---------- BTC regime features (LOOKAHEAD-SAFE) ----------
def btc_regime_frame(tf="15m"):
    con = duckdb.connect(str(DB), read_only=True)
    btc = con.execute("SELECT ts,high,low,close FROM ohlcv WHERE venue='binance' "
                      "AND symbol='BTC/USDT' AND timeframe=? ORDER BY ts", [tf]).fetchdf()
    con.close()
    btc["ts"] = pd.to_datetime(btc["ts"], utc=True)
    btc = btc.sort_values("ts").reset_index(drop=True)
    btc["ret"] = np.log(btc["close"]).diff()
    btc["rv"] = btc["ret"].rolling(96).std()              # ~1d realized vol (past only)
    # ADX(14) on 15m for trend strength (all past bars)
    h, l, c = btc["high"], btc["low"], btc["close"]
    up = h.diff(); dn = -l.diff()
    plus_dm = np.where((up > dn) & (up > 0), up, 0.0)
    minus_dm = np.where((dn > up) & (dn > 0), dn, 0.0)
    tr = pd.concat([(h - l), (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1/14, adjust=False).mean()
    pdi = 100 * pd.Series(plus_dm, index=btc.index).ewm(alpha=1/14, adjust=False).mean() / atr
    mdi = 100 * pd.Series(minus_dm, index=btc.index).ewm(alpha=1/14, adjust=False).mean() / atr
    dx = 100 * (pdi - mdi).abs() / (pdi + mdi).replace(0, np.nan)
    btc["adx"] = dx.ewm(alpha=1/14, adjust=False).mean()
    return btc.dropna(subset=["rv", "adx"]).reset_index(drop=True)


def assign_regime_walkforward(trades, btc, vol_lookback_bars=96*90):
    """Per-trade regime label using ONLY trailing data.
    vol tertile cutoffs = rolling 90d (96*90 bars) quantiles of rv, computed causally.
    Returns trades with 't[\"regime\"]' in {low,mid,high} and trend flag.
    """
    btc = btc.copy()
    # causal rolling tertile cutoffs (shift(1) so current bar not in its own window)
    rv = btc["rv"]
    btc["q33"] = rv.rolling(vol_lookback_bars, min_periods=96*20).quantile(1/3).shift(1)
    btc["q67"] = rv.rolling(vol_lookback_bars, min_periods=96*20).quantile(2/3).shift(1)
    adx_med = btc["adx"].rolling(vol_lookback_bars, min_periods=96*20).median().shift(1)
    btc["adx_med"] = adx_med
    ts_arr = btc["ts"].values
    for t in trades:
        idx = np.searchsorted(ts_arr, np.datetime64(t["entry_ts"])) - 1  # last bar BEFORE entry
        if idx < 0 or idx >= len(btc):
            t["regime"] = "unk"; t["adx_hi"] = False; continue
        row = btc.iloc[idx]
        if np.isnan(row["q33"]) or np.isnan(row["q67"]):
            t["regime"] = "unk"; t["adx_hi"] = False; continue
        rvv = row["rv"]
        t["regime"] = "low" if rvv <= row["q33"] else ("high" if rvv >= row["q67"] else "mid")
        t["adx_hi"] = bool(row["adx"] >= row["adx_med"]) if not np.isnan(row["adx_med"]) else False
    return trades


def apply_weights(trades, weight_fn):
    out = []
    for t in trades:
        u = dict(t); u["risk_weight"] = float(weight_fn(t)); out.append(u)
    return out


def gather_universe(syms, exit_cfg, tf="15m"):
    pool = []
    for s in syms:
        pool += wlr.gather(s, exit_cfg, tf=tf)
    return [t for t in pool if sl_pct_of(t) >= SL_PCT_MIN]


def main():
    print("=" * 100)
    print("STEP 0: reproduce CHAMPION BAR (BASELINE exit @ 55bps, 19-sym 15m)")
    print("=" * 100)
    pool19 = gather_universe(SYMS19, BASELINE_EXIT, "15m")
    print(f"widestop trades (19s, 15m, 55bps) = {len(pool19)}")

    cfg1 = build_cfg(1.0)
    res = production_replay(sorted(pool19, key=lambda x: x["entry_ts"]), cfg1)
    mr = monthly_from_replay(res, cfg1)
    base = stats(mr)
    base_dd = cont_dd(res.equity_curve)
    print(f"CHAMPION: mean={base['mean']:+.2f}%/mo med={base['med']:+.2f}% pos={base['pos']:.0f}% "
          f"min={base['mn']:+.2f}% sd={base['sd']:.2f} MaxDD={base_dd:+.1f}% Sharpe_ann={base['sharpe']:+.2f} n_mo={base['n']}")

    # ---------- LEVER 1: regime-conditional leverage ----------
    print("\n" + "=" * 100)
    print("STEP 1: REGIME-CONDITIONAL LEVERAGE (lookahead-safe, walk-forward thresholds)")
    print("=" * 100)
    btc = btc_regime_frame("15m")
    pool19 = assign_regime_walkforward(pool19, btc)

    # diagnostic: per-regime meanR (IS only, for schedule fitting) — NO lookahead since
    # schedule is fit on IS and frozen for OOS.
    def regime_meanR(trades, lo, hi):
        d = {}
        for r in ["low", "mid", "high", "unk"]:
            a = np.array([t["R"] for t in trades if t["regime"] == r and lo <= t["entry_ts"] < hi])
            d[r] = (len(a), float(a.mean()) if len(a) else 0.0)
        return d
    is_reg = regime_meanR(pool19, IS_START, IS_END)
    oos_reg = regime_meanR(pool19, IS_END, OOS_END)
    print("per-regime meanR (vol tertile, causal cutoffs):")
    print(f"  {'regime':<6} {'IS_n':>7} {'IS_mR':>8} {'OOS_n':>7} {'OOS_mR':>8}")
    for r in ["low", "mid", "high", "unk"]:
        print(f"  {r:<6} {is_reg[r][0]:>7} {is_reg[r][1]:>+8.3f} {oos_reg[r][0]:>7} {oos_reg[r][1]:>+8.3f}")

    # ADX-conditioned per regime (IS)
    print("\nper-(regime x ADX) meanR (IS):")
    for r in ["low", "mid", "high"]:
        for a in [True, False]:
            arr = np.array([t["R"] for t in pool19 if t["regime"] == r and t["adx_hi"] == a
                            and IS_START <= t["entry_ts"] < IS_END])
            if len(arr):
                print(f"  {r:<5} adx_hi={a!s:<5} n={len(arr):>6} meanR={arr.mean():+.3f}")

    # SCHEDULE: lever UP where IS per-trade edge is highest, DOWN where weak.
    # Fit thresholds on IS meanR ranking, freeze, apply to ALL (incl OOS).
    is_mR = {r: is_reg[r][1] for r in ["low", "mid", "high"]}
    ranked = sorted(is_mR, key=lambda r: is_mR[r], reverse=True)
    print(f"\nIS edge ranking (best->worst): {ranked}  (mR: " +
          ", ".join(f'{r}={is_mR[r]:+.3f}' for r in ranked) + ")")

    # Several schedules to test (avg leverage ~2x for fair comparison vs flat-2x).
    # Schedule maps regime->L. unk -> 1.0 (no info).
    schedules = {}
    # S1: strong tilt 3/2/1 by IS rank
    schedules["S1_tilt_3-2-1"] = {ranked[0]: 3.0, ranked[1]: 2.0, ranked[2]: 1.0, "unk": 1.0}
    # S2: moderate 2.5/2/1.5
    schedules["S2_tilt_2.5-2-1.5"] = {ranked[0]: 2.5, ranked[1]: 2.0, ranked[2]: 1.5, "unk": 1.0}
    # S3: binary — lever only the best regime
    schedules["S3_best_only_3x"] = {ranked[0]: 3.0, ranked[1]: 1.0, ranked[2]: 1.0, "unk": 1.0}
    # S4: defensive — cut the worst to flat, others 2.5
    schedules["S4_cut_worst"] = {ranked[0]: 2.5, ranked[1]: 2.5, ranked[2]: 1.0, "unk": 1.5}

    def run_pool(pool, cfg):
        r = production_replay(sorted(pool, key=lambda x: x["entry_ts"]), cfg)
        return stats(monthly_from_replay(r, cfg)), cont_dd(r.equity_curve), r

    # Flat-leverage baselines (the comparison anchor)
    print("\n--- FLAT LEVERAGE baselines (no regime timing) ---")
    print(f"{'config':<22} {'mean':>7} {'med':>7} {'pos':>5} {'min':>7} {'sd':>6} {'MaxDD':>7} {'Sharpe':>7}")
    flat_rows = {}
    for L in [1.0, 1.5, 2.0, 2.5, 3.0]:
        # avg risk_weight = L via uniform weight (set on cfg, weight=1)
        s, dd, _ = run_pool(pool19, build_cfg(L))
        flat_rows[L] = (s, dd)
        print(f"flat_{L:<17.1f} {s['mean']:>+6.2f}% {s['med']:>+6.2f}% {s['pos']:>4.0f}% {s['mn']:>+6.2f}% {s['sd']:>5.2f} {dd:>+6.1f}% {s['sharpe']:>+6.2f}")

    print("\n--- REGIME-CONDITIONAL leverage schedules ---")
    print(f"{'schedule':<22} {'avgL':>5} {'mean':>7} {'med':>7} {'pos':>5} {'min':>7} {'sd':>6} {'MaxDD':>7} {'Sharpe':>7}")
    reg_rows = {}
    for name, sch in schedules.items():
        wpool = apply_weights(pool19, lambda t: sch.get(t["regime"], 1.0))
        # average leverage actually applied (trade-weighted)
        avgL = np.mean([sch.get(t["regime"], 1.0) for t in pool19])
        s, dd, _ = run_pool(wpool, build_cfg(1.0))  # base cfg lev=1; risk_weight carries L
        # NOTE: base cfg notional cap not scaled here -> must scale cap to max L in schedule
        maxL = max(sch.values())
        cfgL = build_cfg(maxL)  # scale caps to max L; risk_pct base then *risk_weight
        cfgL = replace(cfgL, risk_pct=RISK_PCT)  # keep base risk; weight does the leverage
        s, dd, _ = run_pool(wpool, cfgL)
        reg_rows[name] = (s, dd, avgL)
        print(f"{name:<22} {avgL:>4.2f} {s['mean']:>+6.2f}% {s['med']:>+6.2f}% {s['pos']:>4.0f}% {s['mn']:>+6.2f}% {s['sd']:>5.2f} {dd:>+6.1f}% {s['sharpe']:>+6.2f}")

    # ---- OOS-only validation of best schedule vs flat at matched mean ----
    print("\n--- OOS-ONLY [2024,2026.5) validation (schedule frozen from IS ranking) ---")
    oos_pool = [t for t in pool19 if IS_END <= t["entry_ts"] < OOS_END]
    print(f"{'config':<22} {'mean':>7} {'med':>7} {'pos':>5} {'min':>7} {'MaxDD':>7} {'Sharpe':>7}")
    for L in [1.0, 2.0]:
        s, dd, _ = run_pool(oos_pool, build_cfg(L))
        print(f"OOS flat_{L:<13.1f} {s['mean']:>+6.2f}% {s['med']:>+6.2f}% {s['pos']:>4.0f}% {s['mn']:>+6.2f}% {dd:>+6.1f}% {s['sharpe']:>+6.2f}")
    for name, sch in schedules.items():
        wpool = apply_weights(oos_pool, lambda t: sch.get(t["regime"], 1.0))
        cfgL = replace(build_cfg(max(sch.values())), risk_pct=RISK_PCT)
        s, dd, _ = run_pool(wpool, cfgL)
        print(f"OOS {name:<18} {s['mean']:>+6.2f}% {s['med']:>+6.2f}% {s['pos']:>4.0f}% {s['mn']:>+6.2f}% {dd:>+6.1f}% {s['sharpe']:>+6.2f}")

    # ---------- LEVER 2: multi-TF stacking ----------
    print("\n" + "=" * 100)
    print("STEP 2: MULTI-TF STACKING (5m + 15m + 1h, SAME edge, common-10 universe)")
    print("=" * 100)
    # 1h starts 2023-05; restrict all TFs to the COMMON window for honest comparison.
    print("gathering 15m/5m/1h on common-10 (this is the slow part)...")
    pool_15 = gather_universe(SYMS10, BASELINE_EXIT, "15m")
    pool_05 = gather_universe(SYMS10, BASELINE_EXIT, "5m")
    pool_1h = gather_universe(SYMS10, BASELINE_EXIT, "1h")
    print(f"  15m n={len(pool_15)}  5m n={len(pool_05)}  1h n={len(pool_1h)}")

    # common window = max of TF mins
    def span(p):
        ts = [t["entry_ts"] for t in p]
        return (min(ts), max(ts)) if ts else (None, None)
    lo = max(span(pool_15)[0], span(pool_05)[0], span(pool_1h)[0])
    hi = min(span(pool_15)[1], span(pool_05)[1], span(pool_1h)[1])
    print(f"  common window: {lo.date()} -> {hi.date()}")

    def clip(p):
        return [t for t in p if lo <= t["entry_ts"] <= hi]
    p15, p05, p1h = clip(pool_15), clip(pool_05), clip(pool_1h)
    stack = p15 + p05 + p1h

    print(f"\n{'pool':<22} {'n':>6} {'mean':>7} {'med':>7} {'pos':>5} {'min':>7} {'sd':>6} {'MaxDD':>7} {'Sharpe':>7}")
    for nm, p in [("15m only", p15), ("5m only", p05), ("1h only", p1h), ("STACK 5m+15m+1h", stack)]:
        if not p:
            print(f"{nm:<22} (empty)"); continue
        s, dd, _ = run_pool(p, build_cfg(1.0))
        print(f"{nm:<22} {len(p):>6} {s['mean']:>+6.2f}% {s['med']:>+6.2f}% {s['pos']:>4.0f}% {s['mn']:>+6.2f}% {s['sd']:>5.2f} {dd:>+6.1f}% {s['sharpe']:>+6.2f}")

    # lever the smoother stack to match flat-2x mean and compare DD
    print("\n--- LEVER the stack (does smoother stack reach higher return at same DD?) ---")
    print(f"{'config':<22} {'mean':>7} {'med':>7} {'pos':>5} {'min':>7} {'sd':>6} {'MaxDD':>7} {'Sharpe':>7}")
    for L in [1.0, 1.5, 2.0, 2.5, 3.0]:
        s, dd, _ = run_pool(stack, build_cfg(L))
        print(f"stack_flat_{L:<11.1f} {s['mean']:>+6.2f}% {s['med']:>+6.2f}% {s['pos']:>4.0f}% {s['mn']:>+6.2f}% {s['sd']:>5.2f} {dd:>+6.1f}% {s['sharpe']:>+6.2f}")
    # also 15m-only on SAME common window+universe, levered, as the apples-to-apples ref
    print("  -- 15m-only (same window/universe) levered ref --")
    for L in [1.0, 2.0]:
        s, dd, _ = run_pool(p15, build_cfg(L))
        print(f"15m_only_flat_{L:<8.1f} {s['mean']:>+6.2f}% {s['med']:>+6.2f}% {s['pos']:>4.0f}% {s['mn']:>+6.2f}% {s['sd']:>5.2f} {dd:>+6.1f}% {s['sharpe']:>+6.2f}")

    # ---- best return at MaxDD <= -18% search (across all levers) ----
    print("\n" + "=" * 100)
    print("STEP 3: BEST RETURN at MaxDD <= -18% (the decisive number)")
    print("=" * 100)
    candidates = []
    # fine leverage sweep on 19-sym flat
    for L in np.arange(1.0, 3.05, 0.1):
        s, dd, _ = run_pool(pool19, build_cfg(round(L, 2)))
        candidates.append((f"flat_19s_{L:.1f}x", s["mean"], dd, s["pos"], s["mn"], s["sharpe"]))
    # regime schedules already computed (full period)
    for name, (s, dd, avgL) in reg_rows.items():
        candidates.append((f"regime_{name}", s["mean"], dd, s["pos"], s["mn"], s["sharpe"]))
    feasible = [c for c in candidates if c[2] >= -18.0]
    feasible.sort(key=lambda c: c[1], reverse=True)
    print(f"{'config':<26} {'mean':>7} {'MaxDD':>7} {'pos':>5} {'min':>7} {'Sharpe':>7}")
    for c in feasible[:12]:
        print(f"{c[0]:<26} {c[1]:>+6.2f}% {c[2]:>+6.1f}% {c[3]:>4.0f}% {c[4]:>+6.2f}% {c[5]:>+6.2f}")
    best = feasible[0] if feasible else None
    print(f"\nBEST at MaxDD<=-18%: {best}")

    out = dict(champion=dict(**base, maxdd=base_dd),
               flat={str(L): dict(**flat_rows[L][0], maxdd=flat_rows[L][1]) for L in flat_rows},
               regime={k: dict(**v[0], maxdd=v[1], avgL=v[2]) for k, v in reg_rows.items()},
               best_at_18dd=best)
    json.dump(out, open("/tmp/v8_regime_leverage.json", "w"), indent=2, default=str)
    print("\n[dumped /tmp/v8_regime_leverage.json]")


if __name__ == "__main__":
    main()
