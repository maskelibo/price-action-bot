"""Pure causal portfolio engine for the preregistered v15p2 fair baseline.

The engine deliberately performs no file, database, network, clock, or daemon
IO.  It consumes already materialised OHLCV frames, signal intents and funding
events and returns frozen evidence records.  The policy defaults mirror
``configs/crypto_15m_v15p2_fair_baseline_prereg.yaml``.

Two accounting bases are intentionally kept separate:

* new-order sizing and caps use current futures ``wallet_balance`` after
  realised cashflows and exclude open unrealised PnL;
* the evaluation curve marks every open position to market after every
  available 15-minute bar and accrues a hypothetical exit cost.

This is a ``NEXT_OPEN_BAR_EXECUTION_PROXY``.  It is not an exchange fill or
order-book simulator.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, timedelta
from types import MappingProxyType
from typing import Any, Literal, Protocol

import pandas as pd

Side = Literal["long", "short"]
ScenarioName = Literal["B", "C2", "H"]

FAIR_BASELINE_CANDIDATE_ID = "v15p2_fair_baseline"
EXPECTED_CONFIG_SHA256 = "78025a394aecb807c32aeba737823bd565f0f19e72ec133352d63f697036ea82"
STRATEGY_RANKS: Mapping[str, int] = MappingProxyType(
    {"vsa_climax_test": 0, "grimes_abc_pullback": 1}
)
EXPECTED_MANIFEST_HASHES: Mapping[str, str] = MappingProxyType(
    {
        "vsa_climax_test": "ebddc62d495cc790",
        "grimes_abc_pullback": "33653e0c52e34338",
    }
)


class V15P2SignalIntentLike(Protocol):
    """Structural contract emitted by ``crypto_15m_v15p2_signals``."""

    candidate_id: str
    decision_ts: datetime
    entry_ts: datetime
    symbol: str
    side: Side
    strategy: str
    strategy_rank: int
    pattern_id: str
    confluence_score: float
    decision_close: float
    entry_reference_price: float
    entry_price: float
    stop_price: float
    take_profit_price: float
    decision_stop_distance_pct: float
    entry_stop_distance_pct: float
    suggested_size_atr: float
    signal_manifest_hash: str
    config_sha256: str


def _finite(name: str, value: Any, *, positive: bool = False) -> float:
    parsed = float(value)
    if not math.isfinite(parsed) or (positive and parsed <= 0.0):
        qualifier = "finite and > 0" if positive else "finite"
        raise ValueError(f"{name} must be {qualifier}")
    return parsed


def _fraction(name: str, value: Any, *, allow_zero: bool = False) -> float:
    parsed = _finite(name, value)
    lower_ok = parsed >= 0.0 if allow_zero else parsed > 0.0
    if not lower_ok or parsed > 1.0:
        interval = "[0, 1]" if allow_zero else "(0, 1]"
        raise ValueError(f"{name} must be in {interval}")
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


def _close_enough(left: float, right: float) -> bool:
    return math.isclose(left, right, rel_tol=1e-10, abs_tol=1e-12)


@dataclass(frozen=True, slots=True)
class V15P2CostScenario:
    """One independently replayed execution/funding/payoff scenario."""

    name: ScenarioName
    fee_bps_per_fill: float = 4.0
    spread_slippage_bps_per_fill: float = 20.0
    impact_bps_per_fill: float = 4.5
    cost_multiplier: float = 1.0
    funding_multiplier: float = 1.0
    positive_price_pnl_multiplier: float = 1.0
    negative_price_pnl_multiplier: float = 1.0

    def __post_init__(self) -> None:
        if self.name not in {"B", "C2", "H"}:
            raise ValueError("scenario name must be B, C2 or H")
        for field_name in (
            "fee_bps_per_fill",
            "spread_slippage_bps_per_fill",
            "impact_bps_per_fill",
            "cost_multiplier",
            "funding_multiplier",
            "positive_price_pnl_multiplier",
            "negative_price_pnl_multiplier",
        ):
            value = _finite(field_name, getattr(self, field_name))
            if value < 0.0:
                raise ValueError(f"{field_name} must be >= 0")
            object.__setattr__(self, field_name, value)


B_SCENARIO = V15P2CostScenario(name="B")
C2_SCENARIO = V15P2CostScenario(
    name="C2",
    cost_multiplier=2.0,
    funding_multiplier=2.0,
)
H_SCENARIO = V15P2CostScenario(
    name="H",
    positive_price_pnl_multiplier=0.50,
    negative_price_pnl_multiplier=1.25,
)
SCENARIOS: Mapping[str, V15P2CostScenario] = MappingProxyType(
    {
        "B": B_SCENARIO,
        "C2": C2_SCENARIO,
        "H": H_SCENARIO,
    }
)


@dataclass(frozen=True, slots=True)
class V15P2PortfolioPolicy:
    """Frozen v15p2 fair-proxy policy, customisable only for unit tests."""

    initial_wallet: float = 10_000.0
    base_risk_per_trade: float = 0.01
    stop_normalizer_target: float = 0.01
    stop_normalizer_min: float = 0.20
    stop_normalizer_max: float = 1.50
    minimum_stop_distance_pct: float = 0.025
    minimum_confluence: float = 0.25
    dd_throttle_threshold: float = 0.06
    dd_throttle_multiplier: float = 0.50
    max_symbol_notional_pct: float = 0.15
    max_open_positions: int = 16
    max_same_side_positions: int = 4
    max_portfolio_notional_x: float = 3.0
    leverage: float = 3.0
    initial_margin_buffer: float = 0.90
    stop_liquidation_safety_ratio: float = 0.50
    cooldown_days: float = 0.010
    correlation_lookback_days: int = 90
    correlation_min_observations: int = 90
    correlation_reduce_above: float = 0.70
    correlation_block_at: float = 0.90
    correlation_reduction_factor: float = 0.50
    tp1_r: float = 1.0
    tp2_r: float = 1.5
    tp1_fraction: float = 0.30
    tp2_fraction: float = 0.30
    runner_fraction: float = 0.40
    trail_pct: float = 0.015
    runner_time_bars_after_tp1: int = 30
    daily_loss_pct: float = 0.04
    daily_halt_days: float = 1.0
    weekly_loss_pct: float = 0.08
    weekly_halt_days: float = 2.0
    monthly_combined_loss_pct: float = 0.99
    monthly_halt_days: float = 3.0
    monthly_long_loss_pct: float = 0.12
    monthly_short_loss_pct: float = 0.04
    consecutive_loss_count: int = 5
    consecutive_loss_lookback_days: int = 30
    consecutive_pause_days: float = 1.0
    bar_minutes: int = 15
    gap_max_minutes: int = 30
    minimum_notional: float = 10.0

    def __post_init__(self) -> None:
        for field_name in (
            "initial_wallet",
            "stop_normalizer_target",
            "max_portfolio_notional_x",
            "leverage",
            "tp1_r",
            "tp2_r",
            "daily_halt_days",
            "weekly_halt_days",
            "monthly_halt_days",
            "consecutive_pause_days",
            "minimum_notional",
        ):
            object.__setattr__(
                self, field_name, _finite(field_name, getattr(self, field_name), positive=True)
            )
        for field_name in (
            "base_risk_per_trade",
            "minimum_stop_distance_pct",
            "minimum_confluence",
            "dd_throttle_threshold",
            "dd_throttle_multiplier",
            "max_symbol_notional_pct",
            "initial_margin_buffer",
            "stop_liquidation_safety_ratio",
            "correlation_reduce_above",
            "correlation_block_at",
            "correlation_reduction_factor",
            "tp1_fraction",
            "tp2_fraction",
            "runner_fraction",
            "trail_pct",
            "daily_loss_pct",
            "weekly_loss_pct",
            "monthly_combined_loss_pct",
            "monthly_long_loss_pct",
            "monthly_short_loss_pct",
        ):
            object.__setattr__(self, field_name, _fraction(field_name, getattr(self, field_name)))
        for field_name in ("stop_normalizer_min", "stop_normalizer_max"):
            object.__setattr__(
                self, field_name, _finite(field_name, getattr(self, field_name), positive=True)
            )
        for field_name in ("cooldown_days",):
            value = _finite(field_name, getattr(self, field_name))
            if value < 0.0:
                raise ValueError(f"{field_name} must be >= 0")
            object.__setattr__(self, field_name, value)
        for field_name in (
            "max_open_positions",
            "max_same_side_positions",
            "correlation_lookback_days",
            "correlation_min_observations",
            "runner_time_bars_after_tp1",
            "consecutive_loss_count",
            "consecutive_loss_lookback_days",
            "bar_minutes",
            "gap_max_minutes",
        ):
            object.__setattr__(
                self, field_name, _positive_int(field_name, getattr(self, field_name))
            )
        if self.stop_normalizer_min > self.stop_normalizer_max:
            raise ValueError("stop_normalizer_min cannot exceed stop_normalizer_max")
        if self.max_same_side_positions > self.max_open_positions:
            raise ValueError("max_same_side_positions cannot exceed max_open_positions")
        if self.correlation_reduce_above >= self.correlation_block_at:
            raise ValueError("correlation reduction threshold must be below hard block")
        if self.correlation_min_observations != self.correlation_lookback_days:
            raise ValueError(
                "correlation_min_observations must equal the full correlation lookback"
            )
        if not _close_enough(
            self.tp1_fraction + self.tp2_fraction + self.runner_fraction,
            1.0,
        ):
            raise ValueError("TP1, TP2 and runner fractions must sum to 1")
        if self.tp2_r <= self.tp1_r:
            raise ValueError("tp2_r must exceed tp1_r")


@dataclass(frozen=True, slots=True)
class RejectionLedger:
    candidate_id: str
    decision_ts: datetime
    entry_ts: datetime
    symbol: str
    side: Side
    strategy: str
    reason: str
    detail: str


@dataclass(frozen=True, slots=True)
class RiskDecisionLedger:
    candidate_id: str
    decision_ts: datetime
    entry_ts: datetime
    symbol: str
    side: Side
    strategy: str
    wallet_before_entry: float
    wallet_peak: float
    wallet_drawdown: float
    base_risk_budget: float
    stop_normalizer_factor: float
    drawdown_factor: float
    correlation_factor: float
    maximum_observed_correlation: float | None
    requested_risk_budget: float
    requested_notional: float
    pre_correlation_notional: float
    post_correlation_notional: float
    accepted_notional: float
    dynamic_leverage: float
    effective_initial_stop_risk: float
    cap_bindings: tuple[str, ...]
    open_notional_before: float
    free_margin_before: float
    required_initial_margin: float


@dataclass(frozen=True, slots=True)
class EntryFillLedger:
    candidate_id: str
    decision_ts: datetime
    entry_ts: datetime
    symbol: str
    side: Side
    strategy: str
    pattern_id: str
    entry_price: float
    initial_stop: float
    tp1_price: float
    tp2_price: float
    original_quantity: float
    entry_notional: float
    dynamic_leverage: float
    wallet_before_entry: float
    wallet_after_entry: float
    risk_budget: float
    effective_initial_stop_risk: float
    fee: float
    spread_slippage: float
    impact: float
    execution_cost: float
    scenario: ScenarioName
    signal_manifest_hash: str
    config_sha256: str


@dataclass(frozen=True, slots=True)
class ExitFillLedger:
    candidate_id: str
    ts: datetime
    symbol: str
    side: Side
    strategy: str
    reason: str
    price: float
    quantity: float
    fraction_of_original: float
    remaining_quantity: float
    gross_price_pnl: float
    payoff_multiplier: float
    adjusted_price_pnl: float
    allocated_entry_cost: float
    fee: float
    spread_slippage: float
    impact: float
    exit_execution_cost: float
    net_pnl_excluding_funding: float
    wallet_after_fill: float
    is_final: bool


@dataclass(frozen=True, slots=True)
class FundingLedger:
    candidate_id: str
    ts: datetime
    symbol: str
    side: Side
    rate: float
    mark_price: float
    remaining_quantity: float
    notional: float
    multiplier: float
    cashflow: float
    wallet_after_funding: float


@dataclass(frozen=True, slots=True)
class JournalLedger:
    """One row as the deployed breaker journal would consume it."""

    candidate_id: str
    ts: datetime
    symbol: str
    side: Side
    strategy: str
    exit_reason: str
    amount: float
    is_final: bool
    cumulative_episode_journal_amount: float
    episode_scenario_net_if_final: float | None


@dataclass(frozen=True, slots=True)
class StopTransitionLedger:
    candidate_id: str
    symbol: str
    side: Side
    calculated_ts: datetime
    effective_ts: datetime
    previous_stop: float
    new_stop: float
    favorable_extreme: float
    reason: str


@dataclass(frozen=True, slots=True)
class BreakerTransitionLedger:
    ts: datetime
    breaker: str
    action: str
    side: Side | None
    metric_value: float
    threshold_value: float
    blocked_until: datetime | None


@dataclass(frozen=True, slots=True)
class ClosedEpisodeLedger:
    candidate_id: str
    symbol: str
    side: Side
    strategy: str
    pattern_id: str
    decision_ts: datetime
    entry_ts: datetime
    exit_ts: datetime
    final_exit_reason: str
    entry_price: float
    initial_stop: float
    original_quantity: float
    bars_held: int
    gross_price_pnl: float
    adjusted_price_pnl: float
    total_entry_execution_cost: float
    total_exit_execution_cost: float
    funding_cashflow: float
    net_pnl: float
    wallet_before_entry: float
    wallet_after_exit: float


@dataclass(frozen=True, slots=True)
class CurvePoint:
    ts: datetime
    wallet_balance: float
    gross_unrealized_price_pnl: float
    adjusted_unrealized_price_pnl: float
    accrued_exit_cost: float
    nav: float
    open_position_count: int


@dataclass(frozen=True, slots=True)
class OpenPositionAccrual:
    candidate_id: str
    symbol: str
    side: Side
    entry_ts: datetime
    cutoff_ts: datetime
    entry_price: float
    mark_price: float
    remaining_quantity: float
    gross_unrealized_price_pnl: float
    payoff_multiplier: float
    adjusted_unrealized_price_pnl: float
    accrued_exit_cost: float
    accrued_nav_contribution: float


@dataclass(frozen=True, slots=True)
class V15P2PortfolioResult:
    scenario: ScenarioName
    scenario_identity: str
    scenario_is_canonical: bool
    scenario_config: V15P2CostScenario
    policy: V15P2PortfolioPolicy
    evaluation_start: datetime
    evaluation_end: datetime
    initial_wallet: float
    final_wallet: float
    final_nav: float
    max_drawdown: float
    total_execution_cost_charged: float
    total_funding_cashflow: float
    accrued_terminal_exit_cost: float
    entries: tuple[EntryFillLedger, ...]
    exit_fills: tuple[ExitFillLedger, ...]
    funding_events: tuple[FundingLedger, ...]
    journal_rows: tuple[JournalLedger, ...]
    stop_transitions: tuple[StopTransitionLedger, ...]
    breaker_transitions: tuple[BreakerTransitionLedger, ...]
    risk_decisions: tuple[RiskDecisionLedger, ...]
    rejections: tuple[RejectionLedger, ...]
    closed_episodes: tuple[ClosedEpisodeLedger, ...]
    curve: tuple[CurvePoint, ...]
    terminal_positions: tuple[OpenPositionAccrual, ...]


@dataclass(frozen=True, slots=True)
class _Intent:
    candidate_id: str
    decision_ts: datetime
    entry_ts: datetime
    symbol: str
    side: Side
    strategy: str
    strategy_rank: int
    pattern_id: str
    confluence_score: float
    decision_close: float
    entry_reference_price: float
    entry_price: float
    stop_price: float
    take_profit_price: float
    decision_stop_distance_pct: float
    entry_stop_distance_pct: float
    suggested_size_atr: float
    signal_manifest_hash: str
    config_sha256: str


@dataclass(frozen=True, slots=True)
class _Funding:
    ts: datetime
    symbol: str
    rate: float
    mark_price: float | None


@dataclass(slots=True)
class _Position:
    intent: _Intent
    entry_ts: datetime
    entry_price: float
    initial_stop: float
    active_stop: float
    pending_stop: float | None
    pending_stop_effective_ts: datetime | None
    tp1_price: float
    tp2_price: float
    original_quantity: float
    remaining_quantity: float
    entry_notional: float
    dynamic_leverage: float
    risk_budget: float
    wallet_before_entry: float
    entry_fee: float
    entry_spread: float
    entry_impact: float
    entry_cost: float
    bars_held: int
    last_bar_ts: datetime
    tp1_filled: bool
    tp2_filled: bool
    tp1_fill_bar_ts: datetime | None
    bars_after_tp1: int
    time_exit_due_ts: datetime | None
    favorable_extreme: float | None
    gross_realized: float
    adjusted_realized: float
    exit_cost_total: float
    funding_cashflow: float
    journal_amount_before_final: float


def _normalize_intent(raw: V15P2SignalIntentLike) -> _Intent:
    required = (
        "candidate_id",
        "decision_ts",
        "entry_ts",
        "symbol",
        "side",
        "strategy",
        "strategy_rank",
        "pattern_id",
        "confluence_score",
        "decision_close",
        "entry_reference_price",
        "entry_price",
        "stop_price",
        "take_profit_price",
        "decision_stop_distance_pct",
        "entry_stop_distance_pct",
        "suggested_size_atr",
        "signal_manifest_hash",
        "config_sha256",
    )
    missing = [name for name in required if not hasattr(raw, name)]
    if missing:
        raise TypeError(f"intent missing fields: {missing}")
    candidate = str(raw.candidate_id).strip()
    symbol = str(raw.symbol).strip()
    strategy = str(raw.strategy).strip()
    pattern = str(raw.pattern_id).strip()
    manifest_hash = str(raw.signal_manifest_hash).strip()
    config_hash = str(raw.config_sha256).strip()
    if not all((candidate, symbol, strategy, pattern, manifest_hash, config_hash)):
        raise ValueError("intent string identity fields must be non-empty")
    if candidate != FAIR_BASELINE_CANDIDATE_ID:
        raise ValueError("intent candidate_id does not identify the frozen v15p2 baseline")
    if strategy not in STRATEGY_RANKS:
        raise ValueError("intent strategy is not part of the frozen v15p2 baseline")
    if config_hash != EXPECTED_CONFIG_SHA256:
        raise ValueError("intent config_sha256 does not match the frozen v15p2 baseline")
    if manifest_hash != EXPECTED_MANIFEST_HASHES[strategy]:
        raise ValueError("signal_manifest_hash does not match the frozen effective manifest")
    side = str(raw.side).lower()
    if side not in {"long", "short"}:
        raise ValueError("intent side must be long or short")
    rank = _positive_int("strategy_rank", raw.strategy_rank, allow_zero=True)
    if rank != STRATEGY_RANKS[strategy]:
        raise ValueError("strategy_rank does not match the frozen VSA-then-Grimes order")
    decision_close = _finite("decision_close", raw.decision_close, positive=True)
    entry_reference = _finite("entry_reference_price", raw.entry_reference_price, positive=True)
    if entry_reference != decision_close:
        raise ValueError("entry_reference_price must equal decision_close")
    confluence = _finite("confluence_score", raw.confluence_score)
    if confluence < 0.0:
        raise ValueError("confluence_score must be >= 0")
    return _Intent(
        candidate_id=candidate,
        decision_ts=_utc("decision_ts", raw.decision_ts),
        entry_ts=_utc("entry_ts", raw.entry_ts),
        symbol=symbol,
        side=side,  # type: ignore[arg-type]
        strategy=strategy,
        strategy_rank=rank,
        pattern_id=pattern,
        confluence_score=confluence,
        decision_close=decision_close,
        entry_reference_price=entry_reference,
        entry_price=_finite("entry_price", raw.entry_price, positive=True),
        stop_price=_finite("stop_price", raw.stop_price, positive=True),
        take_profit_price=_finite("take_profit_price", raw.take_profit_price, positive=True),
        decision_stop_distance_pct=_finite(
            "decision_stop_distance_pct",
            raw.decision_stop_distance_pct,
            positive=True,
        ),
        entry_stop_distance_pct=_finite(
            "entry_stop_distance_pct",
            raw.entry_stop_distance_pct,
            positive=True,
        ),
        suggested_size_atr=_finite("suggested_size_atr", raw.suggested_size_atr, positive=True),
        signal_manifest_hash=manifest_hash,
        config_sha256=config_hash,
    )


def _normalize_frames(
    frames: Mapping[str, pd.DataFrame], policy: V15P2PortfolioPolicy
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, dict[datetime, int]]]:
    if not isinstance(frames, Mapping) or not frames:
        raise ValueError("frames must be a non-empty symbol -> DataFrame mapping")
    normalized: dict[str, list[dict[str, Any]]] = {}
    indexes: dict[str, dict[datetime, int]] = {}
    for raw_symbol, frame in frames.items():
        symbol = str(raw_symbol).strip()
        if not symbol or not isinstance(frame, pd.DataFrame):
            raise ValueError("each frame must have a non-empty symbol and be a DataFrame")
        missing = {"ts", "open", "high", "low", "close"} - set(frame.columns)
        if missing:
            raise ValueError(f"{symbol} frame missing columns: {sorted(missing)}")
        rows: list[dict[str, Any]] = []
        for record in frame.loc[:, ["ts", "open", "high", "low", "close"]].to_dict("records"):
            ts = _utc(f"{symbol}.ts", record["ts"])
            if ts.second != 0 or ts.microsecond != 0 or ts.minute % policy.bar_minutes != 0:
                raise ValueError(f"{symbol} timestamp is off the 15-minute UTC grid")
            values = {
                key: _finite(f"{symbol}.{key}", record[key], positive=True)
                for key in ("open", "high", "low", "close")
            }
            if values["high"] < max(values["open"], values["low"], values["close"]):
                raise ValueError(f"{symbol} invalid OHLC high at {ts.isoformat()}")
            if values["low"] > min(values["open"], values["high"], values["close"]):
                raise ValueError(f"{symbol} invalid OHLC low at {ts.isoformat()}")
            rows.append({"ts": ts, **values})
        rows.sort(key=lambda item: item["ts"])
        timestamps = [row["ts"] for row in rows]
        if not timestamps:
            raise ValueError(f"{symbol} frame is empty")
        if len(timestamps) != len(set(timestamps)):
            raise ValueError(f"{symbol} frame has duplicate timestamps")
        normalized[symbol] = rows
        indexes[symbol] = {ts: idx for idx, ts in enumerate(timestamps)}
    return normalized, indexes


def _normalize_funding(
    events: Iterable[Mapping[str, Any]] | Mapping[str, pd.DataFrame] | pd.DataFrame | None,
) -> tuple[_Funding, ...]:
    if events is None:
        return ()
    records: list[dict[str, Any]] = []
    if isinstance(events, pd.DataFrame):
        records.extend(events.to_dict("records"))
    elif isinstance(events, Mapping):
        for symbol, frame in events.items():
            if not isinstance(frame, pd.DataFrame):
                raise ValueError("mapped funding values must be DataFrames")
            records.extend({"symbol": symbol, **record} for record in frame.to_dict("records"))
    else:
        records.extend(dict(record) for record in events)
    result: list[_Funding] = []
    for record in records:
        ts_key = "ts" if "ts" in record else "funding_time"
        rate_key = "rate" if "rate" in record else "funding_rate"
        if "symbol" not in record or ts_key not in record or rate_key not in record:
            raise ValueError("funding event requires symbol, ts/funding_time and rate/funding_rate")
        raw_mark = record.get("mark_price")
        mark: float | None = None
        if raw_mark is not None:
            try:
                parsed = float(raw_mark)
            except (TypeError, ValueError):
                parsed = math.nan
            if math.isfinite(parsed) and parsed > 0.0:
                mark = parsed
        result.append(
            _Funding(
                ts=_utc("funding.ts", record[ts_key]),
                symbol=str(record["symbol"]).strip(),
                rate=_finite("funding.rate", record[rate_key]),
                mark_price=mark,
            )
        )
    ordered = tuple(sorted(result, key=lambda item: (item.ts, item.symbol)))
    keys = [(event.ts, event.symbol) for event in ordered]
    if len(keys) != len(set(keys)):
        raise ValueError("funding events contain duplicate symbol timestamps")
    return ordered


def _derive_daily_returns(bars: Mapping[str, list[dict[str, Any]]]) -> pd.DataFrame:
    series: dict[str, pd.Series] = {}
    for symbol, rows in bars.items():
        by_day: dict[date, list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            by_day[row["ts"].date()].append(row)
        closes: dict[date, float] = {}
        expected_rows = 24 * 60 // 15
        expected_delta = timedelta(minutes=15)
        for day, day_rows in by_day.items():
            day_rows.sort(key=lambda item: item["ts"])
            complete = (
                len(day_rows) == expected_rows
                and day_rows[0]["ts"].hour == 0
                and day_rows[0]["ts"].minute == 0
                and day_rows[-1]["ts"].hour == 23
                and day_rows[-1]["ts"].minute == 45
                and all(
                    day_rows[idx]["ts"] - day_rows[idx - 1]["ts"] == expected_delta
                    for idx in range(1, len(day_rows))
                )
            )
            if complete:
                closes[day] = day_rows[-1]["close"]
        ordered = sorted(closes)
        values: dict[pd.Timestamp, float] = {}
        for idx in range(1, len(ordered)):
            current = ordered[idx]
            previous = ordered[idx - 1]
            if current - previous == timedelta(days=1):
                values[pd.Timestamp(current, tz="UTC")] = math.log(
                    closes[current] / closes[previous]
                )
        series[symbol] = pd.Series(values, dtype=float)
    if not series:
        return pd.DataFrame()
    return pd.DataFrame(series).sort_index()


def _normalize_daily_returns(
    daily_returns: pd.DataFrame | Mapping[str, pd.Series] | None,
    bars: Mapping[str, list[dict[str, Any]]],
) -> pd.DataFrame:
    if daily_returns is None:
        return _derive_daily_returns(bars)
    if isinstance(daily_returns, pd.DataFrame):
        frame = daily_returns.copy()
    elif isinstance(daily_returns, Mapping):
        if any(not isinstance(value, pd.Series) for value in daily_returns.values()):
            raise ValueError("daily_returns mapping values must be pandas Series")
        frame = pd.DataFrame(dict(daily_returns))
    else:
        raise TypeError("daily_returns must be a DataFrame, mapping of Series, or None")
    normalized_index: list[pd.Timestamp] = []
    for raw_index in frame.index:
        stamp = pd.Timestamp(raw_index)
        stamp = stamp.tz_localize("UTC") if stamp.tzinfo is None else stamp.tz_convert("UTC")
        normalized_index.append(stamp.normalize())
    frame.index = pd.DatetimeIndex(normalized_index)
    frame = frame.apply(pd.to_numeric, errors="coerce")
    return frame.groupby(level=0).last().sort_index()


def _execution_components(
    notional: float, scenario: V15P2CostScenario
) -> tuple[float, float, float]:
    scale = max(float(notional), 0.0) * scenario.cost_multiplier / 10_000.0
    return (
        scale * scenario.fee_bps_per_fill,
        scale * scenario.spread_slippage_bps_per_fill,
        scale * scenario.impact_bps_per_fill,
    )


def _adjust_price_pnl(gross: float, scenario: V15P2CostScenario) -> tuple[float, float]:
    if gross > 0.0:
        multiplier = scenario.positive_price_pnl_multiplier
    elif gross < 0.0:
        multiplier = scenario.negative_price_pnl_multiplier
    else:
        multiplier = 1.0
    return multiplier, gross * multiplier


def _week_key(ts: datetime) -> str:
    iso = ts.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def _month_key(ts: datetime) -> str:
    return f"{ts.year:04d}-{ts.month:02d}"


def _scenario_identity(scenario: V15P2CostScenario) -> tuple[str, bool]:
    canonical = SCENARIOS[scenario.name]
    if scenario == canonical:
        return scenario.name, True
    payload = json.dumps(asdict(scenario), sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return f"CUSTOM:{scenario.name}:{digest}", False


def simulate_v15p2_portfolio(
    frames: Mapping[str, pd.DataFrame],
    intents: Iterable[V15P2SignalIntentLike],
    funding_events: Iterable[Mapping[str, Any]]
    | Mapping[str, pd.DataFrame]
    | pd.DataFrame
    | None = None,
    daily_returns: pd.DataFrame | Mapping[str, pd.Series] | None = None,
    *,
    scenario: ScenarioName | V15P2CostScenario = "B",
    policy: V15P2PortfolioPolicy | None = None,
    evaluation_start: datetime | None = None,
    evaluation_end: datetime | None = None,
) -> V15P2PortfolioResult:
    """Replay one independent B/C2/H path over immutable in-memory inputs."""

    policy = policy or V15P2PortfolioPolicy()
    if isinstance(scenario, str):
        try:
            scenario_model = SCENARIOS[scenario]
        except KeyError as exc:
            raise ValueError("scenario must be B, C2 or H") from exc
    elif isinstance(scenario, V15P2CostScenario):
        scenario_model = scenario
    else:
        raise TypeError("scenario must be a scenario name or V15P2CostScenario")
    scenario_identity, scenario_is_canonical = _scenario_identity(scenario_model)

    bars, indexes = _normalize_frames(frames, policy)
    all_timestamps = [row["ts"] for rows in bars.values() for row in rows]
    default_start = min(all_timestamps)
    default_end = max(all_timestamps) + timedelta(minutes=policy.bar_minutes)
    evaluation_start = (
        default_start if evaluation_start is None else _utc("evaluation_start", evaluation_start)
    )
    evaluation_end = (
        default_end if evaluation_end is None else _utc("evaluation_end", evaluation_end)
    )
    if evaluation_start >= evaluation_end:
        raise ValueError("evaluation_start must be before evaluation_end")
    for name, boundary in (
        ("evaluation_start", evaluation_start),
        ("evaluation_end", evaluation_end),
    ):
        if (
            boundary.second != 0
            or boundary.microsecond != 0
            or boundary.minute % policy.bar_minutes != 0
        ):
            raise ValueError(f"{name} must be on the 15-minute UTC grid")
    if not any(evaluation_start <= ts < evaluation_end for ts in all_timestamps):
        raise ValueError("evaluation window contains no bars")
    funding = tuple(
        event
        for event in _normalize_funding(funding_events)
        if evaluation_start <= event.ts < evaluation_end
    )
    returns_frame = _normalize_daily_returns(daily_returns, bars)
    bar_delta = timedelta(minutes=policy.bar_minutes)
    gap_limit = timedelta(minutes=policy.gap_max_minutes)
    cooldown_delta = timedelta(days=policy.cooldown_days)

    normalized_intents = [_normalize_intent(intent) for intent in intents]
    normalized_intents.sort(
        key=lambda item: (
            item.decision_ts,
            item.symbol,
            item.strategy_rank,
            item.side,
            item.candidate_id,
        )
    )
    scheduled: dict[datetime, list[_Intent]] = defaultdict(list)
    rejections: list[RejectionLedger] = []

    def reject(intent: _Intent, reason: str, detail: str = "") -> None:
        rejections.append(
            RejectionLedger(
                candidate_id=intent.candidate_id,
                decision_ts=intent.decision_ts,
                entry_ts=intent.entry_ts,
                symbol=intent.symbol,
                side=intent.side,
                strategy=intent.strategy,
                reason=reason,
                detail=detail,
            )
        )

    for intent in normalized_intents:
        if not (evaluation_start <= intent.entry_ts < evaluation_end):
            reject(intent, "entry_outside_evaluation_window")
            continue
        symbol_rows = bars.get(intent.symbol)
        decision_idx = indexes.get(intent.symbol, {}).get(intent.decision_ts)
        if symbol_rows is None or decision_idx is None:
            reject(intent, "decision_bar_missing")
            continue
        if intent.entry_ts != intent.decision_ts + bar_delta:
            reject(intent, "entry_ts_not_next_exact_bar")
            continue
        if decision_idx + 1 >= len(symbol_rows):
            reject(intent, "entry_bar_missing")
            continue
        actual_next = symbol_rows[decision_idx + 1]
        if actual_next["ts"] != intent.entry_ts:
            reject(intent, "entry_bar_not_contiguous")
            continue
        decision_close = symbol_rows[decision_idx]["close"]
        if not _close_enough(decision_close, intent.decision_close):
            reject(
                intent,
                "decision_close_mismatch",
                f"intent={intent.decision_close:.12g},bar_close={decision_close:.12g}",
            )
            continue
        if not _close_enough(actual_next["open"], intent.entry_price):
            reject(
                intent,
                "entry_price_mismatch",
                f"intent={intent.entry_price:.12g},bar_open={actual_next['open']:.12g}",
            )
            continue
        decision_stop_pct = abs(intent.decision_close - intent.stop_price) / intent.decision_close
        if not _close_enough(decision_stop_pct, intent.decision_stop_distance_pct):
            reject(
                intent,
                "decision_stop_distance_mismatch",
                f"intent={intent.decision_stop_distance_pct:.12g},actual={decision_stop_pct:.12g}",
            )
            continue
        entry_stop_pct = abs(intent.entry_price - intent.stop_price) / intent.entry_price
        if not _close_enough(entry_stop_pct, intent.entry_stop_distance_pct):
            reject(
                intent,
                "entry_stop_distance_mismatch",
                f"intent={intent.entry_stop_distance_pct:.12g},actual={entry_stop_pct:.12g}",
            )
            continue
        if intent.confluence_score < policy.minimum_confluence:
            reject(intent, "confluence_below_minimum")
            continue
        if decision_stop_pct < policy.minimum_stop_distance_pct:
            reject(intent, "decision_stop_distance_below_minimum")
            continue
        scheduled[intent.entry_ts].append(intent)

    bars_by_ts: dict[datetime, list[tuple[str, dict[str, Any]]]] = defaultdict(list)
    for symbol, rows in bars.items():
        for row in rows:
            if evaluation_start <= row["ts"] < evaluation_end:
                bars_by_ts[row["ts"]].append((symbol, row))

    wallet = policy.initial_wallet
    wallet_peak = wallet
    marks: dict[str, float] = {}
    positions: dict[str, _Position] = {}
    last_entry: dict[tuple[str, Side], datetime] = {}
    entry_ledgers: list[EntryFillLedger] = []
    exit_ledgers: list[ExitFillLedger] = []
    funding_ledgers: list[FundingLedger] = []
    journal_ledgers: list[JournalLedger] = []
    stop_ledgers: list[StopTransitionLedger] = []
    breaker_ledgers: list[BreakerTransitionLedger] = []
    risk_ledgers: list[RiskDecisionLedger] = []
    episodes: list[ClosedEpisodeLedger] = []
    curve: list[CurvePoint] = []
    total_execution_cost = 0.0
    total_funding = 0.0
    funding_idx = 0

    current_day: str | None = None
    current_week: str | None = None
    current_month: str | None = None
    daily_anchor = wallet
    weekly_anchor = wallet
    monthly_anchor = wallet
    daily_journal_net = 0.0
    monthly_long_journal_net = 0.0
    monthly_short_journal_net = 0.0
    consecutive_losses = 0
    consumed_consecutive_losses = 0
    final_journal_outcomes: list[tuple[datetime, float]] = []
    blocked_until: dict[str, datetime] = {}
    combined_triggered = {"daily": False, "weekly": False, "monthly_combined": False}
    combined_clock_source: str | None = None
    side_latched: set[Side] = set()
    side_blocked_until: dict[Side, datetime] = {}
    side_expiry_recorded: set[Side] = set()

    def update_wallet_peak() -> None:
        nonlocal wallet_peak
        wallet_peak = max(wallet_peak, wallet)

    def refresh_consecutive_streak(ts: datetime) -> None:
        nonlocal consecutive_losses, consumed_consecutive_losses
        cutoff = ts - timedelta(days=policy.consecutive_loss_lookback_days)
        streak = 0
        for outcome_ts, amount in reversed(final_journal_outcomes):
            if outcome_ts < cutoff:
                break
            if amount < 0.0:
                streak += 1
                continue
            break
        consecutive_losses = streak
        consumed_consecutive_losses = min(consumed_consecutive_losses, streak)

    def reset_anchors(ts: datetime) -> None:
        nonlocal current_day, current_week, current_month
        nonlocal daily_anchor, weekly_anchor, monthly_anchor
        nonlocal daily_journal_net
        nonlocal monthly_long_journal_net, monthly_short_journal_net
        day_key = ts.date().isoformat()
        week_key = _week_key(ts)
        month_key = _month_key(ts)
        # Live AccountState.equity_usdt is Binance futures wallet_balance,
        # explicitly excluding open unrealized PnL.  MTM belongs only to the
        # evaluation NAV curve, never to breaker anchors.
        equity = wallet
        if current_day != day_key:
            current_day = day_key
            daily_anchor = equity
            daily_journal_net = 0.0
        if current_week != week_key:
            current_week = week_key
            weekly_anchor = equity
        if current_month != month_key:
            for side in sorted(side_latched):
                carried_until = side_blocked_until.get(side)
                breaker_ledgers.append(
                    BreakerTransitionLedger(
                        ts=ts,
                        breaker=side,
                        action="monthly_reset",
                        side=side,
                        metric_value=(
                            monthly_long_journal_net
                            if side == "long"
                            else monthly_short_journal_net
                        ),
                        threshold_value=0.0,
                        blocked_until=(
                            carried_until
                            if carried_until is not None and ts < carried_until
                            else None
                        ),
                    )
                )
            side_latched.clear()
            current_month = month_key
            monthly_anchor = equity
            monthly_long_journal_net = 0.0
            monthly_short_journal_net = 0.0

    def evaluate_breakers(ts: datetime) -> None:
        nonlocal combined_clock_source
        refresh_consecutive_streak(ts)
        equity = wallet
        combined_metrics = {
            "daily": (
                daily_journal_net,
                -daily_anchor * policy.daily_loss_pct,
                policy.daily_halt_days,
            ),
            "weekly": (
                equity - weekly_anchor,
                -weekly_anchor * policy.weekly_loss_pct,
                policy.weekly_halt_days,
            ),
            "monthly_combined": (
                equity - monthly_anchor,
                -monthly_anchor * policy.monthly_combined_loss_pct,
                policy.monthly_halt_days,
            ),
        }
        previous_flags = dict(combined_triggered)
        for key, (metric, threshold, _halt_days) in combined_metrics.items():
            combined_triggered[key] = metric <= threshold

        # Current live DDBreaker owns one combined clock.  Its update order is
        # deliberately daily -> weekly -> monthly (if/elif), and an active
        # trigger rolls that one clock forward on every state update.
        selected = next(
            (key for key in ("daily", "weekly", "monthly_combined") if combined_triggered[key]),
            None,
        )
        if selected is not None:
            metric, threshold, halt_days = combined_metrics[selected]
            until = ts + timedelta(days=halt_days)
            if not previous_flags[selected] or combined_clock_source != selected:
                breaker_ledgers.append(
                    BreakerTransitionLedger(
                        ts=ts,
                        breaker=selected,
                        action="activated",
                        side=None,
                        metric_value=metric,
                        threshold_value=threshold,
                        blocked_until=until,
                    )
                )
            blocked_until["combined"] = until
            combined_clock_source = selected
        else:
            combined_until = blocked_until.get("combined")
            if combined_until is not None and ts >= combined_until:
                expired_source = combined_clock_source or "combined"
                metric, threshold, _halt_days = combined_metrics.get(
                    expired_source, (0.0, 0.0, 0.0)
                )
                del blocked_until["combined"]
                combined_clock_source = None
                breaker_ledgers.append(
                    BreakerTransitionLedger(
                        ts=ts,
                        breaker=expired_source,
                        action="expired",
                        side=None,
                        metric_value=metric,
                        threshold_value=threshold,
                        blocked_until=None,
                    )
                )

        for side, metric, pct in (
            ("long", monthly_long_journal_net, policy.monthly_long_loss_pct),
            ("short", monthly_short_journal_net, policy.monthly_short_loss_pct),
        ):
            threshold = -monthly_anchor * pct
            if metric <= threshold and side not in side_latched:
                typed_side: Side = side  # type: ignore[assignment]
                side_latched.add(typed_side)
                until = ts + timedelta(days=policy.monthly_halt_days)
                side_blocked_until[typed_side] = until
                side_expiry_recorded.discard(typed_side)
                breaker_ledgers.append(
                    BreakerTransitionLedger(
                        ts=ts,
                        breaker=side,
                        action="activated",
                        side=typed_side,
                        metric_value=metric,
                        threshold_value=threshold,
                        blocked_until=until,
                    )
                )
            typed_side = side  # type: ignore[assignment]
            side_until = side_blocked_until.get(typed_side)
            if (
                side_until is not None
                and ts >= side_until
                and typed_side not in side_expiry_recorded
            ):
                side_expiry_recorded.add(typed_side)
                breaker_ledgers.append(
                    BreakerTransitionLedger(
                        ts=ts,
                        breaker=side,
                        action="expired",
                        side=typed_side,
                        metric_value=metric,
                        threshold_value=threshold,
                        blocked_until=None,
                    )
                )

        consecutive_until = blocked_until.get("consecutive")
        if consecutive_until is not None and ts >= consecutive_until:
            del blocked_until["consecutive"]
            breaker_ledgers.append(
                BreakerTransitionLedger(
                    ts=ts,
                    breaker="consecutive",
                    action="expired",
                    side=None,
                    metric_value=float(consecutive_losses - consumed_consecutive_losses),
                    threshold_value=float(policy.consecutive_loss_count),
                    blocked_until=None,
                )
            )

    def activate_consecutive_breaker(ts: datetime) -> None:
        nonlocal consumed_consecutive_losses
        effective = consecutive_losses - consumed_consecutive_losses
        if "consecutive" in blocked_until or effective < policy.consecutive_loss_count:
            return
        consumed_consecutive_losses = consecutive_losses
        until = ts + timedelta(days=policy.consecutive_pause_days)
        blocked_until["consecutive"] = until
        breaker_ledgers.append(
            BreakerTransitionLedger(
                ts=ts,
                breaker="consecutive",
                action="activated",
                side=None,
                metric_value=float(effective),
                threshold_value=float(policy.consecutive_loss_count),
                blocked_until=until,
            )
        )

    def blocking_reason(side: Side, ts: datetime) -> str | None:
        combined_until = blocked_until.get("combined")
        if combined_until is not None and ts < combined_until:
            return f"breaker_{combined_clock_source or 'combined'}"
        for key in ("daily", "weekly", "monthly_combined"):
            if combined_triggered[key]:
                return f"breaker_{key}"
        if "consecutive" in blocked_until and ts < blocked_until["consecutive"]:
            return "breaker_consecutive"
        if side in side_blocked_until and ts < side_blocked_until[side]:
            return f"breaker_monthly_{side}"
        return None

    def current_open_notional() -> float:
        return sum(
            marks.get(symbol, position.entry_price) * position.remaining_quantity
            for symbol, position in positions.items()
        )

    def nav_components() -> tuple[float, float, float, float]:
        gross_total = 0.0
        adjusted_total = 0.0
        accrued_cost = 0.0
        for symbol, position in positions.items():
            mark = marks.get(symbol, position.entry_price)
            direction = 1.0 if position.intent.side == "long" else -1.0
            gross = direction * (mark - position.entry_price) * position.remaining_quantity
            _, adjusted = _adjust_price_pnl(gross, scenario_model)
            exit_cost = sum(
                _execution_components(mark * position.remaining_quantity, scenario_model)
            )
            gross_total += gross
            adjusted_total += adjusted
            accrued_cost += exit_cost
        return gross_total, adjusted_total, accrued_cost, wallet + adjusted_total - accrued_cost

    def correlation_factor(
        intent: _Intent,
    ) -> tuple[float, float | None, bool, str | None]:
        if not positions:
            return 1.0, None, False, None
        if returns_frame.empty:
            return 0.0, None, False, "daily_returns_empty"
        if intent.symbol not in returns_frame.columns:
            return 0.0, None, False, f"candidate_column_missing:{intent.symbol}"
        cutoff = pd.Timestamp(intent.entry_ts.date(), tz="UTC")
        expected_index = pd.date_range(
            cutoff - pd.Timedelta(days=policy.correlation_lookback_days),
            cutoff - pd.Timedelta(days=1),
            freq="D",
            tz="UTC",
        )
        observed: list[float] = []
        for symbol in sorted(positions):
            if symbol not in returns_frame.columns:
                return 0.0, None, False, f"open_symbol_column_missing:{symbol}"
            available_index = returns_frame.index.intersection(expected_index)
            if not available_index.equals(expected_index):
                return (
                    0.0,
                    None,
                    False,
                    f"pair_history_calendar:{intent.symbol}:{symbol}:{len(available_index)}"
                    f"/{policy.correlation_lookback_days}",
                )
            pair = returns_frame.loc[expected_index, [intent.symbol, symbol]]
            pair_values = pair.to_numpy(dtype=float)
            if not all(math.isfinite(value) for value in pair_values.flat):
                return 0.0, None, False, f"pair_history_nonfinite:{intent.symbol}:{symbol}"
            value = float(pair.iloc[:, 0].corr(pair.iloc[:, 1]))
            if not math.isfinite(value):
                return 0.0, None, False, f"pair_correlation_undefined:{intent.symbol}:{symbol}"
            observed.append(abs(value))
        maximum = max(observed) if observed else None
        if maximum is not None and maximum >= policy.correlation_block_at:
            return 0.0, maximum, True, None
        if maximum is not None and maximum > policy.correlation_reduce_above:
            return policy.correlation_reduction_factor, maximum, False, None
        return 1.0, maximum, False, None

    def close_slice(
        position: _Position,
        *,
        ts: datetime,
        price: float,
        quantity: float,
        reason: str,
    ) -> None:
        nonlocal wallet, total_execution_cost, daily_journal_net
        nonlocal monthly_long_journal_net, monthly_short_journal_net
        quantity = min(quantity, position.remaining_quantity)
        if quantity <= 0.0:
            return
        direction = 1.0 if position.intent.side == "long" else -1.0
        gross = direction * (price - position.entry_price) * quantity
        payoff_multiplier, adjusted = _adjust_price_pnl(gross, scenario_model)
        fee, spread, impact = _execution_components(price * quantity, scenario_model)
        exit_cost = fee + spread + impact
        fraction = quantity / position.original_quantity
        allocated_entry_cost = position.entry_cost * fraction
        fill_net_excluding_funding = adjusted - exit_cost - allocated_entry_cost
        wallet += adjusted - exit_cost
        total_execution_cost += exit_cost
        position.remaining_quantity = max(position.remaining_quantity - quantity, 0.0)
        position.gross_realized += gross
        position.adjusted_realized += adjusted
        position.exit_cost_total += exit_cost
        is_final = position.remaining_quantity <= position.original_quantity * 1e-12
        if is_final:
            position.remaining_quantity = 0.0
        exit_ledgers.append(
            ExitFillLedger(
                candidate_id=position.intent.candidate_id,
                ts=ts,
                symbol=position.intent.symbol,
                side=position.intent.side,
                strategy=position.intent.strategy,
                reason=reason,
                price=price,
                quantity=quantity,
                fraction_of_original=fraction,
                remaining_quantity=position.remaining_quantity,
                gross_price_pnl=gross,
                payoff_multiplier=payoff_multiplier,
                adjusted_price_pnl=adjusted,
                allocated_entry_cost=allocated_entry_cost,
                fee=fee,
                spread_slippage=spread,
                impact=impact,
                exit_execution_cost=exit_cost,
                net_pnl_excluding_funding=fill_net_excluding_funding,
                wallet_after_fill=wallet,
                is_final=is_final,
            )
        )
        episode_net = (
            position.adjusted_realized
            - position.entry_cost
            - position.exit_cost_total
            + position.funding_cashflow
        )
        if is_final:
            journal_amount = episode_net - position.journal_amount_before_final
        else:
            # The deployed partial-close hook journals scenario-adjusted price
            # PnL only.  Costs and funding reconcile once, on the final row.
            journal_amount = adjusted
            position.journal_amount_before_final += journal_amount
        daily_journal_net += journal_amount
        if position.intent.side == "long":
            monthly_long_journal_net += journal_amount
        else:
            monthly_short_journal_net += journal_amount
        journal_ledgers.append(
            JournalLedger(
                candidate_id=position.intent.candidate_id,
                ts=ts,
                symbol=position.intent.symbol,
                side=position.intent.side,
                strategy=position.intent.strategy,
                exit_reason=reason,
                amount=journal_amount,
                is_final=is_final,
                cumulative_episode_journal_amount=(
                    position.journal_amount_before_final
                    if not is_final
                    else position.journal_amount_before_final + journal_amount
                ),
                episode_scenario_net_if_final=episode_net if is_final else None,
            )
        )
        if not is_final:
            evaluate_breakers(ts)
            return
        del positions[position.intent.symbol]
        final_journal_outcomes.append((ts, journal_amount))
        refresh_consecutive_streak(ts)
        episodes.append(
            ClosedEpisodeLedger(
                candidate_id=position.intent.candidate_id,
                symbol=position.intent.symbol,
                side=position.intent.side,
                strategy=position.intent.strategy,
                pattern_id=position.intent.pattern_id,
                decision_ts=position.intent.decision_ts,
                entry_ts=position.entry_ts,
                exit_ts=ts,
                final_exit_reason=reason,
                entry_price=position.entry_price,
                initial_stop=position.initial_stop,
                original_quantity=position.original_quantity,
                bars_held=position.bars_held,
                gross_price_pnl=position.gross_realized,
                adjusted_price_pnl=position.adjusted_realized,
                total_entry_execution_cost=position.entry_cost,
                total_exit_execution_cost=position.exit_cost_total,
                funding_cashflow=position.funding_cashflow,
                net_pnl=episode_net,
                wallet_before_entry=position.wallet_before_entry,
                wallet_after_exit=wallet,
            )
        )
        activate_consecutive_breaker(ts)
        evaluate_breakers(ts)

    for ts in sorted(bars_by_ts):
        current_rows = sorted(bars_by_ts[ts], key=lambda item: item[0])

        # Funding at the exact open belongs to a position carried into that
        # instant; a position opened at the same timestamp does not receive it.
        while funding_idx < len(funding) and funding[funding_idx].ts <= ts:
            settlement_ts = funding[funding_idx].ts
            # Binance settles every symbol's funding for one timestamp before
            # the post-boundary account snapshot.  Apply the entire timestamp
            # batch before resetting anchors; otherwise the first alphabetic
            # symbol would be inside the new anchor and later symbols outside.
            while funding_idx < len(funding) and funding[funding_idx].ts == settlement_ts:
                event = funding[funding_idx]
                position = positions.get(event.symbol)
                if position is not None:
                    mark = event.mark_price or marks.get(event.symbol, position.entry_price)
                    notional = mark * position.remaining_quantity
                    direction = 1.0 if position.intent.side == "long" else -1.0
                    cashflow = (
                        -direction * notional * event.rate * scenario_model.funding_multiplier
                    )
                    wallet += cashflow
                    total_funding += cashflow
                    position.funding_cashflow += cashflow
                    funding_ledgers.append(
                        FundingLedger(
                            candidate_id=position.intent.candidate_id,
                            ts=event.ts,
                            symbol=event.symbol,
                            side=position.intent.side,
                            rate=event.rate,
                            mark_price=mark,
                            remaining_quantity=position.remaining_quantity,
                            notional=notional,
                            multiplier=scenario_model.funding_multiplier,
                            cashflow=cashflow,
                            wallet_after_funding=wallet,
                        )
                    )
                funding_idx += 1
            # A live post-boundary AccountState observes Binance's already
            # settled wallet.  Therefore an exact 00:00 funding cashflow must
            # be included in the new day/week/month anchor, while the carried
            # position still receives that settlement.
            reset_anchors(settlement_ts)
            evaluate_breakers(settlement_ts)

        # Account-equity breakers observe the current tradable open.  This is
        # also the mark used by gap-stop handling and by pre-entry risk gates.
        for symbol, row in current_rows:
            marks[symbol] = row["open"]
        reset_anchors(ts)
        evaluate_breakers(ts)

        # First tradable open after a >30m gap forces a pessimistic exit.  On a
        # contiguous bar, previously calculated stop/time states become active
        # at the open, before any current-bar high/low can be observed.
        for symbol, row in current_rows:
            position = positions.get(symbol)
            if position is None:
                continue
            if ts - position.last_bar_ts > gap_limit:
                close_slice(
                    position,
                    ts=ts,
                    price=row["open"],
                    quantity=position.remaining_quantity,
                    reason="data_gap",
                )
                continue
            if (
                position.pending_stop is not None
                and position.pending_stop_effective_ts is not None
                and ts >= position.pending_stop_effective_ts
            ):
                position.active_stop = position.pending_stop
                position.pending_stop = None
                position.pending_stop_effective_ts = None
            active_stop = position.active_stop
            gap_through_stop = (
                row["open"] <= active_stop
                if position.intent.side == "long"
                else row["open"] >= active_stop
            )
            if gap_through_stop:
                fill_price = (
                    min(row["open"], active_stop)
                    if position.intent.side == "long"
                    else max(row["open"], active_stop)
                )
                if _close_enough(active_stop, position.initial_stop):
                    reason = "initial_stop"
                elif _close_enough(active_stop, position.entry_price):
                    reason = "break_even_stop"
                else:
                    reason = "trailing_stop"
                close_slice(
                    position,
                    ts=ts,
                    price=fill_price,
                    quantity=position.remaining_quantity,
                    reason=reason,
                )
                continue
            if position.time_exit_due_ts is not None and ts >= position.time_exit_due_ts:
                close_slice(
                    position,
                    ts=ts,
                    price=row["open"],
                    quantity=position.remaining_quantity,
                    reason="runner_time_stop",
                )

        # Required even on bars with no funding/fills: combined flags are
        # recomputed from current equity and expired cooldowns are consumed.
        evaluate_breakers(ts)
        entry_rows = {symbol: row for symbol, row in current_rows}
        for intent in sorted(
            scheduled.get(ts, ()),
            key=lambda item: (item.symbol, item.strategy_rank, item.side, item.candidate_id),
        ):
            if intent.symbol in positions:
                reject(intent, "symbol_already_open")
                continue
            breaker_reason = blocking_reason(intent.side, ts)
            if breaker_reason is not None:
                reject(intent, breaker_reason)
                continue
            previous_entry = last_entry.get((intent.symbol, intent.side))
            if previous_entry is not None and ts - previous_entry < cooldown_delta:
                reject(intent, "same_symbol_side_cooldown")
                continue
            if len(positions) >= policy.max_open_positions:
                reject(intent, "max_open_positions")
                continue
            same_side_count = sum(
                position.intent.side == intent.side for position in positions.values()
            )
            if same_side_count >= policy.max_same_side_positions:
                reject(intent, "max_same_side_positions")
                continue
            row = entry_rows.get(intent.symbol)
            if row is None:
                reject(intent, "entry_bar_missing")
                continue
            if wallet <= 0.0:
                reject(intent, "non_positive_wallet")
                continue
            # Current live RiskOfficer observes and persists the running wallet
            # peak when an intent reaches its DD-throttle/sizing stage, before
            # validating whether the next-open stop remains protective.
            update_wallet_peak()
            if (intent.side == "long" and intent.stop_price >= row["open"]) or (
                intent.side == "short" and intent.stop_price <= row["open"]
            ):
                reject(intent, "stop_on_wrong_side")
                continue
            stop_distance = abs(row["open"] - intent.stop_price)
            stop_pct = stop_distance / row["open"]
            # Intermediate exit/funding highs with no signal are not observable
            # to the live throttle and therefore do not ratchet this peak.
            wallet_dd = (wallet_peak - wallet) / wallet_peak if wallet_peak > 0.0 else 0.0
            dd_factor = (
                policy.dd_throttle_multiplier if wallet_dd >= policy.dd_throttle_threshold else 1.0
            )
            normalizer = max(
                policy.stop_normalizer_min,
                min(
                    policy.stop_normalizer_max,
                    policy.stop_normalizer_target / stop_pct,
                ),
            )
            base_budget = wallet * policy.base_risk_per_trade
            risk_budget = base_budget * normalizer * dd_factor
            requested_quantity = risk_budget / stop_distance
            requested_notional = requested_quantity * row["open"]
            cap_bindings: list[str] = []
            symbol_cap = wallet * policy.max_symbol_notional_pct
            pre_correlation_notional = requested_notional
            if pre_correlation_notional > symbol_cap:
                pre_correlation_notional = symbol_cap
                cap_bindings.append("max_symbol_notional")
            if pre_correlation_notional < policy.minimum_notional:
                reject(
                    intent,
                    "below_min_notional",
                    f"notional={pre_correlation_notional:.8g},min={policy.minimum_notional:.8g}",
                )
                continue
            open_notional = current_open_notional()
            if (
                open_notional + pre_correlation_notional
                > wallet * policy.max_portfolio_notional_x + 1e-10
            ):
                reject(
                    intent,
                    "max_portfolio_notional",
                    f"open={open_notional:.8g},new={pre_correlation_notional:.8g}",
                )
                continue
            dynamic_leverage = min(
                policy.leverage,
                max(1.0, pre_correlation_notional / wallet),
            )
            used_margin = sum(
                marks.get(symbol, position.entry_price)
                * position.remaining_quantity
                / position.dynamic_leverage
                for symbol, position in positions.items()
            )
            free_margin = max(wallet - used_margin, 0.0)
            required_margin = pre_correlation_notional / dynamic_leverage
            if required_margin > free_margin * policy.initial_margin_buffer + 1e-10:
                reject(
                    intent,
                    "initial_margin_buffer",
                    f"required={required_margin:.8g},allowed={free_margin * policy.initial_margin_buffer:.8g}",
                )
                continue
            corr_factor, max_corr, corr_block, corr_unavailable = correlation_factor(intent)
            if corr_unavailable is not None:
                reject(intent, "correlation_history_unavailable", corr_unavailable)
                continue
            if corr_block:
                reject(intent, "correlation_hard_block", f"max_abs_corr={max_corr:.8g}")
                continue
            post_correlation_notional = pre_correlation_notional * corr_factor
            if stop_pct > (1.0 / dynamic_leverage) * policy.stop_liquidation_safety_ratio:
                reject(
                    intent,
                    "stop_liquidation_margin_safety",
                    f"stop_pct={stop_pct:.8g},leverage={dynamic_leverage:.8g}",
                )
                continue
            accepted_notional = post_correlation_notional
            quantity = accepted_notional / row["open"]
            if quantity <= 0.0 or not math.isfinite(quantity):
                reject(intent, "invalid_position_size")
                continue

            effective_risk = quantity * stop_distance
            risk_ledgers.append(
                RiskDecisionLedger(
                    candidate_id=intent.candidate_id,
                    decision_ts=intent.decision_ts,
                    entry_ts=ts,
                    symbol=intent.symbol,
                    side=intent.side,
                    strategy=intent.strategy,
                    wallet_before_entry=wallet,
                    wallet_peak=wallet_peak,
                    wallet_drawdown=wallet_dd,
                    base_risk_budget=base_budget,
                    stop_normalizer_factor=normalizer,
                    drawdown_factor=dd_factor,
                    correlation_factor=corr_factor,
                    maximum_observed_correlation=max_corr,
                    requested_risk_budget=risk_budget,
                    requested_notional=requested_notional,
                    pre_correlation_notional=pre_correlation_notional,
                    post_correlation_notional=post_correlation_notional,
                    accepted_notional=accepted_notional,
                    dynamic_leverage=dynamic_leverage,
                    effective_initial_stop_risk=effective_risk,
                    cap_bindings=tuple(cap_bindings),
                    open_notional_before=open_notional,
                    free_margin_before=free_margin,
                    required_initial_margin=required_margin,
                )
            )
            fee, spread, impact = _execution_components(accepted_notional, scenario_model)
            entry_cost = fee + spread + impact
            wallet_before = wallet
            wallet -= entry_cost
            total_execution_cost += entry_cost
            evaluate_breakers(ts)
            direction = 1.0 if intent.side == "long" else -1.0
            risk_distance = abs(row["open"] - intent.stop_price)
            tp1_price = row["open"] + direction * risk_distance * policy.tp1_r
            tp2_price = row["open"] + direction * risk_distance * policy.tp2_r
            position = _Position(
                intent=intent,
                entry_ts=ts,
                entry_price=row["open"],
                initial_stop=intent.stop_price,
                active_stop=intent.stop_price,
                pending_stop=None,
                pending_stop_effective_ts=None,
                tp1_price=tp1_price,
                tp2_price=tp2_price,
                original_quantity=quantity,
                remaining_quantity=quantity,
                entry_notional=accepted_notional,
                dynamic_leverage=dynamic_leverage,
                risk_budget=risk_budget,
                wallet_before_entry=wallet_before,
                entry_fee=fee,
                entry_spread=spread,
                entry_impact=impact,
                entry_cost=entry_cost,
                bars_held=0,
                last_bar_ts=ts,
                tp1_filled=False,
                tp2_filled=False,
                tp1_fill_bar_ts=None,
                bars_after_tp1=0,
                time_exit_due_ts=None,
                favorable_extreme=None,
                gross_realized=0.0,
                adjusted_realized=0.0,
                exit_cost_total=0.0,
                funding_cashflow=0.0,
                journal_amount_before_final=0.0,
            )
            positions[intent.symbol] = position
            last_entry[(intent.symbol, intent.side)] = ts
            entry_ledgers.append(
                EntryFillLedger(
                    candidate_id=intent.candidate_id,
                    decision_ts=intent.decision_ts,
                    entry_ts=ts,
                    symbol=intent.symbol,
                    side=intent.side,
                    strategy=intent.strategy,
                    pattern_id=intent.pattern_id,
                    entry_price=row["open"],
                    initial_stop=intent.stop_price,
                    tp1_price=tp1_price,
                    tp2_price=tp2_price,
                    original_quantity=quantity,
                    entry_notional=accepted_notional,
                    dynamic_leverage=dynamic_leverage,
                    wallet_before_entry=wallet_before,
                    wallet_after_entry=wallet,
                    risk_budget=risk_budget,
                    effective_initial_stop_risk=effective_risk,
                    fee=fee,
                    spread_slippage=spread,
                    impact=impact,
                    execution_cost=entry_cost,
                    scenario=scenario_model.name,
                    signal_manifest_hash=intent.signal_manifest_hash,
                    config_sha256=intent.config_sha256,
                )
            )

        # Intrabar ambiguity is resolved pessimistically: the stop active at
        # this bar's open preempts TP1/TP2 even when both extremes are touched.
        for symbol, row in current_rows:
            position = positions.get(symbol)
            if position is None:
                marks[symbol] = row["close"]
                continue
            position.bars_held += 1
            position.last_bar_ts = ts
            active_stop = position.active_stop
            stop_touched = (
                row["low"] <= active_stop
                if position.intent.side == "long"
                else row["high"] >= active_stop
            )
            if stop_touched:
                fill_price = (
                    min(row["open"], active_stop)
                    if position.intent.side == "long"
                    else max(row["open"], active_stop)
                )
                if _close_enough(active_stop, position.initial_stop):
                    reason = "initial_stop"
                elif _close_enough(active_stop, position.entry_price):
                    reason = "break_even_stop"
                else:
                    reason = "trailing_stop"
                close_slice(
                    position,
                    ts=ts,
                    price=fill_price,
                    quantity=position.remaining_quantity,
                    reason=reason,
                )
                marks[symbol] = row["close"]
                continue

            tp1_was_filled = position.tp1_filled
            tp1_touched = (
                row["high"] >= position.tp1_price
                if position.intent.side == "long"
                else row["low"] <= position.tp1_price
            )
            if not position.tp1_filled and tp1_touched:
                close_slice(
                    position,
                    ts=ts,
                    price=position.tp1_price,
                    quantity=position.original_quantity * policy.tp1_fraction,
                    reason="tp1",
                )
                if symbol in positions:
                    position.tp1_filled = True
                    position.tp1_fill_bar_ts = ts
                    position.bars_after_tp1 = 0
            if symbol not in positions:
                marks[symbol] = row["close"]
                continue
            tp2_touched = (
                row["high"] >= position.tp2_price
                if position.intent.side == "long"
                else row["low"] <= position.tp2_price
            )
            if position.tp1_filled and not position.tp2_filled and tp2_touched:
                close_slice(
                    position,
                    ts=ts,
                    price=position.tp2_price,
                    quantity=position.original_quantity * policy.tp2_fraction,
                    reason="tp2",
                )
                if symbol in positions:
                    position.tp2_filled = True
            if symbol not in positions:
                marks[symbol] = row["close"]
                continue

            if position.tp1_filled:
                favorable = row["high"] if position.intent.side == "long" else row["low"]
                if position.favorable_extreme is None:
                    position.favorable_extreme = favorable
                elif position.intent.side == "long":
                    position.favorable_extreme = max(position.favorable_extreme, favorable)
                else:
                    position.favorable_extreme = min(position.favorable_extreme, favorable)
                if position.intent.side == "long":
                    candidate_stop = max(
                        position.entry_price,
                        position.favorable_extreme * (1.0 - policy.trail_pct),
                    )
                    tighter = (
                        candidate_stop
                        > max(
                            position.active_stop,
                            position.pending_stop or -math.inf,
                        )
                        + 1e-12
                    )
                else:
                    candidate_stop = min(
                        position.entry_price,
                        position.favorable_extreme * (1.0 + policy.trail_pct),
                    )
                    tighter = (
                        candidate_stop
                        < min(
                            position.active_stop,
                            position.pending_stop or math.inf,
                        )
                        - 1e-12
                    )
                if tighter:
                    previous = position.pending_stop or position.active_stop
                    effective_ts = ts + bar_delta
                    position.pending_stop = candidate_stop
                    position.pending_stop_effective_ts = effective_ts
                    stop_ledgers.append(
                        StopTransitionLedger(
                            candidate_id=position.intent.candidate_id,
                            symbol=symbol,
                            side=position.intent.side,
                            calculated_ts=ts,
                            effective_ts=effective_ts,
                            previous_stop=previous,
                            new_stop=candidate_stop,
                            favorable_extreme=position.favorable_extreme,
                            reason="tp1_break_even_and_pct_trail",
                        )
                    )
                if tp1_was_filled and ts != position.tp1_fill_bar_ts:
                    position.bars_after_tp1 += 1
                    if (
                        position.bars_after_tp1 >= policy.runner_time_bars_after_tp1
                        and position.time_exit_due_ts is None
                    ):
                        position.time_exit_due_ts = ts + bar_delta
            marks[symbol] = row["close"]

        gross_unrealized, adjusted_unrealized, accrued_cost, current_nav = nav_components()
        curve.append(
            CurvePoint(
                ts=ts,
                wallet_balance=wallet,
                gross_unrealized_price_pnl=gross_unrealized,
                adjusted_unrealized_price_pnl=adjusted_unrealized,
                accrued_exit_cost=accrued_cost,
                nav=current_nav,
                open_position_count=len(positions),
            )
        )

    terminal: list[OpenPositionAccrual] = []
    cutoff_ts = curve[-1].ts if curve else min(row[0]["ts"] for row in bars.values())
    for symbol, position in sorted(positions.items()):
        mark = marks.get(symbol, position.entry_price)
        direction = 1.0 if position.intent.side == "long" else -1.0
        gross = direction * (mark - position.entry_price) * position.remaining_quantity
        multiplier, adjusted = _adjust_price_pnl(gross, scenario_model)
        accrued_cost = sum(
            _execution_components(mark * position.remaining_quantity, scenario_model)
        )
        terminal.append(
            OpenPositionAccrual(
                candidate_id=position.intent.candidate_id,
                symbol=symbol,
                side=position.intent.side,
                entry_ts=position.entry_ts,
                cutoff_ts=cutoff_ts,
                entry_price=position.entry_price,
                mark_price=mark,
                remaining_quantity=position.remaining_quantity,
                gross_unrealized_price_pnl=gross,
                payoff_multiplier=multiplier,
                adjusted_unrealized_price_pnl=adjusted,
                accrued_exit_cost=accrued_cost,
                accrued_nav_contribution=adjusted - accrued_cost,
            )
        )

    max_drawdown = 0.0
    running_peak = policy.initial_wallet
    for point in curve:
        running_peak = max(running_peak, point.nav)
        if running_peak > 0.0:
            max_drawdown = min(max_drawdown, point.nav / running_peak - 1.0)
    final_nav = curve[-1].nav if curve else wallet
    accrued_terminal = sum(item.accrued_exit_cost for item in terminal)
    return V15P2PortfolioResult(
        scenario=scenario_model.name,
        scenario_identity=scenario_identity,
        scenario_is_canonical=scenario_is_canonical,
        scenario_config=scenario_model,
        policy=policy,
        evaluation_start=evaluation_start,
        evaluation_end=evaluation_end,
        initial_wallet=policy.initial_wallet,
        final_wallet=wallet,
        final_nav=final_nav,
        max_drawdown=max_drawdown,
        total_execution_cost_charged=total_execution_cost,
        total_funding_cashflow=total_funding,
        accrued_terminal_exit_cost=accrued_terminal,
        entries=tuple(entry_ledgers),
        exit_fills=tuple(exit_ledgers),
        funding_events=tuple(funding_ledgers),
        journal_rows=tuple(journal_ledgers),
        stop_transitions=tuple(stop_ledgers),
        breaker_transitions=tuple(breaker_ledgers),
        risk_decisions=tuple(risk_ledgers),
        rejections=tuple(rejections),
        closed_episodes=tuple(episodes),
        curve=tuple(curve),
        terminal_positions=tuple(terminal),
    )


# Runner-facing alias; both names are intentionally explicit and side-effect free.
run_v15p2_engine = simulate_v15p2_portfolio


__all__ = [
    "B_SCENARIO",
    "C2_SCENARIO",
    "EXPECTED_CONFIG_SHA256",
    "FAIR_BASELINE_CANDIDATE_ID",
    "H_SCENARIO",
    "SCENARIOS",
    "STRATEGY_RANKS",
    "BreakerTransitionLedger",
    "ClosedEpisodeLedger",
    "CurvePoint",
    "EntryFillLedger",
    "ExitFillLedger",
    "FundingLedger",
    "JournalLedger",
    "OpenPositionAccrual",
    "RejectionLedger",
    "RiskDecisionLedger",
    "StopTransitionLedger",
    "V15P2CostScenario",
    "V15P2PortfolioPolicy",
    "V15P2PortfolioResult",
    "V15P2SignalIntentLike",
    "run_v15p2_engine",
    "simulate_v15p2_portfolio",
]
