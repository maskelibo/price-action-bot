"""DeadMansSwitch TF-aware constructor testleri — SEC31.

Yeni ozellikler:
  - DeadMansSwitch(exchange, tf="1m")  → heartbeat=5s, timeout=120s, watchdog=3s
  - DeadMansSwitch(exchange, tf="5m")  → heartbeat=10s, timeout=600s, watchdog=5s
  - DeadMansSwitch(exchange, tf="15m") → heartbeat=20s, timeout=1800s, watchdog=10s
  - DeadMansSwitch(exchange, tf="1d")  → heartbeat=60s, timeout=300s, watchdog=30s (default)
  - Explicit override: heartbeat_sec=999 → override kazanir

Senaryolar:
  1) test_default_tf_1d_params      — default tf="1d": timeout=300s
  2) test_tf_15m_params             — 15m: timeout=1800s, heartbeat=20s
  3) test_tf_5m_params              — 5m: timeout=600s, heartbeat=10s
  4) test_tf_1m_params              — 1m: timeout=120s, heartbeat=5s, watchdog=3s
  5) test_explicit_override         — heartbeat_sec explicit → override kazanir
  6) test_tf_stored_on_instance     — .tf attribute dogrulama
  7) test_watchdog_interval_scales  — _watchdog_interval TF ile degisiyor
"""
from __future__ import annotations

import pytest

from price_action.execution.dead_mans_switch import DeadMansSwitch, TF_DMS_PARAMS


# ===== Parametre dogrulamalari (exchange=None, thread baslatma yok) =====

def test_default_tf_1d_params():
    """Senaryo 1: default tf='1d' → timeout=300s, heartbeat=60s."""
    dms = DeadMansSwitch(exchange=None, tf="1d")
    assert dms.timeout_sec == 300
    assert dms.heartbeat_sec == 60
    assert dms._watchdog_interval == 30
    assert dms.tf == "1d"


def test_tf_15m_params():
    """Senaryo 2: tf='15m' → timeout=1800s (30dk)."""
    dms = DeadMansSwitch(exchange=None, tf="15m")
    assert dms.timeout_sec == 1800
    assert dms.heartbeat_sec == 20
    assert dms._watchdog_interval == 10
    assert dms.tf == "15m"


def test_tf_5m_params():
    """Senaryo 3: tf='5m' → timeout=600s (10dk)."""
    dms = DeadMansSwitch(exchange=None, tf="5m")
    assert dms.timeout_sec == 600
    assert dms.heartbeat_sec == 10
    assert dms._watchdog_interval == 5


def test_tf_1m_params():
    """Senaryo 4: tf='1m' → timeout=120s (2dk), heartbeat=5s, watchdog=3s."""
    dms = DeadMansSwitch(exchange=None, tf="1m")
    assert dms.timeout_sec == 120
    assert dms.heartbeat_sec == 5
    assert dms._watchdog_interval == 3


def test_explicit_override():
    """Senaryo 5: explicit heartbeat_sec / timeout_sec → override kazanir."""
    dms = DeadMansSwitch(
        exchange=None,
        tf="1m",
        heartbeat_sec=999,
        timeout_sec=888,
    )
    assert dms.heartbeat_sec == 999
    assert dms.timeout_sec == 888
    # watchdog hala TF'den geliyor
    assert dms._watchdog_interval == 3


def test_tf_stored_on_instance():
    """Senaryo 6: .tf attribute dogrulama."""
    for tf in ["1m", "5m", "15m", "1h", "4h", "1d"]:
        dms = DeadMansSwitch(exchange=None, tf=tf)
        assert dms.tf == tf


def test_watchdog_interval_scales():
    """Senaryo 7: _watchdog_interval TF kuculdukce azaliyor."""
    dms_1d  = DeadMansSwitch(exchange=None, tf="1d")
    dms_15m = DeadMansSwitch(exchange=None, tf="15m")
    dms_5m  = DeadMansSwitch(exchange=None, tf="5m")
    dms_1m  = DeadMansSwitch(exchange=None, tf="1m")

    # 1d > 15m > 5m > 1m
    assert dms_1d._watchdog_interval > dms_15m._watchdog_interval
    assert dms_15m._watchdog_interval > dms_5m._watchdog_interval
    assert dms_5m._watchdog_interval > dms_1m._watchdog_interval


def test_tf_dms_params_table_complete():
    """TF_DMS_PARAMS tablosu gerekli TF'leri icerir."""
    required = {"1m", "5m", "15m", "1h", "4h", "1d"}
    assert required.issubset(set(TF_DMS_PARAMS.keys()))
    for tf, cfg in TF_DMS_PARAMS.items():
        assert "heartbeat_sec" in cfg
        assert "timeout_sec" in cfg
        assert "watchdog_sec" in cfg
        # Mantik tutarlilik: timeout > heartbeat
        assert cfg["timeout_sec"] > cfg["heartbeat_sec"]


def test_timeout_hierarchy():
    """Kucuk TF → kucuk timeout (daha agresif failsafe)."""
    params_1m  = TF_DMS_PARAMS["1m"]
    params_5m  = TF_DMS_PARAMS["5m"]
    params_15m = TF_DMS_PARAMS["15m"]
    params_1d  = TF_DMS_PARAMS["1d"]

    # 1d (swing) daha kucuk timeout kabul edilebilir (5dk vs 30dk)
    # 1m daha agresif timeout olmali
    assert params_1m["timeout_sec"] < params_5m["timeout_sec"]
    assert params_5m["timeout_sec"] < params_15m["timeout_sec"]
