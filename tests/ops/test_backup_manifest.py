from __future__ import annotations

import os
import stat
import subprocess
import sys
import time
from pathlib import Path

import duckdb
import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "backup_duckdb.sh"
pytestmark = pytest.mark.subprocess


def test_backup_signal_traps_exit_before_mutex_cleanup() -> None:
    script = SCRIPT.read_text(encoding="utf-8")

    assert "trap _cleanup_stage EXIT\n" in script
    assert "trap 'exit 130' INT" in script
    assert "trap 'exit 143' TERM" in script
    assert "trap _cleanup_stage EXIT INT TERM" not in script


def _db(path: Path, values: list[int]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(path))
    try:
        con.execute("CREATE TABLE evidence(value INTEGER)")
        con.executemany("INSERT INTO evidence VALUES (?)", [(value,) for value in values])
        con.execute("CHECKPOINT")
    finally:
        con.close()


def _values(path: Path) -> list[int]:
    con = duckdb.connect(str(path), read_only=True)
    try:
        return [
            row[0] for row in con.execute("SELECT value FROM evidence ORDER BY value").fetchall()
        ]
    finally:
        con.close()


def _run_backup(
    project: Path, *, path_prefix: Path | None = None
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.update(
        {
            "PA_PROJECT_ROOT": str(project),
            "PA_BACKUP_RETENTION_DAYS": "3",
            "PA_PYTHON_BIN": sys.executable,
        }
    )
    if path_prefix is not None:
        env["PATH"] = f"{path_prefix}:{env['PATH']}"
    return subprocess.run(
        ["bash", str(SCRIPT)], capture_output=True, text=True, check=False, env=env
    )


def test_backup_writes_verifiable_destination_checksum_manifest(tmp_path: Path) -> None:
    data = tmp_path / "data"
    data.mkdir()
    _db(data / "alpha.duckdb", [1, 2, 3])

    result = _run_backup(tmp_path)

    assert result.returncode == 0, result.stdout + result.stderr
    destination = data / "backups" / time.strftime("%Y%m%d")
    manifest = destination / "backup_manifest.sha256"
    assert manifest.is_file()
    manifest_text = manifest.read_text(encoding="utf-8")
    assert "alpha.duckdb" in manifest_text
    assert ".wal" not in manifest_text
    assert not (destination / "alpha.duckdb.wal").exists()
    assert _values(destination / "alpha.duckdb") == [1, 2, 3]
    assert "mode=staged-copy-checkpoint wal=none" in result.stdout
    verified = subprocess.run(
        ["shasum", "-a", "256", "-c", manifest.name],
        cwd=destination,
        capture_output=True,
        text=True,
        check=False,
    )
    assert verified.returncode == 0, verified.stdout + verified.stderr

    (destination / "alpha.duckdb").write_bytes(b"tampered")
    tampered = subprocess.run(
        ["shasum", "-a", "256", "-c", manifest.name],
        cwd=destination,
        capture_output=True,
        text=True,
        check=False,
    )
    assert tampered.returncode != 0
    assert not (data / "backups" / ".backup_duckdb.lock").exists()


def test_backup_refuses_existing_single_writer_lock_without_publishing(
    tmp_path: Path,
) -> None:
    data = tmp_path / "data"
    data.mkdir()
    _db(data / "alpha.duckdb", [1])
    backup_root = data / "backups"
    lock = backup_root / ".backup_duckdb.lock"
    lock.mkdir(parents=True)
    (lock / "pid").write_text("424242\n", encoding="utf-8")

    result = _run_backup(tmp_path)

    assert result.returncode == 3
    assert "başka backup çalışıyor veya stale lock var" in result.stdout
    assert (lock / "pid").read_text(encoding="utf-8") == "424242\n"
    assert not (backup_root / time.strftime("%Y%m%d")).exists()


def test_backup_replays_abandoned_wal_into_self_contained_snapshot(tmp_path: Path) -> None:
    data = tmp_path / "data"
    data.mkdir()
    source = data / "wal_source.duckdb"
    crashed_writer = """
import os
import sys
import duckdb

con = duckdb.connect(sys.argv[1])
con.execute("CREATE TABLE evidence(value INTEGER)")
con.execute("CHECKPOINT")
con.execute("INSERT INTO evidence VALUES (41), (42)")
os._exit(0)
"""
    writer = subprocess.run(
        [sys.executable, "-c", crashed_writer, str(source)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert writer.returncode == 0, writer.stdout + writer.stderr
    assert Path(f"{source}.wal").is_file()

    result = _run_backup(tmp_path)

    assert result.returncode == 0, result.stdout + result.stderr
    destination = data / "backups" / time.strftime("%Y%m%d")
    snapshot = destination / source.name
    assert _values(snapshot) == [41, 42]
    assert not Path(f"{snapshot}.wal").exists()


def test_backup_snapshots_source_held_by_live_writer(tmp_path: Path) -> None:
    data = tmp_path / "data"
    data.mkdir()
    source = data / "live_writer.duckdb"
    ready = tmp_path / "writer.ready"
    writer_script = """
import sys
import time
from pathlib import Path

import duckdb

con = duckdb.connect(sys.argv[1])
con.execute("CREATE TABLE evidence(value INTEGER)")
con.execute("CHECKPOINT")
con.execute("INSERT INTO evidence VALUES (73), (74)")
Path(sys.argv[2]).write_text("ready", encoding="utf-8")
time.sleep(30)
con.close()
"""
    writer = subprocess.Popen(
        [sys.executable, "-c", writer_script, str(source), str(ready)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        deadline = time.monotonic() + 10
        while not ready.exists() and writer.poll() is None and time.monotonic() < deadline:
            time.sleep(0.05)
        assert ready.exists(), writer.communicate(timeout=1)

        result = _run_backup(tmp_path)

        assert result.returncode == 0, result.stdout + result.stderr
        destination = data / "backups" / time.strftime("%Y%m%d")
        assert _values(destination / source.name) == [73, 74]
        assert not (destination / f"{source.name}.wal").exists()
    finally:
        writer.terminate()
        try:
            writer.wait(timeout=5)
        except subprocess.TimeoutExpired:
            writer.kill()
            writer.wait(timeout=5)


def test_backup_logs_open_source_but_publishes_verified_stage(tmp_path: Path) -> None:
    data = tmp_path / "data"
    data.mkdir()
    _db(data / "alpha.duckdb", [1])
    destination = data / "backups" / time.strftime("%Y%m%d")
    destination.mkdir(parents=True)
    sentinel = destination / "previous-good.txt"
    sentinel.write_text("keep", encoding="utf-8")

    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir()
    fake_lsof = fake_bin / "lsof"
    fake_lsof.write_text("#!/bin/sh\necho 9876\nexit 0\n", encoding="utf-8")
    fake_lsof.chmod(fake_lsof.stat().st_mode | stat.S_IXUSR)

    result = _run_backup(tmp_path, path_prefix=fake_bin)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "BACKUP_SOURCE_OPEN" in result.stdout
    assert not sentinel.exists()
    assert _values(destination / "alpha.duckdb") == [1]
    assert not list((data / "backups").glob(".*.stage.*"))


def test_same_day_rerun_does_not_publish_stale_db_or_wal(tmp_path: Path) -> None:
    data = tmp_path / "data"
    data.mkdir()
    _db(data / "alpha.duckdb", [7])
    destination = data / "backups" / time.strftime("%Y%m%d")
    destination.mkdir(parents=True)
    (destination / "obsolete.duckdb").write_bytes(b"old")
    (destination / "obsolete.duckdb.wal").write_bytes(b"old-wal")
    (destination / "backup_manifest.sha256").write_text("legacy manifest\n", encoding="utf-8")

    result = _run_backup(tmp_path)

    assert result.returncode == 0, result.stdout + result.stderr
    assert sorted(path.name for path in destination.iterdir()) == [
        "alpha.duckdb",
        "backup_manifest.sha256",
    ]
    assert "obsolete" not in (destination / "backup_manifest.sha256").read_text(encoding="utf-8")


def test_source_checkpoint_between_db_and_wal_copy_preserves_published_backup(
    tmp_path: Path,
) -> None:
    data = tmp_path / "data"
    data.mkdir()
    source = data / "checkpoint_race.duckdb"
    crashed_writer = """
import os
import sys
import duckdb

con = duckdb.connect(sys.argv[1])
con.execute("CREATE TABLE evidence(value INTEGER)")
con.execute("CHECKPOINT")
con.execute("INSERT INTO evidence VALUES (91)")
os._exit(0)
"""
    writer = subprocess.run(
        [sys.executable, "-c", crashed_writer, str(source)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert writer.returncode == 0, writer.stdout + writer.stderr
    assert Path(f"{source}.wal").is_file()

    destination = data / "backups" / time.strftime("%Y%m%d")
    destination.mkdir(parents=True)
    sentinel = destination / "previous-good.txt"
    sentinel.write_text("keep", encoding="utf-8")

    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir()
    marker = tmp_path / "checkpoint-triggered"
    fake_cp = fake_bin / "cp"
    fake_cp.write_text(
        "\n".join(
            [
                "#!/bin/sh",
                '/bin/cp "$@" || exit $?',
                'src="$2"',
                f"if [ \"$src\" = '{source}' ] && [ ! -e '{marker}' ]; then",
                f"  '{sys.executable}' -c 'import duckdb,sys; c=duckdb.connect(sys.argv[1]); c.execute(\"CHECKPOINT\"); c.close()' \"$src\" || exit $?",
                f"  : > '{marker}'",
                "fi",
                "exit 0",
                "",
            ]
        ),
        encoding="utf-8",
    )
    fake_cp.chmod(fake_cp.stat().st_mode | stat.S_IXUSR)
    env = os.environ.copy()
    env.update(
        {
            "PA_PROJECT_ROOT": str(tmp_path),
            "PA_BACKUP_RETENTION_DAYS": "3",
            "PA_BACKUP_SNAPSHOT_RETRIES": "1",
            "PA_PYTHON_BIN": sys.executable,
            "PATH": f"{fake_bin}:{env['PATH']}",
        }
    )

    result = subprocess.run(
        ["bash", str(SCRIPT)], capture_output=True, text=True, check=False, env=env
    )

    assert marker.is_file()
    assert result.returncode == 1
    assert "SOURCE_PAIR_CHANGED" in result.stdout
    assert sentinel.read_text(encoding="utf-8") == "keep"
    assert not list((data / "backups").glob(".*.stage.*"))


def test_invalid_source_preserves_last_published_set(tmp_path: Path) -> None:
    data = tmp_path / "data"
    data.mkdir()
    (data / "broken.duckdb").write_bytes(b"not-a-duckdb")
    destination = data / "backups" / time.strftime("%Y%m%d")
    destination.mkdir(parents=True)
    sentinel = destination / "previous-good.txt"
    sentinel.write_text("keep", encoding="utf-8")

    env = os.environ.copy()
    env.update(
        {
            "PA_PROJECT_ROOT": str(tmp_path),
            "PA_BACKUP_RETENTION_DAYS": "3",
            "PA_BACKUP_SNAPSHOT_RETRIES": "1",
            "PA_PYTHON_BIN": sys.executable,
        }
    )
    result = subprocess.run(
        ["bash", str(SCRIPT)], capture_output=True, text=True, check=False, env=env
    )

    assert result.returncode == 1
    assert "BACKUP_ABORT: snapshot 1 denemede" in result.stdout
    assert sentinel.read_text(encoding="utf-8") == "keep"
    assert not list((data / "backups").glob(".*.stage.*"))
