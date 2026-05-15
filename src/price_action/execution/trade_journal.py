"""TradeJournal — kapanan futures trade kayıt + bugünkü realized PnL aggregation.

SEC26.B-4: `realized_pnl_today_futures()` artık equity_snapshot delta yerine
gerçek kapanmış trade'lerin SUM(realized_pnl_usdt) toplamından okusun.
Açık pozisyon unrealized değişimi daily_pnl'i kirletmesin → DD breaker doğru.

Schema (SEC26.B-3 ile ortak — CREATE IF NOT EXISTS idempotent):

    CREATE TABLE futures_trades_closed (
        trade_id TEXT PRIMARY KEY,
        ts_open TIMESTAMP,
        ts_close TIMESTAMP,
        sym TEXT,
        side TEXT,           -- 'long' | 'short'
        strategy TEXT,
        entry_price DOUBLE,
        exit_price DOUBLE,
        qty DOUBLE,
        realized_pnl_usdt DOUBLE,
        realized_r DOUBLE,
        win BOOLEAN,
        close_reason TEXT    -- 'tp' | 'sl' | 'time' | 'force'
    )

Public API:
    journal = TradeJournal()                           # default data/futures_journal.duckdb
    journal.record_close(trade_id, ts_open, ts_close,
                         sym, side, strategy,
                         entry_price, exit_price, qty,
                         sl_price, close_reason)       # → True/False (idempotent)
    pnl_today = journal.get_realized_pnl_today()       # USD bugün
    pnl_window = journal.get_realized_pnl_window(s, e) # arbitrary window
"""
from __future__ import annotations

import threading
from datetime import datetime, time, timezone
from pathlib import Path
from typing import Literal, Optional

import duckdb


# Module-level lock — concurrent record_close threads aynı trade_id için
# DuckDB constraint violation race'i önle (DuckDB PRIMARY KEY tablosu lock
# tutmuyor, pre-check + insert iki ayrı işlem). Bu lock process-içi yeterli.
_WRITE_LOCK = threading.Lock()


def _compute_realized_pnl(entry_price: float, exit_price: float,
                          qty: float, side: str) -> float:
    """Realized PnL (USDT). Linear futures (USDT-margined) for both sides.

    long:  (exit - entry) * qty
    short: (entry - exit) * qty
    """
    if side == "long":
        return (exit_price - entry_price) * qty
    elif side == "short":
        return (entry_price - exit_price) * qty
    else:
        raise ValueError(f"side must be 'long' or 'short', got {side!r}")


def _compute_realized_r(entry_price: float, exit_price: float,
                        side: str, sl_price: float) -> float:
    """Realized R = pnl_per_unit / risk_per_unit.

    Edge case: sl_price == entry_price → risk=0 → R=0 (clamp, no crash).
    Bu durum normalde olmamalı (signal builder sl_price'i entry'den uzakta
    set eder) ama defensive.
    """
    risk_per_unit = abs(entry_price - sl_price)
    if risk_per_unit <= 0.0:
        return 0.0
    if side == "long":
        pnl_per_unit = exit_price - entry_price
    elif side == "short":
        pnl_per_unit = entry_price - exit_price
    else:
        raise ValueError(f"side must be 'long' or 'short', got {side!r}")
    return pnl_per_unit / risk_per_unit


class TradeJournal:
    """Kapanan trade kayıt + bugünkü realized PnL aggregation.

    Idempotent (PRIMARY KEY trade_id, duplicate insert sessizce reddedilir).
    UTC consistent (tüm timestamp UTC olarak yorumlanır).
    """

    def __init__(self, db_path: str | Path = "data/futures_journal.duckdb") -> None:
        self.db_path = str(db_path)
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        """CREATE IF NOT EXISTS — SEC26.B-3 schema parity."""
        con = duckdb.connect(self.db_path)
        try:
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
        finally:
            con.close()

    def record_close(
        self,
        *,
        trade_id: str,
        ts_open: datetime,
        ts_close: datetime,
        sym: str,
        side: Literal["long", "short"],
        strategy: str,
        entry_price: float,
        exit_price: float,
        qty: float,
        sl_price: float,
        close_reason: Literal["tp", "sl", "time", "force"] = "tp",
    ) -> bool:
        """Kapanan trade'i kaydet. Idempotent — aynı trade_id 2. kez çağrılırsa False.

        Returns:
            True  → yeni kayıt eklendi
            False → trade_id zaten mevcut (idempotent no-op)

        No-clip: realized_pnl çok büyük olsa bile clip etmiyoruz.
        """
        # UTC normalize
        if ts_open.tzinfo is None:
            ts_open = ts_open.replace(tzinfo=timezone.utc)
        if ts_close.tzinfo is None:
            ts_close = ts_close.replace(tzinfo=timezone.utc)

        side = side.lower()  # type: ignore[assignment]
        realized_pnl = _compute_realized_pnl(entry_price, exit_price, qty, side)
        realized_r = _compute_realized_r(entry_price, exit_price, side, sl_price)
        win = realized_pnl > 0.0

        with _WRITE_LOCK:
            con = duckdb.connect(self.db_path)
            try:
                # Idempotent: pre-check + insert. PRIMARY KEY constraint extra safety.
                existing = con.execute(
                    "SELECT 1 FROM futures_trades_closed WHERE trade_id = ?",
                    [trade_id],
                ).fetchone()
                if existing:
                    return False
                try:
                    con.execute(
                        """
                        INSERT INTO futures_trades_closed VALUES
                        (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        [
                            trade_id, ts_open, ts_close, sym, side, strategy,
                            float(entry_price), float(exit_price), float(qty),
                            float(realized_pnl), float(realized_r),
                            bool(win), close_reason,
                        ],
                    )
                    con.commit()
                    return True
                except duckdb.ConstraintException:
                    # Race: başka thread/process aynı trade_id'yi insert etti.
                    return False
            finally:
                con.close()

    def get_realized_pnl_today(self, *, now: Optional[datetime] = None) -> float:
        """Bugünkü (UTC) realized PnL toplamı (USDT).

        UTC günü 00:00:00'da reset olur (kalan zaman dilimleri irrelevant
        — DD breaker UTC daily anchor ile tutarlı).
        """
        if now is None:
            now = datetime.now(timezone.utc)
        elif now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        day_start = datetime.combine(now.date(), time.min, tzinfo=timezone.utc)
        day_end = datetime.combine(now.date(), time.max, tzinfo=timezone.utc)
        return self.get_realized_pnl_window(day_start, day_end)

    def get_realized_pnl_window(self, start_utc: datetime,
                                end_utc: datetime) -> float:
        """[start_utc, end_utc] kapalı aralık için SUM(realized_pnl_usdt).

        Boş aralık veya tablo yokken 0.0.
        """
        if start_utc.tzinfo is None:
            start_utc = start_utc.replace(tzinfo=timezone.utc)
        if end_utc.tzinfo is None:
            end_utc = end_utc.replace(tzinfo=timezone.utc)
        con = duckdb.connect(self.db_path, read_only=True)
        try:
            row = con.execute(
                """
                SELECT COALESCE(SUM(realized_pnl_usdt), 0.0)
                FROM futures_trades_closed
                WHERE ts_close >= ? AND ts_close <= ?
                """,
                [start_utc, end_utc],
            ).fetchone()
            if row is None or row[0] is None:
                return 0.0
            return float(row[0])
        except duckdb.CatalogException:
            # Tablo yok (yeni DB, schema henüz yaratılmadı)
            return 0.0
        finally:
            con.close()


__all__ = [
    "TradeJournal",
    "_compute_realized_pnl",
    "_compute_realized_r",
]
