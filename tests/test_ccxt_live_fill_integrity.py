"""ccxt_live kardeş-bug'ları — 2 latent CRIT (dead-code, gerçek-canlı öncesi ŞART).

Bug A: post-only timeout'ta cancel exception YUTULUYOR + koşulsuz TAM-QTY market
  → limit hâlâ diri/kısmi doluysa 2× maruziyet (naked-double sınıfı).
Bug B: fill kaydı average/price yoksa ref_price'a (beklenen), filled yoksa qty'ye
  (istenen) düşüyor → hayalet fiyat/miktar journal'lanıyor, slippage sahte-0.

Fix A: cancel doğrula → hâlâ açık/bilinmiyor → REDDET (fail-closed); onaylı
  iptalse yalnız kalanı market at. Fix B: gerçek yoksa None+alarm (asla uydurma).

ccxt_live canlı v15p2 testnet yolunda DEĞİL (guard'lı, ölü kod) → canlı regresyon
sıfır; testler guard'ı subclass ile baypas edip fake exchange enjekte eder.
"""

from __future__ import annotations

from datetime import UTC, datetime

from price_action.contracts import OrderInstruction, RiskedOrder, Signal, TPLevel
from price_action.execution.ccxt_live import CCXTLiveBroker


class _TestBroker(CCXTLiveBroker):
    """Live-guard'ı baypas eden test alt-sınıfı (fake exchange enjekte edilir)."""

    def _verify_live_mode(self) -> None:
        return None


class FakeEx:
    def __init__(self, *, cancel_raises=False, fetch_order_result=None, create_seq=None):
        self.create_calls = []
        self.cancel_calls = []
        self.cancel_raises = cancel_raises
        self._fetch_order_result = fetch_order_result
        self._create_seq = list(create_seq or [])
        self._ci = 0

    def fetch_ticker(self, symbol):
        return {"last": 100.0}

    def fetch_order_book(self, symbol, limit=5):
        return {"bids": [[99.98, 5.0]], "asks": [[100.02, 5.0]]}

    def create_order(self, **kwargs):
        self.create_calls.append(kwargs)
        if self._ci < len(self._create_seq):
            res = self._create_seq[self._ci]
        else:
            res = {"id": f"ord{self._ci}"}
        self._ci += 1
        return res

    def cancel_order(self, order_id, symbol=None):
        self.cancel_calls.append(order_id)
        if self.cancel_raises:
            raise Exception("network error on cancel")

    def fetch_order(self, order_id, symbol=None):
        return self._fetch_order_result or {"id": order_id, "status": "open", "filled": 0.0}


def _broker(fake) -> _TestBroker:
    b = _TestBroker(venue="binance", post_only_timeout_sec=0)  # 0 → timeout döngüsü atlanır
    b._exchange = fake
    return b


def _instr(order_type: str = "post_only_limit", qty: float = 0.01) -> OrderInstruction:
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
        quantity=qty,
        notional_usdt=qty * 100,
        leverage=1.0,
        sl_price=99.0,
        tp_levels=[TPLevel(price=103.0, fraction=1.0)],
        margin_used=1.0,
        risk_budget_consumed=0.01,
    )
    return OrderInstruction(risked_order=ro, priority=1.0, order_type=order_type)


# ---------------------------------------------------------------------------
# Bug A — çift-pozisyon önleme
# ---------------------------------------------------------------------------


def test_bug_a_cancel_fails_refuses_double():
    """Cancel RAISE + limit hâlâ açık → 2. market ATILMAZ, None döner."""
    fake = FakeEx(cancel_raises=True, fetch_order_result={"status": "open", "filled": 0.0})
    b = _broker(fake)
    alerts = []
    b._push_alert = lambda msg, source: alerts.append(source)  # type: ignore
    fill = b.place_order(_instr("post_only_limit"))
    assert fill is None
    assert len(fake.create_calls) == 1  # yalnız ilk post-only limit; market YOK
    assert "ccxt_live_double_guard" in alerts


def test_bug_a_status_unknown_refuses_double():
    """fetch_order EXCEPTION (durum bilinmiyor) → fail-closed, market YOK."""

    class _Ex(FakeEx):
        def fetch_order(self, order_id, symbol=None):
            raise Exception("fetch fail")

    fake = _Ex(cancel_raises=False)
    b = _broker(fake)
    b._push_alert = lambda msg, source: None  # type: ignore
    fill = b.place_order(_instr("post_only_limit"))
    assert fill is None
    assert len(fake.create_calls) == 1


def test_bug_a_confirmed_cancel_markets_remainder_only():
    """Cancel onaylı + kısmi dolmuş → yalnız KALAN market'e (tam qty değil)."""
    fake = FakeEx(
        cancel_raises=False,
        fetch_order_result={"status": "canceled", "filled": 0.004},
        create_seq=[
            {"id": "L1"},  # ilk post-only limit
            {"id": "M2", "filled": 0.006, "average": 100.1},  # remainder market (10bps<25)
        ],
    )
    b = _broker(fake)
    fill = b.place_order(_instr("post_only_limit", qty=0.01))
    assert fill is not None
    assert len(fake.create_calls) == 2
    market_call = fake.create_calls[1]
    assert market_call["type"] == "market"
    assert abs(market_call["amount"] - 0.006) < 1e-9  # kalan = 0.01 - 0.004
    assert abs(fill.quantity - 0.01) < 1e-9  # toplam = kısmi(0.004) + market(0.006)


def test_bug_a_race_closed_no_market():
    """Cancel öncesi limit tam dolmuş (status=closed) → market GEREKMEZ."""
    fake = FakeEx(
        cancel_raises=False,
        fetch_order_result={"status": "closed", "filled": 0.01, "average": 100.2},
        create_seq=[{"id": "L1"}],
    )
    b = _broker(fake)
    fill = b.place_order(_instr("post_only_limit", qty=0.01))
    assert fill is not None
    assert len(fake.create_calls) == 1  # market yok
    assert abs(fill.quantity - 0.01) < 1e-9
    assert abs(fill.price - 100.2) < 1e-9


# ---------------------------------------------------------------------------
# Bug B — hayalet fill kaydı önleme
# ---------------------------------------------------------------------------


def test_bug_b_no_fill_data_returns_none():
    """average/price + filled YOK → uydurma değer yazmak yerine None + alarm."""
    fake = FakeEx(create_seq=[{"id": "M1"}])  # ne filled ne average
    b = _broker(fake)
    alerts = []
    b._push_alert = lambda msg, source: alerts.append(source)  # type: ignore
    fill = b.place_order(_instr("market"))
    assert fill is None  # eski kod ref_price + qty ile hayalet Fill üretirdi
    assert "ccxt_live_no_fill" in alerts


def test_bug_b_genuine_fill_recorded():
    """Gerçek average/filled var → doğru Fill (over-reject yok)."""
    fake = FakeEx(create_seq=[{"id": "M1", "filled": 0.01, "average": 100.0}])
    b = _broker(fake)
    fill = b.place_order(_instr("market"))
    assert fill is not None
    assert abs(fill.quantity - 0.01) < 1e-9  # qty fallback değil, gerçek filled
    assert abs(fill.price - 100.0) < 1e-9


def test_bug_b_partial_fill_not_inflated_to_qty():
    """Kısmi fill (0.006/0.01) → istenen qty'ye ŞİŞİRİLMEZ."""
    fake = FakeEx(create_seq=[{"id": "M1", "filled": 0.006, "average": 100.0}])
    b = _broker(fake)
    fill = b.place_order(_instr("market", qty=0.01))
    assert fill is not None
    assert abs(fill.quantity - 0.006) < 1e-9  # gerçek kısmi, 0.01 değil


# ---------------------------------------------------------------------------
# Kaynak-pin
# ---------------------------------------------------------------------------


def test_source_pins_no_phantom_fallbacks():
    from pathlib import Path

    src = (
        Path(__file__).resolve().parents[1] / "src" / "price_action" / "execution" / "ccxt_live.py"
    ).read_text(encoding="utf-8")
    assert 'or order.get("price") or ref_price' not in src  # eski hayalet fiyat
    assert 'float(order.get("filled", qty))' not in src  # eski hayalet miktar
    assert "_push_alert" in src
    assert "still_resting" in src
