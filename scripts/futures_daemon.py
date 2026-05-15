"""Futures Testnet REAL-TIME DAEMON — Binance USDM Futures Testnet sürekli paper trading.

Loops:
  - SIGNAL SCAN: günde 1 (yeni 1d bar formed olduğunda)
  - POSITION CHECK: her 60 saniye (TP/SL fill detection + trailing)
  - EQUITY SNAPSHOT: her 5 dakika (dashboard live update)

LONG + SHORT ikisi de calisir (futures'ta margin var).

Usage:
    python scripts/futures_daemon.py            # arka planda sürekli
    python scripts/futures_daemon.py --once     # tek seferlik
"""
from __future__ import annotations

import argparse
import io
import os
import sys
import time
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

os.environ["PA_LOG_QUIET"] = "1"
import warnings
warnings.filterwarnings("ignore")

import duckdb

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

# Multi-bot futures support
_BOT_NAME = os.environ.get("PA_BOT_NAME", "").lower()
if _BOT_NAME == "atlas":
    JOURNAL = ROOT / "data" / "futures_journal_atlas.duckdb"
    LOG_FILE = ROOT / "logs" / "futures_daemon_atlas.log"
    LAST_SCAN_STATE = ROOT / "logs" / "state" / "futures_last_scan_atlas.txt"
elif _BOT_NAME == "phoenix":
    JOURNAL = ROOT / "data" / "futures_journal_phoenix.duckdb"
    LOG_FILE = ROOT / "logs" / "futures_daemon_phoenix.log"
    LAST_SCAN_STATE = ROOT / "logs" / "state" / "futures_last_scan_phoenix.txt"
else:
    JOURNAL = ROOT / "data" / "futures_journal.duckdb"
    LOG_FILE = ROOT / "logs" / "futures_daemon.log"
    LAST_SCAN_STATE = ROOT / "logs" / "state" / "futures_last_scan.txt"
KILL_SWITCH_PATH = ROOT / "logs" / "kill_switch.json"
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
        import json as _json
        with open(KILL_SWITCH_PATH, "r", encoding="utf-8") as f:
            ks = _json.load(f)
        if bool(ks.get("halted", False)):
            return True, str(ks.get("reason") or "no reason")
        return False, ""
    except Exception:
        return False, ""  # bozuk dosya = halted değil (fail-safe)


def log(msg: str):
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


_last_signal_scan_date = _load_last_scan_date()  # restart-persistent (sadece günde 1 tarama)

# Dead Man's Switch instance (daemon başladığında set edilir)
_dms = None


def _init_dead_mans_switch(exchange):
    """Dead Man's Switch'i exchange ile başlat."""
    global _dms
    try:
        from price_action.execution.dead_mans_switch import DeadMansSwitch
        _dms = DeadMansSwitch(exchange, service_name="futures_daemon")
        _dms.start()
        log("DEAD_MANS_SWITCH: başlatıldı (timeout=300s, heartbeat=60s)")
    except Exception as e:
        log(f"DEAD_MANS_SWITCH_INIT_ERROR: {e}")


def _dms_ping(state: dict | None = None):
    """Dead Man's Switch heartbeat ping."""
    global _dms
    if _dms is None:
        return
    try:
        equity = float((state or {}).get("wallet_balance", 0))
        n_pos = int((state or {}).get("n_positions", 0))
        _dms.ping(equity_usdt=equity, n_open_positions=n_pos)
    except Exception:
        pass


def equity_snapshot():
    from scripts.futures_trade_daily import get_futures_exchange, fetch_futures_state, init_futures_journal
    init_futures_journal()
    try:
        ex = get_futures_exchange()
        state = fetch_futures_state(ex)
        con = duckdb.connect(str(JOURNAL))
        con.execute("""
            INSERT INTO futures_equity_snapshots VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (uuid.uuid4().hex[:16], datetime.now(timezone.utc),
              state['wallet_balance'], state['unrealized_pnl'], state['margin_balance'],
              state['available_balance'], state['n_positions'], state['n_open_orders'], None))
        con.commit()
        con.close()
        log(f"SNAPSHOT: wallet=${state['wallet_balance']:.2f}, "
            f"unrealized={state['unrealized_pnl']:+.2f}, "
            f"pos={state['n_positions']}, orders={state['n_open_orders']}")
        # Dead Man's Switch heartbeat ping
        _dms_ping(state)
        return state
    except Exception as e:
        log(f"SNAPSHOT ERROR: {e}")
        return None


def position_check():
    """Açık pozisyonları + algo (TP/SL) protection order durumu."""
    from scripts.futures_trade_daily import get_futures_exchange, fetch_futures_state
    try:
        ex = get_futures_exchange()
        state = fetch_futures_state(ex)
        positions = state['positions']

        if positions:
            pos_summary = []
            for p in positions:
                sym = p.get('symbol', '?')
                contracts = float(p.get('contracts', 0))
                side = p.get('side', '?')
                entry = float(p.get('entryPrice', 0))
                mark = float(p.get('markPrice', 0))
                pnl = float(p.get('unrealizedPnl', 0))
                pos_summary.append(f"{sym.replace('/USDT:USDT','').replace('/USDT','')}={side[0].upper()}{abs(contracts):.3f}@${entry:.2f}->{mark:.2f}({pnl:+.2f})")
            log(f"POS_CHECK: {len(positions)} pos, {state['n_algo_orders']} algo (TP+SL) | " + " | ".join(pos_summary[:6]))
        else:
            log(f"POS_CHECK: 0 pozisyon, {state['n_algo_orders']} algo orders")

        # Orphan algo cleanup — TP fill sonrası SL kalıntısı (veya tersi) iptal.
        # reduceOnly tek başına whipsaw'da yetersiz: TP doldu → fiyat geri döner →
        # yeni pozisyon (farklı qty) açılırsa eski SL yanlış miktar kapatır.
        # Bu yüzden "pozisyon yok ama algo var" durumunu deterministik temizle.
        try:
            active_pos_syms = set()
            for p in positions:
                qty = abs(float(p.get('contracts', 0)))
                if qty > 0.0001:
                    sym_raw = p.get('symbol', '')
                    # "BTC/USDT:USDT" → "BTCUSDT" (algo endpoint sym format)
                    active_pos_syms.add(sym_raw.split(':')[0].replace('/', ''))

            orphan_cnt = 0
            for o in state.get('algo_orders', []) or []:
                algo_sym = o.get('symbol', '')  # "BTCUSDT"
                if not algo_sym or algo_sym in active_pos_syms:
                    continue
                algo_id = o.get('algoId') or o.get('algo_id')
                if not algo_id:
                    continue
                try:
                    ex.fapiPrivateDeleteAlgoOrder({'symbol': algo_sym, 'algoId': algo_id})
                    orphan_cnt += 1
                    log(f"ORPHAN_CANCEL: {algo_sym} algoId={algo_id} type={o.get('type','?')} (no matching position)")
                except Exception as cancel_err:
                    log(f"ORPHAN_CANCEL_FAIL: {algo_sym} algoId={algo_id} err={str(cancel_err)[:80]}")
            if orphan_cnt > 0:
                log(f"ORPHAN_CLEANUP: {orphan_cnt} algo orders cancelled (whipsaw protection)")
        except Exception as cleanup_err:
            log(f"ORPHAN_CLEANUP_ERR: {str(cleanup_err)[:120]}")

        # Algo order fill detection (Binance algo endpoint)
        try:
            con = duckdb.connect(str(JOURNAL))
            our_active_prot = con.execute("""
                SELECT prot_id, symbol, tp_order_id, sl_order_id
                FROM futures_protection_orders WHERE status = 'placed'
            """).fetchall()
            # Mevcut algo IDs
            algo_open_ids = set(str(o.get('algoId', '')) for o in state['algo_orders'])
            for prot_id, sym, tp_oid, sl_oid in our_active_prot:
                tp_open = tp_oid in algo_open_ids if tp_oid else False
                sl_open = sl_oid in algo_open_ids if sl_oid else False
                if not tp_open and not sl_open:
                    # Ikisi de yok — pozisyon kapanmış (TP/SL hit veya stale cancel)
                    sym_id = sym.replace('/USDT:USDT', 'USDT').replace('/USDT', 'USDT')
                    try:
                        hist = ex.fapiPrivateGetAllAlgoOrders({'symbol': sym_id, 'limit': 30})
                        for o in hist:
                            algo_id_str = str(o.get('algoId', ''))
                            if algo_id_str in (str(tp_oid), str(sl_oid)) and o.get('algoStatus') in ('TRIGGERED', 'CANCELED', 'FINISHED', 'EXPIRED'):
                                kind = 'TP' if algo_id_str == str(tp_oid) else 'SL'
                                status_alg = o.get('algoStatus')
                                if status_alg in ('TRIGGERED', 'FINISHED'):
                                    log(f"PROT_FILL: {sym} {kind} HIT @ ${o.get('triggerPrice', 0)} (status={status_alg})")
                                else:
                                    log(f"PROT_CANCEL: {sym} {kind} cancelled (stale/manual)")
                                con.execute("""UPDATE futures_protection_orders SET status='filled' WHERE prot_id=?""", [prot_id])
                                # SEC26.B-3 + B-4: closed-trade journal write (canonical TradeJournal).
                                # Only TRIGGERED/FINISHED counts as a real close; CANCELED/EXPIRED skipped.
                                if status_alg in ('TRIGGERED', 'FINISHED'):
                                    try:
                                        sig_row = con.execute("""
                                            SELECT signal_id, ts, symbol, side, strategy, fill_price, fill_qty, sl_price
                                            FROM futures_signals
                                            WHERE signal_id = (
                                                SELECT signal_id FROM futures_protection_orders WHERE prot_id = ?
                                            )
                                        """, [prot_id]).fetchone()
                                        if sig_row:
                                            (sig_id, ts_open, sym_sig, side_sig,
                                             strat, entry_p, qty, sl_p) = sig_row
                                            exit_p = float(o.get('triggerPrice', 0) or 0)
                                            close_reason = kind.lower()  # 'tp' | 'sl'
                                            now_close = datetime.now(timezone.utc)
                                            # Canonical writer (SEC26.B-4) — idempotent, hesaplı pnl + R.
                                            try:
                                                from price_action.execution.trade_journal import TradeJournal
                                                tj = TradeJournal(db_path=str(JOURNAL))
                                                inserted = tj.record_close(
                                                    trade_id=str(sig_id),
                                                    ts_open=ts_open or now_close,
                                                    ts_close=now_close,
                                                    sym=str(sym_sig),
                                                    side=str(side_sig).lower(),
                                                    strategy=str(strat or ""),
                                                    entry_price=float(entry_p or 0.0),
                                                    exit_price=float(exit_p),
                                                    qty=float(qty or 0.0),
                                                    sl_price=float(sl_p or 0.0),
                                                    close_reason=close_reason,
                                                )
                                                log(f"  TRADE_CLOSED: sig={sig_id} {kind} inserted={inserted}")
                                            except Exception as tje:
                                                log(f"  TRADE_CLOSED_WRITE_FAIL sig_id={sig_id}: {str(tje)[:120]}")
                                    except Exception as je:
                                        log(f"  TRADE_CLOSED_LOOKUP_FAIL prot_id={prot_id}: {str(je)[:120]}")
                                break
                    except Exception as e:
                        log(f"  algo hist err {sym_id}: {str(e)[:80]}")
            con.commit()
            con.close()
        except Exception as e:
            log(f"PROT_CHECK ERROR: {e}")
    except Exception as e:
        log(f"POS_CHECK ERROR: {e}")


def signal_scan_if_new_day():
    global _last_signal_scan_date
    now = datetime.now(timezone.utc)
    today = now.date()
    if _last_signal_scan_date == today:
        return
    if now.hour == 0 and now.minute < 10:
        return
    log(f"DAILY_SCAN: yeni gün {today}, sinyal taraması başlıyor...")
    try:
        from scripts.futures_trade_daily import daily_run
        target = now - timedelta(days=1)
        daily_run(target, dry_run=False)
        _last_signal_scan_date = today
        _save_last_scan_date(today)
        log(f"DAILY_SCAN: tamamlandı, target={target.date()}")
    except Exception as e:
        log(f"DAILY_SCAN ERROR: {e}")


def main_loop():
    log("=" * 60)
    log("FUTURES DAEMON STARTED (USDM Futures Testnet)")
    log("  - Position check: every 60 seconds")
    log("  - Equity snapshot: every 5 minutes")
    log("  - Signal scan: günde 1 kez (yeni 1d bar)")
    log("  - Dead Man's Switch: 5dk heartbeat kesilirse emergency flatten")
    log("  LONG + SHORT ikisi de calisir, leverage 3x, TP/SL otomatik")
    log("  Dashboard: http://localhost:8501")
    log("=" * 60)

    last_pos_check = 0
    last_equity_snap = 0
    last_signal_check = 0
    last_slippage_summary = 0

    # Dead Man's Switch başlat
    try:
        from scripts.futures_trade_daily import get_futures_exchange
        _ex_for_dms = get_futures_exchange()
        _init_dead_mans_switch(_ex_for_dms)
    except Exception as e:
        log(f"DMS_INIT_WARNING: {e} — devam ediliyor (DMS devre dışı)")

    try:
        while True:
            # Kill-switch (her tick = 5sn — acil durdurma kapısı)
            halted, reason = _kill_switch_active()
            if halted:
                log(f"KILL_SWITCH ACTIVE — daemon exiting. Reason: {reason}")
                break
            now = time.time()
            try:
                if now - last_signal_check >= 60:
                    signal_scan_if_new_day()
                    last_signal_check = now
                if now - last_pos_check >= 60:
                    position_check()
                    last_pos_check = now
                if now - last_equity_snap >= 300:
                    equity_snapshot()
                    last_equity_snap = now
                # Günlük slippage özeti (her 6 saatte bir kontrol)
                if now - last_slippage_summary >= 21600:
                    try:
                        from price_action.execution.slippage_tracker import SlippageTracker
                        summary = SlippageTracker().daily_summary()
                        log(f"SLIPPAGE_SUMMARY: n={summary['n_fills']} "
                            f"avg={summary['avg_slippage_bps']:.1f}bps "
                            f"max={summary['max_slippage_bps']:.1f}bps "
                            f"maker={summary['maker_fill_pct']:.0f}% "
                            f"alarm={summary['alarm_level']}")
                        last_slippage_summary = now
                    except Exception as slip_err:
                        log(f"SLIPPAGE_SUMMARY_ERR: {slip_err}")
                time.sleep(5)
            except KeyboardInterrupt:
                raise
            except Exception as e:
                log(f"LOOP ERROR: {e}")
                time.sleep(30)
    except KeyboardInterrupt:
        log("DAEMON STOPPED (Ctrl+C)")
    finally:
        # Dead Man's Switch'i kapat
        global _dms
        if _dms is not None:
            try:
                _dms.stop()
            except Exception:
                pass


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true", help="Tek seferlik test")
    args = parser.parse_args()

    if args.once:
        equity_snapshot()
        position_check()
        signal_scan_if_new_day()
    else:
        main_loop()
