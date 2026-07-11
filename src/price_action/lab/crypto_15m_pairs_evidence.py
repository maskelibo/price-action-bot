"""Validation evidence adapters for the causal v17 two-leg pair engine.

The pair engine exposes immutable tuple/dataclass records in decimal-return
units.  Validation consumes pandas objects and percentage points.  This module
is the explicit boundary between those contracts and, importantly, keeps
terminal open-pair MTM pseudo episodes separate from the closed sample count.
"""

from __future__ import annotations

from dataclasses import dataclass, fields
from datetime import datetime, timedelta
from typing import Any

import numpy as np
import pandas as pd

from price_action.lab.crypto_15m_pairs_engine import PairEpisodeLedger, PairPortfolioResult

ACTIVE_MONTH_DEFINITION = "at_least_one_equity_curve_observation_with_nonzero_open_pair_exposure"
_EPISODE_TIMESTAMP_COLUMNS = (
    "selection_ts",
    "decision_ts",
    "entry_ts",
    "exit_decision_ts",
    "exit_ts",
)
_EPISODE_FINITE_COLUMNS = (
    "gross_exposure",
    "gross_pair_price_pnl",
    "adjusted_pair_price_pnl",
    "y_funding_cashflow",
    "x_funding_cashflow",
    "execution_cost",
    "net_pnl",
)


@dataclass(frozen=True, slots=True)
class PairScenarioWindowSummary:
    """Validation-ready evidence for one half-open UTC scenario window."""

    start: pd.Timestamp
    end: pd.Timestamp
    baseline_equity: float
    pre_window_peak_equity: float
    ending_equity: float
    equity_observations: int
    monthly_returns_pct: pd.Series
    monthly_active_exposure: pd.Series
    active_months: int
    active_month_definition: str
    max_mtm_drawdown_pct: float
    max_recovery_months: int
    closed_episodes: int
    high_spread_closed_episodes: int
    low_spread_closed_episodes: int
    closed_episode_execution_cost: float
    closed_episode_funding_cashflow: float
    closed_episode_gross_pair_price_pnl: float
    closed_episode_adjusted_pair_price_pnl: float
    closed_episode_net_pnl: float
    terminal_pseudo_episodes: int


def _portfolio_result(value: PairPortfolioResult) -> PairPortfolioResult:
    if not isinstance(value, PairPortfolioResult):
        raise TypeError("result must be a PairPortfolioResult")
    return value


def _finite(name: str, value: Any, *, positive: bool = False) -> float:
    parsed = float(value)
    if not np.isfinite(parsed) or (positive and parsed <= 0.0):
        qualifier = "finite and > 0" if positive else "finite"
        raise ValueError(f"{name} must be {qualifier}")
    return parsed


def _utc_timestamp(name: str, value: str | datetime | pd.Timestamp) -> pd.Timestamp:
    try:
        timestamp = pd.Timestamp(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a valid timestamp") from exc
    if timestamp.tzinfo is None or timestamp.utcoffset() != timedelta(0):
        raise ValueError(f"{name} must be timezone-aware UTC")
    return timestamp.tz_convert("UTC")


def _window_boundaries(
    start: str | datetime | pd.Timestamp,
    end: str | datetime | pd.Timestamp,
) -> tuple[pd.Timestamp, pd.Timestamp]:
    start_ts = _utc_timestamp("start", start)
    end_ts = _utc_timestamp("end", end)
    if start_ts >= end_ts:
        raise ValueError("start must be before end")
    return start_ts, end_ts


def _window_months(start: pd.Timestamp, end: pd.Timestamp) -> pd.PeriodIndex:
    first = start.tz_localize(None).to_period("M")
    last = (end - pd.Timedelta(nanoseconds=1)).tz_localize(None).to_period("M")
    return pd.period_range(first, last, freq="M", name="month")


def equity_series(result: PairPortfolioResult) -> pd.Series:
    """Convert pair-engine NAV points to a finite, ordered UTC Series."""

    result = _portfolio_result(result)
    timestamps: list[pd.Timestamp] = []
    equities: list[float] = []
    for position, point in enumerate(result.equity_curve):
        if not isinstance(point, tuple) or len(point) != 2:
            raise ValueError("equity_curve entries must be (UTC timestamp, equity) tuples")
        timestamps.append(_utc_timestamp(f"equity_curve[{position}].timestamp", point[0]))
        equities.append(_finite(f"equity_curve[{position}].equity", point[1]))

    index = pd.DatetimeIndex(timestamps, tz="UTC", name="timestamp")
    if index.has_duplicates or not index.is_monotonic_increasing:
        raise ValueError("equity_curve timestamps must be unique and increasing")
    return pd.Series(equities, index=index, dtype=float, name="equity")


def _episode_frame(
    episodes: tuple[PairEpisodeLedger, ...],
    *,
    label: str,
    terminal: bool,
) -> pd.DataFrame:
    field_names = tuple(field.name for field in fields(PairEpisodeLedger))
    records: list[dict[str, Any]] = []
    for position, episode in enumerate(episodes):
        if not isinstance(episode, PairEpisodeLedger):
            raise TypeError(f"{label}[{position}] must be a PairEpisodeLedger")
        is_terminal_reason = episode.exit_reason == "terminal_open_mtm"
        if terminal != is_terminal_reason:
            expected = "terminal_open_mtm" if terminal else "a non-terminal exit reason"
            raise ValueError(f"{label}[{position}] must have {expected}")
        records.append({name: getattr(episode, name) for name in field_names})

    frame = pd.DataFrame.from_records(records, columns=field_names)
    for column in _EPISODE_TIMESTAMP_COLUMNS:
        if frame.empty:
            frame[column] = pd.Series(dtype="datetime64[ns, UTC]")
        else:
            frame[column] = [
                _utc_timestamp(f"{label}[{position}].{column}", value)
                for position, value in enumerate(frame[column])
            ]

    if frame.empty:
        return frame

    if (frame["selection_ts"] > frame["entry_ts"]).any():
        raise ValueError(f"{label} selection_ts cannot be after entry_ts")
    if terminal:
        invalid_lifecycle = frame["entry_ts"] > frame["exit_ts"]
    else:
        invalid_lifecycle = frame["entry_ts"] >= frame["exit_ts"]
    if invalid_lifecycle.any():
        relation = "<=" if terminal else "<"
        raise ValueError(f"{label} entry_ts must be {relation} exit_ts")
    if not frame["entry_regime"].isin(("high_spread", "low_spread")).all():
        raise ValueError(f"{label} contains an invalid entry_regime")

    for column in _EPISODE_FINITE_COLUMNS:
        numeric = pd.to_numeric(frame[column], errors="coerce")
        if not np.isfinite(numeric.to_numpy(dtype=float)).all():
            raise ValueError(f"{label}.{column} must be finite")
        frame[column] = numeric.astype(float)
    if (frame["gross_exposure"] <= 0.0).any():
        raise ValueError(f"{label}.gross_exposure must be > 0")
    if (frame["execution_cost"] < 0.0).any():
        raise ValueError(f"{label}.execution_cost must be >= 0")
    return frame


def closed_episode_frame(result: PairPortfolioResult) -> pd.DataFrame:
    """Return only genuinely closed pair episodes, preserving ledger fields."""

    result = _portfolio_result(result)
    return _episode_frame(result.episodes, label="episodes", terminal=False)


def terminal_episode_frame(result: PairPortfolioResult) -> pd.DataFrame:
    """Return terminal open-pair MTM pseudo episodes as a separate frame."""

    result = _portfolio_result(result)
    if result.open_pair_count != len(result.terminal_episodes):
        raise ValueError("open_pair_count must equal terminal_episodes length")
    if result.open_leg_count != 2 * result.open_pair_count:
        raise ValueError("open_leg_count must equal two times open_pair_count")
    return _episode_frame(result.terminal_episodes, label="terminal_episodes", terminal=True)


def economic_episode_frame(
    result: PairPortfolioResult,
    *,
    start: str | datetime | pd.Timestamp | None = None,
    end: str | datetime | pd.Timestamp | None = None,
) -> pd.DataFrame:
    """Return closed and terminal pseudo episodes for economic analysis.

    ``is_closed_sample`` is the authoritative sampling flag.  Terminal rows are
    included for direction and concentration calculations but remain false in
    that column.  When supplied, ``start`` and ``end`` filter episode valuation
    timestamps with the same ``[start, end)`` convention as window summaries.
    """

    if (start is None) != (end is None):
        raise ValueError("start and end must either both be supplied or both be omitted")

    closed = closed_episode_frame(result).copy()
    terminal = terminal_episode_frame(result).copy()
    closed["episode_kind"] = "closed"
    closed["is_closed_sample"] = True
    terminal["episode_kind"] = "terminal_open_mtm"
    terminal["is_closed_sample"] = False
    frame = pd.concat((closed, terminal), ignore_index=True)
    frame["funding_cashflow"] = frame["y_funding_cashflow"].astype(float) + frame[
        "x_funding_cashflow"
    ].astype(float)

    if start is not None and end is not None:
        start_ts, end_ts = _window_boundaries(start, end)
        frame = frame.loc[(frame["exit_ts"] >= start_ts) & (frame["exit_ts"] < end_ts)].reset_index(
            drop=True
        )
    frame.attrs["terminal_rows_are_closed_samples"] = False
    frame.attrs["terminal_usage"] = "economic_edge_direction_and_concentration"
    return frame


def engine_monthly_returns_pct(result: PairPortfolioResult) -> pd.Series:
    """Explicitly convert engine decimal monthly returns to percentage points."""

    result = _portfolio_result(result)
    periods: list[pd.Period] = []
    returns_pct: list[float] = []
    for position, point in enumerate(result.monthly_returns):
        if not isinstance(point, tuple) or len(point) != 2:
            raise ValueError("monthly_returns entries must be (YYYY-MM, decimal return) tuples")
        try:
            period = pd.Period(point[0], freq="M")
        except (TypeError, ValueError) as exc:
            raise ValueError(f"monthly_returns[{position}] has an invalid month") from exc
        decimal_return = _finite(f"monthly_returns[{position}].return", point[1])
        periods.append(period)
        returns_pct.append(decimal_return * 100.0)

    index = pd.PeriodIndex(periods, freq="M", name="month")
    if index.has_duplicates or not index.is_monotonic_increasing:
        raise ValueError("monthly_returns months must be unique and increasing")
    series = pd.Series(returns_pct, index=index, dtype=float, name="monthly_return_pct")
    series.attrs["source_unit"] = "engine_decimal"
    series.attrs["output_unit"] = "percentage_points"
    return series


def engine_max_drawdown_pct(result: PairPortfolioResult) -> float:
    """Convert the engine's non-positive decimal drawdown to positive percent."""

    result = _portfolio_result(result)
    decimal_drawdown = _finite("max_drawdown", result.max_drawdown)
    if decimal_drawdown > 0.0:
        raise ValueError("engine max_drawdown must be a non-positive decimal")
    return -decimal_drawdown * 100.0


def _continuous_monthly_returns_pct(
    window_equity: pd.Series,
    *,
    start: pd.Timestamp,
    end: pd.Timestamp,
    baseline: float,
) -> tuple[pd.Series, pd.Series]:
    months = _window_months(start, end)
    observed_months = window_equity.index.tz_localize(None).to_period("M")
    observed_closes = window_equity.groupby(observed_months).last()
    month_end_equity = observed_closes.reindex(months).ffill().fillna(baseline).astype(float)

    previous = month_end_equity.shift(1)
    previous.iloc[0] = baseline
    if (previous <= 0.0).any():
        raise ValueError("monthly return baseline equity must remain > 0")
    monthly_returns = (month_end_equity / previous - 1.0) * 100.0
    monthly_returns.name = "monthly_return_pct"
    monthly_returns.attrs["missing_months"] = len(months.difference(observed_closes.index))
    monthly_returns.attrs["missing_return_pct"] = 0.0
    monthly_returns.attrs["source"] = "15m_equity_curve"
    return monthly_returns.astype(float), month_end_equity


def monthly_active_exposure(
    result: PairPortfolioResult,
    *,
    start: str | datetime | pd.Timestamp,
    end: str | datetime | pd.Timestamp,
) -> pd.Series:
    """Mark months containing an observed 15m point with open pair exposure.

    Closed episodes are active on ``[entry_ts, exit_ts)`` because the atomic
    exit executes before the exit timestamp's NAV observation.  Terminal pseudo
    episodes are active through their terminal MTM observation.  The calculation
    uses only actual equity-curve timestamps, so a missing month is not silently
    inferred to have exposure.
    """

    result = _portfolio_result(result)
    start_ts, end_ts = _window_boundaries(start, end)
    months = _window_months(start_ts, end_ts)
    observations = (
        equity_series(result)
        .loc[lambda series: (series.index >= start_ts) & (series.index < end_ts)]
        .index
    )
    delta = np.zeros(len(observations) + 1, dtype=np.int64)

    def add_intervals(frame: pd.DataFrame, *, terminal: bool) -> None:
        for episode in frame.itertuples(index=False):
            left = int(observations.searchsorted(episode.entry_ts, side="left"))
            right_side = "right" if terminal else "left"
            right = int(observations.searchsorted(episode.exit_ts, side=right_side))
            if left < right:
                delta[left] += 1
                delta[right] -= 1

    add_intervals(closed_episode_frame(result), terminal=False)
    add_intervals(terminal_episode_frame(result), terminal=True)
    active_observations = np.cumsum(delta[:-1]) > 0

    if len(observations):
        observation_months = observations.tz_localize(None).to_period("M")
        observed = pd.Series(active_observations, index=observation_months).groupby(level=0).any()
        monthly = observed.reindex(months, fill_value=False).astype(bool)
    else:
        monthly = pd.Series(False, index=months, dtype=bool)
    monthly.name = "has_active_pair_exposure"
    monthly.attrs["definition"] = ACTIVE_MONTH_DEFINITION
    monthly.attrs["interval_inference"] = (
        "closed_[entry,exit);terminal_[entry,terminal_observation]"
    )
    monthly.attrs["active_observations"] = int(active_observations.sum())
    return monthly


def _positive_mtm_drawdown_pct(window_equity: pd.Series, pre_window_peak: float) -> float:
    peak = pre_window_peak
    maximum = 0.0
    for equity in window_equity.to_numpy(dtype=float):
        peak = max(peak, equity)
        maximum = max(maximum, (peak - equity) / peak * 100.0)
    return float(maximum)


def _monthly_recovery_length(month_end_equity: pd.Series, pre_window_peak: float) -> int:
    peak = pre_window_peak
    current = 0
    longest = 0
    for equity in month_end_equity.to_numpy(dtype=float):
        if equity >= peak - 1e-12:
            peak = max(peak, equity)
            current = 0
        else:
            current += 1
            longest = max(longest, current)
    return longest


def scenario_window_summary(
    result: PairPortfolioResult,
    *,
    start: str | datetime | pd.Timestamp,
    end: str | datetime | pd.Timestamp,
) -> PairScenarioWindowSummary:
    """Summarize one ``[start, end)`` pair-strategy evidence window.

    Monthly returns carry the last observed pre-window NAV.  Drawdown also
    carries the highest pre-window NAV, so an underwater spell cannot disappear
    at a split boundary.  Closed sample metrics are assigned by exit timestamp;
    terminal open-pair rows are reported separately and never increase the
    closed episode or direction counts.
    """

    result = _portfolio_result(result)
    start_ts, end_ts = _window_boundaries(start, end)

    # Validate, but do not use, the engine's aggregate decimal fields.  Window
    # percentages are recomputed from NAV so no decimal/percentage mix can leak.
    engine_max_drawdown_pct(result)
    engine_monthly_returns_pct(result)

    equity = equity_series(result)
    initial_equity = _finite("initial_equity", result.initial_equity, positive=True)
    before = equity.loc[equity.index < start_ts]
    baseline = float(before.iloc[-1]) if not before.empty else initial_equity
    baseline = _finite("pre-window baseline equity", baseline, positive=True)
    pre_window_peak = max(
        initial_equity, float(before.max()) if not before.empty else initial_equity
    )
    pre_window_peak = _finite("pre-window peak equity", pre_window_peak, positive=True)

    window_equity = equity.loc[(equity.index >= start_ts) & (equity.index < end_ts)]
    monthly_returns, month_end_equity = _continuous_monthly_returns_pct(
        window_equity,
        start=start_ts,
        end=end_ts,
        baseline=baseline,
    )
    active = monthly_active_exposure(result, start=start_ts, end=end_ts)
    max_drawdown = _positive_mtm_drawdown_pct(window_equity, pre_window_peak)
    recovery_months = _monthly_recovery_length(month_end_equity, pre_window_peak)

    ledger = closed_episode_frame(result)
    closed = ledger.loc[(ledger["exit_ts"] >= start_ts) & (ledger["exit_ts"] < end_ts)]
    regimes = closed["entry_regime"].astype(str)
    funding_cashflow = closed["y_funding_cashflow"].sum() + closed["x_funding_cashflow"].sum()
    terminal = terminal_episode_frame(result)
    terminal_in_window = terminal.loc[
        (terminal["exit_ts"] >= start_ts) & (terminal["exit_ts"] < end_ts)
    ]

    return PairScenarioWindowSummary(
        start=start_ts,
        end=end_ts,
        baseline_equity=baseline,
        pre_window_peak_equity=pre_window_peak,
        ending_equity=(float(window_equity.iloc[-1]) if not window_equity.empty else baseline),
        equity_observations=len(window_equity),
        monthly_returns_pct=monthly_returns,
        monthly_active_exposure=active,
        active_months=int(active.sum()),
        active_month_definition=ACTIVE_MONTH_DEFINITION,
        max_mtm_drawdown_pct=max_drawdown,
        max_recovery_months=recovery_months,
        closed_episodes=len(closed),
        high_spread_closed_episodes=int((regimes == "high_spread").sum()),
        low_spread_closed_episodes=int((regimes == "low_spread").sum()),
        closed_episode_execution_cost=float(closed["execution_cost"].sum()),
        closed_episode_funding_cashflow=float(funding_cashflow),
        closed_episode_gross_pair_price_pnl=float(closed["gross_pair_price_pnl"].sum()),
        closed_episode_adjusted_pair_price_pnl=float(closed["adjusted_pair_price_pnl"].sum()),
        closed_episode_net_pnl=float(closed["net_pnl"].sum()),
        terminal_pseudo_episodes=len(terminal_in_window),
    )


__all__ = [
    "ACTIVE_MONTH_DEFINITION",
    "PairScenarioWindowSummary",
    "closed_episode_frame",
    "economic_episode_frame",
    "engine_max_drawdown_pct",
    "engine_monthly_returns_pct",
    "equity_series",
    "monthly_active_exposure",
    "scenario_window_summary",
    "terminal_episode_frame",
]
