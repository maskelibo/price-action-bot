"""v1 vs v2 — 5y verinin TUM rolling 3-YIL dilimlerinde test.

3-yil pencere = bull+bear+transition hepsini kapsar.
Karar metrigi: Hangisi daha cok dilimde kazanir, ortalama ne?
"""
from __future__ import annotations

import io
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))
sys.path.insert(0, str(ROOT))

from scripts.bot_v2_multi_window import _gather, replay


def main():
    print("Trade'leri topluyor (5y)...")
    all_trades = _gather()
    print(f"Toplam {len(all_trades)} sinyal\n")

    if not all_trades:
        return

    start = all_trades[0]["entry_ts"]
    end = all_trades[-1]["exit_ts"]
    print(f"Veri araligi: {start.date()} -> {end.date()}\n")

    # Rolling 3-year windows, 30-day shift
    windows = []
    cur = start
    three_yr = pd.Timedelta(days=3 * 365)
    while cur + three_yr <= end:
        win_end = cur + three_yr
        windows.append((cur, win_end))
        cur = cur + pd.Timedelta(days=30)

    print(f"Toplam {len(windows)} rolling 3-YIL pencere\n")
    print(f"{'Pencere (3y)':<28} {'v1 final':>10} {'v2 final':>10} {'v1 ret%':>9} {'v2 ret%':>9} {'v1 yIllk':>9} {'v2 yIllk':>9} {'v1 WR':>6} {'v2 WR':>6} {'kazanan':<8}")
    print("-" * 130)

    v1_wins = v2_wins = ties = 0
    v1_total_ret = v2_total_ret = 0.0
    v1_total_annual = v2_total_annual = 0.0
    v1_avg_dd = v2_avg_dd = 0.0
    v1_avg_wr = v2_avg_wr = 0.0
    n_valid = 0

    for ws, we in windows:
        wt = [t for t in all_trades if ws <= t["entry_ts"] < we]
        if len(wt) < 10:
            continue
        r1 = replay(wt, version="v1")
        r2 = replay(wt, version="v2")
        if r1 is None or r2 is None:
            continue
        ret1 = (r1["final"] / 10_000 - 1) * 100
        ret2 = (r2["final"] / 10_000 - 1) * 100

        # 3y compound -> annualized
        ann1 = ((r1["final"] / 10_000) ** (1/3) - 1) * 100
        ann2 = ((r2["final"] / 10_000) ** (1/3) - 1) * 100

        winner = "v2" if ret2 > ret1 else ("v1" if ret1 > ret2 else "tie")
        if winner == "v1":
            v1_wins += 1
        elif winner == "v2":
            v2_wins += 1
        else:
            ties += 1

        v1_total_ret += ret1
        v2_total_ret += ret2
        v1_total_annual += ann1
        v2_total_annual += ann2
        v1_avg_dd += r1["max_dd"]
        v2_avg_dd += r2["max_dd"]
        v1_avg_wr += r1["wr"]
        v2_avg_wr += r2["wr"]
        n_valid += 1

        label = f"{ws.date()}->{we.date()}"
        print(f"{label:<28} ${r1['final']:>9,.0f} ${r2['final']:>9,.0f} {ret1:>+8.1f}% {ret2:>+8.1f}% {ann1:>+8.1f}% {ann2:>+8.1f}% {r1['wr']*100:>5.0f}% {r2['wr']*100:>5.0f}%  {winner}")

    print()
    print("=" * 130)
    print(f"3-YIL PENCERE SONUCU — Toplam {n_valid} pencere")
    print("=" * 130)
    print(f"  v1 kazandi: {v1_wins} pencere ({100*v1_wins/n_valid:.0f}%)")
    print(f"  v2 kazandi: {v2_wins} pencere ({100*v2_wins/n_valid:.0f}%)")
    print(f"  Berabere : {ties} pencere ({100*ties/n_valid:.0f}%)")
    print()
    print(f"Ortalama 3-yil toplam getiri:")
    print(f"  v1: {v1_total_ret/n_valid:+.2f}%")
    print(f"  v2: {v2_total_ret/n_valid:+.2f}%")
    print()
    print(f"Ortalama YILLIK getiri (3y compound):")
    print(f"  v1: {v1_total_annual/n_valid:+.2f}%")
    print(f"  v2: {v2_total_annual/n_valid:+.2f}%")
    print()
    print(f"Ortalama maxDD:")
    print(f"  v1: {v1_avg_dd*100/n_valid:+.1f}%")
    print(f"  v2: {v2_avg_dd*100/n_valid:+.1f}%")
    print()
    print(f"Ortalama WR:")
    print(f"  v1: {v1_avg_wr*100/n_valid:.1f}%")
    print(f"  v2: {v2_avg_wr*100/n_valid:.1f}%")
    print()
    print(f"Risk-adjusted (yillik / |DD|):")
    print(f"  v1: {(v1_total_annual/n_valid) / abs(v1_avg_dd*100/n_valid):.2f}")
    print(f"  v2: {(v2_total_annual/n_valid) / abs(v2_avg_dd*100/n_valid):.2f}")

    print()
    print("=" * 130)
    if v2_wins > v1_wins:
        print(f"🏆 KAZANAN: v2 ({v2_wins}/{n_valid} pencere)")
    elif v1_wins > v2_wins:
        print(f"🏆 KAZANAN: v1 ({v1_wins}/{n_valid} pencere)")
    else:
        print(f"⚖️  BERABERE")

    # $10K projeksiyonu (en iyi 3-yil senaryosu)
    print()
    print("$10K -> 3 YIL projeksiyonu (ortalama):")
    avg_v1_final = 10_000 * (1 + v1_total_ret/n_valid/100)
    avg_v2_final = 10_000 * (1 + v2_total_ret/n_valid/100)
    print(f"  v1: ${avg_v1_final:,.0f}")
    print(f"  v2: ${avg_v2_final:,.0f}")


if __name__ == "__main__":
    main()
