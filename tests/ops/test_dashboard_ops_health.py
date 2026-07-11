from __future__ import annotations

import importlib.util
import os
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "scripts" / "dashboard" / "collect.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("pa_dashboard_collect_ops_test", MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _job(*, loaded: bool = True, runs: int = 3, last_exit: int | None = 0) -> dict:
    return {
        "loaded": loaded,
        "pid": None,
        "state": "not running" if loaded else "missing",
        "runs": runs,
        "last_exit": last_exit,
    }


def _prepare(monkeypatch, tmp_path: Path):
    module = _load_module()
    monkeypatch.setattr(module, "ROOT", tmp_path)
    log = tmp_path / "logs" / "launchd" / "dbbackup.stdout.log"
    log.parent.mkdir(parents=True)
    log.write_text("BACKUP_DONE\n", encoding="utf-8")
    (log.parent / "healthping.stdout.log").write_text("PING_OK\n", encoding="utf-8")
    latest = tmp_path / "data" / "backups" / datetime.now().strftime("%Y%m%d")
    latest.mkdir(parents=True)
    (latest / "backup_manifest.sha256").write_text("fixture\n", encoding="utf-8")
    monkeypatch.delenv("HEALTHCHECKS_PING_URL", raising=False)
    return module, log


def test_launchctl_parser_captures_idle_job_last_exit_and_runs(monkeypatch) -> None:
    module = _load_module()
    output = """
    state = not running
    runs = 7
    last exit code = 3
    """
    monkeypatch.setattr(
        module.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout=output, stderr=""),
    )

    job = module._launchctl_job("com.priceaction.dbbackup")

    assert job == {
        "loaded": True,
        "pid": None,
        "state": "not running",
        "runs": 7,
        "last_exit": 3,
    }


def test_backup_is_ok_only_when_loaded_successful_and_fresh(monkeypatch, tmp_path: Path) -> None:
    module, _ = _prepare(monkeypatch, tmp_path)
    monkeypatch.setattr(module, "_launchctl_job", lambda label: _job())

    rows = {row["key"]: row for row in module.collect_daemons()}

    assert rows["dbbackup"]["status"] == "ok"
    assert rows["dbbackup"]["last_exit"] == 0
    assert rows["healthping"]["status"] == "warn"
    assert "INERT" in rows["healthping"]["detail"]
    assert rows["offsite_backup"]["status"] == "warn"
    assert "PENDING" in rows["offsite_backup"]["detail"]


def test_backup_stale_success_log_is_warn(monkeypatch, tmp_path: Path) -> None:
    module, log = _prepare(monkeypatch, tmp_path)
    old = time.time() - 27 * 3600
    os.utime(log, (old, old))
    monkeypatch.setattr(module, "_launchctl_job", lambda label: _job())

    rows = {row["key"]: row for row in module.collect_daemons()}

    assert rows["dbbackup"]["status"] == "warn"
    assert "27.0 saat eski" in rows["dbbackup"]["detail"]


def test_backup_without_checksum_manifest_is_warn(monkeypatch, tmp_path: Path) -> None:
    module, _ = _prepare(monkeypatch, tmp_path)
    for manifest in tmp_path.glob("data/backups/*/backup_manifest.sha256"):
        manifest.unlink()
    monkeypatch.setattr(module, "_launchctl_job", lambda label: _job())

    rows = {row["key"]: row for row in module.collect_daemons()}

    assert rows["dbbackup"]["status"] == "warn"
    assert "checksum manifest yok" in rows["dbbackup"]["detail"]


def test_backup_nonzero_exit_or_unloaded_is_down(monkeypatch, tmp_path: Path) -> None:
    module, _ = _prepare(monkeypatch, tmp_path)

    def failed(label: str) -> dict:
        return _job(last_exit=9) if label.endswith("dbbackup") else _job()

    monkeypatch.setattr(module, "_launchctl_job", failed)
    rows = {row["key"]: row for row in module.collect_daemons()}
    assert rows["dbbackup"]["status"] == "down"
    assert rows["dbbackup"]["last_exit"] == 9

    def unloaded(label: str) -> dict:
        return _job(loaded=False, runs=0, last_exit=None) if label.endswith("dbbackup") else _job()

    monkeypatch.setattr(module, "_launchctl_job", unloaded)
    rows = {row["key"]: row for row in module.collect_daemons()}
    assert rows["dbbackup"]["status"] == "down"
    assert "yüklü değil" in rows["dbbackup"]["detail"]


def test_healthcheck_needs_external_alarm_drill_marker_before_ok(
    monkeypatch, tmp_path: Path
) -> None:
    module, _ = _prepare(monkeypatch, tmp_path)
    monkeypatch.setenv("HEALTHCHECKS_PING_URL", "https://example.invalid/redacted")
    monkeypatch.delenv("HEALTHCHECKS_ALARM_DRILL_VERIFIED_AT", raising=False)
    monkeypatch.setattr(module, "_launchctl_job", lambda label: _job())

    rows = {row["key"]: row for row in module.collect_daemons()}

    assert rows["healthping"]["status"] == "warn"
    assert "drill kanıtı PENDING" in rows["healthping"]["detail"]

    marker = (datetime.now(UTC) - timedelta(minutes=1)).isoformat().replace("+00:00", "Z")
    monkeypatch.setenv("HEALTHCHECKS_ALARM_DRILL_VERIFIED_AT", marker)
    rows = {row["key"]: row for row in module.collect_daemons()}
    assert rows["healthping"]["status"] == "ok"
    assert "drill=" in rows["healthping"]["detail"]


def test_healthcheck_reads_dotenv_without_exposing_ping_url(monkeypatch, tmp_path: Path) -> None:
    module, _ = _prepare(monkeypatch, tmp_path)
    marker = (datetime.now(UTC) - timedelta(minutes=1)).isoformat().replace("+00:00", "Z")
    secret_url = "https://example.invalid/do-not-print-this-token"
    (tmp_path / ".env").write_text(
        "\n".join(
            [
                f"HEALTHCHECKS_PING_URL={secret_url}",
                f"HEALTHCHECKS_ALARM_DRILL_VERIFIED_AT={marker}",
                "",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.delenv("HEALTHCHECKS_PING_URL", raising=False)
    monkeypatch.delenv("HEALTHCHECKS_ALARM_DRILL_VERIFIED_AT", raising=False)
    monkeypatch.setattr(module, "_launchctl_job", lambda label: _job())

    rows = {row["key"]: row for row in module.collect_daemons()}

    assert rows["healthping"]["status"] == "ok"
    assert secret_url not in str(rows["healthping"])


def test_healthcheck_stale_stdout_never_reports_ok(monkeypatch, tmp_path: Path) -> None:
    module, log = _prepare(monkeypatch, tmp_path)
    health_log = log.parent / "healthping.stdout.log"
    old = time.time() - 13 * 60
    os.utime(health_log, (old, old))
    marker = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    monkeypatch.setenv("HEALTHCHECKS_PING_URL", "https://example.invalid/redacted")
    monkeypatch.setenv("HEALTHCHECKS_ALARM_DRILL_VERIFIED_AT", marker)
    monkeypatch.setattr(module, "_launchctl_job", lambda label: _job())

    row = {item["key"]: item for item in module.collect_daemons()}["healthping"]

    assert row["status"] == "warn"
    assert "13.0 dk eski" in row["detail"]


def test_healthcheck_unknown_last_exit_never_reports_ok(monkeypatch, tmp_path: Path) -> None:
    module, _ = _prepare(monkeypatch, tmp_path)
    marker = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    monkeypatch.setenv("HEALTHCHECKS_PING_URL", "https://example.invalid/redacted")
    monkeypatch.setenv("HEALTHCHECKS_ALARM_DRILL_VERIFIED_AT", marker)

    def unknown_exit(label: str) -> dict:
        return _job(last_exit=None) if label.endswith("healthping") else _job()

    monkeypatch.setattr(module, "_launchctl_job", unknown_exit)
    row = {item["key"]: item for item in module.collect_daemons()}["healthping"]

    assert row["status"] == "warn"
    assert "bilinmiyor" in row["detail"]


def test_rate_limit_status_uses_only_local_log_and_marks_active_ban(tmp_path: Path) -> None:
    module = _load_module()
    now = datetime(2026, 7, 11, 2, 20, tzinfo=UTC)
    deadline = now + timedelta(minutes=40)
    log = tmp_path / "futures_daemon_v15p2.log"
    log.write_text(
        "[02:15:17Z] POS_CHECK ERROR: binance 418 "
        '{"code":-1003,"msg":"banned until '
        f"{int(deadline.timestamp() * 1000)}"
        '"}\n'
        "[02:15:18Z] BREAKER ERROR: binance 418 -1003 response truncated\n",
        encoding="utf-8",
    )
    os.utime(log, (now.timestamp(), now.timestamp()))

    status = module._rate_limit_status(log, now=now)

    assert status["events"] == 2
    assert status["active"] is True
    assert status["recent_48h"] is True
    assert status["last_event_age_min"] == 4.7
    assert status["ban_until_utc"] == "2026-07-11T03:00:00Z"


def test_rate_limit_status_clears_recent_gate_only_after_48_hours(tmp_path: Path) -> None:
    module = _load_module()
    now = datetime(2026, 7, 11, 2, 20, tzinfo=UTC)
    event = now - timedelta(hours=49)
    deadline = event + timedelta(minutes=15)
    log = tmp_path / "futures_daemon_v15p2.log"
    log.write_text(
        f"[{event:%H:%M:%S}Z] ERROR 418 -1003 banned until "
        f"{int(deadline.timestamp() * 1000)}\n",
        encoding="utf-8",
    )
    os.utime(log, (event.timestamp(), event.timestamp()))

    status = module._rate_limit_status(log, now=now)

    assert status["active"] is False
    assert status["recent_48h"] is False
    assert status["last_event_age_min"] == 49 * 60


def test_daemon_health_exposes_rate_limit_warning_row(monkeypatch, tmp_path: Path) -> None:
    module, _ = _prepare(monkeypatch, tmp_path)
    monkeypatch.setattr(module, "_launchctl_job", lambda label: _job())
    monkeypatch.setattr(
        module,
        "_rate_limit_status",
        lambda _path: {
            "events": 36,
            "last_event_utc": "2026-07-11T02:15:17Z",
            "last_event_age_min": 5.0,
            "ban_until_utc": "2026-07-11T03:00:58Z",
            "active": True,
            "recent_48h": True,
            "error": None,
        },
    )

    row = {item["key"]: item for item in module.collect_daemons()}[
        "binance_private_rest"
    ]

    assert row["status"] == "warn"
    assert row["runs"] == 36
    assert "ACTIVE ban until" in row["detail"]
