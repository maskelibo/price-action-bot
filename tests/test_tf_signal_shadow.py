"""Signal-only TF shadow runner safety and idempotency tests."""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import duckdb
import pandas as pd
import pytest
import yaml

import price_action.lab.tf_signal_shadow as shadow_module
from price_action.lab.tf_shadow_promotion import promote_evidence
from price_action.lab.tf_signal_shadow import (
    ShadowRunError,
    StrategyCapabilityError,
    load_closed_bars,
    run_default_scan,
    run_shadow_config,
    validate_shadow_config,
)
from price_action.orchestrator.scheduler import _RESEARCH_AUTOPILOT_JOBS, JOB_TABLE
from tests.test_tf_oos_testkit import (
    AS_OF,
    make_canonical_tf_repo,
    write_principal_authorization,
)

pytestmark = pytest.mark.subprocess

_STRATEGY_SOURCE = (
    "from price_action.contracts import Signal\n"
    "from price_action.strategies.base import Strategy\n\n"
    "class EngulfingContinuationStrategy(Strategy):\n"
    "    def prepare_features(self, frame):\n"
    "        return frame\n\n"
    "    def generate_signals(self, frame):\n"
    "        row = frame.iloc[-1]\n"
    "        return [Signal(ts=row['ts'], venue='binance', symbol=row['symbol'], "
    "timeframe=row['timeframe'], direction='long', pattern_id='synthetic_test', "
    "confluence_score=2.0, sl_price=float(row['close']) - 2, "
    "tp_price=float(row['close']) + 4, suggested_size_atr=1.0)]\n"
)


def _make_promoted_repo(tmp_path: Path):
    fixture = make_canonical_tf_repo(tmp_path, strategy_source=_STRATEGY_SOURCE)
    result = promote_evidence(fixture.evidence, repo_root=fixture.root)
    return fixture, fixture.root / result["paths"]["config"]


def _market_db(path: Path, *, start: datetime, n: int = 240) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    for i in range(n):
        ts = start + timedelta(minutes=15 * i)
        price = 100.0 + i / 100
        rows.append(("binance", "BTC/USDT", "15m", ts, price, price + 1, price - 1, price, 10.0))
    con = duckdb.connect(str(path))
    try:
        con.execute(
            """
            CREATE TABLE ohlcv (
              venue VARCHAR, symbol VARCHAR, timeframe VARCHAR, ts TIMESTAMPTZ,
              open DOUBLE, high DOUBLE, low DOUBLE, close DOUBLE, volume DOUBLE
            )
            """
        )
        con.executemany("INSERT INTO ohlcv VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)
    finally:
        con.close()
    return path


def test_signal_only_runner_writes_local_journal_and_is_idempotent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture, config = _make_promoted_repo(tmp_path)
    root = fixture.root
    worker_tmp = tmp_path / "worker-tmp"
    worker_tmp.mkdir()
    monkeypatch.setattr(shadow_module.tempfile, "tempdir", str(worker_tmp))
    start = datetime(2025, 1, 1, tzinfo=UTC)
    market = _market_db(root / "data/market.duckdb", start=start)
    now = start + timedelta(minutes=15 * 240 + 30)
    authorization = write_principal_authorization(
        fixture,
        config_path=config,
        issued_at=now - timedelta(minutes=1),
        expires_at=now + timedelta(hours=1),
    )

    first = run_shadow_config(
        config,
        repo_root=root,
        market_db=market,
        now=now,
        symbols=("BTC/USDT",),
        authorization_path=authorization,
    )
    second = run_shadow_config(
        config,
        repo_root=root,
        market_db=market,
        now=now,
        symbols=("BTC/USDT",),
        authorization_path=authorization,
    )

    assert first["counts"] == {
        "symbols": 1,
        "scanned": 1,
        "already_scanned": 0,
        "signals": 1,
        "errors": 0,
    }
    assert second["counts"]["already_scanned"] == 1
    assert first["exchange_io_performed"] is False
    assert first["order_path_enabled"] is False
    journal = root / yaml.safe_load(config.read_text())["journal"]["path"]
    con = duckdb.connect(str(journal), read_only=True)
    try:
        assert con.execute("SELECT count(*) FROM shadow_scans").fetchone()[0] == 1
        row = con.execute("SELECT status, side, notes FROM shadow_signals").fetchone()
    finally:
        con.close()
    assert row[0] == "OBSERVED_SIGNAL_ONLY"
    assert row[1] == "long"
    assert json.loads(row[2])["exchange_io"] is False
    assert list(worker_tmp.glob("tf-signal-shadow-worker-*")) == []


def test_tampered_exchange_boundary_is_rejected(tmp_path: Path) -> None:
    fixture, config = _make_promoted_repo(tmp_path)
    root = fixture.root
    payload = yaml.safe_load(config.read_text())
    payload["exchange"]["order_submit_allowed"] = True
    config.write_text(yaml.safe_dump(payload), encoding="utf-8")

    with pytest.raises(ShadowRunError, match="no-exchange boundary"):
        validate_shadow_config(config, repo_root=root)


def test_config_cannot_replace_evidence_pinned_principal_key(tmp_path: Path) -> None:
    fixture, config = _make_promoted_repo(tmp_path)
    payload = yaml.safe_load(config.read_text(encoding="utf-8"))
    payload["principal_authorization"]["public_key_sha256"] = "1" * 64
    config.write_text(yaml.safe_dump(payload, sort_keys=True), encoding="utf-8")

    with pytest.raises(ShadowRunError, match="differs from canonical OOS evidence pin"):
        validate_shadow_config(config, repo_root=fixture.root)


def test_only_fully_closed_resampled_bar_is_visible(tmp_path: Path) -> None:
    start = datetime(2025, 1, 1, tzinfo=UTC)
    market = _market_db(tmp_path / "market.duckdb", start=start, n=10)
    # 10 source bars: five complete 30m buckets. At 02:15 UTC the 02:00 bucket
    # has not closed yet, so only the first four may be consumed.
    now = start + timedelta(hours=2, minutes=15)

    bars = load_closed_bars(
        market,
        symbol="BTC/USDT",
        timeframe="30m",
        now=now,
    )

    assert list(bars["ts"]) == [pd.Timestamp(start + timedelta(minutes=30 * i)) for i in range(4)]


def test_strategy_source_drift_is_rejected(tmp_path: Path) -> None:
    fixture, config = _make_promoted_repo(tmp_path)
    root = fixture.root
    module = root / "src/price_action/strategies/engulfing_continuation.py"
    module.write_text(_STRATEGY_SOURCE + "# drift\n", encoding="utf-8")

    with pytest.raises(ShadowRunError, match="hash drifted"):
        validate_shadow_config(config, repo_root=root)


def test_transitive_strategy_dependency_drift_is_rejected(tmp_path: Path) -> None:
    fixture, config = _make_promoted_repo(tmp_path)
    dependency = fixture.root / "src/price_action/strategies/classic_pa.py"
    dependency.write_text(dependency.read_text(encoding="utf-8") + "# drift\n", encoding="utf-8")

    with pytest.raises(ShadowRunError, match="transitive dependency closure"):
        validate_shadow_config(config, repo_root=fixture.root)


def test_os_sandbox_blocks_numpy_ctypes_libc_process_and_file_escape(tmp_path: Path) -> None:
    target = tmp_path / "forbidden.txt"
    snapshot = tmp_path / "snapshot"
    snapshot.mkdir()
    python_path = Path(sys.executable).absolute()
    profile = shadow_module._strategy_worker_sandbox_profile(python_path, snapshot)
    code = (
        "import ctypes, numpy as np; "
        f"rc=ctypes.CDLL(None).system(b'/usr/bin/touch {target}'); "
        "raise SystemExit(0 if rc != 0 and np.array([1]).sum() == 1 else 9)"
    )
    completed = subprocess.run(
        [
            str(shadow_module._SANDBOX_EXEC),
            "-p",
            profile,
            str(python_path),
            "-I",
            "-c",
            code,
        ],
        env={"PATH": "/usr/bin:/bin", "PYTHONDONTWRITEBYTECODE": "1"},
        cwd=snapshot,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr.decode(errors="replace")
    assert not target.exists()


def test_os_sandbox_denies_system_and_unpinned_repo_file_reads(tmp_path: Path) -> None:
    repo_secret = tmp_path / "repo-secret.txt"
    repo_secret.write_text("must-not-be-visible", encoding="utf-8")
    snapshot = tmp_path / "snapshot"
    snapshot.mkdir()
    python_path = Path(sys.executable).absolute()
    profile = shadow_module._strategy_worker_sandbox_profile(python_path, snapshot)
    code = (
        "from pathlib import Path; "
        f"paths=[Path('/etc/hosts'),Path({str(repo_secret)!r})]; "
        "blocked=0; "
        "\nfor path in paths:\n"
        " try: path.read_bytes()\n"
        " except (PermissionError, OSError): blocked += 1\n"
        "\nraise SystemExit(0 if blocked == len(paths) else 9)"
    )
    completed = subprocess.run(
        [
            str(shadow_module._SANDBOX_EXEC),
            "-p",
            profile,
            str(python_path),
            "-I",
            "-c",
            code,
        ],
        env={"PATH": "/usr/bin:/bin", "PYTHONDONTWRITEBYTECODE": "1"},
        cwd=snapshot,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr.decode(errors="replace")


def test_missing_os_sandbox_holds_before_any_journal_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture, config = _make_promoted_repo(tmp_path)
    now = AS_OF
    authorization = write_principal_authorization(
        fixture,
        config_path=config,
        issued_at=now - timedelta(minutes=1),
        expires_at=now + timedelta(hours=1),
    )
    journal = fixture.root / yaml.safe_load(config.read_text(encoding="utf-8"))["journal"][
        "path"
    ]
    monkeypatch.setattr(shadow_module, "_SANDBOX_EXEC", fixture.root / "missing-sandbox-exec")

    with pytest.raises(StrategyCapabilityError, match="sandbox-exec is required"):
        run_shadow_config(
            config,
            repo_root=fixture.root,
            now=now,
            authorization_path=authorization,
        )

    con = duckdb.connect(str(journal), read_only=True)
    try:
        assert con.execute("SELECT count(*) FROM shadow_scans").fetchone()[0] == 0
        assert con.execute("SELECT count(*) FROM shadow_signals").fetchone()[0] == 0
    finally:
        con.close()


def test_principal_signature_rejects_wrong_binding_expiry_and_nonce_copy(
    tmp_path: Path,
) -> None:
    fixture, config = _make_promoted_repo(tmp_path)

    wrong_binding = write_principal_authorization(
        fixture,
        config_path=config,
        config_sha256="0" * 64,
        issued_at=AS_OF - timedelta(minutes=1),
        expires_at=AS_OF + timedelta(hours=1),
    )
    with pytest.raises(ShadowRunError, match="identity/scope binding"):
        run_shadow_config(
            config,
            repo_root=fixture.root,
            now=AS_OF,
            authorization_path=wrong_binding,
        )

    expired = write_principal_authorization(
        fixture,
        config_path=config,
        issued_at=AS_OF - timedelta(hours=2),
        expires_at=AS_OF - timedelta(hours=1),
    )
    with pytest.raises(ShadowRunError, match="not active"):
        run_shadow_config(
            config,
            repo_root=fixture.root,
            now=AS_OF,
            authorization_path=expired,
        )

    valid = write_principal_authorization(
        fixture,
        config_path=config,
        issued_at=AS_OF - timedelta(minutes=1),
        expires_at=AS_OF + timedelta(hours=1),
    )
    copied = valid.parent / "copied-authorization.json"
    copied.write_bytes(valid.read_bytes())
    with pytest.raises(ShadowRunError, match="nonce replayed"):
        run_shadow_config(
            config,
            repo_root=fixture.root,
            now=AS_OF,
            authorization_path=valid,
        )


def test_scheduler_skips_spec_until_exact_queue_authorization(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture, config = _make_promoted_repo(tmp_path)
    root = fixture.root
    config_payload = yaml.safe_load(config.read_text(encoding="utf-8"))
    assert config_payload["runtime"]["auto_start"] is False
    journal = root / config_payload["journal"]["path"]
    calls: list[Path] = []

    def fake_run(path: Path, **_kwargs) -> dict:
        calls.append(Path(path))
        return {
            "candidate_id": config_payload["candidate_id"],
            "status": "FAKE_TICK",
            "counts": {"errors": 0},
            "exchange_io_performed": False,
            "order_path_enabled": False,
        }

    monkeypatch.setattr("price_action.lab.tf_signal_shadow.run_shadow_config", fake_run)
    report = run_default_scan(repo_root=root, now=AS_OF)
    assert report["configs_considered"] == 1
    assert report["configs_scanned"] == 0
    assert report["results"][0]["status"] == "SKIPPED_NOT_AUTHORIZED"
    assert calls == []
    con = duckdb.connect(str(journal), read_only=True)
    try:
        assert con.execute("SELECT count(*) FROM shadow_scans").fetchone()[0] == 0
    finally:
        con.close()

    queue_path = root / "memory/researcher/deploy_queue.json"
    queue = json.loads(queue_path.read_text(encoding="utf-8"))
    row = queue["tf_signal_shadow"]["candidates"][0]
    row["status"] = "SHADOW_ACTIVE_AUTHORIZED"
    queue_path.write_text(json.dumps(queue, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    rejected = run_default_scan(repo_root=root, now=AS_OF)
    assert rejected["configs_scanned"] == 0
    assert rejected["results"][0]["status"] == "REJECTED"
    assert rejected["results"][0]["reason_code"] == "AUTHORIZATION"
    assert calls == []

    authorization = write_principal_authorization(
        fixture,
        config_path=config,
        issued_at=AS_OF - timedelta(minutes=1),
        expires_at=AS_OF + timedelta(hours=1),
    )
    tampered = json.loads(authorization.read_text(encoding="utf-8"))
    tampered["signature"] = "AA=="
    authorization.write_text(
        json.dumps(tampered, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    rejected = run_default_scan(repo_root=root, now=AS_OF)
    assert rejected["configs_scanned"] == 0
    assert rejected["results"][0]["status"] == "REJECTED"
    assert calls == []

    write_principal_authorization(
        fixture,
        config_path=config,
        issued_at=AS_OF - timedelta(minutes=1),
        expires_at=AS_OF + timedelta(hours=1),
    )
    authorized = run_default_scan(repo_root=root, now=AS_OF)
    assert authorized["configs_scanned"] == 1
    assert len(calls) == 1
    assert calls[0] == config.resolve()


def test_scheduler_ticks_shadow_without_research_autopilot() -> None:
    jobs = {job_id: expression for job_id, kind, expression, _func in JOB_TABLE if kind == "cron"}
    assert jobs["tf_signal_shadow"] == "11,26,41,56 * * * *"
    assert "tf_signal_shadow" not in _RESEARCH_AUTOPILOT_JOBS
