"""Live RiskOfficer stop-distance-target wiring and safety contracts."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from price_action.contracts import Signal
from price_action.risk.breaker import DDBreaker
from price_action.risk.sizing import AccountState, RiskOfficer
from price_action.risk.vol_target import from_live_risk_yaml


def _config(vol_target: dict | None = None) -> dict:
    config = {
        "position_sizing": {
            "method": "fixed_fractional",
            "risk_per_trade": 0.005,
            "min_quantity_usdt": 5,
            "max_notional_pct_equity": 0.0,
        },
        "stop_loss": {"method": "atr", "atr_multiplier": 1.5},
        "take_profit": {"primary_R": 1.5, "partial_close_at_R": 1.0},
        "leverage": {
            "max_leverage_per_symbol": 3,
            "max_portfolio_notional_x_equity": 4,
            "margin_safety_ratio": 0.5,
        },
        "drawdown_breakers": {
            "daily_loss_pct": 0.99,
            "weekly_loss_pct": 0.99,
            "monthly_loss_pct": 0.99,
            "consecutive_losses": 99,
        },
        "correlation_gate": {"enabled": False},
        "concentration_limits": {
            "max_open_positions": 8,
            "max_per_symbol_pct": 1.0,
            "max_per_category_pct": 1.0,
        },
        "liquidity_gate": {
            "max_order_to_minute_volume": 1.0,
            "min_book_depth_usdt": 0,
        },
    }
    if vol_target is not None:
        config["vol_target"] = vol_target
    return config


def _signal(sl_pct: float) -> Signal:
    price = 100.0
    return Signal(
        ts=datetime(2026, 7, 10, 12, 0, tzinfo=UTC),
        venue="binance",
        symbol="BTC/USDT",
        timeframe="15m",
        direction="long",
        pattern_id="brooks_failed_breakout",
        confluence_score=0.6,
        sl_price=price * (1.0 - sl_pct),
        tp_price=price * (1.0 + sl_pct * 1.5),
        suggested_size_atr=1.0,
        metadata={"entry_price": price},
    )


def _evaluate(tmp_path, config: dict, sl_pct: float):
    breaker = DDBreaker(config["drawdown_breakers"], state_path=tmp_path / "breaker.json")
    officer = RiskOfficer(config, breaker=breaker)
    account = AccountState(
        equity_usdt=10_000.0,
        free_margin_usdt=10_000.0,
        open_positions=[],
        realized_pnl_today=0.0,
    )
    return officer.evaluate(_signal(sl_pct), account, market_price=100.0)


def test_disabled_is_quantity_and_risk_budget_identical(tmp_path) -> None:
    implicit = _evaluate(tmp_path / "implicit", _config(), 0.025)
    explicit = _evaluate(
        tmp_path / "explicit",
        _config({"enabled": False, "target_atr_pct": 0.01}),
        0.025,
    )

    assert implicit.quantity == explicit.quantity
    assert implicit.notional_usdt == explicit.notional_usdt
    assert implicit.risk_budget_consumed == explicit.risk_budget_consumed == 0.005


@pytest.mark.parametrize(
    ("sl_pct", "expected_factor"),
    [(0.025, 0.4), (0.05, 0.2)],
)
def test_enabled_scales_before_caps(tmp_path, sl_pct: float, expected_factor: float) -> None:
    baseline = _evaluate(tmp_path / "off", _config(), sl_pct)
    scaled = _evaluate(
        tmp_path / "on",
        _config(
            {
                "enabled": True,
                "input_metric": "entry_stop_distance_pct",
                "target_atr_pct": 0.01,
                "min_factor": 0.2,
                "max_factor": 1.0,
            }
        ),
        sl_pct,
    )

    assert scaled.quantity == pytest.approx(baseline.quantity * expected_factor)
    assert scaled.notional_usdt == pytest.approx(baseline.notional_usdt * expected_factor)
    assert scaled.risk_budget_consumed == pytest.approx(0.005 * expected_factor)


def test_invalid_enabled_config_rejects_new_entry(tmp_path) -> None:
    result = _evaluate(
        tmp_path,
        _config(
            {
                "enabled": True,
                "input_metric": "entry_stop_distance_pct",
                "target_atr_pct": "not-a-number",
                "min_factor": 0.2,
                "max_factor": 1.0,
            }
        ),
        0.025,
    )

    assert result.reason == "invalid_vol_target_config"


def test_live_parser_rejects_inverted_clamps() -> None:
    with pytest.raises(ValueError, match="min_factor"):
        from_live_risk_yaml(
            {
                "vol_target": {
                    "enabled": True,
                    "input_metric": "entry_stop_distance_pct",
                    "target_atr_pct": 0.01,
                    "min_factor": 1.5,
                    "max_factor": 0.2,
                }
            }
        )


def test_live_parser_rejects_unwired_volatility_metric() -> None:
    with pytest.raises(ValueError, match="entry_stop_distance_pct"):
        from_live_risk_yaml(
            {
                "vol_target": {
                    "enabled": True,
                    "input_metric": "atr_pct_at_entry",
                    "target_atr_pct": 0.01,
                    "min_factor": 0.2,
                    "max_factor": 1.0,
                }
            }
        )


def test_live_parser_rejects_enabled_legacy_block_without_explicit_metric() -> None:
    with pytest.raises(ValueError, match="requires explicit input_metric"):
        from_live_risk_yaml(
            {
                "vol_target": {
                    "enabled": True,
                    "target_atr_pct": 0.01,
                    "min_factor": 0.2,
                    "max_factor": 1.0,
                }
            }
        )
