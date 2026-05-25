"""Risk officer + sizing + breaker + correlation tests."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from forex_bot.contracts import Signal
from forex_bot.risk.breaker import BreakerConfig, DDBreaker
from forex_bot.risk.correlation import CorrelationGate
from forex_bot.risk.officer import AccountState, RiskConfig, RiskOfficer
from forex_bot.risk.sizing import kelly_fraction, position_size_pip_risk


def test_position_size_pip_risk():
    lots = position_size_pip_risk(equity_usd=10_000.0, risk_pct=0.01, sl_pips=20.0, pair="EURUSD")
    assert lots > 0
    # 10000 * 0.01 / (20 * 10) = 0.5
    assert abs(lots - 0.5) < 0.01


def test_position_size_zero_sl():
    assert position_size_pip_risk(equity_usd=10_000, risk_pct=0.01, sl_pips=0, pair="EURUSD") == 0.0


def test_kelly_fraction_capped():
    f = kelly_fraction(win_rate=0.6, avg_win_r=2.0, avg_loss_r=1.0)
    assert 0.0 <= f <= 0.25


def test_breaker_daily_dd_blocks():
    b = DDBreaker(BreakerConfig(daily_loss_pct=0.05))
    blocked, reason = b.update(
        equity_usd=10_000, daily_pnl=-600, weekly_pnl=-600, monthly_pnl=-600,
        consecutive_losses=0, now=datetime(2024, 1, 1, tzinfo=timezone.utc),
    )
    assert blocked
    assert reason == "daily_dd"


def test_correlation_block():
    g = CorrelationGate(hard_block_at=0.9, max_pairwise_corr=0.7)
    # AUDUSD/NZDUSD ≈ 0.85 — should reduce
    allow, mult, reason = g.evaluate("AUDUSD", ["NZDUSD"], "long", {"NZDUSD": "long"})
    assert allow
    assert mult < 1.0


def test_risk_officer_rejects_zero_size():
    cfg = RiskConfig()
    ro = RiskOfficer(cfg)
    sig = Signal(
        pair="EURUSD", side="long", ts=datetime(2024, 1, 1, 10, 0, tzinfo=timezone.utc),
        entry_price=1.10, sl_price=1.10, tp_prices=[1.11], confluence=0.7,
        strategy="test", session="london", pattern="x", sl_pips=0.0, rr=2.0, meta={},
    )
    acct = AccountState(equity_usd=10_000, free_margin_usd=10_000, open_positions={})
    d = ro.evaluate(sig, acct, datetime(2024, 1, 1, 10, 0, tzinfo=timezone.utc))
    from forex_bot.contracts import Reject
    assert isinstance(d, Reject)


def test_risk_officer_accepts():
    cfg = RiskConfig()
    ro = RiskOfficer(cfg)
    sig = Signal(
        pair="EURUSD", side="long", ts=datetime(2024, 1, 1, 10, 0, tzinfo=timezone.utc),
        entry_price=1.10, sl_price=1.0980, tp_prices=[1.105, 1.110], confluence=0.7,
        strategy="test", session="london", pattern="x", sl_pips=20.0, rr=2.0, meta={},
    )
    acct = AccountState(equity_usd=10_000, free_margin_usd=10_000, open_positions={})
    d = ro.evaluate(sig, acct, datetime(2024, 1, 1, 10, 0, tzinfo=timezone.utc))
    from forex_bot.contracts import RiskedOrder
    assert isinstance(d, RiskedOrder)
    assert d.lots > 0
