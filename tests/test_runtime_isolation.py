"""Regression tests for the pytest runtime safety boundary."""

from __future__ import annotations

import json
import os
import socket
import sqlite3
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

from price_action.runtime_paths import REPO_ROOT, RuntimePaths


def test_runtime_override_moves_mutable_paths_outside_repo() -> None:
    runtime_root = Path(os.environ["PA_RUNTIME_ROOT"]).resolve()
    paths = RuntimePaths.from_env()

    assert paths.root == runtime_root
    assert not paths.root.is_relative_to(REPO_ROOT)
    assert paths.kill_switch == runtime_root / "logs" / "kill_switch.json"


def test_production_default_paths_remain_backward_compatible(monkeypatch) -> None:
    monkeypatch.delenv("PA_RUNTIME_ROOT", raising=False)

    paths = RuntimePaths.from_env()

    assert paths.root == REPO_ROOT
    assert paths.kill_switch == REPO_ROOT / "logs" / "kill_switch.json"


def test_blank_runtime_override_is_treated_as_unset(monkeypatch) -> None:
    monkeypatch.setenv("PA_RUNTIME_ROOT", "   ")

    assert RuntimePaths.from_env().root == REPO_ROOT


def test_settings_mutable_directories_follow_runtime_root() -> None:
    from price_action.settings import get_settings

    get_settings.cache_clear()  # type: ignore[attr-defined]
    settings = get_settings()
    runtime_root = Path(os.environ["PA_RUNTIME_ROOT"]).resolve()

    assert settings.logs_dir == runtime_root / "logs"
    assert settings.reports_dir == runtime_root / "reports"
    assert settings.memory_dir == runtime_root / "memory"
    assert settings.knowledge_dir == runtime_root / "knowledge"
    assert settings.duckdb_path == runtime_root / "data" / "market.duckdb"
    assert settings.ingest_duckdb_path == runtime_root / "data" / "market_ingest.duckdb"
    assert settings.parquet_root == runtime_root / "data" / "parquet"
    assert settings.chroma_path == runtime_root / "knowledge" / "index"
    assert settings.repo_root == REPO_ROOT
    assert settings.configs_dir == REPO_ROOT / "configs"


def test_explicit_storage_env_override_wins(monkeypatch, tmp_path) -> None:
    from price_action.settings import get_settings

    explicit = tmp_path / "explicit.duckdb"
    monkeypatch.setenv("DUCKDB_PATH", str(explicit))
    get_settings.cache_clear()  # type: ignore[attr-defined]

    assert get_settings().duckdb_path == explicit


def test_dotenv_loading_is_disabled_during_tests() -> None:
    assert os.environ["PYTHON_DOTENV_DISABLED"] == "1"
    assert os.environ["BINANCE_FUTURES_TESTNET_API_KEY"] == ""
    assert os.environ["BINANCE_FUTURES_TESTNET_API_SECRET"] == ""
    assert os.environ["PA_DASHBOARD_ADMIN_TOKEN"] == ""


def test_execution_defaults_follow_runtime_root() -> None:
    from price_action.execution import (
        dead_mans_switch,
        idempotency,
        pyramid_store,
        slippage_tracker,
    )

    runtime = RuntimePaths.from_env()

    assert runtime.data / "idempotency.duckdb" == dead_mans_switch.DEFAULT_DB
    assert runtime.kill_switch == dead_mans_switch.KILL_SWITCH_PATH
    assert runtime.data / "idempotency.duckdb" == idempotency.DEFAULT_DB
    assert runtime.data / "pyramid_store.duckdb" == pyramid_store.DEFAULT_DB
    assert runtime.data / "execution_fills.duckdb" == slippage_tracker.DEFAULT_DB
    assert dead_mans_switch._RUNTIME_PATHS.logs == runtime.logs
    assert slippage_tracker._RUNTIME_PATHS.logs == runtime.logs


def test_daemon_family_defaults_follow_runtime_root() -> None:
    import scripts.futures_daemon as daemon
    import scripts.futures_trade_15m as trade_15m
    import scripts.futures_trade_daily as trade_daily

    runtime = RuntimePaths.from_env()
    for path in (
        daemon.JOURNAL,
        daemon.LOG_FILE,
        daemon.LAST_SCAN_STATE,
        daemon.IDEMPOTENCY_DB,
        daemon.PYRAMID_STORE_DB,
        daemon.KILL_SWITCH_PATH,
        trade_daily.JOURNAL,
        trade_daily.BREAKER_STATE,
        trade_15m.JOURNAL,
        trade_15m.BREAKER_STATE,
    ):
        assert Path(path).resolve().is_relative_to(runtime.root)


def test_token_budget_ignores_dry_run_records(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("PA_RUNTIME_ROOT", str(tmp_path))
    audit = tmp_path / "data" / "llm_calls.jsonl"
    audit.parent.mkdir(parents=True)
    now = datetime.now(UTC).isoformat()
    records = [
        {
            "ts": now,
            "agent": "dry-agent",
            "model": "dry-model",
            "input_tokens": 999,
            "output_tokens": 999,
            "stop_reason": "dry_run",
        },
        {
            "ts": now,
            "agent": "real-agent",
            "model": "real-model",
            "input_tokens": 10,
            "output_tokens": 20,
            "stop_reason": "end_turn",
        },
    ]
    audit.write_text("\n".join(json.dumps(record) for record in records) + "\n", encoding="utf-8")

    from price_action.ops.token_budget import get_token_stats

    stats = get_token_stats(window_hours=1)

    assert "dry-agent|dry-model" not in stats
    assert stats["real-agent|real-model"]["input"] == 10
    assert stats["real-agent|real-model"]["output"] == 20


def test_repo_operational_write_is_blocked_before_mutation() -> None:
    forbidden = REPO_ROOT / "logs" / "pytest-must-not-write.txt"
    with pytest.raises(RuntimeError, match="protected runtime path"):
        forbidden.write_text("unsafe", encoding="utf-8")
    assert not forbidden.exists()


def test_repo_operational_bytes_write_is_blocked() -> None:
    forbidden = REPO_ROOT / "logs" / "pytest-bytes-must-not-write.txt"
    with (
        pytest.raises(RuntimeError, match="protected runtime path"),
        open(os.fsencode(forbidden), "w", encoding="utf-8"),
    ):
        pass
    assert not forbidden.exists()


def test_repo_operational_dir_fd_write_is_blocked() -> None:
    directory_fd = os.open(REPO_ROOT / "logs", os.O_RDONLY)
    try:
        with pytest.raises(RuntimeError, match="protected runtime path"):
            os.open(
                "pytest-dir-fd-must-not-write.txt",
                os.O_CREAT | os.O_WRONLY,
                dir_fd=directory_fd,
            )
    finally:
        os.close(directory_fd)
    assert not (REPO_ROOT / "logs" / "pytest-dir-fd-must-not-write.txt").exists()


def test_writable_native_databases_under_repo_are_blocked() -> None:
    import duckdb

    duckdb_path = REPO_ROOT / "data" / "pytest-must-not-write.duckdb"
    sqlite_path = REPO_ROOT / "data" / "pytest-must-not-write.sqlite"
    with pytest.raises(RuntimeError, match="writable DuckDB"):
        duckdb.connect(str(duckdb_path))
    with pytest.raises(RuntimeError, match="writable SQLite"):
        sqlite3.connect(sqlite_path)
    assert not duckdb_path.exists()
    assert not sqlite_path.exists()


def test_read_only_native_database_requires_ops_capability() -> None:
    import duckdb

    protected = REPO_ROOT / "data" / "market.duckdb"
    with pytest.raises(RuntimeError, match="protected DuckDB read"):
        duckdb.connect(str(protected), read_only=True)

    sqlite_uri = f"file:{REPO_ROOT / 'data' / 'market.sqlite'}?mode=ro"
    with pytest.raises(RuntimeError, match="protected SQLite read"):
        sqlite3.connect(
            sqlite_uri,
            5.0,
            0,
            "DEFERRED",
            True,
            sqlite3.Connection,
            128,
            True,
        )


def test_unit_test_external_network_is_blocked() -> None:
    with pytest.raises(RuntimeError, match="network access blocked"):
        socket.create_connection(("example.com", 443), timeout=0.01)


def test_unit_test_udp_is_blocked() -> None:
    with (
        socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock,
        pytest.raises(RuntimeError, match="network access blocked"),
    ):
        sock.sendto(b"probe", ("127.0.0.1", 9))


def test_unmarked_subprocess_is_blocked() -> None:
    with pytest.raises(RuntimeError, match="subprocess blocked"):
        subprocess.run([sys.executable, "-c", "print('unsafe')"], check=False)


def test_unmarked_os_system_is_blocked() -> None:
    with pytest.raises(RuntimeError, match="subprocess blocked"):
        os.system("true")


@pytest.mark.subprocess
def test_marked_subprocess_inherits_sterile_environment() -> None:
    code = (
        "import json, os; "
        "print(json.dumps({k: os.environ.get(k) for k in "
        "['PA_TESTING','PA_RUNTIME_ROOT','PYTHON_DOTENV_DISABLED',"
        "'BINANCE_FUTURES_TESTNET_API_KEY','PA_LIVE_CONFIRM']}))"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        check=True,
        capture_output=True,
        text=True,
    )
    child_env = json.loads(result.stdout)

    assert child_env["PA_TESTING"] == "1"
    assert child_env["PA_RUNTIME_ROOT"] == os.environ["PA_RUNTIME_ROOT"]
    assert child_env["PYTHON_DOTENV_DISABLED"] == "1"
    assert child_env["BINANCE_FUTURES_TESTNET_API_KEY"] == ""
    assert child_env["PA_LIVE_CONFIRM"] == ""

    positional = subprocess.Popen(
        [sys.executable, "-c", "import os; print(os.environ['PA_TESTING'])"],
        -1,
        None,
        None,
        subprocess.PIPE,
        None,
        None,
        True,
        False,
        None,
        {"PA_TESTING": "0"},
        text=True,
    )
    stdout, _ = positional.communicate(timeout=10)
    assert positional.returncode == 0
    assert stdout.strip() == "1"
