"""Portfolio testleri — önceliklendirme + concentration."""
from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd
import pytest

from price_action.contracts import RiskedOrder, Signal, TPLevel
from price_action.portfolio.allocator import PortfolioManager
from price_action.risk.sizing import AccountState


def _signal(symbol: str, score: float, direction: str = "long") -> Signal:
    return Signal(
        ts=datetime(2024, 6, 1, tzinfo=timezone.utc),
        venue="binance",
        symbol=symbol,
        timeframe="1d",
        direction=direction,  # type: ignore[arg-type]
        pattern_id="bullish_pin_bar",
        confluence_score=score,
        sl_price=98.0,
        tp_price=104.0,
        suggested_size_atr=2.0,
    )


def _risked(sig: Signal, qty: float = 1.0, notional: float = 1000.0) -> RiskedOrder:
    return RiskedOrder(
        signal=sig,
        quantity=qty,
        notional_usdt=notional,
        leverage=1.0,
        sl_price=sig.sl_price,
        tp_levels=[TPLevel(price=sig.tp_price, fraction=1.0)],
        margin_used=notional,
        risk_budget_consumed=0.01,
    )


def test_prioritize_orders_by_confluence_first():
    pm = PortfolioManager(category_map={})
    sigs = [
        _risked(_signal("XYZ/USDT", score=1.5)),
        _risked(_signal("ABC/USDT", score=2.5)),
    ]
    acct = AccountState(equity_usdt=100_000, free_margin_usdt=100_000)
    instr, rejects = pm.prioritize(sigs, acct, correlation_matrix=None)
    assert len(rejects) == 0
    assert len(instr) == 2
    # Daha yüksek skor ilk
    assert instr[0].risked_order.signal.symbol == "ABC/USDT"


def test_concentration_per_symbol_cap_blocks():
    pm = PortfolioManager(max_per_symbol_pct=0.10)
    sigs = [
        _risked(_signal("BTC/USDT", 2.0), notional=15_000),  # %15 > %10 cap
    ]
    acct = AccountState(equity_usdt=100_000, free_margin_usdt=100_000)
    instr, rejects = pm.prioritize(sigs, acct)
    assert len(instr) == 0
    assert len(rejects) == 1
    assert rejects[0].reason == "per_symbol_cap"


def test_max_open_positions_caps_total():
    from price_action.contracts import Position

    pm = PortfolioManager(max_open_positions=2)
    open_pos = [
        Position(
            venue="binance",
            symbol="X1/USDT",
            side="long",
            quantity=1,
            entry_price=100,
            current_price=100,
            unrealized_pnl_usdt=0,
            realized_pnl_usdt=0,
            opened_at=datetime.now(timezone.utc),
            strategy_id="t",
            last_updated=datetime.now(timezone.utc),
        ),
        Position(
            venue="binance",
            symbol="X2/USDT",
            side="long",
            quantity=1,
            entry_price=100,
            current_price=100,
            unrealized_pnl_usdt=0,
            realized_pnl_usdt=0,
            opened_at=datetime.now(timezone.utc),
            strategy_id="t",
            last_updated=datetime.now(timezone.utc),
        ),
    ]
    sigs = [_risked(_signal("X3/USDT", 2.0))]
    acct = AccountState(
        equity_usdt=100_000, free_margin_usdt=100_000, open_positions=open_pos
    )
    instr, rejects = pm.prioritize(sigs, acct)
    assert len(instr) == 0
    assert rejects[0].reason == "max_open_positions"


def test_opposite_direction_blocked():
    from price_action.contracts import Position

    pm = PortfolioManager()
    pos = Position(
        venue="binance",
        symbol="BTC/USDT",
        side="long",
        quantity=1,
        entry_price=100,
        current_price=100,
        unrealized_pnl_usdt=0,
        realized_pnl_usdt=0,
        opened_at=datetime.now(timezone.utc),
        strategy_id="t",
        last_updated=datetime.now(timezone.utc),
    )
    sigs = [_risked(_signal("BTC/USDT", 2.0, direction="short"))]
    acct = AccountState(
        equity_usdt=100_000, free_margin_usdt=100_000, open_positions=[pos]
    )
    instr, rejects = pm.prioritize(sigs, acct)
    assert len(instr) == 0
    assert rejects[0].reason == "opposite_direction_with_existing"
