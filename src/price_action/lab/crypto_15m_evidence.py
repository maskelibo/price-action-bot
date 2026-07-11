"""Adapters from the crypto 15-minute engine records to validation evidence.

The event engine deliberately exposes immutable tuple/dataclass contracts.  The
validation layer works with pandas objects and percentage points.  This module
is the explicit unit and shape boundary between those two layers: engine
decimal returns and negative decimal drawdowns never pass through as if they
were validation-ready percentages.
"""

from __future__ import annotations

from dataclasses import dataclass, fields
from datetime import datetime, timedelta
from typing import Any

import numpy as np
import pandas as pd

from price_action.lab.crypto_15m_event_engine import PortfolioResult, TradeLedger


@dataclass(frozen=True, slots=True)
class ScenarioWindowSummary:
    """Validation-ready evidence for one half-open UTC scenario window."""

    start: pd.Timestamp
    end: pd.Timestamp
    baseline_equity: float
    pre_window_peak_equity: float
    ending_equity: float
    equity_observations: int
    monthly_returns_pct: pd.Series
    max_mtm_drawdown_pct: float
    max_recovery_months: int
    closed_trades: int
    long_closed_trades: int
    short_closed_trades: int
    closed_trade_execution_cost: float
    closed_trade_funding_cashflow: float
    closed_trade_net_pnl: float


def _portfolio_result(value: PortfolioResult) -> PortfolioResult:
    if not isinstance(value, PortfolioResult):
        raise TypeError("result must be a PortfolioResult")
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


def equity_series(result: PortfolioResult) -> pd.Series:
    """Convert the engine's equity tuple to a finite, ordered UTC Series."""

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


def ledger_frame(result: PortfolioResult) -> pd.DataFrame:
    """Convert closed trades while preserving every ``TradeLedger`` field."""

    result = _portfolio_result(result)
    field_names = tuple(field.name for field in fields(TradeLedger))
    records: list[dict[str, Any]] = []
    for position, trade in enumerate(result.trades):
        if not isinstance(trade, TradeLedger):
            raise TypeError(f"trades[{position}] must be a TradeLedger")
        records.append({name: getattr(trade, name) for name in field_names})

    frame = pd.DataFrame.from_records(records, columns=field_names)
    for column in ("decision_ts", "entry_ts", "exit_ts"):
        if frame.empty:
            frame[column] = pd.Series(dtype="datetime64[ns, UTC]")
            continue
        frame[column] = [
            _utc_timestamp(f"trades[{position}].{column}", value)
            for position, value in enumerate(frame[column])
        ]
    return frame


def engine_monthly_returns_pct(result: PortfolioResult) -> pd.Series:
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


def engine_max_drawdown_pct(result: PortfolioResult) -> float:
    """Convert the engine's non-positive decimal drawdown to a positive percent."""

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
    first_month = start.tz_localize(None).to_period("M")
    last_month = (end - pd.Timedelta(nanoseconds=1)).tz_localize(None).to_period("M")
    months = pd.period_range(first_month, last_month, freq="M", name="month")

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
    result: PortfolioResult,
    *,
    start: str | datetime | pd.Timestamp,
    end: str | datetime | pd.Timestamp,
) -> ScenarioWindowSummary:
    """Summarize one ``[start, end)`` window in validation-ready units.

    The first monthly return uses the last observed NAV before ``start``.  MTM
    drawdown carries the highest NAV observed before ``start`` (and the initial
    equity) so an underwater spell crossing the boundary cannot disappear.
    Closed-trade metrics are assigned by exit timestamp and therefore also obey
    the half-open interval.
    """

    result = _portfolio_result(result)
    start_ts = _utc_timestamp("start", start)
    end_ts = _utc_timestamp("end", end)
    if start_ts >= end_ts:
        raise ValueError("start must be before end")

    # Validate and explicitly acknowledge the engine's raw-unit contracts.  The
    # window metrics below are recomputed from 15m NAV and are never populated
    # by feeding these decimal engine fields into percentage-point validation.
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
    max_drawdown = _positive_mtm_drawdown_pct(window_equity, pre_window_peak)
    recovery_months = _monthly_recovery_length(month_end_equity, pre_window_peak)

    ledger = ledger_frame(result)
    closed = ledger.loc[(ledger["exit_ts"] >= start_ts) & (ledger["exit_ts"] < end_ts)]
    sides = closed["side"].astype(str).str.lower()

    return ScenarioWindowSummary(
        start=start_ts,
        end=end_ts,
        baseline_equity=baseline,
        pre_window_peak_equity=pre_window_peak,
        ending_equity=(float(window_equity.iloc[-1]) if not window_equity.empty else baseline),
        equity_observations=len(window_equity),
        monthly_returns_pct=monthly_returns,
        max_mtm_drawdown_pct=max_drawdown,
        max_recovery_months=recovery_months,
        closed_trades=len(closed),
        long_closed_trades=int((sides == "long").sum()),
        short_closed_trades=int((sides == "short").sum()),
        closed_trade_execution_cost=float(closed["execution_cost"].sum()),
        closed_trade_funding_cashflow=float(closed["funding_cashflow"].sum()),
        closed_trade_net_pnl=float(closed["net_pnl"].sum()),
    )


__all__ = [
    "ScenarioWindowSummary",
    "engine_max_drawdown_pct",
    "engine_monthly_returns_pct",
    "equity_series",
    "ledger_frame",
    "scenario_window_summary",
]
