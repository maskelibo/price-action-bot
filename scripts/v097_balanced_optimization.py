"""v0.9.7 — BALANCED preset optimization sweep.

Hedef: BALANCED cercevesini koruyarak (halt + risk %4) ROI artir, DD dusur.

Varyantlar:
  B0  BASELINE BALANCED (halt + r%4)
  B1  + funding filter (causal 00:00 only)
  B2  + drop_pairs (ablation 10 worst)
  B3  + F&G short-skip (<=20 contrarian)
  B4  r%4.5 + halt
  B5  r%5 + halt + cap %25 (daha siki cap, daha yuksek risk)
  B6  + funding + drop_pairs
  B7  + funding + F&G short-skip
  B8  + funding + drop_pairs + F&G
  B9  + funding + drop_pairs + F&G + vol-target
  B10 + funding + drop_pairs + F&G + side_max_4
  B11 r%4.5 + halt + funding + drop_pairs
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


def build_fng_short_skip(threshold: int = 20):
    """F&G value <= threshold gunlerinde short skip (extreme fear contrarian)."""
    fng = pd.read_csv(ROOT / "data" / "alt_data" / "fng_daily.csv")
    fng["date"] = pd.to_datetime(fng["date"]).dt.date
    return {r["date"]: True for _, r in fng.iterrows()
            if pd.notna(r["value"]) and int(r["value"]) <= threshold}


def main():
    print("=" * 110)
    print("v0.9.7 BALANCED OPTIMIZATION — ROI ARTIR DD DUSUR (3y rolling 13 pencere)")
    print("=" * 110)

    print("\nTrade topluyor...")
    all_trades = []
    for m, c in TOP_10:
        all_trades.extend(_gather(m, c))
    all_trades.sort(key=lambda x: x["entry_ts"])
    print(f"Toplam: {len(all_trades)}")

    print("Filter calendars...")
    halt_cal = compute_btc_capitulation_halt()
    fund_long, fund_short = _lazy_build_funding_filters({
        "funding_filter_enabled": True,
        "funding_aggregation_mode": "00:00_only",
    })
    fng_short_20 = build_fng_short_skip(20)
    print(f"  halt: {sum(1 for v in halt_cal.values() if v)}/{len(halt_cal)} gun")
    print(f"  funding long-skip: {len(fund_long or {})}, short-skip: {len(fund_short or {})}")
    print(f"  F&G short-skip (<=20): {len(fng_short_20)} gun")

    start = all_trades[0]["entry_ts"]
    end = all_trades[-1]["exit_ts"]
    windows = []
    cur = start
    while cur + pd.Timedelta(days=3 * 365) <= end:
        windows.append((cur, cur + pd.Timedelta(days=3 * 365)))
        cur += pd.Timedelta(days=60)
    print(f"  Pencere sayisi: {len(windows)}")

    # Base BALANCED config
    base_bal = ProductionConfig.from_yaml("configs/risk_balanced.yaml")

    # Compose short_skip union (funding + F&G)
    fund_short_dict = dict(fund_short or {})
    fng_short_dict = dict(fng_short_20)
    combined_short_skip = {**fund_short_dict, **fng_short_dict}

    scenarios = [
        ("B0  BASELINE (halt + r%4)",
         base_bal),
        ("B1  + funding",
         base_bal.with_overrides(alt_data_skip_long=fund_long, alt_data_skip_short=fund_short)),
        ("B2  + drop_pairs",
         base_bal.with_overrides(drop_pairs=DROP_PAIRS)),
        ("B3  + F&G short-skip <=20",
         base_bal.with_overrides(alt_data_skip_short=fng_short_dict)),
        ("B4  r%4.5 + halt",
         base_bal.with_overrides(risk_pct=0.045)),
        ("B5  r%5 + halt + cap 0.25",
         base_bal.with_overrides(risk_pct=0.050, max_notional_pct_equity=0.25)),
        ("B6  + funding + drop_pairs",
         base_bal.with_overrides(alt_data_skip_long=fund_long, alt_data_skip_short=fund_short, drop_pairs=DROP_PAIRS)),
        ("B7  + funding + F&G short-skip",
         base_bal.with_overrides(alt_data_skip_long=fund_long, alt_data_skip_short=combined_short_skip)),
        ("B8  + funding + drop_pairs + F&G",
         base_bal.with_overrides(alt_data_skip_long=fund_long, alt_data_skip_short=combined_short_skip, drop_pairs=DROP_PAIRS)),
        ("B9  + funding + drop_pairs + F&G + vol-target",
         base_bal.with_overrides(alt_data_skip_long=fund_long, alt_data_skip_short=combined_short_skip,
                                 drop_pairs=DROP_PAIRS, vol_target_enabled=True)),
        ("B10 + funding + drop_pairs + F&G + side_max_4",
         base_bal.with_overrides(alt_data_skip_long=fund_long, alt_data_skip_short=combined_short_skip,
                                 drop_pairs=DROP_PAIRS, max_same_side_concurrent=4)),
        ("B11 r%4.5 + halt + funding + drop_pairs",
         base_bal.with_overrides(risk_pct=0.045, alt_data_skip_long=fund_long, alt_data_skip_short=fund_short,
                                 drop_pairs=DROP_PAIRS)),
        ("B12 r%5 + halt + funding + drop_pairs + cap 0.25",
         base_bal.with_overrides(risk_pct=0.050, max_notional_pct_equity=0.25,
                                 alt_data_skip_long=fund_long, alt_data_skip_short=fund_short, drop_pairs=DROP_PAIRS)),
    ]

    print(f"\n{'scenario':<54}  {'yillik':>8}  {'med':>7}  {'min':>7}  {'max':>7}  {'DD':>6}  {'minDD':>7}  {'r-adj':>7}  {'neg':>4}")
    print("-" * 120)

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
        if "BASELINE" in name:
            marker = " <-- baseline"
        elif ra >= 1.5:
            marker = " ⭐⭐ r-adj>=1.5"
        elif ra >= 1.2:
            marker = " ⭐ r-adj>=1.2"
        rated.append((name, ma, md, ra, min(anns), max(anns), median(anns), min(dds), neg))
        print(f"  {name:<54}  {ma:>+6.1f}%  {median(anns):>+5.1f}%  {min(anns):>+5.1f}%  {max(anns):>+5.1f}%  {md:>+4.0f}%  {min(dds):>+5.0f}%  {ra:>6.3f}  {neg:>3}{marker}")

    # Sirala — risk-adj
    print()
    print("# RISK-ADJ SIRALAMA (en iyi 5)")
    rated.sort(key=lambda x: -x[3])
    for i, (name, ma, md, ra, mna, mxa, med_a, mnd, neg) in enumerate(rated[:5], 1):
        print(f"  {i}. {name:<54}  yillik {ma:+6.1f}%  DD {md:+4.0f}%  r-adj={ra:.3f}  (min {mna:+.1f} / max {mxa:+.1f})  neg={neg}")

    # Hedef: BALANCED'dan ROI ↑ + DD ↓ olan secenekler
    print()
    print("# HEDEF: HEM ROI ARTAN HEM DD AZALAN (BASELINE B0'a gore)")
    b0 = [r for r in rated if "BASELINE" in r[0]][0]
    b0_ma, b0_md = b0[1], b0[2]
    print(f"  B0 baseline: yillik {b0_ma:+.1f}%, DD {b0_md:+.0f}%")
    print()
    print(f"  {'scenario':<54}  {'ROI delta':>10}  {'DD delta':>10}  {'r-adj':>7}  {'verdict':>8}")
    for name, ma, md, ra, *_ in rated:
        if "BASELINE" in name: continue
        roi_d = ma - b0_ma
        dd_d = md - b0_md  # pozitif = DD daha az kotu (iyilesti)
        if roi_d > 0 and dd_d > 0:
            verdict = " ⭐⭐ WIN-WIN"
        elif roi_d > 2 and dd_d > -2:
            verdict = " ⭐ ROI+,DD~"
        elif dd_d > 2 and roi_d > -3:
            verdict = " DD↓"
        else:
            verdict = ""
        print(f"  {name:<54}  {roi_d:>+8.1f}pp  {dd_d:>+8.1f}pp  {ra:>6.3f}{verdict}")


if __name__ == "__main__":
    main()
