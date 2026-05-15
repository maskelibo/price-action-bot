"""TradeJournal testleri — SEC26.B-4 realized PnL journal.

8 test:
  1. test_record_close_long_win
  2. test_record_close_long_loss
  3. test_record_close_short_win
  4. test_record_close_short_loss
  5. test_realized_r_zero_when_sl_equals_entry
  6. test_get_realized_pnl_today_aggregates
  7. test_idempotent_insert_same_trade_id
  8. test_concurrent_close_safe
"""
from __future__ import annotations

import os
import tempfile
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

import duckdb
import pytest

from price_action.execution.trade_journal import (
    TradeJournal,
    _compute_realized_pnl,
    _compute_realized_r,
)


# ── helper ─────────────────────────────────────────────────────────────────────

def _tmp_db() -> Path:
    """Geçici DuckDB path."""
    p = tempfile.mktemp(suffix=".duckdb")
    return Path(p)


def _cleanup(p: Path):
    try:
        os.unlink(p)
    except Exception:
        pass


# ── Test 1: long win ───────────────────────────────────────────────────────────

def test_record_close_long_win():
    """Long entry 100 → exit 110 (TP), sl=95, qty=1 → pnl=+10, R=+2."""
    db = _tmp_db()
    try:
        tj = TradeJournal(db_path=str(db))
        now = datetime.now(timezone.utc)
        ok = tj.record_close(
            trade_id="t1",
            ts_open=now - timedelta(hours=2),
            ts_close=now,
            sym="BTC/USDT", side="long", strategy="engulfing",
            entry_price=100.0, exit_price=110.0, qty=1.0,
            sl_price=95.0, close_reason="tp",
        )
        assert ok is True

        con = duckdb.connect(str(db), read_only=True)
        row = con.execute(
            "SELECT realized_pnl_usdt, realized_r, win, close_reason "
            "FROM futures_trades_closed WHERE trade_id='t1'"
        ).fetchone()
        con.close()
        assert row is not None
        pnl, r, win, reason = row
        assert pnl == pytest.approx(10.0)
        assert r == pytest.approx(2.0)  # (110-100)/(100-95)=10/5=2
        assert win is True
        assert reason == "tp"
    finally:
        _cleanup(db)


# ── Test 2: long loss ──────────────────────────────────────────────────────────

def test_record_close_long_loss():
    """Long entry 100 → exit 95 (SL), sl=95, qty=1 → pnl=-5, R=-1."""
    db = _tmp_db()
    try:
        tj = TradeJournal(db_path=str(db))
        now = datetime.now(timezone.utc)
        tj.record_close(
            trade_id="t2",
            ts_open=now - timedelta(hours=1),
            ts_close=now,
            sym="ETH/USDT", side="long", strategy="pin_bar",
            entry_price=100.0, exit_price=95.0, qty=1.0,
            sl_price=95.0, close_reason="sl",
        )
        con = duckdb.connect(str(db), read_only=True)
        row = con.execute(
            "SELECT realized_pnl_usdt, realized_r, win, close_reason "
            "FROM futures_trades_closed WHERE trade_id='t2'"
        ).fetchone()
        con.close()
        pnl, r, win, reason = row
        assert pnl == pytest.approx(-5.0)
        assert r == pytest.approx(-1.0)  # (95-100)/(100-95)=-5/5=-1
        assert win is False
        assert reason == "sl"
    finally:
        _cleanup(db)


# ── Test 3: short win ──────────────────────────────────────────────────────────

def test_record_close_short_win():
    """Short entry 100 → exit 95 (TP), sl=105, qty=1 → pnl=+5, R=+1."""
    db = _tmp_db()
    try:
        tj = TradeJournal(db_path=str(db))
        now = datetime.now(timezone.utc)
        tj.record_close(
            trade_id="t3", ts_open=now, ts_close=now,
            sym="SOL/USDT", side="short", strategy="engulfing",
            entry_price=100.0, exit_price=95.0, qty=1.0,
            sl_price=105.0, close_reason="tp",
        )
        con = duckdb.connect(str(db), read_only=True)
        row = con.execute(
            "SELECT realized_pnl_usdt, realized_r, win "
            "FROM futures_trades_closed WHERE trade_id='t3'"
        ).fetchone()
        con.close()
        pnl, r, win = row
        assert pnl == pytest.approx(5.0)  # (100-95)*1
        assert r == pytest.approx(1.0)    # (100-95)/|100-105|=5/5=1
        assert win is True
    finally:
        _cleanup(db)


# ── Test 4: short loss ─────────────────────────────────────────────────────────

def test_record_close_short_loss():
    """Short entry 100 → exit 110 (SL), sl=105, qty=1 → pnl=-10, R=-2."""
    db = _tmp_db()
    try:
        tj = TradeJournal(db_path=str(db))
        now = datetime.now(timezone.utc)
        tj.record_close(
            trade_id="t4", ts_open=now, ts_close=now,
            sym="BNB/USDT", side="short", strategy="cvd_spike",
            entry_price=100.0, exit_price=110.0, qty=1.0,
            sl_price=105.0, close_reason="sl",
        )
        con = duckdb.connect(str(db), read_only=True)
        row = con.execute(
            "SELECT realized_pnl_usdt, realized_r, win "
            "FROM futures_trades_closed WHERE trade_id='t4'"
        ).fetchone()
        con.close()
        pnl, r, win = row
        assert pnl == pytest.approx(-10.0)  # (100-110)*1
        assert r == pytest.approx(-2.0)     # -10/5=-2
        assert win is False
    finally:
        _cleanup(db)


# ── Test 5: R-edge case ────────────────────────────────────────────────────────

def test_realized_r_zero_when_sl_equals_entry():
    """SL == entry → risk_per_unit=0 → R=0 (defensive clamp, no crash)."""
    db = _tmp_db()
    try:
        tj = TradeJournal(db_path=str(db))
        now = datetime.now(timezone.utc)
        ok = tj.record_close(
            trade_id="t5", ts_open=now, ts_close=now,
            sym="ADA/USDT", side="long", strategy="test",
            entry_price=1.0, exit_price=1.5, qty=10.0,
            sl_price=1.0,  # SL == entry
            close_reason="tp",
        )
        assert ok is True

        con = duckdb.connect(str(db), read_only=True)
        row = con.execute(
            "SELECT realized_pnl_usdt, realized_r "
            "FROM futures_trades_closed WHERE trade_id='t5'"
        ).fetchone()
        con.close()
        pnl, r = row
        assert pnl == pytest.approx(5.0)  # (1.5-1.0)*10
        assert r == 0.0  # defensive clamp
    finally:
        _cleanup(db)


# ── Test 6: aggregate today PnL ────────────────────────────────────────────────

def test_get_realized_pnl_today_aggregates():
    """3 trade bugün UTC, 1 trade dün → bugün toplam = today_3 SUM, dünki hariç."""
    db = _tmp_db()
    try:
        tj = TradeJournal(db_path=str(db))
        now = datetime.now(timezone.utc)
        yday = now - timedelta(days=1)

        # 3 trade bugün, farklı PnL
        tj.record_close(
            trade_id="today_1", ts_open=now, ts_close=now,
            sym="BTC/USDT", side="long", strategy="s",
            entry_price=100.0, exit_price=110.0, qty=1.0,
            sl_price=95.0, close_reason="tp",
        )
        tj.record_close(
            trade_id="today_2", ts_open=now, ts_close=now,
            sym="ETH/USDT", side="long", strategy="s",
            entry_price=100.0, exit_price=98.0, qty=1.0,
            sl_price=95.0, close_reason="sl",
        )
        tj.record_close(
            trade_id="today_3", ts_open=now, ts_close=now,
            sym="SOL/USDT", side="short", strategy="s",
            entry_price=100.0, exit_price=95.0, qty=2.0,
            sl_price=105.0, close_reason="tp",
        )
        # 1 trade dün
        tj.record_close(
            trade_id="yday_1", ts_open=yday, ts_close=yday,
            sym="BNB/USDT", side="long", strategy="s",
            entry_price=100.0, exit_price=150.0, qty=1.0,
            sl_price=95.0, close_reason="tp",
        )

        # Bugünkü toplam: +10 + -2 + +10 = +18
        pnl_today = tj.get_realized_pnl_today(now=now)
        assert pnl_today == pytest.approx(18.0)

        # Dün'kü trade dahil edilmemeli
        assert pnl_today != pytest.approx(18.0 + 50.0)
    finally:
        _cleanup(db)


# ── Test 7: idempotency ────────────────────────────────────────────────────────

def test_idempotent_insert_same_trade_id():
    """Aynı trade_id 2 kez → 1 satır, 2. çağrı False döner."""
    db = _tmp_db()
    try:
        tj = TradeJournal(db_path=str(db))
        now = datetime.now(timezone.utc)
        ok1 = tj.record_close(
            trade_id="dup", ts_open=now, ts_close=now,
            sym="BTC/USDT", side="long", strategy="s",
            entry_price=100.0, exit_price=110.0, qty=1.0,
            sl_price=95.0, close_reason="tp",
        )
        assert ok1 is True

        # 2. kez aynı trade_id (farklı parametreler — yine de reject)
        ok2 = tj.record_close(
            trade_id="dup", ts_open=now, ts_close=now,
            sym="BTC/USDT", side="long", strategy="s",
            entry_price=999.0, exit_price=1000.0, qty=1.0,
            sl_price=900.0, close_reason="sl",
        )
        assert ok2 is False

        con = duckdb.connect(str(db), read_only=True)
        cnt = con.execute(
            "SELECT COUNT(*) FROM futures_trades_closed WHERE trade_id='dup'"
        ).fetchone()[0]
        # Orijinal değer korunmalı (2. INSERT ignore edildi)
        row = con.execute(
            "SELECT entry_price FROM futures_trades_closed WHERE trade_id='dup'"
        ).fetchone()
        con.close()
        assert cnt == 1, f"Idempotent fail: {cnt} satır oluştu"
        assert row[0] == pytest.approx(100.0)  # ilk INSERT korundu
    finally:
        _cleanup(db)


# ── Test 8: concurrent safety ──────────────────────────────────────────────────

def test_concurrent_close_safe():
    """2 thread aynı trade_id'yi paralel insert → toplamda 1 satır."""
    db = _tmp_db()
    try:
        tj = TradeJournal(db_path=str(db))
        now = datetime.now(timezone.utc)
        results: list[bool] = []

        def _worker():
            ok = tj.record_close(
                trade_id="race",
                ts_open=now, ts_close=now,
                sym="BTC/USDT", side="long", strategy="s",
                entry_price=100.0, exit_price=110.0, qty=1.0,
                sl_price=95.0, close_reason="tp",
            )
            results.append(ok)

        threads = [threading.Thread(target=_worker) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Tam 1 thread True dönmeli, 4 thread False
        assert sum(1 for r in results if r) == 1, (
            f"Expected exactly 1 successful insert, got {sum(1 for r in results if r)} "
            f"(results={results})"
        )
        con = duckdb.connect(str(db), read_only=True)
        cnt = con.execute(
            "SELECT COUNT(*) FROM futures_trades_closed WHERE trade_id='race'"
        ).fetchone()[0]
        con.close()
        assert cnt == 1, f"Race condition: {cnt} satır (1 bekleniyordu)"
    finally:
        _cleanup(db)


# ── Bonus: pure-function tests for compute helpers ─────────────────────────────

def test_compute_realized_pnl_directional():
    """Pure helper: long/short PnL sign correctness."""
    assert _compute_realized_pnl(100, 110, 1, "long") == pytest.approx(10.0)
    assert _compute_realized_pnl(100, 95, 1, "long") == pytest.approx(-5.0)
    assert _compute_realized_pnl(100, 95, 1, "short") == pytest.approx(5.0)
    assert _compute_realized_pnl(100, 110, 1, "short") == pytest.approx(-10.0)
    # qty multiplier
    assert _compute_realized_pnl(100, 110, 2, "long") == pytest.approx(20.0)


def test_compute_realized_r_directional():
    """Pure helper: R sign + magnitude."""
    # long: entry 100, sl 95 → 1R=5
    assert _compute_realized_r(100, 110, "long", 95) == pytest.approx(2.0)
    assert _compute_realized_r(100, 95, "long", 95) == pytest.approx(-1.0)
    # short: entry 100, sl 105 → 1R=5
    assert _compute_realized_r(100, 95, "short", 105) == pytest.approx(1.0)
    assert _compute_realized_r(100, 110, "short", 105) == pytest.approx(-2.0)
    # zero-risk edge
    assert _compute_realized_r(100, 110, "long", 100) == 0.0
