"""OANDA REST v20 broker interface.

Requires: pip install oandapyV20
Auth: set FX_OANDA_API_TOKEN + FX_OANDA_ACCOUNT_ID env vars (practice or live).

Phase 7 wiring (incomplete — requires testnet validation):
  - MarketOrderRequest / LimitOrderRequest → orders.OrderCreate
  - trades.TradeClose / TradeCRCDO (SL/TP modify)
  - positions.OpenPositions → list[Position]
  - accounts.AccountDetails → balance + NAV (multi-currency handled by broker)
"""
from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime
from typing import Optional

from ..contracts import Fill, Position, RiskedOrder
from .broker_base import BrokerBase

logger = logging.getLogger(__name__)


class OandaBroker(BrokerBase):
    def __init__(self, account_id: Optional[str] = None, api_token: Optional[str] = None,
                 environment: str = "practice"):
        super().__init__(mode="live", account_currency="USD")
        self.account_id = account_id or os.environ.get("FX_OANDA_ACCOUNT_ID", "")
        self.api_token = api_token or os.environ.get("FX_OANDA_API_TOKEN", "")
        self.environment = environment
        self._client = None
        if not self.account_id or not self.api_token:
            raise RuntimeError("FX_OANDA_ACCOUNT_ID and FX_OANDA_API_TOKEN must be set")

    def connect(self) -> bool:
        try:
            from oandapyV20 import API  # type: ignore
        except ImportError:
            raise RuntimeError("oandapyV20 not installed: pip install oandapyV20")
        self._client = API(access_token=self.api_token, environment=self.environment)
        return True

    def _require_client(self):
        if self._client is None:
            self.connect()
        return self._client

    def place_order(self, order: RiskedOrder, ts: datetime, market_price: float) -> Optional[Fill]:
        client = self._require_client()
        try:
            from oandapyV20.endpoints.orders import OrderCreate  # type: ignore
            from oandapyV20.contrib.requests import MarketOrderRequest  # type: ignore
        except ImportError as e:
            raise RuntimeError(f"oandapyV20 import failed: {e}")
        sig = order.signal
        # OANDA instrument format: EUR_USD
        instrument = f"{sig.pair[:3]}_{sig.pair[3:]}"
        units = int(order.lots * 100_000)
        if sig.side == "short":
            units = -units
        req = MarketOrderRequest(
            instrument=instrument, units=units,
            stopLossOnFill={"price": f"{order.sl_price:.5f}"},
            takeProfitOnFill={"price": f"{order.tp_prices[0]:.5f}"} if order.tp_prices else None,
        )
        try:
            r = OrderCreate(accountID=self.account_id, data=req.data)
            resp = client.request(r)
            fill_data = resp.get("orderFillTransaction", {})
            fill_price = float(fill_data.get("price", market_price))
            order_id = fill_data.get("id", str(uuid.uuid4()))
            return Fill(
                order_id=order_id, pair=sig.pair, side=sig.side, lots=order.lots,
                fill_price=fill_price, ts=ts,
                spread_paid_pips=0.0, commission_usd=0.0, slippage_pips=0.0,
            )
        except Exception as e:
            logger.exception("OANDA place_order failed: %s", e)
            return None

    def cancel_order(self, order_id: str) -> bool:
        try:
            from oandapyV20.endpoints.orders import OrderCancel  # type: ignore
            r = OrderCancel(accountID=self.account_id, orderID=order_id)
            self._require_client().request(r)
            return True
        except Exception as e:
            logger.exception("OANDA cancel failed: %s", e)
            return False

    def modify_sl(self, pair: str, new_sl: float) -> bool:
        # OANDA: modify trade's SL via TradeCRCDO
        # Implementation deferred — needs trade_id lookup by pair
        logger.warning("OANDA modify_sl not yet implemented for pair=%s", pair)
        return False

    def close_position(self, pair: str, ts: datetime, market_price: float, reason: str = "manual") -> Optional[Fill]:
        try:
            from oandapyV20.endpoints.positions import PositionClose  # type: ignore
            instrument = f"{pair[:3]}_{pair[3:]}"
            r = PositionClose(accountID=self.account_id, instrument=instrument,
                              data={"longUnits": "ALL", "shortUnits": "ALL"})
            resp = self._require_client().request(r)
            tx = resp.get("longOrderFillTransaction") or resp.get("shortOrderFillTransaction") or {}
            fill_price = float(tx.get("price", market_price))
            return Fill(
                order_id=tx.get("id", str(uuid.uuid4())),
                pair=pair, side="short", lots=abs(float(tx.get("units", 0)) / 100_000),
                fill_price=fill_price, ts=ts,
                spread_paid_pips=0.0, commission_usd=0.0, slippage_pips=0.0,
            )
        except Exception as e:
            logger.exception("OANDA close_position failed: %s", e)
            return None

    def positions(self) -> list[Position]:
        try:
            from oandapyV20.endpoints.positions import OpenPositions  # type: ignore
            r = OpenPositions(accountID=self.account_id)
            resp = self._require_client().request(r)
            out = []
            for p in resp.get("positions", []):
                instr = p["instrument"]
                pair = instr.replace("_", "")
                long_units = float(p.get("long", {}).get("units", 0))
                short_units = float(p.get("short", {}).get("units", 0))
                if long_units > 0:
                    out.append(Position(
                        pair=pair, side="long", lots=long_units / 100_000,
                        entry_price=float(p["long"].get("averagePrice", 0)),
                        current_price=float(p["long"].get("averagePrice", 0)),
                        sl_price=0.0, tp_prices=[],
                        opened_at=datetime.utcnow(),
                        unrealized_usd=float(p.get("unrealizedPL", 0)),
                    ))
                elif short_units < 0:
                    out.append(Position(
                        pair=pair, side="short", lots=abs(short_units) / 100_000,
                        entry_price=float(p["short"].get("averagePrice", 0)),
                        current_price=float(p["short"].get("averagePrice", 0)),
                        sl_price=0.0, tp_prices=[],
                        opened_at=datetime.utcnow(),
                        unrealized_usd=float(p.get("unrealizedPL", 0)),
                    ))
            return out
        except Exception as e:
            logger.exception("OANDA positions failed: %s", e)
            return []

    def balance_usd(self) -> float:
        try:
            from oandapyV20.endpoints.accounts import AccountDetails  # type: ignore
            r = AccountDetails(accountID=self.account_id)
            resp = self._require_client().request(r)
            return float(resp["account"]["balance"])
        except Exception as e:
            logger.exception("OANDA balance failed: %s", e)
            return 0.0

    def equity_usd(self, prices: dict[str, float]) -> float:
        try:
            from oandapyV20.endpoints.accounts import AccountDetails  # type: ignore
            r = AccountDetails(accountID=self.account_id)
            resp = self._require_client().request(r)
            return float(resp["account"].get("NAV", resp["account"]["balance"]))
        except Exception as e:
            logger.exception("OANDA equity failed: %s", e)
            return 0.0
