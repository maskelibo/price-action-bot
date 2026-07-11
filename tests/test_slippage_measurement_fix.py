"""Slippage ölçüm tamiri — execution paketi 2026-07-10 (0.0 bps bug).

Kök-neden (DB-kanıtlı: 269/303 fill = 0.0, HER sıfır expected==realized):
  Fix A (koruma TP/SL): daemon `_prot_fill_px`'i HEM expected HEM realized
    geçiyordu → fill kendi benchmark'ı → %100 exit 0.0 bps by construction.
  Fix B (giriş): `realized_price=_avg_px`; _avg_px borsa avg vermezse _cur_px'e
    (arrival) düşüyordu → realized==expected → sahte 0.0 (167 market girişi).

İki fix de MEASUREMENT-ONLY: _avg_px/_prot_fill_px (journal/idem/notional) ve
hiçbir trade-kararı değişkeni değişmez; yalnız slippage kaydının referansı düzelir.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path

import duckdb
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

import scripts.futures_daemon as fd  # noqa: E402

from price_action.execution.slippage_tracker import (  # noqa: E402
    SlippageTracker,
    execution_evidence_values_match,
)

# ---------------------------------------------------------------------------
# Pure helper: _slip_expected_from_trigger (Fix A referansı)
# ---------------------------------------------------------------------------


def test_expected_from_trigger_uses_trigger_when_positive():
    assert fd._slip_expected_from_trigger(100.0, 99.5) == 100.0


def test_expected_from_trigger_falls_back_to_fill_when_trigger_zero():
    # trigger yoksa (0) → fill'e döner = dürüst-0 (expected==realized)
    assert fd._slip_expected_from_trigger(0.0, 99.5) == 99.5


def test_expected_from_trigger_falls_back_when_trigger_none():
    assert fd._slip_expected_from_trigger(None, 99.5) == 99.5


# ---------------------------------------------------------------------------
# Pure helper: _slip_realized_from_order (Fix B gerçek-fiyat türetici)
# ---------------------------------------------------------------------------


def test_realized_from_order_prefers_order_average():
    assert fd._slip_realized_from_order(50.2, 50.1, 50.3) == 50.2


def test_realized_from_order_falls_to_price_then_fetched():
    assert fd._slip_realized_from_order(None, 50.1, 50.3) == 50.1
    assert fd._slip_realized_from_order(None, None, 50.3) == 50.3


def test_realized_from_order_none_when_unmeasurable():
    # Hiçbir gerçek fiyat yok → None (çağıran arrival'a düşer, sahte değer YAZMAZ)
    assert fd._slip_realized_from_order(None, None, None) is None
    assert fd._slip_realized_from_order(0, 0, 0) is None


def test_realized_from_order_skips_non_numeric():
    assert fd._slip_realized_from_order("x", None, 50.3) == 50.3


# ---------------------------------------------------------------------------
# record_fill DAVRANIŞI — protective (Fix A) uçtan uca
# ---------------------------------------------------------------------------


def _tracker(tmp_path) -> SlippageTracker:
    return SlippageTracker(db_path=tmp_path / "fills.duckdb")


def test_protective_old_bug_shape_records_zero(tmp_path):
    """ESKİ hata belgesi: expected==realized (ikisi de _prot_fill_px) → 0.0."""
    st = _tracker(tmp_path)
    bps = st.record_fill(
        fill_id="prot_x_sl",
        ts=datetime.now(UTC),
        symbol="DOGE/USDT",
        strategy="vsa_sl",
        side="long",
        expected_price=100.0,
        realized_price=100.0,  # eski daemon şekli
        quantity=10.0,
        fee_usdt=0.0,
        is_maker=False,
        order_type="algo_stop_market",
        mode="paper",
        fill_type="sl",
        fill_role="exit",
        tf="15m",
    )
    assert bps == 0.0  # bug: fill kendi benchmark'ı


def test_protective_fixed_shape_records_real_slippage(tmp_path):
    """LONG exit is a sell: filling below the trigger is a +50bps cost."""
    st = _tracker(tmp_path)
    # daemon artık _slip_expected_from_trigger(trigger, fill) geçiyor
    expected = fd._slip_expected_from_trigger(100.0, 99.5)
    bps = st.record_fill(
        fill_id="prot_y_sl",
        ts=datetime.now(UTC),
        symbol="DOGE/USDT",
        strategy="vsa_sl",
        side="long",
        expected_price=expected,
        realized_price=99.5,
        quantity=10.0,
        fee_usdt=0.0,
        is_maker=False,
        order_type="algo_stop_market",
        mode="paper",
        fill_type="sl",
        fill_role="exit",
        tf="15m",
    )
    assert bps == 50.0  # 0.5% = 50bps adverse sell slippage


def test_long_exit_fill_above_trigger_is_negative_favorable_cost(tmp_path):
    """XLM case: sell stop filled above trigger, therefore execution improved."""
    st = _tracker(tmp_path)
    bps = st.record_fill(
        fill_id="prot_xlm_sl",
        ts=datetime.now(UTC),
        symbol="XLM/USDT",
        strategy="vsa_sl",
        side="long",
        expected_price=0.18834,
        realized_price=0.18870,
        quantity=3845.0,
        fee_usdt=0.2902206,
        fee_source="exchange_user_trades",
        is_maker=False,
        order_type="algo_stop_market",
        mode="paper",
        fill_type="sl",
        fill_role="exit",
        tf="15m",
    )
    assert bps == pytest.approx(-19.114367633, rel=1e-10)


# ---------------------------------------------------------------------------
# Protective execution truth — actual order trades / commission
# ---------------------------------------------------------------------------


class _FakeUserTradesExchange:
    def __init__(self, rows=None, exc: Exception | None = None):
        self.rows = rows or []
        self.exc = exc
        self.calls = []

    def fapiPrivateGetUserTrades(self, params):  # noqa: N802 - CCXT API name
        self.calls.append(params)
        if self.exc is not None:
            raise self.exc
        return self.rows


class _FakeMultiOrderTradesExchange:
    def __init__(self, rows_by_order):
        self.rows_by_order = rows_by_order
        self.calls = []

    def fapiPrivateGetUserTrades(self, params):  # noqa: N802 - CCXT API name
        self.calls.append(params)
        return self.rows_by_order.get(str(params["orderId"]), [])


def test_protection_execution_uses_actual_order_trades_and_commission():
    ex = _FakeUserTradesExchange(
        rows=[
            {
                "orderId": 777,
                "price": "100.0",
                "qty": "1.0",
                "quoteQty": "100.0",
                "commission": "0.0400",
                "commissionAsset": "USDT",
                "maker": False,
            },
            {
                "orderId": "777",
                "price": "101.0",
                "qty": "2.0",
                "quoteQty": "202.0",
                "commission": "0.0808",
                "commissionAsset": "USDT",
                "maker": False,
            },
            {
                "orderId": 999,
                "price": "500.0",
                "qty": "1.0",
                "quoteQty": "500.0",
                "commission": "9.9",
                "commissionAsset": "USDT",
                "maker": False,
            },
        ]
    )

    execution = fd._protection_execution_from_user_trades(
        ex,
        "BTCUSDT",
        {"algoId": "123", "actualOrderId": "777", "orderType": "STOP_MARKET"},
        fallback_price=99.5,
        fallback_quantity=4.0,
    )

    assert ex.calls == [{"symbol": "BTCUSDT", "orderId": 777, "limit": 1000}]
    assert execution["actual_order_id"] == "777"
    assert execution["price"] == 302.0 / 3.0
    assert execution["quantity"] == 3.0
    assert execution["price_verified"] is True
    assert execution["price_source"] == "exchange_user_trades"
    assert execution["fee_usdt"] == 0.1208
    assert execution["fee_source"] == "exchange_user_trades"
    assert execution["is_maker"] is False


def test_protection_execution_without_exact_order_id_fails_closed():
    ex = _FakeUserTradesExchange()
    execution = fd._protection_execution_from_user_trades(
        ex,
        "BTCUSDT",
        {"algoId": "123", "orderType": "STOP_MARKET"},
        fallback_price=99.5,
        fallback_quantity=4.0,
    )

    assert ex.calls == []
    assert execution["actual_order_id"] == ""
    assert execution["price"] == 99.5
    assert execution["quantity"] == 4.0
    assert execution["price_verified"] is False
    assert execution["price_source"] == "unavailable"
    assert execution["fee_usdt"] is None
    assert execution["fee_source"] == "unavailable"
    assert execution["is_maker"] is False


def test_protection_execution_rejects_non_usdt_commission_as_usdt():
    ex = _FakeUserTradesExchange(
        rows=[
            {
                "orderId": 777,
                "price": "100.0",
                "qty": "1.0",
                "quoteQty": "100.0",
                "commission": "0.001",
                "commissionAsset": "BNB",
                "maker": False,
            }
        ]
    )
    execution = fd._protection_execution_from_user_trades(
        ex,
        "BTCUSDT",
        {"actualOrderId": "777", "orderType": "STOP_MARKET"},
        fallback_price=99.5,
        fallback_quantity=1.0,
    )

    assert execution["price"] == 100.0
    assert execution["quantity"] == 1.0
    assert execution["price_verified"] is True
    assert execution["fee_usdt"] is None
    assert execution["fee_source"] == "unsupported_asset:BNB"
    assert execution["is_maker"] is False


def test_partial_protection_user_trade_fill_is_persisted_exactly_once(tmp_path, monkeypatch):
    """TP1 replay keeps one deterministic execution_fills row with exact fee."""
    ex = _FakeUserTradesExchange(
        rows=[
            {
                "orderId": 777,
                "price": "100.05",
                "qty": "0.25",
                "quoteQty": "25.0125",
                "commission": "0.010005",
                "commissionAsset": "USDT",
                "maker": False,
            }
        ]
    )
    triggered = {
        "algoId": "501",
        "actualOrderId": "777",
        "orderType": "TAKE_PROFIT_MARKET",
    }
    execution = fd._protection_execution_from_user_trades(
        ex,
        "BTCUSDT",
        triggered,
        fallback_price=100.0,
        fallback_quantity=0.25,
    )
    tracker = SlippageTracker(db_path=tmp_path / "execution_fills.duckdb")
    jsonl_writes = []
    monkeypatch.setattr(
        tracker,
        "_write_jsonl",
        lambda *args, **kwargs: jsonl_writes.append((args, kwargs)),
    )
    kwargs = {
        "prot_id": "prot-partial-1",
        "triggered_kind": "tp1",
        "triggered_order": triggered,
        "execution": execution,
        "trigger_price": 100.0,
        "fill_price": execution["price"],
        "ts": datetime(2026, 7, 11, tzinfo=UTC),
        "symbol": "BTC/USDT",
        "strategy": "vsa",
        "side": "long",
        "fallback_quantity": 1.0,
        "tracker": tracker,
    }

    assert fd._record_protection_fill_evidence(**kwargs) is True
    assert fd._record_protection_fill_evidence(**kwargs) is True
    assert len(jsonl_writes) == 1

    with duckdb.connect(str(tmp_path / "execution_fills.duckdb"), read_only=True) as con:
        rows = con.execute(
            """SELECT fill_id, realized_price, quantity, fee_usdt, fee_source,
                      fill_role, exchange_order_id
               FROM fills"""
        ).fetchall()
    assert rows == [
        (
            "prot_prot-partial-1_tp1",
            100.05,
            0.25,
            0.010005,
            "exchange_user_trades",
            "exit",
            "777",
        )
    ]


def test_entry_execution_aggregates_mixed_order_ids_with_exact_commission():
    maker_notional = 104.14604
    taker_notional = 642.31906
    ex = _FakeMultiOrderTradesExchange(
        {
            "543048866": [
                {
                    "orderId": 543048866,
                    "price": str(maker_notional / 538.0),
                    "qty": "538",
                    "quoteQty": str(maker_notional),
                    "commission": "0.02082915",
                    "commissionAsset": "USDT",
                    "maker": True,
                }
            ],
            "543051193": [
                {
                    "orderId": 543051193,
                    "price": str(taker_notional / 3307.0),
                    "qty": "3307",
                    "quoteQty": str(taker_notional),
                    "commission": "0.2569276",
                    "commissionAsset": "USDT",
                    "maker": False,
                }
            ],
        }
    )
    order = {
        "id": "543051193",
        "partial_limit_order_id": "543048866",
        "market_fallback_order_id": "543051193",
    }

    execution = fd._entry_execution_from_user_trades(ex, "XLMUSDT", order)

    assert [call["orderId"] for call in ex.calls] == [543048866, 543051193]
    assert execution["complete"] is True
    assert execution["quantity"] == 3845.0
    assert execution["notional_usdt"] == maker_notional + taker_notional
    assert execution["price"] == (maker_notional + taker_notional) / 3845.0
    assert execution["fee_usdt"] == 0.27775675
    assert execution["fee_source"] == "exchange_user_trades"
    assert execution["maker_quantity"] == 538.0
    assert execution["maker_notional_usdt"] == maker_notional


def test_entry_execution_missing_one_leg_returns_no_estimate():
    ex = _FakeMultiOrderTradesExchange(
        {
            "543048866": [
                {
                    "orderId": 543048866,
                    "price": "0.097",
                    "qty": "538",
                    "quoteQty": "52.186",
                    "commission": "0.0208744",
                    "commissionAsset": "USDT",
                    "maker": True,
                }
            ]
        }
    )
    execution = fd._entry_execution_from_user_trades(
        ex,
        "XLMUSDT",
        {
            "partial_limit_order_id": "543048866",
            "market_fallback_order_id": "543051193",
        },
    )

    assert execution["complete"] is False
    assert execution["fee_usdt"] is None
    assert execution["fee_source"] == "unavailable"
    assert execution["quantity"] is None
    assert execution["price"] is None


def test_position_delta_evidence_recovers_exact_new_entry_qty_and_price():
    before = {"positions_ok": True, "positions": []}
    after = {
        "positions_ok": True,
        "positions": [
            {
                "symbol": "XLM/USDT:USDT",
                "side": "long",
                "contracts": 3845,
                "entryPrice": 0.0971,
            }
        ],
    }

    evidence = fd._entry_position_delta_evidence(before, after, "XLM/USDT", "long")
    assert evidence == {
        "complete": True,
        "quantity": 3845.0,
        "price": 0.0971,
        "notional_usdt": 373.3495,
        "source": "exchange_position_delta",
    }


def test_position_delta_evidence_rejects_stale_or_non_increasing_state():
    before = {
        "positions_ok": True,
        "positions": [
            {"symbol": "XLM/USDT:USDT", "side": "long", "contracts": 10, "entryPrice": 1}
        ],
    }
    stale_after = {"positions_ok": False, "positions": []}
    same_after = {
        "positions_ok": True,
        "positions": [
            {"symbol": "XLM/USDT:USDT", "side": "long", "contracts": 10, "entryPrice": 1}
        ],
    }
    assert (
        fd._entry_position_delta_evidence(before, stale_after, "XLM/USDT", "long")["complete"]
        is False
    )
    assert (
        fd._entry_position_delta_evidence(before, same_after, "XLM/USDT", "long")["complete"]
        is False
    )


def test_entry_position_baseline_is_signed_and_stale_state_is_not_flat():
    trusted = {
        "positions_ok": True,
        "positions": [
            {
                "symbol": "NEAR/USDT:USDT",
                "side": "short",
                "contracts": 394,
                "entryPrice": 1.871,
                "info": {"positionAmt": "-394"},
            }
        ],
    }
    assert fd._entry_position_baseline(trusted, "NEAR/USDT") == (-394.0, 1.871)
    assert fd._entry_position_baseline(trusted, "XLM/USDT") == (0.0, None)
    assert fd._entry_position_baseline({"positions_ok": False}, "XLM/USDT") == (None, None)


def test_execution_evidence_tolerance_accepts_rounding_dust_only():
    assert execution_evidence_values_match(100.0, 100.0000005) is True
    assert execution_evidence_values_match(2.0, 2.000000001) is True
    assert execution_evidence_values_match(100.0, 100.01) is False
    assert execution_evidence_values_match(True, 1.0) is False
    assert execution_evidence_values_match(float("nan"), 1.0) is False


# ---------------------------------------------------------------------------
# record_fill DAVRANIŞI — entry (Fix B) uçtan uca
# ---------------------------------------------------------------------------


def test_legacy_entry_unmeasurable_fallback_shape_would_record_false_zero(tmp_path):
    """Eski şeklin neden karantinaya alındığını belgeler."""
    st = _tracker(tmp_path)
    cur_px = 50.0
    realized = fd._slip_realized_from_order(None, None, None)  # -> None
    bps = st.record_fill(
        fill_id="entry_1",
        ts=datetime.now(UTC),
        symbol="X/USDT",
        strategy="grimes",
        side="long",
        expected_price=cur_px,
        realized_price=(realized if realized else cur_px),
        quantity=1.0,
        fee_usdt=0.0,
        is_maker=False,
        order_type="market",
        mode="paper",
        fill_type="entry",
        tf="15m",
    )
    assert bps == 0.0


def test_entry_genuine_average_records_real_slippage(tmp_path):
    """FIX B: borsa avg=50.2, arrival=50.0 → 40 bps (eski kod 0.0 yazardı)."""
    st = _tracker(tmp_path)
    cur_px = 50.0
    realized = fd._slip_realized_from_order(None, None, 50.2)  # fetch avg
    bps = st.record_fill(
        fill_id="entry_2",
        ts=datetime.now(UTC),
        symbol="X/USDT",
        strategy="grimes",
        side="long",
        expected_price=cur_px,
        realized_price=(realized if realized else cur_px),
        quantity=1.0,
        fee_usdt=0.0,
        is_maker=False,
        order_type="market",
        mode="paper",
        fill_type="entry",
        tf="15m",
    )
    assert abs(bps - 40.0) < 1e-9


def test_entry_correct_fills_unchanged_regression(tmp_path):
    """REGRESYON KALKANI: borsa avg zaten mevcut olan 34 doğru fill AYNI kalır.
    _slip_realized_from_order(order_avg) == eski _avg_px → aynı bps."""
    st = _tracker(tmp_path)
    cur_px = 50.0
    # eski davranış: _avg_px = order.average = 50.15
    realized = fd._slip_realized_from_order(50.15, None, None)
    assert realized == 50.15  # _avg_px ile birebir aynı kaynak
    bps = st.record_fill(
        fill_id="entry_3",
        ts=datetime.now(UTC),
        symbol="X/USDT",
        strategy="grimes",
        side="long",
        expected_price=cur_px,
        realized_price=realized,
        quantity=1.0,
        fee_usdt=0.0,
        is_maker=False,
        order_type="limit",
        mode="paper",
        fill_type="entry",
        tf="15m",
    )
    assert abs(bps - 30.0) < 1e-9  # (50.15-50)/50*1e4 = 30bps, eskisiyle aynı


# ---------------------------------------------------------------------------
# Kaynak-pin: daemon çağrı yerleri fix'leri gerçekten kullanıyor
# ---------------------------------------------------------------------------


def test_daemon_source_wires_both_fixes():
    src = (ROOT / "scripts" / "futures_daemon.py").read_text(encoding="utf-8")
    # Fix A: koruma expected'i trigger helper'ından
    assert "_slip_expected_from_trigger(" in src
    assert "expected_price=_prot_fill_px,\n" not in src  # eski aynı-değişken şekli gitti
    # Fix B: giriş realized'i ayrı ölçüm değişkeninden, _avg_px değil
    assert "_slip_realized_px" in src
    assert "realized_price=_avg_px,\n" not in src  # eski journal-değeri realized gitti
    assert "_slip_realized_from_order(" in src
    # Maker KPI fix: protection market fill exit/taker, ücret exact userTrades'ten.
    assert "_protection_execution_from_user_trades(" in src
    assert "_prot_fee_bps = 4.0" not in src
    assert "is_maker=False," in src
    assert 'fill_role="exit",' in src
    assert 'fill_role="entry",' in src
    assert "PROT_SLIP_UNVERIFIED" in src
    assert '_order.get("partial_limit_qty")' in src
    assert "maker_quantity=_entry_maker_qty" in src
    assert "maker_notional_usdt=_entry_maker_notional" in src
    assert "_entry_execution_from_user_trades(" in src
    assert "_entry_position_delta_evidence(" in src
    assert "_entry_position_baseline(" in src
    # Queue builder owns the durable schema; both daemon call sites must pass
    # the signed pre-submit baseline through that typed helper.
    assert '"pre_submit_position_qty": pre_submit_position_qty' in src
    assert "pre_submit_position_qty=_pre_submit_position_qty" in src
    assert '"pre_submit_position_qty": pre_submit_position_qty' in src
    assert "_entry_wal.update(_entry_exc.to_queue_fields())" in src
    assert "15M_FILL_UNVERIFIED_CRITICAL" in src
    assert "using intended qty=" not in src
    assert 'fee_source="estimated"' not in src


def test_slippage_tracker_has_module_json_import():
    """json modül-seviyesinde import edilmeli (outlier yolu NameError yemesin)."""
    src = (ROOT / "src" / "price_action" / "execution" / "slippage_tracker.py").read_text(
        encoding="utf-8"
    )
    assert "\nimport json\n" in src
