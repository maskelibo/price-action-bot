"""Futures Testnet REAL-TIME DAEMON — Binance USDM Futures Testnet sürekli paper trading.

Modes:
  --timeframe 1d  (default): Günlük 1d bar close bazlı tarama
  --timeframe 15m           : 15 dakikalık intraday bar-close loop

1d Loops:
  - SIGNAL SCAN: günde 1 (yeni 1d bar formed olduğunda)
  - POSITION CHECK: her 60 saniye (TP/SL fill detection + trailing)
  - EQUITY SNAPSHOT: her 5 dakika (dashboard live update)

15m Loops:
  - SIGNAL SCAN: her 15 dakikada bir (bar-close + 5s buffer)
  - POSITION MONITOR: her bar'da (pyramid trigger detection)
  - DMS HEARTBEAT: her tick (20s TF_DMS_PARAMS["15m"])

LONG + SHORT ikisi de calisir (futures'ta margin var).

Usage:
    python scripts/futures_daemon.py                       # 1d mode, arka planda
    python scripts/futures_daemon.py --once               # 1d, tek seferlik
    python scripts/futures_daemon.py --timeframe 15m      # 15m intraday mode
    python scripts/futures_daemon.py --timeframe 15m --once  # 15m, tek seferlik
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


# ── PyramidRouter singleton (SEC54.3) ─────────────────────────────────────
# Pyramid aktif pozisyonlar: parent_position_id → PyramidPosition
# SEC58-L2: in-memory cache + DuckDB persist (restart-safe).
_pyramid_positions: dict[str, object] = {}
_pyramid_router_instance = None

# SEC58-L2: PyramidStore singleton — startup'ta yüklenir, her upsert'te yazılır.
_pyramid_store = None


def _get_pyramid_store() -> object | None:
    """PyramidStore singleton (lazy init)."""
    global _pyramid_store
    if _pyramid_store is not None:
        return _pyramid_store
    try:
        from price_action.execution.pyramid_store import PyramidStore
        _pyramid_store = PyramidStore()
        log(f"PYRAMID_STORE: başlatıldı → {_pyramid_store._path}")
    except Exception as exc:
        log(f"PYRAMID_STORE_INIT_FAIL: {exc} — in-memory only (restart = state lost)")
        _pyramid_store = None
    return _pyramid_store


def _pyramid_store_load_on_startup() -> None:
    """Daemon başladığında DB'den aktif pozisyonları yükle (SEC58-L2)."""
    global _pyramid_positions
    store = _get_pyramid_store()
    if store is None:
        return
    try:
        recovered = store.load_all()
        if recovered:
            _pyramid_positions.update(recovered)
            log(f"PYRAMID_STORE: {len(recovered)} pozisyon restart'tan kurtarıldı: "
                f"{list(recovered.keys())[:5]}")
        else:
            log("PYRAMID_STORE: startup — kayıtlı aktif pozisyon yok")
    except Exception as exc:
        log(f"PYRAMID_STORE_LOAD_FAIL: {exc} — _pyramid_positions boş başladı")


def _get_pyramid_router(exchange):
    """PyramidRouter singleton — config'den pyramid_enabled kontrolü."""
    global _pyramid_router_instance
    if _pyramid_router_instance is not None:
        return _pyramid_router_instance
    try:
        from price_action.execution.pyramid_router import PyramidRouter
        from price_action.execution.idempotency import IdempotencyStore
        from price_action.execution.slippage_tracker import SlippageTracker
        _pyramid_router_instance = PyramidRouter(
            exchange=exchange,
            idempotency_store=IdempotencyStore(),
            slippage_tracker=SlippageTracker(),
            post_only_enabled=False,  # SEC54.4'te post-only aktif edilir (paper fill_rate ≥%60 sonrası)
            fallback_seconds=30,
            slippage_limit_bps=25.0,
            mode=os.environ.get("PA_RUN_MODE", "paper"),
        )
        log("PYRAMID_ROUTER: başlatıldı (post_only=False, slip_limit=25bps)")
    except Exception as exc:
        log(f"PYRAMID_ROUTER_INIT_FAIL: {exc} — pyramid devre dışı")
        _pyramid_router_instance = None
    return _pyramid_router_instance


_TRAIL_PCT = 0.10   # TP2 sonrası %10 trailing (kullanıcı kararı 2026-05-20)


def _desired_sl_price(side: str, entry: float, intended_sl: float,
                      mark: float, pyramid_leg_filled: bool = False) -> float:
    """Bir pozisyon için olması gereken stop-loss fiyatı.

    Kullanıcı kuralı (2026-05-20):
      • Fiyat TP2'yi (1.5R) aşana kadar → orijinal SL (değişmez).
      • TP2 aşıldıktan sonra → SL = TP1 ile (anlık fiyat ∓ %10)'dan
        pozisyon lehine olan (LONG: daha yüksek, SHORT: daha düşük).
        LONG : max(TP1, mark * 0.90)
        SHORT: min(TP1, mark * 1.10)
    TP1 = entry ± 1R, TP2 = entry ± 1.5R  (1R = |entry - intended_sl|).
    Ratchet (SL yalnız lehe hareket) çağıran bekçide uygulanır.

    Seçenek-D / BE-protect (2026-05-20):
      pyramid_leg_filled=True → pyramid leg-2 (veya sonrası) FILLED:
        SL tabanı entry'ye (break-even) çekilir.
        1.0R–1.5R bölgesinde orijinal SL yerine BE taban döner:
          LONG  → max(entry, intended_sl)  (BE ≥ intended_sl)
          SHORT → min(entry, intended_sl)  (BE ≤ intended_sl)
        TP2 sonrası trailing zaten BE üstünde (max/min ile doğal kapsanır).
      pyramid_leg_filled=False (default) → davranış byte-identical (backward-compat).

    CEO raporu 2026-05-20: lab.py bonus = max(0, R-trig) formülü BE-protect
    varsayar; bu parametre canlı kodu backtest modeli ile hizalar.
    """
    initial_r = abs(entry - intended_sl)
    if initial_r <= 0 or mark <= 0:
        return intended_sl
    if side == 'long':
        tp1 = entry + initial_r
        tp2 = entry + 1.5 * initial_r
        if mark <= tp2:
            # BE-protect: leg-2+ fill → SL tabanı entry'ye çek
            if pyramid_leg_filled:
                return max(entry, intended_sl)
            return intended_sl
        return max(tp1, mark * (1.0 - _TRAIL_PCT))
    # short
    tp1 = entry - initial_r
    tp2 = entry - 1.5 * initial_r
    if mark >= tp2:
        # BE-protect: leg-2+ fill → SL tabanı entry'ye çek
        if pyramid_leg_filled:
            return min(entry, intended_sl)
        return intended_sl
    return min(tp1, mark * (1.0 + _TRAIL_PCT))


def position_check():
    """Açık pozisyonları + algo (TP/SL) protection order durumu."""
    from scripts.futures_trade_daily import get_futures_exchange, fetch_futures_state
    try:
        ex = get_futures_exchange()
        state = fetch_futures_state(ex)
        positions = state['positions']

        # A3: rate-limit/network bilgi etiketi
        algo_ok = state.get('algo_orders_ok', True)
        pos_ok = state.get('positions_ok', True)
        rate_limit_suffix = "" if (algo_ok and pos_ok) else " [API_STALE]"

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
            log(f"POS_CHECK: {len(positions)} pos, {state['n_algo_orders']} algo (TP+SL){rate_limit_suffix} | " + " | ".join(pos_summary[:6]))
        else:
            log(f"POS_CHECK: 0 pozisyon, {state['n_algo_orders']} algo orders{rate_limit_suffix}")

        # A3: API stale ise — orphan cleanup + prot_check SKIP (false-close yazımı önle)
        if not algo_ok or not pos_ok:
            log(f"POS_CHECK SKIP: orphan+prot_check passed (algo_ok={algo_ok}, pos_ok={pos_ok}) — rate-limit/network")
            return

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
                        # Bug 3 fix: ilk eşleşmede kırma. SL tetiklenince Binance
                        # kardeş TP order'ını otomatik CANCELED yapar; eski döngü
                        # CANCELED order'ı önce yakalarsa gerçek kapanışı kaçırır
                        # ve record_close hiç çağrılmazdı. Çözüm: TP+SL order'ını
                        # ayrı bul, TRIGGERED/FINISHED olana öncelik ver.
                        tp_order = sl_order = None
                        for o in hist:
                            algo_id_str = str(o.get('algoId', ''))
                            if tp_oid and algo_id_str == str(tp_oid):
                                tp_order = o
                            elif sl_oid and algo_id_str == str(sl_oid):
                                sl_order = o
                        triggered = triggered_kind = None
                        for cand, knd in ((sl_order, 'SL'), (tp_order, 'TP')):
                            if cand is not None and cand.get('algoStatus') in ('TRIGGERED', 'FINISHED'):
                                triggered, triggered_kind = cand, knd
                                break
                        any_terminal = any(
                            o is not None and o.get('algoStatus') in ('TRIGGERED', 'CANCELED', 'FINISHED', 'EXPIRED')
                            for o in (tp_order, sl_order)
                        )
                        if any_terminal:
                            con.execute("""UPDATE futures_protection_orders SET status='filled' WHERE prot_id=?""", [prot_id])
                        if triggered is not None:
                            status_alg = triggered.get('algoStatus')
                            log(f"PROT_FILL: {sym} {triggered_kind} HIT @ ${triggered.get('triggerPrice', 0)} (status={status_alg})")
                            # SEC26.B-3 + B-4: closed-trade journal write (canonical TradeJournal).
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
                                    exit_p = float(triggered.get('triggerPrice', 0) or 0)
                                    close_reason = triggered_kind.lower()  # 'tp' | 'sl'
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
                                        log(f"  TRADE_CLOSED: sig={sig_id} {triggered_kind} inserted={inserted}")
                                    except Exception as tje:
                                        log(f"  TRADE_CLOSED_WRITE_FAIL sig_id={sig_id}: {str(tje)[:120]}")
                            except Exception as je:
                                log(f"  TRADE_CLOSED_LOOKUP_FAIL prot_id={prot_id}: {str(je)[:120]}")
                        elif any_terminal:
                            log(f"PROT_CANCEL: {sym} cancelled (stale/manual — no trigger)")
                    except Exception as e:
                        log(f"  algo hist err {sym_id}: {str(e)[:80]}")
            con.commit()
            con.close()
        except Exception as e:
            log(f"PROT_CHECK ERROR: {e}")

        # ── Koruma Bekçisi + Trailing Stop (Protection Watchdog) ──────
        # Her açık pozisyonun SL'ini _desired_sl_price() hedefine hizalar:
        #  • SL eksikse → koyar (Madde 1)
        #  • SL varsa ama hedef daha iyiyse → yukarı taşır (FAZ 2a trailing)
        #  • SL yok + kayıtlı SL ihlal → pozisyonu market kapatır (kaçan stop)
        # SL tespiti orderType=STOP_MARKET (SL breakeven'e çıksa da doğru
        # tanınır). Ratchet: SL yalnız lehe taşınır. Kaynak: pyramid_store.
        try:
            for p in positions:
                _contracts = abs(float(p.get('contracts', 0) or 0))
                if _contracts <= 1e-9:
                    continue
                _sym_raw = p.get('symbol', '')
                _sym_ccxt = _sym_raw.split(':')[0]
                _sym_algo = _sym_ccxt.replace('/', '')
                _side = (p.get('side') or '').lower()
                _entry = float(p.get('entryPrice', 0) or 0)
                _mark = float(p.get('markPrice', 0) or 0)
                if _entry <= 0 or _side not in ('long', 'short'):
                    continue
                # Sembolün açık SL emirleri (orderType=STOP_MARKET)
                _sl_orders = []   # (trigger, algoId, qty)
                for o in state.get('algo_orders', []) or []:
                    if (o.get('symbol') == _sym_algo
                            and str(o.get('orderType', '')).upper() == 'STOP_MARKET'):
                        _t = o.get('triggerPrice') or o.get('stopPrice')
                        _a = o.get('algoId') or o.get('algo_id')
                        if _t and _a is not None:
                            try:
                                _q = float(o.get('quantity')
                                           or o.get('origQty') or 0)
                            except (TypeError, ValueError):
                                _q = 0.0
                            _sl_orders.append((float(_t), _a, _q))
                # En iyi mevcut SL (long→en yüksek, short→en düşük trigger)
                _cur_sl = _cur_aid = None
                _cur_sl_qty = 0.0
                if _sl_orders:
                    _cur_sl, _cur_aid, _cur_sl_qty = (
                        max if _side == 'long' else min)(
                        _sl_orders, key=lambda t: t[0])
                # Fazla SL'leri temizle (en iyinin dışındakiler)
                for _t, _a, _q in _sl_orders:
                    if _a != _cur_aid:
                        try:
                            ex.fapiPrivateDeleteAlgoOrder(
                                {'symbol': _sym_algo, 'algoId': _a})
                            log(f"  PROT_WATCHDOG: {_sym_algo} fazla SL iptal "
                                f"(algoId={_a})")
                        except Exception:
                            pass
                # pyramid_store'dan orijinal SL + leg-1 entry.
                # ÖNEMLİ: TP1/TP2/R hesabı leg-1 (orijinal) entry ile yapılmalı.
                # Borsa entryPrice'ı pyramid ADD sonrası ortalama → şişer →
                # TP2 yanlış hesaplanır, trailing hiç tetiklenmez.
                _intended_sl = None
                _pyr_entry = None
                _pyr_pos_obj = None
                for _pp in (_pyramid_positions or {}).values():
                    if (getattr(_pp, 'symbol', '') == _sym_ccxt
                            and str(getattr(_pp, 'side', '')).lower() == _side):
                        _intended_sl = float(getattr(_pp, 'sl_price', 0) or 0)
                        _pyr_entry = float(getattr(_pp, 'entry_price', 0) or 0)
                        _pyr_pos_obj = _pp
                        break
                if not _intended_sl or _intended_sl <= 0:
                    if _cur_sl is None:
                        log(f"  PROT_WATCHDOG_ALARM: {_sym_algo} SL YOK + "
                            f"pyramid kaydı yok — manuel müdahale gerek")
                    continue
                # R/TP hesabı için leg-1 entry; yoksa borsa entry'ye düş
                _calc_entry = _pyr_entry if (_pyr_entry and _pyr_entry > 0) else _entry
                # Seçenek-D BE-protect: pyramid leg-2+ FILLED ise SL tabanı entry.
                # PyramidPosition.legs içinde leg_num >= 2 ve leg_state == "FILLED"
                # olan var mı kontrol et. Default False → backward-compat.
                _pyr_leg_filled = False
                if _pyr_pos_obj is not None:
                    for _lg in getattr(_pyr_pos_obj, 'legs', []):
                        if (getattr(_lg, 'leg_num', 0) >= 2
                                and getattr(_lg, 'leg_state', '') == 'FILLED'):
                            _pyr_leg_filled = True
                            break
                # Hedef SL (TP2 sonrası trailing — kullanıcı kuralı; BE-protect ile birlikte)
                _sl_price = _desired_sl_price(_side, _calc_entry, _intended_sl, _mark,
                                              pyramid_leg_filled=_pyr_leg_filled)
                _close_side = 'SELL' if _side == 'long' else 'BUY'
                try:
                    _qty_str = ex.amount_to_precision(_sym_ccxt, _contracts)
                    if _cur_sl is None:
                        # SL hiç yok
                        _breached = _mark > 0 and (
                            (_side == 'long' and _sl_price >= _mark)
                            or (_side == 'short' and _sl_price <= _mark))
                        if _breached:
                            ex.create_order(
                                symbol=_sym_ccxt, type='MARKET',
                                side=_close_side, amount=float(_qty_str),
                                params={'reduceOnly': True})
                            log(f"  PROT_WATCHDOG: {_sym_algo} SL yok + kayıtlı "
                                f"SL ${_sl_price} ihlal — market kapatıldı "
                                f"qty={_qty_str}")
                        else:
                            _sl_str = ex.price_to_precision(_sym_ccxt, _sl_price)
                            ex.create_order(
                                symbol=_sym_ccxt, type='STOP_MARKET',
                                side=_close_side, amount=float(_qty_str),
                                params={'stopPrice': _sl_str, 'reduceOnly': True,
                                        'workingType': 'MARK_PRICE'})
                            log(f"  PROT_WATCHDOG: {_sym_algo} SL eksikti → "
                                f"kondu @ ${_sl_str} qty={_qty_str}")
                    else:
                        # B-2 fix (CEO 2026-05-20): SL qty pozisyonu tam
                        # kapsamıyorsa (pyramid leg / re-arm pozisyonu
                        # büyüttü, eski SL küçük kaldı) tam qty'ye çek.
                        # reduceOnly → güvenli; mevcut trigger fiyatı korunur.
                        # Önce tam qty yeni SL, sonra eski kısmi SL iptal.
                        if (_cur_sl_qty > 0
                                and _cur_sl_qty < _contracts * 0.99):
                            _sl_str = ex.price_to_precision(_sym_ccxt, _cur_sl)
                            ex.create_order(
                                symbol=_sym_ccxt, type='STOP_MARKET',
                                side=_close_side, amount=float(_qty_str),
                                params={'stopPrice': _sl_str,
                                        'reduceOnly': True,
                                        'workingType': 'MARK_PRICE'})
                            try:
                                ex.fapiPrivateDeleteAlgoOrder(
                                    {'symbol': _sym_algo,
                                     'algoId': _cur_aid})
                            except Exception as _cx:
                                log(f"  PROT_WATCHDOG: {_sym_algo} eski "
                                    f"kısmi SL iptal edilemedi: "
                                    f"{str(_cx)[:60]}")
                            log(f"  PROT_WATCHDOG: {_sym_algo} SL qty "
                                f"eksik ({_cur_sl_qty}/{_contracts}) → "
                                f"tam qty'ye çekildi @ ${_sl_str}")
                            continue
                        # SL var → ratchet: hedef daha iyiyse taşı
                        _tol = _mark * 0.0005 if _mark > 0 else 0.0
                        _better = ((_sl_price > _cur_sl + _tol) if _side == 'long'
                                   else (_sl_price < _cur_sl - _tol))
                        if not _better:
                            continue
                        _sl_str = ex.price_to_precision(_sym_ccxt, _sl_price)
                        # Önce yeni koy, sonra eskiyi iptal (asla çıplak kalmaz)
                        ex.create_order(
                            symbol=_sym_ccxt, type='STOP_MARKET',
                            side=_close_side, amount=float(_qty_str),
                            params={'stopPrice': _sl_str, 'reduceOnly': True,
                                    'workingType': 'MARK_PRICE'})
                        try:
                            ex.fapiPrivateDeleteAlgoOrder(
                                {'symbol': _sym_algo, 'algoId': _cur_aid})
                        except Exception as _cx:
                            log(f"  PROT_WATCHDOG: {_sym_algo} eski SL iptal "
                                f"edilemedi: {str(_cx)[:60]}")
                        log(f"  PROT_WATCHDOG: {_sym_algo} SL taşındı "
                            f"${_cur_sl} → ${_sl_str} (trailing)")
                except Exception as _wd_place_err:
                    log(f"  PROT_WATCHDOG_FAIL: {_sym_algo}: "
                        f"{str(_wd_place_err)[:110]}")
        except Exception as _wd_err:
            log(f"  PROT_WATCHDOG_ERR: {str(_wd_err)[:120]}")

        # ── SEC54.3: PyramidRouter hook (60s tick) ────────────────────
        # Aktif pyramid pozisyonlarını kontrol et.
        # _pyramid_positions dict'i futures_trade_daily.py'deki
        # submit_to_futures() fill sonrası doldurulmalı (SEC54.4 bağlantısı).
        # Şimdi: mevcut exchange pozisyonlarından mark price oku, PyramidRouter'a ilet.
        try:
            if _pyramid_positions:
                pr = _get_pyramid_router(ex)
                if pr is not None:
                    now_ts = datetime.now(timezone.utc)
                    for pos_id, pyr_pos in list(_pyramid_positions.items()):
                        sym = getattr(pyr_pos, "symbol", None)
                        if not sym:
                            continue
                        # Mark price: exchange pozisyonlarından al
                        mark_px = None
                        for p in positions:
                            if p.get("symbol", "").replace(":USDT", "") == sym.replace(":", ""):
                                mark_px = float(p.get("markPrice") or p.get("entryPrice") or 0)
                                break
                        if not mark_px or mark_px <= 0:
                            continue
                        try:
                            pr.on_position_check(pyr_pos, mark_px, now_ts)
                            # SEC58-L2: leg state değişmiş olabilir → persist
                            try:
                                _ps = _get_pyramid_store()
                                if _ps is not None:
                                    _ps.upsert_position(pyr_pos)
                            except Exception as _ps_upd_err:
                                log(f"PYRAMID_STORE_UPSERT_ERR pos={pos_id}: {_ps_upd_err}")
                        except Exception as pyr_exc:
                            log(f"PYRAMID_CHECK_ERR pos={pos_id}: {str(pyr_exc)[:120]}")
        except Exception as pyr_loop_err:
            log(f"PYRAMID_LOOP_ERR: {str(pyr_loop_err)[:120]}")

    except Exception as e:
        log(f"POS_CHECK ERROR: {e}")


# =====================================================================
# 15m helpers (SEC54.4)
# =====================================================================

def next_15m_boundary() -> datetime:
    """Bir sonraki 15 dakikalık bar kapanış anını (UTC, sekunde sıfır) döner.

    Örnekler:
      14:07 UTC → 14:15 UTC
      14:45 UTC → 15:00 UTC
      14:59 UTC → 15:00 UTC
    """
    now = datetime.now(timezone.utc)
    minute = now.minute
    next_quarter_min = ((minute // 15) + 1) * 15
    if next_quarter_min >= 60:
        # Saat başına taşma
        new_hour = now.hour + 1
        if new_hour >= 24:
            # Gün sınırı
            from datetime import date
            tomorrow = (now.date() if False else now) + timedelta(days=1)
            return tomorrow.replace(hour=0, minute=0, second=0, microsecond=0)
        return now.replace(hour=new_hour, minute=0, second=0, microsecond=0)
    return now.replace(minute=next_quarter_min, second=0, microsecond=0)


def sleep_until(target: datetime) -> None:
    """target UTC anına kadar bekle. Geçmiş ise anında döner."""
    now = datetime.now(timezone.utc)
    delta = (target - now).total_seconds()
    if delta > 0:
        time.sleep(delta)


def _scan_signals_15m(target_dt: datetime) -> list:
    """15m tarama: futures_trade_15m.scan_signals_15m wrapper (P-04 fix).

    futures_trade_15m.scan_signals_15m(target_bar_close) → 15m signal list.
    Bu fonksiyon TOP-4 15m stratejilerini (C2 champion) çalıştırır.
    """
    try:
        from scripts.futures_trade_15m import scan_signals_15m
        sigs = scan_signals_15m(target_dt)
        return sigs
    except Exception as e:
        log(f"15M_SCAN_ERROR: {e}")
        return []


def run_15m_mode(once: bool = False) -> None:
    """15 dakikalık intraday daemon loop.

    Bar-close detect: UTC :00/:15/:30/:45 + 5s buffer
    DMS: TF_DMS_PARAMS["15m"] (heartbeat=20s, timeout=1800s)
    Stale signal guard: >30 dk → REJECT (DQ-02)
    Pyramid hook: SEC54.3 pyramid_router.on_position_check (graceful if not yet present)
    """
    try:
        from price_action.execution.dead_mans_switch import DeadMansSwitch
        dms_15m = DeadMansSwitch(exchange=None, service_name="futures_daemon_15m", tf="15m")
        dms_15m.start()
        log("15M_DMS: başlatıldı (tf=15m, heartbeat=20s, timeout=1800s)")
    except Exception as e:
        log(f"15M_DMS_INIT_ERROR: {e} — DMS devre dışı, devam ediyor")
        dms_15m = None

    # Prometheus metrics — lazy import (metrics yoksa graceful)
    try:
        from price_action.api.prometheus_metrics import (
            scan_latency_seconds,
            signal_to_order_latency_seconds,
            missed_bars_total,
            position_monitor_duration_seconds,
        )
        _metrics_ok = True
    except Exception:
        _metrics_ok = False

    # Pyramid router — SEC54.3 (P-04/P-05 fix: build_position_from_signal + pop on close)
    _pyramid_router_15m = None
    try:
        from price_action.execution.pyramid_router import PyramidRouter
        from price_action.execution.idempotency import IdempotencyStore
        from price_action.execution.slippage_tracker import SlippageTracker
        _pyramid_router_15m = PyramidRouter(
            exchange=None,   # başlangıçta None; exchange signal submit sonrası set edilir
            idempotency_store=IdempotencyStore(),
            slippage_tracker=SlippageTracker(),
            post_only_enabled=False,  # smoke: market order (post_only paper test sonrası açılır)
            fallback_seconds=30,
            slippage_limit_bps=25.0,
            mode=os.environ.get("PA_RUN_MODE", "paper"),
        )
        log("15M_PYRAMID: PyramidRouter başlatıldı (SEC54.3, post_only=False smoke)")
    except Exception as e:
        log(f"15M_PYRAMID_WARN: {e} — pyramid hook atlanıyor")

    # SEC58-L2: startup'ta DB'den aktif pyramid pozisyonlarını yükle (restart recovery)
    _pyramid_store_load_on_startup()

    log("=" * 60)
    log("FUTURES 15M DAEMON STARTED")
    log("  - Signal scan: her 15 dakikada (bar-close + 5s buffer)")
    log("  - Position monitor: her bar (pyramid trigger detection)")
    log("  - DMS heartbeat: 20s (tf=15m, timeout=30dk)")
    log("  - Stale guard: >30 dk sinyal REJECT")
    log("  - Pyramid DB persist: pyramid_store.duckdb (SEC58-L2)")
    log("=" * 60)

    last_bar_boundary: datetime | None = None

    try:
        while True:
            # Kill-switch kontrolü
            halted, reason = _kill_switch_active()
            if halted:
                log(f"15M_KILL_SWITCH ACTIVE — daemon exiting. Reason: {reason}")
                break

            # Sonraki bar kapanışını hesapla + 5s buffer ekle
            next_close = next_15m_boundary() + timedelta(seconds=5)
            log(f"15M_WAIT: sonraki bar kapanış {next_close.strftime('%H:%M:%S')} UTC")
            sleep_until(next_close)

            # Missed bar detect: önceki boundary'den 2+ bar geçti mi?
            current_boundary = next_close - timedelta(seconds=5)
            if last_bar_boundary is not None:
                bars_elapsed = int(
                    (current_boundary - last_bar_boundary).total_seconds() / 900
                )
                if bars_elapsed > 1:
                    log(f"15M_MISSED_BARS: {bars_elapsed - 1} bar kaçırıldı "
                        f"(son={last_bar_boundary.strftime('%H:%M')}, "
                        f"şimdi={current_boundary.strftime('%H:%M')})")
                    if _metrics_ok:
                        try:
                            missed_bars_total.labels(tf="15m").inc(bars_elapsed - 1)
                        except Exception:
                            pass
            last_bar_boundary = current_boundary

            scan_start = datetime.now(timezone.utc)
            try:
                # ------ SIGNAL SCAN ------
                # SEC56 FIX: current_boundary = son kapanan barın close timestamp'i.
                # scan_start = datetime.now() → birkaç saniye sonra olduğu için
                # semantik olarak yanlıştı; current_boundary daha doğru.
                signals = _scan_signals_15m(current_boundary)

                scan_elapsed = (datetime.now(timezone.utc) - scan_start).total_seconds()
                log(f"15M_SCAN: {len(signals)} sinyal, latency={scan_elapsed:.1f}s")
                if _metrics_ok:
                    try:
                        scan_latency_seconds.labels(tf="15m").observe(scan_elapsed)
                    except Exception:
                        pass

                # ------ SIGNAL FILTER + ORDER SUBMIT (P-04 fix) ------
                # futures_trade_15m.run_15m() tüm filtre + RiskOfficer + submit döngüsünü
                # zaten içeriyor. Ancak daemon flow'unda sinyaller zaten tarandı;
                # burada tekil sinyal başına submit + pyramid build hook yapılıyor.
                # Stale guard futures_trade_15m.filter_stale_signals ile halihazırda uygulandı.
                # Daemon'da ek stale check (DQ-02 defensive double-check):

                # SEC58 CRIT-2 FIX: returns_df loop dışında tek seferlik hesapla.
                # Eski kod her sinyal için build_returns_df() çağırıyordu →
                # Windows DuckDB exclusive lock conflict (read_only=True vs R/W singleton).
                # 90 günlük 1d log-return matrix 15 dakikada değişmez → bar başına 1 çekiş yeterli.
                from scripts.lib.risk_integration import build_returns_df as _build_returns_df
                _all_scan_syms = list({s["symbol"] for s in signals}) if signals else []
                try:
                    _shared_returns_df = _build_returns_df(
                        _all_scan_syms,
                        days=90,
                        market_db=ROOT / "data" / "market.duckdb",
                    )
                except Exception as _rdf_err:
                    log(f"15M_RETURNS_DF_WARN: {_rdf_err} — correlation gate konservatif")
                    import pandas as _pd_rdf
                    _shared_returns_df = _pd_rdf.DataFrame()

                import pandas as _pd
                for sig in signals:
                    try:
                        bar_close = sig.get("bar_close_ts") or sig.get("ts")
                        if bar_close is not None:
                            _bc = _pd.Timestamp(bar_close)
                            if _bc.tzinfo is None:
                                _bc = _bc.tz_localize("UTC")
                            age_min = (datetime.now(timezone.utc) - _bc.to_pydatetime()).total_seconds() / 60
                            if age_min > 30:
                                log(f"  15M_REJECT_STALE(daemon-guard): {sig.get('symbol','?')} age={age_min:.1f}min")
                                continue
                    except Exception as age_err:
                        log(f"  15M_STALE_CHECK_ERR: {age_err}")

                    order_start = datetime.now(timezone.utc)
                    try:
                        from scripts.futures_trade_daily import (
                            get_futures_exchange,
                            fetch_futures_state,
                            setup_leverage,
                            place_protection_orders,
                        )
                        from scripts.lib.risk_integration import (
                            build_futures_account_state,
                            build_signal_from_scan,
                            load_risk_officer,
                        )
                        import uuid as _uuid
                        import yaml as _yaml

                        _ex_submit = get_futures_exchange()
                        _state_submit = fetch_futures_state(_ex_submit)
                        _risk_yaml_path = ROOT / "configs" / "risk_phoenix_scalp_15m_c2v5_final.yaml"
                        _breaker_state_path = ROOT / "logs" / "risk" / "futures_breaker_state_15m_phoenix.json"
                        _breaker_state_path.parent.mkdir(parents=True, exist_ok=True)
                        _risk_officer = load_risk_officer(
                            yaml_path=_risk_yaml_path,
                            breaker_state_path=_breaker_state_path,
                        )
                        with open(_risk_yaml_path, "r", encoding="utf-8") as _f:
                            _risk_cfg = _yaml.safe_load(_f) or {}

                        _account = build_futures_account_state(
                            _state_submit,
                            journal_path=JOURNAL,
                        )
                        # SEC58 CRIT-2: _shared_returns_df loop dışında hazırlandı (no-lock conflict)
                        _returns_df = _shared_returns_df
                        _ticker = _ex_submit.fetch_ticker(sig["symbol"])
                        _cur_px = float(_ticker["last"])
                        _signal_obj = build_signal_from_scan(sig, venue="binance", timeframe="15m")
                        _decision = _risk_officer.evaluate(
                            _signal_obj, _account,
                            market_price=_cur_px,
                            returns_df=_returns_df,
                        )

                        if not hasattr(_decision, "quantity"):
                            log(f"  15M_REJECT_RISK: {sig['symbol']} {sig.get('strategy','')} "
                                f"reason={getattr(_decision,'reason','unknown')}")
                        else:
                            _qty = float(_decision.quantity)
                            _notional = float(_decision.notional_usdt)
                            _lev = max(1, min(3, int(round(_decision.leverage)))) or 1
                            _margin = _notional / _lev if _lev > 0 else _notional

                            if _margin > _state_submit["available_balance"] * 0.9:
                                log(f"  15M_SKIP_MARGIN: {sig['symbol']} need=${_margin:.2f}")
                            else:
                                setup_leverage(_ex_submit, sig["symbol"], _lev)
                                _order_side = "buy" if sig["side"] == "long" else "sell"
                                _order = _ex_submit.create_market_order(sig["symbol"], _order_side, _qty)
                                _avg_px = float(_order.get("average", _cur_px))
                                _fill_qty = float(_order.get("filled", _qty))
                                _sig_id = _uuid.uuid4().hex[:16]

                                log(f"  15M_FILL: [{sig['side'].upper()}] {sig['symbol']} "
                                    f"{sig.get('strategy','')} qty={_fill_qty:.4f} "
                                    f"px=${_avg_px:.4f} lev={_lev}x id={_order.get('id','?')}")

                                # A2: futures_signals INSERT (1d daemon parity) — prot_check + TradeJournal akışı
                                # bu kayıtlar olmadan tetiklenemiyordu (Signal Chief + Analyst convergence).
                                try:
                                    _jcon = duckdb.connect(str(JOURNAL))
                                    _jcon.execute("""
                                        INSERT INTO futures_signals VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                                    """, (_sig_id, sig.get("bar_close_ts") or sig.get("ts"),
                                          sig["symbol"], sig.get("strategy", ""), sig["side"],
                                          float(sig["sl_price"]), float(sig["tp_price"]),
                                          float(sig.get("confluence", 0.0)), _lev, "filled",
                                          str(_order.get("id", "")), _avg_px, _fill_qty,
                                          _notional, _margin, None))
                                    _jcon.commit()
                                    _jcon.close()
                                except Exception as _je_sig:
                                    log(f"    15M_JOURNAL_SIG_ERR: {str(_je_sig)[:120]}")

                                # Protection orders
                                _prot = place_protection_orders(
                                    _ex_submit, sig["symbol"], sig["side"], _fill_qty,
                                    float(sig["tp_price"]), float(sig["sl_price"]),
                                    entry_price=_avg_px,
                                )
                                if _prot["status"] == "placed":
                                    log(f"    15M_PROTECT: tp=${_prot['tp_price']:.4f} sl=${_prot['sl_price']:.4f}")
                                    # A2: futures_protection_orders INSERT (1d parity)
                                    try:
                                        _jcon = duckdb.connect(str(JOURNAL))
                                        _prot_id = _uuid.uuid4().hex[:16]
                                        _notes = None
                                        if _prot.get("mode") == "multi_target":
                                            _notes = f"mode=multi_target tp2={_prot.get('tp2_price',0):.4f} tp2_id={_prot.get('tp2_order_id','')}"
                                        _jcon.execute("""
                                            INSERT INTO futures_protection_orders VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                                        """, (_prot_id, datetime.now(timezone.utc), _sig_id,
                                              sig["symbol"], sig["side"], _fill_qty,
                                              _prot["tp_price"], _prot["sl_price"],
                                              _prot.get("tp_order_id"), _prot.get("sl_order_id"),
                                              "placed", _notes))
                                        _jcon.commit()
                                        _jcon.close()
                                    except Exception as _je_prot:
                                        log(f"    15M_JOURNAL_PROT_ERR: {str(_je_prot)[:120]}")
                                else:
                                    log(f"    15M_PROTECT_ERR: {_prot.get('reason')}")

                                # P-04: PyramidPosition build + register (P-05 cleanup ready)
                                if _pyramid_router_15m is not None:
                                    try:
                                        from price_action.execution.pyramid_router import (
                                            build_position_from_signal,
                                        )
                                        _pyr_cfg = _risk_cfg.get("strategy_portfolio", {})
                                        _pyr_triggers = _pyr_cfg.get("pyramid_triggers", [])
                                        _pyr_sizes = _pyr_cfg.get("pyramid_sizes", [])
                                        if _pyr_triggers and _pyr_sizes:
                                            _pyr_pos = build_position_from_signal(
                                                signal_dict=sig,
                                                fill_price=_avg_px,
                                                fill_qty=_fill_qty,
                                                sl_price=float(sig["sl_price"]),
                                                parent_position_id=_sig_id,
                                                pyramid_triggers=list(_pyr_triggers),
                                                pyramid_sizes=list(_pyr_sizes),
                                            )
                                            _pyramid_positions[_sig_id] = _pyr_pos
                                            # Exchange'i router'a ilet (ilk fill sonrası)
                                            _pyramid_router_15m.exchange = _ex_submit
                                            log(f"    15M_PYRAMID_REGISTERED: pos_id={_sig_id} "
                                                f"triggers={_pyr_triggers}")
                                            # SEC58-L2: DB persist
                                            try:
                                                _ps = _get_pyramid_store()
                                                if _ps is not None:
                                                    _ps.upsert_position(_pyr_pos)
                                            except Exception as _ps_err:
                                                log(f"    15M_PYRAMID_STORE_WRITE_ERR: {_ps_err}")
                                    except Exception as pyr_build_err:
                                        log(f"    15M_PYRAMID_BUILD_ERR: {pyr_build_err}")

                    except Exception as sub_err:
                        log(f"  15M_ORDER_ERR: {sig.get('symbol','?')}: {str(sub_err)[:120]}")

                    order_elapsed = (datetime.now(timezone.utc) - order_start).total_seconds()
                    if _metrics_ok:
                        try:
                            signal_to_order_latency_seconds.observe(order_elapsed)
                        except Exception:
                            pass

                # ------ POSITION MONITOR (pyramid hook + P-05 TP/SL pop) ------
                pos_monitor_start = datetime.now(timezone.utc)
                try:
                    position_check()  # 1d pos_check: TP/SL fill detection + orphan cleanup

                    # P-04/P-05: PyramidRouter hook — aktif pyramid pozisyonları kontrol et
                    if _pyramid_router_15m is not None and _pyramid_positions:
                        try:
                            from scripts.futures_trade_daily import (
                                get_futures_exchange,
                                fetch_futures_state,
                            )
                            _ex_mon = get_futures_exchange()
                            # Restart-recovered pyramid pozisyonları için exchange set et
                            # (router exchange=None ile init edilir, yeni signal fill yoksa
                            # boş kalır → create_market_order'da NoneType crash).
                            if _pyramid_router_15m.exchange is None:
                                _pyramid_router_15m.exchange = _ex_mon
                            _state_mon = fetch_futures_state(_ex_mon)
                            _pyr_now = datetime.now(timezone.utc)
                            # Aktif exchange pozisyonlarından mark price haritası
                            _mark_map: dict[str, float] = {}
                            for _ep in _state_mon.get("positions", []):
                                _sym_raw = _ep.get("symbol", "")
                                _sym_clean = _sym_raw.replace(":USDT", "").replace("/", "")
                                _mark_map[_sym_clean] = float(_ep.get("markPrice") or _ep.get("entryPrice") or 0)

                            # P-05: exchange'de artık açık olmayan pozisyonları _pyramid_positions'dan çıkar
                            _active_ex_syms: set[str] = set()
                            for _ep in _state_mon.get("positions", []):
                                if abs(float(_ep.get("contracts", 0) or 0)) > 1e-6:
                                    _active_ex_syms.add(
                                        _ep.get("symbol", "").replace(":USDT", "").replace("/", "")
                                    )
                            _to_pop: list[str] = []
                            for _fp, _pyr_pos in list(_pyramid_positions.items()):
                                _pos_sym_clean = getattr(_pyr_pos, "symbol", "").replace("/", "").replace(":USDT", "")
                                if _pos_sym_clean not in _active_ex_syms:
                                    _to_pop.append(_fp)
                                    log(f"  15M_PYRAMID_POP: {_fp} {_pos_sym_clean} TP/SL hit — removing")
                            for _fp in _to_pop:
                                _pyramid_positions.pop(_fp, None)
                                # SEC58-L2: DB'den de sil
                                try:
                                    _ps = _get_pyramid_store()
                                    if _ps is not None:
                                        _ps.delete_position(_fp)
                                except Exception as _ps_del_err:
                                    log(f"  15M_PYRAMID_STORE_DEL_ERR: {_fp}: {_ps_del_err}")

                            # Kalan aktif pyramid pozisyonlarını router'a ilet
                            for _fp, _pyr_pos in list(_pyramid_positions.items()):
                                _sym_clean = getattr(_pyr_pos, "symbol", "").replace("/", "").replace(":USDT", "")
                                _mark = _mark_map.get(_sym_clean, 0.0)
                                if _mark > 0:
                                    try:
                                        _pyramid_router_15m.on_position_check(_pyr_pos, _mark, _pyr_now)
                                    except Exception as _pyr_chk_err:
                                        log(f"  15M_PYRAMID_CHECK_ERR pos={_fp}: {str(_pyr_chk_err)[:100]}")
                        except Exception as pyr_mon_err:
                            log(f"  15M_PYRAMID_MONITOR_ERR: {str(pyr_mon_err)[:120]}")
                except Exception as pm_err:
                    log(f"  15M_POS_MONITOR_ERR: {pm_err}")

                pos_monitor_elapsed = (datetime.now(timezone.utc) - pos_monitor_start).total_seconds()
                if _metrics_ok:
                    try:
                        position_monitor_duration_seconds.observe(pos_monitor_elapsed)
                    except Exception:
                        pass

                # ------ DMS HEARTBEAT ------
                if dms_15m is not None:
                    try:
                        dms_15m.ping()
                    except Exception:
                        pass

                log(f"15M_TICK_DONE: scan={scan_elapsed:.1f}s pos_monitor={pos_monitor_elapsed:.1f}s")

            except KeyboardInterrupt:
                raise
            except Exception as loop_err:
                log(f"15M_LOOP_ERROR: {loop_err}")

            if once:
                log("15M_ONCE: tek seferlik mod, çıkılıyor")
                break

    except KeyboardInterrupt:
        log("15M_DAEMON STOPPED (Ctrl+C)")
    finally:
        if dms_15m is not None:
            try:
                dms_15m.stop()
            except Exception:
                pass


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
    # SEC58-L2: startup recovery — pyramid pozisyonlarını DB'den yükle
    _pyramid_store_load_on_startup()

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
    parser = argparse.ArgumentParser(description="Futures Daemon — 1d veya 15m intraday mode")
    parser.add_argument("--once", action="store_true", help="Tek seferlik test (1d mode için)")
    parser.add_argument(
        "--timeframe",
        choices=["1d", "15m"],
        default="1d",
        help="Daemon timeframe: '1d' (default, günlük bar) veya '15m' (intraday, SEC54.4)",
    )
    args = parser.parse_args()

    if args.timeframe == "15m":
        run_15m_mode(once=args.once)
    elif args.once:
        equity_snapshot()
        position_check()
        signal_scan_if_new_day()
    else:
        main_loop()
