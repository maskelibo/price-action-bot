"""CT-EXE-02 remediation testleri — borsa income-tabanlı realized PnL yazımı.

Kapsam:
- fetch_realized_income: income tiplerini doğru topluyor (REALIZED_PNL+COMMISSION+
  FUNDING_FEE), ilgisizleri eliyor, hata/boş → None (best-effort sözleşmesi).
- record_close(realized_pnl_override): override yazılır (lokal hesap DEĞİL);
  None → eski lokal (exit-entry)*qty (geriye uyum).
- get_partial_pnl_sum: çift-sayma önleme için partial toplamı.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from price_action.execution.exchange_income import fetch_realized_income, to_symbol_id
from price_action.execution.trade_journal import TradeJournal


class _FakeExchange:
    def __init__(self, rows, raise_exc=False):
        self._rows = rows
        self._raise = raise_exc
        self.last_params = None

    def fapiPrivateGetIncome(self, params):
        self.last_params = params
        if self._raise:
            raise RuntimeError("borsa 500")
        return self._rows


def test_to_symbol_id():
    assert to_symbol_id("AVAX/USDT:USDT") == "AVAXUSDT"
    assert to_symbol_id("AVAX/USDT") == "AVAXUSDT"
    assert to_symbol_id("BTCUSDT") == "BTCUSDT"


def test_fetch_income_sums_relevant_types():
    rows = [
        {"incomeType": "REALIZED_PNL", "income": "-40.99"},
        {"incomeType": "COMMISSION", "income": "-0.85"},
        {"incomeType": "FUNDING_FEE", "income": "0.12"},
        {"incomeType": "TRANSFER", "income": "1000.0"},  # ilgisiz — elenmeli
    ]
    ex = _FakeExchange(rows)
    got = fetch_realized_income(ex, "ATOM/USDT:USDT", start_ms=1)
    assert got == pytest.approx(-40.99 - 0.85 + 0.12)
    assert ex.last_params["symbol"] == "ATOMUSDT"
    assert ex.last_params["startTime"] == 1


def test_fetch_income_empty_returns_none():
    # Hiç ilgili satır yok → None (caller eski davranışa düşer, 0 YAZMAZ)
    ex = _FakeExchange([{"incomeType": "TRANSFER", "income": "5"}])
    assert fetch_realized_income(ex, "X/USDT", start_ms=1) is None


def test_fetch_income_exception_returns_none():
    ex = _FakeExchange([], raise_exc=True)
    assert fetch_realized_income(ex, "X/USDT", start_ms=1) is None


def _close_kwargs(**over):
    base = dict(
        trade_id="sig-1",
        ts_open=datetime(2026, 6, 14, 10, 0, tzinfo=UTC),
        ts_close=datetime(2026, 6, 14, 12, 0, tzinfo=UTC),
        sym="ATOM/USDT",
        side="long",
        strategy="grimes_abc",
        entry_price=2.50,
        exit_price=2.40,  # lokal long PnL = (2.40-2.50)*100 = -10.0
        qty=100.0,
        sl_price=2.30,
    )
    base.update(over)
    return base


def test_record_close_override_used(tmp_path):
    db = str(tmp_path / "j.duckdb")
    tj = TradeJournal(db_path=db)
    # override = borsa income (fee dahil) = -42.50; lokal hesap -10.0 OLMAMALI
    assert tj.record_close(**_close_kwargs(realized_pnl_override=-42.50)) is True
    pnl = tj.get_realized_pnl_window(
        datetime(2026, 6, 14, 0, 0, tzinfo=UTC), datetime(2026, 6, 15, 0, 0, tzinfo=UTC)
    )
    assert pnl == pytest.approx(-42.50)


def test_record_close_no_override_local_calc(tmp_path):
    db = str(tmp_path / "j.duckdb")
    tj = TradeJournal(db_path=db)
    assert tj.record_close(**_close_kwargs()) is True  # override yok → lokal
    pnl = tj.get_realized_pnl_window(
        datetime(2026, 6, 14, 0, 0, tzinfo=UTC), datetime(2026, 6, 15, 0, 0, tzinfo=UTC)
    )
    assert pnl == pytest.approx(-10.0)  # (2.40-2.50)*100


def test_get_partial_pnl_sum(tmp_path):
    db = str(tmp_path / "j.duckdb")
    tj = TradeJournal(db_path=db)
    assert tj.get_partial_pnl_sum("sig-1") == 0.0  # partial yok
    tj.record_partial_close(
        close_id="sig-1_tp1",
        trade_id="sig-1",
        ts_close=datetime(2026, 6, 14, 11, 0, tzinfo=UTC),
        sym="ATOM/USDT",
        side="long",
        strategy="grimes_abc",
        entry_price=2.50,
        exit_price=2.70,  # +0.20*25 = +5.0
        qty_closed=25.0,
        sl_price=2.30,
        close_reason="tp1",
    )
    assert tj.get_partial_pnl_sum("sig-1") == pytest.approx(5.0)


def test_runner_income_avoids_double_count(tmp_path):
    """heal/in-daemon: override = FULL income − partial_sum = runner dilimi.

    Senaryo: trade FULL income borsada -30 (TP1 +5 partial + runner -35).
    partial_closes'ta +5 zaten var. record_close'a -35 (=-30-5) geçilmeli →
    toplam (partial +5) + (final -35) = -30 = FULL income (çift-sayma yok).
    """
    db = str(tmp_path / "j.duckdb")
    tj = TradeJournal(db_path=db)
    tj.record_partial_close(
        close_id="sig-1_tp1",
        trade_id="sig-1",
        ts_close=datetime(2026, 6, 14, 11, 0, tzinfo=UTC),
        sym="ATOM/USDT",
        side="long",
        strategy="g",
        entry_price=2.50,
        exit_price=2.70,
        qty_closed=25.0,  # +5.0
        sl_price=2.30,
        close_reason="tp1",
    )
    full_income = -30.0
    runner = full_income - tj.get_partial_pnl_sum("sig-1")  # -30 - 5 = -35
    tj.record_close(**_close_kwargs(qty=75.0, realized_pnl_override=runner))
    total = tj.get_realized_pnl_window(
        datetime(2026, 6, 14, 0, 0, tzinfo=UTC), datetime(2026, 6, 15, 0, 0, tzinfo=UTC)
    )
    assert total == pytest.approx(full_income)  # -30, çift sayım yok
