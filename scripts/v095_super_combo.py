"""v0.9.5 SUPER combo — alt-data + ablation drops + capitulation halt + AGGRESSIVE risk.

Onaylanan kazanc'lari kombinleyelim:
  1. Ablation (Analyst): drop_pairs 10 en kotu hucre  -> +%11pp / -%5pp DD
  2. Alt-data (Researcher): funding both-side filter   -> +%18pp / nötr DD
  3. Capitulation halt (Analyst v0.9.4): dispersiyon  -> min pencere +%17pp
  4. AGGRESSIVE risk_pct %4 (v0.9.3 sweep)             -> +%8pp / -%2pp DD

Hedef: r-adj > 1.5, yıllık > %60, DD < -%30, min pencere > +%20.
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

# Ablation drop_pairs (Analyst karar)
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


def build_funding_filters():
    """Alt-data funding both-side filter (high pos -> long skip, deep neg -> short skip)."""
    p = ROOT / "data" / "alt_data" / "funding_BTCUSDT.csv"
    df = pd.read_csv(p)
    df["ts"] = pd.to_datetime(df["ts"], utc=True, format="ISO8601")
    df["date"] = df["ts"].dt.date
    daily = df.groupby("date")["fundingRate"].mean().reset_index()

    long_skip = {}
    short_skip = {}
    for _, r in daily.iterrows():
        v = r["fundingRate"]
        if pd.isna(v):
            continue
        if v > 0.0001:  # overheated long -> contrarian skip
            long_skip[r["date"]] = True
        if v < -0.0001:  # overshort -> contrarian skip
            short_skip[r["date"]] = True
    return long_skip, short_skip


def main():
    print("=" * 110)
    print("v0.9.5 SUPER COMBO — alt-data + drop_pairs + halt + AGGRESSIVE risk")
    print("=" * 110)

    print("\nTrade topluyor...")
    all_trades = []
    for m, c in TOP_10:
        all_trades.extend(_gather(m, c))
    all_trades.sort(key=lambda x: x["entry_ts"])
    print(f"Toplam: {len(all_trades)}")

    print("Capitulation halt + funding filter calendar...")
    btc_halt = compute_btc_capitulation_halt()
    fund_long_skip, fund_short_skip = build_funding_filters()
    print(f"  halt {sum(1 for v in btc_halt.values() if v)}/{len(btc_halt)} gun")
    print(f"  funding long-skip {len(fund_long_skip)}, short-skip {len(fund_short_skip)} gun")

    start = all_trades[0]["entry_ts"]
    end = all_trades[-1]["exit_ts"]
    windows = []
    cur = start
    while cur + pd.Timedelta(days=3 * 365) <= end:
        windows.append((cur, cur + pd.Timedelta(days=3 * 365)))
        cur += pd.Timedelta(days=60)

    base_prod = ProductionConfig.from_yaml().with_overrides(
        concentration_max_per_symbol_pct=0.20,
    )
    cfg_aggr = ProductionConfig.from_yaml("configs/risk_aggressive.yaml")
    cfg_bal = ProductionConfig.from_yaml("configs/risk_balanced.yaml")

    scenarios = [
        ("BASELINE prod (v0.9.2)",                base_prod),
        ("AGGRESSIVE (r%4)",                      cfg_aggr),
        ("BALANCED (r%4 + halt)",                 cfg_bal),
        ("PROD + drop_pairs",                     base_prod.with_overrides(drop_pairs=DROP_PAIRS)),
        ("PROD + funding both",                   base_prod.with_overrides(alt_data_skip_long=fund_long_skip, alt_data_skip_short=fund_short_skip)),
        ("PROD + drop_pairs + funding",           base_prod.with_overrides(drop_pairs=DROP_PAIRS, alt_data_skip_long=fund_long_skip, alt_data_skip_short=fund_short_skip)),
        ("AGGR + funding (replicate alt-data)",   cfg_aggr.with_overrides(alt_data_skip_long=fund_long_skip, alt_data_skip_short=fund_short_skip)),
        ("AGGR + drop_pairs",                     cfg_aggr.with_overrides(drop_pairs=DROP_PAIRS)),
        ("AGGR + drop_pairs + funding",           cfg_aggr.with_overrides(drop_pairs=DROP_PAIRS, alt_data_skip_long=fund_long_skip, alt_data_skip_short=fund_short_skip)),
        ("BALANCED + drop_pairs",                 cfg_bal.with_overrides(drop_pairs=DROP_PAIRS)),
        ("BALANCED + funding",                    cfg_bal.with_overrides(alt_data_skip_long=fund_long_skip, alt_data_skip_short=fund_short_skip)),
        ("BALANCED + drop_pairs + funding",       cfg_bal.with_overrides(drop_pairs=DROP_PAIRS, alt_data_skip_long=fund_long_skip, alt_data_skip_short=fund_short_skip)),
        ("AGGR + drop_pairs + funding + halt ⭐", cfg_aggr.with_overrides(drop_pairs=DROP_PAIRS, alt_data_skip_long=fund_long_skip, alt_data_skip_short=fund_short_skip, btc_halt_calendar=btc_halt)),
    ]

    print(f"\n{'scenario':<48}  {'yillik':>8}  {'med':>7}  {'min':>7}  {'max':>8}  {'DD':>6}  {'minDD':>6}  {'r-adj':>7}")
    print("-" * 110)

    results = []
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
        results.append((name, ma, md, ra, min(anns), max(anns), median(anns), min(dds)))
        marker = ""
        if "BASELINE" in name:
            marker = " <-- v0.9.2"
        elif ra >= 1.5:
            marker = " ⭐⭐ r-adj>=1.5"
        elif ra >= 1.2:
            marker = " ⭐ r-adj>=1.2"
        print(f"  {name:<48}  {ma:>+6.1f}%  {median(anns):>+5.1f}%  {min(anns):>+5.1f}%  {max(anns):>+6.1f}%  {md:>+4.0f}%  {min(dds):>+4.0f}%  {ra:>6.3f}{marker}")

    # En iyi 5
    print()
    print("# EN YUKSEK RISK-ADJ 5")
    results.sort(key=lambda x: -x[3])
    for i, (name, ma, md, ra, mna, mxa, med_a, mnd) in enumerate(results[:5], 1):
        print(f"  {i}. {name:<48}  yillik {ma:+6.1f}%  DD {md:+4.0f}%  r-adj={ra:.3f}  (min/max {mna:+.1f}/{mxa:+.1f})")


if __name__ == "__main__":
    main()
