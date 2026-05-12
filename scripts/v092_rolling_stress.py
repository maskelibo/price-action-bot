"""v0.9.2 — Notional cap 0.30 ile 3y rolling stress test (13 pencere).

v0.9.0/v0.9.1 hedefi: 13 pencerede pozitif tutarlilik
v0.9.2 hedefi: cap 0.30 ile DD profili dususu var mi her pencerede?

Karsilastirma:
  BASELINE (v0.9.1 no cap): yillik ortalama +%53.58, DD -%80
  v0.9.2 cap 0.30        : yillik ortalama ??? , DD ???
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

from scripts.v09_optimize_top10 import _gather, TOP_10
from scripts.v091_fix_test import replay_fixed


def run_rolling(all_trades, label, **kwargs):
    print(f"\n# {label}")
    start = all_trades[0]["entry_ts"]
    end = all_trades[-1]["exit_ts"]
    windows = []
    cur = start
    while cur + pd.Timedelta(days=3 * 365) <= end:
        windows.append((cur, cur + pd.Timedelta(days=3 * 365)))
        cur += pd.Timedelta(days=60)

    print(f"  {'Pencere':<28} {'sinyal':>7} {'final$':>10} {'3y%':>8} {'yIllIk':>8} {'DD':>6} {'WR':>4}")
    anns = []; dds = []; wrs = []; finals = []
    for ws, we in windows:
        wt = [t for t in all_trades if ws <= t["entry_ts"] < we]
        if len(wt) < 10: continue
        r = replay_fixed(wt, risk_pct=0.030, conf_min=0.20,
                         consecutive_loss_n=3, consecutive_loss_pause=5, **kwargs)
        if r is None: continue
        ret = (r["final"]/10000-1)*100
        ann = ((r["final"]/10000)**(1/3)-1)*100
        anns.append(ann); dds.append(r["max_dd"]*100); wrs.append(r["wr"]*100); finals.append(r["final"])
        wlabel = f"{ws.date()}->{we.date()}"
        print(f"  {wlabel:<28} {r['trades']:>7} {r['final']:>10,.0f} {ret:>+7.1f}% {ann:>+7.2f}% {r['max_dd']*100:>+5.0f}% {r['wr']*100:>3.0f}%")
    return anns, dds, wrs, finals


def summarize(anns, dds, wrs, finals, label):
    if not anns:
        print(f"  (sonuc yok)")
        return None
    print(f"\n  # {label} OZET ({len(anns)} pencere):")
    print(f"    Ortalama yIllIk : {np.mean(anns):+.2f}% (std {np.std(anns):.1f})")
    print(f"    Median yIllIk   : {np.median(anns):+.2f}%")
    print(f"    Min/Max yIllIk  : {min(anns):+.1f}% / {max(anns):+.1f}%")
    print(f"    Ortalama DD     : {np.mean(dds):+.1f}%")
    print(f"    Median DD       : {np.median(dds):+.1f}%")
    print(f"    Min/Max DD      : {min(dds):+.0f}% / {max(dds):+.0f}%")
    print(f"    Ortalama WR     : {np.mean(wrs):.1f}%")
    print(f"    Negatif pencere : {sum(1 for a in anns if a < 0)}/{len(anns)}")
    print(f"    %50+ pencere    : {sum(1 for a in anns if a >= 50)}/{len(anns)} ({100*sum(1 for a in anns if a >= 50)/len(anns):.0f}%)")
    print(f"    %100+ pencere   : {sum(1 for a in anns if a >= 100)}/{len(anns)}")
    return {
        "mean_ann": np.mean(anns), "median_ann": np.median(anns),
        "mean_dd": np.mean(dds), "median_dd": np.median(dds),
        "min_dd": min(dds), "max_dd": max(dds),
        "min_ann": min(anns), "max_ann": max(anns),
        "neg": sum(1 for a in anns if a < 0), "n": len(anns),
    }


def main():
    print("=" * 90)
    print("v0.9.2 — 3y ROLLING STRESS (cap 0.30 vs no cap)")
    print("=" * 90)

    print("\nTopluyor (5y data, 10 strateji x 11 sembol)...")
    all_trades = []
    for m, c in TOP_10:
        all_trades.extend(_gather(m, c))
    all_trades.sort(key=lambda x: x["entry_ts"])
    print(f"Toplam sinyal: {len(all_trades)}")

    # Senaryo 1: BASELINE no cap (v0.9.1)
    anns1, dds1, wrs1, finals1 = run_rolling(
        all_trades, "BASELINE v0.9.1 (cap YOK)", max_notional_ratio=None)
    s1 = summarize(anns1, dds1, wrs1, finals1, "BASELINE no cap")

    # Senaryo 2: v0.9.2 cap 0.30
    anns2, dds2, wrs2, finals2 = run_rolling(
        all_trades, "v0.9.2 PRODUCTION (cap 0.30)", max_notional_ratio=0.30)
    s2 = summarize(anns2, dds2, wrs2, finals2, "v0.9.2 cap 0.30")

    # Senaryo 3 (kontrol): cap 0.20
    anns3, dds3, wrs3, finals3 = run_rolling(
        all_trades, "KONTROL (cap 0.20 daha siki)", max_notional_ratio=0.20)
    s3 = summarize(anns3, dds3, wrs3, finals3, "cap 0.20 kontrol")

    # Senaryo 4 (kontrol): cap 0.50
    anns4, dds4, wrs4, finals4 = run_rolling(
        all_trades, "KONTROL (cap 0.50 daha gevsek)", max_notional_ratio=0.50)
    s4 = summarize(anns4, dds4, wrs4, finals4, "cap 0.50 kontrol")

    # Karsilastirma tablosu
    print()
    print("=" * 90)
    print("KARSILASTIRMA — 4 senaryo, 3y rolling ozet")
    print("=" * 90)
    print(f"\n{'Senaryo':<28} {'pencere':>8} {'mean yIllIk':>13} {'median yIllIk':>15} {'mean DD':>9} {'min DD':>9}")
    print("-" * 90)
    for name, s in [("BASELINE no cap (v0.9.1)", s1),
                     ("CAP 0.30 (v0.9.2 prod)", s2),
                     ("CAP 0.20", s3),
                     ("CAP 0.50", s4)]:
        if s is None:
            print(f"  {name:<28} (yok)"); continue
        print(f"  {name:<28} {s['n']:>8} {s['mean_ann']:>+11.2f}% {s['median_ann']:>+13.2f}% {s['mean_dd']:>+7.0f}% {s['min_dd']:>+7.0f}%")

    # Karar yorumu
    print()
    print("=" * 90)
    print("YORUM")
    print("=" * 90)
    if s1 and s2:
        roi_delta = s2['mean_ann'] - s1['mean_ann']
        dd_delta = s2['mean_dd'] - s1['mean_dd']  # daha az negatif daha iyi
        print(f"\n  CAP 0.30 vs no cap:")
        print(f"    Ortalama yIllIk farki: {roi_delta:+.1f}pp")
        print(f"    Ortalama DD farki    : {dd_delta:+.1f}pp (pozitif = DD AZALDI)")
        if roi_delta > 0 and dd_delta > 0:
            print(f"    SONUC: CAP 0.30 hem ROI artirir hem DD dusurur — PRODUCTION LOCK ONAYLI")
        elif roi_delta > 0:
            print(f"    SONUC: CAP 0.30 ROI artirir ama DD ayni — uygulanabilir")
        elif dd_delta > 0:
            print(f"    SONUC: CAP 0.30 ROI'yi dusurur ama DD'yi belirgin azaltir — risk-adj iyilesir")
        else:
            print(f"    SONUC: CAP 0.30 her iki yondan kotu — gozden gecir!")


if __name__ == "__main__":
    main()
