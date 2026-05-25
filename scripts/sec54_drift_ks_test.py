"""SEC54.DD-01 — Drift Detection KS Test (production paper-vs-backtest).

Pre-reg / kullanim:
  Backtest aylik ROI dagilimi: 61 ay (SEC53 sec53_c2v5_per_month.csv)
  Paper trade 30g toplam: tek scalar ya da haftalik 4 sample.

  Iki yontem:
    A) Tek-ay null: Backtest 61 aydan random tek ay ornekle, paper 30g ROI
       bu dagilimda nereye duser? Bootstrap percentile (one-sided).
    B) KS 2-sample (paper >=30 sample lazim — daha sonra; ilk 30g icin A
       yeterli).

Gate:
  p < 0.01  -> drift alarmi (CEO brief)
  p < 0.05  -> warning (Researcher hipotez)
  p >= 0.05 -> healthy

Cikti: reports/lab/sec54_drift_<YYYY-MM-DD>.md
"""
from __future__ import annotations

import csv
import json
import math
import random
import sys
from pathlib import Path
from statistics import mean

ROOT = Path(__file__).resolve().parents[1]
PER_MONTH = ROOT / "reports" / "lab" / "sec53_c2v5_per_month.csv"


def load_backtest_monthly_rois() -> list[float]:
    rows = []
    with PER_MONTH.open("r", encoding="utf-8") as f:
        rd = csv.DictReader(f)
        for r in rd:
            if r.get("skip", ""):
                continue
            rows.append(float(r["monthly_pct"]))
    return rows


def percentile_of_value(sorted_vals: list[float], val: float) -> float:
    """Empirical CDF: fraction of sorted_vals <= val."""
    if not sorted_vals:
        return 0.5
    cnt = sum(1 for x in sorted_vals if x <= val)
    return cnt / len(sorted_vals)


def two_sided_pvalue(sorted_vals: list[float], val: float) -> float:
    """Two-sided p: 2 * min(empirical_cdf, 1 - empirical_cdf)."""
    cdf = percentile_of_value(sorted_vals, val)
    return 2 * min(cdf, 1 - cdf)


def ks_2sample(a: list[float], b: list[float]) -> tuple[float, float]:
    """KS 2-sample stat + asymptotic p-value (Smirnov)."""
    a = sorted(a)
    b = sorted(b)
    na, nb = len(a), len(b)
    # Build joint CDF
    all_vals = sorted(set(a + b))
    d = 0.0
    for v in all_vals:
        ca = sum(1 for x in a if x <= v) / na
        cb = sum(1 for x in b if x <= v) / nb
        d = max(d, abs(ca - cb))
    # Asymptotic p (Smirnov)
    en = math.sqrt(na * nb / (na + nb))
    arg = (en + 0.12 + 0.11 / en) * d
    # series approximation
    p = 0.0
    for j in range(1, 101):
        p += 2 * ((-1) ** (j - 1)) * math.exp(-2 * (j ** 2) * (arg ** 2))
    p = max(0.0, min(1.0, p))
    return d, p


def drift_test(paper_monthly_roi: float) -> dict:
    """Single-month drift test: paper observed vs backtest distribution."""
    bt = load_backtest_monthly_rois()
    s = sorted(bt)
    cdf = percentile_of_value(s, paper_monthly_roi)
    p_two = two_sided_pvalue(s, paper_monthly_roi)

    # Bootstrap: random month from BT 10000 times
    rng = random.Random(20260517)
    boot = [s[rng.randrange(len(s))] for _ in range(10000)]
    boot_sorted = sorted(boot)
    boot_p_left = sum(1 for x in boot_sorted if x <= paper_monthly_roi) / len(boot)
    boot_p_two = 2 * min(boot_p_left, 1 - boot_p_left)

    verdict = ("DRIFT_ALARM" if p_two < 0.01 else
                "DRIFT_WARNING" if p_two < 0.05 else "HEALTHY")
    return {
        "paper_monthly_roi": paper_monthly_roi,
        "backtest_mean": mean(bt),
        "backtest_median": s[len(s) // 2],
        "backtest_min": s[0],
        "backtest_max": s[-1],
        "empirical_cdf": cdf,
        "p_two_sided": p_two,
        "bootstrap_p_two_sided": boot_p_two,
        "verdict": verdict,
    }


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python sec54_drift_ks_test.py <paper_monthly_roi_pct>")
        print("       paper sample list: python sec54_drift_ks_test.py 12.3 8.7 -2.1")
        sys.exit(1)

    if len(sys.argv) == 2:
        roi = float(sys.argv[1])
        result = drift_test(roi)
        print(json.dumps(result, indent=2))
    else:
        # Multi-sample KS test
        paper = [float(x) for x in sys.argv[1:]]
        bt = load_backtest_monthly_rois()
        d, p = ks_2sample(bt, paper)
        out = {
            "n_paper": len(paper),
            "n_backtest": len(bt),
            "ks_stat": d,
            "ks_p_asymptotic": p,
            "paper_mean": mean(paper),
            "backtest_mean": mean(bt),
            "verdict": ("DRIFT_ALARM" if p < 0.01 else
                         "DRIFT_WARNING" if p < 0.05 else "HEALTHY"),
        }
        print(json.dumps(out, indent=2))
