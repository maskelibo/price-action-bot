"""Promotion-ineligible feature discovery records and strict researcher loader.

Feature sweeps are useful hypothesis generators, but they are not independent
out-of-sample promotion evidence.  This module makes that boundary executable:

* only ``feature-sweep-candidate-v2`` records can be active;
* every v2 record is explicitly ``DESCRIPTIVE_DISCOVERY`` and
  ``promotion_eligible=false``;
* a stable candidate key provides append-only de-duplication;
* an integrity digest covers the complete record (including timestamps);
* the researcher loader fails closed on stale data, stale code, malformed
  source fingerprints, duplicate keys, and all legacy rows.

The legacy ``sweep_candidates.jsonl`` file is deliberately read-only here.  It
can be counted for a quarantine summary, but no record from it can become
active researcher context.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import math
import re
from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CANDIDATE_PATH = REPO_ROOT / "memory" / "researcher" / "sweep_candidates_v2.jsonl"
LEGACY_CANDIDATE_PATH = REPO_ROOT / "memory" / "researcher" / "sweep_candidates.jsonl"

SCHEMA_VERSION = "feature-sweep-candidate-v2"
EVIDENCE_CLASS = "DESCRIPTIVE_DISCOVERY"
ACTIVE_STATUS = "ACTIVE"
ALGORITHM_NAME = "feature-sweep-by-deoverlap-volnorm-v3"
SUPPORTED_TIMEFRAMES = frozenset({"1h", "4h", "1d"})

DEFAULT_GENERATED_MAX_AGE = timedelta(days=7)
DEFAULT_SOURCE_MAX_AGE = timedelta(days=3)
MAX_FUTURE_SKEW = timedelta(minutes=5)

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_KEY_RE = re.compile(r"^fsv2-[0-9a-f]{64}$")
_TOP_LEVEL_FIELDS = frozenset(
    {
        "schema_version",
        "evidence_class",
        "promotion_eligible",
        "status",
        "candidate_key",
        "integrity_sha256",
        "generated_at",
        "symbol",
        "timeframe",
        "feature",
        "feature_family",
        "target",
        "statistics",
        "source",
        "algorithm",
    }
)
_STAT_FIELDS = frozenset(
    {
        "n_is",
        "n_oos",
        "ic_is",
        "p_is",
        "ic_oos",
        "fdr_pass",
        "oos_confirmed",
        "is_start_ts",
        "is_end_ts",
        "oos_start_ts",
        "oos_end_ts",
        "effective_independence_bars",
        "fdr_alpha",
        "fdr_family_size",
    }
)
_SOURCE_FIELDS = frozenset(
    {
        "kind",
        "venue",
        "dataset",
        "symbol",
        "timeframe",
        "row_count",
        "max_ts",
        "market_snapshot_sha256",
    }
)
_ALGORITHM_FIELDS = frozenset(
    {
        "name",
        "code_sha256",
        "multiple_testing",
        "multiple_testing_scope",
        "forward_target_deoverlap",
        "target_normalization",
        "oos_scheme",
    }
)


@dataclass(frozen=True)
class CandidateAppendSummary:
    """Result of an append-only candidate write."""

    appended: int
    duplicates: int


@dataclass(frozen=True)
class CandidateLoadResult:
    """Strict active records plus a machine-readable quarantine summary."""

    candidates: tuple[dict[str, Any], ...]
    summary: dict[str, Any]


def _canonical_json(payload: Any) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=True,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _sha256(payload: Any) -> str:
    return hashlib.sha256(_canonical_json(payload)).hexdigest()


def _parse_utc(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(UTC)


def _is_number(value: Any) -> bool:
    return not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value)


def _oos_consistent(statistics: Mapping[str, Any]) -> bool:
    ic_is = statistics.get("ic_is")
    ic_oos = statistics.get("ic_oos")
    return bool(
        statistics.get("fdr_pass") is True
        and _is_number(ic_is)
        and _is_number(ic_oos)
        and abs(ic_is) >= 0.02
        and ic_is * ic_oos > 0
        and abs(ic_oos) >= 0.5 * abs(ic_is)
    )


def algorithm_code_sha256(
    *,
    module_path: Path | None = None,
    script_path: Path | None = None,
) -> str:
    """Hash the exact feature-candidate contract and sweep implementation."""

    paths = (
        Path(module_path or __file__).resolve(),
        Path(script_path or (REPO_ROOT / "scripts" / "feature_sweep.py")).resolve(),
    )
    digest = hashlib.sha256()
    for path in paths:
        raw = path.read_bytes()
        digest.update(path.name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(len(raw).to_bytes(8, "big"))
        digest.update(raw)
    return digest.hexdigest()


def market_snapshot_metadata(
    frame: pd.DataFrame,
    *,
    symbol: str,
    timeframe: str,
    venue: str = "binance",
    dataset: str = "data/market.duckdb:ohlcv",
) -> dict[str, Any]:
    """Return a deterministic content fingerprint for one resampled OHLCV frame.

    The hash covers index timestamps and exact IEEE-754 values via ``float.hex``.
    It therefore identifies the actual bars used by the sweep instead of the
    mutable 1.5GB DuckDB container file.
    """

    if timeframe not in SUPPORTED_TIMEFRAMES:
        raise ValueError(f"unsupported timeframe: {timeframe}")
    required = ("open", "high", "low", "close", "volume")
    missing = [column for column in required if column not in frame.columns]
    if missing:
        raise ValueError(f"OHLCV frame missing columns: {missing}")
    if frame.empty:
        raise ValueError("cannot fingerprint an empty OHLCV frame")
    if not frame.index.is_monotonic_increasing or frame.index.has_duplicates:
        raise ValueError("OHLCV index must be monotonic and unique")

    digest = hashlib.sha256()
    digest.update(f"{venue}|{dataset}|{symbol}|{timeframe}\n".encode())
    for row in frame.loc[:, required].itertuples():
        ts = pd.Timestamp(row.Index)
        if ts.tzinfo is None:
            raise ValueError("OHLCV timestamps must be timezone-aware")
        digest.update(ts.tz_convert(UTC).isoformat().encode("ascii"))
        for value in row[1:]:
            number = float(value)
            if not math.isfinite(number):
                raise ValueError("OHLCV snapshot contains non-finite values")
            digest.update(b"|")
            digest.update(number.hex().encode("ascii"))
        digest.update(b"\n")

    max_ts = pd.Timestamp(frame.index.max()).tz_convert(UTC).isoformat()
    return {
        "kind": "MARKET_OHLCV_SNAPSHOT",
        "venue": venue,
        "dataset": dataset,
        "symbol": symbol,
        "timeframe": timeframe,
        "row_count": len(frame),
        "max_ts": max_ts,
        "market_snapshot_sha256": digest.hexdigest(),
    }


def _identity_payload(record: Mapping[str, Any]) -> dict[str, Any]:
    """Stable discovery identity; excludes wall-clock time and mutable status."""

    return {
        "schema_version": record.get("schema_version"),
        "evidence_class": record.get("evidence_class"),
        "promotion_eligible": record.get("promotion_eligible"),
        "symbol": record.get("symbol"),
        "timeframe": record.get("timeframe"),
        "feature": record.get("feature"),
        "feature_family": record.get("feature_family"),
        "target": record.get("target"),
        "statistics": record.get("statistics"),
        "source": record.get("source"),
        "algorithm": record.get("algorithm"),
    }


def candidate_key(record: Mapping[str, Any]) -> str:
    """Compute the stable append de-duplication key."""

    return f"fsv2-{_sha256(_identity_payload(record))}"


def record_integrity_sha256(record: Mapping[str, Any]) -> str:
    """Hash every field except the digest itself."""

    return _sha256({key: value for key, value in record.items() if key != "integrity_sha256"})


def make_candidate_record(
    result: Mapping[str, Any],
    *,
    timeframe: str,
    source: Mapping[str, Any],
    generated_at: datetime,
    code_sha256: str,
) -> dict[str, Any]:
    """Build a strict promotion-ineligible v2 discovery record."""

    if generated_at.tzinfo is None:
        raise ValueError("generated_at must be timezone-aware")
    statistics = {
        "n_is": int(result["n_is"]),
        "n_oos": int(result["n_oos"]),
        "ic_is": float(result["ic_is"]),
        "p_is": float(result["p_is"]),
        "ic_oos": float(result["ic_oos"]),
        "fdr_pass": result.get("fdr_pass") is True,
        "is_start_ts": str(result["is_start_ts"]),
        "is_end_ts": str(result["is_end_ts"]),
        "oos_start_ts": str(result["oos_start_ts"]),
        "oos_end_ts": str(result["oos_end_ts"]),
        "effective_independence_bars": int(result["effective_independence_bars"]),
        "fdr_alpha": float(result["fdr_alpha"]),
        "fdr_family_size": int(result["fdr_family_size"]),
    }
    statistics["oos_confirmed"] = _oos_consistent(statistics)
    record: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "evidence_class": EVIDENCE_CLASS,
        "promotion_eligible": False,
        "status": ACTIVE_STATUS,
        "candidate_key": "",
        "integrity_sha256": "",
        "generated_at": generated_at.astimezone(UTC).isoformat(),
        "symbol": result["symbol"],
        "timeframe": timeframe,
        "feature": result["feature"],
        "feature_family": result["feature_family"],
        "target": result["target"],
        "statistics": statistics,
        "source": dict(source),
        "algorithm": {
            "name": ALGORITHM_NAME,
            "code_sha256": code_sha256,
            "multiple_testing": "BENJAMINI_YEKUTIELI",
            "multiple_testing_scope": result["fdr_scope"],
            "forward_target_deoverlap": True,
            "target_normalization": result["target_normalization"],
            "oos_scheme": result["oos_scheme"],
        },
    }
    record["candidate_key"] = candidate_key(record)
    record["integrity_sha256"] = record_integrity_sha256(record)
    errors = validate_candidate_record(
        record,
        expected_algorithm_sha256=code_sha256,
        check_freshness=False,
    )
    if errors:
        raise ValueError("invalid feature candidate: " + "; ".join(errors))
    return record


def validate_candidate_record(
    record: Any,
    *,
    now: datetime | None = None,
    generated_max_age: timedelta = DEFAULT_GENERATED_MAX_AGE,
    source_max_age: timedelta = DEFAULT_SOURCE_MAX_AGE,
    expected_algorithm_sha256: str | None = None,
    trusted_source_hashes: Mapping[tuple[str, str], str] | None = None,
    check_freshness: bool = True,
) -> list[str]:
    """Return all fail-closed validation errors for one candidate record."""

    if not isinstance(record, dict):
        return ["record_not_object"]
    errors: list[str] = []
    if frozenset(record) != _TOP_LEVEL_FIELDS:
        errors.append("top_level_schema_mismatch")
    if record.get("schema_version") != SCHEMA_VERSION:
        errors.append("legacy_or_unknown_schema")
    if record.get("evidence_class") != EVIDENCE_CLASS:
        errors.append("invalid_evidence_class")
    if record.get("promotion_eligible") is not False:
        errors.append("promotion_boundary_violation")
    if record.get("status") != ACTIVE_STATUS:
        errors.append("not_active")

    for field in ("symbol", "feature", "feature_family", "target"):
        value = record.get(field)
        if not isinstance(value, str) or not value.strip():
            errors.append(f"invalid_{field}")
    if isinstance(record.get("target"), str) and not record["target"].startswith(
        "fwd_volnorm_"
    ):
        errors.append("target_not_vol_normalized")
    timeframe = record.get("timeframe")
    if timeframe not in SUPPORTED_TIMEFRAMES:
        errors.append("unsupported_timeframe")

    statistics = record.get("statistics")
    if not isinstance(statistics, dict) or frozenset(statistics) != _STAT_FIELDS:
        errors.append("statistics_schema_mismatch")
    else:
        for field in ("n_is", "n_oos"):
            value = statistics.get(field)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                errors.append(f"invalid_statistics_{field}")
        for field in ("ic_is", "p_is", "ic_oos"):
            if not _is_number(statistics.get(field)):
                errors.append(f"invalid_statistics_{field}")
        if _is_number(statistics.get("p_is")) and not 0 <= statistics["p_is"] <= 1:
            errors.append("invalid_statistics_p_is_range")
        if statistics.get("fdr_pass") is not True:
            errors.append("fdr_not_passed")
        if statistics.get("oos_confirmed") is not True or not _oos_consistent(statistics):
            errors.append("oos_not_confirmed")
        for field in ("effective_independence_bars", "fdr_family_size"):
            value = statistics.get(field)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                errors.append(f"invalid_statistics_{field}")
        fdr_alpha = statistics.get("fdr_alpha")
        if not _is_number(fdr_alpha) or not 0 < fdr_alpha <= 0.05:
            errors.append("invalid_statistics_fdr_alpha")
        split = {
            field: _parse_utc(statistics.get(field))
            for field in ("is_start_ts", "is_end_ts", "oos_start_ts", "oos_end_ts")
        }
        if any(value is None for value in split.values()):
            errors.append("invalid_oos_split_timestamps")
        elif not (
            split["is_start_ts"]
            <= split["is_end_ts"]
            < split["oos_start_ts"]
            <= split["oos_end_ts"]
        ):
            errors.append("non_chronological_oos_split")

    source = record.get("source")
    source_max_ts: datetime | None = None
    if not isinstance(source, dict) or frozenset(source) != _SOURCE_FIELDS:
        errors.append("source_schema_mismatch")
    else:
        if source.get("kind") != "MARKET_OHLCV_SNAPSHOT":
            errors.append("invalid_source_kind")
        if source.get("symbol") != record.get("symbol"):
            errors.append("source_symbol_mismatch")
        if source.get("timeframe") != timeframe:
            errors.append("source_timeframe_mismatch")
        if not isinstance(source.get("venue"), str) or not source["venue"]:
            errors.append("invalid_source_venue")
        if not isinstance(source.get("dataset"), str) or not source["dataset"]:
            errors.append("invalid_source_dataset")
        row_count = source.get("row_count")
        if isinstance(row_count, bool) or not isinstance(row_count, int) or row_count <= 0:
            errors.append("invalid_source_row_count")
        snapshot_sha = source.get("market_snapshot_sha256")
        if not isinstance(snapshot_sha, str) or not _SHA256_RE.fullmatch(snapshot_sha):
            errors.append("invalid_source_snapshot_sha256")
        source_max_ts = _parse_utc(source.get("max_ts"))
        if source_max_ts is None:
            errors.append("invalid_source_max_ts")
        if trusted_source_hashes is not None:
            expected_source = trusted_source_hashes.get((str(record.get("symbol")), str(timeframe)))
            if expected_source is None or snapshot_sha != expected_source:
                errors.append("untrusted_source_snapshot")

    algorithm = record.get("algorithm")
    if not isinstance(algorithm, dict) or frozenset(algorithm) != _ALGORITHM_FIELDS:
        errors.append("algorithm_schema_mismatch")
    else:
        if algorithm.get("name") != ALGORITHM_NAME:
            errors.append("invalid_algorithm_name")
        code_sha = algorithm.get("code_sha256")
        if not isinstance(code_sha, str) or not _SHA256_RE.fullmatch(code_sha):
            errors.append("invalid_algorithm_sha256")
        if expected_algorithm_sha256 is not None and code_sha != expected_algorithm_sha256:
            errors.append("stale_algorithm_code")
        if algorithm.get("multiple_testing") != "BENJAMINI_YEKUTIELI":
            errors.append("invalid_multiple_testing")
        if (
            algorithm.get("multiple_testing_scope")
            != "ALL_SELECTED_TF_SYMBOL_FEATURE_TARGET_PAIRS_IN_RUN"
        ):
            errors.append("invalid_multiple_testing_scope")
        if algorithm.get("forward_target_deoverlap") is not True:
            errors.append("deoverlap_not_enforced")
        if algorithm.get("target_normalization") != "TRAILING_REALIZED_VOL_AT_DECISION_BAR":
            errors.append("target_not_vol_normalized")
        if (
            algorithm.get("oos_scheme")
            != "CHRONOLOGICAL_70_30_CONFIRMATION_NOT_PROMOTION_HOLDOUT"
        ):
            errors.append("invalid_oos_scheme")

    key = record.get("candidate_key")
    if not isinstance(key, str) or not _KEY_RE.fullmatch(key) or key != candidate_key(record):
        errors.append("candidate_key_mismatch")
    integrity = record.get("integrity_sha256")
    if (
        not isinstance(integrity, str)
        or not _SHA256_RE.fullmatch(integrity)
        or integrity != record_integrity_sha256(record)
    ):
        errors.append("record_integrity_mismatch")

    generated_at = _parse_utc(record.get("generated_at"))
    if generated_at is None:
        errors.append("invalid_generated_at")
    if check_freshness:
        current = (now or datetime.now(UTC)).astimezone(UTC)
        if generated_at is not None:
            if generated_at > current + MAX_FUTURE_SKEW:
                errors.append("generated_at_in_future")
            elif current - generated_at > generated_max_age:
                errors.append("stale_generated_at")
        if source_max_ts is not None:
            if source_max_ts > current + MAX_FUTURE_SKEW:
                errors.append("source_max_ts_in_future")
            elif current - source_max_ts > source_max_age:
                errors.append("stale_source_snapshot")
            if generated_at is not None and source_max_ts > generated_at + MAX_FUTURE_SKEW:
                errors.append("source_after_generation")
    return errors


def append_candidate_records(
    path: Path,
    records: Iterable[Mapping[str, Any]],
    *,
    expected_algorithm_sha256: str | None = None,
) -> CandidateAppendSummary:
    """Atomically append structurally valid records, de-duplicated by key."""

    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    appended = 0
    duplicates = 0
    with destination.open("a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            handle.seek(0)
            seen: set[str] = set()
            for line in handle:
                try:
                    existing = json.loads(line)
                except json.JSONDecodeError:
                    continue
                key = existing.get("candidate_key") if isinstance(existing, dict) else None
                if isinstance(key, str):
                    seen.add(key)
            handle.seek(0, 2)
            for raw_record in records:
                record = dict(raw_record)
                errors = validate_candidate_record(
                    record,
                    expected_algorithm_sha256=expected_algorithm_sha256,
                    check_freshness=False,
                )
                if errors:
                    raise ValueError("refusing invalid candidate record: " + "; ".join(errors))
                key = record["candidate_key"]
                if key in seen:
                    duplicates += 1
                    continue
                handle.write(_canonical_json(record).decode("utf-8") + "\n")
                seen.add(key)
                appended += 1
            handle.flush()
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    return CandidateAppendSummary(appended=appended, duplicates=duplicates)


def _read_jsonl(path: Path) -> tuple[list[Any], int]:
    records: list[Any] = []
    malformed = 0
    if not path.exists():
        return records, malformed
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            malformed += 1
    return records, malformed


def load_researcher_candidates(
    *,
    path: Path = DEFAULT_CANDIDATE_PATH,
    legacy_path: Path | None = LEGACY_CANDIDATE_PATH,
    now: datetime | None = None,
    generated_max_age: timedelta = DEFAULT_GENERATED_MAX_AGE,
    source_max_age: timedelta = DEFAULT_SOURCE_MAX_AGE,
    expected_algorithm_sha256: str | None = None,
    trusted_source_hashes: Mapping[tuple[str, str], str] | None = None,
) -> CandidateLoadResult:
    """Load only strict, fresh, current-code v2 records for researcher context."""

    expected_code = expected_algorithm_sha256 or algorithm_code_sha256()
    records, malformed = _read_jsonl(Path(path))
    reasons: Counter[str] = Counter()
    reasons["malformed_json"] += malformed
    active: list[dict[str, Any]] = []
    seen: set[str] = set()
    for record in records:
        if not isinstance(record, dict) or record.get("schema_version") != SCHEMA_VERSION:
            reasons["legacy_or_unknown_schema"] += 1
            continue
        errors = validate_candidate_record(
            record,
            now=now,
            generated_max_age=generated_max_age,
            source_max_age=source_max_age,
            expected_algorithm_sha256=expected_code,
            trusted_source_hashes=trusted_source_hashes,
        )
        if errors:
            for reason in sorted(set(errors)):
                reasons[reason] += 1
            continue
        key = record["candidate_key"]
        if key in seen:
            reasons["duplicate_candidate_key"] += 1
            continue
        seen.add(key)
        active.append(record)

    legacy_total = 0
    legacy_malformed = 0
    if legacy_path is not None and Path(legacy_path).resolve() != Path(path).resolve():
        legacy_records, legacy_malformed = _read_jsonl(Path(legacy_path))
        legacy_total = len(legacy_records) + legacy_malformed
        if legacy_total:
            reasons["legacy_file_quarantined"] += legacy_total

    active.sort(key=lambda row: (-abs(row["statistics"]["ic_oos"]), row["candidate_key"]))
    total_v2_file_rows = len(records) + malformed
    summary: dict[str, Any] = {
        "schema_version": "feature-sweep-quarantine-summary-v1",
        "v2_path": str(Path(path)),
        "legacy_path": str(Path(legacy_path)) if legacy_path is not None else None,
        "v2_file_rows": total_v2_file_rows,
        "active_count": len(active),
        "quarantined_count": total_v2_file_rows - len(active) + legacy_total,
        "legacy_quarantined_count": legacy_total,
        "legacy_malformed_count": legacy_malformed,
        "reasons": dict(sorted(reasons.items())),
    }
    return CandidateLoadResult(candidates=tuple(active), summary=summary)


def load_active_candidates(**kwargs: Any) -> list[dict[str, Any]]:
    """Convenience wrapper for prompt/context consumers."""

    return list(load_researcher_candidates(**kwargs).candidates)


__all__ = [
    "ACTIVE_STATUS",
    "ALGORITHM_NAME",
    "DEFAULT_CANDIDATE_PATH",
    "EVIDENCE_CLASS",
    "LEGACY_CANDIDATE_PATH",
    "SCHEMA_VERSION",
    "SUPPORTED_TIMEFRAMES",
    "CandidateAppendSummary",
    "CandidateLoadResult",
    "algorithm_code_sha256",
    "append_candidate_records",
    "candidate_key",
    "load_active_candidates",
    "load_researcher_candidates",
    "make_candidate_record",
    "market_snapshot_metadata",
    "record_integrity_sha256",
    "validate_candidate_record",
]
