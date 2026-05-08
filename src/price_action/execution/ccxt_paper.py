"""Paper trading broker.

Gerçek WS fiyatından okur (varsa), sahte cüzdanla doldurur. Slippage modeli:
- Order book varsa: book impact (cumulative size * level price ortalaması).
- Yoksa: parametrik 5 bps base + size * coefficient.

Network çağrılarını test/CI'da tetiklemez — `ccxt` yoksa veya canlı veri
yoksa parametrik fiyat kullanılır.
"""
from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone
from typing import Any

from price_action.contracts import Fill, OrderInstruction, Position, stable_hash
from price_action.execution.broker_base import BrokerBase
from price_action.execution.paper_state import PaperState
from price_action.logging_config import logger
from price_action.settings import get_settings


class CCXTPaperBroker(BrokerBase):
    """Paper broker — sahte cüzdan + opsiyonel ccxt fiyat fetch.

    `force_offline=True` testte network'ü tamamen kapatır.
    """

    mode = "paper"

    def __init__(
        self,
        *,
        venue: str = "binance",
        force_offline: bool = False,
        slippage_bps_base: float = 5.0,
        size_impact_bps_per_pct_book: float = 100.0,
        state: PaperState | None = None,
    ) -> None:
        self.venue = venue
        self.force_offline = force_offline
        self.slippage_bps_base = slippage_bps_base
        self.size_impact_bps_per_pct_book = size_impact_bps_per_pct_book
        self.state = state or PaperState()
        self._exchange: Any = None
        self._log = logger.bind(component="ccxt_paper", venue=venue)

    # ----- exchange handle (lazy) -----
    def _get_exchange(self) -> Any | None:
        if self.force_offline:
            return None
        if self._exchange is not None:
            return self._exchange
        try:
            import ccxt  # type: ignore

            kls = getattr(ccxt, self.venue, None)
            if kls is None:
                return None
            self._exchange = kls({"enableRateLimit": True})
            return self._exchange
        except Exception as exc:  # pragma: no cover
            self._log.bind(err=str(exc)).warning("ccxt_paper.exchange_init_fail")
            return None

    # ----- market data -----
    def _fetch_price(self, symbol: str) -> float | None:
        ex = self._get_exchange()
        if ex is None:
            return None
        try:
            t = ex.fetch_ticker(symbol)
            return float(t.get("last") or t.get("close") or 0.0) or None
        except Exception as exc:
            self._log.bind(err=str(exc), symbol=symbol).warning("paper.fetch_ticker_fail")
            return None

    def _fetch_book(self, symbol: str, limit: int = 10) -> dict[str, list[list[float]]] | None:
        ex = self._get_exchange()
        if ex is None:
            return None
        try:
            book = ex.fetch_order_book(symbol, limit=limit)
            return {"bids": book.get("bids", []), "asks": book.get("asks", [])}
        except Exception as exc:
            self._log.bind(err=str(exc), symbol=symbol).warning("paper.fetch_book_fail")
            return None

    # ----- slippage -----
    def _slippage_bps_for(
        self, symbol: str, side: str, quantity: float, ref_price: float
    ) -> float:
        book = self._fetch_book(symbol)
        if not book:
            return self.slippage_bps_base + 0.5  # küçük ek
        levels = book["asks"] if side == "long" else book["bids"]
        remaining = quantity
        cost_qty = 0.0
        cost_total = 0.0
        for lvl in levels:
            if remaining <= 0:
                break
            price, size = float(lvl[0]), float(lvl[1])
            take = min(remaining, size)
            cost_qty += take
            cost_total += take * price
            remaining -= take
        if cost_qty <= 0 or ref_price <= 0:
            return self.slippage_bps_base
        avg_fill = cost_total / cost_qty
        slippage = (avg_fill - ref_price) / ref_price if side == "long" else (ref_price - avg_fill) / ref_price
        return max(self.slippage_bps_base, slippage * 10_000)

    # ----- API -----
    def place_order(self, instruction: OrderInstruction) -> Fill | None:
        # Live mode guard — paper'a çağrılan emir test mode'da bile gerçek fiyat
        # almak için canlıya gidebilir; ama settings.is_live ile bağlantı kurmaya çalışmaz.
        sig = instruction.risked_order.signal
        ref_price = self._fetch_price(sig.symbol)
        if ref_price is None or ref_price <= 0:
            # Offline fallback: signal'in tp_price/sl_price ortasından bir tahmin
            ref_price = (sig.sl_price + sig.tp_price) / 2 if sig.tp_price else sig.sl_price
        ref_price = float(ref_price)

        qty = instruction.risked_order.quantity
        side = sig.direction
        slip_bps = self._slippage_bps_for(sig.symbol, side, qty, ref_price)
        if slip_bps > 25:
            self._log.bind(symbol=sig.symbol, slip_bps=slip_bps).warning("paper.slippage_too_high")
            return None
        slip = slip_bps / 10_000.0
        fill_price = ref_price * (1 + slip if side == "long" else 1 - slip)
        fee = qty * fill_price * 0.00075  # taker varsayım

        # Cüzdana yansıt
        self.state.open_position(
            venue=self.venue,
            symbol=sig.symbol,
            side=side,
            quantity=qty,
            price=fill_price,
            fee=fee,
            sl_price=instruction.risked_order.sl_price,
            tp_price=sig.tp_price,
            strategy_id=sig.metadata.get("strategy_id", "") if sig.metadata else "",
        )
        order_id = "paper-" + uuid.uuid4().hex[:12]
        fill = Fill(
            order_id=order_id,
            venue=self.venue,
            symbol=sig.symbol,
            side=side,  # type: ignore[arg-type]
            price=fill_price,
            quantity=qty,
            fee_usdt=fee,
            timestamp=datetime.now(timezone.utc),
            is_maker=instruction.order_type == "post_only_limit",
            expected_price=ref_price,
            slippage_bps=slip_bps,
            mode="paper",
            manifest_hash=stable_hash(
                {
                    "instr": instruction.model_dump(mode="json"),
                    "fill_price": fill_price,
                    "ts": datetime.now(timezone.utc).isoformat(),
                }
            ),
        )
        self._log.bind(order_id=order_id, slip_bps=slip_bps).info("paper.fill")
        return fill

    def cancel(self, order_id: str) -> bool:
        # Paper modu emirleri instant fill — cancel no-op
        return True

    def fetch_positions(self) -> list[Position]:
        return self.state.to_positions()

    def fetch_balance(self) -> dict[str, float]:
        return dict(self.state.wallet.balances)

    # ----- close (paper-only convenience) -----
    def close_position(self, position: Position, exit_price: float | None = None) -> Fill | None:
        for p in self.state.wallet.positions:
            if p.symbol == position.symbol and p.side == position.side:
                px = exit_price or self._fetch_price(p.symbol) or p.entry_price
                fee = p.quantity * px * 0.00075
                pnl = self.state.close_position(p, exit_price=px, fee=fee)
                return Fill(
                    order_id="paper-close-" + uuid.uuid4().hex[:8],
                    venue=self.venue,
                    symbol=p.symbol,
                    side="short" if p.side == "long" else "long",  # type: ignore[arg-type]
                    price=px,
                    quantity=p.quantity,
                    fee_usdt=fee,
                    timestamp=datetime.now(timezone.utc),
                    is_maker=False,
                    expected_price=px,
                    slippage_bps=0.0,
                    mode="paper",
                    manifest_hash=stable_hash({"close": True, "pnl": pnl}),
                )
        return None
