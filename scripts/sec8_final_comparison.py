"""SEC8 final: Crypto champion vs Forex realistic vs Combined portfolio."""
from __future__ import annotations

import os
import sys
from pathlib import Path
from statistics import mean, median

os.environ["PA_LOG_QUIET"] = "1"
import warnings
warnings.filterwarnings("ignore")

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from price_action.backtest.lab import ProductionConfig, production_replay, _lazy_build_funding_filters
from price_action.backtest.regime import compute_btc_capitulation_halt
from scripts.sec7_forex_survey import _gather_forex
from scripts.v09_optimize_top10 import _gather, TOP_10
from scripts.v097_balanced_optimization import DROP_PAIRS, build_fng_short_skip


def realistic_replay(trades, risk_pct=0.01, leverage=30, max_concurrent=10, initial=10000, cooldown_days=1):
    """Forex broker-realistic margin model."""
    trades = sorted(trades, key=lambda t: t['entry_ts'])
    equity = initial
    cash = initial
    open_pos = []
    Rs = []
    last_entry = {}
    peak = initial
    max_dd = 0.0
    for t in trades:
        still = []
        for p in open_pos:
            if p['exit_ts'] <= t['entry_ts']:
                cash += p['margin'] + p['risk'] * p['R']
                equity = cash + sum(q['margin'] for q in still)
                Rs.append(p['R'])
                peak = max(peak, equity)
                dd = (equity - peak) / peak if peak > 0 else 0
                max_dd = min(max_dd, dd)
            else:
                still.append(p)
        open_pos = still
        sl_pct = abs(t['entry_price'] - t['initial_sl']) / t['entry_price']
        if sl_pct <= 0:
            continue
        key = (t['symbol'], t['side'])
        prev = last_entry.get(key)
        if prev is not None and (t['entry_ts'] - prev).days < cooldown_days:
            continue
        if len(open_pos) >= max_concurrent:
            continue
        risk_d = equity * risk_pct
        notional = risk_d / sl_pct
        margin = notional / leverage
        if margin > cash:
            continue
        cash -= margin
        last_entry[key] = t['entry_ts']
        open_pos.append({'exit_ts': t['exit_ts'], 'margin': margin, 'risk': risk_d, 'R': t['R'], 'symbol': t['symbol']})
    for p in open_pos:
        cash += p['margin'] + p['risk'] * p['R']
        Rs.append(p['R'])
    equity = cash
    return {'final': equity, 'max_dd': max_dd, 'n_trades': len(Rs)}


def main() -> None:
    print('Trade topluyor...')
    crypto_trades = []
    for m, c in TOP_10:
        crypto_trades.extend(_gather(m, c))
    crypto_trades.sort(key=lambda x: x['entry_ts'])

    forex_trades = []
    for m, c in TOP_10:
        forex_trades.extend(_gather_forex(m, c))
    forex_trades.sort(key=lambda x: x['entry_ts'])
    print(f'Crypto: {len(crypto_trades)}, Forex: {len(forex_trades)}')

    base = ProductionConfig.from_yaml('configs/risk_balanced.yaml')
    halt_cal = compute_btc_capitulation_halt()
    fund_long, fund_short = _lazy_build_funding_filters({
        'funding_filter_enabled': True,
        'funding_aggregation_mode': '00:00_only',
    })
    fng_short_20 = build_fng_short_skip(20)
    combined_short_skip = {**dict(fund_short or {}), **dict(fng_short_20)}
    cfg_crypto = base.with_overrides(
        alt_data_skip_long=fund_long,
        alt_data_skip_short=combined_short_skip,
        drop_pairs=DROP_PAIRS,
    )

    common_start = max(crypto_trades[0]['entry_ts'], forex_trades[0]['entry_ts'])
    common_end = min(crypto_trades[-1]['exit_ts'], forex_trades[-1]['exit_ts'])
    common_windows = []
    cur = common_start
    while cur + pd.Timedelta(days=3 * 365) <= common_end:
        common_windows.append((cur, cur + pd.Timedelta(days=3 * 365)))
        cur += pd.Timedelta(days=60)
    print(f'Common windows: {len(common_windows)}')

    print()
    print(f"{'scenario':<48} {'yillik':>9} {'med':>7} {'DD':>7} {'r-adj':>7} {'neg':>5}")
    print('-' * 95)

    # Crypto solo
    anns_c = []
    dds_c = []
    for ws, we in common_windows:
        ww_t = [t for t in crypto_trades if ws <= t['entry_ts'] < we]
        r = production_replay(ww_t, cfg_crypto)
        if r is None:
            continue
        anns_c.append(r.annualized(3.0) * 100)
        dds_c.append(r.max_drawdown * 100)
    ma_c = mean(anns_c)
    md_c = mean(dds_c)
    ra_c = ma_c / abs(md_c) if md_c != 0 else 0
    neg_c = sum(1 for a in anns_c if a < 0)
    print(f"  {'Crypto Champion (v0.9.7)':<48} {ma_c:>+8.1f}% {median(anns_c):>+5.1f}% {md_c:>+5.1f}% {ra_c:>6.3f} {neg_c:>3}/{len(anns_c)}")

    # Forex solo realistic
    anns_f = []
    dds_f = []
    for ws, we in common_windows:
        ww_t = [t for t in forex_trades if ws <= t['entry_ts'] < we]
        r = realistic_replay(ww_t, risk_pct=0.01, leverage=30, max_concurrent=10, initial=10000, cooldown_days=1)
        if r is None or r['n_trades'] == 0:
            continue
        ret = r['final'] / 10000 - 1
        ann = (1 + ret) ** (1 / 3.0) - 1
        anns_f.append(ann * 100)
        dds_f.append(r['max_dd'] * 100)
    ma_f = mean(anns_f)
    md_f = mean(dds_f)
    ra_f = ma_f / abs(md_f) if md_f != 0 else 0
    neg_f = sum(1 for a in anns_f if a < 0)
    print(f"  {'Forex Realistic (r%1 + lev 30x)':<48} {ma_f:>+8.1f}% {median(anns_f):>+5.1f}% {md_f:>+5.1f}% {ra_f:>6.3f} {neg_f:>3}/{len(anns_f)}")

    # Combined 50/50
    for c_alloc, f_alloc, label in [
        (0.5, 0.5, 'Combined 50/50 ($5k crypto + $5k forex)'),
        (0.7, 0.3, 'Combined 70/30 ($7k crypto + $3k forex)'),
        (0.3, 0.7, 'Combined 30/70 ($3k crypto + $7k forex)'),
    ]:
        anns = []
        dds = []
        for ws, we in common_windows:
            c_ww = [t for t in crypto_trades if ws <= t['entry_ts'] < we]
            f_ww = [t for t in forex_trades if ws <= t['entry_ts'] < we]
            r_c = production_replay(c_ww, cfg_crypto.with_overrides(initial_capital=10000 * c_alloc))
            r_f = realistic_replay(f_ww, risk_pct=0.01, leverage=30, max_concurrent=10, initial=10000 * f_alloc, cooldown_days=1)
            if r_c is None or r_f is None or r_f['n_trades'] == 0:
                continue
            final = r_c.final_equity + r_f['final']
            ret = final / 10000 - 1
            ann = (1 + ret) ** (1 / 3.0) - 1
            anns.append(ann * 100)
            dd_combined = (r_c.max_drawdown * c_alloc + r_f['max_dd'] * f_alloc) * 100
            dds.append(dd_combined)
        if not anns:
            continue
        ma = mean(anns)
        md = mean(dds)
        ra = ma / abs(md) if md != 0 else 0
        neg = sum(1 for a in anns if a < 0)
        print(f"  {label:<48} {ma:>+8.1f}% {median(anns):>+5.1f}% {md:>+5.1f}% {ra:>6.3f} {neg:>3}/{len(anns)}")


if __name__ == "__main__":
    main()
