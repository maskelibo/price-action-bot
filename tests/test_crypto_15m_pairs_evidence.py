from __future__ import annotations

from dataclasses import fields, replace
from datetime import UTC, datetime, timedelta

import pytest

from price_action.lab.crypto_15m_pairs_engine import PairEpisodeLedger, PairPortfolioResult
from price_action.lab.crypto_15m_pairs_evidence import (
    ACTIVE_MONTH_DEFINITION,
    closed_episode_frame,
    economic_episode_frame,
    engine_max_drawdown_pct,
    engine_monthly_returns_pct,
    equity_series,
    monthly_active_exposure,
    scenario_window_summary,
    terminal_episode_frame,
)

T0 = datetime(2025, 1, 1, tzinfo=UTC)


def _episode(
    pair_id: str,
    *,
    entry_ts: datetime,
    exit_ts: datetime,
    regime: str = "high_spread",
    terminal: bool = False,
    execution_cost: float = 3.0,
    y_funding: float = -0.50,
    x_funding: float = 0.25,
    gross_pnl: float = 10.0,
    adjusted_pnl: float = 9.0,
    net_pnl: float = 5.75,
) -> PairEpisodeLedger:
    high = regime == "high_spread"
    return PairEpisodeLedger(
        candidate_id="DP1",
        pair_id=pair_id,
        selection_ts=entry_ts - timedelta(days=1),
        y_symbol="Y/USDT",
        x_symbol="X/USDT",
        entry_regime=regime,  # type: ignore[arg-type]
        y_side="short" if high else "long",
        x_side="long" if high else "short",
        decision_ts=entry_ts - timedelta(minutes=15),
        entry_ts=entry_ts,
        exit_decision_ts=exit_ts - timedelta(minutes=15),
        exit_ts=exit_ts,
        exit_reason="terminal_open_mtm" if terminal else "mean_exit",
        signal_z=2.5 if high else -2.5,
        fill_z=2.6 if high else -2.6,
        entry_z=2.6 if high else -2.6,
        exit_z=0.4 if high else -0.4,
        alpha=0.0,
        beta=1.0,
        validation_mean=0.0,
        validation_std=0.1,
        gross_weight_y=0.5,
        gross_weight_x=0.5,
        y_entry_price=100.0,
        x_entry_price=100.0,
        y_exit_price=99.0,
        x_exit_price=100.0,
        y_quantity=5.0,
        x_quantity=5.0,
        gross_exposure=1_000.0,
        y_entry_notional=500.0,
        x_entry_notional=500.0,
        risk_budget=50.0,
        loss_per_gross=0.05,
        bars_held=4,
        gross_pair_price_pnl=gross_pnl,
        payoff_multiplier=adjusted_pnl / gross_pnl if gross_pnl else 1.0,
        adjusted_pair_price_pnl=adjusted_pnl,
        y_entry_fee=0.50,
        y_entry_spread_slippage=0.25,
        y_entry_impact=0.10,
        x_entry_fee=0.50,
        x_entry_spread_slippage=0.25,
        x_entry_impact=0.10,
        y_exit_fee=0.50,
        y_exit_spread_slippage=0.25,
        y_exit_impact=0.10,
        x_exit_fee=0.50,
        x_exit_spread_slippage=0.25,
        x_exit_impact=0.10,
        y_funding_cashflow=y_funding,
        x_funding_cashflow=x_funding,
        execution_cost=execution_cost,
        net_pnl=net_pnl,
        signal_expected_convergence_return=0.03,
        expected_convergence_return=0.025,
        adverse_funding=0.001,
        signal_stressed_required_return=0.01,
        stressed_required_return=0.01,
        equity_before_entry=100.0,
        equity_after_exit=100.0 + net_pnl,
    )


def _result(
    *,
    curve: tuple[tuple[datetime, float], ...] = ((T0, 100.0),),
    episodes: tuple[PairEpisodeLedger, ...] = (),
    terminal_episodes: tuple[PairEpisodeLedger, ...] = (),
    monthly_returns: tuple[tuple[str, float], ...] = (("2025-01", 0.10),),
    max_drawdown: float = 0.0,
) -> PairPortfolioResult:
    return PairPortfolioResult(
        episodes=episodes,
        terminal_episodes=terminal_episodes,
        equity_curve=curve,
        monthly_returns=monthly_returns,
        rejections=(),
        initial_equity=100.0,
        final_equity=curve[-1][1] if curve else 100.0,
        max_drawdown=max_drawdown,
        total_execution_cost=sum(episode.execution_cost for episode in episodes),
        accrued_exit_cost=sum(episode.execution_cost for episode in terminal_episodes),
        total_funding_cashflow=sum(
            episode.y_funding_cashflow + episode.x_funding_cashflow
            for episode in (*episodes, *terminal_episodes)
        ),
        open_pair_count=len(terminal_episodes),
        open_leg_count=2 * len(terminal_episodes),
        quarantined_pairs=(),
    )


def test_pair_engine_units_are_explicitly_converted_for_validation() -> None:
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


def test_closed_terminal_and_economic_frames_preserve_sampling_boundary() -> None:
    closed = _episode(
        "closed",
        entry_ts=T0,
        exit_ts=T0 + timedelta(days=1),
    )
    terminal = _episode(
        "terminal",
        entry_ts=T0 + timedelta(days=2),
        exit_ts=T0 + timedelta(days=3),
        regime="low_spread",
        terminal=True,
    )
    result = _result(episodes=(closed,), terminal_episodes=(terminal,))

    closed_frame = closed_episode_frame(result)
    terminal_frame = terminal_episode_frame(result)
    economic = economic_episode_frame(result)

    assert tuple(closed_frame.columns) == tuple(field.name for field in fields(PairEpisodeLedger))
    assert tuple(terminal_frame.columns) == tuple(field.name for field in fields(PairEpisodeLedger))
    for frame in (closed_frame, terminal_frame):
        for column in (
            "selection_ts",
            "decision_ts",
            "entry_ts",
            "exit_decision_ts",
            "exit_ts",
        ):
            assert str(frame[column].dt.tz) == "UTC"

    assert economic["episode_kind"].tolist() == ["closed", "terminal_open_mtm"]
    assert economic["is_closed_sample"].tolist() == [True, False]
    assert economic["funding_cashflow"].tolist() == pytest.approx([-0.25, -0.25])
    assert economic.attrs["terminal_rows_are_closed_samples"] is False

    before_terminal = economic_episode_frame(
        result,
        start=T0,
        end=T0 + timedelta(days=3),
    )
    assert before_terminal["pair_id"].tolist() == ["closed"]
    through_terminal = economic_episode_frame(
        result,
        start=T0,
        end=T0 + timedelta(days=4),
    )
    assert through_terminal["pair_id"].tolist() == ["closed", "terminal"]


def test_window_summary_carries_baseline_peak_fills_missing_month_and_sums_closed() -> None:
    start = datetime(2025, 1, 1, tzinfo=UTC)
    end = datetime(2025, 4, 1, tzinfo=UTC)
    curve = (
        (datetime(2024, 12, 1, tzinfo=UTC), 120.0),
        (datetime(2024, 12, 31, 23, 45, tzinfo=UTC), 80.0),
        (datetime(2025, 1, 15, tzinfo=UTC), 60.0),
        (datetime(2025, 1, 31, 23, 45, tzinfo=UTC), 88.0),
        (datetime(2025, 2, 15, tzinfo=UTC), 88.0),
        (datetime(2025, 3, 31, 23, 45, tzinfo=UTC), 96.8),
        (end, 200.0),
    )
    high = _episode(
        "high",
        entry_ts=datetime(2025, 1, 1, tzinfo=UTC),
        exit_ts=datetime(2025, 1, 31, 23, 45, tzinfo=UTC),
    )
    low = _episode(
        "low",
        entry_ts=datetime(2025, 3, 1, tzinfo=UTC),
        exit_ts=datetime(2025, 3, 31, 23, 45, tzinfo=UTC),
        regime="low_spread",
        execution_cost=4.0,
        y_funding=0.75,
        x_funding=-0.25,
        gross_pnl=20.0,
        adjusted_pnl=20.0,
        net_pnl=16.5,
    )
    at_end = _episode(
        "at_end",
        entry_ts=datetime(2025, 3, 15, tzinfo=UTC),
        exit_ts=end,
        execution_cost=99.0,
        net_pnl=99.0,
    )
    terminal = _episode(
        "terminal",
        entry_ts=datetime(2025, 2, 1, tzinfo=UTC),
        exit_ts=end,
        regime="low_spread",
        terminal=True,
        execution_cost=50.0,
        net_pnl=50.0,
    )
    result = _result(
        curve=curve,
        episodes=(high, low, at_end),
        terminal_episodes=(terminal,),
        monthly_returns=(
            ("2024-12", -0.20),
            ("2025-01", -0.25),
            ("2025-03", 0.10),
        ),
        max_drawdown=-0.50,
    )

    summary = scenario_window_summary(result, start=start, end=end)

    assert summary.baseline_equity == pytest.approx(80.0)
    assert summary.pre_window_peak_equity == pytest.approx(120.0)
    assert summary.ending_equity == pytest.approx(96.8)
    assert summary.equity_observations == 4
    assert summary.monthly_returns_pct.tolist() == pytest.approx([10.0, 0.0, 10.0])
    assert summary.monthly_returns_pct.attrs == {
        "missing_months": 0,
        "missing_return_pct": 0.0,
        "source": "15m_equity_curve",
    }
    assert summary.max_mtm_drawdown_pct == pytest.approx(50.0)
    assert summary.max_recovery_months == 3
    assert summary.monthly_active_exposure.tolist() == [True, True, True]
    assert summary.active_months == 3
    assert summary.active_month_definition == ACTIVE_MONTH_DEFINITION
    assert summary.closed_episodes == 2
    assert summary.high_spread_closed_episodes == 1
    assert summary.low_spread_closed_episodes == 1
    assert summary.closed_episode_execution_cost == pytest.approx(7.0)
    assert summary.closed_episode_funding_cashflow == pytest.approx(0.25)
    assert summary.closed_episode_gross_pair_price_pnl == pytest.approx(30.0)
    assert summary.closed_episode_adjusted_pair_price_pnl == pytest.approx(29.0)
    assert summary.closed_episode_net_pnl == pytest.approx(22.25)
    assert summary.terminal_pseudo_episodes == 0


def test_active_month_uses_observed_exposure_and_closed_exit_is_half_open() -> None:
    start = T0
    end = datetime(2025, 2, 1, tzinfo=UTC)
    exited_at_start = _episode(
        "boundary",
        entry_ts=datetime(2024, 12, 15, tzinfo=UTC),
        exit_ts=start,
    )
    result = _result(
        curve=((start, 100.0), (datetime(2025, 1, 15, tzinfo=UTC), 100.0)),
        episodes=(exited_at_start,),
    )

    active = monthly_active_exposure(result, start=start, end=end)
    summary = scenario_window_summary(result, start=start, end=end)

    assert active.tolist() == [False]
    assert active.attrs["definition"] == ACTIVE_MONTH_DEFINITION
    assert active.attrs["active_observations"] == 0
    assert summary.closed_episodes == 1
    assert summary.active_months == 0


def test_monthly_return_series_inserts_zero_for_a_month_with_no_nav_observation() -> None:
    start = T0
    end = datetime(2025, 4, 1, tzinfo=UTC)
    result = _result(
        curve=(
            (datetime(2024, 12, 31, 23, 45, tzinfo=UTC), 100.0),
            (datetime(2025, 1, 31, 23, 45, tzinfo=UTC), 110.0),
            (datetime(2025, 3, 31, 23, 45, tzinfo=UTC), 121.0),
        ),
        monthly_returns=(("2025-01", 0.10), ("2025-03", 0.10)),
    )

    summary = scenario_window_summary(result, start=start, end=end)

    assert summary.monthly_returns_pct.tolist() == pytest.approx([10.0, 0.0, 10.0])
    assert summary.monthly_returns_pct.attrs["missing_months"] == 1
    assert summary.monthly_active_exposure.tolist() == [False, False, False]


def test_adapter_rejects_naive_boundaries_non_increasing_nav_and_bad_terminal_count() -> None:
    with pytest.raises(ValueError, match="start must be timezone-aware UTC"):
        scenario_window_summary(
            _result(),
            start=datetime(2025, 1, 1),
            end=datetime(2025, 2, 1, tzinfo=UTC),
        )

    bad_curve = _result(curve=((T0 + timedelta(minutes=15), 100.0), (T0, 99.0)))
    with pytest.raises(ValueError, match="unique and increasing"):
        equity_series(bad_curve)

    terminal = _episode(
        "terminal",
        entry_ts=T0,
        exit_ts=T0 + timedelta(minutes=15),
        terminal=True,
    )
    bad_count = replace(
        _result(terminal_episodes=(terminal,)),
        open_pair_count=0,
        open_leg_count=0,
    )
    with pytest.raises(ValueError, match="open_pair_count"):
        terminal_episode_frame(bad_count)
