"""Config-driven TF exploration scheduler contract."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
import yaml

from price_action.orchestrator import scheduler as scheduler_module
from price_action.orchestrator.scheduler import JOB_TABLE, _load_tf_exploration_schedule


def _config(path: Path, *, pool: str = "data/custom_4h.pkl") -> Path:
    payload = {
        "exploration": {
            "strategies": ["engulfing_continuation"],
            "enabled_timeframes": ["4h"],
        },
        "target_tfs": [{"tf": "4h", "pool": pool, "feasibility": "medium"}],
    }
    path.write_text(yaml.safe_dump(payload), encoding="utf-8")
    return path


def test_scheduler_universe_comes_from_yaml(tmp_path: Path) -> None:
    config = _config(tmp_path / "tf.yaml")

    strategies, timeframes, pools = _load_tf_exploration_schedule(
        tmp_path,
        config_path=config,
    )

    assert strategies == ["engulfing_continuation"]
    assert timeframes == ["4h"]
    assert pools == {"4h": (tmp_path / "data/custom_4h.pkl").resolve()}


def test_scheduler_rejects_pool_path_escape(tmp_path: Path) -> None:
    config = _config(tmp_path / "tf.yaml", pool="../outside.pkl")

    with pytest.raises(ValueError, match="escapes repository"):
        _load_tf_exploration_schedule(tmp_path, config_path=config)


def test_oos_completion_triggers_promotion_without_independent_cron(monkeypatch) -> None:
    events: list[str] = []

    def fake_oos_scan():
        events.append("oos_complete")
        return {
            "schema_version": "tf-independent-oos-scan-v1",
            "scanned": 0,
            "authorized": 0,
            "errors": 0,
            "artifacts": [],
            "exchange_io_performed": False,
            "live_order_authorized": False,
        }

    async def fake_promotion():
        events.append("promotion_started")

    monkeypatch.setattr(scheduler_module, "_run_tf_independent_oos_scan_sync", fake_oos_scan)
    monkeypatch.setattr(scheduler_module, "_job_tf_shadow_promotion", fake_promotion)

    asyncio.run(scheduler_module._job_tf_independent_oos())

    assert events == ["oos_complete", "promotion_started"]
    job_names = {row[0] for row in JOB_TABLE}
    assert "tf_independent_oos" in job_names
    assert "tf_shadow_promotion" not in job_names
