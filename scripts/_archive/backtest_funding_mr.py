"""Funding Rate Mean-Reversion backtest runner — real Binance data."""
import warnings
warnings.filterwarnings('ignore')

from datetime import datetime, timezone
import pandas as pd
import numpy as np
import ccxt
import time
import sys

sys.path.insert(0, 'src')

symbols_perp = ['BTC/USDT:USDT', 'ETH/USDT:USDT', 'SOL/USDT:USDT', 'BNB/USDT:USDT', 'XRP/USDT:USDT']
ex = ccxt.binance({'options': {'defaultType': 'future'}, 'enableRateLimit': True})

start_ms = int(datetime(2023, 5, 10, tzinfo=timezone.utc).timestamp() * 1000)
end_dt = datetime(2026, 5, 8, tzinfo=timezone.utc)

print('Fetching data...')
datasets = {}
for sym in symbols_perp:
    # 4h OHLCV
    ohlcv_raw = []
    since = start_ms
    while True:
        chunk = ex.fetch_ohlcv(sym, '4h', since=since, limit=1000)
        if not chunk:
            break
        ohlcv_raw.extend(chunk)
        if len(chunk) < 1000:
            break
        since = chunk[-1][0] + 4*3600*1000
        time.sleep(0.1)
    ohlcv_df = pd.DataFrame(ohlcv_raw, columns=['ts_ms','open','high','low','close','volume'])
    ohlcv_df['ts'] = pd.to_datetime(ohlcv_df['ts_ms'], unit='ms', utc=True)
    ohlcv_df['venue'] = 'binance'
    ohlcv_df['symbol'] = sym
    ohlcv_df['timeframe'] = '4h'
    ohlcv_df = ohlcv_df[['ts','open','high','low','close','volume','venue','symbol','timeframe']]

    # 8h funding
    fr_raw = []
    since = start_ms
    while True:
        chunk = ex.fetch_funding_rate_history(sym, since=since, limit=1000)
        if not chunk:
            break
        fr_raw.extend(chunk)
        if len(chunk) < 1000:
            break
        since = chunk[-1]['timestamp'] + 8*3600*1000
        time.sleep(0.1)
    fr_rows = []
    for r in fr_raw:
        mp = float(r['info'].get('markPrice') or 0)
        fr_rows.append({
            'ts': pd.Timestamp(r['timestamp'], unit='ms', tz='UTC'),
            'funding_rate': float(r['fundingRate']),
            'mark_price': mp,
        })
    fr_df = pd.DataFrame(fr_rows)

    datasets[sym] = (ohlcv_df, fr_df)
    print(f"  {sym}: {len(ohlcv_df)} 4h bars, {len(fr_df)} funding records")

print("Data fetch complete.")

from price_action.strategies.funding_mean_reversion import (
    FundingMeanReversionStrategy,
    _default_manifest,
    merge_funding_to_ohlcv,
)
from price_action.backtest.engine import BacktestEngine

manifest = _default_manifest()
strat = FundingMeanReversionStrategy(manifest)
engine = BacktestEngine()

start_dt = datetime(2023, 5, 10, tzinfo=timezone.utc)


def _to_utc_ts(dt):
    ts = pd.Timestamp(dt)
    if ts.tzinfo is None:
        ts = ts.tz_localize('UTC')
    else:
        ts = ts.tz_convert('UTC')
    return ts


def make_provider(ds):
    def provider(sym, tf, start, end):
        if sym not in ds:
            return pd.DataFrame()
        ohlcv, fr = ds[sym]
        merged = merge_funding_to_ohlcv(ohlcv, fr, symbol=sym)
        s_ts = _to_utc_ts(start)
        e_ts = _to_utc_ts(end)
        return merged[
            (merged['ts'] >= s_ts) &
            (merged['ts'] <= e_ts)
        ].copy()
    return provider


# Quick signal count pre-backtest
print("\nPre-backtest signal count:")
for sym in symbols_perp:
    ohlcv, fr = datasets[sym]
    merged = merge_funding_to_ohlcv(ohlcv, fr, symbol=sym)
    df_feat = strat.prepare_features(merged)
    sigs = strat.generate_signals(df_feat)
    print(f"  {sym}: {len(sigs)} signals ({sum(1 for s in sigs if s.direction=='short')} short, {sum(1 for s in sigs if s.direction=='long')} long)")

result = engine.run(
    strat,
    universe=symbols_perp,
    start=start_dt,
    end=end_dt,
    initial_capital=10_000.0,
    timeframe='4h',
    fees={'taker': 0.00075, 'maker': -0.0001},
    slippage_bps=5.0,
    ohlcv_provider=make_provider(datasets),
)

print()
print("=== BACKTEST RESULTS (2023-05-10 to 2026-05-08) ===")
print(f"Strategy: {result.strategy_name}")
print(f"Universe: {len(result.universe)} symbols")
print(f"N trades: {result.n_trades}")
print(f"Initial capital: USD {result.initial_capital:,.0f}")
if not result.equity_curve.empty:
    final_eq = result.equity_curve.iloc[-1]
    total_ret = (final_eq / result.initial_capital - 1) * 100
    print(f"Final equity:    USD {final_eq:,.2f}")
    print(f"Total return:    {total_ret:.1f}%")
kpis = result.kpis
print(f"Sharpe:          {kpis.get('sharpe', 0):.3f}")
print(f"Sortino:         {kpis.get('sortino', 0):.3f}")
print(f"Max drawdown:    {kpis.get('max_drawdown', 0)*100:.1f}%")
print(f"CAGR:            {kpis.get('cagr', 0)*100:.1f}%")
print(f"Win rate:        {kpis.get('win_rate', 0)*100:.1f}%")
print(f"Profit factor:   {kpis.get('profit_factor', 0):.2f}")
print(f"Avg win USD:     {kpis.get('avg_win', 0):.2f}")
print(f"Avg loss USD:    {kpis.get('avg_loss', 0):.2f}")
print(f"Deflated Sharpe: {kpis.get('deflated_sharpe', 0):.3f}")

if not result.trades.empty:
    trades = result.trades.copy()
    trades['year'] = pd.to_datetime(trades['exit_ts']).dt.year
    print()
    print("=== YEARLY BREAKDOWN ===")
    for yr, grp in trades.groupby('year'):
        pnl = grp['realized_pnl_usdt'].sum()
        wr = (grp['realized_pnl_usdt'] > 0).mean() * 100
        print(f"  {yr}: n={len(grp):3d}, PnL=USD {pnl:+7.2f}, WR={wr:.0f}%")
