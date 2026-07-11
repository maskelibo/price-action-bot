"""Fail-closed validation primitives for the preregistered v17 pairs study.

The module is deliberately independent of the pairs engine and report payloads.
Functions accept plain arrays, pandas objects, mappings, or record-like episode
objects and return ordinary dictionaries/data frames.  Percentage values are in
percentage points (``10.0`` means ten percent).

The v17 statistical contract is intentionally repeated as constants here.  A
caller cannot accidentally shorten the H window, drop a non-finite month, treat
two pair legs as two samples, or substitute descriptive symbol attribution for a
true leave-one-symbol-out replay.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict, is_dataclass
from math import ceil, inf, isclose
from typing import Any

import numpy as np
import pandas as pd

from price_action.lab.crypto_15m_validation import (
    block_bootstrap_lower_bound_pct,
    deflated_sharpe_statistics,
    holm_adjusted_pvalues,
    monthly_return_statistics,
    probability_of_backtest_overfitting,
    trimmed_mean_pct,
)

EXPECTED_H_MONTHS = 36
EXPECTED_V17_CANDIDATES = 3
EXPECTED_PROGRAM_CANDIDATES = 9
BLOCK_MONTHS = 3
SIGN_FLIP_BLOCKS = 12
VALIDATION_ITERATIONS = 20_000
VALIDATION_SEED = 17
TRIM_FRACTION = 0.10
BOOTSTRAP_LOWER_QUANTILE = 0.10
PBO_SLICES = 6

TRUE_LOSO_UNAVAILABLE = "TRUE_LOSO_UNAVAILABLE"
TRUE_LOSO_OK = "OK"
DESCRIPTIVE_ATTRIBUTION_ONLY = "DESCRIPTIVE_ATTRIBUTION_ONLY"
DEGENERATE_TRIAL_SHARPE = "DEGENERATE_TRIAL_SHARPE"

FROZEN_V16_CANDIDATE_IDS = (
    "T1_RESIDUAL_TREND_1W",
    "T2_RESIDUAL_TREND_2W",
    "T4_RESIDUAL_TREND_4W",
    "M1_FUNDING_RESIDUAL_REVERSION_4H_Z2",
    "M2_FUNDING_RESIDUAL_REVERSION_8H_Z2",
    "M3_FUNDING_RESIDUAL_REVERSION_4H_Z2P5",
)
FROZEN_V17_CANDIDATE_IDS = (
    "DP1_EG_90D_Z2P5",
    "DP2_EG_180D_Z2P5",
    "DP3_EG_180D_Z3_STRICT",
)
FROZEN_PROGRAM_CANDIDATE_IDS = (*FROZEN_V16_CANDIDATE_IDS, *FROZEN_V17_CANDIDATE_IDS)
FROZEN_H_MONTHS = pd.period_range("2023-06", "2026-05", freq="M")
FROZEN_PRIMARY_SYMBOLS = frozenset(
    {
        "ETH/USDT",
        "SOL/USDT",
        "BNB/USDT",
        "ADA/USDT",
        "AVAX/USDT",
        "LINK/USDT",
        "DOT/USDT",
        "DOGE/USDT",
        "ZEC/USDT",
        "NEAR/USDT",
        "FIL/USDT",
        "ATOM/USDT",
        "ALGO/USDT",
    }
)


DEFAULT_V17_HARD_GATES: dict[str, dict[str, Any]] = {
    "sample": {
        "pseudo_oos_months": 36,
        "minimum_closed_pair_episodes": 120,
        "minimum_high_spread_entries": 40,
        "minimum_low_spread_entries": 40,
        "minimum_active_months": 30,
        "pair_legs_may_not_count_as_separate_trades": True,
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
        "total_return_must_be_positive": True,
    },
    "drawdown": {
        "B_max_mtm_pct": 15.0,
        "C2_H_max_mtm_pct": 20.0,
        "max_recovery_months": 6,
    },
    "walk_forward": {
        "positive_folds_min": 5,
        "total_folds": 6,
        "worst_six_month_fold_pct_min": -5.0,
        "oos_to_is_trimmed_return_ratio_min": 0.50,
        "oos_to_is_drawdown_ratio_max": 1.50,
    },
    "economic_edge": {
        "B_closed_pair_price_pnl_before_execution_and_funding_must_be_positive": True,
        "B_pre_cost_price_pnl_over_execution_cost_min": 1.25,
        "median_entry_expected_edge_over_stressed_cost_min": 1.50,
    },
    "concentration": {
        "best_month_positive_pnl_share_max": 0.15,
        "best_3_month_positive_pnl_share_max": 0.35,
        "top_5pct_pair_episodes_positive_pnl_share_max": 0.65,
        "net_after_top_5pct_pair_episodes_removed_must_be_positive": True,
        "effective_symbol_count_min": 6,
        "all_true_leave_one_symbol_out_replays_positive": True,
    },
    "holdout": {
        "C2_total_return_must_be_positive": True,
        "primary_return_retention_min": 0.40,
        "retention_formula": (
            "holdout C2 trimmed monthly mean divided by primary C2 trimmed monthly mean "
            "over the same 36 pseudo-OOS months; nonpositive primary denominator fails"
        ),
        "distinct_holdout_symbols_traded_min": 4,
        "distinct_closed_holdout_pairs_min": 2,
        "minimum_closed_pair_episodes": 30,
        "minimum_active_months": 18,
        "max_drawdown_pct": 25.0,
        "evaluation_order": "single_locked_primary_winner_then_LOSO_then_one_holdout_run",
        "runner_up_after_holdout_failure_forbidden": True,
    },
    "direction": {
        "high_spread_C2_net_must_be_positive": True,
        "low_spread_C2_net_must_be_positive": True,
    },
    "multiple_testing": {
        "paired_block_months": 3,
        "bootstrap_iterations": 20_000,
        "holm_fwer_adjusted_p_max": 0.05,
        "deflated_sharpe_min": 0.95,
        "probability_backtest_overfit_max": 0.20,
        "local_v17_trial_count": 3,
        "cumulative_program_trial_count_including_v16": 9,
        "cumulative_program_holm_adjusted_p_max": 0.05,
        "cumulative_program_deflated_sharpe_min": 0.95,
        "cumulative_program_probability_backtest_overfit_max": 0.20,
    },
}


def _validate_month_index(index: pd.Index, *, name: str) -> None:
    """Reject dated monthly inputs with duplicates or calendar gaps."""

    if isinstance(index, pd.RangeIndex):
        return
    try:
        if isinstance(index, pd.PeriodIndex):
            periods = index.asfreq("M")
        else:
            timestamps = pd.DatetimeIndex(pd.to_datetime(index, utc=True)).tz_convert(None)
            periods = timestamps.to_period("M")
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} index must be monthly timestamps") from exc
    if not periods.is_unique:
        raise ValueError(f"{name} must contain one observation per calendar month")
    expected = pd.period_range(periods.min(), periods=periods.size, freq="M")
    if not periods.equals(expected):
        raise ValueError(f"{name} must contain consecutive calendar months")


def _one_dimensional_values(values: Any, *, name: str) -> np.ndarray:
    """Coerce one chronological numeric vector without dropping observations."""

    source = values
    if isinstance(values, pd.DataFrame):
        if values.shape[1] != 1:
            raise ValueError(f"{name} DataFrame must contain exactly one value column")
        source = values.iloc[:, 0]
    if isinstance(source, pd.Series):
        if not source.index.is_unique:
            raise ValueError(f"{name} index must be unique")
        if not source.index.is_monotonic_increasing:
            raise ValueError(f"{name} must be chronological")
        _validate_month_index(source.index, name=name)
        source = source.to_numpy()
    elif isinstance(source, Mapping):
        if not source:
            source = []
        else:
            try:
                ordered = sorted(source.items(), key=lambda item: pd.Timestamp(item[0]))
            except (TypeError, ValueError) as exc:
                raise ValueError(f"{name} mapping keys must be chronological timestamps") from exc
            mapping_index = pd.DatetimeIndex(
                pd.to_datetime([key for key, _value in ordered], utc=True)
            )
            _validate_month_index(mapping_index, name=name)
            source = [value for _, value in ordered]

    try:
        array = np.asarray(source, dtype=float)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must contain numeric observations") from exc
    if array.ndim != 1:
        raise ValueError(f"{name} must be one-dimensional")
    if not np.isfinite(array).all():
        raise ValueError(f"{name} must contain only finite observations")
    return array


def _dated_month_index(values: Any, *, name: str) -> pd.PeriodIndex | None:
    source = values
    if isinstance(source, pd.DataFrame):
        if source.shape[1] != 1:
            raise ValueError(f"{name} DataFrame must contain exactly one value column")
        source = source.iloc[:, 0]
    if isinstance(source, pd.Series):
        _validate_month_index(source.index, name=name)
        if isinstance(source.index, pd.PeriodIndex):
            return source.index.asfreq("M")
        return (
            pd.DatetimeIndex(pd.to_datetime(source.index, utc=True)).tz_convert(None).to_period("M")
        )
    if isinstance(source, Mapping) and source:
        try:
            ordered_keys = sorted(source, key=pd.Timestamp)
            index = pd.DatetimeIndex(pd.to_datetime(ordered_keys, utc=True))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{name} mapping keys must be monthly timestamps") from exc
        _validate_month_index(index, name=name)
        return index.tz_convert(None).to_period("M")
    return None


def _require_aligned_candidate_months(
    candidates: Mapping[str, Any], names: Sequence[str], *, name: str
) -> None:
    indices = {
        candidate: _dated_month_index(candidates[candidate], name=f"{name}[{candidate}]")
        for candidate in names
    }
    dated = {candidate: index for candidate, index in indices.items() if index is not None}
    if dated and len(dated) != len(names):
        raise ValueError(f"{name} candidates must either all be dated or all be undated")
    if dated:
        reference = next(iter(dated.values()))
        if any(not index.equals(reference) for index in dated.values()):
            raise ValueError(f"{name} candidates must use the identical calendar months")


def _enforce_frozen_matrix_contract(
    frame: pd.DataFrame,
    *,
    candidate_ids: Sequence[str],
    name: str,
) -> None:
    if tuple(map(str, frame.columns)) != tuple(candidate_ids):
        raise ValueError(f"{name} candidate IDs/order differ from the frozen contract")
    if isinstance(frame.index, pd.RangeIndex):
        raise ValueError(f"{name} must carry the frozen dated pseudo-OOS month index")
    if isinstance(frame.index, pd.PeriodIndex):
        periods = frame.index.asfreq("M")
    else:
        periods = (
            pd.DatetimeIndex(pd.to_datetime(frame.index, utc=True)).tz_convert(None).to_period("M")
        )
    if not periods.equals(FROZEN_H_MONTHS):
        raise ValueError(f"{name} must cover exactly 2023-06 through 2026-05")


def exact_h_monthly_returns(values: Any, *, name: str = "H_monthly_returns") -> np.ndarray:
    """Return exactly 36 finite chronological H monthly returns.

    A dated pandas object must already be sorted and unique.  A timestamp-keyed
    mapping is sorted by its keys.  Undated arrays are interpreted in the order
    supplied by the caller.
    """

    array = _one_dimensional_values(values, name=name)
    if array.size != EXPECTED_H_MONTHS:
        raise ValueError(
            f"{name} must contain exactly {EXPECTED_H_MONTHS} months, got {array.size}"
        )
    return array


def exact_h_candidate_matrix(
    candidates: pd.DataFrame | Mapping[str, Any] | np.ndarray,
    *,
    candidate_names: Sequence[str] | None = None,
    enforce_frozen_contract: bool = True,
) -> pd.DataFrame:
    """Return the exact finite ``36 x 3`` H matrix used by Holm/DSR/PBO."""

    if isinstance(candidates, pd.DataFrame):
        frame = candidates.copy()
        if not frame.index.is_unique or not frame.index.is_monotonic_increasing:
            raise ValueError("candidate H matrix index must be unique and chronological")
        _validate_month_index(frame.index, name="candidate H matrix")
        if candidate_names is not None:
            if len(candidate_names) != len(frame.columns):
                raise ValueError("candidate_names length does not match matrix columns")
            frame.columns = [str(name) for name in candidate_names]
    elif isinstance(candidates, Mapping):
        if candidate_names is None:
            names = [str(name) for name in candidates]
        else:
            names = [str(name) for name in candidate_names]
            if set(names) != {str(name) for name in candidates}:
                raise ValueError("candidate_names do not match candidate mapping keys")
        normalized = {str(key): value for key, value in candidates.items()}
        _require_aligned_candidate_months(normalized, names, name="candidate H matrix")
        aligned_index = _dated_month_index(
            normalized[names[0]], name=f"candidate H matrix[{names[0]}]"
        )
        frame = pd.DataFrame(
            {name: exact_h_monthly_returns(normalized[name], name=f"H[{name}]") for name in names}
        )
        if aligned_index is not None:
            frame.index = aligned_index
    else:
        try:
            matrix = np.asarray(candidates, dtype=float)
        except (TypeError, ValueError) as exc:
            raise ValueError("candidate H matrix must be numeric") from exc
        if matrix.ndim != 2:
            raise ValueError("candidate H matrix must be two-dimensional")
        names = (
            [str(name) for name in candidate_names]
            if candidate_names is not None
            else [f"candidate_{index + 1}" for index in range(matrix.shape[1])]
        )
        if len(names) != matrix.shape[1]:
            raise ValueError("candidate_names length does not match matrix columns")
        frame = pd.DataFrame(matrix, columns=names)

    if frame.shape != (EXPECTED_H_MONTHS, EXPECTED_V17_CANDIDATES):
        raise ValueError(
            "candidate H matrix must have exact shape "
            f"({EXPECTED_H_MONTHS}, {EXPECTED_V17_CANDIDATES}), got {frame.shape}"
        )
    if len(set(map(str, frame.columns))) != EXPECTED_V17_CANDIDATES:
        raise ValueError("candidate names must be unique")
    numeric = frame.apply(pd.to_numeric, errors="coerce")
    if numeric.isna().any().any() or not np.isfinite(numeric.to_numpy(dtype=float)).all():
        raise ValueError("candidate H matrix must contain only finite numeric observations")
    numeric.columns = [str(column) for column in frame.columns]
    if enforce_frozen_contract:
        _enforce_frozen_matrix_contract(
            numeric,
            candidate_ids=FROZEN_V17_CANDIDATE_IDS,
            name="candidate H matrix",
        )
    return numeric.astype(float)


def exact_program_candidate_matrix(
    candidates: pd.DataFrame | Mapping[str, Any] | np.ndarray,
    *,
    candidate_names: Sequence[str] | None = None,
    enforce_frozen_contract: bool = True,
) -> pd.DataFrame:
    """Return the exact finite ``36 x 9`` cumulative v16+v17 H matrix."""

    if isinstance(candidates, pd.DataFrame):
        frame = candidates.copy()
        if not frame.index.is_unique or not frame.index.is_monotonic_increasing:
            raise ValueError("program H matrix index must be unique and chronological")
        _validate_month_index(frame.index, name="program H matrix")
        if candidate_names is not None:
            if len(candidate_names) != len(frame.columns):
                raise ValueError("candidate_names length does not match matrix columns")
            frame.columns = [str(name) for name in candidate_names]
    elif isinstance(candidates, Mapping):
        normalized = {str(key): value for key, value in candidates.items()}
        names = (
            [str(name) for name in candidate_names]
            if candidate_names is not None
            else list(normalized)
        )
        if set(names) != set(normalized):
            raise ValueError("candidate_names do not match program candidate mapping keys")
        _require_aligned_candidate_months(normalized, names, name="program H matrix")
        aligned_index = _dated_month_index(
            normalized[names[0]], name=f"program H matrix[{names[0]}]"
        )
        frame = pd.DataFrame(
            {name: exact_h_monthly_returns(normalized[name], name=f"H[{name}]") for name in names}
        )
        if aligned_index is not None:
            frame.index = aligned_index
    else:
        try:
            matrix = np.asarray(candidates, dtype=float)
        except (TypeError, ValueError) as exc:
            raise ValueError("program H matrix must be numeric") from exc
        if matrix.ndim != 2:
            raise ValueError("program H matrix must be two-dimensional")
        names = (
            [str(name) for name in candidate_names]
            if candidate_names is not None
            else [f"candidate_{index + 1}" for index in range(matrix.shape[1])]
        )
        if len(names) != matrix.shape[1]:
            raise ValueError("candidate_names length does not match matrix columns")
        frame = pd.DataFrame(matrix, columns=names)

    expected_shape = (EXPECTED_H_MONTHS, EXPECTED_PROGRAM_CANDIDATES)
    if frame.shape != expected_shape:
        raise ValueError(
            f"program H matrix must have exact shape {expected_shape}, got {frame.shape}"
        )
    if len(set(map(str, frame.columns))) != EXPECTED_PROGRAM_CANDIDATES:
        raise ValueError("program candidate names must be unique")
    numeric = frame.apply(pd.to_numeric, errors="coerce")
    if numeric.isna().any().any() or not np.isfinite(numeric.to_numpy(dtype=float)).all():
        raise ValueError("program H matrix must contain only finite numeric observations")
    numeric.columns = [str(column) for column in frame.columns]
    if enforce_frozen_contract:
        _enforce_frozen_matrix_contract(
            numeric,
            candidate_ids=FROZEN_PROGRAM_CANDIDATE_IDS,
            name="program H matrix",
        )
    return numeric.astype(float)


def h_monthly_statistics(
    monthly_returns: Any,
    *,
    monthly_pnl: Any,
    enforce_frozen_period: bool = True,
) -> dict[str, float | int | None]:
    """Compute the fixed v17 H return/stability/bootstrap statistics."""

    _require_aligned_candidate_months(
        {"returns": monthly_returns, "pnl": monthly_pnl},
        ("returns", "pnl"),
        name="H monthly return/PnL",
    )
    if enforce_frozen_period:
        returns_index = _dated_month_index(monthly_returns, name="H monthly returns")
        pnl_index = _dated_month_index(monthly_pnl, name="H monthly PnL")
        if returns_index is None or pnl_index is None:
            raise ValueError("H monthly returns and PnL must carry the frozen dated index")
        if not returns_index.equals(FROZEN_H_MONTHS) or not pnl_index.equals(FROZEN_H_MONTHS):
            raise ValueError("H monthly returns and PnL must cover 2023-06 through 2026-05")
    returns = exact_h_monthly_returns(monthly_returns)
    pnl = exact_h_monthly_returns(monthly_pnl, name="H_monthly_pnl")
    raw_statistics = monthly_return_statistics(returns, monthly_pnl=pnl)
    statistics = {
        key: (None if isinstance(value, float | np.floating) and not np.isfinite(value) else value)
        for key, value in raw_statistics.items()
    }
    return {
        **statistics,
        "pseudo_oos_months": EXPECTED_H_MONTHS,
        "block_bootstrap_90pct_lower_bound_pct": block_bootstrap_lower_bound_pct(
            returns,
            block_months=BLOCK_MONTHS,
            iterations=VALIDATION_ITERATIONS,
            confidence=1.0 - BOOTSTRAP_LOWER_QUANTILE,
            seed=VALIDATION_SEED,
            trim_fraction=TRIM_FRACTION,
        ),
        "bootstrap_block_months": BLOCK_MONTHS,
        "bootstrap_iterations": VALIDATION_ITERATIONS,
        "bootstrap_seed": VALIDATION_SEED,
        "bootstrap_lower_quantile": BOOTSTRAP_LOWER_QUANTILE,
    }


def candidate_block_sign_flip_test(
    monthly_returns: Any,
    *,
    iterations: int = VALIDATION_ITERATIONS,
    seed: int = VALIDATION_SEED,
) -> dict[str, float | int | str]:
    """One-sided zero-alpha sign-flip test on 12 chronological 3-month blocks."""

    returns = exact_h_monthly_returns(monthly_returns)
    if iterations != VALIDATION_ITERATIONS or seed != VALIDATION_SEED:
        raise ValueError("v17 sign-flip is locked to 20,000 iterations and seed 17")
    blocks = returns.reshape(SIGN_FLIP_BLOCKS, BLOCK_MONTHS)
    observed = trimmed_mean_pct(returns, proportion_to_cut=TRIM_FRACTION)
    rng = np.random.default_rng(seed)
    signs = rng.integers(0, 2, size=(iterations, SIGN_FLIP_BLOCKS), dtype=np.int8)
    signs = signs * 2 - 1
    null_samples = (blocks[np.newaxis, :, :] * signs[:, :, np.newaxis]).reshape(
        iterations, EXPECTED_H_MONTHS
    )
    null_samples.sort(axis=1)
    cut = int(np.floor(EXPECTED_H_MONTHS * TRIM_FRACTION))
    kept = null_samples[:, cut : EXPECTED_H_MONTHS - cut]
    null_statistics = kept.mean(axis=1)
    exceedances = int(np.count_nonzero(null_statistics >= observed))
    return {
        "status": "OK",
        "observed_trimmed_mean_monthly_pct": float(observed),
        "candidate_sign_flip_pvalue": float((1 + exceedances) / (iterations + 1)),
        "null_exceedances_gte_observed": exceedances,
        "iterations": int(iterations),
        "seed": int(seed),
        "blocks": SIGN_FLIP_BLOCKS,
        "block_months": BLOCK_MONTHS,
    }


def _periodic_sharpe(values: np.ndarray) -> float:
    standard_deviation = float(np.std(values, ddof=1))
    mean = float(np.mean(values))
    if standard_deviation == 0.0:
        if mean > 0.0:
            return inf
        if mean < 0.0:
            return -inf
        return 0.0
    return mean / standard_deviation


def three_candidate_multiple_testing(
    candidates: pd.DataFrame | Mapping[str, Any] | np.ndarray,
    *,
    candidate_names: Sequence[str] | None = None,
    iterations: int = VALIDATION_ITERATIONS,
    seed: int = VALIDATION_SEED,
    enforce_frozen_contract: bool = True,
) -> dict[str, Any]:
    """Run the locked three-cell v17 sign-flip, Holm, DSR, and CSCV tests."""

    if iterations != VALIDATION_ITERATIONS or seed != VALIDATION_SEED:
        raise ValueError("v17 multiple testing is locked to 20,000 iterations and seed 17")
    frame = exact_h_candidate_matrix(
        candidates,
        candidate_names=candidate_names,
        enforce_frozen_contract=enforce_frozen_contract,
    )
    raw_tests = {
        candidate: candidate_block_sign_flip_test(
            frame[candidate], iterations=iterations, seed=seed
        )
        for candidate in frame.columns
    }
    raw_pvalues = {
        candidate: float(test["candidate_sign_flip_pvalue"])
        for candidate, test in raw_tests.items()
    }
    adjusted = holm_adjusted_pvalues(raw_pvalues)
    assert isinstance(adjusted, dict)

    periodic_sharpes = {
        candidate: _periodic_sharpe(frame[candidate].to_numpy(dtype=float))
        for candidate in frame.columns
    }
    finite_trial_sharpes = np.isfinite(list(periodic_sharpes.values())).all()
    reported_sharpes = {
        candidate: (float(value) if np.isfinite(value) else None)
        for candidate, value in periodic_sharpes.items()
    }
    candidate_results: dict[str, dict[str, Any]] = {}
    for candidate in frame.columns:
        if finite_trial_sharpes:
            dsr = deflated_sharpe_statistics(
                frame[candidate].to_numpy(dtype=float),
                n_trials=EXPECTED_V17_CANDIDATES,
                trial_sharpes=list(periodic_sharpes.values()),
                periods_per_year=12,
            )
            dsr_status = "OK"
        else:
            dsr = {
                "deflated_sharpe": None,
                "observed_sharpe": None,
                "annualized_sharpe": None,
                "expected_max_sharpe": None,
                "n_trials": EXPECTED_V17_CANDIDATES,
                "observations": EXPECTED_H_MONTHS,
            }
            dsr_status = DEGENERATE_TRIAL_SHARPE
        candidate_results[candidate] = {
            **raw_tests[candidate],
            "holm_fwer_adjusted_p": float(adjusted[candidate]),
            "periodic_monthly_sharpe": reported_sharpes[candidate],
            "deflated_sharpe_status": dsr_status,
            **dsr,
        }

    pbo = probability_of_backtest_overfitting(
        frame,
        n_slices=PBO_SLICES,
        expected_configurations=EXPECTED_V17_CANDIDATES,
    )
    return {
        "candidate_results": candidate_results,
        "trial_periodic_monthly_sharpes": reported_sharpes,
        "pbo": pbo,
        "candidate_count": EXPECTED_V17_CANDIDATES,
        "months": EXPECTED_H_MONTHS,
        "pbo_slices": PBO_SLICES,
        "paired_block_months": BLOCK_MONTHS,
        "bootstrap_iterations": int(iterations),
        "seed": int(seed),
    }


def program_wide_multiple_testing(
    candidates: pd.DataFrame | Mapping[str, Any] | np.ndarray,
    *,
    candidate_names: Sequence[str] | None = None,
    iterations: int = VALIDATION_ITERATIONS,
    seed: int = VALIDATION_SEED,
    enforce_frozen_contract: bool = True,
) -> dict[str, Any]:
    """Run cumulative Holm/DSR/PBO over the frozen six v16 plus three v17 trials."""

    if iterations != VALIDATION_ITERATIONS or seed != VALIDATION_SEED:
        raise ValueError("program-wide testing is locked to 20,000 iterations and seed 17")
    frame = exact_program_candidate_matrix(
        candidates,
        candidate_names=candidate_names,
        enforce_frozen_contract=enforce_frozen_contract,
    )
    raw_tests = {
        candidate: candidate_block_sign_flip_test(
            frame[candidate], iterations=iterations, seed=seed
        )
        for candidate in frame.columns
    }
    raw_pvalues = {
        candidate: float(test["candidate_sign_flip_pvalue"])
        for candidate, test in raw_tests.items()
    }
    adjusted = holm_adjusted_pvalues(raw_pvalues)
    assert isinstance(adjusted, dict)

    periodic_sharpes = {
        candidate: _periodic_sharpe(frame[candidate].to_numpy(dtype=float))
        for candidate in frame.columns
    }
    finite_trial_sharpes = np.isfinite(list(periodic_sharpes.values())).all()
    reported_sharpes = {
        candidate: (float(value) if np.isfinite(value) else None)
        for candidate, value in periodic_sharpes.items()
    }
    candidate_results: dict[str, dict[str, Any]] = {}
    for candidate in frame.columns:
        if finite_trial_sharpes:
            dsr = deflated_sharpe_statistics(
                frame[candidate].to_numpy(dtype=float),
                n_trials=EXPECTED_PROGRAM_CANDIDATES,
                trial_sharpes=list(periodic_sharpes.values()),
                periods_per_year=12,
            )
            dsr_status = "OK"
        else:
            dsr = {
                "deflated_sharpe": None,
                "observed_sharpe": None,
                "annualized_sharpe": None,
                "expected_max_sharpe": None,
                "n_trials": EXPECTED_PROGRAM_CANDIDATES,
                "observations": EXPECTED_H_MONTHS,
            }
            dsr_status = DEGENERATE_TRIAL_SHARPE
        candidate_results[candidate] = {
            **raw_tests[candidate],
            "holm_fwer_adjusted_p": float(adjusted[candidate]),
            "periodic_monthly_sharpe": reported_sharpes[candidate],
            "deflated_sharpe_status": dsr_status,
            **dsr,
        }

    pbo = probability_of_backtest_overfitting(
        frame,
        n_slices=PBO_SLICES,
        expected_configurations=EXPECTED_PROGRAM_CANDIDATES,
    )
    return {
        "candidate_results": candidate_results,
        "trial_periodic_monthly_sharpes": reported_sharpes,
        "pbo": pbo,
        "candidate_count": EXPECTED_PROGRAM_CANDIDATES,
        "months": EXPECTED_H_MONTHS,
        "pbo_slices": PBO_SLICES,
        "paired_block_months": BLOCK_MONTHS,
        "bootstrap_iterations": int(iterations),
        "seed": int(seed),
        "scope": "CUMULATIVE_V16_PLUS_V17",
    }


def _aligned_metric(
    values: Mapping[str, Any] | Sequence[float] | pd.Series,
    names: Sequence[str],
    *,
    metric_name: str,
) -> dict[str, float]:
    if isinstance(values, Mapping):
        normalized = {str(key): value for key, value in values.items()}
        if set(normalized) != set(names):
            raise ValueError(f"{metric_name} keys must match candidate names")
        raw = [normalized[name] for name in names]
    elif isinstance(values, pd.Series) and set(map(str, values.index)) == set(names):
        normalized = {str(key): value for key, value in values.items()}
        raw = [normalized[name] for name in names]
    else:
        raw = list(values)
        if len(raw) != len(names):
            raise ValueError(f"{metric_name} length must match candidate count")
    array = _one_dimensional_values(raw, name=metric_name)
    if (array < 0.0).any():
        raise ValueError(f"{metric_name} cannot be negative")
    return {name: float(array[index]) for index, name in enumerate(names)}


def rank_h_candidates(
    candidates: pd.DataFrame | Mapping[str, Any] | np.ndarray,
    *,
    h_max_drawdowns: Mapping[str, Any] | Sequence[float] | pd.Series,
    turnovers: Mapping[str, Any] | Sequence[float] | pd.Series,
    candidate_names: Sequence[str] | None = None,
    enforce_frozen_contract: bool = True,
) -> pd.DataFrame:
    """Rank the three cells by capped H mean and preregistered tie-breakers."""

    frame = exact_h_candidate_matrix(
        candidates,
        candidate_names=candidate_names,
        enforce_frozen_contract=enforce_frozen_contract,
    )
    names = list(frame.columns)
    drawdowns = _aligned_metric(h_max_drawdowns, names, metric_name="h_max_drawdowns")
    turnover_values = _aligned_metric(turnovers, names, metric_name="turnovers")
    rows = []
    for candidate in names:
        returns = frame[candidate].to_numpy(dtype=float)
        trimmed = trimmed_mean_pct(returns, proportion_to_cut=TRIM_FRACTION)
        rows.append(
            {
                "candidate_id": candidate,
                "H_trimmed_mean_monthly_pct": trimmed,
                "H_rank_value_pct": min(trimmed, 15.0),
                "H_max_drawdown_pct": drawdowns[candidate],
                "H_negative_months": int(np.count_nonzero(returns < 0.0)),
                "turnover": turnover_values[candidate],
            }
        )
    ranked = pd.DataFrame(rows).sort_values(
        by=[
            "H_rank_value_pct",
            "H_max_drawdown_pct",
            "H_negative_months",
            "turnover",
            "candidate_id",
        ],
        ascending=[False, True, True, True, True],
        kind="stable",
        ignore_index=True,
    )
    ranked["resolved_by_lexicographic_candidate_id"] = ranked.duplicated(
        subset=[
            "H_rank_value_pct",
            "H_max_drawdown_pct",
            "H_negative_months",
            "turnover",
        ],
        keep=False,
    )
    ranked["preregistered_rank_tie"] = ranked.duplicated(
        subset=[
            "H_rank_value_pct",
            "H_max_drawdown_pct",
            "H_negative_months",
            "turnover",
            "candidate_id",
        ],
        keep=False,
    )
    ranked.insert(0, "rank", np.arange(1, len(ranked) + 1, dtype=int))
    return ranked


def _record_mapping(record: Any) -> dict[str, Any]:
    if isinstance(record, Mapping):
        return dict(record)
    if is_dataclass(record) and not isinstance(record, type):
        return asdict(record)
    fields = getattr(record, "__slots__", ())
    if fields:
        return {str(field): getattr(record, field) for field in fields if hasattr(record, field)}
    if hasattr(record, "__dict__"):
        return dict(vars(record))
    raise TypeError("episode records must be mappings or record-like objects")


def _episode_frame(episodes: Any) -> pd.DataFrame:
    if episodes is None:
        return pd.DataFrame()
    if isinstance(episodes, pd.DataFrame):
        return episodes.copy()
    if isinstance(episodes, pd.Series):
        if pd.api.types.is_numeric_dtype(episodes):
            return pd.DataFrame({"net_pnl": episodes.to_numpy()})
        return pd.DataFrame([episodes.to_dict()])
    if isinstance(episodes, Mapping):
        if not episodes:
            return pd.DataFrame()
        if all(np.isscalar(value) or value is None for value in episodes.values()):
            return pd.DataFrame([dict(episodes)])
        try:
            return pd.DataFrame(episodes)
        except ValueError as exc:
            raise ValueError("episode column mapping has inconsistent lengths") from exc

    if (
        isinstance(episodes, np.ndarray)
        and episodes.ndim == 1
        and np.issubdtype(episodes.dtype, np.number)
    ):
        return pd.DataFrame({"net_pnl": episodes})
    records = list(episodes)
    if not records:
        return pd.DataFrame()
    if all(isinstance(value, int | float | np.number) for value in records):
        return pd.DataFrame({"net_pnl": records})
    return pd.DataFrame([_record_mapping(record) for record in records])


def _column_name(frame: pd.DataFrame, requested: str | None, aliases: Sequence[str]) -> str:
    if requested is not None:
        if requested not in frame.columns:
            raise ValueError(f"episode data is missing {requested!r}")
        return requested
    found = next((name for name in aliases if name in frame.columns), None)
    if found is None:
        raise ValueError(f"episode data is missing one of {list(aliases)}")
    return found


def _finite_column(frame: pd.DataFrame, column: str) -> np.ndarray:
    values = pd.to_numeric(frame[column], errors="coerce").to_numpy(dtype=float)
    if not np.isfinite(values).all():
        raise ValueError(f"episode column {column!r} must contain only finite values")
    return values


def episode_concentration_statistics(
    closed_episodes: Any,
    terminal_episodes: Any = None,
    *,
    pnl_col: str | None = None,
    top_fraction: float = 0.05,
) -> dict[str, float | int | None]:
    """Measure pair-episode concentration with terminal episodes included.

    ``closed_pair_episodes`` remains the number of closed rows only.  The top
    removal and all PnL statistics combine closed and terminal pseudo-episodes.
    """

    if not 0.0 < top_fraction <= 1.0:
        raise ValueError("top_fraction must be in (0, 1]")
    closed = _episode_frame(closed_episodes)
    terminal = _episode_frame(terminal_episodes)
    combined = pd.concat([closed, terminal], ignore_index=True, sort=False)
    if combined.empty:
        return {
            "closed_pair_episodes": len(closed),
            "terminal_pair_episodes": len(terminal),
            "episode_count_including_terminal": 0,
            "top_5pct_pair_episode_count": 0,
            "top_5pct_pair_episodes_positive_pnl_share": None,
            "net_after_top_5pct_pair_episodes_removed": 0.0,
            "total_net_pair_pnl": 0.0,
        }
    column = _column_name(combined, pnl_col, ("net_pnl", "pnl", "realized_pnl", "net_profit"))
    pnl = _finite_column(combined, column)
    count = max(1, ceil(len(pnl) * top_fraction))
    ordered = np.sort(pnl)[::-1]
    removed = ordered[:count]
    positive_total = float(np.clip(pnl, 0.0, None).sum())
    positive_removed = float(np.clip(removed, 0.0, None).sum())
    share = positive_removed / positive_total if positive_total > 0.0 else None
    return {
        "closed_pair_episodes": len(closed),
        "terminal_pair_episodes": len(terminal),
        "episode_count_including_terminal": len(pnl),
        "top_5pct_pair_episode_count": count,
        "top_5pct_pair_episodes_positive_pnl_share": (float(share) if share is not None else None),
        "net_after_top_5pct_pair_episodes_removed": float(pnl.sum() - removed.sum()),
        "total_net_pair_pnl": float(pnl.sum()),
    }


def entry_regime_statistics(
    episodes: Any,
    *,
    pnl_col: str | None = None,
    regime_col: str = "entry_regime",
) -> dict[str, float | int]:
    """Count and attribute episode PnL by high/low spread entry regime.

    Invoke this on H *closed* episodes for sample counts, and independently on
    C2 closed plus terminal episodes for the direction gate.
    """

    frame = _episode_frame(episodes)
    if frame.empty:
        return {
            "pair_episodes": 0,
            "high_spread_entries": 0,
            "low_spread_entries": 0,
            "unknown_entry_regime_entries": 0,
            "high_spread_C2_net_pnl": 0.0,
            "low_spread_C2_net_pnl": 0.0,
            "unknown_entry_regime_net_pnl": 0.0,
        }
    if regime_col not in frame.columns:
        raise ValueError(f"episode data is missing {regime_col!r}")
    column = _column_name(frame, pnl_col, ("net_pnl", "pnl", "realized_pnl", "net_profit"))
    pnl = _finite_column(frame, column)
    regimes = frame[regime_col].astype(str).str.strip().str.lower()
    high = regimes == "high_spread"
    low = regimes == "low_spread"
    unknown = ~(high | low)
    if unknown.any():
        raise ValueError("episode data contains an unknown entry_regime")
    return {
        "pair_episodes": len(frame),
        "high_spread_entries": int(high.sum()),
        "low_spread_entries": int(low.sum()),
        "unknown_entry_regime_entries": int(unknown.sum()),
        "high_spread_C2_net_pnl": float(pnl[high.to_numpy()].sum()),
        "low_spread_C2_net_pnl": float(pnl[low.to_numpy()].sum()),
        "unknown_entry_regime_net_pnl": float(pnl[unknown.to_numpy()].sum()),
    }


def descriptive_symbol_attribution(
    episodes: Any,
    *,
    pnl_col: str | None = None,
    y_symbol_col: str = "y_symbol",
    x_symbol_col: str = "x_symbol",
    y_weight_col: str = "gross_weight_y",
    x_weight_col: str = "gross_weight_x",
) -> dict[str, Any]:
    """Allocate pair PnL by gross entry weights for description only.

    This additive allocation is not a counterfactual replay and consequently
    never emits a passing true-LOSO metric.
    """

    frame = _episode_frame(episodes)
    if frame.empty:
        return {
            "status": DESCRIPTIVE_ATTRIBUTION_ONLY,
            "episodes": 0,
            "symbol_attributed_net_pnl": {},
            "total_net_pair_pnl": 0.0,
            "total_attributed_net_pnl": 0.0,
            "true_loso_available": False,
            "all_true_leave_one_symbol_out_replays_positive": None,
            "effective_symbol_count": None,
        }
    for column in (y_symbol_col, x_symbol_col):
        if column not in frame.columns:
            raise ValueError(f"episode data is missing {column!r}")
        if frame[column].isna().any():
            raise ValueError(f"episode column {column!r} cannot contain missing symbols")
    pnl_name = _column_name(frame, pnl_col, ("net_pnl", "pnl", "realized_pnl", "net_profit"))
    pnl = _finite_column(frame, pnl_name)

    if y_weight_col in frame.columns and x_weight_col in frame.columns:
        y_weight = _finite_column(frame, y_weight_col)
        x_weight = _finite_column(frame, x_weight_col)
    elif "y_entry_notional" in frame.columns and "x_entry_notional" in frame.columns:
        y_weight = np.abs(_finite_column(frame, "y_entry_notional"))
        x_weight = np.abs(_finite_column(frame, "x_entry_notional"))
    else:
        raise ValueError("episode data lacks gross entry weights or entry notionals")
    if (y_weight < 0.0).any() or (x_weight < 0.0).any():
        raise ValueError("gross entry weights cannot be negative")
    gross = y_weight + x_weight
    if (gross <= 0.0).any():
        raise ValueError("gross entry weights must have a positive sum")
    y_weight = y_weight / gross
    x_weight = x_weight / gross

    attributed: dict[str, float] = {}
    for index in range(len(frame)):
        y_symbol = str(frame.iloc[index][y_symbol_col]).strip()
        x_symbol = str(frame.iloc[index][x_symbol_col]).strip()
        if not y_symbol or not x_symbol or y_symbol == x_symbol:
            raise ValueError("pair symbols must be distinct non-empty strings")
        attributed[y_symbol] = attributed.get(y_symbol, 0.0) + float(pnl[index] * y_weight[index])
        attributed[x_symbol] = attributed.get(x_symbol, 0.0) + float(pnl[index] * x_weight[index])
    attributed = dict(sorted(attributed.items()))
    return {
        "status": DESCRIPTIVE_ATTRIBUTION_ONLY,
        "episodes": len(frame),
        "symbol_attributed_net_pnl": attributed,
        "total_net_pair_pnl": float(pnl.sum()),
        "total_attributed_net_pnl": float(sum(attributed.values())),
        "true_loso_available": False,
        "all_true_leave_one_symbol_out_replays_positive": None,
        "effective_symbol_count": None,
    }


def true_loso_statistics(
    full_h_total_net_pnl: float,
    replay_net_pnl_by_omitted_symbol: Mapping[str, float] | pd.Series | None,
    *,
    expected_symbols: Sequence[str] | None = None,
    enforce_frozen_primary: bool = True,
) -> dict[str, Any]:
    """Summarize true H LOSO replays, or explicitly fail closed when unavailable."""

    try:
        full_total = float(full_h_total_net_pnl)
    except (TypeError, ValueError) as exc:
        raise ValueError("full_h_total_net_pnl must be finite") from exc
    if not np.isfinite(full_total):
        raise ValueError("full_h_total_net_pnl must be finite")

    replay = (
        {}
        if replay_net_pnl_by_omitted_symbol is None
        else {
            str(symbol): float(value) for symbol, value in replay_net_pnl_by_omitted_symbol.items()
        }
    )
    expected = set(map(str, expected_symbols)) if expected_symbols is not None else set()
    frozen_symbol_set_mismatch = enforce_frozen_primary and expected != set(FROZEN_PRIMARY_SYMBOLS)
    missing_symbols = sorted(expected - set(replay))
    extra_symbols = sorted(set(replay) - expected) if expected else []
    expected_symbol_set_missing = not expected
    invalid = (
        not replay
        or expected_symbol_set_missing
        or frozen_symbol_set_mismatch
        or missing_symbols
        or extra_symbols
        or not np.isfinite(list(replay.values())).all()
    )
    if invalid:
        reported_replay = {
            symbol: (float(value) if np.isfinite(value) else None)
            for symbol, value in replay.items()
        }
        return {
            "status": TRUE_LOSO_UNAVAILABLE,
            "true_loso_available": False,
            "expected_symbol_set_missing": expected_symbol_set_missing,
            "frozen_primary_symbol_set_mismatch": frozen_symbol_set_mismatch,
            "missing_symbols": missing_symbols,
            "extra_symbols": extra_symbols,
            "replay_net_pnl_by_omitted_symbol": reported_replay,
            "symbol_marginal_net_pnl": None,
            "positive_symbol_marginal_share": None,
            "effective_symbol_count": None,
            "all_true_leave_one_symbol_out_replays_positive": None,
        }

    replay = dict(sorted(replay.items()))
    marginal = {symbol: full_total - value for symbol, value in replay.items()}
    positive = {symbol: max(0.0, value) for symbol, value in marginal.items()}
    positive_total = float(sum(positive.values()))
    if positive_total > 0.0:
        shares = {symbol: value / positive_total for symbol, value in positive.items()}
        effective_n = 1.0 / sum(value * value for value in shares.values())
    else:
        shares = {symbol: 0.0 for symbol in positive}
        effective_n = 0.0
    return {
        "status": TRUE_LOSO_OK,
        "true_loso_available": True,
        "expected_symbol_set_missing": False,
        "frozen_primary_symbol_set_mismatch": False,
        "missing_symbols": [],
        "extra_symbols": [],
        "replay_net_pnl_by_omitted_symbol": replay,
        "symbol_marginal_net_pnl": marginal,
        "positive_symbol_marginal_share": shares,
        "effective_symbol_count": float(effective_n),
        "all_true_leave_one_symbol_out_replays_positive": all(
            value > 0.0 for value in replay.values()
        ),
    }


# Metric path and operation for each YAML gate whose name is not a direct metric.
_GATE_SPECS: dict[tuple[str, str], tuple[str, str]] = {
    ("sample", "pseudo_oos_months"): ("sample.pseudo_oos_months", "eq"),
    ("sample", "minimum_closed_pair_episodes"): ("sample.closed_pair_episodes", "ge"),
    ("sample", "minimum_high_spread_entries"): ("sample.high_spread_entries", "ge"),
    ("sample", "minimum_low_spread_entries"): ("sample.low_spread_entries", "ge"),
    ("sample", "minimum_active_months"): ("sample.active_months", "ge"),
    ("sample", "pair_legs_may_not_count_as_separate_trades"): (
        "sample.pair_legs_may_not_count_as_separate_trades",
        "true",
    ),
    ("H_return", "trimmed_mean_monthly_pct_min"): (
        "H_return.trimmed_mean_monthly_pct",
        "ge",
    ),
    ("H_return", "median_monthly_pct_min"): ("H_return.median_monthly_pct", "ge"),
    ("H_return", "block_bootstrap_90pct_lower_bound_pct_min"): (
        "H_return.block_bootstrap_90pct_lower_bound_pct",
        "ge",
    ),
    ("H_stability", "negative_months_max"): ("H_stability.negative_months", "le"),
    ("H_stability", "months_below_minus_1pct_max"): (
        "H_stability.months_below_minus_1pct",
        "le",
    ),
    ("H_stability", "worst_month_pct_min"): ("H_stability.worst_month_pct", "ge"),
    ("C2_return", "trimmed_mean_monthly_pct_min"): (
        "C2_return.trimmed_mean_monthly_pct",
        "ge",
    ),
    ("C2_return", "median_monthly_pct_min"): ("C2_return.median_monthly_pct", "ge"),
    ("C2_return", "total_return_must_be_positive"): ("C2_return.total_return_pct", "gt0"),
    ("drawdown", "B_max_mtm_pct"): ("drawdown.B_max_mtm_pct", "le"),
    ("drawdown", "C2_H_max_mtm_pct"): ("drawdown.C2_H_max_mtm_pct", "le"),
    ("drawdown", "max_recovery_months"): ("drawdown.max_recovery_months", "le"),
    ("walk_forward", "positive_folds_min"): ("walk_forward.positive_folds", "ge"),
    ("walk_forward", "total_folds"): ("walk_forward.total_folds", "eq"),
    ("walk_forward", "worst_six_month_fold_pct_min"): (
        "walk_forward.worst_six_month_fold_pct",
        "ge",
    ),
    ("walk_forward", "oos_to_is_trimmed_return_ratio_min"): (
        "walk_forward.oos_to_is_trimmed_return_ratio",
        "ge",
    ),
    ("walk_forward", "oos_to_is_drawdown_ratio_max"): (
        "walk_forward.oos_to_is_drawdown_ratio",
        "le",
    ),
    (
        "economic_edge",
        "B_closed_pair_price_pnl_before_execution_and_funding_must_be_positive",
    ): ("economic_edge.B_closed_pair_price_pnl_before_execution_and_funding", "gt0"),
    ("economic_edge", "B_pre_cost_price_pnl_over_execution_cost_min"): (
        "economic_edge.B_pre_cost_price_pnl_over_execution_cost",
        "ge",
    ),
    ("economic_edge", "median_entry_expected_edge_over_stressed_cost_min"): (
        "economic_edge.median_entry_expected_edge_over_stressed_cost",
        "ge",
    ),
    ("concentration", "best_month_positive_pnl_share_max"): (
        "concentration.best_month_positive_pnl_share",
        "le",
    ),
    ("concentration", "best_3_month_positive_pnl_share_max"): (
        "concentration.best_3_month_positive_pnl_share",
        "le",
    ),
    ("concentration", "top_5pct_pair_episodes_positive_pnl_share_max"): (
        "concentration.top_5pct_pair_episodes_positive_pnl_share",
        "le",
    ),
    ("concentration", "net_after_top_5pct_pair_episodes_removed_must_be_positive"): (
        "concentration.net_after_top_5pct_pair_episodes_removed",
        "gt0",
    ),
    ("concentration", "effective_symbol_count_min"): (
        "concentration.effective_symbol_count",
        "ge",
    ),
    ("concentration", "all_true_leave_one_symbol_out_replays_positive"): (
        "concentration.all_true_leave_one_symbol_out_replays_positive",
        "true",
    ),
    ("holdout", "C2_total_return_must_be_positive"): ("holdout.C2_total_return_pct", "gt0"),
    ("holdout", "primary_return_retention_min"): (
        "holdout.primary_return_retention",
        "ge",
    ),
    ("holdout", "distinct_holdout_symbols_traded_min"): (
        "holdout.distinct_holdout_symbols_traded",
        "ge",
    ),
    ("holdout", "distinct_closed_holdout_pairs_min"): (
        "holdout.distinct_closed_holdout_pairs",
        "ge",
    ),
    ("holdout", "minimum_closed_pair_episodes"): (
        "holdout.closed_pair_episodes",
        "ge",
    ),
    ("holdout", "minimum_active_months"): ("holdout.active_months", "ge"),
    ("holdout", "max_drawdown_pct"): ("holdout.max_drawdown_pct", "le"),
    ("direction", "high_spread_C2_net_must_be_positive"): (
        "direction.high_spread_C2_net_pnl",
        "gt0",
    ),
    ("direction", "low_spread_C2_net_must_be_positive"): (
        "direction.low_spread_C2_net_pnl",
        "gt0",
    ),
    ("multiple_testing", "paired_block_months"): (
        "multiple_testing.paired_block_months",
        "eq",
    ),
    ("multiple_testing", "bootstrap_iterations"): (
        "multiple_testing.bootstrap_iterations",
        "eq",
    ),
    ("multiple_testing", "holm_fwer_adjusted_p_max"): (
        "multiple_testing.holm_fwer_adjusted_p",
        "le",
    ),
    ("multiple_testing", "deflated_sharpe_min"): (
        "multiple_testing.deflated_sharpe",
        "ge",
    ),
    ("multiple_testing", "probability_backtest_overfit_max"): (
        "multiple_testing.probability_backtest_overfit",
        "le",
    ),
    ("multiple_testing", "local_v17_trial_count"): (
        "multiple_testing.local_v17_trial_count",
        "eq",
    ),
    ("multiple_testing", "cumulative_program_trial_count_including_v16"): (
        "multiple_testing.cumulative_program_trial_count_including_v16",
        "eq",
    ),
    ("multiple_testing", "cumulative_program_holm_adjusted_p_max"): (
        "multiple_testing.cumulative_program_holm_adjusted_p",
        "le",
    ),
    ("multiple_testing", "cumulative_program_deflated_sharpe_min"): (
        "multiple_testing.cumulative_program_deflated_sharpe",
        "ge",
    ),
    ("multiple_testing", "cumulative_program_probability_backtest_overfit_max"): (
        "multiple_testing.cumulative_program_probability_backtest_overfit",
        "le",
    ),
}

_NONNEGATIVE_METRICS = {
    "sample.pseudo_oos_months",
    "sample.closed_pair_episodes",
    "sample.high_spread_entries",
    "sample.low_spread_entries",
    "sample.active_months",
    "H_stability.negative_months",
    "H_stability.months_below_minus_1pct",
    "drawdown.B_max_mtm_pct",
    "drawdown.C2_H_max_mtm_pct",
    "drawdown.max_recovery_months",
    "walk_forward.positive_folds",
    "walk_forward.total_folds",
    "walk_forward.oos_to_is_drawdown_ratio",
    "concentration.best_month_positive_pnl_share",
    "concentration.best_3_month_positive_pnl_share",
    "concentration.top_5pct_pair_episodes_positive_pnl_share",
    "concentration.effective_symbol_count",
    "holdout.primary_return_retention",
    "holdout.distinct_holdout_symbols_traded",
    "holdout.distinct_closed_holdout_pairs",
    "holdout.closed_pair_episodes",
    "holdout.active_months",
    "holdout.max_drawdown_pct",
    "multiple_testing.paired_block_months",
    "multiple_testing.bootstrap_iterations",
    "multiple_testing.holm_fwer_adjusted_p",
    "multiple_testing.deflated_sharpe",
    "multiple_testing.probability_backtest_overfit",
    "multiple_testing.local_v17_trial_count",
    "multiple_testing.cumulative_program_trial_count_including_v16",
    "multiple_testing.cumulative_program_holm_adjusted_p",
    "multiple_testing.cumulative_program_deflated_sharpe",
    "multiple_testing.cumulative_program_probability_backtest_overfit",
}

_UNIT_INTERVAL_METRICS = {
    "concentration.best_month_positive_pnl_share",
    "concentration.best_3_month_positive_pnl_share",
    "concentration.top_5pct_pair_episodes_positive_pnl_share",
    "multiple_testing.holm_fwer_adjusted_p",
    "multiple_testing.deflated_sharpe",
    "multiple_testing.probability_backtest_overfit",
    "multiple_testing.cumulative_program_holm_adjusted_p",
    "multiple_testing.cumulative_program_deflated_sharpe",
    "multiple_testing.cumulative_program_probability_backtest_overfit",
}


def _metric_value(metrics: Mapping[str, Any], path: str) -> tuple[bool, Any]:
    if path in metrics:
        return True, metrics[path]
    current: Any = metrics
    for part in path.split("."):
        if not isinstance(current, Mapping) or part not in current:
            return False, None
        current = current[part]
    return True, current


def _direct_gate_spec(group: str, gate: str, threshold: Any) -> tuple[str, str]:
    path = f"{group}.{gate}"
    if gate.endswith("_min"):
        return f"{group}.{gate.removesuffix('_min')}", "ge"
    if gate.endswith("_max"):
        return f"{group}.{gate.removesuffix('_max')}", "le"
    if gate.endswith("_must_be_positive"):
        return f"{group}.{gate.removesuffix('_must_be_positive')}", "gt0"
    if threshold is True:
        return path, "true"
    return path, "eq_value"


def _comparison(value: Any, threshold: Any, operation: str) -> bool:
    if operation == "true":
        return value is True or (isinstance(value, np.bool_) and bool(value))
    if operation == "eq_value" and isinstance(threshold, str):
        return isinstance(value, str) and value == threshold
    try:
        numeric_value = float(value)
        numeric_threshold = float(threshold)
    except (TypeError, ValueError):
        return False
    if not np.isfinite(numeric_value) or not np.isfinite(numeric_threshold):
        return False
    if operation in {"eq", "eq_value"}:
        return isclose(numeric_value, numeric_threshold, rel_tol=0.0, abs_tol=1e-12)
    if operation == "ge":
        return numeric_value >= numeric_threshold
    if operation == "le":
        return numeric_value <= numeric_threshold
    if operation == "gt0":
        return numeric_value > 0.0
    raise ValueError(f"unsupported gate operation {operation!r}")


def evaluate_v17_hard_gates(
    metrics: Mapping[str, Any],
    *,
    hard_gates: Mapping[str, Any] | None = None,
    require_complete_contract: bool = True,
) -> dict[str, Any]:
    """Evaluate a v17 YAML ``hard_gates`` mapping without silent skips.

    ``hard_gates`` may be either the gate mapping itself or the full preregistration
    mapping containing a ``hard_gates`` key.  Missing, ``None``, non-finite, and
    negative domain-invalid metrics all fail; no absent metric can pass.
    """

    selected: Any = DEFAULT_V17_HARD_GATES if hard_gates is None else hard_gates
    if isinstance(selected, Mapping) and "hard_gates" in selected:
        selected = selected["hard_gates"]
    if not isinstance(selected, Mapping) or not selected:
        raise ValueError("hard_gates must be a non-empty mapping")
    if require_complete_contract and selected != DEFAULT_V17_HARD_GATES:
        raise ValueError("hard_gates must exactly match the complete frozen v17 contract")

    checks: dict[str, dict[str, Any]] = {}
    failed: list[str] = []
    missing: list[str] = []
    for group, group_gates in selected.items():
        if not isinstance(group_gates, Mapping):
            raise ValueError(f"hard gate group {group!r} must be a mapping")
        for gate, threshold in group_gates.items():
            metric_path, operation = _GATE_SPECS.get(
                (str(group), str(gate)),
                _direct_gate_spec(str(group), str(gate), threshold),
            )
            found, value = _metric_value(metrics, metric_path)
            reason: str | None = None
            invalid_negative = False
            invalid_nonfinite = False
            invalid_unit_interval = False
            if found and value is not None and isinstance(value, float | np.floating):
                invalid_nonfinite = not np.isfinite(value)
            if found and value is not None and metric_path in _NONNEGATIVE_METRICS:
                try:
                    invalid_negative = float(value) < 0.0
                except (TypeError, ValueError):
                    invalid_negative = True
            if found and value is not None and metric_path in _UNIT_INTERVAL_METRICS:
                try:
                    numeric_value = float(value)
                    invalid_unit_interval = not 0.0 <= numeric_value <= 1.0
                except (TypeError, ValueError):
                    invalid_unit_interval = True
            if not found or value is None:
                passed = False
                reason = "MISSING_METRIC"
                missing.append(f"{group}.{gate}")
            elif invalid_negative:
                passed = False
                reason = "INVALID_SIGN"
            elif invalid_nonfinite:
                passed = False
                reason = "NONFINITE_METRIC"
            elif invalid_unit_interval:
                passed = False
                reason = "OUT_OF_RANGE"
            else:
                passed = _comparison(value, threshold, operation)
                if not passed:
                    reason = "THRESHOLD_NOT_MET"
            gate_path = f"{group}.{gate}"
            checks[gate_path] = {
                "passed": bool(passed),
                "metric": metric_path,
                "value": None if invalid_nonfinite else value,
                "comparison": operation,
                "threshold": threshold,
                "reason": reason,
            }
            if not passed:
                failed.append(gate_path)

    return {
        "passed": not failed,
        "checks": checks,
        "failed_gates": failed,
        "missing_gates": missing,
        "passed_count": len(checks) - len(failed),
        "total_count": len(checks),
    }


__all__ = [
    "BLOCK_MONTHS",
    "BOOTSTRAP_LOWER_QUANTILE",
    "DEFAULT_V17_HARD_GATES",
    "DEGENERATE_TRIAL_SHARPE",
    "DESCRIPTIVE_ATTRIBUTION_ONLY",
    "EXPECTED_H_MONTHS",
    "EXPECTED_PROGRAM_CANDIDATES",
    "EXPECTED_V17_CANDIDATES",
    "FROZEN_H_MONTHS",
    "FROZEN_PROGRAM_CANDIDATE_IDS",
    "FROZEN_V16_CANDIDATE_IDS",
    "FROZEN_V17_CANDIDATE_IDS",
    "PBO_SLICES",
    "SIGN_FLIP_BLOCKS",
    "TRIM_FRACTION",
    "TRUE_LOSO_OK",
    "TRUE_LOSO_UNAVAILABLE",
    "VALIDATION_ITERATIONS",
    "VALIDATION_SEED",
    "candidate_block_sign_flip_test",
    "descriptive_symbol_attribution",
    "entry_regime_statistics",
    "episode_concentration_statistics",
    "evaluate_v17_hard_gates",
    "exact_h_candidate_matrix",
    "exact_h_monthly_returns",
    "exact_program_candidate_matrix",
    "h_monthly_statistics",
    "program_wide_multiple_testing",
    "rank_h_candidates",
    "three_candidate_multiple_testing",
    "true_loso_statistics",
]
