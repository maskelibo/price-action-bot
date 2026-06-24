"""PyramidRouter — Piramit pozisyon leg yönetimi (SEC54.3).

Lab.py'de backtest muhasebesi olarak var olan pyramid mantığını canlı execution'a
taşır. Tek-leg pozisyon flow'unu kırmaz — opt-in flag ile aktif edilir.

Tasarım prensipleri:
  - Idempotency-strict: client_order_id PA_{fp[:12]}_L{n} restart'a dayanıklı.
  - Slippage-obsessed: SEC26.B-5 post_only_router kullanır, yeniden yazmaz.
  - Backward compat: pyramid_router OPT-IN; mevcut tek-leg flow dokunulmaz.
  - No silent fail: exception log + re-raise (caller karar verir).
  - SL-first: SL tetiklenince tüm PENDING/SUBMITTED leg'ler iptal.

Kullanım:
    from price_action.execution.pyramid_router import PyramidRouter, PyramidPosition, PyramidLeg
    router = PyramidRouter(exchange, idempotency_store, slippage_tracker)
    router.on_position_check(position, current_price, ts)

Config (YAML pyramid block):
    pyramid_triggers: [1.0, 1.5]   # R katı tetik noktaları
    pyramid_sizes:    [0.50, 0.30] # leg-1 boyutunun oranı

Leg numaralandırma:
    Leg-1: Entry (scanner/router tarafından yerleştirildi, bu modül görmez)
    Leg-2: pyramid_triggers[0]=1.0R tetiklenince
    Leg-3: pyramid_triggers[1]=1.5R tetiklenince

KRITIK KISITLAR:
  - PA_LIVE_CONFIRM olmadan live order atılmaz (caller'ın sorumluluğu).
  - Bu modül sadece kod + unit test sprinti (SEC54.3). Testnet smoke SEC54.4.
"""
from __future__ import annotations

import logging
import sys
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Literal, Optional

if TYPE_CHECKING:
    from price_action.execution.idempotency import IdempotencyStore
    from price_action.execution.slippage_tracker import SlippageTracker

# Modül namespace'ine al: testler patch edebilsin, lazy import yerine.
try:
    from price_action.execution.post_only_router import (
        SlippageExceededError,
        place_post_only_with_fallback,
    )
    _POST_ONLY_AVAILABLE = True
except ImportError:  # pragma: no cover
    _POST_ONLY_AVAILABLE = False
    SlippageExceededError = Exception  # type: ignore[misc,assignment]

    def place_post_only_with_fallback(*args, **kwargs):  # type: ignore[misc]
        raise RuntimeError("post_only_router not available")

log = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Data structures
# ─────────────────────────────────────────────────────────────────────────────

LegState = Literal["PENDING", "SUBMITTED", "FILLED", "CANCELED", "REJECTED"]
PositionSide = Literal["LONG", "SHORT"]


@dataclass
class PyramidLeg:
    """Bir pyramid leg'inin yaşam döngüsü."""

    leg_num: int                        # 1=entry, 2=ilk pyramid, 3=ikinci pyramid
    leg_state: LegState
    leg_qty: float                      # işlem miktarı (base asset)
    leg_price: float                    # tetik fiyatı (trigger / fill ref)
    client_order_id: str                # PA_{fp[:12]}_L{n}
    submitted_at: Optional[datetime] = None
    filled_at: Optional[datetime] = None
    exchange_order_id: Optional[str] = None
    fill_price: Optional[float] = None  # gerçek fill fiyatı (log + slippage)


@dataclass
class PyramidPosition:
    """Bir pozisyona ait tüm leg durumu + konfigürasyonu."""

    parent_position_id: str             # sinyal fingerprint (ilk leg ile aynı)
    symbol: str
    side: PositionSide
    entry_price: float                  # leg-1 fill fiyatı
    sl_price: float
    initial_R: float                    # 1R mesafesi = |entry_price - sl_price|
    legs: list[PyramidLeg]             # indeks 0 = leg-1 (entry)
    pyramid_triggers: list[float]       # örn. [1.0, 1.5] R katları
    pyramid_sizes: list[float]          # örn. [0.50, 0.30] (leg-1 qty oranı)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False, compare=False)

    # ── Yardımcılar ──────────────────────────────────────────────────────────

    @property
    def entry_qty(self) -> float:
        """Leg-1 miktarı (pyramid boyutu referansı)."""
        if not self.legs:
            return 0.0
        return self.legs[0].leg_qty

    def leg_for_num(self, leg_num: int) -> Optional[PyramidLeg]:
        for lg in self.legs:
            if lg.leg_num == leg_num:
                return lg
        return None

    def sl_hit(self, current_price: float) -> bool:
        """SL tetiklenme kontrolü — yön duyarlı."""
        if self.side == "LONG":
            return current_price <= self.sl_price
        else:  # SHORT
            return current_price >= self.sl_price

    def trigger_price_for_leg(self, leg_num: int) -> Optional[float]:
        """Leg numarasına karşılık gelen tetik fiyatını hesapla.

        Leg-2 → pyramid_triggers[0], Leg-3 → pyramid_triggers[1]
        """
        idx = leg_num - 2  # leg-2 → idx 0
        if idx < 0 or idx >= len(self.pyramid_triggers):
            return None
        r_mult = self.pyramid_triggers[idx]
        if self.side == "LONG":
            return self.entry_price + r_mult * self.initial_R
        else:
            return self.entry_price - r_mult * self.initial_R

    def trigger_reached(self, leg_num: int, current_price: float) -> bool:
        """Tetik fiyatına ulaşıldı mı?"""
        trig = self.trigger_price_for_leg(leg_num)
        if trig is None:
            return False
        if self.side == "LONG":
            return current_price >= trig
        else:
            return current_price <= trig

    def leg_qty_for_num(self, leg_num: int) -> float:
        """Leg-n için hedef miktar: entry_qty × pyramid_sizes[n-2]."""
        idx = leg_num - 2
        if idx < 0 or idx >= len(self.pyramid_sizes):
            return 0.0
        return self.entry_qty * self.pyramid_sizes[idx]


# ─────────────────────────────────────────────────────────────────────────────
# PyramidRouter
# ─────────────────────────────────────────────────────────────────────────────


class PyramidRouter:
    """Position monitor loop'tan çağrılan pyramid leg yöneticisi.

    Args:
        exchange: ccxt-compatible nesne (create_order, cancel_order, fetch_order,
                  create_market_order).
        idempotency_store: IdempotencyStore (DuckDB persist, restart-safe).
        slippage_tracker: SlippageTracker (fill-level journal).
        post_only_enabled: True → SEC26.B-5 post_only_router. False → market order.
        fallback_seconds: post-only timeout (default 30).
        slippage_limit_bps: market fallback slippage cap (default 25).
        mode: 'backtest' | 'paper' | 'live' (telemetri için, emir davranışını değiştirmez).
    """

    def __init__(
        self,
        exchange: Any,
        idempotency_store: "IdempotencyStore",
        slippage_tracker: "SlippageTracker",
        *,
        post_only_enabled: bool = True,
        fallback_seconds: int = 30,
        slippage_limit_bps: float = 25.0,
        mode: str = "paper",
    ) -> None:
        self.exchange = exchange
        self.idempotency = idempotency_store
        self.slippage = slippage_tracker
        self.post_only_enabled = post_only_enabled
        self.fallback_seconds = fallback_seconds
        self.slippage_limit_bps = slippage_limit_bps
        self.mode = mode

    # ── Giriş noktası ────────────────────────────────────────────────────────

    def on_position_check(
        self,
        position: PyramidPosition,
        current_price: float,
        ts: datetime,
    ) -> None:
        """Position monitor loop'tan (60s tick veya bar-close) çağrılır.

        Sıralama:
          1. SL hit → pending leg'leri iptal et, erken çık.
          2. Her pyramid trigger için: önceden işlenmediyse submit_leg.

        Thread-safe: pozisyon başına lock.
        """
        with position._lock:
            # 1. SL hit → orphan cancel
            if position.sl_hit(current_price):
                self._cancel_pending_legs(position, reason="sl_hit")
                return

            # 2. Trigger detection
            for idx, _ in enumerate(position.pyramid_triggers):
                leg_num = idx + 2  # leg-2, leg-3, ...
                if self._leg_already_handled(position, leg_num):
                    continue
                if position.trigger_reached(leg_num, current_price):
                    trig_px = position.trigger_price_for_leg(leg_num)
                    if trig_px is None:
                        continue
                    try:
                        self._submit_leg(position, leg_num, trig_px, ts)
                    except Exception as exc:
                        log.error(
                            "PyramidRouter._submit_leg FAILED: pos=%s leg=%d err=%s",
                            position.parent_position_id,
                            leg_num,
                            exc,
                        )
                        # No silent fail — re-raise. Caller (daemon loop) karar verir.
                        raise

    # ── İç metodlar ──────────────────────────────────────────────────────────

    def _leg_already_handled(self, position: PyramidPosition, leg_num: int) -> bool:
        """Leg daha önce SUBMITTED/FILLED/CANCELED/REJECTED olduysa True."""
        lg = position.leg_for_num(leg_num)
        if lg is None:
            return False  # hiç oluşturulmamış → henüz işlenmedi
        return lg.leg_state in ("SUBMITTED", "FILLED", "CANCELED", "REJECTED")

    def _submit_leg(
        self,
        position: PyramidPosition,
        leg_num: int,
        trigger_price: float,
        ts: datetime,
    ) -> None:
        """Pyramid leg'ini borsaya gönder.

        post_only_enabled=True  → SEC26.B-5 post_only_router (maker rebate, 30s timeout).
        post_only_enabled=False → direkt market order (testnet fallback).

        İdempotency: client_order_id DuckDB'de kayıtlıysa double-submit olmaz.
        """
        size = position.leg_qty_for_num(leg_num)
        if size <= 0:
            log.warning(
                "PyramidRouter: leg-%d qty=%.6f <= 0, skip. pos=%s",
                leg_num, size, position.parent_position_id,
            )
            return

        client_order_id = _make_client_order_id(position.parent_position_id, leg_num)

        # ── Idempotency check ─────────────────────────────────────────────
        if self.idempotency.is_seen(client_order_id):
            # Daha önce submit edildi; leg durumunu SUBMITTED olarak işaretle
            log.info(
                "PyramidRouter: leg-%d idem HIT — already submitted. coid=%s",
                leg_num, client_order_id,
            )
            self._ensure_leg_submitted(position, leg_num, size, trigger_price,
                                       client_order_id, ts)
            return

        # ── Leg oluştur (PENDING) ─────────────────────────────────────────
        leg = _find_or_create_leg(
            position, leg_num, size, trigger_price, client_order_id
        )
        leg.leg_state = "PENDING"

        # ── Borsa'ya gönder ───────────────────────────────────────────────
        order_side = "buy" if position.side == "LONG" else "sell"
        order: dict[str, Any] | None = None

        if self.post_only_enabled:
            try:
                order_dict, method = place_post_only_with_fallback(
                    self.exchange,
                    symbol=position.symbol,
                    side=order_side,
                    qty=size,
                    target_price=trigger_price,
                    client_order_id=client_order_id,
                    fallback_after_sec=self.fallback_seconds,
                    slippage_limit_bps=self.slippage_limit_bps,
                    poll_interval=1.0,
                )
                order = order_dict
            except SlippageExceededError as slip_err:
                leg.leg_state = "REJECTED"
                self.idempotency.mark_rejected(
                    client_order_id,
                    reason=f"slippage_exceeded:{slip_err.slippage_bps:.1f}bps",
                )
                log.error(
                    "PyramidRouter: leg-%d SLIP_EXCEEDED %.1fbps > %.1fbps. pos=%s",
                    leg_num, slip_err.slippage_bps, self.slippage_limit_bps,
                    position.parent_position_id,
                )
                # Telemetri: reverse-close edilen leg'i kaydet (is_maker=False, market)
                # _record_slippage'ı buradan doğrudan çağıramayız — fill_qty/fill_px yok.
                # SlippageTracker'a REJECTED kaydı yazarak kör kalmamasını sağla.
                try:
                    _rej_fill_id = f"pyr_rej_{uuid.uuid4().hex[:12]}"
                    self.slippage.record_fill(
                        fill_id=_rej_fill_id,
                        ts=ts,
                        symbol=position.symbol,
                        strategy=f"pyramid_leg{leg_num}_rejected",
                        side=position.side.lower(),
                        expected_price=trigger_price,
                        realized_price=trigger_price,  # bilinmiyor; beklenen fiyat
                        quantity=size,
                        fee_usdt=0.0,
                        is_maker=False,
                        order_type="slip_exceeded_reverse_close",
                        mode=self.mode,
                        exchange_order_id="",
                        client_order_id=client_order_id,
                        notes=(
                            f"pyramid leg-{leg_num} REJECTED "
                            f"slip={slip_err.slippage_bps:.1f}bps>"
                            f"{self.slippage_limit_bps:.1f}bps "
                            f"pos={position.parent_position_id}"
                        ),
                        tf="15m",
                    )
                except Exception as _tel_err:
                    log.error("PyramidRouter: slip_exceeded telemetry FAIL: %s", _tel_err)
                raise
        else:
            # Market order (testnet / post_only_enabled=False)
            params: dict[str, Any] = {"newClientOrderId": client_order_id}
            order = self.exchange.create_market_order(
                symbol=position.symbol,
                side=order_side,
                amount=size,
                params=params,
            )
            method = "market"  # type: ignore[assignment]

        # ── Idempotency kayıt ─────────────────────────────────────────────
        self.idempotency.mark_submitted(client_order_id, symbol=position.symbol, side=order_side)

        # ── Leg güncelle ──────────────────────────────────────────────────
        leg.leg_state = "SUBMITTED"
        leg.submitted_at = ts

        if order:
            exchange_order_id = str(order.get("id", ""))
            fill_px = float(order.get("average") or order.get("price") or trigger_price)
            fill_qty = float(order.get("filled") or size)
            order_status = str(order.get("status", "open"))

            if order_status in ("closed", "filled"):
                leg.leg_state = "FILLED"
                leg.filled_at = ts
                leg.exchange_order_id = exchange_order_id
                leg.fill_price = fill_px

                # Idempotency fill update
                self.idempotency.mark_filled(
                    client_order_id, exchange_order_id, fill_px, fill_qty
                )

                # Slippage kayıt
                self._record_slippage(
                    position=position,
                    leg_num=leg_num,
                    client_order_id=client_order_id,
                    exchange_order_id=exchange_order_id,
                    expected_price=trigger_price,
                    fill_price=fill_px,
                    fill_qty=fill_qty,
                    ts=ts,
                    method=getattr(method, "__class__", type(method)).__name__ if not isinstance(method, str) else method,
                )

                log.info(
                    "PyramidRouter: leg-%d FILLED @ %.6f (expected %.6f). "
                    "coid=%s exoid=%s pos=%s",
                    leg_num, fill_px, trigger_price,
                    client_order_id, exchange_order_id,
                    position.parent_position_id,
                )
            else:
                log.info(
                    "PyramidRouter: leg-%d SUBMITTED (pending fill). "
                    "coid=%s status=%s pos=%s",
                    leg_num, client_order_id, order_status,
                    position.parent_position_id,
                )

    def _cancel_pending_legs(
        self,
        position: PyramidPosition,
        reason: str = "sl_hit",
    ) -> None:
        """SL hit veya force-exit → PENDING/SUBMITTED leg'leri iptal et.

        Borsada SUBMITTED ama henüz fill olmamış leg'leri de cancel dener.
        Zaten FILLED/CANCELED/REJECTED ise geçer.
        """
        for leg in position.legs:
            if leg.leg_state not in ("PENDING", "SUBMITTED"):
                continue
            coid = leg.client_order_id
            log.info(
                "PyramidRouter: cancel leg-%d state=%s reason=%s coid=%s pos=%s",
                leg.leg_num, leg.leg_state, reason, coid,
                position.parent_position_id,
            )
            # Borsa cancel (best-effort — zaten fill/cancel olmuşsa hata normaldir)
            exc_id = leg.exchange_order_id
            if exc_id:
                try:
                    self.exchange.cancel_order(exc_id, position.symbol)
                    log.info("PyramidRouter: exchange cancel OK exoid=%s", exc_id)
                except Exception as exc:
                    log.warning(
                        "PyramidRouter: exchange cancel FAIL exoid=%s err=%s "
                        "(already filled/canceled — not critical)",
                        exc_id, exc,
                    )
            else:
                # client_order_id ile cancel dene (bazı borsalar destekler)
                try:
                    self.exchange.cancel_order(coid, position.symbol)
                except Exception as exc:
                    log.warning(
                        "PyramidRouter: coid-cancel FAIL coid=%s err=%s",
                        coid, exc,
                    )
            leg.leg_state = "CANCELED"

    # ── Yardımcı metodlar ─────────────────────────────────────────────────

    def _ensure_leg_submitted(
        self,
        position: PyramidPosition,
        leg_num: int,
        size: float,
        trigger_price: float,
        client_order_id: str,
        ts: datetime,
    ) -> None:
        """İdempotency hit sonrası: leg nesnesini SUBMITTED'a çek (yoksa oluştur)."""
        leg = _find_or_create_leg(position, leg_num, size, trigger_price, client_order_id)
        if leg.leg_state == "PENDING":
            leg.leg_state = "SUBMITTED"
            leg.submitted_at = ts

    def _record_slippage(
        self,
        position: PyramidPosition,
        leg_num: int,
        client_order_id: str,
        exchange_order_id: str,
        expected_price: float,
        fill_price: float,
        fill_qty: float,
        ts: datetime,
        method: str,
    ) -> None:
        """SlippageTracker'a fill kaydı. Hata durumu non-fatal (log + devam)."""
        try:
            fill_id = f"pyr_{uuid.uuid4().hex[:16]}"
            notional = fill_qty * fill_price
            # Yaklaşık fee: maker 4bps, taker 8bps
            is_maker = "post_only" in method.lower()
            fee_bps = 4.0 if is_maker else 8.0
            fee_usdt = notional * fee_bps / 10_000

            self.slippage.record_fill(
                fill_id=fill_id,
                ts=ts,
                symbol=position.symbol,
                strategy=f"pyramid_leg{leg_num}",
                side=position.side.lower(),
                expected_price=expected_price,
                realized_price=fill_price,
                quantity=fill_qty,
                fee_usdt=fee_usdt,
                is_maker=is_maker,
                order_type=method,
                mode=self.mode,
                exchange_order_id=exchange_order_id,
                client_order_id=client_order_id,
                notes=f"pyramid leg-{leg_num} pos={position.parent_position_id}",
                tf="15m",  # phoenix-scalp TF
            )
        except Exception as exc:
            log.error("PyramidRouter: slippage record FAIL: %s", exc)


# ─────────────────────────────────────────────────────────────────────────────
# Module-level yardımcılar
# ─────────────────────────────────────────────────────────────────────────────


def _make_client_order_id(parent_position_id: str, leg_num: int) -> str:
    """Deterministik client_order_id. Binance max 36 karakter.

    Format: PA_{fp[:12]}_L{n}
    Örnek:  PA_a1b2c3d4e5f6_L2
    """
    fp_short = parent_position_id[:12]
    coid = f"PA_{fp_short}_L{leg_num}"
    return coid[:36]  # Binance max


def _find_or_create_leg(
    position: PyramidPosition,
    leg_num: int,
    size: float,
    trigger_price: float,
    client_order_id: str,
) -> PyramidLeg:
    """Mevcut leg'i bul, yoksa oluştur ve position.legs'e ekle."""
    existing = position.leg_for_num(leg_num)
    if existing is not None:
        return existing
    new_leg = PyramidLeg(
        leg_num=leg_num,
        leg_state="PENDING",
        leg_qty=size,
        leg_price=trigger_price,
        client_order_id=client_order_id,
    )
    position.legs.append(new_leg)
    return new_leg


def build_position_from_signal(
    signal_dict: dict[str, Any],
    fill_price: float,
    fill_qty: float,
    sl_price: float,
    parent_position_id: str,
    pyramid_triggers: list[float],
    pyramid_sizes: list[float],
) -> PyramidPosition:
    """Sinyal sözlüğünden PyramidPosition inşa et (daemon entegrasyon noktası).

    Leg-1 otomatik FILLED olarak eklenir (entry emri zaten gerçekleşti).
    """
    symbol = signal_dict["symbol"]
    side_raw = signal_dict.get("side", "long").upper()
    side: PositionSide = "LONG" if side_raw == "LONG" else "SHORT"

    initial_R = abs(fill_price - sl_price)

    # Leg-1: entry (zaten dolu)
    entry_leg = PyramidLeg(
        leg_num=1,
        leg_state="FILLED",
        leg_qty=fill_qty,
        leg_price=fill_price,
        client_order_id=_make_client_order_id(parent_position_id, 1),
        fill_price=fill_price,
        filled_at=datetime.now(timezone.utc),
    )

    return PyramidPosition(
        parent_position_id=parent_position_id,
        symbol=symbol,
        side=side,
        entry_price=fill_price,
        sl_price=sl_price,
        initial_R=initial_R,
        legs=[entry_leg],
        pyramid_triggers=pyramid_triggers,
        pyramid_sizes=pyramid_sizes,
    )


__all__ = [
    "PyramidLeg",
    "PyramidPosition",
    "PyramidRouter",
    "build_position_from_signal",
    "_make_client_order_id",
]
