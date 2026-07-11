"""15m equity snapshot canlı-kanıt hattı."""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

import scripts.futures_daemon as fd  # noqa: E402


def _create_snapshot_table(db: Path) -> None:
    con = duckdb.connect(str(db))
    con.execute(
        """CREATE TABLE futures_equity_snapshots (
               notes VARCHAR,
               snapshot_id VARCHAR PRIMARY KEY,
               wallet_balance DOUBLE,
               ts TIMESTAMP,
               margin_balance DOUBLE,
               unrealized_pnl DOUBLE,
               n_open_orders INTEGER,
               available_balance DOUBLE,
               n_positions INTEGER,
               schema_version INTEGER DEFAULT 1
           )"""
    )
    con.close()


def _state(wallet: float = 1000.0) -> dict:
    return {
        "wallet_balance": wallet,
        "unrealized_pnl": 12.5,
        "margin_balance": wallet + 12.5,
        "available_balance": 700.0,
        "n_positions": 2,
        "n_open_orders": 5,
        "positions_ok": True,
    }


def test_snapshot_writer_is_explicit_column_and_idempotent(tmp_path):
    db = tmp_path / "journal.duckdb"
    _create_snapshot_table(db)
    ts = datetime(2026, 7, 11, 12, 15, tzinfo=UTC)
    snapshot_id = "v15p2_15m_20260711T1215Z"

    assert (
        fd._write_equity_snapshot(
            _state(),
            journal_path=db,
            snapshot_id=snapshot_id,
            snapshot_ts=ts,
            notes="15m_bar_g19",
        )
        == snapshot_id
    )
    # Aynı bar retry edilirse ikinci satır veya overwrite oluşmaz.
    fd._write_equity_snapshot(
        _state(wallet=9999.0),
        journal_path=db,
        snapshot_id=snapshot_id,
        snapshot_ts=ts,
        notes="retry",
    )

    con = duckdb.connect(str(db))
    row = con.execute(
        """SELECT snapshot_id, ts, wallet_balance, unrealized_pnl, margin_balance,
                  available_balance, n_positions, n_open_orders, notes,
                  schema_version
           FROM futures_equity_snapshots"""
    ).fetchone()
    count = con.execute("SELECT COUNT(*) FROM futures_equity_snapshots").fetchone()[0]
    con.close()

    assert count == 1
    assert row == (
        snapshot_id,
        datetime(2026, 7, 11, 12, 15),
        1000.0,
        12.5,
        1012.5,
        700.0,
        2,
        5,
        "15m_bar_g19 positions_ok=true",
        1,
    )


def test_snapshot_writer_marks_stale_position_quality(tmp_path):
    db = tmp_path / "stale.duckdb"
    _create_snapshot_table(db)
    stale = _state()
    stale["positions_ok"] = False
    stale["n_positions"] = 0
    fd._write_equity_snapshot(stale, journal_path=db, notes="15m_bar_g19")

    with duckdb.connect(str(db), read_only=True) as con:
        notes = con.execute("SELECT notes FROM futures_equity_snapshots").fetchone()[0]
    assert notes == "15m_bar_g19 positions_ok=false API_STALE"


def test_15m_g19_state_is_wired_to_deterministic_snapshot():
    src = (ROOT / "scripts" / "futures_daemon.py").read_text(encoding="utf-8")
    assert "_write_equity_snapshot(" in src
    assert "snapshot_ts=current_boundary" in src
    assert 'notes="15m_bar_g19"' in src
    assert "current_boundary.strftime('%Y%m%dT%H%MZ')" in src
    assert "INSERT OR IGNORE INTO futures_equity_snapshots" in src
    assert "(snapshot_id, ts, wallet_balance" in src
    assert "_utc_naive_timestamp(" in src
    assert 'sig.get("bar_close_ts") or sig.get("ts")' in src
