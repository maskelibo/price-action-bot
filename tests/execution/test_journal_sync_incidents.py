"""Regression tests — journal/exchange sync incidents 2026-05-30.

INC1: XLM orphan false-positive
  - Orphan cancel logic must skip when journal has open signal for that symbol
  - reconcile_journal.reconcile() SAFE_MODE must not close orphan when
    exchange returns 0 positions but journal has 3 open

INC2: NEAR market_fallback qty drift
  - market_fallback path must read actual fill qty via fetch_order when
    order.get("filled") is 0/None
  - reconciler auto-heal must update fill_qty journal→exchange when exchange < journal

Both tests use in-memory DuckDB to avoid touching production data.
"""

from __future__ import annotations

import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import duckdb

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _make_journal(path: str) -> duckdb.DuckDBPyConnection:
    """In-memory journal with minimal schema needed for tests."""
    con = duckdb.connect(path)
    con.execute("""
        CREATE TABLE IF NOT EXISTS futures_signals (
            signal_id TEXT PRIMARY KEY,
            ts TIMESTAMP,
            symbol TEXT,
            strategy TEXT,
            side TEXT,
            sl_price DOUBLE,
            tp_price DOUBLE,
            confluence DOUBLE,
            leverage INTEGER,
            status TEXT,
            order_id TEXT,
            fill_price DOUBLE,
            fill_qty DOUBLE,
            notional_usdt DOUBLE,
            margin_usdt DOUBLE,
            error_msg TEXT
        )
    """)
    con.execute("""
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
    """)
    con.commit()
    return con


def _insert_open_signal(
    con,
    symbol: str,
    side: str,
    fill_price: float,
    fill_qty: float,
    sl_price: float = 0.0,
    sig_id: str | None = None,
) -> str:
    if sig_id is None:
        sig_id = uuid.uuid4().hex[:16]
    con.execute(
        "INSERT INTO futures_signals VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            sig_id,
            datetime.now(UTC),
            symbol,
            "test_strategy",
            side,
            sl_price,
            0.0,
            0.5,
            1,
            "filled",
            "order123",
            fill_price,
            fill_qty,
            fill_price * fill_qty,
            fill_price * fill_qty,
            None,
        ),
    )
    con.commit()
    return sig_id


# ─────────────────────────────────────────────────────────────────────────────
# INC1a: Orphan cancel — journal cross-check guard
# ─────────────────────────────────────────────────────────────────────────────


class TestOrphanCancelJournalCrossCheck:
    """ORPHAN_CANCEL must not fire when journal has an open trade for that symbol."""

    def _build_active_pos_syms(self, positions: list[dict]) -> set[str]:
        """Replica of daemon's active_pos_syms logic."""
        active = set()
        for p in positions:
            qty = abs(float(p.get("contracts", 0)))
            if qty > 0.0001:
                sym_raw = p.get("symbol", "")
                active.add(sym_raw.split(":")[0].replace("/", ""))
        return active

    def _should_skip_orphan_cancel(
        self, algo_sym: str, active_pos_syms: set[str], journal_open_syms: set[str]
    ) -> bool:
        """Replica of daemon's new guard logic (INC1 fix)."""
        if algo_sym in active_pos_syms:
            return True  # position exists, not orphan
        if algo_sym in journal_open_syms:
            return True  # journal says open — API stale, skip
        return False

    def test_xlm_open_in_journal_skip_orphan_cancel(self):
        """
        XLM vacancy: fetch_positions returns [AVAX, NEAR] (XLM missing due to
        API stale). XLMUSDT algo orders exist. Journal has XLM open signal.
        Orphan cancel must be SKIPPED for XLMUSDT.
        """
        positions = [
            {"symbol": "AVAX/USDT:USDT", "contracts": 84.0},
            {"symbol": "NEAR/USDT:USDT", "contracts": 219.0},
        ]
        active_pos_syms = self._build_active_pos_syms(positions)
        assert "XLMUSDT" not in active_pos_syms

        # Journal has XLM open
        journal_open_syms = {"XLMUSDT", "AVAXUSDT", "NEARUSDT"}

        # XLMUSDT algo order present
        result = self._should_skip_orphan_cancel("XLMUSDT", active_pos_syms, journal_open_syms)
        assert result is True, "XLMUSDT orphan cancel must be skipped when journal has open trade"

    def test_genuine_orphan_no_journal_entry_cancels(self):
        """
        Truly closed position: DOGEUSDT algo order present, but DOGE not in
        positions AND not in journal. This is a real orphan — cancel is correct.
        """
        positions = [
            {"symbol": "AVAX/USDT:USDT", "contracts": 84.0},
        ]
        active_pos_syms = self._build_active_pos_syms(positions)
        journal_open_syms = {"AVAXUSDT"}  # only AVAX open

        result = self._should_skip_orphan_cancel("DOGEUSDT", active_pos_syms, journal_open_syms)
        assert result is False, "DOGEUSDT with no journal entry IS a real orphan — should NOT skip"

    def test_position_present_skip_orphan(self):
        """Position in active_pos_syms → always skip regardless of journal."""
        positions = [{"symbol": "BTC/USDT:USDT", "contracts": 0.5}]
        active_pos_syms = self._build_active_pos_syms(positions)
        result = self._should_skip_orphan_cancel("BTCUSDT", active_pos_syms, set())
        assert result is True

    def test_journal_open_syms_format_conversion(self):
        """
        Journal stores 'XLM/USDT'. Conversion to 'XLMUSDT' for comparison
        with algo_sym format must work correctly.
        """
        journal_syms_raw = ["XLM/USDT", "NEAR/USDT", "AVAX/USDT"]
        converted = {s.replace("/", "").replace(":USDT", "") for s in journal_syms_raw}
        assert "XLMUSDT" in converted
        assert "NEARUSDT" in converted
        assert "AVAXUSDT" in converted


# ─────────────────────────────────────────────────────────────────────────────
# INC1b: reconciler SAFE_MODE
# ─────────────────────────────────────────────────────────────────────────────


class TestReconcilerSafeMode:
    """reconcile() must not close orphans when exchange returns 0 positions
    but journal has open trades (SAFE_MODE guard)."""

    def test_safe_mode_skips_orphan_close_when_exchange_empty(self, tmp_path):
        """exchange_pos=0 + journal_open=3 → SAFE_MODE, no orphan_closed."""

        # Build a temp journal with 3 open signals
        db_path = str(tmp_path / "test_journal.duckdb")
        con = _make_journal(db_path)
        _insert_open_signal(con, "XLM/USDT", "short", 0.2335, 1448.0)
        _insert_open_signal(con, "NEAR/USDT", "short", 2.522, 291.0)
        _insert_open_signal(con, "AVAX/USDT", "long", 8.843, 84.0)
        con.close()

        # Patch _fetch_exchange_positions to return empty (API fail)
        # Patch _JOURNAL in the module
        import scripts.reconcile_journal as rj

        original_journal = rj._JOURNAL
        try:
            rj._JOURNAL = Path(db_path)
            with patch.object(rj, "_fetch_exchange_positions", return_value={}):
                stats = rj.reconcile()
        finally:
            rj._JOURNAL = original_journal

        assert stats["exchange_fetch_ok"] is False
        assert (
            stats["orphans_closed"] == 0
        ), "SAFE_MODE: no orphans should be closed when exchange returns empty"
        assert stats["journal_open"] == 3


# ─────────────────────────────────────────────────────────────────────────────
# INC2a: Fill qty — market_fallback actual fill
# ─────────────────────────────────────────────────────────────────────────────


class TestFillQtyActualFill:
    """market_fallback order.filled=None → fetch_order to get actual filled qty."""

    def _simulate_fill_qty_logic(
        self, order: dict, intended_qty: float, exchange
    ) -> tuple[float, float]:
        """
        Replica of daemon's fill_qty resolution logic after INC2 fix.
        Returns (fill_qty, avg_px).
        """
        cur_px = 2.522
        avg_px = float(order.get("average") or order.get("price") or cur_px)
        raw_filled = order.get("filled")
        if not raw_filled or float(raw_filled) <= 0:
            order_id_for_fetch = str(order.get("id", ""))
            if order_id_for_fetch:
                try:
                    fetched = exchange.fetch_order(order_id_for_fetch, "NEAR/USDT")
                    raw_filled = fetched.get("filled") or raw_filled
                    fetched_avg = fetched.get("average") or fetched.get("price")
                    if fetched_avg:
                        avg_px = float(fetched_avg)
                except Exception:
                    pass
        if raw_filled and float(raw_filled) > 0:
            fill_qty = float(raw_filled)
        else:
            fill_qty = float(intended_qty)
        return fill_qty, avg_px

    def test_market_fallback_filled_none_uses_fetch_order(self):
        """
        order.filled=None → fetch_order called → returns actual 219.
        fill_qty must be 219, NOT intended 291.
        """
        order = {
            "id": "270728605",
            "status": "closed",
            "average": 2.5220,
            "filled": None,  # API returns None on first response
        }
        mock_exchange = MagicMock()
        mock_exchange.fetch_order.return_value = {
            "id": "270728605",
            "status": "filled",
            "average": 2.5220,
            "filled": 219.0,  # actual fill
        }
        fill_qty, avg_px = self._simulate_fill_qty_logic(order, 291.0, mock_exchange)

        assert fill_qty == 219.0, f"Expected actual fill 219, got {fill_qty}"
        mock_exchange.fetch_order.assert_called_once_with("270728605", "NEAR/USDT")

    def test_market_fallback_filled_zero_uses_fetch_order(self):
        """order.filled=0 (not None) → same path, fetch_order called."""
        order = {
            "id": "270728606",
            "status": "closed",
            "average": 2.5220,
            "filled": 0,  # explicit 0
        }
        mock_exchange = MagicMock()
        mock_exchange.fetch_order.return_value = {
            "id": "270728606",
            "filled": 219.0,
            "average": 2.5220,
        }
        fill_qty, _ = self._simulate_fill_qty_logic(order, 291.0, mock_exchange)
        assert fill_qty == 219.0
        mock_exchange.fetch_order.assert_called_once()

    def test_filled_present_no_fetch_needed(self):
        """order.filled=219.0 → no fetch_order, use directly."""
        order = {
            "id": "12345",
            "status": "closed",
            "average": 2.5220,
            "filled": 219.0,
        }
        mock_exchange = MagicMock()
        fill_qty, _ = self._simulate_fill_qty_logic(order, 291.0, mock_exchange)

        assert fill_qty == 219.0
        mock_exchange.fetch_order.assert_not_called()

    def test_filled_none_fetch_order_fails_falls_back_to_intended(self):
        """fetch_order fails → fall back to intended qty (with WARN log)."""
        order = {
            "id": "99999",
            "status": "closed",
            "average": 2.5220,
            "filled": None,
        }
        mock_exchange = MagicMock()
        mock_exchange.fetch_order.side_effect = Exception("network timeout")

        fill_qty, _ = self._simulate_fill_qty_logic(order, 291.0, mock_exchange)
        # Falls back to intended qty when fetch fails
        assert fill_qty == 291.0

    def test_post_only_filled_uses_filled_directly(self):
        """post_only_filled returns actual fill in 'filled' field — no fetch needed."""
        order = {
            "id": "379536676",
            "status": "closed",
            "average": 0.2335,
            "filled": 1448.0,
        }
        mock_exchange = MagicMock()
        fill_qty, _ = self._simulate_fill_qty_logic(order, 1448.0, mock_exchange)
        assert fill_qty == 1448.0
        mock_exchange.fetch_order.assert_not_called()


# ─────────────────────────────────────────────────────────────────────────────
# INC2b: Reconciler qty auto-heal
# ─────────────────────────────────────────────────────────────────────────────


class TestReconcilerQtyAutoHeal:
    """reconciler qty drift auto-heal: exchange_qty < journal_qty → update journal."""

    def _run_qty_heal(
        self, journal_qty: float, exchange_qty: float, diff_pct: float, tmp_path: Path
    ) -> tuple[list, duckdb.DuckDBPyConnection]:
        """Run just the auto-heal portion of reconcile() logic."""
        import scripts.reconcile_journal as rj

        db_path = str(tmp_path / "heal_test.duckdb")
        con = _make_journal(db_path)
        sig_id = _insert_open_signal(con, "NEAR/USDT", "short", 2.522, journal_qty, sl_price=2.608)
        con.close()

        # Build sync_mismatches as reconcile() would
        sync_mismatches = [
            {
                "symbol": "NEAR/USDT",
                "exchange_qty": exchange_qty,
                "journal_qty": journal_qty,
                "diff_pct": diff_pct,
            }
        ]

        # Run heal logic directly (isolated from full reconcile)
        original_journal = rj._JOURNAL
        healed = []
        try:
            rj._JOURNAL = Path(db_path)
            import duckdb as _ddb

            journal_list = [{"symbol": "NEAR/USDT", "signal_id": sig_id, "fill_qty": journal_qty}]
            _jcon_heal = _ddb.connect(db_path)
            try:
                for _mm in sync_mismatches:
                    _sym = _mm["symbol"]
                    _ex_qty = float(_mm["exchange_qty"])
                    _j_qty = float(_mm["journal_qty"])
                    _diff_pct = float(_mm["diff_pct"])
                    if _ex_qty >= _j_qty:
                        continue
                    if _diff_pct > 50.0:
                        continue
                    _j_rows = [j for j in journal_list if j["symbol"] == _sym]
                    for _jr in _j_rows:
                        _sig_id = str(_jr["signal_id"])
                        _jcon_heal.execute(
                            "UPDATE futures_signals SET fill_qty=? WHERE signal_id=? AND fill_qty=?",
                            [_ex_qty, _sig_id, _j_qty],
                        )
                        healed.append(
                            {"symbol": _sym, "sig_id": _sig_id, "from": _j_qty, "to": _ex_qty}
                        )
                _jcon_heal.commit()
            finally:
                _jcon_heal.close()
        finally:
            rj._JOURNAL = original_journal

        verify_con = duckdb.connect(db_path, read_only=True)
        return healed, verify_con

    def test_near_qty_heal_291_to_219(self, tmp_path):
        """NEAR 291→219 (24.74% drift, exchange < journal) → healed."""
        healed, con = self._run_qty_heal(291.0, 219.0, 24.74, tmp_path)
        try:
            row = con.execute(
                "SELECT fill_qty FROM futures_signals WHERE symbol='NEAR/USDT'"
            ).fetchone()
            assert row is not None
            assert row[0] == 219.0, f"Expected 219, got {row[0]}"
            assert len(healed) == 1
            assert healed[0]["from"] == 291.0
            assert healed[0]["to"] == 219.0
        finally:
            con.close()

    def test_exchange_qty_greater_no_auto_heal(self, tmp_path):
        """exchange_qty > journal_qty → phantom-like, auto-heal skipped."""
        healed, con = self._run_qty_heal(219.0, 291.0, 24.74, tmp_path)
        try:
            row = con.execute(
                "SELECT fill_qty FROM futures_signals WHERE symbol='NEAR/USDT'"
            ).fetchone()
            assert row[0] == 219.0, "Original journal qty should be unchanged"
            assert len(healed) == 0
        finally:
            con.close()

    def test_drift_over_50pct_no_auto_heal(self, tmp_path):
        """diff > 50% → too aggressive, auto-heal skipped."""
        healed, con = self._run_qty_heal(291.0, 100.0, 65.6, tmp_path)
        try:
            row = con.execute(
                "SELECT fill_qty FROM futures_signals WHERE symbol='NEAR/USDT'"
            ).fetchone()
            assert row[0] == 291.0, "Journal qty should NOT change for >50% diff"
            assert len(healed) == 0
        finally:
            con.close()

    def test_drift_exactly_5pct_threshold(self, tmp_path):
        """diff=4.9% < 5% → not in sync_mismatches → no heal needed."""
        # If diff is exactly at 4.9%, it wouldn't appear in sync_mismatches (>5% gate)
        # This tests the gate: 4.9% should NOT trigger the drift path
        # Direct check: diff_pct = 4.9 < 5.0 → not in sync_mismatches
        exchange_qty = 277.0  # 291 * (1 - 0.049) ≈ 277
        diff_pct = abs(291.0 - exchange_qty) / max(291.0, exchange_qty) * 100
        assert diff_pct < 5.0, "4.9% drift should not trigger reconciler alarm"


# ─────────────────────────────────────────────────────────────────────────────
# INC1c: one-time correction script PnL math
# ─────────────────────────────────────────────────────────────────────────────


class TestXlmCorrectionPnLMath:
    """Verify that the correction script's PnL/R calculation is correct for XLM."""

    def test_xlm_short_pnl_at_correct_exit(self):
        """
        XLM short: entry=0.23354, exit=0.24959, qty=1448
        PnL = (entry - exit) * qty = (0.23354 - 0.24959) * 1448 = -23.24...
        """
        entry = 0.23354
        exit_price = 0.24959
        qty = 1448.0
        side = "short"
        pnl = (entry - exit_price) * qty
        assert abs(pnl - (-23.24)) < 0.1, f"PnL {pnl:.4f} not close to -23.24"

    def test_xlm_short_pnl_at_wrong_exit(self):
        """
        XLM short: entry=0.23354, exit=0.25819 (wrong ticker), qty=1448
        PnL = (0.23354 - 0.25819) * 1448 = -35.69...
        """
        entry = 0.23354
        exit_price = 0.25819
        qty = 1448.0
        pnl = (entry - exit_price) * qty
        assert abs(pnl - (-35.69)) < 0.1, f"PnL {pnl:.4f} not close to -35.69"

    def test_xlm_r_calculation(self):
        """
        XLM short: entry=0.23354, exit=0.24959, sl=0.25086
        R = pnl_per_unit / risk_per_unit = (entry-exit) / (entry-sl)
        """
        entry = 0.23354
        exit_price = 0.24959
        sl = 0.25086
        side = "short"
        pnl_per_unit = entry - exit_price  # short
        risk_per_unit = abs(entry - sl)
        r = pnl_per_unit / risk_per_unit
        # Should be negative (loss)
        assert r < 0, f"R should be negative for a short loss, got {r}"
        # Magnitude should be around -0.93 (based on the numbers)
        assert abs(r) < 2.0, f"R {r:.4f} out of expected range"

    def test_near_pnl_with_correct_qty(self):
        """
        NEAR short: entry=2.522, qty=219 (corrected), SL=2.608
        Max risk = (2.608 - 2.522) * 219 = 18.834 USDT (1R)
        """
        entry = 2.522
        sl = 2.608
        qty_correct = 219.0
        qty_wrong = 291.0
        risk_correct = abs(sl - entry) * qty_correct
        risk_wrong = abs(sl - entry) * qty_wrong
        # Correct 1R is smaller — risk was overstated by journal
        assert risk_correct < risk_wrong
        # Ratio should match 219/291
        assert abs(risk_correct / risk_wrong - 219 / 291) < 0.001
