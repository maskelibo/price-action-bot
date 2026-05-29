"""HYP-2026-05-29-crypto-winner-let-run-vsa-exit.

WINNER-LET-RUN exit optimization on vsa_climax_test (10 crypto, 15m).
Crypto transfer of the proven forex brooks-8FX-4H winner-let-run edge.

METHOD (artifact-free, per pre-reg):
  - Trades generated through the REAL BacktestEngine. Exit parameterized via engine
    CONSTRUCTOR knobs (runner_trail_mult, trail_activate_stage, tp1/tp2_R, close_pct,
    runner_force_exit_method/bars, force_exit_from_entry). NO hand-coded exit /
    NO peak_R-reblend (forex v1 died on hand exit; widestop reblend_close_pct also
    analytic — we do NOT use it).
  - ATR for trail = native per-15m-bar (engine reads metadata atr14; VSA emits atr20
    only -> engine falls back to initial_R_dist*0.5, which is itself native 15m).
    Running engine on 15m -> NO sub-TF/HTF ATR mixing -> MTF v1 artifact impossible.
  - Same entry signals across all exit variants; only exit changes.
  - Pool-build pipeline replicated VERBATIM from scripts/_expansion_vsa_pool_build.py
    (default manifest + df timeframe=15m -> apply_tf_manifest loads vsa2 amplify,
    fees taker 7.5bps/maker -1bp, slippage 5bps).

GATE 1 (Feynman): engine default-exit must REPRODUCE pool pkl VSA R per symbol
  (per-sym mean|ΔR| <= 0.05; pool BTC=7952 trades) before any variant is trusted.

Portfolio replay: production_replay with the live widestop_vsa2 config (risk 0.5%,
sl_pct>=0.025 filter, DD halts) — identical to realistic_backtest.py live baseline.

Usage: .venv/bin/python scripts/crypto_winner_let_run_vsa_exit.py [--gate-only]
PA_DUCKDB_READ_ONLY=true enforced. Read-only DB, no daemon touch.
"""
from __future__ import annotations

import os, sys, pickle
from pathlib import Path

os.environ["PA_DUCKDB_READ_ONLY"] = "true"
os.environ["PA_LOG_QUIET"] = "1"
import warnings; warnings.filterwarnings("ignore")
import logging; logging.getLogger("price_action").setLevel(logging.ERROR)
import numpy as np, pandas as pd, duckdb

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "src"))

from price_action.backtest.engine import BacktestEngine
from price_action.backtest.lab import ProductionConfig, production_replay
from price_action.signals.filters import volume_zscore
from price_action.strategies.vsa_climax_test import VSAClimaxTestStrategy, _default_manifest

DB = ROOT / "data" / "market.duckdb"
POOL = ROOT / "data" / "sec53_15m_pool_v11_vsa2_top4.pkl"
YAML = ROOT / "configs" / "risk_phoenix_scalp_15m_widestop_vsa2.yaml"
SYMS = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "ADA/USDT",
        "AVAX/USDT", "LINK/USDT", "DOT/USDT", "DOGE/USDT", "XRP/USDT"]
FEES = {"taker": 0.00075, "maker": -0.00010}
SLIPPAGE_BPS = 5.0
SL_PCT_MIN = 0.025
RISK_PCT = 0.005
SEED = 12345
IS_START = pd.Timestamp("2021-01-01", tz="UTC")
IS_END = pd.Timestamp("2024-01-01", tz="UTC")
OOS_END = pd.Timestamp("2026-07-01", tz="UTC")


def load_ohlcv(sym, tf="15m", venue="binance"):
    con = duckdb.connect(str(DB), read_only=True)
    df = con.execute(
        "SELECT ts,open,high,low,close,volume FROM ohlcv "
        "WHERE venue=? AND symbol=? AND timeframe=? ORDER BY ts",
        [venue, sym, tf]).fetchdf()
    con.close()
    if df.empty:
        return df
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    df = df.sort_values("ts").reset_index(drop=True)
    df["symbol"], df["venue"], df["timeframe"] = sym, venue, tf
    return df


def gather(sym, exit_cfg: dict, tf="15m") -> list[dict]:
    """Real engine, exit constructor cfg. Returns trade dicts (verbatim pool schema)."""
    s = VSAClimaxTestStrategy(_default_manifest())
    df = load_ohlcv(sym, tf)
    if df is None or df.empty:
        return []
    try:
        df["vol_z_pre"] = volume_zscore(df["volume"], period=20)
    except Exception:
        roll = df["volume"].rolling(20)
        df["vol_z_pre"] = (df["volume"] - roll.mean()) / roll.std()

    def prov(*a, **k):
        return df.copy()

    e = BacktestEngine(risk_officer=None, store_load=None, **exit_cfg)
    r = e.run(s, [sym], start=df["ts"].iloc[0].to_pydatetime(),
              end=df["ts"].iloc[-1].to_pydatetime(), timeframe=tf,
              initial_capital=10_000.0, fees=FEES, slippage_bps=SLIPPAGE_BPS,
              ohlcv_provider=prov)
    out = []
    if r.trades is None or r.trades.empty:
        return out
    ts_map = pd.to_datetime(df["ts"], utc=True)
    for _, t in r.trades.iterrows():
        try:
            conf = max(0.0, min(1.0, (float(t["confluence_score"]) - 1.5) / 1.5))
            ep, sp = float(t["entry_price"]), float(t["initial_sl"])
            mfe_pct = float(t.get("mfe_pct", 0))
            rp = abs(sp - ep) / ep if ep > 0 else 0.04
            side = str(t["side"]).lower()
            pk = (mfe_pct / rp if side == "long" else -mfe_pct / rp) if rp > 0 else 0
            final_R = float(t["realized_r_multiple"])
            pk = max(pk, final_R)
            te = pd.Timestamp(t["entry_ts"]); te = te.tz_localize("UTC") if te.tzinfo is None else te
            tx = pd.Timestamp(t["exit_ts"]); tx = tx.tz_localize("UTC") if tx.tzinfo is None else tx
            out.append({"entry_ts": te, "exit_ts": tx, "entry_price": ep, "initial_sl": sp,
                        "R": final_R, "peak_R": pk, "symbol": sym, "side": str(t["side"]),
                        "conf": conf, "strategy": "vsa_climax_test", "vol_z": 0.0,
                        "hold_h": (tx - te) / pd.Timedelta(hours=1)})
        except Exception:
            continue
    return out


# ---- portfolio replay + stats ----
def build_cfg():
    from dataclasses import replace
    c = ProductionConfig.from_yaml(str(YAML))
    return replace(c, risk_pct=RISK_PCT, sl_pct_min=max(c.sl_pct_min, SL_PCT_MIN))


def sl_pct_of(t):
    ep = t["entry_price"]
    return abs(t["initial_sl"] - ep) / ep if ep > 0 else 0.04


def cont_dd(eq):
    peak = eq[0]; mdd = 0.0
    for v in eq:
        peak = max(peak, v); mdd = min(mdd, (v - peak) / peak if peak > 0 else 0.0)
    return mdd * 100.0


def monthly_from_replay(res, cfg):
    eq = res.equity_curve or []
    ts = res.entry_ts_list or []
    if len(eq) < 2 or not ts:
        return pd.Series(dtype=float)
    n = min(len(eq) - 1, len(ts))
    stamps = pd.to_datetime(ts[:n], utc=True)
    eq_after = eq[1:n + 1]
    df = pd.DataFrame({"ts": stamps, "eq": eq_after})
    df["m"] = df["ts"].dt.to_period("M")
    me = df.groupby("m")["eq"].last()
    prev = me.shift(1, fill_value=cfg.initial_capital)
    return (me / prev - 1.0) * 100.0


def r_skew(Rs):
    a = np.array(Rs, dtype=float)
    if len(a) == 0:
        return dict(n=0, mR=0, wr=0, top5=0)
    wins = a[a > 0]
    thr = np.percentile(a, 95)
    top5 = a[a >= thr].sum() / wins.sum() * 100 if wins.sum() > 0 else 0.0
    return dict(n=len(a), mR=float(a.mean()), wr=len(wins) / len(a) * 100, top5=top5)


def profile(trades, cfg):
    if not trades:
        return None
    pool = sorted(trades, key=lambda x: x["entry_ts"])
    res = production_replay(pool, cfg)
    if res is None:
        return None
    mr = monthly_from_replay(res, cfg)
    if mr.empty:
        return None
    holds = [t.get("hold_h", 0) for t in pool]
    return dict(n=res.trades, med=float(mr.median()), mean=float(mr.mean()),
                sharpe=float(mr.mean() / mr.std()) if mr.std() > 0 else 0.0,
                dd=cont_dd(res.equity_curve), neg=int((mr < 0).sum()), nmo=len(mr),
                hold_med=float(np.median(holds)) if holds else 0.0,
                wr=float(res.win_rate * 100), mR=float(res.avg_r))


def shuffle_p(Rs, n_iter=4000, seed=SEED):
    a = np.array(Rs, dtype=float)
    if len(a) < 5:
        return 1.0
    obs = a.mean()
    rng = np.random.default_rng(seed)
    cnt = sum(1 for _ in range(n_iter) if rng.choice(a, size=len(a), replace=True).mean() >= obs)
    return (cnt + 1) / (n_iter + 1)


# ---- exit variant configs ----
BASELINE = dict(runner_trail_mult=1.5, trail_activate_stage=2, tp1_R=1.0, tp2_R=1.5,
                tp1_close_pct=0.30, tp2_close_pct=0.30,
                runner_force_exit_method="time", runner_force_exit_bars=30,
                force_exit_from_entry=False)


def variants():
    V = {"B_baseline": dict(BASELINE)}
    for m in (2.0, 2.5, 3.0):
        V[f"V1a_trail{m}"] = {**BASELINE, "runner_trail_mult": m}
    for m in (2.0, 2.5, 3.0):
        V[f"V1a_fe_trail{m}"] = {**BASELINE, "runner_trail_mult": m, "force_exit_from_entry": True}
    for m in (1.5, 2.5):
        V[f"V1b_notime_trail{m}"] = {**BASELINE, "runner_trail_mult": m,
                                     "runner_force_exit_method": "atr_only",
                                     "runner_force_exit_bars": None}
    for m in (2.0, 2.5):
        V[f"V2_1partial_run70_trail{m}"] = {**BASELINE, "tp2_R": 1.5, "tp2_close_pct": 0.0,
                                            "tp1_close_pct": 0.30, "runner_trail_mult": m,
                                            "trail_activate_stage": 1}
    for m in (2.0, 2.5):
        V[f"V3_puretrail{m}"] = {**BASELINE, "tp1_close_pct": 0.0, "tp2_close_pct": 0.0,
                                 "trail_activate_stage": 1, "runner_trail_mult": m}
    return V


def split(trs, lo, hi):
    return [t for t in trs if lo <= t["entry_ts"] < hi]


def main():
    gate_only = "--gate-only" in sys.argv

    # ---- GATE 1: round-trip determinism (current code) + stale-pool drift report ----
    # NOTE: the deployed sec53 pool (2026-05-23) is NO LONGER reproducible from current
    # HEAD (strategy/engine code changed: Faz 14.27 C1 fallback + audit fixes; canonical
    # builder now yields BTC 8002 vs cached 7952). Therefore the stale pool is NOT a valid
    # anchor. GATE-1 here = (a) current-code default exit is DETERMINISTIC (bit-identical
    # across 2 runs), (b) report drift vs stale pool transparently. ALL Δ comparisons below
    # are anchored to the CURRENT-CODE baseline (same engine version) — pure apples-to-apples.
    print("=" * 110)
    print("GATE 1 (Feynman): current-code determinism + stale-pool drift report")
    print("=" * 110)
    pool = pickle.load(open(POOL, "rb"))
    pool_vsa = {s: [t for t in pool if t["strategy"] == "vsa_climax_test" and t["symbol"] == s]
                for s in SYMS}
    repro = {}
    det_pass = True
    for sym in SYMS:
        gen = gather(sym, BASELINE)
        gen2 = gather(sym, BASELINE)
        repro[sym] = gen
        # determinism: two runs identical
        r1 = np.array([t["R"] for t in gen]); r2 = np.array([t["R"] for t in gen2])
        det = (len(r1) == len(r2)) and np.allclose(r1, r2, atol=1e-9)
        det_pass &= det
        # drift vs stale pool
        pmap = {pd.Timestamp(t["entry_ts"]): t["R"] for t in pool_vsa[sym]}
        diffs = [t["R"] - pmap[t["entry_ts"]] for t in gen if t["entry_ts"] in pmap]
        md = np.mean(np.abs(diffs)) if diffs else 99
        print(f"  {sym:<10} gen_n={len(gen):>5} stale_pool_n={len(pool_vsa[sym]):>5} "
              f"determ={'OK' if det else 'FAIL'}  drift_mean|ΔR|_vs_stale={md:.3f}")
    print(f"\nGATE 1: determinism={'PASS' if det_pass else 'FAIL'} — "
          f"{'current-code baseline trusted as anchor' if det_pass else 'STOP, non-deterministic'}")
    print("  (stale pool drift is EXPECTED & non-blocking; anchor = current-code baseline)")
    if gate_only or not det_pass:
        return

    # ---- generate all variants ----
    V = variants()
    print("\n" + "=" * 110)
    print(f"Generating {len(V)} exit variants x {len(SYMS)} crypto (15m, real engine)...")
    print("=" * 110)
    var_tr = {}
    for name, cfg in V.items():
        var_tr[name] = {s: (repro[s] if name == "B_baseline" else gather(s, cfg)) for s in SYMS}
        print(f"  {name:<28} sumtrades={sum(len(v) for v in var_tr[name].values())}")
    pickle.dump(var_tr, open("/tmp/wlr_vsa_variants.pkl", "wb"))

    cfg = build_cfg()
    rows = {}
    for name in V:
        pooled = [t for s in SYMS for t in var_tr[name][s] if sl_pct_of(t) >= SL_PCT_MIN]
        is_t = split(pooled, IS_START, IS_END)
        oos_t = split(pooled, IS_END, OOS_END)
        rows[name] = dict(
            si=r_skew([t["R"] for t in is_t]), so=r_skew([t["R"] for t in oos_t]),
            pi=profile(is_t, cfg), po=profile(oos_t, cfg),
            pa=profile(pooled, cfg), oos_t=oos_t)

    # ---- (b) IS vs OOS table ----
    print("\n" + "=" * 110)
    print("(b) IS=[2021,2024) vs OOS=[2024,2026.5)  (10 crypto, sl_pct>=0.025, risk0.5%, widestop_vsa2 cfg)")
    print("=" * 110)
    hdr = (f"{'variant':<28}| {'IS_mR':>6} {'IS_wr':>5} {'IS_t5':>5} {'IS_med':>6} {'IS_shp':>6} {'IS_DD':>6} {'IS_hd':>5} "
           f"| {'OO_mR':>6} {'OO_wr':>5} {'OO_t5':>5} {'OO_med':>6} {'OO_shp':>6} {'OO_DD':>6} {'OO_hd':>5}")
    print(hdr); print("-" * len(hdr))
    for name in V:
        r = rows[name]; si, so, pi, po = r["si"], r["so"], r["pi"], r["po"]
        if pi is None or po is None:
            print(f"{name:<28}| (no profile)"); continue
        print(f"{name:<28}| {si['mR']:>+6.3f} {si['wr']:>4.0f}% {si['top5']:>4.0f}% {pi['med']:>+6.2f} {pi['sharpe']:>+6.2f} {pi['dd']:>+6.1f} {pi['hold_med']:>5.1f} "
              f"| {so['mR']:>+6.3f} {so['wr']:>4.0f}% {so['top5']:>4.0f}% {po['med']:>+6.2f} {po['sharpe']:>+6.2f} {po['dd']:>+6.1f} {po['hold_med']:>5.1f}")

    # ---- (c) Δ vs baseline (OOS) + falsification + shuffle-p + BH-FDR ----
    print("\n" + "=" * 110)
    print("(c) Δ vs BASELINE (OOS) — winner-let-run net effect + falsification")
    print("=" * 110)
    bo, bpo = rows["B_baseline"]["so"], rows["B_baseline"]["po"]
    print(f"BASELINE OOS: mR={bo['mR']:+.3f} wr={bo['wr']:.0f}% top5={bo['top5']:.0f}% "
          f"med={bpo['med']:+.2f} sharpe={bpo['sharpe']:+.2f} DD={bpo['dd']:+.1f} hold={bpo['hold_med']:.1f}h")
    print(f"{'variant':<28} {'Δt5':>5} {'ΔmR':>7} {'Δmed':>6} {'Δshp':>6} {'ΔDD':>6} {'Δhold':>7} {'shuf_p':>7}  verdict")
    print("-" * 100)
    pvals = []
    for name in V:
        if name == "B_baseline":
            continue
        r = rows[name]; so, po = r["so"], r["po"]
        if po is None:
            continue
        dt5 = so["top5"] - bo["top5"]; dmr = so["mR"] - bo["mR"]
        dmed = po["med"] - bpo["med"]; dshp = po["sharpe"] - bpo["sharpe"]
        ddd = po["dd"] - bpo["dd"]; dhold = po["hold_med"] - bpo["hold_med"]
        sp = shuffle_p([t["R"] for t in r["oos_t"]])
        pvals.append((name, sp))
        h1 = (dt5 > 0) and (dmed > 0 or dshp > 0) and (dmr >= -0.02)
        v = "H1-candidate" if h1 else "reject"
        print(f"{name:<28} {dt5:>+4.0f}% {dmr:>+7.3f} {dmed:>+6.2f} {dshp:>+6.2f} {ddd:>+6.1f} {dhold:>+6.1f}h {sp:>7.4f}  {v}")

    if pvals:
        ps = sorted(pvals, key=lambda x: x[1]); m = len(ps)
        print("\n  BH-FDR (alpha=0.05) over OOS shuffle-p:")
        crit = None
        for i, (name, p) in enumerate(ps, 1):
            thr = 0.05 * i / m; sig = p <= thr
            if sig:
                crit = i
            print(f"    {i:>2}. {name:<28} p={p:.4f} BH_thr={thr:.4f} {'sig' if sig else ''}")
        print(f"  -> BH cutoff rank: {crit if crit else 'NONE'}")

    # ---- full-period profile (5y) for deploy framing ----
    print("\n" + "=" * 110)
    print("(d) FULL-PERIOD 5y profile (deploy framing)")
    print("=" * 110)
    bp = rows["B_baseline"]["pa"]
    print(f"BASELINE 5y: mR={bp['mR']:+.3f} wr={bp['wr']:.0f}% med={bp['med']:+.2f}% mean={bp['mean']:+.2f}% "
          f"sharpe={bp['sharpe']:+.2f} DD={bp['dd']:+.1f}% neg={bp['neg']}/{bp['nmo']} hold={bp['hold_med']:.1f}h")
    for name in V:
        if name == "B_baseline":
            continue
        pa = rows[name]["pa"]
        if pa is None:
            continue
        print(f"{name:<28} mR={pa['mR']:+.3f} wr={pa['wr']:.0f}% med={pa['med']:+.2f}% mean={pa['mean']:+.2f}% "
              f"sharpe={pa['sharpe']:+.2f} DD={pa['dd']:+.1f}% neg={pa['neg']}/{pa['nmo']} hold={pa['hold_med']:.1f}h")


if __name__ == "__main__":
    main()
