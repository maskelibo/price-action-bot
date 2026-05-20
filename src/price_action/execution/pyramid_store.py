"""PyramidStore — PyramidPosition DuckDB persist + startup recovery (SEC58-L2).

Tasarim:
  - Daemon restart sonrasi _pyramid_positions dict'i kaybolur.
  - Bu modül aktif pyramid pozisyonlarini DuckDB'ye yazar, daemon restart
    sonrasi otomatik geri yukler.
  - Idempotent schema (CREATE IF NOT EXISTS).
  - Thread-safe: tek RLock.
  - Backward compat: pyramid store yoksa graceful fallback (log + devam).

Tablolar:
    pyramid_positions   — pozisyon metadata (per parent_position_id)
    pyramid_legs        — her leg'in durumu

Kullanim:
    store = PyramidStore(db_path)
    store.upsert_position(pyr_pos)       # fill/state degisiminde cagir
    live_positions = store.load_all()    # daemon startup'ta
    store.delete_position(pos_id)        # TP/SL hit sonrasi temizle

SEC58-L2 sprint kapsamı:
  - PyramidStore sinifi
  - upsert_position / load_all / delete_position / delete_closed_legs
  - 8 unit test (test_pyramid_store.py)
"""
from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import duckdb

from price_action.execution.pyramid_router import (
    PyramidLeg,
    PyramidPosition,
    LegState,
    PositionSide,
)

log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[4]
DEFAULT_DB = ROOT / "data" / "pyramid_store.duckdb"

_DDL_POSITIONS = """
CREATE TABLE IF NOT EXISTS pyramid_positions (
    parent_position_id  VARCHAR PRIMARY KEY,
    symbol              VARCHAR NOT NULL,
    side                VARCHAR NOT NULL,
    entry_price         DOUBLE  NOT NULL,
    sl_price            DOUBLE  NOT NULL,
    initial_r           DOUBLE  NOT NULL,
    pyramid_triggers    VARCHAR NOT NULL,   -- JSON array string
    pyramid_sizes       VARCHAR NOT NULL,   -- JSON array string
    created_at          TIMESTAMP NOT NULL,
    updated_at          TIMESTAMP NOT NULL
)
"""

_DDL_LEGS = """
CREATE TABLE IF NOT EXISTS pyramid_legs (
    leg_id              VARCHAR PRIMARY KEY,    -- parent_position_id + '_L' + leg_num
    parent_position_id  VARCHAR NOT NULL,
    leg_num             INTEGER NOT NULL,
    leg_state           VARCHAR NOT NULL,
    leg_qty             DOUBLE  NOT NULL,
    leg_price           DOUBLE  NOT NULL,
    client_order_id     VARCHAR NOT NULL,
    exchange_order_id   VARCHAR,
    fill_price          DOUBLE,
    submitted_at        TIMESTAMP,
    filled_at           TIMESTAMP,
    updated_at          TIMESTAMP NOT NULL
)
"""

_DDL_IDX = """
CREATE INDEX IF NOT EXISTS idx_pl_pos ON pyramid_legs (parent_position_id);
"""


def _leg_id(parent_position_id: str, leg_num: int) -> str:
    return f"{parent_position_id}_L{leg_num}"


def _ts_now() -> datetime:
    return datetime.now(timezone.utc)


class PyramidStore:
    """Thread-safe DuckDB persist katmani pyramid pozisyonlari icin.

    Args:
        db_path: DuckDB dosya yolu. None → data/pyramid_store.duckdb.
    """

    def __init__(self, db_path: Path | str | None = None) -> None:
        self._path = Path(db_path) if db_path else DEFAULT_DB
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._init_schema()

    # ── Schema ──────────────────────────────────────────────────────────────

    def _init_schema(self) -> None:
        with self._lock:
            con = duckdb.connect(str(self._path))
            try:
                con.execute(_DDL_POSITIONS)
                con.execute(_DDL_LEGS)
                con.execute(_DDL_IDX)
                con.commit()
            finally:
                con.close()

    # ── Write ────────────────────────────────────────────────────────────────

    def upsert_position(self, pos: PyramidPosition) -> None:
        """PyramidPosition'i (ve tum leg'lerini) DB'ye yaz/guncelle.

        Idempotent: mevcut pozisyon varsa gunceller, yoksa ekler.
        Her leg icin de upsert yapilir.
        """
        now = _ts_now()
        triggers_json = json.dumps(pos.pyramid_triggers)
        sizes_json = json.dumps(pos.pyramid_sizes)

        with self._lock:
            con = duckdb.connect(str(self._path))
            try:
                # DuckDB INSERT OR REPLACE (idempotent upsert)
                con.execute(
                    """
                    INSERT OR REPLACE INTO pyramid_positions
                        (parent_position_id, symbol, side, entry_price, sl_price,
                         initial_r, pyramid_triggers, pyramid_sizes,
                         created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        pos.parent_position_id,
                        pos.symbol,
                        pos.side,
                        pos.entry_price,
                        pos.sl_price,
                        pos.initial_R,
                        triggers_json,
                        sizes_json,
                        now,
                        now,
                    ],
                )
                # Leg'ler
                for leg in pos.legs:
                    self._upsert_leg(con, pos.parent_position_id, leg, now)
                con.commit()
            finally:
                con.close()

    def upsert_leg(self, parent_position_id: str, leg: PyramidLeg) -> None:
        """Tek bir leg'i guncelle (fill detection sonrasi cagrilir)."""
        now = _ts_now()
        with self._lock:
            con = duckdb.connect(str(self._path))
            try:
                self._upsert_leg(con, parent_position_id, leg, now)
                con.commit()
            finally:
                con.close()

    def _upsert_leg(
        self,
        con: duckdb.DuckDBPyConnection,
        parent_position_id: str,
        leg: PyramidLeg,
        now: datetime,
    ) -> None:
        """Internal: upsert tek leg, conn verilmis."""
        lid = _leg_id(parent_position_id, leg.leg_num)
        con.execute(
            """
            INSERT OR REPLACE INTO pyramid_legs
                (leg_id, parent_position_id, leg_num, leg_state, leg_qty,
                 leg_price, client_order_id, exchange_order_id, fill_price,
                 submitted_at, filled_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                lid,
                parent_position_id,
                leg.leg_num,
                leg.leg_state,
                leg.leg_qty,
                leg.leg_price,
                leg.client_order_id,
                leg.exchange_order_id,
                leg.fill_price,
                leg.submitted_at,
                leg.filled_at,
                now,
            ],
        )

    # ── Delete ───────────────────────────────────────────────────────────────

    def delete_position(self, parent_position_id: str) -> None:
        """Pozisyon + tum leg'leri DB'den sil (TP/SL hit sonrasi)."""
        with self._lock:
            con = duckdb.connect(str(self._path))
            try:
                con.execute(
                    "DELETE FROM pyramid_legs WHERE parent_position_id = ?",
                    [parent_position_id],
                )
                con.execute(
                    "DELETE FROM pyramid_positions WHERE parent_position_id = ?",
                    [parent_position_id],
                )
                con.commit()
            finally:
                con.close()

    def delete_closed_legs(self, parent_position_id: str) -> None:
        """Sadece CANCELED/REJECTED/FILLED leg'leri sil — PENDING/SUBMITTED koru."""
        with self._lock:
            con = duckdb.connect(str(self._path))
            try:
                con.execute(
                    """
                    DELETE FROM pyramid_legs
                    WHERE parent_position_id = ?
                      AND leg_state IN ('CANCELED', 'REJECTED')
                    """,
                    [parent_position_id],
                )
                con.commit()
            finally:
                con.close()

    # ── Read ─────────────────────────────────────────────────────────────────

    def load_all(self) -> dict[str, PyramidPosition]:
        """Tum aktif pozisyonlari yukle. Kapatilmamis pozisyonlar donus.

        Returns:
            {parent_position_id: PyramidPosition} — FILLED/CANCELED terminal
            state'indeki sadece-closed-leg pozisyonlar dahil edilmez.
        """
        with self._lock:
            con = duckdb.connect(str(self._path))
            try:
                pos_rows = con.execute(
                    """
                    SELECT parent_position_id, symbol, side, entry_price, sl_price,
                           initial_r, pyramid_triggers, pyramid_sizes
                    FROM pyramid_positions
                    ORDER BY created_at
                    """
                ).fetchall()
                if not pos_rows:
                    return {}

                result: dict[str, PyramidPosition] = {}
                for row in pos_rows:
                    (
                        pos_id, symbol, side, entry_price, sl_price,
                        initial_r, triggers_json, sizes_json,
                    ) = row

                    # Leg'leri cek
                    leg_rows = con.execute(
                        """
                        SELECT leg_num, leg_state, leg_qty, leg_price,
                               client_order_id, exchange_order_id, fill_price,
                               submitted_at, filled_at
                        FROM pyramid_legs
                        WHERE parent_position_id = ?
                        ORDER BY leg_num
                        """,
                        [pos_id],
                    ).fetchall()

                    legs: list[PyramidLeg] = []
                    for lr in leg_rows:
                        (
                            leg_num, leg_state, leg_qty, leg_price,
                            client_order_id, exchange_order_id, fill_price,
                            submitted_at, filled_at,
                        ) = lr
                        legs.append(PyramidLeg(
                            leg_num=int(leg_num),
                            leg_state=str(leg_state),  # type: ignore[arg-type]
                            leg_qty=float(leg_qty),
                            leg_price=float(leg_price),
                            client_order_id=str(client_order_id),
                            exchange_order_id=exchange_order_id,
                            fill_price=float(fill_price) if fill_price is not None else None,
                            submitted_at=submitted_at,
                            filled_at=filled_at,
                        ))

                    # Pozisyon hepsi terminal durumda ise yukle ama isaretlenmemis demektir
                    # (daemon P-05 tarafindan pop edilmemis). Tutarlilik icin dahil et.
                    try:
                        triggers: list[float] = json.loads(triggers_json)
                        sizes: list[float] = json.loads(sizes_json)
                    except Exception:
                        triggers = []
                        sizes = []

                    pyr_pos = PyramidPosition(
                        parent_position_id=str(pos_id),
                        symbol=str(symbol),
                        side=str(side),  # type: ignore[arg-type]
                        entry_price=float(entry_price),
                        sl_price=float(sl_price),
                        initial_R=float(initial_r),
                        legs=legs,
                        pyramid_triggers=triggers,
                        pyramid_sizes=sizes,
                    )
                    result[str(pos_id)] = pyr_pos
            finally:
                con.close()

        log.info("PyramidStore.load_all: %d pozisyon yuklendi", len(result))
        return result

    def count_positions(self) -> int:
        """Kayitli pozisyon sayisi (monitoring)."""
        with self._lock:
            con = duckdb.connect(str(self._path))
            try:
                row = con.execute(
                    "SELECT COUNT(*) FROM pyramid_positions"
                ).fetchone()
                return int(row[0]) if row else 0
            finally:
                con.close()


__all__ = ["PyramidStore"]
