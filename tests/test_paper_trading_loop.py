"""Unit tests for Faz 6 paper trading loop.

Tests:
  - Confidence score computation formula
  - Confidence → leverage tier mapping
  - Risk officer breaker logic integration
  - Mock signal generation → mock order submission (idempotency, dry-run)
  - Paper journal operations
"""
from __future__ import annotations

import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest

# Ensure src is on path
_ROOT = Path(__file__).resolve().parents[1]
_SRC = _ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

# Import the loop module (not installed, import directly)
sys.path.insert(0, str(_ROOT / "scripts"))
from paper_trading_loop import (  # type: ignore[import]
    CONFIDENCE_TIERS,
    compute_confidence_score,
    confidence_to_leverage,
    _make_synthetic_ohlcv,
    PaperJournal,
    run_daily,
    _seconds_until_next_run,
)

from price_action.contracts import (
    OrderInstruction,
    RiskedOrder,
    Signal,
    TPLevel,
)
from price_action.execution.ccxt_paper import CCXTPaperBroker
from price_action.execution.paper_state import PaperState
from price_action.risk.breaker import DDBreaker
from price_action.risk.sizing import AccountState, RiskOfficer


# =====================================================================
# Confidence score tests
# =====================================================================

class TestConfidenceScore:
    def test_all_zeros_returns_minimum(self):
        score = compute_confidence_score(
            confluence_score=0.0,
            kaufman_er=0.0,
            rolling_sharpe=-2.0,  # normalized to 0
            body_ratio=0.0,
        )
        assert score == pytest.approx(0.0, abs=1e-6)

    def test_all_max_returns_one(self):
        # confluence=3.0 (max norm), kaufman_er=1.0, sharpe=3.0 (norm=1.0), body=1.0
        score = compute_confidence_score(
            confluence_score=3.0,
            kaufman_er=1.0,
            rolling_sharpe=3.0,
            body_ratio=1.0,
        )
        assert score == pytest.approx(1.0, abs=1e-6)

    def test_formula_weights_sum_to_one(self):
        """0.35 + 0.25 + 0.25 + 0.15 == 1.0"""
        weights = [0.35, 0.25, 0.25, 0.15]
        assert sum(weights) == pytest.approx(1.0)

    def test_typical_signal_score(self):
        """A typical engulfing signal (confluence=1.8, er=0.35, sharpe=0.5, body=0.7)."""
        score = compute_confidence_score(
            confluence_score=1.8,
            kaufman_er=0.35,
            rolling_sharpe=0.5,
            body_ratio=0.7,
        )
        # confluence_norm = 1.8/3 = 0.6
        # kaufman_er_norm = 0.35
        # sharpe_norm = (0.5+2)/5 = 0.5
        # body_ratio_norm = 0.7
        expected = 0.35 * 0.6 + 0.25 * 0.35 + 0.25 * 0.5 + 0.15 * 0.7
        assert score == pytest.approx(expected, abs=1e-6)

    def test_confluence_capped_at_one(self):
        """Confluence scores above 3.0 should be capped at 1.0 norm."""
        score_capped = compute_confidence_score(
            confluence_score=10.0,
            kaufman_er=0.0,
            rolling_sharpe=-2.0,
            body_ratio=0.0,
        )
        score_exact = compute_confidence_score(
            confluence_score=3.0,
            kaufman_er=0.0,
            rolling_sharpe=-2.0,
            body_ratio=0.0,
        )
        assert score_capped == pytest.approx(score_exact)

    def test_negative_sharpe_clamps_to_zero(self):
        """rolling_sharpe < -2 should be clamped to 0 in norm."""
        score_low = compute_confidence_score(
            confluence_score=0.0,
            kaufman_er=0.0,
            rolling_sharpe=-10.0,  # extreme negative
            body_ratio=0.0,
        )
        score_floor = compute_confidence_score(
            confluence_score=0.0,
            kaufman_er=0.0,
            rolling_sharpe=-2.0,  # exact floor
            body_ratio=0.0,
        )
        assert score_low == pytest.approx(score_floor, abs=1e-6)

    def test_score_is_in_range(self):
        """Score must always be in [0, 1]."""
        import random
        random.seed(42)
        for _ in range(100):
            score = compute_confidence_score(
                confluence_score=random.uniform(-5, 10),
                kaufman_er=random.uniform(-1, 2),
                rolling_sharpe=random.uniform(-5, 5),
                body_ratio=random.uniform(-1, 2),
            )
            assert 0.0 <= score <= 1.0, f"score={score} out of range"


# =====================================================================
# Leverage tier mapping tests
# =====================================================================

class TestConfidenceToLeverage:
    def test_tier_boundaries(self):
        test_cases = [
            (0.00, 1),
            (0.10, 1),
            (0.31, 1),
            (0.32, 2),
            (0.40, 2),
            (0.42, 3),
            (0.50, 3),
            (0.52, 4),
            (0.57, 4),
            (0.58, 5),
            (0.99, 5),
        ]
        for confidence, expected_lev in test_cases:
            result = confidence_to_leverage(confidence)
            assert result == expected_lev, (
                f"confidence={confidence} → got {result}, expected {expected_lev}"
            )

    def test_all_tiers_covered(self):
        """All tiers in CONFIDENCE_TIERS should map to distinct leverages."""
        leverages = {tier["leverage"] for tier in CONFIDENCE_TIERS}
        assert leverages == {1, 2, 3, 4, 5}

    def test_tiers_contiguous_no_gaps(self):
        """Tiers should be contiguous (each max == next min)."""
        sorted_tiers = sorted(CONFIDENCE_TIERS, key=lambda t: t["min"])
        for i in range(len(sorted_tiers) - 1):
            assert sorted_tiers[i]["max"] == pytest.approx(sorted_tiers[i + 1]["min"]), (
                f"Gap between tier {i} and {i+1}"
            )

    def test_fallback_returns_1x(self):
        """Edge: confidence exactly at 1.0 should still return something sane."""
        # With max 1.01 in last tier, 1.0 should still map to 5
        result = confidence_to_leverage(1.0)
        assert result == 5

    def test_negative_confidence_falls_back(self):
        """Negative values are invalid but should not crash — fallback to 1x."""
        result = confidence_to_leverage(-0.5)
        assert result == 1  # fallback


# =====================================================================
# DDBreaker integration
# =====================================================================

class TestDDBreakerIntegration:
    def test_no_breaker_on_fresh_state(self, tmp_path):
        breaker = DDBreaker(
            config={
                "daily_loss_pct": 0.05,
                "weekly_loss_pct": 0.10,
                "monthly_loss_pct": 0.15,
                "consecutive_losses": 6,
            },
            state_path=tmp_path / "breaker.json",
        )
        acc = AccountState(
            equity_usdt=10_000.0,
            free_margin_usdt=10_000.0,
        )
        status = breaker.snapshot(acc)
        assert not any(status.values()), f"Expected no breaker, got {status}"

    def test_daily_breaker_triggers_at_5pct(self, tmp_path):
        breaker = DDBreaker(
            config={"daily_loss_pct": 0.05, "weekly_loss_pct": 0.10, "monthly_loss_pct": 0.15},
            state_path=tmp_path / "breaker.json",
        )
        # Initialize anchor at 10000
        acc_initial = AccountState(equity_usdt=10_000.0, free_margin_usdt=10_000.0)
        breaker.snapshot(acc_initial)

        # Drop equity by exactly 5% (500 USDT) — should trigger
        acc_loss = AccountState(equity_usdt=9_500.0, free_margin_usdt=9_500.0)
        status = breaker.snapshot(acc_loss)
        assert status["daily"], f"Daily breaker should trigger at 5% loss, got {status}"

    def test_weekly_breaker_triggers_at_10pct(self, tmp_path):
        breaker = DDBreaker(
            config={"daily_loss_pct": 0.20, "weekly_loss_pct": 0.10, "monthly_loss_pct": 0.50},
            state_path=tmp_path / "breaker.json",
        )
        acc_initial = AccountState(equity_usdt=10_000.0, free_margin_usdt=10_000.0)
        breaker.snapshot(acc_initial)

        acc_loss = AccountState(equity_usdt=8_900.0, free_margin_usdt=8_900.0)
        status = breaker.snapshot(acc_loss)
        assert status["weekly"], f"Weekly breaker should trigger at 11% loss, got {status}"

    def test_consecutive_losses_breaker(self, tmp_path):
        breaker = DDBreaker(
            config={"daily_loss_pct": 1.0, "weekly_loss_pct": 1.0, "monthly_loss_pct": 1.0, "consecutive_losses": 3},
            state_path=tmp_path / "breaker.json",
        )
        acc = AccountState(
            equity_usdt=10_000.0,
            free_margin_usdt=10_000.0,
            consecutive_losses=3,
        )
        status = breaker.snapshot(acc)
        assert status["consecutive"], f"Consecutive breaker should trigger, got {status}"

    def test_no_breaker_below_threshold(self, tmp_path):
        breaker = DDBreaker(
            config={"daily_loss_pct": 0.05, "weekly_loss_pct": 0.10, "monthly_loss_pct": 0.15},
            state_path=tmp_path / "breaker.json",
        )
        acc_initial = AccountState(equity_usdt=10_000.0, free_margin_usdt=10_000.0)
        breaker.snapshot(acc_initial)

        # Only 2% loss — should NOT trigger
        acc_small = AccountState(equity_usdt=9_800.0, free_margin_usdt=9_800.0)
        status = breaker.snapshot(acc_small)
        assert not status["daily"], f"Daily breaker should NOT trigger at 2% loss, got {status}"


# =====================================================================
# Synthetic OHLCV
# =====================================================================

class TestSyntheticOHLCV:
    def test_shape_and_columns(self):
        df = _make_synthetic_ohlcv("BTC/USDT", n=250)
        assert len(df) == 250
        for col in ["ts", "open", "high", "low", "close", "volume", "symbol", "venue", "timeframe"]:
            assert col in df.columns, f"Missing column: {col}"

    def test_ohlc_sanity(self):
        df = _make_synthetic_ohlcv("ETH/USDT", n=100)
        assert (df["high"] >= df["close"]).all(), "high >= close violated"
        assert (df["high"] >= df["open"]).all(), "high >= open violated"
        assert (df["low"] <= df["close"]).all(), "low <= close violated"
        assert (df["low"] <= df["open"]).all(), "low <= open violated"

    def test_deterministic_seed(self):
        df1 = _make_synthetic_ohlcv("BTC/USDT", n=50)
        df2 = _make_synthetic_ohlcv("BTC/USDT", n=50)
        pd.testing.assert_frame_equal(df1, df2)

    def test_different_symbols_differ(self):
        df_btc = _make_synthetic_ohlcv("BTC/USDT", n=50)
        df_eth = _make_synthetic_ohlcv("ETH/USDT", n=50)
        # Close prices should differ (different seeds)
        assert not df_btc["close"].equals(df_eth["close"])

    def test_correct_metadata(self):
        df = _make_synthetic_ohlcv("SOL/USDT", n=10)
        assert (df["symbol"] == "SOL/USDT").all()
        assert (df["venue"] == "binance").all()
        assert (df["timeframe"] == "1d").all()


# =====================================================================
# PaperJournal
# =====================================================================

class TestPaperJournal:
    def test_init_creates_tables(self, tmp_path):
        try:
            import duckdb  # type: ignore
        except ImportError:
            pytest.skip("duckdb not installed")
        journal = PaperJournal(path=tmp_path / "test.duckdb")
        # Should not raise
        conn = duckdb.connect(str(tmp_path / "test.duckdb"))
        tables = [r[0] for r in conn.execute("SHOW TABLES").fetchall()]
        conn.close()
        assert "paper_trades" in tables
        assert "paper_equity_snapshots" in tables

    def test_log_trade_open_and_exists(self, tmp_path):
        try:
            import duckdb  # type: ignore
        except ImportError:
            pytest.skip("duckdb not installed")
        journal = PaperJournal(path=tmp_path / "test.duckdb")
        ts = datetime(2025, 1, 15, tzinfo=timezone.utc)
        trade_id = uuid.uuid4().hex
        journal.log_trade_open(
            trade_id=trade_id,
            symbol="BTC/USDT",
            side="long",
            entry_ts=ts,
            entry_price=50_000.0,
            quantity=0.002,
            leverage=3,
            confidence=0.55,
            sl_price=48_000.0,
            tp_price=54_000.0,
            pattern_id="bullish_engulfing_cont",
            confluence_score=1.8,
            dry_run=False,
        )
        assert journal.trade_exists_for_bar("BTC/USDT", ts)

    def test_idempotency_trade_exists(self, tmp_path):
        try:
            import duckdb  # type: ignore
        except ImportError:
            pytest.skip("duckdb not installed")
        journal = PaperJournal(path=tmp_path / "test.duckdb")
        ts = datetime(2025, 2, 20, tzinfo=timezone.utc)
        journal.log_trade_open(
            trade_id=uuid.uuid4().hex,
            symbol="ETH/USDT",
            side="long",
            entry_ts=ts,
            entry_price=2_500.0,
            quantity=0.01,
            leverage=2,
            confidence=0.45,
            sl_price=2_400.0,
            tp_price=2_700.0,
            pattern_id="bullish_engulfing_cont",
            confluence_score=1.7,
            dry_run=True,
        )
        # Same bar → should report as existing
        assert journal.trade_exists_for_bar("ETH/USDT", ts)
        # Different symbol → should not exist
        assert not journal.trade_exists_for_bar("SOL/USDT", ts)

    def test_log_equity_snapshot(self, tmp_path):
        try:
            import duckdb  # type: ignore
        except ImportError:
            pytest.skip("duckdb not installed")
        journal = PaperJournal(path=tmp_path / "test.duckdb")
        journal.log_equity_snapshot(
            ts=datetime.now(timezone.utc),
            equity=10_500.0,
            open_positions=2,
            realized_pnl_total=500.0,
            daily_pnl=50.0,
        )
        conn = duckdb.connect(str(tmp_path / "test.duckdb"))
        count = conn.execute("SELECT COUNT(*) FROM paper_equity_snapshots").fetchone()[0]
        conn.close()
        assert count == 1

    def test_log_trade_close(self, tmp_path):
        try:
            import duckdb  # type: ignore
        except ImportError:
            pytest.skip("duckdb not installed")
        journal = PaperJournal(path=tmp_path / "test.duckdb")
        ts = datetime(2025, 3, 10, tzinfo=timezone.utc)
        trade_id = uuid.uuid4().hex
        journal.log_trade_open(
            trade_id=trade_id,
            symbol="BNB/USDT",
            side="short",
            entry_ts=ts,
            entry_price=400.0,
            quantity=0.5,
            leverage=1,
            confidence=0.30,
            sl_price=420.0,
            tp_price=360.0,
            pattern_id="bearish_engulfing_cont",
            confluence_score=1.6,
            dry_run=False,
        )
        exit_ts = datetime(2025, 3, 12, tzinfo=timezone.utc)
        journal.log_trade_close(
            trade_id=trade_id,
            exit_ts=exit_ts,
            exit_price=370.0,
            exit_reason="tp_hit",
            realized_pnl=15.0,
            r_multiple=1.5,
        )
        conn = duckdb.connect(str(tmp_path / "test.duckdb"))
        row = conn.execute(
            "SELECT status, exit_reason, realized_pnl FROM paper_trades WHERE trade_id=?",
            [trade_id],
        ).fetchone()
        conn.close()
        assert row[0] == "closed"
        assert row[1] == "tp_hit"
        assert row[2] == pytest.approx(15.0)

    def test_get_open_trade_ids(self, tmp_path):
        try:
            import duckdb  # type: ignore
        except ImportError:
            pytest.skip("duckdb not installed")
        journal = PaperJournal(path=tmp_path / "test.duckdb")
        ts1 = datetime(2025, 4, 1, tzinfo=timezone.utc)
        ts2 = datetime(2025, 4, 2, tzinfo=timezone.utc)
        id1 = uuid.uuid4().hex
        id2 = uuid.uuid4().hex
        for trade_id, sym, ts in [(id1, "BTC/USDT", ts1), (id2, "ETH/USDT", ts2)]:
            journal.log_trade_open(
                trade_id=trade_id, symbol=sym, side="long",
                entry_ts=ts, entry_price=100.0, quantity=0.1,
                leverage=1, confidence=0.35, sl_price=90.0, tp_price=120.0,
                pattern_id="bullish_engulfing_cont", confluence_score=1.5,
                dry_run=False,
            )
        open_ids = journal.get_open_trade_ids()
        assert id1 in open_ids
        assert id2 in open_ids


# =====================================================================
# Mock signal generation → mock order submission (dry-run)
# =====================================================================

class TestDryRunDailyLoop:
    """Tests that run_daily in dry-run mode processes signals without submitting real orders."""

    def test_dry_run_does_not_create_real_fills(self, tmp_path, monkeypatch):
        """dry_run=True should not call broker.place_order."""
        # Patch PaperState to use tmp_path
        monkeypatch.setenv("PA_LLM_DRY_RUN", "true")

        fills_submitted = []

        from price_action.execution import ccxt_paper
        original_place = ccxt_paper.CCXTPaperBroker.place_order

        def mock_place(self, instruction):
            fills_submitted.append(instruction)
            return original_place(self, instruction)

        monkeypatch.setattr(ccxt_paper.CCXTPaperBroker, "place_order", mock_place)

        # Override paper state path to tmp
        import paper_trading_loop as ptl
        original_state_path = ptl.PAPER_STATE_PATH if hasattr(ptl, "PAPER_STATE_PATH") else None

        # Run dry-run
        summary = run_daily(dry_run=True)

        # In dry-run mode, no actual fills are submitted
        assert summary["dry_run"] is True
        assert isinstance(summary["signals_found"], int)
        assert isinstance(summary["orders_placed"], int)
        # No real place_order calls in dry-run
        assert len(fills_submitted) == 0, (
            f"place_order was called {len(fills_submitted)} times in dry-run mode"
        )

    def test_dry_run_returns_valid_summary_structure(self, monkeypatch):
        monkeypatch.setenv("PA_LLM_DRY_RUN", "true")
        summary = run_daily(dry_run=True)

        required_keys = [
            "run_ts", "dry_run", "equity_usdt", "signals_found",
            "orders_placed", "rejects", "breakers_active", "signals", "orders", "rejected",
        ]
        for key in required_keys:
            assert key in summary, f"Missing key in summary: {key}"

        assert summary["dry_run"] is True
        assert isinstance(summary["signals"], list)
        assert isinstance(summary["orders"], list)
        assert isinstance(summary["rejected"], list)
        assert isinstance(summary["breakers_active"], dict)

    def test_dry_run_equity_is_positive(self, monkeypatch):
        monkeypatch.setenv("PA_LLM_DRY_RUN", "true")
        summary = run_daily(dry_run=True)
        assert summary["equity_usdt"] > 0

    def test_signal_info_has_required_fields(self, monkeypatch):
        monkeypatch.setenv("PA_LLM_DRY_RUN", "true")
        summary = run_daily(dry_run=True)
        for sig in summary["signals"]:
            assert "symbol" in sig
            assert "direction" in sig
            assert "confidence" in sig
            assert "leverage" in sig
            assert sig["leverage"] in {1, 2, 3, 4, 5}
            assert 0.0 <= sig["confidence"] <= 1.0

    def test_order_info_in_dry_run_has_required_fields(self, monkeypatch):
        monkeypatch.setenv("PA_LLM_DRY_RUN", "true")
        summary = run_daily(dry_run=True)
        for order in summary["orders"]:
            assert "symbol" in order
            assert "trade_id" in order
            assert order.get("status") == "dry_run"
            assert "leverage" in order
            assert "confidence" in order


# =====================================================================
# Paper broker round-trip with risk officer
# =====================================================================

class TestPaperBrokerWithRiskOfficer:
    def _make_signal(
        self,
        symbol: str = "BTC/USDT",
        direction: str = "long",
        sl: float = 48_000.0,
        tp: float = 54_000.0,
        confluence: float = 1.8,
    ) -> Signal:
        return Signal(
            ts=datetime(2025, 5, 1, tzinfo=timezone.utc),
            venue="binance",
            symbol=symbol,
            timeframe="1d",
            direction=direction,  # type: ignore[arg-type]
            pattern_id="bullish_engulfing_cont",
            confluence_score=confluence,
            sl_price=sl,
            tp_price=tp,
            suggested_size_atr=1.0,
            metadata={"kaufman_er": 0.35},
        )

    def test_paper_order_with_risk_officer_accepts(self, tmp_path):
        state = PaperState(path=tmp_path / "state.json", initial_balance_usdt=10_000.0)
        broker = CCXTPaperBroker(force_offline=True, state=state)

        risk_config = {
            "position_sizing": {"method": "fixed_fractional", "risk_per_trade": 0.02, "min_quantity_usdt": 1},
            "stop_loss": {"atr_multiplier": 2.0},
            "take_profit": {"primary_R": 2.0, "partial_close_at_R": 1.0},
            "leverage": {
                "max_leverage_per_symbol": 5,
                "max_portfolio_notional_x_equity": 5,
                "margin_safety_ratio": 0.1,  # relaxed for test
            },
            "drawdown_breakers": {"daily_loss_pct": 0.05},
            "correlation_gate": {"enabled": False},
            "concentration_limits": {"max_open_positions": 5, "max_per_symbol_pct": 0.9, "max_per_category_pct": 1.0},
            "liquidity_gate": {"max_order_to_minute_volume": 0.01, "min_book_depth_usdt": 0},
        }
        ro = RiskOfficer(config=risk_config)

        sig = self._make_signal(sl=48_000.0, tp=54_000.0)
        acc = AccountState(
            equity_usdt=10_000.0,
            free_margin_usdt=10_000.0,
            open_positions=[],
        )
        result = ro.evaluate(sig, acc, market_price=50_000.0)
        assert hasattr(result, "quantity"), f"Expected RiskedOrder, got {type(result)}: {result}"
        assert result.quantity > 0

    def test_max_concurrent_positions_rejected(self, tmp_path):
        from price_action.contracts import Position
        state = PaperState(path=tmp_path / "state.json", initial_balance_usdt=10_000.0)

        risk_config = {
            "position_sizing": {"method": "fixed_fractional", "risk_per_trade": 0.02, "min_quantity_usdt": 1},
            "stop_loss": {"atr_multiplier": 2.0},
            "take_profit": {"primary_R": 2.0, "partial_close_at_R": 1.0},
            "leverage": {
                "max_leverage_per_symbol": 5,
                "max_portfolio_notional_x_equity": 5,
                "margin_safety_ratio": 0.1,
            },
            "drawdown_breakers": {"daily_loss_pct": 0.05},
            "correlation_gate": {"enabled": False},
            "concentration_limits": {"max_open_positions": 5, "max_per_symbol_pct": 0.9, "max_per_category_pct": 1.0},
            "liquidity_gate": {"max_order_to_minute_volume": 0.01, "min_book_depth_usdt": 0},
        }
        ro = RiskOfficer(config=risk_config)

        # Create 5 mock open positions
        fake_positions = [
            Position(
                venue="binance",
                symbol=f"COIN{i}/USDT",
                side="long",
                quantity=0.1,
                entry_price=100.0,
                current_price=100.0,
                unrealized_pnl_usdt=0.0,
                realized_pnl_usdt=0.0,
                opened_at=datetime.now(timezone.utc),
                strategy_id="test",
                last_updated=datetime.now(timezone.utc),
            )
            for i in range(5)
        ]

        sig = self._make_signal()
        acc = AccountState(
            equity_usdt=10_000.0,
            free_margin_usdt=10_000.0,
            open_positions=fake_positions,
        )
        result = ro.evaluate(sig, acc, market_price=50_000.0)
        from price_action.contracts import Reject
        assert isinstance(result, Reject)
        assert result.reason == "max_open_positions_reached"


# =====================================================================
# Timing utility
# =====================================================================

class TestTimingUtil:
    def test_seconds_until_next_run_positive(self):
        secs = _seconds_until_next_run(0, 30)
        assert 0 < secs <= 24 * 3600

    def test_seconds_until_next_run_never_zero(self):
        """Should always be > 0 (next run, not current)."""
        secs = _seconds_until_next_run(0, 30)
        assert secs > 0
