"""DuckDB + Parquet OHLCV katmanı.

Tablolar:
    ohlcv(venue, symbol, timeframe, ts, open, high, low, close, volume)

Parquet partitioning:
    data/parquet/{venue}/{symbol}/{tf}/year=YYYY/month=MM/data.parquet

Tüm zamanlar UTC, tz-aware.
"""
from __future__ import annotations

import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

import duckdb
import pandas as pd

from price_action.logging_config import logger
from price_action.settings import get_settings


# =====================================================================
# Connection pool — Windows DuckDB lock-safety
# =====================================================================
# DuckDB on Windows occasionally throws InternalException with parametrized
# queries when multiple processes/threads open and close connections rapidly
# against the same file. We mitigate by maintaining a per-path singleton
# connection guarded by an RLock; all reads/writes serialize through it.

_CONN_POOL: dict[str, duckdb.DuckDBPyConnection] = {}
_CONN_LOCKS: dict[str, threading.RLock] = {}
_POOL_GUARD = threading.Lock()


def _get_pooled_connection(path: str) -> tuple[duckdb.DuckDBPyConnection, threading.RLock]:
    """Pooled connection. PA_DUCKDB_READ_ONLY=true ise read_only modunda aç.

    Faz 5.2 fix: 5m bot 15m bot ile aynı market.duckdb'yi okuyor; DuckDB
    exclusive lock conflict yaşıyor. PA_DUCKDB_READ_ONLY=true scan-only
    bot'lar (5m) için — birden fazla process aynı anda RO açabilir.
    """
    import os as _os
    read_only = _os.environ.get("PA_DUCKDB_READ_ONLY", "").lower() in ("1", "true", "yes")
    with _POOL_GUARD:
        if path not in _CONN_POOL:
            if read_only:
                _CONN_POOL[path] = duckdb.connect(path, read_only=True)
            else:
                _CONN_POOL[path] = duckdb.connect(path)
            _CONN_LOCKS[path] = threading.RLock()
        return _CONN_POOL[path], _CONN_LOCKS[path]


def reset_store_pool() -> None:
    """Test fixture'larında kullanılır — pooled bağlantıları kapat."""
    with _POOL_GUARD:
        for con in list(_CONN_POOL.values()):
            try:
                con.close()
            except Exception:  # pragma: no cover
                pass
        _CONN_POOL.clear()
        _CONN_LOCKS.clear()

OHLCV_COLUMNS: tuple[str, ...] = (
    "venue",
    "symbol",
    "timeframe",
    "ts",
    "open",
    "high",
    "low",
    "close",
    "volume",
)

_OHLCV_DDL = """
CREATE TABLE IF NOT EXISTS ohlcv (
    venue       VARCHAR NOT NULL,
    symbol      VARCHAR NOT NULL,
    timeframe   VARCHAR NOT NULL,
    ts          TIMESTAMP WITH TIME ZONE NOT NULL,
    open        DOUBLE,
    high        DOUBLE,
    low         DOUBLE,
    close       DOUBLE,
    volume      DOUBLE,
    PRIMARY KEY (venue, symbol, timeframe, ts)
);
"""

_INSTRUMENTS_DDL = """
CREATE TABLE IF NOT EXISTS instruments (
    venue           VARCHAR NOT NULL,
    symbol          VARCHAR NOT NULL,
    market_type     VARCHAR NOT NULL,
    base            VARCHAR,
    quote           VARCHAR,
    listing_date    TIMESTAMP WITH TIME ZONE,
    delisting_date  TIMESTAMP WITH TIME ZONE,
    tick_size       DOUBLE,
    lot_step        DOUBLE,
    min_notional_usdt DOUBLE,
    is_active       BOOLEAN DEFAULT TRUE,
    PRIMARY KEY (venue, symbol, market_type)
);
"""


def _ensure_utc(df: pd.DataFrame, col: str = "ts") -> pd.DataFrame:
    """`ts` kolonunu tz-aware UTC'ye çevirir."""
    if col not in df.columns:
        return df
    s = df[col]
    if not pd.api.types.is_datetime64_any_dtype(s):
        s = pd.to_datetime(s, utc=True, errors="coerce")
    elif s.dt.tz is None:
        s = s.dt.tz_localize("UTC")
    else:
        s = s.dt.tz_convert("UTC")
    df = df.copy()
    df[col] = s
    return df


class OHLCVStore:
    """DuckDB + Parquet ikili katman."""

    def __init__(
        self,
        duckdb_path: Path | None = None,
        parquet_root: Path | None = None,
    ) -> None:
        s = get_settings()
        self.duckdb_path: Path = Path(duckdb_path) if duckdb_path else s.duckdb_path
        self.parquet_root: Path = Path(parquet_root) if parquet_root else s.parquet_root
        self.duckdb_path.parent.mkdir(parents=True, exist_ok=True)
        self.parquet_root.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()

    # ----- Schema ----------------------------------------------------
    @contextmanager
    def _conn(self) -> Iterator[duckdb.DuckDBPyConnection]:
        """Pooled, mutex-guarded DuckDB connection.

        Windows DuckDB internal-error tuzağı: aynı path için her çağrıda yeni
        connection açıp kapatmak corruption üretebilir. Bunun yerine path
        başına tek bir pooled connection tutuyoruz, RLock ile serialize
        ediyoruz. ``with self._conn() as con:`` API'si değişmiyor, sadece
        altında havuz çalışıyor.
        """
        path = str(self.duckdb_path)
        con, lock = _get_pooled_connection(path)
        with lock:
            yield con

    def _ensure_schema(self) -> None:
        # Faz 5.2: read_only mode'da DDL çalıştırma — schema zaten var varsayılır
        import os as _os
        if _os.environ.get("PA_DUCKDB_READ_ONLY", "").lower() in ("1", "true", "yes"):
            return
        with self._conn() as con:
            con.execute(_OHLCV_DDL)
            con.execute(_INSTRUMENTS_DDL)
            con.execute(
                "CREATE INDEX IF NOT EXISTS idx_ohlcv_lookup "
                "ON ohlcv (venue, symbol, timeframe, ts);"
            )

    # ----- Read ------------------------------------------------------
    def read(
        self,
        symbol: str,
        tf: str,
        start: datetime | None = None,
        end: datetime | None = None,
        venue: str | None = None,
    ) -> pd.DataFrame:
        """OHLCV oku. ts ascending sıralı.

        Params:
            symbol: "BTC/USDT" gibi
            tf: "1d" / "1w"
            start, end: tz-aware datetime (UTC); None ise sınırsız.
            venue: belirtilmezse tüm venue'ler.
        """
        clauses = ["symbol = ?", "timeframe = ?"]
        params: list[Any] = [symbol, tf]
        if venue is not None:
            clauses.append("venue = ?")
            params.append(venue)
        if start is not None:
            clauses.append("ts >= ?")
            params.append(start)
        if end is not None:
            clauses.append("ts <= ?")
            params.append(end)
        where = " AND ".join(clauses)
        sql = (
            f"SELECT venue, symbol, timeframe, ts, open, high, low, close, volume "
            f"FROM ohlcv WHERE {where} ORDER BY ts ASC"
        )
        with self._conn() as con:
            df = con.execute(sql, params).fetchdf()
        if df.empty:
            return df
        df = _ensure_utc(df, "ts")
        return df

    # ----- Write / upsert -------------------------------------------
    def write(self, df: pd.DataFrame, *, also_parquet: bool = True) -> int:
        """Truncate-write (delete-then-insert) — upsert ile aynı semantiğe yakın.

        Geriye yazılan satır sayısını döner.
        """
        return self.upsert(df, also_parquet=also_parquet)

    def upsert(self, df: pd.DataFrame, *, also_parquet: bool = True) -> int:
        """OHLCV satırlarını idempotent şekilde yaz.

        Aynı (venue, symbol, timeframe, ts) varsa silip yeniden ekler.
        """
        if df is None or df.empty:
            return 0
        missing = [c for c in OHLCV_COLUMNS if c not in df.columns]
        if missing:
            raise ValueError(f"OHLCV df eksik kolon(lar): {missing}")
        df = df[list(OHLCV_COLUMNS)].copy()
        df = _ensure_utc(df, "ts")
        # OHLC sayısal koruması
        for col in ("open", "high", "low", "close", "volume"):
            df[col] = pd.to_numeric(df[col], errors="coerce")
        # Dedup: aynı PK'yi son kayıtla bırak
        df = df.drop_duplicates(subset=["venue", "symbol", "timeframe", "ts"], keep="last")

        with self._conn() as con:
            con.register("staging_df", df)
            con.execute("BEGIN")
            try:
                con.execute(
                    """
                    DELETE FROM ohlcv
                    USING staging_df s
                    WHERE ohlcv.venue = s.venue
                      AND ohlcv.symbol = s.symbol
                      AND ohlcv.timeframe = s.timeframe
                      AND ohlcv.ts = s.ts;
                    """
                )
                con.execute(
                    "INSERT INTO ohlcv (venue, symbol, timeframe, ts, open, high, low, close, volume) "
                    "SELECT venue, symbol, timeframe, ts, open, high, low, close, volume FROM staging_df;"
                )
                con.execute("COMMIT")
            except Exception:
                con.execute("ROLLBACK")
                raise
            finally:
                con.unregister("staging_df")

        if also_parquet:
            self._write_parquet(df)
        logger.bind(rows=len(df), op="upsert").info("ohlcv.upsert")
        return len(df)

    # ----- Parquet partition ----------------------------------------
    def _partition_dir(self, venue: str, symbol: str, tf: str, year: int, month: int) -> Path:
        sym_safe = symbol.replace("/", "_")
        return (
            self.parquet_root
            / venue
            / sym_safe
            / tf
            / f"year={year:04d}"
            / f"month={month:02d}"
        )

    def _write_parquet(self, df: pd.DataFrame) -> None:
        if df.empty:
            return
        df = df.copy()
        df["_year"] = df["ts"].dt.year
        df["_month"] = df["ts"].dt.month
        for (venue, sym, tf, yr, mo), part in df.groupby(
            ["venue", "symbol", "timeframe", "_year", "_month"], sort=False
        ):
            out_dir = self._partition_dir(venue, sym, tf, int(yr), int(mo))
            out_dir.mkdir(parents=True, exist_ok=True)
            file_path = out_dir / "data.parquet"
            keep = list(OHLCV_COLUMNS)
            existing: pd.DataFrame | None = None
            if file_path.exists():
                try:
                    existing = pd.read_parquet(file_path)
                    existing = _ensure_utc(existing, "ts")
                except Exception as exc:  # pragma: no cover - defensive
                    logger.bind(path=str(file_path), err=str(exc)).warning("parquet.read_fail")
                    existing = None
            new_part = part[keep]
            if existing is not None and not existing.empty:
                merged = pd.concat([existing, new_part], ignore_index=True)
                merged = merged.drop_duplicates(
                    subset=["venue", "symbol", "timeframe", "ts"], keep="last"
                )
                merged = merged.sort_values("ts")
            else:
                merged = new_part.sort_values("ts")
            merged.to_parquet(file_path, index=False)

    # ----- Instruments table ----------------------------------------
    def upsert_instruments(self, rows: list[dict[str, Any]]) -> int:
        if not rows:
            return 0
        df = pd.DataFrame(rows)
        for tcol in ("listing_date", "delisting_date"):
            if tcol in df.columns:
                df = _ensure_utc(df, tcol)
        with self._conn() as con:
            con.register("inst_df", df)
            con.execute("BEGIN")
            try:
                con.execute(
                    """
                    DELETE FROM instruments
                    USING inst_df s
                    WHERE instruments.venue = s.venue
                      AND instruments.symbol = s.symbol
                      AND instruments.market_type = s.market_type;
                    """
                )
                con.execute("INSERT INTO instruments SELECT * FROM inst_df;")
                con.execute("COMMIT")
            except Exception:
                con.execute("ROLLBACK")
                raise
            finally:
                con.unregister("inst_df")
        return len(df)

    # ----- Convenience ----------------------------------------------
    def last_ts(self, venue: str, symbol: str, tf: str) -> datetime | None:
        try:
            with self._conn() as con:
                row = con.execute(
                    "SELECT MAX(ts) FROM ohlcv WHERE venue=? AND symbol=? AND timeframe=?",
                    [venue, symbol, tf],
                ).fetchone()
        except Exception as exc:
            # DuckDB on Windows occasionally raises an internal assertion on
            # parameterized SELECT MAX over a freshly-opened DB. Fall back to
            # "no prior data" so the caller refetches full history rather than
            # crashing the whole ingest. The duplicate-key path on upsert
            # protects against double inserts.
            logger.warning(
                "store.last_ts_fallback",
                extra={"venue": venue, "symbol": symbol, "tf": tf, "err": str(exc)[:200]},
            )
            return None
        if row is None or row[0] is None:
            return None
        ts = row[0]
        if isinstance(ts, datetime) and ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return ts

    def symbols(self, venue: str | None = None, tf: str | None = None) -> list[str]:
        clauses = []
        params: list[Any] = []
        if venue:
            clauses.append("venue = ?")
            params.append(venue)
        if tf:
            clauses.append("timeframe = ?")
            params.append(tf)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        sql = f"SELECT DISTINCT symbol FROM ohlcv {where} ORDER BY symbol"
        with self._conn() as con:
            return [r[0] for r in con.execute(sql, params).fetchall()]
