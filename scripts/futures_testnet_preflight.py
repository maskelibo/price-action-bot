"""Binance Futures Testnet Pre-Flight Check.

Kontroller:
  1. .env'de BINANCE_FUTURES_TESTNET_API_KEY + _SECRET var mı?
  2. CCXT ile testnet'e bağlantı (futures market'i çek)
  3. Hesap balance çek (testnet wallet)
  4. Test sembolünde leverage set deneme (3x)
  5. Sample order book read (latency ölç)

Hiçbir gerçek emir vermez. Sadece read-only API + leverage set.

Usage:
    python scripts/futures_testnet_preflight.py
"""
from __future__ import annotations

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

import ccxt


def check_env() -> tuple[bool, str]:
    """Env var existence check (değer okuma yok, sadece presence)."""
    key = os.getenv("BINANCE_FUTURES_TESTNET_API_KEY")
    secret = os.getenv("BINANCE_FUTURES_TESTNET_API_SECRET")
    if not key:
        return False, "BINANCE_FUTURES_TESTNET_API_KEY MISSING in .env"
    if not secret:
        return False, "BINANCE_FUTURES_TESTNET_API_SECRET MISSING in .env"
    if key.startswith("xxxxxxxx") or key == "":
        return False, "API_KEY placeholder — gerçek testnet key gerekli"
    if secret.startswith("xxxxxxxx") or secret == "":
        return False, "API_SECRET placeholder — gerçek testnet secret gerekli"
    masked = key[:6] + "..." + key[-4:] if len(key) > 10 else "***"
    return True, f"Keys present (key prefix: {masked})"


def build_exchange():
    """Testnet exchange instance (futures_trade_daily.py mantığı)."""
    api_key = os.getenv("BINANCE_FUTURES_TESTNET_API_KEY")
    api_secret = os.getenv("BINANCE_FUTURES_TESTNET_API_SECRET")
    ex = ccxt.binance({
        'apiKey': api_key,
        'secret': api_secret,
        'enableRateLimit': True,
        'options': {
            'defaultType': 'future',
            'warnOnFetchOpenOrdersWithoutSymbol': False,
            'adjustForTimeDifference': True,
            'recvWindow': 10000,
            'fetchMarkets': ['linear'],
        },
    })
    TESTNET_FAPI = 'https://testnet.binancefuture.com/fapi'
    for ver, suffix in [('fapiPublic', '/v1'), ('fapiPublicV2', '/v2'), ('fapiPublicV3', '/v3'),
                        ('fapiPrivate', '/v1'), ('fapiPrivateV2', '/v2'), ('fapiPrivateV3', '/v3')]:
        ex.urls['api'][ver] = TESTNET_FAPI + suffix
    ex.has['fetchCurrencies'] = False
    try:
        ex.load_time_difference()
    except Exception:
        pass
    return ex


def main():
    print("=" * 70)
    print("🚀 Binance Futures TESTNET Pre-Flight Check")
    print("=" * 70)

    # Step 1: .env check
    print("\n[1/5] .env API key kontrolü...")
    ok, msg = check_env()
    if not ok:
        print(f"  ❌ FAIL: {msg}")
        print("\n📝 NASIL ÇÖZÜLÜR:")
        print("  1. https://testnet.binancefuture.com adresine git, giriş yap")
        print("  2. Sağ üst → API Key → Create → 'API Key' ve 'Secret Key' kopyala")
        print("  3. Proje root'unda .env dosyasını aç")
        print("  4. Şu satırları ekle (yoksa) veya doldur:")
        print("     BINANCE_FUTURES_TESTNET_API_KEY=<api key>")
        print("     BINANCE_FUTURES_TESTNET_API_SECRET=<secret>")
        print("  5. Tekrar bu script'i çalıştır: python scripts/futures_testnet_preflight.py")
        return 1
    print(f"  ✅ {msg}")

    # Step 2: Exchange bağlantı
    print("\n[2/5] CCXT exchange bağlantı kuruluyor...")
    try:
        ex = build_exchange()
        print(f"  ✅ ccxt.binanceusdm instance kuruldu (testnet URL override OK)")
    except Exception as e:
        print(f"  ❌ FAIL: {e}")
        return 2

    # Step 3: Markets fetch (testnet)
    print("\n[3/5] Testnet markets çekiliyor...")
    try:
        t0 = time.time()
        markets = ex.fetch_markets()
        elapsed = time.time() - t0
        futures_markets = [m for m in markets if m.get('contract') and m.get('settle') == 'USDT']
        print(f"  ✅ {len(futures_markets)} USDT-margined futures market ({elapsed*1000:.0f}ms)")
        # Sample
        sample = [m['symbol'] for m in futures_markets[:5]]
        print(f"     Sample: {sample}")
    except Exception as e:
        print(f"  ❌ FAIL: {e}")
        return 3

    # Step 4: Account balance
    print("\n[4/5] Testnet hesap balance...")
    try:
        t0 = time.time()
        account = ex.fapiPrivateV2GetAccount()
        elapsed = time.time() - t0
        total_wallet = float(account.get('totalWalletBalance', 0))
        total_unrealized = float(account.get('totalUnrealizedProfit', 0))
        available_balance = float(account.get('availableBalance', 0))
        print(f"  ✅ Hesap erişimi OK ({elapsed*1000:.0f}ms)")
        print(f"     Total wallet:      {total_wallet:>12,.2f} USDT")
        print(f"     Unrealized PnL:    {total_unrealized:>+12,.2f} USDT")
        print(f"     Available balance: {available_balance:>12,.2f} USDT")
        if total_wallet < 100:
            print(f"  ⚠️  WARN: Bakiye düşük ($<100). Testnet faucet: https://testnet.binancefuture.com")
    except ccxt.AuthenticationError as e:
        print(f"  ❌ FAIL: Authentication — API key/secret yanlış olabilir: {e}")
        return 4
    except Exception as e:
        print(f"  ❌ FAIL: {e}")
        return 4

    # Step 5: Order book read + leverage set (BTC/USDT)
    print("\n[5/5] BTC/USDT order book + leverage 3x test...")
    try:
        t0 = time.time()
        ob = ex.fetch_order_book("BTC/USDT", limit=5)
        latency_ob = (time.time() - t0) * 1000
        best_bid = ob['bids'][0][0] if ob['bids'] else 0
        best_ask = ob['asks'][0][0] if ob['asks'] else 0
        spread_bps = (best_ask - best_bid) / best_bid * 10000 if best_bid > 0 else 0
        print(f"  ✅ Order book: bid={best_bid:,.2f} ask={best_ask:,.2f} spread={spread_bps:.1f}bps ({latency_ob:.0f}ms)")

        t0 = time.time()
        ex.set_leverage(3, "BTC/USDT")
        latency_lev = (time.time() - t0) * 1000
        print(f"  ✅ Leverage 3x set on BTC/USDT ({latency_lev:.0f}ms)")
    except Exception as e:
        print(f"  ❌ FAIL: {e}")
        return 5

    print("\n" + "=" * 70)
    print("🎉 PRE-FLIGHT PASS — testnet bağlantı sağlam.")
    print("=" * 70)
    print("\nSonraki adım:")
    print("  python scripts/futures_daemon_atlas.py   (🏛️ ATLAS testnet)")
    print("  python scripts/futures_daemon_phoenix.py (🔥 PHOENIX testnet)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
