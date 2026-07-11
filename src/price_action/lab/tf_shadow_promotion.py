"""Fail-closed TF evidence consumer for signal-only shadow specifications.

This module closes the research-report-to-shadow-spec wiring without granting
an order path.  It deliberately does *not* run a daemon, submit an exchange
order, create a launchd job, or bootstrap a process.  Its only accepted input
is a content-addressed ``tf-independent-oos-v2`` artifact whose explicit
authorization scope is ``SIGNAL_ONLY_SHADOW``.

Raw TF exploration recommendations and the current
``tf-robustness-v2``/``DESCRIPTIVE_SCREEN_PASS`` artifacts are research
evidence only and can never pass this consumer.
"""

from __future__ import annotations

import ast
import fcntl
import hashlib
import json
import math
import os
import re
import tempfile
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]

EVIDENCE_SCHEMA = "tf-independent-oos-v2"
SHADOW_CONFIG_SCHEMA = "tf-signal-shadow-config-v2"
SHADOW_MANIFEST_SCHEMA = "tf-signal-shadow-manifest-v2"
SCAN_SCHEMA = "tf-shadow-promotion-scan-v1"
AUTHORIZATION_SCOPE = "SIGNAL_ONLY_SHADOW"

SUPPORTED_TFS = frozenset({"5m", "15m", "30m", "1h", "4h", "1d"})
_STRATEGY_RE = re.compile(r"^[a-z][a-z0-9_]{2,63}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_IMMUTABLE_NAME_RE = re.compile(
    r"^(?P<strategy>[a-z][a-z0-9_]{2,63})-"
    r"(?P<tf>5m|15m|30m|1h|4h|1d)-independent-oos-"
    r"(?P<stamp>\d{8}T\d{6}\.\d{6}Z)-(?P<sha>[0-9a-f]{12})\.json$"
)
_MAX_EVIDENCE_BYTES = 8 * 1024 * 1024
_ACTIVE_SHADOW_STATUSES = frozenset({"SHADOW_ACTIVE_AUTHORIZED"})
_TRUSTED_EVALUATOR_PATH = "scripts/tf_independent_oos_runner.py"
_TRUSTED_EVALUATOR_MODULE_PATH = "src/price_action/lab/tf_independent_oos.py"
CAPABILITY_PROFILE = "PURE_SIGNAL_SHADOW_V1"
ALLOWED_SIGNAL_SHADOW_STRATEGIES = frozenset(
    {
        "vsa_climax_test",
        "brooks_failed_breakout",
        "anchored_vwap_reversal",
        "engulfing_continuation",
    }
)
CAPABILITY_CONTRACT = {
    "profile": CAPABILITY_PROFILE,
    "network_allowed": False,
    "socket_allowed": False,
    "subprocess_allowed": False,
    "filesystem_write_allowed": False,
    "dynamic_code_allowed": False,
    "scheduler_tick_requires_queue_authorization": True,
}
_TRANSITIVE_STRATEGY_PATHS = (
    "src/price_action/__init__.py",
    "src/price_action/contracts.py",
    "src/price_action/logging_config.py",
    "src/price_action/runtime_paths.py",
    "src/price_action/settings.py",
    "src/price_action/strategies/__init__.py",
    "src/price_action/strategies/base.py",
    "src/price_action/strategies/classic_pa.py",
    "src/price_action/strategies/manifest_loader.py",
    "src/price_action/lab/tf_signal_shadow_worker.py",
)


class PromotionError(RuntimeError):
    """Base error for a rejected or conflicting shadow promotion."""


class EvidenceRejectedError(PromotionError):
    """The source artifact does not satisfy the immutable evidence contract."""

    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__("; ".join(errors))


class OutputConflictError(PromotionError):
    """A deterministic output path already contains different content."""


@dataclass(frozen=True)
class ValidatedEvidence:
    """Strictly validated, content-addressed promotion evidence."""

    path: Path
    payload: dict[str, Any]
    sha256: str
    generated_at: datetime
    strategy: str
    candidate_tf: str
    baseline_tf: str


@dataclass(frozen=True)
class ShadowPaths:
    """All candidate-specific outputs; none is a process/bootstrap artifact."""

    hypothesis: Path
    config: Path
    journal: Path
    manifest: Path
    deploy_queue: Path
    authorization: Path


def _sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _parse_utc(value: Any, field: str, errors: list[str]) -> datetime | None:
    if not isinstance(value, str):
        errors.append(f"{field} must be an ISO-8601 string")
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        errors.append(f"{field} is not a valid ISO-8601 timestamp")
        return None
    if parsed.tzinfo is None:
        errors.append(f"{field} must include a UTC offset")
        return None
    return parsed.astimezone(UTC)


def _nested(payload: dict[str, Any], *keys: str) -> Any:
    value: Any = payload
    for key in keys:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value


def _require_sha(value: Any, field: str, errors: list[str]) -> None:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        errors.append(f"{field} must be a lowercase 64-character sha256")


def _strict_true(value: Any, field: str, errors: list[str]) -> None:
    if value is not True:
        errors.append(f"{field} must be boolean true")


def validate_evidence(
    path: Path,
    *,
    evidence_dir: Path,
    repo_root: Path | None = None,
) -> ValidatedEvidence:
    """Validate an independent-OOS authorization artifact.

    The filename is content-addressed: its final 12 hex characters must match
    the SHA-256 of the exact file bytes.  This both distinguishes immutable
    run artifacts from mutable ``latest``/date-only reports and makes any
    post-write edit fail closed.
    """

    path = Path(path)
    evidence_root = Path(evidence_dir).resolve()
    errors: list[str] = []

    if path.is_symlink():
        raise EvidenceRejectedError(["evidence path must not be a symlink"])
    try:
        resolved = path.resolve(strict=True)
    except FileNotFoundError as exc:
        raise EvidenceRejectedError(["evidence file does not exist"]) from exc
    if resolved.parent != evidence_root:
        raise EvidenceRejectedError(["evidence must be a direct child of the configured directory"])
    if not resolved.is_file():
        raise EvidenceRejectedError(["evidence path is not a regular file"])

    raw = resolved.read_bytes()
    if len(raw) > _MAX_EVIDENCE_BYTES:
        raise EvidenceRejectedError([f"evidence exceeds {_MAX_EVIDENCE_BYTES} bytes"])
    artifact_sha = _sha256_bytes(raw)
    name_match = _IMMUTABLE_NAME_RE.fullmatch(resolved.name)
    if name_match is None:
        errors.append(
            "filename is not immutable/content-addressed; expected "
            "<strategy>-<tf>-independent-oos-<UTC timestamp>-<sha12>.json"
        )
    elif name_match.group("sha") != artifact_sha[:12]:
        errors.append("filename sha12 does not match artifact content sha256")

    try:
        payload = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise EvidenceRejectedError([f"evidence is not valid UTF-8 JSON: {exc}"]) from exc
    if not isinstance(payload, dict):
        raise EvidenceRejectedError(["evidence JSON root must be an object"])
    if raw != _canonical_json(payload).encode("utf-8"):
        errors.append("evidence bytes are not the canonical producer serialization")

    if payload.get("schema_version") != EVIDENCE_SCHEMA:
        errors.append(f"schema_version must equal {EVIDENCE_SCHEMA!r}")
    if payload.get("evidence_class") != "INDEPENDENT_OOS":
        errors.append("evidence_class must equal 'INDEPENDENT_OOS'")
    if payload.get("verdict") != "PROMOTION_AUTHORIZED":
        errors.append("verdict must equal 'PROMOTION_AUTHORIZED'")
    _strict_true(payload.get("independent_oos"), "independent_oos", errors)
    _strict_true(payload.get("deployment_authorized"), "deployment_authorized", errors)
    _strict_true(_nested(payload, "data_quality", "valid"), "data_quality.valid", errors)

    if payload.get("failed_gates") != []:
        errors.append("failed_gates must be an empty list")
    gates = payload.get("gates")
    if not isinstance(gates, list) or not gates:
        errors.append("gates must be a non-empty list")
    elif any(not isinstance(gate, dict) or gate.get("passed") is not True for gate in gates):
        errors.append("every gate must have boolean passed=true")

    strategy = payload.get("strategy")
    candidate_tf = _nested(payload, "inputs", "candidate_tf")
    baseline_tf = _nested(payload, "inputs", "baseline_tf")
    if not isinstance(strategy, str) or not _STRATEGY_RE.fullmatch(strategy):
        errors.append("strategy must be a safe lowercase strategy slug")
        strategy = "invalid_strategy"
    if candidate_tf not in SUPPORTED_TFS:
        errors.append(f"inputs.candidate_tf must be one of {sorted(SUPPORTED_TFS)}")
        candidate_tf = "invalid_tf"
    if baseline_tf not in SUPPORTED_TFS:
        errors.append(f"inputs.baseline_tf must be one of {sorted(SUPPORTED_TFS)}")
        baseline_tf = "invalid_tf"
    if candidate_tf == baseline_tf:
        errors.append("candidate and baseline timeframes must differ")
    if _nested(payload, "candidate", "tf") != candidate_tf:
        errors.append("candidate.tf must match inputs.candidate_tf")
    if _nested(payload, "baseline", "tf") != baseline_tf:
        errors.append("baseline.tf must match inputs.baseline_tf")

    candidate_n = _nested(payload, "candidate", "oos", "n_trades")
    if (
        isinstance(candidate_n, bool)
        or not isinstance(candidate_n, (int, float))
        or not math.isfinite(float(candidate_n))
        or candidate_n <= 0
    ):
        errors.append("candidate.oos.n_trades must be a positive finite number")

    _require_sha(_nested(payload, "inputs", "candidate_pool", "sha256"), "candidate pool", errors)
    _require_sha(_nested(payload, "inputs", "baseline_pool", "sha256"), "baseline pool", errors)
    _require_sha(
        _nested(payload, "inputs", "strategy_module", "sha256"),
        "strategy module",
        errors,
    )
    expected_strategy_path = f"src/price_action/strategies/{strategy}.py"
    if _nested(payload, "inputs", "strategy_module", "path") != expected_strategy_path:
        errors.append(f"inputs.strategy_module.path must equal {expected_strategy_path!r}")
    if _nested(payload, "evaluator", "path") != _TRUSTED_EVALUATOR_PATH:
        errors.append(f"evaluator.path must equal {_TRUSTED_EVALUATOR_PATH!r}")
    _require_sha(_nested(payload, "evaluator", "code_sha256"), "evaluator.code_sha256", errors)
    if _nested(payload, "evaluator", "module_path") != _TRUSTED_EVALUATOR_MODULE_PATH:
        errors.append(f"evaluator.module_path must equal {_TRUSTED_EVALUATOR_MODULE_PATH!r}")
    _require_sha(
        _nested(payload, "evaluator", "module_sha256"),
        "evaluator.module_sha256",
        errors,
    )

    if _nested(payload, "authorization", "scope") != AUTHORIZATION_SCOPE:
        errors.append(f"authorization.scope must equal {AUTHORIZATION_SCOPE!r}")
    if _nested(payload, "authorization", "live_order_authorized") is not False:
        errors.append("authorization.live_order_authorized must be boolean false")
    principal_auth = _nested(payload, "authorization", "principal_authorization")
    if not isinstance(principal_auth, dict):
        errors.append("authorization.principal_authorization must be an object")
    else:
        if principal_auth.get("algorithm") != "Ed25519":
            errors.append("principal authorization algorithm must be Ed25519")
        public_path = principal_auth.get("public_key_path")
        if (
            not isinstance(public_path, str)
            or not public_path
            or Path(public_path).is_absolute()
            or ".." in Path(public_path).parts
        ):
            errors.append("principal public key path must be safe and repo-relative")
        _require_sha(
            principal_auth.get("public_key_sha256"),
            "principal public key sha256",
            errors,
        )
        validity = principal_auth.get("max_validity_seconds")
        if isinstance(validity, bool) or not isinstance(validity, int) or not 60 <= validity <= 604800:
            errors.append("principal authorization max validity is invalid")

    protocol = payload.get("evaluation_protocol")
    if not isinstance(protocol, dict):
        errors.append("evaluation_protocol must be an object")
        protocol = {}
    _strict_true(protocol.get("pre_registered"), "evaluation_protocol.pre_registered", errors)
    _strict_true(
        protocol.get("selection_data_excluded"),
        "evaluation_protocol.selection_data_excluded",
        errors,
    )
    _strict_true(
        protocol.get("holdout_unseen_until_final"),
        "evaluation_protocol.holdout_unseen_until_final",
        errors,
    )
    cutoff = _parse_utc(protocol.get("selection_cutoff"), "selection_cutoff", errors)
    oos_start = _parse_utc(protocol.get("oos_start"), "oos_start", errors)
    oos_end = _parse_utc(protocol.get("oos_end"), "oos_end", errors)
    _require_sha(
        protocol.get("preregistration_sha256"),
        "evaluation_protocol.preregistration_sha256",
        errors,
    )
    preregistration = protocol.get("preregistration")
    if not isinstance(preregistration, dict) or not isinstance(preregistration.get("path"), str):
        errors.append("evaluation_protocol.preregistration path/hash object is required")
    else:
        _require_sha(
            preregistration.get("sha256"),
            "evaluation_protocol.preregistration.sha256",
            errors,
        )
    protocol_artifact = protocol.get("protocol_artifact")
    if not isinstance(protocol_artifact, dict) or not isinstance(
        protocol_artifact.get("path"), str
    ):
        errors.append("evaluation_protocol.protocol_artifact path/hash object is required")
    else:
        _require_sha(
            protocol_artifact.get("sha256"),
            "evaluation_protocol.protocol_artifact.sha256",
            errors,
        )

    producer = payload.get("producer")
    if not isinstance(producer, dict):
        errors.append("canonical producer receipt is required")
    else:
        for field in (
            "preregistration_sha256",
            "protocol_sha256",
            "evaluator_sha256",
            "evaluator_module_sha256",
            "payload_sha256",
        ):
            _require_sha(producer.get(field), f"producer.{field}", errors)
        for field in (
            "contract",
            "preregistration_path",
            "protocol_path",
            "evaluator_path",
            "evaluator_module_path",
        ):
            if not isinstance(producer.get(field), str) or not producer[field]:
                errors.append(f"producer.{field} must be a non-empty string")
    if cutoff and oos_start and not oos_start > cutoff:
        errors.append("oos_start must be after selection_cutoff")
    if oos_start and oos_end and not oos_end > oos_start:
        errors.append("oos_end must be after oos_start")

    generated_at = _parse_utc(payload.get("generated_at"), "generated_at", errors)
    if generated_at is not None:
        if generated_at > datetime.now(UTC) + timedelta(minutes=5):
            errors.append("generated_at is implausibly in the future")
        if name_match is not None:
            expected_stamp = generated_at.strftime("%Y%m%dT%H%M%S.%fZ")
            if name_match.group("stamp") != expected_stamp:
                errors.append("filename timestamp does not match generated_at")

    if name_match is not None:
        if name_match.group("strategy") != strategy:
            errors.append("filename strategy does not match artifact strategy")
        if name_match.group("tf") != candidate_tf:
            errors.append("filename timeframe does not match candidate timeframe")

    if errors:
        raise EvidenceRejectedError(errors)
    if repo_root is not None:
        try:
            from price_action.lab.tf_independent_oos import verify_canonical_evidence_chain

            verify_canonical_evidence_chain(
                resolved,
                repo_root=Path(repo_root),
                payload=payload,
            )
        except Exception as exc:
            raise EvidenceRejectedError(
                [f"canonical evidence chain/replay rejected artifact: {exc}"]
            ) from exc
    assert generated_at is not None
    assert isinstance(strategy, str)
    assert isinstance(candidate_tf, str)
    assert isinstance(baseline_tf, str)
    return ValidatedEvidence(
        path=resolved,
        payload=payload,
        sha256=artifact_sha,
        generated_at=generated_at,
        strategy=strategy,
        candidate_tf=candidate_tf,
        baseline_tf=baseline_tf,
    )


def _candidate_id(evidence: ValidatedEvidence) -> str:
    producer_sha = _nested(evidence.payload, "producer", "payload_sha256")
    if not isinstance(producer_sha, str) or not _SHA256_RE.fullmatch(producer_sha):
        raise EvidenceRejectedError(["producer.payload_sha256 is required for candidate identity"])
    return f"tf-{evidence.strategy}-{evidence.candidate_tf}-{producer_sha[:12]}"


def _bot_name(evidence: ValidatedEvidence) -> str:
    strategy_short = evidence.strategy.replace("_", "-")[:30].rstrip("-")
    producer_sha = str(_nested(evidence.payload, "producer", "payload_sha256"))
    return f"tfshadow-{strategy_short}-{evidence.candidate_tf}-{producer_sha[:8]}"


def _paths_for(repo_root: Path, candidate_id: str) -> ShadowPaths:
    return ShadowPaths(
        # HypothesisRunner intentionally skips underscore-prefixed protocol
        # records. This evidence-final document must not re-enter the LLM
        # extraction/backtest queue and create a second selection loop.
        hypothesis=(
            repo_root
            / "memory"
            / "researcher"
            / "hypotheses"
            / f"_approved-shadow-{candidate_id}.md"
        ),
        config=repo_root / "configs" / "shadow" / f"{candidate_id}.yaml",
        journal=repo_root / "data" / "shadow" / f"{candidate_id}.duckdb",
        manifest=repo_root / "memory" / "researcher" / "shadow_specs" / f"{candidate_id}.json",
        deploy_queue=repo_root / "memory" / "researcher" / "deploy_queue.json",
        authorization=(
            repo_root
            / "memory"
            / "researcher"
            / "shadow_authorizations"
            / f"{candidate_id}.json"
        ),
    )


def _strategy_module_identity(repo_root: Path, evidence: ValidatedEvidence) -> tuple[Path, str]:
    """Require a local Strategy implementation and pin its source identity."""

    path = repo_root / "src" / "price_action" / "strategies" / f"{evidence.strategy}.py"
    if path.is_symlink() or not path.is_file():
        raise EvidenceRejectedError(
            [f"strategy module is missing or unsafe: {path.relative_to(repo_root)}"]
        )
    if evidence.strategy not in ALLOWED_SIGNAL_SHADOW_STRATEGIES:
        raise EvidenceRejectedError(
            [f"strategy is not allowlisted for {CAPABILITY_PROFILE}: {evidence.strategy}"]
        )
    raw = path.read_bytes()
    try:
        source = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise EvidenceRejectedError(["strategy module must be valid UTF-8 Python"]) from exc
    if re.search(r"^class\s+\w+\([^)]*\bStrategy\b[^)]*\):", source, re.MULTILINE) is None:
        raise EvidenceRejectedError(
            ["strategy module does not declare a concrete Strategy subclass"]
        )
    validate_strategy_capabilities(path, evidence.strategy)
    return path, _sha256_bytes(raw)


_ALLOWED_STRATEGY_IMPORTS = frozenset(
    {
        "__future__",
        "typing",
        "numpy",
        "pandas",
        "numba",
        "price_action.contracts",
        "price_action.logging_config",
        "price_action.strategies.base",
        "price_action.strategies.classic_pa",
    }
)
_FORBIDDEN_CALL_NAMES = frozenset({"open", "eval", "exec", "compile", "__import__"})
_FORBIDDEN_NUMPY_READS = frozenset(
    {"fromfile", "genfromtxt", "load", "loadtxt", "memmap", "open_memmap"}
)
_FORBIDDEN_ATTR_CALLS = frozenset(
    {
        "Popen",
        "call",
        "check_call",
        "check_output",
        "create_connection",
        "fork",
        "forkpty",
        "getaddrinfo",
        "fromfile",
        "genfromtxt",
        "load",
        "load_library",
        "loadtxt",
        "memmap",
        "open",
        "open_memmap",
        "popen",
        "read_bytes",
        "read_text",
        "run",
        "save",
        "savetxt",
        "savez",
        "savez_compressed",
        "socket",
        "system",
        "to_csv",
        "to_excel",
        "to_feather",
        "to_file",
        "to_hdf",
        "to_json",
        "to_parquet",
        "to_pickle",
        "to_sql",
        "write_bytes",
        "write_text",
    }
)


def _attribute_parts(node: ast.AST) -> list[str]:
    parts: list[str] = []
    current = node
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if isinstance(current, ast.Name):
        parts.append(current.id)
    return list(reversed(parts))


def validate_strategy_capabilities(path: Path, strategy: str) -> None:
    """Statically enforce the reviewed pure-strategy module contract."""

    if strategy not in ALLOWED_SIGNAL_SHADOW_STRATEGIES:
        raise EvidenceRejectedError(
            [f"strategy is not allowlisted for {CAPABILITY_PROFILE}: {strategy}"]
        )
    try:
        source = Path(path).read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
    except (OSError, UnicodeDecodeError, SyntaxError) as exc:
        raise EvidenceRejectedError([f"strategy capability scan failed: {exc}"]) from exc
    errors: list[str] = []
    forbidden_direct_names: set[str] = set()
    allowed_imports = set(_ALLOWED_STRATEGY_IMPORTS)
    if strategy == "engulfing_continuation":
        allowed_imports.update({"os", "logging"})
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name not in allowed_imports:
                    errors.append(f"strategy import is outside capability allowlist: {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            if node.level != 0 or node.module not in allowed_imports:
                errors.append(
                    f"strategy import is outside capability allowlist: {node.module or '<relative>'}"
                )
            if any(alias.name == "*" for alias in node.names):
                errors.append("wildcard strategy imports are forbidden")
            for alias in node.names:
                is_forbidden_reader = (
                    node.module == "pandas" and alias.name.startswith("read_")
                ) or (node.module == "numpy" and alias.name in _FORBIDDEN_NUMPY_READS)
                if is_forbidden_reader:
                    forbidden_direct_names.add(alias.asname or alias.name)
                    errors.append(
                        f"strategy capability import is forbidden: {node.module}.{alias.name}"
                    )
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id in (
                _FORBIDDEN_CALL_NAMES | forbidden_direct_names
            ):
                errors.append(f"strategy dynamic/I/O call is forbidden: {node.func.id}")
            if (
                isinstance(node.func, ast.Name)
                and node.func.id == "getattr"
                and len(node.args) >= 2
                and isinstance(node.args[1], ast.Constant)
                and isinstance(node.args[1].value, str)
                and (
                    node.args[1].value.startswith("read_")
                    or node.args[1].value in _FORBIDDEN_ATTR_CALLS
                )
            ):
                errors.append(
                    f"strategy dynamic capability lookup is forbidden: {node.args[1].value}"
                )
            parts = _attribute_parts(node.func)
            if parts:
                leaf = parts[-1]
                root = parts[0]
                if leaf in _FORBIDDEN_ATTR_CALLS or leaf.startswith(
                    ("spawn", "exec", "read_")
                ):
                    errors.append(f"strategy capability call is forbidden: {'.'.join(parts)}")
                if root == "os" and leaf != "getenv":
                    errors.append(f"strategy os capability is forbidden: {'.'.join(parts)}")
        elif isinstance(node, ast.Attribute):
            if node.attr in {
                "__class__",
                "__dict__",
                "__globals__",
                "__subclasses__",
            }:
                errors.append(f"strategy dunder traversal is forbidden: {node.attr}")
            if node.attr.startswith("read_") or node.attr in _FORBIDDEN_ATTR_CALLS:
                errors.append(f"strategy capability reference is forbidden: {node.attr}")
    if errors:
        raise EvidenceRejectedError(sorted(set(errors)))


def strategy_dependency_closure(
    repo_root: Path,
    *,
    strategy: str,
    timeframe: str,
) -> list[dict[str, Any]]:
    """Pin the exact reviewed source closure used inside the OS sandbox."""

    repo_root = Path(repo_root).resolve()
    paths = [
        f"src/price_action/strategies/{strategy}.py",
        *_TRANSITIVE_STRATEGY_PATHS,
    ]
    closure: list[dict[str, Any]] = []
    for relative in paths:
        path = repo_root / relative
        if path.is_symlink() or not path.is_file():
            raise EvidenceRejectedError([f"strategy dependency is missing or unsafe: {relative}"])
        raw = path.read_bytes()
        try:
            tree = ast.parse(raw.decode("utf-8"), filename=relative)
        except (UnicodeDecodeError, SyntaxError) as exc:
            raise EvidenceRejectedError([f"strategy dependency AST scan failed: {relative}"]) from exc
        closure.append(
            {
                "path": relative,
                "sha256": _sha256_bytes(raw),
                "ast_sha256": _sha256_bytes(
                    ast.dump(tree, annotate_fields=True, include_attributes=False).encode()
                ),
            }
        )
    manifest_rel = f"src/price_action/strategies/manifests/{strategy}_{timeframe}.yaml"
    manifest_path = repo_root / manifest_rel
    if manifest_path.is_symlink():
        raise EvidenceRejectedError([f"strategy manifest is a symlink: {manifest_rel}"])
    if manifest_path.is_file():
        closure.append(
            {
                "path": manifest_rel,
                "sha256": _sha256_bytes(manifest_path.read_bytes()),
                "kind": "manifest",
            }
        )
    else:
        closure.append({"path": manifest_rel, "absent": True, "kind": "manifest"})
    return sorted(closure, key=lambda row: str(row["path"]))


def _verify_evaluator_identity(repo_root: Path, evidence: ValidatedEvidence) -> None:
    """Require the exact local independent-OOS evaluator named by the evidence."""

    evaluator_path = repo_root / _TRUSTED_EVALUATOR_PATH
    if evaluator_path.is_symlink() or not evaluator_path.is_file():
        raise EvidenceRejectedError(
            [f"trusted independent-OOS evaluator is missing or unsafe: {_TRUSTED_EVALUATOR_PATH}"]
        )
    local_sha = _sha256_bytes(evaluator_path.read_bytes())
    tested_sha = _nested(evidence.payload, "evaluator", "code_sha256")
    if local_sha != tested_sha:
        raise EvidenceRejectedError(
            ["local independent-OOS evaluator sha256 differs from the evidence producer"]
        )
    module_path = repo_root / _TRUSTED_EVALUATOR_MODULE_PATH
    if module_path.is_symlink() or not module_path.is_file():
        raise EvidenceRejectedError(
            [
                "trusted independent-OOS evaluator module is missing or unsafe: "
                f"{_TRUSTED_EVALUATOR_MODULE_PATH}"
            ]
        )
    if _sha256_bytes(module_path.read_bytes()) != _nested(
        evidence.payload, "evaluator", "module_sha256"
    ):
        raise EvidenceRejectedError(
            ["local independent-OOS evaluator module sha256 differs from the evidence producer"]
        )


def _relative(path: Path, repo_root: Path) -> str:
    return str(path.resolve().relative_to(repo_root.resolve()))


def _canonical_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def _atomic_create_or_verify(path: Path, raw: bytes, *, mode: int = 0o600) -> bool:
    """Atomically create an immutable output, or verify byte-identical reuse."""

    if path.exists():
        if path.is_symlink() or not path.is_file():
            raise OutputConflictError(f"unsafe existing output path: {path}")
        if path.read_bytes() != raw:
            raise OutputConflictError(f"deterministic output conflict: {path}")
        return False

    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp_name, mode)
        try:
            os.link(tmp_name, path)
        except FileExistsError:
            if path.is_symlink() or not path.is_file() or path.read_bytes() != raw:
                raise OutputConflictError(
                    f"concurrent deterministic output conflict: {path}"
                ) from None
            return False
        return True
    finally:
        with suppress(FileNotFoundError):
            os.unlink(tmp_name)


def _render_config(
    evidence: ValidatedEvidence,
    *,
    candidate_id: str,
    bot_name: str,
    paths: ShadowPaths,
    repo_root: Path,
    strategy_module: Path,
    strategy_module_sha256: str,
    dependency_closure: list[dict[str, Any]],
) -> str:
    config = {
        "schema_version": SHADOW_CONFIG_SCHEMA,
        "candidate_id": candidate_id,
        "bot_name": bot_name,
        "strategy": evidence.strategy,
        "strategy_module": {
            "path": _relative(strategy_module, repo_root),
            "sha256": strategy_module_sha256,
        },
        "strategy_dependency_closure": dependency_closure,
        "timeframe": evidence.candidate_tf,
        "mode": {
            "run_mode": "shadow",
            "sim_only": True,
            "signal_only": True,
        },
        "exchange": {
            "enabled": False,
            "credentials_allowed": False,
            "market_data_private_api_allowed": False,
            "order_submit_allowed": False,
            "cancel_order_allowed": False,
        },
        "capabilities": dict(CAPABILITY_CONTRACT),
        "runtime": {
            "auto_start": False,
            "scheduler_tick_requires_queue_authorization": True,
            "launchd_bootstrap_allowed": False,
            "daemon_restart_allowed": False,
        },
        "principal_authorization": {
            "state": "SPEC_READY_NOT_RUNNING",
            "artifact": _relative(paths.authorization, repo_root),
            **evidence.payload["authorization"]["principal_authorization"],
        },
        "journal": {
            "path": _relative(paths.journal, repo_root),
            "namespace": candidate_id,
        },
        "evidence": {
            "artifact": _relative(evidence.path, repo_root),
            "artifact_sha256": evidence.sha256,
            "independent_oos": True,
            "deployment_authorized": True,
            "authorization_scope": AUTHORIZATION_SCOPE,
        },
    }
    return yaml.safe_dump(config, sort_keys=True, allow_unicode=True)


def _render_hypothesis(
    evidence: ValidatedEvidence,
    *,
    candidate_id: str,
    bot_name: str,
    strategy_module_sha256: str,
) -> str:
    created = evidence.generated_at.isoformat().replace("+00:00", "Z")
    return (
        "---\n"
        f"doc_id: researcher-{candidate_id}\n"
        "doc_type: hypothesis\n"
        "agent_id: tf_shadow_promotion\n"
        f"created_at: {created}\n"
        "status: APPROVED_SIGNAL_ONLY_SHADOW\n"
        "confidence: high\n"
        "depends_on: []\n"
        "blocks: []\n"
        "requested_review_from: []\n"
        "tags: [hypothesis, tf, independent-oos, signal-only-shadow]\n"
        f"source_artifact_sha256: {evidence.sha256}\n"
        "---\n\n"
        f"# TF Shadow Hypothesis — `{evidence.strategy}` on `{evidence.candidate_tf}`\n\n"
        "## Decision\n\n"
        f"Immutable independent-OOS evidence authorizes candidate `{candidate_id}` for "
        "a **signal-only shadow specification**. It does not authorize paper, testnet, "
        "or live exchange orders.\n\n"
        "## Locked identity\n\n"
        f"- Strategy: `{evidence.strategy}`\n"
        f"- Candidate TF: `{evidence.candidate_tf}`\n"
        f"- Baseline TF: `{evidence.baseline_tf}`\n"
        f"- Bot name: `{bot_name}`\n"
        f"- Strategy module SHA-256: `{strategy_module_sha256}`\n"
        f"- Evidence SHA-256: `{evidence.sha256}`\n\n"
        "## Safety boundary\n\n"
        "- `sim_only=true`\n"
        "- `signal_only=true`\n"
        "- exchange access and order submission disabled\n"
        "- no launchd bootstrap and no automatic process start\n"
        "- separate candidate-specific journal namespace\n"
    )


def _manifest_payload(
    evidence: ValidatedEvidence,
    *,
    candidate_id: str,
    bot_name: str,
    paths: ShadowPaths,
    repo_root: Path,
    strategy_module: Path,
    strategy_module_sha256: str,
    dependency_closure: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "schema_version": SHADOW_MANIFEST_SCHEMA,
        "candidate_id": candidate_id,
        "bot_name": bot_name,
        "strategy": evidence.strategy,
        "timeframe": evidence.candidate_tf,
        "created_at": evidence.generated_at.isoformat(),
        "source": {
            "artifact": _relative(evidence.path, repo_root),
            "artifact_sha256": evidence.sha256,
            "schema_version": EVIDENCE_SCHEMA,
            "strategy_module": _relative(strategy_module, repo_root),
            "strategy_module_sha256": strategy_module_sha256,
            "strategy_dependency_closure": dependency_closure,
        },
        "artifacts": {
            "hypothesis": _relative(paths.hypothesis, repo_root),
            "config": _relative(paths.config, repo_root),
            "journal": _relative(paths.journal, repo_root),
        },
        "safety": {
            "run_mode": "shadow",
            "sim_only": True,
            "signal_only": True,
            "exchange_enabled": False,
            "order_submit_allowed": False,
            "live_order_authorized": False,
            "capability_profile": CAPABILITY_PROFILE,
        },
        "runtime": {
            "state": "SPEC_READY_NOT_RUNNING",
            "auto_start": False,
            "scheduler_tick_requires_queue_authorization": True,
            "launchd_bootstrap_allowed": False,
            "daemon_restart_allowed": False,
        },
        "principal_authorization": {
            "artifact": _relative(paths.authorization, repo_root),
            **evidence.payload["authorization"]["principal_authorization"],
        },
    }


def _validate_safety(config_text: str, manifest: dict[str, Any]) -> None:
    """Last in-process tripwire before any candidate output is written."""

    config = yaml.safe_load(config_text)
    checks = (
        config.get("mode", {}).get("sim_only") is True,
        config.get("mode", {}).get("signal_only") is True,
        config.get("exchange", {}).get("enabled") is False,
        config.get("exchange", {}).get("order_submit_allowed") is False,
        config.get("capabilities") == CAPABILITY_CONTRACT,
        config.get("runtime", {}).get("auto_start") is False,
        config.get("runtime", {}).get("scheduler_tick_requires_queue_authorization") is True,
        config.get("principal_authorization", {}).get("state")
        == "SPEC_READY_NOT_RUNNING",
        config.get("principal_authorization", {}).get("algorithm") == "Ed25519",
        config.get("runtime", {}).get("launchd_bootstrap_allowed") is False,
        manifest.get("safety", {}).get("sim_only") is True,
        manifest.get("safety", {}).get("signal_only") is True,
        manifest.get("safety", {}).get("exchange_enabled") is False,
        manifest.get("safety", {}).get("order_submit_allowed") is False,
        manifest.get("runtime", {}).get("auto_start") is False,
        manifest.get("runtime", {}).get("scheduler_tick_requires_queue_authorization") is True,
        manifest.get("principal_authorization", {}).get("algorithm") == "Ed25519",
    )
    if not all(checks):
        raise PromotionError("internal safety invariant failed; no output may be generated")


_JOURNAL_SCHEMA = {
    "shadow_metadata": {"key", "value"},
    "shadow_scans": {"scan_id", "ts", "bar_ts", "symbol", "status", "notes"},
    "shadow_signals": {
        "signal_id",
        "ts",
        "bar_ts",
        "symbol",
        "strategy",
        "timeframe",
        "side",
        "entry_reference",
        "sl_reference",
        "tp_reference",
        "status",
        "notes",
    },
}


def _create_journal_file(path: Path, *, candidate_id: str, evidence_sha: str) -> None:
    import duckdb

    con = duckdb.connect(str(path))
    try:
        con.execute(
            "CREATE TABLE shadow_metadata (key VARCHAR PRIMARY KEY, value VARCHAR NOT NULL)"
        )
        con.execute(
            """
            CREATE TABLE shadow_scans (
                scan_id VARCHAR PRIMARY KEY,
                ts TIMESTAMP,
                bar_ts TIMESTAMP,
                symbol VARCHAR,
                status VARCHAR,
                notes VARCHAR
            )
            """
        )
        con.execute(
            """
            CREATE TABLE shadow_signals (
                signal_id VARCHAR PRIMARY KEY,
                ts TIMESTAMP,
                bar_ts TIMESTAMP,
                symbol VARCHAR,
                strategy VARCHAR,
                timeframe VARCHAR,
                side VARCHAR,
                entry_reference DOUBLE,
                sl_reference DOUBLE,
                tp_reference DOUBLE,
                status VARCHAR,
                notes VARCHAR
            )
            """
        )
        con.executemany(
            "INSERT INTO shadow_metadata VALUES (?, ?)",
            [
                ("schema_version", SHADOW_MANIFEST_SCHEMA),
                ("candidate_id", candidate_id),
                ("evidence_sha256", evidence_sha),
                ("exchange_enabled", "false"),
                ("signal_only", "true"),
            ],
        )
        con.commit()
    finally:
        con.close()


def _verify_journal(path: Path, *, candidate_id: str, evidence_sha: str) -> None:
    import duckdb

    try:
        con = duckdb.connect(str(path), read_only=True)
        try:
            tables = {
                row[0]
                for row in con.execute(
                    "SELECT table_name FROM information_schema.tables WHERE table_schema='main'"
                ).fetchall()
            }
            for table, expected_columns in _JOURNAL_SCHEMA.items():
                if table not in tables:
                    raise OutputConflictError(f"shadow journal missing table {table}: {path}")
                columns = {
                    row[1] for row in con.execute(f"PRAGMA table_info('{table}')").fetchall()
                }
                if columns != expected_columns:
                    raise OutputConflictError(f"shadow journal schema mismatch for {table}: {path}")
            metadata = dict(con.execute("SELECT key, value FROM shadow_metadata").fetchall())
        finally:
            con.close()
    except OutputConflictError:
        raise
    except Exception as exc:
        raise OutputConflictError(f"cannot validate existing shadow journal {path}: {exc}") from exc

    expected = {
        "schema_version": SHADOW_MANIFEST_SCHEMA,
        "candidate_id": candidate_id,
        "evidence_sha256": evidence_sha,
        "exchange_enabled": "false",
        "signal_only": "true",
    }
    if metadata != expected:
        raise OutputConflictError(f"shadow journal metadata mismatch: {path}")


def _init_journal_idempotent(path: Path, *, candidate_id: str, evidence_sha: str) -> bool:
    if path.exists():
        if path.is_symlink() or not path.is_file():
            raise OutputConflictError(f"unsafe existing journal path: {path}")
        _verify_journal(path, candidate_id=candidate_id, evidence_sha=evidence_sha)
        return False

    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".duckdb", dir=path.parent)
    os.close(fd)
    os.unlink(tmp_name)  # duckdb requires a non-existent or valid DB path
    tmp_path = Path(tmp_name)
    try:
        _create_journal_file(tmp_path, candidate_id=candidate_id, evidence_sha=evidence_sha)
        try:
            os.link(tmp_path, path)
        except FileExistsError:
            _verify_journal(path, candidate_id=candidate_id, evidence_sha=evidence_sha)
            return False
        return True
    finally:
        tmp_path.unlink(missing_ok=True)


def _load_queue(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {
            "schema_version": 1,
            "updated_at": None,
            "candidates": [],
            "status": "EMPTY",
        }
    if path.is_symlink() or not path.is_file():
        raise OutputConflictError(f"unsafe deploy queue path: {path}")
    try:
        queue = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise OutputConflictError(f"deploy queue is invalid JSON: {path}") from exc
    if not isinstance(queue, dict):
        raise OutputConflictError("deploy queue root must be an object")
    return queue


def _shadow_candidates(queue: dict[str, Any]) -> list[dict[str, Any]]:
    shadow = queue.get("tf_signal_shadow")
    if shadow is None:
        return []
    if not isinstance(shadow, dict) or not isinstance(shadow.get("candidates"), list):
        raise OutputConflictError("deploy_queue.tf_signal_shadow has an invalid shape")
    candidates = shadow["candidates"]
    if any(not isinstance(row, dict) for row in candidates):
        raise OutputConflictError("deploy_queue.tf_signal_shadow.candidates must contain objects")
    return candidates


def _check_shadow_slot(
    queue: dict[str, Any], evidence: ValidatedEvidence, candidate_id: str
) -> None:
    for row in _shadow_candidates(queue):
        if row.get("id") == candidate_id:
            if row.get("evidence_artifact_sha256") != evidence.sha256:
                raise OutputConflictError(f"candidate id collision in deploy queue: {candidate_id}")
            return
        if (
            row.get("strategy") == evidence.strategy
            and row.get("timeframe") == evidence.candidate_tf
            and row.get("status") in _ACTIVE_SHADOW_STATUSES
        ):
            raise OutputConflictError(
                "an active signal-only shadow slot already exists for "
                f"{evidence.strategy}/{evidence.candidate_tf}: {row.get('id')}"
            )


def _queue_candidate(
    evidence: ValidatedEvidence,
    *,
    candidate_id: str,
    bot_name: str,
    paths: ShadowPaths,
    repo_root: Path,
    strategy_module_sha256: str,
    config_sha256: str,
    dependency_closure: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "id": candidate_id,
        "status": "SPEC_READY_NOT_RUNNING",
        "added_at": evidence.generated_at.isoformat(),
        "strategy": evidence.strategy,
        "timeframe": evidence.candidate_tf,
        "bot_name": bot_name,
        "evidence_artifact": _relative(evidence.path, repo_root),
        "evidence_artifact_sha256": evidence.sha256,
        "strategy_module_sha256": strategy_module_sha256,
        "strategy_dependency_closure": dependency_closure,
        "hypothesis": _relative(paths.hypothesis, repo_root),
        "config": _relative(paths.config, repo_root),
        "config_sha256": config_sha256,
        "journal": _relative(paths.journal, repo_root),
        "shadow_manifest": _relative(paths.manifest, repo_root),
        "principal_authorization": {
            "artifact": _relative(paths.authorization, repo_root),
            **evidence.payload["authorization"]["principal_authorization"],
        },
        "safety": {
            "sim_only": True,
            "signal_only": True,
            "exchange_enabled": False,
            "order_submit_allowed": False,
            "auto_start": False,
            "scheduler_tick_requires_queue_authorization": True,
        },
    }


def _update_queue(
    path: Path,
    *,
    candidate: dict[str, Any],
    evidence: ValidatedEvidence,
) -> bool:
    """Append a candidate under a namespaced queue without reactivating legacy rows."""

    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_suffix(path.suffix + ".lock")
    with lock_path.open("a+", encoding="utf-8") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        queue = _load_queue(path)
        _check_shadow_slot(queue, evidence, candidate["id"])

        existing = [row for row in _shadow_candidates(queue) if row.get("id") == candidate["id"]]
        if existing:
            mutable_state_fields = {
                "status",
                "last_scheduler_tick_at",
                "last_scheduler_result",
            }
            expected_immutable = {
                key: value for key, value in candidate.items() if key not in mutable_state_fields
            }
            actual_immutable = {
                key: value for key, value in existing[0].items() if key not in mutable_state_fields
            }
            if actual_immutable != expected_immutable:
                raise OutputConflictError(f"deploy queue candidate conflict: {candidate['id']}")
            return False

        shadow = queue.setdefault(
            "tf_signal_shadow",
            {
                "schema_version": 1,
                "status": "ACTIVE_SIGNAL_ONLY",
                "policy": {
                    "accepted_evidence_schema": EVIDENCE_SCHEMA,
                    "authorization_scope": AUTHORIZATION_SCOPE,
                    "exchange_enabled": False,
                    "order_submit_allowed": False,
                    "auto_start": False,
                    "scheduler_tick_requires_queue_authorization": True,
                    "required_active_status": "SHADOW_ACTIVE_AUTHORIZED",
                },
                "candidates": [],
            },
        )
        expected_policy = {
            "accepted_evidence_schema": EVIDENCE_SCHEMA,
            "authorization_scope": AUTHORIZATION_SCOPE,
            "exchange_enabled": False,
            "order_submit_allowed": False,
            "auto_start": False,
            "scheduler_tick_requires_queue_authorization": True,
            "required_active_status": "SHADOW_ACTIVE_AUTHORIZED",
        }
        if (
            not isinstance(shadow, dict)
            or shadow.get("schema_version") != 1
            or shadow.get("status") != "ACTIVE_SIGNAL_ONLY"
            or shadow.get("policy") != expected_policy
            or not isinstance(shadow.get("candidates"), list)
        ):
            raise OutputConflictError("deploy_queue.tf_signal_shadow policy/schema conflict")
        shadow["candidates"].append(candidate)
        shadow["candidates"].sort(key=lambda row: str(row.get("id", "")))
        queue["tf_signal_shadow_updated_at"] = evidence.generated_at.isoformat()

        raw = _canonical_json(queue).encode("utf-8")
        fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(raw)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_name, path)
        finally:
            with suppress(FileNotFoundError):
                os.unlink(tmp_name)
        return True


def promote_evidence(path: Path, *, repo_root: Path = REPO_ROOT) -> dict[str, Any]:
    """Create a deterministic signal-only shadow spec from one valid artifact."""

    repo_root = Path(repo_root).resolve()
    evidence = validate_evidence(
        path,
        evidence_dir=Path(path).parent,
        repo_root=repo_root,
    )
    try:
        evidence.path.relative_to(repo_root)
    except ValueError as exc:
        raise EvidenceRejectedError(["evidence artifact must live inside repo_root"]) from exc

    candidate_id = _candidate_id(evidence)
    bot_name = _bot_name(evidence)
    paths = _paths_for(repo_root, candidate_id)
    strategy_module, strategy_module_sha256 = _strategy_module_identity(repo_root, evidence)
    dependency_closure = strategy_dependency_closure(
        repo_root,
        strategy=evidence.strategy,
        timeframe=evidence.candidate_tf,
    )
    _verify_evaluator_identity(repo_root, evidence)
    tested_strategy_sha = _nested(evidence.payload, "inputs", "strategy_module", "sha256")
    if tested_strategy_sha != strategy_module_sha256:
        raise EvidenceRejectedError(
            [
                "local strategy module sha256 differs from the implementation "
                "evaluated by independent OOS evidence"
            ]
        )

    # Preflight queue/slot before creating any candidate-specific artifacts.
    queue = _load_queue(paths.deploy_queue)
    _check_shadow_slot(queue, evidence, candidate_id)

    config_text = _render_config(
        evidence,
        candidate_id=candidate_id,
        bot_name=bot_name,
        paths=paths,
        repo_root=repo_root,
        strategy_module=strategy_module,
        strategy_module_sha256=strategy_module_sha256,
        dependency_closure=dependency_closure,
    )
    hypothesis_text = _render_hypothesis(
        evidence,
        candidate_id=candidate_id,
        bot_name=bot_name,
        strategy_module_sha256=strategy_module_sha256,
    )
    manifest = _manifest_payload(
        evidence,
        candidate_id=candidate_id,
        bot_name=bot_name,
        paths=paths,
        repo_root=repo_root,
        strategy_module=strategy_module,
        strategy_module_sha256=strategy_module_sha256,
        dependency_closure=dependency_closure,
    )
    _validate_safety(config_text, manifest)

    created = {
        "hypothesis": _atomic_create_or_verify(paths.hypothesis, hypothesis_text.encode("utf-8")),
        "config": _atomic_create_or_verify(paths.config, config_text.encode("utf-8")),
        "journal": _init_journal_idempotent(
            paths.journal,
            candidate_id=candidate_id,
            evidence_sha=evidence.sha256,
        ),
        "manifest": _atomic_create_or_verify(
            paths.manifest, _canonical_json(manifest).encode("utf-8")
        ),
    }
    candidate = _queue_candidate(
        evidence,
        candidate_id=candidate_id,
        bot_name=bot_name,
        paths=paths,
        repo_root=repo_root,
        strategy_module_sha256=strategy_module_sha256,
        config_sha256=_sha256_bytes(config_text.encode("utf-8")),
        dependency_closure=dependency_closure,
    )
    created["deploy_queue"] = _update_queue(
        paths.deploy_queue,
        candidate=candidate,
        evidence=evidence,
    )
    if created["deploy_queue"]:
        status = "PROMOTED_TO_SIGNAL_ONLY_SPEC"
    elif any(created.values()):
        status = "REPAIRED_SIGNAL_ONLY_SPEC"
    else:
        status = "ALREADY_PROMOTED"

    return {
        "status": status,
        "candidate_id": candidate_id,
        "bot_name": bot_name,
        "strategy": evidence.strategy,
        "timeframe": evidence.candidate_tf,
        "evidence_sha256": evidence.sha256,
        "created": created,
        "paths": {
            "hypothesis": _relative(paths.hypothesis, repo_root),
            "config": _relative(paths.config, repo_root),
            "journal": _relative(paths.journal, repo_root),
            "manifest": _relative(paths.manifest, repo_root),
            "deploy_queue": _relative(paths.deploy_queue, repo_root),
        },
        "runtime_started": False,
        "exchange_order_path_enabled": False,
    }


def scan_evidence_directory(
    *,
    evidence_dir: Path,
    repo_root: Path = REPO_ROOT,
    audit_output: Path | None = None,
) -> dict[str, Any]:
    """Consume every JSON artifact once-by-identity; invalid evidence is audited only."""

    evidence_dir = Path(evidence_dir)
    repo_root = Path(repo_root).resolve()
    records: list[dict[str, Any]] = []
    if evidence_dir.exists():
        candidates = sorted(path for path in evidence_dir.glob("*.json") if path.is_file())
    else:
        candidates = []

    for path in candidates:
        try:
            result = promote_evidence(path, repo_root=repo_root)
        except EvidenceRejectedError as exc:
            records.append(
                {
                    "artifact": str(path),
                    "status": "REJECTED",
                    "errors": exc.errors,
                }
            )
        except PromotionError as exc:
            records.append(
                {
                    "artifact": str(path),
                    "status": "CONFLICT",
                    "errors": [str(exc)],
                }
            )
        except Exception as exc:  # defensive: an unknown failure must never promote
            records.append(
                {
                    "artifact": str(path),
                    "status": "ERROR",
                    "errors": [f"{type(exc).__name__}: {str(exc)[:300]}"],
                }
            )
        else:
            records.append({"artifact": str(path), **result})

    counts = {
        "scanned": len(records),
        "promoted": sum(r.get("status") == "PROMOTED_TO_SIGNAL_ONLY_SPEC" for r in records),
        "already_promoted": sum(r.get("status") == "ALREADY_PROMOTED" for r in records),
        "repaired": sum(r.get("status") == "REPAIRED_SIGNAL_ONLY_SPEC" for r in records),
        "rejected": sum(r.get("status") == "REJECTED" for r in records),
        "conflicts": sum(r.get("status") == "CONFLICT" for r in records),
        "errors": sum(r.get("status") == "ERROR" for r in records),
    }
    report = {
        "schema_version": SCAN_SCHEMA,
        "generated_at": datetime.now(UTC).isoformat(),
        "evidence_dir": str(evidence_dir.resolve()),
        "counts": counts,
        "runtime_started": False,
        "exchange_order_path_enabled": False,
        "artifacts": records,
    }
    if audit_output is not None:
        audit_path = Path(audit_output)
        audit_path.parent.mkdir(parents=True, exist_ok=True)
        raw = _canonical_json(report).encode("utf-8")
        fd, tmp_name = tempfile.mkstemp(
            prefix=f".{audit_path.name}.", suffix=".tmp", dir=audit_path.parent
        )
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(raw)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_name, audit_path)
        finally:
            with suppress(FileNotFoundError):
                os.unlink(tmp_name)
    return report


def run_default_scan() -> dict[str, Any]:
    """Scheduler-safe default scan; it has no process or exchange side effects."""

    return scan_evidence_directory(
        evidence_dir=REPO_ROOT / "reports" / "tf_robustness",
        repo_root=REPO_ROOT,
        audit_output=REPO_ROOT / "reports" / "tf_shadow_pipeline" / "latest.json",
    )


__all__ = [
    "ALLOWED_SIGNAL_SHADOW_STRATEGIES",
    "AUTHORIZATION_SCOPE",
    "CAPABILITY_CONTRACT",
    "CAPABILITY_PROFILE",
    "EVIDENCE_SCHEMA",
    "SHADOW_CONFIG_SCHEMA",
    "SHADOW_MANIFEST_SCHEMA",
    "EvidenceRejectedError",
    "OutputConflictError",
    "PromotionError",
    "promote_evidence",
    "run_default_scan",
    "scan_evidence_directory",
    "validate_evidence",
    "validate_strategy_capabilities",
]
