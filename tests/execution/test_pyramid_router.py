"""PyramidRouter testleri — SEC54.3 (5 senaryo).

Senaryo 1: SL hit → leg-2 PENDING/SUBMITTED iptal (orphan yok)
Senaryo 2: Leg-1 TP1 hit değil ama 1.0R tetiklendi → leg-2 normal submit
Senaryo 3: Leg-2 fill happy path (fiyat ≥ 1.5R trigger, post-only fill)
Senaryo 4: Leg-2 partial fill (exchange fill_qty < requested)
Senaryo 5: Leg-2 30s post-only timeout → market fallback (slip ≤ 25bps)

Gerçek borsa/DB çağrısı yok. Tüm exchange + idempotency + slippage mock.
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch, call

import pytest

from price_action.execution.pyramid_router import (
    PyramidLeg,
    PyramidPosition,
    PyramidRouter,
    _make_client_order_id,
    build_position_from_signal,
)


# ─────────────────────────────────────────────────────────────────────────────
# Test fixture builder'ları
# ─────────────────────────────────────────────────────────────────────────────

ENTRY_PRICE = 65_000.0
SL_PRICE = 63_700.0   # 1R = 1300 USDT
INITIAL_R = abs(ENTRY_PRICE - SL_PRICE)   # 1300.0

# Trigger fiyatları (LONG):
# Leg-2: entry + 1.0 × R = 65_000 + 1300 = 66_300
# Leg-3: entry + 1.5 × R = 65_000 + 1950 = 66_950
TRIG_LEG2 = ENTRY_PRICE + 1.0 * INITIAL_R  # 66_300
TRIG_LEG3 = ENTRY_PRICE + 1.5 * INITIAL_R  # 66_950


def _make_position(legs=None) -> PyramidPosition:
    """Test için temel PyramidPosition (LONG, BTC/USDT)."""
    entry_leg = PyramidLeg(
        leg_num=1,
        leg_state="FILLED",
        leg_qty=0.01,
        leg_price=ENTRY_PRICE,
        client_order_id="PA_test123456789_L1",
        fill_price=ENTRY_PRICE,
        filled_at=datetime.now(timezone.utc),
    )
    return PyramidPosition(
        parent_position_id="test123456789_base",
        symbol="BTC/USDT",
        side="LONG",
        entry_price=ENTRY_PRICE,
        sl_price=SL_PRICE,
        initial_R=INITIAL_R,
        legs=legs if legs is not None else [entry_leg],
        pyramid_triggers=[1.0, 1.5],
        pyramid_sizes=[0.50, 0.30],
    )


def _make_router(
    exchange=None,
    idem=None,
    slippage=None,
    post_only_enabled=False,  # testlerde market order (hızlı, senkron)
) -> PyramidRouter:
    if exchange is None:
        exchange = MagicMock()
    if idem is None:
        idem = MagicMock()
        idem.is_seen.return_value = False  # default: hiç görülmedi
        idem.mark_submitted.return_value = None
        idem.mark_filled.return_value = None
        idem.mark_rejected.return_value = None
    if slippage is None:
        slippage = MagicMock()
        slippage.record_fill.return_value = 0.0
    return PyramidRouter(
        exchange=exchange,
        idempotency_store=idem,
        slippage_tracker=slippage,
        post_only_enabled=post_only_enabled,
        fallback_seconds=1,   # testlerde kısa timeout
        slippage_limit_bps=25.0,
        mode="paper",
    )


def _mk_market_order(fill_avg=66_300.0, fill_qty=0.005, status="closed") -> dict:
    return {
        "id": "EX_ORDER_123",
        "status": status,
        "average": fill_avg,
        "filled": fill_qty,
        "price": fill_avg,
    }


TS = datetime(2026, 5, 18, 12, 0, 0, tzinfo=timezone.utc)


# ─────────────────────────────────────────────────────────────────────────────
# Yardımcı unit testler
# ─────────────────────────────────────────────────────────────────────────────

def test_make_client_order_id_format():
    """client_order_id format PA_{fp[:12]}_L{n} doğrulama."""
    coid = _make_client_order_id("abcdef1234567890", 2)
    assert coid == "PA_abcdef123456_L2"
    assert len(coid) <= 36  # Binance max


def test_make_client_order_id_truncated_to_36():
    """Çok uzun fp → 36 char truncate."""
    long_fp = "x" * 50
    coid = _make_client_order_id(long_fp, 99)
    assert len(coid) <= 36


def test_trigger_price_long():
    """LONG pozisyon leg-2 trigger fiyatı: entry + 1.0R."""
    pos = _make_position()
    trig = pos.trigger_price_for_leg(2)
    assert trig == pytest.approx(TRIG_LEG2)


def test_trigger_price_long_leg3():
    """LONG pozisyon leg-3 trigger fiyatı: entry + 1.5R."""
    pos = _make_position()
    trig = pos.trigger_price_for_leg(3)
    assert trig == pytest.approx(TRIG_LEG3)


def test_sl_hit_long():
    """LONG SL hit: current <= sl_price."""
    pos = _make_position()
    assert pos.sl_hit(SL_PRICE) is True          # exact hit
    assert pos.sl_hit(SL_PRICE - 1) is True      # below
    assert pos.sl_hit(SL_PRICE + 1) is False      # above sl → not hit


def test_sl_hit_short():
    """SHORT SL hit: current >= sl_price."""
    pos = _make_position()
    pos.side = "SHORT"
    pos.sl_price = ENTRY_PRICE + 1300  # short SL above entry
    current_sl = pos.sl_price
    assert pos.sl_hit(current_sl) is True
    assert pos.sl_hit(current_sl + 1) is True
    assert pos.sl_hit(current_sl - 1) is False


def test_leg_qty_for_num():
    """Leg boyutu: entry_qty × pyramid_sizes[idx]."""
    pos = _make_position()
    # leg-2: 0.01 × 0.50 = 0.005
    assert pos.leg_qty_for_num(2) == pytest.approx(0.005)
    # leg-3: 0.01 × 0.30 = 0.003
    assert pos.leg_qty_for_num(3) == pytest.approx(0.003)


def test_build_position_from_signal():
    """build_position_from_signal: leg-1 FILLED olarak eklenmeli."""
    sig = {"symbol": "ETH/USDT", "side": "long"}
    pos = build_position_from_signal(
        signal_dict=sig,
        fill_price=3000.0,
        fill_qty=0.1,
        sl_price=2850.0,
        parent_position_id="abcdef123456",
        pyramid_triggers=[1.0, 1.5],
        pyramid_sizes=[0.5, 0.3],
    )
    assert pos.symbol == "ETH/USDT"
    assert pos.side == "LONG"
    assert pos.initial_R == pytest.approx(150.0)
    assert len(pos.legs) == 1
    assert pos.legs[0].leg_num == 1
    assert pos.legs[0].leg_state == "FILLED"
    assert pos.legs[0].fill_price == pytest.approx(3000.0)


# ─────────────────────────────────────────────────────────────────────────────
# Senaryo 1: SL hit → leg-2 PENDING iptal
# ─────────────────────────────────────────────────────────────────────────────

def test_scenario1_sl_hit_cancels_pending_legs():
    """SL fiyatı altına düşünce PENDING leg-2 iptal edilmeli (orphan yok)."""
    ex = MagicMock()
    idem = MagicMock()
    idem.is_seen.return_value = False

    pos = _make_position()
    # Leg-2 PENDING olarak ekle (submit edilmedi ama oluşturuldu)
    pending_leg = PyramidLeg(
        leg_num=2,
        leg_state="PENDING",
        leg_qty=0.005,
        leg_price=TRIG_LEG2,
        client_order_id="PA_test123456789_L2",
    )
    pos.legs.append(pending_leg)

    router = _make_router(exchange=ex, idem=idem)

    # SL fiyatının altı
    current_price = SL_PRICE - 100.0

    router.on_position_check(pos, current_price, TS)

    # Leg-2 CANCELED olmalı
    assert pending_leg.leg_state == "CANCELED"
    # PENDING'de exchange_order_id yok → exchange.cancel_order CALL EDİLMEMELİ
    # (exchange_order_id = None olduğu için coid üzerinden denenmeli)
    # Borsadan hata gelebilir; PENDING durumda exchange_order_id zaten None.
    # cancel_order çağrısı en fazla 1 (coid ile).


def test_scenario1_sl_hit_cancels_submitted_leg():
    """SUBMITTED leg-2 (exchange_order_id var) SL'de exchange.cancel_order çağrılmalı."""
    ex = MagicMock()
    ex.cancel_order.return_value = {"status": "canceled"}
    idem = MagicMock()
    idem.is_seen.return_value = False

    pos = _make_position()
    submitted_leg = PyramidLeg(
        leg_num=2,
        leg_state="SUBMITTED",
        leg_qty=0.005,
        leg_price=TRIG_LEG2,
        client_order_id="PA_test123456789_L2",
        exchange_order_id="EX_SUB_456",
    )
    pos.legs.append(submitted_leg)

    router = _make_router(exchange=ex, idem=idem)
    current_price = SL_PRICE - 50.0  # SL altı

    router.on_position_check(pos, current_price, TS)

    # exchange.cancel_order exchange_order_id ile çağrıldı
    ex.cancel_order.assert_called_once_with("EX_SUB_456", "BTC/USDT")
    assert submitted_leg.leg_state == "CANCELED"


def test_scenario1_filled_leg_not_canceled():
    """FILLED leg SL'de dokunulmaz (pozisyon zaten kapandı/kapanıyor)."""
    ex = MagicMock()
    pos = _make_position()
    filled_leg = PyramidLeg(
        leg_num=2,
        leg_state="FILLED",
        leg_qty=0.005,
        leg_price=TRIG_LEG2,
        client_order_id="PA_test123456789_L2",
        exchange_order_id="EX_FILLED_789",
    )
    pos.legs.append(filled_leg)

    router = _make_router(exchange=ex)
    router.on_position_check(pos, SL_PRICE - 100.0, TS)

    # FILLED leg dokunulmaz
    assert filled_leg.leg_state == "FILLED"
    ex.cancel_order.assert_not_called()


# ─────────────────────────────────────────────────────────────────────────────
# Senaryo 2: 1.0R tetiklendi → leg-2 normal submit
# ─────────────────────────────────────────────────────────────────────────────

def test_scenario2_trigger_reached_submits_leg2():
    """1.0R fiyatına ulaşıldı → leg-2 submit edilmeli."""
    ex = MagicMock()
    ex.create_market_order.return_value = _mk_market_order(
        fill_avg=TRIG_LEG2, fill_qty=0.005, status="closed"
    )

    idem = MagicMock()
    idem.is_seen.return_value = False

    slip = MagicMock()
    slip.record_fill.return_value = 0.0

    pos = _make_position()
    router = _make_router(exchange=ex, idem=idem, slippage=slip, post_only_enabled=False)

    # Fiyat tam trigger'da
    current_price = TRIG_LEG2

    router.on_position_check(pos, current_price, TS)

    # create_market_order çağrıldı
    ex.create_market_order.assert_called_once()
    call_kwargs = ex.create_market_order.call_args
    assert call_kwargs.kwargs["symbol"] == "BTC/USDT"
    assert call_kwargs.kwargs["side"] == "buy"
    assert call_kwargs.kwargs["amount"] == pytest.approx(0.005)

    # Leg-2 pozisyona eklendi ve FILLED
    leg2 = pos.leg_for_num(2)
    assert leg2 is not None
    assert leg2.leg_state == "FILLED"

    # Idempotency kaydedildi
    idem.mark_submitted.assert_called_once()
    idem.mark_filled.assert_called_once()


def test_scenario2_below_trigger_no_submit():
    """Fiyat trigger altında → leg-2 submit edilmemeli."""
    ex = MagicMock()
    pos = _make_position()
    router = _make_router(exchange=ex)

    current_price = TRIG_LEG2 - 100.0  # trigger'a ulaşmadı

    router.on_position_check(pos, current_price, TS)

    ex.create_market_order.assert_not_called()
    assert pos.leg_for_num(2) is None


# ─────────────────────────────────────────────────────────────────────────────
# Senaryo 3: Leg-3 happy path (≥ 1.5R, post-only fill)
# ─────────────────────────────────────────────────────────────────────────────

def test_scenario3_leg3_post_only_fill():
    """1.5R tetiklendi, post-only fill → leg-3 FILLED, slippage kaydı var."""
    # post_only_router patch ederek post-only fill simüle et
    mock_order = {
        "id": "PO_LEG3_999",
        "status": "closed",
        "average": TRIG_LEG3,
        "filled": 0.003,
    }

    ex = MagicMock()
    idem = MagicMock()
    idem.is_seen.return_value = False
    slip = MagicMock()
    slip.record_fill.return_value = 0.0

    pos = _make_position()
    # Leg-2 zaten fill olmuş (önceki tick'te)
    leg2 = PyramidLeg(
        leg_num=2,
        leg_state="FILLED",
        leg_qty=0.005,
        leg_price=TRIG_LEG2,
        client_order_id="PA_test123456789_L2",
        fill_price=TRIG_LEG2,
    )
    pos.legs.append(leg2)

    router = PyramidRouter(
        exchange=ex,
        idempotency_store=idem,
        slippage_tracker=slip,
        post_only_enabled=True,
        fallback_seconds=1,
        slippage_limit_bps=25.0,
        mode="paper",
    )

    # post_only_router patch
    with patch(
        "price_action.execution.pyramid_router.place_post_only_with_fallback",
        return_value=(mock_order, "post_only_filled"),
    ) as mock_po:
        current_price = TRIG_LEG3  # 1.5R tam tetik
        router.on_position_check(pos, current_price, TS)

    # post_only çağrıldı
    mock_po.assert_called_once()
    call_kw = mock_po.call_args
    assert call_kw.kwargs["symbol"] == "BTC/USDT"
    assert call_kw.kwargs["side"] == "buy"
    assert call_kw.kwargs["qty"] == pytest.approx(0.003)  # 0.01 × 0.30

    # Leg-3 FILLED
    leg3 = pos.leg_for_num(3)
    assert leg3 is not None
    assert leg3.leg_state == "FILLED"

    # Slippage kaydedildi
    slip.record_fill.assert_called_once()
    slip_kwargs = slip.record_fill.call_args.kwargs
    assert slip_kwargs["symbol"] == "BTC/USDT"
    assert "pyramid_leg3" in slip_kwargs["strategy"]


# ─────────────────────────────────────────────────────────────────────────────
# Senaryo 4: Partial fill (fill_qty < requested — DOGE/ADA düşük likidite)
# ─────────────────────────────────────────────────────────────────────────────

def test_scenario4_partial_fill():
    """Exchange sadece kısmi fill döndürdü — leg state SUBMITTED (open), slippage yok."""
    ex = MagicMock()
    # Partial: qty=0.005 ama filled=0.002, status=open
    ex.create_market_order.return_value = {
        "id": "EX_PARTIAL_111",
        "status": "open",          # henüz tam dolmadı
        "average": TRIG_LEG2,
        "filled": 0.002,           # kısmi
        "price": TRIG_LEG2,
    }

    idem = MagicMock()
    idem.is_seen.return_value = False
    slip = MagicMock()

    pos = _make_position()
    router = _make_router(exchange=ex, idem=idem, slippage=slip, post_only_enabled=False)

    current_price = TRIG_LEG2
    router.on_position_check(pos, current_price, TS)

    # Leg oluşturuldu
    leg2 = pos.leg_for_num(2)
    assert leg2 is not None
    # status='open' → SUBMITTED (dolmadı; FILLED değil)
    assert leg2.leg_state == "SUBMITTED"
    # Slippage kaydedilmedi (filled değil)
    slip.record_fill.assert_not_called()

    # Idempotency submitted kaydedildi
    idem.mark_submitted.assert_called_once()
    # mark_filled çağrılmadı
    idem.mark_filled.assert_not_called()


# ─────────────────────────────────────────────────────────────────────────────
# Senaryo 5: post-only timeout → market fallback (slip ≤ 25bps)
# ─────────────────────────────────────────────────────────────────────────────

def test_scenario5_post_only_timeout_market_fallback():
    """30s post-only timeout → market fallback, slip içinde → FILLED."""
    # Market fallback fiyatı: 66300 → 66315 = ~2.3bps (25bps altı)
    market_fill_px = TRIG_LEG2 + 15.0  # ~2.3bps, limit altı

    market_order = {
        "id": "MK_FALLBACK_222",
        "status": "closed",
        "average": market_fill_px,
        "filled": 0.005,
    }

    ex = MagicMock()
    idem = MagicMock()
    idem.is_seen.return_value = False
    slip = MagicMock()
    slip.record_fill.return_value = 0.0

    pos = _make_position()
    router = PyramidRouter(
        exchange=ex,
        idempotency_store=idem,
        slippage_tracker=slip,
        post_only_enabled=True,
        fallback_seconds=1,
        slippage_limit_bps=25.0,
        mode="paper",
    )

    # place_post_only_with_fallback: timeout → market fallback → (market_order, "market_fallback")
    with patch(
        "price_action.execution.pyramid_router.place_post_only_with_fallback",
        return_value=(market_order, "market_fallback"),
    ) as mock_po:
        router.on_position_check(pos, TRIG_LEG2, TS)

    mock_po.assert_called_once()

    leg2 = pos.leg_for_num(2)
    assert leg2 is not None
    # market_fallback ama status=closed → FILLED
    assert leg2.leg_state == "FILLED"
    assert leg2.fill_price == pytest.approx(market_fill_px)

    # Slippage kaydedildi
    slip.record_fill.assert_called_once()
    # is_maker=False (market_fallback)
    slip_kw = slip.record_fill.call_args.kwargs
    assert slip_kw["is_maker"] is False


def test_scenario5_post_only_slippage_exceeded_raises():
    """Fallback slip > 25bps → SlippageExceededError raise, leg REJECTED."""
    from price_action.execution.post_only_router import SlippageExceededError

    ex = MagicMock()
    idem = MagicMock()
    idem.is_seen.return_value = False
    slip = MagicMock()

    pos = _make_position()
    router = PyramidRouter(
        exchange=ex,
        idempotency_store=idem,
        slippage_tracker=slip,
        post_only_enabled=True,
        fallback_seconds=1,
        slippage_limit_bps=25.0,
        mode="paper",
    )

    # post_only_router slip > 25bps → raise
    with patch(
        "price_action.execution.pyramid_router.place_post_only_with_fallback",
        side_effect=SlippageExceededError(40.0, 25.0, symbol="BTC/USDT"),
    ):
        with pytest.raises(SlippageExceededError) as exc_info:
            router.on_position_check(pos, TRIG_LEG2, TS)

    assert exc_info.value.slippage_bps == pytest.approx(40.0)

    leg2 = pos.leg_for_num(2)
    assert leg2 is not None
    assert leg2.leg_state == "REJECTED"
    # Idempotency rejected kaydedildi
    idem.mark_rejected.assert_called_once()


def test_scenario5_slip_exceeded_telemetry_recorded():
    """SlippageExceededError → record_fill REJECTED kaydı yapılmalı (telemetri kör kalmasın)."""
    from price_action.execution.post_only_router import SlippageExceededError

    ex = MagicMock()
    idem = MagicMock()
    idem.is_seen.return_value = False
    slip = MagicMock()

    pos = _make_position()
    router = PyramidRouter(
        exchange=ex,
        idempotency_store=idem,
        slippage_tracker=slip,
        post_only_enabled=True,
        fallback_seconds=1,
        slippage_limit_bps=25.0,
        mode="paper",
    )

    with patch(
        "price_action.execution.pyramid_router.place_post_only_with_fallback",
        side_effect=SlippageExceededError(46.0, 25.0, symbol="BTC/USDT"),
    ):
        with pytest.raises(SlippageExceededError):
            router.on_position_check(pos, TRIG_LEG2, TS)

    # Telemetri: record_fill çağrıldı
    slip.record_fill.assert_called_once()
    kw = slip.record_fill.call_args.kwargs
    # REJECTED kaydı: is_maker=False, notes'ta slip değer var
    assert kw["is_maker"] is False
    assert "REJECTED" in kw["notes"]
    assert "46.0bps" in kw["notes"]
    assert kw["order_type"] == "slip_exceeded_reverse_close"


def test_post_only_fill_is_maker_true():
    """post_only_filled method → is_maker=True ile slippage kaydedilmeli."""
    mock_order = {
        "id": "PO_MAKER_123",
        "status": "closed",
        "average": TRIG_LEG2,
        "filled": 0.005,
    }

    ex = MagicMock()
    idem = MagicMock()
    idem.is_seen.return_value = False
    slip = MagicMock()
    slip.record_fill.return_value = 0.0

    pos = _make_position()
    router = PyramidRouter(
        exchange=ex,
        idempotency_store=idem,
        slippage_tracker=slip,
        post_only_enabled=True,
        fallback_seconds=1,
        slippage_limit_bps=25.0,
        mode="paper",
    )

    with patch(
        "price_action.execution.pyramid_router.place_post_only_with_fallback",
        return_value=(mock_order, "post_only_filled"),
    ):
        router.on_position_check(pos, TRIG_LEG2, TS)

    slip.record_fill.assert_called_once()
    kw = slip.record_fill.call_args.kwargs
    assert kw["is_maker"] is True
    assert kw["order_type"] == "post_only_filled"


def test_market_fallback_is_maker_false():
    """market_fallback method → is_maker=False ile slippage kaydedilmeli."""
    market_fill_px = TRIG_LEG2 + 10.0  # ~1.5bps, limit altı
    mock_order = {
        "id": "MK_FALL_456",
        "status": "closed",
        "average": market_fill_px,
        "filled": 0.005,
    }

    ex = MagicMock()
    idem = MagicMock()
    idem.is_seen.return_value = False
    slip = MagicMock()
    slip.record_fill.return_value = 0.0

    pos = _make_position()
    router = PyramidRouter(
        exchange=ex,
        idempotency_store=idem,
        slippage_tracker=slip,
        post_only_enabled=True,
        fallback_seconds=1,
        slippage_limit_bps=25.0,
        mode="paper",
    )

    with patch(
        "price_action.execution.pyramid_router.place_post_only_with_fallback",
        return_value=(mock_order, "market_fallback"),
    ):
        router.on_position_check(pos, TRIG_LEG2, TS)

    slip.record_fill.assert_called_once()
    kw = slip.record_fill.call_args.kwargs
    assert kw["is_maker"] is False
    assert kw["order_type"] == "market_fallback"


# ─────────────────────────────────────────────────────────────────────────────
# Idempotency: restart sırasında double-submit yok
# ─────────────────────────────────────────────────────────────────────────────

def test_idempotency_no_double_submit():
    """Idempotency hit → create_market_order CALL EDİLMEMELİ."""
    ex = MagicMock()
    idem = MagicMock()
    # Zaten gönderilmiş
    idem.is_seen.return_value = True

    pos = _make_position()
    router = _make_router(exchange=ex, idem=idem, post_only_enabled=False)

    router.on_position_check(pos, TRIG_LEG2, TS)

    # Borsa çağrısı yok
    ex.create_market_order.assert_not_called()
    ex.create_order.assert_not_called()


# ─────────────────────────────────────────────────────────────────────────────
# Backward compat: pyramid router aktif değilse tek-leg flow etkilenmez
# ─────────────────────────────────────────────────────────────────────────────

def test_backward_compat_already_handled_legs_skipped():
    """Leg-2 FILLED ise tekrar submit edilmemeli (idempotent loop)."""
    ex = MagicMock()
    idem = MagicMock()
    idem.is_seen.return_value = False

    pos = _make_position()
    already_filled = PyramidLeg(
        leg_num=2,
        leg_state="FILLED",
        leg_qty=0.005,
        leg_price=TRIG_LEG2,
        client_order_id="PA_test123456789_L2",
        fill_price=TRIG_LEG2,
    )
    pos.legs.append(already_filled)

    router = _make_router(exchange=ex, idem=idem)
    # Fiyat leg-3 trigger üzerinde bile olsa leg-2 tekrar submit edilmemeli
    router.on_position_check(pos, TRIG_LEG3, TS)

    # Leg-2 dokunulmadı
    assert already_filled.leg_state == "FILLED"
    # Leg-3 submite gidebilir (ama sadece 1 order)
    # Önemli: leg-2 ikinci kez submit edilmedi
    call_count = ex.create_market_order.call_count
    # Sadece leg-3 için 0 veya 1 çağrı (post_only_enabled=False, market order)
    assert call_count <= 1


def test_trigger_not_reached_no_submit():
    """Fiyat trigger seviyesinin altında → hiç submit yok."""
    ex = MagicMock()
    pos = _make_position()
    router = _make_router(exchange=ex, post_only_enabled=False)

    # Fiyat entry ile trigger arasında
    current_price = ENTRY_PRICE + 500.0  # 65500 < 66300 trigger

    router.on_position_check(pos, current_price, TS)

    ex.create_market_order.assert_not_called()
    assert pos.leg_for_num(2) is None
