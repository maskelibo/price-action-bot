"""cTrader Open API stub — protobuf-based, requires implementations per broker.

Full impl deferred to Phase 7 (high effort, broker-specific session/auth flow).
Stub raises clear error for live attempts.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from ..contracts import Fill, Position, RiskedOrder
from .broker_base import BrokerBase

logger = logging.getLogger(__name__)


class CTraderBroker(BrokerBase):
    def __init__(self, client_id: str = "", client_secret: str = "", account_id: int = 0):
        super().__init__(mode="live", account_currency="USD")
        self.client_id = client_id
        self.client_secret = client_secret
        self.account_id = account_id

    def connect(self) -> bool:
        raise NotImplementedError(
            "cTrader Open API protobuf session not implemented. "
            "Phase 7: pip install ctrader-open-api + complete auth flow."
        )

    def place_order(self, order: RiskedOrder, ts: datetime, market_price: float) -> Optional[Fill]:
        raise NotImplementedError("cTrader place_order deferred to Phase 7")

    def cancel_order(self, order_id: str) -> bool:
        raise NotImplementedError

    def modify_sl(self, pair: str, new_sl: float) -> bool:
        raise NotImplementedError

    def close_position(self, pair: str, ts: datetime, market_price: float, reason: str = "manual") -> Optional[Fill]:
        raise NotImplementedError

    def positions(self) -> list[Position]:
        raise NotImplementedError

    def balance_usd(self) -> float:
        raise NotImplementedError

    def equity_usd(self, prices: dict[str, float]) -> float:
        raise NotImplementedError
