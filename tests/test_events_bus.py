"""Faz 14.27 KRİTİK-1 test: event bus pub-sub."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


class TestEventBus:
    def test_publish_writes_to_disk(self, tmp_path, monkeypatch):
        """publish() → events/YYYY-MM-DD.jsonl yazıyor."""
        monkeypatch.setattr("price_action.events.bus._EVENTS_DIR", tmp_path)
        from price_action.events import publish, EventTopic

        env = publish(
            topic=EventTopic.BOT_MONITOR_PAUSE,
            producer="test_producer",
            payload={"bot_id": "futures15m", "dd_pct": 0.30},
        )
        assert env.event_id
        assert env.topic == "bot_monitor.pause_alert"

        # Diske yazıldı mı?
        from datetime import datetime, timezone
        log_path = tmp_path / f"{datetime.now(timezone.utc).strftime('%Y-%m-%d')}.jsonl"
        assert log_path.exists()
        content = log_path.read_text()
        assert "bot_monitor.pause_alert" in content
        assert "test_producer" in content

    def test_publish_triggers_handlers(self, tmp_path, monkeypatch):
        """register_handler ile kayıtlı handler tetikleniyor."""
        monkeypatch.setattr("price_action.events.bus._EVENTS_DIR", tmp_path)
        monkeypatch.setattr("price_action.events.bus._HANDLERS", {})
        from price_action.events import publish, register_handler, EventTopic

        captured = []

        def my_handler(env):
            captured.append(env)

        register_handler(EventTopic.DRIFT_WR_DROP, my_handler)
        publish(EventTopic.DRIFT_WR_DROP, "test", {"wr": 0.30})

        assert len(captured) == 1
        assert captured[0].payload["wr"] == 0.30

    def test_replay_recent(self, tmp_path, monkeypatch):
        """replay_recent N saat geri okuyor."""
        monkeypatch.setattr("price_action.events.bus._EVENTS_DIR", tmp_path)
        from price_action.events import publish, replay_recent, EventTopic

        publish(EventTopic.BOT_MONITOR_PAUSE, "p1", {"x": 1})
        publish(EventTopic.DRIFT_WR_DROP, "p2", {"y": 2})
        publish(EventTopic.BOT_MONITOR_PAUSE, "p3", {"z": 3})

        all_events = replay_recent(hours_back=24)
        assert len(all_events) == 3

        only_pause = replay_recent(topic=EventTopic.BOT_MONITOR_PAUSE, hours_back=24)
        assert len(only_pause) == 2

    def test_event_id_deterministic(self, tmp_path, monkeypatch):
        """Aynı producer + topic + payload = aynı event_id (idempotency)."""
        monkeypatch.setattr("price_action.events.bus._EVENTS_DIR", tmp_path)
        monkeypatch.setattr("price_action.events.bus._HANDLERS", {})
        from price_action.events import publish, EventTopic

        e1 = publish(EventTopic.RECONCILER_PHANTOM, "test", {"symbol": "BTC", "qty": 0.01})
        e2 = publish(EventTopic.RECONCILER_PHANTOM, "test", {"symbol": "BTC", "qty": 0.01})
        # Aynı payload → aynı event_id
        assert e1.event_id == e2.event_id

    def test_handler_exception_doesnt_stop_others(self, tmp_path, monkeypatch):
        """Bir handler crash → diğer handler'lar yine çalışır."""
        monkeypatch.setattr("price_action.events.bus._EVENTS_DIR", tmp_path)
        monkeypatch.setattr("price_action.events.bus._HANDLERS", {})
        from price_action.events import publish, register_handler, EventTopic

        triggered = []

        def crash_handler(env):
            raise RuntimeError("Bang")

        def good_handler(env):
            triggered.append("good")

        register_handler(EventTopic.DRIFT_R_DROP, crash_handler)
        register_handler(EventTopic.DRIFT_R_DROP, good_handler)

        # Crash doesn't propagate
        publish(EventTopic.DRIFT_R_DROP, "test", {})
        assert triggered == ["good"], "Good handler should still fire despite crash"
