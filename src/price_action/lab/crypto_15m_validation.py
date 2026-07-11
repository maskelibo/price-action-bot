"""Deterministic validation helpers for the preregistered 15-minute crypto study.

The functions in this module deliberately operate on pandas objects and duck-typed
portfolio results.  They do not import the backtest engine, so research reports can
use them without creating an engine/report import cycle.

Return values whose names end in ``_pct`` are percentage points (``10.0`` means
10 percent), while concentration and retention values are fractions in ``[0, 1]``.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from itertools import combinations
from math import ceil, e, inf, isclose, log, sqrt
from statistics import NormalDist
from typing import Any

import numpy as np
import pandas as pd

NOT_ENOUGH_CONFIGS = "NOT_ENOUGH_CONFIGS"


# Kept in code as well as YAML so evaluation is pure, deterministic, and does not
# depend on the process working directory.  A caller may pass a different mapping.
DEFAULT_HARD_GATES: dict[str, dict[str, float | int | bool]] = {
    "sample": {
        "pseudo_oos_months": 36,
        "minimum_closed_trades": 360,
        "minimum_long_trades": 60,
        "minimum_short_trades": 60,
        "missing_month_return_pct": 0.0,
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
    "concentration": {
        "best_month_positive_pnl_share_max": 0.15,
        "best_3_month_positive_pnl_share_max": 0.35,
        "mean_after_best_3_months_removed_pct_min": 7.0,
        "top_5pct_trades_positive_pnl_share_max": 0.65,
        "net_after_top_5pct_trades_removed_must_be_positive": True,
        "single_symbol_marginal_share_max": 0.20,
        "top_3_symbol_marginal_share_max": 0.50,
        "effective_symbol_count_min": 6,
        "all_leave_one_symbol_out_positive": True,
    },
    "holdout": {
        "C2_total_return_must_be_positive": True,
        "development_return_retention_min": 0.40,
        "positive_holdout_symbols_min": 3,
        "holdout_symbols_total": 4,
        "max_drawdown_pct": 25.0,
    },
    "direction": {
        "long_C2_net_must_be_positive": True,
        "short_C2_net_must_be_positive": True,
    },
    "multiple_testing": {
        "paired_block_months": 3,
        "bootstrap_iterations": 20_000,
        "holm_fwer_adjusted_p_max": 0.05,
        "deflated_sharpe_min": 0.95,
        "probability_backtest_overfit_max": 0.20,
    },
}


def _finite_array(values: Sequence[float] | pd.Series | np.ndarray) -> np.ndarray:
    array = np.asarray(values, dtype=float).reshape(-1)
    return array[np.isfinite(array)]


def _strict_array(values: Sequence[float] | pd.Series | np.ndarray) -> np.ndarray:
    array = np.asarray(values, dtype=float).reshape(-1)
    if array.size == 0:
        raise ValueError("at least one observation is required")
    if not np.isfinite(array).all():
        raise ValueError("observations must all be finite")
    return array


def _compound_return_pct(values: Sequence[float] | np.ndarray) -> float:
    array = _strict_array(values)
    return float((np.prod(1.0 + array / 100.0) - 1.0) * 100.0)


def _month_period_index(index: pd.Index) -> pd.PeriodIndex:
    if isinstance(index, pd.PeriodIndex):
        return index.asfreq("M")
    timestamps = pd.DatetimeIndex(pd.to_datetime(index, utc=True)).tz_convert(None)
    return timestamps.to_period("M")


def _period(value: str | pd.Timestamp | pd.Period) -> pd.Period:
    if isinstance(value, pd.Period):
        return value.asfreq("M")
    return pd.Period(pd.Timestamp(value), freq="M")


def _series_from_frame(
    data: pd.Series | pd.DataFrame,
    *,
    value_col: str | None,
    timestamp_col: str,
    candidates: Sequence[str],
) -> pd.Series:
    if isinstance(data, pd.Series):
        return data.copy()

    frame = data.copy()
    if timestamp_col in frame.columns:
        frame = frame.set_index(timestamp_col)
    if value_col is None:
        value_col = next((column for column in candidates if column in frame.columns), None)
    if value_col is None and len(frame.columns) == 1:
        value_col = str(frame.columns[0])
    if value_col is None or value_col not in frame.columns:
        raise ValueError(f"could not identify a value column; tried {list(candidates)}")
    return frame[value_col].copy()


def _duck_value(source: Any, names: Sequence[str]) -> Any:
    if isinstance(source, Mapping):
        for name in names:
            if name in source:
                return source[name]
    for name in names:
        if hasattr(source, name):
            return getattr(source, name)
    return source


def continuous_monthly_returns(
    monthly_returns: pd.Series | pd.DataFrame | Sequence[float],
    *,
    start: str | pd.Timestamp | pd.Period | None = None,
    end: str | pd.Timestamp | pd.Period | None = None,
    missing_return_pct: float = 0.0,
    return_col: str | None = None,
    timestamp_col: str = "timestamp",
) -> pd.Series:
    """Return a gap-free monthly percentage-return series.

    Multiple rows in the same month are compounded.  Missing calendar months are
    filled with ``missing_return_pct`` (zero in the preregistration).  For an
    undated sequence, ``start`` is required and consecutive months are assumed.
    """

    if isinstance(monthly_returns, pd.Series | pd.DataFrame):
        series = _series_from_frame(
            monthly_returns,
            value_col=return_col,
            timestamp_col=timestamp_col,
            candidates=("monthly_return_pct", "return_pct", "return", "returns"),
        )
        if isinstance(series.index, pd.RangeIndex):
            if start is None:
                raise ValueError("start is required for an undated return series")
            series.index = pd.period_range(_period(start), periods=len(series), freq="M")
        else:
            series.index = _month_period_index(series.index)
    else:
        if start is None:
            raise ValueError("start is required for an undated return sequence")
        values = np.asarray(monthly_returns, dtype=float).reshape(-1)
        series = pd.Series(
            values,
            index=pd.period_range(_period(start), periods=len(values), freq="M"),
        )

    numeric = pd.to_numeric(series, errors="coerce")
    numeric_values = numeric.to_numpy(dtype=float)
    if numeric.isna().any() or not np.isfinite(numeric_values).all():
        raise ValueError("observed monthly returns must all be finite numeric values")

    def compound_month(group: pd.Series) -> float:
        values = _finite_array(group)
        if values.size == 0:
            return float("nan")
        return _compound_return_pct(values)

    grouped = numeric.groupby(numeric.index).apply(compound_month).sort_index()
    if start is None:
        if grouped.empty:
            raise ValueError("start and end are required for an empty series")
        start_period = grouped.index.min()
    else:
        start_period = _period(start)
    if end is None:
        if grouped.empty:
            raise ValueError("start and end are required for an empty series")
        end_period = grouped.index.max()
    else:
        end_period = _period(end)
    if start_period > end_period:
        raise ValueError("start must not be after end")

    full_index = pd.period_range(start_period, end_period, freq="M")
    missing = len(full_index.difference(grouped.dropna().index))
    result = grouped.reindex(full_index).fillna(float(missing_return_pct)).astype(float)
    result.name = "monthly_return_pct"
    result.attrs["missing_months"] = missing
    result.attrs["missing_return_pct"] = float(missing_return_pct)
    return result


def monthly_returns_from_equity(
    portfolio_or_equity: Any,
    *,
    start: str | pd.Timestamp | pd.Period | None = None,
    end: str | pd.Timestamp | pd.Period | None = None,
    initial_equity: float | None = None,
    equity_col: str | None = None,
    timestamp_col: str = "timestamp",
) -> pd.Series:
    """Build gap-free month-end returns from an equity curve or portfolio result.

    A portfolio result is accepted by duck typing: ``equity_curve``, ``equity`` or
    ``curve`` may contain the pandas object.  Months with no observations carry
    equity forward and therefore have a zero return.
    """

    source = _duck_value(portfolio_or_equity, ("equity_curve", "equity", "curve"))
    if not isinstance(source, pd.Series | pd.DataFrame):
        raise TypeError("equity input must be a pandas Series/DataFrame or expose one")
    equity = _series_from_frame(
        source,
        value_col=equity_col,
        timestamp_col=timestamp_col,
        candidates=("equity", "total_equity", "balance", "mark_to_market_equity"),
    )
    if equity.empty:
        if start is None or end is None:
            raise ValueError("start and end are required for an empty equity curve")
        return continuous_monthly_returns([], start=start, end=end)

    equity = pd.to_numeric(equity, errors="coerce").dropna()
    if equity.empty:
        raise ValueError("equity curve has no finite numeric observations")
    timestamps = pd.DatetimeIndex(pd.to_datetime(equity.index, utc=True)).tz_convert(None)
    equity.index = timestamps
    equity = equity.sort_index()
    equity = equity[~equity.index.duplicated(keep="last")]
    periods = equity.index.to_period("M")

    start_period = _period(start) if start is not None else periods.min()
    end_period = _period(end) if end is not None else periods.max()
    if start_period > end_period:
        raise ValueError("start must not be after end")
    full_index = pd.period_range(start_period, end_period, freq="M")

    prior = equity.loc[periods < start_period]
    if initial_equity is not None:
        baseline = float(initial_equity)
    elif not prior.empty:
        baseline = float(prior.iloc[-1])
    else:
        at_or_after = equity.loc[periods >= start_period]
        baseline = float(equity.iloc[-1]) if at_or_after.empty else float(at_or_after.iloc[0])
    if not np.isfinite(baseline) or baseline == 0.0:
        raise ValueError("initial equity must be finite and non-zero")

    monthly_close = equity.groupby(periods).last().reindex(full_index)
    monthly_close = monthly_close.ffill().fillna(baseline)
    previous = monthly_close.shift(1)
    previous.iloc[0] = baseline
    if (previous == 0.0).any():
        raise ValueError("equity cannot cross a zero denominator")
    result = (monthly_close / previous - 1.0) * 100.0
    result.name = "monthly_return_pct"
    result.attrs["missing_months"] = len(
        full_index.difference(pd.PeriodIndex(periods.unique(), freq="M"))
    )
    result.attrs["missing_return_pct"] = 0.0
    return result.astype(float)


def trimmed_mean_pct(
    values: Sequence[float] | pd.Series | np.ndarray,
    *,
    proportion_to_cut: float = 0.10,
) -> float:
    """Return the symmetric trimmed arithmetic mean in percentage points."""

    if not 0.0 <= proportion_to_cut < 0.5:
        raise ValueError("proportion_to_cut must be in [0, 0.5)")
    array = np.sort(_strict_array(values))
    cut = int(np.floor(array.size * proportion_to_cut))
    kept = array[cut : array.size - cut] if cut else array
    return float(np.mean(kept))


def monthly_return_statistics(
    monthly_returns: Sequence[float] | pd.Series | np.ndarray,
    *,
    monthly_pnl: Sequence[float] | pd.Series | np.ndarray | None = None,
) -> dict[str, float | int]:
    """Compute preregistered return, stability, and month-concentration metrics."""

    returns = _strict_array(monthly_returns)
    pnl = returns if monthly_pnl is None else _strict_array(monthly_pnl)
    if pnl.size != returns.size:
        raise ValueError("monthly_pnl and monthly_returns must have equal length")

    positive_pnl = np.clip(pnl, 0.0, None)
    positive_total = float(positive_pnl.sum())
    ordered_positive = np.sort(positive_pnl)[::-1]
    if positive_total > 0.0:
        best_share = float(ordered_positive[0] / positive_total)
        best_three_share = float(ordered_positive[:3].sum() / positive_total)
    else:
        best_share = inf
        best_three_share = inf

    remove_count = min(3, returns.size)
    keep = np.argsort(returns)[: returns.size - remove_count]
    mean_without_best_three = float(np.mean(returns[keep])) if keep.size else float("nan")
    return {
        "months": int(returns.size),
        "trimmed_mean_monthly_pct": trimmed_mean_pct(returns),
        "median_monthly_pct": float(np.median(returns)),
        "negative_months": int(np.sum(returns < 0.0)),
        "months_below_minus_1pct": int(np.sum(returns < -1.0)),
        "worst_month_pct": float(np.min(returns)),
        "best_month_pct": float(np.max(returns)),
        "total_return_pct": _compound_return_pct(returns),
        "best_month_positive_pnl_share": best_share,
        "best_3_month_positive_pnl_share": best_three_share,
        "mean_after_best_3_months_removed_pct": mean_without_best_three,
    }


def drawdown_recovery_statistics(
    monthly_returns: Sequence[float] | pd.Series | np.ndarray,
) -> dict[str, float | int]:
    """Compute mark-to-market drawdown and longest monthly underwater spell."""

    returns = _strict_array(monthly_returns)
    equity = np.concatenate(([1.0], np.cumprod(1.0 + returns / 100.0)))
    peaks = np.maximum.accumulate(equity)
    drawdowns = 1.0 - equity / peaks

    longest = 0
    current = 0
    for value, peak in zip(equity[1:], peaks[1:], strict=True):
        if value >= peak - 1e-12:
            current = 0
        else:
            current += 1
            longest = max(longest, current)
    return {
        "max_mtm_drawdown_pct": float(np.max(drawdowns) * 100.0),
        "max_recovery_months": longest,
    }


def _ledger_frame(portfolio_or_ledger: Any) -> pd.DataFrame:
    source = _duck_value(portfolio_or_ledger, ("ledger", "trades", "closed_trades"))
    if not isinstance(source, pd.DataFrame):
        raise TypeError("ledger input must be a pandas DataFrame or expose one")
    return source.copy()


def _pnl_series(frame: pd.DataFrame, pnl_col: str | None) -> pd.Series:
    if pnl_col is None:
        pnl_col = next(
            (
                column
                for column in ("net_pnl", "pnl", "realized_pnl", "net_profit")
                if column in frame.columns
            ),
            None,
        )
    if pnl_col is None or pnl_col not in frame.columns:
        raise ValueError("could not identify a trade PnL column")
    return pd.to_numeric(frame[pnl_col], errors="coerce")


def trade_concentration_statistics(
    portfolio_or_ledger: Any,
    *,
    pnl_col: str | None = None,
    top_fraction: float = 0.05,
) -> dict[str, float | int]:
    """Measure dependence on the highest-PnL fraction of closed trades."""

    if not 0.0 < top_fraction <= 1.0:
        raise ValueError("top_fraction must be in (0, 1]")
    frame = _ledger_frame(portfolio_or_ledger)
    pnl = _pnl_series(frame, pnl_col).dropna().astype(float)
    if pnl.empty:
        return {
            "closed_trades": 0,
            "top_5pct_trade_count": 0,
            "top_5pct_trades_positive_pnl_share": inf,
            "net_after_top_5pct_trades_removed": 0.0,
            "total_net_pnl": 0.0,
        }

    count = max(1, ceil(len(pnl) * top_fraction))
    top = pnl.nlargest(count)
    positive_total = float(pnl.clip(lower=0.0).sum())
    positive_top = float(top.clip(lower=0.0).sum())
    share = positive_top / positive_total if positive_total > 0.0 else inf
    return {
        "closed_trades": len(pnl),
        "top_5pct_trade_count": count,
        "top_5pct_trades_positive_pnl_share": float(share),
        "net_after_top_5pct_trades_removed": float(pnl.sum() - top.sum()),
        "total_net_pnl": float(pnl.sum()),
    }


def direction_pnl_statistics(
    portfolio_or_ledger: Any,
    *,
    pnl_col: str | None = None,
    direction_col: str = "side",
) -> dict[str, float | int]:
    """Return long/short trade counts and additive net PnL."""

    frame = _ledger_frame(portfolio_or_ledger)
    if direction_col not in frame.columns:
        direction_col = next(
            (column for column in ("direction", "position_side") if column in frame.columns),
            direction_col,
        )
    if direction_col not in frame.columns:
        raise ValueError("could not identify a trade direction column")
    pnl = _pnl_series(frame, pnl_col)
    sides = frame[direction_col].astype(str).str.strip().str.lower()
    long_mask = sides.isin({"long", "buy", "1", "+1"})
    short_mask = sides.isin({"short", "sell", "-1"})
    valid_pnl = pnl.notna()
    return {
        "long_trades": int((long_mask & valid_pnl).sum()),
        "short_trades": int((short_mask & valid_pnl).sum()),
        "unknown_direction_trades": int((~long_mask & ~short_mask & valid_pnl).sum()),
        "long_C2_net_pnl": float(pnl[long_mask].sum()),
        "short_C2_net_pnl": float(pnl[short_mask].sum()),
    }


def symbol_concentration_statistics(
    portfolio_or_ledger: Any,
    *,
    pnl_col: str | None = None,
    symbol_col: str = "symbol",
) -> dict[str, Any]:
    """Compute additive symbol marginals, effective N, and leave-one-out PnL.

    Marginal shares use positive symbol contributions only.  Negative contributors
    therefore cannot make concentration look artificially diversified.
    """

    frame = _ledger_frame(portfolio_or_ledger)
    if symbol_col not in frame.columns:
        raise ValueError(f"ledger is missing {symbol_col!r}")
    pnl = _pnl_series(frame, pnl_col)
    valid = pnl.notna() & frame[symbol_col].notna()
    by_symbol = (
        pd.DataFrame({"symbol": frame.loc[valid, symbol_col].astype(str), "pnl": pnl[valid]})
        .groupby("symbol", sort=True)["pnl"]
        .sum()
    )
    total = float(by_symbol.sum())
    positive = by_symbol.clip(lower=0.0)
    positive_total = float(positive.sum())
    if positive_total > 0.0:
        shares = positive / positive_total
        single_share = float(shares.max())
        top_three_share = float(shares.nlargest(3).sum())
        effective_n = float(1.0 / np.square(shares.to_numpy(dtype=float)).sum())
    else:
        shares = positive
        single_share = inf
        top_three_share = inf
        effective_n = 0.0

    leave_one_out = {symbol: total - float(value) for symbol, value in by_symbol.items()}
    all_loso_positive = bool(leave_one_out) and all(value > 0.0 for value in leave_one_out.values())
    return {
        "symbol_net_pnl": {symbol: float(value) for symbol, value in by_symbol.items()},
        "symbol_marginal_share": {symbol: float(value) for symbol, value in shares.items()},
        "single_symbol_marginal_share": single_share,
        "top_3_symbol_marginal_share": top_three_share,
        "effective_symbol_count": effective_n,
        "leave_one_symbol_out_net_pnl": leave_one_out,
        "all_leave_one_symbol_out_positive": all_loso_positive,
        "symbols": len(by_symbol),
        "total_net_pnl": total,
    }


def six_nonoverlap_fold_statistics(
    monthly_returns: Sequence[float] | pd.Series | np.ndarray,
    *,
    fold_months: int = 6,
    total_folds: int = 6,
) -> dict[str, Any]:
    """Compound exactly six non-overlapping six-month pseudo-OOS folds."""

    if fold_months <= 0 or total_folds <= 0:
        raise ValueError("fold_months and total_folds must be positive")
    returns = _strict_array(monthly_returns)
    expected = fold_months * total_folds
    if returns.size != expected:
        raise ValueError(f"expected exactly {expected} months, got {returns.size}")
    folds = [
        _compound_return_pct(returns[offset : offset + fold_months])
        for offset in range(0, expected, fold_months)
    ]
    return {
        "fold_returns_pct": folds,
        "positive_folds": int(sum(value > 0.0 for value in folds)),
        "total_folds": total_folds,
        "worst_six_month_fold_pct": float(min(folds)),
    }


def block_bootstrap_lower_bound_pct(
    monthly_returns: Sequence[float] | pd.Series | np.ndarray,
    *,
    block_months: int = 3,
    iterations: int = 20_000,
    confidence: float = 0.90,
    seed: int = 16,
    trim_fraction: float = 0.10,
) -> float:
    """One-sided lower bound for the trimmed monthly mean via moving blocks."""

    returns = _strict_array(monthly_returns)
    if block_months <= 0 or block_months > returns.size:
        raise ValueError("block_months must be between 1 and the sample size")
    if iterations <= 0:
        raise ValueError("iterations must be positive")
    if not 0.0 < confidence < 1.0:
        raise ValueError("confidence must be in (0, 1)")
    if not 0.0 <= trim_fraction < 0.5:
        raise ValueError("trim_fraction must be in [0, 0.5)")

    blocks = np.lib.stride_tricks.sliding_window_view(returns, block_months)
    blocks_per_sample = ceil(returns.size / block_months)
    rng = np.random.default_rng(seed)
    selected = rng.integers(0, len(blocks), size=(iterations, blocks_per_sample))
    samples = blocks[selected].reshape(iterations, -1)[:, : returns.size]
    samples.sort(axis=1)
    cut = int(np.floor(returns.size * trim_fraction))
    kept = samples[:, cut : returns.size - cut] if cut else samples
    estimates = kept.mean(axis=1)
    return float(np.quantile(estimates, 1.0 - confidence))


def holm_adjusted_pvalues(
    pvalues: Mapping[str, float] | Sequence[float],
) -> dict[str, float] | list[float]:
    """Holm step-down family-wise-error adjusted p-values."""

    is_mapping = isinstance(pvalues, Mapping)
    keys = list(pvalues) if is_mapping else list(range(len(pvalues)))
    raw = np.asarray(
        [pvalues[key] for key in keys] if is_mapping else list(pvalues),
        dtype=float,
    )
    if raw.size == 0:
        return {} if is_mapping else []
    if not np.isfinite(raw).all() or ((raw < 0.0) | (raw > 1.0)).any():
        raise ValueError("p-values must be finite and in [0, 1]")

    order = np.argsort(raw, kind="stable")
    adjusted = np.empty_like(raw)
    running = 0.0
    count = len(raw)
    for rank, index in enumerate(order):
        running = max(running, (count - rank) * float(raw[index]))
        adjusted[index] = min(1.0, running)
    if is_mapping:
        return {str(key): float(adjusted[index]) for index, key in enumerate(keys)}
    return [float(value) for value in adjusted]


def deflated_sharpe_statistics(
    returns: Sequence[float] | pd.Series | np.ndarray,
    *,
    n_trials: int,
    trial_sharpes: Sequence[float] | None = None,
    periods_per_year: int = 12,
) -> dict[str, float | int]:
    """Compute Bailey/Lopez-de-Prado's deflated Sharpe probability.

    ``returns`` may be in decimal or percentage units because Sharpe is scale-free.
    ``trial_sharpes``, when supplied, must use the same *unannualized* periodic
    Sharpe convention as ``observed_sharpe``.
    """

    values = _strict_array(returns)
    if values.size < 3:
        raise ValueError("at least three returns are required")
    if n_trials <= 0:
        raise ValueError("n_trials must be positive")
    if periods_per_year <= 0:
        raise ValueError("periods_per_year must be positive")
    if n_trials > 1 and trial_sharpes is None:
        raise ValueError("trial_sharpes are required when n_trials is greater than one")

    sample_std = float(np.std(values, ddof=1))
    mean = float(np.mean(values))
    if sample_std == 0.0:
        probability = 1.0 if mean > 0.0 else (0.0 if mean < 0.0 else 0.5)
        observed = inf if mean > 0.0 else (-inf if mean < 0.0 else 0.0)
        return {
            "deflated_sharpe": probability,
            "observed_sharpe": observed,
            "annualized_sharpe": observed,
            "expected_max_sharpe": 0.0,
            "n_trials": n_trials,
            "observations": int(values.size),
        }

    observed = mean / sample_std
    centered = values - mean
    population_std = float(np.std(values, ddof=0))
    standardized = centered / population_std
    skew = float(np.mean(standardized**3))
    kurtosis = float(np.mean(standardized**4))
    variance_term = max(
        1e-15,
        1.0 - skew * observed + ((kurtosis - 1.0) / 4.0) * observed**2,
    )
    sharpe_standard_error = sqrt(variance_term / (values.size - 1))

    if trial_sharpes is not None:
        trial_array = _strict_array(trial_sharpes)
        if trial_array.size != n_trials:
            raise ValueError("trial_sharpes must contain exactly n_trials values")
        trial_dispersion = (
            float(np.std(trial_array, ddof=1)) if trial_array.size > 1 else sharpe_standard_error
        )
    else:
        trial_dispersion = sharpe_standard_error

    if n_trials == 1 or trial_dispersion == 0.0:
        expected_max = 0.0
    else:
        normal = NormalDist()
        gamma = 0.5772156649015329
        z_first = normal.inv_cdf(1.0 - 1.0 / n_trials)
        z_second = normal.inv_cdf(1.0 - 1.0 / (n_trials * e))
        expected_max = trial_dispersion * ((1.0 - gamma) * z_first + gamma * z_second)

    test_statistic = (observed - expected_max) / sharpe_standard_error
    probability = NormalDist().cdf(test_statistic)
    return {
        "deflated_sharpe": float(probability),
        "observed_sharpe": float(observed),
        "annualized_sharpe": float(observed * sqrt(periods_per_year)),
        "expected_max_sharpe": float(expected_max),
        "n_trials": n_trials,
        "observations": int(values.size),
    }


def _column_sharpes(matrix: np.ndarray) -> np.ndarray:
    means = np.mean(matrix, axis=0)
    standard_deviations = np.std(matrix, axis=0, ddof=1)
    with np.errstate(divide="ignore", invalid="ignore"):
        scores = means / standard_deviations
    constant = standard_deviations == 0.0
    scores[constant & (means > 0.0)] = inf
    scores[constant & (means < 0.0)] = -inf
    scores[constant & (means == 0.0)] = 0.0
    return scores


def probability_of_backtest_overfitting(
    performance_matrix: pd.DataFrame | np.ndarray | None,
    *,
    n_slices: int = 6,
    expected_configurations: int | None = None,
) -> dict[str, Any]:
    """Estimate PBO with combinatorially symmetric cross-validation (CSCV).

    Rows are ordered observations and columns are independently tried strategy
    configurations.  Without at least two configurations the result is explicitly
    unavailable rather than optimistically treated as zero overfitting.
    """

    if performance_matrix is None:
        return {
            "status": NOT_ENOUGH_CONFIGS,
            "probability_backtest_overfit": None,
            "combinations": 0,
            "logits": [],
        }
    matrix = np.asarray(performance_matrix, dtype=float)
    if matrix.ndim != 2:
        raise ValueError("performance_matrix must be two-dimensional")
    if expected_configurations is not None and matrix.shape[1] != expected_configurations:
        return {
            "status": NOT_ENOUGH_CONFIGS,
            "probability_backtest_overfit": None,
            "combinations": 0,
            "logits": [],
        }
    if matrix.shape[1] < 2:
        return {
            "status": NOT_ENOUGH_CONFIGS,
            "probability_backtest_overfit": None,
            "combinations": 0,
            "logits": [],
        }
    if n_slices < 2 or n_slices % 2:
        raise ValueError("n_slices must be an even integer of at least two")
    if not np.isfinite(matrix).all():
        raise ValueError("performance_matrix must be finite; fill missing calendar months first")
    if matrix.shape[0] < n_slices:
        raise ValueError("performance_matrix has fewer valid rows than CSCV slices")

    slices = [part for part in np.array_split(np.arange(matrix.shape[0]), n_slices) if len(part)]
    half = n_slices // 2
    logits: list[float] = []
    chosen: list[int] = []
    for in_sample_slices in combinations(range(n_slices), half):
        in_set = set(in_sample_slices)
        out_sample_slices = [index for index in range(n_slices) if index not in in_set]
        in_rows = np.concatenate([slices[index] for index in in_sample_slices])
        out_rows = np.concatenate([slices[index] for index in out_sample_slices])
        in_scores = _column_sharpes(matrix[in_rows])
        out_scores = _column_sharpes(matrix[out_rows])
        selected = int(np.argmax(in_scores))
        chosen.append(selected)
        ranks = pd.Series(out_scores).rank(method="average", ascending=True).to_numpy()
        relative_rank = float(ranks[selected] / (matrix.shape[1] + 1.0))
        relative_rank = min(max(relative_rank, 1e-12), 1.0 - 1e-12)
        logits.append(log(relative_rank / (1.0 - relative_rank)))

    pbo = float(np.mean(np.asarray(logits) <= 0.0))
    return {
        "status": "OK",
        "probability_backtest_overfit": pbo,
        "combinations": len(logits),
        "logits": logits,
        "selected_config_indices": chosen,
    }


# metric path and comparison for every leaf in DEFAULT_HARD_GATES.  Procedural
# preregistration values (block length, iteration count, missing-month fill) are
# checked too; changing the method cannot silently produce a passing result.
_GATE_SPECS: dict[tuple[str, str], tuple[str, str]] = {
    ("sample", "pseudo_oos_months"): ("sample.pseudo_oos_months", "eq"),
    ("sample", "minimum_closed_trades"): ("sample.closed_trades", "ge"),
    ("sample", "minimum_long_trades"): ("sample.long_trades", "ge"),
    ("sample", "minimum_short_trades"): ("sample.short_trades", "ge"),
    ("sample", "missing_month_return_pct"): ("sample.missing_month_return_pct", "eq"),
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
    ("concentration", "best_month_positive_pnl_share_max"): (
        "concentration.best_month_positive_pnl_share",
        "le",
    ),
    ("concentration", "best_3_month_positive_pnl_share_max"): (
        "concentration.best_3_month_positive_pnl_share",
        "le",
    ),
    ("concentration", "mean_after_best_3_months_removed_pct_min"): (
        "concentration.mean_after_best_3_months_removed_pct",
        "ge",
    ),
    ("concentration", "top_5pct_trades_positive_pnl_share_max"): (
        "concentration.top_5pct_trades_positive_pnl_share",
        "le",
    ),
    ("concentration", "net_after_top_5pct_trades_removed_must_be_positive"): (
        "concentration.net_after_top_5pct_trades_removed",
        "gt0",
    ),
    ("concentration", "single_symbol_marginal_share_max"): (
        "concentration.single_symbol_marginal_share",
        "le",
    ),
    ("concentration", "top_3_symbol_marginal_share_max"): (
        "concentration.top_3_symbol_marginal_share",
        "le",
    ),
    ("concentration", "effective_symbol_count_min"): (
        "concentration.effective_symbol_count",
        "ge",
    ),
    ("concentration", "all_leave_one_symbol_out_positive"): (
        "concentration.all_leave_one_symbol_out_positive",
        "true",
    ),
    ("holdout", "C2_total_return_must_be_positive"): (
        "holdout.C2_total_return_pct",
        "gt0",
    ),
    ("holdout", "development_return_retention_min"): (
        "holdout.development_return_retention",
        "ge",
    ),
    ("holdout", "positive_holdout_symbols_min"): (
        "holdout.positive_holdout_symbols",
        "ge",
    ),
    ("holdout", "holdout_symbols_total"): ("holdout.holdout_symbols_total", "eq"),
    ("holdout", "max_drawdown_pct"): ("holdout.max_drawdown_pct", "le"),
    ("direction", "long_C2_net_must_be_positive"): ("direction.long_C2_net_pnl", "gt0"),
    ("direction", "short_C2_net_must_be_positive"): (
        "direction.short_C2_net_pnl",
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


def _comparison(value: Any, threshold: Any, operation: str) -> bool:
    if operation == "true":
        return value is True or (isinstance(value, np.bool_) and bool(value))
    try:
        numeric_value = float(value)
        numeric_threshold = float(threshold)
    except (TypeError, ValueError):
        return False
    if not np.isfinite(numeric_value):
        return False
    if operation == "eq":
        return isclose(numeric_value, numeric_threshold, rel_tol=0.0, abs_tol=1e-12)
    if operation == "ge":
        return numeric_value >= numeric_threshold
    if operation == "le":
        return numeric_value <= numeric_threshold
    if operation == "gt0":
        return numeric_value > 0.0
    raise ValueError(f"unknown gate comparison {operation!r}")


def evaluate_hard_gates(
    metrics: Mapping[str, Any],
    *,
    hard_gates: Mapping[str, Mapping[str, float | int | bool]] = DEFAULT_HARD_GATES,
) -> dict[str, Any]:
    """Evaluate every preregistered gate without silent skips or coercive defaults."""

    checks: dict[str, dict[str, Any]] = {}
    failed: list[str] = []
    missing: list[str] = []
    for group, group_gates in hard_gates.items():
        for gate, threshold in group_gates.items():
            key = (group, gate)
            if key not in _GATE_SPECS:
                raise ValueError(f"no metric specification for gate {group}.{gate}")
            metric_path, operation = _GATE_SPECS[key]
            found, value = _metric_value(metrics, metric_path)
            invalid_sign = False
            if (
                found
                and value is not None
                and metric_path
                in {
                    "drawdown.B_max_mtm_pct",
                    "drawdown.C2_H_max_mtm_pct",
                    "holdout.max_drawdown_pct",
                }
            ):
                try:
                    invalid_sign = float(value) < 0.0
                except (TypeError, ValueError):
                    invalid_sign = True
            passed = (
                found
                and value is not None
                and not invalid_sign
                and _comparison(value, threshold, operation)
            )
            reason: str | None = None
            if not found or value is None:
                pbo_status_found, pbo_status = _metric_value(
                    metrics, "multiple_testing.probability_backtest_overfit_status"
                )
                if metric_path.endswith("probability_backtest_overfit") and pbo_status_found:
                    reason = str(pbo_status)
                else:
                    reason = "MISSING_METRIC"
                missing.append(f"{group}.{gate}")
            elif not passed:
                reason = "INVALID_SIGN" if invalid_sign else "THRESHOLD_NOT_MET"
            gate_path = f"{group}.{gate}"
            checks[gate_path] = {
                "passed": bool(passed),
                "metric": metric_path,
                "value": value,
                "comparison": operation,
                "threshold": threshold,
                "reason": reason,
            }
            if not passed:
                failed.append(gate_path)

    passed_count = len(checks) - len(failed)
    return {
        "passed": not failed,
        "checks": checks,
        "failed_gates": failed,
        "missing_gates": missing,
        "passed_count": passed_count,
        "total_count": len(checks),
    }


__all__ = [
    "DEFAULT_HARD_GATES",
    "NOT_ENOUGH_CONFIGS",
    "block_bootstrap_lower_bound_pct",
    "continuous_monthly_returns",
    "deflated_sharpe_statistics",
    "direction_pnl_statistics",
    "drawdown_recovery_statistics",
    "evaluate_hard_gates",
    "holm_adjusted_pvalues",
    "monthly_return_statistics",
    "monthly_returns_from_equity",
    "probability_of_backtest_overfitting",
    "six_nonoverlap_fold_statistics",
    "symbol_concentration_statistics",
    "trade_concentration_statistics",
    "trimmed_mean_pct",
]
