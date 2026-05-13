"""Sec11e: 3 yeni signal source standalone backtest.

Strategies:
  - fvg_fill_reversal       (FVG 3-bar imbalance + fill+reclaim)
  - liquidity_sweep_reversal (single swing point sweep + reclaim)
  - nr7_breakout_v2         (NR-window range/ATR breakout)

Edge gate (per strategy):
  - mean_R > +0.10
  - n_trade > 50
  - WR > 35%

Coskmaz: 11 sym x 5y x 1d.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ["PA_LOG_QUIET"] = "1"

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from scripts.v09_optimize_top10 import _gather, SYMBOLS_11

NEW = [
    ("fvg_fill_reversal", "FVGFillReversalStrategy"),
    ("liquidity_sweep_reversal", "LiquiditySweepReversalStrategy"),
    ("nr7_breakout_v2", "NR7BreakoutV2Strategy"),
]


def _summary(trades, name):
    if not trades:
        return {"name": name, "n": 0, "mR": 0.0, "sumR": 0.0, "WR": 0.0,
                "n_long": 0, "n_short": 0, "by_sym": {}}
    Rs = np.array([t["R"] for t in trades], dtype=float)
    n_long = sum(1 for t in trades if t["side"] == "long")
    n_short = sum(1 for t in trades if t["side"] == "short")
    by_sym = {}
    for t in trades:
        sym = t["symbol"]
        by_sym.setdefault(sym, []).append(t["R"])
    sym_summary = {sym: (len(v), float(np.mean(v))) for sym, v in by_sym.items()}
    return {
        "name": name,
        "n": len(trades),
        "mR": float(Rs.mean()),
        "sumR": float(Rs.sum()),
        "WR": float((Rs > 0).mean()),
        "n_long": n_long,
        "n_short": n_short,
        "by_sym": sym_summary,
    }


def main():
    print("=" * 90)
    print("Sec11e — 3 yeni signal source standalone backtest (5y, 11 sym)")
    print("=" * 90)
    print()

    all_trades = {}
    summaries = []
    for module_name, cls_name in NEW:
        print(f"-> {module_name} ({cls_name})")
        trades = _gather(module_name, cls_name)
        all_trades[module_name] = trades
        s = _summary(trades, module_name)
        summaries.append(s)
        print(f"   n={s['n']:5d}  mR={s['mR']:+.3f}  sumR={s['sumR']:+.1f}  "
              f"WR={s['WR']*100:.1f}%  long={s['n_long']:4d} short={s['n_short']:4d}")

    print()
    print("=" * 90)
    print("EDGE GATE (mR > +0.10, n > 50, WR > 35%)")
    print("=" * 90)
    for s in summaries:
        passes = s["mR"] > 0.10 and s["n"] > 50 and s["WR"] > 0.35
        verdict = "PASS" if passes else "FAIL"
        reasons = []
        if s["mR"] <= 0.10: reasons.append(f"mR={s['mR']:+.2f}<=0.10")
        if s["n"] <= 50: reasons.append(f"n={s['n']}<=50")
        if s["WR"] <= 0.35: reasons.append(f"WR={s['WR']*100:.0f}%<=35%")
        rs = (" | " + ", ".join(reasons)) if reasons else ""
        print(f"  [{verdict}] {s['name']:<32} mR={s['mR']:+.3f} n={s['n']:5d} WR={s['WR']*100:5.1f}%{rs}")

    print()
    print("=" * 90)
    print("PER SYMBOL (top 5 mR per strategy)")
    print("=" * 90)
    for s in summaries:
        print(f"\n  {s['name']}:")
        sym_sorted = sorted(s["by_sym"].items(), key=lambda x: -x[1][1])
        for sym, (n, mr) in sym_sorted[:5]:
            print(f"    {sym:<14} n={n:4d} mR={mr:+.3f}")
        if len(sym_sorted) > 5:
            print(f"    ... ({len(sym_sorted)-5} more)")
            print(f"    --- bottom 3 ---")
            for sym, (n, mr) in sym_sorted[-3:]:
                print(f"    {sym:<14} n={n:4d} mR={mr:+.3f}")

    # Save trades for walk-forward (TOP_10 + new)
    out_path = ROOT / "reports" / "lab" / "sec11e_new_signals_trades.csv"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    for strat_name, trades in all_trades.items():
        for t in trades:
            rows.append({
                "strategy": strat_name,
                "symbol": t["symbol"],
                "side": t["side"],
                "entry_ts": t["entry_ts"].isoformat(),
                "exit_ts": t["exit_ts"].isoformat(),
                "R": t["R"],
                "conf": t["conf"],
            })
    if rows:
        pd.DataFrame(rows).to_csv(out_path, index=False)
        print(f"\nTrades dumped: {out_path}")

    # Pickle for walk-forward script
    import pickle
    pkl_path = ROOT / "reports" / "lab" / "sec11e_new_trades.pkl"
    with open(pkl_path, "wb") as f:
        pickle.dump(all_trades, f)
    print(f"Pickle for WF: {pkl_path}")

    return summaries, all_trades


if __name__ == "__main__":
    main()
