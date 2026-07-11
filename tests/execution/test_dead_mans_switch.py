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
from unittest.mock import MagicMock

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
    dms, _ = tmp_dms
    # Age the heartbeat file (instead of just in-memory timestamp)
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


def test_emergency_flatten_cancels_wrapped_algo_response_once(tmp_path, monkeypatch):
    """Binance'in ``{orders: [...]}`` şekli de iptal ve tek alarm üretir."""
    import price_action.execution.dead_mans_switch as dms_mod

    monkeypatch.setattr(dms_mod, "KILL_SWITCH_PATH", tmp_path / "kill_switch.json")
    mock_ex = MagicMock()
    mock_ex.fetch_positions.return_value = []
    mock_ex.fapiPrivateGetOpenAlgoOrders.return_value = {
        "orders": [{"symbol": "BTCUSDT", "algoId": "12345"}]
    }
    dms = DeadMansSwitch(
        mock_ex,
        service_name="wrapped_algo",
        db_path=tmp_path / "wrapped_algo.duckdb",
        heartbeat_file=tmp_path / "wrapped_algo.hb",
        timeout_sec=300,
    )
    dms._send_alarm = MagicMock()

    try:
        assert dms._emergency_flatten() is True
        mock_ex.fapiPrivateDeleteAlgoOrder.assert_called_once_with(
            {"symbol": "BTCUSDT", "algoId": "12345"}
        )
        dms._send_alarm.assert_called_once()
    finally:
        dms.stop()


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


def test_external_heartbeat_uses_main_loop_without_private_rest_poll(tmp_path):
    """15m mode keeps the exchange only for stale-triggered emergency flatten."""
    exchange = MagicMock()
    dms = DeadMansSwitch(
        exchange=exchange,
        service_name="external_hb",
        db_path=tmp_path / "external.duckdb",
        heartbeat_file=tmp_path / "external.txt",
        heartbeat_sec=1,
        timeout_sec=300,
        external_heartbeat=True,
    )

    dms.start()
    try:
        assert dms.external_heartbeat is True
        assert dms._heartbeat_thread is None
        assert dms._watchdog_thread is not None
        assert dms._watchdog_thread.is_alive()
        dms.ping(equity_usdt=1234.5, n_open_positions=2)
        exchange.fapiPrivateV2GetAccount.assert_not_called()
        exchange.fetch_positions.assert_not_called()
    finally:
        dms.stop()


def test_active_private_rest_cooldown_defers_without_spending_retry_budget(tmp_path):
    deadline = {"value": time.time() + 600}
    dms = DeadMansSwitch(
        exchange=MagicMock(),
        service_name="cooldown_defer",
        db_path=tmp_path / "cooldown.duckdb",
        heartbeat_file=tmp_path / "cooldown.txt",
        timeout_sec=1,
        retry_not_before_reader=lambda: deadline["value"],
    )
    os.utime(dms._watchdog.heartbeat_file, (time.time() - 10, time.time() - 10))
    dms._emergency_flatten = MagicMock(return_value=False)

    for _ in range(10):
        dms._watchdog_check()

    assert dms._emergency_flatten.call_count == 0
    assert dms._flatten_attempts == 0
    assert dms._flatten_done is False

    deadline["value"] = 0.0
    dms._emergency_flatten.return_value = True
    dms._watchdog_check()
    assert dms._emergency_flatten.call_count == 1
    assert dms._flatten_attempts == 1
    assert dms._flatten_done is True
    dms.stop()


def test_cooldown_created_during_flatten_does_not_spend_retry(tmp_path):
    deadline = {"value": 0.0}
    calls = {"count": 0}
    dms = DeadMansSwitch(
        exchange=MagicMock(),
        service_name="cooldown_race",
        db_path=tmp_path / "cooldown-race.duckdb",
        heartbeat_file=tmp_path / "cooldown-race.txt",
        timeout_sec=1,
        retry_not_before_reader=lambda: deadline["value"],
    )
    os.utime(dms._watchdog.heartbeat_file, (time.time() - 10, time.time() - 10))

    def _flatten_once_banned_then_ok():
        calls["count"] += 1
        if calls["count"] == 1:
            deadline["value"] = time.time() + 600
            return False
        return True

    dms._emergency_flatten = MagicMock(side_effect=_flatten_once_banned_then_ok)
    dms._watchdog_check()
    assert dms._flatten_attempts == 0
    assert dms._flatten_done is False

    deadline["value"] = 0.0
    dms._watchdog_check()
    assert dms._emergency_flatten.call_count == 2
    assert dms._flatten_attempts == 1
    assert dms._flatten_done is True
    dms.stop()


def test_unreadable_cooldown_state_fails_closed_without_spending_retry(tmp_path):
    def _broken_reader():
        raise ValueError("corrupt state")

    dms = DeadMansSwitch(
        exchange=MagicMock(),
        service_name="cooldown_corrupt",
        db_path=tmp_path / "cooldown-corrupt.duckdb",
        heartbeat_file=tmp_path / "cooldown-corrupt.txt",
        timeout_sec=1,
        retry_not_before_reader=_broken_reader,
    )
    os.utime(dms._watchdog.heartbeat_file, (time.time() - 10, time.time() - 10))
    dms._emergency_flatten = MagicMock(return_value=False)
    dms._send_alarm = MagicMock()

    dms._watchdog_check()
    dms._watchdog_check()

    assert dms._emergency_flatten.call_count == 0
    assert dms._flatten_attempts == 0
    assert dms._flatten_done is False
    dms._send_alarm.assert_called_once()
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
    dms, _ = tmp_dms
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
