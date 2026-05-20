"""Forex TradeJournal — persistent kapanan trade kayıt + realized PnL aggregation.

Forex-adapted (crypto sibling src/price_action/execution/trade_journal.py):
- USDT → USD account currency
- + spread_paid_pips, commission_usd, swap_usd, slippage_pips fields
- + session column for per-session breakdown
- DuckDB persistent, idempotent (PRIMARY KEY trade_id)

Schema:
    CREATE TABLE forex_trades_closed (
        trade_id TEXT PRIMARY KEY,
        ts_open TIMESTAMP,
        ts_close TIMESTAMP,
        pair TEXT,
        side TEXT,          -- 'long' | 'short'
        strategy TEXT,
        session TEXT,        -- 'asia' | 'london' | 'london_ny_overlap' | 'ny' | 'off'
        entry_price DOUBLE,
        exit_price DOUBLE,
        lots DOUBLE,
        sl_price DOUBLE,
        realized_usd DOUBLE,
        realized_r DOUBLE,
        win BOOLEAN,
        close_reason TEXT,   -- 'tp1'|'tp2'|'runner'|'sl'|'time'|'news_close'|'force'
        spread_paid_pips DOUBLE,
        commission_usd DOUBLE,
        swap_usd DOUBLE,
        slippage_pips DOUBLE,
        duration_min INT
    )
"""
from __future__ import annotations

import threading
from datetime import datetime, time, timezone
from pathlib import Path
from typing import Literal, Optional

import duckdb

_WRITE_LOCK = threading.Lock()


class TradeJournal:
    """Persistent forex trade journal with realized PnL aggregation."""

    def __init__(self, db_path: str | Path = "data/forex/forex_journal.duckdb") -> None:
        self.db_path = str(db_path)
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        con = duckdb.connect(self.db_path)
        try:
            con.execute("""
                CREATE TABLE IF NOT EXISTS forex_trades_closed (
                    trade_id TEXT PRIMARY KEY,
                    ts_open TIMESTAMP,
                    ts_close TIMESTAMP,
                    pair TEXT,
                    side TEXT,
                    strategy TEXT,
                    session TEXT,
                    entry_price DOUBLE,
                    exit_price DOUBLE,
                    lots DOUBLE,
                    sl_price DOUBLE,
                    realized_usd DOUBLE,
                    realized_r DOUBLE,
                    win BOOLEAN,
                    close_reason TEXT,
                    spread_paid_pips DOUBLE,
                    commission_usd DOUBLE,
                    swap_usd DOUBLE,
                    slippage_pips DOUBLE,
                    duration_min INTEGER
                )
            """)
            con.commit()
        finally:
            con.close()

    def record_close(
        self,
        *,
        trade_id: str,
        ts_open: datetime,
        ts_close: datetime,
        pair: str,
        side: Literal["long", "short"],
        strategy: str,
        session: str,
        entry_price: float,
        exit_price: float,
        lots: float,
        sl_price: float,
        realized_usd: float,
        realized_r: float,
        close_reason: str = "tp",
        spread_paid_pips: float = 0.0,
        commission_usd: float = 0.0,
        swap_usd: float = 0.0,
        slippage_pips: float = 0.0,
        duration_min: int = 0,
    ) -> bool:
        if ts_open.tzinfo is None:
            ts_open = ts_open.replace(tzinfo=timezone.utc)
        if ts_close.tzinfo is None:
            ts_close = ts_close.replace(tzinfo=timezone.utc)
        win = realized_usd > 0.0
        with _WRITE_LOCK:
            con = duckdb.connect(self.db_path)
            try:
                if con.execute("SELECT 1 FROM forex_trades_closed WHERE trade_id=?", [trade_id]).fetchone():
                    return False
                try:
                    con.execute(
                        """INSERT INTO forex_trades_closed VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        [
                            trade_id, ts_open, ts_close, pair, side, strategy, session,
                            float(entry_price), float(exit_price), float(lots), float(sl_price),
                            float(realized_usd), float(realized_r), bool(win), close_reason,
                            float(spread_paid_pips), float(commission_usd), float(swap_usd),
                            float(slippage_pips), int(duration_min),
                        ],
                    )
                    con.commit()
                    return True
                except duckdb.ConstraintException:
                    return False
            finally:
                con.close()

    def get_realized_pnl_today(self, *, now: Optional[datetime] = None) -> float:
        if now is None:
            now = datetime.now(timezone.utc)
        elif now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        day_start = datetime.combine(now.date(), time.min, tzinfo=timezone.utc)
        day_end = datetime.combine(now.date(), time.max, tzinfo=timezone.utc)
        return self.get_realized_pnl_window(day_start, day_end)

    def get_realized_pnl_window(self, start_utc: datetime, end_utc: datetime) -> float:
        if start_utc.tzinfo is None:
            start_utc = start_utc.replace(tzinfo=timezone.utc)
        if end_utc.tzinfo is None:
            end_utc = end_utc.replace(tzinfo=timezone.utc)
        con = duckdb.connect(self.db_path, read_only=True)
        try:
            row = con.execute(
                "SELECT COALESCE(SUM(realized_usd),0.0) FROM forex_trades_closed WHERE ts_close>=? AND ts_close<=?",
                [start_utc, end_utc],
            ).fetchone()
            return float(row[0]) if row and row[0] is not None else 0.0
        except duckdb.CatalogException:
            return 0.0
        finally:
            con.close()

    def count_consecutive_losses(self, pair: Optional[str] = None, lookback_days: int = 30) -> int:
        """Recent consecutive losses (from most recent backwards). Stops on win or lookback boundary."""
        con = duckdb.connect(self.db_path, read_only=True)
        try:
            q = (
                "SELECT win FROM forex_trades_closed "
                "WHERE ts_close >= now() - INTERVAL ? DAY "
                + ("AND pair=? " if pair else "")
                + "ORDER BY ts_close DESC"
            )
            params = [lookback_days] + ([pair] if pair else [])
            rows = con.execute(q, params).fetchall()
        except duckdb.CatalogException:
            return 0
        finally:
            con.close()
        count = 0
        for (win,) in rows:
            if win:
                break
            count += 1
        return count
