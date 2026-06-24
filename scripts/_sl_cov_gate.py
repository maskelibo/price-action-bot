"""ETH/BTC/DOGE SL kapsama >= %99 ise exit 0, eksikse exit 1 (Monitor gate)."""
import sys
sys.path.insert(0, 'scripts')
from dotenv import load_dotenv
load_dotenv()
from futures_trade_daily import get_futures_exchange

ex = get_futures_exchange()
pos = {p['symbol'].replace('/USDT:USDT', ''): abs(p.get('contracts', 0) or 0)
       for p in ex.fetch_positions() if (p.get('contracts', 0) or 0) > 0}
algo = ex.fapiPrivateGetOpenAlgoOrders()
algo = algo if isinstance(algo, list) else algo.get('orders', [])

ok = True
parts = []
for s in ['ETH', 'BTC', 'DOGE']:
    sls = [o for o in algo
           if str(o.get('symbol', '')).replace('USDT', '') == s
           and 'STOP' in str(o.get('orderType', '')).upper()]
    cov = sum(float(o.get('quantity') or 0) for o in sls)
    pq = pos.get(s, 0)
    pct = cov / pq * 100 if pq else 100
    parts.append(f'{s}:{pct:.0f}%')
    if pq and pct < 99:
        ok = False
print(' '.join(parts), 'OK' if ok else 'EKSIK')
sys.exit(0 if ok else 1)
