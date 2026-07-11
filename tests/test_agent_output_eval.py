"""Offline agent-output quality gate acceptance tests."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml

from price_action.lab.agent_output_eval import (
    AgentOutputEvalError,
    EvalConfig,
    evaluate_agent_outputs,
    load_eval_config,
    write_report,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _temp_config(tmp_path: Path, *, inputs: list[str] | None = None) -> EvalConfig:
    (tmp_path / "configs").mkdir(exist_ok=True)
    (tmp_path / "memory" / "researcher" / "hypotheses").mkdir(parents=True, exist_ok=True)
    (tmp_path / "memory" / "researcher" / "backtest_results").mkdir(parents=True, exist_ok=True)
    (tmp_path / "reports" / "research").mkdir(parents=True, exist_ok=True)
    raw = yaml.safe_load(
        (PROJECT_ROOT / "configs" / "agent_output_eval.yaml").read_text(encoding="utf-8")
    )
    raw["inputs"]["paths"] = inputs or []
    raw["report"]["path"] = "reports/autonomy/agent_output_eval.json"
    config_path = tmp_path / "configs" / "agent_output_eval.yaml"
    config_path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    return load_eval_config(config_path, repo_root=tmp_path)


def _valid_text() -> str:
    raw = yaml.safe_load(
        (PROJECT_ROOT / "configs" / "agent_output_eval.yaml").read_text(encoding="utf-8")
    )
    return next(
        item["content"] for item in raw["golden_cases"] if item["id"] == "valid_research_contract"
    )


def _valid_json_text() -> str:
    raw = yaml.safe_load(
        (PROJECT_ROOT / "configs" / "agent_output_eval.yaml").read_text(encoding="utf-8")
    )
    return next(
        item["content"]
        for item in raw["golden_cases"]
        if item["id"] == "valid_json_field_bound_citations"
    )


def _write_input(tmp_path: Path, name: str, content: str) -> str:
    relative = Path("memory") / "researcher" / "hypotheses" / name
    path = tmp_path / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return str(relative)


def _codes(case: dict[str, object]) -> set[str]:
    return {item["code"] for item in case["issues"]}  # type: ignore[index, union-attr]


def test_valid_contract_passes_quality_gate_but_never_authorizes_promotion(
    tmp_path: Path,
) -> None:
    path = _write_input(tmp_path, "valid.md", _valid_text())
    config = _temp_config(tmp_path, inputs=[path])

    report = evaluate_agent_outputs(
        config,
        evaluated_at=datetime(2026, 7, 11, tzinfo=UTC),
    )

    assert report["status"] == "PASS"
    assert report["verdict"] == "QUALITY_GATE_PASS"
    assert report["golden_contract"]["all_cases_match"] is True
    assert report["cases"][0]["status"] == "PASS"
    assert len(report["cases"][0]["fingerprint_sha256"]) == 64
    assert report["quality_gate_only"] is True
    assert report["promotion_authorized"] is False
    assert report["deployment_authorized"] is False
    assert report["live_authorized"] is False
    assert report["order_authorized"] is False
    assert not (tmp_path / "reports" / "autonomy" / "agent_output_eval.json").exists()


def test_no_inputs_is_hold_and_never_fake_green(tmp_path: Path) -> None:
    config = _temp_config(tmp_path)

    report = evaluate_agent_outputs(config, input_paths=[])

    assert report["status"] == "HOLD"
    assert report["verdict"] == "HOLD_NO_INPUTS"
    assert report["aggregate"]["input_count"] == 0
    assert report["aggregate"]["checks"]["has_inputs"] is False


@pytest.mark.parametrize(
    ("mutator", "expected_code"),
    [
        (
            lambda text: text.replace(
                "[SRC-1] `memory/researcher/learning.md` documents",
                "[SRC-1] `memory/researcher/learning.md` documents\nCurve-fit şüphesi yarat.\n",
            ),
            "FORBIDDEN_PHRASE",
        ),
        (
            lambda text: text + "\ndeployment_authorized: true\n",
            "AUTHORITY_BOUNDARY_VIOLATION",
        ),
        (
            lambda text: text.replace(
                "OOS Sharpe is expected to exceed 1.0 across 240 trades. [SRC-1]",
                "OOS Sharpe is expected to exceed 1.0 across 240 trades.",
            ),
            "NUMERIC_CITATION_MISSING",
        ),
        (
            lambda text: text.replace("- `max_dd < 20`", "- better than production"),
            "ACCEPT_GATE_INVALID",
        ),
    ],
)
def test_critical_content_failures_are_fail_closed(
    tmp_path: Path,
    mutator: object,
    expected_code: str,
) -> None:
    modified = mutator(_valid_text())  # type: ignore[operator]
    path = _write_input(tmp_path, "bad.md", modified)
    config = _temp_config(tmp_path, inputs=[path])

    report = evaluate_agent_outputs(config)

    assert report["status"] == "FAIL"
    assert report["cases"][0]["status"] == "FAIL"
    assert expected_code in _codes(report["cases"][0])


def test_malformed_json_is_parse_failure(tmp_path: Path) -> None:
    path = _write_input(tmp_path, "broken.json", '{"metadata": ')
    config = _temp_config(tmp_path, inputs=[path])

    report = evaluate_agent_outputs(config)

    assert report["status"] == "FAIL"
    assert report["aggregate"]["parse_error_count"] == 1
    assert "PARSE_ERROR" in _codes(report["cases"][0])


def test_unresolved_citation_and_bad_typed_metadata_cannot_pass(tmp_path: Path) -> None:
    text = _valid_text()
    text = text.replace("created_at: 2026-07-11T00:00:00Z", "created_at: 2026-07-11T00:00:00")
    text = text.replace("status: PRE_REGISTERED", "status: [PRE_REGISTERED]")
    text = text.replace("confidence: 0.25", "confidence: .nan")
    text = text.replace("240 trades. [SRC-1]", "240 trades. [X]")
    path = _write_input(tmp_path, "unresolved.md", text)
    config = _temp_config(tmp_path, inputs=[path])

    report = evaluate_agent_outputs(config)

    assert report["status"] == "FAIL"
    codes = _codes(report["cases"][0])
    assert "METADATA_SCHEMA_INVALID" in codes
    assert "NUMERIC_CITATION_MISSING" in codes
    errors = report["cases"][0]["checks"]["required_fields"]["schema_errors"]
    assert any("timezone_required" in item for item in errors)
    assert any("status:expected_string" in item for item in errors)
    assert any("confidence" in item for item in errors)
    uncited = report["cases"][0]["checks"]["numeric_citation_binding"]["uncited_claims"]
    assert "X" in uncited[0]["unresolved_ids"]


def test_json_citation_wrong_field_scope_does_not_bind(tmp_path: Path) -> None:
    payload = json.loads(_valid_json_text())
    payload["references"]["SRC-1"]["supports"] = ["rationale and sources"]
    path = _write_input(tmp_path, "wrong-scope.json", json.dumps(payload))
    config = _temp_config(tmp_path, inputs=[path])

    report = evaluate_agent_outputs(config)

    assert report["status"] == "FAIL"
    assert "NUMERIC_CITATION_MISSING" in _codes(report["cases"][0])
    uncited = report["cases"][0]["checks"]["numeric_citation_binding"]["uncited_claims"]
    assert uncited[0]["wrong_scope_ids"] == ["SRC-1"]


def test_duplicate_fingerprint_and_low_novelty_fail_second_case(tmp_path: Path) -> None:
    first = _write_input(tmp_path, "first.md", _valid_text())
    second = _write_input(tmp_path, "second.md", _valid_text())
    config = _temp_config(tmp_path, inputs=[first, second])

    report = evaluate_agent_outputs(config)

    assert report["status"] == "FAIL"
    assert report["cases"][0]["status"] == "PASS"
    assert report["cases"][1]["status"] == "FAIL"
    assert "DUPLICATE_CONTENT" in _codes(report["cases"][1])
    assert report["aggregate"]["duplicate_or_low_novelty_count"] == 1
    assert report["cases"][0]["fingerprint_sha256"] == report["cases"][1]["fingerprint_sha256"]


def test_traversal_and_symlink_inputs_are_not_read(tmp_path: Path) -> None:
    config = _temp_config(tmp_path)
    outside = tmp_path.parent / f"{tmp_path.name}-outside.md"
    outside.write_text(_valid_text(), encoding="utf-8")
    symlink = tmp_path / "memory" / "researcher" / "hypotheses" / "link.md"
    symlink.symlink_to(outside)

    traversal = evaluate_agent_outputs(config, input_paths=["../outside.md"])
    linked = evaluate_agent_outputs(
        config,
        input_paths=["memory/researcher/hypotheses/link.md"],
    )

    assert traversal["status"] == "FAIL"
    assert linked["status"] == "FAIL"
    assert "PARSE_ERROR" in _codes(traversal["cases"][0])
    assert "PARSE_ERROR" in _codes(linked["cases"][0])


def test_missing_input_can_never_be_counted_as_pass(tmp_path: Path) -> None:
    missing = "memory/researcher/hypotheses/does-not-exist.md"
    config = _temp_config(tmp_path, inputs=[missing])

    report = evaluate_agent_outputs(config)

    assert report["status"] == "FAIL"
    assert report["cases"][0]["status"] == "FAIL"
    assert report["aggregate"]["pass_count"] == 0
    assert "PARSE_ERROR" in _codes(report["cases"][0])


def test_input_count_and_byte_limits_fail_before_unbounded_reads(tmp_path: Path) -> None:
    first = _write_input(tmp_path, "first.md", _valid_text())
    second = _write_input(tmp_path, "second.md", _valid_text())
    config = _temp_config(tmp_path)
    raw = yaml.safe_load(config.path.read_text(encoding="utf-8"))
    raw["limits"]["max_inputs"] = 1
    raw["limits"]["max_input_bytes"] = 100
    config.path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    limited = load_eval_config(config.path, repo_root=tmp_path)

    too_many = evaluate_agent_outputs(limited, input_paths=[first, second])
    too_large = evaluate_agent_outputs(limited, input_paths=[first])

    assert too_many["status"] == "FAIL"
    assert too_large["status"] == "FAIL"
    assert "INPUT_COUNT_LIMIT" in too_many["cases"][0]["checks"]["parse"]["errors"][0]
    assert "INPUT_BYTE_LIMIT" in too_large["cases"][0]["checks"]["parse"]["errors"][0]


def test_report_writer_is_atomic_and_restricted_to_report_roots(tmp_path: Path) -> None:
    path = _write_input(tmp_path, "valid.md", _valid_text())
    config = _temp_config(tmp_path, inputs=[path])
    report = evaluate_agent_outputs(
        config,
        evaluated_at=datetime(2026, 7, 11, tzinfo=UTC),
    )

    output = write_report(report, config)

    assert output == tmp_path / "reports" / "autonomy" / "agent_output_eval.json"
    assert (
        json.loads(output.read_text(encoding="utf-8"))["schema_version"] == report["schema_version"]
    )
    assert list(output.parent.glob(f".{output.name}.*")) == []
    with pytest.raises(AgentOutputEvalError, match=r"outside configured allowed roots|escapes"):
        write_report(report, config, path="memory/researcher/hypotheses/not-a-report.json")


def test_report_requires_deterministic_as_of(tmp_path: Path) -> None:
    path = _write_input(tmp_path, "valid.md", _valid_text())
    config = _temp_config(tmp_path, inputs=[path])
    report = evaluate_agent_outputs(config)

    with pytest.raises(AgentOutputEvalError, match="deterministic as-of"):
        write_report(report, config)


def test_deterministic_report_bytes_and_content_provenance(tmp_path: Path) -> None:
    path = _write_input(tmp_path, "valid.md", _valid_text())
    config = _temp_config(tmp_path, inputs=[path])
    as_of = datetime(2026, 7, 11, tzinfo=UTC)
    input_bytes = (tmp_path / path).read_bytes()

    first = evaluate_agent_outputs(config, evaluated_at=as_of)
    # The validated config object owns immutable provenance. Evaluation must
    # not silently reread changed bytes from its original path.
    config.path.write_text("tampered after validated load\n", encoding="utf-8")
    second = evaluate_agent_outputs(config, evaluated_at=as_of)
    first_path = write_report(first, config, path="reports/autonomy/first.json")
    second_path = write_report(second, config, path="reports/autonomy/second.json")

    assert first == second
    assert first_path.read_bytes() == second_path.read_bytes()
    assert first["config_sha256"] == config.content_sha256
    assert first["config_size_bytes"] == config.content_size_bytes
    assert first["cases"][0]["input_sha256"] == hashlib.sha256(input_bytes).hexdigest()
    assert first["cases"][0]["input_size_bytes"] == len(input_bytes)


def test_config_bytes_are_read_once_at_load(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _temp_config(tmp_path)
    original_read_bytes = Path.read_bytes
    reads = 0

    def counted(path: Path) -> bytes:
        nonlocal reads
        if path == config.path:
            reads += 1
        return original_read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", counted)
    loaded = load_eval_config(config.path, repo_root=tmp_path)

    assert reads == 1
    assert len(loaded.content_sha256) == 64


@pytest.mark.parametrize(
    "mutator",
    [
        lambda raw: raw["thresholds"].update({"min_case_score": 0.0}),
        lambda raw: raw["thresholds"].update({"min_aggregate_score": 0.0}),
        lambda raw: raw["thresholds"].update({"max_parse_errors": 1}),
        lambda raw: raw["thresholds"].update({"critical_checks": []}),
        lambda raw: raw["golden_cases"][0].update({"expected_status": "FAIL"}),
        lambda raw: raw["golden_cases"][0].update({"content": "tampered"}),
    ],
)
def test_config_downgrade_or_golden_tampering_is_rejected_at_load(
    tmp_path: Path, mutator: object
) -> None:
    config = _temp_config(tmp_path)
    raw = yaml.safe_load(config.path.read_text(encoding="utf-8"))
    mutator(raw)  # type: ignore[operator]
    config.path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")

    with pytest.raises(AgentOutputEvalError):
        load_eval_config(config.path, repo_root=tmp_path)


def test_unsafe_config_cannot_enable_live_or_promotion(tmp_path: Path) -> None:
    config = _temp_config(tmp_path)
    raw = yaml.safe_load(config.path.read_text(encoding="utf-8"))
    raw["safety"]["promotion_authorized"] = True
    config.path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")

    with pytest.raises(AgentOutputEvalError, match="promotion_authorized"):
        load_eval_config(config.path, repo_root=tmp_path)


@pytest.mark.subprocess
def test_cli_no_inputs_returns_nonzero_hold_without_writing_report() -> None:
    report_path = PROJECT_ROOT / "reports" / "autonomy" / "agent_output_eval.json"
    before = report_path.read_bytes() if report_path.exists() else None
    completed = subprocess.run(
        [
            sys.executable,
            str(PROJECT_ROOT / "scripts" / "agent_output_eval.py"),
            "--no-inputs",
            "--no-report",
            "--as-of",
            "2026-07-11T00:00:00Z",
        ],
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    payload = json.loads(completed.stdout)
    assert completed.returncode != 0
    assert payload["status"] == "HOLD"
    assert payload["verdict"] == "HOLD_NO_INPUTS"
    after = report_path.read_bytes() if report_path.exists() else None
    assert after == before


def test_configured_real_memory_dry_run_is_read_only() -> None:
    config = load_eval_config(
        PROJECT_ROOT / "configs" / "agent_output_eval.yaml",
        repo_root=PROJECT_ROOT,
    )
    source = PROJECT_ROOT / config.raw["inputs"]["paths"][0]
    before = source.read_bytes()

    report = evaluate_agent_outputs(
        config,
        evaluated_at=datetime(2026, 7, 11, tzinfo=UTC),
    )

    assert report["aggregate"]["input_count"] == 1
    assert report["promotion_authorized"] is False
    assert source.read_bytes() == before


def test_harness_source_has_no_llm_network_or_order_surface() -> None:
    source = (PROJECT_ROOT / "src" / "price_action" / "lab" / "agent_output_eval.py").read_text(
        encoding="utf-8"
    )
    forbidden = (
        "import requests",
        "import httpx",
        "import ccxt",
        "import socket",
        "openai",
        "anthropic",
        "create_order",
        "place_order",
        "deployment_authorized = true",
        "promotion_authorized = true",
    )
    lowered = source.lower()
    assert all(token not in lowered for token in forbidden)
