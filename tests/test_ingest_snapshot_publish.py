"""Fail-closed ingest -> consumer snapshot publication regressions."""

from __future__ import annotations

import asyncio
import fcntl
import hashlib
import shutil
import threading
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import duckdb
import pandas as pd
import pytest
import scripts.ingest_15m_live as live_ingest

from price_action.data import ingest_ccxt
from price_action.data import store as store_module
from price_action.data.ingest_ccxt import IngestStats
from price_action.data.store import (
    _CONN_POOL,
    OHLCVStore,
    checkpoint_and_close_pool_for_path,
    reset_store_pool,
)


def _snapshot_db(path: Path, values: list[int]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(path))
    try:
        con.execute("CREATE TABLE ohlcv(ts TIMESTAMPTZ, value INTEGER)")
        for offset, value in enumerate(values):
            con.execute(
                "INSERT INTO ohlcv VALUES (?, ?)",
                [datetime(2026, 7, 11, 1, offset, tzinfo=UTC), value],
            )
        con.execute("CHECKPOINT")
    finally:
        con.close()


def _values(path: Path) -> list[int]:
    con = duckdb.connect(str(path), read_only=True)
    try:
        return [row[0] for row in con.execute("SELECT value FROM ohlcv ORDER BY ts").fetchall()]
    finally:
        con.close()


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture(autouse=True)
def _clean_pool() -> None:
    reset_store_pool()
    yield
    reset_store_pool()


def test_validated_snapshot_atomically_replaces_consumer_and_keeps_old_backup(
    tmp_path: Path,
) -> None:
    source = tmp_path / "market_ingest.duckdb"
    consumer = tmp_path / "market.duckdb"
    _snapshot_db(source, [7, 8])
    _snapshot_db(consumer, [1])

    result = ingest_ccxt._snapshot_ingest_to_consumer(source, consumer)

    assert result["snapshotted"] is True
    assert result["error"] is None
    assert result["rows"] == 2
    assert result["bytes"] == consumer.stat().st_size
    assert result["newest_bar"] is not None
    assert _values(consumer) == [7, 8]
    assert _values(consumer.with_suffix(".duckdb.bak")) == [1]
    assert not list(tmp_path.glob(".market.duckdb.snapshot.*.duckdb"))


def test_source_change_during_copy_preserves_old_consumer(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / "market_ingest.duckdb"
    consumer = tmp_path / "market.duckdb"
    _snapshot_db(source, [7])
    _snapshot_db(consumer, [1])
    before_hash = _sha(consumer)
    real_copyfile = shutil.copyfile

    def _copy_then_mutate(src: Path, dst: Path) -> str:
        copied = real_copyfile(src, dst)
        con = duckdb.connect(str(source))
        try:
            con.execute(
                "INSERT INTO ohlcv VALUES (?, ?)",
                [datetime(2026, 7, 11, 1, 2, tzinfo=UTC), 9],
            )
            con.execute("CHECKPOINT")
        finally:
            con.close()
        return copied

    monkeypatch.setattr(shutil, "copyfile", _copy_then_mutate)

    result = ingest_ccxt._snapshot_ingest_to_consumer(source, consumer)

    assert result["snapshotted"] is False
    assert "SNAPSHOT_SOURCE_CHANGED" in str(result["error"])
    assert _sha(consumer) == before_hash
    assert _values(consumer) == [1]
    assert not list(tmp_path.glob(".market.duckdb.snapshot.*.duckdb"))


def test_invalid_temporary_duckdb_never_reaches_consumer(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / "market_ingest.duckdb"
    consumer = tmp_path / "market.duckdb"
    _snapshot_db(source, [7])
    _snapshot_db(consumer, [1])
    before_hash = _sha(consumer)

    def _corrupt_copy(src: Path, dst: Path) -> str:
        Path(dst).write_bytes(b"x" * Path(src).stat().st_size)
        return str(dst)

    monkeypatch.setattr(shutil, "copyfile", _corrupt_copy)

    result = ingest_ccxt._snapshot_ingest_to_consumer(source, consumer)

    assert result["snapshotted"] is False
    assert result["error"]
    assert _sha(consumer) == before_hash
    assert _values(consumer) == [1]
    assert not list(tmp_path.glob(".market.duckdb.snapshot.*.duckdb"))


def test_source_wal_is_rejected_without_touching_consumer(tmp_path: Path) -> None:
    source = tmp_path / "market_ingest.duckdb"
    consumer = tmp_path / "market.duckdb"
    _snapshot_db(source, [7])
    _snapshot_db(consumer, [1])
    Path(f"{source}.wal").write_bytes(b"uncheckpointed")
    before_hash = _sha(consumer)

    result = ingest_ccxt._snapshot_ingest_to_consumer(source, consumer)

    assert result["snapshotted"] is False
    assert "SNAPSHOT_SOURCE_WAL_PRESENT" in str(result["error"])
    assert _sha(consumer) == before_hash


def test_competing_snapshot_publisher_fails_visible_and_preserves_consumer(
    tmp_path: Path,
) -> None:
    source = tmp_path / "market_ingest.duckdb"
    consumer = tmp_path / "market.duckdb"
    _snapshot_db(source, [7])
    _snapshot_db(consumer, [1])
    lock_path = tmp_path / ".market.duckdb.snapshot.lock"

    with lock_path.open("a+b") as held:
        fcntl.flock(held.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        result = ingest_ccxt._snapshot_ingest_to_consumer(source, consumer)

    assert result["snapshotted"] is False
    assert "SNAPSHOT_PUBLISH_BUSY" in str(result["error"])
    assert _values(consumer) == [1]


def test_checkpoint_close_accepts_path_and_releases_real_string_pool_key(
    tmp_path: Path,
) -> None:
    source = tmp_path / "market_ingest.duckdb"
    store = OHLCVStore(
        path=source,
        parquet_root=tmp_path / "parquet",
        force_write=True,
    )
    frame = pd.DataFrame(
        [
            {
                "venue": "binance",
                "symbol": "BTC/USDT",
                "timeframe": "15m",
                "ts": datetime(2026, 7, 11, 1, 0, tzinfo=UTC),
                "open": 1.0,
                "high": 2.0,
                "low": 0.5,
                "close": 1.5,
                "volume": 10.0,
            }
        ]
    )
    store.upsert(frame, also_parquet=False)
    assert str(source) in _CONN_POOL

    checkpoint_and_close_pool_for_path(source)

    assert str(source) not in _CONN_POOL
    assert not Path(f"{source}.wal").exists()
    con = duckdb.connect(str(source), read_only=True)
    try:
        assert con.execute("SELECT COUNT(*) FROM ohlcv").fetchone() == (1,)
    finally:
        con.close()


def test_checkpoint_failure_still_closes_and_detaches_writer_handle(tmp_path: Path) -> None:
    key = str(tmp_path / "market_ingest.duckdb")

    class _FailingCheckpointConnection:
        closed = False

        def execute(self, sql: str) -> None:
            assert sql == "CHECKPOINT"
            raise RuntimeError("checkpoint exploded")

        def close(self) -> None:
            self.closed = True

    connection = _FailingCheckpointConnection()
    store_module._CONN_POOL[key] = [connection]  # type: ignore[list-item]
    store_module._CONN_LOCKS[key] = [threading.RLock()]
    store_module._POOL_RR_INDEX[key] = 0

    with pytest.raises(RuntimeError, match="checkpoint exploded"):
        checkpoint_and_close_pool_for_path(Path(key))

    assert connection.closed is True
    assert key not in store_module._CONN_POOL
    assert key not in store_module._CONN_LOCKS
    assert key not in store_module._POOL_RR_INDEX


class _FakeLiveStore:
    def __init__(self, *args, **kwargs) -> None:
        del args, kwargs

    def read(self, *args, **kwargs) -> pd.DataFrame:
        del args, kwargs
        return pd.DataFrame()


def _live_settings(tmp_path: Path) -> SimpleNamespace:
    return SimpleNamespace(
        ingest_duckdb_path=tmp_path / "market_ingest.duckdb",
        duckdb_path=tmp_path / "market.duckdb",
    )


def test_live_ingest_success_checkpoints_before_snapshot(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    events: list[str] = []
    monkeypatch.setattr(live_ingest, "SYMBOLS", ["BTC/USDT"])
    monkeypatch.setattr(live_ingest, "VENUE_PRIORITY", ["binance"])
    monkeypatch.setattr(live_ingest, "get_settings", lambda: _live_settings(tmp_path))
    monkeypatch.setattr(live_ingest, "OHLCVStore", _FakeLiveStore)
    monkeypatch.setattr(live_ingest, "_build_exchange", lambda venue: object())
    monkeypatch.setattr(
        live_ingest, "ingest_symbol_15m", lambda *args: events.append("ingest") or 1
    )
    monkeypatch.setattr(
        live_ingest,
        "checkpoint_and_close_pool_for_path",
        lambda path: events.append("checkpoint"),
    )

    def _snapshot(source: Path, consumer: Path) -> dict[str, object]:
        del source, consumer
        assert events[-1] == "checkpoint"
        events.append("snapshot")
        return {"snapshotted": True, "bytes": 123, "newest_bar": "2026-07-11 01:00:00"}

    monkeypatch.setattr(live_ingest, "_snapshot_ingest_to_consumer", _snapshot)

    live_ingest.main()

    assert events == ["ingest", "checkpoint", "snapshot"]
    assert "[INGEST-15M] OK" in capsys.readouterr().out


def test_live_ingest_reuses_one_exchange_client_per_venue(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    build_calls: list[str] = []
    seen_clients: list[object] = []
    client = object()
    monkeypatch.setattr(live_ingest, "SYMBOLS", ["BTC/USDT", "ETH/USDT"])
    monkeypatch.setattr(live_ingest, "VENUE_PRIORITY", ["binance"])
    monkeypatch.setattr(live_ingest, "get_settings", lambda: _live_settings(tmp_path))
    monkeypatch.setattr(live_ingest, "OHLCVStore", _FakeLiveStore)

    def _build(venue: str) -> object:
        build_calls.append(venue)
        return client

    def _ingest(_symbol: str, _store: object, exchange: object, _venue: str) -> int:
        seen_clients.append(exchange)
        return 1

    monkeypatch.setattr(live_ingest, "_build_exchange", _build)
    monkeypatch.setattr(live_ingest, "ingest_symbol_15m", _ingest)
    monkeypatch.setattr(live_ingest, "checkpoint_and_close_pool_for_path", lambda _path: None)
    monkeypatch.setattr(
        live_ingest,
        "_snapshot_ingest_to_consumer",
        lambda *_args: {
            "snapshotted": True,
            "bytes": 123,
            "newest_bar": "2026-07-11 01:00:00",
        },
    )

    live_ingest.main()

    assert build_calls == ["binance"]
    assert seen_clients == [client, client]
    assert "[INGEST-15M] OK" in capsys.readouterr().out


def test_live_partial_ingest_closes_writer_but_never_publishes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    events: list[str] = []
    monkeypatch.setattr(live_ingest, "SYMBOLS", ["BTC/USDT"])
    monkeypatch.setattr(live_ingest, "VENUE_PRIORITY", ["binance", "bybit"])
    monkeypatch.setattr(live_ingest, "get_settings", lambda: _live_settings(tmp_path))
    monkeypatch.setattr(live_ingest, "OHLCVStore", _FakeLiveStore)
    monkeypatch.setattr(
        live_ingest,
        "_build_exchange",
        lambda venue: (_ for _ in ()).throw(RuntimeError(f"{venue} down")),
    )
    monkeypatch.setattr(
        live_ingest,
        "checkpoint_and_close_pool_for_path",
        lambda path: events.append("checkpoint"),
    )
    monkeypatch.setattr(
        live_ingest,
        "_snapshot_ingest_to_consumer",
        lambda *args: events.append("snapshot"),
    )

    with pytest.raises(SystemExit) as exc_info:
        live_ingest.main()

    assert exc_info.value.code == 1
    assert events == ["checkpoint"]


def test_live_zero_closed_rows_is_not_publishable_success(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    events: list[str] = []
    monkeypatch.setattr(live_ingest, "SYMBOLS", ["BTC/USDT"])
    monkeypatch.setattr(live_ingest, "VENUE_PRIORITY", ["binance"])
    monkeypatch.setattr(live_ingest, "get_settings", lambda: _live_settings(tmp_path))
    monkeypatch.setattr(live_ingest, "OHLCVStore", _FakeLiveStore)
    monkeypatch.setattr(live_ingest, "_build_exchange", lambda venue: object())
    monkeypatch.setattr(live_ingest, "ingest_symbol_15m", lambda *args: 0)
    monkeypatch.setattr(
        live_ingest,
        "checkpoint_and_close_pool_for_path",
        lambda path: events.append("checkpoint"),
    )
    monkeypatch.setattr(
        live_ingest,
        "_snapshot_ingest_to_consumer",
        lambda *args: events.append("snapshot"),
    )

    with pytest.raises(SystemExit) as exc_info:
        live_ingest.main()

    assert exc_info.value.code == 1
    assert events == ["checkpoint"]


def test_hourly_partial_ingest_suppresses_snapshot_after_checkpoint_close(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    events: list[str] = []
    settings = SimpleNamespace(
        ingest_duckdb_path=tmp_path / "market_ingest.duckdb",
        duckdb_path=tmp_path / "market.duckdb",
        timeframes_list=["15m"],
        pa_backtest_years=1,
    )
    monkeypatch.setenv("PA_INGEST_HOURLY_SYMBOLS", "binance:BTC/USDT")
    monkeypatch.setattr(ingest_ccxt, "get_settings", lambda: settings)
    monkeypatch.setattr(ingest_ccxt, "OHLCVStore", _FakeLiveStore)
    monkeypatch.setattr(ingest_ccxt, "_build_ccxt", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(
        ingest_ccxt,
        "ingest_symbol",
        lambda **kwargs: IngestStats(
            venue="binance",
            symbol="BTC/USDT",
            timeframe="15m",
            rows_written=0,
            fetched_pages=0,
            error="fetch failed",
        ),
    )
    monkeypatch.setattr(
        ingest_ccxt,
        "checkpoint_and_close_pool_for_path",
        lambda path: events.append("checkpoint"),
    )
    monkeypatch.setattr(
        ingest_ccxt,
        "_snapshot_ingest_to_consumer",
        lambda *args: events.append("snapshot"),
    )

    result = asyncio.run(ingest_ccxt.run_hourly())

    assert events == ["checkpoint"]
    assert result["ingested"] == 0
    assert result["errors"]
    assert result["snapshot"]["snapshotted"] is False
    assert "SNAPSHOT_SUPPRESSED_PARTIAL_INGEST" in result["snapshot"]["error"]


def test_hourly_success_checkpoints_before_validated_snapshot(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    events: list[str] = []
    settings = SimpleNamespace(
        ingest_duckdb_path=tmp_path / "market_ingest.duckdb",
        duckdb_path=tmp_path / "market.duckdb",
        timeframes_list=["15m"],
        pa_backtest_years=1,
    )
    monkeypatch.setenv("PA_INGEST_HOURLY_SYMBOLS", "binance:BTC/USDT")
    monkeypatch.setattr(ingest_ccxt, "get_settings", lambda: settings)
    monkeypatch.setattr(ingest_ccxt, "OHLCVStore", _FakeLiveStore)
    monkeypatch.setattr(ingest_ccxt, "_build_ccxt", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(
        ingest_ccxt,
        "ingest_symbol",
        lambda **kwargs: IngestStats(
            venue="binance",
            symbol="BTC/USDT",
            timeframe="15m",
            rows_written=1,
            fetched_pages=1,
            error=None,
        ),
    )
    monkeypatch.setattr(
        ingest_ccxt,
        "checkpoint_and_close_pool_for_path",
        lambda path: events.append("checkpoint"),
    )

    def _snapshot(source: Path, consumer: Path) -> dict[str, object]:
        del source, consumer
        assert events[-1] == "checkpoint"
        events.append("snapshot")
        return {"snapshotted": True, "bytes": 123, "newest_bar": "bar", "error": None}

    monkeypatch.setattr(ingest_ccxt, "_snapshot_ingest_to_consumer", _snapshot)

    result = asyncio.run(ingest_ccxt.run_hourly())

    assert events == ["checkpoint", "snapshot"]
    assert result["ingested"] == 1
    assert result["errors"] == []
    assert result["snapshot"]["snapshotted"] is True


def test_hourly_ingest_reuses_one_exchange_per_venue(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    settings = SimpleNamespace(
        ingest_duckdb_path=tmp_path / "market_ingest.duckdb",
        duckdb_path=tmp_path / "market.duckdb",
        timeframes_list=["1d", "1w"],
        pa_backtest_years=1,
    )
    monkeypatch.setenv(
        "PA_INGEST_HOURLY_SYMBOLS",
        "binance:BTC/USDT,binance:ETH/USDT",
    )
    monkeypatch.setattr(ingest_ccxt, "get_settings", lambda: settings)
    monkeypatch.setattr(ingest_ccxt, "OHLCVStore", _FakeLiveStore)
    build_calls: list[str] = []
    client = object()

    def _build(venue: str, *, market_type: str) -> object:
        assert market_type == "future"
        build_calls.append(venue)
        return client

    seen_clients: list[object] = []

    def _ingest(**kwargs) -> IngestStats:
        seen_clients.append(kwargs["exchange"])
        return IngestStats(
            venue=kwargs["venue"],
            symbol=kwargs["symbol"],
            timeframe=kwargs["timeframe"],
            rows_written=1,
            fetched_pages=1,
            error=None,
        )

    monkeypatch.setattr(ingest_ccxt, "_build_ccxt", _build)
    monkeypatch.setattr(ingest_ccxt, "ingest_symbol", _ingest)
    monkeypatch.setattr(ingest_ccxt, "checkpoint_and_close_pool_for_path", lambda _path: None)
    monkeypatch.setattr(
        ingest_ccxt,
        "_snapshot_ingest_to_consumer",
        lambda *_args: {"snapshotted": True, "error": None},
    )

    result = asyncio.run(ingest_ccxt.run_hourly())

    assert build_calls == ["binance"]
    assert seen_clients == [client, client, client, client]
    assert result["ingested"] == 4
