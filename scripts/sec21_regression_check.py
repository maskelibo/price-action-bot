"""SEC21 — Quick parity check: confirms lab.py changes are pure-additive.

Compares regression-test result against:
  1. SEC15.5 std_pyramid (no MFE-aware, no 0.06R slippage): +%150.5 / DD -%35.5
  2. v2.0.3 PRODUCTION reference (post-SEC16 MFE+slip): +%239.5 / DD -%38.7

Cached pool does NOT contain peak_R, so MFE-aware pyramid degrades to
non-MFE behavior. Result expected: +%136 area (SEC16 0.06R slippage applied
to non-MFE peak_R fallback = lower than SEC15.5).
"""
from __future__ import annotations

import pickle
import sys
from dataclasses import replace
from pathlib import Path
from statistics import mean, median

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from price_action.backtest.lab import ProductionConfig, production_replay
from price_action.backtest.regime import compute_btc_capitulation_halt
from scripts.v097_balanced_optimization import build_fng_short_skip


def main():
    POOL = ROOT / "data" / "_sec13_4_cache" / "pool_A6_mult15_t30.pkl"
    with POOL.open("rb") as f:
        pool = pickle.load(f)
    pool.sort(key=lambda t: t["entry_ts"])
    print(f"Pool: {len(pool)} trade  (cached v1.5 A6, no peak_R)")

    base = ProductionConfig.from_yaml(str(ROOT / "configs" / "risk_balanced.yaml"))
    halt_cal = compute_btc_capitulation_halt()
    fng = build_fng_short_skip(20)
    cfg = replace(base, alt_data_skip_long=None,
                  alt_data_skip_short=fng, btc_halt_calendar=halt_cal)
    print(f"cfg: pyr_en={cfg.pyramid_enabled} trig={cfg.pyramid_triggers} "
          f"size={cfg.pyramid_sizes} slot_alloc={cfg.slot_allocation_enabled}")
    print(f"     mdd={cfg.monthly_dd} mdd_long={cfg.monthly_dd_long} "
          f"mdd_short={cfg.monthly_dd_short} halt={cfg.monthly_halt_days}d")

    win_start = pool[0]["entry_ts"]
    win_end = pool[-1]["exit_ts"]
    cur = win_start
    windows = []
    while cur + pd.Timedelta(days=3*365) <= win_end:
        windows.append((cur, cur + pd.Timedelta(days=3*365)))
        cur += pd.Timedelta(days=60)
    print(f"{len(windows)} windows")

    anns, dds = [], []
    for ws, we in windows:
        w = [t for t in pool if ws <= t["entry_ts"] < we]
        r = production_replay(w, cfg)
        if r:
            anns.append(r.annualized(3.0)*100)
            dds.append(r.max_drawdown*100)
    ma = mean(anns)
    md = mean(dds)
    print(f"RESULT: mean_ann={ma:+.2f}%  mean_dd={md:+.1f}%  "
          f"r-adj={ma/abs(md):.3f}  neg={sum(1 for a in anns if a<0)}")
    print()
    print("Reference points:")
    print("  SEC15.5 std_pyramid (no MFE, no 0.06R slip): +%150.5 / DD -%35.5")
    print("  v2.0.3 PRODUCTION (MFE+0.06R slip):           +%239.5 / DD -%38.7")
    print()
    print("Interpretation:")
    print("  - Cached pool has NO peak_R -> MFE fallback to final R")
    print("  - With 0.06R slip applied:  +%150.5 -> ~+%136 (slip cost on trigger crossers)")
    print(f"  - Measured {ma:+.2f}%: {'consistent with SEC16 fixes on no-peak_R pool' if 130 <= ma <= 145 else 'UNEXPECTED'}")


if __name__ == "__main__":
    main()
