"""NewsGuard tests with cached calendar."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from forex_bot.news.calendar import EconomicEvent
from forex_bot.news.guard import NewsGuard


def test_blackout_simple():
    evt = EconomicEvent(
        ts_utc=datetime(2024, 5, 3, 12, 30, tzinfo=timezone.utc),
        currency="USD", impact="high", title="NFP", country="US",
    )
    g = NewsGuard(events=[evt])
    blocked, e = g.is_blackout(datetime(2024, 5, 3, 12, 15, tzinfo=timezone.utc), "EURUSD")
    assert blocked
    blocked, _ = g.is_blackout(datetime(2024, 5, 3, 12, 55, tzinfo=timezone.utc), "EURUSD")
    assert blocked
    blocked, _ = g.is_blackout(datetime(2024, 5, 3, 13, 5, tzinfo=timezone.utc), "EURUSD")
    assert not blocked


def test_pair_filter():
    evt = EconomicEvent(
        ts_utc=datetime(2024, 5, 3, 12, 30, tzinfo=timezone.utc),
        currency="JPY", impact="high", title="BoJ", country="JP",
    )
    g = NewsGuard(events=[evt])
    blocked, _ = g.is_blackout(datetime(2024, 5, 3, 12, 30, tzinfo=timezone.utc), "EURUSD")
    assert not blocked  # JPY event doesn't affect EURUSD
    blocked, _ = g.is_blackout(datetime(2024, 5, 3, 12, 30, tzinfo=timezone.utc), "USDJPY")
    assert blocked


def test_should_tighten():
    evt = EconomicEvent(
        ts_utc=datetime(2024, 5, 3, 13, 0, tzinfo=timezone.utc),
        currency="USD", impact="high", title="NFP", country="US",
    )
    g = NewsGuard(events=[evt])
    # 30 minutes before — should tighten
    assert g.should_tighten_stop(datetime(2024, 5, 3, 12, 30, tzinfo=timezone.utc), "GBPUSD")
    # 2 hours before — should not
    assert not g.should_tighten_stop(datetime(2024, 5, 3, 11, 0, tzinfo=timezone.utc), "GBPUSD")


def test_impact_filter():
    evt = EconomicEvent(
        ts_utc=datetime(2024, 5, 3, 12, 30, tzinfo=timezone.utc),
        currency="USD", impact="low", title="Random", country="US",
    )
    g = NewsGuard(events=[evt])  # default filters only "high"
    blocked, _ = g.is_blackout(datetime(2024, 5, 3, 12, 30, tzinfo=timezone.utc), "EURUSD")
    assert not blocked
