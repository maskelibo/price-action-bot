"""Check: if MR strategies have negative edge (fade is wrong), does the REVERSE
direction (continuation) yield positive edge?

This is the contrapositive sanity check. If e.g. range_bo_failure 'fade' has
mR=-0.17 with p=1.00 (strong negative), then 'follow the breakout' should have
mR=+0.17 (modulo fee asymmetry).

If TRUE: MR pool could be flipped -> new trend-cont strategies.
If FALSE: pool is just losers (fee/slip dominated).
"""
from __future__ import annotations
import io, os, pickle, sys
from pathlib import Path

if __name__ == "__main__":
    try: sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    except Exception: pass

os.environ["PA_LOG_QUIET"] = "1"
import warnings; warnings.filterwarnings("ignore")
import logging; logging.getLogger("price_action").setLevel(logging.ERROR)

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "src"))

import numpy as np

POOL = ROOT / "data" / "sec_s5_mr_pool.pkl"


def main():
    with POOL.open("rb") as f:
        mr_by_strat = pickle.load(f)

    print("DIRECTIONAL FLIP SANITY CHECK")
    print("=" * 80)
    print(f"{'Strategy':<24} {'n':>6} {'mR(fade)':>10} {'WR%':>6} {'mR(rev)':>10} {'WR%(rev)':>9}")
    print("-" * 80)
    for strat, trades in mr_by_strat.items():
        if not trades:
            continue
        Rs = np.array([t["R"] for t in trades])
        wr_fade = (Rs > 0).mean() * 100
        # Reverse: if we'd taken the OPPOSITE direction, what's the R?
        # Naive: R_rev = -R - 2*fee_proxy (each side pays fee). Assume 8 bps RT.
        # Tighter: per-trade we know entry/sl/initial_sl - reversing means SL becomes TP*1/1.2 + fee adjustment.
        # Quick approx: R_rev = -(R + fee_in_R), where fee_in_R = 2*0.00075/risk_pct
        # But we have R as final, so just flip sign and subtract 2x fee (paid on both sides).
        # Single trade's risk_pct varies; use average 1.5% as proxy -> fee_in_R ~ 0.001/0.015 = 0.067 R
        fee_in_R = 0.10  # conservative: 2x taker = 0.15%, on ~1.5% risk = 0.10 R loss to flip
        R_rev = -Rs - fee_in_R
        wr_rev = (R_rev > 0).mean() * 100
        print(f"{strat:<24} {len(trades):>6,} {Rs.mean():>+10.4f} {wr_fade:>6.1f} "
              f"{R_rev.mean():>+10.4f} {wr_rev:>9.1f}")

    print()
    print("Interpretation:")
    print("- If mR(rev) > +0.10 -> flipping the strategy yields edge -> FOLLOW direction (continuation)")
    print("- If mR(rev) < +0.10 -> pool is just fee-dominated losers -> archive")


if __name__ == "__main__":
    main()
