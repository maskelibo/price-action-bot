"""Pure signal-selection adapter for the preregistered V18 challenger cells.

The module performs no file, database, network, clock, or strategy IO.  It
consumes the already generated, frozen V15.2 signal batch and applies only the
two V18 differences allowed by the preregistration:

* the exact enabled-strategy subset for each of the four cells; and
* for two cells, a causal SMA50 gate built from completed UTC calendar days.

The source V15.2 intent objects are returned unchanged.  ``cell_id`` lives on
the outer result and decision ledger so the inherited engine identity does not
need to be rewritten.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal, Protocol

import numpy as np
import pandas as pd

from price_action.lab.crypto_15m_v15p2_signals import (
    EXPECTED_CONFIG_SHA256,
    FAIR_BASELINE_CANDIDATE_ID,
    STRATEGY_ORDER,
    SignalGenerationResult,
)

V18CellId = Literal[
    "C1_VSA_ONLY",
    "C2_GRIMES_ONLY",
    "C3_DUAL_HTF50",
    "C4_VSA_HTF50",
]
V18DecisionOutcome = Literal["accepted", "rejected"]
V18DecisionReason = Literal[
    "accepted_no_htf",
    "accepted_htf_long",
    "accepted_htf_short",
    "strategy_disabled",
    "strategy_not_declared",
    "invalid_side",
    "missing_symbol_frame",
    "invalid_symbol_frame",
    "missing_required_utc_day",
    "incomplete_required_utc_day",
    "nonfinite_or_nonpositive_daily_close",
    "sma50_equality",
    "long_not_above_sma50",
    "short_not_below_sma50",
]

_BAR = pd.Timedelta(minutes=15)
_DAY = pd.Timedelta(days=1)
_BARS_PER_DAY = 96
_LOOKBACK_DAYS = 50
_VSA = "vsa_climax_test"
_GRIMES = "grimes_abc_pullback"


class _IntentLike(Protocol):
    candidate_id: str
    config_sha256: str
    decision_ts: datetime
    entry_ts: datetime
    symbol: str
    side: str
    strategy: str


class _BatchLike(Protocol):
    candidate_id: str
    config_sha256: str
    decisions: Sequence[Any]
    intents: Sequence[_IntentLike]


@dataclass(frozen=True, slots=True)
class V18CellSpec:
    """One of the four exact preregistered V18 cells."""

    cell_id: V18CellId
    enabled_strategies: tuple[str, ...]
    disabled_strategies: tuple[str, ...]
    htf50_gate: bool

    def __post_init__(self) -> None:
        enabled = tuple(self.enabled_strategies)
        disabled = tuple(self.disabled_strategies)
        if not enabled:
            raise ValueError("a V18 cell must enable at least one strategy")
        if set(enabled).intersection(disabled):
            raise ValueError("enabled and disabled strategies must be disjoint")
        if set((*enabled, *disabled)) != set(STRATEGY_ORDER):
            raise ValueError("a V18 cell must exhaust the frozen V15.2 strategies")
        if tuple(strategy for strategy in STRATEGY_ORDER if strategy in enabled) != enabled:
            raise ValueError("enabled strategies must retain frozen V15.2 order")
        if tuple(strategy for strategy in STRATEGY_ORDER if strategy in disabled) != disabled:
            raise ValueError("disabled strategies must retain frozen V15.2 order")
        object.__setattr__(self, "enabled_strategies", enabled)
        object.__setattr__(self, "disabled_strategies", disabled)


V18_CELL_SPECS: tuple[V18CellSpec, ...] = (
    V18CellSpec(
        cell_id="C1_VSA_ONLY",
        enabled_strategies=(_VSA,),
        disabled_strategies=(_GRIMES,),
        htf50_gate=False,
    ),
    V18CellSpec(
        cell_id="C2_GRIMES_ONLY",
        enabled_strategies=(_GRIMES,),
        disabled_strategies=(_VSA,),
        htf50_gate=False,
    ),
    V18CellSpec(
        cell_id="C3_DUAL_HTF50",
        enabled_strategies=(_VSA, _GRIMES),
        disabled_strategies=(),
        htf50_gate=True,
    ),
    V18CellSpec(
        cell_id="C4_VSA_HTF50",
        enabled_strategies=(_VSA,),
        disabled_strategies=(_GRIMES,),
        htf50_gate=True,
    ),
)
V18_CELL_SPEC_BY_ID: Mapping[str, V18CellSpec] = {spec.cell_id: spec for spec in V18_CELL_SPECS}


@dataclass(frozen=True, slots=True)
class V18CellDecisionLedger:
    """Exactly one strategy/HTF decision for one source V15.2 intent."""

    cell_id: V18CellId
    source_intent_index: int
    source_candidate_id: str
    decision_ts: datetime
    entry_ts: datetime
    symbol: str
    side: str
    strategy: str
    htf50_gate: bool
    outcome: V18DecisionOutcome
    reason: V18DecisionReason
    required_window_start_day: datetime | None
    required_window_end_day: datetime | None
    required_day_count: int
    complete_day_count: int
    failed_day: datetime | None
    latest_completed_daily_close: float | None
    sma50: float | None

    def __post_init__(self) -> None:
        if isinstance(self.source_intent_index, bool) or self.source_intent_index < 0:
            raise ValueError("source_intent_index must be an integer >= 0")
        if self.outcome not in {"accepted", "rejected"}:
            raise ValueError("outcome must be accepted or rejected")
        accepted_reason = self.reason.startswith("accepted_")
        if (self.outcome == "accepted") != accepted_reason:
            raise ValueError("accepted outcome and reason must agree")
        if self.required_day_count != _LOOKBACK_DAYS:
            raise ValueError("required_day_count must remain 50")
        if not 0 <= self.complete_day_count <= self.required_day_count:
            raise ValueError("complete_day_count is outside the required window")
        for name in ("decision_ts", "entry_ts"):
            value = getattr(self, name)
            if value.tzinfo is None or value.utcoffset() != timedelta(0):
                raise ValueError(f"{name} must be timezone-aware UTC")
        if self.entry_ts - self.decision_ts != timedelta(minutes=15):
            raise ValueError("entry_ts must be the next exact 15-minute label")
        for name in (
            "required_window_start_day",
            "required_window_end_day",
            "failed_day",
        ):
            value = getattr(self, name)
            if value is not None and (value.tzinfo is None or value.utcoffset() != timedelta(0)):
                raise ValueError(f"{name} must be timezone-aware UTC")
        for name in ("latest_completed_daily_close", "sma50"):
            value = getattr(self, name)
            if value is not None and (not math.isfinite(value) or value <= 0.0):
                raise ValueError(f"{name} must be finite and positive when present")


@dataclass(frozen=True, slots=True)
class V18CellSignalResult:
    """A cell's ordered intent stream and its exhaustive adapter ledger."""

    candidate_id: V18CellId
    enabled_strategies: tuple[str, ...]
    disabled_strategies: tuple[str, ...]
    htf50_gate: bool
    source_candidate_id: str
    source_config_sha256: str
    source_raw_decision_count: int
    source_intent_count: int
    decisions: tuple[V18CellDecisionLedger, ...]
    intents: tuple[_IntentLike, ...]

    def __post_init__(self) -> None:
        decisions = tuple(self.decisions)
        intents = tuple(self.intents)
        object.__setattr__(self, "decisions", decisions)
        object.__setattr__(self, "intents", intents)
        if len(decisions) != self.source_intent_count:
            raise ValueError("cell ledger must contain exactly one row per source intent")
        if tuple(row.source_intent_index for row in decisions) != tuple(
            range(self.source_intent_count)
        ):
            raise ValueError("cell ledger source indexes must be contiguous")
        if any(row.cell_id != self.candidate_id for row in decisions):
            raise ValueError("cell ledger contains a foreign cell_id")
        accepted_indexes = [
            row.source_intent_index for row in decisions if row.outcome == "accepted"
        ]
        if len(accepted_indexes) != len(intents):
            raise ValueError("accepted ledger count does not reconcile to intents")

    @property
    def rejections(self) -> tuple[V18CellDecisionLedger, ...]:
        return tuple(row for row in self.decisions if row.outcome == "rejected")

    @property
    def cell_id(self) -> V18CellId:
        """Descriptive alias for the serialized outer candidate identity."""

        return self.candidate_id

    @property
    def accepted_count(self) -> int:
        return len(self.intents)

    @property
    def rejected_count(self) -> int:
        return len(self.rejections)


@dataclass(frozen=True, slots=True)
class _DailyState:
    status: Literal["complete", "incomplete", "invalid_close"]
    close: float | None


@dataclass(frozen=True, slots=True)
class _SymbolDailyHistory:
    states: Mapping[pd.Timestamp, _DailyState]
    error_reason: V18DecisionReason | None = None


def _utc_timestamp(value: Any, *, label: str) -> pd.Timestamp:
    try:
        stamp = pd.Timestamp(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} is not a timestamp") from exc
    if stamp.tzinfo is None or stamp.utcoffset() != pd.Timedelta(0):
        raise ValueError(f"{label} must be timezone-aware UTC")
    return stamp.tz_convert(UTC)


def _daily_history(frame: Any) -> _SymbolDailyHistory:
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        return _SymbolDailyHistory({}, "missing_symbol_frame")
    if "close" not in frame.columns:
        return _SymbolDailyHistory({}, "invalid_symbol_frame")
    raw_timestamps = frame["ts"] if "ts" in frame.columns else frame.index
    try:
        timestamps = pd.DatetimeIndex(raw_timestamps)
    except (TypeError, ValueError):
        return _SymbolDailyHistory({}, "invalid_symbol_frame")
    if timestamps.tz is None or timestamps.hasnans:
        return _SymbolDailyHistory({}, "invalid_symbol_frame")
    timestamps = timestamps.tz_convert(UTC)
    numeric_close = pd.to_numeric(frame["close"], errors="coerce").to_numpy(dtype=float)
    normalized = pd.DataFrame({"ts": timestamps, "close": numeric_close})
    normalized["day"] = normalized["ts"].dt.floor("D")

    states: dict[pd.Timestamp, _DailyState] = {}
    for raw_day, group in normalized.groupby("day", sort=True):
        day = pd.Timestamp(raw_day)
        ordered = group.sort_values("ts", kind="stable")
        actual = pd.DatetimeIndex(ordered["ts"])
        expected = pd.date_range(day, periods=_BARS_PER_DAY, freq=_BAR)
        if len(actual) != _BARS_PER_DAY or not actual.equals(expected):
            states[day] = _DailyState("incomplete", None)
            continue
        close = float(ordered.iloc[-1]["close"])
        if not math.isfinite(close) or close <= 0.0:
            states[day] = _DailyState("invalid_close", None)
            continue
        states[day] = _DailyState("complete", close)
    return _SymbolDailyHistory(states)


def _base_ledger(
    *,
    spec: V18CellSpec,
    source_index: int,
    intent: _IntentLike,
    outcome: V18DecisionOutcome,
    reason: V18DecisionReason,
    window_start: pd.Timestamp | None = None,
    window_end: pd.Timestamp | None = None,
    complete_days: int = 0,
    failed_day: pd.Timestamp | None = None,
    latest_close: float | None = None,
    sma50: float | None = None,
) -> V18CellDecisionLedger:
    decision_ts = _utc_timestamp(intent.decision_ts, label="intent.decision_ts")
    entry_ts = _utc_timestamp(intent.entry_ts, label="intent.entry_ts")
    return V18CellDecisionLedger(
        cell_id=spec.cell_id,
        source_intent_index=source_index,
        source_candidate_id=str(intent.candidate_id),
        decision_ts=decision_ts.to_pydatetime(),
        entry_ts=entry_ts.to_pydatetime(),
        symbol=str(intent.symbol),
        side=str(intent.side).lower(),
        strategy=str(intent.strategy),
        htf50_gate=spec.htf50_gate,
        outcome=outcome,
        reason=reason,
        required_window_start_day=(None if window_start is None else window_start.to_pydatetime()),
        required_window_end_day=None if window_end is None else window_end.to_pydatetime(),
        required_day_count=_LOOKBACK_DAYS,
        complete_day_count=complete_days,
        failed_day=None if failed_day is None else failed_day.to_pydatetime(),
        latest_completed_daily_close=latest_close,
        sma50=sma50,
    )


def _evaluate_intent(
    intent: _IntentLike,
    *,
    source_index: int,
    spec: V18CellSpec,
    frames: Mapping[str, pd.DataFrame] | None,
    history_cache: dict[str, _SymbolDailyHistory],
) -> V18CellDecisionLedger:
    strategy = str(intent.strategy)
    side = str(intent.side).strip().lower()
    if strategy not in STRATEGY_ORDER:
        return _base_ledger(
            spec=spec,
            source_index=source_index,
            intent=intent,
            outcome="rejected",
            reason="strategy_not_declared",
        )
    if strategy not in spec.enabled_strategies:
        return _base_ledger(
            spec=spec,
            source_index=source_index,
            intent=intent,
            outcome="rejected",
            reason="strategy_disabled",
        )
    if side not in {"long", "short"}:
        return _base_ledger(
            spec=spec,
            source_index=source_index,
            intent=intent,
            outcome="rejected",
            reason="invalid_side",
        )
    if not spec.htf50_gate:
        return _base_ledger(
            spec=spec,
            source_index=source_index,
            intent=intent,
            outcome="accepted",
            reason="accepted_no_htf",
        )

    decision_ts = _utc_timestamp(intent.decision_ts, label="intent.decision_ts")
    decision_day = decision_ts.floor("D")
    window_start = decision_day - _LOOKBACK_DAYS * _DAY
    window_end = decision_day - _DAY
    symbol = str(intent.symbol)
    if symbol not in history_cache:
        raw_frame = None if frames is None else frames.get(symbol)
        history_cache[symbol] = _daily_history(raw_frame)
    history = history_cache[symbol]
    if history.error_reason is not None:
        return _base_ledger(
            spec=spec,
            source_index=source_index,
            intent=intent,
            outcome="rejected",
            reason=history.error_reason,
            window_start=window_start,
            window_end=window_end,
        )

    required_days = tuple(pd.date_range(window_start, window_end, freq="D"))
    states = tuple(history.states.get(day) for day in required_days)
    complete_days = sum(state is not None and state.status == "complete" for state in states)
    for day, state in zip(required_days, states, strict=True):
        if state is None:
            return _base_ledger(
                spec=spec,
                source_index=source_index,
                intent=intent,
                outcome="rejected",
                reason="missing_required_utc_day",
                window_start=window_start,
                window_end=window_end,
                complete_days=complete_days,
                failed_day=day,
            )
        if state.status == "incomplete":
            return _base_ledger(
                spec=spec,
                source_index=source_index,
                intent=intent,
                outcome="rejected",
                reason="incomplete_required_utc_day",
                window_start=window_start,
                window_end=window_end,
                complete_days=complete_days,
                failed_day=day,
            )
        if state.status == "invalid_close":
            return _base_ledger(
                spec=spec,
                source_index=source_index,
                intent=intent,
                outcome="rejected",
                reason="nonfinite_or_nonpositive_daily_close",
                window_start=window_start,
                window_end=window_end,
                complete_days=complete_days,
                failed_day=day,
            )

    closes = tuple(float(state.close) for state in states if state is not None)
    if len(closes) != _LOOKBACK_DAYS or not np.isfinite(closes).all():
        raise AssertionError("complete daily-state invariant failed")
    latest_close = closes[-1]
    sma50 = math.fsum(closes) / _LOOKBACK_DAYS
    common = {
        "spec": spec,
        "source_index": source_index,
        "intent": intent,
        "window_start": window_start,
        "window_end": window_end,
        "complete_days": _LOOKBACK_DAYS,
        "latest_close": latest_close,
        "sma50": sma50,
    }
    if latest_close == sma50:
        return _base_ledger(
            **common,
            outcome="rejected",
            reason="sma50_equality",
        )
    if side == "long":
        if latest_close > sma50:
            return _base_ledger(
                **common,
                outcome="accepted",
                reason="accepted_htf_long",
            )
        return _base_ledger(
            **common,
            outcome="rejected",
            reason="long_not_above_sma50",
        )
    if latest_close < sma50:
        return _base_ledger(
            **common,
            outcome="accepted",
            reason="accepted_htf_short",
        )
    return _base_ledger(
        **common,
        outcome="rejected",
        reason="short_not_below_sma50",
    )


def _validate_batch(batch: _BatchLike) -> tuple[_IntentLike, ...]:
    if str(batch.candidate_id) != FAIR_BASELINE_CANDIDATE_ID:
        raise ValueError("source batch does not identify the frozen V15.2 baseline")
    if str(batch.config_sha256).lower() != EXPECTED_CONFIG_SHA256:
        raise ValueError("source batch config SHA-256 drifted")
    intents = tuple(batch.intents)
    for index, intent in enumerate(intents):
        if str(intent.candidate_id) != FAIR_BASELINE_CANDIDATE_ID:
            raise ValueError(f"source intent {index} has a foreign candidate_id")
        if str(intent.config_sha256).lower() != EXPECTED_CONFIG_SHA256:
            raise ValueError(f"source intent {index} config SHA-256 drifted")
    return intents


def evaluate_v18_cell(
    batch: SignalGenerationResult | _BatchLike,
    frames: Mapping[str, pd.DataFrame] | None,
    *,
    cell: V18CellSpec | V18CellId,
    _history_cache: dict[str, _SymbolDailyHistory] | None = None,
) -> V18CellSignalResult:
    """Apply one exact V18 cell to a frozen V15.2 signal batch.

    No-HTF cells never inspect ``frames``.  HTF cells fail closed, with one
    ledger row per source intent, when the required symbol/day evidence is
    missing or incomplete.
    """

    spec = V18_CELL_SPEC_BY_ID[cell] if isinstance(cell, str) else cell
    intents = _validate_batch(batch)
    cache = {} if _history_cache is None else _history_cache
    decisions = tuple(
        _evaluate_intent(
            intent,
            source_index=index,
            spec=spec,
            frames=frames,
            history_cache=cache,
        )
        for index, intent in enumerate(intents)
    )
    accepted = tuple(
        intents[row.source_intent_index] for row in decisions if row.outcome == "accepted"
    )
    return V18CellSignalResult(
        candidate_id=spec.cell_id,
        enabled_strategies=spec.enabled_strategies,
        disabled_strategies=spec.disabled_strategies,
        htf50_gate=spec.htf50_gate,
        source_candidate_id=str(batch.candidate_id),
        source_config_sha256=str(batch.config_sha256).lower(),
        source_raw_decision_count=len(tuple(batch.decisions)),
        source_intent_count=len(intents),
        decisions=decisions,
        intents=accepted,
    )


def adapt_v15p2_signal_batch_to_v18_cells(
    batch: SignalGenerationResult | _BatchLike,
    frames: Mapping[str, pd.DataFrame] | None,
) -> dict[str, V18CellSignalResult]:
    """Return all four cells in preregistered order from one source batch."""

    cache: dict[str, _SymbolDailyHistory] = {}
    return {
        spec.cell_id: evaluate_v18_cell(
            batch,
            frames,
            cell=spec,
            _history_cache=cache,
        )
        for spec in V18_CELL_SPECS
    }


def generate_v18_candidate_batches(
    frames: Mapping[str, pd.DataFrame] | None,
    *,
    baseline_batch: SignalGenerationResult | _BatchLike,
) -> dict[str, V18CellSignalResult]:
    """Runner-facing canonical wrapper around the pure four-cell adapter."""

    return adapt_v15p2_signal_batch_to_v18_cells(baseline_batch, frames)


__all__ = [
    "V18_CELL_SPECS",
    "V18_CELL_SPEC_BY_ID",
    "V18CellDecisionLedger",
    "V18CellId",
    "V18CellSignalResult",
    "V18CellSpec",
    "adapt_v15p2_signal_batch_to_v18_cells",
    "evaluate_v18_cell",
    "generate_v18_candidate_batches",
]
