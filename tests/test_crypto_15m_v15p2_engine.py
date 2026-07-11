from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta

import numpy as np
import pandas as pd
import pytest

from price_action.lab.crypto_15m_v15p2_engine import (
    EXPECTED_CONFIG_SHA256,
    EXPECTED_MANIFEST_HASHES,
    FAIR_BASELINE_CANDIDATE_ID,
    V15P2CostScenario,
    V15P2PortfolioPolicy,
    simulate_v15p2_portfolio,
)


@dataclass(frozen=True)
class Intent:
    candidate_id: str
    decision_ts: datetime
    entry_ts: datetime
    symbol: str
    side: str
    strategy: str = "vsa_climax_test"
    strategy_rank: int = 0
    pattern_id: str = "VSA_TEST"
    confluence_score: float = 0.50
    decision_close: float = 100.0
    entry_reference_price: float = 100.0
    entry_price: float = 100.0
    stop_price: float = 97.0
    take_profit_price: float = 106.0
    decision_stop_distance_pct: float = 0.03
    entry_stop_distance_pct: float = 0.03
    suggested_size_atr: float = 1.0
    signal_manifest_hash: str = EXPECTED_MANIFEST_HASHES["vsa_climax_test"]
    config_sha256: str = EXPECTED_CONFIG_SHA256


T0 = datetime(2025, 1, 1, tzinfo=UTC)


def frame(rows: list[tuple[datetime, float, float, float, float]]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=["ts", "open", "high", "low", "close"])


def return_history(symbols: list[str], *, periods: int = 90) -> pd.DataFrame:
    rng = np.random.default_rng(20260711)
    index = pd.date_range(end=T0 - timedelta(days=1), periods=periods, freq="D", tz="UTC")
    return pd.DataFrame(
        rng.normal(0.0, 0.01, size=(periods, len(symbols))),
        index=index,
        columns=symbols,
    )


def intent(
    symbol: str,
    decision_ts: datetime = T0,
    *,
    side: str = "long",
    entry: float = 100.0,
    decision_close: float | None = None,
    stop: float = 97.0,
) -> Intent:
    decision = entry if decision_close is None else decision_close
    decision_stop_pct = abs(decision - stop) / decision
    entry_stop_pct = abs(entry - stop) / entry
    return Intent(
        candidate_id=FAIR_BASELINE_CANDIDATE_ID,
        decision_ts=decision_ts,
        entry_ts=decision_ts + timedelta(minutes=15),
        symbol=symbol,
        side=side,
        decision_close=decision,
        entry_reference_price=decision,
        entry_price=entry,
        stop_price=stop,
        take_profit_price=entry + (6.0 if side == "long" else -6.0),
        decision_stop_distance_pct=decision_stop_pct,
        entry_stop_distance_pct=entry_stop_pct,
    )


def test_protective_stop_preempts_targets_on_collision() -> None:
    bars = frame(
        [
            (T0, 100.0, 101.0, 99.0, 100.0),
            (T0 + timedelta(minutes=15), 100.0, 105.0, 96.0, 104.0),
        ]
    )
    result = simulate_v15p2_portfolio({"ETH/USDT": bars}, [intent("ETH/USDT")])
    haircut = simulate_v15p2_portfolio({"ETH/USDT": bars}, [intent("ETH/USDT")], scenario="H")

    assert [fill.reason for fill in result.exit_fills] == ["initial_stop"]
    assert result.exit_fills[0].price == 97.0
    assert result.closed_episodes[0].final_exit_reason == "initial_stop"
    assert haircut.exit_fills[0].adjusted_price_pnl == pytest.approx(
        result.exit_fills[0].gross_price_pnl * 1.25
    )


def test_gap_forces_exit_at_first_tradable_open() -> None:
    bars = frame(
        [
            (T0, 100.0, 101.0, 99.0, 100.0),
            (T0 + timedelta(minutes=15), 100.0, 101.0, 99.0, 100.0),
            (T0 + timedelta(minutes=60), 95.0, 96.0, 94.0, 95.0),
        ]
    )
    result = simulate_v15p2_portfolio({"ETH/USDT": bars}, [intent("ETH/USDT")])

    assert result.closed_episodes[0].final_exit_reason == "data_gap"
    assert result.exit_fills[-1].price == 95.0


def test_partial_fills_charge_actual_notional_and_h_haircuts_price_pnl_only() -> None:
    bars = frame(
        [
            (T0, 100.0, 101.0, 99.0, 100.0),
            (T0 + timedelta(minutes=15), 100.0, 104.6, 99.0, 104.0),
        ]
    )
    baseline = simulate_v15p2_portfolio({"ETH/USDT": bars}, [intent("ETH/USDT")], scenario="B")
    haircut = simulate_v15p2_portfolio({"ETH/USDT": bars}, [intent("ETH/USDT")], scenario="H")

    assert [fill.reason for fill in baseline.exit_fills] == ["tp1", "tp2"]
    assert sum(fill.quantity for fill in baseline.exit_fills) == pytest.approx(
        baseline.entries[0].original_quantity * 0.60
    )
    for b_fill, h_fill in zip(baseline.exit_fills, haircut.exit_fills, strict=True):
        assert h_fill.adjusted_price_pnl == pytest.approx(b_fill.gross_price_pnl * 0.5)
        assert h_fill.exit_execution_cost == pytest.approx(b_fill.exit_execution_cost)
    expected_charged = baseline.entries[0].execution_cost + sum(
        fill.exit_execution_cost for fill in baseline.exit_fills
    )
    assert baseline.total_execution_cost_charged == pytest.approx(expected_charged)
    assert len(baseline.terminal_positions) == 1
    assert baseline.closed_episodes == ()


def test_funding_uses_remaining_notional_and_c2_doubles_once() -> None:
    bars = frame(
        [
            (T0, 100.0, 101.0, 99.0, 100.0),
            (T0 + timedelta(minutes=15), 100.0, 101.0, 99.0, 100.0),
            (T0 + timedelta(minutes=30), 100.0, 101.0, 99.0, 100.0),
        ]
    )
    funding = [
        {
            "ts": T0 + timedelta(minutes=30),
            "symbol": "ETH/USDT",
            "rate": 0.01,
            "mark_price": 100.0,
        }
    ]
    base = simulate_v15p2_portfolio({"ETH/USDT": bars}, [intent("ETH/USDT")], funding)
    c2 = simulate_v15p2_portfolio({"ETH/USDT": bars}, [intent("ETH/USDT")], funding, scenario="C2")

    expected = -base.entries[0].original_quantity * 100.0 * 0.01
    assert base.total_funding_cashflow == pytest.approx(expected)
    assert c2.total_funding_cashflow == pytest.approx(expected * 2.0)
    assert c2.funding_events[0].multiplier == 2.0


def test_sizing_uses_current_wallet_and_symbol_cap() -> None:
    eth = frame(
        [
            (T0, 100.0, 101.0, 99.0, 100.0),
            (T0 + timedelta(minutes=15), 100.0, 101.0, 97.5, 100.0),
        ]
    )
    sol = eth.copy()
    signals = [
        intent("ETH/USDT", stop=97.5),
        intent("SOL/USDT", stop=97.5),
    ]
    result = simulate_v15p2_portfolio(
        {"ETH/USDT": eth, "SOL/USDT": sol},
        signals,
        daily_returns=return_history(["ETH/USDT", "SOL/USDT"]),
    )

    first, second = result.risk_decisions
    assert first.accepted_notional == pytest.approx(1_500.0)
    assert "max_symbol_notional" in first.cap_bindings
    assert second.wallet_before_entry < first.wallet_before_entry
    assert second.base_risk_budget == pytest.approx(second.wallet_before_entry * 0.01)
    assert second.accepted_notional == pytest.approx(second.wallet_before_entry * 0.15)


def test_dd_peak_observes_wallet_only_when_an_intent_reaches_sizing() -> None:
    rows = [
        (T0, 100.0, 101.0, 99.0, 100.0),
        (T0 + timedelta(minutes=15), 100.0, 101.0, 99.0, 100.0),
        (T0 + timedelta(minutes=30), 100.0, 101.0, 99.0, 100.0),
        (T0 + timedelta(minutes=45), 100.0, 101.0, 99.0, 100.0),
    ]
    result = simulate_v15p2_portfolio(
        {"ETH/USDT": frame(rows), "SOL/USDT": frame(rows[2:])},
        [intent("ETH/USDT"), intent("SOL/USDT", T0 + timedelta(minutes=30))],
        funding_events=[
            {
                "ts": T0 + timedelta(minutes=30),
                "symbol": "ETH/USDT",
                "rate": -0.20,
                "mark_price": 100.0,
            },
            {
                "ts": T0 + timedelta(minutes=45),
                "symbol": "ETH/USDT",
                "rate": 0.20,
                "mark_price": 100.0,
            },
        ],
        daily_returns=return_history(["ETH/USDT", "SOL/USDT"]),
        policy=V15P2PortfolioPolicy(dd_throttle_threshold=0.01),
    )

    second = next(item for item in result.risk_decisions if item.symbol == "SOL/USDT")
    assert second.wallet_peak == pytest.approx(10_000.0)
    assert second.drawdown_factor == 1.0


def test_correlation_is_strictly_causal_and_hard_blocks_second_symbol() -> None:
    bars = frame(
        [
            (T0, 100.0, 101.0, 99.0, 100.0),
            (T0 + timedelta(minutes=15), 100.0, 101.0, 99.0, 100.0),
        ]
    )
    index = pd.date_range(end=T0 - timedelta(days=1), periods=90, freq="D", tz="UTC")
    values = [float(index_) / 100.0 for index_ in range(90)]
    returns = pd.DataFrame({"AAA": values, "BBB": values}, index=index)
    # A future value must never enter the entry-time correlation window.
    returns.loc[pd.Timestamp(T0 + timedelta(days=1)), :] = [1000.0, -1000.0]
    result = simulate_v15p2_portfolio(
        {"AAA": bars, "BBB": bars.copy()},
        [intent("AAA"), intent("BBB")],
        daily_returns=returns,
    )

    assert [entry.symbol for entry in result.entries] == ["AAA"]
    assert any(
        rejection.symbol == "BBB" and rejection.reason == "correlation_hard_block"
        for rejection in result.rejections
    )


def test_daily_breaker_blocks_next_bar_entry() -> None:
    eth = frame(
        [
            (T0, 100.0, 101.0, 99.0, 100.0),
            (T0 + timedelta(minutes=15), 100.0, 101.0, 96.0, 97.0),
            (T0 + timedelta(minutes=30), 97.0, 98.0, 96.0, 97.0),
        ]
    )
    sol = frame(
        [
            (T0, 100.0, 101.0, 99.0, 100.0),
            (T0 + timedelta(minutes=15), 100.0, 101.0, 99.0, 100.0),
            (T0 + timedelta(minutes=30), 100.0, 101.0, 99.0, 100.0),
        ]
    )
    policy = V15P2PortfolioPolicy(daily_loss_pct=0.001)
    result = simulate_v15p2_portfolio(
        {"ETH/USDT": eth, "SOL/USDT": sol},
        [intent("ETH/USDT"), intent("SOL/USDT", T0 + timedelta(minutes=15))],
        policy=policy,
    )

    assert any(
        transition.breaker == "daily" and transition.action == "activated"
        for transition in result.breaker_transitions
    )
    assert any(
        rejection.symbol == "SOL/USDT" and rejection.reason == "breaker_daily"
        for rejection in result.rejections
    )


def test_trail_calculated_from_completed_bar_is_effective_next_bar_only() -> None:
    bars = frame(
        [
            (T0, 100.0, 101.0, 99.0, 100.0),
            # Low is below the newly-calculated trail, but above the old stop.
            (T0 + timedelta(minutes=15), 100.0, 103.0, 99.0, 102.0),
            (T0 + timedelta(minutes=30), 102.0, 102.5, 101.0, 101.5),
        ]
    )
    result = simulate_v15p2_portfolio({"ETH/USDT": bars}, [intent("ETH/USDT")])

    assert result.exit_fills[0].reason == "tp1"
    assert result.stop_transitions[0].calculated_ts == T0 + timedelta(minutes=15)
    assert result.stop_transitions[0].effective_ts == T0 + timedelta(minutes=30)
    assert result.exit_fills[-1].reason == "trailing_stop"
    assert result.exit_fills[-1].ts == T0 + timedelta(minutes=30)


def test_runner_time_stop_fills_next_open_after_thirty_completed_bars() -> None:
    rows = [(T0, 100.0, 101.0, 99.0, 100.0)]
    # Entry/TP1 bar, followed by exactly 30 completed runner bars and one fill bar.
    rows.append((T0 + timedelta(minutes=15), 100.0, 103.0, 99.0, 102.0))
    for offset in range(2, 32):
        rows.append(
            (
                T0 + timedelta(minutes=15 * offset),
                102.0,
                102.8,
                102.0,
                102.4,
            )
        )
    rows.append((T0 + timedelta(minutes=15 * 32), 102.25, 102.5, 102.0, 102.2))

    result = simulate_v15p2_portfolio(
        {"ETH/USDT": frame(rows)},
        [intent("ETH/USDT")],
    )

    assert result.exit_fills[-1].reason == "runner_time_stop"
    assert result.exit_fills[-1].ts == T0 + timedelta(minutes=15 * 32)
    assert result.exit_fills[-1].price == 102.25


def test_entry_requires_exact_next_bar_and_matching_decision_close() -> None:
    bars = frame(
        [
            (T0, 100.0, 101.0, 99.0, 101.0),
            (T0 + timedelta(minutes=30), 100.0, 101.0, 99.0, 100.0),
        ]
    )
    result = simulate_v15p2_portfolio({"ETH/USDT": bars}, [intent("ETH/USDT")])

    assert result.entries == ()
    assert result.rejections[0].reason == "entry_bar_not_contiguous"


def test_next_open_beyond_stop_is_rejected_by_repaired_live_risk_rule() -> None:
    bars = frame(
        [
            (T0, 100.0, 101.0, 99.0, 100.0),
            (T0 + timedelta(minutes=15), 95.0, 96.0, 94.0, 95.0),
        ]
    )
    signal = intent(
        "ETH/USDT",
        entry=95.0,
        decision_close=100.0,
        stop=97.0,
    )

    result = simulate_v15p2_portfolio({"ETH/USDT": bars}, [signal])

    assert result.entries == ()
    assert result.total_execution_cost_charged == 0.0
    assert result.rejections[0].reason == "stop_on_wrong_side"


@pytest.mark.parametrize(
    "bad_kind",
    ["only_89_rows", "one_missing_value", "missing_calendar_day_but_90_rows"],
)
def test_correlation_requires_full_finite_90_for_every_open_symbol(bad_kind: str) -> None:
    bars = frame(
        [
            (T0, 100.0, 101.0, 99.0, 100.0),
            (T0 + timedelta(minutes=15), 100.0, 101.0, 99.0, 100.0),
        ]
    )
    periods = 91 if bad_kind == "missing_calendar_day_but_90_rows" else 90
    if bad_kind == "only_89_rows":
        periods = 89
    returns = return_history(["AAA", "BBB"], periods=periods)
    if bad_kind == "one_missing_value":
        returns.loc[returns.index[-1], "BBB"] = np.nan
    elif bad_kind == "missing_calendar_day_but_90_rows":
        # There are still 90 finite rows, but one of the exact trailing 90 UTC
        # dates is absent and an older date must never substitute for it.
        returns = returns.drop(index=returns.index[-10])

    result = simulate_v15p2_portfolio(
        {"AAA": bars, "BBB": bars.copy()},
        [intent("AAA"), intent("BBB")],
        daily_returns=returns,
    )

    assert [entry.symbol for entry in result.entries] == ["AAA"]
    rejection = next(item for item in result.rejections if item.symbol == "BBB")
    assert rejection.reason == "correlation_history_unavailable"
    assert "pair_history" in rejection.detail


def test_one_x_margin_gate_accepts_six_and_rejects_seventh_pre_correlation() -> None:
    symbols = [f"S{index}" for index in range(7)]
    bars = frame(
        [
            (T0, 100.0, 101.0, 99.0, 100.0),
            (T0 + timedelta(minutes=15), 100.0, 101.0, 99.0, 100.0),
        ]
    )
    policy = V15P2PortfolioPolicy(max_open_positions=10, max_same_side_positions=10)
    result = simulate_v15p2_portfolio(
        {symbol: bars.copy() for symbol in symbols},
        [intent(symbol, stop=97.5) for symbol in symbols],
        daily_returns=return_history(symbols),
        policy=policy,
    )

    assert len(result.entries) == 6
    assert all(decision.dynamic_leverage == 1.0 for decision in result.risk_decisions)
    seventh = next(item for item in result.rejections if item.symbol == "S6")
    assert seventh.reason == "initial_margin_buffer"


def test_correlation_reduction_is_last_and_ledgers_fifteen_to_seven_point_five() -> None:
    bars = frame(
        [
            (T0, 100.0, 101.0, 99.0, 100.0),
            (T0 + timedelta(minutes=15), 100.0, 101.0, 99.0, 100.0),
        ]
    )
    rng = np.random.default_rng(77)
    first = rng.normal(size=90)
    orthogonal = rng.normal(size=90)
    orthogonal -= first * float(np.dot(first, orthogonal) / np.dot(first, first))
    first /= float(np.std(first))
    orthogonal /= float(np.std(orthogonal))
    second = 0.8 * first + 0.6 * orthogonal
    index = pd.date_range(end=T0 - timedelta(days=1), periods=90, freq="D", tz="UTC")
    returns = pd.DataFrame({"AAA": first, "BBB": second}, index=index)

    result = simulate_v15p2_portfolio(
        {"AAA": bars, "BBB": bars.copy()},
        [intent("AAA", stop=97.5), intent("BBB", stop=97.5)],
        daily_returns=returns,
    )

    second_decision = next(item for item in result.risk_decisions if item.symbol == "BBB")
    assert 0.7 < (second_decision.maximum_observed_correlation or 0.0) < 0.9
    assert second_decision.pre_correlation_notional == pytest.approx(
        second_decision.wallet_before_entry * 0.15
    )
    assert second_decision.post_correlation_notional == pytest.approx(
        second_decision.pre_correlation_notional * 0.5
    )
    assert second_decision.accepted_notional == pytest.approx(
        second_decision.post_correlation_notional
    )
    assert second_decision.required_initial_margin == pytest.approx(
        second_decision.pre_correlation_notional
    )
    assert second_decision.dynamic_leverage == 1.0


def test_open_gap_stop_trips_breaker_before_same_timestamp_reentry() -> None:
    bars = frame(
        [
            (T0, 100.0, 101.0, 99.0, 100.0),
            (T0 + timedelta(minutes=15), 100.0, 101.0, 99.0, 100.0),
            (T0 + timedelta(minutes=30), 90.0, 91.0, 89.0, 90.0),
        ]
    )
    first = intent("ETH/USDT")
    reentry = intent(
        "ETH/USDT",
        T0 + timedelta(minutes=15),
        entry=90.0,
        decision_close=100.0,
        stop=87.0,
    )
    result = simulate_v15p2_portfolio(
        {"ETH/USDT": bars},
        [first, reentry],
        policy=V15P2PortfolioPolicy(daily_loss_pct=0.001),
    )

    assert result.exit_fills[-1].ts == T0 + timedelta(minutes=30)
    assert result.exit_fills[-1].price == 90.0
    assert result.exit_fills[-1].reason == "initial_stop"
    assert any(
        item.breaker == "daily" and item.action == "activated"
        for item in result.breaker_transitions
    )
    assert any(
        item.entry_ts == T0 + timedelta(minutes=30) and item.reason == "breaker_daily"
        for item in result.rejections
    )


def test_widestop_uses_decision_distance_while_entry_gap_distance_sizes_only() -> None:
    narrow_at_decision = frame(
        [
            (T0, 100.0, 101.0, 99.0, 100.0),
            (T0 + timedelta(minutes=15), 110.0, 111.0, 109.0, 110.0),
        ]
    )
    wide_at_decision = frame(
        [
            (T0, 100.0, 101.0, 99.0, 100.0),
            (T0 + timedelta(minutes=15), 98.0, 99.0, 97.5, 98.0),
        ]
    )
    result = simulate_v15p2_portfolio(
        {"NARROW_DECISION": narrow_at_decision, "WIDE_DECISION": wide_at_decision},
        [
            intent(
                "NARROW_DECISION",
                entry=110.0,
                decision_close=100.0,
                stop=98.0,
            ),
            intent(
                "WIDE_DECISION",
                entry=98.0,
                decision_close=100.0,
                stop=97.0,
            ),
        ],
    )

    assert [entry.symbol for entry in result.entries] == ["WIDE_DECISION"]
    assert any(
        item.symbol == "NARROW_DECISION" and item.reason == "decision_stop_distance_below_minimum"
        for item in result.rejections
    )
    decision = result.risk_decisions[0]
    assert decision.stop_normalizer_factor == pytest.approx(0.01 / (1.0 / 98.0))


def test_final_journal_reconciles_costs_and_funding_and_drives_consecutive() -> None:
    eth = frame(
        [
            (T0, 100.0, 101.0, 99.0, 100.0),
            (T0 + timedelta(minutes=15), 100.0, 103.2, 99.0, 100.0),
            (T0 + timedelta(minutes=30), 100.0, 101.0, 99.0, 100.0),
        ]
    )
    sol = frame(
        [
            (T0 + timedelta(minutes=15), 100.0, 101.0, 99.0, 100.0),
            (T0 + timedelta(minutes=30), 100.0, 101.0, 99.0, 100.0),
        ]
    )
    funding = [
        {
            "ts": T0 + timedelta(minutes=30),
            "symbol": "ETH/USDT",
            "rate": 0.001,
            "mark_price": 100.0,
        }
    ]
    result = simulate_v15p2_portfolio(
        {"ETH/USDT": eth, "SOL/USDT": sol},
        [intent("ETH/USDT"), intent("SOL/USDT", T0 + timedelta(minutes=15))],
        funding,
        policy=V15P2PortfolioPolicy(consecutive_loss_count=1),
    )

    partial, final = result.journal_rows
    episode = result.closed_episodes[0]
    assert partial.is_final is False
    assert partial.amount == pytest.approx(result.exit_fills[0].adjusted_price_pnl)
    assert final.is_final is True
    assert final.amount == pytest.approx(episode.net_pnl - partial.amount)
    assert final.cumulative_episode_journal_amount == pytest.approx(episode.net_pnl)
    assert final.episode_scenario_net_if_final == pytest.approx(episode.net_pnl)
    assert episode.funding_cashflow == pytest.approx(result.total_funding_cashflow)
    assert episode.net_pnl > 0.0
    assert final.amount < 0.0
    assert any(item.breaker == "consecutive" for item in result.breaker_transitions)
    assert any(
        item.symbol == "SOL/USDT" and item.reason == "breaker_consecutive"
        for item in result.rejections
    )


def test_consecutive_loss_streak_uses_live_30_day_journal_lookback() -> None:
    later = T0 + timedelta(days=32)
    loss_rows = [
        (T0, 100.0, 101.0, 99.0, 100.0),
        (T0 + timedelta(minutes=15), 100.0, 101.0, 99.0, 100.0),
        (T0 + timedelta(minutes=30), 97.0, 98.0, 96.0, 97.0),
    ]
    later_loss_rows = [
        (later, 100.0, 101.0, 99.0, 100.0),
        (later + timedelta(minutes=15), 100.0, 101.0, 99.0, 100.0),
        (later + timedelta(minutes=30), 97.0, 98.0, 96.0, 97.0),
    ]
    resumed_rows = [
        (later + timedelta(minutes=15), 100.0, 101.0, 99.0, 100.0),
        (later + timedelta(minutes=30), 100.0, 101.0, 99.0, 100.0),
    ]
    result = simulate_v15p2_portfolio(
        {
            "A_OLD_LOSS": frame(loss_rows),
            "B_NEW_LOSS": frame(later_loss_rows),
            "C_RESUMED": frame(resumed_rows),
        },
        [
            intent("A_OLD_LOSS"),
            intent("B_NEW_LOSS", later),
            intent("C_RESUMED", later + timedelta(minutes=15)),
        ],
        policy=V15P2PortfolioPolicy(consecutive_loss_count=2),
    )

    assert not any(item.breaker == "consecutive" for item in result.breaker_transitions)
    assert any(entry.symbol == "C_RESUMED" for entry in result.entries)


def test_combined_breaker_remains_blocking_when_breach_outlives_first_cooldown() -> None:
    eth = frame(
        [
            (T0, 100.0, 101.0, 99.0, 100.0),
            (T0 + timedelta(minutes=15), 100.0, 101.0, 99.0, 100.0),
            (T0 + timedelta(minutes=30), 97.5, 98.0, 96.5, 97.5),
            (T0 + timedelta(minutes=45), 97.5, 98.0, 97.4, 97.5),
        ]
    )
    sol = frame(
        [
            (T0 + timedelta(minutes=30), 100.0, 101.0, 99.0, 100.0),
            (T0 + timedelta(minutes=45), 100.0, 101.0, 99.0, 100.0),
        ]
    )
    result = simulate_v15p2_portfolio(
        {"ETH/USDT": eth, "SOL/USDT": sol},
        [intent("ETH/USDT"), intent("SOL/USDT", T0 + timedelta(minutes=30))],
        policy=V15P2PortfolioPolicy(weekly_loss_pct=0.001, weekly_halt_days=0.01),
    )

    activated = next(
        item
        for item in result.breaker_transitions
        if item.breaker == "weekly" and item.action == "activated"
    )
    assert activated.blocked_until is not None
    assert activated.blocked_until < T0 + timedelta(minutes=45)
    assert any(
        item.symbol == "SOL/USDT" and item.reason == "breaker_weekly" for item in result.rejections
    )


def test_combined_breaker_uses_one_daily_first_clock_then_weekly_on_reset() -> None:
    next_day = T0 + timedelta(days=1)
    eth = frame(
        [
            (T0, 100.0, 101.0, 99.0, 100.0),
            (T0 + timedelta(minutes=15), 100.0, 101.0, 99.0, 100.0),
            (T0 + timedelta(minutes=30), 97.0, 98.0, 96.0, 97.0),
            (next_day, 97.0, 98.0, 96.0, 97.0),
        ]
    )
    result = simulate_v15p2_portfolio(
        {"ETH/USDT": eth},
        [intent("ETH/USDT")],
        policy=V15P2PortfolioPolicy(daily_loss_pct=0.001, weekly_loss_pct=0.001),
    )

    activated = [item for item in result.breaker_transitions if item.action == "activated"]
    first_daily = next(item for item in activated if item.breaker == "daily")
    first_weekly = next(item for item in activated if item.breaker == "weekly")
    assert first_daily.ts == T0 + timedelta(minutes=30)
    assert not any(item.breaker == "weekly" and item.ts == first_daily.ts for item in activated)
    assert first_weekly.ts == next_day


def test_combined_clock_carries_after_daily_flag_resets_then_expires_once() -> None:
    loss_decision = datetime(2025, 1, 1, 23, tzinfo=UTC)
    loss_entry = loss_decision + timedelta(minutes=15)
    loss_exit = loss_decision + timedelta(minutes=30)
    carry_decision = loss_decision + timedelta(minutes=45)
    boundary = datetime(2025, 1, 2, tzinfo=UTC)
    resume_entry = boundary + timedelta(minutes=15)
    loss = frame(
        [
            (loss_decision, 100.0, 101.0, 99.0, 100.0),
            (loss_entry, 100.0, 101.0, 99.0, 100.0),
            (loss_exit, 97.0, 98.0, 96.0, 97.0),
        ]
    )
    blocked = frame(
        [
            (carry_decision, 100.0, 101.0, 99.0, 100.0),
            (boundary, 100.0, 101.0, 99.0, 100.0),
        ]
    )
    resumed = frame(
        [
            (boundary, 100.0, 101.0, 99.0, 100.0),
            (resume_entry, 100.0, 101.0, 99.0, 100.0),
        ]
    )
    result = simulate_v15p2_portfolio(
        {"A_LOSS": loss, "B_BLOCKED": blocked, "C_RESUMED": resumed},
        [
            intent("A_LOSS", loss_decision),
            intent("B_BLOCKED", carry_decision),
            intent("C_RESUMED", boundary),
        ],
        policy=V15P2PortfolioPolicy(
            daily_loss_pct=0.001,
            daily_halt_days=0.02,
            weekly_loss_pct=0.99,
            monthly_combined_loss_pct=0.99,
        ),
    )

    assert any(
        item.symbol == "B_BLOCKED" and item.reason == "breaker_daily" for item in result.rejections
    )
    expirations = [
        item
        for item in result.breaker_transitions
        if item.breaker == "daily" and item.action == "expired"
    ]
    assert len(expirations) == 1
    assert expirations[0].ts == resume_entry
    assert [entry.symbol for entry in result.entries] == ["A_LOSS", "C_RESUMED"]


def test_midnight_funding_is_included_in_new_month_anchor_before_entry_gate() -> None:
    boundary = datetime(2025, 2, 1, tzinfo=UTC)
    decision_first = boundary - timedelta(minutes=30)
    decision_second = boundary - timedelta(minutes=15)
    eth = frame(
        [
            (decision_first, 100.0, 101.0, 99.0, 100.0),
            (decision_second, 100.0, 101.0, 99.0, 100.0),
            (boundary, 100.0, 101.0, 99.0, 100.0),
        ]
    )
    sol = frame(
        [
            (decision_second, 100.0, 101.0, 99.0, 100.0),
            (boundary, 100.0, 101.0, 99.0, 100.0),
        ]
    )
    index = pd.date_range(end=boundary - timedelta(days=1), periods=90, freq="D", tz="UTC")
    rng = np.random.default_rng(919)
    returns = pd.DataFrame(
        rng.normal(0.0, 0.01, size=(90, 2)),
        index=index,
        columns=["ETH/USDT", "SOL/USDT"],
    )
    result = simulate_v15p2_portfolio(
        {"ETH/USDT": eth, "SOL/USDT": sol},
        [intent("ETH/USDT", decision_first), intent("SOL/USDT", decision_second)],
        funding_events=[
            {
                "ts": boundary,
                "symbol": "ETH/USDT",
                "rate": 0.05,
                "mark_price": 100.0,
            }
        ],
        daily_returns=returns,
        policy=V15P2PortfolioPolicy(
            daily_loss_pct=0.99,
            weekly_loss_pct=0.99,
            monthly_combined_loss_pct=0.0005,
        ),
    )

    assert result.total_funding_cashflow < 0.0
    assert [entry.symbol for entry in result.entries] == ["ETH/USDT", "SOL/USDT"]
    assert not any(
        item.breaker == "monthly_combined" and item.action == "activated"
        for item in result.breaker_transitions
    )


def test_all_same_timestamp_midnight_funding_is_inside_new_month_anchor() -> None:
    boundary = datetime(2025, 2, 1, tzinfo=UTC)
    first_decision = boundary - timedelta(minutes=30)
    second_decision = boundary - timedelta(minutes=15)
    carried = frame(
        [
            (first_decision, 100.0, 101.0, 99.0, 100.0),
            (second_decision, 100.0, 101.0, 99.0, 100.0),
            (boundary, 100.0, 101.0, 99.0, 100.0),
        ]
    )
    new_symbol = frame(
        [
            (second_decision, 100.0, 101.0, 99.0, 100.0),
            (boundary, 100.0, 101.0, 99.0, 100.0),
        ]
    )
    symbols = ["ETH/USDT", "ZEC/USDT", "SOL/USDT"]
    index = pd.date_range(end=boundary, periods=91, freq="D", tz="UTC") - timedelta(days=1)
    rng = np.random.default_rng(920)
    returns = pd.DataFrame(
        rng.normal(0.0, 0.01, size=(91, 3)),
        index=index,
        columns=symbols,
    )
    result = simulate_v15p2_portfolio(
        {
            "ETH/USDT": carried,
            "ZEC/USDT": carried.copy(),
            "SOL/USDT": new_symbol,
        },
        [
            intent("ETH/USDT", first_decision),
            intent("ZEC/USDT", first_decision),
            intent("SOL/USDT", second_decision),
        ],
        funding_events=[
            {"ts": boundary, "symbol": "ETH/USDT", "rate": 0.05, "mark_price": 100.0},
            {"ts": boundary, "symbol": "ZEC/USDT", "rate": 0.05, "mark_price": 100.0},
        ],
        daily_returns=returns,
        policy=V15P2PortfolioPolicy(
            daily_loss_pct=0.99,
            weekly_loss_pct=0.99,
            monthly_combined_loss_pct=0.001,
        ),
    )

    assert len(result.funding_events) == 2
    assert result.total_funding_cashflow < 0.0
    assert [entry.symbol for entry in result.entries] == symbols
    assert not any(
        item.breaker == "monthly_combined" and item.action == "activated"
        for item in result.breaker_transitions
    )


def test_monthly_side_breaker_latches_after_pnl_recovers_then_resets() -> None:
    t15 = T0 + timedelta(minutes=15)
    t30 = T0 + timedelta(minutes=30)
    t45 = T0 + timedelta(minutes=45)
    loss = frame(
        [
            (T0, 100.0, 101.0, 99.0, 100.0),
            (t15, 100.0, 101.0, 99.0, 100.0),
            (t30, 97.0, 98.0, 96.0, 97.0),
        ]
    )
    win = frame(
        [
            (T0, 100.0, 101.0, 99.0, 100.0),
            (t15, 100.0, 101.0, 99.0, 100.0),
            (t30, 100.0, 110.0, 99.0, 109.0),
            (t45, 107.0, 108.0, 106.0, 107.0),
        ]
    )
    blocked = frame(
        [
            (t30, 100.0, 101.0, 99.0, 100.0),
            (t45, 100.0, 101.0, 99.0, 100.0),
        ]
    )
    jan_end = datetime(2025, 1, 31, 23, 45, tzinfo=UTC)
    feb_start = datetime(2025, 2, 1, tzinfo=UTC)
    after_reset = frame(
        [
            (jan_end, 100.0, 101.0, 99.0, 100.0),
            (feb_start, 100.0, 101.0, 99.0, 100.0),
        ]
    )
    result = simulate_v15p2_portfolio(
        {
            "A_LOSS": loss,
            "Z_WIN": win,
            "M_BLOCKED": blocked,
            "N_RESET": after_reset,
        },
        [
            intent("A_LOSS"),
            intent("Z_WIN"),
            intent("M_BLOCKED", t30),
            intent("N_RESET", jan_end),
        ],
        daily_returns=return_history(["A_LOSS", "Z_WIN"]),
        policy=V15P2PortfolioPolicy(monthly_long_loss_pct=0.001),
    )

    long_rows = [row.amount for row in result.journal_rows if row.side == "long"]
    assert sum(long_rows) > 0.0
    assert any(
        item.symbol == "M_BLOCKED" and item.reason == "breaker_monthly_long"
        for item in result.rejections
    )
    reset = next(
        item
        for item in result.breaker_transitions
        if item.breaker == "long" and item.action == "monthly_reset"
    )
    assert reset.blocked_until is None
    assert any(entry.symbol == "N_RESET" for entry in result.entries)


def test_monthly_side_breaker_expires_after_fixed_halt_without_reextension() -> None:
    after_halt_decision = T0 + timedelta(days=4)
    after_halt_entry = after_halt_decision + timedelta(minutes=15)
    loss = frame(
        [
            (T0, 100.0, 101.0, 99.0, 100.0),
            (T0 + timedelta(minutes=15), 100.0, 101.0, 99.0, 100.0),
            (T0 + timedelta(minutes=30), 97.0, 98.0, 96.0, 97.0),
        ]
    )
    resumed = frame(
        [
            (after_halt_decision, 100.0, 101.0, 99.0, 100.0),
            (after_halt_entry, 100.0, 101.0, 99.0, 100.0),
        ]
    )
    result = simulate_v15p2_portfolio(
        {"A_LOSS": loss, "B_RESUMED": resumed},
        [intent("A_LOSS"), intent("B_RESUMED", after_halt_decision)],
        policy=V15P2PortfolioPolicy(
            daily_loss_pct=0.99,
            weekly_loss_pct=0.99,
            monthly_combined_loss_pct=0.99,
            monthly_long_loss_pct=0.001,
            monthly_halt_days=3.0,
        ),
    )

    activation = next(
        item
        for item in result.breaker_transitions
        if item.breaker == "long" and item.action == "activated"
    )
    assert activation.blocked_until == T0 + timedelta(minutes=30, days=3)
    assert any(
        item.breaker == "long" and item.action == "expired" for item in result.breaker_transitions
    )
    assert any(entry.symbol == "B_RESUMED" for entry in result.entries)


def test_month_reset_clears_side_latch_but_old_fixed_halt_carries_across_boundary() -> None:
    loss_decision = datetime(2025, 1, 31, 23, 15, tzinfo=UTC)
    loss_entry = loss_decision + timedelta(minutes=15)
    loss_exit = loss_decision + timedelta(minutes=30)
    month_boundary = datetime(2025, 2, 1, tzinfo=UTC)
    resume_decision = datetime(2025, 2, 4, tzinfo=UTC)
    resume_entry = resume_decision + timedelta(minutes=15)
    loss = frame(
        [
            (loss_decision, 100.0, 101.0, 99.0, 100.0),
            (loss_entry, 100.0, 101.0, 99.0, 100.0),
            (loss_exit, 97.0, 98.0, 96.0, 97.0),
        ]
    )
    carry_attempt = frame(
        [
            (loss_exit, 100.0, 101.0, 99.0, 100.0),
            (month_boundary, 100.0, 101.0, 99.0, 100.0),
        ]
    )
    resumed = frame(
        [
            (resume_decision, 100.0, 101.0, 99.0, 100.0),
            (resume_entry, 100.0, 101.0, 99.0, 100.0),
        ]
    )
    result = simulate_v15p2_portfolio(
        {"A_LOSS": loss, "B_CARRY": carry_attempt, "C_RESUME": resumed},
        [
            intent("A_LOSS", loss_decision),
            intent("B_CARRY", loss_exit),
            intent("C_RESUME", resume_decision),
        ],
        policy=V15P2PortfolioPolicy(
            daily_loss_pct=0.99,
            weekly_loss_pct=0.99,
            monthly_combined_loss_pct=0.99,
            monthly_long_loss_pct=0.001,
            monthly_halt_days=3.0,
        ),
    )

    activation = next(
        item
        for item in result.breaker_transitions
        if item.breaker == "long" and item.action == "activated"
    )
    assert activation.blocked_until == loss_exit + timedelta(days=3)
    reset = next(
        item
        for item in result.breaker_transitions
        if item.breaker == "long" and item.action == "monthly_reset"
    )
    assert reset.blocked_until == activation.blocked_until
    assert any(
        item.symbol == "B_CARRY" and item.reason == "breaker_monthly_long"
        for item in result.rejections
    )
    assert any(
        item.breaker == "long" and item.action == "expired" for item in result.breaker_transitions
    )
    assert [entry.symbol for entry in result.entries] == ["A_LOSS", "C_RESUME"]


def test_evaluation_window_allows_prior_decision_but_excludes_end_and_context() -> None:
    start = T0 + timedelta(minutes=15)
    end = T0 + timedelta(minutes=30)
    eth = frame(
        [
            (T0, 100.0, 101.0, 99.0, 100.0),
            (start, 100.0, 101.0, 99.0, 100.0),
            (end, 100.0, 101.0, 99.0, 100.0),
        ]
    )
    sol = frame(
        [
            (start, 100.0, 101.0, 99.0, 100.0),
            (end, 100.0, 101.0, 99.0, 100.0),
        ]
    )
    result = simulate_v15p2_portfolio(
        {"ETH/USDT": eth, "SOL/USDT": sol},
        [intent("ETH/USDT"), intent("SOL/USDT", start)],
        funding_events=[{"ts": end, "symbol": "ETH/USDT", "rate": 0.01, "mark_price": 100.0}],
        evaluation_start=start,
        evaluation_end=end,
    )

    assert result.evaluation_start == start
    assert result.evaluation_end == end
    assert [point.ts for point in result.curve] == [start]
    assert [entry.symbol for entry in result.entries] == ["ETH/USDT"]
    assert result.funding_events == ()
    assert any(
        item.symbol == "SOL/USDT" and item.reason == "entry_outside_evaluation_window"
        for item in result.rejections
    )


def test_custom_scenario_has_noncanonical_identity_and_full_serialized_record() -> None:
    bars = frame(
        [
            (T0, 100.0, 101.0, 99.0, 100.0),
            (T0 + timedelta(minutes=15), 100.0, 101.0, 99.0, 100.0),
        ]
    )
    custom = V15P2CostScenario(name="B", fee_bps_per_fill=5.0)
    result = simulate_v15p2_portfolio({"ETH/USDT": bars}, [intent("ETH/USDT")], scenario=custom)
    canonical = simulate_v15p2_portfolio({"ETH/USDT": bars}, [intent("ETH/USDT")], scenario="B")

    assert result.scenario == "B"
    assert result.scenario_is_canonical is False
    assert result.scenario_identity.startswith("CUSTOM:B:")
    assert result.scenario_config.fee_bps_per_fill == 5.0
    assert result.policy.minimum_notional == 10.0
    assert canonical.scenario_is_canonical is True
    assert canonical.scenario_identity == "B"


def test_short_terminal_position_and_financial_identities() -> None:
    bars = frame(
        [
            (T0, 100.0, 101.0, 99.0, 100.0),
            (T0 + timedelta(minutes=15), 100.0, 101.0, 95.0, 95.0),
        ]
    )
    result = simulate_v15p2_portfolio(
        {"ETH/USDT": bars},
        [intent("ETH/USDT", side="short", stop=103.0)],
    )

    assert [fill.reason for fill in result.exit_fills] == ["tp1", "tp2"]
    terminal = result.terminal_positions[0]
    assert terminal.side == "short"
    assert terminal.gross_unrealized_price_pnl > 0.0
    assert result.final_wallet == pytest.approx(
        result.initial_wallet
        + sum(fill.adjusted_price_pnl for fill in result.exit_fills)
        + result.total_funding_cashflow
        - result.total_execution_cost_charged
    )
    assert result.final_nav == pytest.approx(
        result.final_wallet + terminal.accrued_nav_contribution
    )
    assert result.accrued_terminal_exit_cost == pytest.approx(terminal.accrued_exit_cost)


def test_post_correlation_minimum_notional_gate_is_fail_closed() -> None:
    bars = frame(
        [
            (T0, 100.0, 101.0, 99.0, 100.0),
            (T0 + timedelta(minutes=15), 100.0, 101.0, 99.0, 100.0),
        ]
    )
    result = simulate_v15p2_portfolio(
        {"ETH/USDT": bars},
        [intent("ETH/USDT")],
        policy=V15P2PortfolioPolicy(base_risk_per_trade=0.00005),
    )

    assert result.entries == ()
    assert result.rejections[0].reason == "below_min_notional"


def test_minimum_notional_rejection_precedes_portfolio_notional_rejection() -> None:
    bars = frame(
        [
            (T0, 100.0, 101.0, 99.0, 100.0),
            (T0 + timedelta(minutes=15), 100.0, 101.0, 99.0, 100.0),
        ]
    )
    result = simulate_v15p2_portfolio(
        {"AAA": bars, "BBB": bars.copy()},
        [intent("AAA", stop=97.5), intent("BBB", stop=1.0)],
        daily_returns=return_history(["AAA", "BBB"]),
        policy=V15P2PortfolioPolicy(
            base_risk_per_trade=0.0001,
            max_portfolio_notional_x=0.00161,
        ),
    )

    assert [entry.symbol for entry in result.entries] == ["AAA"]
    rejection = next(item for item in result.rejections if item.symbol == "BBB")
    assert rejection.reason == "below_min_notional"


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ({"candidate_id": "other"}, "candidate_id"),
        ({"config_sha256": "b" * 64}, "config_sha256"),
        ({"strategy_rank": 1}, "strategy_rank"),
        ({"entry_reference_price": 99.0}, "entry_reference_price"),
    ],
)
def test_intent_identity_rank_config_and_reference_are_validated(
    mutation: dict[str, object], message: str
) -> None:
    bars = frame(
        [
            (T0, 100.0, 101.0, 99.0, 100.0),
            (T0 + timedelta(minutes=15), 100.0, 101.0, 99.0, 100.0),
        ]
    )
    malformed = replace(intent("ETH/USDT"), **mutation)

    with pytest.raises(ValueError, match=message):
        simulate_v15p2_portfolio({"ETH/USDT": bars}, [malformed])
