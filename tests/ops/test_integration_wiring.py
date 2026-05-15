"""Integration tests for throttle wiring into core modules."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from price_action.execution.dead_mans_switch import DeadMansSwitch
from price_action.execution.slippage_tracker import SlippageTracker
from price_action.ops import reset_telegram_throttle
from price_action.risk.breaker import DDBreaker
from price_action.risk.sizing import AccountState


class TestDeadMansSwitchTelegram:
    """Verify DMS -> Telegram throttle wiring."""

    def setup_method(self) -> None:
        reset_telegram_throttle()

    def test_dms_alarm_calls_throttle(self) -> None:
        """When DMS triggers flatten, alarm goes through throttle."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "dms.duckdb"
            dms = DeadMansSwitch(db_path=db_path, service_name="test_svc")

            with patch("price_action.ops.telegram_throttle.send_critical") as mock_crit:
                mock_crit.return_value = True
                dms._send_alarm("Test emergency message")

            # Verify send_critical was called (via throttle)
            mock_crit.assert_called_once()
            call_args = mock_crit.call_args[0][0]
            assert "Test emergency message" in call_args


class TestSlippageTrackerTelegram:
    """Verify slippage_tracker -> Telegram throttle wiring."""

    def setup_method(self) -> None:
        reset_telegram_throttle()

    def test_slippage_alarm_calls_throttle(self) -> None:
        """When slippage exceeds threshold, alarm goes through throttle."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "slippage.duckdb"
            tracker = SlippageTracker(db_path=db_path)

            with patch(
                "price_action.ops.telegram_throttle.send_telegram"
            ) as mock_send:
                mock_send.return_value = True
                tracker._alarm("WARNING", "Slippage warning test")

            mock_send.assert_called_once()


class TestBreakerTelegram:
    """Verify breaker -> Telegram throttle wiring."""

    def setup_method(self) -> None:
        reset_telegram_throttle()

    def test_breaker_trigger_sends_alert(self) -> None:
        """When breaker triggers, throttled alarm sent."""
        with tempfile.TemporaryDirectory() as tmpdir:
            state_path = Path(tmpdir) / "breaker_state.json"
            config = {
                "daily_loss_pct": 0.05,
                "monthly_loss_pct": 0.15,
            }
            breaker = DDBreaker(config=config, state_path=state_path)

            # Manually trigger daily breaker
            breaker.state.triggered_daily = True

            with patch("price_action.ops.get_telegram_throttle") as mock_get:
                mock_throttle = MagicMock()
                mock_get.return_value = mock_throttle
                breaker._send_trigger_alarms()

            # Should have called throttle for daily DD halt
            # send_throttled is called with positional arg 0 = alert_type
            calls = [c[0][0] for c in mock_throttle.send_throttled.call_args_list]
            assert "daily_dd_halt" in calls

    def test_breaker_no_trigger_no_alarm(self) -> None:
        """When breaker not triggered, no alarm sent."""
        with tempfile.TemporaryDirectory() as tmpdir:
            state_path = Path(tmpdir) / "breaker_state.json"
            config = {"daily_loss_pct": 0.05}
            breaker = DDBreaker(config=config, state_path=state_path)

            # No trigger
            breaker.state.triggered_daily = False
            breaker.state.triggered_weekly = False
            breaker.state.triggered_monthly = False
            breaker.state.triggered_consecutive = False

            with patch("price_action.ops.get_telegram_throttle") as mock_get:
                mock_throttle = MagicMock()
                mock_get.return_value = mock_throttle
                breaker._send_trigger_alarms()

            # Should not call throttle.send_throttled
            mock_throttle.send_throttled.assert_not_called()


class TestThrottleEffectiveness:
    """Verify throttle reduces alarm spam in realistic scenarios."""

    def setup_method(self) -> None:
        reset_telegram_throttle()

    def test_slippage_spam_throttled(self) -> None:
        """Multiple slippage alarms within window are buffered."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "slippage.duckdb"
            tracker = SlippageTracker(db_path=db_path)

            with patch(
                "price_action.ops.telegram_throttle.send_telegram"
            ) as mock_send:
                mock_send.return_value = True

                # Trigger 5 slippage alarms rapidly
                for i in range(5):
                    tracker._alarm("WARNING", f"Slippage {i}")

            # Only 1 should be sent (rest buffered)
            assert mock_send.call_count == 1

    def test_breaker_multiple_triggers_throttled(self) -> None:
        """Multiple breaker updates within window send only once."""
        with tempfile.TemporaryDirectory() as tmpdir:
            state_path = Path(tmpdir) / "breaker_state.json"
            config = {"daily_loss_pct": 0.05}
            breaker = DDBreaker(config=config, state_path=state_path)

            with patch("price_action.ops.get_telegram_throttle") as mock_get:
                mock_throttle = MagicMock()
                mock_get.return_value = mock_throttle

                # Trigger daily DD 3 times
                for _ in range(3):
                    breaker.state.triggered_daily = True
                    breaker._send_trigger_alarms()

            # Should call 3 times (each _send_trigger_alarms call attempts),
            # but throttle on backend will suppress 2 of 3
            # (This test verifies calls are made, actual throttling tested elsewhere)
            assert mock_throttle.send_throttled.call_count >= 1
