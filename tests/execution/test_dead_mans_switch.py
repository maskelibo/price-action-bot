"""Dead Man's Switch testleri.

- Heartbeat property is_triggered (via file watchdog primary path)
- Fallback to in-memory timestamp if file unavailable
- Flatten senaryosu (mock exchange)
- Kill switch dosyası yazımı
- DMS stop + file cleanup
- DuckDB lock doesn't affect DMS (file watchdog is primary)
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from price_action.execution.dead_mans_switch import DeadMansSwitch


@pytest.fixture
def tmp_dms(tmp_path):
    db = tmp_path / "dms_test.duckdb"
    hb_file = tmp_path / "heartbeat.txt"
    ks = tmp_path / "kill_switch.json"
    dms = DeadMansSwitch(
        exchange=None,
        service_name="test_svc",
        db_path=db,
        heartbeat_file=hb_file,
        heartbeat_sec=60,
        timeout_sec=5,  # kısa timeout test için
    )
    # Kill switch yolunu override et
    import price_action.execution.dead_mans_switch as dms_mod
    dms._original_ks = dms_mod.KILL_SWITCH_PATH
    dms_mod.KILL_SWITCH_PATH = ks
    yield dms, tmp_path
    # Cleanup
    dms_mod.KILL_SWITCH_PATH = dms._original_ks
    dms.stop()


def test_not_triggered_initially(tmp_dms):
    dms, _ = tmp_dms
    assert not dms.is_triggered


def test_triggered_after_timeout(tmp_dms):
    dms, _ = tmp_dms
    # Timeout 5s — _last_heartbeat_ts'i geçmişe ayarla
    dms._last_heartbeat_ts = time.time() - 10  # 10s geçti, timeout=5s
    assert dms.is_triggered


def test_seconds_since_heartbeat(tmp_dms):
    dms, tmp_path = tmp_dms
    # Age the heartbeat file (instead of just in-memory timestamp)
    import os
    hb_file = dms._watchdog.heartbeat_file
    mtime = time.time() - 30
    os.utime(hb_file, (mtime, mtime))
    assert dms.seconds_since_heartbeat >= 29


def test_ping_resets_timer(tmp_dms):
    dms, _ = tmp_dms
    dms._last_heartbeat_ts = time.time() - 10
    assert dms.is_triggered
    dms.ping()
    assert not dms.is_triggered


def test_emergency_flatten_calls_exchange(tmp_path):
    """Flatten: pozisyon var → market close + algo cancel."""
    mock_ex = MagicMock()
    mock_ex.fetch_positions.return_value = [
        {"symbol": "BTC/USDT:USDT", "contracts": 0.01, "side": "long"},
        {"symbol": "ETH/USDT:USDT", "contracts": 0.1, "side": "short"},
    ]
    mock_ex.fapiPrivateGetOpenAlgoOrders.return_value = [
        {"symbol": "BTCUSDT", "algoId": "12345"},
    ]

    db = tmp_path / "flatten_test.duckdb"
    ks = tmp_path / "kill_switch.json"

    import price_action.execution.dead_mans_switch as dms_mod
    orig_ks = dms_mod.KILL_SWITCH_PATH
    dms_mod.KILL_SWITCH_PATH = ks

    try:
        dms = DeadMansSwitch(mock_ex, service_name="test", db_path=db, timeout_sec=300)
        dms._emergency_flatten()

        # create_market_order iki kez çağrıldı (2 pozisyon)
        assert mock_ex.create_market_order.call_count == 2
        # algo cancel çağrıldı
        assert mock_ex.fapiPrivateDeleteAlgoOrder.call_count == 1
        # Kill switch yazıldı
        assert ks.exists()
        with open(ks) as f:
            ks_data = json.load(f)
        assert ks_data["halted"] is True
        assert ks_data["reason"] == "dead_mans_switch"
    finally:
        dms_mod.KILL_SWITCH_PATH = orig_ks


def test_heartbeat_write_to_file(tmp_path):
    """Heartbeat file mtime updated?"""
    hb_file = tmp_path / "hb_test.txt"
    dms = DeadMansSwitch(
        exchange=None,
        service_name="hb_test",
        heartbeat_file=hb_file,
        timeout_sec=300,
    )
    dms.ping()

    assert hb_file.exists()
    # File should have been touched
    assert time.time() - hb_file.stat().st_mtime < 5.0
    dms.stop()


def test_heartbeat_write_to_db(tmp_path):
    """Heartbeat DB'ye de yazıyor mu (fallback)?"""
    import duckdb
    db = tmp_path / "hb_test.duckdb"
    hb_file = tmp_path / "hb_test.txt"
    dms = DeadMansSwitch(
        exchange=None,
        service_name="hb_test",
        db_path=db,
        heartbeat_file=hb_file,
    )
    dms._write_heartbeat(equity_usdt=1000.0, n_open_positions=2)

    con = duckdb.connect(str(db))
    rows = con.execute(
        "SELECT service, equity_usdt, n_open_positions FROM heartbeat_log"
    ).fetchall()
    con.close()

    assert len(rows) == 1
    assert rows[0][0] == "hb_test"
    assert rows[0][1] == pytest.approx(1000.0)
    assert rows[0][2] == 2
    dms.stop()


def test_heartbeat_file_exists_after_init(tmp_dms):
    """File is created during __init__ for safety."""
    dms, tmp_path = tmp_dms
    # File should exist now (initialized in __init__)
    assert dms._watchdog.heartbeat_file.exists() is True


def test_triggered_via_file_mtime(tmp_path):
    """is_triggered checks file mtime (primary path)."""
    hb_file = tmp_path / "hb.txt"
    dms = DeadMansSwitch(
        exchange=None,
        service_name="test",
        heartbeat_file=hb_file,
        timeout_sec=5,
    )
    # File exists (initialized in __init__) and is fresh → NOT triggered
    assert dms.is_triggered is False

    # Set mtime to past
    import os
    mtime = time.time() - 10.0
    os.utime(hb_file, (mtime, mtime))

    # Now it should be triggered
    assert dms.is_triggered is True

    # Fresh ping resets
    dms.ping()
    assert dms.is_triggered is False

    dms.stop()


def test_seconds_since_heartbeat_via_file(tmp_path):
    """seconds_since_heartbeat uses file mtime."""
    hb_file = tmp_path / "hb.txt"
    dms = DeadMansSwitch(
        exchange=None,
        service_name="test",
        heartbeat_file=hb_file,
        timeout_sec=300,
    )

    # File not written yet → return in-memory fallback (~0)
    elapsed1 = dms.seconds_since_heartbeat
    assert elapsed1 < 1.0

    # After ping
    dms.ping()
    elapsed2 = dms.seconds_since_heartbeat
    assert elapsed2 < 1.0

    # Age file
    import os
    mtime = time.time() - 10.0
    os.utime(hb_file, (mtime, mtime))

    elapsed3 = dms.seconds_since_heartbeat
    assert elapsed3 >= 9.0  # ~10s
    dms.stop()


def test_duckdb_lock_does_not_affect_dms(tmp_path):
    """
    CRITICAL: If DuckDB is locked, DMS heartbeat still works via file watchdog.

    Scenario:
      1. DMS starts, heartbeat loop writes to file every 60s
      2. DuckDB gets locked (e.g., concurrent access)
      3. Heartbeat file write still succeeds (lockless)
      4. Watchdog checks file mtime, does NOT trigger false positive
    """
    db = tmp_path / "idem.duckdb"
    hb_file = tmp_path / "hb.txt"
    ks = tmp_path / "kill.json"

    import price_action.execution.dead_mans_switch as dms_mod
    orig_ks = dms_mod.KILL_SWITCH_PATH
    dms_mod.KILL_SWITCH_PATH = ks

    try:
        dms = DeadMansSwitch(
            exchange=None,
            service_name="test",
            db_path=db,
            heartbeat_file=hb_file,
            heartbeat_sec=1,
            timeout_sec=5,
        )

        # Ping several times — file updates work
        for _ in range(3):
            dms.ping()
            time.sleep(0.5)

        # File should exist and be fresh
        assert hb_file.exists()
        elapsed = dms.seconds_since_heartbeat
        assert elapsed < 2.0

        # Now simulate DuckDB lock by holding a connection
        import duckdb
        con_lock = duckdb.connect(str(db))
        # Start a transaction that holds the lock
        con_lock.execute("BEGIN TRANSACTION")

        # Try to write heartbeat — file write should still work
        result = dms._watchdog.ping()
        assert result is True  # File write succeeded despite DB lock

        # Watchdog should NOT be triggered (file is fresh)
        assert dms.is_triggered is False

        con_lock.close()
        dms.stop()

    finally:
        dms_mod.KILL_SWITCH_PATH = orig_ks


def test_dms_stop_cleans_heartbeat_file(tmp_path):
    """stop() removes heartbeat file."""
    hb_file = tmp_path / "hb.txt"
    dms = DeadMansSwitch(
        exchange=None,
        service_name="test",
        heartbeat_file=hb_file,
    )
    dms.ping()
    assert hb_file.exists()

    dms.stop()
    # File should be cleaned up
    assert hb_file.exists() is False
