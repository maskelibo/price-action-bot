"""v0.9.4 regime filter sweep — Analyst capitulation halt + Researcher B chop suppressor.

Test sirasi (3y rolling 13 pencere + ozellikle WORST/BEST):
  S0: BASELINE v0.9.2 + conc 0.20 (live-realistic, mevcut)
  S1: + BTC capitulation halt (Analyst HYP, ATR%>=6 + EMA200streak>=10 + 90d-DD<=-25)
  S2: + Chop suppressor (Researcher B HYP-REGIME-001, ADX<18 + BBW pct<30 -> skip)
  S3: S1 + S2 (her ikisi)

Beklenti:
  S1: WORST yillik +%14 -> +%30, BEST kucuk dusus, ortalama ROI artar, DD dusur
  S2: Sub-Nis 2026 DD'yi yarilamasi beklenir
  S3: en iyi risk-adj
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from statistics import mean, median

os.environ["PA_LOG_QUIET"] = "1"

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from price_action.backtest.lab import ProductionConfig, production_replay
from price_action.backtest.regime import (
    build_all_chop_calendars,
    compute_btc_capitulation_halt,
)
from scripts.v09_optimize_top10 import _gather, SYMBOLS_11, TOP_10


def rolling_metrics(trades, cfg, windows):
    anns, dds = [], []
    for ws, we in windows:
        w = [t for t in trades if ws <= t["entry_ts"] < we]
        r = production_replay(w, cfg)
        if r is None:
            anns.append(None); dds.append(None); continue
        anns.append(r.annualized(3.0) * 100)
        dds.append(r.max_drawdown * 100)
    return anns, dds


def main():
    print("=" * 110)
    print("v0.9.4 REGIME FILTER SWEEP — capitulation halt + chop suppressor")
    print("=" * 110)

    t0 = time.time()
    print("\nTrade topluyor...")
    all_trades = []
    for m, c in TOP_10:
        all_trades.extend(_gather(m, c))
    all_trades.sort(key=lambda x: x["entry_ts"])
    print(f"Toplam: {len(all_trades)} sinyal ({time.time()-t0:.1f}s)")

    # Regime calendars (bir kez hesapla, cache)
    print("\nBTC capitulation halt calendar uretiliyor...")
    t1 = time.time()
    btc_halt = compute_btc_capitulation_halt()
    halt_days = sum(1 for v in btc_halt.values() if v)
    print(f"  {len(btc_halt)} gun, {halt_days} gun halt aktif ({halt_days/len(btc_halt)*100:.1f}%) — {time.time()-t1:.1f}s")

    print("\nChop calendar uretiliyor (11 sembol)...")
    t2 = time.time()
    chop_cals = build_all_chop_calendars(SYMBOLS_11)
    # Sample stats
    sample_sym = "BTC/USDT"
    sample_cal = chop_cals[sample_sym]
    chop_pct = sum(1 for v in sample_cal.values() if v == "chop") / len(sample_cal) * 100
    transition_pct = sum(1 for v in sample_cal.values() if v == "transition") / len(sample_cal) * 100
    trend_pct = sum(1 for v in sample_cal.values() if v == "trend") / len(sample_cal) * 100
    print(f"  {len(chop_cals)} sembol cache'lendi — BTC sample: chop {chop_pct:.0f}% / trans {transition_pct:.0f}% / trend {trend_pct:.0f}%  ({time.time()-t2:.1f}s)")

    # Pencereler
    start = all_trades[0]["entry_ts"]
    end = all_trades[-1]["exit_ts"]
    windows = []
    cur = start
    while cur + pd.Timedelta(days=3 * 365) <= end:
        windows.append((cur, cur + pd.Timedelta(days=3 * 365)))
        cur += pd.Timedelta(days=60)

    # WORST/BEST pencereler (Analyst tanimi)
    worst = (pd.Timestamp("2022-05-10", tz="UTC"), pd.Timestamp("2025-05-10", tz="UTC"))
    best = (pd.Timestamp("2022-07-09", tz="UTC"), pd.Timestamp("2025-07-09", tz="UTC"))

    # Scenarios
    base_cfg = ProductionConfig.from_yaml().with_overrides(
        concentration_max_per_symbol_pct=0.20,
    )

    scenarios = [
        ("S0 BASELINE (v0.9.2 + conc 0.20)",
         base_cfg),
        ("S1 + BTC capitulation halt (Analyst)",
         base_cfg.with_overrides(btc_halt_calendar=btc_halt)),
        ("S2 + chop suppressor (Researcher B)",
         base_cfg.with_overrides(chop_calendars=chop_cals)),
        ("S3 BOTH (halt + chop)",
         base_cfg.with_overrides(btc_halt_calendar=btc_halt, chop_calendars=chop_cals)),
    ]

    # 3y rolling — ortalama
    print()
    print("=" * 110)
    print("# 3Y ROLLING 13 PENCERE — ortalama yillik / DD")
    print("=" * 110)
    print(f"  {'scenario':<42}  {'ort.yil':>9}  {'med':>8}  {'min':>7}  {'max':>8}  {'ortDD':>7}  {'minDD':>7}  {'r-adj':>7}")
    print("-" * 110)

    summary = {}
    for name, cfg in scenarios:
        anns, dds = rolling_metrics(all_trades, cfg, windows)
        anns_f = [a for a in anns if a is not None]
        dds_f = [d for d in dds if d is not None]
        ma = mean(anns_f); md = mean(dds_f)
        ra = ma / abs(md) if md != 0 else 0
        summary[name] = {"anns": anns_f, "dds": dds_f}
        print(f"  {name:<42}  {ma:>+7.1f}%  {median(anns_f):>+6.1f}%  {min(anns_f):>+5.1f}%  {max(anns_f):>+6.1f}%  {md:>+5.0f}%  {min(dds_f):>+5.0f}%  {ra:>6.3f}")

    # WORST ve BEST pencere ozel
    print()
    print("=" * 110)
    print("# WORST (2022-05) vs BEST (2022-07) — Analyst pencerelerinde etki")
    print("=" * 110)
    print(f"  {'scenario':<42}  {'WORST yil':>10}  {'WORST DD':>10}  {'BEST yil':>10}  {'BEST DD':>9}")
    print("-" * 110)
    for name, cfg in scenarios:
        w_trades = [t for t in all_trades if worst[0] <= t["entry_ts"] < worst[1]]
        b_trades = [t for t in all_trades if best[0] <= t["entry_ts"] < best[1]]
        wr = production_replay(w_trades, cfg)
        br = production_replay(b_trades, cfg)
        wa = wr.annualized(3.0) * 100 if wr else float("nan")
        wd = wr.max_drawdown * 100 if wr else float("nan")
        ba = br.annualized(3.0) * 100 if br else float("nan")
        bd = br.max_drawdown * 100 if br else float("nan")
        print(f"  {name:<42}  {wa:>+8.1f}%  {wd:>+8.1f}%  {ba:>+8.1f}%  {bd:>+7.1f}%")

    # Karsilastirma — baseline'dan delta
    print()
    print("=" * 110)
    print("# DELTA — baseline'dan fark")
    print("=" * 110)
    base = summary["S0 BASELINE (v0.9.2 + conc 0.20)"]
    base_ann = mean(base["anns"]); base_dd = mean(base["dds"])
    print(f"\n  {'scenario':<42}  {'ROI delta':>11}  {'DD delta':>11}  {'r-adj-yon':>10}")
    print("-" * 80)
    for name in [n for n, _ in scenarios]:
        s = summary[name]
        ma = mean(s["anns"]); md = mean(s["dds"])
        roi_d = ma - base_ann
        dd_d = md - base_dd  # pozitif = DD daha az kotu
        marker = ""
        if name.startswith("S0"):
            marker = " <-- baseline"
        elif roi_d > 0 and dd_d > 0:
            marker = " ⭐ HEM ROI ARTTI HEM DD AZALDI"
        elif roi_d > 0:
            marker = " (ROI ↑)"
        elif dd_d > 0:
            marker = " (DD ↓)"
        print(f"  {name:<42}  {roi_d:>+9.1f}pp  {dd_d:>+9.1f}pp{marker}")


if __name__ == "__main__":
    main()
