"""Readiness-gated, permanent-paper forex coordinator acceptance tests."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import duckdb
import pandas as pd
import pytest
import yaml

import price_action.forex.paper_signal as paper_signal_module
from price_action.contracts import Signal
from price_action.forex.paper_broker import (
    LocalPaperBrokerConfig,
    run_local_paper_broker_once,
)
from price_action.forex.paper_signal import (
    ForexPaperConfig,
    ForexSignalJournal,
    read_weekly_signal_kpis,
    run_forex_signal_once,
)


def _write_market(
    path: Path,
    *,
    last_open: datetime,
    bars: int = 300,
    include_spread: bool = True,
) -> None:
    start = last_open - timedelta(hours=4 * (bars - 1))
    rows = []
    for i in range(bars):
        ts = start + timedelta(hours=4 * i)
        price = 1.05 + i * 0.00001
        row: tuple[object, ...] = (
            "histdata",
            "EUR/USD",
            "4h",
            ts,
            price,
            price + 0.001,
            price - 0.001,
            price + 0.0002,
            1.0,
        )
        if include_spread:
            row += (1.5,)
        rows.append(row)
    spread = ", spread_bps DOUBLE" if include_spread else ""
    with duckdb.connect(str(path)) as con:
        con.execute(
            f"""
            CREATE TABLE ohlcv (
                venue VARCHAR, symbol VARCHAR, timeframe VARCHAR, ts TIMESTAMPTZ,
                open DOUBLE, high DOUBLE, low DOUBLE, close DOUBLE, volume DOUBLE
                {spread}
            )
            """
        )
        placeholders = ",".join("?" for _ in rows[0])
        con.executemany(f"INSERT INTO ohlcv VALUES ({placeholders})", rows)


def _capability_contract(root: Path, name: str) -> dict[str, str]:
    implementation = root / f"{name}_implementation.py"
    implementation.write_text(f'CAPABILITY = "{name}"\n', encoding="utf-8")
    contract = root / f"{name}_capability.json"
    contract.write_text(
        json.dumps(
            {
                "schema_version": "forex-capability-v1",
                "capability": name,
                "ready": True,
                "paper_only": True,
                "live_authorized": False,
                "testnet_authorized": False,
                "order_authorized": False,
                "implementation_artifacts": [
                    {
                        "path": str(implementation),
                        "sha256": hashlib.sha256(implementation.read_bytes()).hexdigest(),
                    }
                ],
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return {"contract_file": str(contract)}


def _write_readiness(
    path: Path,
    market_db: Path,
    *,
    min_rows: int = 1,
    capabilities_ready: bool = True,
    trusted_venues: list[str] | None = None,
) -> None:
    trusted_venues = trusted_venues or ["histdata"]
    capabilities: dict[str, object] = {
        "feed": capabilities_ready,
        "paper_broker": _capability_contract(path.parent, "paper_broker")
        if capabilities_ready
        else False,
        "local_runner": _capability_contract(path.parent, "local_runner")
        if capabilities_ready
        else False,
    }
    payload = {
        "schema_version": "forex-autonomy-v1",
        "database": {"path": str(market_db)},
        "data": {
            "trusted_venues": trusted_venues,
            "required_series": [{"venue": "histdata", "symbol": "EUR/USD", "timeframe": "4h"}],
            "min_rows_per_series": min_rows,
            "spread": {"column": "spread_bps", "min_value": 0.0, "max_value": 20.0},
            "freshness": {
                "max_market_age_bars": 2.0,
                "grace_hours": 2.0,
                "future_tolerance_hours": 1.0,
                "market_hours": {
                    "friday_close_hour_utc": 22,
                    "sunday_open_hour_utc": 22,
                },
            },
        },
        "capabilities": capabilities,
        "policy": {
            "permanent_mode": "PAPER_ONLY",
            "live_authorized": False,
            "testnet_authorized": False,
            "order_authorized": False,
        },
    }
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")


def _config(tmp_path: Path, *, min_history: int = 250) -> ForexPaperConfig:
    readiness = tmp_path / "readiness.yaml"
    _write_readiness(readiness, tmp_path / "forex_market.duckdb")
    return ForexPaperConfig(
        market_db=tmp_path / "forex_market.duckdb",
        journal_db=tmp_path / "forex_signal_journal.duckdb",
        broker_db=tmp_path / "forex_paper_broker.duckdb",
        status_path=tmp_path / "forex_status.json",
        readiness_config=readiness,
        max_feed_age_hours=72.0,
        min_history_bars=min_history,
    )


def _latest_signal(frame: pd.DataFrame, config: ForexPaperConfig) -> list[Signal]:
    row = frame.iloc[-1]
    return [
        Signal(
            ts=pd.Timestamp(row["ts"]).to_pydatetime(),
            venue="histdata",
            symbol="EUR/USD",
            timeframe="4h",
            direction="long",
            pattern_id="synthetic_acceptance_signal",
            confluence_score=2.0,
            sl_price=float(row["close"]) - 0.001,
            tp_price=float(row["close"]) + 0.002,
            suggested_size_atr=1.0,
            metadata={"fixture": True},
            manifest_hash="fixture-manifest",
        )
    ]


def test_readiness_failure_prevents_detector_and_both_journal_mutations(tmp_path: Path) -> None:
    config = _config(tmp_path)
    _write_market(config.market_db, last_open=datetime(2026, 1, 1, tzinfo=UTC))
    called = False

    def detector(frame: pd.DataFrame, cfg: ForexPaperConfig) -> list[Signal]:
        nonlocal called
        called = True
        return _latest_signal(frame, cfg)

    status = run_forex_signal_once(
        config,
        as_of=datetime(2026, 7, 11, tzinfo=UTC),
        detector=detector,
    )

    assert status["verdict"] == "DEFER_READINESS"
    assert status["new_signals"] == 0
    assert status["journal_mutated"] is False
    assert status["broker_db_mutated"] is False
    assert status["order_path_enabled"] is False
    assert status["network_path_enabled"] is False
    assert status["deployment_evidence"] is False
    assert not config.journal_db.exists()
    assert not config.broker_db.exists()
    assert called is False


def test_fresh_bar_close_signal_is_idempotent_and_enters_weekly_kpi(tmp_path: Path) -> None:
    config = _config(tmp_path)
    last_open = datetime(2026, 7, 8, 4, tzinfo=UTC)
    _write_market(config.market_db, last_open=last_open)

    first = run_forex_signal_once(
        config,
        as_of=datetime(2026, 7, 8, 8, 5, tzinfo=UTC),
        detector=_latest_signal,
    )
    second = run_forex_signal_once(
        config,
        as_of=datetime(2026, 7, 8, 9, 5, tzinfo=UTC),
        detector=_latest_signal,
    )

    assert first["verdict"] == "READY_LOCAL_PAPER"
    assert first["new_signals"] == 1
    assert first["paper_broker"]["deferred_signals"] == 1
    assert second["new_signals"] == 0
    assert second["duplicate_signals"] == 1
    assert second["weekly_kpis"]["signals"]["signals"] == 1
    assert second["weekly_kpis"]["signals"]["runs"] == 2
    assert second["weekly_kpis"]["paper_trades"]["closed_trades"] == 0
    with duckdb.connect(str(config.journal_db), read_only=True) as con:
        assert con.execute("SELECT count(*) FROM signal_events").fetchone()[0] == 1
        row = con.execute("SELECT mode, deployment_evidence FROM signal_events").fetchone()
    assert row == ("SIGNAL_ONLY_PAPER", False)


def test_short_history_blocks_before_signal_journal_creation(tmp_path: Path) -> None:
    config = _config(tmp_path, min_history=250)
    _write_market(
        config.market_db,
        last_open=datetime(2026, 7, 8, 4, tzinfo=UTC),
        bars=100,
    )
    status = run_forex_signal_once(
        config,
        as_of=datetime(2026, 7, 8, 8, 5, tzinfo=UTC),
        detector=_latest_signal,
    )
    assert status["verdict"] == "DEFER_INPUT_BLOCKED"
    assert any("INSUFFICIENT" in blocker for blocker in status["blockers"])
    assert not config.journal_db.exists()


def test_signal_detector_receives_only_the_configured_venue(tmp_path: Path) -> None:
    config = _config(tmp_path)
    last_open = datetime(2026, 7, 8, 4, tzinfo=UTC)
    _write_market(config.market_db, last_open=last_open)
    with duckdb.connect(str(config.market_db)) as con:
        con.execute(
            """
            INSERT INTO ohlcv
            SELECT 'secondary', symbol, timeframe, ts, open * 2, high * 2,
                   low * 2, close * 2, volume, spread_bps
            FROM ohlcv WHERE venue='histdata'
            """
        )
    _write_readiness(
        config.readiness_config,
        config.market_db,
        trusted_venues=["histdata", "secondary"],
    )
    detector_called = False

    def detector(frame: pd.DataFrame, _: ForexPaperConfig) -> list[Signal]:
        nonlocal detector_called
        detector_called = True
        assert set(frame["venue"]) == {"histdata"}
        assert len(frame) == 300
        assert float(frame["close"].max()) < 2.0
        return []

    status = run_forex_signal_once(
        config,
        as_of=datetime(2026, 7, 8, 8, 5, tzinfo=UTC),
        detector=detector,
    )

    assert status["verdict"] == "READY_LOCAL_PAPER"
    assert detector_called is True


def test_missing_observed_spread_defers_before_journal_mutation(tmp_path: Path) -> None:
    config = _config(tmp_path)
    _write_market(
        config.market_db,
        last_open=datetime(2026, 7, 8, 4, tzinfo=UTC),
        include_spread=False,
    )

    status = run_forex_signal_once(
        config,
        as_of=datetime(2026, 7, 8, 8, 5, tzinfo=UTC),
        detector=_latest_signal,
    )

    codes = {item["code"] for item in status["readiness_reasons"]}
    assert status["verdict"] == "DEFER_READINESS"
    assert "SPREAD_DATA_MISSING" in codes
    assert not config.journal_db.exists()
    assert not config.broker_db.exists()


def test_from_yaml_rejects_repository_path_traversal(tmp_path: Path) -> None:
    config_path = tmp_path / "forex.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "schema_version": "forex-paper-signal-config-v1",
                "mode": "SIGNAL_ONLY_PAPER",
                "safety_locks": {
                    "permanent_paper_only": True,
                    "allow_order_submission": False,
                    "allow_network": False,
                },
                "data": {"market_db": "../escaped.duckdb"},
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="escapes repository root"):
        ForexPaperConfig.from_yaml(config_path, repo_root=tmp_path)


def test_naive_evaluation_timestamp_is_rejected(tmp_path: Path) -> None:
    config = _config(tmp_path)
    with pytest.raises(ValueError, match="timezone-aware"):
        run_forex_signal_once(config, as_of=datetime(2026, 7, 8, 8, 5))


def test_status_replace_failure_preserves_previous_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _config(tmp_path)
    _write_market(config.market_db, last_open=datetime(2026, 1, 1, tzinfo=UTC))
    config.status_path.write_text("previous-status\n", encoding="utf-8")

    def fail_replace(_: str, __: Path) -> None:
        raise OSError("synthetic replace failure")

    monkeypatch.setattr(paper_signal_module.os, "replace", fail_replace)
    with pytest.raises(OSError, match="synthetic replace failure"):
        run_forex_signal_once(config, as_of=datetime(2026, 7, 11, tzinfo=UTC))

    assert config.status_path.read_text(encoding="utf-8") == "previous-status\n"
    assert list(tmp_path.glob(f".{config.status_path.name}.*")) == []


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("mode", "LIVE"),
        ("permanent_paper_only", False),
        ("permanent_paper_only", 1),
        ("permanent_paper_only", "true"),
        ("allow_order_submission", True),
        ("allow_order_submission", 0),
        ("allow_network", True),
        ("allow_network", "false"),
    ],
)
def test_safety_locks_have_no_configurable_live_state(
    tmp_path: Path, field: str, value: object
) -> None:
    kwargs = {
        "market_db": tmp_path / "market.duckdb",
        "journal_db": tmp_path / "journal.duckdb",
        "broker_db": tmp_path / "broker.duckdb",
        "status_path": tmp_path / "status.json",
        "readiness_config": tmp_path / "readiness.yaml",
        field: value,
    }
    with pytest.raises(ValueError):
        ForexPaperConfig(**kwargs)


def test_all_databases_must_be_separate(tmp_path: Path) -> None:
    same = tmp_path / "same.duckdb"
    with pytest.raises(ValueError, match="separate"):
        ForexPaperConfig(
            market_db=same,
            journal_db=same,
            broker_db=tmp_path / "broker.duckdb",
            status_path=tmp_path / "status.json",
            readiness_config=tmp_path / "readiness.yaml",
        )


def test_weekly_signal_kpi_read_does_not_create_a_database(tmp_path: Path) -> None:
    path = tmp_path / "journal.duckdb"
    kpis = read_weekly_signal_kpis(path, as_of=datetime(2026, 7, 11, tzinfo=UTC))
    assert kpis["signals"] == 0
    assert not path.exists()


def test_local_paper_broker_round_trip_is_idempotent_and_has_no_order_id(
    tmp_path: Path,
) -> None:
    market = tmp_path / "market.duckdb"
    last_open = datetime(2026, 7, 8, 12, tzinfo=UTC)
    _write_market(market, last_open=last_open)
    # Force a later closed bar to cross the target after next-bar-open entry.
    with duckdb.connect(str(market)) as con:
        con.execute(
            "UPDATE ohlcv SET high=1.20, close=1.10 WHERE ts=?",
            [last_open],
        )

    readiness = tmp_path / "readiness.yaml"
    _write_readiness(readiness, market)
    signal_db = tmp_path / "signals.duckdb"
    journal = ForexSignalJournal(signal_db)
    decision = last_open - timedelta(hours=8)
    signal = Signal(
        ts=decision,
        venue="histdata",
        symbol="EUR/USD",
        timeframe="4h",
        direction="long",
        pattern_id="paper_round_trip",
        confluence_score=2.0,
        sl_price=1.0,
        tp_price=1.15,
        suggested_size_atr=1.0,
        metadata={},
        manifest_hash="fixture",
    )
    assert journal.record_signal(
        signal,
        recorded_at=decision + timedelta(hours=4),
        timeframe_delta=timedelta(hours=4),
        config_hash="fixture-config",
    )
    broker_db = tmp_path / "broker.duckdb"
    broker_config = LocalPaperBrokerConfig(
        market_db=market,
        signal_db=signal_db,
        broker_db=broker_db,
        readiness_config=readiness,
        venue="histdata",
        symbols=("EUR/USD",),
        timeframe="4h",
    )

    first = run_local_paper_broker_once(
        broker_config, as_of=last_open + timedelta(hours=4, minutes=5)
    )
    second = run_local_paper_broker_once(
        broker_config, as_of=last_open + timedelta(hours=4, minutes=5)
    )
    third = run_local_paper_broker_once(
        broker_config, as_of=last_open + timedelta(hours=4, minutes=5)
    )

    assert first["verdict"] == "READY_LOCAL_PAPER"
    assert first["entries"] == 1
    assert first["exits"] == 1
    assert second["entries"] == 0
    assert second["exits"] == 0
    assert third["entries"] == 0
    assert third["exits"] == 0
    with duckdb.connect(str(broker_db), read_only=True) as con:
        assert con.execute("SELECT count(*) FROM paper_trades").fetchone()[0] == 1
        mode, deployment = con.execute(
            "SELECT mode, deployment_evidence FROM paper_trades"
        ).fetchone()
        assert (
            con.execute(
                "SELECT count(*) FROM paper_fills WHERE exchange_order_id IS NOT NULL"
            ).fetchone()[0]
            == 0
        )
    assert (mode, deployment) == ("LOCAL_PERMANENT_PAPER", False)


def test_runtime_sources_have_no_execution_or_network_client_import() -> None:
    root = Path(__file__).resolve().parents[1]
    sources = [
        root / "src" / "price_action" / "forex" / "paper_signal.py",
        root / "src" / "price_action" / "forex" / "paper_broker.py",
        root / "src" / "price_action" / "lab" / "forex_readiness.py",
    ]
    forbidden = (
        "import ccxt",
        "import httpx",
        "import requests",
        "BrokerBase",
        "place_order(",
        "exchange_order_id =",
    )
    for path in sources:
        source = path.read_text(encoding="utf-8")
        assert all(token not in source for token in forbidden)
