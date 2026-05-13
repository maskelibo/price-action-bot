"""SEC10.C: Recent Regime Guard test."""
from __future__ import annotations

import os
import sys
from pathlib import Path
from statistics import mean
from datetime import timedelta

os.environ["PA_LOG_QUIET"] = "1"
import warnings
warnings.filterwarnings("ignore")

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from price_action.backtest.lab import ProductionConfig, production_replay, _lazy_build_funding_filters
from price_action.backtest.regime import compute_btc_capitulation_halt
from scripts.v09_optimize_top10 import _gather, TOP_10
from scripts.v097_balanced_optimization import DROP_PAIRS, build_fng_short_skip


def replay_with_recent_guard(trades_in, cfg, lookback_days=30, R_thr=-3.0, halve_for_days=14, verbose=False):
    trades = sorted(trades_in, key=lambda t: t['entry_ts'])
    if not trades:
        return None
    equity = cfg.initial_capital
    cash = cfg.initial_capital
    open_pos = []
    Rs = []
    eq_curve = [cfg.initial_capital]
    last_d = trades[0]['entry_ts'].date()
    last_w = trades[0]['entry_ts'].isocalendar()[1]
    last_m = trades[0]['entry_ts'].month
    daily_anchor = weekly_anchor = monthly_anchor = cfg.initial_capital
    blocked_until = None
    last_entry = {}
    consec_loss = 0
    cool_until = None
    peak = cfg.initial_capital
    halve_until = None
    closed_trades = []
    n_halved = 0

    def close_due(now):
        nonlocal cash, equity, peak, consec_loss, cool_until
        still = []
        for p in open_pos:
            if p['exit_ts'] <= now:
                pnl = p['risk'] * p['R']
                cash += p['margin'] + pnl
                equity = cash + sum(q['margin'] for q in still)
                peak = max(peak, equity)
                Rs.append(p['R'])
                eq_curve.append(equity)
                closed_trades.append((p['exit_ts'], p['R']))
                if pnl < 0:
                    consec_loss += 1
                    if cfg.consecutive_loss_n and consec_loss >= cfg.consecutive_loss_n:
                        cool_until = p['exit_ts'] + timedelta(days=cfg.consecutive_loss_pause_days)
                        consec_loss = 0
                else:
                    consec_loss = 0
            else:
                still.append(p)
        open_pos[:] = still

    for t in trades:
        close_due(t['entry_ts'])
        if cool_until and t['entry_ts'] < cool_until:
            continue
        d_key = t['entry_ts'].date()
        if cfg.btc_halt_calendar is not None and cfg.btc_halt_calendar.get(d_key, False):
            continue
        if cfg.alt_data_skip_long is not None and t['side'] == 'long' and cfg.alt_data_skip_long.get(d_key, False):
            continue
        if cfg.alt_data_skip_short is not None and t['side'] == 'short' and cfg.alt_data_skip_short.get(d_key, False):
            continue
        if cfg.drop_pairs and (t['strategy'], t['symbol']) in cfg.drop_pairs:
            continue
        if t['conf'] < cfg.conf_min:
            continue
        key = (t['symbol'], t['side'])
        prev = last_entry.get(key)
        if prev is not None and (t['entry_ts'] - prev).days < cfg.same_symbol_side_cooldown_days:
            continue
        cd = t['entry_ts'].date()
        cw = t['entry_ts'].isocalendar()[1]
        cm = t['entry_ts'].month
        if cd != last_d:
            daily_anchor = equity
            last_d = cd
        if cw != last_w:
            weekly_anchor = equity
            last_w = cw
        if cm != last_m:
            monthly_anchor = equity
            last_m = cm
        if blocked_until and t['entry_ts'] < blocked_until:
            continue
        if (daily_anchor - equity) / max(daily_anchor, 1) >= cfg.daily_dd:
            blocked_until = t['entry_ts'] + timedelta(days=1)
            continue
        if (weekly_anchor - equity) / max(weekly_anchor, 1) >= cfg.weekly_dd:
            blocked_until = t['entry_ts'] + timedelta(days=7)
            continue
        if (monthly_anchor - equity) / max(monthly_anchor, 1) >= cfg.monthly_dd:
            blocked_until = t['entry_ts'] + timedelta(days=30)
            continue
        if len(open_pos) >= cfg.max_concurrent:
            continue

        # Recent regime guard
        cutoff = t['entry_ts'] - timedelta(days=lookback_days)
        recent_R = sum(R for ets, R in closed_trades if ets >= cutoff)
        risk_modifier = 1.0
        if halve_until and t['entry_ts'] < halve_until:
            risk_modifier = 0.5
            n_halved += 1
        if recent_R < R_thr:
            halve_until = t['entry_ts'] + timedelta(days=halve_for_days)
            if risk_modifier == 1.0:
                risk_modifier = 0.5
                n_halved += 1

        sl_pct = abs(t['entry_price'] - t['initial_sl']) / t['entry_price']
        if sl_pct <= 0:
            continue
        risk_d = equity * cfg.risk_pct * risk_modifier
        notional = risk_d / sl_pct
        if cfg.max_notional_pct_equity is not None:
            cap = equity * cfg.max_notional_pct_equity
            if notional > cap:
                notional = cap
                risk_d = notional * sl_pct
        margin = notional / max(cfg.leverage, 1.0)
        if margin > cash:
            continue
        cash -= margin
        last_entry[key] = t['entry_ts']
        open_pos.append({'exit_ts': t['exit_ts'], 'margin': margin, 'risk': risk_d, 'R': t['R']})

    for p in open_pos:
        cash += p['margin'] + p['risk'] * p['R']
        Rs.append(p['R'])
        eq_curve.append(cash)
    equity = cash
    peak = eq_curve[0]
    max_dd = 0.0
    for v in eq_curve:
        if v > peak:
            peak = v
        dd = (v - peak) / peak if peak > 0 else 0
        if dd < max_dd:
            max_dd = dd
    return {'final': equity, 'max_dd': max_dd, 'n_trades': len(Rs), 'n_halved': n_halved}


def main() -> None:
    print("Trade topluyor...")
    trades = []
    for m, c in TOP_10:
        trades.extend(_gather(m, c))
    trades.sort(key=lambda x: x['entry_ts'])

    base = ProductionConfig.from_yaml('configs/risk_balanced.yaml')
    halt_cal = compute_btc_capitulation_halt()
    fund_long, fund_short = _lazy_build_funding_filters({'funding_filter_enabled': True, 'funding_aggregation_mode': '00:00_only'})
    fng_short_20 = build_fng_short_skip(20)
    combined_short_skip = {**dict(fund_short or {}), **dict(fng_short_20)}
    cfg = base.with_overrides(
        alt_data_skip_long=fund_long,
        alt_data_skip_short=combined_short_skip,
        drop_pairs=DROP_PAIRS,
        btc_halt_calendar=halt_cal,
    )

    start = trades[0]['entry_ts']
    end = trades[-1]['exit_ts']
    windows = []
    cur = start
    while cur + pd.Timedelta(days=3 * 365) <= end:
        windows.append((cur, cur + pd.Timedelta(days=3 * 365)))
        cur += pd.Timedelta(days=60)
    print(f'Pencere: {len(windows)}')

    print(f"\n{'scenario':<55} {'yillik':>8} {'DD':>7} {'r-adj':>7} {'neg':>5} {'halve':>6}")
    print('-' * 100)

    # Production replay baseline
    anns_b, dds_b = [], []
    for ws, we in windows:
        ww_t = [t for t in trades if ws <= t['entry_ts'] < we]
        r = production_replay(ww_t, cfg)
        if r is None:
            continue
        anns_b.append(r.annualized(3.0) * 100)
        dds_b.append(r.max_drawdown * 100)
    ma_b = mean(anns_b)
    md_b = mean(dds_b)
    ra_b = ma_b / abs(md_b) if md_b != 0 else 0
    print(f'  {"Baseline (production_replay)":<55} {ma_b:>+7.1f}% {md_b:>+5.1f}% {ra_b:>6.3f} {sum(1 for a in anns_b if a<0):>3}/{len(anns_b)}')

    # Manual sanity: guard off
    anns, dds = [], []
    for ws, we in windows:
        ww_t = [t for t in trades if ws <= t['entry_ts'] < we]
        r = replay_with_recent_guard(ww_t, cfg, lookback_days=30, R_thr=-999, halve_for_days=0)
        if r is None or r['n_trades'] == 0:
            continue
        ret = r['final'] / cfg.initial_capital - 1
        ann = (1 + ret) ** (1 / 3.0) - 1
        anns.append(ann * 100)
        dds.append(r['max_dd'] * 100)
    ma = mean(anns)
    md = mean(dds)
    ra = ma / abs(md) if md != 0 else 0
    print(f'  {"Manual replay sanity (guard off)":<55} {ma:>+7.1f}% {md:>+5.1f}% {ra:>6.3f} {sum(1 for a in anns if a<0):>3}/{len(anns)}')

    # Guard variants
    guards = [
        (30, -3.0, 14, 'Guard: 30d sum<-3R -> halve 14d'),
        (30, -2.0, 14, 'Guard: 30d sum<-2R -> halve 14d'),
        (30, -5.0, 30, 'Guard: 30d sum<-5R -> halve 30d (gevsek)'),
        (60, -5.0, 30, 'Guard: 60d sum<-5R -> halve 30d'),
        (14, -2.0, 7, 'Guard: 14d sum<-2R -> halve 7d (siki)'),
        (30, -1.0, 7, 'Guard: 30d sum<-1R -> halve 7d (cok siki)'),
    ]
    for lb, rthr, hd, name in guards:
        anns, dds, halv = [], [], []
        for ws, we in windows:
            ww_t = [t for t in trades if ws <= t['entry_ts'] < we]
            r = replay_with_recent_guard(ww_t, cfg, lookback_days=lb, R_thr=rthr, halve_for_days=hd)
            if r is None or r['n_trades'] == 0:
                continue
            ret = r['final'] / cfg.initial_capital - 1
            ann = (1 + ret) ** (1 / 3.0) - 1
            anns.append(ann * 100)
            dds.append(r['max_dd'] * 100)
            halv.append(r['n_halved'])
        if not anns:
            continue
        ma = mean(anns)
        md = mean(dds)
        ra = ma / abs(md) if md != 0 else 0
        print(f'  {name:<55} {ma:>+7.1f}% {md:>+5.1f}% {ra:>6.3f} {sum(1 for a in anns if a<0):>3}/{len(anns)} {mean(halv):>5.0f}')


if __name__ == "__main__":
    main()
