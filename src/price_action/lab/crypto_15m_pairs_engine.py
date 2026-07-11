"""Causal atomic two-leg portfolio engine for the preregistered v17 pair study.

The module performs no file or network IO.  Pair selection and entry signal
generation are deliberately external; an entry intent carries the frozen model
that remains attached to its episode until both legs exit together.
"""

from __future__ import annotations

import math
from bisect import bisect_left, bisect_right
from collections import defaultdict, deque
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal, Protocol

import numpy as np
import pandas as pd

from price_action.lab.crypto_15m_pairs_signals import PairEntryIntent, PairModel

LegSide = Literal["long", "short"]
EntryRegime = Literal["high_spread", "low_spread"]


class PairModelLike(Protocol):
    candidate_id: str
    pair_id: str
    selection_ts: datetime


class PairEntryIntentLike(Protocol):
    candidate_id: str
    pair_id: str
    selection_ts: datetime
    decision_ts: datetime
    entry_ts: datetime
    y_symbol: str
    x_symbol: str
    y_side: LegSide
    x_side: LegSide
    z_score: float
    alpha: float
    beta: float
    validation_mean: float
    validation_std: float
    gross_weight_y: float
    gross_weight_x: float
    entry_abs_z: float
    exit_abs_z: float
    disaster_abs_z: float
    max_hold_hours: int
    cooldown_hours: int
    expected_convergence_return: float
    adverse_funding: float
    stressed_required_return: float
    economic_buffer_multiplier: float
    base_round_trip_cost_per_gross: float
    c2_round_trip_cost_per_gross: float


def _finite(name: str, value: Any, *, positive: bool = False) -> float:
    parsed = float(value)
    if not math.isfinite(parsed) or (positive and parsed <= 0.0):
        qualifier = "finite and > 0" if positive else "finite"
        raise ValueError(f"{name} must be {qualifier}")
    return parsed


def _positive_int(name: str, value: Any, *, allow_zero: bool = False) -> int:
    minimum = 0 if allow_zero else 1
    if isinstance(value, bool) or int(value) != value or int(value) < minimum:
        qualifier = ">= 0" if allow_zero else ">= 1"
        raise ValueError(f"{name} must be an integer {qualifier}")
    return int(value)


def _utc(name: str, value: Any) -> datetime:
    if isinstance(value, pd.Timestamp):
        value = value.to_pydatetime()
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware UTC")
    if value.utcoffset() != timedelta(0):
        raise ValueError(f"{name} must be UTC")
    return value.astimezone(UTC)


@dataclass(frozen=True, slots=True)
class PairCostModel:
    """Per-fill execution and observed funding cost assumptions."""

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
            value = _finite(name, getattr(self, name))
            if value < 0.0:
                raise ValueError(f"{name} must be >= 0")
            object.__setattr__(self, name, value)


@dataclass(frozen=True, slots=True)
class PairPortfolioPolicy:
    """Frozen common-equity and risk policy for one candidate replay."""

    initial_equity: float = 10_000.0
    risk_per_pair_episode: float = 0.005
    max_leg_notional_pct: float = 0.15
    max_pairs: int = 3
    max_legs: int = 6
    leverage: float = 3.0
    dd_throttle_threshold: float = 0.06
    dd_throttle_multiplier: float = 0.5
    gap_max_minutes: int = 30
    bar_minutes: int = 15
    structural_mean_window_hours: int = 48
    structural_distance_sigma: float = 1.5
    structural_consecutive_hourly_checks: int = 4
    structural_min_completeness: float = 0.95

    def __post_init__(self) -> None:
        for name in (
            "initial_equity",
            "risk_per_pair_episode",
            "max_leg_notional_pct",
            "leverage",
            "dd_throttle_threshold",
            "dd_throttle_multiplier",
            "structural_distance_sigma",
            "structural_min_completeness",
        ):
            value = _finite(name, getattr(self, name), positive=True)
            object.__setattr__(self, name, value)
        for name in (
            "max_pairs",
            "max_legs",
            "gap_max_minutes",
            "bar_minutes",
            "structural_mean_window_hours",
            "structural_consecutive_hourly_checks",
        ):
            object.__setattr__(self, name, _positive_int(name, getattr(self, name)))
        if self.risk_per_pair_episode > 1.0 or self.max_leg_notional_pct > 1.0:
            raise ValueError("risk and leg cap must be fractions <= 1")
        if self.dd_throttle_threshold > 1.0 or self.dd_throttle_multiplier > 1.0:
            raise ValueError("drawdown throttle values must be <= 1")
        if not 0.0 < self.structural_min_completeness <= 1.0:
            raise ValueError("structural_min_completeness must be in (0, 1]")
        if self.max_legs < 2 or self.max_legs < 2 * self.max_pairs:
            raise ValueError("max_legs must accommodate two legs per max_pairs")
        bars_per_hour = 60 / self.bar_minutes
        if not bars_per_hour.is_integer():
            raise ValueError("bar_minutes must divide one hour")


@dataclass(frozen=True, slots=True)
class PairSelectionEvent:
    """The complete selected pair set for one candidate at a monthly boundary."""

    candidate_id: str
    selection_ts: datetime
    selected_pair_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        candidate = str(self.candidate_id).strip()
        if not candidate:
            raise ValueError("candidate_id must be non-empty")
        pairs = tuple(str(pair).strip() for pair in self.selected_pair_ids)
        if any(not pair for pair in pairs) or len(pairs) != len(set(pairs)):
            raise ValueError("selected_pair_ids must be non-empty and unique")
        object.__setattr__(self, "candidate_id", candidate)
        object.__setattr__(self, "selection_ts", _utc("selection_ts", self.selection_ts))
        object.__setattr__(self, "selected_pair_ids", tuple(sorted(pairs)))


@dataclass(frozen=True, slots=True)
class PairEpisodeLedger:
    candidate_id: str
    pair_id: str
    selection_ts: datetime
    y_symbol: str
    x_symbol: str
    entry_regime: EntryRegime
    y_side: LegSide
    x_side: LegSide
    decision_ts: datetime
    entry_ts: datetime
    exit_decision_ts: datetime
    exit_ts: datetime
    exit_reason: str
    signal_z: float
    fill_z: float
    entry_z: float
    exit_z: float
    alpha: float
    beta: float
    validation_mean: float
    validation_std: float
    gross_weight_y: float
    gross_weight_x: float
    y_entry_price: float
    x_entry_price: float
    y_exit_price: float
    x_exit_price: float
    y_quantity: float
    x_quantity: float
    gross_exposure: float
    y_entry_notional: float
    x_entry_notional: float
    risk_budget: float
    loss_per_gross: float
    bars_held: int
    gross_pair_price_pnl: float
    payoff_multiplier: float
    adjusted_pair_price_pnl: float
    y_entry_fee: float
    y_entry_spread_slippage: float
    y_entry_impact: float
    x_entry_fee: float
    x_entry_spread_slippage: float
    x_entry_impact: float
    y_exit_fee: float
    y_exit_spread_slippage: float
    y_exit_impact: float
    x_exit_fee: float
    x_exit_spread_slippage: float
    x_exit_impact: float
    y_funding_cashflow: float
    x_funding_cashflow: float
    execution_cost: float
    net_pnl: float
    signal_expected_convergence_return: float
    expected_convergence_return: float
    adverse_funding: float
    signal_stressed_required_return: float
    stressed_required_return: float
    equity_before_entry: float
    equity_after_exit: float


@dataclass(frozen=True, slots=True)
class PairPortfolioResult:
    episodes: tuple[PairEpisodeLedger, ...]
    terminal_episodes: tuple[PairEpisodeLedger, ...]
    equity_curve: tuple[tuple[datetime, float], ...]
    monthly_returns: tuple[tuple[str, float], ...]
    rejections: tuple[tuple[str, str, str], ...]
    initial_equity: float
    final_equity: float
    max_drawdown: float
    total_execution_cost: float
    accrued_exit_cost: float
    total_funding_cashflow: float
    open_pair_count: int
    open_leg_count: int
    quarantined_pairs: tuple[tuple[str, str], ...]


@dataclass(frozen=True, slots=True)
class _Bar:
    ts: datetime
    open: float
    close: float


@dataclass(frozen=True, slots=True)
class _Funding:
    ts: datetime
    symbol: str
    rate: float
    mark_price: float | None


def _canonical_funding_symbol(value: Any) -> str:
    """Map the frozen funding spellings onto canonical ``BASE/USDT`` symbols."""

    text = str(value).strip().upper().split(":", 1)[0].replace("-", "/").replace("_", "/")
    if not text:
        raise ValueError("funding symbol must be non-empty")
    if "/" in text:
        pieces = text.split("/")
        if len(pieces) != 2:
            raise ValueError(f"unsupported funding symbol: {value!r}")
        base, quote = pieces
    elif text.endswith("USDT"):
        base, quote = text[:-4], "USDT"
    else:
        base, quote = text, "USDT"
    if not base or quote != "USDT" or not base.isalnum():
        raise ValueError(f"unsupported funding symbol: {value!r}")
    return f"{base}/USDT"


@dataclass(frozen=True, slots=True)
class _Entry:
    candidate_id: str
    pair_id: str
    selection_ts: datetime
    decision_ts: datetime
    entry_ts: datetime
    y_symbol: str
    x_symbol: str
    y_side: LegSide
    x_side: LegSide
    entry_regime: EntryRegime
    z_score: float
    alpha: float
    beta: float
    validation_mean: float
    validation_std: float
    gross_weight_y: float
    gross_weight_x: float
    entry_abs_z: float
    exit_abs_z: float
    disaster_abs_z: float
    max_hold_hours: int
    cooldown_hours: int
    expected_convergence_return: float
    adverse_funding: float
    stressed_required_return: float
    economic_buffer_multiplier: float
    base_round_trip_cost_per_gross: float
    c2_round_trip_cost_per_gross: float


@dataclass(slots=True)
class _Position:
    entry: _Entry
    y_entry_price: float
    x_entry_price: float
    y_quantity: float
    x_quantity: float
    gross_exposure: float
    y_entry_notional: float
    x_entry_notional: float
    risk_budget: float
    loss_per_gross: float
    fill_z: float
    fill_expected_convergence_return: float
    fill_stressed_required_return: float
    y_entry_costs: tuple[float, float, float]
    x_entry_costs: tuple[float, float, float]
    y_funding_cashflow: float
    x_funding_cashflow: float
    equity_before_entry: float
    bars_held: int
    last_shared_ts: datetime
    last_z: float
    residuals: deque[tuple[datetime, float]]
    structural_checks: int
    last_structural_check_ts: datetime | None
    pending_exit_reason: str | None = None
    pending_exit_decision_ts: datetime | None = None
    pending_exit_ts: datetime | None = None
    pending_exit_z: float | None = None


_EXIT_PRIORITY = {
    "data_gap": 0,
    "disaster_z_stop": 1,
    "structural_break": 2,
    "max_hold": 3,
    "pair_deselection": 4,
    "mean_exit": 5,
}


def _execution_components(notional: float, cost: PairCostModel) -> tuple[float, float, float]:
    scale = float(notional) * cost.cost_multiplier / 10_000.0
    return (
        scale * cost.fee_bps_per_leg,
        scale * cost.spread_slippage_bps_per_leg,
        scale * cost.impact_bps_per_leg,
    )


def _normalize_frames(
    frames: Mapping[str, pd.DataFrame], bar_delta: timedelta
) -> tuple[dict[str, dict[datetime, _Bar]], dict[str, tuple[datetime, ...]]]:
    if not isinstance(frames, Mapping) or not frames:
        raise ValueError("frames must be a non-empty symbol -> DataFrame mapping")
    bars: dict[str, dict[datetime, _Bar]] = {}
    ordered: dict[str, tuple[datetime, ...]] = {}
    grid_minutes = int(bar_delta.total_seconds() // 60)
    for raw_symbol, frame in frames.items():
        symbol = str(raw_symbol).strip()
        if not symbol or not isinstance(frame, pd.DataFrame) or frame.empty:
            raise ValueError("every frame must have a non-empty symbol and DataFrame")
        missing = {"ts", "open", "close"}.difference(frame.columns)
        if missing:
            raise ValueError(f"{symbol} frame missing columns: {sorted(missing)}")
        rows: list[_Bar] = []
        for position, (raw_ts, raw_open, raw_close) in enumerate(
            frame.loc[:, ["ts", "open", "close"]].itertuples(index=False, name=None)
        ):
            ts = _utc(f"{symbol}.ts[{position}]", raw_ts)
            if ts.minute % grid_minutes != 0 or ts.second != 0 or ts.microsecond != 0:
                raise ValueError(f"{symbol} timestamps must lie on the 15-minute UTC grid")
            open_price = _finite(f"{symbol}.open[{position}]", raw_open, positive=True)
            close_price = _finite(f"{symbol}.close[{position}]", raw_close, positive=True)
            rows.append(_Bar(ts, open_price, close_price))
        rows.sort(key=lambda row: row.ts)
        timestamps = tuple(row.ts for row in rows)
        if len(timestamps) != len(set(timestamps)):
            raise ValueError(f"{symbol} frame has duplicate timestamps")
        if timestamps and any(
            (timestamp - timestamps[0]) % bar_delta != timedelta(0) for timestamp in timestamps[1:]
        ):
            raise ValueError(f"{symbol} timestamps must lie on one 15-minute grid")
        bars[symbol] = {row.ts: row for row in rows}
        ordered[symbol] = timestamps
    return bars, ordered


def _normalize_funding(
    funding_events: Iterable[Mapping[str, Any]] | Mapping[str, pd.DataFrame] | pd.DataFrame | None,
) -> tuple[_Funding, ...]:
    if funding_events is None:
        return ()
    records: list[dict[str, Any]] = []
    if isinstance(funding_events, pd.DataFrame):
        records.extend(funding_events.to_dict("records"))
    elif isinstance(funding_events, Mapping):
        for symbol, frame in funding_events.items():
            if not isinstance(frame, pd.DataFrame):
                raise ValueError("mapped funding events must be DataFrames")
            records.extend({"symbol": symbol, **row} for row in frame.to_dict("records"))
    else:
        records.extend(dict(record) for record in funding_events)

    normalized: list[_Funding] = []
    for position, record in enumerate(records):
        rate_key = "rate" if "rate" in record else "funding_rate"
        if not {"symbol", "ts", rate_key} <= set(record):
            raise ValueError("funding event requires symbol, ts and rate")
        mark = record.get("mark_price")
        effective_ts = _utc(f"funding[{position}].ts", record["ts"]).replace(microsecond=0)
        symbol = _canonical_funding_symbol(record["symbol"])
        mark_price: float | None = None
        if mark is not None and pd.notna(mark):
            try:
                parsed_mark = float(mark)
            except (TypeError, ValueError):
                parsed_mark = float("nan")
            # Frozen precedence is finite-positive event mark, otherwise the
            # latest completed symbol close.  Invalid optional marks therefore
            # do not invalidate an otherwise reproducible funding event.
            if math.isfinite(parsed_mark) and parsed_mark > 0.0:
                mark_price = parsed_mark
        normalized.append(
            _Funding(
                ts=effective_ts,
                symbol=symbol,
                rate=_finite(f"funding[{position}].rate", record[rate_key]),
                mark_price=mark_price,
            )
        )
    ordered = tuple(sorted(normalized, key=lambda event: (event.ts, event.symbol)))
    keys = [(event.ts, event.symbol) for event in ordered]
    if len(keys) != len(set(keys)):
        raise ValueError("funding events collide after whole-second timestamp normalization")
    return ordered


def _normalize_entry(raw: PairEntryIntent | PairEntryIntentLike, bar_delta: timedelta) -> _Entry:
    candidate_id = str(raw.candidate_id).strip()
    pair_id = str(raw.pair_id).strip()
    y_symbol = str(raw.y_symbol).strip()
    x_symbol = str(raw.x_symbol).strip()
    if not candidate_id or not pair_id or not y_symbol or not x_symbol or y_symbol == x_symbol:
        raise ValueError("entry candidate, pair and two distinct symbols are required")
    decision_ts = _utc("entry.decision_ts", raw.decision_ts)
    entry_ts = _utc("entry.entry_ts", raw.entry_ts)
    selection_ts = _utc("entry.selection_ts", raw.selection_ts)
    if decision_ts.minute != 45 or decision_ts.second != 0 or decision_ts.microsecond != 0:
        raise ValueError("entry decision_ts must be the completed :45 bar open label")
    if entry_ts != decision_ts + bar_delta:
        raise ValueError("entry_ts must be exactly one 15-minute bar after decision_ts")
    if selection_ts > entry_ts:
        raise ValueError("selection_ts cannot be after entry_ts")

    beta = _finite("entry.beta", raw.beta, positive=True)
    validation_std = _finite("entry.validation_std", raw.validation_std, positive=True)
    weight_y = _finite("entry.gross_weight_y", raw.gross_weight_y, positive=True)
    weight_x = _finite("entry.gross_weight_x", raw.gross_weight_x, positive=True)
    expected_y = 1.0 / (1.0 + beta)
    expected_x = beta / (1.0 + beta)
    if not math.isclose(weight_y, expected_y, rel_tol=0.0, abs_tol=1e-12) or not math.isclose(
        weight_x, expected_x, rel_tol=0.0, abs_tol=1e-12
    ):
        raise ValueError("entry gross weights do not match frozen beta")
    if not math.isclose(weight_y + weight_x, 1.0, rel_tol=0.0, abs_tol=1e-12):
        raise ValueError("entry gross weights must sum to one")

    z_score = _finite("entry.z_score", raw.z_score)
    if z_score == 0.0:
        raise ValueError("entry z_score cannot be zero")
    y_side = str(raw.y_side)
    x_side = str(raw.x_side)
    expected_sides = ("short", "long") if z_score > 0 else ("long", "short")
    if (y_side, x_side) != expected_sides:
        raise ValueError("entry leg sides disagree with high/low spread contract")
    regime: EntryRegime = "high_spread" if z_score > 0 else "low_spread"

    entry_abs_z = _finite("entry.entry_abs_z", raw.entry_abs_z, positive=True)
    exit_abs_z = _finite("entry.exit_abs_z", raw.exit_abs_z)
    disaster_abs_z = _finite("entry.disaster_abs_z", raw.disaster_abs_z, positive=True)
    if exit_abs_z < 0.0 or not exit_abs_z < entry_abs_z < disaster_abs_z:
        raise ValueError("entry z thresholds must satisfy exit < entry < disaster")
    expected = _finite("entry.expected_convergence_return", raw.expected_convergence_return)
    adverse_funding = _finite("entry.adverse_funding", raw.adverse_funding)
    required = _finite("entry.stressed_required_return", raw.stressed_required_return)
    buffer_multiplier = _finite(
        "entry.economic_buffer_multiplier", raw.economic_buffer_multiplier, positive=True
    )
    base_cost = _finite("entry.base_round_trip_cost_per_gross", raw.base_round_trip_cost_per_gross)
    c2_cost = _finite("entry.c2_round_trip_cost_per_gross", raw.c2_round_trip_cost_per_gross)
    if min(expected, adverse_funding, required, base_cost, c2_cost) < 0.0:
        raise ValueError("entry economic values must be >= 0")
    if c2_cost < base_cost:
        raise ValueError("entry C2 round-trip cost cannot be below base cost")
    return _Entry(
        candidate_id=candidate_id,
        pair_id=pair_id,
        selection_ts=selection_ts,
        decision_ts=decision_ts,
        entry_ts=entry_ts,
        y_symbol=y_symbol,
        x_symbol=x_symbol,
        y_side=y_side,  # type: ignore[arg-type]
        x_side=x_side,  # type: ignore[arg-type]
        entry_regime=regime,
        z_score=z_score,
        alpha=_finite("entry.alpha", raw.alpha),
        beta=beta,
        validation_mean=_finite("entry.validation_mean", raw.validation_mean),
        validation_std=validation_std,
        gross_weight_y=weight_y,
        gross_weight_x=weight_x,
        entry_abs_z=entry_abs_z,
        exit_abs_z=exit_abs_z,
        disaster_abs_z=disaster_abs_z,
        max_hold_hours=_positive_int("entry.max_hold_hours", raw.max_hold_hours),
        cooldown_hours=_positive_int("entry.cooldown_hours", raw.cooldown_hours, allow_zero=True),
        expected_convergence_return=expected,
        adverse_funding=adverse_funding,
        stressed_required_return=required,
        economic_buffer_multiplier=buffer_multiplier,
        base_round_trip_cost_per_gross=base_cost,
        c2_round_trip_cost_per_gross=c2_cost,
    )


def _selection_schedule(
    pair_models: Iterable[PairModel | PairModelLike],
    selection_events: Iterable[PairSelectionEvent],
) -> list[tuple[datetime, str, frozenset[str]]]:
    from_models: dict[tuple[datetime, str], set[str]] = defaultdict(set)
    for position, model in enumerate(pair_models):
        candidate = str(model.candidate_id).strip()
        pair_id = str(model.pair_id).strip()
        selection_ts = _utc(f"pair_models[{position}].selection_ts", model.selection_ts)
        if not candidate or not pair_id:
            raise ValueError("pair model candidate_id and pair_id must be non-empty")
        from_models[(selection_ts, candidate)].add(pair_id)

    explicit: dict[tuple[datetime, str], frozenset[str]] = {}
    for event in selection_events:
        if not isinstance(event, PairSelectionEvent):
            raise TypeError("selection_events must contain PairSelectionEvent values")
        key = (event.selection_ts, event.candidate_id)
        if key in explicit:
            raise ValueError("duplicate selection event for candidate and timestamp")
        explicit[key] = frozenset(event.selected_pair_ids)
    for key, model_pairs in from_models.items():
        if key in explicit and not model_pairs <= explicit[key]:
            raise ValueError("selection event omits a supplied PairModel")

    keys = set(from_models).union(explicit)
    return [
        (timestamp, candidate, explicit.get(key, frozenset(from_models.get(key, set()))))
        for key in sorted(keys)
        for timestamp, candidate in (key,)
    ]


def _direction(side: LegSide) -> float:
    return 1.0 if side == "long" else -1.0


def _spread(entry: _Entry, y_price: float, x_price: float) -> float:
    return math.log(y_price) - entry.alpha - entry.beta * math.log(x_price)


def _zscore(entry: _Entry, y_price: float, x_price: float) -> tuple[float, float]:
    spread = _spread(entry, y_price, x_price)
    return spread, (spread - entry.validation_mean) / entry.validation_std


def _pair_price_pnl(position: _Position, y_price: float, x_price: float) -> float:
    y_pnl = (
        _direction(position.entry.y_side) * (y_price - position.y_entry_price) * position.y_quantity
    )
    x_pnl = (
        _direction(position.entry.x_side) * (x_price - position.x_entry_price) * position.x_quantity
    )
    return y_pnl + x_pnl


def _payoff_multiplier(gross: float, positive: float, negative: float) -> float:
    return positive if gross > 0.0 else negative if gross < 0.0 else 1.0


def _monthly_returns(
    curve: list[tuple[datetime, float]], initial_equity: float
) -> tuple[tuple[str, float], ...]:
    month_end: dict[str, float] = {}
    for ts, nav in curve:
        month_end[f"{ts.year:04d}-{ts.month:02d}"] = nav
    previous = initial_equity
    values: list[tuple[str, float]] = []
    for month in sorted(month_end):
        nav = month_end[month]
        values.append((month, nav / previous - 1.0 if previous > 0.0 else 0.0))
        previous = nav
    return tuple(values)


def simulate_pair_portfolio(
    frames: Mapping[str, pd.DataFrame],
    entry_intents: Iterable[PairEntryIntent | PairEntryIntentLike],
    pair_models: Iterable[PairModel | PairModelLike] = (),
    funding_events: Iterable[Mapping[str, Any]]
    | Mapping[str, pd.DataFrame]
    | pd.DataFrame
    | None = None,
    cost: PairCostModel | None = None,
    policy: PairPortfolioPolicy | None = None,
    *,
    selection_events: Iterable[PairSelectionEvent] = (),
    positive_payoff_multiplier: float = 1.0,
    negative_payoff_multiplier: float = 1.0,
) -> PairPortfolioResult:
    """Replay pair entries and exits over one common compounding portfolio.

    Entry and ordinary exit decisions use a completed bar and execute both legs
    only at the next shared open.  A data gap is the sole exception: an open
    episode exits at the first later timestamp carrying both leg opens.
    """

    cost = cost or PairCostModel()
    policy = policy or PairPortfolioPolicy()
    positive_mult = _finite("positive_payoff_multiplier", positive_payoff_multiplier, positive=True)
    negative_mult = _finite("negative_payoff_multiplier", negative_payoff_multiplier, positive=True)
    bar_delta = timedelta(minutes=policy.bar_minutes)
    gap_limit = timedelta(minutes=policy.gap_max_minutes)
    bars, ordered = _normalize_frames(frames, bar_delta)
    funding = _normalize_funding(funding_events)
    schedule = _selection_schedule(pair_models, selection_events)
    has_selection_contract = bool(schedule)

    rejections: list[tuple[str, str, str]] = []
    entries_by_ts: dict[datetime, list[_Entry]] = defaultdict(list)
    for raw in entry_intents:
        entry = _normalize_entry(raw, bar_delta)
        if abs(entry.z_score) >= entry.disaster_abs_z:
            rejections.append((entry.candidate_id, entry.pair_id, "entry_at_or_beyond_disaster"))
            continue
        if entry.y_symbol not in bars or entry.x_symbol not in bars:
            rejections.append((entry.candidate_id, entry.pair_id, "atomic_entry_symbol_missing"))
            continue
        y_decision = bars[entry.y_symbol].get(entry.decision_ts)
        x_decision = bars[entry.x_symbol].get(entry.decision_ts)
        if y_decision is None or x_decision is None:
            rejections.append((entry.candidate_id, entry.pair_id, "atomic_decision_leg_missing"))
            continue
        y_entry = bars[entry.y_symbol].get(entry.entry_ts)
        x_entry = bars[entry.x_symbol].get(entry.entry_ts)
        if y_entry is None or x_entry is None:
            rejections.append((entry.candidate_id, entry.pair_id, "atomic_entry_leg_missing"))
            continue
        for symbol in (entry.y_symbol, entry.x_symbol):
            timestamps = ordered[symbol]
            decision_index = bisect_left(timestamps, entry.decision_ts)
            if (
                decision_index >= len(timestamps)
                or timestamps[decision_index] != entry.decision_ts
                or decision_index + 1 >= len(timestamps)
                or timestamps[decision_index + 1] != entry.entry_ts
            ):
                rejections.append(
                    (entry.candidate_id, entry.pair_id, "atomic_entry_not_next_contiguous_open")
                )
                break
        else:
            entries_by_ts[entry.entry_ts].append(entry)

    bars_by_ts: dict[datetime, dict[str, _Bar]] = defaultdict(dict)
    for symbol, symbol_bars in bars.items():
        for ts, row in symbol_bars.items():
            bars_by_ts[ts][symbol] = row

    cash = policy.initial_equity
    peak_nav = policy.initial_equity
    marks: dict[str, float] = {}
    positions: dict[tuple[str, str], _Position] = {}
    symbol_owner: dict[str, tuple[str, str]] = {}
    cooldown_until: dict[tuple[str, str], datetime] = {}
    quarantined: set[tuple[str, str]] = set()
    active_selection: dict[str, frozenset[str]] = {}
    ledgers: list[PairEpisodeLedger] = []
    curve: list[tuple[datetime, float]] = []
    total_execution_cost = 0.0
    total_funding = 0.0
    funding_index = 0
    selection_index = 0

    def marked_prices(position: _Position) -> tuple[float, float]:
        return (
            marks.get(position.entry.y_symbol, position.y_entry_price),
            marks.get(position.entry.x_symbol, position.x_entry_price),
        )

    def nav() -> float:
        unrealized = 0.0
        for position in positions.values():
            y_mark, x_mark = marked_prices(position)
            gross = _pair_price_pnl(position, y_mark, x_mark)
            multiplier = _payoff_multiplier(gross, positive_mult, negative_mult)
            exit_cost = sum(_execution_components(y_mark * position.y_quantity, cost)) + sum(
                _execution_components(x_mark * position.x_quantity, cost)
            )
            unrealized += gross * multiplier - exit_cost
        return cash + unrealized

    def set_pending(
        position: _Position,
        reason: str,
        *,
        decision_ts: datetime,
        expected_ts: datetime,
        z_score: float,
    ) -> None:
        current = position.pending_exit_reason
        if current is None or _EXIT_PRIORITY[reason] < _EXIT_PRIORITY[current]:
            position.pending_exit_reason = reason
            position.pending_exit_decision_ts = decision_ts
            position.pending_exit_ts = expected_ts
            position.pending_exit_z = z_score

    def seed_residuals(entry: _Entry) -> deque[tuple[datetime, float]]:
        start = entry.entry_ts - timedelta(hours=policy.structural_mean_window_hours)
        y_times = ordered[entry.y_symbol]
        first = bisect_left(y_times, start)
        seeded: deque[tuple[datetime, float]] = deque()
        for ts in y_times[first:]:
            if ts >= entry.entry_ts:
                break
            x_row = bars[entry.x_symbol].get(ts)
            if x_row is not None:
                seeded.append((ts, _spread(entry, bars[entry.y_symbol][ts].close, x_row.close)))
        return seeded

    def close_pair(
        key: tuple[str, str],
        *,
        ts: datetime,
        y_price: float,
        x_price: float,
        reason: str,
        decision_ts: datetime,
        exit_z: float,
    ) -> None:
        nonlocal cash, total_execution_cost
        position = positions.pop(key)
        entry = position.entry
        symbol_owner.pop(entry.y_symbol, None)
        symbol_owner.pop(entry.x_symbol, None)
        gross = _pair_price_pnl(position, y_price, x_price)
        multiplier = _payoff_multiplier(gross, positive_mult, negative_mult)
        adjusted = gross * multiplier
        y_exit_costs = _execution_components(y_price * position.y_quantity, cost)
        x_exit_costs = _execution_components(x_price * position.x_quantity, cost)
        exit_cost = sum(y_exit_costs) + sum(x_exit_costs)
        entry_cost = sum(position.y_entry_costs) + sum(position.x_entry_costs)
        cash += adjusted - exit_cost
        total_execution_cost += exit_cost
        marks[entry.y_symbol] = y_price
        marks[entry.x_symbol] = x_price
        equity_after = nav()
        execution_cost = entry_cost + exit_cost
        ledgers.append(
            PairEpisodeLedger(
                candidate_id=entry.candidate_id,
                pair_id=entry.pair_id,
                selection_ts=entry.selection_ts,
                y_symbol=entry.y_symbol,
                x_symbol=entry.x_symbol,
                entry_regime=entry.entry_regime,
                y_side=entry.y_side,
                x_side=entry.x_side,
                decision_ts=entry.decision_ts,
                entry_ts=entry.entry_ts,
                exit_decision_ts=decision_ts,
                exit_ts=ts,
                exit_reason=reason,
                signal_z=entry.z_score,
                fill_z=position.fill_z,
                entry_z=position.fill_z,
                exit_z=exit_z,
                alpha=entry.alpha,
                beta=entry.beta,
                validation_mean=entry.validation_mean,
                validation_std=entry.validation_std,
                gross_weight_y=entry.gross_weight_y,
                gross_weight_x=entry.gross_weight_x,
                y_entry_price=position.y_entry_price,
                x_entry_price=position.x_entry_price,
                y_exit_price=y_price,
                x_exit_price=x_price,
                y_quantity=position.y_quantity,
                x_quantity=position.x_quantity,
                gross_exposure=position.gross_exposure,
                y_entry_notional=position.y_entry_notional,
                x_entry_notional=position.x_entry_notional,
                risk_budget=position.risk_budget,
                loss_per_gross=position.loss_per_gross,
                bars_held=position.bars_held,
                gross_pair_price_pnl=gross,
                payoff_multiplier=multiplier,
                adjusted_pair_price_pnl=adjusted,
                y_entry_fee=position.y_entry_costs[0],
                y_entry_spread_slippage=position.y_entry_costs[1],
                y_entry_impact=position.y_entry_costs[2],
                x_entry_fee=position.x_entry_costs[0],
                x_entry_spread_slippage=position.x_entry_costs[1],
                x_entry_impact=position.x_entry_costs[2],
                y_exit_fee=y_exit_costs[0],
                y_exit_spread_slippage=y_exit_costs[1],
                y_exit_impact=y_exit_costs[2],
                x_exit_fee=x_exit_costs[0],
                x_exit_spread_slippage=x_exit_costs[1],
                x_exit_impact=x_exit_costs[2],
                y_funding_cashflow=position.y_funding_cashflow,
                x_funding_cashflow=position.x_funding_cashflow,
                execution_cost=execution_cost,
                net_pnl=(
                    adjusted
                    - execution_cost
                    + position.y_funding_cashflow
                    + position.x_funding_cashflow
                ),
                signal_expected_convergence_return=entry.expected_convergence_return,
                expected_convergence_return=position.fill_expected_convergence_return,
                adverse_funding=entry.adverse_funding,
                signal_stressed_required_return=entry.stressed_required_return,
                stressed_required_return=position.fill_stressed_required_return,
                equity_before_entry=position.equity_before_entry,
                equity_after_exit=equity_after,
            )
        )
        cooldown_until[key] = ts + timedelta(hours=entry.cooldown_hours)
        if reason in {"data_gap", "structural_break"}:
            quarantined.add(key)

    timeline = sorted(bars_by_ts)
    for ts in timeline:
        current_rows = bars_by_ts[ts]

        while funding_index < len(funding) and funding[funding_index].ts <= ts:
            event = funding[funding_index]
            owner = symbol_owner.get(event.symbol)
            position = positions.get(owner) if owner is not None else None
            if position is not None and position.entry.entry_ts < event.ts:
                if event.symbol == position.entry.y_symbol:
                    side = position.entry.y_side
                    quantity = position.y_quantity
                else:
                    side = position.entry.x_side
                    quantity = position.x_quantity
                if event.mark_price is not None:
                    mark = event.mark_price
                else:
                    timestamps = ordered.get(event.symbol, ())
                    completed_index = bisect_right(timestamps, event.ts - bar_delta) - 1
                    if completed_index < 0:
                        raise ValueError(
                            f"funding mark unavailable for open leg {event.symbol} at "
                            f"{event.ts.isoformat()}"
                        )
                    completed_ts = timestamps[completed_index]
                    mark = bars[event.symbol][completed_ts].close
                cashflow = (
                    -_direction(side) * mark * quantity * event.rate * cost.funding_multiplier
                )
                cash += cashflow
                if event.symbol == position.entry.y_symbol:
                    position.y_funding_cashflow += cashflow
                else:
                    position.x_funding_cashflow += cashflow
                total_funding += cashflow
            funding_index += 1

        for symbol, row in current_rows.items():
            marks[symbol] = row.open

        while selection_index < len(schedule) and schedule[selection_index][0] <= ts:
            selection_ts, candidate, selected = schedule[selection_index]
            active_selection[candidate] = selected
            quarantined.difference_update(key for key in tuple(quarantined) if key[0] == candidate)
            for key, position in positions.items():
                if key[0] == candidate and key[1] not in selected:
                    set_pending(
                        position,
                        "pair_deselection",
                        decision_ts=selection_ts - bar_delta,
                        expected_ts=selection_ts,
                        z_score=position.last_z,
                    )
            selection_index += 1

        for key in sorted(tuple(positions)):
            position = positions.get(key)
            if position is None:
                continue
            y_row = current_rows.get(position.entry.y_symbol)
            x_row = current_rows.get(position.entry.x_symbol)
            if y_row is None or x_row is None:
                continue
            data_gap = ts - position.last_shared_ts > gap_limit
            missed_atomic_exit = (
                position.pending_exit_ts is not None and ts > position.pending_exit_ts
            )
            if data_gap or missed_atomic_exit:
                close_pair(
                    key,
                    ts=ts,
                    y_price=y_row.open,
                    x_price=x_row.open,
                    reason="data_gap",
                    decision_ts=ts,
                    exit_z=position.last_z,
                )
            elif position.pending_exit_ts is not None and ts >= position.pending_exit_ts:
                assert position.pending_exit_reason is not None
                assert position.pending_exit_decision_ts is not None
                assert position.pending_exit_z is not None
                close_pair(
                    key,
                    ts=ts,
                    y_price=y_row.open,
                    x_price=x_row.open,
                    reason=position.pending_exit_reason,
                    decision_ts=position.pending_exit_decision_ts,
                    exit_z=position.pending_exit_z,
                )

        for entry in sorted(
            entries_by_ts.get(ts, ()), key=lambda item: (item.candidate_id, item.pair_id)
        ):
            key = (entry.candidate_id, entry.pair_id)
            if key in positions:
                rejections.append((entry.candidate_id, entry.pair_id, "pair_already_open"))
                continue
            if entry.y_symbol in symbol_owner or entry.x_symbol in symbol_owner:
                rejections.append((entry.candidate_id, entry.pair_id, "symbol_already_open"))
                continue
            if len(positions) >= policy.max_pairs:
                rejections.append((entry.candidate_id, entry.pair_id, "max_pairs"))
                continue
            if 2 * len(positions) + 2 > policy.max_legs:
                rejections.append((entry.candidate_id, entry.pair_id, "max_legs"))
                continue
            if key in quarantined:
                rejections.append((entry.candidate_id, entry.pair_id, "pair_quarantined"))
                continue
            if ts < cooldown_until.get(key, datetime.min.replace(tzinfo=UTC)):
                rejections.append((entry.candidate_id, entry.pair_id, "pair_cooldown"))
                continue
            if has_selection_contract and entry.pair_id not in active_selection.get(
                entry.candidate_id, frozenset()
            ):
                rejections.append((entry.candidate_id, entry.pair_id, "pair_not_selected"))
                continue
            y_row = current_rows.get(entry.y_symbol)
            x_row = current_rows.get(entry.x_symbol)
            if y_row is None or x_row is None:
                # This should have been rejected in the static atomic-entry check.
                rejections.append((entry.candidate_id, entry.pair_id, "atomic_entry_leg_missing"))
                continue
            _, fill_z = _zscore(entry, y_row.open, x_row.open)
            if fill_z * entry.z_score <= 0.0:
                rejections.append((entry.candidate_id, entry.pair_id, "fill_z_direction_changed"))
                continue
            if abs(fill_z) + 1e-12 < entry.entry_abs_z:
                rejections.append(
                    (entry.candidate_id, entry.pair_id, "fill_z_below_entry_threshold")
                )
                continue
            if abs(fill_z) >= entry.disaster_abs_z - 1e-12:
                rejections.append(
                    (entry.candidate_id, entry.pair_id, "fill_z_at_or_beyond_disaster")
                )
                continue
            fill_expected = (
                (abs(fill_z) - entry.exit_abs_z) * entry.validation_std / (1.0 + entry.beta)
            )
            fill_required = entry.economic_buffer_multiplier * max(
                entry.c2_round_trip_cost_per_gross + 2.0 * entry.adverse_funding,
                2.0 * (entry.base_round_trip_cost_per_gross + entry.adverse_funding),
            )
            if fill_expected < fill_required:
                rejections.append((entry.candidate_id, entry.pair_id, "fill_economic_gate"))
                continue
            current_nav = nav()
            if current_nav <= 0.0:
                rejections.append((entry.candidate_id, entry.pair_id, "non_positive_equity"))
                continue
            drawdown = (peak_nav - current_nav) / peak_nav if peak_nav > 0.0 else 0.0
            throttle = (
                policy.dd_throttle_multiplier if drawdown >= policy.dd_throttle_threshold else 1.0
            )
            risk_budget = current_nav * policy.risk_per_pair_episode * throttle
            loss_per_gross = (
                (entry.disaster_abs_z - abs(fill_z)) * entry.validation_std / (1.0 + entry.beta)
            )
            if loss_per_gross <= 0.0 or not math.isfinite(loss_per_gross):
                rejections.append((entry.candidate_id, entry.pair_id, "invalid_risk_distance"))
                continue
            gross_exposure = risk_budget / loss_per_gross
            gross_exposure = min(
                gross_exposure,
                current_nav * policy.max_leg_notional_pct / entry.gross_weight_y,
                current_nav * policy.max_leg_notional_pct / entry.gross_weight_x,
            )
            # The preregistered leverage denominator uses current common NAV,
            # while its numerator is frozen gross entry notional per episode.
            used_notional = sum(
                open_position.gross_exposure for open_position in positions.values()
            )
            gross_exposure = min(
                gross_exposure, max(current_nav * policy.leverage - used_notional, 0.0)
            )
            if gross_exposure <= 0.0 or not math.isfinite(gross_exposure):
                rejections.append((entry.candidate_id, entry.pair_id, "invalid_pair_size"))
                continue
            y_notional = gross_exposure * entry.gross_weight_y
            x_notional = gross_exposure * entry.gross_weight_x
            y_quantity = y_notional / y_row.open
            x_quantity = x_notional / x_row.open
            y_entry_costs = _execution_components(y_notional, cost)
            x_entry_costs = _execution_components(x_notional, cost)
            entry_cost = sum(y_entry_costs) + sum(x_entry_costs)
            cash -= entry_cost
            total_execution_cost += entry_cost
            position = _Position(
                entry=entry,
                y_entry_price=y_row.open,
                x_entry_price=x_row.open,
                y_quantity=y_quantity,
                x_quantity=x_quantity,
                gross_exposure=gross_exposure,
                y_entry_notional=y_notional,
                x_entry_notional=x_notional,
                risk_budget=risk_budget,
                loss_per_gross=loss_per_gross,
                fill_z=fill_z,
                fill_expected_convergence_return=fill_expected,
                fill_stressed_required_return=fill_required,
                y_entry_costs=y_entry_costs,
                x_entry_costs=x_entry_costs,
                y_funding_cashflow=0.0,
                x_funding_cashflow=0.0,
                equity_before_entry=current_nav,
                bars_held=0,
                last_shared_ts=entry.decision_ts,
                last_z=fill_z,
                residuals=seed_residuals(entry),
                structural_checks=0,
                last_structural_check_ts=None,
            )
            positions[key] = position
            symbol_owner[entry.y_symbol] = key
            symbol_owner[entry.x_symbol] = key

        for symbol, row in current_rows.items():
            marks[symbol] = row.close

        for key in sorted(tuple(positions)):
            position = positions.get(key)
            if position is None:
                continue
            entry = position.entry
            y_row = current_rows.get(entry.y_symbol)
            x_row = current_rows.get(entry.x_symbol)
            if y_row is None or x_row is None:
                continue
            position.bars_held += 1
            position.last_shared_ts = ts
            spread, z_score = _zscore(entry, y_row.close, x_row.close)
            position.last_z = z_score
            position.residuals.append((ts, spread))
            residual_cutoff = ts - timedelta(hours=policy.structural_mean_window_hours) + bar_delta
            while position.residuals and position.residuals[0][0] < residual_cutoff:
                position.residuals.popleft()

            reason: str | None = None
            if abs(z_score) >= entry.disaster_abs_z:
                reason = "disaster_z_stop"
            else:
                expected_bars = policy.structural_mean_window_hours * 60 // policy.bar_minutes
                required_bars = math.ceil(expected_bars * policy.structural_min_completeness)
                if ts.minute == 45:
                    if (
                        position.last_structural_check_ts is not None
                        and ts - position.last_structural_check_ts != timedelta(hours=1)
                    ):
                        position.structural_checks = 0
                    position.last_structural_check_ts = ts
                    if len(position.residuals) < required_bars:
                        position.structural_checks = 0
                    else:
                        rolling_mean = float(np.mean([value for _, value in position.residuals]))
                        distance = abs(rolling_mean - entry.validation_mean) / entry.validation_std
                        position.structural_checks = (
                            position.structural_checks + 1
                            if distance > policy.structural_distance_sigma
                            else 0
                        )
                        if (
                            position.structural_checks
                            >= policy.structural_consecutive_hourly_checks
                        ):
                            reason = "structural_break"
                if reason is None and ts + bar_delta >= entry.entry_ts + timedelta(
                    hours=entry.max_hold_hours
                ):
                    reason = "max_hold"
                if reason is None:
                    mean_exit = (
                        entry.entry_regime == "high_spread" and z_score <= entry.exit_abs_z
                    ) or (entry.entry_regime == "low_spread" and z_score >= -entry.exit_abs_z)
                    if mean_exit:
                        reason = "mean_exit"
            if reason is not None:
                set_pending(
                    position,
                    reason,
                    decision_ts=ts,
                    expected_ts=ts + bar_delta,
                    z_score=z_score,
                )

        current_nav = nav()
        peak_nav = max(peak_nav, current_nav)
        curve.append((ts, current_nav))

    max_drawdown = 0.0
    running_peak = policy.initial_equity
    for _, point_nav in curve:
        running_peak = max(running_peak, point_nav)
        if running_peak > 0.0:
            max_drawdown = min(max_drawdown, point_nav / running_peak - 1.0)
    accrued_exit_cost = 0.0
    terminal_episodes: list[PairEpisodeLedger] = []
    terminal_nav = nav()
    terminal_ts = curve[-1][0] if curve else timeline[-1]
    for key in sorted(positions):
        position = positions[key]
        entry = position.entry
        y_mark, x_mark = marked_prices(position)
        y_exit_costs = _execution_components(y_mark * position.y_quantity, cost)
        x_exit_costs = _execution_components(x_mark * position.x_quantity, cost)
        terminal_exit_cost = sum(y_exit_costs) + sum(x_exit_costs)
        accrued_exit_cost += terminal_exit_cost
        entry_cost = sum(position.y_entry_costs) + sum(position.x_entry_costs)
        gross = _pair_price_pnl(position, y_mark, x_mark)
        multiplier = _payoff_multiplier(gross, positive_mult, negative_mult)
        adjusted = gross * multiplier
        _, terminal_z = _zscore(entry, y_mark, x_mark)
        execution_cost = entry_cost + terminal_exit_cost
        terminal_episodes.append(
            PairEpisodeLedger(
                candidate_id=entry.candidate_id,
                pair_id=entry.pair_id,
                selection_ts=entry.selection_ts,
                y_symbol=entry.y_symbol,
                x_symbol=entry.x_symbol,
                entry_regime=entry.entry_regime,
                y_side=entry.y_side,
                x_side=entry.x_side,
                decision_ts=entry.decision_ts,
                entry_ts=entry.entry_ts,
                exit_decision_ts=terminal_ts,
                exit_ts=terminal_ts,
                exit_reason="terminal_open_mtm",
                signal_z=entry.z_score,
                fill_z=position.fill_z,
                entry_z=position.fill_z,
                exit_z=terminal_z,
                alpha=entry.alpha,
                beta=entry.beta,
                validation_mean=entry.validation_mean,
                validation_std=entry.validation_std,
                gross_weight_y=entry.gross_weight_y,
                gross_weight_x=entry.gross_weight_x,
                y_entry_price=position.y_entry_price,
                x_entry_price=position.x_entry_price,
                y_exit_price=y_mark,
                x_exit_price=x_mark,
                y_quantity=position.y_quantity,
                x_quantity=position.x_quantity,
                gross_exposure=position.gross_exposure,
                y_entry_notional=position.y_entry_notional,
                x_entry_notional=position.x_entry_notional,
                risk_budget=position.risk_budget,
                loss_per_gross=position.loss_per_gross,
                bars_held=position.bars_held,
                gross_pair_price_pnl=gross,
                payoff_multiplier=multiplier,
                adjusted_pair_price_pnl=adjusted,
                y_entry_fee=position.y_entry_costs[0],
                y_entry_spread_slippage=position.y_entry_costs[1],
                y_entry_impact=position.y_entry_costs[2],
                x_entry_fee=position.x_entry_costs[0],
                x_entry_spread_slippage=position.x_entry_costs[1],
                x_entry_impact=position.x_entry_costs[2],
                y_exit_fee=y_exit_costs[0],
                y_exit_spread_slippage=y_exit_costs[1],
                y_exit_impact=y_exit_costs[2],
                x_exit_fee=x_exit_costs[0],
                x_exit_spread_slippage=x_exit_costs[1],
                x_exit_impact=x_exit_costs[2],
                y_funding_cashflow=position.y_funding_cashflow,
                x_funding_cashflow=position.x_funding_cashflow,
                execution_cost=execution_cost,
                net_pnl=(
                    adjusted
                    - execution_cost
                    + position.y_funding_cashflow
                    + position.x_funding_cashflow
                ),
                signal_expected_convergence_return=entry.expected_convergence_return,
                expected_convergence_return=position.fill_expected_convergence_return,
                adverse_funding=entry.adverse_funding,
                signal_stressed_required_return=entry.stressed_required_return,
                stressed_required_return=position.fill_stressed_required_return,
                equity_before_entry=position.equity_before_entry,
                equity_after_exit=terminal_nav,
            )
        )

    return PairPortfolioResult(
        episodes=tuple(ledgers),
        terminal_episodes=tuple(terminal_episodes),
        equity_curve=tuple(curve),
        monthly_returns=_monthly_returns(curve, policy.initial_equity),
        rejections=tuple(rejections),
        initial_equity=policy.initial_equity,
        final_equity=nav(),
        max_drawdown=max_drawdown,
        total_execution_cost=total_execution_cost,
        accrued_exit_cost=accrued_exit_cost,
        total_funding_cashflow=total_funding,
        open_pair_count=len(positions),
        open_leg_count=2 * len(positions),
        quarantined_pairs=tuple(sorted(quarantined)),
    )


__all__ = [
    "PairCostModel",
    "PairEpisodeLedger",
    "PairPortfolioPolicy",
    "PairPortfolioResult",
    "PairSelectionEvent",
    "simulate_pair_portfolio",
]
