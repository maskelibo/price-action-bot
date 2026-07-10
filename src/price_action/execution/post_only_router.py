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

import logging as _logging
import time
from datetime import UTC
from typing import Any

_MOD_LOG = _logging.getLogger(__name__)


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
        method_str: 'post_only_filled' | 'market_fallback'

    Raises:
        SlippageExceededError: Market fallback slippage > limit -> ters-kapatildi.
    """
    params: dict[str, Any] = {}
    if client_order_id:
        params["newClientOrderId"] = client_order_id

    # FIX 2026-07-07 (denetim CRIT-1): post-only KISMİ dolum takibi.
    # Eskiden partial fill görünmezdi → market fallback FULL qty gönderiyordu
    # → pozisyon risk-boyutundan büyük (overfill) + journal qty-drift.
    partial_filled = 0.0

    # ===== FAZ 1: Post-only limit =====
    # Maker limit fiyatı: cross etmeyen passive fiyat (bid/ask verildiyse; yoksa
    # target_price = eski davranış). Slippage baseline target_price'da DEĞİŞMEDEN kalır.
    _maker_px = _maker_limit_price(exchange, symbol, side, target_price, best_bid, best_ask)
    post_only_params = {**params, "timeInForce": "PO", "postOnly": True}
    order_id: str | None = None
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
        # Post-only reddedildi (market'i cross ediyor olabilir). Direk market fallback.
        # log-only (W2-MED): taker'a düşüş artık görünür (maker-oranı teşhisi için).
        _MOD_LOG.warning(
            "post_only_router.phase1_reject",
            extra={"symbol": symbol, "err": str(_po_err)[:160]},
        )
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
            except Exception as _ff_err:
                # log-only: kesin-detay fetch fail → bayat order objesi döner
                # (eski davranış); artık görünür.
                _MOD_LOG.warning(
                    "post_only_router.final_fetch_fail_stale_order",
                    extra={"symbol": symbol, "order_id": order_id, "err": str(_ff_err)[:120]},
                )
                return order or {}, "post_only_filled"

        # Timeout -> cancel (FIX 2026-05-28 (Faz 14.27 C3-1) — atomic guard)
        # Önceki bug: cancel fail (network/exchange) → market fallback yine submit
        # → double position (limit + market ikisi de fill olabilir).
        # Şimdi: cancel sonrası order_status fetch et, gerçekten kapanmadıysa
        # market fallback ATLA + push_critical.
        cancel_ok = False
        try:
            exchange.cancel_order(order_id, symbol)
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

        # Cancel sonrası order status doğrula — race condition guard
        # Eğer order hala "open" değilse (filled olmuş olabilir), market YAPMA.
        try:
            verify = exchange.fetch_order(order_id, symbol)
            v_status = str(verify.get("status", "")).lower()
            if v_status in ("closed", "filled"):
                # Cancel race — order tam o anda fill oldu → market submit etme!
                return verify, "post_only_filled_late"
            # CRIT-1 fix: iptal edilen limitin dolan kısmı fallback'ten düşülür
            partial_filled = float(verify.get("filled") or 0.0)
        except Exception as _vf_err:
            # log-only: verify fail → partial_filled=0 varsayımıyla devam (eski
            # davranış — kısmi dolum varsa fallback tam-qty atar); artık görünür.
            _MOD_LOG.warning(
                "post_only_router.verify_fail",
                extra={"symbol": symbol, "order_id": order_id, "err": str(_vf_err)[:120]},
            )

        if not cancel_ok:
            # Cancel fail + verify de fail → BELİRSİZ STATE. Market YAPMA, alarm.
            try:
                from price_action.orchestrator.notifications import push_critical

                push_critical(
                    f"🚨 POST-ONLY CANCEL FAIL — {symbol} {side} qty={qty} "
                    f"order_id={order_id}. Market fallback ATLANDI (double position riski). "
                    f"MANUEL kontrol et exchange'de bu order'ı.",
                    source="post_only_router_cancel",
                )
            except Exception:
                pass
            raise RuntimeError(
                f"post_only cancel ambiguous: {symbol} order_id={order_id} — manual check"
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
            return verify, "post_only_filled_late"
        try:
            import logging as _lg

            _lg.getLogger(__name__).info(
                "post_only_router.partial_fill_deducted",
                extra={"symbol": symbol, "partial": partial_filled, "fb_qty": fb_qty},
            )
        except Exception:
            pass

    fb_client_id = (client_order_id + "_fb") if client_order_id else None
    fb_params = {"newClientOrderId": fb_client_id} if fb_client_id else {}
    market_order = exchange.create_market_order(
        symbol=symbol,
        side=side,
        amount=fb_qty,
        params=fb_params,
    )

    # ===== FAZ 4: Slippage gate (market fallback) =====
    # HIGH-7 fix (2026-07-07): Binance market yanıtında average sık None gelir
    # → eski fallback zinciri fill_px=target yapıp slippage'ı 0 gösteriyordu
    # (kapı kendi kendini baypas ediyordu). Önce fetch_order ile tazele.
    fill_px = float(market_order.get("average") or 0.0)
    if fill_px <= 0:
        try:
            _mk_fresh = exchange.fetch_order(str(market_order.get("id", "")), symbol)
            fill_px = float(_mk_fresh.get("average") or 0.0)
            if float(_mk_fresh.get("filled") or 0.0) > 0:
                market_order = _mk_fresh
        except Exception as _fr_err:
            # log-only (HIGH-7 tazeleme adımı): refresh fail → fill_px price/
            # target fallback'ına düşer (eski davranış); artık görünür.
            _MOD_LOG.warning(
                "post_only_router.fill_refresh_fail",
                extra={"symbol": symbol, "err": str(_fr_err)[:120]},
            )
    if fill_px <= 0:
        fill_px = float(market_order.get("price") or target_price)
    slip_bps = _compute_slippage_bps(side, target_price, fill_px)

    if slip_bps > slippage_limit_bps:
        # Ters-kapat: ayni qty market order, opposite side
        # FIX 2026-05-28 (Faz 14.27 C3-2): Önceki bug — reverse close fail
        # ise silent except, pozisyon ACIK kalıyordu, no Telegram alert.
        # Şimdi: structured log + push_critical orphan tracking.
        rev_side = opposite_side(side)
        rev_ok = False
        rev_err: str | None = None
        try:
            exchange.create_market_order(
                symbol=symbol,
                side=rev_side,
                amount=qty,
                params={"reduceOnly": True} if hasattr(exchange, "options") else {},
            )
            rev_ok = True
        except Exception as _rev_exc:
            rev_err = f"{type(_rev_exc).__name__}: {str(_rev_exc)[:200]}"

        if not rev_ok:
            # KRITIK: pozisyon orphan kaldı, Principal'a CRIT push
            try:
                import logging as _lg

                _log = _lg.getLogger(__name__)
                _log.error(
                    "post_only_router.reverse_close_FAIL — ORPHAN POSITION",
                    extra={
                        "symbol": symbol,
                        "side": side,
                        "qty": qty,
                        "fill_px": fill_px,
                        "target_px": target_price,
                        "slip_bps": slip_bps,
                        "limit_bps": slippage_limit_bps,
                        "rev_err": rev_err,
                    },
                )
            except Exception:
                pass
            try:
                from price_action.orchestrator.notifications import push_critical

                push_critical(
                    f"🚨 ORPHAN POSITION — {symbol} {side} qty={qty} fill=${fill_px} "
                    f"(slip={slip_bps:.0f}bps > limit={slippage_limit_bps:.0f}bps). "
                    f"Reverse close FAILED: {rev_err}. MANUEL kapat.",
                    source="post_only_router_slip",
                )
            except Exception:
                pass
            # Orphan tracking — disk'e yaz reconciler tarafından okunabilsin
            try:
                import json as _json
                from datetime import datetime as _dt
                from pathlib import Path

                orphan_path = Path("data/orphan_positions.jsonl")
                orphan_path.parent.mkdir(parents=True, exist_ok=True)
                with open(orphan_path, "a", encoding="utf-8") as _f:
                    _f.write(
                        _json.dumps(
                            {
                                "ts": _dt.now(UTC).isoformat(),
                                "symbol": symbol,
                                "side": side,
                                "qty": qty,
                                "fill_px": fill_px,
                                "slip_bps": slip_bps,
                                "rev_err": rev_err,
                            }
                        )
                        + "\n"
                    )
            except Exception as _oj_err:
                # log-only: ORPHAN devir-dosyası (reconciler okur) yazılamadı —
                # sessiz kalırsa orphan takipsiz kalırdı; artık görünür.
                _MOD_LOG.error(
                    "post_only_router.orphan_jsonl_write_fail",
                    extra={"symbol": symbol, "err": str(_oj_err)[:120]},
                )

        raise SlippageExceededError(slip_bps, slippage_limit_bps, symbol=symbol)

    # CRIT-1 fix: kısmi limit dolumu + market kalanı → çağırana TOPLAM yansıt
    # (aksi halde journal/koruma emirleri sadece market bacağını boyutlar,
    # limit bacağı korumasız kalırdı). average = ağırlıklı ortalama.
    if partial_filled > 0:
        try:
            mk_fill = float(market_order.get("filled") or fb_qty)
            total_fill = mk_fill + partial_filled
            w_avg = ((fill_px * mk_fill) + (target_price * partial_filled)) / max(total_fill, 1e-12)
            market_order["filled"] = total_fill
            market_order["average"] = w_avg
            market_order["partial_limit_qty"] = partial_filled
        except Exception as _bl_err:
            # log-only: blend fail → yalnız market bacağı raporlanır (limit
            # bacağı koruma-boyutundan düşer — CRIT-1 sınıfı); artık görünür.
            _MOD_LOG.error(
                "post_only_router.partial_blend_fail",
                extra={"symbol": symbol, "partial": partial_filled, "err": str(_bl_err)[:120]},
            )

    return market_order, "market_fallback"
