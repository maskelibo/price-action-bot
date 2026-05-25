"""Persistent idempotency store (DuckDB-backed).

Replaces previous in-memory dict. Survives process restart.
Forex client_id prefix: FX_, max length 32 (OANDA/cTrader limit).
"""
from __future__ import annotations

import hashlib
import logging
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import duckdb

logger = logging.getLogger(__name__)
_LOCK = threading.Lock()

CLIENT_ID_PREFIX = "FX_"
MAX_CLIENT_ID_LEN = 32


def signal_fingerprint(pair: str, ts: datetime, side: str, sl: float, strategy: str) -> str:
    """Stable fingerprint, microsecond-stripped, pip-rounded SL."""
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    ts_norm = ts.replace(microsecond=0).isoformat()
    raw = f"{pair}|{ts_norm}|{side}|{round(sl, 5)}|{strategy}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def make_client_order_id(fingerprint: str) -> str:
    return (CLIENT_ID_PREFIX + fingerprint)[:MAX_CLIENT_ID_LEN]


class IdempotencyStore:
    """DuckDB-persistent store. Process-restart safe."""

    def __init__(self, db_path: str | Path = "data/forex/forex_idempotency.duckdb"):
        self.db_path = str(db_path)
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        with duckdb.connect(self.db_path) as con:
            con.execute("""
                CREATE TABLE IF NOT EXISTS forex_order_fingerprints (
                    fingerprint TEXT PRIMARY KEY,
                    ts_first_seen TIMESTAMP,
                    outcome TEXT,
                    detail TEXT
                )
            """)

    def is_seen(self, fp: str) -> bool:
        with duckdb.connect(self.db_path, read_only=True) as con:
            try:
                row = con.execute("SELECT 1 FROM forex_order_fingerprints WHERE fingerprint=?", [fp]).fetchone()
            except duckdb.CatalogException:
                return False
        return row is not None

    def mark(self, fp: str, outcome: str, detail: str = "") -> bool:
        """Returns True if newly inserted, False if already existed."""
        with _LOCK:
            with duckdb.connect(self.db_path) as con:
                try:
                    if con.execute("SELECT 1 FROM forex_order_fingerprints WHERE fingerprint=?", [fp]).fetchone():
                        # update outcome only (e.g. submitted → filled)
                        con.execute(
                            "UPDATE forex_order_fingerprints SET outcome=?, detail=? WHERE fingerprint=?",
                            [outcome, detail, fp],
                        )
                        return False
                    con.execute(
                        "INSERT INTO forex_order_fingerprints VALUES (?,?,?,?)",
                        [fp, datetime.now(timezone.utc), outcome, detail],
                    )
                    return True
                except duckdb.ConstraintException:
                    return False

    def get_outcome(self, fp: str) -> Optional[str]:
        with duckdb.connect(self.db_path, read_only=True) as con:
            try:
                row = con.execute("SELECT outcome FROM forex_order_fingerprints WHERE fingerprint=?", [fp]).fetchone()
            except duckdb.CatalogException:
                return None
        return row[0] if row else None
