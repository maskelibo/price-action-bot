"""Funding rate ingest — dedicated alt-data module.

Binance USDT-perp funding rate'lerini DuckDB'ye yazar.
data/funding_rates.duckdb (market.duckdb'den bağımsız, collision-free).

Schema:
    funding_rates(venue, symbol, ts, funding_rate, mark_price)
    PRIMARY KEY (venue, symbol, ts)

Kısıtlar:
  - Tüm ts UTC, tz-aware
  - No forward-fill: eksik bar NaN olarak kalır, downstream karar verir
  - No clip / winsorize: ham veri korunur, anomali işaretlenir
  - Idempotent: aynı run → aynı satır sayısı (upsert semantics)
  - Rate limit: ccxt built-in throttle + exponential backoff

Binance endpoint:
    /fapi/v1/fundingRate?symbol=BTCUSDT&limit=1000
    Granularity: 8h (3 per day)
    History: genellikle 2019+ (sembol başlatma tarihine bağlı)

Universe: configs/symbols.yaml manual_list'teki 11 sembol
    BTC, ETH, SOL, BNB, XRP, ADA, DOGE, AVAX, LINK, MATIC, DOT
    → Binance perp format: {SYM}USDT
"""
from __future__ import annotations

import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator

import duckdb
import pandas as pd

from price_action.logging_config import logger
from price_action.settings import ROOT_DIR

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

# Dedicated alt-data DB (ayrı dosya — market.duckdb ile çakışma yok)
ALT_DATA_DB: Path = ROOT_DIR / "data" / "funding_rates.duckdb"

# 8h interval in ms
_FUNDING_INTERVAL_MS: int = 8 * 60 * 60 * 1000

# Binance perp symbols for 11-sym universe
UNIVERSE_SYMBOLS: list[str] = [
    "BTCUSDT",
    "ETHUSDT",
    "SOLUSDT",
    "BNBUSDT",
    "XRPUSDT",
    "ADAUSDT",
    "DOGEUSDT",
    "AVAXUSDT",
    "LINKUSDT",
    "MATICUSDT",
    "DOTUSDT",
]

# Reasonable sanity bounds for funding rate anomaly flagging
FUNDING_ANOMALY_HIGH: float = 0.01    # > 1% per 8h = extreme
FUNDING_ANOMALY_LOW: float = -0.01   # < -1% per 8h = extreme

_DDL = """
CREATE TABLE IF NOT EXISTS funding_rates (
    venue        VARCHAR NOT NULL,
    symbol       VARCHAR NOT NULL,
    ts           TIMESTAMP WITH TIME ZONE NOT NULL,
    funding_rate DOUBLE NOT NULL,
    mark_price   DOUBLE,
    anomaly_flag BOOLEAN DEFAULT FALSE,
    PRIMARY KEY (venue, symbol, ts)
);
CREATE INDEX IF NOT EXISTS idx_fr_sym_ts
    ON funding_rates (symbol, ts);
"""

# ---------------------------------------------------------------------------
# Connection pool (Windows DuckDB safety — same pattern as store.py)
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


def reset_pool() -> None:
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
# FundingRateStore
# ---------------------------------------------------------------------------

class FundingRateStore:
    """Dedicated funding_rates.duckdb katmanı.

    market.duckdb'den bağımsız.
    funding_ingest.FundingStore ile API uyumlu ama farklı DB path + anomaly_flag kolonu.
    """

    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = Path(db_path) if db_path else ALT_DATA_DB
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()

    @contextmanager
    def _conn(self) -> Iterator[duckdb.DuckDBPyConnection]:
        path = str(self.db_path)
        con, lock = _get_pooled_connection(path)
        with lock:
            yield con

    def _ensure_schema(self) -> None:
        with self._conn() as con:
            con.execute(_DDL)

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------

    def last_ts(self, venue: str, symbol: str) -> datetime | None:
        """Son kayıtlı timestamp. None ise backfill başlatılmalı."""
        try:
            with self._conn() as con:
                row = con.execute(
                    "SELECT MAX(ts) FROM funding_rates WHERE venue=? AND symbol=?",
                    [venue, symbol],
                ).fetchone()
        except Exception as exc:
            logger.warning("fr_store.last_ts_fail", extra={"symbol": symbol, "err": str(exc)[:120]})
            return None
        if not row or row[0] is None:
            return None
        ts = row[0]
        if isinstance(ts, datetime) and ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return ts

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
        if start:
            clauses.append("ts >= ?")
            params.append(start)
        if end:
            clauses.append("ts <= ?")
            params.append(end)
        where = " AND ".join(clauses)
        sql = (
            f"SELECT venue, symbol, ts, funding_rate, mark_price, anomaly_flag "
            f"FROM funding_rates WHERE {where} ORDER BY ts ASC"
        )
        with self._conn() as con:
            df = con.execute(sql, params).df()
        if df.empty:
            return df
        df["ts"] = pd.to_datetime(df["ts"], utc=True)
        return df

    def symbols(self, venue: str = "binance") -> list[str]:
        with self._conn() as con:
            rows = con.execute(
                "SELECT DISTINCT symbol FROM funding_rates WHERE venue=? ORDER BY symbol",
                [venue],
            ).fetchall()
        return [r[0] for r in rows]

    def row_count(self, venue: str = "binance") -> dict[str, int]:
        """Her sembol için satır sayısı."""
        with self._conn() as con:
            rows = con.execute(
                "SELECT symbol, COUNT(*) FROM funding_rates WHERE venue=? GROUP BY symbol ORDER BY symbol",
                [venue],
            ).fetchall()
        return {r[0]: int(r[1]) for r in rows}

    def gap_summary(self, symbol: str, venue: str = "binance") -> dict[str, Any]:
        """Gap analizi: beklenen vs mevcut 8h bar sayısı."""
        with self._conn() as con:
            row = con.execute(
                "SELECT MIN(ts), MAX(ts), COUNT(*) FROM funding_rates WHERE venue=? AND symbol=?",
                [venue, symbol],
            ).fetchone()
        if not row or row[0] is None:
            return {"symbol": symbol, "status": "empty"}
        min_ts, max_ts, count = row
        if isinstance(min_ts, datetime) and min_ts.tzinfo is None:
            min_ts = min_ts.replace(tzinfo=timezone.utc)
        if isinstance(max_ts, datetime) and max_ts.tzinfo is None:
            max_ts = max_ts.replace(tzinfo=timezone.utc)
        span_h = (max_ts - min_ts).total_seconds() / 3600.0
        expected = max(1, int(span_h / 8) + 1)
        gaps = max(0, expected - count)
        return {
            "symbol": symbol,
            "min_ts": min_ts.isoformat(),
            "max_ts": max_ts.isoformat(),
            "rows": count,
            "expected_bars": expected,
            "gap_count": gaps,
            "gap_pct": round(gaps / expected * 100, 3) if expected > 0 else 0.0,
        }

    def anomaly_count(self, symbol: str, venue: str = "binance") -> int:
        with self._conn() as con:
            row = con.execute(
                "SELECT COUNT(*) FROM funding_rates WHERE venue=? AND symbol=? AND anomaly_flag=TRUE",
                [venue, symbol],
            ).fetchone()
        return int(row[0]) if row else 0

    # ------------------------------------------------------------------
    # Writes
    # ------------------------------------------------------------------

    def upsert(self, df: pd.DataFrame) -> int:
        """Funding rate satırlarını idempotent upsert yap.

        Kurallar:
          - No forward-fill (eksik ts → eksik, downstream karar)
          - No clip / winsorize (ham veri, anomaly_flag ile işaret)
          - Anomali: |funding_rate| > 1% per 8h → anomaly_flag=True
        """
        if df is None or df.empty:
            return 0
        required = ["venue", "symbol", "ts", "funding_rate"]
        missing = [c for c in required if c not in df.columns]
        if missing:
            raise ValueError(f"funding_rate_ingest.upsert: eksik kolonlar: {missing}")

        df = df.copy()
        if "mark_price" not in df.columns:
            df["mark_price"] = float("nan")

        # UTC normalize
        if not pd.api.types.is_datetime64_any_dtype(df["ts"]):
            df["ts"] = pd.to_datetime(df["ts"], utc=True, errors="coerce")
        elif df["ts"].dt.tz is None:
            df["ts"] = df["ts"].dt.tz_localize("UTC")
        else:
            df["ts"] = df["ts"].dt.tz_convert("UTC")

        # Numeric coerce (never clip — anomaly_flag instead)
        df["funding_rate"] = pd.to_numeric(df["funding_rate"], errors="coerce")
        df["mark_price"] = pd.to_numeric(df["mark_price"], errors="coerce")

        # Anomaly flag (surface don't fix)
        df["anomaly_flag"] = (
            (df["funding_rate"] > FUNDING_ANOMALY_HIGH)
            | (df["funding_rate"] < FUNDING_ANOMALY_LOW)
        ).fillna(False)

        df = df.drop_duplicates(subset=["venue", "symbol", "ts"], keep="last")
        df = df.dropna(subset=["funding_rate"])
        df = df[["venue", "symbol", "ts", "funding_rate", "mark_price", "anomaly_flag"]]

        with self._conn() as con:
            con.register("fr_staging", df)
            con.execute("BEGIN")
            try:
                con.execute("""
                    DELETE FROM funding_rates
                    USING fr_staging s
                    WHERE funding_rates.venue = s.venue
                      AND funding_rates.symbol = s.symbol
                      AND funding_rates.ts = s.ts;
                """)
                con.execute("""
                    INSERT INTO funding_rates
                        (venue, symbol, ts, funding_rate, mark_price, anomaly_flag)
                    SELECT venue, symbol, ts, funding_rate, mark_price, anomaly_flag
                    FROM fr_staging;
                """)
                con.execute("COMMIT")
            except Exception:
                con.execute("ROLLBACK")
                raise
            finally:
                con.unregister("fr_staging")

        n = len(df)
        logger.bind(rows=n, symbol=df["symbol"].iloc[0] if len(df) > 0 else "?").info(
            "fr_store.upsert"
        )
        return n


# ---------------------------------------------------------------------------
# ccxt fetch helpers
# ---------------------------------------------------------------------------

def _build_exchange(venue: str = "binance") -> Any:  # pragma: no cover
    import ccxt
    if not hasattr(ccxt, venue):
        raise ValueError(f"ccxt: unknown venue {venue}")
    return getattr(ccxt, venue)(
        {"options": {"defaultType": "future"}, "enableRateLimit": True}
    )


def _fetch_with_retry(
    exchange: Any,
    symbol: str,
    since_ms: int,
    limit: int = 1000,
    *,
    max_retries: int = 5,
    base_backoff: float = 1.0,
) -> list[dict[str, Any]]:  # pragma: no cover
    """fetch_funding_rate_history + exponential backoff on transient errors."""
    attempt = 0
    while True:
        try:
            return exchange.fetch_funding_rate_history(symbol, since=since_ms, limit=limit)
        except Exception as exc:
            cls = exc.__class__.__name__.lower()
            transient = any(k in cls for k in ("ratelimit", "timeout", "ddos", "network"))
            attempt += 1
            if attempt > max_retries or not transient:
                logger.bind(symbol=symbol, err=str(exc)[:200]).error("fr_ingest.fetch_fail")
                raise
            delay = base_backoff * (2 ** (attempt - 1))
            logger.bind(symbol=symbol, attempt=attempt, delay=delay).warning("fr_ingest.backoff")
            time.sleep(delay)


def _records_to_df(records: list[dict[str, Any]], *, venue: str) -> pd.DataFrame:
    """ccxt funding_rate_history kayıtlarını DataFrame'e çevir."""
    if not records:
        return pd.DataFrame(columns=["venue", "symbol", "ts", "funding_rate", "mark_price"])
    rows = []
    for r in records:
        ts = pd.to_datetime(r["timestamp"], unit="ms", utc=True)
        mark = float(r["info"].get("markPrice", float("nan"))) if r.get("info") else float("nan")
        rows.append({
            "venue": venue,
            "symbol": r["symbol"],
            "ts": ts,
            "funding_rate": float(r["fundingRate"]),
            "mark_price": mark,
        })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Ingest function
# ---------------------------------------------------------------------------

@dataclass
class IngestStats:
    venue: str
    symbol: str
    rows_written: int = 0
    pages_fetched: int = 0
    date_start: str = ""
    date_end: str = ""
    gap_count: int = 0
    anomaly_count: int = 0
    error: str | None = None


def ingest_symbol(
    *,
    venue: str = "binance",
    symbol: str,
    years: int = 5,
    store: FundingRateStore,
    exchange: Any | None = None,
    page_limit: int = 1000,
    sleep_between_pages: float = 0.15,
) -> IngestStats:  # pragma: no cover
    """Tek sembol için funding rate backfill + incremental update.

    ccxt symbol format: BTC/USDT:USDT (perp)
    Binance raw symbol format: BTCUSDT (API)

    store.last_ts'e göre başlangıç noktası belirlenir.
    429 / timeout → exponential backoff.
    Partial backfill OK: bir sonraki gece eksik tamamlanır.
    """
    if exchange is None:
        exchange = _build_exchange(venue)

    # ccxt unified symbol format (BTC/USDT:USDT for BTCUSDT)
    ccxt_symbol = symbol
    if ":" not in ccxt_symbol and "/" not in ccxt_symbol:
        # BTCUSDT → BTC/USDT:USDT
        base = ccxt_symbol.replace("USDT", "")
        ccxt_symbol = f"{base}/USDT:USDT"

    last = store.last_ts(venue, symbol)
    if last is not None:
        since_dt = last + timedelta(milliseconds=_FUNDING_INTERVAL_MS)
    else:
        since_dt = datetime.now(timezone.utc) - timedelta(days=365 * years)

    since_ms = int(since_dt.timestamp() * 1000)
    stats = IngestStats(venue=venue, symbol=symbol)

    try:
        while True:
            raw = _fetch_with_retry(exchange, ccxt_symbol, since_ms, limit=page_limit)
            if not raw:
                break
            df = _records_to_df(raw, venue=venue)
            # Use raw symbol as stored key (BTCUSDT)
            df["symbol"] = symbol
            written = store.upsert(df)
            stats.rows_written += written
            stats.pages_fetched += 1

            last_ms = int(raw[-1]["timestamp"])
            next_ms = last_ms + _FUNDING_INTERVAL_MS
            if len(raw) < page_limit:
                break
            if next_ms <= since_ms:
                break
            since_ms = next_ms
            if sleep_between_pages > 0:
                time.sleep(sleep_between_pages)

        # Post-ingest stats
        gap_info = store.gap_summary(symbol, venue)
        stats.gap_count = gap_info.get("gap_count", 0)
        stats.date_start = gap_info.get("min_ts", "")
        stats.date_end = gap_info.get("max_ts", "")
        stats.anomaly_count = store.anomaly_count(symbol, venue)

    except Exception as exc:
        stats.error = str(exc)[:300]
        logger.bind(venue=venue, symbol=symbol, err=stats.error).error("fr_ingest.symbol_fail")

    return stats


def run_universe_ingest(
    *,
    symbols: list[str] | None = None,
    venue: str = "binance",
    years: int = 5,
    db_path: Path | None = None,
    sleep_between_symbols: float = 1.0,
) -> list[IngestStats]:  # pragma: no cover
    """Tüm universe için funding rate backfill çalıştır.

    Args:
        symbols: None → UNIVERSE_SYMBOLS (11 sym)
        years: backfill geçmişi (default 5)
        db_path: None → data/funding_rates.duckdb
        sleep_between_symbols: semboller arası bekleme (rate limit koruması)

    Returns:
        Her sembol için IngestStats listesi.
    """
    sym_list = symbols or UNIVERSE_SYMBOLS
    store = FundingRateStore(db_path)
    exchange = _build_exchange(venue)
    results: list[IngestStats] = []

    for sym in sym_list:
        logger.bind(symbol=sym, venue=venue).info("fr_ingest.start")
        stats = ingest_symbol(
            venue=venue,
            symbol=sym,
            years=years,
            store=store,
            exchange=exchange,
        )
        results.append(stats)
        logger.bind(
            symbol=sym,
            rows=stats.rows_written,
            pages=stats.pages_fetched,
            gaps=stats.gap_count,
            anomalies=stats.anomaly_count,
            error=stats.error,
        ).info("fr_ingest.done")
        if sleep_between_symbols > 0:
            time.sleep(sleep_between_symbols)

    return results


# ---------------------------------------------------------------------------
# 1d aggregation helper (8h → 1d for strategy merge)
# ---------------------------------------------------------------------------

def resample_to_daily(
    df: pd.DataFrame,
    *,
    agg_funding: str = "mean",
) -> pd.DataFrame:
    """8h funding → 1d aggregated DataFrame.

    Per day: mean (or last) funding rate + mean mark price.
    ts = UTC midnight of each day.

    This is the merge-ready format for 1d OHLCV strategies.
    No forward-fill: missing days stay NaN.

    Args:
        df: funding_rates table output (venue, symbol, ts, funding_rate, mark_price, anomaly_flag)
        agg_funding: 'mean' | 'last' | 'max' (daily aggregation method)
    """
    if df.empty:
        return df.copy()

    df = df.copy()
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    df = df.sort_values("ts")

    agg_map: dict[str, Any] = {
        "funding_rate": agg_funding,
        "mark_price": "last",
        "anomaly_flag": "any",
    }
    # Keep only numeric-ish cols
    existing_cols = {k: v for k, v in agg_map.items() if k in df.columns}

    # Group by venue + symbol + calendar day
    df["_day"] = df["ts"].dt.floor("D")
    grouped = df.groupby(["venue", "symbol", "_day"], as_index=False).agg(existing_cols)
    grouped = grouped.rename(columns={"_day": "ts"})
    # Normalize tz: groupby may drop or retain tz info depending on pandas version
    _ts = grouped["ts"]
    if not pd.api.types.is_datetime64_any_dtype(_ts):
        grouped["ts"] = pd.to_datetime(_ts, utc=True)
    elif _ts.dt.tz is None:
        grouped["ts"] = _ts.dt.tz_localize("UTC")
    else:
        grouped["ts"] = _ts.dt.tz_convert("UTC")

    # Rename for strategy clarity
    grouped = grouped.rename(columns={"funding_rate": "funding_rate_1d"})
    return grouped.sort_values(["symbol", "ts"]).reset_index(drop=True)
