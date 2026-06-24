"""Quick status snapshot — periodic update helper."""
import sys, os
sys.path.insert(0, 'scripts')
from dotenv import load_dotenv
load_dotenv()
from futures_trade_daily import get_futures_exchange
from datetime import datetime, timezone

ex = get_futures_exchange()
BOT_START = datetime(2026, 5, 18, 17, 0, 0, tzinfo=timezone.utc)
since = int(BOT_START.timestamp() * 1000)
income = ex.fapiPrivateGetIncome({'incomeType': 'REALIZED_PNL', 'startTime': since, 'limit': 200})
realized = sum(float(i.get('income', 0)) for i in income)
fees = ex.fapiPrivateGetIncome({'incomeType': 'COMMISSION', 'startTime': since, 'limit': 300})
total_fee = sum(float(f.get('income', 0)) for f in fees)
pos = [p for p in ex.fetch_positions() if (p.get('contracts',0) or 0) > 0]
unreal = sum((p.get('unrealizedPnl', 0) or 0) for p in pos)
total_notional = sum(abs(p['contracts'] * p.get('entryPrice', 0)) for p in pos)
bal = ex.fetch_balance().get('USDT', {})

print(f'POS: {len(pos)}')
for p in pos:
    sym = p['symbol'].replace('/USDT:USDT', '')[:5]
    pnl = p.get('unrealizedPnl', 0) or 0
    margin = p.get('initialMargin', 1) or 1
    pct = pnl / margin * 100
    qty = p['contracts']
    entry = p.get('entryPrice', 0)
    mark = p.get('markPrice', 0)
    notional = abs(qty * entry)
    print(f'  {sym:5} {p["side"][:5].upper():5} q={qty:>10.4f} E=${entry:>10.4f} N=${notional:>8.2f} M=${mark:>10.4f} PnL=${pnl:+7.2f} ({pct:+.2f}%)')
print(f'YATIRILAN=${total_notional:.2f}  UNREALIZED=${unreal:+.2f}')
print(f'NET = R:${realized:+.2f} | U:${unreal:+.2f} | F:${total_fee:+.2f} | TOTAL:${realized + unreal + total_fee:+.2f}')
print(f'USDT total=${bal.get("total",0):.2f}  free=${bal.get("free",0):.2f}')
