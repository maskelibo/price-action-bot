from __future__ import annotations

import math
from dataclasses import fields
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pandas as pd
import pytest

from price_action.lab.crypto_15m_pairs_engine import (
    PairCostModel,
    PairPortfolioPolicy,
    PairSelectionEvent,
    simulate_pair_portfolio,
)
from price_action.lab.crypto_15m_pairs_signals import PairEntryIntent

BASE = datetime(2025, 1, 1, tzinfo=UTC)
ZERO_COST = PairCostModel(0.0, 0.0, 0.0)


def _frame(points: list[tuple[int, float, float]]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"ts": BASE + timedelta(minutes=minute), "open": open_, "close": close}
            for minute, open_, close in points
        ]
    )


def _y_for_z(
    z_score: float,
    *,
    x_price: float = 100.0,
    beta: float = 1.0,
    alpha: float = 0.0,
    mean: float = 0.0,
    std: float = 0.05,
) -> float:
    return math.exp(alpha + beta * math.log(x_price) + mean + z_score * std)


def _pair_frames(
    rows: list[tuple[int, float, float]],
    *,
    y_symbol: str = "Y/USDT",
    x_symbol: str = "X/USDT",
    x_price: float = 100.0,
    beta: float = 1.0,
    std: float = 0.05,
) -> dict[str, pd.DataFrame]:
    return {
        y_symbol: _frame(
            [
                (
                    minute,
                    _y_for_z(open_z, x_price=x_price, beta=beta, std=std),
                    _y_for_z(close_z, x_price=x_price, beta=beta, std=std),
                )
                for minute, open_z, close_z in rows
            ]
        ),
        x_symbol: _frame([(minute, x_price, x_price) for minute, _, _ in rows]),
    }


def _intent(
    *,
    pair_id: str = "PAIR",
    decision_minute: int = 45,
    selection_minute: int = 0,
    y_symbol: str = "Y/USDT",
    x_symbol: str = "X/USDT",
    z_score: float = 2.5,
    beta: float = 1.0,
    validation_std: float = 0.05,
    max_hold_hours: int = 10,
    cooldown_hours: int = 1,
) -> PairEntryIntent:
    high_spread = z_score > 0.0
    return PairEntryIntent(
        candidate_id="CELL",
        pair_id=pair_id,
        selection_ts=BASE + timedelta(minutes=selection_minute),
        decision_ts=BASE + timedelta(minutes=decision_minute),
        entry_ts=BASE + timedelta(minutes=decision_minute + 15),
        y_symbol=y_symbol,
        x_symbol=x_symbol,
        y_side="short" if high_spread else "long",
        x_side="long" if high_spread else "short",
        z_score=z_score,
        alpha=0.0,
        beta=beta,
        validation_mean=0.0,
        validation_std=validation_std,
        gross_weight_y=1.0 / (1.0 + beta),
        gross_weight_x=beta / (1.0 + beta),
        entry_abs_z=2.5,
        exit_abs_z=0.5,
        disaster_abs_z=4.5,
        max_hold_hours=max_hold_hours,
        cooldown_hours=cooldown_hours,
        expected_convergence_return=0.02,
        adverse_funding=0.0,
        stressed_required_return=0.01,
    )


def _merge_frames(*groups: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    merged: dict[str, pd.DataFrame] = {}
    for group in groups:
        for symbol, frame in group.items():
            if symbol in merged:
                merged[symbol] = (
                    pd.concat([merged[symbol], frame])
                    .drop_duplicates("ts", keep="last")
                    .sort_values("ts")
                    .reset_index(drop=True)
                )
            else:
                merged[symbol] = frame.copy()
    return merged


def test_atomic_entry_and_exit_use_next_shared_opens_without_close_lookahead() -> None:
    frames = _pair_frames([(45, 2.5, 2.5), (60, 3.0, 0.0), (75, 2.0, 2.0)])

    result = simulate_pair_portfolio(frames, [_intent()], cost=ZERO_COST)

    episode = result.episodes[0]
    assert episode.decision_ts == BASE + timedelta(minutes=45)
    assert episode.entry_ts == BASE + timedelta(minutes=60)
    assert episode.y_entry_price == pytest.approx(_y_for_z(3.0))
    assert episode.signal_z == pytest.approx(2.5)
    assert episode.fill_z == pytest.approx(3.0)
    assert episode.entry_z == pytest.approx(3.0)
    assert episode.loss_per_gross == pytest.approx(0.0375)
    assert episode.gross_exposure == pytest.approx(50.0 / 0.0375)
    assert episode.signal_expected_convergence_return == pytest.approx(0.02)
    assert episode.expected_convergence_return == pytest.approx(0.0625)
    assert episode.signal_stressed_required_return == pytest.approx(0.01)
    assert episode.stressed_required_return == pytest.approx(0.0171)
    assert episode.exit_decision_ts == BASE + timedelta(minutes=60)
    assert episode.exit_ts == BASE + timedelta(minutes=75)
    assert episode.y_exit_price == pytest.approx(_y_for_z(2.0))
    assert episode.exit_reason == "mean_exit"


def test_atomic_entry_rejects_missing_leg_and_disaster_z_without_any_fill() -> None:
    frames = _pair_frames([(45, 2.5, 2.5), (60, 2.5, 2.5)])
    frames["X/USDT"] = _frame([(45, 100.0, 100.0), (75, 100.0, 100.0)])

    missing = simulate_pair_portfolio(frames, [_intent()])

    assert missing.episodes == ()
    assert missing.open_pair_count == 0
    assert missing.total_execution_cost == 0.0
    assert missing.rejections == (("CELL", "PAIR", "atomic_entry_leg_missing"),)
    assert missing.rejection_details[0].decision_ts == BASE + timedelta(minutes=45)
    assert missing.rejection_details[0].entry_ts == BASE + timedelta(minutes=60)
    assert missing.rejection_details[0].reason == "atomic_entry_leg_missing"

    valid = _intent()
    payload = {field.name: getattr(valid, field.name) for field in fields(PairEntryIntent)}
    payload["z_score"] = valid.disaster_abs_z
    at_disaster = simulate_pair_portfolio(
        _pair_frames([(45, 2.5, 2.5), (60, 2.5, 2.5)]),
        [SimpleNamespace(**payload)],
    )
    assert at_disaster.open_pair_count == 0
    assert at_disaster.total_execution_cost == 0.0
    assert at_disaster.rejections[-1][2] == "entry_at_or_beyond_disaster"


@pytest.mark.parametrize(
    ("fill_z", "reason"),
    [
        (-2.5, "fill_z_direction_changed"),
        (2.4, "fill_z_below_entry_threshold"),
        (4.5, "fill_z_at_or_beyond_disaster"),
    ],
)
def test_atomic_fill_revalidates_direction_entry_and_disaster_thresholds(
    fill_z: float, reason: str
) -> None:
    frames = _pair_frames([(45, 2.5, 2.5), (60, fill_z, 2.5)])

    result = simulate_pair_portfolio(frames, [_intent()], cost=ZERO_COST)

    assert result.open_pair_count == 0
    assert result.total_execution_cost == 0.0
    assert result.rejections == (("CELL", "PAIR", reason),)


def test_atomic_fill_recomputes_and_enforces_economic_gate() -> None:
    std = 0.01
    frames = _pair_frames([(45, 2.5, 2.5), (60, 2.5, 2.5)], std=std)

    result = simulate_pair_portfolio(frames, [_intent(validation_std=std)], cost=ZERO_COST)

    assert result.open_pair_count == 0
    assert result.rejections == (("CELL", "PAIR", "fill_economic_gate"),)


def test_leg_cap_scales_both_beta_weighted_legs_by_one_common_factor() -> None:
    beta = 3.0
    std = 0.04
    frames = _pair_frames(
        [(45, 2.5, 2.5), (60, 4.0, 4.0), (75, 4.0, 0.0), (90, 4.0, 4.0)],
        x_price=1.0,
        beta=beta,
        std=std,
    )

    result = simulate_pair_portfolio(
        frames,
        [_intent(beta=beta, validation_std=std)],
        cost=ZERO_COST,
    )

    episode = result.episodes[0]
    assert episode.gross_exposure == pytest.approx(2_000.0)
    assert episode.y_entry_notional == pytest.approx(500.0)
    assert episode.x_entry_notional == pytest.approx(1_500.0)
    assert episode.y_entry_notional + episode.x_entry_notional == pytest.approx(
        episode.gross_exposure
    )


def test_leverage_cap_uses_total_gross_entry_notional_over_current_nav() -> None:
    frames = _pair_frames([(45, 2.5, 2.5), (60, 3.0, 3.0), (75, 3.0, 0.0), (90, 3.0, 3.0)])
    policy = PairPortfolioPolicy(max_leg_notional_pct=1.0, leverage=0.10)

    result = simulate_pair_portfolio(frames, [_intent()], policy=policy, cost=ZERO_COST)

    episode = result.episodes[0]
    assert episode.gross_exposure == pytest.approx(1_000.0)
    assert episode.gross_exposure / episode.equity_before_entry == pytest.approx(0.10)


@pytest.mark.parametrize(("cost_multiplier", "expected_bps"), [(1.0, 57.0), (2.0, 114.0)])
def test_four_atomic_fills_charge_exact_preregistered_gross_round_trip_bps(
    cost_multiplier: float, expected_bps: float
) -> None:
    frames = _pair_frames([(45, 2.5, 2.5), (60, 2.5, 2.5), (75, 2.5, 0.0), (90, 2.5, 2.5)])
    cost = PairCostModel(cost_multiplier=cost_multiplier)

    result = simulate_pair_portfolio(frames, [_intent()], cost=cost)

    episode = result.episodes[0]
    assert episode.gross_exposure == pytest.approx(1_000.0)
    assert episode.gross_pair_price_pnl == pytest.approx(0.0)
    assert episode.execution_cost / episode.gross_exposure * 10_000 == pytest.approx(expected_bps)
    assert episode.execution_cost == pytest.approx(5.70 * cost_multiplier)
    assert result.final_equity == pytest.approx(10_000.0 - episode.execution_cost)


def test_open_pair_mtm_accrues_hypothetical_exit_cost_for_both_legs() -> None:
    frames = _pair_frames([(45, 2.5, 2.5), (60, 2.5, 2.5)])
    cost = PairCostModel(
        fee_bps_per_leg=10.0,
        spread_slippage_bps_per_leg=0.0,
        impact_bps_per_leg=0.0,
    )

    result = simulate_pair_portfolio(frames, [_intent()], cost=cost)

    assert result.open_pair_count == 1
    assert result.total_execution_cost == pytest.approx(1.0)
    assert result.accrued_exit_cost == pytest.approx(1.0)
    assert result.final_equity == pytest.approx(9_998.0)
    assert len(result.terminal_episodes) == 1
    terminal = result.terminal_episodes[0]
    assert terminal.exit_reason == "terminal_open_mtm"
    assert terminal.execution_cost == pytest.approx(2.0)
    assert terminal.net_pnl == pytest.approx(-2.0)
    assert terminal.equity_after_exit == pytest.approx(result.final_equity)


def test_funding_uses_leg_signs_beta_weights_and_mark_precedence() -> None:
    beta = 3.0
    std = 0.10
    x_price = 1.0
    y_entry = _y_for_z(2.5, x_price=x_price, beta=beta, std=std)
    frames = _pair_frames(
        [(45, 2.5, 2.5), (60, 2.5, 2.5), (75, 2.5, 0.0), (90, 2.5, 2.5)],
        x_price=x_price,
        beta=beta,
        std=std,
    )
    # The current 01:15 opens must not be used for a 01:15 funding event.
    frames["X/USDT"].loc[frames["X/USDT"]["ts"] == BASE + timedelta(minutes=75), "open"] = 10
    funding = [
        {
            "ts": BASE + timedelta(minutes=75),
            "symbol": "Y/USDT",
            "rate": 0.01,
            "mark_price": 2.0 * y_entry,
        },
        {"ts": BASE + timedelta(minutes=75), "symbol": "X/USDT", "rate": 0.01},
    ]

    result = simulate_pair_portfolio(
        frames,
        [_intent(beta=beta, validation_std=std)],
        funding_events=funding,
        cost=ZERO_COST,
    )

    episode = result.episodes[0]
    assert episode.gross_weight_y == pytest.approx(0.25)
    assert episode.gross_weight_x == pytest.approx(0.75)
    assert episode.y_entry_notional == pytest.approx(250.0)
    assert episode.x_entry_notional == pytest.approx(750.0)
    assert episode.y_funding_cashflow == pytest.approx(5.0)  # short receives
    assert episode.x_funding_cashflow == pytest.approx(-7.5)  # long pays
    assert result.total_funding_cashflow == pytest.approx(-2.5)


def test_bare_funding_symbol_is_canonical_and_invalid_mark_falls_back_to_close() -> None:
    frames = _pair_frames([(45, 2.5, 2.5), (60, 2.5, 2.5), (75, 2.5, 0.0), (90, 2.5, 2.5)])
    funding = [
        {
            "ts": BASE + timedelta(minutes=75),
            "symbol": "Y",
            "rate": 0.01,
            "mark_price": 0.0,
        }
    ]

    result = simulate_pair_portfolio(frames, [_intent()], funding_events=funding, cost=ZERO_COST)

    # High-spread Y is short, so it receives positive funding.  The invalid
    # event mark is ignored and the completed 01:00 close is used.
    assert result.episodes[0].y_funding_cashflow == pytest.approx(5.0)
    assert result.total_funding_cashflow == pytest.approx(5.0)


def test_funding_floors_fractional_seconds_and_uses_strict_entry_inclusive_exit_rule() -> None:
    y_entry = _y_for_z(2.5)
    frames = _pair_frames([(45, 2.5, 2.5), (60, 2.5, 2.5), (75, 2.5, 0.0), (90, 2.5, 2.5)])
    funding = [
        {
            # Floors to entry_ts and must not charge the not-yet-held pair.
            "ts": BASE + timedelta(minutes=60, microseconds=999_999),
            "symbol": "Y/USDT",
            "rate": 0.50,
            "mark_price": y_entry,
        },
        {
            # Floors to exit_ts and is eligible before the atomic exit fill.
            "ts": BASE + timedelta(minutes=90, microseconds=999_999),
            "symbol": "Y/USDT",
            "rate": 0.01,
            "mark_price": y_entry,
        },
    ]

    result = simulate_pair_portfolio(frames, [_intent()], funding_events=funding, cost=ZERO_COST)

    assert result.episodes[0].y_funding_cashflow == pytest.approx(5.0)
    assert result.total_funding_cashflow == pytest.approx(5.0)


def test_funding_timestamp_floor_collision_fails_closed_before_replay() -> None:
    frames = _pair_frames([(45, 2.5, 2.5), (60, 2.5, 2.5)])
    funding = [
        {
            "ts": BASE + timedelta(minutes=60, microseconds=100_000),
            "symbol": "Y/USDT",
            "rate": 0.01,
        },
        {
            "ts": BASE + timedelta(minutes=60, microseconds=900_000),
            "symbol": "Y/USDT",
            "rate": 0.02,
        },
    ]

    with pytest.raises(ValueError, match="collide after whole-second"):
        simulate_pair_portfolio(frames, [_intent()], funding_events=funding)


def test_disaster_stop_has_priority_over_simultaneous_mean_exit() -> None:
    frames = _pair_frames([(45, 2.5, 2.5), (60, 2.5, -5.0), (75, -5.0, -5.0)])

    result = simulate_pair_portfolio(frames, [_intent()], cost=ZERO_COST)

    assert result.episodes[0].exit_reason == "disaster_z_stop"
    assert result.episodes[0].exit_decision_ts == BASE + timedelta(minutes=60)
    assert result.episodes[0].exit_ts == BASE + timedelta(minutes=75)


def test_max_hold_has_priority_over_mean_exit_on_same_completed_bar() -> None:
    frames = _pair_frames(
        [
            (45, 2.5, 2.5),
            (60, 2.5, 2.5),
            (75, 2.5, 2.5),
            (90, 2.5, 2.5),
            (105, 2.5, 0.0),
            (120, 2.5, 2.5),
        ]
    )

    result = simulate_pair_portfolio(frames, [_intent(max_hold_hours=1)], cost=ZERO_COST)

    assert result.episodes[0].exit_reason == "max_hold"
    assert result.episodes[0].exit_ts == BASE + timedelta(minutes=120)


def test_h_multiplier_applies_to_cumulative_atomic_pair_mtm_not_each_leg() -> None:
    y_entry = _y_for_z(2.5)
    frames = {
        "Y/USDT": _frame([(45, y_entry, y_entry), (60, y_entry, 0.9 * y_entry)]),
        "X/USDT": _frame([(45, 100.0, 100.0), (60, 100.0, 100.0)]),
    }
    intent = _intent()

    base = simulate_pair_portfolio(frames, [intent], cost=ZERO_COST)
    haircut = simulate_pair_portfolio(
        frames,
        [intent],
        cost=ZERO_COST,
        positive_payoff_multiplier=0.5,
        negative_payoff_multiplier=1.25,
    )

    assert base.open_pair_count == 1
    assert base.final_equity == pytest.approx(10_050.0)
    assert haircut.final_equity == pytest.approx(10_025.0)
    assert haircut.equity_curve[-1][1] == pytest.approx(haircut.final_equity)

    closed_frames = {
        "Y/USDT": _frame(
            [
                (45, y_entry, y_entry),
                (60, y_entry, 0.9 * y_entry),
                (75, 0.9 * y_entry, 0.9 * y_entry),
            ]
        ),
        "X/USDT": _frame([(45, 100.0, 100.0), (60, 100.0, 100.0), (75, 100.0, 100.0)]),
    }
    closed = simulate_pair_portfolio(
        closed_frames,
        [intent],
        cost=ZERO_COST,
        positive_payoff_multiplier=0.5,
        negative_payoff_multiplier=1.25,
    )
    assert closed.episodes[0].gross_pair_price_pnl == pytest.approx(50.0)
    assert closed.episodes[0].payoff_multiplier == pytest.approx(0.5)
    assert closed.episodes[0].adjusted_pair_price_pnl == pytest.approx(25.0)


def test_data_gap_exits_both_legs_at_first_shared_open_and_quarantines_pair() -> None:
    frames = _pair_frames([(45, 2.5, 2.5), (60, 2.5, 2.5), (135, 3.0, 3.0)])

    result = simulate_pair_portfolio(frames, [_intent()], cost=ZERO_COST)

    episode = result.episodes[0]
    assert episode.exit_reason == "data_gap"
    assert episode.exit_ts == BASE + timedelta(minutes=135)
    assert result.open_pair_count == 0
    assert result.quarantined_pairs == (("CELL", "PAIR"),)


def test_monthly_deselection_exits_atomically_at_effective_open() -> None:
    frames = _pair_frames(
        [
            (45, 2.5, 2.5),
            (60, 2.5, 2.5),
            (75, 2.5, 2.5),
            (90, 2.5, 2.5),
            (105, 2.5, 2.5),
            (120, 2.5, 2.5),
        ]
    )
    events = [
        PairSelectionEvent("CELL", BASE, ("PAIR",)),
        PairSelectionEvent("CELL", BASE + timedelta(minutes=120), ("OTHER",)),
    ]

    result = simulate_pair_portfolio(frames, [_intent()], selection_events=events, cost=ZERO_COST)

    episode = result.episodes[0]
    assert episode.exit_reason == "pair_deselection"
    assert episode.exit_decision_ts == BASE + timedelta(minutes=105)
    assert episode.exit_ts == BASE + timedelta(minutes=120)


def test_structural_break_needs_four_hourly_checks_and_quarantine_resets_on_selection() -> None:
    minutes = list(range(45, 421, 15))
    entry_opens = {45, 60, 345, 360, 405, 420}
    rows = [(minute, 2.5 if minute in entry_opens else 2.0, 2.0) for minute in minutes]
    frames = _pair_frames(rows)
    intents = [
        _intent(),
        _intent(decision_minute=345),
        _intent(decision_minute=405, selection_minute=420),
    ]
    events = [
        PairSelectionEvent("CELL", BASE, ("PAIR",)),
        PairSelectionEvent("CELL", BASE + timedelta(minutes=420), ("PAIR",)),
    ]
    policy = PairPortfolioPolicy(
        structural_mean_window_hours=1,
        structural_consecutive_hourly_checks=4,
        structural_min_completeness=1.0,
    )

    result = simulate_pair_portfolio(
        frames,
        intents,
        selection_events=events,
        policy=policy,
        cost=ZERO_COST,
    )

    assert result.episodes[0].exit_reason == "structural_break"
    assert result.episodes[0].exit_decision_ts == BASE + timedelta(minutes=285)
    assert result.episodes[0].exit_ts == BASE + timedelta(minutes=300)
    assert ("CELL", "PAIR", "pair_quarantined") in result.rejections
    assert result.open_pair_count == 1  # next selection cleared quarantine before 07:00 entry
    assert result.quarantined_pairs == ()


def test_cooldown_rejects_reentry_without_creating_partial_state() -> None:
    frames = _pair_frames(
        [
            (45, 2.5, 2.5),
            (60, 2.5, 0.0),
            (75, 2.5, 2.5),
            (90, 2.5, 2.5),
            (105, 2.5, 2.5),
            (120, 2.5, 2.5),
        ]
    )

    result = simulate_pair_portfolio(
        frames,
        [_intent(cooldown_hours=2), _intent(decision_minute=105, cooldown_hours=2)],
        cost=ZERO_COST,
    )

    assert len(result.episodes) == 1
    assert result.open_pair_count == 0
    assert ("CELL", "PAIR", "pair_cooldown") in result.rejections


def test_common_nav_loss_drives_dd_throttled_risk_for_next_pair() -> None:
    first = _pair_frames(
        [(45, 2.5, 2.5), (60, 2.5, 2.5), (75, 5.0, 5.0), (90, 5.0, 5.0)],
        y_symbol="A/USDT",
        x_symbol="B/USDT",
    )
    second = _pair_frames(
        [(105, 2.5, 2.5), (120, 2.5, 0.0), (135, 2.5, 2.5)],
        y_symbol="C/USDT",
        x_symbol="D/USDT",
    )
    intents = [
        _intent(pair_id="P1", y_symbol="A/USDT", x_symbol="B/USDT"),
        _intent(
            pair_id="P2",
            decision_minute=105,
            y_symbol="C/USDT",
            x_symbol="D/USDT",
        ),
    ]
    policy = PairPortfolioPolicy(dd_throttle_threshold=0.001)

    result = simulate_pair_portfolio(
        _merge_frames(first, second), intents, policy=policy, cost=ZERO_COST
    )

    first_episode, second_episode = result.episodes
    assert first_episode.net_pnl < 0.0
    assert second_episode.equity_before_entry == pytest.approx(first_episode.equity_after_exit)
    assert second_episode.risk_budget == pytest.approx(
        second_episode.equity_before_entry * policy.risk_per_pair_episode * 0.5
    )


def test_pair_and_symbol_caps_leave_no_orphan_leg_state() -> None:
    p1 = _pair_frames(
        [(45, 2.5, 2.5), (60, 2.5, 2.5)],
        y_symbol="A/USDT",
        x_symbol="B/USDT",
    )
    p2 = _pair_frames(
        [(45, 2.5, 2.5), (60, 2.5, 2.5)],
        y_symbol="A/USDT",
        x_symbol="C/USDT",
    )
    p3 = _pair_frames(
        [(45, 2.5, 2.5), (60, 2.5, 2.5)],
        y_symbol="D/USDT",
        x_symbol="E/USDT",
    )
    intents = [
        _intent(pair_id="P1", y_symbol="A/USDT", x_symbol="B/USDT"),
        _intent(pair_id="P2", y_symbol="A/USDT", x_symbol="C/USDT"),
        _intent(pair_id="P3", y_symbol="D/USDT", x_symbol="E/USDT"),
    ]
    policy = PairPortfolioPolicy(max_pairs=1, max_legs=2)

    result = simulate_pair_portfolio(
        _merge_frames(p1, p2, p3), intents, policy=policy, cost=ZERO_COST
    )

    assert result.open_pair_count == 1
    assert result.open_leg_count == 2
    assert ("CELL", "P2", "symbol_already_open") in result.rejections
    assert ("CELL", "P3", "max_pairs") in result.rejections
