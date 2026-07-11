"""Scheduler contracts for the permanent-paper Forex coordinator."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from price_action.orchestrator.scheduler import JOB_TABLE, _run_forex_paper_signal_sync


def _completed(payload: dict, *, rc: int) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        args=["python", "scripts/forex_paper_signal.py"],
        returncode=rc,
        stdout=json.dumps(payload),
        stderr="",
    )


def _safe_payload(verdict: str) -> dict:
    return {
        "verdict": verdict,
        "blockers": ["CAPABILITY_FEED_UNAVAILABLE"],
        "journal_mutated": False,
        "broker_db_mutated": False,
        "permanent_paper_only": True,
        "order_path_enabled": False,
        "network_path_enabled": False,
        "deployment_evidence": False,
    }


def test_forex_scheduler_accepts_explicit_readiness_defer(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: _completed(_safe_payload("DEFER_READINESS"), rc=3),
    )

    result = _run_forex_paper_signal_sync(repo_root=tmp_path)

    assert result["rc"] == 3
    assert result["verdict"] == "DEFER_READINESS"
    assert result["journal_mutated"] is False
    assert result["broker_db_mutated"] is False


def test_forex_scheduler_rejects_unsafe_capability_claim(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    payload = _safe_payload("READY_LOCAL_PAPER")
    payload["order_path_enabled"] = True
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: _completed(payload, rc=0),
    )

    with pytest.raises(RuntimeError, match="order_path_enabled"):
        _run_forex_paper_signal_sync(repo_root=tmp_path)


def test_forex_scheduler_rejects_database_mutation_on_defer(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    payload = _safe_payload("DEFER_READINESS")
    payload["journal_mutated"] = True
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: _completed(payload, rc=3),
    )

    with pytest.raises(RuntimeError, match="unexpected database mutation"):
        _run_forex_paper_signal_sync(repo_root=tmp_path)


def test_forex_scheduler_job_is_four_hourly_and_paper_only() -> None:
    rows = {name: (kind, cadence, func) for name, kind, cadence, func in JOB_TABLE}

    assert rows["forex_paper_signal"][0:2] == ("cron", "8 */4 * * *")
