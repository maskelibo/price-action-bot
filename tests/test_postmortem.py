"""Post-mortem sınıflandırma — kural bazlı."""
from __future__ import annotations

from datetime import datetime

import pytest

from price_action.analytics.postmortem import classify_loss, classify_loss_detailed
from price_action.contracts import TradeRecord


def _trade(**kwargs) -> TradeRecord:
    base = dict(
        trade_id="T1",
        venue="binance",
        symbol="BTCUSDT",
        side="long",
        entry_ts=datetime(2024, 1, 1),
        exit_ts=datetime(2024, 1, 2),
        entry_price=100.0,
        exit_price=99.0,
        quantity=1.0,
        realized_pnl_usdt=-1.0,
        realized_r_multiple=-0.5,
        fees_usdt=0.5,
        slippage_bps=5.0,
        strategy_id="classic_pa",
        pattern_id="bullish_pin_bar",
        confluence_score=2.0,
        initial_sl=98.0,
        initial_tp=104.0,
        mae_pct=0.005,
        mfe_pct=0.002,
    )
    base.update(kwargs)
    return TradeRecord(**base)


def test_data_glitch_classification():
    t = _trade(slippage_bps=120.0)
    assert classify_loss(t) == "data_glitch"


def test_regime_change_classification():
    t = _trade()
    out = classify_loss(t, {"regime_at_entry": "bull", "regime_at_exit": "bear"})
    assert out == "regime_change"


def test_wrong_size_classification():
    t = _trade(realized_r_multiple=-2.5)
    assert classify_loss(t) == "wrong_size"


def test_wrong_pattern_classification():
    t = _trade(confluence_score=1.0, mfe_pct=0.001, realized_r_multiple=-0.8)
    assert classify_loss(t) == "wrong_pattern"


def test_wrong_timing_classification():
    t = _trade(confluence_score=2.5, mfe_pct=0.02, realized_r_multiple=-0.4)
    assert classify_loss(t) == "wrong_timing"


def test_unlucky_default():
    t = _trade(confluence_score=2.5, mfe_pct=0.003, realized_r_multiple=-0.5)
    assert classify_loss(t) == "unlucky"


def test_detailed_returns_rationale_and_confidence():
    t = _trade(slippage_bps=200.0)
    res = classify_loss_detailed(t)
    assert res.classification == "data_glitch"
    assert "slippage" in res.rationale
    assert res.confidence == "high"


@pytest.mark.parametrize(
    "kwargs,expected",
    [
        ({"slippage_bps": 80.0}, "data_glitch"),
        ({"realized_r_multiple": -3.0}, "wrong_size"),
        ({"confluence_score": 1.2, "mfe_pct": 0.001}, "wrong_pattern"),
    ],
)
def test_classification_table(kwargs, expected):
    t = _trade(**kwargs)
    assert classify_loss(t) == expected
