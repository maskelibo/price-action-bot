"""TelegramThrottle — Alarm yağmuru önleyici throttle engine.

Tasarım:
  - Max 1 alarm / alert_type / TF-adaptive window
  - Timeframe-specific windows (tighter for fast TFs):
      * 1d: 3600s (1 hour) — avoid SL spam in volatile days
      * 1h: 1800s (30 min)
      * 15m: 600s (10 min) — DEFAULT, scalp-friendly
      * 5m: 300s (5 min)
      * 1m: 180s (3 min)
  - Window içi fazlalık buffer'lanır
  - 1 saatte 1 kez flush_digest() çağrılır — buffered alarmları özet halinde gönder
  - Thread-safe, no-op if Telegram down
  - BACKWARD COMPAT: PA_TELEGRAM_THROTTLE_TF env var (default='15m' → 600s)

Public API:
  send_throttled(alert_type, message, level="INFO")
    — Throttle kuralına göre Telegram'a gönder veya buffer'la (default TF window)
  flush_digest()
    — Buffered alarmları digest olarak gönder (cron'dan çağrılmalı)
  is_telegram_ready()
    — Telegram config OK mi? (test için)

Usage (integration):
  from price_action.ops import get_telegram_throttle
  throttle = get_telegram_throttle()  # PA_TELEGRAM_THROTTLE_TF env var okur
  throttle.send_throttled("slippage_warning", "Slip %15 hit", level="WARNING")
"""

from __future__ import annotations

import os
import threading
from datetime import UTC, datetime
from typing import ClassVar

from price_action.logging_config import logger
from price_action.notifications.telegram import send_critical, send_telegram


class TelegramThrottle:
    """Alarm throttle engine — TF-adaptive window, excess buffered."""

    # UNMUTE 2026-05-30 (Ops): mute list emptied after root causes resolved.
    # The 2026-05-28 mutes (dms_stale_, regime_cache_stale_warn) were a band-aid
    # for the market.duckdb freeze + daily-only regime refresh. Post-deploy
    # (regime 4h cadence + store decouple + fresh DMS heartbeat) those conditions
    # no longer fire: freshness_watchdog went GREEN 2026-05-29 20:12Z, DMS
    # heartbeat updates every second. Leaving them muted would silently swallow
    # a future genuine recurrence (daemon crash, RAG empty). Infra kept intact —
    # re-add a prefix here to mute again. PA_TELEGRAM_UNMUTE=1 still forces send.
    _MUTED_ALERT_PREFIXES: tuple[str, ...] = ()

    # TF → throttle window (seconds)
    TF_WINDOW_MAP: ClassVar[dict[str, int]] = {
        "1d": 3600,  # 1 hour — avoid SL spam on volatile days
        "1h": 1800,  # 30 min
        "15m": 600,  # 10 min — scalp standard (SEC54 ME-02 audit)
        "5m": 300,  # 5 min
        "1m": 180,  # 3 min
    }

    def __init__(self, window_seconds: int | None = None, timeframe: str = "15m") -> None:
        """Init throttler with TF-adaptive window.

        Parameters
        ----------
        window_seconds:
            Override TF-based window (for backward compat, tests).
            If None, compute from timeframe parameter.
        timeframe:
            '1d', '1h', '15m', '5m', '1m'. Default '15m' (600s).
            Ignored if window_seconds is provided.
            Also reads PA_TELEGRAM_THROTTLE_TF env var if available.
        """
        # Read TF from env (allows per-bot override)
        env_tf = os.environ.get("PA_TELEGRAM_THROTTLE_TF", "").strip()
        if env_tf:
            timeframe = env_tf

        # Explicit window_seconds override (backward compat + tests)
        if window_seconds is not None:
            self.window_seconds = window_seconds
            self.timeframe = None  # No TF tracking
        else:
            # TF-based window
            self.timeframe = timeframe
            self.window_seconds = self.TF_WINDOW_MAP.get(timeframe, 600)

        self.last_sent: dict[str, datetime] = {}
        self.digest_buffer: dict[str, list[str]] = {}
        # FIX 2026-07-08 (bildirim paketi, N3): CRIT pencere tabanı — CRIT
        # seviyeli alarm normal pencereye (600-3600s) TAKILMAZ, en fazla bu
        # kadar gecikir. Fırtına koruması korunur (floor içi tekrar → buffer).
        self.crit_floor_seconds = 120
        self._lock = threading.Lock()
        self._log = logger.bind(
            component="telegram_throttle",
            timeframe=self.timeframe,
            window_seconds=self.window_seconds,
        )

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
        # MUTE 2026-05-28 (Ops): paper/research-mode false-positive alarms.
        # These alert_types are non-actionable in paper mode (no live orders to
        # protect, refresh jobs not scheduled) and were flooding Telegram.
        # Trading-protective REJECT/HARD_REJECT alerts (regime_cache_stale_reject)
        # are NOT muted — only the WARN-level staleness notice. Reversible:
        # set PA_TELEGRAM_UNMUTE=1 env var, or delete _MUTED_ALERT_PREFIXES.
        if os.environ.get("PA_TELEGRAM_UNMUTE", "").strip().lower() not in ("1", "true", "yes"):
            for _muted in self._MUTED_ALERT_PREFIXES:
                if alert_type.startswith(_muted):
                    self._log.bind(alert_type=alert_type, level=level).info(
                        "telegram_throttle.muted_paper_fp"
                    )
                    return False

        now = datetime.now(UTC)

        with self._lock:
            last = self.last_sent.get(alert_type)

            # FIX 2026-07-08 (N3): CRIT pencere tabanı — CRIT normal pencereye
            # takılıp saatlerce buffer'da KAYBOLMAZ.
            eff_window = self._effective_window(level)
            within_window = last is not None and (now - last).total_seconds() < eff_window

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
            # FIX 2026-07-08 (N2): buffer SİLİNMEZ, drain edilir — pencere içinde
            # buffer'lananlar giden mesaja mini-digest olarak eklenir (eski kod
            # burada del ile GÖNDERMEDEN imha ediyordu; flush_digest cron'u da
            # olmadığından her buffer'lanan alarm kanıtsız ölüyordu).
            _pending = self.digest_buffer.pop(alert_type, [])

        if _pending:
            message = message + self._drain_suffix(_pending)

        # Send outside lock to avoid blocking
        sent = self._send_impl(message, level)
        if sent:
            self._log.bind(alert_type=alert_type, level=level).info("telegram_throttle.sent")
        return sent

    def _effective_window(self, level: str) -> float:
        """Level'e göre etkin pencere: CRIT → min(pencere, crit_floor)."""
        if (level or "INFO").upper() in ("CRIT", "CRITICAL"):
            return min(self.window_seconds, self.crit_floor_seconds)
        return self.window_seconds

    @staticmethod
    def _drain_suffix(pending: list[str]) -> str:
        """Buffer'lanan mesajları giden mesaja eklenecek mini-digest'e çevir."""
        lines = [f"\n\n📦 pencere içinde {len(pending)} alarm buffer'lanmıştı:"]
        for m in pending[:3]:
            lines.append(f"  • {m[:80]}")
        if len(pending) > 3:
            lines.append(f"  … +{len(pending) - 3} daha")
        return "\n".join(lines)

    def send_report(self, alert_type: str, chunks: list[str], level: str = "INFO") -> bool:
        """Çok parçalı raporu TEK throttle kararıyla gönder.

        FIX 2026-07-08 (N1, DERIN_DENETIM W6-HIGH): push_report her chunk'ı
        aynı alert_type ile send_throttled'a sokuyordu → 1. chunk pencereyi
        başlatır, 2+ chunk buffer'a düşer ve (N2 bug'ıyla) imha edilirdi —
        Daily Truth Report dahil tüm çok parçalı raporların gövdesi kayboluyordu.
        Karar rapor-bazlı: izin varsa TÜM parçalar gider, yoksa hiçbiri
        (özet buffer'a düşer, sonraki gönderimde drain edilir).

        Returns: en az bir parça gönderildiyse True.
        """
        if not chunks:
            return False
        now = datetime.now(UTC)
        with self._lock:
            last = self.last_sent.get(alert_type)
            eff_window = self._effective_window(level)
            if last is not None and (now - last).total_seconds() < eff_window:
                self.digest_buffer.setdefault(alert_type, []).append(
                    f"[{len(chunks)} parçalı rapor throttle'landı] {chunks[0][:80]}"
                )
                self._log.bind(alert_type=alert_type, chunks=len(chunks)).info(
                    "telegram_throttle.report_throttled"
                )
                return False
            self.last_sent[alert_type] = now
            _pending = self.digest_buffer.pop(alert_type, [])

        sent_any = False
        for i, chunk in enumerate(chunks):
            if i == 0 and _pending:
                chunk = chunk + self._drain_suffix(_pending)
            sent_any = self._send_impl(chunk, level) or sent_any
        if sent_any:
            self._log.bind(alert_type=alert_type, chunks=len(chunks), level=level).info(
                "telegram_throttle.report_sent"
            )
        return sent_any

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
                self._log.bind(alert_type=alert_type).warning("telegram_throttle.digest_failed")

        return sent_count

    def is_telegram_ready(self) -> bool:
        """Check if Telegram config is available (for tests/healthcheck)."""
        import os

        token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
        chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
        return bool(token and chat_id)

    def send_throttled_with_tf(
        self,
        alert_type: str,
        message: str,
        level: str = "INFO",
        timeframe: str | None = None,
    ) -> bool:
        """Send alert with explicit TF window override.

        Allows per-alert TF specification (e.g., SL alert in 1d vs 15m context).

        Parameters
        ----------
        alert_type:
            Unique key (e.g., 'slippage_high', 'dd_halt').
        message:
            Alert text.
        level:
            "INFO" | "WARNING" | "CRITICAL".
        timeframe:
            '1d', '1h', '15m', '5m', '1m'. If None, uses instance TF window.

        Returns
        -------
        bool
            True if sent immediately, False if buffered.
        """
        # Resolve window: explicit TF > instance TF
        if timeframe and timeframe in self.TF_WINDOW_MAP:
            window_sec = self.TF_WINDOW_MAP[timeframe]
        else:
            window_sec = self.window_seconds

        # Create composite key if TF override
        if timeframe and timeframe != self.timeframe:
            composite_key = f"{timeframe}_{alert_type}"
        else:
            composite_key = alert_type

        now = datetime.now(UTC)

        # FIX 2026-07-08 (N3): CRIT floor burada da geçerli
        if (level or "INFO").upper() in ("CRIT", "CRITICAL"):
            window_sec = min(window_sec, self.crit_floor_seconds)

        with self._lock:
            last = self.last_sent.get(composite_key)
            within_window = last is not None and (now - last).total_seconds() < window_sec

            if within_window:
                # Buffer
                self.digest_buffer.setdefault(composite_key, []).append(message)
                self._log.bind(
                    alert_type=alert_type,
                    timeframe=timeframe,
                    buffered_count=len(self.digest_buffer[composite_key]),
                    window_sec=window_sec,
                ).debug("telegram_throttle_with_tf.buffered")
                return False

            # Send immediately
            self.last_sent[composite_key] = now
            # FIX 2026-07-08 (N2): drain, silme değil
            _pending = self.digest_buffer.pop(composite_key, [])

        if _pending:
            message = message + self._drain_suffix(_pending)

        # Send outside lock
        sent = self._send_impl(message, level)
        if sent:
            self._log.bind(
                alert_type=alert_type,
                timeframe=timeframe,
                level=level,
                window_sec=window_sec,
            ).info("telegram_throttle_with_tf.sent")
        return sent

    def send_throttled_scalp(
        self,
        timeframe: str,
        alert_type: str,
        message: str,
        level: str = "INFO",
    ) -> bool:
        """DEPRECATED: Send scalper alert with TF-scaled throttle window.

        Use send_throttled_with_tf() instead (same logic, better API).

        Timeframe-specific throttle windows (tighter for faster TFs):
          - '15m' → max 1 alert / 600s (10 min)
          - '5m'  → max 1 alert / 300s (5 min)
          - '1m'  → max 1 alert / 180s (3 min)

        Parameters
        ----------
        timeframe:
            '15m', '5m', '1m'
        alert_type:
            Unique key (e.g., 'slippage_high', 'dd_halt').
        message:
            Alert text.
        level:
            "INFO" | "WARNING" | "CRITICAL".

        Returns
        -------
        bool
            True if sent immediately, False if buffered.
        """
        # Delegate to send_throttled_with_tf for unified logic
        return self.send_throttled_with_tf(
            alert_type=alert_type,
            message=message,
            level=level,
            timeframe=timeframe,
        )

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


def get_telegram_throttle(
    window_seconds: int | None = None,
    timeframe: str = "15m",
) -> TelegramThrottle:
    """Get or create global TelegramThrottle singleton.

    Reads PA_TELEGRAM_THROTTLE_TF env var to determine adaptive window.
    For backward compat, explicit window_seconds parameter overrides TF detection.

    Parameters
    ----------
    window_seconds:
        Override TF-based window (only used on first call).
        If None, uses timeframe parameter (or PA_TELEGRAM_THROTTLE_TF env var).
        Default None (TF-adaptive).
    timeframe:
        Default '15m' (600s). Ignored if PA_TELEGRAM_THROTTLE_TF env var set.

    Returns
    -------
    TelegramThrottle
        Singleton instance.
    """
    global _global_throttle
    if _global_throttle is None:
        with _throttle_lock:
            if _global_throttle is None:
                _global_throttle = TelegramThrottle(
                    window_seconds=window_seconds,
                    timeframe=timeframe,
                )
    return _global_throttle


def reset_telegram_throttle() -> None:
    """Reset singleton (test use only)."""
    global _global_throttle
    with _throttle_lock:
        _global_throttle = None
