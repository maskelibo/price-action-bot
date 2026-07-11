from __future__ import annotations

import hashlib
import io
import json
import subprocess
import zipfile
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path

import duckdb
import pytest

from scripts.research import build_crypto_15m_usdm_snapshot_v2 as builder

ROOT = Path(__file__).resolve().parents[1]


def _monthly_zip(
    *,
    symbol: str = "ETHUSDT",
    month: str = "2021-02",
    gap: int | None = None,
    prefix_lines: tuple[str, ...] = (),
    timestamp_multiplier: int = 1,
    tail_fields: tuple[str, str, str, str, str] = ("0", "1", "0", "0", "0"),
) -> bytes:
    start_ms, end_ms, expected_rows = builder._month_bounds(month)
    records: list[str] = []
    for index, timestamp_ms in enumerate(range(start_ms, end_ms, builder.BAR_MS)):
        if index == gap:
            continue
        records.append(
            ",".join(
                (
                    str(timestamp_ms * timestamp_multiplier),
                    "10.0",
                    "12.0",
                    "9.0",
                    "11.0",
                    "123.5",
                    str((timestamp_ms + builder.BAR_MS - 1) * timestamp_multiplier),
                    *tail_fields,
                )
            )
        )
    assert len(records) == expected_rows - (1 if gap is not None else 0)
    filename = f"{symbol}-{builder.TIMEFRAME}-{month}.csv"
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(filename, "\n".join((*prefix_lines, *records)) + "\n")
    return output.getvalue()


def _valid_vendor_lock() -> dict:
    protocol_path = ROOT / builder.CANONICAL_PROTOCOL_RELATIVE
    builder_path = Path(builder.__file__).resolve()
    test_path = ROOT / builder.CANONICAL_TEST_RELATIVE
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    source = {
        "git": {"commit": commit, "clean": True, "status": []},
        "file_sha256": {
            builder.CANONICAL_PROTOCOL_RELATIVE: builder.sha256_file(protocol_path),
            str(builder_path.relative_to(ROOT)): builder.sha256_file(builder_path),
            builder.CANONICAL_TEST_RELATIVE: builder.sha256_file(test_path),
        },
        "runtime_versions": builder._runtime_versions(),
    }
    entries = []
    for expected in builder.expected_vendor_entries():
        vendor_sha = "a" * 64
        checksum_text = f"{vendor_sha}  {expected['filename']}\n"
        entries.append(
            {
                **expected,
                "vendor_sha256": vendor_sha,
                "checksum_text": checksum_text,
                "checksum_body_sha256": hashlib.sha256(checksum_text.encode()).hexdigest(),
                "checksum_body_bytes": len(checksum_text.encode()),
                "retrieved_at_utc": "2026-07-11T13:30:00+00:00",
                "http_attempts": 1,
                "final_url": expected["checksum_url"],
                "response_headers": {},
            }
        )
    return {
        "schema_version": builder.VENDOR_LOCK_SCHEMA,
        "source_kind": builder.SOURCE_KIND,
        "protocol_path": builder.CANONICAL_PROTOCOL_RELATIVE,
        "protocol_sha256": builder.sha256_file(protocol_path),
        "builder_path": str(builder_path.relative_to(ROOT)),
        "builder_sha256": builder.sha256_file(builder_path),
        "builder_test_path": builder.CANONICAL_TEST_RELATIVE,
        "builder_test_sha256": builder.sha256_file(test_path),
        "source_preflight": source,
        "source_postflight": deepcopy(source),
        "entry_count": len(entries),
        "ordered_by": ["SYMBOLS_declared_order", "month_ascending"],
        "entries": entries,
        "governance": {
            "kline_zip_downloaded_by_pin_phase": False,
            "kline_csv_opened_by_pin_phase": False,
            "strategy_or_performance_code_imported": False,
            "exchange_account_or_credentials_used": False,
        },
    }


def test_frozen_month_and_grid_identity() -> None:
    months = builder._month_range()
    assert months[0] == "2021-02"
    assert months[-1] == "2026-05"
    assert len(months) == 64
    assert len(builder.expected_vendor_entries()) == 896
    assert builder.ROWS_PER_SYMBOL == 184_896
    assert builder.TOTAL_ROWS == 2_588_544
    assert builder.ROWS_PER_SYMBOL * len(builder.SYMBOLS) == builder.TOTAL_ROWS


def test_expected_vendor_entries_are_ordered_and_usdm_only() -> None:
    entries = builder.expected_vendor_entries()
    assert entries[0]["symbol"] == "ETHUSDT"
    assert entries[0]["month"] == "2021-02"
    assert entries[-1]["symbol"] == "BTCUSDT"
    assert entries[-1]["month"] == "2026-05"
    assert all("/futures/um/monthly/klines/" in entry["zip_url"] for entry in entries)
    assert all("spot" not in entry["zip_url"] for entry in entries)
    assert len({entry["zip_url"] for entry in entries}) == len(entries)


def test_expected_key_hash_is_stable() -> None:
    assert (
        builder.expected_key_sha256()
        == "b1097799637634dff741bdbde77f83e340e98063e2ffb134e4d163abbe6d97fc"
    )


def test_parse_vendor_checksum_is_strict() -> None:
    digest = "a" * 64
    assert (
        builder.parse_vendor_checksum(
            f"{digest}  ETHUSDT-15m-2021-02.zip\n".encode(),
            expected_filename="ETHUSDT-15m-2021-02.zip",
        )
        == digest
    )
    with pytest.raises(builder.SnapshotBuildError, match="filename drift"):
        builder.parse_vendor_checksum(
            f"{digest}  BTCUSDT-15m-2021-02.zip\n".encode(),
            expected_filename="ETHUSDT-15m-2021-02.zip",
        )


def test_monthly_archive_parser_requires_complete_exact_grid() -> None:
    payload = _monthly_zip()
    rows, audit = builder.parse_monthly_archive(
        payload,
        symbol="ETHUSDT",
        month="2021-02",
        expected_filename="ETHUSDT-15m-2021-02.zip",
    )
    assert len(rows) == 2_688
    assert audit["rows"] == 2_688
    assert rows[0][1] == "ETH/USDT"
    assert rows[0][3] == datetime(2021, 2, 1, tzinfo=UTC)
    assert rows[-1][3] == datetime(2021, 2, 28, 23, 45, tzinfo=UTC)


def test_monthly_archive_parser_rejects_one_missing_real_bar() -> None:
    with pytest.raises(builder.SnapshotBuildError, match="monthly grid is incomplete"):
        builder.parse_monthly_archive(
            _monthly_zip(gap=17),
            symbol="ETHUSDT",
            month="2021-02",
            expected_filename="ETHUSDT-15m-2021-02.zip",
        )


@pytest.mark.parametrize(
    "payload",
    [
        _monthly_zip(prefix_lines=("arbitrary,preamble",)),
        _monthly_zip(timestamp_multiplier=1_000),
        _monthly_zip(tail_fields=("garbage", "x", "y", "z", "oops")),
    ],
)
def test_monthly_archive_parser_rejects_noncanonical_usdm_csv(payload: bytes) -> None:
    with pytest.raises(builder.SnapshotBuildError):
        builder.parse_monthly_archive(
            payload,
            symbol="ETHUSDT",
            month="2021-02",
            expected_filename="ETHUSDT-15m-2021-02.zip",
        )


def test_monthly_archive_parser_accepts_only_the_canonical_optional_header() -> None:
    rows, _audit = builder.parse_monthly_archive(
        _monthly_zip(prefix_lines=(",".join(builder.CANONICAL_CSV_HEADER),)),
        symbol="ETHUSDT",
        month="2021-02",
        expected_filename="ETHUSDT-15m-2021-02.zip",
    )
    assert len(rows) == 2_688


def test_monthly_archive_parser_rejects_wrong_member_path() -> None:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("nested/wrong.csv", "")
    with pytest.raises(builder.SnapshotBuildError, match="ZIP member drift"):
        builder.parse_monthly_archive(
            output.getvalue(),
            symbol="ETHUSDT",
            month="2021-02",
            expected_filename="ETHUSDT-15m-2021-02.zip",
        )


def test_cached_archive_must_match_vendor_hash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    filename = "ETHUSDT-15m-2021-02.zip"
    archive = tmp_path / filename
    archive.write_bytes(b"not-a-real-zip")
    entry = {
        "symbol": "ETHUSDT",
        "filename": filename,
        "zip_url": "https://example.invalid/archive.zip",
        "vendor_sha256": hashlib.sha256(b"different").hexdigest(),
    }
    monkeypatch.setattr(
        builder,
        "_http_get",
        lambda _url, **_kwargs: pytest.fail("network must not run"),
    )
    cache_dir_fd = builder._open_cache_directory(tmp_path)
    try:
        with pytest.raises(builder.SnapshotBuildError, match="cached vendor archive hash drifted"):
            builder._download_archive(
                entry,
                cache_root=tmp_path,
                cache_dir_fd=cache_dir_fd,
            )
    finally:
        builder.os.close(cache_dir_fd)


def test_cache_entry_symlink_cannot_escape_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cache = tmp_path / "cache"
    outside = tmp_path / "outside"
    cache.mkdir()
    outside.mkdir()
    filename = "ETHUSDT-15m-2021-02.zip"
    outside_file = outside / "archive.zip"
    outside_file.write_bytes(b"outside-must-remain-unchanged")
    (cache / filename).symlink_to(outside_file)
    entry = {
        "symbol": "ETHUSDT",
        "filename": filename,
        "zip_url": "https://example.invalid/archive.zip",
        "vendor_sha256": hashlib.sha256(b"body").hexdigest(),
    }
    monkeypatch.setattr(
        builder,
        "_http_get",
        lambda _url, **_kwargs: pytest.fail("network must not run"),
    )
    cache_dir_fd = builder._open_cache_directory(cache)
    try:
        with pytest.raises(builder.SnapshotBuildError, match="cannot safely open"):
            builder._download_archive(
                entry,
                cache_root=cache,
                cache_dir_fd=cache_dir_fd,
            )
    finally:
        builder.os.close(cache_dir_fd)
    assert outside_file.read_bytes() == b"outside-must-remain-unchanged"


def test_retained_cache_dir_fd_cannot_be_redirected_by_path_swap(tmp_path: Path) -> None:
    cache = tmp_path / "cache"
    displaced = tmp_path / "displaced"
    outside = tmp_path / "outside"
    cache.mkdir()
    outside.mkdir()
    cache_dir_fd = builder._open_cache_directory(cache)
    cache.rename(displaced)
    cache.symlink_to(outside, target_is_directory=True)
    filename = "ETHUSDT-15m-2021-02.zip"
    body = b"pinned-body"
    try:
        builder._write_cache_archive_at(cache_dir_fd, filename, body)
        assert (
            builder._read_verified_archive_at(
                cache_dir_fd,
                filename,
                expected_sha256=hashlib.sha256(body).hexdigest(),
            )
            == body
        )
    finally:
        builder.os.close(cache_dir_fd)
    assert (displaced / filename).read_bytes() == body
    assert list(outside.iterdir()) == []


def test_cache_tree_rejects_intermediate_symlink(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    (root / "data").symlink_to(outside, target_is_directory=True)
    with pytest.raises(builder.SnapshotBuildError, match="safely open directory tree"):
        builder._open_directory_tree_no_symlinks(
            root,
            "data/backups/cache",
            create=True,
        )
    assert list(outside.iterdir()) == []


def test_cached_archive_open_uses_nofollow_and_nonblock(tmp_path: Path) -> None:
    filename = "ETHUSDT-15m-2021-02.zip"
    body = b"archive"
    (tmp_path / filename).write_bytes(body)
    cache_dir_fd = builder._open_cache_directory(tmp_path)
    try:
        builder._read_verified_archive_at(
            cache_dir_fd,
            filename,
            expected_sha256=hashlib.sha256(body).hexdigest(),
        )
    finally:
        builder.os.close(cache_dir_fd)
    flags = builder._archive_read_flags()
    assert flags & builder.os.O_NOFOLLOW
    assert flags & builder.os.O_NONBLOCK


def test_strict_json_rejects_duplicate_keys(tmp_path: Path) -> None:
    path = tmp_path / "duplicate.json"
    path.write_text('{"a": 1, "a": 2}\n', encoding="utf-8")
    with pytest.raises(builder.SnapshotBuildError, match="duplicate JSON key"):
        builder.load_strict_json(path)


def test_strict_json_rejects_nonfinite_constants(tmp_path: Path) -> None:
    path = tmp_path / "nonfinite.json"
    path.write_text('{"value": NaN}\n', encoding="utf-8")
    with pytest.raises(builder.SnapshotBuildError, match="non-finite JSON"):
        builder.load_strict_json(path)


def test_atomic_writer_never_overwrites(tmp_path: Path) -> None:
    path = tmp_path / "evidence.json"
    builder.write_json_no_overwrite(path, {"ok": True})
    assert json.loads(path.read_text()) == {"ok": True}
    with pytest.raises(FileExistsError, match="refusing to overwrite"):
        builder.write_json_no_overwrite(path, {"ok": False})


def test_protocol_validation_rejects_critical_semantic_tampering() -> None:
    protocol = builder.load_strict_json(ROOT / builder.CANONICAL_PROTOCOL_RELATIVE)
    builder._validate_protocol(protocol, repo_root=ROOT)
    mutations = (
        (("status",), "TAMPERED_POST_RESULT"),
        (("builder_path",), "other.py"),
        (("source_selection", "failed_v1_snapshot_rows_reused"), True),
        (
            (
                "pre_protocol_access_disclosure",
                "signals_trades_returns_roi_drawdown_or_scenario_metrics_seen",
            ),
            True,
        ),
        (("two_phase_lock", "bulk_build_before_phase_2_commit_forbidden"), False),
        (("snapshot_qa", "read_only_post_close_reverification_required"), False),
        (("governance", "performance_results_seen"), True),
    )
    for path, value in mutations:
        changed = deepcopy(protocol)
        target = changed
        for key in path[:-1]:
            target = target[key]
        target[path[-1]] = value
        with pytest.raises(builder.SnapshotBuildError):
            builder._validate_protocol(changed, repo_root=ROOT)
    missing = deepcopy(protocol)
    missing.pop("predecessor_failure")
    with pytest.raises(builder.SnapshotBuildError, match="top-level fields"):
        builder._validate_protocol(missing, repo_root=ROOT)


def test_vendor_lock_validation_is_fail_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(builder, "_assert_phase_1_commit_identity", lambda *_args: None)
    lock = _valid_vendor_lock()
    protocol_hash = builder.sha256_file(ROOT / builder.CANONICAL_PROTOCOL_RELATIVE)
    validated = builder._validate_vendor_lock(
        lock,
        protocol_sha256=protocol_hash,
        repo_root=ROOT,
    )
    assert len(validated) == 896
    mutations = []
    wrong_source = deepcopy(lock)
    wrong_source["source_kind"] = "SPOT"
    mutations.append(wrong_source)
    wrong_governance = deepcopy(lock)
    wrong_governance["governance"]["kline_zip_downloaded_by_pin_phase"] = True
    mutations.append(wrong_governance)
    wrong_final_url = deepcopy(lock)
    wrong_final_url["entries"][0]["final_url"] = "https://example.invalid/redirect"
    mutations.append(wrong_final_url)
    wrong_checksum_body = deepcopy(lock)
    wrong_checksum_body["entries"][0]["checksum_body_sha256"] = "0" * 64
    mutations.append(wrong_checksum_body)
    for changed in mutations:
        with pytest.raises(builder.SnapshotBuildError):
            builder._validate_vendor_lock(
                changed,
                protocol_sha256=protocol_hash,
                repo_root=ROOT,
            )


@pytest.mark.subprocess
def test_phase_1_commit_identity_requires_exact_blobs_and_absent_lock(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Snapshot Test"], cwd=repo, check=True)
    relative = "protocol.json"
    payload = b'{"phase": 1}\n'
    (repo / relative).write_bytes(payload)
    subprocess.run(["git", "add", relative], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "phase 1"], cwd=repo, check=True)
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    expected = {relative: hashlib.sha256(payload).hexdigest()}
    builder._assert_phase_1_commit_identity(repo, commit, expected)
    with pytest.raises(builder.SnapshotBuildError, match="blob hash drifted"):
        builder._assert_phase_1_commit_identity(repo, commit, {relative: "0" * 64})

    lock = repo / builder.CANONICAL_VENDOR_LOCK_RELATIVE
    lock.parent.mkdir(parents=True)
    lock.write_text("{}\n", encoding="utf-8")
    subprocess.run(["git", "add", str(lock.relative_to(repo))], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "add lock"], cwd=repo, check=True)
    lock_commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    with pytest.raises(builder.SnapshotBuildError, match="already existed"):
        builder._assert_phase_1_commit_identity(repo, lock_commit, expected)


def test_http_get_rejects_redirect_and_oversized_declared_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeResponse:
        status = 200

        def __init__(self, *, final_url: str, headers: dict[str, str]) -> None:
            self._final_url = final_url
            self.headers = headers

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def geturl(self) -> str:
            return self._final_url

        def read(self, _size: int) -> bytes:
            return b""

    monkeypatch.setattr(builder, "HTTP_RETRIES", 1)
    url = "https://data.binance.vision/exact"
    monkeypatch.setattr(
        builder.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: FakeResponse(
            final_url="https://example.invalid/redirect", headers={}
        ),
    )
    with pytest.raises(builder.SnapshotBuildError, match="redirect"):
        builder._http_get(url, max_bytes=100)
    monkeypatch.setattr(
        builder.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: FakeResponse(final_url=url, headers={"Content-Length": "101"}),
    )
    with pytest.raises(builder.SnapshotBuildError, match="Content-Length"):
        builder._http_get(url, max_bytes=100)


def test_atomic_bundle_publishes_database_and_evidence_together(tmp_path: Path) -> None:
    staging = tmp_path / ".bundle.building"
    final = tmp_path / "bundle"
    staging.mkdir()
    (staging / "market.duckdb").write_bytes(b"db")
    (staging / "build_evidence.json").write_text('{"status":"SUCCESS"}\n')
    builder._publish_bundle_atomic(staging, final)
    assert not staging.exists()
    assert (final / "market.duckdb").read_bytes() == b"db"
    assert json.loads((final / "build_evidence.json").read_text())["status"] == "SUCCESS"
    with pytest.raises(FileExistsError):
        builder._publish_bundle_atomic(tmp_path / "missing", final)
    assert (final / "market.duckdb").read_bytes() == b"db"
    assert json.loads((final / "build_evidence.json").read_text())["status"] == "SUCCESS"


def test_atomic_bundle_publish_loses_race_without_replacing_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    staging = tmp_path / ".bundle.building"
    final = tmp_path / "bundle"
    staging.mkdir()
    (staging / "market.duckdb").write_bytes(b"candidate")
    actual_rename = builder._rename_exclusive_at
    competing_inode: list[int] = []

    def create_competing_target(parent_dir_fd: int, source: str, destination: str) -> None:
        final.mkdir()
        competing_inode.append(final.stat().st_ino)
        actual_rename(parent_dir_fd, source, destination)

    monkeypatch.setattr(builder, "_rename_exclusive_at", create_competing_target)
    with pytest.raises(FileExistsError):
        builder._publish_bundle_atomic(staging, final)
    assert competing_inode and final.stat().st_ino == competing_inode[0]
    assert list(final.iterdir()) == []
    assert (staging / "market.duckdb").read_bytes() == b"candidate"


def test_staging_io_and_cleanup_remain_bound_to_retained_directory_fd(tmp_path: Path) -> None:
    parent = tmp_path / "backups"
    displaced = tmp_path / "displaced"
    outside = tmp_path / "outside"
    parent.mkdir()
    outside.mkdir()
    parent_dir_fd = builder._open_cache_directory(parent)
    staging_name, staging_dir_fd = builder._create_staging_directory_at(
        parent_dir_fd,
        final_name="bundle",
    )
    parent.rename(displaced)
    parent.symlink_to(outside, target_is_directory=True)
    try:
        with builder._working_directory_fd(staging_dir_fd):
            connection = builder._create_snapshot_db(
                Path("market.duckdb"),
                {"source_kind": builder.SOURCE_KIND},
            )
            connection.close()
            Path("build_evidence.json").write_text("{}\n", encoding="utf-8")
        assert (displaced / staging_name / "market.duckdb").is_file()
        assert (displaced / staging_name / "build_evidence.json").is_file()
        assert list(outside.iterdir()) == []
        builder._remove_staging_directory_at(
            parent_dir_fd,
            staging_dir_fd,
            staging_name,
        )
        assert not (displaced / staging_name).exists()
    finally:
        builder.os.close(staging_dir_fd)
        builder.os.close(parent_dir_fd)


def test_publish_rejects_staging_name_swap(tmp_path: Path) -> None:
    parent = tmp_path / "backups"
    parent.mkdir()
    parent_dir_fd = builder._open_cache_directory(parent)
    staging_name, staging_dir_fd = builder._create_staging_directory_at(
        parent_dir_fd,
        final_name="bundle",
    )
    staging = parent / staging_name
    displaced_good = parent / "displaced-good"
    (staging / "identity.txt").write_text("GOOD", encoding="utf-8")
    staging.rename(displaced_good)
    staging.mkdir()
    (staging / "identity.txt").write_text("BAD", encoding="utf-8")
    try:
        with pytest.raises(builder.SnapshotBuildError, match="retained inode"):
            builder._publish_bundle_atomic(
                staging,
                parent / "bundle",
                parent_dir_fd=parent_dir_fd,
                staging_dir_fd=staging_dir_fd,
            )
        assert not (parent / "bundle").exists()
        assert (displaced_good / "identity.txt").read_text(encoding="utf-8") == "GOOD"
        assert (staging / "identity.txt").read_text(encoding="utf-8") == "BAD"
    finally:
        builder.os.close(staging_dir_fd)
        builder.os.close(parent_dir_fd)


def test_publish_rejects_parent_path_inode_swap(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    parent = root / "data" / "backups"
    displaced_parent = root / "data" / "displaced-backups"
    parent.mkdir(parents=True)
    parent_dir_fd = builder._open_directory_tree_no_symlinks(
        root,
        "data/backups",
        create=False,
    )
    staging_name, staging_dir_fd = builder._create_staging_directory_at(
        parent_dir_fd,
        final_name="bundle",
    )
    (parent / staging_name / "identity.txt").write_text("GOOD", encoding="utf-8")
    parent.rename(displaced_parent)
    parent.mkdir()
    try:
        with pytest.raises(builder.SnapshotBuildError, match="retained inode"):
            builder._publish_bundle_atomic(
                parent / staging_name,
                parent / "bundle",
                parent_dir_fd=parent_dir_fd,
                staging_dir_fd=staging_dir_fd,
                identity_root=root,
                identity_relative="data/backups",
            )
        assert not (parent / "bundle").exists()
        assert not (displaced_parent / "bundle").exists()
        assert (displaced_parent / staging_name / "identity.txt").read_text(
            encoding="utf-8"
        ) == "GOOD"
    finally:
        builder.os.close(staging_dir_fd)
        builder.os.close(parent_dir_fd)


def test_post_rename_mismatch_does_not_move_competitor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    parent = tmp_path / "backups"
    parent.mkdir()
    staging = parent / ".bundle.building"
    final = parent / "bundle"
    displaced_good = parent / "displaced-good"
    staging.mkdir()
    (staging / "identity.txt").write_text("GOOD", encoding="utf-8")
    parent_dir_fd = builder._open_cache_directory(parent)
    staging_dir_fd = builder._open_cache_directory(staging)
    actual_rename = builder._rename_exclusive_at

    def replace_after_publish(parent_fd: int, source: str, destination: str) -> None:
        actual_rename(parent_fd, source, destination)
        if source == staging.name and destination == final.name:
            final.rename(displaced_good)
            final.mkdir()
            (final / "identity.txt").write_text("COMPETITOR", encoding="utf-8")

    monkeypatch.setattr(builder, "_rename_exclusive_at", replace_after_publish)
    try:
        with pytest.raises(builder.BundlePublicationError) as captured:
            builder._publish_bundle_atomic(
                staging,
                final,
                parent_dir_fd=parent_dir_fd,
                staging_dir_fd=staging_dir_fd,
            )
        assert captured.value.publication_state == "RETAINED_INODE_NOT_VISIBLE_AT_FINAL_NAME"
        assert (final / "identity.txt").read_text(encoding="utf-8") == "COMPETITOR"
        assert (displaced_good / "identity.txt").read_text(encoding="utf-8") == "GOOD"
        assert not staging.exists()
    finally:
        builder.os.close(staging_dir_fd)
        builder.os.close(parent_dir_fd)


def test_post_rename_fsync_failure_never_rolls_back_by_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    parent = tmp_path / "backups"
    parent.mkdir()
    staging = parent / ".bundle.building"
    final = parent / "bundle"
    staging.mkdir()
    (staging / "identity.txt").write_text("GOOD", encoding="utf-8")
    parent_dir_fd = builder._open_cache_directory(parent)
    staging_dir_fd = builder._open_cache_directory(staging)
    actual_fsync = builder.os.fsync

    def fail_parent_fsync(descriptor: int) -> None:
        if descriptor == parent_dir_fd:
            raise OSError("injected parent fsync failure")
        actual_fsync(descriptor)

    monkeypatch.setattr(builder.os, "fsync", fail_parent_fsync)
    try:
        with pytest.raises(builder.BundlePublicationError) as captured:
            builder._publish_bundle_atomic(
                staging,
                final,
                parent_dir_fd=parent_dir_fd,
                staging_dir_fd=staging_dir_fd,
            )
        assert captured.value.publication_state == "VISIBLE_RETAINED_INODE_DURABILITY_UNCONFIRMED"
        assert not staging.exists()
        assert (final / "identity.txt").read_text(encoding="utf-8") == "GOOD"
    finally:
        builder.os.close(staging_dir_fd)
        builder.os.close(parent_dir_fd)


@pytest.mark.parametrize(
    ("state", "expected"),
    [
        ("NOT_RENAMED", False),
        ("RETAINED_INODE_NOT_VISIBLE_AT_FINAL_NAME", False),
        ("VISIBLE_RETAINED_INODE_DURABILITY_UNCONFIRMED", True),
        ("VISIBLE_RETAINED_INODE_DURABILITY_CONFIRMED", True),
        ("FINAL_VISIBILITY_UNKNOWN_AFTER_ATOMIC_RENAME", None),
    ],
)
def test_publication_confirmation_is_truthful(state: str, expected: bool | None) -> None:
    assert builder._publication_confirmation(state) is expected
    with pytest.raises(builder.SnapshotBuildError, match="unknown publication state"):
        builder._publication_confirmation("UNRECOGNIZED")


def test_snapshot_schema_primary_key_and_metadata(tmp_path: Path) -> None:
    path = tmp_path / "snapshot.duckdb"
    connection = builder._create_snapshot_db(path, {"source_kind": builder.SOURCE_KIND})
    row = (
        "binance",
        "ETH/USDT",
        "15m",
        datetime(2021, 2, 21, tzinfo=UTC),
        10.0,
        12.0,
        9.0,
        11.0,
        1.0,
    )
    connection.execute("INSERT INTO ohlcv VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", row)
    with pytest.raises(duckdb.ConstraintException):
        connection.execute("INSERT INTO ohlcv VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", row)
    assert (
        connection.execute(
            "SELECT value FROM snapshot_metadata WHERE key='source_kind'"
        ).fetchone()[0]
        == builder.SOURCE_KIND
    )
    connection.close()


def test_reserved_duckdb_path_is_absent_and_initializable(tmp_path: Path) -> None:
    path = builder._reserve_duckdb_path(tmp_path, output_name="snapshot.duckdb")
    assert not path.exists()
    connection = builder._create_snapshot_db(path, {"source_kind": builder.SOURCE_KIND})
    connection.close()
    assert path.is_file()


def test_post_close_qa_reopens_database_read_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "snapshot.duckdb"
    connection = builder._create_snapshot_db(path, {"source_kind": builder.SOURCE_KIND})
    connection.close()

    def prove_read_only(connection: duckdb.DuckDBPyConnection) -> dict[str, bool]:
        with pytest.raises(duckdb.Error):
            connection.execute("CREATE TABLE forbidden_write(value INTEGER)")
        return {"read_only": True}

    monkeypatch.setattr(builder, "_validate_snapshot_db", prove_read_only)
    assert builder._read_only_post_close_qa(path) == {"read_only": True}


def test_builder_is_strategy_and_live_database_isolated() -> None:
    source = Path(builder.__file__).read_text(encoding="utf-8")
    forbidden_imports = (
        "price_action.lab.crypto_15m_v15p2",
        "price_action.strategies",
        "price_action.risk",
        "price_action.execution",
        "OHLCVStore",
        "ccxt",
    )
    assert all(item not in source for item in forbidden_imports)
    assert "data/futures/um/monthly/klines" in source
    assert builder.CANONICAL_OUTPUT_RELATIVE != "data/market.duckdb"


def test_month_bounds_cover_every_15m_bar() -> None:
    start_ms, end_ms, rows = builder._month_bounds("2024-02")
    assert rows == 29 * 96
    assert end_ms - start_ms == rows * builder.BAR_MS
    assert datetime.fromtimestamp(start_ms / 1000, tz=UTC) + timedelta(minutes=15 * rows) == (
        datetime.fromtimestamp(end_ms / 1000, tz=UTC)
    )
