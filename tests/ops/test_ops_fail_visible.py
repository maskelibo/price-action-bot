from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.subprocess


def test_healthcheck_without_url_is_explicitly_inert_and_never_calls_network(
    tmp_path: Path,
) -> None:
    env = os.environ.copy()
    env.pop("HEALTHCHECKS_PING_URL", None)
    env["PA_PROJECT_ROOT"] = str(tmp_path)

    result = subprocess.run(
        ["bash", str(ROOT / "scripts" / "healthcheck_ping.sh")],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )

    assert result.returncode == 0
    assert "INERT" in result.stdout
    assert "dış dead-man alarmı YOK" in result.stdout


def _write_tool(bin_dir: Path, name: str, body: str) -> None:
    path = bin_dir / name
    path.write_text("#!/bin/sh\n" + body + "\n", encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def _healthy_launchctl(project: Path) -> str:
    return "\n".join(
        [
            'test "$1" = "print" || exit 2',
            f"echo 'program = {project}/ops/launchd/run_futures_v15p2.sh'",
            f"echo 'pid = {os.getpid()}'",
            "exit 0",
        ]
    )


def _select_v15p2_pid(process_table: str) -> str:
    result = subprocess.run(
        ["awk", "-f", str(ROOT / "ops" / "launchd" / "select_futures_v15p2_pid.awk")],
        input=process_table,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def test_v15p2_duplicate_guard_ignores_orchestrator_text_and_selects_real_daemon() -> None:
    process_table = "\n".join(
        [
            "52764 zsh /bin/zsh -c python -m py_compile scripts/futures_daemon_v14.py --timeframe 15m",
            "52815 bash bash ops/launchd/run_futures_v15p2.sh",
            "53783 python3.12 .venv/bin/python -u scripts/futures_daemon_v14.py --timeframe 15m",
            "53784 python3.12 .venv/bin/python -u scripts/futures_daemon_v14.py --timeframe 5m",
        ]
    )

    assert _select_v15p2_pid(process_table) == "53783"


def test_v15p2_duplicate_guard_returns_empty_without_exact_python_daemon() -> None:
    process_table = "\n".join(
        [
            "52764 zsh /bin/zsh -c inspect scripts/futures_daemon_v14.py --timeframe 15m",
            "52815 bash bash ops/launchd/run_futures_v15p2.sh",
            "53784 python3.12 .venv/bin/python -m py_compile scripts/futures_daemon_v14.py",
            "53785 python3.12 .venv/bin/python -u scripts/futures_daemon_v14.py --timeframe 5m",
        ]
    )

    assert _select_v15p2_pid(process_table) == ""


def test_healthcheck_ping_delivery_failure_is_visible_in_launchd_exit(
    tmp_path: Path,
) -> None:
    log = tmp_path / "logs" / "futures_daemon_v15p2.log"
    log.parent.mkdir(parents=True)
    log.write_text("fresh\n", encoding="utf-8")
    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir()
    _write_tool(fake_bin, "launchctl", _healthy_launchctl(tmp_path))
    _write_tool(fake_bin, "curl", "exit 7")
    env = os.environ.copy()
    env.update(
        {
            "HEALTHCHECKS_PING_URL": "https://example.invalid/secret-token",
            "PA_PROJECT_ROOT": str(tmp_path),
            "PATH": f"{fake_bin}:{env['PATH']}",
        }
    )

    result = subprocess.run(
        ["bash", str(ROOT / "scripts" / "healthcheck_ping.sh")],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )

    assert result.returncode == 1
    assert "PING_FAIL" in result.stdout
    assert "secret-token" not in result.stdout + result.stderr


def test_healthcheck_unhealthy_daemon_skips_network_and_returns_nonzero(
    tmp_path: Path,
) -> None:
    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir()
    curl_marker = tmp_path / "curl-called"
    _write_tool(fake_bin, "launchctl", "exit 1")
    _write_tool(fake_bin, "curl", f"touch '{curl_marker}'; exit 0")
    env = os.environ.copy()
    env.update(
        {
            "HEALTHCHECKS_PING_URL": "https://example.invalid/redacted",
            "PA_PROJECT_ROOT": str(tmp_path),
            "PATH": f"{fake_bin}:{env['PATH']}",
        }
    )

    result = subprocess.run(
        ["bash", str(ROOT / "scripts" / "healthcheck_ping.sh")],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )

    assert result.returncode == 2
    assert "UNHEALTHY" in result.stdout
    assert not curl_marker.exists()


def test_healthcheck_accepted_ping_returns_success_without_printing_url(
    tmp_path: Path,
) -> None:
    log = tmp_path / "logs" / "futures_daemon_v15p2.log"
    log.parent.mkdir(parents=True)
    log.write_text("fresh\n", encoding="utf-8")
    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir()
    _write_tool(fake_bin, "launchctl", _healthy_launchctl(tmp_path))
    _write_tool(fake_bin, "curl", "exit 0")
    env = os.environ.copy()
    env.update(
        {
            "HEALTHCHECKS_PING_URL": "https://example.invalid/secret-token",
            "PA_PROJECT_ROOT": str(tmp_path),
            "PATH": f"{fake_bin}:{env['PATH']}",
        }
    )

    result = subprocess.run(
        ["bash", str(ROOT / "scripts" / "healthcheck_ping.sh")],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )

    assert result.returncode == 0
    assert "PING_OK" in result.stdout
    assert "secret-token" not in result.stdout + result.stderr


def test_healthcheck_uses_gnu_stat_mtime_on_linux(tmp_path: Path) -> None:
    log = tmp_path / "logs" / "futures_daemon_v15p2.log"
    log.parent.mkdir(parents=True)
    log.write_text("fresh\n", encoding="utf-8")
    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir()
    _write_tool(fake_bin, "uname", "echo Linux")
    _write_tool(fake_bin, "launchctl", _healthy_launchctl(tmp_path))
    _write_tool(fake_bin, "stat", 'test "$1" = "-c" && echo $(( $(date +%s) - 10 ))')
    _write_tool(fake_bin, "curl", "exit 0")
    env = os.environ.copy()
    env.update(
        {
            "HEALTHCHECKS_PING_URL": "https://example.invalid/redacted",
            "PA_PROJECT_ROOT": str(tmp_path),
            "PATH": f"{fake_bin}:{env['PATH']}",
        }
    )

    result = subprocess.run(
        ["bash", str(ROOT / "scripts" / "healthcheck_ping.sh")],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "PING_OK" in result.stdout


def test_healthcheck_rejects_future_log_timestamp(tmp_path: Path) -> None:
    log = tmp_path / "logs" / "futures_daemon_v15p2.log"
    log.parent.mkdir(parents=True)
    log.write_text("future\n", encoding="utf-8")
    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir()
    _write_tool(fake_bin, "uname", "echo Linux")
    _write_tool(fake_bin, "launchctl", _healthy_launchctl(tmp_path))
    _write_tool(fake_bin, "stat", 'test "$1" = "-c" && echo $(( $(date +%s) + 60 ))')
    curl_marker = tmp_path / "curl-called"
    _write_tool(fake_bin, "curl", f"touch '{curl_marker}'; exit 0")
    env = os.environ.copy()
    env.update(
        {
            "HEALTHCHECKS_PING_URL": "https://example.invalid/redacted",
            "PA_PROJECT_ROOT": str(tmp_path),
            "PATH": f"{fake_bin}:{env['PATH']}",
        }
    )

    result = subprocess.run(
        ["bash", str(ROOT / "scripts" / "healthcheck_ping.sh")],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )

    assert result.returncode == 2
    assert "mtime gelecekte" in result.stdout
    assert not curl_marker.exists()


def test_healthcheck_broad_process_match_cannot_replace_exact_launchd_identity(
    tmp_path: Path,
) -> None:
    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir()
    _write_tool(fake_bin, "launchctl", "exit 1")
    _write_tool(fake_bin, "pgrep", "exit 0")
    env = os.environ.copy()
    env.update(
        {
            "HEALTHCHECKS_PING_URL": "https://example.invalid/redacted",
            "PA_PROJECT_ROOT": str(tmp_path),
            "PATH": f"{fake_bin}:{env['PATH']}",
        }
    )

    result = subprocess.run(
        ["bash", str(ROOT / "scripts" / "healthcheck_ping.sh")],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )

    assert result.returncode == 2
    assert "loaded değil" in result.stdout


def test_healthcheck_rejects_loaded_label_with_wrong_program(tmp_path: Path) -> None:
    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir()
    launchctl = "\n".join(
        [
            "echo 'program = /tmp/not-the-live-wrapper.sh'",
            f"echo 'pid = {os.getpid()}'",
            "exit 0",
        ]
    )
    _write_tool(fake_bin, "launchctl", launchctl)
    curl_marker = tmp_path / "curl-called"
    _write_tool(fake_bin, "curl", f"touch '{curl_marker}'; exit 0")
    env = os.environ.copy()
    env.update(
        {
            "HEALTHCHECKS_PING_URL": "https://example.invalid/redacted",
            "PA_PROJECT_ROOT": str(tmp_path),
            "PATH": f"{fake_bin}:{env['PATH']}",
        }
    )

    result = subprocess.run(
        ["bash", str(ROOT / "scripts" / "healthcheck_ping.sh")],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )

    assert result.returncode == 2
    assert "beklenen programı çalıştırmıyor" in result.stdout
    assert not curl_marker.exists()


def test_healthcheck_requires_exact_program_not_prefix_match(tmp_path: Path) -> None:
    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir()
    expected = tmp_path / "ops" / "launchd" / "run_futures_v15p2.sh"
    launchctl = "\n".join(
        [
            f"echo 'program = {expected}.lookalike'",
            f"echo 'pid = {os.getpid()}'",
            "exit 0",
        ]
    )
    _write_tool(fake_bin, "launchctl", launchctl)
    curl_marker = tmp_path / "curl-called"
    _write_tool(fake_bin, "curl", f"touch '{curl_marker}'; exit 0")
    env = os.environ.copy()
    env.update(
        {
            "HEALTHCHECKS_PING_URL": "https://example.invalid/redacted",
            "PA_PROJECT_ROOT": str(tmp_path),
            "PATH": f"{fake_bin}:{env['PATH']}",
        }
    )

    result = subprocess.run(
        ["bash", str(ROOT / "scripts" / "healthcheck_ping.sh")],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )

    assert result.returncode == 2
    assert "beklenen programı çalıştırmıyor" in result.stdout
    assert not curl_marker.exists()


def test_security_workflow_has_nonempty_scan_guard_and_no_conflicting_bandit_flags() -> None:
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    security = (ROOT / "docs" / "SECURITY.md").read_text(encoding="utf-8")

    assert "bandit -r src scripts --severity-level medium -f json" in workflow
    assert "scanned LOC is zero" in workflow
    assert "Bandit scan errors" in workflow
    assert 'issue_severity") == "HIGH"' in workflow
    assert "bandit_runtime_report.json" in workflow
    assert "bandit_broad_report.json" in workflow
    assert "runtime-critical surface — HIGH blocking" in workflow
    assert "src + all scripts — INFORMATIONAL" in workflow
    assert "-ll -f txt" not in workflow
    assert "-ll --severity-level" not in security
    assert "CI'da bağımsız gitleaks job'ı" in security
    assert "Install project for pip-audit (blocking setup)" in workflow
    assert "pip install -e '.[dev]' 2>&1 | tee pip_audit_install.log" in workflow
    install_step = workflow.split(
        "- name: Install project for pip-audit (blocking setup)", maxsplit=1
    )[1].split("- name: pip-audit", maxsplit=1)[0]
    assert "continue-on-error" not in install_step
    assert "pip install -e .[dev] 2>&1 | tail -5 || true" not in workflow


def test_ci_truthfully_separates_informational_baselines_from_blocking_safety() -> None:
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

    assert "Ruff (repo-wide — INFORMATIONAL, exit code visible)" in workflow
    assert "ruff check src scripts tests" in workflow
    assert "Ruff (runtime safety surface — blocking)" in workflow
    assert "Coverage (whole package — INFORMATIONAL, 70% target visible)" in workflow
    assert "Pytest (full suite — INFORMATIONAL, exit code görünür)" in workflow
    assert 'exit "$_ec"' in workflow
    assert "tests/ops/test_dashboard_local_evidence.py" in workflow
    assert "tests/execution/test_e13_exit_evidence.py" in workflow
    assert "tests/execution/test_e13_shadow_sync.py" in workflow
    assert "tests/execution/test_daily_execution_disabled.py" in workflow
    assert "tests/execution/test_pyramid_router.py" in workflow
    assert "tests/execution/test_pyramid_be_protect.py" in workflow
