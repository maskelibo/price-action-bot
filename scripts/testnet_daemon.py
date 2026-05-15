"""Testnet REAL-TIME DAEMON — Binance Spot Testnet sürekli paper trading.

Loops:
  - SIGNAL SCAN: her 5 dakika (1d bar formed olduğunda anında yakala)
  - POSITION CHECK: her 60 saniye (açık pozisyon SL/TP hit anında kapat)
  - EQUITY SNAPSHOT: her 5 dakika (dashboard live update)

Usage:
    python scripts/testnet_daemon.py            # arka planda sürekli
    python scripts/testnet_daemon.py --once     # tek seferlik
"""
from __future__ import annotations

import argparse
import io
import json
import os
import sys
import time
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

# UTF-8 stderr (print yerine stderr.write kullanıyoruz Windows uyumluluk için)

os.environ["PA_LOG_QUIET"] = "1"
import warnings
warnings.filterwarnings("ignore")

import duckdb

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

JOURNAL = ROOT / "data" / "testnet_journal.duckdb"
LOG_FILE = ROOT / "logs" / "testnet_daemon.log"
KILL_SWITCH_PATH = ROOT / "logs" / "kill_switch.json"
LAST_SCAN_STATE = ROOT / "logs" / "state" / "testnet_last_scan.txt"
LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
LAST_SCAN_STATE.parent.mkdir(parents=True, exist_ok=True)


def _load_last_scan_date() -> date | None:
    """Restart'a dayanıklı: son başarılı DAILY_SCAN tarihini oku."""
    if not LAST_SCAN_STATE.exists():
        return None
    try:
        text = LAST_SCAN_STATE.read_text(encoding="utf-8").strip()
        return date.fromisoformat(text) if text else None
    except Exception:
        return None


def _save_last_scan_date(d: date) -> None:
    try:
        LAST_SCAN_STATE.write_text(d.isoformat(), encoding="utf-8")
    except Exception:
        pass


def _kill_switch_active() -> tuple[bool, str]:
    """logs/kill_switch.json oku — halted=true ise daemon durmalı."""
    if not KILL_SWITCH_PATH.exists():
        return False, ""
    try:
        with open(KILL_SWITCH_PATH, "r", encoding="utf-8") as f:
            ks = json.load(f)
        if bool(ks.get("halted", False)):
            return True, str(ks.get("reason") or "no reason")
        return False, ""
    except Exception:
        return False, ""  # bozuk dosya = halted değil (fail-safe)


def log(msg: str):
    """Stderr + log file."""
    ts = datetime.now(timezone.utc).strftime('%H:%M:%S')
    line = f"[{ts}] {msg}"
    try:
        with open(LOG_FILE, 'a', encoding='utf-8') as f:
            f.write(line + "\n")
    except Exception:
        pass
    try:
        sys.stderr.write(line + "\n")
        sys.stderr.flush()
    except Exception:
        pass


# State tracking — last scan / last snap times
_last_signal_scan_date = _load_last_scan_date()  # restart-persistent (sadece günde 1 tarama)


def equity_snapshot():
    """Testnet hesap snapshot (dashboard için)."""
    from scripts.testnet_trade_daily import get_testnet_exchange, fetch_account_state, init_testnet_journal

    init_testnet_journal()
    try:
        ex = get_testnet_exchange()
        state = fetch_account_state(ex)
        con = duckdb.connect(str(JOURNAL))
        con.execute("""
            INSERT INTO testnet_equity_snapshots VALUES (?, ?, ?, ?, ?, ?)
        """, (uuid.uuid4().hex[:16], datetime.now(timezone.utc),
              state['usdt_balance'], state['total_value_usdt'], state['n_open_orders'], None))
        con.commit()
        con.close()
        log(f"SNAPSHOT: USDT=${state['usdt_balance']:.2f}, total=${state['total_value_usdt']:.2f}, open_orders={state['n_open_orders']}")
        return state
    except Exception as e:
        log(f"SNAPSHOT ERROR: {e}")
        return None


def position_check():
    """Açık pozisyonları takip et + OCO order durumu.

    OCO yerleşik (testnet_add_oco.py + testnet_trade_daily.py inline) — exchange
    SL/TP'i kendisi handle ediyor. Burada sadece monitoring + journal güncelleme.
    """
    from scripts.testnet_trade_daily import get_testnet_exchange
    try:
        ex = get_testnet_exchange()

        # Açık order'lar (OCO leg'leri)
        open_orders = ex.fetch_open_orders()
        n_open = len(open_orders)

        # Per-symbol pozisyon değeri (sadece bizim trade'lediğimiz)
        traded_currencies = ['DOT', 'ADA', 'SOL', 'BNB', 'AVAX', 'LINK', 'DOGE', 'XRP', 'BTC', 'ETH']
        bal = ex.fetch_balance()
        active = []
        for ccy in traded_currencies:
            amt = bal['total'].get(ccy, 0)
            if amt > 0.0001:
                try:
                    ticker = ex.fetch_ticker(f'{ccy}/USDT')
                    value = amt * ticker['last']
                    active.append((ccy, amt, ticker['last'], value))
                except Exception:
                    pass

        if active:
            top = " | ".join(f"{ccy}=${val:.0f}" for ccy, amt, px, val in sorted(active, key=lambda x: -x[3])[:6])
            log(f"POS_CHECK: open_orders={n_open} | values: {top}")
        else:
            log(f"POS_CHECK: open_orders={n_open}, no traded positions")

        # OCO fill detection — eğer eski OCO list'imiz exchange'de yoksa fill olmuş demek
        try:
            con = duckdb.connect(str(JOURNAL))
            our_active_oco = con.execute("""
                SELECT oco_id, symbol, list_client_order_id, tp_order_id, sl_order_id
                FROM testnet_oco_orders WHERE status = 'placed'
            """).fetchall()
            exchange_open_ids = set(str(o.get('id', '')) for o in open_orders)
            for oco_id, sym, list_cid, tp_oid, sl_oid in our_active_oco:
                # Eğer hem TP hem SL exchange'de yok = OCO triggered (bir taraf fill, diğeri cancel)
                if tp_oid not in exchange_open_ids and sl_oid not in exchange_open_ids:
                    # Fetch order list status
                    try:
                        hist = ex.fetch_closed_orders(sym, limit=20)
                        filled = [o for o in hist if str(o.get('id')) in (tp_oid, sl_oid) and o.get('status') == 'closed']
                        if filled:
                            f = filled[0]
                            log(f"OCO_FILL: {sym} {f.get('side')} @ ${f.get('average', f.get('price', 0)):.4f} qty={f.get('filled', 0):.4f}")
                            con.execute("""UPDATE testnet_oco_orders SET status='filled' WHERE oco_id=?""", [oco_id])
                            con.commit()
                    except Exception:
                        pass
            con.close()
        except Exception as e:
            log(f"OCO_CHECK ERROR: {e}")
    except Exception as e:
        log(f"POS_CHECK ERROR: {e}")


def signal_scan_if_new_day():
    """Günde 1 kez signal scan (yeni 1d bar oluştuğunda)."""
    global _last_signal_scan_date
    now = datetime.now(timezone.utc)
    today = now.date()
    # Sadece UTC 00:00'dan sonra (1d bar dün kapandı) ve günde 1 kez
    if _last_signal_scan_date == today:
        return  # bugün zaten taradık
    if now.hour == 0 and now.minute < 10:
        # Çok erken, henüz bar fully kapanmadı (Binance veri update ediliyor)
        return
    log(f"DAILY_SCAN: yeni gün {today}, sinyal taraması başlıyor...")
    try:
        from scripts.testnet_trade_daily import daily_run
        target = now - timedelta(days=1)
        daily_run(target, dry_run=False)
        _last_signal_scan_date = today
        _save_last_scan_date(today)
        log(f"DAILY_SCAN: tamamlandı, target={target.date()}")
    except Exception as e:
        log(f"DAILY_SCAN ERROR: {e}")


def main_loop():
    """Sürekli döngü — non-blocking, basit time.sleep based."""
    log("=" * 60)
    log("TESTNET DAEMON STARTED")
    log("  - Position check: every 60 seconds")
    log("  - Equity snapshot: every 5 minutes")
    log("  - Signal scan: günde 1 kez (yeni 1d bar)")
    log("  Dashboard: http://localhost:8501")
    log("=" * 60)

    last_pos_check = 0
    last_equity_snap = 0
    last_signal_check = 0

    while True:
        # Kill-switch (her tick = 5sn — acil durdurma kapısı)
        halted, reason = _kill_switch_active()
        if halted:
            log(f"KILL_SWITCH ACTIVE — daemon exiting. Reason: {reason}")
            break
        now = time.time()
        try:
            # Signal scan check (her dakika kontrol, sadece 1/gün çalışır)
            if now - last_signal_check >= 60:
                signal_scan_if_new_day()
                last_signal_check = now

            # Position check her 60sn
            if now - last_pos_check >= 60:
                position_check()
                last_pos_check = now

            # Equity snapshot her 5 dk (300sn)
            if now - last_equity_snap >= 300:
                equity_snapshot()
                last_equity_snap = now

            time.sleep(5)  # ana loop tick 5sn
        except KeyboardInterrupt:
            log("DAEMON STOPPED (Ctrl+C)")
            break
        except Exception as e:
            log(f"LOOP ERROR: {e}")
            time.sleep(30)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true", help="Tek seferlik (test)")
    args = parser.parse_args()

    if args.once:
        equity_snapshot()
        position_check()
        signal_scan_if_new_day()
    else:
        main_loop()
