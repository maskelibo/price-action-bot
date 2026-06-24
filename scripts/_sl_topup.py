"""SL kapsama tamamlama — ETH/BTC/DOGE eksik SL qty'sini %100'e çek.

Botun place_protection_orders mantığıyla birebir: STOP_MARKET reduceOnly,
mevcut SL trigger fiyatında. Additive — korumasız pencere yok.
"""
import sys
sys.path.insert(0, 'scripts')
from dotenv import load_dotenv
load_dotenv()
from futures_trade_daily import get_futures_exchange

ex = get_futures_exchange()
TARGETS = {'ETHUSDT', 'BTCUSDT', 'DOGEUSDT'}


def norm(s):
    return str(s).replace('/USDT:USDT', '').replace('/', '')


pos = [p for p in ex.fetch_positions() if (p.get('contracts', 0) or 0) > 0]
algo_raw = ex.fapiPrivateGetOpenAlgoOrders()
algo = algo_raw if isinstance(algo_raw, list) else algo_raw.get('orders', [])

print('SL TOP-UP — ETH/BTC/DOGE')
print('=' * 70)
for p in pos:
    sym_ccxt = p['symbol']
    sym = norm(sym_ccxt)
    if sym not in TARGETS:
        continue
    side = (p.get('side') or '').lower()
    pos_qty = abs(p.get('contracts', 0) or 0)
    close_side = 'SELL' if side == 'long' else 'BUY'
    sls = [o for o in algo if norm(o.get('symbol', '')) == sym
           and 'STOP' in str(o.get('orderType', '')).upper()]
    if not sls:
        print(f'{sym}: mevcut SL YOK — atlanıyor (manuel bak)')
        continue
    covered = sum(float(o.get('quantity') or 0) for o in sls)
    gap = pos_qty - covered
    trig = float(sls[0].get('triggerPrice') or sls[0].get('stopPrice'))
    print(f'\n{sym}: pos={pos_qty}  SL_covered={covered}  gap={gap:.8f}  trig={trig}')
    if gap <= 1e-9:
        print('   gap yok — atlanıyor')
        continue
    gap_str = ex.amount_to_precision(sym_ccxt, gap)
    trig_str = ex.price_to_precision(sym_ccxt, trig)
    if float(gap_str) <= 0:
        print(f'   gap precision sonrası 0 ({gap_str}) — atlanıyor')
        continue
    print(f'   -> STOP_MARKET {close_side} amount={gap_str} stopPrice={trig_str} reduceOnly')
    order = ex.create_order(
        symbol=sym_ccxt, type='STOP_MARKET', side=close_side,
        amount=float(gap_str),
        params={'stopPrice': trig_str, 'reduceOnly': True, 'workingType': 'MARK_PRICE'},
    )
    print(f'   PLACED ok id={order.get("id")} status={order.get("status")}')

print('=' * 70)
print('Bitti — doğrulama için _orders_check.py çalıştır.')
