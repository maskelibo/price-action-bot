"""File-based event bus — formal pub-sub.

Topics:
  - bot_monitor.pause_alert     (Bot Monitor: kill criteria breach)
  - bot_monitor.warn            (Bot Monitor: drift warn)
  - drift.regime_change         (BTC capitulation, FNG swing)
  - drift.wr_drop               (Win rate degradation)
  - drift.r_drop                (Avg R degradation)
  - reconciler.phantom          (Exchange-only position)
  - reconciler.qty_drift        (Journal vs exchange mismatch)
  - adversary.stress_fail       (Stress test FAIL)

Consumers register via register_handler(topic, callable). publish() yazar dosyaya,
sonra registered handler'ları senkron çağırır (fire-and-forget hata yutar).
"""
from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Awaitable, Callable

ROOT = Path(__file__).resolve().parents[3]
_EVENTS_DIR = ROOT / "data" / "events"


class EventTopic(str, Enum):
    """Tipli event kanalları."""

    BOT_MONITOR_PAUSE = "bot_monitor.pause_alert"
    BOT_MONITOR_WARN = "bot_monitor.warn"
    DRIFT_REGIME_CHANGE = "drift.regime_change"
    DRIFT_WR_DROP = "drift.wr_drop"
    DRIFT_R_DROP = "drift.r_drop"
    RECONCILER_PHANTOM = "reconciler.phantom"
    RECONCILER_QTY_DRIFT = "reconciler.qty_drift"
    ADVERSARY_STRESS_FAIL = "adversary.stress_fail"


@dataclass
class EventEnvelope:
    """Bir event'in serializable container'ı."""

    event_id: str
    topic: str
    producer: str
    ts: str
    payload: dict[str, Any]
    correlation_id: str | None = None  # zincir tracking (örn doc_id)

    def to_jsonl(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)


# Handler registry — module-level
_HANDLERS: dict[str, list[Callable[[EventEnvelope], Any]]] = {}


def register_handler(topic: EventTopic | str,
                     handler: Callable[[EventEnvelope], Any]) -> None:
    """Bir topic için handler kaydet (sync or async)."""
    topic_str = topic.value if isinstance(topic, EventTopic) else topic
    _HANDLERS.setdefault(topic_str, []).append(handler)


def publish(topic: EventTopic | str,
            producer: str,
            payload: dict[str, Any],
            correlation_id: str | None = None) -> EventEnvelope:
    """Bir event yayınla — diske yaz + handler'ları tetikle."""
    topic_str = topic.value if isinstance(topic, EventTopic) else topic
    body = json.dumps(payload, sort_keys=True, default=str)
    event_id = hashlib.sha256(
        f"{producer}::{topic_str}::{body}".encode("utf-8")
    ).hexdigest()[:16]
    env = EventEnvelope(
        event_id=event_id,
        topic=topic_str,
        producer=producer,
        ts=datetime.now(timezone.utc).isoformat(),
        payload=payload,
        correlation_id=correlation_id,
    )

    # Diske append (atomic-ish: open + write + close)
    _EVENTS_DIR.mkdir(parents=True, exist_ok=True)
    log_path = _EVENTS_DIR / f"{datetime.now(timezone.utc).strftime('%Y-%m-%d')}.jsonl"
    try:
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(env.to_jsonl() + "\n")
    except Exception:
        pass  # Disk fail tolerated, handlers yine tetiklenir

    # Handler'ları tetikle (sync wrapper async sarar)
    for handler in _HANDLERS.get(topic_str, []):
        try:
            result = handler(env)
            if asyncio.iscoroutine(result):
                # Sync context'ten async handler — schedule
                try:
                    loop = asyncio.get_event_loop()
                    if loop.is_running():
                        asyncio.create_task(result)
                    else:
                        loop.run_until_complete(result)
                except RuntimeError:
                    # No event loop → ignore
                    pass
        except Exception:
            pass  # Handler crash diğerlerini durdurmasın

    return env


def replay_recent(topic: EventTopic | str | None = None,
                  hours_back: int = 24) -> list[EventEnvelope]:
    """Son N saat'in event'lerini oku (consumer cron tarafından kullanılır).

    Args:
        topic: Filter (None = tüm topic'ler)
        hours_back: Geriye dönük pencere
    """
    from datetime import timedelta
    if not _EVENTS_DIR.exists():
        return []
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours_back)
    topic_str = topic.value if isinstance(topic, EventTopic) else topic
    results: list[EventEnvelope] = []
    # Bugün + dün dosyalarını oku (24h pencere için yeterli)
    today = datetime.now(timezone.utc)
    for d in (today, today - timedelta(days=1)):
        p = _EVENTS_DIR / f"{d.strftime('%Y-%m-%d')}.jsonl"
        if not p.exists():
            continue
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue
            try:
                ts = datetime.fromisoformat(data["ts"])
            except Exception:
                continue
            if ts < cutoff:
                continue
            if topic_str and data.get("topic") != topic_str:
                continue
            results.append(EventEnvelope(**data))
    return results


class EventBus:
    """OOP wrapper (test'ler için override edilebilir)."""

    def __init__(self) -> None:
        self._handlers: dict[str, list[Callable]] = {}

    def register(self, topic: EventTopic | str, handler: Callable) -> None:
        topic_str = topic.value if isinstance(topic, EventTopic) else topic
        self._handlers.setdefault(topic_str, []).append(handler)

    def emit(self, topic: EventTopic | str, producer: str,
             payload: dict[str, Any]) -> EventEnvelope:
        return publish(topic, producer, payload)
