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
import json
import os
import signal as _signal
import sys
import time
import traceback as _traceback
import uuid
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

os.environ["PA_LOG_QUIET"] = "1"
import warnings

warnings.filterwarnings("ignore")

import duckdb

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

# Multi-bot futures support
# FIX 2026-05-27 (Faz 14.25): generic — herhangi bir bot adına izin ver.
# FIX 2026-05-27 (Faz 14.26): idempotency + pyramid_store + DMS DB'leri de per-bot.
#   Önceki bug: PA_BOT_NAME sadece journal/log/state ayırıyordu, ama
#   idempotency.duckdb ve pyramid_store.duckdb shared kalmıştı → ikinci bot
#   startup'ta DuckDB lock conflict, DMS init fail (kritik güvenlik açığı).
_BOT_NAME = os.environ.get("PA_BOT_NAME", "").lower().strip()
if _BOT_NAME and _BOT_NAME not in ("default", ""):
    # Generic: PA_BOT_NAME=rsi2 → futures_journal_rsi2.duckdb
    JOURNAL = ROOT / "data" / f"futures_journal_{_BOT_NAME}.duckdb"
    LOG_FILE = ROOT / "logs" / f"futures_daemon_{_BOT_NAME}.log"
    LAST_SCAN_STATE = ROOT / "logs" / "state" / f"futures_last_scan_{_BOT_NAME}.txt"
    IDEMPOTENCY_DB = ROOT / "data" / f"idempotency_{_BOT_NAME}.duckdb"
    PYRAMID_STORE_DB = ROOT / "data" / f"pyramid_store_{_BOT_NAME}.duckdb"
    # FIX 2026-06-10 (v14 audit BLOCKER-2): breaker state de bot-bazlı olmalı.
    # Önceden iki yerde hardcoded "futures_breaker_state_15m_phoenix.json" idi →
    # yeni bot (v14) eski botun daily_anchor/triggered watermark'larını miras
    # alıyordu (d04/w08 eşikleri d02/w05 anchor'ı üstünde yanlış hesap).
    BREAKER_STATE_15M = ROOT / "logs" / "risk" / f"futures_breaker_state_15m_{_BOT_NAME}.json"
else:
    JOURNAL = ROOT / "data" / "futures_journal.duckdb"
    LOG_FILE = ROOT / "logs" / "futures_daemon.log"
    LAST_SCAN_STATE = ROOT / "logs" / "state" / "futures_last_scan.txt"
    IDEMPOTENCY_DB = ROOT / "data" / "idempotency.duckdb"
    PYRAMID_STORE_DB = ROOT / "data" / "pyramid_store.duckdb"
    # Backward-compat: PA_BOT_NAME yokken eski path korunur (çalışan botlar etkilenmez)
    BREAKER_STATE_15M = ROOT / "logs" / "risk" / "futures_breaker_state_15m_phoenix.json"
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


# FIX 2026-05-26 (Faz 14.9): pyramid_enabled gate — cached.
# Önceki bug: widestop_vsa2 config'inde strategy_portfolio.pyramid_enabled=false
# olmasına rağmen daemon her POS_CHECK tick'inde pyramid_store'dan eski L2 PENDING
# leg'i yükleyip submit etmeye çalışıyordu → Binance -1007 timeout sonsuz retry.
# Kök neden: _get_pyramid_router() ve POS_CHECK loop bu flag'i hiç okumuyordu.
_PYRAMID_ENABLED_CACHE: dict[str, bool] = {}

# FIX 2026-06-10 (XRP 02:15Z): orphan-cancel N-ardışık-tick stateful teyit.
# Anahtar "SYMBOL|algoId" → ardışık orphan-görünüm tick sayısı. Pozisyon tek
# tick'te bile görünse sıfırlanır. ORPHAN_CONFIRM_TICKS tick (~45dk) üst üste
# orphan görünmeden iptal YAPILMAZ (double-stale-read deliği kapanışı).
_ORPHAN_SUSPECT_TICKS: dict[str, int] = {}
ORPHAN_CONFIRM_TICKS = 3


def _pyramid_enabled_15m() -> bool:
    """15m active config'de strategy_portfolio.pyramid_enabled değerini döner.

    Cache: process-lifetime; config değişirse daemon restart gerek.
    """
    cache_key = "15m"
    if cache_key in _PYRAMID_ENABLED_CACHE:
        return _PYRAMID_ENABLED_CACHE[cache_key]
    try:
        import yaml as _yaml_pe

        _path = _risk_config_15m()
        with open(_path, encoding="utf-8") as _pe_f:
            _cfg = _yaml_pe.safe_load(_pe_f) or {}
        _enabled = bool(_cfg.get("strategy_portfolio", {}).get("pyramid_enabled", True))
    except Exception:
        _enabled = True  # safe default: behavior unchanged on read fail
    _PYRAMID_ENABLED_CACHE[cache_key] = _enabled
    return _enabled


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

        with open(KILL_SWITCH_PATH, encoding="utf-8") as f:
            ks = _json.load(f)
        if bool(ks.get("halted", False)):
            return True, str(ks.get("reason") or "no reason")
        return False, ""
    except Exception as exc:
        # FIX 2026-05-26 (H1): bozuk kill_switch.json fark edilsin
        sys.stderr.write(f"WARN _kill_switch_active parse fail (treating as not halted): {exc}\n")
        return False, ""  # bozuk dosya = halted değil (fail-safe)


_LOG_MAX_BYTES = 20 * 1024 * 1024  # 20 MB — yıllık ~250 MB cap


def _rotate_log_if_large(path) -> None:
    """FIX 2026-05-28 (Faz 14.27): basit log rotation.
    Log >20MB ise .1 → .2 → ... rotate. Maksimum 5 backup tutar (.5 silinir).

    FIX 2026-05-28 (audit-Y1): rotation fail SESSİZ değil → stderr'e warn.
    Önceden `except Exception: pass` ile permission/disk-full hatası gizliydi;
    log dosyası unbounded büyür, disk dolar, daemon ileride patlar. Şimdi
    en azından stderr'e (launchd log'una) düşüyor.
    """
    try:
        if not path.exists() or path.stat().st_size < _LOG_MAX_BYTES:
            return
        for i in range(5, 0, -1):
            old = path.with_suffix(path.suffix + f".{i}")
            new = path.with_suffix(path.suffix + f".{i+1}")
            if i == 5 and old.exists():
                old.unlink()
            elif old.exists():
                old.rename(new)
        path.rename(path.with_suffix(path.suffix + ".1"))
    except Exception as _rot_err:
        # FIX audit-Y1: silent fail → stderr (launchd capture eder)
        try:
            sys.stderr.write(
                f"[WARN] log rotation fail ({path}): {type(_rot_err).__name__}: {_rot_err}\n"
            )
            sys.stderr.flush()
        except Exception:
            pass


def log(msg: str):
    # FIX 2026-05-28 (audit-D2): timestamp'e Z suffix — UTC olduğu net göster.
    # Önceden `[12:45:24]` yazıyordu; kullanıcı TR sanıp 3 saat shift hatası
    # yapabiliyordu (gerçekte 12:45 UTC = 15:45 TR). Şimdi `[12:45:24Z]`.
    ts = datetime.now(UTC).strftime("%H:%M:%SZ")
    line = f"[{ts}] {msg}"
    # FIX 2026-05-26 (C1): flush + fsync — crash sonrası log kaybını önler.
    # Önceki versiyon Python buffer'da bırakıyordu; SIGKILL/OOM sonrası son
    # N satır disk'e yazılmamış kalıyordu (post-mortem yapılamıyordu).
    # FIX 2026-05-28 (Faz 14.27): log rotation — disk doldurma riski azalt.
    try:
        _rotate_log_if_large(LOG_FILE)
        with open(LOG_FILE, "a", encoding="utf-8") as f:
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

# FIX 2026-05-28 (audit-A1): graceful shutdown bayrağı + signal handler.
# Önceki bug: PID 17267 12:45 TR'de sessiz öldü; son log "15M_WAIT", crash log yok.
# Kök neden: signal handler yoktu (SIGTERM/SIGHUP gelince Python cleanup yaptı,
# resource_tracker warning'i stderr'e yazıldı, ama "shutdown" log'u futures_daemon.log'a
# düşmedi) + sleep_until try/except dışındaydı (uyku içi exception görünmüyordu).
_stop_flag: bool = False


def _install_signal_handlers() -> None:
    """SIGTERM / SIGHUP için handler kur — sessiz ölümü engelle.

    SIGINT (Ctrl+C) Python tarafından KeyboardInterrupt'a çevriliyor zaten,
    main loop onu yakalıyor. Burada SIGTERM (kill, launchd unload) ve
    SIGHUP (terminal kapanması) için log + _stop_flag set ediyoruz.
    Main loop her tick başında _stop_flag'i kontrol edip break edecek.
    """

    def _shutdown_handler(signum: int, frame) -> None:  # type: ignore[no-untyped-def]
        global _stop_flag
        try:
            sig_name = _signal.Signals(signum).name
        except Exception:
            sig_name = f"SIG{signum}"
        log(f"SIGNAL_RECEIVED: {sig_name} ({signum}) — graceful shutdown başlıyor")
        _stop_flag = True

    try:
        _signal.signal(_signal.SIGTERM, _shutdown_handler)
    except (ValueError, OSError) as _e:
        sys.stderr.write(f"WARN SIGTERM handler kurulamadı: {_e}\n")
    try:
        # SIGHUP Unix-only; Windows'ta AttributeError olabilir
        _signal.signal(_signal.SIGHUP, _shutdown_handler)
    except (ValueError, OSError, AttributeError) as _e:
        sys.stderr.write(f"WARN SIGHUP handler kurulamadı (Windows normal): {_e}\n")


def _init_dead_mans_switch(exchange):
    """Dead Man's Switch'i exchange ile başlat."""
    global _dms
    try:
        from price_action.execution.dead_mans_switch import DeadMansSwitch

        _dms = DeadMansSwitch(exchange, service_name="futures_daemon", db_path=IDEMPOTENCY_DB)
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
    from scripts.futures_trade_daily import (
        fetch_futures_state,
        get_futures_exchange,
        init_futures_journal,
    )

    init_futures_journal()
    try:
        ex = get_futures_exchange()
        state = fetch_futures_state(ex)
        con = duckdb.connect(str(JOURNAL))
        con.execute(
            """
            INSERT INTO futures_equity_snapshots VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
            (
                uuid.uuid4().hex[:16],
                datetime.now(UTC),
                state["wallet_balance"],
                state["unrealized_pnl"],
                state["margin_balance"],
                state["available_balance"],
                state["n_positions"],
                state["n_open_orders"],
                None,
            ),
        )
        con.commit()
        con.close()
        log(
            f"SNAPSHOT: wallet=${state['wallet_balance']:.2f}, "
            f"unrealized={state['unrealized_pnl']:+.2f}, "
            f"pos={state['n_positions']}, orders={state['n_open_orders']}"
        )
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

# FIX 2026-06-05: ORİJİNAL intended-SL cache. Key="SYMUSDT|side" → ilk SL fiyatı.
# Kök neden: v13'te pyramid KAPALI → entry'de _pyramid_positions kaydı oluşmuyor →
# watchdog G22 yolu hareketli borsa SL'ini intended_sl sanıyor → initial_r yanlış →
# TP1 sonrası trailing DONUYOR (kazanan pozisyon breakeven'a geri dönüp $0 kapanıyor;
# XRP +$64 → $0 olayı). Çözüm: girişte orijinal SL'i burada sakla, watchdog stabil bu
# değeri kullansın → BE-lock + trailing doğru çalışır. In-memory (restart'ta rebuild
# _pyramid_positions'ı journal'dan doldurur; bu cache running-açılan pozisyonları kapsar).
_ORIG_INTENDED_SL: dict[str, float] = {}

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

        _pyramid_store = PyramidStore(db_path=PYRAMID_STORE_DB)
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
            log(
                f"PYRAMID_STORE: {len(recovered)} pozisyon restart'tan kurtarıldı: "
                f"{list(recovered.keys())[:5]}"
            )
        else:
            log("PYRAMID_STORE: startup — kayıtlı aktif pozisyon yok")
    except Exception as exc:
        log(f"PYRAMID_STORE_LOAD_FAIL: {exc} — _pyramid_positions boş başladı")


def _rebuild_position_tracking_from_exchange(exchange) -> None:
    """Restart sonrası borsadaki açık pozisyonlar için takip kaydı yeniden kur.

    Kök neden: Daemon restart'ta pyramid_store.duckdb boşsa (ya da pozisyon
    pyramid dışı açılmışsa) _pyramid_positions boş kalır → PROT_WATCHDOG G22
    yolu _intended_sl olarak borsadaki MEVCUT SL'i kullanır → initial_r yanlış
    hesaplanır (SL zaten trailing ile taşınmış olabilir) → trailing donukluk.

    Bu fonksiyon:
      1. Borsadaki açık pozisyonları çeker.
      2. Her pozisyon için _pyramid_positions'da zaten kayıt varsa atlar.
      3. Yoksa: journal'dan orijinal entry + sl_price'ı arar (en son fill eşleşmesi).
         Journal'da bulunamazsa borsanın entry + mevcut algo SL'ini kullanır.
      4. Stub PyramidPosition (legs=[]) oluşturup _pyramid_positions'a ekler.
      5. pyramid_store'a YAZMAZ (pyramid_enabled=false bağımsızlığı korumak için).

    Güvenlik: sadece _pyramid_positions EKSIK kayıtları doldurur; mevcut kayıtlara
    dokunmaz. Strateji/risk config'e hiç dokunmaz. Exception → log + devam.
    """
    global _pyramid_positions
    try:
        from price_action.execution.pyramid_router import PyramidLeg, PyramidPosition
    except ImportError as _imp_err:
        log(f"REBUILD_TRACKING_SKIP: PyramidPosition import fail: {_imp_err}")
        return

    try:
        positions = exchange.fetch_positions()
        active_pos = [p for p in positions if abs(float(p.get("contracts", 0))) > 0]
    except Exception as _fetch_err:
        log(f"REBUILD_TRACKING_FAIL: borsa pozisyonları çekilemedi: {_fetch_err}")
        return

    if not active_pos:
        log("REBUILD_TRACKING: borsa'da açık pozisyon yok — atlanıyor")
        return

    # Journal bağlantısı: orijinal entry + sl_price lookup için
    _journal_map: dict[
        str, tuple[float, float, str]
    ] = {}  # "SYM|side" → (fill_price, sl_price, signal_id)
    try:
        _jcon = duckdb.connect(str(JOURNAL))
        try:
            _jrows = _jcon.execute(
                """
                SELECT symbol, side, fill_price, sl_price, signal_id
                FROM futures_signals
                WHERE fill_price > 0 AND status = 'filled'
                ORDER BY ts DESC
                """
            ).fetchall()
            # İlk eşleşmeyi (en yeni) al — sembol 'XLM/USDT' formatında
            for _jr in _jrows:
                _jsym, _jside, _jfill, _jsl, _jsid = _jr
                _key = f"{_jsym}|{_jside}"
                if _key not in _journal_map and _jfill and _jfill > 0 and _jsl and _jsl > 0:
                    _journal_map[_key] = (float(_jfill), float(_jsl), str(_jsid))
        finally:
            _jcon.close()
    except Exception as _jexc:
        log(f"REBUILD_TRACKING: journal okunamadı ({_jexc}) — borsa entry/SL kullanılacak")

    # Borsadaki algo SL'leri al (per-symbol hızlı lookup için)
    _algo_sl_map: dict[str, float] = {}  # "XLMUSDT" → triggerPrice
    try:
        _algo_ords = exchange.fapiPrivateGetOpenAlgoOrders()
        for _ao in _algo_ords or []:
            if _ao.get("orderType") == "STOP_MARKET":
                _ao_sym = str(_ao.get("symbol", ""))
                _ao_tp = float(_ao.get("triggerPrice") or 0)
                if _ao_sym and _ao_tp > 0:
                    _algo_sl_map[_ao_sym] = _ao_tp
    except Exception as _algo_err:
        log(f"REBUILD_TRACKING: algo SL'ler çekilemedi ({_algo_err}) — borsa entry kullanılacak")

    rebuilt_count = 0
    for pos in active_pos:
        _sym_ccxt = str(pos.get("symbol", ""))  # "XLM/USDT:USDT"
        _side_raw = str(pos.get("side", "")).lower()  # "long" / "short"
        _entry = float(pos.get("entryPrice") or pos.get("info", {}).get("entryPrice") or 0)
        _contracts = float(pos.get("contracts") or 0)

        if not _sym_ccxt or _side_raw not in ("long", "short") or _entry <= 0:
            continue

        # watchdog _sym_ccxt formatı: "XLM/USDT:USDT".split(":")[0] = "XLM/USDT"
        # PyramidPosition.symbol bu formatla uyumlu olmalı.
        _sym_for_check = _sym_ccxt.split(":")[0]

        # Bu pozisyon için zaten _pyramid_positions'da kayıt var mı?
        _already = any(
            getattr(_pp, "symbol", "") == _sym_for_check
            and str(getattr(_pp, "side", "")).lower() == _side_raw
            for _pp in _pyramid_positions.values()
        )
        if _already:
            continue

        # Journal'dan orijinal entry + sl bul
        # Journal formatı: 'XLM/USDT' (ccxt'nin :USDT suffix'i olmadan)
        _sym_journal = _sym_ccxt.split(":")[0]  # "XLM/USDT:USDT" → "XLM/USDT"
        _sym_algo = _sym_ccxt.replace("/", "").replace(":USDT", "").replace(":usdt", "")
        _jkey = f"{_sym_journal}|{_side_raw}"
        _orig_entry, _orig_sl, _orig_sig_id = _journal_map.get(_jkey, (0.0, 0.0, ""))

        # Fallback: journal yoksa borsadaki entry + algo SL
        if _orig_entry <= 0:
            _orig_entry = _entry
        if _orig_sl <= 0:
            # Algo SL map'den (XLMUSDT formatı)
            _orig_sl = _algo_sl_map.get(_sym_algo, 0.0)

        if _orig_sl <= 0:
            log(
                f"REBUILD_TRACKING: {_sym_ccxt} {_side_raw} — sl_price bulunamadı, atlanıyor "
                f"(journal_key={_jkey}, algo_map_keys={list(_algo_sl_map.keys())[:5]})"
            )
            continue

        _initial_r = abs(_orig_entry - _orig_sl)
        if _initial_r <= 0:
            log(f"REBUILD_TRACKING: {_sym_ccxt} {_side_raw} — initial_r=0, atlanıyor")
            continue

        # Stub PyramidPosition: legs boş (pyramid_enabled=false, leg trigger yok)
        # watchdog'un _sym_ccxt'si: _sym_raw.split(":")[0] → "XLM/USDT" (":USDT" yok)
        # PyramidPosition.symbol'ü watchdog ile aynı formatta set et.
        _sym_for_pp = _sym_ccxt.split(":")[0]  # "XLM/USDT:USDT" → "XLM/USDT"
        _stub_leg = PyramidLeg(
            leg_num=1,
            leg_state="FILLED",
            leg_qty=_contracts,
            leg_price=_orig_entry,
            client_order_id=f"rebuild_{_sym_algo}_L1",
            fill_price=_orig_entry,
        )
        _stub_id = _orig_sig_id if _orig_sig_id else f"rebuild_{_sym_algo}_{_side_raw}"
        _pyr_pos = PyramidPosition(
            parent_position_id=_stub_id,
            symbol=_sym_for_pp,
            side=_side_raw.upper(),  # type: ignore[arg-type]
            entry_price=_orig_entry,
            sl_price=_orig_sl,
            initial_R=_initial_r,
            legs=[_stub_leg],
            pyramid_triggers=[],
            pyramid_sizes=[],
        )
        _pyramid_positions[_stub_id] = _pyr_pos
        rebuilt_count += 1
        log(
            f"REBUILD_TRACKING: {_sym_ccxt} {_side_raw} → stub kayıt oluşturuldu "
            f"(entry={_orig_entry}, sl={_orig_sl}, initial_r={_initial_r:.5f}, "
            f"source={'journal' if _orig_sig_id else 'exchange'}, id={_stub_id})"
        )

    if rebuilt_count > 0:
        log(f"REBUILD_TRACKING: {rebuilt_count} pozisyon için takip kaydı yeniden kuruldu")
    else:
        log("REBUILD_TRACKING: tüm pozisyonlar zaten takip kaydına sahip (veya sl bulunamadı)")


def _get_pyramid_router(exchange):
    """PyramidRouter singleton — config'den pyramid_enabled kontrolü."""
    global _pyramid_router_instance
    if _pyramid_router_instance is not None:
        return _pyramid_router_instance
    # FIX 2026-05-26 (Faz 14.9): pyramid_enabled gate.
    # Config'de kapalıysa router'ı hiç init etme — eski PENDING leg'lerin
    # sonsuz submit retry'ı önlenir.
    if not _pyramid_enabled_15m():
        log("PYRAMID_ROUTER: skip init (strategy_portfolio.pyramid_enabled=false)")
        return None
    try:
        import yaml as _yaml_gr

        _gr_yaml_path = _risk_config_15m()
        try:
            with open(_gr_yaml_path, encoding="utf-8") as _gr_f:
                _gr_cfg = _yaml_gr.safe_load(_gr_f) or {}
        except Exception as _gr_load_exc:
            # FIX 2026-05-26 (H1): config eksikliği görünür olsun
            log(
                f"WARN _get_pyramid_router config load fail: {_gr_load_exc} — defaults kullanılıyor"
            )
            _gr_cfg = {}
        _gr_exec = _gr_cfg.get("execution", {})
        _gr_po_enabled = bool(_gr_exec.get("post_only_limit_enabled", False))
        _gr_po_timeout = int(_gr_exec.get("post_only_fallback_seconds", 30))
        _gr_slip_limit = float(_gr_exec.get("slippage_limit_bps", 25.0))
        # pyramid_slippage_limit_bps: entry slippage_limit_bps'den ayrı,
        # pyramid leg market-fallback için daha geniş tolerans (default 50bps).
        _gr_pyr_slip = float(_gr_exec.get("pyramid_slippage_limit_bps", 50.0))
        from price_action.execution.idempotency import IdempotencyStore
        from price_action.execution.pyramid_router import PyramidRouter
        from price_action.execution.slippage_tracker import SlippageTracker

        _pyramid_router_instance = PyramidRouter(
            exchange=exchange,
            idempotency_store=IdempotencyStore(db_path=IDEMPOTENCY_DB),
            slippage_tracker=SlippageTracker(),
            post_only_enabled=_gr_po_enabled,
            fallback_seconds=_gr_po_timeout,
            slippage_limit_bps=_gr_pyr_slip,
            mode=os.environ.get("PA_RUN_MODE", "paper"),
        )
        log(
            f"PYRAMID_ROUTER: başlatıldı (post_only={_gr_po_enabled}, slip_limit={_gr_pyr_slip}bps)"
        )
    except Exception as exc:
        log(f"PYRAMID_ROUTER_INIT_FAIL: {exc} — pyramid devre dışı")
        _pyramid_router_instance = None
    return _pyramid_router_instance


_TRAIL_PCT = 0.04  # TP1 sonrası %4 trailing — backtest doğrulaması bekleniyor (2026-06-01)
# Eski: 0.10 (TP2 sonrası) — açık kâr korunmuyordu (XLM kâr→zarar vakası 2026-05-31)
# Yeni: 0.04 (TP1 sonrası) — backtest sonucuna göre 0.03/0.04/0.05 karşılaştırması yapılacak.

# Runner time-stop — 30-bar forced exit once in runner phase (post-TP1).
# Validated by lab tournament (reports/research/smc/exit_tournament_verdict.md):
#   LIVE_ts30 = same 4% pct-trail + BE-lock + 30-bar runner cap.
#   Collapses the +56%/mo tail artifact → honest +6.43%/mo, Sharpe 1.67, DD -18.7%,
#   top-5% R share 40.9%, 12/12 walk-forward. Driver: scripts/_champ_exit_parity_timestop.py.
# Anchor: bars counted from when runner trail engages (TP1 hit / +1R) — NOT from entry.
#   force_exit_from_entry=False in LIVE_ts30 config; clock starts at TP1 partial fill.
#   In the daemon: runner anchor = ts_close of the first TP1 partial close from the journal
#   (fully restart-safe — derived from DB on every position_check tick, not in-memory counter).
# Bar size: 15 minutes → 30 bars = 7.5 hours max runner hold after TP1.
_RUNNER_MAX_BARS = 30  # ts30 validated value; do not change without re-running lab tournament
_RUNNER_BAR_SECONDS = 15 * 60  # 15m timeframe → seconds per bar


def _desired_sl_price(
    side: str,
    entry: float,
    intended_sl: float,
    mark: float,
    pyramid_leg_filled: bool = False,
    trail_pct: float | None = None,
) -> float:
    """Bir pozisyon için olması gereken stop-loss fiyatı.

    Yeni kural (2026-06-01) — breakeven kilidi + erken trailing:
      1) BREAKEVEN KİLİDİ: mark +1R'yi (TP1) geçtiği anda SL tabanı entry'ye çekilir.
         LONG: max(entry, intended_sl) — pozisyon artık asla zarara dönemez.
         SHORT: min(entry, intended_sl)
      2) TRAIL ERKEN BAŞLAR: +1R'den (TP1) itibaren hem BE kilidi hem trailing aktif.
         (Eski davranış: trail yalnız TP2 = 1.5R sonrası başlıyordu → kâr korunmuyordu.)
      3) TRAIL SIKLIĞI: varsayılan _TRAIL_PCT = 0.04 (%4).
         LONG : max(entry, mark * (1 - trail_pct))
         SHORT: min(entry, mark * (1 + trail_pct))
      4) RATCHET: SL yalnız lehe hareket eder. Bu fonksiyon istenen SL'i döner;
         gerçek ratchet çağıran bekçide uygulanır (current >= desired → güncelleme yok).

    Seçenek-D / BE-protect (pyramid_leg_filled, 2026-05-20 davranışı korundu):
      pyramid_leg_filled=True → pyramid leg-2+ FILLED iken +1R altında BE taban.
      pyramid_leg_filled=False (default) → backward-compat, davranış aynı.

    Parametre:
      trail_pct: None → _TRAIL_PCT global default kullanılır. Explicit verilirse override.

    Örnek (LONG: entry=511.65, intended_sl=499.0, mark=571.0):
      initial_r = 12.65, tp1 = 524.30
      mark(571) > tp1(524.30) → trail aktif
      trail_sl = max(entry=511.65, 571*(1-0.04)) = max(511.65, 548.16) = 548.16
      → SL = 548.16  (eski %10: max(524.30, 571*0.90=513.90) = 524.30 — çok gevşek)
    """
    pct = trail_pct if trail_pct is not None else _TRAIL_PCT
    initial_r = abs(entry - intended_sl)
    if initial_r <= 0 or mark <= 0:
        return intended_sl
    if side == "long":
        tp1 = entry + initial_r
        if mark < tp1:
            # TP1 altında: BE kilidi yok, orijinal SL (pyramid ise BE taban)
            if pyramid_leg_filled:
                return max(entry, intended_sl)
            return intended_sl
        # mark >= tp1: BE kilidi + trailing (TP1'den itibaren)
        trail_sl = mark * (1.0 - pct)
        return max(entry, trail_sl)
    # short
    tp1 = entry - initial_r
    if mark > tp1:
        # TP1 altında (short yönde): BE kilidi yok
        if pyramid_leg_filled:
            return min(entry, intended_sl)
        return intended_sl
    # mark <= tp1: BE kilidi + trailing
    trail_sl = mark * (1.0 + pct)
    return min(entry, trail_sl)


def position_check():
    """Açık pozisyonları + algo (TP/SL) protection order durumu."""
    from scripts.futures_trade_daily import fetch_futures_state, get_futures_exchange

    try:
        ex = get_futures_exchange()
        state = fetch_futures_state(ex)
        positions = state["positions"]

        # A3: rate-limit/network bilgi etiketi
        algo_ok = state.get("algo_orders_ok", True)
        pos_ok = state.get("positions_ok", True)
        rate_limit_suffix = "" if (algo_ok and pos_ok) else " [API_STALE]"

        if positions:
            pos_summary = []
            for p in positions:
                sym = p.get("symbol", "?")
                contracts = float(p.get("contracts", 0))
                side = p.get("side", "?")
                entry = float(p.get("entryPrice", 0))
                mark = float(p.get("markPrice", 0))
                pnl = float(p.get("unrealizedPnl", 0))
                # FIX 2026-05-26 (Faz 14.9): 4-digit fiyat format (Principal isteği).
                # Düşük-fiyatlı coinler (DOGE, AVAX) $.2f'te aynı görünüyordu —
                # gerçek hareket gizleniyordu. $.4f ile $0.1014 vs $0.1023 ayırt edilir.
                pos_summary.append(
                    f"{sym.replace('/USDT:USDT','').replace('/USDT','')}={side[0].upper()}{abs(contracts):.3f}@${entry:.4f}->{mark:.4f}({pnl:+.2f})"
                )
            log(
                f"POS_CHECK: {len(positions)} pos, {state['n_algo_orders']} algo (TP+SL){rate_limit_suffix} | "
                + " | ".join(pos_summary[:6])
            )
        else:
            log(f"POS_CHECK: 0 pozisyon, {state['n_algo_orders']} algo orders{rate_limit_suffix}")

        # SEC-#3C: Fill-sonrası konsantrasyon watchdog (sadece alarm).
        # Sorun: mevcut concentration_gate PRE-trade çalışır; FILL SONRASI gerçek
        # piyasa hareketi sembolü beklenenin üzerine taşıyabilir. Bu watchdog
        # post-fill durumu kontrol eder ve konfigürasyondaki max_per_symbol_pct
        # (default 0.15) eşiğini aşanları WARN log + Telegram ile bildirir.
        # Önemli: TRADE YAPILMAZ / KESİLMEZ — sadece pasif uyarı.
        # Dedup: aynı sembol 12 saat içinde tekrar bildirilmez (state dosyası).
        if positions and pos_ok:
            try:
                import yaml as _conc_yaml

                _conc_cfg_path = _risk_config_15m()
                with open(_conc_cfg_path, encoding="utf-8") as _cf:
                    _conc_cfg = _conc_yaml.safe_load(_cf) or {}
                _max_per_sym_pct = float(
                    _conc_cfg.get("concentration_limits", {}).get("max_per_symbol_pct", 0.15)
                )
                # Equity tahmini: margin_balance (pozisyon kaybı dahil)
                _watchdog_equity = float(state.get("margin_balance", 0)) or float(
                    state.get("wallet_balance", 1)
                )
                if _watchdog_equity > 0:
                    # Dedup state dosyası
                    _conc_dedup_path = ROOT / "logs" / "risk" / "conc_watchdog_dedup.json"
                    _conc_dedup_path.parent.mkdir(parents=True, exist_ok=True)
                    try:
                        import json as _json_conc

                        _dedup_state = (
                            _json_conc.loads(_conc_dedup_path.read_text(encoding="utf-8"))
                            if _conc_dedup_path.exists()
                            else {}
                        )
                    except Exception:
                        _dedup_state = {}

                    _now_iso = datetime.now(UTC).isoformat()
                    _dedup_changed = False
                    for _p in positions:
                        _psym = _p.get("symbol", "?")
                        _pcontracts = abs(float(_p.get("contracts", 0)))
                        _pmark = float(_p.get("markPrice", 0))
                        _pnotional = _pcontracts * _pmark
                        _ppct = _pnotional / _watchdog_equity
                        if _ppct > _max_per_sym_pct:
                            # Dedup: son 12h içinde bildirildi mi?
                            _last_alert = _dedup_state.get(_psym)
                            _skip_dedup = False
                            if _last_alert:
                                try:
                                    from datetime import timedelta as _td

                                    _last_dt = datetime.fromisoformat(_last_alert)
                                    if _last_dt.tzinfo is None:
                                        _last_dt = _last_dt.replace(tzinfo=UTC)
                                    if (datetime.now(UTC) - _last_dt) < _td(hours=12):
                                        _skip_dedup = True
                                except Exception:
                                    pass
                            if not _skip_dedup:
                                log(
                                    f"  CONCENTRATION_BREACH: {_psym} "
                                    f"{_ppct*100:.1f}% > {_max_per_sym_pct*100:.0f}% "
                                    f"(notional=${_pnotional:.0f}, equity=${_watchdog_equity:.0f})"
                                )
                                try:
                                    from price_action.orchestrator.notifications import (
                                        push_critical,
                                    )

                                    push_critical(
                                        f"CONCENTRATION_BREACH: {_psym} "
                                        f"{_ppct*100:.1f}% > {_max_per_sym_pct*100:.0f}% "
                                        f"(notional=${_pnotional:.0f})",
                                        source="pos_check_watchdog",
                                    )
                                except Exception:
                                    pass
                                _dedup_state[_psym] = _now_iso
                                _dedup_changed = True
                    if _dedup_changed:
                        try:
                            import json as _json_conc

                            _conc_dedup_path.write_text(
                                _json_conc.dumps(_dedup_state, indent=2), encoding="utf-8"
                            )
                        except Exception:
                            pass
            except Exception as _conc_ex:
                log(f"  CONC_WATCHDOG_ERR: {str(_conc_ex)[:80]}")

        # A3: API stale ise — orphan cleanup + prot_check SKIP (false-close yazımı önle)
        if not algo_ok or not pos_ok:
            log(
                f"POS_CHECK SKIP: orphan+prot_check passed (algo_ok={algo_ok}, pos_ok={pos_ok}) — rate-limit/network"
            )
            return

        # Orphan algo cleanup — TP fill sonrası SL kalıntısı (veya tersi) iptal.
        # reduceOnly tek başına whipsaw'da yetersiz: TP doldu → fiyat geri döner →
        # yeni pozisyon (farklı qty) açılırsa eski SL yanlış miktar kapatır.
        # Bu yüzden "pozisyon yok ama algo var" durumunu deterministik temizle.
        #
        # FIX 2026-05-30 (INC1-orphan-fp): Yanlış-pozitif orphan cancel.
        # Kök neden: fetch_positions() geçici olarak boş dönebilir (testnet API
        # stale / rate-limit 418, no exception, empty list). Bu durumda pozisyon
        # HÂLÂ AÇIKKEN algo order'ı "orphan" sanıp iptal ediyorduk — XLM vakası.
        # Düzeltme: algo_sym journal'daki açık futures_signals kaydıyla çapraz kontrol.
        # Journal'da açık kayıt varsa pozisyon borsada açık varsayılır; API stale
        # sanılır; bu tick'te orphan cancel ATLA + warning log.
        try:
            active_pos_syms = set()
            for p in positions:
                qty = abs(float(p.get("contracts", 0)))
                if qty > 0.0001:
                    sym_raw = p.get("symbol", "")
                    # "BTC/USDT:USDT" → "BTCUSDT" (algo endpoint sym format)
                    active_pos_syms.add(sym_raw.split(":")[0].replace("/", ""))

            # FIX INC1: journal'daki açık sinyal sembollerini al (BTCUSDT formatına çevir)
            # FIX 2026-06-10 (v14 audit MAJOR-1a): journal okunamazsa FAIL-CLOSED —
            # cross-check katmanı sessizce devre dışı kalıyordu (fail-open); artık
            # journal okunamadıysa bu tick orphan-cancel TAMAMEN atlanır.
            _journal_open_syms: set[str] = set()
            _journal_read_ok = True
            try:
                _jcon_oc = duckdb.connect(str(JOURNAL), read_only=True)
                try:
                    _jrows = _jcon_oc.execute("""
                        SELECT DISTINCT symbol FROM futures_signals
                        WHERE status = 'filled'
                          AND signal_id NOT IN (SELECT trade_id FROM futures_trades_closed)
                    """).fetchall()
                    for (_jsym,) in _jrows:
                        # "XLM/USDT" → "XLMUSDT"
                        _journal_open_syms.add(str(_jsym).replace("/", "").replace(":USDT", ""))
                finally:
                    _jcon_oc.close()
            except Exception as _joc_err:
                _journal_read_ok = False
                log(
                    f"ORPHAN_JOURNAL_READ_ERR: {str(_joc_err)[:80]} — "
                    f"fail-closed: bu tick orphan-cancel atlanıyor"
                )

            # FIX 2026-06-07 (XRP/LINK çıplak döngüsü): İKİNCİ TAZE POZİSYON TEYİDİ.
            # Tek fetch_positions stale dönebilir (testnet): pozisyon AÇIKKEN positions[]
            # boş → SL "orphan" sanılıp iptal → çıplak → heal koyuyor → orphan tekrar
            # iptal (sonsuz döngü; XRP +$66 korumasız, LINK -$224). Journal cross-check
            # de drift'te kurtarmıyor. Çözüm: silmeden önce 2. bağımsız okuma. Sembol İKİ
            # okumada da yoksa gerçekten orphan; biri görürse / teyit alınamazsa İPTAL ETME.
            # FIX 2026-06-10 (v14 audit MAJOR-1b): 2. teyit FARKLI endpoint'ten —
            # fetch_positions ile aynı endpoint'in stale pencereleri korele
            # (02:15Z'de iki okuma da boş geldi). positionRisk ayrı endpoint,
            # sembol formatı zaten ham "BTCUSDT".
            _confirm_syms: set[str] | None = set(active_pos_syms)
            try:
                for _pr in ex.fapiPrivateV2GetPositionRisk():
                    if abs(float(_pr.get("positionAmt", 0) or 0)) > 0.0001:
                        _confirm_syms.add(str(_pr.get("symbol", "")))
            except Exception:
                _confirm_syms = None  # teyit alınamadı → hiçbir şeyi orphan sayma

            # FIX 2026-06-10 (XRP 02:15Z olayı): N-ARDIŞIK-TİCK STATEFUL TEYİT.
            # Double-read fix (d513795) DELİNDİ: 4. tick'te İKİ okuma da stale geldi
            # → açık pozisyonun SL'i iptal edildi (çıplak 30dk, HEAL kurtardı).
            # Tek-tick içi okuma sayısını artırmak yetmez (stale pencereleri korele).
            # Çözüm: cancel noktasına gelen emir _ORPHAN_SUSPECT_TICKS'te sayaç
            # biriktirir; ancak ORPHAN_CONFIRM_TICKS ardışık tick'te (~45dk) hep
            # orphan görünürse iptal edilir. Pozisyon TEK tick'te bile görünse sayaç
            # sıfırlanır. Gerçek orphan'lar ~45dk gecikmeyle temizlenir — kabul
            # edilebilir: SL'ler reduceOnly (pozisyonsuz tetik reddedilir); aynı
            # sembolde 45dk içinde yeni pozisyon whipsaw'ı PROT_WATCHDOG "fazla SL
            # temizle" adımıyla sınırlı.
            orphan_cnt = 0
            _seen_suspects: set[str] = set()
            # MAJOR-1a fail-closed: journal okunamadıysa hiçbir emri orphan sayma
            _orphan_scan_list = (state.get("algo_orders", []) or []) if _journal_read_ok else []
            for o in _orphan_scan_list:
                algo_sym = o.get("symbol", "")  # "BTCUSDT"
                if not algo_sym:
                    continue
                algo_id = o.get("algoId") or o.get("algo_id")
                if not algo_id:
                    continue
                _skey = f"{algo_sym}|{algo_id}"
                if algo_sym in active_pos_syms:
                    _ORPHAN_SUSPECT_TICKS.pop(_skey, None)
                    continue
                # FIX INC1: journal'da açık kayıt varsa → API stale olabilir, iptal ETME
                if algo_sym in _journal_open_syms:
                    _ORPHAN_SUSPECT_TICKS.pop(_skey, None)
                    log(
                        f"ORPHAN_SKIP: {algo_sym} algoId={algo_id} — "
                        f"journal'da açık kayıt var, pos API stale olabilir; bu tick skip"
                    )
                    continue
                # FIX 2026-06-07: 2. taze teyit. İkinci okuma pozisyonu görüyorsa VEYA
                # teyit alınamadıysa → orphan DEĞİL, iptal etme (stale-read'den çıplak bırakma).
                if _confirm_syms is None or algo_sym in _confirm_syms:
                    _ORPHAN_SUSPECT_TICKS.pop(_skey, None)
                    log(
                        f"ORPHAN_SKIP: {algo_sym} algoId={algo_id} — 2. taze teyitte "
                        f"pozisyon açık/teyit-yok; iptal edilmedi (stale-read koruması)"
                    )
                    continue
                # Bu tick'te orphan görünüyor → sayaç artır, eşiğe gelmeden iptal ETME.
                _streak = _ORPHAN_SUSPECT_TICKS.get(_skey, 0) + 1
                _ORPHAN_SUSPECT_TICKS[_skey] = _streak
                _seen_suspects.add(_skey)
                if _streak < ORPHAN_CONFIRM_TICKS:
                    log(
                        f"ORPHAN_PENDING: {algo_sym} algoId={algo_id} — "
                        f"{_streak}/{ORPHAN_CONFIRM_TICKS} ardışık tick; iptal bekletildi"
                    )
                    continue
                try:
                    ex.fapiPrivateDeleteAlgoOrder({"symbol": algo_sym, "algoId": algo_id})
                    orphan_cnt += 1
                    _ORPHAN_SUSPECT_TICKS.pop(_skey, None)
                    log(
                        f"ORPHAN_CANCEL: {algo_sym} algoId={algo_id} type={o.get('type','?')} "
                        f"({ORPHAN_CONFIRM_TICKS} ardışık tick teyitli orphan)"
                    )
                except Exception as cancel_err:
                    log(
                        f"ORPHAN_CANCEL_FAIL: {algo_sym} algoId={algo_id} err={str(cancel_err)[:80]}"
                    )
            # Bu tick'te görünmeyen şüpheli kayıtlarını temizle (emir doldu/iptal oldu)
            for _stale_key in [k for k in _ORPHAN_SUSPECT_TICKS if k not in _seen_suspects]:
                _ORPHAN_SUSPECT_TICKS.pop(_stale_key, None)
            if orphan_cnt > 0:
                log(f"ORPHAN_CLEANUP: {orphan_cnt} algo orders cancelled (whipsaw protection)")
        except Exception as cleanup_err:
            log(f"ORPHAN_CLEANUP_ERR: {str(cleanup_err)[:120]}")

        # Algo order fill detection (Binance algo endpoint)
        # PARTIAL-CLOSE AWARE (2026-05-31):
        # Winner-let-run: TP1(%25) + TP2(%25) partial + SL(%50 runner).
        # TP1 kısmi dolup trailing SL cancel-replace yarışında "ikisi de yok"
        # görünürdü → TÜM kaydı 'tp' ile kapatıyordu → runner borsada AÇIK
        # kalırken journal'da kapalı → phantom + sahte PnL.
        # Yeni mantık: borsa güncel pozisyon qty'sini çek; karşılaştır:
        #   borsa_qty > epsilon → KISMİ: partial_closes'a yaz, signal açık kal.
        #   borsa_qty ≈ 0      → TAM: record_close(kalan_qty).
        try:
            con = duckdb.connect(str(JOURNAL))
            our_active_prot = con.execute("""
                SELECT prot_id, symbol, tp_order_id, sl_order_id
                FROM futures_protection_orders WHERE status = 'placed'
            """).fetchall()
            # Mevcut algo IDs
            algo_open_ids = set(str(o.get("algoId", "")) for o in state["algo_orders"])
            # Borsa güncel pozisyon qtyleri (sym_ccxt → qty) — partial-aware için
            _exchange_pos_qty: dict[str, float] = {}
            for _pos in positions:
                _psym = _pos.get("symbol", "")  # "AVAX/USDT:USDT" formatı
                _pqty = abs(float(_pos.get("contracts", 0) or 0))
                if _pqty > 1e-9:
                    _exchange_pos_qty[_psym] = _pqty
            # Kısa sem map: "AVAX/USDT:USDT" → "AVAX/USDT" (journal sym formatı)
            _exchange_pos_qty_j: dict[str, float] = {}
            for _sym_raw, _qty_raw in _exchange_pos_qty.items():
                _sym_j = _sym_raw.split(":")[0]  # "AVAX/USDT"
                _exchange_pos_qty_j[_sym_j] = _qty_raw

            for prot_id, sym, tp_oid, sl_oid in our_active_prot:
                tp_open = tp_oid in algo_open_ids if tp_oid else False
                sl_open = sl_oid in algo_open_ids if sl_oid else False
                # FIX 2026-06-11 (görev #11, ZEC+ATOM vakaları): eski şart yalnız
                # "TP VE SL ikisi de kayıp" idi — 2026-05-31 varsayımı "SL dolunca
                # Binance kardeş TP'leri otomatik iptal eder" testnet ALGO
                # emirlerinde TUTMUYOR: SL tam-kapanışta TP'ler AÇIK kalıyor →
                # tp_open=True → kapanış tespiti sonsuza dek beklemede, journal
                # 'filled' kalır, artık TP'ler orphan-skip korumasına takılırdı.
                # Yeni: SL kayıp + borsada pozisyon qty≈0 (çift kanıt) da tam
                # kapanış sayılır; kalan TP'leri journal kapanınca orphan-temizlik
                # N-tick teyidiyle süpürür.
                _sl_gone_pos_flat = (
                    sl_oid
                    and not sl_open
                    and _exchange_pos_qty_j.get(sym, 0.0) <= 1e-6
                )
                if (not tp_open and not sl_open) or _sl_gone_pos_flat:
                    # TP1 ve SL ikisi de algo_open_ids'de yok.
                    # UYARI: TP2 order_id'si notes'ta saklanıyor (tp2_id=...).
                    # notes parse et — TP2 hâlâ açıksa bu sadece TP1 filldir.
                    _notes_str = ""
                    try:
                        _nr = con.execute(
                            "SELECT notes FROM futures_protection_orders WHERE prot_id=?",
                            [prot_id],
                        ).fetchone()
                        _notes_str = str(_nr[0] or "") if _nr else ""
                    except Exception:
                        pass
                    _tp2_oid = None
                    if "tp2_id=" in _notes_str:
                        try:
                            _tp2_oid = _notes_str.split("tp2_id=")[-1].strip().split()[0]
                            if not _tp2_oid:
                                _tp2_oid = None
                        except Exception:
                            _tp2_oid = None
                    _tp2_open = _tp2_oid in algo_open_ids if _tp2_oid else False

                    sym_id = sym.replace("/USDT:USDT", "USDT").replace("/USDT", "USDT")
                    try:
                        hist = ex.fapiPrivateGetAllAlgoOrders({"symbol": sym_id, "limit": 30})
                        # Bug 3 fix: ilk eşleşmede kırma. SL tetiklenince Binance
                        # kardeş TP order'ını otomatik CANCELED yapar; eski döngü
                        # CANCELED order'ı önce yakalarsa gerçek kapanışı kaçırır
                        # ve record_close hiç çağrılmazdı. Çözüm: TP+SL order'ını
                        # ayrı bul, TRIGGERED/FINISHED olana öncelik ver.
                        tp_order = sl_order = tp2_order = None
                        for o in hist:
                            algo_id_str = str(o.get("algoId", ""))
                            if tp_oid and algo_id_str == str(tp_oid):
                                tp_order = o
                            elif sl_oid and algo_id_str == str(sl_oid):
                                sl_order = o
                            elif _tp2_oid and algo_id_str == str(_tp2_oid):
                                tp2_order = o
                        triggered = triggered_kind = None
                        for cand, knd in ((sl_order, "SL"), (tp_order, "TP1"), (tp2_order, "TP2")):
                            if cand is not None and cand.get("algoStatus") in (
                                "TRIGGERED",
                                "FINISHED",
                            ):
                                triggered, triggered_kind = cand, knd
                                break
                        any_terminal = any(
                            o is not None
                            and o.get("algoStatus")
                            in ("TRIGGERED", "CANCELED", "FINISHED", "EXPIRED")
                            for o in (tp_order, sl_order)
                        )
                        if any_terminal:
                            con.execute(
                                """UPDATE futures_protection_orders SET status='filled' WHERE prot_id=?""",
                                [prot_id],
                            )
                        if triggered is not None:
                            status_alg = triggered.get("algoStatus")
                            # FIX 2026-05-30 (INC3-triggerPrice-bug): exit_price GERÇEK fill fiyatı.
                            # KÖK NEDEN: triggered.get("triggerPrice") EMIR KURULUM fiyatını döner
                            # (sinyal hesaplamasındaki TP/SL hedef fiyatı) — borsanın gerçek fill
                            # fiyatı DEĞİL. Binance TAKE_PROFIT_MARKET/STOP_MARKET algo emirleri
                            # triggerPrice'de TETIKLENIR ama MARKET PRICE'dan FILL olur. Bu fark
                            # testnet'te küçük, canlıda/stres dönemlerinde 10-30bps slippage = $10+
                            # sapma. Daha kötüsü: DOT gibi vakalarda TP hiç dolmamış olabilir ama
                            # journal "TP hit @ target" yazmıştı → +28.73 sahte kâr.
                            # Düzeltme: avgPrice (gerçek weighted-average fill) veya
                            # executedQty > 0 olan fill. triggerPrice fallback olarak son çare.
                            _prot_trigger_px = float(triggered.get("triggerPrice", 0) or 0)
                            _prot_avg_px = triggered.get("avgPrice") or triggered.get(
                                "avgExecutedPrice"
                            )
                            _prot_fill_px = (
                                float(_prot_avg_px)
                                if _prot_avg_px and float(_prot_avg_px) > 0
                                else _prot_trigger_px
                            )
                            if _prot_avg_px and float(_prot_avg_px) > 0:
                                log(
                                    f"PROT_FILL: {sym} {triggered_kind} HIT @ ${_prot_fill_px} "
                                    f"(avgPrice, trigger=${_prot_trigger_px}, status={status_alg})"
                                )
                            else:
                                # avgPrice yoksa triggerPrice kullandık — audit uyarısı
                                log(
                                    f"PROT_FILL: {sym} {triggered_kind} HIT @ ${_prot_fill_px} "
                                    f"(triggerPrice fallback — avgPrice missing, status={status_alg}) "
                                    f"[AUDIT: exit_price may differ from actual fill]"
                                )
                            # PARTIAL-CLOSE KARAR NOKTASI (2026-05-31):
                            # Borsa güncel qty'sini çek; 0'a yakınsa TAM kapanış,
                            # hâlâ qty varsa KISMİ kapanış (TP1/TP2 partial fill).
                            # Epsilon: borsa minumum qty 0.001'in altı = "sıfır".
                            _CLOSE_EPSILON = 1e-6
                            _exchange_qty_now = _exchange_pos_qty_j.get(sym, 0.0)
                            try:
                                sig_row = con.execute(
                                    """
                                    SELECT signal_id, ts, symbol, side, strategy, fill_price, fill_qty, sl_price
                                    FROM futures_signals
                                    WHERE signal_id = (
                                        SELECT signal_id FROM futures_protection_orders WHERE prot_id = ?
                                    )
                                """,
                                    [prot_id],
                                ).fetchone()
                                if sig_row:
                                    (
                                        sig_id,
                                        ts_open,
                                        sym_sig,
                                        side_sig,
                                        strat,
                                        entry_p,
                                        fill_qty_sig,
                                        sl_p,
                                    ) = sig_row
                                    exit_p = _prot_fill_px
                                    now_close = datetime.now(UTC)

                                    if _exchange_qty_now > _CLOSE_EPSILON:
                                        # ── KISMİ KAPANIŞ (TP1 veya TP2 partial fill) ──
                                        # Borsa hâlâ açık: runner pozisyon devam ediyor.
                                        # closed_qty = sinyal kalan qty − borsa güncel qty.
                                        from price_action.execution.trade_journal import (
                                            TradeJournal,
                                        )

                                        tj = TradeJournal(db_path=str(JOURNAL))
                                        _remaining_before = tj.get_remaining_qty(
                                            str(sig_id), float(fill_qty_sig or 0.0)
                                        )
                                        _closed_qty = max(
                                            0.0, _remaining_before - _exchange_qty_now
                                        )
                                        if _closed_qty < _CLOSE_EPSILON:
                                            # qty fark çok küçük — büyük ihtimalle API stale
                                            # (borsa qty taze gelmediyse). Skip + uyarı.
                                            log(
                                                f"  PROT_PARTIAL_SKIP: {sym} {triggered_kind} "
                                                f"exchange_qty={_exchange_qty_now:.6f} remaining_before={_remaining_before:.6f} "
                                                f"closed_qty={_closed_qty:.6f} < epsilon — API stale olabilir, skip"
                                            )
                                        else:
                                            # close_id deterministik: trade_id + order_id
                                            _close_id = (
                                                f"{sig_id}_{triggered.get('algoId', prot_id)}"
                                            )
                                            _partial_inserted = tj.record_partial_close(
                                                close_id=_close_id,
                                                trade_id=str(sig_id),
                                                ts_close=now_close,
                                                sym=str(sym_sig),
                                                side=str(side_sig).lower(),
                                                strategy=str(strat or ""),
                                                entry_price=float(entry_p or 0.0),
                                                exit_price=float(exit_p),
                                                qty_closed=float(_closed_qty),
                                                sl_price=float(sl_p or 0.0),
                                                close_reason=triggered_kind.lower(),
                                            )
                                            log(
                                                f"  TRADE_PARTIAL: sig={sig_id} {triggered_kind} "
                                                f"qty_closed={_closed_qty:.6f} exit=${exit_p:.4f} "
                                                f"exchange_remaining={_exchange_qty_now:.6f} inserted={_partial_inserted}"
                                            )
                                            # TP1 partial Telegram (kısa bilgi)
                                            if _partial_inserted:
                                                try:
                                                    from price_action.orchestrator.notifications import (
                                                        notify_position_close,
                                                    )

                                                    _pnl_part = (
                                                        (float(exit_p) - float(entry_p or 0.0))
                                                        * _closed_qty
                                                        if str(side_sig).lower() == "long"
                                                        else (float(entry_p or 0.0) - float(exit_p))
                                                        * _closed_qty
                                                    )
                                                    notify_position_close(
                                                        bot="futures15m",
                                                        symbol=str(sym_sig),
                                                        side=str(side_sig).lower(),
                                                        strategy=str(strat or ""),
                                                        entry_price=float(entry_p or 0.0),
                                                        exit_price=float(exit_p),
                                                        qty=float(_closed_qty),
                                                        notional_usdt=float(_closed_qty)
                                                        * float(entry_p or 0.0),
                                                        realized_pnl_usdt=_pnl_part,
                                                        realized_r=0.0,
                                                        close_reason=f"partial_{triggered_kind.lower()}",
                                                        hold_seconds=None,
                                                    )
                                                except Exception as _tn_part_exc:
                                                    log(f"  TELEGRAM_PARTIAL_FAIL: {_tn_part_exc}")
                                    else:
                                        # ── TAM KAPANIŞ ──
                                        # Borsa qty ≈ 0: tüm pozisyon kapandı.
                                        # Kalan qty = fill_qty − SUM(partials).
                                        from price_action.execution.trade_journal import (
                                            TradeJournal,
                                        )

                                        tj = TradeJournal(db_path=str(JOURNAL))
                                        _remaining_qty = tj.get_remaining_qty(
                                            str(sig_id), float(fill_qty_sig or 0.0)
                                        )
                                        # 0'a yakınsa en az sembolik qty yaz (borsanın yuvarlama toleransı)
                                        _final_qty = max(_remaining_qty, 0.0)
                                        close_reason_str = triggered_kind.lower()
                                        # "tp1"/"tp2" → trades_closed'e "tp" yaz (eski raporlar okur)
                                        if close_reason_str in ("tp1", "tp2"):
                                            close_reason_str = "tp"

                                        # G14: TP/SL fill slippage kaydı (sig_row verisiyle)
                                        try:
                                            from price_action.execution.slippage_tracker import (
                                                SlippageTracker as _ST_prot,
                                            )

                                            _st_prot = _ST_prot()
                                            _prot_qty = float(_final_qty or 0.0)
                                            _prot_notional = _prot_qty * _prot_fill_px
                                            _prot_fee_bps = 4.0  # algo order = maker
                                            _prot_fee_usdt = _prot_notional * _prot_fee_bps / 10_000
                                            _st_prot.record_fill(
                                                fill_id=f"prot_{prot_id}_{triggered_kind.lower()}",
                                                ts=now_close,
                                                symbol=str(sym_sig),
                                                strategy=f"{strat or ''!s}_{triggered_kind.lower()}",
                                                side=str(side_sig).lower(),
                                                expected_price=_prot_fill_px,
                                                realized_price=_prot_fill_px,
                                                quantity=_prot_qty,
                                                fee_usdt=_prot_fee_usdt,
                                                is_maker=True,
                                                order_type="algo_stop_market",
                                                mode=os.environ.get("PA_RUN_MODE", "paper"),
                                                exchange_order_id=str(triggered.get("algoId", "")),
                                                fill_type=triggered_kind.lower(),
                                                tf="15m",
                                            )
                                        except Exception as _st_prot_err:
                                            log(
                                                f"  PROT_SLIP_RECORD_ERR prot_id={prot_id}: {str(_st_prot_err)[:100]}"
                                            )
                                        # Canonical writer (SEC26.B-4) — idempotent.
                                        try:
                                            inserted = tj.record_close(
                                                trade_id=str(sig_id),
                                                ts_open=ts_open or now_close,
                                                ts_close=now_close,
                                                sym=str(sym_sig),
                                                side=str(side_sig).lower(),
                                                strategy=str(strat or ""),
                                                entry_price=float(entry_p or 0.0),
                                                exit_price=float(exit_p),
                                                qty=float(_final_qty),
                                                sl_price=float(sl_p or 0.0),
                                                close_reason=close_reason_str,
                                            )
                                            log(
                                                f"  TRADE_CLOSED: sig={sig_id} {triggered_kind} "
                                                f"qty={_final_qty:.6f} inserted={inserted}"
                                            )

                                            # FIX 2026-05-26 (Faz 14.5): Telegram position-close bildirimi
                                            if inserted:
                                                try:
                                                    from price_action.orchestrator.notifications import (
                                                        notify_position_close,
                                                    )

                                                    _side = str(side_sig).lower()
                                                    _entry = float(entry_p or 0.0)
                                                    _exit = float(exit_p)
                                                    _qty = float(_final_qty)
                                                    if _side == "long":
                                                        _pnl = (_exit - _entry) * _qty
                                                    else:
                                                        _pnl = (_entry - _exit) * _qty
                                                    _sl = float(sl_p or 0.0)
                                                    _r = 0.0
                                                    if _sl and _entry:
                                                        _sl_dist = abs(_entry - _sl)
                                                        if _sl_dist > 0:
                                                            _r = _pnl / (_sl_dist * _qty)
                                                    _notional = _qty * _entry
                                                    _hold_s = None
                                                    if ts_open:
                                                        try:
                                                            _tso = (
                                                                ts_open
                                                                if ts_open.tzinfo
                                                                else ts_open.replace(tzinfo=UTC)
                                                            )
                                                            _tsc = (
                                                                now_close
                                                                if now_close.tzinfo
                                                                else now_close.replace(tzinfo=UTC)
                                                            )
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
                                                        close_reason=close_reason_str,
                                                        hold_seconds=_hold_s,
                                                    )
                                                except Exception as _tn_exc:
                                                    log(f"  TELEGRAM_CLOSE_FAIL: {_tn_exc}")
                                        except Exception as tje:
                                            log(
                                                f"  TRADE_CLOSED_WRITE_FAIL sig_id={sig_id}: {str(tje)[:120]}"
                                            )
                            except Exception as je:
                                log(
                                    f"  TRADE_CLOSED_LOOKUP_FAIL prot_id={prot_id}: {str(je)[:120]}"
                                )
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
                _contracts = abs(float(p.get("contracts", 0) or 0))
                if _contracts <= 1e-9:
                    continue
                _sym_raw = p.get("symbol", "")
                _sym_ccxt = _sym_raw.split(":")[0]
                _sym_algo = _sym_ccxt.replace("/", "")
                _side = (p.get("side") or "").lower()
                _entry = float(p.get("entryPrice", 0) or 0)
                _mark = float(p.get("markPrice", 0) or 0)
                if _entry <= 0 or _side not in ("long", "short"):
                    continue
                # FIX 2026-05-28 (Faz 14.27): SL emir filtresine SIDE eklendi.
                # Önceki bug: STOP_MARKET emirleri yön bağımsız toplanıyordu →
                # pozisyon SHORT'tan LONG'a döndüğünde eski BUY STOP emri "LONG'un
                # SL'i" sanılıyordu (ters yön = işe yaramaz). Doğrusu:
                #   LONG  pozisyon → SL emri SELL side'da (pozisyonu kapatır)
                #   SHORT pozisyon → SL emri BUY  side'da (pozisyonu kapatır)
                _expected_sl_side = "SELL" if _side == "long" else "BUY"
                _sl_orders = []  # (trigger, algoId, qty)
                _orphan_wrong_side = []  # eski yön — iptal edilecek
                for o in state.get("algo_orders", []) or []:
                    if (
                        o.get("symbol") == _sym_algo
                        and str(o.get("orderType", "")).upper() == "STOP_MARKET"
                    ):
                        _t = o.get("triggerPrice") or o.get("stopPrice")
                        _a = o.get("algoId") or o.get("algo_id")
                        _o_side = str(o.get("side", "")).upper()
                        if _t and _a is not None:
                            try:
                                _q = float(o.get("quantity") or o.get("origQty") or 0)
                            except (TypeError, ValueError):
                                _q = 0.0
                            if _o_side == _expected_sl_side:
                                _sl_orders.append((float(_t), _a, _q))
                            else:
                                # Yön mismatch → eski/orphan SL, iptal et
                                _orphan_wrong_side.append((float(_t), _a, _o_side))

                # Yön mismatch SL'leri temizle (defansif)
                for _t, _a, _wrong_side in _orphan_wrong_side:
                    try:
                        ex.fapiPrivateDeleteAlgoOrder({"symbol": _sym_algo, "algoId": _a})
                        log(
                            f"  PROT_WATCHDOG: {_sym_algo} ters-yön SL iptal "
                            f"(algoId={_a}, side={_wrong_side}, pos={_side}, trigger=${_t})"
                        )
                    except Exception as _cx:
                        log(
                            f"  PROT_WATCHDOG: {_sym_algo} ters-yön SL iptal "
                            f"FAIL ({_cx}); algoId={_a}"
                        )
                # En iyi mevcut SL (long→en yüksek, short→en düşük trigger)
                _cur_sl = _cur_aid = None
                _cur_sl_qty = 0.0
                if _sl_orders:
                    _cur_sl, _cur_aid, _cur_sl_qty = (max if _side == "long" else min)(
                        _sl_orders, key=lambda t: t[0]
                    )
                # Fazla SL'leri temizle (en iyinin dışındakiler)
                for _t, _a, _q in _sl_orders:
                    if _a != _cur_aid:
                        try:
                            ex.fapiPrivateDeleteAlgoOrder({"symbol": _sym_algo, "algoId": _a})
                            log(f"  PROT_WATCHDOG: {_sym_algo} fazla SL iptal " f"(algoId={_a})")
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
                    if (
                        getattr(_pp, "symbol", "") == _sym_ccxt
                        and str(getattr(_pp, "side", "")).lower() == _side
                    ):
                        _intended_sl = float(getattr(_pp, "sl_price", 0) or 0)
                        _pyr_entry = float(getattr(_pp, "entry_price", 0) or 0)
                        _pyr_pos_obj = _pp
                        break
                if not _intended_sl or _intended_sl <= 0:
                    # FIX 2026-06-05: ÖNCE girişte saklanan STABİL orijinal SL'i dene.
                    # v13'te pyramid KAPALI → _pyramid_positions kaydı yok → eskiden hareketli
                    # borsa SL'i (G22) intended_sl olurdu; SL ratchet'le taşındıkça initial_r
                    # küçülüp tp1 kayar → trailing DONAR (XRP +$64→$0 kapandı). Orijinal SL
                    # sabit olduğu için BE-lock + %4 trailing doğru hesaplanır.
                    _orig_sl = _ORIG_INTENDED_SL.get(f"{_sym_algo}|{_side}", 0.0)
                    if _orig_sl and _orig_sl > 0:
                        _intended_sl = _orig_sl
                    # G22 (orijinal SL de yok): borsadaki mevcut SL'i taban al. Restart sonrası
                    # _pyramid_positions boş; borsadaki SL zaten yerleştirilmiş → onu kullan.
                    elif _cur_sl is not None and _cur_sl > 0:
                        _intended_sl = _cur_sl
                        log(
                            f"  PROT_WATCHDOG_G22: {_sym_algo} pyramid kaydı yok — "
                            f"exchange SL ${_cur_sl} intended_sl olarak kullanılıyor"
                        )
                    elif _entry > 0:
                        # PROT_WATCHDOG_HEAL (2026-06-03): çıplak pozisyon — pyramid
                        # kaydı YOK ve borsada SL de YOK. Sebep: TP1 fill cancel-replace
                        # yarışı (satır ~933 "ikisi de yok" penceresi) veya restart
                        # rebuild'inin stub kaydı pyramid metadata'sını kaybetmesi.
                        # ESKİ davranış: "manuel müdahale gerek" + continue → pozisyon
                        # korumasız kalıyordu (ZEC/DOT 2026-06-03'te 4+ saat çıplak).
                        # YENİ: intended_sl=entry → _desired_sl_price breakeven (entry)
                        # döner → aşağıdaki "SL eksikti → kondu" bloğu BE stop yerleştirir.
                        #   • karda pozisyon (long: entry<mark): geçerli breakeven stop.
                        #   • zararda çıplak (entry>=mark): _breached → market close
                        #     (korumasız zarar pozisyonu güvenle düzleştirilir).
                        _intended_sl = _entry
                        log(
                            f"  PROT_WATCHDOG_HEAL: {_sym_algo} çıplak (pyramid+SL yok) "
                            f"→ breakeven SL @ ${_entry} yerleştiriliyor"
                        )
                        # continue YOK — SL yerleştirme bloğuna düş.
                    else:
                        log(
                            f"  PROT_WATCHDOG_ALARM: {_sym_algo} SL YOK + pyramid kaydı yok "
                            f"+ entry geçersiz ({_entry}) — manuel müdahale gerek"
                        )
                        continue
                # R/TP hesabı için leg-1 entry; yoksa borsa entry'ye düş
                _calc_entry = _pyr_entry if (_pyr_entry and _pyr_entry > 0) else _entry
                # Seçenek-D BE-protect: pyramid leg-2+ FILLED ise SL tabanı entry.
                # PyramidPosition.legs içinde leg_num >= 2 ve leg_state == "FILLED"
                # olan var mı kontrol et. Default False → backward-compat.
                _pyr_leg_filled = False
                if _pyr_pos_obj is not None:
                    for _lg in getattr(_pyr_pos_obj, "legs", []):
                        if (
                            getattr(_lg, "leg_num", 0) >= 2
                            and getattr(_lg, "leg_state", "") == "FILLED"
                        ):
                            _pyr_leg_filled = True
                            break
                # Hedef SL (TP2 sonrası trailing — kullanıcı kuralı; BE-protect ile birlikte)
                _sl_price = _desired_sl_price(
                    _side, _calc_entry, _intended_sl, _mark, pyramid_leg_filled=_pyr_leg_filled
                )
                _close_side = "SELL" if _side == "long" else "BUY"

                # ── RUNNER TIME-STOP (ts30) ───────────────────────────────
                # Force-exit if runner phase has been active ≥ _RUNNER_MAX_BARS bars.
                # Anchor: ts_close of the first TP1 partial close for this position
                # (from futures_partial_closes journal table).  Restart-safe: derived
                # from DB each tick — no in-memory counter.  Fires BEFORE the trailing
                # SL block; BE-lock + 4% trail remain active and whichever triggers
                # first (trail hit OR time-stop) closes the runner.
                # Ref: exit_tournament_verdict.md §6 fallback params.
                try:
                    _runner_ts_fired = False
                    # Only relevant when position is in runner phase (mark >= TP1).
                    _initial_r_ts = abs(_calc_entry - _intended_sl)
                    _in_runner = (
                        _initial_r_ts > 0
                        and _mark > 0
                        and (
                            (_side == "long" and _mark >= _calc_entry + _initial_r_ts)
                            or (_side == "short" and _mark <= _calc_entry - _initial_r_ts)
                        )
                    )
                    if _in_runner:
                        # Look up the first TP1 partial-close timestamp for this symbol/side.
                        _runner_anchor_ts: datetime | None = None
                        try:
                            _jcon_ts = duckdb.connect(str(JOURNAL), read_only=True)
                            try:
                                _ts_row = _jcon_ts.execute(
                                    """
                                    SELECT pc.ts_close
                                    FROM futures_partial_closes pc
                                    JOIN futures_signals fs
                                      ON pc.trade_id = fs.signal_id
                                    WHERE fs.symbol = ?
                                      AND LOWER(fs.side) = LOWER(?)
                                      AND fs.status = 'filled'
                                      AND LOWER(pc.close_reason) IN ('tp1', 'tp')
                                      AND fs.signal_id NOT IN (
                                          SELECT trade_id FROM futures_trades_closed
                                      )
                                    ORDER BY pc.ts_close ASC
                                    LIMIT 1
                                    """,
                                    [_sym_ccxt, _side],
                                ).fetchone()
                                if _ts_row and _ts_row[0]:
                                    _runner_anchor_ts = _ts_row[0]
                                    if (
                                        hasattr(_runner_anchor_ts, "tzinfo")
                                        and _runner_anchor_ts.tzinfo is None
                                    ):
                                        _runner_anchor_ts = _runner_anchor_ts.replace(tzinfo=UTC)
                            finally:
                                _jcon_ts.close()
                        except Exception as _ts_db_err:
                            log(f"  RUNNER_TS_LOOKUP_ERR: {_sym_algo}: {str(_ts_db_err)[:80]}")

                        if _runner_anchor_ts is not None:
                            _bars_in_runner = (
                                datetime.now(UTC) - _runner_anchor_ts
                            ).total_seconds() / _RUNNER_BAR_SECONDS
                            if _bars_in_runner >= _RUNNER_MAX_BARS:
                                _runner_ts_fired = True
                                log(
                                    f"  RUNNER_TIMESTOP: {_sym_algo} {_side} "
                                    f"runner={_bars_in_runner:.1f} bars >= {_RUNNER_MAX_BARS} "
                                    f"(anchor={_runner_anchor_ts.strftime('%H:%MZ')}) "
                                    f"→ force-close at market"
                                )

                    if _runner_ts_fired:
                        try:
                            _qty_str_ts = ex.amount_to_precision(_sym_ccxt, _contracts)
                            ex.create_order(
                                symbol=_sym_ccxt,
                                type="MARKET",
                                side=_close_side,
                                amount=float(_qty_str_ts),
                                params={"reduceOnly": True},
                            )
                            log(
                                f"  RUNNER_TIMESTOP_FILLED: {_sym_algo} market close sent "
                                f"qty={_qty_str_ts} mark=${_mark:.4f} "
                                f"(reconcile_orphan will record close on next tick)"
                            )
                        except Exception as _ts_close_err:
                            log(
                                f"  RUNNER_TIMESTOP_CLOSE_ERR: {_sym_algo}: "
                                f"{str(_ts_close_err)[:110]}"
                            )
                        continue  # skip SL ratchet for this position this tick
                except Exception as _ts_outer_err:
                    log(f"  RUNNER_TIMESTOP_ERR: {_sym_algo}: {str(_ts_outer_err)[:110]}")
                # ── END RUNNER TIME-STOP ──────────────────────────────────

                try:
                    _qty_str = ex.amount_to_precision(_sym_ccxt, _contracts)
                    if _cur_sl is None:
                        # SL hiç yok
                        _breached = _mark > 0 and (
                            (_side == "long" and _sl_price >= _mark)
                            or (_side == "short" and _sl_price <= _mark)
                        )
                        if _breached:
                            # Çıplak + SL seviyesi ihlal → kapat. Önce reduceOnly
                            # market; testnet -2022 "ReduceOnly rejected" alırsa
                            # reduceOnly'siz plain-market'e düş (TAZE qty ile —
                            # stale qty ters pozisyon açmasın). Böylece çıplak
                            # zarar pozisyonu HER ZAMAN kapanır (asla naked kalmaz).
                            # FIX 2026-06-04: AVAX -2022 olayı (manuel kapatma gerekmişti).
                            try:
                                ex.create_order(
                                    symbol=_sym_ccxt,
                                    type="MARKET",
                                    side=_close_side,
                                    amount=float(_qty_str),
                                    params={"reduceOnly": True},
                                )
                                log(
                                    f"  PROT_WATCHDOG: {_sym_algo} SL yok + ${_sl_price} "
                                    f"ihlal — market(reduceOnly) kapatıldı qty={_qty_str}"
                                )
                            except Exception as _ro_err:
                                _fresh_amt = 0.0
                                try:
                                    for _fp in ex.fetch_positions([_sym_ccxt]):
                                        _pa = abs(float(_fp["info"].get("positionAmt", 0) or 0))
                                        if _pa > 0:
                                            _fresh_amt = _pa
                                            break
                                except Exception:
                                    _fresh_amt = _contracts
                                if _fresh_amt > 0:
                                    _fresh_qty = ex.amount_to_precision(_sym_ccxt, _fresh_amt)
                                    ex.create_order(
                                        symbol=_sym_ccxt,
                                        type="MARKET",
                                        side=_close_side,
                                        amount=float(_fresh_qty),
                                    )
                                    log(
                                        f"  PROT_WATCHDOG_HEAL: {_sym_algo} reduceOnly "
                                        f"reddedildi ({str(_ro_err)[:40]}) → plain-market "
                                        f"kapatıldı qty={_fresh_qty}"
                                    )
                                else:
                                    log(
                                        f"  PROT_WATCHDOG: {_sym_algo} kapatma atlandı "
                                        f"— pozisyon zaten kapanmış"
                                    )
                        else:
                            _sl_str = ex.price_to_precision(_sym_ccxt, _sl_price)
                            ex.create_order(
                                symbol=_sym_ccxt,
                                type="STOP_MARKET",
                                side=_close_side,
                                amount=float(_qty_str),
                                params={
                                    "stopPrice": _sl_str,
                                    "reduceOnly": True,
                                    "workingType": "MARK_PRICE",
                                },
                            )
                            log(
                                f"  PROT_WATCHDOG: {_sym_algo} SL eksikti → "
                                f"kondu @ ${_sl_str} qty={_qty_str}"
                            )
                    else:
                        # B-2 fix (CEO 2026-05-20): SL qty pozisyonu tam
                        # kapsamıyorsa (pyramid leg / re-arm pozisyonu
                        # büyüttü, eski SL küçük kaldı) tam qty'ye çek.
                        # reduceOnly → güvenli; mevcut trigger fiyatı korunur.
                        # Önce tam qty yeni SL, sonra eski kısmi SL iptal.
                        if _cur_sl_qty > 0 and _cur_sl_qty < _contracts * 0.99:
                            _sl_str = ex.price_to_precision(_sym_ccxt, _cur_sl)
                            ex.create_order(
                                symbol=_sym_ccxt,
                                type="STOP_MARKET",
                                side=_close_side,
                                amount=float(_qty_str),
                                params={
                                    "stopPrice": _sl_str,
                                    "reduceOnly": True,
                                    "workingType": "MARK_PRICE",
                                },
                            )
                            try:
                                ex.fapiPrivateDeleteAlgoOrder(
                                    {"symbol": _sym_algo, "algoId": _cur_aid}
                                )
                            except Exception as _cx:
                                log(
                                    f"  PROT_WATCHDOG: {_sym_algo} eski "
                                    f"kısmi SL iptal edilemedi: "
                                    f"{str(_cx)[:60]}"
                                )
                            log(
                                f"  PROT_WATCHDOG: {_sym_algo} SL qty "
                                f"eksik ({_cur_sl_qty}/{_contracts}) → "
                                f"tam qty'ye çekildi @ ${_sl_str}"
                            )
                            continue
                        # SL var → ratchet: hedef daha iyiyse taşı
                        _tol = _mark * 0.0005 if _mark > 0 else 0.0
                        _better = (
                            (_sl_price > _cur_sl + _tol)
                            if _side == "long"
                            else (_sl_price < _cur_sl - _tol)
                        )
                        if not _better:
                            continue
                        _sl_str = ex.price_to_precision(_sym_ccxt, _sl_price)
                        # Önce yeni koy, sonra eskiyi iptal (asla çıplak kalmaz)
                        ex.create_order(
                            symbol=_sym_ccxt,
                            type="STOP_MARKET",
                            side=_close_side,
                            amount=float(_qty_str),
                            params={
                                "stopPrice": _sl_str,
                                "reduceOnly": True,
                                "workingType": "MARK_PRICE",
                            },
                        )
                        try:
                            ex.fapiPrivateDeleteAlgoOrder({"symbol": _sym_algo, "algoId": _cur_aid})
                        except Exception as _cx:
                            log(
                                f"  PROT_WATCHDOG: {_sym_algo} eski SL iptal "
                                f"edilemedi: {str(_cx)[:60]}"
                            )
                        log(
                            f"  PROT_WATCHDOG: {_sym_algo} SL taşındı "
                            f"${_cur_sl} → ${_sl_str} (trailing)"
                        )
                except Exception as _wd_place_err:
                    log(f"  PROT_WATCHDOG_FAIL: {_sym_algo}: " f"{str(_wd_place_err)[:110]}")
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
                    now_ts = datetime.now(UTC)
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
    now = datetime.now(UTC)
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
    now = datetime.now(UTC)
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
    # FIX 2026-05-28 (audit-A1): SIGTERM/SIGHUP handler kur.
    # PID 17267 sessiz öldü çünkü signal handler yoktu — Python interpreter
    # cleanup yaptı (stderr'e resource_tracker warning düştü) ama futures_daemon.log'a
    # "shutdown" satırı yazılmadı. Şimdi handler "SIGNAL_RECEIVED: SIGTERM" log'layıp
    # _stop_flag set ediyor; main loop bunu kontrol edip clean exit yapacak.
    _install_signal_handlers()

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
        dms_15m = DeadMansSwitch(
            exchange=_dms_exchange,
            service_name="futures_daemon_15m",
            tf="15m",
            db_path=IDEMPOTENCY_DB,
        )
        dms_15m.start()
        log("15M_DMS: başlatıldı (tf=15m, heartbeat=20s, timeout=1800s, flatten AKTİF)")
    except Exception as e:
        log(f"15M_DMS_INIT_ERROR: {e} — DMS devre dışı, devam ediyor")
        dms_15m = None

    # Prometheus metrics — lazy import (metrics yoksa graceful)
    try:
        from price_action.api.prometheus_metrics import (
            missed_bars_total,
            position_monitor_duration_seconds,
            scan_latency_seconds,
            signal_to_order_latency_seconds,
        )

        _metrics_ok = True
    except Exception:
        _metrics_ok = False

    # Pyramid router — SEC54.3 (P-04/P-05 fix: build_position_from_signal + pop on close)
    # Post-only flag 15m YAML'den okunur (2026-05-21: paper fill rate %87.5 → enabled)
    _pyramid_router_15m = None
    # FIX 2026-05-26 (Faz 14.9): pyramid_enabled gate.
    # Config kapalıysa init etme → eski store'daki PENDING leg'ler tetiklenmez.
    if not _pyramid_enabled_15m():
        log("15M_PYRAMID: skip init (strategy_portfolio.pyramid_enabled=false)")
    else:
        try:
            import yaml as _yaml_pr

            _pr_yaml_path = _risk_config_15m()
            with open(_pr_yaml_path, encoding="utf-8") as _pr_f:
                _pr_cfg = _yaml_pr.safe_load(_pr_f) or {}
            _pr_exec = _pr_cfg.get("execution", {})
            _pr_po_enabled = bool(_pr_exec.get("post_only_limit_enabled", False))
            _pr_po_timeout = int(_pr_exec.get("post_only_fallback_seconds", 30))
            _pr_slip_limit = float(_pr_exec.get("slippage_limit_bps", 25.0))
            # pyramid_slippage_limit_bps: pyramid leg için ayrı market-fallback cap (default 50bps)
            _pr_pyr_slip = float(_pr_exec.get("pyramid_slippage_limit_bps", 50.0))
            from price_action.execution.idempotency import IdempotencyStore
            from price_action.execution.pyramid_router import PyramidRouter
            from price_action.execution.slippage_tracker import SlippageTracker

            _pyramid_router_15m = PyramidRouter(
                exchange=None,  # başlangıçta None; exchange signal submit sonrası set edilir
                idempotency_store=IdempotencyStore(db_path=IDEMPOTENCY_DB),
                slippage_tracker=SlippageTracker(),
                post_only_enabled=_pr_po_enabled,
                fallback_seconds=_pr_po_timeout,
                slippage_limit_bps=_pr_pyr_slip,
                mode=os.environ.get("PA_RUN_MODE", "paper"),
            )
            log(
                f"15M_PYRAMID: PyramidRouter başlatıldı (SEC54.3, post_only={_pr_po_enabled}, "
                f"timeout={_pr_po_timeout}s, slip={_pr_pyr_slip}bps)"
            )
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

        with open(_risk_config_15m(), encoding="utf-8") as _sl_f:
            _sl_cfg_raw = _yaml_sl.safe_load(_sl_f) or {}
        _sl_pct_min_15m = float((_sl_cfg_raw.get("execution", {}) or {}).get("sl_pct_min", 0.0))
        _sl_cfg_load_ok = True
    except Exception as _sl_err:
        log(
            f"15M_WIDESTOP_CFG_FAIL: {_sl_err} — SAFE DEFAULT sl_pct_min=1.0 (TÜM sinyaller reddedilecek)"
        )
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
        log(
            f"15M_WIDESTOP: sl_pct_min={_sl_pct_min_15m:.4f} AKTİF — "
            f"dar-stop sinyaller REJECT edilecek"
        )
    elif not _sl_cfg_load_ok:
        log(
            f"15M_WIDESTOP_SAFE_MODE: sl_pct_min={_sl_pct_min_15m:.4f} "
            f"(config load fail — tüm sinyaller reddedilir; config'i düzelt + daemon restart)"
        )

    # SEC58-L2: startup'ta DB'den aktif pyramid pozisyonlarını yükle (restart recovery)
    _pyramid_store_load_on_startup()

    # FIX 2026-05-31 (Faz restart-rebuild): pyramid_store boşsa borsadaki açık
    # pozisyonlar için takip kaydını yeniden kur (trailing donukluğunu önler).
    # G22 yolu (_cur_sl → intended_sl) initial_r'yi yanlış hesaplıyor çünkü
    # exchange SL'i trailing sonrası taşınmış olabilir → bu rebuild orijinal
    # entry + sl_price'ı journal'dan alarak _desired_sl_price() hesabını doğru yapar.
    try:
        from scripts.futures_trade_daily import get_futures_exchange as _get_fx_rb

        _rb_exchange = _get_fx_rb()
        _rebuild_position_tracking_from_exchange(_rb_exchange)
    except Exception as _rb_err:
        log(
            f"REBUILD_TRACKING_INIT_ERR: {_rb_err} — takip kaydı yeniden kurulamadı, G22 fallback devam"
        )

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
    # FIX 2026-05-28 (audit-A1): hata-bazlı exponential backoff sayacı.
    # Önceki bug: `15M_LOOP_ERROR` log'lanıyor sonra hemen sıradaki bar'ı
    # bekliyordu — kalıcı bir hata (ör. DuckDB lock) varsa her tick'te aynı
    # hata, log spam'i, CPU spin. Şimdi ardışık hata sayısına göre 2-60s
    # bekliyoruz; 10+ ardışık hatada daemon abort ediyor (launchd restart eder).
    _err_count = 0
    _ERR_ABORT_THRESHOLD = 10

    try:
        while True:
            # FIX 2026-05-28 (audit-A1): graceful shutdown bayrağı.
            if _stop_flag:
                log("15M_STOP_FLAG aktif — graceful exit (signal handler tetikledi)")
                break

            # Kill-switch kontrolü
            halted, reason = _kill_switch_active()
            if halted:
                log(f"15M_KILL_SWITCH ACTIVE — daemon exiting. Reason: {reason}")
                break

            # FIX 2026-05-28 (audit-Y1): DMS thread health check.
            # DMS heartbeat/watchdog thread'leri ayrı log dosyasına (futures_daemon_15m_dms.log)
            # yazıyor; bu thread'ler sessiz ölürse main loop fark etmiyordu (audit
            # bulgusu: DMS log'unda 25+ "started" satırı, hiç heartbeat satırı yok =
            # restart spam). Şimdi her tick başında is_alive() check; ölü ise abort.
            if dms_15m is not None:
                _hb = getattr(dms_15m, "_heartbeat_thread", None)
                _wd = getattr(dms_15m, "_watchdog_thread", None)
                _hb_dead = _hb is not None and not _hb.is_alive()
                _wd_dead = _wd is not None and not _wd.is_alive()
                if _hb_dead or _wd_dead:
                    log(
                        f"15M_DMS_THREAD_DEAD: heartbeat_alive={not _hb_dead} "
                        f"watchdog_alive={not _wd_dead} — emergency shutdown"
                    )
                    try:
                        from price_action.orchestrator.notifications import push_critical

                        push_critical(
                            "⚠️ 15m DMS thread ÖLDÜ (heartbeat veya watchdog) — "
                            "bot acil durduruluyor. launchd KeepAlive restart eder."
                        )
                    except Exception:
                        pass
                    break

            # FIX 2026-05-28 (audit-A1): sleep_until + boundary detect + scan'i
            # tek try'a aldık. Önceden sleep_until (1138) try DIŞINDAYDI →
            # uyku sırasında atılan herhangi bir exception (signal-related,
            # OS interrupt, vb.) hiçbir log yazmadan process'i öldürebiliyordu.
            try:
                # Sonraki bar kapanışını hesapla + 5s buffer ekle
                next_close = next_15m_boundary() + timedelta(seconds=5)
                log(f"15M_WAIT: sonraki bar kapanış {next_close.strftime('%H:%M:%S')} UTC")
                sleep_until(next_close)

                # Sleep sonrası signal geldi mi?
                if _stop_flag:
                    log("15M_STOP_FLAG: uyku sonrası tespit — graceful exit")
                    break

                # Missed bar detect: önceki boundary'den 2+ bar geçti mi?
                current_boundary = next_close - timedelta(seconds=5)
                if last_bar_boundary is not None:
                    bars_elapsed = int((current_boundary - last_bar_boundary).total_seconds() / 900)
                    if bars_elapsed > 1:
                        log(
                            f"15M_MISSED_BARS: {bars_elapsed - 1} bar kaçırıldı "
                            f"(son={last_bar_boundary.strftime('%H:%M')}, "
                            f"şimdi={current_boundary.strftime('%H:%M')})"
                        )
                        if _metrics_ok:
                            try:
                                missed_bars_total.labels(tf="15m").inc(bars_elapsed - 1)
                            except Exception:
                                pass
                last_bar_boundary = current_boundary

                scan_start = datetime.now(UTC)
                # ------ SIGNAL SCAN ------
                # SEC56 FIX: current_boundary = son kapanan barın close timestamp'i.
                # scan_start = datetime.now() → birkaç saniye sonra olduğu için
                # semantik olarak yanlıştı; current_boundary daha doğru.
                signals = _scan_signals_15m(current_boundary)

                scan_elapsed = (datetime.now(UTC) - scan_start).total_seconds()
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
                            age_min = (datetime.now(UTC) - _bc.to_pydatetime()).total_seconds() / 60
                            if age_min > 30:
                                log(
                                    f"  15M_REJECT_STALE(daemon-guard): {sig.get('symbol','?')} age={age_min:.1f}min"
                                )
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
                        _ws_sl_pct = abs(_ws_entry - _ws_sl) / _ws_entry if _ws_entry > 0 else 0.0
                        if _ws_sl_pct < _sl_pct_min_15m:
                            log(
                                f"  15M_REJECT_WIDESTOP: {sig.get('symbol','?')} "
                                f"sl_pct={_ws_sl_pct:.4f} < {_sl_pct_min_15m:.4f}"
                            )
                            continue

                    order_start = datetime.now(UTC)
                    try:
                        import uuid as _uuid

                        import yaml as _yaml

                        from scripts.futures_trade_daily import (
                            fetch_futures_state,
                            get_futures_exchange,
                            place_protection_orders,
                            setup_leverage,
                        )
                        from scripts.lib.risk_integration import (
                            build_futures_account_state,
                            build_signal_from_scan,
                            load_risk_officer,
                        )

                        _ex_submit = get_futures_exchange()
                        _state_submit = fetch_futures_state(_ex_submit)

                        # SEC-#3A: Konsantrasyon fail-safe — stale pozisyon dedektörü.
                        # fetch_positions() bazen boş dönebilir (rate-limit 418, API stale)
                        # ama borsada hala açık pozisyon bulunabilir. Bu durumda
                        # concentration_gate "pozisyon yok" sanıp yeni emri geçirir →
                        # ALGO sembolünde yığılma (gözlemlenen: %15→%27).
                        # Stale koşul: positions_ok=False VEYA (positions boş AMA initialMargin>0)
                        # İkinci koşul: fetch_positions() boş döndü ama raw account
                        # totalInitialMargin > 0 → borsada pozisyon var ama liste gelmedi.
                        _pos_ok_15m = _state_submit.get("positions_ok", True)
                        _init_margin_15m = float(_state_submit.get("total_initial_margin", 0))
                        _pos_list_15m = _state_submit.get("positions", [])
                        _stale_positions_15m = not _pos_ok_15m or (
                            len(_pos_list_15m) == 0 and _init_margin_15m > 0
                        )
                        if _stale_positions_15m:
                            log(
                                f"  ENTRY_SKIP_STALE_POS: {sig.get('symbol','?')} — "
                                f"pozisyon verisi güvenilmez (positions_ok={_pos_ok_15m}, "
                                f"pos_list_len={len(_pos_list_15m)}, "
                                f"initialMargin={_init_margin_15m:.2f}), giriş atlandı"
                            )
                            continue

                        _risk_yaml_path = _risk_config_15m()
                        # FIX 2026-06-10 (BLOCKER-2): bot-bazlı breaker state
                        _breaker_state_path = BREAKER_STATE_15M
                        _breaker_state_path.parent.mkdir(parents=True, exist_ok=True)
                        _risk_officer = load_risk_officer(
                            yaml_path=_risk_yaml_path,
                            breaker_state_path=_breaker_state_path,
                        )
                        with open(_risk_yaml_path, encoding="utf-8") as _f:
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
                            _signal_obj,
                            _account,
                            market_price=_cur_px,
                            returns_df=_returns_df,
                        )

                        if not hasattr(_decision, "quantity"):
                            log(
                                f"  15M_REJECT_RISK: {sig['symbol']} {sig.get('strategy','')} "
                                f"reason={getattr(_decision,'reason','unknown')}"
                            )
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
                                    f"{sig.get('bar_close_ts') or sig.get('ts','')!s}"
                                )
                                _fp = _hashlib.sha256(_fp_src.encode()).hexdigest()[:16]
                                _coid = f"PA_{_fp}"  # max 19 char (< 36 limit)

                                from price_action.execution.idempotency import (
                                    IdempotencyStore as _IdemStore,
                                )

                                _idem = _IdemStore(db_path=IDEMPOTENCY_DB)
                                if _idem.is_seen(_fp):
                                    log(
                                        f"  15M_IDEM_SKIP: {sig['symbol']} {sig.get('strategy','')} "
                                        f"fp={_fp} — zaten gönderildi (restart/duplicate scan)"
                                    )
                                    continue

                                # FIX 2026-06-10 (v14 audit MAJOR-2): borsa minQty/stepSize/
                                # minNotional ön-kontrolü. 19-sembol evreninde (ALGO/XLM gibi
                                # düşük fiyatlılar) precision yuvarlaması sonrası qty minQty
                                # altına düşebilir veya MIN_NOTIONAL (-4164) reddi gelir —
                                # önceden bu genel 15M_ENTRY_ERR'e düşüp sinyal sessizce
                                # kayboluyordu. Şimdi temiz reject + idempotency'e YAZILMAZ.
                                try:
                                    _mkt = _ex_submit.market(sig["symbol"])
                                    _lim = _mkt.get("limits", {}) or {}
                                    _min_amt = float((_lim.get("amount", {}) or {}).get("min") or 0)
                                    _min_cost = float((_lim.get("cost", {}) or {}).get("min") or 0)
                                    _qty_prec = float(
                                        _ex_submit.amount_to_precision(sig["symbol"], _qty)
                                    )
                                    _notional_prec = _qty_prec * float(_cur_px or 0)
                                    if (
                                        _qty_prec <= 0
                                        or (_min_amt and _qty_prec < _min_amt)
                                        or (_min_cost and _notional_prec < _min_cost)
                                    ):
                                        log(
                                            f"  15M_BELOW_EXCHANGE_MIN: {sig['symbol']} "
                                            f"qty={_qty_prec} notional={_notional_prec:.2f} "
                                            f"(minQty={_min_amt}, minNotional={_min_cost}) — reject"
                                        )
                                        continue
                                    _qty = _qty_prec
                                except Exception as _lim_err:
                                    log(
                                        f"  15M_EXCHANGE_MIN_CHECK_ERR: "
                                        f"{str(_lim_err)[:80]} — kontrol atlandı (fail-open)"
                                    )

                                _idem.mark_submitted(_fp, symbol=sig["symbol"], side=_order_side)

                                # ── POST-ONLY ENTRY PATH (2026-05-21) ──────────────────────────
                                # Config-gated: post_only_limit_enabled (default False → backward-compat)
                                # 1d pattern (futures_trade_daily.py:331-343) birebir izlendi.
                                # Idempotency: _coid her iki yolda da geçilir.
                                # SlippageExceededError: yakala, logla, o sinyali skip et, devam et.
                                _15m_po_enabled = bool(
                                    _risk_cfg.get("execution", {}).get(
                                        "post_only_limit_enabled", False
                                    )
                                )
                                _15m_po_timeout = int(
                                    _risk_cfg.get("execution", {}).get(
                                        "post_only_fallback_seconds", 30
                                    )
                                )
                                _15m_slip_limit = float(
                                    _risk_cfg.get("execution", {}).get("slippage_limit_bps", 25.0)
                                )
                                _fill_method = "market_only"
                                try:
                                    if _15m_po_enabled:
                                        from price_action.execution.post_only_router import (
                                            place_post_only_with_fallback as _po_place,
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
                                        log(
                                            f"  15M_PO_ENTRY: {sig['symbol']} method={_fill_method} "
                                            f"coid={_coid}"
                                        )
                                    else:
                                        _order = _ex_submit.create_market_order(
                                            sig["symbol"],
                                            _order_side,
                                            _qty,
                                            params={"newClientOrderId": _coid},
                                        )
                                        _fill_method = "market_only"
                                except Exception as _entry_exc:
                                    # SlippageExceededError veya başka hata — sinyali skip et
                                    _exc_name = type(_entry_exc).__name__
                                    if "SlippageExceeded" in _exc_name:
                                        log(
                                            f"  15M_SLIP_EXCEEDED: {sig['symbol']} {_entry_exc} — sinyal atlandı"
                                        )
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
                                                "ts": datetime.now(UTC).isoformat(),
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
                                                _pf.write(
                                                    json.dumps(_pending_entry, default=str) + "\n"
                                                )
                                            log(
                                                f"  15M_ENTRY_DEFERRED: {sig['symbol']} → pending_retries queue "
                                                f"(daemon devam ediyor, retry async)"
                                            )
                                        except Exception as _q_exc:
                                            log(f"  15M_QUEUE_FAIL: {sig['symbol']} {_q_exc}")
                                        # NOT: _idem.mark_filled YAPMA — retry başarılı olursa
                                        # işaretlemez, sonsuz queue riski. Scheduler retry
                                        # sonucuna göre mark_filled yapar.
                                        continue

                                    # Non-timeout hata: doğrudan miss, audit + alert
                                    log(
                                        f"  15M_ENTRY_ERR: {sig['symbol']} {_exc_name}: {str(_entry_exc)[:120]}"
                                    )
                                    try:
                                        _missed_path = Path("data/missed_signals.jsonl")
                                        _missed_path.parent.mkdir(parents=True, exist_ok=True)
                                        _missed_entry = {
                                            "ts": datetime.now(UTC).isoformat(),
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
                                        from price_action.orchestrator.notifications import (
                                            push_critical,
                                        )

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

                                _avg_px = float(
                                    _order.get("average") or _order.get("price") or _cur_px
                                )
                                # FIX 2026-05-30 (INC2-fill-qty): market_fallback path'de
                                # Binance testnet bazen filled=None/0 döner (async fill).
                                # Önceki: `or _qty` → intended qty yazılıyordu (NEAR 291→219 bug).
                                # Düzeltme: filled falsy ise fetch_order ile gerçek değeri al;
                                # o da başarısızsa/hâlâ 0 ise intended qty'yi yaz AMA warn log.
                                _raw_filled = _order.get("filled")
                                if not _raw_filled or float(_raw_filled) <= 0:
                                    _order_id_for_fetch = str(_order.get("id", ""))
                                    if _order_id_for_fetch:
                                        try:
                                            _fetched = _ex_submit.fetch_order(
                                                _order_id_for_fetch, sig["symbol"]
                                            )
                                            _raw_filled = _fetched.get("filled") or _raw_filled
                                            # avg_px da fetch'ten daha güvenilir olabilir
                                            _fetched_avg = _fetched.get("average") or _fetched.get(
                                                "price"
                                            )
                                            if _fetched_avg:
                                                _avg_px = float(_fetched_avg)
                                        except Exception as _fe_err:
                                            log(
                                                f"  15M_FILL_FETCH_ERR: {sig['symbol']} fetch_order fail: {str(_fe_err)[:80]}"
                                            )
                                if _raw_filled and float(_raw_filled) > 0:
                                    _fill_qty = float(_raw_filled)
                                else:
                                    log(
                                        f"  15M_FILL_QTY_WARN: {sig['symbol']} filled=0/None after fetch — "
                                        f"using intended qty={_qty} (AUDIT REQUIRED)"
                                    )
                                    _fill_qty = float(_qty)
                                _sig_id = _uuid.uuid4().hex[:16]
                                _idem.mark_filled(
                                    _fp, str(_order.get("id", "")), _avg_px, _fill_qty
                                )

                                log(
                                    f"  15M_FILL: [{sig['side'].upper()}] {sig['symbol']} "
                                    f"{sig.get('strategy','')} qty={_fill_qty:.4f} "
                                    f"px=${_avg_px:.4f} lev={_lev}x id={_order.get('id','?')} "
                                    f"coid={_coid} method={_fill_method}"
                                )

                                # FIX 2026-05-26 (Faz 14.5): Telegram position-open bildirimi
                                try:
                                    from price_action.orchestrator.notifications import (
                                        notify_position_open,
                                    )

                                    _entry_notional_telegram = _fill_qty * _avg_px
                                    _margin_telegram = _entry_notional_telegram / max(
                                        int(_lev or 1), 1
                                    )
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
                                    from price_action.execution.slippage_tracker import (
                                        SlippageTracker as _ST,
                                    )

                                    _st = _ST()
                                    _entry_notional = _fill_qty * _avg_px
                                    # post_only_filled → maker rebate (~4bps), market_fallback → taker (~8bps)
                                    _is_maker = _fill_method == "post_only_filled"
                                    _entry_fee_bps = 4.0 if _is_maker else 8.0
                                    _entry_fee_usdt = _entry_notional * _entry_fee_bps / 10_000
                                    _st.record_fill(
                                        fill_id=f"entry_{_sig_id}",
                                        ts=datetime.now(UTC),
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
                                    _jcon.execute(
                                        """
                                        INSERT INTO futures_signals VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                                    """,
                                        (
                                            _sig_id,
                                            sig.get("bar_close_ts") or sig.get("ts"),
                                            sig["symbol"],
                                            sig.get("strategy", ""),
                                            sig["side"],
                                            float(sig["sl_price"]),
                                            float(sig["tp_price"]),
                                            float(sig.get("confluence", 0.0)),
                                            _lev,
                                            "filled",
                                            str(_order.get("id", "")),
                                            _avg_px,
                                            _fill_qty,
                                            _notional,
                                            _margin,
                                            None,
                                        ),
                                    )
                                    _jcon.commit()
                                    _jcon.close()
                                except Exception as _je_sig:
                                    log(f"    15M_JOURNAL_SIG_ERR: {str(_je_sig)[:120]}")

                                # Protection orders
                                _prot = place_protection_orders(
                                    _ex_submit,
                                    sig["symbol"],
                                    sig["side"],
                                    _fill_qty,
                                    float(sig["tp_price"]),
                                    float(sig["sl_price"]),
                                    entry_price=_avg_px,
                                )
                                # FIX 2026-06-05: orijinal SL'i stabil sakla → watchdog
                                # trailing'i hareketli SL yerine bunu kullanır (XRP +$64→$0 fix).
                                try:
                                    _ORIG_INTENDED_SL[
                                        f"{sig['symbol'].replace('/', '').replace(':USDT', '')}"
                                        f"|{str(sig['side']).lower()}"
                                    ] = float(sig["sl_price"])
                                except Exception:
                                    pass
                                if _prot["status"] == "placed":
                                    log(
                                        f"    15M_PROTECT: tp=${_prot['tp_price']:.4f} sl=${_prot['sl_price']:.4f}"
                                    )
                                    # A2: futures_protection_orders INSERT (1d parity)
                                    try:
                                        _jcon = duckdb.connect(str(JOURNAL))
                                        _prot_id = _uuid.uuid4().hex[:16]
                                        _notes = None
                                        if _prot.get("mode") == "multi_target":
                                            _notes = f"mode=multi_target tp2={_prot.get('tp2_price',0):.4f} tp2_id={_prot.get('tp2_order_id','')}"
                                        _jcon.execute(
                                            """
                                            INSERT INTO futures_protection_orders VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                                        """,
                                            (
                                                _prot_id,
                                                datetime.now(UTC),
                                                _sig_id,
                                                sig["symbol"],
                                                sig["side"],
                                                _fill_qty,
                                                _prot["tp_price"],
                                                _prot["sl_price"],
                                                _prot.get("tp_order_id"),
                                                _prot.get("sl_order_id"),
                                                "placed",
                                                _notes,
                                            ),
                                        )
                                        _jcon.commit()
                                        _jcon.close()
                                    except Exception as _je_prot:
                                        log(f"    15M_JOURNAL_PROT_ERR: {str(_je_prot)[:120]}")
                                else:
                                    log(f"    15M_PROTECT_ERR: {_prot.get('reason')}")

                                # FIX 2026-06-05 (kullanıcı isteği — LINK -$224 çıplak olayı):
                                # GİRİŞTE HEMEN-DOĞRULA-YOKSA-KOY. place_protection_orders
                                # başarısız dönebilir VEYA SL borsaya düşmeyebilir → pozisyon
                                # çıplak kalır, 15-dk watchdog'a kadar korumasız (LINK girişten
                                # sonra çıplak kalıp -%20 düştü). Çözüm: koruma çağrısından HEMEN
                                # sonra borsada gerçekten SL var mı bak; yoksa anında widestop SL
                                # koy — tick'i BEKLEME. Pozisyon fresh (mark≈entry) → reduceOnly
                                # STOP tetik-altı değil, -2022 riski düşük; olursa watchdog yakalar.
                                try:
                                    _vsym = sig["symbol"].replace("/", "").replace(":USDT", "")
                                    _v_algo = _ex_submit.fapiPrivateGetOpenAlgoOrders()
                                    _v_ords = (
                                        _v_algo.get("orders", _v_algo)
                                        if isinstance(_v_algo, dict)
                                        else _v_algo
                                    )
                                    _has_sl = any(
                                        o.get("symbol") == _vsym
                                        and "STOP" in str(o.get("orderType", ""))
                                        for o in (_v_ords or [])
                                    )
                                    if not _has_sl:
                                        _v_side = "SELL" if str(sig["side"]).lower() == "long" else "BUY"
                                        _v_sl_str = _ex_submit.price_to_precision(
                                            sig["symbol"], float(sig["sl_price"])
                                        )
                                        _v_qty_str = _ex_submit.amount_to_precision(
                                            sig["symbol"], _fill_qty
                                        )
                                        _ex_submit.create_order(
                                            symbol=sig["symbol"],
                                            type="STOP_MARKET",
                                            side=_v_side,
                                            amount=float(_v_qty_str),
                                            params={
                                                "stopPrice": _v_sl_str,
                                                "reduceOnly": True,
                                                "workingType": "MARK_PRICE",
                                            },
                                        )
                                        log(
                                            f"    15M_PROTECT_VERIFY: {_vsym} SL borsada YOKTU "
                                            f"→ ANINDA kondu @ ${_v_sl_str} qty={_v_qty_str}"
                                        )
                                except Exception as _v_err:
                                    log(
                                        f"    15M_PROTECT_VERIFY_FAIL: {sig['symbol']} "
                                        f"{str(_v_err)[:90]} — watchdog yedek yakalayacak"
                                    )

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
                                            log(
                                                f"    15M_PYRAMID_REGISTERED: pos_id={_sig_id} "
                                                f"triggers={_pyr_triggers}"
                                            )
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

                    order_elapsed = (datetime.now(UTC) - order_start).total_seconds()
                    if _metrics_ok:
                        try:
                            signal_to_order_latency_seconds.observe(order_elapsed)
                        except Exception:
                            pass

                # ------ POSITION MONITOR (pyramid hook + P-05 TP/SL pop) ------
                pos_monitor_start = datetime.now(UTC)
                try:
                    position_check()  # 1d pos_check: TP/SL fill detection + orphan cleanup

                    # P-04/P-05: PyramidRouter hook — aktif pyramid pozisyonları kontrol et
                    if _pyramid_router_15m is not None and _pyramid_positions:
                        try:
                            from scripts.futures_trade_daily import (
                                fetch_futures_state,
                                get_futures_exchange,
                            )

                            _ex_mon = get_futures_exchange()
                            # Restart-recovered pyramid pozisyonları için exchange set et
                            # (router exchange=None ile init edilir, yeni signal fill yoksa
                            # boş kalır → create_market_order'da NoneType crash).
                            if _pyramid_router_15m.exchange is None:
                                _pyramid_router_15m.exchange = _ex_mon
                            _state_mon = fetch_futures_state(_ex_mon)
                            _pyr_now = datetime.now(UTC)
                            # Aktif exchange pozisyonlarından mark price haritası
                            _mark_map: dict[str, float] = {}
                            for _ep in _state_mon.get("positions", []):
                                _sym_raw = _ep.get("symbol", "")
                                _sym_clean = _sym_raw.replace(":USDT", "").replace("/", "")
                                _mark_map[_sym_clean] = float(
                                    _ep.get("markPrice") or _ep.get("entryPrice") or 0
                                )

                            # P-05: exchange'de artık açık olmayan pozisyonları _pyramid_positions'dan çıkar
                            _active_ex_syms: set[str] = set()
                            for _ep in _state_mon.get("positions", []):
                                if abs(float(_ep.get("contracts", 0) or 0)) > 1e-6:
                                    _active_ex_syms.add(
                                        _ep.get("symbol", "").replace(":USDT", "").replace("/", "")
                                    )
                            _to_pop: list[str] = []
                            for _fp, _pyr_pos in list(_pyramid_positions.items()):
                                _pos_sym_clean = (
                                    getattr(_pyr_pos, "symbol", "")
                                    .replace("/", "")
                                    .replace(":USDT", "")
                                )
                                if _pos_sym_clean not in _active_ex_syms:
                                    _to_pop.append(_fp)
                                    log(
                                        f"  15M_PYRAMID_POP: {_fp} {_pos_sym_clean} TP/SL hit — removing"
                                    )
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
                                _sym_clean = (
                                    getattr(_pyr_pos, "symbol", "")
                                    .replace("/", "")
                                    .replace(":USDT", "")
                                )
                                _mark = _mark_map.get(_sym_clean, 0.0)
                                if _mark > 0:
                                    try:
                                        _pyramid_router_15m.on_position_check(
                                            _pyr_pos, _mark, _pyr_now
                                        )
                                    except Exception as _pyr_chk_err:
                                        log(
                                            f"  15M_PYRAMID_CHECK_ERR pos={_fp}: {str(_pyr_chk_err)[:100]}"
                                        )
                        except Exception as pyr_mon_err:
                            log(f"  15M_PYRAMID_MONITOR_ERR: {str(pyr_mon_err)[:120]}")
                except Exception as pm_err:
                    log(f"  15M_POS_MONITOR_ERR: {pm_err}")

                pos_monitor_elapsed = (datetime.now(UTC) - pos_monitor_start).total_seconds()
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
                    from scripts.futures_trade_daily import (
                        fetch_futures_state,
                        get_futures_exchange,
                    )
                    from scripts.lib.risk_integration import (
                        build_futures_account_state,
                        load_risk_officer,
                    )

                    _g19_risk_yaml = _risk_config_15m()
                    # FIX 2026-06-10 (BLOCKER-2): bot-bazlı breaker state
                    _g19_state_path = BREAKER_STATE_15M
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

                log(
                    f"15M_TICK_DONE: scan={scan_elapsed:.1f}s pos_monitor={pos_monitor_elapsed:.1f}s"
                )
                # FIX 2026-05-28 (audit-A1): tick başarılı, backoff sayacını sıfırla.
                _err_count = 0

            except KeyboardInterrupt:
                raise
            except Exception as loop_err:
                # FIX 2026-05-28 (audit-A1): traceback ekle + exponential backoff +
                # abort threshold. Önceden hata sadece tek satır log'lanıp anında
                # devam ediyordu → kalıcı hatada CPU spin ve log spam riski.
                _err_count += 1
                _tb_snippet = _traceback.format_exc()
                log(f"15M_LOOP_ERROR #{_err_count}: {type(loop_err).__name__}: {loop_err}")
                # traceback'i kısalt (log dosyasını şişirmemek için ilk 600 char)
                for _tb_line in _tb_snippet.splitlines()[-12:]:
                    log(f"  TB: {_tb_line[:180]}")
                if _err_count >= _ERR_ABORT_THRESHOLD:
                    log(
                        f"15M_ABORT: {_err_count} ardışık hata → daemon exit "
                        f"(launchd KeepAlive restart eder)"
                    )
                    break
                _backoff = min(2 * (2 ** (_err_count - 1)), 60)
                log(f"15M_BACKOFF: {_backoff}s bekleyip devam (ardışık hata={_err_count})")
                time.sleep(_backoff)

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
    now = datetime.now(UTC)
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
    # FIX 2026-05-28 (audit-Y9): 1d daemon mode'u için signal handler — 5m/15m
    # ile aynı pattern. SIGTERM/SIGHUP'ta graceful exit, sessiz ölüm yok.
    _install_signal_handlers()

    # SEC58-L2: startup recovery — pyramid pozisyonlarını DB'den yükle
    _pyramid_store_load_on_startup()

    # FIX 2026-05-31 (Faz restart-rebuild): borsadaki açık pozisyonlar için
    # takip kaydını yeniden kur (1d daemon için de aynı rebuild mantığı).
    try:
        from scripts.futures_trade_daily import get_futures_exchange as _get_fx_rb1d

        _rb_exchange_1d = _get_fx_rb1d()
        _rebuild_position_tracking_from_exchange(_rb_exchange_1d)
    except Exception as _rb_err_1d:
        log(f"REBUILD_TRACKING_INIT_ERR_1D: {_rb_err_1d} — G22 fallback devam")

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
            # FIX 2026-05-28 (audit-Y9): _stop_flag check (graceful shutdown).
            if _stop_flag:
                log("STOP_FLAG aktif — graceful exit (signal handler)")
                break

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
                        log(
                            f"SLIPPAGE_SUMMARY: n={summary['n_fills']} "
                            f"avg={summary['avg_slippage_bps']:.1f}bps "
                            f"max={summary['max_slippage_bps']:.1f}bps "
                            f"maker={summary['maker_fill_pct']:.0f}% "
                            f"alarm={summary['alarm_level']}"
                        )
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

    # FIX 2026-05-28 (audit-Y9): A1 pattern 5m'e extend.
    # 15m'de sleep_until + signal handler eksikliği PID 17267'yi sessiz
    # öldürmüştü. 5m daemon henüz canlı değil ama aynı bug burada da var.
    # Şu an deploy edilmedi; aktif edilirse bu fix sayesinde sessiz ölüm yok.
    _install_signal_handlers()

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

    # FIX 2026-05-28 (Faz 14.27): 5m bot DMS — kritik güvenlik.
    # Önceden 5m bot DMS başlatmıyordu — 5m bot eğer trade açıp donsa,
    # 30dk timeout flatten YOK = pozisyon açıkta kalır.
    # 5m TF için TF_DMS_PARAMS: heartbeat=10s, timeout=600s (10dk).
    dms_5m = None
    try:
        from price_action.execution.dead_mans_switch import DeadMansSwitch
        from scripts.futures_trade_daily import get_futures_exchange as _get_fx_dms_5m

        _dms_5m_ex = _get_fx_dms_5m()
        dms_5m = DeadMansSwitch(
            exchange=_dms_5m_ex,
            service_name="futures_daemon_5m",
            tf="5m",
            db_path=IDEMPOTENCY_DB,
        )
        dms_5m.start()
        log_5m("5M_DMS: başlatıldı (tf=5m, heartbeat=10s, timeout=600s, flatten AKTİF)")
    except Exception as e:
        log_5m(f"5M_DMS_INIT_ERROR: {e} — DMS devre dışı, devam ediyor (RİSK!)")

    # SL pct min config'den oku
    # FIX 2026-05-26 (H4): config load fail → SAFE DEFAULT 1.0 (tüm sinyaller red)
    # + push_critical alert. Önceden 0.030 fallback'i bot'u "açık" mod'da çalıştırıyordu.
    _sl_pct_min_5m = 0.030
    _cfg_load_ok_5m = False
    try:
        import yaml as _yaml

        with open(_risk_config_5m(), encoding="utf-8") as f:
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
    # FIX 2026-05-28 (audit-Y9): 15m'dekiyle simetrik backoff counter.
    _err_count_5m = 0
    _ERR_ABORT_5M = 10

    try:
        while True:
            # FIX 2026-05-28 (audit-Y9): _stop_flag (SIGTERM/SIGHUP) check.
            if _stop_flag:
                log_5m("5M_STOP_FLAG aktif — graceful exit")
                break

            # Kill switch
            halted, reason = _kill_switch_active()
            if halted:
                log_5m(f"5M_KILL_SWITCH ACTIVE — daemon exiting. Reason: {reason}")
                break

            # FIX 2026-05-28 (audit-Y9): DMS thread health check (15m simetri).
            if dms_5m is not None:
                _hb5 = getattr(dms_5m, "_heartbeat_thread", None)
                _wd5 = getattr(dms_5m, "_watchdog_thread", None)
                if (_hb5 is not None and not _hb5.is_alive()) or (
                    _wd5 is not None and not _wd5.is_alive()
                ):
                    log_5m("5M_DMS_THREAD_DEAD: emergency shutdown (launchd restart eder)")
                    try:
                        from price_action.orchestrator.notifications import push_critical

                        push_critical("⚠️ 5m DMS thread ÖLDÜ — bot acil durduruluyor")
                    except Exception:
                        pass
                    break

            # Sonraki 5m bar kapanışı + 5s buffer
            next_close = next_5m_boundary() + timedelta(seconds=5)
            log_5m(f"5M_WAIT: sonraki bar kapanış {next_close.strftime('%H:%M:%S')} UTC")
            sleep_until(next_close)
            if _stop_flag:
                log_5m("5M_STOP_FLAG: uyku sonrası tespit — graceful exit")
                break

            current_boundary = next_close - timedelta(seconds=5)
            if last_bar_boundary is not None:
                bars_elapsed = int((current_boundary - last_bar_boundary).total_seconds() / 300)
                if bars_elapsed > 1:
                    log_5m(
                        f"5M_MISSED_BARS: {bars_elapsed - 1} bar kaçırıldı "
                        f"(son={last_bar_boundary.strftime('%H:%M')}, "
                        f"şimdi={current_boundary.strftime('%H:%M')})"
                    )
            last_bar_boundary = current_boundary

            # P1c walker halt check
            if p1c_walker is not None:
                halt_status = p1c_walker.check_halts()
                if halt_status.get("halted"):
                    log_5m(
                        f"5M_HALT_ACTIVE: {halt_status.get('reason')} "
                        f"(until={halt_status.get('release_at')})"
                    )
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
                        log_5m(
                            f"  5M_REJECT_WIDESTOP: {sym} sl_pct={sl_pct:.4f} < {_sl_pct_min_5m:.4f}"
                        )
                        n_widestop += 1
                        continue

                # P1c walker karar verir (sizing, halt re-check)
                if p1c_walker is not None:
                    decision = p1c_walker.evaluate_signal(sig)
                    if not decision.get("accept", False):
                        log_5m(f"  5M_REJECT_P1C: {sym} reason={decision.get('reason', '?')}")
                        continue

                n_accept += 1
                log_5m(
                    f"  5M_ACCEPT: {sym} sl_pct={sl_pct:.4f} risk_pct={decision.get('risk_pct', 0):.4f}"
                )

                # Faz 5.3: walker.record_open_position + paper journal entry
                if p1c_walker is not None:
                    try:
                        from datetime import datetime as _dt

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
                            "entry_ts": _dt.now(UTC).isoformat(),
                        }
                        p1c_walker.record_open_position(position)
                        log_5m(
                            f"  5M_POSITION_OPENED: {sym} {sig.get('side')} risk=${decision.get('risk_usdt', 0):.2f} tier={decision.get('tier')}"
                        )

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
            # FIX 2026-05-28 (audit-Y9): tick başarılı → backoff sayacı sıfırla.
            _err_count_5m = 0

            if once:
                log_5m("5M_ONCE_DONE")
                break
    except KeyboardInterrupt:
        log_5m("5M_DAEMON STOPPED (Ctrl+C)")
    except Exception as e:
        # FIX 2026-05-28 (audit-Y9): fatal exception → backoff + retry, loop break ETME.
        # Önceki davranış: tek bir exception bot'u kalıcı kapatıyordu (sonra
        # launchd KeepAlive restart edebilirdi ama in-process recovery yoktu).
        _err_count_5m += 1
        log_5m(f"5M_LOOP_ERROR #{_err_count_5m}: {type(e).__name__}: {e}")
        import traceback as _tb

        for _l in _tb.format_exc().splitlines()[-12:]:
            log_5m(f"  TB: {_l[:180]}")
        if _err_count_5m >= _ERR_ABORT_5M:
            log_5m(
                f"5M_ABORT: {_err_count_5m} ardışık hata, daemon exit " f"(launchd restart eder)"
            )
        else:
            _bk = min(2 * (2 ** (_err_count_5m - 1)), 60)
            log_5m(f"5M_BACKOFF: {_bk}s — sonraki tick'te tekrar dene")
            time.sleep(_bk)
            # Not: bu basit pattern outer try sonrası bir kerelik fail için —
            # geniş retry-loop refactor sonraki turda. Şu an 5m daemon canlı değil.


def _log_5m(msg: str) -> None:
    """5m daemon log — ayrı dosya (futures_daemon_5m.log)."""
    # FIX 2026-05-28 (audit-D2): Z suffix — UTC olduğu net.
    ts = datetime.now(UTC).strftime("%H:%M:%SZ")
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

        ex = ccxt.binance(
            {
                "enableRateLimit": True,
                "options": {"defaultType": "future"},
                "timeout": 10000,
            }
        )
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
        _log_5m(
            f"  5M_BE: {be['symbol']} {be['side']} peak_R={be['peak_R']} "
            f"SL {be['old_sl']:.4f} → {be['new_sl']:.4f}"
        )

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
                _log_5m(
                    f"  5M_CLOSE: {symbol} {side} reason={close_reason} "
                    f"price={current:.4f} pnl=${outcome['pnl_usdt']:+.2f} R={outcome['r_multiple']:+.2f}"
                )
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
        import uuid

        import duckdb

        journal_path = ROOT / "data" / "futures_journal_5m.duckdb"
        if not journal_path.exists():
            return

        con = duckdb.connect(str(journal_path))
        con.execute(
            """
            INSERT INTO futures_trades_closed
            (trade_id, ts_open, ts_close, sym, side, strategy,
             entry_price, exit_price, qty, realized_pnl_usdt, realized_r,
             win, close_reason)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
            (
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
            ),
        )
        con.commit()
        con.close()
    except Exception as e:
        _log_5m(f"  5M_JOURNAL_CLOSE_ERR: {e}")


def _write_5m_journal_signal(sig: dict, decision: dict) -> None:
    """Faz 5.3: futures_journal_5m.duckdb'ye signal entry yaz.

    Mevcut 15m futures_journal'ın schema'sını kullanır — ayrı PnL track için.
    """
    try:
        import uuid

        import duckdb

        journal_path = ROOT / "data" / "futures_journal_5m.duckdb"
        if not journal_path.exists():
            _log_5m(f"5M_JOURNAL_MISSING: {journal_path}")
            return

        con = duckdb.connect(str(journal_path))
        signal_id = str(uuid.uuid4())
        bar_close = sig.get("bar_close_ts") or sig.get("ts")
        if hasattr(bar_close, "to_pydatetime"):
            bar_close = bar_close.to_pydatetime()

        con.execute(
            """
            INSERT INTO futures_signals
            (signal_id, ts, symbol, strategy, side, sl_price, tp_price,
             confluence, leverage, status, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
            (
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
            ),
        )
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
