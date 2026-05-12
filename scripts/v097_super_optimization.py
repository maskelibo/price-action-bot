"""v0.9.7 — SUPER preset optimization (yillik %60+ hedef).

SUPER baseline: AGGRESSIVE (r%4) + funding (00:00 causal)
3y rolling: yillik +%61.3, DD -%37, r-adj 1.67.

Hedef: %65+ yillik, DD <= %37, varsa daha dusurmek.

Varyantlar:
  S0  BASELINE SUPER (AGGR + funding)
  S1  + F&G short-skip <=20
  S2  + F&G short-skip <=15 (daha siki)
  S3  + drop_pairs (10 worst ablation)
  S4  + halt (capitulation overlay)
  S5  + F&G + drop_pairs
  S6  + F&G + halt
  S7  + drop_pairs + halt
  S8  + F&G + drop_pairs + halt
  S9  r%4.5 + funding
  S10 r%5 + funding
  S11 r%4.5 + funding + F&G
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

from price_action.backtest.lab import ProductionConfig, production_replay, _lazy_build_funding_filters
from price_action.backtest.regime import compute_btc_capitulation_halt
from scripts.v09_optimize_top10 import _gather, TOP_10


DROP_PAIRS = frozenset({
    ("anchored_vwap_reversal", "ETH/USDT"),
    ("anchored_vwap_reversal", "LINK/USDT"),
    ("anchored_vwap_reversal", "BTC/USDT"),
    ("pin_bar_round_numbers", "BNB/USDT"),
    ("equal_highs_sweep", "BNB/USDT"),
    ("equal_highs_sweep", "ETH/USDT"),
    ("pin_bar_round_numbers", "BTC/USDT"),
    ("pin_bar_round_numbers", "ADA/USDT"),
    ("equal_highs_sweep", "AVAX/USDT"),
    ("wyckoff_phase_d", "DOT/USDT"),
})


def build_fng_short_skip(thr: int = 20):
    fng = pd.read_csv(ROOT / "data" / "alt_data" / "fng_daily.csv")
    fng["date"] = pd.to_datetime(fng["date"]).dt.date
    return {r["date"]: True for _, r in fng.iterrows()
            if pd.notna(r["value"]) and int(r["value"]) <= thr}


def main():
    print("=" * 110)
    print("v0.9.7 SUPER OPTIMIZATION — yillik %60+ hedef (3y rolling 13 pencere)")
    print("=" * 110)

    print("\nTrade topluyor...")
    all_trades = []
    for m, c in TOP_10:
        all_trades.extend(_gather(m, c))
    all_trades.sort(key=lambda x: x["entry_ts"])
    print(f"Toplam: {len(all_trades)}")

    halt_cal = compute_btc_capitulation_halt()
    fund_long, fund_short = _lazy_build_funding_filters({
        "funding_filter_enabled": True,
        "funding_aggregation_mode": "00:00_only",
    })
    fng_20 = build_fng_short_skip(20)
    fng_15 = build_fng_short_skip(15)

    start = all_trades[0]["entry_ts"]
    end = all_trades[-1]["exit_ts"]
    windows = []
    cur = start
    while cur + pd.Timedelta(days=3 * 365) <= end:
        windows.append((cur, cur + pd.Timedelta(days=3 * 365)))
        cur += pd.Timedelta(days=60)

    base_super = ProductionConfig.from_yaml("configs/risk_super.yaml")

    # Union short-skip variants
    def union_short(*dicts):
        out = {}
        for d in dicts:
            if d: out.update(d)
        return out

    scenarios = [
        ("S0  BASELINE SUPER (AGGR+funding)",
         base_super),
        ("S1  + F&G short <=20",
         base_super.with_overrides(alt_data_skip_short=union_short(fund_short, fng_20))),
        ("S2  + F&G short <=15 (siki)",
         base_super.with_overrides(alt_data_skip_short=union_short(fund_short, fng_15))),
        ("S3  + drop_pairs",
         base_super.with_overrides(drop_pairs=DROP_PAIRS)),
        ("S4  + halt",
         base_super.with_overrides(btc_halt_calendar=halt_cal)),
        ("S5  + F&G <=20 + drop_pairs",
         base_super.with_overrides(alt_data_skip_short=union_short(fund_short, fng_20), drop_pairs=DROP_PAIRS)),
        ("S6  + F&G <=20 + halt",
         base_super.with_overrides(alt_data_skip_short=union_short(fund_short, fng_20), btc_halt_calendar=halt_cal)),
        ("S7  + drop_pairs + halt",
         base_super.with_overrides(drop_pairs=DROP_PAIRS, btc_halt_calendar=halt_cal)),
        ("S8  + F&G + drop_pairs + halt",
         base_super.with_overrides(alt_data_skip_short=union_short(fund_short, fng_20),
                                   drop_pairs=DROP_PAIRS, btc_halt_calendar=halt_cal)),
        ("S9  r%4.5 + funding",
         base_super.with_overrides(risk_pct=0.045)),
        ("S10 r%5 + funding",
         base_super.with_overrides(risk_pct=0.050)),
        ("S11 r%4.5 + funding + F&G <=20",
         base_super.with_overrides(risk_pct=0.045,
                                   alt_data_skip_short=union_short(fund_short, fng_20))),
    ]

    print(f"\n{'scenario':<46}  {'yillik':>8}  {'med':>7}  {'min':>7}  {'max':>7}  {'DD':>5}  {'minDD':>7}  {'r-adj':>6}  {'neg':>4}")
    print("-" * 115)

    rated = []
    for name, cfg in scenarios:
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
        neg = sum(1 for a in anns if a < 0)
        marker = ""
        if "BASELINE" in name: marker = " <-- baseline SUPER"
        elif ma >= 65 and md >= -38: marker = " ⭐⭐ HEDEF %65+ DD<%38"
        elif ma >= 60: marker = " ⭐ ROI>=60"
        rated.append((name, ma, md, ra, min(anns), max(anns), median(anns), min(dds), neg))
        print(f"  {name:<46}  {ma:>+6.1f}%  {median(anns):>+5.1f}%  {min(anns):>+5.1f}%  {max(anns):>+5.1f}%  {md:>+4.0f}%  {min(dds):>+5.0f}%  {ra:>5.3f}  {neg:>3}{marker}")

    print()
    print("# SUPER BASE'den WIN-WIN (ROI artarken DD bozulmayan)")
    s0 = [r for r in rated if "BASELINE" in r[0]][0]
    s0_ma, s0_md = s0[1], s0[2]
    print(f"  S0 baseline: yillik {s0_ma:+.1f}%, DD {s0_md:+.0f}%")
    print(f"  {'scenario':<46}  {'ROI delta':>10}  {'DD delta':>10}  {'verdict':>14}")
    for name, ma, md, ra, *_ in rated:
        if "BASELINE" in name: continue
        roi_d = ma - s0_ma
        dd_d = md - s0_md
        v = ""
        if roi_d > 2 and dd_d > -2:
            v = " ⭐⭐ ROI++ DD~"
        elif roi_d > 0 and dd_d > 0:
            v = " ⭐ WIN-WIN"
        elif roi_d > 0:
            v = " ROI↑"
        elif dd_d > 2:
            v = " DD↓"
        print(f"  {name:<46}  {roi_d:>+8.1f}pp  {dd_d:>+8.1f}pp  {v}")


if __name__ == "__main__":
    main()
