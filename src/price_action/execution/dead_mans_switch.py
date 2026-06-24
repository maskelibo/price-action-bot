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
    dms = DeadMansSwitch(exchange, service_name="futures_daemon")
    dms.start()
    # ... daemon loop ...
    dms.stop()

Flatten tetiklenince:
  1. Tüm açık pozisyonlar market close
  2. Tüm algo emirler iptal
  3. kill_switch.json yaz {halted: true, reason: "dead_mans_switch"}
  4. Log + Telegram alarm
"""
from __future__ import annotations

import json
import sys
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import duckdb

from price_action.execution.heartbeat_watchdog import HeartbeatWatchdog

ROOT = Path(__file__).resolve().parents[3]  # G24 fix: Price Action kökü (eskiden parents[4]=projeler — proje dışı)
DEFAULT_DB = ROOT / "data" / "idempotency.duckdb"
KILL_SWITCH_PATH = ROOT / "logs" / "kill_switch.json"

HEARTBEAT_INTERVAL_SEC = 60
WATCHDOG_INTERVAL_SEC = 30
DEAD_MAN_TIMEOUT_SEC = 300  # 5 dakika (1d default)

# TF-spesifik heartbeat ve timeout ayarlari (master plan §4.5)
# heartbeat_sec: ne siklıkla DB'ye heartbeat yazilir
# timeout_sec: bu kadar susarsa flatten tetiklenir
TF_DMS_PARAMS: dict[str, dict[str, int]] = {
    "1d":  {"heartbeat_sec": 60,   "timeout_sec": 300,   "watchdog_sec": 30},
    "4h":  {"heartbeat_sec": 60,   "timeout_sec": 300,   "watchdog_sec": 30},
    "1h":  {"heartbeat_sec": 30,   "timeout_sec": 180,   "watchdog_sec": 15},
    "15m": {"heartbeat_sec": 20,   "timeout_sec": 1800,  "watchdog_sec": 10},
    "5m":  {"heartbeat_sec": 10,   "timeout_sec": 600,   "watchdog_sec": 5},
    "1m":  {"heartbeat_sec": 5,    "timeout_sec": 120,   "watchdog_sec": 3},
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
        self._stop = threading.Event()
        self._heartbeat_thread: threading.Thread | None = None
        self._watchdog_thread: threading.Thread | None = None
        self._last_heartbeat_ts: float = time.time()
        self._flatten_done = False

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
        con.close()

    # ----- public API -----

    def start(self) -> None:
        """Heartbeat ve watchdog thread'lerini başlat."""
        if self._heartbeat_thread is not None:
            return
        self._heartbeat_thread = threading.Thread(
            target=self._heartbeat_loop, name=f"dms-hb-{self.service_name}", daemon=True
        )
        self._watchdog_thread = threading.Thread(
            target=self._watchdog_loop, name=f"dms-wd-{self.service_name}", daemon=True
        )
        self._heartbeat_thread.start()
        self._watchdog_thread.start()
        self._log(
            f"DEAD_MANS_SWITCH started: service={self.service_name} "
            f"tf={self.tf} heartbeat={self.heartbeat_sec}s "
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
                    except Exception:
                        pass

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

    def _watchdog_loop(self) -> None:
        while not self._stop.is_set():
            elapsed = self.seconds_since_heartbeat
            if elapsed > self.timeout_sec and not self._flatten_done:
                self._log(
                    f"DEAD_MANS_SWITCH TRIGGERED [{self.tf}]: heartbeat {elapsed:.0f}s ago "
                    f"(timeout={self.timeout_sec}s)"
                )
                self._emergency_flatten()
                self._flatten_done = True
            self._stop.wait(self._watchdog_interval)

    # ----- core actions -----

    def _emergency_flatten(self) -> None:
        """Tüm pozisyonları market ile kapat + algo emirleri iptal."""
        self._log("EMERGENCY_FLATTEN: başlıyor...")

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
                        self._log(f"FLATTEN_FAIL: {sym} {e}")
            except Exception as e:
                self._log(f"FLATTEN_FETCH_POS_ERROR: {e}")

            # 2) Algo emirleri iptal
            try:
                algo_orders = self.exchange.fapiPrivateGetOpenAlgoOrders()
                if isinstance(algo_orders, list):
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
                            self._log(f"ALGO_CANCEL_FAIL: {e}")
            except Exception as e:
                self._log(f"ALGO_CANCEL_FETCH_ERROR: {e}")

        # 3) Kill switch dosyasına yaz
        self._write_kill_switch()

        # 4) Telegram alarm
        self._send_alarm("DEAD_MANS_SWITCH: emergency flatten tamamlandı — HUMAN REQUIRED")

        self._log("EMERGENCY_FLATTEN: tamamlandı")

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
                    datetime.now(timezone.utc),
                    equity_usdt,
                    n_open_positions,
                    status,
                ],
            )
            con.commit()
            con.close()
        except Exception:
            pass

    def _write_kill_switch(self) -> None:
        KILL_SWITCH_PATH.parent.mkdir(parents=True, exist_ok=True)
        try:
            payload = {
                "halted": True,
                "reason": "dead_mans_switch",
                "service": self.service_name,
                "triggered_at": datetime.now(timezone.utc).isoformat(),
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
        except Exception:
            pass

    def _log(self, msg: str) -> None:
        ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
        line = f"[{ts}][DMS:{self.service_name}] {msg}"
        try:
            print(line, file=sys.stderr)
        except Exception:
            pass
        # Log dosyasına da yaz
        try:
            log_file = ROOT / "logs" / f"{self.service_name}_dms.log"
            log_file.parent.mkdir(parents=True, exist_ok=True)
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except Exception:
            pass
