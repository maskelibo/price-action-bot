"""Paper modu sahte cüzdan + pozisyon simulator.

DuckDB tablosu `paper_state` opsiyonel; default JSON dosyasıyla persist eder.
"""
from __future__ import annotations

import json
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from price_action.contracts import Position
from price_action.logging_config import logger
from price_action.settings import get_settings


@dataclass
class PaperPosition:
    venue: str
    symbol: str
    side: str
    quantity: float
    entry_price: float
    sl_price: float | None = None
    tp_price: float | None = None
    opened_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    strategy_id: str = ""
    realized_pnl: float = 0.0
    fees_paid: float = 0.0


@dataclass
class PaperWallet:
    balances: dict[str, float] = field(default_factory=dict)
    positions: list[PaperPosition] = field(default_factory=list)
    realized_pnl_total: float = 0.0


class PaperState:
    """Persistent sahte cüzdan + pozisyon defteri.

    Threadsafe basit kilit ile. DuckDB opsiyonel — yoksa JSON kullanılır.
    """

    def __init__(
        self,
        path: Path | None = None,
        *,
        initial_balance_usdt: float = 10_000.0,
    ) -> None:
        s = get_settings()
        self.path: Path = path or s.logs_dir / "execution" / "paper_state.json"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self.wallet = self._load()
        if "USDT" not in self.wallet.balances:
            self.wallet.balances["USDT"] = initial_balance_usdt
            self._save()

    # ----- persistence -----
    def _load(self) -> PaperWallet:
        if not self.path.exists():
            return PaperWallet()
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            wallet = PaperWallet(
                balances=data.get("balances", {}),
                positions=[PaperPosition(**p) for p in data.get("positions", [])],
                realized_pnl_total=data.get("realized_pnl_total", 0.0),
            )
            return wallet
        except Exception as exc:  # pragma: no cover
            logger.bind(err=str(exc)).warning("paper_state.load_fail")
            return PaperWallet()

    def _save(self) -> None:
        try:
            data = {
                "balances": self.wallet.balances,
                "positions": [asdict(p) for p in self.wallet.positions],
                "realized_pnl_total": self.wallet.realized_pnl_total,
            }
            self.path.write_text(json.dumps(data, default=str, indent=2), encoding="utf-8")
        except Exception as exc:  # pragma: no cover
            logger.bind(err=str(exc)).error("paper_state.save_fail")

    # ----- API -----
    def balance_usdt(self) -> float:
        with self._lock:
            return float(self.wallet.balances.get("USDT", 0.0))

    def open_position(
        self,
        *,
        venue: str,
        symbol: str,
        side: str,
        quantity: float,
        price: float,
        fee: float,
        sl_price: float | None,
        tp_price: float | None,
        strategy_id: str = "",
    ) -> PaperPosition:
        with self._lock:
            notional = quantity * price
            self.wallet.balances["USDT"] = (
                self.wallet.balances.get("USDT", 0.0) - notional - fee
            )
            pos = PaperPosition(
                venue=venue,
                symbol=symbol,
                side=side,
                quantity=quantity,
                entry_price=price,
                sl_price=sl_price,
                tp_price=tp_price,
                strategy_id=strategy_id,
                fees_paid=fee,
            )
            self.wallet.positions.append(pos)
            self._save()
            logger.bind(symbol=symbol, side=side, qty=quantity, price=price).info(
                "paper.open_position"
            )
            return pos

    def close_position(self, position: PaperPosition, *, exit_price: float, fee: float) -> float:
        """Pozisyonu kapat, realized PnL döner."""
        with self._lock:
            if position not in self.wallet.positions:
                return 0.0
            if position.side == "long":
                pnl = (exit_price - position.entry_price) * position.quantity
            else:
                pnl = (position.entry_price - exit_price) * position.quantity
            net = pnl - fee
            self.wallet.balances["USDT"] = (
                self.wallet.balances.get("USDT", 0.0)
                + position.quantity * exit_price
                - fee
            )
            self.wallet.realized_pnl_total += net
            self.wallet.positions.remove(position)
            self._save()
            logger.bind(symbol=position.symbol, exit=exit_price, pnl=net).info(
                "paper.close_position"
            )
            return net

    def to_positions(self) -> list[Position]:
        out = []
        for p in self.wallet.positions:
            out.append(
                Position(
                    venue=p.venue,
                    symbol=p.symbol,
                    side=p.side,  # type: ignore[arg-type]
                    quantity=p.quantity,
                    entry_price=p.entry_price,
                    current_price=p.entry_price,  # MTM çağıran tarafından
                    unrealized_pnl_usdt=0.0,
                    realized_pnl_usdt=p.realized_pnl,
                    sl_price=p.sl_price,
                    tp_price=p.tp_price,
                    opened_at=datetime.fromisoformat(p.opened_at),
                    strategy_id=p.strategy_id,
                    last_updated=datetime.now(timezone.utc),
                )
            )
        return out

    def mark_to_market(self, prices: dict[str, float]) -> float:
        with self._lock:
            equity = self.wallet.balances.get("USDT", 0.0)
            for p in self.wallet.positions:
                px = prices.get(p.symbol, p.entry_price)
                if p.side == "long":
                    pnl = (px - p.entry_price) * p.quantity
                else:
                    pnl = (p.entry_price - px) * p.quantity
                equity += p.quantity * px + pnl - (p.quantity * p.entry_price)
            return equity
