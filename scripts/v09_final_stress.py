"""v0.9 FINAL stress test — best config 3y rolling.

Config: Top 10 strateji + 11 sembol + sabit %3 + conf>=0.2 + 1.0 ATR trail
Target: yIllIk +%62.78 (5y), test 3y rolling robustness.
"""
from __future__ import annotations

import sys
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

from scripts.v09_optimize_top10 import _gather, replay, TOP_10


def main():
    print("=" * 80)
    print("v0.9 FINAL stress test — Top 10 + 11 sym + r%3 + conf>=0.2 + 1.0 ATR trail")
    print("=" * 80)

    print("\nTopluyor...")
    all_trades = []
    for m, c in TOP_10:
        all_trades.extend(_gather(m, c))
    all_trades.sort(key=lambda x: x["entry_ts"])
    print(f"Toplam: {len(all_trades)}\n")

    # 5y tek
    print("# 5y senaryolar:")
    for risk in [0.015, 0.020, 0.025, 0.030, 0.035]:
        r = replay(all_trades, risk_pct=risk, conf_min=0.20)
        if r is None: continue
        ann = ((r["final"]/10000)**(1/5)-1)*100
        print(f"  risk %{risk*100:.1f} conf>=0.2: yIllIk {ann:+.2f}% DD {r['max_dd']*100:+.1f}% WR {r['wr']*100:.0f}% n={r['trades']}")

    # 3y rolling
    print("\n# 3y rolling stress (risk %3 conf>=0.2):")
    start = all_trades[0]["entry_ts"]
    end = all_trades[-1]["exit_ts"]
    windows = []
    cur = start
    while cur + pd.Timedelta(days=3*365) <= end:
        windows.append((cur, cur + pd.Timedelta(days=3*365)))
        cur += pd.Timedelta(days=60)

    print(f"{'Pencere':<28} {'sinyal':>7} {'final$':>10} {'3y%':>8} {'yIllIk':>8} {'DD':>6}")
    anns = []; dds = []; wrs = []
    for ws, we in windows:
        wt = [t for t in all_trades if ws <= t["entry_ts"] < we]
        if len(wt) < 10: continue
        r = replay(wt, risk_pct=0.030, conf_min=0.20)
        if r is None: continue
        ret = (r["final"]/10000-1)*100
        ann = ((r["final"]/10000)**(1/3)-1)*100
        anns.append(ann); dds.append(r["max_dd"]*100); wrs.append(r["wr"]*100)
        label = f"{ws.date()}->{we.date()}"
        print(f"{label:<28} {r['trades']:>7} {r['final']:>10,.0f} {ret:>+7.1f}% {ann:>+7.2f}% {r['max_dd']*100:>+5.0f}%")

    if anns:
        print()
        print(f"# 3y rolling ozeti ({len(anns)} pencere):")
        print(f"  Ortalama yIllIk: {np.mean(anns):+.2f}% (std {np.std(anns):.1f})")
        print(f"  Min/Max yIllIk: {min(anns):+.1f}% / {max(anns):+.1f}%")
        print(f"  Ortalama DD: {np.mean(dds):+.1f}%")
        print(f"  Ortalama WR: {np.mean(wrs):.1f}%")
        neg = sum(1 for a in anns if a < 0)
        print(f"  Negatif pencere: {neg}/{len(anns)}")
        target = sum(1 for a in anns if a >= 50)
        print(f"  %50+ pencere: {target}/{len(anns)} ({100*target/len(anns):.0f}%)")


if __name__ == "__main__":
    main()
