"""Independent-OOS producer tests use only synthetic local pool artifacts."""

from __future__ import annotations

import hashlib
import json
import os
import pickle
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

import price_action.lab.tf_independent_oos as oos_module
from price_action.lab.tf_independent_oos import (
    EVIDENCE_SCHEMA,
    OOSContractError,
    OOSProtocol,
    build_pool_from_replay,
    create_preregistration,
    evaluate_preregistration,
    record_pool_provenance,
    validate_preregistration,
)
from price_action.lab.tf_shadow_promotion import validate_evidence
from price_action.orchestrator.scheduler import _RESEARCH_AUTOPILOT_JOBS, JOB_TABLE
from tests.test_tf_oos_testkit import _BUILDER_SOURCE

pytestmark = pytest.mark.subprocess

STRATEGY = "synthetic_edge"
CREATED_AT = datetime(2024, 1, 10, tzinfo=UTC)
OOS_START = datetime(2024, 1, 11, tzinfo=UTC)
AS_OF = datetime(2025, 1, 20, tzinfo=UTC)


def test_scheduler_keeps_prospective_gate_live_and_removes_racy_promotion_cron() -> None:
    jobs = {job_id: expr for job_id, kind, expr, _func in JOB_TABLE if kind == "cron"}
    assert jobs["tf_independent_oos"] == "40 4 * * *"
    assert "tf_shadow_promotion" not in jobs
    assert "tf_independent_oos" not in _RESEARCH_AUTOPILOT_JOBS


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _row(
    timestamp: datetime,
    *,
    symbol: str,
    r_value: float,
    regime: str,
) -> dict:
    return {
        "entry_ts": timestamp,
        "exit_ts": timestamp + timedelta(hours=1),
        "R": r_value,
        "symbol": symbol,
        "strategy": STRATEGY,
        "side": "long",
        "regime": regime,
    }


def _write_pool(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(pickle.dumps(rows))


def _build_pool(root: Path, path: Path) -> None:
    _logical_id, role, parameters, _variant_of, _delta = _provenance_identity(path)
    build_pool_from_replay(
        output_path=path,
        raw_ohlcv_path=root / "data/raw_ohlcv.jsonl",
        builder_path=root / "scripts/synthetic_pool_builder.py",
        repo_root=root,
        strategy=STRATEGY,
        timeframe="15m" if role == "baseline" else "30m",
        parameters=parameters,
    )


def test_pool_loader_rejects_pickle_code_execution(tmp_path: Path) -> None:
    marker = tmp_path / "pickle-executed"

    class Exploit:
        def __reduce__(self):
            return os.system, (f"touch {marker}",)

    pool = tmp_path / "synthetic_30m_pool.pkl"
    pool.write_bytes(pickle.dumps([Exploit()]))

    with pytest.raises(OOSContractError, match="forbidden pool pickle global"):
        oos_module._load_pool(
            pool,
            strategy=STRATEGY,
            timeframe="30m",
            label="malicious",
        )

    assert not marker.exists()


def test_pool_loader_enforces_scalar_string_cap(tmp_path: Path) -> None:
    row = _row(
        datetime(2024, 1, 1, tzinfo=UTC),
        symbol="X" * (16 * 1024 + 1),
        r_value=0.1,
        regime="trend",
    )
    pool = tmp_path / "oversized_30m_pool.pkl"
    pool.write_bytes(pickle.dumps([row], protocol=4))

    with pytest.raises(OOSContractError, match="string cap"):
        oos_module._load_pool(
            pool,
            strategy=STRATEGY,
            timeframe="30m",
            label="oversized",
        )


def _repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    strategy = root / "src" / "price_action" / "strategies" / f"{STRATEGY}.py"
    strategy.parent.mkdir(parents=True)
    strategy.write_text(
        "from price_action.strategies.base import Strategy\n\n"
        "class SyntheticEdgeStrategy(Strategy):\n"
        "    pass\n",
        encoding="utf-8",
    )
    evaluator_module = root / "src" / "price_action" / "lab" / "tf_independent_oos.py"
    evaluator_module.parent.mkdir(parents=True)
    evaluator_module.write_text("# frozen evaluator implementation\n", encoding="utf-8")
    wrapper = root / "scripts" / "tf_independent_oos_runner.py"
    wrapper.parent.mkdir(parents=True)
    wrapper.write_text("# trusted independent OOS evaluator fixture\n", encoding="utf-8")
    protocol = root / "configs" / "tf_oos_protocol.yaml"
    protocol.parent.mkdir(parents=True)
    protocol.write_text(
        (Path(__file__).resolve().parents[1] / "configs" / "tf_oos_protocol.yaml").read_text(
            encoding="utf-8"
        ),
        encoding="utf-8",
    )
    builder = root / "scripts" / "synthetic_pool_builder.py"
    builder.write_text(_BUILDER_SOURCE, encoding="utf-8")
    raw = root / "data" / "raw_ohlcv.jsonl"
    raw.parent.mkdir(parents=True)
    raw.write_bytes(b"")
    return root


def _provenance_identity(path: Path) -> tuple[str, str, dict, str | None, dict]:
    if "candidate" in path.name:
        return (
            "synthetic-edge-30m-primary",
            "candidate",
            {"risk": 1.0, "threshold": 1.0},
            None,
            {},
        )
    if "baseline" in path.name:
        return (
            "synthetic-edge-15m-baseline",
            "baseline",
            {"risk": 1.0, "threshold": 1.0},
            None,
            {},
        )
    value = 0.9 if "variant_1" in path.name else 1.1
    return (
        f"synthetic-edge-30m-threshold-{str(value).replace('.', '-')}",
        "variant",
        {"risk": 1.0, "threshold": value},
        "synthetic-edge-30m-primary",
        {"threshold": {"from": 1.0, "to": value}},
    )


def _attest_pool(root: Path, path: Path, *, generated_at: datetime) -> None:
    logical_id, role, parameters, variant_of, delta = _provenance_identity(path)
    record_pool_provenance(
        pool_path=path,
        raw_ohlcv_path=root / "data" / "raw_ohlcv.jsonl",
        builder_path=root / "scripts" / "synthetic_pool_builder.py",
        repo_root=root,
        strategy=STRATEGY,
        timeframe="15m" if role == "baseline" else "30m",
        logical_id=logical_id,
        parameter_family="synthetic-edge-parameters",
        parameter_role=role,
        parameters=parameters,
        variant_of=variant_of,
        declared_delta=delta,
        generated_at=generated_at,
    )


def _publish_future(
    root: Path,
    rows_by_path: dict[Path, list[dict]],
    *,
    generated_at: datetime = AS_OF - timedelta(days=1),
) -> None:
    raw = root / "data" / "raw_ohlcv.jsonl"
    existing_rows = len(raw.read_text(encoding="utf-8").splitlines())
    candidate_path = next(
        (path for path in rows_by_path if "candidate" in path.name), None
    )
    baseline_path = next(path for path in rows_by_path if "baseline" in path.name)
    variant_low_path = next(
        (path for path in rows_by_path if "variant_1" in path.name), None
    )
    variant_high_path = next(
        (path for path in rows_by_path if "variant_2" in path.name), None
    )

    def values(path: Path | None) -> dict[tuple[datetime, str], float]:
        if path is None:
            return {}
        return {
            (row["entry_ts"], row["symbol"]): float(row["R"])
            for row in rows_by_path[path]
        }

    source_path = candidate_path or variant_low_path or variant_high_path or baseline_path
    candidate_values = values(candidate_path) or values(source_path)
    baseline_values = values(baseline_path)
    low_values = values(variant_low_path)
    high_values = values(variant_high_path)
    records = []
    for row in rows_by_path[source_path][existing_rows:]:
        key = (row["entry_ts"], row["symbol"])
        records.append(
            _raw_record(
                row,
                candidate_r=candidate_values[key],
                baseline_r=baseline_values[key],
                variant_low_r=low_values.get(key, candidate_values[key]),
                variant_high_r=high_values.get(key, candidate_values[key]),
            )
        )
    _append_raw(root, records)
    for path in rows_by_path:
        _build_pool(root, path)
    for path in rows_by_path:
        _attest_pool(root, path, generated_at=generated_at)


def _selection_rows(r_value: float) -> list[dict]:
    return [
        _row(
            datetime(2024, 1, 1, tzinfo=UTC) + timedelta(days=index),
            symbol=f"SYM{index}",
            r_value=r_value,
            regime="trend" if index % 2 else "range",
        )
        for index in range(5)
    ]


def _future_rows(r_value: float) -> list[dict]:
    rows = []
    for day in range(365):
        timestamp = OOS_START + timedelta(days=day, hours=1)
        regime = "trend" if day % 2 else "range"
        for symbol_index in range(5):
            rows.append(
                _row(
                    timestamp + timedelta(minutes=symbol_index),
                    symbol=f"SYM{symbol_index}",
                    r_value=r_value,
                    regime=regime,
                )
            )
    return rows


def _raw_record(
    row: dict,
    *,
    candidate_r: float,
    baseline_r: float,
    variant_low_r: float,
    variant_high_r: float,
) -> dict:
    return {
        "candidate_r": candidate_r,
        "baseline_r": baseline_r,
        "entry_ts": row["entry_ts"].isoformat(),
        "regime": row["regime"],
        "symbol": row["symbol"],
        "variant_high_r": variant_high_r,
        "variant_low_r": variant_low_r,
    }


def _append_raw(root: Path, records: list[dict]) -> None:
    raw = root / "data/raw_ohlcv.jsonl"
    with raw.open("ab") as handle:
        for record in records:
            handle.write(
                (json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n").encode()
            )


def _fixture(
    tmp_path: Path,
    *,
    verdict: str = "DESCRIPTIVE_SCREEN_PASS",
    with_variants: bool = True,
) -> tuple[Path, Path, Path, Path, list[Path], dict[Path, list[dict]]]:
    root = _repo(tmp_path)
    candidate = root / "data" / "synthetic_30m_candidate_pool.pkl"
    baseline = root / "data" / "synthetic_15m_baseline_pool.pkl"
    initial = {
        candidate: _selection_rows(0.25),
        baseline: _selection_rows(0.05),
    }
    variants = []
    if with_variants:
        for index, value in enumerate((0.22, 0.18), start=1):
            path = root / "data" / f"synthetic_30m_variant_{index}_pool.pkl"
            initial[path] = _selection_rows(value)
            variants.append(path)
    _append_raw(
        root,
        [
            _raw_record(
                row,
                candidate_r=0.25,
                baseline_r=0.05,
                variant_low_r=0.22,
                variant_high_r=0.18,
            )
            for row in initial[candidate]
        ],
    )
    for path in initial:
        _build_pool(root, path)
    for path in initial:
        _attest_pool(root, path, generated_at=datetime(2024, 1, 6, 1, tzinfo=UTC))
    discovery = {
        "schema_version": "tf-robustness-v2",
        "generated_at": "2024-01-06T00:00:00+00:00",
        "verdict": verdict,
        "evidence_class": "DESCRIPTIVE_REUSED_HISTORY",
        "independent_oos": False,
        "deployment_authorized": False,
        "strategy": STRATEGY,
        "inputs": {
            "candidate_tf": "30m",
            "baseline_tf": "15m",
            "candidate_pool": {"path": str(candidate), "sha256": _sha(candidate)},
            "baseline_pool": {"path": str(baseline), "sha256": _sha(baseline)},
        },
        "data_quality": {"valid": True, "errors": []},
        "gates": [{"name": "descriptive", "passed": verdict == "DESCRIPTIVE_SCREEN_PASS"}],
        "failed_gates": [] if verdict == "DESCRIPTIVE_SCREEN_PASS" else ["descriptive"],
    }
    discovery_path = root / "reports" / "tf_robustness" / "discovery.json"
    discovery_path.parent.mkdir(parents=True)
    discovery_path.write_text(json.dumps(discovery, sort_keys=True) + "\n", encoding="utf-8")
    return root, discovery_path, candidate, baseline, variants, initial


def _preregister(
    root: Path,
    discovery: Path,
    candidate: Path,
    baseline: Path,
    variants: list[Path],
) -> tuple[dict, Path]:
    return create_preregistration(
        discovery_path=discovery,
        repo_root=root,
        output_dir=root / "reports" / "tf_oos" / "prereg",
        candidate_pool=candidate,
        baseline_pool=baseline,
        variant_pools=variants,
        created_at=CREATED_AT,
        oos_start=OOS_START,
    )


def test_only_passed_descriptive_v2_discovery_can_preregister(tmp_path: Path) -> None:
    root, discovery, candidate, baseline, variants, _ = _fixture(tmp_path, verdict="RED")

    with pytest.raises(OOSContractError, match=r"verdict|failed_gates|gate"):
        _preregister(root, discovery, candidate, baseline, variants)

    assert not (root / "reports" / "tf_oos" / "prereg").exists()


def test_preregistration_is_content_addressed_and_pins_selection(tmp_path: Path) -> None:
    root, discovery, candidate, baseline, variants, _ = _fixture(tmp_path)

    payload, path = _preregister(root, discovery, candidate, baseline, variants)
    validated, artifact_sha = validate_preregistration(path, repo_root=root)

    assert validated == payload
    assert path.name.endswith(f"-{artifact_sha[:12]}.json")
    assert datetime.fromisoformat(payload["selection_cutoff"]) < CREATED_AT < OOS_START
    assert payload["strategy_module"]["sha256"] == _sha(root / payload["strategy_module"]["path"])
    assert payload["evaluator"]["path"] == "scripts/tf_independent_oos_runner.py"
    assert payload["protocol_artifact"]["path"] == "configs/tf_oos_protocol.yaml"
    assert payload["protocol_artifact"]["sha256"] == _sha(root / "configs/tf_oos_protocol.yaml")
    assert payload["pools"]["candidate"]["selection_file_sha256"] == _sha(candidate)
    assert payload["pools"]["candidate"]["provenance"]["selection_entry_count"] == 1
    assert len(payload["pools"]["parameter_variants"]) == 2

    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(OOSContractError, match="hash mismatch"):
        validate_preregistration(path, repo_root=root)


def test_pool_provenance_requires_exact_builder_bytes_and_real_executable(
    tmp_path: Path,
) -> None:
    root, _discovery, candidate, _baseline, _variants, _initial = _fixture(tmp_path)
    rows = _selection_rows(0.25)
    candidate.write_bytes(pickle.dumps(rows, protocol=5))

    with pytest.raises(OOSContractError, match="deterministic hermetic builder replay"):
        _attest_pool(root, candidate, generated_at=datetime(2024, 1, 7, tzinfo=UTC))

    _build_pool(root, candidate)
    builder = root / "scripts/synthetic_pool_builder.py"
    builder.write_text("#!/usr/bin/env python3\n# comment-only fixture\n", encoding="utf-8")
    with pytest.raises(OOSContractError, match="did not create its exact output"):
        _attest_pool(root, candidate, generated_at=datetime(2024, 1, 7, tzinfo=UTC))


def test_frozen_variant_parameters_change_hermetic_builder_output(tmp_path: Path) -> None:
    root, _discovery, _candidate, _baseline, _variants, _initial = _fixture(tmp_path)
    candidate_probe = root / "data/probe_candidate_30m_pool.pkl"
    variant_probe = root / "data/probe_variant_30m_pool.pkl"
    candidate_receipt = build_pool_from_replay(
        output_path=candidate_probe,
        raw_ohlcv_path=root / "data/raw_ohlcv.jsonl",
        builder_path=root / "scripts/synthetic_pool_builder.py",
        repo_root=root,
        strategy=STRATEGY,
        timeframe="30m",
        parameters={"risk": 1.0, "threshold": 1.0},
    )
    variant_receipt = build_pool_from_replay(
        output_path=variant_probe,
        raw_ohlcv_path=root / "data/raw_ohlcv.jsonl",
        builder_path=root / "scripts/synthetic_pool_builder.py",
        repo_root=root,
        strategy=STRATEGY,
        timeframe="30m",
        parameters={"risk": 1.0, "threshold": 0.9},
    )

    assert candidate_receipt["parameters"] != variant_receipt["parameters"]
    assert candidate_receipt["output"]["file_sha256"] != variant_receipt["output"][
        "file_sha256"
    ]
    assert candidate_probe.read_bytes() != variant_probe.read_bytes()


def test_hermetic_builder_cannot_read_unpinned_repository_side_input(
    tmp_path: Path,
) -> None:
    root, _discovery, _candidate, _baseline, _variants, _initial = _fixture(tmp_path)
    secret = root / "unpinned-secret.txt"
    secret.write_text("must not influence a pool\n", encoding="utf-8")
    builder = root / "scripts/synthetic_pool_builder.py"
    builder.write_text(
        _BUILDER_SOURCE.replace(
            "args = parser.parse_args()",
            f"args = parser.parse_args()\nPath({str(secret)!r}).read_text(encoding='utf-8')",
        ),
        encoding="utf-8",
    )

    with pytest.raises(OOSContractError, match="hermetic pool-builder replay exited"):
        build_pool_from_replay(
            output_path=root / "data/side_input_30m_pool.pkl",
            raw_ohlcv_path=root / "data/raw_ohlcv.jsonl",
            builder_path=builder,
            repo_root=root,
            strategy=STRATEGY,
            timeframe="30m",
            parameters={"risk": 1.0, "threshold": 1.0},
        )


def test_missing_parameter_variants_emits_only_hold_status(tmp_path: Path) -> None:
    root, discovery, candidate, baseline, variants, initial = _fixture(
        tmp_path, with_variants=False
    )
    _, prereg = _preregister(root, discovery, candidate, baseline, variants)
    _publish_future(
        root,
        {
            candidate: initial[candidate] + _future_rows(0.30),
            baseline: initial[baseline] + _future_rows(0.05),
        },
    )
    evidence_dir = root / "reports" / "tf_oos" / "evidence"

    status, status_path = evaluate_preregistration(
        preregistration_path=prereg,
        repo_root=root,
        evidence_dir=evidence_dir,
        status_dir=root / "reports" / "tf_oos" / "status",
        as_of=AS_OF,
    )

    assert status["status"] == "HOLD"
    assert "parameter_perturbation" in status["failed_gates"]
    assert status_path.name.endswith(f"-{_sha(status_path)[:12]}.json")
    assert not evidence_dir.exists()


def test_selection_prefix_mutation_fails_closed_to_status(tmp_path: Path) -> None:
    root, discovery, candidate, baseline, variants, initial = _fixture(tmp_path)
    _, prereg = _preregister(root, discovery, candidate, baseline, variants)
    mutated = [dict(row) for row in initial[candidate]]
    mutated[0]["R"] = 99.0
    _publish_future(
        root,
        {
            baseline: initial[baseline] + _future_rows(0.05),
            **{
                path: initial[path] + _future_rows((0.22, 0.18)[index])
                for index, path in enumerate(variants)
            },
        },
    )
    _write_pool(candidate, mutated + _future_rows(0.30))

    status, _ = evaluate_preregistration(
        preregistration_path=prereg,
        repo_root=root,
        evidence_dir=root / "evidence",
        status_dir=root / "status",
        as_of=AS_OF,
    )

    assert status["status"] == "HOLD"
    assert status["data_quality"]["valid"] is False
    assert "frozen selection prefix changed" in status["data_quality"]["errors"][0]
    assert not (root / "evidence").exists()


def test_all_gates_produce_downstream_compatible_signal_only_evidence(
    tmp_path: Path,
) -> None:
    root, discovery, candidate, baseline, variants, initial = _fixture(tmp_path)
    _, prereg = _preregister(root, discovery, candidate, baseline, variants)
    _publish_future(
        root,
        {
            candidate: initial[candidate] + _future_rows(0.30),
            baseline: initial[baseline] + _future_rows(0.05),
            **{
                path: initial[path] + _future_rows((0.22, 0.18)[index])
                for index, path in enumerate(variants)
            },
        },
    )
    evidence_dir = root / "reports" / "tf_oos" / "evidence"

    evidence, path = evaluate_preregistration(
        preregistration_path=prereg,
        repo_root=root,
        evidence_dir=evidence_dir,
        status_dir=root / "reports" / "tf_oos" / "status",
        as_of=AS_OF,
    )
    validated = validate_evidence(path, evidence_dir=evidence_dir, repo_root=root)

    assert evidence["schema_version"] == EVIDENCE_SCHEMA
    assert evidence["verdict"] == "PROMOTION_AUTHORIZED"
    assert evidence["authorization"]["scope"] == "SIGNAL_ONLY_SHADOW"
    assert evidence["authorization"]["live_order_authorized"] is False
    assert evidence["authorization"]["principal_authorization"]["algorithm"] == "Ed25519"
    assert evidence["failed_gates"] == []
    assert evidence["producer"]["contract"] == "TF_CANONICAL_EVALUATOR_V2"
    assert evidence["evaluation_protocol"]["preregistration"]["path"].startswith(
        "reports/tf_oos/prereg/"
    )
    assert all(gate["passed"] is True for gate in evidence["gates"])
    assert validated.sha256 == _sha(path)
    assert evidence["statistical_tests"]["multiple_testing"]["adjusted_p_value"] <= 0.05
    assert not (root / "reports" / "tf_oos" / "status").exists()


def test_old_evidence_survives_a_later_valid_provenance_append(tmp_path: Path) -> None:
    root, discovery, candidate, baseline, variants, initial = _fixture(tmp_path)
    _, prereg = _preregister(root, discovery, candidate, baseline, variants)
    published = {
        candidate: initial[candidate] + _future_rows(0.30),
        baseline: initial[baseline] + _future_rows(0.05),
        **{
            path: initial[path] + _future_rows((0.22, 0.18)[index])
            for index, path in enumerate(variants)
        },
    }
    _publish_future(root, published)
    evidence_dir = root / "reports/tf_oos/evidence"
    evidence, evidence_path = evaluate_preregistration(
        preregistration_path=prereg,
        repo_root=root,
        evidence_dir=evidence_dir,
        status_dir=root / "reports/tf_oos/status",
        as_of=AS_OF,
    )
    historical_hashes = {
        name: evidence["inputs"][name]["sha256"]
        for name in ("candidate_pool", "baseline_pool")
    }

    extra_timestamp = AS_OF + timedelta(hours=1)
    extended = {
        candidate: [
            *published[candidate],
            _row(extra_timestamp, symbol="LATE", r_value=0.30, regime="trend"),
        ],
        baseline: [
            *published[baseline],
            _row(extra_timestamp, symbol="LATE", r_value=0.05, regime="trend"),
        ],
        variants[0]: [
            *published[variants[0]],
            _row(extra_timestamp, symbol="LATE", r_value=0.22, regime="trend"),
        ],
        variants[1]: [
            *published[variants[1]],
            _row(extra_timestamp, symbol="LATE", r_value=0.18, regime="trend"),
        ],
    }
    _publish_future(root, extended, generated_at=AS_OF + timedelta(days=1))

    validated = validate_evidence(evidence_path, evidence_dir=evidence_dir, repo_root=root)

    assert validated.payload == evidence
    assert _sha(candidate) != historical_hashes["candidate_pool"]
    assert _sha(baseline) != historical_hashes["baseline_pool"]


def test_weak_walk_forward_never_writes_promotion_evidence(tmp_path: Path) -> None:
    root, discovery, candidate, baseline, variants, initial = _fixture(tmp_path)
    protocol = OOSProtocol(min_positive_walk_forward_share=1.0)
    _, prereg = create_preregistration(
        discovery_path=discovery,
        repo_root=root,
        output_dir=root / "prereg",
        candidate_pool=candidate,
        baseline_pool=baseline,
        variant_pools=variants,
        protocol=protocol,
        created_at=CREATED_AT,
        oos_start=OOS_START,
    )
    weak = _future_rows(0.30)
    for row in weak[-600:]:
        row["R"] = -1.0
    _publish_future(
        root,
        {
            candidate: initial[candidate] + weak,
            baseline: initial[baseline] + _future_rows(0.05),
            **{
                path: initial[path] + _future_rows((0.22, 0.18)[index])
                for index, path in enumerate(variants)
            },
        },
    )

    status, _ = evaluate_preregistration(
        preregistration_path=prereg,
        repo_root=root,
        evidence_dir=root / "evidence",
        status_dir=root / "status",
        as_of=AS_OF,
    )

    assert status["status"] == "HOLD"
    assert "walk_forward" in status["failed_gates"]
    assert not (root / "evidence").exists()


def test_appended_trade_without_new_provenance_head_is_hold(tmp_path: Path) -> None:
    root, discovery, candidate, baseline, variants, initial = _fixture(tmp_path)
    _, prereg = _preregister(root, discovery, candidate, baseline, variants)
    published = {
        candidate: initial[candidate] + _future_rows(0.30),
        baseline: initial[baseline] + _future_rows(0.05),
        **{
            path: initial[path] + _future_rows((0.22, 0.18)[index])
            for index, path in enumerate(variants)
        },
    }
    _publish_future(root, published)
    fake = _row(
        OOS_START + timedelta(days=364, hours=2),
        symbol="FAKE",
        r_value=99.0,
        regime="trend",
    )
    _write_pool(candidate, [*published[candidate], fake])

    status, _ = evaluate_preregistration(
        preregistration_path=prereg,
        repo_root=root,
        evidence_dir=root / "evidence",
        status_dir=root / "status",
        as_of=AS_OF,
    )

    assert status["status"] == "HOLD"
    assert "without a matching provenance head" in status["data_quality"]["errors"][0]
    assert not (root / "evidence").exists()


def test_raw_ohlcv_prefix_mutation_and_builder_drift_fail_closed(tmp_path: Path) -> None:
    root, discovery, candidate, baseline, variants, initial = _fixture(tmp_path)
    _, prereg = _preregister(root, discovery, candidate, baseline, variants)
    _publish_future(
        root,
        {
            candidate: initial[candidate] + _future_rows(0.30),
            baseline: initial[baseline] + _future_rows(0.05),
            **{
                path: initial[path] + _future_rows((0.22, 0.18)[index])
                for index, path in enumerate(variants)
            },
        },
    )
    raw = root / "data/raw_ohlcv.jsonl"
    raw.write_bytes(b"X" + raw.read_bytes()[1:])

    status, _ = evaluate_preregistration(
        preregistration_path=prereg,
        repo_root=root,
        evidence_dir=root / "evidence",
        status_dir=root / "status-raw",
        as_of=AS_OF,
    )
    assert status["status"] == "HOLD"
    assert "raw OHLCV prefix hash mismatch" in status["data_quality"]["errors"][0]

    # Restore raw content, then independently prove builder identity drift is
    # also a fail-closed input change.
    raw.write_bytes(b"{" + raw.read_bytes()[1:])
    builder = root / "scripts/synthetic_pool_builder.py"
    builder.write_text(builder.read_text() + "# drift\n", encoding="utf-8")
    status, _ = evaluate_preregistration(
        preregistration_path=prereg,
        repo_root=root,
        evidence_dir=root / "evidence",
        status_dir=root / "status-builder",
        as_of=AS_OF,
    )
    assert status["status"] == "HOLD"
    assert "pool builder path/hash differs" in status["data_quality"]["errors"][0]


def test_variant_file_difference_without_parameter_delta_is_rejected(tmp_path: Path) -> None:
    root, discovery, candidate, baseline, variants, _ = _fixture(tmp_path)
    provenance_path = Path(f"{variants[0]}.provenance.json")
    provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
    provenance["parameter_identity"]["parameters"] = {"risk": 1.0, "threshold": 1.0}
    provenance["parameter_identity"]["declared_delta"] = {}
    provenance_path.write_text(
        json.dumps(provenance, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(OOSContractError, match="replay receipt mismatch"):
        _preregister(root, discovery, candidate, baseline, variants)
