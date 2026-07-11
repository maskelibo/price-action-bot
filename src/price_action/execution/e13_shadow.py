"""Causal, stateful ATR-chandelier shadow recorder for the E13 exit trial.

The recorder never submits or modifies an exchange order.  A completed bar may
only update the stop used by the *next* bar, which keeps the paired outcome
free of same-bar lookahead.  State is policy-hashed and evidence is append-only.
"""

from __future__ import annotations

import errno
import fcntl
import hashlib
import json
import math
import os
import signal
import stat
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from functools import wraps
from pathlib import Path
from typing import TYPE_CHECKING, Any

from price_action.execution.e13_storage import (
    atomic_write_text,
    durable_unlink,
    e13_global_lock_path,
    e13_transaction_path,
    ensure_canonical_e13_data_root,
    fsync_directory,
    secure_read_text,
    validate_e13_artifact_path,
)

if TYPE_CHECKING:
    from price_action.execution.exit_evidence import E13Policy

_SOURCE = "e13_atr_shadow_recorder_v1"
_TRADE_FIELDS = {
    "trade_id",
    "side",
    "ts_open_utc",
    "entry_price",
    "initial_sl_price",
    "risk_per_unit",
    "active_stop",
    "high_water",
    "low_water",
    "bars_observed",
    "last_bar_utc",
    "trail_activated",
    "candidate_exit_price",
    "candidate_closed_at_utc",
    "candidate_close_reason",
    "baseline_exit_price",
    "baseline_closed_at_utc",
    "baseline_close_reason",
    "baseline_realized_r",
}
_CANDIDATE_REASONS_BY_TRAIL = {
    False: {"shared_initial_stop", "shared_initial_stop_gap"},
    True: {"atr_chandelier_gap", "atr_chandelier_stop"},
}


def e13_shadow_lock_path(_state_path: str | Path | None = None) -> Path:
    """Return the one canonical E13 lease, independent of config/path aliases."""
    return e13_global_lock_path()


class E13ShadowBusyError(RuntimeError):
    """Another process owns the E13 state/evidence writer lease."""

    def __init__(self, lock_path: Path) -> None:
        self.lock_path = lock_path
        super().__init__(f"E13 shadow writer busy: {lock_path}")


class E13ShadowLease:
    """Non-blocking global E13 writer lease shared by every config."""

    def __init__(self, state_path: str | Path) -> None:
        self.state_path = validate_e13_artifact_path(
            state_path,
            field="E13 lease state_path",
        )
        self.lock_path = e13_shadow_lock_path()
        self._handle: Any | None = None

    @property
    def held(self) -> bool:
        return self._handle is not None

    def acquire(self) -> E13ShadowLease:
        if self.held:
            raise RuntimeError("E13 shadow writer lease is already held")
        ensure_canonical_e13_data_root()
        existed = self.lock_path.exists()
        validate_e13_artifact_path(
            self.lock_path,
            field="E13 global writer lock",
            create_parent=True,
        )
        flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_CLOEXEC", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(self.lock_path, flags, 0o600)
        handle = os.fdopen(fd, "r+", encoding="utf-8")
        try:
            if not existed:
                os.fchmod(handle.fileno(), 0o600)
            info = os.fstat(handle.fileno())
            if not stat.S_ISREG(info.st_mode):
                raise ValueError(f"E13 shadow lock is not a regular file: {self.lock_path}")
            if info.st_nlink != 1:
                raise ValueError(f"E13 shadow lock must not be hard-linked: {self.lock_path}")
            if info.st_uid != os.geteuid():
                raise ValueError("E13 shadow lock must be owned by the current uid")
            if stat.S_IMODE(info.st_mode) != 0o600:
                raise ValueError("E13 shadow lock must have safe mode 0600")
            current = self.lock_path.lstat()
            if (info.st_dev, info.st_ino) != (current.st_dev, current.st_ino):
                raise ValueError("E13 shadow lock changed while it was opened")
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                if exc.errno in {errno.EACCES, errno.EAGAIN}:
                    raise E13ShadowBusyError(self.lock_path) from exc
                raise
            handle.seek(0)
            handle.truncate()
            handle.write(f"pid={os.getpid()}\n")
            handle.flush()
            os.fsync(handle.fileno())
            if not existed:
                fsync_directory(self.lock_path.parent)
        except Exception:
            handle.close()
            raise
        self._handle = handle
        return self

    def release(self) -> None:
        handle = self._handle
        self._handle = None
        if handle is None:
            return
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()

    def __enter__(self) -> E13ShadowLease:
        return self.acquire()

    def __exit__(self, _exc_type: Any, _exc: Any, _tb: Any) -> None:
        self.release()


def _lease_guarded(method: Callable[..., Any]) -> Callable[..., Any]:
    @wraps(method)
    def guarded(self: AtrChandelierShadowRecorder, *args: Any, **kwargs: Any) -> Any:
        with self._operation_lease():
            return method(self, *args, **kwargs)

    return guarded


def _utc(value: datetime, *, field: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware")
    return value.astimezone(UTC)


def _finite_positive(value: Any, *, field: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{field} must be numeric")
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be numeric") from exc
    if not math.isfinite(parsed) or parsed <= 0:
        raise ValueError(f"{field} must be finite and > 0")
    return parsed


def _iso(value: datetime) -> str:
    return _utc(value, field="timestamp").isoformat()


def _state_number(value: Any, *, field: str, positive: bool = True) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{field} must be numeric")
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be numeric") from exc
    if not math.isfinite(parsed) or (positive and parsed <= 0):
        qualifier = "finite and > 0" if positive else "finite"
        raise ValueError(f"{field} must be {qualifier}")
    return parsed


def _state_timestamp(value: Any, *, field: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be an ISO-8601 timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field} must be a valid ISO-8601 timestamp") from exc
    return _utc(parsed, field=field)


def _require_15m_epoch_grid(value: datetime, *, field: str) -> None:
    """Reject timestamps that cannot identify a completed 15-minute bar."""
    utc_value = _utc(value, field=field)
    if utc_value.second or utc_value.microsecond or utc_value.minute % 15:
        raise ValueError(f"{field} must be aligned to the UTC 15m epoch grid")


def _validate_trade_semantics(
    trade_key: str,
    record: Any,
    policy: E13Policy,
) -> None:
    if not isinstance(record, dict) or set(record) != _TRADE_FIELDS:
        raise ValueError(f"E13 shadow trade {trade_key!r} has an invalid field set")
    trade_id = str(record.get("trade_id") or "").strip()
    if not trade_id or trade_id != trade_key:
        raise ValueError("E13 shadow trade key/id mismatch")
    side = str(record.get("side") or "").strip().lower()
    if side not in {"long", "short"}:
        raise ValueError(f"E13 shadow trade {trade_id} has invalid side")
    opened = _state_timestamp(record.get("ts_open_utc"), field=f"{trade_id}.ts_open")
    _require_15m_epoch_grid(opened, field=f"{trade_id}.ts_open")
    entry = _state_number(record.get("entry_price"), field=f"{trade_id}.entry_price")
    initial_sl = _state_number(
        record.get("initial_sl_price"), field=f"{trade_id}.initial_sl_price"
    )
    risk = _state_number(record.get("risk_per_unit"), field=f"{trade_id}.risk")
    if not math.isclose(risk, abs(entry - initial_sl), rel_tol=1e-10, abs_tol=1e-10):
        raise ValueError(f"E13 shadow trade {trade_id} risk mismatch")
    if (side == "long" and initial_sl >= entry) or (
        side == "short" and initial_sl <= entry
    ):
        raise ValueError(f"E13 shadow trade {trade_id} initial stop is reversed")

    active_stop = _state_number(
        record.get("active_stop"), field=f"{trade_id}.active_stop"
    )
    high_water = _state_number(
        record.get("high_water"), field=f"{trade_id}.high_water"
    )
    low_water = _state_number(
        record.get("low_water"), field=f"{trade_id}.low_water"
    )
    if high_water < entry or low_water > entry or low_water > high_water:
        raise ValueError(f"E13 shadow trade {trade_id} water marks are reversed")
    if side == "long" and not math.isclose(
        low_water, entry, rel_tol=1e-12, abs_tol=1e-12
    ):
        raise ValueError(f"E13 long trade {trade_id} low water must remain entry")
    if side == "short" and not math.isclose(
        high_water, entry, rel_tol=1e-12, abs_tol=1e-12
    ):
        raise ValueError(f"E13 short trade {trade_id} high water must remain entry")

    bars = record.get("bars_observed")
    if isinstance(bars, bool) or not isinstance(bars, int) or bars < 0:
        raise ValueError(f"E13 shadow trade {trade_id} bars_observed is invalid")
    last_bar_raw = record.get("last_bar_utc")
    if (bars == 0) != (last_bar_raw is None):
        raise ValueError(f"E13 shadow trade {trade_id} last-bar count mismatch")
    last_bar = (
        _state_timestamp(last_bar_raw, field=f"{trade_id}.last_bar")
        if last_bar_raw is not None
        else None
    )
    if last_bar is not None and last_bar <= opened:
        raise ValueError(f"E13 shadow trade {trade_id} last bar is noncausal")
    if last_bar is not None:
        _require_15m_epoch_grid(last_bar, field=f"{trade_id}.last_bar")
        available_closes = int((last_bar - opened).total_seconds() // (15 * 60))
        if bars > available_closes:
            raise ValueError(
                f"E13 shadow trade {trade_id} bars_observed exceeds time capacity"
            )
    trail_activated = record.get("trail_activated")
    if not isinstance(trail_activated, bool):
        raise ValueError(f"E13 shadow trade {trade_id} trail flag is invalid")

    candidate_values = (
        record.get("candidate_exit_price"),
        record.get("candidate_closed_at_utc"),
        record.get("candidate_close_reason"),
    )
    candidate_terminal = any(value is not None for value in candidate_values)
    if candidate_terminal and any(value is None for value in candidate_values):
        raise ValueError(f"E13 shadow trade {trade_id} candidate terminal is partial")
    candidate_closed: datetime | None = None
    if candidate_terminal:
        candidate_exit = _state_number(
            candidate_values[0], field=f"{trade_id}.candidate_exit_price"
        )
        candidate_closed = _state_timestamp(
            candidate_values[1], field=f"{trade_id}.candidate_closed_at"
        )
        if candidate_closed <= opened:
            raise ValueError(f"E13 shadow trade {trade_id} candidate close is noncausal")
        if candidate_values[2] not in _CANDIDATE_REASONS_BY_TRAIL[trail_activated]:
            raise ValueError(
                f"E13 shadow trade {trade_id} candidate reason/trail mismatch"
            )
        if str(candidate_values[2]).endswith("_gap"):
            gap_crossed_stop = (
                candidate_exit <= active_stop
                if side == "long"
                else candidate_exit >= active_stop
            )
            if not gap_crossed_stop:
                raise ValueError(
                    f"E13 shadow trade {trade_id} candidate gap did not cross stop"
                )
        elif not math.isclose(
            candidate_exit, active_stop, rel_tol=1e-12, abs_tol=1e-12
        ):
            raise ValueError(
                f"E13 shadow trade {trade_id} candidate stop price mismatch"
            )

    baseline_values = (
        record.get("baseline_exit_price"),
        record.get("baseline_closed_at_utc"),
        record.get("baseline_close_reason"),
        record.get("baseline_realized_r"),
    )
    baseline_terminal = any(value is not None for value in baseline_values)
    if baseline_terminal and any(value is None for value in baseline_values):
        raise ValueError(f"E13 shadow trade {trade_id} baseline terminal is partial")
    if baseline_terminal:
        baseline_exit = _state_number(
            baseline_values[0], field=f"{trade_id}.baseline_exit_price"
        )
        baseline_closed = _state_timestamp(
            baseline_values[1], field=f"{trade_id}.baseline_closed_at"
        )
        if baseline_closed <= opened:
            raise ValueError(f"E13 shadow trade {trade_id} baseline close is noncausal")
        if baseline_values[2] not in policy.eligible_close_reasons:
            raise ValueError(f"E13 shadow trade {trade_id} baseline reason is ineligible")
        baseline_r = _state_number(
            baseline_values[3], field=f"{trade_id}.baseline_realized_r", positive=False
        )
        direction = 1.0 if side == "long" else -1.0
        expected_r = direction * (baseline_exit - entry) / risk
        if not math.isclose(baseline_r, expected_r, rel_tol=1e-8, abs_tol=1e-8):
            raise ValueError(f"E13 shadow trade {trade_id} baseline R mismatch")

    if candidate_terminal and baseline_terminal:
        raise ValueError(f"E13 shadow trade {trade_id} has two terminal outcomes")
    if bars == 0:
        if trail_activated or candidate_terminal or baseline_terminal:
            raise ValueError(f"E13 shadow trade {trade_id} terminal/trail without bars")
        if not math.isclose(high_water, entry) or not math.isclose(low_water, entry):
            raise ValueError(f"E13 shadow trade {trade_id} water moved without bars")
    if candidate_terminal and candidate_closed != last_bar:
        raise ValueError(f"E13 shadow trade {trade_id} candidate/last-bar mismatch")

    if not trail_activated:
        if not math.isclose(active_stop, initial_sl, rel_tol=1e-12, abs_tol=1e-12):
            raise ValueError(f"E13 shadow trade {trade_id} inactive stop drifted")
        activation = (
            entry + policy.atr_activate_after_r * risk
            if side == "long"
            else entry - policy.atr_activate_after_r * risk
        )
        activation_reached = bars > 0 and (
            high_water >= activation if side == "long" else low_water <= activation
        )
        first_bar_initial_stop = (
            candidate_terminal
            and bars == 1
            and policy.atr_activate_after_r == 0
            and math.isclose(high_water, entry)
            and math.isclose(low_water, entry)
        )
        if activation_reached and not first_bar_initial_stop:
            raise ValueError(
                f"E13 shadow trade {trade_id} inactive trail crossed activation"
            )
    else:
        if bars < 1 or last_bar is None:
            raise ValueError(f"E13 shadow trade {trade_id} active trail has no bar")
        if side == "long":
            activation = entry + policy.atr_activate_after_r * risk
            if (
                high_water < activation
                or active_stop < entry
                or active_stop > high_water
                or (high_water > entry and active_stop >= high_water)
            ):
                raise ValueError(f"E13 long trade {trade_id} active stop is impossible")
        else:
            activation = entry - policy.atr_activate_after_r * risk
            if (
                low_water > activation
                or active_stop > entry
                or active_stop < low_water
                or (low_water < entry and active_stop <= low_water)
            ):
                raise ValueError(f"E13 short trade {trade_id} active stop is impossible")


def validate_e13_shadow_state_document(
    state: Any,
    policy: E13Policy,
    *,
    expected_hash: str,
    legacy_provenance: bool = False,
) -> None:
    """Validate structural and causal invariants for one persisted checkpoint."""
    if not isinstance(state, dict):
        raise ValueError("invalid E13 shadow state structure")
    base_fields = {"schema_version", "policy_hash_sha256", "trades"}
    fields = set(state)
    if legacy_provenance:
        if fields not in (base_fields, base_fields | {"policy_provenance_version"}):
            raise ValueError("invalid legacy E13 shadow state field set")
        if (
            "policy_provenance_version" in state
            and state.get("policy_provenance_version") != 1
        ):
            raise ValueError("legacy E13 shadow state provenance mismatch")
    elif fields != base_fields | {"policy_provenance_version"}:
        raise ValueError("invalid E13 shadow state field set")
    if state.get("schema_version") != policy.shadow_schema_version:
        raise ValueError("E13 shadow state schema mismatch")
    if state.get("policy_hash_sha256") != expected_hash:
        raise ValueError("E13 shadow state policy hash mismatch")
    if not legacy_provenance and (
        state.get("policy_provenance_version") != policy.policy_provenance_version
    ):
        raise ValueError("E13 shadow state policy provenance mismatch")
    trades = state.get("trades")
    if not isinstance(trades, dict):
        raise ValueError("invalid E13 shadow state trades structure")
    for raw_key, record in trades.items():
        if not isinstance(raw_key, str) or not raw_key.strip():
            raise ValueError("E13 shadow state trade key is invalid")
        _validate_trade_semantics(raw_key, record, policy)


class AtrChandelierShadowRecorder:
    """Persist causal E13 shadow state and policy-bound paired evidence."""

    def __init__(
        self,
        policy: E13Policy,
        *,
        lease: E13ShadowLease | None = None,
        on_artifact_mutation: Callable[[Path], None] | None = None,
        transaction_path: str | Path | None = None,
    ) -> None:
        self.policy = policy
        self.state_path = validate_e13_artifact_path(
            policy.shadow_state_path,
            field="E13 shadow state",
            create_parent=True,
        )
        self.evidence_path = validate_e13_artifact_path(
            policy.shadow_evidence_path,
            field="E13 shadow evidence",
            create_parent=True,
        )
        if self.state_path == self.evidence_path:
            raise ValueError("E13 state and evidence paths must be different")
        self.lease_path = e13_shadow_lock_path()
        self.transaction_path = validate_e13_artifact_path(
            e13_transaction_path() if transaction_path is None else transaction_path,
            field="E13 recovery transaction",
            create_parent=True,
        )
        if self.transaction_path in {self.state_path, self.evidence_path}:
            raise ValueError("E13 transaction path collides with state/evidence")
        self._lease = lease
        self._on_artifact_mutation = on_artifact_mutation
        if lease is not None:
            if not lease.held:
                raise ValueError("E13 recorder lease must be held")
            self._state = self._load_state()
            self._recover_transaction()
        else:
            with E13ShadowLease(self.state_path):
                self._state = self._load_state()
                self._recover_transaction()

    @contextmanager
    def _operation_lease(self) -> Iterator[None]:
        if self._lease is not None:
            if not self._lease.held:
                raise RuntimeError("E13 recorder lease was released during operation")
            yield
            return
        with E13ShadowLease(self.state_path):
            # A standalone recorder may live longer than another process' tick.
            # Always reload after acquiring so no stale in-memory state can win.
            self._state = self._load_state()
            self._recover_transaction()
            yield

    def _empty_state(self) -> dict[str, Any]:
        return {
            "schema_version": self.policy.shadow_schema_version,
            "policy_provenance_version": self.policy.policy_provenance_version,
            "policy_hash_sha256": self.policy.policy_hash_sha256,
            "trades": {},
        }

    def _load_state(self) -> dict[str, Any]:
        validate_e13_artifact_path(
            self.state_path,
            field="E13 shadow state",
            create_parent=True,
        )
        if not self.state_path.exists():
            return self._empty_state()
        try:
            state = json.loads(
                secure_read_text(self.state_path, field="E13 shadow state")
            )
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"invalid E13 shadow state: {self.state_path}") from exc
        validate_e13_shadow_state_document(
            state,
            self.policy,
            expected_hash=self.policy.policy_hash_sha256,
        )
        return state

    def _persist(self) -> None:
        validate_e13_shadow_state_document(
            self._state,
            self.policy,
            expected_hash=self.policy.policy_hash_sha256,
        )
        payload = json.dumps(self._state, sort_keys=True, indent=2) + "\n"
        atomic_write_text(
            self.state_path,
            payload,
            field="E13 shadow state",
            on_mutation=self._on_artifact_mutation,
        )

    @staticmethod
    def _validate_identity(
        record: dict[str, Any],
        *,
        trade_id: str,
        side: str,
        ts_open: datetime,
        entry_price: float,
        initial_sl_price: float,
    ) -> None:
        expected_open = _utc(ts_open, field="ts_open").isoformat()
        expected_entry = _finite_positive(entry_price, field="entry_price")
        expected_sl = _finite_positive(initial_sl_price, field="initial_sl_price")
        identity_matches = (
            record.get("trade_id") == trade_id
            and record.get("side") == side
            and record.get("ts_open_utc") == expected_open
            and math.isclose(
                float(record.get("entry_price")),
                expected_entry,
                rel_tol=1e-12,
                abs_tol=1e-12,
            )
            and math.isclose(
                float(record.get("initial_sl_price")),
                expected_sl,
                rel_tol=1e-12,
                abs_tol=1e-12,
            )
        )
        if not identity_matches:
            raise ValueError(f"conflicting E13 shadow trade identity: {trade_id}")

    @_lease_guarded
    def start_trade(
        self,
        *,
        trade_id: str,
        side: str,
        ts_open: datetime,
        entry_price: float,
        initial_sl_price: float,
    ) -> dict[str, Any]:
        """Register an open baseline trade; identical retries are idempotent."""
        normalized_id = str(trade_id).strip()
        normalized_side = str(side).strip().lower()
        if not normalized_id:
            raise ValueError("trade_id must be non-empty")
        if normalized_side not in {"long", "short"}:
            raise ValueError("side must be long or short")
        opened = _utc(ts_open, field="ts_open")
        _require_15m_epoch_grid(opened, field="ts_open")
        entry = _finite_positive(entry_price, field="entry_price")
        initial_sl = _finite_positive(initial_sl_price, field="initial_sl_price")
        if normalized_side == "long" and initial_sl >= entry:
            raise ValueError("long initial SL must be below entry")
        if normalized_side == "short" and initial_sl <= entry:
            raise ValueError("short initial SL must be above entry")

        record = {
            "trade_id": normalized_id,
            "side": normalized_side,
            "ts_open_utc": opened.isoformat(),
            "entry_price": entry,
            "initial_sl_price": initial_sl,
            "risk_per_unit": abs(entry - initial_sl),
            "active_stop": initial_sl,
            "high_water": entry,
            "low_water": entry,
            "bars_observed": 0,
            "last_bar_utc": None,
            "trail_activated": False,
            "candidate_exit_price": None,
            "candidate_closed_at_utc": None,
            "candidate_close_reason": None,
            "baseline_exit_price": None,
            "baseline_closed_at_utc": None,
            "baseline_close_reason": None,
            "baseline_realized_r": None,
        }
        existing = self._state["trades"].get(normalized_id)
        if existing is not None:
            self._validate_identity(
                existing,
                trade_id=normalized_id,
                side=normalized_side,
                ts_open=opened,
                entry_price=entry,
                initial_sl_price=initial_sl,
            )
            return dict(existing)
        self._state["trades"][normalized_id] = record
        self._persist()
        return dict(record)

    @_lease_guarded
    def observe_closed_bar(
        self,
        *,
        trade_id: str,
        ts: datetime,
        open_price: float,
        high: float,
        low: float,
        close: float,
        atr: float,
    ) -> dict[str, Any]:
        """Apply the prior stop, then derive a stop for the next completed bar."""
        record = self._trade(trade_id)
        bar_ts = _utc(ts, field="bar ts")
        _require_15m_epoch_grid(bar_ts, field="bar ts")
        opened = datetime.fromisoformat(record["ts_open_utc"])
        if bar_ts <= opened:
            raise ValueError("bar must close after trade open")
        last_raw = record.get("last_bar_utc")
        if last_raw:
            last_ts = datetime.fromisoformat(last_raw)
            if bar_ts == last_ts:
                return dict(record)
            if bar_ts < last_ts:
                raise ValueError("E13 shadow bars must be chronological")
        if record.get("candidate_exit_price") is not None:
            return dict(record)

        o = _finite_positive(open_price, field="open_price")
        h = _finite_positive(high, field="high")
        lo = _finite_positive(low, field="low")
        c = _finite_positive(close, field="close")
        atr_value = _finite_positive(atr, field="atr")
        if h < max(o, lo, c) or lo > min(o, h, c):
            raise ValueError("invalid OHLC bar")

        record["bars_observed"] = int(record.get("bars_observed", 0)) + 1
        record["last_bar_utc"] = bar_ts.isoformat()

        side = record["side"]
        active_stop = float(record["active_stop"])
        if side == "long":
            if o <= active_stop:
                reason = (
                    "atr_chandelier_gap"
                    if record["trail_activated"]
                    else "shared_initial_stop_gap"
                )
                self._close_candidate(record, o, bar_ts, reason)
            elif lo <= active_stop:
                reason = (
                    "atr_chandelier_stop"
                    if record["trail_activated"]
                    else "shared_initial_stop"
                )
                self._close_candidate(record, active_stop, bar_ts, reason)
            else:
                record["high_water"] = max(float(record["high_water"]), h)
                activation = record["entry_price"] + (
                    self.policy.atr_activate_after_r * record["risk_per_unit"]
                )
                if float(record["high_water"]) >= activation:
                    record["trail_activated"] = True
                    next_stop = max(
                        float(record["initial_sl_price"]),
                        float(record["entry_price"]),
                        float(record["high_water"])
                        - self.policy.atr_multiplier * atr_value,
                    )
                    record["active_stop"] = max(active_stop, next_stop)
        else:
            if o >= active_stop:
                reason = (
                    "atr_chandelier_gap"
                    if record["trail_activated"]
                    else "shared_initial_stop_gap"
                )
                self._close_candidate(record, o, bar_ts, reason)
            elif h >= active_stop:
                reason = (
                    "atr_chandelier_stop"
                    if record["trail_activated"]
                    else "shared_initial_stop"
                )
                self._close_candidate(record, active_stop, bar_ts, reason)
            else:
                record["low_water"] = min(float(record["low_water"]), lo)
                activation = record["entry_price"] - (
                    self.policy.atr_activate_after_r * record["risk_per_unit"]
                )
                if float(record["low_water"]) <= activation:
                    record["trail_activated"] = True
                    next_stop = min(
                        float(record["initial_sl_price"]),
                        float(record["entry_price"]),
                        float(record["low_water"])
                        + self.policy.atr_multiplier * atr_value,
                    )
                    record["active_stop"] = min(active_stop, next_stop)
        evidence = self._maybe_emit(record)
        if evidence is None:
            self._persist()
        return evidence if evidence is not None else dict(record)

    @_lease_guarded
    def record_baseline_close(
        self,
        *,
        trade_id: str,
        ts_close: datetime,
        exit_price: float,
        close_reason: str,
        baseline_realized_r: float | None = None,
    ) -> dict[str, Any]:
        """Record the live close; keep shadowing until the candidate really exits."""
        normalized_id = str(trade_id).strip()
        record = self._trade(normalized_id)
        closed = _utc(ts_close, field="ts_close")
        opened = datetime.fromisoformat(record["ts_open_utc"])
        if closed <= opened:
            raise ValueError("baseline close must be after trade open")
        baseline_exit = _finite_positive(exit_price, field="exit_price")
        reason = str(close_reason).strip().lower()
        if reason not in self.policy.eligible_close_reasons:
            raise ValueError(f"baseline close reason is not E13-eligible: {reason}")
        if int(record.get("bars_observed", 0)) < 1:
            raise ValueError("cannot record baseline close without a causal bar")

        baseline_r = (
            self._realized_r(record, baseline_exit)
            if baseline_realized_r is None
            else _state_number(
                baseline_realized_r,
                field="baseline_realized_r",
                positive=False,
            )
        )
        if not math.isfinite(baseline_r):
            raise ValueError("baseline_realized_r must be finite")
        existing = (
            record.get("baseline_closed_at_utc"),
            record.get("baseline_exit_price"),
            record.get("baseline_close_reason"),
        )
        expected = (closed.isoformat(), baseline_exit, reason)
        if existing[0] is not None and existing != expected:
            raise ValueError(f"conflicting baseline close for E13 trade: {normalized_id}")
        record["baseline_closed_at_utc"] = closed.isoformat()
        record["baseline_exit_price"] = baseline_exit
        record["baseline_close_reason"] = reason
        record["baseline_realized_r"] = baseline_r
        evidence = self._maybe_emit(record)
        if evidence is None:
            self._persist()
        return evidence if evidence is not None else dict(record)

    def _maybe_emit(self, record: dict[str, Any]) -> dict[str, Any] | None:
        if record.get("candidate_exit_price") is None:
            return None
        if record.get("baseline_exit_price") is None:
            return None
        candidate_exit = float(record["candidate_exit_price"])
        evidence = {
            "schema_version": self.policy.shadow_schema_version,
            "policy_provenance_version": self.policy.policy_provenance_version,
            "source": _SOURCE,
            "causal": True,
            "policy_hash_sha256": self.policy.policy_hash_sha256,
            "trade_id": record["trade_id"],
            "side": record["side"],
            "ts_open_utc": record["ts_open_utc"],
            "baseline_closed_at_utc": record["baseline_closed_at_utc"],
            "candidate_closed_at_utc": record["candidate_closed_at_utc"],
            "entry_price": record["entry_price"],
            "initial_sl_price": record["initial_sl_price"],
            "risk_per_unit": record["risk_per_unit"],
            "baseline_exit_price": record["baseline_exit_price"],
            "candidate_exit_price": candidate_exit,
            "baseline_realized_r": record["baseline_realized_r"],
            "candidate_realized_r": self._realized_r(record, candidate_exit),
            "baseline_close_reason": record["baseline_close_reason"],
            "candidate_close_reason": record["candidate_close_reason"],
            "candidate_policy": {
                "method": "atr_chandelier",
                "atr_period": self.policy.atr_period,
                "atr_method": self.policy.atr_method,
                "multiplier": self.policy.atr_multiplier,
                "activate_after_R": self.policy.atr_activate_after_r,
                "stop_effective": "next_completed_bar",
                "market_venue": self.policy.shadow_market_venue,
                "timeframe": self.policy.shadow_timeframe,
                "entry_timestamp_semantics": self.policy.entry_timestamp_semantics,
            },
            "bars_observed": int(record["bars_observed"]),
        }
        self._commit_evidence(evidence)
        return evidence

    def _trade(self, trade_id: str) -> dict[str, Any]:
        normalized = str(trade_id).strip()
        record = self._state["trades"].get(normalized)
        if record is None:
            raise KeyError(f"E13 shadow trade not found: {normalized}")
        return record

    @_lease_guarded
    def trade_state(self, trade_id: str) -> dict[str, Any] | None:
        """Return a defensive copy of one open shadow state, if present."""
        record = self._state["trades"].get(str(trade_id).strip())
        return dict(record) if record is not None else None

    @_lease_guarded
    def validate_trade_identity(
        self,
        *,
        trade_id: str,
        side: str,
        ts_open: datetime,
        entry_price: float,
        initial_sl_price: float,
    ) -> dict[str, Any]:
        """Fail closed unless a journal baseline matches persisted identity."""
        normalized_id = str(trade_id).strip()
        normalized_side = str(side).strip().lower()
        record = self._trade(normalized_id)
        self._validate_identity(
            record,
            trade_id=normalized_id,
            side=normalized_side,
            ts_open=ts_open,
            entry_price=entry_price,
            initial_sl_price=initial_sl_price,
        )
        return dict(record)

    @_lease_guarded
    def discard_trade(self, trade_id: str) -> bool:
        """Drop an ineligible/invalid baseline trade without emitting evidence."""
        normalized = str(trade_id).strip()
        if normalized not in self._state["trades"]:
            return False
        del self._state["trades"][normalized]
        self._persist()
        return True

    @_lease_guarded
    def trade_ids(self) -> tuple[str, ...]:
        """Return deterministic IDs currently held in the state checkpoint."""
        return tuple(sorted(str(trade_id) for trade_id in self._state["trades"]))

    @_lease_guarded
    def evidence_trade_ids(self) -> set[str]:
        """Read append-only checkpoint IDs; malformed evidence fails closed."""
        return {
            str(record["trade_id"])
            for record in self._load_evidence_records()
        }

    @staticmethod
    def _close_candidate(
        record: dict[str, Any], price: float, closed_at: datetime, reason: str
    ) -> None:
        record["candidate_exit_price"] = float(price)
        record["candidate_closed_at_utc"] = closed_at.isoformat()
        record["candidate_close_reason"] = reason

    @staticmethod
    def _realized_r(record: dict[str, Any], exit_price: float) -> float:
        direction = 1.0 if record["side"] == "long" else -1.0
        return direction * (float(exit_price) - float(record["entry_price"])) / float(
            record["risk_per_unit"]
        )

    def _load_evidence_records(self) -> list[dict[str, Any]]:
        validate_e13_artifact_path(
            self.evidence_path,
            field="E13 shadow evidence",
            create_parent=True,
        )
        if not self.evidence_path.exists():
            return []
        text = secure_read_text(self.evidence_path, field="E13 shadow evidence")
        records: list[dict[str, Any]] = []
        trade_ids: set[str] = set()
        for line_number, line in enumerate(text.splitlines(), start=1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                quarantine = self._quarantine_corrupt_evidence(text)
                raise ValueError(
                    f"invalid E13 evidence JSON at line {line_number}; "
                    f"forensic copy: {quarantine}"
                ) from exc
            if not isinstance(record, dict):
                raise ValueError(f"E13 evidence line {line_number} must be an object")
            if record.get("schema_version") != self.policy.shadow_schema_version:
                raise ValueError(f"E13 evidence line {line_number} schema mismatch")
            if (
                record.get("policy_provenance_version")
                != self.policy.policy_provenance_version
            ):
                raise ValueError(
                    f"E13 evidence line {line_number} policy provenance mismatch"
                )
            if record.get("source") != _SOURCE or record.get("causal") is not True:
                raise ValueError(f"E13 evidence line {line_number} provenance mismatch")
            if record.get("policy_hash_sha256") != self.policy.policy_hash_sha256:
                raise ValueError(f"E13 evidence line {line_number} policy hash mismatch")
            trade_id = str(record.get("trade_id") or "").strip()
            if not trade_id:
                raise ValueError(f"E13 evidence line {line_number} has no trade_id")
            if trade_id in trade_ids:
                raise ValueError(f"duplicate E13 evidence trade_id: {trade_id}")
            trade_ids.add(trade_id)
            records.append(record)
        return records

    def _quarantine_corrupt_evidence(self, payload: str) -> Path:
        """Durably preserve malformed evidence without altering the source file."""
        digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:20]
        quarantine = self.evidence_path.with_name(
            f".{self.evidence_path.name}.corrupt-{digest}.quarantine"
        )
        validate_e13_artifact_path(
            quarantine,
            field="E13 corrupt evidence quarantine",
            create_parent=True,
        )
        if quarantine.exists():
            existing = secure_read_text(
                quarantine,
                field="E13 corrupt evidence quarantine",
            )
            if existing != payload:
                raise ValueError("E13 corrupt evidence quarantine digest collision")
            return quarantine
        return atomic_write_text(
            quarantine,
            payload,
            field="E13 corrupt evidence quarantine",
            on_mutation=self._on_artifact_mutation,
        )

    def _write_evidence_records(self, records: list[dict[str, Any]]) -> None:
        payload = "".join(
            json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n"
            for record in records
        )
        atomic_write_text(
            self.evidence_path,
            payload,
            field="E13 shadow evidence",
            on_mutation=self._on_artifact_mutation,
        )

    def _transaction_record(self, evidence: dict[str, Any]) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "policy_provenance_version": self.policy.policy_provenance_version,
            "policy_hash_sha256": self.policy.policy_hash_sha256,
            "state_path": str(self.state_path),
            "evidence_path": str(self.evidence_path),
            "trade_id": str(evidence["trade_id"]),
            "evidence": evidence,
        }

    def _write_transaction(self, evidence: dict[str, Any]) -> None:
        payload = json.dumps(
            self._transaction_record(evidence),
            sort_keys=True,
            separators=(",", ":"),
        ) + "\n"
        atomic_write_text(
            self.transaction_path,
            payload,
            field="E13 recovery transaction",
            on_mutation=self._on_artifact_mutation,
        )

    def _read_transaction(self) -> dict[str, Any] | None:
        validate_e13_artifact_path(
            self.transaction_path,
            field="E13 recovery transaction",
            create_parent=True,
        )
        if not self.transaction_path.exists():
            return None
        try:
            transaction = json.loads(
                secure_read_text(
                    self.transaction_path,
                    field="E13 recovery transaction",
                )
            )
        except json.JSONDecodeError as exc:
            raise ValueError("invalid E13 recovery transaction") from exc
        if not isinstance(transaction, dict):
            raise ValueError("E13 recovery transaction must be an object")
        expected = {
            "schema_version": 1,
            "policy_provenance_version": self.policy.policy_provenance_version,
            "policy_hash_sha256": self.policy.policy_hash_sha256,
            "state_path": str(self.state_path),
            "evidence_path": str(self.evidence_path),
        }
        for key, value in expected.items():
            if transaction.get(key) != value:
                raise ValueError(f"E13 recovery transaction {key} mismatch")
        evidence = transaction.get("evidence")
        trade_id = str(transaction.get("trade_id") or "").strip()
        if not isinstance(evidence, dict) or not trade_id:
            raise ValueError("invalid E13 recovery transaction payload")
        if str(evidence.get("trade_id") or "").strip() != trade_id:
            raise ValueError("E13 recovery transaction trade_id mismatch")
        if evidence.get("policy_hash_sha256") != self.policy.policy_hash_sha256:
            raise ValueError("E13 recovery evidence policy hash mismatch")
        return transaction

    @staticmethod
    def _test_cutpoint(name: str) -> None:
        """Deterministic crash/exception hook, inert outside marked tests."""
        if os.environ.get("PA_TESTING") != "1":
            return
        if os.environ.get("PA_E13_TEST_CUTPOINT") != name:
            return
        if os.environ.get("PA_E13_TEST_CUTPOINT_ACTION") == "exception":
            raise RuntimeError(f"injected E13 transaction failure: {name}")
        os.kill(os.getpid(), signal.SIGKILL)

    def _ensure_evidence_record(self, evidence: dict[str, Any]) -> None:
        trade_id = str(evidence["trade_id"])
        records = self._load_evidence_records()
        for existing in records:
            if str(existing.get("trade_id") or "") != trade_id:
                continue
            if existing != evidence:
                raise ValueError(f"conflicting E13 evidence for trade: {trade_id}")
            return
        self._write_evidence_records([*records, evidence])

    def _recover_transaction(self) -> None:
        transaction = self._read_transaction()
        if transaction is None:
            return
        evidence = transaction["evidence"]
        trade_id = str(transaction["trade_id"])
        self._ensure_evidence_record(evidence)
        if trade_id in self._state["trades"]:
            del self._state["trades"][trade_id]
            self._persist()
        durable_unlink(
            self.transaction_path,
            field="E13 recovery transaction",
            on_mutation=self._on_artifact_mutation,
        )

    def _commit_evidence(self, evidence: dict[str, Any]) -> None:
        trade_id = str(evidence["trade_id"])
        existing = next(
            (
                record
                for record in self._load_evidence_records()
                if str(record.get("trade_id") or "") == trade_id
            ),
            None,
        )
        if existing is not None:
            if existing != evidence:
                raise ValueError(f"conflicting E13 evidence for trade: {trade_id}")
            if trade_id in self._state["trades"]:
                del self._state["trades"][trade_id]
                self._persist()
            return

        self._write_transaction(evidence)
        self._test_cutpoint("after_transaction")
        self._ensure_evidence_record(evidence)
        self._test_cutpoint("after_evidence")
        del self._state["trades"][trade_id]
        self._persist()
        self._test_cutpoint("after_state")
        durable_unlink(
            self.transaction_path,
            field="E13 recovery transaction",
            on_mutation=self._on_artifact_mutation,
        )

    @_lease_guarded
    def status(self) -> dict[str, Any]:
        trades = self._state["trades"]
        return {
            "policy_hash_sha256": self.policy.policy_hash_sha256,
            "policy_provenance_version": self.policy.policy_provenance_version,
            "state_path": str(self.state_path),
            "evidence_path": str(self.evidence_path),
            "writer_lock_path": str(self.lease_path),
            "tracked_trades": len(trades),
            "candidate_closed_waiting_for_baseline": sum(
                record.get("candidate_exit_price") is not None
                and record.get("baseline_exit_price") is None
                for record in trades.values()
            ),
            "baseline_closed_waiting_for_candidate": sum(
                record.get("baseline_exit_price") is not None
                and record.get("candidate_exit_price") is None
                for record in trades.values()
            ),
            "exchange_calls": 0,
        }


__all__ = [
    "AtrChandelierShadowRecorder",
    "E13ShadowBusyError",
    "E13ShadowLease",
    "e13_shadow_lock_path",
    "validate_e13_shadow_state_document",
]
