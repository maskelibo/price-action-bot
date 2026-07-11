from __future__ import annotations

import copy
import gzip
import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest
import yaml

from price_action.lab.crypto_15m_pairs_validation import program_wide_multiple_testing
from price_action.lab.crypto_15m_v18_validation import (
    CUMULATIVE_CANDIDATE_IDS,
    FROZEN_H_MONTHS,
    LEGACY_CANDIDATE_IDS,
    LOCAL_CANDIDATE_IDS,
    V18ValidationContractError,
    evaluate_v18_absolute_hard_gates,
    exact_h_monthly_returns,
    exact_local_h_matrix,
    load_legacy_trial_inputs,
    rank_v18_candidates,
    v18_block_bootstrap_lower_bound_pct,
    v18_candidate_sign_flip_test,
    v18_multiple_testing,
)
from price_action.lab.crypto_15m_validation import block_bootstrap_lower_bound_pct

ROOT = Path(__file__).resolve().parents[1]


def _series(values: np.ndarray) -> pd.Series:
    return pd.Series(values, index=FROZEN_H_MONTHS, dtype=float)


def _nonconstant_candidates(candidate_ids: tuple[str, ...]) -> dict[str, pd.Series]:
    phase = np.linspace(0.0, 4.0 * np.pi, 36)
    return {
        candidate: _series(1.0 + index / 20.0 + np.sin(phase + index / 7.0))
        for index, candidate in enumerate(candidate_ids)
    }


def test_exact_h_contract_rejects_order_month_and_nonfinite_drift() -> None:
    values = {str(month): float(index) for index, month in enumerate(FROZEN_H_MONTHS)}

    result = exact_h_monthly_returns(values)

    assert result.index.equals(FROZEN_H_MONTHS)
    assert result.iloc[-1] == 35.0
    with pytest.raises(V18ValidationContractError, match="chronological months"):
        exact_h_monthly_returns(dict(reversed(values.items())))
    with pytest.raises(V18ValidationContractError, match="2023-06 through 2026-05"):
        exact_h_monthly_returns(_series(np.arange(36.0)).set_axis(FROZEN_H_MONTHS + 1))
    invalid = values.copy()
    invalid["2024-01"] = float("nan")
    with pytest.raises(V18ValidationContractError, match="finite number"):
        exact_h_monthly_returns(invalid)


def test_seed18_sign_flip_is_exact_one_sided_and_resets_rng_per_candidate() -> None:
    values = _series(2.0 + np.sin(np.linspace(0.0, 3.0 * np.pi, 36)))

    first = v18_candidate_sign_flip_test(values)
    second = v18_candidate_sign_flip_test(values)

    assert first == second
    assert first["seed"] == 18
    assert first["iterations"] == 20_000
    assert first["blocks"] == 12
    assert first["block_months"] == 3
    assert (
        first["candidate_sign_flip_pvalue"] == (1 + first["null_exceedances_gte_observed"]) / 20_001
    )


def test_seed18_bootstrap_wrapper_matches_bound_shared_implementation() -> None:
    values = _series(np.linspace(-2.0, 5.0, 36) + np.sin(np.arange(36)))

    wrapped = v18_block_bootstrap_lower_bound_pct(values)
    direct = block_bootstrap_lower_bound_pct(
        values,
        block_months=3,
        iterations=20_000,
        confidence=0.90,
        seed=18,
        trim_fraction=0.10,
    )

    assert wrapped == direct


def test_v18_multiple_testing_binds_local4_cumulative13_dsr_and_local_pbo() -> None:
    legacy = _nonconstant_candidates(LEGACY_CANDIDATE_IDS)
    local = _nonconstant_candidates(LOCAL_CANDIDATE_IDS)

    result = v18_multiple_testing(local, legacy)

    assert result["status"] == "OK"
    assert result["seed"] == 18
    local_result = result["local_exact_36x4"]
    cumulative = result["cumulative_floor_exact_36x13"]
    assert local_result["candidate_order"] == list(LOCAL_CANDIDATE_IDS)
    assert cumulative["candidate_order"] == list(CUMULATIVE_CANDIDATE_IDS)
    assert local_result["pbo"]["status"] == "OK"
    assert local_result["pbo"]["combinations"] == 20
    assert cumulative["candidate_count"] == 13
    assert len(cumulative["trial_periodic_monthly_sharpes"]) == 13
    for candidate in LOCAL_CANDIDATE_IDS:
        metrics = local_result["candidate_results"][candidate]
        assert 0.0 <= metrics["local_holm_fwer_adjusted_p"] <= 1.0
        assert 0.0 <= metrics["cumulative_floor_holm_fwer_adjusted_p"] <= 1.0
        assert 0.0 <= metrics["cumulative_floor_deflated_sharpe"] <= 1.0
    json.dumps(result, allow_nan=False)


def test_v18_multiple_testing_fails_closed_on_nonfinite_trial_sharpe() -> None:
    legacy = _nonconstant_candidates(LEGACY_CANDIDATE_IDS)
    local = _nonconstant_candidates(LOCAL_CANDIDATE_IDS)
    legacy[LEGACY_CANDIDATE_IDS[0]] = _series(np.ones(36))

    with pytest.raises(V18ValidationContractError, match="UNVERIFIABLE"):
        v18_multiple_testing(local, legacy)


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _write_bound_file(root: Path, relative: str, value: bytes) -> dict[str, Any]:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(value)
    return {"path": relative, "bytes": len(value), "sha256": _sha(value)}


def _month_mapping(values: pd.Series) -> dict[str, float]:
    return {str(month): float(values.loc[month]) for month in FROZEN_H_MONTHS}


def _raw_payload(candidates: tuple[str, ...], values: dict[str, pd.Series], schema: str) -> dict:
    return {
        "schema_version": schema,
        "evidence_eligible": True,
        "evidence_ineligible_reasons": [],
        "candidate_ids": list(candidates),
        "candidate_count": len(candidates),
        "scenario_order": ["B", "C2", "H"],
        "results": {
            candidate: {
                "B": {},
                "C2": {},
                "H": {
                    "windows": {
                        "pseudo_oos": {
                            "monthly_returns_unit": "percentage_points",
                            "monthly_returns_pct": _month_mapping(values[candidate]),
                        }
                    }
                },
            }
            for candidate in candidates
        },
    }


def _strict_json_bytes(value: Any) -> bytes:
    return json.dumps(value, separators=(",", ":"), allow_nan=False).encode()


def _legacy_fixture(tmp_path: Path) -> dict[str, Any]:
    canonical_trials = yaml.safe_load(
        (ROOT / "configs/crypto_15m_v18_challenger_prereg.yaml").read_text()
    )["multiple_testing_and_trial_ledger"]
    values = _nonconstant_candidates(LEGACY_CANDIDATE_IDS)
    matrix = pd.DataFrame(values, index=FROZEN_H_MONTHS)
    seed17 = program_wide_multiple_testing(matrix)
    v16 = _strict_json_bytes(_raw_payload(_V16_IDS, values, "crypto-15m-v16-run-v1"))
    v17 = _strict_json_bytes(_raw_payload(_V17_IDS, values, "crypto-15m-v17-pairs-run-v1"))
    report = _strict_json_bytes(
        {
            "schema_version": "crypto-15m-v17-pairs-report-v1",
            "evidence_eligible": True,
            "multiple_testing": {
                "program_wide_v16_plus_v17_exact_36x9": seed17,
            },
        }
    )
    v16_gzip = gzip.compress(v16, mtime=0)
    v17_gzip = gzip.compress(v17, mtime=0)
    shared = _write_bound_file(tmp_path, "src/shared.py", b"shared-frozen")
    prior = _write_bound_file(tmp_path, "src/prior.py", b"prior-frozen")
    v16_prereg = _write_bound_file(tmp_path, "configs/v16.yaml", b"v16-prereg")
    v17_prereg = _write_bound_file(tmp_path, "configs/v17.yaml", b"v17-prereg")
    v16_spec = _write_bound_file(tmp_path, "reports/v16.json.gz", v16_gzip)
    v16_spec.update(
        {
            "decoded_bytes": len(v16),
            "decoded_json_sha256": _sha(v16),
            "schema_version": "crypto-15m-v16-run-v1",
            "evidence_eligible_required": True,
        }
    )
    v17_spec = _write_bound_file(tmp_path, "reports/v17.json", v17)
    v17_spec.update(
        {
            "schema_version": "crypto-15m-v17-pairs-run-v1",
            "evidence_eligible_required": True,
        }
    )
    v17_gzip_spec = _write_bound_file(tmp_path, "reports/v17.json.gz", v17_gzip)
    v17_gzip_spec.update(
        {
            "decoded_bytes": len(v17),
            "decoded_json_sha256": _sha(v17),
        }
    )
    report_spec = _write_bound_file(tmp_path, "reports/v17-report.json", report)
    report_spec.update(
        {
            "schema_version": "crypto-15m-v17-pairs-report-v1",
            "evidence_eligible_required": True,
        }
    )
    return {
        "multiple_testing_and_trial_ledger": {
            "audit_grade_prior_trials": 9,
            "local_v18_trials": 4,
            "cumulative_governed_trial_floor": 13,
            "thirteen_is_a_floor_not_a_claim_of_total_historical_trials": True,
            "canonical_candidate_order": list(CUMULATIVE_CANDIDATE_IDS),
            "locked_statistical_algorithms": copy.deepcopy(
                canonical_trials["locked_statistical_algorithms"]
            ),
            "local_holm": copy.deepcopy(canonical_trials["local_holm"]),
            "cumulative_floor_holm": copy.deepcopy(canonical_trials["cumulative_floor_holm"]),
            "deflated_sharpe": copy.deepcopy(canonical_trials["deflated_sharpe"]),
            "probability_backtest_overfit": copy.deepcopy(
                canonical_trials["probability_backtest_overfit"]
            ),
            "bound_validation_sources": {
                "shared_statistics": shared,
                "prior_program_statistics": prior,
            },
            "prior_artifacts": {
                "v16_prereg": v16_prereg,
                "v17_prereg": v17_prereg,
                "v16_raw_gzip": v16_spec,
                "v17_raw_json": v17_spec,
                "v17_raw_gzip_crosscheck": v17_gzip_spec,
                "v17_report_json": report_spec,
            },
            "prior_candidate_field_bindings": {
                **copy.deepcopy(canonical_trials["prior_candidate_field_bindings"]),
                "inputs": [
                    {
                        "candidate_id": candidate,
                        "raw_artifact": (
                            "v16_raw_gzip" if candidate in _V16_IDS else "v17_raw_json"
                        ),
                    }
                    for candidate in LEGACY_CANDIDATE_IDS
                ],
            },
        }
    }


_V16_IDS = LEGACY_CANDIDATE_IDS[:6]
_V17_IDS = LEGACY_CANDIDATE_IDS[6:]


def test_legacy_loader_verifies_artifacts_paths_and_exact_seed17_report(tmp_path: Path) -> None:
    prereg = _legacy_fixture(tmp_path)

    result = load_legacy_trial_inputs(prereg, repo_root=tmp_path)

    assert result.monthly_returns.shape == (36, 9)
    assert tuple(result.monthly_returns) == LEGACY_CANDIDATE_IDS
    assert result.seed17_crosscheck["status"] == "EXACT_SEED17_REPORT_CROSSCHECK_OK"
    assert result.seed17_crosscheck["trial_sharpe_map_exact"] is True


def test_canonical_legacy_artifacts_smoke_without_exposing_performance_values() -> None:
    prereg = yaml.safe_load((ROOT / "configs/crypto_15m_v18_challenger_prereg.yaml").read_text())
    specs = prereg["multiple_testing_and_trial_ledger"]["prior_artifacts"]
    required = [ROOT / specs[name]["path"] for name in specs]
    if not all(path.is_file() for path in required):
        pytest.skip("large canonical legacy artifacts are not present in this checkout")

    result = load_legacy_trial_inputs(prereg, repo_root=ROOT)

    assert result.monthly_returns.shape == (36, 9)
    assert tuple(result.monthly_returns) == LEGACY_CANDIDATE_IDS
    assert result.seed17_crosscheck == {
        "status": "EXACT_SEED17_REPORT_CROSSCHECK_OK",
        "candidate_count": 9,
        "months": 36,
        "seed": 17,
        "iterations": 20_000,
        "candidate_pvalues_and_sharpes_exact": True,
        "trial_sharpe_map_exact": True,
    }


def test_legacy_loader_fails_when_bound_report_no_longer_reconstructs(tmp_path: Path) -> None:
    prereg = _legacy_fixture(tmp_path)
    trials = prereg["multiple_testing_and_trial_ledger"]
    report_spec = trials["prior_artifacts"]["v17_report_json"]
    report_path = tmp_path / report_spec["path"]
    report = json.loads(report_path.read_text())
    candidate_result = report["multiple_testing"]["program_wide_v16_plus_v17_exact_36x9"][
        "candidate_results"
    ][LEGACY_CANDIDATE_IDS[0]]
    candidate_result["candidate_sign_flip_pvalue"] += 0.001
    changed = _strict_json_bytes(report)
    report_path.write_bytes(changed)
    report_spec["bytes"] = len(changed)
    report_spec["sha256"] = _sha(changed)

    with pytest.raises(V18ValidationContractError, match="exact seed-17 reconstruction"):
        load_legacy_trial_inputs(prereg, repo_root=tmp_path)


def _passing_gate_metrics() -> dict[str, Any]:
    return {
        "sample": {
            "pseudo_oos_months": 36,
            "closed_trades": 400,
            "long_trades": 200,
            "short_trades": 200,
            "active_months": 36,
        },
        "H_return": {
            "trimmed_mean_monthly_pct": 12.0,
            "median_monthly_pct": 10.0,
            "block_bootstrap_90pct_lower_bound_pct": 8.0,
        },
        "H_stability": {
            "negative_months": 2,
            "months_below_minus_1pct": 1,
            "worst_month_pct": -3.0,
        },
        "C2_return": {"trimmed_mean_monthly_pct": 9.0, "median_monthly_pct": 7.0},
        "drawdown": {
            "B_max_mtm_pct": 10.0,
            "H_max_mtm_pct": 11.0,
            "worse_of_C2_H_max_mtm_pct": 12.0,
        },
        "walk_forward": {
            "positive_folds": 6,
            "total_folds": 6,
            "worst_six_month_fold_pct": 1.0,
            "H_oos_to_development_trimmed_return_ratio": 0.8,
            "H_oos_to_development_drawdown_ratio": 1.2,
            "denominators_positive": True,
        },
        "economic_edge": {
            "B_pre_cost_price_pnl_over_execution_cost": 2.0,
            "denominator_execution_cost_positive": True,
            "funding_excluded_and_reported_separately": True,
        },
        "direction": {"long_C2_net_positive": True, "short_C2_net_positive": True},
        "concentration": {
            "best_month_positive_pnl_share": 0.10,
            "best_3_month_positive_pnl_share": 0.30,
            "mean_after_best_3_months_removed_pct": 8.0,
            "net_after_top_5pct_trades_removed_positive": True,
            "effective_symbol_count": 8.0,
            "all_true_leave_one_symbol_out_replays_positive": True,
        },
        "multiple_testing": {
            "local_holm_fwer_adjusted_p": 0.04,
            "cumulative_floor_holm_fwer_adjusted_p": 0.04,
            "cumulative_floor_deflated_sharpe": 0.97,
            "local_probability_backtest_overfit": 0.10,
        },
        "turnover": {"H_filled_gross_turnover": 100.0},
    }


def test_absolute_gates_fail_closed_and_ranking_uses_all_tie_breakers() -> None:
    prereg = yaml.safe_load((ROOT / "configs/crypto_15m_v18_challenger_prereg.yaml").read_text())
    hard_gates = prereg["hard_gates"]
    passing = _passing_gate_metrics()

    result = evaluate_v18_absolute_hard_gates(passing, hard_gates=hard_gates)

    assert result["passed"] is True
    missing = copy.deepcopy(passing)
    del missing["multiple_testing"]["cumulative_floor_deflated_sharpe"]
    failed = evaluate_v18_absolute_hard_gates(missing, hard_gates=hard_gates)
    assert failed["passed"] is False
    assert (
        failed["checks"]["multiple_testing.cumulative_floor_deflated_sharpe_min"]["reason"]
        == "MISSING_METRIC"
    )

    metrics = {candidate: copy.deepcopy(passing) for candidate in LOCAL_CANDIDATE_IDS}
    metrics["C1_VSA_ONLY"]["H_return"]["trimmed_mean_monthly_pct"] = 16.0
    metrics["C2_GRIMES_ONLY"]["H_return"]["trimmed_mean_monthly_pct"] = 18.0
    metrics["C2_GRIMES_ONLY"]["drawdown"]["H_max_mtm_pct"] = 10.0
    metrics["C1_VSA_ONLY"]["drawdown"]["H_max_mtm_pct"] = 11.0
    gates = {candidate: {"passed": True} for candidate in LOCAL_CANDIDATE_IDS}

    ranking = rank_v18_candidates(metrics, absolute_gate_results=gates)

    assert ranking.iloc[0]["candidate_id"] == "C2_GRIMES_ONLY"
    assert ranking.iloc[0]["H_rank_value_pct"] == 15.0
    assert list(ranking["rank"]) == [1, 2, 3, 4]


def test_local_matrix_rejects_candidate_permutation() -> None:
    candidates = _nonconstant_candidates(LOCAL_CANDIDATE_IDS)
    permuted = {candidate: candidates[candidate] for candidate in reversed(LOCAL_CANDIDATE_IDS)}

    with pytest.raises(V18ValidationContractError, match="IDs/order"):
        exact_local_h_matrix(permuted)
