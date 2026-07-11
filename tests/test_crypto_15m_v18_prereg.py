from __future__ import annotations

import hashlib
import json
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
PREREG_PATH = ROOT / "configs/crypto_15m_v18_challenger_prereg.yaml"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load() -> dict:
    loaded = yaml.safe_load(PREREG_PATH.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


def test_v18_prereg_is_pre_result_design_only_and_has_exact_four_cells() -> None:
    prereg = _load()

    assert prereg["status"] == "PREREGISTERED_DESIGN_ONLY_NO_ENGINE_NO_RESULTS_SEEN"
    assert prereg["baseline_result_seen_before_candidate_lock"] is False
    assert prereg["snapshot_performance_opened_by_this_change"] is False
    assert prereg["live_or_paper_deployment_authorized"] is False
    assert (
        prereg["implementation_and_execution_governance"][
            "engine_program_or_report_implemented_by_this_change"
        ]
        is False
    )
    assert prereg["candidate_cells"] == [
        {
            "id": "C1_VSA_ONLY",
            "enabled_strategies": ["vsa_climax_test"],
            "disabled_strategies": ["grimes_abc_pullback"],
            "htf50_gate": False,
        },
        {
            "id": "C2_GRIMES_ONLY",
            "enabled_strategies": ["grimes_abc_pullback"],
            "disabled_strategies": ["vsa_climax_test"],
            "htf50_gate": False,
        },
        {
            "id": "C3_DUAL_HTF50",
            "enabled_strategies": ["vsa_climax_test", "grimes_abc_pullback"],
            "disabled_strategies": [],
            "htf50_gate": True,
        },
        {
            "id": "C4_VSA_HTF50",
            "enabled_strategies": ["vsa_climax_test"],
            "disabled_strategies": ["grimes_abc_pullback"],
            "htf50_gate": True,
        },
    ]


def test_v18_pre_result_amendment_did_not_move_candidates_or_thresholds() -> None:
    prereg = _load()

    assert prereg["pre_result_amendments"] == [
        {
            "at_utc": "2026-07-11T17:27:59Z",
            "subject": "baseline_legacy_statistics_and_funding_bindings",
            "performance_seen_before_amendment": False,
            "candidate_cells_or_thresholds_changed": False,
            "change": (
                "Before any v15p2 V2 baseline or V18 performance replay, bind the "
                "actual V2 baseline preregistration and program/report sources, the "
                "exact nine reconstructible v16/v17 trial artifacts and field paths, "
                "and every result-affecting bootstrap, sign-flip, Holm, DSR, and CSCV "
                "convention. Also record that the funding aggregate disclosure was "
                "learned after the original V18 created_at timestamp but before any "
                "baseline or challenger result. Candidate cells and all economic "
                "acceptance thresholds are unchanged."
            ),
        }
    ]
    assert prereg["created_at_utc"] == "2026-07-11T17:01:08Z"
    assert prereg["baseline_result_seen_before_candidate_lock"] is False
    assert prereg["snapshot_performance_opened_by_this_change"] is False
    assert prereg["performance_execution_authorized_by_this_artifact"] is False


def test_v18_binds_exact_v2_baseline_contract_sources_and_outputs() -> None:
    prereg = _load()
    lineage = prereg["frozen_lineage"]

    expected_sources = {
        "fair_baseline_v2_contract": {
            "path": "configs/crypto_15m_v15p2_fair_baseline_v2_prereg.yaml",
            "bytes": 39694,
            "sha256": "7a6180312bcbb1b1f9644d26dbce8bd8ac57ea4eb13fc0aa783025f069ddd511",
            "schema_version": "crypto-15m-v15p2-fair-baseline-prereg-v2",
            "alpha_result_trials_before_execution": 0,
        },
        "fair_baseline_v2_program_source": {
            "path": "src/price_action/lab/crypto_15m_v15p2_program.py",
            "bytes": 74553,
            "sha256": "d925ef902d33b01ab7b22487e304ec6a724fb14153a32b73f538c63d79879bcb",
            "raw_schema_version": "crypto-15m-v15p2-fair-baseline-run-v2",
        },
        "fair_baseline_v2_report_source": {
            "path": "src/price_action/lab/crypto_15m_v15p2_report.py",
            "bytes": 135566,
            "sha256": "0417ea087627251cd056655e83a72d7e8b38624c3158763258c830ca0e599f9f",
            "report_schema_version": "crypto-15m-v15p2-fair-baseline-report-v2",
        },
    }
    for name, expected in expected_sources.items():
        assert lineage[name] == expected
        source_path = ROOT / expected["path"]
        assert source_path.stat().st_size == expected["bytes"]
        assert _sha256(source_path) == expected["sha256"]

    comparison = prereg["fair_baseline_comparison"]
    assert comparison["canonical_contract"] == "frozen_lineage.fair_baseline_v2_contract"
    assert (
        comparison["canonical_program_source"] == "frozen_lineage.fair_baseline_v2_program_source"
    )
    assert comparison["canonical_report_source"] == "frozen_lineage.fair_baseline_v2_report_source"
    assert comparison["canonical_outputs"] == {
        "raw_json": "reports/research/crypto_15m_v15p2_fair_baseline_v2_raw.json",
        "report_json": "reports/research/crypto_15m_v15p2_fair_baseline_v2_report.json",
        "report_markdown": "reports/research/CRYPTO_15M_V15P2_FAIR_BASELINE_V2.md",
        "post_run_identity": ("configs/crypto_15m_v15p2_fair_baseline_v2_result_identity.json"),
    }
    assert comparison["result_identity_requirements"] == {
        "raw_schema_version": "crypto-15m-v15p2-fair-baseline-run-v2",
        "report_schema_version": "crypto-15m-v15p2-fair-baseline-report-v2",
        "prereg_path_bytes_sha_must_match_canonical_contract": True,
        "program_and_report_source_bytes_sha_must_match_frozen_lineage": True,
        "market_and_funding_bytes_sha_must_match_snapshots": True,
        "raw_and_report_artifact_path_bytes_sha_required": True,
        "execution_git_commit_required": True,
        "clean_source_preflight_and_unchanged_postflight_required": True,
        "raw_and_report_evidence_eligible_must_both_be_true": True,
        "post_run_identity_must_bind_all_of_the_above_before_comparison": True,
        "missing_mismatch_or_duplicate_canonical_output": ("no_better_than_baseline_claim"),
    }


def test_v18_prereg_binds_the_sealed_v3_success_identity() -> None:
    prereg = _load()
    identity_spec = prereg["frozen_lineage"]["v3_success_identity"]
    identity_path = ROOT / identity_spec["path"]
    identity = json.loads(identity_path.read_text(encoding="utf-8"))

    assert identity_path.stat().st_size == identity_spec["bytes"] == 14258
    assert _sha256(identity_path) == identity_spec["sha256"]
    assert identity["status"] == identity_spec["status"]
    assert identity["bundle"]["database"] == {
        "bytes": prereg["snapshots"]["market"]["bytes"],
        "identity_unchanged_before_and_after_independent_read_only_qa": True,
        "path": prereg["snapshots"]["market"]["path"],
        "sha256": prereg["snapshots"]["market"]["sha256"],
    }
    assert (
        identity["bundle"]["build_evidence"]["sha256"]
        == prereg["frozen_lineage"]["v3_build_evidence"]["sha256"]
    )
    assert identity["qa"]["total_rows"] == prereg["snapshots"]["market"]["total_rows"]
    assert (
        identity["qa"]["actual_ordered_primary_key_sha256"]
        == prereg["snapshots"]["market"]["ordered_primary_key_sha256"]
    )
    assert (
        identity["qa"]["actual_ordered_missing_key_sha256"]
        == prereg["snapshots"]["market"]["ordered_missing_key_sha256"]
    )


def test_v18_sma50_and_candidate_locked_time_contract_are_causal() -> None:
    prereg = _load()
    time = prereg["time_protocol"]
    htf = prereg["htf50_contract"]

    assert time["development"] == [
        "2021-06-01T00:00:00Z",
        "2023-06-01T00:00:00Z",
    ]
    assert time["pseudo_oos"] == [
        "2023-06-01T00:00:00Z",
        "2026-06-01T00:00:00Z",
    ]
    assert time["candidate_parameters_locked_before_baseline_result"] is True
    assert time["one_continuous_stateful_replay_per_cell_and_scenario"] is True
    assert time["folds_are_metric_slices_only"] is True
    assert [len(fold) for fold in time["folds"]] == [2] * 6

    assert htf["complete_UTC_day_requires_exactly_96_bars"] is True
    assert htf["latest_permitted_daily_close_for_decision_on_day_D"] == "D_minus_1"
    assert htf["lookback_days"] == 50
    assert htf["requires_50_consecutive_complete_UTC_days_ending_D_minus_1"] is True
    assert htf["moving_average"] == "exact_arithmetic_SMA50"
    assert htf["forming_day_or_any_D_day_close_forbidden"] is True
    assert htf["reaching_farther_back_to_replace_missing_day_forbidden"] is True
    assert htf["forward_fill_or_imputation_forbidden"] is True


def test_v18_costs_gates_and_trial_floor_are_frozen() -> None:
    prereg = _load()
    costs = prereg["cost_and_payoff_scenarios"]
    gates = prereg["hard_gates"]
    trials = prereg["multiple_testing_and_trial_ledger"]
    binding = prereg["validation_metrics"]["scenario_binding"]

    assert costs["bps_per_actual_fill"] == {
        "fee": 4.0,
        "spread_and_slippage": 20.0,
        "impact": 4.5,
        "total": 28.5,
    }
    assert costs["scenarios"]["C2"]["execution_cost_multiplier"] == 2.0
    assert costs["scenarios"]["C2"]["funding_multiplier"] == 2.0
    assert costs["scenarios"]["H"]["positive_price_pnl_multiplier"] == 0.50
    assert costs["scenarios"]["H"]["negative_price_pnl_multiplier"] == 1.25

    assert gates["sample"] == {
        "pseudo_oos_months": 36,
        "minimum_closed_trades": 360,
        "minimum_long_trades": 60,
        "minimum_short_trades": 60,
        "minimum_active_months": 30,
    }
    assert gates["H_return"]["trimmed_mean_monthly_pct_min"] == 10.0
    assert gates["H_return"]["median_monthly_pct_min"] == 8.0
    assert gates["H_return"]["block_bootstrap_90pct_lower_bound_pct_min"] == 6.0
    assert gates["drawdown"] == {
        "B_max_mtm_pct": 15.0,
        "worse_of_C2_H_max_mtm_pct": 20.0,
    }
    assert gates["economic_edge"]["B_pre_cost_price_pnl_over_execution_cost_min"] == 1.50
    assert gates["multiple_testing"]["cumulative_floor_deflated_sharpe_min"] == 0.95
    assert gates["multiple_testing"]["local_probability_backtest_overfit_max"] == 0.20
    assert binding == {
        "sample_counts": "H_closed_trade_ledger_by_exit_timestamp",
        "return_stability_walk_forward_and_month_concentration": "H",
        "top_5pct_trade_removal": "H",
        "true_LOSO_and_effective_symbol_count": "H",
        "direction": "C2",
        "economic_edge": "B",
        "drawdown": "B_and_worse_of_C2_H",
    }

    assert trials["audit_grade_prior_trials"] == 9
    assert trials["local_v18_trials"] == 4
    assert trials["cumulative_governed_trial_floor"] == 13
    assert trials["larger_legacy_exposure_exists"] is True
    assert trials["larger_legacy_exposure_exact_count_reconstructible"] is False
    assert trials["thirteen_is_a_floor_not_a_claim_of_total_historical_trials"] is True


def test_v18_binds_exact_v16_v17_artifacts_and_nine_prior_candidates() -> None:
    prereg = _load()
    trials = prereg["multiple_testing_and_trial_ledger"]

    expected_artifacts = {
        "v16_prereg": {
            "path": "configs/crypto_15m_v16_research_prereg.yaml",
            "bytes": 13052,
            "sha256": "bd41fc39b2e65a77b3aa2b396b676b0d4e2d315b9d3addac0e738e6f8b9e0fa3",
        },
        "v17_prereg": {
            "path": "configs/crypto_15m_v17_pairs_prereg.yaml",
            "bytes": 21064,
            "sha256": "52d6b0e433e4145e17c588be88d3f82bc7ecb91e281fab12fd5450db12b6cc52",
        },
        "v16_raw_gzip": {
            "path": "reports/research/crypto_15m_v16_primary_raw_2026-07-11.json.gz",
            "bytes": 488844,
            "sha256": "7e434d50280dadea4a730a1a8dac0f6436f92e36118082eef164f3638256265d",
            "decoded_bytes": 1888565,
            "decoded_json_sha256": (
                "9ebbe8620a7fb5b46eb958ce593e7e772a50f2380f54fc7b857f9cd488063d8e"
            ),
            "schema_version": "crypto-15m-v16-run-v1",
            "evidence_eligible_required": True,
        },
        "v17_raw_json": {
            "path": "reports/research/crypto_15m_v17_pairs_primary_raw_2026-07-11.json",
            "bytes": 162198487,
            "sha256": "73e92a02131985a8a24c195c54c165b6775decef0ea41e24b6b34991edf4d82a",
            "schema_version": "crypto-15m-v17-pairs-run-v1",
            "evidence_eligible_required": True,
        },
        "v17_raw_gzip_crosscheck": {
            "path": ("reports/research/crypto_15m_v17_pairs_primary_raw_2026-07-11.json.gz"),
            "bytes": 7091723,
            "sha256": "6d9ded77ceed025b73259c44b2527caf60a9e0eacc8a21ddeb8c2990563e369d",
            "decoded_bytes": 162198487,
            "decoded_json_sha256": (
                "73e92a02131985a8a24c195c54c165b6775decef0ea41e24b6b34991edf4d82a"
            ),
        },
        "v17_report_json": {
            "path": "reports/research/crypto_15m_v17_pairs_report_2026-07-11.json",
            "bytes": 380701,
            "sha256": "ae234c398ac1390b39ac29210f92698523322687ef332e37c43243d75201a18d",
            "schema_version": "crypto-15m-v17-pairs-report-v1",
            "evidence_eligible_required": True,
        },
    }
    assert trials["prior_artifacts"] == expected_artifacts
    for expected in expected_artifacts.values():
        artifact_path = ROOT / expected["path"]
        assert artifact_path.stat().st_size == expected["bytes"]
        assert _sha256(artifact_path) == expected["sha256"]

    expected_prior_inputs = [
        {"candidate_id": "T1_RESIDUAL_TREND_1W", "raw_artifact": "v16_raw_gzip"},
        {"candidate_id": "T2_RESIDUAL_TREND_2W", "raw_artifact": "v16_raw_gzip"},
        {"candidate_id": "T4_RESIDUAL_TREND_4W", "raw_artifact": "v16_raw_gzip"},
        {
            "candidate_id": "M1_FUNDING_RESIDUAL_REVERSION_4H_Z2",
            "raw_artifact": "v16_raw_gzip",
        },
        {
            "candidate_id": "M2_FUNDING_RESIDUAL_REVERSION_8H_Z2",
            "raw_artifact": "v16_raw_gzip",
        },
        {
            "candidate_id": "M3_FUNDING_RESIDUAL_REVERSION_4H_Z2P5",
            "raw_artifact": "v16_raw_gzip",
        },
        {"candidate_id": "DP1_EG_90D_Z2P5", "raw_artifact": "v17_raw_json"},
        {"candidate_id": "DP2_EG_180D_Z2P5", "raw_artifact": "v17_raw_json"},
        {
            "candidate_id": "DP3_EG_180D_Z3_STRICT",
            "raw_artifact": "v17_raw_json",
        },
    ]
    bindings = trials["prior_candidate_field_bindings"]
    assert bindings["input_months"] == (
        "exact_2023_06_through_2026_05_inclusive_in_chronological_order"
    )
    assert bindings["monthly_return_unit"] == "percentage_points"
    assert bindings["finite_36_values_required"] is True
    assert bindings["v16_monthly_return_pointer_template"] == (
        "/results/{candidate_id}/H/windows/pseudo_oos/monthly_returns_pct"
    )
    assert bindings["v17_monthly_return_pointer_template"] == (
        "/results/{candidate_id}/H/windows/pseudo_oos/monthly_returns_pct"
    )
    assert bindings["prior_raw_pvalue_crosscheck_pointer_template"] == (
        "/multiple_testing/program_wide_v16_plus_v17_exact_36x9/"
        "candidate_results/{candidate_id}/candidate_sign_flip_pvalue"
    )
    assert bindings["prior_periodic_sharpe_crosscheck_pointer_template"] == (
        "/multiple_testing/program_wide_v16_plus_v17_exact_36x9/"
        "candidate_results/{candidate_id}/periodic_monthly_sharpe"
    )
    assert bindings["prior_trial_sharpe_map_crosscheck_pointer"] == (
        "/multiple_testing/program_wide_v16_plus_v17_exact_36x9/trial_periodic_monthly_sharpes"
    )
    assert bindings["inputs"] == expected_prior_inputs
    assert [item["candidate_id"] for item in expected_prior_inputs] == trials[
        "canonical_candidate_order"
    ][:9]
    assert (
        "Recompute the nine seed-17 sign-flip p-values"
        in bindings["legacy_report_crosscheck_policy"]
    )
    assert "UNVERIFIABLE and fails closed" in bindings["legacy_report_crosscheck_policy"]


def test_v18_binds_validation_sources_and_every_statistical_algorithm() -> None:
    prereg = _load()
    trials = prereg["multiple_testing_and_trial_ledger"]

    expected_sources = {
        "shared_statistics": {
            "path": "src/price_action/lab/crypto_15m_validation.py",
            "bytes": 38943,
            "sha256": "6227e9f1e4d3f979dbc539ec0ee2b0e7507437a61962194c5d37a52083b6d9e9",
            "functions": [
                "trimmed_mean_pct",
                "block_bootstrap_lower_bound_pct",
                "holm_adjusted_pvalues",
                "deflated_sharpe_statistics",
                "probability_of_backtest_overfitting",
            ],
        },
        "prior_program_statistics": {
            "path": "src/price_action/lab/crypto_15m_pairs_validation.py",
            "bytes": 58684,
            "sha256": "9f0eae0bb08f45ceacdb7a3bb9c48ceb1b2f1b3469d21bd2bf572e11ecf6a95b",
            "functions": [
                "candidate_block_sign_flip_test",
                "program_wide_multiple_testing",
            ],
        },
    }
    assert trials["bound_validation_sources"] == expected_sources
    for expected in expected_sources.values():
        source_path = ROOT / expected["path"]
        assert source_path.stat().st_size == expected["bytes"]
        assert _sha256(source_path) == expected["sha256"]

    assert trials["locked_statistical_algorithms"] == {
        "missing_or_nonfinite_input": "fail_closed_UNVERIFIABLE",
        "symmetric_trimmed_mean": {
            "order": "stable_numeric_ascending",
            "cut_each_tail": "floor_n_times_0_10",
            "statistic": "arithmetic_mean_of_remaining_values",
        },
        "moving_block_bootstrap": {
            "blocks": "all_34_overlapping_consecutive_3_month_blocks_from_36_months",
            "generator": "numpy_random_default_rng_PCG64_seed_18",
            "draws_per_iteration": "12_block_indices_uniform_with_replacement",
            "assembly": "concatenate_drawn_blocks_then_take_first_36_values",
            "iterations": 20000,
            "statistic": "symmetric_10pct_trimmed_arithmetic_mean",
            "lower_quantile": 0.10,
            "quantile_method": "numpy_quantile_linear",
        },
        "sign_flip": {
            "blocks": "12_nonoverlapping_consecutive_3_month_blocks",
            "generator": "numpy_random_default_rng_PCG64_seed_18",
            "sign_draw": ("integers_0_or_1_mapped_to_minus_1_or_plus_1_independently_per_block"),
            "iterations": 20000,
            "observed_statistic": ("symmetric_10pct_trimmed_arithmetic_mean_of_36_months"),
            "null_statistic": "same_statistic_after_block_signs",
            "exceedance": "null_statistic_greater_than_or_equal_to_observed",
            "pvalue": "one_plus_exceedances_divided_by_20001",
        },
        "holm": {
            "family_order": "canonical_candidate_order_restricted_to_family",
            "sort": "ascending_raw_p_stable_ties_preserve_family_order",
            "adjusted_formula": (
                "cumulative_max_over_sorted_rank_j_of_family_size_minus_j_times_raw_p, "
                "clipped_to_1_and_returned_in_family_order"
            ),
        },
        "periodic_sharpe": {
            "formula": ("arithmetic_mean_divided_by_sample_standard_deviation_ddof_1"),
            "annualization_for_display_only": "multiply_by_sqrt_12",
            "zero_standard_deviation": ("positive_inf_negative_inf_or_zero_by_mean"),
        },
        "deflated_sharpe": {
            "implementation": "bound_shared_statistics.deflated_sharpe_statistics",
            "observed_returns": "exact_36_H_monthly_percentage_point_returns",
            "trial_distribution": (
                "exact_13_periodic_monthly_sharpes_in_canonical_candidate_order"
            ),
            "n_trials": 13,
            "periods_per_year": 12,
            "skew_and_kurtosis": "population_standardized_central_moments",
            "sharpe_standard_error_ddof": ("n_minus_1_denominator_as_bound_source"),
            "expected_max": ("euler_mascheroni_normal_order_statistic_as_bound_source"),
            "output": ("standard_normal_CDF_of_observed_minus_expected_max_over_standard_error"),
            "any_nonfinite_trial_sharpe": "fail_closed_UNVERIFIABLE",
        },
        "cscv_pbo": {
            "scope": "local_exact_36_by_4_H_matrix_only",
            "candidate_column_order": [
                "C1_VSA_ONLY",
                "C2_GRIMES_ONLY",
                "C3_DUAL_HTF50",
                "C4_VSA_HTF50",
            ],
            "slices": "numpy_array_split_36_chronological_rows_into_6_equal_slices",
            "combinations": "lexicographic_all_choose_3_of_6",
            "score": "periodic_sharpe_mean_over_sample_std_ddof_1",
            "in_sample_selection": "numpy_argmax_first_column_wins_exact_tie",
            "out_sample_rank": "pandas_average_rank_ascending",
            "relative_rank": "rank_divided_by_5",
            "logit": ("natural_log_relative_rank_divided_by_one_minus_relative_rank"),
            "probability": "fraction_of_20_logits_less_than_or_equal_to_zero",
        },
    }
    assert trials["local_H_matrix"] == ("exact_finite_36_by_4_percentage_point_monthly_returns")
    assert trials["local_holm"] == {
        "raw_p_method": "locked_statistical_algorithms.sign_flip",
        "iterations": 20000,
        "seed": 18,
        "scope": "all_4_v18_cells",
    }
    assert trials["cumulative_floor_holm"] == {
        "scope": (
            "recompute all exact reconstructible 9 prior plus 4 V18 raw pvalues "
            "under locked_statistical_algorithms.sign_flip and apply one 13-member "
            "Holm family"
        ),
        "adjusted_p_max": 0.05,
        "missing_prior_input": "fail_closed_UNVERIFIABLE",
    }
    assert trials["deflated_sharpe"] == {
        "returns": "36_month_H_percentage_point_returns",
        "n_trials_floor": 13,
        "minimum": 0.95,
        "trial_distribution": ("exact_13_periodic_monthly_sharpes_in_canonical_candidate_order"),
        "missing_prior_trial_distribution": "fail_closed_UNVERIFIABLE",
    }
    assert trials["probability_backtest_overfit"] == {
        "method": "locked_statistical_algorithms.cscv_pbo",
        "matrix": "exact_finite_36_by_4_H_monthly_return_matrix",
        "slices": 6,
        "maximum": 0.20,
    }


def test_v18_comparison_and_prospective_gates_cannot_auto_promote() -> None:
    prereg = _load()
    comparison = prereg["fair_baseline_comparison"]
    prospective = prereg["prospective_evidence_gate"]

    assert comparison["baseline_must_be_run_on_exact_same_V3_market_and_funding_snapshots"] is True
    assert comparison["old_21p36_pool_headline_forbidden"] is True
    assert comparison["pass_logic"] == "rule_1_or_rule_2_and_stability_noninferiority"
    assert (
        comparison["rule_1"]["challenger_H_trimmed_mean_monthly_pct_min_formula"]
        == "max_10pct_or_baseline_plus_1p5pp"
    )
    assert (
        comparison["rule_2"]["challenger_H_max_MTM_drawdown_reduction_vs_baseline_min_fraction"]
        == 0.25
    )

    assert prospective["minimum_calendar_days"] == 90
    assert prospective["minimum_closed_trades"] == 100
    assert prospective["stop_when"] == "both_minimums_satisfied_whichever_occurs_later"
    assert prospective["integrity_failures_allowed"] == 0
    assert prospective["net_return_must_be_positive"] is True
    assert prospective["max_MTM_drawdown_pct"] == 10.0
    assert prospective["automatic_live_deployment_forbidden"] is True
