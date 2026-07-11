"""Frozen-data integration runner for the crypto 15-minute v16 research batch.

The module is intentionally conservative at its IO boundary: both DuckDB files
must match the preregistered byte size and SHA256 before either is opened.  Signal
generation happens once per candidate over the full cross-sectional universe;
development/holdout symbol views are applied only afterwards.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import subprocess
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

import duckdb
import numpy as np
import pandas as pd
import yaml

from price_action.lab.crypto_15m_event_engine import (
    CostModel,
    PortfolioPolicy,
    PortfolioResult,
    SignalIntent,
    simulate_portfolio,
)
from price_action.lab.crypto_15m_evidence import ledger_frame, scenario_window_summary
from price_action.lab.crypto_15m_residual_signals import (
    FundingReversionCell,
    ResidualTrendCell,
    generate_funding_confirmed_residual_reversion_intents,
    generate_residual_cross_sectional_trend_intents,
)

PROGRAM_SCHEMA = "crypto-15m-v16-run-v1"
PREREG_SCHEMA = "crypto-15m-v16-prereg-v1"
SCENARIO_ORDER = ("B", "C2", "H")
SYMBOL_VIEW = Literal["all", "development", "holdout"]
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
    frames: dict[str, pd.DataFrame]
    raw_rows_by_symbol: dict[str, int]
    dropped_rows_by_symbol: dict[str, int]
    common_rows: int
    first_ts: pd.Timestamp
    last_ts: pd.Timestamp


@dataclass(frozen=True, slots=True)
class FundingBundle:
    signal_rates: dict[str, pd.DataFrame]
    engine_events: tuple[dict[str, Any], ...]
    rows_by_symbol: dict[str, int]


CandidateCell = ResidualTrendCell | FundingReversionCell


def sha256_file(path: Path, *, chunk_bytes: int = 8 * 1024 * 1024) -> str:
    """Stream a file hash without loading a snapshot into memory."""

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while block := handle.read(chunk_bytes):
            digest.update(block)
    return digest.hexdigest()


def load_preregistration(path: Path) -> dict[str, Any]:
    """Load and minimally validate the immutable preregistration contract."""

    raw = path.read_bytes()
    loaded = yaml.safe_load(raw)
    if not isinstance(loaded, dict):
        raise ValueError("preregistration must be a YAML mapping")
    if loaded.get("schema_version") != PREREG_SCHEMA:
        raise ValueError(f"unsupported preregistration schema: {loaded.get('schema_version')!r}")
    if loaded.get("status") != "PREREGISTERED_NO_RESULTS_SEEN":
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
    symbols = universe.get("symbols")
    if not isinstance(symbols, list) or len(symbols) != 18 or len(set(symbols)) != 18:
        raise ValueError("the frozen universe must contain exactly 18 unique symbols")
    if not isinstance(cells, list) or len(cells) != 6:
        raise ValueError("the frozen batch must contain exactly six candidate cells")
    return loaded


def _snapshot_path(spec: Mapping[str, Any], repo_root: Path) -> Path:
    configured = Path(str(spec.get("path", "")))
    if not configured.as_posix():
        raise ValueError("snapshot path is missing")
    return configured if configured.is_absolute() else repo_root / configured


def verify_frozen_snapshot(
    name: str, spec: Mapping[str, Any], *, repo_root: Path
) -> SnapshotVerification:
    """Require an exact regular-file size and SHA256 match."""

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
    """Map spot/perpetual database spellings to canonical ``BASE/USDT``."""

    text = str(value).strip().upper()
    if not text:
        raise ValueError("empty symbol")
    text = text.split(":", 1)[0].replace("-", "/").replace("_", "/")
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
        timestamp = timestamp.tz_localize("UTC")
    else:
        timestamp = timestamp.tz_convert("UTC")
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
    """Load, normalize, and align all 18 OHLCV frames on their intersection."""

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

    indexed: dict[str, pd.DataFrame] = {}
    raw_counts: dict[str, int] = {}
    for symbol in symbols:
        frame = data.loc[
            data["symbol"] == symbol, ["ts", "open", "high", "low", "close", "volume"]
        ].copy()
        frame = frame.sort_values("ts")
        if frame.empty:
            raise ValueError(f"market snapshot has no rows for {symbol}")
        if frame["ts"].duplicated().any():
            raise ValueError(f"market snapshot has duplicate timestamps for {symbol}")
        for column in ("open", "high", "low", "close", "volume"):
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
        if not np.isfinite(frame[["open", "high", "low", "close", "volume"]]).all().all():
            raise ValueError(f"market snapshot has non-finite OHLCV for {symbol}")
        frame = frame.set_index("ts", drop=False)
        indexed[symbol] = frame
        raw_counts[symbol] = len(frame)

    common: pd.DatetimeIndex | None = None
    for symbol in symbols:
        index = pd.DatetimeIndex(indexed[symbol].index)
        common = index if common is None else common.intersection(index, sort=False)
    assert common is not None
    common = common.sort_values()
    if common.empty:
        raise ValueError("the 18 market frames have no common timestamps")
    if len(common) > 1:
        deltas = common[1:] - common[:-1]
        if np.any(deltas <= pd.Timedelta(0)) or np.any((deltas / _BAR) % 1 != 0):
            raise ValueError("common timestamps are not on a 15-minute UTC grid")
    aligned = {symbol: indexed[symbol].loc[common].reset_index(drop=True) for symbol in symbols}
    dropped = {symbol: raw_counts[symbol] - len(common) for symbol in symbols}
    return MarketBundle(
        frames=aligned,
        raw_rows_by_symbol=raw_counts,
        dropped_rows_by_symbol=dropped,
        common_rows=len(common),
        first_ts=common[0],
        last_ts=common[-1],
    )


def load_funding_snapshot(
    path: Path,
    spec: Mapping[str, Any],
    *,
    symbols: Sequence[str],
    venue: str,
    start: pd.Timestamp,
    end: pd.Timestamp,
) -> FundingBundle:
    """Load funding once and expose signal ``funding_rate`` plus engine ``rate``."""

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
        # One eight-hour funding interval before the first bar is signal context only.
        data = connection.execute(
            query,
            [venue, (start - pd.Timedelta(hours=8)).to_pydatetime(), end.to_pydatetime(), *native],
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
        columns_to_keep = ["ts", "funding_rate"]
        frame = data.loc[
            data["symbol"] == symbol, columns_to_keep + (["mark_price"] if has_mark else [])
        ].copy()
        frame = frame.sort_values("ts")
        if frame.empty:
            raise ValueError(f"funding snapshot has no rows for {symbol}")
        if frame["ts"].duplicated().any():
            raise ValueError(f"funding snapshot has duplicate timestamps for {symbol}")
        signal_rates[symbol] = frame.loc[:, columns_to_keep].reset_index(drop=True)
        rows_by_symbol[symbol] = len(frame)
        for row in frame.itertuples(index=False):
            if row.ts < start:
                continue
            event: dict[str, Any] = {
                "symbol": symbol,
                "ts": row.ts.to_pydatetime(),
                "rate": float(row.funding_rate),
            }
            if has_mark and pd.notna(row.mark_price):
                mark = float(row.mark_price)
                if not math.isfinite(mark) or mark <= 0:
                    raise ValueError(f"funding snapshot has invalid mark_price for {symbol}")
                event["mark_price"] = mark
            engine_events.append(event)
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
    if not math.isfinite(parsed) or (positive and parsed <= 0):
        raise ValueError(f"{key} must be finite{' and > 0' if positive else ''}")
    return parsed


def build_candidate_cells(prereg: Mapping[str, Any]) -> tuple[CandidateCell, ...]:
    """Build exactly the six YAML-defined cells; code constants are not substituted."""

    raw_cells = prereg.get("candidate_cells")
    if not isinstance(raw_cells, list) or len(raw_cells) != 6:
        raise ValueError("candidate_cells must contain exactly six cells")
    cells: list[CandidateCell] = []
    ids: set[str] = set()
    family_counts: Counter[str] = Counter()
    for raw in raw_cells:
        if not isinstance(raw, dict):
            raise ValueError("every candidate cell must be a mapping")
        candidate_id = str(raw.get("id", "")).strip()
        family = str(raw.get("family", "")).strip()
        if not candidate_id or candidate_id in ids:
            raise ValueError("candidate IDs must be non-empty and unique")
        ids.add(candidate_id)
        family_counts[family] += 1
        common = {
            "candidate_id": candidate_id,
            "beta_lookback_bars": _required_int(raw, "beta_lookback_bars"),
            "hold_bars": _required_int(raw, "hold_bars"),
            "long_k": _required_int(raw, "long_k"),
            "short_k": _required_int(raw, "short_k"),
            "atr_period": _required_int(raw, "stop_atr_period"),
            "stop_atr_multiple": _required_float(raw, "stop_atr_multiple"),
        }
        if family == "residual_cross_sectional_trend":
            if raw.get("score_normalization") != "residual_sum_over_residual_std_sqrt_formation":
                raise ValueError("trend score_normalization differs from the frozen contract")
            if raw.get("rebalance") != "monday_00_00_utc":
                raise ValueError("trend rebalance differs from the frozen contract")
            if raw.get("funding_role") != "realized_cost_only":
                raise ValueError("trend funding_role differs from the frozen contract")
            cells.append(
                ResidualTrendCell(formation_bars=_required_int(raw, "formation_bars"), **common)
            )
        elif family == "funding_confirmed_residual_reversion":
            if raw.get("decision_times_utc") != ["00:00", "08:00", "16:00"]:
                raise ValueError("reversion decision times differ from the frozen contract")
            if raw.get("funding_confirmation") != "same_direction_crowding_sign":
                raise ValueError("reversion funding confirmation differs from the frozen contract")
            cells.append(
                FundingReversionCell(
                    formation_bars=_required_int(raw, "residual_formation_bars"),
                    z_lookback_bars=_required_int(raw, "residual_z_lookback_bars"),
                    residual_abs_z_min=_required_float(raw, "residual_abs_z_min"),
                    **common,
                )
            )
        else:
            raise ValueError(f"unsupported candidate family: {family!r}")
    if family_counts != Counter(
        {"residual_cross_sectional_trend": 3, "funding_confirmed_residual_reversion": 3}
    ):
        raise ValueError("the frozen batch requires three trend and three reversion cells")
    return tuple(cells)


def build_policy(prereg: Mapping[str, Any]) -> PortfolioPolicy:
    execution = prereg["execution_contract"]
    gap = prereg["time_protocol"]["gap_policy"]
    throttle = execution["dd_throttle"]
    return PortfolioPolicy(
        risk_per_trade=_required_float(execution, "risk_per_trade_pct") / 100.0,
        max_symbol_notional_pct=(
            _required_float(execution, "max_symbol_notional_pct_equity") / 100.0
        ),
        max_positions=_required_int(execution, "max_positions"),
        max_same_side=_required_int(execution, "max_same_side_positions"),
        leverage=_required_float(execution, "max_leverage"),
        dd_throttle_threshold=_required_float(throttle, "threshold_pct") / 100.0,
        dd_throttle_multiplier=_required_float(throttle, "risk_multiplier"),
        gap_max_minutes=_required_int(gap, "max_contiguous_gap_minutes"),
        warmup_bars_after_gap=_required_int(gap, "warmup_bars_after_gap"),
        bar_minutes=15,
    )


def generate_all_intents_once(
    frames: Mapping[str, pd.DataFrame],
    funding: Mapping[str, pd.DataFrame],
    cells: Sequence[CandidateCell],
    *,
    reference_symbol: str,
    warmup_bars_after_gap: int,
) -> dict[str, tuple[SignalIntent, ...]]:
    """Rank the full universe, including holdouts, once per candidate cell."""

    generated: dict[str, tuple[SignalIntent, ...]] = {}
    for cell in cells:
        if isinstance(cell, ResidualTrendCell):
            intents = generate_residual_cross_sectional_trend_intents(
                frames,
                cell,
                trade_holdouts=frozenset(),
                btc_symbol=reference_symbol,
                warmup_bars_after_gap=warmup_bars_after_gap,
            )
        else:
            intents = generate_funding_confirmed_residual_reversion_intents(
                frames,
                funding,
                cell,
                trade_holdouts=frozenset(),
                btc_symbol=reference_symbol,
                warmup_bars_after_gap=warmup_bars_after_gap,
            )
        if any(intent.symbol == reference_symbol for intent in intents):
            raise RuntimeError("reference BTC leaked into tradable intents")
        generated[cell.candidate_id] = tuple(intents)
    return generated


def filter_intents(
    intents: Iterable[SignalIntent],
    *,
    symbols: frozenset[str] | None = None,
    start: pd.Timestamp | None = None,
    end: pd.Timestamp | None = None,
) -> tuple[SignalIntent, ...]:
    """Filter only after ranking; time bounds follow ``[start, end)``."""

    start_dt = start.to_pydatetime() if start is not None else None
    end_dt = end.to_pydatetime() if end is not None else None
    return tuple(
        intent
        for intent in intents
        if (symbols is None or intent.symbol in symbols)
        and (start_dt is None or intent.decision_ts >= start_dt)
        and (end_dt is None or intent.decision_ts < end_dt)
    )


def _symbol_view(prereg: Mapping[str, Any], view: SYMBOL_VIEW) -> frozenset[str] | None:
    universe = prereg["universe"]
    symbols = frozenset(universe["symbols"])
    holdouts = frozenset(universe["holdout_selection"]["holdout_symbols"])
    reference = str(universe["holdout_selection"]["reference_symbol"])
    if not holdouts < symbols or reference not in symbols or reference in holdouts:
        raise ValueError("invalid holdout/reference partition")
    if view == "all":
        return symbols.difference({reference})
    if view == "development":
        return symbols.difference(holdouts).difference({reference})
    if view == "holdout":
        return holdouts
    raise ValueError(f"unknown symbol view: {view}")


def _window_result(
    result: PortfolioResult, *, start: pd.Timestamp, end: pd.Timestamp
) -> dict[str, Any]:
    summary = scenario_window_summary(result, start=start, end=end)
    ledger = ledger_frame(result)
    closed = ledger.loc[(ledger["exit_ts"] >= start) & (ledger["exit_ts"] < end)].copy()
    by_symbol = (
        closed.groupby("symbol", sort=True)["net_pnl"].sum().astype(float).to_dict()
        if not closed.empty
        else {}
    )
    by_side = (
        closed.groupby("side", sort=True)["net_pnl"].sum().astype(float).to_dict()
        if not closed.empty
        else {}
    )
    previous = summary.baseline_equity
    monthly_pnl: dict[str, float] = {}
    for month, return_pct in summary.monthly_returns_pct.items():
        ending = previous * (1.0 + float(return_pct) / 100.0)
        monthly_pnl[str(month)] = float(ending - previous)
        previous = ending
    return {
        "start_inclusive": start.isoformat(),
        "end_exclusive": end.isoformat(),
        "baseline_equity": summary.baseline_equity,
        "pre_window_peak_equity": summary.pre_window_peak_equity,
        "ending_equity": summary.ending_equity,
        "total_return_pct": float((summary.ending_equity / summary.baseline_equity - 1.0) * 100.0),
        "equity_observations": summary.equity_observations,
        "max_mtm_drawdown_pct": summary.max_mtm_drawdown_pct,
        "max_recovery_months": summary.max_recovery_months,
        "closed_trades": summary.closed_trades,
        "long_trades": summary.long_closed_trades,
        "short_trades": summary.short_closed_trades,
        "closed_trade_execution_cost": summary.closed_trade_execution_cost,
        "closed_trade_funding_cashflow": summary.closed_trade_funding_cashflow,
        "closed_trade_net_pnl": summary.closed_trade_net_pnl,
        "closed_trade_net_pnl_by_symbol": {
            str(symbol): float(value) for symbol, value in by_symbol.items()
        },
        "closed_trade_net_pnl_by_side": {
            str(side): float(value) for side, value in by_side.items()
        },
        "closed_trade_net_pnl_values": [
            float(value) for value in closed["net_pnl"].sort_values(ascending=False)
        ],
        "monthly_returns_unit": "percentage_points",
        "monthly_returns_pct": {
            str(month): float(value) for month, value in summary.monthly_returns_pct.items()
        },
        "monthly_pnl": monthly_pnl,
    }


def _scenario_result(
    result: PortfolioResult,
    *,
    windows: Mapping[str, tuple[pd.Timestamp, pd.Timestamp]],
) -> dict[str, Any]:
    rejections = Counter(reason for _, reason in result.rejections)
    return {
        "open_positions": result.open_position_count,
        "initial_equity": float(result.initial_equity),
        "final_equity": float(result.final_equity),
        "total_execution_cost": float(result.total_execution_cost),
        "accrued_exit_cost": float(result.accrued_exit_cost),
        "total_funding_cashflow": float(result.total_funding_cashflow),
        "windows": {
            name: _window_result(result, start=bounds[0], end=bounds[1])
            for name, bounds in windows.items()
        },
        "rejections": dict(sorted(rejections.items())),
    }


def _scenario_models(prereg: Mapping[str, Any]) -> dict[str, tuple[CostModel, float, float]]:
    execution = prereg["execution_contract"]
    base_cost = execution["costs_bps_per_leg"]
    scenarios = execution["cost_scenarios"]
    if not isinstance(scenarios, dict) or set(scenarios) != set(SCENARIO_ORDER):
        raise ValueError("cost_scenarios must be exactly B, C2 and H")
    built: dict[str, tuple[CostModel, float, float]] = {}
    for name in SCENARIO_ORDER:
        scenario = scenarios[name]
        built[name] = (
            CostModel(
                fee_bps_per_leg=_required_float(base_cost, "fee", positive=False),
                spread_slippage_bps_per_leg=_required_float(
                    base_cost, "spread_and_slippage", positive=False
                ),
                impact_bps_per_leg=_required_float(base_cost, "impact", positive=False),
                cost_multiplier=_required_float(scenario, "cost_multiplier", positive=False),
                funding_multiplier=_required_float(scenario, "funding_multiplier", positive=False),
            ),
            _required_float(scenario, "positive_pnl_multiplier"),
            _required_float(scenario, "negative_pnl_multiplier"),
        )
    return built


def _research_source_provenance() -> dict[str, Any]:
    source_root = Path(__file__).resolve().parents[3]
    relative_files = (
        "configs/crypto_15m_v16_research_prereg.yaml",
        "scripts/research/crypto_15m_v16_program.py",
        "src/price_action/lab/crypto_15m_event_engine.py",
        "src/price_action/lab/crypto_15m_evidence.py",
        "src/price_action/lab/crypto_15m_program.py",
        "src/price_action/lab/crypto_15m_residual_signals.py",
        "src/price_action/lab/crypto_15m_validation.py",
    )
    hashes = {
        relative: sha256_file(source_root / relative)
        for relative in relative_files
        if (source_root / relative).is_file()
    }
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=source_root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        status = subprocess.run(
            ["git", "status", "--porcelain", "--", *relative_files],
            cwd=source_root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        commit = "UNAVAILABLE"
        status = "UNAVAILABLE"
    return {
        "git_commit": commit,
        "research_source_clean": status == "",
        "research_source_status": status.splitlines(),
        "file_sha256": hashes,
    }


def _base_plan(prereg: Mapping[str, Any], prereg_path: Path) -> dict[str, Any]:
    cells = build_candidate_cells(prereg)
    policy = build_policy(prereg)
    snapshots = prereg["snapshots"]
    return {
        "schema_version": PROGRAM_SCHEMA,
        "evidence_eligible": False,
        "preregistration": {
            "path": str(prereg_path.resolve()),
            "sha256": sha256_file(prereg_path.resolve()),
            "schema_version": prereg["schema_version"],
            "status": prereg["status"],
        },
        "candidate_ids": [cell.candidate_id for cell in cells],
        "candidate_count": len(cells),
        "scenario_order": list(SCENARIO_ORDER),
        "source_provenance": _research_source_provenance(),
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


def _evaluation_windows(prereg: Mapping[str, Any]) -> dict[str, tuple[pd.Timestamp, pd.Timestamp]]:
    protocol = prereg["time_protocol"]
    complete = tuple(
        _utc_timestamp(value, label="complete-month boundary")
        for value in protocol["complete_months_utc"]
    )
    development = tuple(
        _utc_timestamp(value, label="development boundary") for value in protocol["development"]
    )
    folds = protocol["expanding_walk_forward"]
    if not isinstance(folds, list) or len(folds) != 6:
        raise ValueError("expanding_walk_forward must contain exactly six folds")
    pseudo_oos = (
        _utc_timestamp(folds[0][0], label="pseudo-OOS start"),
        _utc_timestamp(folds[-1][1], label="pseudo-OOS end"),
    )
    windows = {
        "complete": (complete[0], complete[1]),
        "development": (development[0], development[1]),
        "pseudo_oos": pseudo_oos,
    }
    if any(start >= end for start, end in windows.values()):
        raise ValueError("every evaluation window must be increasing")
    if development[0] != complete[0] or development[1] != pseudo_oos[0]:
        raise ValueError("development and pseudo-OOS windows must be contiguous")
    if pseudo_oos[1] != complete[1]:
        raise ValueError("pseudo-OOS end must equal the complete-month end")
    previous = pseudo_oos[0]
    for fold in folds:
        fold_start = _utc_timestamp(fold[0], label="fold start")
        fold_end = _utc_timestamp(fold[1], label="fold end")
        if fold_start != previous or fold_end <= fold_start:
            raise ValueError("walk-forward folds must be ordered and non-overlapping")
        previous = fold_end
    if previous != pseudo_oos[1]:
        raise ValueError("walk-forward folds must cover the full pseudo-OOS window")
    return windows


def _history_start(start: pd.Timestamp, cells: Sequence[CandidateCell]) -> pd.Timestamp:
    required_bars = 0
    for cell in cells:
        if isinstance(cell, ResidualTrendCell):
            required_bars = max(required_bars, cell.beta_lookback_bars + cell.formation_bars)
        else:
            required_bars = max(
                required_bars,
                cell.beta_lookback_bars + cell.formation_bars + cell.z_lookback_bars,
            )
    return start - required_bars * _BAR


def run_program(
    prereg_path: Path,
    *,
    repo_root: Path,
    symbol_view: SYMBOL_VIEW = "all",
) -> dict[str, Any]:
    """Verify frozen inputs and sequentially replay B/C2/H for all six cells."""

    prereg_path = prereg_path.resolve()
    repo_root = repo_root.resolve()
    prereg = load_preregistration(prereg_path)
    cells = build_candidate_cells(prereg)
    policy = build_policy(prereg)
    scenario_models = _scenario_models(prereg)
    snapshots = prereg["snapshots"]
    windows = _evaluation_windows(prereg)

    # Verify both immutable inputs before opening either database.
    verified = {
        name: verify_frozen_snapshot(name, snapshots[name], repo_root=repo_root)
        for name in ("market", "funding")
    }
    start, end = windows["complete"]
    if start >= end:
        raise ValueError("complete-month range must be increasing")
    history_start = _history_start(start, cells)
    symbols = tuple(str(symbol) for symbol in prereg["universe"]["symbols"])
    market_spec = snapshots["market"]
    market = load_market_snapshot(
        Path(verified["market"].resolved_path),
        market_spec,
        symbols=symbols,
        start=history_start,
        end=end,
    )
    funding = load_funding_snapshot(
        Path(verified["funding"].resolved_path),
        snapshots["funding"],
        symbols=symbols,
        venue=str(market_spec["venue"]),
        start=history_start,
        end=end,
    )
    reference = str(prereg["universe"]["holdout_selection"]["reference_symbol"])
    all_intents = generate_all_intents_once(
        market.frames,
        funding.signal_rates,
        cells,
        reference_symbol=reference,
        warmup_bars_after_gap=policy.warmup_bars_after_gap,
    )
    selected_symbols = _symbol_view(prereg, symbol_view)
    selected_intents = {
        candidate_id: filter_intents(intents, symbols=selected_symbols, start=start, end=end)
        for candidate_id, intents in all_intents.items()
    }

    results: dict[str, dict[str, Any]] = {}
    for cell in cells:
        cell_results: dict[str, Any] = {}
        for scenario_name in SCENARIO_ORDER:  # Deliberately sequential and deterministic.
            cost, positive_multiplier, negative_multiplier = scenario_models[scenario_name]
            replay = simulate_portfolio(
                market.frames,
                selected_intents[cell.candidate_id],
                funding.engine_events,
                cost,
                policy,
                positive_payoff_multiplier=positive_multiplier,
                negative_payoff_multiplier=negative_multiplier,
            )
            cell_results[scenario_name] = _scenario_result(replay, windows=windows)
        results[cell.candidate_id] = cell_results

    payload = _base_plan(prereg, prereg_path)
    source_clean = bool(payload["source_provenance"]["research_source_clean"])
    payload.update(
        {
            "mode": "FULL_FROZEN_REPLAY",
            "evidence_eligible": source_clean,
            "evidence_ineligible_reasons": ([] if source_clean else ["RESEARCH_SOURCE_DIRTY"]),
            "symbol_view": symbol_view,
            "snapshots": {name: asdict(value) for name, value in verified.items()},
            "time_range_utc": {
                "history_start_inclusive": history_start.isoformat(),
                "evaluation_start_inclusive": start.isoformat(),
                "end_exclusive": end.isoformat(),
                "windows": {
                    name: {
                        "start_inclusive": bounds[0].isoformat(),
                        "end_exclusive": bounds[1].isoformat(),
                    }
                    for name, bounds in windows.items()
                },
            },
            "market_alignment": {
                "frame_count": len(market.frames),
                "method": "exact_common_timestamp_intersection",
                "common_rows": market.common_rows,
                "first_ts": market.first_ts.isoformat(),
                "last_ts": market.last_ts.isoformat(),
                "raw_rows_by_symbol": market.raw_rows_by_symbol,
                "dropped_rows_by_symbol": market.dropped_rows_by_symbol,
            },
            "funding": {
                "signal_column": "funding_rate",
                "engine_column": "rate",
                "engine_event_count": len(funding.engine_events),
                "rows_by_symbol_including_signal_context": funding.rows_by_symbol,
            },
            "intent_generation": {
                "frame_universe_count": len(symbols),
                "ranking_universe_count": len(symbols) - 1,
                "reference_symbol": reference,
                "reference_symbol_intents": sum(
                    intent.symbol == reference
                    for intents in all_intents.values()
                    for intent in intents
                ),
                "full_ranked_counts": {
                    candidate_id: len(intents) for candidate_id, intents in all_intents.items()
                },
                "selected_counts": {
                    candidate_id: len(intents) for candidate_id, intents in selected_intents.items()
                },
            },
            "results": results,
        }
    )
    return payload


def dry_run(prereg_path: Path) -> dict[str, Any]:
    """Validate YAML/cell/policy structure without statting or hashing snapshots."""

    prereg_path = prereg_path.resolve()
    prereg = load_preregistration(prereg_path)
    _scenario_models(prereg)
    payload = _base_plan(prereg, prereg_path)
    payload["mode"] = "DRY_RUN_NO_SNAPSHOT_ACCESS"
    return payload


def smoke_run(prereg_path: Path) -> dict[str, Any]:
    """Run a tiny in-memory engine contract check; never access snapshot paths."""

    payload = dry_run(prereg_path)
    candidate_id = payload["candidate_ids"][0]
    timestamps = pd.date_range("2024-01-01", periods=4, freq="15min", tz="UTC")
    frames = {
        "BTC/USDT": pd.DataFrame(
            {"ts": timestamps, "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0}
        ),
        "ETH/USDT": pd.DataFrame(
            {
                "ts": timestamps,
                "open": [100.0, 100.0, 101.0, 102.0],
                "high": [101.0, 101.5, 102.5, 103.0],
                "low": [99.0, 99.5, 100.5, 101.5],
                "close": [100.0, 101.0, 102.0, 102.5],
            }
        ),
    }
    intent = SignalIntent(
        candidate_id=candidate_id,
        decision_ts=timestamps[0].to_pydatetime(),
        symbol="ETH/USDT",
        side="long",
        score=1.0,
        atr=1.0,
        stop_atr_multiple=5.0,
        hold_bars=2,
    )
    result = simulate_portfolio(
        frames,
        [intent],
        cost=CostModel(0.0, 0.0, 0.0),
        policy=PortfolioPolicy(warmup_bars_after_gap=0),
    )
    payload["mode"] = "SMOKE_IN_MEMORY_NO_SNAPSHOT_ACCESS"
    payload["smoke"] = {
        "closed_trades": len(result.trades),
        "final_equity": float(result.final_equity),
        "reference_symbol_traded": any(trade.symbol == "BTC/USDT" for trade in result.trades),
    }
    return payload


def deterministic_json(payload: Mapping[str, Any]) -> str:
    """Render stable, strict JSON; NaN/Infinity are forbidden research output."""

    return json.dumps(payload, sort_keys=True, indent=2, allow_nan=False) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--prereg",
        type=Path,
        default=Path("configs/crypto_15m_v16_research_prereg.yaml"),
    )
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--execute", action="store_true", help="run the frozen DuckDB replay")
    modes.add_argument("--smoke", action="store_true", help="in-memory contract smoke only")
    modes.add_argument("--dry-run", action="store_true", help="YAML validation only (default)")
    parser.add_argument("--symbol-view", choices=("all", "development", "holdout"), default="all")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)

    if args.execute:
        payload = run_program(args.prereg, repo_root=args.repo_root, symbol_view=args.symbol_view)
    elif args.smoke:
        payload = smoke_run(args.prereg)
    else:
        payload = dry_run(args.prereg)
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
    "deterministic_json",
    "dry_run",
    "filter_intents",
    "generate_all_intents_once",
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
