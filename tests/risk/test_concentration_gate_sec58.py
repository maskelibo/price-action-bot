"""SEC58 concentration_gate paradox regression tests.

Senaryo: 0 acik pozisyon, max_notional_pct_equity > max_per_symbol_pct.
Beklenen: signal PASS (hicbir sebep yokken reject yok).
Orj. bug: notional cap 0.30*equity, concentration_gate 0.15*equity -> REJECT.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from price_action.contracts import Signal
from price_action.risk.breaker import DDBreaker
from price_action.risk.sizing import AccountState, RiskOfficer


def _scalp_config(
    max_notional_pct: float = 0.30,
    max_per_symbol_pct: float = 0.15,
) -> dict:
    return {
        "position_sizing": {
            "method": "fixed_fractional",
            "risk_per_trade": 0.020,
            "min_quantity_usdt": 5,
            "max_notional_pct_equity": max_notional_pct,
        },
        "stop_loss": {"method": "atr", "atr_period": 14, "atr_multiplier": 1.5},
        "take_profit": {
            "method": "r_multiple",
            "primary_R": 1.2,
            "partial_close_at_R": 0.8,
        },
        "leverage": {
            "enabled": True,
            "max_leverage_per_symbol": 3,
            "max_portfolio_notional_x_equity": 3,
            "margin_safety_ratio": 0.5,
        },
        "drawdown_breakers": {
            "daily_loss_pct": 0.04,
            "weekly_loss_pct": 0.08,
            "monthly_loss_pct": 0.99,
            "consecutive_losses": 5,
        },
        "correlation_gate": {"enabled": False},
        "concentration_limits": {
            "max_open_positions": 16,
            "max_per_category_pct": 0.35,
            "max_per_symbol_pct": max_per_symbol_pct,
        },
        "liquidity_gate": {
            "max_order_to_minute_volume": 0.01,
            "min_book_depth_usdt": 0,
        },
    }


def _signal(symbol: str = "XRP/USDT", direction: str = "long") -> Signal:
    price = 0.60
    sl_pct = 0.015
    sl_price = price * (1 - sl_pct) if direction == "long" else price * (1 + sl_pct)
    tp_mult = 1.2
    tp_price = (price * (1 + sl_pct * tp_mult)
                if direction == "long" else price * (1 - sl_pct * tp_mult))
    return Signal(
        ts=datetime(2026, 5, 18, 16, 30, tzinfo=timezone.utc),
        venue="binance",
        symbol=symbol,
        timeframe="15m",
        direction=direction,
        pattern_id="brooks_failed_breakout",
        confluence_score=0.65,
        sl_price=sl_price,
        tp_price=tp_price,
        suggested_size_atr=0.009,
        metadata={"atr14": 0.009},
    )


def _empty_account(equity: float = 1000.0) -> AccountState:
    return AccountState(
        equity_usdt=equity,
        free_margin_usdt=equity,
        open_positions=[],
        realized_pnl_today=0.0,
    )


def test_sec58_paradox_zero_pos_buggy_yaml_now_passes(tmp_path):
    """SEC58 root cause: max_notional_pct=0.30 > max_per_symbol_pct=0.15.
    Pre-fix: concentration_gate REJECT at 0 positions (paradox).
    Post-fix: PASS, notional clipped to 15% of equity.
    """
    cfg = _scalp_config(max_notional_pct=0.30, max_per_symbol_pct=0.15)
    breaker = DDBreaker(cfg["drawdown_breakers"], state_path=tmp_path / "brk.json")
    ro = RiskOfficer(cfg, breaker=breaker)
    sig = _signal("XRP/USDT", "long")
    acct = _empty_account(equity=1000.0)
    result = ro.evaluate(sig, acct, market_price=0.60)
    assert hasattr(result, "quantity"), (
        f"Expected PASS but got REJECT: reason={getattr(result, 'reason', '?')}, "
        f"detail={getattr(result, 'detail', '')}"
    )
    assert result.notional_usdt <= 1000.0 * 0.15 + 0.01, (
        f"Notional {result.notional_usdt:.2f} exceeds concentration limit 150"
    )


def test_sec58_aligned_yaml_passes(tmp_path):
    """Duzeltilmis YAML: max_notional_pct=0.15 == max_per_symbol_pct=0.15."""
    cfg = _scalp_config(max_notional_pct=0.15, max_per_symbol_pct=0.15)
    breaker = DDBreaker(cfg["drawdown_breakers"], state_path=tmp_path / "brk.json")
    ro = RiskOfficer(cfg, breaker=breaker)
    sig = _signal("XRP/USDT", "long")
    acct = _empty_account(equity=1000.0)
    result = ro.evaluate(sig, acct, market_price=0.60)
    assert hasattr(result, "quantity"), (
        f"Aligned YAML still REJECT: {getattr(result, 'reason', '?')}"
    )


def test_sec58_five_signals_zero_pos_no_conc_reject(tmp_path):
    """Daemon log senaryo: 5 sinyal + 0 pos -> hicbiri concentration_gate REJECT olmamali."""
    cfg = _scalp_config(max_notional_pct=0.30, max_per_symbol_pct=0.15)
    breaker = DDBreaker(cfg["drawdown_breakers"], state_path=tmp_path / "brk.json")
    ro = RiskOfficer(cfg, breaker=breaker)
    acct = _empty_account(equity=1000.0)
    pairs = [("XRP/USDT", 0.60), ("ETH/USDT", 3200.0), ("BTC/USDT", 65000.0),
             ("SOL/USDT", 150.0), ("ADA/USDT", 0.45)]
    conc_rejects = []
    for sym, px in pairs:
        result = ro.evaluate(_signal(sym, "long"), acct, market_price=px)
        if not hasattr(result, "quantity") and getattr(result, "reason", "") == "concentration_gate":
            conc_rejects.append(sym)
    assert conc_rejects == [], (
        f"0 pozisyonla concentration_gate REJECT: {conc_rejects} -- SEC58 paradoks DEVAM"
    )


def test_sec58_full_symbol_correctly_rejects(tmp_path):
    """Sembol zaten %15 dolu -> ek pozisyon dogru sekilde reject edilmeli."""
    from price_action.contracts import Position
    cfg = _scalp_config(max_notional_pct=0.30, max_per_symbol_pct=0.15)
    breaker = DDBreaker(cfg["drawdown_breakers"], state_path=tmp_path / "brk.json")
    ro = RiskOfficer(cfg, breaker=breaker)
    equity = 1000.0
    existing_pos = [Position(
        venue="binance", symbol="XRP/USDT", side="long",
        quantity=250.0, entry_price=0.60, current_price=0.60,
        unrealized_pnl_usdt=0.0, realized_pnl_usdt=0.0,
        opened_at=datetime.now(timezone.utc),
        strategy_id="prev", last_updated=datetime.now(timezone.utc),
    )]
    acct = AccountState(equity_usdt=equity, free_margin_usdt=500.0, open_positions=existing_pos)
    result = ro.evaluate(_signal("XRP/USDT", "long"), acct, market_price=0.60)
    assert not hasattr(result, "quantity"), (
        f"Sembol dolu ama PASS geldi: {getattr(result, 'notional_usdt', '?')}"
    )


def test_sec58_tight_sl_notional_clipped_not_rejected(tmp_path):
    """Cok dar SL -> fixed_fractional cok buyuk notional -> conc-clip -> min_notional veya PASS.
    Asla concentration_gate REJECT olmamali."""
    cfg = _scalp_config(max_notional_pct=0.30, max_per_symbol_pct=0.15)
    breaker = DDBreaker(cfg["drawdown_breakers"], state_path=tmp_path / "brk.json")
    ro = RiskOfficer(cfg, breaker=breaker)
    price = 100.0
    sig = Signal(
        ts=datetime(2026, 5, 18, 16, 30, tzinfo=timezone.utc),
        venue="binance", symbol="XRP/USDT", timeframe="15m",
        direction="long", pattern_id="test", confluence_score=0.65,
        sl_price=price * 0.999, tp_price=price * 1.003,
        suggested_size_atr=0.1, metadata={},
    )
    acct = _empty_account(equity=10_000.0)
    result = ro.evaluate(sig, acct, market_price=price)
    reason = getattr(result, "reason", None)
    assert reason != "concentration_gate", (
        f"Tight SL + 0 pos -> concentration_gate REJECT hala oluyor: {reason}"
    )
    if hasattr(result, "quantity"):
        assert result.notional_usdt <= 10_000.0 * 0.15 + 0.01
