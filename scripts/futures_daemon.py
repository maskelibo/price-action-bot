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
import json
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


# WIRE-widestop (2026-05-22): 15m risk config path — env-overridable.
# Default = c2v5 final (live behavior UNCHANGED). To run the wide-stop deploy
# candidate in paper/shadow without any code change:
#   PA_15M_CONFIG=configs/risk_phoenix_scalp_15m_widestop.yaml \
#       python scripts/futures_daemon.py --timeframe 15m
# Rollback = unset PA_15M_CONFIG. See DEPLOY_widestop_15m.md.
def _risk_config_15m() -> Path:
    """Resolve the active 15m risk config (PA_15M_CONFIG override or c2v5)."""
    _override = os.environ.get("PA_15M_CONFIG", "").strip()
    if _override:
        _p = Path(_override)
        return _p if _p.is_absolute() else (ROOT / _p)
    return ROOT / "configs" / "risk_phoenix_scalp_15m_c2v5_final.yaml"


def _risk_config_5m() -> Path:
    """Resolve the active 5m risk config (PA_5M_CONFIG override or P1c default).

    Default: configs/risk_phoenix_scalp_5m_p1c.yaml (Faz 5 P1c deploy candidate)
    Override: PA_5M_CONFIG env var
    """
    _override = os.environ.get("PA_5M_CONFIG", "").strip()
    if _override:
        _p = Path(_override)
        return _p if _p.is_absolute() else (ROOT / _p)
    return ROOT / "configs" / "risk_phoenix_scalp_5m_p1c.yaml"


def _load_last_scan_date() -> date | None:
    """Restart'a dayanıklı: son başarılı DAILY_SCAN tarihini oku."""
    if not LAST_SCAN_STATE.exists():
        return None
    try:
        text = LAST_SCAN_STATE.read_text(encoding="utf-8").strip()
        return date.fromisoformat(text) if text else None
    except Exception as exc:
        # FIX 2026-05-26 (H1): silent → stderr log (logger henüz init değil olabilir)
        sys.stderr.write(f"WARN _load_last_scan_date fail: {exc}\n")
        return None


def _save_last_scan_date(d: date) -> None:
    try:
        LAST_SCAN_STATE.write_text(d.isoformat(), encoding="utf-8")
    except Exception as exc:
        # FIX 2026-05-26 (H1): state save fail kritik — daemon restart'ta
        # tarama tekrar yapılır (idempotent değilse double scan)
        sys.stderr.write(f"WARN _save_last_scan_date fail: {exc}\n")


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
    except Exception as exc:
        # FIX 2026-05-26 (H1): bozuk kill_switch.json fark edilsin
        sys.stderr.write(f"WARN _kill_switch_active parse fail (treating as not halted): {exc}\n")
        return False, ""  # bozuk dosya = halted değil (fail-safe)


def log(msg: str):
    ts = datetime.now(timezone.utc).strftime('%H:%M:%S')
    line = f"[{ts}] {msg}"
    # FIX 2026-05-26 (C1): flush + fsync — crash sonrası log kaybını önler.
    # Önceki versiyon Python buffer'da bırakıyordu; SIGKILL/OOM sonrası son
    # N satır disk'e yazılmamış kalıyordu (post-mortem yapılamıyordu).
    try:
        with open(LOG_FILE, 'a', encoding='utf-8') as f:
            f.write(line + "\n")
            f.flush()
            try:
                os.fsync(f.fileno())  # kernel buffer → disk garantili
            except OSError:
                pass  # bazı dosya sistemleri fsync desteklemez
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
    """PyramidStore singleton (lazy init).

    FIX 2026-05-26 (M3): init fail → push_critical Telegram alert.
    Önceden in-memory mode silent fallback'e düşüyordu — restart'ta
    aktif pyramid pozisyonları kayboluyordu (bot duplicate layer-up
    açma riski). Şimdi: data/ permission check + alert.
    """
    global _pyramid_store
    if _pyramid_store is not None:
        return _pyramid_store

    # Önce data/ dizini yazılabilir mi kontrol et (defansif)
    try:
        data_dir = Path("data")
        data_dir.mkdir(parents=True, exist_ok=True)
        test_file = data_dir / ".pyramid_write_test"
        test_file.write_text("ok", encoding="utf-8")
        test_file.unlink()
    except Exception as perm_exc:
        log(f"PYRAMID_STORE_PERMISSION_FAIL: data/ yazılabilir değil ({perm_exc})")
        try:
            from price_action.orchestrator.notifications import push_critical
            push_critical(
                f"PyramidStore: data/ permission denied — "
                f"in-memory mode, restart = state KAYIP. "
                f"Permission'ları düzelt + daemon restart. ({perm_exc})",
                source="futures_daemon_pyramid",
            )
        except Exception:
            pass
        _pyramid_store = None
        return None

    try:
        from price_action.execution.pyramid_store import PyramidStore
        _pyramid_store = PyramidStore()
        log(f"PYRAMID_STORE: başlatıldı → {_pyramid_store._path}")
    except Exception as exc:
        log(f"PYRAMID_STORE_INIT_FAIL: {exc} — in-memory only (restart = state lost)")
        # FIX 2026-05-26 (M3): Silent değil — Principal hemen bilsin
        try:
            from price_action.orchestrator.notifications import push_critical
            push_critical(
                f"PyramidStore INIT FAIL: {str(exc)[:200]} — "
                f"daemon in-memory mode'a düştü. Restart sonrası aktif "
                f"pyramid pozisyonları kaybolur (duplicate layer-up riski).",
                source="futures_daemon_pyramid",
            )
        except Exception:
            pass
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
        import yaml as _yaml_gr
        _gr_yaml_path = _risk_config_15m()
        try:
            with open(_gr_yaml_path, "r", encoding="utf-8") as _gr_f:
                _gr_cfg = _yaml_gr.safe_load(_gr_f) or {}
        except Exception as _gr_load_exc:
            # FIX 2026-05-26 (H1): config eksikliği görünür olsun
            log(f"WARN _get_pyramid_router config load fail: {_gr_load_exc} — defaults kullanılıyor")
            _gr_cfg = {}
        _gr_exec = _gr_cfg.get("execution", {})
        _gr_po_enabled = bool(_gr_exec.get("post_only_limit_enabled", False))
        _gr_po_timeout = int(_gr_exec.get("post_only_fallback_seconds", 30))
        _gr_slip_limit = float(_gr_exec.get("slippage_limit_bps", 25.0))
        # pyramid_slippage_limit_bps: entry slippage_limit_bps'den ayrı,
        # pyramid leg market-fallback için daha geniş tolerans (default 50bps).
        _gr_pyr_slip = float(_gr_exec.get("pyramid_slippage_limit_bps", 50.0))
        from price_action.execution.pyramid_router import PyramidRouter
        from price_action.execution.idempotency import IdempotencyStore
        from price_action.execution.slippage_tracker import SlippageTracker
        _pyramid_router_instance = PyramidRouter(
            exchange=exchange,
            idempotency_store=IdempotencyStore(),
            slippage_tracker=SlippageTracker(),
            post_only_enabled=_gr_po_enabled,
            fallback_seconds=_gr_po_timeout,
            slippage_limit_bps=_gr_pyr_slip,
            mode=os.environ.get("PA_RUN_MODE", "paper"),
        )
        log(f"PYRAMID_ROUTER: başlatıldı (post_only={_gr_po_enabled}, slip_limit={_gr_pyr_slip}bps)")
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
                            _prot_fill_px = float(triggered.get('triggerPrice', 0) or 0)
                            log(f"PROT_FILL: {sym} {triggered_kind} HIT @ ${_prot_fill_px} (status={status_alg})")
                            # SEC26.B-3 + B-4: closed-trade journal write (canonical TradeJournal).
                            # G14: slippage kaydı sig_row verisiyle birlikte (gerçek qty + side).
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
                                    # G14: TP/SL fill slippage kaydı (sig_row verisiyle)
                                    try:
                                        from price_action.execution.slippage_tracker import SlippageTracker as _ST_prot
                                        _st_prot = _ST_prot()
                                        _prot_qty = float(qty or 0.0)
                                        _prot_notional = _prot_qty * _prot_fill_px
                                        _prot_fee_bps = 4.0  # algo order = maker
                                        _prot_fee_usdt = _prot_notional * _prot_fee_bps / 10_000
                                        _st_prot.record_fill(
                                            fill_id=f"prot_{prot_id}_{triggered_kind.lower()}",
                                            ts=now_close,
                                            symbol=str(sym_sig),
                                            strategy=f"{str(strat or '')}_{triggered_kind.lower()}",
                                            side=str(side_sig).lower(),
                                            expected_price=_prot_fill_px,
                                            realized_price=_prot_fill_px,
                                            quantity=_prot_qty,
                                            fee_usdt=_prot_fee_usdt,
                                            is_maker=True,
                                            order_type="algo_stop_market",
                                            mode=os.environ.get("PA_RUN_MODE", "paper"),
                                            exchange_order_id=str(triggered.get('algoId', '')),
                                            fill_type=triggered_kind.lower(),  # 'tp'|'sl' — Batch C/D koordinasyon
                                            tf="15m",
                                        )
                                    except Exception as _st_prot_err:
                                        log(f"  PROT_SLIP_RECORD_ERR prot_id={prot_id}: {str(_st_prot_err)[:100]}")
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

                                        # FIX 2026-05-26 (Faz 14.5): Telegram position-close bildirimi
                                        if inserted:
                                            try:
                                                from price_action.orchestrator.notifications import notify_position_close
                                                # PnL hesabı
                                                _side = str(side_sig).lower()
                                                _entry = float(entry_p or 0.0)
                                                _exit = float(exit_p)
                                                _qty = float(qty or 0.0)
                                                if _side == "long":
                                                    _pnl = (_exit - _entry) * _qty
                                                else:
                                                    _pnl = (_entry - _exit) * _qty
                                                # R hesabı
                                                _sl = float(sl_p or 0.0)
                                                _r = 0.0
                                                if _sl and _entry:
                                                    _sl_dist = abs(_entry - _sl)
                                                    if _sl_dist > 0:
                                                        _r = _pnl / (_sl_dist * _qty)
                                                _notional = _qty * _entry
                                                # FIX 2026-05-26: tz normalize (DuckDB tz-naive, now_close tz-aware)
                                                _hold_s = None
                                                if ts_open:
                                                    try:
                                                        _tso = ts_open if ts_open.tzinfo else ts_open.replace(tzinfo=timezone.utc)
                                                        _tsc = now_close if now_close.tzinfo else now_close.replace(tzinfo=timezone.utc)
                                                        _hold_s = (_tsc - _tso).total_seconds()
                                                    except Exception:
                                                        _hold_s = None
                                                notify_position_close(
                                                    bot="futures15m",
                                                    symbol=str(sym_sig),
                                                    side=_side,
                                                    strategy=str(strat or ""),
                                                    entry_price=_entry,
                                                    exit_price=_exit,
                                                    qty=_qty,
                                                    notional_usdt=_notional,
                                                    realized_pnl_usdt=_pnl,
                                                    realized_r=_r,
                                                    close_reason=close_reason,
                                                    hold_seconds=_hold_s,
                                                )
                                            except Exception as _tn_exc:
                                                log(f"  TELEGRAM_CLOSE_FAIL: {_tn_exc}")
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
                    # G22: pyramid kaydı yok → exchange'deki mevcut SL emrini intended_sl olarak kullan.
                    # Restart sonrası _pyramid_positions boş; borsadaki SL zaten yerleştirilmiş →
                    # onu taban al. Bu yeterli: trailing, ratchet ve TP2 hesabı çalışmaya devam eder.
                    # NOT: _calc_entry da borsa entry'ye düşer (aşağıdaki fallback ile uyumlu).
                    if _cur_sl is not None and _cur_sl > 0:
                        _intended_sl = _cur_sl
                        log(f"  PROT_WATCHDOG_G22: {_sym_algo} pyramid kaydı yok — "
                            f"exchange SL ${_cur_sl} intended_sl olarak kullanılıyor")
                    else:
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
    return next_tf_boundary(15)


def next_5m_boundary() -> datetime:
    """Bir sonraki 5 dakikalık bar kapanış anını (UTC, sekunde sıfır) döner.

    Örnekler:
      14:07 UTC → 14:10 UTC
      14:13 UTC → 14:15 UTC
      14:58 UTC → 15:00 UTC
    """
    return next_tf_boundary(5)


def next_tf_boundary(tf_minutes: int) -> datetime:
    """Generic: bir sonraki tf-dakikalık bar boundary'sini döner."""
    now = datetime.now(timezone.utc)
    minute = now.minute
    next_min = ((minute // tf_minutes) + 1) * tf_minutes
    if next_min >= 60:
        new_hour = now.hour + 1
        if new_hour >= 24:
            tomorrow = now + timedelta(days=1)
            return tomorrow.replace(hour=0, minute=0, second=0, microsecond=0)
        return now.replace(hour=new_hour, minute=0, second=0, microsecond=0)
    return now.replace(minute=next_min, second=0, microsecond=0)


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
    # WIRE-widestop fix (2026-05-22): 15m daemon journal-tablo init.
    # run_15m_mode init_futures_journal()'i HİÇ çağırmıyordu → taze
    # futures_journal.duckdb'de futures_protection_orders / futures_signals vb.
    # tablolar yoktu (PROT_CHECK ERROR + ilk pozisyonda INSERT patlardı). 1d yolu
    # (_init_dead_mans_switch) bunu yapıyor; 15m yolu atlamıştı. CREATE TABLE IF
    # NOT EXISTS → idempotent, mevcut DB'ye zarar vermez.
    try:
        from scripts.futures_trade_daily import init_futures_journal
        init_futures_journal()
        log("15M_JOURNAL_INIT: futures_journal tabloları hazır")
    except Exception as _ji_err:
        log(f"15M_JOURNAL_INIT_ERR: {_ji_err} — journal tabloları eksik kalabilir")

    try:
        from price_action.execution.dead_mans_switch import DeadMansSwitch
        from scripts.futures_trade_daily import get_futures_exchange as _get_fx_dms
        # G21 fix (hard review 2026-05-21): DMS'e gerçek exchange ver — eskiden
        # exchange=None idi → _emergency_flatten pozisyon kapatamıyordu (sahte
        # güvenlik). Ayrı instance: DMS watchdog thread'i ana loop ile çakışmasın.
        _dms_exchange = _get_fx_dms()
        dms_15m = DeadMansSwitch(exchange=_dms_exchange, service_name="futures_daemon_15m", tf="15m")
        dms_15m.start()
        log("15M_DMS: başlatıldı (tf=15m, heartbeat=20s, timeout=1800s, flatten AKTİF)")
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
    # Post-only flag 15m YAML'den okunur (2026-05-21: paper fill rate %87.5 → enabled)
    _pyramid_router_15m = None
    try:
        import yaml as _yaml_pr
        _pr_yaml_path = _risk_config_15m()
        with open(_pr_yaml_path, "r", encoding="utf-8") as _pr_f:
            _pr_cfg = _yaml_pr.safe_load(_pr_f) or {}
        _pr_exec = _pr_cfg.get("execution", {})
        _pr_po_enabled = bool(_pr_exec.get("post_only_limit_enabled", False))
        _pr_po_timeout = int(_pr_exec.get("post_only_fallback_seconds", 30))
        _pr_slip_limit = float(_pr_exec.get("slippage_limit_bps", 25.0))
        # pyramid_slippage_limit_bps: pyramid leg için ayrı market-fallback cap (default 50bps)
        _pr_pyr_slip = float(_pr_exec.get("pyramid_slippage_limit_bps", 50.0))
        from price_action.execution.pyramid_router import PyramidRouter
        from price_action.execution.idempotency import IdempotencyStore
        from price_action.execution.slippage_tracker import SlippageTracker
        _pyramid_router_15m = PyramidRouter(
            exchange=None,   # başlangıçta None; exchange signal submit sonrası set edilir
            idempotency_store=IdempotencyStore(),
            slippage_tracker=SlippageTracker(),
            post_only_enabled=_pr_po_enabled,
            fallback_seconds=_pr_po_timeout,
            slippage_limit_bps=_pr_pyr_slip,
            mode=os.environ.get("PA_RUN_MODE", "paper"),
        )
        log(f"15M_PYRAMID: PyramidRouter başlatıldı (SEC54.3, post_only={_pr_po_enabled}, "
            f"timeout={_pr_po_timeout}s, slip={_pr_pyr_slip}bps)")
    except Exception as e:
        log(f"15M_PYRAMID_WARN: {e} — pyramid hook atlanıyor")

    # WIRE-widestop (2026-05-22): 15m wide-stop deploy filter threshold.
    # Reject signals whose entry sl_pct = |entry - sl| / entry < sl_pct_min.
    # Read once at startup from the active 15m config's execution block.
    # Default 0.0 = OFF → no signal is rejected → byte-identical to pre-WIRE
    # behavior. Deploy value (0.025) lives in the wide-stop config; activate
    # via PA_15M_CONFIG. See DEPLOY_widestop_15m.md.
    # FIX 2026-05-26 (H4): config load fail → SAFE DEFAULT + CRIT alert
    # Önceden _sl_pct_min_15m=0.0 fallback → widestop filter KAPALI → TÜM
    # sinyaller geçer (catastrophic). Yeni: fail safe (1.0 = %100, hiçbir
    # sinyal geçemez) + push_critical.
    _sl_pct_min_15m = 0.0
    _sl_cfg_load_ok = False
    try:
        import yaml as _yaml_sl
        with open(_risk_config_15m(), "r", encoding="utf-8") as _sl_f:
            _sl_cfg_raw = _yaml_sl.safe_load(_sl_f) or {}
        _sl_pct_min_15m = float(
            (_sl_cfg_raw.get("execution", {}) or {}).get("sl_pct_min", 0.0)
        )
        _sl_cfg_load_ok = True
    except Exception as _sl_err:
        log(f"15M_WIDESTOP_CFG_FAIL: {_sl_err} — SAFE DEFAULT sl_pct_min=1.0 (TÜM sinyaller reddedilecek)")
        _sl_pct_min_15m = 1.0  # %100 — hiçbir sinyal bunu geçemez
        # Telegram alert: config eksikse Principal HEMEN bilsin
        try:
            from price_action.orchestrator.notifications import push_critical as _pc_h4
            _pc_h4(
                f"15m risk config LOAD FAIL — daemon SAFE MODE'da "
                f"(sl_pct_min=1.0, tüm sinyaller reddedilir). "
                f"Path: {_risk_config_15m()} | Err: {str(_sl_err)[:120]}",
                source="futures15m_startup",
            )
        except Exception:
            pass
    if _sl_cfg_load_ok and _sl_pct_min_15m > 0.0:
        log(f"15M_WIDESTOP: sl_pct_min={_sl_pct_min_15m:.4f} AKTİF — "
            f"dar-stop sinyaller REJECT edilecek")
    elif not _sl_cfg_load_ok:
        log(f"15M_WIDESTOP_SAFE_MODE: sl_pct_min={_sl_pct_min_15m:.4f} "
            f"(config load fail — tüm sinyaller reddedilir; config'i düzelt + daemon restart)")

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

    # FIX 2026-05-26 (Faz 14.1): Provenance banner — config açıkça beyan
    try:
        from price_action.ops.provenance import config_provenance, format_banner
        _prov = config_provenance(_risk_config_15m())
        for _line in format_banner(_prov, component="FUTURES 15M").splitlines():
            log(_line)
    except Exception as _prov_exc:
        log(f"PROVENANCE_BANNER_FAIL: {_prov_exc}")

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

                    # WIRE-widestop (2026-05-22): wide-stop deploy filter.
                    # Reject narrow-stop signals — entry sl_pct < threshold.
                    # sl_pct is known here from the scan (entry_price + sl_price,
                    # both ATR-derived at bar close → causal, no look-ahead).
                    # _sl_pct_min_15m=0.0 (default) → this block never rejects.
                    # See DEPLOY_widestop_15m.md.
                    if _sl_pct_min_15m > 0.0:
                        _ws_entry = float(sig.get("entry_price") or 0.0)
                        _ws_sl = float(sig.get("sl_price") or 0.0)
                        _ws_sl_pct = (
                            abs(_ws_entry - _ws_sl) / _ws_entry
                            if _ws_entry > 0 else 0.0
                        )
                        if _ws_sl_pct < _sl_pct_min_15m:
                            log(f"  15M_REJECT_WIDESTOP: {sig.get('symbol','?')} "
                                f"sl_pct={_ws_sl_pct:.4f} < {_sl_pct_min_15m:.4f}")
                            continue

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
                        _risk_yaml_path = _risk_config_15m()
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

                                # G20: Deterministik fingerprint → idempotency guard
                                # Sinyal parmak izi: symbol + side + strategy + bar_close_ts
                                # Format: PA_{fp[:16]} (Binance max 36 char → 19 char, güvenli)
                                import hashlib as _hashlib
                                _fp_src = (
                                    f"{sig['symbol']}|{sig.get('side','')}|"
                                    f"{sig.get('strategy','')}|"
                                    f"{str(sig.get('bar_close_ts') or sig.get('ts',''))}"
                                )
                                _fp = _hashlib.sha256(_fp_src.encode()).hexdigest()[:16]
                                _coid = f"PA_{_fp}"  # max 19 char (< 36 limit)

                                from price_action.execution.idempotency import IdempotencyStore as _IdemStore
                                _idem = _IdemStore()
                                if _idem.is_seen(_fp):
                                    log(f"  15M_IDEM_SKIP: {sig['symbol']} {sig.get('strategy','')} "
                                        f"fp={_fp} — zaten gönderildi (restart/duplicate scan)")
                                    continue

                                _idem.mark_submitted(_fp, symbol=sig["symbol"], side=_order_side)

                                # ── POST-ONLY ENTRY PATH (2026-05-21) ──────────────────────────
                                # Config-gated: post_only_limit_enabled (default False → backward-compat)
                                # 1d pattern (futures_trade_daily.py:331-343) birebir izlendi.
                                # Idempotency: _coid her iki yolda da geçilir.
                                # SlippageExceededError: yakala, logla, o sinyali skip et, devam et.
                                _15m_po_enabled = bool(
                                    _risk_cfg.get("execution", {}).get("post_only_limit_enabled", False)
                                )
                                _15m_po_timeout = int(
                                    _risk_cfg.get("execution", {}).get("post_only_fallback_seconds", 30)
                                )
                                _15m_slip_limit = float(
                                    _risk_cfg.get("execution", {}).get("slippage_limit_bps", 25.0)
                                )
                                _fill_method = "market_only"
                                try:
                                    if _15m_po_enabled:
                                        from price_action.execution.post_only_router import (
                                            place_post_only_with_fallback as _po_place,
                                            SlippageExceededError as _SlipErr,
                                        )
                                        _order, _fill_method = _po_place(
                                            _ex_submit,
                                            symbol=sig["symbol"],
                                            side=_order_side,
                                            qty=_qty,
                                            target_price=_cur_px,
                                            fallback_after_sec=_15m_po_timeout,
                                            slippage_limit_bps=_15m_slip_limit,
                                            client_order_id=_coid,
                                        )
                                        log(f"  15M_PO_ENTRY: {sig['symbol']} method={_fill_method} "
                                            f"coid={_coid}")
                                    else:
                                        _order = _ex_submit.create_market_order(
                                            sig["symbol"], _order_side, _qty,
                                            params={"newClientOrderId": _coid},
                                        )
                                        _fill_method = "market_only"
                                except Exception as _entry_exc:
                                    # SlippageExceededError veya başka hata — sinyali skip et
                                    _exc_name = type(_entry_exc).__name__
                                    if "SlippageExceeded" in _exc_name:
                                        log(f"  15M_SLIP_EXCEEDED: {sig['symbol']} {_entry_exc} — sinyal atlandı")
                                        _idem.mark_filled(_fp, "", 0.0, 0.0)
                                        continue

                                    # FIX 2026-05-26 v2: H6 düzeltme — DEFERRED QUEUE pattern.
                                    # Önceki versiyon time.sleep(30+60)=90s ile daemon ana
                                    # döngüyü bloke ediyordu (position monitor + diğer sembol
                                    # sinyalleri gecikti). Yeni: timeout durumunda sinyali
                                    # data/pending_retries.jsonl'e yaz ve continue.
                                    # Scheduler _job_process_pending_entries (her 60s)
                                    # bu kuyruğu işler, retry yapar, fill ederse journal
                                    # yazar. Daemon hiç bloke olmaz.
                                    _err_str = str(_entry_exc)
                                    _is_timeout = (
                                        "RequestTimeout" in _exc_name
                                        or "-1007" in _err_str
                                        or "timeout" in _err_str.lower()
                                        or "Timeout" in _err_str
                                    )
                                    if _is_timeout:
                                        # Deferred retry queue'ya yaz, daemon bloke olma
                                        try:
                                            _pending_path = Path("data/pending_retries.jsonl")
                                            _pending_path.parent.mkdir(parents=True, exist_ok=True)
                                            _pending_entry = {
                                                "ts": datetime.now(timezone.utc).isoformat(),
                                                "tf": "15m",
                                                "symbol": sig["symbol"],
                                                "strategy": sig.get("strategy", ""),
                                                "side": sig["side"],
                                                "qty": _qty,
                                                "entry_px": _cur_px,
                                                "sl_price": sig.get("sl_price"),
                                                "tp_price": sig.get("tp_price"),
                                                "leverage": _lev,
                                                "client_order_id": _coid,
                                                "attempts": 0,  # scheduler bunu artırır
                                                "max_attempts": 2,
                                                "max_age_seconds": 120,  # 2 dk window
                                                "orig_error": f"{_exc_name}: {str(_entry_exc)[:200]}",
                                            }
                                            with open(_pending_path, "a", encoding="utf-8") as _pf:
                                                _pf.write(json.dumps(_pending_entry, default=str) + "\n")
                                            log(f"  15M_ENTRY_DEFERRED: {sig['symbol']} → pending_retries queue "
                                                f"(daemon devam ediyor, retry async)")
                                        except Exception as _q_exc:
                                            log(f"  15M_QUEUE_FAIL: {sig['symbol']} {_q_exc}")
                                        # NOT: _idem.mark_filled YAPMA — retry başarılı olursa
                                        # işaretlemez, sonsuz queue riski. Scheduler retry
                                        # sonucuna göre mark_filled yapar.
                                        continue

                                    # Non-timeout hata: doğrudan miss, audit + alert
                                    log(f"  15M_ENTRY_ERR: {sig['symbol']} {_exc_name}: {str(_entry_exc)[:120]}")
                                    try:
                                        _missed_path = Path("data/missed_signals.jsonl")
                                        _missed_path.parent.mkdir(parents=True, exist_ok=True)
                                        _missed_entry = {
                                            "ts": datetime.now(timezone.utc).isoformat(),
                                            "tf": "15m",
                                            "symbol": sig["symbol"],
                                            "strategy": sig.get("strategy", ""),
                                            "side": sig["side"],
                                            "entry_px": _cur_px,
                                            "sl_px": sig.get("sl_price"),
                                            "error": f"{_exc_name}: {str(_entry_exc)[:200]}",
                                            "retried": False,
                                        }
                                        with open(_missed_path, "a", encoding="utf-8") as _mf:
                                            _mf.write(json.dumps(_missed_entry, default=str) + "\n")
                                    except Exception:
                                        pass
                                    try:
                                        from price_action.orchestrator.notifications import push_critical
                                        push_critical(
                                            f"15m ENTRY MISSED: {sig['symbol']} {sig['side']} "
                                            f"{sig.get('strategy','')} — {_exc_name} "
                                            f"({str(_entry_exc)[:80]})",
                                            source="futures15m",
                                        )
                                    except Exception:
                                        pass
                                    _idem.mark_filled(_fp, "", 0.0, 0.0)
                                    continue  # bu sinyali atla, daemon devam et

                                _avg_px = float(_order.get("average") or _order.get("price") or _cur_px)
                                _fill_qty = float(_order.get("filled") or _qty)
                                _sig_id = _uuid.uuid4().hex[:16]
                                _idem.mark_filled(_fp, str(_order.get("id", "")), _avg_px, _fill_qty)

                                log(f"  15M_FILL: [{sig['side'].upper()}] {sig['symbol']} "
                                    f"{sig.get('strategy','')} qty={_fill_qty:.4f} "
                                    f"px=${_avg_px:.4f} lev={_lev}x id={_order.get('id','?')} "
                                    f"coid={_coid} method={_fill_method}")

                                # FIX 2026-05-26 (Faz 14.5): Telegram position-open bildirimi
                                try:
                                    from price_action.orchestrator.notifications import notify_position_open
                                    _entry_notional_telegram = _fill_qty * _avg_px
                                    _margin_telegram = _entry_notional_telegram / max(int(_lev or 1), 1)
                                    notify_position_open(
                                        bot="futures15m",
                                        symbol=sig["symbol"],
                                        side=sig["side"],
                                        strategy=sig.get("strategy", ""),
                                        entry_price=_avg_px,
                                        qty=_fill_qty,
                                        notional_usdt=_entry_notional_telegram,
                                        margin_usdt=_margin_telegram,
                                        leverage=int(_lev or 1),
                                        sl_price=sig.get("sl_price"),
                                        tp_price=sig.get("tp_price"),
                                    )
                                except Exception as _notify_exc:
                                    log(f"  TELEGRAM_OPEN_FAIL: {_notify_exc}")

                                # G14: Entry fill slippage kaydı — maker/taker fee method'a göre
                                try:
                                    from price_action.execution.slippage_tracker import SlippageTracker as _ST
                                    _st = _ST()
                                    _entry_notional = _fill_qty * _avg_px
                                    # post_only_filled → maker rebate (~4bps), market_fallback → taker (~8bps)
                                    _is_maker = (_fill_method == "post_only_filled")
                                    _entry_fee_bps = 4.0 if _is_maker else 8.0
                                    _entry_fee_usdt = _entry_notional * _entry_fee_bps / 10_000
                                    _st.record_fill(
                                        fill_id=f"entry_{_sig_id}",
                                        ts=datetime.now(timezone.utc),
                                        symbol=sig["symbol"],
                                        strategy=sig.get("strategy", ""),
                                        side=sig["side"],
                                        expected_price=_cur_px,
                                        realized_price=_avg_px,
                                        quantity=_fill_qty,
                                        fee_usdt=_entry_fee_usdt,
                                        is_maker=_is_maker,
                                        order_type=("limit" if _is_maker else "market"),
                                        mode=os.environ.get("PA_RUN_MODE", "paper"),
                                        exchange_order_id=str(_order.get("id", "")),
                                        client_order_id=_coid,
                                        tf="15m",
                                    )
                                except Exception as _st_err:
                                    log(f"    15M_SLIP_ENTRY_ERR: {str(_st_err)[:100]}")

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

                # ------ G19: DDBreaker standalone tick (bar-close, sinyal-bağımsız) ------
                # Breaker sadece evaluate() sırasında güncelleniyordu → sinyal gelmediğinde
                # (düşük volatilite saatleri) DD breaker sessizce geç tetikleniyordu.
                # Çözüm: her bar-close'da hesap durumunu breaker'a bildir.
                try:
                    from scripts.futures_trade_daily import get_futures_exchange, fetch_futures_state
                    from scripts.lib.risk_integration import build_futures_account_state, load_risk_officer
                    _g19_risk_yaml = _risk_config_15m()
                    _g19_state_path = ROOT / "logs" / "risk" / "futures_breaker_state_15m_phoenix.json"
                    _g19_ro = load_risk_officer(
                        yaml_path=_g19_risk_yaml,
                        breaker_state_path=_g19_state_path,
                    )
                    _g19_ex = get_futures_exchange()
                    _g19_state = fetch_futures_state(_g19_ex)
                    _g19_acct = build_futures_account_state(_g19_state, journal_path=JOURNAL)
                    _g19_snap = _g19_ro.breaker.update_from_account(_g19_acct)
                    if any(_g19_snap.values()):
                        log(f"15M_BREAKER_TICK: triggered={_g19_snap}")
                except Exception as _g19_err:
                    log(f"15M_BREAKER_TICK_ERR: {str(_g19_err)[:120]}")

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


# =============================================================================
# Faz 5 — 5m P1c daemon mode (paper-only, P1c walker delege)
# =============================================================================

def run_5m_mode(once: bool = False) -> None:
    """5 dakikalık intraday daemon — P1c walker paper-deploy.

    Tasarım: 15m'in MİNİMAL kopyası değil — temiz P1c-spesifik loop:
    - Bar timing: UTC :00/:05/.../:55 + 5s buffer
    - Signal scan: vsa_climax_test only (config: drop_strategies)
    - WIDESTOP filter: sl_pct >= 0.030
    - P1c walker delege: monthly halt + 3-loss + rolling DD + vol_z sizing
    - Journal: data/futures_journal_5m.duckdb (15m'den AYRI PnL)
    - Log: logs/futures_daemon_5m.log
    - DMS: service_name=futures_daemon_5m (15m DMS'le ayrı)

    HARDLIMIT: paper-only (PA_RUN_MODE=paper); live için Principal sign-off.
    """
    log_5m = lambda msg: _log_5m(msg)
    log_5m("============================================================")
    log_5m("FUTURES 5M P1C DAEMON STARTED")
    log_5m("  - Signal scan: her 5 dakikada (bar-close + 5s buffer)")
    log_5m("  - Strategy: vsa_climax_test (P1c W1 base)")
    log_5m("  - sl_pct_min: 0.030 (wide-stop)")
    log_5m("  - Walker: P1c (monthly halt + 3-loss + rolling 14d DD + vol_z)")
    log_5m("  - Journal: data/futures_journal_5m.duckdb (15m'den AYRI)")
    log_5m("============================================================")

    # FIX 2026-05-26 (Faz 14.1): Provenance banner
    try:
        from price_action.ops.provenance import config_provenance, format_banner
        _prov_5m = config_provenance(_risk_config_5m())
        for _line in format_banner(_prov_5m, component="FUTURES 5M P1C").splitlines():
            log_5m(_line)
    except Exception as _prov_exc:
        log_5m(f"PROVENANCE_BANNER_FAIL: {_prov_exc}")

    # P1c walker init
    p1c_walker = None
    try:
        from price_action.execution.p1c_walker import P1cWalker
        p1c_walker = P1cWalker(config_path=_risk_config_5m())
        log_5m(f"5M_P1C_WALKER: initialized (state={p1c_walker.state_summary()})")
    except Exception as e:
        log_5m(f"5M_P1C_WALKER_ERR: {e} — walker olmadan devam (sadece tarama)")

    # SL pct min config'den oku
    # FIX 2026-05-26 (H4): config load fail → SAFE DEFAULT 1.0 (tüm sinyaller red)
    # + push_critical alert. Önceden 0.030 fallback'i bot'u "açık" mod'da çalıştırıyordu.
    _sl_pct_min_5m = 0.030
    _cfg_load_ok_5m = False
    try:
        import yaml as _yaml
        with open(_risk_config_5m(), "r", encoding="utf-8") as f:
            _cfg = _yaml.safe_load(f) or {}
        _sl_pct_min_5m = float(_cfg.get("execution", {}).get("sl_pct_min", 0.030))
        _cfg_load_ok_5m = True
        log_5m(f"5M_WIDESTOP: sl_pct_min={_sl_pct_min_5m:.4f}")
    except Exception as e:
        log_5m(f"5M_CONFIG_FAIL: {e} — SAFE DEFAULT sl_pct_min=1.0 (TÜM sinyaller red)")
        _sl_pct_min_5m = 1.0  # %100 — hiçbir sinyal geçemez
        try:
            from price_action.orchestrator.notifications import push_critical as _pc_h4_5m
            _pc_h4_5m(
                f"5m risk config LOAD FAIL — daemon SAFE MODE "
                f"(sl_pct_min=1.0). Path: {_risk_config_5m()} | Err: {str(e)[:120]}",
                source="futures5m_startup",
            )
        except Exception:
            pass

    last_bar_boundary = None
    log_5m("5M_DAEMON_RUN_START")

    try:
        while True:
            # Kill switch
            halted, reason = _kill_switch_active()
            if halted:
                log_5m(f"5M_KILL_SWITCH ACTIVE — daemon exiting. Reason: {reason}")
                break

            # Sonraki 5m bar kapanışı + 5s buffer
            next_close = next_5m_boundary() + timedelta(seconds=5)
            log_5m(f"5M_WAIT: sonraki bar kapanış {next_close.strftime('%H:%M:%S')} UTC")
            sleep_until(next_close)

            current_boundary = next_close - timedelta(seconds=5)
            if last_bar_boundary is not None:
                bars_elapsed = int((current_boundary - last_bar_boundary).total_seconds() / 300)
                if bars_elapsed > 1:
                    log_5m(f"5M_MISSED_BARS: {bars_elapsed - 1} bar kaçırıldı "
                           f"(son={last_bar_boundary.strftime('%H:%M')}, "
                           f"şimdi={current_boundary.strftime('%H:%M')})")
            last_bar_boundary = current_boundary

            # P1c walker halt check
            if p1c_walker is not None:
                halt_status = p1c_walker.check_halts()
                if halt_status.get("halted"):
                    log_5m(f"5M_HALT_ACTIVE: {halt_status.get('reason')} "
                           f"(until={halt_status.get('release_at')})")
                    if once:
                        break
                    continue

            # Signal scan — vsa_climax_test only (P1c W1 base)
            scan_start = time.time()
            try:
                sigs = _scan_signals_5m(current_boundary)
            except Exception as e:
                log_5m(f"5M_SCAN_ERR: {e}")
                sigs = []

            scan_dur = time.time() - scan_start
            n_sig = len(sigs)
            log_5m(f"5M_SCAN: {n_sig} sinyal, latency={scan_dur:.1f}s")

            # WIDESTOP + P1c walker filter
            n_widestop = 0
            n_accept = 0
            for sig in sigs:
                sym = sig.get("symbol", "?")
                entry = float(sig.get("entry_price", 0))
                sl = float(sig.get("sl_price", 0))
                if entry > 0 and sl > 0:
                    sl_pct = abs(entry - sl) / entry
                    if sl_pct < _sl_pct_min_5m:
                        log_5m(f"  5M_REJECT_WIDESTOP: {sym} sl_pct={sl_pct:.4f} < {_sl_pct_min_5m:.4f}")
                        n_widestop += 1
                        continue

                # P1c walker karar verir (sizing, halt re-check)
                if p1c_walker is not None:
                    decision = p1c_walker.evaluate_signal(sig)
                    if not decision.get("accept", False):
                        log_5m(f"  5M_REJECT_P1C: {sym} reason={decision.get('reason', '?')}")
                        continue

                n_accept += 1
                log_5m(f"  5M_ACCEPT: {sym} sl_pct={sl_pct:.4f} risk_pct={decision.get('risk_pct', 0):.4f}")

                # Faz 5.3: walker.record_open_position + paper journal entry
                if p1c_walker is not None:
                    try:
                        from datetime import datetime as _dt, timezone as _tz
                        position = {
                            "symbol": sym,
                            "side": sig.get("side", "?"),
                            "entry_price": entry,
                            "sl_price": sl,
                            "tp_price": float(sig.get("tp_price", 0)),
                            "strategy": sig.get("strategy", "?"),
                            "risk_pct": decision.get("risk_pct", 0),
                            "risk_usdt": decision.get("risk_usdt", 0),
                            "tier": decision.get("tier", "?"),
                            "vol_z": sig.get("vol_z", 0),
                            "entry_ts": _dt.now(_tz.utc).isoformat(),
                        }
                        p1c_walker.record_open_position(position)
                        log_5m(f"  5M_POSITION_OPENED: {sym} {sig.get('side')} risk=${decision.get('risk_usdt', 0):.2f} tier={decision.get('tier')}")

                        # Paper journal entry (futures_journal_5m.duckdb)
                        _write_5m_journal_signal(sig, decision)

                        # FIX 2026-05-26 (Faz 14.5): Telegram position-open bildirimi
                        try:
                            from price_action.orchestrator.notifications import notify_position_open
                            _qty = float(decision.get("qty", position.get("qty", 0.0)))
                            _notional = _qty * float(entry)
                            # 5m P1c walker margin = notional (1x leverage paper)
                            notify_position_open(
                                bot="futures5m",
                                symbol=sym,
                                side=sig.get("side", "?"),
                                strategy=sig.get("strategy", "?"),
                                entry_price=float(entry),
                                qty=_qty,
                                notional_usdt=_notional,
                                margin_usdt=_notional,  # 1x paper
                                leverage=1,
                                sl_price=float(sl),
                                tp_price=float(sig.get("tp_price", 0)) or None,
                            )
                        except Exception as _tn_exc:
                            log_5m(f"  TELEGRAM_OPEN_FAIL: {_tn_exc}")
                    except Exception as e:
                        log_5m(f"  5M_POSITION_RECORD_ERR: {e}")

                # NOTE: real ccxt order submit Faz 5.3.2 — şu an walker state + journal yeterli

            # Faz 5.3: Position monitor — BE-protect + close trigger
            if p1c_walker is not None:
                try:
                    n_be, n_closed = _monitor_5m_positions(p1c_walker)
                    if n_be > 0:
                        log_5m(f"5M_BE_PROTECTED: {n_be} pozisyon SL → entry")
                    if n_closed > 0:
                        log_5m(f"5M_POSITIONS_CLOSED: {n_closed}")
                except Exception as e:
                    log_5m(f"5M_POSITION_MONITOR_ERR: {e}")

            log_5m(f"5M_TICK_DONE: scan={scan_dur:.1f}s widestop={n_widestop} accept={n_accept}")

            if once:
                log_5m("5M_ONCE_DONE")
                break
    except KeyboardInterrupt:
        log_5m("5M_DAEMON STOPPED (Ctrl+C)")
    except Exception as e:
        log_5m(f"5M_DAEMON_FATAL: {e}")
        import traceback
        log_5m(traceback.format_exc()[:2000])


def _log_5m(msg: str) -> None:
    """5m daemon log — ayrı dosya (futures_daemon_5m.log)."""
    ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    log_path = ROOT / "logs" / "futures_daemon_5m.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def _monitor_5m_positions(walker) -> tuple[int, int]:
    """Faz 5.3: Open 5m positions için BE-protect + SL/TP hit kontrolü.

    Her bar sonunda:
    1. Open positions için ccxt'ten current price çek
    2. walker.check_be_protect() — peak_R >= 0.5 → SL → entry
    3. SL veya TP hit ise walker.close_position() çağır (paper journal)

    Returns: (n_be_triggered, n_closed)
    """
    n_be = 0
    n_closed = 0

    positions = walker._state.get("open_positions", {})
    if not positions:
        return (0, 0)

    # ccxt'ten current prices çek
    try:
        import ccxt
        ex = ccxt.binance({
            "enableRateLimit": True,
            "options": {"defaultType": "future"},
            "timeout": 10000,
        })
        current_prices: dict[str, float] = {}
        for sym in positions.keys():
            try:
                ticker = ex.fetch_ticker(sym)
                current_prices[sym] = float(ticker.get("last", 0))
            except Exception:
                pass
    except Exception as e:
        _log_5m(f"5M_PRICE_FETCH_ERR: {e}")
        return (0, 0)

    # BE-protect
    be_triggered = walker.check_be_protect(current_prices)
    for be in be_triggered:
        n_be += 1
        _log_5m(f"  5M_BE: {be['symbol']} {be['side']} peak_R={be['peak_R']} "
                f"SL {be['old_sl']:.4f} → {be['new_sl']:.4f}")

    # SL/TP hit check (paper close)
    for symbol, pos in list(positions.items()):
        current = current_prices.get(symbol)
        if current is None or current <= 0:
            continue

        side = pos.get("side", "")
        entry = float(pos.get("entry_price", 0))
        sl = float(pos.get("sl_price", 0))
        tp = float(pos.get("tp_price", 0))

        close_reason = None
        if side == "long":
            if sl > 0 and current <= sl:
                close_reason = "be_hit" if pos.get("be_protected") else "sl_hit"
            elif tp > 0 and current >= tp:
                close_reason = "tp_hit"
        elif side == "short":
            if sl > 0 and current >= sl:
                close_reason = "be_hit" if pos.get("be_protected") else "sl_hit"
            elif tp > 0 and current <= tp:
                close_reason = "tp_hit"

        if close_reason:
            outcome = walker.close_position(symbol, close_price=current, reason=close_reason)
            if outcome:
                n_closed += 1
                _log_5m(f"  5M_CLOSE: {symbol} {side} reason={close_reason} "
                        f"price={current:.4f} pnl=${outcome['pnl_usdt']:+.2f} R={outcome['r_multiple']:+.2f}")
                # Journal'a closed trade yaz
                _write_5m_journal_trade_close(outcome)
                # FIX 2026-05-26 (Faz 14.5): Telegram position-close bildirimi
                try:
                    from price_action.orchestrator.notifications import notify_position_close
                    _entry = float(outcome.get("entry_price", entry))
                    _exit = float(outcome.get("close_price", current))
                    _qty = float(outcome.get("qty", pos.get("qty", 0.0)))
                    _notional = _qty * _entry
                    _hold_s = None
                    if outcome.get("open_ts") and outcome.get("close_ts"):
                        try:
                            from datetime import datetime as _dt
                            _ot = _dt.fromisoformat(str(outcome["open_ts"]))
                            _ct = _dt.fromisoformat(str(outcome["close_ts"]))
                            _hold_s = (_ct - _ot).total_seconds()
                        except Exception:
                            pass
                    notify_position_close(
                        bot="futures5m",
                        symbol=symbol,
                        side=side,
                        strategy=str(pos.get("strategy", "")),
                        entry_price=_entry,
                        exit_price=_exit,
                        qty=_qty,
                        notional_usdt=_notional,
                        realized_pnl_usdt=float(outcome["pnl_usdt"]),
                        realized_r=float(outcome["r_multiple"]),
                        close_reason=close_reason,
                        hold_seconds=_hold_s,
                    )
                except Exception as _tn_exc:
                    _log_5m(f"  TELEGRAM_CLOSE_FAIL: {_tn_exc}")

    return (n_be, n_closed)


def _write_5m_journal_trade_close(outcome: dict) -> None:
    """Closed trade'i futures_journal_5m.duckdb'ye yaz."""
    try:
        import duckdb
        import uuid
        journal_path = ROOT / "data" / "futures_journal_5m.duckdb"
        if not journal_path.exists():
            return

        con = duckdb.connect(str(journal_path))
        con.execute("""
            INSERT INTO futures_trades_closed
            (trade_id, ts_open, ts_close, sym, side, strategy,
             entry_price, exit_price, qty, realized_pnl_usdt, realized_r,
             win, close_reason)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            str(uuid.uuid4()),
            outcome.get("entry_ts", ""),
            outcome["close_ts"],
            outcome["symbol"],
            outcome["side"],
            outcome.get("strategy", "?"),
            outcome["entry_price"],
            outcome["close_price"],
            0.0,  # qty placeholder (Faz 5.3.2 real submit'ta)
            outcome["pnl_usdt"],
            outcome["r_multiple"],
            outcome["pnl_usdt"] > 0,
            outcome["reason"],
        ))
        con.commit()
        con.close()
    except Exception as e:
        _log_5m(f"  5M_JOURNAL_CLOSE_ERR: {e}")


def _write_5m_journal_signal(sig: dict, decision: dict) -> None:
    """Faz 5.3: futures_journal_5m.duckdb'ye signal entry yaz.

    Mevcut 15m futures_journal'ın schema'sını kullanır — ayrı PnL track için.
    """
    try:
        import duckdb
        import uuid
        journal_path = ROOT / "data" / "futures_journal_5m.duckdb"
        if not journal_path.exists():
            _log_5m(f"5M_JOURNAL_MISSING: {journal_path}")
            return

        con = duckdb.connect(str(journal_path))
        signal_id = str(uuid.uuid4())
        bar_close = sig.get("bar_close_ts") or sig.get("ts")
        if hasattr(bar_close, "to_pydatetime"):
            bar_close = bar_close.to_pydatetime()

        con.execute("""
            INSERT INTO futures_signals
            (signal_id, ts, symbol, strategy, side, sl_price, tp_price,
             confluence, leverage, status, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            signal_id,
            bar_close,
            sig.get("symbol", "?"),
            sig.get("strategy", "?"),
            sig.get("side", "?"),
            float(sig.get("sl_price", 0)),
            float(sig.get("tp_price", 0)),
            float(sig.get("confluence", 0)),
            1,  # leverage placeholder
            "ACCEPTED_PAPER",
            f"tier={decision.get('tier', '?')} risk_pct={decision.get('risk_pct', 0):.4f} risk_usdt={decision.get('risk_usdt', 0):.2f} vol_z={sig.get('vol_z', 0):+.2f}",
        ))
        con.commit()
        con.close()
        _log_5m(f"  5M_JOURNAL_WRITE: {signal_id[:8]} → futures_journal_5m.duckdb")
    except Exception as e:
        _log_5m(f"  5M_JOURNAL_ERR: {e}")


def _scan_signals_5m(target_dt: datetime) -> list:
    """5m tarama: scripts.futures_trade_5m.scan_signals_5m delege.

    Faz 5.2 fix (2026-05-25): scripts/futures_trade_5m.py oluşturuldu,
    artık gerçek 5m signal pipeline çalışıyor. P1c W1 base: vsa_climax_test
    only (engulfing_continuation drop_strategies'de). vol_z signal dict'inde
    döner — P1c walker M3a sizing için.
    """
    try:
        from scripts.futures_trade_5m import scan_signals_5m
        return scan_signals_5m(target_dt)
    except Exception as e:
        _log_5m(f"5M_SCAN_IMPORT_ERR: {e}")
        import traceback
        _log_5m(traceback.format_exc()[:1500])
        return []


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Futures Daemon — 1d, 15m veya 5m intraday mode")
    parser.add_argument("--once", action="store_true", help="Tek seferlik test (1d mode için)")
    parser.add_argument(
        "--timeframe",
        choices=["1d", "15m", "5m"],
        default="1d",
        help="Daemon timeframe: '1d' (default), '15m' (intraday), '5m' (P1c)",
    )
    args = parser.parse_args()

    if args.timeframe == "15m":
        run_15m_mode(once=args.once)
    elif args.timeframe == "5m":
        run_5m_mode(once=args.once)
    elif args.once:
        equity_snapshot()
        position_check()
        signal_scan_if_new_day()
    else:
        main_loop()
