"""P1c Walker test — sizing tier + halt logic + state persist.

Run:
    cd ~/price-action-bot
    PYTHONPATH=src .venv/bin/python -m pytest tests/test_p1c_walker.py -v
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from price_action.execution.p1c_walker import P1cConfig, P1cWalker


@pytest.fixture
def tmp_state(tmp_path, monkeypatch):
    tmp_state_file = tmp_path / "p1c_walker_state.json"
    monkeypatch.setattr("price_action.execution.p1c_walker._STATE_FILE", tmp_state_file)
    monkeypatch.setattr("price_action.execution.p1c_walker._STATE_DIR", tmp_path)
    yield tmp_state_file


@pytest.fixture
def walker(tmp_state):
    return P1cWalker()


def test_vol_z_high_tier(walker):
    sig = {"symbol": "BTC/USDT", "strategy": "vsa_climax_test", "vol_z": 2.5,
           "entry_price": 50000, "sl_price": 48500}
    dec = walker.evaluate_signal(sig)
    assert dec["accept"] is True
    assert dec["risk_pct"] == 0.007
    assert dec["tier"] == "high"


def test_vol_z_normal_tier(walker):
    sig = {"symbol": "BTC/USDT", "strategy": "vsa_climax_test", "vol_z": 1.0,
           "entry_price": 50000, "sl_price": 48500}
    dec = walker.evaluate_signal(sig)
    assert dec["risk_pct"] == 0.005
    assert dec["tier"] == "normal"


def test_vol_z_low_tier(walker):
    sig = {"symbol": "BTC/USDT", "strategy": "vsa_climax_test", "vol_z": -0.5,
           "entry_price": 50000, "sl_price": 48500}
    dec = walker.evaluate_signal(sig)
    assert dec["risk_pct"] == 0.003
    assert dec["tier"] == "low"


def test_dropped_strategy_rejected(walker):
    sig = {"symbol": "BTC/USDT", "strategy": "engulfing_continuation", "vol_z": 1.0,
           "entry_price": 50000, "sl_price": 48500}
    dec = walker.evaluate_signal(sig)
    assert dec["accept"] is False
    assert "strategy_dropped" in dec["reason"]


def test_per_symbol_cap(walker):
    walker.record_open_position({"symbol": "BTC/USDT", "entry_price": 50000})
    sig = {"symbol": "BTC/USDT", "strategy": "vsa_climax_test", "vol_z": 1.0,
           "entry_price": 51000, "sl_price": 49000}
    dec = walker.evaluate_signal(sig)
    assert dec["accept"] is False
    assert "per_symbol_cap" in dec["reason"]


def test_max_concurrent(walker):
    for sym in ["BTC/USDT", "ETH/USDT", "SOL/USDT"]:
        walker.record_open_position({"symbol": sym, "entry_price": 1000})
    sig = {"symbol": "ADA/USDT", "strategy": "vsa_climax_test", "vol_z": 1.0,
           "entry_price": 1, "sl_price": 0.95}
    dec = walker.evaluate_signal(sig)
    assert dec["accept"] is False
    assert "max_concurrent" in dec["reason"]


def test_monthly_dd_breach(walker):
    walker.record_trade_outcome({
        "symbol": "BTC/USDT", "close_ts": datetime.now(timezone.utc).isoformat(),
        "pnl_usdt": -30, "r_multiple": -1.5, "side": "long", "strategy": "vsa_climax_test",
    })
    halts = walker.check_halts()
    assert halts["halted"] is True


def test_3_loss_halt(walker):
    now = datetime.now(timezone.utc)
    for i in range(3):
        walker.record_trade_outcome({
            "symbol": f"SYM{i}/USDT",
            "close_ts": (now + timedelta(minutes=i * 5)).isoformat(),
            "pnl_usdt": -5, "r_multiple": -1.0, "side": "long", "strategy": "vsa_climax_test",
        })
    halts = walker.check_halts()
    assert halts["halted"] is True


def test_state_save_load(tmp_state):
    walker = P1cWalker()
    walker.record_trade_outcome({
        "symbol": "BTC/USDT", "close_ts": datetime.now(timezone.utc).isoformat(),
        "pnl_usdt": 50, "r_multiple": 2.0, "side": "long", "strategy": "vsa_climax_test",
    })
    equity_after = walker.state_summary()["equity"]
    walker2 = P1cWalker()
    assert walker2.state_summary()["equity"] == equity_after


def test_equity_additive_pct(walker):
    initial = walker.state_summary()["equity"]
    walker.record_trade_outcome({
        "symbol": "BTC/USDT", "close_ts": datetime.now(timezone.utc).isoformat(),
        "pnl_usdt": 100, "r_multiple": 4.0, "side": "long", "strategy": "vsa_climax_test",
    })
    assert walker.state_summary()["equity"] == initial + 100


def test_config_load_from_yaml(tmp_state):
    cfg = P1cConfig.from_yaml(Path("configs/risk_phoenix_scalp_5m_p1c.yaml"))
    assert cfg.walker_mode == "additive_pct"
    assert cfg.monthly_loss_pct == 0.025
    assert cfg.n_losses == 3
    assert cfg.halt_hours == 12
    assert cfg.rolling_window_days == 14
    assert cfg.rolling_threshold_pct == -0.03
    assert cfg.be_protect_enabled is True
    assert cfg.be_protect_trigger_R == 0.5
    assert "engulfing_continuation" in cfg.drop_strategies
    assert cfg.max_concurrent_positions == 3
    assert cfg.per_symbol_cap == 1
    assert cfg.initial_capital == 1000.0
