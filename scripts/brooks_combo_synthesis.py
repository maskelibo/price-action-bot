"""Combo-SYNTHESIS: merge session winners into ONE honest config + full profile.

Winners merged:
  B (winner-let-run exit): wlr_variants_4h.pkl['V1a_trail3.0']  (trail 3.0, 30-bar time
     exit kept, real BacktestEngine — NO hand-coded exit).
  A (fixed-notional sizing): faithful_replay risk_d = $100 fixed (1% of 10k, no compound).
  C (leg-decay): REJECTED — equal-weight + netUSD<=3 already sufficient, no re-weight.

Pipeline (identical for every cell):
  trades_by_sym -> risk_parity (equal-weight; AUD/NZD 0.5 risk-block) -> apply_net_usd_cap(3,6)
  -> faithful_replay(mode) with mc=6.

Three-way compare:
  (i)   OLD baseline exit + COMPOUNDING        = the original illusion
  (ii)  OLD baseline exit + FIXED-NOTIONAL     = honest baseline
  (iii) NEW winner-let-run exit + FIXED-NOTIONAL = the merged candidate

Honesty: NO iid MC. realized contMaxDD + block-bootstrap(20) p05 DD only.
Backtest = hypothesis, not live fill.

Usage: .venv/bin/python scripts/brooks_combo_synthesis.py
"""
from __future__ import annotations
import os, sys, pickle
from pathlib import Path
os.environ["PA_LOG_QUIET"] = "1"
import warnings; warnings.filterwarnings("ignore")
import numpy as np, pandas as pd, yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "src"))

from scripts.brooks_8fx_honest_cap import (
    risk_parity_trades, apply_net_usd_cap, build_cfg,
    continuous_max_dd, block_bootstrap_maxdd,
)
from scripts.brooks_8fx_sizing_combo_a import faithful_replay, INIT

SYMBOLS_8 = ["EUR/USD", "GBP/USD", "USD/JPY", "AUD/USD", "USD/CHF", "EUR/GBP", "USD/CAD", "NZD/USD"]
NET_USD_CAP, GROSS_CAP = 3, 6
RISK_PCT = 0.01
IS_LO = pd.Timestamp("2020-01-01", tz="UTC")
IS_END = pd.Timestamp("2024-01-01", tz="UTC")
OOS_END = pd.Timestamp("2026-01-01", tz="UTC")


def split(trs, lo, hi):
    return [t for t in trs if lo <= pd.Timestamp(t["entry_ts"]) < hi]


def monthly_roi_from_ledger(led, start, end):
    """Realized monthly ROI% from a faithful_replay ledger, restricted to [start,end).
    ROI uses equity_after path (path-dependent, honest for fixed-notional too)."""
    if led.empty:
        return pd.Series(dtype=float)
    l = led.copy()
    l["exit_ts"] = pd.to_datetime(l["exit_ts"], utc=True)
    l = l[(l["exit_ts"] >= start) & (l["exit_ts"] < end)].sort_values("exit_ts")
    if l.empty:
        return pd.Series(dtype=float)
    eq = pd.Series(l["equity_after"].values, index=l["exit_ts"])
    me = eq.resample("ME").last().dropna()
    if me.empty:
        return pd.Series(dtype=float)
    # start-of-window equity = equity_after of last trade BEFORE window, else INIT
    before = led.copy(); before["exit_ts"] = pd.to_datetime(before["exit_ts"], utc=True)
    before = before[before["exit_ts"] < start].sort_values("exit_ts")
    start_eq = float(before["equity_after"].iloc[-1]) if len(before) else INIT
    prev = pd.Series([start_eq] + list(me.values[:-1]), index=me.index)
    return (me / prev - 1.0) * 100.0


def realized_maxdd_window(led, start, end):
    l = led.copy(); l["exit_ts"] = pd.to_datetime(l["exit_ts"], utc=True)
    l = l[(l["exit_ts"] >= start) & (l["exit_ts"] < end)].sort_values("exit_ts")
    if l.empty:
        return 0.0
    before = led.copy(); before["exit_ts"] = pd.to_datetime(before["exit_ts"], utc=True)
    before = before[before["exit_ts"] < start].sort_values("exit_ts")
    start_eq = float(before["equity_after"].iloc[-1]) if len(before) else INIT
    eq = [start_eq] + list(l["equity_after"].values)
    return continuous_max_dd(eq)


def winner_stripped_median(mr):
    if mr.empty:
        return None
    k = max(1, int(np.ceil(len(mr) * 0.05)))
    return float(mr.sort_values()[:-k].median()) if k < len(mr) else float(mr.median())


def profile_window(led, capped, start, end, label, risk_pct):
    mr = monthly_roi_from_ledger(led, start, end)
    if mr.empty:
        return None
    Rs = [t["R"] for t in split(capped, start, end)]
    p05 = block_bootstrap_maxdd(Rs, risk_pct=risk_pct)[1] if len(Rs) >= 20 else float("nan")
    rmdd = realized_maxdd_window(led, start, end)
    neg = int((mr < 0).sum())
    return dict(
        label=label, n_months=len(mr), n_tr=len(Rs),
        mean=float(mr.mean()), med=float(mr.median()),
        ws_med=winner_stripped_median(mr), std=float(mr.std()),
        neg=neg, best=float(mr.max()), worst=float(mr.min()),
        realized_dd=rmdd, bb_p05_dd=p05,
        sharpe_m=float(mr.mean() / mr.std()) if mr.std() > 0 else 0.0,
        sharpe_ann=float(mr.mean() / mr.std() * np.sqrt(12)) if mr.std() > 0 else 0.0,
    )


def run_cell(trades_by_sym, mode):
    """pool -> risk_parity -> netUSD cap -> faithful_replay(mode). Returns (led, eq, final, capped)."""
    raw = yaml.safe_load((ROOT / "configs" / "risk_forex.yaml").read_text())
    cfg = build_cfg(raw, max_concurrent=GROSS_CAP).with_overrides(risk_pct=RISK_PCT)
    pooled = risk_parity_trades(trades_by_sym, SYMBOLS_8)
    capped = apply_net_usd_cap(pooled, NET_USD_CAP, gross_cap=GROSS_CAP)
    led, eq, final = faithful_replay(capped, cfg, mode)
    return led, eq, final, capped


def fmt_row(p):
    if p is None:
        return "  (no data)"
    return (f"  {p['label']:<20} nM={p['n_months']:>2} nTr={p['n_tr']:>4} | "
            f"mean={p['mean']:>+6.2f} med={p['med']:>+6.2f} wsMed={p['ws_med']:>+6.2f} "
            f"std={p['std']:>5.2f} | neg={p['neg']:>2}/{p['n_months']:<2} "
            f"best={p['best']:>+6.1f} worst={p['worst']:>+6.1f} | "
            f"rDD={p['realized_dd']:>+6.1f} bbP05={p['bb_p05_dd']:>+6.1f} | "
            f"Shrp_m={p['sharpe_m']:>+5.2f} ann={p['sharpe_ann']:>+5.2f}")


def main():
    baseline = pickle.load(open("/tmp/rt_trades.pkl", "rb"))["trades"]   # OLD exit
    wlr = pickle.load(open("/tmp/wlr_variants_4h.pkl", "rb"))
    winner = wlr["V1a_trail3.0"]                                          # NEW exit

    # quick sanity: same symbol set, trade counts
    print("=" * 110)
    print("SYNTHESIS INPUTS")
    print("=" * 110)
    for s in SYMBOLS_8:
        print(f"  {s:<9} baseline_n={len(baseline[s]):>4}  winner_let_run_n={len(winner[s]):>4}")

    cells = {
        "i_OLD_compound":   (baseline, "compounding"),
        "ii_OLD_fixed":     (baseline, "fixed_notional"),
        "iii_NEW_fixed":    (winner,   "fixed_notional"),
        # bonus: NEW exit under compounding (to isolate sizing vs exit interaction)
        "x_NEW_compound":   (winner,   "compounding"),
    }
    results = {}
    for name, (tr, mode) in cells.items():
        led, eq, final, capped = run_cell(tr, mode)
        results[name] = dict(led=led, eq=eq, final=final, capped=capped,
                             sumR=float(led["R"].sum()))

    # ============ (a) MERGED CONFIG FULL PROFILE : IS / OOS / COMBINED ============
    print("\n" + "=" * 110)
    print("(a) MERGED CANDIDATE = NEW winner-let-run exit (trail3.0) + FIXED-NOTIONAL ($100/trade)")
    print("    equal-weight, netUSD<=3, mc6, honest cost (slip1.0bps, swap haircut, fee0). init=$10k")
    print("=" * 110)
    cell = results["iii_NEW_fixed"]
    led, capped = cell["led"], cell["capped"]
    prof = {}
    for lbl, lo, hi in [("IS 2020-2023", IS_LO, IS_END),
                        ("OOS 2024-2025", IS_END, OOS_END),
                        ("COMBINED 2020-25", IS_LO, OOS_END)]:
        prof[lbl] = profile_window(led, capped, lo, hi, lbl, RISK_PCT)
    hdr = ("  window               nM  nTr  |   mean    med  wsMed   std |  neg    best  worst |"
           "    rDD  bbP05 |  Shrp_m   ann")
    print(hdr); print("  " + "-" * (len(hdr) - 2))
    for lbl in ["IS 2020-2023", "OOS 2024-2025", "COMBINED 2020-25"]:
        print(fmt_row(prof[lbl]))
    print(f"\n  final equity (fixed-notional, no compound): ${cell['final']:,.0f}  "
          f"sumR={cell['sumR']:.0f}  -> ${cell['final']-INIT:,.0f} net on $10k over 6y")

    # ============ (b) THREE-WAY COMPARISON (COMBINED window) ============
    print("\n" + "=" * 110)
    print("(b) THREE-WAY COMPARISON (combined 2020-2025, full pipeline)")
    print("=" * 110)
    cmp_rows = []
    labels = {"i_OLD_compound": "i) OLD+compound", "ii_OLD_fixed": "ii) OLD+fixed",
              "iii_NEW_fixed": "iii) NEW+fixed", "x_NEW_compound": "x) NEW+compound"}
    for name in ["i_OLD_compound", "ii_OLD_fixed", "iii_NEW_fixed", "x_NEW_compound"]:
        r = results[name]
        p = profile_window(r["led"], r["capped"], IS_LO, OOS_END, labels[name], RISK_PCT)
        p["final"] = r["final"]; p["sumR"] = r["sumR"]
        cmp_rows.append((name, p))
    hdr2 = (f"  {'config':<20}{'final$':>13}{'sumR':>7} | {'med%':>7}{'wsMed%':>7}{'std%':>6} |"
            f" {'rDD%':>7}{'bbP05%':>7} | {'Shrp_ann':>9}{'neg/72':>8}")
    print(hdr2); print("  " + "-" * (len(hdr2) - 2))
    for name, p in cmp_rows:
        print(f"  {p['label']:<20}{p['final']:>13,.0f}{p['sumR']:>7.0f} | "
              f"{p['med']:>+7.2f}{p['ws_med']:>+7.2f}{p['std']:>6.2f} | "
              f"{p['realized_dd']:>+7.1f}{p['bb_p05_dd']:>+7.1f} | "
              f"{p['sharpe_ann']:>+9.2f}{p['neg']:>5}/{p['n_months']:<2}")

    # ============ (c) INTERACTION CHECK: does fixed-notional re-scale winner-let-run big-R? ============
    print("\n" + "=" * 110)
    print("(c) INTERACTION CHECK — winner-let-run big-R x fixed-notional")
    print("=" * 110)
    # compare R-distribution of winner vs baseline AFTER cap, and how each mode's $-path treats tails
    base_caps = results["ii_OLD_fixed"]["capped"]
    new_caps = results["iii_NEW_fixed"]["capped"]
    for tag, caps in [("OLD baseline", base_caps), ("NEW winner-let-run", new_caps)]:
        Rs = np.array([t["R"] for t in caps])
        print(f"  {tag:<20} n={len(Rs):>4} meanR={Rs.mean():>+.3f} "
              f"p95R={np.percentile(Rs,95):>+.2f} maxR={Rs.max():>+.2f} "
              f"top5%share={Rs[Rs>=np.percentile(Rs,95)].sum()/Rs[Rs>0].sum()*100:>4.0f}%")
    print("  Under FIXED-notional every R worth the same $ (=$100*R) regardless of when it lands ->")
    print("  winner-let-run's fatter right tail converts 1:1 to $; under COMPOUND a late big-R is")
    print("  amplified by prior equity (illusion). Compare NEW+fixed vs NEW+compound final$ above.")

    pickle.dump({"results": {k: {"final": v["final"], "sumR": v["sumR"]} for k, v in results.items()},
                 "merged_profile": prof}, open("/tmp/combo_synthesis.pkl", "wb"))
    print("\nDONE.")


if __name__ == "__main__":
    main()
