from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

from price_action.lab import crypto_15m_v18_report as report


def _prereg() -> dict[str, Any]:
    return {
        "limitations": ["synthetic_test_only"],
        "prospective_evidence_gate": {
            "minimum_calendar_days": 90,
            "minimum_closed_trades": 100,
        },
        "hard_gates": {
            "sample": {
                "pseudo_oos_months": 36,
                "minimum_closed_trades": 360,
                "minimum_long_trades": 60,
                "minimum_short_trades": 60,
                "minimum_active_months": 30,
            },
            "H_return": {
                "trimmed_mean_monthly_pct_min": 10.0,
                "median_monthly_pct_min": 8.0,
                "block_bootstrap_90pct_lower_bound_pct_min": 6.0,
            },
            "H_stability": {
                "negative_months_max": 4,
                "months_below_minus_1pct_max": 3,
                "worst_month_pct_min": -6.0,
            },
            "C2_return": {
                "trimmed_mean_monthly_pct_min": 8.0,
                "median_monthly_pct_min": 6.0,
            },
            "drawdown": {
                "B_max_mtm_pct": 15.0,
                "worse_of_C2_H_max_mtm_pct": 20.0,
            },
            "walk_forward": {
                "positive_folds_min": 5,
                "total_folds": 6,
                "worst_six_month_fold_pct_min": -5.0,
                "H_oos_to_development_trimmed_return_ratio_min": 0.5,
                "H_oos_to_development_drawdown_ratio_max": 1.5,
            },
            "economic_edge": {
                "B_pre_cost_price_pnl_over_execution_cost_min": 1.5,
            },
            "concentration": {
                "best_month_positive_pnl_share_max": 0.15,
                "best_3_month_positive_pnl_share_max": 0.35,
                "mean_after_best_3_months_removed_pct_min": 7.0,
            },
        },
    }


def _passing_metrics() -> dict[str, Any]:
    return {
        "sample": {
            "closed_trades": 500,
            "long_trades": 250,
            "short_trades": 250,
            "active_months": 36,
        },
        "H": {
            "trimmed_mean_monthly_pct": 12.0,
            "median_monthly_pct": 10.0,
            "block_bootstrap_90pct_lower_bound_pct": 8.0,
            "negative_months": 2,
            "months_below_minus_1pct": 1,
            "worst_month_pct": -3.0,
            "max_mtm_drawdown_pct": 10.0,
            "positive_folds": 6,
            "fold_returns_pct": [1.0] * 6,
            "oos_to_development_trimmed_return_ratio": 0.8,
            "oos_to_development_drawdown_ratio": 1.0,
            "best_month_positive_pnl_share": 0.10,
            "best_3_month_positive_pnl_share": 0.30,
            "mean_after_best_3_months_removed_pct": 8.0,
            "top_5pct_trade_removal": {"net_after_top_5pct_removed": 1.0},
            "turnover": {
                "filled_gross_turnover_over_arithmetic_mean_15m_nav": 1.0,
            },
        },
        "C2": {
            "trimmed_mean_monthly_pct": 9.0,
            "median_monthly_pct": 7.0,
            "max_mtm_drawdown_pct": 15.0,
            "long_net_pnl": 1.0,
            "short_net_pnl": 1.0,
        },
        "B": {
            "max_mtm_drawdown_pct": 9.0,
            "pre_cost_price_pnl_over_execution_cost": 2.0,
            "execution_cost": 1.0,
            "funding_cashflow": 0.0,
        },
    }


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, sort_keys=True, allow_nan=False), encoding="utf-8")


def _signal_shard(candidate: str = "C1_VSA_ONLY") -> tuple[dict[str, Any], dict[str, Any]]:
    source = {
        "candidate_id": "v15p2_fair_baseline",
        "decision_ts": "2024-01-01T00:00:00+00:00",
        "entry_ts": "2024-01-01T00:15:00+00:00",
        "symbol": "ETH/USDT",
        "side": "long",
        "strategy": "vsa_climax_test",
        "strategy_rank": 0,
        "pattern_id": "synthetic",
        "confluence_score": 1.0,
        "decision_close": 100.0,
        "entry_reference_price": 100.0,
        "entry_price": 101.0,
        "stop_price": 97.0,
        "take_profit_price": 106.0,
        "decision_stop_distance_pct": 0.03,
        "entry_stop_distance_pct": 4.0 / 101.0,
        "suggested_size_atr": 1.0,
        "signal_manifest_hash": "manifest",
        "config_sha256": "c" * 64,
    }
    decision = {
        "cell_id": candidate,
        "source_intent_index": 0,
        "source_candidate_id": "v15p2_fair_baseline",
        "decision_ts": source["decision_ts"],
        "entry_ts": source["entry_ts"],
        "symbol": source["symbol"],
        "side": source["side"],
        "strategy": source["strategy"],
        "outcome": "accepted",
        "reason": "accepted_no_htf",
    }
    proxy = {
        **source,
        "cell_id": candidate,
        "source_candidate_id": "v15p2_fair_baseline",
        "source_intent_sha256": report._payload_sha256(source),
    }
    decisions = [decision]
    rejections: list[Any] = []
    sources = [source]
    proxies = [proxy]
    stream = {
        "source_candidate_id": "v15p2_fair_baseline",
        "cell_candidate_id": candidate,
        "baseline_decision_ledger_sha256": "d" * 64,
        "baseline_intents_sha256": "e" * 64,
        "adapter_decisions": decisions,
        "adapter_rejections": rejections,
        "source_intents": sources,
        "engine_proxy_intents": proxies,
        "adapter_decisions_sha256": report._payload_sha256(decisions),
        "adapter_rejections_sha256": report._payload_sha256(rejections),
        "source_intents_sha256": report._payload_sha256(sources),
        "engine_proxy_intents_sha256": report._payload_sha256(proxies),
        "reason_counts": {"accepted_no_htf": 1},
    }
    shard = {
        "candidate_batch_sha256": "f" * 64,
        "candidate_signal_stream": stream,
    }
    manifest_hashes = {
        "baseline_decisions_sha256": "d" * 64,
        "baseline_intents_sha256": "e" * 64,
        "candidate_batches_sha256": {candidate: "f" * 64},
    }
    return shard, manifest_hashes


def _loso_signal_fixture(
    *, candidate: str = "C1_VSA_ONLY", excluded_symbol: str = "SOL/USDT"
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    primary_shard, primary_hashes = _signal_shard(candidate)
    primary_summary = report._validate_candidate_signal_stream(
        primary_shard,
        candidate_id=candidate,
        manifest_input_hashes=primary_hashes,
    )
    primary_stream = primary_shard["candidate_signal_stream"]
    proxies = list(primary_stream["engine_proxy_intents"])
    loso_stream = {
        "source_candidate_id": "v15p2_fair_baseline",
        "cell_candidate_id": candidate,
        "excluded_symbol": excluded_symbol,
        "baseline_decision_ledger_sha256": primary_stream["baseline_decision_ledger_sha256"],
        "baseline_intents_sha256": primary_stream["baseline_intents_sha256"],
        "adapter_decisions": primary_stream["adapter_decisions"],
        "adapter_rejections": primary_stream["adapter_rejections"],
        "source_intents": primary_stream["source_intents"],
        "engine_proxy_intents": proxies,
        "engine_proxy_intents_sha256": report._payload_sha256(proxies),
        "excluded_source_intent_count": 0,
    }
    shard = {
        "candidate_batch_sha256": primary_shard["candidate_batch_sha256"],
        "candidate_signal_stream": loso_stream,
    }
    manifest_hashes = {
        "baseline_decisions_sha256": primary_hashes["baseline_decisions_sha256"],
        "baseline_intents_sha256": primary_hashes["baseline_intents_sha256"],
        "locked_winner_batch_sha256": primary_shard["candidate_batch_sha256"],
    }
    return shard, manifest_hashes, primary_summary


def _bundle(tmp_path: Path) -> Path:
    specs: list[dict[str, Any]] = []
    for candidate in report.CANDIDATE_ORDER:
        for scenario in report.SCENARIO_ORDER:
            payload = {
                "schema_version": report.SHARD_SCHEMA,
                "candidate_id": candidate,
                "scenario": scenario,
                "policy": {},
                "complete_result": {},
                "complete_result_sha256": report.baseline_report._canonical_hash({}),
            }
            relative = f"cells/{candidate}/{scenario}.json"
            path = tmp_path / relative
            _write_json(path, payload)
            specs.append(
                {
                    "candidate_id": candidate,
                    "scenario": scenario,
                    "path": relative,
                    "bytes": path.stat().st_size,
                    "sha256": report._file_sha256(path),
                    "payload_sha256": report._payload_sha256(payload),
                }
            )
    manifest = {
        "schema_version": report.MANIFEST_SCHEMA,
        "status": "COMPLETE",
        "candidate_order": list(report.CANDIDATE_ORDER),
        "scenario_order": list(report.SCENARIO_ORDER),
        "shards": specs,
    }
    manifest_path = tmp_path / "manifest.json"
    _write_json(manifest_path, manifest)
    return manifest_path


def test_pre_loso_gates_are_complete_and_fail_closed() -> None:
    passing = report._pre_loso_gates(_passing_metrics(), _prereg())
    assert passing["passed_before_multiple_testing_and_LOSO"] is True
    assert len(passing["checks"]) == 30

    failing_metrics = _passing_metrics()
    failing_metrics["H"]["block_bootstrap_90pct_lower_bound_pct"] = None
    failing = report._pre_loso_gates(failing_metrics, _prereg())
    assert failing["passed_before_multiple_testing_and_LOSO"] is False
    assert failing["checks"]["H.bootstrap_lcb"]["passed"] is False

    zero_direction = _passing_metrics()
    zero_direction["C2"]["long_net_pnl"] = 0.0
    strict = report._pre_loso_gates(zero_direction, _prereg())
    assert strict["checks"]["direction.long"]["comparison"] == "gt"
    assert strict["checks"]["direction.long"]["passed"] is False


def test_top_trade_removal_is_additive_and_uses_ceil_five_percent() -> None:
    episodes = [{"net_pnl": float(value)} for value in range(1, 22)]
    result = report._top_trade_removal(episodes)
    assert result["count"] == 21
    assert result["removed_count"] == 2
    assert result["net_after_top_5pct_removed"] == sum(range(1, 20))


def test_undefined_positive_pnl_shares_serialize_as_null_and_fail_closed() -> None:
    normalized = report._json_safe_monthly_statistics(
        {
            "best_month_positive_pnl_share": float("inf"),
            "best_3_month_positive_pnl_share": float("inf"),
            "trimmed_mean_monthly_pct": -2.0,
        }
    )
    metrics = _passing_metrics()
    metrics["H"].update(normalized)

    gates = report._pre_loso_gates(metrics, _prereg())

    assert normalized == {
        "best_month_positive_pnl_share": None,
        "best_3_month_positive_pnl_share": None,
        "trimmed_mean_monthly_pct": -2.0,
    }
    assert gates["checks"]["concentration.best_month"]["passed"] is False
    assert gates["checks"]["concentration.best_3_months"]["passed"] is False
    assert '"best_month_positive_pnl_share": null' in report.deterministic_json(normalized)


def test_bundle_path_escape_and_symlink_are_rejected(tmp_path: Path) -> None:
    root = tmp_path / "bundle"
    root.mkdir()
    outside = tmp_path / "outside.json"
    outside.write_text("{}", encoding="utf-8")
    with pytest.raises(report.V18ReportContractError, match="escapes"):
        report._safe_bundle_child(root, "../outside.json", name="shard")

    link = root / "link.json"
    link.symlink_to(outside)
    with pytest.raises(report.V18ReportContractError, match="symlink"):
        report._safe_bundle_child(root, "link.json", name="shard")


def test_manifest_must_be_complete_and_exact_4x3(tmp_path: Path) -> None:
    manifest = _bundle(tmp_path)
    payload = report._load_json(manifest, name="manifest")
    payload["status"] = "INCOMPLETE"
    _write_json(manifest, payload)
    with pytest.raises(report.V18ReportContractError, match="not a complete"):
        report.build_primary_report(manifest, prereg=_prereg())

    payload["status"] = "COMPLETE"
    payload["shards"] = payload["shards"][:-1]
    _write_json(manifest, payload)
    with pytest.raises(report.V18ReportContractError, match="exact ordered"):
        report.build_primary_report(manifest, prereg=_prereg())


def test_build_primary_report_verifies_all_shards_and_never_authorizes_deployment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = _bundle(tmp_path)
    validated_calls: list[tuple[str, str]] = []

    monkeypatch.setattr(
        report,
        "_validate_manifest_governance",
        lambda *_args, **_kwargs: {
            "input_hashes": {},
            "expected_policy": {},
            "expected_scenarios": {name: {} for name in report.SCENARIO_ORDER},
            "preregistration": {},
            "execution_lock": {},
            "baseline_result_identity": {},
            "runtime_git_commit": "a" * 40,
            "locked_source_commit": "b" * 40,
        },
    )
    monkeypatch.setattr(
        report,
        "_validate_shard_governance",
        lambda *_args, candidate_id, scenario, **_kwargs: {
            "policy_sha256": "1" * 64,
            "scenario_config_sha256": scenario * 64,
            "signal_stream": {
                "stream_sha256": candidate_id,
                "engine_proxy_intents": [],
                "decision_count": 0,
                "accepted_count": 0,
                "rejected_count": 0,
                "engine_proxy_count": 0,
                "reason_counts": {},
            },
        },
    )

    def fake_validate(
        _shard: Mapping[str, Any], *, candidate_id: str, scenario: str
    ) -> tuple[dict[str, Any], object, dict[str, Any], dict[str, Any]]:
        validated_calls.append((candidate_id, scenario))
        return {}, object(), {"entries": []}, {}

    monkeypatch.setattr(report, "_validate_complete_result", fake_validate)
    monkeypatch.setattr(
        report,
        "_compact_scenario_evidence",
        lambda *_args, scenario, **_kwargs: {"scenario": scenario},
    )
    monkeypatch.setattr(
        report,
        "_candidate_metrics",
        lambda candidate_id, _validated: {
            **_passing_metrics(),
            "candidate_id": candidate_id,
        },
    )

    def fake_multiple(
        candidates: dict[str, Any], **_kwargs: Any
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        for candidate in report.CANDIDATE_ORDER:
            checks = candidates[candidate]["primary_gates"]["checks"]
            checks["multiple.synthetic"] = {
                "value": 1.0,
                "threshold": 1.0,
                "comparison": "eq",
                "passed": True,
            }
            candidates[candidate]["primary_gates"]["passed_before_multiple_testing_and_LOSO"] = True
        return {"status": "OK"}, {"status": "OK"}

    monkeypatch.setattr(report, "_attach_multiple_testing", fake_multiple)
    result = report.build_primary_report(manifest, prereg=_prereg())

    assert validated_calls == [
        (candidate, scenario)
        for candidate in report.CANDIDATE_ORDER
        for scenario in report.SCENARIO_ORDER
    ]
    assert result["decision"] == {
        "verdict": "REQUIRES_TRUE_LOSO",
        "locked_winner": "C1_VSA_ONLY",
        "remaining_required_evidence": [
            "TRUE_LOSO_NOT_YET_EVALUATED",
            "BASELINE_COMPARISON_NOT_YET_EVALUATED",
        ],
        "historical_feasibility_only": True,
        "paper_authorized": False,
        "live_deployment_authorized": False,
    }
    assert result["evidence_eligible"] is True
    assert len(result["provenance"]["shards"]) == 12


def test_shard_file_and_payload_hashes_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = _bundle(tmp_path)
    payload = report._load_json(manifest, name="manifest")
    first = payload["shards"][0]
    shard = tmp_path / first["path"]
    shard.write_text(shard.read_text(encoding="utf-8") + "\n", encoding="utf-8")

    monkeypatch.setattr(
        report,
        "_validate_manifest_governance",
        lambda *_args, **_kwargs: {
            "input_hashes": {},
            "expected_policy": {},
            "expected_scenarios": {name: {} for name in report.SCENARIO_ORDER},
            "preregistration": {},
            "execution_lock": {},
            "baseline_result_identity": {},
            "runtime_git_commit": "a" * 40,
            "locked_source_commit": "b" * 40,
        },
    )
    with pytest.raises(report.V18ReportContractError, match="byte identity"):
        report.build_primary_report(manifest, prereg=_prereg())


def test_duplicate_and_nonfinite_json_are_rejected(tmp_path: Path) -> None:
    duplicate = tmp_path / "duplicate.json"
    duplicate.write_text('{"a":1,"a":2}', encoding="utf-8")
    with pytest.raises(report.V18ReportContractError, match="duplicate"):
        report._load_json(duplicate, name="duplicate")

    nonfinite = tmp_path / "nonfinite.json"
    nonfinite.write_text('{"a":NaN}', encoding="utf-8")
    with pytest.raises(report.V18ReportContractError, match="non-finite"):
        report._load_json(nonfinite, name="nonfinite")


def test_candidate_signal_stream_and_engine_entry_reconcile_exactly() -> None:
    shard, manifest_hashes = _signal_shard()
    result = report._validate_candidate_signal_stream(
        shard,
        candidate_id="C1_VSA_ONLY",
        manifest_input_hashes=manifest_hashes,
    )
    assert result["decision_count"] == result["accepted_count"] == 1
    assert result["rejected_count"] == 0
    proxy = result["engine_proxy_intents"][0]
    entry = {
        "decision_ts": proxy["decision_ts"],
        "entry_ts": proxy["entry_ts"],
        "symbol": proxy["symbol"],
        "side": proxy["side"],
        "strategy": proxy["strategy"],
        "pattern_id": proxy["pattern_id"],
        "entry_price": proxy["entry_price"],
        "initial_stop": proxy["stop_price"],
        "signal_manifest_hash": proxy["signal_manifest_hash"],
        "config_sha256": proxy["config_sha256"],
    }
    report._validate_entries_originate_from_proxies([entry], [proxy])

    bad_entry = {**entry, "symbol": "SOL/USDT"}
    with pytest.raises(report.V18ReportContractError, match="does not originate"):
        report._validate_entries_originate_from_proxies([bad_entry], [proxy])


def test_candidate_signal_stream_tamper_fails_closed() -> None:
    shard, manifest_hashes = _signal_shard()
    shard["candidate_signal_stream"]["adapter_decisions"][0]["outcome"] = "rejected"
    with pytest.raises(report.V18ReportContractError, match="hash mismatch"):
        report._validate_candidate_signal_stream(
            shard,
            candidate_id="C1_VSA_ONLY",
            manifest_input_hashes=manifest_hashes,
        )


def test_loso_signal_stream_requires_all_and_only_non_holdout_winner_intents() -> None:
    shard, manifest_hashes, primary_summary = _loso_signal_fixture()
    result = report._validate_loso_signal_stream(
        shard,
        candidate_id="C1_VSA_ONLY",
        excluded_symbol="SOL/USDT",
        manifest_input_hashes=manifest_hashes,
        primary_signal_summary=primary_summary,
    )
    assert len(result["engine_proxy_intents"]) == 1
    assert result["excluded_source_intent_count"] == 0

    stream = shard["candidate_signal_stream"]
    stream["engine_proxy_intents"] = []
    stream["engine_proxy_intents_sha256"] = report._payload_sha256([])
    stream["excluded_source_intent_count"] = 1
    with pytest.raises(report.V18ReportContractError, match="all-and-only"):
        report._validate_loso_signal_stream(
            shard,
            candidate_id="C1_VSA_ONLY",
            excluded_symbol="SOL/USDT",
            manifest_input_hashes=manifest_hashes,
            primary_signal_summary=primary_summary,
        )


def test_loso_input_hashes_reconcile_to_primary_winner() -> None:
    frame_hashes = {symbol: "1" * 64 for symbol in report.v18_program.PRIMARY_SYMBOLS}
    primary_hashes = {
        "engine_frames_sha256_by_symbol": frame_hashes,
        "funding_events_sha256": "2" * 64,
        "daily_returns_sha256": "3" * 64,
        "baseline_decisions_sha256": "4" * 64,
        "baseline_intents_sha256": "5" * 64,
        "candidate_batches_sha256": {
            candidate: str(index + 6) * 64 for index, candidate in enumerate(report.CANDIDATE_ORDER)
        },
    }
    primary = {"provenance": {"runner_governance": {"input_hashes": primary_hashes}}}
    manifest = {
        "input_hashes": {
            key: value for key, value in primary_hashes.items() if key != "candidate_batches_sha256"
        }
    }
    manifest["input_hashes"]["locked_winner_batch_sha256"] = primary_hashes[
        "candidate_batches_sha256"
    ]["C1_VSA_ONLY"]
    loso, bound_primary = report._reconcile_loso_input_hashes(
        manifest,
        primary=primary,
        winner="C1_VSA_ONLY",
    )
    assert (
        loso["locked_winner_batch_sha256"]
        == bound_primary["candidate_batches_sha256"]["C1_VSA_ONLY"]
    )

    manifest["input_hashes"]["locked_winner_batch_sha256"] = "f" * 64
    with pytest.raises(report.V18ReportContractError, match="winner batch hash"):
        report._reconcile_loso_input_hashes(
            manifest,
            primary=primary,
            winner="C1_VSA_ONLY",
        )


def test_loso_governance_passes_prereg_and_locked_commit_to_program_apis(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    prereg = {"snapshots": {"market": {}, "funding": {}}}
    source = {"source": "stable"}
    runtime = {"runtime": "stable"}
    primary_spec = {"bytes": 1, "sha256": "1" * 64, "path": "primary"}
    manifest = {
        "schema_version": report.LOSO_MANIFEST_SCHEMA,
        "program_schema_version": report.v18_program.PROGRAM_SCHEMA,
        "status": "COMPLETE",
        "phase": "TRUE_LOSO",
        "evidence_eligible": True,
        "runner_up_fallback_used": False,
        "scenario": "H",
        "excluded_symbol_order": list(report.v18_program.PRIMARY_SYMBOLS),
        "manifest_published_last": True,
        "historical_feasibility_only": True,
        "live_or_paper_authorized": False,
        "locked_winner": "C1_VSA_ONLY",
        "preregistration": {},
        "execution_lock": {},
        "source_preflight": source,
        "source_postflight": source,
        "runtime_preflight": runtime,
        "runtime_postflight": runtime,
        "primary_report": primary_spec,
        "baseline_result_identity": {},
        "baseline_evidence_artifacts": {"status": "ok", "runtime_versions": runtime},
        "lineage": {},
        "snapshots": {},
        "generation_counts": {
            "market_snapshot_loads": 1,
            "funding_snapshot_loads": 1,
            "baseline_signal_generations": 1,
            "candidate_adapter_generations": 1,
            "independent_H_true_loso_replays": 13,
        },
    }
    lock = {"execution_git_commit": "a" * 40}
    captured: dict[str, Any] = {}
    monkeypatch.setattr(
        report,
        "_manifest_identity",
        lambda _root, _relative, spec, **_kwargs: dict(spec),
    )
    monkeypatch.setattr(report.v18_program, "_load_execution_lock", lambda _path: lock)
    monkeypatch.setattr(report.v18_program, "_source_provenance", lambda *_args: source)
    monkeypatch.setattr(report.v18_program, "_assert_source_ready", lambda _source: None)
    monkeypatch.setattr(
        report.v18_program.baseline,
        "_critical_runtime_versions",
        lambda _root: runtime,
    )

    def fake_primary(_path: Path, **kwargs: Any) -> tuple[dict[str, Any], dict[str, Any]]:
        captured["primary_prereg"] = kwargs["prereg"]
        return {"decision": {"locked_winner": "C1_VSA_ONLY"}}, dict(primary_spec)

    def fake_baseline(_path: Path, **kwargs: Any) -> dict[str, Any]:
        captured["baseline_commit"] = kwargs["expected_execution_git_commit"]
        return {"status": "ok", "runtime_versions": runtime}

    monkeypatch.setattr(report.v18_program, "_primary_report_evidence", fake_primary)
    monkeypatch.setattr(report.v18_program, "_baseline_identity_evidence", fake_baseline)
    monkeypatch.setattr(
        report,
        "_reconcile_loso_input_hashes",
        lambda *_args, **_kwargs: ({}, {}),
    )
    monkeypatch.setattr(report, "_validate_frozen_identity_map", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(report.v18_program, "_lineage_specs", lambda _prereg: {})
    result = report._validate_loso_manifest_governance(
        manifest,
        primary_report_path=tmp_path / "primary.json",
        prereg=prereg,
        repo_root=tmp_path,
    )
    assert result["winner"] == "C1_VSA_ONLY"
    assert captured == {
        "primary_prereg": prereg,
        "baseline_commit": lock["execution_git_commit"],
    }


def test_atomic_writer_publishes_exact_bytes_and_refuses_overwrite(tmp_path: Path) -> None:
    output = tmp_path / "report.json"
    report._write_atomic(output, '{"ok":true}\n')
    assert output.read_bytes() == b'{"ok":true}\n'
    with pytest.raises(FileExistsError):
        report._write_atomic(output, "{}\n")


def test_markdown_never_claims_deployment_authority() -> None:
    payload = {
        "decision": {"verdict": "RED_NO_PRIMARY_CELL_PASSED"},
        "candidates": {
            candidate: {
                "metrics": _passing_metrics(),
                "primary_gates": {"passed_before_multiple_testing_and_LOSO": False},
            }
            for candidate in report.CANDIDATE_ORDER
        },
    }
    markdown = report.render_markdown(payload)
    assert "RED_NO_PRIMARY_CELL_PASSED" in markdown
    assert "canlı işlem yetkisi vermez" in markdown
    assert "C1_VSA_ONLY" in markdown


def test_final_markdown_discloses_true_loso_and_baseline_comparison() -> None:
    payload = {
        "decision": {"verdict": "RED_NOT_BETTER_THAN_FAIR_BASELINE"},
        "candidates": {
            candidate: {
                "metrics": _passing_metrics(),
                "primary_gates": {"passed_before_multiple_testing_and_LOSO": True},
            }
            for candidate in report.CANDIDATE_ORDER
        },
        "true_loso": {
            "rows": [
                {
                    "excluded_symbol": "BTC/USDT",
                    "pseudo_oos_continuous_pnl": 123.0,
                    "positive": True,
                    "marginal_pnl": 7.0,
                }
            ],
            "effective_symbol_count": 8.5,
            "minimum_effective_symbol_count": 6.0,
            "passed": True,
        },
        "fair_baseline_comparison": {
            "baseline": {
                "H_trimmed_mean_monthly_pct": 1.0,
                "H_max_mtm_drawdown_pct": 10.0,
                "H_negative_months": 8,
                "H_worst_month_pct": -4.0,
            },
            "rule_1_passed": False,
            "rule_2_passed": False,
            "stability_noninferiority_passed": True,
            "passed": False,
        },
    }

    markdown = report.render_markdown(payload)

    assert "## True LOSO" in markdown
    assert "BTC/USDT" in markdown
    assert "Etkin sembol sayısı" in markdown
    assert "## Adil baseline karşılaştırması" in markdown
    assert "Baseline'dan daha iyi kapısı: `RED`" in markdown


def test_cli_routes_primary_and_loso_to_canonical_outputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "repo"
    prereg = root / report.CANONICAL_PREREG_RELATIVE
    primary_manifest = root / report.CANONICAL_PRIMARY_MANIFEST_RELATIVE
    loso_manifest = root / report.CANONICAL_LOSO_MANIFEST_RELATIVE
    for path in (prereg, primary_manifest, loso_manifest):
        _write_json(path, {})

    phases: list[str] = []
    monkeypatch.setattr(report.v18_program, "load_preregistration", lambda _path: _prereg())
    monkeypatch.setattr(
        report,
        "build_primary_report",
        lambda *_args, **_kwargs: phases.append("primary") or {"phase": "primary"},
    )
    monkeypatch.setattr(
        report,
        "build_loso_report",
        lambda *_args, **_kwargs: phases.append("loso") or {"phase": "loso"},
    )
    monkeypatch.setattr(report, "render_markdown", lambda payload: f"{payload['phase']}\n")

    primary_json = root / report.CANONICAL_PRIMARY_REPORT_JSON_RELATIVE
    primary_markdown = root / report.CANONICAL_PRIMARY_REPORT_MARKDOWN_RELATIVE
    assert (
        report.main(
            [
                "--phase",
                "primary",
                "--manifest",
                str(primary_manifest),
                "--prereg",
                str(prereg),
                "--json-output",
                str(primary_json),
                "--markdown-output",
                str(primary_markdown),
            ]
        )
        == 0
    )
    assert json.loads(primary_json.read_text(encoding="utf-8")) == {"phase": "primary"}

    final_json = root / report.CANONICAL_FINAL_REPORT_JSON_RELATIVE
    final_markdown = root / report.CANONICAL_FINAL_REPORT_MARKDOWN_RELATIVE
    assert (
        report.main(
            [
                "--phase",
                "loso",
                "--manifest",
                str(loso_manifest),
                "--prereg",
                str(prereg),
                "--primary-report",
                str(primary_json),
                "--json-output",
                str(final_json),
                "--markdown-output",
                str(final_markdown),
            ]
        )
        == 0
    )
    assert json.loads(final_json.read_text(encoding="utf-8")) == {"phase": "loso"}
    assert phases == ["primary", "loso"]
