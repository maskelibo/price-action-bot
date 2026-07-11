"""Fail-closed reporter for the preregistered crypto 15-minute V18 batch.

The reporter never opens a market or funding database and never runs a replay.
It verifies the completed shard bundle, reconstructs every metric from the raw
engine ledgers, applies the frozen gates, and emits historical-feasibility
evidence only.  It cannot authorize paper or live trading.
"""

from __future__ import annotations

import argparse
import copy
import gc
import hashlib
import json
import math
import os
import subprocess
import tempfile
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from price_action.lab import crypto_15m_v15p2_report as baseline_report
from price_action.lab import crypto_15m_v18_program as v18_program
from price_action.lab import crypto_15m_v18_validation as v18_validation
from price_action.lab.crypto_15m_validation import (
    block_bootstrap_lower_bound_pct,
    monthly_return_statistics,
    trimmed_mean_pct,
)

REPORT_SCHEMA = "crypto-15m-v18-primary-report-v1"
MANIFEST_SCHEMA = "crypto-15m-v18-primary-bundle-manifest-v1"
SHARD_SCHEMA = "crypto-15m-v18-scenario-shard-v1"
LOSO_MANIFEST_SCHEMA = "crypto-15m-v18-true-loso-bundle-manifest-v1"
LOSO_SHARD_SCHEMA = "crypto-15m-v18-true-loso-shard-v1"
PREREG_SCHEMA = "crypto-15m-v18-challenger-prereg-v1"
LOCK_SCHEMA = "crypto-15m-v18-execution-lock-v1"
BASELINE_IDENTITY_SCHEMA = "crypto-15m-v15p2-fair-baseline-v2-result-identity-v1"
CANONICAL_PREREG_RELATIVE = "configs/crypto_15m_v18_challenger_prereg.yaml"
CANONICAL_LOCK_RELATIVE = "configs/crypto_15m_v18_execution_lock.json"
CANONICAL_BASELINE_IDENTITY_RELATIVE = (
    "configs/crypto_15m_v15p2_fair_baseline_v2_result_identity.json"
)
CANONICAL_PRIMARY_MANIFEST_RELATIVE = "reports/research/crypto_15m_v18_primary_bundle/manifest.json"
CANONICAL_PRIMARY_REPORT_JSON_RELATIVE = "reports/research/crypto_15m_v18_primary_report.json"
CANONICAL_PRIMARY_REPORT_MARKDOWN_RELATIVE = "reports/research/CRYPTO_15M_V18_PRIMARY_REPORT.md"
CANONICAL_LOSO_MANIFEST_RELATIVE = "reports/research/crypto_15m_v18_loso_bundle/manifest.json"
CANONICAL_FINAL_REPORT_JSON_RELATIVE = "reports/research/crypto_15m_v18_final_report.json"
CANONICAL_FINAL_REPORT_MARKDOWN_RELATIVE = "reports/research/CRYPTO_15M_V18_FINAL_REPORT.md"
CANDIDATE_ORDER = (
    "C1_VSA_ONLY",
    "C2_GRIMES_ONLY",
    "C3_DUAL_HTF50",
    "C4_VSA_HTF50",
)
SCENARIO_ORDER = ("B", "C2", "H")
EVALUATION_START = pd.Timestamp("2021-06-01T00:00:00Z")
DEVELOPMENT_END = pd.Timestamp("2023-06-01T00:00:00Z")
EVALUATION_END = pd.Timestamp("2026-06-01T00:00:00Z")
BAR = pd.Timedelta(minutes=15)


class V18ReportContractError(ValueError):
    """Raised when an artifact cannot qualify as V18 evidence."""


def _canonical_json(value: Any) -> bytes:
    try:
        rendered = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise V18ReportContractError("artifact is not strict finite JSON") from exc
    return rendered.encode("utf-8")


def _payload_sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_json(path: Path, *, name: str) -> dict[str, Any]:
    def reject_duplicate(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise V18ReportContractError(f"{name} contains duplicate JSON key {key!r}")
            result[key] = value
        return result

    try:
        loaded = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=reject_duplicate,
            parse_constant=lambda value: (_ for _ in ()).throw(
                V18ReportContractError(f"{name} contains non-finite constant {value}")
            ),
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise V18ReportContractError(f"could not read {name}: {path}") from exc
    if not isinstance(loaded, dict):
        raise V18ReportContractError(f"{name} must be a JSON object")
    _canonical_json(loaded)
    return loaded


def _mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise V18ReportContractError(f"{name} must be a mapping")
    return value


def _list(value: Any, name: str) -> list[Any]:
    if not isinstance(value, list):
        raise V18ReportContractError(f"{name} must be a list")
    return value


def _finite(value: Any, name: str, *, positive: bool = False) -> float:
    if isinstance(value, bool):
        raise V18ReportContractError(f"{name} must be numeric")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise V18ReportContractError(f"{name} must be numeric") from exc
    if not math.isfinite(number) or (positive and number <= 0.0):
        raise V18ReportContractError(f"{name} is non-finite or outside its domain")
    return number


def _utc(value: Any, name: str) -> pd.Timestamp:
    try:
        timestamp = pd.Timestamp(value)
    except (TypeError, ValueError) as exc:
        raise V18ReportContractError(f"{name} is not a timestamp") from exc
    if timestamp.tzinfo is None:
        raise V18ReportContractError(f"{name} must carry a UTC offset")
    if timestamp.utcoffset() != pd.Timedelta(0):
        raise V18ReportContractError(f"{name} must use exact UTC offset zero")
    return timestamp.tz_convert("UTC")


def _verify_file(path: Path, spec: Mapping[str, Any], *, name: str) -> None:
    if path.is_symlink() or not path.is_file():
        raise V18ReportContractError(f"{name} is missing, non-regular, or a symlink")
    expected_bytes = int(spec.get("bytes", -1))
    if path.stat().st_size != expected_bytes:
        raise V18ReportContractError(f"{name} byte identity mismatch")
    expected_sha = str(spec.get("sha256", ""))
    if _file_sha256(path) != expected_sha:
        raise V18ReportContractError(f"{name} SHA-256 identity mismatch")


def _safe_bundle_child(bundle_root: Path, relative: Any, *, name: str) -> Path:
    if not isinstance(relative, str) or not relative or Path(relative).is_absolute():
        raise V18ReportContractError(f"{name} must be a non-empty relative path")
    lexical = bundle_root / relative
    if lexical.is_symlink():
        raise V18ReportContractError(f"{name} may not be a symlink")
    resolved_root = bundle_root.resolve()
    resolved = lexical.resolve()
    if resolved_root not in resolved.parents:
        raise V18ReportContractError(f"{name} escapes the bundle root")
    return lexical


def _manifest_identity(
    root: Path,
    relative: str,
    spec: Mapping[str, Any],
    *,
    name: str,
) -> dict[str, Any]:
    if spec.get("path") != relative:
        raise V18ReportContractError(f"{name} canonical path drifted")
    path = root / relative
    _verify_file(path, spec, name=name)
    return {
        "path": relative,
        "bytes": path.stat().st_size,
        "sha256": _file_sha256(path),
    }


def _validate_frozen_identity_map(
    actual: Any,
    expected: Mapping[str, Any],
    *,
    name: str,
) -> None:
    mapping = _mapping(actual, name)
    if set(mapping) != set(expected):
        raise V18ReportContractError(f"{name} scope drifted")
    for key, spec in expected.items():
        row = _mapping(mapping[key], f"{name}.{key}")
        configured = str(spec["path"])
        if (
            row.get("configured_path") != configured
            or row.get("bytes") != int(spec["bytes"])
            or row.get("sha256") != str(spec["sha256"])
            or row.get("status") != "VERIFIED"
        ):
            raise V18ReportContractError(f"{name}.{key} identity drifted")


def _validate_manifest_governance(
    manifest: Mapping[str, Any],
    *,
    prereg: Mapping[str, Any],
    repo_root: Path,
) -> dict[str, Any]:
    required = {
        "schema_version",
        "program_schema_version",
        "status",
        "evidence_eligible",
        "candidate_order",
        "scenario_order",
        "replay_order",
        "preregistration",
        "execution_lock",
        "baseline_result_identity",
        "baseline_evidence_artifacts",
        "runtime_git_commit",
        "locked_source_commit",
        "source_preflight",
        "source_postflight",
        "runtime_preflight",
        "runtime_postflight",
        "lineage",
        "snapshots",
        "input_hashes",
        "generation_counts",
        "shards",
        "manifest_published_last",
        "live_or_paper_authorized",
    }
    if set(manifest) != required:
        raise V18ReportContractError("manifest governance field set drifted")
    if manifest.get("program_schema_version") != v18_program.PROGRAM_SCHEMA:
        raise V18ReportContractError("manifest program schema drifted")
    if manifest.get("evidence_eligible") is not True:
        raise V18ReportContractError("runner manifest is not evidence eligible")
    if manifest.get("manifest_published_last") is not True:
        raise V18ReportContractError("manifest-last publication was not attested")
    if manifest.get("live_or_paper_authorized") is not False:
        raise V18ReportContractError("runner manifest improperly authorizes deployment")

    expected_replays = [
        {"candidate_id": candidate, "scenario": scenario}
        for candidate in CANDIDATE_ORDER
        for scenario in SCENARIO_ORDER
    ]
    if manifest.get("replay_order") != expected_replays:
        raise V18ReportContractError("manifest replay order drifted")

    prereg_spec = _mapping(manifest.get("preregistration"), "manifest preregistration")
    prereg_identity = _manifest_identity(
        repo_root,
        CANONICAL_PREREG_RELATIVE,
        prereg_spec,
        name="V18 preregistration",
    )
    try:
        canonical_prereg = v18_program.load_preregistration(repo_root / CANONICAL_PREREG_RELATIVE)
    except (OSError, ValueError) as exc:
        raise V18ReportContractError(str(exc)) from exc
    if _canonical_json(canonical_prereg) != _canonical_json(dict(prereg)):
        raise V18ReportContractError("report preregistration differs from canonical file")

    lock_spec = _mapping(manifest.get("execution_lock"), "manifest execution lock")
    lock_identity = _manifest_identity(
        repo_root,
        CANONICAL_LOCK_RELATIVE,
        lock_spec,
        name="V18 execution lock",
    )
    try:
        lock = v18_program._load_execution_lock(repo_root / CANONICAL_LOCK_RELATIVE)
        current_source = v18_program._source_provenance(lock, repo_root)
        v18_program._assert_source_ready(current_source)
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as exc:
        raise V18ReportContractError(str(exc)) from exc
    if manifest.get("source_preflight") != manifest.get("source_postflight"):
        raise V18ReportContractError("runner source preflight/postflight differ")
    if manifest.get("source_postflight") != current_source:
        raise V18ReportContractError("current locked source differs from runner provenance")
    if manifest.get("runtime_git_commit") != current_source["runtime_git_commit"]:
        raise V18ReportContractError("runtime git commit does not reconcile")
    if manifest.get("locked_source_commit") != current_source["locked_source_commit"]:
        raise V18ReportContractError("locked source commit does not reconcile")
    if manifest.get("runtime_preflight") != manifest.get("runtime_postflight"):
        raise V18ReportContractError("runner runtime preflight/postflight differ")
    current_runtime = v18_program.baseline._critical_runtime_versions(repo_root)
    if manifest.get("runtime_postflight") != current_runtime:
        raise V18ReportContractError("current runtime differs from runner provenance")

    baseline_spec = _mapping(manifest.get("baseline_result_identity"), "baseline result identity")
    baseline_identity = _manifest_identity(
        repo_root,
        CANONICAL_BASELINE_IDENTITY_RELATIVE,
        baseline_spec,
        name="baseline result identity",
    )
    try:
        baseline_evidence = v18_program._baseline_identity_evidence(
            repo_root / CANONICAL_BASELINE_IDENTITY_RELATIVE,
            root=repo_root,
            prereg=prereg,
            expected_execution_git_commit=str(lock["execution_git_commit"]),
        )
    except (OSError, RuntimeError, ValueError) as exc:
        raise V18ReportContractError(str(exc)) from exc
    if manifest.get("baseline_evidence_artifacts") != baseline_evidence:
        raise V18ReportContractError("baseline evidence artifacts do not reconcile")
    if baseline_evidence.get("runtime_versions") != current_runtime:
        raise V18ReportContractError("V18 runtime differs from sealed baseline runtime")

    lineage_specs = v18_program._lineage_specs(prereg)
    _validate_frozen_identity_map(manifest.get("lineage"), lineage_specs, name="manifest.lineage")
    snapshots = _mapping(prereg.get("snapshots"), "prereg snapshots")
    snapshot_specs = {name: _mapping(snapshots[name], name) for name in ("market", "funding")}
    _validate_frozen_identity_map(
        manifest.get("snapshots"), snapshot_specs, name="manifest.snapshots"
    )

    counts = _mapping(manifest.get("generation_counts"), "generation_counts")
    if counts != {
        "market_snapshot_loads": 1,
        "funding_snapshot_loads": 1,
        "baseline_signal_generations": 1,
        "candidate_adapter_generations": 1,
        "independent_engine_replays": 12,
    }:
        raise V18ReportContractError("runner generation counts drifted")
    hashes = _mapping(manifest.get("input_hashes"), "input_hashes")
    expected_hash_keys = {
        "engine_frames_sha256_by_symbol",
        "funding_events_sha256",
        "daily_returns_sha256",
        "baseline_decisions_sha256",
        "baseline_intents_sha256",
        "candidate_batches_sha256",
    }
    if set(hashes) != expected_hash_keys:
        raise V18ReportContractError("runner input-hash scope drifted")
    for name in (
        "funding_events_sha256",
        "daily_returns_sha256",
        "baseline_decisions_sha256",
        "baseline_intents_sha256",
    ):
        if not isinstance(hashes[name], str) or len(hashes[name]) != 64:
            raise V18ReportContractError(f"runner input hash {name} is invalid")
    frame_hashes = _mapping(hashes["engine_frames_sha256_by_symbol"], "frame hashes")
    candidate_hashes = _mapping(hashes["candidate_batches_sha256"], "candidate hashes")
    if set(frame_hashes) != set(v18_program.PRIMARY_SYMBOLS):
        raise V18ReportContractError("engine frame hash universe drifted")
    if tuple(candidate_hashes) != CANDIDATE_ORDER:
        raise V18ReportContractError("candidate batch hash order drifted")
    try:
        baseline_prereg = v18_program.baseline.load_preregistration(
            repo_root / v18_program.CANONICAL_BASELINE_PREREG_RELATIVE
        )
        expected_policy = v18_program.baseline._jsonable(
            v18_program.baseline.build_policy(baseline_prereg)
        )
        expected_scenarios = v18_program.baseline._jsonable(
            v18_program.baseline.build_scenarios(baseline_prereg)
        )
    except (OSError, RuntimeError, ValueError) as exc:
        raise V18ReportContractError(str(exc)) from exc
    return {
        "preregistration": prereg_identity,
        "execution_lock": lock_identity,
        "baseline_result_identity": baseline_identity,
        "input_hashes": dict(hashes),
        "expected_policy": expected_policy,
        "expected_scenarios": expected_scenarios,
        "runtime_git_commit": str(manifest["runtime_git_commit"]),
        "locked_source_commit": str(manifest["locked_source_commit"]),
    }


def _signal_key(row: Mapping[str, Any]) -> tuple[Any, ...]:
    return (
        _utc(row.get("decision_ts"), "signal decision_ts").isoformat(),
        _utc(row.get("entry_ts"), "signal entry_ts").isoformat(),
        str(row.get("symbol")),
        str(row.get("side")),
        str(row.get("strategy")),
    )


def _validate_candidate_signal_stream(
    shard: Mapping[str, Any],
    *,
    candidate_id: str,
    manifest_input_hashes: Mapping[str, Any],
) -> dict[str, Any]:
    stream = _mapping(shard.get("candidate_signal_stream"), "candidate_signal_stream")
    expected_fields = {
        "source_candidate_id",
        "cell_candidate_id",
        "baseline_decision_ledger_sha256",
        "baseline_intents_sha256",
        "adapter_decisions",
        "adapter_rejections",
        "source_intents",
        "engine_proxy_intents",
        "adapter_decisions_sha256",
        "adapter_rejections_sha256",
        "source_intents_sha256",
        "engine_proxy_intents_sha256",
        "reason_counts",
    }
    if set(stream) != expected_fields:
        raise V18ReportContractError("candidate signal-stream field set drifted")
    if stream.get("source_candidate_id") != "v15p2_fair_baseline":
        raise V18ReportContractError("candidate stream source identity drifted")
    if stream.get("cell_candidate_id") != candidate_id:
        raise V18ReportContractError("candidate stream cell identity drifted")
    if stream.get("baseline_decision_ledger_sha256") != manifest_input_hashes.get(
        "baseline_decisions_sha256"
    ):
        raise V18ReportContractError("baseline decision hash does not reconcile")
    if stream.get("baseline_intents_sha256") != manifest_input_hashes.get(
        "baseline_intents_sha256"
    ):
        raise V18ReportContractError("baseline intent hash does not reconcile")
    candidate_hashes = _mapping(
        manifest_input_hashes.get("candidate_batches_sha256"), "candidate batch hashes"
    )
    if shard.get("candidate_batch_sha256") != candidate_hashes.get(candidate_id):
        raise V18ReportContractError("shard candidate-batch hash does not reconcile")

    decisions = _list(stream.get("adapter_decisions"), "adapter_decisions")
    rejections = _list(stream.get("adapter_rejections"), "adapter_rejections")
    source_intents = _list(stream.get("source_intents"), "source_intents")
    proxies = _list(stream.get("engine_proxy_intents"), "engine_proxy_intents")
    payloads = {
        "adapter_decisions": decisions,
        "adapter_rejections": rejections,
        "source_intents": source_intents,
        "engine_proxy_intents": proxies,
    }
    for name, payload in payloads.items():
        if stream.get(f"{name}_sha256") != _payload_sha256(payload):
            raise V18ReportContractError(f"candidate stream {name} hash mismatch")

    normalized_decisions = [
        _mapping(row, f"adapter_decisions[{index}]") for index, row in enumerate(decisions)
    ]
    if [row.get("source_intent_index") for row in normalized_decisions] != list(
        range(len(normalized_decisions))
    ):
        raise V18ReportContractError("adapter decision indexes are not contiguous")
    if any(row.get("cell_id") != candidate_id for row in normalized_decisions):
        raise V18ReportContractError("adapter decision contains a foreign cell")
    if any(row.get("outcome") not in {"accepted", "rejected"} for row in normalized_decisions):
        raise V18ReportContractError("adapter decision outcome is invalid")
    expected_rejections = [row for row in normalized_decisions if row.get("outcome") == "rejected"]
    if rejections != expected_rejections:
        raise V18ReportContractError("adapter rejection ledger does not conserve decisions")
    accepted = [row for row in normalized_decisions if row.get("outcome") == "accepted"]
    if len(accepted) != len(source_intents):
        raise V18ReportContractError("accepted adapter decisions do not reconcile to intents")
    for index, (decision, raw_intent) in enumerate(zip(accepted, source_intents, strict=True)):
        intent = _mapping(raw_intent, f"source_intents[{index}]")
        if intent.get("candidate_id") != "v15p2_fair_baseline":
            raise V18ReportContractError("source intent candidate identity drifted")
        if _signal_key(decision) != _signal_key(intent):
            raise V18ReportContractError("accepted adapter decision differs from source intent")

    expected_proxies = [
        _mapping(intent, f"source_intents[{index}]")
        for index, intent in enumerate(source_intents)
        if EVALUATION_START
        <= _utc(_mapping(intent, "source intent").get("entry_ts"), "source entry_ts")
        < EVALUATION_END
    ]
    if len(proxies) != len(expected_proxies):
        raise V18ReportContractError("engine proxy count differs from evaluation intents")
    for index, (raw_proxy, source) in enumerate(zip(proxies, expected_proxies, strict=True)):
        proxy = _mapping(raw_proxy, f"engine_proxy_intents[{index}]")
        if (
            proxy.get("candidate_id") != "v15p2_fair_baseline"
            or proxy.get("source_candidate_id") != "v15p2_fair_baseline"
            or proxy.get("cell_id") != candidate_id
            or proxy.get("source_intent_sha256") != _payload_sha256(source)
        ):
            raise V18ReportContractError("engine proxy binding drifted")
        reconstructed = {
            key: value
            for key, value in proxy.items()
            if key not in {"cell_id", "source_candidate_id", "source_intent_sha256"}
        }
        if reconstructed != source:
            raise V18ReportContractError("engine proxy changed inherited intent fields")

    reason_counts = dict(
        sorted(Counter(str(row.get("reason")) for row in normalized_decisions).items())
    )
    if stream.get("reason_counts") != reason_counts:
        raise V18ReportContractError("adapter reason counts do not reconcile")
    return {
        "stream_sha256": _payload_sha256(stream),
        "decision_count": len(decisions),
        "accepted_count": len(source_intents),
        "rejected_count": len(rejections),
        "engine_proxy_count": len(proxies),
        "reason_counts": reason_counts,
        "engine_proxy_intents": proxies,
    }


def _validate_entries_originate_from_proxies(
    entries: Sequence[Mapping[str, Any]], proxies: Sequence[Mapping[str, Any]]
) -> None:
    available = Counter(
        baseline_report._signal_entry_key(proxy, engine_entry=False) for proxy in proxies
    )
    for index, entry in enumerate(entries):
        key = baseline_report._signal_entry_key(entry, engine_entry=True)
        if available[key] <= 0:
            raise V18ReportContractError(
                f"engine entry {index} does not originate from a candidate proxy intent"
            )
        available[key] -= 1


def _proxy_payload_from_source_intent(
    source: Mapping[str, Any], *, candidate_id: str
) -> dict[str, Any]:
    """Rebuild the exact engine proxy emitted by the governed V18 runner."""

    if source.get("candidate_id") != "v15p2_fair_baseline":
        raise V18ReportContractError("LOSO source intent candidate identity drifted")
    return {
        **source,
        "cell_id": candidate_id,
        "source_candidate_id": "v15p2_fair_baseline",
        "source_intent_sha256": _payload_sha256(source),
    }


def _validate_loso_signal_stream(
    shard: Mapping[str, Any],
    *,
    candidate_id: str,
    excluded_symbol: str,
    manifest_input_hashes: Mapping[str, Any],
    primary_signal_summary: Mapping[str, Any],
) -> dict[str, Any]:
    """Prove one holdout uses all and only the locked winner's eligible intents.

    The LOSO shard repeats the winner's complete adapter/source ledgers.  We
    reconstruct the original primary stream from those ledgers, bind it to the
    primary report's stream digest, and then derive the holdout proxy list by
    the sole allowed transformation: remove the excluded symbol (and intents
    outside the fixed evaluation interval).
    """

    stream = _mapping(shard.get("candidate_signal_stream"), "LOSO signal stream")
    expected_fields = {
        "source_candidate_id",
        "cell_candidate_id",
        "excluded_symbol",
        "baseline_decision_ledger_sha256",
        "baseline_intents_sha256",
        "adapter_decisions",
        "adapter_rejections",
        "source_intents",
        "engine_proxy_intents",
        "engine_proxy_intents_sha256",
        "excluded_source_intent_count",
    }
    if set(stream) != expected_fields:
        raise V18ReportContractError("true-LOSO signal-stream field set drifted")
    if (
        stream.get("source_candidate_id") != "v15p2_fair_baseline"
        or stream.get("cell_candidate_id") != candidate_id
        or stream.get("excluded_symbol") != excluded_symbol
    ):
        raise V18ReportContractError("true-LOSO signal-stream identity drifted")

    baseline_decisions_sha = str(manifest_input_hashes.get("baseline_decisions_sha256", ""))
    baseline_intents_sha = str(manifest_input_hashes.get("baseline_intents_sha256", ""))
    if (
        stream.get("baseline_decision_ledger_sha256") != baseline_decisions_sha
        or stream.get("baseline_intents_sha256") != baseline_intents_sha
    ):
        raise V18ReportContractError("true-LOSO baseline signal hashes do not reconcile")
    winner_batch_sha = str(manifest_input_hashes.get("locked_winner_batch_sha256", ""))
    if shard.get("candidate_batch_sha256") != winner_batch_sha:
        raise V18ReportContractError("true-LOSO candidate-batch hash does not reconcile")

    decisions = _list(stream.get("adapter_decisions"), "LOSO adapter decisions")
    rejections = _list(stream.get("adapter_rejections"), "LOSO adapter rejections")
    raw_sources = _list(stream.get("source_intents"), "LOSO source intents")
    sources = [
        _mapping(row, f"LOSO source_intents[{index}]") for index, row in enumerate(raw_sources)
    ]
    full_primary_proxies = [
        _proxy_payload_from_source_intent(source, candidate_id=candidate_id)
        for source in sources
        if EVALUATION_START <= _utc(source.get("entry_ts"), "LOSO source entry_ts") < EVALUATION_END
    ]
    reason_counts = dict(
        sorted(
            Counter(
                str(_mapping(row, "LOSO adapter decision").get("reason")) for row in decisions
            ).items()
        )
    )
    reconstructed_primary_stream = {
        "source_candidate_id": "v15p2_fair_baseline",
        "cell_candidate_id": candidate_id,
        "baseline_decision_ledger_sha256": baseline_decisions_sha,
        "baseline_intents_sha256": baseline_intents_sha,
        "adapter_decisions": decisions,
        "adapter_rejections": rejections,
        "source_intents": raw_sources,
        "engine_proxy_intents": full_primary_proxies,
        "adapter_decisions_sha256": _payload_sha256(decisions),
        "adapter_rejections_sha256": _payload_sha256(rejections),
        "source_intents_sha256": _payload_sha256(raw_sources),
        "engine_proxy_intents_sha256": _payload_sha256(full_primary_proxies),
        "reason_counts": reason_counts,
    }
    reconstructed = _validate_candidate_signal_stream(
        {
            "candidate_batch_sha256": winner_batch_sha,
            "candidate_signal_stream": reconstructed_primary_stream,
        },
        candidate_id=candidate_id,
        manifest_input_hashes={
            "baseline_decisions_sha256": baseline_decisions_sha,
            "baseline_intents_sha256": baseline_intents_sha,
            "candidate_batches_sha256": {candidate_id: winner_batch_sha},
        },
    )
    if reconstructed["stream_sha256"] != primary_signal_summary.get("stream_sha256"):
        raise V18ReportContractError("LOSO winner stream differs from the primary report")
    for key in (
        "decision_count",
        "accepted_count",
        "rejected_count",
        "engine_proxy_count",
        "reason_counts",
    ):
        if reconstructed[key] != primary_signal_summary.get(key):
            raise V18ReportContractError(f"LOSO primary signal summary {key} drifted")

    expected_proxies = [
        proxy for proxy in full_primary_proxies if proxy.get("symbol") != excluded_symbol
    ]
    actual_proxies = [
        dict(_mapping(row, f"LOSO engine_proxy_intents[{index}]"))
        for index, row in enumerate(
            _list(stream.get("engine_proxy_intents"), "LOSO engine proxies")
        )
    ]
    if stream.get("engine_proxy_intents_sha256") != _payload_sha256(actual_proxies):
        raise V18ReportContractError("true-LOSO engine-proxy hash mismatch")
    if actual_proxies != expected_proxies:
        raise V18ReportContractError(
            "true-LOSO proxies are not all-and-only non-holdout winner intents"
        )
    expected_excluded_count = len(sources) - len(expected_proxies)
    if stream.get("excluded_source_intent_count") != expected_excluded_count:
        raise V18ReportContractError("true-LOSO excluded-intent count drifted")
    return {
        "engine_proxy_intents": actual_proxies,
        "primary_stream_sha256": reconstructed["stream_sha256"],
        "source_intent_count": len(sources),
        "excluded_source_intent_count": expected_excluded_count,
    }


def _validate_shard_governance(
    shard: Mapping[str, Any],
    *,
    manifest: Mapping[str, Any],
    candidate_id: str,
    scenario: str,
    manifest_input_hashes: Mapping[str, Any],
    expected_policy: Mapping[str, Any],
    expected_scenario: Mapping[str, Any],
) -> dict[str, Any]:
    required = {
        "schema_version",
        "program_schema_version",
        "candidate_id",
        "scenario",
        "preregistration",
        "execution_lock",
        "baseline_result_identity",
        "policy",
        "policy_sha256",
        "scenario_config",
        "scenario_config_sha256",
        "candidate_batch_sha256",
        "candidate_signal_stream",
        "engine_candidate_binding",
        "complete_result",
        "complete_result_sha256",
    }
    if set(shard) != required:
        raise V18ReportContractError("scenario shard field set drifted")
    if shard.get("program_schema_version") != v18_program.PROGRAM_SCHEMA:
        raise V18ReportContractError("scenario shard program schema drifted")
    for field in ("preregistration", "execution_lock", "baseline_result_identity"):
        if shard.get(field) != manifest.get(field):
            raise V18ReportContractError(f"scenario shard {field} differs from manifest")
    policy = _mapping(shard.get("policy"), "shard policy")
    if policy != expected_policy:
        raise V18ReportContractError("scenario shard policy differs from frozen baseline")
    if shard.get("policy_sha256") != _payload_sha256(policy):
        raise V18ReportContractError("scenario shard policy hash mismatch")
    scenario_config = _mapping(shard.get("scenario_config"), "shard scenario config")
    if scenario_config != expected_scenario:
        raise V18ReportContractError("scenario shard cost scenario differs from frozen baseline")
    if shard.get("scenario_config_sha256") != _payload_sha256(scenario_config):
        raise V18ReportContractError("scenario config hash mismatch")
    try:
        baseline_report._exact_scenario(
            scenario_config,
            scenario,
            f"{candidate_id}.{scenario}.scenario_config",
        )
    except baseline_report.BaselineReportContractError as exc:
        raise V18ReportContractError(str(exc)) from exc
    stream = _validate_candidate_signal_stream(
        shard,
        candidate_id=candidate_id,
        manifest_input_hashes=manifest_input_hashes,
    )
    return {
        "policy_sha256": str(shard["policy_sha256"]),
        "scenario_config_sha256": str(shard["scenario_config_sha256"]),
        "signal_stream": stream,
    }


def _validate_complete_result(
    shard: Mapping[str, Any], *, candidate_id: str, scenario: str
) -> tuple[
    Mapping[str, Any],
    Any,
    dict[str, list[Mapping[str, Any]]],
    dict[str, Any],
]:
    complete = _mapping(shard.get("complete_result"), "complete_result")
    if shard.get("complete_result_sha256") != baseline_report._canonical_hash(complete):
        raise V18ReportContractError("complete_result_sha256 mismatch")
    binding = _mapping(shard.get("engine_candidate_binding"), "engine_candidate_binding")
    if binding.get("engine_validation_identity") != "v15p2_fair_baseline":
        raise V18ReportContractError("candidate binding source identity drifted")
    if binding.get("serialized_ledger_identity") != candidate_id:
        raise V18ReportContractError("candidate binding target identity drifted")
    if binding.get("binding_method") != "DETERMINISTIC_POST_ENGINE_CANDIDATE_ID_REBIND":
        raise V18ReportContractError("candidate binding algorithm drifted")
    reconstructed = copy.deepcopy(dict(complete))
    transformed = 0

    def reverse(value: Any) -> None:
        nonlocal transformed
        if isinstance(value, dict):
            for key, child in value.items():
                if key == "candidate_id":
                    if child != candidate_id:
                        raise V18ReportContractError(
                            "rebound result contains a foreign candidate_id leaf"
                        )
                    value[key] = "v15p2_fair_baseline"
                    transformed += 1
                else:
                    reverse(child)
        elif isinstance(value, list):
            for child in value:
                reverse(child)

    reverse(reconstructed)
    if binding.get("candidate_id_rebinding_count") != transformed:
        raise V18ReportContractError("candidate binding transformed count mismatch")
    if binding.get("raw_engine_result_sha256") != baseline_report._canonical_hash(reconstructed):
        raise V18ReportContractError("raw engine result SHA-256 does not reverse-reconcile")
    if complete.get("scenario") != scenario or complete.get("scenario_identity") != scenario:
        raise V18ReportContractError(f"{candidate_id}/{scenario} scenario identity drifted")
    if complete.get("scenario_is_canonical") is not True:
        raise V18ReportContractError(f"{candidate_id}/{scenario} is a custom scenario")
    try:
        baseline_report._exact_scenario(
            complete.get("scenario_config"),
            scenario,
            f"{candidate_id}.{scenario}.scenario_config",
        )
    except baseline_report.BaselineReportContractError as exc:
        raise V18ReportContractError(str(exc)) from exc
    if complete.get("policy") != shard.get("policy"):
        raise V18ReportContractError(f"{candidate_id}/{scenario} policy drifted")
    if _utc(complete.get("evaluation_start"), "evaluation_start") != EVALUATION_START:
        raise V18ReportContractError("evaluation_start drifted")
    if _utc(complete.get("evaluation_end"), "evaluation_end") != EVALUATION_END:
        raise V18ReportContractError("evaluation_end drifted")
    _finite(complete.get("initial_wallet"), "initial_wallet", positive=True)
    _finite(complete.get("final_nav"), "final_nav", positive=True)

    raw_ledgers: dict[str, list[Any]] = {}
    for key in baseline_report._RESULT_LISTS:
        raw_ledgers[key] = _list(complete.get(key), f"complete_result.{key}")
    try:
        curve = baseline_report._validate_curve(raw_ledgers["curve"], scenario)
        ledgers: dict[str, list[Mapping[str, Any]]] = {}
        ledgers["entries"] = baseline_report._validate_timestamped_ledger(
            raw_ledgers["entries"], name=f"{scenario}.entries", timestamp_key="entry_ts"
        )
        for key in ("exit_fills", "funding_events", "journal_rows", "breaker_transitions"):
            ledgers[key] = baseline_report._validate_timestamped_ledger(
                raw_ledgers[key], name=f"{scenario}.{key}", timestamp_key="ts"
            )
        for key in ("risk_decisions", "rejections"):
            ledgers[key] = baseline_report._validate_timestamped_ledger(
                raw_ledgers[key], name=f"{scenario}.{key}", timestamp_key="entry_ts"
            )
        ledgers["stop_transitions"] = baseline_report._validate_timestamped_ledger(
            raw_ledgers["stop_transitions"],
            name=f"{scenario}.stop_transitions",
            timestamp_key="calculated_ts",
        )
        ledgers["closed_episodes"] = baseline_report._validate_timestamped_ledger(
            raw_ledgers["closed_episodes"],
            name=f"{scenario}.closed_episodes",
            timestamp_key="exit_ts",
        )
        ledgers["terminal_positions"] = baseline_report._validate_timestamped_ledger(
            raw_ledgers["terminal_positions"],
            name=f"{scenario}.terminal_positions",
            timestamp_key="cutoff_ts",
        )
    except baseline_report.BaselineReportContractError as exc:
        raise V18ReportContractError(str(exc)) from exc

    candidate_ledgers = (
        "entries",
        "exit_fills",
        "funding_events",
        "journal_rows",
        "stop_transitions",
        "risk_decisions",
        "rejections",
        "closed_episodes",
        "terminal_positions",
    )
    for ledger_name in candidate_ledgers:
        for index, row in enumerate(ledgers[ledger_name]):
            if row.get("candidate_id") != candidate_id:
                raise V18ReportContractError(
                    f"{candidate_id}/{scenario}/{ledger_name}[{index}] candidate drifted"
                )
    for index, row in enumerate(ledgers["entries"]):
        decision = _utc(row.get("decision_ts"), f"entries[{index}].decision_ts")
        entry = _utc(row.get("entry_ts"), f"entries[{index}].entry_ts")
        if decision >= entry or decision < EVALUATION_START - BAR:
            raise V18ReportContractError("engine entry decision/entry timing drifted")
    for index, row in enumerate(ledgers["closed_episodes"]):
        entry = _utc(row.get("entry_ts"), f"closed[{index}].entry_ts")
        exit_ts = _utc(row.get("exit_ts"), f"closed[{index}].exit_ts")
        if not EVALUATION_START <= entry <= exit_ts < EVALUATION_END:
            raise V18ReportContractError("closed episode escapes the half-open replay")
    cutoff = curve.timestamps[-1]
    for index, row in enumerate(ledgers["terminal_positions"]):
        entry = _utc(row.get("entry_ts"), f"terminal[{index}].entry_ts")
        row_cutoff = _utc(row.get("cutoff_ts"), f"terminal[{index}].cutoff_ts")
        if not EVALUATION_START <= entry <= row_cutoff or row_cutoff != cutoff:
            raise V18ReportContractError("terminal position cutoff timing drifted")
    try:
        summary = baseline_report._scenario_report(complete, curve, ledgers)
    except baseline_report.BaselineReportContractError as exc:
        raise V18ReportContractError(str(exc)) from exc
    return complete, curve, ledgers, summary


def _pseudo_closed(
    ledgers: Mapping[str, list[Mapping[str, Any]]],
) -> list[Mapping[str, Any]]:
    return [
        row
        for row in ledgers["closed_episodes"]
        if DEVELOPMENT_END <= _utc(row.get("exit_ts"), "closed.exit_ts") < EVALUATION_END
    ]


def _pseudo_filled_turnover(
    curve: Any, ledgers: Mapping[str, list[Mapping[str, Any]]]
) -> dict[str, float | bool]:
    entry_notional = sum(
        _finite(row.get("entry_notional"), "entry_notional")
        for row in ledgers["entries"]
        if DEVELOPMENT_END <= _utc(row.get("entry_ts"), "entry_ts") < EVALUATION_END
    )
    exit_notional = sum(
        _finite(row.get("price"), "exit.price") * _finite(row.get("quantity"), "exit.quantity")
        for row in ledgers["exit_fills"]
        if DEVELOPMENT_END <= _utc(row.get("ts"), "exit.ts") < EVALUATION_END
    )
    selected_nav = [
        nav
        for timestamp, nav in zip(curve.timestamps, curve.navs, strict=True)
        if DEVELOPMENT_END <= timestamp < EVALUATION_END
    ]
    if not selected_nav:
        raise V18ReportContractError("pseudo-OOS curve contains no NAV observations")
    mean_nav = float(np.mean(np.asarray(selected_nav, dtype=float)))
    if not math.isfinite(mean_nav) or mean_nav <= 0.0:
        raise V18ReportContractError("pseudo-OOS arithmetic mean NAV is not positive")
    gross = entry_notional + exit_notional
    return {
        "filled_gross_notional": gross,
        "arithmetic_mean_15m_nav": mean_nav,
        "filled_gross_turnover_over_arithmetic_mean_15m_nav": gross / mean_nav,
        "terminal_accrual_excluded": True,
    }


def _compact_scenario_evidence(
    complete: Mapping[str, Any],
    curve: Any,
    ledgers: Mapping[str, list[Mapping[str, Any]]],
    summary: Mapping[str, Any],
    *,
    scenario: str,
) -> dict[str, Any]:
    compact: dict[str, Any] = {
        "initial_wallet": _finite(
            complete.get("initial_wallet"), f"{scenario}.initial_wallet", positive=True
        ),
        "summary": dict(summary),
        "pseudo_closed_episodes": _pseudo_closed(ledgers),
    }
    if scenario == "H":
        active_for_monthly_accounting = baseline_report._activity_months(curve, ledgers)
        compact["folds"] = baseline_report._fold_reports(
            curve,
            compact["initial_wallet"],
            active_for_monthly_accounting,
        )
        compact["turnover"] = _pseudo_filled_turnover(curve, ledgers)
        compact["active_exposure_months"] = sorted(
            {
                timestamp.strftime("%Y-%m")
                for timestamp, count in zip(curve.timestamps, curve.open_counts, strict=True)
                if DEVELOPMENT_END <= timestamp < EVALUATION_END and count > 0
            }
        )
    return compact


def _top_trade_removal(episodes: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    values = sorted(
        (_finite(row.get("net_pnl"), "closed.net_pnl") for row in episodes), reverse=True
    )
    if not values:
        return {
            "count": 0,
            "removed_count": 0,
            "net_after_top_5pct_removed": 0.0,
        }
    remove = max(1, math.ceil(len(values) * 0.05))
    return {
        "count": len(values),
        "removed_count": remove,
        "net_after_top_5pct_removed": float(sum(values[remove:])),
    }


def _json_safe_monthly_statistics(statistics: Mapping[str, Any]) -> dict[str, Any]:
    """Encode undefined positive-PnL shares as null while gates stay fail-closed.

    ``monthly_return_statistics`` deliberately returns ``+inf`` when total
    positive monthly PnL is zero.  That sentinel is useful for a comparison
    gate (it cannot pass a finite maximum), but strict JSON forbids it.  The
    report representation therefore uses ``None`` for only those two
    denominator-zero diagnostics; :func:`_gate` already treats ``None`` as a
    failed check.
    """

    normalized = dict(statistics)
    for key in ("best_month_positive_pnl_share", "best_3_month_positive_pnl_share"):
        value = normalized.get(key)
        if isinstance(value, int | float) and not math.isfinite(float(value)):
            normalized[key] = None
    return normalized


def _candidate_metrics(
    candidate_id: str,
    validated: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    b_evidence = _mapping(validated["B"], "B evidence")
    c2_evidence = _mapping(validated["C2"], "C2 evidence")
    h_evidence = _mapping(validated["H"], "H evidence")
    b_summary = _mapping(b_evidence["summary"], "B summary")
    c2_summary = _mapping(c2_evidence["summary"], "C2 summary")
    h_summary = _mapping(h_evidence["summary"], "H summary")
    h_pseudo = h_summary["windows"]["pseudo_oos"]
    h_development = h_summary["windows"]["development"]
    c2_pseudo = c2_summary["windows"]["pseudo_oos"]
    b_pseudo = b_summary["windows"]["pseudo_oos"]
    h_returns = [float(row["return_pct"]) for row in h_pseudo["monthly"]]
    h_pnl = [float(row["pnl"]) for row in h_pseudo["monthly"]]
    c2_returns = [float(row["return_pct"]) for row in c2_pseudo["monthly"]]
    h_statistics = _json_safe_monthly_statistics(
        monthly_return_statistics(h_returns, monthly_pnl=h_pnl)
    )
    c2_statistics = monthly_return_statistics(c2_returns)
    h_statistics["block_bootstrap_90pct_lower_bound_pct"] = block_bootstrap_lower_bound_pct(
        h_returns,
        block_months=3,
        iterations=20_000,
        confidence=0.90,
        seed=18,
        trim_fraction=0.10,
    )

    h_closed = _list(h_evidence["pseudo_closed_episodes"], "H closed episodes")
    c2_closed = _list(c2_evidence["pseudo_closed_episodes"], "C2 closed episodes")
    b_closed = _list(b_evidence["pseudo_closed_episodes"], "B closed episodes")
    gross_price_pnl = sum(
        _finite(row.get("gross_price_pnl"), "gross_price_pnl") for row in b_closed
    )
    execution_cost = sum(
        _finite(row.get("total_entry_execution_cost"), "entry_cost")
        + _finite(row.get("total_exit_execution_cost"), "exit_cost")
        for row in b_closed
    )
    edge_ratio = gross_price_pnl / execution_cost if execution_cost > 0.0 else None
    direction = {
        side: sum(
            _finite(row.get("net_pnl"), "net_pnl") for row in c2_closed if row.get("side") == side
        )
        for side in ("long", "short")
    }
    folds = _list(h_evidence["folds"], "H folds")
    dev_returns = [float(row["return_pct"]) for row in h_development["monthly"]]
    dev_trimmed = trimmed_mean_pct(dev_returns)
    oos_trimmed = float(h_statistics["trimmed_mean_monthly_pct"])
    dev_dd = float(h_development["drawdown_and_recovery"]["max_drawdown_pct"])
    oos_dd = float(h_pseudo["drawdown_and_recovery"]["max_drawdown_pct"])
    return {
        "candidate_id": candidate_id,
        "sample": {
            "closed_trades": len(h_closed),
            "long_trades": sum(row.get("side") == "long" for row in h_closed),
            "short_trades": sum(row.get("side") == "short" for row in h_closed),
            "active_months": len(_list(h_evidence["active_exposure_months"], "active months")),
            "terminal_positions_excluded": True,
        },
        "H": {
            **h_statistics,
            "monthly_returns_pct": h_returns,
            "monthly_pnl": h_pnl,
            "max_mtm_drawdown_pct": oos_dd,
            "fold_returns_pct": [float(row["continuous_return_pct"]) for row in folds],
            "positive_folds": sum(float(row["continuous_return_pct"]) > 0.0 for row in folds),
            "development_trimmed_mean_monthly_pct": dev_trimmed,
            "oos_to_development_trimmed_return_ratio": (
                oos_trimmed / dev_trimmed if dev_trimmed > 0.0 else None
            ),
            "development_max_mtm_drawdown_pct": dev_dd,
            "oos_to_development_drawdown_ratio": oos_dd / dev_dd if dev_dd > 0.0 else None,
            "turnover": dict(_mapping(h_evidence["turnover"], "H turnover")),
            "top_5pct_trade_removal": _top_trade_removal(h_closed),
        },
        "C2": {
            **c2_statistics,
            "monthly_returns_pct": c2_returns,
            "max_mtm_drawdown_pct": float(c2_pseudo["drawdown_and_recovery"]["max_drawdown_pct"]),
            "long_net_pnl": direction["long"],
            "short_net_pnl": direction["short"],
            "terminal_positions_excluded_from_direction": True,
        },
        "B": {
            "max_mtm_drawdown_pct": float(b_pseudo["drawdown_and_recovery"]["max_drawdown_pct"]),
            "pre_cost_gross_price_pnl": gross_price_pnl,
            "execution_cost": execution_cost,
            "pre_cost_price_pnl_over_execution_cost": edge_ratio,
            "funding_cashflow": sum(
                _finite(row.get("funding_cashflow"), "funding_cashflow") for row in b_closed
            ),
            "closed_episode_exit_timestamp_sample": True,
            "terminal_positions_excluded_from_edge": True,
            "result_initial_wallet": _finite(
                b_evidence.get("initial_wallet"), "B.initial_wallet", positive=True
            ),
        },
        "scenario_reports": {
            "B": b_summary,
            "C2": c2_summary,
            "H": h_summary,
        },
    }


def _gate(value: Any, threshold: float | int, comparison: str) -> dict[str, Any]:
    passed = False
    if value is not None and isinstance(value, int | float) and math.isfinite(float(value)):
        if comparison == "ge":
            passed = float(value) >= float(threshold)
        elif comparison == "gt":
            passed = float(value) > float(threshold)
        elif comparison == "le":
            passed = float(value) <= float(threshold)
        elif comparison == "eq":
            passed = float(value) == float(threshold)
        else:
            raise AssertionError(comparison)
    return {
        "value": value,
        "threshold": threshold,
        "comparison": comparison,
        "passed": passed,
    }


def _pre_loso_gates(metrics: Mapping[str, Any], prereg: Mapping[str, Any]) -> dict[str, Any]:
    gates = _mapping(prereg.get("hard_gates"), "hard_gates")
    sample = _mapping(metrics["sample"], "sample metrics")
    h = _mapping(metrics["H"], "H metrics")
    c2 = _mapping(metrics["C2"], "C2 metrics")
    b = _mapping(metrics["B"], "B metrics")
    h_return = _mapping(gates["H_return"], "H_return gates")
    h_stability = _mapping(gates["H_stability"], "H_stability gates")
    c2_return = _mapping(gates["C2_return"], "C2_return gates")
    sample_gate = _mapping(gates["sample"], "sample gates")
    drawdown = _mapping(gates["drawdown"], "drawdown gates")
    walk = _mapping(gates["walk_forward"], "walk gates")
    economic = _mapping(gates["economic_edge"], "economic gates")
    concentration = _mapping(gates["concentration"], "concentration gates")
    checks = {
        "sample.pseudo_oos_months": _gate(36, sample_gate["pseudo_oos_months"], "eq"),
        "sample.closed_trades": _gate(
            sample["closed_trades"], sample_gate["minimum_closed_trades"], "ge"
        ),
        "sample.long_trades": _gate(
            sample["long_trades"], sample_gate["minimum_long_trades"], "ge"
        ),
        "sample.short_trades": _gate(
            sample["short_trades"], sample_gate["minimum_short_trades"], "ge"
        ),
        "sample.active_months": _gate(
            sample["active_months"], sample_gate["minimum_active_months"], "ge"
        ),
        "H.trimmed_mean": _gate(
            h["trimmed_mean_monthly_pct"], h_return["trimmed_mean_monthly_pct_min"], "ge"
        ),
        "H.median": _gate(h["median_monthly_pct"], h_return["median_monthly_pct_min"], "ge"),
        "H.bootstrap_lcb": _gate(
            h["block_bootstrap_90pct_lower_bound_pct"],
            h_return["block_bootstrap_90pct_lower_bound_pct_min"],
            "ge",
        ),
        "H.negative_months": _gate(h["negative_months"], h_stability["negative_months_max"], "le"),
        "H.months_below_minus_1": _gate(
            h["months_below_minus_1pct"],
            h_stability["months_below_minus_1pct_max"],
            "le",
        ),
        "H.worst_month": _gate(h["worst_month_pct"], h_stability["worst_month_pct_min"], "ge"),
        "C2.trimmed_mean": _gate(
            c2["trimmed_mean_monthly_pct"],
            c2_return["trimmed_mean_monthly_pct_min"],
            "ge",
        ),
        "C2.median": _gate(c2["median_monthly_pct"], c2_return["median_monthly_pct_min"], "ge"),
        "B.max_drawdown": _gate(b["max_mtm_drawdown_pct"], drawdown["B_max_mtm_pct"], "le"),
        "stress.max_drawdown": _gate(
            max(c2["max_mtm_drawdown_pct"], h["max_mtm_drawdown_pct"]),
            drawdown["worse_of_C2_H_max_mtm_pct"],
            "le",
        ),
        "walk.positive_folds": _gate(h["positive_folds"], walk["positive_folds_min"], "ge"),
        "walk.total_folds": _gate(len(h["fold_returns_pct"]), walk["total_folds"], "eq"),
        "walk.worst_fold": _gate(
            min(h["fold_returns_pct"]), walk["worst_six_month_fold_pct_min"], "ge"
        ),
        "walk.return_ratio": _gate(
            h["oos_to_development_trimmed_return_ratio"],
            walk["H_oos_to_development_trimmed_return_ratio_min"],
            "ge",
        ),
        "walk.drawdown_ratio": _gate(
            h["oos_to_development_drawdown_ratio"],
            walk["H_oos_to_development_drawdown_ratio_max"],
            "le",
        ),
        "walk.denominators_positive": {
            "value": (
                h["oos_to_development_trimmed_return_ratio"] is not None
                and h["oos_to_development_drawdown_ratio"] is not None
            ),
            "threshold": True,
            "comparison": "is_true",
            "passed": (
                h["oos_to_development_trimmed_return_ratio"] is not None
                and h["oos_to_development_drawdown_ratio"] is not None
            ),
        },
        "economic.edge": _gate(
            b["pre_cost_price_pnl_over_execution_cost"],
            economic["B_pre_cost_price_pnl_over_execution_cost_min"],
            "ge",
        ),
        "economic.execution_cost_positive": {
            "value": b["execution_cost"] > 0.0,
            "threshold": True,
            "comparison": "is_true",
            "passed": b["execution_cost"] > 0.0,
        },
        "economic.funding_excluded_and_reported": {
            "value": b.get("funding_cashflow") is not None,
            "threshold": True,
            "comparison": "is_true",
            "passed": b.get("funding_cashflow") is not None,
        },
        "direction.long": _gate(c2["long_net_pnl"], 0.0, "gt"),
        "direction.short": _gate(c2["short_net_pnl"], 0.0, "gt"),
        "concentration.best_month": _gate(
            h["best_month_positive_pnl_share"],
            concentration["best_month_positive_pnl_share_max"],
            "le",
        ),
        "concentration.best_3_months": _gate(
            h["best_3_month_positive_pnl_share"],
            concentration["best_3_month_positive_pnl_share_max"],
            "le",
        ),
        "concentration.mean_without_best_3": _gate(
            h["mean_after_best_3_months_removed_pct"],
            concentration["mean_after_best_3_months_removed_pct_min"],
            "ge",
        ),
        "concentration.net_after_top_5pct": _gate(
            h["top_5pct_trade_removal"]["net_after_top_5pct_removed"], 0.0, "gt"
        ),
    }
    return {
        "checks": checks,
        "passed_before_multiple_testing_and_LOSO": all(row["passed"] for row in checks.values()),
    }


def _attach_multiple_testing(
    candidates: dict[str, Any],
    *,
    prereg: Mapping[str, Any],
    repo_root: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    local_returns = {
        candidate: pd.Series(
            candidates[candidate]["metrics"]["H"]["monthly_returns_pct"],
            index=v18_validation.FROZEN_H_MONTHS,
            dtype=float,
        )
        for candidate in CANDIDATE_ORDER
    }
    legacy = v18_validation.load_legacy_trial_inputs(prereg, repo_root=repo_root)
    result = v18_validation.v18_multiple_testing(local_returns, legacy)
    if (
        result.get("status") != "OK"
        or result.get("iterations") != 20_000
        or result.get("seed") != 18
        or result.get("block_months") != 3
    ):
        raise V18ReportContractError("V18 multiple-testing header drifted")
    local = _mapping(result["local_exact_36x4"], "local multiple testing")
    if (
        local.get("candidate_count") != 4
        or local.get("months") != 36
        or local.get("candidate_order") != list(CANDIDATE_ORDER)
    ):
        raise V18ReportContractError("local 36x4 multiple-testing contract drifted")
    local_results = _mapping(local["candidate_results"], "local candidate results")
    pbo = _mapping(local["pbo"], "local PBO")
    if pbo.get("status") != "OK" or pbo.get("combinations") != 20:
        raise V18ReportContractError("local CSCV/PBO contract drifted")
    cumulative = _mapping(result["cumulative_floor_exact_36x13"], "cumulative multiple testing")
    if (
        cumulative.get("candidate_count") != 13
        or cumulative.get("months") != 36
        or cumulative.get("candidate_order") != list(v18_validation.CUMULATIVE_CANDIDATE_IDS)
    ):
        raise V18ReportContractError("cumulative 36x13 multiple-testing contract drifted")
    pbo_value = _finite(pbo.get("probability_backtest_overfit"), "probability_backtest_overfit")
    thresholds = _mapping(
        _mapping(prereg["hard_gates"], "hard_gates")["multiple_testing"],
        "multiple-testing gates",
    )
    for candidate in CANDIDATE_ORDER:
        candidate_result = _mapping(local_results[candidate], f"{candidate} multiple testing")
        checks = candidates[candidate]["primary_gates"]["checks"]
        checks.update(
            {
                "multiple.local_holm": _gate(
                    candidate_result["local_holm_fwer_adjusted_p"],
                    thresholds["local_holm_fwer_adjusted_p_max"],
                    "le",
                ),
                "multiple.cumulative_holm": _gate(
                    candidate_result["cumulative_floor_holm_fwer_adjusted_p"],
                    thresholds["cumulative_floor_holm_fwer_adjusted_p_max"],
                    "le",
                ),
                "multiple.cumulative_dsr": _gate(
                    candidate_result["cumulative_floor_deflated_sharpe"],
                    thresholds["cumulative_floor_deflated_sharpe_min"],
                    "ge",
                ),
                "multiple.local_pbo": _gate(
                    pbo_value,
                    thresholds["local_probability_backtest_overfit_max"],
                    "le",
                ),
            }
        )
        candidates[candidate]["primary_gates"]["passed_before_multiple_testing_and_LOSO"] = all(
            row["passed"] for row in checks.values()
        )
        candidates[candidate]["multiple_testing"] = dict(candidate_result)
    provenance = {
        "legacy_artifacts": dict(legacy.artifact_provenance),
        "legacy_validation_sources": dict(legacy.source_provenance),
        "legacy_seed17_crosscheck": dict(legacy.seed17_crosscheck),
    }
    return result, provenance


def _rank_primary_passers(candidates: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for candidate in CANDIDATE_ORDER:
        item = candidates[candidate]
        if item["primary_gates"]["passed_before_multiple_testing_and_LOSO"] is not True:
            continue
        h = item["metrics"]["H"]
        rows.append(
            {
                "candidate_id": candidate,
                "H_trimmed_mean_monthly_pct": h["trimmed_mean_monthly_pct"],
                "H_rank_value_pct": min(float(h["trimmed_mean_monthly_pct"]), 15.0),
                "H_max_mtm_drawdown_pct": h["max_mtm_drawdown_pct"],
                "H_negative_months": h["negative_months"],
                "H_worst_month_pct": h["worst_month_pct"],
                "H_filled_gross_turnover": h["turnover"][
                    "filled_gross_turnover_over_arithmetic_mean_15m_nav"
                ],
            }
        )
    rows.sort(
        key=lambda row: (
            -float(row["H_rank_value_pct"]),
            float(row["H_max_mtm_drawdown_pct"]),
            int(row["H_negative_months"]),
            -float(row["H_worst_month_pct"]),
            float(row["H_filled_gross_turnover"]),
            str(row["candidate_id"]),
        )
    )
    for rank, row in enumerate(rows, start=1):
        row["rank"] = rank
    return rows


def deterministic_json(payload: Mapping[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, indent=2, allow_nan=False) + "\n"


def _write_atomic(path: Path, text: str) -> None:
    if path.exists() or path.is_symlink():
        raise FileExistsError(f"output already exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary = handle.name
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temporary, path)
        Path(temporary).unlink()
        temporary = None
    finally:
        if temporary is not None:
            Path(temporary).unlink(missing_ok=True)


def build_primary_report(
    manifest_path: Path,
    *,
    prereg: Mapping[str, Any],
    repo_root: Path | None = None,
) -> dict[str, Any]:
    """Verify all twelve shards and build the pre-LOSO primary report."""

    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise V18ReportContractError("manifest must be a non-symlink regular file")
    manifest = _load_json(manifest_path, name="V18 manifest")
    if manifest.get("schema_version") != MANIFEST_SCHEMA:
        raise V18ReportContractError("manifest schema drifted")
    if manifest.get("status") != "COMPLETE":
        raise V18ReportContractError("manifest is not a complete atomic bundle")
    if manifest.get("candidate_order") != list(CANDIDATE_ORDER):
        raise V18ReportContractError("manifest candidate order drifted")
    if manifest.get("scenario_order") != list(SCENARIO_ORDER):
        raise V18ReportContractError("manifest scenario order drifted")
    shard_specs = _list(manifest.get("shards"), "manifest.shards")
    expected_pairs = [
        (candidate, scenario) for candidate in CANDIDATE_ORDER for scenario in SCENARIO_ORDER
    ]
    actual_pairs = [(row.get("candidate_id"), row.get("scenario")) for row in shard_specs]
    if actual_pairs != expected_pairs:
        raise V18ReportContractError("manifest must contain exact ordered 4x3 shards")

    root = (repo_root or Path(__file__).resolve().parents[3]).resolve()
    governance = _validate_manifest_governance(manifest, prereg=prereg, repo_root=root)
    manifest_input_hashes = _mapping(governance["input_hashes"], "manifest input hashes")
    expected_policy = _mapping(governance["expected_policy"], "expected policy")
    expected_scenarios = _mapping(governance["expected_scenarios"], "expected scenarios")
    bundle_root = manifest_path.parent
    shard_provenance: list[dict[str, Any]] = []
    candidates: dict[str, Any] = {}
    for candidate_index, candidate_id in enumerate(CANDIDATE_ORDER):
        compact: dict[str, Mapping[str, Any]] = {}
        common_stream_sha: str | None = None
        common_policy_sha: str | None = None
        stream_summary: Mapping[str, Any] | None = None
        for scenario_index, scenario in enumerate(SCENARIO_ORDER):
            spec = shard_specs[candidate_index * len(SCENARIO_ORDER) + scenario_index]
            shard_path = _safe_bundle_child(bundle_root, spec.get("path"), name="shard path")
            _verify_file(
                shard_path,
                _mapping(spec, "shard spec"),
                name=f"{candidate_id}/{scenario}",
            )
            shard = _load_json(shard_path, name=f"{candidate_id}/{scenario} shard")
            if shard.get("schema_version") != SHARD_SCHEMA:
                raise V18ReportContractError("shard schema drifted")
            if shard.get("candidate_id") != candidate_id or shard.get("scenario") != scenario:
                raise V18ReportContractError("shard candidate/scenario identity drifted")
            if spec.get("payload_sha256") != _payload_sha256(shard):
                raise V18ReportContractError("shard payload SHA-256 mismatch")
            shard_governance = _validate_shard_governance(
                shard,
                manifest=manifest,
                candidate_id=candidate_id,
                scenario=scenario,
                manifest_input_hashes=manifest_input_hashes,
                expected_policy=expected_policy,
                expected_scenario=_mapping(expected_scenarios[scenario], scenario),
            )
            signal = _mapping(shard_governance["signal_stream"], "signal stream summary")
            if common_stream_sha is None:
                common_stream_sha = str(signal["stream_sha256"])
                stream_summary = signal
            elif common_stream_sha != signal["stream_sha256"]:
                raise V18ReportContractError("candidate signal stream differs across scenarios")
            if common_policy_sha is None:
                common_policy_sha = str(shard_governance["policy_sha256"])
            elif common_policy_sha != shard_governance["policy_sha256"]:
                raise V18ReportContractError("candidate policy differs across scenarios")
            complete, curve, ledgers, summary = _validate_complete_result(
                shard, candidate_id=candidate_id, scenario=scenario
            )
            _validate_entries_originate_from_proxies(
                ledgers["entries"],
                [
                    _mapping(row, "engine proxy intent")
                    for row in _list(signal["engine_proxy_intents"], "engine proxy intents")
                ],
            )
            compact[scenario] = _compact_scenario_evidence(
                complete,
                curve,
                ledgers,
                summary,
                scenario=scenario,
            )
            shard_provenance.append(
                {
                    "candidate_id": candidate_id,
                    "scenario": scenario,
                    "path": str(spec["path"]),
                    "bytes": int(spec["bytes"]),
                    "sha256": str(spec["sha256"]),
                    "payload_sha256": str(spec["payload_sha256"]),
                    "policy_sha256": str(shard_governance["policy_sha256"]),
                    "scenario_config_sha256": str(shard_governance["scenario_config_sha256"]),
                    "signal_stream_sha256": str(signal["stream_sha256"]),
                }
            )
            del shard, complete, curve, ledgers, summary
            gc.collect()
        metrics = _candidate_metrics(candidate_id, compact)
        primary_gates = _pre_loso_gates(metrics, prereg)
        candidates[candidate_id] = {
            "metrics": metrics,
            "primary_gates": primary_gates,
            "signal_stream": {
                key: value
                for key, value in _mapping(stream_summary, "stream summary").items()
                if key != "engine_proxy_intents"
            },
        }
    multiple_testing, legacy_provenance = _attach_multiple_testing(
        candidates,
        prereg=prereg,
        repo_root=root,
    )
    ranking = _rank_primary_passers(candidates)
    if ranking:
        verdict = "REQUIRES_TRUE_LOSO"
        locked_winner = ranking[0]["candidate_id"]
        remaining = [
            "TRUE_LOSO_NOT_YET_EVALUATED",
            "BASELINE_COMPARISON_NOT_YET_EVALUATED",
        ]
    else:
        verdict = "RED_NO_PRIMARY_CELL_PASSED"
        locked_winner = None
        remaining = []
    return {
        "schema_version": REPORT_SCHEMA,
        "deterministic": True,
        "evidence_eligible": True,
        "evidence_ineligible_reasons": [],
        "decision": {
            "verdict": verdict,
            "locked_winner": locked_winner,
            "remaining_required_evidence": remaining,
            "historical_feasibility_only": True,
            "paper_authorized": False,
            "live_deployment_authorized": False,
        },
        "candidate_order": list(CANDIDATE_ORDER),
        "scenario_order": list(SCENARIO_ORDER),
        "candidates": candidates,
        "multiple_testing": multiple_testing,
        "ranking": ranking,
        "limitations": list(prereg.get("limitations", [])),
        "prospective_evidence_gate": dict(
            _mapping(prereg.get("prospective_evidence_gate"), "prospective evidence gate")
        ),
        "provenance": {
            "manifest_path": str(manifest_path.resolve()),
            "manifest_bytes": manifest_path.stat().st_size,
            "manifest_sha256": _file_sha256(manifest_path),
            "shards": shard_provenance,
            "legacy_trial_inputs": legacy_provenance,
            "runner_governance": {
                "preregistration": governance["preregistration"],
                "execution_lock": governance["execution_lock"],
                "baseline_result_identity": governance["baseline_result_identity"],
                "runtime_git_commit": governance["runtime_git_commit"],
                "locked_source_commit": governance["locked_source_commit"],
                "input_hashes": dict(_mapping(governance["input_hashes"], "runner input hashes")),
                "source_preflight_equals_postflight_and_current": True,
                "runtime_preflight_equals_postflight_and_current": True,
                "lineage_verified_by_runner": True,
                "snapshots_verified_by_runner": True,
                "manifest_published_last": True,
            },
        },
    }


def _baseline_comparison_metrics(repo_root: Path) -> dict[str, float | int]:
    identity = _load_json(
        repo_root / CANONICAL_BASELINE_IDENTITY_RELATIVE,
        name="baseline result identity",
    )
    report_spec = _mapping(identity.get("report_artifact"), "baseline report artifact")
    path = repo_root / str(report_spec.get("path"))
    _verify_file(path, report_spec, name="baseline report artifact")
    payload = _load_json(path, name="baseline report")
    if (
        payload.get("schema_version") != "crypto-15m-v15p2-fair-baseline-report-v2"
        or payload.get("evidence_eligible") is not True
    ):
        raise V18ReportContractError("baseline report is not eligible V2 evidence")
    h_summary = _mapping(payload.get("H_summary"), "baseline H summary")
    scenarios = _mapping(payload.get("scenarios"), "baseline scenarios")
    h_pseudo = _mapping(
        _mapping(_mapping(scenarios["H"], "baseline H")["windows"], "baseline H windows")[
            "pseudo_oos"
        ],
        "baseline H pseudo-OOS",
    )
    return {
        "H_trimmed_mean_monthly_pct": _finite(
            h_summary.get("pseudo_oos_trimmed_10pct_symmetric_mean_monthly_return_pct"),
            "baseline H trimmed mean",
        ),
        "H_negative_months": int(h_summary.get("pseudo_oos_negative_month_count")),
        "H_worst_month_pct": _finite(
            h_summary.get("pseudo_oos_worst_month_pct"), "baseline H worst month"
        ),
        "H_max_mtm_drawdown_pct": _finite(
            _mapping(h_pseudo.get("drawdown_and_recovery"), "baseline drawdown").get(
                "max_drawdown_pct"
            ),
            "baseline H pseudo-OOS drawdown",
        ),
    }


def _reconcile_loso_input_hashes(
    manifest: Mapping[str, Any],
    *,
    primary: Mapping[str, Any],
    winner: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Bind the LOSO replay inputs to the independently published primary run."""

    primary_runner = _mapping(
        _mapping(primary.get("provenance"), "primary provenance").get("runner_governance"),
        "primary runner governance",
    )
    primary_input_hashes = _mapping(
        primary_runner.get("input_hashes"), "primary runner input hashes"
    )
    loso_input_hashes = _mapping(manifest.get("input_hashes"), "LOSO input hashes")
    expected_loso_hash_fields = {
        "engine_frames_sha256_by_symbol",
        "funding_events_sha256",
        "daily_returns_sha256",
        "baseline_decisions_sha256",
        "baseline_intents_sha256",
        "locked_winner_batch_sha256",
    }
    if set(loso_input_hashes) != expected_loso_hash_fields:
        raise V18ReportContractError("true-LOSO input-hash scope drifted")
    for field in (
        "engine_frames_sha256_by_symbol",
        "funding_events_sha256",
        "daily_returns_sha256",
        "baseline_decisions_sha256",
        "baseline_intents_sha256",
    ):
        if loso_input_hashes.get(field) != primary_input_hashes.get(field):
            raise V18ReportContractError(f"true-LOSO input hash {field} differs from primary")
    primary_candidate_hashes = _mapping(
        primary_input_hashes.get("candidate_batches_sha256"),
        "primary candidate-batch hashes",
    )
    if loso_input_hashes.get("locked_winner_batch_sha256") != primary_candidate_hashes.get(winner):
        raise V18ReportContractError("true-LOSO winner batch hash differs from primary")
    frame_hashes = _mapping(
        loso_input_hashes.get("engine_frames_sha256_by_symbol"), "LOSO frame hashes"
    )
    if tuple(frame_hashes) != tuple(v18_program.PRIMARY_SYMBOLS):
        raise V18ReportContractError("true-LOSO frame-hash universe/order drifted")
    scalar_hash_fields = (
        "funding_events_sha256",
        "daily_returns_sha256",
        "baseline_decisions_sha256",
        "baseline_intents_sha256",
        "locked_winner_batch_sha256",
    )
    if any(
        not isinstance(loso_input_hashes.get(field), str)
        or len(str(loso_input_hashes[field])) != 64
        for field in scalar_hash_fields
    ) or any(not isinstance(value, str) or len(value) != 64 for value in frame_hashes.values()):
        raise V18ReportContractError("true-LOSO input contains an invalid SHA-256 digest")
    return dict(loso_input_hashes), dict(primary_input_hashes)


def _validate_loso_manifest_governance(
    manifest: Mapping[str, Any],
    *,
    primary_report_path: Path,
    prereg: Mapping[str, Any],
    repo_root: Path,
) -> dict[str, Any]:
    if (
        manifest.get("schema_version") != LOSO_MANIFEST_SCHEMA
        or manifest.get("program_schema_version") != v18_program.PROGRAM_SCHEMA
        or manifest.get("status") != "COMPLETE"
        or manifest.get("phase") != "TRUE_LOSO"
        or manifest.get("evidence_eligible") is not True
        or manifest.get("runner_up_fallback_used") is not False
        or manifest.get("scenario") != "H"
        or manifest.get("excluded_symbol_order") != list(v18_program.PRIMARY_SYMBOLS)
        or manifest.get("manifest_published_last") is not True
        or manifest.get("historical_feasibility_only") is not True
        or manifest.get("live_or_paper_authorized") is not False
    ):
        raise V18ReportContractError("true-LOSO manifest header drifted")
    winner = str(manifest.get("locked_winner"))
    if winner not in CANDIDATE_ORDER:
        raise V18ReportContractError("true-LOSO winner identity drifted")

    prereg_identity = _manifest_identity(
        repo_root,
        CANONICAL_PREREG_RELATIVE,
        _mapping(manifest.get("preregistration"), "LOSO preregistration"),
        name="V18 preregistration",
    )
    lock_spec = _mapping(manifest.get("execution_lock"), "LOSO execution lock")
    lock_identity = _manifest_identity(
        repo_root,
        CANONICAL_LOCK_RELATIVE,
        lock_spec,
        name="V18 execution lock",
    )
    lock = v18_program._load_execution_lock(repo_root / CANONICAL_LOCK_RELATIVE)
    current_source = v18_program._source_provenance(lock, repo_root)
    try:
        v18_program._assert_source_ready(current_source)
    except RuntimeError as exc:
        raise V18ReportContractError(str(exc)) from exc
    current_runtime = v18_program.baseline._critical_runtime_versions(repo_root)
    if (
        manifest.get("source_preflight") != manifest.get("source_postflight")
        or manifest.get("source_postflight") != current_source
        or manifest.get("runtime_preflight") != manifest.get("runtime_postflight")
        or manifest.get("runtime_postflight") != current_runtime
    ):
        raise V18ReportContractError("true-LOSO source/runtime provenance drifted")

    report_spec = _mapping(manifest.get("primary_report"), "LOSO primary report")
    try:
        primary, primary_identity = v18_program._primary_report_evidence(
            primary_report_path,
            root=repo_root,
            prereg=prereg,
            expected_bytes=int(report_spec["bytes"]),
            expected_sha256=str(report_spec["sha256"]),
        )
    except (RuntimeError, ValueError) as exc:
        raise V18ReportContractError(str(exc)) from exc
    if primary_identity != report_spec:
        raise V18ReportContractError("true-LOSO primary report identity drifted")
    decision = _mapping(primary.get("decision"), "primary decision")
    if decision.get("locked_winner") != winner:
        raise V18ReportContractError("LOSO winner differs from primary report")

    loso_input_hashes, primary_input_hashes = _reconcile_loso_input_hashes(
        manifest,
        primary=primary,
        winner=winner,
    )

    baseline_spec = _mapping(manifest.get("baseline_result_identity"), "LOSO baseline identity")
    baseline_identity = _manifest_identity(
        repo_root,
        CANONICAL_BASELINE_IDENTITY_RELATIVE,
        baseline_spec,
        name="baseline result identity",
    )
    baseline_evidence = v18_program._baseline_identity_evidence(
        repo_root / CANONICAL_BASELINE_IDENTITY_RELATIVE,
        root=repo_root,
        prereg=prereg,
        expected_execution_git_commit=str(lock["execution_git_commit"]),
    )
    if manifest.get("baseline_evidence_artifacts") != baseline_evidence:
        raise V18ReportContractError("LOSO baseline evidence does not reconcile")
    if baseline_evidence.get("runtime_versions") != current_runtime:
        raise V18ReportContractError("true-LOSO runtime differs from sealed baseline runtime")
    _validate_frozen_identity_map(
        manifest.get("lineage"),
        v18_program._lineage_specs(prereg),
        name="LOSO lineage",
    )
    snapshots = _mapping(prereg.get("snapshots"), "snapshots")
    _validate_frozen_identity_map(
        manifest.get("snapshots"),
        {name: _mapping(snapshots[name], name) for name in ("market", "funding")},
        name="LOSO snapshots",
    )
    counts = _mapping(manifest.get("generation_counts"), "LOSO generation counts")
    if counts != {
        "market_snapshot_loads": 1,
        "funding_snapshot_loads": 1,
        "baseline_signal_generations": 1,
        "candidate_adapter_generations": 1,
        "independent_H_true_loso_replays": 13,
    }:
        raise V18ReportContractError("true-LOSO generation counts drifted")
    return {
        "winner": winner,
        "primary": primary,
        "primary_identity": primary_identity,
        "preregistration": prereg_identity,
        "execution_lock": lock_identity,
        "baseline_result_identity": baseline_identity,
        "input_hashes": dict(loso_input_hashes),
        "primary_input_hashes": dict(primary_input_hashes),
    }


def build_loso_report(
    loso_manifest_path: Path,
    *,
    primary_report_path: Path,
    prereg: Mapping[str, Any],
    repo_root: Path,
) -> dict[str, Any]:
    """Finalize the sole locked winner with thirteen true LOSO replays."""

    if loso_manifest_path.is_symlink() or not loso_manifest_path.is_file():
        raise V18ReportContractError("LOSO manifest must be a non-symlink regular file")
    manifest = _load_json(loso_manifest_path, name="true-LOSO manifest")
    governance = _validate_loso_manifest_governance(
        manifest,
        primary_report_path=primary_report_path,
        prereg=prereg,
        repo_root=repo_root,
    )
    winner = str(governance["winner"])
    primary = copy.deepcopy(dict(_mapping(governance["primary"], "primary report")))
    winner_primary = _mapping(
        _mapping(primary["candidates"], "primary candidates")[winner], "winner"
    )
    winner_metrics = _mapping(winner_primary["metrics"], "winner metrics")
    primary_signal_summary = _mapping(
        winner_primary.get("signal_stream"), "winner primary signal summary"
    )
    manifest_input_hashes = _mapping(governance["input_hashes"], "LOSO input hashes")
    full_h_pnl = _finite(
        _mapping(
            _mapping(
                _mapping(winner_metrics["scenario_reports"], "scenario reports")["H"],
                "winner H report",
            )["windows"],
            "winner H windows",
        )["pseudo_oos"]["continuous_pnl"],
        "winner H pseudo-OOS PnL",
    )

    specs = _list(manifest.get("shards"), "LOSO shards")
    if [row.get("excluded_symbol") for row in specs] != list(v18_program.PRIMARY_SYMBOLS):
        raise V18ReportContractError("LOSO shard order drifted")
    expected_policy = v18_program.baseline._jsonable(
        v18_program.baseline.build_policy(
            v18_program.baseline.load_preregistration(
                repo_root / v18_program.CANONICAL_BASELINE_PREREG_RELATIVE
            )
        )
    )
    expected_h = v18_program.baseline._jsonable(
        v18_program.baseline.build_scenarios(
            v18_program.baseline.load_preregistration(
                repo_root / v18_program.CANONICAL_BASELINE_PREREG_RELATIVE
            )
        )["H"]
    )
    bundle_root = loso_manifest_path.parent
    rows: list[dict[str, Any]] = []
    for spec in specs:
        if set(_mapping(spec, "LOSO shard spec")) != {
            "candidate_id",
            "scenario",
            "excluded_symbol",
            "path",
            "bytes",
            "sha256",
            "payload_sha256",
        }:
            raise V18ReportContractError("true-LOSO shard-spec field set drifted")
        excluded = str(spec["excluded_symbol"])
        if spec.get("candidate_id") != winner or spec.get("scenario") != "H":
            raise V18ReportContractError("true-LOSO shard-spec candidate/scenario drifted")
        path = _safe_bundle_child(bundle_root, spec.get("path"), name="LOSO shard path")
        _verify_file(path, _mapping(spec, "LOSO shard spec"), name=f"LOSO {excluded}")
        shard = _load_json(path, name=f"LOSO {excluded} shard")
        expected_shard_fields = {
            "schema_version",
            "program_schema_version",
            "phase",
            "candidate_id",
            "scenario",
            "excluded_symbol",
            "included_symbols",
            "continuous_replay_window",
            "candidate_batch_sha256",
            "preregistration",
            "execution_lock",
            "primary_report",
            "baseline_result_identity",
            "policy",
            "policy_sha256",
            "scenario_config",
            "scenario_config_sha256",
            "candidate_signal_stream",
            "loso_input_hashes",
            "engine_candidate_binding",
            "complete_result",
            "complete_result_sha256",
            "live_or_paper_authorized",
        }
        if (
            set(shard) != expected_shard_fields
            or shard.get("schema_version") != LOSO_SHARD_SCHEMA
            or shard.get("program_schema_version") != v18_program.PROGRAM_SCHEMA
            or shard.get("phase") != "TRUE_LOSO"
            or shard.get("candidate_id") != winner
            or shard.get("scenario") != "H"
            or shard.get("excluded_symbol") != excluded
            or shard.get("live_or_paper_authorized") is not False
            or spec.get("payload_sha256") != _payload_sha256(shard)
        ):
            raise V18ReportContractError("true-LOSO shard identity drifted")
        included = [symbol for symbol in v18_program.PRIMARY_SYMBOLS if symbol != excluded]
        if shard.get("included_symbols") != included:
            raise V18ReportContractError("true-LOSO included-symbol universe drifted")
        if shard.get("continuous_replay_window") != {
            "start_inclusive": EVALUATION_START.isoformat(),
            "end_exclusive": EVALUATION_END.isoformat(),
            "month_or_fold_restarts": 0,
        }:
            raise V18ReportContractError("true-LOSO continuous replay window drifted")
        for field in (
            "preregistration",
            "execution_lock",
            "primary_report",
            "baseline_result_identity",
        ):
            if shard.get(field) != manifest.get(field):
                raise V18ReportContractError(f"true-LOSO shard {field} differs from manifest")
        if shard.get("policy") != expected_policy or shard.get("policy_sha256") != _payload_sha256(
            expected_policy
        ):
            raise V18ReportContractError("true-LOSO policy drifted")
        if shard.get("scenario_config") != expected_h or shard.get(
            "scenario_config_sha256"
        ) != _payload_sha256(expected_h):
            raise V18ReportContractError("true-LOSO H scenario drifted")
        loso_inputs = _mapping(shard.get("loso_input_hashes"), "LOSO shard input hashes")
        if set(loso_inputs) != {
            "included_engine_frames_sha256_by_symbol",
            "funding_events_sha256",
            "daily_returns_sha256",
        }:
            raise V18ReportContractError("true-LOSO shard input-hash scope drifted")
        expected_frame_hashes = {
            symbol: _mapping(
                manifest_input_hashes["engine_frames_sha256_by_symbol"],
                "LOSO manifest frame hashes",
            )[symbol]
            for symbol in included
        }
        if loso_inputs.get("included_engine_frames_sha256_by_symbol") != expected_frame_hashes:
            raise V18ReportContractError("true-LOSO included frame hashes drifted")
        for field in ("funding_events_sha256", "daily_returns_sha256"):
            value = loso_inputs.get(field)
            if not isinstance(value, str) or len(value) != 64:
                raise V18ReportContractError(f"true-LOSO shard {field} is invalid")
        stream_evidence = _validate_loso_signal_stream(
            shard,
            candidate_id=winner,
            excluded_symbol=excluded,
            manifest_input_hashes=manifest_input_hashes,
            primary_signal_summary=primary_signal_summary,
        )
        proxies = [
            _mapping(row, "LOSO engine proxy")
            for row in _list(stream_evidence["engine_proxy_intents"], "LOSO proxies")
        ]
        complete, curve, ledgers, summary = _validate_complete_result(
            shard, candidate_id=winner, scenario="H"
        )
        _validate_entries_originate_from_proxies(ledgers["entries"], proxies)
        for ledger_name in (
            "entries",
            "exit_fills",
            "funding_events",
            "journal_rows",
            "stop_transitions",
            "risk_decisions",
            "rejections",
            "closed_episodes",
            "terminal_positions",
        ):
            if any(row.get("symbol") == excluded for row in ledgers[ledger_name]):
                raise V18ReportContractError("true-LOSO result contains excluded symbol")
        compact = _compact_scenario_evidence(
            complete,
            curve,
            ledgers,
            summary,
            scenario="H",
        )
        pseudo_pnl = _finite(
            _mapping(_mapping(compact["summary"], "LOSO summary")["windows"], "LOSO windows")[
                "pseudo_oos"
            ]["continuous_pnl"],
            "LOSO pseudo-OOS PnL",
        )
        rows.append(
            {
                "excluded_symbol": excluded,
                "pseudo_oos_continuous_pnl": pseudo_pnl,
                "positive": pseudo_pnl > 0.0,
                "marginal_pnl": full_h_pnl - pseudo_pnl,
                "shard": {
                    "path": str(spec["path"]),
                    "bytes": int(spec["bytes"]),
                    "sha256": str(spec["sha256"]),
                    "payload_sha256": str(spec["payload_sha256"]),
                },
            }
        )
        del shard, complete, curve, ledgers, summary, compact
        gc.collect()

    positive_marginals = [max(0.0, float(row["marginal_pnl"])) for row in rows]
    marginal_total = sum(positive_marginals)
    effective_n = (
        1.0 / sum((value / marginal_total) ** 2 for value in positive_marginals)
        if marginal_total > 0.0
        else 0.0
    )
    concentration_gates = _mapping(
        _mapping(prereg["hard_gates"], "hard gates")["concentration"],
        "concentration gates",
    )
    loso_passed = all(row["positive"] for row in rows) and effective_n >= float(
        concentration_gates["effective_symbol_count_min"]
    )

    baseline = _baseline_comparison_metrics(repo_root)
    h = _mapping(winner_metrics["H"], "winner H metrics")
    challenger_trim = _finite(h["trimmed_mean_monthly_pct"], "challenger trim")
    challenger_dd = _finite(h["max_mtm_drawdown_pct"], "challenger drawdown")
    rule_1 = (
        challenger_trim >= max(10.0, float(baseline["H_trimmed_mean_monthly_pct"]) + 1.5)
        and challenger_dd <= float(baseline["H_max_mtm_drawdown_pct"]) + 1.0
    )
    baseline_dd = float(baseline["H_max_mtm_drawdown_pct"])
    rule_2 = (
        challenger_trim >= float(baseline["H_trimmed_mean_monthly_pct"]) - 1.0
        and baseline_dd > 0.0
        and challenger_dd <= baseline_dd * 0.75
    )
    stability = int(h["negative_months"]) <= int(baseline["H_negative_months"]) and float(
        h["worst_month_pct"]
    ) >= float(baseline["H_worst_month_pct"])
    better_than_baseline = loso_passed and (rule_1 or rule_2) and stability
    if not loso_passed:
        verdict = "RED_TRUE_LOSO_FAILED"
    elif not better_than_baseline:
        verdict = "RED_NOT_BETTER_THAN_FAIR_BASELINE"
    else:
        verdict = "HISTORICAL_FEASIBILITY_PASS_REQUIRES_PROSPECTIVE_EVIDENCE"
    primary["schema_version"] = "crypto-15m-v18-final-report-v1"
    primary["decision"] = {
        "verdict": verdict,
        "locked_winner": winner,
        "historical_feasibility_only": True,
        "prospective_evidence_required": better_than_baseline,
        "paper_authorized": False,
        "live_deployment_authorized": False,
    }
    primary["true_loso"] = {
        "rows": rows,
        "all_replays_positive": all(row["positive"] for row in rows),
        "effective_symbol_count": effective_n,
        "minimum_effective_symbol_count": concentration_gates["effective_symbol_count_min"],
        "passed": loso_passed,
    }
    primary["fair_baseline_comparison"] = {
        "baseline": baseline,
        "rule_1_passed": rule_1,
        "rule_2_passed": rule_2,
        "stability_noninferiority_passed": stability,
        "passed": better_than_baseline,
    }
    primary["provenance"]["true_loso_manifest"] = {
        "path": str(loso_manifest_path.resolve()),
        "bytes": loso_manifest_path.stat().st_size,
        "sha256": _file_sha256(loso_manifest_path),
    }
    _canonical_json(primary)
    return primary


def render_markdown(report: Mapping[str, Any]) -> str:
    decision = _mapping(report.get("decision"), "decision")
    candidates = _mapping(report.get("candidates"), "candidates")
    lines = [
        "# Crypto 15m V18 challenger sonucu",
        "",
        f"Karar: **{decision.get('verdict')}**.",
        "Bu yalnız tarihsel feasibility kanıtıdır; paper veya canlı işlem yetkisi vermez.",
        "",
        "## Aday özeti",
        "",
        "| Aday | H trimli aylık % | H medyan % | H DD % | H negatif ay | H trade | Ön-LOSO geçiş |",
        "|---|---:|---:|---:|---:|---:|---|",
    ]
    for candidate in CANDIDATE_ORDER:
        item = _mapping(candidates[candidate], candidate)
        metrics = _mapping(item["metrics"], f"{candidate}.metrics")
        h = _mapping(metrics["H"], f"{candidate}.H")
        sample = _mapping(metrics["sample"], f"{candidate}.sample")
        gates = _mapping(item["primary_gates"], f"{candidate}.gates")
        lines.append(
            "| {candidate} | {trim:.4f} | {median:.4f} | {dd:.4f} | {negative} | "
            "{trades} | {passed} |".format(
                candidate=candidate,
                trim=float(h["trimmed_mean_monthly_pct"]),
                median=float(h["median_monthly_pct"]),
                dd=float(h["max_mtm_drawdown_pct"]),
                negative=int(h["negative_months"]),
                trades=int(sample["closed_trades"]),
                passed=(
                    "EVET" if gates["passed_before_multiple_testing_and_LOSO"] is True else "HAYIR"
                ),
            )
        )
    if "true_loso" in report:
        loso = _mapping(report.get("true_loso"), "true_loso")
        rows = _list(loso.get("rows"), "true_loso.rows")
        lines.extend(
            [
                "",
                "## True LOSO",
                "",
                "| Dışarıda bırakılan sembol | H pseudo-OOS PnL | Pozitif | Marjinal PnL |",
                "|---|---:|:---:|---:|",
            ]
        )
        for raw_row in rows:
            row = _mapping(raw_row, "true_loso row")
            lines.append(
                "| {symbol} | {pnl:.4f} | {positive} | {marginal:.4f} |".format(
                    symbol=row.get("excluded_symbol"),
                    pnl=float(row.get("pseudo_oos_continuous_pnl")),
                    positive="EVET" if row.get("positive") is True else "HAYIR",
                    marginal=float(row.get("marginal_pnl")),
                )
            )
        lines.extend(
            [
                "",
                "- Etkin sembol sayısı: "
                f"`{float(loso.get('effective_symbol_count')):.4f}` "
                f"(minimum `{float(loso.get('minimum_effective_symbol_count')):.4f}`).",
                f"- True-LOSO kapısı: `{'PASS' if loso.get('passed') is True else 'RED'}`.",
            ]
        )
    if "fair_baseline_comparison" in report:
        comparison = _mapping(report.get("fair_baseline_comparison"), "fair_baseline_comparison")
        baseline = _mapping(comparison.get("baseline"), "fair baseline metrics")
        lines.extend(
            [
                "",
                "## Adil baseline karşılaştırması",
                "",
                "- Baseline H trimli aylık getiri: "
                f"`{float(baseline.get('H_trimmed_mean_monthly_pct')):.4f}%`.",
                "- Baseline H pseudo-OOS MTM DD: "
                f"`{float(baseline.get('H_max_mtm_drawdown_pct')):.4f}%`.",
                "- Baseline H negatif ay / en kötü ay: "
                f"`{int(baseline.get('H_negative_months'))}` / "
                f"`{float(baseline.get('H_worst_month_pct')):.4f}%`.",
                f"- Kural 1: `{'PASS' if comparison.get('rule_1_passed') is True else 'RED'}`; "
                f"Kural 2: `{'PASS' if comparison.get('rule_2_passed') is True else 'RED'}`; "
                "istikrar non-inferiority: "
                f"`{'PASS' if comparison.get('stability_noninferiority_passed') is True else 'RED'}`.",
                "- Baseline'dan daha iyi kapısı: "
                f"`{'PASS' if comparison.get('passed') is True else 'RED'}`.",
            ]
        )
    lines.extend(
        [
            "",
            "## Yönetişim",
            "",
            "- Dört aday ve bütün eşikler baseline sonucu görülmeden kilitlendi.",
            "- Yerel test 36×4, program-floor test 36×13 ve seed 18 ile çalıştı.",
            "- Market/funding, kaynak, prereg, execution-lock ve baseline kimlikleri pre/post bağlıdır.",
            "- Historical sonuç doğrudan deployment veya promotion kanıtı değildir.",
            "- Ayrı prospective kapı: en az 90 gün ve 100 kapanmış trade; hangisi geç tamamlanırsa.",
            "",
        ]
    )
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", choices=("primary", "loso"), default="primary")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--prereg", type=Path, required=True)
    parser.add_argument("--primary-report", type=Path)
    parser.add_argument("--json-output", type=Path, required=True)
    parser.add_argument("--markdown-output", type=Path, required=True)
    args = parser.parse_args(argv)
    root = args.prereg.resolve().parent.parent
    try:
        prereg = v18_program.load_preregistration(args.prereg.resolve())
    except (OSError, ValueError) as exc:
        raise V18ReportContractError(str(exc)) from exc
    canonical_paths: dict[str, Path] = {
        "preregistration": (root / CANONICAL_PREREG_RELATIVE).resolve()
    }
    actual_paths = {
        "preregistration": args.prereg.resolve(),
        "manifest": args.manifest.resolve(),
        "JSON output": args.json_output.resolve(),
        "Markdown output": args.markdown_output.resolve(),
    }
    if args.phase == "primary":
        if args.primary_report is not None:
            parser.error("--primary-report is valid only for LOSO phase")
        canonical_paths.update(
            {
                "manifest": (root / CANONICAL_PRIMARY_MANIFEST_RELATIVE).resolve(),
                "JSON output": (root / CANONICAL_PRIMARY_REPORT_JSON_RELATIVE).resolve(),
                "Markdown output": (root / CANONICAL_PRIMARY_REPORT_MARKDOWN_RELATIVE).resolve(),
            }
        )
    else:
        if args.primary_report is None:
            parser.error("LOSO phase requires --primary-report")
        canonical_paths.update(
            {
                "manifest": (root / CANONICAL_LOSO_MANIFEST_RELATIVE).resolve(),
                "primary report": (root / CANONICAL_PRIMARY_REPORT_JSON_RELATIVE).resolve(),
                "JSON output": (root / CANONICAL_FINAL_REPORT_JSON_RELATIVE).resolve(),
                "Markdown output": (root / CANONICAL_FINAL_REPORT_MARKDOWN_RELATIVE).resolve(),
            }
        )
        actual_paths["primary report"] = args.primary_report.resolve()
    for name, expected in canonical_paths.items():
        if actual_paths[name] != expected:
            raise V18ReportContractError(f"{name} must use canonical path {expected}")
    if args.phase == "primary":
        result = build_primary_report(
            args.manifest,
            prereg=prereg,
            repo_root=root,
        )
    else:
        assert args.primary_report is not None
        result = build_loso_report(
            args.manifest,
            primary_report_path=args.primary_report,
            prereg=prereg,
            repo_root=root,
        )
    _write_atomic(args.json_output, deterministic_json(result))
    _write_atomic(args.markdown_output, render_markdown(result))
    return 0


__all__ = [
    "BASELINE_IDENTITY_SCHEMA",
    "CANDIDATE_ORDER",
    "CANONICAL_FINAL_REPORT_JSON_RELATIVE",
    "CANONICAL_FINAL_REPORT_MARKDOWN_RELATIVE",
    "CANONICAL_LOSO_MANIFEST_RELATIVE",
    "CANONICAL_PRIMARY_MANIFEST_RELATIVE",
    "CANONICAL_PRIMARY_REPORT_JSON_RELATIVE",
    "CANONICAL_PRIMARY_REPORT_MARKDOWN_RELATIVE",
    "LOCK_SCHEMA",
    "LOSO_MANIFEST_SCHEMA",
    "LOSO_SHARD_SCHEMA",
    "MANIFEST_SCHEMA",
    "REPORT_SCHEMA",
    "SHARD_SCHEMA",
    "V18ReportContractError",
    "build_loso_report",
    "build_primary_report",
    "deterministic_json",
    "main",
    "render_markdown",
]


if __name__ == "__main__":
    raise SystemExit(main())
