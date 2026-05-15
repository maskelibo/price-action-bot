"""Futures Testnet baglanti testi.

Calistir:  python scripts/futures_test_connection.py
"""
from __future__ import annotations
import io, os, sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env", override=False)

from scripts.futures_trade_daily import get_futures_exchange, fetch_futures_state

print("=" * 60)
print("FUTURES TESTNET CONNECTION TEST")
print("=" * 60)

if not os.getenv("BINANCE_FUTURES_TESTNET_API_KEY"):
    print("[ERR] .env'de BINANCE_FUTURES_TESTNET_API_KEY yok")
    print("    .env dosyasina ekle:")
    print("    BINANCE_FUTURES_TESTNET_API_KEY=...")
    print("    BINANCE_FUTURES_TESTNET_API_SECRET=...")
    sys.exit(1)

ex = get_futures_exchange()
print(f"[OK] Exchange instance OK (sandbox=ON, type=future)")

# Fetch markets
markets = ex.load_markets()
print(f"[OK] Markets loaded: {len(markets)} pairs")

# Test sym
test_sym = 'BTC/USDT:USDT'  # USDM futures notation
if test_sym in markets:
    print(f"[OK] {test_sym} listed")
else:
    # Fallback: try BTC/USDT
    test_sym = 'BTC/USDT'
    if test_sym in markets:
        print(f"[OK] {test_sym} listed (fallback)")
    else:
        print(f"[WARN] BTC/USDT yok, ilk 5 sym: {list(markets.keys())[:5]}")

# Hesap bakiyesi
state = fetch_futures_state(ex)
print()
print(f"Wallet balance:    ${state['wallet_balance']:.2f}")
print(f"Margin balance:    ${state['margin_balance']:.2f}")
print(f"Available:         ${state['available_balance']:.2f}")
print(f"Unrealized PnL:    {state['unrealized_pnl']:+.2f}")
print(f"Pozisyon:          {state['n_positions']}")
print(f"Açık order:        {state['n_open_orders']}")

if state['wallet_balance'] > 100:
    print()
    print("[READY] Futures testnet hazir, ilk trade'i atabiliriz.")
    print("Calistir:  python scripts/futures_trade_daily.py --dry-run --days 7")
else:
    print()
    print("[!] Wallet 0 — testnet hesabini reset et: testnet.binancefuture.com -> Settings -> Reset USDT Balance")
