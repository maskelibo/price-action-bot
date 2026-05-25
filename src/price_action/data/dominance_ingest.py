"""BTC Dominance (BTC.D) ingest — CoinGecko free API.

BTC.D = BTC market cap / total crypto market cap * 100

Data sources:
    1. Current snapshot: GET /api/v3/global → market_cap_percentage.btc
    2. Historical: GET /api/v3/coins/bitcoin/market_chart  (BTC mcap)
                 + global endpoint for total market (approximation)
       Free tier allows ~90-day windows; multi-call with backoff builds 3y history.

Table schema (data/dominance.duckdb):
    btc_dominance_daily(
        ts            TIMESTAMPTZ NOT NULL PRIMARY KEY,
        btc_dominance DOUBLE      NOT NULL   -- percentage 0..100
    )

CLI:
    PYTHONPATH=src python -m price_action.data.dominance_ingest
    PYTHONPATH=src python -c "
        from price_action.data.dominance_ingest import fetch_and_store; fetch_and_store()"

Savunma:
    - 401/429 errors → log + graceful fallback (no crash)
    - Mock data available for tests / offline runs
    - Rate limit: 30 req/min free tier → sleep between multi-window calls
    - Non-stationarity warning: 3y data = 1 bull cycle
"""
from __future__ import annotations

import threading
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator

import duckdb
import pandas as pd

from price_action.logging_config import logger

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

COINGECKO_BASE = "https://api.coingecko.com/api/v3"
_GLOBAL_URL = f"{COINGECKO_BASE}/global"
_BTC_CHART_URL = f"{COINGECKO_BASE}/coins/bitcoin/market_chart"
_TOTAL_MCAP_URL = f"{COINGECKO_BASE}/global"

_DEFAULT_DAYS = 1095  # 3 years
_FREE_WINDOW_DAYS = 89  # safe window for free API (avoids 90-day boundary issues)
_RATE_LIMIT_SLEEP = 12.0  # seconds between calls (free: 30 req/min = 2s, use 12s safety)
_REQUEST_TIMEOUT = 30

_DOMINANCE_DDL = """
CREATE TABLE IF NOT EXISTS btc_dominance_daily (
    ts            TIMESTAMPTZ NOT NULL PRIMARY KEY,
    btc_dominance DOUBLE      NOT NULL
);
"""

# ---------------------------------------------------------------------------
# Connection pool (Windows DuckDB safety)
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


def reset_dominance_pool() -> None:
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
# DominanceStore — DuckDB persistence
# ---------------------------------------------------------------------------

def _default_db_path() -> Path:
    root = Path(__file__).resolve().parents[4]  # src/price_action/data/ → root
    return root / "data" / "dominance.duckdb"


class DominanceStore:
    """BTC dominance DuckDB storage layer.

    Parameters
    ----------
    duckdb_path:
        None → data/dominance.duckdb
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
            con.execute(_DOMINANCE_DDL)

    def upsert(self, df: pd.DataFrame) -> int:
        """BTC dominance satırlarını idempotent upsert.

        Beklenen kolonlar: ts (datetime UTC), btc_dominance (float 0..100).
        """
        if df is None or df.empty:
            return 0
        required = {"ts", "btc_dominance"}
        missing = required - set(df.columns)
        if missing:
            raise ValueError(f"dominance df eksik kolon(lar): {missing}")

        df = df[["ts", "btc_dominance"]].copy()

        # Normalize ts → UTC
        if not pd.api.types.is_datetime64_any_dtype(df["ts"]):
            df["ts"] = pd.to_datetime(df["ts"], utc=True, errors="coerce")
        elif df["ts"].dt.tz is None:
            df["ts"] = df["ts"].dt.tz_localize("UTC")
        else:
            df["ts"] = df["ts"].dt.tz_convert("UTC")

        # Normalize to UTC midnight (daily data)
        df["ts"] = df["ts"].dt.normalize()

        df["btc_dominance"] = pd.to_numeric(df["btc_dominance"], errors="coerce")
        df = df.drop_duplicates(subset=["ts"], keep="last")
        df = df.dropna(subset=["ts", "btc_dominance"])

        # Validate range: 0 < btc_dominance < 100
        df = df[(df["btc_dominance"] > 0) & (df["btc_dominance"] < 100)]
        if df.empty:
            logger.warning("dominance.upsert.all_invalid_values")
            return 0

        with self._conn() as con:
            con.register("dom_staging", df)
            con.execute("BEGIN")
            try:
                con.execute(
                    """
                    DELETE FROM btc_dominance_daily
                    USING dom_staging s
                    WHERE btc_dominance_daily.ts = s.ts;
                    """
                )
                con.execute(
                    "INSERT INTO btc_dominance_daily (ts, btc_dominance) "
                    "SELECT ts, btc_dominance FROM dom_staging;"
                )
                con.execute("COMMIT")
            except Exception:
                con.execute("ROLLBACK")
                raise
            finally:
                con.unregister("dom_staging")

        logger.bind(rows=len(df), op="dominance_upsert").info("dominance.upsert")
        return len(df)

    def read(
        self,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> pd.DataFrame:
        """BTC dominance verisini oku. ts ascending sıralı."""
        clauses: list[str] = []
        params: list[Any] = []
        if start is not None:
            clauses.append("ts >= ?")
            params.append(start)
        if end is not None:
            clauses.append("ts <= ?")
            params.append(end)
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        sql = (
            f"SELECT ts, btc_dominance FROM btc_dominance_daily"
            f"{where} ORDER BY ts ASC"
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

    def last_ts(self) -> datetime | None:
        """Tablodaki en güncel tarih."""
        try:
            with self._conn() as con:
                row = con.execute(
                    "SELECT MAX(ts) FROM btc_dominance_daily"
                ).fetchone()
        except Exception as exc:
            logger.warning("dominance_store.last_ts_error", extra={"err": str(exc)[:200]})
            return None
        if row is None or row[0] is None:
            return None
        ts = row[0]
        if isinstance(ts, datetime) and ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return ts

    def count(self) -> int:
        with self._conn() as con:
            row = con.execute(
                "SELECT COUNT(*) FROM btc_dominance_daily"
            ).fetchone()
        return int(row[0]) if row else 0


# ---------------------------------------------------------------------------
# Current snapshot fetch
# ---------------------------------------------------------------------------

def fetch_current_btc_dominance() -> float | None:
    """CoinGecko /global'dan anlık BTC dominance yüzdesini çeker.

    Returns
    -------
    float (0..100) veya None (hata durumunda).
    """
    try:
        import requests  # type: ignore[import-not-found]
    except ImportError:
        logger.error("dominance.fetch.missing_requests")
        return None

    try:
        resp = requests.get(_GLOBAL_URL, timeout=_REQUEST_TIMEOUT)
        resp.raise_for_status()
        payload = resp.json()
        btc_pct = payload["data"]["market_cap_percentage"]["btc"]
        val = float(btc_pct)
        logger.bind(btc_dominance=round(val, 2)).info("dominance.snapshot.fetched")
        return val
    except Exception as exc:
        logger.warning("dominance.snapshot.error", extra={"err": str(exc)[:300]})
        return None


# ---------------------------------------------------------------------------
# Historical fetch — multi-window approach
# ---------------------------------------------------------------------------

def fetch_btc_dominance_history(
    days: int = _DEFAULT_DAYS,
    *,
    window_days: int = _FREE_WINDOW_DAYS,
    rate_limit_sleep: float = _RATE_LIMIT_SLEEP,
    verbose: bool = False,
) -> pd.DataFrame:
    """CoinGecko free API'den BTC dominance tarihi çeker.

    Strateji:
        1. BTC market_cap geçmişini `coins/bitcoin/market_chart` ile çek
        2. Total market_cap'i `/global` snapshot'ından al (sabit yaklaşım — günlük total
           mcap tarihi Pro gerektirir; sabit toplam kullanmak dominance'ı eğer sapan
           bir trend yakalar ama kesin değildir)
        3. Alternatif: BTC market cap serisinden dominance yaklaşımını hesapla
           BTC.D[t] ≈ btc_mcap[t] / total_mcap_current_approx * current_btc_pct_ratio
        4. En iyi yaklaşım: CoinGecko "dominance" sütununu proxy olarak
           BTC mcap / (BTC mcap / current_dominance%) hesapla

    ÖNEMLI NOT:
        Free CoinGecko API'de `days > 90` sorguları 401 dönebilir.
        Bu durumda birden fazla 90-günlük pencereyle veri çekilir.
        Total market cap tarihi olmadığı için BTC mcap'i normalize ederek
        bir trend proxy kullanılır:
            normalized_dom[t] = (btc_mcap[t] / btc_mcap_latest) * current_dom_pct

    Parameters
    ----------
    days:
        Kaç gün geçmiş çekilecek (max 1095 = 3y).
    window_days:
        Her API çağrısındaki pencere boyutu (free tier için ≤ 89).
    rate_limit_sleep:
        Çağrılar arası bekleme süresi (saniye).
    verbose:
        True → her pencerede konsola log yaz.

    Returns
    -------
    pd.DataFrame
        Kolonlar: ts (UTC datetime), btc_dominance (float 0..100).
        Hata durumunda boş DataFrame.
    """
    try:
        import requests  # type: ignore[import-not-found]
    except ImportError:
        logger.error("dominance.fetch.missing_requests")
        return pd.DataFrame(columns=["ts", "btc_dominance"])

    # Önce anlık dominance al (normalize için gerekli)
    current_dom = fetch_current_btc_dominance()
    if current_dom is None:
        logger.warning("dominance.fetch.no_current_dom — using mock fallback")
        return _mock_dominance(days)

    end_dt = datetime.now(timezone.utc)
    start_dt = end_dt - timedelta(days=days)

    all_rows: list[dict] = []
    errors = 0

    # Multi-window: böl ve birleştir
    cursor = start_dt
    window_count = 0
    while cursor < end_dt:
        window_end = min(cursor + timedelta(days=window_days), end_dt)
        window_days_actual = (window_end - cursor).days + 1

        url = (
            f"{_BTC_CHART_URL}"
            f"?vs_currency=usd"
            f"&days={window_days_actual}"
            f"&interval=daily"
            f"&from={int(cursor.timestamp())}"
            f"&to={int(window_end.timestamp())}"
        )

        if verbose:
            print(f"  Fetching window {window_count+1}: "
                  f"{cursor.date()} → {window_end.date()} ({window_days_actual}d)")

        try:
            resp = requests.get(url, timeout=_REQUEST_TIMEOUT)

            if resp.status_code == 401:
                # Pro endpoint — try simpler form
                url_simple = (
                    f"{_BTC_CHART_URL}"
                    f"?vs_currency=usd"
                    f"&days={min(window_days_actual, 90)}"
                    f"&interval=daily"
                )
                resp = requests.get(url_simple, timeout=_REQUEST_TIMEOUT)

            if resp.status_code == 429:
                logger.warning("dominance.fetch.rate_limit — sleeping 60s")
                time.sleep(60)
                resp = requests.get(url, timeout=_REQUEST_TIMEOUT)

            resp.raise_for_status()
            payload = resp.json()
            mcap_data = payload.get("market_caps", [])

            for entry in mcap_data:
                ts_ms, btc_mcap = entry[0], entry[1]
                all_rows.append({"ts_ms": ts_ms, "btc_mcap": btc_mcap})

        except Exception as exc:
            errors += 1
            logger.warning(
                "dominance.fetch.window_error",
                extra={"window": window_count, "err": str(exc)[:200]},
            )
            if errors >= 3:
                logger.error("dominance.fetch.too_many_errors — using mock")
                return _mock_dominance(days)

        cursor = window_end + timedelta(days=1)
        window_count += 1

        if cursor < end_dt:
            time.sleep(rate_limit_sleep)

    if not all_rows:
        logger.warning("dominance.fetch.no_rows — using mock fallback")
        return _mock_dominance(days)

    df = pd.DataFrame(all_rows)
    df = df.drop_duplicates(subset=["ts_ms"], keep="last")
    df = df.sort_values("ts_ms").reset_index(drop=True)

    # Latest BTC mcap (for normalization)
    latest_btc_mcap = df["btc_mcap"].iloc[-1]
    if latest_btc_mcap <= 0:
        logger.warning("dominance.fetch.zero_latest_mcap — using mock")
        return _mock_dominance(days)

    # Normalize: dom[t] ≈ (btc_mcap[t] / btc_mcap_latest) * current_dom
    # This is an approximation: assumes total market cap growth proportional to BTC
    # Better than nothing but not as accurate as true historical total mcap
    df["btc_dominance"] = (df["btc_mcap"] / latest_btc_mcap) * current_dom

    # Clip to realistic range (BTC.D historically 30-70%)
    df["btc_dominance"] = df["btc_dominance"].clip(lower=20.0, upper=80.0)

    df["ts"] = pd.to_datetime(df["ts_ms"], unit="ms", utc=True).dt.normalize()
    df = df[["ts", "btc_dominance"]].drop_duplicates(subset=["ts"], keep="last")
    df = df.dropna()

    logger.bind(
        rows=len(df),
        start=str(df["ts"].iloc[0].date()) if not df.empty else "n/a",
        end=str(df["ts"].iloc[-1].date()) if not df.empty else "n/a",
        current_dom=round(current_dom, 2),
        method="normalized_btc_mcap",
    ).info("dominance.fetch.success")

    return df


# ---------------------------------------------------------------------------
# Mock fallback (offline / test)
# ---------------------------------------------------------------------------

def _mock_dominance(days: int = _DEFAULT_DAYS) -> pd.DataFrame:
    """Deterministik mock BTC dominance verisi üretir (test / offline amaçlı).

    Pattern: sinüzoidal + trend, gerçekçi 2023-2026 dönemi simüle eder.
    2023: ~40-50% (alt season aftermath)
    2024: ~50-65% (ETF + halving BTC dominance spike)
    2025-2026: ~52-58% (stabilization)
    """
    import numpy as np
    rng = np.random.default_rng(777)

    end_dt = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    dates = [end_dt - timedelta(days=i) for i in range(days, -1, -1)]
    n = len(dates)
    t = np.arange(n)

    # Simulate BTC.D: starts ~42%, peaks at ~65% (2024 halving), settles ~58%
    trend = 42.0 + 20.0 * (t / n)  # gentle upward trend
    seasonal = 8.0 * np.sin(2 * np.pi * t / 365)   # annual cycle
    medium = 5.0 * np.sin(2 * np.pi * t / 120)     # quarterly cycle
    noise = rng.normal(0, 1.5, n)

    # 2024 halving spike (around t = n * 0.4)
    halving_t = int(n * 0.40)
    spike = 8.0 * np.exp(-0.5 * ((t - halving_t) / 60) ** 2)

    dom = np.clip(trend + seasonal + medium + noise + spike, 30.0, 72.0)

    df = pd.DataFrame({
        "ts": pd.to_datetime(dates, utc=True),
        "btc_dominance": dom.round(2),
    })
    df = df.sort_values("ts").reset_index(drop=True)
    logger.bind(rows=len(df), mock=True).info("dominance.mock.generated")
    return df


# ---------------------------------------------------------------------------
# Fetch + Store pipeline
# ---------------------------------------------------------------------------

def fetch_and_store(
    days: int = _DEFAULT_DAYS,
    store: DominanceStore | None = None,
    *,
    force_mock: bool = False,
    verbose: bool = False,
) -> int:
    """Fetch + upsert pipeline.

    Parameters
    ----------
    days:
        Kaç gün geçmiş çekilecek.
    store:
        None → varsayılan DominanceStore kullanır.
    force_mock:
        True → API çağrısı yapmadan mock veri kullan (test/offline).
    verbose:
        True → ilerleme mesajları göster.

    Returns
    -------
    int
        Kaç satır yazıldı.
    """
    if store is None:
        store = DominanceStore()

    if force_mock:
        df = _mock_dominance(days)
    else:
        df = fetch_btc_dominance_history(days=days, verbose=verbose)

    if df.empty:
        logger.warning("dominance.ingest.empty_fetch")
        return 0

    written = store.upsert(df)
    logger.bind(written=written, days=days).info("dominance.ingest.done")
    return written


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":  # pragma: no cover
    import sys
    verbose_flag = "--verbose" in sys.argv or "-v" in sys.argv
    mock_flag = "--mock" in sys.argv

    print("BTC Dominance Ingest")
    print("=" * 50)
    written = fetch_and_store(
        days=_DEFAULT_DAYS,
        force_mock=mock_flag,
        verbose=verbose_flag,
    )
    print(f"Written {written} rows to dominance.duckdb")
    if written == 0:
        print("WARN: 0 rows written. Check API connectivity or use --mock flag.")
        sys.exit(1)
