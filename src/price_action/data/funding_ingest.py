"""Binance USDT-perp funding rate ingest — ccxt unified API.

Her 8 saatte bir Binance perpetual'lardan funding rate çeker ve
DuckDB'ye yazar. OHLCV ingest ile aynı pattern / retry / backfill
mantığını kullanır.

Table schema:
    funding_rates(venue, symbol, ts, funding_rate, mark_price)

CLI:
    pa-funding-ingest --symbols BTC/USDT:USDT,ETH/USDT:USDT --years 3
    pa-funding-ingest                                          # tüm konfig defaults
"""
from __future__ import annotations

import time
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator

import duckdb
import pandas as pd
import typer

from price_action.logging_config import logger
from price_action.settings import get_settings

app = typer.Typer(add_completion=False, help="Funding rate ingest CLI")

# 8h in milliseconds — Binance perp funding frequency
_FUNDING_INTERVAL_MS: int = 8 * 60 * 60 * 1000

# Default USDT-perp symbols to ingest
PERP_SYMBOLS_DEFAULT: list[str] = [
    "BTC/USDT:USDT",
    "ETH/USDT:USDT",
    "SOL/USDT:USDT",
    "BNB/USDT:USDT",
    "XRP/USDT:USDT",
]

_FUNDING_DDL = """
CREATE TABLE IF NOT EXISTS funding_rates (
    venue        VARCHAR NOT NULL,
    symbol       VARCHAR NOT NULL,
    ts           TIMESTAMP WITH TIME ZONE NOT NULL,
    funding_rate DOUBLE NOT NULL,
    mark_price   DOUBLE,
    PRIMARY KEY (venue, symbol, ts)
);
"""

# ---------------------------------------------------------------------------
# Connection pool (same pattern as OHLCVStore for Windows DuckDB safety)
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


def reset_funding_pool() -> None:
    """Test fixture'larında kullanılır."""
    with _POOL_GUARD:
        for con in list(_CONN_POOL.values()):
            try:
                con.close()
            except Exception:
                pass
        _CONN_POOL.clear()
        _CONN_LOCKS.clear()


# ---------------------------------------------------------------------------
# FundingStore — DuckDB persistence layer
# ---------------------------------------------------------------------------

class FundingStore:
    """Funding rate DuckDB katmanı."""

    def __init__(self, duckdb_path: Path | None = None) -> None:
        s = get_settings()
        self.duckdb_path: Path = Path(duckdb_path) if duckdb_path else s.duckdb_path
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
            con.execute(_FUNDING_DDL)
            con.execute(
                "CREATE INDEX IF NOT EXISTS idx_funding_lookup "
                "ON funding_rates (venue, symbol, ts);"
            )

    def last_ts(self, venue: str, symbol: str) -> datetime | None:
        try:
            with self._conn() as con:
                row = con.execute(
                    "SELECT MAX(ts) FROM funding_rates WHERE venue=? AND symbol=?",
                    [venue, symbol],
                ).fetchone()
        except Exception as exc:
            logger.warning(
                "funding_store.last_ts_fallback",
                extra={"venue": venue, "symbol": symbol, "err": str(exc)[:200]},
            )
            return None
        if row is None or row[0] is None:
            return None
        ts = row[0]
        if isinstance(ts, datetime) and ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return ts

    def upsert(self, df: pd.DataFrame) -> int:
        """Funding rate satırlarını idempotent şekilde yaz."""
        if df is None or df.empty:
            return 0
        required = ["venue", "symbol", "ts", "funding_rate"]
        missing = [c for c in required if c not in df.columns]
        if missing:
            raise ValueError(f"funding df eksik kolon(lar): {missing}")
        if "mark_price" not in df.columns:
            df = df.copy()
            df["mark_price"] = float("nan")
        df = df[["venue", "symbol", "ts", "funding_rate", "mark_price"]].copy()
        # Ensure UTC timestamps
        if not pd.api.types.is_datetime64_any_dtype(df["ts"]):
            df["ts"] = pd.to_datetime(df["ts"], utc=True, errors="coerce")
        elif df["ts"].dt.tz is None:
            df["ts"] = df["ts"].dt.tz_localize("UTC")
        else:
            df["ts"] = df["ts"].dt.tz_convert("UTC")
        df["funding_rate"] = pd.to_numeric(df["funding_rate"], errors="coerce")
        df["mark_price"] = pd.to_numeric(df["mark_price"], errors="coerce")
        df = df.drop_duplicates(subset=["venue", "symbol", "ts"], keep="last")
        df = df.dropna(subset=["funding_rate"])

        with self._conn() as con:
            con.register("funding_staging", df)
            con.execute("BEGIN")
            try:
                con.execute(
                    """
                    DELETE FROM funding_rates
                    USING funding_staging s
                    WHERE funding_rates.venue = s.venue
                      AND funding_rates.symbol = s.symbol
                      AND funding_rates.ts = s.ts;
                    """
                )
                con.execute(
                    "INSERT INTO funding_rates (venue, symbol, ts, funding_rate, mark_price) "
                    "SELECT venue, symbol, ts, funding_rate, mark_price FROM funding_staging;"
                )
                con.execute("COMMIT")
            except Exception:
                con.execute("ROLLBACK")
                raise
            finally:
                con.unregister("funding_staging")
        logger.bind(rows=len(df), op="funding_upsert").info("funding.upsert")
        return len(df)

    def read(
        self,
        symbol: str,
        *,
        venue: str = "binance",
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> pd.DataFrame:
        """Funding rate oku. ts ascending sıralı."""
        clauses = ["venue = ?", "symbol = ?"]
        params: list[Any] = [venue, symbol]
        if start is not None:
            clauses.append("ts >= ?")
            params.append(start)
        if end is not None:
            clauses.append("ts <= ?")
            params.append(end)
        where = " AND ".join(clauses)
        sql = (
            f"SELECT venue, symbol, ts, funding_rate, mark_price "
            f"FROM funding_rates WHERE {where} ORDER BY ts ASC"
        )
        with self._conn() as con:
            df = con.execute(sql, params).fetchdf()
        if df.empty:
            return df
        if df["ts"].dt.tz is None:
            df["ts"] = df["ts"].dt.tz_localize("UTC")
        else:
            df["ts"] = df["ts"].dt.tz_convert("UTC")
        return df

    def symbols(self, venue: str = "binance") -> list[str]:
        with self._conn() as con:
            rows = con.execute(
                "SELECT DISTINCT symbol FROM funding_rates WHERE venue=? ORDER BY symbol",
                [venue],
            ).fetchall()
        return [r[0] for r in rows]


# ---------------------------------------------------------------------------
# Ingest logic
# ---------------------------------------------------------------------------

@dataclass
class FundingIngestStats:
    venue: str
    symbol: str
    rows_written: int
    fetched_pages: int
    error: str | None = None


def _build_ccxt_future(venue: str = "binance") -> Any:  # pragma: no cover
    import ccxt

    if not hasattr(ccxt, venue):
        raise ValueError(f"ccxt: bilinmeyen venue {venue}")
    return getattr(ccxt, venue)(
        {"options": {"defaultType": "future"}, "enableRateLimit": True}
    )


def _fetch_funding_with_retry(
    exchange: Any,
    symbol: str,
    since_ms: int,
    limit: int = 1000,
    *,
    max_retries: int = 5,
    base_backoff: float = 1.0,
) -> list[dict[str, Any]]:  # pragma: no cover
    """fetch_funding_rate_history ile rate-limit guard + exponential backoff."""
    attempt = 0
    while True:
        try:
            return exchange.fetch_funding_rate_history(symbol, since=since_ms, limit=limit)
        except Exception as exc:
            cls = exc.__class__.__name__.lower()
            transient = "ratelimit" in cls or "timeout" in cls or "ddos" in cls
            attempt += 1
            if attempt > max_retries or not transient:
                logger.bind(symbol=symbol, err=str(exc)).error("funding.fetch_fail")
                raise
            delay = base_backoff * (2 ** (attempt - 1))
            logger.bind(symbol=symbol, attempt=attempt, delay=delay).warning(
                "funding.backoff"
            )
            time.sleep(delay)


def _funding_records_to_df(
    records: list[dict[str, Any]],
    *,
    venue: str,
) -> pd.DataFrame:
    """ccxt funding_rate_history kayıtlarını DataFrame'e çevir."""
    if not records:
        return pd.DataFrame(
            columns=["venue", "symbol", "ts", "funding_rate", "mark_price"]
        )
    rows = []
    for r in records:
        ts = pd.to_datetime(r["timestamp"], unit="ms", utc=True)
        mark_price = float(r["info"].get("markPrice", float("nan"))) if r.get("info") else float("nan")
        rows.append(
            {
                "venue": venue,
                "symbol": r["symbol"],
                "ts": ts,
                "funding_rate": float(r["fundingRate"]),
                "mark_price": mark_price,
            }
        )
    return pd.DataFrame(rows)


def ingest_symbol_funding(
    *,
    venue: str = "binance",
    symbol: str,
    years: int = 3,
    store: FundingStore,
    exchange: Any | None = None,
    page_limit: int = 1000,
    sleep_between_pages_s: float = 0.1,
) -> FundingIngestStats:  # pragma: no cover
    """Tek sembol için funding rate backfill + incremental güncelle."""
    if exchange is None:
        exchange = _build_ccxt_future(venue)

    last = store.last_ts(venue, symbol)
    if last is not None:
        since = last + timedelta(milliseconds=_FUNDING_INTERVAL_MS)
    else:
        since = datetime.now(timezone.utc) - timedelta(days=365 * years)
    since_ms = int(since.timestamp() * 1000)

    pages = 0
    total_rows = 0
    error: str | None = None
    try:
        while True:
            raw = _fetch_funding_with_retry(exchange, symbol, since_ms, limit=page_limit)
            if not raw:
                break
            df = _funding_records_to_df(raw, venue=venue)
            written = store.upsert(df)
            total_rows += written
            pages += 1
            last_ms = int(raw[-1]["timestamp"])
            next_ms = last_ms + _FUNDING_INTERVAL_MS
            if next_ms <= since_ms:
                break
            since_ms = next_ms
            if len(raw) < page_limit:
                break
            if sleep_between_pages_s > 0:
                time.sleep(sleep_between_pages_s)
    except Exception as exc:
        error = str(exc)
        logger.bind(venue=venue, symbol=symbol, err=error).error("funding.ingest_fail")

    return FundingIngestStats(
        venue=venue,
        symbol=symbol,
        rows_written=total_rows,
        fetched_pages=pages,
        error=error,
    )


@app.command("run")
def run(
    symbols: str = typer.Option(
        ",".join(PERP_SYMBOLS_DEFAULT),
        "--symbols",
        help="Virgüllü USDT-perp sembolleri. Ör: BTC/USDT:USDT,ETH/USDT:USDT",
    ),
    years: int = typer.Option(3, "--years", help="Kaç yıl geçmişe git"),
    venue: str = typer.Option("binance", "--venue"),
) -> None:  # pragma: no cover
    symbol_list = [s.strip() for s in symbols.split(",") if s.strip()]
    store = FundingStore()
    for sym in symbol_list:
        stat = ingest_symbol_funding(venue=venue, symbol=sym, years=years, store=store)
        logger.bind(**stat.__dict__).info("funding.ingest_done")


def main() -> None:  # pragma: no cover
    app()


if __name__ == "__main__":  # pragma: no cover
    main()
