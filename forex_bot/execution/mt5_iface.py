"""MetaTrader 5 broker interface stub.

Requires: pip install MetaTrader5 (Windows only).
Set FX_MT5_LOGIN, FX_MT5_PASSWORD, FX_MT5_SERVER env vars.

Phase 7 wiring template (full impl pending testnet).
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


class MT5Broker(BrokerBase):
    def __init__(self, login: Optional[int] = None, password: Optional[str] = None,
                 server: Optional[str] = None, account_currency: str = "USD"):
        super().__init__(mode="live", account_currency=account_currency)
        self.login = int(login or os.environ.get("FX_MT5_LOGIN", "0"))
        self.password = password or os.environ.get("FX_MT5_PASSWORD", "")
        self.server = server or os.environ.get("FX_MT5_SERVER", "")
        self._connected = False

    def connect(self) -> bool:
        try:
            import MetaTrader5 as mt5  # type: ignore
        except ImportError:
            raise RuntimeError("MetaTrader5 not installed (Windows only)")
        if not mt5.initialize(login=self.login, password=self.password, server=self.server):
            raise RuntimeError(f"MT5 init failed: {mt5.last_error()}")
        self._connected = True
        return True

    def place_order(self, order: RiskedOrder, ts: datetime, market_price: float) -> Optional[Fill]:
        try:
            import MetaTrader5 as mt5  # type: ignore
        except ImportError:
            return None
        sig = order.signal
        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": sig.pair,
            "volume": float(order.lots),
            "type": mt5.ORDER_TYPE_BUY if sig.side == "long" else mt5.ORDER_TYPE_SELL,
            "price": market_price,
            "sl": float(order.sl_price),
            "tp": float(order.tp_prices[0]) if order.tp_prices else 0.0,
            "deviation": 20,
            "magic": 99001,
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_FOK,
        }
        result = mt5.order_send(request)
        if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
            logger.error("MT5 order_send failed: %s", result)
            return None
        return Fill(
            order_id=str(result.order), pair=sig.pair, side=sig.side, lots=order.lots,
            fill_price=float(result.price), ts=ts,
            spread_paid_pips=0.0, commission_usd=0.0, slippage_pips=0.0,
        )

    def cancel_order(self, order_id: str) -> bool:
        try:
            import MetaTrader5 as mt5  # type: ignore
            request = {"action": mt5.TRADE_ACTION_REMOVE, "order": int(order_id)}
            result = mt5.order_send(request)
            return result is not None and result.retcode == mt5.TRADE_RETCODE_DONE
        except Exception:
            return False

    def modify_sl(self, pair: str, new_sl: float) -> bool:
        try:
            import MetaTrader5 as mt5  # type: ignore
            positions = mt5.positions_get(symbol=pair)
            if not positions:
                return False
            pos = positions[0]
            request = {
                "action": mt5.TRADE_ACTION_SLTP,
                "position": pos.ticket,
                "sl": float(new_sl),
                "tp": pos.tp,
            }
            result = mt5.order_send(request)
            return result is not None and result.retcode == mt5.TRADE_RETCODE_DONE
        except Exception:
            return False

    def close_position(self, pair: str, ts: datetime, market_price: float, reason: str = "manual") -> Optional[Fill]:
        try:
            import MetaTrader5 as mt5  # type: ignore
            positions = mt5.positions_get(symbol=pair)
            if not positions:
                return None
            pos = positions[0]
            close_type = mt5.ORDER_TYPE_SELL if pos.type == mt5.POSITION_TYPE_BUY else mt5.ORDER_TYPE_BUY
            request = {
                "action": mt5.TRADE_ACTION_DEAL,
                "symbol": pair, "volume": pos.volume,
                "type": close_type, "position": pos.ticket,
                "price": market_price, "deviation": 20, "magic": 99001,
                "type_time": mt5.ORDER_TIME_GTC, "type_filling": mt5.ORDER_FILLING_FOK,
            }
            result = mt5.order_send(request)
            if result and result.retcode == mt5.TRADE_RETCODE_DONE:
                return Fill(
                    order_id=str(result.order), pair=pair,
                    side="short" if pos.type == mt5.POSITION_TYPE_BUY else "long",
                    lots=pos.volume, fill_price=float(result.price), ts=ts,
                    spread_paid_pips=0.0, commission_usd=0.0, slippage_pips=0.0,
                )
            return None
        except Exception as e:
            logger.exception("MT5 close failed: %s", e)
            return None

    def positions(self) -> list[Position]:
        try:
            import MetaTrader5 as mt5  # type: ignore
            mt5_positions = mt5.positions_get() or []
            out = []
            for p in mt5_positions:
                out.append(Position(
                    pair=p.symbol,
                    side="long" if p.type == mt5.POSITION_TYPE_BUY else "short",
                    lots=float(p.volume), entry_price=float(p.price_open),
                    current_price=float(p.price_current),
                    sl_price=float(p.sl), tp_prices=[float(p.tp)] if p.tp else [],
                    opened_at=datetime.fromtimestamp(p.time),
                    unrealized_usd=float(p.profit),
                ))
            return out
        except Exception:
            return []

    def balance_usd(self) -> float:
        try:
            import MetaTrader5 as mt5  # type: ignore
            info = mt5.account_info()
            return float(info.balance) if info else 0.0
        except Exception:
            return 0.0

    def equity_usd(self, prices: dict[str, float]) -> float:
        try:
            import MetaTrader5 as mt5  # type: ignore
            info = mt5.account_info()
            return float(info.equity) if info else 0.0
        except Exception:
            return 0.0
