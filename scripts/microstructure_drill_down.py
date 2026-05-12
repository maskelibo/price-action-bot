"""vol_spike_bull_rev drill-down + threshold sensitivity.

Bulgu: tum semboller havuzunda n=58 olayda avg fwd5 = +5.87% vs baseline +0.30%.
Sorular:
  1. Threshold sensitivity: vol_z 2.0/2.5/3.0 — n vs edge tradeoff.
  2. Yıllara gore dagilim: tek yila ozgu mu, robust mu?
  3. Bootstrap p-value: sansa karsi anlam.
"""
from __future__ import annotations

import os
os.environ['PA_LOG_QUIET'] = '1'

import pandas as pd
import numpy as np
from pathlib import Path

ROOT = Path(r'C:\Users\koray\projeler\Price Action')
DATA = ROOT / 'data' / 'parquet' / 'binance'

np.random.seed(42)


def load_symbol(sym: str, tf: str = '1d') -> pd.DataFrame:
    path = DATA / sym / tf
    if not path.exists():
        return pd.DataFrame()
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
    df['upper_wick'] = high - df[['open', 'close']].max(axis=1)
    df['lower_wick'] = df[['open', 'close']].min(axis=1) - low

    df['fwd_1'] = close.shift(-1) / close - 1
    df['fwd_5'] = close.shift(-5) / close - 1
    df['fwd_10'] = close.shift(-10) / close - 1

    df['year'] = df['ts'].dt.year
    return df


def collect_all():
    symbols = sorted([p.name for p in DATA.iterdir() if p.is_dir()])
    rows = []
    for sym in symbols:
        df = load_symbol(sym, '1d')
        if df.empty or len(df) < 60:
            continue
        df = features(df)
        df['sym'] = sym
        rows.append(df)
    return pd.concat(rows, ignore_index=True)


def main():
    pool = collect_all()
    print(f'Pool rows: {len(pool):,} ({pool["sym"].nunique()} symbols)')
    print(f'Date range: {pool["ts"].min()} -> {pool["ts"].max()}')
    print()

    # Threshold sensitivity for "vol_spike_bull_rev" proxy
    # = vol_z > X AND bullish close AND lower_wick > Y * body
    print('=' * 80)
    print('THRESHOLD SENSITIVITY (vol_spike_bull_rev)')
    print('=' * 80)
    print(f'{"vol_z":<8}{"wick_mult":<12}{"n":<8}{"avg_fwd1":<12}{"avg_fwd5":<12}{"avg_fwd10":<12}{"wr_fwd5":<10}{"median_fwd5":<12}')
    print('-' * 90)

    base_fwd1 = pool['fwd_1'].mean()
    base_fwd5 = pool['fwd_5'].mean()
    base_fwd10 = pool['fwd_10'].mean()
    base_wr = (pool['fwd_5'] > 0).mean()
    print(f'{"BASE":<8}{"-":<12}{len(pool):<8}{base_fwd1*100:<12.4f}{base_fwd5*100:<12.4f}{base_fwd10*100:<12.4f}{base_wr*100:<10.2f}{pool["fwd_5"].median()*100:<12.4f}')
    print()

    for vz_thr in [2.0, 2.5, 3.0, 3.5]:
        for wick_mult in [1.0, 1.5, 2.0]:
            mask = (pool['vol_z20'] > vz_thr) & (pool['close'] > pool['open']) & (pool['lower_wick'] > wick_mult * pool['body'])
            sub = pool[mask]
            n = len(sub)
            if n < 5:
                print(f'{vz_thr:<8.1f}{wick_mult:<12.1f}{n:<8}  ---')
                continue
            f1 = sub['fwd_1'].mean() * 100
            f5 = sub['fwd_5'].mean() * 100
            f10 = sub['fwd_10'].mean() * 100
            wr = (sub['fwd_5'] > 0).mean() * 100
            med = sub['fwd_5'].median() * 100
            print(f'{vz_thr:<8.1f}{wick_mult:<12.1f}{n:<8}{f1:<12.4f}{f5:<12.4f}{f10:<12.4f}{wr:<10.2f}{med:<12.4f}')

    # Year-by-year breakdown for vol_z>2.5 wick>1.5
    print()
    print('=' * 80)
    print('YEAR-BY-YEAR (vol_z>2.5 AND wick>1.5*body AND bullish close)')
    print('=' * 80)
    mask = (pool['vol_z20'] > 2.5) & (pool['close'] > pool['open']) & (pool['lower_wick'] > 1.5 * pool['body'])
    sub = pool[mask]
    grp = sub.groupby('year').agg(
        n=('fwd_5', 'count'),
        avg_fwd5=('fwd_5', lambda x: x.mean() * 100),
        wr_fwd5=('fwd_5', lambda x: (x > 0).mean() * 100),
        median_fwd5=('fwd_5', lambda x: x.median() * 100),
    )
    print(grp.to_string())

    # Bootstrap p-value: kac defa bu kadar veya daha buyuk avg_fwd5 random orneklemde gorulur?
    print()
    print('=' * 80)
    print('BOOTSTRAP p-VALUE (vol_z>2.5 wick>1.5)')
    print('=' * 80)
    observed_fwd5 = sub['fwd_5'].mean()
    n_obs = len(sub)
    n_boot = 20000
    fwd5_all = pool['fwd_5'].dropna().values
    boot_means = np.zeros(n_boot)
    for i in range(n_boot):
        boot_means[i] = np.random.choice(fwd5_all, size=n_obs, replace=False).mean()
    pval = (boot_means >= observed_fwd5).mean()
    print(f'Observed n = {n_obs}, observed avg fwd5 = {observed_fwd5*100:.4f}%')
    print(f'Bootstrap (20k samples of size n from pool) avg fwd5 distribution:')
    print(f'  mean = {boot_means.mean()*100:.4f}%, std = {boot_means.std()*100:.4f}%')
    print(f'  95% CI = [{np.percentile(boot_means, 2.5)*100:.4f}%, {np.percentile(boot_means, 97.5)*100:.4f}%]')
    print(f'  p-value (one-sided) = {pval:.4f}')

    # Per-symbol breakdown
    print()
    print('=' * 80)
    print('PER-SYMBOL DETAIL')
    print('=' * 80)
    g = sub.groupby('sym').agg(
        n=('fwd_5', 'count'),
        avg_fwd5_pct=('fwd_5', lambda x: x.mean() * 100),
        wr_fwd5_pct=('fwd_5', lambda x: (x > 0).mean() * 100),
    )
    print(g.to_string())


if __name__ == '__main__':
    main()
