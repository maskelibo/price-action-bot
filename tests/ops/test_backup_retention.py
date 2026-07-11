from __future__ import annotations

import os
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

import duckdb
import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "backup_duckdb.sh"
pytestmark = pytest.mark.subprocess


def _run_backup(project_root: Path, *, retention: str) -> subprocess.CompletedProcess[str]:
    data_dir = project_root / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    # Use a real DuckDB: backup now creates a checkpointed logical snapshot and
    # deliberately rejects arbitrary extension-only fixtures.
    fixture = data_dir / "fixture.duckdb"
    con = duckdb.connect(str(fixture))
    try:
        con.execute("CREATE TABLE evidence(value INTEGER)")
        con.execute("INSERT INTO evidence VALUES (1)")
        con.execute("CHECKPOINT")
    finally:
        con.close()
    env = os.environ.copy()
    env.update(
        {
            "PA_PROJECT_ROOT": str(project_root),
            "PA_BACKUP_RETENTION_DAYS": retention,
            "PA_PYTHON_BIN": sys.executable,
        }
    )
    return subprocess.run(
        ["bash", str(SCRIPT)],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )


def test_retention_keeps_exact_newest_n_independent_of_mtime(tmp_path: Path) -> None:
    backup_root = tmp_path / "data" / "backups"
    backup_root.mkdir(parents=True)
    today = date.today()
    older_dates = [
        (today - timedelta(days=offset)).strftime("%Y%m%d")
        for offset in range(4, 0, -1)
    ]
    for backup_date in older_dates:
        directory = backup_root / backup_date
        directory.mkdir()
        # Equal mtimes reproduce the rounding/tie case that made -mtime retain
        # more than the configured count.
        os.utime(directory, (1_700_000_000, 1_700_000_000))

    result = _run_backup(tmp_path, retention="3")

    assert result.returncode == 0, result.stderr
    kept = sorted(path.name for path in backup_root.iterdir() if path.is_dir())
    # Today's directory is added by the run and participates in newest-N.
    expected = [today.strftime("%Y%m%d")] + [
        (today - timedelta(days=offset)).strftime("%Y%m%d") for offset in (1, 2)
    ]
    assert kept == sorted(expected)
    assert "policy=newest-N" in result.stdout


def test_retention_ignores_non_backup_directories(tmp_path: Path) -> None:
    backup_root = tmp_path / "data" / "backups"
    (backup_root / "manual-notes").mkdir(parents=True)
    today = date.today()
    for offset in (3, 2, 1):
        (backup_root / (today - timedelta(days=offset)).strftime("%Y%m%d")).mkdir()

    result = _run_backup(tmp_path, retention="2")

    assert result.returncode == 0, result.stderr
    assert (backup_root / "manual-notes").is_dir()
    dated = sorted(
        path.name
        for path in backup_root.iterdir()
        if path.is_dir() and path.name.isdigit()
    )
    assert dated == sorted(
        [today.strftime("%Y%m%d"), (today - timedelta(days=1)).strftime("%Y%m%d")]
    )


def test_retention_rejects_non_positive_or_non_numeric_values(tmp_path: Path) -> None:
    for invalid in ("0", "-1", "three"):
        result = _run_backup(tmp_path / invalid.replace("/", "_"), retention=invalid)
        assert result.returncode == 2
        assert "pozitif tam sayi" in result.stderr
