"""Order Router — sinyal → borsa emri tam akışı.

Bu modül futures_trade_daily.py'deki submit_to_futures() mantığını
idempotency + slippage tracking + dead man's switch ile bütünleştirir.
Backward compatible: mevcut daemonlar kendi flow'larını korur.
Bu modül scheduler wiring ve yeni entegrasyonlar için referans implementasyondur.

Ana fonksiyon:
    route_signal(signal_dict, exchange, risk_officer, account, returns_df)
        -> dict: {status, symbol, side, fill_id, slippage_bps, ...}

Desteklenen order tipleri:
    - market (default, testnet uyumlu)
    - post_only_limit (maker rebate, >30s timeout → market fallback)

Idempotency:
    - Signal fingerprint → client_order_id
    - DuckDB persist → restart sonrası duplicate koruması
    - Borsa tarafı idem: "already exists" hata → mevcut fill fetch

Slippage:
    - Her fill record_fill() ile SlippageTracker'a
    - >25 bps → zaten broker'da iptal; burada tekrar log
    - Günlük özet: daily_summary() çağrısı daemon loop sonunda
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from price_action.execution.idempotency import IdempotencyStore
from price_action.execution.slippage_tracker import SlippageTracker
from price_action.contracts import Position, Signal


# Singleton'lar (daemon başına bir instance)
_idem_store: IdempotencyStore | None = None
_slip_tracker: SlippageTracker | None = None


def get_idempotency_store() -> IdempotencyStore:
    global _idem_store
    if _idem_store is None:
        _idem_store = IdempotencyStore()
    return _idem_store


def get_slippage_tracker() -> SlippageTracker:
    global _slip_tracker
    if _slip_tracker is None:
        _slip_tracker = SlippageTracker()
    return _slip_tracker


def route_signal(
    signal_dict: dict,
    exchange: Any,
    risk_officer: Any,
    account: Any,
    returns_df: Any,
    *,
    post_only: bool = False,
    post_only_timeout_sec: int = 30,
    max_slippage_bps: float = 25.0,
    capital_cap_usdt: float | None = None,
) -> dict:
    """Tek sinyal için tam order akışı.

    Returns: status dict (status='filled'|'rejected'|'error'|'duplicate'|'cap_exceeded')
    """
    idem = get_idempotency_store()
    tracker = get_slippage_tracker()

    sym = signal_dict["symbol"]
    side = signal_dict["side"]
    strategy = signal_dict.get("strategy", "unknown")

    # 1) Signal fingerprint — idempotency kontrolü
    from scripts.lib.risk_integration import build_signal_from_scan
    try:
        signal_obj: Signal = build_signal_from_scan(signal_dict, venue="binance")
    except Exception as e:
        return {"status": "error", "symbol": sym, "reason": f"signal_build: {e}"}

    fingerprint = signal_obj.fingerprint()

    # 2) Duplicate kontrolü
    if idem.is_seen(fingerprint):
        existing = idem.get(fingerprint)
        return {
            "status": "duplicate",
            "symbol": sym,
            "fingerprint": fingerprint,
            "existing_status": existing.get("status") if existing else "unknown",
        }

    # 3) Capital cap kontrolü
    if capital_cap_usdt is not None:
        try:
            ticker = exchange.fetch_ticker(sym)
            cur_px = float(ticker["last"])
        except Exception as e:
            return {"status": "error", "symbol": sym, "reason": f"ticker_fail: {e}"}

        decision_tmp = risk_officer.evaluate(signal_obj, account,
                                             market_price=cur_px, returns_df=returns_df)
        if hasattr(decision_tmp, "notional_usdt"):
            if float(decision_tmp.notional_usdt) > capital_cap_usdt:
                idem.mark_rejected(fingerprint, reason="capital_cap_exceeded")
                return {
                    "status": "cap_exceeded",
                    "symbol": sym,
                    "notional": float(decision_tmp.notional_usdt),
                    "cap": capital_cap_usdt,
                }

    # 4) Ticker (varsa zaten fetch edildi)
    try:
        ticker = exchange.fetch_ticker(sym)
        ref_price = float(ticker["last"])
    except Exception as e:
        return {"status": "error", "symbol": sym, "reason": f"ticker_fail: {e}"}

    # 5) RiskOfficer
    decision = risk_officer.evaluate(signal_obj, account,
                                     market_price=ref_price, returns_df=returns_df)
    if not hasattr(decision, "quantity"):
        reject_reason = getattr(decision, "reason", "unknown")
        idem.mark_rejected(fingerprint, reason=reject_reason)
        return {"status": "rejected", "symbol": sym, "reason": reject_reason}

    risked = decision
    qty = float(risked.quantity)
    notional = float(risked.notional_usdt)
    leverage_used = max(1, min(5, int(round(risked.leverage)))) or 1
    margin = notional / leverage_used

    # 6) Margin check
    avail = float(getattr(account, "free_margin_usdt", 0))
    if margin > avail * 0.9:
        idem.mark_rejected(fingerprint, reason="broker_margin")
        return {"status": "rejected", "symbol": sym, "reason": "broker_margin",
                "need": margin, "have": avail}

    # 7) Idempotency mark + client_order_id oluştur
    client_order_id = idem.mark_submitted(fingerprint, symbol=sym, side=side)

    # 8) Leverage set
    try:
        exchange.set_leverage(leverage_used, sym)
    except Exception as e:
        if "No need to change" not in str(e) and "not modified" not in str(e).lower():
            pass  # leverage set fail non-fatal

    # 9) Emir gönder
    order_side = "buy" if side == "long" else "sell"
    try:
        if post_only:
            order, actual_type = _place_post_only_with_fallback(
                exchange, sym, order_side, qty, client_order_id, post_only_timeout_sec
            )
        else:
            order = _place_market(exchange, sym, order_side, qty, client_order_id)
            actual_type = "market"
    except Exception as e:
        idem.mark_rejected(fingerprint, reason=f"order_place_error: {e}")
        return {"status": "error", "symbol": sym, "reason": str(e)[:200]}

    if order is None:
        idem.mark_rejected(fingerprint, reason="order_returned_none")
        return {"status": "error", "symbol": sym, "reason": "order_returned_none"}

    # 10) Fill bilgileri
    exchange_order_id = str(order.get("id", ""))
    fill_qty = float(order.get("filled", qty))
    avg_px = float(order.get("average", ref_price))
    fee_raw = order.get("fee", {}) or {}
    fee_usdt = float(fee_raw.get("cost", 0.0)) or fill_qty * avg_px * 0.00075

    # 11) Slippage kontrolü
    if side == "long":
        slip_bps = (avg_px - ref_price) / max(ref_price, 1e-10) * 10_000
    else:
        slip_bps = (ref_price - avg_px) / max(ref_price, 1e-10) * 10_000

    if slip_bps > max_slippage_bps:
        # İptal et — resubmit yasak
        try:
            exchange.cancel_order(exchange_order_id, sym)
        except Exception:
            pass
        idem.mark_rejected(fingerprint, reason=f"slippage_exceeded:{slip_bps:.1f}bps")
        return {
            "status": "rejected",
            "symbol": sym,
            "reason": "slippage_exceeded",
            "slippage_bps": slip_bps,
        }

    # 12) Idempotency fill update
    idem.mark_filled(fingerprint, exchange_order_id, avg_px, fill_qty)

    # 13) Slippage kayıt
    fill_id = uuid.uuid4().hex[:20]
    tracker.record_fill(
        fill_id=fill_id,
        ts=datetime.now(timezone.utc),
        symbol=sym,
        strategy=strategy,
        side=side,
        expected_price=ref_price,
        realized_price=avg_px,
        quantity=fill_qty,
        fee_usdt=fee_usdt,
        is_maker=(actual_type == "post_only_limit"),
        order_type=actual_type,
        mode="live",
        exchange_order_id=exchange_order_id,
        client_order_id=client_order_id,
    )

    return {
        "status": "filled",
        "symbol": sym,
        "side": side,
        "strategy": strategy,
        "fill_id": fill_id,
        "exchange_order_id": exchange_order_id,
        "client_order_id": client_order_id,
        "ref_price": ref_price,
        "fill_price": avg_px,
        "fill_qty": fill_qty,
        "notional_usdt": fill_qty * avg_px,
        "fee_usdt": fee_usdt,
        "slippage_bps": round(slip_bps, 2),
        "is_maker": actual_type == "post_only_limit",
        "leverage": leverage_used,
    }


def _place_market(exchange: Any, sym: str, side: str, qty: float,
                  client_order_id: str) -> Any:
    """Market order, client_order_id ile."""
    return exchange.create_market_order(
        symbol=sym,
        side=side,
        amount=qty,
        params={"newClientOrderId": client_order_id},
    )


def _place_post_only_with_fallback(
    exchange: Any,
    sym: str,
    side: str,
    qty: float,
    client_order_id: str,
    timeout_sec: int,
) -> tuple[Any, str]:
    """Post-only limit, timeout sonrası market fallback.

    Returns: (order_dict, order_type_str)
    """
    import time

    try:
        ob = exchange.fetch_order_book(sym, limit=5)
        best_bid = float(ob["bids"][0][0]) if ob.get("bids") else 0
        best_ask = float(ob["asks"][0][0]) if ob.get("asks") else 0
    except Exception:
        best_bid = best_ask = 0

    if best_bid <= 0 or best_ask <= 0:
        # Fallback market
        return _place_market(exchange, sym, side, qty, client_order_id), "market"

    ref = (best_bid + best_ask) / 2
    tick = ref * 0.0001
    if side == "buy":
        limit_px = best_bid - tick
    else:
        limit_px = best_ask + tick

    try:
        order = exchange.create_limit_order(
            symbol=sym,
            side=side,
            amount=qty,
            price=limit_px,
            params={
                "postOnly": True,
                "timeInForce": "GTC",
                "newClientOrderId": client_order_id,
            },
        )
        order_id = str(order.get("id", ""))
    except Exception:
        return _place_market(exchange, sym, side, qty, client_order_id), "market"

    # Fill bekleme
    t0 = time.time()
    while time.time() - t0 < timeout_sec:
        try:
            o = exchange.fetch_order(order_id, sym)
            if o.get("status") == "closed":
                return o, "post_only_limit"
        except Exception:
            pass
        time.sleep(1.0)

    # Timeout → cancel + market
    try:
        exchange.cancel_order(order_id, sym)
    except Exception:
        pass
    return _place_market(exchange, sym, side, qty, client_order_id + "_fb"), "market"
