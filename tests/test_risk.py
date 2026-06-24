"""Risk testleri — sizing, breaker, korelasyon."""
from __future__ import annotations

from datetime import datetime, timezone

import numpy as np
import pandas as pd
import pytest

from price_action.contracts import Position, Signal
from price_action.risk.breaker import DDBreaker
from price_action.risk.gates import (
    concentration_gate,
    correlation_gate,
    leverage_gate,
    liquidity_gate,
)
from price_action.risk.sizing import (
    AccountState,
    RiskOfficer,
    atr_normalized_size,
    fixed_fractional,
    kelly_capped,
)


# =====================================================================
# fixtures
# =====================================================================

@pytest.fixture
def risk_config() -> dict:
    return {
        "position_sizing": {
            "method": "fixed_fractional",
            "risk_per_trade": 0.01,
            "kelly_cap": 0.25,
            "min_quantity_usdt": 20,
        },
        "stop_loss": {"method": "atr", "atr_period": 14, "atr_multiplier": 2.0},
        "take_profit": {
            "method": "r_multiple",
            "primary_R": 2.0,
            "partial_close_at_R": 1.0,
        },
        "leverage": {
            "enabled": True,
            "max_leverage_per_symbol": 3,
            "max_portfolio_notional_x_equity": 4,
            "margin_safety_ratio": 0.5,
        },
        "drawdown_breakers": {
            "daily_loss_pct": 0.05,
            "weekly_loss_pct": 0.10,
            "monthly_loss_pct": 0.15,
            "consecutive_losses": 6,
        },
        "correlation_gate": {
            "enabled": True,
            "max_pairwise_corr": 0.7,
            "reduction_factor": 0.5,
            "hard_block_at": 0.9,
        },
        "concentration_limits": {
            "max_open_positions": 8,
            "max_per_category_pct": 0.40,
            "max_per_symbol_pct": 0.20,
        },
        "liquidity_gate": {
            "max_order_to_minute_volume": 0.01,
            "min_book_depth_usdt": 100_000,
        },
        "execution": {"order_type_default": "post_only_limit"},
    }


@pytest.fixture
def make_signal():
    """1D crypto için realistik SL: %8 mesafe (≈ 4 ATR @ %2 ATR).

    Notional hesabı: risk %1 × 10k = 100 USDT; SL %8 → notional 1250 USDT
    (= equity'nin %12.5'i, max_per_symbol_pct %20'nin altında).
    """
    def _make(symbol: str = "BTC/USDT", direction: str = "long", score: float = 2.0) -> Signal:
        return Signal(
            ts=datetime(2024, 6, 1, tzinfo=timezone.utc),
            venue="binance",
            symbol=symbol,
            timeframe="1d",
            direction=direction,  # type: ignore[arg-type]
            pattern_id="bullish_pin_bar",
            confluence_score=score,
            sl_price=92.0,  # %8 SL — 1D realistik
            tp_price=116.0,  # 2R TP
            suggested_size_atr=4.0,
            metadata={"atr14": 2.0},
        )
    return _make


# =====================================================================
# Sizing primitives
# =====================================================================

def test_fixed_fractional_basic():
    notional = fixed_fractional(equity=10_000, risk_pct=0.01, sl_distance_pct=0.02)
    # 100 risk dolar / %2 SL = 5000 notional
    assert notional == pytest.approx(5000)


def test_fixed_fractional_zero_inputs():
    assert fixed_fractional(0, 0.01, 0.02) == 0.0
    assert fixed_fractional(10_000, 0, 0.02) == 0.0
    assert fixed_fractional(10_000, 0.01, 0) == 0.0


def test_kelly_capped_positive_edge():
    f = kelly_capped(win_rate=0.6, avg_win=2.0, avg_loss=1.0, cap=0.25)
    # Kelly = 0.6 - 0.4/2 = 0.4 → capped 0.25
    assert f == pytest.approx(0.25)


def test_kelly_capped_no_edge():
    assert kelly_capped(0.4, 1.0, 1.0, cap=0.25) == 0.0


def test_atr_normalized_size():
    qty = atr_normalized_size(atr=2.0, equity=10_000, risk_pct=0.01, atr_multiplier_for_sl=2.0)
    # risk = 100, sl_dist = 4 -> qty = 25
    assert qty == pytest.approx(25)


# =====================================================================
# Breaker
# =====================================================================

def test_breaker_triggers_on_daily_loss(tmp_path, risk_config):
    state_path = tmp_path / "br.json"
    breaker = DDBreaker(risk_config["drawdown_breakers"], state_path=state_path)
    # SEC26.B-4: daily_pnl artık realized_pnl_today'den okunur (equity delta yerine).
    # Anchor 10k, equity 9.4k, realized_pnl_today=-600 → -%6 → daily breaker tetik
    acct = AccountState(equity_usdt=10_000, free_margin_usdt=10_000)
    breaker.update(acct)
    acct2 = AccountState(
        equity_usdt=9_400,
        free_margin_usdt=9_400,
        realized_pnl_today=-600.0,  # SEC26.B-4: realized PnL kaynağı
    )
    snap = breaker.update(acct2)
    assert snap["daily"] is True


def test_breaker_consecutive_losses(tmp_path, risk_config):
    state_path = tmp_path / "br.json"
    breaker = DDBreaker(risk_config["drawdown_breakers"], state_path=state_path)
    acct = AccountState(equity_usdt=10_000, free_margin_usdt=10_000, consecutive_losses=6)
    snap = breaker.update(acct)
    assert snap["consecutive"] is True


# =====================================================================
# Gates
# =====================================================================

def test_correlation_gate_hard_block():
    df = pd.DataFrame(
        {
            "BTC/USDT": np.linspace(0.001, 0.05, 60),
            "ETH/USDT": np.linspace(0.001, 0.05, 60),  # Mükemmel pozitif korelasyon
        }
    )
    pos = Position(
        venue="binance",
        symbol="ETH/USDT",
        side="long",
        quantity=1.0,
        entry_price=100,
        current_price=101,
        unrealized_pnl_usdt=0.0,
        realized_pnl_usdt=0.0,
        opened_at=datetime.now(timezone.utc),
        strategy_id="test",
        last_updated=datetime.now(timezone.utc),
    )
    allow, factor = correlation_gate(
        symbol="BTC/USDT",
        open_positions=[pos],
        returns_df=df,
        max_corr=0.7,
        hard_block_at=0.9,
        reduction_factor=0.5,
    )
    # Mükemmel korelasyon → hard block
    assert allow is False
    assert factor == 0.0


def test_correlation_gate_reduction_band():
    rng = np.random.default_rng(7)
    base = rng.normal(0, 0.01, 60)
    df = pd.DataFrame(
        {
            "BTC/USDT": base,
            "ETH/USDT": 0.75 * base + rng.normal(0, 0.005, 60),  # ~0.7-0.85 corr
        }
    )
    pos = Position(
        venue="binance",
        symbol="ETH/USDT",
        side="long",
        quantity=1,
        entry_price=100,
        current_price=101,
        unrealized_pnl_usdt=0,
        realized_pnl_usdt=0,
        opened_at=datetime.now(timezone.utc),
        strategy_id="test",
        last_updated=datetime.now(timezone.utc),
    )
    allow, factor = correlation_gate(
        symbol="BTC/USDT",
        open_positions=[pos],
        returns_df=df,
        max_corr=0.7,
        hard_block_at=0.95,
        reduction_factor=0.5,
    )
    # Band içinde → izin verilir ama factor düşürülür
    assert allow is True
    # Factor ya 0.5 (band) ya 1.0 (band altı)
    assert factor in (0.5, 1.0)


def test_concentration_gate_per_symbol_cap():
    pos = Position(
        venue="binance",
        symbol="BTC/USDT",
        side="long",
        quantity=10,
        entry_price=100,
        current_price=100,
        unrealized_pnl_usdt=0,
        realized_pnl_usdt=0,
        opened_at=datetime.now(timezone.utc),
        strategy_id="t",
        last_updated=datetime.now(timezone.utc),
    )
    ok, reason = concentration_gate(
        symbol="BTC/USDT",
        new_notional=2_000,
        equity=10_000,
        open_positions=[pos],
        max_per_symbol_pct=0.20,
        max_per_category_pct=0.40,
    )
    # Mevcut 1000 + 2000 = 3000 / 10000 = %30 > %20 cap
    assert ok is False
    assert "per_symbol_pct" in reason


def test_leverage_gate_block():
    ok, _, _ = leverage_gate(
        new_notional=20_000,
        existing_notional=30_000,
        equity=10_000,
        max_portfolio_x=4.0,
    )
    # (20+30)/10 = 5 > 4
    assert ok is False


def test_liquidity_gate_pass_when_no_data():
    ok, _ = liquidity_gate(
        order_notional_usdt=1000,
        minute_volume_usdt=None,
        book_depth_usdt=None,
    )
    assert ok is True


def test_liquidity_gate_block_on_volume_ratio():
    ok, reason = liquidity_gate(
        order_notional_usdt=10_000,
        minute_volume_usdt=500_000,
        book_depth_usdt=200_000,
        max_order_to_minute_volume=0.01,
    )
    # 10k / 500k = 0.02 > 0.01
    assert ok is False
    assert "ratio" in reason


# =====================================================================
# RiskOfficer end-to-end
# =====================================================================

def test_risk_officer_accepts_basic_signal(risk_config, make_signal, tmp_path):
    breaker = DDBreaker(risk_config["drawdown_breakers"], state_path=tmp_path / "br.json")
    ro = RiskOfficer(risk_config, breaker=breaker)
    sig = make_signal()
    acct = AccountState(equity_usdt=10_000, free_margin_usdt=10_000)
    out = ro.evaluate(sig, acct, market_price=100.0, atr=2.0)
    assert hasattr(out, "quantity")
    assert out.quantity > 0  # type: ignore[union-attr]
    # Risk %1 → SL 2 → notional ~ 5000
    assert out.notional_usdt > 100  # type: ignore[union-attr]


def test_risk_officer_rejects_when_breaker_active(risk_config, make_signal, tmp_path):
    from datetime import datetime as _dt, timezone as _tz
    breaker = DDBreaker(risk_config["drawdown_breakers"], state_path=tmp_path / "br.json")
    ro = RiskOfficer(risk_config, breaker=breaker)
    sig = make_signal()
    # SEC26.B-4: daily_pnl realized_pnl_today'den. -%5 daily_loss_pct için
    # realized_pnl_today >= 0.05 * daily_anchor_equity gerekli.
    today = _dt.now(_tz.utc).date().isoformat()
    breaker.state.last_reset_daily = today
    breaker.state.last_reset_weekly = today
    breaker.state.last_reset_monthly = today
    breaker.state.daily_anchor_equity = 11_000  # equity 10k → realized -1000 → -%9 ≥ %5
    breaker.state.weekly_anchor_equity = 10_000
    breaker.state.monthly_anchor_equity = 10_000
    breaker._save()
    acct = AccountState(
        equity_usdt=10_000,
        free_margin_usdt=10_000,
        realized_pnl_today=-1_000.0,  # SEC26.B-4: realized kayıp
    )
    out = ro.evaluate(sig, acct, market_price=100.0, atr=2.0)
    assert not hasattr(out, "quantity")


def test_risk_officer_rejects_max_open_positions(risk_config, make_signal, tmp_path):
    breaker = DDBreaker(risk_config["drawdown_breakers"], state_path=tmp_path / "br.json")
    ro = RiskOfficer(risk_config, breaker=breaker)
    open_pos = [
        Position(
            venue="binance",
            symbol=f"X{i}/USDT",
            side="long",
            quantity=1,
            entry_price=100,
            current_price=100,
            unrealized_pnl_usdt=0,
            realized_pnl_usdt=0,
            opened_at=datetime.now(timezone.utc),
            strategy_id="t",
            last_updated=datetime.now(timezone.utc),
        )
        for i in range(8)
    ]
    acct = AccountState(
        equity_usdt=100_000, free_margin_usdt=100_000, open_positions=open_pos
    )
    sig = make_signal()
    out = ro.evaluate(sig, acct, market_price=100.0, atr=2.0)
    assert not hasattr(out, "quantity")
