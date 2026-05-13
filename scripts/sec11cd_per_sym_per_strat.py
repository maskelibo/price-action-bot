"""SEC11.C + SEC11.D: Per-symbol custom config + Strategy weight optimization.

Hipotez:
  C - BTC vs altcoin farklı vol regime → farklı risk profile fayda eder
  D - TOP_10 stratejilerinin Sharpe-rank weight ile capital allocation

v1.1.0 baseline (monthly_dd=0.08): yıllık +%37.5 / DD -%31.8 / r-adj 1.178
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from statistics import mean, median

os.environ["PA_LOG_QUIET"] = "1"
import warnings
warnings.filterwarnings("ignore")

import pandas as pd
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from price_action.backtest.lab import ProductionConfig, production_replay, _lazy_build_funding_filters
from price_action.backtest.regime import compute_btc_capitulation_halt
from scripts.v09_optimize_top10 import _gather, TOP_10
from scripts.v097_balanced_optimization import DROP_PAIRS, build_fng_short_skip


def main() -> None:
    print("Trade topluyor...")
    trades = []
    for m, c in TOP_10:
        trades.extend(_gather(m, c))
    trades.sort(key=lambda x: x['entry_ts'])
    print(f"Total: {len(trades)}")

    base = ProductionConfig.from_yaml('configs/risk_balanced.yaml')
    halt_cal = compute_btc_capitulation_halt()
    fund_long, fund_short = _lazy_build_funding_filters({'funding_filter_enabled': True, 'funding_aggregation_mode': '00:00_only'})
    fng_short_20 = build_fng_short_skip(20)
    combined_short_skip = {**dict(fund_short or {}), **dict(fng_short_20)}
    cfg_v11 = base.with_overrides(
        alt_data_skip_long=fund_long,
        alt_data_skip_short=combined_short_skip,
        drop_pairs=DROP_PAIRS,
        monthly_dd=0.08,  # v1.1.0
    )

    start = trades[0]['entry_ts']
    end = trades[-1]['exit_ts']
    windows = []
    cur = start
    while cur + pd.Timedelta(days=3 * 365) <= end:
        windows.append((cur, cur + pd.Timedelta(days=3 * 365)))
        cur += pd.Timedelta(days=60)
    print(f"Pencere: {len(windows)}")

    def replay_pool(pool, cfg):
        anns, dds = [], []
        for ws, we in windows:
            ww_t = [t for t in pool if ws <= t['entry_ts'] < we]
            r = production_replay(ww_t, cfg)
            if r is None:
                continue
            anns.append(r.annualized(3.0) * 100)
            dds.append(r.max_drawdown * 100)
        if not anns:
            return None
        return mean(anns), mean(dds), len(anns), sum(1 for a in anns if a < 0)

    # =================== SEC11.C: Per-symbol drop ablation ===================
    print(f"\n{'=' * 80}")
    print("SEC11.C: Per-symbol drop ablation (en kötü sembolleri çıkarmak edge artırır mı?)")
    print('=' * 80)

    # Per-symbol mean R
    sym_stats = {}
    for sym in set(t['symbol'] for t in trades):
        sym_trades = [t for t in trades if t['symbol'] == sym]
        Rs = [t['R'] for t in sym_trades]
        sym_stats[sym] = {'n': len(Rs), 'mR': sum(Rs) / len(Rs), 'sumR': sum(Rs)}

    sym_sorted = sorted(sym_stats.items(), key=lambda x: x[1]['mR'])
    print(f"\nPer-symbol mean R sıralı:")
    for sym, s in sym_sorted:
        print(f"  {sym:<15} n={s['n']:>4} mR={s['mR']:+.3f} sumR={s['sumR']:+.1f}")

    print(f"\n{'config':<55} {'yillik':>8} {'DD':>7} {'r-adj':>7} {'neg':>5}")
    print('-' * 90)

    # Baseline (TOP_10 + BALANCED+F&G+v1.1)
    res = replay_pool(trades, cfg_v11)
    print(f"  {'Baseline (v1.1.0 monthly_dd=0.08)':<55} {res[0]:>+7.1f}% {res[1]:>+5.1f}% {res[0]/abs(res[1]):>6.3f} {res[3]:>3}/{res[2]}")

    # Drop worst 1/2/3 symbols
    for n_drop in [1, 2, 3]:
        worst_syms = set(sym for sym, _ in sym_sorted[:n_drop])
        kept = [t for t in trades if t['symbol'] not in worst_syms]
        res = replay_pool(kept, cfg_v11)
        if res:
            print(f"  Drop worst {n_drop} ({','.join(sorted(worst_syms))[:25]:<25}): {res[0]:>+7.1f}% {res[1]:>+5.1f}% {res[0]/abs(res[1]):>6.3f} {res[3]:>3}/{res[2]}")

    # Drop bottom 30% sym×strat (mevcut DROP_PAIRS=10, deneyelim 15/20)
    print()
    cell_stats = {}
    for t in trades:
        k = (t['strategy'], t['symbol'])
        if k not in cell_stats:
            cell_stats[k] = []
        cell_stats[k].append(t['R'])
    cells = [(k, sum(rs) / len(rs), len(rs)) for k, rs in cell_stats.items() if len(rs) >= 10]
    cells.sort(key=lambda x: x[1])

    for n_drop in [15, 20, 25, 30]:
        worst_cells = set(k for k, _, _ in cells[:n_drop])
        kept_trades = [t for t in trades if (t['strategy'], t['symbol']) not in worst_cells]
        # NOT: DROP_PAIRS zaten 10 cell drop'luyor production_replay içinde
        # Burada additional drop'la replay
        cfg_extra = cfg_v11.with_overrides(drop_pairs=worst_cells | DROP_PAIRS)
        res = replay_pool(trades, cfg_extra)
        if res:
            print(f"  Drop worst {n_drop} cell + DROP_PAIRS ({len(worst_cells | DROP_PAIRS)} total): {res[0]:>+7.1f}% {res[1]:>+5.1f}% {res[0]/abs(res[1]):>6.3f} {res[3]:>3}/{res[2]}")

    # =================== SEC11.D: Per-strategy ablation ===================
    print(f"\n{'=' * 80}")
    print("SEC11.D: Per-strategy ablation (en zayıf stratejileri çıkar)")
    print('=' * 80)

    strat_stats = {}
    for s_name, _ in TOP_10:
        s_trades = [t for t in trades if t['strategy'] == s_name]
        Rs = [t['R'] for t in s_trades]
        if Rs:
            strat_stats[s_name] = {'n': len(Rs), 'mR': sum(Rs) / len(Rs), 'sumR': sum(Rs)}

    strat_sorted = sorted(strat_stats.items(), key=lambda x: x[1]['mR'])
    print(f"\nPer-strategy mean R sıralı:")
    for s, st in strat_sorted:
        print(f"  {s:<35} n={st['n']:>4} mR={st['mR']:+.3f} sumR={st['sumR']:+.1f}")

    print(f"\n{'config':<55} {'yillik':>8} {'DD':>7} {'r-adj':>7} {'neg':>5}")
    print('-' * 90)
    res = replay_pool(trades, cfg_v11)
    print(f"  {'Baseline (TOP_10)':<55} {res[0]:>+7.1f}% {res[1]:>+5.1f}% {res[0]/abs(res[1]):>6.3f} {res[3]:>3}/{res[2]}")

    for n_drop in [1, 2, 3]:
        worst_strats = set(s for s, _ in strat_sorted[:n_drop])
        kept = [t for t in trades if t['strategy'] not in worst_strats]
        res = replay_pool(kept, cfg_v11)
        if res:
            print(f"  Drop worst {n_drop} strats ({','.join(sorted(worst_strats))[:25]:<25}): {res[0]:>+7.1f}% {res[1]:>+5.1f}% {res[0]/abs(res[1]):>6.3f} {res[3]:>3}/{res[2]}")

    # Top-N keep
    for n_keep in [3, 5, 7]:
        top_strats = set(s for s, _ in strat_sorted[-n_keep:])  # top n
        kept = [t for t in trades if t['strategy'] in top_strats]
        res = replay_pool(kept, cfg_v11)
        if res:
            print(f"  Keep TOP {n_keep} strats ({','.join(sorted(top_strats))[:25]:<25}): {res[0]:>+7.1f}% {res[1]:>+5.1f}% {res[0]/abs(res[1]):>6.3f} {res[3]:>3}/{res[2]}")


if __name__ == "__main__":
    main()
