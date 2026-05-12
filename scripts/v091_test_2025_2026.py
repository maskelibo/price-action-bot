"""v0.9.1 production config — 2025-05-09 -> 2026-05-09 (1 yil) testi.

Mevcut konfig (v0.9.1):
  - 11 sembol
  - Top 10 strateji
  - Risk %3 sabit
  - Conf>=0.20
  - 3-loss cool-down (5 gun)
  - Multi-target TP engine + 1.0 ATR trail
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
from scripts.v09_dd_protect import replay_protected


def main():
    print("=" * 80)
    print("v0.9.1 PRODUCTION — 2025-05-09 -> 2026-05-09 (1 yil)")
    print("=" * 80)

    print("\nTopluyor (5y data, 1y filtreli)...")
    all_trades = []
    for m, c in TOP_10:
        all_trades.extend(_gather(m, c))
    all_trades.sort(key=lambda x: x["entry_ts"])

    # 1 yil filtre
    win_start = pd.Timestamp("2025-05-09", tz="UTC")
    win_end = pd.Timestamp("2026-05-09", tz="UTC")
    one_year = [t for t in all_trades if win_start <= t["entry_ts"] < win_end]
    print(f"Toplam 5y sinyal: {len(all_trades)}")
    print(f"1 yil pencere ({win_start.date()} -> {win_end.date()}) sinyal: {len(one_year)}\n")

    # Strateji bazinda dagilim
    print("# 1y sinyal dagilimi (strateji bazinda):")
    from collections import Counter
    strat_count = Counter(t["strategy"] for t in one_year)
    for s, n in strat_count.most_common():
        print(f"  {s:<32} {n} sinyal")
    print()

    # Symbol dagilimi
    print("# 1y sinyal dagilimi (sembol bazinda):")
    sym_count = Counter(t["symbol"] for t in one_year)
    for s, n in sym_count.most_common():
        print(f"  {s:<14} {n} sinyal")
    print()

    # Side dagilimi
    print("# 1y sinyal dagilimi (yon):")
    side_count = Counter(t["side"] for t in one_year)
    for s, n in side_count.items():
        print(f"  {s:<6} {n} sinyal")
    print()

    # Replay v0.9.1 production config
    print("=" * 80)
    print("# v0.9.1 PRODUCTION REPLAY (1 yil)")
    print("=" * 80)
    r = replay_protected(
        one_year,
        risk_pct=0.030,
        conf_min=0.20,
        consecutive_loss_n=3,
        consecutive_loss_pause=5,
    )
    if r is None:
        print("Sonuc yok")
        return

    ret = (r["final"]/10000-1)*100
    print(f"\nFinal equity: ${r['final']:,.2f}")
    print(f"1 yil getiri: {ret:+.2f}%")
    print(f"Trade sayisi: {r['trades']}")
    print(f"Win rate: {r['wr']*100:.1f}%")
    print(f"Max DD: {r['max_dd']*100:+.1f}%")
    print(f"$10K -> 1y -> ${r['final']:,.0f}")
    print(f"$200 -> 1y -> ${200 * r['final']/10000:,.0f}")

    # Karsilastirma: farkli risk seviyeleri
    print()
    print("# Farkli risk seviyeleri (1 yil):")
    print(f"{'Risk':<8} {'final$':>10} {'getiri%':>9} {'maxDD':>7} {'WR':>5} {'trade':>5}")
    print("-" * 50)
    for risk in [0.010, 0.015, 0.020, 0.025, 0.030, 0.035, 0.040]:
        rr = replay_protected(
            one_year, risk_pct=risk, conf_min=0.20,
            consecutive_loss_n=3, consecutive_loss_pause=5,
        )
        if rr is None: continue
        rret = (rr["final"]/10000-1)*100
        print(f"%{risk*100:>5.1f}  {rr['final']:>10,.0f} {rret:>+8.1f}% {rr['max_dd']*100:>+5.0f}% {rr['wr']*100:>3.0f}% {rr['trades']:>5}")

    # Aylar
    print()
    print("# Aylik dagilim (production config):")
    if one_year:
        # Manuel aylik replay
        eq = 10_000.0
        m_anchor = 10_000.0
        m = one_year[0]["entry_ts"].month
        y = one_year[0]["entry_ts"].year
        # Tek tek calistirmak yerine, ayni replay kullan ama parça parça
        # Daha basit: trade'leri ay bazinda topla
        from collections import defaultdict
        m_trades = defaultdict(list)
        for t in one_year:
            mk = (t["entry_ts"].year, t["entry_ts"].month)
            m_trades[mk].append(t)
        running_equity = 10_000.0
        for (yr, mo), trs in sorted(m_trades.items()):
            wins = sum(1 for t in trs if t["R"] > 0)
            avg_r = np.mean([t["R"] for t in trs])
            sum_r = sum(t["R"] for t in trs)
            print(f"  {yr}-{mo:02d}: {len(trs)} trade, {wins} win, avg R {avg_r:+.2f}, sum R {sum_r:+.2f}")


if __name__ == "__main__":
    main()
