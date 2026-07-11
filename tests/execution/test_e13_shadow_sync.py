from __future__ import annotations

import hashlib
import json
import os
import signal
import subprocess
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import duckdb
import pytest

import price_action.execution.e13_storage as e13_storage
from price_action.execution.e13_policy_migration import (
    migrate_e13_policy_provenance,
)
from price_action.execution.e13_shadow import (
    AtrChandelierShadowRecorder,
    E13ShadowLease,
    e13_shadow_lock_path,
    validate_e13_shadow_state_document,
)
from price_action.execution.e13_shadow_sync import (
    E13ShadowMutationError,
    sync_e13_shadow,
)
from price_action.execution.e13_storage import (
    canonical_e13_data_root,
    e13_policy_migration_audit_path,
    e13_policy_migration_transaction_path,
    e13_transaction_path,
)
from price_action.execution.exit_evidence import (
    e13_exit_evidence,
    e13_legacy_semantic_policy_hash,
    load_e13_policy,
)

ROOT = Path(__file__).resolve().parents[2]


def _write_config(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    path = root / "risk.yaml"
    artifact_id = hashlib.sha256(str(root).encode()).hexdigest()[:16]
    artifact_dir = f"data/e13-tests/{artifact_id}"
    path.write_text(
        f"""
stop_loss:
  trailing:
    enabled: true
    method: atr_chandelier
    atr_period: 14
    multiplier: 1.5
    activate_after_R: 1.0
exit_evidence:
  e13_atr_chandelier:
    status: shadow_only
    clean_cutoff_utc: "2026-07-09T00:00:00Z"
    min_clean_closed_trades: 1
    eligible_close_reasons: [sl, tp, time]
    auto_promote: false
    live_exit:
      method: pct_trail
      trail_pct: 0.015
      activate_after_R: 1.0
    candidate_exit:
      method: atr_chandelier
      atr_period: 14
      atr_method: true_range_sma
      multiplier: 1.5
      activate_after_R: 1.0
    paired_shadow:
      schema_version: 1
      min_paired_closed_trades: 1
      market_venue: binance
      timeframe: 15m
      entry_timestamp_semantics: signal_bar_open
      state_path: {artifact_dir}/state.json
      evidence_path: {artifact_dir}/evidence.jsonl
""".lstrip(),
        encoding="utf-8",
    )
    return path


def _set_artifact_path(config: Path, key: str, value: str | Path) -> None:
    lines = config.read_text(encoding="utf-8").splitlines()
    prefix = f"      {key}:"
    replaced = False
    for index, line in enumerate(lines):
        if line.startswith(prefix):
            lines[index] = f'{prefix} "{value}"'
            replaced = True
            break
    assert replaced, key
    config.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _downgrade_to_legacy_policy_hash(config: Path) -> tuple[str, str]:
    policy = load_e13_policy(config)
    legacy_hash = e13_legacy_semantic_policy_hash(policy)
    state = json.loads(policy.shadow_state_path.read_text(encoding="utf-8"))
    state["policy_hash_sha256"] = legacy_hash
    state.pop("policy_provenance_version", None)
    policy.shadow_state_path.write_text(
        json.dumps(state, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    if policy.shadow_evidence_path.exists():
        migrated_records = []
        for line in policy.shadow_evidence_path.read_text(
            encoding="utf-8"
        ).splitlines():
            record = json.loads(line)
            record["policy_hash_sha256"] = legacy_hash
            record.pop("policy_provenance_version", None)
            migrated_records.append(record)
        policy.shadow_evidence_path.write_text(
            "".join(
                json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n"
                for record in migrated_records
            ),
            encoding="utf-8",
        )
    return legacy_hash, policy.policy_hash_sha256


def _filesystem_snapshot(root: Path) -> dict[str, tuple[object, ...]]:
    if not root.exists():
        return {"<root>": (False,)}
    snapshot: dict[str, tuple[object, ...]] = {}
    for path in [root, *sorted(root.rglob("*"))]:
        info = path.lstat()
        relative = "." if path == root else str(path.relative_to(root))
        content_hash = (
            hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
        )
        snapshot[relative] = (
            info.st_mode,
            info.st_size,
            info.st_mtime_ns,
            info.st_ino,
            content_hash,
        )
    return snapshot


def _write_open_journal(path: Path, opened: datetime) -> None:
    with duckdb.connect(str(path)) as connection:
        connection.execute(
            """CREATE TABLE futures_signals (
                signal_id VARCHAR PRIMARY KEY, ts TIMESTAMP, symbol VARCHAR,
                side VARCHAR, fill_price DOUBLE, sl_price DOUBLE, status VARCHAR
            )"""
        )
        connection.execute(
            """CREATE TABLE futures_trades_closed (
                trade_id VARCHAR PRIMARY KEY, ts_open TIMESTAMP, ts_close TIMESTAMP,
                sym VARCHAR, side VARCHAR, strategy VARCHAR, entry_price DOUBLE,
                exit_price DOUBLE, qty DOUBLE, realized_pnl_usdt DOUBLE,
                realized_r DOUBLE, win BOOLEAN, close_reason VARCHAR
            )"""
        )
        connection.execute(
            "INSERT INTO futures_signals VALUES (?, ?, ?, ?, ?, ?, ?)",
            ["trade-1", opened.replace(tzinfo=None), "TEST/USDT", "long", 100, 98, "filled"],
        )


def _close_journal(path: Path, opened: datetime) -> None:
    with duckdb.connect(str(path)) as connection:
        connection.execute(
            """
            INSERT INTO futures_trades_closed VALUES
            (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                "trade-1",
                opened.replace(tzinfo=None),
                (opened + timedelta(hours=1)).replace(tzinfo=None),
                "TEST/USDT",
                "long",
                "test_strategy",
                100,
                98,
                1,
                -2,
                -1,
                False,
                "sl",
            ],
        )
        connection.execute(
            "UPDATE futures_signals SET status='closed' WHERE signal_id='trade-1'"
        )


def _write_market(path: Path, opened: datetime) -> None:
    with duckdb.connect(str(path)) as connection:
        connection.execute(
            """CREATE TABLE ohlcv (
                venue VARCHAR, symbol VARCHAR, timeframe VARCHAR, ts TIMESTAMPTZ,
                open DOUBLE, high DOUBLE, low DOUBLE, close DOUBLE, volume DOUBLE
            )"""
        )
        rows = []
        for offset in range(-17, 1):
            ts = opened + timedelta(minutes=15 * offset)
            rows.append(("binance", "TEST/USDT", "15m", ts, 100, 100.5, 99.5, 100, 1))
        # futures_signals.ts is the signal bar's open.  First exposure is the
        # next full bar (+15m), which activates a 102 stop for bar +30m.
        rows.extend(
            [
                (
                    "binance",
                    "TEST/USDT",
                    "15m",
                    opened + timedelta(minutes=15),
                    100,
                    103.5,
                    99.5,
                    103,
                    1,
                ),
                (
                    "binance",
                    "TEST/USDT",
                    "15m",
                    opened + timedelta(minutes=30),
                    102.5,
                    103,
                    101.5,
                    102,
                    1,
                ),
            ]
        )
        connection.executemany("INSERT INTO ohlcv VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)


def test_sync_is_prospective_causal_and_idempotent(tmp_path: Path) -> None:
    opened = datetime(2026, 7, 10, tzinfo=UTC)
    config = _write_config(tmp_path)
    policy = load_e13_policy(config)
    journal = tmp_path / "journal.duckdb"
    market = tmp_path / "market.duckdb"
    _write_open_journal(journal, opened)
    _write_market(market, opened)

    opened_tick = sync_e13_shadow(
        journal,
        market,
        config_path=config,
        through=opened + timedelta(minutes=45),
    )
    _close_journal(journal, opened)
    close_tick = sync_e13_shadow(
        journal,
        market,
        config_path=config,
        through=opened + timedelta(hours=2),
    )
    repeat_tick = sync_e13_shadow(
        journal,
        market,
        config_path=config,
        through=opened + timedelta(hours=2),
    )

    assert opened_tick["trades_started"] == 1
    assert opened_tick["evidence_emitted"] == 0
    assert close_tick["evidence_emitted"] == 1
    assert repeat_tick["evidence_emitted"] == 0
    assert repeat_tick["already_evidenced"] == 1
    evidence_lines = policy.shadow_evidence_path.read_text(encoding="utf-8").splitlines()
    assert len(evidence_lines) == 1
    evidence = json.loads(evidence_lines[0])
    assert 101 < evidence["candidate_exit_price"] < 102
    assert evidence["candidate_realized_r"] == pytest.approx(
        (evidence["candidate_exit_price"] - 100) / 2
    )
    result = e13_exit_evidence(journal, config_path=config)
    assert result["formal_review_ready"] is True
    assert result["promotion_authorized"] is False


def test_dry_run_never_mutates_real_artifacts(tmp_path: Path) -> None:
    opened = datetime(2026, 7, 10, tzinfo=UTC)
    config = _write_config(tmp_path)
    policy = load_e13_policy(config)
    journal = tmp_path / "journal.duckdb"
    market = tmp_path / "market.duckdb"
    _write_open_journal(journal, opened)
    _write_market(market, opened)

    result = sync_e13_shadow(
        journal,
        market,
        config_path=config,
        through=opened + timedelta(minutes=45),
        dry_run=True,
    )

    assert result["dry_run"] is True
    assert result["mutated_real_artifacts"] is False
    assert result["trades_started"] == 1
    assert not policy.shadow_state_path.exists()
    assert not policy.shadow_evidence_path.exists()


def test_market_schema_without_timezone_fails_closed(tmp_path: Path) -> None:
    opened = datetime(2026, 7, 10, tzinfo=UTC)
    config = _write_config(tmp_path)
    journal = tmp_path / "journal.duckdb"
    market = tmp_path / "market.duckdb"
    _write_open_journal(journal, opened)
    with duckdb.connect(str(market)) as connection:
        connection.execute(
            """CREATE TABLE ohlcv (
                venue VARCHAR, symbol VARCHAR, timeframe VARCHAR, ts TIMESTAMP,
                open DOUBLE, high DOUBLE, low DOUBLE, close DOUBLE
            )"""
        )

    with pytest.raises(ValueError, match="TIMESTAMP WITH TIME ZONE"):
        sync_e13_shadow(
            journal,
            market,
            config_path=config,
            through=opened + timedelta(minutes=45),
        )


def test_sync_source_has_no_private_api_or_order_path() -> None:
    source = (Path(__file__).parents[2] / "src/price_action/execution/e13_shadow_sync.py").read_text(
        encoding="utf-8"
    )
    for forbidden in (
        "fapiPrivate",
        "create_order",
        "cancel_order",
        "futures_daemon",
        "ccxt",
    ):
        assert forbidden not in source


def test_launchd_tick_is_the_only_e13_shadow_writer() -> None:
    daemon_source = (ROOT / "scripts/futures_daemon.py").read_text(encoding="utf-8")
    plist_source = (ROOT / "ops/launchd/com.priceaction.e13_shadow_tick.plist").read_text(
        encoding="utf-8"
    )

    assert "sync_e13_shadow" not in daemon_source
    assert "15M_E13_SHADOW" not in daemon_source
    assert "scripts/e13_shadow_tick.py" in plist_source


@pytest.mark.subprocess
def test_tick_cli_dry_run_is_strict_json_and_non_mutating(tmp_path: Path) -> None:
    opened = datetime(2026, 7, 10, tzinfo=UTC)
    config = _write_config(tmp_path)
    policy = load_e13_policy(config)
    journal = tmp_path / "journal.duckdb"
    market = tmp_path / "market.duckdb"
    _write_open_journal(journal, opened)
    _write_market(market, opened)
    env = os.environ.copy()
    env["PA_LOG_QUIET"] = "0"
    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/e13_shadow_tick.py"),
            "--config",
            str(config),
            "--journal",
            str(journal),
            "--market",
            str(market),
            "--through",
            (opened + timedelta(minutes=45)).isoformat(),
            "--dry-run",
            "--json",
        ],
        cwd=ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["dry_run"] is True
    assert payload["mutated_real_artifacts"] is False
    assert payload["exchange_calls"] == 0
    assert completed.stderr == ""
    assert not policy.shadow_state_path.exists()
    assert not policy.shadow_evidence_path.exists()


def _subprocess_env() -> dict[str, str]:
    env = os.environ.copy()
    env["PA_LOG_QUIET"] = "1"
    env["PA_DISABLE_FILE_LOG"] = "1"
    env["PYTHONPATH"] = str(ROOT / "src")
    return env


def _wait_for_file(path: Path, process: subprocess.Popen[str], *, timeout: float = 10) -> None:
    deadline = time.monotonic() + timeout
    while not path.exists() and process.poll() is None and time.monotonic() < deadline:
        time.sleep(0.01)
    assert path.exists(), process.communicate(timeout=1)


@pytest.mark.subprocess
def test_busy_tick_and_manual_recorder_are_side_effect_free_and_crash_releases_lock(
    tmp_path: Path,
) -> None:
    opened = datetime(2026, 7, 10, tzinfo=UTC)
    config = _write_config(tmp_path)
    journal = tmp_path / "journal.duckdb"
    market = tmp_path / "market.duckdb"
    _write_open_journal(journal, opened)
    _write_market(market, opened)
    policy = load_e13_policy(config)
    ready = tmp_path / "lease.ready"
    holder_code = """
import sys
import time
from pathlib import Path

from price_action.execution.e13_shadow import E13ShadowLease

with E13ShadowLease(sys.argv[1]):
    Path(sys.argv[2]).write_text("ready", encoding="utf-8")
    time.sleep(30)
"""
    holder = subprocess.Popen(
        [sys.executable, "-c", holder_code, str(policy.shadow_state_path), str(ready)],
        cwd=ROOT,
        env=_subprocess_env(),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        _wait_for_file(ready, holder)
        tick = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts/e13_shadow_tick.py"),
                "--config",
                str(config),
                "--journal",
                str(journal),
                "--market",
                str(market),
                "--through",
                (opened + timedelta(minutes=45)).isoformat(),
                "--json",
            ],
            cwd=ROOT,
            env=_subprocess_env(),
            check=False,
            capture_output=True,
            text=True,
        )
        manual = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts/e13_shadow_recorder.py"),
                "--config",
                str(config),
                "status",
            ],
            cwd=ROOT,
            env=_subprocess_env(),
            check=False,
            capture_output=True,
            text=True,
        )

        assert tick.returncode == 3, tick.stdout + tick.stderr
        assert manual.returncode == 3, manual.stdout + manual.stderr
        assert json.loads(tick.stdout)["status"] == "HOLD_WRITER_BUSY"
        assert json.loads(manual.stdout)["status"] == "HOLD_WRITER_BUSY"
        assert not policy.shadow_state_path.exists()
        assert not policy.shadow_evidence_path.exists()
        assert e13_shadow_lock_path(policy.shadow_state_path).is_file()
    finally:
        # SIGKILL models an unhandled process crash; the kernel must release
        # the fcntl lease even though the runtime lock file remains.
        holder.kill()
        holder.wait(timeout=5)

    with (
        pytest.raises(RuntimeError, match="lease exception"),
        E13ShadowLease(policy.shadow_state_path),
    ):
        raise RuntimeError("lease exception")
    with E13ShadowLease(policy.shadow_state_path) as released_lease:
        assert released_lease.held is True

    after_crash = sync_e13_shadow(
        journal,
        market,
        config_path=config,
        through=opened + timedelta(minutes=45),
    )
    assert after_crash["status"] == "OK"
    assert after_crash["lease_busy"] is False
    assert policy.shadow_state_path.is_file()


@pytest.mark.subprocess
def test_two_real_tick_processes_same_bar_emit_exactly_once(tmp_path: Path) -> None:
    opened = datetime(2026, 7, 10, tzinfo=UTC)
    config = _write_config(tmp_path)
    policy = load_e13_policy(config)
    journal = tmp_path / "journal.duckdb"
    market = tmp_path / "market.duckdb"
    _write_open_journal(journal, opened)
    _write_market(market, opened)
    seeded = sync_e13_shadow(
        journal,
        market,
        config_path=config,
        through=opened + timedelta(minutes=45),
    )
    assert seeded["trades_started"] == 1
    _close_journal(journal, opened)

    tick_args = [
        str(ROOT / "scripts/e13_shadow_tick.py"),
        "--config",
        str(config),
        "--journal",
        str(journal),
        "--market",
        str(market),
        "--through",
        (opened + timedelta(hours=2)).isoformat(),
        "--json",
    ]
    go = tmp_path / "go"
    runner_code = """
import os
import sys
import time
from pathlib import Path

ready = Path(sys.argv[1])
go = Path(sys.argv[2])
ready.write_text("ready", encoding="utf-8")
while not go.exists():
    time.sleep(0.005)
os.execv(sys.executable, [sys.executable, *sys.argv[3:]])
"""
    workers: list[subprocess.Popen[str]] = []
    ready_files: list[Path] = []
    for index in range(2):
        ready = tmp_path / f"worker-{index}.ready"
        ready_files.append(ready)
        workers.append(
            subprocess.Popen(
                [sys.executable, "-c", runner_code, str(ready), str(go), *tick_args],
                cwd=ROOT,
                env=_subprocess_env(),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
        )
    for ready, worker in zip(ready_files, workers, strict=True):
        _wait_for_file(ready, worker)
    go.write_text("go", encoding="utf-8")
    completed = [worker.communicate(timeout=20) for worker in workers]
    return_codes = [worker.returncode for worker in workers]
    assert all(code in {0, 3} for code in return_codes), completed
    assert 0 in return_codes
    payloads = [json.loads(stdout) for stdout, _stderr in completed]
    assert all(payload["status"] in {"OK", "HOLD_WRITER_BUSY"} for payload in payloads)
    assert sum(int(payload["evidence_emitted"]) for payload in payloads) == 1

    state = json.loads(policy.shadow_state_path.read_text(encoding="utf-8"))
    assert state["trades"] == {}
    lines = policy.shadow_evidence_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    evidence = json.loads(lines[0])
    assert evidence["trade_id"] == "trade-1"


@pytest.mark.parametrize("artifact_field", ["state_path", "evidence_path"])
def test_policy_rejects_artifact_paths_outside_canonical_data(
    tmp_path: Path,
    artifact_field: str,
) -> None:
    config = _write_config(tmp_path)
    _set_artifact_path(config, artifact_field, tmp_path / f"outside-{artifact_field}")

    with pytest.raises(ValueError, match=r"relative path|canonical E13 data root"):
        load_e13_policy(config)


@pytest.mark.parametrize("artifact_field", ["state_path", "evidence_path"])
def test_policy_rejects_absolute_paths_even_inside_canonical_data(
    tmp_path: Path,
    artifact_field: str,
) -> None:
    config = _write_config(tmp_path)
    inside = canonical_e13_data_root() / "absolute-alias" / f"{artifact_field}.json"
    _set_artifact_path(config, artifact_field, inside)

    with pytest.raises(ValueError, match="must be a relative path"):
        load_e13_policy(config)


@pytest.mark.parametrize("artifact_field", ["state_path", "evidence_path"])
def test_policy_rejects_lexical_path_traversal(
    tmp_path: Path,
    artifact_field: str,
) -> None:
    config = _write_config(tmp_path)
    _set_artifact_path(
        config,
        artifact_field,
        f"data/e13-tests/temporary/../{artifact_field}.json",
    )

    with pytest.raises(ValueError, match="path traversal"):
        load_e13_policy(config)


@pytest.mark.parametrize("artifact_field", ["state_path", "evidence_path"])
def test_policy_rejects_symlinked_artifacts(
    tmp_path: Path,
    artifact_field: str,
) -> None:
    config = _write_config(tmp_path)
    policy = load_e13_policy(config)
    artifact = (
        policy.shadow_state_path
        if artifact_field == "state_path"
        else policy.shadow_evidence_path
    )
    artifact.parent.mkdir(parents=True, exist_ok=True)
    target = artifact.with_suffix(f"{artifact.suffix}.target")
    target.write_text("{}\n", encoding="utf-8")
    artifact.symlink_to(target)

    with pytest.raises(ValueError, match="must not be a symlink"):
        load_e13_policy(config)


@pytest.mark.parametrize("artifact_field", ["state_path", "evidence_path"])
def test_policy_rejects_hardlinked_artifacts(
    tmp_path: Path,
    artifact_field: str,
) -> None:
    config = _write_config(tmp_path)
    policy = load_e13_policy(config)
    artifact = (
        policy.shadow_state_path
        if artifact_field == "state_path"
        else policy.shadow_evidence_path
    )
    artifact.parent.mkdir(parents=True, exist_ok=True)
    target = artifact.with_suffix(f"{artifact.suffix}.target")
    target.write_text("{}\n", encoding="utf-8")
    os.link(target, artifact)

    with pytest.raises(ValueError, match="must not be hard-linked"):
        load_e13_policy(config)


@pytest.mark.parametrize("artifact_field", ["state_path", "evidence_path"])
def test_policy_rejects_symlinked_artifact_parent(
    tmp_path: Path,
    artifact_field: str,
) -> None:
    config = _write_config(tmp_path)
    path_id = hashlib.sha256(str(tmp_path).encode()).hexdigest()[:12]
    alias_parent = canonical_e13_data_root() / "e13-tests" / f"parent-alias-{path_id}"
    target_parent = canonical_e13_data_root() / "e13-tests" / f"parent-target-{path_id}"
    target_parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    alias_parent.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    alias_parent.symlink_to(target_parent, target_is_directory=True)
    relative = alias_parent.relative_to(canonical_e13_data_root().parent)
    _set_artifact_path(config, artifact_field, relative / f"{artifact_field}.json")

    with pytest.raises(ValueError, match="parent must not be a symlink"):
        load_e13_policy(config)


@pytest.mark.parametrize("artifact_field", ["state_path", "evidence_path"])
def test_policy_rejects_nonregular_or_unsafe_mode_artifacts(
    tmp_path: Path,
    artifact_field: str,
) -> None:
    config = _write_config(tmp_path)
    policy = load_e13_policy(config)
    artifact = (
        policy.shadow_state_path
        if artifact_field == "state_path"
        else policy.shadow_evidence_path
    )
    artifact.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    artifact.write_text("{}\n", encoding="utf-8")
    artifact.chmod(0o644)

    with pytest.raises(ValueError, match="safe mode 0600"):
        load_e13_policy(config)


def test_policy_rejects_nonregular_artifact(tmp_path: Path) -> None:
    config = _write_config(tmp_path)
    policy = load_e13_policy(config)
    policy.shadow_state_path.mkdir(mode=0o700, parents=True)

    with pytest.raises(ValueError, match="must be a regular file"):
        load_e13_policy(config)


def test_policy_rejects_artifact_not_owned_by_current_uid(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _write_config(tmp_path)
    policy = load_e13_policy(config)
    policy.shadow_state_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    policy.shadow_state_path.write_text("{}\n", encoding="utf-8")
    policy.shadow_state_path.chmod(0o600)
    current_uid = os.geteuid()
    monkeypatch.setattr(e13_storage.os, "geteuid", lambda: current_uid + 1)

    with pytest.raises(ValueError, match="owned by the current uid"):
        load_e13_policy(config)


def test_policy_hash_binds_artifact_paths_and_configs_share_one_lock(
    tmp_path: Path,
) -> None:
    first = load_e13_policy(_write_config(tmp_path / "first"))
    second = load_e13_policy(_write_config(tmp_path / "second"))

    assert first.shadow_state_path != second.shadow_state_path
    assert first.shadow_evidence_path != second.shadow_evidence_path
    assert first.policy_hash_sha256 != second.policy_hash_sha256
    assert e13_shadow_lock_path(first.shadow_state_path) == e13_shadow_lock_path(
        second.shadow_state_path
    )


def test_policy_hash_binds_config_provenance_with_identical_artifact_pair(
    tmp_path: Path,
) -> None:
    first_config = _write_config(tmp_path / "first")
    second_config = _write_config(tmp_path / "second")
    first = load_e13_policy(first_config)
    runtime_root = canonical_e13_data_root().parent
    _set_artifact_path(
        second_config,
        "state_path",
        first.shadow_state_path.relative_to(runtime_root),
    )
    _set_artifact_path(
        second_config,
        "evidence_path",
        first.shadow_evidence_path.relative_to(runtime_root),
    )
    second = load_e13_policy(second_config)

    assert second.shadow_state_path == first.shadow_state_path
    assert second.shadow_evidence_path == first.shadow_evidence_path
    assert second.config_path != first.config_path
    assert second.policy_hash_sha256 != first.policy_hash_sha256


@pytest.mark.subprocess
def test_alternate_config_cannot_race_the_canonical_global_lease(
    tmp_path: Path,
) -> None:
    opened = datetime(2026, 7, 10, tzinfo=UTC)
    first = load_e13_policy(_write_config(tmp_path / "first"))
    second_config = _write_config(tmp_path / "second")
    _set_artifact_path(
        second_config,
        "evidence_path",
        first.shadow_evidence_path.relative_to(canonical_e13_data_root().parent),
    )
    second = load_e13_policy(second_config)
    assert second.shadow_state_path != first.shadow_state_path
    assert second.shadow_evidence_path == first.shadow_evidence_path
    journal = tmp_path / "journal.duckdb"
    market = tmp_path / "market.duckdb"
    _write_open_journal(journal, opened)
    _write_market(market, opened)
    ready = tmp_path / "alternate-lease.ready"
    holder_code = """
import sys
import time
from pathlib import Path

from price_action.execution.e13_shadow import E13ShadowLease

with E13ShadowLease(sys.argv[1]):
    Path(sys.argv[2]).write_text("ready", encoding="utf-8")
    time.sleep(30)
"""
    holder = subprocess.Popen(
        [sys.executable, "-c", holder_code, str(first.shadow_state_path), str(ready)],
        cwd=ROOT,
        env=_subprocess_env(),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        _wait_for_file(ready, holder)
        result = sync_e13_shadow(
            journal,
            market,
            config_path=second_config,
            through=opened + timedelta(minutes=45),
        )
    finally:
        holder.kill()
        holder.wait(timeout=5)

    assert result["status"] == "HOLD_WRITER_BUSY"
    assert result["mutated_real_artifacts"] is False
    assert not second.shadow_state_path.exists()
    assert not second.shadow_evidence_path.exists()


@pytest.mark.subprocess
@pytest.mark.parametrize(
    "cutpoint",
    ["after_transaction", "after_evidence", "after_state"],
)
def test_sigkill_cutpoints_recover_to_one_valid_evidence_record(
    tmp_path: Path,
    cutpoint: str,
) -> None:
    opened = datetime(2026, 7, 10, tzinfo=UTC)
    config = _write_config(tmp_path)
    policy = load_e13_policy(config)
    journal = tmp_path / "journal.duckdb"
    market = tmp_path / "market.duckdb"
    _write_open_journal(journal, opened)
    _write_market(market, opened)
    sync_e13_shadow(
        journal,
        market,
        config_path=config,
        through=opened + timedelta(minutes=45),
    )
    _close_journal(journal, opened)

    env = _subprocess_env()
    env["PA_E13_TEST_CUTPOINT"] = cutpoint
    killed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/e13_shadow_tick.py"),
            "--config",
            str(config),
            "--journal",
            str(journal),
            "--market",
            str(market),
            "--through",
            (opened + timedelta(hours=2)).isoformat(),
            "--json",
        ],
        cwd=ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )

    assert killed.returncode == -signal.SIGKILL
    assert e13_transaction_path().is_file()
    interrupted_gate = e13_exit_evidence(journal, config_path=config)
    assert interrupted_gate["formal_review_ready"] is False
    assert interrupted_gate["paired_shadow_integrity_pass"] is False
    assert interrupted_gate["invalid_paired_shadow_records"] == {
        "pending_recovery_transaction": 1
    }
    recovered = sync_e13_shadow(
        journal,
        market,
        config_path=config,
        through=opened + timedelta(hours=2),
    )

    assert recovered["status"] == "OK"
    assert recovered["mutated_real_artifacts"] is True
    assert not e13_transaction_path().exists()
    state = json.loads(policy.shadow_state_path.read_text(encoding="utf-8"))
    assert state["trades"] == {}
    evidence_lines = policy.shadow_evidence_path.read_text(encoding="utf-8").splitlines()
    assert len(evidence_lines) == 1
    assert json.loads(evidence_lines[0])["trade_id"] == "trade-1"


@pytest.mark.subprocess
@pytest.mark.parametrize(
    "cutpoint",
    ["after_transaction", "after_evidence", "after_state"],
)
def test_exception_cutpoints_report_mutation_and_recover_exactly_once(
    tmp_path: Path,
    cutpoint: str,
) -> None:
    opened = datetime(2026, 7, 10, tzinfo=UTC)
    config = _write_config(tmp_path)
    policy = load_e13_policy(config)
    journal = tmp_path / "journal.duckdb"
    market = tmp_path / "market.duckdb"
    _write_open_journal(journal, opened)
    _write_market(market, opened)
    sync_e13_shadow(
        journal,
        market,
        config_path=config,
        through=opened + timedelta(minutes=45),
    )
    _close_journal(journal, opened)

    env = _subprocess_env()
    env["PA_E13_TEST_CUTPOINT"] = cutpoint
    env["PA_E13_TEST_CUTPOINT_ACTION"] = "exception"
    failed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/e13_shadow_tick.py"),
            "--config",
            str(config),
            "--journal",
            str(journal),
            "--market",
            str(market),
            "--through",
            (opened + timedelta(hours=2)).isoformat(),
            "--json",
        ],
        cwd=ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )

    assert failed.returncode == 2, failed.stdout + failed.stderr
    payload = json.loads(failed.stdout)
    assert payload["status"] == "FAIL_CLOSED"
    assert payload["mutated_real_artifacts"] is True
    assert payload["mutation_outcome"] == "mutated"
    assert e13_transaction_path().is_file()
    interrupted_gate = e13_exit_evidence(journal, config_path=config)
    assert interrupted_gate["formal_review_ready"] is False
    assert interrupted_gate["invalid_paired_shadow_records"] == {
        "pending_recovery_transaction": 1
    }

    recovered = sync_e13_shadow(
        journal,
        market,
        config_path=config,
        through=opened + timedelta(hours=2),
    )
    assert recovered["status"] == "OK"
    assert not e13_transaction_path().exists()
    state = json.loads(policy.shadow_state_path.read_text(encoding="utf-8"))
    assert state["trades"] == {}
    evidence_lines = policy.shadow_evidence_path.read_text(
        encoding="utf-8"
    ).splitlines()
    assert len(evidence_lines) == 1
    assert json.loads(evidence_lines[0])["trade_id"] == "trade-1"


@pytest.mark.subprocess
def test_generic_tick_failure_reports_unknown_mutation_outcome(tmp_path: Path) -> None:
    missing_config = tmp_path / "missing.yaml"
    missing_journal = tmp_path / "missing-journal.duckdb"
    missing_market = tmp_path / "missing-market.duckdb"
    failed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/e13_shadow_tick.py"),
            "--config",
            str(missing_config),
            "--journal",
            str(missing_journal),
            "--market",
            str(missing_market),
            "--json",
        ],
        cwd=ROOT,
        env=_subprocess_env(),
        check=False,
        capture_output=True,
        text=True,
    )

    assert failed.returncode == 2
    payload = json.loads(failed.stdout)
    assert payload["status"] == "FAIL_CLOSED"
    assert payload["mutated_real_artifacts"] is None
    assert payload["mutated_artifact_paths"] is None
    assert payload["mutation_outcome"] == "unknown"


def test_corrupt_evidence_tail_fails_gate_and_is_quarantined_without_rewrite(
    tmp_path: Path,
) -> None:
    opened = datetime(2026, 7, 10, tzinfo=UTC)
    config = _write_config(tmp_path)
    policy = load_e13_policy(config)
    journal = tmp_path / "journal.duckdb"
    market = tmp_path / "market.duckdb"
    _write_open_journal(journal, opened)
    _write_market(market, opened)
    sync_e13_shadow(
        journal,
        market,
        config_path=config,
        through=opened + timedelta(minutes=45),
    )
    _close_journal(journal, opened)
    sync_e13_shadow(
        journal,
        market,
        config_path=config,
        through=opened + timedelta(hours=2),
    )
    with policy.shadow_evidence_path.open("a", encoding="utf-8") as handle:
        handle.write('{"partial":')
    corrupt_payload = policy.shadow_evidence_path.read_text(encoding="utf-8")

    gate = e13_exit_evidence(journal, config_path=config)
    assert gate["paired_shadow_closed_trades"] == 1
    assert gate["invalid_paired_shadow_records"] == {"invalid_json": 1}
    assert gate["paired_shadow_integrity_pass"] is False
    assert gate["formal_review_ready"] is False
    assert gate["decision"] == "HOLD_PAIRED_SHADOW_EVIDENCE_INTEGRITY"

    with pytest.raises(E13ShadowMutationError) as captured:
        sync_e13_shadow(
            journal,
            market,
            config_path=config,
            through=opened + timedelta(hours=2),
        )

    assert captured.value.mutated_real_artifacts is True
    assert policy.shadow_evidence_path.read_text(encoding="utf-8") == corrupt_payload
    quarantines = list(
        policy.shadow_evidence_path.parent.glob(
            f".{policy.shadow_evidence_path.name}.corrupt-*.quarantine"
        )
    )
    assert len(quarantines) == 1
    assert quarantines[0].read_text(encoding="utf-8") == corrupt_payload
    assert oct(quarantines[0].stat().st_mode & 0o777) == "0o600"


def test_exception_after_atomic_replace_reports_mutation_truth(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    opened = datetime(2026, 7, 10, tzinfo=UTC)
    config = _write_config(tmp_path)
    policy = load_e13_policy(config)
    journal = tmp_path / "journal.duckdb"
    market = tmp_path / "market.duckdb"
    _write_open_journal(journal, opened)
    _write_market(market, opened)
    real_fsync_directory = e13_storage.fsync_directory

    def fail_after_state_replace(path: str | Path) -> None:
        real_fsync_directory(path)
        if Path(path) == policy.shadow_state_path.parent:
            raise OSError("injected parent fsync report failure")

    monkeypatch.setattr(e13_storage, "fsync_directory", fail_after_state_replace)

    with pytest.raises(E13ShadowMutationError) as captured:
        sync_e13_shadow(
            journal,
            market,
            config_path=config,
            through=opened + timedelta(minutes=45),
        )

    assert captured.value.mutated_real_artifacts is True
    assert str(policy.shadow_state_path) in captured.value.mutation_paths
    persisted = json.loads(policy.shadow_state_path.read_text(encoding="utf-8"))
    assert "trade-1" in persisted["trades"]


@pytest.mark.parametrize(
    ("side", "trailing"),
    [("long", False), ("long", True), ("short", False), ("short", True)],
)
def test_state_validator_accepts_valid_side_aware_trailing_states(
    tmp_path: Path,
    side: str,
    trailing: bool,
) -> None:
    opened = datetime(2026, 7, 10, tzinfo=UTC)
    config = _write_config(tmp_path / f"{side}-{trailing}")
    policy = load_e13_policy(config)
    recorder = AtrChandelierShadowRecorder(policy)
    initial_sl = 98 if side == "long" else 102
    recorder.start_trade(
        trade_id="trade-1",
        side=side,
        ts_open=opened,
        entry_price=100,
        initial_sl_price=initial_sl,
    )
    if side == "long" and trailing:
        bar = {"open_price": 100, "high": 103.5, "low": 99.5, "close": 103}
    elif side == "long":
        bar = {"open_price": 100, "high": 101, "low": 99, "close": 100.5}
    elif trailing:
        bar = {"open_price": 100, "high": 100.5, "low": 96.5, "close": 97}
    else:
        bar = {"open_price": 100, "high": 101, "low": 99, "close": 99.5}
    recorder.observe_closed_bar(
        trade_id="trade-1",
        ts=opened + timedelta(minutes=15),
        atr=1,
        **bar,
    )

    state = json.loads(policy.shadow_state_path.read_text(encoding="utf-8"))
    validate_e13_shadow_state_document(
        state,
        policy,
        expected_hash=policy.policy_hash_sha256,
    )
    loaded = AtrChandelierShadowRecorder(policy).trade_state("trade-1")
    assert loaded is not None
    assert loaded["trail_activated"] is trailing
    assert loaded["active_stop"] == (
        102 if side == "long" and trailing else 98 if trailing else initial_sl
    )


def test_recorder_rejects_off_grid_and_boolean_inputs_but_keeps_duplicate_idempotency(
    tmp_path: Path,
) -> None:
    opened = datetime(2026, 7, 10, tzinfo=UTC)
    config = _write_config(tmp_path)
    policy = load_e13_policy(config)
    recorder = AtrChandelierShadowRecorder(policy)

    with pytest.raises(ValueError, match="UTC 15m epoch grid"):
        recorder.start_trade(
            trade_id="off-grid",
            side="long",
            ts_open=opened + timedelta(minutes=1),
            entry_price=100,
            initial_sl_price=98,
        )
    with pytest.raises(ValueError, match="entry_price must be numeric"):
        recorder.start_trade(
            trade_id="boolean-entry",
            side="long",
            ts_open=opened,
            entry_price=True,
            initial_sl_price=0.5,
        )

    recorder.start_trade(
        trade_id="trade-1",
        side="long",
        ts_open=opened,
        entry_price=100,
        initial_sl_price=98,
    )
    with pytest.raises(ValueError, match="UTC 15m epoch grid"):
        recorder.observe_closed_bar(
            trade_id="trade-1",
            ts=opened + timedelta(minutes=16),
            open_price=100,
            high=101,
            low=99,
            close=100.5,
            atr=1,
        )
    first = recorder.observe_closed_bar(
        trade_id="trade-1",
        ts=opened + timedelta(minutes=15),
        open_price=100,
        high=101,
        low=99,
        close=100.5,
        atr=1,
    )
    duplicate = recorder.observe_closed_bar(
        trade_id="trade-1",
        ts=opened + timedelta(minutes=15),
        open_price=True,
        high=True,
        low=True,
        close=True,
        atr=True,
    )
    assert duplicate == first
    assert duplicate["bars_observed"] == 1

    with pytest.raises(ValueError, match="baseline_realized_r must be numeric"):
        recorder.record_baseline_close(
            trade_id="trade-1",
            ts_close=opened + timedelta(minutes=20),
            exit_price=102,
            close_reason="tp",
            baseline_realized_r=True,
        )
    with pytest.raises(ValueError, match="baseline_realized_r must be finite"):
        recorder.record_baseline_close(
            trade_id="trade-1",
            ts_close=opened + timedelta(minutes=20),
            exit_price=102,
            close_reason="tp",
            baseline_realized_r=float("nan"),
        )

    terminal = recorder.observe_closed_bar(
        trade_id="trade-1",
        ts=opened + timedelta(minutes=30),
        open_price=100,
        high=100,
        low=98,
        close=99,
        atr=1,
    )
    terminal_duplicate = recorder.observe_closed_bar(
        trade_id="trade-1",
        ts=opened + timedelta(minutes=30),
        open_price=True,
        high=True,
        low=True,
        close=True,
        atr=True,
    )
    assert terminal_duplicate == terminal
    with pytest.raises(ValueError, match="chronological"):
        recorder.observe_closed_bar(
            trade_id="trade-1",
            ts=opened + timedelta(minutes=15),
            open_price=100,
            high=101,
            low=99,
            close=100,
            atr=1,
        )
    with pytest.raises(ValueError, match="UTC 15m epoch grid"):
        recorder.observe_closed_bar(
            trade_id="trade-1",
            ts=opened + timedelta(minutes=31),
            open_price=100,
            high=101,
            low=99,
            close=100,
            atr=1,
        )


@pytest.mark.parametrize(
    "case",
    [
        "inactive_stop_one",
        "reversed_initial_stop",
        "active_trail_out_of_bounds",
        "wrong_side_water",
        "bars_without_last_bar",
        "partial_candidate_terminal",
        "two_terminal_outcomes",
        "reversed_last_timestamp",
        "nonfinite_water",
        "off_grid_last_bar",
        "impossible_bar_count",
        "boolean_baseline_r",
    ],
)
def test_migration_rejects_impossible_legacy_state_matrix(
    tmp_path: Path,
    case: str,
) -> None:
    opened = datetime(2026, 7, 10, tzinfo=UTC)
    config = _write_config(tmp_path / case)
    policy = load_e13_policy(config)
    recorder = AtrChandelierShadowRecorder(policy)
    recorder.start_trade(
        trade_id="trade-1",
        side="long",
        ts_open=opened,
        entry_price=100,
        initial_sl_price=98,
    )
    old_hash, new_hash = _downgrade_to_legacy_policy_hash(config)
    state = json.loads(policy.shadow_state_path.read_text(encoding="utf-8"))
    record = state["trades"]["trade-1"]
    if case == "inactive_stop_one":
        record["active_stop"] = 1
    elif case == "reversed_initial_stop":
        record["initial_sl_price"] = 102
        record["active_stop"] = 102
    elif case == "active_trail_out_of_bounds":
        record.update(
            {
                "bars_observed": 1,
                "last_bar_utc": (opened + timedelta(minutes=15)).isoformat(),
                "trail_activated": True,
                "high_water": 103,
                "active_stop": 1,
            }
        )
    elif case == "wrong_side_water":
        record["low_water"] = 99
    elif case == "bars_without_last_bar":
        record["bars_observed"] = 1
    elif case == "partial_candidate_terminal":
        record["candidate_exit_price"] = 98
    elif case == "two_terminal_outcomes":
        record.update(
            {
                "bars_observed": 1,
                "last_bar_utc": (opened + timedelta(minutes=15)).isoformat(),
                "candidate_exit_price": 98,
                "candidate_closed_at_utc": (
                    opened + timedelta(minutes=15)
                ).isoformat(),
                "candidate_close_reason": "shared_initial_stop",
                "baseline_exit_price": 101,
                "baseline_closed_at_utc": (
                    opened + timedelta(minutes=20)
                ).isoformat(),
                "baseline_close_reason": "sl",
                "baseline_realized_r": 0.5,
            }
        )
    elif case == "reversed_last_timestamp":
        record["bars_observed"] = 1
        record["last_bar_utc"] = opened.isoformat()
    elif case == "nonfinite_water":
        record["high_water"] = float("nan")
    elif case == "off_grid_last_bar":
        record.update(
            {
                "bars_observed": 1,
                "last_bar_utc": (opened + timedelta(minutes=16)).isoformat(),
                "high_water": 101,
            }
        )
    elif case == "impossible_bar_count":
        record.update(
            {
                "bars_observed": 100,
                "last_bar_utc": (opened + timedelta(minutes=15)).isoformat(),
                "high_water": 101,
            }
        )
    else:
        record.update(
            {
                "bars_observed": 1,
                "last_bar_utc": (opened + timedelta(minutes=15)).isoformat(),
                "high_water": 101,
                "baseline_exit_price": 102,
                "baseline_closed_at_utc": (
                    opened + timedelta(minutes=20)
                ).isoformat(),
                "baseline_close_reason": "tp",
                "baseline_realized_r": True,
            }
        )
    policy.shadow_state_path.write_text(
        json.dumps(state, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )

    result = migrate_e13_policy_provenance(
        config_path=config,
        expected_old_hash=old_hash,
        expected_new_hash=new_hash,
        operator_reason="reject impossible legacy state",
    )

    assert result["status"] == "HOLD_STATE_INTEGRITY"
    assert result["mutated_real_artifacts"] is False
    assert not e13_policy_migration_transaction_path().exists()


def test_migration_accepts_valid_missed_bar_capacity_state(tmp_path: Path) -> None:
    opened = datetime(2026, 7, 10, 23, 0, tzinfo=UTC)
    config = _write_config(tmp_path)
    policy = load_e13_policy(config)
    recorder = AtrChandelierShadowRecorder(policy)
    recorder.start_trade(
        trade_id="trade-1",
        side="long",
        ts_open=opened,
        entry_price=100,
        initial_sl_price=98,
    )
    old_hash, new_hash = _downgrade_to_legacy_policy_hash(config)
    state = json.loads(policy.shadow_state_path.read_text(encoding="utf-8"))
    state["trades"]["trade-1"].update(
        {
            "bars_observed": 2,
            "last_bar_utc": (opened + timedelta(minutes=45)).isoformat(),
            "high_water": 101,
        }
    )
    policy.shadow_state_path.write_text(
        json.dumps(state, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )

    result = migrate_e13_policy_provenance(
        config_path=config,
        expected_old_hash=old_hash,
        expected_new_hash=new_hash,
        operator_reason="allow bounded missed bar state",
    )

    assert result["status"] == "HOLD_REQUIRES_APPLY_LOCK"
    assert result["static_validation_pass"] is True
    assert result["mutated_real_artifacts"] is False


def test_recorder_rejects_semantically_impossible_existing_state(tmp_path: Path) -> None:
    opened = datetime(2026, 7, 10, tzinfo=UTC)
    config = _write_config(tmp_path)
    policy = load_e13_policy(config)
    recorder = AtrChandelierShadowRecorder(policy)
    recorder.start_trade(
        trade_id="trade-1",
        side="long",
        ts_open=opened,
        entry_price=100,
        initial_sl_price=98,
    )
    state = json.loads(policy.shadow_state_path.read_text(encoding="utf-8"))
    state["trades"]["trade-1"]["active_stop"] = 1
    policy.shadow_state_path.write_text(
        json.dumps(state, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="inactive stop drifted"):
        AtrChandelierShadowRecorder(policy)


def test_sync_rejects_existing_state_with_different_baseline_identity(
    tmp_path: Path,
) -> None:
    opened = datetime(2026, 7, 10, tzinfo=UTC)
    config = _write_config(tmp_path)
    policy = load_e13_policy(config)
    journal = tmp_path / "journal.duckdb"
    market = tmp_path / "market.duckdb"
    _write_open_journal(journal, opened)
    _write_market(market, opened)
    sync_e13_shadow(
        journal,
        market,
        config_path=config,
        through=opened + timedelta(minutes=45),
    )
    state_before = policy.shadow_state_path.read_text(encoding="utf-8")
    with duckdb.connect(str(journal)) as connection:
        connection.execute(
            "UPDATE futures_signals SET fill_price=101, sl_price=98 "
            "WHERE signal_id='trade-1'"
        )

    result = sync_e13_shadow(
        journal,
        market,
        config_path=config,
        through=opened + timedelta(minutes=45),
    )

    assert result["status"] == "HOLD_LOCAL_EVIDENCE_GAPS"
    assert result["invalid_baselines"] == 1
    assert result["issues"] == [
        {
            "trade_id": "trade-1",
            "code": "state_baseline_identity_mismatch",
            "detail": "conflicting E13 shadow trade identity: trade-1",
        }
    ]
    assert policy.shadow_state_path.read_text(encoding="utf-8") == state_before


def test_policy_migration_dry_run_apply_and_idempotent_with_consistent_evidence(
    tmp_path: Path,
) -> None:
    opened = datetime(2026, 7, 10, tzinfo=UTC)
    config = _write_config(tmp_path)
    policy = load_e13_policy(config)
    journal = tmp_path / "journal.duckdb"
    market = tmp_path / "market.duckdb"
    _write_open_journal(journal, opened)
    _write_market(market, opened)
    sync_e13_shadow(
        journal,
        market,
        config_path=config,
        through=opened + timedelta(minutes=45),
    )
    _close_journal(journal, opened)
    sync_e13_shadow(
        journal,
        market,
        config_path=config,
        through=opened + timedelta(hours=2),
    )
    old_hash, new_hash = _downgrade_to_legacy_policy_hash(config)
    state_before = policy.shadow_state_path.read_text(encoding="utf-8")
    evidence_before = policy.shadow_evidence_path.read_text(encoding="utf-8")
    reason = "controlled legacy provenance upgrade"
    lock_path = e13_shadow_lock_path(policy.shadow_state_path)
    lock_before = (lock_path.read_text(encoding="utf-8"), lock_path.stat().st_mtime_ns)
    tree_before = _filesystem_snapshot(canonical_e13_data_root())

    dry_run = migrate_e13_policy_provenance(
        config_path=config,
        expected_old_hash=old_hash,
        expected_new_hash=new_hash,
        operator_reason=reason,
    )
    assert dry_run["status"] == "HOLD_REQUIRES_APPLY_LOCK"
    assert dry_run["dry_run"] is True
    assert dry_run["static_validation_pass"] is True
    assert dry_run["ready_for_locked_apply"] is True
    assert dry_run["filesystem_unchanged"] is True
    assert dry_run["mutated_real_artifacts"] is False
    assert policy.shadow_state_path.read_text(encoding="utf-8") == state_before
    assert policy.shadow_evidence_path.read_text(encoding="utf-8") == evidence_before
    assert not Path(dry_run["state_backup_path"]).exists()
    assert not e13_policy_migration_transaction_path().exists()
    assert (lock_path.read_text(encoding="utf-8"), lock_path.stat().st_mtime_ns) == lock_before
    assert _filesystem_snapshot(canonical_e13_data_root()) == tree_before

    applied = migrate_e13_policy_provenance(
        config_path=config,
        expected_old_hash=old_hash,
        expected_new_hash=new_hash,
        operator_reason=reason,
        apply=True,
    )
    assert applied["status"] == "MIGRATED"
    assert applied["evidence_records_migrated"] == 1
    assert applied["mutated_real_artifacts"] is True
    assert not e13_policy_migration_transaction_path().exists()
    migrated_state = json.loads(policy.shadow_state_path.read_text(encoding="utf-8"))
    assert migrated_state["policy_hash_sha256"] == new_hash
    assert migrated_state["policy_provenance_version"] == 2
    legacy_state = json.loads(state_before)
    assert migrated_state["schema_version"] == legacy_state["schema_version"]
    assert migrated_state["trades"] == legacy_state["trades"]
    migrated_evidence = json.loads(
        policy.shadow_evidence_path.read_text(encoding="utf-8")
    )
    assert migrated_evidence["policy_hash_sha256"] == new_hash
    assert migrated_evidence["policy_provenance_version"] == 2
    legacy_evidence = json.loads(evidence_before)
    for field in ("policy_hash_sha256", "policy_provenance_version"):
        migrated_evidence.pop(field, None)
        legacy_evidence.pop(field, None)
    assert migrated_evidence == legacy_evidence
    assert Path(applied["state_backup_path"]).read_text(
        encoding="utf-8"
    ) == state_before
    assert Path(applied["evidence_backup_path"]).read_text(
        encoding="utf-8"
    ) == evidence_before

    repeated = migrate_e13_policy_provenance(
        config_path=config,
        expected_old_hash=old_hash,
        expected_new_hash=new_hash,
        operator_reason=reason,
        apply=True,
    )
    assert repeated["status"] == "ALREADY_MIGRATED"
    assert repeated["mutated_real_artifacts"] is False
    audit_records = [
        json.loads(line)
        for line in e13_policy_migration_audit_path().read_text(
            encoding="utf-8"
        ).splitlines()
    ]
    assert sum(
        record.get("migration_id") == applied["migration_id"]
        for record in audit_records
    ) == 1


def test_policy_migration_dry_run_does_not_create_an_empty_runtime_tree(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime_root = tmp_path / "empty-runtime"
    monkeypatch.setenv("PA_RUNTIME_ROOT", str(runtime_root))
    config = _write_config(tmp_path / "config")
    policy = load_e13_policy(config)
    old_hash = e13_legacy_semantic_policy_hash(policy)

    assert not runtime_root.exists()
    before = _filesystem_snapshot(runtime_root)
    result = migrate_e13_policy_provenance(
        config_path=config,
        expected_old_hash=old_hash,
        expected_new_hash=policy.policy_hash_sha256,
        operator_reason="read only validation on empty runtime",
    )

    assert result["status"] == "HOLD_STATE_MISSING"
    assert result["dry_run"] is True
    assert result["mutated_real_artifacts"] is False
    assert not (runtime_root / "data" / ".e13_shadow.writer.lock").exists()
    assert _filesystem_snapshot(runtime_root) == before
    assert not runtime_root.exists()


@pytest.mark.parametrize("wrong_field", ["old", "new"])
def test_policy_migration_rejects_wrong_expected_hash(
    tmp_path: Path,
    wrong_field: str,
) -> None:
    opened = datetime(2026, 7, 10, tzinfo=UTC)
    config = _write_config(tmp_path)
    policy = load_e13_policy(config)
    journal = tmp_path / "journal.duckdb"
    market = tmp_path / "market.duckdb"
    _write_open_journal(journal, opened)
    _write_market(market, opened)
    sync_e13_shadow(
        journal,
        market,
        config_path=config,
        through=opened + timedelta(minutes=45),
    )
    old_hash, new_hash = _downgrade_to_legacy_policy_hash(config)
    before = policy.shadow_state_path.read_text(encoding="utf-8")

    result = migrate_e13_policy_provenance(
        config_path=config,
        expected_old_hash="0" * 64 if wrong_field == "old" else old_hash,
        expected_new_hash="f" * 64 if wrong_field == "new" else new_hash,
        operator_reason="reject wrong expected migration hash",
        apply=True,
    )

    expected_status = (
        "HOLD_SEMANTIC_DRIFT_OR_OLD_HASH_MISMATCH"
        if wrong_field == "old"
        else "HOLD_NEW_HASH_MISMATCH"
    )
    assert result["status"] == expected_status
    assert result["mutated_real_artifacts"] is False
    assert policy.shadow_state_path.read_text(encoding="utf-8") == before
    assert not e13_policy_migration_transaction_path().exists()


def test_policy_migration_rejects_semantic_drift_and_invalid_state(
    tmp_path: Path,
) -> None:
    opened = datetime(2026, 7, 10, tzinfo=UTC)
    config = _write_config(tmp_path)
    policy = load_e13_policy(config)
    journal = tmp_path / "journal.duckdb"
    market = tmp_path / "market.duckdb"
    _write_open_journal(journal, opened)
    _write_market(market, opened)
    sync_e13_shadow(
        journal,
        market,
        config_path=config,
        through=opened + timedelta(minutes=45),
    )
    old_hash, _new_hash = _downgrade_to_legacy_policy_hash(config)
    original_state = policy.shadow_state_path.read_text(encoding="utf-8")
    config.write_text(
        config.read_text(encoding="utf-8").replace("multiplier: 1.5", "multiplier: 1.6"),
        encoding="utf-8",
    )
    drifted_policy = load_e13_policy(config)

    drifted = migrate_e13_policy_provenance(
        config_path=config,
        expected_old_hash=old_hash,
        expected_new_hash=drifted_policy.policy_hash_sha256,
        operator_reason="semantic drift must not be migrated",
        apply=True,
    )
    assert drifted["status"] == "HOLD_SEMANTIC_DRIFT_OR_OLD_HASH_MISMATCH"
    assert drifted["mutated_real_artifacts"] is False
    assert policy.shadow_state_path.read_text(encoding="utf-8") == original_state

    config.write_text(
        config.read_text(encoding="utf-8").replace("multiplier: 1.6", "multiplier: 1.5"),
        encoding="utf-8",
    )
    state = json.loads(original_state)
    state["trades"]["trade-1"]["risk_per_unit"] = 999
    policy.shadow_state_path.write_text(
        json.dumps(state, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    invalid = migrate_e13_policy_provenance(
        config_path=config,
        expected_old_hash=old_hash,
        expected_new_hash=load_e13_policy(config).policy_hash_sha256,
        operator_reason="invalid state must remain fail closed",
        apply=True,
    )
    assert invalid["status"] == "HOLD_STATE_INTEGRITY"
    assert invalid["mutated_real_artifacts"] is False


@pytest.mark.subprocess
def test_policy_migration_sigkill_recovers_and_blocks_readers_until_complete(
    tmp_path: Path,
) -> None:
    opened = datetime(2026, 7, 10, tzinfo=UTC)
    config = _write_config(tmp_path)
    policy = load_e13_policy(config)
    journal = tmp_path / "journal.duckdb"
    market = tmp_path / "market.duckdb"
    _write_open_journal(journal, opened)
    _write_market(market, opened)
    sync_e13_shadow(
        journal,
        market,
        config_path=config,
        through=opened + timedelta(minutes=45),
    )
    _close_journal(journal, opened)
    sync_e13_shadow(
        journal,
        market,
        config_path=config,
        through=opened + timedelta(hours=2),
    )
    old_hash, new_hash = _downgrade_to_legacy_policy_hash(config)
    reason = "recover migration after power loss proxy"
    env = _subprocess_env()
    env["PA_E13_MIGRATION_TEST_CUTPOINT"] = "after_state"
    killed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/e13_policy_migrate.py"),
            "--config",
            str(config),
            "--expected-old-hash",
            old_hash,
            "--expected-new-hash",
            new_hash,
            "--operator-reason",
            reason,
            "--apply",
            "--json",
        ],
        cwd=ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )

    assert killed.returncode == -signal.SIGKILL
    assert e13_policy_migration_transaction_path().is_file()
    gate = e13_exit_evidence(journal, config_path=config)
    assert gate["formal_review_ready"] is False
    assert gate["invalid_paired_shadow_records"] == {"pending_policy_migration": 1}
    held_tick = sync_e13_shadow(
        journal,
        market,
        config_path=config,
        through=opened + timedelta(hours=2),
    )
    assert held_tick["status"] == "HOLD_POLICY_MIGRATION_PENDING"
    assert held_tick["mutated_real_artifacts"] is False

    recovered = migrate_e13_policy_provenance(
        config_path=config,
        expected_old_hash=old_hash,
        expected_new_hash=new_hash,
        operator_reason=reason,
        apply=True,
    )
    assert recovered["status"] == "RECOVERED_AND_MIGRATED"
    assert recovered["mutated_real_artifacts"] is True
    assert not e13_policy_migration_transaction_path().exists()
    state = json.loads(policy.shadow_state_path.read_text(encoding="utf-8"))
    evidence = json.loads(policy.shadow_evidence_path.read_text(encoding="utf-8"))
    assert state["policy_hash_sha256"] == new_hash
    assert evidence["policy_hash_sha256"] == new_hash
    assert e13_exit_evidence(journal, config_path=config)["formal_review_ready"] is True
