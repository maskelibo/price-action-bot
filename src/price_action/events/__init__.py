"""Faz 14.27 KRITIK-1 fix: formal event bus.

Önceki bug: Bot Monitor PAUSE alert üretiyor, ama Adversary engineer ve Researcher
otomatik tetiklenmiyordu. Cron-based polling vardı (saatlik hook), ama:
  - Geç tepki (60dk gecikme)
  - Hook her cron'da inbox tarıyor (CPU)
  - Multi-consumer yok

Bu module: publish-subscribe pattern, file-based event log.
  - Producer: Bot Monitor, Drift Detector, Reconciler
  - Consumer: Adversary Engineer, Researcher, Risk Officer
  - Storage: data/events/YYYY-MM-DD.jsonl (append-only)
  - Idempotency: event_id (sha256(producer + topic + body))
  - Subscriber registry: configs/event_subscribers.yaml
"""
from .bus import (
    EventBus,
    EventEnvelope,
    EventTopic,
    publish,
    register_handler,
    replay_recent,
)

__all__ = [
    "EventBus",
    "EventEnvelope",
    "EventTopic",
    "publish",
    "register_handler",
    "replay_recent",
]
