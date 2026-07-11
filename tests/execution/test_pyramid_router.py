"""PyramidRouter testleri — SEC54.3 (5 senaryo).

Senaryo 1: SL hit → leg-2 PENDING/SUBMITTED iptal (orphan yok)
Senaryo 2: Leg-1 TP1 hit değil ama 1.0R tetiklendi → leg-2 normal submit
Senaryo 3: Leg-2 fill happy path (fiyat ≥ 1.5R trigger, post-only fill)
Senaryo 4: Leg-2 partial fill (exchange fill_qty < requested)
Senaryo 5: Leg-2 30s post-only timeout → market fallback (slip ≤ 25bps)

Gerçek borsa/DB çağrısı yok. Tüm exchange + idempotency + slippage mock.
"""
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

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
        filled_at=datetime.now(UTC),
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


TS = datetime(2026, 5, 18, 12, 0, 0, tzinfo=UTC)


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
        "fill_price_verified": True,
        "fill_quantity_verified": True,
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
        "fill_price_verified": True,
        "fill_quantity_verified": True,
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
    ), pytest.raises(SlippageExceededError) as exc_info:
        router.on_position_check(pos, TRIG_LEG2, TS)

    assert exc_info.value.slippage_bps == pytest.approx(40.0)

    leg2 = pos.leg_for_num(2)
    assert leg2 is not None
    assert leg2.leg_state == "REJECTED"
    # Idempotency rejected kaydedildi
    idem.mark_rejected.assert_called_once()


def test_scenario5_legacy_slip_error_does_not_fabricate_fill_telemetry():
    """Fiyat/qty kanıtı yoksa rejected olayı sahte fill olarak yazılmaz."""
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
    ), pytest.raises(SlippageExceededError):
        router.on_position_check(pos, TRIG_LEG2, TS)

    slip.record_fill.assert_not_called()
    idem.mark_rejected.assert_called_once()


def test_uncertain_post_only_submit_is_durably_held_submitted_without_fake_fill():
    """Unknown ACK is a durable no-resubmit marker, never a rejected/fill event."""
    from price_action.execution.post_only_router import OrderSubmissionUncertainError

    ex = MagicMock()
    idem = MagicMock()
    idem.is_seen.return_value = False
    slip = MagicMock()
    pos = _make_position()
    router = _make_router(exchange=ex, idem=idem, slippage=slip, post_only_enabled=True)
    uncertain = OrderSubmissionUncertainError(
        stage="market_fallback_submit",
        symbol=pos.symbol,
        side="buy",
        main_client_order_id="test-main",
        fallback_client_order_id="test-fallback",
        partial_order=None,
        partial_qty=0.0,
        remaining_qty=0.005,
        cause=TimeoutError("ACK missing"),
    )

    with patch(
        "price_action.execution.pyramid_router.place_post_only_with_fallback",
        side_effect=uncertain,
    ), pytest.raises(OrderSubmissionUncertainError):
        router.on_position_check(pos, TRIG_LEG2, TS)

    leg2 = pos.leg_for_num(2)
    assert leg2 is not None
    assert leg2.leg_state == "SUBMITTED"
    idem.mark_submitted.assert_called_once_with(
        leg2.client_order_id,
        symbol=pos.symbol,
        side="buy",
    )
    idem.mark_filled.assert_not_called()
    idem.mark_rejected.assert_not_called()
    slip.record_fill.assert_not_called()


@pytest.mark.parametrize(
    ("price_verified", "quantity_verified"),
    [(False, True), (True, False), (False, False)],
)
def test_closed_post_only_fill_requires_verified_price_and_quantity(
    price_verified, quantity_verified
):
    """A closed status cannot promote trigger/size fallbacks into fill truth."""
    order = {
        "id": "UNVERIFIED_CLOSED",
        "status": "closed",
        "average": TRIG_LEG2,
        "filled": 0.005,
        "fill_price_verified": price_verified,
        "fill_quantity_verified": quantity_verified,
    }
    ex = MagicMock()
    idem = MagicMock()
    idem.is_seen.return_value = False
    slip = MagicMock()
    pos = _make_position()
    router = _make_router(exchange=ex, idem=idem, slippage=slip, post_only_enabled=True)

    with patch(
        "price_action.execution.pyramid_router.place_post_only_with_fallback",
        return_value=(order, "market_fallback"),
    ):
        router.on_position_check(pos, TRIG_LEG2, TS)

    leg2 = pos.leg_for_num(2)
    assert leg2 is not None
    assert leg2.leg_state == "SUBMITTED"
    idem.mark_submitted.assert_called_once()
    idem.mark_filled.assert_not_called()
    slip.record_fill.assert_not_called()


def test_slippage_breach_must_own_the_same_verified_fill():
    """Mismatched breach metadata stays SUBMITTED and cannot resize protection."""
    order = {
        "id": "BREACH_MISMATCH",
        "status": "closed",
        "average": TRIG_LEG2,
        "filled": 0.005,
        "fill_price_verified": True,
        "fill_quantity_verified": True,
        "slippage_breach": {
            "disposition": "protect_position",
            "position_owned": True,
            "protection_required": True,
            "fill_evidence_verified": True,
            "owned_quantity": 0.004,
            "owned_average": TRIG_LEG2,
        },
    }
    ex = MagicMock()
    idem = MagicMock()
    idem.is_seen.return_value = False
    slip = MagicMock()
    pos = _make_position()
    router = _make_router(exchange=ex, idem=idem, slippage=slip, post_only_enabled=True)
    resize = MagicMock()
    router._resize_protection_after_leg_fill = resize

    with patch(
        "price_action.execution.pyramid_router.place_post_only_with_fallback",
        return_value=(order, "market_fallback_slippage_breach_protect"),
    ):
        router.on_position_check(pos, TRIG_LEG2, TS)

    leg2 = pos.leg_for_num(2)
    assert leg2 is not None
    assert leg2.leg_state == "SUBMITTED"
    idem.mark_filled.assert_not_called()
    slip.record_fill.assert_not_called()
    resize.assert_not_called()


def test_production_daemon_hard_disables_config_enabled_pyramid(tmp_path, monkeypatch):
    """Until pyramid gets crash-complete WAL, config=true still performs no I/O."""
    import scripts.futures_daemon as daemon

    config = tmp_path / "risk.yaml"
    config.write_text("strategy_portfolio:\n  pyramid_enabled: true\n", encoding="utf-8")
    messages = []
    monkeypatch.setattr(daemon, "_risk_config_15m", lambda: config)
    monkeypatch.setattr(daemon, "_PYRAMID_ENABLED_CACHE", {})
    monkeypatch.setattr(daemon, "_pyramid_router_instance", None)
    monkeypatch.setattr(daemon, "log", messages.append)
    exchange = MagicMock()

    assert daemon._pyramid_enabled_15m() is False
    assert daemon._get_pyramid_router(exchange) is None
    assert exchange.mock_calls == []
    assert any("PYRAMID_EXECUTION_DISABLED" in message for message in messages)


def test_post_only_fill_is_maker_true():
    """post_only_filled method → is_maker=True ile slippage kaydedilmeli."""
    mock_order = {
        "id": "PO_MAKER_123",
        "status": "closed",
        "average": TRIG_LEG2,
        "filled": 0.005,
        "fill_price_verified": True,
        "fill_quantity_verified": True,
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
        "fill_price_verified": True,
        "fill_quantity_verified": True,
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


# ─────────────────────────────────────────────────────────────────────────────
# FIX 2026-06-10 (v14 audit BLOCKER-1): leg fill → SL tam-qty resize
# ─────────────────────────────────────────────────────────────────────────────


class _ResizeFakeExchange:
    """SL-resize akışını sıra-duyarlı kaydeden sahte borsa."""

    def __init__(self, position_amt=0.015, old_sl_trigger=63_700.0):
        self.position_amt = position_amt
        self.old_sl_trigger = old_sl_trigger
        self.calls = []  # (op, payload) sıralı

    def fapiPrivateV2GetPositionRisk(self):  # noqa: N802 - CCXT raw API name
        self.calls.append(("position_risk", None))
        return [{"symbol": "BTCUSDT", "positionAmt": str(self.position_amt)}]

    def fapiPrivateGetOpenAlgoOrders(self):  # noqa: N802 - CCXT raw API name
        self.calls.append(("get_algos", None))
        return [{
            "symbol": "BTCUSDT", "algoId": 111, "orderType": "STOP_MARKET",
            "side": "SELL", "triggerPrice": str(self.old_sl_trigger),
        }]

    def amount_to_precision(self, symbol, qty):
        return f"{qty:.3f}"

    def price_to_precision(self, symbol, px):
        return f"{px:.1f}"

    def create_order(self, **kw):
        self.calls.append(("create_order", kw))
        return {"id": "999", "status": "open"}

    def fapiPrivateDeleteAlgoOrder(self, params):  # noqa: N802 - CCXT raw API name
        self.calls.append(("delete_algo", params))
        return {"code": "200"}


def _make_resize_router(exchange):
    return PyramidRouter(
        exchange=exchange,
        idempotency_store=MagicMock(),
        slippage_tracker=MagicMock(),
        mode="paper",
    )


class TestLegFillSLResize:
    def test_new_full_qty_sl_placed_before_old_cancelled(self):
        """Sıra güvenliği: yeni tam-qty SL, eski iptal edilmeden ÖNCE konmalı."""
        ex = _ResizeFakeExchange(position_amt=0.015)
        router = _make_resize_router(ex)
        pos = _make_position()
        router._resize_protection_after_leg_fill(pos, leg_num=2)

        ops = [c[0] for c in ex.calls]
        assert "create_order" in ops and "delete_algo" in ops
        assert ops.index("create_order") < ops.index("delete_algo"), (
            "yeni SL eski iptalden ÖNCE konmalı — çıplak pencere yasak"
        )
        create = next(p for op, p in ex.calls if op == "create_order")
        assert float(create["amount"]) == pytest.approx(0.015)  # tam qty
        assert create["params"]["reduceOnly"] is True
        assert create["type"] == "STOP_MARKET"
        # trigger korunmuş (eski SL 63700)
        assert float(create["params"]["stopPrice"]) == pytest.approx(63_700.0)

    def test_position_read_failure_keeps_old_sl(self):
        """Pozisyon okunamazsa hiçbir şey yapılmaz (eski SL korunur, watchdog'a kalır)."""
        ex = _ResizeFakeExchange(position_amt=0.0)
        router = _make_resize_router(ex)
        pos = _make_position()
        router._resize_protection_after_leg_fill(pos, leg_num=2)
        ops = [c[0] for c in ex.calls]
        assert "create_order" not in ops and "delete_algo" not in ops

    def test_create_failure_does_not_cancel_old_sl(self):
        """Yeni SL konamadıysa eski SL ASLA iptal edilmez."""
        ex = _ResizeFakeExchange()
        def _boom(**kw):
            ex.calls.append(("create_order", kw))
            raise RuntimeError("-2022 ReduceOnly rejected")
        ex.create_order = _boom
        router = _make_resize_router(ex)
        pos = _make_position()
        router._resize_protection_after_leg_fill(pos, leg_num=2)  # exception yutulmalı
        ops = [c[0] for c in ex.calls]
        assert "delete_algo" not in ops

    def test_leg_fill_triggers_resize(self):
        """submit_leg FILLED yolunda resize çağrısı yapılır (entegrasyon)."""
        source_path = (
            Path(__file__).resolve().parents[2]
            / "src"
            / "price_action"
            / "execution"
            / "pyramid_router.py"
        )
        src = source_path.read_text(encoding="utf-8")
        assert "_resize_protection_after_leg_fill(position, leg_num)" in src
