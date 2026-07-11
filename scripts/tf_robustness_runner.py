"""Fail-closed robustness gate for raw timeframe candidate pools.

This runner is deliberately downstream of ``tf_exploration_runner.py``.  A
raw pool can pass a *descriptive* historical screen here, but this module never
authorizes live deployment.  The only possible verdicts are
``DESCRIPTIVE_SCREEN_PASS`` and ``RED``.  Because current TF selection used the
same historical span, this runner deliberately does not call the post-split
slice independent out-of-sample evidence.

The evaluation uses a purged chronological split, yearly stability, a
trade-sign test, a monthly block sign-flip permutation test, leave-one-symbol-
out OOS performance, symbol concentration, and OOS correlation with the
baseline timeframe.

Examples::

    .venv/bin/python scripts/tf_robustness_runner.py \
      --strategy brooks_failed_breakout \
      --candidate-tf 1h \
      --baseline-tf 15m

    .venv/bin/python scripts/tf_robustness_runner.py \
      --strategy brooks_failed_breakout \
      --candidate-tf 4h \
      --candidate-pool data/pool_19sym_20260610_4h_15m.pkl \
      --baseline-tf 15m
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import pickle
import re
import sys
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy.stats import binomtest

ROOT = Path(__file__).resolve().parents[1]

DEFAULT_POOL_MAP: dict[str, Path] = {
    "5m": ROOT / "data" / "sec53_5m_pool_v11_vm20.pkl",
    "15m": ROOT / "data" / "sec53_15m_pool_v11.pkl",
    "30m": ROOT / "data" / "sec53_30m_pool_v11.pkl",
    "1h": ROOT / "data" / "sec53_1h_pool_v11.pkl",
    "4h": ROOT / "data" / "sec53_4h_pool_v11.pkl",
}

REQUIRED_FIELDS = frozenset({"entry_ts", "exit_ts", "R", "symbol", "strategy"})
SCHEMA_VERSION = "tf-robustness-v2"


class PoolValidationError(ValueError):
    """Raised when a pool is not safe to evaluate."""


@dataclass(frozen=True)
class RobustnessThresholds:
    """Conservative defaults for a raw-pool candidate gate.

    These are research gates, not live-promotion gates.  Passing them only
    means the candidate is eligible for deeper walk-forward/adversarial work.
    """

    min_is_trades: int = 100
    min_oos_trades: int = 100
    min_baseline_oos_trades: int = 100
    min_oos_years: int = 2
    min_oos_symbols: int = 5
    min_positive_oos_year_share: float = 2 / 3
    min_is_mean_r: float = 0.0
    min_oos_mean_r: float = 0.0
    min_oos_mean_r_gain_pct: float = 0.10
    max_sign_permutation_p: float = 0.05
    min_symbol_out_mean_r: float = 0.0
    min_correlation_periods: int = 12
    max_baseline_correlation: float = 0.80
    max_top_symbol_trade_share: float = 0.30
    max_top_symbol_abs_r_share: float = 0.35


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _evaluator_metadata() -> dict[str, Any]:
    path = Path(__file__).resolve()
    return {
        "schema_version": SCHEMA_VERSION,
        "path": str(path),
        "code_sha256": _sha256(path),
    }


def _parse_utc_timestamp(value: str | datetime | pd.Timestamp) -> pd.Timestamp:
    try:
        ts = pd.Timestamp(value)
    except (TypeError, ValueError) as exc:
        raise PoolValidationError(f"invalid split timestamp: {value!r}") from exc
    if pd.isna(ts):
        raise PoolValidationError(f"invalid split timestamp: {value!r}")
    if ts.tzinfo is None:
        return ts.tz_localize("UTC")
    return ts.tz_convert("UTC")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _infer_timeframe_from_path(path: Path) -> str | None:
    match = re.search(r"(?:^|[_-])(1m|5m|15m|30m|1h|4h|1d)(?:[_-]|$)", path.stem)
    return match.group(1) if match else None


def _load_strategy_pool(
    path: Path,
    strategy: str,
    label: str,
    expected_tf: str,
) -> tuple[pd.DataFrame, dict]:
    """Load and strictly validate trades for one strategy.

    Missing fields, non-finite R values, invalid timestamps, empty symbols, or
    negative holding intervals invalidate the whole input.  Same-bar exits
    are valid in these raw pools and therefore may have identical timestamps.
    Silently
    replacing malformed values with zero would make a research gate unsafe.
    """

    path = Path(path).expanduser()
    if not path.exists():
        raise PoolValidationError(f"{label} pool does not exist: {path}")
    if not path.is_file():
        raise PoolValidationError(f"{label} pool is not a file: {path}")
    inferred_tf = _infer_timeframe_from_path(path)
    if inferred_tf is None:
        raise PoolValidationError(
            f"{label} pool filename does not declare timeframe {expected_tf!r}: {path.name}"
        )
    if inferred_tf != expected_tf:
        raise PoolValidationError(
            f"{label} pool timeframe mismatch: expected={expected_tf!r}, "
            f"filename={inferred_tf!r} ({path.name})"
        )

    try:
        with path.open("rb") as handle:
            raw = pickle.load(handle)
    except Exception as exc:
        raise PoolValidationError(f"{label} pool cannot be loaded: {exc}") from exc

    if not isinstance(raw, list) or not raw:
        raise PoolValidationError(f"{label} pool must be a non-empty list")

    non_dict = [idx for idx, row in enumerate(raw) if not isinstance(row, dict)]
    if non_dict:
        raise PoolValidationError(f"{label} pool contains non-dict rows at indexes {non_dict[:5]}")

    missing_strategy = [idx for idx, row in enumerate(raw) if "strategy" not in row]
    if missing_strategy:
        raise PoolValidationError(
            f"{label} pool rows missing strategy at indexes {missing_strategy[:5]}"
        )

    selected = [(idx, row) for idx, row in enumerate(raw) if row["strategy"] == strategy]
    if not selected:
        raise PoolValidationError(f"{label} pool has no trades for strategy {strategy!r}")

    malformed: list[tuple[int, list[str]]] = []
    for idx, row in selected:
        missing = sorted(REQUIRED_FIELDS.difference(row))
        if missing:
            malformed.append((idx, missing))
    if malformed:
        raise PoolValidationError(f"{label} strategy rows missing required fields: {malformed[:5]}")

    frame = pd.DataFrame(
        [{**row, "side": row.get("side")} for _, row in selected],
        columns=[*sorted(REQUIRED_FIELDS), "side"],
    )
    frame["entry_ts"] = pd.to_datetime(frame["entry_ts"], utc=True, errors="coerce")
    frame["exit_ts"] = pd.to_datetime(frame["exit_ts"], utc=True, errors="coerce")
    frame["R"] = pd.to_numeric(frame["R"], errors="coerce")

    bad_ts = frame["entry_ts"].isna() | frame["exit_ts"].isna()
    if bool(bad_ts.any()):
        raise PoolValidationError(
            f"{label} pool has {int(bad_ts.sum())} invalid entry/exit timestamps"
        )

    finite_r = np.isfinite(frame["R"].to_numpy(dtype=float))
    if not bool(finite_r.all()):
        raise PoolValidationError(f"{label} pool has {int((~finite_r).sum())} non-finite R values")

    invalid_symbol = ~frame["symbol"].map(
        lambda value: isinstance(value, str) and bool(value.strip())
    )
    if bool(invalid_symbol.any()):
        raise PoolValidationError(
            f"{label} pool has {int(invalid_symbol.sum())} empty/invalid symbols"
        )
    frame["symbol"] = frame["symbol"].str.strip()

    duplicate_key = ["entry_ts", "exit_ts", "symbol", "R", "side"]
    duplicates = frame.duplicated(duplicate_key, keep=False)
    if bool(duplicates.any()):
        raise PoolValidationError(
            f"{label} pool has {int(duplicates.sum())} duplicate strategy rows "
            f"for key={duplicate_key}"
        )

    bad_holding_period = frame["exit_ts"] < frame["entry_ts"]
    if bool(bad_holding_period.any()):
        raise PoolValidationError(
            f"{label} pool has {int(bad_holding_period.sum())} negative holding periods"
        )

    frame = frame.sort_values(["entry_ts", "exit_ts", "symbol"], kind="stable").reset_index(
        drop=True
    )
    resolved = path.resolve()
    provenance = {
        "path": str(resolved),
        "sha256": _sha256(resolved),
        "pool_rows": len(raw),
        "strategy_rows": len(frame),
        "declared_timeframe": inferred_tf,
        "timeframe_verified": True,
        "first_entry_ts": frame["entry_ts"].iloc[0].isoformat(),
        "last_entry_ts": frame["entry_ts"].iloc[-1].isoformat(),
    }
    return frame, provenance


def split_chronologically(
    trades: pd.DataFrame, split_date: str | datetime | pd.Timestamp
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Return purged IS, OOS, and boundary-crossing trades.

    IS requires the trade to be fully closed before the boundary.  OOS starts
    only when entry is at or after the boundary.  A trade opened before but
    closed on/after the boundary is purged from both samples.
    """

    split_ts = _parse_utc_timestamp(split_date)
    is_mask = trades["exit_ts"] < split_ts
    oos_mask = trades["entry_ts"] >= split_ts
    purged_mask = ~(is_mask | oos_mask)
    return (
        trades.loc[is_mask].copy(),
        trades.loc[oos_mask].copy(),
        trades.loc[purged_mask].copy(),
    )


def align_pair_to_common_sample(
    candidate: pd.DataFrame,
    baseline: pd.DataFrame,
    *,
    label: str,
    drop_trailing_partial_month: bool = False,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    """Restrict a candidate/baseline pair to common symbols and entry dates."""

    if candidate.empty or baseline.empty:
        raise PoolValidationError(f"{label}: candidate or baseline sample is empty")
    common_symbols = sorted(
        set(candidate["symbol"].astype(str)).intersection(baseline["symbol"].astype(str))
    )
    if not common_symbols:
        raise PoolValidationError(f"{label}: candidate and baseline have no common symbols")

    candidate_common = candidate.loc[candidate["symbol"].isin(common_symbols)]
    baseline_common = baseline.loc[baseline["symbol"].isin(common_symbols)]
    start = max(candidate_common["entry_ts"].min(), baseline_common["entry_ts"].min())
    raw_end = min(candidate_common["entry_ts"].max(), baseline_common["entry_ts"].max())
    end = raw_end
    if drop_trailing_partial_month:
        month_start = raw_end.normalize().replace(day=1)
        end = month_start - pd.Timedelta(nanoseconds=1)
    if pd.isna(start) or pd.isna(end) or start > end:
        raise PoolValidationError(f"{label}: candidate and baseline have no overlapping window")

    candidate_aligned = candidate_common.loc[
        candidate_common["entry_ts"].between(start, end, inclusive="both")
    ].copy()
    baseline_aligned = baseline_common.loc[
        baseline_common["entry_ts"].between(start, end, inclusive="both")
    ].copy()
    if candidate_aligned.empty or baseline_aligned.empty:
        raise PoolValidationError(f"{label}: no trades remain after common-sample alignment")

    provenance = {
        "method": "symbol_intersection_and_overlapping_entry_window",
        "common_symbols": common_symbols,
        "n_common_symbols": len(common_symbols),
        "entry_start": start.isoformat(),
        "entry_end": end.isoformat(),
        "raw_overlap_end": raw_end.isoformat(),
        "trailing_partial_month_excluded": drop_trailing_partial_month,
        "candidate_before_alignment": len(candidate),
        "candidate_after_alignment": len(candidate_aligned),
        "baseline_before_alignment": len(baseline),
        "baseline_after_alignment": len(baseline_aligned),
    }
    return candidate_aligned, baseline_aligned, provenance


def calculate_metrics(trades: pd.DataFrame) -> dict[str, Any]:
    """Calculate deterministic trade-level metrics without annualization claims."""

    n = len(trades)
    if n == 0:
        return {
            "n_trades": 0,
            "n_symbols": 0,
            "mean_R": None,
            "median_R": None,
            "sum_R": 0.0,
            "std_R": None,
            "trade_sharpe": None,
            "win_rate": None,
            "maxdd_R": None,
            "profit_factor": None,
            "first_entry_ts": None,
            "last_entry_ts": None,
        }

    values = trades["R"].to_numpy(dtype=float)
    mean_r = float(values.mean())
    std_r = float(values.std(ddof=1)) if n > 1 else 0.0
    trade_sharpe = float(mean_r / std_r * math.sqrt(n)) if std_r > 0 else None

    realized = trades.sort_values(["exit_ts", "entry_ts"], kind="stable")["R"].to_numpy(dtype=float)
    equity = np.concatenate(([0.0], np.cumsum(realized)))
    running_peak = np.maximum.accumulate(equity)
    maxdd = float(np.max(running_peak - equity))

    gross_profit = float(values[values > 0].sum())
    gross_loss = float(-values[values < 0].sum())
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else None

    return {
        "n_trades": n,
        "n_symbols": int(trades["symbol"].nunique()),
        "mean_R": mean_r,
        "median_R": float(np.median(values)),
        "sum_R": float(values.sum()),
        "std_R": std_r,
        "trade_sharpe": trade_sharpe,
        "win_rate": float(np.mean(values > 0)),
        "maxdd_R": maxdd,
        "profit_factor": profit_factor,
        "first_entry_ts": trades["entry_ts"].min().isoformat(),
        "last_entry_ts": trades["entry_ts"].max().isoformat(),
    }


def calculate_yearly_metrics(trades: pd.DataFrame) -> dict[str, dict[str, Any]]:
    """Return metrics keyed by entry calendar year."""

    if trades.empty:
        return {}
    years = trades["entry_ts"].dt.year
    return {
        str(int(year)): calculate_metrics(group) for year, group in trades.groupby(years, sort=True)
    }


def trade_sign_test(trades: pd.DataFrame) -> dict[str, Any]:
    """Diagnostic exact binomial test that positive trades outnumber negatives.

    This is reported but is not a gate: a valid convex strategy can have a win
    rate below 50% while retaining positive expectancy.  The required
    significance gate is the magnitude-preserving monthly sign-permutation
    test below.
    """

    values = trades["R"].to_numpy(dtype=float)
    wins = int(np.count_nonzero(values > 0))
    losses = int(np.count_nonzero(values < 0))
    nonzero = wins + losses
    if nonzero == 0:
        return {"defined": False, "wins": wins, "losses": losses, "p_value": None}
    p_value = float(binomtest(wins, nonzero, p=0.5, alternative="greater").pvalue)
    return {
        "defined": True,
        "wins": wins,
        "losses": losses,
        "zero_R": int(len(values) - nonzero),
        "p_value": p_value,
    }


def monthly_sign_flip_permutation_test(
    trades: pd.DataFrame,
    *,
    permutations: int = 20_000,
    seed: int = 20260711,
) -> dict[str, Any]:
    """One-sided monthly block sign-flip test of positive OOS expectancy.

    Monthly aggregation avoids pretending that overlapping trades are fully
    independent.  A fixed seed and finite-sample correction make the result
    reproducible and prevent a Monte Carlo p-value of exactly zero.
    """

    if permutations < 1:
        raise ValueError("permutations must be >= 1")
    monthly = (
        trades.assign(month=trades["entry_ts"].dt.strftime("%Y-%m"))
        .groupby("month", sort=True)["R"]
        .sum()
        .astype(float)
    )
    blocks = monthly.to_numpy(dtype=float)
    if len(blocks) < 2:
        return {
            "defined": False,
            "n_months": len(blocks),
            "observed_mean_monthly_R": float(blocks.mean()) if len(blocks) else None,
            "p_value": None,
            "permutations": permutations,
            "seed": seed,
        }

    observed = float(blocks.mean())
    if observed <= 0:
        return {
            "defined": True,
            "n_months": len(blocks),
            "observed_mean_monthly_R": observed,
            "p_value": 1.0,
            "permutations": permutations,
            "seed": seed,
        }

    rng = np.random.default_rng(seed)
    extreme = 0
    remaining = permutations
    chunk_size = 2_048
    while remaining:
        size = min(chunk_size, remaining)
        signs = rng.integers(0, 2, size=(size, len(blocks)), dtype=np.int8) * 2 - 1
        permuted_means = (signs * blocks).mean(axis=1)
        extreme += int(np.count_nonzero(permuted_means >= observed - 1e-12))
        remaining -= size
    p_value = float((extreme + 1) / (permutations + 1))
    return {
        "defined": True,
        "n_months": len(blocks),
        "observed_mean_monthly_R": observed,
        "p_value": p_value,
        "permutations": permutations,
        "seed": seed,
    }


def symbol_concentration(trades: pd.DataFrame) -> dict[str, Any]:
    """Measure OOS trade-count and absolute-R concentration by symbol."""

    if trades.empty:
        return {"defined": False}

    trade_counts = trades.groupby("symbol", sort=True).size().astype(float)
    trade_shares = trade_counts / float(trade_counts.sum())
    abs_r = trades.assign(abs_R=trades["R"].abs()).groupby("symbol", sort=True)["abs_R"].sum()
    abs_total = float(abs_r.sum())
    if abs_total <= 0:
        return {"defined": False, "reason": "absolute R total is zero"}
    abs_shares = abs_r / abs_total

    top_trade_symbol = str(trade_shares.idxmax())
    top_abs_symbol = str(abs_shares.idxmax())
    return {
        "defined": True,
        "n_symbols": len(trade_shares),
        "top_trade_symbol": top_trade_symbol,
        "top_symbol_trade_share": float(trade_shares.loc[top_trade_symbol]),
        "trade_count_hhi": float(np.square(trade_shares).sum()),
        "top_abs_R_symbol": top_abs_symbol,
        "top_symbol_abs_R_share": float(abs_shares.loc[top_abs_symbol]),
        "abs_R_hhi": float(np.square(abs_shares).sum()),
        "per_symbol_trade_share": {
            str(symbol): float(share) for symbol, share in trade_shares.items()
        },
        "per_symbol_abs_R_share": {
            str(symbol): float(share) for symbol, share in abs_shares.items()
        },
    }


def leave_one_symbol_out(trades: pd.DataFrame) -> dict[str, Any]:
    """Calculate OOS mean R after excluding each symbol in turn."""

    symbols = sorted(str(value) for value in trades["symbol"].unique())
    if len(symbols) < 2:
        return {
            "defined": False,
            "n_symbols": len(symbols),
            "minimum_mean_R": None,
            "per_omitted_symbol": {},
        }

    results: dict[str, dict[str, Any]] = {}
    for symbol in symbols:
        remainder = trades.loc[trades["symbol"] != symbol]
        results[symbol] = {
            "n_trades": len(remainder),
            "mean_R": float(remainder["R"].mean()),
        }
    worst_symbol, worst = min(results.items(), key=lambda item: item[1]["mean_R"])
    return {
        "defined": True,
        "n_symbols": len(symbols),
        "minimum_mean_R": float(worst["mean_R"]),
        "worst_omitted_symbol": worst_symbol,
        "per_omitted_symbol": results,
    }


def candidate_baseline_correlation(
    candidate_oos: pd.DataFrame, baseline_oos: pd.DataFrame
) -> dict[str, Any]:
    """Pearson correlation of common-calendar-month OOS summed R."""

    def monthly(frame: pd.DataFrame) -> pd.Series:
        return (
            frame.assign(month=frame["entry_ts"].dt.strftime("%Y-%m"))
            .groupby("month", sort=True)["R"]
            .sum()
            .astype(float)
        )

    aligned = pd.concat(
        [monthly(candidate_oos).rename("candidate"), monthly(baseline_oos).rename("baseline")],
        axis=1,
        join="inner",
    ).dropna()
    common_months = len(aligned)
    if common_months < 2:
        return {
            "defined": False,
            "common_months": common_months,
            "pearson_monthly_sum_R": None,
            "first_month": None,
            "last_month": None,
        }

    candidate_std = float(aligned["candidate"].std(ddof=1))
    baseline_std = float(aligned["baseline"].std(ddof=1))
    if candidate_std <= 0 or baseline_std <= 0:
        return {
            "defined": False,
            "common_months": common_months,
            "pearson_monthly_sum_R": None,
            "first_month": str(aligned.index[0]),
            "last_month": str(aligned.index[-1]),
            "reason": "constant monthly series",
        }

    correlation = float(aligned["candidate"].corr(aligned["baseline"]))
    if not math.isfinite(correlation):
        correlation = None
    return {
        "defined": correlation is not None,
        "common_months": common_months,
        "pearson_monthly_sum_R": correlation,
        "first_month": str(aligned.index[0]),
        "last_month": str(aligned.index[-1]),
    }


def _gate(
    name: str,
    passed: bool,
    *,
    value: Any,
    operator: str,
    threshold: Any,
    detail: str,
) -> dict[str, Any]:
    return {
        "name": name,
        "passed": bool(passed),
        "value": value,
        "operator": operator,
        "threshold": threshold,
        "detail": detail,
    }


def _invalid_result(
    *,
    strategy: str,
    candidate_tf: str,
    baseline_tf: str,
    candidate_pool: Path,
    baseline_pool: Path,
    split_value: Any,
    thresholds: RobustnessThresholds,
    error: str,
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "evaluator": _evaluator_metadata(),
        "generated_at": _utc_now_iso(),
        "verdict": "RED",
        "evidence_class": "INVALID_INPUT",
        "independent_oos": False,
        "strategy": strategy,
        "inputs": {
            "candidate_tf": candidate_tf,
            "candidate_pool": str(Path(candidate_pool).expanduser()),
            "baseline_tf": baseline_tf,
            "baseline_pool": str(Path(baseline_pool).expanduser()),
            "split_date": (
                split_value.isoformat()
                if isinstance(split_value, (datetime, pd.Timestamp))
                else str(split_value)
            ),
        },
        "thresholds": asdict(thresholds),
        "data_quality": {"valid": False, "errors": [error]},
        "gates": [
            _gate(
                "data_quality",
                False,
                value=error,
                operator="valid",
                threshold=True,
                detail="Malformed or missing input invalidates the entire evaluation.",
            )
        ],
        "failed_gates": ["data_quality"],
        "candidate": None,
        "baseline": None,
        "statistical_tests": None,
        "symbol_out_oos": None,
        "concentration": None,
        "baseline_correlation": None,
        "candidate_vs_baseline": None,
        "deployment_authorized": False,
    }


def evaluate_candidate(
    *,
    strategy: str,
    candidate_tf: str,
    candidate_pool: Path,
    baseline_tf: str,
    baseline_pool: Path,
    split_date: str | datetime | pd.Timestamp = "2024-01-01",
    thresholds: RobustnessThresholds | None = None,
    permutations: int = 20_000,
    seed: int = 20260711,
) -> dict[str, Any]:
    """Evaluate a raw-pool TF candidate against a baseline, fail closed."""

    thresholds = thresholds or RobustnessThresholds()
    split_value: Any = split_date
    try:
        split_ts = _parse_utc_timestamp(split_date)
        split_value = split_ts
        if permutations < 1:
            raise PoolValidationError("permutations must be >= 1")
        candidate, candidate_provenance = _load_strategy_pool(
            Path(candidate_pool), strategy, "candidate", candidate_tf
        )
        baseline, baseline_provenance = _load_strategy_pool(
            Path(baseline_pool), strategy, "baseline", baseline_tf
        )
        candidate_is_raw, candidate_oos_raw, candidate_purged = split_chronologically(
            candidate, split_ts
        )
        baseline_is_raw, baseline_oos_raw, baseline_purged = split_chronologically(
            baseline, split_ts
        )
        candidate_is, baseline_is, is_comparison = align_pair_to_common_sample(
            candidate_is_raw, baseline_is_raw, label="IS"
        )
        candidate_oos, baseline_oos, oos_comparison = align_pair_to_common_sample(
            candidate_oos_raw,
            baseline_oos_raw,
            label="OOS",
            drop_trailing_partial_month=True,
        )
    except (PoolValidationError, OSError, pickle.PickleError, ValueError) as exc:
        return _invalid_result(
            strategy=strategy,
            candidate_tf=candidate_tf,
            baseline_tf=baseline_tf,
            candidate_pool=Path(candidate_pool),
            baseline_pool=Path(baseline_pool),
            split_value=split_value,
            thresholds=thresholds,
            error=str(exc),
        )

    candidate_is_metrics = calculate_metrics(candidate_is)
    candidate_oos_metrics = calculate_metrics(candidate_oos)
    baseline_is_metrics = calculate_metrics(baseline_is)
    baseline_oos_metrics = calculate_metrics(baseline_oos)
    candidate_oos_yearly = calculate_yearly_metrics(candidate_oos)
    baseline_oos_yearly = calculate_yearly_metrics(baseline_oos)

    sign_test = trade_sign_test(candidate_oos)
    permutation_test = monthly_sign_flip_permutation_test(
        candidate_oos, permutations=permutations, seed=seed
    )
    concentration = symbol_concentration(candidate_oos)
    symbol_out = leave_one_symbol_out(candidate_oos)
    correlation = candidate_baseline_correlation(candidate_oos, baseline_oos)

    positive_years = sum(
        metrics["mean_R"] is not None and metrics["mean_R"] > 0
        for metrics in candidate_oos_yearly.values()
    )
    year_count = len(candidate_oos_yearly)
    positive_year_share = positive_years / year_count if year_count else 0.0
    candidate_oos_mean = candidate_oos_metrics["mean_R"]
    baseline_oos_mean = baseline_oos_metrics["mean_R"]
    oos_mean_r_gain_pct = (
        (candidate_oos_mean - baseline_oos_mean) / baseline_oos_mean
        if candidate_oos_mean is not None
        and baseline_oos_mean is not None
        and baseline_oos_mean > 0
        else None
    )

    gates = [
        _gate(
            "candidate_is_trade_count",
            candidate_is_metrics["n_trades"] >= thresholds.min_is_trades,
            value=candidate_is_metrics["n_trades"],
            operator=">=",
            threshold=thresholds.min_is_trades,
            detail="Candidate must have enough fully closed pre-split trades.",
        ),
        _gate(
            "candidate_oos_trade_count",
            candidate_oos_metrics["n_trades"] >= thresholds.min_oos_trades,
            value=candidate_oos_metrics["n_trades"],
            operator=">=",
            threshold=thresholds.min_oos_trades,
            detail="Candidate must have enough post-split entries.",
        ),
        _gate(
            "baseline_oos_trade_count",
            baseline_oos_metrics["n_trades"] >= thresholds.min_baseline_oos_trades,
            value=baseline_oos_metrics["n_trades"],
            operator=">=",
            threshold=thresholds.min_baseline_oos_trades,
            detail="Baseline must be sufficiently populated for comparison.",
        ),
        _gate(
            "candidate_oos_year_count",
            year_count >= thresholds.min_oos_years,
            value=year_count,
            operator=">=",
            threshold=thresholds.min_oos_years,
            detail="OOS evidence must span multiple entry calendar years.",
        ),
        _gate(
            "candidate_oos_symbol_count",
            candidate_oos_metrics["n_symbols"] >= thresholds.min_oos_symbols,
            value=candidate_oos_metrics["n_symbols"],
            operator=">=",
            threshold=thresholds.min_oos_symbols,
            detail="OOS evidence must cover multiple symbols.",
        ),
        _gate(
            "candidate_is_expectancy",
            candidate_is_metrics["mean_R"] is not None
            and candidate_is_metrics["mean_R"] > thresholds.min_is_mean_r,
            value=candidate_is_metrics["mean_R"],
            operator=">",
            threshold=thresholds.min_is_mean_r,
            detail="IS mean R must be positive; equality is not evidence of edge.",
        ),
        _gate(
            "candidate_oos_expectancy",
            candidate_oos_metrics["mean_R"] is not None
            and candidate_oos_metrics["mean_R"] > thresholds.min_oos_mean_r,
            value=candidate_oos_metrics["mean_R"],
            operator=">",
            threshold=thresholds.min_oos_mean_r,
            detail="OOS mean R must remain positive.",
        ),
        _gate(
            "candidate_vs_baseline_oos_mean_R_gain",
            oos_mean_r_gain_pct is not None
            and oos_mean_r_gain_pct >= thresholds.min_oos_mean_r_gain_pct,
            value=oos_mean_r_gain_pct,
            operator=">=",
            threshold=thresholds.min_oos_mean_r_gain_pct,
            detail=(
                "On the same OOS symbols and dates, candidate mean R must beat the "
                "positive baseline by the configured margin."
            ),
        ),
        _gate(
            "positive_oos_year_share",
            positive_year_share >= thresholds.min_positive_oos_year_share,
            value=positive_year_share,
            operator=">=",
            threshold=thresholds.min_positive_oos_year_share,
            detail=f"{positive_years}/{year_count} OOS years have positive mean R.",
        ),
        _gate(
            "monthly_block_sign_permutation_p",
            permutation_test["defined"]
            and permutation_test["p_value"] <= thresholds.max_sign_permutation_p,
            value=permutation_test["p_value"],
            operator="<=",
            threshold=thresholds.max_sign_permutation_p,
            detail="One-sided monthly block sign-flip test of OOS summed R.",
        ),
        _gate(
            "symbol_out_oos_minimum",
            symbol_out["defined"]
            and symbol_out["minimum_mean_R"] > thresholds.min_symbol_out_mean_r,
            value=symbol_out["minimum_mean_R"],
            operator=">",
            threshold=thresholds.min_symbol_out_mean_r,
            detail="Every leave-one-symbol-out OOS portfolio must retain positive mean R.",
        ),
        _gate(
            "correlation_period_count",
            correlation["common_months"] >= thresholds.min_correlation_periods,
            value=correlation["common_months"],
            operator=">=",
            threshold=thresholds.min_correlation_periods,
            detail="Correlation needs enough common OOS calendar months.",
        ),
        _gate(
            "candidate_baseline_correlation",
            correlation["defined"]
            and correlation["pearson_monthly_sum_R"] <= thresholds.max_baseline_correlation,
            value=correlation["pearson_monthly_sum_R"],
            operator="<=",
            threshold=thresholds.max_baseline_correlation,
            detail="High positive monthly correlation weakens diversification value.",
        ),
        _gate(
            "top_symbol_trade_share",
            concentration.get("defined", False)
            and concentration["top_symbol_trade_share"] <= thresholds.max_top_symbol_trade_share,
            value=concentration.get("top_symbol_trade_share"),
            operator="<=",
            threshold=thresholds.max_top_symbol_trade_share,
            detail="No single symbol may dominate OOS trade count.",
        ),
        _gate(
            "top_symbol_abs_R_share",
            concentration.get("defined", False)
            and concentration["top_symbol_abs_R_share"] <= thresholds.max_top_symbol_abs_r_share,
            value=concentration.get("top_symbol_abs_R_share"),
            operator="<=",
            threshold=thresholds.max_top_symbol_abs_r_share,
            detail="No single symbol may dominate absolute OOS R contribution.",
        ),
    ]
    failed_gates = [gate["name"] for gate in gates if not gate["passed"]]
    verdict = "DESCRIPTIVE_SCREEN_PASS" if not failed_gates else "RED"

    return {
        "schema_version": SCHEMA_VERSION,
        "evaluator": _evaluator_metadata(),
        "generated_at": _utc_now_iso(),
        "verdict": verdict,
        "evidence_class": "DESCRIPTIVE_REUSED_HISTORY",
        "independent_oos": False,
        "strategy": strategy,
        "inputs": {
            "candidate_tf": candidate_tf,
            "candidate_pool": candidate_provenance,
            "baseline_tf": baseline_tf,
            "baseline_pool": baseline_provenance,
            "split_date": split_ts.isoformat(),
        },
        "thresholds": asdict(thresholds),
        "data_quality": {
            "valid": True,
            "errors": [],
            "candidate_purged_boundary_trades": len(candidate_purged),
            "baseline_purged_boundary_trades": len(baseline_purged),
            "is_comparison_sample": is_comparison,
            "oos_comparison_sample": oos_comparison,
        },
        "candidate": {
            "tf": candidate_tf,
            "all": calculate_metrics(candidate),
            "is": candidate_is_metrics,
            "oos": candidate_oos_metrics,
            "per_year_all": calculate_yearly_metrics(candidate),
            "per_year_oos": candidate_oos_yearly,
            "positive_oos_years": positive_years,
            "positive_oos_year_share": positive_year_share,
        },
        "baseline": {
            "tf": baseline_tf,
            "all": calculate_metrics(baseline),
            "is": baseline_is_metrics,
            "oos": baseline_oos_metrics,
            "per_year_all": calculate_yearly_metrics(baseline),
            "per_year_oos": baseline_oos_yearly,
        },
        "statistical_tests": {
            "trade_sign_test_diagnostic": sign_test,
            "monthly_block_sign_permutation": permutation_test,
        },
        "symbol_out_oos": symbol_out,
        "concentration": concentration,
        "baseline_correlation": correlation,
        "candidate_vs_baseline": {
            "oos_mean_R_gain_pct": oos_mean_r_gain_pct,
        },
        "gates": gates,
        "failed_gates": failed_gates,
        "deployment_authorized": False,
    }


def _format_value(value: Any) -> str:
    if value is None:
        return "N/A"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, float):
        if abs(value) < 0.001 and value != 0:
            return f"{value:.3e}"
        return f"{value:.4f}"
    return str(value)


def render_markdown(result: dict[str, Any]) -> str:
    """Render a compact, auditable Markdown companion to the JSON artifact."""

    inputs = result["inputs"]
    lines = [
        f"# TF Robustness — `{result['strategy']}`",
        "",
        f"- Verdict: **{result['verdict']}**",
        f"- Candidate: `{inputs['candidate_tf']}`",
        f"- Baseline: `{inputs['baseline_tf']}`",
        f"- Split: `{inputs['split_date']}` (purged chronological descriptive split)",
        "- Independent OOS: **NO** — upstream TF selection reused this history.",
        "- Deployment authorized: **NO** — this gate can only qualify further research.",
        "",
    ]

    if not result["data_quality"]["valid"]:
        lines.extend(["## Data quality", ""])
        lines.extend(f"- RED: {error}" for error in result["data_quality"]["errors"])
        lines.append("")
    else:
        candidate = result["candidate"]
        baseline = result["baseline"]
        comparison = result["data_quality"]["oos_comparison_sample"]
        lines.extend(
            [
                "## Fair post-split comparison sample",
                "",
                f"- Common symbols: {comparison['n_common_symbols']} "
                f"(`{', '.join(comparison['common_symbols'])}`)",
                f"- Entry window: `{comparison['entry_start']}` → `{comparison['entry_end']}`",
                "- Candidate and baseline metrics below use this same universe/window.",
                "",
                "## Chronological evidence",
                "",
                "| Sample | Trades | Symbols | Mean R | Sum R | MaxDD R | Win rate |",
                "|---|---:|---:|---:|---:|---:|---:|",
            ]
        )
        for label, metrics in (
            (f"Candidate {candidate['tf']} IS", candidate["is"]),
            (f"Candidate {candidate['tf']} post-split", candidate["oos"]),
            (f"Baseline {baseline['tf']} IS", baseline["is"]),
            (f"Baseline {baseline['tf']} post-split", baseline["oos"]),
        ):
            win_rate = metrics["win_rate"]
            lines.append(
                f"| {label} | {metrics['n_trades']} | {metrics['n_symbols']} | "
                f"{_format_value(metrics['mean_R'])} | {_format_value(metrics['sum_R'])} | "
                f"{_format_value(metrics['maxdd_R'])} | "
                f"{_format_value(win_rate * 100 if win_rate is not None else None)}% |"
            )
        lines.extend(["", "## Candidate post-split by year", ""])
        lines.extend(
            [
                "| Year | Trades | Symbols | Mean R | Sum R | Win rate |",
                "|---|---:|---:|---:|---:|---:|",
            ]
        )
        for year, metrics in candidate["per_year_oos"].items():
            win_rate = metrics["win_rate"]
            lines.append(
                f"| {year} | {metrics['n_trades']} | {metrics['n_symbols']} | "
                f"{_format_value(metrics['mean_R'])} | {_format_value(metrics['sum_R'])} | "
                f"{_format_value(win_rate * 100 if win_rate is not None else None)}% |"
            )
        lines.append("")

    lines.extend(
        [
            "## Gates",
            "",
            "| Gate | Pass | Value | Rule | Detail |",
            "|---|:---:|---:|---:|---|",
        ]
    )
    for gate in result["gates"]:
        marker = "PASS" if gate["passed"] else "RED"
        lines.append(
            f"| `{gate['name']}` | {marker} | {_format_value(gate['value'])} | "
            f"{gate['operator']} {_format_value(gate['threshold'])} | {gate['detail']} |"
        )
    lines.extend(
        [
            "",
            "## Decision",
            "",
            f"**{result['verdict']}**",
            "",
        ]
    )
    if result["failed_gates"]:
        lines.append("Failed gates: " + ", ".join(f"`{name}`" for name in result["failed_gates"]))
        lines.append("")
    lines.append(
        "A DESCRIPTIVE_SCREEN_PASS is not independent OOS evidence or a live/paper deployment "
        "approval; pre-registration with a future cutoff, walk-forward, execution parity, "
        "adversarial review, risk endorsement, and paper evidence remain separate gates."
    )
    lines.append("")
    return "\n".join(lines)


def write_reports(
    result: dict[str, Any], json_path: Path, markdown_path: Path
) -> tuple[Path, Path]:
    """Write both required report formats, rejecting non-standard JSON floats."""

    json_path = Path(json_path)
    markdown_path = Path(markdown_path)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n"
    json_path.write_text(payload, encoding="utf-8")
    markdown_path.write_text(render_markdown(result), encoding="utf-8")
    return json_path, markdown_path


def _safe_stem(strategy: str, candidate_tf: str, baseline_tf: str) -> str:
    raw = f"{strategy}-{candidate_tf}-vs-{baseline_tf}"
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", raw).strip("-_")


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fail-closed raw-pool TF robustness candidate gate"
    )
    parser.add_argument("--strategy", required=True)
    parser.add_argument("--candidate-tf", required=True)
    parser.add_argument("--baseline-tf", default="15m")
    parser.add_argument("--candidate-pool", type=Path)
    parser.add_argument("--baseline-pool", type=Path)
    parser.add_argument("--split-date", default="2024-01-01")
    parser.add_argument("--permutations", type=int, default=20_000)
    parser.add_argument("--seed", type=int, default=20260711)
    parser.add_argument("--json-output", type=Path)
    parser.add_argument("--markdown-output", type=Path)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    candidate_pool = args.candidate_pool or DEFAULT_POOL_MAP.get(args.candidate_tf)
    baseline_pool = args.baseline_pool or DEFAULT_POOL_MAP.get(args.baseline_tf)
    if candidate_pool is None:
        raise SystemExit(
            f"No default pool for candidate TF {args.candidate_tf!r}; pass --candidate-pool"
        )
    if baseline_pool is None:
        raise SystemExit(
            f"No default pool for baseline TF {args.baseline_tf!r}; pass --baseline-pool"
        )

    result = evaluate_candidate(
        strategy=args.strategy,
        candidate_tf=args.candidate_tf,
        candidate_pool=candidate_pool,
        baseline_tf=args.baseline_tf,
        baseline_pool=baseline_pool,
        split_date=args.split_date,
        permutations=args.permutations,
        seed=args.seed,
    )

    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ")
    stem = _safe_stem(args.strategy, args.candidate_tf, args.baseline_tf)
    output_dir = ROOT / "reports" / "tf_robustness"
    candidate_input = result["inputs"]["candidate_pool"]
    candidate_hash = (
        candidate_input.get("sha256", "invalid")[:8]
        if isinstance(candidate_input, dict)
        else "invalid"
    )
    code_hash = result["evaluator"]["code_sha256"][:8]
    artifact_stem = f"{stem}-{run_id}-{candidate_hash}-{code_hash}"
    json_path = args.json_output or output_dir / f"{artifact_stem}.json"
    markdown_path = args.markdown_output or output_dir / f"{artifact_stem}.md"
    write_reports(result, json_path, markdown_path)

    print(f"[VERDICT] {result['verdict']}")
    print(f"[JSON] {json_path}")
    print(f"[MARKDOWN] {markdown_path}")
    if result["failed_gates"]:
        print(f"[FAILED_GATES] {','.join(result['failed_gates'])}")
    return 0 if result["verdict"] == "DESCRIPTIVE_SCREEN_PASS" else 2


if __name__ == "__main__":
    sys.exit(main())
