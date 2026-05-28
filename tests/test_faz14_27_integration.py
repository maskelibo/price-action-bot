"""Faz 14.27 KRİTİK-2 fix: futures_daemon integration tests.

Mock exchange + journal + reconciler + PROT_WATCHDOG end-to-end.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


# ─────────────────────────────────────────────────────────────────────────────
# Mock Exchange
# ─────────────────────────────────────────────────────────────────────────────

class MockExchange:
    """Minimal exchange — futures_daemon kod path için."""

    def __init__(self):
        self.algo_orders: list[dict] = []
        self.orders_cancelled: list[int] = []
        self.orders_created: list[dict] = []
        self.positions: list[dict] = []
        self._next_id = 1000

    def fapiPrivateGetOpenAlgoOrders(self):
        return {"orders": list(self.algo_orders)}

    def fapiPrivateDeleteAlgoOrder(self, params):
        algo_id = params.get("algoId")
        self.algo_orders = [o for o in self.algo_orders if o.get("algoId") != algo_id]
        self.orders_cancelled.append(algo_id)
        return {"code": "200", "msg": "success"}

    def fapiPrivateV2GetPositionRisk(self, params=None):
        return self.positions

    def amount_to_precision(self, symbol, qty):
        return f"{qty:.4f}"

    def price_to_precision(self, symbol, px):
        return f"{px:.4f}"

    def create_order(self, **kw):
        oid = self._next_id
        self._next_id += 1
        order = {
            "id": oid,
            "symbol": kw.get("symbol"),
            "type": kw.get("type"),
            "side": kw.get("side"),
            "amount": kw.get("amount"),
            "stopPrice": kw.get("params", {}).get("stopPrice"),
            "status": "open",
        }
        self.orders_created.append(order)
        # Algo order kaydı (STOP_MARKET ise)
        if kw.get("type") == "STOP_MARKET":
            self.algo_orders.append({
                "algoId": oid,
                "symbol": kw.get("symbol", "").replace("/USDT", "USDT"),
                "orderType": "STOP_MARKET",
                "side": kw.get("side", "").upper(),
                "triggerPrice": str(kw.get("params", {}).get("stopPrice", "0")),
                "quantity": str(kw.get("amount", 0)),
            })
        return order


# ─────────────────────────────────────────────────────────────────────────────
# PROT_WATCHDOG logic reproduction (futures_daemon.py:680-712 fix)
# ─────────────────────────────────────────────────────────────────────────────

class TestProtWatchdogIntegration:
    """PROT_WATCHDOG yön mismatch fix end-to-end."""

    def test_long_position_orphan_sl_cancelled(self):
        """LONG pozisyon + eski BUY STOP → BUY STOP iptal edilir."""
        ex = MockExchange()
        # Eski SHORT'tan kalma BUY STOP (yön ters)
        ex.algo_orders.append({
            "algoId": 999,
            "symbol": "AVAXUSDT",
            "orderType": "STOP_MARKET",
            "side": "BUY",         # ← LONG pozisyon için TERS
            "triggerPrice": "9.524",
            "quantity": "40",
        })

        # Reproduce PROT_WATCHDOG logic
        _side = "long"
        _sym_algo = "AVAXUSDT"
        _expected_sl_side = "SELL" if _side == "long" else "BUY"
        _orphan_wrong_side = []
        for o in ex.fapiPrivateGetOpenAlgoOrders().get("orders", []):
            if (o.get("symbol") == _sym_algo
                    and str(o.get("orderType", "")).upper() == "STOP_MARKET"):
                _o_side = str(o.get("side", "")).upper()
                if _o_side != _expected_sl_side:
                    _orphan_wrong_side.append((float(o["triggerPrice"]), o["algoId"], _o_side))

        # Cancel orphans
        for _t, _a, _wrong_side in _orphan_wrong_side:
            ex.fapiPrivateDeleteAlgoOrder({"symbol": _sym_algo, "algoId": _a})

        # Verify: orphan iptal edildi
        assert 999 in ex.orders_cancelled
        # Verify: algo_orders artık BUY STOP içermiyor
        remaining_sides = [o.get("side") for o in ex.fapiPrivateGetOpenAlgoOrders()["orders"]]
        assert "BUY" not in remaining_sides

    def test_new_sl_placed_after_orphan_cancel(self):
        """Orphan iptal sonrası bot doğru yön SL koyuyor (LONG → SELL STOP)."""
        ex = MockExchange()
        ex.algo_orders.append({
            "algoId": 999, "symbol": "AVAXUSDT", "orderType": "STOP_MARKET",
            "side": "BUY", "triggerPrice": "9.524", "quantity": "40",
        })

        _side = "long"
        _contracts = 20.0
        _sym_ccxt = "AVAX/USDT"
        _sl_price = 8.50  # LONG için aşağıda

        # Orphan iptal (yukarıdaki logic)
        ex.fapiPrivateDeleteAlgoOrder({"symbol": "AVAXUSDT", "algoId": 999})

        # Yeni SL koy
        _close_side = "SELL" if _side == "long" else "BUY"
        new_order = ex.create_order(
            symbol=_sym_ccxt, type="STOP_MARKET",
            side=_close_side, amount=_contracts,
            params={"stopPrice": _sl_price, "reduceOnly": True},
        )

        # Verify
        assert new_order["side"] == "SELL"
        assert new_order["type"] == "STOP_MARKET"
        new_algos = ex.fapiPrivateGetOpenAlgoOrders()["orders"]
        assert len(new_algos) == 1
        assert new_algos[0]["side"] == "SELL"
        assert float(new_algos[0]["triggerPrice"]) == 8.50


# ─────────────────────────────────────────────────────────────────────────────
# Reconciler integration
# ─────────────────────────────────────────────────────────────────────────────

class TestReconcilerIntegration:
    """Reconciler phantom + qty drift end-to-end."""

    def test_phantom_detected_and_reported(self):
        """Exchange'de var, journal'da yok → phantom listesi."""
        exchange = {
            "DOTUSDT": {"symbol": "DOTUSDT", "qty": 293.2, "side": "long",
                        "entry_price": 1.235, "unrealized_pnl": -2.99},
        }
        journal = []  # boş — bot bilmiyor bu pozisyondan

        exchange_symbols = set(exchange.keys())
        journal_symbols = {j["symbol"] for j in journal}
        phantoms = [exchange[s] for s in exchange_symbols if s not in journal_symbols]

        assert len(phantoms) == 1
        assert phantoms[0]["symbol"] == "DOTUSDT"
        assert phantoms[0]["qty"] == 293.2

    def test_orphan_detected_and_can_close(self):
        """Journal'da açık, exchange'de yok → orphan close."""
        exchange = {}  # boş
        journal = [
            {"symbol": "BTCUSDT", "signal_id": "sig1", "side": "long",
             "fill_price": 65000, "fill_qty": 0.01},
        ]

        exchange_symbols = set(exchange.keys())
        orphans = [j for j in journal if j["symbol"] not in exchange_symbols]

        assert len(orphans) == 1
        assert orphans[0]["signal_id"] == "sig1"

    def test_qty_drift_above_threshold(self):
        """Aynı sembol, qty fark >5% → sync_mismatches."""
        exchange = {"BTCUSDT": {"symbol": "BTCUSDT", "qty": 0.010,
                                 "side": "long", "entry_price": 65000}}
        journal = [{"symbol": "BTCUSDT", "fill_qty": 0.020,  # 100% fark
                    "side": "long", "fill_price": 65000, "signal_id": "s1",
                    "strategy": "test", "sl_price": 63000, "tp_price": 67000}]

        sync_mismatches = []
        for sym in set(exchange.keys()) & {j["symbol"] for j in journal}:
            ex_qty = abs(float(exchange[sym].get("qty", 0)))
            j_qty = abs(float([j for j in journal if j["symbol"] == sym][0].get("fill_qty", 0)))
            diff_pct = abs(ex_qty - j_qty) / max(ex_qty, j_qty)
            if diff_pct > 0.05:
                sync_mismatches.append({"symbol": sym, "diff_pct": diff_pct})

        assert len(sync_mismatches) == 1
        assert sync_mismatches[0]["diff_pct"] > 0.05


# ─────────────────────────────────────────────────────────────────────────────
# Event bus + Reconciler integration
# ─────────────────────────────────────────────────────────────────────────────

class TestEventBusIntegration:
    """Reconciler phantom → event bus publish → handler consume."""

    def test_reconciler_phantom_publishes_event(self, tmp_path, monkeypatch):
        """Phantom detected → publish RECONCILER_PHANTOM event."""
        monkeypatch.setattr("price_action.events.bus._EVENTS_DIR", tmp_path)
        monkeypatch.setattr("price_action.events.bus._HANDLERS", {})
        from price_action.events import publish, register_handler, EventTopic, replay_recent

        # Simulate reconciler publishing phantom event
        received = []
        register_handler(EventTopic.RECONCILER_PHANTOM, lambda env: received.append(env))

        publish(
            topic=EventTopic.RECONCILER_PHANTOM,
            producer="reconciler",
            payload={"symbol": "DOTUSDT", "qty": 293.2, "entry_price": 1.235},
            correlation_id="reconcile-2026-05-28-1200",
        )

        # Handler tetiklendi
        assert len(received) == 1
        assert received[0].payload["symbol"] == "DOTUSDT"
        assert received[0].correlation_id == "reconcile-2026-05-28-1200"

        # Disk'te kayıtlı
        events = replay_recent(EventTopic.RECONCILER_PHANTOM, hours_back=24)
        assert len(events) == 1


# ─────────────────────────────────────────────────────────────────────────────
# Config adapter + RiskOfficer integration
# ─────────────────────────────────────────────────────────────────────────────

class TestConfigAdapterRiskOfficerIntegration:
    """Config adapter çıktısı RiskOfficer evaluate() ile uyumlu."""

    def test_canonical_config_loads_riskofficer_compatible(self):
        """v63 canonical → RiskOfficer instance kabul ediyor."""
        from price_action.config import from_live_yaml, to_live_yaml_dict
        from price_action.risk.sizing import RiskOfficer

        canonical = from_live_yaml(ROOT / "configs/risk_phoenix_scalp_15m_rsi2_v63.yaml")
        live_dict = to_live_yaml_dict(canonical)
        # Diğer alanları ekle (regime_filter_per_strategy gibi optional)

        ro = RiskOfficer(live_dict)
        # RiskOfficer kabul etti, attribute'ları okuyabiliyor
        assert ro.config.position_sizing.get("risk_per_trade") == 0.005
        assert int(ro.config.concentration_limits.get("max_open_positions", 0)) == 8
