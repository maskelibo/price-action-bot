"""Her stratejinin TEK BASINA (kombine etmeden) 3 yillik getirisi.

$10,000 baslangic. Pencere: 2023-01-01 -> 2026-05-12 (~3.36 yil).
Risk parametreleri: v0.9.7 BALANCED (halt + F&G short-skip + r%4).
Tek fark: drop_strategies ile sadece o tek strateji aktif.

Cikti: tablo + CSV.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ["PA_LOG_QUIET"] = "1"

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from price_action.backtest.lab import ProductionConfig, production_replay
from scripts.v09_optimize_top10 import _gather, TOP_10


def main():
    print("=" * 100)
    print("HER STRATEJI TEK BASINA — 3 YIL (2023-01-01 -> 2026-05-12)")
    print("$10,000 baslangic, BALANCED risk parametreleri (halt + F&G + r%4)")
    print("=" * 100)

    print("\nTrade topluyor...")
    all_trades = []
    for m, c in TOP_10:
        all_trades.extend(_gather(m, c))
    all_trades.sort(key=lambda x: x["entry_ts"])

    start = pd.Timestamp("2023-01-01", tz="UTC")
    end = pd.Timestamp("2026-05-12", tz="UTC")
    window = [t for t in all_trades if start <= t["entry_ts"] < end]
    years = (end - start).total_seconds() / (365.25 * 86400)
    print(f"Pencere sinyal: {len(window)}, sure: {years:.2f} yil\n")

    base_cfg = ProductionConfig.from_yaml("configs/risk_balanced.yaml")
    all_strategy_names = [s for s, _ in TOP_10]

    print(f"{'#':>3} {'Strateji':<32} {'final$':>10} {'toplam%':>9} {'yillik%':>9} {'DD%':>7} {'WR%':>5} {'n':>4}  {'mansion':>15}")
    print("-" * 110)

    rows = []
    for i, (strat_name, _) in enumerate(TOP_10, 1):
        # Diger stratejileri drop et — sadece bu kalir
        other = frozenset(s for s in all_strategy_names if s != strat_name)
        cfg = base_cfg.with_overrides(drop_strategies=other)
        r = production_replay(window, cfg)
        if r is None:
            print(f"  {i:>2} {strat_name:<32} (sinyal yok ya da filter sonrasi bos)")
            continue
        ret = (r.final_equity / 10_000 - 1) * 100
        ann = ((r.final_equity / 10_000) ** (1 / years) - 1) * 100
        # 10K mansion: net dolar tutar
        mansion_str = f"${r.final_equity:,.0f}"
        verdict = ""
        if ann < 0: verdict = "❌"
        elif ann < 5: verdict = "⚠️"
        elif ann < 15: verdict = "✓"
        elif ann < 30: verdict = "⭐"
        else: verdict = "⭐⭐"
        print(f"  {i:>2} {strat_name:<32} {r.final_equity:>10,.0f} {ret:>+8.1f}% {ann:>+8.2f}% {r.max_drawdown*100:>+6.1f}% {r.win_rate*100:>4.0f}% {r.trades:>4}  {mansion_str:>15} {verdict}")
        rows.append((strat_name, r.final_equity, ret, ann, r.max_drawdown * 100, r.win_rate * 100, r.trades))

    # Karsilastirma — KOMBINE (BALANCED tum stratejiler)
    print("-" * 110)
    cfg_full = base_cfg
    r_full = production_replay(window, cfg_full)
    if r_full:
        ann = ((r_full.final_equity / 10_000) ** (1 / years) - 1) * 100
        print(f"  -- KOMBINE BALANCED (10 strat birlikte) {r_full.final_equity:>10,.0f} "
              f"{(r_full.final_equity/10_000-1)*100:>+7.1f}% {ann:>+8.2f}% "
              f"{r_full.max_drawdown*100:>+6.1f}% {r_full.win_rate*100:>4.0f}% {r_full.trades:>4}  "
              f"${r_full.final_equity:,.0f} ⭐⭐⭐")

    # Sirala
    rows.sort(key=lambda x: -x[3])  # yillik desc
    print()
    print("# YILLIK GETIRI SIRALAMASI (en iyi -> en kotu, TEK BASINA)")
    for s, fin, ret, ann, dd, wr, n in rows:
        print(f"  {s:<32} yillik {ann:>+6.2f}%  final ${fin:>8,.0f}  DD {dd:>+5.1f}%  n={n}")

    # CSV
    out = ROOT / "reports" / "v099_per_strategy_3y.csv"
    import csv
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["strateji", "final_dolar", "toplam_pct", "yillik_pct", "DD_pct", "WR_pct", "n_trade"])
        for s, fin, ret, ann, dd, wr, n in rows:
            w.writerow([s, f"{fin:.2f}", f"{ret:.2f}", f"{ann:.2f}", f"{dd:.2f}", f"{wr:.2f}", n])
    print(f"\nCSV: {out}")


if __name__ == "__main__":
    main()
