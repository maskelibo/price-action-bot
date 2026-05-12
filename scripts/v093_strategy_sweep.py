"""v0.9.3 strategy improvement sweep — DD dusur + ROI artir denemeleri.

Baseline: v0.9.2 + concentration 0.20 (live-realistic)

Test edilenler:
  T1: Drop zayif stratejiler (equal_highs_sweep + cvd_spike_fade + vsa_climax_test)
  T2: Vol-target sizing enable
  T3: Side concentration (max 4 long VEYA 4 short)
  T4: T1 + T2 combo
  T5: T1 + T3 combo
  T6: T1 + T2 + T3 ALL combo

Tum testler 3y rolling 13 pencere uzerinde. Production-realistic
(concentration gate aktif) baz alarak karsilastirilir.
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
    """3y rolling sonuclari."""
    anns, dds, finals = [], [], []
    for ws, we in windows:
        w = [t for t in trades if ws <= t["entry_ts"] < we]
        r = production_replay(w, cfg)
        if r is None:
            continue
        anns.append(r.annualized(3.0) * 100)
        dds.append(r.max_drawdown * 100)
        finals.append(r.final_equity)
    return anns, dds, finals


def summarize(name, anns, dds):
    if not anns:
        return f"  {name:<45}: (yok)"
    pos50 = sum(1 for a in anns if a >= 50)
    neg = sum(1 for a in anns if a < 0)
    return (
        f"  {name:<45}: n={len(anns):>2}  "
        f"ort{mean(anns):>+6.1f}%  med{median(anns):>+6.1f}%  "
        f"min{min(anns):>+6.1f}%  max{max(anns):>+6.1f}%  "
        f"ortDD{mean(dds):>+5.0f}%  minDD{min(dds):>+5.0f}%  "
        f"50+{pos50}/{len(anns)}  neg{neg}"
    )


def main():
    print("=" * 110)
    print("v0.9.3 STRATEGY SWEEP — DD dusur + ROI artir, 3y rolling 13 pencere")
    print("=" * 110)

    print("\nTrade topluyor...")
    all_trades = []
    for m, c in TOP_10:
        all_trades.extend(_gather(m, c))
    all_trades.sort(key=lambda x: x["entry_ts"])
    print(f"Toplam: {len(all_trades)}\n")

    # 3y rolling pencereleri (60-gun adim)
    start = all_trades[0]["entry_ts"]
    end = all_trades[-1]["exit_ts"]
    windows = []
    cur = start
    while cur + pd.Timedelta(days=3 * 365) <= end:
        windows.append((cur, cur + pd.Timedelta(days=3 * 365)))
        cur += pd.Timedelta(days=60)

    # Live-realistic baseline (v0.9.2 + conc 0.20)
    base_cfg = ProductionConfig.from_yaml().with_overrides(
        concentration_max_per_symbol_pct=0.20
    )
    drop_weak = frozenset({"equal_highs_sweep", "cvd_spike_fade", "vsa_climax_test"})

    scenarios = [
        ("BASELINE v0.9.2 + conc 0.20",          base_cfg),
        ("T1: drop weak (equal/cvd/vsa)",        base_cfg.with_overrides(drop_strategies=drop_weak)),
        ("T2: vol-target enable",                 base_cfg.with_overrides(vol_target_enabled=True)),
        ("T3: side concentration max 4",          base_cfg.with_overrides(max_same_side_concurrent=4)),
        ("T3b: side concentration max 3",         base_cfg.with_overrides(max_same_side_concurrent=3)),
        ("T4: T1 + T2 (drop + vol-target)",       base_cfg.with_overrides(drop_strategies=drop_weak, vol_target_enabled=True)),
        ("T5: T1 + T3 (drop + side max 4)",       base_cfg.with_overrides(drop_strategies=drop_weak, max_same_side_concurrent=4)),
        ("T6: T1 + T2 + T3 ALL",                  base_cfg.with_overrides(drop_strategies=drop_weak, vol_target_enabled=True, max_same_side_concurrent=4)),
    ]

    print(f"# 3Y ROLLING 13 PENCERE — yillik ortalama / DD ortalama / dispersiyon")
    print("-" * 110)
    print(f"  {'scenario':<45} {'metrics':>50}")
    print("-" * 110)

    results = {}
    for name, cfg in scenarios:
        anns, dds, finals = rolling_metrics(all_trades, cfg, windows)
        results[name] = (anns, dds, finals)
        print(summarize(name, anns, dds))

    # Karsilastirma — baseline'dan delta
    print()
    print("=" * 110)
    print("# KARSILASTIRMA — baseline'dan delta")
    print("=" * 110)
    base_anns = results["BASELINE v0.9.2 + conc 0.20"][0]
    base_dds = results["BASELINE v0.9.2 + conc 0.20"][1]
    base_mean_ann = mean(base_anns) if base_anns else 0
    base_mean_dd = mean(base_dds) if base_dds else 0

    print(f"\n  {'scenario':<45}  {'ROI delta':>11}  {'DD delta':>11}  {'risk-adj':>9}")
    print("-" * 90)
    for name, _ in scenarios:
        anns, dds, _ = results[name]
        if not anns:
            continue
        ma, md = mean(anns), mean(dds)
        roi_d = ma - base_mean_ann
        dd_d = md - base_mean_dd  # pozitif = DD daha az kotu (iyilesti)
        ra = ma / abs(md) if md != 0 else 0
        marker = ""
        if name.startswith("BASELINE"):
            marker = " <-- baseline"
        elif roi_d > 0 and dd_d > 0:
            marker = " ⭐ HEM ROI ARTTI HEM DD AZALDI"
        elif roi_d > 0:
            marker = " (ROI ↑)"
        elif dd_d > 0:
            marker = " (DD ↓)"
        print(f"  {name:<45}  {roi_d:>+9.1f}pp  {dd_d:>+9.1f}pp  {ra:>8.2f}{marker}")

    # Kazanan analizi
    print()
    print("=" * 110)
    print("# EN IYI SENARYO ARAYISI")
    print("=" * 110)
    # En yuksek risk-adjusted (ortalama yillik / mutlak DD)
    rated = []
    for name, _ in scenarios:
        anns, dds, _ = results[name]
        if not anns:
            continue
        ma, md = mean(anns), mean(dds)
        ra = ma / abs(md) if md != 0 else 0
        rated.append((name, ma, md, ra))
    rated.sort(key=lambda x: -x[3])
    print(f"\n  Risk-adjusted siralamasi (yillik/abs(DD)):")
    for i, (name, ma, md, ra) in enumerate(rated[:5], 1):
        print(f"    {i}. {name:<45}  yillik {ma:+.1f}%  DD {md:+.0f}%  risk-adj={ra:.3f}")


if __name__ == "__main__":
    main()
