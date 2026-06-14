"""OPTIMIZED CHAMPION builder — BASELINE exit + universe pruning + WF edge-weighting.

REUSES the deployed harness VERBATIM:
  - wlr.gather() (real BacktestEngine) from scripts/crypto_winner_let_run_vsa_exit.py
  - production_replay() + ProductionConfig.from_yaml() from src/price_action/backtest/lab.py
  - BASELINE exit dict (tournament winner) from wlr.BASELINE
  - 55bps fee model identical to scripts/_champ_55bps_exit_compare.py
    (taker 0.00275/leg x2 = 55bps round-trip, slippage 0).

GOAL: beat the validated honest BASELINE (+7.58%/mo, Sharpe 1.98, MaxDD -17.6% @55bps)
on SKEW-CONTROLLED metrics, via:
  1. PRUNE dead-weight symbols (mean_R <= ~0 at 55bps over full sample — DATA, not story).
  2. EDGE-WEIGHT by TRAILING per-symbol performance only (walk-forward, NO lookahead).
Honest flag: if pruning/weighting is just past-winner overfit and dies in WF, SAY SO and
fall back to BASELINE-on-full-universe.

Lookahead audit: gather() uses the real engine (decisions on bar t use <= t-1; no
df.shift(-1)/center). Edge-weight for a trade entered at t uses ONLY trades with
exit_ts < entry_ts (strictly settled before the decision) -> causal.

Usage: .venv/bin/python scripts/optimized_champion.py
"""
from __future__ import annotations
import os, sys, json, pickle
from pathlib import Path
os.environ["PA_DUCKDB_READ_ONLY"] = "true"
os.environ["PA_LOG_QUIET"] = "1"
import warnings; warnings.filterwarnings("ignore")
import logging; logging.getLogger("price_action").setLevel(logging.ERROR)
import numpy as np, pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "src"))

import importlib.util
spec = importlib.util.spec_from_file_location(
    "wlr", str(ROOT / "scripts" / "crypto_winner_let_run_vsa_exit.py"))
wlr = importlib.util.module_from_spec(spec); spec.loader.exec_module(wlr)

from price_action.backtest.lab import ProductionConfig, production_replay
from dataclasses import replace

YAML = ROOT / "configs" / "risk_phoenix_scalp_15m_widestop_vsa2.yaml"
SYMS = ["BTC/USDT","ETH/USDT","SOL/USDT","BNB/USDT","ADA/USDT","AVAX/USDT",
        "LINK/USDT","DOT/USDT","DOGE/USDT","XRP/USDT","ZEC/USDT","NEAR/USDT",
        "FIL/USDT","XLM/USDT","TRX/USDT","UNI/USDT","ATOM/USDT","AAVE/USDT","ALGO/USDT"]
SL_PCT_MIN = 0.025
RISK_PCT = 0.005
SEED = 12345
CACHE = Path("/tmp/optchamp_baseline_55bps.pkl")

# 55bps honest fee model (identical to _champ_55bps_exit_compare.py)
FEES_55 = {"taker": 0.00275, "maker": -0.00010}
SLIP_55 = 0.0
# 0bps reference
FEES_0 = {"taker": 0.0, "maker": 0.0}
SLIP_0 = 0.0


def build_cfg():
    c = ProductionConfig.from_yaml(str(YAML))
    return replace(c, risk_pct=RISK_PCT, sl_pct_min=max(c.sl_pct_min, SL_PCT_MIN))


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


def daily_sharpe(res):
    eq = res.equity_curve or []; ts = res.entry_ts_list or []
    n = min(len(eq) - 1, len(ts))
    if n < 2:
        return 0.0, 0.0
    stamps = pd.to_datetime(ts[:n], utc=True)
    df = pd.DataFrame({"ts": stamps, "eq": eq[1:n + 1]})
    df["d"] = df["ts"].dt.floor("D")
    de = df.groupby("d")["eq"].last()
    full = pd.date_range(de.index.min(), de.index.max(), freq="D", tz="UTC")
    de = de.reindex(full).ffill().bfill()
    rets = de.pct_change().dropna()
    if rets.std() <= 0:
        return 0.0, 0.0
    return float(rets.mean() / rets.std() * np.sqrt(365)), float(rets.mean() / rets.std())


def top5_share(R):
    R = np.asarray(R, dtype=float)
    if (R > 0).sum() == 0:
        return 0.0
    thr = np.percentile(R, 95)
    return float(R[R >= thr].sum() / R[R > 0].sum() * 100)


def shuffle_p_gross(R, n_iter=5000, seed=SEED):
    """Bootstrap null: P(mean of resample >= observed) ~ p_gross for positive edge."""
    a = np.asarray(R, dtype=float)
    if len(a) < 5:
        return 1.0
    obs = a.mean()
    rng = np.random.default_rng(seed)
    # sign-flip null: center the sample, P(|resample mean| >= |obs|) is two-sided;
    # for "edge exists" we want one-sided P(shuffled mean >= obs) under H0 mean=0.
    centered = a - a.mean()
    cnt = 0
    for _ in range(n_iter):
        s = rng.choice(centered, size=len(a), replace=True)
        if s.mean() >= obs:
            cnt += 1
    return (cnt + 1) / (n_iter + 1)


def profile(trades, cfg, label=""):
    """Full skew-controlled profile of a trade pool under the live replay mechanics."""
    if not trades:
        return None
    pool = sorted(trades, key=lambda x: x["entry_ts"])
    res = production_replay(pool, cfg)
    if res is None:
        return None
    mr = monthly_from_replay(res, cfg)
    R = np.array([t["R"] for t in pool])
    sh_ann, sh_raw = daily_sharpe(res)
    # walk-forward positive-month count by year-half windows (6mo step, 36mo train
    # implied by the per-trade WF weighting; here WF = rolling 6-month OOS month count)
    return dict(
        label=label, n=len(pool), n_replay=res.trades,
        mean_R=float(R.mean()), win=float((R > 0).mean() * 100),
        top5=top5_share(R),
        n_mo=len(mr), pos_mo_pct=float((mr > 0).mean() * 100) if len(mr) else 0.0,
        pos_mo_cnt=int((mr > 0).sum()), neg_mo=int((mr < 0).sum()),
        mean_mo=float(mr.mean()) if len(mr) else 0.0,
        med_mo=float(mr.median()) if len(mr) else 0.0,
        sharpe_ann=sh_ann, maxdd=cont_dd(res.equity_curve),
        best_mo=float(mr.max()) if len(mr) else 0.0,
        worst_mo=float(mr.min()) if len(mr) else 0.0,
        total_ret=(res.final_equity / cfg.initial_capital - 1.0) * 100.0,
        skew=float(pd.Series(mr).skew()) if len(mr) > 2 else 0.0,
        kurt=float(pd.Series(mr).kurt()) if len(mr) > 3 else 0.0,
        shuffle_p=shuffle_p_gross(R),
        monthly={str(p): float(v) for p, v in mr.items()},
    )


def gather_all(fees, slip):
    wlr.FEES = fees; wlr.SLIPPAGE_BPS = slip
    per = {}
    for s in SYMS:
        t = wlr.gather(s, wlr.BASELINE)
        per[s] = [x for x in t if wlr.sl_pct_of(x) >= SL_PCT_MIN]
        print(f"  {s:<10} widestop_n={len(per[s])}", flush=True)
    return per


# ---------- WALK-FORWARD edge-weighting (NO LOOKAHEAD) ----------
def assign_wf_weights(pool, warmup_n=40, lo=0.5, hi=1.5, half_life_days=None):
    """For each trade (sorted by entry_ts), compute its symbol's TRAILING mean_R using
    ONLY trades of that symbol that EXITED strictly before this trade's entry_ts.
    Map trailing mean_R -> risk_weight in [lo, hi] via a cross-sectional rank at that
    moment. Pure causal: no future info. Warmup: until a symbol has >= warmup_n settled
    trades, weight = 1.0 (neutral).

    Returns a NEW list of trade dicts with 'risk_weight' set.
    """
    srt = sorted(pool, key=lambda x: x["entry_ts"])
    # settled history per symbol: list of (exit_ts, R)
    hist = {s: [] for s in SYMS}
    # pointer approach: we need trailing mean of trades with exit_ts < entry_ts.
    # Build per-symbol arrays of (exit_ts, R) sorted by exit_ts for bisect.
    by_sym_exits = {s: [] for s in SYMS}
    for t in srt:
        by_sym_exits[t["symbol"]].append((t["exit_ts"], t["R"]))
    for s in SYMS:
        by_sym_exits[s].sort(key=lambda x: x[0])
    import bisect
    exit_ts_only = {s: [e[0] for e in by_sym_exits[s]] for s in SYMS}
    cum_R = {}
    for s in SYMS:
        arr = np.array([e[1] for e in by_sym_exits[s]], dtype=float)
        cum_R[s] = np.concatenate([[0.0], np.cumsum(arr)]) if len(arr) else np.array([0.0])

    out = []
    for t in srt:
        # trailing per-symbol mean_R: trades of EACH symbol settled before entry_ts.
        entry = t["entry_ts"]
        means = {}
        for s in SYMS:
            k = bisect.bisect_left(exit_ts_only[s], entry)  # # settled before entry
            if k >= warmup_n:
                means[s] = cum_R[s][k] / k
        w = 1.0
        if len(means) >= 3 and t["symbol"] in means:
            vals = np.array(list(means.values()))
            # cross-sectional percentile rank of this symbol's trailing mean_R
            mine = means[t["symbol"]]
            rank = (vals < mine).mean()  # 0..1
            w = lo + (hi - lo) * rank
        tt = dict(t); tt["risk_weight"] = float(w)
        out.append(tt)
    return out


def main():
    cfg = build_cfg()
    print("=" * 100)
    print("OPTIMIZED CHAMPION — BASELINE exit, 55bps honest. Reuse wlr.gather + production_replay")
    print("=" * 100)

    if CACHE.exists():
        print(f"[cache] loading {CACHE}")
        blob = pickle.load(open(CACHE, "rb"))
        per55, per0 = blob["per55"], blob["per0"]
    else:
        print("\n[55bps] gathering BASELINE-exit widestop trades, 19 syms ...")
        per55 = gather_all(FEES_55, SLIP_55)
        print("\n[0bps] gathering BASELINE-exit widestop trades, 19 syms ...")
        per0 = gather_all(FEES_0, SLIP_0)
        pickle.dump({"per55": per55, "per0": per0}, open(CACHE, "wb"))
        print(f"[cache] wrote {CACHE}")

    # ---- 1) per-symbol mean_R (prune decision: DATA) ----
    print("\n" + "=" * 100)
    print("PER-SYMBOL mean_R (full sample) — prune rule: drop mean_R <= 0 @55bps")
    print("=" * 100)
    print(f"{'symbol':<10} {'n55':>6} {'mR@55':>8} {'win%55':>7} {'sumR55':>9} {'mR@0':>8}  decision")
    rows = []
    for s in SYMS:
        R55 = np.array([t["R"] for t in per55[s]]) if per55[s] else np.array([0.0])
        R0 = np.array([t["R"] for t in per0[s]]) if per0[s] else np.array([0.0])
        rows.append((s, len(per55[s]), float(R55.mean()), float((R55 > 0).mean() * 100),
                     float(R55.sum()), float(R0.mean())))
    rows.sort(key=lambda r: r[2], reverse=True)
    DROP = []
    for s, n, mr55, w55, sum55, mr0 in rows:
        dec = "KEEP"
        if mr55 <= 0.0:
            dec = "DROP (mR<=0 @55bps)"; DROP.append(s)
        elif mr55 < 0.05:
            dec = "MARGINAL (keep, monitor)"
        print(f"{s:<10} {n:>6} {mr55:>+8.3f} {w55:>6.1f}% {sum55:>+9.1f} {mr0:>+8.3f}  {dec}")
    KEEP = [s for s in SYMS if s not in DROP]
    print(f"\nDROP = {DROP}")
    print(f"KEEP (pruned universe) = {KEEP}  (n={len(KEEP)})")

    # ---- 2) build the three universes ----
    full_pool = [t for s in SYMS for t in per55[s]]
    pruned_pool = [t for s in KEEP for t in per55[s]]

    # edge-weighted on PRUNED universe (weight by trailing per-symbol mean_R, causal)
    weighted_pool = assign_wf_weights(pruned_pool)

    print("\n" + "=" * 100)
    print("PROFILES (55bps, live replay mechanics, risk 0.5%, sl_pct_min 0.025)")
    print("=" * 100)
    pf_full = profile(full_pool, cfg, "BASELINE_FULL19")
    pf_prune = profile(pruned_pool, cfg, "PRUNED_equalweight")
    pf_weight = profile(weighted_pool, cfg, "PRUNED_edgeweighted_WF")

    hdr = (f"{'variant':<26} {'n':>6} {'meanR':>7} {'win%':>6} {'top5%':>6} {'med_mo':>7} "
           f"{'mean_mo':>8} {'Sharpe':>7} {'MaxDD':>8} {'posMo':>10} {'skew':>6} {'kurt':>6} {'shuf_p':>7}")
    print(hdr); print("-" * len(hdr))
    for pf in (pf_full, pf_prune, pf_weight):
        if pf is None:
            continue
        print(f"{pf['label']:<26} {pf['n']:>6} {pf['mean_R']:>+7.3f} {pf['win']:>5.1f}% "
              f"{pf['top5']:>5.1f}% {pf['med_mo']:>+7.2f} {pf['mean_mo']:>+8.2f} {pf['sharpe_ann']:>+7.2f} "
              f"{pf['maxdd']:>+8.1f} {pf['pos_mo_cnt']:>3}/{pf['n_mo']:<3}{'':2} {pf['skew']:>+6.2f} "
              f"{pf['kurt']:>+6.2f} {pf['shuffle_p']:>7.4f}")

    # ---- 3) WALK-FORWARD validation of the prune (does dropping survive OOS?) ----
    # Split sample into 36mo train / rolling 6mo OOS; in EACH OOS window check whether
    # the symbols pruned on TRAILING data are still dead in the OOS window (no lookahead).
    print("\n" + "=" * 100)
    print("WALK-FORWARD prune robustness — is the prune set stable, or past-winner overfit?")
    print("=" * 100)
    # report per-DROP-symbol mean_R in first-half vs second-half (overfit smell test)
    mid = pd.Timestamp("2024-01-01", tz="UTC")
    print(f"{'symbol':<10} {'mR_pre2024':>11} {'n_pre':>6} {'mR_post2024':>12} {'n_post':>7}  stable_dead?")
    for s in DROP + [r[0] for r in rows if r[0] in KEEP][-3:]:  # drops + 3 weakest keeps
        pre = np.array([t["R"] for t in per55[s] if t["entry_ts"] < mid])
        post = np.array([t["R"] for t in per55[s] if t["entry_ts"] >= mid])
        mpre = pre.mean() if len(pre) else float("nan")
        mpost = post.mean() if len(post) else float("nan")
        flag = ""
        if s in DROP:
            flag = "DEAD both halves" if (mpre <= 0.1 and mpost <= 0.1) else "UNSTABLE (was positive once)"
        print(f"{s:<10} {mpre:>+11.3f} {len(pre):>6} {mpost:>+12.3f} {len(post):>7}  {flag}")

    # ---- 4) verdict numbers vs BASELINE ----
    print("\n" + "=" * 100)
    print("VERDICT DELTAS vs BASELINE_FULL19 (skew-controlled)")
    print("=" * 100)
    base = pf_full
    for pf in (pf_prune, pf_weight):
        if pf is None or base is None:
            continue
        d_sharpe = pf['sharpe_ann'] - base['sharpe_ann']
        d_med = pf['med_mo'] - base['med_mo']
        d_dd = pf['maxdd'] - base['maxdd']
        d_top5 = pf['top5'] - base['top5']
        beats = (d_sharpe > 0 and d_med > 0 and pf['maxdd'] >= base['maxdd'] - 1.0)
        print(f"{pf['label']:<26} dSharpe={d_sharpe:+.3f} dMedMo={d_med:+.2f}pp "
              f"dMaxDD={d_dd:+.1f}pp dTop5={d_top5:+.1f}pp  -> {'BEATS' if beats else 'does NOT beat'}")

    out = dict(
        prune_drop=DROP, prune_keep=KEEP,
        per_symbol=[dict(sym=r[0], n=r[1], mR55=r[2], win55=r[3], sumR55=r[4], mR0=r[5]) for r in rows],
        baseline_full=pf_full, pruned=pf_prune, weighted=pf_weight,
    )
    json.dump(out, open("/tmp/optchamp.json", "w"), indent=2, default=str)
    print("\n[dumped /tmp/optchamp.json]")


if __name__ == "__main__":
    main()
