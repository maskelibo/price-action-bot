"""v0.9.8 — DYNAMIC preset backtest (confidence-based sizing + leverage).

Karsilastirma:
  BALANCED static (r%4 sabit + 3x lev sabit)
  DYNAMIC v0.9.8 (conf_pct tier'a gore %2/%4/%6/%7 + 3x/4x/5x)

3y rolling 13 pencere + 2023-2026 single pencere.

Bekleyenler:
  - Yuksek conf trade'lerde BUYUK pos -> Eger conf gercekten edge yansitiyorsa ROI ↑
  - Dusuk conf trade'lerde KUCUK pos -> DD ↓ (kotu sinyaller ucuza)
  - Net etki: WIN-WIN bekliyoruz (ama validasyon sart)
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
from price_action.backtest.scoring import normalize_conf_percentile
from scripts.v09_optimize_top10 import _gather, TOP_10


def main():
    print("=" * 110)
    print("v0.9.8 DYNAMIC BACKTEST — confidence-based sizing & leverage")
    print("=" * 110)

    print("\nTrade topluyor...")
    all_trades = []
    for m, c in TOP_10:
        all_trades.extend(_gather(m, c))
    all_trades.sort(key=lambda x: x["entry_ts"])
    print(f"Toplam: {len(all_trades)}")

    # Conf_pct dagilim teshhisi
    print("\n# CONF PERCENTILE DAGILIM (re-normalization etkisi)")
    sample = list(all_trades)  # copy
    normalize_conf_percentile(sample, lookback_days=180)
    pcts = [t.get("conf_pct", t["conf"]) for t in sample]
    buckets = {"<0.25": 0, "0.25-0.50": 0, "0.50-0.75": 0, "0.75-0.90": 0, ">=0.90": 0}
    for p in pcts:
        if p < 0.25: buckets["<0.25"] += 1
        elif p < 0.50: buckets["0.25-0.50"] += 1
        elif p < 0.75: buckets["0.50-0.75"] += 1
        elif p < 0.90: buckets["0.75-0.90"] += 1
        else: buckets[">=0.90"] += 1
    total = len(pcts)
    print(f"  Bucket             | Sayı  | Oran  | Tier")
    for b, n in buckets.items():
        pct = n / total * 100
        if b == "<0.25" or b == "0.25-0.50":
            tier = "%2 risk + 3x lev"
        elif b == "0.50-0.75":
            tier = "%4 risk + 4x lev"
        elif b == "0.75-0.90":
            tier = "%6 risk + 5x lev"
        else:
            tier = "%7 risk + 5x lev"
        print(f"  {b:<18} | {n:>4} | {pct:>4.1f}% | {tier}")

    presets = [
        ("BALANCED v0.9.7 (static)", "configs/risk_balanced.yaml"),
        ("AGGRESSIVE (static r%4)", "configs/risk_aggressive.yaml"),
        ("DYNAMIC v0.9.8 ⭐", "configs/risk_dynamic.yaml"),
    ]

    # 3y rolling 13 pencere
    print("\n# 3Y ROLLING 13 PENCERE")
    print(f"  {'preset':<32} {'yillik':>8} {'med':>7} {'min':>7} {'max':>7} {'DD':>6} {'minDD':>7} {'r-adj':>6}")
    print("-" * 100)

    start = all_trades[0]["entry_ts"]
    end = all_trades[-1]["exit_ts"]
    windows = []
    cur = start
    while cur + pd.Timedelta(days=3 * 365) <= end:
        windows.append((cur, cur + pd.Timedelta(days=3 * 365)))
        cur += pd.Timedelta(days=60)

    for name, yml in presets:
        cfg = ProductionConfig.from_yaml(yml)
        anns, dds = [], []
        for ws, we in windows:
            w = [t for t in all_trades if ws <= t["entry_ts"] < we]
            r = production_replay(w, cfg)
            if r is None: continue
            anns.append(r.annualized(3.0) * 100)
            dds.append(r.max_drawdown * 100)
        if not anns: continue
        ma, md = mean(anns), mean(dds)
        ra = ma / abs(md) if md != 0 else 0
        print(f"  {name:<32} {ma:>+7.1f}% {median(anns):>+6.1f}% {min(anns):>+6.1f}% {max(anns):>+6.1f}% {md:>+5.0f}% {min(dds):>+6.0f}% {ra:>5.3f}")

    # 2023-2026 single
    print("\n# 2023-01-01 → 2026-05-12 single window")
    ws_s = pd.Timestamp("2023-01-01", tz="UTC")
    we_s = pd.Timestamp("2026-05-12", tz="UTC")
    years = (we_s - ws_s).total_seconds() / (365.25 * 86400)
    window = [t for t in all_trades if ws_s <= t["entry_ts"] < we_s]
    print(f"  {'preset':<32} {'final$':>10} {'yillik':>8} {'DD':>7} {'WR':>5} {'n':>4}")
    print("-" * 80)
    for name, yml in presets:
        cfg = ProductionConfig.from_yaml(yml)
        r = production_replay(window, cfg)
        if r is None: continue
        ann = ((r.final_equity / 10_000) ** (1 / years) - 1) * 100
        print(f"  {name:<32} {r.final_equity:>10,.0f} {ann:>+7.2f}% {r.max_drawdown*100:>+6.1f}% {r.win_rate*100:>4.0f}% {r.trades:>4}")


if __name__ == "__main__":
    main()
