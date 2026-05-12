"""Self-contained backtest: vol_spike_bull_rev strategy on 11 symbols.

Trigger: vol_z20 > 2.5 AND lower_wick > 1.5*body AND close > open
Entry: next bar open
Stop: entry_price - 1.5 * ATR14
Target: 3R (TP) OR 10 bars time-stop
Risk: 3% per trade, $10,000 starting capital, max 8 concurrent

Compare to BASELINE (random long entries with same risk).
"""
from __future__ import annotations

import os
os.environ['PA_LOG_QUIET'] = '1'

import pandas as pd
import numpy as np
from pathlib import Path

ROOT = Path(r'C:\Users\koray\projeler\Price Action')
DATA = ROOT / 'data' / 'parquet' / 'binance'

INITIAL_CAPITAL = 10_000.0
RISK_PCT = 0.03
MAX_CONCURRENT = 8
TP_R = 2.0
TIME_STOP_BARS = 5
ATR_MULT = 2.0

VZ_THRESHOLD = 2.5
WICK_MULT = 1.5


def load_symbol(sym, tf='1d'):
    path = DATA / sym / tf
    files = sorted(path.glob('year=*/month=*/data.parquet'))
    dfs = [pd.read_parquet(f) for f in files]
    df = pd.concat(dfs, ignore_index=True).drop_duplicates(subset=['ts']).sort_values('ts').reset_index(drop=True)
    return df


def features(df):
    df = df.copy()
    high = df['high']; low = df['low']; close = df['close']; op = df['open']
    pc = close.shift(1)
    tr = pd.concat([(high - low), (high - pc).abs(), (low - pc).abs()], axis=1).max(axis=1)
    df['atr14'] = tr.rolling(14).mean()
    df['vol_z20'] = (df['volume'] - df['volume'].rolling(20).mean()) / df['volume'].rolling(20).std()
    df['body'] = (close - op).abs()
    df['lower_wick'] = df[['open', 'close']].min(axis=1) - low
    df['signal'] = ((df['vol_z20'] > VZ_THRESHOLD)
                    & (df['lower_wick'] > WICK_MULT * df['body'])
                    & (close > op)).astype(int)
    return df


def generate_trades(start_date=None, end_date=None):
    """Tum semboller icin vol_spike_bull_rev sinyallerini topla.

    Returns list of trade dicts with:
      entry_ts, exit_ts, entry_price, sl, R, symbol, conf, strategy
    """
    symbols = sorted([p.name for p in DATA.iterdir() if p.is_dir()])
    all_trades = []

    for sym in symbols:
        df = load_symbol(sym, '1d')
        if df.empty or len(df) < 30:
            continue
        df = features(df)
        if start_date is not None:
            df = df[df['ts'] >= pd.Timestamp(start_date, tz='UTC')]
        if end_date is not None:
            df = df[df['ts'] <= pd.Timestamp(end_date, tz='UTC')]
        df = df.reset_index(drop=True)

        sig_idx = df.index[df['signal'] == 1].tolist()
        for i in sig_idx:
            # Entry: next bar open
            if i + 1 >= len(df):
                continue
            entry_bar = df.iloc[i + 1]
            atr = df.iloc[i]['atr14']
            if pd.isna(atr) or atr <= 0:
                continue
            entry_price = entry_bar['open']
            sl = entry_price - ATR_MULT * atr
            tp = entry_price + ATR_MULT * atr * TP_R  # 3R target
            entry_ts = entry_bar['ts']

            # Walk forward
            exit_ts = None
            exit_price = None
            R = None
            for j in range(i + 1, min(i + 1 + TIME_STOP_BARS + 1, len(df))):
                bar = df.iloc[j]
                # Stop hit check (low <= sl)
                if bar['low'] <= sl:
                    exit_ts = bar['ts']
                    exit_price = sl
                    R = -1.0
                    break
                # TP hit check (high >= tp)
                if bar['high'] >= tp:
                    exit_ts = bar['ts']
                    exit_price = tp
                    R = TP_R
                    break
            if exit_ts is None:
                # Time stop at close of last bar
                final_idx = min(i + TIME_STOP_BARS, len(df) - 1)
                bar = df.iloc[final_idx]
                exit_ts = bar['ts']
                exit_price = bar['close']
                R = (exit_price - entry_price) / (entry_price - sl)

            all_trades.append({
                'symbol': sym,
                'entry_ts': entry_ts,
                'exit_ts': exit_ts,
                'entry_price': entry_price,
                'sl': sl,
                'R': R,
                'side': 'long',
                'strategy': 'vol_spike_bull_rev',
                'conf': 0.5,
            })

    return sorted(all_trades, key=lambda t: t['entry_ts'])


def replay(trades, initial_cap=INITIAL_CAPITAL, risk_pct=RISK_PCT, max_conc=MAX_CONCURRENT):
    """Compounding equity replay with max-concurrent gate."""
    equity = initial_cap
    cash = initial_cap
    peak = initial_cap
    max_dd = 0.0
    open_pos = []
    Rs = []
    eq_curve = [initial_cap]
    wins = 0
    n_taken = 0

    for t in trades:
        # Close due
        still = []
        for p in open_pos:
            if p['exit_ts'] <= t['entry_ts']:
                pnl = p['risk'] * p['R']
                cash += pnl
                equity = cash + sum(q['risk'] * 0 for q in still)  # margin not modeled (R-based)
                peak = max(peak, equity)
                dd = (equity - peak) / peak
                if dd < max_dd:
                    max_dd = dd
                Rs.append(p['R'])
                if p['R'] > 0:
                    wins += 1
                eq_curve.append(equity)
            else:
                still.append(p)
        open_pos = still

        if len(open_pos) >= max_conc:
            continue
        risk_amt = equity * risk_pct
        open_pos.append({'exit_ts': t['exit_ts'], 'R': t['R'], 'risk': risk_amt})
        n_taken += 1

    # Close remaining
    open_pos.sort(key=lambda p: p['exit_ts'])
    for p in open_pos:
        pnl = p['risk'] * p['R']
        cash += pnl
        equity = cash
        peak = max(peak, equity)
        dd = (equity - peak) / peak
        if dd < max_dd:
            max_dd = dd
        Rs.append(p['R'])
        if p['R'] > 0:
            wins += 1
        eq_curve.append(equity)

    n_total = len(Rs)
    wr = wins / n_total if n_total > 0 else 0
    avg_r = np.mean(Rs) if Rs else 0
    return {
        'final_equity': equity,
        'total_return_pct': (equity / initial_cap - 1) * 100,
        'max_dd_pct': max_dd * 100,
        'n_trades': n_total,
        'n_taken': n_taken,
        'wr_pct': wr * 100,
        'avg_r': avg_r,
    }


def annualize(result, years):
    if result['final_equity'] <= 0 or years <= 0:
        return 0.0
    return ((result['final_equity'] / INITIAL_CAPITAL) ** (1.0 / years) - 1.0) * 100


def main():
    # 5y in-sample (2021-05 -> 2026-05)
    print('=' * 80)
    print('vol_spike_bull_rev Strategy Backtest')
    print('=' * 80)
    print(f'Risk: {RISK_PCT*100}% per trade | Max concurrent: {MAX_CONCURRENT}')
    print(f'Entry: vol_z>{VZ_THRESHOLD} AND lower_wick>{WICK_MULT}*body AND bullish close')
    print(f'Stop: -{ATR_MULT}*ATR14 | Target: {TP_R}R | Time-stop: {TIME_STOP_BARS} bars')
    print()

    trades = generate_trades()
    print(f'Total signals generated: {len(trades)}')

    # Full 5y window
    print()
    print('--- Full 5y window (2021-05-01 -> 2026-05-08) ---')
    res = replay(trades)
    years = 5.02
    ann = annualize(res, years)
    print(f"n_trade: {res['n_trades']} (taken {res['n_taken']})")
    print(f"final $: {res['final_equity']:,.2f}")
    print(f"total return: {res['total_return_pct']:+.2f}%")
    print(f"annualized: {ann:+.2f}%/y")
    print(f"max DD: {res['max_dd_pct']:+.2f}%")
    print(f"WR: {res['wr_pct']:.1f}%")
    print(f"avg R: {res['avg_r']:+.3f}")

    # 3-year rolling windows (13 windows, 60-day step)
    print()
    print('--- 3y rolling windows (13 windows, 60-day step) ---')
    start = pd.Timestamp('2021-05-15', tz='UTC')
    rows = []
    for w in range(13):
        s = start + pd.Timedelta(days=60 * w)
        e = s + pd.Timedelta(days=365 * 3)
        sub = [t for t in trades if s <= t['entry_ts'] <= e]
        if not sub:
            continue
        r = replay(sub)
        ann_w = annualize(r, 3.0)
        rows.append({
            'window': f"{s.strftime('%Y-%m-%d')} -> {e.strftime('%Y-%m-%d')}",
            'n': r['n_trades'],
            'final$': r['final_equity'],
            'ann_pct': ann_w,
            'dd_pct': r['max_dd_pct'],
            'wr_pct': r['wr_pct'],
        })

    rdf = pd.DataFrame(rows)
    print(rdf.to_string(index=False))
    print()
    print('--- Aggregate ---')
    print(f"Mean annualized: {rdf['ann_pct'].mean():+.2f}%")
    print(f"Median annualized: {rdf['ann_pct'].median():+.2f}%")
    print(f"Min annualized: {rdf['ann_pct'].min():+.2f}%")
    print(f"Max annualized: {rdf['ann_pct'].max():+.2f}%")
    print(f"Mean DD: {rdf['dd_pct'].mean():+.2f}%")
    print(f"Negative windows: {(rdf['ann_pct'] < 0).sum()}/{len(rdf)}")
    print(f"50%+ windows: {(rdf['ann_pct'] >= 50).sum()}/{len(rdf)}")

    # Save trade detail
    out_path = ROOT / 'reports' / 'microstructure_vol_spike_trades.csv'
    pd.DataFrame(trades).to_csv(out_path, index=False)
    print()
    print(f'Trade detail saved: {out_path}')


if __name__ == '__main__':
    main()
