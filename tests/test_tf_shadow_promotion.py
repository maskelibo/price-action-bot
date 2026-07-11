"""FAZ-3/4: fail-closed TF evidence → signal-only shadow spec wiring."""

from __future__ import annotations

import hashlib
import json
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

import duckdb
import pytest
import yaml

from price_action.lab.tf_independent_oos import evaluate_preregistration
from price_action.lab.tf_shadow_promotion import (
    EVIDENCE_SCHEMA,
    EvidenceRejectedError,
    promote_evidence,
    scan_evidence_directory,
    validate_strategy_capabilities,
)
from price_action.orchestrator import scheduler as scheduler_module
from price_action.orchestrator.scheduler import _RESEARCH_AUTOPILOT_JOBS, JOB_TABLE
from tests.test_tf_oos_testkit import AS_OF, make_canonical_tf_repo

pytestmark = pytest.mark.subprocess

_STRATEGY_SOURCE = (
    "from price_action.contracts import Signal\n"
    "from price_action.strategies.base import Strategy\n\n"
    "class EngulfingContinuationStrategy(Strategy):\n"
    "    def prepare_features(self, frame):\n"
    "        return frame\n\n"
    "    def generate_signals(self, frame):\n"
    "        return []\n"
)
_EVALUATOR_SOURCE = "# trusted independent OOS evaluator fixture\n"


def _authorized_payload(
    *,
    generated_at: str = "2025-01-02T03:04:05.000006+00:00",
    strategy: str = "engulfing_continuation",
    candidate_tf: str = "30m",
    baseline_tf: str = "15m",
) -> dict:
    return {
        "schema_version": EVIDENCE_SCHEMA,
        "generated_at": generated_at,
        "verdict": "PROMOTION_AUTHORIZED",
        "evidence_class": "INDEPENDENT_OOS",
        "independent_oos": True,
        "deployment_authorized": True,
        "strategy": strategy,
        "authorization": {
            "scope": "SIGNAL_ONLY_SHADOW",
            "live_order_authorized": False,
        },
        "evaluation_protocol": {
            "pre_registered": True,
            "selection_data_excluded": True,
            "holdout_unseen_until_final": True,
            "selection_cutoff": "2023-12-31T23:59:59+00:00",
            "oos_start": "2024-01-01T00:00:00+00:00",
            "oos_end": "2024-12-31T23:59:59+00:00",
        },
        "evaluator": {
            "path": "scripts/tf_independent_oos_runner.py",
            "code_sha256": hashlib.sha256(_EVALUATOR_SOURCE.encode("utf-8")).hexdigest(),
        },
        "inputs": {
            "candidate_tf": candidate_tf,
            "baseline_tf": baseline_tf,
            "candidate_pool": {"sha256": "a" * 64},
            "baseline_pool": {"sha256": "b" * 64},
            "strategy_module": {
                "path": f"src/price_action/strategies/{strategy}.py",
                "sha256": hashlib.sha256(_STRATEGY_SOURCE.encode("utf-8")).hexdigest(),
            },
        },
        "data_quality": {"valid": True, "errors": []},
        "candidate": {"tf": candidate_tf, "oos": {"n_trades": 250}},
        "baseline": {"tf": baseline_tf, "oos": {"n_trades": 210}},
        "gates": [
            {"name": "independent_holdout_expectancy", "passed": True},
            {"name": "walk_forward", "passed": True},
            {"name": "adversarial", "passed": True},
        ],
        "failed_gates": [],
    }


def _write_content_addressed(evidence_dir: Path, payload: dict) -> Path:
    evidence_dir.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(payload, indent=2, sort_keys=True).encode("utf-8") + b"\n"
    sha = hashlib.sha256(raw).hexdigest()
    stamp = payload["generated_at"].replace("-", "").replace(":", "")
    stamp = stamp.replace("+0000", "Z")
    name = (
        f"{payload['strategy']}-{payload['inputs']['candidate_tf']}-independent-oos-"
        f"{stamp}-{sha[:12]}.json"
    )
    path = evidence_dir / name
    path.write_bytes(raw)
    return path


def _repo(tmp_path: Path) -> tuple[Path, Path]:
    root = tmp_path / "repo"
    strategy_module = root / "src" / "price_action" / "strategies" / "engulfing_continuation.py"
    strategy_module.parent.mkdir(parents=True)
    strategy_module.write_text(_STRATEGY_SOURCE, encoding="utf-8")
    evaluator = root / "scripts" / "tf_independent_oos_runner.py"
    evaluator.parent.mkdir(parents=True)
    evaluator.write_text(_EVALUATOR_SOURCE, encoding="utf-8")
    evidence_dir = root / "reports" / "tf_robustness"
    evidence_dir.mkdir(parents=True)
    queue = root / "memory" / "researcher" / "deploy_queue.json"
    queue.parent.mkdir(parents=True)
    queue.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "status": "SUPERSEDED",
                "candidates": [{"id": "legacy", "status": "SUPERSEDED"}],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return root, evidence_dir


def test_authorized_artifact_creates_only_signal_shadow_assets(tmp_path: Path) -> None:
    fixture = make_canonical_tf_repo(tmp_path, strategy_source=_STRATEGY_SOURCE)
    root, evidence = fixture.root, fixture.evidence

    result = promote_evidence(evidence, repo_root=root)
    evidence_payload = json.loads(evidence.read_text(encoding="utf-8"))

    assert result["status"] == "PROMOTED_TO_SIGNAL_ONLY_SPEC"
    assert result["candidate_id"].endswith(
        evidence_payload["producer"]["payload_sha256"][:12]
    )
    assert result["runtime_started"] is False
    assert result["exchange_order_path_enabled"] is False
    assert all(result["created"].values())

    config_path = root / result["paths"]["config"]
    hypothesis_path = root / result["paths"]["hypothesis"]
    manifest_path = root / result["paths"]["manifest"]
    journal_path = root / result["paths"]["journal"]
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert config["mode"] == {
        "run_mode": "shadow",
        "signal_only": True,
        "sim_only": True,
    }
    assert config["exchange"]["enabled"] is False
    assert config["exchange"]["order_submit_allowed"] is False
    assert config["runtime"]["auto_start"] is False
    assert manifest["runtime"]["state"] == "SPEC_READY_NOT_RUNNING"
    assert manifest["safety"]["live_order_authorized"] is False
    assert hypothesis_path.name.startswith("_approved-shadow-")

    con = duckdb.connect(str(journal_path), read_only=True)
    try:
        metadata = dict(con.execute("SELECT key, value FROM shadow_metadata").fetchall())
        tables = {
            row[0]
            for row in con.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_schema='main'"
            ).fetchall()
        }
    finally:
        con.close()
    assert metadata["signal_only"] == "true"
    assert metadata["exchange_enabled"] == "false"
    assert tables == {"shadow_metadata", "shadow_scans", "shadow_signals"}

    queue = json.loads(
        (root / "memory" / "researcher" / "deploy_queue.json").read_text(encoding="utf-8")
    )
    assert queue["status"] == "SUPERSEDED"  # legacy rows are never reactivated
    assert queue["candidates"] == [{"id": "legacy", "status": "SUPERSEDED"}]
    shadow_rows = queue["tf_signal_shadow"]["candidates"]
    assert len(shadow_rows) == 1
    assert shadow_rows[0]["safety"]["auto_start"] is False
    assert shadow_rows[0]["safety"]["exchange_enabled"] is False

    assert not (root / "ops").exists()
    assert not list(root.rglob("*.plist"))
    assert not list(root.rglob("run_*.sh"))


def test_promotion_is_byte_idempotent_and_queue_deduplicated(tmp_path: Path) -> None:
    fixture = make_canonical_tf_repo(tmp_path, strategy_source=_STRATEGY_SOURCE)
    root, evidence = fixture.root, fixture.evidence
    first = promote_evidence(evidence, repo_root=root)
    tracked = {
        key: (root / rel).read_bytes()
        for key, rel in first["paths"].items()
        if key != "deploy_queue"
    }
    queue_before = (root / first["paths"]["deploy_queue"]).read_bytes()

    second = promote_evidence(evidence, repo_root=root)

    assert second["candidate_id"] == first["candidate_id"]
    assert second["status"] == "ALREADY_PROMOTED"
    assert not any(second["created"].values())
    assert {key: (root / first["paths"][key]).read_bytes() for key in tracked} == tracked
    assert (root / first["paths"]["deploy_queue"]).read_bytes() == queue_before
    queue = json.loads(queue_before)
    assert len(queue["tf_signal_shadow"]["candidates"]) == 1


def test_descriptive_or_raw_candidate_cannot_promote(tmp_path: Path) -> None:
    root, evidence_dir = _repo(tmp_path)
    payload = _authorized_payload()
    payload.update(
        {
            "schema_version": "tf-robustness-v2",
            "verdict": "DESCRIPTIVE_SCREEN_PASS",
            "evidence_class": "DESCRIPTIVE_REUSED_HISTORY",
            "independent_oos": False,
            "deployment_authorized": False,
        }
    )
    _write_content_addressed(evidence_dir, payload)

    report = scan_evidence_directory(evidence_dir=evidence_dir, repo_root=root)

    assert report["counts"] == {
        "scanned": 1,
        "promoted": 0,
        "already_promoted": 0,
        "repaired": 0,
        "rejected": 1,
        "conflicts": 0,
        "errors": 0,
    }
    errors = " ".join(report["artifacts"][0]["errors"])
    assert "tf-independent-oos-v2" in errors
    assert "PROMOTION_AUTHORIZED" in errors
    assert "independent_oos" in errors
    assert "deployment_authorized" in errors
    assert not (root / "configs" / "shadow").exists()
    assert not (root / "memory" / "researcher" / "shadow_specs").exists()


def test_string_booleans_fail_closed(tmp_path: Path) -> None:
    root, evidence_dir = _repo(tmp_path)
    payload = _authorized_payload()
    payload["independent_oos"] = "true"
    payload["deployment_authorized"] = 1
    payload["gates"][0]["passed"] = "true"
    _write_content_addressed(evidence_dir, payload)

    report = scan_evidence_directory(evidence_dir=evidence_dir, repo_root=root)

    assert report["counts"]["promoted"] == 0
    assert report["counts"]["rejected"] == 1
    errors = " ".join(report["artifacts"][0]["errors"])
    assert "boolean true" in errors
    assert "every gate" in errors


def test_hash_shaped_v2_evidence_without_canonical_preregistration_cannot_promote(
    tmp_path: Path,
) -> None:
    root, evidence_dir = _repo(tmp_path)
    _write_content_addressed(evidence_dir, _authorized_payload())

    report = scan_evidence_directory(evidence_dir=evidence_dir, repo_root=root)

    assert report["counts"]["promoted"] == 0
    assert report["counts"]["rejected"] == 1
    errors = " ".join(report["artifacts"][0]["errors"])
    assert "preregistration" in errors
    assert "canonical producer receipt" in errors
    assert not (root / "configs/shadow").exists()


def test_content_tamper_breaks_immutable_identity(tmp_path: Path) -> None:
    fixture = make_canonical_tf_repo(tmp_path, strategy_source=_STRATEGY_SOURCE)
    root, evidence_dir, evidence = fixture.root, fixture.evidence_dir, fixture.evidence
    evidence.write_bytes(evidence.read_bytes() + b" \n")

    report = scan_evidence_directory(evidence_dir=evidence_dir, repo_root=root)

    assert report["counts"]["promoted"] == 0
    assert report["counts"]["rejected"] == 1
    assert "filename sha12 does not match" in " ".join(report["artifacts"][0]["errors"])
    assert not (root / "configs" / "shadow").exists()


def test_noncanonical_semantic_clone_cannot_create_a_second_candidate(tmp_path: Path) -> None:
    fixture = make_canonical_tf_repo(tmp_path, strategy_source=_STRATEGY_SOURCE)
    payload = json.loads(fixture.evidence.read_text(encoding="utf-8"))
    clone_raw = (
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n"
    ).encode("utf-8")
    clone_sha = hashlib.sha256(clone_raw).hexdigest()
    stamp = AS_OF.strftime("%Y%m%dT%H%M%S.%fZ")
    clone = fixture.evidence_dir / (
        f"{payload['strategy']}-{payload['inputs']['candidate_tf']}-independent-oos-"
        f"{stamp}-{clone_sha[:12]}.json"
    )
    clone.write_bytes(clone_raw)

    report = scan_evidence_directory(
        evidence_dir=fixture.evidence_dir,
        repo_root=fixture.root,
    )

    assert report["counts"]["scanned"] == 2
    assert report["counts"]["promoted"] == 1
    assert report["counts"]["rejected"] == 1
    rejected = next(item for item in report["artifacts"] if item["status"] == "REJECTED")
    assert "canonical producer serialization" in " ".join(rejected["errors"])
    assert len(list((fixture.root / "configs/shadow").glob("*.yaml"))) == 1


def test_local_strategy_code_must_match_independent_oos_identity(tmp_path: Path) -> None:
    fixture = make_canonical_tf_repo(tmp_path, strategy_source=_STRATEGY_SOURCE)
    root, evidence_dir = fixture.root, fixture.evidence_dir
    module = root / "src" / "price_action" / "strategies" / "engulfing_continuation.py"
    module.write_text(_STRATEGY_SOURCE + "\n# untested drift\n", encoding="utf-8")

    report = scan_evidence_directory(evidence_dir=evidence_dir, repo_root=root)

    assert report["counts"]["promoted"] == 0
    assert report["counts"]["rejected"] == 1
    assert "strategy module identity changed" in " ".join(report["artifacts"][0]["errors"])
    assert not (root / "configs" / "shadow").exists()


def test_protocol_or_evaluator_module_drift_breaks_full_evidence_chain(tmp_path: Path) -> None:
    fixture = make_canonical_tf_repo(tmp_path, strategy_source=_STRATEGY_SOURCE)
    module = fixture.root / "src/price_action/lab/tf_independent_oos.py"
    module.write_text(module.read_text() + "# drift\n", encoding="utf-8")

    report = scan_evidence_directory(
        evidence_dir=fixture.evidence_dir,
        repo_root=fixture.root,
    )
    assert report["counts"]["rejected"] == 1
    assert "evaluator identity changed" in " ".join(report["artifacts"][0]["errors"])

    # A fresh fixture isolates the independent protocol-path/content pin.
    second = make_canonical_tf_repo(
        tmp_path / "second",
        strategy_source=_STRATEGY_SOURCE,
    )
    protocol = second.root / "configs/tf_oos_protocol.yaml"
    protocol.write_text(protocol.read_text() + "# drift\n", encoding="utf-8")
    report = scan_evidence_directory(evidence_dir=second.evidence_dir, repo_root=second.root)
    assert report["counts"]["rejected"] == 1
    assert "protocol content hash changed" in " ".join(report["artifacts"][0]["errors"])


def test_non_pure_allowlisted_strategy_source_is_rejected_before_outputs(tmp_path: Path) -> None:
    malicious_source = (
        "import socket\n"
        "from price_action.strategies.base import Strategy\n\n"
        "class EngulfingContinuationStrategy(Strategy):\n"
        "    pass\n"
    )
    fixture = make_canonical_tf_repo(tmp_path, strategy_source=malicious_source)

    report = scan_evidence_directory(
        evidence_dir=fixture.evidence_dir,
        repo_root=fixture.root,
    )

    assert report["counts"]["promoted"] == 0
    assert report["counts"]["rejected"] == 1
    assert "outside capability allowlist: socket" in " ".join(report["artifacts"][0]["errors"])
    assert not (fixture.root / "configs/shadow").exists()


def test_all_four_reviewed_strategy_modules_satisfy_pure_capability_contract() -> None:
    root = Path(__file__).resolve().parents[1]
    for strategy in (
        "vsa_climax_test",
        "brooks_failed_breakout",
        "anchored_vwap_reversal",
        "engulfing_continuation",
    ):
        validate_strategy_capabilities(
            root / "src/price_action/strategies" / f"{strategy}.py",
            strategy,
        )


@pytest.mark.parametrize(
    "forbidden_expression",
    [
        "pd.read_csv('secret')",
        "pd.read_json('secret')",
        "pd.read_parquet('secret')",
        "np.load('secret')",
        "np.loadtxt('secret')",
        "np.genfromtxt('secret')",
        "np.fromfile('secret')",
        "np.memmap('secret')",
        "candidate.read_text()",
        "candidate.read_bytes()",
    ],
)
def test_strategy_static_policy_rejects_file_read_surfaces(
    tmp_path: Path,
    forbidden_expression: str,
) -> None:
    module = tmp_path / "engulfing_continuation.py"
    module.write_text(
        "import numpy as np\n"
        "import pandas as pd\n"
        "from price_action.strategies.base import Strategy\n\n"
        "class EngulfingContinuationStrategy(Strategy):\n"
        "    def probe(self, candidate):\n"
        f"        return {forbidden_expression}\n",
        encoding="utf-8",
    )

    with pytest.raises(EvidenceRejectedError, match="forbidden"):
        validate_strategy_capabilities(module, "engulfing_continuation")


@pytest.mark.parametrize(
    ("import_line", "call_name"),
    [
        ("from pandas import read_csv as reader", "reader('secret')"),
        ("from numpy import load as loader", "loader('secret')"),
    ],
)
def test_strategy_static_policy_rejects_direct_reader_import_aliases(
    tmp_path: Path,
    import_line: str,
    call_name: str,
) -> None:
    module = tmp_path / "engulfing_continuation.py"
    module.write_text(
        f"{import_line}\n"
        "from price_action.strategies.base import Strategy\n\n"
        "class EngulfingContinuationStrategy(Strategy):\n"
        "    def probe(self):\n"
        f"        return {call_name}\n",
        encoding="utf-8",
    )

    with pytest.raises(EvidenceRejectedError, match="forbidden"):
        validate_strategy_capabilities(module, "engulfing_continuation")


def test_second_active_strategy_tf_slot_is_rejected_before_outputs(tmp_path: Path) -> None:
    fixture = make_canonical_tf_repo(tmp_path, strategy_source=_STRATEGY_SOURCE)
    root, evidence_dir, first = fixture.root, fixture.evidence_dir, fixture.evidence
    first_result = promote_evidence(first, repo_root=root)
    queue_path = root / "memory/researcher/deploy_queue.json"
    queue = json.loads(queue_path.read_text(encoding="utf-8"))
    row = queue["tf_signal_shadow"]["candidates"][0]
    row["status"] = "SHADOW_ACTIVE_AUTHORIZED"
    queue_path.write_text(json.dumps(queue, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    evaluate_preregistration(
        preregistration_path=fixture.preregistration,
        repo_root=root,
        evidence_dir=evidence_dir,
        status_dir=root / "reports/tf_oos/status",
        as_of=AS_OF + timedelta(days=1),
    )
    report = scan_evidence_directory(evidence_dir=evidence_dir, repo_root=root)

    assert report["counts"]["promoted"] == 0
    assert report["counts"]["already_promoted"] == 1
    assert report["counts"]["conflicts"] == 1
    conflict = next(row for row in report["artifacts"] if row["status"] == "CONFLICT")
    assert "active signal-only shadow slot" in conflict["errors"][0]
    assert len(list((root / "configs" / "shadow").glob("*.yaml"))) == 1
    assert len(list((root / "data" / "shadow").glob("*.duckdb"))) == 1
    assert (root / first_result["paths"]["manifest"]).exists()


def test_scheduler_wires_promotion_only_after_oos_completion() -> None:
    jobs = {job_id: expression for job_id, kind, expression, _func in JOB_TABLE if kind == "cron"}

    assert jobs["tf_exploration_chunk"] == "30 4 * * *"
    assert jobs["tf_independent_oos"] == "40 4 * * *"
    # Promotion is invoked by the OOS coroutine after evaluation completes;
    # an independent wall-clock cron could overtake a slow OOS run.
    assert "tf_shadow_promotion" not in jobs
    assert "tf_independent_oos" not in _RESEARCH_AUTOPILOT_JOBS


def test_scheduler_explores_all_canonical_pool_timeframes(tmp_path: Path, monkeypatch) -> None:
    import scripts.tf_exploration_runner as exploration_module

    import price_action.settings as settings_module

    reports_dir = tmp_path / "reports"
    captured: dict = {}

    def fake_explore_tf(*, strategy, tf_list, pool_paths):
        captured.update(
            strategy=strategy,
            tf_list=tf_list,
            pool_paths=pool_paths,
        )
        return {"best_tf": "30m", "recommendation": "CANDIDATE 30m"}

    monkeypatch.setattr(
        settings_module,
        "get_settings",
        lambda: SimpleNamespace(reports_dir=reports_dir),
    )
    monkeypatch.setattr(exploration_module, "explore_tf", fake_explore_tf)
    monkeypatch.setattr(exploration_module, "render_markdown", lambda _result: "safe report\n")

    scheduler_module._run_tf_exploration_chunk_sync()

    assert captured["strategy"] in {
        "vsa_climax_test",
        "brooks_failed_breakout",
        "anchored_vwap_reversal",
        "engulfing_continuation",
    }
    assert captured["tf_list"] == ["5m", "15m", "30m", "1h", "4h"]
    assert set(captured["pool_paths"]) == {"5m", "15m", "30m", "1h", "4h"}
    assert len(list((reports_dir / "tf_exploration").glob("*.md"))) == 1
