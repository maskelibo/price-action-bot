from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path

import duckdb
import pandas as pd
import pytest

from price_action.lab import crypto_15m_snapshot_io as snapshot_io


def test_verify_frozen_snapshot_requires_exact_size_and_hash(tmp_path: Path) -> None:
    path = tmp_path / "snapshot.duckdb"
    payload = b"immutable-snapshot"
    path.write_bytes(payload)
    spec = {
        "path": path.name,
        "bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }

    verified = snapshot_io.verify_frozen_snapshot("market", spec, repo_root=tmp_path)
    assert verified.bytes == len(payload)
    assert verified.sha256 == spec["sha256"]
    assert verified.resolved_path == str(path.resolve())

    with pytest.raises(ValueError, match="byte-size mismatch"):
        snapshot_io.verify_frozen_snapshot(
            "market", {**spec, "bytes": len(payload) + 1}, repo_root=tmp_path
        )
    with pytest.raises(ValueError, match="SHA256 mismatch"):
        snapshot_io.verify_frozen_snapshot(
            "market", {**spec, "sha256": "0" * 64}, repo_root=tmp_path
        )


def test_market_loader_keeps_independent_symbol_timestamps(tmp_path: Path) -> None:
    path = tmp_path / "market.duckdb"
    timestamps = pd.date_range("2024-01-01T00:00:00Z", periods=3, freq="15min")
    connection = duckdb.connect(str(path))
    try:
        connection.execute(
            """
            CREATE TABLE ohlcv (
                venue VARCHAR, symbol VARCHAR, timeframe VARCHAR, ts TIMESTAMPTZ,
                open DOUBLE, high DOUBLE, low DOUBLE, close DOUBLE, volume DOUBLE
            )
            """
        )
        rows = []
        for symbol, selected in (
            ("BTCUSDT", timestamps),
            ("ETH-USDT", timestamps[[0, 2]]),
        ):
            rows.extend(
                ("binance", symbol, "15m", ts.to_pydatetime(), 100.0, 101.0, 99.0, 100.0, 1.0)
                for ts in selected
            )
        connection.executemany("INSERT INTO ohlcv VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)
    finally:
        connection.close()

    bundle = snapshot_io.load_market_snapshot(
        path,
        {"table": "ohlcv", "venue": "binance", "timeframe": "15m"},
        symbols=("BTC/USDT", "ETH/USDT"),
        start=timestamps[0],
        end=timestamps[-1] + pd.Timedelta(minutes=15),
    )

    assert bundle.rows_by_symbol == {"BTC/USDT": 3, "ETH/USDT": 2}
    assert list(bundle.frames["BTC/USDT"]["ts"]) == list(timestamps)
    assert list(bundle.frames["ETH/USDT"]["ts"]) == [timestamps[0], timestamps[2]]


def test_funding_loader_preserves_fractional_timestamps_and_null_mark_fallback(
    tmp_path: Path,
) -> None:
    path = tmp_path / "funding.duckdb"
    first = datetime(2024, 1, 1, 0, 0, 0, 500_000, tzinfo=UTC)
    second = datetime(2024, 1, 1, 8, 0, 0, 750_000, tzinfo=UTC)
    connection = duckdb.connect(str(path))
    try:
        connection.execute(
            """
            CREATE TABLE funding_rates (
                venue VARCHAR, symbol VARCHAR, ts TIMESTAMPTZ,
                funding_rate DOUBLE, mark_price DOUBLE
            )
            """
        )
        connection.executemany(
            "INSERT INTO funding_rates VALUES (?, ?, ?, ?, ?)",
            [
                ("binance", "ETH", first, 0.0001, None),
                ("binance", "ETH", second, 0.0002, -1.0),
                ("binance", "SOL", first, -0.0001, 123.0),
                ("binance", "SOL", second, -0.0002, float("nan")),
            ],
        )
    finally:
        connection.close()

    bundle = snapshot_io.load_funding_snapshot(
        path,
        {"table": "funding_rates"},
        symbols=("ETH/USDT", "SOL/USDT"),
        venue="binance",
        start=pd.Timestamp("2024-01-01T00:00:00Z"),
        engine_start=pd.Timestamp("2024-01-01T00:00:00Z"),
        end=pd.Timestamp("2024-01-02T00:00:00Z"),
    )

    assert bundle.engine_events[0]["ts"].microsecond == 500_000
    marks = {(item["symbol"], item["ts"]): item["mark_price"] for item in bundle.engine_events}
    assert marks[("ETH/USDT", first)] is None
    assert marks[("ETH/USDT", second)] is None
    assert marks[("SOL/USDT", first)] == pytest.approx(123.0)
    assert marks[("SOL/USDT", second)] is None


def test_loaders_reject_unsafe_table_identifiers_before_connect(tmp_path: Path) -> None:
    missing = tmp_path / "missing.duckdb"
    with pytest.raises(ValueError, match="unsafe market table"):
        snapshot_io.load_market_snapshot(
            missing,
            {"table": "ohlcv; DROP TABLE x", "venue": "binance", "timeframe": "15m"},
            symbols=("BTC/USDT",),
            start=pd.Timestamp("2024-01-01T00:00:00Z"),
            end=pd.Timestamp("2024-01-02T00:00:00Z"),
        )
    assert not missing.exists()
