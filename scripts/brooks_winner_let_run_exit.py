"""HYP-2026-05-29-brooks-winner-let-run-exit-optimization.

WINNER-LET-RUN exit optimization on brooks_failed_breakout (8 FX 4H + 3 core sub-TF).

METHOD (artifact-free, per pre-reg):
  - Trades generated through the REAL BacktestEngine. Exit is parameterized via
    engine CONSTRUCTOR knobs (trail_mult, tp1/tp2_R, close_pct, activate_stage,
    runner_force_exit_method/bars). NO hand-coded exit.
  - ATR for trail = strategy sig.metadata["atr14"], computed by the strategy on the
    run-timeframe bars. Running engine on 15m/30m -> ATR NATIVE sub-TF (no 4H-ATR
    injection -> NOT the MTF v1 artifact).
  - Same entry signals across all exit variants; only exit changes.
  - Filters/cost replicate forex_4h_research.gather verbatim (session, weekend-block,
    swap haircut, slippage 1.0bps, fee=0).

GATE 1 (Feynman, falsif #1): engine default-exit must REPRODUCE /tmp/rt_trades.pkl R
(per-sym mean|ΔR| <= 0.02) before any variant is trusted.

Usage: .venv/bin/python scripts/brooks_winner_let_run_exit.py [--gate-only] [--subtf]
"""
from __future__ import annotations

import os, sys, pickle, hashlib
from pathlib import Path
from statistics import mean

os.environ["PA_LOG_QUIET"] = "1"
import warnings; warnings.filterwarnings("ignore")
import numpy as np, pandas as pd, duckdb, yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "src"))

from price_action.backtest.engine import BacktestEngine
from price_action.backtest.lab import ProductionConfig, production_replay

DB = ROOT / "data" / "forex_market.duckdb"
FEES = {"taker": 0.0, "maker": 0.0}
SLIPPAGE_BPS = 1.0
SWAP_BPS_PER_NIGHT = 0.3
ATR_MIN_PCT = 0.0008
SESSION_START_H, SESSION_END_H = 7, 16
SEED = 12345
IS_END = pd.Timestamp("2024-01-01", tz="UTC")
OOS_END = pd.Timestamp("2026-01-01", tz="UTC")
SYMBOLS_8 = ["EUR/USD", "GBP/USD", "USD/JPY", "AUD/USD", "USD/CHF", "EUR/GBP", "USD/CAD", "NZD/USD"]
CORE3 = ["EUR/USD", "GBP/USD", "USD/JPY"]
RISK_BLOCK = {"AUD/USD", "NZD/USD"}


# ---- filters (verbatim from forex_4h_research) ----
def in_session(ts):
    return SESSION_START_H <= ts.hour <= SESSION_END_H


def is_weekend_block(ts):
    wd = ts.dayofweek
    if wd == 4 and ts.hour >= 16:
        return True
    return wd in (5, 6)


def nights_held(e, x):
    if x <= e:
        return 0
    d0, d1 = e.normalize(), x.normalize()
    nights = int((d1 - d0).days)
    if nights <= 0:
        return 0
    triple = 0
    cur = d0 + pd.Timedelta(days=1)
    while cur <= d1:
        if cur.dayofweek == 2:
            triple += 1
        cur += pd.Timedelta(days=1)
    return nights + 2 * triple


def load_ohlcv(sym, tf):
    con = duckdb.connect(str(DB), read_only=True)
    df = con.execute(
        "SELECT ts,open,high,low,close,volume FROM ohlcv WHERE symbol=? AND timeframe=? ORDER BY ts",
        [sym, tf],
    ).fetchdf()
    con.close()
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    df = df.sort_values("ts").reset_index(drop=True)
    df["symbol"], df["venue"], df["timeframe"] = sym, "forex", tf
    return df


def build_strategy():
    mod = __import__("price_action.strategies.brooks_failed_breakout",
                     fromlist=["BrooksFailedBreakoutStrategy", "_default_manifest"])
    manifest = mod._default_manifest()
    manifest.signals.filters.atr_min_pct = ATR_MIN_PCT
    return mod.BrooksFailedBreakoutStrategy(manifest)


def gather(sym, tf, exit_cfg: dict) -> list[dict]:
    """Run real engine with given exit constructor config. Return trade dicts."""
    df = load_ohlcv(sym, tf)
    if df.empty:
        return []
    strat = build_strategy()

    def prov(*a, **k):
        return df.copy()

    e = BacktestEngine(risk_officer=None, store_load=None, **exit_cfg)
    r = e.run(strat, [sym], start=df["ts"].iloc[0].to_pydatetime(),
              end=df["ts"].iloc[-1].to_pydatetime(), timeframe=tf,
              initial_capital=10_000.0, fees=FEES, slippage_bps=SLIPPAGE_BPS,
              ohlcv_provider=prov)
    out = []
    if r.trades is None or r.trades.empty:
        return out
    for _, t in r.trades.iterrows():
        te = pd.Timestamp(t["entry_ts"]); te = te.tz_localize("UTC") if te.tzinfo is None else te.tz_convert("UTC")
        tx = pd.Timestamp(t["exit_ts"]); tx = tx.tz_localize("UTC") if tx.tzinfo is None else tx.tz_convert("UTC")
        if not in_session(te) or is_weekend_block(te):
            continue
        R = float(t["realized_r_multiple"]); gross_R = R
        ep, sp = float(t["entry_price"]), float(t["initial_sl"])
        sl_pct = abs(ep - sp) / ep if ep > 0 else 0.0
        sl_bps = sl_pct * 1e4
        nh = nights_held(te, tx)
        swap_R = (nh * SWAP_BPS_PER_NIGHT) / sl_bps if sl_bps > 0 else 0.0
        conf = max(0.0, min(1.0, (float(t["confluence_score"]) - 1.5) / 1.5)) if "confluence_score" in t else 0.33
        out.append({"entry_ts": te, "exit_ts": tx, "entry_price": ep, "initial_sl": sp,
                    "R": R - swap_R, "gross_R": gross_R, "swap_R": swap_R, "nights": nh,
                    "symbol": sym, "side": str(t["side"]).lower(), "conf": conf,
                    "hold_days": (tx - te) / pd.Timedelta(days=1), "strategy": strat.name})
    return out


# ---- USD exposure cap (verbatim from honest_cap) ----
def usd_dir(sym, side):
    is_long = side == "long"
    if sym.endswith("/USD"):
        return -1 if is_long else +1
    if sym.startswith("USD/"):
        return +1 if is_long else -1
    return 0


def risk_parity(trades_by_sym, symbols):
    block = RISK_BLOCK.issubset(set(symbols))
    pooled = []
    for s in symbols:
        sc = 0.5 if (block and s in RISK_BLOCK) else 1.0
        for t in trades_by_sym[s]:
            t2 = dict(t)
            if sc != 1.0:
                t2["R"] = t["R"] * sc
                t2["gross_R"] = t.get("gross_R", t["R"]) * sc
            pooled.append(t2)
    return sorted(pooled, key=lambda x: x["entry_ts"])


def apply_net_usd_cap(pooled, net_cap, gross_cap=8):
    if not pooled:
        return []
    ps = sorted(pooled, key=lambda x: x["entry_ts"])
    open_pos, adm = [], []
    for t in ps:
        now = t["entry_ts"]
        open_pos = [p for p in open_pos if pd.Timestamp(p["exit_ts"]) > now]
        if len(open_pos) >= gross_cap:
            continue
        u = usd_dir(t["symbol"], t["side"])
        if net_cap is not None and abs(sum(p["usd"] for p in open_pos) + u) > net_cap:
            continue
        open_pos.append({"exit_ts": t["exit_ts"], "usd": u})
        adm.append(t)
    return adm


# ---- portfolio replay + stats ----
def build_pcfg(mc=6):
    raw = yaml.safe_load((ROOT / "configs" / "risk_forex.yaml").read_text())
    return ProductionConfig(
        risk_pct=0.015, leverage=float(raw["leverage"]["max_leverage_per_symbol"]),
        max_notional_pct_equity=None, conf_min=0.0,
        daily_dd=raw["drawdown_breakers"]["daily_loss_pct"],
        weekly_dd=raw["drawdown_breakers"]["weekly_loss_pct"],
        monthly_dd=raw["drawdown_breakers"]["monthly_loss_pct"],
        consecutive_loss_n=None, same_symbol_side_cooldown_days=1.0,
        max_concurrent=mc, initial_capital=10_000.0)


def cont_dd(eq):
    peak = eq[0]; mdd = 0.0
    for v in eq:
        peak = max(peak, v); mdd = min(mdd, (v - peak) / peak if peak > 0 else 0.0)
    return mdd * 100.0


def monthly_ret(eq, ex_ts):
    s = pd.Series(eq[1:], index=pd.to_datetime([pd.Timestamp(t) for t in ex_ts], utc=True)).sort_index()
    me = s.resample("ME").last().dropna()
    if me.empty:
        return pd.Series(dtype=float)
    prev = pd.Series([eq[0]] + list(me.values[:-1]), index=me.index)
    return (me / prev - 1.0) * 100.0


def robust_median(mr):
    if mr.empty:
        return None
    k = max(1, int(np.ceil(len(mr) * 0.05)))
    return float(mr.sort_values()[:-k].median()) if k < len(mr) else float(mr.median())


def r_skew_stats(Rs):
    a = np.array(Rs, dtype=float)
    if len(a) == 0:
        return dict(n=0, mR=0, wr=0, pf=0, top5=0, hold=0)
    wins = a[a > 0]; losses = a[a < 0]
    pf = wins.sum() / abs(losses.sum()) if losses.sum() != 0 else float("inf")
    thr = np.percentile(a, 95)
    top5 = a[a >= thr].sum() / wins.sum() * 100 if wins.sum() > 0 else 0.0
    return dict(n=len(a), mR=float(a.mean()), wr=len(wins) / len(a) * 100, pf=pf, top5=top5)


def portfolio_profile(pooled, mc=6, eff_r=0.015):
    if not pooled:
        return None
    c = build_pcfg(mc).with_overrides(risk_pct=eff_r)
    res = production_replay(sorted(pooled, key=lambda x: x["entry_ts"]), c)
    if res is None:
        return None
    mr = monthly_ret(res.equity_curve, res.entry_ts_list)
    if mr.empty:
        return None
    holds = [t.get("hold_days", 0) for t in pooled]
    return dict(n_tr=res.trades, robmed=robust_median(mr), med=float(mr.median()),
                mean=float(mr.mean()), std=float(mr.std()),
                sharpe=float(mr.mean() / mr.std()) if mr.std() > 0 else 0.0,
                dd=cont_dd(res.equity_curve), final=res.final_equity / 10000.0,
                med_dd=robust_median(mr) / abs(cont_dd(res.equity_curve)) if cont_dd(res.equity_curve) != 0 else 0,
                hold_med=float(np.median(holds)) if holds else 0.0)


def shuffle_p(Rs, n_iter=4000, seed=SEED):
    a = np.array(Rs, dtype=float)
    if len(a) < 5:
        return 1.0
    obs = a.mean()
    rng = np.random.default_rng(seed)
    cnt = 0
    for _ in range(n_iter):
        s = rng.choice(a, size=len(a), replace=True)
        if s.mean() >= obs:
            cnt += 1
    return (cnt + 1) / (n_iter + 1)


# ---- exit variant configs ----
BASELINE = dict(runner_trail_mult=1.5, trail_activate_stage=2, tp1_R=1.0, tp2_R=1.5,
                tp1_close_pct=0.30, tp2_close_pct=0.30,
                runner_force_exit_method="time", runner_force_exit_bars=30)


def variants():
    V = {"B_baseline": dict(BASELINE)}
    # V1a wide-trail (time-exit kept)
    for m in (2.0, 2.5, 3.0):
        V[f"V1a_trail{m}"] = {**BASELINE, "runner_trail_mult": m}
    # V1b no-time-exit + wide trail (tail-risk test)
    for m in (1.5, 2.5):
        V[f"V1b_notime_trail{m}"] = {**BASELINE, "runner_trail_mult": m,
                                     "runner_force_exit_method": "atr_only",
                                     "runner_force_exit_bars": None}
    # V1c push TP2 + heavier runner
    V["V1c_tp2_3_run50"] = {**BASELINE, "tp2_R": 3.0, "tp1_close_pct": 0.30, "tp2_close_pct": 0.20}
    V["V1c_tp2_2_run50"] = {**BASELINE, "tp2_R": 2.0, "tp1_close_pct": 0.30, "tp2_close_pct": 0.20}
    # V2 single-partial + heavy runner (tp2 off)
    for m in (1.5, 2.5):
        V[f"V2_1partial_run70_trail{m}"] = {**BASELINE, "tp2_R": 1.5, "tp2_close_pct": 0.0,
                                            "tp1_close_pct": 0.30, "runner_trail_mult": m,
                                            "trail_activate_stage": 1}
    # V3 pure trail (no TP)
    for m in (1.5, 2.5):
        V[f"V3_puretrail{m}"] = {**BASELINE, "tp1_close_pct": 0.0, "tp2_close_pct": 0.0,
                                 "trail_activate_stage": 1, "runner_trail_mult": m}
    return V


def fmt_skew(tag, s):
    return (f"{tag:<26} n={s['n']:>4} mR={s['mR']:>+.3f} wr={s['wr']:>4.0f}% "
            f"pf={s['pf']:>4.2f} top5={s['top5']:>4.0f}%")


def main():
    subtf_only = "--subtf" in sys.argv
    gate_only = "--gate-only" in sys.argv

    # ---- GATE 1: reproduce baseline pkl with default exit ----
    print("=" * 100)
    print("GATE 1 (Feynman/falsif#1): reproduce /tmp/rt_trades.pkl with engine DEFAULT exit")
    print("=" * 100)
    pkl = pickle.load(open("/tmp/rt_trades.pkl", "rb"))
    pkl_tr = pkl["trades"]
    repro = {}
    gate_pass = True
    for sym in SYMBOLS_8:
        gen = gather(sym, "4h", BASELINE)
        repro[sym] = gen
        # match by entry_ts
        pmap = {pd.Timestamp(t["entry_ts"]): t["gross_R"] for t in pkl_tr[sym]}
        diffs = []
        for t in gen:
            if t["entry_ts"] in pmap:
                diffs.append(t["gross_R"] - pmap[t["entry_ts"]])
        md = np.mean(np.abs(diffs)) if diffs else 99
        mx = np.max(np.abs(diffs)) if diffs else 99
        ok = md <= 0.02
        gate_pass &= ok
        print(f"  {sym:<9} gen_n={len(gen):>4} pkl_n={len(pkl_tr[sym]):>4} matched={len(diffs):>4} "
              f"mean|ΔR|={md:.4f} max|ΔR|={mx:.4f}  {'PASS' if ok else 'FAIL'}")
    print(f"\nGATE 1: {'PASS — baseline reproduced, harness trusted' if gate_pass else 'FAIL — harness NOT trusted, STOP'}")
    if gate_only or not gate_pass:
        return

    # ---- generate all variants (4H, 8 FX) ----
    V = variants()
    print("\n" + "=" * 100)
    print(f"Generating {len(V)} exit variants x 8 FX (4H, real engine)...")
    print("=" * 100)
    var_trades = {}  # name -> {sym: trades}
    for name, cfg in V.items():
        var_trades[name] = {s: (repro[s] if name == "B_baseline" else gather(s, "4h", cfg)) for s in SYMBOLS_8}
        print(f"  {name:<26} done (sumtrades={sum(len(v) for v in var_trades[name].values())})")
    pickle.dump(var_trades, open("/tmp/wlr_variants_4h.pkl", "wb"))

    # ---- per-variant IS/OOS pooled skew stats + portfolio profile ----
    def split(trs, lo, hi):
        return [t for t in trs if lo <= t["entry_ts"] < hi]

    print("\n" + "=" * 100)
    print("(b) POOLED R-SKEW: IS=[2020,2024) vs OOS=[2024,2026)  (8 FX, netUSD<=3 mc6, risk-parity)")
    print("=" * 100)
    rows = {}
    for name in V:
        pooled = risk_parity(var_trades[name], SYMBOLS_8)
        capped = apply_net_usd_cap(pooled, 3, 6)
        is_t = split(capped, pd.Timestamp("2020-01-01", tz="UTC"), IS_END)
        oos_t = split(capped, IS_END, OOS_END)
        si = r_skew_stats([t["R"] for t in is_t]); so = r_skew_stats([t["R"] for t in oos_t])
        pi = portfolio_profile(is_t); po = portfolio_profile(oos_t)
        rows[name] = dict(si=si, so=so, pi=pi, po=po, capped=capped, is_t=is_t, oos_t=oos_t)

    hdr = (f"{'variant':<26} | {'IS_mR':>6} {'IS_wr':>5} {'IS_top5':>7} {'IS_robM':>7} {'IS_shrp':>7} {'IS_DD':>6} {'IS_hd':>5} "
           f"| {'OOS_mR':>6} {'OOS_wr':>5} {'OOS_top5':>8} {'OOS_robM':>8} {'OOS_shrp':>8} {'OOS_DD':>6} {'OOS_hd':>5}")
    print(hdr); print("-" * len(hdr))
    base = rows["B_baseline"]
    for name in V:
        r = rows[name]; si, so, pi, po = r["si"], r["so"], r["pi"], r["po"]
        if pi is None or po is None:
            print(f"{name:<26} | (no portfolio profile)"); continue
        print(f"{name:<26} | {si['mR']:>+6.3f} {si['wr']:>4.0f}% {si['top5']:>6.0f}% {pi['robmed']:>+6.2f} {pi['sharpe']:>+6.3f} {pi['dd']:>+5.1f} {pi['hold_med']:>4.1f} "
              f"| {so['mR']:>+6.3f} {so['wr']:>4.0f}% {so['top5']:>7.0f}% {po['robmed']:>+7.2f} {po['sharpe']:>+7.3f} {po['dd']:>+5.1f} {po['hold_med']:>4.1f}")

    # ---- Δ vs baseline (OOS) + falsification flags + shuffle-p + BH-FDR ----
    print("\n" + "=" * 100)
    print("(c) Δ vs BASELINE (OOS) — winner-let-run net effect + falsification checks")
    print("=" * 100)
    bo, bpo = base["so"], base["po"]
    print(f"BASELINE OOS: mR={bo['mR']:+.3f} wr={bo['wr']:.0f}% top5={bo['top5']:.0f}% "
          f"robMed={bpo['robmed']:+.2f} sharpe={bpo['sharpe']:+.3f} DD={bpo['dd']:+.1f} hold={bpo['hold_med']:.1f}d")
    print(f"{'variant':<26} {'Δtop5':>7} {'ΔmR':>7} {'ΔrobM':>7} {'Δsharpe':>8} {'ΔDD':>6} {'Δhold':>6} {'shuf_p':>7}  verdict")
    print("-" * 110)
    pvals = []
    for name in V:
        if name == "B_baseline":
            continue
        r = rows[name]; so, po = r["so"], r["po"]
        if po is None:
            continue
        dtop5 = so["top5"] - bo["top5"]; dmr = so["mR"] - bo["mR"]
        drob = po["robmed"] - bpo["robmed"]; dshrp = po["sharpe"] - bpo["sharpe"]
        ddd = po["dd"] - bpo["dd"]; dhold = po["hold_med"] - bpo["hold_med"]
        sp = shuffle_p([t["R"] for t in r["oos_t"]])
        pvals.append((name, sp))
        # H1 needs: top5 up AND (robmed up OR sharpe up) AND mR not negative
        h1 = (dtop5 > 0) and (drob > 0 or dshrp > 0) and (dmr >= -0.005)
        v = "H1-candidate" if h1 else "reject"
        print(f"{name:<26} {dtop5:>+6.0f}% {dmr:>+7.3f} {drob:>+6.2f} {dshrp:>+7.3f} {ddd:>+5.1f} {dhold:>+5.1f}d {sp:>6.3f}  {v}")

    # BH-FDR over shuffle p-values
    if pvals:
        pvals_sorted = sorted(pvals, key=lambda x: x[1])
        m = len(pvals_sorted)
        print("\n  BH-FDR (alpha=0.05) over OOS shuffle-p:")
        crit = None
        for i, (name, p) in enumerate(pvals_sorted, 1):
            thr = 0.05 * i / m
            sig = p <= thr
            if sig:
                crit = i
            print(f"    {i:>2}. {name:<26} p={p:.4f}  BH_thr={thr:.4f}  {'sig' if sig else ''}")
        print(f"  -> BH cutoff rank: {crit if crit else 'NONE (no variant beats null after FDR)'}")

    print("\nDONE 4H. Run with --subtf for sub-TF (V4) sanity.")


if __name__ == "__main__":
    main()
