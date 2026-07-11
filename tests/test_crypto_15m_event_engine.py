from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pandas as pd
import pytest

from price_action.lab.crypto_15m_event_engine import (
    CostModel,
    PortfolioPolicy,
    SignalIntent,
    simulate_portfolio,
)

T0 = datetime(2025, 1, 1, tzinfo=UTC)


def _frame(
    rows: list[tuple[int, float, float, float, float]],
) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "ts": T0 + timedelta(minutes=minute),
                "open": open_,
                "high": high,
                "low": low,
                "close": close,
            }
            for minute, open_, high, low, close in rows
        ]
    )


def _intent(
    *,
    decision_minute: int = 0,
    symbol: str = "BTC/USDT",
    side: str = "long",
    score: float = 1.0,
    atr: float = 10.0,
    hold_bars: int = 1,
    candidate_id: str = "candidate",
) -> SignalIntent:
    return SignalIntent(
        candidate_id=candidate_id,
        decision_ts=T0 + timedelta(minutes=decision_minute),
        symbol=symbol,
        side=side,
        score=score,
        atr=atr,
        stop_atr_multiple=1.0,
        hold_bars=hold_bars,
    )


def _policy(**overrides) -> PortfolioPolicy:
    return PortfolioPolicy(warmup_bars_after_gap=0, **overrides)


def test_default_cost_model_matches_preregistered_57_bps_round_trip() -> None:
    cost = CostModel()
    per_leg = cost.fee_bps_per_leg + cost.spread_slippage_bps_per_leg + cost.impact_bps_per_leg

    assert 2 * per_leg == pytest.approx(57.0)


def test_decision_enters_only_next_contiguous_open_and_time_exits() -> None:
    frame = _frame([(0, 90, 91, 89, 90), (15, 100, 106, 99, 105)])

    result = simulate_portfolio(
        {"BTC/USDT": frame}, [_intent(atr=20)], policy=_policy(), cost=CostModel(0, 0, 0)
    )

    trade = result.trades[0]
    assert trade.entry_ts == T0 + timedelta(minutes=15)
    assert trade.entry_price == 100
    assert trade.exit_reason == "time"
    assert trade.exit_price == 105


def test_stop_is_pessimistically_first_and_gap_through_uses_open() -> None:
    frame = _frame([(0, 100, 101, 99, 100), (15, 100, 101, 99, 100), (30, 85, 110, 80, 105)])

    result = simulate_portfolio(
        {"BTC/USDT": frame},
        [_intent(hold_bars=10)],
        policy=_policy(),
        cost=CostModel(0, 0, 0),
    )

    trade = result.trades[0]
    assert trade.exit_reason == "stop"
    assert trade.exit_price == 85
    assert trade.gross_price_pnl < 0


def test_large_data_gap_exits_at_first_open() -> None:
    frame = _frame([(0, 100, 101, 99, 100), (15, 100, 101, 99, 100), (75, 95, 96, 94, 95)])

    result = simulate_portfolio(
        {"BTC/USDT": frame},
        [_intent(atr=20, hold_bars=10)],
        policy=_policy(gap_max_minutes=30),
        cost=CostModel(0, 0, 0),
    )

    assert result.trades[0].exit_reason == "data_gap"
    assert result.trades[0].exit_price == 95


def test_execution_cost_is_charged_once_per_leg_and_kept_separate() -> None:
    frame = _frame([(0, 100, 100, 100, 100), (15, 100, 100, 100, 100)])

    result = simulate_portfolio(
        {"BTC/USDT": frame},
        [_intent(atr=1)],
        policy=_policy(),
        cost=CostModel(
            fee_bps_per_leg=10,
            spread_slippage_bps_per_leg=0,
            impact_bps_per_leg=0,
        ),
    )

    trade = result.trades[0]
    assert trade.entry_notional == pytest.approx(1_500)
    assert trade.entry_fee == pytest.approx(1.5)
    assert trade.exit_fee == pytest.approx(1.5)
    assert trade.execution_cost == pytest.approx(3.0)
    assert trade.net_pnl == pytest.approx(-3.0)
    assert result.final_equity == pytest.approx(9_997.0)


def test_open_position_mtm_accrues_hypothetical_exit_cost() -> None:
    frame = _frame([(0, 100, 100, 100, 100), (15, 100, 100, 100, 100)])

    result = simulate_portfolio(
        {"BTC/USDT": frame},
        [_intent(atr=1, hold_bars=10)],
        policy=_policy(),
        cost=CostModel(
            fee_bps_per_leg=10,
            spread_slippage_bps_per_leg=0,
            impact_bps_per_leg=0,
        ),
    )

    assert result.open_position_count == 1
    assert result.total_execution_cost == pytest.approx(1.5)
    assert result.accrued_exit_cost == pytest.approx(1.5)
    assert result.final_equity == pytest.approx(10_000 - 1.5 - 1.5)


def test_positive_funding_is_paid_by_long_and_received_by_short() -> None:
    frames = {
        "BTC/USDT": _frame(
            [(0, 100, 100, 100, 100), (15, 100, 100, 100, 100), (30, 100, 100, 100, 100)]
        ),
        "ETH/USDT": _frame(
            [(0, 100, 100, 100, 100), (15, 100, 100, 100, 100), (30, 100, 100, 100, 100)]
        ),
    }
    intents = [
        _intent(symbol="BTC/USDT", side="long", hold_bars=2),
        _intent(symbol="ETH/USDT", side="short", hold_bars=2),
    ]
    funding = [
        {"ts": T0 + timedelta(minutes=30), "symbol": "BTC/USDT", "rate": 0.01},
        {"ts": T0 + timedelta(minutes=30), "symbol": "ETH/USDT", "rate": 0.01},
    ]

    result = simulate_portfolio(
        frames, intents, funding, CostModel(0, 0, 0), _policy(max_same_side=2)
    )
    by_symbol = {trade.symbol: trade for trade in result.trades}

    assert by_symbol["BTC/USDT"].funding_cashflow < 0
    assert by_symbol["ETH/USDT"].funding_cashflow > 0
    assert result.total_funding_cashflow == pytest.approx(0.0)


def test_execution_and_funding_stress_multipliers_are_orthogonal() -> None:
    frame = _frame([(0, 100, 100, 100, 100), (15, 100, 100, 100, 100), (30, 100, 100, 100, 100)])
    funding = [{"ts": T0 + timedelta(minutes=30), "symbol": "BTC/USDT", "rate": 0.01}]

    base = simulate_portfolio(
        {"BTC/USDT": frame},
        [_intent(hold_bars=2)],
        funding,
        CostModel(0, 0, 0),
        _policy(),
    )
    doubled = simulate_portfolio(
        {"BTC/USDT": frame},
        [_intent(hold_bars=2)],
        funding,
        CostModel(0, 0, 0, funding_multiplier=2, cost_multiplier=2),
        _policy(),
    )

    assert doubled.total_funding_cashflow == pytest.approx(2 * base.total_funding_cashflow)


@pytest.mark.parametrize(
    ("close", "positive_mult", "negative_mult", "expected_adjusted"),
    [(110.0, 0.5, 1.25, 12.5), (90.0, 0.5, 1.25, -31.25)],
)
def test_haircut_multipliers_change_price_payoff_not_costs(
    close: float,
    positive_mult: float,
    negative_mult: float,
    expected_adjusted: float,
) -> None:
    frame = _frame([(0, 100, 100, 100, 100), (15, 100, max(100, close), min(100, close), close)])

    result = simulate_portfolio(
        {"BTC/USDT": frame},
        [_intent(atr=20)],
        cost=CostModel(0, 0, 0),
        policy=_policy(),
        positive_payoff_multiplier=positive_mult,
        negative_payoff_multiplier=negative_mult,
    )

    assert result.trades[0].adjusted_price_pnl == pytest.approx(expected_adjusted)


@pytest.mark.parametrize(
    ("close", "expected_unrealized"),
    [(110.0, 12.5), (90.0, -31.25)],
)
def test_haircut_multipliers_also_apply_to_open_position_mtm(
    close: float, expected_unrealized: float
) -> None:
    frame = _frame([(0, 100, 100, 100, 100), (15, 100, max(100, close), min(100, close), close)])

    result = simulate_portfolio(
        {"BTC/USDT": frame},
        [_intent(atr=20, hold_bars=10)],
        cost=CostModel(0, 0, 0),
        policy=_policy(),
        positive_payoff_multiplier=0.5,
        negative_payoff_multiplier=1.25,
    )

    assert result.open_position_count == 1
    assert result.final_equity == pytest.approx(10_000 + expected_unrealized)
    assert result.equity_curve[-1][1] == pytest.approx(result.final_equity)


def test_common_compounding_equity_and_dd_throttle_reduce_next_risk() -> None:
    frame = _frame(
        [
            (0, 100, 100, 100, 100),
            (15, 100, 100, 90, 90),
            (30, 100, 100, 100, 100),
            (45, 100, 100, 100, 100),
        ]
    )
    intents = [
        _intent(decision_minute=0, atr=10, candidate_id="same-cell"),
        _intent(decision_minute=30, atr=10, candidate_id="same-cell"),
    ]

    result = simulate_portfolio(
        {"BTC/USDT": frame},
        intents,
        cost=CostModel(0, 0, 0),
        policy=_policy(
            risk_per_trade=0.01,
            max_symbol_notional_pct=1.0,
            dd_throttle_threshold=0.005,
            dd_throttle_multiplier=0.5,
        ),
    )

    assert len(result.trades) == 2
    assert result.trades[0].net_pnl == pytest.approx(-100)
    assert result.trades[1].risk_budget == pytest.approx(49.5)


def test_deterministic_score_priority_and_one_position_per_symbol() -> None:
    frame = _frame([(0, 100, 100, 100, 100), (15, 100, 100, 100, 100)])
    intents = [
        _intent(score=0.1, candidate_id="low", atr=20),
        _intent(score=0.9, candidate_id="high", atr=20),
    ]

    result = simulate_portfolio(
        {"BTC/USDT": frame}, intents, cost=CostModel(0, 0, 0), policy=_policy()
    )

    assert [trade.candidate_id for trade in result.trades] == ["high"]
    assert ("low", "symbol_already_open") in result.rejections


def test_warmup_rejects_signal_immediately_after_gap() -> None:
    frame = _frame([(0, 100, 100, 100, 100), (60, 100, 100, 100, 100), (75, 100, 100, 100, 100)])

    result = simulate_portfolio(
        {"BTC/USDT": frame},
        [_intent(decision_minute=60)],
        cost=CostModel(0, 0, 0),
        policy=PortfolioPolicy(warmup_bars_after_gap=3),
    )

    assert result.trades == ()
    assert result.rejections == (("candidate", "warmup_incomplete"),)


def test_final_bar_of_month_is_not_shifted_into_following_month() -> None:
    month_end = datetime(2025, 1, 31, 23, 30, tzinfo=UTC)
    frame = pd.DataFrame(
        [
            {"ts": month_end, "open": 100, "high": 100, "low": 100, "close": 100},
            {
                "ts": month_end + timedelta(minutes=15),
                "open": 100,
                "high": 110,
                "low": 100,
                "close": 110,
            },
        ]
    )
    intent = SignalIntent(
        candidate_id="month-end",
        decision_ts=month_end,
        symbol="BTC/USDT",
        side="long",
        score=1,
        atr=20,
        stop_atr_multiple=1,
        hold_bars=1,
    )

    result = simulate_portfolio(
        {"BTC/USDT": frame}, [intent], cost=CostModel(0, 0, 0), policy=_policy()
    )

    assert [month for month, _ in result.monthly_returns] == ["2025-01"]
    assert result.monthly_returns[0][1] == pytest.approx(0.0025)
