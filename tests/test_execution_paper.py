"""Paper broker round-trip testi."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from price_action.contracts import OrderInstruction, RiskedOrder, Signal, TPLevel
from price_action.execution.ccxt_paper import CCXTPaperBroker
from price_action.execution.order_manager import OrderManager
from price_action.execution.paper_state import PaperState


def _instr(symbol: str = "BTC/USDT", direction: str = "long") -> OrderInstruction:
    sig = Signal(
        ts=datetime(2024, 6, 1, tzinfo=timezone.utc),
        venue="binance",
        symbol=symbol,
        timeframe="1d",
        direction=direction,  # type: ignore[arg-type]
        pattern_id="bullish_pin_bar",
        confluence_score=2.5,
        sl_price=99.0,
        tp_price=103.0,
        suggested_size_atr=2.0,
    )
    ro = RiskedOrder(
        signal=sig,
        quantity=0.01,
        notional_usdt=1.0,
        leverage=1.0,
        sl_price=99.0,
        tp_levels=[TPLevel(price=103.0, fraction=1.0)],
        margin_used=1.0,
        risk_budget_consumed=0.01,
    )
    return OrderInstruction(risked_order=ro, priority=1.0, order_type="market")


def test_paper_broker_round_trip(tmp_path):
    state = PaperState(path=tmp_path / "paper.json", initial_balance_usdt=10_000)
    broker = CCXTPaperBroker(force_offline=True, state=state)
    fill = broker.place_order(_instr())
    assert fill is not None
    assert fill.mode == "paper"
    assert fill.quantity > 0
    positions = broker.fetch_positions()
    assert len(positions) == 1
    # Manuel kapatma
    closed = broker.close_position(positions[0], exit_price=fill.price * 1.02)
    assert closed is not None
    assert closed.symbol == "BTC/USDT"


def test_order_manager_idempotency_blocks_duplicate(tmp_path):
    state = PaperState(path=tmp_path / "paper.json", initial_balance_usdt=10_000)
    broker = CCXTPaperBroker(force_offline=True, state=state)
    om = OrderManager(broker=broker, risk_officer=None)
    inst = _instr()
    fill1 = om.submit(inst)
    assert hasattr(fill1, "order_id")  # Fill
    fill2 = om.submit(inst)
    # Aynı fingerprint — duplicate kuralı
    assert hasattr(fill2, "rejected_by")  # Reject


def test_live_broker_rejected_in_test_mode():
    """Live broker init testte exception atmalı."""
    from price_action.execution.ccxt_live import CCXTLiveBroker

    with pytest.raises(RuntimeError):
        CCXTLiveBroker(venue="binance")


@pytest.mark.live
def test_live_round_trip_skipped():
    """Gerçek borsa — CI'da skip."""
    pytest.skip("live test")


@pytest.mark.integration
def test_paper_with_real_ws_skipped():
    """Network gerektiren paper test — CI'da skip."""
    pytest.skip("integration test")
