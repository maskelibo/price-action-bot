"""Sec19: 3 yeni strateji standalone backtest (Researcher sprint 2026-05-14).

Stratejiler:
  - inside_day_failure (Tom Dante IDF + Adam Grimes failure test)
  - high_tight_flag    (O'Neil/Bulkowski HTF — alt-coin parabolik breakout)
  - quasimodo_reversal (LiteFinance/HoneyPips QM 5-pivot reversal)

Edge gate (her strateji):
  - mean_R > +0.10
  - n_trade > 30 (HTF rare)
  - WR > 0.35

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
    ("inside_day_failure", "InsideDayFailureStrategy"),
    ("high_tight_flag", "HighTightFlagStrategy"),
    ("quasimodo_reversal", "QuasimodoReversalStrategy"),
]

# Edge gates (n threshold per pattern; HTF is rare so lower)
GATES = {
    "inside_day_failure": {"mR": 0.10, "n": 50, "WR": 0.35},
    "high_tight_flag":    {"mR": 0.10, "n": 30, "WR": 0.40},
    "quasimodo_reversal": {"mR": 0.10, "n": 50, "WR": 0.35},
}


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
    print("Sec19 - 3 yeni strateji standalone backtest (5y, 11 sym)")
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
    print("EDGE GATE")
    print("=" * 90)
    for s in summaries:
        gate = GATES.get(s["name"], {"mR": 0.10, "n": 50, "WR": 0.35})
        passes = s["mR"] > gate["mR"] and s["n"] > gate["n"] and s["WR"] > gate["WR"]
        verdict = "PASS" if passes else "FAIL"
        reasons = []
        if s["mR"] <= gate["mR"]: reasons.append(f"mR={s['mR']:+.3f}<={gate['mR']:.2f}")
        if s["n"] <= gate["n"]: reasons.append(f"n={s['n']}<={gate['n']}")
        if s["WR"] <= gate["WR"]: reasons.append(f"WR={s['WR']*100:.0f}%<={gate['WR']*100:.0f}%")
        rs = (" | " + ", ".join(reasons)) if reasons else ""
        print(f"  [{verdict}] {s['name']:<28} mR={s['mR']:+.3f} n={s['n']:5d} WR={s['WR']*100:5.1f}%{rs}")

    print()
    print("=" * 90)
    print("PER SYMBOL (top 5 / bottom 3 mR per strategy)")
    print("=" * 90)
    for s in summaries:
        print(f"\n  {s['name']}:")
        if not s["by_sym"]:
            print("    (no trades)")
            continue
        sym_sorted = sorted(s["by_sym"].items(), key=lambda x: -x[1][1])
        for sym, (n, mr) in sym_sorted[:5]:
            print(f"    {sym:<14} n={n:4d} mR={mr:+.3f}")
        if len(sym_sorted) > 5:
            print(f"    --- bottom 3 ---")
            for sym, (n, mr) in sym_sorted[-3:]:
                print(f"    {sym:<14} n={n:4d} mR={mr:+.3f}")

    # Dump trades pkl (for ensemble WF)
    import pickle
    pkl_path = ROOT / "reports" / "researcher" / "sec19_new_trades.pkl"
    pkl_path.parent.mkdir(parents=True, exist_ok=True)
    with open(pkl_path, "wb") as f:
        pickle.dump(all_trades, f)
    print(f"\nPickle for WF: {pkl_path}")

    return summaries, all_trades


if __name__ == "__main__":
    main()
