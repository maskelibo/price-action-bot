"""Minimal immutable-snapshot IO boundary for the v15p2 baseline runner.

This module owns only frozen-file verification and read-only DuckDB loading.
It deliberately contains no strategy, portfolio, preregistration, reporting,
or V17 pair-study dependency.
"""

from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd

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
    """Independent OHLCV frames; no cross-symbol alignment is performed."""

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

    if isinstance(chunk_bytes, bool) or not isinstance(chunk_bytes, int) or chunk_bytes < 1:
        raise ValueError("chunk_bytes must be an integer >= 1")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while block := handle.read(chunk_bytes):
            digest.update(block)
    return digest.hexdigest()


def _snapshot_path(spec: Mapping[str, Any], repo_root: Path) -> Path:
    configured_text = str(spec.get("path", "")).strip()
    if not configured_text:
        raise ValueError("snapshot path is missing")
    configured = Path(configured_text)
    return configured if configured.is_absolute() else repo_root / configured


def verify_frozen_snapshot(
    name: str, spec: Mapping[str, Any], *, repo_root: Path
) -> SnapshotVerification:
    """Require exact byte size and SHA-256 before a snapshot may be opened."""

    expected_hash = str(spec.get("sha256", "")).lower()
    expected_bytes = spec.get("bytes")
    if not _SHA256.fullmatch(expected_hash):
        raise ValueError(f"{name}: invalid preregistered SHA256")
    if (
        isinstance(expected_bytes, bool)
        or not isinstance(expected_bytes, int)
        or expected_bytes < 0
    ):
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


def _normalize_usdt_symbol(value: Any) -> str:
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
            normalized = _normalize_usdt_symbol(raw)
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
    """Load every symbol independently; never intersect or forward-fill."""

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
        required = {
            "venue",
            "symbol",
            "timeframe",
            "ts",
            "open",
            "high",
            "low",
            "close",
            "volume",
        }
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
            query,
            [venue, timeframe, start.to_pydatetime(), end.to_pydatetime(), *native],
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
    """Load observed funding while preserving raw fractional timestamps."""

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
            query,
            [venue, start.to_pydatetime(), end.to_pydatetime(), *native],
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


__all__ = [
    "FundingBundle",
    "MarketBundle",
    "SnapshotVerification",
    "load_funding_snapshot",
    "load_market_snapshot",
    "sha256_file",
    "verify_frozen_snapshot",
]
