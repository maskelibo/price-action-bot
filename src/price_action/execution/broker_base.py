"""Broker ABC."""
from __future__ import annotations

from abc import ABC, abstractmethod

from price_action.contracts import Fill, OrderInstruction, Position


class BrokerBase(ABC):
    """Broker abstraction — paper / live ortak yüzey."""

    mode: str = "abstract"

    @abstractmethod
    def place_order(self, instruction: OrderInstruction) -> Fill | None:
        """Emri ilet ve doldur. Reddedilirse None."""

    @abstractmethod
    def cancel(self, order_id: str) -> bool: ...

    @abstractmethod
    def fetch_positions(self) -> list[Position]: ...

    @abstractmethod
    def fetch_balance(self) -> dict[str, float]:
        """Currency -> free amount."""
