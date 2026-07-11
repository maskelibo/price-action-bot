"""Controlled, crash-recoverable E13 policy-provenance migration.

The migration is intentionally separate from the scheduled shadow tick.  It
requires explicit old/new hashes and an operator reason, defaults to dry-run,
and holds the repository-global E13 writer lease for the entire inspection or
apply operation.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import signal
import stat
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from price_action.execution.e13_shadow import (
    E13ShadowBusyError,
    E13ShadowLease,
    validate_e13_shadow_state_document,
)
from price_action.execution.e13_storage import (
    atomic_write_text,
    canonical_e13_data_root,
    durable_unlink,
    e13_global_lock_path,
    e13_policy_migration_audit_path,
    e13_policy_migration_root,
    e13_policy_migration_transaction_path,
    e13_transaction_path,
    secure_read_text,
    validate_e13_artifact_path,
)
from price_action.execution.exit_evidence import (
    E13_DEFAULT_CONFIG_PATH,
    E13Policy,
    e13_legacy_semantic_policy_hash,
    load_e13_policy,
)

_SOURCE = "e13_atr_shadow_recorder_v1"
_HASH_LENGTH = 64
_CANDIDATE_REASONS = {
    "atr_chandelier_gap",
    "atr_chandelier_stop",
    "shared_initial_stop",
    "shared_initial_stop_gap",
}
_EVIDENCE_FIELDS = {
    "schema_version",
    "source",
    "causal",
    "policy_hash_sha256",
    "trade_id",
    "side",
    "ts_open_utc",
    "baseline_closed_at_utc",
    "candidate_closed_at_utc",
    "entry_price",
    "initial_sl_price",
    "risk_per_unit",
    "baseline_exit_price",
    "candidate_exit_price",
    "baseline_realized_r",
    "candidate_realized_r",
    "baseline_close_reason",
    "candidate_close_reason",
    "candidate_policy",
    "bars_observed",
}


class E13PolicyMigrationMutationError(RuntimeError):
    """Migration failed after at least one durable artifact mutation."""

    def __init__(self, cause: Exception, mutation_paths: set[Path]) -> None:
        self.mutated_real_artifacts = True
        self.mutation_paths = tuple(sorted(str(path) for path in mutation_paths))
        super().__init__(
            "E13 policy migration failed after durable mutation "
            f"({type(cause).__name__}): {cause}"
        )


class _MigrationHoldError(ValueError):
    def __init__(self, code: str, detail: str) -> None:
        self.code = code
        self.detail = detail
        super().__init__(detail)


def _sha256_text(payload: str) -> str:
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _validated_hash(value: str, *, field: str) -> str:
    normalized = str(value).strip().lower()
    if len(normalized) != _HASH_LENGTH or any(
        character not in "0123456789abcdef" for character in normalized
    ):
        raise ValueError(f"{field} must be a 64-character lowercase SHA-256")
    return normalized


def _operator_reason(value: str) -> str:
    normalized = " ".join(str(value).strip().split())
    if len(normalized) < 8:
        raise ValueError("operator_reason must contain at least 8 characters")
    return normalized


def _aware_timestamp(value: Any, *, field: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise _MigrationHoldError("STATE_INTEGRITY", f"{field} must be an ISO timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise _MigrationHoldError(
            "STATE_INTEGRITY", f"{field} must be a valid ISO timestamp"
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise _MigrationHoldError("STATE_INTEGRITY", f"{field} must be timezone-aware")
    return parsed.astimezone(UTC)


def _positive(value: Any, *, field: str) -> float:
    if isinstance(value, bool):
        raise _MigrationHoldError("STATE_INTEGRITY", f"{field} must be numeric")
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise _MigrationHoldError("STATE_INTEGRITY", f"{field} must be numeric") from exc
    if not math.isfinite(parsed) or parsed <= 0:
        raise _MigrationHoldError("STATE_INTEGRITY", f"{field} must be finite and > 0")
    return parsed


def _finite(value: Any, *, field: str) -> float:
    if isinstance(value, bool):
        raise _MigrationHoldError("STATE_INTEGRITY", f"{field} must be numeric")
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise _MigrationHoldError("STATE_INTEGRITY", f"{field} must be numeric") from exc
    if not math.isfinite(parsed):
        raise _MigrationHoldError("STATE_INTEGRITY", f"{field} must be finite")
    return parsed


def _load_state_document(
    policy: E13Policy,
    *,
    expected_hash: str,
    expected_provenance: int | None,
) -> tuple[dict[str, Any], str]:
    state_path = validate_e13_artifact_path(
        policy.shadow_state_path,
        field="E13 migration state",
        must_exist=True,
    )
    raw = secure_read_text(state_path, field="E13 migration state")
    try:
        state = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise _MigrationHoldError("STATE_INTEGRITY", "state JSON is invalid") from exc
    try:
        validate_e13_shadow_state_document(
            state,
            policy,
            expected_hash=expected_hash,
            legacy_provenance=expected_provenance is None,
        )
    except ValueError as exc:
        code = (
            "STATE_HASH_MISMATCH"
            if "policy hash mismatch" in str(exc)
            else "STATE_INTEGRITY"
        )
        raise _MigrationHoldError(code, str(exc)) from exc
    return state, raw


def _candidate_policy(policy: E13Policy) -> dict[str, Any]:
    return {
        "method": "atr_chandelier",
        "atr_period": policy.atr_period,
        "atr_method": policy.atr_method,
        "multiplier": policy.atr_multiplier,
        "activate_after_R": policy.atr_activate_after_r,
        "stop_effective": "next_completed_bar",
        "market_venue": policy.shadow_market_venue,
        "timeframe": policy.shadow_timeframe,
        "entry_timestamp_semantics": policy.entry_timestamp_semantics,
    }


def _validate_evidence_record(
    record: dict[str, Any],
    *,
    policy: E13Policy,
    expected_hash: str,
    expected_provenance: int | None,
    line_number: int,
) -> None:
    fields = set(record)
    if fields != _EVIDENCE_FIELDS and fields != _EVIDENCE_FIELDS | {
        "policy_provenance_version"
    }:
        raise _MigrationHoldError(
            "EVIDENCE_INCONSISTENT",
            f"evidence line {line_number} has an invalid field set",
        )
    provenance = record.get("policy_provenance_version")
    provenance_ok = (
        (
            "policy_provenance_version" not in record
            or provenance == 1
        )
        if expected_provenance is None
        else provenance == expected_provenance
    )
    valid_provenance = (
        record.get("schema_version") == policy.shadow_schema_version
        and provenance_ok
        and record.get("source") == _SOURCE
        and record.get("causal") is True
        and record.get("policy_hash_sha256") == expected_hash
        and record.get("candidate_policy") == _candidate_policy(policy)
    )
    if not valid_provenance:
        raise _MigrationHoldError(
            "EVIDENCE_INCONSISTENT",
            f"evidence line {line_number} provenance/policy is inconsistent",
        )
    side = str(record.get("side") or "").strip().lower()
    if side not in {"long", "short"}:
        raise _MigrationHoldError(
            "EVIDENCE_INCONSISTENT", f"evidence line {line_number} side is invalid"
        )
    try:
        opened = _aware_timestamp(record.get("ts_open_utc"), field="evidence.ts_open")
        baseline_closed = _aware_timestamp(
            record.get("baseline_closed_at_utc"), field="evidence.baseline_closed"
        )
        candidate_closed = _aware_timestamp(
            record.get("candidate_closed_at_utc"), field="evidence.candidate_closed"
        )
        entry = _positive(record.get("entry_price"), field="evidence.entry_price")
        initial_sl = _positive(
            record.get("initial_sl_price"), field="evidence.initial_sl_price"
        )
        risk = _positive(record.get("risk_per_unit"), field="evidence.risk_per_unit")
        baseline_exit = _positive(
            record.get("baseline_exit_price"), field="evidence.baseline_exit_price"
        )
        candidate_exit = _positive(
            record.get("candidate_exit_price"), field="evidence.candidate_exit_price"
        )
        baseline_r = _finite(
            record.get("baseline_realized_r"), field="evidence.baseline_realized_r"
        )
        candidate_r = _finite(
            record.get("candidate_realized_r"), field="evidence.candidate_realized_r"
        )
    except _MigrationHoldError as exc:
        raise _MigrationHoldError("EVIDENCE_INCONSISTENT", exc.detail) from exc
    if baseline_closed <= opened or candidate_closed <= opened:
        raise _MigrationHoldError(
            "EVIDENCE_INCONSISTENT",
            f"evidence line {line_number} timestamps are noncausal",
        )
    if not math.isclose(risk, abs(entry - initial_sl), rel_tol=1e-10, abs_tol=1e-10):
        raise _MigrationHoldError(
            "EVIDENCE_INCONSISTENT", f"evidence line {line_number} risk mismatch"
        )
    if (side == "long" and initial_sl >= entry) or (
        side == "short" and initial_sl <= entry
    ):
        raise _MigrationHoldError(
            "EVIDENCE_INCONSISTENT", f"evidence line {line_number} initial SL mismatch"
        )
    direction = 1.0 if side == "long" else -1.0
    expected_baseline_r = direction * (baseline_exit - entry) / risk
    expected_candidate_r = direction * (candidate_exit - entry) / risk
    if not math.isclose(
        baseline_r, expected_baseline_r, rel_tol=1e-8, abs_tol=1e-8
    ) or not math.isclose(
        candidate_r, expected_candidate_r, rel_tol=1e-8, abs_tol=1e-8
    ):
        raise _MigrationHoldError(
            "EVIDENCE_INCONSISTENT", f"evidence line {line_number} R values mismatch"
        )
    if record.get("baseline_close_reason") not in policy.eligible_close_reasons:
        raise _MigrationHoldError(
            "EVIDENCE_INCONSISTENT",
            f"evidence line {line_number} baseline reason is ineligible",
        )
    if record.get("candidate_close_reason") not in _CANDIDATE_REASONS:
        raise _MigrationHoldError(
            "EVIDENCE_INCONSISTENT",
            f"evidence line {line_number} candidate reason is invalid",
        )
    bars = record.get("bars_observed")
    if isinstance(bars, bool) or not isinstance(bars, int) or bars < 1:
        raise _MigrationHoldError(
            "EVIDENCE_INCONSISTENT", f"evidence line {line_number} bars are invalid"
        )


def _load_evidence_document(
    policy: E13Policy,
    *,
    expected_hash: str,
    expected_provenance: int | None,
    open_trade_ids: set[str],
) -> tuple[list[dict[str, Any]], str | None]:
    path = validate_e13_artifact_path(
        policy.shadow_evidence_path,
        field="E13 migration evidence",
    )
    if not path.exists():
        return [], None
    raw = secure_read_text(path, field="E13 migration evidence")
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    for line_number, line in enumerate(raw.splitlines(), start=1):
        if not line.strip():
            raise _MigrationHoldError(
                "EVIDENCE_INCONSISTENT",
                f"evidence line {line_number} is blank",
            )
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise _MigrationHoldError(
                "EVIDENCE_INCONSISTENT",
                f"evidence line {line_number} is invalid JSON",
            ) from exc
        if not isinstance(record, dict):
            raise _MigrationHoldError(
                "EVIDENCE_INCONSISTENT", f"evidence line {line_number} is not an object"
            )
        trade_id = str(record.get("trade_id") or "").strip()
        if not trade_id or trade_id in seen or trade_id in open_trade_ids:
            raise _MigrationHoldError(
                "EVIDENCE_INCONSISTENT",
                f"evidence line {line_number} trade identity is inconsistent",
            )
        seen.add(trade_id)
        _validate_evidence_record(
            record,
            policy=policy,
            expected_hash=expected_hash,
            expected_provenance=expected_provenance,
            line_number=line_number,
        )
        records.append(record)
    return records, raw


def _state_payload(state: dict[str, Any]) -> str:
    return json.dumps(state, sort_keys=True, indent=2) + "\n"


def _evidence_payload(records: list[dict[str, Any]]) -> str:
    return "".join(_canonical_json(record) + "\n" for record in records)


def _test_cutpoint(name: str) -> None:
    if os.environ.get("PA_TESTING") != "1":
        return
    if os.environ.get("PA_E13_MIGRATION_TEST_CUTPOINT") != name:
        return
    if os.environ.get("PA_E13_MIGRATION_TEST_CUTPOINT_ACTION") == "exception":
        raise RuntimeError(f"injected E13 migration failure: {name}")
    os.kill(os.getpid(), signal.SIGKILL)


def _ensure_exact_file(
    path: Path,
    payload: str,
    *,
    field: str,
    allowed_before: str | None,
    on_mutation: Any,
) -> None:
    validate_e13_artifact_path(path, field=field, create_parent=True)
    if path.exists():
        current = secure_read_text(path, field=field)
        if current == payload:
            return
        if allowed_before is None or current != allowed_before:
            raise ValueError(f"{field} changed outside the migration transaction")
    elif allowed_before is not None:
        raise ValueError(f"{field} disappeared during migration")
    atomic_write_text(path, payload, field=field, on_mutation=on_mutation)


def _ensure_backup(path: Path, payload: str, *, field: str, on_mutation: Any) -> None:
    validate_e13_artifact_path(path, field=field, create_parent=True)
    if path.exists():
        if secure_read_text(path, field=field) != payload:
            raise ValueError(f"{field} conflicts with the durable transaction")
        return
    atomic_write_text(path, payload, field=field, on_mutation=on_mutation)


def _read_audit_records() -> tuple[Path, list[dict[str, Any]]]:
    path = validate_e13_artifact_path(
        e13_policy_migration_audit_path(),
        field="E13 migration audit",
    )
    records: list[dict[str, Any]] = []
    if path.exists():
        raw = secure_read_text(path, field="E13 migration audit")
        seen: set[str] = set()
        for line_number, line in enumerate(raw.splitlines(), start=1):
            if not line.strip():
                raise ValueError(f"blank E13 migration audit line {line_number}")
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"invalid E13 migration audit JSON at line {line_number}"
                ) from exc
            if not isinstance(record, dict):
                raise ValueError("E13 migration audit record must be an object")
            migration_id = str(record.get("migration_id") or "")
            if not migration_id or migration_id in seen:
                raise ValueError("E13 migration audit id is missing or duplicated")
            seen.add(migration_id)
            records.append(record)
    return path, records


def _ensure_audit(transaction: dict[str, Any], *, on_mutation: Any) -> None:
    path, records = _read_audit_records()
    audit_record = transaction["audit_record"]
    existing = next(
        (
            record
            for record in records
            if record.get("migration_id") == transaction["migration_id"]
        ),
        None,
    )
    if existing is not None:
        if existing != audit_record:
            raise ValueError("E13 migration audit record conflicts with transaction")
        return
    atomic_write_text(
        path,
        _evidence_payload([*records, audit_record]),
        field="E13 migration audit",
        on_mutation=on_mutation,
    )


def _preflight_transaction(transaction: dict[str, Any]) -> None:
    backup_payloads = {
        transaction["state_backup_path"]: transaction["state_before"],
        transaction["manifest_path"]: transaction["manifest_payload"],
    }
    if transaction.get("evidence_before") is not None:
        backup_payloads[transaction["evidence_backup_path"]] = transaction[
            "evidence_before"
        ]
    for raw_path, payload in backup_payloads.items():
        path = validate_e13_artifact_path(
            raw_path,
            field="E13 migration backup preflight",
        )
        if path.exists() and secure_read_text(
            path, field="E13 migration backup preflight"
        ) != payload:
            raise _MigrationHoldError(
                "BACKUP_CONFLICT", f"migration backup conflicts: {path}"
            )
    _audit_path, audit_records = _read_audit_records()
    if any(
        record.get("migration_id") == transaction["migration_id"]
        for record in audit_records
    ):
        raise _MigrationHoldError(
            "AUDIT_CONFLICT",
            "migration id is already present while state remains legacy",
        )


def _validate_transaction(
    transaction: Any,
    *,
    policy: E13Policy,
    expected_old_hash: str,
    expected_new_hash: str,
    operator_reason: str,
) -> dict[str, Any]:
    if not isinstance(transaction, dict):
        raise ValueError("E13 migration transaction must be an object")
    expected = {
        "schema_version": 1,
        "kind": "e13_policy_provenance_migration",
        "config_path": str(policy.config_path),
        "state_path": str(policy.shadow_state_path),
        "evidence_path": str(policy.shadow_evidence_path),
        "expected_old_hash": expected_old_hash,
        "expected_new_hash": expected_new_hash,
        "operator_reason": operator_reason,
        "policy_provenance_version": policy.policy_provenance_version,
    }
    for key, value in expected.items():
        if transaction.get(key) != value:
            raise ValueError(f"E13 migration transaction {key} mismatch")
    required_strings = {
        "migration_id",
        "state_before",
        "state_after",
        "state_before_sha256",
        "state_after_sha256",
        "state_backup_path",
        "manifest_path",
        "manifest_payload",
    }
    if any(not isinstance(transaction.get(key), str) for key in required_strings):
        raise ValueError("E13 migration transaction payload is incomplete")
    for before_or_after in ("before", "after"):
        payload = transaction[f"state_{before_or_after}"]
        digest = transaction[f"state_{before_or_after}_sha256"]
        if _sha256_text(payload) != digest:
            raise ValueError("E13 migration transaction state digest mismatch")
    evidence_before = transaction.get("evidence_before")
    evidence_after = transaction.get("evidence_after")
    if (evidence_before is None) != (evidence_after is None):
        raise ValueError("E13 migration transaction evidence presence mismatch")
    if evidence_before is not None:
        if not isinstance(evidence_before, str) or not isinstance(evidence_after, str):
            raise ValueError("E13 migration transaction evidence payload is invalid")
        if _sha256_text(evidence_before) != transaction.get("evidence_before_sha256"):
            raise ValueError("E13 migration transaction evidence-before digest mismatch")
        if _sha256_text(evidence_after) != transaction.get("evidence_after_sha256"):
            raise ValueError("E13 migration transaction evidence-after digest mismatch")
        if not isinstance(transaction.get("evidence_backup_path"), str):
            raise ValueError("E13 migration transaction evidence backup is missing")
    if not isinstance(transaction.get("audit_record"), dict):
        raise ValueError("E13 migration transaction audit record is missing")
    identity = {
        "config_path": str(policy.config_path),
        "state_path": str(policy.shadow_state_path),
        "evidence_path": str(policy.shadow_evidence_path),
        "old_hash": expected_old_hash,
        "new_hash": expected_new_hash,
        "operator_reason": operator_reason,
        "state_before_sha256": transaction["state_before_sha256"],
        "evidence_before_sha256": transaction.get("evidence_before_sha256"),
    }
    migration_id = hashlib.sha256(_canonical_json(identity).encode()).hexdigest()
    if transaction["migration_id"] != migration_id:
        raise ValueError("E13 migration transaction id mismatch")
    backup_root = e13_policy_migration_root() / migration_id
    expected_paths = {
        "state_backup_path": str(backup_root / "state.before.json"),
        "manifest_path": str(backup_root / "manifest.json"),
        "evidence_backup_path": (
            str(backup_root / "evidence.before.jsonl")
            if evidence_before is not None
            else None
        ),
    }
    for key, value in expected_paths.items():
        if transaction.get(key) != value:
            raise ValueError(f"E13 migration transaction {key} is not canonical")
    audit_record = transaction["audit_record"]
    audit_expected = {
        "migration_id": migration_id,
        "operator_reason": operator_reason,
        "config_path": str(policy.config_path),
        "state_path": str(policy.shadow_state_path),
        "evidence_path": str(policy.shadow_evidence_path),
        "old_policy_hash_sha256": expected_old_hash,
        "new_policy_hash_sha256": expected_new_hash,
        "policy_provenance_version": policy.policy_provenance_version,
        "state_before_sha256": transaction["state_before_sha256"],
        "state_after_sha256": transaction["state_after_sha256"],
        "evidence_before_sha256": transaction.get("evidence_before_sha256"),
        "evidence_after_sha256": transaction.get("evidence_after_sha256"),
        "state_backup_path": expected_paths["state_backup_path"],
        "evidence_backup_path": expected_paths["evidence_backup_path"],
    }
    for key, value in audit_expected.items():
        if audit_record.get(key) != value:
            raise ValueError(f"E13 migration audit payload {key} mismatch")
    expected_manifest = json.dumps(audit_record, sort_keys=True, indent=2) + "\n"
    if transaction["manifest_payload"] != expected_manifest:
        raise ValueError("E13 migration backup manifest mismatch")
    return transaction


def _read_transaction(
    *,
    policy: E13Policy,
    expected_old_hash: str,
    expected_new_hash: str,
    operator_reason: str,
) -> dict[str, Any] | None:
    path = validate_e13_artifact_path(
        e13_policy_migration_transaction_path(),
        field="E13 policy migration transaction",
    )
    if not path.exists():
        return None
    try:
        transaction = json.loads(
            secure_read_text(path, field="E13 policy migration transaction")
        )
    except json.JSONDecodeError as exc:
        raise ValueError("invalid E13 policy migration transaction") from exc
    return _validate_transaction(
        transaction,
        policy=policy,
        expected_old_hash=expected_old_hash,
        expected_new_hash=expected_new_hash,
        operator_reason=operator_reason,
    )


def _complete_transaction(transaction: dict[str, Any], *, on_mutation: Any) -> None:
    state_backup = validate_e13_artifact_path(
        transaction["state_backup_path"],
        field="E13 migration state backup",
        create_parent=True,
    )
    _ensure_backup(
        state_backup,
        transaction["state_before"],
        field="E13 migration state backup",
        on_mutation=on_mutation,
    )
    evidence_before = transaction.get("evidence_before")
    if evidence_before is not None:
        evidence_backup = validate_e13_artifact_path(
            transaction["evidence_backup_path"],
            field="E13 migration evidence backup",
            create_parent=True,
        )
        _ensure_backup(
            evidence_backup,
            evidence_before,
            field="E13 migration evidence backup",
            on_mutation=on_mutation,
        )
    manifest = validate_e13_artifact_path(
        transaction["manifest_path"],
        field="E13 migration backup manifest",
        create_parent=True,
    )
    _ensure_backup(
        manifest,
        transaction["manifest_payload"],
        field="E13 migration backup manifest",
        on_mutation=on_mutation,
    )
    _test_cutpoint("after_backups")

    if evidence_before is not None:
        _ensure_exact_file(
            Path(transaction["evidence_path"]),
            transaction["evidence_after"],
            field="E13 migration evidence",
            allowed_before=evidence_before,
            on_mutation=on_mutation,
        )
    _test_cutpoint("after_evidence")
    _ensure_exact_file(
        Path(transaction["state_path"]),
        transaction["state_after"],
        field="E13 migration state",
        allowed_before=transaction["state_before"],
        on_mutation=on_mutation,
    )
    _test_cutpoint("after_state")
    _ensure_audit(transaction, on_mutation=on_mutation)
    _test_cutpoint("after_audit")
    durable_unlink(
        e13_policy_migration_transaction_path(),
        field="E13 policy migration transaction",
        on_mutation=on_mutation,
    )


def _build_transaction(
    *,
    policy: E13Policy,
    expected_old_hash: str,
    expected_new_hash: str,
    operator_reason: str,
    state_before: str,
    state_after: str,
    evidence_before: str | None,
    evidence_after: str | None,
    evidence_count: int,
) -> dict[str, Any]:
    identity = {
        "config_path": str(policy.config_path),
        "state_path": str(policy.shadow_state_path),
        "evidence_path": str(policy.shadow_evidence_path),
        "old_hash": expected_old_hash,
        "new_hash": expected_new_hash,
        "operator_reason": operator_reason,
        "state_before_sha256": _sha256_text(state_before),
        "evidence_before_sha256": (
            _sha256_text(evidence_before) if evidence_before is not None else None
        ),
    }
    migration_id = hashlib.sha256(_canonical_json(identity).encode()).hexdigest()
    backup_root = e13_policy_migration_root() / migration_id
    state_backup = backup_root / "state.before.json"
    evidence_backup = backup_root / "evidence.before.jsonl"
    manifest_path = backup_root / "manifest.json"
    started_at = datetime.now(UTC).isoformat()
    audit_record = {
        "schema_version": 1,
        "migration_id": migration_id,
        "kind": "e13_policy_provenance_migration",
        "completed_at_utc": started_at,
        "operator_reason": operator_reason,
        "config_path": str(policy.config_path),
        "state_path": str(policy.shadow_state_path),
        "evidence_path": str(policy.shadow_evidence_path),
        "old_policy_hash_sha256": expected_old_hash,
        "new_policy_hash_sha256": expected_new_hash,
        "policy_provenance_version": policy.policy_provenance_version,
        "state_before_sha256": _sha256_text(state_before),
        "state_after_sha256": _sha256_text(state_after),
        "evidence_before_sha256": (
            _sha256_text(evidence_before) if evidence_before is not None else None
        ),
        "evidence_after_sha256": (
            _sha256_text(evidence_after) if evidence_after is not None else None
        ),
        "evidence_records_migrated": evidence_count,
        "state_backup_path": str(state_backup),
        "evidence_backup_path": (
            str(evidence_backup) if evidence_before is not None else None
        ),
    }
    manifest_payload = json.dumps(audit_record, sort_keys=True, indent=2) + "\n"
    return {
        "schema_version": 1,
        "kind": "e13_policy_provenance_migration",
        "migration_id": migration_id,
        "started_at_utc": started_at,
        "operator_reason": operator_reason,
        "config_path": str(policy.config_path),
        "state_path": str(policy.shadow_state_path),
        "evidence_path": str(policy.shadow_evidence_path),
        "expected_old_hash": expected_old_hash,
        "expected_new_hash": expected_new_hash,
        "policy_provenance_version": policy.policy_provenance_version,
        "state_before": state_before,
        "state_after": state_after,
        "state_before_sha256": _sha256_text(state_before),
        "state_after_sha256": _sha256_text(state_after),
        "evidence_before": evidence_before,
        "evidence_after": evidence_after,
        "evidence_before_sha256": (
            _sha256_text(evidence_before) if evidence_before is not None else None
        ),
        "evidence_after_sha256": (
            _sha256_text(evidence_after) if evidence_after is not None else None
        ),
        "state_backup_path": str(state_backup),
        "evidence_backup_path": (
            str(evidence_backup) if evidence_before is not None else None
        ),
        "manifest_path": str(manifest_path),
        "manifest_payload": manifest_payload,
        "audit_record": audit_record,
    }


def _inspect_migration(
    *,
    policy: E13Policy,
    old_hash: str,
    new_hash: str,
    reason: str,
) -> dict[str, Any]:
    """Read and validate migration inputs without acquiring or creating a lease."""
    shadow_transaction = validate_e13_artifact_path(
        e13_transaction_path(),
        field="E13 recovery transaction",
    )
    if shadow_transaction.exists():
        raise _MigrationHoldError(
            "SHADOW_TRANSACTION_PENDING", str(shadow_transaction)
        )
    try:
        pending = _read_transaction(
            policy=policy,
            expected_old_hash=old_hash,
            expected_new_hash=new_hash,
            operator_reason=reason,
        )
    except ValueError as exc:
        raise _MigrationHoldError(
            "PENDING_MIGRATION_MISMATCH", str(exc)
        ) from exc
    if pending is not None:
        return {"kind": "pending", "transaction": pending}

    state_path = validate_e13_artifact_path(
        policy.shadow_state_path,
        field="E13 migration state",
    )
    if not state_path.exists():
        raise _MigrationHoldError("STATE_MISSING", str(state_path))
    try:
        state, state_before = _load_state_document(
            policy,
            expected_hash=old_hash,
            expected_provenance=None,
        )
    except _MigrationHoldError as legacy_error:
        try:
            state, _state_current = _load_state_document(
                policy,
                expected_hash=new_hash,
                expected_provenance=policy.policy_provenance_version,
            )
        except _MigrationHoldError as current_error:
            raise legacy_error from current_error
        records, _evidence_current = _load_evidence_document(
            policy,
            expected_hash=new_hash,
            expected_provenance=policy.policy_provenance_version,
            open_trade_ids=set(state["trades"]),
        )
        return {"kind": "already", "evidence_count": len(records)}

    records, evidence_before = _load_evidence_document(
        policy,
        expected_hash=old_hash,
        expected_provenance=None,
        open_trade_ids=set(state["trades"]),
    )
    state_after_document = dict(state)
    state_after_document["policy_hash_sha256"] = new_hash
    state_after_document[
        "policy_provenance_version"
    ] = policy.policy_provenance_version
    state_after = _state_payload(state_after_document)
    evidence_after_records = []
    for record in records:
        migrated = dict(record)
        migrated["policy_hash_sha256"] = new_hash
        migrated["policy_provenance_version"] = policy.policy_provenance_version
        evidence_after_records.append(migrated)
    evidence_after = (
        _evidence_payload(evidence_after_records)
        if evidence_before is not None
        else None
    )
    transaction = _build_transaction(
        policy=policy,
        expected_old_hash=old_hash,
        expected_new_hash=new_hash,
        operator_reason=reason,
        state_before=state_before,
        state_after=state_after,
        evidence_before=evidence_before,
        evidence_after=evidence_after,
        evidence_count=len(records),
    )
    _preflight_transaction(transaction)
    return {
        "kind": "ready",
        "transaction": transaction,
        "evidence_count": len(records),
    }


def _fingerprint_path(path: Path) -> dict[str, Any]:
    """Capture mutation-relevant metadata and content without following aliases."""
    try:
        info = path.lstat()
    except FileNotFoundError:
        return {"exists": False}
    fingerprint: dict[str, Any] = {
        "exists": True,
        "mode": stat.S_IMODE(info.st_mode),
        "uid": info.st_uid,
        "nlink": info.st_nlink,
        "size": info.st_size,
        "mtime_ns": info.st_mtime_ns,
        "device": info.st_dev,
        "inode": info.st_ino,
        "kind": (
            "regular"
            if stat.S_ISREG(info.st_mode)
            else "directory"
            if stat.S_ISDIR(info.st_mode)
            else "symlink"
            if stat.S_ISLNK(info.st_mode)
            else "other"
        ),
    }
    if stat.S_ISREG(info.st_mode):
        flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(
            os, "O_NOFOLLOW", 0
        )
        try:
            fd = os.open(path, flags)
            try:
                opened = os.fstat(fd)
                if (opened.st_dev, opened.st_ino) != (info.st_dev, info.st_ino):
                    fingerprint["content_sha256"] = "<changed-during-open>"
                else:
                    digest = hashlib.sha256()
                    while chunk := os.read(fd, 1024 * 1024):
                        digest.update(chunk)
                    fingerprint["content_sha256"] = digest.hexdigest()
            finally:
                os.close(fd)
        except OSError as exc:
            fingerprint["read_error"] = f"{type(exc).__name__}:{exc.errno}"
    return fingerprint


def _fingerprint_paths(paths: set[Path]) -> dict[str, dict[str, Any]]:
    return {
        str(path): _fingerprint_path(path)
        for path in sorted(paths, key=lambda candidate: str(candidate))
    }


def _observed_paths(policy: E13Policy) -> set[Path]:
    return {
        canonical_e13_data_root(),
        e13_global_lock_path(),
        e13_transaction_path(),
        e13_policy_migration_transaction_path(),
        e13_policy_migration_audit_path(),
        policy.shadow_state_path,
        policy.shadow_evidence_path,
    }


def _base_result(
    policy: E13Policy,
    *,
    expected_old_hash: str,
    expected_new_hash: str,
    legacy_hash: str,
    apply: bool,
) -> dict[str, Any]:
    return {
        "config": str(policy.config_path),
        "state_artifact": str(policy.shadow_state_path),
        "evidence_artifact": str(policy.shadow_evidence_path),
        "writer_lock_path": str(e13_global_lock_path()),
        "migration_transaction_path": str(e13_policy_migration_transaction_path()),
        "migration_audit_path": str(e13_policy_migration_audit_path()),
        "computed_legacy_hash": legacy_hash,
        "computed_new_hash": policy.policy_hash_sha256,
        "expected_old_hash": expected_old_hash,
        "expected_new_hash": expected_new_hash,
        "policy_provenance_version": policy.policy_provenance_version,
        "apply_requested": bool(apply),
        "dry_run": not apply,
        "network_calls": 0,
        "exchange_calls": 0,
    }


def migrate_e13_policy_provenance(
    *,
    config_path: str | Path = E13_DEFAULT_CONFIG_PATH,
    expected_old_hash: str,
    expected_new_hash: str,
    operator_reason: str,
    apply: bool = False,
) -> dict[str, Any]:
    """Inspect or explicitly apply the legacy-to-provenance E13 hash migration."""
    old_hash = _validated_hash(expected_old_hash, field="expected_old_hash")
    new_hash = _validated_hash(expected_new_hash, field="expected_new_hash")
    reason = _operator_reason(operator_reason)
    policy = load_e13_policy(config_path)
    legacy_hash = e13_legacy_semantic_policy_hash(policy)
    result = _base_result(
        policy,
        expected_old_hash=old_hash,
        expected_new_hash=new_hash,
        legacy_hash=legacy_hash,
        apply=apply,
    )
    if old_hash != legacy_hash:
        result.update(
            {
                "status": "HOLD_SEMANTIC_DRIFT_OR_OLD_HASH_MISMATCH",
                "fail_closed": True,
                "mutated_real_artifacts": False,
                "mutated_artifact_paths": [],
            }
        )
        return result
    if new_hash != policy.policy_hash_sha256:
        result.update(
            {
                "status": "HOLD_NEW_HASH_MISMATCH",
                "fail_closed": True,
                "mutated_real_artifacts": False,
                "mutated_artifact_paths": [],
            }
        )
        return result

    if not apply:
        paths = _observed_paths(policy)
        before = _fingerprint_paths(paths)
        initial_before = before
        try:
            inspection = _inspect_migration(
                policy=policy,
                old_hash=old_hash,
                new_hash=new_hash,
                reason=reason,
            )
        except _MigrationHoldError as exc:
            after = _fingerprint_paths(paths)
            result.update(
                {
                    "status": (
                        f"HOLD_{exc.code}"
                        if before == after
                        else "HOLD_CONCURRENT_CHANGE"
                    ),
                    "detail": exc.detail,
                    "fail_closed": True,
                    "static_validation_pass": False,
                    "ready_for_locked_apply": False,
                    "filesystem_fingerprint_before": before,
                    "filesystem_fingerprint_after": after,
                    "filesystem_unchanged": before == after,
                    "mutated_real_artifacts": False,
                    "mutated_artifact_paths": [],
                }
            )
            return result
        except ValueError as exc:
            after = _fingerprint_paths(paths)
            result.update(
                {
                    "status": (
                        "HOLD_STATIC_VALIDATION_ERROR"
                        if before == after
                        else "HOLD_CONCURRENT_CHANGE"
                    ),
                    "detail": str(exc),
                    "fail_closed": True,
                    "static_validation_pass": False,
                    "ready_for_locked_apply": False,
                    "filesystem_fingerprint_before": before,
                    "filesystem_fingerprint_after": after,
                    "filesystem_unchanged": before == after,
                    "mutated_real_artifacts": False,
                    "mutated_artifact_paths": [],
                }
            )
            return result
        transaction = inspection.get("transaction")
        if isinstance(transaction, dict):
            paths.update(
                Path(transaction[key])
                for key in (
                    "state_backup_path",
                    "manifest_path",
                )
            )
            if transaction.get("evidence_backup_path"):
                paths.add(Path(transaction["evidence_backup_path"]))
            before = _fingerprint_paths(paths)
        after = _fingerprint_paths(paths)
        initial_unchanged = all(after.get(path) == value for path, value in initial_before.items())
        unchanged = initial_unchanged and before == after
        result.update(
            {
                "status": (
                    "HOLD_REQUIRES_APPLY_LOCK"
                    if unchanged
                    else "HOLD_CONCURRENT_CHANGE"
                ),
                "fail_closed": True,
                "static_validation_pass": unchanged,
                "ready_for_locked_apply": unchanged,
                "observed_migration_state": inspection["kind"],
                "filesystem_fingerprint_before": before,
                "filesystem_fingerprint_after": after,
                "filesystem_unchanged": unchanged,
                "mutated_real_artifacts": False,
                "mutated_artifact_paths": [],
            }
        )
        if isinstance(transaction, dict):
            result.update(
                {
                    "migration_id": transaction["migration_id"],
                    "evidence_records_migrated": transaction["audit_record"][
                        "evidence_records_migrated"
                    ],
                    "state_backup_path": transaction["state_backup_path"],
                    "evidence_backup_path": transaction["evidence_backup_path"],
                }
            )
        else:
            result["evidence_records_migrated"] = inspection.get("evidence_count", 0)
        return result

    mutations: set[Path] = set()

    def _note_mutation(path: Path) -> None:
        mutations.add(path)

    try:
        with E13ShadowLease(policy.shadow_state_path):
            inspection = _inspect_migration(
                policy=policy,
                old_hash=old_hash,
                new_hash=new_hash,
                reason=reason,
            )
            if inspection["kind"] == "already":
                result.update(
                    {
                        "status": "ALREADY_MIGRATED",
                        "fail_closed": False,
                        "evidence_records_migrated": inspection["evidence_count"],
                        "mutated_real_artifacts": False,
                        "mutated_artifact_paths": [],
                    }
                )
                return result
            transaction = inspection["transaction"]
            if inspection["kind"] == "pending":
                _complete_transaction(transaction, on_mutation=_note_mutation)
                result.update(
                    {
                        "status": "RECOVERED_AND_MIGRATED",
                        "fail_closed": False,
                        "migration_id": transaction["migration_id"],
                        "evidence_records_migrated": transaction["audit_record"][
                            "evidence_records_migrated"
                        ],
                    }
                )
            else:
                result.update(
                    {
                        "migration_id": transaction["migration_id"],
                        "evidence_records_migrated": inspection["evidence_count"],
                        "state_backup_path": transaction["state_backup_path"],
                        "evidence_backup_path": transaction["evidence_backup_path"],
                    }
                )
                atomic_write_text(
                    e13_policy_migration_transaction_path(),
                    _canonical_json(transaction) + "\n",
                    field="E13 policy migration transaction",
                    on_mutation=_note_mutation,
                )
                _test_cutpoint("after_transaction")
                _complete_transaction(transaction, on_mutation=_note_mutation)
                result.update({"status": "MIGRATED", "fail_closed": False})
    except E13ShadowBusyError as exc:
        result.update(
            {
                "status": "HOLD_WRITER_BUSY",
                "fail_closed": True,
                "retryable": True,
                "writer_lock_path": str(exc.lock_path),
                "mutated_real_artifacts": False,
                "mutated_artifact_paths": [],
            }
        )
        return result
    except _MigrationHoldError as exc:
        result.update(
            {
                "status": f"HOLD_{exc.code}",
                "detail": exc.detail,
                "fail_closed": True,
                "mutated_real_artifacts": bool(mutations),
                "mutated_artifact_paths": sorted(str(path) for path in mutations),
            }
        )
        return result
    except Exception as exc:
        if mutations:
            raise E13PolicyMigrationMutationError(exc, mutations) from exc
        raise

    result["mutated_real_artifacts"] = bool(mutations)
    result["mutated_artifact_paths"] = sorted(str(path) for path in mutations)
    return result


__all__ = [
    "E13PolicyMigrationMutationError",
    "migrate_e13_policy_provenance",
]
