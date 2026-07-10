"""Paket-5 (KALAN_ISLER #9) + #10 testleri — cancel-yutma kardeşleri + poll-özet.

Kapsam (hepsi LATENT modüller — canlı yolda değil, referans-impl/test-only):
  * order_router._place_post_only_with_fallback — timeout-cancel yolu:
      (a) cancel doğrulanamaz → market YOK + (None, ...) döner
      (b) onaylı iptal + kısmi dolum → yalnız KALAN market'e ("_fb" coid)
      (c) race'te closed → fill sahiplenilir (market yok)
  * order_router.route_signal — slippage-exceeded cancel yolu:
      cancel-verify; dolmuşsa fill sahiplen (status=filled + slippage_exceeded
      bayrağı), doğrulanamazsa cancel_verified=False bayrağı.
  * maker_only_router._cancel_safe + place — cancel fail fetch-verify;
      doğrulanamazsa retry YOK (signal abort), race-closed'da fill sahiplen.
  * #10 poll-özet: post_only_router._wait_for_fill / maker_only_router.
      _poll_until_filled / order_router poll / ccxt_live poll — her exception'da
      DEĞİL, timeout sonunda TEK "poll_summary" satırı.

ccxt_live Bug-A davranışı test_ccxt_live_fill_integrity.py'de; burada ccxt_live
için yalnız #10 sayaç-sargısı test edilir (akış değişmedi).
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest

from price_action.execution import order_router
from price_action.execution.maker_only_router import (
    MakerOnlyRouter,
    SignalAbortedError,
    _cancel_safe,
)
from price_action.execution.order_router import _place_post_only_with_fallback
from price_action.execution.post_only_router import _wait_for_fill

# ---------------------------------------------------------------------------
# Fake exchange — order_router._place_post_only_with_fallback için
# ---------------------------------------------------------------------------


class FakeExOR:
    """Poll / cancel / verify / market fazları ayrı ayrı programlanabilir."""

    def __init__(
        self,
        *,
        poll_raises: bool = False,
        cancel_raises: bool = False,
        verify_result: dict | None = None,
        verify_raises: bool = False,
        market_result: dict | None = None,
    ) -> None:
        self.cancel_calls: list[str] = []
        self.market_calls: list[dict] = []
        self.poll_raises = poll_raises
        self.cancel_raises = cancel_raises
        self.verify_result = verify_result
        self.verify_raises = verify_raises
        self.market_result = market_result or {"id": "M1", "filled": 0.0, "average": 0.0}
        self._cancel_attempted = False

    def fetch_order_book(self, sym, limit=5):
        return {"bids": [[99.98, 5.0]], "asks": [[100.02, 5.0]]}

    def create_limit_order(self, **kw):
        return {"id": "L1", "status": "open"}

    def cancel_order(self, order_id, sym=None):
        self.cancel_calls.append(order_id)
        self._cancel_attempted = True
        if self.cancel_raises:
            raise Exception("cancel network fail")

    def fetch_order(self, order_id, sym=None):
        if not self._cancel_attempted:
            # poll fazı
            if self.poll_raises:
                raise Exception("poll fetch fail")
            return {"id": order_id, "status": "open", "filled": 0.0}
        # cancel-sonrası verify fazı
        if self.verify_raises:
            raise Exception("verify fetch fail")
        return self.verify_result or {"id": order_id, "status": "open", "filled": 0.0}

    def create_market_order(self, **kw):
        self.market_calls.append(kw)
        return self.market_result


# ---------------------------------------------------------------------------
# (a) cancel doğrulanamaz → market YOK + None
# ---------------------------------------------------------------------------


def test_or_timeout_cancel_fail_still_open_refuses_market():
    """Cancel RAISE + verify 'open' → market ATILMAZ, (None, ...) döner."""
    ex = FakeExOR(cancel_raises=True, verify_result={"status": "open", "filled": 0.0})
    order, _otype = _place_post_only_with_fallback(ex, "BTC/USDT", "buy", 1.0, "cid", 0)
    assert order is None
    assert ex.market_calls == []  # koşulsuz tam-qty market YOK
    assert len(ex.cancel_calls) == 1


def test_or_timeout_cancel_verify_fail_refuses_market():
    """Cancel OK ama verify EXCEPTION (durum bilinmiyor) → fail-closed, market YOK."""
    ex = FakeExOR(cancel_raises=False, verify_raises=True)
    order, _ = _place_post_only_with_fallback(ex, "BTC/USDT", "buy", 1.0, "cid", 0)
    assert order is None
    assert ex.market_calls == []


def test_or_timeout_cancel_ok_but_still_open_refuses_market():
    """Cancel OK dedi ama borsa 'open' diyor → borsa gerçeği kazanır, market YOK."""
    ex = FakeExOR(cancel_raises=False, verify_result={"status": "open", "filled": 0.0})
    order, _ = _place_post_only_with_fallback(ex, "BTC/USDT", "buy", 1.0, "cid", 0)
    assert order is None
    assert ex.market_calls == []


# ---------------------------------------------------------------------------
# (b) onaylı iptal + kısmi dolum → yalnız KALAN market'e
# ---------------------------------------------------------------------------


def test_or_partial_fill_markets_remainder_only():
    """İptal onaylı + 0.4 dolmuş (qty=1.0) → market amount=0.6, coid '_fb'."""
    ex = FakeExOR(
        verify_result={"status": "canceled", "filled": 0.4, "average": 100.0},
        market_result={"id": "M1", "filled": 0.6, "average": 100.5},
    )
    order, otype = _place_post_only_with_fallback(ex, "BTC/USDT", "buy", 1.0, "cid", 0)
    assert otype == "market"
    assert len(ex.market_calls) == 1
    mk = ex.market_calls[0]
    assert mk["amount"] == pytest.approx(0.6)  # kalan; tam-qty DEĞİL
    assert mk["params"]["newClientOrderId"] == "cid_fb"
    # Dönen order TOPLAMI yansıtır: filled = 0.4 (limit) + 0.6 (market)
    assert order["filled"] == pytest.approx(1.0)
    assert order["partial_limit_qty"] == pytest.approx(0.4)
    # Ağırlıklı ortalama: (100.5*0.6 + 100.0*0.4) / 1.0
    assert order["average"] == pytest.approx(100.3)


def test_or_fully_filled_during_cancel_no_market():
    """İptal 'canceled' ama filled==qty → fiilen dolmuş, market GEREKMEZ."""
    ex = FakeExOR(verify_result={"status": "canceled", "filled": 1.0, "average": 100.0})
    order, otype = _place_post_only_with_fallback(ex, "BTC/USDT", "buy", 1.0, "cid", 0)
    assert otype == "post_only_limit"
    assert ex.market_calls == []
    assert order["filled"] == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# (c) race'te closed → fill'i sahiplen
# ---------------------------------------------------------------------------


def test_or_race_closed_owns_fill_no_market():
    """Cancel-verify 'closed' → limit fill'i sahiplenilir, market YOK."""
    ex = FakeExOR(
        cancel_raises=True,  # cancel 'unknown order' benzeri raise etse bile
        verify_result={"status": "closed", "filled": 1.0, "average": 100.02},
    )
    order, otype = _place_post_only_with_fallback(ex, "BTC/USDT", "buy", 1.0, "cid", 0)
    assert otype == "post_only_limit"
    assert order["filled"] == pytest.approx(1.0)
    assert order["average"] == pytest.approx(100.02)
    assert ex.market_calls == []


# ---------------------------------------------------------------------------
# route_signal — slippage-exceeded cancel-verify
# ---------------------------------------------------------------------------


def _make_signal_dict(sym="BTC/USDT", side="long"):
    return {
        "ts": datetime.now(UTC),
        "symbol": sym,
        "strategy": "engulfing_continuation",
        "side": side,
        "sl_price": 60000.0,
        "tp_price": 70000.0,
        "confluence": 0.6,
        "entry_price": 65000.0,
    }


def _route_env(tmp_path):
    from price_action.execution import idempotency, slippage_tracker

    idem = idempotency.IdempotencyStore(tmp_path / "idem.duckdb")
    slip = slippage_tracker.SlippageTracker(tmp_path / "slip.duckdb")
    risk_officer = MagicMock()
    risked = MagicMock()
    risked.quantity = 0.01
    risked.notional_usdt = 650.0
    risked.leverage = 3.0
    risk_officer.evaluate.return_value = risked
    account = MagicMock()
    account.free_margin_usdt = 5000.0
    account.equity_usdt = 5000.0
    account.open_positions = []
    return idem, slip, risk_officer, account


def _slippage_ex(fetch_order_result=None, cancel_raises=False):
    """ref=65000, fill=65200 → 30.8bps > 25bps → slippage-exceeded yolu."""
    ex = MagicMock()
    ex.fetch_ticker.return_value = {"last": 65000.0}
    ex.create_market_order.return_value = {
        "id": "EX_SLIP1",
        "filled": 0.01,
        "average": 65200.0,
        "fee": {"cost": 0.05},
        "status": "closed",
    }
    ex.set_leverage.return_value = None
    if cancel_raises:
        ex.cancel_order.side_effect = Exception("cancel fail")
    if fetch_order_result is not None:
        ex.fetch_order.return_value = fetch_order_result
    return ex


def test_route_slippage_race_filled_owns_position(tmp_path):
    """Slippage aşıldı ama emir borsada DOLMUŞ → fill sahiplenilir (rejected değil)."""
    ex = _slippage_ex(
        fetch_order_result={"status": "closed", "filled": 0.01, "average": 65200.0}
    )
    idem, slip, risk_officer, account = _route_env(tmp_path)
    with (
        patch.object(order_router, "get_idempotency_store", return_value=idem),
        patch.object(order_router, "get_slippage_tracker", return_value=slip),
    ):
        result = order_router.route_signal(
            _make_signal_dict(), ex, risk_officer, account, MagicMock(),
            max_slippage_bps=25.0,
        )

    assert result["status"] == "filled"  # pozisyon borsada GERÇEK — rejected yalanı yok
    assert result["slippage_exceeded"] is True
    assert result["fill_qty"] == pytest.approx(0.01)
    assert result["fill_price"] == pytest.approx(65200.0)
    assert ex.create_market_order.call_count == 1  # resubmit YOK


def test_route_slippage_partial_fill_on_cancel_owned(tmp_path):
    """Onaylı iptal ama KISMİ dolum var → kısmi pozisyon sahiplenilir."""
    ex = _slippage_ex(
        fetch_order_result={"status": "canceled", "filled": 0.004, "average": 65200.0}
    )
    idem, slip, risk_officer, account = _route_env(tmp_path)
    with (
        patch.object(order_router, "get_idempotency_store", return_value=idem),
        patch.object(order_router, "get_slippage_tracker", return_value=slip),
    ):
        result = order_router.route_signal(
            _make_signal_dict(), ex, risk_officer, account, MagicMock(),
            max_slippage_bps=25.0,
        )

    assert result["status"] == "filled"
    assert result["slippage_exceeded"] is True
    assert result["fill_qty"] == pytest.approx(0.004)  # gerçek kısmi, istenen 0.01 değil


def test_route_slippage_cancel_unverified_flagged(tmp_path):
    """Cancel RAISE + emir hâlâ 'open' → rejected ama cancel_verified=False bayrağı."""
    ex = _slippage_ex(
        fetch_order_result={"status": "open", "filled": 0.0, "average": None},
        cancel_raises=True,
    )
    idem, slip, risk_officer, account = _route_env(tmp_path)
    with (
        patch.object(order_router, "get_idempotency_store", return_value=idem),
        patch.object(order_router, "get_slippage_tracker", return_value=slip),
    ):
        result = order_router.route_signal(
            _make_signal_dict(), ex, risk_officer, account, MagicMock(),
            max_slippage_bps=25.0,
        )

    assert result["status"] == "rejected"
    assert "slippage" in result["reason"]
    assert result["cancel_verified"] is False


def test_route_slippage_verified_cancel_legacy_reject(tmp_path):
    """Onaylı iptal + dolum yok → eski davranış: rejected + cancel_verified=True."""
    ex = _slippage_ex(
        fetch_order_result={"status": "canceled", "filled": 0.0, "average": None}
    )
    idem, slip, risk_officer, account = _route_env(tmp_path)
    with (
        patch.object(order_router, "get_idempotency_store", return_value=idem),
        patch.object(order_router, "get_slippage_tracker", return_value=slip),
    ):
        result = order_router.route_signal(
            _make_signal_dict(), ex, risk_officer, account, MagicMock(),
            max_slippage_bps=25.0,
        )

    assert result["status"] == "rejected"
    assert "slippage" in result["reason"]
    assert result["cancel_verified"] is True


# ---------------------------------------------------------------------------
# maker_only_router — _cancel_safe fetch-verify + place entegrasyonu
# ---------------------------------------------------------------------------


def _maker_ex(cancel_raises=True, verify_status="open", verify_extra=None):
    """Poll boyunca 'open'; cancel denendiyse verify_status döner."""
    ex = MagicMock()
    state = {"cancel_attempted": False}
    ex.create_order.return_value = {"id": "PO_1", "status": "open"}

    def _cancel(order_id, symbol):
        state["cancel_attempted"] = True
        if cancel_raises:
            raise Exception("cancel network fail")
        return {"status": "canceled"}

    def _fetch(order_id, symbol):
        if state["cancel_attempted"]:
            out = {"id": order_id, "status": verify_status}
            out.update(verify_extra or {})
            return out
        return {"id": order_id, "status": "open"}

    ex.cancel_order.side_effect = _cancel
    ex.fetch_order.side_effect = _fetch
    return ex


def _mk_router(ex, **kw):
    defaults = dict(cancel_after_sec=0.03, max_retries=3, poll_interval=0.01)
    defaults.update(kw)
    return MakerOnlyRouter(ex, **defaults)


def test_maker_cancel_unverified_aborts_no_retry():
    """Cancel RAISE + verify 'open' → yeni emir YERLEŞTİRİLMEZ, signal abort."""
    ex = _maker_ex(cancel_raises=True, verify_status="open")
    router = _mk_router(ex)
    with pytest.raises(SignalAbortedError) as exc_info:
        router.place("BTC/USDT", "buy", 0.01, 65000.0)
    assert exc_info.value.n_attempts == 1  # retry döngüsü ilk denemede kesildi
    assert ex.create_order.call_count == 1  # eski emir asılıyken YENİ EMİR YOK
    assert router.stats.aborted == 1
    assert not ex.create_market_order.called  # taker fallback zaten YOK


def test_maker_cancel_verify_fetch_fail_aborts():
    """Cancel RAISE + verify de RAISE (durum bilinmiyor) → fail-closed abort."""
    ex = MagicMock()
    ex.create_order.return_value = {"id": "PO_1", "status": "open"}
    state = {"cancel_attempted": False}

    def _cancel(order_id, symbol):
        state["cancel_attempted"] = True
        raise Exception("cancel fail")

    def _fetch(order_id, symbol):
        if state["cancel_attempted"]:
            raise Exception("verify fetch fail")
        return {"id": order_id, "status": "open"}

    ex.cancel_order.side_effect = _cancel
    ex.fetch_order.side_effect = _fetch
    router = _mk_router(ex)
    with pytest.raises(SignalAbortedError):
        router.place("BTC/USDT", "buy", 0.01, 65000.0)
    assert ex.create_order.call_count == 1


def test_maker_race_closed_owns_fill():
    """Cancel RAISE ama verify 'closed' → fill sahiplenilir (abort DEĞİL)."""
    ex = _maker_ex(
        cancel_raises=True, verify_status="closed", verify_extra={"average": 65000.5}
    )
    router = _mk_router(ex)
    order, attempt = router.place("BTC/USDT", "buy", 0.01, 65000.0)
    assert attempt == 1
    assert order["status"] == "closed"
    assert router.stats.filled == 1
    assert router.stats.aborted == 0
    assert ex.create_order.call_count == 1


def test_maker_cancel_ok_keeps_retrying():
    """Regresyon: cancel BAŞARILI ise eski davranış — retry devam, sonda abort."""
    ex = MagicMock()
    counter = [0]

    def _create(**kw):
        counter[0] += 1
        return {"id": f"PO_{counter[0]}", "status": "open"}

    ex.create_order.side_effect = _create
    ex.fetch_order.return_value = {"status": "open"}
    ex.cancel_order.return_value = {"status": "canceled"}
    router = _mk_router(ex, max_retries=3)
    with pytest.raises(SignalAbortedError) as exc_info:
        router.place("BTC/USDT", "buy", 0.01, 65000.0)
    assert exc_info.value.n_attempts == 3
    assert ex.create_order.call_count == 3
    assert ex.cancel_order.call_count == 3


def test_cancel_safe_already_canceled_error_is_ok():
    """Cancel 'already canceled' hatası + verify 'canceled' → (True, None)."""
    ex = MagicMock()
    ex.cancel_order.side_effect = Exception("order already canceled")
    ex.fetch_order.return_value = {"id": "X", "status": "canceled"}
    ok, race = _cancel_safe(ex, "X", "BTC/USDT")
    assert ok is True
    assert race is None


# ---------------------------------------------------------------------------
# (d) #10 poll-özet — timeout sonunda TEK log
# ---------------------------------------------------------------------------


def test_post_only_wait_for_fill_single_poll_summary(caplog):
    """post_only_router._wait_for_fill: N hata yutulur, timeout'ta TEK özet."""
    ex = MagicMock()
    ex.fetch_order.side_effect = Exception("boom")
    with caplog.at_level(logging.WARNING, logger="price_action.execution.post_only_router"):
        status = _wait_for_fill(ex, "OID", "BTC/USDT", 0.05, poll_interval=0.01)
    assert status == "open"  # davranış aynı: son bilinen status döner
    summaries = [r for r in caplog.records if "poll_summary" in r.getMessage()]
    assert len(summaries) == 1  # exception başına DEĞİL, tek özet
    msg = summaries[0].getMessage()
    assert "hata" in msg and "son_hata" in msg and "boom" in msg
    assert ex.fetch_order.call_count >= 2  # birden çok deneme oldu ama tek log


def test_post_only_wait_for_fill_no_errors_no_summary(caplog):
    """Hata yoksa özet log YOK (normal timeout akışına gürültü ekleme)."""
    ex = MagicMock()
    ex.fetch_order.return_value = {"status": "open"}
    with caplog.at_level(logging.WARNING, logger="price_action.execution.post_only_router"):
        status = _wait_for_fill(ex, "OID", "BTC/USDT", 0.03, poll_interval=0.01)
    assert status == "open"
    assert not [r for r in caplog.records if "poll_summary" in r.getMessage()]


def test_maker_poll_until_filled_single_summary(capsys):
    """maker_only_router._poll_until_filled: hatalar sayılır, TEK özet stderr'e."""
    ex = MagicMock()
    ex.fetch_order.side_effect = Exception("net glitch")
    router = MakerOnlyRouter(ex, cancel_after_sec=0.05, poll_interval=0.01)
    status, last = router._poll_until_filled("OID", "BTC/USDT", 0.05)
    assert status == "timeout"
    assert last == {}
    err = capsys.readouterr().err
    assert err.count("poll_summary") == 1
    assert "net glitch" in err


def test_order_router_poll_single_summary(caplog):
    """order_router poll: hatalar yutulmaz, timeout'ta TEK özet."""
    ex = FakeExOR(poll_raises=True, verify_raises=True)
    with caplog.at_level(logging.WARNING, logger="price_action.execution.order_router"):
        order, _ = _place_post_only_with_fallback(ex, "BTC/USDT", "buy", 1.0, "cid", 0.01)
    assert order is None  # verify de fail → fail-closed (market yok)
    summaries = [r for r in caplog.records if "order_router.poll_summary" in r.getMessage()]
    assert len(summaries) == 1
    assert "son_hata" in summaries[0].getMessage()


# ---------------------------------------------------------------------------
# ccxt_live #10 — yalnız sayaç + özet-log sargısı (akış aynı)
# ---------------------------------------------------------------------------


class _RecLog:
    """loguru-benzeri .bind().warning() zincirini kaydeden sahte logger."""

    def __init__(self) -> None:
        self.events: list[tuple[str, str, dict]] = []
        self._ctx: dict = {}

    def bind(self, **kw):
        self._ctx = kw
        return self

    def warning(self, msg):
        self.events.append(("warning", msg, dict(self._ctx)))

    def error(self, msg):
        self.events.append(("error", msg, dict(self._ctx)))

    def info(self, msg):
        self.events.append(("info", msg, dict(self._ctx)))


class _FakeTime:
    """time.time() her çağrıda 0.6s ilerler; sleep no-op → poll döngüsü 1 tur."""

    def __init__(self) -> None:
        self.t = 0.0

    def time(self) -> float:
        self.t += 0.6
        return self.t

    def sleep(self, _s) -> None:
        return None


class _FakeExLive:
    def fetch_ticker(self, symbol):
        return {"last": 100.0}

    def fetch_order_book(self, symbol, limit=5):
        return {"bids": [[99.98, 1.0]], "asks": [[100.02, 1.0]]}

    def create_order(self, **kw):
        return {"id": "L1"}

    def cancel_order(self, order_id, symbol=None):
        return {"status": "canceled"}

    def fetch_order(self, order_id, symbol=None):
        raise Exception("poll fail")


def test_ccxt_live_poll_summary_single_line(monkeypatch):
    """ccxt_live poll: hata sayacı + timeout'ta tek 'live.post_only_poll_summary'."""
    from price_action.contracts import OrderInstruction, RiskedOrder, Signal, TPLevel
    from price_action.execution import ccxt_live as ccxt_live_mod
    from price_action.execution.ccxt_live import CCXTLiveBroker

    class _TestBroker(CCXTLiveBroker):
        def _verify_live_mode(self) -> None:
            return None

    monkeypatch.setattr(ccxt_live_mod, "time", _FakeTime())

    b = _TestBroker(venue="binance", post_only_timeout_sec=1)
    b._exchange = _FakeExLive()
    rec = _RecLog()
    b._log = rec  # type: ignore[assignment]
    b._push_alert = lambda msg, source: None  # type: ignore[method-assign]

    sig = Signal(
        ts=datetime(2024, 6, 1, tzinfo=UTC),
        venue="binance",
        symbol="BTC/USDT",
        timeframe="1d",
        direction="long",
        pattern_id="bullish_pin_bar",
        confluence_score=2.5,
        sl_price=99.0,
        tp_price=103.0,
        suggested_size_atr=2.0,
    )
    ro = RiskedOrder(
        signal=sig,
        quantity=0.01,
        notional_usdt=1.0,
        leverage=1.0,
        sl_price=99.0,
        tp_levels=[TPLevel(price=103.0, fraction=1.0)],
        margin_used=1.0,
        risk_budget_consumed=0.01,
    )
    instr = OrderInstruction(risked_order=ro, priority=1.0, order_type="post_only_limit")

    fill = b.place_order(instr)

    # Akış aynı: verify fetch de fail → fail-closed None (Bug-A davranışı korunur)
    assert fill is None
    summaries = [e for e in rec.events if e[1] == "live.post_only_poll_summary"]
    assert len(summaries) == 1  # exception başına değil, TEK özet
    assert summaries[0][2].get("errors", 0) >= 1
