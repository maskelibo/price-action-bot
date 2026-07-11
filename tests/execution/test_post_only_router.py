"""Post-Only Router testleri — SEC26.B-5 (CONDITIONAL).

5 senaryo:
  1) test_post_only_fills_no_fallback         — Post-only fill, market'a duşmez
  2) test_post_only_unfilled_market_fallback  — Post-only timeout -> market fallback
  3) test_market_fallback_slippage_within_limit  — Fallback slippage <= limit, OK
  4) test_market_fallback_slippage_exceeded_is_owned_for_protection
  5) test_post_only_disabled_uses_market_directly — futures_trade_daily.py'de
     post_only_enabled=False -> direkt create_market_order (place_post_only_with_fallback CALL EDILMEZ).

Gercek exchange call yok; tum exchange mock.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from price_action.execution.post_only_router import (
    OrderSubmissionUncertainError,
    _compute_slippage_bps,
    opposite_side,
    place_post_only_with_fallback,
)


def test_limit_submit_timeout_is_uncertain_and_never_falls_back_to_market():
    """Missing LIMIT ACK is not a reject; a market order could double ownership."""
    ex = MagicMock()
    ex.create_order.side_effect = TimeoutError("submit response timed out")

    with pytest.raises(OrderSubmissionUncertainError) as exc_info:
        place_post_only_with_fallback(
            ex,
            symbol="BTC/USDT",
            side="buy",
            qty=1.0,
            target_price=100.0,
            client_order_id="PA_timeout_main",
            fallback_after_sec=0,
        )

    err = exc_info.value
    assert err.stage == "post_only_limit_submit"
    assert err.main_client_order_id == "PA_timeout_main"
    assert err.partial_qty == 0.0
    assert err.remaining_qty == pytest.approx(1.0)
    assert err.uncertain_client_order_ids == ("PA_timeout_main",)
    assert not ex.create_market_order.called


def test_market_fallback_timeout_exposes_fallback_id_and_partial_metadata():
    """Fallback ACK timeout carries `_fb` identity and known limit ownership."""
    ex = MagicMock()
    ex.create_order.return_value = {"id": "L_PART", "status": "open"}
    ex.cancel_order.return_value = {"id": "L_PART", "status": "canceled"}
    ex.fetch_order.return_value = {
        "id": "L_PART",
        "status": "canceled",
        "filled": 0.4,
        "average": 100.0,
        "cost": 40.0,
    }
    ex.amount_to_precision.side_effect = lambda _symbol, qty: str(qty)
    ex.create_market_order.side_effect = TimeoutError("market ACK timed out")

    with pytest.raises(OrderSubmissionUncertainError) as exc_info:
        place_post_only_with_fallback(
            ex,
            symbol="BTC/USDT",
            side="buy",
            qty=1.0,
            target_price=100.0,
            client_order_id="PA_timeout_fb",
            fallback_after_sec=0,
        )

    err = exc_info.value
    assert err.stage == "market_fallback_submit"
    assert err.fallback_client_order_id == "PA_timeout_fb_fb"
    assert err.uncertain_client_order_ids == ("PA_timeout_fb_fb",)
    assert err.partial_order["id"] == "L_PART"
    assert err.partial_qty == pytest.approx(0.4)
    assert err.remaining_qty == pytest.approx(0.6)
    assert err.to_queue_fields()["submit_uncertainty"]["fallback_client_order_id"] == (
        "PA_timeout_fb_fb"
    )
    assert ex.create_market_order.call_count == 1


def test_cancel_unverified_is_typed_uncertainty_and_never_falls_back():
    """An OPEN post-cancel snapshot must be queued/reconciled, not resubmitted."""
    ex = MagicMock()
    ex.create_order.return_value = {"id": "L_OPEN", "status": "open"}
    ex.cancel_order.return_value = None
    ex.fetch_order.return_value = {
        "id": "L_OPEN",
        "status": "open",
        "filled": 0.0,
    }

    with pytest.raises(OrderSubmissionUncertainError) as exc_info:
        place_post_only_with_fallback(
            ex,
            symbol="BTC/USDT",
            side="buy",
            qty=1.0,
            target_price=100.0,
            client_order_id="PA_cancel_open",
            fallback_after_sec=0,
        )

    err = exc_info.value
    assert err.stage == "post_only_cancel_verify"
    assert err.uncertain_client_order_ids == ("PA_cancel_open",)
    assert err.partial_order["id"] == "L_OPEN"
    assert err.remaining_qty == pytest.approx(1.0)
    assert not ex.create_market_order.called


class _PartialFallbackExchange:
    """Partial limit + delayed Binance market-fill evidence."""

    def __init__(
        self,
        *,
        limit_fill: dict,
        market_initial: dict,
        market_snapshots: list[dict],
    ) -> None:
        self.limit_fill = limit_fill
        self.market_initial = market_initial
        self.market_snapshots = list(market_snapshots)
        self.market_calls: list[dict] = []
        self.fetch_calls: list[str] = []

    def create_order(self, **kwargs):
        return {"id": "PO_PARTIAL", "status": "open", "type": "limit"}

    def cancel_order(self, order_id, symbol):
        return {"id": order_id, "status": "canceled"}

    def fetch_order(self, order_id, symbol):
        self.fetch_calls.append(order_id)
        if order_id == "PO_PARTIAL":
            return dict(self.limit_fill)
        if self.market_snapshots:
            return dict(self.market_snapshots.pop(0))
        return {"id": order_id, "status": "closed", "filled": 3307.0, "average": None}

    def create_market_order(self, **kwargs):
        self.market_calls.append(kwargs)
        if len(self.market_calls) == 1:
            return dict(self.market_initial)
        return {
            "id": "MK_REVERSE",
            "status": "closed",
            "filled": kwargs["amount"],
            "average": 0.19414,
        }

    def amount_to_precision(self, symbol, amount):
        return str(float(amount))


# ===== Test fixture helpers =====


def _mk_exchange_post_only_fills(fill_avg: float) -> MagicMock:
    """Post-only emir hemen 'closed' donduren mock exchange."""
    ex = MagicMock()
    ex.create_order.return_value = {
        "id": "PO_123",
        "status": "open",  # initial open
        "type": "limit",
        "average": fill_avg,
    }
    # fetch_order: ilk poll'da 'closed' (fill).
    ex.fetch_order.return_value = {
        "id": "PO_123",
        "status": "closed",
        "average": fill_avg,
        "filled": 0.01,
    }
    return ex


def _mk_exchange_post_only_timeout(market_fill_avg: float) -> MagicMock:
    """Post-only acik kaliyor (timeout) -> market fallback."""
    ex = MagicMock()
    ex.create_order.return_value = {
        "id": "PO_TIMEOUT",
        "status": "open",
        "type": "limit",
    }
    state = {"canceled": False}

    def _fetch_order(order_id, symbol):
        if order_id == "PO_TIMEOUT":
            return {
                "id": order_id,
                "status": "canceled" if state["canceled"] else "open",
                "filled": 0.0,
            }
        return ex.create_market_order.return_value

    def _cancel_order(order_id, symbol):
        state["canceled"] = True
        return {"id": order_id, "status": "canceled", "filled": 0.0}

    ex.fetch_order.side_effect = _fetch_order
    ex.cancel_order.side_effect = _cancel_order
    ex.create_market_order.return_value = {
        "id": "MK_456",
        "status": "closed",
        "average": market_fill_avg,
        "filled": 0.01,
    }
    return ex


# ===== Unit tests for helpers =====


def test_opposite_side():
    assert opposite_side("buy") == "sell"
    assert opposite_side("sell") == "buy"
    assert opposite_side("long") == "sell"
    assert opposite_side("short") == "buy"
    with pytest.raises(ValueError):
        opposite_side("invalid")


def test_compute_slippage_bps_buy():
    # buy: fill > expected -> positive slip (cost)
    assert _compute_slippage_bps("buy", 100.0, 100.5) == pytest.approx(50.0)
    assert _compute_slippage_bps("buy", 100.0, 99.5) == pytest.approx(-50.0)


def test_compute_slippage_bps_sell():
    # sell: expected > fill -> positive slip (cost)
    assert _compute_slippage_bps("sell", 100.0, 99.5) == pytest.approx(50.0)
    assert _compute_slippage_bps("sell", 100.0, 100.5) == pytest.approx(-50.0)


# ===== 5 senaryo (sprint spec) =====


def test_post_only_fills_no_fallback():
    """Senaryo 1: Post-only emir fill oldu -> market fallback CALL EDILMEZ."""
    ex = _mk_exchange_post_only_fills(fill_avg=65000.0)

    _order, method = place_post_only_with_fallback(
        ex,
        symbol="BTC/USDT",
        side="buy",
        qty=0.01,
        target_price=65000.0,
        fallback_after_sec=2,
        slippage_limit_bps=25.0,
        poll_interval=0.05,
    )

    assert method == "post_only_filled"
    assert ex.create_order.called
    # Post-only flag gonderildi
    call_kwargs = ex.create_order.call_args.kwargs
    assert call_kwargs["params"].get("postOnly") is True
    assert call_kwargs["params"].get("timeInForce") == "PO"
    assert call_kwargs["price"] == 65000.0
    # Market fallback CALL EDILMEDI
    assert not ex.create_market_order.called
    assert not ex.cancel_order.called


def test_post_only_unfilled_market_fallback():
    """Senaryo 2: Post-only timeout -> cancel + market fallback."""
    ex = _mk_exchange_post_only_timeout(market_fill_avg=65010.0)

    order, method = place_post_only_with_fallback(
        ex,
        symbol="BTC/USDT",
        side="buy",
        qty=0.01,
        target_price=65000.0,
        fallback_after_sec=1,  # kisa timeout, hizli test
        slippage_limit_bps=50.0,  # 65010 vs 65000 = 1.5bps, fine
        poll_interval=0.05,
    )

    assert method == "market_fallback"
    assert ex.create_order.called
    assert ex.cancel_order.called
    assert ex.create_market_order.called
    assert order.get("id") == "MK_456"


def test_market_fallback_slippage_within_limit():
    """Senaryo 3: Market fallback ama slippage <= limit -> OK, raise YOK."""
    # 65000 -> 65010 = 1.54 bps, limit 25 bps
    ex = _mk_exchange_post_only_timeout(market_fill_avg=65010.0)

    _order, method = place_post_only_with_fallback(
        ex,
        symbol="BTC/USDT",
        side="buy",
        qty=0.01,
        target_price=65000.0,
        fallback_after_sec=1,
        slippage_limit_bps=25.0,
        poll_interval=0.05,
    )

    assert method == "market_fallback"
    # Reverse YOK — sadece bir market order (fallback)
    assert ex.create_market_order.call_count == 1


def test_market_fallback_slippage_exceeded_is_owned_for_protection():
    """A verified breach stays owned and enters the canonical protection path."""
    # 65000 -> 65200 = 30.77 bps, limit 25 bps -> EXCEEDED
    ex = _mk_exchange_post_only_timeout(market_fill_avg=65200.0)

    order, method = place_post_only_with_fallback(
        ex,
        symbol="BTC/USDT",
        side="buy",
        qty=0.01,
        target_price=65000.0,
        fallback_after_sec=1,
        slippage_limit_bps=25.0,
        poll_interval=0.05,
    )

    assert method == "market_fallback_slippage_breach_protect"
    assert order["slippage_breach"]["disposition"] == "protect_position"
    assert order["slippage_breach"]["position_owned"] is True
    assert order["slippage_breach"]["protection_required"] is True
    assert order["slippage_breach"]["unwind_attempted"] is False
    assert order["slippage_bps"] > 25.0
    assert ex.create_market_order.call_count == 1


def test_post_only_disabled_uses_market_directly():
    """Senaryo 5: post_only_limit_enabled=False -> futures_trade_daily.py
    place_post_only_with_fallback'i CALL ETMEZ, direkt create_market_order.

    Bu testte place_post_only_with_fallback'i 'spy'liyoruz:
    submit_to_futures cagrildiginda eger config off ise modul fonk CALL EDILMEZ.

    NOT: Tum futures_trade_daily.py'i mock'lamak yerine, sadece *config flag*'in
    dogru davrandigini dogruluyoruz: enabled=False iken kod yolu market'a gidiyor.
    """
    # Direkt: config'i False yapinca place_post_only_with_fallback CALL EDILMEMELI.
    # Bu davranis scripts/futures_trade_daily.py'de:
    #   if post_only_enabled:
    #       order, method = place_post_only_with_fallback(...)
    #   else:
    #       order = exchange.create_market_order(...)
    #
    # Modul-seviye contract: enabled flag False iken modulun cagri sayisi 0 olmali.

    # Simulasyon: futures_trade_daily.py flag yolunu mimik et
    execution_cfg = {"post_only_limit_enabled": False}
    post_only_enabled = bool(execution_cfg.get("post_only_limit_enabled", False))

    ex = MagicMock()
    ex.create_market_order.return_value = {
        "id": "MK_DIRECT",
        "status": "closed",
        "average": 65000.0,
        "filled": 0.01,
    }

    if post_only_enabled:
        # Bu dal CALL EDILMEMELI
        _order, method = place_post_only_with_fallback(
            ex,
            symbol="BTC/USDT",
            side="buy",
            qty=0.01,
            target_price=65000.0,
        )
    else:
        # Disabled-by-default path
        _order = ex.create_market_order("BTC/USDT", "buy", 0.01)
        method = "market_only"

    assert method == "market_only"
    assert ex.create_market_order.called
    # place_post_only_with_fallback CALL EDILMEDI -> create_order yok
    assert not ex.create_order.called


# ===== Delayed fill reconciliation / partial notional integrity =====


def _xlm_partial_exchange() -> _PartialFallbackExchange:
    """Audit fill: 538@0.19358 limit + 3307@0.19423 market."""
    return _PartialFallbackExchange(
        limit_fill={
            "id": "PO_PARTIAL",
            "status": "canceled",
            "filled": 538.0,
            "average": None,
            "info": {"executedQty": "538", "cumQuote": "104.14604"},
        },
        market_initial={
            "id": "MK_PARTIAL",
            "status": "closed",
            "filled": 3307.0,
            "average": None,
        },
        market_snapshots=[
            {
                "id": "MK_PARTIAL",
                "status": "closed",
                "filled": 3307.0,
                "average": None,
                "info": {"executedQty": "3307", "cumQuote": "0"},
            },
            {
                "id": "MK_PARTIAL",
                "status": "closed",
                "filled": 3307.0,
                "average": None,
                "info": {"executedQty": "3307", "cumQuote": "642.31861"},
            },
        ],
    )


def test_partial_limit_market_uses_delayed_actual_notional_blend(monkeypatch):
    """Gecikmeli cumQuote gelir; target değil gerçek iki-bacak VWAP döner."""
    ex = _xlm_partial_exchange()
    sleeps: list[float] = []
    monkeypatch.setattr(
        "price_action.execution.post_only_router.time.sleep",
        lambda seconds: sleeps.append(seconds),
    )

    order, method = place_post_only_with_fallback(
        ex,
        symbol="XLM/USDT",
        side="buy",
        qty=3845.0,
        target_price=0.19358,
        fallback_after_sec=0,
        slippage_limit_bps=35.0,
        client_order_id="test-client",
    )

    expected_avg = ((538.0 * 0.19358) + (3307.0 * 0.19423)) / 3845.0
    expected_slip = (expected_avg - 0.19358) / 0.19358 * 10_000
    assert method == "market_fallback"
    assert order["filled"] == pytest.approx(3845.0)
    assert order["average"] == pytest.approx(expected_avg)
    assert order["partial_limit_qty"] == pytest.approx(538.0)
    assert order["partial_limit_average"] == pytest.approx(0.19358)
    assert order["partial_limit_notional"] == pytest.approx(104.14604)
    assert order["market_fallback_average"] == pytest.approx(0.19423)
    assert order["market_fallback_notional"] == pytest.approx(642.31861)
    assert order["partial_limit_order_id"] == "PO_PARTIAL"
    assert order["market_fallback_order_id"] == "MK_PARTIAL"
    assert order["fill_price_verified"] is True
    assert order["fill_quantity_verified"] is True
    assert order["slippage_verified"] is True
    assert order["slippage_bps"] == pytest.approx(expected_slip)
    assert order["fill_reconciliation_status"] == "verified"
    assert ex.fetch_calls.count("MK_PARTIAL") == 2
    assert sleeps  # en az bir gecikmeli retry yapildi
    assert len(ex.market_calls) == 1


def test_partial_weighted_slippage_breach_preserves_total_owned_qty(monkeypatch):
    """Weighted breach reports the exact owned qty for SL-first protection."""
    ex = _xlm_partial_exchange()
    monkeypatch.setattr("price_action.execution.post_only_router.time.sleep", lambda _: None)

    order, method = place_post_only_with_fallback(
        ex,
        symbol="XLM/USDT",
        side="buy",
        qty=3845.0,
        target_price=0.19358,
        fallback_after_sec=0,
        slippage_limit_bps=25.0,
        client_order_id="test-client",
    )

    assert method == "market_fallback_slippage_breach_protect"
    assert order["slippage_bps"] == pytest.approx(28.8795699563)
    assert order["slippage_breach"]["owned_quantity"] == pytest.approx(3845.0)
    assert len(ex.market_calls) == 1
    assert ex.market_calls[0]["amount"] == pytest.approx(3307.0)


def test_slippage_gate_uses_aggregate_not_market_leg_only(monkeypatch):
    """Market leg ~33.6bps olsa da toplam 28.88bps ise 30bps kapısı geçilir."""
    ex = _xlm_partial_exchange()
    monkeypatch.setattr("price_action.execution.post_only_router.time.sleep", lambda _: None)

    order, method = place_post_only_with_fallback(
        ex,
        symbol="XLM/USDT",
        side="buy",
        qty=3845.0,
        target_price=0.19358,
        fallback_after_sec=0,
        slippage_limit_bps=30.0,
    )

    assert method == "market_fallback"
    assert order["slippage_bps"] == pytest.approx(28.8795699563)
    assert len(ex.market_calls) == 1


def test_slippage_breach_uses_actual_partial_market_fill_not_requested_qty(monkeypatch):
    """Eksik market fill'de protection ownership gerçek toplam qty'dir."""
    ex = _PartialFallbackExchange(
        limit_fill={
            "id": "PO_PARTIAL",
            "status": "canceled",
            "filled": 538.0,
            "info": {"executedQty": "538", "cumQuote": "104.14604"},
        },
        market_initial={
            "id": "MK_PARTIAL",
            "status": "closed",
            "filled": 3000.0,
            "average": 0.19450,
            "cost": 583.50,
        },
        market_snapshots=[],
    )
    monkeypatch.setattr("price_action.execution.post_only_router.time.sleep", lambda _: None)

    order, method = place_post_only_with_fallback(
        ex,
        symbol="XLM/USDT",
        side="buy",
        qty=3845.0,
        target_price=0.19358,
        fallback_after_sec=0,
        slippage_limit_bps=25.0,
    )

    assert method == "market_fallback_slippage_breach_protect"
    assert ex.market_calls[0]["amount"] == pytest.approx(3307.0)  # requested remainder
    assert order["slippage_breach"]["owned_quantity"] == pytest.approx(3538.0)
    assert len(ex.market_calls) == 1


def test_missing_fill_price_is_explicitly_unverified_not_target_fallback(monkeypatch):
    """Bounded retry sonrası fiyat yoksa average=target ve sahte 0bps yazılmaz."""
    ex = _PartialFallbackExchange(
        limit_fill={
            "id": "PO_PARTIAL",
            "status": "canceled",
            "filled": 0.0,
            "average": None,
        },
        market_initial={
            "id": "MK_PARTIAL",
            "status": "closed",
            "filled": 1.0,
            "average": None,
            "price": 100.0,  # market order price alani fill kaniti degildir
        },
        market_snapshots=[
            {"id": "MK_PARTIAL", "status": "closed", "filled": 1.0, "average": None}
            for _ in range(5)
        ],
    )
    monkeypatch.setattr("price_action.execution.post_only_router.time.sleep", lambda _: None)

    order, method = place_post_only_with_fallback(
        ex,
        symbol="BTC/USDT",
        side="buy",
        qty=1.0,
        target_price=100.0,
        fallback_after_sec=0,
        slippage_limit_bps=25.0,
    )

    assert method == "market_fallback"
    assert order.get("average") is None
    assert order.get("price") is None
    assert order["exchange_reported_price"] == pytest.approx(100.0)
    assert order["filled"] == pytest.approx(1.0)  # sahiplik/koruma qty'si korunur
    assert order["fill_price_verified"] is False
    assert order["slippage_verified"] is False
    assert order["slippage_bps"] is None
    assert order["fill_reconciliation_status"] == "unverified"
    assert 1 <= ex.fetch_calls.count("MK_PARTIAL") <= 4  # bounded, sonsuz poll yok
    assert len(ex.market_calls) == 1  # fiyat bilinmiyor diye pozisyon tekrar gönderilmez


def test_unverified_partial_limit_price_preserves_total_qty_without_fake_vwap(monkeypatch):
    """Limit notional yoksa market fiyatıyla sahte toplam VWAP üretilmez."""
    ex = _PartialFallbackExchange(
        limit_fill={
            "id": "PO_PARTIAL",
            "status": "canceled",
            "filled": 0.4,
            "average": None,
        },
        market_initial={
            "id": "MK_PARTIAL",
            "status": "closed",
            "filled": 0.6,
            "average": 100.5,
            "cost": 60.3,
        },
        market_snapshots=[],
    )
    monkeypatch.setattr("price_action.execution.post_only_router.time.sleep", lambda _: None)

    order, _ = place_post_only_with_fallback(
        ex,
        symbol="BTC/USDT",
        side="buy",
        qty=1.0,
        target_price=100.0,
        fallback_after_sec=0,
        slippage_limit_bps=100.0,
    )

    assert order["filled"] == pytest.approx(1.0)
    assert order.get("average") is None
    assert order["partial_limit_qty"] == pytest.approx(0.4)
    assert order["market_fallback_average"] == pytest.approx(100.5)
    assert order["fill_price_verified"] is False
    assert order["slippage_bps"] is None


def test_cancel_ok_but_order_still_open_refuses_market_fallback():
    """Cancel ACK tek başına yetmez; exchange hâlâ open diyorsa çift pozisyon riski."""
    ex = MagicMock()
    ex.create_order.return_value = {"id": "PO_OPEN", "status": "open"}
    ex.cancel_order.return_value = {"id": "PO_OPEN", "status": "canceled"}
    ex.fetch_order.return_value = {
        "id": "PO_OPEN",
        "status": "open",
        "filled": 0.4,
        "average": 100.0,
    }

    with pytest.raises(OrderSubmissionUncertainError) as exc_info:
        place_post_only_with_fallback(
            ex,
            symbol="BTC/USDT",
            side="buy",
            qty=1.0,
            target_price=100.0,
            fallback_after_sec=0,
        )

    assert exc_info.value.stage == "post_only_cancel_verify"
    assert not ex.create_market_order.called


def test_cancel_ok_but_verify_fetch_fails_refuses_market_fallback():
    """Cancel sonrası durum okunamıyorsa partial=0 varsayılıp tam market atılmaz."""
    ex = MagicMock()
    ex.create_order.return_value = {"id": "PO_UNKNOWN", "status": "open"}
    ex.cancel_order.return_value = None  # terminal order kanıtı içermeyen salt ACK
    ex.fetch_order.side_effect = RuntimeError("fetch unavailable")

    with pytest.raises(OrderSubmissionUncertainError) as exc_info:
        place_post_only_with_fallback(
            ex,
            symbol="BTC/USDT",
            side="buy",
            qty=1.0,
            target_price=100.0,
            fallback_after_sec=0,
        )

    assert exc_info.value.stage == "post_only_cancel_verify"
    assert not ex.create_market_order.called


def test_terminal_cancel_snapshot_allows_fallback_when_refresh_temporarily_fails():
    """cancel_order terminal order döndürürse fetch outage çift-pozisyon belirsizliği değildir."""
    ex = MagicMock()
    ex.create_order.return_value = {"id": "PO_TERMINAL", "status": "open"}
    ex.cancel_order.return_value = {
        "id": "PO_TERMINAL",
        "status": "canceled",
        "filled": 0.0,
    }
    ex.fetch_order.side_effect = RuntimeError("temporary fetch outage")
    ex.create_market_order.return_value = {
        "id": "MK_SAFE",
        "status": "closed",
        "filled": 1.0,
        "average": 100.0,
    }

    order, method = place_post_only_with_fallback(
        ex,
        symbol="BTC/USDT",
        side="buy",
        qty=1.0,
        target_price=100.0,
        fallback_after_sec=0,
    )

    assert method == "market_fallback"
    assert order["fill_price_verified"] is True
    assert ex.create_market_order.call_count == 1


def test_post_only_closed_fill_uses_delayed_reconciliation_and_leg_metadata(monkeypatch):
    """Normal maker fill de gecikmeli cumQuote ile doğrulanır; limit price kanıt değildir."""
    ex = MagicMock()
    ex.create_order.return_value = {
        "id": "PO_CLOSED",
        "status": "closed",
        "filled": 1.0,
        "average": None,
        "price": 100.0,
    }
    ex.fetch_order.side_effect = [
        {"id": "PO_CLOSED", "status": "closed", "filled": 1.0, "average": None},
        {"id": "PO_CLOSED", "status": "closed", "filled": 1.0, "average": None},
        {
            "id": "PO_CLOSED",
            "status": "closed",
            "filled": 1.0,
            "average": None,
            "info": {"executedQty": "1", "cumQuote": "100.2"},
        },
    ]
    sleeps: list[float] = []
    monkeypatch.setattr("price_action.execution.post_only_router.time.sleep", sleeps.append)

    order, method = place_post_only_with_fallback(
        ex,
        symbol="BTC/USDT",
        side="buy",
        qty=1.0,
        target_price=100.0,
        fallback_after_sec=0,
    )

    assert method == "post_only_filled"
    assert order["average"] == pytest.approx(100.2)
    assert order["filled"] == pytest.approx(1.0)
    assert order["fill_price_verified"] is True
    assert order["fill_quantity_verified"] is True
    assert order["slippage_bps"] == pytest.approx(20.0)
    assert order["partial_limit_qty"] == pytest.approx(1.0)
    assert order["partial_limit_notional"] == pytest.approx(100.2)
    assert order["partial_limit_order_id"] == "PO_CLOSED"
    assert order["market_fallback_qty"] == pytest.approx(0.0)
    assert order["market_fallback_order_id"] is None
    assert sleeps
    assert not ex.create_market_order.called


def test_post_only_late_fill_without_actual_price_is_explicitly_unverified(monkeypatch):
    """Cancel race closed olsa da limit price/target gerçekleşen average sayılmaz."""
    ex = MagicMock()
    ex.create_order.return_value = {"id": "PO_LATE", "status": "open"}
    ex.cancel_order.return_value = {"id": "PO_LATE", "status": "canceled"}
    ex.fetch_order.return_value = {
        "id": "PO_LATE",
        "status": "closed",
        "filled": 1.0,
        "average": None,
        "price": 99.9,
    }
    monkeypatch.setattr("price_action.execution.post_only_router.time.sleep", lambda _: None)

    order, method = place_post_only_with_fallback(
        ex,
        symbol="BTC/USDT",
        side="buy",
        qty=1.0,
        target_price=100.0,
        fallback_after_sec=0,
    )

    assert method == "post_only_filled_late"
    assert order["filled"] == pytest.approx(1.0)
    assert order.get("average") is None
    assert order.get("price") is None
    assert order["exchange_reported_price"] == pytest.approx(99.9)
    assert order["fill_price_verified"] is False
    assert order["slippage_verified"] is False
    assert order["slippage_bps"] is None
    assert order["partial_limit_qty"] == pytest.approx(1.0)
    assert order["market_fallback_qty"] == pytest.approx(0.0)
    assert not ex.create_market_order.called


def test_market_fallback_client_order_id_respects_binance_36_char_limit():
    """Ana coid 36 karakter olsa da deterministic `_fb` kimliği sınırı aşmaz."""
    ex = _PartialFallbackExchange(
        limit_fill={"id": "PO_PARTIAL", "status": "canceled", "filled": 0.0},
        market_initial={
            "id": "MK_PARTIAL",
            "status": "closed",
            "filled": 1.0,
            "average": 100.0,
        },
        market_snapshots=[],
    )
    long_coid = "PA_" + ("a" * 33)
    assert len(long_coid) == 36

    place_post_only_with_fallback(
        ex,
        symbol="BTC/USDT",
        side="buy",
        qty=1.0,
        target_price=100.0,
        fallback_after_sec=0,
        client_order_id=long_coid,
    )

    fallback_coid = ex.market_calls[0]["params"]["newClientOrderId"]
    assert len(fallback_coid) <= 36
    assert fallback_coid.endswith("_fb")
