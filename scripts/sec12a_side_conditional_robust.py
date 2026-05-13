"""SEC12A.B: Side-conditional WINNER robustness check.

Top winner: V_C long=0.12/short=0.06 -> ann +64.46% / DD -32.94% / r-adj 1.957

Bunu robust mu? Plateau veya cherry-pick mı?
- Yakın grid: long ∈ {0.10, 0.12, 0.15, 0.20}, short ∈ {0.04, 0.05, 0.06, 0.07, 0.08}
- En iyi 3 en az 3'lük cluster bul
- Per-window detail
- Long/short trade dağılımı (kaç long halt, kaç short halt)
"""
from __future__ import annotations

import os, sys, pickle
from pathlib import Path
from statistics import mean, median

os.environ["PA_LOG_QUIET"] = "1"
import warnings; warnings.filterwarnings("ignore")
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from price_action.backtest.lab import ProductionConfig, _lazy_build_funding_filters
from price_action.backtest.regime import compute_btc_capitulation_halt
from scripts.v097_balanced_optimization import DROP_PAIRS, build_fng_short_skip
from scripts.sec12a_monthly_dd_deep import (
    replay_with_monthly_dd, window_metrics, CACHE_PATH,
)


def main():
    # Pool reuse
    with CACHE_PATH.open("rb") as f:
        pool = pickle.load(f)
    print(f"Pool: {len(pool)} trade")

    # Long/short trade ratios
    longs = [t for t in pool if t["side"] == "long"]
    shorts = [t for t in pool if t["side"] == "short"]
    print(f"  Long: {len(longs)} ({len(longs)/len(pool)*100:.1f}%)")
    print(f"  Short: {len(shorts)} ({len(shorts)/len(pool)*100:.1f}%)")
    long_R = sum(t["R"] for t in longs) / len(longs) if longs else 0
    short_R = sum(t["R"] for t in shorts) / len(shorts) if shorts else 0
    print(f"  Avg R long: {long_R:+.3f}, short: {short_R:+.3f}")
    long_neg = sum(1 for t in longs if t["R"] < 0)
    short_neg = sum(1 for t in shorts if t["R"] < 0)
    print(f"  Long WR: {(len(longs)-long_neg)/len(longs)*100:.1f}%, Short WR: {(len(shorts)-short_neg)/len(shorts)*100:.1f}%")

    base = ProductionConfig.from_yaml("configs/risk_balanced.yaml")
    halt_cal = compute_btc_capitulation_halt()
    fund_long, fund_short = _lazy_build_funding_filters({
        "funding_filter_enabled": True, "funding_aggregation_mode": "00:00_only",
    })
    fng_short_20 = build_fng_short_skip(20)
    combined_short_skip = {**dict(fund_short or {}), **dict(fng_short_20)}
    cfg_v12 = base.with_overrides(
        alt_data_skip_long=fund_long,
        alt_data_skip_short=combined_short_skip,
        drop_pairs=DROP_PAIRS,
        btc_halt_calendar=halt_cal,
        monthly_dd=0.08,
    )

    # Genis side grid
    print("\n" + "=" * 110)
    print("GENIS SIDE-CONDITIONAL GRID (5x5 = 25 hücre)")
    print("=" * 110)
    print(f"  {'long':>5} {'short':>5} {'yillik':>9} {'med':>7} {'min':>7} {'max':>7} {'DD':>7} {'r-adj':>7} {'neg':>5}")
    grid = []
    longs_g = [0.08, 0.10, 0.12, 0.15, 0.20]
    shorts_g = [0.04, 0.05, 0.06, 0.07, 0.08]
    for sl in longs_g:
        for ss in shorts_g:
            m = window_metrics(pool, cfg_v12, replay_with_monthly_dd,
                              monthly_dd=0.08, halt_days=30,
                              side_dd_long=sl, side_dd_short=ss,
                              track_halt=True)
            if not m: continue
            ra = m["ann_mean"] / abs(m["dd_mean"])
            print(f"  {sl:>5.2f} {ss:>5.2f} {m['ann_mean']:>+8.2f}% {m['ann_med']:>+5.2f}% {m['ann_min']:>+5.2f}% {m['ann_max']:>+5.2f}% {m['dd_mean']:>+5.2f}% {ra:>6.3f} {m['neg']:>3}/{m['n_windows']}")
            grid.append((sl, ss, m, ra))

    # Top 5 robust
    grid.sort(key=lambda x: -x[2]["ann_mean"])
    print("\nTOP 5 ROI:")
    for sl, ss, m, ra in grid[:5]:
        print(f"  long={sl:.2f} short={ss:.2f}: ann {m['ann_mean']:+.2f}% / DD {m['dd_mean']:+.2f}% / r-adj {ra:.3f}")

    # Top 5 r-adj
    grid_ra = sorted(grid, key=lambda x: -x[3])
    print("\nTOP 5 r-adj:")
    for sl, ss, m, ra in grid_ra[:5]:
        print(f"  long={sl:.2f} short={ss:.2f}: ann {m['ann_mean']:+.2f}% / DD {m['dd_mean']:+.2f}% / r-adj {ra:.3f}")

    # Plateau check: WINNER (0.12/0.06) etrafindaki 8 komsusunu ortalama al
    # neighbors: (long ∈ {0.10, 0.12, 0.15}) x (short ∈ {0.05, 0.06, 0.07})
    print("\nPLATEAU CHECK — WINNER (0.12/0.06) etrafindaki 9-cell mean")
    nbr = [g for g in grid
           if g[0] in [0.10, 0.12, 0.15] and g[1] in [0.05, 0.06, 0.07]]
    if nbr:
        nm = mean(g[2]["ann_mean"] for g in nbr)
        nd = mean(g[2]["dd_mean"] for g in nbr)
        nr = mean(g[3] for g in nbr)
        print(f"  9-cell neighborhood mean: ann {nm:+.2f}% / DD {nd:+.2f}% / r-adj {nr:.3f}")

    # Per-window detail for WINNER
    print("\nWINNER (0.12/0.06) per-window:")
    m = window_metrics(pool, cfg_v12, replay_with_monthly_dd,
                      monthly_dd=0.08, halt_days=30,
                      side_dd_long=0.12, side_dd_short=0.06,
                      track_halt=True)
    if m:
        for w in m["per_window"]:
            print(f"  {w['start']:>10} -> {w['end']:>10}: ann {w['ann']:+.2f}% / DD {w['dd']:+.2f}% / halts {w['halts']}")


if __name__ == "__main__":
    main()
