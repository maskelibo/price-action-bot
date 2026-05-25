"""Order router: signal → idempotency → risk → broker."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from ..contracts import Fill, Reject, RiskedOrder, Signal
from ..risk.officer import AccountState, RiskOfficer
from .broker_base import BrokerBase
from .idempotency import IdempotencyStore, signal_fingerprint


class OrderRouter:
    def __init__(self, broker: BrokerBase, risk: RiskOfficer, idempotency: Optional[IdempotencyStore] = None):
        self.broker = broker
        self.risk = risk
        self.idempotency = idempotency or IdempotencyStore()

    def route(self, signal: Signal, account: AccountState, ts: datetime, market_price: float) -> tuple[str, Optional[Fill], Optional[Reject], Optional[RiskedOrder]]:
        fp = signal_fingerprint(signal.pair, signal.ts, signal.side, signal.sl_price, signal.strategy)
        if self.idempotency.is_seen(fp):
            return "duplicate", None, None, None
        decision = self.risk.evaluate(signal, account, ts)
        if isinstance(decision, Reject):
            self.idempotency.mark(fp, "rejected")
            return "rejected", None, decision, None
        fill = self.broker.place_order(decision, ts, market_price)
        self.idempotency.mark(fp, "filled")
        return ("filled" if fill else "broker_error"), fill, None, decision
