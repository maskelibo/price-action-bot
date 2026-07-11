"""Maker oranı kalibrasyonu — execution paketi 2026-07-10 (maker %21→%50+ hedef).

Kök-neden: post-only limit target_price'a (=last-trade fiyatı) konuyordu — passive
offset YOK → yarı zaman book'u cross → Binance -5022 reject → taker fallback
(maker payı ~%21). Fix: passive best_bid/best_ask'e yerleştir (cross etmez) →
gerçekten maker rest eder. target_price slippage baseline olarak KORUNUR.

Regresyon kalkanı: taker market fallback zinciri DEĞİŞMEZ (Faz 3) → giriş ASLA
düşmez; bid/ask yoksa eski davranışa döner; slippage 25bps kapısı baseline
target_price'da kalır (self-bypass yok).
"""

from __future__ import annotations

import re

from price_action.execution.post_only_router import (
    _maker_limit_price,
    place_post_only_with_fallback,
)


class FakeEx:
    def __init__(self, *, create_status="closed", create_raises=False, market_avg=100.0):
        self.create_calls = []
        self.market_calls = []
        self.create_status = create_status
        self.create_raises = create_raises
        self.market_avg = market_avg

    def price_to_precision(self, symbol, x):
        return f"{float(x):.2f}"

    def amount_to_precision(self, symbol, x):
        return f"{float(x):.6f}"

    def create_order(self, symbol, type, side, amount, price, params):
        self.create_calls.append({"price": price, "side": side, "amount": amount})
        if self.create_raises:
            raise Exception("-5022 post only would cross")
        return {"id": "L1", "status": self.create_status, "filled": amount}

    def create_market_order(self, symbol, side, amount, params=None):
        self.market_calls.append({"side": side, "amount": amount})
        return {"id": f"M{len(self.market_calls)}", "average": self.market_avg, "filled": amount}

    def fetch_order(self, order_id, symbol):
        # verify/wait: canceled + hiç dolmamış (market fallback yolunu açar)
        return {"id": order_id, "status": "canceled", "filled": 0.0, "average": self.market_avg}

    def cancel_order(self, order_id, symbol):
        return {"id": order_id, "status": "canceled"}


# ---------------------------------------------------------------------------
# _maker_limit_price — pure
# ---------------------------------------------------------------------------


def test_maker_price_buy_uses_bid():
    px = _maker_limit_price(FakeEx(), "BTC/USDT", "buy", 100.0, 99.98, 100.02)
    assert px == 99.98


def test_maker_price_sell_uses_ask():
    px = _maker_limit_price(FakeEx(), "BTC/USDT", "sell", 100.0, 99.98, 100.02)
    assert px == 100.02


def test_maker_price_no_cross_invariant():
    buy_px = _maker_limit_price(FakeEx(), "BTC/USDT", "buy", 100.0, 99.98, 100.02)
    sell_px = _maker_limit_price(FakeEx(), "BTC/USDT", "sell", 100.0, 99.98, 100.02)
    assert buy_px < 100.02  # buy < ask → cross etmez
    assert sell_px > 99.98  # sell > bid → cross etmez


def test_maker_price_missing_book_falls_back_to_target():
    assert _maker_limit_price(FakeEx(), "BTC/USDT", "buy", 100.0, None, None) == 100.0


def test_maker_price_inverted_book_falls_back():
    # bid >= ask (stale/ters) → güvenli fallback
    assert _maker_limit_price(FakeEx(), "BTC/USDT", "buy", 100.0, 100.5, 100.0) == 100.0


def test_maker_price_zero_falls_back():
    assert _maker_limit_price(FakeEx(), "BTC/USDT", "sell", 100.0, 0.0, 100.02) == 100.0


# ---------------------------------------------------------------------------
# place_post_only_with_fallback — entegrasyon
# ---------------------------------------------------------------------------


def test_post_only_places_at_maker_price():
    """Post-only emri target değil best_bid'e konur (buy)."""
    ex = FakeEx(create_status="closed")
    _order, method = place_post_only_with_fallback(
        ex,
        "BTC/USDT",
        "buy",
        1.0,
        target_price=100.0,
        best_bid=99.98,
        best_ask=100.02,
        fallback_after_sec=0,
    )
    assert method == "post_only_filled"
    assert ex.create_calls[0]["price"] == 99.98  # target 100.0 DEĞİL


def test_missing_book_places_at_target_backward_compat():
    """bid/ask yoksa eski davranış: post-only target_price'a konur."""
    ex = FakeEx(create_status="closed")
    place_post_only_with_fallback(
        ex,
        "BTC/USDT",
        "buy",
        1.0,
        target_price=100.0,
        fallback_after_sec=0,
    )
    assert ex.create_calls[0]["price"] == 100.0


def test_taker_fallback_still_fires_on_timeout():
    """REGRESYON KALKANI: post-only dolmazsa market fallback yine çalışır (drop yok)."""
    ex = FakeEx(create_status="open", market_avg=100.0)
    _order, method = place_post_only_with_fallback(
        ex,
        "BTC/USDT",
        "buy",
        1.0,
        target_price=100.0,
        best_bid=99.98,
        best_ask=100.02,
        fallback_after_sec=0,
    )
    assert method == "market_fallback"
    assert len(ex.market_calls) == 1  # taker fallback atıldı


def test_taker_fallback_fires_on_postonly_reject():
    """Post-only create_order RAISE (cross reject) → market fallback yine çalışır."""
    ex = FakeEx(create_raises=True, market_avg=100.0)
    _order, method = place_post_only_with_fallback(
        ex,
        "BTC/USDT",
        "sell",
        1.0,
        target_price=100.0,
        best_bid=99.98,
        best_ask=100.02,
        fallback_after_sec=0,
    )
    assert method == "market_fallback"
    assert len(ex.market_calls) == 1


def test_slippage_baseline_stays_target_not_maker_price():
    """Slippage 25bps kapısı baseline target_price'da; maker fiyatına repoint edilmez.
    High-slippage owned fill ters market emriyle unwind edilmez; korumaya devredilir."""
    ex = FakeEx(create_status="open", market_avg=100.30)
    order, method = place_post_only_with_fallback(
        ex,
        "BTC/USDT",
        "buy",
        1.0,
        target_price=100.0,
        best_bid=99.98,
        best_ask=100.02,
        fallback_after_sec=0,
        slippage_limit_bps=25.0,
    )

    assert method == "market_fallback_slippage_breach_protect"
    assert order["slippage_breach"]["owned_average"] == 100.30
    assert round(order["slippage_breach"]["slippage_bps"], 8) == 30.0


# ---------------------------------------------------------------------------
# Kaynak-pin
# ---------------------------------------------------------------------------


def test_source_pins_maker_wiring():
    from pathlib import Path

    router = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "price_action"
        / "execution"
        / "post_only_router.py"
    ).read_text(encoding="utf-8")
    assert "_maker_limit_price(" in router
    assert "price=_maker_px," in router
    # Sadece create_order'ın `price=` kwarg'ını yasakla; helper'ların
    # `arrival_px=target_price` gibi güvenli baseline aktarımı false-positive olmasın.
    assert re.search(r"(?<![A-Za-z_])price\s*=\s*target_price\s*,", router) is None
    daemon = (Path(__file__).resolve().parents[1] / "scripts" / "futures_daemon.py").read_text(
        encoding="utf-8"
    )
    assert 'best_bid=_ticker.get("bid")' in daemon
    assert 'best_ask=_ticker.get("ask")' in daemon
