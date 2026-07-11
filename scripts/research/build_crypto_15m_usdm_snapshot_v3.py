"""Build the gap-manifest-pinned v3 Binance USD-M 15m research snapshot.

V2 proved that four official monthly archives contain two shared, bounded
timestamp gaps.  This successor preserves those vendor-observed absences
exactly; it never fills, interpolates, resamples, or synthesizes a bar.  Every
other timestamp and every OHLCV row remains checksum- and invariant-bound.

This module reuses only audited filesystem, Git-provenance, and atomic
publication primitives from the sealed v2 builder.  It does not import strategy,
engine, report, live database, exchange-account, or performance code.
"""

from __future__ import annotations

import argparse
import calendar
import contextlib
import csv
import hashlib
import io
import json
import math
import os
import re
import secrets
import stat
import traceback
import zipfile
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from itertools import pairwise
from pathlib import Path
from typing import Any

import duckdb

from scripts.research import build_crypto_15m_usdm_snapshot_v2 as base

PROTOCOL_SCHEMA = "crypto-15m-v15p2-usdm-snapshot-v3-build-protocol-v1"
BUILD_EVIDENCE_SCHEMA = "crypto-15m-v15p2-usdm-snapshot-v3-build-evidence-v1"
BUILD_RESERVATION_SCHEMA = "crypto-15m-v15p2-usdm-snapshot-v3-build-reservation-v1"

CANONICAL_PROTOCOL_RELATIVE = "configs/crypto_15m_v15p2_usdm_snapshot_v3_build_protocol.json"
CANONICAL_TEST_RELATIVE = "tests/test_crypto_15m_usdm_snapshot_v3_builder.py"
CANONICAL_BUNDLE_RELATIVE = "data/backups/20260711_v15p2_v3_usdm"
CANONICAL_OUTPUT_RELATIVE = f"{CANONICAL_BUNDLE_RELATIVE}/market.duckdb"
CANONICAL_BUILD_EVIDENCE_RELATIVE = f"{CANONICAL_BUNDLE_RELATIVE}/build_evidence.json"
CANONICAL_RESERVATION_RELATIVE = (
    "configs/crypto_15m_v15p2_usdm_snapshot_v3_build_attempt_001_started.json"
)
CANONICAL_FAILURE_EVIDENCE_RELATIVE = (
    "configs/crypto_15m_v15p2_usdm_snapshot_v3_build_attempt_001_failure.json"
)
CANONICAL_COVERAGE_DIAGNOSIS_RELATIVE = (
    "configs/crypto_15m_v15p2_usdm_snapshot_v2_coverage_diagnosis.json"
)

HISTORY_START = base.HISTORY_START
EVALUATION_END = base.EVALUATION_END
BAR_MS = base.BAR_MS
TIMEFRAME = base.TIMEFRAME
SYMBOLS = base.SYMBOLS
SYMBOL_TO_CANONICAL = base.SYMBOL_TO_CANONICAL
SOURCE_KIND = base.SOURCE_KIND

V2_PROTOCOL_SHA256 = "7f9b48374551aed7afc7afb48d460204241b378ca60ed375c9f52f03c2496850"
VENDOR_LOCK_SHA256 = "d7168500a61a60de44212e2401dcbcfab9ee4c1d14d28226b73105f0a8df106b"
V2_RESERVATION_SHA256 = "073d35afee68d4ad86efb9c6d3b91c2c9648db79e60ea31bb262851fb1bb618e"
V2_FAILURE_SHA256 = "0a65ceb3d3cd5569acdf44c6035835cfa927e42ce9bd56d081e9a21983c421a2"
COVERAGE_DIAGNOSIS_SHA256 = "b2a50fdb00c055aef8ec09b1c81e662160917878ac797b2dae966e661b745e91"
V2_FAILURE_COMMIT = "cb08fd9c82a3461402874f6b30f8f8b7bfdfc974"
COVERAGE_DIAGNOSIS_COMMIT = "7d1de13060cbf5d96910b1d36b0f0785b6db1a47"
FAIR_BASELINE_PREREG_RELATIVE = "configs/crypto_15m_v15p2_fair_baseline_prereg.yaml"
FAIR_BASELINE_PREREG_SHA256 = "695fb5b7a07fc0bb54c0a69b10f0893d246926a4339a17b5e8705802800f9c22"
FAIR_BASELINE_PREREG_COMMIT = "05fc820c0a684954ec035a164b82bda0bf57ab66"
V2_BUILDER_SHA256 = "4a3519a7faaeb3d4e6a2fb38c30f0cf18edfe21a70c997475e8c7af8d67ab4cf"
V2_TEST_SHA256 = "c812c9d11fc0310749ea54a36710b0356ae2a6ba1c557f4921a54313f3d01e3b"
EVALUATION_START = datetime(2021, 6, 1, tzinfo=UTC)

GAP_SYMBOLS = ("SOLUSDT", "ZECUSDT", "NEARUSDT", "FILUSDT")
GAP_INTERVALS = (
    (
        datetime(2022, 2, 26, tzinfo=UTC),
        datetime(2022, 3, 1, tzinfo=UTC),
        288,
    ),
    (
        datetime(2022, 4, 1, tzinfo=UTC),
        datetime(2022, 4, 3, tzinfo=UTC),
        192,
    ),
)
ROWS_CONTINUOUS_SYMBOL = 184_896
ROWS_GAP_SYMBOL = 184_416
TOTAL_ROWS = 2_586_624
EXPECTED_VALIDATED_VENDOR_ROWS = 2_613_504
EXPECTED_KEY_SHA256 = "8fa35b544898ab7f131a0826a2a4bd989aa0d283cc5a2926fb85f962a3e93318"
EXPECTED_MISSING_KEY_SHA256 = "bfd80250c7ae2b5b242f80b2170c47c872b771100f88b7e1ed64d0eaad29287d"
EXPECTED_CACHE_MANIFEST_SHA256 = "3a14ca9553128ee65d7fc9e31cc93ee71a7244d570b8faadacb7b5542d7f9c59"

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_TEMPORARY_DATABASE_NAME = re.compile(r"^\.market\.[0-9a-f]{64}\.duckdb$")
MAX_STAGED_FILE_BYTES = 8 * 1024 * 1024 * 1024
CONFIRMED_PUBLICATION_OUTCOME: tuple[bool | None, str, bool] = (
    True,
    "VISIBLE_RETAINED_INODE_DURABILITY_CONFIRMED",
    True,
)


class SnapshotV3BuildError(RuntimeError):
    """Raised when the gap-aware immutable build contract fails closed."""


def _canonical_path(repo_root: Path, relative: str) -> Path:
    return base._canonical_path(repo_root, relative)


def _canonical_bundle_target(repo_root: Path) -> tuple[Path, str, str]:
    relative = Path(CANONICAL_BUNDLE_RELATIVE)
    if relative.is_absolute() or not relative.parts or ".." in relative.parts:
        raise SnapshotV3BuildError("unsafe canonical bundle identity")
    parent_relative = str(relative.parent)
    parent = _canonical_path(repo_root, parent_relative)
    final_name = relative.name
    if final_name in {"", ".", ".."}:
        raise SnapshotV3BuildError("unsafe canonical bundle leaf identity")
    return parent / final_name, parent_relative, final_name


def _canonical_config_target(repo_root: Path, relative: str) -> tuple[Path, str]:
    relative_path = Path(relative)
    if (
        relative_path.is_absolute()
        or relative_path.parent != Path("configs")
        or not relative_path.name
        or ".." in relative_path.parts
    ):
        raise SnapshotV3BuildError("unsafe canonical config identity")
    parent = _canonical_path(repo_root, "configs")
    return parent / relative_path.name, relative_path.name


def _is_frozen_missing_timestamp(symbol: str, timestamp_ms: int) -> bool:
    if symbol not in GAP_SYMBOLS:
        return False
    return any(
        int(start.timestamp() * 1000) <= timestamp_ms < int(end.timestamp() * 1000)
        for start, end, _bars in GAP_INTERVALS
    )


def _expected_timestamps(symbol: str, start: datetime, end: datetime) -> tuple[int, ...]:
    return tuple(
        timestamp_ms
        for timestamp_ms in range(
            int(start.timestamp() * 1000),
            int(end.timestamp() * 1000),
            BAR_MS,
        )
        if not _is_frozen_missing_timestamp(symbol, timestamp_ms)
    )


def expected_rows_for_symbol(symbol: str) -> int:
    if symbol not in SYMBOLS:
        raise ValueError(f"unexpected symbol: {symbol}")
    return ROWS_GAP_SYMBOL if symbol in GAP_SYMBOLS else ROWS_CONTINUOUS_SYMBOL


def expected_key_sha256() -> str:
    digest = hashlib.sha256()
    for raw_symbol in SYMBOLS:
        canonical = SYMBOL_TO_CANONICAL[raw_symbol]
        for timestamp_ms in _expected_timestamps(raw_symbol, HISTORY_START, EVALUATION_END):
            digest.update(f"binance|{canonical}|15m|{timestamp_ms}\n".encode())
    actual = digest.hexdigest()
    if actual != EXPECTED_KEY_SHA256:
        raise SnapshotV3BuildError("frozen expected-key implementation drifted")
    return actual


def expected_missing_key_sha256() -> str:
    digest = hashlib.sha256()
    missing_count = 0
    for raw_symbol in SYMBOLS:
        canonical = SYMBOL_TO_CANONICAL[raw_symbol]
        for timestamp_ms in range(
            int(HISTORY_START.timestamp() * 1000),
            int(EVALUATION_END.timestamp() * 1000),
            BAR_MS,
        ):
            if _is_frozen_missing_timestamp(raw_symbol, timestamp_ms):
                digest.update(f"binance|{canonical}|15m|{timestamp_ms}\n".encode())
                missing_count += 1
    if missing_count != 1_920 or digest.hexdigest() != EXPECTED_MISSING_KEY_SHA256:
        raise SnapshotV3BuildError("frozen expected-missing-key implementation drifted")
    return digest.hexdigest()


def _month_bounds(month: str) -> tuple[datetime, datetime, int]:
    year, number = map(int, month.split("-"))
    days = calendar.monthrange(year, number)[1]
    start = datetime(year, number, 1, tzinfo=UTC)
    end = (
        datetime(year + 1, 1, 1, tzinfo=UTC)
        if number == 12
        else datetime(year, number + 1, 1, tzinfo=UTC)
    )
    return start, end, days * 96


def parse_monthly_archive(
    archive: bytes | Path,
    *,
    symbol: str,
    month: str,
    expected_filename: str,
) -> tuple[tuple[tuple[Any, ...], ...], dict[str, Any]]:
    if symbol not in SYMBOLS:
        raise SnapshotV3BuildError(f"unexpected archive symbol: {symbol}")
    if expected_filename != f"{symbol}-{TIMEFRAME}-{month}.zip":
        raise SnapshotV3BuildError("archive filename identity differs from symbol/month")
    source: Any = archive if isinstance(archive, Path) else io.BytesIO(archive)
    expected_member = expected_filename[:-4] + ".csv"
    month_start, month_end, full_calendar_rows = _month_bounds(month)
    expected_timestamps = _expected_timestamps(symbol, month_start, month_end)
    rows: list[tuple[Any, ...]] = []
    try:
        zipped_context = zipfile.ZipFile(source)
    except (OSError, zipfile.BadZipFile) as exc:
        raise SnapshotV3BuildError(f"invalid ZIP container: {expected_filename}") from exc
    with zipped_context as zipped:
        members = [info for info in zipped.infolist() if not info.is_dir()]
        if len(members) != 1 or members[0].filename != expected_member:
            raise SnapshotV3BuildError(
                f"ZIP member drift for {expected_filename}: {[item.filename for item in members]}"
            )
        member = members[0]
        compression_ratio = member.file_size / max(member.compress_size, 1)
        if (
            member.flag_bits & 0x1
            or member.file_size <= 0
            or member.file_size > base.MAX_ZIP_MEMBER_BYTES
            or compression_ratio > base.MAX_ZIP_COMPRESSION_RATIO
        ):
            raise SnapshotV3BuildError(f"unsafe ZIP resource profile: {expected_filename}")
        if zipped.testzip() is not None:
            raise SnapshotV3BuildError(f"ZIP CRC failed: {expected_filename}")
        header_seen = False
        with zipped.open(member, "r") as binary:
            reader = csv.reader(io.TextIOWrapper(binary, encoding="utf-8", newline=""))
            for line_number, record in enumerate(reader, start=1):
                if not record:
                    raise SnapshotV3BuildError(
                        f"blank CSV record at line {line_number}: {expected_filename}"
                    )
                if not record[0].isdigit():
                    if (
                        line_number == 1
                        and not header_seen
                        and tuple(record) == base.CANONICAL_CSV_HEADER
                    ):
                        header_seen = True
                        continue
                    raise SnapshotV3BuildError(
                        f"non-canonical CSV header/preamble at line {line_number}: "
                        f"{expected_filename}"
                    )
                if len(record) != 12:
                    raise SnapshotV3BuildError(
                        f"expected 12 CSV fields in {expected_filename}, got {len(record)}"
                    )
                timestamp_ms = int(record[0])
                try:
                    open_, high, low, close, volume = (
                        float(record[index]) for index in range(1, 6)
                    )
                    close_time = int(record[6])
                    quote_volume = float(record[7])
                    trade_count = int(record[8])
                    taker_buy_volume = float(record[9])
                    taker_buy_quote_volume = float(record[10])
                    ignore = float(record[11])
                except (TypeError, ValueError, OverflowError) as exc:
                    raise SnapshotV3BuildError(
                        f"invalid numeric CSV row: {expected_filename}"
                    ) from exc
                finite_values = (
                    open_,
                    high,
                    low,
                    close,
                    volume,
                    quote_volume,
                    taker_buy_volume,
                    taker_buy_quote_volume,
                    ignore,
                )
                if (
                    not all(math.isfinite(value) for value in finite_values)
                    or not 10**12 <= timestamp_ms < 10**13
                    or timestamp_ms % BAR_MS != 0
                    or not 10**12 <= close_time < 10**13
                    or min(open_, high, low, close) <= 0.0
                    or min(volume, quote_volume, taker_buy_volume, taker_buy_quote_volume) < 0.0
                    or trade_count < 0
                    or ignore != 0.0
                    or high < max(open_, close, low)
                    or low > min(open_, close, high)
                    or close_time != timestamp_ms + BAR_MS - 1
                ):
                    raise SnapshotV3BuildError(f"invalid OHLCV geometry: {expected_filename}")
                rows.append(
                    (
                        "binance",
                        SYMBOL_TO_CANONICAL[symbol],
                        TIMEFRAME,
                        datetime.fromtimestamp(timestamp_ms / 1000, tz=UTC),
                        open_,
                        high,
                        low,
                        close,
                        volume,
                    )
                )
                if len(rows) > full_calendar_rows:
                    raise SnapshotV3BuildError(
                        f"monthly row count exceeds calendar bound: {expected_filename}"
                    )
    actual_timestamps = tuple(int(row[3].timestamp() * 1000) for row in rows)
    if actual_timestamps != expected_timestamps:
        raise SnapshotV3BuildError(
            f"monthly timestamps differ from frozen vendor-gap manifest for {symbol} {month}: "
            f"rows={len(rows)}, expected={len(expected_timestamps)}"
        )
    return tuple(rows), {
        "rows": len(rows),
        "full_calendar_rows": full_calendar_rows,
        "frozen_missing_rows": full_calendar_rows - len(expected_timestamps),
        "first_ts": rows[0][3].isoformat() if rows else None,
        "last_ts": rows[-1][3].isoformat() if rows else None,
        "member": expected_member,
    }


def _gap_manifest() -> list[dict[str, Any]]:
    return [
        {
            "start_inclusive_utc": start.isoformat(),
            "end_exclusive_utc": end.isoformat(),
            "bars_per_affected_symbol": bars,
            "affected_symbols": list(GAP_SYMBOLS),
        }
        for start, end, bars in GAP_INTERVALS
    ]


def _source_paths(repo_root: Path) -> tuple[str, ...]:
    builder_relative = str(Path(__file__).resolve().relative_to(repo_root.resolve()))
    return (
        CANONICAL_PROTOCOL_RELATIVE,
        builder_relative,
        CANONICAL_TEST_RELATIVE,
        str(Path(base.__file__).resolve().relative_to(repo_root.resolve())),
        base.CANONICAL_TEST_RELATIVE,
        base.CANONICAL_PROTOCOL_RELATIVE,
        base.CANONICAL_VENDOR_LOCK_RELATIVE,
        base.CANONICAL_RESERVATION_RELATIVE,
        base.CANONICAL_FAILURE_EVIDENCE_RELATIVE,
        CANONICAL_COVERAGE_DIAGNOSIS_RELATIVE,
        FAIR_BASELINE_PREREG_RELATIVE,
    )


def _source_identity(repo_root: Path) -> dict[str, Any]:
    return {
        "git": base._git_state(repo_root),
        "file_sha256": {
            relative: base.sha256_file(_canonical_path(repo_root, relative))
            for relative in _source_paths(repo_root)
        },
        "runtime_versions": base._runtime_versions(),
    }


def _validate_protocol(protocol: Mapping[str, Any], *, repo_root: Path) -> None:
    exact_top_level = {
        "schema_version",
        "status",
        "created_at_utc",
        "source_kind",
        "market_type",
        "timeframe",
        "history_start_inclusive_utc",
        "evaluation_end_exclusive_utc",
        "evaluation_start_inclusive_utc",
        "evaluation_complete_months",
        "development_complete_months",
        "pseudo_oos_complete_months",
        "symbols",
        "canonical_symbols",
        "vendor_gap_symbols",
        "exact_vendor_gap_manifest",
        "continuous_symbol_rows_each",
        "vendor_gap_symbol_rows_each",
        "expected_total_rows",
        "expected_validated_vendor_rows",
        "expected_ordered_primary_key_sha256",
        "expected_missing_key_count",
        "expected_ordered_missing_key_sha256",
        "expected_cache_manifest_sha256",
        "builder_path",
        "builder_sha256",
        "builder_test_path",
        "builder_test_sha256",
        "v2_builder_path",
        "v2_builder_sha256",
        "v2_builder_test_path",
        "v2_builder_test_sha256",
        "v2_protocol_path",
        "v2_protocol_sha256",
        "vendor_lock_path",
        "vendor_lock_sha256",
        "coverage_diagnosis_path",
        "coverage_diagnosis_sha256",
        "coverage_diagnosis_commit",
        "fair_baseline_prereg_path",
        "fair_baseline_prereg_sha256",
        "fair_baseline_prereg_commit",
        "v2_reservation_path",
        "v2_reservation_sha256",
        "v2_failure_path",
        "v2_failure_sha256",
        "v2_failure_commit",
        "vendor_cache_path",
        "output_path",
        "build_evidence_path",
        "build_reservation_path",
        "build_failure_evidence_path",
        "data_build_trial_count_before_execution",
        "source_selection",
        "pre_protocol_access_disclosure",
        "snapshot_qa",
        "governance",
    }
    if set(protocol) != exact_top_level:
        raise SnapshotV3BuildError("v3 protocol top-level fields drifted")
    builder_path = Path(__file__).resolve()
    builder_relative = str(builder_path.relative_to(repo_root.resolve()))
    test_path = _canonical_path(repo_root, CANONICAL_TEST_RELATIVE)
    v2_builder_path = Path(base.__file__).resolve()
    v2_builder_relative = str(v2_builder_path.relative_to(repo_root.resolve()))
    expected_scalars = {
        "schema_version": PROTOCOL_SCHEMA,
        "status": "PREREGISTERED_AFTER_COVERAGE_ONLY_V2_FAILURE_BEFORE_V3_BUILD",
        "created_at_utc": "2026-07-11T16:12:37Z",
        "source_kind": SOURCE_KIND,
        "market_type": "USD_M_PERPETUAL_CONTRACT_PRICE",
        "timeframe": TIMEFRAME,
        "history_start_inclusive_utc": HISTORY_START.isoformat(),
        "evaluation_end_exclusive_utc": EVALUATION_END.isoformat(),
        "evaluation_start_inclusive_utc": EVALUATION_START.isoformat(),
        "evaluation_complete_months": 60,
        "development_complete_months": 24,
        "pseudo_oos_complete_months": 36,
        "symbols": list(SYMBOLS),
        "canonical_symbols": [SYMBOL_TO_CANONICAL[symbol] for symbol in SYMBOLS],
        "vendor_gap_symbols": list(GAP_SYMBOLS),
        "exact_vendor_gap_manifest": _gap_manifest(),
        "continuous_symbol_rows_each": ROWS_CONTINUOUS_SYMBOL,
        "vendor_gap_symbol_rows_each": ROWS_GAP_SYMBOL,
        "expected_total_rows": TOTAL_ROWS,
        "expected_validated_vendor_rows": EXPECTED_VALIDATED_VENDOR_ROWS,
        "expected_ordered_primary_key_sha256": EXPECTED_KEY_SHA256,
        "expected_missing_key_count": 1_920,
        "expected_ordered_missing_key_sha256": EXPECTED_MISSING_KEY_SHA256,
        "expected_cache_manifest_sha256": EXPECTED_CACHE_MANIFEST_SHA256,
        "builder_path": builder_relative,
        "builder_sha256": base.sha256_file(builder_path),
        "builder_test_path": CANONICAL_TEST_RELATIVE,
        "builder_test_sha256": base.sha256_file(test_path),
        "v2_builder_path": v2_builder_relative,
        "v2_builder_sha256": V2_BUILDER_SHA256,
        "v2_builder_test_path": base.CANONICAL_TEST_RELATIVE,
        "v2_builder_test_sha256": V2_TEST_SHA256,
        "v2_protocol_path": base.CANONICAL_PROTOCOL_RELATIVE,
        "v2_protocol_sha256": V2_PROTOCOL_SHA256,
        "vendor_lock_path": base.CANONICAL_VENDOR_LOCK_RELATIVE,
        "vendor_lock_sha256": VENDOR_LOCK_SHA256,
        "coverage_diagnosis_path": CANONICAL_COVERAGE_DIAGNOSIS_RELATIVE,
        "coverage_diagnosis_sha256": COVERAGE_DIAGNOSIS_SHA256,
        "coverage_diagnosis_commit": COVERAGE_DIAGNOSIS_COMMIT,
        "fair_baseline_prereg_path": FAIR_BASELINE_PREREG_RELATIVE,
        "fair_baseline_prereg_sha256": FAIR_BASELINE_PREREG_SHA256,
        "fair_baseline_prereg_commit": FAIR_BASELINE_PREREG_COMMIT,
        "v2_reservation_path": base.CANONICAL_RESERVATION_RELATIVE,
        "v2_reservation_sha256": V2_RESERVATION_SHA256,
        "v2_failure_path": base.CANONICAL_FAILURE_EVIDENCE_RELATIVE,
        "v2_failure_sha256": V2_FAILURE_SHA256,
        "v2_failure_commit": V2_FAILURE_COMMIT,
        "vendor_cache_path": base.CANONICAL_CACHE_RELATIVE,
        "output_path": CANONICAL_OUTPUT_RELATIVE,
        "build_evidence_path": CANONICAL_BUILD_EVIDENCE_RELATIVE,
        "build_reservation_path": CANONICAL_RESERVATION_RELATIVE,
        "build_failure_evidence_path": CANONICAL_FAILURE_EVIDENCE_RELATIVE,
        "data_build_trial_count_before_execution": 1,
    }
    for key, value in expected_scalars.items():
        if protocol.get(key) != value:
            raise SnapshotV3BuildError(f"v3 protocol field drifted: {key}")
    identity_files = {
        base.CANONICAL_PROTOCOL_RELATIVE: V2_PROTOCOL_SHA256,
        str(v2_builder_path.relative_to(repo_root.resolve())): V2_BUILDER_SHA256,
        base.CANONICAL_TEST_RELATIVE: V2_TEST_SHA256,
        base.CANONICAL_VENDOR_LOCK_RELATIVE: VENDOR_LOCK_SHA256,
        base.CANONICAL_RESERVATION_RELATIVE: V2_RESERVATION_SHA256,
        base.CANONICAL_FAILURE_EVIDENCE_RELATIVE: V2_FAILURE_SHA256,
        CANONICAL_COVERAGE_DIAGNOSIS_RELATIVE: COVERAGE_DIAGNOSIS_SHA256,
        FAIR_BASELINE_PREREG_RELATIVE: FAIR_BASELINE_PREREG_SHA256,
    }
    for relative, expected_sha in identity_files.items():
        if base.sha256_file(_canonical_path(repo_root, relative)) != expected_sha:
            raise SnapshotV3BuildError(f"v3 predecessor identity drifted: {relative}")
    base._assert_commit_file_identity(
        repo_root,
        V2_FAILURE_COMMIT,
        {
            base.CANONICAL_RESERVATION_RELATIVE: V2_RESERVATION_SHA256,
            base.CANONICAL_FAILURE_EVIDENCE_RELATIVE: V2_FAILURE_SHA256,
        },
    )
    base._assert_commit_file_identity(
        repo_root,
        COVERAGE_DIAGNOSIS_COMMIT,
        {CANONICAL_COVERAGE_DIAGNOSIS_RELATIVE: COVERAGE_DIAGNOSIS_SHA256},
    )
    base._assert_commit_file_identity(
        repo_root,
        FAIR_BASELINE_PREREG_COMMIT,
        {FAIR_BASELINE_PREREG_RELATIVE: FAIR_BASELINE_PREREG_SHA256},
    )
    source_selection = {
        "preserve_original_sixty_month_evaluation": True,
        "global_common_suffix_truncation_allowed": False,
        "vendor_observed_gaps_preserved": True,
        "forward_fill_interpolation_resampling_or_synthetic_rows_allowed": False,
        "unlisted_gap_duplicate_extra_offgrid_or_out_of_order_timestamp_allowed": False,
        "cache_reuse_requires_vendor_sha256_reverification": True,
        "v3_network_access_allowed": False,
        "v2_cache_mutation_allowed": False,
        "reason": (
            "Per-symbol gap preservation retains the preregistered 24+36 month evaluation; "
            "the signal engine resets exact-contiguous feature state after every gap."
        ),
    }
    if protocol.get("source_selection") != source_selection:
        raise SnapshotV3BuildError("v3 source-selection contract drifted")
    disclosure = {
        "all_896_archive_timestamp_counts_and_gap_locations_seen": True,
        "sol_february_2022_first_three_and_last_three_raw_rows_seen": True,
        "v2_attempt_archives_parsed_and_geometry_validated_before_failure": 77,
        "v2_attempt_ohlcv_rows_parsed_and_geometry_validated_before_failure": 224_256,
        "v2_attempt_selected_rows_written_to_ephemeral_staging_db_before_failure": 218_016,
        "v2_ephemeral_database_published_or_retained": False,
        "signals_trades_returns_roi_drawdown_monthly_metrics_or_scenarios_seen": False,
        "strategy_universe_threshold_execution_cost_or_risk_policy_selected_from_values": False,
        "alpha_result_trials": 0,
        "performance_result_produced": False,
    }
    if protocol.get("pre_protocol_access_disclosure") != disclosure:
        raise SnapshotV3BuildError("v3 pre-access disclosure drifted")
    snapshot_qa = {
        "exact_primary_key": ["venue", "symbol", "timeframe", "ts"],
        "exact_table_object_column_constraint_and_index_schema_required": True,
        "exact_per_symbol_timestamp_sets_required": True,
        "exact_vendor_gap_manifest_required": True,
        "exact_start_and_end_required_for_every_symbol": True,
        "duplicate_null_nonfinite_invalid_ohlc_rows_allowed": 0,
        "actual_ordered_primary_key_sha256_required": EXPECTED_KEY_SHA256,
        "per_symbol_content_sha256_required": True,
        "read_only_post_close_reverification_required": True,
        "snapshot_metadata_exact_match_required": True,
        "random_temporary_database_then_exclusive_fixed_name_publish_required": True,
        "exact_staging_children": ["build_evidence.json", "market.duckdb"],
        "pre_and_post_atomic_publication_identity_reverification_required": True,
        "generic_failure_publication_inode_probe_required": True,
        "database_and_success_evidence_atomic_bundle_required": True,
    }
    if protocol.get("snapshot_qa") != snapshot_qa:
        raise SnapshotV3BuildError("v3 snapshot QA contract drifted")
    governance = {
        "data_build_trial_count_before_execution": 1,
        "data_build_trial_count_including_this_attempt": 2,
        "coverage_diagnosis_pass_count": 1,
        "alpha_result_trials": 0,
        "strategy_engine_report_or_performance_imports_forbidden": True,
        "failed_v1_or_v2_database_rows_reused": False,
        "vendor_checksum_required_before_parse": True,
        "network_access_forbidden": True,
        "v2_cache_mutation_forbidden": True,
        "live_database_daemon_and_shared_parquet_mutation_forbidden": True,
        "exchange_account_credentials_or_private_api_forbidden": True,
        "clean_committed_protocol_required_before_build": True,
        "immutable_reservation_before_archive_access_required": True,
        "success_and_failure_evidence_exact_archive_progress_required": True,
        "deployment_authorized": False,
    }
    if protocol.get("governance") != governance:
        raise SnapshotV3BuildError("v3 governance contract drifted")


def _validate_snapshot_schema(connection: duckdb.DuckDBPyConnection) -> dict[str, Any]:
    actual_user_schemas = connection.execute(
        """
        SELECT schema_name, internal
        FROM duckdb_schemas()
        WHERE database_name=current_database()
        ORDER BY schema_name
        """
    ).fetchall()
    if actual_user_schemas != [("main", True)]:
        raise SnapshotV3BuildError("v3 snapshot user schema set differs from contract")
    actual_table_objects = connection.execute(
        """
        SELECT table_schema, table_name, table_type
        FROM information_schema.tables
        WHERE table_catalog=current_database()
        ORDER BY table_schema, table_name
        """
    ).fetchall()
    expected_table_objects = [
        ("main", "ohlcv", "BASE TABLE"),
        ("main", "snapshot_metadata", "BASE TABLE"),
    ]
    if actual_table_objects != expected_table_objects:
        raise SnapshotV3BuildError("v3 snapshot table object set differs from contract")
    actual_columns = connection.execute(
        """
        SELECT table_schema, table_name, column_name, data_type, is_nullable,
               ordinal_position, column_default, is_generated, generation_expression
        FROM information_schema.columns
        WHERE table_catalog=current_database()
        ORDER BY table_schema, table_name, ordinal_position
        """
    ).fetchall()
    expected_columns = [
        ("main", "ohlcv", "venue", "VARCHAR", "NO", 1, None, None, None),
        ("main", "ohlcv", "symbol", "VARCHAR", "NO", 2, None, None, None),
        ("main", "ohlcv", "timeframe", "VARCHAR", "NO", 3, None, None, None),
        (
            "main",
            "ohlcv",
            "ts",
            "TIMESTAMP WITH TIME ZONE",
            "NO",
            4,
            None,
            None,
            None,
        ),
        ("main", "ohlcv", "open", "DOUBLE", "NO", 5, None, None, None),
        ("main", "ohlcv", "high", "DOUBLE", "NO", 6, None, None, None),
        ("main", "ohlcv", "low", "DOUBLE", "NO", 7, None, None, None),
        ("main", "ohlcv", "close", "DOUBLE", "NO", 8, None, None, None),
        ("main", "ohlcv", "volume", "DOUBLE", "NO", 9, None, None, None),
        (
            "main",
            "snapshot_metadata",
            "key",
            "VARCHAR",
            "NO",
            1,
            None,
            None,
            None,
        ),
        (
            "main",
            "snapshot_metadata",
            "value",
            "VARCHAR",
            "YES",
            2,
            None,
            None,
            None,
        ),
    ]
    if actual_columns != expected_columns:
        raise SnapshotV3BuildError("v3 snapshot table schema differs from frozen contract")
    actual_constraints = connection.execute(
        """
        SELECT schema_name, table_name, constraint_type, constraint_column_names
        FROM duckdb_constraints()
        WHERE database_name=current_database()
        ORDER BY schema_name, table_name, constraint_index
        """
    ).fetchall()
    expected_constraints = [
        ("main", "ohlcv", "NOT NULL", ["venue"]),
        ("main", "ohlcv", "NOT NULL", ["symbol"]),
        ("main", "ohlcv", "NOT NULL", ["timeframe"]),
        ("main", "ohlcv", "NOT NULL", ["ts"]),
        ("main", "ohlcv", "NOT NULL", ["open"]),
        ("main", "ohlcv", "NOT NULL", ["high"]),
        ("main", "ohlcv", "NOT NULL", ["low"]),
        ("main", "ohlcv", "NOT NULL", ["close"]),
        ("main", "ohlcv", "NOT NULL", ["volume"]),
        ("main", "ohlcv", "PRIMARY KEY", ["venue", "symbol", "timeframe", "ts"]),
        ("main", "snapshot_metadata", "PRIMARY KEY", ["key"]),
        ("main", "snapshot_metadata", "NOT NULL", ["key"]),
    ]
    if actual_constraints != expected_constraints:
        raise SnapshotV3BuildError("v3 snapshot constraints differ from frozen contract")
    actual_primary_keys = [
        (table_name, column_names)
        for _schema_name, table_name, constraint_type, column_names in actual_constraints
        if constraint_type == "PRIMARY KEY"
    ]
    expected_primary_keys = [
        ("ohlcv", ["venue", "symbol", "timeframe", "ts"]),
        ("snapshot_metadata", ["key"]),
    ]
    if actual_primary_keys != expected_primary_keys:
        raise SnapshotV3BuildError("v3 snapshot primary-key constraints differ from contract")
    actual_indexes = connection.execute(
        """
        SELECT table_name, index_name, is_unique, is_primary, expressions
        FROM duckdb_indexes()
        WHERE database_name=current_database()
        ORDER BY schema_name, table_name, index_name
        """
    ).fetchall()
    if actual_indexes:
        raise SnapshotV3BuildError("v3 snapshot contains unregistered explicit indexes")
    unexpected_user_views = connection.execute(
        """
        SELECT schema_name, view_name
        FROM duckdb_views()
        WHERE database_name=current_database() AND internal=false
        ORDER BY schema_name, view_name
        """
    ).fetchall()
    unexpected_sequences = connection.execute(
        """
        SELECT schema_name, sequence_name
        FROM duckdb_sequences()
        WHERE database_name=current_database()
        ORDER BY schema_name, sequence_name
        """
    ).fetchall()
    unexpected_functions = connection.execute(
        """
        SELECT schema_name, function_name, function_type
        FROM duckdb_functions()
        WHERE database_name=current_database() AND internal=false
        ORDER BY schema_name, function_name, function_type
        """
    ).fetchall()
    unexpected_types = connection.execute(
        """
        SELECT schema_name, type_name
        FROM duckdb_types()
        WHERE database_name=current_database() AND internal=false
        ORDER BY schema_name, type_name
        """
    ).fetchall()
    if unexpected_user_views or unexpected_sequences or unexpected_functions or unexpected_types:
        raise SnapshotV3BuildError("v3 snapshot contains unregistered persistent user objects")
    return {
        "exact_user_schemas": [list(row) for row in actual_user_schemas],
        "exact_table_objects": [list(row) for row in actual_table_objects],
        "exact_columns": [list(row) for row in actual_columns],
        "exact_constraints": [
            [schema_name, table_name, constraint_type, list(column_names)]
            for schema_name, table_name, constraint_type, column_names in actual_constraints
        ],
        "exact_primary_keys": [
            [table_name, list(column_names)] for table_name, column_names in actual_primary_keys
        ],
        "explicit_indexes": [],
        "unregistered_persistent_user_objects": [],
    }


def _validate_snapshot_db(
    connection: duckdb.DuckDBPyConnection,
    *,
    expected_metadata: Mapping[str, str],
) -> dict[str, Any]:
    schema_contract = _validate_snapshot_schema(connection)
    total, distinct_keys = connection.execute(
        "SELECT COUNT(*), COUNT(DISTINCT (venue, symbol, timeframe, ts)) FROM ohlcv"
    ).fetchone()
    if total != TOTAL_ROWS or distinct_keys != TOTAL_ROWS:
        raise SnapshotV3BuildError(
            f"v3 snapshot row/key count drift: total={total}, distinct={distinct_keys}"
        )
    invalid = connection.execute(
        """
        SELECT COUNT(*) FROM ohlcv
        WHERE venue <> 'binance' OR timeframe <> '15m'
           OR ts IS NULL OR open IS NULL OR high IS NULL OR low IS NULL
           OR close IS NULL OR volume IS NULL
           OR NOT isfinite(open) OR NOT isfinite(high) OR NOT isfinite(low)
           OR NOT isfinite(close) OR NOT isfinite(volume)
           OR least(open, high, low, close) <= 0 OR volume < 0
           OR high < greatest(open, close, low) OR low > least(open, close, high)
        """
    ).fetchone()[0]
    if invalid:
        raise SnapshotV3BuildError(f"v3 snapshot contains {invalid} invalid OHLCV rows")
    metadata_rows = connection.execute(
        "SELECT key, value FROM snapshot_metadata ORDER BY key"
    ).fetchall()
    actual_metadata = {str(key): str(value) for key, value in metadata_rows}
    if actual_metadata != dict(expected_metadata):
        raise SnapshotV3BuildError("v3 snapshot metadata differs from frozen build identity")

    expected_first = HISTORY_START
    expected_last = datetime.fromtimestamp(
        (int(EVALUATION_END.timestamp() * 1000) - BAR_MS) / 1000,
        tz=UTC,
    )
    per_symbol: dict[str, Any] = {}
    for raw_symbol in SYMBOLS:
        canonical = SYMBOL_TO_CANONICAL[raw_symbol]
        rows = connection.execute(
            """
            SELECT epoch_ms(ts) FROM ohlcv
            WHERE venue='binance' AND symbol=? AND timeframe='15m'
            ORDER BY ts
            """,
            [canonical],
        ).fetchall()
        actual_timestamps = tuple(int(row[0]) for row in rows)
        expected_timestamps = _expected_timestamps(raw_symbol, HISTORY_START, EVALUATION_END)
        if actual_timestamps != expected_timestamps:
            raise SnapshotV3BuildError(
                f"{canonical}: database timestamps differ from frozen vendor-gap manifest"
            )
        count, first_ts, last_ts = connection.execute(
            """
            SELECT COUNT(*), MIN(ts), MAX(ts) FROM ohlcv
            WHERE venue='binance' AND symbol=? AND timeframe='15m'
            """,
            [canonical],
        ).fetchone()
        expected_count = expected_rows_for_symbol(raw_symbol)
        if count != expected_count or first_ts != expected_first or last_ts != expected_last:
            raise SnapshotV3BuildError(
                f"{canonical}: v3 range/count drift count={count}, first={first_ts}, last={last_ts}"
            )
        gap_transitions = sum(
            current - previous != BAR_MS for previous, current in pairwise(actual_timestamps)
        )
        expected_gap_transitions = 2 if raw_symbol in GAP_SYMBOLS else 0
        if gap_transitions != expected_gap_transitions:
            raise SnapshotV3BuildError(f"{canonical}: gap-transition count drifted")
        per_symbol[canonical] = {
            "rows": count,
            "first_ts": first_ts.astimezone(UTC).isoformat(),
            "last_ts": last_ts.astimezone(UTC).isoformat(),
            "gap_transition_count": gap_transitions,
            "frozen_missing_bar_count": 480 if raw_symbol in GAP_SYMBOLS else 0,
            "frozen_missing_full_utc_day_count": 5 if raw_symbol in GAP_SYMBOLS else 0,
            "content_sha256": base._row_content_hash(connection, canonical),
        }
    actual_key_hash = base._actual_key_sha256(connection)
    if actual_key_hash != expected_key_sha256():
        raise SnapshotV3BuildError("v3 actual key hash differs from frozen expected identity")
    return {
        **schema_contract,
        "total_rows": total,
        "distinct_primary_keys": distinct_keys,
        "invalid_ohlcv_rows": 0,
        "actual_ordered_primary_key_sha256": actual_key_hash,
        "expected_ordered_primary_key_sha256": EXPECTED_KEY_SHA256,
        "snapshot_metadata": actual_metadata,
        "per_symbol": per_symbol,
    }


def _read_only_post_close_qa(
    path: Path,
    *,
    expected_metadata: Mapping[str, str],
) -> dict[str, Any]:
    connection = duckdb.connect(str(path), read_only=True)
    try:
        connection.execute("SET TimeZone='UTC'")
        return _validate_snapshot_db(connection, expected_metadata=expected_metadata)
    finally:
        connection.close()


def _assert_build_source_postflight(
    preflight: Mapping[str, Any],
    postflight: Mapping[str, Any],
) -> None:
    if postflight.get("file_sha256") != preflight.get("file_sha256") or postflight.get(
        "runtime_versions"
    ) != preflight.get("runtime_versions"):
        raise SnapshotV3BuildError("v3 source/runtime identity changed during execution")
    pre_git = preflight.get("git")
    post_git = postflight.get("git")
    if not isinstance(pre_git, dict) or not isinstance(post_git, dict):
        raise SnapshotV3BuildError("v3 git provenance is malformed")
    if (
        pre_git.get("clean") is not True
        or pre_git.get("status") != []
        or post_git.get("commit") != pre_git.get("commit")
        or post_git.get("clean") is not False
        or post_git.get("status") != [f"?? {CANONICAL_RESERVATION_RELATIVE}"]
    ):
        raise SnapshotV3BuildError("v3 source postflight differs beyond reservation")


def _best_effort_source_identity(repo_root: Path) -> dict[str, Any]:
    try:
        return _source_identity(repo_root)
    except BaseException as exc:
        return {
            "status": "UNAVAILABLE_DURING_FAILURE_EVIDENCE_COLLECTION",
            "exception_type": type(exc).__name__,
            "exception_message": str(exc),
        }


def _assert_name_absent_at(directory_fd: int, filename: str) -> None:
    if Path(filename).name != filename or filename in {"", ".", ".."}:
        raise SnapshotV3BuildError("unsafe immutable config filename")
    try:
        os.stat(filename, dir_fd=directory_fd, follow_symlinks=False)
    except FileNotFoundError:
        return
    raise FileExistsError(f"immutable config target already exists: {filename}")


def _write_json_no_overwrite_at(
    directory_fd: int,
    filename: str,
    payload: Mapping[str, Any],
) -> str:
    _assert_name_absent_at(directory_fd, filename)
    body = base.canonical_json(dict(payload))
    expected_sha256 = base.sha256_bytes(body)
    base._write_cache_archive_at(directory_fd, filename, body)
    _assert_json_identity_at(
        directory_fd,
        filename,
        payload,
        expected_sha256=expected_sha256,
    )
    return expected_sha256


def _assert_json_identity_at(
    directory_fd: int,
    filename: str,
    payload: Mapping[str, Any],
    *,
    expected_sha256: str,
) -> None:
    body = base._read_verified_archive_at(
        directory_fd,
        filename,
        expected_sha256=expected_sha256,
    )
    if body != base.canonical_json(dict(payload)):
        raise SnapshotV3BuildError("immutable config JSON differs from canonical payload")


def _json_identity_is_present_at(
    directory_fd: int,
    filename: str,
    payload: Mapping[str, Any],
    *,
    expected_sha256: str,
) -> bool:
    try:
        _assert_json_identity_at(
            directory_fd,
            filename,
            payload,
            expected_sha256=expected_sha256,
        )
    except BaseException:
        return False
    return True


def _publish_reservation_with_terminal_on_error(
    *,
    repo_root: Path,
    config_dir_fd: int,
    reservation_name: str,
    failure_name: str,
    reservation: Mapping[str, Any],
    terminal_factory: Callable[[BaseException, str], Mapping[str, Any]],
) -> str:
    reservation_body = base.canonical_json(dict(reservation))
    reservation_hash = base.sha256_bytes(reservation_body)
    try:
        base._assert_directory_tree_matches_fd(repo_root, "configs", config_dir_fd)
        _assert_name_absent_at(config_dir_fd, reservation_name)
        base._write_cache_archive_at(
            config_dir_fd,
            reservation_name,
            reservation_body,
        )
        _assert_json_identity_at(
            config_dir_fd,
            reservation_name,
            reservation,
            expected_sha256=reservation_hash,
        )
        base._assert_directory_tree_matches_fd(repo_root, "configs", config_dir_fd)
    except BaseException as reservation_exc:
        reservation_published = _json_identity_is_present_at(
            config_dir_fd,
            reservation_name,
            reservation,
            expected_sha256=reservation_hash,
        )
        if reservation_published:
            try:
                try:
                    terminal = terminal_factory(reservation_exc, reservation_hash)
                except BaseException as factory_exc:
                    terminal = {
                        "schema_version": BUILD_EVIDENCE_SCHEMA,
                        "status": "FAILED_DURING_RESERVATION_TERMINAL_FACTORY",
                        "finished_at_utc": datetime.now(UTC).isoformat(),
                        "reservation_sha256": reservation_hash,
                        "archive_access_started": False,
                        "output_published": False,
                        "original_exception_type": type(reservation_exc).__name__,
                        "original_exception_message": str(reservation_exc),
                        "terminal_factory_exception_type": type(factory_exc).__name__,
                        "terminal_factory_exception_message": str(factory_exc),
                        "performance_or_strategy_execution_authorized": False,
                    }
                base._assert_directory_tree_matches_fd(repo_root, "configs", config_dir_fd)
                _write_json_no_overwrite_at(
                    config_dir_fd,
                    failure_name,
                    terminal,
                )
                base._assert_directory_tree_matches_fd(repo_root, "configs", config_dir_fd)
            except BaseException as terminal_exc:
                raise SnapshotV3BuildError(
                    "v3 reservation exists but terminal failure evidence could not be published"
                ) from terminal_exc
        raise
    return reservation_hash


def _file_identity_at(directory_fd: int, filename: str) -> dict[str, Any]:
    if Path(filename).name != filename or filename in {"", ".", ".."}:
        raise SnapshotV3BuildError("unsafe staged file identity")
    try:
        descriptor = os.open(filename, base._archive_read_flags(), dir_fd=directory_fd)
    except OSError as exc:
        raise SnapshotV3BuildError(f"cannot safely open staged file: {filename}") from exc
    try:
        info = os.fstat(descriptor)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_nlink != 1
            or info.st_size <= 0
            or info.st_size > MAX_STAGED_FILE_BYTES
        ):
            raise SnapshotV3BuildError(f"unsafe staged file profile: {filename}")
        digest = hashlib.sha256()
        observed = 0
        while True:
            chunk = os.read(descriptor, 8 * 1024 * 1024)
            if not chunk:
                break
            observed += len(chunk)
            if observed > MAX_STAGED_FILE_BYTES:
                raise SnapshotV3BuildError(f"staged file exceeds byte cap: {filename}")
            digest.update(chunk)
        final_info = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    identity_fields = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
    if (
        observed != info.st_size
        or any(getattr(info, field) != getattr(final_info, field) for field in identity_fields)
        or final_info.st_nlink != 1
    ):
        raise SnapshotV3BuildError(f"staged file changed while hashing: {filename}")
    return {"bytes": observed, "sha256": digest.hexdigest()}


def _publish_database_name_at(directory_fd: int, temporary_name: str) -> dict[str, Any]:
    if not _TEMPORARY_DATABASE_NAME.fullmatch(temporary_name):
        raise SnapshotV3BuildError("unsafe temporary database identity")
    temporary_identity = _file_identity_at(directory_fd, temporary_name)
    base._rename_exclusive_at(directory_fd, temporary_name, "market.duckdb")
    published_identity = _file_identity_at(directory_fd, "market.duckdb")
    if published_identity != temporary_identity:
        raise SnapshotV3BuildError("published database identity differs from temporary database")
    os.fsync(directory_fd)
    return published_identity


def _fsync_regular_file_at(directory_fd: int, filename: str) -> None:
    try:
        descriptor = os.open(filename, base._archive_read_flags(), dir_fd=directory_fd)
    except OSError as exc:
        raise SnapshotV3BuildError(f"cannot safely open staged file for fsync: {filename}") from exc
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise SnapshotV3BuildError(f"cannot fsync non-regular staged file: {filename}")
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _assert_staging_bundle_at(
    directory_fd: int,
    *,
    expected_database_identity: Mapping[str, Any],
    expected_evidence: Mapping[str, Any],
) -> dict[str, Any]:
    expected_names = {"market.duckdb", "build_evidence.json"}
    if set(os.listdir(directory_fd)) != expected_names:
        raise SnapshotV3BuildError("v3 staging bundle child set drifted")
    database_identity = _file_identity_at(directory_fd, "market.duckdb")
    if database_identity != dict(expected_database_identity):
        raise SnapshotV3BuildError("v3 staged database identity drifted")
    evidence_body = base.canonical_json(dict(expected_evidence))
    evidence_identity = _file_identity_at(directory_fd, "build_evidence.json")
    expected_evidence_identity = {
        "bytes": len(evidence_body),
        "sha256": base.sha256_bytes(evidence_body),
    }
    if evidence_identity != expected_evidence_identity:
        raise SnapshotV3BuildError("v3 staged success evidence identity drifted")
    return {
        "database": database_identity,
        "build_evidence": evidence_identity,
        "children": sorted(expected_names),
    }


def _probe_bundle_publication_at(
    parent_directory_fd: int,
    staging_directory_fd: int,
    *,
    final_name: str,
) -> tuple[bool | None, str]:
    if Path(final_name).name != final_name or final_name in {"", ".", ".."}:
        raise SnapshotV3BuildError("unsafe final bundle identity probe")
    retained = os.fstat(staging_directory_fd)
    if not stat.S_ISDIR(retained.st_mode):
        return None, "RETAINED_STAGING_INODE_IS_NOT_A_DIRECTORY"
    try:
        visible = os.stat(
            final_name,
            dir_fd=parent_directory_fd,
            follow_symlinks=False,
        )
    except FileNotFoundError:
        return False, "NOT_VISIBLE_AT_FINAL_NAME"
    except OSError:
        return None, "FINAL_VISIBILITY_UNKNOWN_DURING_FAILURE_PROBE"
    if stat.S_ISDIR(visible.st_mode) and (visible.st_dev, visible.st_ino) == (
        retained.st_dev,
        retained.st_ino,
    ):
        return True, "VISIBLE_RETAINED_INODE_DURABILITY_UNCONFIRMED"
    return None, "FINAL_NAME_DOES_NOT_MATCH_RETAINED_STAGING_INODE"


def _reconcile_failure_publication_outcome(
    current_outcome: tuple[bool | None, str, bool],
    parent_directory_fd: int,
    staging_directory_fd: int,
    *,
    final_name: str,
) -> tuple[bool | None, str, bool]:
    if current_outcome == CONFIRMED_PUBLICATION_OUTCOME:
        return current_outcome
    try:
        published, state = _probe_bundle_publication_at(
            parent_directory_fd,
            staging_directory_fd,
            final_name=final_name,
        )
    except BaseException:
        return (None, "FINAL_VISIBILITY_UNKNOWN_FAILURE_PROBE_FAILED", False)
    return (published, state, False)


def _archive_progress_evidence(
    *,
    archive_access_started: bool,
    downloads: Sequence[Mapping[str, Any]],
    archive_audits: Sequence[Mapping[str, Any]],
    archive_parse_attempted_count: int,
    archives_parsed_count: int,
    validated_vendor_rows: int,
    inserted_target_rows_confirmed: int,
    current_archive: Mapping[str, Any] | None,
) -> dict[str, Any]:
    audit_validated_rows = sum(int(audit["validated_vendor_rows"]) for audit in archive_audits)
    audit_inserted_rows = sum(
        int(audit["inserted_target_rows_confirmed"]) for audit in archive_audits
    )
    consistency_issues: list[str] = []
    if archive_parse_attempted_count < archives_parsed_count:
        consistency_issues.append("parsed_count_exceeds_attempted_count")
    if archive_parse_attempted_count > archives_parsed_count + 1:
        consistency_issues.append("more_than_one_parse_attempt_is_in_flight")
    if archives_parsed_count != len(archive_audits):
        consistency_issues.append("parsed_count_differs_from_completed_audits")
    if validated_vendor_rows != audit_validated_rows:
        consistency_issues.append("validated_row_counter_differs_from_audit_sum")
    if inserted_target_rows_confirmed != audit_inserted_rows:
        consistency_issues.append("inserted_row_counter_differs_from_audit_sum")
    if not archive_access_started and (
        downloads
        or archive_audits
        or archive_parse_attempted_count
        or archives_parsed_count
        or validated_vendor_rows
        or inserted_target_rows_confirmed
        or current_archive is not None
    ):
        consistency_issues.append("progress_exists_before_archive_access")
    return {
        "archive_access_started": archive_access_started,
        "cache_archives_verified_count": len(downloads),
        "archive_parse_attempted_count": archive_parse_attempted_count,
        "archives_parsed_count": archives_parsed_count,
        "validated_vendor_rows": validated_vendor_rows,
        "completed_audit_validated_vendor_rows": audit_validated_rows,
        "inserted_target_rows_confirmed": inserted_target_rows_confirmed,
        "completed_audit_inserted_target_rows_confirmed": audit_inserted_rows,
        "counter_consistency_pass": not consistency_issues,
        "counter_consistency_issues": consistency_issues,
        "current_archive_at_evidence_boundary": (
            dict(current_archive) if current_archive is not None else None
        ),
        "archive_audits_completed": [dict(audit) for audit in archive_audits],
    }


def _best_effort_archive_progress_evidence(
    *,
    archive_access_started: bool,
    downloads: Sequence[Mapping[str, Any]],
    archive_audits: Sequence[Mapping[str, Any]],
    archive_parse_attempted_count: int,
    archives_parsed_count: int,
    validated_vendor_rows: int,
    inserted_target_rows_confirmed: int,
    current_archive: Mapping[str, Any] | None,
) -> dict[str, Any]:
    try:
        return _archive_progress_evidence(
            archive_access_started=archive_access_started,
            downloads=downloads,
            archive_audits=archive_audits,
            archive_parse_attempted_count=archive_parse_attempted_count,
            archives_parsed_count=archives_parsed_count,
            validated_vendor_rows=validated_vendor_rows,
            inserted_target_rows_confirmed=inserted_target_rows_confirmed,
            current_archive=current_archive,
        )
    except BaseException as exc:
        return {
            "archive_access_started": archive_access_started,
            "cache_archives_verified_count": len(downloads),
            "archive_parse_attempted_count": archive_parse_attempted_count,
            "archives_parsed_count": archives_parsed_count,
            "validated_vendor_rows": validated_vendor_rows,
            "inserted_target_rows_confirmed": inserted_target_rows_confirmed,
            "current_archive_at_evidence_boundary": (
                dict(current_archive) if current_archive is not None else None
            ),
            "archive_audits_completed": [dict(audit) for audit in archive_audits],
            "counter_consistency_pass": False,
            "counter_consistency_issues": [
                f"progress_evidence_collection_failed:{type(exc).__name__}:{exc}"
            ],
        }


def build_snapshot(
    protocol_path: Path,
    vendor_lock_path: Path,
    *,
    repo_root: Path,
) -> dict[str, Any]:
    root = repo_root.resolve()
    canonical_protocol = _canonical_path(root, CANONICAL_PROTOCOL_RELATIVE)
    canonical_lock = _canonical_path(root, base.CANONICAL_VENDOR_LOCK_RELATIVE)
    if (
        protocol_path.resolve() != canonical_protocol
        or vendor_lock_path.resolve() != canonical_lock
    ):
        raise SnapshotV3BuildError("v3 build requires canonical protocol and vendor lock")
    protocol = base.load_strict_json(canonical_protocol)
    vendor_lock = base.load_strict_json(canonical_lock)
    _validate_protocol(protocol, repo_root=root)
    if base.sha256_file(canonical_lock) != VENDOR_LOCK_SHA256:
        raise SnapshotV3BuildError("v3 vendor lock file hash drifted")
    entries = base._validate_vendor_lock(
        vendor_lock,
        protocol_sha256=V2_PROTOCOL_SHA256,
        repo_root=root,
    )
    builder_path = Path(__file__).resolve()
    test_path = _canonical_path(root, CANONICAL_TEST_RELATIVE)
    protocol_hash = base.sha256_file(canonical_protocol)
    builder_hash = base.sha256_file(builder_path)
    test_hash = base.sha256_file(test_path)
    source_preflight = _source_identity(root)
    if not source_preflight["git"]["clean"]:
        raise SnapshotV3BuildError(
            f"v3 build requires a clean repo: {source_preflight['git']['status']}"
        )
    base._assert_commit_file_identity(
        root,
        str(source_preflight["git"]["commit"]),
        source_preflight["file_sha256"],
    )

    bundle, bundle_parent_relative, bundle_final_name = _canonical_bundle_target(root)
    cache = _canonical_path(root, base.CANONICAL_CACHE_RELATIVE)
    _reservation_path, reservation_name = _canonical_config_target(
        root,
        CANONICAL_RESERVATION_RELATIVE,
    )
    _failure_path, failure_name = _canonical_config_target(
        root,
        CANONICAL_FAILURE_EVIDENCE_RELATIVE,
    )
    config_dir_fd = base._open_directory_tree_no_symlinks(root, "configs", create=False)
    try:
        bundle_parent_fd = base._open_directory_tree_no_symlinks(
            root,
            bundle_parent_relative,
            create=True,
        )
    except BaseException:
        os.close(config_dir_fd)
        raise
    try:
        base._assert_directory_tree_matches_fd(root, "configs", config_dir_fd)
        _assert_name_absent_at(config_dir_fd, reservation_name)
        _assert_name_absent_at(config_dir_fd, failure_name)
        _assert_name_absent_at(bundle_parent_fd, bundle_final_name)
    except BaseException:
        os.close(config_dir_fd)
        os.close(bundle_parent_fd)
        raise

    started_at = datetime.now(UTC).isoformat()
    reservation = {
        "schema_version": BUILD_RESERVATION_SCHEMA,
        "status": "STARTED_IMMUTABLE_V3_ATTEMPT_RESERVATION",
        "attempt_number_within_v3": 1,
        "data_build_trial_count_before_execution": 1,
        "data_build_trial_count_including_this_attempt": 2,
        "started_at_utc": started_at,
        "protocol": {"path": CANONICAL_PROTOCOL_RELATIVE, "sha256": protocol_hash},
        "vendor_lock": {
            "path": base.CANONICAL_VENDOR_LOCK_RELATIVE,
            "sha256": VENDOR_LOCK_SHA256,
        },
        "coverage_diagnosis": {
            "path": CANONICAL_COVERAGE_DIAGNOSIS_RELATIVE,
            "sha256": COVERAGE_DIAGNOSIS_SHA256,
        },
        "builder": {
            "path": str(builder_path.relative_to(root)),
            "sha256": builder_hash,
            "test_path": CANONICAL_TEST_RELATIVE,
            "test_sha256": test_hash,
        },
        "git_commit": source_preflight["git"]["commit"],
        "archive_access_may_start_only_after_this_reservation": True,
        "performance_or_strategy_execution_authorized": False,
    }

    def reservation_terminal(
        reservation_exc: BaseException,
        reservation_hash: str,
    ) -> Mapping[str, Any]:
        return {
            "schema_version": BUILD_EVIDENCE_SCHEMA,
            "status": "FAILED_DURING_RESERVATION_PUBLICATION_BEFORE_ARCHIVE_ACCESS",
            "attempt_number_within_v3": 1,
            "data_build_trial_count_before_execution": 1,
            "data_build_trial_count_including_this_attempt": 2,
            "started_at_utc": started_at,
            "finished_at_utc": datetime.now(UTC).isoformat(),
            "source_kind": SOURCE_KIND,
            "reservation": {
                "path": CANONICAL_RESERVATION_RELATIVE,
                "sha256": reservation_hash,
                "published": True,
            },
            "source_preflight": source_preflight,
            "protocol": {"path": CANONICAL_PROTOCOL_RELATIVE, "sha256": protocol_hash},
            "vendor_lock": {
                "path": base.CANONICAL_VENDOR_LOCK_RELATIVE,
                "sha256": VENDOR_LOCK_SHA256,
            },
            "coverage_diagnosis": {
                "path": CANONICAL_COVERAGE_DIAGNOSIS_RELATIVE,
                "sha256": COVERAGE_DIAGNOSIS_SHA256,
            },
            "builder": {
                "path": str(builder_path.relative_to(root)),
                "sha256": builder_hash,
                "test_path": CANONICAL_TEST_RELATIVE,
                "test_sha256": test_hash,
            },
            "output_published": False,
            "output_publication_state": "NOT_RENAMED",
            "publication_durability_confirmed": False,
            "archive_access_started": False,
            "downloads_completed": [],
            "exception_type": type(reservation_exc).__name__,
            "exception_message": str(reservation_exc),
            "traceback": traceback.format_exc(),
            "governance": {
                "alpha_result_trials": 0,
                "strategy_engine_report_or_performance_code_imported": False,
                "exchange_account_or_credentials_used": False,
                "live_database_or_daemon_mutated": False,
            },
        }

    try:
        reservation_hash = _publish_reservation_with_terminal_on_error(
            repo_root=root,
            config_dir_fd=config_dir_fd,
            reservation_name=reservation_name,
            failure_name=failure_name,
            reservation=reservation,
            terminal_factory=reservation_terminal,
        )
    except BaseException:
        os.close(config_dir_fd)
        os.close(bundle_parent_fd)
        raise

    downloads: list[dict[str, Any]] = []
    archive_filenames: dict[tuple[str, str], str] = {}
    archive_audits: list[dict[str, Any]] = []
    archive_access_started = False
    archive_parse_attempted_count = 0
    archives_parsed_count = 0
    validated_vendor_rows = 0
    inserted_target_rows_confirmed = 0
    current_archive: dict[str, Any] | None = None
    cache_dir_fd: int | None = None
    staging_dir_fd: int | None = None
    staging_name: str | None = None
    connection: duckdb.DuckDBPyConnection | None = None
    publication_outcome: tuple[bool | None, str, bool] = (
        False,
        "NOT_RENAMED",
        False,
    )
    try:
        base._assert_directory_tree_matches_fd(root, "configs", config_dir_fd)
        cache_dir_fd = base._open_directory_tree_no_symlinks(
            root,
            base.CANONICAL_CACHE_RELATIVE,
            create=False,
        )
        expected_cache_filenames = {str(entry["filename"]) for entry in entries}
        actual_cache_filenames = set(os.listdir(cache_dir_fd))
        if actual_cache_filenames != expected_cache_filenames:
            raise SnapshotV3BuildError("v3 read-only cache filename set drifted")
        cache_manifest_digest = hashlib.sha256()
        for entry in entries:
            symbol = str(entry["symbol"])
            month = str(entry["month"])
            filename = str(entry["filename"])
            base._validate_cache_filename(symbol=symbol, filename=filename)
            archive_access_started = True
            current_archive = {
                "phase": "CACHE_SHA256_REVERIFICATION",
                "symbol": symbol,
                "month": month,
                "filename": filename,
            }
            archive_bytes = base._read_verified_archive_at(
                cache_dir_fd,
                filename,
                expected_sha256=str(entry["vendor_sha256"]),
            )
            archive_filenames[(symbol, month)] = filename
            cache_manifest_digest.update(
                f"{filename}|{len(archive_bytes)}|{entry['vendor_sha256']}\n".encode()
            )
            downloads.append(
                {
                    "symbol": symbol,
                    "month": month,
                    "filename": filename,
                    "source": "VERIFIED_EXISTING_READ_ONLY_CACHE",
                    "cache_logical_root": str(cache),
                    "cache_filename": filename,
                    "cache_directory_fd_bound": True,
                    "bytes": len(archive_bytes),
                    "sha256": base.sha256_bytes(archive_bytes),
                    "http_attempts": 0,
                    "final_url": None,
                    "response_headers": {},
                    "retrieved_at_utc": None,
                }
            )
            current_archive = None
        if len(downloads) != len(entries):
            raise SnapshotV3BuildError("v3 download audit count drifted")
        if cache_manifest_digest.hexdigest() != EXPECTED_CACHE_MANIFEST_SHA256:
            raise SnapshotV3BuildError("v3 read-only cache manifest hash drifted")

        staging_name, staging_dir_fd = base._create_staging_directory_at(
            bundle_parent_fd,
            final_name=bundle_final_name,
        )
        staging_bundle = bundle.parent / staging_name
        metadata = {
            "schema_version": BUILD_EVIDENCE_SCHEMA,
            "source_kind": SOURCE_KIND,
            "gap_policy": "EXACT_FROZEN_VENDOR_GAPS_NO_FILL",
            "protocol_sha256": protocol_hash,
            "vendor_lock_sha256": VENDOR_LOCK_SHA256,
            "coverage_diagnosis_sha256": COVERAGE_DIAGNOSIS_SHA256,
            "builder_sha256": builder_hash,
            "git_commit": str(source_preflight["git"]["commit"]),
            "history_start_utc": HISTORY_START.isoformat(),
            "evaluation_end_exclusive_utc": EVALUATION_END.isoformat(),
            "expected_total_rows": str(TOTAL_ROWS),
            "expected_ordered_primary_key_sha256": EXPECTED_KEY_SHA256,
        }
        with base._working_directory_fd(staging_dir_fd):
            temporary_database_name = f".market.{secrets.token_hex(32)}.duckdb"
            _assert_name_absent_at(staging_dir_fd, temporary_database_name)
            temporary_db = Path(temporary_database_name)
            try:
                connection = base._create_snapshot_db(temporary_db, metadata)
                insert_sql = "INSERT INTO ohlcv VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)"
                for entry in entries:
                    key = (str(entry["symbol"]), str(entry["month"]))
                    current_archive = {
                        "phase": "PARSE_VALIDATE_AND_INSERT",
                        "symbol": key[0],
                        "month": key[1],
                        "filename": str(entry["filename"]),
                    }
                    archive_parse_attempted_count += 1
                    archive_bytes = base._read_verified_archive_at(
                        cache_dir_fd,
                        archive_filenames[key],
                        expected_sha256=str(entry["vendor_sha256"]),
                    )
                    rows, archive_audit = parse_monthly_archive(
                        archive_bytes,
                        symbol=key[0],
                        month=key[1],
                        expected_filename=str(entry["filename"]),
                    )
                    archives_parsed_count += 1
                    validated_vendor_rows += int(archive_audit["rows"])
                    selected = tuple(
                        row for row in rows if HISTORY_START <= row[3] < EVALUATION_END
                    )
                    completed_audit = {
                        "symbol": key[0],
                        "month": key[1],
                        "vendor_sha256": entry["vendor_sha256"],
                        "validated_vendor_rows": archive_audit["rows"],
                        "full_calendar_rows": archive_audit["full_calendar_rows"],
                        "frozen_missing_rows": archive_audit["frozen_missing_rows"],
                        "selected_target_rows": len(selected),
                        "inserted_target_rows_confirmed": 0,
                        "first_ts": archive_audit["first_ts"],
                        "last_ts": archive_audit["last_ts"],
                        "zip_member": archive_audit["member"],
                        "parse_input_sha256": base.sha256_bytes(archive_bytes),
                    }
                    archive_audits.append(completed_audit)
                    if selected:
                        connection.executemany(insert_sql, selected)
                        completed_audit["inserted_target_rows_confirmed"] = len(selected)
                        inserted_target_rows_confirmed += len(selected)
                    current_archive = None
                archive_progress = _archive_progress_evidence(
                    archive_access_started=archive_access_started,
                    downloads=downloads,
                    archive_audits=archive_audits,
                    archive_parse_attempted_count=archive_parse_attempted_count,
                    archives_parsed_count=archives_parsed_count,
                    validated_vendor_rows=validated_vendor_rows,
                    inserted_target_rows_confirmed=inserted_target_rows_confirmed,
                    current_archive=current_archive,
                )
                if (
                    archive_progress["counter_consistency_pass"] is not True
                    or archive_progress["cache_archives_verified_count"] != len(entries)
                    or archive_progress["archive_parse_attempted_count"] != len(entries)
                    or archive_progress["archives_parsed_count"] != len(entries)
                    or archive_progress["validated_vendor_rows"] != EXPECTED_VALIDATED_VENDOR_ROWS
                    or archive_progress["inserted_target_rows_confirmed"] != TOTAL_ROWS
                    or archive_progress["current_archive_at_evidence_boundary"] is not None
                ):
                    raise SnapshotV3BuildError("v3 completed archive progress differs from freeze")
                qa_write = _validate_snapshot_db(connection, expected_metadata=metadata)
                connection.execute("CHECKPOINT")
                connection.close()
                connection = None
                temporary_identity = _file_identity_at(
                    staging_dir_fd,
                    temporary_database_name,
                )
                published_identity = _publish_database_name_at(
                    staging_dir_fd,
                    temporary_database_name,
                )
                if published_identity != temporary_identity:
                    raise SnapshotV3BuildError(
                        "v3 database identity changed during fixed-name publication"
                    )
                published_db = Path("market.duckdb")
                qa_read_only = _read_only_post_close_qa(
                    published_db,
                    expected_metadata=metadata,
                )
                if qa_read_only != qa_write:
                    raise SnapshotV3BuildError("v3 post-close QA differs from write QA")
                if _file_identity_at(staging_dir_fd, "market.duckdb") != published_identity:
                    raise SnapshotV3BuildError("v3 database identity changed during read-only QA")
                source_postflight = _source_identity(root)
                _assert_build_source_postflight(source_preflight, source_postflight)
                _fsync_regular_file_at(staging_dir_fd, "market.duckdb")
                final_database_identity = _file_identity_at(staging_dir_fd, "market.duckdb")
                if final_database_identity != published_identity:
                    raise SnapshotV3BuildError("v3 database identity changed after fsync")
                output_identity = {
                    "path": CANONICAL_OUTPUT_RELATIVE,
                    **final_database_identity,
                }
                evidence = {
                    "schema_version": BUILD_EVIDENCE_SCHEMA,
                    "status": "SUCCESS",
                    "attempt_number_within_v3": 1,
                    "data_build_trial_count_before_execution": 1,
                    "data_build_trial_count_including_this_attempt": 2,
                    "started_at_utc": started_at,
                    "finished_at_utc": datetime.now(UTC).isoformat(),
                    "source_kind": SOURCE_KIND,
                    "gap_policy": {
                        "exact_vendor_gap_manifest": _gap_manifest(),
                        "forward_fill_interpolation_resampling_or_synthetic_rows": False,
                    },
                    "reservation": {
                        "path": CANONICAL_RESERVATION_RELATIVE,
                        "sha256": reservation_hash,
                    },
                    "source_preflight": source_preflight,
                    "source_postflight": source_postflight,
                    "protocol": {"path": CANONICAL_PROTOCOL_RELATIVE, "sha256": protocol_hash},
                    "vendor_lock": {
                        "path": base.CANONICAL_VENDOR_LOCK_RELATIVE,
                        "sha256": VENDOR_LOCK_SHA256,
                        "entries": len(entries),
                    },
                    "coverage_diagnosis": {
                        "path": CANONICAL_COVERAGE_DIAGNOSIS_RELATIVE,
                        "sha256": COVERAGE_DIAGNOSIS_SHA256,
                    },
                    "builder": {
                        "path": str(builder_path.relative_to(root)),
                        "sha256": builder_hash,
                        "test_path": CANONICAL_TEST_RELATIVE,
                        "test_sha256": test_hash,
                    },
                    "output": output_identity,
                    "qa_write_connection": qa_write,
                    "qa_read_only_post_close": qa_read_only,
                    "qa_pre_post_exact_match": True,
                    "archive_access_started": archive_access_started,
                    "downloads": downloads,
                    "archive_progress": archive_progress,
                    "governance": {
                        "alpha_result_trials": 0,
                        "strategy_engine_report_or_performance_code_imported": False,
                        "exchange_account_or_credentials_used": False,
                        "live_database_or_daemon_mutated": False,
                        "failed_v1_or_v2_database_rows_reused": False,
                        "database_and_success_evidence_published_as_one_atomic_bundle": True,
                    },
                }
                _write_json_no_overwrite_at(
                    staging_dir_fd,
                    "build_evidence.json",
                    evidence,
                )
                _assert_staging_bundle_at(
                    staging_dir_fd,
                    expected_database_identity=final_database_identity,
                    expected_evidence=evidence,
                )
                os.fsync(staging_dir_fd)
            finally:
                if connection is not None:
                    with contextlib.suppress(Exception):
                        connection.close()
                    connection = None
        source_publish_boundary = _source_identity(root)
        _assert_build_source_postflight(source_preflight, source_publish_boundary)
        if source_publish_boundary != source_postflight:
            raise SnapshotV3BuildError("v3 source changed before publication")
        _assert_json_identity_at(
            config_dir_fd,
            reservation_name,
            reservation,
            expected_sha256=reservation_hash,
        )
        base._assert_directory_tree_matches_fd(root, "configs", config_dir_fd)
        _assert_staging_bundle_at(
            staging_dir_fd,
            expected_database_identity=final_database_identity,
            expected_evidence=evidence,
        )
        base._publish_bundle_atomic(
            staging_bundle,
            bundle,
            parent_dir_fd=bundle_parent_fd,
            staging_dir_fd=staging_dir_fd,
            identity_root=root,
            identity_relative=bundle_parent_relative,
        )
        publication_outcome = CONFIRMED_PUBLICATION_OUTCOME
        _assert_staging_bundle_at(
            staging_dir_fd,
            expected_database_identity=final_database_identity,
            expected_evidence=evidence,
        )
        staging_name = None
        return evidence
    except BaseException as exc:
        if isinstance(exc, base.BundlePublicationError):
            publication_outcome = (
                base._publication_confirmation(exc.publication_state),
                exc.publication_state,
                False,
            )
        elif staging_dir_fd is not None:
            publication_outcome = _reconcile_failure_publication_outcome(
                publication_outcome,
                bundle_parent_fd,
                staging_dir_fd,
                final_name=bundle_final_name,
            )
        if connection is not None:
            with contextlib.suppress(Exception):
                connection.close()
            connection = None
        failure_archive_progress = _best_effort_archive_progress_evidence(
            archive_access_started=archive_access_started,
            downloads=downloads,
            archive_audits=archive_audits,
            archive_parse_attempted_count=archive_parse_attempted_count,
            archives_parsed_count=archives_parsed_count,
            validated_vendor_rows=validated_vendor_rows,
            inserted_target_rows_confirmed=inserted_target_rows_confirmed,
            current_archive=current_archive,
        )
        failure_evidence = {
            "schema_version": BUILD_EVIDENCE_SCHEMA,
            "status": "FAILED",
            "attempt_number_within_v3": 1,
            "data_build_trial_count_before_execution": 1,
            "data_build_trial_count_including_this_attempt": 2,
            "started_at_utc": started_at,
            "finished_at_utc": datetime.now(UTC).isoformat(),
            "source_kind": SOURCE_KIND,
            "reservation": {
                "path": CANONICAL_RESERVATION_RELATIVE,
                "sha256": reservation_hash,
            },
            "source_preflight": source_preflight,
            "source_at_failure": _best_effort_source_identity(root),
            "protocol": {"path": CANONICAL_PROTOCOL_RELATIVE, "sha256": protocol_hash},
            "vendor_lock": {
                "path": base.CANONICAL_VENDOR_LOCK_RELATIVE,
                "sha256": VENDOR_LOCK_SHA256,
                "entries": len(entries),
            },
            "coverage_diagnosis": {
                "path": CANONICAL_COVERAGE_DIAGNOSIS_RELATIVE,
                "sha256": COVERAGE_DIAGNOSIS_SHA256,
            },
            "builder": {
                "path": str(builder_path.relative_to(root)),
                "sha256": builder_hash,
                "test_path": CANONICAL_TEST_RELATIVE,
                "test_sha256": test_hash,
            },
            "output_published": publication_outcome[0],
            "output_publication_state": publication_outcome[1],
            "publication_durability_confirmed": publication_outcome[2],
            "archive_access_started": archive_access_started,
            "downloads_completed": downloads,
            "archive_progress": failure_archive_progress,
            "exception_type": type(exc).__name__,
            "exception_message": str(exc),
            "traceback": traceback.format_exc(),
            "governance": {
                "alpha_result_trials": 0,
                "strategy_engine_report_or_performance_code_imported": False,
                "exchange_account_or_credentials_used": False,
                "live_database_or_daemon_mutated": False,
            },
        }
        try:
            base._assert_directory_tree_matches_fd(root, "configs", config_dir_fd)
            _write_json_no_overwrite_at(
                config_dir_fd,
                failure_name,
                failure_evidence,
            )
            base._assert_directory_tree_matches_fd(root, "configs", config_dir_fd)
        except BaseException as evidence_exc:
            raise SnapshotV3BuildError(
                "v3 build failed and failure evidence publication also failed"
            ) from evidence_exc
        raise
    finally:
        if staging_name is not None and staging_dir_fd is not None and bundle_parent_fd is not None:
            with contextlib.suppress(Exception):
                base._remove_staging_directory_at(
                    bundle_parent_fd,
                    staging_dir_fd,
                    staging_name,
                )
        if staging_dir_fd is not None:
            os.close(staging_dir_fd)
        if cache_dir_fd is not None:
            os.close(cache_dir_fd)
        os.close(bundle_parent_fd)
        os.close(config_dir_fd)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--protocol", type=Path)
    parser.add_argument("--vendor-lock", type=Path)
    args = parser.parse_args(argv)
    root = args.repo_root.resolve()
    protocol = args.protocol or root / CANONICAL_PROTOCOL_RELATIVE
    vendor_lock = args.vendor_lock or root / base.CANONICAL_VENDOR_LOCK_RELATIVE
    result = build_snapshot(protocol, vendor_lock, repo_root=root)
    print(
        json.dumps(
            {
                "status": "V3_SNAPSHOT_BUILT",
                "rows": result["qa_read_only_post_close"]["total_rows"],
                "output": CANONICAL_OUTPUT_RELATIVE,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
