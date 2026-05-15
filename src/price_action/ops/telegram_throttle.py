"""TelegramThrottle — Alarm yağmuru önleyici throttle engine.

Tasarım:
  - Max 1 alarm / alert_type / 5min window (yapılandırılabilir)
  - Window içi fazlalık buffer'lanır
  - 1 saatte 1 kez flush_digest() çağrılır — buffered alarmları özet halinde gönder
  - Thread-safe, no-op if Telegram down

Public API:
  send_throttled(alert_type, message, level="INFO")
    — Throttle kuralına göre Telegram'a gönder veya buffer'la
  flush_digest()
    — Buffered alarmları digest olarak gönder (cron'dan çağrılmalı)
  is_telegram_ready()
    — Telegram config OK mi? (test için)

Usage (integration):
  from price_action.ops import get_telegram_throttle
  throttle = get_telegram_throttle()
  throttle.send_throttled("slippage_warning", "Slip %15 hit", level="WARNING")
"""
from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import Any

from price_action.logging_config import logger
from price_action.notifications.telegram import send_critical, send_telegram


class TelegramThrottle:
    """Alarm throttle engine — 5min/type single send, excess buffered."""

    def __init__(self, window_seconds: int = 300) -> None:
        """Init throttler.

        Parameters
        ----------
        window_seconds:
            Max 1 send per window per alert_type. Default 300s (5 min).
        """
        self.window_seconds = window_seconds
        self.last_sent: dict[str, datetime] = {}
        self.digest_buffer: dict[str, list[str]] = {}
        self._lock = threading.Lock()
        self._log = logger.bind(component="telegram_throttle")

    def send_throttled(
        self,
        alert_type: str,
        message: str,
        level: str = "INFO",
    ) -> bool:
        """Send or buffer Telegram message based on throttle window.

        Parameters
        ----------
        alert_type:
            Unique key for throttling (e.g. "slippage_warning", "dms_emergency").
        message:
            Message text (can include newlines).
        level:
            "INFO" | "WARNING" | "WARN" | "ERROR" | "CRIT" | "CRITICAL".
            Levels INFO/WARNING/WARN → normal send_telegram().
            Level CRITICAL → send_critical() (🚨 immediate).

        Returns
        -------
        bool
            True if message was sent immediately.
            False if buffered or no-op (Telegram down).
        """
        now = datetime.now(timezone.utc)

        with self._lock:
            last = self.last_sent.get(alert_type)

            # Check if within window
            within_window = (
                last is not None
                and (now - last).total_seconds() < self.window_seconds
            )

            if within_window:
                # Buffer the message
                self.digest_buffer.setdefault(alert_type, []).append(message)
                self._log.bind(
                    alert_type=alert_type,
                    buffered_count=len(self.digest_buffer[alert_type]),
                ).debug("telegram_throttle.buffered")
                return False

            # Outside window OR first send — send immediately
            self.last_sent[alert_type] = now
            # Clear buffered messages for this type if any
            if alert_type in self.digest_buffer:
                del self.digest_buffer[alert_type]

        # Send outside lock to avoid blocking
        sent = self._send_impl(message, level)
        if sent:
            self._log.bind(alert_type=alert_type, level=level).info(
                "telegram_throttle.sent"
            )
        return sent

    def flush_digest(self) -> int:
        """Send buffered alarms as digests, once per hour (call from cron).

        Returns
        -------
        int
            Number of digest messages sent.
        """
        with self._lock:
            # Snapshot buffer and clear
            buffer_snapshot = dict(self.digest_buffer)
            self.digest_buffer.clear()

        sent_count = 0
        for alert_type, messages in buffer_snapshot.items():
            if not messages:
                continue

            # Build digest
            digest_lines = [
                f"📊 {alert_type} digest ({len(messages)} alert{'s' if len(messages) != 1 else ''} in last hour):",
                "",
            ]
            # Show top 10, summarize rest
            for i, msg in enumerate(messages[:10]):
                digest_lines.append(f"  {i+1}. {msg[:100]}")
            if len(messages) > 10:
                digest_lines.append(f"  ... +{len(messages) - 10} more")

            digest_text = "\n".join(digest_lines)
            if self._send_impl(digest_text, level="INFO"):
                sent_count += 1
                self._log.bind(
                    alert_type=alert_type,
                    message_count=len(messages),
                ).info("telegram_throttle.digest_sent")
            else:
                self._log.bind(alert_type=alert_type).warning(
                    "telegram_throttle.digest_failed"
                )

        return sent_count

    def is_telegram_ready(self) -> bool:
        """Check if Telegram config is available (for tests/healthcheck)."""
        import os

        token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
        chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
        return bool(token and chat_id)

    # ----- internal -----

    def _send_impl(self, message: str, level: str) -> bool:
        """Delegate to telegram module, fail-safe."""
        try:
            level_upper = (level or "INFO").upper()
            if level_upper in ("CRIT", "CRITICAL"):
                return send_critical(message)
            else:
                return send_telegram(message, level=level)
        except Exception as exc:
            self._log.bind(err=str(exc)[:200]).warning("telegram_throttle.send_failed")
            return False


# ----- Singleton Provider -----

_global_throttle: TelegramThrottle | None = None
_throttle_lock = threading.Lock()


def get_telegram_throttle(window_seconds: int = 300) -> TelegramThrottle:
    """Get or create global TelegramThrottle singleton.

    Parameters
    ----------
    window_seconds:
        Throttle window (only used on first call; subsequent calls return
        existing instance).

    Returns
    -------
    TelegramThrottle
        Singleton instance.
    """
    global _global_throttle
    if _global_throttle is None:
        with _throttle_lock:
            if _global_throttle is None:
                _global_throttle = TelegramThrottle(window_seconds=window_seconds)
    return _global_throttle


def reset_telegram_throttle() -> None:
    """Reset singleton (test use only)."""
    global _global_throttle
    with _throttle_lock:
        _global_throttle = None
