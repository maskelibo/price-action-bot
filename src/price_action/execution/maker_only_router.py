"""Maker-Only Router — 1m scalper icin zorunlu post-only + abort politikasi.

Tasarim (master plan §4.5):
  1m'de taker fill kabul edilmez: fee fizigi (round-trip ~12-20 bps) trade edge'ini siler.
  Bu router: post-only limit + cancel-if-not-filled-in-5s + retry max 3 + taker fallback YOK.
  3 retry sonrasi fill yok → signal abort + log.

Fark: post_only_router.py (1d) vs maker_only_router.py (1m):
  ┌─────────────────────────┬────────────────────┬────────────────────┐
  │ Ozellik                 │ post_only_router   │ maker_only_router  │
  ├─────────────────────────┼────────────────────┼────────────────────┤
  │ TF hedef                │ 1d / swing         │ 1m / scalp         │
  │ Timeout per attempt     │ 30s (default)      │ 5s (sabit)         │
  │ Max retry               │ 1 (timeout→market) │ 3                  │
  │ Taker fallback          │ EVET               │ YOK (abort)        │
  │ Slippage gate           │ 25 bps (default)   │ 10 bps (1m budget) │
  │ Abort on fail           │ HAYIR (market ok)  │ EVET               │
  └─────────────────────────┴────────────────────┴────────────────────┘

Kill criteria: 1m maker fill rate < %50 → 1m TF KILL (master plan §7 madde 4).
Paper trading'de fill rate izlenmeli.

Usage:
    from price_action.execution.maker_only_router import (
        MakerOnlyRouter, SignalAbortedError
    )
    router = MakerOnlyRouter(exchange)
    try:
        order, fill_attempt = router.place(
            symbol="BTC/USDT", side="buy", qty=0.01, target_price=65000.0
        )
    except SignalAbortedError as e:
        log.warning(f"Signal aborted: {e}")  # 3 retry no fill
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


# ===== Exceptions =====

class SignalAbortedError(Exception):
    """3 retry sonrasi fill yok; signal abort.

    1m maker-only router: taker fallback YOK. Bu exception raise oldugunda
    caller signal'i discard etmeli ve bir sonraki bar'i beklemeli.
    """

    def __init__(
        self,
        symbol: str,
        side: str,
        n_attempts: int,
        target_price: float,
    ) -> None:
        self.symbol = symbol
        self.side = side
        self.n_attempts = n_attempts
        self.target_price = target_price
        super().__init__(
            f"SignalAborted [{symbol} {side}]: {n_attempts} post-only retry sonrasi "
            f"fill yok @ {target_price:.6g} — taker fallback YOK (1m maker-only)"
        )


class MakerSlippageError(Exception):
    """Fill oldu ama slippage > limit (mantik hatasi — post-only'de olmamalı).

    Defense-in-depth: fill price'i dogrularken kullanilir.
    """

    def __init__(self, symbol: str, slippage_bps: float, limit_bps: float) -> None:
        self.symbol = symbol
        self.slippage_bps = slippage_bps
        self.limit_bps = limit_bps
        super().__init__(
            f"MakerSlippage [{symbol}]: {slippage_bps:.1f}bps > {limit_bps:.1f}bps limit"
        )


# ===== Stats collector =====

@dataclass
class MakerOnlyStats:
    """Cumulative fill rate takibi (paper trading kill criteria icin)."""
    total_signals: int = 0
    filled: int = 0
    aborted: int = 0
    total_attempts: int = 0

    @property
    def fill_rate_pct(self) -> float:
        if self.total_signals == 0:
            return 0.0
        return self.filled / self.total_signals * 100.0

    @property
    def avg_attempts_per_fill(self) -> float:
        if self.filled == 0:
            return 0.0
        return self.total_attempts / self.filled

    def kill_criteria_check(self, min_fill_rate_pct: float = 50.0) -> bool:
        """True → 1m KILL (fill rate < threshold)."""
        if self.total_signals < 10:  # min sample
            return False
        return self.fill_rate_pct < min_fill_rate_pct

    def summary(self) -> dict[str, Any]:
        return {
            "total_signals": self.total_signals,
            "filled": self.filled,
            "aborted": self.aborted,
            "fill_rate_pct": round(self.fill_rate_pct, 1),
            "avg_attempts_per_fill": round(self.avg_attempts_per_fill, 2),
        }


# ===== Router =====

class MakerOnlyRouter:
    """1m scalper post-only maker router.

    Args:
        exchange: ccxt-compatible (create_order, fetch_order, cancel_order).
        cancel_after_sec: Her denemede bu kadar bekle (default 5s).
        max_retries: Maksimum deneme sayisi (default 3).
        slippage_limit_bps: Fill price vs target_price max sapma (default 10 bps).
        poll_interval: fetch_order polling periyodu (default 0.5s).
    """

    def __init__(
        self,
        exchange: Any,
        *,
        cancel_after_sec: float = 5.0,
        max_retries: int = 3,
        slippage_limit_bps: float = 10.0,
        poll_interval: float = 0.5,
    ) -> None:
        self.exchange = exchange
        self.cancel_after_sec = cancel_after_sec
        self.max_retries = max_retries
        self.slippage_limit_bps = slippage_limit_bps
        self.poll_interval = poll_interval
        self.stats = MakerOnlyStats()

    def place(
        self,
        symbol: str,
        side: str,
        qty: float,
        target_price: float,
        *,
        client_order_id: str | None = None,
    ) -> tuple[dict, int]:
        """Post-only limit yerleştir. Fill olana veya max_retries dolana kadar dene.

        Args:
            symbol: 'BTC/USDT'
            side: 'buy' | 'sell'
            qty: amount
            target_price: limit fiyati (aynı zamanda slippage ref)
            client_order_id: idempotency prefix

        Returns:
            (order_dict, attempt_number)  — fill olduğu deneme numarası (1-indexed)

        Raises:
            SignalAbortedError: max_retries sonrasi fill yok. TAKER YOK.
            MakerSlippageError: fill oldu ama fiyat sapti (defense check).
        """
        self.stats.total_signals += 1

        for attempt in range(1, self.max_retries + 1):
            self.stats.total_attempts += 1

            # Her deneme icin benzersiz client ID
            coid = f"{client_order_id}_r{attempt}" if client_order_id else None

            order_id = self._submit_post_only(symbol, side, qty, target_price, coid)

            if order_id is None:
                # POST-ONLY reddedildi (fiyat market'i cross ediyor): bir sonraki deneme
                _log_warn(
                    f"[MakerOnly] attempt={attempt} POST_ONLY_REJECTED "
                    f"{symbol} {side} @ {target_price:.6g}"
                )
                continue

            # Poll: cancel_after_sec icerisinde fill bekle
            status, filled_order = self._poll_until_filled(
                order_id, symbol, self.cancel_after_sec
            )

            if status in ("closed", "filled"):
                fill_px = float(
                    filled_order.get("average")
                    or filled_order.get("price")
                    or target_price
                )
                # Slippage defense check
                slip_bps = _compute_slippage_bps(side, target_price, fill_px)
                if slip_bps > self.slippage_limit_bps:
                    self.stats.filled += 1
                    raise MakerSlippageError(symbol, slip_bps, self.slippage_limit_bps)

                self.stats.filled += 1
                _log_info(
                    f"[MakerOnly] FILLED attempt={attempt} {symbol} {side} "
                    f"@ {fill_px:.6g} slip={slip_bps:.1f}bps"
                )
                return filled_order, attempt

            # Timeout → cancel + retry
            _cancel_safe(self.exchange, order_id, symbol)
            _log_warn(
                f"[MakerOnly] attempt={attempt}/{self.max_retries} TIMEOUT "
                f"{symbol} {side} @ {target_price:.6g}"
            )

        # ===== 3 retry bitti, fill yok =====
        self.stats.aborted += 1
        _log_warn(
            f"[MakerOnly] SIGNAL_ABORT {symbol} {side} after {self.max_retries} attempts "
            f"fill_rate_so_far={self.stats.fill_rate_pct:.1f}%"
        )
        raise SignalAbortedError(symbol, side, self.max_retries, target_price)

    def kill_check(self, min_fill_rate_pct: float = 50.0) -> bool:
        """True → 1m KILL criterion met (fill rate < %50)."""
        return self.stats.kill_criteria_check(min_fill_rate_pct)

    # ----- internal -----

    def _submit_post_only(
        self,
        symbol: str,
        side: str,
        qty: float,
        price: float,
        coid: str | None,
    ) -> str | None:
        """POST-ONLY limit yerlestir. order_id don (None = rejected)."""
        params: dict[str, Any] = {"timeInForce": "PO", "postOnly": True}
        if coid:
            params["newClientOrderId"] = coid
        try:
            order = self.exchange.create_order(
                symbol=symbol,
                type="limit",
                side=side,
                amount=qty,
                price=price,
                params=params,
            )
            oid = str(order.get("id", ""))
            return oid if oid else None
        except Exception as exc:
            # POST_ONLY rejection = ccxt exception (ornek: "Order would immediately match")
            _log_warn(f"[MakerOnly] create_order exception: {exc}")
            return None

    def _poll_until_filled(
        self,
        order_id: str,
        symbol: str,
        timeout_sec: float,
    ) -> tuple[str, dict]:
        """Order fill olana veya timeout'a kadar poll et.

        Returns:
            (status_str, order_dict)
        """
        t0 = time.time()
        last_order: dict = {}
        while time.time() - t0 < timeout_sec:
            try:
                o = self.exchange.fetch_order(order_id, symbol)
                last_order = o
                st = str(o.get("status", "open"))
                if st in ("closed", "filled", "canceled"):
                    return st, o
            except Exception:
                pass
            time.sleep(self.poll_interval)
        return "timeout", last_order


# ===== helpers =====

def _compute_slippage_bps(side: str, expected_px: float, fill_px: float) -> float:
    """Yon-duzeltmeli slippage bps. Pozitif = maliyet."""
    if expected_px <= 0:
        return 0.0
    if side.lower() in ("buy", "long"):
        return (fill_px - expected_px) / expected_px * 10_000
    return (expected_px - fill_px) / expected_px * 10_000


def _cancel_safe(exchange: Any, order_id: str, symbol: str) -> None:
    try:
        exchange.cancel_order(order_id, symbol)
    except Exception:
        pass


def _log_info(msg: str) -> None:
    import sys
    print(msg, file=sys.stderr)


def _log_warn(msg: str) -> None:
    import sys
    print(f"[WARN] {msg}", file=sys.stderr)
