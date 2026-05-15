"""Mevcut açık testnet pozisyonlarına OCO (auto SL/TP) ekle.

Trade journal'dan filled trades'i oku, her biri için OCO sell order yerleştir.
Yeni testnet trade'ler için testnet_trade_daily.py güncellendi (OCO inline).
"""
from __future__ import annotations

import io
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

# Load env (python-dotenv: quote+comment trim, mevcut env korunur)
from dotenv import load_dotenv
load_dotenv(ROOT / ".env", override=False)

import ccxt
import duckdb

JOURNAL = ROOT / "data" / "testnet_journal.duckdb"


def get_exchange():
    ex = ccxt.binance({
        'apiKey': os.getenv('BINANCE_TESTNET_API_KEY'),
        'secret': os.getenv('BINANCE_TESTNET_API_SECRET'),
        'enableRateLimit': True,
        'options': {
            'defaultType': 'spot',
            'warnOnFetchOpenOrdersWithoutSymbol': False,
            'adjustForTimeDifference': True,
            'recvWindow': 10000,
        },
    })
    ex.set_sandbox_mode(True)
    try:
        ex.load_time_difference()
    except Exception:
        pass
    ex.load_markets()
    return ex


def init_oco_table():
    con = duckdb.connect(str(JOURNAL))
    con.execute("""
        CREATE TABLE IF NOT EXISTS testnet_oco_orders (
            oco_id VARCHAR PRIMARY KEY,
            ts TIMESTAMP,
            signal_id VARCHAR,
            symbol VARCHAR,
            side VARCHAR,
            qty DOUBLE,
            tp_price DOUBLE,
            sl_trigger DOUBLE,
            sl_limit DOUBLE,
            tp_order_id VARCHAR,
            sl_order_id VARCHAR,
            list_client_order_id VARCHAR,
            status VARCHAR,
            notes VARCHAR
        )
    """)
    con.commit()
    con.close()


def place_oco_for_long(ex, symbol: str, qty: float, tp_price: float, sl_price: float) -> dict:
    """LONG pozisyonu için SELL OCO order.

    OCO 2 leg:
      - TP: LIMIT SELL @ tp_price (price > current)
      - SL: STOP_LOSS_LIMIT SELL @ stopPrice=sl_trigger, price=sl_limit
    Bir tarafı fill olunca diğer cancel.
    """
    market = ex.market(symbol)
    # Round qty + prices to symbol precision
    qty_rounded = float(ex.amount_to_precision(symbol, qty))
    tp_rounded = float(ex.price_to_precision(symbol, tp_price))
    sl_trigger = float(ex.price_to_precision(symbol, sl_price))
    sl_limit = float(ex.price_to_precision(symbol, sl_price * 0.995))  # %0.5 altı limit (slippage tampon)

    # Min cost check
    ticker = ex.fetch_ticker(symbol)
    cur_px = ticker['last']
    min_cost = market['limits']['cost'].get('min', 5)
    if qty_rounded * cur_px < min_cost:
        return {'status': 'skip', 'reason': f'qty {qty_rounded}*${cur_px:.4f}<{min_cost}'}

    # tp_price > current_price > sl_trigger şart
    if not (tp_rounded > cur_px > sl_trigger):
        return {'status': 'skip', 'reason': f'invalid OCO order: tp={tp_rounded}, cur={cur_px}, sl={sl_trigger}'}

    try:
        # ccxt private_post_order_oco
        params = {
            'symbol': market['id'],
            'side': 'SELL',
            'quantity': str(qty_rounded),
            'price': str(tp_rounded),         # TP limit price
            'stopPrice': str(sl_trigger),     # SL trigger
            'stopLimitPrice': str(sl_limit),  # SL limit (after trigger)
            'stopLimitTimeInForce': 'GTC',
        }
        result = ex.private_post_order_oco(params)
        # ccxt result format: orderListId, contingencyType, listStatusType, ...
        order_list_id = result.get('orderListId')
        list_client_id = result.get('listClientOrderId')
        orders = result.get('orders', [])
        return {
            'status': 'placed',
            'order_list_id': order_list_id,
            'list_client_id': list_client_id,
            'orders': orders,
            'tp_price': tp_rounded,
            'sl_trigger': sl_trigger,
            'sl_limit': sl_limit,
            'qty': qty_rounded,
        }
    except Exception as e:
        return {'status': 'error', 'reason': f'{type(e).__name__}: {str(e)[:200]}'}


def add_oco_for_existing_filled():
    """Mevcut filled trades için OCO ekle (eğer yoksa)."""
    init_oco_table()
    ex = get_exchange()

    con = duckdb.connect(str(JOURNAL))
    # Filled long trades
    rows = con.execute("""
        SELECT s.signal_id, s.symbol, s.fill_qty, s.tp_price, s.sl_price, s.fill_price
        FROM testnet_signals s
        WHERE s.status = 'filled' AND s.side = 'long'
          AND s.signal_id NOT IN (SELECT signal_id FROM testnet_oco_orders WHERE status = 'placed')
    """).fetchall()

    print(f"OCO eklenecek pozisyon: {len(rows)}")

    for sig_id, sym, qty, tp, sl, fill_px in rows:
        print(f"\n  {sym} qty={qty:.4f} fill=${fill_px:.4f} tp=${tp:.4f} sl=${sl:.4f}")
        result = place_oco_for_long(ex, sym, qty, tp, sl)
        print(f"    -> {result['status']}: ", end='')
        if result['status'] == 'placed':
            print(f"order_list_id={result['order_list_id']}, tp=${result['tp_price']:.4f}, sl_trigger=${result['sl_trigger']:.4f}")
            con.execute("""
                INSERT INTO testnet_oco_orders VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (uuid.uuid4().hex[:16], datetime.now(timezone.utc), sig_id, sym, 'sell',
                  result['qty'], result['tp_price'], result['sl_trigger'], result['sl_limit'],
                  str(result['orders'][0].get('orderId')) if result['orders'] else None,
                  str(result['orders'][1].get('orderId')) if len(result['orders']) > 1 else None,
                  str(result['list_client_id']),
                  'placed', None))
        else:
            print(f"{result.get('reason')}")
            con.execute("""
                INSERT INTO testnet_oco_orders VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (uuid.uuid4().hex[:16], datetime.now(timezone.utc), sig_id, sym, 'sell',
                  qty, tp, sl, sl * 0.995, None, None, None, result['status'], result.get('reason')))

    con.commit()
    con.close()


if __name__ == "__main__":
    add_oco_for_existing_filled()
