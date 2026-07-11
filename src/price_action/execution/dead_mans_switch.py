"""Dead Man's Switch — heartbeat + emergency flatten.

Mimari:
  - HeartbeatEmitter: atomic file touch() her 60s (DMS lockless)
  - Fallback DB: heartbeat_log yazı (backward compat + audit trail)
  - Watchdog: file mtime kontrolü; yok/stale → flatten
  - EmergencyFlattener: tüm pozisyonları MARKET ile kapatır

Design:
  - Primary: file mtime (lockless, no DB lock risk)
  - Fallback: DuckDB heartbeat_log (if file write fails)
  - Reader: check file mtime every watchdog_interval; if > timeout → flatten

Usage (daemon içinde):
    dms = DeadMansSwitch(
        exchange,
        service_name="futures_daemon",
        external_heartbeat=True,
    )
    dms.start()
    # ... her başarılı ana-loop tick'inde dms.ping(...) ...
    dms.stop()

Flatten tetiklenince:
  1. Tüm açık pozisyonlar market close
  2. Tüm algo emirler iptal
  3. kill_switch.json yaz {halted: true, reason: "dead_mans_switch"}
  4. Log + Telegram alarm
"""

from __future__ import annotations

import contextlib
import json
import math
import sys
import threading
import time
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb

from price_action.execution.heartbeat_watchdog import HeartbeatWatchdog
from price_action.runtime_paths import RuntimePaths

ROOT = (
    Path(__file__).resolve().parents[3]
)  # G24 fix: Price Action kökü (eskiden parents[4]=projeler — proje dışı)
_RUNTIME_PATHS = RuntimePaths.from_env(ROOT)
DEFAULT_DB = _RUNTIME_PATHS.data / "idempotency.duckdb"
KILL_SWITCH_PATH = _RUNTIME_PATHS.kill_switch

HEARTBEAT_INTERVAL_SEC = 60
WATCHDOG_INTERVAL_SEC = 30
DEAD_MAN_TIMEOUT_SEC = 300  # 5 dakika (1d default)

# FIX 2026-07-08 (W1-HIGH, dalga-3): flatten tek-atış değil — başarısızsa
# sonraki watchdog tick'lerinde tekrar denenir; sonsuz emir spam'ine karşı tavan.
FLATTEN_MAX_ATTEMPTS = 3

# TF-spesifik heartbeat ve timeout ayarlari (master plan §4.5)
# heartbeat_sec: ne siklıkla DB'ye heartbeat yazilir
# timeout_sec: bu kadar susarsa flatten tetiklenir
TF_DMS_PARAMS: dict[str, dict[str, int]] = {
    "1d": {"heartbeat_sec": 60, "timeout_sec": 300, "watchdog_sec": 30},
    "4h": {"heartbeat_sec": 60, "timeout_sec": 300, "watchdog_sec": 30},
    "1h": {"heartbeat_sec": 30, "timeout_sec": 180, "watchdog_sec": 15},
    "15m": {"heartbeat_sec": 20, "timeout_sec": 1800, "watchdog_sec": 10},
    "5m": {"heartbeat_sec": 10, "timeout_sec": 600, "watchdog_sec": 5},
    "1m": {"heartbeat_sec": 5, "timeout_sec": 120, "watchdog_sec": 3},
}


def _dms_params_for_tf(tf: str) -> dict[str, int]:
    """TF icin DMS parametrelerini don."""
    return TF_DMS_PARAMS.get(tf, TF_DMS_PARAMS["1d"])


class DeadMansSwitch:
    """Heartbeat + watchdog + emergency flatten.

    TF-aware constructor: tf parametresi ile heartbeat/timeout otomatik ayarlanir.
    Ornek:
        dms = DeadMansSwitch(exchange, tf="15m")  # 30 dk timeout
        dms = DeadMansSwitch(exchange, tf="1m")   # 2 dk timeout
        dms = DeadMansSwitch(exchange)             # 1d default (5 dk timeout)
    """

    def __init__(
        self,
        exchange: Any | None = None,
        *,
        service_name: str = "execution",
        db_path: Path | str | None = None,
        heartbeat_sec: int | None = None,
        timeout_sec: int | None = None,
        tf: str = "1d",
        heartbeat_file: Path | str | None = None,
        external_heartbeat: bool = False,
        retry_not_before_reader: Callable[[], float] | None = None,
    ) -> None:
        # TF-bazli parametreleri hesapla
        tf_params = _dms_params_for_tf(tf)
        _heartbeat = heartbeat_sec if heartbeat_sec is not None else tf_params["heartbeat_sec"]
        _timeout = timeout_sec if timeout_sec is not None else tf_params["timeout_sec"]
        self._watchdog_interval = tf_params["watchdog_sec"]
        self.tf = tf
        self.exchange = exchange
        self.service_name = service_name
        self._path = Path(db_path) if db_path else DEFAULT_DB
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self.heartbeat_sec = _heartbeat
        self.timeout_sec = _timeout
        # ``True`` olduğunda watchdog yalnız ana daemon loop'unun explicit
        # ``ping`` çağrılarını kabul eder. Böylece yardımcı heartbeat thread'i
        # ana-loop deadlock'unu taze heartbeat ile maskelemez ve her 20 saniyede
        # account/positions REST polling yapmaz. Exchange handle yalnız gerçek
        # stale durumda emergency-flatten için saklanır.
        self.external_heartbeat = bool(external_heartbeat)
        # Optional shared-rate-limit deadline (Unix seconds). Emergency
        # flatten must not spend its finite retry budget on requests that the
        # local HTTP guard will reject before network I/O.
        self._retry_not_before_reader = retry_not_before_reader
        self._last_deferred_deadline = 0.0
        self._cooldown_reader_error_reported = False
        self._stop = threading.Event()
        self._heartbeat_thread: threading.Thread | None = None
        self._watchdog_thread: threading.Thread | None = None
        self._last_heartbeat_ts: float = time.time()
        self._flatten_done = False
        self._flatten_attempts = 0

        # Initialize lockless file-based watchdog (primary) + DB fallback
        self._watchdog = HeartbeatWatchdog(
            service_name=service_name,
            heartbeat_file=heartbeat_file,
        )
        # Initialize heartbeat file (so file exists before threads start)
        self._watchdog.ping()

        self._init_db()

    def _init_db(self) -> None:
        con = duckdb.connect(str(self._path))
        try:
            con.execute("""
                CREATE TABLE IF NOT EXISTS heartbeat_log (
                    hb_id VARCHAR PRIMARY KEY,
                    service VARCHAR,
                    ts TIMESTAMP,
                    equity_usdt DOUBLE,
                    n_open_positions INTEGER,
                    status VARCHAR
                )
            """)
            con.commit()
        finally:
            con.close()

    # ----- public API -----

    def start(self) -> None:
        """Heartbeat ve watchdog thread'lerini başlat."""
        if self._watchdog_thread is not None:
            return
        if not self.external_heartbeat:
            self._heartbeat_thread = threading.Thread(
                target=self._heartbeat_loop,
                name=f"dms-hb-{self.service_name}",
                daemon=True,
            )
        self._watchdog_thread = threading.Thread(
            target=self._watchdog_loop, name=f"dms-wd-{self.service_name}", daemon=True
        )
        if self._heartbeat_thread is not None:
            self._heartbeat_thread.start()
        self._watchdog_thread.start()
        self._log(
            f"DEAD_MANS_SWITCH started: service={self.service_name} "
            f"tf={self.tf} heartbeat={self.heartbeat_sec}s "
            f"source={'external_main_loop' if self.external_heartbeat else 'internal_thread'} "
            f"timeout={self.timeout_sec}s watchdog={self._watchdog_interval}s"
        )

    def stop(self) -> None:
        """Düzgün durdur — kill_switch'e dokunma."""
        self._stop.set()
        # Clean up file watchdog
        self._watchdog.reset_heartbeat_file()
        self._write_heartbeat(status="stopping")

    def ping(self, equity_usdt: float = 0.0, n_open_positions: int = 0) -> None:
        """Manuel heartbeat ping (opsiyonel — thread zaten otomatik yapar)."""
        self._last_heartbeat_ts = time.time()
        # Primary: write to lockless file watchdog
        self._watchdog.ping()
        # Fallback: also write to DB (for backward compat + audit trail)
        self._write_heartbeat(equity_usdt=equity_usdt, n_open_positions=n_open_positions)

    @property
    def is_triggered(self) -> bool:
        """
        Dead man's switch tetiklendi mi?

        Primary check: file mtime (lockless). If file check fails, fall back
        to in-memory timestamp (for backward compat).
        """
        # Primary: check file mtime (no lock risk)
        if self._watchdog.is_stale(self.timeout_sec):
            return True
        # Fallback: in-memory timestamp (shouldn't reach here unless file_watchdog broken)
        return time.time() - self._last_heartbeat_ts > self.timeout_sec

    @property
    def seconds_since_heartbeat(self) -> float:
        """
        Seconds elapsed since last heartbeat (from file mtime, primary).

        Falls back to in-memory timestamp if file doesn't exist yet.
        """
        file_elapsed = self._watchdog.seconds_since_heartbeat()
        if file_elapsed == float("inf"):
            # File not written yet, use in-memory timestamp
            return time.time() - self._last_heartbeat_ts
        return file_elapsed

    # ----- internal threads -----

    def _heartbeat_loop(self) -> None:
        while not self._stop.is_set():
            try:
                self._last_heartbeat_ts = time.time()
                equity = 0.0
                n_pos = 0
                if self.exchange is not None:
                    try:
                        state = self._fetch_state()
                        equity = state.get("equity", 0.0)
                        n_pos = state.get("n_positions", 0)
                    except Exception as e:
                        # log-only: fallback equity=0/n_pos=0 aynen geçerli, akış değişmez
                        self._log(f"DMS_STATE_FETCH_FAIL: {e}")

                # Primary: write to lockless file watchdog (no DB lock risk)
                file_ok = self._watchdog.ping()
                if not file_ok:
                    self._log("HEARTBEAT_FILE_WRITE_FAILED: watchdog.ping() error")

                # Fallback: also write to DB (backward compat + audit trail)
                # DB write errors are silently ignored (don't block heartbeat)
                self._write_heartbeat(equity_usdt=equity, n_open_positions=n_pos)
            except Exception as e:
                self._log(f"HEARTBEAT_ERROR: {e}")
            self._stop.wait(self.heartbeat_sec)

    def _watchdog_check(self) -> None:
        """Tek watchdog tick kararı (test edilebilir; loop bunu çağırır).

        FIX 2026-07-08 (W1-HIGH, dalga-3): flatten TEK-ATIŞ değil. Eskiden
        _flatten_done koşulsuz True yapılırdı — ilk deneme kısmen/komple
        başarısızsa (ağ, -2022) pozisyonlar açık kalır ve bir daha ASLA
        denenmezdi. Artık yalnız doğrulanmış başarıda done; başarısızlıkta
        FLATTEN_MAX_ATTEMPTS'e kadar sonraki tick'lerde retry.
        """
        elapsed = self.seconds_since_heartbeat
        if elapsed > self.timeout_sec and not self._flatten_done:
            if self._flatten_blocked_by_cooldown():
                return
            self._log(
                f"DEAD_MANS_SWITCH TRIGGERED [{self.tf}]: heartbeat {elapsed:.0f}s ago "
                f"(timeout={self.timeout_sec}s, attempt="
                f"{self._flatten_attempts + 1}/{FLATTEN_MAX_ATTEMPTS})"
            )
            ok = self._emergency_flatten()
            # A 418 may have established the shared cooldown during this
            # attempt. Such an attempt could not complete and must not consume
            # one of the three finite emergency retries.
            if not ok and self._flatten_blocked_by_cooldown():
                return
            self._flatten_attempts += 1
            if ok:
                self._flatten_done = True
            elif self._flatten_attempts >= FLATTEN_MAX_ATTEMPTS:
                self._flatten_done = True
                self._log(
                    f"FLATTEN_GIVEUP [CRIT]: {FLATTEN_MAX_ATTEMPTS} deneme sonrası "
                    f"pozisyonlar hâlâ doğrulanamadı — HUMAN REQUIRED"
                )
                self._send_alarm(
                    "DEAD_MANS_SWITCH CRIT: flatten "
                    f"{FLATTEN_MAX_ATTEMPTS} denemede DOĞRULANAMADI — manuel kontrol ŞART"
                )

    def _flatten_blocked_by_cooldown(self) -> bool:
        """Defer emergency I/O while the shared private-REST gate is closed.

        ``retry_not_before_reader`` returns a Unix epoch deadline. A reader
        failure or invalid value is itself fail-closed: the HTTP guard cannot
        be proven open, so no retry is burned and a single critical alarm is
        emitted for operator repair.
        """
        if self._retry_not_before_reader is None:
            return False
        try:
            deadline = float(self._retry_not_before_reader())
            if not math.isfinite(deadline) or deadline < 0:
                raise ValueError(f"invalid retry deadline: {deadline!r}")
        except Exception as exc:
            if not self._cooldown_reader_error_reported:
                self._cooldown_reader_error_reported = True
                self._log(
                    "FLATTEN_COOLDOWN_STATE_ERROR [CRIT]: private REST gate "
                    f"okunamadı; retry hakkı korunuyor: {type(exc).__name__}: "
                    f"{str(exc)[:120]}"
                )
                self._send_alarm(
                    "DEAD_MANS_SWITCH CRIT: private REST cooldown state "
                    "okunamadı; flatten retry ertelendi — HUMAN REQUIRED"
                )
            return True

        self._cooldown_reader_error_reported = False
        now = time.time()
        if deadline <= now:
            self._last_deferred_deadline = 0.0
            return False
        if not math.isclose(deadline, self._last_deferred_deadline, abs_tol=0.001):
            self._last_deferred_deadline = deadline
            try:
                retry_at = datetime.fromtimestamp(deadline, UTC).isoformat()
            except (OverflowError, OSError, ValueError):
                retry_at = f"unix:{deadline:.3f}"
            self._log(
                "FLATTEN_DEFER_COOLDOWN: private REST gate aktif; "
                f"retry_at={retry_at} "
                f"remaining={deadline - now:.1f}s; attempts={self._flatten_attempts}/"
                f"{FLATTEN_MAX_ATTEMPTS} (hak tüketilmedi)"
            )
        return True

    def _watchdog_loop(self) -> None:
        while not self._stop.is_set():
            self._watchdog_check()
            self._stop.wait(self._watchdog_interval)

    # ----- core actions -----

    def _emergency_flatten(self) -> bool:
        """Tüm pozisyonları market ile kapat + algo emirleri iptal.

        Döner: True = borsa doğrulamasıyla FLAT (veya exchange yok);
        False = en az bir pozisyon açık kalmış olabilir → watchdog retry eder.

        FIX 2026-07-08 (W1-HIGH, dalga-3): reduceOnly market reddi (testnet
        -2022 "ReduceOnly rejected" sınıfı) artık pozisyonu çıplak bırakmaz —
        TAZE qty ile reduceOnly'siz plain-market'e düşülür (watchdog
        naked-defense'teki 2026-06-04 AVAX reçetesinin kopyası).
        """
        self._log("EMERGENCY_FLATTEN: başlıyor...")
        all_flat = True

        if self.exchange is not None:
            # 1) Pozisyonları kapat
            try:
                positions = self.exchange.fetch_positions()
                active = [p for p in positions if abs(float(p.get("contracts", 0) or 0)) > 0.0001]
                for pos in active:
                    sym = pos.get("symbol", "")
                    contracts = abs(float(pos.get("contracts", 0)))
                    side_raw = pos.get("side", "long")
                    close_side = "sell" if side_raw == "long" else "buy"
                    try:
                        self.exchange.create_market_order(
                            symbol=sym,
                            side=close_side,
                            amount=contracts,
                            params={"reduceOnly": True},
                        )
                        self._log(f"FLATTEN_OK: {sym} {close_side} {contracts}")
                    except Exception as e:
                        # reduceOnly reddedildi (-2022 vb.) → TAZE qty ile
                        # plain-market fallback (stale qty ters pozisyon açmasın)
                        try:
                            fresh_amt = 0.0
                            for fp in self.exchange.fetch_positions():
                                if fp.get("symbol") == sym:
                                    fresh_amt = abs(float(fp.get("contracts", 0) or 0))
                                    break
                            if fresh_amt > 0.0001:
                                self.exchange.create_market_order(
                                    symbol=sym,
                                    side=close_side,
                                    amount=fresh_amt,
                                )
                                self._log(
                                    f"FLATTEN_FALLBACK_OK: {sym} reduceOnly reddedildi "
                                    f"({str(e)[:60]}) → plain-market {close_side} {fresh_amt}"
                                )
                            else:
                                self._log(
                                    f"FLATTEN_SKIP: {sym} zaten kapanmış "
                                    f"(reduceOnly reddi: {str(e)[:60]})"
                                )
                        except Exception as e2:
                            all_flat = False
                            self._log(f"FLATTEN_FAIL: {sym} reduceOnly={e} fallback={e2}")
            except Exception as e:
                all_flat = False
                self._log(f"FLATTEN_FETCH_POS_ERROR: {e}")

            # 2) Algo emirleri iptal
            try:
                algo_response = self.exchange.fapiPrivateGetOpenAlgoOrders()
                algo_orders = (
                    algo_response.get("orders")
                    if isinstance(algo_response, dict)
                    else algo_response
                )
                if not isinstance(algo_orders, list):
                    raise TypeError(
                        "open algo orders response must be a list or {orders: list}"
                    )
                for o in algo_orders:
                    try:
                        sym = o.get("symbol", "")
                        algo_id = o.get("algoId") or o.get("algo_id")
                        if sym and algo_id:
                            self.exchange.fapiPrivateDeleteAlgoOrder(
                                {"symbol": sym, "algoId": algo_id}
                            )
                            self._log(f"ALGO_CANCEL: {sym} algoId={algo_id}")
                    except Exception as e:
                        all_flat = False
                        self._log(f"ALGO_CANCEL_FAIL: {e}")
            except Exception as e:
                all_flat = False
                self._log(f"ALGO_CANCEL_FETCH_ERROR: {e}")

            # 3) Borsa doğrulaması: gerçekten flat mıyız? (retry kararının kanıtı)
            try:
                remaining = [
                    p
                    for p in self.exchange.fetch_positions()
                    if abs(float(p.get("contracts", 0) or 0)) > 0.0001
                ]
                if remaining:
                    all_flat = False
                    self._log(
                        f"FLATTEN_VERIFY: {len(remaining)} pozisyon HÂLÂ açık: "
                        f"{[p.get('symbol', '?') for p in remaining]}"
                    )
            except Exception as e:
                all_flat = False  # doğrulanamıyor → başarı SAYMA (retry)
                self._log(f"FLATTEN_VERIFY_ERROR: {e}")

        # 4) Kill switch dosyasına yaz
        self._write_kill_switch()

        # 5) Telegram alarm
        _durum = "tamamlandı (borsa flat)" if all_flat else "EKSİK — retry edilecek"
        self._send_alarm(f"DEAD_MANS_SWITCH: emergency flatten {_durum} — HUMAN REQUIRED")

        self._log(f"EMERGENCY_FLATTEN: {_durum}")
        return all_flat

    def _fetch_state(self) -> dict:
        """Exchange'den kısa hesap özeti."""
        try:
            raw = self.exchange.fapiPrivateV2GetAccount()
            wallet = float(raw.get("totalWalletBalance", 0))
            positions = self.exchange.fetch_positions()
            active = [p for p in positions if abs(float(p.get("contracts", 0) or 0)) > 0.0001]
            return {"equity": wallet, "n_positions": len(active)}
        except Exception:
            return {}

    def _write_heartbeat(
        self,
        equity_usdt: float = 0.0,
        n_open_positions: int = 0,
        status: str = "alive",
    ) -> None:
        try:
            con = duckdb.connect(str(self._path))
            con.execute(
                """INSERT INTO heartbeat_log VALUES (?, ?, ?, ?, ?, ?)""",
                [
                    uuid.uuid4().hex[:16],
                    self.service_name,
                    datetime.now(UTC),
                    equity_usdt,
                    n_open_positions,
                    status,
                ],
            )
            con.commit()
        except Exception as e:
            # log-only: heartbeat-state DB persist best-effort, akış değişmez
            self._log(f"DMS_STATE_DB_PERSIST_FAIL: {e}")
        finally:
            with contextlib.suppress(Exception):
                con.close()

    def _write_kill_switch(self) -> None:
        KILL_SWITCH_PATH.parent.mkdir(parents=True, exist_ok=True)
        try:
            payload = {
                "halted": True,
                "reason": "dead_mans_switch",
                "service": self.service_name,
                "triggered_at": datetime.now(UTC).isoformat(),
            }
            with open(KILL_SWITCH_PATH, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2)
        except Exception as e:
            self._log(f"KILL_SWITCH_WRITE_ERROR: {e}")

    def _send_alarm(self, msg: str) -> None:
        """Telegram alarm (fail-safe — hata olsa da flatten tamamlanmış olacak)."""
        try:
            from price_action.ops import get_telegram_throttle

            throttle = get_telegram_throttle()
            throttle.send_throttled(
                "dms_emergency_flatten",
                msg,
                level="CRITICAL",
            )
        except Exception as e:
            # log-only: flatten zaten yürütüldü; bu yalnız alarm-teslim hatasını yüzeye çıkarır
            self._log(f"DMS_FLATTEN_ALERT_FAIL: {e}")

    def _log(self, msg: str) -> None:
        ts = datetime.now(UTC).strftime("%H:%M:%S")
        line = f"[{ts}][DMS:{self.service_name}] {msg}"
        with contextlib.suppress(Exception):
            print(line, file=sys.stderr)
        # Log dosyasına da yaz
        try:
            log_file = _RUNTIME_PATHS.logs / f"{self.service_name}_dms.log"
            log_file.parent.mkdir(parents=True, exist_ok=True)
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except Exception:
            pass
