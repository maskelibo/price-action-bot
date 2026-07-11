"""Deterministic, fail-closed reporting for the frozen v17 pairs batch.

This module consumes results; it never opens a market/funding database and it
never runs a backtest.  The report contract binds the canonical v17
preregistration, the exact v17 and v16 candidate matrices, immutable snapshot
identities, and the full pseudo-OOS calendar before calculating any verdict.

Percentage values are percentage points (``10.0`` means ten percent).
"""

from __future__ import annotations

import argparse
import copy
import functools
import gzip
import hashlib
import importlib.metadata
import json
import math
import platform
import re
import subprocess
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from itertools import combinations, pairwise
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from price_action.lab.crypto_15m_pairs_program import load_preregistration
from price_action.lab.crypto_15m_pairs_validation import (
    DEFAULT_V17_HARD_GATES,
    FROZEN_H_MONTHS,
    FROZEN_PROGRAM_CANDIDATE_IDS,
    FROZEN_V16_CANDIDATE_IDS,
    FROZEN_V17_CANDIDATE_IDS,
    VALIDATION_ITERATIONS,
    VALIDATION_SEED,
    descriptive_symbol_attribution,
    entry_regime_statistics,
    episode_concentration_statistics,
    evaluate_v17_hard_gates,
    h_monthly_statistics,
    program_wide_multiple_testing,
    rank_h_candidates,
    three_candidate_multiple_testing,
    true_loso_statistics,
)
from price_action.lab.crypto_15m_validation import monthly_return_statistics, trimmed_mean_pct

REPORT_SCHEMA = "crypto-15m-v17-pairs-report-v1"
V17_RAW_SCHEMA = "crypto-15m-v17-pairs-run-v1"
V16_RAW_SCHEMA = "crypto-15m-v16-run-v1"
PREREG_SCHEMA = "crypto-15m-v17-pairs-prereg-v1"
FULL_REPLAY_MODE = "FULL_FROZEN_REPLAY"
SCENARIO_ORDER = ("B", "C2", "H")
RED_NO_HOLDOUT = "RED_NO_HOLDOUT"
REQUIRES_TRUE_LOSO = "REQUIRES_TRUE_LOSO"
_H_START = pd.Timestamp("2023-06-01T00:00:00Z")
_H_END = pd.Timestamp("2026-06-01T00:00:00Z")
_SHA256_LENGTH = 64
_COMMIT_SHA = re.compile(r"^[0-9a-f]{40}$")
_FROZEN_SOURCE_FILES = (
    "configs/crypto_15m_v17_pairs_prereg.yaml",
    "docs/CRYPTO_15M_V17_PAIRS_PREREG_2026-07-11.md",
    "requirements-lock.txt",
    "scripts/research/crypto_15m_v17_pairs_program.py",
    "scripts/research/crypto_15m_v17_pairs_report.py",
    "src/price_action/lab/crypto_15m_pairs_engine.py",
    "src/price_action/lab/crypto_15m_pairs_evidence.py",
    "src/price_action/lab/crypto_15m_pairs_program.py",
    "src/price_action/lab/crypto_15m_pairs_report.py",
    "src/price_action/lab/crypto_15m_pairs_signals.py",
    "src/price_action/lab/crypto_15m_pairs_validation.py",
    "src/price_action/lab/crypto_15m_validation.py",
)


class PairsReportContractError(ValueError):
    """Raised when input evidence cannot satisfy the frozen report contract."""


@dataclass(frozen=True, slots=True)
class JsonArtifact:
    path: Path
    payload: dict[str, Any]
    file_bytes: int
    decoded_json_bytes: int
    file_sha256: str
    decoded_json_sha256: str
    compression: str

    def provenance(self) -> dict[str, Any]:
        return {
            "path": str(self.path),
            "compression": self.compression,
            "file_bytes": self.file_bytes,
            "decoded_json_bytes": self.decoded_json_bytes,
            "file_sha256": self.file_sha256,
            "decoded_json_sha256": self.decoded_json_sha256,
        }


def _reject_json_constant(value: str) -> None:
    raise PairsReportContractError(f"non-finite JSON constant is forbidden: {value}")


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise PairsReportContractError(f"duplicate JSON key is forbidden: {key!r}")
        result[key] = value
    return result


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while block := handle.read(8 * 1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def load_json_artifact(path: Path) -> JsonArtifact:
    """Load strict JSON or JSON.gz while preserving both byte identities."""

    resolved = path.resolve(strict=True)
    if not resolved.is_file():
        raise PairsReportContractError(f"artifact is not a regular file: {resolved}")
    encoded = resolved.read_bytes()
    if resolved.suffix.lower() == ".gz":
        try:
            decoded = gzip.decompress(encoded)
        except (gzip.BadGzipFile, EOFError, OSError) as exc:
            raise PairsReportContractError(f"invalid gzip artifact: {resolved}") from exc
        compression = "gzip"
    else:
        decoded = encoded
        compression = "none"
    try:
        payload = json.loads(
            decoded.decode("utf-8"),
            parse_constant=_reject_json_constant,
            object_pairs_hook=_unique_object,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PairsReportContractError(f"invalid UTF-8 JSON artifact: {resolved}") from exc
    if not isinstance(payload, dict):
        raise PairsReportContractError("raw result JSON must be a top-level object")
    return JsonArtifact(
        path=resolved,
        payload=payload,
        file_bytes=len(encoded),
        decoded_json_bytes=len(decoded),
        file_sha256=_sha256_bytes(encoded),
        decoded_json_sha256=_sha256_bytes(decoded),
        compression=compression,
    )


def _mapping(value: Any, *, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise PairsReportContractError(f"{name} must be a JSON object")
    return value


def _list(value: Any, *, name: str) -> list[Any]:
    if not isinstance(value, list):
        raise PairsReportContractError(f"{name} must be a JSON array")
    return value


def _exact_bool(value: Any, expected: bool, *, name: str) -> None:
    if value is not expected:
        raise PairsReportContractError(f"{name} must be {expected!r}")


def _finite(value: Any, *, name: str, positive: bool = False, nonnegative: bool = False) -> float:
    if isinstance(value, bool):
        raise PairsReportContractError(f"{name} must be numeric")
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise PairsReportContractError(f"{name} must be numeric") from exc
    if not math.isfinite(parsed):
        raise PairsReportContractError(f"{name} must be finite")
    if positive and parsed <= 0.0:
        raise PairsReportContractError(f"{name} must be > 0")
    if nonnegative and parsed < 0.0:
        raise PairsReportContractError(f"{name} must be >= 0")
    return parsed


def _integer(value: Any, *, name: str, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise PairsReportContractError(f"{name} must be an integer >= {minimum}")
    return value


def _utc(value: Any, *, name: str) -> pd.Timestamp:
    try:
        timestamp = pd.Timestamp(value)
    except (TypeError, ValueError) as exc:
        raise PairsReportContractError(f"{name} must be a UTC timestamp") from exc
    if timestamp.tzinfo is None or timestamp.utcoffset() != pd.Timedelta(0):
        raise PairsReportContractError(f"{name} must be timezone-aware UTC")
    return timestamp.tz_convert("UTC")


def _canonical_hash(value: Any) -> str:
    try:
        encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode(
            "utf-8"
        )
    except (TypeError, ValueError) as exc:
        raise PairsReportContractError("evidence contains non-canonical JSON values") from exc
    return _sha256_bytes(encoded)


def _assert_payload_hash(container: Mapping[str, Any], field: str, *, name: str) -> None:
    hash_field = f"{field}_sha256"
    expected = container.get(hash_field)
    if not isinstance(expected, str) or len(expected) != _SHA256_LENGTH:
        raise PairsReportContractError(f"{name}.{hash_field} is missing or invalid")
    if _canonical_hash(container.get(field)) != expected:
        raise PairsReportContractError(f"{name}.{field} hash mismatch")


def _same_number(actual: float, expected: float, *, name: str) -> None:
    if not math.isclose(actual, expected, rel_tol=1e-10, abs_tol=1e-8):
        raise PairsReportContractError(f"{name} reconciliation failed")


def _month_range(start: pd.Timestamp, end: pd.Timestamp) -> pd.PeriodIndex:
    return pd.period_range(
        start.tz_localize(None).to_period("M"),
        (end - pd.Timedelta(nanoseconds=1)).tz_localize(None).to_period("M"),
        freq="M",
        name="month",
    )


def _expected_windows(prereg: Mapping[str, Any]) -> dict[str, tuple[pd.Timestamp, pd.Timestamp]]:
    protocol = _mapping(prereg.get("time_protocol"), name="prereg.time_protocol")
    complete = _list(protocol.get("complete_months_utc"), name="complete_months_utc")
    development = _list(protocol.get("development"), name="development")
    folds = _list(protocol.get("expanding_walk_forward"), name="expanding_walk_forward")
    common_is = _list(
        _mapping(prereg.get("validation_metrics"), name="validation_metrics").get(
            "common_IS_ratio_window"
        ),
        name="common_IS_ratio_window",
    )
    if len(complete) != 2 or len(development) != 2 or len(common_is) != 2 or len(folds) != 6:
        raise PairsReportContractError("preregistered window cardinality changed")
    parsed_folds: list[tuple[pd.Timestamp, pd.Timestamp]] = []
    for index, raw in enumerate(folds, start=1):
        values = _list(raw, name=f"walk_forward_{index}")
        if len(values) != 2:
            raise PairsReportContractError("each walk-forward fold needs two boundaries")
        parsed_folds.append((_utc(values[0], name="fold start"), _utc(values[1], name="fold end")))
    result = {
        "complete": (
            _utc(complete[0], name="complete start"),
            _utc(complete[1], name="complete end"),
        ),
        "development": (
            _utc(development[0], name="development start"),
            _utc(development[1], name="development end"),
        ),
        "common_is": (
            _utc(common_is[0], name="common IS start"),
            _utc(common_is[1], name="common IS end"),
        ),
        "pseudo_oos": (parsed_folds[0][0], parsed_folds[-1][1]),
    }
    result.update({f"walk_forward_{index}": bounds for index, bounds in enumerate(parsed_folds, 1)})
    if result["pseudo_oos"] != (_H_START, _H_END):
        raise PairsReportContractError("pseudo-OOS boundaries must be 2023-06-01..2026-06-01")
    return result


def _first_monday_schedule(start: pd.Timestamp, end: pd.Timestamp) -> tuple[pd.Timestamp, ...]:
    schedule: list[pd.Timestamp] = []
    for month in pd.period_range(
        start.tz_localize(None).to_period("M"),
        end.tz_localize(None).to_period("M"),
        freq="M",
    ):
        first = month.start_time.tz_localize("UTC")
        selection = first + pd.Timedelta(days=(7 - first.dayofweek) % 7)
        if start <= selection < end:
            schedule.append(selection)
    return tuple(schedule)


def _pair_symbols(
    pair_id: Any,
    *,
    primary_symbols: set[str],
    name: str,
    y_symbol: Any | None = None,
    x_symbol: Any | None = None,
) -> tuple[str, str]:
    if not isinstance(pair_id, str):
        raise PairsReportContractError(f"{name}.pair_id must be a string")
    pieces = tuple(pair_id.split("|"))
    if len(pieces) != 2 or not pieces[0] or not pieces[1] or pieces[0] == pieces[1]:
        raise PairsReportContractError(f"{name}.pair_id must identify two distinct symbols")
    if not set(pieces).issubset(primary_symbols):
        raise PairsReportContractError(f"{name} pair leaks outside the primary universe")
    if (y_symbol is None) != (x_symbol is None):
        raise PairsReportContractError(f"{name} must provide both pair leg symbols or neither")
    if y_symbol is not None and (
        not isinstance(y_symbol, str)
        or not isinstance(x_symbol, str)
        or y_symbol == x_symbol
        or {y_symbol, x_symbol} != set(pieces)
    ):
        raise PairsReportContractError(f"{name} pair_id and y/x symbols disagree")
    return pieces


def _validate_stream_contract(
    stream: Mapping[str, Any],
    *,
    candidate: str,
    windows: Mapping[str, tuple[pd.Timestamp, pd.Timestamp]],
    primary_symbols: set[str],
    prereg: Mapping[str, Any],
) -> dict[str, Any]:
    """Bind the complete selection/model/intent chain for one candidate."""

    selection_ledger = _list(
        stream.get("pair_selection_ledger"), name=f"streams.{candidate}.selection_ledger"
    )
    expected_schedule = _first_monday_schedule(*windows["complete"])
    actual_schedule = tuple(
        _utc(
            _mapping(item, name=f"{candidate}.selection[{index}]").get("selection_ts"),
            name=f"{candidate}.selection[{index}].selection_ts",
        )
        for index, item in enumerate(selection_ledger)
    )
    if actual_schedule != expected_schedule:
        raise PairsReportContractError(
            f"{candidate} selection ledger must contain every exact first-Monday timestamp"
        )

    flattened_models: list[dict[str, Any]] = []
    selected_by_timestamp: dict[pd.Timestamp, set[str]] = {}
    model_by_key: dict[tuple[pd.Timestamp, str], dict[str, Any]] = {}
    for index, raw_selection in enumerate(selection_ledger):
        selection = _mapping(raw_selection, name=f"{candidate}.selection[{index}]")
        selection_ts = actual_schedule[index]
        selected_ids_raw = _list(
            selection.get("selected_pair_ids"), name=f"{candidate}.selected_pair_ids"
        )
        if (
            any(not isinstance(item, str) for item in selected_ids_raw)
            or selected_ids_raw != sorted(selected_ids_raw)
            or len(selected_ids_raw) != len(set(selected_ids_raw))
            or len(selected_ids_raw) > 3
        ):
            raise PairsReportContractError(f"{candidate} selected pair IDs are invalid")
        selected_ids = set(selected_ids_raw)
        selected_symbols: set[str] = set()
        for pair_id in selected_ids_raw:
            pieces = _pair_symbols(
                pair_id, primary_symbols=primary_symbols, name=f"{candidate}.selected pair"
            )
            if selected_symbols.intersection(pieces):
                raise PairsReportContractError(
                    f"{candidate} selected pairs overlap symbols at {selection_ts.isoformat()}"
                )
            selected_symbols.update(pieces)

        models = [
            _mapping(item, name=f"{candidate}.selected_models")
            for item in _list(selection.get("selected_models"), name=f"{candidate}.selected_models")
        ]
        decisions = [
            _mapping(item, name=f"{candidate}.pair_decisions")
            for item in _list(selection.get("pair_decisions"), name=f"{candidate}.pair_decisions")
        ]
        rejected = [
            _mapping(item, name=f"{candidate}.rejected_pair_reasons")
            for item in _list(
                selection.get("rejected_pair_reasons"),
                name=f"{candidate}.rejected_pair_reasons",
            )
        ]
        if [item for item in decisions if item.get("status") == "rejected"] != rejected:
            raise PairsReportContractError(f"{candidate} rejected decision ledger mismatch")
        decision_ids = [item.get("pair_id") for item in decisions]
        expected_decision_ids = [
            "|".join(pair) for pair in combinations(sorted(primary_symbols), 2)
        ]
        if decision_ids != expected_decision_ids:
            raise PairsReportContractError(
                f"{candidate} selection decisions must terminate all 78 primary pairs"
            )
        selected_decision_ids = {
            str(item["pair_id"]) for item in decisions if item.get("status") == "selected"
        }
        if selected_decision_ids != selected_ids:
            raise PairsReportContractError(f"{candidate} selected decisions disagree with IDs")
        for decision in decisions:
            if decision.get("status") not in {"selected", "rejected"}:
                raise PairsReportContractError(f"{candidate} selection decision status is invalid")
            if (
                not isinstance(decision.get("reason"), str)
                or not str(decision.get("reason")).strip()
            ):
                raise PairsReportContractError(f"{candidate} selection decision reason is empty")
            if (
                _utc(decision.get("selection_ts"), name=f"{candidate}.decision.selection_ts")
                != selection_ts
            ):
                raise PairsReportContractError(f"{candidate} decision selection timestamp mismatch")
            if decision.get("y_symbol") is None and decision.get("x_symbol") is None:
                _pair_symbols(
                    decision.get("pair_id"),
                    primary_symbols=primary_symbols,
                    name=f"{candidate}.decision",
                )
            else:
                _pair_symbols(
                    decision.get("pair_id"),
                    primary_symbols=primary_symbols,
                    name=f"{candidate}.decision",
                    y_symbol=decision.get("y_symbol"),
                    x_symbol=decision.get("x_symbol"),
                )

        model_ids: set[str] = set()
        for model in models:
            pair_id = model.get("pair_id")
            if not isinstance(pair_id, str) or pair_id in model_ids:
                raise PairsReportContractError(f"{candidate} selected models duplicate pair IDs")
            model_ids.add(pair_id)
            if (
                _utc(model.get("selection_ts"), name=f"{candidate}.model.selection_ts")
                != selection_ts
            ):
                raise PairsReportContractError(f"{candidate} model selection timestamp mismatch")
            _pair_symbols(
                pair_id,
                primary_symbols=primary_symbols,
                name=f"{candidate}.model",
                y_symbol=model.get("y_symbol"),
                x_symbol=model.get("x_symbol"),
            )
            model_by_key[(selection_ts, pair_id)] = model
        if model_ids != selected_ids:
            raise PairsReportContractError(f"{candidate} selected models disagree with IDs")
        flattened_models.extend(models)
        selected_by_timestamp[selection_ts] = selected_ids

    raw_models = [
        _mapping(item, name=f"streams.{candidate}.pair_models")
        for item in _list(stream.get("pair_models"), name=f"streams.{candidate}.pair_models")
    ]
    if raw_models != flattened_models:
        raise PairsReportContractError(
            f"{candidate} flattened pair models disagree with monthly selection ledger"
        )

    intents = [
        _mapping(item, name=f"streams.{candidate}.entry_intents")
        for item in _list(stream.get("entry_intents"), name=f"streams.{candidate}.entry_intents")
    ]
    intent_by_key: dict[tuple[str, pd.Timestamp, pd.Timestamp], dict[str, Any]] = {}
    schedule_positions = {timestamp: index for index, timestamp in enumerate(expected_schedule)}
    cell = next(
        (
            _mapping(item, name="candidate cell")
            for item in _list(prereg.get("candidate_cells"), name="candidate_cells")
            if isinstance(item, Mapping) and item.get("id") == candidate
        ),
        None,
    )
    if cell is None:
        raise PairsReportContractError(f"{candidate} is absent from canonical candidate cells")
    economic_gate = _mapping(prereg.get("economic_entry_gate"), name="economic_entry_gate")
    for intent in intents:
        selection_ts = _utc(intent.get("selection_ts"), name=f"{candidate}.intent.selection_ts")
        decision_ts = _utc(intent.get("decision_ts"), name=f"{candidate}.intent.decision_ts")
        entry_ts = _utc(intent.get("entry_ts"), name=f"{candidate}.intent.entry_ts")
        pair_id = intent.get("pair_id")
        if (
            selection_ts not in schedule_positions
            or pair_id not in selected_by_timestamp[selection_ts]
        ):
            raise PairsReportContractError(f"{candidate} intent lacks its selected monthly pair")
        next_index = schedule_positions[selection_ts] + 1
        active_end = (
            expected_schedule[next_index]
            if next_index < len(expected_schedule)
            else windows["complete"][1]
        )
        if not selection_ts <= entry_ts < active_end:
            raise PairsReportContractError(f"{candidate} intent lies outside its selection month")
        if entry_ts - decision_ts != pd.Timedelta(minutes=15) or decision_ts.minute != 45:
            raise PairsReportContractError(f"{candidate} intent decision/entry timing is invalid")
        model = model_by_key[(selection_ts, str(pair_id))]
        _pair_symbols(
            pair_id,
            primary_symbols=primary_symbols,
            name=f"{candidate}.intent",
            y_symbol=intent.get("y_symbol"),
            x_symbol=intent.get("x_symbol"),
        )
        if (intent.get("y_symbol"), intent.get("x_symbol")) != (
            model.get("y_symbol"),
            model.get("x_symbol"),
        ):
            raise PairsReportContractError(f"{candidate} intent symbols disagree with model")
        for field in (
            "alpha",
            "beta",
            "validation_mean",
            "validation_std",
            "gross_weight_y",
            "gross_weight_x",
        ):
            _same_number(
                _finite(intent.get(field), name=f"intent {field}"),
                _finite(model.get(field), name=f"model {field}"),
                name=f"{candidate} intent/model {field}",
            )
        for intent_field, cell_field in (
            ("entry_abs_z", "entry_abs_z"),
            ("exit_abs_z", "exit_abs_z"),
            ("disaster_abs_z", "disaster_abs_z"),
            ("max_hold_hours", "max_hold_hours"),
            ("cooldown_hours", "cooldown_hours"),
        ):
            _same_number(
                _finite(intent.get(intent_field), name=f"intent {intent_field}", positive=True),
                _finite(cell.get(cell_field), name=f"cell {cell_field}", positive=True),
                name=f"{candidate} intent/cell {intent_field}",
            )
        _same_number(
            _finite(
                intent.get("economic_buffer_multiplier"),
                name="intent economic buffer",
                positive=True,
            ),
            _finite(economic_gate.get("buffer_multiplier"), name="canonical buffer", positive=True),
            name="intent canonical economic buffer",
        )
        _same_number(
            _finite(
                intent.get("base_round_trip_cost_per_gross"),
                name="intent base round-trip cost",
                nonnegative=True,
            ),
            _finite(
                economic_gate.get("base_round_trip_cost_per_gross_exposure"),
                name="canonical base round-trip cost",
                nonnegative=True,
            ),
            name="intent canonical base round-trip cost",
        )
        _same_number(
            _finite(
                intent.get("c2_round_trip_cost_per_gross"),
                name="intent C2 round-trip cost",
                nonnegative=True,
            ),
            _finite(
                economic_gate.get("C2_round_trip_cost_per_gross_exposure"),
                name="canonical C2 round-trip cost",
                nonnegative=True,
            ),
            name="intent canonical C2 round-trip cost",
        )
        signal_z = _finite(intent.get("z_score"), name="intent z score")
        beta = _finite(intent.get("beta"), name="intent beta", positive=True)
        validation_std = _finite(
            intent.get("validation_std"), name="intent validation std", positive=True
        )
        exit_abs_z = _finite(intent.get("exit_abs_z"), name="intent exit z", positive=True)
        _same_number(
            _finite(
                intent.get("expected_convergence_return"),
                name="intent expected convergence",
                nonnegative=True,
            ),
            (abs(signal_z) - exit_abs_z) * validation_std / (1.0 + beta),
            name="intent signal expected convergence identity",
        )
        adverse_funding = _finite(
            intent.get("adverse_funding"), name="intent adverse funding", nonnegative=True
        )
        buffer = _finite(
            intent.get("economic_buffer_multiplier"), name="intent economic buffer", positive=True
        )
        base_cost = _finite(
            intent.get("base_round_trip_cost_per_gross"),
            name="intent base cost",
            nonnegative=True,
        )
        c2_cost = _finite(
            intent.get("c2_round_trip_cost_per_gross"),
            name="intent C2 cost",
            nonnegative=True,
        )
        _same_number(
            _finite(
                intent.get("stressed_required_return"),
                name="intent stressed requirement",
                nonnegative=True,
            ),
            buffer * max(c2_cost + 2.0 * adverse_funding, 2.0 * (base_cost + adverse_funding)),
            name="intent stressed requirement identity",
        )
        key = (str(pair_id), selection_ts, entry_ts)
        if key in intent_by_key:
            raise PairsReportContractError(f"{candidate} duplicate entry intent")
        intent_by_key[key] = intent
    return {
        "selection_timestamps": expected_schedule,
        "selected_by_timestamp": selected_by_timestamp,
        "model_by_key": model_by_key,
        "intent_by_key": intent_by_key,
    }


def _series_from_mapping(
    value: Any,
    *,
    name: str,
    expected_months: pd.PeriodIndex,
) -> pd.Series:
    raw = _mapping(value, name=name)
    expected_keys = tuple(str(month) for month in expected_months)
    if tuple(raw) != expected_keys:
        raise PairsReportContractError(
            f"{name} must contain the exact chronological months {expected_keys[0]}..{expected_keys[-1]}"
        )
    parsed = [_finite(raw[key], name=f"{name}[{key}]") for key in expected_keys]
    return pd.Series(parsed, index=expected_months, dtype=float, name=name)


def _window_payload(
    value: Any,
    *,
    name: str,
    start: pd.Timestamp,
    end: pd.Timestamp,
) -> dict[str, Any]:
    window = _mapping(value, name=name)
    if _utc(window.get("start_inclusive"), name=f"{name}.start") != start:
        raise PairsReportContractError(f"{name} start boundary mismatch")
    if _utc(window.get("end_exclusive"), name=f"{name}.end") != end:
        raise PairsReportContractError(f"{name} end boundary mismatch")
    if window.get("monthly_returns_unit") != "percentage_points":
        raise PairsReportContractError(f"{name} monthly return unit mismatch")
    months = _month_range(start, end)
    returns = _series_from_mapping(
        window.get("monthly_returns_pct"),
        name=f"{name}.monthly_returns_pct",
        expected_months=months,
    )
    pnl = _series_from_mapping(
        window.get("monthly_pnl"), name=f"{name}.monthly_pnl", expected_months=months
    )
    baseline = _finite(window.get("baseline_equity"), name=f"{name}.baseline", positive=True)
    pre_window_peak = _finite(
        window.get("pre_window_peak_equity"), name=f"{name}.pre-window peak", positive=True
    )
    if pre_window_peak + 1e-8 < baseline:
        raise PairsReportContractError(f"{name} pre-window peak is below baseline equity")
    ending = _finite(window.get("ending_equity"), name=f"{name}.ending")
    previous = baseline
    month_end_equities: list[float] = []
    for month in months:
        expected_ending = previous * (1.0 + float(returns.loc[month]) / 100.0)
        _same_number(
            float(pnl.loc[month]), expected_ending - previous, name=f"{name}.{month}.monthly_pnl"
        )
        previous = expected_ending
        month_end_equities.append(expected_ending)
    _same_number(ending, previous, name=f"{name}.ending_equity")
    total_return = (ending / baseline - 1.0) * 100.0
    _same_number(
        _finite(window.get("total_return_pct"), name=f"{name}.total_return_pct"),
        total_return,
        name=f"{name}.total_return_pct",
    )
    observations = _integer(
        window.get("equity_observations"), name=f"{name}.equity_observations", minimum=1
    )
    nav_sum = _finite(window.get("nav_observation_sum"), name=f"{name}.nav_sum", positive=True)
    nav_mean = _finite(
        window.get("arithmetic_mean_15m_nav"), name=f"{name}.nav_mean", positive=True
    )
    _same_number(nav_mean, nav_sum / observations, name=f"{name}.NAV mean")
    active = _mapping(window.get("monthly_active_exposure"), name=f"{name}.active")
    if tuple(active) != tuple(str(month) for month in months) or any(
        item is not True and item is not False for item in active.values()
    ):
        raise PairsReportContractError(f"{name} monthly active exposure calendar is invalid")
    active_months = _integer(window.get("active_months"), name=f"{name}.active_months")
    if active_months != sum(value is True for value in active.values()):
        raise PairsReportContractError(f"{name} active month count mismatch")
    peak = pre_window_peak
    current_recovery = 0
    maximum_recovery = 0
    monthly_close_drawdown_lower_bound = 0.0
    for month_end_equity in month_end_equities:
        monthly_close_drawdown_lower_bound = max(
            monthly_close_drawdown_lower_bound,
            (peak - month_end_equity) / peak * 100.0,
        )
        if month_end_equity >= peak - 1e-12:
            peak = max(peak, month_end_equity)
            current_recovery = 0
        else:
            current_recovery += 1
            maximum_recovery = max(maximum_recovery, current_recovery)
    reported_recovery = _integer(window.get("max_recovery_months"), name=f"{name}.recovery")
    if reported_recovery != maximum_recovery:
        raise PairsReportContractError(f"{name} monthly recovery length mismatch")
    reported_drawdown = _finite(
        window.get("max_mtm_drawdown_pct"), name=f"{name}.max_dd", nonnegative=True
    )
    if reported_drawdown + 1e-8 < monthly_close_drawdown_lower_bound:
        raise PairsReportContractError(
            f"{name} MTM drawdown is below the reconstructed monthly-close lower bound"
        )
    return {
        "start_inclusive": start.isoformat(),
        "end_exclusive": end.isoformat(),
        "baseline_equity": baseline,
        "pre_window_peak_equity": pre_window_peak,
        "ending_equity": ending,
        "total_return_pct": total_return,
        "equity_observations": observations,
        "nav_observation_sum": nav_sum,
        "arithmetic_mean_15m_nav": nav_mean,
        "max_mtm_drawdown_pct": reported_drawdown,
        "max_recovery_months": reported_recovery,
        "active_months": active_months,
        "closed_pair_episodes": _integer(
            window.get("closed_pair_episodes"), name=f"{name}.closed episodes"
        ),
        "terminal_open_pair_pseudo_episodes": _integer(
            window.get("terminal_open_pair_pseudo_episodes"),
            name=f"{name}.terminal episodes",
        ),
        "high_spread_closed_episodes": _integer(
            window.get("high_spread_closed_episodes"), name=f"{name}.high spread"
        ),
        "low_spread_closed_episodes": _integer(
            window.get("low_spread_closed_episodes"), name=f"{name}.low spread"
        ),
        "monthly_returns_pct": {str(month): float(value) for month, value in returns.items()},
        "monthly_pnl": {str(month): float(value) for month, value in pnl.items()},
        "monthly_active_exposure": {str(key): bool(item) for key, item in active.items()},
        "_returns": returns,
        "_pnl": pnl,
    }


def _public_window(window: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in window.items() if not key.startswith("_")}


def _snapshot_contract(payload: Mapping[str, Any], prereg: Mapping[str, Any], *, name: str) -> None:
    actual = _mapping(payload, name=name)
    expected = _mapping(
        _mapping(prereg.get("snapshots"), name="snapshots").get(name.rsplit(".", 1)[-1]),
        name="snapshot prereg",
    )
    expected_sha = str(expected.get("sha256"))
    expected_bytes = expected.get("bytes")
    if actual.get("status") != "VERIFIED":
        raise PairsReportContractError(f"{name} must be VERIFIED")
    if actual.get("sha256") != expected_sha or actual.get("bytes") != expected_bytes:
        raise PairsReportContractError(f"{name} immutable identity mismatch")


def _validate_runner_provenance(
    payload: Mapping[str, Any],
    *,
    prereg_sha256: str,
    canonical_prereg_path: Path,
    repo_root: Path,
) -> None:
    source = _mapping(payload.get("source_provenance"), name="v17.source_provenance")
    _exact_bool(source.get("research_source_clean"), True, name="research_source_clean")
    if source.get("research_source_status") != []:
        raise PairsReportContractError("v17 research source status must be empty")
    if source.get("missing_source_files") != []:
        raise PairsReportContractError("v17 runner reports missing frozen source files")
    file_hashes = _mapping(source.get("file_sha256"), name="v17 source file hashes")
    if set(file_hashes) != set(_FROZEN_SOURCE_FILES) or len(file_hashes) != len(
        _FROZEN_SOURCE_FILES
    ):
        raise PairsReportContractError("v17 source file list differs from frozen report contract")
    if any(
        not isinstance(value, str) or len(value) != _SHA256_LENGTH for value in file_hashes.values()
    ):
        raise PairsReportContractError("v17 source file hashes are incomplete")
    for relative in _FROZEN_SOURCE_FILES:
        path = repo_root / relative
        if not path.is_file() or sha256_file(path) != file_hashes[relative]:
            raise PairsReportContractError(f"v17 frozen source hash mismatch: {relative}")
    governance = _mapping(payload.get("execution_governance"), name="execution_governance")
    for field in (
        "canonical_prereg_semantic_match",
        "clean_source_preflight",
        "source_unchanged_postflight",
        "snapshots_reverified_postflight",
        "snapshots_unchanged_postflight",
    ):
        _exact_bool(governance.get(field), True, name=f"execution_governance.{field}")
    if governance.get("preflight_git_commit") != governance.get("postflight_git_commit"):
        raise PairsReportContractError("v17 runner commit changed during replay")
    if source.get("git_commit") != governance.get("preflight_git_commit"):
        raise PairsReportContractError("v17 source commit disagrees with execution governance")
    commit = str(source.get("git_commit", ""))
    if not _COMMIT_SHA.fullmatch(commit):
        raise PairsReportContractError("v17 source commit must be a lowercase 40-hex Git commit")
    _validate_git_commit_blobs(
        str(repo_root),
        commit,
        tuple((relative, str(file_hashes[relative])) for relative in _FROZEN_SOURCE_FILES),
    )
    try:
        governed_prereg_path = Path(str(governance.get("canonical_prereg_path"))).resolve()
    except (OSError, TypeError, ValueError) as exc:
        raise PairsReportContractError("v17 canonical preregistration path is invalid") from exc
    if governed_prereg_path != canonical_prereg_path:
        raise PairsReportContractError("v17 canonical preregistration path mismatch")
    if governance.get("canonical_prereg_preflight_sha256") != prereg_sha256:
        raise PairsReportContractError("v17 preflight preregistration hash mismatch")
    if governance.get("canonical_prereg_postflight_sha256") != prereg_sha256:
        raise PairsReportContractError("v17 postflight preregistration hash mismatch")
    if governance.get("preflight_source_file_sha256") != governance.get(
        "postflight_source_file_sha256"
    ):
        raise PairsReportContractError("v17 source hashes changed during replay")
    if governance.get("postflight_source_file_sha256") != file_hashes:
        raise PairsReportContractError("v17 postflight source hashes disagree with provenance")


@functools.lru_cache(maxsize=8)
def _validate_git_commit_blobs(
    repo_root: str, commit: str, expected_hashes: tuple[tuple[str, str], ...]
) -> None:
    try:
        subprocess.run(
            ["git", "cat-file", "-e", f"{commit}^{{commit}}"],
            cwd=repo_root,
            check=True,
            capture_output=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise PairsReportContractError(
            "v17 source commit is not a valid repository commit"
        ) from exc
    for relative, expected_hash in expected_hashes:
        try:
            committed = subprocess.run(
                ["git", "show", f"{commit}:{relative}"],
                cwd=repo_root,
                check=True,
                capture_output=True,
            ).stdout
        except (OSError, subprocess.CalledProcessError) as exc:
            raise PairsReportContractError(
                f"v17 source commit is missing frozen dependency: {relative}"
            ) from exc
        if _sha256_bytes(committed) != expected_hash:
            raise PairsReportContractError(f"v17 source commit blob hash mismatch: {relative}")


def _validate_runtime_versions(payload: Mapping[str, Any], *, repo_root: Path) -> None:
    runtime = _mapping(payload.get("runtime_versions"), name="v17.runtime_versions")
    expected_runtime = {
        "python": platform.python_version(),
        "python_implementation": platform.python_implementation(),
        "duckdb": importlib.metadata.version("duckdb"),
        "numpy": importlib.metadata.version("numpy"),
        "pandas": importlib.metadata.version("pandas"),
        "pyyaml": importlib.metadata.version("PyYAML"),
        "scipy": importlib.metadata.version("scipy"),
        "statsmodels": importlib.metadata.version("statsmodels"),
    }
    if runtime != expected_runtime:
        raise PairsReportContractError(
            "v17 runtime versions differ from the exact reporter environment"
        )
    lock_path = repo_root / "requirements-lock.txt"
    pins: dict[str, str] = {}
    for line in lock_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "==" not in stripped:
            continue
        package, version = stripped.split("==", 1)
        pins[package.lower()] = version
    for package in ("duckdb", "numpy", "pandas", "pyyaml", "scipy", "statsmodels"):
        if pins.get(package) != runtime[package]:
            raise PairsReportContractError(
                f"v17 runtime {package} differs from requirements-lock.txt"
            )
    if tuple(map(int, platform.python_version_tuple()[:2])) < (3, 11):
        raise PairsReportContractError("v17 report requires Python >=3.11")


def _validate_v17_header(
    raw: Mapping[str, Any],
    prereg: Mapping[str, Any],
    *,
    prereg_sha256: str,
    canonical_prereg_path: Path,
    repo_root: Path,
) -> None:
    if raw.get("schema_version") != V17_RAW_SCHEMA:
        raise PairsReportContractError("unsupported v17 raw schema")
    if raw.get("mode") != FULL_REPLAY_MODE or raw.get("partition") != "primary":
        raise PairsReportContractError("v17 evidence must be a full frozen primary replay")
    _exact_bool(raw.get("evidence_eligible"), True, name="v17.evidence_eligible")
    if raw.get("evidence_ineligible_reasons") != []:
        raise PairsReportContractError("v17 evidence ineligible reasons must be empty")
    if tuple(_list(raw.get("candidate_ids"), name="v17.candidate_ids")) != tuple(
        FROZEN_V17_CANDIDATE_IDS
    ):
        raise PairsReportContractError("v17 candidate IDs/order differ from the frozen contract")
    if raw.get("candidate_count") != len(FROZEN_V17_CANDIDATE_IDS):
        raise PairsReportContractError("v17 candidate count mismatch")
    if tuple(_list(raw.get("scenario_order"), name="v17.scenario_order")) != SCENARIO_ORDER:
        raise PairsReportContractError("v17 scenario order mismatch")
    registration = _mapping(raw.get("preregistration"), name="v17.preregistration")
    if (
        registration.get("sha256") != prereg_sha256
        or registration.get("schema_version") != PREREG_SCHEMA
        or registration.get("status") != "PREREGISTERED_NO_RESULTS_SEEN"
    ):
        raise PairsReportContractError("v17 preregistration provenance mismatch")
    _exact_bool(
        registration.get("live_deployment_authorized"),
        False,
        name="v17 prereg live authorization",
    )
    snapshots = _mapping(raw.get("snapshots"), name="v17.snapshots")
    for snapshot_name in ("market", "funding"):
        _snapshot_contract(
            _mapping(snapshots.get(snapshot_name), name=f"v17.{snapshot_name}"),
            prereg,
            name=f"v17.{snapshot_name}",
        )
    _validate_runner_provenance(
        raw,
        prereg_sha256=prereg_sha256,
        canonical_prereg_path=canonical_prereg_path,
        repo_root=repo_root,
    )
    _validate_runtime_versions(raw, repo_root=repo_root)
    postflight = _mapping(
        _mapping(raw.get("execution_governance"), name="execution_governance").get(
            "postflight_snapshots"
        ),
        name="postflight_snapshots",
    )
    for snapshot_name in ("market", "funding"):
        _snapshot_contract(
            _mapping(postflight.get(snapshot_name), name=f"postflight.{snapshot_name}"),
            prereg,
            name=f"postflight.{snapshot_name}",
        )


def _validate_v16_header(artifact: JsonArtifact, prereg: Mapping[str, Any]) -> None:
    raw = artifact.payload
    parent = _mapping(prereg.get("batch1_parent_evidence"), name="batch1_parent_evidence")
    if artifact.compression != "gzip":
        raise PairsReportContractError("frozen v16 parent evidence must be gzip")
    if artifact.file_sha256 != parent.get("gzip_sha256"):
        raise PairsReportContractError("v16 gzip SHA256 differs from preregistration")
    if artifact.decoded_json_sha256 != parent.get("raw_json_sha256"):
        raise PairsReportContractError("v16 decoded JSON SHA256 differs from preregistration")
    if parent.get("verdict") != "RED_ALL_SIX_CELLS":
        raise PairsReportContractError("v16 parent verdict changed")
    if raw.get("schema_version") != V16_RAW_SCHEMA or raw.get("mode") != FULL_REPLAY_MODE:
        raise PairsReportContractError("unsupported v16 parent raw schema/mode")
    _exact_bool(raw.get("evidence_eligible"), True, name="v16.evidence_eligible")
    if raw.get("evidence_ineligible_reasons") != []:
        raise PairsReportContractError("v16 evidence ineligible reasons must be empty")
    if tuple(_list(raw.get("candidate_ids"), name="v16.candidate_ids")) != tuple(
        FROZEN_V16_CANDIDATE_IDS
    ):
        raise PairsReportContractError("v16 candidate IDs/order differ from frozen contract")
    if raw.get("candidate_count") != len(FROZEN_V16_CANDIDATE_IDS):
        raise PairsReportContractError("v16 candidate count mismatch")
    if tuple(_list(raw.get("scenario_order"), name="v16.scenario_order")) != SCENARIO_ORDER:
        raise PairsReportContractError("v16 scenario order mismatch")
    snapshots = _mapping(raw.get("snapshots"), name="v16.snapshots")
    for snapshot_name in ("market", "funding"):
        _snapshot_contract(
            _mapping(snapshots.get(snapshot_name), name=f"v16.{snapshot_name}"),
            prereg,
            name=f"v16.{snapshot_name}",
        )
    source = _mapping(raw.get("source_provenance"), name="v16.source_provenance")
    _exact_bool(source.get("research_source_clean"), True, name="v16 research source clean")
    if source.get("research_source_status") != []:
        raise PairsReportContractError("v16 research source status must be empty")


def _filter_records(
    records: Any,
    *,
    timestamp_field: str,
    start: pd.Timestamp,
    end: pd.Timestamp,
    name: str,
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for index, raw in enumerate(_list(records, name=name)):
        record = _mapping(raw, name=f"{name}[{index}]")
        timestamp = _utc(record.get(timestamp_field), name=f"{name}[{index}].{timestamp_field}")
        if start <= timestamp < end:
            result.append(record)
    return result


def _validate_nested_candidate_ids(value: Any, *, expected: str, name: str) -> int:
    """Require every nested candidate_id to agree with its outer cell."""

    found = 0
    if isinstance(value, Mapping):
        if "candidate_id" in value:
            found += 1
            if value["candidate_id"] != expected:
                raise PairsReportContractError(f"{name} contains a foreign candidate_id")
        for key, item in value.items():
            found += _validate_nested_candidate_ids(item, expected=expected, name=f"{name}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            found += _validate_nested_candidate_ids(
                item, expected=expected, name=f"{name}[{index}]"
            )
    return found


def _validate_scenario_hashes(scenario: Mapping[str, Any], *, candidate: str, name: str) -> None:
    for field in (
        "closed_episode_ledger",
        "terminal_episode_ledger",
        "economic_episode_ledger",
        "rejections",
    ):
        _assert_payload_hash(scenario, field, name=name)
        records = _list(scenario.get(field), name=f"{name}.{field}")
        _validate_nested_candidate_ids(records, expected=candidate, name=f"{name}.{field}")
        if field in {
            "closed_episode_ledger",
            "terminal_episode_ledger",
            "economic_episode_ledger",
        } and any(
            not isinstance(item, Mapping) or item.get("candidate_id") != candidate
            for item in records
        ):
            raise PairsReportContractError(f"{name}.{field} rows must carry outer candidate_id")
    if scenario.get("economic_terminal_rows_are_closed_samples") is not False:
        raise PairsReportContractError(f"{name} terminal sample flag must be false")


def _equity_curve_series(scenario: Mapping[str, Any], *, name: str) -> pd.Series:
    ledger = _list(scenario.get("equity_curve_ledger"), name=f"{name}.equity_curve_ledger")
    expected_hash = scenario.get("equity_curve_sha256")
    if (
        not isinstance(expected_hash, str)
        or len(expected_hash) != _SHA256_LENGTH
        or any(character not in "0123456789abcdef" for character in expected_hash)
    ):
        raise PairsReportContractError(f"{name} equity curve hash invalid")
    if _canonical_hash(ledger) != expected_hash:
        raise PairsReportContractError(f"{name} equity curve ledger hash mismatch")
    timestamps: list[pd.Timestamp] = []
    nav_values: list[float] = []
    for index, raw in enumerate(ledger):
        row = _list(raw, name=f"{name}.equity_curve_ledger[{index}]")
        if len(row) != 2:
            raise PairsReportContractError("equity curve rows must be [UTC timestamp, NAV]")
        timestamps.append(_utc(row[0], name=f"{name}.equity_curve[{index}].timestamp"))
        nav_values.append(_finite(row[1], name=f"{name}.equity_curve[{index}].NAV", positive=True))
    index = pd.DatetimeIndex(timestamps, name="timestamp")
    if index.empty or index.has_duplicates or not index.is_monotonic_increasing:
        raise PairsReportContractError("equity curve must be non-empty, unique and chronological")
    return pd.Series(nav_values, index=index, dtype=float, name="NAV")


def _reconcile_windows_to_equity_curve(
    curve: pd.Series,
    *,
    parsed_windows: Mapping[str, Mapping[str, Any]],
    initial_equity: float,
    closed: Sequence[Mapping[str, Any]],
    terminal: Sequence[Mapping[str, Any]],
    name: str,
) -> None:
    complete_start = _utc(
        parsed_windows["complete"]["start_inclusive"], name="complete curve start"
    )
    complete_end = _utc(parsed_windows["complete"]["end_exclusive"], name="complete curve end")
    if curve.index[0] < complete_start or curve.index[-1] >= complete_end:
        raise PairsReportContractError(f"{name} equity curve lies outside complete window")

    closed_intervals = [
        (
            _utc(item.get("entry_ts"), name="closed active entry"),
            _utc(item.get("exit_ts"), name="closed active exit"),
        )
        for item in closed
    ]
    terminal_intervals = [
        (
            _utc(item.get("entry_ts"), name="terminal active entry"),
            _utc(item.get("exit_ts"), name="terminal active exit"),
        )
        for item in terminal
    ]
    for window_name, window in parsed_windows.items():
        start = _utc(window["start_inclusive"], name=f"{window_name}.curve start")
        end = _utc(window["end_exclusive"], name=f"{window_name}.curve end")
        before = curve.loc[curve.index < start]
        baseline = float(before.iloc[-1]) if not before.empty else initial_equity
        pre_window_peak = max(
            initial_equity, float(before.max()) if not before.empty else initial_equity
        )
        values = curve.loc[(curve.index >= start) & (curve.index < end)]
        if values.empty:
            raise PairsReportContractError(f"{name}.{window_name} has no equity observations")
        _same_number(
            float(window["baseline_equity"]), baseline, name=f"{name}.{window_name}.curve baseline"
        )
        _same_number(
            float(window["pre_window_peak_equity"]),
            pre_window_peak,
            name=f"{name}.{window_name}.curve pre-window peak",
        )
        _same_number(
            float(window["ending_equity"]),
            float(values.iloc[-1]),
            name=f"{name}.{window_name}.curve ending",
        )
        if int(window["equity_observations"]) != len(values):
            raise PairsReportContractError(f"{name}.{window_name} curve observation count mismatch")
        _same_number(
            float(window["nav_observation_sum"]),
            float(values.sum()),
            name=f"{name}.{window_name}.curve NAV sum",
        )
        _same_number(
            float(window["arithmetic_mean_15m_nav"]),
            float(values.mean()),
            name=f"{name}.{window_name}.curve NAV mean",
        )

        periods = values.index.tz_localize(None).to_period("M")
        expected_months = window["_returns"].index
        month_end = values.groupby(periods).last().reindex(expected_months).ffill().fillna(baseline)
        previous = month_end.shift(1)
        previous.iloc[0] = baseline
        reconstructed_returns = (month_end / previous - 1.0) * 100.0
        reconstructed_pnl = month_end - previous
        if not np.allclose(
            reconstructed_returns.to_numpy(dtype=float),
            window["_returns"].to_numpy(dtype=float),
            rtol=1e-12,
            atol=1e-10,
        ) or not np.allclose(
            reconstructed_pnl.to_numpy(dtype=float),
            window["_pnl"].to_numpy(dtype=float),
            rtol=1e-12,
            atol=1e-8,
        ):
            raise PairsReportContractError(
                f"{name}.{window_name} monthly returns/PnL disagree with equity curve"
            )

        running_peak = pre_window_peak
        maximum_drawdown = 0.0
        for nav in values.to_numpy(dtype=float):
            running_peak = max(running_peak, nav)
            maximum_drawdown = max(maximum_drawdown, (running_peak - nav) / running_peak * 100.0)
        _same_number(
            float(window["max_mtm_drawdown_pct"]),
            maximum_drawdown,
            name=f"{name}.{window_name}.curve max drawdown",
        )
        recovery_peak = pre_window_peak
        current_recovery = 0
        maximum_recovery = 0
        for nav in month_end.to_numpy(dtype=float):
            if nav >= recovery_peak - 1e-12:
                recovery_peak = max(recovery_peak, nav)
                current_recovery = 0
            else:
                current_recovery += 1
                maximum_recovery = max(maximum_recovery, current_recovery)
        if int(window["max_recovery_months"]) != maximum_recovery:
            raise PairsReportContractError(
                f"{name}.{window_name} recovery disagrees with equity curve"
            )

        active_delta = np.zeros(len(values) + 1, dtype=np.int64)
        for entry, exit_ts in closed_intervals:
            left = int(values.index.searchsorted(entry, side="left"))
            right = int(values.index.searchsorted(exit_ts, side="left"))
            if left < right:
                active_delta[left] += 1
                active_delta[right] -= 1
        for entry, exit_ts in terminal_intervals:
            left = int(values.index.searchsorted(entry, side="left"))
            right = int(values.index.searchsorted(exit_ts, side="right"))
            if left < right:
                active_delta[left] += 1
                active_delta[right] -= 1
        active_observations = np.cumsum(active_delta[:-1]) > 0
        observation_months = values.index.tz_localize(None).to_period("M")
        active_by_month = (
            pd.Series(active_observations, index=observation_months)
            .groupby(level=0)
            .any()
            .reindex(expected_months, fill_value=False)
        )
        expected_active = {str(month): bool(value) for month, value in active_by_month.items()}
        if window["monthly_active_exposure"] != expected_active or int(
            window["active_months"]
        ) != sum(expected_active.values()):
            raise PairsReportContractError(
                f"{name}.{window_name} active exposure disagrees with equity curve and episodes"
            )


def _scenario_semantics(
    scenario: Mapping[str, Any],
    *,
    candidate: str,
    scenario_name: str,
    stream_contract: Mapping[str, Any],
    primary_symbols: set[str],
    parsed_windows: Mapping[str, Mapping[str, Any]],
    prereg: Mapping[str, Any],
) -> None:
    """Reconcile engine aggregates and the exact episode tagged union."""

    closed = [
        _mapping(item, name=f"{candidate}.{scenario_name}.closed")
        for item in _list(
            scenario.get("closed_episode_ledger"),
            name=f"{candidate}.{scenario_name}.closed_episode_ledger",
        )
    ]
    terminal = [
        _mapping(item, name=f"{candidate}.{scenario_name}.terminal")
        for item in _list(
            scenario.get("terminal_episode_ledger"),
            name=f"{candidate}.{scenario_name}.terminal_episode_ledger",
        )
    ]
    intent_by_key = _mapping(
        stream_contract.get("intent_by_key"), name=f"{candidate}.intent contract"
    )
    seen_episode_keys: set[tuple[str, pd.Timestamp, pd.Timestamp]] = set()

    def validate_episode(record: Mapping[str, Any], *, is_terminal: bool) -> None:
        pair_id = record.get("pair_id")
        selection_ts = _utc(
            record.get("selection_ts"), name=f"{candidate}.{scenario_name}.selection_ts"
        )
        entry_ts = _utc(record.get("entry_ts"), name=f"{candidate}.{scenario_name}.entry_ts")
        exit_ts = _utc(record.get("exit_ts"), name=f"{candidate}.{scenario_name}.exit_ts")
        _pair_symbols(
            pair_id,
            primary_symbols=primary_symbols,
            name=f"{candidate}.{scenario_name}.episode",
            y_symbol=record.get("y_symbol"),
            x_symbol=record.get("x_symbol"),
        )
        key = (str(pair_id), selection_ts, entry_ts)
        if key not in intent_by_key:
            raise PairsReportContractError(
                f"{candidate}.{scenario_name} episode has no matching frozen entry intent"
            )
        intent = intent_by_key[key]
        if (record.get("y_symbol"), record.get("x_symbol")) != (
            intent.get("y_symbol"),
            intent.get("x_symbol"),
        ):
            raise PairsReportContractError(
                f"{candidate}.{scenario_name} episode symbols disagree with entry intent"
            )
        regime = record.get("entry_regime")
        y_side = record.get("y_side")
        x_side = record.get("x_side")
        expected_sides = {
            "high_spread": ("short", "long"),
            "low_spread": ("long", "short"),
        }
        if regime not in expected_sides or (y_side, x_side) != expected_sides[regime]:
            raise PairsReportContractError(
                f"{candidate}.{scenario_name} episode spread regime/sides are invalid"
            )
        signal_z = _finite(intent.get("z_score"), name="intent signal z")
        intended_regime = (
            "high_spread" if signal_z > 0.0 else "low_spread" if signal_z < 0.0 else None
        )
        if (
            intended_regime is None
            or regime != intended_regime
            or (
                y_side,
                x_side,
            )
            != expected_sides[intended_regime]
            or (y_side, x_side)
            != (
                intent.get("y_side"),
                intent.get("x_side"),
            )
        ):
            raise PairsReportContractError(
                f"{candidate}.{scenario_name} episode regime/sides disagree with intent z"
            )
        y_quantity = abs(_finite(record.get("y_quantity"), name="y quantity"))
        x_quantity = abs(_finite(record.get("x_quantity"), name="x quantity"))
        y_entry_price = _finite(record.get("y_entry_price"), name="y entry price", positive=True)
        x_entry_price = _finite(record.get("x_entry_price"), name="x entry price", positive=True)
        y_exit_price = _finite(record.get("y_exit_price"), name="y exit price", positive=True)
        x_exit_price = _finite(record.get("x_exit_price"), name="x exit price", positive=True)
        y_entry_notional = _finite(
            record.get("y_entry_notional"), name="y entry notional", positive=True
        )
        x_entry_notional = _finite(
            record.get("x_entry_notional"), name="x entry notional", positive=True
        )
        _same_number(y_entry_notional, y_quantity * y_entry_price, name="y entry notional identity")
        _same_number(x_entry_notional, x_quantity * x_entry_price, name="x entry notional identity")
        gross_exposure = _finite(record.get("gross_exposure"), name="gross exposure", positive=True)
        _same_number(
            gross_exposure,
            y_entry_notional + x_entry_notional,
            name="gross exposure identity",
        )
        y_weight = _finite(record.get("gross_weight_y"), name="y gross weight", positive=True)
        x_weight = _finite(record.get("gross_weight_x"), name="x gross weight", positive=True)
        _same_number(y_weight + x_weight, 1.0, name="gross weight sum")
        _same_number(y_weight, y_entry_notional / gross_exposure, name="y gross weight")
        _same_number(x_weight, x_entry_notional / gross_exposure, name="x gross weight")
        for field in ("alpha", "beta", "validation_mean", "validation_std"):
            _same_number(
                _finite(record.get(field), name=f"episode {field}"),
                _finite(intent.get(field), name=f"intent {field}"),
                name=f"episode/intent {field}",
            )
        _same_number(
            y_weight,
            _finite(intent.get("gross_weight_y"), name="intent y gross weight"),
            name="episode/intent y gross weight",
        )
        _same_number(
            x_weight,
            _finite(intent.get("gross_weight_x"), name="intent x gross weight"),
            name="episode/intent x gross weight",
        )
        alpha = _finite(record.get("alpha"), name="episode alpha")
        beta = _finite(record.get("beta"), name="episode beta", positive=True)
        validation_mean = _finite(record.get("validation_mean"), name="validation mean")
        validation_std = _finite(record.get("validation_std"), name="validation std", positive=True)
        reconstructed_fill_z = (
            math.log(y_entry_price) - alpha - beta * math.log(x_entry_price) - validation_mean
        ) / validation_std
        fill_z = _finite(record.get("fill_z"), name="fill z")
        _same_number(fill_z, reconstructed_fill_z, name="fill z from entry prices")
        _same_number(_finite(record.get("entry_z"), name="entry z"), fill_z, name="entry/fill z")
        _same_number(
            _finite(record.get("signal_z"), name="episode signal z"),
            signal_z,
            name="episode/intent signal z",
        )
        exit_abs_z = _finite(intent.get("exit_abs_z"), name="intent exit z", positive=True)
        reconstructed_expected = (abs(fill_z) - exit_abs_z) * validation_std / (1.0 + beta)
        _same_number(
            _finite(record.get("expected_convergence_return"), name="fill expected return"),
            reconstructed_expected,
            name="fill expected convergence identity",
        )
        _same_number(
            _finite(
                record.get("signal_expected_convergence_return"),
                name="signal expected return",
            ),
            _finite(intent.get("expected_convergence_return"), name="intent expected return"),
            name="signal expected convergence identity",
        )
        adverse_funding = _finite(
            intent.get("adverse_funding"), name="intent adverse funding", nonnegative=True
        )
        _same_number(
            _finite(record.get("adverse_funding"), name="episode adverse funding"),
            adverse_funding,
            name="episode/intent adverse funding",
        )
        economic_buffer = _finite(
            intent.get("economic_buffer_multiplier"), name="economic buffer", positive=True
        )
        base_cost = _finite(
            intent.get("base_round_trip_cost_per_gross"), name="intent base cost", nonnegative=True
        )
        c2_cost = _finite(
            intent.get("c2_round_trip_cost_per_gross"), name="intent C2 cost", nonnegative=True
        )
        reconstructed_stressed = economic_buffer * max(
            c2_cost + 2.0 * adverse_funding,
            2.0 * (base_cost + adverse_funding),
        )
        _same_number(
            _finite(record.get("stressed_required_return"), name="fill stressed return"),
            reconstructed_stressed,
            name="fill stressed cost identity",
        )
        _same_number(
            _finite(record.get("signal_stressed_required_return"), name="signal stressed return"),
            _finite(intent.get("stressed_required_return"), name="intent stressed return"),
            name="signal stressed cost identity",
        )
        y_direction = 1.0 if y_side == "long" else -1.0
        x_direction = 1.0 if x_side == "long" else -1.0
        reconstructed_gross_price_pnl = (
            y_direction * (y_exit_price - y_entry_price) * y_quantity
            + x_direction * (x_exit_price - x_entry_price) * x_quantity
        )
        gross_price_pnl = _finite(record.get("gross_pair_price_pnl"), name="gross pair price PnL")
        _same_number(
            gross_price_pnl,
            reconstructed_gross_price_pnl,
            name="gross pair price PnL identity",
        )
        payoff_multiplier = _finite(
            record.get("payoff_multiplier"), name="payoff multiplier", positive=True
        )
        expected_multiplier = (
            (0.50 if gross_price_pnl > 0.0 else 1.25 if gross_price_pnl < 0.0 else 1.0)
            if scenario_name == "H"
            else 1.0
        )
        _same_number(payoff_multiplier, expected_multiplier, name="scenario payoff multiplier")
        adjusted_price_pnl = _finite(
            record.get("adjusted_pair_price_pnl"), name="adjusted pair price PnL"
        )
        _same_number(
            adjusted_price_pnl,
            gross_price_pnl * payoff_multiplier,
            name="adjusted pair price PnL identity",
        )
        execution_component_fields = (
            "y_entry_fee",
            "y_entry_spread_slippage",
            "y_entry_impact",
            "x_entry_fee",
            "x_entry_spread_slippage",
            "x_entry_impact",
            "y_exit_fee",
            "y_exit_spread_slippage",
            "y_exit_impact",
            "x_exit_fee",
            "x_exit_spread_slippage",
            "x_exit_impact",
        )
        component_cost = sum(
            _finite(record.get(field), name=field, nonnegative=True)
            for field in execution_component_fields
        )
        execution_cost = _finite(
            record.get("execution_cost"), name="execution cost", nonnegative=True
        )
        _same_number(execution_cost, component_cost, name="execution component identity")
        cost_spec = _mapping(
            _mapping(prereg.get("risk_and_execution"), name="risk_and_execution").get(
                "execution_costs_bps_per_leg"
            ),
            name="execution cost spec",
        )
        scenario_spec = _mapping(
            _mapping(prereg["risk_and_execution"].get("cost_scenarios"), name="cost scenarios").get(
                scenario_name
            ),
            name=f"{scenario_name} cost scenario",
        )
        cost_multiplier = _finite(
            scenario_spec.get("cost_multiplier"), name="scenario cost multiplier", positive=True
        )
        leg_fill_notionals = {
            "y_entry": y_entry_notional,
            "x_entry": x_entry_notional,
            "y_exit": y_quantity * y_exit_price,
            "x_exit": x_quantity * x_exit_price,
        }
        component_bps = {
            "fee": _finite(cost_spec.get("fee"), name="fee bps", nonnegative=True),
            "spread_slippage": _finite(
                cost_spec.get("spread_and_slippage"),
                name="spread/slippage bps",
                nonnegative=True,
            ),
            "impact": _finite(cost_spec.get("impact"), name="impact bps", nonnegative=True),
        }
        for leg_fill, notional in leg_fill_notionals.items():
            for component, bps in component_bps.items():
                field = f"{leg_fill}_{component}"
                _same_number(
                    _finite(record.get(field), name=field, nonnegative=True),
                    notional * bps * cost_multiplier / 10_000.0,
                    name=f"{field} canonical bps identity",
                )
        funding_cashflow = _finite(
            record.get("y_funding_cashflow"), name="y funding cashflow"
        ) + _finite(record.get("x_funding_cashflow"), name="x funding cashflow")
        _same_number(
            _finite(record.get("net_pnl"), name="episode net PnL"),
            adjusted_price_pnl - execution_cost + funding_cashflow,
            name="episode net PnL identity",
        )
        if key in seen_episode_keys:
            raise PairsReportContractError(
                f"{candidate}.{scenario_name} duplicates one entry across ledgers"
            )
        seen_episode_keys.add(key)
        if is_terminal:
            if record.get("exit_reason") != "terminal_open_mtm":
                raise PairsReportContractError("terminal ledger row has a non-terminal reason")
            expected_cutoff = _H_END - pd.Timedelta(minutes=15)
            if exit_ts != expected_cutoff:
                raise PairsReportContractError(
                    "terminal ledger must use the final completed 15m cutoff"
                )
            if entry_ts > exit_ts:
                raise PairsReportContractError("terminal episode entry is after cutoff")
        else:
            if record.get("exit_reason") == "terminal_open_mtm":
                raise PairsReportContractError("closed ledger contains a terminal pseudo episode")
            if entry_ts >= exit_ts:
                raise PairsReportContractError("closed episode must exit after entry")

    for record in closed:
        validate_episode(record, is_terminal=False)
    for record in terminal:
        validate_episode(record, is_terminal=True)

    economic = [
        _mapping(item, name=f"{candidate}.{scenario_name}.economic")
        for item in _list(
            scenario.get("economic_episode_ledger"),
            name=f"{candidate}.{scenario_name}.economic_episode_ledger",
        )
    ]
    expected_economic: list[dict[str, Any]] = []
    for record, kind, is_closed in (
        *[(record, "closed", True) for record in closed],
        *[(record, "terminal_open_mtm", False) for record in terminal],
    ):
        expected = dict(record)
        expected["episode_kind"] = kind
        expected["is_closed_sample"] = is_closed
        expected["funding_cashflow"] = _finite(
            record.get("y_funding_cashflow"), name="y funding cashflow"
        ) + _finite(record.get("x_funding_cashflow"), name="x funding cashflow")
        expected_economic.append(expected)
    if economic != expected_economic:
        raise PairsReportContractError(
            f"{candidate}.{scenario_name} economic ledger is not the exact closed+terminal union"
        )

    rejections = [
        _mapping(item, name=f"{candidate}.{scenario_name}.rejection")
        for item in _list(
            scenario.get("rejections"), name=f"{candidate}.{scenario_name}.rejections"
        )
    ]
    rejection_keys: set[tuple[str, pd.Timestamp, pd.Timestamp]] = set()
    for rejection in rejections:
        pair_id = rejection.get("pair_id")
        selection_ts = _utc(rejection.get("selection_ts"), name="rejection.selection_ts")
        entry_ts = _utc(rejection.get("entry_ts"), name="rejection.entry_ts")
        _pair_symbols(
            pair_id,
            primary_symbols=primary_symbols,
            name=f"{candidate}.{scenario_name}.rejection",
        )
        key = (str(pair_id), selection_ts, entry_ts)
        if key not in intent_by_key:
            raise PairsReportContractError("engine rejection has no matching entry intent")
        if key in rejection_keys or key in seen_episode_keys:
            raise PairsReportContractError("one intent has duplicate or conflicting outcomes")
        rejection_keys.add(key)
    if seen_episode_keys.union(rejection_keys) != set(intent_by_key):
        raise PairsReportContractError(
            f"{candidate}.{scenario_name} outcomes do not partition every entry intent"
        )
    expected_rejection_counts = dict(
        sorted(Counter(str(item.get("reason")) for item in rejections).items())
    )
    if scenario.get("rejection_counts") != expected_rejection_counts:
        raise PairsReportContractError(f"{candidate}.{scenario_name} rejection counts mismatch")

    complete = parsed_windows["complete"]
    engine_returns = _list(
        scenario.get("engine_monthly_returns"),
        name=f"{candidate}.{scenario_name}.engine_monthly_returns",
    )
    expected_months = tuple(str(month) for month in complete["_returns"].index)
    actual_months: list[str] = []
    actual_returns: list[float] = []
    for index, raw in enumerate(engine_returns):
        point = _mapping(raw, name=f"engine_monthly_returns[{index}]")
        actual_months.append(str(point.get("month")))
        actual_returns.append(
            _finite(point.get("return_pct"), name=f"engine_monthly_returns[{index}].return")
        )
    if tuple(actual_months) != expected_months or not np.allclose(
        actual_returns,
        complete["_returns"].to_numpy(dtype=float),
        rtol=1e-12,
        atol=1e-12,
    ):
        raise PairsReportContractError(
            f"{candidate}.{scenario_name} engine monthly returns disagree with complete window"
        )
    _same_number(
        _finite(scenario.get("initial_equity"), name="scenario initial equity", positive=True),
        float(complete["baseline_equity"]),
        name=f"{candidate}.{scenario_name}.initial equity",
    )
    _same_number(
        _finite(scenario.get("final_equity"), name="scenario final equity"),
        float(complete["ending_equity"]),
        name=f"{candidate}.{scenario_name}.final equity",
    )
    _same_number(
        _finite(
            scenario.get("max_mtm_drawdown_pct"),
            name="scenario max drawdown",
            nonnegative=True,
        ),
        float(complete["max_mtm_drawdown_pct"]),
        name=f"{candidate}.{scenario_name}.max drawdown",
    )
    if (
        _integer(
            scenario.get("equity_curve_observations"),
            name="scenario equity observations",
            minimum=1,
        )
        != complete["equity_observations"]
    ):
        raise PairsReportContractError(
            f"{candidate}.{scenario_name} equity observation count mismatch"
        )
    curve = _equity_curve_series(scenario, name=f"{candidate}.{scenario_name}")
    if len(curve) != complete["equity_observations"]:
        raise PairsReportContractError(
            f"{candidate}.{scenario_name} equity curve ledger length mismatch"
        )
    _reconcile_windows_to_equity_curve(
        curve,
        parsed_windows=parsed_windows,
        initial_equity=float(complete["baseline_equity"]),
        closed=closed,
        terminal=terminal,
        name=f"{candidate}.{scenario_name}",
    )
    open_pairs = _integer(scenario.get("open_pair_count"), name="open_pair_count")
    open_legs = _integer(scenario.get("open_leg_count"), name="open_leg_count")
    if open_pairs != len(terminal) or open_legs != 2 * open_pairs:
        raise PairsReportContractError(f"{candidate}.{scenario_name} open pair/leg count mismatch")
    quarantined = _list(
        scenario.get("quarantined_pairs"), name=f"{candidate}.{scenario_name}.quarantined"
    )
    for index, raw_pair in enumerate(quarantined):
        item = _list(raw_pair, name=f"quarantined_pairs[{index}]")
        if len(item) != 2 or item[0] != candidate:
            raise PairsReportContractError("quarantined pair candidate mismatch")
        _pair_symbols(
            item[1],
            primary_symbols=primary_symbols,
            name=f"{candidate}.{scenario_name}.quarantined pair",
        )
    accrued_exit_cost = _finite(
        scenario.get("accrued_exit_cost"), name="accrued exit cost", nonnegative=True
    )
    ledger_execution = sum(
        _finite(item.get("execution_cost"), name="episode execution cost", nonnegative=True)
        for item in [*closed, *terminal]
    )
    _same_number(
        ledger_execution,
        _finite(
            scenario.get("total_execution_cost"),
            name="scenario total execution cost",
            nonnegative=True,
        )
        + accrued_exit_cost,
        name=f"{candidate}.{scenario_name}.execution cost",
    )
    ledger_funding = sum(
        _finite(item.get("y_funding_cashflow"), name="y funding")
        + _finite(item.get("x_funding_cashflow"), name="x funding")
        for item in [*closed, *terminal]
    )
    _same_number(
        ledger_funding,
        _finite(scenario.get("total_funding_cashflow"), name="scenario total funding"),
        name=f"{candidate}.{scenario_name}.funding cashflow",
    )
    ledger_net_pnl = sum(
        _finite(item.get("net_pnl"), name="episode net PnL") for item in [*closed, *terminal]
    )
    _same_number(
        ledger_net_pnl,
        float(complete["ending_equity"]) - float(complete["baseline_equity"]),
        name=f"{candidate}.{scenario_name}.ledger net PnL to NAV identity",
    )
    for window_name, window in parsed_windows.items():
        start = _utc(window["start_inclusive"], name=f"{window_name}.start")
        end = _utc(window["end_exclusive"], name=f"{window_name}.end")
        closed_window = [
            item for item in closed if start <= _utc(item.get("exit_ts"), name="exit_ts") < end
        ]
        terminal_window = [
            item
            for item in terminal
            if start <= _utc(item.get("exit_ts"), name="terminal exit_ts") < end
        ]
        if (
            len(closed_window) != window["closed_pair_episodes"]
            or len(terminal_window) != window["terminal_open_pair_pseudo_episodes"]
        ):
            raise PairsReportContractError(
                f"{candidate}.{scenario_name}.{window_name} episode count mismatch"
            )
        if (
            sum(item.get("entry_regime") == "high_spread" for item in closed_window)
            != window["high_spread_closed_episodes"]
            or sum(item.get("entry_regime") == "low_spread" for item in closed_window)
            != window["low_spread_closed_episodes"]
        ):
            raise PairsReportContractError(
                f"{candidate}.{scenario_name}.{window_name} regime count mismatch"
            )


def _turnover(
    scenario: Mapping[str, Any],
    window: Mapping[str, Any],
    *,
    start: pd.Timestamp,
    end: pd.Timestamp,
    name: str,
) -> dict[str, float | int]:
    closed_all = [
        _mapping(item, name=f"{name}.closed")
        for item in _list(scenario.get("closed_episode_ledger"), name=f"{name}.closed")
    ]
    terminal_all = [
        _mapping(item, name=f"{name}.terminal")
        for item in _list(scenario.get("terminal_episode_ledger"), name=f"{name}.terminal")
    ]
    entry_gross = 0.0
    entry_count = 0
    for record in (*closed_all, *terminal_all):
        entry_ts = _utc(record.get("entry_ts"), name=f"{name}.entry_ts")
        if start <= entry_ts < end:
            y = _finite(
                record.get("y_entry_notional"), name=f"{name}.y_entry_notional", nonnegative=True
            )
            x = _finite(
                record.get("x_entry_notional"), name=f"{name}.x_entry_notional", nonnegative=True
            )
            gross = _finite(
                record.get("gross_exposure"), name=f"{name}.gross_exposure", positive=True
            )
            _same_number(y + x, gross, name=f"{name}.entry gross")
            entry_gross += y + x
            entry_count += 1

    def exit_notional(record: Mapping[str, Any]) -> float:
        y_quantity = abs(_finite(record.get("y_quantity"), name=f"{name}.y_quantity"))
        x_quantity = abs(_finite(record.get("x_quantity"), name=f"{name}.x_quantity"))
        y_price = _finite(record.get("y_exit_price"), name=f"{name}.y_exit_price", positive=True)
        x_price = _finite(record.get("x_exit_price"), name=f"{name}.x_exit_price", positive=True)
        return y_quantity * y_price + x_quantity * x_price

    closed_exit_gross = 0.0
    closed_exit_count = 0
    for record in closed_all:
        exit_ts = _utc(record.get("exit_ts"), name=f"{name}.closed.exit_ts")
        if start <= exit_ts < end:
            closed_exit_gross += exit_notional(record)
            closed_exit_count += 1
    terminal_liquidation_gross = 0.0
    terminal_count = 0
    for record in terminal_all:
        exit_ts = _utc(record.get("exit_ts"), name=f"{name}.terminal.exit_ts")
        if start <= exit_ts < end:
            terminal_liquidation_gross += exit_notional(record)
            terminal_count += 1

    denominator = _finite(
        window.get("arithmetic_mean_15m_nav"), name=f"{name}.turnover denominator", positive=True
    )
    observations = _integer(
        window.get("equity_observations"), name=f"{name}.turnover observations", minimum=1
    )
    nav_sum = _finite(
        window.get("nav_observation_sum"), name=f"{name}.turnover NAV sum", positive=True
    )
    _same_number(denominator, nav_sum / observations, name=f"{name}.turnover denominator")
    numerator = entry_gross + closed_exit_gross + terminal_liquidation_gross
    return {
        "entry_fill_gross_notional": entry_gross,
        "entry_fill_count": entry_count,
        "closed_exit_fill_gross_notional": closed_exit_gross,
        "closed_exit_count": closed_exit_count,
        "terminal_accrued_liquidation_gross_notional": terminal_liquidation_gross,
        "terminal_pair_count": terminal_count,
        "filled_gross_notional_numerator": numerator,
        "arithmetic_mean_15m_nav_denominator": denominator,
        "nav_observations": observations,
        "filled_gross_turnover": numerator / denominator,
    }


def _safe_ratio(numerator: float, denominator: float) -> float | None:
    if not math.isfinite(numerator) or not math.isfinite(denominator) or denominator <= 0.0:
        return None
    value = numerator / denominator
    return float(value) if math.isfinite(value) else None


def _json_safe(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_json_safe(item) for item in value]
    if isinstance(value, np.bool_):
        return bool(value)
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating | float):
        parsed = float(value)
        return parsed if math.isfinite(parsed) else None
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if isinstance(value, pd.Period):
        return str(value)
    return value


def _scenario_windows(
    scenario: Mapping[str, Any],
    *,
    candidate: str,
    scenario_name: str,
    windows: Mapping[str, tuple[pd.Timestamp, pd.Timestamp]],
) -> dict[str, dict[str, Any]]:
    raw_windows = _mapping(scenario.get("windows"), name=f"{candidate}.{scenario_name}.windows")
    if set(raw_windows) != set(windows) or len(raw_windows) != len(windows):
        raise PairsReportContractError(
            f"{candidate}.{scenario_name} window IDs differ from preregistration"
        )
    parsed = {
        name: _window_payload(
            raw_windows[name],
            name=f"{candidate}.{scenario_name}.{name}",
            start=bounds[0],
            end=bounds[1],
        )
        for name, bounds in windows.items()
    }
    complete_returns = parsed["complete"]["_returns"]
    complete_pnl = parsed["complete"]["_pnl"]
    for window_name, window in parsed.items():
        for month, value in window["_returns"].items():
            _same_number(
                float(value),
                float(complete_returns.loc[month]),
                name=f"{candidate}.{scenario_name}.{window_name}.{month}.return overlap",
            )
            _same_number(
                float(window["_pnl"].loc[month]),
                float(complete_pnl.loc[month]),
                name=f"{candidate}.{scenario_name}.{window_name}.{month}.PnL overlap",
            )
            if (
                window["monthly_active_exposure"][str(month)]
                != parsed["complete"]["monthly_active_exposure"][str(month)]
            ):
                raise PairsReportContractError(
                    f"{candidate}.{scenario_name}.{window_name}.{month} active exposure overlap mismatch"
                )
        months_before = complete_pnl.loc[complete_pnl.index < window["_pnl"].index[0]]
        expected_baseline = float(parsed["complete"]["baseline_equity"]) + float(
            months_before.sum()
        )
        _same_number(
            float(window["baseline_equity"]),
            expected_baseline,
            name=f"{candidate}.{scenario_name}.{window_name}.continuous baseline",
        )
        _same_number(
            float(window["ending_equity"]),
            expected_baseline + float(window["_pnl"].sum()),
            name=f"{candidate}.{scenario_name}.{window_name}.continuous ending",
        )
        prior_month_end_equities = (
            float(parsed["complete"]["baseline_equity"])
            + complete_pnl.cumsum().loc[complete_pnl.index < window["_pnl"].index[0]]
        )
        minimum_pre_window_peak = max(
            float(parsed["complete"]["baseline_equity"]),
            (
                float(prior_month_end_equities.max())
                if not prior_month_end_equities.empty
                else float(parsed["complete"]["baseline_equity"])
            ),
        )
        if float(window["pre_window_peak_equity"]) + 1e-8 < minimum_pre_window_peak:
            raise PairsReportContractError(
                f"{candidate}.{scenario_name}.{window_name} pre-window peak violates reconstructed lower bound"
            )
    fold_returns = pd.concat([parsed[f"walk_forward_{index}"]["_returns"] for index in range(1, 7)])
    if not fold_returns.index.equals(FROZEN_H_MONTHS) or not np.allclose(
        fold_returns.to_numpy(dtype=float),
        parsed["pseudo_oos"]["_returns"].to_numpy(dtype=float),
        rtol=1e-12,
        atol=1e-12,
    ):
        raise PairsReportContractError(
            f"{candidate}.{scenario_name} six folds do not exactly reconstruct pseudo-OOS"
        )
    folds = [parsed[f"walk_forward_{index}"] for index in range(1, 7)]
    pseudo = parsed["pseudo_oos"]
    _same_number(
        float(parsed["complete"]["pre_window_peak_equity"]),
        float(parsed["development"]["pre_window_peak_equity"]),
        name=f"{candidate}.{scenario_name}.same-start complete/development pre-window peak",
    )
    _same_number(
        float(parsed["complete"]["pre_window_peak_equity"]),
        float(parsed["complete"]["baseline_equity"]),
        name=f"{candidate}.{scenario_name}.complete initial pre-window peak",
    )
    _same_number(
        float(pseudo["pre_window_peak_equity"]),
        float(folds[0]["pre_window_peak_equity"]),
        name=f"{candidate}.{scenario_name}.same-start pseudo/fold1 pre-window peak",
    )
    for left, right in pairwise(folds):
        _same_number(
            float(left["ending_equity"]),
            float(right["baseline_equity"]),
            name=f"{candidate}.{scenario_name}.fold NAV chain",
        )
        if float(right["pre_window_peak_equity"]) + 1e-8 < max(
            float(left["pre_window_peak_equity"]), float(left["ending_equity"])
        ):
            raise PairsReportContractError(
                f"{candidate}.{scenario_name} fold pre-window peaks are not chronological"
            )
    _same_number(
        float(pseudo["baseline_equity"]),
        float(folds[0]["baseline_equity"]),
        name=f"{candidate}.{scenario_name}.pseudo baseline",
    )
    _same_number(
        float(pseudo["ending_equity"]),
        float(folds[-1]["ending_equity"]),
        name=f"{candidate}.{scenario_name}.pseudo ending",
    )
    additive_fields = (
        "equity_observations",
        "nav_observation_sum",
        "active_months",
        "closed_pair_episodes",
        "terminal_open_pair_pseudo_episodes",
        "high_spread_closed_episodes",
        "low_spread_closed_episodes",
    )
    for field in additive_fields:
        _same_number(
            float(pseudo[field]),
            sum(float(fold[field]) for fold in folds),
            name=f"{candidate}.{scenario_name}.pseudo fold {field}",
        )
    _same_number(
        float(pseudo["max_mtm_drawdown_pct"]),
        max(float(fold["max_mtm_drawdown_pct"]) for fold in folds),
        name=f"{candidate}.{scenario_name}.pseudo fold max drawdown",
    )
    development = parsed["development"]
    complete = parsed["complete"]
    _same_number(
        float(development["ending_equity"]),
        float(pseudo["baseline_equity"]),
        name=f"{candidate}.{scenario_name}.development/OOS NAV chain",
    )
    for field in additive_fields:
        _same_number(
            float(complete[field]),
            float(development[field]) + float(pseudo[field]),
            name=f"{candidate}.{scenario_name}.complete partition {field}",
        )
    _same_number(
        float(complete["max_mtm_drawdown_pct"]),
        max(
            float(development["max_mtm_drawdown_pct"]),
            float(pseudo["max_mtm_drawdown_pct"]),
        ),
        name=f"{candidate}.{scenario_name}.complete partition max drawdown",
    )
    if (
        float(parsed["common_is"]["max_mtm_drawdown_pct"])
        > float(development["max_mtm_drawdown_pct"]) + 1e-8
    ):
        raise PairsReportContractError(
            f"{candidate}.{scenario_name}.common-IS drawdown exceeds development drawdown"
        )
    return parsed


def _episode_inputs(
    scenario: Mapping[str, Any], *, start: pd.Timestamp, end: pd.Timestamp, name: str
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    closed = _filter_records(
        scenario.get("closed_episode_ledger"),
        timestamp_field="exit_ts",
        start=start,
        end=end,
        name=f"{name}.closed_episode_ledger",
    )
    terminal = _filter_records(
        scenario.get("terminal_episode_ledger"),
        timestamp_field="exit_ts",
        start=start,
        end=end,
        name=f"{name}.terminal_episode_ledger",
    )
    return closed, terminal


def _economic_edge(closed: list[dict[str, Any]], terminal: list[dict[str, Any]]) -> dict[str, Any]:
    episodes = [*closed, *terminal]
    gross_price = sum(
        _finite(item.get("gross_pair_price_pnl"), name="B gross pair price PnL")
        for item in episodes
    )
    execution_cost = sum(
        _finite(item.get("execution_cost"), name="B execution cost", nonnegative=True)
        for item in episodes
    )
    edge_ratios: list[float] = []
    for item in episodes:
        expected = _finite(
            item.get("expected_convergence_return"),
            name="entry expected convergence",
            nonnegative=True,
        )
        buffered_required = _finite(
            item.get("stressed_required_return"), name="entry stressed required", positive=True
        )
        # The ledger stores the preregistered 1.50x buffered requirement.  The
        # gate denominator is stressed cost before applying that buffer.
        edge_ratios.append(expected / (buffered_required / 1.50))
    return {
        "B_closed_pair_price_pnl_before_execution_and_funding": gross_price,
        "B_execution_cost": execution_cost,
        "B_pre_cost_price_pnl_over_execution_cost": _safe_ratio(gross_price, execution_cost),
        "median_entry_expected_edge_over_stressed_cost": (
            float(np.median(edge_ratios)) if edge_ratios else None
        ),
        "economic_episode_count_including_terminal": len(episodes),
        "terminal_open_pair_pseudo_episodes": len(terminal),
    }


def _primary_gate_contract() -> dict[str, Any]:
    gates = copy.deepcopy(DEFAULT_V17_HARD_GATES)
    gates.pop("holdout")
    concentration = _mapping(gates["concentration"], name="primary concentration gates")
    concentration.pop("effective_symbol_count_min")
    concentration.pop("all_true_leave_one_symbol_out_replays_positive")
    return gates


def _v16_h_matrix(raw: Mapping[str, Any]) -> pd.DataFrame:
    results = _mapping(raw.get("results"), name="v16.results")
    if set(results) != set(FROZEN_V16_CANDIDATE_IDS) or len(results) != len(
        FROZEN_V16_CANDIDATE_IDS
    ):
        raise PairsReportContractError("v16 result IDs differ from frozen contract")
    data: dict[str, pd.Series] = {}
    for candidate in FROZEN_V16_CANDIDATE_IDS:
        scenarios = _mapping(results[candidate], name=f"v16.{candidate}")
        if set(scenarios) != set(SCENARIO_ORDER) or len(scenarios) != len(SCENARIO_ORDER):
            raise PairsReportContractError(f"v16 {candidate} scenario IDs mismatch")
        h = _mapping(scenarios["H"], name=f"v16.{candidate}.H")
        pseudo = _mapping(
            _mapping(h.get("windows"), name=f"v16.{candidate}.H.windows").get("pseudo_oos"),
            name=f"v16.{candidate}.H.pseudo_oos",
        )
        if pseudo.get("monthly_returns_unit") != "percentage_points":
            raise PairsReportContractError("v16 H return unit mismatch")
        data[candidate] = _series_from_mapping(
            pseudo.get("monthly_returns_pct"),
            name=f"v16.{candidate}.H.monthly_returns",
            expected_months=FROZEN_H_MONTHS,
        )
    return pd.DataFrame(data, index=FROZEN_H_MONTHS)


def _candidate_metrics(
    *,
    candidate: str,
    scenarios: Mapping[str, Any],
    parsed_windows: Mapping[str, Mapping[str, Mapping[str, Any]]],
    local_testing: Mapping[str, Any],
    program_testing: Mapping[str, Any],
    turnover: Mapping[str, Any],
    prereg: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    pseudo = {scenario: parsed_windows[scenario]["pseudo_oos"] for scenario in SCENARIO_ORDER}
    h_returns = pseudo["H"]["_returns"]
    h_pnl = pseudo["H"]["_pnl"]
    c2_returns = pseudo["C2"]["_returns"]
    c2_pnl = pseudo["C2"]["_pnl"]
    h_statistics = h_monthly_statistics(h_returns, monthly_pnl=h_pnl)
    c2_statistics = monthly_return_statistics(c2_returns, monthly_pnl=c2_pnl)
    b_statistics = monthly_return_statistics(
        pseudo["B"]["_returns"], monthly_pnl=pseudo["B"]["_pnl"]
    )

    h_scenario = _mapping(scenarios["H"], name=f"{candidate}.H")
    c2_scenario = _mapping(scenarios["C2"], name=f"{candidate}.C2")
    b_scenario = _mapping(scenarios["B"], name=f"{candidate}.B")
    h_closed, h_terminal = _episode_inputs(
        h_scenario, start=_H_START, end=_H_END, name=f"{candidate}.H"
    )
    c2_closed, c2_terminal = _episode_inputs(
        c2_scenario, start=_H_START, end=_H_END, name=f"{candidate}.C2"
    )
    b_closed, b_terminal = _episode_inputs(
        b_scenario, start=_H_START, end=_H_END, name=f"{candidate}.B"
    )

    h_direction = entry_regime_statistics(h_closed)
    c2_direction = entry_regime_statistics([*c2_closed, *c2_terminal])
    if len(h_closed) != pseudo["H"]["closed_pair_episodes"]:
        raise PairsReportContractError(f"{candidate} H closed sample count mismatch")
    if len(h_terminal) != pseudo["H"]["terminal_open_pair_pseudo_episodes"]:
        raise PairsReportContractError(f"{candidate} H terminal count mismatch")
    if h_direction["high_spread_entries"] != pseudo["H"]["high_spread_closed_episodes"]:
        raise PairsReportContractError(f"{candidate} H high-spread count mismatch")
    if h_direction["low_spread_entries"] != pseudo["H"]["low_spread_closed_episodes"]:
        raise PairsReportContractError(f"{candidate} H low-spread count mismatch")

    episode_concentration = episode_concentration_statistics(h_closed, h_terminal)
    attribution = descriptive_symbol_attribution([*h_closed, *h_terminal])
    loso = true_loso_statistics(
        float(episode_concentration["total_net_pair_pnl"]),
        None,
        expected_symbols=_list(
            _mapping(prereg.get("universe"), name="universe").get("primary_symbols"),
            name="primary symbols",
        ),
    )

    fold_returns = []
    for index in range(1, 7):
        window = parsed_windows["H"][f"walk_forward_{index}"]
        fold_returns.append(float(window["total_return_pct"]))
    is_trimmed = trimmed_mean_pct(parsed_windows["H"]["common_is"]["_returns"])
    oos_trimmed = float(h_statistics["trimmed_mean_monthly_pct"])
    is_dd = float(parsed_windows["H"]["common_is"]["max_mtm_drawdown_pct"])
    oos_dd = float(pseudo["H"]["max_mtm_drawdown_pct"])

    local_candidate = _mapping(
        _mapping(local_testing.get("candidate_results"), name="local candidate results").get(
            candidate
        ),
        name=f"local candidate {candidate}",
    )
    program_candidate = _mapping(
        _mapping(program_testing.get("candidate_results"), name="program candidate results").get(
            candidate
        ),
        name=f"program candidate {candidate}",
    )
    local_pbo = _mapping(local_testing.get("pbo"), name="local PBO")
    program_pbo = _mapping(program_testing.get("pbo"), name="program PBO")
    economic = _economic_edge(b_closed, b_terminal)
    metrics: dict[str, Any] = {
        "sample": {
            "pseudo_oos_months": len(h_returns),
            "closed_pair_episodes": len(h_closed),
            "high_spread_entries": int(h_direction["high_spread_entries"]),
            "low_spread_entries": int(h_direction["low_spread_entries"]),
            "active_months": int(pseudo["H"]["active_months"]),
            "pair_legs_may_not_count_as_separate_trades": True,
            "terminal_open_pair_pseudo_episodes_excluded_from_closed_sample": len(h_terminal),
        },
        "H_return": {
            "trimmed_mean_monthly_pct": h_statistics["trimmed_mean_monthly_pct"],
            "median_monthly_pct": h_statistics["median_monthly_pct"],
            "block_bootstrap_90pct_lower_bound_pct": h_statistics[
                "block_bootstrap_90pct_lower_bound_pct"
            ],
            "total_return_pct": h_statistics["total_return_pct"],
        },
        "H_stability": {
            "negative_months": h_statistics["negative_months"],
            "months_below_minus_1pct": h_statistics["months_below_minus_1pct"],
            "worst_month_pct": h_statistics["worst_month_pct"],
            "best_month_pct": h_statistics["best_month_pct"],
        },
        "C2_return": {
            "trimmed_mean_monthly_pct": c2_statistics["trimmed_mean_monthly_pct"],
            "median_monthly_pct": c2_statistics["median_monthly_pct"],
            "total_return_pct": c2_statistics["total_return_pct"],
        },
        "drawdown": {
            "B_max_mtm_pct": pseudo["B"]["max_mtm_drawdown_pct"],
            "C2_H_max_mtm_pct": max(
                pseudo["C2"]["max_mtm_drawdown_pct"], pseudo["H"]["max_mtm_drawdown_pct"]
            ),
            "max_recovery_months": max(
                pseudo[scenario]["max_recovery_months"] for scenario in SCENARIO_ORDER
            ),
            "B_recovery_months": pseudo["B"]["max_recovery_months"],
            "C2_recovery_months": pseudo["C2"]["max_recovery_months"],
            "H_recovery_months": pseudo["H"]["max_recovery_months"],
        },
        "walk_forward": {
            "fold_total_returns_pct": fold_returns,
            "positive_folds": sum(value > 0.0 for value in fold_returns),
            "total_folds": len(fold_returns),
            "worst_six_month_fold_pct": min(fold_returns),
            "common_is_trimmed_mean_monthly_pct": is_trimmed,
            "pseudo_oos_trimmed_mean_monthly_pct": oos_trimmed,
            "oos_to_is_trimmed_return_ratio": _safe_ratio(oos_trimmed, is_trimmed),
            "common_is_max_mtm_drawdown_pct": is_dd,
            "pseudo_oos_max_mtm_drawdown_pct": oos_dd,
            "oos_to_is_drawdown_ratio": _safe_ratio(oos_dd, is_dd),
        },
        "economic_edge": economic,
        "concentration": {
            "best_month_positive_pnl_share": h_statistics["best_month_positive_pnl_share"],
            "best_3_month_positive_pnl_share": h_statistics["best_3_month_positive_pnl_share"],
            "top_5pct_pair_episodes_positive_pnl_share": episode_concentration[
                "top_5pct_pair_episodes_positive_pnl_share"
            ],
            "net_after_top_5pct_pair_episodes_removed": episode_concentration[
                "net_after_top_5pct_pair_episodes_removed"
            ],
            "effective_symbol_count": loso["effective_symbol_count"],
            "all_true_leave_one_symbol_out_replays_positive": loso[
                "all_true_leave_one_symbol_out_replays_positive"
            ],
            "episode": episode_concentration,
            "descriptive_symbol_attribution": attribution,
            "true_loso": loso,
        },
        "holdout": {
            "status": "NOT_RUN_PRIMARY_ONLY",
        },
        "direction": {
            "high_spread_C2_net_pnl": c2_direction["high_spread_C2_net_pnl"],
            "low_spread_C2_net_pnl": c2_direction["low_spread_C2_net_pnl"],
            "C2_closed_pair_episodes": len(c2_closed),
            "C2_terminal_open_pair_pseudo_episodes": len(c2_terminal),
        },
        "multiple_testing": {
            "paired_block_months": 3,
            "bootstrap_iterations": VALIDATION_ITERATIONS,
            "holm_fwer_adjusted_p": local_candidate["holm_fwer_adjusted_p"],
            "deflated_sharpe": local_candidate["deflated_sharpe"],
            "probability_backtest_overfit": local_pbo["probability_backtest_overfit"],
            "local_v17_trial_count": 3,
            "cumulative_program_trial_count_including_v16": 9,
            "cumulative_program_holm_adjusted_p": program_candidate["holm_fwer_adjusted_p"],
            "cumulative_program_deflated_sharpe": program_candidate["deflated_sharpe"],
            "cumulative_program_probability_backtest_overfit": program_pbo[
                "probability_backtest_overfit"
            ],
            "local_candidate": local_candidate,
            "program_candidate": program_candidate,
        },
        "turnover": dict(turnover),
    }
    supplemental = {
        "B_monthly_statistics": b_statistics,
        "C2_monthly_statistics": c2_statistics,
        "H_monthly_statistics": h_statistics,
        "H_closed_episode_regime_statistics": h_direction,
        "C2_closed_plus_terminal_direction_statistics": c2_direction,
        "H_episode_concentration": episode_concentration,
        "H_descriptive_symbol_attribution_not_LOSO": attribution,
        "true_LOSO": loso,
    }
    return _json_safe(metrics), _json_safe(supplemental)


def _canonical_preregistration(
    prereg_path: Path, *, repo_root: Path
) -> tuple[dict[str, Any], str, Path]:
    canonical = (repo_root / "configs/crypto_15m_v17_pairs_prereg.yaml").resolve(strict=True)
    supplied = prereg_path.resolve(strict=True)
    if supplied != canonical:
        raise PairsReportContractError(
            f"report requires canonical preregistration path: {canonical}"
        )
    prereg = load_preregistration(canonical)
    if prereg.get("schema_version") != PREREG_SCHEMA:
        raise PairsReportContractError("canonical preregistration schema mismatch")
    if prereg.get("hard_gates") != DEFAULT_V17_HARD_GATES:
        raise PairsReportContractError(
            "canonical hard gates differ from frozen validation defaults"
        )
    candidate_ids = tuple(
        str(_mapping(item, name="candidate cell").get("id"))
        for item in _list(prereg.get("candidate_cells"), name="candidate_cells")
    )
    if candidate_ids != tuple(FROZEN_V17_CANDIDATE_IDS):
        raise PairsReportContractError("canonical candidate IDs/order changed")
    return prereg, sha256_file(canonical), canonical


def build_report(
    *,
    v17_artifact: JsonArtifact,
    v16_artifact: JsonArtifact,
    prereg: Mapping[str, Any],
    prereg_path: Path,
    prereg_sha256: str,
    repo_root: Path,
) -> dict[str, Any]:
    """Validate both raw artifacts and build the frozen primary report."""

    v17 = v17_artifact.payload
    _validate_v17_header(
        v17,
        prereg,
        prereg_sha256=prereg_sha256,
        canonical_prereg_path=prereg_path,
        repo_root=repo_root,
    )
    _validate_v16_header(v16_artifact, prereg)
    windows = _expected_windows(prereg)
    results = _mapping(v17.get("results"), name="v17.results")
    streams = _mapping(v17.get("streams"), name="v17.streams")
    expected_candidates = set(FROZEN_V17_CANDIDATE_IDS)
    if (
        set(results) != expected_candidates
        or len(results) != len(expected_candidates)
        or set(streams) != expected_candidates
        or len(streams) != len(expected_candidates)
    ):
        raise PairsReportContractError("v17 results/streams candidate IDs changed")
    primary_symbols = set(
        str(item)
        for item in _list(
            _mapping(prereg.get("universe"), name="universe").get("primary_symbols"),
            name="primary symbols",
        )
    )
    stream_contracts: dict[str, dict[str, Any]] = {}
    for candidate in FROZEN_V17_CANDIDATE_IDS:
        stream = _mapping(streams[candidate], name=f"streams.{candidate}")
        for field in ("pair_selection_ledger", "pair_models", "entry_intents"):
            _assert_payload_hash(stream, field, name=f"streams.{candidate}")
            _validate_nested_candidate_ids(
                stream.get(field), expected=candidate, name=f"streams.{candidate}.{field}"
            )
        stream_contracts[candidate] = _validate_stream_contract(
            stream,
            candidate=candidate,
            windows=windows,
            primary_symbols=primary_symbols,
            prereg=prereg,
        )

    parsed_by_candidate: dict[str, dict[str, Any]] = {}
    h_matrix_data: dict[str, pd.Series] = {}
    turnover_by_candidate: dict[str, dict[str, Any]] = {}
    for candidate in FROZEN_V17_CANDIDATE_IDS:
        scenarios = _mapping(results[candidate], name=f"results.{candidate}")
        if set(scenarios) != set(SCENARIO_ORDER) or len(scenarios) != len(SCENARIO_ORDER):
            raise PairsReportContractError(f"{candidate} scenario IDs changed")
        parsed_scenarios: dict[str, Any] = {}
        for scenario_name in SCENARIO_ORDER:
            scenario = _mapping(scenarios[scenario_name], name=f"{candidate}.{scenario_name}")
            _validate_scenario_hashes(
                scenario, candidate=candidate, name=f"{candidate}.{scenario_name}"
            )
            parsed_scenarios[scenario_name] = _scenario_windows(
                scenario,
                candidate=candidate,
                scenario_name=scenario_name,
                windows=windows,
            )
            _scenario_semantics(
                scenario,
                candidate=candidate,
                scenario_name=scenario_name,
                stream_contract=stream_contracts[candidate],
                primary_symbols=primary_symbols,
                parsed_windows=parsed_scenarios[scenario_name],
                prereg=prereg,
            )
        h_matrix_data[candidate] = parsed_scenarios["H"]["pseudo_oos"]["_returns"]
        turnover_by_candidate[candidate] = _turnover(
            _mapping(scenarios["H"], name=f"{candidate}.H"),
            parsed_scenarios["H"]["pseudo_oos"],
            start=_H_START,
            end=_H_END,
            name=f"{candidate}.H.pseudo_oos",
        )
        parsed_by_candidate[candidate] = {
            "raw_scenarios": scenarios,
            "windows": parsed_scenarios,
        }

    h_matrix = pd.DataFrame(h_matrix_data, index=FROZEN_H_MONTHS)
    local_testing = three_candidate_multiple_testing(h_matrix)
    v16_matrix = _v16_h_matrix(v16_artifact.payload)
    program_matrix = pd.concat((v16_matrix, h_matrix), axis=1)
    program_matrix = program_matrix.loc[:, list(FROZEN_PROGRAM_CANDIDATE_IDS)]
    program_testing = program_wide_multiple_testing(program_matrix)
    ranking = rank_h_candidates(
        h_matrix,
        h_max_drawdowns={
            candidate: parsed_by_candidate[candidate]["windows"]["H"]["pseudo_oos"][
                "max_mtm_drawdown_pct"
            ]
            for candidate in FROZEN_V17_CANDIDATE_IDS
        },
        turnovers={
            candidate: turnover_by_candidate[candidate]["filled_gross_turnover"]
            for candidate in FROZEN_V17_CANDIDATE_IDS
        },
    )
    ranking_records = _json_safe(ranking.to_dict("records"))

    primary_gates = _primary_gate_contract()
    cells: dict[str, Any] = {}
    passing: set[str] = set()
    for candidate in FROZEN_V17_CANDIDATE_IDS:
        parsed = parsed_by_candidate[candidate]
        metrics, supplemental = _candidate_metrics(
            candidate=candidate,
            scenarios=parsed["raw_scenarios"],
            parsed_windows=parsed["windows"],
            local_testing=local_testing,
            program_testing=program_testing,
            turnover=turnover_by_candidate[candidate],
            prereg=prereg,
        )
        pre_loso = evaluate_v17_hard_gates(
            metrics, hard_gates=primary_gates, require_complete_contract=False
        )
        full = evaluate_v17_hard_gates(metrics, hard_gates=prereg)
        if full["passed"]:
            raise PairsReportContractError(
                "primary-only evidence cannot pass full gates without LOSO and holdout"
            )
        if pre_loso["passed"]:
            passing.add(candidate)
        cells[candidate] = {
            "scenario_windows": {
                scenario: {
                    name: _public_window(window)
                    for name, window in parsed["windows"][scenario].items()
                }
                for scenario in SCENARIO_ORDER
            },
            "metrics": metrics,
            "supplemental_statistics": supplemental,
            "primary_pre_LOSO_gates": pre_loso,
            "full_hard_gates": full,
            "full_gate_missing_LOSO_or_holdout_are_not_passed": True,
        }

    ranked_passing = [
        str(row["candidate_id"]) for row in ranking_records if row["candidate_id"] in passing
    ]
    locked_winner = ranked_passing[0] if ranked_passing else None
    verdict = REQUIRES_TRUE_LOSO if locked_winner is not None else RED_NO_HOLDOUT
    decision = {
        "verdict": verdict,
        "primary_pre_LOSO_passing_candidates": ranked_passing,
        "locked_primary_winner": locked_winner,
        "true_LOSO": (
            "REQUIRED_NOT_RUN" if locked_winner is not None else "NOT_RUN_PRIMARY_GATES_FAILED"
        ),
        "holdout": (
            "NOT_RUN_REQUIRES_TRUE_LOSO"
            if locked_winner is not None
            else "NOT_RUN_PRIMARY_GATES_FAILED"
        ),
        "runner_up_after_failure_tested": False,
        "promotion_authorized": False,
        "paper_authorized": False,
        "live_deployment_authorized": False,
    }

    module_path = Path(__file__).resolve()
    cli_path = (repo_root / "scripts/research/crypto_15m_v17_pairs_report.py").resolve()
    report: dict[str, Any] = {
        "schema_version": REPORT_SCHEMA,
        "deterministic": True,
        "evidence_eligible": True,
        "as_of_utc": str(prereg.get("created_at_utc")),
        "decision": decision,
        "ranking": {
            "rank_metric": "H_trimmed_mean_monthly_return_capped_at_15pct",
            "cap_pct": 15.0,
            "tie_break_order": [
                "lower_H_max_drawdown",
                "fewer_H_negative_months",
                "lower_H_pseudo_oos_filled_gross_turnover",
                "lexicographic_candidate_id",
            ],
            "rows": ranking_records,
        },
        "multiple_testing": {
            "local_v17_exact_36x3": _json_safe(local_testing),
            "program_wide_v16_plus_v17_exact_36x9": _json_safe(program_testing),
            "iterations": VALIDATION_ITERATIONS,
            "seed": VALIDATION_SEED,
        },
        "cells": cells,
        "governance": {
            "primary_pre_LOSO_gate_contract": primary_gates,
            "full_hard_gate_contract": DEFAULT_V17_HARD_GATES,
            "holdout_or_LOSO_run_by_reporter": False,
            "raw_backtest_or_snapshot_access_by_reporter": False,
            "historical_result_is_not_live_implementability_evidence": True,
        },
        "provenance": {
            "canonical_preregistration": {
                "path": str(prereg_path),
                "sha256": prereg_sha256,
                "schema_version": PREREG_SCHEMA,
            },
            "v17_raw": v17_artifact.provenance(),
            "v16_raw": v16_artifact.provenance(),
            "frozen_snapshots": {
                name: {
                    "bytes": int(prereg["snapshots"][name]["bytes"]),
                    "sha256": str(prereg["snapshots"][name]["sha256"]),
                }
                for name in ("market", "funding")
            },
            "v17_runner_source_provenance": v17["source_provenance"],
            "report_source": {
                "module": str(module_path.relative_to(repo_root)),
                "module_sha256": sha256_file(module_path),
                "cli": str(cli_path.relative_to(repo_root)),
                "cli_sha256": sha256_file(cli_path) if cli_path.is_file() else None,
            },
        },
    }
    return _json_safe(report)


def generate_report(
    v17_raw_path: Path,
    *,
    v16_raw_path: Path | None = None,
    prereg_path: Path | None = None,
    repo_root: Path | None = None,
) -> dict[str, Any]:
    """Load canonical artifacts and return one deterministic report mapping."""

    root = (repo_root or Path(__file__).resolve().parents[3]).resolve()
    registration_path = prereg_path or root / "configs/crypto_15m_v17_pairs_prereg.yaml"
    prereg, prereg_sha256, canonical_path = _canonical_preregistration(
        registration_path, repo_root=root
    )
    parent_path = v16_raw_path or root / str(prereg["batch1_parent_evidence"]["raw_result_gzip"])
    return build_report(
        v17_artifact=load_json_artifact(v17_raw_path),
        v16_artifact=load_json_artifact(parent_path),
        prereg=prereg,
        prereg_path=canonical_path,
        prereg_sha256=prereg_sha256,
        repo_root=root,
    )


def deterministic_json(report: Mapping[str, Any]) -> str:
    """Serialize report bytes deterministically; NaN and Infinity are forbidden."""

    return (
        json.dumps(
            _json_safe(report), sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False
        )
        + "\n"
    )


def _format_number(value: Any, *, suffix: str = "", digits: int = 2) -> str:
    if value is None:
        return "N/A"
    return f"{float(value):.{digits}f}{suffix}"


def render_markdown(report: Mapping[str, Any]) -> str:
    """Render a compact deterministic Turkish decision report."""

    if report.get("schema_version") != REPORT_SCHEMA:
        raise PairsReportContractError("markdown renderer requires a v17 pairs report")
    decision = _mapping(report.get("decision"), name="report.decision")
    cells = _mapping(report.get("cells"), name="report.cells")
    ranking_rows = _list(
        _mapping(report.get("ranking"), name="report.ranking").get("rows"),
        name="ranking.rows",
    )
    lines = [
        "# Crypto 15m v17 pairs — primary sonuç raporu",
        "",
        "## Karar",
        "",
        f"**{decision['verdict']}**",
        "",
    ]
    if decision["verdict"] == RED_NO_HOLDOUT:
        lines.append(
            "Hiçbir hücre ön-LOSO primary mutlak kapılarını geçmedi; gerçek LOSO ve "
            "holdout çalıştırılmadı."
        )
    else:
        lines.append(
            f"Kilitli primary kazanan `{decision['locked_primary_winner']}`. Sonuç henüz "
            "başarı değildir; gerçek LOSO zorunludur ve holdout çalıştırılmamıştır."
        )
    lines.extend(
        [
            "",
            "Tam hard-gate sonucu hiçbir hücre için başarılı sayılmadı: primary raw "
            "kanıtta bulunmayan LOSO/holdout metrikleri fail-closed başarısızdır.",
            "",
            "## Hücre özeti",
            "",
            "| Sıra | Hücre | Ön-LOSO | H trim/ay | H medyan | H negatif | H kötü ay | H DD | C2 trim/ay | B edge/cost | H kapalı+terminal | Aktif ay | Turnover |",
            "|---:|---|:---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for row in ranking_rows:
        candidate = str(row["candidate_id"])
        cell = _mapping(cells[candidate], name=f"cells.{candidate}")
        metrics = _mapping(cell["metrics"], name=f"{candidate}.metrics")
        pre_loso = _mapping(cell["primary_pre_LOSO_gates"], name=f"{candidate}.gates")
        sample = metrics["sample"]
        lines.append(
            "| "
            + " | ".join(
                (
                    str(row["rank"]),
                    candidate,
                    "PASS" if pre_loso["passed"] else "FAIL",
                    _format_number(metrics["H_return"]["trimmed_mean_monthly_pct"], suffix="%"),
                    _format_number(metrics["H_return"]["median_monthly_pct"], suffix="%"),
                    str(metrics["H_stability"]["negative_months"]),
                    _format_number(metrics["H_stability"]["worst_month_pct"], suffix="%"),
                    _format_number(row["H_max_drawdown_pct"], suffix="%"),
                    _format_number(metrics["C2_return"]["trimmed_mean_monthly_pct"], suffix="%"),
                    _format_number(
                        metrics["economic_edge"]["B_pre_cost_price_pnl_over_execution_cost"],
                        suffix="x",
                    ),
                    f"{sample['closed_pair_episodes']}+{sample['terminal_open_pair_pseudo_episodes_excluded_from_closed_sample']}",
                    str(sample["active_months"]),
                    _format_number(row["turnover"], suffix="x"),
                )
            )
            + " |"
        )
    lines.extend(["", "## Başarısız kapılar", ""])
    for candidate in FROZEN_V17_CANDIDATE_IDS:
        gate = cells[candidate]["primary_pre_LOSO_gates"]
        failed = gate["failed_gates"]
        rendered = ", ".join(f"`{item}`" for item in failed) if failed else "yok"
        lines.append(f"- `{candidate}`: {rendered}")
    provenance = report["provenance"]
    lines.extend(
        [
            "",
            "## Kanıt ve sınırlar",
            "",
            f"- V17 raw JSON SHA-256: `{provenance['v17_raw']['decoded_json_sha256']}`",
            f"- V16 raw JSON SHA-256: `{provenance['v16_raw']['decoded_json_sha256']}`",
            f"- Prereg SHA-256: `{provenance['canonical_preregistration']['sha256']}`",
            f"- Market snapshot SHA-256: `{provenance['frozen_snapshots']['market']['sha256']}`",
            f"- Funding snapshot SHA-256: `{provenance['frozen_snapshots']['funding']['sha256']}`",
            "- Pseudo-OOS tam olarak Haziran 2023–Mayıs 2026, 36 aydır.",
            "- Turnover paydası H penceresindeki her 15m NAV gözleminin aritmetik ortalamasıdır.",
            "- Rapor snapshot açmadı, backtest veya holdout/LOSO çalıştırmadı ve deployment yetkisi vermedi.",
            "",
        ]
    )
    return "\n".join(lines)


def _write_output(path: Path, content: str, *, protected: Sequence[Path]) -> None:
    resolved = path.resolve()
    if resolved in {item.resolve() for item in protected}:
        raise PairsReportContractError("report output cannot overwrite an input artifact")
    resolved.parent.mkdir(parents=True, exist_ok=True)
    resolved.write_text(content, encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--v17-raw", type=Path, required=True)
    parser.add_argument(
        "--v16-raw",
        type=Path,
        default=None,
    )
    parser.add_argument("--prereg", type=Path, default=None)
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[3])
    parser.add_argument("--json-output", type=Path)
    parser.add_argument("--markdown-output", type=Path)
    parser.add_argument("--stdout", choices=("json", "markdown"), default="markdown")
    args = parser.parse_args(argv)

    root = args.repo_root.resolve()
    v16_raw = (
        args.v16_raw or root / "reports/research/crypto_15m_v16_primary_raw_2026-07-11.json.gz"
    )
    prereg = args.prereg or root / "configs/crypto_15m_v17_pairs_prereg.yaml"
    if (
        args.json_output is not None
        and args.markdown_output is not None
        and args.json_output.resolve() == args.markdown_output.resolve()
    ):
        raise PairsReportContractError("JSON and Markdown outputs must be distinct files")

    report = generate_report(
        args.v17_raw,
        v16_raw_path=v16_raw,
        prereg_path=prereg,
        repo_root=root,
    )
    rendered_json = deterministic_json(report)
    rendered_markdown = render_markdown(report)
    protected = (
        args.v17_raw,
        v16_raw,
        prereg,
        *(root / relative for relative in _FROZEN_SOURCE_FILES),
    )
    if args.json_output is not None:
        _write_output(args.json_output, rendered_json, protected=protected)
    if args.markdown_output is not None:
        _write_output(args.markdown_output, rendered_markdown, protected=protected)
    print(rendered_json if args.stdout == "json" else rendered_markdown, end="")
    return 0


__all__ = [
    "RED_NO_HOLDOUT",
    "REPORT_SCHEMA",
    "REQUIRES_TRUE_LOSO",
    "JsonArtifact",
    "PairsReportContractError",
    "build_report",
    "deterministic_json",
    "generate_report",
    "load_json_artifact",
    "main",
    "render_markdown",
    "sha256_file",
]
