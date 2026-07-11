from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from price_action.lab import crypto_15m_v15p2_program as program
from price_action.lab import crypto_15m_v15p2_report as report
from price_action.lab.crypto_15m_v15p2_signals import (
    SignalDecisionLedger,
    SignalGenerationResult,
    V15P2SignalIntent,
)


def _scenario_config(name: str) -> dict[str, Any]:
    return copy.deepcopy(report._EXPECTED_SCENARIOS[name])


def _curve(*, terminal: bool = False) -> list[dict[str, Any]]:
    timestamps: list[pd.Timestamp] = []
    for month_start in pd.date_range(
        report.EVALUATION_START,
        report.EVALUATION_END,
        freq="MS",
        inclusive="left",
    ):
        timestamps.extend([month_start, month_start + pd.offsets.MonthBegin(1) - report.BAR])
    timestamps = sorted(set(timestamps))
    rows: list[dict[str, Any]] = []
    for timestamp in timestamps:
        wallet = 10_000.0
        gross = adjusted = accrued = 0.0
        open_count = 0
        if terminal:
            wallet = 9_997.15
            accrued = 2.85
            open_count = 1
            if timestamp == report.EVALUATION_END - report.BAR:
                gross = adjusted = 100.0
                accrued = 3.135
        rows.append(
            {
                "ts": timestamp.isoformat(),
                "wallet_balance": wallet,
                "gross_unrealized_price_pnl": gross,
                "adjusted_unrealized_price_pnl": adjusted,
                "accrued_exit_cost": accrued,
                "nav": wallet + adjusted - accrued,
                "open_position_count": open_count,
            }
        )
    return rows


def _max_drawdown(curve: list[dict[str, Any]]) -> float:
    peak = 10_000.0
    worst = 0.0
    for row in curve:
        nav = float(row["nav"])
        peak = max(peak, nav)
        worst = min(worst, nav / peak - 1.0)
    return worst


def _entry() -> dict[str, Any]:
    return {
        "candidate_id": "v15p2_fair_baseline",
        "decision_ts": "2021-05-31T23:45:00+00:00",
        "entry_ts": "2021-06-01T00:00:00+00:00",
        "symbol": "ETH/USDT",
        "side": "long",
        "strategy": "vsa_climax_test",
        "pattern_id": "synthetic",
        "entry_price": 100.0,
        "initial_stop": 97.5,
        "tp1_price": 102.5,
        "tp2_price": 103.75,
        "original_quantity": 10.0,
        "entry_notional": 1_000.0,
        "dynamic_leverage": 3.0,
        "wallet_before_entry": 10_000.0,
        "wallet_after_entry": 9_997.15,
        "risk_budget": 100.0,
        "effective_initial_stop_risk": 25.0,
        "fee": 0.4,
        "spread_slippage": 2.0,
        "impact": 0.45,
        "execution_cost": 2.85,
        "scenario": "B",
        "signal_manifest_hash": report.EXPECTED_SIGNAL_MANIFEST_HASHES["vsa_climax_test"],
        "config_sha256": report.EXPECTED_CONFIG_SHA256,
    }


def _signal_intent() -> dict[str, Any]:
    return {
        "candidate_id": "v15p2_fair_baseline",
        "decision_ts": "2021-05-31T23:45:00+00:00",
        "entry_ts": "2021-06-01T00:00:00+00:00",
        "symbol": "ETH/USDT",
        "side": "long",
        "strategy": "vsa_climax_test",
        "strategy_rank": 0,
        "pattern_id": "synthetic",
        "confluence_score": 1.0,
        "decision_close": 100.0,
        "entry_reference_price": 100.0,
        "entry_price": 100.0,
        "stop_price": 97.5,
        "take_profit_price": 103.75,
        "decision_stop_distance_pct": 0.025,
        "entry_stop_distance_pct": 0.025,
        "suggested_size_atr": 1.0,
        "signal_manifest_hash": report.EXPECTED_SIGNAL_MANIFEST_HASHES["vsa_climax_test"],
        "config_sha256": report.EXPECTED_CONFIG_SHA256,
    }


def _signal_stream(*, with_evaluation_intent: bool) -> dict[str, Any]:
    intents = [_signal_intent()] if with_evaluation_intent else []
    decisions = (
        [{"emission_index": 0, **intents[0], "outcome": "accepted", "reason": "accepted"}]
        if intents
        else []
    )
    fingerprints = [
        {field: row[field] for field in report._SIGNAL_FINGERPRINT_FIELDS} for row in decisions
    ]
    fingerprint_hash = _hash(fingerprints)
    return {
        "generation_call_count": 1,
        "raw_emission_count": len(decisions),
        "generated_history_intent_count": len(intents),
        "evaluation_intent_count": len(intents),
        "pre_evaluation_intents_excluded": 0,
        "decision_reason_counts": {"accepted": 1} if decisions else {},
        "decision_ledger": decisions,
        "decision_ledger_sha256": _hash(decisions),
        "accepted_intent_reconciliation": {
            "accepted_decision_count": len(intents),
            "intent_count": len(intents),
            "exact_ordered_reconciliation": True,
            "accepted_decision_fingerprints_sha256": fingerprint_hash,
            "intent_fingerprints_sha256": fingerprint_hash,
            "evaluation_accepted_decision_count": len(intents),
            "evaluation_intent_count": len(intents),
            "evaluation_exact_ordered_reconciliation": True,
            "evaluation_fingerprints_sha256": fingerprint_hash,
        },
        "only_signal_eligible_intents_passed_to_engines": True,
        "accepted_intents": intents,
        "accepted_intents_sha256": _hash(intents),
        "entry_intents": intents,
        "entry_intents_sha256": _hash(intents),
        "reference_or_holdout_intents": 0,
    }


def _terminal() -> dict[str, Any]:
    return {
        "candidate_id": "v15p2_fair_baseline",
        "symbol": "ETH/USDT",
        "side": "long",
        "entry_ts": "2021-06-01T00:00:00+00:00",
        "cutoff_ts": (report.EVALUATION_END - report.BAR).isoformat(),
        "entry_price": 100.0,
        "mark_price": 110.0,
        "remaining_quantity": 10.0,
        "gross_unrealized_price_pnl": 100.0,
        "payoff_multiplier": 1.0,
        "adjusted_unrealized_price_pnl": 100.0,
        "accrued_exit_cost": 3.135,
        "accrued_nav_contribution": 96.865,
    }


def _complete_result(name: str, *, terminal: bool = False) -> dict[str, Any]:
    curve = _curve(terminal=terminal)
    entries = [_entry()] if terminal else []
    terminal_positions = [_terminal()] if terminal else []
    if terminal:
        entries[0]["scenario"] = name
    final_wallet = 9_997.15 if terminal else 10_000.0
    final_nav = float(curve[-1]["nav"])
    return {
        "scenario": name,
        "scenario_identity": name,
        "scenario_is_canonical": True,
        "scenario_config": _scenario_config(name),
        "policy": {"initial_wallet": 10_000.0},
        "evaluation_start": report.EVALUATION_START.isoformat(),
        "evaluation_end": report.EVALUATION_END.isoformat(),
        "initial_wallet": 10_000.0,
        "final_wallet": final_wallet,
        "final_nav": final_nav,
        "max_drawdown": _max_drawdown(curve),
        "total_execution_cost_charged": 2.85 if terminal else 0.0,
        "total_funding_cashflow": 0.0,
        "accrued_terminal_exit_cost": 3.135 if terminal else 0.0,
        "entries": entries,
        "exit_fills": [],
        "funding_events": [],
        "journal_rows": [],
        "stop_transitions": [],
        "breaker_transitions": [],
        "risk_decisions": [],
        "rejections": [],
        "closed_episodes": [],
        "curve": curve,
        "terminal_positions": terminal_positions,
    }


def _hash(value: Any) -> str:
    return report._canonical_hash(value)


def _source_provenance() -> dict[str, Any]:
    required = set(report._REQUIRED_RUNNER_SOURCE_FILES).union(
        path for path, _digest in report._EXPECTED_REFERENCE_SOURCES.values()
    )
    hashes = {path: "9" * 64 for path in required}
    hashes[report.CANONICAL_PREREG_RELATIVE] = report.EXPECTED_PREREG_SHA256
    hashes["requirements-lock.txt"] = report.EXPECTED_REQUIREMENTS_LOCK_SHA256
    checks: dict[str, Any] = {}
    for key in report._REFERENCE_SOURCE_KEYS:
        path, digest = report._EXPECTED_REFERENCE_SOURCES[key]
        hashes[path] = digest
        checks[key] = {
            "path": path,
            "expected_sha256": digest,
            "actual_sha256": digest,
            "matches": True,
        }
    return {
        "git_commit": "a" * 40,
        "research_source_clean": True,
        "research_source_status": [],
        "missing_source_files": [],
        "file_sha256": hashes,
        "reference_source_checks": checks,
        "exact_reference_source_hashes_match": True,
    }


def _snapshots() -> dict[str, Any]:
    return {
        name: {
            "name": name,
            "configured_path": identity["configured_path"],
            "resolved_path": f"/repo/{identity['configured_path']}",
            "bytes": identity["bytes"],
            "sha256": identity["sha256"],
            "status": "VERIFIED",
        }
        for name, identity in report.EXPECTED_SNAPSHOT_IDENTITIES.items()
    }


def _market_loading() -> dict[str, Any]:
    all_symbols = [*report.PRIMARY_SYMBOLS, report.REFERENCE_SYMBOL]
    return {
        "symbols": all_symbols,
        "tradable_symbols": list(report.PRIMARY_SYMBOLS),
        "reference_symbol": report.REFERENCE_SYMBOL,
        "reference_symbol_traded": False,
        "alignment": "INDEPENDENT_SYMBOL_FRAMES",
        "global_intersection_performed": False,
        "forward_fill_performed": False,
        "history_rows_by_symbol": {symbol: 1_000 for symbol in all_symbols},
        "first_ts_by_symbol": {symbol: report.HISTORY_START.isoformat() for symbol in all_symbols},
        "last_ts_by_symbol": {
            symbol: (report.EVALUATION_END - report.BAR).isoformat() for symbol in all_symbols
        },
        "engine_validation_start_inclusive": (report.EVALUATION_START - report.BAR).isoformat(),
        "engine_rows_by_symbol": {symbol: 500 for symbol in report.PRIMARY_SYMBOLS},
    }


def _raw(*, terminal_scenario: str | None = None) -> dict[str, Any]:
    scenarios = {name: _scenario_config(name) for name in report.SCENARIO_ORDER}
    results: dict[str, Any] = {}
    for name in report.SCENARIO_ORDER:
        complete = _complete_result(name, terminal=name == terminal_scenario)
        results[name] = {
            "complete_result": complete,
            "complete_result_sha256": _hash(complete),
        }
    policy = {"initial_wallet": 10_000.0}
    signal_stream = _signal_stream(with_evaluation_intent=terminal_scenario is not None)
    source = _source_provenance()
    runtime = copy.deepcopy(report.EXPECTED_RUNTIME_VERSIONS)
    snapshots = _snapshots()
    frame_hashes = {symbol: "e" * 64 for symbol in report.PRIMARY_SYMBOLS}
    funding_hash = "7" * 64
    returns_hash = "d" * 64
    return {
        "schema_version": report.RAW_SCHEMA,
        "mode": report.FULL_REPLAY_MODE,
        "evidence_eligible": True,
        "evidence_ineligible_reasons": [],
        "classification": {
            "result_label": "FAIR_LIVE_POLICY_PROXY",
            "strategy": "FAIR_LIVE_POLICY_PROXY",
            "execution": "NEXT_OPEN_BAR_EXECUTION_PROXY",
            "exact_live_replay_claim_allowed": False,
            "deployment_decision_authorized": False,
            "historical_pseudo_oos_is_independent_prospective_evidence": False,
        },
        "external_live_gate_proxy_policy": copy.deepcopy(report._EXPECTED_EXTERNAL_PROXY_POLICY),
        "fair_improvement_rules": copy.deepcopy(report._EXPECTED_FAIR_IMPROVEMENT_RULES),
        "fair_improvement_rules_sha256": _hash(report._EXPECTED_FAIR_IMPROVEMENT_RULES),
        "limitations": list(report._EXPECTED_RAW_LIMITATIONS),
        "disclosed_limitations": {
            "required": True,
            "count": len(report._EXPECTED_RAW_LIMITATIONS),
            "items": list(report._EXPECTED_RAW_LIMITATIONS),
            "sha256": _hash(list(report._EXPECTED_RAW_LIMITATIONS)),
        },
        "preregistration": {
            "path": "/repo/configs/crypto_15m_v15p2_fair_baseline_prereg.yaml",
            "sha256": report.EXPECTED_PREREG_SHA256,
            "schema_version": "crypto-15m-v15p2-fair-baseline-prereg-v1",
            "status": "PREREGISTERED_NO_RESULTS_SEEN",
            "live_deployment_authorized": False,
        },
        "candidate_id": "v15p2_fair_baseline",
        "scenario_order": list(report.SCENARIO_ORDER),
        "policy": policy,
        "policy_sha256": _hash(policy),
        "scenarios": scenarios,
        "scenarios_sha256": _hash(scenarios),
        "runtime_versions": runtime,
        "source_provenance": source,
        "universe": {
            "tradable_symbols": list(report.PRIMARY_SYMBOLS),
            "non_traded_reference_symbol": report.REFERENCE_SYMBOL,
            "holdout_symbols_accessed": [],
            "reference_symbol_traded": False,
        },
        "time_range_utc": {
            "history_start_inclusive": report.HISTORY_START.isoformat(),
            "evaluation_start_inclusive": report.EVALUATION_START.isoformat(),
            "end_exclusive": report.EVALUATION_END.isoformat(),
        },
        "evaluation_protocol": {
            "development": [
                report.EVALUATION_START.isoformat(),
                report.DEVELOPMENT_END.isoformat(),
            ],
            "pseudo_oos": [
                report.DEVELOPMENT_END.isoformat(),
                report.EVALUATION_END.isoformat(),
            ],
            "walk_forward_folds": [
                [start.isoformat(), end.isoformat()] for start, end in report.FOLD_WINDOWS
            ],
            "fold_count": 6,
            "fold_months_each": [6, 6, 6, 6, 6, 6],
            "interval_semantics": "half_open_start_inclusive_end_exclusive",
        },
        "snapshots": snapshots,
        "execution_governance": {
            "canonical_prereg_path": ("/repo/configs/crypto_15m_v15p2_fair_baseline_prereg.yaml"),
            "canonical_prereg_semantic_match": True,
            "canonical_prereg_preflight_sha256": report.EXPECTED_PREREG_SHA256,
            "canonical_prereg_postflight_sha256": report.EXPECTED_PREREG_SHA256,
            "clean_source_preflight_before_snapshot_access": True,
            "exact_reference_source_hashes_preflight": True,
            "source_unchanged_postflight": True,
            "runtime_unchanged_postflight": True,
            "snapshots_reverified_postflight": True,
            "snapshots_unchanged_postflight": True,
            "preflight_source": copy.deepcopy(source),
            "postflight_source": copy.deepcopy(source),
            "preflight_runtime": copy.deepcopy(runtime),
            "postflight_runtime": copy.deepcopy(runtime),
            "postflight_snapshots": copy.deepcopy(snapshots),
            "input_mutation_checks": {
                "engine_frames_sha256_by_symbol": frame_hashes,
                "signal_decision_ledger_sha256": signal_stream["decision_ledger_sha256"],
                "signal_batch_intents_sha256": signal_stream["accepted_intents_sha256"],
                "entry_intents_sha256": signal_stream["entry_intents_sha256"],
                "funding_events_sha256": funding_hash,
                "daily_returns_sha256": returns_hash,
                "all_unchanged": True,
            },
        },
        "market_loading": _market_loading(),
        "funding": {
            "source": "OBSERVED_FROZEN_FUNDING_EVENTS",
            "symbols": list(report.PRIMARY_SYMBOLS),
            "event_count": 0,
            "rows_by_symbol_including_history": {symbol: 10 for symbol in report.PRIMARY_SYMBOLS},
            "raw_fractional_timestamps_preserved": True,
            "invalid_mark_price_falls_back_in_engine": True,
        },
        "daily_returns": {
            "construction": "COMPLETE_CAUSAL_UTC_DAYS_ONLY",
            "minimum_initial_common_observations": 90,
            "row_count": 100,
            "columns": list(report.PRIMARY_SYMBOLS),
            "sha256": returns_hash,
        },
        "signal_stream": signal_stream,
        "results": results,
    }


def _rehash_result(raw: dict[str, Any], name: str) -> None:
    wrapper = raw["results"][name]
    wrapper["complete_result_sha256"] = _hash(wrapper["complete_result"])


def test_no_trade_report_has_all_zero_months_and_no_deployment() -> None:
    raw = _raw()
    result = report.build_report(raw)

    assert result["decision"] == {
        "verdict": report.VERDICT,
        "measurement_label": "FAIR_LIVE_POLICY_PROXY",
        "execution_label": "NEXT_OPEN_BAR_EXECUTION_PROXY",
        "winner_declared": False,
        "challenger_comparison_performed": False,
        "holdout_run_by_reporter": False,
        "paper_authorized": False,
        "live_deployment_authorized": False,
        "baseline_measurement_is_not_a_deployment_decision": True,
    }
    assert result["classification"] == raw["classification"]
    assert tuple(result["classification"]) == tuple(raw["classification"])
    for name in report.SCENARIO_ORDER:
        full = result["scenarios"][name]["windows"]["full"]
        development = result["scenarios"][name]["windows"]["development"]
        pseudo = result["scenarios"][name]["windows"]["pseudo_oos"]
        assert full["month_count"] == 60
        assert development["month_count"] == 24
        assert pseudo["month_count"] == 36
        assert full["inactive_month_count"] == 60
        assert [row["return_pct"] for row in full["monthly"]] == [0.0] * 60
        assert (
            result["scenarios"][name]["turnover"][
                "filled_gross_turnover_over_arithmetic_mean_15m_nav"
            ]
            == 0.0
        )
    assert result["scenarios"]["H"]["windows"]["pseudo_oos"]["month_count"] == 36
    assert result["H_summary"]["pseudo_oos_trimmed_10pct_symmetric_mean_monthly_return_pct"] == 0.0


def test_monthly_baseline_is_last_nav_strictly_before_boundary() -> None:
    timestamps = (
        pd.Timestamp("2021-06-01T00:00:00Z"),
        pd.Timestamp("2021-06-30T23:45:00Z"),
        pd.Timestamp("2021-07-01T00:00:00Z"),
        pd.Timestamp("2021-07-31T23:45:00Z"),
    )
    curve = report._Curve(
        timestamps=timestamps,
        navs=(10_000.0, 11_000.0, 22_000.0, 12_100.0),
        wallets=(10_000.0, 11_000.0, 22_000.0, 12_100.0),
        gross_unrealized=(0.0,) * 4,
        adjusted_unrealized=(0.0,) * 4,
        accrued_exit_costs=(0.0,) * 4,
        open_counts=(1,) * 4,
    )

    rows = report._monthly_rows(
        curve,
        10_000.0,
        {"2021-06", "2021-07"},
        pd.Timestamp("2021-06-01T00:00:00Z"),
        pd.Timestamp("2021-08-01T00:00:00Z"),
    )

    assert rows[0]["return_pct"] == pytest.approx(10.0)
    assert rows[1]["baseline_nav"] == 11_000.0
    assert rows[1]["baseline_timestamp_strictly_before_start"] == ("2021-06-30T23:45:00+00:00")
    assert rows[1]["return_pct"] == pytest.approx(10.0)


def test_terminal_open_accrual_and_wallet_identities() -> None:
    result = report.build_report(_raw(terminal_scenario="B"))
    cell = result["scenarios"]["B"]

    assert cell["financial_identities"]["all_passed"] is True
    assert cell["sample"]["closed_episode_count"] == 0
    assert cell["sample"]["terminal_open_position_count"] == 1
    assert cell["terminal_open_accrual"]["adjusted_unrealized_price_pnl"] == 100.0
    assert cell["terminal_open_accrual"]["accrued_exit_cost"] == 3.135
    assert cell["terminal_open_accrual"]["accrued_nav_contribution"] == 96.865
    assert cell["turnover"]["filled_gross_turnover"] == 1_000.0
    assert result["signal_evidence"]["raw_emission_count"] == 1
    assert result["signal_evidence"]["evaluation_intent_count"] == 1
    assert result["signal_evidence"]["accepted_rows_exactly_reconciled_to_engine_intents"] is True


def test_signal_ledger_full_field_reconciliation_fails_after_valid_hashes() -> None:
    raw = _raw(terminal_scenario="B")
    stream = raw["signal_stream"]
    stream["entry_intents"][0]["confluence_score"] = 2.0
    stream["entry_intents_sha256"] = _hash(stream["entry_intents"])
    raw["execution_governance"]["input_mutation_checks"]["entry_intents_sha256"] = stream[
        "entry_intents_sha256"
    ]

    with pytest.raises(report.BaselineReportContractError, match="exactly reconcile"):
        report.build_report(raw)


def test_all_history_accepted_intents_are_bound_to_decisions_and_mutation_proof() -> None:
    raw = _raw(terminal_scenario="B")
    stream = raw["signal_stream"]
    stream["accepted_intents"][0]["confluence_score"] = 2.0
    stream["accepted_intents_sha256"] = _hash(stream["accepted_intents"])
    raw["execution_governance"]["input_mutation_checks"]["signal_batch_intents_sha256"] = stream[
        "accepted_intents_sha256"
    ]

    with pytest.raises(report.BaselineReportContractError, match="all accepted decision rows"):
        report.build_report(raw)


def test_current_program_and_report_source_scopes_stay_integrated() -> None:
    assert set(program._RUNNER_SOURCE_FILES) == set(report._REQUIRED_RUNNER_SOURCE_FILES)
    assert tuple(program._REFERENCE_SOURCE_KEYS) == report._REFERENCE_SOURCE_KEYS


def test_report_identity_constants_match_canonical_preregistration() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    prereg_path = repo_root / report.CANONICAL_PREREG_RELATIVE
    prereg = program.load_preregistration(prereg_path)
    references = prereg["audited_live_reference"]

    assert program.sha256_file(prereg_path) == report.EXPECTED_PREREG_SHA256
    for key in report._REFERENCE_SOURCE_KEYS:
        expected_path, expected_sha256 = report._EXPECTED_REFERENCE_SOURCES[key]
        assert references[key] == {
            "path": expected_path,
            "sha256_at_prereg": expected_sha256,
        }


@pytest.mark.parametrize(
    ("mutation", "match"),
    [
        (lambda raw: raw.pop("market_loading"), "raw payload fields drifted"),
        (
            lambda raw: raw["external_live_gate_proxy_policy"].update(
                FNG_history_in_frozen_snapshots=True
            ),
            "external live-gate proxy policy",
        ),
        (
            lambda raw: raw["fair_improvement_rules"]["rule_1"].update(
                challenger_H_max_MTM_drawdown_may_be_at_most_pp_worse=2.0
            ),
            "fair-improvement rules",
        ),
        (
            lambda raw: raw["runtime_versions"].update(pandas="0.0.0"),
            "frozen runtime versions",
        ),
        (
            lambda raw: raw["source_provenance"]["research_source_status"].append(" M x"),
            "research_source_status",
        ),
        (
            lambda raw: raw["source_provenance"]["missing_source_files"].append("x.py"),
            "missing_source_files",
        ),
        (
            lambda raw: raw["source_provenance"]["reference_source_checks"]["scanner"].update(
                actual_sha256="0" * 64
            ),
            "scanner reference hash",
        ),
        (
            lambda raw: raw["snapshots"]["market"].update(status="NOT_VERIFIED"),
            "not VERIFIED",
        ),
        (
            lambda raw: raw["snapshots"]["funding"].update(
                configured_path="data/backups/other/funding.duckdb"
            ),
            "configured path",
        ),
        (
            lambda raw: raw["market_loading"].update(forward_fill_performed=True),
            "forward_fill_performed",
        ),
        (
            lambda raw: raw["funding"].update(source="SYNTHETIC"),
            "funding source",
        ),
        (
            lambda raw: raw["daily_returns"].update(sha256="4" * 64),
            "daily-return mutation hash",
        ),
    ],
)
def test_raw_program_evidence_blocks_fail_closed(mutation: Any, match: str) -> None:
    raw = _raw()
    mutation(raw)
    with pytest.raises(report.BaselineReportContractError, match=match):
        report.build_report(raw)


def test_governance_pre_post_evidence_must_equal_top_level() -> None:
    raw = _raw()
    raw["execution_governance"]["preflight_source"] = copy.deepcopy(raw["source_provenance"])
    raw["execution_governance"]["preflight_source"]["git_commit"] = "b" * 40
    with pytest.raises(report.BaselineReportContractError, match="preflight source differs"):
        report.build_report(raw)

    raw = _raw()
    raw["execution_governance"]["postflight_snapshots"]["market"]["bytes"] += 1
    with pytest.raises(report.BaselineReportContractError, match="byte size drifted"):
        report.build_report(raw)


def test_preregistration_path_hash_and_source_hash_are_one_chain() -> None:
    raw = _raw()
    raw["preregistration"]["path"] = "/other/configs/not-the-prereg.yaml"
    raw["execution_governance"]["canonical_prereg_path"] = raw["preregistration"]["path"]
    with pytest.raises(report.BaselineReportContractError, match="absolute/canonical"):
        report.build_report(raw)

    raw = _raw()
    raw["source_provenance"]["file_sha256"][report.CANONICAL_PREREG_RELATIVE] = "0" * 64
    with pytest.raises(report.BaselineReportContractError, match="frozen preregistration"):
        report.build_report(raw)


def test_report_accepts_genuine_program_signal_reconciliation_output() -> None:
    signal_fields = _signal_intent()
    signal_fields["decision_ts"] = pd.Timestamp(signal_fields["decision_ts"]).to_pydatetime()
    signal_fields["entry_ts"] = pd.Timestamp(signal_fields["entry_ts"]).to_pydatetime()
    intent = V15P2SignalIntent(**signal_fields)
    decision = SignalDecisionLedger(
        emission_index=0,
        **signal_fields,
        outcome="accepted",
        reason="accepted",
    )
    batch = SignalGenerationResult(
        candidate_id=program.FAIR_BASELINE_CANDIDATE_ID,
        config_sha256=program.EXPECTED_CONFIG_SHA256,
        decisions=(decision,),
        intents=(intent,),
    )
    genuine_reconciliation = program._reconcile_signal_batch(batch)

    raw = _raw(terminal_scenario="B")
    raw["signal_stream"]["accepted_intent_reconciliation"] = genuine_reconciliation

    result = report.build_report(raw)

    assert result["signal_evidence"]["accepted_rows_exactly_reconciled_to_engine_intents"] is True
    assert (
        genuine_reconciliation["accepted_decision_fingerprints_sha256"]
        == (genuine_reconciliation["intent_fingerprints_sha256"])
    )


def test_engine_entry_must_originate_from_evaluation_signal_intent() -> None:
    raw = _raw(terminal_scenario="B")
    raw["results"]["B"]["complete_result"]["entries"][0]["pattern_id"] = "foreign"
    _rehash_result(raw, "B")

    with pytest.raises(report.BaselineReportContractError, match="evaluation intent"):
        report.build_report(raw)


def test_raw_limitations_and_scenario_identity_are_exact() -> None:
    raw = _raw()
    raw["limitations"].remove("inert_YAML_exit_engine_differs_from_live_wrapper_30_30_40_authority")
    raw["disclosed_limitations"]["items"] = list(raw["limitations"])
    raw["disclosed_limitations"]["count"] = len(raw["limitations"])
    raw["disclosed_limitations"]["sha256"] = _hash(raw["limitations"])
    with pytest.raises(report.BaselineReportContractError, match="limitations"):
        report.build_report(raw)

    raw = _raw()
    raw["scenarios"]["H"]["positive_price_pnl_multiplier"] = 0.75
    raw["scenarios_sha256"] = _hash(raw["scenarios"])
    with pytest.raises(report.BaselineReportContractError, match="reconciliation"):
        report.build_report(raw)


def test_serializers_permanently_refuse_a_deployment_verdict() -> None:
    result = report.build_report(_raw())
    result["decision"]["verdict"] = "DEPLOY"
    result["decision"]["live_deployment_authorized"] = True

    with pytest.raises(report.BaselineReportContractError, match=report.VERDICT):
        report.deterministic_json(result)
    with pytest.raises(report.BaselineReportContractError, match=report.VERDICT):
        report.render_markdown(result)


def test_exact_six_h_folds_cover_36_months_without_reset() -> None:
    result = report.build_report(_raw())

    assert len(result["H_folds"]) == 6
    assert [len(fold["monthly_returns_pct"]) for fold in result["H_folds"]] == [6] * 6
    assert result["H_folds"][0]["start_inclusive"] == "2023-06-01T00:00:00+00:00"
    assert result["H_folds"][-1]["end_exclusive"] == "2026-06-01T00:00:00+00:00"


@pytest.mark.parametrize(
    ("mutation", "match"),
    [
        (lambda raw: raw.update(evidence_eligible=False), "not evidence eligible"),
        (lambda raw: raw.update(scenario_order=["B", "H", "C2"]), "scenario order"),
        (
            lambda raw: raw["results"]["H"]["complete_result"].update(
                evaluation_end="2026-06-01T00:15:00+00:00"
            ),
            "sha256 mismatch",
        ),
        (
            lambda raw: raw["execution_governance"].update(source_unchanged_postflight=False),
            "source_unchanged_postflight",
        ),
    ],
)
def test_fail_closed_header_and_half_open_contract(mutation: Any, match: str) -> None:
    raw = _raw()
    mutation(raw)
    with pytest.raises(report.BaselineReportContractError, match=match):
        report.build_report(raw)


def test_ledger_event_at_exclusive_end_is_rejected_after_valid_hash() -> None:
    raw = _raw()
    entry = _entry()
    entry["decision_ts"] = (report.EVALUATION_END - report.BAR).isoformat()
    entry["entry_ts"] = report.EVALUATION_END.isoformat()
    raw["results"]["B"]["complete_result"]["entries"].append(entry)
    _rehash_result(raw, "B")

    with pytest.raises(report.BaselineReportContractError, match="half-open"):
        report.build_report(raw)


def test_rejects_nan_even_when_nested_in_unused_ledger() -> None:
    raw = _raw()
    raw["results"]["B"]["complete_result"]["rejections"].append(
        {
            "entry_ts": "2021-06-01T00:00:00+00:00",
            "detail": float("nan"),
        }
    )

    with pytest.raises(report.BaselineReportContractError, match="non-finite"):
        report.build_report(raw)


def test_json_loader_rejects_nan_and_duplicate_keys(tmp_path: Path) -> None:
    nan_path = tmp_path / "nan.json"
    nan_path.write_text('{"value": NaN}', encoding="utf-8")
    duplicate_path = tmp_path / "duplicate.json"
    duplicate_path.write_text('{"value": 1, "value": 2}', encoding="utf-8")

    with pytest.raises(report.BaselineReportContractError, match="non-finite"):
        report.load_json_artifact(nan_path)
    with pytest.raises(report.BaselineReportContractError, match="duplicate"):
        report.load_json_artifact(duplicate_path)


def test_deterministic_json_and_markdown() -> None:
    result = report.build_report(_raw())
    markdown = report.render_markdown(result)

    assert report.deterministic_json(result) == report.deterministic_json(result)
    assert markdown == report.render_markdown(copy.deepcopy(result))
    assert report.VERDICT in markdown
    assert "repaired_scanner_not_running_pid_history" in markdown
    assert all(item in markdown for item in report._EXPECTED_RAW_LIMITATIONS)
    assert "static_survivor_primary_universe" in markdown
    assert "no_exchange_state_stale_or_rate_limit_path" in markdown
    assert "historical_pseudo_OOS_is_not_genuine_prospective_evidence" in markdown
    assert json.loads(report.deterministic_json(result))["schema_version"] == report.REPORT_SCHEMA


def test_cli_writes_distinct_outputs_and_refuses_overwrite(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    input_path = tmp_path / "raw.json"
    input_path.write_text(
        json.dumps(_raw(), sort_keys=True, allow_nan=False),
        encoding="utf-8",
    )
    json_output = tmp_path / "report.json"
    markdown_output = tmp_path / "report.md"

    assert (
        report.main(
            [
                "--input",
                str(input_path),
                "--json-output",
                str(json_output),
                "--markdown-output",
                str(markdown_output),
            ]
        )
        == 0
    )
    assert json.loads(json_output.read_text(encoding="utf-8"))["decision"]["verdict"] == (
        report.VERDICT
    )
    assert report.VERDICT in markdown_output.read_text(encoding="utf-8")
    assert report.VERDICT in capsys.readouterr().out

    with pytest.raises(FileExistsError, match="overwrite"):
        report.main(
            [
                "--input",
                str(input_path),
                "--json-output",
                str(json_output),
            ]
        )


def test_cli_rejects_same_output_and_input(tmp_path: Path) -> None:
    input_path = tmp_path / "raw.json"
    input_path.write_text(json.dumps(_raw()), encoding="utf-8")

    with pytest.raises(report.BaselineReportContractError, match="overwrite the input"):
        report.main(["--input", str(input_path), "--json-output", str(input_path)])


def test_atomic_exclusive_writer_leaves_no_partial_final_or_temp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / "report.json"

    def fail_publish(_source: str, _destination: Path) -> None:
        raise OSError("injected publish failure")

    monkeypatch.setattr(report.os, "link", fail_publish)
    with pytest.raises(OSError, match="injected"):
        report._write_exclusive(output, '{"ok": true}\n')

    assert not output.exists()
    assert list(tmp_path.glob(".report.json.*.tmp")) == []


def test_atomic_exclusive_writer_cannot_replace_concurrent_output(tmp_path: Path) -> None:
    output = tmp_path / "report.json"
    output.write_text("existing", encoding="utf-8")

    with pytest.raises(FileExistsError):
        report._write_exclusive(output, "replacement")

    assert output.read_text(encoding="utf-8") == "existing"
    assert list(tmp_path.glob(".report.json.*.tmp")) == []
