"""DuckDB + Parquet OHLCV katmanı.

Tablolar:
    ohlcv(venue, symbol, timeframe, ts, open, high, low, close, volume)

Parquet partitioning:
    data/parquet/{venue}/{symbol}/{tf}/year=YYYY/month=MM/data.parquet

Tüm zamanlar UTC, tz-aware.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

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

_CONN_POOL: dict[str, list[duckdb.DuckDBPyConnection]] = {}
_CONN_LOCKS: dict[str, list[threading.RLock]] = {}
_POOL_RR_INDEX: dict[str, int] = {}  # round-robin counter
_POOL_GUARD = threading.Lock()

# FIX 2026-06-02 (PROD-INCIDENT): Poisoned-handle detection strings.
# DuckDB "Invalid bitmask for FixedSizeAllocator" is a fatal internal allocator
# error triggered by concurrent writers to the same file (CEO run_hourly +
# launchd ingest15m both write market_ingest.duckdb at the same second). Once
# this error fires, DuckDB marks the entire connection handle as permanently
# invalidated — every subsequent call raises "database has been invalidated...
# must be restarted". The module-level pool holds this dead handle for the rest
# of the process lifetime, so every hourly run_hourly call keeps failing.
# Fix: detect the invalidation strings in _conn() and evict + reconnect.
_INVALIDATED_MARKERS: tuple[str, ...] = (
    "has been invalidated because of a previous fatal error",
    "Invalid bitmask for FixedSizeAllocator",
    "database must be restarted",
)


def _connect_write_with_retry(
    path: str,
    *,
    max_wait_s: float = 45.0,
) -> duckdb.DuckDBPyConnection:
    """Write-mode connect with bounded retry on cross-process lock conflict.

    FIX 2026-05-30: market_ingest.duckdb birden çok yazıcı process'e açık
    (CEO run_hourly + launchd ingest15m (5dk) + snapshot). DuckDB single-writer
    olduğu için biri lock'u tutarken diğeri "Conflicting lock is held in ...
    by user" IOException atıyordu → ingest15m exit 1. Burada bounded
    exponential backoff ile bekleriz; lock kısa süreli (saatlik ingest ~65s,
    snapshot ~1s) olduğundan retry penceresi yeterli. Kalıcı çakışmada
    (deadlock/zombie) yine atar — sessiz veri kaybı yok.
    """
    import time as _time

    deadline = _time.monotonic() + max_wait_s
    delay = 0.5
    last_exc: Exception | None = None
    while True:
        try:
            return duckdb.connect(path)
        except Exception as exc:
            msg = str(exc)
            if "Conflicting lock" not in msg and "Could not set lock" not in msg:
                raise  # farklı bir hata — retry etme
            last_exc = exc
            if _time.monotonic() >= deadline:
                logger.warning(
                    "store.write_lock_retry_exhausted",
                    extra={"path": path, "waited_s": round(max_wait_s, 1)},
                )
                raise
            _time.sleep(delay)
            delay = min(delay * 1.6, 5.0)
    # unreachable
    if last_exc:  # pragma: no cover
        raise last_exc


def close_pool_for_path(path: str) -> None:
    """Belirli bir path'in pooled bağlantılarını kapat → cross-process lock bırak.

    FIX 2026-05-30: CEO (uzun-ömürlü) run_hourly market_ingest.duckdb'yi
    force_write açınca pooled conn process ömrü boyunca lock'u TUTUYORDU →
    ingest15m (5dk) hiç yazamıyordu. run_hourly/snapshot bitince bu path'i
    kapatarak lock'u serbest bırakırız; bir sonraki erişimde lazily yeniden açılır.
    """
    with _POOL_GUARD:
        conns = _CONN_POOL.pop(path, [])
        _CONN_LOCKS.pop(path, None)
        _POOL_RR_INDEX.pop(path, None)
    for con in conns:
        try:
            con.close()
        except Exception as _cl_err:  # pragma: no cover
            # log-only: pooled close fail → olası writer-lock leak artık görünür
            logger.warning("store.pool_close_fail", extra={"path": path, "err": str(_cl_err)[:120]})


def _get_pooled_connection(
    path: str, *, force_write: bool = False
) -> tuple[duckdb.DuckDBPyConnection, threading.RLock]:
    """Pooled connection. PA_DUCKDB_READ_ONLY=true ise read_only modunda aç.

    Faz 5.2 fix: 5m bot 15m bot ile aynı market.duckdb'yi okuyor; DuckDB
    exclusive lock conflict yaşıyor. PA_DUCKDB_READ_ONLY=true scan-only
    bot'lar (5m) için — birden fazla process aynı anda RO açabilir.

    FIX 2026-05-28 (audit-A6): Read-only modda pool size > 1 destek (default 4).
    Önceki bug: 8-thread signal scan tek conn + RLock üzerinden seri çalışıyordu;
    paralelizmin faydası yoktu (scan latency 6-8s). Read-only modda DuckDB
    aynı dosyaya birden fazla conn açabiliyor → gerçek concurrent read.
    Write modda exclusive lock zorunlu, pool size=1 zorlanıyor.
    PA_DUCKDB_POOL_SIZE env ile override edilebilir; Windows'ta 1'e zorla
    (DuckDB Windows-specific lock issue'leri için defensive).

    FIX 2026-05-28 (depo-ayirma): ``force_write=True`` → PA_DUCKDB_READ_ONLY
    env'i YOK SAYILIR ve bu path write mode (pool_size=1) açılır. Bu, CEO
    daemon (read-only env) içinde çalışan ingest job'ının ayrı bir yazılabilir
    dosyaya (market_ingest.duckdb) yazabilmesi için. force_write=False (default)
    davranışı BYTE-IDENTICAL — geriye dönük uyum kritik. force_write'lı path'ler
    ayrı dosya olduğundan, aynı path'in hem RO hem write pool'da olması mümkün
    değil (path başına tek pool entry; market_ingest.duckdb sadece force_write
    ile açılır).
    """
    import os as _os
    import platform as _platform

    if force_write:
        read_only = False
    else:
        read_only = _os.environ.get("PA_DUCKDB_READ_ONLY", "").lower() in ("1", "true", "yes")
    # Pool size: write mode → 1 zorunlu, read mode → env (default 4)
    if not read_only:
        pool_size = 1
    elif _platform.system() == "Windows":
        pool_size = 1  # Windows DuckDB lock semantics gevşek; defensive
    else:
        try:
            pool_size = max(1, int(_os.environ.get("PA_DUCKDB_POOL_SIZE", "4")))
        except ValueError:
            pool_size = 4

    with _POOL_GUARD:
        if path not in _CONN_POOL:
            conns: list[duckdb.DuckDBPyConnection] = []
            locks: list[threading.RLock] = []
            for _ in range(pool_size):
                if read_only:
                    conns.append(duckdb.connect(path, read_only=True))
                else:
                    # FIX 2026-05-30: write-mode cross-process lock retry.
                    # market_ingest.duckdb'ye birden fazla process yazar
                    # (CEO run_hourly + launchd ingest15m + snapshot). DuckDB
                    # single-writer → çakışan process lock "Conflicting lock"
                    # IOException atıp ingest15m'i exit 1 ediyordu. Bounded
                    # retry+backoff: kısa contention'ı bekle, kalıcıysa yine at.
                    conns.append(_connect_write_with_retry(path))
                locks.append(threading.RLock())
            _CONN_POOL[path] = conns
            _CONN_LOCKS[path] = locks
            _POOL_RR_INDEX[path] = 0
        # Round-robin pick
        idx = _POOL_RR_INDEX[path] % len(_CONN_POOL[path])
        _POOL_RR_INDEX[path] = (idx + 1) % len(_CONN_POOL[path])
        return _CONN_POOL[path][idx], _CONN_LOCKS[path][idx]


def reset_store_pool() -> None:
    """Test fixture'larında kullanılır — pooled bağlantıları kapat."""
    with _POOL_GUARD:
        for conns in list(_CONN_POOL.values()):
            for con in conns:
                with suppress(Exception):  # pragma: no cover
                    con.close()
        _CONN_POOL.clear()
        _CONN_LOCKS.clear()
        _POOL_RR_INDEX.clear()


def exec_with_checkpoint(
    con: duckdb.DuckDBPyConnection,
    sql: str,
    params: list | tuple | None = None,
) -> None:
    """FIX 2026-05-28 (audit-F4): merkezi WAL-safe write wrapper.

    `con.execute(sql, params)` çağrısı sonrası `CHECKPOINT` çağırır.
    Önceki bug: CHECKPOINT sadece `ohlcv.upsert()` (A5 fix) eklenmişti;
    idempotency.mark, pyramid_store.upsert, slippage_tracker.record_fill,
    futures_trades_closed INSERT vb. çağrılar WAL büyümesine + hard kill
    sonrası replay riskine açıktı. Bu wrapper merkezi koruma sağlar.

    Kullanım:
        with store._conn() as con:
            exec_with_checkpoint(con, "INSERT INTO foo VALUES (?)", [42])

    Maliyet: her checkpoint ~5-50ms (DuckDB doc), kabul edilebilir.
    Read-only conn'da no-op (CHECKPOINT zaten geçersiz olur, try-swallow).
    """
    if params is None:
        con.execute(sql)
    else:
        con.execute(sql, params)
    # Read-only mode veya tx open ise CHECKPOINT fail eder — kabul (benign)
    with suppress(Exception):
        con.execute("CHECKPOINT")


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
        *,
        path: Path | None = None,
        force_write: bool = False,
    ) -> None:
        """OHLCV store.

        Params:
            duckdb_path: (geriye dönük) DuckDB dosya yolu.
            path: ``duckdb_path`` için alias (depo-ayirma fix'i ile eklendi).
                  İkisi de verilirse ``path`` öncelik alır.
            force_write: True ise PA_DUCKDB_READ_ONLY env'i YOK SAYILIR ve
                  bağlantı write mode (exclusive, pool_size=1) açılır. CEO
                  daemon (read-only env) içindeki ingest job'ının
                  market_ingest.duckdb'ye yazabilmesi için. Default False →
                  mevcut davranış byte-identical.
        """
        s = get_settings()
        chosen = path if path is not None else duckdb_path
        self.duckdb_path: Path = Path(chosen) if chosen else s.duckdb_path
        self.parquet_root: Path = Path(parquet_root) if parquet_root else s.parquet_root
        self.force_write: bool = force_write
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

        FIX 2026-06-02 (PROD-INCIDENT): Poisoned-handle reconnect.
        Concurrent writers (CEO run_hourly + launchd ingest15m) to the same
        market_ingest.duckdb file can trigger DuckDB's internal
        "Invalid bitmask for FixedSizeAllocator" fatal error. DuckDB then
        permanently invalidates the connection handle: every subsequent call
        raises "database has been invalidated... must be restarted". Because
        the pool keeps that dead handle forever, all hourly ingest calls fail
        for the rest of the process lifetime. Fix: on any exception whose
        message contains an invalidation marker, evict the pool entry for this
        path (close the dead handle) and retry with a fresh connection once.
        The retry is still guarded by the per-path RLock so write-mode
        serialization is preserved.
        """
        path = str(self.duckdb_path)
        con, lock = _get_pooled_connection(path, force_write=self.force_write)
        with lock:
            try:
                yield con
            except Exception as exc:
                msg = str(exc)
                if any(marker in msg for marker in _INVALIDATED_MARKERS):
                    # Dead handle — evict the pool entry so the next caller
                    # gets a fresh connection. Log loudly; do NOT silently swallow.
                    logger.warning(
                        "store.conn_invalidated_evict",
                        extra={"path": path, "err": msg[:300]},
                    )
                    close_pool_for_path(path)
                raise  # always re-raise — caller decides retry policy

    def _ensure_schema(self) -> None:
        # Faz 5.2: read_only mode'da DDL çalıştırma — schema zaten var varsayılır.
        # depo-ayirma fix: force_write=True ise read-only env'i yok say, DDL koş
        # (market_ingest.duckdb ilk seed'de boş olabilir → schema gerekir).
        import os as _os

        if (not self.force_write) and _os.environ.get("PA_DUCKDB_READ_ONLY", "").lower() in (
            "1",
            "true",
            "yes",
        ):
            return
        # FIX 2026-06-02 (PROD-INCIDENT): retry once after invalidated-handle eviction.
        # If the pool held a dead handle (from a prior "Invalid bitmask" fatal), _conn()
        # evicts it and re-raises. The second attempt gets a fresh connection.
        _attempts = 0
        while True:
            try:
                with self._conn() as con:
                    con.execute(_OHLCV_DDL)
                    con.execute(_INSTRUMENTS_DDL)
                    con.execute(
                        "CREATE INDEX IF NOT EXISTS idx_ohlcv_lookup "
                        "ON ohlcv (venue, symbol, timeframe, ts);"
                    )
                    # FIX 2026-05-28 (audit-Y4): MAX(ts) sorguları için DESC index.
                    # last_ts() ingest tarafından her saat 50 sembol × 3 TF = 150 kez
                    # çağrılıyor. Mevcut ASC index MAX için yardımcı oluyor ama DESC
                    # doğrudan index seek yapar (~10ms → <1ms per query).
                    con.execute(
                        "CREATE INDEX IF NOT EXISTS idx_ohlcv_last_ts "
                        "ON ohlcv (venue, symbol, timeframe, ts DESC);"
                    )
                return  # success
            except Exception as exc:
                _attempts += 1
                if _attempts >= 2 or not any(m in str(exc) for m in _INVALIDATED_MARKERS):
                    raise  # non-invalidation error or retry exhausted — fail loud

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
                # FIX 2026-05-28 (audit-A5): COMMIT sonrası CHECKPOINT — WAL'ı
                # ana dosyaya flush et. DuckDB'de transaction commit ACID ama WAL
                # büyük tutuluyor (8.5MB market.duckdb.wal görüldü) → hard kill
                # sonrası WAL replay'i bozuk olabilir. CHECKPOINT durability garantisi.
                # Maliyet: ingest hourly, latency artışı kabul edilebilir.
                try:
                    con.execute("CHECKPOINT")
                except Exception as _ckpt_err:
                    logger.bind(err=str(_ckpt_err)).warning("ohlcv.checkpoint_fail")
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
        return self.parquet_root / venue / sym_safe / tf / f"year={year:04d}" / f"month={month:02d}"

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
            # FIX 2026-05-28 (audit-A5): atomic parquet write — tmp + os.replace.
            # Önceki kod doğrudan file_path'e yazıyordu → mid-write crash yarım
            # parquet bırakırdı, read tarafı ParquetException atardı + dosya
            # silinene kadar veri kaybı. Şimdi: temp file'a yaz, sonra atomic
            # rename (POSIX guarantee). Crash anında file_path ya eski versiyon
            # ya da tam yeni — yarı asla.
            import os as _os

            tmp_path = file_path.with_suffix(".parquet.tmp")
            try:
                merged.to_parquet(tmp_path, index=False)
                _os.replace(tmp_path, file_path)  # atomic
            except Exception:
                # Cleanup tmp dosya
                try:
                    if tmp_path.exists():
                        tmp_path.unlink()
                except OSError:
                    pass
                raise

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
            ts = ts.replace(tzinfo=UTC)
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
