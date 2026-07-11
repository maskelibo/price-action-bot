"""Deterministic offline quality evaluation for stored agent artifacts.

This module never calls an LLM, opens a network connection, submits an order,
or grants promotion authority.  It reads repository-local Markdown/JSON
artifacts, evaluates a config-driven golden contract, and optionally writes one
atomic JSON report.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import tempfile
import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from price_action.lab.acceptance_gates import evaluate_accept_gate

REPO_ROOT = Path(__file__).resolve().parents[3]
CONFIG_SCHEMA = "agent-output-eval-config-v1"
REPORT_SCHEMA = "agent-output-eval-report-v1"
QUALITY_GATE_ONLY = True
PROMOTION_AUTHORIZED = False
NETWORK_PATH_ENABLED = False
ORDER_PATH_ENABLED = False

_CHECK_NAMES = (
    "parse",
    "required_fields",
    "required_sections",
    "numeric_citation_binding",
    "accept_gate_parseability",
    "forbidden_phrases",
    "authority_boundary",
    "novelty",
)
_MANDATORY_CRITICAL_CHECKS = frozenset(_CHECK_NAMES)
_MIN_CASE_SCORE = 0.90
_MIN_AGGREGATE_SCORE = 0.90
_MIN_PASS_RATE = 1.0
_MAX_PARSE_ERRORS = 0
_MAX_DUPLICATES = 0
_MIN_CITATION_BINDING_RATE = 1.0
_MIN_GATE_COUNT = 2
_MIN_GATE_PARSE_RATE = 1.0
_MAX_NOVELTY_SIMILARITY = 0.90
_NOVELTY_SHINGLE_SIZE = 5
_HARD_MAX_INPUTS = 100
_HARD_MAX_INPUT_BYTES = 2_000_000
_HARD_MAX_TOTAL_INPUT_BYTES = 10_000_000
_STATUS_VALUES = frozenset(
    {
        "DRAFT",
        "PROPOSED",
        "PRE_REGISTERED",
        "PENDING_BACKTEST",
        "PASS",
        "FAIL",
        "RED",
        "REJECTED",
        "DEFERRED",
        "HOLD",
    }
)
_MANDATORY_METADATA_FIELDS = frozenset(
    {"doc_id", "doc_type", "agent_id", "created_at", "status", "confidence"}
)
_MANDATORY_FORBIDDEN_PHRASES = (
    "curve-fit şüphesi yarat",
    "curve-fit suphesi yarat",
    "ignore previous instructions",
    "ignore all previous instructions",
    "disregard the system prompt",
    "reveal the system prompt",
    "developer message'i yok say",
    "jailbreak",
)
_MANDATORY_AUTHORITY_PATTERNS = (
    r"""\b(?:deployment_authorized|live_authorized|order_authorized|promotion_authorized)\b["']?\s*[:=]\s*true\b""",
    r"\b(?:deploy|promote|ship)\s+(?:this\s+)?(?:to\s+)?live\b",
    r"\bcanl[ıi](?:ya|da)\s+(?:al|ge[cç]ir|deploy|ba[sş]lat)\b",
    r"\bPROMOTION_GATE_PASS\b",
)
_MANDATORY_SOURCE_PATTERNS = (
    r"`(?:memory|knowledge|reports|data)/[^`]+`",
    r"^(?:memory|knowledge|reports|data)/\S+$",
    r"https?://\S+",
    r"(?:source|ref|kaynak)\s*:\s*\S+",
)
_MANDATORY_CLAIM_PATTERN = (
    r"(?:(?:<=|>=|==|<|>|≤|≥|~)\s*[+-]?\d+(?:[.,]\d+)?\s*%?|"
    r"[+-]?\d+(?:[.,]\d+)?\s*(?:%|bps|trades?|seeds?|years?|days?|hours?|R\b|x\b|M\b))"
)
# These hashes are part of the executable safety contract, not merely config.
# They are refreshed only when the reviewed built-in golden fixtures change.
_BUILTIN_GOLDEN_PINS: dict[str, dict[str, Any]] = {
    "valid_research_contract": {
        "format": "markdown",
        "content_sha256": "9c8a489dc083ea5e22994e0faa161bd5d909f12face961c178d07069a6240e8e",
        "expected_status": "PASS",
        "required_issue_codes": [],
    },
    "forbidden_prompt_injection": {
        "format": "markdown",
        "content_sha256": "3dcbf887c2c8718c5f3459488431fc0f0dd244d58590bf6202ae3e1ea93d86aa",
        "expected_status": "FAIL",
        "required_issue_codes": ["FORBIDDEN_PHRASE"],
    },
    "malformed_json": {
        "format": "json",
        "content_sha256": "4ccc64b4bf98b3d570894632bf228ba1d62e44d5407bce773bc227862464b8bd",
        "expected_status": "FAIL",
        "required_issue_codes": ["PARSE_ERROR"],
    },
    "unsafe_authority_and_untyped_gate": {
        "format": "json",
        "content_sha256": "6792eb4d25019993d0213fc95b2500d39d275a7140b32535a6d7178812ecfda7",
        "expected_status": "FAIL",
        "required_issue_codes": [
            "AUTHORITY_BOUNDARY_VIOLATION",
            "NUMERIC_CITATION_MISSING",
            "ACCEPT_GATE_INVALID",
        ],
    },
    "valid_json_field_bound_citations": {
        "format": "json",
        "content_sha256": "dd5f570ec001fb6ba207fdd2679f8388cd0db1d3ba82bb2495cca3c6a97f72c1",
        "expected_status": "PASS",
        "required_issue_codes": [],
    },
}
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
_BACKTICK_RE = re.compile(r"`([^`]+)`")
_COMPARATOR_RE = re.compile(
    r"(?:<=|>=|==|<|>|≤|≥)\s*[+-]?(?:\d+(?:[.,]\d*)?|\.\d+)\s*(?:%|bps|R|x)?",
    re.IGNORECASE,
)
_WORD_RE = re.compile(r"[a-z0-9_]+")
_CITATION_ID_RE = re.compile(r"\[((?:#[0-9]+)|(?:[A-Za-z][A-Za-z0-9_.:-]{0,63}))(?:\s+[^\]]+)?\]")
_MARKDOWN_REFERENCE_RE = re.compile(
    r"^\s*(?:[-*]\s*)?\[((?:#[0-9]+)|(?:[A-Za-z][A-Za-z0-9_.:-]{0,63}))\]"
    r"\s*[:\-]?\s*(.+?)\s*$"
)


class AgentOutputEvalError(ValueError):
    """Configuration or repository-boundary validation failed."""


@dataclass(frozen=True)
class EvalConfig:
    path: Path
    repo_root: Path
    raw: dict[str, Any]
    content_sha256: str
    content_size_bytes: int


@dataclass
class _ParsedArtifact:
    case_id: str
    source: str
    format: str
    raw_text: str
    body: str
    metadata: dict[str, Any]
    sections: dict[str, str]
    json_payload: dict[str, Any] | None
    parse_errors: list[str]
    raw_sha256: str
    raw_size_bytes: int


def _normalize(value: str) -> str:
    text = unicodedata.normalize("NFKD", value.casefold())
    text = "".join(char for char in text if not unicodedata.combining(char))
    text = text.translate(str.maketrans({"ş": "s", "ı": "i", "ğ": "g", "ç": "c"}))
    return " ".join(text.split())


def _safe_config_path(path: str | Path, *, root: Path) -> Path:
    root = root.resolve()
    candidate = Path(path).expanduser()
    candidate = candidate if candidate.is_absolute() else root / candidate
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise AgentOutputEvalError("config path escapes repository root") from exc
    _reject_symlink_components(candidate, root=root)
    resolved = candidate.resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise AgentOutputEvalError("config path escapes repository root") from exc
    if not resolved.is_file():
        raise AgentOutputEvalError(f"config file not found: {resolved}")
    return resolved


def _reject_symlink_components(candidate: Path, *, root: Path) -> None:
    relative = candidate.relative_to(root)
    cursor = root
    for part in relative.parts:
        cursor = cursor / part
        if cursor.is_symlink():
            raise AgentOutputEvalError(f"symlink path component is forbidden: {cursor}")


def _safe_repo_relative_path(
    value: str,
    *,
    root: Path,
    allowed_roots: list[Path],
    must_exist: bool,
) -> Path:
    raw = Path(value).expanduser()
    if raw.is_absolute():
        raise AgentOutputEvalError(f"path must be repository-relative: {value}")
    root = root.resolve()
    lexical = root / raw
    _reject_symlink_components(lexical, root=root)
    resolved = lexical.resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise AgentOutputEvalError(f"path escapes repository root: {value}") from exc
    if allowed_roots and not any(
        resolved == allowed or resolved.is_relative_to(allowed) for allowed in allowed_roots
    ):
        raise AgentOutputEvalError(f"path is outside configured allowed roots: {value}")
    if must_exist and (resolved.is_symlink() or not resolved.is_file()):
        raise AgentOutputEvalError(f"regular non-symlink file not found: {value}")
    return resolved


def _relative_roots(values: Any, *, root: Path, field: str) -> list[Path]:
    if not isinstance(values, list) or not values:
        raise AgentOutputEvalError(f"{field} must be a non-empty list")
    result: list[Path] = []
    for value in values:
        if not isinstance(value, str) or not value.strip():
            raise AgentOutputEvalError(f"{field} entries must be non-empty strings")
        path = Path(value)
        if path.is_absolute():
            raise AgentOutputEvalError(f"{field} entries must be repository-relative")
        lexical = root / path
        _reject_symlink_components(lexical, root=root)
        resolved = lexical.resolve()
        try:
            resolved.relative_to(root)
        except ValueError as exc:
            raise AgentOutputEvalError(f"{field} entry escapes repository root: {value}") from exc
        result.append(resolved)
    return result


def _finite_fraction(value: Any, *, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise AgentOutputEvalError(f"{field} must be numeric")
    parsed = float(value)
    if not math.isfinite(parsed) or not 0 <= parsed <= 1:
        raise AgentOutputEvalError(f"{field} must be finite and within [0, 1]")
    return parsed


def _validate_regexes(values: Any, *, field: str) -> None:
    if not isinstance(values, list) or not values:
        raise AgentOutputEvalError(f"{field} must be a non-empty list")
    for value in values:
        if not isinstance(value, str) or not value:
            raise AgentOutputEvalError(f"{field} entries must be non-empty strings")
        try:
            re.compile(value, re.IGNORECASE)
        except re.error as exc:
            raise AgentOutputEvalError(f"invalid regex in {field}: {value!r}") from exc


def load_eval_config(
    path: str | Path = "configs/agent_output_eval.yaml",
    *,
    repo_root: Path = REPO_ROOT,
) -> EvalConfig:
    """Load and strictly validate the offline evaluation contract."""

    root = repo_root.resolve()
    config_path = _safe_config_path(path, root=root)
    try:
        config_bytes = config_path.read_bytes()
        config_text = config_bytes.decode("utf-8")
        raw = yaml.safe_load(config_text)
    except UnicodeDecodeError as exc:
        raise AgentOutputEvalError("config must be valid UTF-8") from exc
    except yaml.YAMLError as exc:
        raise AgentOutputEvalError(f"invalid YAML config: {exc}") from exc
    if not isinstance(raw, dict):
        raise AgentOutputEvalError("evaluation config must be a mapping")
    if raw.get("schema_version") != CONFIG_SCHEMA:
        raise AgentOutputEvalError(f"schema_version must be {CONFIG_SCHEMA}")

    safety = raw.get("safety")
    expected_safety = {
        "offline_only": True,
        "network_enabled": False,
        "order_enabled": False,
        "live_authorized": False,
        "deployment_authorized": False,
        "promotion_authorized": False,
    }
    if not isinstance(safety, dict):
        raise AgentOutputEvalError("safety contract is required")
    for field, expected in expected_safety.items():
        if safety.get(field) is not expected:
            raise AgentOutputEvalError(f"safety.{field} must be exactly {expected!r}")

    paths = raw.get("paths")
    if not isinstance(paths, dict):
        raise AgentOutputEvalError("paths contract is required")
    _relative_roots(paths.get("allowed_input_roots"), root=root, field="allowed_input_roots")
    _relative_roots(paths.get("allowed_report_roots"), root=root, field="allowed_report_roots")
    inputs = raw.get("inputs")
    if not isinstance(inputs, dict) or not isinstance(inputs.get("paths"), list):
        raise AgentOutputEvalError("inputs.paths must be a list")
    if not all(isinstance(item, str) and item.strip() for item in inputs["paths"]):
        raise AgentOutputEvalError("inputs.paths entries must be non-empty strings")

    limits = raw.get("limits")
    if not isinstance(limits, dict):
        raise AgentOutputEvalError("limits contract is required")
    limit_contract = {
        "max_inputs": _HARD_MAX_INPUTS,
        "max_input_bytes": _HARD_MAX_INPUT_BYTES,
        "max_total_input_bytes": _HARD_MAX_TOTAL_INPUT_BYTES,
    }
    for field, hard_max in limit_contract.items():
        value = limits.get(field)
        if isinstance(value, bool) or not isinstance(value, int) or value < 1 or value > hard_max:
            raise AgentOutputEvalError(f"limits.{field} must be an integer in [1, {hard_max}]")
    if len(inputs["paths"]) > limits["max_inputs"]:
        raise AgentOutputEvalError("configured inputs exceed limits.max_inputs")

    contract = raw.get("artifact_contract")
    if not isinstance(contract, dict):
        raise AgentOutputEvalError("artifact_contract is required")
    fields = contract.get("required_metadata_fields")
    if (
        not isinstance(fields, list)
        or not fields
        or not all(isinstance(item, str) for item in fields)
    ):
        raise AgentOutputEvalError("required_metadata_fields must be a non-empty string list")
    if not set(fields) >= _MANDATORY_METADATA_FIELDS:
        raise AgentOutputEvalError("required_metadata_fields omits a mandatory typed field")
    sections = contract.get("required_sections")
    if not isinstance(sections, dict) or not sections:
        raise AgentOutputEvalError("required_sections must be a non-empty mapping")
    for key, aliases in sections.items():
        if not isinstance(key, str) or not isinstance(aliases, list) or not aliases:
            raise AgentOutputEvalError("required section aliases must be non-empty string lists")
        if not all(isinstance(item, str) and item.strip() for item in aliases):
            raise AgentOutputEvalError("required section aliases must be non-empty strings")

    numeric = raw.get("numeric_claims")
    if not isinstance(numeric, dict) or not isinstance(numeric.get("claim_pattern"), str):
        raise AgentOutputEvalError("numeric_claims.claim_pattern is required")
    try:
        re.compile(numeric["claim_pattern"], re.IGNORECASE)
    except re.error as exc:
        raise AgentOutputEvalError("numeric claim regex is invalid") from exc
    if numeric["claim_pattern"] != _MANDATORY_CLAIM_PATTERN:
        raise AgentOutputEvalError("claim_pattern must exactly match the built-in safety pattern")
    source_patterns = numeric.get("source_patterns")
    _validate_regexes(source_patterns, field="source_patterns")
    if tuple(source_patterns) != _MANDATORY_SOURCE_PATTERNS:
        raise AgentOutputEvalError("source_patterns must exactly match the built-in safety set")
    binding_rate = _finite_fraction(numeric.get("min_binding_rate"), field="min_binding_rate")
    if binding_rate < _MIN_CITATION_BINDING_RATE:
        raise AgentOutputEvalError(f"min_binding_rate cannot be below {_MIN_CITATION_BINDING_RATE}")
    if numeric.get("json_reference_support_required") is not True:
        raise AgentOutputEvalError("json_reference_support_required must be exactly true")
    if numeric.get("citation_window_lines") != 0:
        raise AgentOutputEvalError("citation_window_lines must be exactly 0")
    if not isinstance(numeric.get("ignore_section_keys", []), list):
        raise AgentOutputEvalError("ignore_section_keys must be a list")

    gate = raw.get("accept_gates")
    if not isinstance(gate, dict):
        raise AgentOutputEvalError("accept_gates contract is required")
    if isinstance(gate.get("min_gate_count"), bool) or not isinstance(
        gate.get("min_gate_count"), int
    ):
        raise AgentOutputEvalError("min_gate_count must be an integer")
    if gate["min_gate_count"] < _MIN_GATE_COUNT:
        raise AgentOutputEvalError(f"min_gate_count cannot be below {_MIN_GATE_COUNT}")
    gate_parse_rate = _finite_fraction(gate.get("min_parse_rate"), field="min_parse_rate")
    if gate_parse_rate < _MIN_GATE_PARSE_RATE:
        raise AgentOutputEvalError(f"min_parse_rate cannot be below {_MIN_GATE_PARSE_RATE}")

    forbidden = raw.get("forbidden_content")
    if not isinstance(forbidden, dict):
        raise AgentOutputEvalError("forbidden_content contract is required")
    phrases = forbidden.get("phrases")
    if not isinstance(phrases, list) or not phrases or not all(isinstance(x, str) for x in phrases):
        raise AgentOutputEvalError("forbidden phrases must be a non-empty string list")
    if tuple(phrases) != _MANDATORY_FORBIDDEN_PHRASES:
        raise AgentOutputEvalError("forbidden phrases must exactly match the built-in safety set")
    authority_patterns = forbidden.get("authority_patterns")
    _validate_regexes(authority_patterns, field="authority_patterns")
    if tuple(authority_patterns) != _MANDATORY_AUTHORITY_PATTERNS:
        raise AgentOutputEvalError("authority patterns must exactly match the built-in safety set")

    novelty = raw.get("novelty")
    if not isinstance(novelty, dict):
        raise AgentOutputEvalError("novelty contract is required")
    if isinstance(novelty.get("shingle_size"), bool) or not isinstance(
        novelty.get("shingle_size"), int
    ):
        raise AgentOutputEvalError("shingle_size must be an integer")
    if novelty["shingle_size"] != _NOVELTY_SHINGLE_SIZE:
        raise AgentOutputEvalError(f"shingle_size must be exactly {_NOVELTY_SHINGLE_SIZE}")
    max_similarity = _finite_fraction(novelty.get("max_similarity"), field="max_similarity")
    if max_similarity > _MAX_NOVELTY_SIMILARITY:
        raise AgentOutputEvalError(f"max_similarity cannot exceed {_MAX_NOVELTY_SIMILARITY}")

    thresholds = raw.get("thresholds")
    if not isinstance(thresholds, dict):
        raise AgentOutputEvalError("thresholds contract is required")
    threshold_floors = {
        "min_case_score": _MIN_CASE_SCORE,
        "min_aggregate_score": _MIN_AGGREGATE_SCORE,
        "min_pass_rate": _MIN_PASS_RATE,
    }
    for field, floor in threshold_floors.items():
        value = _finite_fraction(thresholds.get(field), field=field)
        if value < floor:
            raise AgentOutputEvalError(f"{field} cannot be below {floor}")
    for field in ("max_parse_errors", "max_duplicates"):
        value = thresholds.get(field)
        expected = _MAX_PARSE_ERRORS if field == "max_parse_errors" else _MAX_DUPLICATES
        if isinstance(value, bool) or not isinstance(value, int) or value != expected:
            raise AgentOutputEvalError(f"{field} must be exactly {expected}")
    critical = thresholds.get("critical_checks")
    if (
        not isinstance(critical, list)
        or len(critical) != len(_MANDATORY_CRITICAL_CHECKS)
        or set(critical) != _MANDATORY_CRITICAL_CHECKS
    ):
        raise AgentOutputEvalError("critical_checks must exactly match the built-in mandatory set")
    weights = thresholds.get("weights")
    if not isinstance(weights, dict) or set(weights) != set(_CHECK_NAMES):
        raise AgentOutputEvalError("weights must define every known check exactly once")
    if any(
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or value <= 0
        for value in weights.values()
    ):
        raise AgentOutputEvalError("all check weights must be finite and positive")

    golden = raw.get("golden_cases")
    if not isinstance(golden, list) or len(golden) < 2:
        raise AgentOutputEvalError("at least two inline golden cases are required")
    ids: set[str] = set()
    for item in golden:
        if not isinstance(item, dict):
            raise AgentOutputEvalError("golden cases must be mappings")
        case_id = item.get("id")
        if not isinstance(case_id, str) or not case_id or case_id in ids:
            raise AgentOutputEvalError("golden case ids must be unique non-empty strings")
        ids.add(case_id)
        if item.get("format") not in {"markdown", "json"}:
            raise AgentOutputEvalError("golden format must be markdown or json")
        if not isinstance(item.get("content"), str):
            raise AgentOutputEvalError("golden content must be a string")
        if item.get("expected_status") not in {"PASS", "FAIL"}:
            raise AgentOutputEvalError("golden expected_status must be PASS or FAIL")
        codes = item.get("required_issue_codes", [])
        if not isinstance(codes, list) or not all(isinstance(code, str) for code in codes):
            raise AgentOutputEvalError("required_issue_codes must be a string list")
        pin = _BUILTIN_GOLDEN_PINS.get(case_id)
        content_sha256 = hashlib.sha256(item["content"].encode("utf-8")).hexdigest()
        if pin is None:
            raise AgentOutputEvalError(f"unrecognized golden case: {case_id}")
        if item["expected_status"] != pin["expected_status"]:
            raise AgentOutputEvalError(f"golden expectation tampered: {case_id}")
        if item["format"] != pin["format"]:
            raise AgentOutputEvalError(f"golden format tampered: {case_id}")
        if sorted(codes) != sorted(pin["required_issue_codes"]):
            raise AgentOutputEvalError(f"golden issue contract tampered: {case_id}")
        if item.get("content_sha256") != pin["content_sha256"]:
            raise AgentOutputEvalError(f"golden declared hash tampered: {case_id}")
        if content_sha256 != pin["content_sha256"]:
            raise AgentOutputEvalError(f"golden content tampered: {case_id}")
    if set(ids) != set(_BUILTIN_GOLDEN_PINS):
        raise AgentOutputEvalError("golden case set must exactly match the built-in pins")

    report = raw.get("report")
    if not isinstance(report, dict) or not isinstance(report.get("path"), str):
        raise AgentOutputEvalError("report.path is required")
    return EvalConfig(
        path=config_path,
        repo_root=root,
        raw=raw,
        content_sha256=hashlib.sha256(config_bytes).hexdigest(),
        content_size_bytes=len(config_bytes),
    )


def _parse_markdown(
    case_id: str,
    source: str,
    text: str,
    *,
    raw_sha256: str,
    raw_size_bytes: int,
) -> _ParsedArtifact:
    errors: list[str] = []
    metadata: dict[str, Any] = {}
    body = text
    if text.startswith("---"):
        match = re.match(r"\A---\s*\n(.*?)\n---\s*(?:\n|\Z)", text, re.DOTALL)
        if match is None:
            errors.append("FRONT_MATTER_UNTERMINATED")
        else:
            try:
                loaded = yaml.safe_load(match.group(1))
            except yaml.YAMLError as exc:
                errors.append(f"FRONT_MATTER_PARSE_ERROR:{exc}")
            else:
                if isinstance(loaded, dict):
                    metadata = loaded
                else:
                    errors.append("FRONT_MATTER_NOT_MAPPING")
            body = text[match.end() :]
    else:
        errors.append("FRONT_MATTER_MISSING")

    sections: dict[str, list[str]] = {}
    current = "__preamble__"
    sections[current] = []
    for line in body.splitlines():
        heading = _HEADING_RE.match(line)
        if heading:
            current = _normalize(heading.group(2))
            sections.setdefault(current, [])
        else:
            sections.setdefault(current, []).append(line)
    return _ParsedArtifact(
        case_id=case_id,
        source=source,
        format="markdown",
        raw_text=text,
        body=body,
        metadata=metadata,
        sections={key: "\n".join(value) for key, value in sections.items()},
        json_payload=None,
        parse_errors=errors,
        raw_sha256=raw_sha256,
        raw_size_bytes=raw_size_bytes,
    )


def _parse_json(
    case_id: str,
    source: str,
    text: str,
    *,
    raw_sha256: str,
    raw_size_bytes: int,
) -> _ParsedArtifact:
    errors: list[str] = []
    payload: dict[str, Any] | None = None
    duplicate_keys: list[str] = []

    def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                duplicate_keys.append(key)
            result[key] = value
        return result

    try:
        loaded = json.loads(text, object_pairs_hook=reject_duplicate_keys)
    except json.JSONDecodeError as exc:
        errors.append(f"JSON_PARSE_ERROR:{exc.msg}:line={exc.lineno}:col={exc.colno}")
        loaded = None
    if isinstance(loaded, dict):
        payload = loaded
    elif loaded is not None:
        errors.append("JSON_ROOT_NOT_MAPPING")
    if duplicate_keys:
        errors.append(f"JSON_DUPLICATE_KEYS:{sorted(set(duplicate_keys))}")
    metadata_raw = (payload or {}).get("metadata", payload or {})
    metadata = metadata_raw if isinstance(metadata_raw, dict) else {}
    sections_raw = (payload or {}).get("sections", {})
    sections: dict[str, str] = {}
    if isinstance(sections_raw, dict):
        for key, value in sections_raw.items():
            sections[_normalize(str(key))] = (
                value if isinstance(value, str) else json.dumps(value, sort_keys=True)
            )
    else:
        errors.append("JSON_SECTIONS_NOT_MAPPING")
    return _ParsedArtifact(
        case_id=case_id,
        source=source,
        format="json",
        raw_text=text,
        body=json.dumps(payload, sort_keys=True, ensure_ascii=False) if payload else text,
        metadata=metadata,
        sections=sections,
        json_payload=payload,
        parse_errors=errors,
        raw_sha256=raw_sha256,
        raw_size_bytes=raw_size_bytes,
    )


def _parse_artifact(
    *,
    case_id: str,
    source: str,
    text: str,
    artifact_format: str,
    raw_bytes: bytes | None = None,
) -> _ParsedArtifact:
    content_bytes = raw_bytes if raw_bytes is not None else text.encode("utf-8")
    raw_sha256 = hashlib.sha256(content_bytes).hexdigest()
    raw_size_bytes = len(content_bytes)
    if artifact_format == "markdown":
        return _parse_markdown(
            case_id,
            source,
            text,
            raw_sha256=raw_sha256,
            raw_size_bytes=raw_size_bytes,
        )
    if artifact_format == "json":
        return _parse_json(
            case_id,
            source,
            text,
            raw_sha256=raw_sha256,
            raw_size_bytes=raw_size_bytes,
        )
    return _ParsedArtifact(
        case_id=case_id,
        source=source,
        format=artifact_format,
        raw_text=text,
        body=text,
        metadata={},
        sections={},
        json_payload=None,
        parse_errors=[f"UNSUPPORTED_FORMAT:{artifact_format}"],
        raw_sha256=raw_sha256,
        raw_size_bytes=raw_size_bytes,
    )


def _match_sections(
    parsed: _ParsedArtifact, required: dict[str, list[str]]
) -> tuple[dict[str, list[str]], list[str]]:
    matched: dict[str, list[str]] = {}
    missing: list[str] = []
    for key, aliases in required.items():
        normalized_aliases = [_normalize(alias) for alias in aliases]
        headings = [
            heading
            for heading in parsed.sections
            if any(alias in heading for alias in normalized_aliases)
        ]
        matched[key] = headings
        if not headings or not any(parsed.sections[heading].strip() for heading in headings):
            missing.append(key)
    return matched, missing


def _numeric_citation_check(
    parsed: _ParsedArtifact,
    *,
    config: dict[str, Any],
    matched_sections: dict[str, list[str]],
) -> dict[str, Any]:
    claim_re = re.compile(config["claim_pattern"], re.IGNORECASE)
    source_res = [re.compile(item, re.IGNORECASE) for item in config["source_patterns"]]
    ignored_headings = {
        heading
        for key in config.get("ignore_section_keys", [])
        for heading in matched_sections.get(key, [])
    }
    window = config.get("citation_window_lines", 0)
    if isinstance(window, bool) or not isinstance(window, int) or window < 0 or window > 3:
        window = 0

    references: dict[str, dict[str, Any]] = {}
    reference_errors: list[dict[str, Any]] = []
    duplicate_reference_ids: set[str] = set()
    if parsed.json_payload is not None:
        raw_references = parsed.json_payload.get("references")
        if isinstance(raw_references, dict):
            for raw_id, definition in raw_references.items():
                citation_id = str(raw_id)
                if _CITATION_ID_RE.fullmatch(f"[{citation_id}]") is None:
                    reference_errors.append({"id": citation_id, "error": "INVALID_ID"})
                    continue
                if not isinstance(definition, dict):
                    reference_errors.append({"id": citation_id, "error": "NOT_MAPPING"})
                    continue
                source = definition.get("source")
                supports = definition.get("supports")
                source_valid = isinstance(source, str) and any(
                    pattern.search(source) for pattern in source_res
                )
                supports_valid = isinstance(supports, list) and all(
                    isinstance(item, str) and item.strip() for item in supports
                )
                if not source_valid:
                    reference_errors.append({"id": citation_id, "error": "SOURCE_INVALID"})
                if config["json_reference_support_required"] and not supports_valid:
                    reference_errors.append({"id": citation_id, "error": "SUPPORTS_INVALID"})
                if source_valid and supports_valid:
                    references[citation_id] = {
                        "source": source,
                        "supports": {_normalize(item) for item in supports},
                    }
        elif raw_references is not None:
            reference_errors.append({"id": None, "error": "REFERENCES_NOT_MAPPING"})
    else:
        for section, body in parsed.sections.items():
            for line in body.splitlines():
                match = _MARKDOWN_REFERENCE_RE.match(line)
                if match is None:
                    continue
                citation_id, detail = match.groups()
                if any(pattern.search(detail) for pattern in source_res):
                    if citation_id in references or citation_id in duplicate_reference_ids:
                        reference_errors.append(
                            {"id": citation_id, "error": "DUPLICATE_DEFINITION"}
                        )
                        duplicate_reference_ids.add(citation_id)
                        references.pop(citation_id, None)
                        continue
                    references[citation_id] = {
                        "source": detail,
                        "supports": None,
                        "defined_in": section,
                    }

    if parsed.json_payload is not None:
        scoped_lines = [
            (heading, offset + 1, offset, line, body.splitlines())
            for heading, body in parsed.sections.items()
            for offset, line in enumerate(body.splitlines())
        ]
    else:
        lines = parsed.body.splitlines()
        scoped_lines = []
        current = "__preamble__"
        current_lines: list[str] = []
        section_starts: list[tuple[str, int, list[str]]] = []
        for index, line in enumerate(lines):
            heading = _HEADING_RE.match(line)
            if heading:
                if current_lines:
                    section_starts.append((current, index - len(current_lines), current_lines))
                current = _normalize(heading.group(2))
                current_lines = []
            else:
                current_lines.append(line)
        if current_lines:
            section_starts.append((current, len(lines) - len(current_lines), current_lines))
        scoped_lines = [
            (heading, start + offset + 1, offset, line, section_lines)
            for heading, start, section_lines in section_starts
            for offset, line in enumerate(section_lines)
        ]

    claims: list[dict[str, Any]] = []
    bound = 0
    for heading, line_number, local_index, line, section_lines in scoped_lines:
        if heading in ignored_headings:
            continue
        if not claim_re.search(line):
            continue
        # Both formats stay within their current section. In particular, a
        # JSON citation in one field cannot satisfy a claim in another field.
        left = max(0, local_index - window)
        right = min(len(section_lines), local_index + window + 1)
        context = "\n".join(section_lines[left:right])
        citation_ids = list(dict.fromkeys(_CITATION_ID_RE.findall(context)))
        unresolved = [item for item in citation_ids if item not in references]
        wrong_scope: list[str] = []
        if parsed.json_payload is not None:
            for citation_id in citation_ids:
                reference = references.get(citation_id)
                if reference is not None and heading not in reference["supports"]:
                    wrong_scope.append(citation_id)
        cited = bool(citation_ids) and not unresolved and not wrong_scope
        bound += int(cited)
        claims.append(
            {
                "section": heading,
                "line": line_number,
                "cited": cited,
                "citation_ids": citation_ids,
                "unresolved_ids": unresolved,
                "wrong_scope_ids": wrong_scope,
                "excerpt": line.strip()[:240],
            }
        )
    rate = bound / len(claims) if claims else 0.0
    required_rate = float(config["min_binding_rate"])
    return {
        "passed": bool(claims) and rate >= required_rate and not reference_errors,
        "claim_count": len(claims),
        "bound_count": bound,
        "binding_rate": round(rate, 6),
        "required_rate": required_rate,
        "reference_count": len(references),
        "reference_errors": reference_errors,
        "uncited_claims": [item for item in claims if not item["cited"]][:20],
    }


def _metric_slug(label: str) -> str:
    normalized = _normalize(label)
    aliases = (
        (("annual", "return"), "annualized_return"),
        (("sharpe",), "oos_sharpe"),
        (("maxdd",), "max_dd"),
        (("max drawdown",), "max_dd"),
        (("mean r",), "mean_R_after_fees"),
        (("trades per year",), "trades_per_year"),
        (("trade",), "n_trades"),
        (("monthly roi",), "monthly_roi"),
        (("win rate",), "win_rate"),
        (("profit factor",), "profit_factor"),
    )
    for needles, canonical in aliases:
        if all(needle in normalized for needle in needles):
            return canonical
    return "_".join(_WORD_RE.findall(normalized))


def _extract_accept_gates(
    parsed: _ParsedArtifact, *, matched_sections: dict[str, list[str]]
) -> list[str]:
    if parsed.json_payload is not None:
        gates = parsed.json_payload.get("accept_gates", [])
        return [str(item).strip() for item in gates] if isinstance(gates, list) else []

    bodies = [parsed.sections[item] for item in matched_sections.get("accept_gates", [])]
    gates: list[str] = []
    for body in bodies:
        for line in body.splitlines():
            for candidate in _BACKTICK_RE.findall(line):
                if _COMPARATOR_RE.search(candidate):
                    gates.append(candidate.strip().replace("≤", "<=").replace("≥", ">="))
            cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
            if len(cells) >= 2 and _COMPARATOR_RE.fullmatch(cells[1].replace(" ", "")):
                threshold = cells[1].replace("≤", "<=").replace("≥", ">=")
                gates.append(f"{_metric_slug(cells[0])} {threshold}")
            elif line.lstrip().startswith(("-", "*")) and _COMPARATOR_RE.search(line):
                cleaned = line.lstrip(" -*\t").strip()
                if not _BACKTICK_RE.search(line):
                    gates.append(cleaned.replace("≤", "<=").replace("≥", ">="))
    return list(dict.fromkeys(gates))


def _gate_parseability_check(
    parsed: _ParsedArtifact,
    *,
    config: dict[str, Any],
    matched_sections: dict[str, list[str]],
) -> dict[str, Any]:
    gates = _extract_accept_gates(parsed, matched_sections=matched_sections)
    outcomes: list[dict[str, Any]] = []
    parseable = 0
    for gate in gates:
        outcome = evaluate_accept_gate(gate, {})
        valid = str(outcome.get("status")) not in {"INVALID", "UNSUPPORTED"}
        parseable += int(valid)
        outcomes.append(
            {
                "gate": gate,
                "parseable": valid,
                "parser_status": str(outcome.get("status")),
                "canonical": outcome.get("canonical"),
            }
        )
    rate = parseable / len(gates) if gates else 0.0
    passed = len(gates) >= int(config["min_gate_count"]) and rate >= float(config["min_parse_rate"])
    return {
        "passed": passed,
        "gate_count": len(gates),
        "parseable_count": parseable,
        "parse_rate": round(rate, 6),
        "required_count": int(config["min_gate_count"]),
        "required_rate": float(config["min_parse_rate"]),
        "outcomes": outcomes,
    }


def _fingerprint(body: str) -> str:
    canonical = _normalize(body)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _shingles(body: str, *, size: int) -> set[tuple[str, ...]]:
    tokens = _WORD_RE.findall(_normalize(body))
    if len(tokens) < size:
        return {tuple(tokens)} if tokens else set()
    return {tuple(tokens[index : index + size]) for index in range(len(tokens) - size + 1)}


def _similarity(left: set[tuple[str, ...]], right: set[tuple[str, ...]]) -> float:
    if not left and not right:
        return 1.0
    union = left | right
    return len(left & right) / len(union) if union else 0.0


def _check_row(
    *, passed: bool, score_ratio: float, critical: bool, detail: dict[str, Any]
) -> dict[str, Any]:
    return {
        "passed": bool(passed),
        "score_ratio": round(max(0.0, min(float(score_ratio), 1.0)), 6),
        "critical": critical,
        **detail,
    }


def _finalize_case(case: dict[str, Any], raw_config: dict[str, Any]) -> None:
    weights = raw_config["thresholds"]["weights"]
    total_weight = sum(float(value) for value in weights.values())
    earned = sum(
        float(weights[name]) * float(case["checks"][name]["score_ratio"]) for name in _CHECK_NAMES
    )
    score = earned / total_weight
    critical_failures = [
        name
        for name, row in case["checks"].items()
        if row["critical"] and row["passed"] is not True
    ]
    case["score"] = round(score, 6)
    case["critical_failures"] = critical_failures
    case["status"] = (
        "PASS"
        if score >= float(raw_config["thresholds"]["min_case_score"]) and not critical_failures
        else "FAIL"
    )


def _metadata_schema_errors(metadata: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for field in ("doc_id", "doc_type", "agent_id"):
        value = metadata.get(field)
        if not isinstance(value, str) or not value.strip():
            errors.append(f"{field}:expected_non_empty_string")

    created_at = metadata.get("created_at")
    parsed_created_at: datetime | None = None
    if isinstance(created_at, datetime):
        parsed_created_at = created_at
    elif isinstance(created_at, str):
        try:
            parsed_created_at = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        except ValueError:
            errors.append("created_at:invalid_iso8601")
    else:
        errors.append("created_at:expected_timestamp")
    if parsed_created_at is not None and parsed_created_at.tzinfo is None:
        errors.append("created_at:timezone_required")

    status = metadata.get("status")
    if not isinstance(status, str):
        errors.append("status:expected_string")
    elif status.strip().upper() not in _STATUS_VALUES:
        errors.append(f"status:unsupported_enum:{status}")

    confidence = metadata.get("confidence")
    if (
        isinstance(confidence, bool)
        or not isinstance(confidence, (int, float))
        or not math.isfinite(float(confidence))
        or not 0 <= float(confidence) <= 1
    ):
        errors.append("confidence:expected_finite_number_in_0_1")
    return errors


def _evaluate_parsed(parsed: _ParsedArtifact, raw_config: dict[str, Any]) -> dict[str, Any]:
    contract = raw_config["artifact_contract"]
    critical_names = set(raw_config["thresholds"]["critical_checks"])
    issues: list[dict[str, Any]] = []

    parse_passed = not parsed.parse_errors
    if not parse_passed:
        issues.extend({"code": "PARSE_ERROR", "detail": item} for item in parsed.parse_errors)

    required_fields = contract["required_metadata_fields"]
    missing_fields = [
        field
        for field in required_fields
        if field not in parsed.metadata or parsed.metadata.get(field) in (None, "", [])
    ]
    if missing_fields:
        issues.append({"code": "REQUIRED_FIELD_MISSING", "detail": missing_fields})
    metadata_schema_errors = _metadata_schema_errors(parsed.metadata)
    if metadata_schema_errors:
        issues.append({"code": "METADATA_SCHEMA_INVALID", "detail": metadata_schema_errors})
    field_ratio = (len(required_fields) - len(missing_fields)) / len(required_fields)
    if metadata_schema_errors:
        field_ratio *= max(
            0.0,
            1.0 - len(metadata_schema_errors) / len(_MANDATORY_METADATA_FIELDS),
        )

    matched_sections, missing_sections = _match_sections(parsed, contract["required_sections"])
    if missing_sections:
        issues.append({"code": "REQUIRED_SECTION_MISSING", "detail": missing_sections})
    section_ratio = (len(contract["required_sections"]) - len(missing_sections)) / len(
        contract["required_sections"]
    )

    numeric = _numeric_citation_check(
        parsed,
        config=raw_config["numeric_claims"],
        matched_sections=matched_sections,
    )
    if not numeric["passed"]:
        issues.append(
            {
                "code": "NUMERIC_CITATION_MISSING",
                "detail": {
                    "claim_count": numeric["claim_count"],
                    "binding_rate": numeric["binding_rate"],
                },
            }
        )

    gates = _gate_parseability_check(
        parsed,
        config=raw_config["accept_gates"],
        matched_sections=matched_sections,
    )
    if not gates["passed"]:
        issues.append(
            {
                "code": "ACCEPT_GATE_INVALID",
                "detail": {
                    "gate_count": gates["gate_count"],
                    "parse_rate": gates["parse_rate"],
                },
            }
        )

    normalized_content = _normalize(parsed.raw_text)
    phrase_hits = [
        phrase
        for phrase in raw_config["forbidden_content"]["phrases"]
        if _normalize(phrase) in normalized_content
    ]
    if phrase_hits:
        issues.append({"code": "FORBIDDEN_PHRASE", "detail": phrase_hits})

    authority_hits: list[str] = []
    for pattern in raw_config["forbidden_content"]["authority_patterns"]:
        if re.search(pattern, parsed.raw_text, re.IGNORECASE):
            authority_hits.append(pattern)
    if authority_hits:
        issues.append({"code": "AUTHORITY_BOUNDARY_VIOLATION", "detail": authority_hits})

    checks = {
        "parse": _check_row(
            passed=parse_passed,
            score_ratio=float(parse_passed),
            critical="parse" in critical_names,
            detail={"errors": parsed.parse_errors},
        ),
        "required_fields": _check_row(
            passed=not missing_fields and not metadata_schema_errors,
            score_ratio=field_ratio,
            critical="required_fields" in critical_names,
            detail={"missing": missing_fields, "schema_errors": metadata_schema_errors},
        ),
        "required_sections": _check_row(
            passed=not missing_sections,
            score_ratio=section_ratio,
            critical="required_sections" in critical_names,
            detail={"missing": missing_sections, "matched": matched_sections},
        ),
        "numeric_citation_binding": _check_row(
            passed=numeric["passed"],
            score_ratio=numeric["binding_rate"],
            critical="numeric_citation_binding" in critical_names,
            detail=numeric,
        ),
        "accept_gate_parseability": _check_row(
            passed=gates["passed"],
            score_ratio=gates["parse_rate"],
            critical="accept_gate_parseability" in critical_names,
            detail=gates,
        ),
        "forbidden_phrases": _check_row(
            passed=not phrase_hits,
            score_ratio=float(not phrase_hits),
            critical="forbidden_phrases" in critical_names,
            detail={"hits": phrase_hits},
        ),
        "authority_boundary": _check_row(
            passed=not authority_hits,
            score_ratio=float(not authority_hits),
            critical="authority_boundary" in critical_names,
            detail={"matched_patterns": authority_hits},
        ),
        "novelty": _check_row(
            passed=True,
            score_ratio=1.0,
            critical="novelty" in critical_names,
            detail={"nearest_case_id": None, "max_similarity": 0.0, "exact_duplicate": False},
        ),
    }
    case = {
        "case_id": parsed.case_id,
        "source": parsed.source,
        "format": parsed.format,
        "input_sha256": parsed.raw_sha256,
        "input_size_bytes": parsed.raw_size_bytes,
        "fingerprint_sha256": _fingerprint(parsed.body),
        "issues": issues,
        "checks": checks,
        "promotion_authorized": False,
        "deployment_authorized": False,
    }
    _finalize_case(case, raw_config)
    return case


def _apply_novelty(
    cases: list[dict[str, Any]], parsed: list[_ParsedArtifact], raw: dict[str, Any]
) -> int:
    size = int(raw["novelty"]["shingle_size"])
    threshold = float(raw["novelty"]["max_similarity"])
    shingle_sets = [_shingles(item.body, size=size) for item in parsed]
    duplicate_count = 0
    for index, case in enumerate(cases):
        if index == 0:
            continue
        similarities = [
            _similarity(shingle_sets[index], shingle_sets[prior]) for prior in range(index)
        ]
        nearest_index = max(range(index), key=lambda prior: similarities[prior])
        similarity = similarities[nearest_index]
        exact = case["fingerprint_sha256"] == cases[nearest_index]["fingerprint_sha256"]
        passed = not exact and similarity <= threshold
        if not passed:
            duplicate_count += 1
            case["issues"].append(
                {
                    "code": "DUPLICATE_CONTENT" if exact else "LOW_NOVELTY",
                    "detail": {
                        "nearest_case_id": cases[nearest_index]["case_id"],
                        "similarity": round(similarity, 6),
                    },
                }
            )
        critical = "novelty" in raw["thresholds"]["critical_checks"]
        case["checks"]["novelty"] = _check_row(
            passed=passed,
            score_ratio=max(0.0, 1.0 - similarity),
            critical=critical,
            detail={
                "nearest_case_id": cases[nearest_index]["case_id"],
                "max_similarity": round(similarity, 6),
                "exact_duplicate": exact,
                "allowed_similarity": threshold,
            },
        )
        _finalize_case(case, raw)
    return duplicate_count


def _invalid_path_parsed(case_id: str, source: str, detail: str) -> _ParsedArtifact:
    return _ParsedArtifact(
        case_id=case_id,
        source=source,
        format="unknown",
        raw_text="",
        body="",
        metadata={},
        sections={},
        json_payload=None,
        parse_errors=[f"INPUT_PATH_INVALID:{detail}"],
        raw_sha256=hashlib.sha256(b"").hexdigest(),
        raw_size_bytes=0,
    )


def _golden_calibration(config: EvalConfig) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    all_match = True
    for item in config.raw["golden_cases"]:
        parsed = _parse_artifact(
            case_id=item["id"],
            source=f"<golden:{item['id']}>",
            text=item["content"],
            artifact_format=item["format"],
        )
        result = _evaluate_parsed(parsed, config.raw)
        issue_codes = {issue["code"] for issue in result["issues"]}
        required_codes = set(item.get("required_issue_codes", []))
        matches = result["status"] == item["expected_status"] and required_codes <= issue_codes
        all_match &= matches
        results.append(
            {
                "case_id": item["id"],
                "expected_status": item["expected_status"],
                "actual_status": result["status"],
                "required_issue_codes": sorted(required_codes),
                "actual_issue_codes": sorted(issue_codes),
                "matches": matches,
            }
        )
    return {"all_cases_match": all_match, "cases": results}


def evaluate_agent_outputs(
    config: EvalConfig | str | Path = "configs/agent_output_eval.yaml",
    *,
    repo_root: Path = REPO_ROOT,
    input_paths: list[str] | None = None,
    evaluated_at: datetime | None = None,
) -> dict[str, Any]:
    """Evaluate configured stored artifacts without mutating them."""

    loaded = (
        config if isinstance(config, EvalConfig) else load_eval_config(config, repo_root=repo_root)
    )
    deterministic_as_of = evaluated_at is not None
    now = evaluated_at or datetime.now(UTC)
    if now.tzinfo is None:
        raise AgentOutputEvalError("evaluated_at must be timezone-aware")
    now = now.astimezone(UTC)
    raw = loaded.raw
    allowed_input_roots = _relative_roots(
        raw["paths"]["allowed_input_roots"],
        root=loaded.repo_root,
        field="allowed_input_roots",
    )
    configured_paths = raw["inputs"]["paths"] if input_paths is None else input_paths
    parsed_cases: list[_ParsedArtifact] = []
    limits = raw["limits"]
    if len(configured_paths) > int(limits["max_inputs"]):
        parsed_cases.append(
            _invalid_path_parsed(
                "input-limit",
                "<input-list>",
                f"INPUT_COUNT_LIMIT:{len(configured_paths)}>{limits['max_inputs']}",
            )
        )
        configured_paths = []
    total_input_bytes = 0
    for index, path_value in enumerate(configured_paths):
        if not isinstance(path_value, str) or not path_value.strip():
            parsed_cases.append(
                _invalid_path_parsed(
                    f"input-{index + 1}:invalid",
                    repr(path_value),
                    "input path must be a non-empty repository-relative string",
                )
            )
            continue
        case_id = f"input-{index + 1}:{Path(path_value).name or 'invalid'}"
        try:
            path = _safe_repo_relative_path(
                path_value,
                root=loaded.repo_root,
                allowed_roots=allowed_input_roots,
                must_exist=True,
            )
            suffix = path.suffix.lower()
            artifact_format = (
                "markdown"
                if suffix in {".md", ".markdown"}
                else "json"
                if suffix == ".json"
                else suffix.lstrip(".")
            )
            input_size = path.stat().st_size
            if input_size > int(limits["max_input_bytes"]):
                raise AgentOutputEvalError(
                    f"INPUT_BYTE_LIMIT:{input_size}>{limits['max_input_bytes']}"
                )
            if total_input_bytes + input_size > int(limits["max_total_input_bytes"]):
                raise AgentOutputEvalError(
                    "TOTAL_INPUT_BYTE_LIMIT:"
                    f"{total_input_bytes + input_size}>{limits['max_total_input_bytes']}"
                )
            content_bytes = path.read_bytes()
            if len(content_bytes) != input_size:
                raise AgentOutputEvalError("input changed while being read")
            total_input_bytes += len(content_bytes)
            parsed_cases.append(
                _parse_artifact(
                    case_id=case_id,
                    source=str(path.relative_to(loaded.repo_root)),
                    text=content_bytes.decode("utf-8"),
                    artifact_format=artifact_format,
                    raw_bytes=content_bytes,
                )
            )
        except (AgentOutputEvalError, OSError, UnicodeError) as exc:
            parsed_cases.append(_invalid_path_parsed(case_id, path_value, str(exc)))

    cases = [_evaluate_parsed(item, raw) for item in parsed_cases]
    duplicate_count = _apply_novelty(cases, parsed_cases, raw)
    golden = _golden_calibration(loaded)
    input_count = len(cases)
    pass_count = sum(case["status"] == "PASS" for case in cases)
    parse_error_count = sum(bool(item.parse_errors) for item in parsed_cases)
    mean_score = sum(float(case["score"]) for case in cases) / input_count if input_count else 0.0
    pass_rate = pass_count / input_count if input_count else 0.0
    thresholds = raw["thresholds"]
    aggregate_checks = {
        "has_inputs": input_count > 0,
        "golden_contract_matches": golden["all_cases_match"],
        "aggregate_score_passed": mean_score >= float(thresholds["min_aggregate_score"]),
        "pass_rate_passed": pass_rate >= float(thresholds["min_pass_rate"]),
        "parse_error_budget_passed": parse_error_count <= int(thresholds["max_parse_errors"]),
        "duplicate_budget_passed": duplicate_count <= int(thresholds["max_duplicates"]),
    }
    if not input_count:
        status = "HOLD"
        verdict = "HOLD_NO_INPUTS"
    elif all(aggregate_checks.values()):
        status = "PASS"
        verdict = "QUALITY_GATE_PASS"
    else:
        status = "FAIL"
        verdict = "QUALITY_GATE_FAIL"

    return {
        "schema_version": REPORT_SCHEMA,
        "evaluated_at": now.isoformat().replace("+00:00", "Z"),
        "deterministic_as_of": deterministic_as_of,
        "status": status,
        "verdict": verdict,
        "quality_gate_only": QUALITY_GATE_ONLY,
        "promotion_authorized": PROMOTION_AUTHORIZED,
        "deployment_authorized": False,
        "live_authorized": False,
        "order_authorized": False,
        "network_path_enabled": NETWORK_PATH_ENABLED,
        "order_path_enabled": ORDER_PATH_ENABLED,
        "config_path": str(loaded.path.relative_to(loaded.repo_root)),
        "config_sha256": loaded.content_sha256,
        "config_size_bytes": loaded.content_size_bytes,
        "golden_contract": golden,
        "cases": cases,
        "aggregate": {
            "input_count": input_count,
            "pass_count": pass_count,
            "fail_count": input_count - pass_count,
            "parse_error_count": parse_error_count,
            "duplicate_or_low_novelty_count": duplicate_count,
            "total_input_bytes": sum(item.raw_size_bytes for item in parsed_cases),
            "mean_score": round(mean_score, 6),
            "pass_rate": round(pass_rate, 6),
            "thresholds": {
                key: thresholds[key]
                for key in (
                    "min_case_score",
                    "min_aggregate_score",
                    "min_pass_rate",
                    "max_parse_errors",
                    "max_duplicates",
                )
            },
            "checks": aggregate_checks,
        },
    }


def write_report(
    report: dict[str, Any],
    config: EvalConfig,
    *,
    path: str | None = None,
) -> Path:
    """Atomically write the only allowed output artifact."""

    if report.get("deterministic_as_of") is not True:
        raise AgentOutputEvalError("report writing requires an explicit deterministic as-of")
    if report.get("config_sha256") != config.content_sha256:
        raise AgentOutputEvalError("report/config provenance mismatch")
    if report.get("schema_version") != REPORT_SCHEMA:
        raise AgentOutputEvalError("unexpected report schema")
    for field in (
        "promotion_authorized",
        "deployment_authorized",
        "live_authorized",
        "order_authorized",
    ):
        if report.get(field) is not False:
            raise AgentOutputEvalError(f"unsafe report authority field: {field}")
    path_value = path or config.raw["report"]["path"]
    allowed = _relative_roots(
        config.raw["paths"]["allowed_report_roots"],
        root=config.repo_root,
        field="allowed_report_roots",
    )
    output = _safe_repo_relative_path(
        path_value,
        root=config.repo_root,
        allowed_roots=allowed,
        must_exist=False,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    raw = (json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode()
    fd, temp_name = tempfile.mkstemp(prefix=f".{output.name}.", dir=output.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, output)
        directory_fd = os.open(output.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)
    return output
