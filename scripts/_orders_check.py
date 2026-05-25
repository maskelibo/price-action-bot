"""Açık TP/SL emir kontrolü — HER iki endpoint (regular + algo) ham sorgu."""
import sys, json
sys.path.insert(0, 'scripts')
from dotenv import load_dotenv
load_dotenv()
from futures_trade_daily import get_futures_exchange

ex = get_futures_exchange()
pos = [p for p in ex.fetch_positions() if (p.get('contracts', 0) or 0) > 0]
print(f'POZISYON={len(pos)}')

# --- 1) Regular open orders (ham fapi) ---
try:
    reg = ex.fapiPrivateGetOpenOrders()
    reg = reg if isinstance(reg, list) else []
    print(f'REGULAR_OPEN_ORDERS={len(reg)}')
except Exception as e:
    reg = []
    print(f'REGULAR_OPEN_ORDERS=HATA: {e}')

# --- 2) Algo open orders ---
try:
    algo_raw = ex.fapiPrivateGetOpenAlgoOrders()
    if isinstance(algo_raw, dict):
        algo = algo_raw.get('orders') or algo_raw.get('data') or []
    elif isinstance(algo_raw, list):
        algo = algo_raw
    else:
        algo = []
    print(f'ALGO_OPEN_ORDERS={len(algo)}  (ham tip: {type(algo_raw).__name__})')
except Exception as e:
    algo = []
    print(f'ALGO_OPEN_ORDERS=HATA: {e}')

print('=' * 78)

def sym_norm(s):
    return str(s).replace('/USDT:USDT', '').replace('USDT', '').replace('/', '')

for p in pos:
    short = sym_norm(p['symbol'])
    side = (p.get('side') or '').upper()
    qty = abs(p.get('contracts', 0) or 0)
    r = [o for o in reg if sym_norm(o.get('symbol', '')) == short]
    a = [o for o in algo if sym_norm(o.get('symbol', '')) == short]
    has_sl = any('STOP' in str(o.get('type') or o.get('origType') or o.get('orderType') or '').upper()
                 for o in r + a)
    print(f'\n{short:6} {side:5} qty={qty:<11} regular={len(r)} algo={len(a)}  [{"OK" if has_sl else "SL YOK!"}]')
    for o in r:
        t = o.get('type') or o.get('origType') or '?'
        print(f'   REG  {str(t):20} trig={o.get("stopPrice","?"):>12} qty={o.get("origQty","?"):>10} reduceOnly={o.get("reduceOnly")}')
    for o in a:
        ot = o.get('orderType') or '?'
        oside = o.get('side') or '?'
        trig = (o.get('triggerPrice') or o.get('stopPrice') or o.get('price')
                or o.get('activationPrice') or '?')
        oqty = o.get('quantity') or o.get('origQty') or o.get('executedQty') or '?'
        st = o.get('algoStatus') or o.get('status') or '?'
        kind = 'SL' if 'STOP' in str(ot).upper() else 'TP'
        print(f'   {kind:2} {str(ot):20} {oside:5} trig={str(trig):>12} qty={str(oqty):>11} [{st}]')

print('=' * 78)
# Tüm regular emirleri de göster (sembol eşleşmese bile)
if reg:
    print('TUM REGULAR EMIRLER:')
    for o in reg:
        print(f'  {o.get("symbol")} {o.get("type") or o.get("origType")} trig={o.get("stopPrice")} qty={o.get("origQty")} reduceOnly={o.get("reduceOnly")}')
