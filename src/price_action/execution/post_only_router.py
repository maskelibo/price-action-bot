"""Post-Only Limit Router — Slippage gate with safe market fallback.

SEC26.B-5 implementasyonu (CONDITIONAL — paper test ZORUNLU).

Tasarim:
  Faz 1: Post-only limit emir gonder (timeInForce=PO, maker rebate, 0bps slippage)
  Faz 2: fallback_after_sec icinde fill bekle (poll fetch_order)
  Faz 3: Fill yoksa iptal et + market order fallback
  Faz 4: Market fallback slippage > slippage_limit_bps ise dolumu sahiplen ve
         caller'in kanonik SL/TP koruma zincirine typed sonuc ile devret

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

import hashlib
import logging as _logging
import math
import time
from enum import StrEnum
from typing import Any

_MOD_LOG = _logging.getLogger(__name__)

_FILL_RECONCILE_MAX_FETCHES = 4
_FILL_RECONCILE_DELAY_SEC = 0.25
_BINANCE_CLIENT_ORDER_ID_MAX_LEN = 36


class SlippageBreachDisposition(StrEnum):
    """Safe ownership disposition for a high-slippage filled entry."""

    PROTECT_POSITION = "protect_position"


class SlippageExceededError(Exception):
    """Legacy compatibility error; new fills return a protection outcome."""

    def __init__(self, slippage_bps: float, limit_bps: float, symbol: str = "") -> None:
        self.slippage_bps = slippage_bps
        self.limit_bps = limit_bps
        self.symbol = symbol
        super().__init__(
            f"Market fallback slippage {slippage_bps:.1f}bps > {limit_bps:.1f}bps ({symbol})"
        )


class OrderSubmissionUncertainError(RuntimeError):
    """Exchange submit sonucu bilinmiyor; ayni niyet yeniden gonderilemez.

    Bir timeout/network hatasi emrin reddedildigini kanitlamaz.  Bu typed hata,
    daemon/queue katmaninin once deterministik client-order-id'leri reconcile
    edebilmesi icin gerekli sahiplik bilgisini tasir.
    """

    def __init__(
        self,
        *,
        stage: str,
        symbol: str,
        side: str,
        main_client_order_id: str | None,
        fallback_client_order_id: str | None,
        partial_order: dict[str, Any] | None,
        partial_qty: float,
        remaining_qty: float,
        cause: BaseException | None = None,
    ) -> None:
        self.stage = stage
        self.symbol = symbol
        self.side = side
        self.main_client_order_id = main_client_order_id
        self.fallback_client_order_id = fallback_client_order_id
        self.partial_order = dict(partial_order) if isinstance(partial_order, dict) else None
        self.partial_qty = max(float(partial_qty), 0.0)
        self.remaining_qty = max(float(remaining_qty), 0.0)
        self.cause = cause
        uncertain_ids: list[str] = []
        if stage in {"post_only_limit_submit", "post_only_cancel_verify"} and main_client_order_id:
            uncertain_ids.append(main_client_order_id)
        if stage == "market_fallback_submit" and fallback_client_order_id:
            uncertain_ids.append(fallback_client_order_id)
        self.uncertain_client_order_ids = tuple(uncertain_ids)
        cause_text = f"{type(cause).__name__}: {str(cause)[:160]}" if cause else "missing ACK"
        super().__init__(
            f"order submit uncertain stage={stage} symbol={symbol} "
            f"coids={','.join(uncertain_ids) or 'missing'} cause={cause_text}"
        )

    def to_queue_fields(self) -> dict[str, Any]:
        """JSON-safe fields for ``pending_retries.jsonl`` hand-off."""
        partial_order_id = None
        if self.partial_order:
            partial_order_id = self.partial_order.get("id")
        return {
            "uncertain_client_order_ids": list(self.uncertain_client_order_ids),
            "submit_uncertainty": {
                "stage": self.stage,
                "main_client_order_id": self.main_client_order_id,
                "fallback_client_order_id": self.fallback_client_order_id,
                "partial_order_id": str(partial_order_id or "") or None,
                "partial_qty": self.partial_qty,
                "remaining_qty": self.remaining_qty,
            },
        }


def _exception_mro_names(exc: BaseException) -> set[str]:
    return {cls.__name__ for cls in type(exc).__mro__}


def _exchange_error_code(exc: BaseException) -> int | None:
    for value in (getattr(exc, "code", None), getattr(exc, "error_code", None)):
        try:
            return int(value)
        except (TypeError, ValueError):
            pass
    text = str(exc)
    for code in (-5022, -1007):
        if str(code) in text:
            return code
    return None


def _is_definitive_submit_rejection(exc: BaseException) -> bool:
    """True only when an exchange response proves no order was accepted."""
    names = _exception_mro_names(exc)
    if names & {
        "InvalidOrder",
        "BadRequest",
        "InsufficientFunds",
        "AuthenticationError",
        "PermissionDenied",
    }:
        return True
    return _exchange_error_code(exc) == -5022


def _is_definitive_post_only_rejection(exc: BaseException) -> bool:
    """Binance post-only cross reject; this one may safely use market fallback."""
    text = str(exc).lower()
    return _exchange_error_code(exc) == -5022 or any(
        marker in text
        for marker in (
            "post only order will be rejected",
            "post-only order will be rejected",
            "would immediately match and take",
        )
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


def _positive_float(value: Any) -> float | None:
    """Return a finite positive float, otherwise ``None``."""
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) and parsed > 0 else None


def _extract_fill_evidence(order: dict[str, Any] | None) -> dict[str, Any]:
    """Extract exchange-backed fill qty/notional/average from a CCXT order.

    Binance futures can expose the same facts either in normalized CCXT fields
    (``filled``, ``cost``, ``average``) or in raw ``info`` fields
    (``executedQty``, ``cumQuote``, ``avgPrice``).  ``price`` is deliberately
    excluded: for a market order it is often zero/None and for a limit order it
    is the requested limit, not proof of the realized average.
    """
    payload = order if isinstance(order, dict) else {}
    raw_info = payload.get("info")
    info = raw_info if isinstance(raw_info, dict) else {}

    qty = None
    qty_source = None
    for source, value in (
        ("filled", payload.get("filled")),
        ("info.executedQty", info.get("executedQty")),
        ("info.cumQty", info.get("cumQty")),
    ):
        qty = _positive_float(value)
        if qty is not None:
            qty_source = source
            break

    notional = None
    notional_source = None
    for source, value in (
        ("cost", payload.get("cost")),
        ("info.cumQuote", info.get("cumQuote")),
        ("info.cummulativeQuoteQty", info.get("cummulativeQuoteQty")),
        ("info.cumulativeQuoteQty", info.get("cumulativeQuoteQty")),
        ("info.quoteQty", info.get("quoteQty")),
    ):
        notional = _positive_float(value)
        if notional is not None:
            notional_source = source
            break

    average = None
    average_source = None
    for source, value in (
        ("average", payload.get("average")),
        ("info.avgPrice", info.get("avgPrice")),
    ):
        average = _positive_float(value)
        if average is not None:
            average_source = source
            break

    if average is None and qty is not None and notional is not None:
        average = notional / qty
        average_source = f"{notional_source}/{qty_source}"
    if notional is None and qty is not None and average is not None:
        notional = qty * average
        notional_source = f"{qty_source}*{average_source}"

    return {
        "qty": qty,
        "qty_source": qty_source,
        "notional": notional,
        "notional_source": notional_source,
        "average": average,
        "average_source": average_source,
        "price_verified": average is not None,
        "qty_verified": qty is not None,
        "notional_verified": notional is not None,
    }


def _reconcile_order_fill(
    exchange: Any,
    order: dict[str, Any],
    symbol: str,
    *,
    require_qty: bool,
    max_fetches: int = _FILL_RECONCILE_MAX_FETCHES,
    delay_sec: float = _FILL_RECONCILE_DELAY_SEC,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Bounded delayed refresh until actual fill price evidence is available."""
    current = dict(order)
    evidence = _extract_fill_evidence(current)

    def _complete() -> bool:
        return bool(evidence["price_verified"] and (evidence["qty_verified"] or not require_qty))

    order_id = str(current.get("id") or "")
    if _complete() or not order_id:
        return current, evidence

    fetch_errors = 0
    last_error: str | None = None
    for attempt in range(max(0, max_fetches)):
        if attempt > 0 and delay_sec > 0:
            time.sleep(delay_sec)
        try:
            fresh = exchange.fetch_order(order_id, symbol)
            if isinstance(fresh, dict):
                current.update(fresh)
                evidence = _extract_fill_evidence(current)
                if _complete():
                    break
        except Exception as exc:
            fetch_errors += 1
            last_error = str(exc)[:120]

    if not _complete():
        _MOD_LOG.error(
            "post_only_router.fill_reconcile_unverified %s id=%s fetch_errors=%d last_error=%s",
            symbol,
            order_id,
            fetch_errors,
            last_error,
        )
    return current, evidence


def _clear_unverified_price_fields(order: dict[str, Any]) -> None:
    """Prevent downstream ``average or price`` chains from inventing a fill."""
    if order.get("price") is not None:
        order["exchange_reported_price"] = order.get("price")
    if order.get("cost") is not None:
        order["exchange_reported_cost"] = order.get("cost")
    order["average"] = None
    order["price"] = None
    order["cost"] = None


def _finalize_post_only_fill(
    order: dict[str, Any],
    evidence: dict[str, Any],
    *,
    side: str,
    arrival_px: float,
    requested_qty: float,
    order_id: str,
) -> dict[str, Any]:
    """Attach the same verified fill/leg contract used by mixed fallback fills."""
    finalized = dict(order)
    actual_qty = evidence.get("qty")
    owned_qty = float(actual_qty or finalized.get("filled") or requested_qty)
    fill_px = evidence.get("average") if evidence.get("price_verified") else None
    fill_notional = evidence.get("notional") if evidence.get("notional_verified") else None
    fill_verified = fill_px is not None
    slip_bps = _compute_slippage_bps(side, arrival_px, float(fill_px)) if fill_verified else None

    finalized["filled"] = owned_qty
    finalized["average"] = float(fill_px) if fill_verified else None
    if fill_verified and fill_notional is not None:
        finalized["cost"] = float(fill_notional)
    elif not fill_verified:
        _clear_unverified_price_fields(finalized)
    finalized["partial_limit_qty"] = owned_qty
    finalized["partial_limit_average"] = float(fill_px) if fill_verified else None
    finalized["partial_limit_notional"] = (
        float(fill_notional) if fill_notional is not None else None
    )
    finalized["partial_limit_order_id"] = order_id
    finalized["market_fallback_qty"] = 0.0
    finalized["market_fallback_average"] = None
    finalized["market_fallback_notional"] = None
    finalized["market_fallback_order_id"] = None
    finalized["fill_price_verified"] = fill_verified
    finalized["fill_quantity_verified"] = bool(evidence.get("qty_verified"))
    finalized["slippage_verified"] = fill_verified
    finalized["slippage_bps"] = slip_bps
    finalized["fill_reconciliation_status"] = "verified" if fill_verified else "unverified"
    return finalized


def _fallback_client_order_id(client_order_id: str | None) -> str | None:
    """Build a deterministic Binance-safe fallback id ending in ``_fb``."""
    if not client_order_id:
        return None
    suffix = "_fb"
    direct = client_order_id + suffix
    if len(direct) <= _BINANCE_CLIENT_ORDER_ID_MAX_LEN:
        return direct
    digest = hashlib.sha256(client_order_id.encode("utf-8")).hexdigest()[:6]
    prefix_len = _BINANCE_CLIENT_ORDER_ID_MAX_LEN - len(suffix) - len(digest) - 1
    return f"{client_order_id[:prefix_len]}_{digest}{suffix}"


def _wait_for_fill(
    exchange: Any, order_id: str, symbol: str, timeout_sec: int, poll_interval: float = 1.0
) -> str:
    """Order durumunu poll et. closed/filled/canceled doner.

    Returns: order status string ('closed', 'open', 'canceled', vb.)
    """
    t0 = time.time()
    last_status = "open"
    # #10: poll hataları YUTULMAZ — timeout sonunda tek özet log (s-başına spam yok)
    n_polls = 0
    n_errs = 0
    last_err: str | None = None
    while time.time() - t0 < timeout_sec:
        n_polls += 1
        try:
            o = exchange.fetch_order(order_id, symbol)
            last_status = str(o.get("status", "open"))
            if last_status in ("closed", "filled", "canceled"):
                return last_status
        except Exception as exc:
            n_errs += 1
            last_err = str(exc)[:120]
        time.sleep(poll_interval)
    if n_errs:
        _MOD_LOG.warning(
            "post_only_router.poll_summary %s id=%s: %d deneme, %d hata, son_hata=%s",
            symbol,
            order_id,
            n_polls,
            n_errs,
            last_err,
        )
    return last_status


def _maker_limit_price(
    exchange: Any,
    symbol: str,
    side: str,
    target_price: float,
    best_bid: float | None,
    best_ask: float | None,
) -> float:
    """Post-only maker limit fiyatı — market'i cross ETMEYEN passive fiyat.

    FIX 2026-07-10 (maker kalibrasyonu): eskiden post-only limit target_price'a
    (=last-trade fiyatı) konuyordu — passive offset YOK → yarı zaman book'u cross
    → Binance -5022 reject → taker fallback (maker payı ~%21). Passive tarafa koy:
      buy  → best_bid  (< best_ask, cross etmez)
      sell → best_ask  (> best_bid)
    tick'e yuvarla. bid/ask eksik/geçersiz/ters (stale) → target_price'a döner
    (eski davranış = SIFIR regresyon; cross olursa -5022 → market fallback, drop yok).
    ÖNEMLİ: slippage baseline DEĞİL — çağıran target_price'ı ayrı gate baseline
    olarak korur; buraya maker fiyatı geçilirse 25bps kapı kendini baypas eder.
    """
    try:
        bid = float(best_bid) if best_bid is not None else 0.0
        ask = float(best_ask) if best_ask is not None else 0.0
    except (TypeError, ValueError):
        return target_price
    if bid <= 0 or ask <= 0 or bid >= ask:
        return target_price  # geçersiz/ters/stale book → güvenli fallback
    px = bid if side.lower() in ("buy", "long") else ask
    try:
        return float(exchange.price_to_precision(symbol, px))
    except Exception:
        return px


def place_post_only_with_fallback(
    exchange: Any,
    symbol: str,
    side: str,
    qty: float,
    target_price: float,
    *,
    best_bid: float | None = None,
    best_ask: float | None = None,
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
        method_str: 'post_only_filled' | 'market_fallback' |
            'market_fallback_slippage_breach_protect'
    """
    params: dict[str, Any] = {}
    if client_order_id:
        params["newClientOrderId"] = client_order_id

    # FIX 2026-07-07 (denetim CRIT-1): post-only KISMİ dolum takibi.
    # Eskiden partial fill görünmezdi → market fallback FULL qty gönderiyordu
    # → pozisyon risk-boyutundan büyük (overfill) + journal qty-drift.
    partial_filled = 0.0
    partial_limit_evidence: dict[str, Any] | None = None

    # ===== FAZ 1: Post-only limit =====
    # Maker limit fiyatı: cross etmeyen passive fiyat (bid/ask verildiyse; yoksa
    # target_price = eski davranış). Slippage baseline target_price'da DEĞİŞMEDEN kalır.
    _maker_px = _maker_limit_price(exchange, symbol, side, target_price, best_bid, best_ask)
    post_only_params = {**params, "timeInForce": "PO", "postOnly": True}
    order_id: str | None = None
    fb_client_id = _fallback_client_order_id(client_order_id)
    try:
        order = exchange.create_order(
            symbol=symbol,
            type="limit",
            side=side,
            amount=qty,
            price=_maker_px,
            params=post_only_params,
        )
        order_id = str(order.get("id", ""))
    except Exception as _po_err:
        # Yalniz exchange'in kesin -5022/cross reject cevabi market fallback'e
        # izin verir. Timeout/network/generic hata "emir yok" demek degildir.
        _MOD_LOG.warning(
            "post_only_router.phase1_reject",
            extra={"symbol": symbol, "err": str(_po_err)[:160]},
        )
        if _is_definitive_post_only_rejection(_po_err):
            order = None
            order_id = None
        elif _is_definitive_submit_rejection(_po_err):
            raise
        else:
            raise OrderSubmissionUncertainError(
                stage="post_only_limit_submit",
                symbol=symbol,
                side=side,
                main_client_order_id=client_order_id,
                fallback_client_order_id=fb_client_id,
                partial_order=None,
                partial_qty=0.0,
                remaining_qty=qty,
                cause=_po_err,
            ) from _po_err

    if order is not None and not order_id:
        ack_evidence = _extract_fill_evidence(order)
        ack_qty = float(ack_evidence.get("qty") or 0.0)
        raise OrderSubmissionUncertainError(
            stage="post_only_limit_submit",
            symbol=symbol,
            side=side,
            main_client_order_id=client_order_id,
            fallback_client_order_id=fb_client_id,
            partial_order=order,
            partial_qty=ack_qty,
            remaining_qty=max(qty - ack_qty, 0.0),
        )

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
            # Kesin fill detayı gecikmeli gelebilir; tek fetch sonrası target/
            # limit price'a düşme. Market fallback ile aynı bounded reconcile
            # ve verified/unverified metadata sözleşmesini döndür.
            final = dict(order or {})
            try:
                fresh_final = exchange.fetch_order(order_id, symbol)
                if isinstance(fresh_final, dict):
                    final.update(fresh_final)
            except Exception as _ff_err:
                _MOD_LOG.warning(
                    "post_only_router.final_fetch_fail_stale_order",
                    extra={"symbol": symbol, "order_id": order_id, "err": str(_ff_err)[:120]},
                )
            final, final_evidence = _reconcile_order_fill(
                exchange,
                final,
                symbol,
                require_qty=True,
            )
            return (
                _finalize_post_only_fill(
                    final,
                    final_evidence,
                    side=side,
                    arrival_px=target_price,
                    requested_qty=qty,
                    order_id=order_id,
                ),
                "post_only_filled",
            )

        # Timeout -> cancel (FIX 2026-05-28 (Faz 14.27 C3-1) — atomic guard)
        # Önceki bug: cancel fail (network/exchange) → market fallback yine submit
        # → double position (limit + market ikisi de fill olabilir).
        # Şimdi: cancel sonrası order_status fetch et, gerçekten kapanmadıysa
        # market fallback ATLA + push_critical.
        cancel_ok = False
        cancel_result: dict[str, Any] | None = None
        try:
            raw_cancel_result = exchange.cancel_order(order_id, symbol)
            if isinstance(raw_cancel_result, dict):
                cancel_result = raw_cancel_result
            cancel_ok = True
        except Exception as _cnc_exc:
            try:
                import logging as _lg

                _lg.getLogger(__name__).warning(
                    "post_only_router.cancel_fail",
                    extra={"symbol": symbol, "order_id": order_id, "err": str(_cnc_exc)[:200]},
                )
            except Exception:
                pass

        # Cancel sonrası order status doğrula — race condition guard.
        # Salt cancel ACK yeterli değil: fetch hala OPEN/UNKNOWN diyorsa limit
        # yaşıyor olabilir ve market fallback pozisyonu ikiye katlar.
        cancel_terminal = False
        verify: dict[str, Any] | None = None
        try:
            fetched_verify = exchange.fetch_order(order_id, symbol)
            if isinstance(fetched_verify, dict):
                verify = fetched_verify
        except Exception as _vf_err:
            # fetch geçici olarak yoksa ancak cancel_order cevabı terminal bir
            # order snapshot'ı taşıyorsa onu kanıt say. None/salt ACK belirsizdir.
            cancel_status = str((cancel_result or {}).get("status", "")).lower()
            if cancel_status in ("canceled", "cancelled", "expired", "rejected"):
                verify = cancel_result
            _MOD_LOG.warning(
                "post_only_router.verify_fail",
                extra={"symbol": symbol, "order_id": order_id, "err": str(_vf_err)[:120]},
            )

        if verify is not None:
            v_status = str(verify.get("status", "")).lower()
            if v_status in ("closed", "filled"):
                # Cancel race — order tam o anda fill oldu → market submit etme!
                late_order, late_evidence = _reconcile_order_fill(
                    exchange,
                    verify,
                    symbol,
                    require_qty=True,
                )
                return (
                    _finalize_post_only_fill(
                        late_order,
                        late_evidence,
                        side=side,
                        arrival_px=target_price,
                        requested_qty=qty,
                        order_id=order_id,
                    ),
                    "post_only_filled_late",
                )
            cancel_terminal = v_status in ("canceled", "cancelled", "expired", "rejected")
            if cancel_terminal:
                # CRIT-1: iptal edilen limitin dolan kısmı fallback'ten düşülür.
                partial_filled = float(verify.get("filled") or 0.0)
                if partial_filled > 0:
                    _, partial_limit_evidence = _reconcile_order_fill(
                        exchange,
                        verify,
                        symbol,
                        require_qty=True,
                    )
                    partial_filled = float(partial_limit_evidence.get("qty") or partial_filled)

        if not cancel_terminal:
            # Cancel ACK/fail + terminal verify yok → BELİRSİZ STATE.
            # Market YAPMA; gerçek pozisyon sahipliği exchange reconcile'a kalır.
            try:
                from price_action.orchestrator.notifications import push_critical

                push_critical(
                    f"🚨 POST-ONLY CANCEL UNVERIFIED — {symbol} {side} qty={qty} "
                    f"order_id={order_id}. Market fallback ATLANDI (double position riski). "
                    f"cancel_ack={cancel_ok}. MANUEL kontrol et exchange'de bu order'ı.",
                    source="post_only_router_cancel",
                )
            except Exception:
                pass
            ambiguous_order = verify if isinstance(verify, dict) else order
            ambiguous_evidence = _extract_fill_evidence(ambiguous_order)
            ambiguous_qty = float(ambiguous_evidence.get("qty") or 0.0)
            raise OrderSubmissionUncertainError(
                stage="post_only_cancel_verify",
                symbol=symbol,
                side=side,
                main_client_order_id=client_order_id,
                fallback_client_order_id=fb_client_id,
                partial_order=ambiguous_order,
                partial_qty=ambiguous_qty,
                remaining_qty=max(qty - ambiguous_qty, 0.0),
            )

    # ===== FAZ 3: Market fallback =====
    # CRIT-1 fix: kısmi dolum düşülür — sadece KALAN miktar market'e gider.
    fb_qty = qty
    if partial_filled > 0:
        fb_qty = max(qty - partial_filled, 0.0)
        try:
            fb_qty = float(exchange.amount_to_precision(symbol, fb_qty))
        except Exception as _pr_err:
            # log-only: precision fail → yuvarlanmamış qty ile devam (borsa
            # -1111 ile reddederse zaten görünür); artık teşhis edilebilir.
            _MOD_LOG.warning(
                "post_only_router.fb_qty_precision_fail",
                extra={"symbol": symbol, "fb_qty": fb_qty, "err": str(_pr_err)[:120]},
            )
        if fb_qty <= 0 or (partial_filled / max(qty, 1e-12)) >= 0.999:
            # Fiilen tamamı dolmuş — partial'ı geç-fill olarak dön, market YAPMA.
            complete_evidence = partial_limit_evidence or _extract_fill_evidence(verify)
            return (
                _finalize_post_only_fill(
                    verify,
                    complete_evidence,
                    side=side,
                    arrival_px=target_price,
                    requested_qty=qty,
                    order_id=order_id or "",
                ),
                "post_only_filled_late",
            )
        try:
            import logging as _lg

            _lg.getLogger(__name__).info(
                "post_only_router.partial_fill_deducted",
                extra={"symbol": symbol, "partial": partial_filled, "fb_qty": fb_qty},
            )
        except Exception:
            pass

    fb_params = {"newClientOrderId": fb_client_id} if fb_client_id else {}
    try:
        market_order = exchange.create_market_order(
            symbol=symbol,
            side=side,
            amount=fb_qty,
            params=fb_params,
        )
    except Exception as _market_err:
        if _is_definitive_submit_rejection(_market_err):
            raise
        raise OrderSubmissionUncertainError(
            stage="market_fallback_submit",
            symbol=symbol,
            side=side,
            main_client_order_id=client_order_id,
            fallback_client_order_id=fb_client_id,
            partial_order=verify if partial_filled > 0 else None,
            partial_qty=partial_filled,
            remaining_qty=fb_qty,
            cause=_market_err,
        ) from _market_err
    if not isinstance(market_order, dict) or not market_order.get("id"):
        ack_order = market_order if isinstance(market_order, dict) else None
        ack_evidence = _extract_fill_evidence(ack_order)
        ack_qty = float(ack_evidence.get("qty") or 0.0)
        raise OrderSubmissionUncertainError(
            stage="market_fallback_submit",
            symbol=symbol,
            side=side,
            main_client_order_id=client_order_id,
            fallback_client_order_id=fb_client_id,
            partial_order=verify if partial_filled > 0 else ack_order,
            partial_qty=partial_filled,
            remaining_qty=max(fb_qty - ack_qty, 0.0),
        )

    # ===== FAZ 4: Fill reconciliation + total-position slippage gate =====
    # Binance market-order ack'i avgPrice/cumQuote bilgisini gecikmeli doldurur.
    # Bounded refresh sonrası bile gerçek notional yoksa target_price'a düşüp
    # sahte 0bps üretme: fiyat/slippage açıkça UNVERIFIED kalsın. Quantity yine
    # sahiplik/koruma için korunur.
    market_order, market_evidence = _reconcile_order_fill(
        exchange,
        market_order,
        symbol,
        require_qty=True,
    )
    market_qty = float(market_evidence.get("qty") or fb_qty)
    total_fill = market_qty + max(partial_filled, 0.0)
    market_avg = market_evidence.get("average")
    market_notional = market_evidence.get("notional")
    limit_avg = partial_limit_evidence.get("average") if partial_limit_evidence else None
    limit_notional = partial_limit_evidence.get("notional") if partial_limit_evidence else None

    if partial_filled > 0:
        fill_verified = bool(
            partial_limit_evidence
            and partial_limit_evidence.get("price_verified")
            and market_evidence.get("price_verified")
            and limit_notional is not None
            and market_notional is not None
            and total_fill > 0
        )
        fill_px = float(limit_notional + market_notional) / total_fill if fill_verified else None
    else:
        fill_verified = bool(market_evidence.get("price_verified"))
        fill_px = float(market_avg) if fill_verified and market_avg is not None else None

    slip_bps = _compute_slippage_bps(side, target_price, fill_px) if fill_px is not None else None
    market_order["filled"] = total_fill
    market_order["average"] = fill_px
    if fill_verified and fill_px is not None:
        market_order["cost"] = fill_px * total_fill
    elif not fill_verified:
        # ``price`` market emrinde gerçek fill kanıtı değildir; downstream
        # ``average or price`` zincirinin bunu gerçek sanmasını engelle.
        if market_order.get("price") is not None:
            market_order["exchange_reported_price"] = market_order.get("price")
        if market_order.get("cost") is not None:
            market_order["exchange_reported_cost"] = market_order.get("cost")
        market_order["price"] = None
        market_order["cost"] = None
    market_order["partial_limit_qty"] = max(partial_filled, 0.0)
    market_order["partial_limit_average"] = limit_avg
    market_order["partial_limit_notional"] = limit_notional
    market_order["partial_limit_order_id"] = order_id if partial_filled > 0 else None
    market_order["market_fallback_qty"] = market_qty
    market_order["market_fallback_average"] = market_avg
    market_order["market_fallback_notional"] = market_notional
    market_order["market_fallback_order_id"] = market_order.get("id")
    market_order["fill_price_verified"] = fill_verified
    market_order["fill_quantity_verified"] = bool(
        market_evidence.get("qty_verified")
        and (
            partial_filled <= 0
            or (partial_limit_evidence and partial_limit_evidence.get("qty_verified"))
        )
    )
    market_order["slippage_verified"] = fill_verified
    market_order["slippage_bps"] = slip_bps
    market_order["fill_reconciliation_status"] = "verified" if fill_verified else "unverified"

    if not fill_verified:
        _MOD_LOG.error(
            "post_only_router.total_fill_price_unverified",
            extra={
                "symbol": symbol,
                "partial_qty": partial_filled,
                "market_qty": market_qty,
                "order_id": market_order.get("id"),
            },
        )

    if slip_bps is not None and slip_bps > slippage_limit_bps:
        # The fallback already owns a fill.  A second, best-effort market order
        # is not a crash-safe unwind: an ACK does not prove flatness, a timeout
        # may still have filled, and retrying can flip the position.  Preserve
        # ownership and hand the exact fill to the caller's durable SL-first
        # protection path instead.
        breach = {
            "schema_version": 1,
            "outcome_type": "slippage_breach",
            "disposition": SlippageBreachDisposition.PROTECT_POSITION.value,
            "terminal": False,
            "position_owned": True,
            "protection_required": True,
            "unwind_attempted": False,
            "symbol": symbol,
            "entry_side": str(side).lower(),
            "owned_quantity": float(total_fill),
            "owned_average": float(fill_px),
            "target_price": float(target_price),
            "slippage_bps": float(slip_bps),
            "limit_bps": float(slippage_limit_bps),
            "fill_evidence_verified": bool(fill_verified),
            "partial_limit_order_id": market_order.get("partial_limit_order_id"),
            "market_fallback_order_id": market_order.get("market_fallback_order_id")
            or market_order.get("id"),
        }
        market_order["slippage_breach"] = breach
        _MOD_LOG.warning(
            "post_only_router.slippage_breach_position_owned",
            extra=breach,
        )
        return market_order, "market_fallback_slippage_breach_protect"

    return market_order, "market_fallback"
