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


# ── Faz 5.3 tests — BE-protect + close_position ────────────────────────────────

def test_be_protect_long_trigger(walker):
    walker.record_open_position({
        "symbol": "BTC/USDT", "side": "long",
        "entry_price": 50000, "sl_price": 48500, "tp_price": 51800,
        "strategy": "vsa_climax_test", "risk_usdt": 5.0,
    })
    # peak_R = 0.5 @ entry + 0.5 × sl_dist = 50000 + 750 = 50750
    triggered = walker.check_be_protect({"BTC/USDT": 50750})
    assert len(triggered) == 1
    assert triggered[0]["new_sl"] == 50000  # SL → entry
    assert triggered[0]["peak_R"] == 0.5
    # State'de be_protected: True
    assert walker._state["open_positions"]["BTC/USDT"]["be_protected"] is True


def test_be_protect_short_trigger(walker):
    walker.record_open_position({
        "symbol": "ETH/USDT", "side": "short",
        "entry_price": 3000, "sl_price": 3060, "tp_price": 2928,
        "strategy": "vsa_climax_test", "risk_usdt": 5.0,
    })
    # peak_R = 0.5 @ entry - 0.5 × sl_dist = 3000 - 30 = 2970
    triggered = walker.check_be_protect({"ETH/USDT": 2970})
    assert len(triggered) == 1
    assert triggered[0]["new_sl"] == 3000


def test_be_protect_no_trigger_below_threshold(walker):
    walker.record_open_position({
        "symbol": "BTC/USDT", "side": "long",
        "entry_price": 50000, "sl_price": 48500, "risk_usdt": 5.0,
    })
    # peak_R = 0.4 @ 50600 — eşik altında
    triggered = walker.check_be_protect({"BTC/USDT": 50600})
    assert len(triggered) == 0
    assert walker._state["open_positions"]["BTC/USDT"]["be_protected"] is False


def test_close_position_tp_hit_long(walker):
    walker.record_open_position({
        "symbol": "SOL/USDT", "side": "long",
        "entry_price": 100, "sl_price": 95, "tp_price": 106,
        "strategy": "vsa_climax_test", "risk_usdt": 5.0,
    })
    outcome = walker.close_position("SOL/USDT", close_price=106, reason="tp_hit")
    assert outcome is not None
    assert outcome["r_multiple"] == 1.2
    assert outcome["pnl_usdt"] == 6.0
    # Walker equity güncellendi
    assert walker.state_summary()["equity"] == 1006.0


def test_close_position_be_hit_no_loss(walker):
    walker.record_open_position({
        "symbol": "BTC/USDT", "side": "long",
        "entry_price": 50000, "sl_price": 48500, "risk_usdt": 5.0,
    })
    # BE trigger
    walker.check_be_protect({"BTC/USDT": 50750})
    # BE hit (entry'e geri dönüş)
    outcome = walker.close_position("BTC/USDT", close_price=50000, reason="be_hit")
    assert outcome["pnl_usdt"] == 0.0  # No loss
    assert walker.state_summary()["equity"] == 1000.0  # No change


def test_close_position_sl_hit_loss(walker):
    walker.record_open_position({
        "symbol": "BTC/USDT", "side": "long",
        "entry_price": 50000, "sl_price": 48500, "risk_usdt": 5.0,
    })
    outcome = walker.close_position("BTC/USDT", close_price=48500, reason="sl_hit")
    assert outcome["r_multiple"] == -1.0
    assert outcome["pnl_usdt"] == -5.0
    assert walker.state_summary()["equity"] == 995.0


def test_original_sl_dist_preserved_after_be(walker):
    walker.record_open_position({
        "symbol": "BTC/USDT", "side": "long",
        "entry_price": 50000, "sl_price": 48500, "risk_usdt": 5.0,
    })
    pos = walker._state["open_positions"]["BTC/USDT"]
    assert pos["original_sl_dist"] == 1500
    # BE trigger sonrası original_sl_dist değişmemeli
    walker.check_be_protect({"BTC/USDT": 50750})
    pos = walker._state["open_positions"]["BTC/USDT"]
    assert pos["original_sl_dist"] == 1500
    assert pos["sl_price"] == 50000  # ama sl_price değişti


def test_be_protect_disabled_no_op(tmp_state):
    walker = P1cWalker()
    walker.config.be_protect_enabled = False
    walker.record_open_position({
        "symbol": "BTC/USDT", "side": "long",
        "entry_price": 50000, "sl_price": 48500, "risk_usdt": 5.0,
    })
    triggered = walker.check_be_protect({"BTC/USDT": 50750})
    assert len(triggered) == 0
