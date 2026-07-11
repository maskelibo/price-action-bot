from __future__ import annotations

import io
import json
import zipfile
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path

import pytest

from scripts.research import build_crypto_15m_usdm_snapshot_v2 as v2
from scripts.research import build_crypto_15m_usdm_snapshot_v3 as builder

ROOT = Path(__file__).resolve().parents[1]


def _monthly_zip(
    *,
    symbol: str,
    month: str,
    omitted: set[int] | None = None,
) -> bytes:
    month_start, month_end, _full_rows = builder._month_bounds(month)
    omitted = omitted or set()
    records = [",".join(v2.CANONICAL_CSV_HEADER)]
    for timestamp_ms in range(
        int(month_start.timestamp() * 1000),
        int(month_end.timestamp() * 1000),
        builder.BAR_MS,
    ):
        if timestamp_ms in omitted:
            continue
        records.append(
            ",".join(
                (
                    str(timestamp_ms),
                    "10.0",
                    "12.0",
                    "9.0",
                    "11.0",
                    "123.5",
                    str(timestamp_ms + builder.BAR_MS - 1),
                    "1358.5",
                    "42",
                    "60.0",
                    "660.0",
                    "0",
                )
            )
        )
    output = io.BytesIO()
    member = f"{symbol}-15m-{month}.csv"
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(member, "\n".join(records) + "\n")
    return output.getvalue()


def _gap_timestamps(month: str) -> set[int]:
    month_start, month_end, _rows = builder._month_bounds(month)
    return {
        timestamp_ms
        for timestamp_ms in range(
            int(month_start.timestamp() * 1000),
            int(month_end.timestamp() * 1000),
            builder.BAR_MS,
        )
        if builder._is_frozen_missing_timestamp("SOLUSDT", timestamp_ms)
    }


def _zip_from_lines(
    *,
    symbol: str,
    month: str,
    lines: list[str],
    member: str | None = None,
) -> bytes:
    output = io.BytesIO()
    member = member or f"{symbol}-15m-{month}.csv"
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(member, "\n".join(lines) + "\n")
    return output.getvalue()


def _zip_lines(payload: bytes) -> list[str]:
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        member = archive.namelist()[0]
        return archive.read(member).decode("utf-8").splitlines()


def test_frozen_v3_row_and_key_identity() -> None:
    assert builder.expected_rows_for_symbol("ETHUSDT") == 184_896
    assert builder.expected_rows_for_symbol("SOLUSDT") == 184_416
    assert sum(builder.expected_rows_for_symbol(symbol) for symbol in builder.SYMBOLS) == 2_586_624
    assert builder.expected_key_sha256() == (
        "8fa35b544898ab7f131a0826a2a4bd989aa0d283cc5a2926fb85f962a3e93318"
    )
    assert builder.expected_missing_key_sha256() == (
        "bfd80250c7ae2b5b242f80b2170c47c872b771100f88b7e1ed64d0eaad29287d"
    )
    assert builder.EXPECTED_VALIDATED_VENDOR_ROWS == 2_613_504


def test_archive_progress_evidence_is_exact_and_failure_safe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    audits = [
        {
            "symbol": "ETHUSDT",
            "month": "2021-01",
            "validated_vendor_rows": 100,
            "inserted_target_rows_confirmed": 80,
        }
    ]
    progress = builder._archive_progress_evidence(
        archive_access_started=True,
        downloads=[{"filename": "archive.zip"}],
        archive_audits=audits,
        archive_parse_attempted_count=1,
        archives_parsed_count=1,
        validated_vendor_rows=100,
        inserted_target_rows_confirmed=80,
        current_archive=None,
    )
    assert progress["counter_consistency_pass"] is True
    assert progress["archives_parsed_count"] == 1
    assert progress["archive_audits_completed"] == audits

    inconsistent = builder._archive_progress_evidence(
        archive_access_started=True,
        downloads=[],
        archive_audits=audits,
        archive_parse_attempted_count=0,
        archives_parsed_count=1,
        validated_vendor_rows=99,
        inserted_target_rows_confirmed=79,
        current_archive={"phase": "PARSE_VALIDATE_AND_INSERT"},
    )
    assert inconsistent["counter_consistency_pass"] is False
    assert inconsistent["counter_consistency_issues"]

    def injected_progress_failure(**_kwargs: object) -> dict:
        raise RuntimeError("injected progress collection failure")

    monkeypatch.setattr(builder, "_archive_progress_evidence", injected_progress_failure)
    fallback = builder._best_effort_archive_progress_evidence(
        archive_access_started=True,
        downloads=[],
        archive_audits=audits,
        archive_parse_attempted_count=1,
        archives_parsed_count=1,
        validated_vendor_rows=100,
        inserted_target_rows_confirmed=80,
        current_archive=None,
    )
    assert fallback["counter_consistency_pass"] is False
    assert fallback["counter_consistency_issues"][0].startswith(
        "progress_evidence_collection_failed:RuntimeError"
    )


def test_gap_manifest_is_exact_and_bounded() -> None:
    manifest = builder._gap_manifest()
    assert [item["bars_per_affected_symbol"] for item in manifest] == [288, 192]
    assert sum(item["bars_per_affected_symbol"] for item in manifest) == 480
    assert all(item["affected_symbols"] == list(builder.GAP_SYMBOLS) for item in manifest)
    assert manifest[0]["start_inclusive_utc"] == "2022-02-26T00:00:00+00:00"
    assert manifest[-1]["end_exclusive_utc"] == "2022-04-03T00:00:00+00:00"


def test_parser_accepts_complete_continuous_symbol_month() -> None:
    rows, audit = builder.parse_monthly_archive(
        _monthly_zip(symbol="ETHUSDT", month="2022-02"),
        symbol="ETHUSDT",
        month="2022-02",
        expected_filename="ETHUSDT-15m-2022-02.zip",
    )
    assert len(rows) == 2_688
    assert audit["frozen_missing_rows"] == 0


@pytest.mark.parametrize(
    ("month", "expected_rows", "expected_missing"),
    [("2022-02", 2_400, 288), ("2022-04", 2_688, 192)],
)
def test_parser_accepts_only_exact_frozen_vendor_gap(
    month: str,
    expected_rows: int,
    expected_missing: int,
) -> None:
    rows, audit = builder.parse_monthly_archive(
        _monthly_zip(symbol="SOLUSDT", month=month, omitted=_gap_timestamps(month)),
        symbol="SOLUSDT",
        month=month,
        expected_filename=f"SOLUSDT-15m-{month}.zip",
    )
    assert len(rows) == expected_rows
    assert audit["frozen_missing_rows"] == expected_missing


def test_parser_rejects_filled_bar_inside_frozen_gap() -> None:
    with pytest.raises(builder.SnapshotV3BuildError, match="gap manifest"):
        builder.parse_monthly_archive(
            _monthly_zip(symbol="SOLUSDT", month="2022-02"),
            symbol="SOLUSDT",
            month="2022-02",
            expected_filename="SOLUSDT-15m-2022-02.zip",
        )


def test_parser_rejects_same_gap_for_unaffected_symbol() -> None:
    with pytest.raises(builder.SnapshotV3BuildError, match="gap manifest"):
        builder.parse_monthly_archive(
            _monthly_zip(
                symbol="ETHUSDT",
                month="2022-02",
                omitted=_gap_timestamps("2022-02"),
            ),
            symbol="ETHUSDT",
            month="2022-02",
            expected_filename="ETHUSDT-15m-2022-02.zip",
        )


def test_parser_rejects_one_additional_missing_bar() -> None:
    omitted = _gap_timestamps("2022-02")
    omitted.add(int(datetime(2022, 2, 10, tzinfo=UTC).timestamp() * 1000))
    with pytest.raises(builder.SnapshotV3BuildError, match="gap manifest"):
        builder.parse_monthly_archive(
            _monthly_zip(symbol="SOLUSDT", month="2022-02", omitted=omitted),
            symbol="SOLUSDT",
            month="2022-02",
            expected_filename="SOLUSDT-15m-2022-02.zip",
        )


def test_parser_rejects_wrong_filename_and_member_identity() -> None:
    payload = _monthly_zip(symbol="ETHUSDT", month="2022-02")
    with pytest.raises(builder.SnapshotV3BuildError, match="filename identity"):
        builder.parse_monthly_archive(
            payload,
            symbol="ETHUSDT",
            month="2022-02",
            expected_filename="BTCUSDT-15m-2022-02.zip",
        )
    lines = _zip_lines(payload)
    with pytest.raises(builder.SnapshotV3BuildError, match="ZIP member drift"):
        builder.parse_monthly_archive(
            _zip_from_lines(
                symbol="ETHUSDT",
                month="2022-02",
                lines=lines,
                member="nested/wrong.csv",
            ),
            symbol="ETHUSDT",
            month="2022-02",
            expected_filename="ETHUSDT-15m-2022-02.zip",
        )


def test_parser_rejects_adversarial_csv_drift() -> None:
    payload = _monthly_zip(symbol="ETHUSDT", month="2022-02")
    canonical = _zip_lines(payload)
    variants: list[list[str]] = []

    preamble = canonical.copy()
    preamble.insert(0, "arbitrary,preamble")
    variants.append(preamble)

    blank = canonical.copy()
    blank.insert(2, "")
    variants.append(blank)

    duplicate = canonical.copy()
    duplicate.insert(3, duplicate[2])
    variants.append(duplicate)

    out_of_order = canonical.copy()
    out_of_order[1], out_of_order[2] = out_of_order[2], out_of_order[1]
    variants.append(out_of_order)

    microseconds = canonical.copy()
    fields = microseconds[1].split(",")
    fields[0] = str(int(fields[0]) * 1_000)
    fields[6] = str(int(fields[6]) * 1_000)
    microseconds[1] = ",".join(fields)
    variants.append(microseconds)

    malformed_tail = canonical.copy()
    fields = malformed_tail[1].split(",")
    fields[8] = "not-an-integer"
    malformed_tail[1] = ",".join(fields)
    variants.append(malformed_tail)

    off_grid = canonical.copy()
    fields = off_grid[1].split(",")
    fields[0] = str(int(fields[0]) + 1)
    fields[6] = str(int(fields[6]) + 1)
    off_grid[1] = ",".join(fields)
    variants.append(off_grid)

    outside_month = canonical.copy()
    fields = outside_month[1].split(",")
    timestamp_ms = int(datetime(2022, 1, 31, 23, 45, tzinfo=UTC).timestamp() * 1000)
    fields[0] = str(timestamp_ms)
    fields[6] = str(timestamp_ms + builder.BAR_MS - 1)
    outside_month[1] = ",".join(fields)
    variants.append(outside_month)

    wrong_close_time = canonical.copy()
    fields = wrong_close_time[1].split(",")
    fields[6] = str(int(fields[6]) - 1)
    wrong_close_time[1] = ",".join(fields)
    variants.append(wrong_close_time)

    nonfinite = canonical.copy()
    fields = nonfinite[1].split(",")
    fields[4] = "nan"
    nonfinite[1] = ",".join(fields)
    variants.append(nonfinite)

    invalid_geometry = canonical.copy()
    fields = invalid_geometry[1].split(",")
    fields[2] = "8.0"
    invalid_geometry[1] = ",".join(fields)
    variants.append(invalid_geometry)

    for lines in variants:
        with pytest.raises(builder.SnapshotV3BuildError):
            builder.parse_monthly_archive(
                _zip_from_lines(symbol="ETHUSDT", month="2022-02", lines=lines),
                symbol="ETHUSDT",
                month="2022-02",
                expected_filename="ETHUSDT-15m-2022-02.zip",
            )


@pytest.mark.subprocess
def test_protocol_validation_is_exact_and_fail_closed() -> None:
    protocol = v2.load_strict_json(ROOT / builder.CANONICAL_PROTOCOL_RELATIVE)
    builder._validate_protocol(protocol, repo_root=ROOT)
    mutations = (
        ("expected_total_rows", 2_588_544),
        ("vendor_gap_symbols", ["SOLUSDT"]),
        ("data_build_trial_count_before_execution", 0),
    )
    for key, value in mutations:
        changed = deepcopy(protocol)
        changed[key] = value
        with pytest.raises(builder.SnapshotV3BuildError):
            builder._validate_protocol(changed, repo_root=ROOT)
    changed = deepcopy(protocol)
    changed["governance"]["alpha_result_trials"] = 1
    with pytest.raises(builder.SnapshotV3BuildError, match="governance"):
        builder._validate_protocol(changed, repo_root=ROOT)


def test_coverage_diagnosis_identity_and_content() -> None:
    path = ROOT / builder.CANONICAL_COVERAGE_DIAGNOSIS_RELATIVE
    assert v2.sha256_file(path) == builder.COVERAGE_DIAGNOSIS_SHA256
    diagnosis = json.loads(path.read_text(encoding="utf-8"))
    target = diagnosis["successor_target_freeze"]
    assert target["expected_total_rows"] == builder.TOTAL_ROWS
    assert target["expected_ordered_primary_key_sha256"] == builder.EXPECTED_KEY_SHA256
    assert diagnosis["audit_scope"]["alpha_result_trials"] == 0


def test_source_postflight_allows_only_v3_reservation() -> None:
    preflight = {
        "git": {"commit": "a" * 40, "clean": True, "status": []},
        "file_sha256": {"source": "b" * 64},
        "runtime_versions": {"python": "3.12"},
    }
    postflight = deepcopy(preflight)
    postflight["git"] = {
        "commit": "a" * 40,
        "clean": False,
        "status": [f"?? {builder.CANONICAL_RESERVATION_RELATIVE}"],
    }
    builder._assert_build_source_postflight(preflight, postflight)
    postflight["git"]["status"].append("?? unexpected.txt")
    with pytest.raises(builder.SnapshotV3BuildError, match="postflight"):
        builder._assert_build_source_postflight(preflight, postflight)


def test_source_identity_includes_imported_v2_test_and_sealed_predecessors() -> None:
    paths = builder._source_paths(ROOT)
    assert v2.CANONICAL_TEST_RELATIVE in paths
    assert v2.CANONICAL_PROTOCOL_RELATIVE in paths
    assert v2.CANONICAL_VENDOR_LOCK_RELATIVE in paths
    assert v2.CANONICAL_RESERVATION_RELATIVE in paths
    assert v2.CANONICAL_FAILURE_EVIDENCE_RELATIVE in paths
    assert builder.CANONICAL_COVERAGE_DIAGNOSIS_RELATIVE in paths
    assert builder.FAIR_BASELINE_PREREG_RELATIVE in paths


def test_dirfd_config_publication_is_canonical_and_no_overwrite(tmp_path: Path) -> None:
    directory_fd = builder.base._open_cache_directory(tmp_path)
    payload = {"status": "STARTED", "value": 1}
    try:
        digest = builder._write_json_no_overwrite_at(
            directory_fd,
            "reservation.json",
            payload,
        )
        builder._assert_json_identity_at(
            directory_fd,
            "reservation.json",
            payload,
            expected_sha256=digest,
        )
        assert json.loads((tmp_path / "reservation.json").read_text()) == payload
        with pytest.raises(FileExistsError):
            builder._write_json_no_overwrite_at(
                directory_fd,
                "reservation.json",
                payload,
            )
    finally:
        builder.os.close(directory_fd)


def test_config_dirfd_identity_rejects_parent_path_swap(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    configs = root / "configs"
    displaced = root / "displaced-configs"
    configs.mkdir(parents=True)
    directory_fd = builder.base._open_directory_tree_no_symlinks(
        root,
        "configs",
        create=False,
    )
    configs.rename(displaced)
    configs.mkdir()
    try:
        with pytest.raises(v2.SnapshotBuildError, match="retained inode"):
            builder.base._assert_directory_tree_matches_fd(root, "configs", directory_fd)
        assert list(configs.iterdir()) == []
    finally:
        builder.os.close(directory_fd)


def test_canonical_bundle_leaf_symlink_is_not_resolved_or_accepted(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    parent = root / "data" / "backups"
    parent.mkdir(parents=True)
    outside = tmp_path / "outside-bundle"
    outside.mkdir()
    canonical_leaf = parent / Path(builder.CANONICAL_BUNDLE_RELATIVE).name
    canonical_leaf.symlink_to(outside, target_is_directory=True)

    bundle, parent_relative, final_name = builder._canonical_bundle_target(root)
    assert bundle == canonical_leaf
    assert parent_relative == "data/backups"
    assert final_name == canonical_leaf.name

    parent_fd = builder.base._open_directory_tree_no_symlinks(
        root,
        parent_relative,
        create=False,
    )
    try:
        with pytest.raises(FileExistsError, match="immutable config target"):
            builder._assert_name_absent_at(parent_fd, final_name)
    finally:
        builder.os.close(parent_fd)


@pytest.mark.parametrize(
    "relative",
    [
        builder.CANONICAL_RESERVATION_RELATIVE,
        builder.CANONICAL_FAILURE_EVIDENCE_RELATIVE,
    ],
)
def test_canonical_config_dangling_symlink_is_not_redirected(
    tmp_path: Path,
    relative: str,
) -> None:
    root = tmp_path / "repo"
    configs = root / "configs"
    configs.mkdir(parents=True)
    canonical_leaf = root / relative
    canonical_leaf.symlink_to("redirected-name.json")

    target, literal_name = builder._canonical_config_target(root, relative)
    assert target == canonical_leaf
    assert literal_name == canonical_leaf.name

    directory_fd = builder.base._open_directory_tree_no_symlinks(
        root,
        "configs",
        create=False,
    )
    try:
        with pytest.raises(FileExistsError, match="immutable config target"):
            builder._assert_name_absent_at(directory_fd, literal_name)
    finally:
        builder.os.close(directory_fd)


def test_reservation_fsync_failure_publishes_terminal_before_archive_access(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "repo"
    configs = root / "configs"
    configs.mkdir(parents=True)
    directory_fd = builder.base._open_directory_tree_no_symlinks(
        root,
        "configs",
        create=False,
    )
    reservation = {
        "status": "STARTED",
        "archive_access_may_start_only_after_this_reservation": True,
    }
    actual_fsync = builder.os.fsync
    injected = False

    def fail_first_directory_fsync(descriptor: int) -> None:
        nonlocal injected
        if descriptor == directory_fd and not injected:
            injected = True
            raise OSError("injected reservation directory fsync failure")
        actual_fsync(descriptor)

    def terminal_factory(exc: BaseException, reservation_hash: str) -> dict:
        return {
            "status": "FAILED_DURING_RESERVATION_PUBLICATION_BEFORE_ARCHIVE_ACCESS",
            "archive_access_started": False,
            "reservation_sha256": reservation_hash,
            "exception_type": type(exc).__name__,
        }

    monkeypatch.setattr(builder.os, "fsync", fail_first_directory_fsync)
    try:
        with pytest.raises(OSError, match="injected reservation"):
            builder._publish_reservation_with_terminal_on_error(
                repo_root=root,
                config_dir_fd=directory_fd,
                reservation_name="reservation.json",
                failure_name="failure.json",
                reservation=reservation,
                terminal_factory=terminal_factory,
            )
        assert json.loads((configs / "reservation.json").read_text()) == reservation
        terminal = json.loads((configs / "failure.json").read_text())
        assert terminal["archive_access_started"] is False
        assert terminal["status"].startswith("FAILED_DURING_RESERVATION")
    finally:
        builder.os.close(directory_fd)


def test_reservation_terminal_factory_failure_still_publishes_terminal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "repo"
    configs = root / "configs"
    configs.mkdir(parents=True)
    directory_fd = builder.base._open_directory_tree_no_symlinks(
        root,
        "configs",
        create=False,
    )
    actual_fsync = builder.os.fsync
    injected = False

    def fail_first_directory_fsync(descriptor: int) -> None:
        nonlocal injected
        if descriptor == directory_fd and not injected:
            injected = True
            raise OSError("injected reservation directory fsync failure")
        actual_fsync(descriptor)

    def broken_terminal_factory(_exc: BaseException, _reservation_hash: str) -> dict:
        raise RuntimeError("injected terminal factory failure")

    monkeypatch.setattr(builder.os, "fsync", fail_first_directory_fsync)
    try:
        with pytest.raises(OSError, match="injected reservation"):
            builder._publish_reservation_with_terminal_on_error(
                repo_root=root,
                config_dir_fd=directory_fd,
                reservation_name="reservation.json",
                failure_name="failure.json",
                reservation={"status": "STARTED"},
                terminal_factory=broken_terminal_factory,
            )
        terminal = json.loads((configs / "failure.json").read_text())
        assert terminal["status"] == "FAILED_DURING_RESERVATION_TERMINAL_FACTORY"
        assert terminal["archive_access_started"] is False
        assert terminal["terminal_factory_exception_type"] == "RuntimeError"
    finally:
        builder.os.close(directory_fd)


def test_snapshot_schema_requires_exact_primary_keys() -> None:
    valid = builder.base._create_snapshot_db(Path(":memory:"), {"key": "value"})
    try:
        contract = builder._validate_snapshot_schema(valid)
        assert contract["exact_primary_keys"] == [
            ["ohlcv", ["venue", "symbol", "timeframe", "ts"]],
            ["snapshot_metadata", ["key"]],
        ]
        valid.execute("CREATE VIEW extra_view AS SELECT * FROM ohlcv")
        with pytest.raises(builder.SnapshotV3BuildError, match="table object set"):
            builder._validate_snapshot_schema(valid)
        valid.execute("DROP VIEW extra_view")
        valid.execute("CREATE INDEX extra_index ON ohlcv(symbol)")
        with pytest.raises(builder.SnapshotV3BuildError, match="explicit indexes"):
            builder._validate_snapshot_schema(valid)
        valid.execute("DROP INDEX extra_index")
        valid.execute("ALTER TABLE ohlcv ALTER open SET DEFAULT 1.0")
        with pytest.raises(builder.SnapshotV3BuildError, match="table schema"):
            builder._validate_snapshot_schema(valid)
        valid.execute("ALTER TABLE ohlcv ALTER open DROP DEFAULT")
        valid.execute("CREATE SCHEMA extra_schema")
        with pytest.raises(builder.SnapshotV3BuildError, match="user schema set"):
            builder._validate_snapshot_schema(valid)
        valid.execute("DROP SCHEMA extra_schema")
        valid.execute("CREATE SEQUENCE extra_sequence")
        with pytest.raises(builder.SnapshotV3BuildError, match="persistent user objects"):
            builder._validate_snapshot_schema(valid)
        valid.execute("DROP SEQUENCE extra_sequence")
        valid.execute("CREATE MACRO extra_macro(x) AS x + 1")
        with pytest.raises(builder.SnapshotV3BuildError, match="persistent user objects"):
            builder._validate_snapshot_schema(valid)
        valid.execute("DROP MACRO extra_macro")
        valid.execute("CREATE TYPE extra_type AS ENUM ('a', 'b')")
        with pytest.raises(builder.SnapshotV3BuildError, match="persistent user objects"):
            builder._validate_snapshot_schema(valid)
    finally:
        valid.close()

    invalid = builder.duckdb.connect(":memory:")
    try:
        invalid.execute(
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
                volume DOUBLE NOT NULL
            )
            """
        )
        invalid.execute("CREATE TABLE snapshot_metadata (key VARCHAR NOT NULL, value VARCHAR)")
        with pytest.raises(builder.SnapshotV3BuildError, match="constraints"):
            builder._validate_snapshot_schema(invalid)
    finally:
        invalid.close()


def test_random_database_name_publishes_exclusively(tmp_path: Path) -> None:
    directory_fd = builder.base._open_cache_directory(tmp_path)
    temporary_name = f".market.{'a' * 64}.duckdb"
    payload = b"immutable database identity"
    (tmp_path / temporary_name).write_bytes(payload)
    try:
        identity = builder._publish_database_name_at(directory_fd, temporary_name)
        assert identity == {
            "bytes": len(payload),
            "sha256": builder.base.sha256_bytes(payload),
        }
        assert not (tmp_path / temporary_name).exists()
        assert (tmp_path / "market.duckdb").read_bytes() == payload
    finally:
        builder.os.close(directory_fd)


def test_fixed_database_symlink_cannot_redirect_publish(tmp_path: Path) -> None:
    directory_fd = builder.base._open_cache_directory(tmp_path)
    temporary_name = f".market.{'b' * 64}.duckdb"
    temporary_payload = b"new database"
    outside = tmp_path / "outside.duckdb"
    outside_payload = b"must remain unchanged"
    (tmp_path / temporary_name).write_bytes(temporary_payload)
    outside.write_bytes(outside_payload)
    (tmp_path / "market.duckdb").symlink_to(outside)
    try:
        with pytest.raises(FileExistsError):
            builder._publish_database_name_at(directory_fd, temporary_name)
        assert outside.read_bytes() == outside_payload
        assert (tmp_path / temporary_name).read_bytes() == temporary_payload
    finally:
        builder.os.close(directory_fd)


def test_staged_file_hardlink_alias_is_rejected(tmp_path: Path) -> None:
    directory_fd = builder.base._open_cache_directory(tmp_path)
    original = tmp_path / "market.duckdb"
    alias = tmp_path / "outside-alias.duckdb"
    original.write_bytes(b"database bytes")
    builder.os.link(original, alias)
    try:
        with pytest.raises(builder.SnapshotV3BuildError, match="unsafe staged file profile"):
            builder._file_identity_at(directory_fd, "market.duckdb")
    finally:
        builder.os.close(directory_fd)


def test_staged_file_symlink_empty_and_concurrent_mutation_are_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    directory_fd = builder.base._open_cache_directory(tmp_path)
    target = tmp_path / "target.bin"
    target.write_bytes(b"target")
    (tmp_path / "symlink.bin").symlink_to(target)
    (tmp_path / "empty.bin").touch()
    mutable = tmp_path / "mutable.bin"
    mutable.write_bytes(b"original bytes")
    try:
        with pytest.raises(builder.SnapshotV3BuildError, match="safely open"):
            builder._file_identity_at(directory_fd, "symlink.bin")
        with pytest.raises(builder.SnapshotV3BuildError, match="unsafe staged file profile"):
            builder._file_identity_at(directory_fd, "empty.bin")

        actual_read = builder.os.read
        mutated = False

        def mutate_after_first_read(descriptor: int, size: int) -> bytes:
            nonlocal mutated
            chunk = actual_read(descriptor, size)
            if chunk and not mutated:
                mutated = True
                mutable.write_bytes(b"changed bytes with another size")
            return chunk

        monkeypatch.setattr(builder.os, "read", mutate_after_first_read)
        with pytest.raises(builder.SnapshotV3BuildError, match="changed while hashing"):
            builder._file_identity_at(directory_fd, "mutable.bin")
    finally:
        builder.os.close(directory_fd)


def test_staged_file_fsync_failure_is_fail_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    directory_fd = builder.base._open_cache_directory(tmp_path)
    (tmp_path / "market.duckdb").write_bytes(b"database")

    def fail_fsync(_descriptor: int) -> None:
        raise OSError("injected file fsync failure")

    monkeypatch.setattr(builder.os, "fsync", fail_fsync)
    try:
        with pytest.raises(OSError, match="injected file fsync"):
            builder._fsync_regular_file_at(directory_fd, "market.duckdb")
    finally:
        builder.os.close(directory_fd)


def test_staging_bundle_child_set_and_identities_are_exact(tmp_path: Path) -> None:
    directory_fd = builder.base._open_cache_directory(tmp_path)
    database_body = b"database bytes"
    evidence = {"status": "SUCCESS", "value": 1}
    (tmp_path / "market.duckdb").write_bytes(database_body)
    try:
        builder._write_json_no_overwrite_at(
            directory_fd,
            "build_evidence.json",
            evidence,
        )
        identity = builder._assert_staging_bundle_at(
            directory_fd,
            expected_database_identity={
                "bytes": len(database_body),
                "sha256": builder.base.sha256_bytes(database_body),
            },
            expected_evidence=evidence,
        )
        assert identity["children"] == ["build_evidence.json", "market.duckdb"]
        (tmp_path / "unexpected.wal").write_bytes(b"unexpected")
        with pytest.raises(builder.SnapshotV3BuildError, match="child set"):
            builder._assert_staging_bundle_at(
                directory_fd,
                expected_database_identity=identity["database"],
                expected_evidence=evidence,
            )
    finally:
        builder.os.close(directory_fd)


def test_publication_probe_tracks_retained_staging_inode(tmp_path: Path) -> None:
    parent_fd = builder.base._open_cache_directory(tmp_path)
    staging_name, staging_fd = builder.base._create_staging_directory_at(
        parent_fd,
        final_name="bundle",
    )
    try:
        assert builder._probe_bundle_publication_at(
            parent_fd,
            staging_fd,
            final_name="bundle",
        ) == (False, "NOT_VISIBLE_AT_FINAL_NAME")
        builder.base._rename_exclusive_at(parent_fd, staging_name, "bundle")
        assert builder._probe_bundle_publication_at(
            parent_fd,
            staging_fd,
            final_name="bundle",
        ) == (True, "VISIBLE_RETAINED_INODE_DURABILITY_UNCONFIRMED")
        inconsistent_outcomes = (
            (True, "NOT_RENAMED", False),
            (True, "VISIBLE_RETAINED_INODE_DURABILITY_CONFIRMED", False),
        )
        for outcome in inconsistent_outcomes:
            assert builder._reconcile_failure_publication_outcome(
                outcome,
                parent_fd,
                staging_fd,
                final_name="bundle",
            ) == (True, "VISIBLE_RETAINED_INODE_DURABILITY_UNCONFIRMED", False)
        assert (
            builder._reconcile_failure_publication_outcome(
                builder.CONFIRMED_PUBLICATION_OUTCOME,
                parent_fd,
                staging_fd,
                final_name="bundle",
            )
            == builder.CONFIRMED_PUBLICATION_OUTCOME
        )
        builder.os.mkdir("competitor", dir_fd=parent_fd)
        assert builder._probe_bundle_publication_at(
            parent_fd,
            staging_fd,
            final_name="competitor",
        ) == (None, "FINAL_NAME_DOES_NOT_MATCH_RETAINED_STAGING_INODE")
    finally:
        builder.os.close(staging_fd)
        builder.os.close(parent_fd)


def test_v3_builder_is_strategy_live_and_performance_isolated() -> None:
    source = Path(builder.__file__).read_text(encoding="utf-8")
    forbidden = (
        "price_action.lab.crypto_15m_v15p2_program",
        "price_action.strategies",
        "price_action.risk",
        "price_action.execution",
        "OHLCVStore",
        "ccxt",
    )
    assert all(value not in source for value in forbidden)
    assert "base._download_archive" not in source
    assert "base._http_get" not in source
    assert "create=False" in source
    assert builder.CANONICAL_OUTPUT_RELATIVE != "data/market.duckdb"
    assert builder.CANONICAL_BUNDLE_RELATIVE != v2.CANONICAL_BUNDLE_RELATIVE
