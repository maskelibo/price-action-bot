"""Deterministic local Forex paper-broker acceptance tests."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import duckdb
import pytest
import yaml

from price_action.contracts import Signal
from price_action.forex.paper_broker import (
    LocalPaperBrokerConfig,
    run_local_paper_broker_once,
)
from price_action.forex.paper_signal import ForexSignalJournal


def _capability(path: Path, name: str) -> dict[str, str]:
    implementation = path.parent / f"{name}_implementation.py"
    implementation.write_text(f'CAPABILITY = "{name}"\n', encoding="utf-8")
    contract = path.parent / f"{name}_capability.json"
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


def _readiness(path: Path, market: Path, *, feed: bool = True) -> None:
    path.write_text(
        yaml.safe_dump(
            {
                "schema_version": "forex-autonomy-v1",
                "database": {"path": str(market)},
                "data": {
                    "trusted_venues": ["histdata"],
                    "required_series": [
                        {"venue": "histdata", "symbol": "EUR/USD", "timeframe": "4h"}
                    ],
                    "min_rows_per_series": 50,
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
                "capabilities": {
                    "feed": feed,
                    "paper_broker": _capability(path, "paper_broker"),
                    "local_runner": _capability(path, "local_runner"),
                },
                "policy": {
                    "permanent_mode": "PAPER_ONLY",
                    "live_authorized": False,
                    "testnet_authorized": False,
                    "order_authorized": False,
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )


def _market(path: Path, *, decision_ts: datetime) -> None:
    first = decision_ts - timedelta(hours=4 * 59)
    rows = []
    for index in range(60):
        ts = first + timedelta(hours=4 * index)
        rows.append(("histdata", "EUR/USD", "4h", ts, 1.1, 1.102, 1.098, 1.1, 1.5))
    with duckdb.connect(str(path)) as con:
        con.execute(
            """
            CREATE TABLE ohlcv (
                venue VARCHAR, symbol VARCHAR, timeframe VARCHAR, ts TIMESTAMPTZ,
                open DOUBLE, high DOUBLE, low DOUBLE, close DOUBLE, spread_bps DOUBLE
            )
            """
        )
        con.executemany("INSERT INTO ohlcv VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)


def _fixture(tmp_path: Path, *, direction: str = "long") -> tuple[LocalPaperBrokerConfig, datetime]:
    decision_ts = datetime(2026, 7, 9, 4, tzinfo=UTC)
    market = tmp_path / "market.duckdb"
    signals = tmp_path / "signals.duckdb"
    broker = tmp_path / "broker.duckdb"
    readiness = tmp_path / "readiness.yaml"
    _market(market, decision_ts=decision_ts)
    _readiness(readiness, market)
    signal = Signal(
        ts=decision_ts,
        venue="histdata",
        symbol="EUR/USD",
        timeframe="4h",
        direction=direction,
        pattern_id="fixture",
        confluence_score=1.0,
        sl_price=1.095 if direction == "long" else 1.105,
        tp_price=1.105 if direction == "long" else 1.095,
        suggested_size_atr=1.0,
        manifest_hash="fixture",
    )
    ForexSignalJournal(signals).record_signal(
        signal,
        recorded_at=decision_ts + timedelta(hours=4, minutes=5),
        timeframe_delta=timedelta(hours=4),
        config_hash="fixture-config",
    )
    config = LocalPaperBrokerConfig(
        market_db=market,
        signal_db=signals,
        broker_db=broker,
        readiness_config=readiness,
        venue="histdata",
        symbols=("EUR/USD",),
        timeframe="4h",
    )
    return config, decision_ts


@pytest.mark.parametrize("direction", ["long", "short"])
def test_next_bar_entry_ambiguous_bar_is_sl_first_and_idempotent(
    tmp_path: Path, direction: str
) -> None:
    config, decision_ts = _fixture(tmp_path, direction=direction)
    first_as_of = decision_ts + timedelta(hours=4, minutes=5)

    first = run_local_paper_broker_once(config, as_of=first_as_of)

    assert first["verdict"] == "READY_LOCAL_PAPER"
    assert first["entries"] == 0
    with duckdb.connect(str(config.market_db)) as con:
        con.execute(
            """
            INSERT INTO ohlcv VALUES
            ('histdata', 'EUR/USD', '4h', ?, 1.1, 1.11, 1.09, 1.1, 2.0)
            """,
            [decision_ts + timedelta(hours=4)],
        )
    second_as_of = decision_ts + timedelta(hours=8, minutes=5)

    second = run_local_paper_broker_once(config, as_of=second_as_of)
    duplicate = run_local_paper_broker_once(config, as_of=second_as_of)

    assert second["entries"] == 1
    assert second["exits"] == 1
    assert second["ambiguous_same_bar_policy"] == "SL_FIRST"
    assert duplicate["entries"] == 0
    assert duplicate["exits"] == 0
    assert second["weekly_kpis"]["closed_trades"] == 1
    assert second["weekly_kpis"]["realized_pnl_usd"] < 0
    with duckdb.connect(str(config.broker_db), read_only=True) as con:
        counts = tuple(
            con.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
            for table in ("paper_positions", "paper_fills", "paper_trades")
        )
        position = con.execute(
            """
            SELECT eligible_entry_ts, entry_bar_ts, status, exit_reason, realized_pnl_usd
            FROM paper_positions
            """
        ).fetchone()
        fill = con.execute(
            "SELECT price, observed_spread_bps, exchange_order_id FROM paper_fills WHERE fill_kind='ENTRY'"
        ).fetchone()
    assert counts == (1, 2, 1)
    assert position[1] >= position[0]
    assert position[2:4] == ("CLOSED", "SL")
    assert position[4] < 0
    assert fill[1:] == (2.0, None)
    assert fill[0] > 1.1 if direction == "long" else fill[0] < 1.1


def test_readiness_defer_never_creates_broker_database(tmp_path: Path) -> None:
    config, decision_ts = _fixture(tmp_path)
    _readiness(config.readiness_config, config.market_db, feed=False)

    status = run_local_paper_broker_once(
        config,
        as_of=decision_ts + timedelta(hours=4, minutes=5),
    )

    assert status["verdict"] == "DEFER_READINESS"
    assert status["broker_db_mutated"] is False
    assert not config.broker_db.exists()


def test_broker_source_has_no_external_execution_surface() -> None:
    source = (
        Path(__file__).resolve().parents[1] / "src" / "price_action" / "forex" / "paper_broker.py"
    ).read_text(encoding="utf-8")
    forbidden = (
        "import ccxt",
        "import requests",
        "import httpx",
        "api_key",
        "secret_key",
        "place_order",
        "create_order",
    )
    assert all(token not in source.lower() for token in forbidden)
