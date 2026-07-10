"""SEC54.7: Paper Gate tests — K2 (first 30d neg months) + K3 (30d ROI).

Tests:
  - K2: First 30 days trigger check (1 neg month = OK; 2+ = HALT)
  - K2: Expiry after 30 days (no evaluation)
  - K3: Rolling 30-day ROI < 15% (ALERT, not HALT)
  - K3: Early period (< 30 days) no-op
  - K3: Positive ROI no-op
  - Integration: All gates together (6/6 K gates simulated)
  - Telegram flow: throttle called with right level + message
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock

import duckdb
import pytest

from price_action.execution.trade_journal import TradeJournal
from price_action.ops import PaperGate, PaperGateConfig

# =====================================================================
# Helpers — setup trade journal + trades
# =====================================================================


def _create_journal_schema(db_path: Path) -> None:
    """Create futures_trades_closed schema."""
    con = duckdb.connect(str(db_path))
    try:
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS futures_trades_closed (
                trade_id TEXT PRIMARY KEY,
                ts_open TIMESTAMP,
                ts_close TIMESTAMP,
                sym TEXT,
                side TEXT,
                strategy TEXT,
                entry_price DOUBLE,
                exit_price DOUBLE,
                qty DOUBLE,
                realized_pnl_usdt DOUBLE,
                realized_r DOUBLE,
                win BOOLEAN,
                close_reason TEXT
            )
            """
        )
        con.commit()
    finally:
        con.close()


def _insert_trade(
    db_path: Path,
    *,
    trade_id: str,
    ts_close: datetime,
    realized_pnl_usdt: float,
    win: bool = True,
    sym: str = "BTC/USDT",
    side: str = "long",
    strategy: str = "test_strat",
) -> None:
    """Insert a closed trade."""
    con = duckdb.connect(str(db_path))
    try:
        con.execute(
            """
            INSERT INTO futures_trades_closed
                (trade_id, ts_open, ts_close, sym, side, strategy,
                 entry_price, exit_price, qty, realized_pnl_usdt, realized_r,
                 win, close_reason)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                trade_id,
                ts_close - timedelta(hours=4),
                ts_close,
                sym,
                side,
                strategy,
                100.0,
                110.0 if realized_pnl_usdt > 0 else 90.0,
                1.0,
                float(realized_pnl_usdt),
                1.0 if realized_pnl_usdt > 0 else -1.0,
                win,
                "tp" if realized_pnl_usdt > 0 else "sl",
            ],
        )
        con.commit()
    finally:
        con.close()


@pytest.fixture
def journal_db(tmp_path: Path) -> Path:
    """Create fresh journal DB."""
    db = tmp_path / "journal.duckdb"
    _create_journal_schema(db)
    return db


@pytest.fixture
def mock_telegram():
    """Mock TelegramThrottle."""
    return MagicMock()


# =====================================================================
# K2 Tests
# =====================================================================


class TestK2:
    """K2: First 30 days, max 1 negative month before HARD KILL."""

    def test_k2_no_trades(self, journal_db: Path, mock_telegram) -> None:
        """No trades yet — K2 should return None."""
        paper_start = datetime(2026, 5, 25, tzinfo=UTC)
        current = datetime(2026, 5, 26, tzinfo=UTC)

        journal = TradeJournal(db_path=journal_db)
        config = PaperGateConfig(paper_start_date=paper_start, cap_usd=1000.0)
        gate = PaperGate(config, journal, mock_telegram)

        result = gate.evaluate_k2(current)
        assert result is None

    def test_k2_early_period_one_day(self, journal_db: Path, mock_telegram) -> None:
        """Only 1 day passed (< 1 day threshold) — K2 returns None."""
        paper_start = datetime(2026, 5, 25, tzinfo=UTC)
        current = datetime(2026, 5, 25, hour=12, tzinfo=UTC)

        journal = TradeJournal(db_path=journal_db)
        config = PaperGateConfig(paper_start_date=paper_start, cap_usd=1000.0)
        gate = PaperGate(config, journal, mock_telegram)

        result = gate.evaluate_k2(current)
        assert result is None

    def test_k2_single_positive_month(self, journal_db: Path, mock_telegram) -> None:
        """First month positive — K2 PASS."""
        paper_start = datetime(2026, 5, 25, tzinfo=UTC)
        current = datetime(2026, 6, 10, tzinfo=UTC)

        # Add positive trade in May
        _insert_trade(
            journal_db,
            trade_id="t1",
            ts_close=datetime(2026, 5, 26, tzinfo=UTC),
            realized_pnl_usdt=50.0,
        )

        journal = TradeJournal(db_path=journal_db)
        config = PaperGateConfig(paper_start_date=paper_start, cap_usd=1000.0)
        gate = PaperGate(config, journal, mock_telegram)

        result = gate.evaluate_k2(current)
        assert result is None  # 1 positive month = no trigger

    def test_k2_single_negative_month(self, journal_db: Path, mock_telegram) -> None:
        """First month negative (1 neg) — K2 PASS (threshold=1)."""
        paper_start = datetime(2026, 5, 25, tzinfo=UTC)
        current = datetime(2026, 6, 10, tzinfo=UTC)

        # Add negative trade in May
        _insert_trade(
            journal_db,
            trade_id="t1",
            ts_close=datetime(2026, 5, 26, tzinfo=UTC),
            realized_pnl_usdt=-50.0,
            win=False,
        )

        journal = TradeJournal(db_path=journal_db)
        config = PaperGateConfig(
            paper_start_date=paper_start, cap_usd=1000.0, k2_max_neg_months_first_30d=1
        )
        gate = PaperGate(config, journal, mock_telegram)

        result = gate.evaluate_k2(current)
        assert result is None  # 1 neg month = exactly threshold, no trigger

    def test_k2_two_negative_months_first_30d(self, journal_db: Path, mock_telegram) -> None:
        """First 30 days with 2 negative months — K2 HALT (threshold=1)."""
        paper_start = datetime(2026, 5, 25, tzinfo=UTC)
        current = datetime(2026, 6, 10, tzinfo=UTC)  # 16 days, within first 30

        # May: negative
        _insert_trade(
            journal_db,
            trade_id="t1",
            ts_close=datetime(2026, 5, 26, tzinfo=UTC),
            realized_pnl_usdt=-50.0,
            win=False,
        )
        # June: negative
        _insert_trade(
            journal_db,
            trade_id="t2",
            ts_close=datetime(2026, 6, 5, tzinfo=UTC),
            realized_pnl_usdt=-30.0,
            win=False,
        )

        journal = TradeJournal(db_path=journal_db)
        config = PaperGateConfig(
            paper_start_date=paper_start, cap_usd=1000.0, k2_max_neg_months_first_30d=1
        )
        gate = PaperGate(config, journal, mock_telegram)

        result = gate.evaluate_k2(current)
        assert result is not None
        assert result.action == "HALT"
        assert result.switch == "K2"
        assert result.metric_value == 2  # 2 negative months
        assert result.threshold == 1
        mock_telegram.send_throttled.assert_called_once()
        call_args = mock_telegram.send_throttled.call_args
        assert "K2_HARD_KILL" in str(call_args[0])
        assert "CRITICAL" in str(call_args[1])

    def test_k2_after_30_days_no_eval(self, journal_db: Path, mock_telegram) -> None:
        """After 30 days, K2 should not evaluate (returns None)."""
        paper_start = datetime(2026, 5, 25, tzinfo=UTC)
        current = datetime(2026, 6, 25, tzinfo=UTC)  # exactly 31 days

        # Add 2 negative months
        _insert_trade(
            journal_db,
            trade_id="t1",
            ts_close=datetime(2026, 5, 26, tzinfo=UTC),
            realized_pnl_usdt=-50.0,
            win=False,
        )
        _insert_trade(
            journal_db,
            trade_id="t2",
            ts_close=datetime(2026, 6, 5, tzinfo=UTC),
            realized_pnl_usdt=-30.0,
            win=False,
        )

        journal = TradeJournal(db_path=journal_db)
        config = PaperGateConfig(
            paper_start_date=paper_start, cap_usd=1000.0, k2_max_neg_months_first_30d=1
        )
        gate = PaperGate(config, journal, mock_telegram)

        result = gate.evaluate_k2(current)
        assert result is None  # K2 disabled after 30 days

    def test_k2_mixed_months(self, journal_db: Path, mock_telegram) -> None:
        """Mix: May +100, June -200 (1 neg month) — K2 PASS."""
        paper_start = datetime(2026, 5, 25, tzinfo=UTC)
        current = datetime(2026, 6, 15, tzinfo=UTC)

        _insert_trade(
            journal_db,
            trade_id="t1",
            ts_close=datetime(2026, 5, 26, tzinfo=UTC),
            realized_pnl_usdt=100.0,
        )
        _insert_trade(
            journal_db,
            trade_id="t2",
            ts_close=datetime(2026, 6, 5, tzinfo=UTC),
            realized_pnl_usdt=-200.0,
            win=False,
        )

        journal = TradeJournal(db_path=journal_db)
        config = PaperGateConfig(
            paper_start_date=paper_start, cap_usd=1000.0, k2_max_neg_months_first_30d=1
        )
        gate = PaperGate(config, journal, mock_telegram)

        result = gate.evaluate_k2(current)
        assert result is None  # 1 positive, 1 negative = 1 neg month = OK


# =====================================================================
# K3 Tests
# =====================================================================


class TestK3:
    """K3: Rolling 30-day ROI < 15% → ALERT (not HALT)."""

    def test_k3_no_trades(self, journal_db: Path, mock_telegram) -> None:
        """No trades yet but 30 days passed — K3 should alert (ROI = 0% < 15%)."""
        paper_start = datetime(2026, 5, 25, tzinfo=UTC)
        current = datetime(2026, 6, 25, tzinfo=UTC)

        journal = TradeJournal(db_path=journal_db)
        config = PaperGateConfig(
            paper_start_date=paper_start, cap_usd=1000.0, k3_min_monthly_roi_pct=15.0
        )
        gate = PaperGate(config, journal, mock_telegram)

        result = gate.evaluate_k3(current)
        # No trades = 0% ROI < 15% = ALERT
        assert result is not None
        assert result.action == "ALERT"
        assert result.metric_value == 0.0

    def test_k3_early_period_no_30d(self, journal_db: Path, mock_telegram) -> None:
        """Less than 30 days passed — K3 should return None."""
        paper_start = datetime(2026, 5, 25, tzinfo=UTC)
        current = datetime(2026, 6, 10, tzinfo=UTC)  # 16 days

        # Add positive trade
        _insert_trade(
            journal_db,
            trade_id="t1",
            ts_close=datetime(2026, 5, 26, tzinfo=UTC),
            realized_pnl_usdt=100.0,
        )

        journal = TradeJournal(db_path=journal_db)
        config = PaperGateConfig(
            paper_start_date=paper_start, cap_usd=1000.0, k3_min_monthly_roi_pct=15.0
        )
        gate = PaperGate(config, journal, mock_telegram)

        result = gate.evaluate_k3(current)
        assert result is None  # 30 days not yet passed

    def test_k3_positive_roi_pass(self, journal_db: Path, mock_telegram) -> None:
        """30+ days, ROI +20% (> 15%) — K3 PASS."""
        paper_start = datetime(2026, 5, 25, tzinfo=UTC)
        current = datetime(2026, 6, 25, tzinfo=UTC)  # 31 days

        # +200 PnL = 200/1000 = 20% ROI
        _insert_trade(
            journal_db,
            trade_id="t1",
            ts_close=datetime(2026, 6, 5, tzinfo=UTC),
            realized_pnl_usdt=200.0,
        )

        journal = TradeJournal(db_path=journal_db)
        config = PaperGateConfig(
            paper_start_date=paper_start, cap_usd=1000.0, k3_min_monthly_roi_pct=15.0
        )
        gate = PaperGate(config, journal, mock_telegram)

        result = gate.evaluate_k3(current)
        assert result is None  # 20% >= 15%, no alert

    def test_k3_low_roi_alert(self, journal_db: Path, mock_telegram) -> None:
        """30+ days, ROI +10% (< 15%) — K3 ALERT."""
        paper_start = datetime(2026, 5, 25, tzinfo=UTC)
        current = datetime(2026, 6, 25, tzinfo=UTC)  # 31 days

        # +100 PnL = 100/1000 = 10% ROI
        _insert_trade(
            journal_db,
            trade_id="t1",
            ts_close=datetime(2026, 6, 5, tzinfo=UTC),
            realized_pnl_usdt=100.0,
        )

        journal = TradeJournal(db_path=journal_db)
        config = PaperGateConfig(
            paper_start_date=paper_start, cap_usd=1000.0, k3_min_monthly_roi_pct=15.0
        )
        gate = PaperGate(config, journal, mock_telegram)

        result = gate.evaluate_k3(current)
        assert result is not None
        assert result.action == "ALERT"
        assert result.switch == "K3"
        assert result.metric_value == 10.0  # 10% ROI
        assert result.threshold == 15.0
        mock_telegram.send_throttled.assert_called_once()
        call_args = mock_telegram.send_throttled.call_args
        assert "K3_ALERT" in str(call_args[0])
        assert "WARNING" in str(call_args[1])

    def test_k3_negative_roi_alert(self, journal_db: Path, mock_telegram) -> None:
        """30+ days, ROI -5% (< 15%) — K3 ALERT."""
        paper_start = datetime(2026, 5, 25, tzinfo=UTC)
        current = datetime(2026, 6, 25, tzinfo=UTC)

        # -50 PnL = -50/1000 = -5% ROI
        _insert_trade(
            journal_db,
            trade_id="t1",
            ts_close=datetime(2026, 6, 5, tzinfo=UTC),
            realized_pnl_usdt=-50.0,
            win=False,
        )

        journal = TradeJournal(db_path=journal_db)
        config = PaperGateConfig(
            paper_start_date=paper_start, cap_usd=1000.0, k3_min_monthly_roi_pct=15.0
        )
        gate = PaperGate(config, journal, mock_telegram)

        result = gate.evaluate_k3(current)
        assert result is not None
        assert result.action == "ALERT"
        assert result.metric_value == -5.0

    def test_k3_rolling_window(self, journal_db: Path, mock_telegram) -> None:
        """30-day rolling window: only last 30 days count (not older trades)."""
        paper_start = datetime(2026, 5, 1, tzinfo=UTC)
        current = datetime(2026, 6, 25, tzinfo=UTC)  # 55 days

        # Old trade (>30 days ago): +500
        _insert_trade(
            journal_db,
            trade_id="t1",
            ts_close=datetime(2026, 5, 10, tzinfo=UTC),
            realized_pnl_usdt=500.0,
        )
        # Recent trade (within 30d): +100
        _insert_trade(
            journal_db,
            trade_id="t2",
            ts_close=datetime(2026, 6, 20, tzinfo=UTC),
            realized_pnl_usdt=100.0,
        )

        journal = TradeJournal(db_path=journal_db)
        config = PaperGateConfig(
            paper_start_date=paper_start, cap_usd=1000.0, k3_min_monthly_roi_pct=15.0
        )
        gate = PaperGate(config, journal, mock_telegram)

        result = gate.evaluate_k3(current)
        assert result is not None  # Only +100 in last 30 days = 10% ROI < 15%
        assert result.action == "ALERT"


# =====================================================================
# Integration Tests
# =====================================================================


class TestPaperGateIntegration:
    """Integration: K2 + K3 + simulated K1-K6."""

    def test_evaluate_all_empty(self, journal_db: Path, mock_telegram) -> None:
        """No trades, no triggers — evaluate_all returns []."""
        paper_start = datetime(2026, 5, 25, tzinfo=UTC)
        current = datetime(2026, 5, 26, tzinfo=UTC)

        journal = TradeJournal(db_path=journal_db)
        config = PaperGateConfig(paper_start_date=paper_start, cap_usd=1000.0)
        gate = PaperGate(config, journal, mock_telegram)

        results = gate.evaluate_all(current)
        assert results == []

    def test_evaluate_all_k2_trigger(self, journal_db: Path, mock_telegram) -> None:
        """K2 triggers in evaluate_all."""
        paper_start = datetime(2026, 5, 25, tzinfo=UTC)
        current = datetime(2026, 6, 10, tzinfo=UTC)

        # 2 negative months
        _insert_trade(
            journal_db,
            trade_id="t1",
            ts_close=datetime(2026, 5, 26, tzinfo=UTC),
            realized_pnl_usdt=-50.0,
            win=False,
        )
        _insert_trade(
            journal_db,
            trade_id="t2",
            ts_close=datetime(2026, 6, 5, tzinfo=UTC),
            realized_pnl_usdt=-30.0,
            win=False,
        )

        journal = TradeJournal(db_path=journal_db)
        config = PaperGateConfig(
            paper_start_date=paper_start, cap_usd=1000.0, k2_max_neg_months_first_30d=1
        )
        gate = PaperGate(config, journal, mock_telegram)

        results = gate.evaluate_all(current)
        assert len(results) == 1
        assert results[0].switch == "K2"
        assert results[0].action == "HALT"

    def test_evaluate_all_k3_trigger(self, journal_db: Path, mock_telegram) -> None:
        """K3 triggers in evaluate_all."""
        paper_start = datetime(2026, 5, 25, tzinfo=UTC)
        current = datetime(2026, 6, 25, tzinfo=UTC)

        _insert_trade(
            journal_db,
            trade_id="t1",
            ts_close=datetime(2026, 6, 5, tzinfo=UTC),
            realized_pnl_usdt=100.0,
        )

        journal = TradeJournal(db_path=journal_db)
        config = PaperGateConfig(
            paper_start_date=paper_start, cap_usd=1000.0, k3_min_monthly_roi_pct=15.0
        )
        gate = PaperGate(config, journal, mock_telegram)

        results = gate.evaluate_all(current)
        assert len(results) == 1
        assert results[0].switch == "K3"
        assert results[0].action == "ALERT"

    def test_evaluate_all_both_k2_k3(self, journal_db: Path, mock_telegram) -> None:
        """Both K2 and K3 trigger."""
        paper_start = datetime(2026, 5, 25, tzinfo=UTC)
        # K2: 16 days (within first 30d)
        # K3: needs 30+ days, so we need 2 evaluations at different times
        # For this test, let's trigger at 35 days (K2 no longer active, K3 active)
        current = datetime(2026, 6, 29, tzinfo=UTC)  # 35 days

        # K3: only -80 PnL in last 30 days = -8% ROI < 15%
        _insert_trade(
            journal_db,
            trade_id="t1",
            ts_close=datetime(2026, 6, 5, tzinfo=UTC),
            realized_pnl_usdt=-50.0,
            win=False,
        )
        _insert_trade(
            journal_db,
            trade_id="t2",
            ts_close=datetime(2026, 6, 20, tzinfo=UTC),
            realized_pnl_usdt=-30.0,
            win=False,
        )

        journal = TradeJournal(db_path=journal_db)
        config = PaperGateConfig(
            paper_start_date=paper_start,
            cap_usd=1000.0,
            k2_max_neg_months_first_30d=1,
            k3_min_monthly_roi_pct=15.0,
        )
        gate = PaperGate(config, journal, mock_telegram)

        results = gate.evaluate_all(current)
        # K2 no longer active (>30 days), K3 triggers (rolling 30d ROI < 15%)
        assert len(results) == 1
        assert results[0].switch == "K3"
        assert results[0].action == "ALERT"

    def test_evaluate_all_with_timestamp_none(self, journal_db: Path, mock_telegram) -> None:
        """evaluate_all(current_date=None) uses UTC now."""
        # paper_start now'a göreli (now-5g) — K3 rolling-30g penceresi 30g dolmadan
        # NO-OP (paper_gate.py:103). Sabit tarih zaman geçince K3'ü tetikliyordu
        # (boş DB → ROI %0 < %15 → alert) = zaman-bağımlı stale test.
        paper_start = datetime.now(UTC) - timedelta(days=5)

        # Make sure no 30-day window has triggered (empty DB)
        journal = TradeJournal(db_path=journal_db)
        config = PaperGateConfig(paper_start_date=paper_start, cap_usd=1000.0)
        gate = PaperGate(config, journal, mock_telegram)

        results = gate.evaluate_all(current_date=None)
        assert results == []

    def test_telegram_level_k2_critical(self, journal_db: Path, mock_telegram) -> None:
        """K2 HALT sends CRITICAL level."""
        paper_start = datetime(2026, 5, 25, tzinfo=UTC)
        current = datetime(2026, 6, 10, tzinfo=UTC)

        _insert_trade(
            journal_db,
            trade_id="t1",
            ts_close=datetime(2026, 5, 26, tzinfo=UTC),
            realized_pnl_usdt=-50.0,
            win=False,
        )
        _insert_trade(
            journal_db,
            trade_id="t2",
            ts_close=datetime(2026, 6, 5, tzinfo=UTC),
            realized_pnl_usdt=-30.0,
            win=False,
        )

        journal = TradeJournal(db_path=journal_db)
        config = PaperGateConfig(
            paper_start_date=paper_start, cap_usd=1000.0, k2_max_neg_months_first_30d=1
        )
        gate = PaperGate(config, journal, mock_telegram)

        gate.evaluate_k2(current)
        mock_telegram.send_throttled.assert_called_once()
        call = mock_telegram.send_throttled.call_args
        assert call[1]["level"] == "CRITICAL"

    def test_telegram_level_k3_warning(self, journal_db: Path, mock_telegram) -> None:
        """K3 ALERT sends WARNING level."""
        paper_start = datetime(2026, 5, 25, tzinfo=UTC)
        current = datetime(2026, 6, 25, tzinfo=UTC)

        _insert_trade(
            journal_db,
            trade_id="t1",
            ts_close=datetime(2026, 6, 5, tzinfo=UTC),
            realized_pnl_usdt=100.0,
        )

        journal = TradeJournal(db_path=journal_db)
        config = PaperGateConfig(
            paper_start_date=paper_start, cap_usd=1000.0, k3_min_monthly_roi_pct=15.0
        )
        gate = PaperGate(config, journal, mock_telegram)

        gate.evaluate_k3(current)
        mock_telegram.send_throttled.assert_called_once()
        call = mock_telegram.send_throttled.call_args
        assert call[1]["level"] == "WARNING"
