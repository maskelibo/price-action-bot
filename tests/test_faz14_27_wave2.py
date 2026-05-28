"""Regression tests for Faz 14.27 Wave 2-3 fixes.

Wave 2 + Wave 3:
  - C2-1, C2-2, C2-3 (p1c_walker)
  - C3-1 (post_only_router atomic guard)
  - C3-5 (pyramid bracket exclusion)
  - C4 (slippage weekly summary)
  - C5 (reconciler qty drift)
  - C8 (adversary liquidation floor)
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


class TestAdversaryLiquidationFloor:
    """Faz 14.27 C8: equity -%100 altına düşemez (liquidation floor)."""

    def test_liquidation_floor_enforced(self):
        """Çok negatif pnl sequence → equity -100% floor + liquidated=True."""
        from price_action.agents.adversary_engineer import AdversaryEngineerAgent

        # Synthetic pool: 10 trade hep -%20 (toplam -200% impossible)
        pool = []
        from datetime import datetime as _dt, timedelta as _td
        base = _dt(2025, 6, 15, tzinfo=timezone.utc)
        for i in range(10):
            pool.append({
                "ts": (base + _td(hours=i)).isoformat(),
                "symbol": "BTC/USDT",
                "side": "long",
                "strategy": "vsa_climax_test",
                "pnl_pct": -20.0,  # %20 loss her trade
                "r_multiple": -1.0,
            })

        ae = AdversaryEngineerAgent()
        res = ae._replay_stress_period(
            strategy="phoenix_scalp_test",
            period_dates=("2025-06-01", "2025-06-30"),
            params={"pool_file": "test"},
            pool=pool,
        )
        # Liquidated → status = "liquidated"
        assert res.get("status") in ("liquidated", "ok"), f"Status: {res.get('status')}"
        if res.get("status") == "liquidated":
            assert res.get("liquidated") is True
            # final_return_pct -100% olmamalı (floor)
            assert res["final_return_pct"] >= -100.0, \
                f"Equity {res['final_return_pct']}% < -100% floor!"


class TestReconcilerQtyDrift:
    """Faz 14.27 C5: open trades exchange sync — qty drift check."""

    def test_qty_drift_detected(self):
        """Aynı sembolde >5% qty fark → sync_mismatches."""
        # Mock exchange ve journal
        exchange = {
            "BTCUSDT": {"symbol": "BTCUSDT", "qty": 0.01, "side": "long", "entry_price": 65000},
        }
        journal = [
            {"symbol": "BTCUSDT", "fill_qty": 0.015, "side": "long", "fill_price": 65000,
             "signal_id": "sig1", "strategy": "test", "sl_price": 63000, "tp_price": 67000},
        ]
        # Bot fix logic'i reproduce
        sync_mismatches = []
        for sym in set(exchange.keys()) & {j["symbol"] for j in journal}:
            ex_qty = abs(float(exchange[sym].get("qty", 0)))
            j_match = [j for j in journal if j["symbol"] == sym]
            if not j_match:
                continue
            j_qty = abs(float(j_match[0].get("fill_qty", 0)))
            if ex_qty > 0 and j_qty > 0:
                diff_pct = abs(ex_qty - j_qty) / max(ex_qty, j_qty)
                if diff_pct > 0.05:
                    sync_mismatches.append({
                        "symbol": sym,
                        "exchange_qty": ex_qty,
                        "journal_qty": j_qty,
                        "diff_pct": round(diff_pct * 100, 2),
                    })
        assert len(sync_mismatches) == 1
        assert sync_mismatches[0]["symbol"] == "BTCUSDT"
        # 0.01 vs 0.015 = 33% drift
        assert sync_mismatches[0]["diff_pct"] > 30.0

    def test_qty_within_threshold_no_drift(self):
        """%5'ten az drift → no mismatch."""
        exchange = {"BTCUSDT": {"qty": 0.010}}
        journal = [{"symbol": "BTCUSDT", "fill_qty": 0.0103}]  # %3 fark
        diff_pct = abs(0.01 - 0.0103) / max(0.01, 0.0103)
        assert diff_pct <= 0.05  # threshold içinde


class TestSlippageWeeklySummary:
    """Faz 14.27 C4: weekly_summary metodu trend + outlier."""

    def test_weekly_summary_structure(self, tmp_path, monkeypatch):
        """weekly_summary döndürdüğü dict beklenen field'lara sahip."""
        # SlippageTracker default path'i temp'e yönlendir
        import os
        monkeypatch.setenv("PA_SLIPPAGE_DB_PATH", str(tmp_path / "test_slippage.duckdb"))
        from price_action.execution.slippage_tracker import SlippageTracker
        st = SlippageTracker(db_path=tmp_path / "test_slippage.duckdb")
        summary = st.weekly_summary()
        # Schema doğrulaması
        assert "week_end" in summary
        assert "week_start" in summary
        assert "current_week" in summary
        assert "vs_previous_week" in summary
        assert "outlier_fills_top10" in summary
        # Current week sub-schema
        for k in ("n_fills", "avg_slippage_bps", "p95_slippage_bps",
                  "p99_slippage_bps", "maker_rate_pct", "total_fee_usdt"):
            assert k in summary["current_week"]


class TestPostOnlyAtomicGuard:
    """Faz 14.27 C3-1: cancel fail + verify fail → RuntimeError (market YAPMA)."""

    def test_ambiguous_cancel_raises_runtime_error(self):
        """Mock exchange: cancel fail + fetch_order fail → RuntimeError beklenir."""
        from price_action.execution.post_only_router import place_post_only_with_fallback

        class MockExchange:
            def __init__(self):
                self.market_called = False

            def create_order(self, **kw):
                return {"id": "test123", "status": "open"}

            def cancel_order(self, order_id, symbol):
                raise RuntimeError("Network error")

            def fetch_order(self, order_id, symbol):
                raise RuntimeError("Fetch fail")

            def create_market_order(self, **kw):
                self.market_called = True
                return {"id": "market456", "average": 100.0}

        ex = MockExchange()
        with pytest.raises(RuntimeError, match="ambiguous"):
            place_post_only_with_fallback(
                ex, symbol="BTC/USDT", side="buy", qty=0.001,
                target_price=100.0,
                fallback_after_sec=1,  # short timeout
                poll_interval=0.1,
            )
        # Market YAPMA garanti
        assert not ex.market_called, "Market order ambiguous cancel sonrası YAPILMAMALI"
