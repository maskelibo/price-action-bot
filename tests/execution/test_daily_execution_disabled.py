"""Fail-closed contract for the retired non-durable daily order surface."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest
import scripts.futures_daemon as daemon
import scripts.futures_trade_daily as daily


def _signal() -> dict:
    return {
        "ts": datetime(2026, 7, 11, tzinfo=UTC),
        "symbol": "BTC/USDT",
        "strategy": "test",
        "side": "long",
        "sl_price": 99.0,
        "tp_price": 102.0,
        "confluence": 0.8,
    }


def test_non_dry_daily_submit_blocks_before_unverified_fill_or_exchange_io(monkeypatch) -> None:
    exchange_factory = MagicMock(side_effect=AssertionError("exchange I/O must not start"))
    router = MagicMock(
        return_value=(
            {
                "id": "filled-but-unverified",
                "status": "closed",
                "filled": 1.0,
                "average": None,
                "fill_price_verified": False,
            },
            "market_fallback",
        )
    )
    monkeypatch.setattr(daily, "get_futures_exchange", exchange_factory)
    monkeypatch.setattr(daily, "place_post_only_with_fallback", router)

    with pytest.raises(daily.LegacyDailyExecutionDisabledError, match="crash-complete"):
        daily.submit_to_futures(
            [_signal()],
            dry_run=False,
            execution_cfg={"post_only_limit_enabled": True},
        )

    exchange_factory.assert_not_called()
    router.assert_not_called()


def test_non_dry_empty_batch_cannot_bypass_retired_surface() -> None:
    with pytest.raises(daily.LegacyDailyExecutionDisabledError, match="disabled"):
        daily.submit_to_futures([], dry_run=False)


def test_daily_run_blocks_before_journal_or_scan_mutation(monkeypatch) -> None:
    init_journal = MagicMock(side_effect=AssertionError("journal must not mutate"))
    scan = MagicMock(side_effect=AssertionError("scanner must not run"))
    monkeypatch.setattr(daily, "init_journal", init_journal)
    monkeypatch.setattr(daily, "scan_signals", scan)

    with pytest.raises(daily.LegacyDailyExecutionDisabledError, match="dry-run"):
        daily.daily_run(datetime(2026, 7, 11, tzinfo=UTC), dry_run=False)

    init_journal.assert_not_called()
    scan.assert_not_called()


def test_post_only_helper_requires_deterministic_client_id_before_router(monkeypatch) -> None:
    router = MagicMock(side_effect=AssertionError("router must not submit without identity"))
    monkeypatch.setattr(daily, "setup_leverage", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(daily, "place_post_only_with_fallback", router)

    with pytest.raises(ValueError, match="deterministic client_order_id"):
        daily._submit_order_with_adaptive_leverage(
            MagicMock(),
            "BTC/USDT",
            "buy",
            1.0,
            1,
            post_only_enabled=True,
            target_price=100.0,
        )

    router.assert_not_called()


def test_legacy_1d_daemon_marks_retired_once_without_scan_or_network(monkeypatch) -> None:
    unsafe_daily = MagicMock(side_effect=AssertionError("legacy daily path must not run"))
    save = MagicMock()
    logs = []
    monkeypatch.setattr(daily, "daily_run", unsafe_daily)
    monkeypatch.setattr(daemon, "_save_last_scan_date", save)
    monkeypatch.setattr(daemon, "log", logs.append)
    monkeypatch.setattr(daemon, "_last_signal_scan_date", None)
    now = datetime(2026, 7, 11, 1, 0, tzinfo=UTC)

    daemon.signal_scan_if_new_day(now)
    daemon.signal_scan_if_new_day(now)

    unsafe_daily.assert_not_called()
    save.assert_called_once_with(now.date())
    assert len(logs) == 1
    assert logs[0].startswith("DAILY_SCAN_RETIRED:")
