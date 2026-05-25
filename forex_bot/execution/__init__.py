"""Execution: broker abstraction, paper backend, MT5/OANDA/cTrader stubs,
trade journal, dead man's switch, slippage tracker, capital cap, persistent idempotency.
"""
from .broker_base import BrokerBase, BrokerMode
from .paper_broker import PaperBroker
from .order_router import OrderRouter
from .idempotency import IdempotencyStore, signal_fingerprint, make_client_order_id
from .trade_journal import TradeJournal
from .dead_mans_switch import DeadMansSwitch
from .slippage_tracker import SlippageTracker
from .capital_cap import CapitalCap

__all__ = [
    "BrokerBase", "BrokerMode", "PaperBroker", "OrderRouter",
    "IdempotencyStore", "signal_fingerprint", "make_client_order_id",
    "TradeJournal", "DeadMansSwitch", "SlippageTracker", "CapitalCap",
]
