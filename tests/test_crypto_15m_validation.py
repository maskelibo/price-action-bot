from copy import deepcopy

import numpy as np
import pandas as pd
import pytest

from price_action.lab.crypto_15m_validation import (
    NOT_ENOUGH_CONFIGS,
    block_bootstrap_lower_bound_pct,
    continuous_monthly_returns,
    deflated_sharpe_statistics,
    direction_pnl_statistics,
    drawdown_recovery_statistics,
    evaluate_hard_gates,
    holm_adjusted_pvalues,
    monthly_return_statistics,
    monthly_returns_from_equity,
    probability_of_backtest_overfitting,
    six_nonoverlap_fold_statistics,
    symbol_concentration_statistics,
    trade_concentration_statistics,
    trimmed_mean_pct,
)


def test_continuous_months_fill_zero_and_equity_carries_forward() -> None:
    sparse = pd.Series([10.0, 20.0], index=pd.to_datetime(["2024-01-31", "2024-03-31"]))
    completed = continuous_monthly_returns(sparse)

    assert completed.tolist() == pytest.approx([10.0, 0.0, 20.0])
    assert completed.attrs["missing_months"] == 1

    equity = pd.Series(
        [100.0, 110.0, 121.0],
        index=pd.to_datetime(["2024-01-01", "2024-01-31", "2024-03-31"]),
    )
    from_equity = monthly_returns_from_equity(equity, initial_equity=100.0)
    assert from_equity.tolist() == pytest.approx([10.0, 0.0, 10.0])

    with pytest.raises(ValueError, match="finite numeric"):
        continuous_monthly_returns(
            pd.Series([10.0, np.nan], index=pd.to_datetime(["2024-01-31", "2024-02-29"]))
        )


def test_trimmed_monthly_statistics_do_not_let_one_outlier_define_result() -> None:
    returns = np.array([-5.0] * 3 + [10.0] * 30 + [100.0] * 3)
    stats = monthly_return_statistics(returns)

    assert trimmed_mean_pct(returns) == pytest.approx(10.0)
    assert stats["median_monthly_pct"] == 10.0
    assert stats["negative_months"] == 3
    assert stats["months_below_minus_1pct"] == 3
    assert stats["worst_month_pct"] == -5.0
    assert stats["best_3_month_positive_pnl_share"] == pytest.approx(0.5)


def test_trade_symbol_and_direction_concentration_helpers() -> None:
    ledger = pd.DataFrame(
        {
            "symbol": np.repeat([f"S{i}" for i in range(10)], 40),
            "side": ["long", "short"] * 200,
            "net_pnl": np.ones(400),
        }
    )

    trades = trade_concentration_statistics(ledger)
    symbols = symbol_concentration_statistics(ledger)
    direction = direction_pnl_statistics(ledger)

    assert trades["closed_trades"] == 400
    assert trades["top_5pct_trade_count"] == 20
    assert trades["top_5pct_trades_positive_pnl_share"] == pytest.approx(0.05)
    assert trades["net_after_top_5pct_trades_removed"] == 380.0
    assert symbols["single_symbol_marginal_share"] == pytest.approx(0.1)
    assert symbols["top_3_symbol_marginal_share"] == pytest.approx(0.3)
    assert symbols["effective_symbol_count"] == pytest.approx(10.0)
    assert symbols["all_leave_one_symbol_out_positive"] is True
    assert direction["long_C2_net_pnl"] == 200.0
    assert direction["short_C2_net_pnl"] == 200.0


def test_six_folds_and_seeded_three_month_block_bootstrap() -> None:
    stable = np.array([12.0] * 33 + [-0.5] * 3)
    folds = six_nonoverlap_fold_statistics(stable)
    first = block_bootstrap_lower_bound_pct(stable, iterations=2_000, seed=123)
    second = block_bootstrap_lower_bound_pct(stable, iterations=2_000, seed=123)

    assert folds["total_folds"] == 6
    assert folds["positive_folds"] == 6
    assert folds["worst_six_month_fold_pct"] > 0.0
    assert first == second
    assert first >= 6.0
    with pytest.raises(ValueError, match="exactly 36 months"):
        six_nonoverlap_fold_statistics(stable[:-1])


def test_holm_deflated_sharpe_and_cscv_pbo() -> None:
    adjusted = holm_adjusted_pvalues({"a": 0.01, "b": 0.04, "c": 0.03})
    assert adjusted == pytest.approx({"a": 0.03, "b": 0.06, "c": 0.06})

    stable = np.array([12.0] * 33 + [-0.5] * 3)
    trial_sharpes = [float(np.mean(stable) / np.std(stable, ddof=1))] * 6
    assert (
        deflated_sharpe_statistics(stable, n_trials=6, trial_sharpes=trial_sharpes)[
            "deflated_sharpe"
        ]
        >= 0.95
    )

    unavailable = probability_of_backtest_overfitting(np.ones((36, 1)))
    assert unavailable["status"] == NOT_ENOUGH_CONFIGS
    assert unavailable["probability_backtest_overfit"] is None

    base = np.tile([-1.0, 0.0, 1.0], 12)
    matrix = np.column_stack([base + offset for offset in np.linspace(0.0, 2.5, 6)])
    pbo = probability_of_backtest_overfitting(matrix, expected_configurations=6)
    assert pbo["status"] == "OK"
    assert pbo["combinations"] == 20
    assert pbo["probability_backtest_overfit"] == 0.0


def _passing_metrics(monthly_returns: np.ndarray) -> dict[str, object]:
    returns = monthly_return_statistics(monthly_returns)
    drawdown = drawdown_recovery_statistics(monthly_returns)
    folds = six_nonoverlap_fold_statistics(monthly_returns)
    ledger = pd.DataFrame(
        {
            "symbol": np.repeat([f"S{i}" for i in range(10)], 40),
            "side": ["long", "short"] * 200,
            "net_pnl": np.ones(400),
        }
    )
    trade_concentration = trade_concentration_statistics(ledger)
    symbol_concentration = symbol_concentration_statistics(ledger)
    direction = direction_pnl_statistics(ledger)
    return {
        "sample": {
            "pseudo_oos_months": len(monthly_returns),
            "closed_trades": 400,
            "long_trades": 200,
            "short_trades": 200,
            "missing_month_return_pct": 0.0,
        },
        "H_return": {
            "trimmed_mean_monthly_pct": returns["trimmed_mean_monthly_pct"],
            "median_monthly_pct": returns["median_monthly_pct"],
            "block_bootstrap_90pct_lower_bound_pct": block_bootstrap_lower_bound_pct(
                monthly_returns, iterations=20_000, seed=7
            ),
        },
        "H_stability": {
            key: returns[key]
            for key in ("negative_months", "months_below_minus_1pct", "worst_month_pct")
        },
        "C2_return": {
            key: returns[key]
            for key in ("trimmed_mean_monthly_pct", "median_monthly_pct", "total_return_pct")
        },
        "drawdown": {
            "B_max_mtm_pct": drawdown["max_mtm_drawdown_pct"],
            "C2_H_max_mtm_pct": drawdown["max_mtm_drawdown_pct"],
            "max_recovery_months": drawdown["max_recovery_months"],
        },
        "walk_forward": {
            **folds,
            "oos_to_is_trimmed_return_ratio": 0.8,
            "oos_to_is_drawdown_ratio": 1.1,
        },
        "concentration": {
            **{
                key: returns[key]
                for key in (
                    "best_month_positive_pnl_share",
                    "best_3_month_positive_pnl_share",
                    "mean_after_best_3_months_removed_pct",
                )
            },
            **trade_concentration,
            **symbol_concentration,
        },
        "holdout": {
            "C2_total_return_pct": 50.0,
            "development_return_retention": 0.7,
            "positive_holdout_symbols": 4,
            "holdout_symbols_total": 4,
            "max_drawdown_pct": 10.0,
        },
        "direction": direction,
        "multiple_testing": {
            "paired_block_months": 3,
            "bootstrap_iterations": 20_000,
            "holm_fwer_adjusted_p": 0.03,
            "deflated_sharpe": 0.99,
            "probability_backtest_overfit": 0.1,
        },
    }


def test_gate_evaluator_accepts_stable_series_and_rejects_plus_100_minus_20_pattern() -> None:
    stable = np.array([12.0] * 33 + [-0.5] * 3)
    accepted = evaluate_hard_gates(_passing_metrics(stable))
    assert accepted["passed"] is True
    assert accepted["passed_count"] == accepted["total_count"]

    pathological = np.tile([100.0, -20.0], 18)
    bad_metrics = deepcopy(_passing_metrics(stable))
    bad_stats = monthly_return_statistics(pathological)
    bad_metrics["H_return"].update(
        {
            "trimmed_mean_monthly_pct": bad_stats["trimmed_mean_monthly_pct"],
            "median_monthly_pct": bad_stats["median_monthly_pct"],
            "block_bootstrap_90pct_lower_bound_pct": block_bootstrap_lower_bound_pct(
                pathological, iterations=2_000, seed=7
            ),
        }
    )
    bad_metrics["H_stability"].update(
        {
            key: bad_stats[key]
            for key in ("negative_months", "months_below_minus_1pct", "worst_month_pct")
        }
    )
    bad_metrics["concentration"].update(
        {
            key: bad_stats[key]
            for key in (
                "best_month_positive_pnl_share",
                "best_3_month_positive_pnl_share",
                "mean_after_best_3_months_removed_pct",
            )
        }
    )
    rejected = evaluate_hard_gates(bad_metrics)

    assert rejected["passed"] is False
    assert "H_stability.negative_months_max" in rejected["failed_gates"]
    assert "H_stability.worst_month_pct_min" in rejected["failed_gates"]


def test_gate_evaluator_fails_closed_when_pbo_matrix_is_unavailable() -> None:
    stable = np.array([12.0] * 33 + [-0.5] * 3)
    metrics = _passing_metrics(stable)
    metrics["multiple_testing"]["probability_backtest_overfit"] = None
    metrics["multiple_testing"]["probability_backtest_overfit_status"] = NOT_ENOUGH_CONFIGS

    result = evaluate_hard_gates(metrics)
    check = result["checks"]["multiple_testing.probability_backtest_overfit_max"]
    assert result["passed"] is False
    assert check["reason"] == NOT_ENOUGH_CONFIGS


def test_gate_evaluator_rejects_negative_drawdown_sign_instead_of_passing_it() -> None:
    stable = np.array([12.0] * 33 + [-0.5] * 3)
    metrics = _passing_metrics(stable)
    metrics["drawdown"]["B_max_mtm_pct"] = -50.0

    result = evaluate_hard_gates(metrics)
    check = result["checks"]["drawdown.B_max_mtm_pct"]

    assert result["passed"] is False
    assert check["reason"] == "INVALID_SIGN"
