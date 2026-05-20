"""Maker-Only Router testleri — SEC31 (1m scalper, maker-only).

Senaryolar:
  1) test_fills_first_attempt          — ilk denemede fill OK
  2) test_fills_second_attempt         — 1. timeout, 2. fill OK
  3) test_abort_after_max_retries      — 3 timeout → SignalAbortedError (taker yok)
  4) test_post_only_rejected_retry     — POST_ONLY rejected (exception), sonra fill
  5) test_slippage_defense_check       — fill ama price sapti → MakerSlippageError
  6) test_stats_fill_rate              — stats tracking dogrulama
  7) test_kill_check_below_threshold   — fill rate < %50 → kill True
  8) test_kill_check_above_threshold   — fill rate >= %50 → kill False
  9) test_cancel_called_on_timeout     — timeout sonrasinda cancel_order cagriliyor mu
"""
from __future__ import annotations

from unittest.mock import MagicMock, call, patch

import pytest

from price_action.execution.maker_only_router import (
    MakerOnlyRouter,
    MakerOnlyStats,
    MakerSlippageError,
    SignalAbortedError,
    _compute_slippage_bps,
)


# ===== Fixtures =====

def _mk_exchange_fill_on_attempt(fill_px: float, fill_attempt: int = 1) -> MagicMock:
    """fill_attempt'inci denemede fill olan mock exchange."""
    ex = MagicMock()
    attempts = [0]  # mutable counter

    def _create_order(**kwargs):
        attempts[0] += 1
        return {"id": f"PO_{attempts[0]}", "status": "open"}

    def _fetch_order(order_id, symbol):
        # Hangi denemede olduğumuzu order_id suffix'inden çıkar
        attempt_n = int(order_id.split("_")[1])
        if attempt_n >= fill_attempt:
            return {"id": order_id, "status": "closed", "average": fill_px}
        return {"id": order_id, "status": "open"}

    ex.create_order.side_effect = lambda **kw: _create_order(**kw)
    ex.fetch_order.side_effect = _fetch_order
    ex.cancel_order.return_value = {"status": "canceled"}
    return ex


def _mk_exchange_always_timeout() -> MagicMock:
    """Hic fill olmayan mock (hep 'open' doner)."""
    ex = MagicMock()
    attempt_counter = [0]

    def _create_order(**kwargs):
        attempt_counter[0] += 1
        return {"id": f"PO_{attempt_counter[0]}", "status": "open"}

    ex.create_order.side_effect = lambda **kw: _create_order(**kw)
    ex.fetch_order.return_value = {"status": "open"}
    ex.cancel_order.return_value = {"status": "canceled"}
    return ex


def _mk_exchange_post_only_rejected() -> MagicMock:
    """create_order exception (POST_ONLY reddedildi), 2. denemede fill."""
    ex = MagicMock()
    call_count = [0]

    def _create_order(**kwargs):
        call_count[0] += 1
        if call_count[0] == 1:
            raise Exception("Order would immediately match and take (POST_ONLY rejected)")
        return {"id": f"PO_{call_count[0]}", "status": "open"}

    def _fetch_order(order_id, symbol):
        return {"id": order_id, "status": "closed", "average": 65000.0}

    ex.create_order.side_effect = lambda **kw: _create_order(**kw)
    ex.fetch_order.side_effect = _fetch_order
    ex.cancel_order.return_value = {"status": "canceled"}
    return ex


def _mk_router(exchange, cancel_after_sec=0.05, max_retries=3,
               slippage_limit_bps=10.0, poll_interval=0.01) -> MakerOnlyRouter:
    return MakerOnlyRouter(
        exchange,
        cancel_after_sec=cancel_after_sec,
        max_retries=max_retries,
        slippage_limit_bps=slippage_limit_bps,
        poll_interval=poll_interval,
    )


# ===== Helper tests =====

def test_compute_slippage_bps_buy():
    # buy: fill > expected → pozitif maliyet
    assert _compute_slippage_bps("buy", 100.0, 100.5) == pytest.approx(50.0)
    assert _compute_slippage_bps("buy", 100.0, 99.5) == pytest.approx(-50.0)


def test_compute_slippage_bps_sell():
    # sell: expected > fill → pozitif maliyet
    assert _compute_slippage_bps("sell", 100.0, 99.5) == pytest.approx(50.0)


# ===== Ana senaryolar =====

def test_fills_first_attempt():
    """Senaryo 1: ilk denemede fill."""
    ex = _mk_exchange_fill_on_attempt(fill_px=65000.0, fill_attempt=1)
    router = _mk_router(ex)

    order, attempt = router.place("BTC/USDT", "buy", 0.01, 65000.0)

    assert attempt == 1
    assert router.stats.filled == 1
    assert router.stats.aborted == 0
    assert router.stats.fill_rate_pct == pytest.approx(100.0)
    # create_order bir kez cagrildı (POST_ONLY)
    assert ex.create_order.call_count == 1
    # cancel cagrılmadi
    assert ex.cancel_order.call_count == 0


def test_fills_second_attempt():
    """Senaryo 2: 1. timeout, 2. fill."""
    ex = _mk_exchange_fill_on_attempt(fill_px=65001.0, fill_attempt=2)
    router = _mk_router(ex)

    order, attempt = router.place("BTC/USDT", "buy", 0.01, 65000.0,
                                   client_order_id="test_ord")

    assert attempt == 2
    assert router.stats.filled == 1
    assert router.stats.total_attempts == 2
    # 1. deneme timeout → cancel
    assert ex.cancel_order.call_count == 1


def test_abort_after_max_retries():
    """Senaryo 3: 3 timeout → SignalAbortedError (taker YOK)."""
    ex = _mk_exchange_always_timeout()
    router = _mk_router(ex, max_retries=3)

    with pytest.raises(SignalAbortedError) as exc_info:
        router.place("BTC/USDT", "buy", 0.01, 65000.0)

    err = exc_info.value
    assert err.symbol == "BTC/USDT"
    assert err.n_attempts == 3
    assert router.stats.aborted == 1
    assert router.stats.filled == 0
    # 3 create_order + 3 cancel
    assert ex.create_order.call_count == 3
    assert ex.cancel_order.call_count == 3
    # TAKER market order CALL EDILMEDI
    assert not ex.create_market_order.called


def test_post_only_rejected_retry():
    """Senaryo 4: 1. POST_ONLY exception, 2. fill."""
    ex = _mk_exchange_post_only_rejected()
    router = _mk_router(ex)

    order, attempt = router.place("BTC/USDT", "buy", 0.01, 65000.0)

    # 1. deneme rejected → retry → 2. deneme fill
    assert attempt == 2
    assert router.stats.filled == 1
    # create_order 2 kez cagrıldı
    assert ex.create_order.call_count == 2


def test_slippage_defense_check():
    """Senaryo 5: fill oldu ama fiyat 1m budget (%10 bps) asiminda → MakerSlippageError."""
    # 65000 → 65010 = 1.54 bps, limit 1 bps (cok dar → tetikle)
    ex = _mk_exchange_fill_on_attempt(fill_px=65010.0, fill_attempt=1)
    router = _mk_router(ex, slippage_limit_bps=1.0)  # ultra-dar limit

    with pytest.raises(MakerSlippageError) as exc_info:
        router.place("BTC/USDT", "buy", 0.01, 65000.0)

    err = exc_info.value
    assert err.symbol == "BTC/USDT"
    assert err.slippage_bps > err.limit_bps
    # Fill sayildi (order geldi)
    assert router.stats.filled == 1


def test_stats_fill_rate():
    """Senaryo 6: 2 fill, 1 abort → fill rate %66.7."""
    ex_fill = _mk_exchange_fill_on_attempt(fill_px=65000.0, fill_attempt=1)
    router = _mk_router(ex_fill)

    router.place("BTC/USDT", "buy", 0.01, 65000.0)
    router.place("BTC/USDT", "sell", 0.01, 65000.0)

    ex_timeout = _mk_exchange_always_timeout()
    router.exchange = ex_timeout

    with pytest.raises(SignalAbortedError):
        router.place("BTC/USDT", "buy", 0.01, 65000.0)

    assert router.stats.total_signals == 3
    assert router.stats.filled == 2
    assert router.stats.aborted == 1
    assert router.stats.fill_rate_pct == pytest.approx(66.67, abs=0.1)


def test_kill_check_below_threshold():
    """Senaryo 7: fill rate < %50 → kill True."""
    stats = MakerOnlyStats(total_signals=20, filled=9, aborted=11)
    assert stats.fill_rate_pct < 50.0
    assert stats.kill_criteria_check(50.0) is True


def test_kill_check_above_threshold():
    """Senaryo 8: fill rate >= %50 → kill False."""
    stats = MakerOnlyStats(total_signals=20, filled=12, aborted=8)
    assert stats.fill_rate_pct >= 50.0
    assert stats.kill_criteria_check(50.0) is False


def test_cancel_called_on_timeout():
    """Senaryo 9: her timeout sonrasi cancel_order cagriliyor mu?"""
    ex = _mk_exchange_always_timeout()
    router = _mk_router(ex, max_retries=2)

    with pytest.raises(SignalAbortedError):
        router.place("ETH/USDT", "sell", 0.1, 3000.0)

    # Her deneme timeout → cancel (2 kez)
    assert ex.cancel_order.call_count == 2
