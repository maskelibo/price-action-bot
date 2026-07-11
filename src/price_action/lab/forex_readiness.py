"""Fail-closed readiness gate for the local Forex paper research path.

This module is intentionally an inspector, not a runner.  It opens the configured
DuckDB database read-only, performs deterministic quality/freshness checks, and
classifies the environment as either ``READY_FOR_LOCAL_PAPER`` or ``DEFER``.

It has no network, ingest, credential, broker, exchange, testnet, or order path.
Even a READY result is permanently constrained to local paper simulation and
never grants order authorization.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import tempfile
from collections.abc import Mapping
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Any

import duckdb
import yaml

CONFIG_SCHEMA = "forex-autonomy-v1"
STATUS_SCHEMA = "forex-readiness-status-v1"
CAPABILITY_SCHEMA = "forex-capability-v1"
READY = "READY_FOR_LOCAL_PAPER"
DEFER = "DEFER"

PERMANENT_POLICY = {
    "mode": "PAPER_ONLY",
    "live_authorized": False,
    "testnet_authorized": False,
    "order_authorized": False,
    "exchange_order_authorized": False,
}

REQUIRED_COLUMNS = {
    "venue",
    "symbol",
    "timeframe",
    "ts",
    "open",
    "high",
    "low",
    "close",
}
NUMERIC_TYPES = {
    "TINYINT",
    "SMALLINT",
    "INTEGER",
    "BIGINT",
    "HUGEINT",
    "UTINYINT",
    "USMALLINT",
    "UINTEGER",
    "UBIGINT",
    "FLOAT",
    "DOUBLE",
    "REAL",
    "DECIMAL",
}
PROVEN_BROKEN_VENUES = frozenset({"yfinance", "yahoo", "yahoo_finance"})
CAPABILITY_NAMES = ("feed", "paper_broker", "local_runner")
IMPLEMENTATION_CAPABILITIES = frozenset({"paper_broker", "local_runner"})
_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_SYMBOL_RE = re.compile(r"^[A-Z]{3}/[A-Z]{3}$")
_TIMEFRAME_RE = re.compile(r"^(?P<count>[1-9][0-9]*)(?P<unit>m|h|d)$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class ForexReadinessError(ValueError):
    """The readiness configuration or a capability contract is malformed."""


def _iso_utc(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _parse_utc(value: datetime | str, *, field: str) -> datetime:
    try:
        parsed = (
            value
            if isinstance(value, datetime)
            else datetime.fromisoformat(value.replace("Z", "+00:00"))
        )
    except (TypeError, ValueError) as exc:
        raise ForexReadinessError(f"{field} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise ForexReadinessError(f"{field} must include a timezone")
    return parsed.astimezone(UTC)


def _timeframe_hours(value: str) -> float:
    match = _TIMEFRAME_RE.fullmatch(value)
    if match is None:
        raise ForexReadinessError(f"unsupported timeframe: {value!r}")
    count = int(match.group("count"))
    unit = match.group("unit")
    factors = {"m": 1.0 / 60.0, "h": 1.0, "d": 24.0}
    return count * factors[unit]


def _project_root(config_path: Path) -> Path:
    parent = config_path.resolve().parent
    return parent.parent if parent.name == "configs" else parent


def _resolve_path(value: str | Path, *, root: Path) -> Path:
    path = Path(value).expanduser()
    root = root.resolve()
    resolved = path.resolve() if path.is_absolute() else (root / path).resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ForexReadinessError(f"configured path escapes project root: {value!s}") from exc
    return resolved


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_mapping(path: Path, *, label: str) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise ForexReadinessError(f"{label} must be a regular non-symlink file: {path}")
    if path.suffix.lower() == ".json":
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ForexReadinessError(f"{label} is not valid JSON: {path}") from exc
    else:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ForexReadinessError(f"{label} must contain an object: {path}")
    return payload


def _load_config(path: Path) -> tuple[dict[str, Any], Path]:
    config_path = path.resolve()
    config = _load_mapping(config_path, label="Forex autonomy config")
    if config.get("schema_version") != CONFIG_SCHEMA:
        raise ForexReadinessError(f"schema_version must be {CONFIG_SCHEMA!r}")
    return config, _project_root(config_path)


def _reason(reasons: list[dict[str, str]], code: str, detail: str) -> None:
    if not any(item["code"] == code and item["detail"] == detail for item in reasons):
        reasons.append({"code": code, "detail": detail})


def _market_interval_for_day(
    day: date,
    *,
    friday_close_hour_utc: int,
    sunday_open_hour_utc: int,
) -> tuple[datetime, datetime] | None:
    start = datetime.combine(day, time.min, tzinfo=UTC)
    weekday = day.weekday()
    if weekday <= 3:  # Monday through Thursday
        return start, start + timedelta(days=1)
    if weekday == 4:  # Friday, until the configured weekly close
        return start, start + timedelta(hours=friday_close_hour_utc)
    if weekday == 6:  # Sunday, from the configured weekly open
        return start + timedelta(hours=sunday_open_hour_utc), start + timedelta(days=1)
    return None  # Saturday


def forex_market_age_seconds(
    start: datetime,
    end: datetime,
    *,
    friday_close_hour_utc: int = 22,
    sunday_open_hour_utc: int = 22,
) -> float:
    """Return elapsed seconds while the spot-FX week is open.

    The default conservative calendar treats Friday 22:00 UTC through Sunday
    22:00 UTC as closed.  It intentionally models only the weekend closure;
    holiday calendars are not guessed and belong in a future trusted feed
    contract.
    """

    start = _parse_utc(start, field="freshness start")
    end = _parse_utc(end, field="freshness end")
    if end <= start:
        return 0.0
    if not 0 <= friday_close_hour_utc <= 23:
        raise ForexReadinessError("friday_close_hour_utc must be in [0, 23]")
    if not 0 <= sunday_open_hour_utc <= 23:
        raise ForexReadinessError("sunday_open_hour_utc must be in [0, 23]")

    total = 0.0
    day = start.date()
    while day <= end.date():
        interval = _market_interval_for_day(
            day,
            friday_close_hour_utc=friday_close_hour_utc,
            sunday_open_hour_utc=sunday_open_hour_utc,
        )
        if interval is not None:
            left = max(start, interval[0])
            right = min(end, interval[1])
            if right > left:
                total += (right - left).total_seconds()
        day += timedelta(days=1)
    return total


def _type_is_numeric(data_type: str) -> bool:
    upper = data_type.upper()
    return upper in NUMERIC_TYPES or upper.startswith("DECIMAL(")


def _quote_identifier(value: str) -> str:
    if _IDENTIFIER_RE.fullmatch(value) is None:
        raise ForexReadinessError(f"unsafe SQL identifier: {value!r}")
    return f'"{value}"'


def _series_key(venue: str, symbol: str, timeframe: str) -> str:
    return f"{venue}/{symbol}/{timeframe}"


def _evaluate_policy(config: Mapping[str, Any], reasons: list[dict[str, str]]) -> bool:
    policy = config.get("policy")
    if not isinstance(policy, Mapping):
        _reason(reasons, "POLICY_CONTRACT_MISSING", "paper-only policy object is required")
        return False
    expected = {
        "permanent_mode": "PAPER_ONLY",
        "live_authorized": False,
        "testnet_authorized": False,
        "order_authorized": False,
    }
    safe = True
    for field, expected_value in expected.items():
        actual = policy.get(field)
        if type(actual) is not type(expected_value) or actual != expected_value:
            safe = False
            _reason(
                reasons,
                "POLICY_CONTRACT_UNSAFE",
                f"policy.{field} must be exactly {expected_value!r}; got {actual!r}",
            )
    return safe


def _capability_from_contract(
    name: str,
    path_value: str,
    *,
    root: Path,
) -> tuple[bool, dict[str, Any], str | None]:
    try:
        path = _resolve_path(path_value, root=root)
    except ForexReadinessError as exc:
        return False, {"source": "contract_file", "path": path_value}, str(exc)
    try:
        contract = _load_mapping(path, label=f"{name} capability contract")
    except (OSError, ForexReadinessError) as exc:
        return False, {"source": "contract_file", "path": str(path)}, str(exc)

    required = {
        "schema_version": CAPABILITY_SCHEMA,
        "capability": name,
        "ready": True,
        "paper_only": True,
        "live_authorized": False,
        "testnet_authorized": False,
        "order_authorized": False,
    }
    mismatches = [
        f"{field}={contract.get(field)!r} (expected {expected!r})"
        for field, expected in required.items()
        if type(contract.get(field)) is not type(expected) or contract.get(field) != expected
    ]
    detail = {
        "source": "contract_file",
        "path": str(path),
        "schema_version": contract.get("schema_version"),
    }

    if name in IMPLEMENTATION_CAPABILITIES:
        artifacts = contract.get("implementation_artifacts")
        artifact_report: list[dict[str, Any]] = []
        if not isinstance(artifacts, list) or not artifacts:
            mismatches.append("implementation_artifacts must be a non-empty list")
        else:
            for index, item in enumerate(artifacts):
                item_report: dict[str, Any] = {"index": index}
                if not isinstance(item, Mapping):
                    mismatches.append(f"implementation_artifacts[{index}] must be an object")
                    item_report["matches"] = False
                    artifact_report.append(item_report)
                    continue
                path_value = item.get("path")
                expected_hash = item.get("sha256")
                item_report.update({"path": path_value, "expected_sha256": expected_hash})
                if not isinstance(path_value, str) or not path_value.strip():
                    mismatches.append(
                        f"implementation_artifacts[{index}].path must be a non-empty string"
                    )
                    item_report["matches"] = False
                    artifact_report.append(item_report)
                    continue
                if (
                    not isinstance(expected_hash, str)
                    or _SHA256_RE.fullmatch(expected_hash) is None
                ):
                    mismatches.append(
                        f"implementation_artifacts[{index}].sha256 must be lowercase SHA-256"
                    )
                    item_report["matches"] = False
                    artifact_report.append(item_report)
                    continue
                try:
                    artifact_path = _resolve_path(path_value, root=root)
                except ForexReadinessError as exc:
                    mismatches.append(str(exc))
                    item_report["matches"] = False
                    artifact_report.append(item_report)
                    continue
                item_report["resolved_path"] = str(artifact_path)
                if artifact_path.is_symlink() or not artifact_path.is_file():
                    mismatches.append(
                        f"implementation artifact must be a regular non-symlink file: {artifact_path}"
                    )
                    item_report["matches"] = False
                    artifact_report.append(item_report)
                    continue
                actual_hash = _sha256_file(artifact_path)
                matches = actual_hash == expected_hash
                item_report.update({"actual_sha256": actual_hash, "matches": matches})
                artifact_report.append(item_report)
                if not matches:
                    mismatches.append(f"implementation artifact hash mismatch: {path_value}")
        detail["implementation_artifacts"] = artifact_report
        detail["content_pinned"] = bool(artifact_report) and all(
            item.get("matches") is True for item in artifact_report
        )

    if mismatches:
        return False, detail, "; ".join(mismatches)
    return True, detail, None


def _evaluate_capabilities(
    config: Mapping[str, Any],
    *,
    root: Path,
    reasons: list[dict[str, str]],
) -> tuple[bool, dict[str, dict[str, Any]]]:
    section = config.get("capabilities")
    if not isinstance(section, Mapping):
        section = {}
    results: dict[str, dict[str, Any]] = {}

    for name in CAPABILITY_NAMES:
        spec = section.get(name)
        ok = False
        detail: dict[str, Any]
        error: str | None = None
        if isinstance(spec, bool):
            if spec and name in IMPLEMENTATION_CAPABILITIES:
                detail = {"source": "explicit_boolean", "declared_ready": spec}
                error = "a content-pinned contract_file is required for implementation readiness"
            else:
                ok = spec
                detail = {"source": "explicit_boolean", "declared_ready": spec}
        elif isinstance(spec, Mapping):
            contract_path = spec.get("contract_file")
            explicit = spec.get("ready")
            if contract_path is not None:
                if not isinstance(contract_path, str) or not contract_path.strip():
                    detail = {"source": "contract_file"}
                    error = "contract_file must be a non-empty path string"
                else:
                    ok, detail, error = _capability_from_contract(name, contract_path, root=root)
                if explicit is not None:
                    if not isinstance(explicit, bool):
                        ok = False
                        error = "ready must be a boolean when supplied"
                    elif not explicit:
                        ok = False
                        error = "explicit ready=false overrides the contract"
                    detail["declared_ready"] = explicit
            elif isinstance(explicit, bool):
                detail = {"source": "explicit_boolean", "declared_ready": explicit}
                if explicit and name in IMPLEMENTATION_CAPABILITIES:
                    error = (
                        "a content-pinned contract_file is required for implementation readiness"
                    )
                else:
                    ok = explicit
            else:
                detail = {"source": "missing_declaration"}
                error = "provide contract_file or an explicit ready boolean"
        else:
            detail = {"source": "missing_declaration"}
            error = "provide a capability contract file or explicit boolean"

        results[name] = {"ready": ok, **detail}
        if not ok:
            suffix = error or "declared false"
            _reason(
                reasons,
                f"CAPABILITY_{name.upper()}_UNAVAILABLE",
                f"{name}: {suffix}",
            )
    return all(item["ready"] for item in results.values()), results


def _inspect_database(
    db_path: Path,
    data_config: Mapping[str, Any],
    *,
    now: datetime,
    reasons: list[dict[str, str]],
) -> tuple[bool, dict[str, Any]]:
    report: dict[str, Any] = {
        "path": str(db_path),
        "access_mode": "read_only",
        "opened": False,
        "checks": {},
        "series": {},
    }
    checks: dict[str, dict[str, Any]] = report["checks"]
    if db_path.is_symlink() or not db_path.is_file():
        _reason(reasons, "DATABASE_UNAVAILABLE", f"regular database file not found: {db_path}")
        checks["database_file"] = {"ok": False}
        return False, report

    trusted_raw = data_config.get("trusted_venues")
    if (
        not isinstance(trusted_raw, list)
        or not trusted_raw
        or not all(isinstance(item, str) and item.strip() for item in trusted_raw)
    ):
        _reason(
            reasons,
            "TRUSTED_VENUES_INVALID",
            "data.trusted_venues must be a non-empty string list",
        )
        return False, report
    trusted = {item.strip().lower() for item in trusted_raw}
    broken_trusted = sorted(trusted & PROVEN_BROKEN_VENUES)
    if broken_trusted:
        _reason(
            reasons,
            "PROVEN_BROKEN_VENUE_CONFIGURED",
            f"proven-broken sources cannot be trusted: {broken_trusted}",
        )

    required_series = data_config.get("required_series")
    if not isinstance(required_series, list) or not required_series:
        _reason(
            reasons,
            "REQUIRED_SERIES_MISSING",
            "data.required_series must contain at least one venue/symbol/timeframe contract",
        )
        return False, report
    normalized_series: list[tuple[str, str, str]] = []
    for index, item in enumerate(required_series):
        if not isinstance(item, Mapping):
            _reason(reasons, "REQUIRED_SERIES_INVALID", f"series[{index}] must be an object")
            continue
        venue = str(item.get("venue", "")).strip().lower()
        symbol = str(item.get("symbol", "")).strip().upper()
        timeframe = str(item.get("timeframe", "")).strip().lower()
        if venue not in trusted:
            _reason(
                reasons,
                "REQUIRED_SERIES_UNTRUSTED",
                f"series[{index}] venue {venue!r} is not configured as trusted",
            )
            continue
        if _SYMBOL_RE.fullmatch(symbol) is None:
            _reason(
                reasons,
                "REQUIRED_SERIES_INVALID",
                f"series[{index}] has invalid FX symbol {symbol!r}",
            )
            continue
        try:
            _timeframe_hours(timeframe)
        except ForexReadinessError as exc:
            _reason(reasons, "REQUIRED_SERIES_INVALID", f"series[{index}]: {exc}")
            continue
        normalized_series.append((venue, symbol, timeframe))

    min_rows = data_config.get("min_rows_per_series", 1)
    if isinstance(min_rows, bool) or not isinstance(min_rows, int) or min_rows < 1:
        _reason(
            reasons,
            "MIN_ROWS_INVALID",
            "data.min_rows_per_series must be an integer >= 1",
        )
        min_rows = 1

    freshness = data_config.get("freshness")
    if not isinstance(freshness, Mapping):
        freshness = {}
    max_age_bars = freshness.get("max_market_age_bars", 2.0)
    grace_hours = freshness.get("grace_hours", 2.0)
    future_tolerance_hours = freshness.get("future_tolerance_hours", 1.0)
    market_hours = freshness.get("market_hours")
    if not isinstance(market_hours, Mapping):
        market_hours = {}
    friday_close = market_hours.get("friday_close_hour_utc", 22)
    sunday_open = market_hours.get("sunday_open_hour_utc", 22)
    numeric_freshness = (max_age_bars, grace_hours, future_tolerance_hours)
    if (
        any(
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            or value < 0
            for value in numeric_freshness
        )
        or max_age_bars <= 0
    ):
        _reason(
            reasons,
            "FRESHNESS_CONFIG_INVALID",
            "freshness values must be finite non-negative numbers and max_market_age_bars > 0",
        )
        max_age_bars, grace_hours, future_tolerance_hours = 2.0, 2.0, 1.0
    if (
        isinstance(friday_close, bool)
        or not isinstance(friday_close, int)
        or not 0 <= friday_close <= 23
        or isinstance(sunday_open, bool)
        or not isinstance(sunday_open, int)
        or not 0 <= sunday_open <= 23
    ):
        _reason(
            reasons,
            "FRESHNESS_CONFIG_INVALID",
            "weekend open/close hours must be integers in [0, 23]",
        )
        friday_close, sunday_open = 22, 22

    spread = data_config.get("spread")
    if not isinstance(spread, Mapping):
        spread = {}
    spread_column = spread.get("column")
    spread_min = spread.get("min_value", 0.0)
    spread_max = spread.get("max_value", math.inf)
    if not isinstance(spread_column, str) or _IDENTIFIER_RE.fullmatch(spread_column) is None:
        _reason(
            reasons,
            "SPREAD_CONTRACT_INVALID",
            "data.spread.column must be a safe column name",
        )
        spread_column = "spread_bps"
    if (
        any(
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            for value in (spread_min, spread_max)
        )
        or spread_min < 0
        or spread_max <= spread_min
    ):
        _reason(
            reasons,
            "SPREAD_CONTRACT_INVALID",
            "spread min/max must be finite with 0 <= min < max",
        )
        spread_min, spread_max = 0.0, 100.0

    try:
        con = duckdb.connect(str(db_path), read_only=True)
    except duckdb.Error as exc:
        _reason(reasons, "DATABASE_OPEN_FAILED", str(exc))
        return False, report

    try:
        report["opened"] = True
        tables = {
            row[0]
            for row in con.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_schema='main'"
            ).fetchall()
        }
        table_ok = "ohlcv" in tables
        checks["table"] = {"ok": table_ok, "required": "ohlcv"}
        if not table_ok:
            _reason(reasons, "SCHEMA_TABLE_MISSING", "required table 'ohlcv' is missing")
            return False, report

        columns = {
            str(name): str(data_type)
            for name, data_type in con.execute(
                """
                SELECT column_name, data_type
                FROM information_schema.columns
                WHERE table_schema='main' AND table_name='ohlcv'
                """
            ).fetchall()
        }
        missing = sorted(REQUIRED_COLUMNS - columns.keys())
        checks["required_columns"] = {"ok": not missing, "missing": missing}
        if missing:
            _reason(reasons, "SCHEMA_COLUMNS_MISSING", f"ohlcv missing columns: {missing}")
            return False, report

        ts_type = columns["ts"].upper()
        tz_ok = "WITH TIME ZONE" in ts_type or ts_type == "TIMESTAMPTZ"
        checks["timestamp_timezone"] = {"ok": tz_ok, "data_type": columns["ts"]}
        if not tz_ok:
            _reason(
                reasons,
                "TIMESTAMP_NOT_TIMEZONE_AWARE",
                f"ohlcv.ts must be TIMESTAMP WITH TIME ZONE, got {columns['ts']}",
            )

        numeric_ohlc = all(
            _type_is_numeric(columns[field]) for field in ("open", "high", "low", "close")
        )
        checks["ohlc_types"] = {"ok": numeric_ohlc}
        if not numeric_ohlc:
            _reason(reasons, "OHLC_TYPE_INVALID", "OHLC columns must be numeric")

        spread_schema_ok = spread_column in columns and _type_is_numeric(columns[spread_column])
        checks["spread_schema"] = {
            "ok": spread_schema_ok,
            "column": spread_column,
            "data_type": columns.get(spread_column),
        }
        if not spread_schema_ok:
            _reason(
                reasons,
                "SPREAD_DATA_MISSING",
                f"numeric observed spread column {spread_column!r} is required",
            )

        venues = sorted(
            str(row[0]).strip().lower()
            for row in con.execute("SELECT DISTINCT venue FROM ohlcv ORDER BY venue").fetchall()
        )
        report["observed_venues"] = venues
        observed_broken = sorted(set(venues) & PROVEN_BROKEN_VENUES)
        untrusted = sorted(set(venues) - trusted)
        venue_ok = not observed_broken and not untrusted and not broken_trusted
        checks["source_venues"] = {
            "ok": venue_ok,
            "trusted": sorted(trusted),
            "proven_broken_observed": observed_broken,
            "untrusted_observed": untrusted,
        }
        if observed_broken:
            _reason(
                reasons,
                "PROVEN_BROKEN_VENUE_OBSERVED",
                f"proven-broken source rows found: {observed_broken}",
            )
        if untrusted:
            _reason(
                reasons,
                "UNTRUSTED_VENUE_OBSERVED",
                f"only configured trusted venues are allowed; found {untrusted}",
            )

        symbols = sorted(
            str(row[0]).strip().upper()
            for row in con.execute("SELECT DISTINCT symbol FROM ohlcv ORDER BY symbol").fetchall()
        )
        invalid_symbols = [item for item in symbols if _SYMBOL_RE.fullmatch(item) is None]
        checks["symbol_format"] = {"ok": not invalid_symbols, "invalid": invalid_symbols}
        if invalid_symbols:
            _reason(reasons, "SYMBOL_FORMAT_INVALID", f"invalid FX symbols: {invalid_symbols}")

        timeframes = sorted(
            str(row[0]).strip().lower()
            for row in con.execute(
                "SELECT DISTINCT timeframe FROM ohlcv ORDER BY timeframe"
            ).fetchall()
        )
        invalid_timeframes: list[str] = []
        for item in timeframes:
            try:
                _timeframe_hours(item)
            except ForexReadinessError:
                invalid_timeframes.append(item)
        checks["timeframe_format"] = {
            "ok": not invalid_timeframes,
            "invalid": invalid_timeframes,
        }
        if invalid_timeframes:
            _reason(
                reasons,
                "TIMEFRAME_FORMAT_INVALID",
                f"invalid timeframes: {invalid_timeframes}",
            )

        duplicate_groups = int(
            con.execute(
                """
                SELECT COUNT(*) FROM (
                    SELECT venue, symbol, timeframe, ts
                    FROM ohlcv
                    GROUP BY venue, symbol, timeframe, ts
                    HAVING COUNT(*) > 1
                )
                """
            ).fetchone()[0]
        )
        checks["duplicates"] = {"ok": duplicate_groups == 0, "duplicate_keys": duplicate_groups}
        if duplicate_groups:
            _reason(
                reasons,
                "DUPLICATE_BARS",
                f"{duplicate_groups} duplicate venue/symbol/timeframe/timestamp keys",
            )

        bad_ohlc = 0
        if numeric_ohlc:
            bad_ohlc = int(
                con.execute(
                    """
                    SELECT COUNT(*) FROM ohlcv
                    WHERE open IS NULL OR high IS NULL OR low IS NULL OR close IS NULL
                       OR NOT isfinite(open) OR NOT isfinite(high)
                       OR NOT isfinite(low) OR NOT isfinite(close)
                       OR least(open, high, low, close) <= 0
                       OR high < greatest(open, close, low)
                       OR low > least(open, close, high)
                    """
                ).fetchone()[0]
            )
        checks["ohlc_values"] = {"ok": numeric_ohlc and bad_ohlc == 0, "invalid_rows": bad_ohlc}
        if bad_ohlc:
            _reason(reasons, "OHLC_VALUES_INVALID", f"{bad_ohlc} invalid OHLC rows")

        bad_spread: int | None = None
        if spread_schema_ok:
            quoted_spread = _quote_identifier(spread_column)
            bad_spread = int(
                con.execute(
                    f"""
                    SELECT COUNT(*) FROM ohlcv
                    WHERE {quoted_spread} IS NULL
                       OR NOT isfinite({quoted_spread})
                       OR {quoted_spread} < ? OR {quoted_spread} > ?
                    """,
                    [float(spread_min), float(spread_max)],
                ).fetchone()[0]
            )
            if bad_spread:
                _reason(
                    reasons,
                    "SPREAD_VALUES_INVALID",
                    f"{bad_spread} spread rows outside [{spread_min}, {spread_max}]",
                )
        checks["spread_values"] = {
            "ok": spread_schema_ok and bad_spread == 0,
            "invalid_rows": bad_spread,
            "min_value": spread_min,
            "max_value": spread_max,
        }

        global_max: datetime | None = None
        for venue, symbol, timeframe in normalized_series:
            key = _series_key(venue, symbol, timeframe)
            row = con.execute(
                """
                SELECT COUNT(*), MIN(ts), MAX(ts)
                FROM ohlcv
                WHERE lower(venue)=? AND upper(symbol)=? AND lower(timeframe)=?
                """,
                [venue, symbol, timeframe],
            ).fetchone()
            row_count = int(row[0])
            min_ts = row[1]
            max_ts = row[2]
            series_report: dict[str, Any] = {
                "row_count": row_count,
                "min_timestamp_utc": _iso_utc(_parse_utc(min_ts, field=f"{key} min ts"))
                if min_ts is not None
                else None,
                "max_timestamp_utc": _iso_utc(_parse_utc(max_ts, field=f"{key} max ts"))
                if max_ts is not None
                else None,
            }
            if row_count < min_rows or max_ts is None:
                series_report["fresh"] = False
                _reason(
                    reasons,
                    "REQUIRED_SERIES_INSUFFICIENT",
                    f"{key}: {row_count} rows, minimum {min_rows}",
                )
            else:
                max_utc = _parse_utc(max_ts, field=f"{key} max ts")
                if global_max is None or max_utc > global_max:
                    global_max = max_utc
                future_hours = (max_utc - now).total_seconds() / 3600.0
                market_age_hours = (
                    forex_market_age_seconds(
                        max_utc,
                        now,
                        friday_close_hour_utc=friday_close,
                        sunday_open_hour_utc=sunday_open,
                    )
                    / 3600.0
                )
                allowed_hours = _timeframe_hours(timeframe) * float(max_age_bars) + float(
                    grace_hours
                )
                fresh = (
                    future_hours <= float(future_tolerance_hours)
                    and market_age_hours <= allowed_hours
                )
                series_report.update(
                    {
                        "fresh": fresh,
                        "market_age_hours": round(market_age_hours, 6),
                        "allowed_market_age_hours": round(allowed_hours, 6),
                    }
                )
                if future_hours > float(future_tolerance_hours):
                    _reason(
                        reasons,
                        "DATA_TIMESTAMP_IN_FUTURE",
                        f"{key}: max timestamp is {future_hours:.3f}h ahead of evaluation time",
                    )
                elif market_age_hours > allowed_hours:
                    _reason(
                        reasons,
                        "DATA_STALE",
                        f"{key}: open-market age {market_age_hours:.3f}h exceeds {allowed_hours:.3f}h",
                    )
            report["series"][key] = series_report

        report["max_timestamp_utc"] = _iso_utc(global_max) if global_max is not None else None
    except (duckdb.Error, ForexReadinessError) as exc:
        _reason(reasons, "DATABASE_INSPECTION_FAILED", str(exc))
    finally:
        con.close()

    checks_ok = all(bool(item.get("ok")) for item in checks.values())
    series_ok = bool(report["series"]) and all(
        item.get("row_count", 0) >= min_rows and item.get("fresh") is True
        for item in report["series"].values()
    )
    return checks_ok and series_ok and not broken_trusted, report


def evaluate_forex_readiness(
    config_path: Path,
    *,
    now: datetime | str | None = None,
    db_path_override: Path | None = None,
) -> dict[str, Any]:
    """Evaluate local Forex paper readiness without mutating data or operations."""

    config, root = _load_config(Path(config_path))
    evaluated_at = datetime.now(UTC) if now is None else _parse_utc(now, field="now")
    database = config.get("database")
    if not isinstance(database, Mapping) or not isinstance(database.get("path"), str):
        raise ForexReadinessError("database.path must be configured")
    db_path = (
        Path(db_path_override).expanduser().resolve()
        if db_path_override is not None
        else _resolve_path(database["path"], root=root)
    )
    data_config = config.get("data")
    if not isinstance(data_config, Mapping):
        raise ForexReadinessError("data configuration object is required")

    reasons: list[dict[str, str]] = []
    policy_safe = _evaluate_policy(config, reasons)
    capabilities_ready, capabilities = _evaluate_capabilities(config, root=root, reasons=reasons)
    data_ready, database_report = _inspect_database(
        db_path,
        data_config,
        now=evaluated_at,
        reasons=reasons,
    )
    ready = policy_safe and capabilities_ready and data_ready and not reasons

    return {
        "schema_version": STATUS_SCHEMA,
        "evaluated_at": _iso_utc(evaluated_at),
        "status": READY if ready else DEFER,
        "policy": dict(PERMANENT_POLICY),
        "authorization": {
            "live": False,
            "testnet": False,
            "orders": False,
        },
        "ready_conditions": {
            "trusted_fresh_data": data_ready,
            "paper_capabilities": capabilities_ready,
            "permanent_paper_policy": policy_safe,
        },
        "capabilities": capabilities,
        "database": database_report,
        "reasons": reasons,
    }


def write_status_json(report: Mapping[str, Any], path: Path) -> None:
    """Atomically write a status artifact; this never touches the market database."""

    output = path.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    raw = (json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode()
    fd, temp_name = tempfile.mkstemp(prefix=f".{output.name}.", dir=output.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, output)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def cli_main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Read-only Forex local-paper readiness and freshness gate"
    )
    parser.add_argument("--config", type=Path, default=Path("configs/forex_autonomy.yaml"))
    parser.add_argument("--db", type=Path, help="read-only database override")
    parser.add_argument("--now", help="timezone-aware ISO-8601 evaluation time")
    parser.add_argument("--output", type=Path, help="status JSON output path")
    parser.add_argument(
        "--require-ready",
        action="store_true",
        help="return exit code 2 when status is DEFER",
    )
    args = parser.parse_args(argv)

    report = evaluate_forex_readiness(args.config, now=args.now, db_path_override=args.db)
    if args.output is not None:
        write_status_json(report, args.output)
    print(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False))
    return 2 if args.require_ready and report["status"] != READY else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(cli_main())
