"""Binance Futures TESTNET — close all positions + cancel all orders.

Kullanım:
    python scripts/futures_testnet_close_all.py [--dry-run]

DRY-RUN ile pozisyonları sadece listeler. --dry-run olmadan KAPATIR.
Testnet hesabını sıfırlamak için kullanılır.
"""
import argparse
import os
import sys
import time
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env", override=False)

from scripts.futures_trade_daily import get_futures_exchange


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Sadece listele, kapatma")
    args = parser.parse_args()

    print("=" * 70)
    print("🧹 Binance Futures TESTNET — CLOSE ALL")
    print("=" * 70)
    print(f"Mode: {'DRY-RUN (yalnızca listele)' if args.dry_run else 'LIVE CLOSE (gerçek kapatma)'}")
    print()

    ex = get_futures_exchange()

    # 1) Hesap balance ve pozisyonlar
    account = ex.fapiPrivateV2GetAccount()
    wallet = float(account.get('totalWalletBalance', 0))
    unrealized = float(account.get('totalUnrealizedProfit', 0))
    print(f"Wallet:           ${wallet:>10,.2f} USDT")
    print(f"Unrealized PnL:   ${unrealized:>+10,.2f} USDT")
    print(f"Available:        ${float(account.get('availableBalance', 0)):>10,.2f} USDT")
    print()

    positions = [p for p in account.get('positions', []) if float(p.get('positionAmt', 0)) != 0]
    print(f"AÇIK POZİSYONLAR ({len(positions)}):")
    for p in positions:
        sym = p['symbol']
        amt = float(p['positionAmt'])
        side = 'LONG' if amt > 0 else 'SHORT'
        entry = float(p.get('entryPrice', 0))
        upnl = float(p.get('unrealizedProfit', 0))
        print(f"  {sym:10s} {side:5s} qty={amt:>10.4f}  entry=${entry:>10.2f}  uPnL={upnl:>+8.2f}")

    # 2) Açık emirler (TP/SL)
    print()
    open_orders = ex.fetch_open_orders()
    print(f"AÇIK EMİRLER ({len(open_orders)}):")
    for o in open_orders[:20]:
        sym = o['symbol']
        typ = o['type']
        side = o['side']
        amt = o.get('amount', 0)
        price = o.get('price') or o.get('info', {}).get('stopPrice', '?')
        print(f"  {sym:10s} {side:5s} type={typ:20s} qty={amt:>10.4f} price={price}")

    if args.dry_run:
        print()
        print("DRY-RUN — hiçbir işlem yapılmadı.")
        return 0

    if not positions and not open_orders:
        print()
        print("✅ Zaten temiz. Yapılacak iş yok.")
        return 0

    # 3) Cancel all open orders (TP/SL emirleri dahil)
    print()
    print("🧹 Cancel all open orders...")
    symbols_with_orders = set(o['symbol'] for o in open_orders)
    for sym in symbols_with_orders:
        try:
            res = ex.cancel_all_orders(sym)
            print(f"  ✅ {sym}: orders cancelled")
        except Exception as e:
            print(f"  ❌ {sym}: {e}")

    # 4) Close all positions (market order opposite side, reduceOnly)
    print()
    print("🧹 Close all positions (market, reduceOnly)...")
    for p in positions:
        sym = p['symbol']
        amt = float(p['positionAmt'])
        side = 'sell' if amt > 0 else 'buy'  # opposite
        try:
            symbol_unified = sym[:-4] + "/" + sym[-4:]  # BTCUSDT -> BTC/USDT
            order = ex.create_order(
                symbol=symbol_unified,
                type='MARKET',
                side=side,
                amount=abs(amt),
                params={'reduceOnly': True},
            )
            print(f"  ✅ {sym}: closed {abs(amt)} ({side}) — order_id={order.get('id')}")
        except Exception as e:
            print(f"  ❌ {sym}: {e}")

    # 5) Final state
    time.sleep(2)
    print()
    print("📊 FINAL STATE:")
    account = ex.fapiPrivateV2GetAccount()
    wallet = float(account.get('totalWalletBalance', 0))
    available = float(account.get('availableBalance', 0))
    positions_left = [p for p in account.get('positions', []) if float(p.get('positionAmt', 0)) != 0]
    print(f"  Wallet:    ${wallet:,.2f} USDT")
    print(f"  Available: ${available:,.2f} USDT")
    print(f"  Open pos:  {len(positions_left)}")
    if positions_left:
        for p in positions_left:
            print(f"    ⚠️ {p['symbol']} hala açık: {p['positionAmt']}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
