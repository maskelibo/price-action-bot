"""Fail-closed statistical validation for the preregistered V18 study.

This module is deliberately independent of the V18 replay engine and never
opens a market/funding snapshot.  It validates exact monthly return matrices,
reconstructs the nine audit-grade V16/V17 trials from byte-bound artifacts,
and implements the seed-18 local/cumulative tests frozen in
``configs/crypto_15m_v18_challenger_prereg.yaml``.

Percentage returns are percentage points: ``10.0`` means ten percent.  The
thirteen-trial family is an auditable floor, not a claim that only thirteen
historical configurations were ever inspected.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import math
import stat
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from price_action.lab.crypto_15m_pairs_validation import program_wide_multiple_testing
from price_action.lab.crypto_15m_validation import (
    block_bootstrap_lower_bound_pct,
    deflated_sharpe_statistics,
    holm_adjusted_pvalues,
    probability_of_backtest_overfitting,
    trimmed_mean_pct,
)

EXPECTED_H_MONTHS = 36
EXPECTED_LOCAL_CANDIDATES = 4
EXPECTED_LEGACY_CANDIDATES = 9
EXPECTED_CUMULATIVE_CANDIDATES = 13
BLOCK_MONTHS = 3
SIGN_FLIP_BLOCKS = 12
VALIDATION_ITERATIONS = 20_000
VALIDATION_SEED = 18
LEGACY_CROSSCHECK_SEED = 17
TRIM_FRACTION = 0.10
BOOTSTRAP_LOWER_QUANTILE = 0.10
PBO_SLICES = 6

LEGACY_CANDIDATE_IDS = (
    "T1_RESIDUAL_TREND_1W",
    "T2_RESIDUAL_TREND_2W",
    "T4_RESIDUAL_TREND_4W",
    "M1_FUNDING_RESIDUAL_REVERSION_4H_Z2",
    "M2_FUNDING_RESIDUAL_REVERSION_8H_Z2",
    "M3_FUNDING_RESIDUAL_REVERSION_4H_Z2P5",
    "DP1_EG_90D_Z2P5",
    "DP2_EG_180D_Z2P5",
    "DP3_EG_180D_Z3_STRICT",
)
LOCAL_CANDIDATE_IDS = (
    "C1_VSA_ONLY",
    "C2_GRIMES_ONLY",
    "C3_DUAL_HTF50",
    "C4_VSA_HTF50",
)
CUMULATIVE_CANDIDATE_IDS = (*LEGACY_CANDIDATE_IDS, *LOCAL_CANDIDATE_IDS)
FROZEN_H_MONTHS = pd.period_range("2023-06", "2026-05", freq="M")

_SCENARIO_ORDER = ("B", "C2", "H")
_V16_CANDIDATES = LEGACY_CANDIDATE_IDS[:6]
_V17_CANDIDATES = LEGACY_CANDIDATE_IDS[6:]


class V18ValidationContractError(ValueError):
    """Input evidence cannot satisfy the frozen V18 validation contract."""


@dataclass(frozen=True, slots=True)
class LegacyTrialInputs:
    """Verified nine-trial H matrix and its seed-17 reconstruction evidence."""

    monthly_returns: pd.DataFrame
    artifact_provenance: Mapping[str, Mapping[str, Any]]
    source_provenance: Mapping[str, Mapping[str, Any]]
    seed17_crosscheck: Mapping[str, Any]


def _mapping(value: Any, *, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise V18ValidationContractError(f"{name} must be a mapping")
    return value


def _sequence(value: Any, *, name: str) -> Sequence[Any]:
    if isinstance(value, str | bytes) or not isinstance(value, Sequence):
        raise V18ValidationContractError(f"{name} must be a sequence")
    return value


def _integer(value: Any, *, name: str, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int | np.integer):
        raise V18ValidationContractError(f"{name} must be an integer")
    parsed = int(value)
    if parsed < minimum:
        raise V18ValidationContractError(f"{name} must be >= {minimum}")
    return parsed


def _finite(value: Any, *, name: str) -> float:
    if isinstance(value, bool | np.bool_):
        raise V18ValidationContractError(f"{name} must be a finite number")
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise V18ValidationContractError(f"{name} must be a finite number") from exc
    if not math.isfinite(parsed):
        raise V18ValidationContractError(f"{name} must be a finite number")
    return parsed


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _strict_json_constant(value: str) -> None:
    raise V18ValidationContractError(f"non-finite JSON constant is forbidden: {value}")


def _strict_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise V18ValidationContractError(f"duplicate JSON key is forbidden: {key!r}")
        result[key] = value
    return result


def _strict_json_loads(value: bytes, *, name: str) -> dict[str, Any]:
    try:
        decoded = value.decode("utf-8")
        payload = json.loads(
            decoded,
            parse_constant=_strict_json_constant,
            object_pairs_hook=_strict_json_object,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise V18ValidationContractError(f"{name} must be strict UTF-8 JSON") from exc
    if not isinstance(payload, dict):
        raise V18ValidationContractError(f"{name} must be a top-level JSON object")
    return payload


def _safe_bound_path(repo_root: Path, relative: Any, *, name: str) -> Path:
    if not isinstance(relative, str) or not relative or Path(relative).is_absolute():
        raise V18ValidationContractError(f"{name}.path must be a non-empty relative path")
    root = repo_root.resolve(strict=True)
    lexical = root / relative
    try:
        mode = lexical.lstat().st_mode
    except OSError as exc:
        raise V18ValidationContractError(f"{name} is missing: {relative}") from exc
    if stat.S_ISLNK(mode) or not stat.S_ISREG(mode):
        raise V18ValidationContractError(f"{name} must be a non-symlink regular file")
    resolved = lexical.resolve(strict=True)
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise V18ValidationContractError(f"{name} escapes repo_root") from exc
    return resolved


def _verified_bytes(
    spec: Mapping[str, Any], *, repo_root: Path, name: str
) -> tuple[Path, bytes, dict[str, Any]]:
    path = _safe_bound_path(repo_root, spec.get("path"), name=name)
    encoded = path.read_bytes()
    expected_bytes = _integer(spec.get("bytes"), name=f"{name}.bytes", minimum=1)
    expected_sha = str(spec.get("sha256", "")).lower()
    if len(expected_sha) != 64 or any(char not in "0123456789abcdef" for char in expected_sha):
        raise V18ValidationContractError(f"{name}.sha256 is not a lowercase SHA-256")
    actual_sha = _sha256_bytes(encoded)
    if len(encoded) != expected_bytes or actual_sha != expected_sha:
        raise V18ValidationContractError(f"{name} byte identity differs from preregistration")
    provenance = {
        "path": str(path),
        "bytes": len(encoded),
        "sha256": actual_sha,
    }
    return path, encoded, provenance


def _artifact_payload(
    spec: Mapping[str, Any],
    *,
    repo_root: Path,
    name: str,
    gzip_encoded: bool,
    parse_json: bool = True,
) -> tuple[dict[str, Any] | None, bytes, dict[str, Any]]:
    _path, encoded, provenance = _verified_bytes(spec, repo_root=repo_root, name=name)
    if gzip_encoded:
        try:
            decoded = gzip.decompress(encoded)
        except (gzip.BadGzipFile, EOFError, OSError) as exc:
            raise V18ValidationContractError(f"{name} is not valid gzip") from exc
        expected_decoded_bytes = _integer(
            spec.get("decoded_bytes"), name=f"{name}.decoded_bytes", minimum=1
        )
        expected_decoded_sha = str(spec.get("decoded_json_sha256", "")).lower()
        if len(decoded) != expected_decoded_bytes or _sha256_bytes(decoded) != expected_decoded_sha:
            raise V18ValidationContractError(
                f"{name} decoded identity differs from preregistration"
            )
        provenance = {
            **provenance,
            "compression": "gzip",
            "decoded_bytes": len(decoded),
            "decoded_json_sha256": _sha256_bytes(decoded),
        }
    else:
        decoded = encoded
        provenance = {
            **provenance,
            "compression": "none",
            "decoded_bytes": len(decoded),
            "decoded_json_sha256": _sha256_bytes(decoded),
        }
    payload = _strict_json_loads(decoded, name=name) if parse_json else None
    return payload, decoded, provenance


def _month_index(index: pd.Index, *, name: str) -> pd.PeriodIndex:
    if isinstance(index, pd.RangeIndex):
        raise V18ValidationContractError(f"{name} must carry the frozen dated month index")
    try:
        if isinstance(index, pd.PeriodIndex):
            months = index.asfreq("M")
        else:
            timestamps = pd.DatetimeIndex(pd.to_datetime(index, utc=True)).tz_convert(None)
            months = timestamps.to_period("M")
    except (TypeError, ValueError) as exc:
        raise V18ValidationContractError(f"{name} index must contain monthly timestamps") from exc
    if not months.is_unique or not months.is_monotonic_increasing:
        raise V18ValidationContractError(f"{name} month index must be unique and chronological")
    return months


def exact_h_monthly_returns(values: Any, *, name: str = "H_monthly_returns") -> pd.Series:
    """Return exact finite 2023-06..2026-05 percentage-point returns."""

    if isinstance(values, pd.DataFrame):
        if values.shape[1] != 1:
            raise V18ValidationContractError(f"{name} DataFrame must have one column")
        values = values.iloc[:, 0]
    if isinstance(values, pd.Series):
        months = _month_index(values.index, name=name)
        source = values.to_numpy()
    elif isinstance(values, Mapping):
        expected_keys = tuple(str(month) for month in FROZEN_H_MONTHS)
        if tuple(values) != expected_keys:
            raise V18ValidationContractError(
                f"{name} must contain exact chronological months 2023-06..2026-05"
            )
        months = FROZEN_H_MONTHS
        source = [values[key] for key in expected_keys]
    else:
        raise V18ValidationContractError(f"{name} must be a dated Series or month mapping")
    if not months.equals(FROZEN_H_MONTHS):
        raise V18ValidationContractError(f"{name} must cover exactly 2023-06 through 2026-05")
    if len(source) != EXPECTED_H_MONTHS:
        raise V18ValidationContractError(f"{name} must contain exactly 36 values")
    parsed = np.asarray(
        [_finite(item, name=f"{name}[{index}]") for index, item in enumerate(source)]
    )
    return pd.Series(parsed, index=FROZEN_H_MONTHS, dtype=float, name=name)


def _exact_matrix(
    candidates: pd.DataFrame | Mapping[str, Any],
    *,
    candidate_ids: Sequence[str],
    name: str,
) -> pd.DataFrame:
    expected_ids = tuple(candidate_ids)
    if isinstance(candidates, pd.DataFrame):
        frame = candidates.copy()
        if tuple(map(str, frame.columns)) != expected_ids:
            raise V18ValidationContractError(f"{name} candidate IDs/order differ from contract")
        months = _month_index(frame.index, name=name)
        if not months.equals(FROZEN_H_MONTHS):
            raise V18ValidationContractError(f"{name} must cover exactly 2023-06 through 2026-05")
        frame.index = months
    elif isinstance(candidates, Mapping):
        if tuple(candidates) != expected_ids:
            raise V18ValidationContractError(f"{name} candidate IDs/order differ from contract")
        frame = pd.DataFrame(
            {
                candidate: exact_h_monthly_returns(
                    candidates[candidate], name=f"{name}[{candidate}]"
                )
                for candidate in expected_ids
            },
            index=FROZEN_H_MONTHS,
        )
    else:
        raise V18ValidationContractError(f"{name} must be a DataFrame or ordered mapping")
    expected_shape = (EXPECTED_H_MONTHS, len(expected_ids))
    if frame.shape != expected_shape:
        raise V18ValidationContractError(f"{name} must have exact shape {expected_shape}")
    numeric = frame.apply(pd.to_numeric, errors="coerce")
    contains_boolean = any(
        isinstance(value, bool | np.bool_) for value in frame.to_numpy(dtype=object).flat
    )
    if (
        contains_boolean
        or numeric.isna().any().any()
        or not np.isfinite(numeric.to_numpy(dtype=float)).all()
    ):
        raise V18ValidationContractError(f"{name} must contain only finite numeric values")
    numeric.columns = list(expected_ids)
    numeric.index = FROZEN_H_MONTHS
    return numeric.astype(float)


def exact_local_h_matrix(candidates: pd.DataFrame | Mapping[str, Any]) -> pd.DataFrame:
    """Return the exact finite 36x4 local V18 H matrix in C1..C4 order."""

    return _exact_matrix(candidates, candidate_ids=LOCAL_CANDIDATE_IDS, name="local H matrix")


def exact_legacy_h_matrix(candidates: pd.DataFrame | Mapping[str, Any]) -> pd.DataFrame:
    """Return the exact finite 36x9 reconstructible V16/V17 H matrix."""

    return _exact_matrix(candidates, candidate_ids=LEGACY_CANDIDATE_IDS, name="legacy H matrix")


def exact_cumulative_h_matrix(candidates: pd.DataFrame | Mapping[str, Any]) -> pd.DataFrame:
    """Return the exact finite 36x13 governed-floor matrix."""

    return _exact_matrix(
        candidates,
        candidate_ids=CUMULATIVE_CANDIDATE_IDS,
        name="cumulative H matrix",
    )


def v18_block_bootstrap_lower_bound_pct(monthly_returns: Any) -> float:
    """Locked 20,000-draw seed-18 moving three-month block lower bound."""

    returns = exact_h_monthly_returns(monthly_returns)
    return block_bootstrap_lower_bound_pct(
        returns.to_numpy(dtype=float),
        block_months=BLOCK_MONTHS,
        iterations=VALIDATION_ITERATIONS,
        confidence=1.0 - BOOTSTRAP_LOWER_QUANTILE,
        seed=VALIDATION_SEED,
        trim_fraction=TRIM_FRACTION,
    )


def v18_candidate_sign_flip_test(monthly_returns: Any) -> dict[str, float | int | str]:
    """Locked one-sided seed-18 test on 12 non-overlapping three-month blocks."""

    returns = exact_h_monthly_returns(monthly_returns).to_numpy(dtype=float)
    blocks = returns.reshape(SIGN_FLIP_BLOCKS, BLOCK_MONTHS)
    observed = trimmed_mean_pct(returns, proportion_to_cut=TRIM_FRACTION)
    rng = np.random.default_rng(VALIDATION_SEED)
    signs = rng.integers(
        0,
        2,
        size=(VALIDATION_ITERATIONS, SIGN_FLIP_BLOCKS),
        dtype=np.int8,
    )
    signs = signs * 2 - 1
    null_samples = (blocks[np.newaxis, :, :] * signs[:, :, np.newaxis]).reshape(
        VALIDATION_ITERATIONS, EXPECTED_H_MONTHS
    )
    null_samples.sort(axis=1)
    cut = int(np.floor(EXPECTED_H_MONTHS * TRIM_FRACTION))
    kept = null_samples[:, cut : EXPECTED_H_MONTHS - cut]
    null_statistics = kept.mean(axis=1)
    exceedances = int(np.count_nonzero(null_statistics >= observed))
    return {
        "status": "OK",
        "observed_trimmed_mean_monthly_pct": float(observed),
        "candidate_sign_flip_pvalue": float((1 + exceedances) / (VALIDATION_ITERATIONS + 1)),
        "null_exceedances_gte_observed": exceedances,
        "iterations": VALIDATION_ITERATIONS,
        "seed": VALIDATION_SEED,
        "blocks": SIGN_FLIP_BLOCKS,
        "block_months": BLOCK_MONTHS,
    }


def _periodic_sharpe(values: pd.Series | np.ndarray) -> float:
    array = np.asarray(values, dtype=float)
    if array.shape != (EXPECTED_H_MONTHS,) or not np.isfinite(array).all():
        raise V18ValidationContractError("periodic Sharpe requires exact finite 36 months")
    standard_deviation = float(np.std(array, ddof=1))
    mean = float(np.mean(array))
    if standard_deviation == 0.0:
        if mean > 0.0:
            return math.inf
        if mean < 0.0:
            return -math.inf
        return 0.0
    return mean / standard_deviation


def _exact_equal_number(actual: Any, expected: Any, *, name: str) -> None:
    actual_number = _finite(actual, name=f"{name}.actual")
    expected_number = _finite(expected, name=f"{name}.expected")
    if actual_number != expected_number:
        raise V18ValidationContractError(f"{name} differs from exact seed-17 reconstruction")


def _validate_raw_header(
    payload: Mapping[str, Any],
    *,
    name: str,
    schema: str,
    candidates: Sequence[str],
) -> None:
    if payload.get("schema_version") != schema:
        raise V18ValidationContractError(f"{name} schema_version differs from preregistration")
    if payload.get("evidence_eligible") is not True:
        raise V18ValidationContractError(f"{name} is not evidence eligible")
    if payload.get("evidence_ineligible_reasons") != []:
        raise V18ValidationContractError(f"{name} has evidence-ineligible reasons")
    if tuple(_sequence(payload.get("candidate_ids"), name=f"{name}.candidate_ids")) != tuple(
        candidates
    ):
        raise V18ValidationContractError(f"{name} candidate IDs/order differ from contract")
    if _integer(payload.get("candidate_count"), name=f"{name}.candidate_count") != len(candidates):
        raise V18ValidationContractError(f"{name} candidate count differs from contract")
    if tuple(_sequence(payload.get("scenario_order"), name=f"{name}.scenario_order")) != (
        _SCENARIO_ORDER
    ):
        raise V18ValidationContractError(f"{name} scenario order differs from contract")


def _extract_legacy_series(payload: Mapping[str, Any], *, candidate: str, name: str) -> pd.Series:
    results = _mapping(payload.get("results"), name=f"{name}.results")
    candidate_result = _mapping(results.get(candidate), name=f"{name}.results.{candidate}")
    if set(candidate_result) != set(_SCENARIO_ORDER) or len(candidate_result) != len(
        _SCENARIO_ORDER
    ):
        raise V18ValidationContractError(f"{name}.{candidate} scenario IDs/order differ")
    h = _mapping(candidate_result.get("H"), name=f"{name}.{candidate}.H")
    windows = _mapping(h.get("windows"), name=f"{name}.{candidate}.H.windows")
    pseudo = _mapping(windows.get("pseudo_oos"), name=f"{name}.{candidate}.H.windows.pseudo_oos")
    if pseudo.get("monthly_returns_unit") != "percentage_points":
        raise V18ValidationContractError(f"{name}.{candidate} monthly return unit differs")
    return exact_h_monthly_returns(
        pseudo.get("monthly_returns_pct"),
        name=f"{name}.{candidate}.H.pseudo_oos.monthly_returns_pct",
    )


def _legacy_seed17_crosscheck(
    matrix: pd.DataFrame,
    report: Mapping[str, Any],
) -> dict[str, Any]:
    reconstructed = program_wide_multiple_testing(matrix)
    if reconstructed.get("seed") != LEGACY_CROSSCHECK_SEED:
        raise V18ValidationContractError("bound V17 reconstruction did not use seed 17")
    multiple = _mapping(report.get("multiple_testing"), name="v17_report.multiple_testing")
    reported = _mapping(
        multiple.get("program_wide_v16_plus_v17_exact_36x9"),
        name="v17_report.program_wide_v16_plus_v17_exact_36x9",
    )
    reconstructed_results = _mapping(
        reconstructed.get("candidate_results"), name="reconstructed.candidate_results"
    )
    reported_results = _mapping(
        reported.get("candidate_results"), name="v17_report.candidate_results"
    )
    if tuple(reconstructed_results) != LEGACY_CANDIDATE_IDS or set(reported_results) != set(
        LEGACY_CANDIDATE_IDS
    ):
        raise V18ValidationContractError("seed-17 report candidate family differs")
    for candidate in LEGACY_CANDIDATE_IDS:
        actual = _mapping(reconstructed_results[candidate], name=f"reconstructed.{candidate}")
        expected = _mapping(reported_results.get(candidate), name=f"reported.{candidate}")
        _exact_equal_number(
            actual.get("candidate_sign_flip_pvalue"),
            expected.get("candidate_sign_flip_pvalue"),
            name=f"{candidate}.seed17_pvalue",
        )
        _exact_equal_number(
            actual.get("periodic_monthly_sharpe"),
            expected.get("periodic_monthly_sharpe"),
            name=f"{candidate}.periodic_monthly_sharpe",
        )
    actual_sharpes = _mapping(
        reconstructed.get("trial_periodic_monthly_sharpes"),
        name="reconstructed.trial_periodic_monthly_sharpes",
    )
    expected_sharpes = _mapping(
        reported.get("trial_periodic_monthly_sharpes"),
        name="reported.trial_periodic_monthly_sharpes",
    )
    if tuple(actual_sharpes) != LEGACY_CANDIDATE_IDS or set(expected_sharpes) != set(
        LEGACY_CANDIDATE_IDS
    ):
        raise V18ValidationContractError("seed-17 report Sharpe map family differs")
    for candidate in LEGACY_CANDIDATE_IDS:
        _exact_equal_number(
            actual_sharpes[candidate],
            expected_sharpes[candidate],
            name=f"{candidate}.seed17_trial_sharpe_map",
        )
    return {
        "status": "EXACT_SEED17_REPORT_CROSSCHECK_OK",
        "candidate_count": EXPECTED_LEGACY_CANDIDATES,
        "months": EXPECTED_H_MONTHS,
        "seed": LEGACY_CROSSCHECK_SEED,
        "iterations": VALIDATION_ITERATIONS,
        "candidate_pvalues_and_sharpes_exact": True,
        "trial_sharpe_map_exact": True,
    }


def validate_v18_statistical_contract(preregistration: Mapping[str, Any]) -> None:
    """Reject any result-affecting drift from the locked YAML algorithms."""

    prereg = _mapping(preregistration, name="preregistration")
    trials = _mapping(
        prereg.get("multiple_testing_and_trial_ledger"),
        name="multiple_testing_and_trial_ledger",
    )
    if tuple(_sequence(trials.get("canonical_candidate_order"), name="candidate order")) != (
        CUMULATIVE_CANDIDATE_IDS
    ):
        raise V18ValidationContractError("canonical 13-candidate order differs from contract")
    if (
        trials.get("audit_grade_prior_trials") != EXPECTED_LEGACY_CANDIDATES
        or trials.get("local_v18_trials") != EXPECTED_LOCAL_CANDIDATES
        or trials.get("cumulative_governed_trial_floor") != EXPECTED_CUMULATIVE_CANDIDATES
        or trials.get("thirteen_is_a_floor_not_a_claim_of_total_historical_trials") is not True
    ):
        raise V18ValidationContractError("governed trial-floor contract differs")

    algorithms = _mapping(trials.get("locked_statistical_algorithms"), name="algorithms")
    moving = _mapping(algorithms.get("moving_block_bootstrap"), name="moving bootstrap")
    sign_flip = _mapping(algorithms.get("sign_flip"), name="sign flip")
    holm = _mapping(algorithms.get("holm"), name="Holm")
    periodic = _mapping(algorithms.get("periodic_sharpe"), name="periodic Sharpe")
    dsr = _mapping(algorithms.get("deflated_sharpe"), name="deflated Sharpe")
    pbo = _mapping(algorithms.get("cscv_pbo"), name="CSCV/PBO")
    exact_contract = (
        algorithms.get("missing_or_nonfinite_input") == "fail_closed_UNVERIFIABLE"
        and moving.get("generator") == "numpy_random_default_rng_PCG64_seed_18"
        and moving.get("iterations") == VALIDATION_ITERATIONS
        and moving.get("lower_quantile") == BOOTSTRAP_LOWER_QUANTILE
        and moving.get("draws_per_iteration") == "12_block_indices_uniform_with_replacement"
        and sign_flip.get("generator") == "numpy_random_default_rng_PCG64_seed_18"
        and sign_flip.get("iterations") == VALIDATION_ITERATIONS
        and sign_flip.get("blocks") == "12_nonoverlapping_consecutive_3_month_blocks"
        and sign_flip.get("exceedance") == "null_statistic_greater_than_or_equal_to_observed"
        and holm.get("family_order") == "canonical_candidate_order_restricted_to_family"
        and holm.get("sort") == "ascending_raw_p_stable_ties_preserve_family_order"
        and periodic.get("formula") == "arithmetic_mean_divided_by_sample_standard_deviation_ddof_1"
        and dsr.get("n_trials") == EXPECTED_CUMULATIVE_CANDIDATES
        and dsr.get("periods_per_year") == 12
        and dsr.get("any_nonfinite_trial_sharpe") == "fail_closed_UNVERIFIABLE"
        and pbo.get("candidate_column_order") == list(LOCAL_CANDIDATE_IDS)
        and pbo.get("relative_rank") == "rank_divided_by_5"
        and pbo.get("probability") == "fraction_of_20_logits_less_than_or_equal_to_zero"
    )
    if not exact_contract:
        raise V18ValidationContractError("locked statistical algorithm contract drifted")

    local_holm = _mapping(trials.get("local_holm"), name="local_holm")
    cumulative_holm = _mapping(trials.get("cumulative_floor_holm"), name="cumulative Holm")
    deflated = _mapping(trials.get("deflated_sharpe"), name="deflated_sharpe")
    probability = _mapping(
        trials.get("probability_backtest_overfit"), name="probability_backtest_overfit"
    )
    if (
        local_holm.get("iterations") != VALIDATION_ITERATIONS
        or local_holm.get("seed") != VALIDATION_SEED
        or local_holm.get("scope") != "all_4_v18_cells"
        or cumulative_holm.get("adjusted_p_max") != 0.05
        or cumulative_holm.get("missing_prior_input") != "fail_closed_UNVERIFIABLE"
        or deflated.get("n_trials_floor") != EXPECTED_CUMULATIVE_CANDIDATES
        or deflated.get("minimum") != 0.95
        or probability.get("slices") != PBO_SLICES
        or probability.get("maximum") != 0.20
    ):
        raise V18ValidationContractError("V18 multiple-testing contract drifted")


def load_legacy_trial_inputs(
    preregistration: Mapping[str, Any], *, repo_root: Path
) -> LegacyTrialInputs:
    """Verify bound V16/V17 artifacts and reconstruct their exact H matrix.

    This function reads only already-sealed legacy JSON evidence and bound
    validation source files.  It never opens market/funding databases.
    """

    validate_v18_statistical_contract(preregistration)
    prereg = _mapping(preregistration, name="preregistration")
    trials = _mapping(
        prereg.get("multiple_testing_and_trial_ledger"),
        name="multiple_testing_and_trial_ledger",
    )
    source_specs = _mapping(trials.get("bound_validation_sources"), name="bound sources")
    source_provenance: dict[str, Mapping[str, Any]] = {}
    for source_name in ("shared_statistics", "prior_program_statistics"):
        spec = _mapping(source_specs.get(source_name), name=f"bound source {source_name}")
        _path, _bytes, provenance = _verified_bytes(
            spec, repo_root=repo_root, name=f"bound source {source_name}"
        )
        source_provenance[source_name] = provenance

    artifact_specs = _mapping(trials.get("prior_artifacts"), name="prior_artifacts")
    expected_artifact_names = (
        "v16_prereg",
        "v17_prereg",
        "v16_raw_gzip",
        "v17_raw_json",
        "v17_raw_gzip_crosscheck",
        "v17_report_json",
    )
    if tuple(artifact_specs) != expected_artifact_names:
        raise V18ValidationContractError("prior artifact names/order differ from contract")
    artifact_provenance: dict[str, Mapping[str, Any]] = {}
    for artifact_name in ("v16_prereg", "v17_prereg"):
        spec = _mapping(artifact_specs[artifact_name], name=artifact_name)
        _path, _bytes, provenance = _verified_bytes(spec, repo_root=repo_root, name=artifact_name)
        artifact_provenance[artifact_name] = provenance

    v16_spec = _mapping(artifact_specs["v16_raw_gzip"], name="v16_raw_gzip")
    v16_raw, _v16_decoded, v16_provenance = _artifact_payload(
        v16_spec,
        repo_root=repo_root,
        name="v16_raw_gzip",
        gzip_encoded=True,
    )
    assert v16_raw is not None
    artifact_provenance["v16_raw_gzip"] = v16_provenance

    v17_spec = _mapping(artifact_specs["v17_raw_json"], name="v17_raw_json")
    v17_raw, v17_decoded, v17_provenance = _artifact_payload(
        v17_spec,
        repo_root=repo_root,
        name="v17_raw_json",
        gzip_encoded=False,
    )
    assert v17_raw is not None
    artifact_provenance["v17_raw_json"] = v17_provenance

    v17_gzip_spec = _mapping(
        artifact_specs["v17_raw_gzip_crosscheck"], name="v17_raw_gzip_crosscheck"
    )
    _unused, v17_gzip_decoded, v17_gzip_provenance = _artifact_payload(
        v17_gzip_spec,
        repo_root=repo_root,
        name="v17_raw_gzip_crosscheck",
        gzip_encoded=True,
        parse_json=False,
    )
    if v17_gzip_decoded != v17_decoded:
        raise V18ValidationContractError("V17 raw JSON and gzip decoded bytes differ")
    artifact_provenance["v17_raw_gzip_crosscheck"] = v17_gzip_provenance

    report_spec = _mapping(artifact_specs["v17_report_json"], name="v17_report_json")
    report, _report_decoded, report_provenance = _artifact_payload(
        report_spec,
        repo_root=repo_root,
        name="v17_report_json",
        gzip_encoded=False,
    )
    assert report is not None
    artifact_provenance["v17_report_json"] = report_provenance

    _validate_raw_header(
        v16_raw,
        name="v16_raw",
        schema=str(v16_spec.get("schema_version")),
        candidates=_V16_CANDIDATES,
    )
    _validate_raw_header(
        v17_raw,
        name="v17_raw",
        schema=str(v17_spec.get("schema_version")),
        candidates=_V17_CANDIDATES,
    )
    if report.get("schema_version") != report_spec.get("schema_version"):
        raise V18ValidationContractError("V17 report schema differs from preregistration")
    if report.get("evidence_eligible") is not True:
        raise V18ValidationContractError("V17 report is not evidence eligible")

    bindings = _mapping(trials.get("prior_candidate_field_bindings"), name="prior bindings")
    expected_binding_fields = {
        "input_months": "exact_2023_06_through_2026_05_inclusive_in_chronological_order",
        "monthly_return_unit": "percentage_points",
        "finite_36_values_required": True,
        "v16_monthly_return_pointer_template": (
            "/results/{candidate_id}/H/windows/pseudo_oos/monthly_returns_pct"
        ),
        "v17_monthly_return_pointer_template": (
            "/results/{candidate_id}/H/windows/pseudo_oos/monthly_returns_pct"
        ),
        "prior_raw_pvalue_crosscheck_pointer_template": (
            "/multiple_testing/program_wide_v16_plus_v17_exact_36x9/"
            "candidate_results/{candidate_id}/candidate_sign_flip_pvalue"
        ),
        "prior_periodic_sharpe_crosscheck_pointer_template": (
            "/multiple_testing/program_wide_v16_plus_v17_exact_36x9/"
            "candidate_results/{candidate_id}/periodic_monthly_sharpe"
        ),
        "prior_trial_sharpe_map_crosscheck_pointer": (
            "/multiple_testing/program_wide_v16_plus_v17_exact_36x9/trial_periodic_monthly_sharpes"
        ),
    }
    if any(bindings.get(key) != value for key, value in expected_binding_fields.items()):
        raise V18ValidationContractError("legacy artifact JSON pointer contract differs")
    inputs = _sequence(bindings.get("inputs"), name="prior inputs")
    expected_inputs = tuple(
        (candidate, "v16_raw_gzip" if candidate in _V16_CANDIDATES else "v17_raw_json")
        for candidate in LEGACY_CANDIDATE_IDS
    )
    actual_inputs = tuple(
        (
            str(_mapping(item, name=f"prior inputs[{index}]").get("candidate_id")),
            str(_mapping(item, name=f"prior inputs[{index}]").get("raw_artifact")),
        )
        for index, item in enumerate(inputs)
    )
    if actual_inputs != expected_inputs:
        raise V18ValidationContractError("prior candidate artifact bindings differ")
    v16_results = _mapping(v16_raw.get("results"), name="v16_raw.results")
    v17_results = _mapping(v17_raw.get("results"), name="v17_raw.results")
    if (
        set(v16_results) != set(_V16_CANDIDATES)
        or len(v16_results) != len(_V16_CANDIDATES)
        or set(v17_results) != set(_V17_CANDIDATES)
        or len(v17_results) != len(_V17_CANDIDATES)
    ):
        raise V18ValidationContractError("legacy raw result IDs differ from contract")
    legacy_series: dict[str, pd.Series] = {}
    for candidate, artifact_name in expected_inputs:
        payload = v16_raw if artifact_name == "v16_raw_gzip" else v17_raw
        legacy_series[candidate] = _extract_legacy_series(
            payload,
            candidate=candidate,
            name=artifact_name,
        )
    matrix = exact_legacy_h_matrix(legacy_series)
    crosscheck = _legacy_seed17_crosscheck(matrix, report)
    return LegacyTrialInputs(
        monthly_returns=matrix,
        artifact_provenance=artifact_provenance,
        source_provenance=source_provenance,
        seed17_crosscheck=crosscheck,
    )


def v18_multiple_testing(
    local_candidates: pd.DataFrame | Mapping[str, Any],
    legacy_candidates: pd.DataFrame | Mapping[str, Any] | LegacyTrialInputs,
) -> dict[str, Any]:
    """Run locked local-4 and cumulative-floor-13 V18 tests."""

    local = exact_local_h_matrix(local_candidates)
    legacy_source = (
        legacy_candidates.monthly_returns
        if isinstance(legacy_candidates, LegacyTrialInputs)
        else legacy_candidates
    )
    legacy = exact_legacy_h_matrix(legacy_source)
    cumulative = exact_cumulative_h_matrix(pd.concat((legacy, local), axis=1))

    local_tests = {
        candidate: v18_candidate_sign_flip_test(local[candidate])
        for candidate in LOCAL_CANDIDATE_IDS
    }
    cumulative_tests = {
        candidate: v18_candidate_sign_flip_test(cumulative[candidate])
        for candidate in CUMULATIVE_CANDIDATE_IDS
    }
    local_raw = {
        candidate: float(local_tests[candidate]["candidate_sign_flip_pvalue"])
        for candidate in LOCAL_CANDIDATE_IDS
    }
    cumulative_raw = {
        candidate: float(cumulative_tests[candidate]["candidate_sign_flip_pvalue"])
        for candidate in CUMULATIVE_CANDIDATE_IDS
    }
    local_adjusted = holm_adjusted_pvalues(local_raw)
    cumulative_adjusted = holm_adjusted_pvalues(cumulative_raw)
    assert isinstance(local_adjusted, dict)
    assert isinstance(cumulative_adjusted, dict)

    trial_sharpes = {
        candidate: _periodic_sharpe(cumulative[candidate].to_numpy(dtype=float))
        for candidate in CUMULATIVE_CANDIDATE_IDS
    }
    if not np.isfinite(list(trial_sharpes.values())).all():
        raise V18ValidationContractError(
            "non-finite periodic trial Sharpe makes cumulative DSR UNVERIFIABLE"
        )
    trial_distribution = [trial_sharpes[candidate] for candidate in CUMULATIVE_CANDIDATE_IDS]
    local_results: dict[str, Any] = {}
    cumulative_results: dict[str, Any] = {}
    for candidate in CUMULATIVE_CANDIDATE_IDS:
        cumulative_results[candidate] = {
            **cumulative_tests[candidate],
            "holm_fwer_adjusted_p": float(cumulative_adjusted[candidate]),
            "periodic_monthly_sharpe": float(trial_sharpes[candidate]),
        }
    for candidate in LOCAL_CANDIDATE_IDS:
        dsr = deflated_sharpe_statistics(
            local[candidate].to_numpy(dtype=float),
            n_trials=EXPECTED_CUMULATIVE_CANDIDATES,
            trial_sharpes=trial_distribution,
            periods_per_year=12,
        )
        local_results[candidate] = {
            **local_tests[candidate],
            "local_holm_fwer_adjusted_p": float(local_adjusted[candidate]),
            "cumulative_floor_holm_fwer_adjusted_p": float(cumulative_adjusted[candidate]),
            "periodic_monthly_sharpe": float(trial_sharpes[candidate]),
            "cumulative_floor_deflated_sharpe": float(dsr["deflated_sharpe"]),
            "deflated_sharpe_details": dsr,
        }

    pbo = probability_of_backtest_overfitting(
        local,
        n_slices=PBO_SLICES,
        expected_configurations=EXPECTED_LOCAL_CANDIDATES,
    )
    if pbo.get("status") != "OK" or pbo.get("combinations") != 20:
        raise V18ValidationContractError("local CSCV/PBO did not produce exact 20 combinations")
    return {
        "status": "OK",
        "local_exact_36x4": {
            "candidate_results": local_results,
            "pbo": pbo,
            "candidate_count": EXPECTED_LOCAL_CANDIDATES,
            "months": EXPECTED_H_MONTHS,
            "candidate_order": list(LOCAL_CANDIDATE_IDS),
        },
        "cumulative_floor_exact_36x13": {
            "candidate_results": cumulative_results,
            "trial_periodic_monthly_sharpes": {
                candidate: float(trial_sharpes[candidate]) for candidate in CUMULATIVE_CANDIDATE_IDS
            },
            "candidate_count": EXPECTED_CUMULATIVE_CANDIDATES,
            "months": EXPECTED_H_MONTHS,
            "candidate_order": list(CUMULATIVE_CANDIDATE_IDS),
            "trial_count_is_governed_floor_not_total_historical_exposure": True,
        },
        "iterations": VALIDATION_ITERATIONS,
        "seed": VALIDATION_SEED,
        "block_months": BLOCK_MONTHS,
    }


_GATE_SPECS: dict[tuple[str, str], tuple[str, str]] = {
    ("sample", "pseudo_oos_months"): ("sample.pseudo_oos_months", "eq"),
    ("sample", "minimum_closed_trades"): ("sample.closed_trades", "ge"),
    ("sample", "minimum_long_trades"): ("sample.long_trades", "ge"),
    ("sample", "minimum_short_trades"): ("sample.short_trades", "ge"),
    ("sample", "minimum_active_months"): ("sample.active_months", "ge"),
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
    ("drawdown", "B_max_mtm_pct"): ("drawdown.B_max_mtm_pct", "le"),
    ("drawdown", "worse_of_C2_H_max_mtm_pct"): (
        "drawdown.worse_of_C2_H_max_mtm_pct",
        "le",
    ),
    ("walk_forward", "positive_folds_min"): ("walk_forward.positive_folds", "ge"),
    ("walk_forward", "total_folds"): ("walk_forward.total_folds", "eq"),
    ("walk_forward", "worst_six_month_fold_pct_min"): (
        "walk_forward.worst_six_month_fold_pct",
        "ge",
    ),
    ("walk_forward", "H_oos_to_development_trimmed_return_ratio_min"): (
        "walk_forward.H_oos_to_development_trimmed_return_ratio",
        "ge",
    ),
    ("walk_forward", "H_oos_to_development_drawdown_ratio_max"): (
        "walk_forward.H_oos_to_development_drawdown_ratio",
        "le",
    ),
    ("walk_forward", "nonpositive_return_or_drawdown_denominator"): (
        "walk_forward.denominators_positive",
        "true",
    ),
    ("economic_edge", "B_pre_cost_price_pnl_over_execution_cost_min"): (
        "economic_edge.B_pre_cost_price_pnl_over_execution_cost",
        "ge",
    ),
    ("economic_edge", "denominator_execution_cost_must_be_positive"): (
        "economic_edge.denominator_execution_cost_positive",
        "true",
    ),
    ("economic_edge", "funding_excluded_from_ratio_and_reported_separately"): (
        "economic_edge.funding_excluded_and_reported_separately",
        "true",
    ),
    ("direction", "long_C2_net_must_be_positive"): ("direction.long_C2_net_positive", "true"),
    ("direction", "short_C2_net_must_be_positive"): (
        "direction.short_C2_net_positive",
        "true",
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
    ("concentration", "net_after_top_5pct_trades_removed_must_be_positive"): (
        "concentration.net_after_top_5pct_trades_removed_positive",
        "true",
    ),
    ("concentration", "effective_symbol_count_min"): (
        "concentration.effective_symbol_count",
        "ge",
    ),
    ("concentration", "all_true_leave_one_symbol_out_replays_positive"): (
        "concentration.all_true_leave_one_symbol_out_replays_positive",
        "true",
    ),
    ("multiple_testing", "local_holm_fwer_adjusted_p_max"): (
        "multiple_testing.local_holm_fwer_adjusted_p",
        "le",
    ),
    ("multiple_testing", "cumulative_floor_holm_fwer_adjusted_p_max"): (
        "multiple_testing.cumulative_floor_holm_fwer_adjusted_p",
        "le",
    ),
    ("multiple_testing", "cumulative_floor_deflated_sharpe_min"): (
        "multiple_testing.cumulative_floor_deflated_sharpe",
        "ge",
    ),
    ("multiple_testing", "local_probability_backtest_overfit_max"): (
        "multiple_testing.local_probability_backtest_overfit",
        "le",
    ),
}


def _metric(metrics: Mapping[str, Any], path: str) -> tuple[bool, Any]:
    current: Any = metrics
    for part in path.split("."):
        if not isinstance(current, Mapping) or part not in current:
            return False, None
        current = current[part]
    return True, current


def evaluate_v18_absolute_hard_gates(
    metrics: Mapping[str, Any], *, hard_gates: Mapping[str, Any]
) -> dict[str, Any]:
    """Evaluate every frozen V18 absolute gate with fail-closed semantics."""

    checks: dict[str, Any] = {}
    for group, raw_group in hard_gates.items():
        gates = _mapping(raw_group, name=f"hard_gates.{group}")
        for gate, threshold in gates.items():
            key = (str(group), str(gate))
            if key not in _GATE_SPECS:
                raise V18ValidationContractError(f"unsupported hard gate: {group}.{gate}")
            metric_path, operation = _GATE_SPECS[key]
            found, raw_value = _metric(metrics, metric_path)
            passed = False
            reason: str | None = None
            value: Any = raw_value
            if not found:
                reason = "MISSING_METRIC"
            elif operation == "true":
                if raw_value is True:
                    passed = True
                else:
                    reason = "BOOLEAN_CONTRACT_NOT_MET"
            else:
                try:
                    value = _finite(raw_value, name=metric_path)
                    numeric_threshold = _finite(threshold, name=f"hard_gates.{group}.{gate}")
                except V18ValidationContractError:
                    reason = "NONFINITE_OR_NONNUMERIC_METRIC"
                else:
                    if operation == "eq":
                        passed = value == numeric_threshold
                    elif operation == "ge":
                        passed = value >= numeric_threshold
                    elif operation == "le":
                        passed = value <= numeric_threshold
                    else:  # pragma: no cover - construction-time invariant
                        raise AssertionError(operation)
                    if not passed:
                        reason = "THRESHOLD_NOT_MET"
            check_name = f"{group}.{gate}"
            checks[check_name] = {
                "passed": passed,
                "metric_path": metric_path,
                "value": value,
                "threshold": threshold,
                "operation": operation,
                "reason": reason,
            }
    failed = [name for name, check in checks.items() if not check["passed"]]
    return {
        "passed": not failed,
        "failed_gates": failed,
        "checks": checks,
        "gate_count": len(checks),
    }


def rank_v18_candidates(
    candidate_metrics: Mapping[str, Mapping[str, Any]],
    *,
    absolute_gate_results: Mapping[str, Mapping[str, Any]],
) -> pd.DataFrame:
    """Rank only absolute-gate passers using the preregistered deterministic order."""

    if tuple(candidate_metrics) != LOCAL_CANDIDATE_IDS or tuple(absolute_gate_results) != (
        LOCAL_CANDIDATE_IDS
    ):
        raise V18ValidationContractError("ranking candidates/order differ from C1..C4")
    rows: list[dict[str, Any]] = []
    for candidate in LOCAL_CANDIDATE_IDS:
        gates = _mapping(absolute_gate_results[candidate], name=f"{candidate}.gates")
        if gates.get("passed") is not True:
            continue
        metrics = _mapping(candidate_metrics[candidate], name=f"{candidate}.metrics")
        required = {
            "trimmed": "H_return.trimmed_mean_monthly_pct",
            "drawdown": "drawdown.H_max_mtm_pct",
            "negative": "H_stability.negative_months",
            "worst": "H_stability.worst_month_pct",
            "turnover": "turnover.H_filled_gross_turnover",
        }
        values: dict[str, float] = {}
        for label, path in required.items():
            found, raw = _metric(metrics, path)
            if not found:
                raise V18ValidationContractError(f"{candidate} ranking metric missing: {path}")
            values[label] = _finite(raw, name=f"{candidate}.{path}")
        rows.append(
            {
                "candidate_id": candidate,
                "H_trimmed_mean_monthly_pct": values["trimmed"],
                "H_rank_value_pct": min(values["trimmed"], 15.0),
                "H_max_mtm_drawdown_pct": values["drawdown"],
                "H_negative_months": int(values["negative"]),
                "H_worst_month_pct": values["worst"],
                "H_filled_gross_turnover": values["turnover"],
            }
        )
    rows.sort(
        key=lambda row: (
            -float(row["H_rank_value_pct"]),
            float(row["H_max_mtm_drawdown_pct"]),
            int(row["H_negative_months"]),
            -float(row["H_worst_month_pct"]),
            float(row["H_filled_gross_turnover"]),
            str(row["candidate_id"]),
        )
    )
    for rank, row in enumerate(rows, start=1):
        row["rank"] = rank
    return pd.DataFrame(rows)


__all__ = [
    "BLOCK_MONTHS",
    "BOOTSTRAP_LOWER_QUANTILE",
    "CUMULATIVE_CANDIDATE_IDS",
    "EXPECTED_CUMULATIVE_CANDIDATES",
    "EXPECTED_H_MONTHS",
    "EXPECTED_LEGACY_CANDIDATES",
    "EXPECTED_LOCAL_CANDIDATES",
    "FROZEN_H_MONTHS",
    "LEGACY_CANDIDATE_IDS",
    "LOCAL_CANDIDATE_IDS",
    "PBO_SLICES",
    "SIGN_FLIP_BLOCKS",
    "TRIM_FRACTION",
    "VALIDATION_ITERATIONS",
    "VALIDATION_SEED",
    "LegacyTrialInputs",
    "V18ValidationContractError",
    "evaluate_v18_absolute_hard_gates",
    "exact_cumulative_h_matrix",
    "exact_h_monthly_returns",
    "exact_legacy_h_matrix",
    "exact_local_h_matrix",
    "load_legacy_trial_inputs",
    "rank_v18_candidates",
    "v18_block_bootstrap_lower_bound_pct",
    "v18_candidate_sign_flip_test",
    "v18_multiple_testing",
]
