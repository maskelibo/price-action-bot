"""E13 exit-policy evidence and local ATR-shadow tests."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import duckdb
import pytest

from price_action.execution.e13_shadow import AtrChandelierShadowRecorder
from price_action.execution.exit_evidence import e13_exit_evidence, load_e13_policy

ROOT = Path(__file__).resolve().parents[2]


def _config(
    root: Path,
    *,
    required: int = 40,
    paired_required: int | None = None,
    cutoff: str = "2026-07-09T23:13:00Z",
) -> Path:
    config_dir = root / "configs"
    config_dir.mkdir(parents=True, exist_ok=True)
    paired_required = required if paired_required is None else paired_required
    path = config_dir / "risk.yaml"
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
    clean_cutoff_utc: "{cutoff}"
    min_clean_closed_trades: {required}
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
      min_paired_closed_trades: {paired_required}
      market_venue: binance
      timeframe: 15m
      entry_timestamp_semantics: signal_bar_open
      state_path: data/e13_shadow_state.json
      evidence_path: data/e13_shadow_evidence.jsonl
""".strip()
        + "\n",
        encoding="utf-8",
    )
    return path


def _journal(path: Path, rows: list[tuple]) -> None:
    with duckdb.connect(str(path)) as connection:
        connection.execute(
            """
            CREATE TABLE futures_trades_closed (
                trade_id VARCHAR PRIMARY KEY,
                ts_open TIMESTAMP,
                ts_close TIMESTAMP,
                sym VARCHAR,
                side VARCHAR,
                strategy VARCHAR,
                entry_price DOUBLE,
                exit_price DOUBLE,
                qty DOUBLE,
                realized_pnl_usdt DOUBLE,
                realized_r DOUBLE,
                win BOOLEAN,
                close_reason VARCHAR
            )
            """
        )
        connection.executemany(
            "INSERT INTO futures_trades_closed VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            rows,
        )


def _row(
    trade_id: str,
    *,
    close_reason: str = "sl",
    hour: int = 1,
    entry: float = 100.0,
    exit_price: float = 98.0,
    realized_r: float = -1.0,
) -> tuple:
    # Journal schema is UTC-semantic TIMESTAMP (timezone-naive by contract).
    opened = datetime(2026, 7, 10)
    closed = opened + timedelta(hours=hour)
    return (
        trade_id,
        opened,
        closed,
        "TEST/USDT",
        "long",
        "test_strategy",
        entry,
        exit_price,
        1.0,
        exit_price - entry,
        realized_r,
        exit_price > entry,
        close_reason,
    )


def test_policy_is_loaded_from_yaml_and_rejects_drift(tmp_path: Path) -> None:
    config = _config(tmp_path)

    policy = load_e13_policy(config)

    assert policy.required_clean_closes == 40
    assert policy.clean_cutoff == datetime(2026, 7, 9, 23, 13, tzinfo=UTC)
    assert policy.eligible_close_reasons == ("sl", "tp", "time")
    assert policy.live_trail_pct == pytest.approx(0.015)
    assert policy.atr_multiplier == pytest.approx(1.5)
    assert policy.atr_period == 14

    text = config.read_text(encoding="utf-8").replace("multiplier: 1.5\n    activate", "multiplier: 1.6\n    activate", 1)
    config.write_text(text, encoding="utf-8")
    with pytest.raises(ValueError, match=r"stop_loss\.trailing.*candidate_exit"):
        load_e13_policy(config)


def test_timezone_naive_api_input_fails_closed(tmp_path: Path) -> None:
    config = _config(tmp_path)
    journal = tmp_path / "journal.duckdb"
    _journal(journal, [_row("trade-1")])

    with pytest.raises(ValueError, match="timezone-aware"):
        e13_exit_evidence(
            journal,
            config_path=config,
            clean_cutoff=datetime(2026, 7, 9, 23, 13),
        )


def test_synthetic_closes_are_not_clean_samples(tmp_path: Path) -> None:
    config = _config(tmp_path, required=3)
    journal = tmp_path / "journal.duckdb"
    _journal(
        journal,
        [
            _row("direct-sl", close_reason="sl", hour=1),
            _row("direct-tp", close_reason="tp", hour=2, exit_price=104.0, realized_r=2.0),
            _row("orphan", close_reason="reconcile_orphan", hour=3),
            _row("forced", close_reason="force", hour=4),
        ],
    )

    result = e13_exit_evidence(journal, config_path=config)

    assert result["post_cutoff_closed_trades"] == 4
    assert result["clean_closed_trades"] == 2
    assert result["excluded_close_reasons"] == {"force": 1, "reconcile_orphan": 1}
    assert result["sample_gate_pass"] is False
    assert result["promotion_authorized"] is False


def test_trade_opened_before_cutoff_is_not_a_prospective_clean_sample(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path, required=1, cutoff="2026-07-10T00:30:00Z")
    journal = tmp_path / "journal.duckdb"
    _journal(journal, [_row("pre-cutoff-entry", close_reason="sl", hour=1)])

    result = e13_exit_evidence(journal, config_path=config)

    assert result["post_cutoff_closed_trades"] == 1
    assert result["clean_closed_trades"] == 0
    assert result["excluded_pre_cutoff_open_trades"] == 1


def test_sample_ready_without_paired_shadow_never_reaches_review(tmp_path: Path) -> None:
    config = _config(tmp_path, required=1, paired_required=1)
    journal = tmp_path / "journal.duckdb"
    _journal(journal, [_row("trade-1")])

    result = e13_exit_evidence(journal, config_path=config)

    assert result["sample_gate_pass"] is True
    assert result["paired_shadow_closed_trades"] == 0
    assert result["paired_shadow_gate_pass"] is False
    assert result["formal_review_ready"] is False
    assert result["promotion_authorized"] is False
    assert result["decision"] == "HOLD_PAIRED_SHADOW_EVIDENCE_REQUIRED"


def test_causal_atr_shadow_recorder_produces_valid_paired_evidence(tmp_path: Path) -> None:
    config = _config(tmp_path, required=1, paired_required=1)
    journal = tmp_path / "journal.duckdb"
    _journal(journal, [_row("trade-1")])
    policy = load_e13_policy(config)
    recorder = AtrChandelierShadowRecorder(policy)
    opened = datetime(2026, 7, 10, tzinfo=UTC)

    recorder.start_trade(
        trade_id="trade-1",
        side="long",
        ts_open=opened,
        entry_price=100.0,
        initial_sl_price=98.0,
    )
    # Completed bar activates a 102.0 stop for the *next* bar:
    # max(BE=100, high_water=103.5 - 1.5 * ATR=1.0).
    recorder.observe_closed_bar(
        trade_id="trade-1",
        ts=opened + timedelta(minutes=15),
        open_price=100.0,
        high=103.5,
        low=99.5,
        close=103.0,
        atr=1.0,
    )
    # Baseline may close first.  That must not fabricate a same-price candidate
    # outcome; the virtual candidate remains open and consumes later bars.
    recorder.record_baseline_close(
        trade_id="trade-1",
        ts_close=opened + timedelta(hours=1),
        exit_price=98.0,
        close_reason="sl",
    )
    assert not policy.shadow_evidence_path.exists()
    recorder.observe_closed_bar(
        trade_id="trade-1",
        ts=opened + timedelta(hours=1, minutes=15),
        open_price=102.5,
        high=103.0,
        low=101.5,
        close=102.0,
        atr=1.0,
    )

    result = e13_exit_evidence(journal, config_path=config)

    assert result["paired_shadow_closed_trades"] == 1
    assert result["paired_shadow_gate_pass"] is True
    assert result["formal_review_ready"] is True
    assert result["promotion_authorized"] is False
    assert result["decision"] == "READY_FOR_FORMAL_REVIEW"
    assert result["paired_metrics"]["mean_candidate_delta_r"] == pytest.approx(2.0)

    # A labeled/source-looking row is still rejected if its paired arithmetic
    # was edited after recording.
    evidence = json.loads(policy.shadow_evidence_path.read_text(encoding="utf-8"))
    evidence["candidate_realized_r"] = 999.0
    policy.shadow_evidence_path.write_text(
        json.dumps(evidence) + "\n", encoding="utf-8"
    )
    tampered = e13_exit_evidence(journal, config_path=config)
    assert tampered["paired_shadow_closed_trades"] == 0
    assert tampered["invalid_paired_shadow_records"] == {"inconsistent_paired_r": 1}
    assert tampered["formal_review_ready"] is False


@pytest.mark.subprocess
def test_cli_stdout_is_strict_json_even_when_caller_requests_logs(tmp_path: Path) -> None:
    config = _config(tmp_path, required=1)
    journal = tmp_path / "journal.duckdb"
    _journal(journal, [_row("trade-1")])
    env = os.environ.copy()
    env["PA_LOG_QUIET"] = "0"
    env["PA_DISABLE_FILE_LOG"] = "0"

    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "e13_exit_evidence.py"),
            "--journal",
            str(journal),
            "--config",
            str(config),
        ],
        cwd=ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["clean_closed_trades"] == 1
    assert completed.stderr == ""
