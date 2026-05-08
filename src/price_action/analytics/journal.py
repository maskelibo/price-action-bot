"""Trade journal — Postgres öncelikli, DuckDB fallback'li.

Trade, fill, position, signal kayıtlarını kalıcı tutar. Analyst bu tablolardan
KPI / post-mortem üretir. Postgres yoksa (CI / dev) DuckDB transparently devreye
girer.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
from typing import Any, Iterator

import pandas as pd
from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    Float,
    Integer,
    String,
    create_engine,
    select,
)
from sqlalchemy.engine import Engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from price_action.contracts import Fill, Position, Signal, TradeRecord
from price_action.logging_config import logger
from price_action.settings import get_settings


class Base(DeclarativeBase):
    pass


# =====================================================================
# Tablo tanımları
# =====================================================================

class TradeORM(Base):
    __tablename__ = "trades"

    trade_id = Column(String(64), primary_key=True)
    venue = Column(String(32), nullable=False)
    symbol = Column(String(64), nullable=False, index=True)
    side = Column(String(8), nullable=False)
    entry_ts = Column(DateTime, nullable=False, index=True)
    exit_ts = Column(DateTime, nullable=False, index=True)
    entry_price = Column(Float, nullable=False)
    exit_price = Column(Float, nullable=False)
    quantity = Column(Float, nullable=False)
    realized_pnl_usdt = Column(Float, nullable=False)
    realized_r_multiple = Column(Float, nullable=False)
    fees_usdt = Column(Float, nullable=False)
    slippage_bps = Column(Float, nullable=False)
    strategy_id = Column(String(64), nullable=False, index=True)
    pattern_id = Column(String(64), nullable=False, index=True)
    confluence_score = Column(Float, nullable=False)
    initial_sl = Column(Float, nullable=False)
    initial_tp = Column(Float, nullable=False)
    mae_pct = Column(Float, nullable=False)
    mfe_pct = Column(Float, nullable=False)
    classification = Column(String(32), nullable=True)
    notes = Column(String, nullable=True)
    manifest_hash = Column(String(64), nullable=False, default="")


class FillORM(Base):
    __tablename__ = "fills"

    id = Column(Integer, primary_key=True, autoincrement=True)
    order_id = Column(String(64), nullable=False, index=True)
    venue = Column(String(32), nullable=False)
    symbol = Column(String(64), nullable=False, index=True)
    side = Column(String(8), nullable=False)
    price = Column(Float, nullable=False)
    quantity = Column(Float, nullable=False)
    fee_usdt = Column(Float, nullable=False)
    fee_currency = Column(String(16), nullable=False, default="USDT")
    timestamp = Column(DateTime, nullable=False, index=True)
    is_maker = Column(Boolean, nullable=False)
    expected_price = Column(Float, nullable=False)
    slippage_bps = Column(Float, nullable=False)
    mode = Column(String(16), nullable=False)
    manifest_hash = Column(String(64), nullable=False, default="")


class PositionORM(Base):
    __tablename__ = "positions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    venue = Column(String(32), nullable=False)
    symbol = Column(String(64), nullable=False, index=True)
    side = Column(String(8), nullable=False)
    quantity = Column(Float, nullable=False)
    entry_price = Column(Float, nullable=False)
    current_price = Column(Float, nullable=False)
    unrealized_pnl_usdt = Column(Float, nullable=False)
    realized_pnl_usdt = Column(Float, nullable=False)
    sl_price = Column(Float, nullable=True)
    tp_price = Column(Float, nullable=True)
    opened_at = Column(DateTime, nullable=False)
    strategy_id = Column(String(64), nullable=False, index=True)
    last_updated = Column(DateTime, nullable=False)


class SignalORM(Base):
    __tablename__ = "signals"

    id = Column(Integer, primary_key=True, autoincrement=True)
    fingerprint = Column(String(32), nullable=False, unique=True, index=True)
    ts = Column(DateTime, nullable=False, index=True)
    venue = Column(String(32), nullable=False)
    symbol = Column(String(64), nullable=False, index=True)
    timeframe = Column(String(8), nullable=False)
    direction = Column(String(8), nullable=False)
    pattern_id = Column(String(64), nullable=False)
    confluence_score = Column(Float, nullable=False)
    sl_price = Column(Float, nullable=False)
    tp_price = Column(Float, nullable=False)
    suggested_size_atr = Column(Float, nullable=False)
    metadata_json = Column(JSON, nullable=True)
    manifest_hash = Column(String(64), nullable=False, default="")


# =====================================================================
# Journal facade
# =====================================================================

class Journal:
    """Postgres öncelikli, DuckDB fallback'li trade journal.

    `db_url` parametresi verilirse onu kullanır; aksi halde Postgres'i dener,
    bağlanamazsa DuckDB SQLAlchemy URL'sine geçer.
    """

    def __init__(self, db_url: str | None = None, *, force_duckdb: bool = False) -> None:
        settings = get_settings()
        self._explicit_url = db_url
        self._force_duckdb = force_duckdb
        self.engine: Engine = self._make_engine()
        self.SessionLocal = sessionmaker(bind=self.engine, autoflush=False, expire_on_commit=False)
        Base.metadata.create_all(self.engine)
        logger.info("journal.ready", extra={"backend": str(self.engine.url.drivername)})
        # idle suppress
        _ = settings  # backwards compat reference

    # -----------------------------------------------------------------
    # Engine / session
    # -----------------------------------------------------------------

    def _make_engine(self) -> Engine:
        settings = get_settings()
        if self._explicit_url:
            return create_engine(self._explicit_url, future=True)
        if self._force_duckdb:
            return self._make_duckdb_engine()
        # Try postgres first
        try:
            url = settings.postgres_dsn.replace("postgresql://", "postgresql+psycopg://")
            engine = create_engine(url, pool_pre_ping=True, future=True)
            with engine.connect():
                pass
            return engine
        except Exception as exc:  # pragma: no cover - environment dependent
            logger.warning(
                "journal.postgres_unavailable_fallback_duckdb",
                extra={"err": str(exc)[:200]},
            )
            return self._make_duckdb_engine()

    def _make_duckdb_engine(self) -> Engine:
        settings = get_settings()
        path = settings.duckdb_path
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            return create_engine(f"duckdb:///{path}", future=True)
        except Exception:  # pragma: no cover
            # duckdb_engine yüklü değilse SQLite'a düş
            sqlite_path = path.with_suffix(".sqlite")
            return create_engine(f"sqlite:///{sqlite_path}", future=True)

    @contextmanager
    def session(self) -> Iterator[Session]:
        sess = self.SessionLocal()
        try:
            yield sess
            sess.commit()
        except Exception:
            sess.rollback()
            raise
        finally:
            sess.close()

    # -----------------------------------------------------------------
    # Yazma yolu
    # -----------------------------------------------------------------

    def record_trade(self, trade: TradeRecord) -> None:
        row = TradeORM(
            trade_id=trade.trade_id,
            venue=trade.venue,
            symbol=trade.symbol,
            side=trade.side,
            entry_ts=trade.entry_ts,
            exit_ts=trade.exit_ts,
            entry_price=trade.entry_price,
            exit_price=trade.exit_price,
            quantity=trade.quantity,
            realized_pnl_usdt=trade.realized_pnl_usdt,
            realized_r_multiple=trade.realized_r_multiple,
            fees_usdt=trade.fees_usdt,
            slippage_bps=trade.slippage_bps,
            strategy_id=trade.strategy_id,
            pattern_id=trade.pattern_id,
            confluence_score=trade.confluence_score,
            initial_sl=trade.initial_sl,
            initial_tp=trade.initial_tp,
            mae_pct=trade.mae_pct,
            mfe_pct=trade.mfe_pct,
            classification=trade.classification,
            notes=trade.notes,
            manifest_hash=trade.manifest_hash,
        )
        with self.session() as sess:
            sess.merge(row)
        logger.info("journal.trade_recorded", extra={"trade_id": trade.trade_id})

    def record_fill(self, fill: Fill) -> None:
        row = FillORM(
            order_id=fill.order_id,
            venue=fill.venue,
            symbol=fill.symbol,
            side=fill.side,
            price=fill.price,
            quantity=fill.quantity,
            fee_usdt=fill.fee_usdt,
            fee_currency=fill.fee_currency,
            timestamp=fill.timestamp,
            is_maker=fill.is_maker,
            expected_price=fill.expected_price,
            slippage_bps=fill.slippage_bps,
            mode=fill.mode,
            manifest_hash=fill.manifest_hash,
        )
        with self.session() as sess:
            sess.add(row)

    def record_signal(self, signal: Signal) -> None:
        row = SignalORM(
            fingerprint=signal.fingerprint(),
            ts=signal.ts,
            venue=signal.venue,
            symbol=signal.symbol,
            timeframe=signal.timeframe,
            direction=signal.direction,
            pattern_id=signal.pattern_id,
            confluence_score=signal.confluence_score,
            sl_price=signal.sl_price,
            tp_price=signal.tp_price,
            suggested_size_atr=signal.suggested_size_atr,
            metadata_json=signal.metadata,
            manifest_hash=signal.manifest_hash,
        )
        try:
            with self.session() as sess:
                sess.add(row)
        except Exception as exc:  # idempotent on fingerprint conflict
            logger.warning("journal.signal_dup_skipped", extra={"err": str(exc)[:120]})

    def upsert_position(self, position: Position) -> None:
        with self.session() as sess:
            existing = (
                sess.query(PositionORM)
                .filter_by(venue=position.venue, symbol=position.symbol, strategy_id=position.strategy_id)
                .first()
            )
            if existing:
                existing.side = position.side
                existing.quantity = position.quantity
                existing.entry_price = position.entry_price
                existing.current_price = position.current_price
                existing.unrealized_pnl_usdt = position.unrealized_pnl_usdt
                existing.realized_pnl_usdt = position.realized_pnl_usdt
                existing.sl_price = position.sl_price
                existing.tp_price = position.tp_price
                existing.last_updated = position.last_updated
            else:
                sess.add(
                    PositionORM(
                        venue=position.venue,
                        symbol=position.symbol,
                        side=position.side,
                        quantity=position.quantity,
                        entry_price=position.entry_price,
                        current_price=position.current_price,
                        unrealized_pnl_usdt=position.unrealized_pnl_usdt,
                        realized_pnl_usdt=position.realized_pnl_usdt,
                        sl_price=position.sl_price,
                        tp_price=position.tp_price,
                        opened_at=position.opened_at,
                        strategy_id=position.strategy_id,
                        last_updated=position.last_updated,
                    )
                )

    # -----------------------------------------------------------------
    # Okuma yolu
    # -----------------------------------------------------------------

    def query_trades(
        self,
        filters: dict[str, Any] | None = None,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
        limit: int | None = None,
    ) -> pd.DataFrame:
        filters = filters or {}
        with self.session() as sess:
            stmt = select(TradeORM)
            for col, val in filters.items():
                if hasattr(TradeORM, col):
                    stmt = stmt.where(getattr(TradeORM, col) == val)
            if start is not None:
                stmt = stmt.where(TradeORM.exit_ts >= start)
            if end is not None:
                stmt = stmt.where(TradeORM.exit_ts <= end)
            stmt = stmt.order_by(TradeORM.exit_ts.desc())
            if limit is not None:
                stmt = stmt.limit(limit)
            rows = sess.execute(stmt).scalars().all()
        return _orm_rows_to_df(rows, TradeORM)

    def query_fills(self, *, limit: int | None = None) -> pd.DataFrame:
        with self.session() as sess:
            stmt = select(FillORM).order_by(FillORM.timestamp.desc())
            if limit is not None:
                stmt = stmt.limit(limit)
            rows = sess.execute(stmt).scalars().all()
        return _orm_rows_to_df(rows, FillORM)

    def query_open_positions(self) -> pd.DataFrame:
        with self.session() as sess:
            stmt = select(PositionORM).where(PositionORM.quantity != 0)
            rows = sess.execute(stmt).scalars().all()
        return _orm_rows_to_df(rows, PositionORM)

    def query_pending_signals(self, limit: int = 50) -> pd.DataFrame:
        with self.session() as sess:
            stmt = select(SignalORM).order_by(SignalORM.ts.desc()).limit(limit)
            rows = sess.execute(stmt).scalars().all()
        return _orm_rows_to_df(rows, SignalORM)

    # -----------------------------------------------------------------
    # Util
    # -----------------------------------------------------------------

    def healthcheck(self) -> bool:
        try:
            with self.engine.connect():
                return True
        except OperationalError:
            return False


def _orm_rows_to_df(rows: list, orm_cls: type) -> pd.DataFrame:
    if not rows:
        cols = [c.name for c in orm_cls.__table__.columns]
        return pd.DataFrame(columns=cols)
    records = []
    for r in rows:
        rec = {c.name: getattr(r, c.name) for c in orm_cls.__table__.columns}
        records.append(rec)
    return pd.DataFrame.from_records(records)
