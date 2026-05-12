"""v0.9.3 — Option D: T6 config + farkli risk_pct seviyeleri.

T6 (drop weak + vol-target + side max 4) DD'yi -%23'e dusurmustu.
Bu DD payi varken risk_pct'i artirarak ROI'yi nasil geri kazaniriz?

Test edilenler:
  - Baseline (v0.9.2 + conc 0.20) risk %3, %4, %5
  - T6 risk %3, %3.5, %4, %4.5, %5, %5.5, %6
  - T6 vol-target enable + vol_max_factor 2.0 (low-vol gunlerde daha buyuk)

Karsilastirma: ayni DD budget'inda en yuksek ROI hangisinde?
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from statistics import mean, median, stdev

os.environ["PA_LOG_QUIET"] = "1"

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from price_action.backtest.lab import ProductionConfig, production_replay
from scripts.v09_optimize_top10 import _gather, TOP_10


def rolling_metrics(trades, cfg, windows):
    anns, dds = [], []
    for ws, we in windows:
        w = [t for t in trades if ws <= t["entry_ts"] < we]
        r = production_replay(w, cfg)
        if r is None:
            continue
        anns.append(r.annualized(3.0) * 100)
        dds.append(r.max_drawdown * 100)
    return anns, dds


def main():
    print("=" * 110)
    print("v0.9.3 OPTION D — T6 risk_pct sweep")
    print("=" * 110)

    print("\nTrade topluyor...")
    all_trades = []
    for m, c in TOP_10:
        all_trades.extend(_gather(m, c))
    all_trades.sort(key=lambda x: x["entry_ts"])
    print(f"Toplam: {len(all_trades)}\n")

    start = all_trades[0]["entry_ts"]
    end = all_trades[-1]["exit_ts"]
    windows = []
    cur = start
    while cur + pd.Timedelta(days=3 * 365) <= end:
        windows.append((cur, cur + pd.Timedelta(days=3 * 365)))
        cur += pd.Timedelta(days=60)

    base_cfg = ProductionConfig.from_yaml().with_overrides(
        concentration_max_per_symbol_pct=0.20,
    )
    drop_weak = frozenset({"equal_highs_sweep", "cvd_spike_fade", "vsa_climax_test"})

    def t6(risk: float, vol_max: float = 1.50) -> ProductionConfig:
        return base_cfg.with_overrides(
            risk_pct=risk,
            drop_strategies=drop_weak,
            vol_target_enabled=True,
            vol_max_factor=vol_max,
            max_same_side_concurrent=4,
        )

    def base(risk: float) -> ProductionConfig:
        return base_cfg.with_overrides(risk_pct=risk)

    scenarios = [
        # Baseline farkli risk seviyeleri (ref)
        ("BASELINE r%3.0",                base(0.030)),
        ("BASELINE r%4.0",                base(0.040)),
        ("BASELINE r%5.0",                base(0.050)),
        # T6 farkli risk seviyeleri
        ("T6 r%3.0 (orijinal)",           t6(0.030)),
        ("T6 r%3.5",                      t6(0.035)),
        ("T6 r%4.0",                      t6(0.040)),
        ("T6 r%4.5",                      t6(0.045)),
        ("T6 r%5.0",                      t6(0.050)),
        ("T6 r%5.5",                      t6(0.055)),
        ("T6 r%6.0",                      t6(0.060)),
        # T6 vol_max_factor 2.0 — low vol'de daha buyuk
        ("T6 r%4 vol_max 2.0",            t6(0.040, vol_max=2.0)),
        ("T6 r%5 vol_max 2.0",            t6(0.050, vol_max=2.0)),
        ("T6 r%6 vol_max 2.0",            t6(0.060, vol_max=2.0)),
    ]

    results = {}
    print(f"  {'scenario':<32}  {'yillik':>9}  {'med':>8}  {'min':>7}  {'max':>8}  {'DD ort':>7}  {'DD min':>7}  {'risk-adj':>9}")
    print("-" * 100)
    for name, cfg in scenarios:
        anns, dds = rolling_metrics(all_trades, cfg, windows)
        results[name] = (anns, dds)
        if not anns:
            print(f"  {name:<32}  (yok)"); continue
        ma, md = mean(anns), mean(dds)
        ra = ma / abs(md) if md != 0 else 0
        marker = ""
        if name.startswith("BASELINE r%3"):
            marker = " <-- v0.9.2 production"
        elif ra > 1.0:
            marker = " ⭐ r-adj > 1"
        print(f"  {name:<32}  {ma:>+7.1f}%  {median(anns):>+6.1f}%  {min(anns):>+5.1f}%  {max(anns):>+6.1f}%  {md:>+5.0f}%  {min(dds):>+5.0f}%  {ra:>8.3f}{marker}")

    # 5y compound projeksiyon — en iyi 3 senaryo
    print()
    print("=" * 110)
    print("# 5Y COMPOUND PROJEKSIYONU (en iyi ve baseline)")
    print("=" * 110)

    rated = []
    for name in results:
        anns, dds = results[name]
        if not anns:
            continue
        ma, md = mean(anns), mean(dds)
        ra = ma / abs(md) if md != 0 else 0
        rated.append((name, ma, md, ra))

    print(f"\n  {'scenario':<32}  {'yillik':>8}  {'realistic (-20%)':>17}  {'5y backtest':>13}  {'5y realistic':>13}")
    print("-" * 100)
    rated.sort(key=lambda x: -x[3])
    show = []
    # baseline ref
    for name in results:
        if "BASELINE r%3.0" in name:
            anns, dds = results[name]
            ma = mean(anns); md = mean(dds)
            show.append((name, ma, md, ma/abs(md) if md != 0 else 0))
    # T6 best 3
    t6_rated = [r for r in rated if r[0].startswith("T6")]
    show.extend(t6_rated[:5])

    for name, ma, md, ra in show:
        bt_5y = (1 + ma/100) ** 5 * 10000
        live_rate = ma * 0.8 / 100
        live_5y = (1 + live_rate) ** 5 * 10000
        print(f"  {name:<32}  {ma:>+7.1f}%  {ma*0.8:>+15.1f}%  ${bt_5y:>11,.0f}  ${live_5y:>11,.0f}")

    # Sonuc
    print()
    print("=" * 110)
    print("# SONUC — T6'nin DD payi nereye kadar gider?")
    print("=" * 110)
    print()
    print("  Baseline DD: -%39  -> T6 r%3 DD: -%23  -> T6 r%X DD baseline'a esit oldugu nokta?")
    for name in ["T6 r%4.0", "T6 r%4.5", "T6 r%5.0", "T6 r%5.5", "T6 r%6.0"]:
        if name in results:
            anns, dds = results[name]
            if anns:
                ma, md = mean(anns), mean(dds)
                print(f"  {name}: yillik {ma:+.1f}%, DD {md:+.0f}%")


if __name__ == "__main__":
    main()
