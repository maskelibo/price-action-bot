"""Governed V18 challenger replay with scenario shards and manifest-last publish.

Dry-plan validates only the preregistration and never resolves, stats, hashes,
or opens either configured snapshot.  Execute mode additionally requires a
separately committed execution lock and a sealed eligible V15.2 baseline
identity.  It loads each immutable snapshot once, generates the inherited
V15.2 signal stream once, adapts the four preregistered cells once, and runs
the twelve independent cell/scenario paths in canonical order.

Each completed path is atomically published as a strict-JSON shard.  The
bundle manifest is published only after all input, source, runtime, lineage,
and snapshot postflight checks pass; therefore a directory without a manifest
is unambiguously incomplete and ineligible evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

os.environ["PA_LOG_QUIET"] = "1"
os.environ["PA_DISABLE_FILE_LOG"] = "1"
os.environ["PA_TESTING"] = "1"

from price_action.lab import crypto_15m_v15p2_program as baseline
from price_action.lab.crypto_15m_snapshot_io import (
    SnapshotVerification,
    load_funding_snapshot,
    load_market_snapshot,
    sha256_file,
    verify_frozen_snapshot,
)
from price_action.lab.crypto_15m_v15p2_engine import run_v15p2_engine
from price_action.lab.crypto_15m_v15p2_signals import (
    EXPECTED_CONFIG_SHA256,
    FAIR_BASELINE_CANDIDATE_ID,
    generate_v15p2_signal_batch,
)

PROGRAM_SCHEMA = "crypto-15m-v18-primary-run-v1"
SHARD_SCHEMA = "crypto-15m-v18-scenario-shard-v1"
MANIFEST_SCHEMA = "crypto-15m-v18-primary-bundle-manifest-v1"
LOSO_SHARD_SCHEMA = "crypto-15m-v18-true-loso-shard-v1"
LOSO_MANIFEST_SCHEMA = "crypto-15m-v18-true-loso-bundle-manifest-v1"
LOCK_SCHEMA = "crypto-15m-v18-execution-lock-v1"
PREREG_SCHEMA = "crypto-15m-v18-challenger-prereg-v1"
CANONICAL_PREREG_RELATIVE = "configs/crypto_15m_v18_challenger_prereg.yaml"
CANONICAL_LOCK_RELATIVE = "configs/crypto_15m_v18_execution_lock.json"
CANONICAL_BASELINE_IDENTITY_RELATIVE = (
    "configs/crypto_15m_v15p2_fair_baseline_v2_result_identity.json"
)
CANONICAL_BASELINE_PREREG_RELATIVE = "configs/crypto_15m_v15p2_fair_baseline_v2_prereg.yaml"
CANONICAL_BASELINE_RAW_RELATIVE = "reports/research/crypto_15m_v15p2_fair_baseline_v2_raw.json"
CANONICAL_BASELINE_REPORT_RELATIVE = (
    "reports/research/crypto_15m_v15p2_fair_baseline_v2_report.json"
)
CANONICAL_PRIMARY_REPORT_RELATIVE = "reports/research/crypto_15m_v18_primary_report.json"
CANONICAL_PRIMARY_BUNDLE_RELATIVE = "reports/research/crypto_15m_v18_primary_bundle"
CANONICAL_LOSO_BUNDLE_RELATIVE = "reports/research/crypto_15m_v18_loso_bundle"
CANONICAL_CONFIG_RELATIVE = "configs/risk_phoenix_scalp_15m_v15p2.yaml"

CELL_ORDER = (
    "C1_VSA_ONLY",
    "C2_GRIMES_ONLY",
    "C3_DUAL_HTF50",
    "C4_VSA_HTF50",
)
SCENARIO_ORDER = ("B", "C2", "H")
PRIMARY_SYMBOLS = baseline.PRIMARY_SYMBOLS
REFERENCE_SYMBOL = baseline.REFERENCE_SYMBOL
HISTORY_START = baseline.HISTORY_START
EVALUATION_START = baseline.EVALUATION_START
EVALUATION_END = baseline.EVALUATION_END
_BAR = pd.Timedelta(minutes=15)
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_COMMIT = re.compile(r"^[0-9a-f]{40}$")

_EXPECTED_CELL_CONTRACT = (
    ("C1_VSA_ONLY", ("vsa_climax_test",), ("grimes_abc_pullback",), False),
    ("C2_GRIMES_ONLY", ("grimes_abc_pullback",), ("vsa_climax_test",), False),
    (
        "C3_DUAL_HTF50",
        ("vsa_climax_test", "grimes_abc_pullback"),
        (),
        True,
    ),
    ("C4_VSA_HTF50", ("vsa_climax_test",), ("grimes_abc_pullback",), True),
)
_EXPECTED_SCENARIOS = {
    "B": (1.0, 1.0, 1.0, 1.0),
    "C2": (2.0, 2.0, 1.0, 1.0),
    "H": (1.0, 1.0, 0.5, 1.25),
}
_REQUIRED_LOCKED_SOURCE_FILES = {
    CANONICAL_PREREG_RELATIVE,
    CANONICAL_BASELINE_PREREG_RELATIVE,
    CANONICAL_CONFIG_RELATIVE,
    "requirements-lock.txt",
    "src/price_action/__init__.py",
    "src/price_action/contracts.py",
    "src/price_action/logging_config.py",
    "src/price_action/runtime_paths.py",
    "src/price_action/settings.py",
    "src/price_action/lab/__init__.py",
    "src/price_action/lab/crypto_15m_snapshot_io.py",
    "src/price_action/lab/crypto_15m_v15p2_engine.py",
    "src/price_action/lab/crypto_15m_v15p2_program.py",
    "src/price_action/lab/crypto_15m_v15p2_report.py",
    "src/price_action/lab/crypto_15m_v15p2_signals.py",
    "src/price_action/lab/crypto_15m_validation.py",
    "src/price_action/lab/crypto_15m_pairs_validation.py",
    "src/price_action/lab/crypto_15m_v18_program.py",
    "src/price_action/lab/crypto_15m_v18_report.py",
    "src/price_action/lab/crypto_15m_v18_signals.py",
    "src/price_action/lab/crypto_15m_v18_validation.py",
    "src/price_action/strategies/base.py",
    "src/price_action/strategies/classic_pa.py",
    "src/price_action/strategies/grimes_abc_pullback.py",
    "src/price_action/strategies/__init__.py",
    "src/price_action/strategies/vsa_climax_test.py",
}

# These are result-affecting report semantics.  The execution lock must repeat
# the mapping exactly before the raw replay is allowed to open a snapshot.
LOCKED_METRIC_SEMANTICS: Mapping[str, Mapping[str, Any]] = {
    "loso": {
        "window": "pseudo_oos",
        "pnl": "strict_prestart_nav_delta",
        "terminal_accrual_included": True,
    },
    "best_3_months": {
        "rank": "H_monthly_return_descending",
        "statistic": "arithmetic_mean_remaining_33_months",
    },
    "B_economic_edge": {
        "sample": "closed_episodes_exit_ts_in_pseudo_oos_terminal_excluded",
        "numerator": "gross_price_pnl",
        "denominator": "entry_plus_exit_execution_cost",
    },
    "C2_direction": {
        "sample": "closed_episodes_exit_ts_in_pseudo_oos_terminal_excluded",
        "split": "long_short_net_pnl",
    },
    "H_turnover": {
        "window": "pseudo_oos",
        "numerator": "entry_plus_exit_filled_notional",
        "denominator": "arithmetic_mean_15m_nav",
        "terminal_accrual_excluded": True,
    },
}


@dataclass(frozen=True, slots=True)
class _CellIntentProxy:
    """Immutable engine-compatible intent carrying an explicit cell binding."""

    candidate_id: str
    cell_id: str
    source_candidate_id: str
    source_intent_sha256: str
    decision_ts: Any
    entry_ts: Any
    symbol: str
    side: str
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


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be a mapping")
    return value


def _strict_digest(value: Any, label: str) -> str:
    digest = str(value)
    if _SHA256.fullmatch(digest) is None:
        raise ValueError(f"{label} must be a lowercase SHA-256 digest")
    return digest


def _read_yaml(path: Path) -> dict[str, Any]:
    try:
        value = yaml.load(path.read_bytes(), Loader=baseline._UniqueKeyLoader)
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise ValueError(f"preregistration is not valid unique-key YAML: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError("preregistration root must be a mapping")
    return value


def _unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key!r}")
        result[key] = value
    return result


def _read_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_bytes(), object_pairs_hook=_unique_json_object)
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise ValueError(f"{label} is not valid unique-key JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} root must be an object")
    return value


def load_preregistration(path: Path) -> dict[str, Any]:
    """Load and fail closed on every runner-critical V18 design field."""

    prereg = _read_yaml(path)
    if prereg.get("schema_version") != PREREG_SCHEMA:
        raise ValueError("unexpected V18 preregistration schema")
    if prereg.get("status") != "PREREGISTERED_DESIGN_ONLY_NO_ENGINE_NO_RESULTS_SEEN":
        raise ValueError("V18 preregistration status drifted")
    if prereg.get("baseline_result_seen_before_candidate_lock") is not False:
        raise ValueError("candidate lock is not result-blind")
    if prereg.get("performance_execution_authorized_by_this_artifact") is not False:
        raise ValueError("design artifact must not self-authorize execution")
    cells = prereg.get("candidate_cells")
    if not isinstance(cells, list):
        raise ValueError("candidate_cells must be a list")
    actual_cells = tuple(
        (
            str(_mapping(item, "candidate cell").get("id")),
            tuple(_mapping(item, "candidate cell").get("enabled_strategies", ())),
            tuple(_mapping(item, "candidate cell").get("disabled_strategies", ())),
            _mapping(item, "candidate cell").get("htf50_gate"),
        )
        for item in cells
    )
    if actual_cells != _EXPECTED_CELL_CONTRACT:
        raise ValueError("canonical V18 candidate cell contract drifted")
    scenarios = _mapping(
        _mapping(prereg.get("cost_and_payoff_scenarios"), "cost contract").get("scenarios"),
        "scenarios",
    )
    if tuple(scenarios) != SCENARIO_ORDER:
        raise ValueError("canonical V18 scenario order drifted")
    for name, expected in _EXPECTED_SCENARIOS.items():
        item = _mapping(scenarios[name], f"scenario {name}")
        actual = tuple(
            float(item[key])
            for key in (
                "execution_cost_multiplier",
                "funding_multiplier",
                "positive_price_pnl_multiplier",
                "negative_price_pnl_multiplier",
            )
        )
        if actual != expected:
            raise ValueError(f"scenario {name} components drifted")
    time_protocol = _mapping(prereg.get("time_protocol"), "time_protocol")
    if time_protocol.get("complete_months_utc") != [
        "2021-06-01T00:00:00Z",
        "2026-06-01T00:00:00Z",
    ]:
        raise ValueError("evaluation window drifted")
    governance = _mapping(
        prereg.get("implementation_and_execution_governance"), "execution governance"
    )
    if governance.get("canonical_prereg_path") != CANONICAL_PREREG_RELATIVE:
        raise ValueError("canonical preregistration path drifted")
    if (
        governance.get(
            "implementation_must_be_completed_and_tested_before_any_snapshot_performance_open"
        )
        is not True
    ):
        raise ValueError("implementation-before-data gate drifted")
    snapshots = _mapping(prereg.get("snapshots"), "snapshots")
    for name in ("market", "funding"):
        spec = _mapping(snapshots.get(name), f"{name} snapshot")
        if not str(spec.get("path", "")) or int(spec.get("bytes", 0)) <= 0:
            raise ValueError(f"{name} snapshot identity is incomplete")
        _strict_digest(spec.get("sha256"), f"{name} snapshot sha256")
    return prereg


def _load_execution_lock(path: Path) -> dict[str, Any]:
    lock = _read_json(path, "execution lock")
    if lock.get("schema_version") != LOCK_SCHEMA:
        raise ValueError("unexpected V18 execution-lock schema")
    if lock.get("status") != "LOCKED_FOR_HISTORICAL_REPLAY_NO_RESULTS_SEEN":
        raise ValueError("execution lock status is not executable")
    if lock.get("performance_result_seen_before_lock") is not False:
        raise ValueError("execution lock was not result-blind")
    if lock.get("historical_replay_authorized") is not True:
        raise ValueError("historical replay is not authorized by the lock")
    if lock.get("live_or_paper_authorized") is not False:
        raise ValueError("execution lock must forbid live and paper deployment")
    commit = str(lock.get("execution_git_commit", ""))
    if _COMMIT.fullmatch(commit) is None:
        raise ValueError("execution_git_commit must be a full lowercase commit")
    prereg = _mapping(lock.get("preregistration"), "locked preregistration")
    if prereg.get("path") != CANONICAL_PREREG_RELATIVE or int(prereg.get("bytes", 0)) <= 0:
        raise ValueError("execution lock does not bind the canonical preregistration")
    _strict_digest(prereg.get("sha256"), "locked preregistration sha256")
    sources = _mapping(lock.get("source_files"), "locked source_files")
    if not _REQUIRED_LOCKED_SOURCE_FILES.issubset(sources):
        missing = sorted(_REQUIRED_LOCKED_SOURCE_FILES.difference(sources))
        raise ValueError(f"execution lock omits required source files: {missing}")
    for relative, raw_identity in sources.items():
        identity = _mapping(raw_identity, f"source identity {relative}")
        if Path(str(relative)).is_absolute() or ".." in Path(str(relative)).parts:
            raise ValueError("locked source paths must be safe repository-relative paths")
        if int(identity.get("bytes", 0)) <= 0:
            raise ValueError(f"locked source {relative} has invalid bytes")
        _strict_digest(identity.get("sha256"), f"locked source {relative} sha256")
    baseline_contract = _mapping(
        lock.get("baseline_result_identity_contract"), "baseline result identity contract"
    )
    if baseline_contract.get("canonical_path") != CANONICAL_BASELINE_IDENTITY_RELATIVE:
        raise ValueError("lock does not bind the canonical baseline result identity")
    if baseline_contract.get("required_before_v18_execute") is not True:
        raise ValueError("baseline result identity is not required before V18 execute")
    if baseline_contract.get("raw_evidence_eligible") is not True:
        raise ValueError("lock does not require eligible baseline raw evidence")
    if baseline_contract.get("report_evidence_eligible") is not True:
        raise ValueError("lock does not require eligible baseline report evidence")
    if int(baseline_contract.get("bytes", 0)) <= 0:
        raise ValueError("baseline result identity bytes are not locked")
    _strict_digest(baseline_contract.get("sha256"), "baseline result identity sha256")
    if lock.get("metric_semantics") != LOCKED_METRIC_SEMANTICS:
        raise ValueError("execution lock metric semantics drifted")
    return lock


def _canonical_file(path: Path, *, root: Path, relative: str, label: str) -> Path:
    lexical = root / relative
    if lexical.is_symlink() or not lexical.is_file():
        raise ValueError(f"canonical {label} must be a non-symlink regular file")
    canonical = lexical.resolve()
    if path.resolve() != canonical:
        raise ValueError(f"execute requires canonical {label}: {canonical}")
    return canonical


def _identity(
    path: Path, *, root: Path, relative: str, expected: Mapping[str, Any]
) -> dict[str, Any]:
    lexical = root / relative
    if lexical.is_symlink() or not lexical.is_file():
        raise RuntimeError(f"identity path is missing, non-regular, or symlinked: {relative}")
    target = lexical.resolve()
    if root not in target.parents:
        raise ValueError("identity path escapes repository root")
    stat = target.stat()
    actual = {
        "path": relative,
        "bytes": stat.st_size,
        "sha256": sha256_file(target),
    }
    if actual["bytes"] != int(expected["bytes"]) or actual["sha256"] != str(expected["sha256"]):
        raise RuntimeError(f"identity mismatch: {relative}")
    return actual


def _git(root: Path, *args: str) -> str:
    completed = subprocess.run(("git", *args), cwd=root, check=True, capture_output=True, text=True)
    return completed.stdout.strip()


def _git_blob_identity(root: Path, commit: str, relative: str) -> dict[str, Any]:
    object_name = f"{commit}:{relative}"
    object_type = subprocess.run(
        ("git", "cat-file", "-t", object_name),
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
    )
    if object_type.returncode != 0 or object_type.stdout.strip() != "blob":
        raise RuntimeError(f"locked commit source is missing or non-blob: {relative}")
    content = subprocess.run(
        ("git", "cat-file", "blob", object_name),
        cwd=root,
        check=True,
        capture_output=True,
    ).stdout
    return {
        "path": relative,
        "bytes": len(content),
        "sha256": hashlib.sha256(content).hexdigest(),
    }


def _source_provenance(lock: Mapping[str, Any], root: Path) -> dict[str, Any]:
    sources = _mapping(lock["source_files"], "source_files")
    paths = sorted({*sources, CANONICAL_LOCK_RELATIVE})
    head = _git(root, "rev-parse", "HEAD")
    locked_commit = str(lock["execution_git_commit"])
    ancestor = (
        subprocess.run(
            ("git", "merge-base", "--is-ancestor", locked_commit, head),
            cwd=root,
            check=False,
            capture_output=True,
            text=True,
        ).returncode
        == 0
    )
    status = _git(root, "status", "--porcelain=v1", "--untracked-files=all", "--", *paths)
    identities = {
        relative: _identity(
            root / relative,
            root=root,
            relative=relative,
            expected=_mapping(spec, f"source {relative}"),
        )
        for relative, spec in sorted(sources.items())
    }
    locked_commit_blobs = {
        relative: _git_blob_identity(root, locked_commit, relative) for relative in sorted(sources)
    }
    locked_commit_blobs_match = all(
        locked_commit_blobs[relative]["bytes"] == int(spec["bytes"])
        and locked_commit_blobs[relative]["sha256"] == str(spec["sha256"])
        and locked_commit_blobs[relative] == identities[relative]
        for relative, spec in sources.items()
    )
    return {
        "runtime_git_commit": head,
        "locked_source_commit": locked_commit,
        "locked_commit_is_runtime_ancestor": ancestor,
        "scoped_source_clean": status == "",
        "scoped_source_status": status.splitlines() if status else [],
        "source_identities": identities,
        "locked_commit_blob_identities": locked_commit_blobs,
        "locked_commit_blobs_match": locked_commit_blobs_match,
    }


def _assert_source_ready(source: Mapping[str, Any]) -> None:
    if not source["locked_commit_is_runtime_ancestor"]:
        raise RuntimeError("locked source commit is not an ancestor of runtime HEAD")
    if source.get("locked_commit_blobs_match") is not True:
        raise RuntimeError(
            "current clean source differs from the exact Git blobs at locked source commit"
        )
    if not source["scoped_source_clean"]:
        raise RuntimeError(f"V18 scoped source is dirty: {source['scoped_source_status']}")


def _lineage_specs(prereg: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    frozen = _mapping(prereg.get("frozen_lineage"), "frozen_lineage")
    result: dict[str, Mapping[str, Any]] = {}
    for name, raw in frozen.items():
        if isinstance(raw, Mapping) and {"path", "bytes", "sha256"}.issubset(raw):
            result[str(name)] = raw
    if not result:
        raise ValueError("V18 preregistration has no verifiable lineage identities")
    return result


def _verify_lineage(prereg: Mapping[str, Any], root: Path) -> dict[str, SnapshotVerification]:
    return {
        name: verify_frozen_snapshot(name, spec, repo_root=root)
        for name, spec in _lineage_specs(prereg).items()
    }


def _baseline_identity_evidence(
    path: Path,
    *,
    root: Path,
    prereg: Mapping[str, Any],
    expected_execution_git_commit: str,
) -> dict[str, Any]:
    """Validate the sealed baseline identity and hash its raw/report artifacts."""

    try:
        identity = _read_json(path, "baseline result identity")
    except ValueError as exc:
        raise RuntimeError(str(exc)) from exc
    if identity.get("schema_version") != ("crypto-15m-v15p2-fair-baseline-v2-result-identity-v1"):
        raise RuntimeError("baseline result identity schema drifted")
    if identity.get("status") != "SEALED_ELIGIBLE_BASELINE_MEASUREMENT_NO_DEPLOYMENT":
        raise RuntimeError("baseline result identity status is not sealed eligible")
    if identity.get("live_or_paper_authorized") is not False:
        raise RuntimeError("baseline result identity must forbid live and paper use")
    identity_commit = str(identity.get("execution_git_commit", ""))
    if identity_commit != expected_execution_git_commit:
        raise RuntimeError("baseline identity execution commit differs from V18 lock")

    raw = _mapping(identity.get("raw_artifact"), "baseline raw artifact")
    report = _mapping(identity.get("report_artifact"), "baseline report artifact")
    artifact_contracts = (
        (
            raw,
            CANONICAL_BASELINE_RAW_RELATIVE,
            "crypto-15m-v15p2-fair-baseline-run-v2",
            "baseline raw artifact",
        ),
        (
            report,
            CANONICAL_BASELINE_REPORT_RELATIVE,
            "crypto-15m-v15p2-fair-baseline-report-v2",
            "baseline report artifact",
        ),
    )
    artifacts: dict[str, Any] = {}
    for spec, relative, schema, label in artifact_contracts:
        if spec.get("path") != relative or spec.get("schema_version") != schema:
            raise RuntimeError(f"{label} canonical path or schema drifted")
        if spec.get("evidence_eligible") is not True:
            raise RuntimeError(f"{label} is not evidence eligible")
        artifacts[label] = _identity(
            root / relative,
            root=root,
            relative=relative,
            expected=spec,
        )

    raw_payload = _read_json(root / CANONICAL_BASELINE_RAW_RELATIVE, "baseline raw artifact")
    report_payload = _read_json(
        root / CANONICAL_BASELINE_REPORT_RELATIVE, "baseline report artifact"
    )
    if raw_payload.get("schema_version") != "crypto-15m-v15p2-fair-baseline-run-v2":
        raise RuntimeError("baseline raw payload schema drifted")
    if raw_payload.get("evidence_eligible") is not True:
        raise RuntimeError("baseline raw payload is not evidence eligible")
    raw_source = _mapping(raw_payload.get("source_provenance"), "baseline raw source")
    raw_commit = str(raw_source.get("git_commit", ""))
    if raw_commit != identity_commit:
        raise RuntimeError("baseline raw source commit differs from sealed identity")
    runtime_versions = dict(
        _mapping(raw_payload.get("runtime_versions"), "baseline raw runtime versions")
    )
    if report_payload.get("schema_version") != ("crypto-15m-v15p2-fair-baseline-report-v2"):
        raise RuntimeError("baseline report payload schema drifted")
    if report_payload.get("evidence_eligible") is not True:
        raise RuntimeError("baseline report payload is not evidence eligible")
    report_provenance = _mapping(report_payload.get("provenance"), "baseline report provenance")
    if report_provenance.get("raw_git_commit") != identity_commit:
        raise RuntimeError("baseline report raw commit differs from sealed identity")
    raw_payload_sha = _payload_sha256(raw_payload)
    if report_provenance.get("raw_payload_sha256") != raw_payload_sha:
        raise RuntimeError("baseline report does not bind the exact raw payload")
    input_artifact = _mapping(
        report_provenance.get("input_artifact"), "baseline report input artifact"
    )
    if input_artifact.get("sha256") != artifacts["baseline raw artifact"]["sha256"]:
        raise RuntimeError("baseline report input SHA differs from raw file identity")
    if int(input_artifact.get("file_bytes", -1)) != artifacts["baseline raw artifact"]["bytes"]:
        raise RuntimeError("baseline report input bytes differ from raw file identity")

    frozen = _mapping(prereg.get("frozen_lineage"), "frozen_lineage")
    snapshots = _mapping(prereg.get("snapshots"), "snapshots")
    identity_bindings = (
        (
            "preregistration",
            _mapping(frozen["fair_baseline_v2_contract"], "baseline prereg lineage"),
        ),
        (
            "program_source",
            _mapping(frozen["fair_baseline_v2_program_source"], "baseline program lineage"),
        ),
        (
            "report_source",
            _mapping(frozen["fair_baseline_v2_report_source"], "baseline report lineage"),
        ),
        ("market_snapshot", _mapping(snapshots["market"], "market snapshot")),
        ("funding_snapshot", _mapping(snapshots["funding"], "funding snapshot")),
    )
    for name, expected in identity_bindings:
        actual = _mapping(identity.get(name), f"baseline identity {name}")
        for key in ("path", "bytes", "sha256"):
            if actual.get(key) != expected.get(key):
                raise RuntimeError(f"baseline identity {name} does not match V18 lineage")
    return {
        "identity_payload_sha256": _payload_sha256(identity),
        "raw_artifact": artifacts["baseline raw artifact"],
        "report_artifact": artifacts["baseline report artifact"],
        "execution_git_commit": identity_commit,
        "raw_payload_sha256": raw_payload_sha,
        "runtime_versions": runtime_versions,
    }


def _jsonable(value: Any) -> Any:
    return baseline._jsonable(value)


def _payload_sha256(value: Any) -> str:
    return baseline._payload_sha256(value)


def deterministic_json(payload: Mapping[str, Any]) -> str:
    return json.dumps(_jsonable(payload), sort_keys=True, indent=2, allow_nan=False) + "\n"


def _candidate_batches(
    frames: Mapping[str, pd.DataFrame], baseline_batch: Any
) -> Mapping[str, Any]:
    # Local import keeps dry-plan independent of the implementation module and
    # lets tests replace this pure seam without any data IO.
    from price_action.lab.crypto_15m_v18_signals import generate_v18_candidate_batches

    batches = generate_v18_candidate_batches(frames, baseline_batch=baseline_batch)
    if not isinstance(batches, Mapping) or tuple(batches) != CELL_ORDER:
        raise RuntimeError("V18 adapter did not return the canonical four-cell order")
    return batches


def _intent_proxy(intent: Any, cell_id: str) -> _CellIntentProxy:
    serialized = _jsonable(intent)
    if not isinstance(serialized, Mapping):
        raise TypeError("candidate intent must serialize to an object")
    required = (
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
    missing = [name for name in required if not hasattr(intent, name)]
    if missing:
        raise TypeError(f"candidate intent omitted fields: {missing}")
    if str(intent.candidate_id) != FAIR_BASELINE_CANDIDATE_ID:
        raise RuntimeError("V18 adapter intent lost its frozen source identity")
    values = {name: getattr(intent, name) for name in required}
    return _CellIntentProxy(
        candidate_id=FAIR_BASELINE_CANDIDATE_ID,
        cell_id=cell_id,
        source_candidate_id=FAIR_BASELINE_CANDIDATE_ID,
        source_intent_sha256=_payload_sha256(serialized),
        **values,
    )


def _rebind_candidate_ids(
    value: Any,
    target_candidate_id: str,
    *,
    source_candidate_id: str = FAIR_BASELINE_CANDIDATE_ID,
) -> Any:
    """Bind serialized engine ledgers to their cell without mutating results."""

    if isinstance(value, dict):
        return {
            key: (
                target_candidate_id
                if key == "candidate_id" and child == source_candidate_id
                else _rebind_candidate_ids(
                    child,
                    target_candidate_id,
                    source_candidate_id=source_candidate_id,
                )
            )
            for key, child in value.items()
        }
    if isinstance(value, list):
        return [
            _rebind_candidate_ids(
                child,
                target_candidate_id,
                source_candidate_id=source_candidate_id,
            )
            for child in value
        ]
    return value


def _candidate_id_leaf_count(value: Any, expected: str) -> int:
    if isinstance(value, dict):
        return sum(
            (1 if key == "candidate_id" and child == expected else 0)
            + _candidate_id_leaf_count(child, expected)
            for key, child in value.items()
        )
    if isinstance(value, list):
        return sum(_candidate_id_leaf_count(child, expected) for child in value)
    return 0


def _write_json_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    baseline._write_json_atomic(path, _jsonable(payload))


def _validate_bundle_dir(raw: Path, *, root: Path, expected_relative: str) -> Path:
    output = raw.resolve()
    expected = (root / expected_relative).resolve()
    if output != expected:
        raise ValueError(f"bundle directory must be the canonical path: {expected}")
    if output.exists() or output.is_symlink():
        raise FileExistsError(f"bundle path already exists: {output}")
    return output


def _file_identity(path: Path, relative_to: Path) -> dict[str, Any]:
    return {
        "path": str(path.relative_to(relative_to)),
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def _primary_report_evidence(
    path: Path,
    *,
    root: Path,
    prereg: Mapping[str, Any],
    expected_bytes: int | None = None,
    expected_sha256: str | None = None,
    expected_manifest_bytes: int | None = None,
    expected_manifest_sha256: str | None = None,
    recompute: bool = True,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Validate the canonical eligible pre-LOSO report and its locked winner."""

    canonical = _canonical_file(
        path,
        root=root,
        relative=CANONICAL_PRIMARY_REPORT_RELATIVE,
        label="V18 primary report",
    )
    report = _read_json(canonical, "V18 primary report")
    if report.get("schema_version") != "crypto-15m-v18-primary-report-v1":
        raise RuntimeError("V18 primary report schema drifted")
    if report.get("deterministic") is not True or report.get("evidence_eligible") is not True:
        raise RuntimeError("V18 primary report is not deterministic eligible evidence")
    if report.get("evidence_ineligible_reasons") != []:
        raise RuntimeError("V18 primary report carries ineligibility reasons")
    if report.get("candidate_order") != list(CELL_ORDER):
        raise RuntimeError("V18 primary report candidate order drifted")
    if report.get("scenario_order") != list(SCENARIO_ORDER):
        raise RuntimeError("V18 primary report scenario order drifted")
    decision = _mapping(report.get("decision"), "V18 primary report decision")
    if decision.get("verdict") != "REQUIRES_TRUE_LOSO":
        raise RuntimeError("V18 primary report does not require true LOSO")
    winner = str(decision.get("locked_winner", ""))
    if winner not in CELL_ORDER:
        raise RuntimeError("V18 primary report locked_winner drifted")
    if decision.get("paper_authorized") is not False:
        raise RuntimeError("V18 primary report unexpectedly authorizes paper trading")
    if decision.get("live_deployment_authorized") is not False:
        raise RuntimeError("V18 primary report unexpectedly authorizes live deployment")
    if decision.get("historical_feasibility_only") is not True:
        raise RuntimeError("V18 primary report lost historical-only classification")
    if decision.get("remaining_required_evidence") != [
        "TRUE_LOSO_NOT_YET_EVALUATED",
        "BASELINE_COMPARISON_NOT_YET_EVALUATED",
    ]:
        raise RuntimeError("V18 primary report remaining evidence contract drifted")
    ranking = report.get("ranking")
    if not isinstance(ranking, list) or not ranking:
        raise RuntimeError("V18 primary report has no deterministic winner ranking")
    first = _mapping(ranking[0], "V18 primary report first ranking row")
    if first.get("candidate_id") != winner or int(first.get("rank", -1)) != 1:
        raise RuntimeError("V18 primary report winner and ranking disagree")
    provenance = _mapping(report.get("provenance"), "V18 primary report provenance")
    primary_manifest_relative = f"{CANONICAL_PRIMARY_BUNDLE_RELATIVE}/manifest.json"
    primary_manifest_path = (root / primary_manifest_relative).resolve()
    if provenance.get("manifest_path") != str(primary_manifest_path):
        raise RuntimeError("V18 primary report does not bind the canonical primary manifest")
    primary_manifest = _identity(
        primary_manifest_path,
        root=root,
        relative=primary_manifest_relative,
        expected={
            "bytes": provenance.get("manifest_bytes"),
            "sha256": provenance.get("manifest_sha256"),
        },
    )
    if (expected_manifest_bytes is None) != (expected_manifest_sha256 is None):
        raise ValueError("primary manifest bytes and SHA-256 must be supplied together")
    if expected_manifest_bytes is not None:
        if int(expected_manifest_bytes) != primary_manifest["bytes"]:
            raise RuntimeError("locked primary manifest byte identity mismatch")
        if (
            _strict_digest(expected_manifest_sha256, "locked primary manifest sha256")
            != primary_manifest["sha256"]
        ):
            raise RuntimeError("locked primary manifest SHA-256 identity mismatch")
    if recompute:
        rebuilt = _rebuild_primary_report(primary_manifest_path, prereg=prereg, root=root)
        if _payload_sha256(rebuilt) != _payload_sha256(report):
            raise RuntimeError(
                "V18 primary report does not deterministically derive from its manifest"
            )
    actual = {
        "path": CANONICAL_PRIMARY_REPORT_RELATIVE,
        "bytes": canonical.stat().st_size,
        "sha256": sha256_file(canonical),
        "schema_version": "crypto-15m-v18-primary-report-v1",
        "evidence_eligible": True,
        "locked_winner": winner,
        "primary_manifest": primary_manifest,
    }
    if (expected_bytes is None) != (expected_sha256 is None):
        raise ValueError("primary report bytes and SHA-256 must be supplied together")
    if expected_bytes is not None:
        if int(expected_bytes) != actual["bytes"]:
            raise RuntimeError("V18 primary report byte identity mismatch")
        if _strict_digest(expected_sha256, "primary report sha256") != actual["sha256"]:
            raise RuntimeError("V18 primary report SHA-256 identity mismatch")
    return report, actual


def _rebuild_primary_report(
    manifest_path: Path, *, prereg: Mapping[str, Any], root: Path
) -> dict[str, Any]:
    """Late import avoids the report module's intentional program dependency."""

    from price_action.lab.crypto_15m_v18_report import build_primary_report

    return build_primary_report(manifest_path, prereg=prereg, repo_root=root)


def dry_plan(
    prereg_path: Path,
    *,
    repo_root: Path | None = None,
    phase: str = "primary",
) -> dict[str, Any]:
    """Return a validated plan with zero configured-snapshot access."""

    root = (repo_root or Path(__file__).resolve().parents[3]).resolve()
    prereg = load_preregistration(prereg_path.resolve())
    snapshots = _mapping(prereg["snapshots"], "snapshots")
    if phase not in {"primary", "loso"}:
        raise ValueError("phase must be primary or loso")
    plan = {
        "schema_version": PROGRAM_SCHEMA,
        "mode": "DRY_PLAN_ZERO_SNAPSHOT_ACCESS",
        "phase": phase,
        "evidence_eligible": False,
        "candidate_order": list(CELL_ORDER),
        "scenario_order": list(SCENARIO_ORDER),
        "expected_independent_replays": 12,
        "execution_lock": {
            "canonical_path": CANONICAL_LOCK_RELATIVE,
            "status": "NOT_ACCESSED_DRY_PLAN",
        },
        "snapshots": {
            name: {
                "configured_path": str(_mapping(snapshots[name], name)["path"]),
                "expected_bytes": int(_mapping(snapshots[name], name)["bytes"]),
                "expected_sha256": str(_mapping(snapshots[name], name)["sha256"]),
                "status": "NOT_ACCESSED",
            }
            for name in ("market", "funding")
        },
        "metric_semantics_required_in_execution_lock": LOCKED_METRIC_SEMANTICS,
        "live_or_paper_authorized": False,
        "repo_root": str(root),
        "canonical_bundle_path": (
            CANONICAL_PRIMARY_BUNDLE_RELATIVE
            if phase == "primary"
            else CANONICAL_LOSO_BUNDLE_RELATIVE
        ),
    }
    if phase == "loso":
        plan.update(
            {
                "expected_independent_replays": len(PRIMARY_SYMBOLS),
                "scenario_order": ["H"],
                "excluded_symbol_order": list(PRIMARY_SYMBOLS),
                "primary_report": {
                    "canonical_path": CANONICAL_PRIMARY_REPORT_RELATIVE,
                    "required_verdict": "REQUIRES_TRUE_LOSO",
                    "status": "NOT_ACCESSED_DRY_PLAN",
                },
                "runner_up_fallback_forbidden": True,
            }
        )
    return plan


def run_program(
    prereg_path: Path,
    *,
    execution_lock_path: Path,
    bundle_dir: Path,
    repo_root: Path,
) -> dict[str, Any]:
    """Execute and publish the canonical four-cell by three-scenario bundle."""

    root = repo_root.resolve()
    prereg_path = _canonical_file(
        prereg_path, root=root, relative=CANONICAL_PREREG_RELATIVE, label="preregistration"
    )
    lock_path = _canonical_file(
        execution_lock_path, root=root, relative=CANONICAL_LOCK_RELATIVE, label="execution lock"
    )
    output = _validate_bundle_dir(
        bundle_dir,
        root=root,
        expected_relative=CANONICAL_PRIMARY_BUNDLE_RELATIVE,
    )
    prereg = load_preregistration(prereg_path)
    lock = _load_execution_lock(lock_path)

    prereg_identity = _identity(
        prereg_path,
        root=root,
        relative=CANONICAL_PREREG_RELATIVE,
        expected=_mapping(lock["preregistration"], "locked preregistration"),
    )
    lock_sha_pre = sha256_file(lock_path)
    lock_bytes = lock_path.stat().st_size
    runtime_pre = baseline._critical_runtime_versions(root)
    source_pre = _source_provenance(lock, root)
    _assert_source_ready(source_pre)

    baseline_contract = _mapping(
        lock["baseline_result_identity_contract"], "baseline result identity contract"
    )
    baseline_identity = _identity(
        root / CANONICAL_BASELINE_IDENTITY_RELATIVE,
        root=root,
        relative=CANONICAL_BASELINE_IDENTITY_RELATIVE,
        expected=baseline_contract,
    )
    baseline_evidence_pre = _baseline_identity_evidence(
        root / CANONICAL_BASELINE_IDENTITY_RELATIVE,
        root=root,
        prereg=prereg,
        expected_execution_git_commit=str(lock["execution_git_commit"]),
    )
    if baseline_evidence_pre["runtime_versions"] != runtime_pre:
        raise RuntimeError("V18 critical runtime differs from the sealed baseline runtime")
    lineage_pre = _verify_lineage(prereg, root)
    snapshots = _mapping(prereg["snapshots"], "snapshots")
    verified_pre = {
        name: verify_frozen_snapshot(name, snapshots[name], repo_root=root)
        for name in ("market", "funding")
    }

    market_spec = _mapping(snapshots["market"], "market snapshot")
    market = load_market_snapshot(
        Path(verified_pre["market"].resolved_path),
        market_spec,
        symbols=(*PRIMARY_SYMBOLS, REFERENCE_SYMBOL),
        start=HISTORY_START,
        end=EVALUATION_END,
    )
    baseline._validate_loaded_market(market)
    funding = load_funding_snapshot(
        Path(verified_pre["funding"].resolved_path),
        _mapping(snapshots["funding"], "funding snapshot"),
        symbols=PRIMARY_SYMBOLS,
        venue=str(market_spec["venue"]),
        start=HISTORY_START,
        engine_start=EVALUATION_START,
        end=EVALUATION_END,
    )

    signal_frames = {symbol: market.frames[symbol] for symbol in PRIMARY_SYMBOLS}
    baseline_batch = generate_v15p2_signal_batch(
        signal_frames,
        config_path=root / CANONICAL_CONFIG_RELATIVE,
        config_sha256=EXPECTED_CONFIG_SHA256,
    )
    candidate_batches = _candidate_batches(signal_frames, baseline_batch)

    baseline_prereg = baseline.load_preregistration(root / CANONICAL_BASELINE_PREREG_RELATIVE)
    policy = baseline.build_policy(baseline_prereg)
    scenarios = baseline.build_scenarios(baseline_prereg)
    if tuple(scenarios) != SCENARIO_ORDER:
        raise RuntimeError("baseline scenario order differs from V18")
    validation_start = EVALUATION_START - _BAR
    engine_frames = {
        symbol: frame.loc[
            (frame["ts"] >= validation_start) & (frame["ts"] < EVALUATION_END)
        ].reset_index(drop=True)
        for symbol, frame in signal_frames.items()
    }
    if any(frame.empty for frame in engine_frames.values()):
        raise RuntimeError("every primary engine frame must contain evaluation bars")
    daily_returns = baseline._daily_log_returns(signal_frames)

    frame_hashes = baseline._frame_hashes(engine_frames)
    funding_hash = _payload_sha256(funding.engine_events)
    returns_hash = baseline._dataframe_sha256(daily_returns)
    baseline_decisions = _jsonable(baseline_batch.decisions)
    baseline_intents = _jsonable(baseline_batch.intents)
    baseline_decisions_hash = _payload_sha256(baseline_decisions)
    baseline_intents_hash = _payload_sha256(baseline_intents)
    candidate_hashes = {
        cell: _payload_sha256(_jsonable(candidate_batches[cell])) for cell in CELL_ORDER
    }

    output_created = False
    shard_identities: list[dict[str, Any]] = []
    for cell_id in CELL_ORDER:
        batch = candidate_batches[cell_id]
        if str(getattr(batch, "candidate_id", "")) != cell_id:
            raise RuntimeError(f"candidate adapter returned foreign identity for {cell_id}")
        source_intents = tuple(batch.intents)
        proxies = tuple(
            _intent_proxy(intent, cell_id)
            for intent in source_intents
            if EVALUATION_START.to_pydatetime() <= intent.entry_ts < EVALUATION_END.to_pydatetime()
        )
        adapter_decisions = _jsonable(batch.decisions)
        adapter_rejections = _jsonable(batch.rejections)
        source_intent_payload = _jsonable(source_intents)
        proxy_payload = _jsonable(proxies)
        stream_hashes = {
            "adapter_decisions_sha256": _payload_sha256(adapter_decisions),
            "adapter_rejections_sha256": _payload_sha256(adapter_rejections),
            "source_intents_sha256": _payload_sha256(source_intent_payload),
            "engine_proxy_intents_sha256": _payload_sha256(proxy_payload),
        }
        for scenario_name in SCENARIO_ORDER:
            result = run_v15p2_engine(
                engine_frames,
                proxies,
                funding.engine_events,
                daily_returns,
                scenario=scenarios[scenario_name],
                policy=policy,
                evaluation_start=EVALUATION_START.to_pydatetime(),
                evaluation_end=EVALUATION_END.to_pydatetime(),
            )
            baseline._assert_result_window(
                result,
                scenario_name,
                scenario_config=scenarios[scenario_name],
                policy=policy,
            )
            raw_result = _jsonable(result)
            rebound_count = _candidate_id_leaf_count(raw_result, FAIR_BASELINE_CANDIDATE_ID)
            bound_result = _rebind_candidate_ids(raw_result, cell_id)
            if _candidate_id_leaf_count(bound_result, FAIR_BASELINE_CANDIDATE_ID) != 0:
                raise RuntimeError("engine candidate identity rebind was incomplete")
            if _candidate_id_leaf_count(bound_result, cell_id) != rebound_count:
                raise RuntimeError("engine candidate identity rebind changed unexpected leaves")

            # Reject mutation immediately so a damaged input never reaches the
            # next independent scenario path.
            if baseline._frame_hashes(engine_frames) != frame_hashes:
                raise RuntimeError("engine mutated market frames")
            if _payload_sha256(funding.engine_events) != funding_hash:
                raise RuntimeError("engine mutated funding events")
            if baseline._dataframe_sha256(daily_returns) != returns_hash:
                raise RuntimeError("engine mutated daily returns")
            if _payload_sha256(_jsonable(baseline_batch.decisions)) != baseline_decisions_hash:
                raise RuntimeError("baseline signal decision ledger mutated")
            if _payload_sha256(_jsonable(baseline_batch.intents)) != baseline_intents_hash:
                raise RuntimeError("baseline signal intents mutated")
            if _payload_sha256(_jsonable(candidate_batches[cell_id])) != candidate_hashes[cell_id]:
                raise RuntimeError("candidate signal batch mutated")

            policy_payload = _jsonable(policy)
            scenario_payload = _jsonable(scenarios[scenario_name])
            shard = {
                "schema_version": SHARD_SCHEMA,
                "program_schema_version": PROGRAM_SCHEMA,
                "candidate_id": cell_id,
                "scenario": scenario_name,
                "candidate_batch_sha256": candidate_hashes[cell_id],
                "preregistration": prereg_identity,
                "execution_lock": {
                    "path": CANONICAL_LOCK_RELATIVE,
                    "bytes": lock_bytes,
                    "sha256": lock_sha_pre,
                },
                "baseline_result_identity": baseline_identity,
                "policy": policy_payload,
                "policy_sha256": _payload_sha256(policy_payload),
                "scenario_config": scenario_payload,
                "scenario_config_sha256": _payload_sha256(scenario_payload),
                "candidate_signal_stream": {
                    "source_candidate_id": FAIR_BASELINE_CANDIDATE_ID,
                    "cell_candidate_id": cell_id,
                    "baseline_decision_ledger_sha256": baseline_decisions_hash,
                    "baseline_intents_sha256": baseline_intents_hash,
                    "adapter_decisions": adapter_decisions,
                    "adapter_rejections": adapter_rejections,
                    "source_intents": source_intent_payload,
                    "engine_proxy_intents": proxy_payload,
                    **stream_hashes,
                    "reason_counts": dict(
                        sorted(Counter(row.reason for row in batch.decisions).items())
                    ),
                },
                "engine_candidate_binding": {
                    "engine_validation_identity": FAIR_BASELINE_CANDIDATE_ID,
                    "serialized_ledger_identity": cell_id,
                    "binding_method": "DETERMINISTIC_POST_ENGINE_CANDIDATE_ID_REBIND",
                    "candidate_id_rebinding_count": rebound_count,
                    "zero_rebinding_allowed_only_when_engine_has_no_candidate_ledger_rows": True,
                    "raw_engine_result_sha256": _payload_sha256(raw_result),
                },
                "complete_result": bound_result,
                "complete_result_sha256": _payload_sha256(bound_result),
            }
            shard_payload_sha = _payload_sha256(shard)
            if not output_created:
                output.mkdir(parents=False, exist_ok=False)
                output_created = True
            shard_path = output / f"{cell_id}__{scenario_name}.json"
            _write_json_atomic(shard_path, shard)
            file_identity = _file_identity(shard_path, output)
            shard_identities.append(
                {
                    "candidate_id": cell_id,
                    "scenario": scenario_name,
                    **file_identity,
                    "payload_sha256": shard_payload_sha,
                }
            )

    if not output_created or len(shard_identities) != 12:
        raise RuntimeError("twelve scenario shards were not published")
    source_post = _source_provenance(lock, root)
    _assert_source_ready(source_post)
    runtime_post = baseline._critical_runtime_versions(root)
    prereg_identity_post = _identity(
        prereg_path,
        root=root,
        relative=CANONICAL_PREREG_RELATIVE,
        expected=_mapping(lock["preregistration"], "locked preregistration"),
    )
    baseline_identity_post = _identity(
        root / CANONICAL_BASELINE_IDENTITY_RELATIVE,
        root=root,
        relative=CANONICAL_BASELINE_IDENTITY_RELATIVE,
        expected=baseline_contract,
    )
    baseline_evidence_post = _baseline_identity_evidence(
        root / CANONICAL_BASELINE_IDENTITY_RELATIVE,
        root=root,
        prereg=prereg,
        expected_execution_git_commit=str(lock["execution_git_commit"]),
    )
    lineage_post = _verify_lineage(prereg, root)
    verified_post = {
        name: verify_frozen_snapshot(name, snapshots[name], repo_root=root)
        for name in ("market", "funding")
    }
    if source_post != source_pre:
        raise RuntimeError("scoped research source changed during V18 replay")
    if runtime_post != runtime_pre:
        raise RuntimeError("critical runtime changed during V18 replay")
    if sha256_file(lock_path) != lock_sha_pre or lock_path.stat().st_size != lock_bytes:
        raise RuntimeError("execution lock changed during V18 replay")
    if prereg_identity_post != prereg_identity:
        raise RuntimeError("V18 preregistration changed during replay")
    if baseline_identity_post != baseline_identity:
        raise RuntimeError("baseline result identity changed during V18 replay")
    if baseline_evidence_post != baseline_evidence_pre:
        raise RuntimeError("baseline raw or report artifact changed during V18 replay")
    if {name: asdict(value) for name, value in lineage_post.items()} != {
        name: asdict(value) for name, value in lineage_pre.items()
    }:
        raise RuntimeError("lineage changed during V18 replay")
    if {name: asdict(value) for name, value in verified_post.items()} != {
        name: asdict(value) for name, value in verified_pre.items()
    }:
        raise RuntimeError("snapshot identity changed during V18 replay")

    manifest = {
        "schema_version": MANIFEST_SCHEMA,
        "program_schema_version": PROGRAM_SCHEMA,
        "status": "COMPLETE",
        "evidence_eligible": True,
        "candidate_order": list(CELL_ORDER),
        "scenario_order": list(SCENARIO_ORDER),
        "replay_order": [
            {"candidate_id": cell, "scenario": scenario}
            for cell in CELL_ORDER
            for scenario in SCENARIO_ORDER
        ],
        "preregistration": prereg_identity,
        "execution_lock": {
            "path": CANONICAL_LOCK_RELATIVE,
            "bytes": lock_bytes,
            "sha256": lock_sha_pre,
        },
        "baseline_result_identity": baseline_identity,
        "baseline_evidence_artifacts": baseline_evidence_pre,
        "runtime_git_commit": source_post["runtime_git_commit"],
        "locked_source_commit": source_post["locked_source_commit"],
        "source_preflight": source_pre,
        "source_postflight": source_post,
        "runtime_preflight": runtime_pre,
        "runtime_postflight": runtime_post,
        "lineage": {name: asdict(value) for name, value in lineage_pre.items()},
        "snapshots": {name: asdict(value) for name, value in verified_pre.items()},
        "input_hashes": {
            "engine_frames_sha256_by_symbol": frame_hashes,
            "funding_events_sha256": funding_hash,
            "daily_returns_sha256": returns_hash,
            "baseline_decisions_sha256": baseline_decisions_hash,
            "baseline_intents_sha256": baseline_intents_hash,
            "candidate_batches_sha256": candidate_hashes,
        },
        "generation_counts": {
            "market_snapshot_loads": 1,
            "funding_snapshot_loads": 1,
            "baseline_signal_generations": 1,
            "candidate_adapter_generations": 1,
            "independent_engine_replays": 12,
        },
        "shards": shard_identities,
        "manifest_published_last": True,
        "live_or_paper_authorized": False,
    }
    _payload_sha256(manifest)
    _write_json_atomic(output / "manifest.json", manifest)
    return manifest


def _funding_symbol(event: Any) -> str:
    if isinstance(event, Mapping):
        return str(event.get("symbol", ""))
    return str(getattr(event, "symbol", ""))


def _symbol_leaf_count(value: Any, symbol: str) -> int:
    if isinstance(value, dict):
        return sum(
            (1 if key == "symbol" and child == symbol else 0) + _symbol_leaf_count(child, symbol)
            for key, child in value.items()
        )
    if isinstance(value, list):
        return sum(_symbol_leaf_count(child, symbol) for child in value)
    return 0


def run_true_loso_replays(
    prereg_path: Path,
    *,
    execution_lock_path: Path,
    primary_report_path: Path,
    bundle_dir: Path,
    repo_root: Path,
    primary_report_bytes: int | None = None,
    primary_report_sha256: str | None = None,
) -> dict[str, Any]:
    """Run the primary report's sole locked winner through true 13-way LOSO."""

    root = repo_root.resolve()
    prereg_path = _canonical_file(
        prereg_path,
        root=root,
        relative=CANONICAL_PREREG_RELATIVE,
        label="preregistration",
    )
    lock_path = _canonical_file(
        execution_lock_path,
        root=root,
        relative=CANONICAL_LOCK_RELATIVE,
        label="execution lock",
    )
    primary_report_path = _canonical_file(
        primary_report_path,
        root=root,
        relative=CANONICAL_PRIMARY_REPORT_RELATIVE,
        label="V18 primary report",
    )
    output = _validate_bundle_dir(
        bundle_dir,
        root=root,
        expected_relative=CANONICAL_LOSO_BUNDLE_RELATIVE,
    )
    prereg = load_preregistration(prereg_path)
    lock = _load_execution_lock(lock_path)

    if primary_report_bytes is None or primary_report_sha256 is None:
        raise ValueError("true LOSO requires CLI-pinned primary report bytes and SHA-256")

    prereg_identity = _identity(
        prereg_path,
        root=root,
        relative=CANONICAL_PREREG_RELATIVE,
        expected=_mapping(lock["preregistration"], "locked preregistration"),
    )
    lock_sha_pre = sha256_file(lock_path)
    lock_bytes = lock_path.stat().st_size
    runtime_pre = baseline._critical_runtime_versions(root)
    source_pre = _source_provenance(lock, root)
    _assert_source_ready(source_pre)
    primary_report, primary_report_identity = _primary_report_evidence(
        primary_report_path,
        root=root,
        prereg=prereg,
        expected_bytes=primary_report_bytes,
        expected_sha256=primary_report_sha256,
    )
    winner = str(_mapping(primary_report["decision"], "primary decision")["locked_winner"])

    baseline_contract = _mapping(
        lock["baseline_result_identity_contract"], "baseline result identity contract"
    )
    baseline_identity = _identity(
        root / CANONICAL_BASELINE_IDENTITY_RELATIVE,
        root=root,
        relative=CANONICAL_BASELINE_IDENTITY_RELATIVE,
        expected=baseline_contract,
    )
    baseline_evidence_pre = _baseline_identity_evidence(
        root / CANONICAL_BASELINE_IDENTITY_RELATIVE,
        root=root,
        prereg=prereg,
        expected_execution_git_commit=str(lock["execution_git_commit"]),
    )
    if baseline_evidence_pre["runtime_versions"] != runtime_pre:
        raise RuntimeError("true LOSO critical runtime differs from the sealed baseline runtime")
    lineage_pre = _verify_lineage(prereg, root)
    snapshots = _mapping(prereg["snapshots"], "snapshots")
    verified_pre = {
        name: verify_frozen_snapshot(name, snapshots[name], repo_root=root)
        for name in ("market", "funding")
    }

    market_spec = _mapping(snapshots["market"], "market snapshot")
    market = load_market_snapshot(
        Path(verified_pre["market"].resolved_path),
        market_spec,
        symbols=(*PRIMARY_SYMBOLS, REFERENCE_SYMBOL),
        start=HISTORY_START,
        end=EVALUATION_END,
    )
    baseline._validate_loaded_market(market)
    funding = load_funding_snapshot(
        Path(verified_pre["funding"].resolved_path),
        _mapping(snapshots["funding"], "funding snapshot"),
        symbols=PRIMARY_SYMBOLS,
        venue=str(market_spec["venue"]),
        start=HISTORY_START,
        engine_start=EVALUATION_START,
        end=EVALUATION_END,
    )
    signal_frames = {symbol: market.frames[symbol] for symbol in PRIMARY_SYMBOLS}
    baseline_batch = generate_v15p2_signal_batch(
        signal_frames,
        config_path=root / CANONICAL_CONFIG_RELATIVE,
        config_sha256=EXPECTED_CONFIG_SHA256,
    )
    candidate_batches = _candidate_batches(signal_frames, baseline_batch)
    winner_batch = candidate_batches[winner]
    if str(getattr(winner_batch, "candidate_id", "")) != winner:
        raise RuntimeError("locked winner batch identity drifted")

    baseline_prereg = baseline.load_preregistration(root / CANONICAL_BASELINE_PREREG_RELATIVE)
    policy = baseline.build_policy(baseline_prereg)
    scenarios = baseline.build_scenarios(baseline_prereg)
    h_scenario = scenarios["H"]
    validation_start = EVALUATION_START - _BAR
    engine_frames = {
        symbol: frame.loc[
            (frame["ts"] >= validation_start) & (frame["ts"] < EVALUATION_END)
        ].reset_index(drop=True)
        for symbol, frame in signal_frames.items()
    }
    if any(frame.empty for frame in engine_frames.values()):
        raise RuntimeError("every primary engine frame must contain evaluation bars")
    daily_returns = baseline._daily_log_returns(signal_frames)
    if tuple(daily_returns.columns) != PRIMARY_SYMBOLS:
        raise RuntimeError("causal daily-return universe differs from primary13")

    frame_hashes = baseline._frame_hashes(engine_frames)
    funding_hash = _payload_sha256(funding.engine_events)
    returns_hash = baseline._dataframe_sha256(daily_returns)
    baseline_decisions_hash = _payload_sha256(_jsonable(baseline_batch.decisions))
    baseline_intents_hash = _payload_sha256(_jsonable(baseline_batch.intents))
    winner_batch_hash = _payload_sha256(_jsonable(winner_batch))
    adapter_decisions = _jsonable(winner_batch.decisions)
    adapter_rejections = _jsonable(winner_batch.rejections)
    source_intent_payload = _jsonable(winner_batch.intents)

    output_created = False
    shard_identities: list[dict[str, Any]] = []
    for excluded_symbol in PRIMARY_SYMBOLS:
        included_symbols = tuple(symbol for symbol in PRIMARY_SYMBOLS if symbol != excluded_symbol)
        loso_frames = {symbol: engine_frames[symbol] for symbol in included_symbols}
        loso_source_intents = tuple(
            intent
            for intent in winner_batch.intents
            if intent.symbol != excluded_symbol
            and EVALUATION_START.to_pydatetime() <= intent.entry_ts < EVALUATION_END.to_pydatetime()
        )
        proxies = tuple(_intent_proxy(intent, winner) for intent in loso_source_intents)
        loso_funding = tuple(
            event for event in funding.engine_events if _funding_symbol(event) != excluded_symbol
        )
        loso_returns = daily_returns.loc[:, list(included_symbols)].copy()
        proxy_payload = _jsonable(proxies)
        loso_frame_hashes = {symbol: frame_hashes[symbol] for symbol in included_symbols}
        loso_funding_hash = _payload_sha256(loso_funding)
        loso_returns_hash = baseline._dataframe_sha256(loso_returns)
        proxy_hash = _payload_sha256(proxy_payload)

        result = run_v15p2_engine(
            loso_frames,
            proxies,
            loso_funding,
            loso_returns,
            scenario=h_scenario,
            policy=policy,
            evaluation_start=EVALUATION_START.to_pydatetime(),
            evaluation_end=EVALUATION_END.to_pydatetime(),
        )
        baseline._assert_result_window(
            result,
            "H",
            scenario_config=h_scenario,
            policy=policy,
        )
        raw_result = _jsonable(result)
        if _symbol_leaf_count(raw_result, excluded_symbol) != 0:
            raise RuntimeError("LOSO engine result contains the excluded symbol")
        rebound_count = _candidate_id_leaf_count(raw_result, FAIR_BASELINE_CANDIDATE_ID)
        bound_result = _rebind_candidate_ids(raw_result, winner)
        if _candidate_id_leaf_count(bound_result, FAIR_BASELINE_CANDIDATE_ID) != 0:
            raise RuntimeError("LOSO engine candidate identity rebind was incomplete")
        if _candidate_id_leaf_count(bound_result, winner) != rebound_count:
            raise RuntimeError("LOSO engine candidate identity rebind changed unexpected leaves")

        if baseline._frame_hashes(engine_frames) != frame_hashes:
            raise RuntimeError("LOSO engine mutated market frames")
        if baseline._frame_hashes(loso_frames) != loso_frame_hashes:
            raise RuntimeError("LOSO engine mutated its excluded market universe")
        if _payload_sha256(funding.engine_events) != funding_hash:
            raise RuntimeError("LOSO engine mutated funding events")
        if _payload_sha256(loso_funding) != loso_funding_hash:
            raise RuntimeError("LOSO engine mutated its excluded funding universe")
        if baseline._dataframe_sha256(daily_returns) != returns_hash:
            raise RuntimeError("LOSO engine mutated daily returns")
        if baseline._dataframe_sha256(loso_returns) != loso_returns_hash:
            raise RuntimeError("LOSO engine mutated its excluded daily-return universe")
        if _payload_sha256(_jsonable(proxies)) != proxy_hash:
            raise RuntimeError("LOSO engine mutated its cell-attributed intent stream")
        if _payload_sha256(_jsonable(baseline_batch.decisions)) != baseline_decisions_hash:
            raise RuntimeError("LOSO baseline signal decision ledger mutated")
        if _payload_sha256(_jsonable(baseline_batch.intents)) != baseline_intents_hash:
            raise RuntimeError("LOSO baseline signal intents mutated")
        if _payload_sha256(_jsonable(winner_batch)) != winner_batch_hash:
            raise RuntimeError("LOSO locked winner batch mutated")

        policy_payload = _jsonable(policy)
        scenario_payload = _jsonable(h_scenario)
        shard = {
            "schema_version": LOSO_SHARD_SCHEMA,
            "program_schema_version": PROGRAM_SCHEMA,
            "phase": "TRUE_LOSO",
            "candidate_id": winner,
            "scenario": "H",
            "excluded_symbol": excluded_symbol,
            "included_symbols": list(included_symbols),
            "continuous_replay_window": {
                "start_inclusive": EVALUATION_START.isoformat(),
                "end_exclusive": EVALUATION_END.isoformat(),
                "month_or_fold_restarts": 0,
            },
            "candidate_batch_sha256": winner_batch_hash,
            "preregistration": prereg_identity,
            "execution_lock": {
                "path": CANONICAL_LOCK_RELATIVE,
                "bytes": lock_bytes,
                "sha256": lock_sha_pre,
            },
            "primary_report": primary_report_identity,
            "baseline_result_identity": baseline_identity,
            "policy": policy_payload,
            "policy_sha256": _payload_sha256(policy_payload),
            "scenario_config": scenario_payload,
            "scenario_config_sha256": _payload_sha256(scenario_payload),
            "candidate_signal_stream": {
                "source_candidate_id": FAIR_BASELINE_CANDIDATE_ID,
                "cell_candidate_id": winner,
                "excluded_symbol": excluded_symbol,
                "baseline_decision_ledger_sha256": baseline_decisions_hash,
                "baseline_intents_sha256": baseline_intents_hash,
                "adapter_decisions": adapter_decisions,
                "adapter_rejections": adapter_rejections,
                "source_intents": source_intent_payload,
                "engine_proxy_intents": proxy_payload,
                "engine_proxy_intents_sha256": proxy_hash,
                "excluded_source_intent_count": len(winner_batch.intents)
                - len(loso_source_intents),
            },
            "loso_input_hashes": {
                "included_engine_frames_sha256_by_symbol": {
                    symbol: frame_hashes[symbol] for symbol in included_symbols
                },
                "funding_events_sha256": loso_funding_hash,
                "daily_returns_sha256": loso_returns_hash,
            },
            "engine_candidate_binding": {
                "engine_validation_identity": FAIR_BASELINE_CANDIDATE_ID,
                "serialized_ledger_identity": winner,
                "binding_method": "DETERMINISTIC_POST_ENGINE_CANDIDATE_ID_REBIND",
                "candidate_id_rebinding_count": rebound_count,
                "zero_rebinding_allowed_only_when_engine_has_no_candidate_ledger_rows": True,
                "raw_engine_result_sha256": _payload_sha256(raw_result),
            },
            "complete_result": bound_result,
            "complete_result_sha256": _payload_sha256(bound_result),
            "live_or_paper_authorized": False,
        }
        shard_payload_sha = _payload_sha256(shard)
        if not output_created:
            output.mkdir(parents=False, exist_ok=False)
            output_created = True
        safe_symbol = excluded_symbol.replace("/", "_")
        shard_path = output / f"without__{safe_symbol}.json"
        _write_json_atomic(shard_path, shard)
        shard_identities.append(
            {
                "candidate_id": winner,
                "scenario": "H",
                "excluded_symbol": excluded_symbol,
                **_file_identity(shard_path, output),
                "payload_sha256": shard_payload_sha,
            }
        )

    if not output_created or len(shard_identities) != len(PRIMARY_SYMBOLS):
        raise RuntimeError("thirteen true-LOSO shards were not published")
    source_post = _source_provenance(lock, root)
    _assert_source_ready(source_post)
    runtime_post = baseline._critical_runtime_versions(root)
    _, primary_report_identity_post = _primary_report_evidence(
        primary_report_path,
        root=root,
        prereg=prereg,
        expected_bytes=primary_report_identity["bytes"],
        expected_sha256=primary_report_identity["sha256"],
        recompute=False,
    )
    prereg_identity_post = _identity(
        prereg_path,
        root=root,
        relative=CANONICAL_PREREG_RELATIVE,
        expected=_mapping(lock["preregistration"], "locked preregistration"),
    )
    baseline_identity_post = _identity(
        root / CANONICAL_BASELINE_IDENTITY_RELATIVE,
        root=root,
        relative=CANONICAL_BASELINE_IDENTITY_RELATIVE,
        expected=baseline_contract,
    )
    baseline_evidence_post = _baseline_identity_evidence(
        root / CANONICAL_BASELINE_IDENTITY_RELATIVE,
        root=root,
        prereg=prereg,
        expected_execution_git_commit=str(lock["execution_git_commit"]),
    )
    lineage_post = _verify_lineage(prereg, root)
    verified_post = {
        name: verify_frozen_snapshot(name, snapshots[name], repo_root=root)
        for name in ("market", "funding")
    }
    if source_post != source_pre:
        raise RuntimeError("scoped research source changed during true LOSO")
    if runtime_post != runtime_pre:
        raise RuntimeError("critical runtime changed during true LOSO")
    if sha256_file(lock_path) != lock_sha_pre or lock_path.stat().st_size != lock_bytes:
        raise RuntimeError("execution lock changed during true LOSO")
    if primary_report_identity_post != primary_report_identity:
        raise RuntimeError("primary report changed during true LOSO")
    if prereg_identity_post != prereg_identity:
        raise RuntimeError("V18 preregistration changed during true LOSO")
    if baseline_identity_post != baseline_identity:
        raise RuntimeError("baseline result identity changed during true LOSO")
    if baseline_evidence_post != baseline_evidence_pre:
        raise RuntimeError("baseline raw or report artifact changed during true LOSO")
    if {name: asdict(value) for name, value in lineage_post.items()} != {
        name: asdict(value) for name, value in lineage_pre.items()
    }:
        raise RuntimeError("lineage changed during true LOSO")
    if {name: asdict(value) for name, value in verified_post.items()} != {
        name: asdict(value) for name, value in verified_pre.items()
    }:
        raise RuntimeError("snapshot identity changed during true LOSO")

    manifest = {
        "schema_version": LOSO_MANIFEST_SCHEMA,
        "program_schema_version": PROGRAM_SCHEMA,
        "status": "COMPLETE",
        "phase": "TRUE_LOSO",
        "evidence_eligible": True,
        "locked_winner": winner,
        "runner_up_fallback_used": False,
        "scenario": "H",
        "excluded_symbol_order": list(PRIMARY_SYMBOLS),
        "preregistration": prereg_identity,
        "execution_lock": {
            "path": CANONICAL_LOCK_RELATIVE,
            "bytes": lock_bytes,
            "sha256": lock_sha_pre,
        },
        "primary_report": primary_report_identity,
        "baseline_result_identity": baseline_identity,
        "baseline_evidence_artifacts": baseline_evidence_pre,
        "runtime_git_commit": source_post["runtime_git_commit"],
        "locked_source_commit": source_post["locked_source_commit"],
        "source_preflight": source_pre,
        "source_postflight": source_post,
        "runtime_preflight": runtime_pre,
        "runtime_postflight": runtime_post,
        "lineage": {name: asdict(value) for name, value in lineage_pre.items()},
        "snapshots": {name: asdict(value) for name, value in verified_pre.items()},
        "input_hashes": {
            "engine_frames_sha256_by_symbol": frame_hashes,
            "funding_events_sha256": funding_hash,
            "daily_returns_sha256": returns_hash,
            "baseline_decisions_sha256": baseline_decisions_hash,
            "baseline_intents_sha256": baseline_intents_hash,
            "locked_winner_batch_sha256": winner_batch_hash,
        },
        "generation_counts": {
            "market_snapshot_loads": 1,
            "funding_snapshot_loads": 1,
            "baseline_signal_generations": 1,
            "candidate_adapter_generations": 1,
            "independent_H_true_loso_replays": len(PRIMARY_SYMBOLS),
        },
        "shards": shard_identities,
        "manifest_published_last": True,
        "historical_feasibility_only": True,
        "live_or_paper_authorized": False,
    }
    _payload_sha256(manifest)
    _write_json_atomic(output / "manifest.json", manifest)
    return manifest


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[3])
    parser.add_argument("--prereg", type=Path)
    parser.add_argument("--execution-lock", type=Path)
    parser.add_argument("--bundle-dir", type=Path)
    parser.add_argument("--phase", choices=("primary", "loso"), default="primary")
    parser.add_argument("--primary-report", type=Path)
    parser.add_argument("--primary-report-bytes", type=int)
    parser.add_argument("--primary-report-sha256")
    parser.add_argument("--dry-plan", action="store_true")
    args = parser.parse_args(argv)
    root = args.repo_root.resolve()
    prereg = args.prereg or root / CANONICAL_PREREG_RELATIVE
    if args.dry_plan:
        print(deterministic_json(dry_plan(prereg, repo_root=root, phase=args.phase)), end="")
        return 0
    if args.execution_lock is None or args.bundle_dir is None:
        parser.error("execute requires --execution-lock and --bundle-dir")
    if args.phase == "loso":
        if args.primary_report is None:
            parser.error("LOSO phase requires --primary-report")
        if (args.primary_report_bytes is None) != (args.primary_report_sha256 is None):
            parser.error("primary report bytes and SHA-256 must be supplied together")
        manifest = run_true_loso_replays(
            prereg,
            execution_lock_path=args.execution_lock,
            primary_report_path=args.primary_report,
            bundle_dir=args.bundle_dir,
            repo_root=root,
            primary_report_bytes=args.primary_report_bytes,
            primary_report_sha256=args.primary_report_sha256,
        )
    else:
        if args.primary_report is not None:
            parser.error("--primary-report is valid only for LOSO phase")
        manifest = run_program(
            prereg,
            execution_lock_path=args.execution_lock,
            bundle_dir=args.bundle_dir,
            repo_root=root,
        )
    print(deterministic_json({"status": "COMPLETE", "manifest": manifest}), end="")
    return 0


__all__ = [
    "CANONICAL_LOCK_RELATIVE",
    "CANONICAL_PREREG_RELATIVE",
    "CELL_ORDER",
    "LOCKED_METRIC_SEMANTICS",
    "LOSO_MANIFEST_SCHEMA",
    "LOSO_SHARD_SCHEMA",
    "MANIFEST_SCHEMA",
    "PROGRAM_SCHEMA",
    "SCENARIO_ORDER",
    "SHARD_SCHEMA",
    "deterministic_json",
    "dry_plan",
    "load_preregistration",
    "main",
    "run_program",
    "run_true_loso_replays",
]


if __name__ == "__main__":
    raise SystemExit(main())
