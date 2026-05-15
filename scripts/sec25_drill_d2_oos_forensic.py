"""SEC25 post-hoc drill — HYP-D2 (VSA SOW) OOS forensic.

Pre-registered hipotezde IS gate FAIL (n_IS<200, WR<45, p>=0.05). AMA OOS dramatik
(mR +0.533, WR 71%, p=0.0015). Bu honest forensic: gerçek edge mi yoksa survivorship/
outlier mi?

Sorular:
1. AVAX outlier (sym-out dev 140%) çıkartılırsa OOS hala iyi mi?
2. max_R 14.91 artifact analizi (hold=48d, R clip uygulandı mı?)
3. Per-sym/per-year OOS breakdown
4. Bootstrap 95% CI for OOS mR
"""
import os
import sys
import pickle
from pathlib import Path

os.environ["PA_LOG_QUIET"] = "1"

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

import numpy as np
import pandas as pd


def main():
    pkl = ROOT / "reports" / "researcher" / "sec25_volume_trades.pkl"
    with open(pkl, "rb") as f:
        all_trades = pickle.load(f)

    d2_trades = all_trades.get("vsa_sow_effort_down", [])
    print(f"=" * 100)
    print(f"HYP-D2 vsa_sow_effort_down POST-HOC FORENSIC")
    print(f"  Total trades: {len(d2_trades)}")
    print(f"=" * 100)

    OOS_START = pd.Timestamp("2024-01-01", tz="UTC")
    def _to_naive(ts):
        ts = pd.Timestamp(ts)
        if ts.tzinfo is not None:
            return ts.tz_localize(None)
        return ts
    oos_cutoff = _to_naive(OOS_START)

    # Convert entry_ts for safe compare
    for t in d2_trades:
        t["_entry_naive"] = _to_naive(t["entry_ts"])
    is_t = [t for t in d2_trades if t["_entry_naive"] < oos_cutoff]
    oos_t = [t for t in d2_trades if t["_entry_naive"] >= oos_cutoff]

    print(f"\n[1] IS / OOS split")
    print(f"   IS:  n={len(is_t):3d}  mR={np.mean([t['R'] for t in is_t]):+.4f}")
    print(f"   OOS: n={len(oos_t):3d}  mR={np.mean([t['R'] for t in oos_t]):+.4f}")

    # AVAX exclusion
    is_no_avax = [t for t in is_t if t["symbol"] != "AVAX/USDT"]
    oos_no_avax = [t for t in oos_t if t["symbol"] != "AVAX/USDT"]
    print(f"\n[2] AVAX exclusion (sym-out dev 140% was AVAX)")
    print(f"   IS  no_AVAX: n={len(is_no_avax):3d}  mR={np.mean([t['R'] for t in is_no_avax]):+.4f}  "
          f"(was {np.mean([t['R'] for t in is_t]):+.4f})")
    print(f"   OOS no_AVAX: n={len(oos_no_avax):3d}  mR={np.mean([t['R'] for t in oos_no_avax]):+.4f}  "
          f"(was {np.mean([t['R'] for t in oos_t]):+.4f})")

    # Per-year OOS breakdown (no AVAX)
    print(f"\n[3] Per-year breakdown (full sample including AVAX)")
    by_year = {}
    by_year_no_avax = {}
    for t in d2_trades:
        yr = t["_entry_naive"].year
        by_year.setdefault(yr, []).append(t["R"])
        if t["symbol"] != "AVAX/USDT":
            by_year_no_avax.setdefault(yr, []).append(t["R"])
    for yr in sorted(by_year.keys()):
        Rs = by_year[yr]
        Rs_na = by_year_no_avax.get(yr, [])
        print(f"   {yr}: n={len(Rs):3d}  mR={np.mean(Rs):+.4f}  |  no_AVAX n={len(Rs_na):3d}  "
              f"mR={(np.mean(Rs_na) if Rs_na else 0):+.4f}")

    # Per-sym OOS breakdown
    print(f"\n[4] Per-symbol OOS breakdown")
    by_sym_oos = {}
    for t in oos_t:
        by_sym_oos.setdefault(t["symbol"], []).append(t["R"])
    for sym in sorted(by_sym_oos.keys()):
        Rs = by_sym_oos[sym]
        print(f"   {sym:<14}: n={len(Rs):3d}  mR={np.mean(Rs):+.4f}  max_R={max(Rs):+.2f}")

    # Max R artifact analysis
    print(f"\n[5] Max-R artifact analysis (clip threshold = 10.0)")
    all_R_raw = [(t["R_raw"], t["R"], t["hold_d"], t["symbol"], t["side"], str(t["_entry_naive"].date()))
                 for t in d2_trades]
    all_R_raw.sort(key=lambda x: -x[0])
    print(f"   Top 5 R_raw:")
    for raw, r, hd, sym, side, date in all_R_raw[:5]:
        clipped = " (clipped)" if hd > 60 and raw > 1.0 else ""
        print(f"     {sym:<14} {side:<5} R_raw={raw:+.2f}  R={r:+.2f}  hold={hd:3d}d  entry={date}{clipped}")

    # Bootstrap CI for OOS mR
    print(f"\n[6] Bootstrap 95% CI for OOS mR (n_resample=5000, seed=42)")
    def _bootstrap_ci(samples, n_resample=5000, seed=42, alpha=0.05):
        if not samples:
            return None, None, None
        rng = np.random.default_rng(seed)
        arr = np.array(samples)
        means = []
        for _ in range(n_resample):
            idx = rng.integers(0, len(arr), len(arr))
            means.append(arr[idx].mean())
        means = np.sort(means)
        lo = means[int(n_resample * alpha / 2)]
        hi = means[int(n_resample * (1 - alpha / 2))]
        return float(np.mean(means)), float(lo), float(hi)

    oos_Rs = [t["R"] for t in oos_t]
    mean, lo, hi = _bootstrap_ci(oos_Rs)
    print(f"   OOS (n={len(oos_Rs)}):       mean={mean:+.4f}  95% CI=[{lo:+.4f}, {hi:+.4f}]")
    oos_Rs_na = [t["R"] for t in oos_no_avax]
    mean_na, lo_na, hi_na = _bootstrap_ci(oos_Rs_na)
    print(f"   OOS no_AVAX (n={len(oos_Rs_na)}): mean={mean_na:+.4f}  95% CI=[{lo_na:+.4f}, {hi_na:+.4f}]")

    # Hold time distribution
    print(f"\n[7] Hold time distribution (OOS)")
    holds = [t["hold_d"] for t in oos_t]
    print(f"   median={int(np.median(holds))}d  p25={int(np.percentile(holds, 25))}d  "
          f"p75={int(np.percentile(holds, 75))}d  p90={int(np.percentile(holds, 90))}d  "
          f"max={max(holds)}d")

    # Decision
    print(f"\n[8] HONEST INTERPRETATION")
    print(f"   IS gate FAIL — pre-registered RED.")
    print(f"   OOS performance retroactive observation, NOT pre-registered alpha.")
    print(f"   AVAX exclusion impact: {('SIGNIFICANT' if abs(mean - mean_na) > 0.2 else 'modest')}")
    print(f"   CI low > 0?  full OOS: {'YES' if lo > 0 else 'NO'}  | no_AVAX: {'YES' if lo_na > 0 else 'NO'}")
    print(f"   FINAL VERDICT: pre-reg RED (cannot promote based on OOS-only evidence).")
    print(f"   FOLLOW-UP candidate: v2 with longer history if 2026 cycle continues bearish.")


if __name__ == "__main__":
    main()
