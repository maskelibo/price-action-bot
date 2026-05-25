"""Idempotency store — sinyal parmak izi persist etme ve borsa duplicate önleme.

Design:
  - Signal.fingerprint() → deterministic SHA-256[:16]
  - client_order_id = "PA_" + fingerprint[:16]
  - DuckDB'ye kayıt (process restart'ta da duplicate koruması)
  - Borsa tarafı idem: client_order_id ile oluşturulan emir zaten varsa
    exchange hatası yakalanır, mevcut emir fetch edilir.

Usage:
    store = IdempotencyStore()
    if store.is_seen(fp):
        existing = store.get(fp)
        ...
    store.mark_submitted(fp, client_order_id, symbol)
    store.mark_filled(fp, exchange_order_id)
"""
from __future__ import annotations

import threading
from datetime import datetime, timezone
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[3]  # G24 fix: Price Action kökü (eskiden parents[4]=projeler — proje dışı)
DEFAULT_DB = ROOT / "data" / "idempotency.duckdb"

CLIENT_ID_PREFIX = "PA_"
MAX_CLIENT_ID_LEN = 36  # Binance max clientOrderId


class IdempotencyStore:
    """Thread-safe fingerprint persistence.

    DuckDB single-file, tek-writer model (lock korumalı).
    """

    def __init__(self, db_path: Path | str | None = None) -> None:
        self._path = Path(db_path) if db_path else DEFAULT_DB
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._init_db()

    def _init_db(self) -> None:
        con = duckdb.connect(str(self._path))
        con.execute("""
            CREATE TABLE IF NOT EXISTS order_fingerprints (
                fingerprint VARCHAR PRIMARY KEY,
                client_order_id VARCHAR NOT NULL,
                symbol VARCHAR,
                side VARCHAR,
                created_at TIMESTAMP NOT NULL,
                status VARCHAR NOT NULL,
                exchange_order_id VARCHAR,
                fill_price DOUBLE,
                fill_qty DOUBLE,
                notes VARCHAR
            )
        """)
        con.commit()
        con.close()

    @staticmethod
    def make_client_id(fingerprint: str) -> str:
        """Borsa'ya gönderilecek client_order_id. Deterministic."""
        raw = CLIENT_ID_PREFIX + fingerprint[:16]
        return raw[:MAX_CLIENT_ID_LEN]

    def is_seen(self, fingerprint: str) -> bool:
        """Bu parmak izi daha önce gönderildi mi?"""
        with self._lock:
            con = duckdb.connect(str(self._path))
            row = con.execute(
                "SELECT 1 FROM order_fingerprints WHERE fingerprint = ?",
                [fingerprint],
            ).fetchone()
            con.close()
            return row is not None

    def get(self, fingerprint: str) -> dict | None:
        """Kayıtlı emir bilgisini döndür. Yoksa None."""
        with self._lock:
            con = duckdb.connect(str(self._path))
            row = con.execute(
                """SELECT fingerprint, client_order_id, symbol, side,
                          created_at, status, exchange_order_id, fill_price, fill_qty
                   FROM order_fingerprints WHERE fingerprint = ?""",
                [fingerprint],
            ).fetchone()
            con.close()
        if row is None:
            return None
        keys = ["fingerprint", "client_order_id", "symbol", "side",
                "created_at", "status", "exchange_order_id", "fill_price", "fill_qty"]
        return dict(zip(keys, row))

    def mark_submitted(
        self,
        fingerprint: str,
        symbol: str,
        side: str,
    ) -> str:
        """Yeni emir kaydını oluştur. Status='submitted'. client_order_id döndür."""
        client_id = self.make_client_id(fingerprint)
        with self._lock:
            con = duckdb.connect(str(self._path))
            con.execute(
                """INSERT OR IGNORE INTO order_fingerprints
                   (fingerprint, client_order_id, symbol, side, created_at, status)
                   VALUES (?, ?, ?, ?, ?, 'submitted')""",
                [fingerprint, client_id, symbol, side,
                 datetime.now(timezone.utc)],
            )
            con.commit()
            con.close()
        return client_id

    def mark_filled(
        self,
        fingerprint: str,
        exchange_order_id: str,
        fill_price: float,
        fill_qty: float,
    ) -> None:
        """Fill alındı — kayıt güncelle."""
        with self._lock:
            con = duckdb.connect(str(self._path))
            con.execute(
                """UPDATE order_fingerprints
                   SET status = 'filled',
                       exchange_order_id = ?,
                       fill_price = ?,
                       fill_qty = ?
                   WHERE fingerprint = ?""",
                [exchange_order_id, fill_price, fill_qty, fingerprint],
            )
            con.commit()
            con.close()

    def mark_rejected(self, fingerprint: str, reason: str) -> None:
        """Emir reddedildi."""
        with self._lock:
            con = duckdb.connect(str(self._path))
            con.execute(
                """UPDATE order_fingerprints
                   SET status = 'rejected', notes = ?
                   WHERE fingerprint = ?""",
                [reason[:200], fingerprint],
            )
            con.commit()
            con.close()

    def count_submitted_today(self) -> int:
        """Bugün gönderilen toplam emir sayısı (monitoring)."""
        with self._lock:
            con = duckdb.connect(str(self._path))
            row = con.execute(
                """SELECT COUNT(*) FROM order_fingerprints
                   WHERE created_at::DATE = CURRENT_DATE
                     AND status IN ('submitted', 'filled')"""
            ).fetchone()
            con.close()
        return int(row[0]) if row else 0
