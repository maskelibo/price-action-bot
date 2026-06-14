"""XRP short'u elle kapat — 2026-06-10 tek seferlik.

Fix-öncesi XRP short (entry 1.3664, pyramid kaydı yok, bot trail edemiyor)
kullanıcı onayıyla elle kapatılıyor. SADECE XRP/USDT'ye dokunur.

Kullanım:
    python scripts/one_time_corrections/close_xrp_2026_06_10.py --dry-run
    python scripts/one_time_corrections/close_xrp_2026_06_10.py
"""
import argparse
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env", override=False)

from scripts.futures_trade_daily import get_futures_exchange

SYMBOL = "XRP/USDT"
SYMBOL_RAW = "XRPUSDT"
TR = timezone(timedelta(hours=3))


def now_tr() -> str:
    return datetime.now(TR).strftime("%Y-%m-%d %H:%M:%S TR")


def fetch_short_amt(ex) -> float:
    """Taze positionAmt (negatif=short). Pozisyon yoksa 0."""
    for p in ex.fetch_positions([SYMBOL]):
        amt = float(p["info"].get("positionAmt", 0) or 0)
        if amt != 0:
            return amt
    return 0.0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Sadece listele, kapatma")
    args = parser.parse_args()

    print(f"[{now_tr()}] XRP elle kapatma — {'DRY-RUN' if args.dry_run else 'EXECUTE'}")

    ex = get_futures_exchange()

    amt = fetch_short_amt(ex)
    if amt == 0:
        print("ABORT: XRP pozisyonu yok — hiçbir şey yapılmadı.")
        return 0
    if amt > 0:
        print(f"ABORT: XRP pozisyonu LONG ({amt}) — beklenen short değil, hiçbir şey yapılmadı.")
        return 1

    qty = abs(amt)
    orders = [o for o in ex.fetch_open_orders(SYMBOL)]
    print(f"Pozisyon: SHORT qty={qty}  |  açık XRP emirleri: {len(orders)}")
    for o in orders:
        print(f"  {o['side']} {o['type']} qty={o.get('amount')} stop={o.get('info', {}).get('stopPrice')}")

    if args.dry_run:
        print("DRY-RUN — hiçbir işlem yapılmadı.")
        return 0

    # 1) Kapat: önce reduceOnly market; testnet -2022 reddi → taze qty ile
    # plain-market (futures_daemon.py PROT_WATCHDOG_HEAL deseninin aynısı).
    income_since_ms = int(time.time() * 1000) - 60_000
    try:
        ex.create_order(
            symbol=SYMBOL,
            type="MARKET",
            side="buy",
            amount=qty,
            params={"reduceOnly": True},
        )
        print(f"Kapatıldı: market(reduceOnly) buy qty={qty}")
    except Exception as ro_err:
        print(f"reduceOnly reddedildi ({str(ro_err)[:60]}) → plain-market fallback")
        fresh = abs(fetch_short_amt(ex))
        if fresh == 0:
            print("Pozisyon zaten kapanmış — fallback gereksiz.")
        else:
            fresh_qty = ex.amount_to_precision(SYMBOL, fresh)
            ex.create_order(symbol=SYMBOL, type="MARKET", side="buy", amount=float(fresh_qty))
            print(f"Kapatıldı: plain-market buy qty={fresh_qty}")

    # 2) Kapanışı doğrula
    time.sleep(2)
    left = fetch_short_amt(ex)
    if left != 0:
        print(f"⚠️ POZİSYON HÂLÂ AÇIK: positionAmt={left} — SL iptal EDİLMEDİ, elle bak!")
        return 1
    print("Doğrulandı: pozisyon amt=0")

    # 3) Kalan algo emirleri (breakeven SL vs.) iptal et
    try:
        ex.cancel_all_orders(SYMBOL)
    except Exception as e:
        print(f"⚠️ cancel_all_orders hatası: {e}")
    time.sleep(1)
    left_orders = ex.fetch_open_orders(SYMBOL)
    print(f"Açık XRP emirleri (iptal sonrası): {len(left_orders)}")

    # 4) Borsa-truth realize NET (REALIZED_PNL + COMMISSION + FUNDING_FEE)
    time.sleep(2)
    total = {"REALIZED_PNL": 0.0, "COMMISSION": 0.0, "FUNDING_FEE": 0.0}
    for inc in ex.fapiPrivateGetIncome({"symbol": SYMBOL_RAW, "startTime": income_since_ms}):
        t = inc.get("incomeType")
        if t in total:
            total[t] += float(inc.get("income", 0) or 0)
    net = sum(total.values())
    print(
        f"[{now_tr()}] Realize NET: ${net:+.2f}  "
        f"(pnl={total['REALIZED_PNL']:+.2f} fee={total['COMMISSION']:+.2f} "
        f"funding={total['FUNDING_FEE']:+.2f})"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
