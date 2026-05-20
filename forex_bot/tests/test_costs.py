"""Cost model tests."""
from __future__ import annotations

from datetime import datetime, timezone

from forex_bot.backtest.costs import CostConfig, CostModel


def test_spread_session_variation():
    cm = CostModel()
    london = cm.spread_pips("EURUSD", datetime(2024, 1, 8, 9, 0, tzinfo=timezone.utc))
    asia = cm.spread_pips("EURUSD", datetime(2024, 1, 8, 23, 0, tzinfo=timezone.utc))
    overlap = cm.spread_pips("EURUSD", datetime(2024, 1, 8, 14, 0, tzinfo=timezone.utc))
    assert asia > london > overlap


def test_commission_per_lot():
    cm = CostModel()
    assert cm.commission_usd(1.0) == 7.0
    assert cm.commission_usd(0.5) == 3.5


def test_swap_signs():
    cm = CostModel()
    # USDJPY long is positive carry
    assert cm.swap_usd("USDJPY", "long", 1.0, 1) > 0
    # USDJPY short is negative carry
    assert cm.swap_usd("USDJPY", "short", 1.0, 1) < 0


def test_weekend_gap_severity():
    cm = CostModel()
    p50 = cm.weekend_gap_pips(0.5)
    p95 = cm.weekend_gap_pips(0.95)
    assert p95 > p50


def test_entry_cost_positive():
    cm = CostModel()
    cost, spr = cm.total_entry_cost_usd("EURUSD", 1.0, datetime(2024, 1, 8, 9, 0))
    assert cost > 0
    assert spr > 0
