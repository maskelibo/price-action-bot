"""Stablecoin supply ingest — CoinGecko free API (no key required).

USDT + USDC piyasa değeri (market cap) günlük zaman serisi çeker.
Hypothesis H22: stable supply büyümesi → kripto likidite proxy'si.

API:
    https://api.coingecko.com/api/v3/coins/tether/market_chart?vs_currency=usd&days=1095
    https://api.coingecko.com/api/v3/coins/usd-coin/market_chart?vs_currency=usd&days=1095
    Returns: {"market_caps": [[timestamp_ms, value], ...], "prices": [...], "total_volumes": [...]}

Free tier limits:
    30 requests/minute. No API key needed for /coins/{id}/market_chart.
    Historical: up to 1095 days (3 years) at daily granularity when days > 90.

Table schema (data/stablecoin.duckdb):
    stablecoin_supply_daily(ts TIMESTAMPTZ, symbol VARCHAR, market_cap_usd DOUBLE)
    PRIMARY KEY (ts, symbol)

Usage:
    from price_action.data.stablecoin_ingest import fetch_stable_supply, fetch_and_store_stable

Lookahead note:
    market_cap data is published at UTC midnight (daily).
    Callers MUST apply shift(1) before using in signal filters.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd

from price_action.logging_config import logger

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

COINGECKO_BASE = "https://api.coingecko.com/api/v3"

# CoinGecko coin IDs for the two dominant stablecoins
STABLE_COIN_IDS: dict[str, str] = {
    "USDT": "tether",
    "USDC": "usd-coin",
}

_DEFAULT_DAYS = 365  # CoinGecko free tier: max 365 days (~1 year)
# NOTE: days=730 and days=1095 return HTTP 401 on the free/public tier.
# For multi-year history, either use a paid CoinGecko plan or supplement with
# CoinMarketCap historical snapshots (requires separate ingest).

_STABLE_DDL = """
CREATE TABLE IF NOT EXISTS stablecoin_supply_daily (
    ts             TIMESTAMPTZ NOT NULL,
    symbol         VARCHAR     NOT NULL,
    market_cap_usd DOUBLE      NOT NULL,
    PRIMARY KEY (ts, symbol)
);
"""

# ---------------------------------------------------------------------------
# Connection pool (thread-safe, mirrors sentiment_ingest pattern)
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


def reset_stable_pool() -> None:
    """Test fixture'larında bağlantı havuzunu temizler."""
    with _POOL_GUARD:
        for con in list(_CONN_POOL.values()):
            try:  # noqa: SIM105
                con.close()
            except Exception:
                pass
        _CONN_POOL.clear()
        _CONN_LOCKS.clear()


# ---------------------------------------------------------------------------
# StablecoinStore — DuckDB persistence layer
# ---------------------------------------------------------------------------


def _default_db_path() -> Path:
    root = (
        Path(__file__).resolve().parents[3]
    )  # G24-fix 2026-07-07: parents[4] repo DIŞINA yazıyordu (~/data/)
    return root / "data" / "stablecoin.duckdb"


class StablecoinStore:
    """Stablecoin supply DuckDB katmanı.

    Parameters
    ----------
    duckdb_path:
        None → data/stablecoin.duckdb.
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
            con.execute(_STABLE_DDL)

    def upsert(self, df: pd.DataFrame) -> int:
        """Stablecoin satırlarını idempotent yazar.

        Beklenen kolonlar: ts (datetime UTC), symbol (str), market_cap_usd (float).
        """
        if df is None or df.empty:
            return 0
        required = {"ts", "symbol", "market_cap_usd"}
        missing = required - set(df.columns)
        if missing:
            raise ValueError(f"stablecoin df eksik kolon(lar): {missing}")

        df = df[["ts", "symbol", "market_cap_usd"]].copy()

        if not pd.api.types.is_datetime64_any_dtype(df["ts"]):
            df["ts"] = pd.to_datetime(df["ts"], utc=True, errors="coerce")
        elif df["ts"].dt.tz is None:
            df["ts"] = df["ts"].dt.tz_localize("UTC")
        else:
            df["ts"] = df["ts"].dt.tz_convert("UTC")

        df["symbol"] = df["symbol"].astype(str)
        df["market_cap_usd"] = pd.to_numeric(df["market_cap_usd"], errors="coerce")
        df = df.drop_duplicates(subset=["ts", "symbol"], keep="last")
        df = df.dropna(subset=["ts", "market_cap_usd"])

        with self._conn() as con:
            con.register("stable_staging", df)
            con.execute("BEGIN")
            try:
                con.execute(
                    """
                    DELETE FROM stablecoin_supply_daily
                    USING stable_staging s
                    WHERE stablecoin_supply_daily.ts = s.ts
                      AND stablecoin_supply_daily.symbol = s.symbol;
                    """
                )
                con.execute(
                    "INSERT INTO stablecoin_supply_daily (ts, symbol, market_cap_usd) "
                    "SELECT ts, symbol, market_cap_usd FROM stable_staging;"
                )
                con.execute("COMMIT")
            except Exception:
                con.execute("ROLLBACK")
                raise
            finally:
                con.unregister("stable_staging")

        logger.bind(rows=len(df), op="stable_upsert").info("stablecoin.upsert")
        return len(df)

    def read(
        self,
        start: datetime | None = None,
        end: datetime | None = None,
        symbols: list[str] | None = None,
    ) -> pd.DataFrame:
        """Stablecoin supply verisini oku. ts ascending sıralı."""
        clauses: list[str] = []
        params: list[Any] = []

        if start is not None:
            clauses.append("ts >= ?")
            params.append(start)
        if end is not None:
            clauses.append("ts <= ?")
            params.append(end)
        if symbols:
            placeholders = ",".join(["?"] * len(symbols))
            clauses.append(f"symbol IN ({placeholders})")
            params.extend(symbols)

        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        sql = (
            "SELECT ts, symbol, market_cap_usd "
            f"FROM stablecoin_supply_daily{where} "
            "ORDER BY ts ASC, symbol ASC"
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

    def count(self) -> int:
        with self._conn() as con:
            row = con.execute("SELECT COUNT(*) FROM stablecoin_supply_daily").fetchone()
        return int(row[0]) if row else 0


# ---------------------------------------------------------------------------
# CoinGecko API fetch
# ---------------------------------------------------------------------------


def fetch_stable_supply(
    coin_id: str,
    symbol: str,
    days: int = _DEFAULT_DAYS,
    *,
    max_retries: int = 3,
    base_backoff: float = 2.0,
) -> pd.DataFrame:
    """CoinGecko'dan tek bir stablecoin'in günlük market cap geçmişini çeker.

    Parameters
    ----------
    coin_id:
        CoinGecko coin ID ("tether", "usd-coin").
    symbol:
        Sembol etiketi (e.g. "USDT", "USDC").
    days:
        Geçmiş gün sayısı. 1095 ≈ 3 yıl.

    Returns
    -------
    pd.DataFrame
        Kolonlar: ts (UTC midnight), symbol (str), market_cap_usd (float).
        Hata durumunda boş DataFrame (crash yok).
    """
    try:
        import requests  # type: ignore[import-not-found]
    except ImportError:
        logger.error("stablecoin.fetch.missing_requests")
        return pd.DataFrame(columns=["ts", "symbol", "market_cap_usd"])

    url = f"{COINGECKO_BASE}/coins/{coin_id}/market_chart"
    params = {"vs_currency": "usd", "days": days}
    # Browser-like headers required by CoinGecko free tier (401 without them)
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json",
    }
    log = logger.bind(coin_id=coin_id, symbol=symbol, days=days)

    attempt = 0
    while True:
        try:
            resp = requests.get(url, params=params, headers=headers, timeout=30)
            if resp.status_code == 429:
                # Rate limit: back off regardless of retry count
                delay = base_backoff * (2**attempt)
                log.warning("stablecoin.fetch.rate_limit", extra={"delay": delay})
                time.sleep(delay)
                attempt += 1
                if attempt > max_retries:
                    log.error("stablecoin.fetch.rate_limit_exceeded")
                    return pd.DataFrame(columns=["ts", "symbol", "market_cap_usd"])
                continue
            resp.raise_for_status()
            payload = resp.json()
            break
        except Exception as exc:
            attempt += 1
            cls = exc.__class__.__name__.lower()
            transient = "timeout" in cls or "connection" in cls
            if attempt > max_retries or not transient:
                log.bind(err=str(exc)[:200]).warning("stablecoin.fetch.error")
                return pd.DataFrame(columns=["ts", "symbol", "market_cap_usd"])
            delay = base_backoff * (2 ** (attempt - 1))
            log.bind(attempt=attempt, delay=delay).warning("stablecoin.fetch.backoff")
            time.sleep(delay)

    market_caps: list[list[Any]] = payload.get("market_caps", [])
    if not market_caps:
        log.warning("stablecoin.fetch.empty_market_caps")
        return pd.DataFrame(columns=["ts", "symbol", "market_cap_usd"])

    rows = []
    for entry in market_caps:
        try:
            ts_ms = int(entry[0])
            cap_usd = float(entry[1])
            ts_dt = datetime.fromtimestamp(ts_ms / 1000.0, tz=UTC)
            # Normalize to UTC midnight (daily grain)
            ts_day = ts_dt.replace(hour=0, minute=0, second=0, microsecond=0)
            rows.append({"ts": ts_day, "symbol": symbol, "market_cap_usd": cap_usd})
        except Exception as exc:
            log.warning("stablecoin.fetch.row_parse_error", extra={"err": str(exc)[:100]})
            continue

    if not rows:
        log.warning("stablecoin.fetch.no_rows_parsed")
        return pd.DataFrame(columns=["ts", "symbol", "market_cap_usd"])

    df = pd.DataFrame(rows)
    df["ts"] = pd.to_datetime(df["ts"], utc=True)

    # When days > 90, CoinGecko returns daily; still may have intra-day duplicates.
    # Keep last reading per day.
    df = df.sort_values("ts")
    df = df.drop_duplicates(subset=["ts", "symbol"], keep="last")
    df = df.reset_index(drop=True)

    log.bind(rows=len(df)).info("stablecoin.fetch.success")
    return df


def fetch_usdt_usdc_supply(
    days: int = _DEFAULT_DAYS,
    *,
    inter_request_sleep: float = 2.0,
) -> pd.DataFrame:
    """USDT + USDC market cap geçmişini çeker ve birleştirir.

    Parameters
    ----------
    days:
        Her iki coin için gün sayısı.
    inter_request_sleep:
        İki istek arasında bekleme (CoinGecko 30 req/min — 2 sn yeterli).

    Returns
    -------
    pd.DataFrame
        Kolonlar: ts (UTC midnight), symbol, market_cap_usd.
        Sıralama: ts asc, symbol asc.
    """
    frames: list[pd.DataFrame] = []

    for symbol, coin_id in STABLE_COIN_IDS.items():
        df = fetch_stable_supply(coin_id=coin_id, symbol=symbol, days=days)
        if not df.empty:
            frames.append(df)
        # Politeness delay between requests
        if inter_request_sleep > 0:
            time.sleep(inter_request_sleep)

    if not frames:
        logger.warning("stablecoin.fetch_combined.empty")
        return pd.DataFrame(columns=["ts", "symbol", "market_cap_usd"])

    combined = pd.concat(frames, ignore_index=True)
    combined = combined.sort_values(["ts", "symbol"]).reset_index(drop=True)
    logger.bind(rows=len(combined), symbols=list(STABLE_COIN_IDS.keys())).info(
        "stablecoin.fetch_combined.done"
    )
    return combined


def build_combined_supply_series(df: pd.DataFrame) -> pd.DataFrame:
    """USDT + USDC market cap'leri tek 'total_stable_mcap' serisine indirger.

    Her gün için USDT + USDC toplamını hesaplar. Eğer bir sembol o günde yoksa
    mevcut değer tek başına kullanılır (partial sum, NaN skip).

    Parameters
    ----------
    df:
        fetch_usdt_usdc_supply() çıktısı (ts, symbol, market_cap_usd).

    Returns
    -------
    pd.DataFrame
        Kolonlar: ts (UTC midnight), total_stable_mcap (float).
        Her satır bir güne karşılık gelir, ts ascending.
    """
    if df is None or df.empty:
        return pd.DataFrame(columns=["ts", "total_stable_mcap"])

    # Pivot: ts → rows, symbol → columns
    pivot = df.pivot_table(
        index="ts",
        columns="symbol",
        values="market_cap_usd",
        aggfunc="last",
    )

    # Sum across USDT + USDC (skipna=True: günde biri eksikse diğeriyle devam)
    pivot["total_stable_mcap"] = pivot.sum(axis=1, skipna=True, min_count=1)

    result = pivot[["total_stable_mcap"]].reset_index()
    result = result.sort_values("ts").reset_index(drop=True)

    # Ensure ts is UTC
    if result["ts"].dt.tz is None:
        result["ts"] = result["ts"].dt.tz_localize("UTC")

    return result


# ---------------------------------------------------------------------------
# Fetch + Store pipeline
# ---------------------------------------------------------------------------


def fetch_and_store_stable(
    days: int = _DEFAULT_DAYS,
    store: StablecoinStore | None = None,
    *,
    inter_request_sleep: float = 2.0,
) -> int:
    """Fetch USDT+USDC supply and persist to DuckDB. Returns rows written."""
    if store is None:
        store = StablecoinStore()

    df = fetch_usdt_usdc_supply(days=days, inter_request_sleep=inter_request_sleep)
    if df.empty:
        logger.warning("stablecoin.ingest.empty_fetch")
        return 0

    written = store.upsert(df)
    logger.bind(written=written).info("stablecoin.ingest.done")
    return written


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":  # pragma: no cover
    import sys

    days_arg = int(sys.argv[1]) if len(sys.argv) > 1 else _DEFAULT_DAYS
    written = fetch_and_store_stable(days=days_arg)
    print(f"Written {written} rows to stablecoin.duckdb")
