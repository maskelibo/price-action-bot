"""Frozen-data runner for the preregistered crypto 15-minute v17 pair study.

The IO boundary is deliberately strict.  Both DuckDB snapshots are byte-size
and SHA256 verified before either database is opened.  Market frames remain
independent by symbol: pair-local alignment belongs to the causal selector and
there is no global intersection or forward fill in this module.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import subprocess
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, is_dataclass
from datetime import UTC, datetime
from itertools import pairwise
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd
import yaml

from price_action.lab.crypto_15m_pairs_engine import (
    PairCostModel,
    PairPortfolioPolicy,
    PairPortfolioResult,
    PairSelectionEvent,
    simulate_pair_portfolio,
)
from price_action.lab.crypto_15m_pairs_evidence import (
    closed_episode_frame,
    economic_episode_frame,
    scenario_window_summary,
    terminal_episode_frame,
)
from price_action.lab.crypto_15m_pairs_signals import (
    PairCell,
    PairEntryIntent,
    PairModel,
    PairSelectionDecision,
    generate_pair_entry_intents,
    select_pairs_monthly_with_diagnostics,
)

PROGRAM_SCHEMA = "crypto-15m-v17-pairs-run-v1"
PREREG_SCHEMA = "crypto-15m-v17-pairs-prereg-v1"
FROZEN_STATUS = "PREREGISTERED_NO_RESULTS_SEEN"
SCENARIO_ORDER = ("B", "C2", "H")
_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_BAR = pd.Timedelta(minutes=15)


@dataclass(frozen=True, slots=True)
class SnapshotVerification:
    name: str
    configured_path: str
    resolved_path: str
    bytes: int
    sha256: str
    status: str = "VERIFIED"


@dataclass(frozen=True, slots=True)
class MarketBundle:
    """Independently loaded OHLCV frames, with no cross-symbol alignment."""

    frames: dict[str, pd.DataFrame]
    rows_by_symbol: dict[str, int]
    first_ts_by_symbol: dict[str, pd.Timestamp]
    last_ts_by_symbol: dict[str, pd.Timestamp]


@dataclass(frozen=True, slots=True)
class FundingBundle:
    signal_rates: dict[str, pd.DataFrame]
    engine_events: tuple[dict[str, Any], ...]
    rows_by_symbol: dict[str, int]


def sha256_file(path: Path, *, chunk_bytes: int = 8 * 1024 * 1024) -> str:
    """Stream a file hash without loading the snapshot into memory."""

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while block := handle.read(chunk_bytes):
            digest.update(block)
    return digest.hexdigest()


def _jsonable(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return _jsonable(asdict(value))
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, tuple | list | set | frozenset):
        items = sorted(value) if isinstance(value, set | frozenset) else value
        return [_jsonable(item) for item in items]
    if isinstance(value, datetime | pd.Timestamp):
        return pd.Timestamp(value).tz_convert(UTC).isoformat()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, np.generic):
        return value.item()
    return value


def _payload_sha256(value: Any) -> str:
    encoded = json.dumps(
        _jsonable(value), sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def load_preregistration(path: Path) -> dict[str, Any]:
    """Read and validate the frozen-before-results v17 contract."""

    loaded = yaml.safe_load(path.read_bytes())
    if not isinstance(loaded, dict):
        raise ValueError("preregistration must be a YAML mapping")
    if loaded.get("schema_version") != PREREG_SCHEMA:
        raise ValueError(f"unsupported preregistration schema: {loaded.get('schema_version')!r}")
    if loaded.get("status") != FROZEN_STATUS:
        raise ValueError("preregistration status is not frozen-before-results")
    if loaded.get("live_deployment_authorized") is not False:
        raise ValueError("research runner requires live_deployment_authorized=false")
    snapshots = loaded.get("snapshots")
    universe = loaded.get("universe")
    cells = loaded.get("candidate_cells")
    if not isinstance(snapshots, dict) or not isinstance(universe, dict):
        raise ValueError("preregistration needs snapshots and universe mappings")
    if snapshots.get("mutable_live_databases_forbidden") is not True:
        raise ValueError("mutable live databases must be forbidden")
    if not all(isinstance(snapshots.get(name), dict) for name in ("market", "funding")):
        raise ValueError("market and funding snapshot mappings are required")
    primary = universe.get("primary_symbols")
    holdout = universe.get("holdout_symbols")
    reference = universe.get("reference_symbol")
    if not isinstance(primary, list) or len(primary) != 13 or len(set(primary)) != 13:
        raise ValueError("primary universe must contain exactly 13 unique symbols")
    if not isinstance(holdout, list) or len(holdout) != 4 or len(set(holdout)) != 4:
        raise ValueError("holdout universe must contain exactly four unique symbols")
    if set(primary).intersection(holdout) or reference in set(primary).union(holdout):
        raise ValueError("reference, primary and holdout partitions must be disjoint")
    if reference != "BTC/USDT":
        raise ValueError("the frozen reference symbol must be BTC/USDT")
    if not isinstance(cells, list) or len(cells) != 3:
        raise ValueError("the frozen v17 batch must contain exactly three cells")
    return loaded


def _require_canonical_preregistration(
    prereg: Mapping[str, Any], *, prereg_path: Path, repo_root: Path
) -> Path:
    canonical_path = (repo_root / "configs/crypto_15m_v17_pairs_prereg.yaml").resolve()
    if not canonical_path.is_file():
        raise ValueError(f"canonical v17 preregistration is missing: {canonical_path}")
    if prereg_path.resolve() != canonical_path:
        raise ValueError("execute requires the canonical repo v17 preregistration path")
    canonical = load_preregistration(canonical_path)
    if prereg != canonical:
        raise ValueError(
            "execute preregistration must semantically equal the canonical repo v17 preregistration"
        )
    return canonical_path


def _snapshot_path(spec: Mapping[str, Any], repo_root: Path) -> Path:
    configured_text = str(spec.get("path", "")).strip()
    if not configured_text:
        raise ValueError("snapshot path is missing")
    configured = Path(configured_text)
    return configured if configured.is_absolute() else repo_root / configured


def verify_frozen_snapshot(
    name: str, spec: Mapping[str, Any], *, repo_root: Path
) -> SnapshotVerification:
    """Require exact byte size and SHA256 before a snapshot may be opened."""

    expected_hash = str(spec.get("sha256", "")).lower()
    expected_bytes = spec.get("bytes")
    if not _SHA256.fullmatch(expected_hash):
        raise ValueError(f"{name}: invalid preregistered SHA256")
    if isinstance(expected_bytes, bool) or not isinstance(expected_bytes, int):
        raise ValueError(f"{name}: invalid preregistered byte size")
    path = _snapshot_path(spec, repo_root)
    try:
        resolved = path.resolve(strict=True)
    except FileNotFoundError as exc:
        raise ValueError(f"{name}: snapshot does not exist: {path}") from exc
    if not resolved.is_file():
        raise ValueError(f"{name}: snapshot is not a regular file: {resolved}")
    actual_bytes = resolved.stat().st_size
    if actual_bytes != expected_bytes:
        raise ValueError(
            f"{name}: byte-size mismatch (expected {expected_bytes}, got {actual_bytes})"
        )
    actual_hash = sha256_file(resolved)
    if actual_hash != expected_hash:
        raise ValueError(f"{name}: SHA256 mismatch")
    return SnapshotVerification(
        name=name,
        configured_path=str(spec["path"]),
        resolved_path=str(resolved),
        bytes=actual_bytes,
        sha256=actual_hash,
    )


def normalize_usdt_symbol(value: Any) -> str:
    """Canonicalize spot, perpetual, and bare-base spellings."""

    text = str(value).strip().upper().split(":", 1)[0].replace("-", "/").replace("_", "/")
    if not text:
        raise ValueError("empty symbol")
    if "/" in text:
        pieces = text.split("/")
        if len(pieces) != 2:
            raise ValueError(f"unsupported symbol spelling: {value!r}")
        base, quote = pieces
    elif text.endswith("USDT"):
        base, quote = text[:-4], "USDT"
    elif re.fullmatch(r"[A-Z0-9]+", text) and text != "USDT":
        base, quote = text, "USDT"
    else:
        raise ValueError(f"symbol is not USDT quoted: {value!r}")
    if not base or quote != "USDT" or not re.fullmatch(r"[A-Z0-9]+", base):
        raise ValueError(f"unsupported symbol spelling: {value!r}")
    return f"{base}/USDT"


def _identifier(value: Any, *, label: str) -> str:
    name = str(value)
    if not _IDENTIFIER.fullmatch(name):
        raise ValueError(f"unsafe {label}: {name!r}")
    return f'"{name}"'


def _columns(connection: duckdb.DuckDBPyConnection, table: str) -> dict[str, str]:
    quoted = _identifier(table, label="table name")
    try:
        rows = connection.execute(f"DESCRIBE {quoted}").fetchall()
    except duckdb.Error as exc:
        raise ValueError(f"cannot describe required table {table!r}") from exc
    result = {str(row[0]).lower(): str(row[0]) for row in rows}
    if len(result) != len(rows):
        raise ValueError(f"{table}: case-colliding column names")
    return result


def _raw_symbol_map(
    raw_symbols: Sequence[Any], expected_symbols: Sequence[str], *, label: str
) -> dict[str, str]:
    grouped: dict[str, list[str]] = {}
    for value in raw_symbols:
        raw = str(value)
        try:
            normalized = normalize_usdt_symbol(raw)
        except ValueError:
            continue
        grouped.setdefault(normalized, []).append(raw)
    result: dict[str, str] = {}
    for expected in expected_symbols:
        choices = sorted(set(grouped.get(expected, [])))
        if not choices:
            raise ValueError(f"{label}: missing symbol {expected}")
        if len(choices) != 1:
            raise ValueError(f"{label}: ambiguous database spellings for {expected}: {choices}")
        result[expected] = choices[0]
    return result


def _utc_timestamp(value: Any, *, label: str) -> pd.Timestamp:
    try:
        timestamp = pd.Timestamp(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label}: invalid timestamp") from exc
    if timestamp.tzinfo is None:
        timestamp = timestamp.tz_localize(UTC)
    else:
        timestamp = timestamp.tz_convert(UTC)
    return timestamp


def _utc_series(values: pd.Series, *, label: str) -> pd.Series:
    timestamps = pd.to_datetime(values, utc=True, errors="coerce")
    if timestamps.isna().any():
        raise ValueError(f"{label}: invalid timestamp values")
    return timestamps


def load_market_snapshot(
    path: Path,
    spec: Mapping[str, Any],
    *,
    symbols: Sequence[str],
    start: pd.Timestamp,
    end: pd.Timestamp,
) -> MarketBundle:
    """Load every symbol independently; never intersect or forward-fill frames."""

    if start >= end:
        raise ValueError("market range must be increasing")
    table_name = str(spec.get("table", ""))
    venue = str(spec.get("venue", ""))
    timeframe = str(spec.get("timeframe", ""))
    table = _identifier(table_name, label="market table")
    connection = duckdb.connect(str(path), read_only=True)
    try:
        connection.execute("SET TimeZone = 'UTC'")
        columns = _columns(connection, table_name)
        required = {"venue", "symbol", "timeframe", "ts", "open", "high", "low", "close", "volume"}
        missing = sorted(required.difference(columns))
        if missing:
            raise ValueError(f"market snapshot missing columns: {missing}")
        raw_symbols = [
            row[0]
            for row in connection.execute(
                f"SELECT DISTINCT symbol FROM {table} WHERE venue=? AND timeframe=?",
                [venue, timeframe],
            ).fetchall()
        ]
        symbol_map = _raw_symbol_map(raw_symbols, symbols, label="market snapshot")
        native = [symbol_map[symbol] for symbol in symbols]
        placeholders = ",".join("?" for _ in native)
        query = (
            f"SELECT symbol, ts, open, high, low, close, volume FROM {table} "
            f"WHERE venue=? AND timeframe=? AND ts>=? AND ts<? "
            f"AND symbol IN ({placeholders}) ORDER BY symbol, ts"
        )
        data = connection.execute(
            query, [venue, timeframe, start.to_pydatetime(), end.to_pydatetime(), *native]
        ).fetchdf()
    finally:
        connection.close()
    if data.empty:
        raise ValueError("market snapshot query returned no rows")
    data["ts"] = _utc_series(data["ts"], label="market snapshot")
    inverse = {raw: symbol for symbol, raw in symbol_map.items()}
    data["symbol"] = data["symbol"].map(inverse)
    if data["symbol"].isna().any():
        raise ValueError("market snapshot returned an unmapped symbol")

    frames: dict[str, pd.DataFrame] = {}
    rows_by_symbol: dict[str, int] = {}
    first_by_symbol: dict[str, pd.Timestamp] = {}
    last_by_symbol: dict[str, pd.Timestamp] = {}
    value_columns = ["open", "high", "low", "close", "volume"]
    for symbol in symbols:
        frame = data.loc[data["symbol"] == symbol, ["ts", *value_columns]].copy()
        frame = frame.sort_values("ts").reset_index(drop=True)
        if frame.empty:
            raise ValueError(f"market snapshot has no rows for {symbol}")
        if frame["ts"].duplicated().any():
            raise ValueError(f"market snapshot has duplicate timestamps for {symbol}")
        for column in value_columns:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
        values = frame[value_columns].to_numpy(dtype=float)
        if not np.isfinite(values).all():
            raise ValueError(f"market snapshot has non-finite OHLCV for {symbol}")
        if (frame[["open", "high", "low", "close"]] <= 0.0).any().any():
            raise ValueError(f"market snapshot has non-positive price for {symbol}")
        if (frame["volume"] < 0.0).any():
            raise ValueError(f"market snapshot has negative volume for {symbol}")
        index = pd.DatetimeIndex(frame["ts"])
        if np.any(index.as_unit("ns").asi8 % _BAR.value != 0):
            raise ValueError(f"market snapshot timestamps are off the 15-minute grid for {symbol}")
        frames[symbol] = frame
        rows_by_symbol[symbol] = len(frame)
        first_by_symbol[symbol] = pd.Timestamp(frame["ts"].iloc[0])
        last_by_symbol[symbol] = pd.Timestamp(frame["ts"].iloc[-1])
    return MarketBundle(frames, rows_by_symbol, first_by_symbol, last_by_symbol)


def load_funding_snapshot(
    path: Path,
    spec: Mapping[str, Any],
    *,
    symbols: Sequence[str],
    venue: str,
    start: pd.Timestamp,
    engine_start: pd.Timestamp,
    end: pd.Timestamp,
) -> FundingBundle:
    """Load bare-base funding, preserving raw fractional timestamps for the engine."""

    if start > engine_start or engine_start >= end:
        raise ValueError("funding ranges must satisfy start <= engine_start < end")
    table_name = str(spec.get("table", ""))
    table = _identifier(table_name, label="funding table")
    connection = duckdb.connect(str(path), read_only=True)
    try:
        connection.execute("SET TimeZone = 'UTC'")
        columns = _columns(connection, table_name)
        required = {"venue", "symbol", "ts", "funding_rate"}
        missing = sorted(required.difference(columns))
        if missing:
            raise ValueError(f"funding snapshot missing columns: {missing}")
        has_mark = "mark_price" in columns
        raw_symbols = [
            row[0]
            for row in connection.execute(
                f"SELECT DISTINCT symbol FROM {table} WHERE venue=?", [venue]
            ).fetchall()
        ]
        symbol_map = _raw_symbol_map(raw_symbols, symbols, label="funding snapshot")
        native = [symbol_map[symbol] for symbol in symbols]
        placeholders = ",".join("?" for _ in native)
        mark_select = ", mark_price" if has_mark else ""
        query = (
            f"SELECT symbol, ts, funding_rate{mark_select} FROM {table} "
            f"WHERE venue=? AND ts>=? AND ts<? AND symbol IN ({placeholders}) "
            "ORDER BY symbol, ts"
        )
        data = connection.execute(
            query, [venue, start.to_pydatetime(), end.to_pydatetime(), *native]
        ).fetchdf()
    finally:
        connection.close()
    if data.empty:
        raise ValueError("funding snapshot query returned no rows")
    data["ts"] = _utc_series(data["ts"], label="funding snapshot")
    inverse = {raw: symbol for symbol, raw in symbol_map.items()}
    data["symbol"] = data["symbol"].map(inverse)
    data["funding_rate"] = pd.to_numeric(data["funding_rate"], errors="coerce")
    if data["symbol"].isna().any() or not np.isfinite(data["funding_rate"]).all():
        raise ValueError("funding snapshot contains unmapped or non-finite values")
    if has_mark:
        data["mark_price"] = pd.to_numeric(data["mark_price"], errors="coerce")

    signal_rates: dict[str, pd.DataFrame] = {}
    rows_by_symbol: dict[str, int] = {}
    engine_events: list[dict[str, Any]] = []
    for symbol in symbols:
        keep = ["ts", "funding_rate", *(["mark_price"] if has_mark else [])]
        frame = data.loc[data["symbol"] == symbol, keep].copy().sort_values("ts")
        frame = frame.reset_index(drop=True)
        if frame.empty:
            raise ValueError(f"funding snapshot has no rows for {symbol}")
        if frame["ts"].duplicated().any():
            raise ValueError(f"funding snapshot has duplicate raw timestamps for {symbol}")
        signal_rates[symbol] = frame.loc[:, ["ts", "funding_rate"]].copy()
        rows_by_symbol[symbol] = len(frame)
        for row in frame.itertuples(index=False):
            if pd.Timestamp(row.ts) < engine_start:
                continue
            mark: float | None = None
            if has_mark and pd.notna(row.mark_price):
                parsed_mark = float(row.mark_price)
                if math.isfinite(parsed_mark) and parsed_mark > 0.0:
                    mark = parsed_mark
            engine_events.append(
                {
                    "symbol": symbol,
                    "ts": row.ts,
                    "rate": float(row.funding_rate),
                    "mark_price": mark,
                }
            )
    engine_events.sort(key=lambda item: (item["ts"], item["symbol"]))
    return FundingBundle(signal_rates, tuple(engine_events), rows_by_symbol)


def _required_int(config: Mapping[str, Any], key: str) -> int:
    value = config.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{key} must be an integer >= 1")
    return value


def _required_float(config: Mapping[str, Any], key: str, *, positive: bool = True) -> float:
    value = config.get(key)
    if isinstance(value, bool):
        raise ValueError(f"{key} must be numeric")
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{key} must be numeric") from exc
    if not math.isfinite(parsed) or (positive and parsed <= 0.0):
        raise ValueError(f"{key} must be finite{' and > 0' if positive else ''}")
    if not positive and parsed < 0.0:
        raise ValueError(f"{key} must be >= 0")
    return parsed


def build_candidate_cells(prereg: Mapping[str, Any]) -> tuple[PairCell, ...]:
    raw_cells = prereg.get("candidate_cells")
    if not isinstance(raw_cells, list) or len(raw_cells) != 3:
        raise ValueError("candidate_cells must contain exactly three cells")
    cells: list[PairCell] = []
    ids: set[str] = set()
    for raw in raw_cells:
        if not isinstance(raw, dict) or raw.get("family") != "dynamic_cointegrated_pairs":
            raise ValueError("every v17 cell must be a dynamic_cointegrated_pairs mapping")
        candidate_id = str(raw.get("id", "")).strip()
        if not candidate_id or candidate_id in ids:
            raise ValueError("candidate IDs must be non-empty and unique")
        ids.add(candidate_id)
        half_life = raw.get("half_life_hours")
        if not isinstance(half_life, list) or len(half_life) != 2:
            raise ValueError("half_life_hours must contain exactly two bounds")
        cells.append(
            PairCell(
                candidate_id=candidate_id,
                train_hours=_required_int(raw, "train_hours"),
                validation_hours=_required_int(raw, "validation_hours"),
                entry_abs_z=_required_float(raw, "entry_abs_z"),
                exit_abs_z=_required_float(raw, "exit_abs_z"),
                disaster_abs_z=_required_float(raw, "disaster_abs_z"),
                half_life_min_hours=float(half_life[0]),
                half_life_max_hours=float(half_life[1]),
                max_hold_hours=_required_int(raw, "max_hold_hours"),
                cooldown_hours=_required_int(raw, "cooldown_hours"),
            )
        )
    return tuple(cells)


def build_policy(prereg: Mapping[str, Any]) -> PairPortfolioPolicy:
    risk = prereg["risk_and_execution"]
    throttle = risk["dd_throttle"]
    exit_contract = prereg["exit_contract"]["structural_break"]
    gap_minutes = _required_int(prereg["data_contract"]["gap_policy"], "max_contiguous_gap_minutes")
    return PairPortfolioPolicy(
        initial_equity=_required_float(risk, "initial_equity"),
        risk_per_pair_episode=_required_float(risk, "risk_per_pair_episode_pct") / 100.0,
        max_leg_notional_pct=_required_float(risk, "max_leg_notional_pct_equity") / 100.0,
        max_pairs=_required_int(risk, "max_pairs"),
        max_legs=_required_int(risk, "max_legs"),
        leverage=_required_float(risk, "max_leverage"),
        dd_throttle_threshold=_required_float(throttle, "threshold_pct") / 100.0,
        dd_throttle_multiplier=_required_float(throttle, "risk_multiplier"),
        gap_max_minutes=gap_minutes,
        bar_minutes=15,
        structural_mean_window_hours=_required_int(exit_contract, "residual_mean_window_hours"),
        structural_distance_sigma=_required_float(exit_contract, "distance_from_frozen_mean_sigma"),
        structural_consecutive_hourly_checks=_required_int(
            exit_contract, "consecutive_hourly_checks"
        ),
        structural_min_completeness=_required_float(
            prereg["data_contract"], "minimum_hourly_completeness_each_window"
        ),
    )


def _scenario_models(prereg: Mapping[str, Any]) -> dict[str, tuple[PairCostModel, float, float]]:
    risk = prereg["risk_and_execution"]
    base = risk["execution_costs_bps_per_leg"]
    raw_scenarios = risk["cost_scenarios"]
    if not isinstance(raw_scenarios, dict) or set(raw_scenarios) != set(SCENARIO_ORDER):
        raise ValueError("cost_scenarios must be exactly B, C2 and H")
    result: dict[str, tuple[PairCostModel, float, float]] = {}
    for name in SCENARIO_ORDER:
        scenario = raw_scenarios[name]
        result[name] = (
            PairCostModel(
                fee_bps_per_leg=_required_float(base, "fee", positive=False),
                spread_slippage_bps_per_leg=_required_float(
                    base, "spread_and_slippage", positive=False
                ),
                impact_bps_per_leg=_required_float(base, "impact", positive=False),
                funding_multiplier=_required_float(scenario, "funding_multiplier", positive=False),
                cost_multiplier=_required_float(scenario, "cost_multiplier", positive=False),
            ),
            _required_float(scenario, "positive_pnl_multiplier"),
            _required_float(scenario, "negative_pnl_multiplier"),
        )
    return result


def _evaluation_windows(prereg: Mapping[str, Any]) -> dict[str, tuple[pd.Timestamp, pd.Timestamp]]:
    protocol = prereg["time_protocol"]
    complete = tuple(
        _utc_timestamp(value, label="complete boundary")
        for value in protocol["complete_months_utc"]
    )
    development = tuple(
        _utc_timestamp(value, label="development boundary") for value in protocol["development"]
    )
    common_is = tuple(
        _utc_timestamp(value, label="common-IS boundary")
        for value in prereg["validation_metrics"]["common_IS_ratio_window"]
    )
    folds = protocol["expanding_walk_forward"]
    if len(complete) != 2 or len(development) != 2 or len(common_is) != 2:
        raise ValueError("evaluation ranges must have two boundaries")
    if not isinstance(folds, list) or len(folds) != 6:
        raise ValueError("expanding_walk_forward must contain six folds")
    parsed_folds = [
        (
            _utc_timestamp(raw[0], label="fold start"),
            _utc_timestamp(raw[1], label="fold end"),
        )
        for raw in folds
    ]
    windows: dict[str, tuple[pd.Timestamp, pd.Timestamp]] = {
        "complete": (complete[0], complete[1]),
        "development": (development[0], development[1]),
        "common_is": (common_is[0], common_is[1]),
        "pseudo_oos": (parsed_folds[0][0], parsed_folds[-1][1]),
    }
    windows.update(
        {f"walk_forward_{index + 1}": bounds for index, bounds in enumerate(parsed_folds)}
    )
    if any(start >= end for start, end in windows.values()):
        raise ValueError("every evaluation window must be increasing")
    if development[0] != complete[0] or development[1] != parsed_folds[0][0]:
        raise ValueError("development and pseudo-OOS windows must be contiguous")
    if parsed_folds[-1][1] != complete[1]:
        raise ValueError("pseudo-OOS end must equal complete end")
    for previous, current in pairwise(parsed_folds):
        if previous[1] != current[0]:
            raise ValueError("walk-forward folds must be contiguous")
    if not complete[0] <= common_is[0] < common_is[1] <= development[1]:
        raise ValueError("common-IS window must lie inside development")
    return windows


def _history_start(start: pd.Timestamp, cells: Sequence[PairCell]) -> pd.Timestamp:
    required_hours = max(cell.train_hours + cell.validation_hours for cell in cells)
    return start - pd.Timedelta(hours=required_hours)


def _partition_symbols(prereg: Mapping[str, Any], partition: str) -> tuple[str, ...]:
    if partition != "primary":
        raise ValueError(
            "holdout replay is locked until a primary winner, LOSO, and one-shot "
            "holdout authorization have been recorded"
        )
    return tuple(str(symbol) for symbol in prereg["universe"]["primary_symbols"])


def _selection_payload(
    selections: Mapping[datetime, Sequence[PairModel]],
    diagnostics: Mapping[datetime, Sequence[PairSelectionDecision]],
) -> tuple[list[dict[str, Any]], list[PairModel]]:
    if set(selections) != set(diagnostics):
        raise ValueError("selection and diagnostic ledgers must have identical timestamps")
    ledger: list[dict[str, Any]] = []
    flattened: list[PairModel] = []
    for selection_ts, raw_models in sorted(selections.items()):
        models = tuple(raw_models)
        decisions = tuple(diagnostics[selection_ts])
        selected = {model.pair_id for model in models}
        decision_pairs = [decision.pair_id for decision in decisions]
        selected_decisions = {
            decision.pair_id for decision in decisions if decision.status == "selected"
        }
        if len(decision_pairs) != len(set(decision_pairs)):
            raise ValueError("selection diagnostics contain duplicate pair IDs")
        if selected != selected_decisions:
            raise ValueError("selected models and selected diagnostic decisions disagree")
        flattened.extend(models)
        ledger.append(
            {
                "selection_ts": selection_ts,
                "selected_pair_ids": sorted(selected),
                "selected_models": list(models),
                "pair_decisions": list(decisions),
                "rejected_pair_reasons": [
                    decision for decision in decisions if decision.status == "rejected"
                ],
            }
        )
    return ledger, flattened


def _evidence_window(
    result: PairPortfolioResult, *, start: pd.Timestamp, end: pd.Timestamp
) -> dict[str, Any]:
    summary = scenario_window_summary(result, start=start, end=end)
    economic = economic_episode_frame(result, start=start, end=end)
    start_dt = start.to_pydatetime()
    end_dt = end.to_pydatetime()
    nav_observations = np.asarray(
        [float(nav) for timestamp, nav in result.equity_curve if start_dt <= timestamp < end_dt],
        dtype=float,
    )
    if len(nav_observations) != summary.equity_observations:
        raise RuntimeError("evidence NAV observation count disagrees with window summary")
    nav_sum = float(nav_observations.sum())
    nav_mean = float(nav_observations.mean()) if len(nav_observations) else None
    monthly_returns = {
        str(month): float(value) for month, value in summary.monthly_returns_pct.items()
    }
    previous = summary.baseline_equity
    monthly_pnl: dict[str, float] = {}
    for month, return_pct in monthly_returns.items():
        ending = previous * (1.0 + return_pct / 100.0)
        monthly_pnl[month] = ending - previous
        previous = ending
    economic_funding = float(economic["funding_cashflow"].sum()) if not economic.empty else 0.0
    return {
        "start_inclusive": summary.start.isoformat(),
        "end_exclusive": summary.end.isoformat(),
        "baseline_equity": summary.baseline_equity,
        "pre_window_peak_equity": summary.pre_window_peak_equity,
        "ending_equity": summary.ending_equity,
        "total_return_pct": ((summary.ending_equity / summary.baseline_equity - 1.0) * 100.0),
        "equity_observations": summary.equity_observations,
        "nav_observation_sum": nav_sum,
        "arithmetic_mean_15m_nav": nav_mean,
        "max_mtm_drawdown_pct": summary.max_mtm_drawdown_pct,
        "max_recovery_months": summary.max_recovery_months,
        "active_months": summary.active_months,
        "active_month_definition": summary.active_month_definition,
        "monthly_active_exposure": {
            str(month): bool(value) for month, value in summary.monthly_active_exposure.items()
        },
        "closed_pair_episodes": summary.closed_episodes,
        "terminal_open_pair_pseudo_episodes": summary.terminal_pseudo_episodes,
        "high_spread_closed_episodes": summary.high_spread_closed_episodes,
        "low_spread_closed_episodes": summary.low_spread_closed_episodes,
        "closed_episode_execution_cost": summary.closed_episode_execution_cost,
        "closed_episode_funding_cashflow": summary.closed_episode_funding_cashflow,
        "closed_episode_gross_pair_price_pnl": summary.closed_episode_gross_pair_price_pnl,
        "closed_episode_adjusted_pair_price_pnl": (summary.closed_episode_adjusted_pair_price_pnl),
        "closed_episode_net_pnl": summary.closed_episode_net_pnl,
        "economic_episode_count_including_terminal": len(economic),
        "economic_terminal_rows_are_closed_samples": False,
        "economic_episode_execution_cost": (
            float(economic["execution_cost"].sum()) if not economic.empty else 0.0
        ),
        "economic_episode_funding_cashflow": economic_funding,
        "economic_episode_gross_pair_price_pnl": (
            float(economic["gross_pair_price_pnl"].sum()) if not economic.empty else 0.0
        ),
        "economic_episode_adjusted_pair_price_pnl": (
            float(economic["adjusted_pair_price_pnl"].sum()) if not economic.empty else 0.0
        ),
        "economic_episode_net_pnl": (
            float(economic["net_pnl"].sum()) if not economic.empty else 0.0
        ),
        "monthly_returns_unit": "percentage_points",
        "monthly_returns_pct": monthly_returns,
        "monthly_pnl": monthly_pnl,
    }


def _frame_ledger(frame: pd.DataFrame) -> list[dict[str, Any]]:
    return [_jsonable(record) for record in frame.to_dict("records")]


def _scenario_payload(
    result: PairPortfolioResult,
    *,
    windows: Mapping[str, tuple[pd.Timestamp, pd.Timestamp]],
) -> dict[str, Any]:
    closed = _frame_ledger(closed_episode_frame(result))
    terminal = _frame_ledger(terminal_episode_frame(result))
    economic = _frame_ledger(economic_episode_frame(result))
    if len(result.rejection_details) != len(result.rejections):
        raise RuntimeError("timestamped rejection details disagree with rejection tuples")
    rejections = [_jsonable(rejection) for rejection in result.rejection_details]
    curve_digest_rows = [
        (pd.Timestamp(ts).isoformat(), float(nav)) for ts, nav in result.equity_curve
    ]
    return {
        "initial_equity": float(result.initial_equity),
        "final_equity": float(result.final_equity),
        "max_mtm_drawdown_pct": float(-result.max_drawdown * 100.0),
        "total_execution_cost": float(result.total_execution_cost),
        "accrued_exit_cost": float(result.accrued_exit_cost),
        "total_funding_cashflow": float(result.total_funding_cashflow),
        "open_pair_count": result.open_pair_count,
        "open_leg_count": result.open_leg_count,
        "quarantined_pairs": _jsonable(result.quarantined_pairs),
        "engine_monthly_returns": [
            {"month": month, "return_pct": float(value) * 100.0}
            for month, value in result.monthly_returns
        ],
        "equity_curve_observations": len(result.equity_curve),
        "equity_curve_sha256": _payload_sha256(curve_digest_rows),
        "closed_episode_ledger": closed,
        "closed_episode_ledger_sha256": _payload_sha256(closed),
        "terminal_episode_ledger": terminal,
        "terminal_episode_ledger_sha256": _payload_sha256(terminal),
        "economic_episode_ledger": economic,
        "economic_episode_ledger_sha256": _payload_sha256(economic),
        "economic_terminal_rows_are_closed_samples": False,
        "rejections": rejections,
        "rejection_counts": dict(sorted(Counter(item["reason"] for item in rejections).items())),
        "rejections_sha256": _payload_sha256(rejections),
        "windows": {
            name: _evidence_window(result, start=bounds[0], end=bounds[1])
            for name, bounds in windows.items()
        },
    }


def _research_source_provenance(repo_root: Path) -> dict[str, Any]:
    relative_files = (
        "configs/crypto_15m_v17_pairs_prereg.yaml",
        "docs/CRYPTO_15M_V17_PAIRS_PREREG_2026-07-11.md",
        "scripts/research/crypto_15m_v17_pairs_program.py",
        "src/price_action/lab/crypto_15m_pairs_engine.py",
        "src/price_action/lab/crypto_15m_pairs_evidence.py",
        "src/price_action/lab/crypto_15m_pairs_program.py",
        "src/price_action/lab/crypto_15m_pairs_signals.py",
        "src/price_action/lab/crypto_15m_pairs_validation.py",
        "src/price_action/lab/crypto_15m_validation.py",
    )
    existing = tuple(relative for relative in relative_files if (repo_root / relative).is_file())
    missing_files = sorted(set(relative_files).difference(existing))
    hashes = {relative: sha256_file(repo_root / relative) for relative in existing}
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        status = subprocess.run(
            ["git", "status", "--porcelain", "--", *relative_files],
            cwd=repo_root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        commit = "UNAVAILABLE"
        status = "UNAVAILABLE"
    return {
        "git_commit": commit,
        "research_source_clean": status == "" and not missing_files,
        "research_source_status": status.splitlines(),
        "missing_source_files": missing_files,
        "file_sha256": hashes,
    }


def _base_plan(
    prereg: Mapping[str, Any],
    prereg_path: Path,
    *,
    repo_root: Path,
    source_provenance: Mapping[str, Any] | None = None,
    prereg_sha256: str | None = None,
) -> dict[str, Any]:
    cells = build_candidate_cells(prereg)
    policy = build_policy(prereg)
    snapshots = prereg["snapshots"]
    return {
        "schema_version": PROGRAM_SCHEMA,
        "evidence_eligible": False,
        "preregistration": {
            "path": str(prereg_path.resolve()),
            "sha256": prereg_sha256 or sha256_file(prereg_path.resolve()),
            "schema_version": prereg["schema_version"],
            "status": prereg["status"],
            "live_deployment_authorized": prereg["live_deployment_authorized"],
        },
        "candidate_ids": [cell.candidate_id for cell in cells],
        "candidate_count": len(cells),
        "scenario_order": list(SCENARIO_ORDER),
        "source_provenance": (
            dict(source_provenance)
            if source_provenance is not None
            else _research_source_provenance(repo_root)
        ),
        "policy": asdict(policy),
        "snapshots": {
            name: {
                "configured_path": str(snapshots[name]["path"]),
                "expected_bytes": int(snapshots[name]["bytes"]),
                "expected_sha256": str(snapshots[name]["sha256"]),
                "status": "NOT_ACCESSED",
            }
            for name in ("market", "funding")
        },
    }


def run_program(
    prereg_path: Path,
    *,
    repo_root: Path,
    partition: str = "primary",
) -> dict[str, Any]:
    """Verify both snapshots, select monthly pairs, then replay B/C2/H sequentially."""

    prereg_path = prereg_path.resolve()
    repo_root = repo_root.resolve()
    prereg = load_preregistration(prereg_path)
    cells = build_candidate_cells(prereg)
    policy = build_policy(prereg)
    scenarios = _scenario_models(prereg)
    windows = _evaluation_windows(prereg)
    snapshots = prereg["snapshots"]
    trade_symbols = _partition_symbols(prereg, partition)
    canonical_prereg_path = _require_canonical_preregistration(
        prereg, prereg_path=prereg_path, repo_root=repo_root
    )
    preflight_prereg_sha256 = sha256_file(canonical_prereg_path)
    preflight_source = _research_source_provenance(repo_root)
    if not preflight_source["research_source_clean"]:
        raise RuntimeError(
            "v17 execute requires clean research source before snapshot access: "
            f"{preflight_source['research_source_status']}"
        )

    # This mapping must finish before either load function can open DuckDB.
    verified = {
        name: verify_frozen_snapshot(name, snapshots[name], repo_root=repo_root)
        for name in ("market", "funding")
    }

    evaluation_start, evaluation_end = windows["complete"]
    history_start = _history_start(evaluation_start, cells)
    reference = str(prereg["universe"]["reference_symbol"])
    market_symbols = (*trade_symbols, reference)
    market_spec = snapshots["market"]
    market = load_market_snapshot(
        Path(verified["market"].resolved_path),
        market_spec,
        symbols=market_symbols,
        start=history_start,
        end=evaluation_end,
    )
    funding = load_funding_snapshot(
        Path(verified["funding"].resolved_path),
        snapshots["funding"],
        symbols=trade_symbols,
        venue=str(market_spec["venue"]),
        start=history_start,
        engine_start=evaluation_start,
        end=evaluation_end,
    )

    engine_frames = {
        symbol: frame.loc[
            (frame["ts"] >= evaluation_start) & (frame["ts"] < evaluation_end)
        ].reset_index(drop=True)
        for symbol, frame in market.frames.items()
    }
    if any(frame.empty for frame in engine_frames.values()):
        raise ValueError("every engine frame must cover at least one evaluation bar")

    cell_streams: dict[str, dict[str, Any]] = {}
    for cell in cells:
        selections, selection_diagnostics = select_pairs_monthly_with_diagnostics(
            market.frames,
            trade_symbols,
            cell,
            start=evaluation_start,
            end=evaluation_end,
            snapshot_sha256=verified["market"].sha256,
            btc_symbol=reference,
            minimum_completeness=float(
                prereg["data_contract"]["minimum_hourly_completeness_each_window"]
            ),
        )
        selection_ledger, models = _selection_payload(selections, selection_diagnostics)
        intents = tuple(
            intent
            for intent in generate_pair_entry_intents(
                market.frames,
                funding.signal_rates,
                cell,
                selections,
                btc_symbol=reference,
            )
            if evaluation_start.to_pydatetime() <= intent.entry_ts < evaluation_end.to_pydatetime()
        )
        if any(reference in {model.y_symbol, model.x_symbol} for model in models):
            raise RuntimeError("BTC reference leaked into a selected tradable pair")
        if any(reference in {intent.y_symbol, intent.x_symbol} for intent in intents):
            raise RuntimeError("BTC reference leaked into a tradable intent")
        events = tuple(
            PairSelectionEvent(
                candidate_id=cell.candidate_id,
                selection_ts=selection_ts,
                selected_pair_ids=tuple(model.pair_id for model in raw_models),
            )
            for selection_ts, raw_models in sorted(selections.items())
        )
        cell_streams[cell.candidate_id] = {
            "selection_ledger": selection_ledger,
            "models": tuple(models),
            "intents": intents,
            "selection_events": events,
        }

    results: dict[str, dict[str, Any]] = {}
    for cell in cells:
        streams = cell_streams[cell.candidate_id]
        cell_results: dict[str, Any] = {}
        for scenario_name in SCENARIO_ORDER:  # Frozen sequential replay order.
            cost, positive_multiplier, negative_multiplier = scenarios[scenario_name]
            replay = simulate_pair_portfolio(
                engine_frames,
                streams["intents"],
                streams["models"],
                funding.engine_events,
                cost,
                policy,
                selection_events=streams["selection_events"],
                positive_payoff_multiplier=positive_multiplier,
                negative_payoff_multiplier=negative_multiplier,
            )
            cell_results[scenario_name] = _scenario_payload(replay, windows=windows)
        results[cell.candidate_id] = cell_results

    # Fail closed if source or either immutable input changed while results were
    # being computed.  No result payload is returned before this postflight.
    postflight_verified = {
        name: verify_frozen_snapshot(name, snapshots[name], repo_root=repo_root)
        for name in ("market", "funding")
    }
    postflight_source = _research_source_provenance(repo_root)
    postflight_prereg_sha256 = sha256_file(canonical_prereg_path)
    source_unchanged = (
        postflight_source["research_source_clean"]
        and postflight_source["git_commit"] == preflight_source["git_commit"]
        and postflight_source["file_sha256"] == preflight_source["file_sha256"]
    )
    snapshots_unchanged = all(
        asdict(postflight_verified[name]) == asdict(verified[name])
        for name in ("market", "funding")
    )
    if not source_unchanged:
        raise RuntimeError("research source changed during v17 replay")
    if postflight_prereg_sha256 != preflight_prereg_sha256:
        raise RuntimeError("canonical preregistration changed during v17 replay")
    if not snapshots_unchanged:
        raise RuntimeError("a frozen snapshot changed during v17 replay")

    payload = _base_plan(
        prereg,
        prereg_path,
        repo_root=repo_root,
        source_provenance=postflight_source,
        prereg_sha256=preflight_prereg_sha256,
    )
    source_clean = bool(postflight_source["research_source_clean"])
    stream_payload: dict[str, Any] = {}
    for candidate_id, streams in cell_streams.items():
        selection_ledger = _jsonable(streams["selection_ledger"])
        models = _jsonable(streams["models"])
        intents = _jsonable(streams["intents"])
        stream_payload[candidate_id] = {
            "pair_selection_ledger": selection_ledger,
            "pair_selection_ledger_sha256": _payload_sha256(selection_ledger),
            "pair_models": models,
            "pair_models_sha256": _payload_sha256(models),
            "entry_intents": intents,
            "entry_intents_sha256": _payload_sha256(intents),
        }
    payload.update(
        {
            "mode": "FULL_FROZEN_REPLAY",
            "evidence_eligible": source_clean,
            "evidence_ineligible_reasons": [] if source_clean else ["RESEARCH_SOURCE_DIRTY"],
            "partition": partition,
            "snapshots": {name: asdict(value) for name, value in verified.items()},
            "execution_governance": {
                "canonical_prereg_path": str(canonical_prereg_path),
                "canonical_prereg_semantic_match": True,
                "canonical_prereg_preflight_sha256": preflight_prereg_sha256,
                "canonical_prereg_postflight_sha256": postflight_prereg_sha256,
                "clean_source_preflight": True,
                "source_unchanged_postflight": source_unchanged,
                "snapshots_reverified_postflight": True,
                "snapshots_unchanged_postflight": snapshots_unchanged,
                "preflight_git_commit": preflight_source["git_commit"],
                "postflight_git_commit": postflight_source["git_commit"],
                "preflight_source_file_sha256": preflight_source["file_sha256"],
                "postflight_source_file_sha256": postflight_source["file_sha256"],
                "postflight_snapshots": {
                    name: asdict(value) for name, value in postflight_verified.items()
                },
            },
            "time_range_utc": {
                "history_start_inclusive": history_start.isoformat(),
                "evaluation_start_inclusive": evaluation_start.isoformat(),
                "end_exclusive": evaluation_end.isoformat(),
                "windows": {
                    name: {
                        "start_inclusive": bounds[0].isoformat(),
                        "end_exclusive": bounds[1].isoformat(),
                    }
                    for name, bounds in windows.items()
                },
            },
            "market_loading": {
                "symbols": list(market_symbols),
                "frame_count": len(market.frames),
                "alignment": "INDEPENDENT_SYMBOL_FRAMES",
                "global_intersection_performed": False,
                "forward_fill_performed": False,
                "rows_by_symbol": market.rows_by_symbol,
                "first_ts_by_symbol": _jsonable(market.first_ts_by_symbol),
                "last_ts_by_symbol": _jsonable(market.last_ts_by_symbol),
                "engine_rows_by_symbol": {
                    symbol: len(frame) for symbol, frame in engine_frames.items()
                },
            },
            "funding": {
                "canonical_symbols": list(trade_symbols),
                "raw_fractional_seconds_preserved_until_engine": True,
                "invalid_or_null_mark_price_serialized_as_none": True,
                "signal_column": "funding_rate",
                "engine_column": "rate",
                "engine_event_count": len(funding.engine_events),
                "rows_by_symbol_including_signal_history": funding.rows_by_symbol,
            },
            "streams": stream_payload,
            "results": results,
        }
    )
    return payload


def dry_run(prereg_path: Path, *, repo_root: Path | None = None) -> dict[str, Any]:
    """Validate YAML and frozen code bindings without touching snapshot paths."""

    prereg_path = prereg_path.resolve()
    root = (repo_root or Path(__file__).resolve().parents[3]).resolve()
    prereg = load_preregistration(prereg_path)
    _scenario_models(prereg)
    _evaluation_windows(prereg)
    payload = _base_plan(prereg, prereg_path, repo_root=root)
    payload["mode"] = "DRY_RUN_NO_SNAPSHOT_ACCESS"
    return payload


def smoke_run(prereg_path: Path, *, repo_root: Path | None = None) -> dict[str, Any]:
    """Exercise the atomic engine entirely in memory; snapshots remain untouched."""

    payload = dry_run(prereg_path, repo_root=repo_root)
    candidate_id = str(payload["candidate_ids"][0])
    selection_ts = pd.Timestamp("2024-01-01T00:00:00Z")
    timestamps = pd.date_range("2024-01-01T00:45:00Z", periods=4, freq="15min")
    x_open = 100.0
    y_open = math.exp(0.3) * x_open
    frames = {
        "ETH/USDT": pd.DataFrame(
            {
                "ts": timestamps,
                "open": [y_open, y_open, 100.0, 100.0],
                "close": [y_open, 100.0, 100.0, 100.0],
            }
        ),
        "SOL/USDT": pd.DataFrame({"ts": timestamps, "open": 100.0, "close": 100.0}),
    }
    intent = PairEntryIntent(
        candidate_id=candidate_id,
        pair_id="ETH/USDT|SOL/USDT",
        selection_ts=selection_ts.to_pydatetime(),
        decision_ts=timestamps[0].to_pydatetime(),
        entry_ts=timestamps[1].to_pydatetime(),
        y_symbol="ETH/USDT",
        x_symbol="SOL/USDT",
        y_side="short",
        x_side="long",
        z_score=3.0,
        alpha=0.0,
        beta=1.0,
        validation_mean=0.0,
        validation_std=0.1,
        gross_weight_y=0.5,
        gross_weight_x=0.5,
        entry_abs_z=2.5,
        exit_abs_z=0.5,
        disaster_abs_z=4.5,
        max_hold_hours=168,
        cooldown_hours=48,
        expected_convergence_return=0.125,
        adverse_funding=0.0,
        stressed_required_return=0.0171,
    )
    result = simulate_pair_portfolio(
        frames,
        [intent],
        funding_events=(),
        cost=PairCostModel(0.0, 0.0, 0.0),
        policy=PairPortfolioPolicy(),
        selection_events=[
            PairSelectionEvent(
                candidate_id=candidate_id,
                selection_ts=selection_ts.to_pydatetime(),
                selected_pair_ids=(intent.pair_id,),
            )
        ],
    )
    payload["mode"] = "SMOKE_IN_MEMORY_NO_SNAPSHOT_ACCESS"
    payload["smoke"] = {
        "closed_pair_episodes": len(result.episodes),
        "terminal_open_pair_episodes": len(result.terminal_episodes),
        "final_equity": float(result.final_equity),
        "reference_symbol_traded": any(
            "BTC/USDT" in {episode.y_symbol, episode.x_symbol}
            for episode in (*result.episodes, *result.terminal_episodes)
        ),
    }
    return payload


def deterministic_json(payload: Mapping[str, Any]) -> str:
    """Render stable strict JSON; NaN and Infinity are forbidden."""

    return json.dumps(_jsonable(payload), sort_keys=True, indent=2, allow_nan=False) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--prereg", type=Path, default=Path("configs/crypto_15m_v17_pairs_prereg.yaml")
    )
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--execute", action="store_true", help="run the frozen DuckDB replay")
    modes.add_argument("--smoke", action="store_true", help="in-memory contract smoke only")
    modes.add_argument("--dry-run", action="store_true", help="YAML validation only (default)")
    parser.add_argument("--partition", choices=("primary",), default="primary")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)

    if args.execute:
        payload = run_program(args.prereg, repo_root=args.repo_root, partition=args.partition)
    elif args.smoke:
        payload = smoke_run(args.prereg, repo_root=args.repo_root)
    else:
        payload = dry_run(args.prereg, repo_root=args.repo_root)
    rendered = deterministic_json(payload)
    if args.output is None:
        print(rendered, end="")
    else:
        output = args.output.resolve()
        if output == args.prereg.resolve():
            raise ValueError("results may not overwrite the preregistration")
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered, encoding="utf-8")
    return 0


__all__ = [
    "FundingBundle",
    "MarketBundle",
    "SnapshotVerification",
    "build_candidate_cells",
    "build_policy",
    "deterministic_json",
    "dry_run",
    "load_funding_snapshot",
    "load_market_snapshot",
    "load_preregistration",
    "main",
    "normalize_usdt_symbol",
    "run_program",
    "sha256_file",
    "smoke_run",
    "verify_frozen_snapshot",
]
