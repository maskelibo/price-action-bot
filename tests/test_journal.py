"""Journal smoke testi — SQLite-file fallback üstünde."""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from price_action.contracts import Fill, Position, Signal, TradeRecord


def _make_trade(i: int = 0) -> TradeRecord:
    return TradeRecord(
        trade_id=f"T{i:04d}",
        venue="binance",
        symbol="BTCUSDT",
        side="long",
        entry_ts=datetime(2024, 1, 1) + timedelta(days=i),
        exit_ts=datetime(2024, 1, 2) + timedelta(days=i),
        entry_price=30000.0,
        exit_price=30500.0,
        quantity=0.01,
        realized_pnl_usdt=5.0,
        realized_r_multiple=0.5,
        fees_usdt=0.5,
        slippage_bps=3.0,
        strategy_id="classic_pa",
        pattern_id="bullish_pin_bar",
        confluence_score=2.0,
        initial_sl=29900.0,
        initial_tp=30900.0,
        mae_pct=0.005,
        mfe_pct=0.012,
    )


def test_record_and_query_trade(in_memory_journal):
    j = in_memory_journal
    j.record_trade(_make_trade(1))
    j.record_trade(_make_trade(2))
    df = j.query_trades(limit=10)
    assert len(df) == 2
    assert set(df["trade_id"].tolist()) == {"T0001", "T0002"}


def test_record_trade_idempotent(in_memory_journal):
    j = in_memory_journal
    t = _make_trade(99)
    j.record_trade(t)
    j.record_trade(t)  # duplicate id → merge
    df = j.query_trades()
    assert len(df) == 1


def test_record_fill_and_query(in_memory_journal):
    j = in_memory_journal
    f = Fill(
        order_id="O1",
        venue="binance",
        symbol="ETHUSDT",
        side="short",
        price=2000.0,
        quantity=0.5,
        fee_usdt=0.3,
        timestamp=datetime(2024, 5, 1, 12, 0),
        is_maker=False,
        expected_price=2001.0,
        slippage_bps=5.0,
        mode="paper",
    )
    j.record_fill(f)
    df = j.query_fills(limit=10)
    assert len(df) == 1
    assert df["order_id"].iloc[0] == "O1"


def test_record_signal_and_query(in_memory_journal):
    j = in_memory_journal
    s = Signal(
        ts=datetime(2024, 6, 1),
        venue="binance",
        symbol="SOLUSDT",
        timeframe="1d",
        direction="long",
        pattern_id="bullish_engulfing",
        confluence_score=2.5,
        sl_price=140.0,
        tp_price=160.0,
        suggested_size_atr=2.0,
    )
    j.record_signal(s)
    df = j.query_pending_signals()
    assert len(df) == 1


def test_upsert_and_query_position(in_memory_journal):
    j = in_memory_journal
    p = Position(
        venue="binance",
        symbol="BTCUSDT",
        side="long",
        quantity=0.05,
        entry_price=30000.0,
        current_price=30500.0,
        unrealized_pnl_usdt=25.0,
        realized_pnl_usdt=0.0,
        sl_price=29800.0,
        tp_price=31500.0,
        opened_at=datetime(2024, 7, 1),
        strategy_id="classic_pa",
        last_updated=datetime(2024, 7, 2),
    )
    j.upsert_position(p)
    # update path
    p2 = p.model_copy(update={"current_price": 31000.0, "unrealized_pnl_usdt": 50.0,
                              "last_updated": datetime(2024, 7, 3)})
    j.upsert_position(p2)
    df = j.query_open_positions()
    assert len(df) == 1
    assert df["current_price"].iloc[0] == pytest.approx(31000.0)


def test_journal_healthcheck(in_memory_journal):
    assert in_memory_journal.healthcheck() is True
