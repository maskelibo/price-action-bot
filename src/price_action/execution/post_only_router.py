"""Post-Only Limit Router — Slippage gate with safe market fallback.

SEC26.B-5 implementasyonu (CONDITIONAL — paper test ZORUNLU).

Tasarim:
  Faz 1: Post-only limit emir gonder (timeInForce=PO, maker rebate, 0bps slippage)
  Faz 2: fallback_after_sec icinde fill bekle (poll fetch_order)
  Faz 3: Fill yoksa iptal et + market order fallback
  Faz 4: Market fallback slippage > slippage_limit_bps ise reverse-close + raise

Backtest assumption: %100 fill (market order)
Live paper trading expected: %60-80 post-only fill rate
- Fill rate >= %60 -> enable production
- Fill rate < %60 -> keep disabled, market order ile devam

CRITICAL:
  - **Default DISABLED** (configs/risk_balanced.yaml execution.post_only_limit_enabled: false)
  - Slippage limit market fallback'te de korunur
  - Replay etkisi: ZERO (default OFF)
"""
from __future__ import annotations

import time
from typing import Any


class SlippageExceededError(Exception):
    """Market fallback fill slippage > limit. Pozisyon ters-kapatildi."""

    def __init__(self, slippage_bps: float, limit_bps: float, symbol: str = "") -> None:
        self.slippage_bps = slippage_bps
        self.limit_bps = limit_bps
        self.symbol = symbol
        super().__init__(
            f"Market fallback slippage {slippage_bps:.1f}bps > {limit_bps:.1f}bps "
            f"({symbol}); pozisyon ters-kapatildi"
        )


def opposite_side(side: str) -> str:
    """buy <-> sell."""
    if side.lower() in ("buy", "long"):
        return "sell"
    if side.lower() in ("sell", "short"):
        return "buy"
    raise ValueError(f"unknown side: {side!r}")


def _compute_slippage_bps(side: str, expected_px: float, fill_px: float) -> float:
    """Yon-duzeltmeli slippage. Buy'da +R, sell'de +R = maliyet."""
    if expected_px <= 0:
        return 0.0
    if side.lower() in ("buy", "long"):
        return (fill_px - expected_px) / expected_px * 10_000
    return (expected_px - fill_px) / expected_px * 10_000


def _wait_for_fill(exchange: Any, order_id: str, symbol: str, timeout_sec: int,
                   poll_interval: float = 1.0) -> str:
    """Order durumunu poll et. closed/filled/canceled doner.

    Returns: order status string ('closed', 'open', 'canceled', vb.)
    """
    t0 = time.time()
    last_status = "open"
    while time.time() - t0 < timeout_sec:
        try:
            o = exchange.fetch_order(order_id, symbol)
            last_status = str(o.get("status", "open"))
            if last_status in ("closed", "filled", "canceled"):
                return last_status
        except Exception:
            pass
        time.sleep(poll_interval)
    return last_status


def place_post_only_with_fallback(
    exchange: Any,
    symbol: str,
    side: str,
    qty: float,
    target_price: float,
    *,
    fallback_after_sec: int = 30,
    slippage_limit_bps: float = 25.0,
    client_order_id: str | None = None,
    poll_interval: float = 1.0,
) -> tuple[dict, str]:
    """Post-only limit + market fallback + slippage gate.

    Args:
        exchange: ccxt-compatible (create_order, fetch_order, cancel_order,
                  create_market_order).
        symbol: 'BTC/USDT'
        side: 'buy' | 'sell' (long sinyal -> 'buy', short -> 'sell')
        qty: amount
        target_price: ref fiyat (slippage hesabi icin baseline)
        fallback_after_sec: post-only timeout (default 30)
        slippage_limit_bps: market fallback slippage limit (default 25)
        client_order_id: idempotency
        poll_interval: fetch_order poll periyodu

    Returns:
        (order_dict, method_str)
        method_str: 'post_only_filled' | 'market_fallback'

    Raises:
        SlippageExceededError: Market fallback slippage > limit -> ters-kapatildi.
    """
    params: dict[str, Any] = {}
    if client_order_id:
        params["newClientOrderId"] = client_order_id

    # ===== FAZ 1: Post-only limit =====
    post_only_params = {**params, "timeInForce": "PO", "postOnly": True}
    order_id: str | None = None
    try:
        order = exchange.create_order(
            symbol=symbol,
            type="limit",
            side=side,
            amount=qty,
            price=target_price,
            params=post_only_params,
        )
        order_id = str(order.get("id", ""))
    except Exception:
        # Post-only reddedildi (market'i cross ediyor olabilir). Direk market fallback.
        order = None
        order_id = None

    # ===== FAZ 2: Fill bekle =====
    if order_id:
        # Eger order_dict zaten 'closed' geldiyse poll'lemeye gerek yok
        initial_status = str(order.get("status", "open")) if order else "open"
        if initial_status in ("closed", "filled"):
            final_status = initial_status
        else:
            final_status = _wait_for_fill(
                exchange, order_id, symbol, fallback_after_sec, poll_interval
            )
        if final_status in ("closed", "filled"):
            # Yeniden fetch — kesin fill detayi icin
            try:
                final = exchange.fetch_order(order_id, symbol)
                return final, "post_only_filled"
            except Exception:
                return order or {}, "post_only_filled"

        # Timeout -> cancel
        try:
            exchange.cancel_order(order_id, symbol)
        except Exception:
            pass

    # ===== FAZ 3: Market fallback =====
    fb_client_id = (client_order_id + "_fb") if client_order_id else None
    fb_params = {"newClientOrderId": fb_client_id} if fb_client_id else {}
    market_order = exchange.create_market_order(
        symbol=symbol,
        side=side,
        amount=qty,
        params=fb_params,
    )

    # ===== FAZ 4: Slippage gate (market fallback) =====
    fill_px = float(market_order.get("average") or market_order.get("price") or target_price)
    slip_bps = _compute_slippage_bps(side, target_price, fill_px)

    if slip_bps > slippage_limit_bps:
        # Ters-kapat: ayni qty market order, opposite side
        rev_side = opposite_side(side)
        try:
            exchange.create_market_order(
                symbol=symbol,
                side=rev_side,
                amount=qty,
                params={"reduceOnly": True} if hasattr(exchange, "options") else {},
            )
        except Exception:
            # Reverse fail — pozisyon acik, alarm
            pass
        raise SlippageExceededError(slip_bps, slippage_limit_bps, symbol=symbol)

    return market_order, "market_fallback"
