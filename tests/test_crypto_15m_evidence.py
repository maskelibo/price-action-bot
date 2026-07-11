from __future__ import annotations

from dataclasses import fields, replace
from datetime import UTC, datetime, timedelta

import pytest

from price_action.lab.crypto_15m_event_engine import PortfolioResult, TradeLedger
from price_action.lab.crypto_15m_evidence import (
    engine_max_drawdown_pct,
    engine_monthly_returns_pct,
    equity_series,
    ledger_frame,
    scenario_window_summary,
)

T0 = datetime(2025, 1, 1, tzinfo=UTC)


def _trade(
    candidate_id: str,
    *,
    side: str = "long",
    exit_ts: datetime = T0,
    execution_cost: float = 3.0,
    funding_cashflow: float = -0.5,
    net_pnl: float = 6.5,
) -> TradeLedger:
    return TradeLedger(
        candidate_id=candidate_id,
        symbol="ETH/USDT",
        side=side,  # type: ignore[arg-type]
        decision_ts=exit_ts - timedelta(minutes=30),
        entry_ts=exit_ts - timedelta(minutes=15),
        exit_ts=exit_ts,
        exit_reason="time",
        entry_price=100.0,
        exit_price=101.0,
        stop_price=95.0,
        quantity=10.0,
        entry_notional=1_000.0,
        risk_budget=50.0,
        bars_held=1,
        gross_price_pnl=10.0,
        payoff_multiplier=1.0,
        adjusted_price_pnl=10.0,
        entry_fee=1.0,
        entry_spread_slippage=0.25,
        entry_impact=0.25,
        exit_fee=1.0,
        exit_spread_slippage=0.25,
        exit_impact=0.25,
        funding_cashflow=funding_cashflow,
        execution_cost=execution_cost,
        net_pnl=net_pnl,
        equity_before_entry=100.0,
        equity_after_exit=100.0 + net_pnl,
    )


def _result(
    *,
    curve: tuple[tuple[datetime, float], ...] = ((T0, 100.0),),
    trades: tuple[TradeLedger, ...] = (),
    monthly_returns: tuple[tuple[str, float], ...] = (("2025-01", 0.10),),
    max_drawdown: float = 0.0,
) -> PortfolioResult:
    return PortfolioResult(
        trades=trades,
        equity_curve=curve,
        monthly_returns=monthly_returns,
        rejections=(),
        initial_equity=100.0,
        final_equity=curve[-1][1] if curve else 100.0,
        max_drawdown=max_drawdown,
        total_execution_cost=sum(trade.execution_cost for trade in trades),
        accrued_exit_cost=0.0,
        total_funding_cashflow=sum(trade.funding_cashflow for trade in trades),
        open_position_count=0,
    )


def test_engine_tuple_units_are_explicitly_converted_for_validation() -> None:
    result = _result(
        curve=((T0, 100.0), (T0 + timedelta(minutes=15), 50.0)),
        monthly_returns=(("2025-01", 0.10), ("2025-02", -0.50)),
        max_drawdown=-0.50,
    )

    equity = equity_series(result)
    monthly = engine_monthly_returns_pct(result)

    assert str(equity.index.tz) == "UTC"
    assert equity.name == "equity"
    assert monthly.tolist() == pytest.approx([10.0, -50.0])
    assert monthly.attrs == {
        "source_unit": "engine_decimal",
        "output_unit": "percentage_points",
    }
    assert engine_max_drawdown_pct(result) == pytest.approx(50.0)

    with pytest.raises(ValueError, match="non-positive decimal"):
        engine_max_drawdown_pct(replace(result, max_drawdown=50.0))


def test_ledger_frame_preserves_every_tradeledger_field_and_utc_timestamps() -> None:
    trade = _trade("candidate", exit_ts=T0 + timedelta(days=1))
    frame = ledger_frame(_result(trades=(trade,)))

    assert tuple(frame.columns) == tuple(field.name for field in fields(TradeLedger))
    assert frame.loc[0, "candidate_id"] == "candidate"
    assert frame.loc[0, "execution_cost"] == pytest.approx(trade.execution_cost)
    for column in ("decision_ts", "entry_ts", "exit_ts"):
        assert str(frame[column].dt.tz) == "UTC"

    empty = ledger_frame(_result())
    assert tuple(empty.columns) == tuple(field.name for field in fields(TradeLedger))
    assert empty.empty


def test_window_summary_uses_pre_window_baseline_and_peak_and_end_is_exclusive() -> None:
    start = datetime(2025, 1, 1, tzinfo=UTC)
    end = datetime(2025, 3, 1, tzinfo=UTC)
    curve = (
        (datetime(2024, 12, 1, tzinfo=UTC), 100.0),
        (datetime(2024, 12, 31, 23, 45, tzinfo=UTC), 80.0),
        (datetime(2025, 1, 1, tzinfo=UTC), 75.0),
        (datetime(2025, 1, 15, tzinfo=UTC), 50.0),
        (datetime(2025, 1, 31, 23, 45, tzinfo=UTC), 60.0),
        (datetime(2025, 2, 28, 23, 45, tzinfo=UTC), 90.0),
        (end, 200.0),
    )
    trades = (
        _trade("jan", exit_ts=datetime(2025, 1, 31, tzinfo=UTC)),
        _trade(
            "feb",
            side="short",
            exit_ts=datetime(2025, 2, 28, tzinfo=UTC),
            execution_cost=4.0,
            funding_cashflow=0.25,
            net_pnl=5.0,
        ),
        _trade("at_end", exit_ts=end, execution_cost=99.0),
    )
    result = _result(
        curve=curve,
        trades=trades,
        monthly_returns=(("2024-12", -0.20), ("2025-01", -0.25), ("2025-02", 0.50)),
        max_drawdown=-0.50,
    )

    summary = scenario_window_summary(result, start=start, end=end)

    assert summary.baseline_equity == pytest.approx(80.0)
    assert summary.pre_window_peak_equity == pytest.approx(100.0)
    assert summary.ending_equity == pytest.approx(90.0)
    assert summary.equity_observations == 4
    assert summary.monthly_returns_pct.tolist() == pytest.approx([-25.0, 50.0])
    assert summary.monthly_returns_pct.attrs["source"] == "15m_equity_curve"
    assert summary.max_mtm_drawdown_pct == pytest.approx(50.0)
    assert (summary.max_mtm_drawdown_pct <= 15.0) is False
    assert summary.max_recovery_months == 2
    assert summary.closed_trades == 2
    assert summary.long_closed_trades == 1
    assert summary.short_closed_trades == 1
    assert summary.closed_trade_execution_cost == pytest.approx(7.0)
    assert summary.closed_trade_funding_cashflow == pytest.approx(-0.25)
    assert summary.closed_trade_net_pnl == pytest.approx(11.5)


def test_adapter_rejects_naive_boundaries_and_non_increasing_equity() -> None:
    with pytest.raises(ValueError, match="start must be timezone-aware UTC"):
        scenario_window_summary(
            _result(),
            start=datetime(2025, 1, 1),
            end=datetime(2025, 2, 1, tzinfo=UTC),
        )

    bad = _result(curve=((T0 + timedelta(minutes=15), 100.0), (T0, 99.0)))
    with pytest.raises(ValueError, match="unique and increasing"):
        equity_series(bad)
