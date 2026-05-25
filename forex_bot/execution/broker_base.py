"""Abstract broker interface (MT5, OANDA, cTrader, paper)."""
from __future__ import annotations

import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Optional

from ..contracts import Fill, Position, RiskedOrder

BrokerMode = Literal["paper", "live"]


@dataclass
class BrokerBase(ABC):
    mode: BrokerMode = "paper"
    account_currency: str = "USD"

    def __post_init__(self):
        if self.mode == "live":
            if os.environ.get("FX_LIVE_CONFIRM") != "YES_I_KNOW":
                raise RuntimeError(
                    "FX_LIVE_CONFIRM=YES_I_KNOW env required for live broker mode. "
                    "This is a double-lock to prevent accidental live trading."
                )

    @abstractmethod
    def connect(self) -> bool:
        """Establish broker connection. Idempotent."""
        ...

    def disconnect(self) -> None:
        """Optional clean disconnect."""
        return None

    @abstractmethod
    def place_order(self, order: RiskedOrder, ts: datetime, market_price: float) -> Optional[Fill]:
        ...

    @abstractmethod
    def cancel_order(self, order_id: str) -> bool:
        """Cancel a pending order. Returns True if successful."""
        ...

    @abstractmethod
    def modify_sl(self, pair: str, new_sl: float) -> bool:
        """Adjust stop-loss of open position. Live-mode critical."""
        ...

    @abstractmethod
    def close_position(self, pair: str, ts: datetime, market_price: float, reason: str = "manual") -> Optional[Fill]:
        ...

    @abstractmethod
    def positions(self) -> list[Position]:
        ...

    @abstractmethod
    def balance_usd(self) -> float:
        ...

    @abstractmethod
    def equity_usd(self, prices: dict[str, float]) -> float:
        ...
