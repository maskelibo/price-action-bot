from __future__ import annotations

import hashlib
import os
import stat
import subprocess
import sys
from pathlib import Path

import duckdb
import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "restore_duckdb.sh"
pytestmark = pytest.mark.subprocess


def _write_tool(bin_dir: Path, name: str, body: str) -> None:
    path = bin_dir / name
    path.write_text("#!/bin/sh\n" + body + "\n", encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def _tools(tmp_path: Path, *, launchctl: str = "exit 1", lsof: str = "exit 1") -> Path:
    bin_dir = tmp_path / "fake-bin"
    bin_dir.mkdir()
    _write_tool(bin_dir, "launchctl", launchctl)
    _write_tool(bin_dir, "lsof", lsof)
    return bin_dir


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


def _run(
    project: Path,
    bin_dir: Path,
    *args: str,
    answer: str = "yes\n",
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.update(
        {
            "PA_PROJECT_ROOT": str(project),
            "PA_PYTHON_BIN": sys.executable,
            "PATH": f"{bin_dir}:/usr/bin:/bin:/usr/sbin",
        }
    )
    return subprocess.run(
        ["bash", str(SCRIPT), *args],
        input=answer,
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )


def test_restore_stages_verifies_replaces_and_removes_stale_active_wal(tmp_path: Path) -> None:
    project = tmp_path / "project"
    active = project / "data" / "sample.duckdb"
    backup = project / "data" / "backups" / "20260711" / "sample.duckdb"
    _db(active, [1])
    _db(backup, [7, 8])
    (backup.parent / "backup_manifest.sha256").write_text(
        f"{hashlib.sha256(backup.read_bytes()).hexdigest()}  {backup.name}\n",
        encoding="utf-8",
    )
    active.with_suffix(".duckdb.wal").write_bytes(b"stale-active-wal")

    result = _run(project, _tools(tmp_path), "sample.duckdb", "20260711")

    assert result.returncode == 0, result.stdout + result.stderr
    assert _values(active) == [7, 8]
    assert not active.with_suffix(".duckdb.wal").exists()
    rollback_files = list(active.parent.glob("sample.duckdb.before_restore.*"))
    assert len([p for p in rollback_files if not p.name.endswith(".wal")]) == 1
    assert "INTEGRITY_OK tables=1 rows_total=2" in result.stdout
    assert "RESTORE_CHECKSUM_OK" in result.stdout
    assert "RESTORE_RESTART_NONE" in result.stdout
    assert "com.priceaction.futures_v15p2.plist" not in result.stdout


def test_restore_when_active_db_did_not_exist_has_no_unbound_rollback_variable(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    active = project / "data" / "new.duckdb"
    backup = project / "data" / "backups" / "20260711" / "new.duckdb"
    _db(backup, [3])

    result = _run(project, _tools(tmp_path), "new.duckdb", "20260711")

    assert result.returncode == 0, result.stdout + result.stderr
    assert _values(active) == [3]
    assert "restore öncesinde yoktu" in result.stdout
    assert "unbound variable" not in result.stderr


@pytest.mark.parametrize(
    "label",
    [
        "com.priceaction.futures_v14",
        "com.priceaction.futures15m",
        "com.priceaction.futures15m_v11",
        "com.priceaction.futures15m_v63",
        "com.priceaction.futures5m",
    ],
)
def test_restore_refuses_loaded_retired_or_v14_job_before_touching_active_db(
    tmp_path: Path, label: str
) -> None:
    project = tmp_path / "project"
    active = project / "data" / "sample.duckdb"
    backup = project / "data" / "backups" / "20260711" / "sample.duckdb"
    _db(active, [1])
    _db(backup, [9])
    launchctl = f'case "$*" in *{label}*) exit 0;; *) exit 1;; esac'

    result = _run(
        project,
        _tools(tmp_path, launchctl=launchctl),
        "sample.duckdb",
        "20260711",
    )

    assert result.returncode == 4
    assert label in result.stdout + result.stderr
    assert _values(active) == [1]


def test_restore_restarts_exact_captured_supported_label_set(tmp_path: Path) -> None:
    project = tmp_path / "project"
    active = project / "data" / "sample.duckdb"
    backup = project / "data" / "backups" / "20260711" / "sample.duckdb"
    _db(active, [1])
    _db(backup, [9])
    state_dir = tmp_path / "launch-state"
    state_dir.mkdir()
    commands = tmp_path / "launch-commands"
    captured = [
        "com.priceaction.ceo",
        "com.priceaction.e13_shadow_tick",
    ]
    for label in captured:
        plist = tmp_path / f"{label}.plist"
        plist.write_text("fixture\n", encoding="utf-8")
        (state_dir / label).write_text(str(plist), encoding="utf-8")
    launchctl = f"""
state_dir='{state_dir}'
commands='{commands}'
echo "$*" >> "$commands"
case "$1" in
  print)
    label="${{2##*/}}"
    [ -f "$state_dir/$label" ] || exit 1
    echo "path = $(cat "$state_dir/$label")"
    ;;
  bootout)
    label="${{2##*/}}"
    rm -f "$state_dir/$label"
    ;;
  bootstrap)
    plist="$3"
    label=$(basename "$plist" .plist)
    echo "$plist" > "$state_dir/$label"
    ;;
  *) exit 2 ;;
esac
exit 0
"""

    result = _run(
        project,
        _tools(tmp_path, launchctl=launchctl),
        "sample.duckdb",
        "20260711",
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert _values(active) == [9]
    command_lines = commands.read_text(encoding="utf-8").splitlines()
    bootouts = [line for line in command_lines if line.startswith("bootout ")]
    bootstraps = [line for line in command_lines if line.startswith("bootstrap ")]
    assert len(bootouts) == len(captured)
    assert len(bootstraps) == len(captured)
    for label in captured:
        assert any(line.endswith(f"/{label}") for line in bootouts)
        assert any(line.endswith(f"/{label}.plist") for line in bootstraps)
        assert (state_dir / label).is_file()
    assert not any("futures_v15p2.plist" in line for line in bootstraps)
    assert "RESTORE_PRE_ACTIVE_CAPTURED" in result.stdout


def test_restore_fails_visible_when_loaded_supported_job_plist_is_missing(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    active = project / "data" / "sample.duckdb"
    backup = project / "data" / "backups" / "20260711" / "sample.duckdb"
    _db(active, [1])
    _db(backup, [9])
    label = "com.priceaction.forward_sim"
    launchctl = f"""
case "$1:$2" in
  print:*/{label}) echo 'path = {tmp_path}/missing.plist'; exit 0 ;;
  bootout:*) echo unexpected-bootout >&2; exit 99 ;;
  *) exit 1 ;;
esac
"""

    result = _run(
        project,
        _tools(tmp_path, launchctl=launchctl),
        "sample.duckdb",
        "20260711",
    )

    assert result.returncode == 4
    assert "plist yolu eksik/geçersiz" in result.stdout
    assert label in result.stdout
    assert "unexpected-bootout" not in result.stderr
    assert _values(active) == [1]


def test_restore_refuses_open_lsof_holder(tmp_path: Path) -> None:
    project = tmp_path / "project"
    active = project / "data" / "sample.duckdb"
    backup = project / "data" / "backups" / "20260711" / "sample.duckdb"
    _db(active, [1])
    _db(backup, [9])

    result = _run(
        project,
        _tools(tmp_path, lsof="echo 4321; exit 0"),
        "sample.duckdb",
        "20260711",
    )

    assert result.returncode == 4
    assert "açık dosya" in result.stdout + result.stderr
    assert _values(active) == [1]


def test_corrupt_backup_fails_integrity_without_touching_active(tmp_path: Path) -> None:
    project = tmp_path / "project"
    active = project / "data" / "sample.duckdb"
    backup = project / "data" / "backups" / "20260711" / "sample.duckdb"
    _db(active, [1])
    backup.parent.mkdir(parents=True)
    backup.write_bytes(b"not-a-duckdb")

    result = _run(project, _tools(tmp_path), "sample.duckdb", "20260711")

    assert result.returncode == 5
    assert "staged integrity fail" in result.stdout
    assert _values(active) == [1]


def test_checksum_mismatch_fails_before_service_or_active_db_checks(tmp_path: Path) -> None:
    project = tmp_path / "project"
    active = project / "data" / "sample.duckdb"
    backup = project / "data" / "backups" / "20260711" / "sample.duckdb"
    _db(active, [1])
    _db(backup, [9])
    (backup.parent / "backup_manifest.sha256").write_text(
        f"{'0' * 64}  sample.duckdb\n", encoding="utf-8"
    )

    result = _run(project, _tools(tmp_path), "sample.duckdb", "20260711")

    assert result.returncode == 5
    assert "checksum mismatch" in result.stdout
    assert _values(active) == [1]


def test_manifest_listed_wal_missing_fails_before_touching_active(tmp_path: Path) -> None:
    project = tmp_path / "project"
    active = project / "data" / "sample.duckdb"
    backup = project / "data" / "backups" / "20260711" / "sample.duckdb"
    _db(active, [1])
    _db(backup, [9])
    (backup.parent / "backup_manifest.sha256").write_text(
        "\n".join(
            [
                f"{hashlib.sha256(backup.read_bytes()).hexdigest()}  sample.duckdb",
                f"{'a' * 64}  sample.duckdb.wal",
                "",
            ]
        ),
        encoding="utf-8",
    )

    result = _run(project, _tools(tmp_path), "sample.duckdb", "20260711")

    assert result.returncode == 5
    assert "manifestte listelenen WAL eksik" in result.stdout
    assert _values(active) == [1]


def test_manifest_listed_wal_is_verified_and_replayed(tmp_path: Path) -> None:
    project = tmp_path / "project"
    active = project / "data" / "sample.duckdb"
    backup = project / "data" / "backups" / "20260711" / "sample.duckdb"
    _db(active, [1])
    _db(backup, [7])
    crashed_writer = """
import os
import sys
import duckdb

con = duckdb.connect(sys.argv[1])
con.execute("INSERT INTO evidence VALUES (8)")
os._exit(0)
"""
    writer = subprocess.run(
        [sys.executable, "-c", crashed_writer, str(backup)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert writer.returncode == 0, writer.stdout + writer.stderr
    wal = Path(f"{backup}.wal")
    assert wal.is_file()
    (backup.parent / "backup_manifest.sha256").write_text(
        "\n".join(
            [
                f"{hashlib.sha256(backup.read_bytes()).hexdigest()}  sample.duckdb",
                f"{hashlib.sha256(wal.read_bytes()).hexdigest()}  sample.duckdb.wal",
                "",
            ]
        ),
        encoding="utf-8",
    )

    result = _run(project, _tools(tmp_path), "sample.duckdb", "20260711")

    assert result.returncode == 0, result.stdout + result.stderr
    assert _values(active) == [7, 8]
    assert "RESTORE_CHECKSUM_OK" in result.stdout
    assert not Path(f"{active}.wal").exists()


def test_restore_rechecks_lsof_after_staging_before_atomic_replace(tmp_path: Path) -> None:
    project = tmp_path / "project"
    active = project / "data" / "sample.duckdb"
    backup = project / "data" / "backups" / "20260711" / "sample.duckdb"
    _db(active, [1])
    _db(backup, [9])
    state_file = tmp_path / "lsof-count"
    lsof = f"""
count=0
[ ! -f '{state_file}' ] || count=$(cat '{state_file}')
count=$((count + 1))
echo "$count" > '{state_file}'
if [ "$count" -ge 2 ]; then
  echo 6789
  exit 0
fi
exit 1
"""

    result = _run(
        project,
        _tools(tmp_path, lsof=lsof),
        "sample.duckdb",
        "20260711",
    )

    assert result.returncode == 4
    assert "açık dosya" in result.stdout + result.stderr
    assert _values(active) == [1]
    assert not list(active.parent.glob("sample.duckdb.before_restore.*"))


def test_atomic_replace_failure_rolls_back_main_and_wal(tmp_path: Path) -> None:
    project = tmp_path / "project"
    active = project / "data" / "sample.duckdb"
    backup = project / "data" / "backups" / "20260711" / "sample.duckdb"
    _db(active, [1])
    _db(backup, [9])
    wal = active.with_suffix(".duckdb.wal")
    wal.write_bytes(b"pre-restore-wal")
    bin_dir = _tools(tmp_path)
    _write_tool(bin_dir, "mv", "exit 1")

    result = _run(project, bin_dir, "sample.duckdb", "20260711")

    assert result.returncode == 6
    assert "RESTORE_ROLLBACK_DONE" in result.stdout
    assert _values(active) == [1]
    assert wal.read_bytes() == b"pre-restore-wal"
