"""Forex slippage tracker — record fills, compute slippage in pips, alert on outliers."""
from __future__ import annotations

import logging
import threading
from datetime import datetime, time, timezone
from pathlib import Path
from typing import Callable, Optional

import duckdb

from ..contracts import PIP_SIZE

logger = logging.getLogger(__name__)
_WRITE_LOCK = threading.Lock()


class SlippageTracker:
    """Records fill slippage in pips (signed: positive = adverse).

    Schema:
        forex_slippage(ts, pair, side, intended_price, fill_price,
                       slippage_pips, lots, alarm)
    """

    def __init__(
        self,
        db_path: str | Path = "data/forex/forex_slippage.duckdb",
        warn_pips: float = 1.5,
        critical_pips: float = 5.0,
        alarm_cb: Optional[Callable[[str], None]] = None,
    ):
        self.db_path = str(db_path)
        self.warn_pips = warn_pips
        self.critical_pips = critical_pips
        self.alarm_cb = alarm_cb
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        with duckdb.connect(self.db_path) as con:
            con.execute("""
                CREATE TABLE IF NOT EXISTS forex_slippage (
                    ts TIMESTAMP, pair TEXT, side TEXT,
                    intended_price DOUBLE, fill_price DOUBLE,
                    slippage_pips DOUBLE, lots DOUBLE, alarm TEXT
                )
            """)

    def record_fill(self, pair: str, side: str, intended_price: float,
                    fill_price: float, lots: float, ts: Optional[datetime] = None) -> float:
        if ts is None:
            ts = datetime.now(timezone.utc)
        pip = PIP_SIZE.get(pair, 0.0001)
        # Adverse direction: long → fill higher than intended; short → fill lower
        if side == "long":
            slip_pips = (fill_price - intended_price) / pip
        else:
            slip_pips = (intended_price - fill_price) / pip
        alarm = ""
        if slip_pips >= self.critical_pips:
            alarm = "CRITICAL"
        elif slip_pips >= self.warn_pips:
            alarm = "WARN"
        with _WRITE_LOCK:
            with duckdb.connect(self.db_path) as con:
                con.execute("INSERT INTO forex_slippage VALUES (?,?,?,?,?,?,?,?)",
                            [ts, pair, side, intended_price, fill_price, slip_pips, lots, alarm])
        if alarm and self.alarm_cb:
            self.alarm_cb(f"[{alarm}] slippage {pair} {side} {slip_pips:+.2f} pips (intended={intended_price:.5f} fill={fill_price:.5f})")
        return slip_pips

    def daily_summary(self, day: Optional[datetime] = None) -> dict:
        if day is None:
            day = datetime.now(timezone.utc)
        day_start = datetime.combine(day.date(), time.min, tzinfo=timezone.utc)
        day_end = datetime.combine(day.date(), time.max, tzinfo=timezone.utc)
        with duckdb.connect(self.db_path, read_only=True) as con:
            try:
                rows = con.execute("""
                    SELECT pair,
                           COUNT(*) AS fills,
                           AVG(slippage_pips) AS avg_slip,
                           MAX(slippage_pips) AS max_slip,
                           SUM(CASE WHEN alarm='CRITICAL' THEN 1 ELSE 0 END) AS critical_count,
                           SUM(CASE WHEN alarm='WARN' THEN 1 ELSE 0 END) AS warn_count
                    FROM forex_slippage WHERE ts>=? AND ts<=?
                    GROUP BY pair ORDER BY avg_slip DESC
                """, [day_start, day_end]).fetchall()
            except duckdb.CatalogException:
                return {}
        return {r[0]: {"fills": r[1], "avg_pips": float(r[2] or 0), "max_pips": float(r[3] or 0),
                       "critical": r[4], "warn": r[5]} for r in rows}
