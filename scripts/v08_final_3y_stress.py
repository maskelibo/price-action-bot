"""v0.8 final config — 3y rolling stress test.

Best config: Top 5 (engulfing, brooks_failed_bo, brooks_h2_l2, wyckoff_phase_d, obv_engulfing)
Risk: sabit %1.5 (yuksek getiri/dd dengesi)
Multi-target engine ile.
"""
from __future__ import annotations

import io
import sys
from datetime import timedelta
from pathlib import Path

import numpy as np
import pandas as pd

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))
sys.path.insert(0, str(ROOT))

from scripts.v08_autonomous_research import _gather, replay


def main():
    print("=" * 80)
    print("v0.8 FINAL CONFIG — 3y rolling stress test")
    print("=" * 80)

    TOP5 = [
        ("engulfing_continuation", "EngulfingContinuationStrategy"),
        ("brooks_failed_breakout", "BrooksFailedBreakoutStrategy"),
        ("brooks_h2_l2", "BrooksH2L2Strategy"),
        ("wyckoff_phase_d", "WyckoffPhaseDStrategy"),
        ("obv_engulfing_confluence", "OBVEngulfingConfluenceStrategy"),
    ]

    print("\nTrade'leri topluyor...")
    all_trades = []
    for module_name, class_name in TOP5:
        trs = _gather(module_name, class_name)
        print(f"  {module_name}: {len(trs)} sinyal")
        all_trades.extend(trs)
    all_trades.sort(key=lambda x: x["entry_ts"])
    print(f"  TOPLAM: {len(all_trades)}\n")

    # 5y tek
    for risk in [0.010, 0.015, 0.020]:
        r = replay(all_trades, risk_pct=risk)
        ann = ((r["final"]/10000)**(1/5)-1)*100
        print(f"5y senaryo (risk %{risk*100:.1f}): yIllIk {ann:+.2f}% DD {r['max_dd']*100:+.1f}% WR {r['wr']*100:.0f}%")

    # 3y rolling stress
    print("\n# 3y rolling stress (sabit %1.5):")
    start = all_trades[0]["entry_ts"]
    end = all_trades[-1]["exit_ts"]
    windows = []
    cur = start
    while cur + pd.Timedelta(days=3*365) <= end:
        windows.append((cur, cur + pd.Timedelta(days=3*365)))
        cur += pd.Timedelta(days=60)

    print(f"{'Pencere (3y)':<28} {'sinyal':>7} {'final$':>10} {'3y%':>8} {'yIllIk':>8} {'DD':>6}")
    anns = []; dds = []
    for ws, we in windows:
        wt = [t for t in all_trades if ws <= t["entry_ts"] < we]
        if len(wt) < 10: continue
        r = replay(wt, risk_pct=0.015)
        if r is None: continue
        ret = (r["final"]/10000-1)*100
        ann = ((r["final"]/10000)**(1/3)-1)*100
        anns.append(ann); dds.append(r["max_dd"]*100)
        label = f"{ws.date()}->{we.date()}"
        print(f"{label:<28} {r['trades']:>7} {r['final']:>10,.0f} {ret:>+7.1f}% {ann:>+7.2f}% {r['max_dd']*100:>+5.0f}%")

    print()
    if anns:
        print(f"# 3y rolling ozeti ({len(anns)} pencere):")
        print(f"  Ortalama yillik: {np.mean(anns):+.2f}% (std {np.std(anns):.1f})")
        print(f"  Min yillik: {min(anns):+.1f}%")
        print(f"  Max yillik: {max(anns):+.1f}%")
        print(f"  Ortalama DD: {np.mean(dds):+.1f}%")
        worst = [a for a in anns if a < 0]
        print(f"  Negatif pencere: {len(worst)}/{len(anns)} ({100*len(worst)/len(anns):.0f}%)")


if __name__ == "__main__":
    main()
