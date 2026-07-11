import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import yaml

from price_action.lab.crypto_15m_pairs_validation import (
    DEFAULT_V17_HARD_GATES,
    DESCRIPTIVE_ATTRIBUTION_ONLY,
    FROZEN_H_MONTHS,
    FROZEN_PRIMARY_SYMBOLS,
    FROZEN_PROGRAM_CANDIDATE_IDS,
    FROZEN_V17_CANDIDATE_IDS,
    TRUE_LOSO_OK,
    TRUE_LOSO_UNAVAILABLE,
    candidate_block_sign_flip_test,
    descriptive_symbol_attribution,
    entry_regime_statistics,
    episode_concentration_statistics,
    evaluate_v17_hard_gates,
    exact_h_candidate_matrix,
    exact_h_monthly_returns,
    exact_program_candidate_matrix,
    h_monthly_statistics,
    program_wide_multiple_testing,
    rank_h_candidates,
    three_candidate_multiple_testing,
    true_loso_statistics,
)


def _nonconstant_candidates() -> dict[str, np.ndarray]:
    phase = np.linspace(0.0, 4.0 * np.pi, 36)
    return {
        "DP1": 4.0 + np.sin(phase),
        "DP2": 3.0 + 0.8 * np.cos(phase),
        "DP3": 2.0 + np.tile([-0.75, 0.75], 18),
    }


def test_exact_h_months_require_36_finite_chronological_observations() -> None:
    months = pd.period_range("2023-06", periods=36, freq="M")
    returns = pd.Series(np.arange(36, dtype=float), index=months)

    assert exact_h_monthly_returns(returns).tolist() == list(np.arange(36, dtype=float))
    with pytest.raises(ValueError, match="exactly 36"):
        exact_h_monthly_returns(returns.iloc[:-1])
    with pytest.raises(ValueError, match="finite"):
        exact_h_monthly_returns(np.r_[np.arange(35, dtype=float), np.nan])
    with pytest.raises(ValueError, match="one-dimensional"):
        exact_h_monthly_returns(np.ones((6, 6)))
    with pytest.raises(ValueError, match="chronological"):
        exact_h_monthly_returns(returns.iloc[::-1])
    gapped = returns.copy()
    gapped.index = gapped.index.where(gapped.index != months[-1], months[-1] + 1)
    with pytest.raises(ValueError, match="consecutive"):
        exact_h_monthly_returns(gapped)

    mapped_gap = {
        str(month): float(index)
        for index, month in enumerate([*months[:18], *months[19:], months[-1] + 1])
    }
    with pytest.raises(ValueError, match="consecutive"):
        exact_h_monthly_returns(mapped_gap)


def test_exact_candidate_matrix_accepts_mapping_and_rejects_wrong_shape() -> None:
    candidates = _nonconstant_candidates()
    matrix = exact_h_candidate_matrix(candidates, enforce_frozen_contract=False)

    assert matrix.shape == (36, 3)
    assert matrix.columns.tolist() == ["DP1", "DP2", "DP3"]
    with pytest.raises(ValueError, match="exact shape"):
        exact_h_candidate_matrix(np.ones((35, 3)), enforce_frozen_contract=False)
    with pytest.raises(ValueError, match="finite"):
        bad = matrix.copy()
        bad.iloc[0, 0] = np.inf
        exact_h_candidate_matrix(bad, enforce_frozen_contract=False)

    first_months = pd.period_range("2023-06", periods=36, freq="M")
    shifted_months = pd.period_range("2023-07", periods=36, freq="M")
    misaligned = {
        "DP1": pd.Series(candidates["DP1"], index=first_months),
        "DP2": pd.Series(candidates["DP2"], index=first_months),
        "DP3": pd.Series(candidates["DP3"], index=shifted_months),
    }
    with pytest.raises(ValueError, match="identical calendar months"):
        exact_h_candidate_matrix(misaligned, enforce_frozen_contract=False)


def test_frozen_matrices_bind_candidate_identity_and_pseudo_oos_calendar() -> None:
    local = pd.DataFrame(np.ones((36, 3)), index=FROZEN_H_MONTHS, columns=FROZEN_V17_CANDIDATE_IDS)
    program = pd.DataFrame(
        np.ones((36, 9)),
        index=FROZEN_H_MONTHS,
        columns=FROZEN_PROGRAM_CANDIDATE_IDS,
    )

    assert exact_h_candidate_matrix(local).shape == (36, 3)
    assert exact_program_candidate_matrix(program).shape == (36, 9)
    with pytest.raises(ValueError, match="candidate IDs/order"):
        exact_h_candidate_matrix(local.rename(columns={local.columns[0]: "renamed"}))
    with pytest.raises(ValueError, match="2023-06 through 2026-05"):
        exact_program_candidate_matrix(program.set_axis(FROZEN_H_MONTHS + 1))


def test_h_statistics_bind_trim_bootstrap_length_seed_and_quantile() -> None:
    returns = np.array([-5.0] * 3 + [10.0] * 30 + [100.0] * 3)
    statistics = h_monthly_statistics(
        returns, monthly_pnl=returns * 100.0, enforce_frozen_period=False
    )

    assert statistics["pseudo_oos_months"] == 36
    assert statistics["trimmed_mean_monthly_pct"] == pytest.approx(10.0)
    assert statistics["bootstrap_block_months"] == 3
    assert statistics["bootstrap_iterations"] == 20_000
    assert statistics["bootstrap_seed"] == 17
    assert statistics["bootstrap_lower_quantile"] == pytest.approx(0.10)
    assert np.isfinite(statistics["block_bootstrap_90pct_lower_bound_pct"])


def test_h_month_concentration_uses_cash_pnl_not_return_percentages() -> None:
    returns = np.linspace(1.0, 2.0, 36)
    monthly_pnl = np.ones(36)
    monthly_pnl[0] = 100.0

    statistics = h_monthly_statistics(returns, monthly_pnl=monthly_pnl, enforce_frozen_period=False)

    assert statistics["best_month_positive_pnl_share"] == pytest.approx(100.0 / 135.0)

    returns_dated = pd.Series(returns, index=pd.period_range("2023-06", periods=36, freq="M"))
    pnl_shifted = pd.Series(monthly_pnl, index=pd.period_range("2023-07", periods=36, freq="M"))
    with pytest.raises(ValueError, match="identical calendar months"):
        h_monthly_statistics(returns_dated, monthly_pnl=pnl_shifted)

    shifted_index = pd.period_range("2023-07", periods=36, freq="M")
    with pytest.raises(ValueError, match="2023-06 through 2026-05"):
        h_monthly_statistics(
            pd.Series(returns, index=shifted_index),
            monthly_pnl=pd.Series(monthly_pnl, index=shifted_index),
        )


def test_candidate_sign_flip_is_seeded_one_sided_and_uses_add_one_pvalue() -> None:
    returns = 2.0 + np.sin(np.linspace(0.0, 3.0 * np.pi, 36))
    first = candidate_block_sign_flip_test(returns)
    second = candidate_block_sign_flip_test(returns)

    assert first == second
    assert first["blocks"] == 12
    assert first["block_months"] == 3
    assert first["candidate_sign_flip_pvalue"] == pytest.approx(
        (1 + first["null_exceedances_gte_observed"]) / 20_001
    )
    assert 0.0 < first["candidate_sign_flip_pvalue"] <= 1.0
    with pytest.raises(ValueError, match="locked"):
        candidate_block_sign_flip_test(returns, iterations=1_000)


def test_three_candidate_multiple_testing_runs_holm_dsr_and_36x3_pbo() -> None:
    result = three_candidate_multiple_testing(
        _nonconstant_candidates(), enforce_frozen_contract=False
    )

    assert result["candidate_count"] == 3
    assert result["months"] == 36
    assert result["pbo_slices"] == 6
    assert result["pbo"]["status"] == "OK"
    assert result["pbo"]["combinations"] == 20
    assert set(result["candidate_results"]) == {"DP1", "DP2", "DP3"}
    for candidate in result["candidate_results"].values():
        assert candidate["deflated_sharpe_status"] == "OK"
        assert candidate["n_trials"] == 3
        assert 0.0 <= candidate["holm_fwer_adjusted_p"] <= 1.0
        assert 0.0 <= candidate["deflated_sharpe"] <= 1.0


def test_degenerate_trial_sharpe_is_explicit_and_strict_json_finite() -> None:
    candidates = _nonconstant_candidates()
    candidates["DP1"] = np.ones(36)

    result = three_candidate_multiple_testing(candidates, enforce_frozen_contract=False)

    assert all(
        candidate["deflated_sharpe_status"] == "DEGENERATE_TRIAL_SHARPE"
        for candidate in result["candidate_results"].values()
    )
    assert result["trial_periodic_monthly_sharpes"]["DP1"] is None
    json.dumps(result, allow_nan=False)


def test_program_wide_multiple_testing_requires_exact_36_by_9_trials() -> None:
    phase = np.linspace(0.0, 4.0 * np.pi, 36)
    candidates = {
        f"trial_{index + 1}": 1.0 + 0.1 * index + np.sin(phase + index / 3.0) for index in range(9)
    }

    matrix = exact_program_candidate_matrix(candidates, enforce_frozen_contract=False)
    result = program_wide_multiple_testing(matrix, enforce_frozen_contract=False)

    assert matrix.shape == (36, 9)
    assert result["candidate_count"] == 9
    assert result["scope"] == "CUMULATIVE_V16_PLUS_V17"
    assert result["pbo"]["status"] == "OK"
    assert result["pbo"]["combinations"] == 20
    assert all(candidate["n_trials"] == 9 for candidate in result["candidate_results"].values())
    with pytest.raises(ValueError, match="exact shape"):
        exact_program_candidate_matrix(np.ones((36, 8)), enforce_frozen_contract=False)


def test_h_ranking_caps_only_rank_value_and_uses_locked_tie_break_order() -> None:
    candidates = {
        "DP1": np.full(36, 20.0),
        "DP2": np.full(36, 16.0),
        "DP3": np.full(36, 14.0),
    }
    ranked = rank_h_candidates(
        candidates,
        h_max_drawdowns={"DP1": 10.0, "DP2": 5.0, "DP3": 1.0},
        turnovers={"DP1": 100.0, "DP2": 200.0, "DP3": 1.0},
        enforce_frozen_contract=False,
    )

    assert ranked["candidate_id"].tolist() == ["DP2", "DP1", "DP3"]
    assert ranked["H_rank_value_pct"].tolist() == [15.0, 15.0, 14.0]
    assert ranked.loc[ranked["candidate_id"] == "DP1", "H_trimmed_mean_monthly_pct"].item() == 20.0

    exact_tie = rank_h_candidates(
        {name: np.full(36, 20.0) for name in ("DP1", "DP2", "DP3")},
        h_max_drawdowns={name: 5.0 for name in ("DP1", "DP2", "DP3")},
        turnovers={name: 1.0 for name in ("DP1", "DP2", "DP3")},
        enforce_frozen_contract=False,
    )
    assert exact_tie["candidate_id"].tolist() == ["DP1", "DP2", "DP3"]
    assert exact_tie["resolved_by_lexicographic_candidate_id"].all()
    assert not exact_tie["preregistered_rank_tie"].any()


def test_episode_concentration_combines_terminal_but_keeps_closed_count_separate() -> None:
    closed = pd.DataFrame({"net_pnl": np.ones(19)})
    terminal = pd.DataFrame({"net_pnl": [100.0, 50.0]})
    statistics = episode_concentration_statistics(closed, terminal)

    assert statistics["closed_pair_episodes"] == 19
    assert statistics["terminal_pair_episodes"] == 2
    assert statistics["episode_count_including_terminal"] == 21
    assert statistics["top_5pct_pair_episode_count"] == 2
    assert statistics["top_5pct_pair_episodes_positive_pnl_share"] == pytest.approx(150 / 169)
    assert statistics["net_after_top_5pct_pair_episodes_removed"] == pytest.approx(19.0)


def test_episode_concentration_accepts_plain_pnl_array() -> None:
    statistics = episode_concentration_statistics(np.array([10.0, -2.0, 1.0]))

    assert statistics["closed_pair_episodes"] == 3
    assert statistics["top_5pct_pair_episode_count"] == 1
    assert statistics["net_after_top_5pct_pair_episodes_removed"] == pytest.approx(-1.0)


def test_direction_and_entry_counts_are_by_atomic_entry_regime() -> None:
    episodes = pd.DataFrame(
        {
            "entry_regime": ["high_spread", "low_spread", "high_spread"],
            "net_pnl": [10.0, 4.0, -2.0],
        }
    )
    statistics = entry_regime_statistics(episodes)

    assert statistics["pair_episodes"] == 3
    assert statistics["high_spread_entries"] == 2
    assert statistics["low_spread_entries"] == 1
    assert statistics["unknown_entry_regime_entries"] == 0
    assert statistics["high_spread_C2_net_pnl"] == pytest.approx(8.0)
    assert statistics["low_spread_C2_net_pnl"] == pytest.approx(4.0)

    with pytest.raises(ValueError, match="unknown entry_regime"):
        entry_regime_statistics(pd.DataFrame({"entry_regime": ["bad"], "net_pnl": [99.0]}))


def test_symbol_weight_attribution_is_explicitly_descriptive_not_loso() -> None:
    episodes = [
        {
            "y_symbol": "A",
            "x_symbol": "B",
            "gross_weight_y": 0.25,
            "gross_weight_x": 0.75,
            "net_pnl": 100.0,
        },
        {
            "y_symbol": "B",
            "x_symbol": "C",
            "gross_weight_y": 0.50,
            "gross_weight_x": 0.50,
            "net_pnl": -40.0,
        },
    ]
    result = descriptive_symbol_attribution(episodes)

    assert result["status"] == DESCRIPTIVE_ATTRIBUTION_ONLY
    assert result["symbol_attributed_net_pnl"] == pytest.approx({"A": 25.0, "B": 55.0, "C": -20.0})
    assert result["total_attributed_net_pnl"] == pytest.approx(60.0)
    assert result["true_loso_available"] is False
    assert result["all_true_leave_one_symbol_out_replays_positive"] is None
    assert result["effective_symbol_count"] is None


def test_true_loso_is_unavailable_without_complete_replay_mapping() -> None:
    absent = true_loso_statistics(
        100.0,
        None,
        expected_symbols=["A", "B", "C"],
        enforce_frozen_primary=False,
    )
    unspecified = true_loso_statistics(100.0, {"A": 70.0}, enforce_frozen_primary=False)
    incomplete = true_loso_statistics(
        100.0,
        {"A": 70.0, "B": 50.0},
        expected_symbols=["A", "B", "C"],
        enforce_frozen_primary=False,
    )

    assert absent["status"] == TRUE_LOSO_UNAVAILABLE
    assert absent["all_true_leave_one_symbol_out_replays_positive"] is None
    assert unspecified["status"] == TRUE_LOSO_UNAVAILABLE
    assert unspecified["expected_symbol_set_missing"] is True
    assert incomplete["status"] == TRUE_LOSO_UNAVAILABLE
    assert incomplete["missing_symbols"] == ["C"]

    invalid = true_loso_statistics(
        100.0,
        {"A": np.nan},
        expected_symbols=["A"],
        enforce_frozen_primary=False,
    )
    assert invalid["replay_net_pnl_by_omitted_symbol"] == {"A": None}
    json.dumps(invalid, allow_nan=False)


def test_true_loso_effective_n_uses_positive_counterfactual_marginals() -> None:
    result = true_loso_statistics(
        100.0,
        {"A": 70.0, "B": 50.0, "C": 10.0},
        expected_symbols=["A", "B", "C"],
        enforce_frozen_primary=False,
    )

    assert result["status"] == TRUE_LOSO_OK
    assert result["symbol_marginal_net_pnl"] == pytest.approx({"A": 30.0, "B": 50.0, "C": 90.0})
    expected_n = 1.0 / sum((value / 170.0) ** 2 for value in (30.0, 50.0, 90.0))
    assert result["effective_symbol_count"] == pytest.approx(expected_n)
    assert result["all_true_leave_one_symbol_out_replays_positive"] is True


def test_true_loso_default_binds_all_thirteen_frozen_primary_symbols() -> None:
    subset = true_loso_statistics(100.0, {"ETH/USDT": 10.0}, expected_symbols=["ETH/USDT"])
    assert subset["status"] == TRUE_LOSO_UNAVAILABLE
    assert subset["frozen_primary_symbol_set_mismatch"] is True

    complete = true_loso_statistics(
        100.0,
        {symbol: 10.0 for symbol in FROZEN_PRIMARY_SYMBOLS},
        expected_symbols=sorted(FROZEN_PRIMARY_SYMBOLS),
    )
    assert complete["status"] == TRUE_LOSO_OK
    assert complete["effective_symbol_count"] == pytest.approx(13.0)


def _representative_gate_contract() -> dict[str, dict[str, object]]:
    return {
        "sample": {"minimum_closed_pair_episodes": 120},
        "H_return": {"trimmed_mean_monthly_pct_min": 10.0},
        "H_stability": {"negative_months_max": 4},
        "C2_return": {"total_return_must_be_positive": True},
        "drawdown": {"B_max_mtm_pct": 15.0},
        "walk_forward": {"positive_folds_min": 5},
        "economic_edge": {
            "B_closed_pair_price_pnl_before_execution_and_funding_must_be_positive": True
        },
        "concentration": {"all_true_leave_one_symbol_out_replays_positive": True},
        "direction": {"high_spread_C2_net_must_be_positive": True},
        "multiple_testing": {"holm_fwer_adjusted_p_max": 0.05},
    }


def _representative_passing_metrics() -> dict[str, dict[str, object]]:
    return {
        "sample": {"closed_pair_episodes": 121},
        "H_return": {"trimmed_mean_monthly_pct": 11.0},
        "H_stability": {"negative_months": 3},
        "C2_return": {"total_return_pct": 1.0},
        "drawdown": {"B_max_mtm_pct": 12.0},
        "walk_forward": {"positive_folds": 5},
        "economic_edge": {"B_closed_pair_price_pnl_before_execution_and_funding": 1.0},
        "concentration": {"all_true_leave_one_symbol_out_replays_positive": True},
        "direction": {"high_spread_C2_net_pnl": 1.0},
        "multiple_testing": {"holm_fwer_adjusted_p": 0.04},
    }


@pytest.mark.parametrize(
    ("group", "metric"),
    [
        ("sample", "closed_pair_episodes"),
        ("H_return", "trimmed_mean_monthly_pct"),
        ("H_stability", "negative_months"),
        ("C2_return", "total_return_pct"),
        ("drawdown", "B_max_mtm_pct"),
        ("walk_forward", "positive_folds"),
        ("economic_edge", "B_closed_pair_price_pnl_before_execution_and_funding"),
        ("concentration", "all_true_leave_one_symbol_out_replays_positive"),
        ("direction", "high_spread_C2_net_pnl"),
        ("multiple_testing", "holm_fwer_adjusted_p"),
    ],
)
def test_yaml_gate_evaluator_never_passes_missing_required_metrics(group: str, metric: str) -> None:
    gates = _representative_gate_contract()
    metrics = _representative_passing_metrics()
    assert (
        evaluate_v17_hard_gates(metrics, hard_gates=gates, require_complete_contract=False)[
            "passed"
        ]
        is True
    )

    del metrics[group][metric]
    result = evaluate_v17_hard_gates(metrics, hard_gates=gates, require_complete_contract=False)

    relevant_check = next(
        check for path, check in result["checks"].items() if path.startswith(f"{group}.")
    )
    assert result["passed"] is False
    assert relevant_check["passed"] is False
    assert relevant_check["reason"] == "MISSING_METRIC"


def test_gate_evaluator_accepts_full_yaml_and_fails_all_absent_metrics_closed() -> None:
    prereg = yaml.safe_load(
        Path("configs/crypto_15m_v17_pairs_prereg.yaml").read_text(encoding="utf-8")
    )
    result = evaluate_v17_hard_gates({}, hard_gates=prereg)
    expected = sum(len(group) for group in prereg["hard_gates"].values())

    assert result["passed"] is False
    assert result["total_count"] == expected
    assert result["passed_count"] == 0
    assert len(result["missing_gates"]) == expected


def test_gate_evaluator_rejects_unavailable_loso_and_negative_drawdown() -> None:
    gates = {
        "drawdown": DEFAULT_V17_HARD_GATES["drawdown"],
        "concentration": {
            "all_true_leave_one_symbol_out_replays_positive": True,
        },
    }
    metrics = {
        "drawdown": {
            "B_max_mtm_pct": -1.0,
            "C2_H_max_mtm_pct": 10.0,
            "max_recovery_months": 2,
        },
        "concentration": {
            "all_true_leave_one_symbol_out_replays_positive": None,
        },
    }
    result = evaluate_v17_hard_gates(metrics, hard_gates=gates, require_complete_contract=False)

    assert result["checks"]["drawdown.B_max_mtm_pct"]["reason"] == "INVALID_SIGN"
    loso = result["checks"]["concentration.all_true_leave_one_symbol_out_replays_positive"]
    assert loso["passed"] is False
    assert loso["reason"] == "MISSING_METRIC"


def test_gate_evaluator_accepts_full_prereg_mapping_wrapper() -> None:
    gates = _representative_gate_contract()
    wrapped = {"schema_version": "test", "hard_gates": gates}

    result = evaluate_v17_hard_gates(
        _representative_passing_metrics(),
        hard_gates=wrapped,
        require_complete_contract=False,
    )

    assert result["passed"] is True


def test_gate_evaluator_requires_complete_frozen_contract_by_default() -> None:
    with pytest.raises(ValueError, match="complete frozen v17 contract"):
        evaluate_v17_hard_gates(
            _representative_passing_metrics(),
            hard_gates=_representative_gate_contract(),
        )

    result = evaluate_v17_hard_gates(
        {"drawdown": {"B_max_mtm_pct": np.nan}},
        hard_gates={"drawdown": {"B_max_mtm_pct": 15.0}},
        require_complete_contract=False,
    )
    check = result["checks"]["drawdown.B_max_mtm_pct"]
    assert check["reason"] == "NONFINITE_METRIC"
    assert check["value"] is None
    json.dumps(result, allow_nan=False)

    out_of_range = evaluate_v17_hard_gates(
        {"multiple_testing": {"deflated_sharpe": 99.0}},
        hard_gates={"multiple_testing": {"deflated_sharpe_min": 0.95}},
        require_complete_contract=False,
    )
    assert (
        out_of_range["checks"]["multiple_testing.deflated_sharpe_min"]["reason"] == "OUT_OF_RANGE"
    )
