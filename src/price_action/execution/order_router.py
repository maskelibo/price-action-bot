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
from datetime import UTC, datetime
from typing import Any

from price_action.contracts import Signal
from price_action.execution.idempotency import IdempotencyStore
from price_action.execution.slippage_tracker import SlippageTracker

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

        decision_tmp = risk_officer.evaluate(
            signal_obj, account, market_price=cur_px, returns_df=returns_df
        )
        if hasattr(decision_tmp, "notional_usdt") and (
            float(decision_tmp.notional_usdt) > capital_cap_usdt
        ):
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
    decision = risk_officer.evaluate(
        signal_obj, account, market_price=ref_price, returns_df=returns_df
    )
    if not hasattr(decision, "quantity"):
        reject_reason = getattr(decision, "reason", "unknown")
        idem.mark_rejected(fingerprint, reason=reject_reason)
        return {"status": "rejected", "symbol": sym, "reason": reject_reason}

    risked = decision
    qty = float(risked.quantity)
    notional = float(risked.notional_usdt)
    # not: RUF046 pre-existing — int() Decimal/np-leverage girişleri için korunur
    leverage_used = max(1, min(5, int(round(risked.leverage)))) or 1  # noqa: RUF046
    margin = notional / leverage_used

    # 6) Margin check
    avail = float(getattr(account, "free_margin_usdt", 0))
    if margin > avail * 0.9:
        idem.mark_rejected(fingerprint, reason="broker_margin")
        return {
            "status": "rejected",
            "symbol": sym,
            "reason": "broker_margin",
            "need": margin,
            "have": avail,
        }

    # 7) Idempotency mark + client_order_id oluştur
    client_order_id = idem.mark_submitted(fingerprint, symbol=sym, side=side)

    # 8) Leverage set
    try:
        exchange.set_leverage(leverage_used, sym)
    except Exception as e:
        if "No need to change" not in str(e) and "not modified" not in str(e).lower():
            # log-only (W8-MED): gerçek set_leverage fail'i artık görünür —
            # pozisyon amaçlanandan farklı kaldıraçla açılabilir (non-fatal ama kör olmasın)
            import logging as _lg

            _lg.getLogger(__name__).warning(f"order_router.set_leverage_fail {sym}: {str(e)[:120]}")

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
        # İptal et — resubmit yasak.
        # Paket-5 fix (2026-07-10, ccxt_live 7d6fc29 şablonu): cancel YUTULMAZ —
        # cancel sonrası fetch_order ile BORSA GERÇEĞİ doğrulanır:
        #   * emir (kısmen) DOLMUŞSA (race) → fill SAHİPLENİLİR; rejected yazmak
        #     journal-drift = naked-position sınıfı idi,
        #   * emir hâlâ açık / durum bilinmiyorsa → cancel_verified=False bayrağı
        #     + error log (çağıran borsada asılı emir olabileceğini bilir).
        import logging as _lg

        _rlog = _lg.getLogger(__name__)
        cancel_ok = True
        try:
            exchange.cancel_order(exchange_order_id, sym)
        except Exception as _cx_err:
            cancel_ok = False
            _rlog.warning(f"order_router.slip_cancel_fail {sym}: {str(_cx_err)[:120]}")

        v_status = ""
        v_filled = 0.0
        v_avg = 0.0
        verify_ok = False
        try:
            _v = exchange.fetch_order(exchange_order_id, sym)
            v_status = str(_v.get("status") or "").lower()
            v_filled = float(_v.get("filled") or 0.0)
            v_avg = float(_v.get("average") or 0.0)
            verify_ok = True
        except Exception as _vf_err:
            _rlog.warning(f"order_router.slip_cancel_verify_fail {sym}: {str(_vf_err)[:120]}")

        # Sahiplenme yalnız TANINAN borsa-durumlarında: tam dolum (closed/filled)
        # veya bilinen-iptal statüsünde gerçek kısmi dolum. Tanınmayan status +
        # filled alanı tek başına sahiplenme tetiklemez (sahte-pozitif koruması).
        _known_cancel = ("canceled", "cancelled", "expired", "rejected")
        if verify_ok and (
            v_status in ("closed", "filled") or (v_status in _known_cancel and v_filled > 0.0)
        ):
            # Race: emir slippage-iptaline rağmen (kısmen) doldu → pozisyon BORSADA
            # gerçek → fill'i sahiplen (idem+tracker'a gerçeği yaz, filled dön).
            own_qty = v_filled if v_filled > 0.0 else fill_qty
            own_px = v_avg or avg_px
            _rlog.error(
                f"order_router.slip_cancel_race_filled {sym}: pozisyon BORSADA "
                f"(qty={own_qty}, px={own_px}, slip={slip_bps:.1f}bps) — fill sahiplenildi"
            )
            idem.mark_filled(fingerprint, exchange_order_id, own_px, own_qty)
            fill_id = uuid.uuid4().hex[:20]
            tracker.record_fill(
                fill_id=fill_id,
                ts=datetime.now(UTC),
                symbol=sym,
                strategy=strategy,
                side=side,
                expected_price=ref_price,
                realized_price=own_px,
                quantity=own_qty,
                fee_usdt=own_qty * own_px * 0.00075,
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
                "fill_price": own_px,
                "fill_qty": own_qty,
                "notional_usdt": own_qty * own_px,
                "fee_usdt": own_qty * own_px * 0.00075,
                "slippage_bps": round(slip_bps, 2),
                "slippage_exceeded": True,  # kapı aşıldı AMA pozisyon borsada gerçek
                "is_maker": actual_type == "post_only_limit",
                "leverage": leverage_used,
            }

        cancel_verified = verify_ok and v_status != "open"
        if not cancel_verified:
            _rlog.error(
                f"order_router.slip_cancel_unverified {sym} id={exchange_order_id}: "
                f"emir borsada ASILI olabilir (cancel_ok={cancel_ok}, "
                f"status={v_status or 'unknown'})"
            )
        idem.mark_rejected(fingerprint, reason=f"slippage_exceeded:{slip_bps:.1f}bps")
        return {
            "status": "rejected",
            "symbol": sym,
            "reason": "slippage_exceeded",
            "slippage_bps": slip_bps,
            "cancel_verified": cancel_verified,
        }

    # 12) Idempotency fill update
    idem.mark_filled(fingerprint, exchange_order_id, avg_px, fill_qty)

    # 13) Slippage kayıt
    fill_id = uuid.uuid4().hex[:20]
    tracker.record_fill(
        fill_id=fill_id,
        ts=datetime.now(UTC),
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


def _place_market(exchange: Any, sym: str, side: str, qty: float, client_order_id: str) -> Any:
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
    limit_px = best_bid - tick if side == "buy" else best_ask + tick

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

    import logging as _lg

    _rlog = _lg.getLogger(__name__)

    # Fill bekleme (#10: poll hataları YUTULMAZ — timeout sonunda tek özet log)
    t0 = time.time()
    _polls = 0
    _poll_errs = 0
    _last_err: str | None = None
    while time.time() - t0 < timeout_sec:
        _polls += 1
        try:
            o = exchange.fetch_order(order_id, sym)
            if o.get("status") == "closed":
                return o, "post_only_limit"
        except Exception as _pe:
            _poll_errs += 1
            _last_err = str(_pe)[:120]
        time.sleep(1.0)
    if _poll_errs:
        _rlog.warning(
            f"order_router.poll_summary {sym} id={order_id}: {_polls} deneme, "
            f"{_poll_errs} hata, son_hata={_last_err}"
        )

    # Timeout → cancel + market — Paket-5 fix (2026-07-10, ccxt_live 7d6fc29 şablonu):
    # cancel fail YUTULMAZ + koşulsuz TAM-QTY market YOK (çift-pozisyon sınıfı).
    #   * cancel sonrası fetch_order ile borsa gerçeği tazelenir,
    #   * limit hâlâ açık / durum bilinmiyor → market fallback REDDET → (None, ...),
    #   * race'te dolmuşsa fill sahiplenilir (market gerekmez),
    #   * onaylı iptal + kısmi dolum → yalnız KALAN market'e; dönen order dict
    #     toplamı yansıtır (filled=kısmi+market, average=ağırlıklı).
    cancel_ok = True
    try:
        exchange.cancel_order(order_id, sym)
    except Exception as _tc_err:
        cancel_ok = False
        _rlog.warning(
            f"order_router.timeout_cancel_fail {sym} id={order_id}: {str(_tc_err)[:120]}"
        )

    partial_filled = 0.0
    partial_px = 0.0
    still_resting = not cancel_ok
    o = None
    try:
        o = exchange.fetch_order(order_id, sym)
        _status = str(o.get("status") or "").lower()
        partial_filled = float(o.get("filled") or 0.0)
        partial_px = float(o.get("average") or 0.0) or limit_px
        if _status in ("closed", "filled"):
            return o, "post_only_limit"  # race: timeout sonrası tam doldu → sahiplen
        if _status == "open":
            still_resting = True  # cancel etkisiz — limit hâlâ borsada
    except Exception as _vf_err:
        still_resting = True  # durum bilinmiyor → fail-closed
        _rlog.error(
            f"order_router.timeout_cancel_verify_fail {sym} id={order_id}: "
            f"{str(_vf_err)[:120]}"
        )

    if still_resting:
        _rlog.error(
            f"order_router.timeout_cancel_unverified {sym} id={order_id}: "
            f"limit borsada ASILI olabilir — market fallback REDDEDİLDİ "
            f"(çift-pozisyon riski)"
        )
        return None, "cancel_unverified"

    remaining = max(0.0, qty - partial_filled)
    if remaining <= 0.0:
        return o, "post_only_limit"  # fiilen tümü dolmuş — market gerekmez

    fb = _place_market(exchange, sym, side, remaining, client_order_id + "_fb")
    if fb is not None and partial_filled > 0.0:
        # Kısmi limit dolumu + market kalanı → çağırana TOPLAMI yansıt
        # (aksi hâlde journal/koruma yalnız market bacağını boyutlar).
        try:
            mk_fill = float(fb.get("filled") or remaining)
            mk_px = float(fb.get("average") or 0.0) or partial_px
            total = mk_fill + partial_filled
            fb["filled"] = total
            fb["average"] = ((mk_px * mk_fill) + (partial_px * partial_filled)) / max(
                total, 1e-12
            )
            fb["partial_limit_qty"] = partial_filled
        except Exception as _bl_err:
            _rlog.error(f"order_router.partial_blend_fail {sym}: {str(_bl_err)[:120]}")
    return fb, "market"
