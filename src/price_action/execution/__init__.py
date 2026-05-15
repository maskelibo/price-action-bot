"""Execution paketi — broker abstraction, paper/live brokers, order manager."""
from __future__ import annotations

from price_action.execution.broker_base import BrokerBase
from price_action.execution.ccxt_paper import CCXTPaperBroker
from price_action.execution.ccxt_live import CCXTLiveBroker
from price_action.execution.order_manager import OrderManager
from price_action.execution.idempotency import IdempotencyStore
from price_action.execution.slippage_tracker import SlippageTracker
from price_action.execution.dead_mans_switch import DeadMansSwitch

__all__ = [
    "BrokerBase",
    "CCXTLiveBroker",
    "CCXTPaperBroker",
    "OrderManager",
    "IdempotencyStore",
    "SlippageTracker",
    "DeadMansSwitch",
]
