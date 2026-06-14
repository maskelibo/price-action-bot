"""HYP-2026-06-03-v13-9pct-fixed-fraction.

DECISIVE honest feasibility: can the best deployable config reach +9%/mo at
acceptable DD, computed with FIXED-FRACTION (NON-compounding) sizing?

The whole point: the prior +7-15%/mo were a COMPOUNDING artifact (production_replay
sizes risk as % of CURRENT growing equity -> geometric inflation ~10-25x). Here we
size FIXED-FRACTION: constant $ risk per trade = risk_pct * E0 (E0 = FIXED starting
equity). Each trade contributes R * (risk_pct * E0) dollars. Sum per calendar month.
Monthly return = month_PnL / E0. NO compounding anywhere.

BEST HONEST CONFIG (stack the REAL gated improvements):
  - Entry: VSA-WIDESTOP (sl_pct >= 0.025) + HTF-1d-aligned filter (V12's only
    OOS-surviving lever: keep trades where daily close on trade side of EMA50).
  - Exit: BASELINE (trail 1.5, stage 2, TP1 30%@1R / TP2 30%@1.5R / runner 40%,
    time-stop 30 bars, force_exit_from_entry=False) -- keeps the runner tail.
  - Structure: clean 5m + 15m core (V11: resampled 30m/45m HURT -> dropped).
  - Fee: true PA_FEE_RT_BPS=18 round-trip (repriced from engine 25bps at R layer).
  - Universe: 5m=10 sym, 15m=19 sym as available.

OUTPUTS:
  1. Unlevered fixed-fraction monthly distribution: mean/median %/mo, %pos, MIN,
     MaxDD (on fixed-$ PnL curve), calendar-day Sharpe (honest).
  2. Leverage frontier to +9%/mo: L scales return & DD ~linearly. Exact L and the
     resulting MaxDD / min month / %pos.
  3. Walk-forward IS/OOS + sign-flip p_gross (NOT broken shuffle).

Usage: PA_FEE_RT_BPS=18 .venv/bin/python scripts/v13_9pct_fixedfraction.py
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

DB = ROOT / "data" / "market.duckdb"
SYMS10 = ["BTC/USDT","ETH/USDT","SOL/USDT","BNB/USDT","ADA/USDT","AVAX/USDT",
          "LINK/USDT","DOT/USDT","DOGE/USDT","XRP/USDT"]
SYMS19 = SYMS10 + ["ZEC/USDT","NEAR/USDT","FIL/USDT","XLM/USDT","TRX/USDT",
                   "UNI/USDT","ATOM/USDT","AAVE/USDT","ALGO/USDT"]
SL_PCT_MIN = 0.025
RISK_PCT = 0.005           # 0.5% fixed fraction
E0 = 10_000.0             # FIXED starting equity (never grows)
SEED = 12345
FEE_RT_BPS = float(os.environ.get("PA_FEE_RT_BPS", "18"))
GATHER_RT_BPS = 25.0      # engine: taker 7.5*2 + slip 5*2 on notional
IS_END = pd.Timestamp("2024-01-01", tz="UTC")

BASELINE_EXIT = dict(
    runner_trail_mult=1.5, trail_activate_stage=2,
    tp1_R=1.0, tp2_R=1.5, tp1_close_pct=0.30, tp2_close_pct=0.30,
    runner_force_exit_method="time", runner_force_exit_bars=30,
    force_exit_from_entry=False,
)

# patch wlr fee to TRUE 18bps round-trip, slippage folded
wlr.FEES = {"taker": (FEE_RT_BPS / 2.0) / 10000.0, "maker": (FEE_RT_BPS / 2.0) / 10000.0}
wlr.SLIPPAGE_BPS = 0.0
wlr.SL_PCT_MIN = SL_PCT_MIN


def sl_pct_of(t):
    ep = t["entry_price"]
    return abs(t["initial_sl"] - ep) / ep if ep > 0 else 0.04


# ---- HTF 1d EMA50 alignment (V12's only OOS-surviving lever) ----
_D1 = {}


def load_d1(sym):
    if sym in _D1:
        return _D1[sym]
    con = duckdb.connect(str(DB), read_only=True)
    df = con.execute("SELECT ts,close FROM ohlcv WHERE venue='binance' "
                     "AND symbol=? AND timeframe='1d' ORDER BY ts", [sym]).fetchdf()
    con.close()
    if df.empty:
        _D1[sym] = df; return df
    df["ts"] = pd.to_datetime(df["ts"], utc=True).dt.tz_localize(None)
    df = df.sort_values("ts").reset_index(drop=True)
    df["ema50"] = df["close"].ewm(span=50, adjust=False).mean()
    _D1[sym] = df
    return df


def htf_aligned(t):
    """1 = daily close on trade side of EMA50 (lookahead-free: bar at/before entry)."""
    sym = t["symbol"]
    d1 = load_d1(sym)
    if d1.empty:
        return -1.0
    te = pd.Timestamp(t["entry_ts"]).tz_convert("UTC").tz_localize(None)
    j = np.searchsorted(d1["ts"].values, np.datetime64(te), side="right") - 1
    if j < 0 or j >= len(d1) or np.isnan(d1["ema50"].iloc[j]):
        return -1.0
    above = d1["close"].iloc[j] > d1["ema50"].iloc[j]
    side = t["side"].lower()
    return 1.0 if ((side == "long" and above) or (side == "short" and not above)) else 0.0


def R18(t):
    """Reprice gather R (@25bps engine) to true FEE_RT_BPS."""
    sp = sl_pct_of(t)
    if sp <= 0:
        return t["R"]
    add_back = (GATHER_RT_BPS / 10000.0) / sp
    charge = (FEE_RT_BPS / 10000.0) / sp
    return t["R"] + add_back - charge


# ---------------- FIXED-FRACTION engine (NO compounding, CAPITAL-CONSTRAINED) ----------------
# CRITICAL: a real fixed-fraction account has FINITE capital. With ~190 trades/mo and
# up to 62 concurrent opens, you cannot fund every gathered trade at 0.5% of E0 — that
# is "infinite-capital" sizing, not fixed-fraction. We replicate the LIVE YAML admission
# control (notional cap = max_notional_pct*E0, per-symbol concentration cap) but with
# equity PINNED to E0 (never compounds) for both sizing AND caps. A trade is taken only
# if it fits; rejected trades contribute $0. This is the honest fixed-fraction object.
MAX_NOTIONAL_PCT = 0.15   # from live YAML
CONC_PCT = 0.15           # per-symbol notional cap, live YAML


def _admit_fixed_fraction(trades, lev=1.0):
    """Chronological walk; constant $ risk = RISK_PCT*lev*E0; caps vs FIXED E0.
    Returns list of (exit_ts, pnl_dollars) for ADMITTED trades only."""
    risk_d_base = RISK_PCT * lev * E0
    notional_cap = MAX_NOTIONAL_PCT * lev * E0
    sym_cap = CONC_PCT * lev * E0
    # event-sorted by entry; track open positions (notional per symbol) released at exit
    ev = sorted(trades, key=lambda x: x["entry_ts"])
    open_pos = []  # list of dict(exit_ts, symbol, notional)
    taken = []
    for t in ev:
        ent = pd.Timestamp(t["entry_ts"]).tz_convert("UTC")
        # release positions that exited before this entry
        open_pos = [p for p in open_pos if p["exit_ts"] > ent]
        sp = sl_pct_of(t)
        if sp <= 0:
            continue
        risk_d = risk_d_base
        notional = risk_d / sp
        if notional > notional_cap:
            notional = notional_cap
            risk_d = notional * sp
        # per-symbol concentration cap (vs FIXED E0)
        sym = t["symbol"]
        existing = sum(p["notional"] for p in open_pos if p["symbol"] == sym)
        if existing + notional > sym_cap:
            continue  # reject
        # PnL = R * effective risk_d (R already net of fee at 18bps)
        pnl = R18(t) * risk_d
        xt = pd.Timestamp(t["exit_ts"]).tz_convert("UTC")
        open_pos.append(dict(exit_ts=xt, symbol=sym, notional=notional))
        taken.append((xt, pnl))
    return taken


def _R18_eff(t):
    return t["_R18_override"] if "_R18_override" in t else R18(t)


def _admit_override(trades, lev=1.0):
    """Same admission as _admit_fixed_fraction but uses _R18_eff for PnL (tail-cap aware)."""
    risk_d_base = RISK_PCT * lev * E0
    notional_cap = MAX_NOTIONAL_PCT * lev * E0
    sym_cap = CONC_PCT * lev * E0
    ev = sorted(trades, key=lambda x: x["entry_ts"])
    open_pos = []; taken = []
    for t in ev:
        ent = pd.Timestamp(t["entry_ts"]).tz_convert("UTC")
        open_pos = [p for p in open_pos if p["exit_ts"] > ent]
        sp = sl_pct_of(t)
        if sp <= 0:
            continue
        risk_d = risk_d_base; notional = risk_d / sp
        if notional > notional_cap:
            notional = notional_cap; risk_d = notional * sp
        existing = sum(p["notional"] for p in open_pos if p["symbol"] == t["symbol"])
        if existing + notional > sym_cap:
            continue
        xt = pd.Timestamp(t["exit_ts"]).tz_convert("UTC")
        open_pos.append(dict(exit_ts=xt, symbol=t["symbol"], notional=notional))
        taken.append((xt, _R18_eff(t) * risk_d))
    return taken


def _ff_monthly_override(trades, lev=1.0):
    taken = _admit_override(trades, lev)
    if not taken:
        return pd.Series(dtype=float), 0.0, pd.Series(dtype=float), 0.0
    df = pd.DataFrame(taken, columns=["ts", "pnl"])
    df["m"] = df["ts"].dt.to_period("M")
    monthly_pnl = df.groupby("m")["pnl"].sum()
    monthly_ret = monthly_pnl / E0 * 100.0
    full_m = pd.period_range(df["m"].min(), df["m"].max(), freq="M")
    monthly_ret = monthly_ret.reindex(full_m, fill_value=0.0)
    df = df.sort_values("ts")
    cum = E0 + df["pnl"].cumsum()
    cum = pd.concat([pd.Series([E0]), cum], ignore_index=True)
    peak = cum.cummax(); dd = ((cum - peak) / peak * 100.0).min()
    df["d"] = df["ts"].dt.floor("D")
    day_pnl = df.groupby("d")["pnl"].sum()
    full_d = pd.date_range(day_pnl.index.min(), day_pnl.index.max(), freq="D", tz="UTC")
    day_ret = day_pnl.reindex(full_d, fill_value=0.0) / E0
    return monthly_ret, float(dd), day_ret, float(df["pnl"].sum())


def fixed_fraction_monthly(trades, lev=1.0):
    """Capital-constrained fixed-fraction (NO compounding).
    Returns (monthly_ret_pct Series, maxdd_pct, daily_ret Series, total_pnl)."""
    taken = _admit_fixed_fraction(trades, lev)
    if not taken:
        return pd.Series(dtype=float), 0.0, pd.Series(dtype=float), 0.0
    df = pd.DataFrame(taken, columns=["ts", "pnl"])
    # monthly: sum of fixed-$ PnL in each calendar month / E0  (rate, not compounded)
    df["m"] = df["ts"].dt.to_period("M")
    monthly_pnl = df.groupby("m")["pnl"].sum()
    monthly_ret = monthly_pnl / E0 * 100.0
    # full calendar-month index (fill empty months with 0)
    full_m = pd.period_range(df["m"].min(), df["m"].max(), freq="M")
    monthly_ret = monthly_ret.reindex(full_m, fill_value=0.0)
    # drawdown on cumulative fixed-$ PnL, as % of E0 (peak = E0 + cum)
    df = df.sort_values("ts")
    cum = E0 + df["pnl"].cumsum()
    cum = pd.concat([pd.Series([E0]), cum], ignore_index=True)
    peak = cum.cummax()
    dd = ((cum - peak) / peak * 100.0).min()
    # calendar-day curve for honest Sharpe
    df["d"] = df["ts"].dt.floor("D")
    day_pnl = df.groupby("d")["pnl"].sum()
    full_d = pd.date_range(day_pnl.index.min(), day_pnl.index.max(), freq="D", tz="UTC")
    day_pnl = day_pnl.reindex(full_d, fill_value=0.0)
    day_ret = day_pnl / E0  # daily return on fixed E0
    return monthly_ret, float(dd), day_ret, float(df["pnl"].sum())


def stats(mr, day_ret):
    if mr is None or mr.empty:
        return dict(n=0, mean=0, med=0, pos=0, mn=0, sd=0, sharpe=0)
    sd_d = day_ret.std()
    sharpe_ann = float(day_ret.mean() / sd_d * np.sqrt(365)) if sd_d > 0 else 0.0
    return dict(n=int(len(mr)), mean=float(mr.mean()), med=float(mr.median()),
                pos=float((mr > 0).mean() * 100), mn=float(mr.min()),
                sd=float(mr.std()), sharpe=sharpe_ann)


def sign_flip_p(Rs, n_iter=10000, seed=SEED):
    """p_gross: prob a random sign-flip of each trade's R gives mean >= observed.
    Tests whether the SIGN structure (the edge) is real vs symmetric noise."""
    a = np.array(Rs, dtype=float)
    if len(a) < 5:
        return 1.0
    obs = a.mean()
    rng = np.random.default_rng(seed)
    cnt = 0
    for _ in range(n_iter):
        flip = rng.choice([-1.0, 1.0], size=len(a))
        if (a * flip).mean() >= obs:
            cnt += 1
    return (cnt + 1) / (n_iter + 1)


def main():
    print("=" * 100)
    print(f"v13 FIXED-FRACTION (NON-compounding) 9%/mo feasibility  FEE_RT={FEE_RT_BPS}bps  E0=${E0:,.0f} risk={RISK_PCT*100:.1f}%")
    print("=" * 100)

    # ---- build best-config pool: 5m(10) + 15m(19), BASELINE exit, widestop ----
    print("gathering 5m(10sym) + 15m(19sym) BASELINE-exit widestop trades @ true 18bps...")
    p05 = []
    for s in SYMS10:
        p05 += [t for t in wlr.gather(s, BASELINE_EXIT, tf="5m") if sl_pct_of(t) >= SL_PCT_MIN]
    p15 = []
    for s in SYMS19:
        p15 += [t for t in wlr.gather(s, BASELINE_EXIT, tf="15m") if sl_pct_of(t) >= SL_PCT_MIN]
    pool = p05 + p15
    print(f"  5m n={len(p05)}  15m n={len(p15)}  TOTAL n={len(pool)}")

    # tag htf alignment
    for t in pool:
        t["htf"] = htf_aligned(t)
    aligned = [t for t in pool if t["htf"] == 1.0]
    print(f"  HTF-1d-aligned subset n={len(aligned)} ({len(aligned)/len(pool)*100:.0f}% of pool)")

    def describe(label, trs):
        R = np.array([R18(t) for t in trs])
        print(f"  {label:<28} n={len(trs):>6} mean_R={R.mean():+.4f} win={np.mean(R>0)*100:.1f}% "
              f"median_R={np.median(R):+.3f}")

    print("\n--- per-trade edge (true 18bps, fixed-fraction-relevant) ---")
    describe("FULL pool (no htf)", pool)
    describe("HTF-aligned (best cfg)", aligned)

    # ---- choose BEST config: compare full vs htf-aligned on fixed-fraction return/DD ----
    print("\n" + "=" * 100)
    print("FIXED-FRACTION UNLEVERED (L=1.0) MONTHLY DISTRIBUTION")
    print("=" * 100)
    candidates = {"FULL pool": pool, "HTF-aligned": aligned}
    best_name, best = None, None
    for nm, trs in candidates.items():
        mr, dd, dret, tot = fixed_fraction_monthly(trs, 1.0)
        s = stats(mr, dret)
        ret_per_dd = s["mean"] / abs(dd) if dd != 0 else 0
        n_taken = len(_admit_fixed_fraction(trs, 1.0))
        print(f"\n[{nm}]  gathered={len(trs)}  ADMITTED={n_taken} ({n_taken/len(trs)*100:.0f}%)  "
              f"n_months={s['n']}  total_PnL=${tot:,.0f} ({tot/E0*100:+.0f}% of E0 over {s['n']}mo)")
        print(f"  mean={s['mean']:+.3f}%/mo  median={s['med']:+.3f}%  pos={s['pos']:.1f}%  "
              f"MIN={s['mn']:+.2f}%  sd={s['sd']:.2f}  MaxDD={dd:+.2f}%  Sharpe(cal-day,ann)={s['sharpe']:+.2f}")
        print(f"  return/DD efficiency = {ret_per_dd:.3f}")
        # pick best by return-per-DD (the honest scaling metric)
        if best is None or ret_per_dd > best[0]:
            best = (ret_per_dd, nm, trs, s, dd)
            best_name = nm
    print(f"\n>>> BEST CONFIG by return/DD: {best_name}")

    bsel = best[2]
    bmr, bdd, bdret, btot = fixed_fraction_monthly(bsel, 1.0)
    bs = stats(bmr, bdret)
    pct = bmr.quantile([0.05, 0.25, 0.5, 0.75, 0.95])
    print(f"  pctiles 5%={pct[0.05]:+.2f} 25%={pct[0.25]:+.2f} 50%={pct[0.5]:+.2f} 75%={pct[0.75]:+.2f} 95%={pct[0.95]:+.2f}")
    print(f"  worst 5 months: {bmr.nsmallest(5).round(2).tolist()}")
    print(f"  best  5 months: {bmr.nlargest(5).round(2).tolist()}")

    # ---- LEVERAGE FRONTIER to +9%/mo ----
    print("\n" + "=" * 100)
    print("LEVERAGE FRONTIER TO +9%/mo  (L scales fixed-$ risk; return & DD ~linear in L)")
    print("=" * 100)
    print(f"{'L':>5} {'mean%/mo':>9} {'median':>8} {'pos%':>6} {'MIN%':>8} {'MaxDD%':>9} {'Sharpe':>7}")
    lev_rows = []
    for L in [1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 5.0, 6.0]:
        mr, dd, dret, _ = fixed_fraction_monthly(bsel, L)
        s = stats(mr, dret)
        lev_rows.append((L, s["mean"], dd, s["mn"], s["pos"], s["sharpe"]))
        print(f"{L:>5.1f} {s['mean']:>+8.3f}% {s['med']:>+7.3f}% {s['pos']:>5.0f}% {s['mn']:>+7.2f}% {dd:>+8.2f}% {s['sharpe']:>+6.2f}")

    # exact L for 9%/mo (linear interpolation: return is exactly linear in L for fixed-fraction)
    L9 = 9.0 / bs["mean"] if bs["mean"] > 0 else float("inf")
    mr9, dd9, dret9, _ = fixed_fraction_monthly(bsel, L9)
    s9 = stats(mr9, dret9)
    print(f"\n>>> EXACT L for +9%/mo: L={L9:.2f}")
    print(f"    -> mean={s9['mean']:+.2f}%/mo  MaxDD={dd9:+.1f}%  MIN_month={s9['mn']:+.2f}%  pos={s9['pos']:.0f}%  Sharpe={s9['sharpe']:+.2f}")

    # max L that keeps DD <= 20%
    L_dd20 = 20.0 / abs(bdd) if bdd != 0 else float("inf")
    mr20, dd20, dret20, _ = fixed_fraction_monthly(bsel, L_dd20)
    s20 = stats(mr20, dret20)
    print(f">>> MAX L at DD<=20%: L={L_dd20:.2f} -> mean={s20['mean']:+.2f}%/mo MaxDD={dd20:+.1f}% MIN={s20['mn']:+.2f}% pos={s20['pos']:.0f}%")

    # ---- WALK-FORWARD IS/OOS ----
    print("\n" + "=" * 100)
    print("WALK-FORWARD  IS=[..2024)  OOS=[2024..)  (fixed-fraction, L=1.0)")
    print("=" * 100)
    for nm, lo, hi in [("IS", pd.Timestamp("2000-01-01", tz="UTC"), IS_END),
                       ("OOS", IS_END, pd.Timestamp("2030-01-01", tz="UTC"))]:
        sub = [t for t in bsel if lo <= pd.Timestamp(t["entry_ts"]) < hi]
        mr, dd, dret, _ = fixed_fraction_monthly(sub, 1.0)
        s = stats(mr, dret)
        R = np.array([R18(t) for t in sub])
        print(f"  {nm:<4} n={len(sub):>5} mean_R={R.mean():+.4f} | {s['n']}mo "
              f"mean={s['mean']:+.3f}%/mo pos={s['pos']:.0f}% MIN={s['mn']:+.2f}% MaxDD={dd:+.1f}% Sharpe={s['sharpe']:+.2f}")

    # ---- TAIL-HAIRCUT STRESS: edge is right-tail (median R<0). If the fat runner
    #      months are execution-fantasy, cap per-trade R at the 95th/99th pctile and
    #      re-measure. This is the honest "can you actually fill the tail" check. ----
    print("\n" + "=" * 100)
    print("TAIL-HAIRCUT STRESS (edge is right-tail; cap R at pctile to kill fantasy runners)")
    print("=" * 100)
    Rs_all = np.array([R18(t) for t in bsel])
    for q in [1.00, 0.99, 0.95, 0.90]:
        cap = float(np.quantile(Rs_all, q)) if q < 1.0 else 1e9
        cpool = []
        for t in bsel:
            tt = dict(t); tt["_R18_override"] = min(R18(t), cap); cpool.append(tt)
        mr, dd, dret, tot = _ff_monthly_override(cpool, 1.0)
        s = stats(mr, dret)
        L9c = 9.0 / s["mean"] if s["mean"] > 0 else float("inf")
        ddc = dd * L9c
        print(f"  R-cap@{int(q*100)}%pctile(R={cap if q<1 else float('inf'):+.2f}): mean={s['mean']:+.2f}%/mo "
              f"MaxDD={dd:+.2f}% pos={s['pos']:.0f}% MIN={s['mn']:+.2f}% | L_for_9%={L9c:.2f} DD@9%={ddc:+.1f}%")

    # ---- SIGN-FLIP p_gross (real edge test) ----
    print("\n--- SIGN-FLIP p_gross (n=10000) on best-config R (true 18bps) ---")
    pg = sign_flip_p([R18(t) for t in bsel], n_iter=10000)
    print(f"  p_gross = {pg:.5f}  ({'PASS <0.05 (edge real)' if pg < 0.05 else 'FAIL'})")
    pg_oos = sign_flip_p([R18(t) for t in bsel if pd.Timestamp(t['entry_ts']) >= IS_END], n_iter=10000)
    print(f"  p_gross OOS-only = {pg_oos:.5f}  ({'PASS' if pg_oos < 0.05 else 'FAIL'})")

    out = dict(fee_rt_bps=FEE_RT_BPS, best_config=best_name, E0=E0, risk_pct=RISK_PCT,
               unlevered=dict(**bs, maxdd=bdd, total_pnl=btot),
               L_for_9pct=L9, dd_at_9pct=dd9, min_at_9pct=s9["mn"], pos_at_9pct=s9["pos"],
               L_at_dd20=L_dd20, mean_at_dd20=s20["mean"],
               lev_rows=lev_rows, p_gross=pg, p_gross_oos=pg_oos)
    json.dump(out, open("/tmp/v13_9pct_fixedfraction.json", "w"), indent=2, default=str)
    print("\n[dumped /tmp/v13_9pct_fixedfraction.json]")


if __name__ == "__main__":
    main()
