"""Testnet 22.5h postmortem analyzer v2 (uses exchange OHLCV for MFE/MAE)."""
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
NOW = datetime(2026, 5, 19, 15, 30, 0, tzinfo=timezone.utc)  # approximate now
SYMS = ['XRPUSDT','ETHUSDT','ADAUSDT','LINKUSDT','DOTUSDT','AVAXUSDT','DOGEUSDT','BTCUSDT']

# Load cached OHLCV
ohlcv = {}
for sym in ['XRP/USDT','ETH/USDT','ADA/USDT','LINK/USDT','DOT/USDT','AVAX/USDT','DOGE/USDT','BTC/USDT']:
    s_norm = sym.replace('/','')
    df = pd.read_parquet(f'data/_postmortem_15m_{sym.replace("/","_")}.parquet')
    df['ts'] = pd.to_datetime(df['ts'], utc=True)
    ohlcv[s_norm] = df

# Fills
ex = get_futures_exchange()
since_ms = int(BOT_START.timestamp() * 1000)
all_fills = []
for s in SYMS:
    t = ex.fapiPrivateGetUserTrades({'symbol': s, 'startTime': since_ms, 'limit': 1000})
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
    'order_id': str(t['orderId']),
} for t in all_fills])

# Parse daemon log for FILL + PROTECT + PYRAMID + ORPHAN
LOG = Path('logs/futures_daemon.log').read_text(encoding='utf-8', errors='replace')
lines = LOG.splitlines()
fill_pat = re.compile(r'\[(\d{2}):(\d{2}):(\d{2})\]\s+15M_FILL: \[(LONG|SHORT)\] (\S+) (\S+) qty=([\d\.]+) px=\$([\d\.]+) lev=\d+x id=(\d+)')
protect_pat = re.compile(r'15M_PROTECT: tp=\$([\d\.]+) sl=\$([\d\.]+)')

# Date inference: BOT_START is 2026-05-18 17:00 UTC.
# Walk through log lines from FUTURES 15M DAEMON STARTED onward.
# Determine the daemon start line: last "FUTURES 15M DAEMON STARTED" before any FILL.
# Just iterate; track day rollover by hour-going-backward.
attributions = []
current_date = datetime(2026,5,18).date()
last_hms_secs = None
in_active_run = False
for i, line in enumerate(lines):
    m_hms = re.match(r'\[(\d{2}):(\d{2}):(\d{2})\]', line)
    if not m_hms:
        continue
    h,m,s = int(m_hms.group(1)), int(m_hms.group(2)), int(m_hms.group(3))
    hms = h*3600+m*60+s
    if last_hms_secs is not None and hms < last_hms_secs - 1800:
        current_date = current_date + timedelta(days=1)
    last_hms_secs = hms
    # Only after 2026-05-18 17:08 (active daemon start)
    fm = fill_pat.search(line)
    if fm:
        side=fm.group(4); sym=fm.group(5); strat=fm.group(6)
        qty=float(fm.group(7)); px=float(fm.group(8)); oid=fm.group(9)
        tp = sl = None
        for j in range(i+1, min(i+6, len(lines))):
            pm = protect_pat.search(lines[j])
            if pm:
                tp = float(pm.group(1)); sl = float(pm.group(2))
                break
        ts = datetime(current_date.year, current_date.month, current_date.day, h, m, s, tzinfo=timezone.utc)
        if ts < BOT_START:
            continue
        attributions.append({
            'ts_log': ts, 'sym': sym.replace('/',''), 'strategy': strat,
            'side_log': side, 'qty_log': qty, 'px_log': px,
            'tp_log': tp, 'sl_log': sl, 'order_id': oid,
        })
attr_df = pd.DataFrame(attributions)
attr_lookup = {r['order_id']: r for _, r in attr_df.iterrows()}

# Pyramid pop events
pop_pat = re.compile(r'15M_PYRAMID_POP:\s+\S+\s+(\S+)\s+TP/SL hit')
pyramid_pops = []
current_date = datetime(2026,5,18).date(); last_hms_secs = None
for line in lines:
    m_hms = re.match(r'\[(\d{2}):(\d{2}):(\d{2})\]', line)
    if not m_hms: continue
    h,m,s = int(m_hms.group(1)), int(m_hms.group(2)), int(m_hms.group(3))
    hms = h*3600+m*60+s
    if last_hms_secs is not None and hms < last_hms_secs - 1800:
        current_date = current_date + timedelta(days=1)
    last_hms_secs = hms
    pm = pop_pat.search(line)
    if pm:
        ts = datetime(current_date.year, current_date.month, current_date.day, h, m, s, tzinfo=timezone.utc)
        if ts < BOT_START: continue
        pyramid_pops.append({'ts':ts,'sym':pm.group(1)})

# Build closed trade pairs (entry + exit, paired by sym + net qty returning to zero)
closed_trades = []
for sym, g in fills_df.groupby('sym'):
    g = g.sort_values('ts').reset_index(drop=True)
    net_qty = 0.0
    open_legs = []
    for _, r in g.iterrows():
        signed = r['qty'] if r['side']=='BUY' else -r['qty']
        attr = attr_lookup.get(r['order_id'])
        strat = attr['strategy'] if attr is not None else None
        tp = attr['tp_log'] if attr is not None else None
        sl = attr['sl_log'] if attr is not None else None
        leg = {'ts':r['ts'],'side':r['side'],'qty':r['qty'],'price':r['price'],'strategy':strat,'sl':sl,'tp':tp}
        if abs(net_qty) < 1e-9:
            net_qty = signed
            open_legs = [leg]
        else:
            same_dir = (net_qty > 0 and signed > 0) or (net_qty < 0 and signed < 0)
            if same_dir:
                net_qty += signed
                open_legs.append(leg)
            else:
                close_qty = min(abs(signed), abs(net_qty))
                net_qty += signed
                open_ts = open_legs[0]['ts']
                close_ts = r['ts']
                avg_entry = sum(l['qty']*l['price'] for l in open_legs)/sum(l['qty'] for l in open_legs)
                pos_side = 'long' if open_legs[0]['side']=='BUY' else 'short'
                # MFE/MAE from exchange OHLCV
                bars = ohlcv[sym]
                mask = (bars['ts'] >= open_ts.floor('15min')) & (bars['ts'] <= close_ts.ceil('15min'))
                win = bars[mask]
                mfe_pct = mae_pct = np.nan
                if len(win):
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
                R = np.nan; sl_bps = np.nan
                if sl_x:
                    sl_dist = abs(avg_entry - sl_x)
                    sl_bps = sl_dist/avg_entry * 10000
                    move = (r['price'] - avg_entry) if pos_side=='long' else (avg_entry - r['price'])
                    R = move / sl_dist if sl_dist > 0 else np.nan
                hold_min = (close_ts - open_ts).total_seconds()/60
                # Close reason heuristic
                close_reason = 'manual/SL'
                if abs(r['price'] - (sl_x or -999)) / max(avg_entry,1e-9) < 0.002:
                    close_reason = 'SL_hit'
                elif tp_x and abs(r['price'] - tp_x) / max(avg_entry,1e-9) < 0.002:
                    close_reason = 'TP_hit'
                elif r['rpnl'] > 0:
                    close_reason = 'TP_partial'
                closed_trades.append({
                    'open_ts': open_ts, 'close_ts': close_ts, 'sym': sym, 'side': pos_side,
                    'strategy': strat_label,
                    'avg_entry': avg_entry, 'exit_price': r['price'],
                    'qty_closed': close_qty, 'rpnl': r['rpnl'], 'comm_exit': r['comm'],
                    'hold_min': hold_min,
                    'MFE_pct': mfe_pct, 'MAE_pct': mae_pct, 'R': R,
                    'sl': sl_x, 'tp': tp_x, 'sl_dist_bps': sl_bps,
                    'close_reason': close_reason,
                    'partial': abs(net_qty) > 1e-9,
                })
                if abs(net_qty) < 1e-9:
                    open_legs = []
                else:
                    rem = abs(net_qty)
                    # Reduce qty of remaining legs proportionally? Keep first leg as remainder.
                    open_legs[0] = dict(open_legs[0]); open_legs[0]['qty'] = rem

ct = pd.DataFrame(closed_trades)
print('\n=== CLOSED TRADES ANNOTATED ===')
print(ct[['open_ts','close_ts','sym','side','strategy','avg_entry','exit_price','rpnl','hold_min','MFE_pct','MAE_pct','R','sl_dist_bps','close_reason']].to_string())

print('\n=== SUMMARY ===')
print(f"n={len(ct)}, wins={(ct['rpnl']>0).sum()}, losses={(ct['rpnl']<0).sum()}, WR={(ct['rpnl']>0).mean()*100:.1f}%")
print(f"net rpnl ${ct['rpnl'].sum():.3f}, commission total ${ct['comm_exit'].sum() + 0:.3f}")
print(f"avg R: {ct['R'].mean():+.3f}, median R: {ct['R'].median():+.3f}")
print(f"avg MFE: {ct['MFE_pct'].mean():.2f}%, avg MAE: {ct['MAE_pct'].mean():.2f}%")
print(f"avg hold: {ct['hold_min'].mean():.1f} min, median: {ct['hold_min'].median():.1f}")
print()
print('--- Per strategy ---')
agg = ct.groupby('strategy').agg(n=('rpnl','size'), rpnl_sum=('rpnl','sum'), avg_R=('R','mean'), avg_MFE=('MFE_pct','mean'), avg_MAE=('MAE_pct','mean'), avg_hold=('hold_min','mean'))
print(agg.to_string())
print()
print('--- Per symbol ---')
print(ct.groupby('sym').agg(n=('rpnl','size'), rpnl_sum=('rpnl','sum'), avg_R=('R','mean')).to_string())

# Noise hit analysis: MFE in favorable direction before SL? For each losing trade, check
print('\n=== NOISE HIT ANALYSIS ===')
for _, r in ct[ct['rpnl']<0].iterrows():
    side = r['side']; sl = r['sl']; entry = r['avg_entry']
    if not sl or not isinstance(sl,(int,float)) or pd.isna(sl): continue
    sl_dist_pct = abs(entry - sl)/entry * 100
    mfe = r['MFE_pct']
    # If MFE moved > 30% of SL distance toward TP and then closed at SL -> noise
    if pd.notna(mfe):
        favorable_pct = mfe  # MFE is already favorable side
        if favorable_pct > 0.3 * sl_dist_pct:
            tag = 'NOISE_HIT' if favorable_pct > 0.5 * sl_dist_pct else 'PARTIAL_FAV'
        else:
            tag = 'CLEAN_INVALIDATION'
        print(f"  {r['sym']:10s} {side:5s} {r['strategy']:25s}  SL_dist={sl_dist_pct:.2f}% MFE={mfe:+.2f}% MAE={r['MAE_pct']:+.2f}%  -> {tag}")
    else:
        print(f"  {r['sym']:10s} {side:5s} {r['strategy']:25s}  no MFE data")

# Open positions current uPnL
print('\n=== OPEN POSITIONS ===')
pos = [p for p in ex.fetch_positions() if (p.get('contracts',0) or 0) > 0]
for p in pos:
    sym = p['symbol']
    side = p['side']
    qty = p['contracts']
    entry = p.get('entryPrice', 0)
    mark = p.get('markPrice', 0)
    upnl = p.get('unrealizedPnl', 0) or 0
    notional = abs(qty * entry)
    move_pct = (mark/entry-1)*100 if side=='long' else (entry/mark-1)*100
    print(f"  {sym:18s} {side:5s} qty={qty:>10.4f} entry=${entry:>10.4f} mark=${mark:>10.4f} notional=${notional:>8.2f} move={move_pct:+.3f}% uPnL=${upnl:+7.2f}")

# DOT pyramid: first entry SL'd, but second (after pyramid) is winning. Show timing
print('\n=== DOT SHORT BIOGRAPHY ===')
dot = ct[ct['sym']=='DOTUSDT']
print(dot.to_string())
# Plus current DOT open position
for p in pos:
    if 'DOT' in p['symbol']:
        print(f"  CURRENT: DOT short qty={p['contracts']:.1f} entry=${p['entryPrice']:.4f} mark=${p['markPrice']:.4f} uPnL=${p.get('unrealizedPnl',0):+.2f}")

# Pyramid status: check pyramid pops & still-registered positions
print('\n=== PYRAMID POPS ===')
for p in pyramid_pops:
    print(f"  {p['ts']} {p['sym']}")

ct.to_csv('reports/analyst/_postmortem_22h_trades_v2.csv', index=False)
print('\nSaved CSV')

# Reject reason aggregator (concentration_gate vs correlation_gate counts)
print('\n=== REJECT REASONS ===')
rej_pat = re.compile(r'15M_REJECT_RISK: (\S+) (\S+) reason=(\S+)')
reasons = {}
strat_rej = {}
for line in lines:
    m_hms = re.match(r'\[(\d{2}):(\d{2}):(\d{2})\]', line)
    if not m_hms: continue
    rm = rej_pat.search(line)
    if rm:
        sym=rm.group(1); strat=rm.group(2); reason=rm.group(3)
        reasons[reason] = reasons.get(reason,0)+1
        strat_rej[(strat,reason)] = strat_rej.get((strat,reason),0)+1
for r,n in sorted(reasons.items(), key=lambda x: -x[1]):
    print(f"  {r:40s} {n:4d}")
print('--- per (strategy, reason) ---')
for (s,r),n in sorted(strat_rej.items(), key=lambda x: -x[1])[:20]:
    print(f"  {s:25s} {r:30s} {n:4d}")
