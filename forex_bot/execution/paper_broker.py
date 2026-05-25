"""Paper broker for simulation and dry-runs."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from ..contracts import Fill, Position, RiskedOrder, pip_value, price_to_pips
from .broker_base import BrokerBase


class PaperBroker(BrokerBase):
    def __init__(self, initial_balance_usd: float = 10_000.0):
        super().__init__(mode="paper", account_currency="USD")
        self._balance = initial_balance_usd
        self._positions: dict[str, Position] = {}
        self._last_close_pnl: float = 0.0
        self._fills: list[Fill] = []
        self._connected = False

    def connect(self) -> bool:
        self._connected = True
        return True

    def disconnect(self) -> None:
        self._connected = False

    def place_order(self, order: RiskedOrder, ts: datetime, market_price: float) -> Optional[Fill]:
        sig = order.signal
        pos = Position(
            pair=sig.pair, side=sig.side, lots=order.lots,
            entry_price=market_price, current_price=market_price,
            sl_price=order.sl_price, tp_prices=order.tp_prices,
            opened_at=ts, unrealized_usd=0.0,
        )
        self._positions[sig.pair] = pos
        fill = Fill(
            order_id=str(uuid.uuid4()),
            pair=sig.pair, side=sig.side, lots=order.lots,
            fill_price=market_price, ts=ts,
            spread_paid_pips=0.0, commission_usd=0.0, slippage_pips=0.0,
        )
        self._fills.append(fill)
        return fill

    def cancel_order(self, order_id: str) -> bool:
        # paper broker: no pending orders, market fills only
        return True

    def modify_sl(self, pair: str, new_sl: float) -> bool:
        if pair in self._positions:
            self._positions[pair].sl_price = new_sl
            return True
        return False

    def close_position(self, pair: str, ts: datetime, market_price: float, reason: str = "manual") -> Optional[Fill]:
        pos = self._positions.pop(pair, None)
        if pos is None:
            return None
        pv = pip_value(pair, lots=pos.lots)
        move_pips = price_to_pips(pair, market_price - pos.entry_price)  # SIGNED
        sign = 1 if pos.side == "long" else -1
        pnl_usd = sign * move_pips * pv
        self._balance += pnl_usd
        self._last_close_pnl = pnl_usd
        fill = Fill(
            order_id=str(uuid.uuid4()),
            pair=pair, side="short" if pos.side == "long" else "long",
            lots=pos.lots, fill_price=market_price, ts=ts,
            spread_paid_pips=0.0, commission_usd=0.0, slippage_pips=0.0,
        )
        self._fills.append(fill)
        return fill

    def positions(self) -> list[Position]:
        return list(self._positions.values())

    def balance_usd(self) -> float:
        return self._balance

    def equity_usd(self, prices: dict[str, float]) -> float:
        eq = self._balance
        for p in self._positions.values():
            cur = prices.get(p.pair, p.current_price)
            pv = pip_value(p.pair, lots=p.lots)
            move_pips = price_to_pips(p.pair, cur - p.entry_price)  # SIGNED
            sign = 1 if p.side == "long" else -1
            eq += sign * move_pips * pv
        return eq
