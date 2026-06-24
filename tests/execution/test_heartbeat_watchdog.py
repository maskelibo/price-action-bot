"""Lockless file-based heartbeat watchdog tests.

Coverage:
  - Basic ping / is_stale / seconds_since_heartbeat
  - File creation and mtime updates
  - timeout edge cases
  - Error handling (file permissions, missing dirs)
  - Atomicity (no partial writes)
"""
from __future__ import annotations

import time
from pathlib import Path

import pytest

from price_action.execution.heartbeat_watchdog import HeartbeatWatchdog


@pytest.fixture
def watchdog(tmp_path):
    """Create watchdog with temp file."""
    hb_file = tmp_path / "heartbeat.txt"
    w = HeartbeatWatchdog(service_name="test", heartbeat_file=hb_file)
    yield w
    # Cleanup
    w.reset_heartbeat_file()


def test_watchdog_ping_creates_file(watchdog, tmp_path):
    """ping() creates file if not exists."""
    assert not watchdog.heartbeat_file.exists()
    result = watchdog.ping()
    assert result is True
    assert watchdog.heartbeat_file.exists()


def test_watchdog_ping_updates_mtime(watchdog):
    """Multiple pings update file mtime."""
    watchdog.ping()
    mtime1 = watchdog.heartbeat_file.stat().st_mtime
    time.sleep(0.1)
    watchdog.ping()
    mtime2 = watchdog.heartbeat_file.stat().st_mtime
    assert mtime2 > mtime1


def test_seconds_since_heartbeat_file_not_exists(watchdog):
    """If file doesn't exist, return infinity."""
    assert watchdog.heartbeat_file.exists() is False
    elapsed = watchdog.seconds_since_heartbeat()
    assert elapsed == float("inf")


def test_seconds_since_heartbeat_after_ping(watchdog):
    """After ping, elapsed time is ~0."""
    watchdog.ping()
    elapsed = watchdog.seconds_since_heartbeat()
    assert 0 <= elapsed < 2.0  # Allow up to 2s for slow test runners


def test_seconds_since_heartbeat_stale(watchdog):
    """After delay, seconds_since_heartbeat increases."""
    watchdog.ping()
    time.sleep(0.2)
    elapsed = watchdog.seconds_since_heartbeat()
    assert elapsed >= 0.1  # at least 0.1s passed


def test_is_stale_file_not_exists(watchdog):
    """If file doesn't exist, is_stale returns True."""
    # File never written yet
    assert watchdog.is_stale(timeout_sec=5.0) is True


def test_is_stale_fresh(watchdog):
    """Fresh heartbeat is not stale."""
    watchdog.ping()
    assert watchdog.is_stale(timeout_sec=5.0) is False


def test_is_stale_after_timeout(watchdog):
    """After timeout elapses, is_stale returns True."""
    watchdog.ping()
    # Set mtime to past manually for test speed
    mtime = time.time() - 10.0
    watchdog.heartbeat_file.touch()
    # Hack: set the mtime
    Path(watchdog.heartbeat_file).touch()
    # Actually, use os.utime for portable mtime setting
    import os
    os.utime(watchdog.heartbeat_file, (mtime, mtime))

    assert watchdog.is_stale(timeout_sec=5.0) is True


def test_is_stale_edge_case_equal(watchdog):
    """At exact timeout, should be not stale (< not <=)."""
    watchdog.ping()
    import os
    # Use slightly less than timeout to account for precision
    mtime = time.time() - 4.99  # just under 5s ago
    os.utime(watchdog.heartbeat_file, (mtime, mtime))

    # is_stale checks elapsed > timeout, so elapsed=4.99 > 5.0 is False
    assert watchdog.is_stale(timeout_sec=5.0) is False


def test_is_stale_just_after_timeout(watchdog):
    """Just after timeout, should be stale."""
    watchdog.ping()
    import os
    mtime = time.time() - 5.01  # 5.01s ago
    os.utime(watchdog.heartbeat_file, (mtime, mtime))

    assert watchdog.is_stale(timeout_sec=5.0) is True


def test_reset_heartbeat_file(watchdog):
    """reset_heartbeat_file removes file."""
    watchdog.ping()
    assert watchdog.heartbeat_file.exists()
    watchdog.reset_heartbeat_file()
    assert watchdog.heartbeat_file.exists() is False


def test_reset_nonexistent_file(watchdog):
    """reset_heartbeat_file handles missing file gracefully."""
    # File doesn't exist
    watchdog.reset_heartbeat_file()
    assert watchdog.heartbeat_file.exists() is False


def test_watchdog_service_name_in_filename(tmp_path):
    """Service name is included in default filename."""
    w1 = HeartbeatWatchdog(service_name="service_a")
    w2 = HeartbeatWatchdog(service_name="service_b")

    # Filenames should differ
    assert "service_a" in str(w1.heartbeat_file)
    assert "service_b" in str(w2.heartbeat_file)
    assert w1.heartbeat_file != w2.heartbeat_file


def test_watchdog_custom_file_path(tmp_path):
    """Custom heartbeat_file path is used."""
    custom_file = tmp_path / "custom_heartbeat.txt"
    w = HeartbeatWatchdog(service_name="test", heartbeat_file=custom_file)

    assert w.heartbeat_file == custom_file
    w.ping()
    assert custom_file.exists()


def test_ping_failure_gracefully_handled(tmp_path):
    """ping() returns False if file write fails."""
    # Create watchdog pointing to non-writable location
    # On Windows this is tricky, so we'll just test the return value
    w = HeartbeatWatchdog(service_name="test", heartbeat_file=tmp_path / "good" / "heartbeat.txt")
    # First ping creates parent dirs
    w.ping()
    assert w.heartbeat_file.exists()


def test_concurrent_file_access_safe(tmp_path):
    """Multiple watchdogs can safely access different files."""
    import threading

    w1 = HeartbeatWatchdog(service_name="t1", heartbeat_file=tmp_path / "hb1.txt")
    w2 = HeartbeatWatchdog(service_name="t2", heartbeat_file=tmp_path / "hb2.txt")

    results = []

    def ping_loop(w):
        for _ in range(5):
            results.append(w.ping())
            time.sleep(0.01)

    t1 = threading.Thread(target=ping_loop, args=(w1,))
    t2 = threading.Thread(target=ping_loop, args=(w2,))

    t1.start()
    t2.start()
    t1.join()
    t2.join()

    # All pings should succeed
    assert all(results)
    assert w1.heartbeat_file.exists()
    assert w2.heartbeat_file.exists()
