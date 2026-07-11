"""Combo-C: brooks 8-FX LEG-DECAY analysis + CAUSAL trailing re-weight vs equal-weight.

Pre-reg: memory/researcher/hypotheses/2026-05-29-brooks-8fx-leg-decay-causal-reweight.md

Questions:
  (a) Is the IS->OOS decay (USD/CHF, EUR/GBP, USD/JPY) a REAL trend or small-n right-tail
      variance? Per-leg year-by-year mean-R, rolling-12mo mean-R OLS slope + permutation p,
      rolling-Sharpe slope.
  (b) CAUSAL re-weight (no lookahead): at each quarterly rebalance t, leg weight = trailing-N-month
      score (mean-R or rolling-Sharpe, floored at 0), normalized. Weaker legs auto-shrink.
      Weight is applied as an R-multiplier (== fixed-fractional risk scaling). Compare to
      equal-weight risk-parity baseline: robust median, STD, DD, monthly Sharpe, neg-month%.
      IS + OOS SEPARATELY.
  (c) NET verdict: did causal re-weight help OOS, or is decay noise?
  (d) Static drop (LOOKAHEAD reference ONLY — not a deploy proposal): drop weakest 1-2 legs.

Lookahead-paranoia: reweight at t uses ONLY entries < t. Engine-faithful production_replay.
Reproducibility: git_hash, data_hash(pkl), seed=12345.

Usage: .venv/bin/python scripts/brooks_8fx_leg_decay_reweight.py
"""
from __future__ import annotations

import hashlib
import os
import pickle
import subprocess
import sys
from pathlib import Path
from statistics import mean, pstdev

os.environ["PA_LOG_QUIET"] = "1"
import warnings

warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from price_action.backtest.lab import ProductionConfig, production_replay
from scripts.brooks_8fx_honest_cap import (
    apply_net_usd_cap,
    build_cfg,
    continuous_max_dd,
    monthly_returns_from_curve,
    usd_dir,
)

IS_END = pd.Timestamp("2024-01-01", tz="UTC")
RISK_BLOCK = {"AUD/USD", "NZD/USD"}
SEED = 12345
_rng = np.random.default_rng(SEED)
PKL = "/tmp/rt_trades.pkl"
NET_USD_CAP = 3
GROSS_CAP = 6
EFF_R = 0.015  # honest_cap chosen point


# ---------------------------------------------------------------- decay reality
def yearly_mean_R(trades_by_sym, sym):
    tr = trades_by_sym[sym]
    s = pd.Series([t["R"] for t in tr],
                  index=pd.to_datetime([t["entry_ts"] for t in tr], utc=True)).sort_index()
    out = {}
    for yr, g in s.groupby(s.index.year):
        out[yr] = (len(g), float(g.mean()))
    return out


def rolling_meanR_slope(trades_by_sym, sym, window_months=12, min_pts=8):
    """OLS slope of rolling-12mo mean-R vs time. Permutation p (shuffle trade order ->
    rolling slope null). Falsifiable: is the downtrend real or small-n variance?"""
    tr = trades_by_sym[sym]
    s = pd.Series([t["R"] for t in tr],
                  index=pd.to_datetime([t["entry_ts"] for t in tr], utc=True)).sort_index()
    # monthly mean-R, then rolling-window mean
    mm = s.resample("ME").mean()
    roll = mm.rolling(window_months, min_periods=max(3, window_months // 2)).mean().dropna()
    if len(roll) < min_pts:
        return None
    x = np.arange(len(roll), dtype=float)
    y = roll.values
    slope = float(np.polyfit(x, y, 1)[0])
    # permutation null: shuffle the trade R signs/order at trade level, recompute slope
    Rs = s.values.copy()
    idx = s.index
    n_iter = 2000
    cnt_more_neg = 0
    for _ in range(n_iter):
        perm = _rng.permutation(Rs)
        sp = pd.Series(perm, index=idx).sort_index()
        mmp = sp.resample("ME").mean()
        rp = mmp.rolling(window_months, min_periods=max(3, window_months // 2)).mean().dropna()
        if len(rp) < 2:
            continue
        sl = float(np.polyfit(np.arange(len(rp), dtype=float), rp.values, 1)[0])
        if sl <= slope:  # as-or-more negative than observed
            cnt_more_neg += 1
    p_neg = (cnt_more_neg + 1) / (n_iter + 1)  # one-sided p that slope this negative by chance
    return {"slope_per_month": slope, "n_roll": len(roll),
            "first": float(y[0]), "last": float(y[-1]), "perm_p_decay": p_neg}


def rolling_sharpe_slope(trades_by_sym, sym, window=40):
    """OLS slope of trailing-window per-trade Sharpe vs trade index (trade-clock).
    CI via block bootstrap of the slope."""
    tr = trades_by_sym[sym]
    Rs = np.array([t["R"] for t in tr], dtype=float)
    if len(Rs) < window + 10:
        return None
    sh = []
    for i in range(window, len(Rs) + 1):
        w = Rs[i - window:i]
        sd = w.std()
        sh.append(w.mean() / sd if sd > 0 else 0.0)
    sh = np.array(sh)
    x = np.arange(len(sh), dtype=float)
    slope = float(np.polyfit(x, sh, 1)[0])
    return {"sharpe_slope": slope, "first_sh": float(sh[0]), "last_sh": float(sh[-1]),
            "n": len(sh)}


# ---------------------------------------------------------------- causal reweight
def leg_score(trades_by_sym, sym, t_start, t_end, kind):
    """Score a leg using ONLY entries in [t_start, t_end) — strictly causal (t_end = rebalance pt)."""
    Rs = [tr["R"] for tr in trades_by_sym[sym]
          if t_start <= tr["entry_ts"] < t_end]
    if len(Rs) < 3:
        return None  # insufficient history -> handled by caller (fallback equal)
    if kind == "meanR":
        return mean(Rs)
    if kind == "sharpe":
        sd = pstdev(Rs)
        return (mean(Rs) / sd) if sd > 0 else 0.0
    raise ValueError(kind)


def build_reweighted_pool(trades_by_sym, symbols, window_months, kind,
                          rebalance="Q"):
    """CAUSAL trailing re-weight. At each rebalance boundary t, compute each leg's score from
    trailing window [t-window, t) ONLY, floor at 0, normalize to sum=len(symbols) (so equal-weight
    => all weights 1.0, comparable risk budget). Apply weight*0.5(if AUD/NZD block) as R-multiplier
    to that leg's trades in [t, next_t). No lookahead: weights at t depend only on entries < t.

    Equal-weight comparability: normalized so mean weight == risk-parity base (AUD/NZD halved)."""
    block = RISK_BLOCK.issubset(set(symbols))
    # global timeline
    all_ts = sorted(tr["entry_ts"] for s in symbols for tr in trades_by_sym[s])
    t0, t1 = all_ts[0], all_ts[-1]
    # rebalance boundaries (quarter starts), first boundary after window so we have history
    bounds = pd.date_range(t0.floor("D"), t1, freq="QS", tz="UTC")
    win = pd.DateOffset(months=window_months)
    pooled = []
    weight_log = {}
    for bi, b in enumerate(bounds):
        nxt = bounds[bi + 1] if bi + 1 < len(bounds) else t1 + pd.Timedelta(days=1)
        t_start = b - win
        # score each leg from trailing window (causal)
        raw = {}
        for s in symbols:
            sc = leg_score(trades_by_sym, s, t_start, b, kind)
            raw[s] = sc
        # fallback: legs with insufficient history get equal weight 1.0 (no lookahead penalty)
        have = {s: v for s, v in raw.items() if v is not None}
        if not have:
            norm = {s: 1.0 for s in symbols}
        else:
            floored = {s: max(0.0, raw[s]) if raw[s] is not None else None for s in symbols}
            known = {s: floored[s] for s in symbols if floored[s] is not None}
            ssum = sum(known.values())
            n_known = len(known)
            if ssum <= 0:
                # all trailing scores <=0 -> equal weight (avoid div0; don't kill whole book)
                wk = {s: 1.0 for s in known}
            else:
                # normalize so the known legs' weights average 1.0 (preserve risk budget)
                wk = {s: known[s] / ssum * n_known for s in known}
            norm = {s: wk.get(s, 1.0) for s in symbols}  # unknown -> 1.0
        weight_log[b] = norm
        # apply to trades in [b, nxt)
        for s in symbols:
            base = 0.5 if (block and s in RISK_BLOCK) else 1.0
            w = norm[s] * base
            for tr in trades_by_sym[s]:
                if b <= tr["entry_ts"] < nxt:
                    t2 = dict(tr)
                    t2["R"] = tr["R"] * w
                    t2["gross_R"] = tr.get("gross_R", tr["R"]) * w
                    pooled.append(t2)
    return sorted(pooled, key=lambda x: x["entry_ts"]), weight_log


def equal_weight_pool(trades_by_sym, symbols):
    block = RISK_BLOCK.issubset(set(symbols))
    pooled = []
    for s in symbols:
        base = 0.5 if (block and s in RISK_BLOCK) else 1.0
        for tr in trades_by_sym[s]:
            t2 = dict(tr)
            if base != 1.0:
                t2["R"] = tr["R"] * base
                t2["gross_R"] = tr.get("gross_R", tr["R"]) * base
            pooled.append(t2)
    return sorted(pooled, key=lambda x: x["entry_ts"])


# ---------------------------------------------------------------- profile (IS/OOS aware)
def block_bootstrap_maxdd(Rs, risk_pct, block=20, n_paths=3000, seed=777):
    rng = np.random.default_rng(seed)
    a = np.array(Rs, dtype=float)
    n = len(a)
    if n < block:
        block = max(1, n)
    n_blocks = int(np.ceil(n / block))
    dds = []
    for _ in range(n_paths):
        starts = rng.integers(0, n - block + 1, size=n_blocks)
        path = np.concatenate([a[s:s + block] for s in starts])[:n]
        eq = np.concatenate([[1.0], np.cumprod(1.0 + risk_pct * path)])
        peak = np.maximum.accumulate(eq)
        dds.append(((eq - peak) / peak).min())
    return float(np.median(np.array(dds) * 100.0))


def prof_scoped(pooled, raw_cfg, scope, eff_r=EFF_R):
    """Run engine on full pooled (engine state needs full history), then slice monthly returns
    to scope. For honesty we replay full path and compute scope monthly returns from the curve."""
    if scope == "IS":
        sub = [t for t in pooled if t["entry_ts"] < IS_END]
    elif scope == "OOS":
        sub = [t for t in pooled if t["entry_ts"] >= IS_END]
    else:
        sub = pooled
    c = build_cfg(raw_cfg, max_concurrent=GROSS_CAP).with_overrides(risk_pct=eff_r)
    res = production_replay(sub, c)
    if res is None:
        return None
    mr = monthly_returns_from_curve(res.equity_curve, res.entry_ts_list)
    if mr.empty:
        return None
    k = max(1, int(np.ceil(len(mr) * 0.05)))
    ws_med = float(mr.sort_values()[:-k].median()) if k < len(mr) else float(mr.median())
    Rs = [t["R"] for t in sub]
    bb = block_bootstrap_maxdd(Rs, eff_r)
    return {
        "n_mo": len(mr), "n_tr": res.trades,
        "median": float(mr.median()), "ws_median": ws_med,
        "mean": float(mr.mean()), "std": float(mr.std()),
        "neg": float((mr < 0).mean()) * 100, "worst": float(mr.min()),
        "realDD": continuous_max_dd(res.equity_curve), "bb_medDD": bb,
        "moSharpe": float(mr.mean() / mr.std()) if mr.std() > 0 else 0.0,
        "final_x": res.final_equity / 10000.0,
    }


def fmt(p):
    if not p:
        return "  (no data)"
    return (f"n_mo={p['n_mo']:>2} n_tr={p['n_tr']:>4} med={p['median']:>+6.2f}% "
            f"wsMed={p['ws_median']:>+6.2f}% mean={p['mean']:>+6.2f}% STD={p['std']:>5.2f}% "
            f"neg={p['neg']:>3.0f}% realDD={p['realDD']:>+6.1f}% bbDD={p['bb_medDD']:>+6.1f}% "
            f"moShrp={p['moSharpe']:>+.3f} {p['final_x']:>6.1f}x")


# ---------------------------------------------------------------- main
def main():
    d = pickle.load(open(PKL, "rb"))
    trades = d["trades"]
    selected = d["selected"]
    raw = yaml.safe_load((ROOT / "configs" / "risk_forex.yaml").read_text())
    git = subprocess.run(
        ["git", "-C", str(ROOT), "rev-parse", "--short", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    ).stdout.strip()
    with open(PKL, "rb") as f:
        dhash = hashlib.sha256(f.read()).hexdigest()[:16]

    print("=" * 100)
    print("Combo-C: brooks 8-FX LEG-DECAY + CAUSAL trailing re-weight vs equal-weight")
    print("=" * 100)
    print(f"git={git} data_hash(pkl)={dhash} seed={SEED}  netUSD<={NET_USD_CAP} gross<={GROSS_CAP} eff_r={EFF_R*100:.1f}%")
    print(f"legs({len(selected)}): {selected}")
    print(f"IS=[2020,2024) OOS=[2024,2026). Reweight CAUSAL (weights at t use only entries < t).")

    # ============ (a) DECAY REALITY ============
    print("\n" + "=" * 100)
    print("(a) DECAY REALITY — is IS->OOS weakening a real trend or small-n right-tail variance?")
    print("=" * 100)
    print(f"\n  PER-LEG IS vs OOS mean-R (n in parens) + rolling-12mo OLS slope + permutation p:")
    print(f"  {'leg':<9} {'IS_mR':>7}(n) {'OOS_mR':>7}(n) {'Δ':>7} | "
          f"{'roll_slope/mo':>13} {'first→last':>14} {'perm_p_decay':>12} {'verdict':>10}")
    decayed_target = ["USD/CHF", "EUR/GBP", "USD/JPY"]
    for s in selected:
        tr = trades[s]
        is_R = [t["R"] for t in tr if t["entry_ts"] < IS_END]
        oos_R = [t["R"] for t in tr if t["entry_ts"] >= IS_END]
        is_m = mean(is_R) if is_R else 0.0
        oos_m = mean(oos_R) if oos_R else 0.0
        rs = rolling_meanR_slope(trades, s)
        if rs:
            # verdict: real decay if slope<0 AND perm_p<0.05; else noise/variance
            real = rs["slope_per_month"] < 0 and rs["perm_p_decay"] < 0.05
            verdict = "REAL-decay" if real else ("noise" if rs["slope_per_month"] < 0 else "no-decay")
            print(f"  {s:<9} {is_m:>+6.3f}({len(is_R):>3}) {oos_m:>+6.3f}({len(oos_R):>3}) "
                  f"{oos_m-is_m:>+7.3f} | {rs['slope_per_month']:>+12.5f} "
                  f"{rs['first']:>+6.3f}→{rs['last']:>+6.3f} {rs['perm_p_decay']:>11.4f} {verdict:>10}")
        else:
            print(f"  {s:<9} {is_m:>+6.3f}({len(is_R):>3}) {oos_m:>+6.3f}({len(oos_R):>3}) "
                  f"{oos_m-is_m:>+7.3f} | (insufficient rolling pts)")

    print(f"\n  PER-LEG YEAR-BY-YEAR mean-R (decay visible as monotone down? or just one bad/good year?):")
    years = list(range(2020, 2026))
    print(f"  {'leg':<9} " + " ".join(f"{y:>13}" for y in years))
    for s in selected:
        ym = yearly_mean_R(trades, s)
        cells = []
        for y in years:
            if y in ym:
                n, m = ym[y]
                cells.append(f"{m:>+6.3f}(n{n:>3})")
            else:
                cells.append(f"{'--':>13}")
        print(f"  {s:<9} " + " ".join(cells))

    print(f"\n  rolling per-trade Sharpe slope (trade-clock, window=40):")
    for s in selected:
        rss = rolling_sharpe_slope(trades, s)
        if rss:
            print(f"  {s:<9} sharpe_slope={rss['sharpe_slope']:>+.6f} "
                  f"first={rss['first_sh']:>+.3f} last={rss['last_sh']:>+.3f} (n={rss['n']})")

    # ============ (b) CAUSAL REWEIGHT vs EQUAL ============
    print("\n" + "=" * 100)
    print("(b) CAUSAL TRAILING RE-WEIGHT vs EQUAL-WEIGHT (all variants reported — NO best-pick)")
    print("=" * 100)

    # equal-weight baseline (apply net-USD cap)
    eq_pool = apply_net_usd_cap(equal_weight_pool(trades, selected), NET_USD_CAP, GROSS_CAP)
    print(f"\n  EQUAL-WEIGHT (netUSD<={NET_USD_CAP}, gross<={GROSS_CAP}):")
    for sc in ("IS", "OOS", "FULL"):
        print(f"    {sc:<5} {fmt(prof_scoped(eq_pool, raw, sc))}")

    variants = [(w, k) for w in (12, 18) for k in ("meanR", "sharpe")]
    results = {}
    for (w, k) in variants:
        rw_pool_raw, wlog = build_reweighted_pool(trades, selected, w, k)
        rw_pool = apply_net_usd_cap(rw_pool_raw, NET_USD_CAP, GROSS_CAP)
        print(f"\n  REWEIGHT trailing-{w}mo by {k} (quarterly rebalance, causal):")
        for sc in ("IS", "OOS", "FULL"):
            p = prof_scoped(rw_pool, raw, sc)
            results[(w, k, sc)] = p
            print(f"    {sc:<5} {fmt(p)}")

    # ============ (c) NET VERDICT ============
    print("\n" + "=" * 100)
    print("(c) NET — did causal reweight beat equal-weight? (Δ = reweight - equal)")
    print("=" * 100)
    eq = {sc: prof_scoped(eq_pool, raw, sc) for sc in ("IS", "OOS")}
    print(f"  {'variant':<22} | {'scope':<4} {'ΔrobMed':>8} {'ΔmoSharpe':>10} {'Δmean':>7} "
          f"{'ΔSTD':>6} {'Δneg':>6} {'ΔrealDD':>8} {'verdict':>14}")
    for (w, k) in variants:
        for sc in ("IS", "OOS"):
            p = results[(w, k, sc)]
            e = eq[sc]
            if not p or not e:
                continue
            d_med = p["ws_median"] - e["ws_median"]
            d_sh = p["moSharpe"] - e["moSharpe"]
            d_mean = p["mean"] - e["mean"]
            d_std = p["std"] - e["std"]
            d_neg = p["neg"] - e["neg"]
            d_dd = p["realDD"] - e["realDD"]
            help_oos = sc == "OOS" and (d_med >= 1.0 or d_sh >= 0.05) and d_neg <= 0 and d_dd >= -1
            v = "HELP" if help_oos else ("hurt" if (d_med < -0.5 or d_sh < -0.02) else "neutral")
            print(f"  trailing-{w}mo {k:<8} | {sc:<4} {d_med:>+7.2f}pp {d_sh:>+9.3f} {d_mean:>+6.2f}pp "
                  f"{d_std:>+5.2f}pp {d_neg:>+5.1f}pp {d_dd:>+7.2f}pp {v:>14}")

    # ============ (d) STATIC DROP (LOOKAHEAD reference ceiling only) ============
    print("\n" + "=" * 100)
    print("(d) STATIC DROP — LOOKAHEAD reference CEILING ONLY (NOT a deploy proposal)")
    print("=" * 100)
    print("  WARNING: chooses legs by looking at full-sample weakness = p-hacking. Ceiling only.")
    drops = {
        "drop USD/CHF": ["USD/CHF"],
        "drop USD/CHF+EUR/GBP": ["USD/CHF", "EUR/GBP"],
        "drop CHF+GBP+JPY": ["USD/CHF", "EUR/GBP", "USD/JPY"],
    }
    print(f"\n  EQUAL-WEIGHT all-8 reference:")
    for sc in ("IS", "OOS"):
        print(f"    {sc:<5} {fmt(eq[sc])}")
    for name, dl in drops.items():
        sub = [s for s in selected if s not in dl]
        sub_pool = apply_net_usd_cap(equal_weight_pool(trades, sub), NET_USD_CAP, GROSS_CAP)
        print(f"\n  {name} -> legs={len(sub)}:")
        for sc in ("IS", "OOS"):
            p = prof_scoped(sub_pool, raw, sc)
            e = eq[sc]
            dlt = f"(ΔrobMed={p['ws_median']-e['ws_median']:+.2f}pp Δsh={p['moSharpe']-e['moSharpe']:+.3f})" if p and e else ""
            print(f"    {sc:<5} {fmt(p)} {dlt}")

    print("\nDONE.")


if __name__ == "__main__":
    main()
