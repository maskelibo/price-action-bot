"""Telegram throttle (port from src/price_action/ops/telegram_throttle.py).

Thread-safe singleton. Max 1 alert per alert_type per cooldown_sec.
Excess alerts → digest buffer, flushed periodically.

Levels: INFO / WARN / CRITICAL (CRITICAL bypasses cooldown but has its own ttl).
"""
from __future__ import annotations

import logging
import threading
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional

logger = logging.getLogger(__name__)


class TelegramThrottle:
    _instance: Optional["TelegramThrottle"] = None
    _lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._init_done = False
            return cls._instance

    def __init__(self, send_fn: Optional[Callable[[str], None]] = None,
                 cooldown_sec: int = 300, critical_cooldown_sec: int = 60,
                 digest_flush_sec: int = 1800):
        if getattr(self, "_init_done", False):
            return
        self.send_fn = send_fn or (lambda msg: logger.info("[TELEGRAM] %s", msg))
        self.cooldown_sec = cooldown_sec
        self.critical_cooldown_sec = critical_cooldown_sec
        self.digest_flush_sec = digest_flush_sec
        self._last_sent: dict[str, float] = {}
        self._digest: dict[str, deque] = defaultdict(lambda: deque(maxlen=50))
        self._last_digest_flush = time.monotonic()
        self._send_lock = threading.Lock()
        self._init_done = True

    def send_throttled(self, alert_type: str, message: str, level: str = "INFO") -> bool:
        """Returns True if sent now, False if throttled (added to digest)."""
        with self._send_lock:
            now = time.monotonic()
            cd = self.critical_cooldown_sec if level == "CRITICAL" else self.cooldown_sec
            last = self._last_sent.get(alert_type, 0.0)
            if (now - last) < cd:
                self._digest[alert_type].append((datetime.now(timezone.utc).isoformat(), level, message))
                self._maybe_flush_digest(now)
                return False
            prefix = "[CRITICAL] " if level == "CRITICAL" else "[WARN] " if level == "WARN" else ""
            try:
                self.send_fn(f"{prefix}{message}")
            except Exception as e:
                logger.exception("send_fn failed: %s", e)
                return False
            self._last_sent[alert_type] = now
            return True

    def _maybe_flush_digest(self, now: float) -> None:
        if now - self._last_digest_flush < self.digest_flush_sec:
            return
        for alert_type, items in list(self._digest.items()):
            if not items:
                continue
            n = len(items)
            self._digest[alert_type].clear()
            try:
                self.send_fn(f"[DIGEST] {alert_type}: {n} suppressed alerts in last {self.digest_flush_sec}s")
            except Exception:
                pass
        self._last_digest_flush = now

    def reset(self) -> None:
        """For testing only."""
        with self._send_lock:
            self._last_sent.clear()
            self._digest.clear()


def get_throttle() -> TelegramThrottle:
    return TelegramThrottle()
