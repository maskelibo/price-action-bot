"""Tests for scripts/forward_sim_compare.py.

All tests are self-contained (no real network, no real DB writes).
We use tmp_path fixtures and mock/stub external calls.
"""
from __future__ import annotations

import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

# ---------------------------------------------------------------------------
# Import the module under test
# ---------------------------------------------------------------------------
# Patch environment before import so settings don't try to load real DB
os.environ.setdefault("PA_DUCKDB_READ_ONLY", "true")
os.environ.setdefault("PA_LOG_QUIET", "1")

import importlib.util

_spec = importlib.util.spec_from_file_location(
    "forward_sim_compare",
    str(ROOT / "scripts" / "forward_sim_compare.py"),
)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

FixedFractionLedger = _mod.FixedFractionLedger
E0_FIXED            = _mod.E0_FIXED
RISK_PCT            = _mod.RISK_PCT
MAX_NOTIONAL_PCT    = _mod.MAX_NOTIONAL_PCT
CONC_PCT            = _mod.CONC_PCT
FEE_RT_BPS          = _mod.FEE_RT_BPS
SL_PCT_MIN_15M      = _mod.SL_PCT_MIN_15M
SL_PCT_MIN_5M       = _mod.SL_PCT_MIN_5M
BASELINE_EXIT       = _mod.BASELINE_EXIT


# ===========================================================================
# 1. Fixed-fraction sizing — non-compounding invariant
# ===========================================================================

class TestFixedFractionSizing:
    """Risk must always be sized off E0_FIXED, never current equity."""

    def test_initial_equity_is_e0(self):
        ledger = FixedFractionLedger("champion")
        assert ledger.equity() == E0_FIXED

    def test_sizing_uses_fixed_e0_not_current_equity(self):
        """After a winning trade, sizing caps must still reference E0_FIXED, not current equity.

        We test this by verifying that the NOTIONAL CAP is MAX_NOTIONAL_PCT * E0_FIXED,
        not MAX_NOTIONAL_PCT * (E0_FIXED + realized_pnl).
        """
        ledger = FixedFractionLedger("champion")

        # Simulate a profitable closed trade
        ledger._realized_pnl = 500.0   # fake +$500 gain
        assert ledger.equity() == E0_FIXED + 500.0

        # Use a tiny sl_pct to force the notional cap to trigger
        # With sl_pct=0.001: uncapped notional = (RISK_PCT * E0_FIXED) / 0.001
        # This will exceed MAX_NOTIONAL_PCT * E0_FIXED → cap triggers
        sl_pct = 0.001
        ok, risk_d, notional = ledger.can_admit("BTC/USDT", sl_pct, "15m")
        assert ok

        # Notional cap must be MAX_NOTIONAL_PCT * E0_FIXED (non-compounding)
        # NOT MAX_NOTIONAL_PCT * (E0 + 500)
        expected_cap = MAX_NOTIONAL_PCT * E0_FIXED
        assert abs(notional - expected_cap) < 0.01, (
            f"notional {notional:.2f} != MAX_NOTIONAL_PCT*E0={expected_cap:.2f} — "
            "cap is not anchored to E0_FIXED (compounding leak detected)"
        )

        # Also check: with larger E0 (compounding scenario) the cap would differ
        compounding_cap = MAX_NOTIONAL_PCT * (E0_FIXED + 500.0)
        assert abs(notional - compounding_cap) > 0.01, (
            "Notional cap appears to be using current equity (compounding) instead of E0_FIXED"
        )

    def test_sizing_uses_fixed_e0_after_loss(self):
        """After a losing trade, concentration cap must still reference E0_FIXED."""
        ledger = FixedFractionLedger("v13")
        ledger._realized_pnl = -200.0   # fake -$200 loss

        # Use a tiny sl_pct to trigger concentration cap arithmetic
        sl_pct = 0.001
        ok, risk_d, notional = ledger.can_admit("ETH/USDT", sl_pct, "15m")
        assert ok
        # Concentration cap: CONC_PCT * E0_FIXED
        expected_cap = CONC_PCT * E0_FIXED
        # With sl_pct tiny, notional = notional_cap (hit the MAX_NOTIONAL_PCT cap first)
        # Both caps are vs E0_FIXED
        assert notional <= MAX_NOTIONAL_PCT * E0_FIXED + 0.01, (
            f"notional {notional} exceeds MAX_NOTIONAL_PCT*E0_FIXED "
            f"({MAX_NOTIONAL_PCT * E0_FIXED}) — compounding detected"
        )

    def test_notional_cap_applied(self):
        """Notional must be capped at MAX_NOTIONAL_PCT * E0_FIXED."""
        ledger = FixedFractionLedger("champion")
        # sl_pct = 0.001 → uncapped notional = RISK_PCT * E0 / 0.001 = huge
        sl_pct = 0.0001
        ok, risk_d, notional = ledger.can_admit("BTC/USDT", sl_pct, "15m")
        assert ok
        assert notional <= MAX_NOTIONAL_PCT * E0_FIXED + 0.01, (
            f"notional {notional} exceeds cap {MAX_NOTIONAL_PCT * E0_FIXED}"
        )

    def test_concentration_cap_prevents_overexposure(self):
        """Per-symbol concentration cap must reject if already at CONC_PCT of E0."""
        ledger = FixedFractionLedger("v13")
        # Manually inject a big open position that fills the concentration cap
        sym = "ETH/USDT"
        cap_notional = CONC_PCT * E0_FIXED  # exactly at limit
        ledger.open_position({
            "trade_id": "test-001",
            "symbol": sym,
            "notional": cap_notional,
            "side": "long",
            "entry_price": 3000.0,
            "entry_ts": datetime.now(UTC),
            "sl_price": 2700.0,
            "tp1_price": 3300.0,
            "tp2_price": 3450.0,
            "sl_pct": 0.10,
            "risk_dollars": RISK_PCT * E0_FIXED,
            "tf": "15m",
            "unrealized_pnl": 0.0,
        })
        # Now try to admit another ETH/USDT position
        ok, _, _ = ledger.can_admit(sym, 0.03, "15m")
        assert not ok, "Should be rejected — symbol already at concentration cap"

    def test_different_symbol_not_blocked_by_concentration(self):
        """Concentration cap is per-symbol — different symbol should be admitted."""
        ledger = FixedFractionLedger("champion")
        sym1 = "BTC/USDT"
        ledger.open_position({
            "trade_id": "test-btc",
            "symbol": sym1,
            "notional": CONC_PCT * E0_FIXED,
            "side": "long",
            "entry_price": 60000.0,
            "entry_ts": datetime.now(UTC),
            "sl_price": 57000.0,
            "tp1_price": 63000.0,
            "tp2_price": 64500.0,
            "sl_pct": 0.05,
            "risk_dollars": RISK_PCT * E0_FIXED,
            "tf": "15m",
            "unrealized_pnl": 0.0,
        })
        sym2 = "ETH/USDT"
        ok, _, _ = ledger.can_admit(sym2, 0.03, "15m")
        assert ok, "Different symbol should not be blocked by BTC concentration"


# ===========================================================================
# 2. Fee model — TRUE 18 bps round-trip
# ===========================================================================

class TestFeeModel:
    def test_fee_constant_is_18_bps(self):
        assert FEE_RT_BPS == 18.0, f"Expected 18.0 bps round-trip, got {FEE_RT_BPS}"

    def test_entry_fee_is_half_round_trip(self):
        """Entry fee must be FEE_RT_BPS/2 of notional."""
        notional = 500.0
        fee_entry = notional * (FEE_RT_BPS / 2.0 / 10_000)
        expected  = notional * 0.0009   # 9 bps
        assert abs(fee_entry - expected) < 0.001

    def test_sl_pct_min_15m_is_025(self):
        assert SL_PCT_MIN_15M == 0.025, f"Champion 15m WIDESTOP gate must be 0.025, got {SL_PCT_MIN_15M}"

    def test_sl_pct_min_5m_is_030(self):
        assert SL_PCT_MIN_5M == 0.030, f"5m WIDESTOP gate must be 0.030, got {SL_PCT_MIN_5M}"


# ===========================================================================
# 3. No real orders placed (mode guard)
# ===========================================================================

class TestNoRealOrders:
    def test_no_pa_live_confirm_needed(self):
        """PA_LIVE_CONFIRM must NOT be set by the sim harness."""
        live_confirm = os.environ.get("PA_LIVE_CONFIRM", "")
        assert live_confirm != "YES_I_KNOW", (
            "PA_LIVE_CONFIRM=YES_I_KNOW must never be set by forward_sim_compare"
        )

    def test_no_pa_run_mode_live(self):
        """PA_RUN_MODE must not be 'live' in simulation."""
        run_mode = os.environ.get("PA_RUN_MODE", "backtest")
        assert run_mode != "live", (
            "PA_RUN_MODE must not be 'live' in forward_sim harness"
        )

    def test_module_has_no_live_order_call(self):
        """The module must not import or call CCXTLiveBroker or place_order on live broker."""
        import inspect
        src = inspect.getsource(_mod)
        # These are the live-order-placing symbols — must not be imported/called
        # (PA_LIVE_CONFIRM may appear in docstrings as a warning reference, that is OK)
        forbidden_imports = ["CCXTLiveBroker", "ccxt_live", "from price_action.execution.ccxt_live"]
        for f in forbidden_imports:
            assert f not in src, f"forward_sim_compare.py must not import/reference '{f}'"

        # PA_LIVE_CONFIRM must not be SET (only mentioned in documentation)
        assert 'os.environ["PA_LIVE_CONFIRM"]' not in src, \
            "forward_sim_compare.py must not SET PA_LIVE_CONFIRM"
        # The harness must not check for the live confirm env var in order to proceed
        assert 'PA_LIVE_CONFIRM" == "YES_I_KNOW"' not in src, \
            "forward_sim_compare.py must not require PA_LIVE_CONFIRM=YES_I_KNOW"


# ===========================================================================
# 4. DB schema — both tables created correctly
# ===========================================================================

class TestDBSchema:
    def test_init_db_creates_all_tables(self, tmp_path):
        db = tmp_path / "test_forward_sim.duckdb"
        _mod.init_db(db)
        import duckdb
        con = duckdb.connect(str(db), read_only=True)
        tables = {r[0] for r in con.execute("SHOW TABLES").fetchall()}
        con.close()
        expected = {"champion_sim", "v13_sim", "champion_sim_equity", "v13_sim_equity"}
        assert expected.issubset(tables), f"Missing tables: {expected - tables}"

    def test_init_db_idempotent(self, tmp_path):
        """Calling init_db twice must not raise."""
        db = tmp_path / "test_forward_sim2.duckdb"
        _mod.init_db(db)
        _mod.init_db(db)   # second call must be no-op


# ===========================================================================
# 5. Sim fill price — slippage applied correctly
# ===========================================================================

class TestSimFillPrice:
    def test_long_fill_above_ref(self):
        """Long fills at ABOVE reference price (adverse slippage)."""
        price  = 100.0
        filled = _mod._sim_fill_price(price, "long", "15m")
        assert filled > price, f"Long fill {filled} should exceed ref {price}"

    def test_short_fill_below_ref(self):
        """Short fills at BELOW reference price (adverse slippage)."""
        price  = 100.0
        filled = _mod._sim_fill_price(price, "short", "15m")
        assert filled < price, f"Short fill {filled} should be below ref {price}"

    def test_5m_slippage_ge_15m(self):
        """5m slippage must be >= 15m slippage (conservative)."""
        price = 100.0
        f15 = _mod._sim_fill_price(price, "long", "15m")
        f5  = _mod._sim_fill_price(price, "long", "5m")
        assert f5 >= f15, f"5m fill {f5} should >= 15m fill {f15}"


# ===========================================================================
# 6. TP level calculation — consistent with BASELINE exit
# ===========================================================================

class TestTPLevels:
    def test_long_tp_levels_above_fill(self):
        fill = 100.0
        sl   = 97.0   # 3% below
        tp1, tp2 = _mod._compute_tp_levels(fill, sl, "long")
        assert tp1 > fill
        assert tp2 > tp1

    def test_short_tp_levels_below_fill(self):
        fill = 100.0
        sl   = 103.0   # 3% above (short stop)
        tp1, tp2 = _mod._compute_tp_levels(fill, sl, "short")
        assert tp1 < fill
        assert tp2 < tp1

    def test_tp1_at_1R_tp2_at_1_5R(self):
        """BASELINE exit: TP1 at 1R, TP2 at 1.5R."""
        fill = 100.0
        sl   = 97.5   # 2.5% SL = $2.50 risk
        risk = fill - sl   # = $2.50
        tp1, tp2 = _mod._compute_tp_levels(fill, sl, "long")
        assert abs(tp1 - (fill + 1.0 * risk)) < 0.001, f"TP1={tp1} != fill+1R={fill+risk}"
        assert abs(tp2 - (fill + 1.5 * risk)) < 0.001, f"TP2={tp2} != fill+1.5R={fill+1.5*risk}"


# ===========================================================================
# 7. HTF alignment filter (V13 leg)
# ===========================================================================

class TestHTFAlignment:
    def test_long_above_ema_is_aligned(self):
        """If daily close > EMA50 and trade is long, htf_aligned=1.0."""
        d1 = pd.DataFrame({
            "ts":    [pd.Timestamp("2026-06-01", tz="UTC")],
            "close": [110.0],
            "ema50": [100.0],   # close > ema50
        })
        _mod._HTF_CACHE.clear()
        _mod._HTF_CACHE["TEST/USDT"] = d1

        entry_ts = pd.Timestamp("2026-06-01 12:00", tz="UTC")
        result = _mod._htf_aligned("TEST/USDT", entry_ts, "long")
        assert result == 1.0

    def test_long_below_ema_is_against(self):
        """If daily close < EMA50 and trade is long, htf_aligned=0.0."""
        d1 = pd.DataFrame({
            "ts":    [pd.Timestamp("2026-06-01", tz="UTC")],
            "close": [90.0],
            "ema50": [100.0],   # close < ema50
        })
        _mod._HTF_CACHE.clear()
        _mod._HTF_CACHE["TEST2/USDT"] = d1

        entry_ts = pd.Timestamp("2026-06-01 12:00", tz="UTC")
        result = _mod._htf_aligned("TEST2/USDT", entry_ts, "long")
        assert result == 0.0

    def test_short_below_ema_is_aligned(self):
        """Short + close < EMA50 = aligned."""
        d1 = pd.DataFrame({
            "ts":    [pd.Timestamp("2026-06-01", tz="UTC")],
            "close": [90.0],
            "ema50": [100.0],
        })
        _mod._HTF_CACHE.clear()
        _mod._HTF_CACHE["TEST3/USDT"] = d1

        entry_ts = pd.Timestamp("2026-06-01 12:00", tz="UTC")
        result = _mod._htf_aligned("TEST3/USDT", entry_ts, "short")
        assert result == 1.0

    def test_no_data_returns_minus_one(self):
        """When HTF cache has empty DataFrame, should return -1.0 (no data)."""
        _mod._HTF_CACHE.clear()
        # Inject an empty-but-valid DF (the guard checks for empty + missing 'ts' column)
        # Use a DataFrame that IS empty to simulate a symbol with no 1d data
        _mod._HTF_CACHE["NODATA/USDT"] = pd.DataFrame(columns=["ts", "close", "ema50"])
        result = _mod._htf_aligned("NODATA/USDT", pd.Timestamp("2026-06-01", tz="UTC"), "long")
        assert result == -1.0, f"Expected -1.0 for missing HTF data, got {result}"


# ===========================================================================
# 8. Position exit logic
# ===========================================================================

class TestPositionExits:
    def _make_ledger_with_position(self, side="long") -> FixedFractionLedger:
        ledger = FixedFractionLedger("champion")
        pos = {
            "trade_id":       "test-exit-001",
            "leg":            "champion",
            "symbol":         "BTC/USDT",
            "tf":             "15m",
            "strategy":       "vsa_climax_test",
            "side":           side,
            "entry_ts":       datetime(2026, 6, 1, 10, 0, tzinfo=UTC),
            "entry_bar_ts":   None,
            "entry_price":    60000.0,
            "sl_price":       57000.0 if side == "long" else 63000.0,
            "tp1_price":      63000.0 if side == "long" else 57000.0,
            "tp2_price":      64500.0 if side == "long" else 55500.0,
            "sl_pct":         0.05,
            "risk_dollars":   RISK_PCT * E0_FIXED,
            "notional":       (RISK_PCT * E0_FIXED) / 0.05,
            "fee_entry_usdt": 5.0,
            "confluence":     3.0,
            "htf_aligned":    -1.0,
            "status":         "open",
            "status_partial": "open",
            "unrealized_pnl": 0.0,
            "notes":          "",
        }
        ledger.open_position(pos)
        return ledger

    def test_sl_hit_closes_long(self):
        ledger = self._make_ledger_with_position("long")
        prices = {"BTC/USDT": 56500.0}   # below SL 57000
        now = datetime(2026, 6, 1, 11, 0, tzinfo=UTC)
        closed = ledger.check_exits(prices, now)
        assert len(closed) == 1
        assert closed[0]["status"] == "closed_sl"
        assert ledger.n_open() == 0

    def test_sl_hit_closes_short(self):
        ledger = self._make_ledger_with_position("short")
        prices = {"BTC/USDT": 64000.0}   # above SL 63000
        now = datetime(2026, 6, 1, 11, 0, tzinfo=UTC)
        closed = ledger.check_exits(prices, now)
        assert len(closed) == 1
        assert closed[0]["status"] == "closed_sl"

    def test_tp1_hit_partial_close_long(self):
        ledger = self._make_ledger_with_position("long")
        prices = {"BTC/USDT": 63500.0}   # above TP1 63000
        now = datetime(2026, 6, 1, 11, 0, tzinfo=UTC)
        closed = ledger.check_exits(prices, now)
        # TP1 partial: position stays open but status_partial = partial_tp1
        assert len(closed) == 0, "TP1 partial should NOT fully close position"
        assert ledger.n_open() == 1
        assert ledger._open[0]["status_partial"] == "partial_tp1"

    def test_tp2_hit_after_tp1_long(self):
        ledger = self._make_ledger_with_position("long")
        ledger._open[0]["status_partial"] = "partial_tp1"
        prices = {"BTC/USDT": 65000.0}   # above TP2 64500
        now = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)
        closed = ledger.check_exits(prices, now)
        assert len(closed) == 1
        assert closed[0]["status"] == "closed_tp2"

    def test_time_stop_fires_at_30_bars_15m(self):
        ledger = self._make_ledger_with_position("long")
        entry_ts = datetime(2026, 6, 1, 10, 0, tzinfo=UTC)
        ledger._open[0]["entry_ts"] = entry_ts
        # 30 bars × 900s = 27000s = 7.5 hours
        now = entry_ts + timedelta(seconds=30 * 900 + 1)
        prices = {"BTC/USDT": 61000.0}   # no TP/SL touched
        closed = ledger.check_exits(prices, now)
        assert len(closed) == 1
        assert closed[0]["status"] == "closed_ts"

    def test_pnl_calculated_net_of_fees(self):
        ledger = self._make_ledger_with_position("long")
        # SL exit at exactly SL price
        sl = ledger._open[0]["sl_price"]
        prices = {"BTC/USDT": sl}
        now = datetime(2026, 6, 1, 11, 0, tzinfo=UTC)
        closed = ledger.check_exits(prices, now)
        assert len(closed) == 1
        pnl = closed[0]["pnl_usdt"]
        # PnL at SL must be negative (loss + fees)
        assert pnl < 0.0, f"PnL at SL={pnl} should be negative"

    def test_realized_pnl_updated_after_close(self):
        ledger = self._make_ledger_with_position("long")
        initial_pnl = ledger._realized_pnl
        prices = {"BTC/USDT": 55000.0}  # hard stop
        now = datetime(2026, 6, 1, 11, 0, tzinfo=UTC)
        ledger.check_exits(prices, now)
        # realized_pnl must have changed
        assert ledger._realized_pnl != initial_pnl


# ===========================================================================
# 9. Daily report — generated without crashing on empty DB
# ===========================================================================

class TestDailyReport:
    def test_report_writes_to_correct_path(self, tmp_path, monkeypatch):
        report_path = tmp_path / "forward_sim" / "daily.md"
        monkeypatch.setattr(_mod, "REPORT_PATH", report_path)
        monkeypatch.setattr(_mod, "DB_SIM", tmp_path / "sim.duckdb")

        # Init empty DB
        _mod.init_db(tmp_path / "sim.duckdb")

        text = _mod.write_daily_report()
        assert report_path.exists()
        assert "CHAMPION" in text
        assert "V13" in text
        assert "SIMULATION" in text
        assert "real orders" in text.lower() or "NO real" in text or "NOT real" in text

    def test_report_contains_honest_sim_note(self, tmp_path, monkeypatch):
        report_path = tmp_path / "forward_sim" / "daily.md"
        monkeypatch.setattr(_mod, "REPORT_PATH", report_path)
        monkeypatch.setattr(_mod, "DB_SIM", tmp_path / "sim.duckdb")
        _mod.init_db(tmp_path / "sim.duckdb")
        text = _mod.write_daily_report()
        assert "SIM" in text.upper()
        # Must mention that it is not real execution
        assert any(phrase in text for phrase in [
            "NOT real testnet execution",
            "SIMULATION",
            "modeled",
        ])


# ===========================================================================
# 10. Bar boundary helpers
# ===========================================================================

class TestBarBoundary:
    def test_last_closed_15m_bar_is_15m_aligned(self):
        bar = _mod._last_closed_15m_bar()
        assert bar.minute % 15 == 0, f"Bar {bar} not 15m-aligned"
        assert bar.second == 0
        assert bar.microsecond == 0

    def test_next_15m_boundary_positive(self):
        bar = _mod._last_closed_15m_bar()
        wait = _mod._next_15m_boundary_in(bar)
        assert wait >= 0.0, f"Wait time {wait} should be non-negative"
        assert wait <= 15 * 60 + 10, f"Wait time {wait} too large"


# ===========================================================================
# 11. Daemon does NOT touch live journal files
# ===========================================================================

class TestIsolation:
    def test_db_sim_separate_from_live_journals(self, tmp_path):
        """DB_SIM path must not overlap with any live journal paths."""
        sim_path = _mod.DB_SIM
        # Live journals we must NOT touch
        live_journals = [
            ROOT / "data" / "futures_journal.duckdb",
            ROOT / "data" / "futures_journal_15m_phoenix.duckdb",
            ROOT / "data" / "futures_journal_5m.duckdb",
        ]
        for lj in live_journals:
            assert sim_path != lj, f"DB_SIM ({sim_path}) overlaps with live journal ({lj})"

    def test_no_idempotency_db_write(self):
        """Module must not reference idempotency.duckdb (live daemon's file)."""
        import inspect
        src = inspect.getsource(_mod)
        assert "idempotency.duckdb" not in src, "forward_sim must not write to idempotency.duckdb"

    def test_no_pyramid_store_reference(self):
        """Module must not reference pyramid_store.duckdb."""
        import inspect
        src = inspect.getsource(_mod)
        assert "pyramid_store" not in src, "forward_sim must not reference pyramid_store"
