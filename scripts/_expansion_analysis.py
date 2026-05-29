"""10 vs 15 symbol expansion analysis for vsa_climax_test wide-stop (deployed cfg).

Methodology (per task brief, anti-inflation):
  - Single CONTINUOUS compounding equity curve replay (NOT per-month-reset).
  - Monthly ROI = month-end-equity / month-start-equity - 1, bucketed from the
    one continuous curve via processed-trade exit_ts.
  - Realized MaxDD from the continuous curve.
  - Block-bootstrap tail (monthly-block, NOT iid MC) for DD/return distribution.
  - Correlation matrix + N_eff on per-symbol monthly R-sum returns.
  - Common-mode: simultaneous-entry same-side fraction.
  - Leave-one-out value for each of the 5 new symbols.

Reads pre-built pools (no DB access here). Live daemons untouched.
"""
from __future__ import annotations

import os
import pickle
import sys
from collections import defaultdict
from datetime import timedelta
from pathlib import Path
from statistics import mean, median, stdev

os.environ["PA_LOG_QUIET"] = "1"
import warnings
warnings.filterwarnings("ignore")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

import numpy as np
import pandas as pd

from price_action.backtest.lab import ProductionConfig, production_replay

YAML = ROOT / "configs" / "risk_phoenix_scalp_15m_widestop_vsa2.yaml"
POOL_15 = ROOT / "data" / "_vsa_pool_15sym_fresh.pkl"

SYMS_10 = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "ADA/USDT",
           "AVAX/USDT", "LINK/USDT", "DOT/USDT", "DOGE/USDT", "XRP/USDT"]
NEW_SYMS = ["ZEC/USDT", "SUI/USDT", "NEAR/USDT", "FIL/USDT", "XLM/USDT"]

RNG = np.random.default_rng(20260529)


def month_key(ts):
    return (ts.year, ts.month)


def continuous_monthly(r):
    """Bucket the single continuous equity curve into per-month ROI.

    r.equity_curve has len = n_processed + 1 (eq_curve[0]=initial).
    r.entry_ts_list = exit_ts of each processed trade (aligned to eq_curve[1:]).
    Monthly ROI = (equity at last trade of month) vs (equity at last trade of
    prev month) -> month-over-month compounding ratio off the SAME curve.
    """
    eq = r.equity_curve
    ts = r.entry_ts_list
    if not eq or not ts or len(eq) < 2:
        return []
    # eq[i+1] is equity AFTER processing trade i (exit ts = ts[i])
    # Build series of (month, end_equity_of_month)
    month_end_eq = {}
    months_order = []
    for i, t in enumerate(ts):
        mk = month_key(pd.Timestamp(t))
        if mk not in month_end_eq:
            months_order.append(mk)
        month_end_eq[mk] = eq[i + 1]  # last write per month = month-end equity
    rois = []
    prev_eq = eq[0]
    for mk in months_order:
        e = month_end_eq[mk]
        roi = e / prev_eq - 1.0 if prev_eq > 0 else 0.0
        rois.append((mk, roi))
        prev_eq = e
    return rois


def realized_maxdd(r):
    eq = r.equity_curve
    peak = eq[0]
    mdd = 0.0
    for v in eq:
        peak = max(peak, v)
        dd = (v - peak) / peak if peak > 0 else 0.0
        mdd = min(mdd, dd)
    return mdd


def block_bootstrap_dd(monthly_rois, n_boot=2000, block=3):
    """Block-bootstrap: resample 3-month blocks of monthly ROI, rebuild
    compounding curve, record terminal return and path MaxDD. NOT iid MC."""
    rois = [r for _, r in monthly_rois]
    n = len(rois)
    if n < block + 1:
        return None
    n_blocks = int(np.ceil(n / block))
    term_rets, mdds = [], []
    for _ in range(n_boot):
        seq = []
        for _b in range(n_blocks):
            start = RNG.integers(0, n - block + 1)
            seq.extend(rois[start:start + block])
        seq = seq[:n]
        eq = [1.0]
        for m in seq:
            eq.append(eq[-1] * (1.0 + m))
        # path MaxDD
        peak = eq[0]; mdd = 0.0
        for v in eq:
            peak = max(peak, v); mdd = min(mdd, (v - peak) / peak)
        term_rets.append(eq[-1] - 1.0)
        mdds.append(mdd)
    term_rets = np.array(term_rets); mdds = np.array(mdds)
    return {
        "dd_p50": float(np.percentile(mdds, 50)),
        "dd_p95": float(np.percentile(mdds, 5)),   # worst 5% (most negative)
        "dd_p99": float(np.percentile(mdds, 1)),
        "ret_p05": float(np.percentile(term_rets, 5)),
        "ret_p50": float(np.percentile(term_rets, 50)),
    }


def monthly_symbol_returns(trades):
    """Per-symbol per-month sum-R (proxy return) matrix for corr / N_eff."""
    bym = defaultdict(lambda: defaultdict(float))
    syms = set()
    for t in trades:
        mk = month_key(t["entry_ts"])
        bym[mk][t["symbol"]] += t["R"]
        syms.add(t["symbol"])
    syms = sorted(syms)
    months = sorted(bym.keys())
    mat = np.array([[bym[m].get(s, 0.0) for s in syms] for m in months])
    return syms, months, mat


def corr_and_neff(mat, syms):
    # drop all-zero columns (symbol with no trades in window)
    keep = [i for i in range(mat.shape[1]) if np.std(mat[:, i]) > 1e-9]
    sub = mat[:, keep]
    ksyms = [syms[i] for i in keep]
    if sub.shape[1] < 2:
        return None, None, 1.0
    C = np.corrcoef(sub.T)
    # mean off-diagonal pairwise corr
    iu = np.triu_indices_from(C, k=1)
    mean_corr = float(np.mean(C[iu]))
    # N_eff via eigenvalues: (sum lambda)^2 / sum(lambda^2)
    ev = np.linalg.eigvalsh(C)
    ev = ev[ev > 0]
    neff = float((ev.sum() ** 2) / (ev ** 2).sum())
    return C, ksyms, neff, mean_corr


def common_mode_same_side(trades, window_min=15):
    """For each entry, count co-entries within +/- window that are same side.
    Returns fraction of co-occurring entry-pairs that are same-side."""
    ev = sorted(trades, key=lambda t: t["entry_ts"])
    same = 0; tot = 0
    j0 = 0
    for i, t in enumerate(ev):
        ti = t["entry_ts"]
        lo = ti - timedelta(minutes=window_min)
        hi = ti + timedelta(minutes=window_min)
        for k in range(i + 1, len(ev)):
            if ev[k]["entry_ts"] > hi:
                break
            tot += 1
            if str(ev[k]["side"]).lower() == str(t["side"]).lower():
                same += 1
    return (same / tot if tot else 0.0), tot


def run_replay(trades, cfg):
    return production_replay(sorted(trades, key=lambda x: x["entry_ts"]), cfg)


def summarize(label, trades, cfg, do_boot=True):
    r = run_replay(trades, cfg)
    if r is None:
        print(f"  [{label}] replay None")
        return None
    rois = continuous_monthly(r)
    roi_vals = [x for _, x in rois]
    span_days = (max(t["exit_ts"] for t in trades) - min(t["entry_ts"] for t in trades)).days
    years = span_days / 365.25
    out = {
        "label": label,
        "n_raw": len(trades),
        "n_exec": r.trades,
        "wr": r.win_rate,
        "mean_R": r.avg_r,
        "final_eq": r.final_equity,
        "total_ret": r.total_return,
        "ann": r.annualized(years),
        "realized_maxdd": realized_maxdd(r),
        "monthly_median": median(roi_vals) if roi_vals else 0.0,
        "monthly_mean": mean(roi_vals) if roi_vals else 0.0,
        "monthly_std": stdev(roi_vals) if len(roi_vals) > 1 else 0.0,
        "n_months": len(roi_vals),
        "neg_months": sum(1 for x in roi_vals if x < 0),
        "worst_month": min(roi_vals) if roi_vals else 0.0,
        "best_month": max(roi_vals) if roi_vals else 0.0,
        "rois": rois,
    }
    if do_boot:
        out["boot"] = block_bootstrap_dd(rois)
    return out


def main():
    cfg = ProductionConfig.from_yaml(str(YAML))
    pool = pickle.load(open(POOL_15, "rb"))
    pool = [t for t in pool if t["strategy"] == "vsa_climax_test"]
    pool_10 = [t for t in pool if t["symbol"] in SYMS_10]
    pool_15 = pool  # 10 + 5

    print(f"[POOL] 15-sym raw vsa: {len(pool_15)}  | 10-sym: {len(pool_10)}  | new-5: {len(pool_15)-len(pool_10)}")

    # ---- 10 vs 15 head-to-head ----
    s10 = summarize("10-sym", pool_10, cfg)
    s15 = summarize("15-sym", pool_15, cfg)

    print("\n=== 10 vs 15 (deployed cfg, 15bps round-trip, continuous compounding curve) ===")
    hdr = ["metric", "10-sym", "15-sym", "delta"]
    def fmt(v, pct=False):
        return f"{v*100:+.2f}%" if pct else f"{v}"
    rows = [
        ("n_raw signals", s10["n_raw"], s15["n_raw"], s15["n_raw"]-s10["n_raw"]),
        ("n executed", s10["n_exec"], s15["n_exec"], s15["n_exec"]-s10["n_exec"]),
        ("WR", f"{s10['wr']*100:.1f}%", f"{s15['wr']*100:.1f}%", f"{(s15['wr']-s10['wr'])*100:+.1f}pp"),
        ("mean_R", f"{s10['mean_R']:+.3f}", f"{s15['mean_R']:+.3f}", f"{s15['mean_R']-s10['mean_R']:+.3f}"),
        ("monthly MEDIAN", f"{s10['monthly_median']*100:+.2f}%", f"{s15['monthly_median']*100:+.2f}%", f"{(s15['monthly_median']-s10['monthly_median'])*100:+.2f}pp"),
        ("monthly mean", f"{s10['monthly_mean']*100:+.2f}%", f"{s15['monthly_mean']*100:+.2f}%", f"{(s15['monthly_mean']-s10['monthly_mean'])*100:+.2f}pp"),
        ("monthly std", f"{s10['monthly_std']*100:.2f}%", f"{s15['monthly_std']*100:.2f}%", "-"),
        ("neg months", f"{s10['neg_months']}/{s10['n_months']}", f"{s15['neg_months']}/{s15['n_months']}", "-"),
        ("worst month", f"{s10['worst_month']*100:+.2f}%", f"{s15['worst_month']*100:+.2f}%", "-"),
        ("realized MaxDD", f"{s10['realized_maxdd']*100:+.2f}%", f"{s15['realized_maxdd']*100:+.2f}%", f"{(s15['realized_maxdd']-s10['realized_maxdd'])*100:+.2f}pp"),
        ("annualized", f"{s10['ann']*100:+.1f}%", f"{s15['ann']*100:+.1f}%", "-"),
    ]
    print(f"{'metric':22s} {'10-sym':>14s} {'15-sym':>14s} {'delta':>12s}")
    for m, a, b, d in rows:
        print(f"{m:22s} {str(a):>14s} {str(b):>14s} {str(d):>12s}")

    for s in (s10, s15):
        b = s.get("boot")
        if b:
            print(f"\n[block-bootstrap {s['label']}] DD p50 {b['dd_p50']*100:+.1f}% / "
                  f"p95 {b['dd_p95']*100:+.1f}% / p99 {b['dd_p99']*100:+.1f}%  | "
                  f"term-ret p05 {b['ret_p05']*100:+.1f}% / p50 {b['ret_p50']*100:+.1f}%")

    # ---- correlation + N_eff ----
    print("\n=== Correlation / N_eff (per-symbol monthly sum-R) ===")
    for label, p in (("10-sym", pool_10), ("15-sym", pool_15)):
        syms, months, mat = monthly_symbol_returns(p)
        C, ksyms, neff, mc = corr_and_neff(mat, syms)
        print(f"  {label}: n_sym_active={len(ksyms)}  mean_pairwise_corr={mc:+.3f}  N_eff={neff:.2f}")

    # ---- common-mode same-side ----
    print("\n=== Common-mode (simultaneous same-side entries, +/-15min) ===")
    for label, p in (("10-sym", pool_10), ("15-sym", pool_15)):
        frac, tot = common_mode_same_side(p)
        print(f"  {label}: same-side fraction of co-entries = {frac*100:.1f}%  (n_pairs={tot})")

    # ---- leave-one-out for the 5 new symbols ----
    print("\n=== Leave-one-out: value of each NEW symbol (15-sym minus that symbol) ===")
    base = s15
    print(f"  FULL-15 baseline: median {base['monthly_median']*100:+.2f}%  "
          f"MaxDD {base['realized_maxdd']*100:+.2f}%  mean_R {base['mean_R']:+.3f}  "
          f"neg {base['neg_months']}/{base['n_months']}")
    print(f"  {'drop':10s} {'med ROI':>10s} {'d-med':>9s} {'MaxDD':>10s} {'d-DD':>9s} {'mean_R':>8s} {'neg':>7s} {'n_exec':>7s}")
    for sym in NEW_SYMS:
        sub = [t for t in pool_15 if t["symbol"] != sym]
        ss = summarize(f"drop-{sym}", sub, cfg, do_boot=False)
        dmed = (base["monthly_median"] - ss["monthly_median"]) * 100  # +ve => sym ADDS median
        ddd = (ss["realized_maxdd"] - base["realized_maxdd"]) * 100   # +ve => removing sym IMPROVES DD (sym hurt DD)
        print(f"  {sym:10s} {ss['monthly_median']*100:>+9.2f}% {dmed:>+8.2f} "
              f"{ss['realized_maxdd']*100:>+9.2f}% {ddd:>+8.2f} {ss['mean_R']:>+8.3f} "
              f"{ss['neg_months']:>3d}/{ss['n_months']:<3d} {ss['n_exec']:>7d}")
    print("\n  Reading: d-med >0 => symbol RAISES portfolio median (adds value).")
    print("           d-DD  >0 => removing symbol IMPROVES DD (symbol HURT DD).")

    # ---- per-new-symbol standalone edge ----
    print("\n=== New-symbol standalone pool stats (raw, sl_pct>=2.5% filter applied) ===")
    for sym in NEW_SYMS:
        ssub = [t for t in pool_15 if t["symbol"] == sym]
        # apply same sl_pct_min filter to count tradeable
        tradeable = [t for t in ssub if t["entry_price"] > 0 and
                     abs(t["initial_sl"]-t["entry_price"])/t["entry_price"] >= cfg.sl_pct_min]
        Rs = [t["R"] for t in tradeable]
        if Rs:
            wr = sum(1 for r in Rs if r > 0)/len(Rs)*100
            print(f"  {sym:10s} raw={len(ssub):>5d} tradeable={len(tradeable):>5d} "
                  f"meanR={mean(Rs):+.3f} sumR={sum(Rs):+.0f} WR={wr:.1f}% "
                  f"range={min(t['entry_ts'] for t in ssub).date()}->{max(t['entry_ts'] for t in ssub).date()}")

    # ---- +55bps taker sensitivity (worst-case) ----
    print("\n=== +55bps taker sensitivity (worst-case fee) ===")
    from dataclasses import replace
    cfg55 = replace(cfg, fee_bps_per_trade=55.0)
    for label, p in (("10-sym", pool_10), ("15-sym", pool_15)):
        ss = summarize(label, p, cfg55, do_boot=False)
        print(f"  {label}: median {ss['monthly_median']*100:+.2f}%  mean {ss['monthly_mean']*100:+.2f}%  "
              f"MaxDD {ss['realized_maxdd']*100:+.2f}%  mean_R {ss['mean_R']:+.3f}  "
              f"neg {ss['neg_months']}/{ss['n_months']}")


if __name__ == "__main__":
    main()
