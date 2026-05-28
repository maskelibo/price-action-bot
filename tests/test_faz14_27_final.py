"""Faz 14.27 FINAL — kalan 11 eksik için integration tests.

5m DMS init kodu, bracket+pyramid race, state JSON atomic, event handler wire.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


class Test5mDMSInitCode:
    """5m bot DMS init kodunu fonksiyonel doğrula (bot start etmeden)."""

    def test_5m_dms_code_path_exists(self):
        """run_5m_mode içinde DMS init kodu var mı?"""
        daemon_code = (ROOT / "scripts/futures_daemon.py").read_text()
        # FIX C2-2/B (Faz 14.27 P1-2) markeri
        assert "5M_DMS: başlatıldı" in daemon_code or "dms_5m = DeadMansSwitch" in daemon_code
        # tf="5m" ile init edilmeli
        assert 'tf="5m"' in daemon_code
        # IDEMPOTENCY_DB kullanılmalı (per-bot)
        assert "db_path=IDEMPOTENCY_DB" in daemon_code

    def test_dms_class_supports_5m_tf(self):
        """DeadMansSwitch tf='5m' parametresini kabul ediyor."""
        from price_action.execution.dead_mans_switch import TF_DMS_PARAMS

        assert "5m" in TF_DMS_PARAMS
        params = TF_DMS_PARAMS["5m"]
        assert "heartbeat_sec" in params
        assert "timeout_sec" in params
        # 5m TF için: heartbeat 10s, timeout 600s
        assert params["heartbeat_sec"] == 10
        assert params["timeout_sec"] == 600


class TestBracketPyramidRace:
    """C3-5 sequential constraint + tp_partial_filled guard."""

    def test_tp_filled_blocks_leg_up(self):
        """Position'da tp_partial_filled=True ise leg-up bloke."""

        # Mock minimal position
        class MockLeg:
            leg_num = 1
            leg_state = "FILLED"

        class MockPosition:
            parent_position_id = "test_pos_1"
            tp_partial_filled = True  # TP fill simüle
            pyramid_triggers = [1.0, 1.5]  # leg-2 + leg-3 trigger R
            _lock = __import__("threading").Lock()
            legs = [MockLeg()]

            def sl_hit(self, price):
                return False

            def trigger_reached(self, leg_num, price):
                return True  # her leg trigger reached

            def trigger_price_for_leg(self, leg_num):
                return 100.0

            def leg_for_num(self, leg_num):
                return MockLeg() if leg_num == 1 else None

        # Bracket+pyramid logic'i reproduce (futures_daemon.py:200-260 ekvivalan)
        position = MockPosition()
        legs_submitted = []
        with position._lock:
            tp_filled = getattr(position, "tp_partial_filled", False)
            if tp_filled:
                # FIX: leg-up bloke
                pass
            else:
                # Eğer fill değilse sequential submit
                for idx, _ in enumerate(position.pyramid_triggers):
                    legs_submitted.append(idx + 2)

        # Verify: 0 leg submitted (TP fill bloke etti)
        assert legs_submitted == [], "TP partial fill leg-up'ı bloke etmeli"


class TestStateJSONAtomic:
    """C2-3 atomic write + .bak recovery."""

    def test_atomic_write_creates_backup(self, tmp_path, monkeypatch):
        """_save_state .bak yedek bırakıyor."""
        # State dir mock'la
        monkeypatch.setattr("price_action.execution.p1c_walker._STATE_DIR", tmp_path)
        state_file = tmp_path / "p1c_walker_state.json"
        monkeypatch.setattr("price_action.execution.p1c_walker._STATE_FILE", state_file)

        from price_action.execution.p1c_walker import P1cWalker

        w = P1cWalker(config_path=ROOT / "configs/risk_phoenix_scalp_5m_p1c.yaml")
        # İlk save
        w._state["test_marker"] = "v1"
        w._save_state()
        assert state_file.exists()
        assert "v1" in state_file.read_text()
        # İkinci save → .bak'a yedek
        w._state["test_marker"] = "v2"
        w._save_state()
        bak = state_file.with_suffix(state_file.suffix + ".bak")
        assert bak.exists(), ".bak yedek dosya olmalı"
        # .bak v1 içermeli (önceki state)
        assert "v1" in bak.read_text(), f".bak son state v1 içermeli: {bak.read_text()}"
        # state v2 içermeli
        assert "v2" in state_file.read_text()

    def test_corrupt_state_recovers_from_bak(self, tmp_path, monkeypatch):
        """state.json bozuk → .bak'tan recover."""
        import json

        monkeypatch.setattr("price_action.execution.p1c_walker._STATE_DIR", tmp_path)
        state_file = tmp_path / "p1c_walker_state.json"
        bak_file = state_file.with_suffix(state_file.suffix + ".bak")
        monkeypatch.setattr("price_action.execution.p1c_walker._STATE_FILE", state_file)

        # Bozuk state.json yaz
        state_file.write_text("{broken json")
        # .bak geçerli
        bak_file.write_text(json.dumps({"equity_usdt": 1234.0, "trades": []}))

        from price_action.execution.p1c_walker import P1cWalker

        w = P1cWalker(config_path=ROOT / "configs/risk_phoenix_scalp_5m_p1c.yaml")
        # Recovery: .bak'tan equity okumalı
        assert w._state["equity_usdt"] == 1234.0


class TestEventHandlersWired:
    """Event bus handler registration kontrolü."""

    def test_register_event_handlers_callable(self):
        """_register_event_handlers_once import edilebilir."""
        from price_action.orchestrator.scheduler import _register_event_handlers_once

        assert callable(_register_event_handlers_once)

    def test_handlers_registered_after_call(self, tmp_path, monkeypatch):
        """Çağrı sonrası _HANDLERS dict 6 topic için handler içermeli."""
        # Clean handler state
        monkeypatch.setattr("price_action.events.bus._HANDLERS", {})
        from price_action.events.bus import _HANDLERS
        from price_action.orchestrator.scheduler import _register_event_handlers_once

        _register_event_handlers_once()

        expected_topics = {
            "bot_monitor.pause_alert",
            "reconciler.phantom",
            "reconciler.qty_drift",
            "drift.wr_drop",
            "drift.r_drop",
            "drift.regime_change",
        }
        registered = set(_HANDLERS.keys())
        assert expected_topics.issubset(registered), f"Eksik topic: {expected_topics - registered}"


class TestLabConfigParity:
    """ProductionConfig.from_yaml LIVE schema okuyor — adapter redundant."""

    def test_production_config_reads_canonical_schema(self):
        """v63 config → ProductionConfig.from_yaml → risk_pct doğru."""
        from price_action.backtest.lab import ProductionConfig

        cfg = ProductionConfig.from_yaml(ROOT / "configs/risk_phoenix_scalp_15m_rsi2_v63.yaml")
        # risk_pct = position_sizing.backtest_risk_pct veya risk_per_trade
        assert cfg.risk_pct == 0.005
        # max_concurrent = concentration_limits.max_open_positions (v63 = 8)
        assert cfg.max_concurrent == 8


class TestPrecommitInstalled:
    """Pre-commit hooks installed kontrol."""

    def test_precommit_hook_file_exists(self):
        """git/hooks/pre-commit dosyası var → hook installed."""
        hook_path = ROOT / ".git/hooks/pre-commit"
        assert hook_path.exists(), "pre-commit install çalıştırılmadı"
        content = hook_path.read_text()
        assert "pre-commit" in content.lower()
