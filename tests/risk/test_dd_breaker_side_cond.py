"""SEC26.B-1: Side-conditional monthly DD breaker tests.

Backtest engine `lab.py` side-bazlı monthly DD halt uyguluyor; live `DDBreaker`'a
port edildi. Bu testler:
  1. Long breaker -%15 eşikte tetikleniyor.
  2. Short breaker -%5 eşikte tetikleniyor.
  3. Long bloke iken short trade'e izin (yön-bağımsızlık).
  4. Short bloke iken long trade'e izin.
  5. Ay değişiminde state reset.
  6. Backward-compat: side-cond key yoksa combined-only davranış korunur.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from price_action.risk.breaker import DDBreaker
from price_action.risk.sizing import AccountState


# =====================================================================
# Fixtures
# =====================================================================

@pytest.fixture
def side_cond_config() -> dict:
    """v1.5.1 PURE side-cond preset (configs/risk_balanced.yaml parity)."""
    return {
        "daily_loss_pct": 0.99,            # disabled — side-cond only test için
        "weekly_loss_pct": 0.99,
        "monthly_loss_pct": 0.99,
        "monthly_loss_pct_long": 0.15,
        "monthly_loss_pct_short": 0.05,
        "monthly_halt_days": 21,
        "daily_halt_days": 1,
        "weekly_halt_days": 7,
        "consecutive_losses": 99,          # disabled
    }


@pytest.fixture
def combined_only_config() -> dict:
    """Eski v0.9.7 preset — side-cond key YOK."""
    return {
        "daily_loss_pct": 0.05,
        "weekly_loss_pct": 0.10,
        "monthly_loss_pct": 0.15,
        "consecutive_losses": 6,
        # NOT: monthly_loss_pct_long/short YOK
    }


# Sabit "şimdi" (ay ortası) — month-reset edge-case'lerinden kaçınmak için.
T0 = datetime(2026, 5, 15, 12, 0, tzinfo=timezone.utc)


def _acct(equity: float) -> AccountState:
    return AccountState(equity_usdt=equity, free_margin_usdt=equity)


# =====================================================================
# 1. Long breaker tetiklemesi (-%15)
# =====================================================================

def test_long_breaker_triggers_at_15pct(tmp_path, side_cond_config):
    breaker = DDBreaker(side_cond_config, state_path=tmp_path / "br.json")
    # Anchor başlat (ay başı)
    breaker.update(_acct(10_000), now=T0)
    # Long pnl -$1600 → -%16 (eşik %15) → bloke
    snap = breaker.record_realized_pnl(
        _acct(8_400), side="long", pnl_realized=-1_600.0, now=T0,
    )
    # snapshot_dict only combined → side-cond ayrı kontrol
    assert breaker.state.triggered_monthly_long is True
    assert breaker.state.triggered_monthly_short is False
    # check_side: long REJECT, short ALLOW
    assert breaker.check_side("long", T0) is False
    assert breaker.check_side("short", T0) is True


def test_long_breaker_below_threshold_allows(tmp_path, side_cond_config):
    breaker = DDBreaker(side_cond_config, state_path=tmp_path / "br.json")
    breaker.update(_acct(10_000), now=T0)
    # Long pnl -$1400 → -%14 (eşik %15) → izin
    breaker.record_realized_pnl(
        _acct(8_600), side="long", pnl_realized=-1_400.0, now=T0,
    )
    assert breaker.state.triggered_monthly_long is False
    assert breaker.check_side("long", T0) is True


# =====================================================================
# 2. Short breaker tetiklemesi (-%5)
# =====================================================================

def test_short_breaker_triggers_at_5pct(tmp_path, side_cond_config):
    breaker = DDBreaker(side_cond_config, state_path=tmp_path / "br.json")
    breaker.update(_acct(10_000), now=T0)
    # Short pnl -$600 → -%6 (eşik %5) → bloke
    breaker.record_realized_pnl(
        _acct(9_400), side="short", pnl_realized=-600.0, now=T0,
    )
    assert breaker.state.triggered_monthly_short is True
    assert breaker.state.triggered_monthly_long is False
    assert breaker.check_side("short", T0) is False
    assert breaker.check_side("long", T0) is True


def test_short_breaker_below_threshold_allows(tmp_path, side_cond_config):
    breaker = DDBreaker(side_cond_config, state_path=tmp_path / "br.json")
    breaker.update(_acct(10_000), now=T0)
    # Short pnl -$400 → -%4 (eşik %5) → izin
    breaker.record_realized_pnl(
        _acct(9_600), side="short", pnl_realized=-400.0, now=T0,
    )
    assert breaker.state.triggered_monthly_short is False
    assert breaker.check_side("short", T0) is True


# =====================================================================
# 3. Long bloke iken short trade'e izin
# =====================================================================

def test_long_block_doesnt_affect_short(tmp_path, side_cond_config):
    breaker = DDBreaker(side_cond_config, state_path=tmp_path / "br.json")
    breaker.update(_acct(10_000), now=T0)
    # Long bloke
    breaker.record_realized_pnl(
        _acct(8_400), side="long", pnl_realized=-1_600.0, now=T0,
    )
    assert breaker.check_side("long", T0) is False
    # Short hala açık
    assert breaker.check_side("short", T0) is True
    # Short kazançlı bir trade kaydedilse bile long bloke kalır
    breaker.record_realized_pnl(
        _acct(8_700), side="short", pnl_realized=+300.0, now=T0,
    )
    assert breaker.check_side("long", T0) is False
    assert breaker.check_side("short", T0) is True


# =====================================================================
# 4. Short bloke iken long trade'e izin
# =====================================================================

def test_short_block_doesnt_affect_long(tmp_path, side_cond_config):
    breaker = DDBreaker(side_cond_config, state_path=tmp_path / "br.json")
    breaker.update(_acct(10_000), now=T0)
    # Short bloke
    breaker.record_realized_pnl(
        _acct(9_400), side="short", pnl_realized=-600.0, now=T0,
    )
    assert breaker.check_side("short", T0) is False
    # Long hala açık
    assert breaker.check_side("long", T0) is True


# =====================================================================
# 5. Aylık anchor reset (yeni ay)
# =====================================================================

def test_monthly_anchor_reset_on_new_month(tmp_path, side_cond_config):
    breaker = DDBreaker(side_cond_config, state_path=tmp_path / "br.json")
    # Mayıs: long bloke
    breaker.update(_acct(10_000), now=T0)
    breaker.record_realized_pnl(
        _acct(8_400), side="long", pnl_realized=-1_600.0, now=T0,
    )
    assert breaker.state.triggered_monthly_long is True
    assert breaker.state.monthly_pnl_long == pytest.approx(-1_600.0)

    # Haziran 1'i → anchor reset, side pnl reset, trigger flag reset
    t_jun = datetime(2026, 6, 1, 0, 0, tzinfo=timezone.utc)
    breaker.update(_acct(8_400), now=t_jun)
    assert breaker.state.monthly_pnl_long == pytest.approx(0.0)
    assert breaker.state.monthly_pnl_short == pytest.approx(0.0)
    assert breaker.state.triggered_monthly_long is False
    assert breaker.state.triggered_monthly_short is False
    # NOT: blocked_long_until ayda devam ediyor (halt süresi geçene kadar).
    # Eğer halt 21 gün ise May 15 + 21 = Jun 5. Jun 1 hala bloke.
    # Bu lab.py ile parity: blocked_until ay reset'inde silinmez.


# =====================================================================
# 6. Backward-compat: side-cond key yoksa combined-only davranış
# =====================================================================

def test_combined_breaker_still_works(tmp_path, combined_only_config):
    breaker = DDBreaker(combined_only_config, state_path=tmp_path / "br.json")
    # Anchor 10k
    breaker.update(_acct(10_000), now=T0)
    # SEC26.B-4: daily_pnl artık realized_pnl_today'den okunur.
    # Equity 9.4k + realized=-600 → daily -%6 → bloke
    acct_loss = AccountState(
        equity_usdt=9_400, free_margin_usdt=9_400,
        realized_pnl_today=-600.0,
    )
    breaker.update(acct_loss, now=T0)
    assert breaker.state.triggered_daily is True
    # check_side: yön-bağımsız reddetmeli (combined breaker aktif)
    assert breaker.check_side("long", T0) is False
    assert breaker.check_side("short", T0) is False
    # Side-cond pasif (config'de yok)
    assert breaker.monthly_pct_long is None
    assert breaker.monthly_pct_short is None


def test_combined_only_no_side_triggers(tmp_path, combined_only_config):
    """Side-cond keys yoksa, side pnl güncellemeleri triggered_monthly_long/short
    asla True'ya çekmemeli."""
    breaker = DDBreaker(combined_only_config, state_path=tmp_path / "br.json")
    breaker.update(_acct(10_000), now=T0)
    # Büyük long loss kaydet — combined trigger olmasın
    breaker.record_realized_pnl(
        _acct(9_900), side="long", pnl_realized=-100.0, now=T0,
    )
    # monthly_pnl_long güncellendi mi (tracking aktif)
    assert breaker.state.monthly_pnl_long == pytest.approx(-100.0)
    # AMA trigger pasif (side eşiği None)
    assert breaker.state.triggered_monthly_long is False


# =====================================================================
# 7. Halt süresi bitiminde otomatik çözülme
# =====================================================================

def test_long_block_expires_after_halt_days(tmp_path, side_cond_config):
    breaker = DDBreaker(side_cond_config, state_path=tmp_path / "br.json")
    breaker.update(_acct(10_000), now=T0)
    breaker.record_realized_pnl(
        _acct(8_400), side="long", pnl_realized=-1_600.0, now=T0,
    )
    # Halt aktif iken
    assert breaker.check_side("long", T0) is False
    # 21 gün + 1 dakika sonra — halt süresi dolmuş ama ay aynı (Mayıs 15 → Haz 5)
    # Haziran 5 — ay değişti, anchor reset ve flag reset olur. NOT: pnl_long'u
    # ay başında reset etmek için update gerekli.
    t_later = T0 + timedelta(days=21, minutes=1)  # 2026-06-05 12:01
    # update çağrısı yapmadan check_side: blocked_until parse edilir, ts > until → izin
    assert breaker.check_side("long", t_later) is True


# =====================================================================
# 8. RiskOfficer entegrasyon — side-cond bloke iken signal reject
# =====================================================================

def test_risk_officer_rejects_side_cond_breaker(tmp_path, side_cond_config):
    from price_action.contracts import Signal
    from price_action.risk.sizing import RiskOfficer

    risk_cfg = {
        "position_sizing": {
            "method": "fixed_fractional",
            "risk_per_trade": 0.01,
            "min_quantity_usdt": 20,
        },
        "stop_loss": {"method": "atr", "atr_period": 14, "atr_multiplier": 2.0},
        "take_profit": {"method": "r_multiple", "primary_R": 2.0, "partial_close_at_R": 1.0},
        "leverage": {
            "enabled": True,
            "max_leverage_per_symbol": 3,
            "max_portfolio_notional_x_equity": 4,
            "margin_safety_ratio": 0.5,
        },
        "drawdown_breakers": side_cond_config,
        "correlation_gate": {"enabled": False},
        "concentration_limits": {
            "max_open_positions": 8,
            "max_per_category_pct": 0.40,
            "max_per_symbol_pct": 0.20,
        },
        "liquidity_gate": {"max_order_to_minute_volume": 0.01, "min_book_depth_usdt": 100_000},
        "execution": {"order_type_default": "post_only_limit"},
    }
    breaker = DDBreaker(side_cond_config, state_path=tmp_path / "br.json")
    ro = RiskOfficer(risk_cfg, breaker=breaker)

    # Long bloke
    breaker.update(_acct(10_000), now=T0)
    breaker.record_realized_pnl(
        _acct(8_400), side="long", pnl_realized=-1_600.0, now=T0,
    )

    sig_long = Signal(
        ts=T0,
        venue="binance",
        symbol="BTC/USDT",
        timeframe="1d",
        direction="long",
        pattern_id="bullish_pin_bar",
        confluence_score=2.0,
        sl_price=92.0,
        tp_price=116.0,
        suggested_size_atr=4.0,
        metadata={"atr14": 2.0},
    )
    sig_short = Signal(
        ts=T0,
        venue="binance",
        symbol="BTC/USDT",
        timeframe="1d",
        direction="short",
        pattern_id="bearish_pin_bar",
        confluence_score=2.0,
        sl_price=108.0,
        tp_price=84.0,
        suggested_size_atr=4.0,
        metadata={"atr14": 2.0},
    )
    acct = AccountState(equity_usdt=8_400, free_margin_usdt=8_400)

    # Long → REJECT (side-cond)
    result_long = ro.evaluate(
        sig_long, acct, market_price=100.0,
        minute_volume_usdt=1e8, order_book_depth_usdt=1e6,
    )
    from price_action.contracts import Reject
    assert isinstance(result_long, Reject)
    assert result_long.reason == "dd_breaker_side_cond"
    # Short → ACCEPT (side-cond izin verir)
    result_short = ro.evaluate(
        sig_short, acct, market_price=100.0,
        minute_volume_usdt=1e8, order_book_depth_usdt=1e6,
    )
    # Short kabul edilmeli (notional / sizing OK)
    from price_action.contracts import RiskedOrder
    assert isinstance(result_short, RiskedOrder), (
        f"Short bekleniyor ama: {result_short}"
    )
