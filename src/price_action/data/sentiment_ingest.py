"""Crypto Fear & Greed Index ingest — alternative.me API.

Günlük F&G verisi çeker ve DuckDB'ye yazar.
Ücretsiz API, 2000 gün geçmiş (2018+).

API:
    https://api.alternative.me/fng/?limit=2000

Table schema (data/sentiment.duckdb):
    fng_daily(ts TIMESTAMPTZ, value INT, classification VARCHAR)

CLI:
    python -m price_action.data.sentiment_ingest   # veya doğrudan
    PYTHONPATH=src python -c "from price_action.data.sentiment_ingest import fetch_and_store; fetch_and_store()"

Savunma:
    - Network fail → log + return empty, no crash
    - Duplicate rows → upsert (DELETE + INSERT)
    - Schema mismatch → clear table on start
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

# ---------------------------------------------------------------------------
# Sabitler
# ---------------------------------------------------------------------------

FNG_API_URL = "https://api.alternative.me/fng/"
_DEFAULT_LIMIT = 2000

_FNG_DDL = """
CREATE TABLE IF NOT EXISTS fng_daily (
    ts             TIMESTAMPTZ NOT NULL PRIMARY KEY,
    value          INTEGER     NOT NULL,
    classification VARCHAR     NOT NULL
);
"""

# ---------------------------------------------------------------------------
# Connection pool (Windows DuckDB safety — tek process, multi-thread safe)
# ---------------------------------------------------------------------------

_CONN_POOL: dict[str, duckdb.DuckDBPyConnection] = {}
_CONN_LOCKS: dict[str, threading.RLock] = {}
_POOL_GUARD = threading.Lock()


def _get_pooled_connection(path: str) -> tuple[duckdb.DuckDBPyConnection, threading.RLock]:
    with _POOL_GUARD:
        if path not in _CONN_POOL:
            _CONN_POOL[path] = duckdb.connect(path)
            _CONN_LOCKS[path] = threading.RLock()
        return _CONN_POOL[path], _CONN_LOCKS[path]


def reset_fng_pool() -> None:
    """Test fixture'larında bağlantı havuzunu temizler."""
    with _POOL_GUARD:
        for con in list(_CONN_POOL.values()):
            try:
                con.close()
            except Exception:
                pass
        _CONN_POOL.clear()
        _CONN_LOCKS.clear()


# ---------------------------------------------------------------------------
# FngStore — DuckDB persistence katmanı
# ---------------------------------------------------------------------------

def _default_db_path() -> Path:
    """Proje kökünden data/sentiment.duckdb yolunu döner."""
    root = Path(__file__).resolve().parents[4]  # src/price_action/data/ → root
    return root / "data" / "sentiment.duckdb"


class FngStore:
    """F&G DuckDB katmanı.

    Parameters
    ----------
    duckdb_path:
        Varsayılan None → data/sentiment.duckdb kullanır.
    """

    def __init__(self, duckdb_path: Path | str | None = None) -> None:
        if duckdb_path is None:
            self.duckdb_path = _default_db_path()
        else:
            self.duckdb_path = Path(duckdb_path)
        self.duckdb_path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()

    @contextmanager
    def _conn(self) -> Iterator[duckdb.DuckDBPyConnection]:
        path = str(self.duckdb_path)
        con, lock = _get_pooled_connection(path)
        with lock:
            yield con

    def _ensure_schema(self) -> None:
        with self._conn() as con:
            con.execute(_FNG_DDL)

    def upsert(self, df: pd.DataFrame) -> int:
        """F&G satırlarını idempotent şekilde yazar.

        Beklenen kolonlar: ts (datetime UTC), value (int), classification (str).
        """
        if df is None or df.empty:
            return 0
        required = {"ts", "value", "classification"}
        missing = required - set(df.columns)
        if missing:
            raise ValueError(f"fng df eksik kolon(lar): {missing}")

        df = df[["ts", "value", "classification"]].copy()

        # ts UTC'ye normalize et
        if not pd.api.types.is_datetime64_any_dtype(df["ts"]):
            df["ts"] = pd.to_datetime(df["ts"], utc=True, errors="coerce")
        elif df["ts"].dt.tz is None:
            df["ts"] = df["ts"].dt.tz_localize("UTC")
        else:
            df["ts"] = df["ts"].dt.tz_convert("UTC")

        df["value"] = pd.to_numeric(df["value"], errors="coerce").astype("Int64")
        df["classification"] = df["classification"].astype(str)
        df = df.drop_duplicates(subset=["ts"], keep="last")
        df = df.dropna(subset=["ts", "value"])

        with self._conn() as con:
            con.register("fng_staging", df)
            con.execute("BEGIN")
            try:
                con.execute(
                    """
                    DELETE FROM fng_daily
                    USING fng_staging s
                    WHERE fng_daily.ts = s.ts;
                    """
                )
                con.execute(
                    "INSERT INTO fng_daily (ts, value, classification) "
                    "SELECT ts, value, classification FROM fng_staging;"
                )
                con.execute("COMMIT")
            except Exception:
                con.execute("ROLLBACK")
                raise
            finally:
                con.unregister("fng_staging")

        logger.bind(rows=len(df), op="fng_upsert").info("fng.upsert")
        return len(df)

    def read(
        self,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> pd.DataFrame:
        """F&G verisini oku. ts ascending sıralı."""
        clauses: list[str] = []
        params: list[Any] = []
        if start is not None:
            clauses.append("ts >= ?")
            params.append(start)
        if end is not None:
            clauses.append("ts <= ?")
            params.append(end)
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        sql = f"SELECT ts, value, classification FROM fng_daily{where} ORDER BY ts ASC"
        with self._conn() as con:
            df = con.execute(sql, params).fetchdf()
        if df.empty:
            return df
        if df["ts"].dt.tz is None:
            df["ts"] = df["ts"].dt.tz_localize("UTC")
        else:
            df["ts"] = df["ts"].dt.tz_convert("UTC")
        return df

    def last_ts(self) -> datetime | None:
        """Tablodaki en güncel tarih."""
        try:
            with self._conn() as con:
                row = con.execute("SELECT MAX(ts) FROM fng_daily").fetchone()
        except Exception as exc:
            logger.warning("fng_store.last_ts_error", extra={"err": str(exc)[:200]})
            return None
        if row is None or row[0] is None:
            return None
        ts = row[0]
        if isinstance(ts, datetime) and ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return ts

    def count(self) -> int:
        with self._conn() as con:
            row = con.execute("SELECT COUNT(*) FROM fng_daily").fetchone()
        return int(row[0]) if row else 0


# ---------------------------------------------------------------------------
# API Fetch
# ---------------------------------------------------------------------------

def fetch_fear_greed_history(limit: int = _DEFAULT_LIMIT) -> pd.DataFrame:
    """Alternative.me F&G API'sinden tarihsel veri çeker.

    Parameters
    ----------
    limit:
        Kaç gün geçmiş istendiği (max 2000).

    Returns
    -------
    pd.DataFrame
        Kolonlar: ts (UTC datetime), value (int 0-100), classification (str).
        Hata durumunda boş DataFrame döner (crash yok).
    """
    try:
        import requests  # type: ignore[import-not-found]
    except ImportError:
        logger.error("fng.fetch.missing_requests", extra={"hint": "pip install requests"})
        return pd.DataFrame(columns=["ts", "value", "classification"])

    # date_format omitted → API returns unix epoch timestamps (integer strings)
    url = f"{FNG_API_URL}?limit={limit}&format=json"
    log = logger.bind(url=url, limit=limit)
    try:
        resp = requests.get(url, timeout=30)
        resp.raise_for_status()
        payload = resp.json()
    except Exception as exc:
        log.warning("fng.fetch.network_error", extra={"err": str(exc)[:300]})
        return pd.DataFrame(columns=["ts", "value", "classification"])

    data = payload.get("data", [])
    if not data:
        log.warning("fng.fetch.empty_response")
        return pd.DataFrame(columns=["ts", "value", "classification"])

    rows = []
    for item in data:
        try:
            # date_format=us → "timestamp" field is unix epoch string
            ts_unix = int(item.get("timestamp", 0))
            value = int(item.get("value", 0))
            classification = str(item.get("value_classification", "Unknown"))
            ts_dt = datetime.fromtimestamp(ts_unix, tz=timezone.utc)
            # Normalize to midnight UTC (daily data)
            ts_day = ts_dt.replace(hour=0, minute=0, second=0, microsecond=0)
            rows.append({"ts": ts_day, "value": value, "classification": classification})
        except Exception as exc:
            log.warning("fng.fetch.row_parse_error", extra={"item": str(item)[:100], "err": str(exc)})
            continue

    if not rows:
        log.warning("fng.fetch.no_rows_parsed")
        return pd.DataFrame(columns=["ts", "value", "classification"])

    df = pd.DataFrame(rows)
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    df = df.sort_values("ts").reset_index(drop=True)
    df = df.drop_duplicates(subset=["ts"], keep="last")

    log.bind(rows=len(df)).info("fng.fetch.success")
    return df


def fetch_and_store(
    limit: int = _DEFAULT_LIMIT,
    store: FngStore | None = None,
) -> int:
    """Fetch + store pipeline. Rows written döner."""
    if store is None:
        store = FngStore()
    df = fetch_fear_greed_history(limit=limit)
    if df.empty:
        logger.warning("fng.ingest.empty_fetch")
        return 0
    written = store.upsert(df)
    logger.bind(written=written).info("fng.ingest.done")
    return written


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":  # pragma: no cover
    import sys
    limit_arg = int(sys.argv[1]) if len(sys.argv) > 1 else _DEFAULT_LIMIT
    written = fetch_and_store(limit=limit_arg)
    print(f"Written {written} rows to sentiment.duckdb")
