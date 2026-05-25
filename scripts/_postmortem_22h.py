"""Testnet 22.5h postmortem analyzer.

Combines:
- Exchange fills (entry + exit market orders)
- Daemon log (strategy attribution, SL/TP from PROTECT events)
- 15m parquet OHLCV (MFE/MAE within hold window)
"""
from __future__ import annotations
import os, sys, re, json
from datetime import datetime, timezone, timedelta
from pathlib import Path
import pandas as pd
import numpy as np

sys.path.insert(0, 'scripts')
from dotenv import load_dotenv
load_dotenv()
from futures_trade_daily import get_futures_exchange

BOT_START = datetime(2026, 5, 18, 17, 0, 0, tzinfo=timezone.utc)
SYMS = ['XRPUSDT','ETHUSDT','ADAUSDT','LINKUSDT','DOTUSDT','AVAXUSDT','DOGEUSDT','BTCUSDT']

# --- 1. EXCHANGE FILLS ---
ex = get_futures_exchange()
since = int(BOT_START.timestamp() * 1000)
all_fills = []
for s in SYMS:
    t = ex.fapiPrivateGetUserTrades({'symbol': s, 'startTime': since, 'limit': 1000})
    all_fills.extend(t)
all_fills.sort(key=lambda x: int(x['time']))
fills_df = pd.DataFrame([{
    'ts': pd.Timestamp(int(t['time']), unit='ms', tz='UTC'),
    'sym': t['symbol'],
    'side': t['side'],
    'qty': float(t['qty']),
    'price': float(t['price']),
    'rpnl': float(t['realizedPnl']),
    'comm': float(t['commission']),
    'order_id': t['orderId'],
    'quote_qty': float(t.get('quoteQty', 0)),
} for t in all_fills])

# --- 2. DAEMON LOG: strategy + SL/TP attribution ---
LOG = Path('logs/futures_daemon.log').read_text(encoding='utf-8', errors='replace')
fill_pat = re.compile(r'\[(\d{2}:\d{2}:\d{2})\]\s+15M_FILL: \[(LONG|SHORT)\] (\S+) (\S+) qty=([\d\.]+) px=\$([\d\.]+) lev=\d+x id=(\d+)')
protect_pat = re.compile(r'\[(\d{2}:\d{2}:\d{2})\]\s+15M_PROTECT: tp=\$([\d\.]+) sl=\$([\d\.]+)')

attributions = []
prev_fill = None
# Walk through log lines; for each FILL we look forward to next PROTECT
lines = LOG.splitlines()
# We need date context — daemon log uses HH:MM:SS only, must infer from sequence.
# Bot start 2026-05-18 17:00 UTC; log entries pre-17:08 are old daemons.
# Day rollover detected when timestamp goes backward.
last_hms = None
current_date = datetime(2026, 5, 18, tzinfo=timezone.utc).date()
for i, line in enumerate(lines):
    m_hms = re.match(r'\[(\d{2}):(\d{2}):(\d{2})\]', line)
    if m_hms:
        h,m,s = int(m_hms.group(1)), int(m_hms.group(2)), int(m_hms.group(3))
        if last_hms is not None and (h*3600+m*60+s) < (last_hms[0]*3600+last_hms[1]*60+last_hms[2]) - 3600:
            # rollover
            current_date = current_date + timedelta(days=1)
        last_hms = (h,m,s)
    fm = fill_pat.search(line)
    if fm:
        hms_str = fm.group(1); side=fm.group(2); sym=fm.group(3); strat=fm.group(4)
        qty=float(fm.group(5)); px=float(fm.group(6)); oid=fm.group(7)
        # find next PROTECT line within 5 lines
        tp = sl = None
        for j in range(i+1, min(i+6, len(lines))):
            pm = protect_pat.search(lines[j])
            if pm:
                tp = float(pm.group(2)); sl = float(pm.group(3))
                break
        h,m,sec = map(int, hms_str.split(':'))
        ts = datetime(current_date.year, current_date.month, current_date.day, h, m, sec, tzinfo=timezone.utc)
        # Only events after BOT_START
        if ts < BOT_START:
            continue
        attributions.append({
            'ts_log': ts, 'sym': sym.replace('/','/'), 'strategy': strat,
            'side_log': side, 'qty_log': qty, 'px_log': px,
            'tp_log': tp, 'sl_log': sl, 'order_id': oid,
        })
attr_df = pd.DataFrame(attributions)
print('\n=== STRATEGY ATTRIBUTION (from log) ===')
for _, r in attr_df.iterrows():
    print(f"  {r['ts_log'].strftime('%m-%d %H:%M:%S')} {r['sym']:11s} {r['strategy']:25s} {r['side_log']:5s} qty={r['qty_log']:>10.4f} px=${r['px_log']:.4f} TP=${r['tp_log']} SL=${r['sl_log']} oid={r['order_id']}")

# --- 3. JOIN: fills (ENTRIES) with log attribution by order_id ---
print('\n=== ENTRIES JOIN (fills <-> log) ===')
fills_df['order_id_str'] = fills_df['order_id'].astype(str)
attr_df['order_id_str'] = attr_df['order_id'].astype(str)
entries = fills_df.merge(attr_df[['order_id_str','strategy','side_log','tp_log','sl_log']], on='order_id_str', how='left')
# Mark entry vs exit: entry => attribution.strategy not null OR rpnl==0
entries['is_entry'] = entries['strategy'].notna()
entries['is_exit_rpnl'] = entries['rpnl'] != 0

# --- 4. CLOSED TRADE PAIRING ---
# Pair: entry + exit by symbol + opposite side. For multi-stage XRP TP1 (2 partials of 166.1), pair with original entry.
print('\n=== FILLS ANNOTATED ===')
for _, r in entries.iterrows():
    role = ''
    if r['is_entry']: role='ENTRY'
    elif r['rpnl'] != 0: role='EXIT (rpnl)'
    elif r['quote_qty'] > 0 and not r['is_entry']: role='PYRAMID/REOPEN'
    print(f"  {r['ts'].strftime('%m-%d %H:%M:%S')} {r['sym']:11s} {r['side']:5s} qty={r['qty']:>10.4f} px=${r['price']:>10.4f} rpnl={r['rpnl']:+7.4f} comm={r['comm']:+.4f}  {role}  strat={r.get('strategy','-')}")

# --- 5. MFE/MAE per CLOSED TRADE ---
# Closed trades = exits where rpnl != 0
print('\n=== CLOSED TRADES (9 realized PnL events) ===')
print(f"{'open_ts':<20}{'close_ts':<20}{'sym':<10}{'side':<5}{'strat':<26}{'qty':<10}{'entry':<10}{'exit':<10}{'rpnl':<8}{'hold_min':<9}{'MFE_pct':<8}{'MAE_pct':<8}{'R':<7}{'SL_dist_bps':<11}")

# Build entry side-resolved closed pairs
closed_trades = []
# Group fills by symbol and walk chronologically
for sym, g in fills_df.groupby('sym'):
    g = g.sort_values('ts').reset_index(drop=True)
    # Position tracking: net qty; when net qty returns to zero, trade closed.
    net_qty = 0.0
    open_legs = []  # list of (ts, side, qty, price, strategy, sl, tp)
    for _, r in g.iterrows():
        signed = r['qty'] if r['side']=='BUY' else -r['qty']
        # Identify if this fill is an opener or closer
        # Find attribution
        attr_row = attr_df[attr_df['order_id_str']==str(r['order_id'])]
        strat = attr_row.iloc[0]['strategy'] if len(attr_row) else None
        tp = attr_row.iloc[0]['tp_log'] if len(attr_row) else None
        sl = attr_row.iloc[0]['sl_log'] if len(attr_row) else None
        if abs(net_qty) < 1e-9:
            # Open new position
            net_qty = signed
            open_legs = [{'ts':r['ts'],'side':r['side'],'qty':r['qty'],'price':r['price'],'strategy':strat,'sl':sl,'tp':tp,'rpnl':r['rpnl'],'comm':r['comm']}]
        else:
            same_dir = (net_qty > 0 and signed > 0) or (net_qty < 0 and signed < 0)
            if same_dir:
                # Pyramid / additional entry
                net_qty += signed
                open_legs.append({'ts':r['ts'],'side':r['side'],'qty':r['qty'],'price':r['price'],'strategy':strat,'sl':sl,'tp':tp,'rpnl':r['rpnl'],'comm':r['comm']})
            else:
                # Closing leg
                close_qty = min(abs(signed), abs(net_qty))
                net_qty += signed
                # Compute MFE/MAE from open_ts to close_ts
                open_ts = open_legs[0]['ts']
                close_ts = r['ts']
                avg_entry = sum(l['qty']*l['price'] for l in open_legs)/sum(l['qty'] for l in open_legs)
                pos_side = 'long' if open_legs[0]['side']=='BUY' else 'short'
                # Load OHLCV
                sym_dir = sym.replace('USDT','_USDT')
                year = open_ts.year; month = f"{open_ts.month:02d}"
                ppath = f"data/parquet/binance/{sym_dir}/15m/year={year}/month={month}/data.parquet"
                mfe_pct = mae_pct = float('nan')
                if os.path.exists(ppath):
                    df = pd.read_parquet(ppath)
                    df['ts'] = pd.to_datetime(df['ts'])
                    mask = (df['ts'] >= open_ts.replace(microsecond=0)) & (df['ts'] <= close_ts.replace(microsecond=0) + pd.Timedelta('15min'))
                    win = df[mask]
                    if len(win)>0:
                        hi = win['high'].max(); lo = win['low'].min()
                        if pos_side=='long':
                            mfe_pct = (hi/avg_entry - 1)*100
                            mae_pct = (lo/avg_entry - 1)*100
                        else:
                            mfe_pct = (avg_entry/lo - 1)*100
                            mae_pct = (avg_entry/hi - 1)*100
                strat_label = open_legs[0]['strategy'] or '?'
                sl_x = open_legs[0]['sl']
                tp_x = open_legs[0]['tp']
                R = float('nan'); sl_bps = float('nan')
                if sl_x:
                    sl_dist = abs(avg_entry - sl_x)
                    sl_bps = sl_dist/avg_entry * 10000
                    move = (r['price'] - avg_entry) if pos_side=='long' else (avg_entry - r['price'])
                    R = move / sl_dist if sl_dist > 0 else float('nan')
                hold_min = (close_ts - open_ts).total_seconds()/60
                closed_trades.append({
                    'open_ts': open_ts, 'close_ts': close_ts, 'sym': sym, 'side': pos_side,
                    'strategy': strat_label,
                    'avg_entry': avg_entry, 'exit_price': r['price'],
                    'qty_closed': close_qty, 'rpnl': r['rpnl'],
                    'hold_min': hold_min,
                    'MFE_pct': mfe_pct, 'MAE_pct': mae_pct, 'R': R,
                    'sl': sl_x, 'tp': tp_x, 'sl_dist_bps': sl_bps,
                    'partial': abs(net_qty) > 1e-9,  # True if remaining position
                })
                if abs(net_qty) < 1e-9:
                    open_legs = []
                else:
                    # Adjust qty of first leg (partial close)
                    rem = abs(net_qty)
                    open_legs[0]['qty'] = rem

ct = pd.DataFrame(closed_trades)
for _, r in ct.iterrows():
    print(f"{r['open_ts'].strftime('%m-%d %H:%M'):<20}{r['close_ts'].strftime('%m-%d %H:%M'):<20}{r['sym']:<10}{r['side']:<5}{r['strategy'][:25]:<26}{r['qty_closed']:<10.2f}{r['avg_entry']:<10.4f}{r['exit_price']:<10.4f}{r['rpnl']:<+8.3f}{r['hold_min']:<9.1f}{r['MFE_pct']:<8.2f}{r['MAE_pct']:<8.2f}{r['R']:<+7.2f}{r['sl_dist_bps']:<11.1f}")

print('\n=== SUMMARY ===')
print(f"closed trades: {len(ct)}")
print(f"wins: {(ct['rpnl']>0).sum()}, losses: {(ct['rpnl']<0).sum()}")
print(f"win rate: {(ct['rpnl']>0).mean()*100:.1f}%")
print(f"net rpnl: ${ct['rpnl'].sum():.2f}")
print(f"avg R: {ct['R'].mean():+.3f}")
print(f"avg MFE: {ct['MFE_pct'].mean():.2f}%, avg MAE: {ct['MAE_pct'].mean():.2f}%")
print(f"avg hold (min): {ct['hold_min'].mean():.1f}")
print()
print('--- Per strategy ---')
print(ct.groupby('strategy').agg(n=('rpnl','size'), rpnl_sum=('rpnl','sum'), avg_R=('R','mean'), avg_MFE=('MFE_pct','mean'), avg_MAE=('MAE_pct','mean')).to_string())
print()
print('--- Per symbol ---')
print(ct.groupby('sym').agg(n=('rpnl','size'), rpnl_sum=('rpnl','sum'), avg_R=('R','mean')).to_string())

# Save
ct.to_csv('reports/analyst/_postmortem_22h_trades.csv', index=False)
print('\nSaved: reports/analyst/_postmortem_22h_trades.csv')

# --- 6. SLIPPAGE ENTRY vs LOG PRICE ---
print('\n=== SLIPPAGE: log px vs fill px ===')
attr_df['order_id_str'] = attr_df['order_id'].astype(str)
fills_df['order_id_str'] = fills_df['order_id'].astype(str)
joined = attr_df.merge(fills_df[['order_id_str','price']], on='order_id_str', how='left')
for _, r in joined.iterrows():
    slip_bps = (r['price']-r['px_log'])/r['px_log']*10000
    sign = '+' if (r['side_log']=='LONG' and slip_bps>0) or (r['side_log']=='SHORT' and slip_bps<0) else '-'
    abs_bps = abs(slip_bps)
    direction = 'ADVERSE' if (r['side_log']=='LONG' and slip_bps>0) or (r['side_log']=='SHORT' and slip_bps<0) else 'FAVORABLE'
    print(f"  {r['ts_log'].strftime('%m-%d %H:%M:%S')} {r['sym']:11s} {r['side_log']:5s} log=${r['px_log']:.4f} fill=${r['price']:.4f} slip={slip_bps:+.2f}bps ({direction})")
