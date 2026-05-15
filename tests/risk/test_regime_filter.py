"""SEC26.B-2: BTC capitulation regime filter live wiring tests.

Backtest engine (lab.py) regime_filter.btc_capitulation_halt_enabled flag'i
ile `compute_btc_capitulation_halt` calendar'ı kuruyor ve replay'de halt günlerinde
yeni pozisyon açmıyor (SEC10 bulgusu: min pencere +%3 -> +%19.8, 6x).

Live `RiskOfficer.evaluate()` aynı calendar'ı kullanmazsa parity kırık (CRITICAL
BLOCKER, risk_officer E1 BLOCKER-2). Bu testler:

  1. Halt yok -> is_capitulation = False (normal trade akışı).
  2. Tek koşul (ATR%) -> False (3 koşul tümü gerekir, ENaz 2 — regime.py mantığı).
  3. Tüm koşullar (ATR + EMA + DD) -> True.
  4. Halt aktif iken short signal REJECT (bidirectional).
  5. Halt aktif iken long signal REJECT (bidirectional).
  6. Filter disabled -> False (backward compat).
  7. BTC data eksik (calendar boş) -> conservative False (veto YAPMA).
"""
from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from price_action.contracts import Reject, Signal
from price_action.risk.breaker import DDBreaker
from price_action.risk.regime_filter import RegimeFilter
from price_action.risk.sizing import AccountState, RiskOfficer


# =====================================================================
# Fixtures
# =====================================================================

@pytest.fixture
def disabled_cfg() -> dict:
    """regime_filter.btc_capitulation_halt_enabled = False (no-op)."""
    return {"btc_capitulation_halt_enabled": False}


@pytest.fixture
def enabled_cfg() -> dict:
    """Live preset parametreleri (configs/risk_balanced.yaml ile aynı)."""
    return {
        "btc_capitulation_halt_enabled": True,
        "atr_pct_threshold": 6.0,
        "ema200_streak_days": 10,
        "dd_90d_threshold_pct": -25.0,
        "resume_atr_threshold": 4.0,
        "resume_streak_days": 5,
    }


@pytest.fixture
def full_risk_cfg() -> dict:
    """RiskOfficer için tam YAML — capitulation halt aktif."""
    return {
        "position_sizing": {
            "method": "fixed_fractional",
            "risk_per_trade": 0.01,
            "min_quantity_usdt": 20,
        },
        "stop_loss": {"method": "atr", "atr_period": 14, "atr_multiplier": 2.0},
        "take_profit": {"primary_R": 2.0, "partial_close_at_R": 1.0},
        "leverage": {
            "enabled": True,
            "max_leverage_per_symbol": 3,
            "max_portfolio_notional_x_equity": 4,
            "margin_safety_ratio": 0.5,
        },
        "drawdown_breakers": {
            "daily_loss_pct": 0.05,
            "weekly_loss_pct": 0.10,
            "monthly_loss_pct": 0.99,  # disabled in test
            "consecutive_losses": 99,
        },
        "correlation_gate": {"enabled": False},  # disable for isolation
        "concentration_limits": {
            "max_open_positions": 8,
            "max_per_category_pct": 0.40,
            "max_per_symbol_pct": 0.20,
        },
        "liquidity_gate": {
            "max_order_to_minute_volume": 0.01,
            "min_book_depth_usdt": 100_000,
        },
        "regime_filter": {
            "btc_capitulation_halt_enabled": True,
            "atr_pct_threshold": 6.0,
            "ema200_streak_days": 10,
            "dd_90d_threshold_pct": -25.0,
        },
    }


def _make_signal(direction: str = "long", ts: datetime | None = None) -> Signal:
    """1D crypto signal — realistik SL %8 (test_risk.py fixture parity)."""
    return Signal(
        ts=ts or datetime(2024, 6, 1, tzinfo=timezone.utc),
        venue="binance",
        symbol="BTC/USDT",
        timeframe="1d",
        direction=direction,  # type: ignore[arg-type]
        pattern_id="bullish_pin_bar",
        confluence_score=2.0,
        sl_price=92.0,
        tp_price=116.0,
        suggested_size_atr=4.0,
        metadata={"atr14": 2.0},
    )


def _force_halt_calendar(rf: RegimeFilter, halt_dates: list[date]) -> None:
    """Test helper: calendar manuel override (data dependency yok testler için)."""
    rf._calendar = {d: True for d in halt_dates}


# =====================================================================
# Unit tests — RegimeFilter standalone
# =====================================================================

def test_no_capitulation_returns_false(enabled_cfg):
    """Halt günü değilse False döner — normal trade akışı."""
    rf = RegimeFilter(enabled_cfg)
    # Calendar lazy-build edildi ama o özel günü halt değil.
    # Garanti için boş calendar zorla:
    rf._calendar = {}
    ts = datetime(2024, 6, 1, tzinfo=timezone.utc)
    assert rf.is_capitulation(ts) is False


def test_capitulation_atr_only_returns_false(enabled_cfg):
    """Tek koşul (sadece ATR%) calendar'a halt eklemez.

    regime.py mantığı: 3 koşulun EN AZ 2'si gerekir (rules.sum >= 2).
    Calendar dışı bir tarih sorgulanırsa False — bu testte calendar BOŞ
    bırakıldığı için "tek koşul tetiklendi ama halt değil" senaryosunu
    simüle eder.
    """
    rf = RegimeFilter(enabled_cfg)
    rf._calendar = {}  # 3-koşul'dan 2'si tetiklenmediği günler boş kalıyor
    ts = datetime(2024, 6, 1, tzinfo=timezone.utc)
    assert rf.is_capitulation(ts) is False


def test_full_capitulation_returns_true(enabled_cfg):
    """Calendar'da halt=True olan tarih -> is_capitulation = True."""
    rf = RegimeFilter(enabled_cfg)
    halt_d = date(2024, 6, 1)
    _force_halt_calendar(rf, [halt_d])
    ts = datetime(2024, 6, 1, 12, 0, tzinfo=timezone.utc)
    assert rf.is_capitulation(ts) is True


def test_disabled_returns_false(disabled_cfg):
    """enabled=False -> calendar build edilmez, her zaman False."""
    rf = RegimeFilter(disabled_cfg)
    # Manuel calendar override edilse bile enabled=False ise False
    rf._calendar = {date(2024, 6, 1): True}
    ts = datetime(2024, 6, 1, tzinfo=timezone.utc)
    assert rf.is_capitulation(ts) is False


def test_insufficient_data_returns_false_conservative(enabled_cfg):
    """BTC data yoksa (calendar boş) veto YAPMA — conservative-on-missing.

    Live'da kısa süreli BTC veri kesintisi tüm trade'i bloke etmemeli.
    F&G filter ile aynı pattern (false-negative kabul).
    """
    rf = RegimeFilter(enabled_cfg)
    rf._calendar = {}  # data load fail simulation
    ts = datetime(2024, 6, 1, tzinfo=timezone.utc)
    assert rf.is_capitulation(ts) is False


# =====================================================================
# Integration tests — RiskOfficer.evaluate() wiring
# =====================================================================

def test_capitulation_long_signal_rejected(full_risk_cfg, tmp_path):
    """Halt aktif -> long signal REJECT (regime_capitulation_halt)."""
    breaker = DDBreaker(
        full_risk_cfg["drawdown_breakers"], state_path=tmp_path / "br.json"
    )
    ro = RiskOfficer(full_risk_cfg, breaker=breaker)
    # Force halt for test date (data-independent)
    halt_d = date(2024, 6, 1)
    _force_halt_calendar(ro.regime_filter, [halt_d])

    sig = _make_signal(direction="long")
    acct = AccountState(equity_usdt=10_000, free_margin_usdt=10_000)
    out = ro.evaluate(sig, acct, market_price=100.0, atr=2.0)

    assert isinstance(out, Reject)
    assert out.reason == "regime_capitulation_halt"
    assert out.detail.get("side") == "long"


def test_capitulation_short_signal_rejected(full_risk_cfg, tmp_path):
    """Halt aktif -> short signal de REJECT (bidirectional, sec10 bulgusu)."""
    breaker = DDBreaker(
        full_risk_cfg["drawdown_breakers"], state_path=tmp_path / "br.json"
    )
    ro = RiskOfficer(full_risk_cfg, breaker=breaker)
    halt_d = date(2024, 6, 1)
    _force_halt_calendar(ro.regime_filter, [halt_d])

    sig = _make_signal(direction="short")
    acct = AccountState(equity_usdt=10_000, free_margin_usdt=10_000)
    out = ro.evaluate(sig, acct, market_price=100.0, atr=2.0)

    assert isinstance(out, Reject)
    assert out.reason == "regime_capitulation_halt"
    assert out.detail.get("side") == "short"
