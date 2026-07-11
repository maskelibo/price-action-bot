"""Causal 15-minute crypto portfolio simulator for preregistered research.

The module is deliberately self-contained and side-effect free: it accepts
already-loaded OHLCV frames and funding events, performs no file/network IO,
and returns immutable evidence records.
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

import pandas as pd

Side = Literal["long", "short"]


def _require_finite(name: str, value: float, *, positive: bool = False) -> float:
    parsed = float(value)
    if not math.isfinite(parsed) or (positive and parsed <= 0):
        qualifier = "finite and > 0" if positive else "finite"
        raise ValueError(f"{name} must be {qualifier}")
    return parsed


def _require_utc(name: str, value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware UTC")
    normalized = value.astimezone(UTC)
    if value.utcoffset().total_seconds() != 0:
        raise ValueError(f"{name} must be UTC")
    return normalized


@dataclass(frozen=True, slots=True)
class SignalIntent:
    """One signal known at the close of the bar labelled ``decision_ts``.

    OHLCV timestamps are bar-open labels.  Therefore an accepted intent enters
    only at the open of the next exactly-contiguous 15-minute bar.
    """

    candidate_id: str
    decision_ts: datetime
    symbol: str
    side: Side
    score: float
    atr: float
    stop_atr_multiple: float
    hold_bars: int

    def __post_init__(self) -> None:
        if not str(self.candidate_id).strip():
            raise ValueError("candidate_id must be non-empty")
        if not str(self.symbol).strip():
            raise ValueError("symbol must be non-empty")
        if self.side not in {"long", "short"}:
            raise ValueError("side must be long or short")
        if isinstance(self.hold_bars, bool) or int(self.hold_bars) < 1:
            raise ValueError("hold_bars must be an integer >= 1")
        object.__setattr__(self, "decision_ts", _require_utc("decision_ts", self.decision_ts))
        object.__setattr__(self, "score", _require_finite("score", self.score))
        object.__setattr__(self, "atr", _require_finite("atr", self.atr, positive=True))
        object.__setattr__(
            self,
            "stop_atr_multiple",
            _require_finite("stop_atr_multiple", self.stop_atr_multiple, positive=True),
        )
        object.__setattr__(self, "hold_bars", int(self.hold_bars))


@dataclass(frozen=True, slots=True)
class CostModel:
    """Auditable execution/funding costs; bps values are per executed leg.

    ``cost_multiplier`` applies only to execution components and
    ``funding_multiplier`` applies only to funding.  Keeping those stress knobs
    orthogonal prevents a scenario that doubles both from charging funding four
    times.
    """

    fee_bps_per_leg: float = 4.0
    spread_slippage_bps_per_leg: float = 20.0
    impact_bps_per_leg: float = 4.5
    funding_multiplier: float = 1.0
    cost_multiplier: float = 1.0

    def __post_init__(self) -> None:
        for name in (
            "fee_bps_per_leg",
            "spread_slippage_bps_per_leg",
            "impact_bps_per_leg",
            "funding_multiplier",
            "cost_multiplier",
        ):
            value = _require_finite(name, getattr(self, name))
            if value < 0:
                raise ValueError(f"{name} must be >= 0")
            object.__setattr__(self, name, value)


@dataclass(frozen=True, slots=True)
class PortfolioPolicy:
    """Frozen portfolio/risk policy used by the preregistered simulator."""

    initial_equity: float = 10_000.0
    risk_per_trade: float = 0.005
    max_symbol_notional_pct: float = 0.15
    max_positions: int = 6
    max_same_side: int = 3
    leverage: float = 3.0
    dd_throttle_threshold: float = 0.06
    dd_throttle_multiplier: float = 0.5
    gap_max_minutes: int = 30
    warmup_bars_after_gap: int = 500
    bar_minutes: int = 15

    def __post_init__(self) -> None:
        for name in (
            "initial_equity",
            "risk_per_trade",
            "max_symbol_notional_pct",
            "leverage",
            "dd_throttle_threshold",
            "dd_throttle_multiplier",
        ):
            value = _require_finite(name, getattr(self, name), positive=True)
            object.__setattr__(self, name, value)
        for name in (
            "max_positions",
            "max_same_side",
            "gap_max_minutes",
            "bar_minutes",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or int(value) < 1:
                raise ValueError(f"{name} must be an integer >= 1")
            object.__setattr__(self, name, int(value))
        if isinstance(self.warmup_bars_after_gap, bool) or int(self.warmup_bars_after_gap) < 0:
            raise ValueError("warmup_bars_after_gap must be an integer >= 0")
        object.__setattr__(self, "warmup_bars_after_gap", int(self.warmup_bars_after_gap))
        if self.risk_per_trade > 1 or self.max_symbol_notional_pct > 1:
            raise ValueError("risk and symbol cap must be fractional values <= 1")
        if self.dd_throttle_threshold > 1 or self.dd_throttle_multiplier > 1:
            raise ValueError("drawdown throttle values must be <= 1")
        if self.max_same_side > self.max_positions:
            raise ValueError("max_same_side cannot exceed max_positions")


@dataclass(frozen=True, slots=True)
class TradeLedger:
    candidate_id: str
    symbol: str
    side: Side
    decision_ts: datetime
    entry_ts: datetime
    exit_ts: datetime
    exit_reason: str
    entry_price: float
    exit_price: float
    stop_price: float
    quantity: float
    entry_notional: float
    risk_budget: float
    bars_held: int
    gross_price_pnl: float
    payoff_multiplier: float
    adjusted_price_pnl: float
    entry_fee: float
    entry_spread_slippage: float
    entry_impact: float
    exit_fee: float
    exit_spread_slippage: float
    exit_impact: float
    funding_cashflow: float
    execution_cost: float
    net_pnl: float
    equity_before_entry: float
    equity_after_exit: float


@dataclass(frozen=True, slots=True)
class PortfolioResult:
    trades: tuple[TradeLedger, ...]
    equity_curve: tuple[tuple[datetime, float], ...]
    monthly_returns: tuple[tuple[str, float], ...]
    rejections: tuple[tuple[str, str], ...]
    initial_equity: float
    final_equity: float
    max_drawdown: float
    total_execution_cost: float
    accrued_exit_cost: float
    total_funding_cashflow: float
    open_position_count: int


@dataclass(slots=True)
class _Position:
    intent: SignalIntent
    entry_ts: datetime
    entry_price: float
    stop_price: float
    quantity: float
    entry_notional: float
    risk_budget: float
    bars_held: int
    entry_fee: float
    entry_spread_slippage: float
    entry_impact: float
    funding_cashflow: float
    equity_before_entry: float
    last_bar_ts: datetime


@dataclass(frozen=True, slots=True)
class _Funding:
    ts: datetime
    symbol: str
    rate: float
    mark_price: float | None


def _execution_components(notional: float, cost: CostModel) -> tuple[float, float, float]:
    scale = float(notional) * cost.cost_multiplier / 10_000.0
    return (
        scale * cost.fee_bps_per_leg,
        scale * cost.spread_slippage_bps_per_leg,
        scale * cost.impact_bps_per_leg,
    )


def _normalize_frames(
    frames: Mapping[str, pd.DataFrame], policy: PortfolioPolicy
) -> tuple[
    dict[str, list[dict[str, Any]]],
    dict[str, dict[datetime, int]],
    dict[str, list[int]],
]:
    if not isinstance(frames, Mapping) or not frames:
        raise ValueError("frames must be a non-empty symbol -> DataFrame mapping")
    normalized: dict[str, list[dict[str, Any]]] = {}
    index_by_ts: dict[str, dict[datetime, int]] = {}
    run_lengths: dict[str, list[int]] = {}
    bar_delta = timedelta(minutes=policy.bar_minutes)
    for raw_symbol, raw_frame in frames.items():
        symbol = str(raw_symbol).strip()
        if not symbol or not isinstance(raw_frame, pd.DataFrame):
            raise ValueError("every frame must have a non-empty symbol and be a DataFrame")
        missing = {"ts", "open", "high", "low", "close"} - set(raw_frame.columns)
        if missing:
            raise ValueError(f"{symbol} frame missing columns: {sorted(missing)}")
        rows: list[dict[str, Any]] = []
        for record in raw_frame.loc[:, ["ts", "open", "high", "low", "close"]].to_dict("records"):
            raw_ts = record["ts"]
            if isinstance(raw_ts, pd.Timestamp):
                raw_ts = raw_ts.to_pydatetime()
            ts = _require_utc(f"{symbol}.ts", raw_ts)
            values = {
                name: _require_finite(f"{symbol}.{name}", record[name], positive=True)
                for name in ("open", "high", "low", "close")
            }
            if values["high"] < max(values["open"], values["low"], values["close"]):
                raise ValueError(f"{symbol} has invalid OHLC high at {ts.isoformat()}")
            if values["low"] > min(values["open"], values["high"], values["close"]):
                raise ValueError(f"{symbol} has invalid OHLC low at {ts.isoformat()}")
            rows.append({"ts": ts, **values})
        rows.sort(key=lambda row: row["ts"])
        timestamps = [row["ts"] for row in rows]
        if len(timestamps) != len(set(timestamps)):
            raise ValueError(f"{symbol} frame has duplicate timestamps")
        runs: list[int] = []
        for idx, ts in enumerate(timestamps):
            if idx == 0 or ts - timestamps[idx - 1] != bar_delta:
                runs.append(1)
            else:
                runs.append(runs[-1] + 1)
        normalized[symbol] = rows
        index_by_ts[symbol] = {ts: idx for idx, ts in enumerate(timestamps)}
        run_lengths[symbol] = runs
    return normalized, index_by_ts, run_lengths


def _normalize_funding(
    funding_events: Iterable[Mapping[str, Any]] | Mapping[str, pd.DataFrame] | pd.DataFrame | None,
) -> list[_Funding]:
    if funding_events is None:
        return []
    records: list[dict[str, Any]] = []
    if isinstance(funding_events, pd.DataFrame):
        records.extend(funding_events.to_dict("records"))
    elif isinstance(funding_events, Mapping):
        for symbol, frame in funding_events.items():
            if not isinstance(frame, pd.DataFrame):
                raise ValueError("mapped funding events must be DataFrames")
            for record in frame.to_dict("records"):
                records.append({"symbol": symbol, **record})
    else:
        records.extend(dict(record) for record in funding_events)
    out: list[_Funding] = []
    for record in records:
        if not {"symbol", "ts", "rate"} <= set(record):
            raise ValueError("funding event requires symbol, ts and rate")
        raw_ts = record["ts"]
        if isinstance(raw_ts, pd.Timestamp):
            raw_ts = raw_ts.to_pydatetime()
        mark = record.get("mark_price")
        out.append(
            _Funding(
                ts=_require_utc("funding.ts", raw_ts),
                symbol=str(record["symbol"]),
                rate=_require_finite("funding.rate", record["rate"]),
                mark_price=(
                    _require_finite("funding.mark_price", mark, positive=True)
                    if mark is not None
                    else None
                ),
            )
        )
    return sorted(out, key=lambda event: (event.ts, event.symbol))


def _monthly_returns(
    curve: list[tuple[datetime, float]], initial_equity: float
) -> tuple[tuple[str, float], ...]:
    month_end: dict[str, float] = {}
    for ts, nav in curve:
        month_end[f"{ts.year:04d}-{ts.month:02d}"] = nav
    previous = initial_equity
    result: list[tuple[str, float]] = []
    for month in sorted(month_end):
        nav = month_end[month]
        result.append((month, nav / previous - 1.0 if previous > 0 else 0.0))
        previous = nav
    return tuple(result)


def simulate_portfolio(
    frames: Mapping[str, pd.DataFrame],
    intents: Iterable[SignalIntent],
    funding_events: Iterable[Mapping[str, Any]]
    | Mapping[str, pd.DataFrame]
    | pd.DataFrame
    | None = None,
    cost: CostModel | None = None,
    policy: PortfolioPolicy | None = None,
    *,
    positive_payoff_multiplier: float = 1.0,
    negative_payoff_multiplier: float = 1.0,
) -> PortfolioResult:
    """Run one causal portfolio replay over immutable in-memory inputs.

    A payoff multiplier changes price PnL only.  Fees, spread/slippage,
    impact and funding remain separately charged, preventing cost double count.
    """

    cost = cost or CostModel()
    policy = policy or PortfolioPolicy()
    positive_mult = _require_finite(
        "positive_payoff_multiplier", positive_payoff_multiplier, positive=True
    )
    negative_mult = _require_finite(
        "negative_payoff_multiplier", negative_payoff_multiplier, positive=True
    )
    bars, index_by_ts, run_lengths = _normalize_frames(frames, policy)
    funding = _normalize_funding(funding_events)
    bar_delta = timedelta(minutes=policy.bar_minutes)
    gap_limit = timedelta(minutes=policy.gap_max_minutes)

    intents_list = list(intents)
    if any(not isinstance(intent, SignalIntent) for intent in intents_list):
        raise TypeError("intents must contain SignalIntent values")

    scheduled: dict[datetime, list[SignalIntent]] = defaultdict(list)
    rejections: list[tuple[str, str]] = []
    for intent in sorted(
        intents_list,
        key=lambda item: (
            item.decision_ts,
            -item.score,
            item.symbol,
            item.candidate_id,
            item.side,
        ),
    ):
        symbol_rows = bars.get(intent.symbol)
        decision_idx = index_by_ts.get(intent.symbol, {}).get(intent.decision_ts)
        if symbol_rows is None or decision_idx is None:
            rejections.append((intent.candidate_id, "decision_bar_missing"))
            continue
        if run_lengths[intent.symbol][decision_idx] < policy.warmup_bars_after_gap:
            rejections.append((intent.candidate_id, "warmup_incomplete"))
            continue
        if decision_idx + 1 >= len(symbol_rows):
            rejections.append((intent.candidate_id, "next_bar_missing"))
            continue
        next_ts = symbol_rows[decision_idx + 1]["ts"]
        if next_ts - intent.decision_ts != bar_delta:
            rejections.append((intent.candidate_id, "next_bar_not_contiguous"))
            continue
        scheduled[next_ts].append(intent)

    bars_by_ts: dict[datetime, list[tuple[str, dict[str, Any]]]] = defaultdict(list)
    for symbol, rows in bars.items():
        for row in rows:
            bars_by_ts[row["ts"]].append((symbol, row))

    cash = policy.initial_equity
    peak_nav = policy.initial_equity
    marks: dict[str, float] = {}
    positions: dict[str, _Position] = {}
    ledgers: list[TradeLedger] = []
    curve: list[tuple[datetime, float]] = []
    total_execution_cost = 0.0
    total_funding = 0.0
    funding_idx = 0

    def nav() -> float:
        unrealized = 0.0
        for symbol, position in positions.items():
            mark = marks.get(symbol, position.entry_price)
            direction = 1.0 if position.intent.side == "long" else -1.0
            gross = direction * (mark - position.entry_price) * position.quantity
            payoff_mult = positive_mult if gross > 0 else negative_mult if gross < 0 else 1.0
            liquidation_cost = sum(_execution_components(mark * position.quantity, cost))
            unrealized += gross * payoff_mult - liquidation_cost
        return cash + unrealized

    def close_position(symbol: str, price: float, reason: str, ts: datetime) -> None:
        nonlocal cash, total_execution_cost
        position = positions.pop(symbol)
        direction = 1.0 if position.intent.side == "long" else -1.0
        gross = direction * (price - position.entry_price) * position.quantity
        payoff_mult = positive_mult if gross > 0 else negative_mult if gross < 0 else 1.0
        adjusted = gross * payoff_mult
        exit_notional = price * position.quantity
        exit_fee, exit_spread, exit_impact = _execution_components(exit_notional, cost)
        exit_cost = exit_fee + exit_spread + exit_impact
        cash += adjusted - exit_cost
        entry_cost = position.entry_fee + position.entry_spread_slippage + position.entry_impact
        execution_cost = entry_cost + exit_cost
        total_execution_cost += exit_cost
        marks[symbol] = price
        equity_after = nav()
        ledgers.append(
            TradeLedger(
                candidate_id=position.intent.candidate_id,
                symbol=symbol,
                side=position.intent.side,
                decision_ts=position.intent.decision_ts,
                entry_ts=position.entry_ts,
                exit_ts=ts,
                exit_reason=reason,
                entry_price=position.entry_price,
                exit_price=price,
                stop_price=position.stop_price,
                quantity=position.quantity,
                entry_notional=position.entry_notional,
                risk_budget=position.risk_budget,
                bars_held=position.bars_held,
                gross_price_pnl=gross,
                payoff_multiplier=payoff_mult,
                adjusted_price_pnl=adjusted,
                entry_fee=position.entry_fee,
                entry_spread_slippage=position.entry_spread_slippage,
                entry_impact=position.entry_impact,
                exit_fee=exit_fee,
                exit_spread_slippage=exit_spread,
                exit_impact=exit_impact,
                funding_cashflow=position.funding_cashflow,
                execution_cost=execution_cost,
                net_pnl=adjusted - execution_cost + position.funding_cashflow,
                equity_before_entry=position.equity_before_entry,
                equity_after_exit=equity_after,
            )
        )

    for ts in sorted(bars_by_ts):
        current_rows = sorted(bars_by_ts[ts], key=lambda item: item[0])

        while funding_idx < len(funding) and funding[funding_idx].ts <= ts:
            event = funding[funding_idx]
            position = positions.get(event.symbol)
            if position is not None:
                mark = event.mark_price or marks.get(event.symbol, position.entry_price)
                notional = mark * position.quantity
                direction = 1.0 if position.intent.side == "long" else -1.0
                cashflow = -direction * notional * event.rate * cost.funding_multiplier
                cash += cashflow
                position.funding_cashflow += cashflow
                total_funding += cashflow
            funding_idx += 1

        # Every decision at this timestamp observes opens only, never current-bar highs/lows.
        for symbol, row in current_rows:
            marks[symbol] = row["open"]
            position = positions.get(symbol)
            if position is not None and ts - position.last_bar_ts > gap_limit:
                close_position(symbol, row["open"], "data_gap", ts)

        entry_rows = {symbol: row for symbol, row in current_rows}
        for intent in sorted(
            scheduled.get(ts, []),
            key=lambda item: (-item.score, item.symbol, item.candidate_id, item.side),
        ):
            if intent.symbol in positions:
                rejections.append((intent.candidate_id, "symbol_already_open"))
                continue
            if len(positions) >= policy.max_positions:
                rejections.append((intent.candidate_id, "max_positions"))
                continue
            if (
                sum(position.intent.side == intent.side for position in positions.values())
                >= policy.max_same_side
            ):
                rejections.append((intent.candidate_id, "max_same_side"))
                continue
            row = entry_rows.get(intent.symbol)
            if row is None:
                rejections.append((intent.candidate_id, "entry_bar_missing"))
                continue
            current_nav = nav()
            if current_nav <= 0:
                rejections.append((intent.candidate_id, "non_positive_equity"))
                continue
            dd = (peak_nav - current_nav) / peak_nav if peak_nav > 0 else 0.0
            throttle = policy.dd_throttle_multiplier if dd >= policy.dd_throttle_threshold else 1.0
            risk_budget = current_nav * policy.risk_per_trade * throttle
            entry_price = row["open"]
            stop_distance = intent.atr * intent.stop_atr_multiple
            quantity = risk_budget / stop_distance
            quantity = min(
                quantity,
                current_nav * policy.max_symbol_notional_pct / entry_price,
            )
            used_margin = sum(
                position.entry_notional / policy.leverage for position in positions.values()
            )
            margin_headroom = max(current_nav - used_margin, 0.0)
            quantity = min(quantity, margin_headroom * policy.leverage / entry_price)
            stop_price = (
                entry_price - stop_distance
                if intent.side == "long"
                else entry_price + stop_distance
            )
            if quantity <= 0 or stop_price <= 0:
                rejections.append((intent.candidate_id, "invalid_size_or_stop"))
                continue
            notional = quantity * entry_price
            entry_fee, entry_spread, entry_impact = _execution_components(notional, cost)
            entry_cost = entry_fee + entry_spread + entry_impact
            cash -= entry_cost
            total_execution_cost += entry_cost
            positions[intent.symbol] = _Position(
                intent=intent,
                entry_ts=ts,
                entry_price=entry_price,
                stop_price=stop_price,
                quantity=quantity,
                entry_notional=notional,
                risk_budget=risk_budget,
                bars_held=0,
                entry_fee=entry_fee,
                entry_spread_slippage=entry_spread,
                entry_impact=entry_impact,
                funding_cashflow=0.0,
                equity_before_entry=current_nav,
                last_bar_ts=ts,
            )

        # Pessimistic within-bar policy: a touched stop always wins over time exit.
        for symbol, row in current_rows:
            position = positions.get(symbol)
            if position is None:
                marks[symbol] = row["close"]
                continue
            position.bars_held += 1
            position.last_bar_ts = ts
            stopped = (
                row["low"] <= position.stop_price
                if position.intent.side == "long"
                else row["high"] >= position.stop_price
            )
            if stopped:
                stop_fill = (
                    min(row["open"], position.stop_price)
                    if position.intent.side == "long"
                    else max(row["open"], position.stop_price)
                )
                close_position(symbol, stop_fill, "stop", ts)
            elif position.bars_held >= position.intent.hold_bars:
                close_position(symbol, row["close"], "time", ts)
            else:
                marks[symbol] = row["close"]

        current_nav = nav()
        peak_nav = max(peak_nav, current_nav)
        # NAV is measured after the bar close but retains the source bar-open
        # label.  This assigns the 23:45 bar to the month it economically closes
        # instead of shifting it to 00:00 of the following month.
        curve.append((ts, current_nav))

    max_drawdown = 0.0
    running_peak = policy.initial_equity
    for _, point_nav in curve:
        running_peak = max(running_peak, point_nav)
        if running_peak > 0:
            max_drawdown = min(max_drawdown, point_nav / running_peak - 1.0)

    accrued_exit_cost = sum(
        sum(
            _execution_components(
                marks.get(symbol, position.entry_price) * position.quantity,
                cost,
            )
        )
        for symbol, position in positions.items()
    )
    return PortfolioResult(
        trades=tuple(ledgers),
        equity_curve=tuple(curve),
        monthly_returns=_monthly_returns(curve, policy.initial_equity),
        rejections=tuple(rejections),
        initial_equity=policy.initial_equity,
        final_equity=nav(),
        max_drawdown=max_drawdown,
        total_execution_cost=total_execution_cost,
        accrued_exit_cost=accrued_exit_cost,
        total_funding_cashflow=total_funding,
        open_position_count=len(positions),
    )


__all__ = [
    "CostModel",
    "PortfolioPolicy",
    "PortfolioResult",
    "SignalIntent",
    "TradeLedger",
    "simulate_portfolio",
]
