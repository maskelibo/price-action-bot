"""Causal signal adapter for the frozen v15p2 fair-baseline replay.

The adapter deliberately reuses the two classes used by the live 15-minute
scanner.  OHLCV timestamps are UTC bar-open labels: a signal on the completed
bar labelled ``decision_ts`` may enter only at ``decision_ts + 15 minutes``,
using that exactly-contiguous bar's open.

Signal generation is pure once :class:`V15P2SignalPolicy` has been loaded:
callers provide independent per-symbol frames, and the generator performs no
database, network, random-number, or wall-clock IO.  Frames are never globally
intersected or forward-filled.  Every non-15-minute timestamp jump starts a
new block and rebuilds the live scanner's 500-bar warm-up.

This remains a ``FAIR_LIVE_POLICY_PROXY``, not an exact fill replay.  Entry is
the next bar open rather than the live post-only queue / 30-second fallback.
"""

from __future__ import annotations

import hashlib
import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal, Protocol

import numpy as np
import pandas as pd
import yaml

from price_action.contracts import Signal
from price_action.strategies.base import Strategy, StrategyManifest
from price_action.strategies.grimes_abc_pullback import (
    GrimesABCPullbackStrategy,
)
from price_action.strategies.grimes_abc_pullback import (
    _default_manifest as _grimes_default_manifest,
)
from price_action.strategies.vsa_climax_test import (
    VSAClimaxTestStrategy,
)
from price_action.strategies.vsa_climax_test import (
    _default_manifest as _vsa_default_manifest,
)

Side = Literal["long", "short"]
SignalDecisionOutcome = Literal["accepted", "rejected"]
SignalDecisionReason = Literal[
    "accepted",
    "confidence_below_minimum",
    "decision_stop_distance_below_minimum",
    "missing_next_bar",
    "duplicate_signal_fingerprint",
]

FAIR_BASELINE_CANDIDATE_ID = "v15p2_fair_baseline"
STRATEGY_ORDER = ("vsa_climax_test", "grimes_abc_pullback")
WARMUP_BARS = 500
CONFIDENCE_MIN = 0.25
STOP_DISTANCE_PCT_MIN = 0.025
EXPECTED_CONFIG_SHA256 = "78025a394aecb807c32aeba737823bd565f0f19e72ec133352d63f697036ea82"
EXPECTED_SIGNAL_MANIFEST_HASHES = {
    "vsa_climax_test": "ebddc62d495cc790",
    "grimes_abc_pullback": "33653e0c52e34338",
}

_REPO_ROOT = Path(__file__).resolve().parents[3]
CANONICAL_CONFIG_PATH = _REPO_ROOT / "configs" / "risk_phoenix_scalp_15m_v15p2.yaml"
_BAR = pd.Timedelta(minutes=15)
_OHLCV = ("open", "high", "low", "close", "volume")


def _finite(name: str, value: float, *, positive: bool = False) -> float:
    parsed = float(value)
    if not math.isfinite(parsed) or (positive and parsed <= 0.0):
        qualifier = "finite and > 0" if positive else "finite"
        raise ValueError(f"{name} must be {qualifier}")
    return parsed


def _utc(name: str, value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware UTC")
    if value.utcoffset() != timedelta(0):
        raise ValueError(f"{name} must be UTC")
    return value.astimezone(UTC)


@dataclass(frozen=True, slots=True)
class V15P2SignalPolicy:
    """Frozen signal-layer values parsed from the canonical live config."""

    candidate_id: str
    strategy_order: tuple[str, ...]
    confidence_min: float
    stop_distance_pct_min: float
    warmup_bars: int
    timeframe: str
    config_sha256: str

    def __post_init__(self) -> None:
        if self.candidate_id != FAIR_BASELINE_CANDIDATE_ID:
            raise ValueError("candidate_id does not identify the frozen v15p2 baseline")
        if tuple(self.strategy_order) != STRATEGY_ORDER:
            raise ValueError("v15p2 strategy order must be VSA then Grimes")
        object.__setattr__(self, "strategy_order", tuple(self.strategy_order))
        confidence = _finite("confidence_min", self.confidence_min)
        stop_distance = _finite("stop_distance_pct_min", self.stop_distance_pct_min, positive=True)
        if not math.isclose(confidence, CONFIDENCE_MIN, rel_tol=0.0, abs_tol=1e-12):
            raise ValueError(f"v15p2 confidence_min must remain {CONFIDENCE_MIN}")
        if not math.isclose(stop_distance, STOP_DISTANCE_PCT_MIN, rel_tol=0.0, abs_tol=1e-12):
            raise ValueError(f"v15p2 stop_distance_pct_min must remain {STOP_DISTANCE_PCT_MIN}")
        if isinstance(self.warmup_bars, bool) or int(self.warmup_bars) != WARMUP_BARS:
            raise ValueError(f"v15p2 warmup_bars must remain {WARMUP_BARS}")
        if self.timeframe != "15m":
            raise ValueError("v15p2 timeframe must remain 15m")
        digest = str(self.config_sha256).lower()
        if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
            raise ValueError("config_sha256 must be a lowercase SHA-256 digest")
        object.__setattr__(self, "confidence_min", confidence)
        object.__setattr__(self, "stop_distance_pct_min", stop_distance)
        object.__setattr__(self, "warmup_bars", int(self.warmup_bars))
        object.__setattr__(self, "config_sha256", digest)


@dataclass(frozen=True, slots=True)
class V15P2SignalIntent:
    """One eligible v15p2 signal with its causal next-open execution proxy."""

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

    def __post_init__(self) -> None:
        if self.candidate_id != FAIR_BASELINE_CANDIDATE_ID:
            raise ValueError("intent candidate_id does not identify the v15p2 baseline")
        object.__setattr__(self, "decision_ts", _utc("decision_ts", self.decision_ts))
        object.__setattr__(self, "entry_ts", _utc("entry_ts", self.entry_ts))
        if self.entry_ts - self.decision_ts != timedelta(minutes=15):
            raise ValueError("entry_ts must be the next exact 15-minute bar open")
        if not self.symbol:
            raise ValueError("symbol must be non-empty")
        if self.side not in {"long", "short"}:
            raise ValueError("side must be long or short")
        if self.strategy not in STRATEGY_ORDER:
            raise ValueError("strategy is not part of the v15p2 baseline")
        expected_rank = STRATEGY_ORDER.index(self.strategy)
        if isinstance(self.strategy_rank, bool) or int(self.strategy_rank) != expected_rank:
            raise ValueError("strategy_rank must match the frozen VSA-then-Grimes order")
        if not self.pattern_id:
            raise ValueError("pattern_id must be non-empty")
        for name in (
            "decision_close",
            "entry_reference_price",
            "entry_price",
            "stop_price",
            "take_profit_price",
            "decision_stop_distance_pct",
            "suggested_size_atr",
        ):
            object.__setattr__(self, name, _finite(name, getattr(self, name), positive=True))
        entry_distance = _finite("entry_stop_distance_pct", self.entry_stop_distance_pct)
        if entry_distance < 0.0:
            raise ValueError("entry_stop_distance_pct must be >= 0")
        object.__setattr__(self, "entry_stop_distance_pct", entry_distance)
        score = _finite("confluence_score", self.confluence_score)
        if score < CONFIDENCE_MIN:
            raise ValueError("intent confluence_score is below the v15p2 gate")
        if not math.isclose(
            self.entry_reference_price, self.decision_close, rel_tol=0.0, abs_tol=0.0
        ):
            raise ValueError("entry_reference_price must match the live scanner decision close")
        expected_decision_distance = (
            abs(self.decision_close - self.stop_price) / self.decision_close
        )
        if not math.isclose(
            self.decision_stop_distance_pct,
            expected_decision_distance,
            rel_tol=1e-12,
            abs_tol=1e-12,
        ):
            raise ValueError(
                "decision_stop_distance_pct does not match decision close and stop price"
            )
        expected_entry_distance = abs(self.entry_price - self.stop_price) / self.entry_price
        if not math.isclose(
            self.entry_stop_distance_pct,
            expected_entry_distance,
            rel_tol=1e-12,
            abs_tol=1e-12,
        ):
            raise ValueError("entry_stop_distance_pct does not match entry and stop prices")
        if self.decision_stop_distance_pct < STOP_DISTANCE_PCT_MIN:
            raise ValueError("intent stop distance is below the v15p2 gate")
        if not str(self.signal_manifest_hash).strip():
            raise ValueError("signal_manifest_hash must be non-empty")
        digest = str(self.config_sha256).lower()
        if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
            raise ValueError("config_sha256 must be a lowercase SHA-256 digest")
        object.__setattr__(self, "strategy_rank", int(self.strategy_rank))
        object.__setattr__(self, "confluence_score", score)
        object.__setattr__(self, "config_sha256", digest)


@dataclass(frozen=True, slots=True)
class SignalDecisionLedger:
    """Audit row for every exact rolling-window raw strategy emission."""

    emission_index: int
    candidate_id: str
    decision_ts: datetime
    entry_ts: datetime | None
    symbol: str
    side: Side
    strategy: str
    strategy_rank: int
    pattern_id: str
    confluence_score: float
    decision_close: float
    entry_reference_price: float
    entry_price: float | None
    stop_price: float
    take_profit_price: float
    decision_stop_distance_pct: float
    entry_stop_distance_pct: float | None
    suggested_size_atr: float
    signal_manifest_hash: str
    config_sha256: str
    outcome: SignalDecisionOutcome
    reason: SignalDecisionReason

    def __post_init__(self) -> None:
        if isinstance(self.emission_index, bool) or int(self.emission_index) < 0:
            raise ValueError("emission_index must be an integer >= 0")
        object.__setattr__(self, "emission_index", int(self.emission_index))
        object.__setattr__(self, "decision_ts", _utc("decision_ts", self.decision_ts))
        if self.entry_ts is not None:
            object.__setattr__(self, "entry_ts", _utc("entry_ts", self.entry_ts))
            if self.entry_ts - self.decision_ts != timedelta(minutes=15):
                raise ValueError("ledger entry_ts must be the next exact 15-minute bar")
        if self.candidate_id != FAIR_BASELINE_CANDIDATE_ID:
            raise ValueError("ledger candidate_id does not identify the v15p2 baseline")
        if not self.symbol or not self.pattern_id:
            raise ValueError("ledger symbol and pattern_id must be non-empty")
        if self.side not in {"long", "short"}:
            raise ValueError("ledger side must be long or short")
        if self.strategy not in STRATEGY_ORDER:
            raise ValueError("ledger strategy is not part of the v15p2 baseline")
        expected_rank = STRATEGY_ORDER.index(self.strategy)
        if int(self.strategy_rank) != expected_rank:
            raise ValueError("ledger strategy_rank does not match the frozen strategy order")
        object.__setattr__(self, "strategy_rank", int(self.strategy_rank))
        score = _finite("confluence_score", self.confluence_score)
        object.__setattr__(self, "confluence_score", score)
        for name in (
            "decision_close",
            "entry_reference_price",
            "stop_price",
            "take_profit_price",
            "suggested_size_atr",
        ):
            object.__setattr__(self, name, _finite(name, getattr(self, name), positive=True))
        decision_distance = _finite("decision_stop_distance_pct", self.decision_stop_distance_pct)
        if decision_distance < 0.0:
            raise ValueError("decision_stop_distance_pct must be >= 0")
        object.__setattr__(self, "decision_stop_distance_pct", decision_distance)
        if self.entry_price is not None:
            object.__setattr__(
                self, "entry_price", _finite("entry_price", self.entry_price, positive=True)
            )
        if self.entry_stop_distance_pct is not None:
            entry_distance = _finite("entry_stop_distance_pct", self.entry_stop_distance_pct)
            if entry_distance < 0.0:
                raise ValueError("entry_stop_distance_pct must be >= 0")
            object.__setattr__(self, "entry_stop_distance_pct", entry_distance)
        if self.entry_reference_price != self.decision_close:
            raise ValueError("ledger entry_reference_price must equal decision_close")
        expected_decision_distance = (
            abs(self.decision_close - self.stop_price) / self.decision_close
        )
        if not math.isclose(
            self.decision_stop_distance_pct,
            expected_decision_distance,
            rel_tol=1e-12,
            abs_tol=1e-12,
        ):
            raise ValueError("ledger decision stop distance is inconsistent")
        if self.entry_price is None:
            if self.entry_ts is not None or self.entry_stop_distance_pct is not None:
                raise ValueError("missing entry price requires null entry fields")
        else:
            if self.entry_ts is None or self.entry_stop_distance_pct is None:
                raise ValueError("available entry price requires complete entry fields")
            expected_entry_distance = abs(self.entry_price - self.stop_price) / self.entry_price
            if not math.isclose(
                self.entry_stop_distance_pct,
                expected_entry_distance,
                rel_tol=1e-12,
                abs_tol=1e-12,
            ):
                raise ValueError("ledger entry stop distance is inconsistent")
        if self.outcome not in {"accepted", "rejected"}:
            raise ValueError("ledger outcome must be accepted or rejected")
        valid_reasons = {
            "accepted",
            "confidence_below_minimum",
            "decision_stop_distance_below_minimum",
            "missing_next_bar",
            "duplicate_signal_fingerprint",
        }
        if self.reason not in valid_reasons:
            raise ValueError("ledger reason is not part of the frozen signal taxonomy")
        if (self.outcome == "accepted") != (self.reason == "accepted"):
            raise ValueError("accepted outcome and reason must agree")
        if score < CONFIDENCE_MIN:
            expected_reason: SignalDecisionReason = "confidence_below_minimum"
        elif decision_distance < STOP_DISTANCE_PCT_MIN:
            expected_reason = "decision_stop_distance_below_minimum"
        elif self.entry_ts is None:
            expected_reason = "missing_next_bar"
        else:
            expected_reason = "accepted"
        if self.reason == "duplicate_signal_fingerprint":
            if expected_reason != "accepted":
                raise ValueError("duplicate rejection requires an otherwise accepted emission")
        elif self.reason != expected_reason:
            raise ValueError("ledger reason does not match the frozen signal gate order")
        if not str(self.signal_manifest_hash).strip():
            raise ValueError("ledger signal_manifest_hash must be non-empty")
        digest = str(self.config_sha256).lower()
        if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
            raise ValueError("ledger config_sha256 must be a lowercase SHA-256 digest")
        object.__setattr__(self, "config_sha256", digest)


def _decision_fingerprint(decision: SignalDecisionLedger) -> tuple[object, ...]:
    return (
        decision.decision_ts,
        decision.entry_ts,
        decision.symbol,
        decision.strategy,
        decision.side,
        decision.pattern_id,
        decision.stop_price,
        decision.take_profit_price,
        decision.signal_manifest_hash,
    )


def _intent_fingerprint(intent: V15P2SignalIntent) -> tuple[object, ...]:
    return (
        intent.decision_ts,
        intent.entry_ts,
        intent.symbol,
        intent.strategy,
        intent.side,
        intent.pattern_id,
        intent.stop_price,
        intent.take_profit_price,
        intent.signal_manifest_hash,
    )


@dataclass(frozen=True, slots=True)
class SignalGenerationResult:
    """Frozen signal audit batch whose accepted rows exactly equal its intents."""

    candidate_id: str
    config_sha256: str
    decisions: tuple[SignalDecisionLedger, ...]
    intents: tuple[V15P2SignalIntent, ...]

    def __post_init__(self) -> None:
        if self.candidate_id != FAIR_BASELINE_CANDIDATE_ID:
            raise ValueError("batch candidate_id does not identify the v15p2 baseline")
        digest = str(self.config_sha256).lower()
        if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
            raise ValueError("batch config_sha256 must be a lowercase SHA-256 digest")
        object.__setattr__(self, "config_sha256", digest)
        object.__setattr__(self, "decisions", tuple(self.decisions))
        object.__setattr__(self, "intents", tuple(self.intents))
        if tuple(decision.emission_index for decision in self.decisions) != tuple(
            range(len(self.decisions))
        ):
            raise ValueError("batch decision emission indexes must be contiguous")
        if any(
            decision.candidate_id != self.candidate_id
            or decision.config_sha256 != self.config_sha256
            for decision in self.decisions
        ) or any(
            intent.candidate_id != self.candidate_id or intent.config_sha256 != self.config_sha256
            for intent in self.intents
        ):
            raise ValueError("batch rows do not share its frozen identity")
        accepted = tuple(
            _decision_fingerprint(decision)
            for decision in self.decisions
            if decision.outcome == "accepted"
        )
        intent_fingerprints = tuple(_intent_fingerprint(intent) for intent in self.intents)
        if accepted != intent_fingerprints:
            raise ValueError("accepted signal ledger rows do not reconcile exactly to intents")

    @property
    def raw_emission_count(self) -> int:
        return len(self.decisions)

    @property
    def accepted_count(self) -> int:
        return len(self.intents)

    @property
    def rejected_count(self) -> int:
        return self.raw_emission_count - self.accepted_count


def load_current_v15p2_signal_policy(
    path: str | Path = CANONICAL_CONFIG_PATH,
    *,
    expected_sha256: str | None = EXPECTED_CONFIG_SHA256,
) -> V15P2SignalPolicy:
    """Load and fail-closed validate the audited v15p2 signal configuration.

    ``expected_sha256=None`` exists only for schema-focused tests and explicit
    audits.  Evidence replay must use the frozen default digest.
    """

    config_path = Path(path)
    try:
        raw_bytes = config_path.read_bytes()
    except OSError as exc:
        raise ValueError(f"cannot read v15p2 config: {config_path}") from exc
    digest = hashlib.sha256(raw_bytes).hexdigest()
    if expected_sha256 is not None and digest != str(expected_sha256).lower():
        raise ValueError("canonical v15p2 config SHA-256 does not match the frozen baseline")
    try:
        raw = yaml.safe_load(raw_bytes)
    except yaml.YAMLError as exc:
        raise ValueError("v15p2 config is not valid YAML") from exc
    if not isinstance(raw, dict):
        raise ValueError("v15p2 config must be a mapping")

    strategy_order = raw.get("strategies_enabled")
    execution = raw.get("execution")
    portfolio = raw.get("strategy_portfolio")
    defaults = raw.get("defaults")
    if not isinstance(strategy_order, list):
        raise ValueError("v15p2 strategies_enabled must be a list")
    if not isinstance(execution, dict) or not isinstance(portfolio, dict):
        raise ValueError("v15p2 execution and strategy_portfolio mappings are required")
    if not isinstance(defaults, dict):
        raise ValueError("v15p2 defaults mapping is required")
    if portfolio.get("enabled") is not True:
        raise ValueError("v15p2 strategy_portfolio must be enabled")

    return V15P2SignalPolicy(
        candidate_id=FAIR_BASELINE_CANDIDATE_ID,
        strategy_order=tuple(str(value) for value in strategy_order),
        confidence_min=float(portfolio.get("signal_confidence_min", math.nan)),
        stop_distance_pct_min=float(execution.get("sl_pct_min", math.nan)),
        warmup_bars=WARMUP_BARS,
        timeframe=str(defaults.get("timeframe", "")),
        config_sha256=digest,
    )


class _StrategyLike(Protocol):
    name: str
    manifest: StrategyManifest

    def prepare_features(self, df: pd.DataFrame) -> pd.DataFrame: ...

    def generate_signals(self, df: pd.DataFrame) -> list[Signal]: ...


@dataclass(frozen=True, slots=True)
class _StrategySpec:
    name: str
    strategy_type: type[Strategy]
    manifest_factory: Callable[[], StrategyManifest]
    rolling_mode: Literal["bruteforce", "vsa_bounded", "grimes_candidates"] = "bruteforce"
    expected_manifest_hash: str | None = None


def _strategy_specs() -> tuple[_StrategySpec, ...]:
    """Return the actual live scanner classes in its exact configured order."""

    return (
        _StrategySpec(
            "vsa_climax_test",
            VSAClimaxTestStrategy,
            _vsa_default_manifest,
            "vsa_bounded",
            EXPECTED_SIGNAL_MANIFEST_HASHES["vsa_climax_test"],
        ),
        _StrategySpec(
            "grimes_abc_pullback",
            GrimesABCPullbackStrategy,
            _grimes_default_manifest,
            "grimes_candidates",
            EXPECTED_SIGNAL_MANIFEST_HASHES["grimes_abc_pullback"],
        ),
    )


def _normalize_symbol_frame(symbol: str, frame: pd.DataFrame) -> pd.DataFrame:
    if not isinstance(symbol, str) or not symbol.strip():
        raise ValueError("frame symbols must be non-empty strings")
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        raise ValueError(f"{symbol}: OHLCV frame must be a non-empty DataFrame")
    missing = sorted(set(_OHLCV).difference(frame.columns))
    if missing:
        raise ValueError(f"{symbol}: missing OHLCV columns: {missing}")
    raw_ts = frame["ts"] if "ts" in frame.columns else frame.index
    try:
        index = pd.DatetimeIndex(raw_ts)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{symbol}: timestamps are invalid") from exc
    if index.tz is None or str(index.tz).upper() not in {"UTC", "UTC+00:00"}:
        raise ValueError(f"{symbol}: timestamps must be timezone-aware UTC")
    index = index.tz_convert(UTC)
    if index.has_duplicates or not index.is_monotonic_increasing:
        raise ValueError(f"{symbol}: timestamps must be unique and increasing")
    if np.any(index.as_unit("ns").asi8 % _BAR.value != 0):
        raise ValueError(f"{symbol}: timestamps must be on the UTC quarter-hour grid")
    if len(index) > 1:
        deltas = index[1:] - index[:-1]
        steps = deltas / _BAR
        if np.any(deltas <= pd.Timedelta(0)) or np.any(steps != np.floor(steps)):
            raise ValueError(f"{symbol}: timestamps must lie on one 15-minute grid")

    normalized = frame.loc[:, _OHLCV].copy().reset_index(drop=True)
    normalized.insert(0, "ts", index)
    try:
        values = normalized.loc[:, _OHLCV].to_numpy(dtype=float)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{symbol}: OHLCV values must be numeric") from exc
    if not np.isfinite(values).all():
        raise ValueError(f"{symbol}: OHLCV values must be finite")
    prices = normalized.loc[:, ("open", "high", "low", "close")]
    if (prices <= 0.0).any().any():
        raise ValueError(f"{symbol}: prices must be > 0")
    if (normalized["volume"] < 0.0).any():
        raise ValueError(f"{symbol}: volume must be >= 0")
    if (normalized["high"] < normalized[["open", "low", "close"]].max(axis=1)).any():
        raise ValueError(f"{symbol}: high violates OHLC geometry")
    if (normalized["low"] > normalized[["open", "high", "close"]].min(axis=1)).any():
        raise ValueError(f"{symbol}: low violates OHLC geometry")

    normalized.loc[:, _OHLCV] = values
    normalized["symbol"] = symbol
    normalized["venue"] = "binance"
    normalized["timeframe"] = "15m"
    normalized["vol_z_pre"] = 0.0
    return normalized


def _contiguous_blocks(frame: pd.DataFrame) -> tuple[pd.DataFrame, ...]:
    index = pd.DatetimeIndex(frame["ts"])
    if len(index) == 1:
        return (frame.reset_index(drop=True),)
    starts = np.flatnonzero(
        np.r_[True, (index[1:] - index[:-1]).to_numpy() != _BAR.to_timedelta64()]
    )
    stops = np.r_[starts[1:], len(frame)]
    return tuple(
        frame.iloc[start:stop].reset_index(drop=True)
        for start, stop in zip(starts, stops, strict=True)
    )


def _signal_timestamp(signal: Signal, *, strategy: str) -> pd.Timestamp:
    try:
        timestamp = pd.Timestamp(signal.ts)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{strategy}: signal timestamp is invalid") from exc
    if timestamp.tzinfo is None or timestamp.utcoffset() != timedelta(0):
        raise ValueError(f"{strategy}: signal timestamp must be UTC")
    return timestamp.tz_convert(UTC)


def _validate_strategy_output(
    spec: _StrategySpec,
    strategy: _StrategyLike,
    source: pd.DataFrame,
    prepared: pd.DataFrame,
    signals: list[Signal],
) -> None:
    if strategy.name != spec.name or strategy.manifest.name != spec.name:
        raise ValueError(f"{spec.name}: strategy/manifest identity mismatch")
    effective_hash = strategy.manifest.hash()
    if spec.expected_manifest_hash is not None and effective_hash != spec.expected_manifest_hash:
        raise ValueError(f"{spec.name}: effective manifest hash does not match the frozen baseline")
    if not isinstance(prepared, pd.DataFrame) or len(prepared) != len(source):
        raise ValueError(f"{spec.name}: prepare_features changed the bar count")
    if "ts" not in prepared.columns or not pd.DatetimeIndex(prepared["ts"]).equals(
        pd.DatetimeIndex(source["ts"])
    ):
        raise ValueError(f"{spec.name}: prepare_features changed bar timestamps")
    if not isinstance(signals, list) or any(not isinstance(signal, Signal) for signal in signals):
        raise TypeError(f"{spec.name}: generate_signals must return list[Signal]")
    if any(signal.manifest_hash != effective_hash for signal in signals):
        raise ValueError(f"{spec.name}: signal manifest hash does not match effective manifest")


def _run_strategy(
    spec: _StrategySpec,
    source: pd.DataFrame,
) -> tuple[_StrategyLike, pd.DataFrame, list[Signal]]:
    strategy = spec.strategy_type(spec.manifest_factory())
    prepared = strategy.prepare_features(source.copy())
    signals = strategy.generate_signals(prepared)
    _validate_strategy_output(spec, strategy, source, prepared, signals)
    return strategy, prepared, signals


def _signals_at_endpoint(
    spec: _StrategySpec,
    window: pd.DataFrame,
) -> list[Signal]:
    if len(window) != WARMUP_BARS:
        raise ValueError(f"{spec.name}: rolling window is not exactly 500 completed bars")
    _, _, signals = _run_strategy(spec, window)
    endpoint = pd.Timestamp(window.iloc[-1]["ts"])
    return [
        signal for signal in signals if _signal_timestamp(signal, strategy=spec.name) == endpoint
    ]


def _assert_vsa_bounded_window_contract(strategy: _StrategyLike) -> None:
    """Prove the frozen VSA endpoint uses fewer than 500 causal bars.

    The pinned implementation computes EMA200 but does not consult it when
    emitting VSA signals.  Every signal-bearing path is bounded by ATR20,
    volume-SMA40, local-extreme lookback 5, climax/test wait 24 and confirmation
    wait 3.  The checks below bind the manifest half of that proof; source hashes
    are independently required by the preregistered runner.
    """

    manifest = strategy.manifest
    if manifest.hash() != EXPECTED_SIGNAL_MANIFEST_HASHES["vsa_climax_test"]:
        raise ValueError("vsa_climax_test: bounded proof requires the frozen manifest")
    if bool(manifest.trend_filter.required):
        raise ValueError("vsa_climax_test: bounded proof requires the EMA trend gate disabled")
    internals = getattr(manifest, "vsa_internals", {}) or {}
    if not isinstance(internals, dict):
        raise ValueError("vsa_climax_test: vsa_internals must be a mapping")
    atr_period = int(internals.get("atr_period", 20))
    volume_period = int(internals.get("vol_sma_period", 20))
    maximum_dependency = max(atr_period, volume_period)
    for pattern in manifest.signals.patterns:
        params = pattern.params
        local_extreme = int(params.get("min_low_bars", params.get("max_high_bars", 1)))
        wait_max = int(params.get("wait_max", 1))
        maximum_dependency = max(
            maximum_dependency,
            max(atr_period, volume_period, local_extreme) + wait_max + 3,
        )
    if maximum_dependency >= WARMUP_BARS:
        raise ValueError("vsa_climax_test: signal dependency is not bounded below 500 bars")


def _vsa_bounded_exact_signals(spec: _StrategySpec, block: pd.DataFrame) -> list[Signal]:
    strategy, _, signals = _run_strategy(spec, block)
    _assert_vsa_bounded_window_contract(strategy)
    return signals


def _grimes_candidate_manifest(spec: _StrategySpec) -> StrategyManifest:
    """Clone Grimes and relax only its within-window cooldown to zero."""

    original = spec.manifest_factory().model_dump(mode="python")
    relaxed = spec.manifest_factory().model_dump(mode="python")
    patterns = relaxed.get("signals", {}).get("patterns", [])
    for pattern in patterns:
        params = pattern.get("params", {})
        params["cooldown_bars"] = 0

    # Fail closed if anything except the explicitly relaxed field drifted.
    normalized_original = StrategyManifest.model_validate(original).model_dump(mode="python")
    normalized_relaxed = StrategyManifest.model_validate(relaxed).model_dump(mode="python")
    for payload in (normalized_original, normalized_relaxed):
        for pattern in payload["signals"]["patterns"]:
            pattern["params"]["cooldown_bars"] = 0
    if normalized_original != normalized_relaxed:
        raise ValueError("grimes_abc_pullback: candidate manifest changed a structural gate")
    return StrategyManifest.model_validate(relaxed)


def _grimes_candidate_locations(spec: _StrategySpec, block: pd.DataFrame) -> tuple[int, ...]:
    """Return a guaranteed superset of rolling-500 Grimes signal endpoints.

    ATR, fractals and the nested ABC searches are finite-window features.  EMA50
    and the 10-bar cooldown are the only rolling-window state that can change an
    endpoint.  Two diagnostic passes preserve every structural/price/ATR gate,
    set cooldown to zero, and engineer EMA arrays that make respectively every
    long or every short trend gate true.  Every real endpoint must therefore be
    in their union; each member is subsequently re-evaluated by the untouched
    strategy on its exact rolling 500-bar window.
    """

    candidate_manifest = _grimes_candidate_manifest(spec)
    base_strategy = spec.strategy_type(candidate_manifest)
    prepared = base_strategy.prepare_features(block.copy())
    if not isinstance(prepared, pd.DataFrame) or len(prepared) != len(block):
        raise ValueError("grimes_abc_pullback: candidate feature preparation changed bars")
    closes = prepared["close"].to_numpy(dtype=float)
    if not np.isfinite(closes).all() or np.any(closes <= 0.0):
        raise ValueError("grimes_abc_pullback: candidate closes must be finite and positive")
    n = len(prepared)
    locations: set[int] = set()
    timestamp_locations = {
        pd.Timestamp(timestamp): location for location, timestamp in enumerate(prepared["ts"])
    }

    long_floor = float(np.min(closes)) * 0.10
    long_ema = long_floor + np.arange(n, dtype=float) * (long_floor / (n + 1))
    short_ceiling = float(np.max(closes)) * 2.0
    short_ema = short_ceiling - np.arange(n, dtype=float) * (float(np.max(closes)) * 0.50 / (n + 1))
    long_pattern = next(
        pattern
        for pattern in candidate_manifest.signals.patterns
        if pattern.id == "grimes_abc_long"
    )
    ema_lag = int(long_pattern.params.get("ema_slope_lag", 10))
    if ema_lag <= 0 or ema_lag >= WARMUP_BARS:
        raise ValueError("grimes_abc_pullback: EMA slope lag is outside the bounded contract")
    if not (
        np.all(closes > long_ema)
        and np.all(long_ema[ema_lag:] > long_ema[:-ema_lag])
        and np.all(closes < short_ema)
        and np.all(short_ema[ema_lag:] < short_ema[:-ema_lag])
    ):
        raise ValueError("grimes_abc_pullback: engineered EMA did not relax every trend gate")

    for direction, engineered in (("long", long_ema), ("short", short_ema)):
        candidate_strategy = spec.strategy_type(candidate_manifest.model_copy(deep=True))
        diagnostic = prepared.copy()
        diagnostic["ema50"] = engineered
        signals = candidate_strategy.generate_signals(diagnostic)
        if any(signal.direction != direction for signal in signals):
            raise ValueError("grimes_abc_pullback: engineered pass leaked the opposite side")
        for signal in signals:
            location = timestamp_locations.get(_signal_timestamp(signal, strategy=spec.name))
            if location is not None and WARMUP_BARS - 1 <= location < len(block):
                locations.add(location)
    return tuple(sorted(locations))


def _grimes_rolling_exact_signals(spec: _StrategySpec, block: pd.DataFrame) -> list[Signal]:
    output: list[Signal] = []
    for location in _grimes_candidate_locations(spec, block):
        window = block.iloc[location - WARMUP_BARS + 1 : location + 1].reset_index(drop=True)
        output.extend(_signals_at_endpoint(spec, window))
    return output


def _bruteforce_rolling_exact_signals(spec: _StrategySpec, block: pd.DataFrame) -> list[Signal]:
    """Small-fixture/reference path used by injected audit strategies."""

    output: list[Signal] = []
    for location in range(WARMUP_BARS - 1, len(block)):
        window = block.iloc[location - WARMUP_BARS + 1 : location + 1].reset_index(drop=True)
        output.extend(_signals_at_endpoint(spec, window))
    return output


def _rolling_exact_signals(spec: _StrategySpec, block: pd.DataFrame) -> list[Signal]:
    if spec.rolling_mode == "vsa_bounded":
        return _vsa_bounded_exact_signals(spec, block)
    if spec.rolling_mode == "grimes_candidates":
        return _grimes_rolling_exact_signals(spec, block)
    if spec.rolling_mode == "bruteforce":
        return _bruteforce_rolling_exact_signals(spec, block)
    raise ValueError(f"{spec.name}: unsupported rolling mode")


def _evaluate_signal_emission(
    signal: Signal,
    *,
    emission_index: int,
    spec: _StrategySpec,
    strategy_rank: int,
    block: pd.DataFrame,
    location: int,
    symbol: str,
    policy: V15P2SignalPolicy,
) -> tuple[SignalDecisionLedger, V15P2SignalIntent | None]:
    if signal.symbol != symbol or signal.venue != "binance" or signal.timeframe != "15m":
        raise ValueError(f"{spec.name}: signal instrument metadata does not match its frame")
    if signal.direction not in {"long", "short"}:
        raise ValueError(f"{spec.name}: unsupported signal direction")
    score = _finite("confluence_score", signal.confluence_score)
    stop = _finite("stop_price", signal.sl_price, positive=True)
    take_profit = _finite("take_profit_price", signal.tp_price, positive=True)
    suggested_size = _finite("suggested_size_atr", signal.suggested_size_atr, positive=True)
    decision_close = _finite("decision_close", block.iloc[location]["close"], positive=True)
    decision_stop_distance = abs(decision_close - stop) / decision_close
    decision_ts = pd.Timestamp(block.iloc[location]["ts"])
    entry_price: float | None = None
    entry_stop_distance: float | None = None
    entry_ts: pd.Timestamp | None = None
    if location + 1 < len(block):
        entry_price = _finite("entry_price", block.iloc[location + 1]["open"], positive=True)
        entry_stop_distance = abs(entry_price - stop) / entry_price
        entry_ts = pd.Timestamp(block.iloc[location + 1]["ts"])
        if entry_ts - decision_ts != _BAR:
            raise ValueError("signal does not have an exact contiguous entry bar")

    reason: SignalDecisionReason
    if score < policy.confidence_min:
        reason = "confidence_below_minimum"
    elif decision_stop_distance < policy.stop_distance_pct_min:
        reason = "decision_stop_distance_below_minimum"
    elif entry_ts is None:
        reason = "missing_next_bar"
    else:
        reason = "accepted"
    outcome: SignalDecisionOutcome = "accepted" if reason == "accepted" else "rejected"

    ledger = SignalDecisionLedger(
        emission_index=emission_index,
        candidate_id=policy.candidate_id,
        decision_ts=decision_ts.to_pydatetime(),
        entry_ts=None if entry_ts is None else entry_ts.to_pydatetime(),
        symbol=symbol,
        side=signal.direction,
        strategy=spec.name,
        strategy_rank=strategy_rank,
        pattern_id=signal.pattern_id,
        confluence_score=score,
        decision_close=decision_close,
        entry_reference_price=decision_close,
        entry_price=entry_price,
        stop_price=stop,
        take_profit_price=take_profit,
        decision_stop_distance_pct=decision_stop_distance,
        entry_stop_distance_pct=entry_stop_distance,
        suggested_size_atr=suggested_size,
        signal_manifest_hash=signal.manifest_hash,
        config_sha256=policy.config_sha256,
        outcome=outcome,
        reason=reason,
    )
    if reason != "accepted":
        return ledger, None
    assert entry_ts is not None
    assert entry_price is not None
    assert entry_stop_distance is not None

    intent = V15P2SignalIntent(
        candidate_id=policy.candidate_id,
        decision_ts=decision_ts.to_pydatetime(),
        entry_ts=entry_ts.to_pydatetime(),
        symbol=symbol,
        side=signal.direction,
        strategy=spec.name,
        strategy_rank=strategy_rank,
        pattern_id=signal.pattern_id,
        confluence_score=score,
        decision_close=decision_close,
        entry_reference_price=decision_close,
        entry_price=entry_price,
        stop_price=stop,
        take_profit_price=take_profit,
        decision_stop_distance_pct=decision_stop_distance,
        entry_stop_distance_pct=entry_stop_distance,
        suggested_size_atr=suggested_size,
        signal_manifest_hash=signal.manifest_hash,
        config_sha256=policy.config_sha256,
    )
    return ledger, intent


def generate_current_v15p2_signal_batch(
    frames: Mapping[str, pd.DataFrame],
    *,
    policy: V15P2SignalPolicy | None = None,
) -> SignalGenerationResult:
    """Regenerate v15p2 intents and ledger every raw rolling-window emission.

    The first eligible decision in each exact-contiguous block is its 500th
    bar.  Its entry requires a 501st, exactly-contiguous bar.  All eligible
    same-symbol/same-decision intents are retained in VSA-then-Grimes order;
    portfolio evaluation, not signal generation, determines which is the first
    accepted intent.
    """

    if not isinstance(frames, Mapping) or not frames:
        raise ValueError("frames must be a non-empty symbol-to-DataFrame mapping")
    frozen_policy = policy or load_current_v15p2_signal_policy()
    specs = _strategy_specs()
    if tuple(spec.name for spec in specs) != frozen_policy.strategy_order:
        raise ValueError("strategy adapters do not match the frozen v15p2 order")

    intents: list[V15P2SignalIntent] = []
    decisions: list[SignalDecisionLedger] = []
    accepted_fingerprints: set[tuple[object, ...]] = set()
    for symbol in sorted(frames):
        normalized = _normalize_symbol_frame(symbol, frames[symbol])
        for block in _contiguous_blocks(normalized):
            if len(block) < frozen_policy.warmup_bars:
                continue
            timestamp_locations = {
                timestamp: location
                for location, timestamp in enumerate(pd.DatetimeIndex(block["ts"]))
            }
            for strategy_rank, spec in enumerate(specs):
                signals = _rolling_exact_signals(spec, block)
                ordered = sorted(
                    signals,
                    key=lambda signal: (
                        _signal_timestamp(signal, strategy=spec.name),
                        signal.direction,
                        signal.pattern_id,
                    ),
                )
                for signal in ordered:
                    decision_ts = _signal_timestamp(signal, strategy=spec.name)
                    location = timestamp_locations.get(decision_ts)
                    if location is None:
                        raise ValueError(
                            f"{spec.name}: signal timestamp is outside its source block"
                        )
                    if location < frozen_policy.warmup_bars - 1:
                        continue
                    ledger, intent = _evaluate_signal_emission(
                        signal,
                        emission_index=0,
                        spec=spec,
                        strategy_rank=strategy_rank,
                        block=block,
                        location=location,
                        symbol=symbol,
                        policy=frozen_policy,
                    )
                    if intent is not None:
                        fingerprint = _intent_fingerprint(intent)
                        if fingerprint in accepted_fingerprints:
                            ledger = replace(
                                ledger,
                                outcome="rejected",
                                reason="duplicate_signal_fingerprint",
                            )
                            intent = None
                        else:
                            accepted_fingerprints.add(fingerprint)
                            intents.append(intent)
                    decisions.append(ledger)

    ordered_intents = tuple(
        sorted(
            intents,
            key=lambda intent: (
                intent.decision_ts,
                intent.symbol,
                intent.strategy_rank,
                intent.side,
                intent.pattern_id,
                intent.stop_price,
                intent.take_profit_price,
            ),
        )
    )
    ordered_decisions = tuple(
        replace(decision, emission_index=index)
        for index, decision in enumerate(
            sorted(
                decisions,
                key=lambda decision: (
                    decision.decision_ts,
                    decision.symbol,
                    decision.strategy_rank,
                    decision.side,
                    decision.pattern_id,
                    decision.stop_price,
                    decision.take_profit_price,
                    decision.emission_index,
                ),
            )
        )
    )
    return SignalGenerationResult(
        candidate_id=frozen_policy.candidate_id,
        config_sha256=frozen_policy.config_sha256,
        decisions=ordered_decisions,
        intents=ordered_intents,
    )


def generate_current_v15p2_signal_intents(
    frames: Mapping[str, pd.DataFrame],
    *,
    policy: V15P2SignalPolicy | None = None,
) -> tuple[V15P2SignalIntent, ...]:
    """Compatibility wrapper returning only signal-eligible intents."""

    return generate_current_v15p2_signal_batch(frames, policy=policy).intents


def generate_v15p2_signal_batch(
    frames: Mapping[str, pd.DataFrame],
    *,
    config_path: str | Path = CANONICAL_CONFIG_PATH,
    config_sha256: str | None = None,
) -> SignalGenerationResult:
    """Public config-bound signal audit batch for the fair v15p2 baseline."""

    expected = EXPECTED_CONFIG_SHA256 if config_sha256 is None else str(config_sha256).lower()
    if expected != EXPECTED_CONFIG_SHA256:
        raise ValueError("config_sha256 does not identify the frozen v15p2 baseline")
    policy = load_current_v15p2_signal_policy(config_path, expected_sha256=expected)
    return generate_current_v15p2_signal_batch(frames, policy=policy)


def generate_v15p2_intents(
    frames: Mapping[str, pd.DataFrame],
    *,
    config_path: str | Path = CANONICAL_CONFIG_PATH,
    config_sha256: str | None = None,
) -> tuple[V15P2SignalIntent, ...]:
    """Public config-bound entry point for the fair v15p2 baseline.

    Passing ``config_sha256=None`` binds to the preregistered canonical digest;
    an explicit digest is useful when the caller already parsed provenance.
    The lower-level :func:`generate_current_v15p2_signal_intents` remains the
    IO-free boundary for callers that already hold a validated policy object.
    """

    return generate_v15p2_signal_batch(
        frames,
        config_path=config_path,
        config_sha256=config_sha256,
    ).intents


__all__ = [
    "CANONICAL_CONFIG_PATH",
    "CONFIDENCE_MIN",
    "EXPECTED_CONFIG_SHA256",
    "EXPECTED_SIGNAL_MANIFEST_HASHES",
    "FAIR_BASELINE_CANDIDATE_ID",
    "STOP_DISTANCE_PCT_MIN",
    "STRATEGY_ORDER",
    "WARMUP_BARS",
    "SignalDecisionLedger",
    "SignalGenerationResult",
    "V15P2SignalIntent",
    "V15P2SignalPolicy",
    "generate_current_v15p2_signal_batch",
    "generate_current_v15p2_signal_intents",
    "generate_v15p2_intents",
    "generate_v15p2_signal_batch",
    "load_current_v15p2_signal_policy",
]
