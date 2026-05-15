"""Dead Man's Switch testleri.

- Heartbeat property is_triggered
- Flatten senaryosu (mock exchange)
- Kill switch dosyası yazımı
- DMS stop
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from price_action.execution.dead_mans_switch import DeadMansSwitch


@pytest.fixture
def tmp_dms(tmp_path):
    db = tmp_path / "dms_test.duckdb"
    ks = tmp_path / "kill_switch.json"
    dms = DeadMansSwitch(
        exchange=None,
        service_name="test_svc",
        db_path=db,
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
    dms._last_heartbeat_ts = time.time() - 30
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


def test_heartbeat_write_to_db(tmp_path):
    """Heartbeat DB'ye yazıyor mu?"""
    import duckdb
    db = tmp_path / "hb_test.duckdb"
    dms = DeadMansSwitch(exchange=None, service_name="hb_test", db_path=db)
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
