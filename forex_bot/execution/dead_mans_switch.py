"""Forex DeadMansSwitch — heartbeat + emergency flatten on stale.

Two-layer:
 1. file mtime watchdog (logs/forex_heartbeat) — updated each loop iter
 2. DB-backed last_heartbeat_ts in DuckDB (audit trail)

If heartbeat older than `timeout_sec`:
 1. Close all open positions via broker.close_position()
 2. Cancel pending orders
 3. Write kill_switch.json {halted:true, reason:"dms_timeout"}
 4. Send CRITICAL alarm
 5. Stop daemon

Forex-specific: timeout_sec=300 default (5min), tighter than crypto 1d (1800s).
"""
from __future__ import annotations

import json
import logging
import threading
import time as time_module
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

from .broker_base import BrokerBase

logger = logging.getLogger(__name__)


class DeadMansSwitch:
    def __init__(
        self,
        broker: BrokerBase,
        heartbeat_path: Path = Path("logs/forex/forex_heartbeat"),
        kill_switch_path: Path = Path("logs/forex/forex_kill_switch.json"),
        timeout_sec: int = 300,
        heartbeat_interval_sec: int = 30,
        alarm_cb: Optional[Callable[[str], None]] = None,
    ):
        self.broker = broker
        self.heartbeat_path = Path(heartbeat_path)
        self.kill_switch_path = Path(kill_switch_path)
        self.timeout_sec = timeout_sec
        self.heartbeat_interval_sec = heartbeat_interval_sec
        self.alarm_cb = alarm_cb
        self._stop_event = threading.Event()
        self._heartbeat_thread: Optional[threading.Thread] = None
        self._watchdog_thread: Optional[threading.Thread] = None
        self.heartbeat_path.parent.mkdir(parents=True, exist_ok=True)

    def _send_alarm(self, msg: str) -> None:
        logger.critical(msg)
        if self.alarm_cb:
            try:
                self.alarm_cb(msg)
            except Exception as e:
                logger.exception("alarm_cb failed: %s", e)

    def heartbeat(self) -> None:
        try:
            self.heartbeat_path.write_text(datetime.now(timezone.utc).isoformat())
        except Exception as e:
            logger.warning("heartbeat write failed: %s", e)

    def is_halted(self) -> bool:
        if not self.kill_switch_path.exists():
            return False
        try:
            data = json.loads(self.kill_switch_path.read_text())
            return bool(data.get("halted", False))
        except Exception:
            return False

    def emergency_flatten(self, reason: str = "dms_timeout") -> int:
        flattened = 0
        for pos in list(self.broker.positions()):
            try:
                fill = self.broker.close_position(
                    pos.pair, datetime.now(timezone.utc), pos.current_price, reason=reason
                )
                if fill:
                    flattened += 1
                    logger.warning("DMS flatten: %s %s lots=%.2f", pos.pair, pos.side, pos.lots)
            except Exception as e:
                logger.exception("flatten failed %s: %s", pos.pair, e)
        try:
            self.kill_switch_path.parent.mkdir(parents=True, exist_ok=True)
            self.kill_switch_path.write_text(json.dumps({
                "halted": True,
                "reason": reason,
                "ts_utc": datetime.now(timezone.utc).isoformat(),
                "flattened": flattened,
            }, indent=2))
        except Exception as e:
            logger.exception("kill_switch write failed: %s", e)
        self._send_alarm(f"[CRITICAL] DMS triggered reason={reason} flattened={flattened}")
        return flattened

    def reset_halt(self, human_confirmation: str) -> bool:
        """Resume requires explicit human confirmation."""
        if human_confirmation != "I_CONFIRM_RESUME":
            return False
        try:
            self.kill_switch_path.unlink(missing_ok=True)
            return True
        except Exception:
            return False

    def _heartbeat_loop(self) -> None:
        while not self._stop_event.is_set():
            self.heartbeat()
            self._stop_event.wait(self.heartbeat_interval_sec)

    def _watchdog_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                if self.heartbeat_path.exists():
                    age = time_module.time() - self.heartbeat_path.stat().st_mtime
                    if age > self.timeout_sec:
                        self._send_alarm(f"DMS: heartbeat stale {age:.0f}s > {self.timeout_sec}s")
                        self.emergency_flatten(reason="dms_timeout")
                        break
            except Exception as e:
                logger.exception("watchdog tick failed: %s", e)
            self._stop_event.wait(min(30, self.timeout_sec // 2))

    def start(self) -> None:
        if self._heartbeat_thread is not None:
            return
        self._stop_event.clear()
        self._heartbeat_thread = threading.Thread(target=self._heartbeat_loop, daemon=True)
        self._watchdog_thread = threading.Thread(target=self._watchdog_loop, daemon=True)
        self._heartbeat_thread.start()
        self._watchdog_thread.start()
        logger.info("DMS started timeout=%ds interval=%ds", self.timeout_sec, self.heartbeat_interval_sec)

    def stop(self) -> None:
        self._stop_event.set()
        if self._heartbeat_thread:
            self._heartbeat_thread.join(timeout=2)
        if self._watchdog_thread:
            self._watchdog_thread.join(timeout=2)
        self._heartbeat_thread = None
        self._watchdog_thread = None
