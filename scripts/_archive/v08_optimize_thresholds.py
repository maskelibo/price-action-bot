"""v0.8 optimize — confidence threshold per strategy + Symbol expansion."""
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


TOP5 = [
    ("engulfing_continuation", "EngulfingContinuationStrategy"),
    ("brooks_failed_breakout", "BrooksFailedBreakoutStrategy"),
    ("brooks_h2_l2", "BrooksH2L2Strategy"),
    ("wyckoff_phase_d", "WyckoffPhaseDStrategy"),
    ("obv_engulfing_confluence", "OBVEngulfingConfluenceStrategy"),
]


def main():
    print("=" * 80)
    print("v0.8 OPTIMIZE — confidence threshold + portfoy")
    print("=" * 80)

    print("\nTrade'leri topluyor...")
    all_trades = []
    for module_name, class_name in TOP5:
        trs = _gather(module_name, class_name)
        all_trades.extend(trs)
    all_trades.sort(key=lambda x: x["entry_ts"])
    print(f"Toplam: {len(all_trades)} sinyal\n")

    # Confidence threshold tarama
    print("# CONFIDENCE THRESHOLD TARAMA (sabit %1.5)")
    print(f"{'Threshold':<12} {'sinyal':>7} {'final$':>10} {'yIllIk':>8} {'DD':>6} {'WR':>4}")
    print("-" * 55)
    for cm in [0.0, 0.10, 0.20, 0.30, 0.35, 0.40, 0.45, 0.50]:
        ts = [t for t in all_trades if t["conf"] >= cm]
        if not ts: continue
        r = replay(ts, risk_pct=0.015)
        if r is None: continue
        ann = ((r["final"]/10000)**(1/5)-1)*100
        print(f"  conf>={cm:.2f}  {r['trades']:>7} {r['final']:>10,.0f} {ann:>+7.2f}% {r['max_dd']*100:>+5.0f}% {r['wr']*100:>3.0f}%")

    # Risk + threshold combinasyon
    print("\n# RISK + CONF THRESHOLD COMBO")
    print(f"{'Senaryo':<22} {'sinyal':>7} {'final$':>10} {'yIllIk':>8} {'DD':>6} {'r-adj':>6}")
    print("-" * 60)
    best = None
    for cm in [0.20, 0.30, 0.40]:
        for risk in [0.010, 0.015, 0.020, 0.025]:
            ts = [t for t in all_trades if t["conf"] >= cm]
            if not ts: continue
            r = replay(ts, risk_pct=risk)
            if r is None: continue
            ann = ((r["final"]/10000)**(1/5)-1)*100
            ra = ann / abs(r["max_dd"]*100) if r["max_dd"] else 0
            label = f"conf>={cm:.2f} risk%{risk*100:.1f}"
            print(f"{label:<22} {r['trades']:>7} {r['final']:>10,.0f} {ann:>+7.2f}% {r['max_dd']*100:>+5.0f}% {ra:>5.2f}")
            if best is None or ann > best[1]:
                best = (label, ann, r, cm, risk)

    if best:
        print(f"\n# EN YUKSEK YILLIK: {best[0]}")
        print(f"  Yillik: {best[1]:+.2f}% | DD: {best[2]['max_dd']*100:+.1f}%")
        print(f"  $10K -> 5y -> ${best[2]['final']:,.0f}")
        if best[1] >= 50:
            print(f"  ⭐ HEDEF (%50) ULASILDI!")

        # Bu config 3y rolling stress
        print(f"\n# 3y rolling stress: {best[0]}")
        ts = [t for t in all_trades if t["conf"] >= best[3]]
        start = ts[0]["entry_ts"]
        end = ts[-1]["exit_ts"]
        windows = []
        cur = start
        while cur + pd.Timedelta(days=3*365) <= end:
            windows.append((cur, cur + pd.Timedelta(days=3*365)))
            cur += pd.Timedelta(days=60)
        anns = []; dds = []
        for ws, we in windows:
            wt = [t for t in ts if ws <= t["entry_ts"] < we]
            if len(wt) < 10: continue
            r = replay(wt, risk_pct=best[4])
            if r is None: continue
            anns.append(((r["final"]/10000)**(1/3)-1)*100)
            dds.append(r["max_dd"]*100)
        if anns:
            print(f"  {len(anns)} pencere | ortalama yillik: {np.mean(anns):+.2f}% | min: {min(anns):+.1f}% | max: {max(anns):+.1f}%")
            print(f"  Ortalama DD: {np.mean(dds):+.1f}%")
            neg = sum(1 for a in anns if a < 0)
            print(f"  Negatif pencere: {neg}/{len(anns)}")


if __name__ == "__main__":
    main()
