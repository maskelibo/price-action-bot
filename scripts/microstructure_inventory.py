"""Microstructure inventory + 1d-OHLCV proxy edge search.

Goals:
  1. Veri envanteri: 1m/orderbook/liquidation yokluk teyidi + 1d coverage.
  2. Proxy fokus: wide_range bar (HL > 2*ATR) sonrası 1-bar reversal edge.
  3. Volume spike (vol_z > 2.5) + reversal candle.
  4. Tweezer top/bottom rejection wick (mevcut signal'lere ek filtre değil — standalone).
  5. Inside bar after wide bar (compression).

Sayisal cikti: her proxy icin tetiklenme sayisi, ortalama 1-bar/5-bar/10-bar return.
"""
from __future__ import annotations

import os
os.environ['PA_LOG_QUIET'] = '1'

import pandas as pd
import numpy as np
from pathlib import Path

ROOT = Path(r'C:\Users\koray\projeler\Price Action')
DATA = ROOT / 'data' / 'parquet' / 'binance'


def load_symbol(sym: str, tf: str = '1d') -> pd.DataFrame:
    path = DATA / sym / tf
    if not path.exists():
        return pd.DataFrame()
    files = sorted(path.glob('year=*/month=*/data.parquet'))
    if not files:
        return pd.DataFrame()
    dfs = [pd.read_parquet(f) for f in files]
    df = pd.concat(dfs, ignore_index=True).drop_duplicates(subset=['ts']).sort_values('ts').reset_index(drop=True)
    return df


def inventory():
    symbols = sorted([p.name for p in DATA.iterdir() if p.is_dir()])
    print(f'Symbols: {len(symbols)}')
    print(f'Symbols list: {symbols}')
    print()
    header = "{:<12} {:<5} {:<12} {:<12} {:<7} {:<10} {:<6} {:<8}".format(
        'symbol', 'tf', 'first', 'last', 'rows', 'expected', 'gaps', 'MB')
    print(header)
    print('-' * 80)

    total_bytes = 0
    rows_summary = []
    for sym in symbols:
        for tf in ['1d', '4h', '1w']:
            path = DATA / sym / tf
            if not path.exists():
                continue
            files = sorted(path.glob('year=*/month=*/data.parquet'))
            if not files:
                continue
            df = load_symbol(sym, tf)
            first = df['ts'].iloc[0].strftime('%Y-%m-%d')
            last = df['ts'].iloc[-1].strftime('%Y-%m-%d')
            rows = len(df)
            freq = {'1d': '1D', '4h': '4h', '1w': '7D'}[tf]
            full_range = pd.date_range(df['ts'].iloc[0], df['ts'].iloc[-1], freq=freq, tz='UTC')
            expected = len(full_range)
            gaps = expected - rows
            size_b = sum(f.stat().st_size for f in files)
            size_mb = size_b / (1024 * 1024)
            total_bytes += size_b
            print("{:<12} {:<5} {:<12} {:<12} {:<7} {:<10} {:<6} {:<8.3f}".format(
                sym, tf, first, last, rows, expected, gaps, size_mb))
            rows_summary.append({'sym': sym, 'tf': tf, 'rows': rows, 'gaps': gaps})

    print()
    print(f'Total MB: {total_bytes/(1024*1024):.2f}')
    return symbols, rows_summary


def compute_features(df: pd.DataFrame) -> pd.DataFrame:
    """Add ATR14, vol_z20, wide_range, tweezer, inside_bar features."""
    df = df.copy()
    high = df['high']
    low = df['low']
    close = df['close']
    op = df['open']
    prev_close = close.shift(1)
    tr = pd.concat([(high - low), (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(axis=1)
    df['atr14'] = tr.rolling(14).mean()
    df['range'] = high - low
    df['vol_z20'] = (df['volume'] - df['volume'].rolling(20).mean()) / df['volume'].rolling(20).std()
    df['body'] = (close - op).abs()
    df['upper_wick'] = high - df[['open', 'close']].max(axis=1)
    df['lower_wick'] = df[['open', 'close']].min(axis=1) - low
    df['is_bullish'] = (close > op).astype(int)

    # Wide-range bar (range > 2 * ATR)
    df['wide_range'] = (df['range'] > 2.0 * df['atr14']).astype(int)

    # Inside bar (high < prev_high AND low > prev_low)
    df['inside_bar'] = ((high < high.shift(1)) & (low > low.shift(1))).astype(int)

    # Inside bar after wide range
    df['ib_after_wide'] = (df['inside_bar'] & df['wide_range'].shift(1).fillna(0).astype(int)).astype(int)

    # Tweezer top: 2 bars, both have similar highs and big upper wicks
    eps = 0.003  # 0.3 percent tolerance
    df['tweezer_top'] = (((high / high.shift(1) - 1).abs() < eps) & (df['upper_wick'] > df['body']) & (df['upper_wick'].shift(1) > df['body'].shift(1))).astype(int)
    df['tweezer_bottom'] = (((low / low.shift(1) - 1).abs() < eps) & (df['lower_wick'] > df['body']) & (df['lower_wick'].shift(1) > df['body'].shift(1))).astype(int)

    # Volume spike + reversal candle: vol_z > 2.5 AND bar shows reversal (long lower wick OR upper wick > body)
    df['vol_spike'] = (df['vol_z20'] > 2.5).astype(int)
    df['rev_long'] = (df['vol_spike'] & (df['lower_wick'] > 1.5 * df['body']) & (close > op)).astype(int)
    df['rev_short'] = (df['vol_spike'] & (df['upper_wick'] > 1.5 * df['body']) & (close < op)).astype(int)

    # Forward returns
    df['fwd_1'] = close.shift(-1) / close - 1
    df['fwd_5'] = close.shift(-5) / close - 1
    df['fwd_10'] = close.shift(-10) / close - 1

    return df


def proxy_edge_summary(df_all: pd.DataFrame, sym: str) -> list:
    """Return list of dicts with hit-rate stats per proxy signal."""
    out = []

    def stat(name, mask, direction='long'):
        sub = df_all[mask]
        if len(sub) == 0:
            return None
        # Direction-adjusted forward returns: long = raw, short = negated
        sign = 1.0 if direction == 'long' else -1.0
        r1 = (sub['fwd_1'] * sign).dropna()
        r5 = (sub['fwd_5'] * sign).dropna()
        r10 = (sub['fwd_10'] * sign).dropna()
        if len(r5) == 0:
            return None
        return {
            'sym': sym,
            'signal': name,
            'direction': direction,
            'n': int(len(sub)),
            'avg_fwd1_pct': float(r1.mean() * 100),
            'avg_fwd5_pct': float(r5.mean() * 100),
            'avg_fwd10_pct': float(r10.mean() * 100),
            'wr_fwd5_pct': float((r5 > 0).mean() * 100),
            'median_fwd5_pct': float(r5.median() * 100),
        }

    # Baseline (all bars)
    base = stat('BASELINE_all_bars', pd.Series([True] * len(df_all), index=df_all.index), 'long')
    if base is not None:
        out.append(base)

    # Wide range bar followed by reversal (next bar): proxy long after wide-down bar
    wide_down = (df_all['wide_range'] == 1) & (df_all['close'] < df_all['open'])
    wide_up = (df_all['wide_range'] == 1) & (df_all['close'] > df_all['open'])
    out.append(stat('wide_range_DOWN_then_long', wide_down, 'long'))
    out.append(stat('wide_range_UP_then_short', wide_up, 'short'))

    # Volume spike + bullish reversal
    out.append(stat('vol_spike_bull_rev', df_all['rev_long'] == 1, 'long'))
    out.append(stat('vol_spike_bear_rev', df_all['rev_short'] == 1, 'short'))

    # Tweezer
    out.append(stat('tweezer_top', df_all['tweezer_top'] == 1, 'short'))
    out.append(stat('tweezer_bottom', df_all['tweezer_bottom'] == 1, 'long'))

    # Inside bar after wide range (compression)
    out.append(stat('ib_after_wide_then_long', df_all['ib_after_wide'] == 1, 'long'))
    out.append(stat('ib_after_wide_then_short', df_all['ib_after_wide'] == 1, 'short'))

    return [x for x in out if x is not None]


def main():
    print('=' * 80)
    print('1. VERI ENVANTERI')
    print('=' * 80)
    symbols, _ = inventory()

    print()
    print('=' * 80)
    print('2. MICROSTRUCTURE PROXY EDGE (1d OHLCV, all symbols)')
    print('=' * 80)

    all_rows = []
    for sym in symbols:
        df = load_symbol(sym, '1d')
        if df.empty or len(df) < 60:
            continue
        df = compute_features(df)
        all_rows.extend(proxy_edge_summary(df, sym))

    summary = pd.DataFrame(all_rows)
    if summary.empty:
        print('No data')
        return

    print()
    print('--- Per-symbol breakdown ---')
    print(summary.to_string(index=False))

    print()
    print('--- Aggregated by signal (all symbols pooled) ---')
    agg = summary.groupby(['signal', 'direction']).agg(
        n_total=('n', 'sum'),
        avg_fwd1_pct=('avg_fwd1_pct', 'mean'),
        avg_fwd5_pct=('avg_fwd5_pct', 'mean'),
        avg_fwd10_pct=('avg_fwd10_pct', 'mean'),
        wr_fwd5_mean=('wr_fwd5_pct', 'mean'),
    ).reset_index().sort_values('avg_fwd5_pct', ascending=False)
    print(agg.to_string(index=False))

    print()
    print('--- BASELINE for comparison (all bars, long bias) ---')
    base = agg[agg['signal'] == 'BASELINE_all_bars']
    print(base.to_string(index=False))


if __name__ == '__main__':
    main()
