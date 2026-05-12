"""v0.9.4 — Capitulation halt + AGGRESSIVE/DEFENSIVE preset combos.

Onaylanan: S1 (BTC halt) dispersiyon dusurdu, WORST yillik %2.8 -> %20.
Reddedilen: S2 (Chop) — fazla agresif skip.

Test:
  - AGGRESSIVE (r%4) + halt
  - DEFENSIVE (T6 r%3.5) + halt
  - DEFENSIVE + halt + risk %4 (T6 risk artirimi)
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from statistics import mean, median

os.environ["PA_LOG_QUIET"] = "1"

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from price_action.backtest.lab import ProductionConfig, production_replay
from price_action.backtest.regime import compute_btc_capitulation_halt
from scripts.v09_optimize_top10 import _gather, TOP_10


def main():
    print("=" * 110)
    print("v0.9.4 PRESET + CAPITULATION HALT")
    print("=" * 110)

    print("\nTrade topluyor...")
    all_trades = []
    for m, c in TOP_10:
        all_trades.extend(_gather(m, c))
    all_trades.sort(key=lambda x: x["entry_ts"])
    print(f"Toplam: {len(all_trades)}")

    print("Capitulation halt calendar...")
    btc_halt = compute_btc_capitulation_halt()

    start = all_trades[0]["entry_ts"]
    end = all_trades[-1]["exit_ts"]
    windows = []
    cur = start
    while cur + pd.Timedelta(days=3 * 365) <= end:
        windows.append((cur, cur + pd.Timedelta(days=3 * 365)))
        cur += pd.Timedelta(days=60)

    base_prod = ProductionConfig.from_yaml().with_overrides(
        concentration_max_per_symbol_pct=0.20
    )
    cfg_aggr = ProductionConfig.from_yaml("configs/risk_aggressive.yaml")
    cfg_def = ProductionConfig.from_yaml("configs/risk_defensive.yaml")

    scenarios = [
        ("BASELINE production (v0.9.2)",              base_prod),
        ("BASELINE + halt",                            base_prod.with_overrides(btc_halt_calendar=btc_halt)),
        ("AGGRESSIVE (r%4)",                           cfg_aggr),
        ("AGGRESSIVE + halt",                          cfg_aggr.with_overrides(btc_halt_calendar=btc_halt)),
        ("DEFENSIVE (T6 r%3.5)",                       cfg_def),
        ("DEFENSIVE + halt",                           cfg_def.with_overrides(btc_halt_calendar=btc_halt)),
        ("DEFENSIVE r%4 + halt",                       cfg_def.with_overrides(risk_pct=0.040, btc_halt_calendar=btc_halt)),
        ("DEFENSIVE r%4.5 + halt",                     cfg_def.with_overrides(risk_pct=0.045, btc_halt_calendar=btc_halt)),
        ("DEFENSIVE r%5 + halt",                       cfg_def.with_overrides(risk_pct=0.050, btc_halt_calendar=btc_halt)),
        ("AGGRESSIVE r%5 + halt",                      cfg_aggr.with_overrides(risk_pct=0.050, btc_halt_calendar=btc_halt)),
    ]

    print(f"\n{'scenario':<40}  {'yillik':>8}  {'med':>7}  {'min':>7}  {'max':>7}  {'DD':>7}  {'minDD':>7}  {'r-adj':>7}")
    print("-" * 100)

    rated = []
    for name, cfg in scenarios:
        anns, dds = [], []
        for ws, we in windows:
            w = [t for t in all_trades if ws <= t["entry_ts"] < we]
            r = production_replay(w, cfg)
            if r is None: continue
            anns.append(r.annualized(3.0)*100)
            dds.append(r.max_drawdown*100)
        if not anns: continue
        ma, md = mean(anns), mean(dds)
        ra = ma / abs(md) if md != 0 else 0
        marker = ""
        if "BASELINE production" in name:
            marker = " <-- v0.9.2"
        elif ra >= 1.0:
            marker = " ⭐ r-adj>=1.0"
        rated.append((name, ma, md, ra, min(anns), max(anns), median(anns), min(dds)))
        print(f"  {name:<40}  {ma:>+6.1f}%  {median(anns):>+5.1f}%  {min(anns):>+5.1f}%  {max(anns):>+5.1f}%  {md:>+5.0f}%  {min(dds):>+5.0f}%  {ra:>6.3f}{marker}")

    # En iyi risk-adj
    rated.sort(key=lambda x: -x[3])
    print()
    print("# RISK-ADJ siralamasi (en iyi 5)")
    for i, (name, ma, md, ra, mna, mxa, med_a, mnd) in enumerate(rated[:5], 1):
        print(f"  {i}. {name:<40}  yillik {ma:+.1f}% (min {mna:+.1f} max {mxa:+.1f})  DD {md:+.0f}% (worst {mnd:+.0f})  r-adj={ra:.3f}")


if __name__ == "__main__":
    main()
