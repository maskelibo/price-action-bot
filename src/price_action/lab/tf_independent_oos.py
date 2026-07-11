"""Preregistered, independent TF out-of-sample evidence producer.

The module has two deliberately separate phases:

* ``create_preregistration`` freezes the discovery artifact, strategy source,
  historical pool prefixes, variants, thresholds, and a future holdout start.
* ``evaluate_preregistration`` examines only trades that begin after that
  holdout start.  Any mutation of the frozen historical prefix, missing
  perturbation pool, weak sample, or failed robustness check yields a
  content-addressed ``HOLD`` status and never promotion evidence.

There is no exchange, credential, daemon, launchd, or order path in this
module.  The sole positive artifact is the narrow ``tf-independent-oos-v2``
contract consumed by :mod:`price_action.lab.tf_shadow_promotion`.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import itertools
import json
import math
import os
import pickle
import re
import resource
import subprocess
import sys
import tempfile
from collections.abc import Iterable
from contextlib import suppress
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml

DISCOVERY_SCHEMA = "tf-robustness-v2"
DISCOVERY_VERDICT = "DESCRIPTIVE_SCREEN_PASS"
DISCOVERY_CLASS = "DESCRIPTIVE_REUSED_HISTORY"
PREREG_SCHEMA = "tf-independent-oos-prereg-v2"
EVIDENCE_SCHEMA = "tf-independent-oos-v2"
STATUS_SCHEMA = "tf-independent-oos-status-v1"
PROTOCOL_SCHEMA = "tf-independent-oos-protocol-v2"
POOL_PROVENANCE_SCHEMA = "tf-pool-provenance-chain-v2"
CANONICAL_EVALUATOR_CONTRACT = "TF_CANONICAL_EVALUATOR_V2"
POOL_BUILDER_REPLAY_CONTRACT = "TF_POOL_BUILDER_REPLAY_V1"
AUTHORIZATION_SCOPE = "SIGNAL_ONLY_SHADOW"
TRUSTED_EVALUATOR_PATH = "scripts/tf_independent_oos_runner.py"

SUPPORTED_TFS = frozenset({"5m", "15m", "30m", "1h", "4h", "1d"})
REQUIRED_POOL_FIELDS = frozenset({"entry_ts", "exit_ts", "R", "symbol", "strategy", "regime"})
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")
_SLUG_RE = re.compile(r"^[a-z][a-z0-9_]{2,63}$")
_TF_IN_NAME_RE = re.compile(r"(?:^|[_-])(5m|15m|30m|1h|4h|1d)(?:[_-]|$)")
_PREREG_NAME_RE = re.compile(
    r"^(?P<strategy>[a-z][a-z0-9_]{2,63})-"
    r"(?P<tf>5m|15m|30m|1h|4h|1d)-oos-prereg-"
    r"(?P<stamp>\d{8}T\d{6}\.\d{6}Z)-(?P<sha>[0-9a-f]{12})\.json$"
)
_MAX_JSON_BYTES = 8 * 1024 * 1024
_MAX_PROVENANCE_BYTES = 32 * 1024 * 1024
_MAX_POOL_BYTES = 512 * 1024 * 1024
_MAX_POOL_ROWS = 2_000_000
_MAX_POOL_FIELDS = 128
_MAX_POOL_STRING_BYTES = 16 * 1024
_BUILDER_TIMEOUT_SECONDS = 30
_SANDBOX_EXEC = Path("/usr/bin/sandbox-exec")


class OOSContractError(ValueError):
    """Input cannot satisfy the independent-OOS evidence contract."""


class ImmutableConflictError(OOSContractError):
    """A content-addressed path already contains different bytes."""


def _validate_authorization_policy(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != {
        "scope",
        "live_order_authorized",
        "principal_authorization",
    }:
        raise OOSContractError("protocol authorization has an invalid shape")
    if value.get("scope") != AUTHORIZATION_SCOPE or value.get("live_order_authorized") is not False:
        raise OOSContractError(
            "protocol authorization must remain signal-only with live orders false"
        )
    principal = value.get("principal_authorization")
    if not isinstance(principal, dict) or set(principal) != {
        "algorithm",
        "public_key_path",
        "public_key_sha256",
        "max_validity_seconds",
    }:
        raise OOSContractError("principal authorization policy has an invalid shape")
    public_key_path = principal.get("public_key_path")
    validity = principal.get("max_validity_seconds")
    if principal.get("algorithm") != "Ed25519":
        raise OOSContractError("principal authorization algorithm must be Ed25519")
    if (
        not isinstance(public_key_path, str)
        or not public_key_path
        or Path(public_key_path).is_absolute()
        or ".." in Path(public_key_path).parts
    ):
        raise OOSContractError("principal public key path must be safe and repo-relative")
    if not _SHA_RE.fullmatch(str(principal.get("public_key_sha256", ""))):
        raise OOSContractError("principal public key sha256 is invalid")
    if isinstance(validity, bool) or not isinstance(validity, int) or not 60 <= validity <= 604800:
        raise OOSContractError("principal authorization validity must be 60..604800 seconds")
    return json.loads(json.dumps(value, sort_keys=True))


@dataclass(frozen=True)
class OOSProtocol:
    """All thresholds fixed before the holdout begins."""

    min_oos_calendar_days: int = 90
    min_candidate_trades: int = 100
    min_baseline_trades: int = 100
    min_common_symbols: int = 5
    walk_forward_folds: int = 3
    min_trades_per_walk_forward_fold: int = 20
    min_regimes: int = 2
    min_trades_per_regime: int = 15
    min_common_months: int = 6
    min_parameter_variants: int = 2
    min_candidate_mean_r: float = 0.0
    min_candidate_vs_baseline_mean_r: float = 0.0
    min_positive_walk_forward_share: float = 1.0
    min_symbol_out_mean_r: float = 0.0
    min_regime_mean_r: float = 0.0
    min_variant_expectancy_retention: float = 0.50
    family_wise_alpha: float = 0.05
    multiple_testing_method: str = "bonferroni"
    family_size: int = 20
    permutation_samples: int = 20_000
    permutation_seed: int = 20260711

    def validate(self) -> None:
        integer_minimums = {
            "min_oos_calendar_days": self.min_oos_calendar_days,
            "min_candidate_trades": self.min_candidate_trades,
            "min_baseline_trades": self.min_baseline_trades,
            "min_common_symbols": self.min_common_symbols,
            "walk_forward_folds": self.walk_forward_folds,
            "min_trades_per_walk_forward_fold": self.min_trades_per_walk_forward_fold,
            "min_regimes": self.min_regimes,
            "min_trades_per_regime": self.min_trades_per_regime,
            "min_common_months": self.min_common_months,
            "min_parameter_variants": self.min_parameter_variants,
            "family_size": self.family_size,
            "permutation_samples": self.permutation_samples,
        }
        bad = [
            name
            for name, value in integer_minimums.items()
            if isinstance(value, bool) or not isinstance(value, int) or value < 1
        ]
        if bad:
            raise OOSContractError(f"protocol integer values must be >= 1: {bad}")
        if self.min_oos_calendar_days < 90:
            raise OOSContractError("min_oos_calendar_days cannot be relaxed below 90")
        if self.walk_forward_folds < 3:
            raise OOSContractError("walk_forward_folds cannot be relaxed below 3")
        if self.min_regimes < 2:
            raise OOSContractError("min_regimes cannot be relaxed below 2")
        unit_interval = {
            "min_positive_walk_forward_share": self.min_positive_walk_forward_share,
            "min_variant_expectancy_retention": self.min_variant_expectancy_retention,
            "family_wise_alpha": self.family_wise_alpha,
        }
        bad = [
            name
            for name, value in unit_interval.items()
            if isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(float(value))
            or not 0 < float(value) <= 1
        ]
        if bad:
            raise OOSContractError(f"protocol probabilities must be in (0, 1]: {bad}")
        if self.multiple_testing_method != "bonferroni":
            raise OOSContractError("only fail-closed bonferroni multiple testing is supported")
        finite_thresholds = (
            self.min_candidate_mean_r,
            self.min_candidate_vs_baseline_mean_r,
            self.min_symbol_out_mean_r,
            self.min_regime_mean_r,
        )
        if any(
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(float(value))
            for value in finite_thresholds
        ):
            raise OOSContractError("all expectancy thresholds must be finite numbers")


def load_protocol(path: Path | None = None) -> OOSProtocol:
    """Load and strictly validate the preregistration protocol YAML."""

    if path is None:
        protocol = OOSProtocol()
        protocol.validate()
        return protocol
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise OOSContractError(f"protocol must be a regular non-symlink file: {path}")
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("schema_version") != PROTOCOL_SCHEMA:
        raise OOSContractError(f"protocol schema_version must be {PROTOCOL_SCHEMA!r}")
    expected_top_level = {
        "schema_version",
        "minimums",
        "thresholds",
        "multiple_testing",
        "permutation",
        "authorization",
    }
    if set(payload) != expected_top_level:
        raise OOSContractError("protocol contains missing or unknown top-level fields")
    minimums = payload.get("minimums")
    thresholds = payload.get("thresholds")
    multiple = payload.get("multiple_testing")
    permutation = payload.get("permutation")
    authorization = payload.get("authorization")
    if not all(
        isinstance(value, dict)
        for value in (minimums, thresholds, multiple, permutation, authorization)
    ):
        raise OOSContractError("protocol sections must all be objects")
    _validate_authorization_policy(authorization)
    expected_section_keys = {
        "minimums": {
            "oos_calendar_days",
            "candidate_trades",
            "baseline_trades",
            "common_symbols",
            "walk_forward_folds",
            "trades_per_walk_forward_fold",
            "regimes",
            "trades_per_regime",
            "common_months",
            "parameter_variants",
        },
        "thresholds": {
            "min_candidate_mean_r",
            "min_candidate_vs_baseline_mean_r",
            "min_positive_walk_forward_share",
            "min_symbol_out_mean_r",
            "min_regime_mean_r",
            "min_variant_expectancy_retention",
            "family_wise_alpha",
        },
        "multiple_testing": {"method", "family_size"},
        "permutation": {"method", "samples", "seed"},
    }
    for name, expected in expected_section_keys.items():
        if set(payload[name]) != expected:
            raise OOSContractError(f"protocol.{name} contains missing or unknown fields")
    if permutation.get("method") != "monthly_paired_mean_r_sign_flip":
        raise OOSContractError("unsupported permutation method")
    try:
        protocol = OOSProtocol(
            min_oos_calendar_days=minimums["oos_calendar_days"],
            min_candidate_trades=minimums["candidate_trades"],
            min_baseline_trades=minimums["baseline_trades"],
            min_common_symbols=minimums["common_symbols"],
            walk_forward_folds=minimums["walk_forward_folds"],
            min_trades_per_walk_forward_fold=minimums["trades_per_walk_forward_fold"],
            min_regimes=minimums["regimes"],
            min_trades_per_regime=minimums["trades_per_regime"],
            min_common_months=minimums["common_months"],
            min_parameter_variants=minimums["parameter_variants"],
            min_candidate_mean_r=thresholds["min_candidate_mean_r"],
            min_candidate_vs_baseline_mean_r=thresholds["min_candidate_vs_baseline_mean_r"],
            min_positive_walk_forward_share=thresholds["min_positive_walk_forward_share"],
            min_symbol_out_mean_r=thresholds["min_symbol_out_mean_r"],
            min_regime_mean_r=thresholds["min_regime_mean_r"],
            min_variant_expectancy_retention=thresholds["min_variant_expectancy_retention"],
            family_wise_alpha=thresholds["family_wise_alpha"],
            multiple_testing_method=multiple["method"],
            family_size=multiple["family_size"],
            permutation_samples=permutation["samples"],
            permutation_seed=permutation["seed"],
        )
    except KeyError as exc:
        raise OOSContractError(f"protocol is missing required field {exc}") from exc
    protocol.validate()
    return protocol


def _load_protocol_authorization(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise OOSContractError("protocol root must be an object")
    return _validate_authorization_policy(payload.get("authorization"))


def _utc(value: datetime | str, field: str) -> datetime:
    try:
        if isinstance(value, datetime):
            parsed = value
        elif isinstance(value, str):
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        else:
            raise TypeError
    except (TypeError, ValueError, AttributeError) as exc:
        raise OOSContractError(f"{field} is not a valid ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise OOSContractError(f"{field} must include a timezone")
    return parsed.astimezone(UTC)


def _sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_json(payload: dict[str, Any]) -> bytes:
    return (json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode()


def _repo_relative_file(repo_root: Path, path: Path, label: str) -> tuple[Path, str]:
    """Resolve one regular file and return its stable repo-relative identity."""

    root = Path(repo_root).resolve()
    candidate = Path(path).expanduser()
    if candidate.is_symlink() or not candidate.is_file():
        raise OOSContractError(f"{label} must be a regular non-symlink file: {candidate}")
    resolved = candidate.resolve()
    try:
        relative = resolved.relative_to(root)
    except ValueError as exc:
        raise OOSContractError(f"{label} must live inside repo_root: {resolved}") from exc
    return resolved, str(relative)


def _pinned_repo_file(repo_root: Path, value: Any, label: str) -> Path:
    if not isinstance(value, str) or not value or Path(value).is_absolute():
        raise OOSContractError(f"{label} must be a non-empty repo-relative path")
    root = Path(repo_root).resolve()
    path = (root / value).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise OOSContractError(f"{label} escapes repo_root") from exc
    if path.is_symlink() or not path.is_file():
        raise OOSContractError(f"{label} is missing or unsafe: {value}")
    return path


def _sha256_file_prefix(path: Path, length: int) -> str:
    if isinstance(length, bool) or not isinstance(length, int) or length < 0:
        raise OOSContractError("content prefix length must be a non-negative integer")
    digest = hashlib.sha256()
    remaining = length
    with Path(path).open("rb") as handle:
        while remaining:
            chunk = handle.read(min(1024 * 1024, remaining))
            if not chunk:
                raise OOSContractError(f"file is shorter than its pinned content prefix: {path}")
            digest.update(chunk)
            remaining -= len(chunk)
    return digest.hexdigest()


def _atomic_replace(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temp_name, 0o600)
        os.replace(temp_name, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        with suppress(FileNotFoundError):
            os.unlink(temp_name)


def _evidence_payload_sha(payload: dict[str, Any]) -> str:
    clone = json.loads(json.dumps(payload, allow_nan=False))
    producer = clone.get("producer")
    if isinstance(producer, dict):
        producer.pop("payload_sha256", None)
    return _sha256_bytes(_canonical_json(clone))


def _atomic_content_write(path: Path, raw: bytes) -> bool:
    if path.exists():
        if path.is_symlink() or not path.is_file() or path.read_bytes() != raw:
            raise ImmutableConflictError(f"immutable output conflict: {path}")
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temp_name, 0o600)
        try:
            os.link(temp_name, path)
        except FileExistsError:
            if path.is_symlink() or not path.is_file() or path.read_bytes() != raw:
                raise ImmutableConflictError(
                    f"concurrent immutable output conflict: {path}"
                ) from None
            return False
        return True
    finally:
        with suppress(FileNotFoundError):
            os.unlink(temp_name)


def _load_json_file(path: Path, label: str) -> tuple[dict[str, Any], bytes]:
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise OOSContractError(f"{label} must be a regular non-symlink file: {path}")
    raw = path.read_bytes()
    if len(raw) > _MAX_JSON_BYTES:
        raise OOSContractError(f"{label} exceeds {_MAX_JSON_BYTES} bytes")
    try:
        payload = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise OOSContractError(f"{label} is not valid UTF-8 JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise OOSContractError(f"{label} JSON root must be an object")
    return payload, raw


def _infer_tf(path: Path) -> str | None:
    match = _TF_IN_NAME_RE.search(path.stem)
    return match.group(1) if match else None


_ALLOWED_POOL_PICKLE_GLOBALS = frozenset(
    {
        ("datetime", "datetime"),
        ("datetime", "timedelta"),
        ("datetime", "timezone"),
        ("pandas._libs.tslibs.timestamps", "_unpickle_timestamp"),
    }
)


class _RestrictedPoolUnpickler(pickle.Unpickler):
    """Decode legacy pools without granting arbitrary pickle imports."""

    def find_class(self, module: str, name: str) -> Any:
        if (module, name) not in _ALLOWED_POOL_PICKLE_GLOBALS:
            raise pickle.UnpicklingError(f"forbidden pool pickle global: {module}.{name}")
        return super().find_class(module, name)


def _load_pool(path: Path, *, strategy: str, timeframe: str, label: str) -> pd.DataFrame:
    path = Path(path).expanduser()
    if path.is_symlink() or not path.is_file():
        raise OOSContractError(f"{label} pool must be a regular non-symlink file: {path}")
    size = path.stat().st_size
    if size < 1 or size > _MAX_POOL_BYTES:
        raise OOSContractError(
            f"{label} pool byte size must be in [1, {_MAX_POOL_BYTES}]: {size}"
        )
    inferred = _infer_tf(path)
    if inferred != timeframe:
        raise OOSContractError(
            f"{label} pool filename timeframe mismatch: expected={timeframe!r}, inferred={inferred!r}"
        )
    try:
        with path.open("rb") as handle:
            rows = _RestrictedPoolUnpickler(handle).load()
    except Exception as exc:
        raise OOSContractError(f"{label} pool cannot be loaded: {exc}") from exc
    if not isinstance(rows, list) or not rows:
        raise OOSContractError(f"{label} pool must contain a non-empty list")
    if len(rows) > _MAX_POOL_ROWS:
        raise OOSContractError(f"{label} pool exceeds {_MAX_POOL_ROWS} rows")
    selected: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise OOSContractError(f"{label} pool row {index} is not an object")
        if len(row) > _MAX_POOL_FIELDS:
            raise OOSContractError(
                f"{label} pool row {index} exceeds {_MAX_POOL_FIELDS} fields"
            )
        for key, value in row.items():
            if not isinstance(key, str) or len(key.encode("utf-8")) > 256:
                raise OOSContractError(f"{label} pool row {index} has an invalid key")
            if isinstance(value, str) and len(value.encode("utf-8")) > _MAX_POOL_STRING_BYTES:
                raise OOSContractError(
                    f"{label} pool row {index}.{key} exceeds the string cap"
                )
            if not isinstance(
                value,
                (str, int, float, bool, type(None), datetime, pd.Timestamp),
            ):
                raise OOSContractError(
                    f"{label} pool row {index}.{key} contains nested/unsupported data"
                )
        if "strategy" not in row:
            raise OOSContractError(f"{label} pool row {index} is missing strategy")
        if row.get("strategy") != strategy:
            continue
        missing = REQUIRED_POOL_FIELDS.difference(row)
        if missing:
            raise OOSContractError(f"{label} strategy row {index} missing fields {sorted(missing)}")
        if isinstance(row.get("R"), bool):
            raise OOSContractError(f"{label} strategy row {index} has boolean R")
        selected.append({**row, "side": row.get("side")})
    if not selected:
        raise OOSContractError(f"{label} pool has no rows for strategy {strategy!r}")
    frame = pd.DataFrame(selected)
    frame["entry_ts"] = pd.to_datetime(frame["entry_ts"], utc=True, errors="coerce")
    frame["exit_ts"] = pd.to_datetime(frame["exit_ts"], utc=True, errors="coerce")
    frame["R"] = pd.to_numeric(frame["R"], errors="coerce")
    if bool((frame["entry_ts"].isna() | frame["exit_ts"].isna()).any()):
        raise OOSContractError(f"{label} pool contains invalid timestamps")
    if bool((frame["exit_ts"] < frame["entry_ts"]).any()):
        raise OOSContractError(f"{label} pool contains negative holding periods")
    if not bool(np.isfinite(frame["R"].to_numpy(dtype=float)).all()):
        raise OOSContractError(f"{label} pool contains non-finite R")
    for field in ("symbol", "regime"):
        valid = frame[field].map(lambda value: isinstance(value, str) and bool(value.strip()))
        if not bool(valid.all()):
            raise OOSContractError(f"{label} pool contains empty/invalid {field}")
        frame[field] = frame[field].str.strip()
    duplicate_cols = ["entry_ts", "exit_ts", "symbol", "side", "regime"]
    if bool(frame.duplicated(duplicate_cols, keep=False).any()):
        raise OOSContractError(f"{label} pool contains duplicate strategy rows")
    return frame.sort_values(["entry_ts", "exit_ts", "symbol"], kind="stable").reset_index(
        drop=True
    )


def _row_fingerprint(frame: pd.DataFrame) -> str:
    records = []
    for row in frame.itertuples(index=False):
        records.append(
            {
                "R": float(row.R).hex(),
                "entry_ts": row.entry_ts.isoformat(),
                "exit_ts": row.exit_ts.isoformat(),
                "regime": row.regime,
                "side": row.side,
                "strategy": row.strategy,
                "symbol": row.symbol,
            }
        )
    return _sha256_bytes(json.dumps(records, sort_keys=True, separators=(",", ":")).encode())


def _default_provenance_path(pool_path: Path) -> Path:
    return Path(f"{Path(pool_path)}.provenance.json")


def _normalise_parameters(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or not value:
        raise OOSContractError(f"{label} must be a non-empty object")
    if any(
        not isinstance(key, str) or re.fullmatch(r"[A-Za-z][A-Za-z0-9_.-]{0,63}", key) is None
        for key in value
    ):
        raise OOSContractError(f"{label} contains an unsafe parameter name")
    try:
        encoded = json.dumps(value, sort_keys=True, allow_nan=False, separators=(",", ":"))
        normalised = json.loads(encoded)
    except (TypeError, ValueError) as exc:
        raise OOSContractError(f"{label} must contain finite JSON values") from exc
    if not isinstance(normalised, dict):  # pragma: no cover - guarded above
        raise OOSContractError(f"{label} must be an object")
    return normalised


def _normalise_parameter_identity(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise OOSContractError("parameter_identity must be an object")
    family = value.get("family")
    role = value.get("role")
    logical_variant_of = value.get("variant_of")
    if not isinstance(family, str) or re.fullmatch(r"[a-z][a-z0-9_.-]{2,95}", family) is None:
        raise OOSContractError("parameter_identity.family is invalid")
    if role not in {"candidate", "baseline", "variant"}:
        raise OOSContractError("parameter_identity.role is invalid")
    if logical_variant_of is not None and (
        not isinstance(logical_variant_of, str)
        or re.fullmatch(r"[a-z][a-z0-9_.-]{2,127}", logical_variant_of) is None
    ):
        raise OOSContractError("parameter_identity.variant_of is invalid")
    parameters = _normalise_parameters(value.get("parameters"), "parameter_identity.parameters")
    declared_delta = value.get("declared_delta", {})
    if not isinstance(declared_delta, dict):
        raise OOSContractError("parameter_identity.declared_delta must be an object")
    try:
        declared_delta = json.loads(
            json.dumps(declared_delta, sort_keys=True, allow_nan=False, separators=(",", ":"))
        )
    except (TypeError, ValueError) as exc:
        raise OOSContractError("parameter_identity.declared_delta must be finite JSON") from exc
    if role == "variant" and logical_variant_of is None:
        raise OOSContractError("variant parameter identity must declare variant_of")
    if role != "variant" and (logical_variant_of is not None or declared_delta):
        raise OOSContractError("only a variant may declare variant_of/declared_delta")
    return {
        "family": family,
        "role": role,
        "parameters": parameters,
        "variant_of": logical_variant_of,
        "declared_delta": declared_delta,
    }


def _provenance_entry_sha(entry: dict[str, Any]) -> str:
    unsigned = dict(entry)
    unsigned.pop("entry_sha256", None)
    return _sha256_bytes(_canonical_json(unsigned))


def _provenance_prefix_sha(entries: list[dict[str, Any]]) -> str:
    return _sha256_bytes(
        (
            json.dumps(entries, sort_keys=True, ensure_ascii=False, separators=(",", ":")) + "\n"
        ).encode()
    )


def _sbpl_literal(path: Path) -> str:
    return str(Path(path).resolve()).replace("\\", "\\\\").replace('"', '\\"')


def _builder_sandbox_profile(
    *,
    repo_root: Path,
    python_path: Path,
    builder_path: Path,
    raw_snapshot_path: Path,
    output_path: Path,
) -> str:
    """macOS Seatbelt profile for deterministic pool-builder replay."""

    runtime_roots = {
        Path(sys.base_prefix).resolve(),
        Path(sys.base_exec_prefix).resolve(),
        Path(sys.exec_prefix).resolve(),
        Path(sys.prefix).resolve(),
    }
    lines = [
        "(version 1)",
        "(allow default)",
        "(deny network*)",
        "(deny file-write*)",
        "(deny process-exec)",
        # Builders execute from an exact temporary copy.  User/repository
        # files are unreadable except for Python's pinned runtime roots, so an
        # absolute-path side input cannot silently influence the pool.
        f'(deny file-read* (subpath "{_sbpl_literal(Path.home())}"))',
        f'(deny file-read* (subpath "{_sbpl_literal(repo_root)}"))',
    ]
    lines.extend(
        f'(allow file-read* (subpath "{_sbpl_literal(path)}"))'
        for path in sorted(runtime_roots, key=str)
    )
    lines.extend(
        (
            f'(allow process-exec (literal "{_sbpl_literal(python_path)}"))',
            f'(allow file-read* (literal "{_sbpl_literal(python_path)}"))',
            f'(allow file-read* (literal "{_sbpl_literal(builder_path)}"))',
            f'(allow file-read* (literal "{_sbpl_literal(raw_snapshot_path)}"))',
            f'(allow file-write* (literal "{_sbpl_literal(output_path)}"))',
        )
    )
    return "\n".join(lines)


def _subprocess_resource_limits() -> None:
    resource.setrlimit(resource.RLIMIT_CPU, (_BUILDER_TIMEOUT_SECONDS, _BUILDER_TIMEOUT_SECONDS))
    resource.setrlimit(resource.RLIMIT_FSIZE, (_MAX_POOL_BYTES, _MAX_POOL_BYTES))
    resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))
    with suppress(ValueError):
        resource.setrlimit(resource.RLIMIT_AS, (4 * 1024**3, 4 * 1024**3))


def _run_pool_builder_replay(
    *,
    repo_root: Path,
    builder_path: Path,
    raw_ohlcv_path: Path,
    raw_prefix_bytes: int,
    strategy: str,
    timeframe: str,
    parameters: dict[str, Any],
) -> tuple[bytes, pd.DataFrame, dict[str, Any]]:
    """Run the frozen builder from only raw-prefix bytes and frozen params."""

    repo_root = Path(repo_root).resolve()
    builder_path, builder_rel = _repo_relative_file(repo_root, builder_path, "pool builder")
    raw_ohlcv_path, raw_rel = _repo_relative_file(
        repo_root, raw_ohlcv_path, "raw OHLCV source"
    )
    if not _SANDBOX_EXEC.is_file() or _SANDBOX_EXEC.is_symlink():
        raise OOSContractError("macOS sandbox-exec is required for hermetic pool replay")
    if (
        isinstance(raw_prefix_bytes, bool)
        or not isinstance(raw_prefix_bytes, int)
        or raw_prefix_bytes < 1
        or raw_prefix_bytes > raw_ohlcv_path.stat().st_size
    ):
        raise OOSContractError("raw OHLCV replay prefix length is invalid")
    parameters = _normalise_parameters(parameters, "builder replay parameters")
    parameter_json = json.dumps(
        parameters, sort_keys=True, allow_nan=False, separators=(",", ":")
    )
    with tempfile.TemporaryDirectory(prefix="tf-pool-replay-") as temp_name:
        temp = Path(temp_name)
        builder_snapshot = temp / "builder_snapshot.py"
        raw_snapshot = temp / "raw_snapshot.bin"
        output = temp / f"replay_{timeframe}_pool.pkl"
        with builder_snapshot.open("wb") as target:
            target.write(builder_path.read_bytes())
            target.flush()
            os.fsync(target.fileno())
        with raw_ohlcv_path.open("rb") as source, raw_snapshot.open("wb") as target:
            remaining = raw_prefix_bytes
            while remaining:
                chunk = source.read(min(1024 * 1024, remaining))
                if not chunk:
                    raise OOSContractError("raw OHLCV source ended before replay prefix")
                target.write(chunk)
                remaining -= len(chunk)
            target.flush()
            os.fsync(target.fileno())
        python_path = Path(sys.executable).resolve()
        profile = _builder_sandbox_profile(
            repo_root=repo_root,
            python_path=python_path,
            builder_path=builder_snapshot,
            raw_snapshot_path=raw_snapshot,
            output_path=output,
        )
        command = [
            str(_SANDBOX_EXEC),
            "-p",
            profile,
            str(python_path),
            "-I",
            str(builder_snapshot),
            "--tf-oos-replay-v1",
            "--raw-snapshot",
            str(raw_snapshot),
            "--output",
            str(output),
            "--strategy",
            strategy,
            "--timeframe",
            timeframe,
            "--parameters-json",
            parameter_json,
        ]
        env = {
            "HOME": str(temp),
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
            "PATH": "/usr/bin:/bin",
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONHASHSEED": "0",
            "NUMBA_DISABLE_JIT": "1",
            "PA_ENGULF_NUMBA": "0",
            "PA_LOG_QUIET": "1",
            "PA_DISABLE_FILE_LOG": "1",
            "OMP_NUM_THREADS": "1",
            "OPENBLAS_NUM_THREADS": "1",
            "MKL_NUM_THREADS": "1",
        }
        try:
            completed = subprocess.run(
                command,
                cwd=temp,
                env=env,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                timeout=_BUILDER_TIMEOUT_SECONDS + 5,
                check=False,
                preexec_fn=_subprocess_resource_limits,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise OOSContractError(f"hermetic pool-builder replay failed: {exc}") from exc
        if completed.returncode != 0:
            stderr = completed.stderr.decode("utf-8", errors="replace")[:1000]
            raise OOSContractError(
                f"hermetic pool-builder replay exited {completed.returncode}: {stderr}"
            )
        if output.is_symlink() or not output.is_file():
            raise OOSContractError("pool builder did not create its exact output file")
        raw = output.read_bytes()
        if not raw or len(raw) > _MAX_POOL_BYTES:
            raise OOSContractError("pool builder output violates the byte cap")
        frame = _load_pool(
            output,
            strategy=strategy,
            timeframe=timeframe,
            label="hermetic replay",
        )
        output_sha = _sha256_bytes(raw)
        expected_receipt = _canonical_json(
            {
                "contract": POOL_BUILDER_REPLAY_CONTRACT,
                "output_sha256": output_sha,
                "status": "OK",
            }
        )
        if completed.stdout != expected_receipt:
            raise OOSContractError("pool builder stdout is not the canonical replay receipt")
        replay = {
            "contract": POOL_BUILDER_REPLAY_CONTRACT,
            "builder": {"path": builder_rel, "sha256": _sha256_file(builder_path)},
            "raw_ohlcv": {
                "path": raw_rel,
                "prefix_bytes": raw_prefix_bytes,
                "prefix_sha256": _sha256_file_prefix(raw_ohlcv_path, raw_prefix_bytes),
            },
            "parameters": parameters,
            "parameters_sha256": _sha256_bytes((parameter_json + "\n").encode()),
            "output": {
                "file_sha256": output_sha,
                "bytes": len(raw),
                "strategy_rows": len(frame),
                "strategy_prefix_sha256": _row_fingerprint(frame),
            },
        }
        return raw, frame, replay


def build_pool_from_replay(
    *,
    output_path: Path,
    raw_ohlcv_path: Path,
    builder_path: Path,
    repo_root: Path,
    strategy: str,
    timeframe: str,
    parameters: dict[str, Any],
    raw_prefix_bytes: int | None = None,
) -> dict[str, Any]:
    """Publish only bytes produced by the hermetic replay builder contract."""

    repo_root = Path(repo_root).resolve()
    output_path = Path(output_path)
    resolved_output = output_path.resolve()
    try:
        resolved_output.relative_to(repo_root)
    except ValueError as exc:
        raise OOSContractError("pool output must live inside repo_root") from exc
    if output_path.is_symlink():
        raise OOSContractError("pool output must not be a symlink")
    raw_path, _ = _repo_relative_file(repo_root, raw_ohlcv_path, "raw OHLCV source")
    raw, _frame, replay = _run_pool_builder_replay(
        repo_root=repo_root,
        builder_path=builder_path,
        raw_ohlcv_path=raw_path,
        raw_prefix_bytes=raw_prefix_bytes or raw_path.stat().st_size,
        strategy=strategy,
        timeframe=timeframe,
        parameters=parameters,
    )
    _atomic_replace(output_path, raw)
    return replay


def _read_provenance(path: Path) -> tuple[dict[str, Any], bytes]:
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise OOSContractError(f"pool provenance is missing or unsafe: {path}")
    raw = path.read_bytes()
    if len(raw) > _MAX_PROVENANCE_BYTES:
        raise OOSContractError("pool provenance exceeds the size limit")
    try:
        payload = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise OOSContractError(f"pool provenance is invalid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise OOSContractError("pool provenance root must be an object")
    return payload, raw


def _verify_provenance_entry_replay(
    *,
    provenance_path: Path,
    entry_sha256: str,
    repo_root: Path,
) -> tuple[dict[str, Any], bytes, pd.DataFrame, int]:
    """Hermetically rebuild one historical provenance head by identity."""

    payload, _ = _read_provenance(provenance_path)
    entries = payload.get("entries")
    if not isinstance(entries, list):
        raise OOSContractError("pool provenance entries are missing")
    matches = [
        (index, entry)
        for index, entry in enumerate(entries)
        if isinstance(entry, dict) and entry.get("entry_sha256") == entry_sha256
    ]
    if len(matches) != 1:
        raise OOSContractError("requested provenance replay head is missing or duplicated")
    index, entry = matches[0]
    builder = entry.get("builder", {})
    raw_source = entry.get("raw_ohlcv", {})
    identity = _normalise_parameter_identity(payload.get("parameter_identity"))
    builder_path = _pinned_repo_file(repo_root, builder.get("path"), "replay builder")
    raw_path = _pinned_repo_file(repo_root, raw_source.get("path"), "replay raw OHLCV")
    raw, frame, replay = _run_pool_builder_replay(
        repo_root=repo_root,
        builder_path=builder_path,
        raw_ohlcv_path=raw_path,
        raw_prefix_bytes=raw_source.get("prefix_bytes"),
        strategy=str(payload.get("strategy")),
        timeframe=str(payload.get("timeframe")),
        parameters=identity["parameters"],
    )
    if replay != entry.get("replay"):
        raise OOSContractError("hermetic builder replay receipt differs from provenance entry")
    pool = entry.get("pool", {})
    if (
        _sha256_bytes(raw) != pool.get("file_sha256")
        or len(frame) != pool.get("strategy_rows")
        or _row_fingerprint(frame) != pool.get("strategy_prefix_sha256")
    ):
        raise OOSContractError("hermetic builder replay output differs from provenance pool pin")
    return entry, raw, frame, index


def _validate_provenance_chain(
    *,
    provenance_path: Path,
    pool_path: Path,
    frame: pd.DataFrame,
    repo_root: Path,
    strategy: str,
    timeframe: str,
    as_of: datetime | None = None,
    require_latest_current: bool = True,
) -> dict[str, Any]:
    """Validate an append-only pool/raw-source provenance chain.

    Every historical pool prefix and raw-file byte prefix is checked against
    the current files.  An appended pool row is therefore rejected until the
    pinned builder has appended a matching chain entry.
    """

    repo_root = Path(repo_root).resolve()
    provenance_path, provenance_rel = _repo_relative_file(
        repo_root, provenance_path, "pool provenance"
    )
    pool_path, pool_rel = _repo_relative_file(repo_root, pool_path, "pool")
    payload, raw = _read_provenance(provenance_path)
    errors: list[str] = []
    if payload.get("schema_version") != POOL_PROVENANCE_SCHEMA:
        errors.append(f"pool provenance schema must be {POOL_PROVENANCE_SCHEMA!r}")
    logical_id = payload.get("logical_id")
    if (
        not isinstance(logical_id, str)
        or re.fullmatch(r"[a-z][a-z0-9_.-]{2,127}", logical_id) is None
    ):
        errors.append("pool provenance logical_id is invalid")
    if payload.get("strategy") != strategy:
        errors.append("pool provenance strategy mismatch")
    if payload.get("timeframe") != timeframe:
        errors.append("pool provenance timeframe mismatch")
    if payload.get("pool_path") != pool_rel:
        errors.append("pool provenance path mismatch")
    try:
        identity = _normalise_parameter_identity(payload.get("parameter_identity"))
    except OOSContractError as exc:
        errors.append(str(exc))
        identity = {}
    entries = payload.get("entries")
    if not isinstance(entries, list) or not entries:
        errors.append("pool provenance entries must be a non-empty list")
        entries = []

    previous_sha: str | None = None
    previous_rows = 0
    previous_raw_bytes = 0
    previous_generated: datetime | None = None
    builder_identity: dict[str, str] | None = None
    raw_path: Path | None = None
    raw_rel: str | None = None
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            errors.append(f"pool provenance entry {index} is not an object")
            continue
        if entry.get("sequence") != index + 1:
            errors.append(f"pool provenance entry {index} sequence mismatch")
        if entry.get("previous_entry_sha256") != previous_sha:
            errors.append(f"pool provenance entry {index} previous hash mismatch")
        expected_entry_sha = _provenance_entry_sha(entry)
        if entry.get("entry_sha256") != expected_entry_sha:
            errors.append(f"pool provenance entry {index} content hash mismatch")
        previous_sha = expected_entry_sha
        try:
            generated = _utc(entry.get("generated_at"), f"provenance[{index}].generated_at")
            if previous_generated is not None and generated <= previous_generated:
                errors.append("pool provenance generated_at values must increase")
            if as_of is not None and generated > as_of:
                errors.append("pool provenance contains an entry after evidence as_of")
            previous_generated = generated
        except OOSContractError as exc:
            errors.append(str(exc))

        pool = entry.get("pool")
        if not isinstance(pool, dict):
            errors.append(f"pool provenance entry {index} pool must be an object")
        else:
            rows = pool.get("strategy_rows")
            if isinstance(rows, bool) or not isinstance(rows, int) or rows < 1:
                errors.append(f"pool provenance entry {index} strategy_rows is invalid")
            else:
                if rows < previous_rows or rows > len(frame):
                    errors.append("pool provenance strategy row count is not append-only")
                else:
                    prefix = frame.iloc[:rows]
                    if pool.get("strategy_prefix_sha256") != _row_fingerprint(prefix):
                        errors.append(
                            f"pool provenance entry {index} strategy prefix hash mismatch"
                        )
                previous_rows = rows
            if not _SHA_RE.fullmatch(str(pool.get("file_sha256", ""))):
                errors.append(f"pool provenance entry {index} pool file hash is invalid")

        builder = entry.get("builder")
        if not isinstance(builder, dict):
            errors.append(f"pool provenance entry {index} builder must be an object")
        else:
            try:
                builder_path = _pinned_repo_file(
                    repo_root, builder.get("path"), f"provenance[{index}].builder.path"
                )
                current_builder = {
                    "path": str(builder_path.relative_to(repo_root)),
                    "sha256": _sha256_file(builder_path),
                }
                if builder != current_builder:
                    errors.append("pool builder path/hash differs from the pinned implementation")
                if builder_identity is None:
                    builder_identity = current_builder
                elif builder_identity != current_builder:
                    errors.append("pool provenance changed builder identity mid-chain")
            except OOSContractError as exc:
                errors.append(str(exc))

        raw_source = entry.get("raw_ohlcv")
        if not isinstance(raw_source, dict):
            errors.append(f"pool provenance entry {index} raw_ohlcv must be an object")
        else:
            try:
                entry_raw_path = _pinned_repo_file(
                    repo_root, raw_source.get("path"), f"provenance[{index}].raw_ohlcv.path"
                )
                entry_raw_rel = str(entry_raw_path.relative_to(repo_root))
                if raw_path is None:
                    raw_path, raw_rel = entry_raw_path, entry_raw_rel
                elif raw_path != entry_raw_path:
                    errors.append("pool provenance changed raw OHLCV source mid-chain")
                raw_bytes = raw_source.get("prefix_bytes")
                if (
                    isinstance(raw_bytes, bool)
                    or not isinstance(raw_bytes, int)
                    or raw_bytes < previous_raw_bytes
                    or raw_bytes < 1
                ):
                    errors.append("raw OHLCV prefix length is not append-only")
                elif raw_source.get("prefix_sha256") != _sha256_file_prefix(
                    entry_raw_path, raw_bytes
                ):
                    errors.append(f"pool provenance entry {index} raw OHLCV prefix hash mismatch")
                previous_raw_bytes = raw_bytes if isinstance(raw_bytes, int) else 0
                if not _SHA_RE.fullmatch(str(raw_source.get("file_sha256", ""))):
                    errors.append("raw OHLCV file hash is invalid")
            except OOSContractError as exc:
                errors.append(str(exc))

        replay = entry.get("replay")
        if not isinstance(replay, dict):
            errors.append(f"pool provenance entry {index} replay receipt is missing")
        else:
            expected_parameter_json = json.dumps(
                identity.get("parameters", {}),
                sort_keys=True,
                allow_nan=False,
                separators=(",", ":"),
            )
            replay_output = replay.get("output")
            replay_raw = replay.get("raw_ohlcv")
            replay_errors = (
                replay.get("contract") != POOL_BUILDER_REPLAY_CONTRACT,
                replay.get("builder") != entry.get("builder"),
                replay.get("parameters") != identity.get("parameters"),
                replay.get("parameters_sha256")
                != _sha256_bytes((expected_parameter_json + "\n").encode()),
                not isinstance(replay_output, dict)
                or replay_output.get("file_sha256") != entry.get("pool", {}).get("file_sha256"),
                not isinstance(replay_output, dict)
                or replay_output.get("strategy_rows")
                != entry.get("pool", {}).get("strategy_rows"),
                not isinstance(replay_output, dict)
                or replay_output.get("strategy_prefix_sha256")
                != entry.get("pool", {}).get("strategy_prefix_sha256"),
                not isinstance(replay_output, dict)
                or isinstance(replay_output.get("bytes"), bool)
                or not isinstance(replay_output.get("bytes"), int)
                or not 0 < replay_output.get("bytes", 0) <= _MAX_POOL_BYTES,
                not isinstance(replay_raw, dict)
                or replay_raw.get("path") != entry.get("raw_ohlcv", {}).get("path"),
                not isinstance(replay_raw, dict)
                or replay_raw.get("prefix_bytes")
                != entry.get("raw_ohlcv", {}).get("prefix_bytes"),
                not isinstance(replay_raw, dict)
                or replay_raw.get("prefix_sha256")
                != entry.get("raw_ohlcv", {}).get("prefix_sha256"),
            )
            if any(replay_errors):
                errors.append(f"pool provenance entry {index} replay receipt mismatch")

    if entries and require_latest_current:
        latest = entries[-1]
        latest_pool = latest.get("pool", {})
        if latest_pool.get("file_sha256") != _sha256_file(pool_path):
            errors.append("pool file changed without a matching provenance head")
        if latest_pool.get("strategy_rows") != len(frame):
            errors.append("pool row count changed without a matching provenance head")
        if latest_pool.get("strategy_prefix_sha256") != _row_fingerprint(frame):
            errors.append("pool rows changed without a matching provenance head")
        if latest.get("replay", {}).get("output", {}).get("bytes") != pool_path.stat().st_size:
            errors.append("pool byte size changed without a matching replay receipt")
        if raw_path is not None:
            latest_raw = latest.get("raw_ohlcv", {})
            if latest_raw.get("prefix_bytes") != raw_path.stat().st_size:
                errors.append("raw OHLCV size changed without a matching provenance head")
            if latest_raw.get("file_sha256") != _sha256_file(raw_path):
                errors.append("raw OHLCV content changed without a matching provenance head")
    if errors:
        raise OOSContractError("; ".join(errors))
    assert entries and previous_sha and builder_identity and raw_path and raw_rel and identity
    return {
        "path": provenance_rel,
        "file_sha256": _sha256_bytes(raw),
        "entry_count": len(entries),
        "head_sha256": previous_sha,
        "chain_prefix_sha256": _provenance_prefix_sha(entries),
        "logical_id": logical_id,
        "builder": builder_identity,
        "raw_ohlcv": {
            "path": raw_rel,
            "prefix_bytes": raw_path.stat().st_size,
            "prefix_sha256": _sha256_file(raw_path),
            "file_sha256": _sha256_file(raw_path),
        },
        "parameter_identity": identity,
    }


def _record_pool_provenance_locked(
    *,
    pool_path: Path,
    raw_ohlcv_path: Path,
    builder_path: Path,
    repo_root: Path,
    strategy: str,
    timeframe: str,
    logical_id: str,
    parameter_family: str,
    parameter_role: str,
    parameters: dict[str, Any],
    variant_of: str | None = None,
    declared_delta: dict[str, Any] | None = None,
    provenance_path: Path | None = None,
    generated_at: datetime | None = None,
) -> tuple[dict[str, Any], Path]:
    """Append one canonical pool/raw-content provenance head.

    Pool builders call this only after atomically publishing a pool.  The
    function never contacts an exchange and only fingerprints local files.
    """

    repo_root = Path(repo_root).resolve()
    pool_path, pool_rel = _repo_relative_file(repo_root, pool_path, "pool")
    raw_ohlcv_path, raw_rel = _repo_relative_file(repo_root, raw_ohlcv_path, "raw OHLCV source")
    builder_path, builder_rel = _repo_relative_file(repo_root, builder_path, "pool builder")
    if timeframe not in SUPPORTED_TFS:
        raise OOSContractError("unsupported provenance timeframe")
    if not isinstance(strategy, str) or _SLUG_RE.fullmatch(strategy) is None:
        raise OOSContractError("invalid provenance strategy")
    if (
        not isinstance(logical_id, str)
        or re.fullmatch(r"[a-z][a-z0-9_.-]{2,127}", logical_id) is None
    ):
        raise OOSContractError("invalid provenance logical_id")
    identity = _normalise_parameter_identity(
        {
            "family": parameter_family,
            "role": parameter_role,
            "parameters": parameters,
            "variant_of": variant_of,
            "declared_delta": declared_delta or {},
        }
    )
    frame = _load_pool(pool_path, strategy=strategy, timeframe=timeframe, label="provenance")
    replay_raw, replay_frame, replay = _run_pool_builder_replay(
        repo_root=repo_root,
        builder_path=builder_path,
        raw_ohlcv_path=raw_ohlcv_path,
        raw_prefix_bytes=raw_ohlcv_path.stat().st_size,
        strategy=strategy,
        timeframe=timeframe,
        parameters=identity["parameters"],
    )
    if pool_path.read_bytes() != replay_raw:
        raise OOSContractError(
            "pool bytes do not equal deterministic hermetic builder replay output"
        )
    if len(frame) != len(replay_frame) or _row_fingerprint(frame) != _row_fingerprint(
        replay_frame
    ):
        raise OOSContractError("pool rows do not equal deterministic builder replay rows")
    path = Path(provenance_path or _default_provenance_path(pool_path))
    try:
        path.resolve().relative_to(repo_root)
    except ValueError as exc:
        raise OOSContractError("pool provenance output must live inside repo_root") from exc
    if path.is_symlink():
        raise OOSContractError("pool provenance output must not be a symlink")

    now = _utc(generated_at or datetime.now(UTC), "provenance.generated_at")
    builder = {"path": builder_rel, "sha256": _sha256_file(builder_path)}
    entries: list[dict[str, Any]] = []
    if path.exists():
        existing, _ = _read_provenance(path)
        expected_root = {
            "schema_version": POOL_PROVENANCE_SCHEMA,
            "logical_id": logical_id,
            "strategy": strategy,
            "timeframe": timeframe,
            "pool_path": pool_rel,
            "parameter_identity": identity,
        }
        if any(existing.get(key) != value for key, value in expected_root.items()):
            raise OOSContractError("pool provenance immutable identity changed")
        entries = existing.get("entries")
        if not isinstance(entries, list) or not entries:
            raise OOSContractError("existing pool provenance has no entries")
        # Validate every existing prefix against the newly published files,
        # but allow the newest pool/raw state to extend the previous head.
        _validate_provenance_chain(
            provenance_path=path,
            pool_path=pool_path,
            frame=frame,
            repo_root=repo_root,
            strategy=strategy,
            timeframe=timeframe,
            require_latest_current=False,
        )
        latest = entries[-1]
        if latest.get("builder") != builder:
            raise OOSContractError("pool builder identity changed mid-chain")
        if latest.get("raw_ohlcv", {}).get("path") != raw_rel:
            raise OOSContractError("raw OHLCV source changed mid-chain")
        latest_generated = _utc(latest.get("generated_at"), "latest provenance.generated_at")
        current_pool_sha = _sha256_file(pool_path)
        current_raw_sha = _sha256_file(raw_ohlcv_path)
        if (
            latest.get("pool", {}).get("file_sha256") == current_pool_sha
            and latest.get("raw_ohlcv", {}).get("file_sha256") == current_raw_sha
        ):
            return existing, path
        if now <= latest_generated:
            raise OOSContractError("new provenance generated_at must follow the prior head")

    entry: dict[str, Any] = {
        "sequence": len(entries) + 1,
        "generated_at": now.isoformat(),
        "previous_entry_sha256": entries[-1]["entry_sha256"] if entries else None,
        "pool": {
            "file_sha256": _sha256_file(pool_path),
            "strategy_rows": len(frame),
            "strategy_prefix_sha256": _row_fingerprint(frame),
        },
        "builder": builder,
        "raw_ohlcv": {
            "path": raw_rel,
            "prefix_bytes": raw_ohlcv_path.stat().st_size,
            "prefix_sha256": _sha256_file(raw_ohlcv_path),
            "file_sha256": _sha256_file(raw_ohlcv_path),
        },
        "replay": replay,
    }
    entry["entry_sha256"] = _provenance_entry_sha(entry)
    payload = {
        "schema_version": POOL_PROVENANCE_SCHEMA,
        "logical_id": logical_id,
        "strategy": strategy,
        "timeframe": timeframe,
        "pool_path": pool_rel,
        "parameter_identity": identity,
        "entries": [*entries, entry],
    }
    _atomic_replace(path, _canonical_json(payload))
    # Reopen and fully validate the exact published bytes before returning.
    _validate_provenance_chain(
        provenance_path=path,
        pool_path=pool_path,
        frame=frame,
        repo_root=repo_root,
        strategy=strategy,
        timeframe=timeframe,
        as_of=now,
    )
    return payload, path


def record_pool_provenance(
    *,
    pool_path: Path,
    raw_ohlcv_path: Path,
    builder_path: Path,
    repo_root: Path,
    strategy: str,
    timeframe: str,
    logical_id: str,
    parameter_family: str,
    parameter_role: str,
    parameters: dict[str, Any],
    variant_of: str | None = None,
    declared_delta: dict[str, Any] | None = None,
    provenance_path: Path | None = None,
    generated_at: datetime | None = None,
) -> tuple[dict[str, Any], Path]:
    """Lock, replay, and append a durable provenance entry."""

    path = Path(provenance_path or _default_provenance_path(pool_path))
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = Path(f"{path}.lock")
    if lock_path.is_symlink():
        raise OOSContractError("pool provenance lock must not be a symlink")
    with lock_path.open("a+b") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        try:
            return _record_pool_provenance_locked(
                pool_path=pool_path,
                raw_ohlcv_path=raw_ohlcv_path,
                builder_path=builder_path,
                repo_root=repo_root,
                strategy=strategy,
                timeframe=timeframe,
                logical_id=logical_id,
                parameter_family=parameter_family,
                parameter_role=parameter_role,
                parameters=parameters,
                variant_of=variant_of,
                declared_delta=declared_delta,
                provenance_path=path,
                generated_at=generated_at,
            )
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def _variant_delta(
    candidate_logical_id: str,
    candidate_identity: dict[str, Any],
    variant_identity: dict[str, Any],
) -> dict[str, Any]:
    if candidate_identity.get("role") != "candidate":
        raise OOSContractError("candidate pool provenance role must be candidate")
    if variant_identity.get("role") != "variant":
        raise OOSContractError("parameter perturbation provenance role must be variant")
    if variant_identity.get("family") != candidate_identity.get("family"):
        raise OOSContractError("parameter variant must share the candidate parameter family")
    if variant_identity.get("variant_of") != candidate_logical_id:
        raise OOSContractError("parameter variant variant_of must name the candidate logical_id")
    candidate_parameters = candidate_identity.get("parameters", {})
    variant_parameters = variant_identity.get("parameters", {})
    if set(candidate_parameters) != set(variant_parameters):
        raise OOSContractError("parameter variant keys must exactly match candidate keys")
    changed = {
        key: {"from": candidate_parameters[key], "to": variant_parameters[key]}
        for key in sorted(candidate_parameters)
        if candidate_parameters[key] != variant_parameters[key]
    }
    if len(changed) != 1:
        raise OOSContractError("each parameter variant must change exactly one parameter")
    if variant_identity.get("declared_delta") != changed:
        raise OOSContractError("parameter variant declared_delta does not match its parameters")
    return changed


def _validate_pinned_provenance_snapshot(
    pinned: Any,
    *,
    repo_root: Path,
    current: dict[str, Any],
    selection_file_sha256: Any,
    selection_rows: Any,
    selection_prefix_sha256: Any,
) -> None:
    if not isinstance(pinned, dict):
        raise OOSContractError("pool provenance snapshot must be an object")
    count = pinned.get("selection_entry_count")
    if isinstance(count, bool) or not isinstance(count, int) or count < 1:
        raise OOSContractError("selection provenance entry count must be positive")
    path = _pinned_repo_file(repo_root, pinned.get("path"), "pinned pool provenance")
    payload, _ = _read_provenance(path)
    entries = payload.get("entries")
    if not isinstance(entries, list) or len(entries) < count:
        raise OOSContractError("pool provenance no longer descends from the selection head")
    prefix = entries[:count]
    selection_entry = prefix[-1]
    if pinned.get("selection_head_sha256") != selection_entry.get("entry_sha256"):
        raise OOSContractError("selection provenance head hash changed")
    if pinned.get("selection_chain_prefix_sha256") != _provenance_prefix_sha(prefix):
        raise OOSContractError("selection provenance content prefix changed")
    _entry, _raw, _frame, replay_index = _verify_provenance_entry_replay(
        provenance_path=path,
        entry_sha256=str(pinned.get("selection_head_sha256")),
        repo_root=repo_root,
    )
    if replay_index != count - 1:
        raise OOSContractError("selection provenance replay index changed")
    selection_pool = selection_entry.get("pool", {})
    if selection_pool.get("file_sha256") != selection_file_sha256:
        raise OOSContractError("selection pool file hash differs from provenance head")
    if selection_pool.get("strategy_rows") != selection_rows:
        raise OOSContractError("selection pool row count differs from provenance head")
    if selection_pool.get("strategy_prefix_sha256") != selection_prefix_sha256:
        raise OOSContractError("selection pool row hash differs from provenance head")
    expected_raw = {
        key: selection_entry.get("raw_ohlcv", {}).get(key)
        for key in ("path", "prefix_bytes", "prefix_sha256", "file_sha256")
    }
    exact = {
        "path": current["path"],
        "logical_id": current["logical_id"],
        "builder": selection_entry.get("builder"),
        "raw_ohlcv": expected_raw,
        "parameter_identity": current["parameter_identity"],
    }
    for field, expected in exact.items():
        if pinned.get(field) != expected:
            raise OOSContractError(f"selection provenance {field} identity changed")


def _validate_evidence_provenance_summary(
    pinned: Any,
    *,
    repo_root: Path,
    strategy: str,
    timeframe: str,
    pool_path: Path,
    pool_sha256: Any,
    selection_pin: Any,
    as_of: datetime,
) -> tuple[bytes, pd.DataFrame, dict[str, Any]]:
    """Validate and replay the provenance head frozen into old evidence.

    Evidence pins a prefix of an append-only provenance ledger, not the
    ledger's forever-changing latest file hash.  A later, correctly dated
    append therefore remains compatible, while a rewritten prefix, a
    backdated append, or a non-hermetic historical head is rejected.
    """

    expected_fields = {
        "path",
        "file_sha256",
        "entry_count",
        "head_sha256",
        "chain_prefix_sha256",
        "logical_id",
        "builder",
        "raw_ohlcv",
        "parameter_identity",
    }
    if not isinstance(pinned, dict) or set(pinned) != expected_fields:
        raise OOSContractError("evidence provenance summary fields are not canonical")
    if not isinstance(selection_pin, dict):
        raise OOSContractError("selection provenance snapshot must be an object")

    repo_root = Path(repo_root).resolve()
    provenance_path = _pinned_repo_file(
        repo_root, pinned.get("path"), "evidence pool provenance"
    )
    payload, current_raw = _read_provenance(provenance_path)
    ledger_fields = {
        "schema_version",
        "logical_id",
        "strategy",
        "timeframe",
        "pool_path",
        "parameter_identity",
        "entries",
    }
    if set(payload) != ledger_fields or current_raw != _canonical_json(payload):
        raise OOSContractError("current provenance ledger is not canonical")
    _pool_resolved, pool_rel = _repo_relative_file(repo_root, pool_path, "evidence pool")
    if payload.get("schema_version") != POOL_PROVENANCE_SCHEMA:
        raise OOSContractError("evidence provenance schema changed")
    if payload.get("strategy") != strategy or payload.get("timeframe") != timeframe:
        raise OOSContractError("evidence provenance strategy/timeframe changed")
    if payload.get("pool_path") != pool_rel:
        raise OOSContractError("evidence provenance pool path changed")

    identity = _normalise_parameter_identity(payload.get("parameter_identity"))
    entries = payload.get("entries")
    count = pinned.get("entry_count")
    if (
        not isinstance(entries, list)
        or isinstance(count, bool)
        or not isinstance(count, int)
        or not 1 <= count <= len(entries)
    ):
        raise OOSContractError("evidence provenance entry count is invalid")
    selection_count = selection_pin.get("selection_entry_count")
    if (
        isinstance(selection_count, bool)
        or not isinstance(selection_count, int)
        or selection_count < 1
        or count < selection_count
    ):
        raise OOSContractError("evidence provenance does not descend from selection")

    previous_sha: str | None = None
    previous_generated: datetime | None = None
    entries_visible_as_of = 0
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise OOSContractError("current provenance ledger contains a non-object entry")
        if entry.get("sequence") != index + 1:
            raise OOSContractError("current provenance ledger sequence changed")
        if entry.get("previous_entry_sha256") != previous_sha:
            raise OOSContractError("current provenance ledger link changed")
        expected_sha = _provenance_entry_sha(entry)
        if entry.get("entry_sha256") != expected_sha:
            raise OOSContractError("current provenance ledger entry hash changed")
        previous_sha = expected_sha
        generated = _utc(entry.get("generated_at"), f"provenance[{index}].generated_at")
        if previous_generated is not None and generated <= previous_generated:
            raise OOSContractError("current provenance timestamps are not increasing")
        previous_generated = generated
        if generated <= as_of:
            entries_visible_as_of += 1
        raw_source = entry.get("raw_ohlcv")
        if (
            not isinstance(raw_source, dict)
            or raw_source.get("file_sha256") != raw_source.get("prefix_sha256")
        ):
            raise OOSContractError("historical raw provenance does not pin exact full bytes")
    if count != entries_visible_as_of:
        raise OOSContractError("evidence provenance is not the latest ledger head as of evidence")

    prefix = entries[:count]
    head = prefix[-1]
    if head.get("entry_sha256") != pinned.get("head_sha256"):
        raise OOSContractError("evidence provenance head changed")
    if _provenance_prefix_sha(prefix) != pinned.get("chain_prefix_sha256"):
        raise OOSContractError("evidence provenance prefix changed")
    if prefix[selection_count - 1].get("entry_sha256") != selection_pin.get(
        "selection_head_sha256"
    ):
        raise OOSContractError("evidence provenance no longer descends from selection head")
    if _provenance_prefix_sha(prefix[:selection_count]) != selection_pin.get(
        "selection_chain_prefix_sha256"
    ):
        raise OOSContractError("evidence provenance selection prefix changed")

    historical_payload = {key: payload[key] for key in ledger_fields if key != "entries"}
    historical_payload["entries"] = prefix
    historical_raw = _canonical_json(historical_payload)
    if pinned.get("file_sha256") != _sha256_bytes(historical_raw):
        raise OOSContractError("evidence provenance historical ledger hash changed")
    expected_summary_fields = {
        "logical_id": payload.get("logical_id"),
        "builder": head.get("builder"),
        "raw_ohlcv": head.get("raw_ohlcv"),
        "parameter_identity": identity,
    }
    for field, expected in expected_summary_fields.items():
        if pinned.get(field) != expected:
            raise OOSContractError(f"evidence provenance {field} identity changed")

    replay_entry, replay_raw, replay_frame, replay_index = _verify_provenance_entry_replay(
        provenance_path=provenance_path,
        entry_sha256=str(pinned.get("head_sha256")),
        repo_root=repo_root,
    )
    if replay_index != count - 1 or replay_entry != head:
        raise OOSContractError("evidence provenance replay selected the wrong historical head")
    if not isinstance(pool_sha256, str) or not _SHA_RE.fullmatch(pool_sha256):
        raise OOSContractError("evidence pool sha256 is invalid")
    if _sha256_bytes(replay_raw) != pool_sha256:
        raise OOSContractError("evidence pool bytes differ from historical builder replay")
    return replay_raw, replay_frame, dict(pinned)


def _validate_discovery(payload: dict[str, Any]) -> tuple[str, str, str]:
    errors: list[str] = []
    expected = {
        "schema_version": DISCOVERY_SCHEMA,
        "verdict": DISCOVERY_VERDICT,
        "evidence_class": DISCOVERY_CLASS,
        "independent_oos": False,
        "deployment_authorized": False,
    }
    for field, value in expected.items():
        if payload.get(field) != value:
            errors.append(f"{field} must equal {value!r}")
    if payload.get("failed_gates") != []:
        errors.append("failed_gates must be empty")
    if payload.get("data_quality", {}).get("valid") is not True:
        errors.append("data_quality.valid must be boolean true")
    gates = payload.get("gates")
    if (
        not isinstance(gates, list)
        or not gates
        or any(not isinstance(gate, dict) or gate.get("passed") is not True for gate in gates)
    ):
        errors.append("every descriptive discovery gate must pass")
    strategy = payload.get("strategy")
    inputs = payload.get("inputs")
    if not isinstance(strategy, str) or not _SLUG_RE.fullmatch(strategy):
        errors.append("strategy must be a safe lowercase slug")
        strategy = "invalid"
    if not isinstance(inputs, dict):
        errors.append("inputs must be an object")
        inputs = {}
    candidate_tf = inputs.get("candidate_tf")
    baseline_tf = inputs.get("baseline_tf")
    if candidate_tf not in SUPPORTED_TFS or baseline_tf not in SUPPORTED_TFS:
        errors.append("candidate and baseline timeframes must be supported")
    if candidate_tf == baseline_tf:
        errors.append("candidate and baseline timeframes must differ")
    for name in ("candidate_pool", "baseline_pool"):
        value = inputs.get(name)
        if not isinstance(value, dict) or not _SHA_RE.fullmatch(str(value.get("sha256", ""))):
            errors.append(f"inputs.{name}.sha256 must be a lowercase sha256")
    if errors:
        raise OOSContractError("; ".join(errors))
    return strategy, str(candidate_tf), str(baseline_tf)


def _pool_snapshot(
    path: Path,
    *,
    repo_root: Path,
    frame: pd.DataFrame,
    timeframe: str,
    selection_cutoff: datetime,
    provenance: dict[str, Any],
) -> dict[str, Any]:
    cutoff = pd.Timestamp(selection_cutoff)
    prefix = frame.loc[frame["entry_ts"] <= cutoff].copy()
    return {
        "path": str(Path(path).resolve().relative_to(Path(repo_root).resolve())),
        "timeframe": timeframe,
        "selection_file_sha256": _sha256_file(Path(path)),
        "selection_prefix_sha256": _row_fingerprint(prefix),
        "selection_rows": len(prefix),
        "provenance": {
            "path": provenance["path"],
            "selection_entry_count": provenance["entry_count"],
            "selection_head_sha256": provenance["head_sha256"],
            "selection_chain_prefix_sha256": provenance["chain_prefix_sha256"],
            "logical_id": provenance["logical_id"],
            "builder": provenance["builder"],
            "raw_ohlcv": provenance["raw_ohlcv"],
            "parameter_identity": provenance["parameter_identity"],
        },
    }


def _strategy_identity(repo_root: Path, strategy: str) -> tuple[str, str]:
    relative = f"src/price_action/strategies/{strategy}.py"
    path = repo_root / relative
    if path.is_symlink() or not path.is_file():
        raise OOSContractError(f"strategy module is missing or unsafe: {relative}")
    return relative, _sha256_file(path)


def _evaluator_identity(repo_root: Path) -> tuple[str, str, str]:
    wrapper = repo_root / TRUSTED_EVALUATOR_PATH
    module_rel = "src/price_action/lab/tf_independent_oos.py"
    module = repo_root / module_rel
    if wrapper.is_symlink() or not wrapper.is_file():
        raise OOSContractError(f"trusted evaluator wrapper is missing: {TRUSTED_EVALUATOR_PATH}")
    if module.is_symlink() or not module.is_file():
        raise OOSContractError(f"trusted evaluator module is missing: {module_rel}")
    return _sha256_file(wrapper), module_rel, _sha256_file(module)


def _artifact_name(prefix: str, generated_at: datetime, raw: bytes) -> str:
    stamp = generated_at.astimezone(UTC).strftime("%Y%m%dT%H%M%S.%fZ")
    return f"{prefix}-{stamp}-{_sha256_bytes(raw)[:12]}.json"


def create_preregistration(
    *,
    discovery_path: Path,
    repo_root: Path,
    output_dir: Path,
    candidate_pool: Path | None = None,
    baseline_pool: Path | None = None,
    variant_pools: Iterable[Path] = (),
    protocol: OOSProtocol | None = None,
    protocol_path: Path | None = None,
    created_at: datetime | None = None,
    oos_start: datetime | None = None,
) -> tuple[dict[str, Any], Path]:
    """Freeze a descriptive screen into an immutable future-OOS protocol."""

    repo_root = Path(repo_root).resolve()
    resolved_protocol, protocol_rel = _repo_relative_file(
        repo_root,
        Path(protocol_path or repo_root / "configs" / "tf_oos_protocol.yaml"),
        "OOS protocol",
    )
    file_protocol = load_protocol(resolved_protocol)
    authorization_policy = _load_protocol_authorization(resolved_protocol)
    if protocol is not None:
        protocol.validate()
        if asdict(protocol) != asdict(file_protocol):
            raise OOSContractError("protocol object differs from the pinned protocol file")
    protocol = file_protocol
    discovery, discovery_raw = _load_json_file(discovery_path, "discovery artifact")
    _, discovery_rel = _repo_relative_file(repo_root, Path(discovery_path), "discovery artifact")
    strategy, candidate_tf, baseline_tf = _validate_discovery(discovery)
    inputs = discovery["inputs"]
    candidate_pool = Path(candidate_pool or inputs["candidate_pool"]["path"])
    baseline_pool = Path(baseline_pool or inputs["baseline_pool"]["path"])
    candidate_pool, _ = _repo_relative_file(repo_root, candidate_pool, "candidate pool")
    baseline_pool, _ = _repo_relative_file(repo_root, baseline_pool, "baseline pool")
    if candidate_pool.resolve() == baseline_pool.resolve():
        raise OOSContractError("candidate and baseline pools must be distinct files")
    if _sha256_file(candidate_pool) != inputs["candidate_pool"]["sha256"]:
        raise OOSContractError("candidate discovery pool hash does not match discovery artifact")
    if _sha256_file(baseline_pool) != inputs["baseline_pool"]["sha256"]:
        raise OOSContractError("baseline discovery pool hash does not match discovery artifact")
    if _sha256_file(candidate_pool) == _sha256_file(baseline_pool):
        raise OOSContractError("candidate and baseline pools must be content-distinct")

    candidate = _load_pool(
        candidate_pool, strategy=strategy, timeframe=candidate_tf, label="candidate"
    )
    baseline = _load_pool(baseline_pool, strategy=strategy, timeframe=baseline_tf, label="baseline")
    variants: list[tuple[Path, pd.DataFrame]] = []
    seen_paths: set[Path] = set()
    seen_hashes = {_sha256_file(candidate_pool), _sha256_file(baseline_pool)}
    for index, raw_path in enumerate(variant_pools):
        path, _ = _repo_relative_file(repo_root, Path(raw_path), f"parameter variant[{index}] pool")
        file_sha = _sha256_file(path)
        if path in seen_paths or file_sha in seen_hashes:
            raise OOSContractError("parameter variant pools must be path- and content-distinct")
        seen_paths.add(path)
        seen_hashes.add(file_sha)
        variants.append(
            (
                path,
                _load_pool(
                    path, strategy=strategy, timeframe=candidate_tf, label=f"variant[{index}]"
                ),
            )
        )

    all_frames = [candidate, baseline, *(frame for _, frame in variants)]
    selection_cutoff = max(frame["exit_ts"].max().to_pydatetime() for frame in all_frames)
    now = _utc(created_at or datetime.now(UTC), "created_at")
    if not now > selection_cutoff:
        raise OOSContractError("preregistration created_at must be after the selection cutoff")
    holdout_start = _utc(oos_start or (now + timedelta(microseconds=1)), "oos_start")
    if not holdout_start > now:
        raise OOSContractError("oos_start must be strictly after preregistration created_at")
    discovery_generated = _utc(discovery.get("generated_at"), "discovery.generated_at")
    if discovery_generated > now:
        raise OOSContractError("discovery artifact cannot be generated after preregistration")

    strategy_path, strategy_sha = _strategy_identity(repo_root, strategy)
    evaluator_sha, evaluator_module_path, evaluator_module_sha = _evaluator_identity(repo_root)
    candidate_provenance = _validate_provenance_chain(
        provenance_path=_default_provenance_path(candidate_pool),
        pool_path=candidate_pool,
        frame=candidate,
        repo_root=repo_root,
        strategy=strategy,
        timeframe=candidate_tf,
        as_of=now,
    )
    baseline_provenance = _validate_provenance_chain(
        provenance_path=_default_provenance_path(baseline_pool),
        pool_path=baseline_pool,
        frame=baseline,
        repo_root=repo_root,
        strategy=strategy,
        timeframe=baseline_tf,
        as_of=now,
    )
    if baseline_provenance["parameter_identity"]["role"] != "baseline":
        raise OOSContractError("baseline pool provenance role must be baseline")
    variant_provenance = [
        _validate_provenance_chain(
            provenance_path=_default_provenance_path(path),
            pool_path=path,
            frame=frame,
            repo_root=repo_root,
            strategy=strategy,
            timeframe=candidate_tf,
            as_of=now,
        )
        for path, frame in variants
    ]
    for provenance in [candidate_provenance, baseline_provenance, *variant_provenance]:
        _verify_provenance_entry_replay(
            provenance_path=_pinned_repo_file(
                repo_root, provenance["path"], "pool provenance replay"
            ),
            entry_sha256=provenance["head_sha256"],
            repo_root=repo_root,
        )
    candidate_identity = candidate_provenance["parameter_identity"]
    seen_parameter_identities = {
        json.dumps(candidate_identity["parameters"], sort_keys=True, separators=(",", ":"))
    }
    variant_deltas: list[dict[str, Any]] = []
    for provenance in variant_provenance:
        if provenance["builder"] != candidate_provenance["builder"]:
            raise OOSContractError("parameter variants must use the candidate pool builder")
        if provenance["raw_ohlcv"] != candidate_provenance["raw_ohlcv"]:
            raise OOSContractError("parameter variants must use identical raw OHLCV content")
        delta = _variant_delta(
            str(candidate_provenance["logical_id"]),
            candidate_identity,
            provenance["parameter_identity"],
        )
        parameter_key = json.dumps(
            provenance["parameter_identity"]["parameters"],
            sort_keys=True,
            separators=(",", ":"),
        )
        if parameter_key in seen_parameter_identities:
            raise OOSContractError("parameter variants must have unique effective parameters")
        seen_parameter_identities.add(parameter_key)
        variant_deltas.append(delta)
    variant_snapshots = [
        {
            "variant_id": f"variant-{_sha256_bytes(_canonical_json(variant_deltas[index]))[:12]}",
            "parameter_delta": variant_deltas[index],
            **_pool_snapshot(
                path,
                repo_root=repo_root,
                frame=frame,
                timeframe=candidate_tf,
                selection_cutoff=selection_cutoff,
                provenance=variant_provenance[index],
            ),
        }
        for index, (path, frame) in enumerate(variants)
    ]
    payload: dict[str, Any] = {
        "schema_version": PREREG_SCHEMA,
        "status": "PREREGISTERED",
        "created_at": now.isoformat(),
        "strategy": strategy,
        "candidate_tf": candidate_tf,
        "baseline_tf": baseline_tf,
        "selection_cutoff": selection_cutoff.isoformat(),
        "oos_start": holdout_start.isoformat(),
        "discovery": {
            "path": discovery_rel,
            "sha256": _sha256_bytes(discovery_raw),
            "schema_version": DISCOVERY_SCHEMA,
            "verdict": DISCOVERY_VERDICT,
        },
        "strategy_module": {"path": strategy_path, "sha256": strategy_sha},
        "evaluator": {
            "path": TRUSTED_EVALUATOR_PATH,
            "code_sha256": evaluator_sha,
            "module_path": evaluator_module_path,
            "module_sha256": evaluator_module_sha,
        },
        "pools": {
            "candidate": _pool_snapshot(
                candidate_pool,
                repo_root=repo_root,
                frame=candidate,
                timeframe=candidate_tf,
                selection_cutoff=selection_cutoff,
                provenance=candidate_provenance,
            ),
            "baseline": _pool_snapshot(
                baseline_pool,
                repo_root=repo_root,
                frame=baseline,
                timeframe=baseline_tf,
                selection_cutoff=selection_cutoff,
                provenance=baseline_provenance,
            ),
            "parameter_variants": variant_snapshots,
        },
        "protocol_artifact": {
            "path": protocol_rel,
            "sha256": _sha256_file(resolved_protocol),
            "schema_version": PROTOCOL_SCHEMA,
        },
        "protocol": asdict(protocol),
        "authorization_ceiling": authorization_policy,
    }
    raw = _canonical_json(payload)
    name = _artifact_name(f"{strategy}-{candidate_tf}-oos-prereg", now, raw)
    path = Path(output_dir) / name
    try:
        path.resolve().relative_to(repo_root)
    except ValueError as exc:
        raise OOSContractError("preregistration output must live inside repo_root") from exc
    _atomic_content_write(path, raw)
    return payload, path


def validate_preregistration(path: Path, *, repo_root: Path) -> tuple[dict[str, Any], str]:
    """Verify content address and every frozen identity before opening holdout data."""

    repo_root = Path(repo_root).resolve()
    resolved_path, _ = _repo_relative_file(repo_root, Path(path), "preregistration")
    payload, raw = _load_json_file(resolved_path, "preregistration")
    sha = _sha256_bytes(raw)
    match = _PREREG_NAME_RE.fullmatch(resolved_path.name)
    errors: list[str] = []
    if match is None or match.group("sha") != sha[:12]:
        errors.append("preregistration filename/content hash mismatch")
    if payload.get("schema_version") != PREREG_SCHEMA or payload.get("status") != "PREREGISTERED":
        errors.append("invalid preregistration schema/status")
    strategy = payload.get("strategy")
    candidate_tf = payload.get("candidate_tf")
    if match and (match.group("strategy") != strategy or match.group("tf") != candidate_tf):
        errors.append("preregistration filename identity mismatch")
    try:
        authorization_ceiling = _validate_authorization_policy(
            payload.get("authorization_ceiling")
        )
        created = _utc(payload.get("created_at"), "created_at")
        cutoff = _utc(payload.get("selection_cutoff"), "selection_cutoff")
        start = _utc(payload.get("oos_start"), "oos_start")
        if not cutoff < created < start:
            errors.append("timestamps must satisfy selection_cutoff < created_at < oos_start")
        if match and match.group("stamp") != created.strftime("%Y%m%dT%H%M%S.%fZ"):
            errors.append("preregistration filename timestamp mismatch")

        protocol = OOSProtocol(**payload.get("protocol", {}))
        protocol.validate()
        protocol_pin = payload.get("protocol_artifact")
        if not isinstance(protocol_pin, dict):
            raise OOSContractError("protocol_artifact must be an object")
        protocol_path = _pinned_repo_file(
            repo_root, protocol_pin.get("path"), "pinned OOS protocol"
        )
        if protocol_pin.get("schema_version") != PROTOCOL_SCHEMA:
            errors.append("pinned OOS protocol schema changed")
        if protocol_pin.get("sha256") != _sha256_file(protocol_path):
            errors.append("pinned OOS protocol content hash changed")
        file_protocol = load_protocol(protocol_path)
        if _load_protocol_authorization(protocol_path) != authorization_ceiling:
            errors.append("pinned principal authorization policy changed")
        if asdict(file_protocol) != asdict(protocol):
            errors.append("pinned OOS protocol content differs from preregistered thresholds")

        discovery_path = _pinned_repo_file(
            repo_root, payload["discovery"]["path"], "pinned discovery artifact"
        )
        discovery, discovery_raw = _load_json_file(discovery_path, "pinned discovery artifact")
        discovery_strategy, discovery_candidate_tf, discovery_baseline_tf = _validate_discovery(
            discovery
        )
        if (strategy, candidate_tf, payload.get("baseline_tf")) != (
            discovery_strategy,
            discovery_candidate_tf,
            discovery_baseline_tf,
        ):
            errors.append("preregistration identity differs from discovery artifact")
        discovery_generated = _utc(discovery.get("generated_at"), "discovery.generated_at")
        if discovery_generated > created:
            errors.append("discovery was generated after preregistration")
        if _sha256_bytes(discovery_raw) != payload["discovery"]["sha256"]:
            errors.append("pinned discovery artifact hash changed")
        pools = payload["pools"]
        candidate_snapshot = pools["candidate"]
        baseline_snapshot = pools["baseline"]
        discovery_inputs = discovery["inputs"]
        if (
            candidate_snapshot.get("selection_file_sha256")
            != discovery_inputs["candidate_pool"]["sha256"]
        ):
            errors.append("candidate selection pool pin differs from discovery")
        if (
            baseline_snapshot.get("selection_file_sha256")
            != discovery_inputs["baseline_pool"]["sha256"]
        ):
            errors.append("baseline selection pool pin differs from discovery")
        if candidate_snapshot.get("timeframe") != candidate_tf:
            errors.append("candidate pool timeframe pin changed")
        if baseline_snapshot.get("timeframe") != payload.get("baseline_tf"):
            errors.append("baseline pool timeframe pin changed")
        snapshots = [
            candidate_snapshot,
            baseline_snapshot,
            *pools.get("parameter_variants", []),
        ]
        snapshot_paths: list[str] = []
        selection_hashes: list[str] = []
        current_provenance: list[dict[str, Any]] = []
        expected_timeframes = [
            candidate_tf,
            payload.get("baseline_tf"),
            *([candidate_tf] * len(pools.get("parameter_variants", []))),
        ]
        for index, (snapshot, expected_tf) in enumerate(
            zip(snapshots, expected_timeframes, strict=True)
        ):
            if not isinstance(snapshot, dict):
                errors.append("pool snapshot must be an object")
                continue
            pool_path = _pinned_repo_file(repo_root, snapshot.get("path"), f"pinned pool[{index}]")
            snapshot_paths.append(str(pool_path))
            if snapshot.get("timeframe") != expected_tf:
                errors.append("pool snapshot timeframe identity changed")
            for field in ("selection_file_sha256", "selection_prefix_sha256"):
                value = snapshot.get(field)
                if not isinstance(value, str) or not _SHA_RE.fullmatch(value):
                    errors.append(f"pool snapshot {field} must be a sha256")
            selection_hashes.append(str(snapshot.get("selection_file_sha256")))
            rows = snapshot.get("selection_rows")
            if isinstance(rows, bool) or not isinstance(rows, int) or rows < 1:
                errors.append("pool snapshot selection_rows must be a positive integer")
            frame = _load_pool(
                pool_path,
                strategy=str(strategy),
                timeframe=str(expected_tf),
                label=f"pinned[{index}]",
            )
            selection_prefix = frame.loc[frame["entry_ts"] <= pd.Timestamp(cutoff)]
            if len(selection_prefix) != rows or _row_fingerprint(selection_prefix) != snapshot.get(
                "selection_prefix_sha256"
            ):
                errors.append(f"pool[{index}] frozen selection prefix changed")
            provenance_pin = snapshot.get("provenance")
            provenance_path = _pinned_repo_file(
                repo_root,
                provenance_pin.get("path") if isinstance(provenance_pin, dict) else None,
                f"pinned pool[{index}] provenance",
            )
            current = _validate_provenance_chain(
                provenance_path=provenance_path,
                pool_path=pool_path,
                frame=frame,
                repo_root=repo_root,
                strategy=str(strategy),
                timeframe=str(expected_tf),
            )
            _validate_pinned_provenance_snapshot(
                provenance_pin,
                repo_root=repo_root,
                current=current,
                selection_file_sha256=snapshot.get("selection_file_sha256"),
                selection_rows=snapshot.get("selection_rows"),
                selection_prefix_sha256=snapshot.get("selection_prefix_sha256"),
            )
            current_provenance.append(current)
        if len(snapshot_paths) != len(set(snapshot_paths)):
            errors.append("preregistered pool paths must be distinct")
        if len(selection_hashes) != len(set(selection_hashes)):
            errors.append("preregistered pool contents must be distinct")
        if len(current_provenance) == len(snapshots):
            candidate_provenance = current_provenance[0]
            if current_provenance[1]["parameter_identity"]["role"] != "baseline":
                errors.append("baseline pool provenance role changed")
            seen_parameters: set[str] = set()
            candidate_key = json.dumps(
                candidate_provenance["parameter_identity"]["parameters"],
                sort_keys=True,
                separators=(",", ":"),
            )
            seen_parameters.add(candidate_key)
            for snapshot, variant_provenance in zip(
                pools.get("parameter_variants", []),
                current_provenance[2:],
                strict=True,
            ):
                if variant_provenance["builder"] != candidate_provenance["builder"]:
                    errors.append("parameter variant builder identity changed")
                if variant_provenance["raw_ohlcv"] != candidate_provenance["raw_ohlcv"]:
                    errors.append("parameter variant raw OHLCV identity changed")
                delta = _variant_delta(
                    str(candidate_provenance["logical_id"]),
                    candidate_provenance["parameter_identity"],
                    variant_provenance["parameter_identity"],
                )
                if snapshot.get("parameter_delta") != delta:
                    errors.append("parameter variant delta pin changed")
                expected_variant_id = f"variant-{_sha256_bytes(_canonical_json(delta))[:12]}"
                if snapshot.get("variant_id") != expected_variant_id:
                    errors.append("parameter variant id is not derived from its delta")
                parameter_key = json.dumps(
                    variant_provenance["parameter_identity"]["parameters"],
                    sort_keys=True,
                    separators=(",", ":"),
                )
                if parameter_key in seen_parameters:
                    errors.append("parameter variant effective identity is duplicated")
                seen_parameters.add(parameter_key)
        strategy_path, strategy_sha = _strategy_identity(repo_root, str(strategy))
        if payload.get("strategy_module") != {"path": strategy_path, "sha256": strategy_sha}:
            errors.append("strategy module identity changed")
        evaluator_sha, module_path, module_sha = _evaluator_identity(repo_root)
        if payload.get("evaluator") != {
            "path": TRUSTED_EVALUATOR_PATH,
            "code_sha256": evaluator_sha,
            "module_path": module_path,
            "module_sha256": module_sha,
        }:
            errors.append("independent-OOS evaluator identity changed")
    except (KeyError, TypeError, OOSContractError) as exc:
        errors.append(str(exc))
    if errors:
        raise OOSContractError("; ".join(errors))
    return payload, sha


def _metrics(frame: pd.DataFrame) -> dict[str, Any]:
    values = frame["R"].to_numpy(dtype=float)
    return {
        "n_trades": len(frame),
        "n_symbols": int(frame["symbol"].nunique()),
        "mean_R": float(values.mean()) if len(values) else None,
        "sum_R": float(values.sum()),
        "win_rate": float(np.mean(values > 0)) if len(values) else None,
        "first_entry_ts": frame["entry_ts"].min().isoformat() if len(frame) else None,
        "last_entry_ts": frame["entry_ts"].max().isoformat() if len(frame) else None,
    }


def _gate(name: str, passed: bool, *, value: Any, threshold: Any, detail: str) -> dict[str, Any]:
    return {
        "name": name,
        "passed": bool(passed),
        "value": value,
        "threshold": threshold,
        "detail": detail,
    }


def _align_common(
    candidate: pd.DataFrame, baseline: pd.DataFrame
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    common_symbols = sorted(set(candidate["symbol"]) & set(baseline["symbol"]))
    if not common_symbols:
        raise OOSContractError("candidate and baseline holdout have no common symbols")
    candidate = candidate.loc[candidate["symbol"].isin(common_symbols)].copy()
    baseline = baseline.loc[baseline["symbol"].isin(common_symbols)].copy()
    start = max(candidate["entry_ts"].min(), baseline["entry_ts"].min())
    end = min(candidate["entry_ts"].max(), baseline["entry_ts"].max())
    if pd.isna(start) or pd.isna(end) or start >= end:
        raise OOSContractError("candidate and baseline holdout have no common time window")
    candidate = candidate.loc[candidate["entry_ts"].between(start, end)].copy()
    baseline = baseline.loc[baseline["entry_ts"].between(start, end)].copy()
    if candidate.empty or baseline.empty:
        raise OOSContractError("common holdout sample is empty")
    return (
        candidate,
        baseline,
        {
            "method": "common_symbol_and_entry_time_window",
            "common_symbols": common_symbols,
            "entry_start": start.isoformat(),
            "entry_end": end.isoformat(),
        },
    )


def _walk_forward(
    candidate: pd.DataFrame, baseline: pd.DataFrame, protocol: OOSProtocol
) -> dict[str, Any]:
    start = min(candidate["entry_ts"].min(), baseline["entry_ts"].min())
    end = max(candidate["entry_ts"].max(), baseline["entry_ts"].max())
    boundaries = pd.date_range(start=start, end=end, periods=protocol.walk_forward_folds + 1)
    folds: list[dict[str, Any]] = []
    for index in range(protocol.walk_forward_folds):
        left, right = boundaries[index], boundaries[index + 1]
        final = index == protocol.walk_forward_folds - 1
        candidate_mask = (candidate["entry_ts"] >= left) & (
            candidate["entry_ts"] <= right if final else candidate["entry_ts"] < right
        )
        baseline_mask = (baseline["entry_ts"] >= left) & (
            baseline["entry_ts"] <= right if final else baseline["entry_ts"] < right
        )
        c_fold, b_fold = candidate.loc[candidate_mask], baseline.loc[baseline_mask]
        c_mean = float(c_fold["R"].mean()) if len(c_fold) else None
        b_mean = float(b_fold["R"].mean()) if len(b_fold) else None
        passed = (
            len(c_fold) >= protocol.min_trades_per_walk_forward_fold
            and len(b_fold) >= protocol.min_trades_per_walk_forward_fold
            and c_mean is not None
            and b_mean is not None
            and c_mean > protocol.min_candidate_mean_r
            and c_mean - b_mean > protocol.min_candidate_vs_baseline_mean_r
        )
        folds.append(
            {
                "fold": index + 1,
                "start": left.isoformat(),
                "end": right.isoformat(),
                "candidate_trades": len(c_fold),
                "baseline_trades": len(b_fold),
                "candidate_mean_R": c_mean,
                "baseline_mean_R": b_mean,
                "passed": passed,
            }
        )
    share = sum(fold["passed"] for fold in folds) / len(folds)
    return {
        "folds": folds,
        "positive_fold_share": share,
        "passed": share >= protocol.min_positive_walk_forward_share,
    }


def _symbol_out(
    candidate: pd.DataFrame, baseline: pd.DataFrame, protocol: OOSProtocol
) -> dict[str, Any]:
    rows = []
    for symbol in sorted(set(candidate["symbol"]) & set(baseline["symbol"])):
        c = candidate.loc[candidate["symbol"] != symbol]
        b = baseline.loc[baseline["symbol"] != symbol]
        c_mean = float(c["R"].mean()) if len(c) else None
        b_mean = float(b["R"].mean()) if len(b) else None
        passed = (
            c_mean is not None
            and b_mean is not None
            and c_mean > protocol.min_symbol_out_mean_r
            and c_mean - b_mean > protocol.min_candidate_vs_baseline_mean_r
        )
        rows.append(
            {
                "omitted_symbol": symbol,
                "candidate_mean_R": c_mean,
                "baseline_mean_R": b_mean,
                "passed": passed,
            }
        )
    return {"per_omitted_symbol": rows, "passed": bool(rows) and all(row["passed"] for row in rows)}


def _regime_robustness(
    candidate: pd.DataFrame, baseline: pd.DataFrame, protocol: OOSProtocol
) -> dict[str, Any]:
    common = sorted(set(candidate["regime"]) & set(baseline["regime"]))
    rows = []
    for regime in common:
        c = candidate.loc[candidate["regime"] == regime]
        b = baseline.loc[baseline["regime"] == regime]
        c_mean = float(c["R"].mean()) if len(c) else None
        b_mean = float(b["R"].mean()) if len(b) else None
        passed = (
            len(c) >= protocol.min_trades_per_regime
            and len(b) >= protocol.min_trades_per_regime
            and c_mean is not None
            and b_mean is not None
            and c_mean > protocol.min_regime_mean_r
            and c_mean - b_mean > protocol.min_candidate_vs_baseline_mean_r
        )
        rows.append(
            {
                "regime": regime,
                "candidate_trades": len(c),
                "baseline_trades": len(b),
                "candidate_mean_R": c_mean,
                "baseline_mean_R": b_mean,
                "passed": passed,
            }
        )
    passed = len(rows) >= protocol.min_regimes and all(row["passed"] for row in rows)
    return {"common_regimes": common, "per_regime": rows, "passed": passed}


def _monthly_permutation(
    candidate: pd.DataFrame, baseline: pd.DataFrame, protocol: OOSProtocol
) -> dict[str, Any]:
    def monthly(frame: pd.DataFrame) -> pd.Series:
        return (
            frame.assign(month=frame["entry_ts"].dt.strftime("%Y-%m"))
            .groupby("month", sort=True)["R"]
            .mean()
        )

    paired = pd.concat(
        [monthly(candidate).rename("candidate"), monthly(baseline).rename("baseline")],
        axis=1,
        join="inner",
    ).dropna()
    differences = (paired["candidate"] - paired["baseline"]).to_numpy(dtype=float)
    observed = float(differences.mean()) if len(differences) else None
    if len(differences) < protocol.min_common_months or observed is None or observed <= 0:
        return {
            "defined": False,
            "common_months": len(differences),
            "observed_mean_difference_R": observed,
            "p_value": None,
            "passed": False,
        }
    if len(differences) <= 16:
        signs = np.asarray(list(itertools.product((-1.0, 1.0), repeat=len(differences))))
        permuted = (signs * differences).mean(axis=1)
        p_value = float(np.mean(permuted >= observed - 1e-15))
        method = "exact"
        samples = len(permuted)
    else:
        rng = np.random.default_rng(protocol.permutation_seed)
        extreme = 0
        remaining = protocol.permutation_samples
        while remaining:
            size = min(2048, remaining)
            signs = rng.integers(0, 2, size=(size, len(differences)), dtype=np.int8) * 2 - 1
            extreme += int(np.count_nonzero((signs * differences).mean(axis=1) >= observed - 1e-15))
            remaining -= size
        p_value = float((extreme + 1) / (protocol.permutation_samples + 1))
        method = "monte_carlo"
        samples = protocol.permutation_samples
    return {
        "defined": True,
        "common_months": len(differences),
        "observed_mean_difference_R": observed,
        "p_value": p_value,
        "method": method,
        "samples": samples,
        "passed": p_value <= protocol.family_wise_alpha,
    }


def _parameter_perturbation(
    variants: list[tuple[str, pd.DataFrame]],
    *,
    primary_mean: float,
    common_symbols: list[str],
    start: pd.Timestamp,
    end: pd.Timestamp,
    protocol: OOSProtocol,
) -> dict[str, Any]:
    rows = []
    for variant_id, frame in variants:
        sample = frame.loc[
            frame["symbol"].isin(common_symbols) & frame["entry_ts"].between(start, end)
        ]
        mean_r = float(sample["R"].mean()) if len(sample) else None
        retention = mean_r / primary_mean if mean_r is not None and primary_mean > 0 else None
        passed = (
            len(sample) >= protocol.min_candidate_trades
            and mean_r is not None
            and mean_r > protocol.min_candidate_mean_r
            and retention is not None
            and retention >= protocol.min_variant_expectancy_retention
        )
        rows.append(
            {
                "variant_id": variant_id,
                "n_trades": len(sample),
                "mean_R": mean_r,
                "expectancy_retention": retention,
                "passed": passed,
            }
        )
    return {
        "variants": rows,
        "passed": len(rows) >= protocol.min_parameter_variants
        and all(row["passed"] for row in rows),
    }


def _status_payload(
    *,
    prereg: dict[str, Any],
    prereg_sha: str,
    generated_at: datetime,
    gates: list[dict[str, Any]],
    data_quality_errors: list[str],
    diagnostics: dict[str, Any],
) -> dict[str, Any]:
    failed = [gate["name"] for gate in gates if not gate["passed"]]
    return {
        "schema_version": STATUS_SCHEMA,
        "generated_at": generated_at.isoformat(),
        "status": "HOLD",
        "verdict": "HOLD",
        "independent_oos": False,
        "deployment_authorized": False,
        "strategy": prereg.get("strategy"),
        "candidate_tf": prereg.get("candidate_tf"),
        "preregistration_sha256": prereg_sha,
        "data_quality": {"valid": not data_quality_errors, "errors": data_quality_errors},
        "gates": gates,
        "failed_gates": failed or (["data_quality"] if data_quality_errors else []),
        "diagnostics": diagnostics,
        "authorization": prereg["authorization_ceiling"],
    }


def _write_status(payload: dict[str, Any], output_dir: Path) -> Path:
    raw = _canonical_json(payload)
    generated = _utc(payload["generated_at"], "generated_at")
    prefix = f"{payload.get('strategy', 'invalid')}-{payload.get('candidate_tf', 'invalid')}-independent-oos-status"
    path = Path(output_dir) / _artifact_name(prefix, generated, raw)
    _atomic_content_write(path, raw)
    return path


def evaluate_preregistration(
    *,
    preregistration_path: Path,
    repo_root: Path,
    evidence_dir: Path,
    status_dir: Path,
    candidate_pool: Path | None = None,
    baseline_pool: Path | None = None,
    variant_pools: Iterable[Path] | None = None,
    as_of: datetime | None = None,
    _downstream_validate: bool = True,
    _replay_inputs: dict[str, tuple[Path, dict[str, Any]]] | None = None,
) -> tuple[dict[str, Any], Path]:
    """Evaluate future rows and emit either one evidence JSON or one HOLD JSON."""

    repo_root = Path(repo_root).resolve()
    generated = _utc(as_of or datetime.now(UTC), "as_of")
    try:
        prereg, prereg_sha = validate_preregistration(preregistration_path, repo_root=repo_root)
    except OOSContractError as exc:
        fallback, fallback_raw = _load_json_file(
            Path(preregistration_path), "rejected preregistration"
        )
        payload = _status_payload(
            prereg=fallback,
            prereg_sha=_sha256_bytes(fallback_raw),
            generated_at=generated,
            gates=[],
            data_quality_errors=[f"preregistration validation failed: {exc}"],
            diagnostics={},
        )
        return payload, _write_status(payload, status_dir)
    protocol = OOSProtocol(**prereg["protocol"])
    cutoff = _utc(prereg["selection_cutoff"], "selection_cutoff")
    oos_start = _utc(prereg["oos_start"], "oos_start")
    if generated > datetime.now(UTC) + timedelta(minutes=5):
        payload = _status_payload(
            prereg=prereg,
            prereg_sha=prereg_sha,
            generated_at=datetime.now(UTC),
            gates=[],
            data_quality_errors=["as_of is implausibly in the future"],
            diagnostics={},
        )
        return payload, _write_status(payload, status_dir)
    if generated <= oos_start:
        payload = _status_payload(
            prereg=prereg,
            prereg_sha=prereg_sha,
            generated_at=generated,
            gates=[],
            data_quality_errors=["as_of must be after preregistered oos_start"],
            diagnostics={},
        )
        return payload, _write_status(payload, status_dir)

    snapshots = prereg["pools"]
    pinned_candidate_path = _pinned_repo_file(
        repo_root, snapshots["candidate"]["path"], "candidate pool"
    )
    pinned_baseline_path = _pinned_repo_file(
        repo_root, snapshots["baseline"]["path"], "baseline pool"
    )
    replay_mode = _replay_inputs is not None
    candidate_path = (
        Path(_replay_inputs["candidate"][0])
        if replay_mode
        else (Path(candidate_pool).resolve() if candidate_pool else pinned_candidate_path)
    )
    baseline_path = (
        Path(_replay_inputs["baseline"][0])
        if replay_mode
        else (Path(baseline_pool).resolve() if baseline_pool else pinned_baseline_path)
    )
    pinned_variants = snapshots.get("parameter_variants", [])
    pinned_variant_paths = [
        _pinned_repo_file(repo_root, item["path"], "parameter variant pool")
        for item in pinned_variants
    ]
    supplied_variants = (
        [Path(_replay_inputs[item["variant_id"]][0]) for item in pinned_variants]
        if replay_mode
        else (
            [Path(path).resolve() for path in variant_pools]
            if variant_pools is not None
            else pinned_variant_paths
        )
    )
    data_errors: list[str] = []
    diagnostics: dict[str, Any] = {}
    gates: list[dict[str, Any]] = []
    try:
        if not replay_mode and candidate_path.resolve() != pinned_candidate_path:
            raise OOSContractError("candidate pool path differs from preregistration")
        if not replay_mode and baseline_path.resolve() != pinned_baseline_path:
            raise OOSContractError("baseline pool path differs from preregistration")
        if len(supplied_variants) != len(pinned_variants):
            raise OOSContractError("parameter variant pool count differs from preregistration")
        for path, snapshot in zip(supplied_variants, pinned_variants, strict=True):
            if not replay_mode and Path(path).resolve() != _pinned_repo_file(
                repo_root, snapshot["path"], "parameter variant pool"
            ):
                raise OOSContractError("parameter variant path differs from preregistration")
        candidate_all = _load_pool(
            candidate_path,
            strategy=prereg["strategy"],
            timeframe=prereg["candidate_tf"],
            label="candidate",
        )
        baseline_all = _load_pool(
            baseline_path,
            strategy=prereg["strategy"],
            timeframe=prereg["baseline_tf"],
            label="baseline",
        )
        current_hashes = {
            _sha256_file(candidate_path),
            _sha256_file(baseline_path),
            *(_sha256_file(Path(path)) for path in supplied_variants),
        }
        if len(current_hashes) != 2 + len(supplied_variants):
            raise OOSContractError(
                "current candidate, baseline, and variant pools must be content-distinct"
            )
        variants_all: list[tuple[str, pd.DataFrame]] = []
        for index, (path, snapshot) in enumerate(
            zip(supplied_variants, pinned_variants, strict=True)
        ):
            variants_all.append(
                (
                    snapshot["variant_id"],
                    _load_pool(
                        Path(path),
                        strategy=prereg["strategy"],
                        timeframe=prereg["candidate_tf"],
                        label=f"variant[{index}]",
                    ),
                )
            )
        pool_rows = [
            (candidate_path, candidate_all, snapshots["candidate"], "candidate"),
            (baseline_path, baseline_all, snapshots["baseline"], "baseline"),
            *(
                (Path(path), frame, snapshot, variant_id)
                for path, (variant_id, frame), snapshot in zip(
                    supplied_variants, variants_all, pinned_variants, strict=True
                )
            ),
        ]
        current_provenance: list[dict[str, Any]] = []
        for path, frame, snapshot, label in pool_rows:
            provenance_pin = snapshot.get("provenance")
            provenance_path = _pinned_repo_file(
                repo_root,
                provenance_pin.get("path") if isinstance(provenance_pin, dict) else None,
                f"{label} pool provenance",
            )
            if replay_mode:
                assert _replay_inputs is not None
                current = dict(_replay_inputs[label][1])
                if current.get("path") != str(provenance_path.relative_to(repo_root)):
                    raise OOSContractError("historical replay provenance path changed")
                if current.get("logical_id") != provenance_pin.get("logical_id"):
                    raise OOSContractError("historical replay provenance logical_id changed")
                if current.get("builder") != provenance_pin.get("builder"):
                    raise OOSContractError("historical replay provenance builder changed")
                if current.get("parameter_identity") != provenance_pin.get(
                    "parameter_identity"
                ):
                    raise OOSContractError("historical replay parameter identity changed")
                selection_count = provenance_pin.get("selection_entry_count")
                if (
                    isinstance(selection_count, bool)
                    or not isinstance(selection_count, int)
                    or current.get("entry_count", 0) < selection_count
                ):
                    raise OOSContractError("historical replay predates frozen selection")
            else:
                current = _validate_provenance_chain(
                    provenance_path=provenance_path,
                    pool_path=Path(path),
                    frame=frame,
                    repo_root=repo_root,
                    strategy=prereg["strategy"],
                    timeframe=snapshot["timeframe"],
                    as_of=generated,
                )
                _verify_provenance_entry_replay(
                    provenance_path=provenance_path,
                    entry_sha256=current["head_sha256"],
                    repo_root=repo_root,
                )
                _validate_pinned_provenance_snapshot(
                    provenance_pin,
                    repo_root=repo_root,
                    current=current,
                    selection_file_sha256=snapshot.get("selection_file_sha256"),
                    selection_rows=snapshot.get("selection_rows"),
                    selection_prefix_sha256=snapshot.get("selection_prefix_sha256"),
                )
            current_provenance.append(current)
        candidate_provenance = current_provenance[0]
        seen_parameter_identities = {
            json.dumps(
                candidate_provenance["parameter_identity"]["parameters"],
                sort_keys=True,
                separators=(",", ":"),
            )
        }
        for snapshot, provenance in zip(pinned_variants, current_provenance[2:], strict=True):
            if provenance["builder"] != candidate_provenance["builder"]:
                raise OOSContractError("parameter variant builder identity changed")
            if provenance["raw_ohlcv"] != candidate_provenance["raw_ohlcv"]:
                raise OOSContractError("parameter variant raw OHLCV identity changed")
            delta = _variant_delta(
                str(candidate_provenance["logical_id"]),
                candidate_provenance["parameter_identity"],
                provenance["parameter_identity"],
            )
            if snapshot.get("parameter_delta") != delta:
                raise OOSContractError("parameter variant delta identity changed")
            parameter_key = json.dumps(
                provenance["parameter_identity"]["parameters"],
                sort_keys=True,
                separators=(",", ":"),
            )
            if parameter_key in seen_parameter_identities:
                raise OOSContractError("parameter variant effective identity is duplicated")
            seen_parameter_identities.add(parameter_key)
        for frame, snapshot, label in (
            (candidate_all, snapshots["candidate"], "candidate"),
            (baseline_all, snapshots["baseline"], "baseline"),
            *(
                (frame, snapshot, variant_id)
                for (variant_id, frame), snapshot in zip(variants_all, pinned_variants, strict=True)
            ),
        ):
            prefix = frame.loc[frame["entry_ts"] <= pd.Timestamp(cutoff)]
            if (
                len(prefix) != snapshot["selection_rows"]
                or _row_fingerprint(prefix) != snapshot["selection_prefix_sha256"]
            ):
                raise OOSContractError(f"{label} frozen selection prefix changed")
        candidate_holdout = candidate_all.loc[
            (candidate_all["entry_ts"] >= pd.Timestamp(oos_start))
            & (candidate_all["exit_ts"] <= pd.Timestamp(generated))
        ].copy()
        baseline_holdout = baseline_all.loc[
            (baseline_all["entry_ts"] >= pd.Timestamp(oos_start))
            & (baseline_all["exit_ts"] <= pd.Timestamp(generated))
        ].copy()
        variants_holdout = [
            (
                variant_id,
                frame.loc[
                    (frame["entry_ts"] >= pd.Timestamp(oos_start))
                    & (frame["exit_ts"] <= pd.Timestamp(generated))
                ].copy(),
            )
            for variant_id, frame in variants_all
        ]
        candidate, baseline, alignment = _align_common(candidate_holdout, baseline_holdout)
        diagnostics["alignment"] = alignment
        c_metrics, b_metrics = _metrics(candidate), _metrics(baseline)
        diagnostics["candidate"] = c_metrics
        diagnostics["baseline"] = b_metrics
        common_days = (
            candidate["entry_ts"].max() - candidate["entry_ts"].min()
        ).total_seconds() / 86400
        candidate_mean = float(c_metrics["mean_R"])
        baseline_mean = float(b_metrics["mean_R"])
        wf = _walk_forward(candidate, baseline, protocol)
        symbol_out = _symbol_out(candidate, baseline, protocol)
        regimes = _regime_robustness(candidate, baseline, protocol)
        permutation = _monthly_permutation(candidate, baseline, protocol)
        adjusted_p = (
            min(1.0, float(permutation["p_value"]) * protocol.family_size)
            if permutation.get("p_value") is not None
            else None
        )
        variants = _parameter_perturbation(
            variants_holdout,
            primary_mean=candidate_mean,
            common_symbols=alignment["common_symbols"],
            start=pd.Timestamp(alignment["entry_start"]),
            end=pd.Timestamp(alignment["entry_end"]),
            protocol=protocol,
        )
        diagnostics.update(
            {
                "walk_forward": wf,
                "symbol_out": symbol_out,
                "regime_robustness": regimes,
                "monthly_block_permutation": permutation,
                "multiple_testing": {
                    "method": "bonferroni",
                    "family_size": protocol.family_size,
                    "raw_p_value": permutation.get("p_value"),
                    "adjusted_p_value": adjusted_p,
                },
                "parameter_perturbation": variants,
            }
        )
        gates = [
            _gate(
                "data_quality",
                True,
                value=True,
                threshold=True,
                detail="All inputs and frozen prefixes validated.",
            ),
            _gate(
                "minimum_oos_calendar_days",
                common_days >= protocol.min_oos_calendar_days,
                value=common_days,
                threshold=protocol.min_oos_calendar_days,
                detail="Common future holdout calendar coverage.",
            ),
            _gate(
                "candidate_trade_count",
                len(candidate) >= protocol.min_candidate_trades,
                value=len(candidate),
                threshold=protocol.min_candidate_trades,
                detail="Candidate common-window holdout trades.",
            ),
            _gate(
                "baseline_trade_count",
                len(baseline) >= protocol.min_baseline_trades,
                value=len(baseline),
                threshold=protocol.min_baseline_trades,
                detail="Baseline common-window holdout trades.",
            ),
            _gate(
                "common_symbol_count",
                len(alignment["common_symbols"]) >= protocol.min_common_symbols,
                value=len(alignment["common_symbols"]),
                threshold=protocol.min_common_symbols,
                detail="Common candidate/baseline symbols.",
            ),
            _gate(
                "candidate_expectancy",
                candidate_mean > protocol.min_candidate_mean_r,
                value=candidate_mean,
                threshold=protocol.min_candidate_mean_r,
                detail="Future candidate mean R must be positive.",
            ),
            _gate(
                "candidate_vs_baseline",
                candidate_mean - baseline_mean > protocol.min_candidate_vs_baseline_mean_r,
                value=candidate_mean - baseline_mean,
                threshold=protocol.min_candidate_vs_baseline_mean_r,
                detail="Candidate must beat the same-window baseline.",
            ),
            _gate(
                "walk_forward",
                wf["passed"],
                value=wf["positive_fold_share"],
                threshold=protocol.min_positive_walk_forward_share,
                detail="Every preregistered chronological fold must remain robust.",
            ),
            _gate(
                "symbol_out",
                symbol_out["passed"],
                value=symbol_out["passed"],
                threshold=True,
                detail="Every leave-one-symbol-out portfolio must retain edge.",
            ),
            _gate(
                "regime_robustness",
                regimes["passed"],
                value=len(regimes["common_regimes"]),
                threshold=protocol.min_regimes,
                detail="Edge must survive every sufficiently populated regime.",
            ),
            _gate(
                "monthly_block_permutation",
                permutation["defined"] and permutation["passed"],
                value=permutation.get("p_value"),
                threshold=protocol.family_wise_alpha,
                detail="Paired monthly mean-R sign-flip test.",
            ),
            _gate(
                "multiple_testing",
                adjusted_p is not None and adjusted_p <= protocol.family_wise_alpha,
                value=adjusted_p,
                threshold=protocol.family_wise_alpha,
                detail="Bonferroni family-wise adjusted p-value.",
            ),
            _gate(
                "parameter_perturbation",
                variants["passed"],
                value=len(variants["variants"]),
                threshold=protocol.min_parameter_variants,
                detail="Distinct preregistered parameter variants must retain expectancy.",
            ),
        ]
    except (KeyError, TypeError, OOSContractError, ValueError) as exc:
        data_errors.append(str(exc))

    failed = [gate["name"] for gate in gates if not gate["passed"]]
    if data_errors or failed:
        payload = _status_payload(
            prereg=prereg,
            prereg_sha=prereg_sha,
            generated_at=generated,
            gates=gates,
            data_quality_errors=data_errors,
            diagnostics=diagnostics,
        )
        return payload, _write_status(payload, status_dir)

    candidate_sha = _sha256_file(candidate_path)
    baseline_sha = _sha256_file(baseline_path)
    _, preregistration_rel = _repo_relative_file(
        repo_root, Path(preregistration_path), "preregistration"
    )
    payload = {
        "schema_version": EVIDENCE_SCHEMA,
        "generated_at": generated.isoformat(),
        "verdict": "PROMOTION_AUTHORIZED",
        "evidence_class": "INDEPENDENT_OOS",
        "independent_oos": True,
        "deployment_authorized": True,
        "strategy": prereg["strategy"],
        "authorization": prereg["authorization_ceiling"],
        "evaluation_protocol": {
            "pre_registered": True,
            "selection_data_excluded": True,
            "holdout_unseen_until_final": True,
            "selection_cutoff": prereg["selection_cutoff"],
            "oos_start": prereg["oos_start"],
            "oos_end": diagnostics["alignment"]["entry_end"],
            "preregistration_sha256": prereg_sha,
            "preregistration": {
                "path": preregistration_rel,
                "sha256": prereg_sha,
            },
            "protocol_artifact": prereg["protocol_artifact"],
        },
        "evaluator": {
            "path": TRUSTED_EVALUATOR_PATH,
            "code_sha256": prereg["evaluator"]["code_sha256"],
            "module_path": prereg["evaluator"]["module_path"],
            "module_sha256": prereg["evaluator"]["module_sha256"],
        },
        "inputs": {
            "candidate_tf": prereg["candidate_tf"],
            "baseline_tf": prereg["baseline_tf"],
            "candidate_pool": {
                "path": snapshots["candidate"]["path"],
                "sha256": candidate_sha,
                "provenance": current_provenance[0],
            },
            "baseline_pool": {
                "path": snapshots["baseline"]["path"],
                "sha256": baseline_sha,
                "provenance": current_provenance[1],
            },
            "parameter_variant_pools": [
                {
                    "variant_id": item["variant_id"],
                    "parameter_delta": item["parameter_delta"],
                    "path": item["path"],
                    "sha256": _sha256_file(Path(path)),
                    "provenance": provenance,
                }
                for item, path, provenance in zip(
                    pinned_variants,
                    supplied_variants,
                    current_provenance[2:],
                    strict=True,
                )
            ],
            "strategy_module": prereg["strategy_module"],
            "discovery_artifact": prereg["discovery"],
        },
        "data_quality": {"valid": True, "errors": [], "alignment": diagnostics["alignment"]},
        "candidate": {"tf": prereg["candidate_tf"], "oos": diagnostics["candidate"]},
        "baseline": {"tf": prereg["baseline_tf"], "oos": diagnostics["baseline"]},
        "statistical_tests": {
            "monthly_block_permutation": diagnostics["monthly_block_permutation"],
            "multiple_testing": diagnostics["multiple_testing"],
        },
        "robustness": {
            "walk_forward": diagnostics["walk_forward"],
            "symbol_out": diagnostics["symbol_out"],
            "regime": diagnostics["regime_robustness"],
            "parameter_perturbation": diagnostics["parameter_perturbation"],
        },
        "gates": gates,
        "failed_gates": [],
        "producer": {
            "contract": CANONICAL_EVALUATOR_CONTRACT,
            "preregistration_path": preregistration_rel,
            "preregistration_sha256": prereg_sha,
            "protocol_path": prereg["protocol_artifact"]["path"],
            "protocol_sha256": prereg["protocol_artifact"]["sha256"],
            "evaluator_path": prereg["evaluator"]["path"],
            "evaluator_sha256": prereg["evaluator"]["code_sha256"],
            "evaluator_module_path": prereg["evaluator"]["module_path"],
            "evaluator_module_sha256": prereg["evaluator"]["module_sha256"],
        },
    }
    payload["producer"]["payload_sha256"] = _evidence_payload_sha(payload)
    raw = _canonical_json(payload)
    name = _artifact_name(
        f"{prereg['strategy']}-{prereg['candidate_tf']}-independent-oos", generated, raw
    )
    evidence_path = Path(evidence_dir) / name
    try:
        evidence_path.resolve().relative_to(repo_root)
    except ValueError as exc:
        raise OOSContractError("evidence output must live inside repo_root") from exc
    created = _atomic_content_write(evidence_path, raw)

    # Verify the exact downstream consumer contract before returning a positive result.
    try:
        if not _downstream_validate:
            return payload, evidence_path
        from price_action.lab.tf_shadow_promotion import validate_evidence

        validate_evidence(
            evidence_path,
            evidence_dir=Path(evidence_dir),
            repo_root=repo_root,
        )
    except Exception as exc:
        if created:
            with suppress(FileNotFoundError):
                evidence_path.unlink()
        status = _status_payload(
            prereg=prereg,
            prereg_sha=prereg_sha,
            generated_at=generated,
            gates=gates,
            data_quality_errors=[f"downstream evidence contract rejected artifact: {exc}"],
            diagnostics=diagnostics,
        )
        return status, _write_status(status, status_dir)
    return payload, evidence_path


def verify_canonical_evidence_chain(
    evidence_path: Path,
    *,
    repo_root: Path,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Replay the canonical evaluator and require byte-semantic equivalence.

    A plausible-looking JSON object is insufficient.  The preregistration,
    protocol, evaluator wrapper/module, strategy, pool-builder receipts, raw
    OHLCV prefixes, and effective parameter deltas must all validate, and a
    deterministic evaluator replay must reproduce the complete evidence
    payload.
    """

    repo_root = Path(repo_root).resolve()
    resolved, _ = _repo_relative_file(repo_root, Path(evidence_path), "OOS evidence")
    loaded, _ = _load_json_file(resolved, "OOS evidence")
    if payload is not None and loaded != payload:
        raise OOSContractError("validated evidence payload differs from file content")
    payload = loaded
    if payload.get("schema_version") != EVIDENCE_SCHEMA:
        raise OOSContractError(f"canonical evidence schema must be {EVIDENCE_SCHEMA!r}")
    producer = payload.get("producer")
    if not isinstance(producer, dict):
        raise OOSContractError("canonical evidence producer receipt is missing")
    if producer.get("contract") != CANONICAL_EVALUATOR_CONTRACT:
        raise OOSContractError("canonical evaluator contract identity mismatch")
    if producer.get("payload_sha256") != _evidence_payload_sha(payload):
        raise OOSContractError("canonical evaluator payload receipt hash mismatch")
    prereg_rel = producer.get("preregistration_path")
    prereg_path = _pinned_repo_file(repo_root, prereg_rel, "evidence preregistration")
    prereg, prereg_sha = validate_preregistration(prereg_path, repo_root=repo_root)
    protocol = payload.get("evaluation_protocol")
    if not isinstance(protocol, dict):
        raise OOSContractError("evaluation_protocol must be an object")
    expected_prereg = {"path": prereg_rel, "sha256": prereg_sha}
    if protocol.get("preregistration") != expected_prereg:
        raise OOSContractError("evidence preregistration path/hash pin mismatch")
    if protocol.get("preregistration_sha256") != prereg_sha:
        raise OOSContractError("legacy preregistration hash pin mismatch")
    if producer.get("preregistration_sha256") != prereg_sha:
        raise OOSContractError("producer preregistration hash pin mismatch")
    if protocol.get("protocol_artifact") != prereg.get("protocol_artifact"):
        raise OOSContractError("evidence protocol artifact pin mismatch")
    expected_producer = {
        "contract": CANONICAL_EVALUATOR_CONTRACT,
        "preregistration_path": prereg_rel,
        "preregistration_sha256": prereg_sha,
        "protocol_path": prereg["protocol_artifact"]["path"],
        "protocol_sha256": prereg["protocol_artifact"]["sha256"],
        "evaluator_path": prereg["evaluator"]["path"],
        "evaluator_sha256": prereg["evaluator"]["code_sha256"],
        "evaluator_module_path": prereg["evaluator"]["module_path"],
        "evaluator_module_sha256": prereg["evaluator"]["module_sha256"],
        "payload_sha256": producer.get("payload_sha256"),
    }
    if producer != expected_producer:
        raise OOSContractError("canonical evaluator producer identity differs from preregistration")
    if payload.get("evaluator") != prereg.get("evaluator"):
        raise OOSContractError("evidence evaluator identity differs from preregistration")
    if payload.get("strategy") != prereg.get("strategy"):
        raise OOSContractError("evidence strategy differs from preregistration")
    inputs = payload.get("inputs")
    if not isinstance(inputs, dict):
        raise OOSContractError("evidence inputs must be an object")
    if inputs.get("strategy_module") != prereg.get("strategy_module"):
        raise OOSContractError("evidence strategy module differs from preregistration")
    if inputs.get("discovery_artifact") != prereg.get("discovery"):
        raise OOSContractError("evidence discovery identity differs from preregistration")
    generated = _utc(payload.get("generated_at"), "evidence.generated_at")

    # Full deterministic replay is the final authorship gate.  It also
    # validates the evidence-pinned provenance prefix within today's longer
    # append-only chain and recalculates every metric, test, gate, and
    # authorization field from hermetically rebuilt historical pool bytes.
    with tempfile.TemporaryDirectory(prefix=".tf-evidence-verify-", dir=repo_root) as temp_name:
        temp = Path(temp_name)
        prereg_pools = prereg.get("pools", {})
        pool_specs: list[tuple[str, Any, Any, str]] = [
            (
                "candidate",
                inputs.get("candidate_pool"),
                prereg_pools.get("candidate"),
                str(prereg.get("candidate_tf")),
            ),
            (
                "baseline",
                inputs.get("baseline_pool"),
                prereg_pools.get("baseline"),
                str(prereg.get("baseline_tf")),
            ),
        ]
        evidence_variants = inputs.get("parameter_variant_pools")
        prereg_variants = prereg_pools.get("parameter_variants")
        if not isinstance(evidence_variants, list) or not isinstance(prereg_variants, list):
            raise OOSContractError("evidence parameter variant inputs must be a list")
        if len(evidence_variants) != len(prereg_variants):
            raise OOSContractError("evidence parameter variant count changed")
        for evidence_variant, prereg_variant in zip(
            evidence_variants, prereg_variants, strict=True
        ):
            if not isinstance(evidence_variant, dict) or not isinstance(prereg_variant, dict):
                raise OOSContractError("parameter variant input must be an object")
            for field in ("variant_id", "parameter_delta", "path"):
                if evidence_variant.get(field) != prereg_variant.get(field):
                    raise OOSContractError(f"evidence parameter variant {field} changed")
            pool_specs.append(
                (
                    str(prereg_variant.get("variant_id")),
                    evidence_variant,
                    prereg_variant,
                    str(prereg.get("candidate_tf")),
                )
            )

        replay_inputs: dict[str, tuple[Path, dict[str, Any]]] = {}
        for index, (label, evidence_pool, prereg_pool, timeframe) in enumerate(pool_specs):
            if not isinstance(evidence_pool, dict) or not isinstance(prereg_pool, dict):
                raise OOSContractError(f"evidence {label} pool input must be an object")
            expected_pool_fields = {"path", "sha256", "provenance"}
            if label not in {"candidate", "baseline"}:
                expected_pool_fields |= {"variant_id", "parameter_delta"}
            if set(evidence_pool) != expected_pool_fields:
                raise OOSContractError(f"evidence {label} pool input fields are not canonical")
            if evidence_pool.get("path") != prereg_pool.get("path"):
                raise OOSContractError(f"evidence {label} pool path changed")
            logical_pool_path = _pinned_repo_file(
                repo_root, evidence_pool.get("path"), f"evidence {label} pool"
            )
            replay_raw, _replay_frame, provenance = _validate_evidence_provenance_summary(
                evidence_pool.get("provenance"),
                repo_root=repo_root,
                strategy=str(prereg.get("strategy")),
                timeframe=timeframe,
                pool_path=logical_pool_path,
                pool_sha256=evidence_pool.get("sha256"),
                selection_pin=prereg_pool.get("provenance"),
                as_of=generated,
            )
            replay_path = temp / f"pool-{index}-{label}-{timeframe}.pkl"
            _atomic_replace(replay_path, replay_raw)
            replay_inputs[label] = (replay_path, provenance)
        replayed, _ = evaluate_preregistration(
            preregistration_path=prereg_path,
            repo_root=repo_root,
            evidence_dir=temp / "evidence",
            status_dir=temp / "status",
            as_of=generated,
            _downstream_validate=False,
            _replay_inputs=replay_inputs,
        )
    if replayed.get("verdict") != "PROMOTION_AUTHORIZED":
        raise OOSContractError("canonical evaluator replay did not authorize promotion")
    if replayed != payload:
        raise OOSContractError("evidence does not equal canonical evaluator replay output")
    return prereg


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[3])
    subparsers = parser.add_subparsers(dest="command", required=True)
    prereg = subparsers.add_parser("preregister")
    prereg.add_argument("--discovery", type=Path, required=True)
    prereg.add_argument("--candidate-pool", type=Path)
    prereg.add_argument("--baseline-pool", type=Path)
    prereg.add_argument("--variant-pool", type=Path, action="append", default=[])
    prereg.add_argument("--protocol", type=Path)
    prereg.add_argument("--oos-start")
    prereg.add_argument("--output-dir", type=Path, required=True)
    provenance = subparsers.add_parser("record-pool-provenance")
    provenance.add_argument("--pool", type=Path, required=True)
    provenance.add_argument("--raw-ohlcv", type=Path, required=True)
    provenance.add_argument("--builder", type=Path, required=True)
    provenance.add_argument("--strategy", required=True)
    provenance.add_argument("--timeframe", required=True)
    provenance.add_argument("--logical-id", required=True)
    provenance.add_argument("--parameter-family", required=True)
    provenance.add_argument(
        "--parameter-role", choices=("candidate", "baseline", "variant"), required=True
    )
    provenance.add_argument("--parameters-json", required=True)
    provenance.add_argument("--variant-of")
    provenance.add_argument("--declared-delta-json", default="{}")
    provenance.add_argument("--generated-at")
    evaluate = subparsers.add_parser("evaluate")
    evaluate.add_argument("--preregistration", type=Path, required=True)
    evaluate.add_argument("--candidate-pool", type=Path)
    evaluate.add_argument("--baseline-pool", type=Path)
    evaluate.add_argument("--variant-pool", type=Path, action="append")
    evaluate.add_argument("--as-of")
    evaluate.add_argument("--evidence-dir", type=Path, required=True)
    evaluate.add_argument("--status-dir", type=Path, required=True)
    return parser.parse_args(argv)


def cli_main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        if args.command == "record-pool-provenance":
            try:
                parameters = json.loads(args.parameters_json)
                declared_delta = json.loads(args.declared_delta_json)
            except json.JSONDecodeError as exc:
                raise OOSContractError(f"parameter JSON is invalid: {exc}") from exc
            payload, path = record_pool_provenance(
                pool_path=args.pool,
                raw_ohlcv_path=args.raw_ohlcv,
                builder_path=args.builder,
                repo_root=args.repo_root,
                strategy=args.strategy,
                timeframe=args.timeframe,
                logical_id=args.logical_id,
                parameter_family=args.parameter_family,
                parameter_role=args.parameter_role,
                parameters=parameters,
                variant_of=args.variant_of,
                declared_delta=declared_delta,
                generated_at=(
                    _utc(args.generated_at, "generated_at") if args.generated_at else None
                ),
            )
        elif args.command == "preregister":
            payload, path = create_preregistration(
                discovery_path=args.discovery,
                repo_root=args.repo_root,
                output_dir=args.output_dir,
                candidate_pool=args.candidate_pool,
                baseline_pool=args.baseline_pool,
                variant_pools=args.variant_pool,
                protocol_path=args.protocol,
                oos_start=_utc(args.oos_start, "oos_start") if args.oos_start else None,
            )
        else:
            payload, path = evaluate_preregistration(
                preregistration_path=args.preregistration,
                repo_root=args.repo_root,
                evidence_dir=args.evidence_dir,
                status_dir=args.status_dir,
                candidate_pool=args.candidate_pool,
                baseline_pool=args.baseline_pool,
                variant_pools=args.variant_pool,
                as_of=_utc(args.as_of, "as_of") if args.as_of else None,
            )
    except OOSContractError as exc:
        print(json.dumps({"status": "HOLD", "error": str(exc)}, sort_keys=True))
        return 2
    print(
        json.dumps(
            {"status": payload.get("status", payload.get("verdict")), "path": str(path)},
            sort_keys=True,
        )
    )
    return 2 if payload.get("status") == "HOLD" else 0


__all__ = [
    "OOSContractError",
    "OOSProtocol",
    "create_preregistration",
    "evaluate_preregistration",
    "load_protocol",
    "record_pool_provenance",
    "validate_preregistration",
    "verify_canonical_evidence_chain",
]
