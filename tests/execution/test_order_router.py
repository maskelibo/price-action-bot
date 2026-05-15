"""Order Router testleri — dry run senaryoları (testnet replay).

Gerçek exchange çağrısı yapılmaz — mock exchange kullanılır.
Senaryolar: filled, duplicate, rejected (risk), cap_exceeded, slippage_exceeded.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ----- fixture: mock signal dict -----

def _make_signal_dict(sym="BTC/USDT", side="long"):
    return {
        "ts": datetime.now(timezone.utc),
        "symbol": sym,
        "strategy": "engulfing_continuation",
        "side": side,
        "sl_price": 60000.0,
        "tp_price": 70000.0,
        "confluence": 0.6,
        "entry_price": 65000.0,
    }


def _make_mock_exchange(last_price=65000.0, fill_avg=65100.0, fill_qty=0.01):
    ex = MagicMock()
    ex.fetch_ticker.return_value = {"last": last_price}
    ex.create_market_order.return_value = {
        "id": f"EX_{uuid.uuid4().hex[:8]}",
        "filled": fill_qty,
        "average": fill_avg,
        "fee": {"cost": 0.048},
        "status": "closed",
    }
    ex.set_leverage.return_value = None
    return ex


def _make_mock_risked(qty=0.01, notional=650.0, leverage=3.0):
    risked = MagicMock()
    risked.quantity = qty
    risked.notional_usdt = notional
    risked.leverage = leverage
    # Pydantic-like: hasattr(risked, "quantity") → True
    return risked


def _make_mock_account(free_margin=5000.0):
    acc = MagicMock()
    acc.free_margin_usdt = free_margin
    acc.equity_usdt = free_margin
    acc.open_positions = []
    return acc


@pytest.fixture
def router_env(tmp_path):
    """Geçici DB'lerle yalıtılmış router ortamı."""
    idem_db = tmp_path / "idem.duckdb"
    slip_db = tmp_path / "slip.duckdb"
    return {"idem_db": idem_db, "slip_db": slip_db, "tmp_path": tmp_path}


def _patch_router(tmp_path):
    """order_router singleton'larını tmp DB'ye yönlendir."""
    from price_action.execution import idempotency, slippage_tracker
    idem = idempotency.IdempotencyStore(tmp_path / "idem.duckdb")
    slip = slippage_tracker.SlippageTracker(tmp_path / "slip.duckdb")
    return idem, slip


def test_route_filled(tmp_path):
    """Normal fill senaryosu."""
    from price_action.execution import order_router

    ex = _make_mock_exchange(last_price=65000.0, fill_avg=65065.0)  # 10 bps slip
    risk_officer = MagicMock()
    risk_officer.evaluate.return_value = _make_mock_risked()
    account = _make_mock_account()
    returns_df = MagicMock()

    idem, slip = _patch_router(tmp_path)
    with patch.object(order_router, "get_idempotency_store", return_value=idem), \
         patch.object(order_router, "get_slippage_tracker", return_value=slip):
        result = order_router.route_signal(
            _make_signal_dict(), ex, risk_officer, account, returns_df
        )

    assert result["status"] == "filled"
    assert result["symbol"] == "BTC/USDT"
    assert "slippage_bps" in result
    assert result["slippage_bps"] < 25.0


def test_route_duplicate(tmp_path):
    """Aynı sinyal iki kez → ikinci 'duplicate' dönmeli."""
    from price_action.execution import order_router

    ex = _make_mock_exchange()
    risk_officer = MagicMock()
    risk_officer.evaluate.return_value = _make_mock_risked()
    account = _make_mock_account()

    idem, slip = _patch_router(tmp_path)
    sig = _make_signal_dict()

    with patch.object(order_router, "get_idempotency_store", return_value=idem), \
         patch.object(order_router, "get_slippage_tracker", return_value=slip):
        r1 = order_router.route_signal(sig, ex, risk_officer, account, MagicMock())
        r2 = order_router.route_signal(sig, ex, risk_officer, account, MagicMock())

    assert r1["status"] == "filled"
    assert r2["status"] == "duplicate"
    # Exchange çağrısı sadece 1 kez
    assert ex.create_market_order.call_count == 1


def test_route_risk_rejected(tmp_path):
    """RiskOfficer reddi → 'rejected' dönmeli."""
    from price_action.execution import order_router

    ex = _make_mock_exchange()
    reject = MagicMock(spec=[])  # no "quantity" attr → Reject
    reject.reason = "dd_breaker"
    risk_officer = MagicMock()
    risk_officer.evaluate.return_value = reject
    account = _make_mock_account()

    idem, slip = _patch_router(tmp_path)
    with patch.object(order_router, "get_idempotency_store", return_value=idem), \
         patch.object(order_router, "get_slippage_tracker", return_value=slip):
        result = order_router.route_signal(
            _make_signal_dict(), ex, risk_officer, account, MagicMock()
        )

    assert result["status"] == "rejected"
    assert "dd_breaker" in result["reason"]
    assert ex.create_market_order.call_count == 0


def test_route_insufficient_margin(tmp_path):
    """Yetersiz margin → 'rejected' dönmeli."""
    from price_action.execution import order_router

    ex = _make_mock_exchange()
    risk_officer = MagicMock()
    # RiskOfficer onay verdi (büyük notional)
    risk_officer.evaluate.return_value = _make_mock_risked(notional=5000.0, leverage=1.0)
    account = _make_mock_account(free_margin=100.0)  # 100 USDT free, 5000 lazım

    idem, slip = _patch_router(tmp_path)
    with patch.object(order_router, "get_idempotency_store", return_value=idem), \
         patch.object(order_router, "get_slippage_tracker", return_value=slip):
        result = order_router.route_signal(
            _make_signal_dict(), ex, risk_officer, account, MagicMock()
        )

    assert result["status"] == "rejected"
    assert "margin" in result["reason"]


def test_route_slippage_exceeded(tmp_path):
    """Slippage > 25 bps → 'rejected' dönmeli."""
    from price_action.execution import order_router

    # Yüksek slippage: ref 65000, fill 65200 = 30.8 bps
    ex = _make_mock_exchange(last_price=65000.0, fill_avg=65200.0)
    risk_officer = MagicMock()
    risk_officer.evaluate.return_value = _make_mock_risked()
    account = _make_mock_account()

    idem, slip = _patch_router(tmp_path)
    with patch.object(order_router, "get_idempotency_store", return_value=idem), \
         patch.object(order_router, "get_slippage_tracker", return_value=slip):
        result = order_router.route_signal(
            _make_signal_dict(), ex, risk_officer, account, MagicMock(),
            max_slippage_bps=25.0,
        )

    assert result["status"] == "rejected"
    assert "slippage" in result["reason"]


def test_route_capital_cap(tmp_path):
    """Notional > cap → 'cap_exceeded' dönmeli."""
    from price_action.execution import order_router

    ex = _make_mock_exchange()
    risk_officer = MagicMock()
    # Büyük notional: 2000 USDT
    risk_officer.evaluate.return_value = _make_mock_risked(notional=2000.0)
    account = _make_mock_account()

    idem, slip = _patch_router(tmp_path)
    with patch.object(order_router, "get_idempotency_store", return_value=idem), \
         patch.object(order_router, "get_slippage_tracker", return_value=slip):
        result = order_router.route_signal(
            _make_signal_dict(), ex, risk_officer, account, MagicMock(),
            capital_cap_usdt=1000.0,
        )

    assert result["status"] == "cap_exceeded"
    assert result["cap"] == 1000.0
    assert ex.create_market_order.call_count == 0
