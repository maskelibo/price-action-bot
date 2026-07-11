"""Build an immutable, checksum-pinned Binance USD-M 15m research snapshot.

This tool is intentionally isolated from strategy, engine, report, live DB, and
exchange-account code.  It has two networked phases:

``pin``
    Download only Binance Public Data ``.CHECKSUM`` sidecars and publish an
    immutable vendor lock.  No kline ZIP is downloaded or parsed.

``build``
    Require a clean committed protocol + vendor lock, download the pinned ZIPs,
    verify every vendor checksum and ZIP/CSV invariant, then create a new
    no-overwrite DuckDB containing only the frozen primary13 + BTC reference
    interval.  No source row is taken from the failed v1 snapshot.

Forward-fill, interpolation, resampling, synthetic OHLCV, spot data, mark/index
klines, mutable live databases, and strategy/performance imports are forbidden.
"""

from __future__ import annotations

import argparse
import calendar
import contextlib
import csv
import ctypes
import errno
import hashlib
import io
import json
import math
import os
import re
import secrets
import stat
import subprocess
import tempfile
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from collections.abc import Iterator, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from functools import cache
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as package_version
from pathlib import Path
from typing import Any

import duckdb

PROTOCOL_SCHEMA = "crypto-15m-v15p2-usdm-snapshot-build-protocol-v1"
VENDOR_LOCK_SCHEMA = "crypto-15m-v15p2-usdm-vendor-lock-v1"
BUILD_EVIDENCE_SCHEMA = "crypto-15m-v15p2-usdm-snapshot-build-evidence-v1"
BUILD_RESERVATION_SCHEMA = "crypto-15m-v15p2-usdm-snapshot-build-reservation-v1"
SOURCE_KIND = "BINANCE_PUBLIC_DATA_USDM_CONTRACT_PRICE_KLINES"
BASE_URL = "https://data.binance.vision/data/futures/um/monthly/klines"
TIMEFRAME = "15m"
BAR_MS = 15 * 60 * 1000
HISTORY_START = datetime(2021, 2, 21, tzinfo=UTC)
EVALUATION_END = datetime(2026, 6, 1, tzinfo=UTC)
MONTH_START = "2021-02"
MONTH_END = "2026-05"
ROWS_PER_SYMBOL = 184_896
TOTAL_ROWS = 2_588_544
DOWNLOAD_WORKERS = 6
HTTP_TIMEOUT_SECONDS = 60
HTTP_RETRIES = 5
USER_AGENT = "price-action-bot-audit-snapshot-builder/1.0"
MAX_CHECKSUM_RESPONSE_BYTES = 1_024
MAX_ZIP_RESPONSE_BYTES = 128 * 1024 * 1024
MAX_ZIP_MEMBER_BYTES = 256 * 1024 * 1024
MAX_ZIP_COMPRESSION_RATIO = 100.0
MAX_IDENTITY_JSON_BYTES = 16 * 1024 * 1024
CANONICAL_CSV_HEADER = (
    "open_time",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "close_time",
    "quote_volume",
    "count",
    "taker_buy_volume",
    "taker_buy_quote_volume",
    "ignore",
)

SYMBOLS = (
    "ETHUSDT",
    "SOLUSDT",
    "BNBUSDT",
    "ADAUSDT",
    "AVAXUSDT",
    "LINKUSDT",
    "DOTUSDT",
    "DOGEUSDT",
    "ZECUSDT",
    "NEARUSDT",
    "FILUSDT",
    "ATOMUSDT",
    "ALGOUSDT",
    "BTCUSDT",
)
SYMBOL_TO_CANONICAL = {symbol: f"{symbol[:-4]}/USDT" for symbol in SYMBOLS}

CANONICAL_PROTOCOL_RELATIVE = "configs/crypto_15m_v15p2_usdm_snapshot_v2_build_protocol.json"
CANONICAL_VENDOR_LOCK_RELATIVE = "configs/crypto_15m_v15p2_usdm_snapshot_v2_vendor_lock.json"
CANONICAL_BUNDLE_RELATIVE = "data/backups/20260711_v15p2_v2_usdm"
CANONICAL_BUILD_EVIDENCE_RELATIVE = f"{CANONICAL_BUNDLE_RELATIVE}/build_evidence.json"
CANONICAL_OUTPUT_RELATIVE = f"{CANONICAL_BUNDLE_RELATIVE}/market.duckdb"
CANONICAL_CACHE_RELATIVE = "data/backups/20260711_v15p2_v2_usdm_vendor_cache"
CANONICAL_RESERVATION_RELATIVE = (
    "configs/crypto_15m_v15p2_usdm_snapshot_v2_build_attempt_001_started.json"
)
CANONICAL_FAILURE_EVIDENCE_RELATIVE = (
    "configs/crypto_15m_v15p2_usdm_snapshot_v2_build_attempt_001_failure.json"
)
CANONICAL_TEST_RELATIVE = "tests/test_crypto_15m_usdm_snapshot_v2_builder.py"

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_MONTH = re.compile(r"^\d{4}-\d{2}$")


class SnapshotBuildError(RuntimeError):
    """Raised when an immutable data-build contract fails closed."""


class BundlePublicationError(SnapshotBuildError):
    """Raised after atomic rename when final visibility or durability is not successful."""

    def __init__(self, message: str, *, publication_state: str) -> None:
        super().__init__(message)
        self.publication_state = publication_state


def _publication_confirmation(publication_state: str) -> bool | None:
    mapping: dict[str, bool | None] = {
        "NOT_RENAMED": False,
        "RETAINED_INODE_NOT_VISIBLE_AT_FINAL_NAME": False,
        "VISIBLE_RETAINED_INODE_DURABILITY_UNCONFIRMED": True,
        "VISIBLE_RETAINED_INODE_DURABILITY_CONFIRMED": True,
        "FINAL_VISIBILITY_UNKNOWN_AFTER_ATOMIC_RENAME": None,
    }
    try:
        return mapping[publication_state]
    except KeyError as exc:
        raise SnapshotBuildError(f"unknown publication state: {publication_state}") from exc


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path, *, chunk_size: int = 8 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_json(payload: Any) -> bytes:
    return (
        json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
    ).encode("utf-8")


def load_strict_json(path: Path) -> dict[str, Any]:
    def reject_duplicate(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise SnapshotBuildError(f"duplicate JSON key in {path}: {key!r}")
            result[key] = value
        return result

    def reject_nonfinite(value: str) -> Any:
        raise SnapshotBuildError(f"non-finite JSON constant in {path}: {value}")

    try:
        loaded = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=reject_duplicate,
            parse_constant=reject_nonfinite,
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SnapshotBuildError(f"cannot load strict JSON: {path}") from exc
    if not isinstance(loaded, dict):
        raise SnapshotBuildError(f"JSON root must be a mapping: {path}")
    return loaded


def write_bytes_no_overwrite(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() or path.is_symlink():
        raise FileExistsError(f"refusing to overwrite immutable output: {path}")
    temporary: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary = handle.name
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temporary, path)
        Path(temporary).unlink()
        temporary = None
        _fsync_directory(path.parent)
    finally:
        if temporary is not None:
            Path(temporary).unlink(missing_ok=True)


def write_json_no_overwrite(path: Path, payload: Mapping[str, Any]) -> None:
    write_bytes_no_overwrite(path, canonical_json(dict(payload)))


def _month_range(start: str = MONTH_START, end: str = MONTH_END) -> tuple[str, ...]:
    if not _MONTH.fullmatch(start) or not _MONTH.fullmatch(end):
        raise ValueError("month values must be YYYY-MM")
    year, month = map(int, start.split("-"))
    end_year, end_month = map(int, end.split("-"))
    result: list[str] = []
    while (year, month) <= (end_year, end_month):
        result.append(f"{year:04d}-{month:02d}")
        month += 1
        if month == 13:
            year += 1
            month = 1
    return tuple(result)


def expected_vendor_entries() -> tuple[dict[str, str], ...]:
    entries: list[dict[str, str]] = []
    for symbol in SYMBOLS:
        for month in _month_range():
            filename = f"{symbol}-{TIMEFRAME}-{month}.zip"
            zip_url = f"{BASE_URL}/{symbol}/{TIMEFRAME}/{filename}"
            entries.append(
                {
                    "symbol": symbol,
                    "canonical_symbol": SYMBOL_TO_CANONICAL[symbol],
                    "month": month,
                    "filename": filename,
                    "zip_url": zip_url,
                    "checksum_url": f"{zip_url}.CHECKSUM",
                }
            )
    return tuple(entries)


@cache
def expected_key_sha256() -> str:
    digest = hashlib.sha256()
    start_ms = int(HISTORY_START.timestamp() * 1000)
    end_ms = int(EVALUATION_END.timestamp() * 1000)
    for symbol in SYMBOLS:
        canonical = SYMBOL_TO_CANONICAL[symbol]
        for timestamp_ms in range(start_ms, end_ms, BAR_MS):
            digest.update(f"binance|{canonical}|15m|{timestamp_ms}\n".encode())
    return digest.hexdigest()


def _http_get(url: str, *, max_bytes: int) -> tuple[bytes, dict[str, str], int, str]:
    if max_bytes <= 0:
        raise ValueError("max_bytes must be positive")
    last_error: BaseException | None = None
    for attempt in range(1, HTTP_RETRIES + 1):
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
                if response.status != 200:
                    raise SnapshotBuildError(f"HTTP {response.status} for {url}")
                final_url = response.geturl()
                if final_url != url:
                    raise SnapshotBuildError(f"HTTP redirect is forbidden: {url} -> {final_url}")
                headers = {
                    key.lower(): value
                    for key, value in response.headers.items()
                    if key.lower() in {"content-length", "last-modified", "etag", "content-type"}
                }
                raw_length = headers.get("content-length")
                if raw_length is not None:
                    try:
                        declared_length = int(raw_length)
                    except ValueError as exc:
                        raise SnapshotBuildError(f"invalid Content-Length for {url}") from exc
                    if declared_length < 0 or declared_length > max_bytes:
                        raise SnapshotBuildError(
                            f"response Content-Length exceeds cap for {url}: {declared_length}"
                        )
                chunks: list[bytes] = []
                observed = 0
                while True:
                    chunk = response.read(min(1024 * 1024, max_bytes - observed + 1))
                    if not chunk:
                        break
                    observed += len(chunk)
                    if observed > max_bytes:
                        raise SnapshotBuildError(
                            f"response body exceeds {max_bytes} byte cap: {url}"
                        )
                    chunks.append(chunk)
                return b"".join(chunks), headers, attempt, final_url
        except SnapshotBuildError:
            raise
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last_error = exc
            if attempt == HTTP_RETRIES:
                break
            time.sleep(min(2 ** (attempt - 1), 16))
    raise SnapshotBuildError(
        f"download failed after {HTTP_RETRIES} attempts: {url}"
    ) from last_error


def parse_vendor_checksum(body: bytes, *, expected_filename: str) -> str:
    try:
        text = body.decode("ascii").strip()
    except UnicodeDecodeError as exc:
        raise SnapshotBuildError("vendor checksum is not ASCII") from exc
    parts = text.split()
    if len(parts) != 2 or parts[1].lstrip("*") != expected_filename:
        raise SnapshotBuildError(
            f"vendor checksum filename drift: expected={expected_filename!r}, body={text!r}"
        )
    digest = parts[0].lower()
    if not _SHA256.fullmatch(digest):
        raise SnapshotBuildError(f"invalid vendor SHA-256: {digest!r}")
    return digest


def _runtime_versions() -> dict[str, str]:
    result = {"python": os.sys.version.split()[0]}
    for distribution in ("duckdb",):
        try:
            result[distribution] = package_version(distribution)
        except PackageNotFoundError as exc:
            raise SnapshotBuildError(f"missing runtime distribution: {distribution}") from exc
    return result


def _git_state(repo_root: Path) -> dict[str, Any]:
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        status = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=all"],
            cwd=repo_root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError) as exc:
        raise SnapshotBuildError("git provenance is unavailable") from exc
    return {"commit": commit, "clean": status == "", "status": status.splitlines()}


def _source_identity(repo_root: Path, *, include_vendor_lock: bool) -> dict[str, Any]:
    paths = [
        CANONICAL_PROTOCOL_RELATIVE,
        str(Path(__file__).resolve().relative_to(repo_root.resolve())),
        CANONICAL_TEST_RELATIVE,
    ]
    if include_vendor_lock:
        paths.append(CANONICAL_VENDOR_LOCK_RELATIVE)
    return {
        "git": _git_state(repo_root),
        "file_sha256": {
            relative: sha256_file(_canonical_path(repo_root, relative)) for relative in paths
        },
        "runtime_versions": _runtime_versions(),
    }


def _assert_git_commit_ancestor(repo_root: Path, commit: str) -> None:
    try:
        subprocess.run(
            ["git", "cat-file", "-e", f"{commit}^{{commit}}"],
            cwd=repo_root,
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "merge-base", "--is-ancestor", commit, "HEAD"],
            cwd=repo_root,
            check=True,
            capture_output=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise SnapshotBuildError("vendor-lock phase-1 commit is not a HEAD ancestor") from exc


def _assert_commit_file_identity(
    repo_root: Path,
    commit: str,
    expected_file_sha256: Mapping[str, str],
) -> None:
    _assert_git_commit_ancestor(repo_root, commit)
    try:
        for relative, expected_sha256 in expected_file_sha256.items():
            if (
                not isinstance(relative, str)
                or Path(relative).is_absolute()
                or ".." in Path(relative).parts
                or not _SHA256.fullmatch(str(expected_sha256))
            ):
                raise SnapshotBuildError("phase-1 committed file identity is malformed")
            blob = subprocess.run(
                ["git", "show", f"{commit}:{relative}"],
                cwd=repo_root,
                check=True,
                capture_output=True,
            ).stdout
            if sha256_bytes(blob) != expected_sha256:
                raise SnapshotBuildError(f"committed blob hash drifted: {relative}")
    except SnapshotBuildError:
        raise
    except (OSError, subprocess.CalledProcessError) as exc:
        raise SnapshotBuildError("cannot prove committed source identity") from exc


def _assert_phase_1_commit_identity(
    repo_root: Path,
    commit: str,
    expected_file_sha256: Mapping[str, str],
) -> None:
    _assert_commit_file_identity(repo_root, commit, expected_file_sha256)
    try:
        lock_listing = subprocess.run(
            [
                "git",
                "ls-tree",
                "-r",
                "--name-only",
                commit,
                "--",
                CANONICAL_VENDOR_LOCK_RELATIVE,
            ],
            cwd=repo_root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError) as exc:
        raise SnapshotBuildError("cannot prove phase-1 vendor-lock absence") from exc
    if lock_listing:
        raise SnapshotBuildError("vendor lock already existed in the phase-1 commit")


def _canonical_path(repo_root: Path, relative: str) -> Path:
    root = repo_root.resolve()
    path = (root / relative).resolve()
    if root not in path.parents:
        raise SnapshotBuildError(f"path escapes repo root: {relative}")
    return path


def _validate_protocol(protocol: Mapping[str, Any], *, repo_root: Path) -> None:
    exact_top_level = {
        "schema_version",
        "status",
        "created_at_utc",
        "source_kind",
        "market_type",
        "base_url",
        "timeframe",
        "history_start_inclusive_utc",
        "evaluation_end_exclusive_utc",
        "month_start",
        "month_end",
        "symbols",
        "canonical_symbols",
        "vendor_file_count",
        "expected_rows_per_symbol",
        "expected_total_rows",
        "expected_key_sha256",
        "builder_path",
        "builder_sha256",
        "builder_test_path",
        "builder_test_sha256",
        "vendor_lock_path",
        "output_path",
        "vendor_cache_path",
        "build_evidence_path",
        "build_reservation_path",
        "build_failure_evidence_path",
        "data_build_trial_count_before_execution",
        "predecessor_failure",
        "source_selection",
        "pre_protocol_access_disclosure",
        "two_phase_lock",
        "snapshot_qa",
        "governance",
    }
    if set(protocol) != exact_top_level:
        raise SnapshotBuildError("build protocol top-level fields drifted")
    expected = {
        "schema_version": PROTOCOL_SCHEMA,
        "status": "PREREGISTERED_BEFORE_BULK_VENDOR_ZIP_DOWNLOAD",
        "created_at_utc": "2026-07-11T13:10:00Z",
        "source_kind": SOURCE_KIND,
        "market_type": "USD_M_PERPETUAL_CONTRACT_PRICE",
        "base_url": BASE_URL,
        "timeframe": TIMEFRAME,
        "history_start_inclusive_utc": HISTORY_START.isoformat(),
        "evaluation_end_exclusive_utc": EVALUATION_END.isoformat(),
        "month_start": MONTH_START,
        "month_end": MONTH_END,
        "symbols": list(SYMBOLS),
        "canonical_symbols": [SYMBOL_TO_CANONICAL[symbol] for symbol in SYMBOLS],
        "vendor_file_count": len(expected_vendor_entries()),
        "expected_rows_per_symbol": ROWS_PER_SYMBOL,
        "expected_total_rows": TOTAL_ROWS,
        "expected_key_sha256": expected_key_sha256(),
        "vendor_lock_path": CANONICAL_VENDOR_LOCK_RELATIVE,
        "output_path": CANONICAL_OUTPUT_RELATIVE,
        "vendor_cache_path": CANONICAL_CACHE_RELATIVE,
        "build_evidence_path": CANONICAL_BUILD_EVIDENCE_RELATIVE,
        "build_reservation_path": CANONICAL_RESERVATION_RELATIVE,
        "build_failure_evidence_path": CANONICAL_FAILURE_EVIDENCE_RELATIVE,
        "data_build_trial_count_before_execution": 0,
        "builder_path": str(Path(__file__).resolve().relative_to(repo_root.resolve())),
        "builder_test_path": CANONICAL_TEST_RELATIVE,
    }
    for key, value in expected.items():
        if protocol.get(key) != value:
            raise SnapshotBuildError(f"build protocol field drifted: {key}")
    builder_path = Path(__file__).resolve()
    if protocol.get("builder_sha256") != sha256_file(builder_path):
        raise SnapshotBuildError("builder source differs from committed protocol")
    test_path = _canonical_path(repo_root, CANONICAL_TEST_RELATIVE)
    if protocol.get("builder_test_sha256") != sha256_file(test_path):
        raise SnapshotBuildError("builder test source differs from committed protocol")
    predecessor = {
        "sealed_artifact_path": ("configs/crypto_15m_v15p2_fair_baseline_v1_coverage_failure.json"),
        "sealed_artifact_sha256": (
            "34a844100497bab4ee6edc6cba5efea26bdf6d9ce7278bf384a86fb9d58fab76"
        ),
        "seal_commit": "f6c7dd9e69b4f8c4c7fe54333116dbb6c118f89b",
        "attempt_source_commit": "05fc820c0a684954ec035a164b82bda0bf57ab66",
        "attempt_preregistration_sha256": (
            "695fb5b7a07fc0bb54c0a69b10f0893d246926a4339a17b5e8705802800f9c22"
        ),
        "supplemental_attestation_path": (
            "configs/crypto_15m_v15p2_fair_baseline_v1_coverage_failure_"
            "supplemental_attestation.json"
        ),
        "supplemental_attestation_sha256": (
            "1254512f1238f1e4bc3a58d0b2331ffad6d5c3e2f995c42d138aa998562c2e03"
        ),
        "performance_result_produced": False,
    }
    if protocol.get("predecessor_failure") != predecessor:
        raise SnapshotBuildError("predecessor failure identity drifted")
    for path_key, hash_key in (
        ("sealed_artifact_path", "sealed_artifact_sha256"),
        ("supplemental_attestation_path", "supplemental_attestation_sha256"),
    ):
        if sha256_file(_canonical_path(repo_root, predecessor[path_key])) != predecessor[hash_key]:
            raise SnapshotBuildError(f"predecessor file hash drifted: {path_key}")

    source_selection = protocol.get("source_selection")
    if not isinstance(source_selection, dict) or set(source_selection) != {
        "full_single_source_rebuild",
        "failed_v1_snapshot_rows_reused",
        "reason",
        "official_archive_url_template",
        "official_checksum_url_template",
        "official_documentation",
        "archive_mutability_warning",
    }:
        raise SnapshotBuildError("source-selection contract fields drifted")
    if (
        source_selection["full_single_source_rebuild"] is not True
        or source_selection["failed_v1_snapshot_rows_reused"] is not False
        or source_selection["official_archive_url_template"]
        != f"{BASE_URL}/{{SYMBOL}}/15m/{{SYMBOL}}-15m-{{YYYY-MM}}.zip"
        or source_selection["official_checksum_url_template"]
        != f"{BASE_URL}/{{SYMBOL}}/15m/{{SYMBOL}}-15m-{{YYYY-MM}}.zip.CHECKSUM"
        or source_selection["official_documentation"]
        != [
            "https://github.com/binance/binance-public-data",
            "https://github.com/binance/binance-public-data/tree/master/python",
            "https://developers.binance.com/en/docs/derivatives/usds-margined-futures/"
            "market-data/rest-api/Kline-Candlestick-Data",
        ]
        or not isinstance(source_selection["reason"], str)
        or not source_selection["reason"].strip()
        or not isinstance(source_selection["archive_mutability_warning"], str)
        or not source_selection["archive_mutability_warning"].strip()
    ):
        raise SnapshotBuildError("source-selection contract drifted")

    access = protocol.get("pre_protocol_access_disclosure")
    expected_access = {
        "coverage_only_snapshot_accessed": True,
        "first_ten_ATOM_open_and_close_rows_seen": True,
        "direct_public_spot_and_fapi_ETH_probe_rows_seen": True,
        "temporary_research_downloads_of_spot_and_usdm_monthly_archives_occurred": True,
        "temporary_research_downloads_retained_in_repo_or_used_as_build_cache": False,
        "vendor_checksums_on_temporary_research_downloads_verified": True,
        "signals_trades_returns_roi_drawdown_or_scenario_metrics_seen": False,
        "strategy_universe_threshold_execution_cost_or_risk_policy_selected_from_values": False,
        "purpose": "Data-source lineage and coverage diagnosis only",
        "alpha_result_trials": 0,
    }
    if access != expected_access:
        raise SnapshotBuildError("pre-protocol access disclosure drifted")
    expected_two_phase = {
        "phase_1": "Commit this protocol and builder before pinning all 896 vendor checksum sidecars.",
        "phase_2": "Commit the generated vendor lock before downloading any of the 896 bulk kline ZIPs.",
        "bulk_build_before_phase_2_commit_forbidden": True,
    }
    if protocol.get("two_phase_lock") != expected_two_phase:
        raise SnapshotBuildError("two-phase lock contract drifted")
    expected_qa = {
        "exact_ordered_symbols_required": 14,
        "unique_primary_key": ["venue", "symbol", "timeframe", "ts"],
        "exact_utc_15m_grid_required": True,
        "expected_first_ts": "2021-02-21T00:00:00Z",
        "expected_last_ts": "2026-05-31T23:45:00Z",
        "complete_utc_days_require_96_bars": True,
        "duplicate_null_nonfinite_or_invalid_ohlc_rows_allowed": 0,
        "volume_must_be_nonnegative": True,
        "per_symbol_content_sha256_required": True,
        "final_database_size_and_sha256_required": True,
        "read_only_post_close_reverification_required": True,
        "actual_database_key_sha256_required": True,
        "atomic_database_and_success_evidence_bundle_required": True,
    }
    if protocol.get("snapshot_qa") != expected_qa:
        raise SnapshotBuildError("snapshot QA contract drifted")
    expected_governance = {
        "single_source_full_rebuild": True,
        "vendor_checksum_required_before_unzip": True,
        "zip_crc_and_exact_member_required": True,
        "exact_15m_grid_required": True,
        "failed_v1_rows_reuse_forbidden": True,
        "spot_mark_index_and_other_market_data_forbidden": True,
        "forward_fill_interpolation_resampling_and_synthetic_rows_forbidden": True,
        "strategy_engine_report_and_performance_imports_forbidden": True,
        "live_database_and_shared_parquet_mutation_forbidden": True,
        "clean_committed_protocol_and_vendor_lock_required_before_build": True,
        "no_overwrite_output_and_evidence": True,
        "performance_results_seen": False,
        "alpha_result_trials": 0,
        "live_or_paper_daemon_restart_authorized": False,
        "exchange_account_or_credentials_authorized": False,
        "deployment_authorized": False,
    }
    if protocol.get("governance") != expected_governance:
        raise SnapshotBuildError("build protocol governance contract drifted")


def pin_vendor_lock(protocol_path: Path, *, repo_root: Path) -> dict[str, Any]:
    root = repo_root.resolve()
    canonical_protocol = _canonical_path(root, CANONICAL_PROTOCOL_RELATIVE)
    if protocol_path.resolve() != canonical_protocol:
        raise SnapshotBuildError("pin requires the canonical build protocol path")
    protocol = load_strict_json(canonical_protocol)
    _validate_protocol(protocol, repo_root=root)
    builder_path = Path(__file__).resolve()
    if protocol.get("builder_sha256") != sha256_file(builder_path):
        raise SnapshotBuildError("builder source differs from committed protocol")
    expected = expected_vendor_entries()
    if protocol.get("vendor_file_count") != len(expected):
        raise SnapshotBuildError("vendor file count drifted")
    output = _canonical_path(root, CANONICAL_VENDOR_LOCK_RELATIVE)
    if output.exists() or output.is_symlink():
        raise FileExistsError(f"vendor lock already exists: {output}")
    source_preflight = _source_identity(root, include_vendor_lock=False)
    if not source_preflight["git"]["clean"]:
        raise SnapshotBuildError(f"pin requires a clean repo: {source_preflight['git']['status']}")
    _assert_phase_1_commit_identity(
        root,
        str(source_preflight["git"]["commit"]),
        source_preflight["file_sha256"],
    )

    def pin_one(entry: Mapping[str, str]) -> dict[str, Any]:
        retrieved_at = datetime.now(UTC).isoformat()
        body, headers, attempts, final_url = _http_get(
            entry["checksum_url"], max_bytes=MAX_CHECKSUM_RESPONSE_BYTES
        )
        vendor_sha = parse_vendor_checksum(body, expected_filename=entry["filename"])
        return {
            **dict(entry),
            "vendor_sha256": vendor_sha,
            "checksum_text": body.decode("ascii"),
            "checksum_body_sha256": sha256_bytes(body),
            "checksum_body_bytes": len(body),
            "retrieved_at_utc": retrieved_at,
            "http_attempts": attempts,
            "final_url": final_url,
            "response_headers": headers,
        }

    pinned: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=DOWNLOAD_WORKERS) as executor:
        futures = {executor.submit(pin_one, entry): entry for entry in expected}
        for future in as_completed(futures):
            pinned.append(future.result())
    order = {(entry["symbol"], entry["month"]): index for index, entry in enumerate(expected)}
    pinned.sort(key=lambda item: order[(item["symbol"], item["month"])])
    if len(pinned) != len(expected):
        raise SnapshotBuildError("vendor checksum pin count drifted")
    source_postflight = _source_identity(root, include_vendor_lock=False)
    if source_postflight != source_preflight:
        raise SnapshotBuildError(
            "pin source/runtime/git identity changed during checksum retrieval"
        )

    payload = {
        "schema_version": VENDOR_LOCK_SCHEMA,
        "source_kind": SOURCE_KIND,
        "protocol_path": CANONICAL_PROTOCOL_RELATIVE,
        "protocol_sha256": sha256_file(canonical_protocol),
        "builder_path": str(builder_path.relative_to(root)),
        "builder_sha256": sha256_file(builder_path),
        "builder_test_path": CANONICAL_TEST_RELATIVE,
        "builder_test_sha256": sha256_file(_canonical_path(root, CANONICAL_TEST_RELATIVE)),
        "source_preflight": source_preflight,
        "source_postflight": source_postflight,
        "entry_count": len(pinned),
        "ordered_by": ["SYMBOLS_declared_order", "month_ascending"],
        "entries": pinned,
        "governance": {
            "kline_zip_downloaded_by_pin_phase": False,
            "kline_csv_opened_by_pin_phase": False,
            "strategy_or_performance_code_imported": False,
            "exchange_account_or_credentials_used": False,
        },
    }
    payload_bytes = canonical_json(payload)
    source_publish_boundary = _source_identity(root, include_vendor_lock=False)
    if source_publish_boundary != source_postflight:
        raise SnapshotBuildError("pin source identity changed before vendor-lock publication")
    write_bytes_no_overwrite(output, payload_bytes)
    return payload


def _validate_vendor_lock(
    vendor_lock: Mapping[str, Any],
    *,
    protocol_sha256: str,
    repo_root: Path,
) -> list[dict[str, Any]]:
    expected_top_level = {
        "schema_version",
        "source_kind",
        "protocol_path",
        "protocol_sha256",
        "builder_path",
        "builder_sha256",
        "builder_test_path",
        "builder_test_sha256",
        "source_preflight",
        "source_postflight",
        "entry_count",
        "ordered_by",
        "entries",
        "governance",
    }
    if set(vendor_lock) != expected_top_level:
        raise SnapshotBuildError("vendor lock top-level fields drifted")
    builder_path = str(Path(__file__).resolve().relative_to(repo_root.resolve()))
    test_hash = sha256_file(_canonical_path(repo_root, CANONICAL_TEST_RELATIVE))
    builder_hash = sha256_file(Path(__file__).resolve())
    expected_scalars = {
        "schema_version": VENDOR_LOCK_SCHEMA,
        "source_kind": SOURCE_KIND,
        "protocol_path": CANONICAL_PROTOCOL_RELATIVE,
        "protocol_sha256": protocol_sha256,
        "builder_path": builder_path,
        "builder_sha256": builder_hash,
        "builder_test_path": CANONICAL_TEST_RELATIVE,
        "builder_test_sha256": test_hash,
        "entry_count": len(expected_vendor_entries()),
        "ordered_by": ["SYMBOLS_declared_order", "month_ascending"],
    }
    if any(vendor_lock.get(key) != value for key, value in expected_scalars.items()):
        raise SnapshotBuildError("vendor lock scalar identity drifted")
    expected_governance = {
        "kline_zip_downloaded_by_pin_phase": False,
        "kline_csv_opened_by_pin_phase": False,
        "strategy_or_performance_code_imported": False,
        "exchange_account_or_credentials_used": False,
    }
    if vendor_lock.get("governance") != expected_governance:
        raise SnapshotBuildError("vendor lock governance drifted")
    source_preflight = vendor_lock.get("source_preflight")
    source_postflight = vendor_lock.get("source_postflight")
    if not isinstance(source_preflight, dict) or source_postflight != source_preflight:
        raise SnapshotBuildError("vendor-lock pin source pre/post identity drifted")
    git = source_preflight.get("git")
    hashes = source_preflight.get("file_sha256")
    if (
        not isinstance(git, dict)
        or set(git) != {"commit", "clean", "status"}
        or not re.fullmatch(r"[0-9a-f]{40}", str(git.get("commit", "")))
        or git.get("clean") is not True
        or git.get("status") != []
        or not isinstance(hashes, dict)
        or hashes
        != {
            CANONICAL_PROTOCOL_RELATIVE: protocol_sha256,
            builder_path: builder_hash,
            CANONICAL_TEST_RELATIVE: test_hash,
        }
        or source_preflight.get("runtime_versions") != _runtime_versions()
    ):
        raise SnapshotBuildError("vendor-lock pin source provenance is invalid")
    _assert_phase_1_commit_identity(repo_root, str(git["commit"]), hashes)

    entries = vendor_lock.get("entries")
    expected_entries = expected_vendor_entries()
    if not isinstance(entries, list) or len(entries) != len(expected_entries):
        raise SnapshotBuildError("vendor lock entry count drifted")
    expected_entry_fields = {
        "symbol",
        "canonical_symbol",
        "month",
        "filename",
        "zip_url",
        "checksum_url",
        "vendor_sha256",
        "checksum_text",
        "checksum_body_sha256",
        "checksum_body_bytes",
        "retrieved_at_utc",
        "http_attempts",
        "final_url",
        "response_headers",
    }
    validated: list[dict[str, Any]] = []
    for expected, raw in zip(expected_entries, entries, strict=True):
        if not isinstance(raw, dict) or set(raw) != expected_entry_fields:
            raise SnapshotBuildError("vendor lock entry fields drifted")
        if any(raw.get(key) != value for key, value in expected.items()):
            raise SnapshotBuildError("vendor lock ordered URL identity drifted")
        vendor_sha = str(raw.get("vendor_sha256", "")).lower()
        checksum_text = raw.get("checksum_text")
        if (
            not _SHA256.fullmatch(vendor_sha)
            or not isinstance(checksum_text, str)
            or parse_vendor_checksum(
                checksum_text.encode("ascii"), expected_filename=expected["filename"]
            )
            != vendor_sha
            or sha256_bytes(checksum_text.encode("ascii")) != raw.get("checksum_body_sha256")
            or raw.get("checksum_body_bytes") != len(checksum_text.encode("ascii"))
            or not 0 < raw["checksum_body_bytes"] <= MAX_CHECKSUM_RESPONSE_BYTES
            or not isinstance(raw.get("http_attempts"), int)
            or not 1 <= raw["http_attempts"] <= HTTP_RETRIES
            or raw.get("final_url") != expected["checksum_url"]
        ):
            raise SnapshotBuildError("vendor checksum sidecar provenance drifted")
        try:
            retrieved = datetime.fromisoformat(str(raw.get("retrieved_at_utc")))
        except ValueError as exc:
            raise SnapshotBuildError("vendor retrieval timestamp is invalid") from exc
        if retrieved.tzinfo is None or retrieved.utcoffset() != UTC.utcoffset(retrieved):
            raise SnapshotBuildError("vendor retrieval timestamp must be UTC")
        headers = raw.get("response_headers")
        if (
            not isinstance(headers, dict)
            or not set(headers).issubset(
                {"content-length", "last-modified", "etag", "content-type"}
            )
            or any(
                not isinstance(key, str) or not isinstance(value, str)
                for key, value in headers.items()
            )
        ):
            raise SnapshotBuildError("vendor checksum response headers are invalid")
        validated.append(raw)
    return validated


def _month_bounds(month: str) -> tuple[int, int, int]:
    year, number = map(int, month.split("-"))
    days = calendar.monthrange(year, number)[1]
    start = datetime(year, number, 1, tzinfo=UTC)
    if number == 12:
        end = datetime(year + 1, 1, 1, tzinfo=UTC)
    else:
        end = datetime(year, number + 1, 1, tzinfo=UTC)
    return int(start.timestamp() * 1000), int(end.timestamp() * 1000), days * 96


def parse_monthly_archive(
    archive: bytes | Path,
    *,
    symbol: str,
    month: str,
    expected_filename: str,
) -> tuple[tuple[tuple[Any, ...], ...], dict[str, Any]]:
    if isinstance(archive, Path):
        source: Any = archive
    else:
        source = io.BytesIO(archive)
    expected_member = expected_filename[:-4] + ".csv"
    start_ms, end_ms, expected_rows = _month_bounds(month)
    rows: list[tuple[Any, ...]] = []
    with zipfile.ZipFile(source) as zipped:
        members = [info for info in zipped.infolist() if not info.is_dir()]
        if len(members) != 1 or members[0].filename != expected_member:
            raise SnapshotBuildError(
                f"ZIP member drift for {expected_filename}: {[item.filename for item in members]}"
            )
        member = members[0]
        compression_ratio = member.file_size / max(member.compress_size, 1)
        if (
            member.flag_bits & 0x1
            or member.file_size <= 0
            or member.file_size > MAX_ZIP_MEMBER_BYTES
            or compression_ratio > MAX_ZIP_COMPRESSION_RATIO
        ):
            raise SnapshotBuildError(f"unsafe ZIP resource profile: {expected_filename}")
        if zipped.testzip() is not None:
            raise SnapshotBuildError(f"ZIP CRC failed: {expected_filename}")
        header_seen = False
        with zipped.open(member, "r") as binary:
            reader = csv.reader(io.TextIOWrapper(binary, encoding="utf-8", newline=""))
            for line_number, record in enumerate(reader, start=1):
                if not record:
                    raise SnapshotBuildError(
                        f"blank CSV record at line {line_number}: {expected_filename}"
                    )
                if not record[0].isdigit():
                    if (
                        line_number == 1
                        and not header_seen
                        and tuple(record) == CANONICAL_CSV_HEADER
                    ):
                        header_seen = True
                        continue
                    raise SnapshotBuildError(
                        f"non-canonical CSV header/preamble at line {line_number}: "
                        f"{expected_filename}"
                    )
                if len(record) != 12:
                    raise SnapshotBuildError(
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
                    raise SnapshotBuildError(
                        f"invalid numeric CSV row: {expected_filename}"
                    ) from exc
                values = (
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
                    not all(math.isfinite(value) for value in values)
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
                    raise SnapshotBuildError(f"invalid OHLCV geometry: {expected_filename}")
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
                if len(rows) > expected_rows:
                    raise SnapshotBuildError(
                        f"monthly row count exceeds calendar bound: {expected_filename}"
                    )
    timestamps = [int(row[3].timestamp() * 1000) for row in rows]
    expected_timestamps = list(range(start_ms, end_ms, BAR_MS))
    if timestamps != expected_timestamps or len(rows) != expected_rows:
        raise SnapshotBuildError(
            f"monthly grid is incomplete for {symbol} {month}: "
            f"rows={len(rows)}, expected={expected_rows}"
        )
    return tuple(rows), {
        "rows": len(rows),
        "first_ts": datetime.fromtimestamp(start_ms / 1000, tz=UTC).isoformat(),
        "last_ts": datetime.fromtimestamp((end_ms - BAR_MS) / 1000, tz=UTC).isoformat(),
        "member": expected_member,
    }


def _validate_cache_filename(*, symbol: str, filename: str) -> None:
    if (
        symbol not in SYMBOLS
        or Path(filename).name != filename
        or "/" in filename
        or "\\" in filename
        or not filename.startswith(f"{symbol}-{TIMEFRAME}-")
        or not filename.endswith(".zip")
    ):
        raise SnapshotBuildError("unsafe vendor cache identity")


def _directory_open_flags() -> int:
    _require_secure_dirfd_primitives()
    return os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC


def _require_secure_dirfd_primitives() -> None:
    required_flags = ("O_DIRECTORY", "O_NOFOLLOW", "O_NONBLOCK", "O_CLOEXEC")
    missing_flags = [name for name in required_flags if not hasattr(os, name)]
    supported_dir_fd_names = {function.__name__ for function in os.supports_dir_fd}
    missing_dir_fd = sorted(
        {"open", "mkdir", "stat", "link", "unlink", "rmdir"} - supported_dir_fd_names
    )
    if missing_flags or missing_dir_fd or not hasattr(os, "fchdir"):
        raise SnapshotBuildError(
            f"secure dir-fd primitives unavailable: flags={missing_flags}, dir_fd={missing_dir_fd}"
        )


def _open_directory_tree_no_symlinks(
    root: Path,
    relative: str,
    *,
    create: bool,
) -> int:
    relative_path = Path(relative)
    if relative_path.is_absolute() or not relative_path.parts or ".." in relative_path.parts:
        raise SnapshotBuildError(f"unsafe directory-tree identity: {relative}")
    descriptor: int | None = None
    try:
        descriptor = os.open(root, _directory_open_flags())
        for component in relative_path.parts:
            if component in {"", "."}:
                raise SnapshotBuildError(f"unsafe directory-tree component: {relative}")
            if create:
                with contextlib.suppress(FileExistsError):
                    os.mkdir(component, mode=0o700, dir_fd=descriptor)
            next_descriptor = os.open(
                component,
                _directory_open_flags(),
                dir_fd=descriptor,
            )
            if not stat.S_ISDIR(os.fstat(next_descriptor).st_mode):
                os.close(next_descriptor)
                raise SnapshotBuildError(
                    f"directory-tree component is not a directory: {component}"
                )
            os.close(descriptor)
            descriptor = next_descriptor
        return descriptor
    except SnapshotBuildError:
        if descriptor is not None:
            os.close(descriptor)
        raise
    except OSError as exc:
        if descriptor is not None:
            os.close(descriptor)
        raise SnapshotBuildError(f"cannot safely open directory tree: {relative}") from exc


def _open_cache_directory(cache_root: Path) -> int:
    try:
        descriptor = os.open(cache_root, _directory_open_flags())
    except OSError as exc:
        raise SnapshotBuildError(f"cannot safely open vendor cache root: {cache_root}") from exc
    info = os.fstat(descriptor)
    if not stat.S_ISDIR(info.st_mode):
        os.close(descriptor)
        raise SnapshotBuildError(f"vendor cache root is not a directory: {cache_root}")
    return descriptor


def _archive_read_flags() -> int:
    _require_secure_dirfd_primitives()
    return os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC


def _read_verified_archive_at(
    cache_dir_fd: int,
    filename: str,
    *,
    expected_sha256: str,
) -> bytes:
    if Path(filename).name != filename or "/" in filename or "\\" in filename:
        raise SnapshotBuildError("unsafe cached archive filename")
    flags = _archive_read_flags()
    try:
        descriptor = os.open(filename, flags, dir_fd=cache_dir_fd)
    except FileNotFoundError:
        raise
    except OSError as exc:
        raise SnapshotBuildError(f"cannot safely open cached archive: {filename}") from exc
    try:
        info = os.fstat(descriptor)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_size <= 0
            or info.st_size > MAX_ZIP_RESPONSE_BYTES
        ):
            raise SnapshotBuildError(f"unsafe cached archive file profile: {filename}")
        chunks: list[bytes] = []
        observed = 0
        while True:
            chunk = os.read(descriptor, min(1024 * 1024, MAX_ZIP_RESPONSE_BYTES - observed + 1))
            if not chunk:
                break
            observed += len(chunk)
            if observed > MAX_ZIP_RESPONSE_BYTES:
                raise SnapshotBuildError(f"cached archive exceeds byte cap: {filename}")
            chunks.append(chunk)
    finally:
        os.close(descriptor)
    body = b"".join(chunks)
    actual = sha256_bytes(body)
    if actual != expected_sha256:
        raise SnapshotBuildError(f"cached vendor archive hash drifted: {filename}")
    return body


def _write_cache_archive_at(cache_dir_fd: int, filename: str, body: bytes) -> None:
    if Path(filename).name != filename or "/" in filename or "\\" in filename:
        raise SnapshotBuildError("unsafe cached archive filename")
    _require_secure_dirfd_primitives()
    temporary_name = f".{filename}.{secrets.token_hex(16)}.tmp"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC
    descriptor: int | None = None
    created = False
    try:
        descriptor = os.open(temporary_name, flags, 0o600, dir_fd=cache_dir_fd)
        created = True
        view = memoryview(body)
        written = 0
        while written < len(view):
            count = os.write(descriptor, view[written:])
            if count <= 0:
                raise SnapshotBuildError(f"short write to vendor cache: {filename}")
            written += count
        os.fsync(descriptor)
        os.link(
            temporary_name,
            filename,
            src_dir_fd=cache_dir_fd,
            dst_dir_fd=cache_dir_fd,
            follow_symlinks=False,
        )
        os.unlink(temporary_name, dir_fd=cache_dir_fd)
        created = False
        os.fsync(cache_dir_fd)
    except BaseException:
        if descriptor is not None:
            os.close(descriptor)
            descriptor = None
        if created:
            with contextlib.suppress(OSError):
                os.unlink(temporary_name, dir_fd=cache_dir_fd)
            with contextlib.suppress(OSError):
                os.fsync(cache_dir_fd)
        raise
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _download_archive(
    entry: Mapping[str, Any],
    *,
    cache_root: Path,
    cache_dir_fd: int,
) -> tuple[str, dict[str, Any]]:
    symbol = str(entry["symbol"])
    filename = str(entry["filename"])
    _validate_cache_filename(symbol=symbol, filename=filename)
    expected_sha = str(entry.get("vendor_sha256", "")).lower()
    if not _SHA256.fullmatch(expected_sha):
        raise SnapshotBuildError("vendor lock entry has invalid SHA-256")
    try:
        body = _read_verified_archive_at(
            cache_dir_fd,
            filename,
            expected_sha256=expected_sha,
        )
    except FileNotFoundError:
        pass
    else:
        return filename, {
            "source": "VERIFIED_EXISTING_CACHE",
            "cache_logical_root": str(cache_root),
            "cache_filename": filename,
            "cache_directory_fd_bound": True,
            "bytes": len(body),
            "sha256": expected_sha,
            "http_attempts": 0,
            "final_url": None,
            "response_headers": {},
            "retrieved_at_utc": None,
        }

    body, headers, attempts, final_url = _http_get(
        str(entry["zip_url"]), max_bytes=MAX_ZIP_RESPONSE_BYTES
    )
    actual = sha256_bytes(body)
    if actual != expected_sha:
        raise SnapshotBuildError(
            f"vendor ZIP checksum mismatch for {entry['filename']}: {actual} != {expected_sha}"
        )
    _write_cache_archive_at(cache_dir_fd, filename, body)
    _read_verified_archive_at(cache_dir_fd, filename, expected_sha256=expected_sha)
    return filename, {
        "source": "DOWNLOADED_AND_VENDOR_CHECKSUM_VERIFIED",
        "cache_logical_root": str(cache_root),
        "cache_filename": filename,
        "cache_directory_fd_bound": True,
        "bytes": len(body),
        "sha256": actual,
        "http_attempts": attempts,
        "final_url": final_url,
        "response_headers": headers,
        "retrieved_at_utc": datetime.now(UTC).isoformat(),
    }


def _create_snapshot_db(path: Path, metadata: Mapping[str, str]) -> duckdb.DuckDBPyConnection:
    connection = duckdb.connect(str(path))
    connection.execute("SET TimeZone='UTC'")
    connection.execute(
        """
        CREATE TABLE ohlcv (
            venue VARCHAR NOT NULL,
            symbol VARCHAR NOT NULL,
            timeframe VARCHAR NOT NULL,
            ts TIMESTAMPTZ NOT NULL,
            open DOUBLE NOT NULL,
            high DOUBLE NOT NULL,
            low DOUBLE NOT NULL,
            close DOUBLE NOT NULL,
            volume DOUBLE NOT NULL,
            PRIMARY KEY (venue, symbol, timeframe, ts)
        )
        """
    )
    connection.execute("CREATE TABLE snapshot_metadata (key VARCHAR PRIMARY KEY, value VARCHAR)")
    connection.executemany("INSERT INTO snapshot_metadata VALUES (?, ?)", sorted(metadata.items()))
    return connection


def _reserve_duckdb_path(directory: Path, *, output_name: str) -> Path:
    """Reserve a random build name, then leave it absent for DuckDB creation."""

    with tempfile.NamedTemporaryFile(
        dir=directory,
        prefix=f".{output_name}.",
        suffix=".building",
        delete=False,
    ) as handle:
        path = Path(handle.name)
    # DuckDB refuses to initialize an already-existing zero-byte file.
    path.unlink()
    return path


def _row_content_hash(connection: duckdb.DuckDBPyConnection, symbol: str) -> str:
    digest = hashlib.sha256()
    cursor = connection.execute(
        """
        SELECT ts, open, high, low, close, volume
        FROM ohlcv WHERE venue='binance' AND symbol=? AND timeframe='15m'
        ORDER BY ts
        """,
        [symbol],
    )
    while batch := cursor.fetchmany(10_000):
        for ts, open_, high, low, close, volume in batch:
            stamp = ts.astimezone(UTC).isoformat().replace("+00:00", "Z")
            line = json.dumps(
                [stamp, open_, high, low, close, volume],
                separators=(",", ":"),
                allow_nan=False,
            )
            digest.update(line.encode())
            digest.update(b"\n")
    return digest.hexdigest()


def _actual_key_sha256(connection: duckdb.DuckDBPyConnection) -> str:
    digest = hashlib.sha256()
    for raw_symbol in SYMBOLS:
        symbol = SYMBOL_TO_CANONICAL[raw_symbol]
        cursor = connection.execute(
            """
            SELECT epoch_ms(ts) FROM ohlcv
            WHERE venue='binance' AND symbol=? AND timeframe='15m'
            ORDER BY ts
            """,
            [symbol],
        )
        while batch := cursor.fetchmany(20_000):
            for (timestamp_ms,) in batch:
                digest.update(f"binance|{symbol}|15m|{int(timestamp_ms)}\n".encode())
    return digest.hexdigest()


def _validate_snapshot_db(connection: duckdb.DuckDBPyConnection) -> dict[str, Any]:
    total, distinct_keys = connection.execute(
        "SELECT COUNT(*), COUNT(DISTINCT (venue, symbol, timeframe, ts)) FROM ohlcv"
    ).fetchone()
    if total != TOTAL_ROWS or distinct_keys != TOTAL_ROWS:
        raise SnapshotBuildError(
            f"snapshot row/key count drift: total={total}, distinct={distinct_keys}"
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
        raise SnapshotBuildError(f"snapshot contains {invalid} invalid OHLCV rows")

    expected_first = HISTORY_START
    expected_last = datetime.fromtimestamp(
        (int(EVALUATION_END.timestamp() * 1000) - BAR_MS) / 1000,
        tz=UTC,
    )
    per_symbol: dict[str, Any] = {}
    for raw_symbol in SYMBOLS:
        symbol = SYMBOL_TO_CANONICAL[raw_symbol]
        count, first_ts, last_ts = connection.execute(
            """
            SELECT COUNT(*), MIN(ts), MAX(ts) FROM ohlcv
            WHERE venue='binance' AND symbol=? AND timeframe='15m'
            """,
            [symbol],
        ).fetchone()
        if count != ROWS_PER_SYMBOL or first_ts != expected_first or last_ts != expected_last:
            raise SnapshotBuildError(
                f"{symbol}: range/count drift count={count}, first={first_ts}, last={last_ts}"
            )
        gaps = connection.execute(
            """
            WITH ordered AS (
                SELECT ts, lag(ts) OVER (ORDER BY ts) AS previous
                FROM ohlcv WHERE venue='binance' AND symbol=? AND timeframe='15m'
            )
            SELECT COUNT(*) FROM ordered
            WHERE previous IS NOT NULL AND ts - previous <> INTERVAL '15 minutes'
            """,
            [symbol],
        ).fetchone()[0]
        if gaps:
            raise SnapshotBuildError(f"{symbol}: snapshot contains {gaps} timestamp gaps")
        incomplete_days = connection.execute(
            """
            SELECT COUNT(*) FROM (
                SELECT date_trunc('day', ts) AS day, COUNT(*) AS bars
                FROM ohlcv WHERE venue='binance' AND symbol=? AND timeframe='15m'
                GROUP BY day HAVING COUNT(*) <> 96
            )
            """,
            [symbol],
        ).fetchone()[0]
        # The first calendar day starts at 00:00 by contract, so every day is full.
        if incomplete_days:
            raise SnapshotBuildError(f"{symbol}: {incomplete_days} UTC days are incomplete")
        per_symbol[symbol] = {
            "rows": count,
            "first_ts": first_ts.astimezone(UTC).isoformat(),
            "last_ts": last_ts.astimezone(UTC).isoformat(),
            "gap_count": 0,
            "incomplete_utc_day_count": 0,
            "content_sha256": _row_content_hash(connection, symbol),
        }
    actual_key_hash = _actual_key_sha256(connection)
    if actual_key_hash != expected_key_sha256():
        raise SnapshotBuildError("snapshot actual key hash differs from the frozen expected grid")
    return {
        "total_rows": total,
        "distinct_primary_keys": distinct_keys,
        "actual_key_sha256": actual_key_hash,
        "expected_key_sha256": expected_key_sha256(),
        "invalid_ohlcv_rows": 0,
        "per_symbol": per_symbol,
    }


def _fsync_directory(path: Path) -> None:
    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    descriptor = os.open(path, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _assert_build_source_postflight(
    preflight: Mapping[str, Any],
    postflight: Mapping[str, Any],
    *,
    reservation_relative: str,
) -> None:
    if postflight.get("file_sha256") != preflight.get("file_sha256") or postflight.get(
        "runtime_versions"
    ) != preflight.get("runtime_versions"):
        raise SnapshotBuildError("build source/runtime identity changed during execution")
    pre_git = preflight.get("git")
    post_git = postflight.get("git")
    if not isinstance(pre_git, dict) or not isinstance(post_git, dict):
        raise SnapshotBuildError("build git provenance is malformed")
    if (
        pre_git.get("clean") is not True
        or pre_git.get("status") != []
        or post_git.get("commit") != pre_git.get("commit")
        or post_git.get("clean") is not False
        or post_git.get("status") != [f"?? {reservation_relative}"]
    ):
        raise SnapshotBuildError("build git/source postflight differs beyond reservation")


def _assert_json_identity(path: Path, expected: Mapping[str, Any], expected_sha256: str) -> None:
    _require_secure_dirfd_primitives()
    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise SnapshotBuildError(f"cannot safely open immutable JSON: {path}") from exc
    try:
        info = os.fstat(descriptor)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_size <= 0
            or info.st_size > MAX_IDENTITY_JSON_BYTES
        ):
            raise SnapshotBuildError(f"unsafe immutable JSON file profile: {path}")
        chunks: list[bytes] = []
        observed = 0
        while True:
            chunk = os.read(
                descriptor,
                min(1024 * 1024, MAX_IDENTITY_JSON_BYTES - observed + 1),
            )
            if not chunk:
                break
            observed += len(chunk)
            if observed > MAX_IDENTITY_JSON_BYTES:
                raise SnapshotBuildError(f"immutable JSON exceeds byte cap: {path}")
            chunks.append(chunk)
    finally:
        os.close(descriptor)
    body = b"".join(chunks)
    if body != canonical_json(dict(expected)) or sha256_bytes(body) != expected_sha256:
        raise SnapshotBuildError(f"immutable JSON identity changed during execution: {path}")


def _read_only_post_close_qa(path: Path) -> dict[str, Any]:
    connection = duckdb.connect(str(path), read_only=True)
    try:
        connection.execute("SET TimeZone='UTC'")
        return _validate_snapshot_db(connection)
    finally:
        connection.close()


def _rename_exclusive_at(parent_dir_fd: int, source_name: str, destination_name: str) -> None:
    if (
        Path(source_name).name != source_name
        or Path(destination_name).name != destination_name
        or source_name in {"", ".", ".."}
        or destination_name in {"", ".", ".."}
    ):
        raise SnapshotBuildError("unsafe atomic-rename identity")
    libc = ctypes.CDLL(None, use_errno=True)
    source = os.fsencode(source_name)
    destination = os.fsencode(destination_name)
    if os.uname().sysname == "Darwin" and hasattr(libc, "renameatx_np"):
        function = libc.renameatx_np
        function.argtypes = [
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        ]
        function.restype = ctypes.c_int
        flags = 0x04 | 0x10  # RENAME_EXCL | RENAME_NOFOLLOW_ANY
    elif hasattr(libc, "renameat2"):
        function = libc.renameat2
        function.argtypes = [
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        ]
        function.restype = ctypes.c_int
        flags = 0x01  # Linux RENAME_NOREPLACE
    else:
        raise SnapshotBuildError("exclusive atomic rename primitive is unavailable")
    ctypes.set_errno(0)
    result = function(parent_dir_fd, source, parent_dir_fd, destination, flags)
    if result == 0:
        return
    error_number = ctypes.get_errno()
    if error_number in {errno.EEXIST, errno.ENOTEMPTY}:
        raise FileExistsError(
            error_number,
            f"immutable bundle target already exists: {destination_name}",
        )
    raise SnapshotBuildError(f"exclusive atomic bundle rename failed: {os.strerror(error_number)}")


def _assert_directory_tree_matches_fd(
    root: Path,
    relative: str,
    retained_dir_fd: int,
) -> None:
    current_dir_fd = _open_directory_tree_no_symlinks(root, relative, create=False)
    try:
        retained_info = os.fstat(retained_dir_fd)
        current_info = os.fstat(current_dir_fd)
        if (
            not stat.S_ISDIR(retained_info.st_mode)
            or not stat.S_ISDIR(current_info.st_mode)
            or (retained_info.st_dev, retained_info.st_ino)
            != (current_info.st_dev, current_info.st_ino)
        ):
            raise SnapshotBuildError("directory path no longer matches retained inode")
    finally:
        os.close(current_dir_fd)


def _publish_bundle_atomic(
    staging_bundle: Path,
    final_bundle: Path,
    *,
    parent_dir_fd: int | None = None,
    staging_dir_fd: int | None = None,
    identity_root: Path | None = None,
    identity_relative: str | None = None,
) -> None:
    if staging_bundle.parent != final_bundle.parent:
        raise SnapshotBuildError("staging and final bundles must share one parent")
    close_parent = parent_dir_fd is None
    if parent_dir_fd is None:
        parent_dir_fd = _open_cache_directory(staging_bundle.parent)
    close_staging = staging_dir_fd is None
    renamed = False
    retained_staging_info: os.stat_result | None = None
    try:
        if (identity_root is None) != (identity_relative is None):
            raise SnapshotBuildError("publication parent identity contract is incomplete")
        if identity_root is not None and identity_relative is not None:
            _assert_directory_tree_matches_fd(
                identity_root,
                identity_relative,
                parent_dir_fd,
            )
        try:
            os.stat(final_bundle.name, dir_fd=parent_dir_fd, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            raise FileExistsError(f"immutable bundle target already exists: {final_bundle}")
        if staging_dir_fd is None:
            staging_dir_fd = os.open(
                staging_bundle.name,
                _directory_open_flags(),
                dir_fd=parent_dir_fd,
            )
        retained_staging_info = os.fstat(staging_dir_fd)
        if not stat.S_ISDIR(retained_staging_info.st_mode):
            raise SnapshotBuildError("retained staging bundle is not a real directory")
        source_info = os.stat(
            staging_bundle.name,
            dir_fd=parent_dir_fd,
            follow_symlinks=False,
        )
        if not stat.S_ISDIR(source_info.st_mode) or (source_info.st_dev, source_info.st_ino) != (
            retained_staging_info.st_dev,
            retained_staging_info.st_ino,
        ):
            raise SnapshotBuildError("staging bundle path no longer matches retained inode")
        _rename_exclusive_at(parent_dir_fd, staging_bundle.name, final_bundle.name)
        renamed = True
        published_info = os.stat(
            final_bundle.name,
            dir_fd=parent_dir_fd,
            follow_symlinks=False,
        )
        if not stat.S_ISDIR(published_info.st_mode) or (
            published_info.st_dev,
            published_info.st_ino,
        ) != (retained_staging_info.st_dev, retained_staging_info.st_ino):
            raise SnapshotBuildError("published bundle no longer matches retained staging inode")
        if identity_root is not None and identity_relative is not None:
            _assert_directory_tree_matches_fd(
                identity_root,
                identity_relative,
                parent_dir_fd,
            )
        os.fsync(parent_dir_fd)
    except BaseException as exc:
        if not renamed or retained_staging_info is None:
            raise
        try:
            current_final_info = os.stat(
                final_bundle.name,
                dir_fd=parent_dir_fd,
                follow_symlinks=False,
            )
        except OSError:
            publication_state = "FINAL_VISIBILITY_UNKNOWN_AFTER_ATOMIC_RENAME"
        else:
            if stat.S_ISDIR(current_final_info.st_mode) and (
                current_final_info.st_dev,
                current_final_info.st_ino,
            ) == (retained_staging_info.st_dev, retained_staging_info.st_ino):
                publication_state = "VISIBLE_RETAINED_INODE_DURABILITY_UNCONFIRMED"
            else:
                publication_state = "RETAINED_INODE_NOT_VISIBLE_AT_FINAL_NAME"
        raise BundlePublicationError(
            f"post-rename bundle publication did not complete: {type(exc).__name__}: {exc}",
            publication_state=publication_state,
        ) from exc
    finally:
        if close_staging and staging_dir_fd is not None:
            os.close(staging_dir_fd)
        if close_parent:
            os.close(parent_dir_fd)


def _create_staging_directory_at(parent_dir_fd: int, *, final_name: str) -> tuple[str, int]:
    _require_secure_dirfd_primitives()
    for _attempt in range(100):
        name = f".{final_name}.{secrets.token_hex(16)}.building"
        try:
            os.mkdir(name, mode=0o700, dir_fd=parent_dir_fd)
        except FileExistsError:
            continue
        try:
            descriptor = os.open(name, _directory_open_flags(), dir_fd=parent_dir_fd)
        except BaseException:
            with contextlib.suppress(OSError):
                os.rmdir(name, dir_fd=parent_dir_fd)
            raise
        if not stat.S_ISDIR(os.fstat(descriptor).st_mode):
            os.close(descriptor)
            raise SnapshotBuildError("staging bundle is not a real directory")
        try:
            os.fsync(parent_dir_fd)
        except BaseException:
            os.close(descriptor)
            with contextlib.suppress(OSError):
                os.rmdir(name, dir_fd=parent_dir_fd)
            raise
        return name, descriptor
    raise SnapshotBuildError("cannot reserve a unique staging-bundle identity")


@contextlib.contextmanager
def _working_directory_fd(directory_fd: int) -> Iterator[None]:
    original_fd = os.open(".", _directory_open_flags())
    try:
        os.fchdir(directory_fd)
        yield
    finally:
        try:
            os.fchdir(original_fd)
        finally:
            os.close(original_fd)


def _remove_staging_directory_at(
    parent_dir_fd: int,
    staging_dir_fd: int,
    staging_name: str,
) -> None:
    retained_info = os.fstat(staging_dir_fd)
    named_info = os.stat(
        staging_name,
        dir_fd=parent_dir_fd,
        follow_symlinks=False,
    )
    if (
        not stat.S_ISDIR(retained_info.st_mode)
        or not stat.S_ISDIR(named_info.st_mode)
        or (retained_info.st_dev, retained_info.st_ino) != (named_info.st_dev, named_info.st_ino)
    ):
        raise SnapshotBuildError("staging cleanup name no longer matches retained inode")
    for name in os.listdir(staging_dir_fd):
        if Path(name).name != name or name in {"", ".", ".."}:
            raise SnapshotBuildError("unsafe staging cleanup identity")
        info = os.stat(name, dir_fd=staging_dir_fd, follow_symlinks=False)
        if stat.S_ISDIR(info.st_mode):
            raise SnapshotBuildError("unexpected directory inside staging bundle")
        os.unlink(name, dir_fd=staging_dir_fd)
    os.fsync(staging_dir_fd)
    os.rmdir(staging_name, dir_fd=parent_dir_fd)
    os.fsync(parent_dir_fd)


def build_snapshot(
    protocol_path: Path,
    vendor_lock_path: Path,
    *,
    repo_root: Path,
) -> dict[str, Any]:
    root = repo_root.resolve()
    canonical_protocol = _canonical_path(root, CANONICAL_PROTOCOL_RELATIVE)
    canonical_lock = _canonical_path(root, CANONICAL_VENDOR_LOCK_RELATIVE)
    if (
        protocol_path.resolve() != canonical_protocol
        or vendor_lock_path.resolve() != canonical_lock
    ):
        raise SnapshotBuildError("build requires canonical protocol and vendor lock paths")
    protocol = load_strict_json(canonical_protocol)
    vendor_lock = load_strict_json(canonical_lock)
    _validate_protocol(protocol, repo_root=root)
    builder_path = Path(__file__).resolve()
    builder_hash = sha256_file(builder_path)
    protocol_hash = sha256_file(canonical_protocol)
    lock_hash = sha256_file(canonical_lock)
    test_hash = sha256_file(_canonical_path(root, CANONICAL_TEST_RELATIVE))
    entries = _validate_vendor_lock(
        vendor_lock,
        protocol_sha256=protocol_hash,
        repo_root=root,
    )
    source_preflight = _source_identity(root, include_vendor_lock=True)
    if not source_preflight["git"]["clean"]:
        raise SnapshotBuildError(
            f"build requires a clean repo: {source_preflight['git']['status']}"
        )
    _assert_commit_file_identity(
        root,
        str(source_preflight["git"]["commit"]),
        source_preflight["file_sha256"],
    )

    bundle = _canonical_path(root, CANONICAL_BUNDLE_RELATIVE)
    cache = _canonical_path(root, CANONICAL_CACHE_RELATIVE)
    reservation_path = _canonical_path(root, CANONICAL_RESERVATION_RELATIVE)
    failure_evidence_path = _canonical_path(root, CANONICAL_FAILURE_EVIDENCE_RELATIVE)
    for protected in (bundle, reservation_path, failure_evidence_path):
        if protected.exists() or protected.is_symlink():
            raise FileExistsError(f"immutable build target already exists: {protected}")
    started_at = datetime.now(UTC).isoformat()
    reservation = {
        "schema_version": BUILD_RESERVATION_SCHEMA,
        "status": "STARTED_IMMUTABLE_ATTEMPT_RESERVATION",
        "attempt_number": 1,
        "data_build_trial_count_before_execution": 0,
        "data_build_trial_count_including_this_attempt": 1,
        "started_at_utc": started_at,
        "protocol": {"path": CANONICAL_PROTOCOL_RELATIVE, "sha256": protocol_hash},
        "vendor_lock": {"path": CANONICAL_VENDOR_LOCK_RELATIVE, "sha256": lock_hash},
        "builder": {
            "path": str(builder_path.relative_to(root)),
            "sha256": builder_hash,
            "test_path": CANONICAL_TEST_RELATIVE,
            "test_sha256": test_hash,
        },
        "git_commit": source_preflight["git"]["commit"],
        "bulk_zip_download_started_after_this_reservation": True,
        "performance_or_strategy_execution_authorized": False,
    }
    # This O_EXCL-style no-overwrite publication is the global attempt lock.
    # A crash leaves it behind and forces an explicitly new attempt identity.
    reservation_bytes = canonical_json(reservation)
    reservation_hash = sha256_bytes(reservation_bytes)
    write_bytes_no_overwrite(reservation_path, reservation_bytes)
    _assert_json_identity(reservation_path, reservation, reservation_hash)

    downloads: list[dict[str, Any]] = []
    archive_filenames: dict[tuple[str, str], str] = {}
    staging_name: str | None = None
    staging_dir_fd: int | None = None
    connection: duckdb.DuckDBPyConnection | None = None
    cache_dir_fd: int | None = None
    bundle_parent_fd: int | None = None
    published: bool | None = False
    publication_state = "NOT_RENAMED"
    publication_durability_confirmed = False
    try:
        cache_dir_fd = _open_directory_tree_no_symlinks(
            root,
            CANONICAL_CACHE_RELATIVE,
            create=True,
        )
        bundle_parent_fd = _open_directory_tree_no_symlinks(
            root,
            str(Path(CANONICAL_BUNDLE_RELATIVE).parent),
            create=True,
        )
        with ThreadPoolExecutor(max_workers=DOWNLOAD_WORKERS) as executor:
            future_map = {
                executor.submit(
                    _download_archive,
                    entry,
                    cache_root=cache,
                    cache_dir_fd=cache_dir_fd,
                ): entry
                for entry in entries
            }
            for future in as_completed(future_map):
                entry = future_map[future]
                filename, audit = future.result()
                archive_filenames[(str(entry["symbol"]), str(entry["month"]))] = filename
                downloads.append(
                    {
                        "symbol": entry["symbol"],
                        "month": entry["month"],
                        "filename": entry["filename"],
                        **audit,
                    }
                )
        downloads.sort(key=lambda item: (SYMBOLS.index(item["symbol"]), item["month"]))
        if len(downloads) != len(entries):
            raise SnapshotBuildError("download audit count drifted")

        staging_name, staging_dir_fd = _create_staging_directory_at(
            bundle_parent_fd,
            final_name=bundle.name,
        )
        staging_bundle = bundle.parent / staging_name
        with _working_directory_fd(staging_dir_fd):
            temporary_db = Path("market.duckdb")
            try:
                connection = _create_snapshot_db(
                    temporary_db,
                    {
                        "schema_version": BUILD_EVIDENCE_SCHEMA,
                        "source_kind": SOURCE_KIND,
                        "protocol_sha256": protocol_hash,
                        "vendor_lock_sha256": lock_hash,
                        "builder_sha256": builder_hash,
                        "git_commit": source_preflight["git"]["commit"],
                        "history_start_utc": HISTORY_START.isoformat(),
                        "evaluation_end_exclusive_utc": EVALUATION_END.isoformat(),
                    },
                )
                archive_audits: list[dict[str, Any]] = []
                insert_sql = "INSERT INTO ohlcv VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)"
                for entry in entries:
                    key = (str(entry["symbol"]), str(entry["month"]))
                    archive_bytes = _read_verified_archive_at(
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
                    selected = tuple(
                        row for row in rows if HISTORY_START <= row[3] < EVALUATION_END
                    )
                    if selected:
                        connection.executemany(insert_sql, selected)
                    archive_audits.append(
                        {
                            "symbol": key[0],
                            "month": key[1],
                            "vendor_sha256": entry["vendor_sha256"],
                            "validated_month_rows": archive_audit["rows"],
                            "inserted_window_rows": len(selected),
                            "first_ts": archive_audit["first_ts"],
                            "last_ts": archive_audit["last_ts"],
                            "zip_member": archive_audit["member"],
                            "parse_input_sha256": sha256_bytes(archive_bytes),
                        }
                    )
                qa_write_connection = _validate_snapshot_db(connection)
                connection.execute("CHECKPOINT")
                connection.close()
                connection = None
                qa_read_only_post_close = _read_only_post_close_qa(temporary_db)
                if qa_read_only_post_close != qa_write_connection:
                    raise SnapshotBuildError(
                        "post-close read-only QA differs from write-connection QA"
                    )

                source_postflight = _source_identity(root, include_vendor_lock=True)
                _assert_build_source_postflight(
                    source_preflight,
                    source_postflight,
                    reservation_relative=CANONICAL_RESERVATION_RELATIVE,
                )
                with temporary_db.open("rb") as file_handle:
                    os.fsync(file_handle.fileno())
                output_identity = {
                    "path": CANONICAL_OUTPUT_RELATIVE,
                    "bytes": temporary_db.stat().st_size,
                    "sha256": sha256_file(temporary_db),
                }
                evidence = {
                    "schema_version": BUILD_EVIDENCE_SCHEMA,
                    "status": "SUCCESS",
                    "attempt_number": 1,
                    "data_build_trial_count_before_execution": 0,
                    "data_build_trial_count_including_this_attempt": 1,
                    "started_at_utc": started_at,
                    "finished_at_utc": datetime.now(UTC).isoformat(),
                    "source_kind": SOURCE_KIND,
                    "reservation": {
                        "path": CANONICAL_RESERVATION_RELATIVE,
                        "sha256": reservation_hash,
                    },
                    "source_preflight": source_preflight,
                    "source_postflight": source_postflight,
                    "runtime_versions": _runtime_versions(),
                    "protocol": {
                        "path": CANONICAL_PROTOCOL_RELATIVE,
                        "sha256": protocol_hash,
                    },
                    "vendor_lock": {
                        "path": CANONICAL_VENDOR_LOCK_RELATIVE,
                        "sha256": lock_hash,
                        "entries": len(entries),
                    },
                    "builder": {
                        "path": str(builder_path.relative_to(root)),
                        "sha256": builder_hash,
                        "test_path": CANONICAL_TEST_RELATIVE,
                        "test_sha256": test_hash,
                    },
                    "output": output_identity,
                    "qa_write_connection": qa_write_connection,
                    "qa_read_only_post_close": qa_read_only_post_close,
                    "qa_pre_post_exact_match": True,
                    "downloads": downloads,
                    "archive_audits": archive_audits,
                    "governance": {
                        "single_source_full_rebuild": True,
                        "failed_v1_rows_reused": False,
                        "spot_mark_index_or_other_market_data_used": False,
                        "forward_fill_interpolation_resampling_or_synthetic_rows": False,
                        "strategy_engine_report_or_performance_code_imported": False,
                        "exchange_account_or_credentials_used": False,
                        "live_database_or_daemon_mutated": False,
                        "alpha_result_trials": 0,
                        "database_and_success_evidence_published_as_one_atomic_bundle": True,
                    },
                }
                temporary_evidence = Path("build_evidence.json")
                write_json_no_overwrite(temporary_evidence, evidence)
                with temporary_evidence.open("rb") as file_handle:
                    os.fsync(file_handle.fileno())
                os.fsync(staging_dir_fd)
            finally:
                if connection is not None:
                    with contextlib.suppress(Exception):
                        connection.close()
                    connection = None
        source_publish_boundary = _source_identity(root, include_vendor_lock=True)
        _assert_build_source_postflight(
            source_preflight,
            source_publish_boundary,
            reservation_relative=CANONICAL_RESERVATION_RELATIVE,
        )
        if source_publish_boundary != source_postflight:
            raise SnapshotBuildError("build source identity changed before bundle publication")
        _assert_json_identity(reservation_path, reservation, reservation_hash)
        _publish_bundle_atomic(
            staging_bundle,
            bundle,
            parent_dir_fd=bundle_parent_fd,
            staging_dir_fd=staging_dir_fd,
            identity_root=root,
            identity_relative=str(Path(CANONICAL_BUNDLE_RELATIVE).parent),
        )
        published = True
        publication_state = "VISIBLE_RETAINED_INODE_DURABILITY_CONFIRMED"
        publication_durability_confirmed = True
        staging_name = None
        # No fallible publication step follows this point: DB and evidence
        # became visible together in the same directory rename.
        return evidence
    except BaseException as exc:
        if isinstance(exc, BundlePublicationError):
            publication_state = exc.publication_state
            published = _publication_confirmation(publication_state)
        if connection is not None:
            with contextlib.suppress(Exception):
                connection.close()
            connection = None
        source_at_failure = _source_identity(root, include_vendor_lock=True)
        failure_evidence = {
            "schema_version": BUILD_EVIDENCE_SCHEMA,
            "status": "FAILED",
            "attempt_number": 1,
            "data_build_trial_count_before_execution": 0,
            "data_build_trial_count_including_this_attempt": 1,
            "started_at_utc": started_at,
            "finished_at_utc": datetime.now(UTC).isoformat(),
            "source_kind": SOURCE_KIND,
            "reservation": {
                "path": CANONICAL_RESERVATION_RELATIVE,
                "sha256": reservation_hash,
            },
            "source_preflight": source_preflight,
            "source_at_failure": source_at_failure,
            "runtime_versions": _runtime_versions(),
            "protocol": {
                "path": CANONICAL_PROTOCOL_RELATIVE,
                "sha256": protocol_hash,
            },
            "vendor_lock": {
                "path": CANONICAL_VENDOR_LOCK_RELATIVE,
                "sha256": lock_hash,
                "entries": len(entries),
            },
            "builder": {
                "path": str(builder_path.relative_to(root)),
                "sha256": builder_hash,
                "test_path": CANONICAL_TEST_RELATIVE,
                "test_sha256": test_hash,
            },
            "output_published": published,
            "output_publication_state": publication_state,
            "publication_durability_confirmed": publication_durability_confirmed,
            "downloads_completed": downloads,
            "exception_type": type(exc).__name__,
            "exception_message": str(exc),
            "traceback": traceback.format_exc(),
            "governance": {
                "strategy_or_performance_code_imported": False,
                "exchange_account_or_credentials_used": False,
                "live_database_or_daemon_mutated": False,
                "alpha_result_trials": 0,
            },
        }
        write_json_no_overwrite(failure_evidence_path, failure_evidence)
        raise
    finally:
        if staging_name is not None and staging_dir_fd is not None and bundle_parent_fd is not None:
            with contextlib.suppress(Exception):
                _remove_staging_directory_at(
                    bundle_parent_fd,
                    staging_dir_fd,
                    staging_name,
                )
        if staging_dir_fd is not None:
            os.close(staging_dir_fd)
        if cache_dir_fd is not None:
            os.close(cache_dir_fd)
        if bundle_parent_fd is not None:
            os.close(bundle_parent_fd)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[2])
    subparsers = parser.add_subparsers(dest="command", required=True)
    pin_parser = subparsers.add_parser("pin", help="pin official vendor checksum sidecars")
    pin_parser.add_argument("--protocol", type=Path)
    build_parser = subparsers.add_parser("build", help="build the checksum-pinned snapshot")
    build_parser.add_argument("--protocol", type=Path)
    build_parser.add_argument("--vendor-lock", type=Path)
    args = parser.parse_args(argv)
    root = args.repo_root.resolve()
    protocol = args.protocol or root / CANONICAL_PROTOCOL_RELATIVE
    if args.command == "pin":
        result = pin_vendor_lock(protocol, repo_root=root)
        print(
            json.dumps(
                {
                    "status": "VENDOR_LOCK_PINNED",
                    "entries": result["entry_count"],
                    "output": CANONICAL_VENDOR_LOCK_RELATIVE,
                },
                sort_keys=True,
            )
        )
        return 0
    vendor_lock = args.vendor_lock or root / CANONICAL_VENDOR_LOCK_RELATIVE
    result = build_snapshot(protocol, vendor_lock, repo_root=root)
    print(
        json.dumps(
            {
                "status": result["status"],
                "output": result["output"],
                "evidence": CANONICAL_BUILD_EVIDENCE_RELATIVE,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
