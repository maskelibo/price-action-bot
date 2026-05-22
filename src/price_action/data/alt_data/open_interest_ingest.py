"""Open interest ingest — dedicated alt-data module.

Binance Futures + Bybit'ten günlük open interest history çeker.
data/open_interest.duckdb (market.duckdb ve funding_rates.duckdb'den bağımsız).

Schema:
    open_interest(venue, symbol, ts, oi_contracts, oi_usd, oi_pct_change,
                  oi_z_30d, anomaly_flag)
    PRIMARY KEY (venue, symbol, ts)

API kaynakları (öncelik sırasına göre):
  1. Bybit v5 /market/open-interest (200 daily bars, ~6.5 ay)
  2. Binance Futures /futures/data/openInterestHist (500 hourly bars, ~21 gün 1h)
     NOT: Binance'in tarihsel günlük OI API'si 2023+ sonrası kısıtlandı.
          Bybit primary kaynak, Binance fallback.

Limit gerçeği:
  - Bybit: 200 bars × 1d → ~6.5 ay. 5y backfill mümkün DEĞİL (ücretsiz API kısıtı).
  - Binance openInterestHist: daily period ile ~30 bar (belgelenmemiş limit).
  - Gerçek 5y OI tarihsel veri: Tardis.dev ($$$) veya Coinglass Pro gerektirir.
  - Bu modül mevcut maksimum ücretsiz geçmişi toplar; gap yüzeyler, sessizce doldurmaz.

Kısıtlar (Data Engineer Hard Limits):
  - No forward-fill — eksik günler NaN olarak kalır
  - No clip / winsorize — anomali işaretlenir, ham veri korunur
  - No timezone juggling — tüm ts UTC
  - Idempotent upsert

Anomali eşiği:
  - OI günlük değişim > %50 → anomaly_flag=True (işaretle, dahil et)
  - Z-score hesabı: 30-gün rolling (backtest'te kullanılabilir)
"""
from __future__ import annotations

import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Iterator

import duckdb
import numpy as np
import pandas as pd
import requests

from price_action.logging_config import logger
from price_action.settings import ROOT_DIR

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

ALT_DATA_DB_OI = ROOT_DIR / "data" / "open_interest.duckdb"

BINANCE_FAPI = "https://fapi.binance.com"
BYBIT_API = "https://api.bybit.com"

# Anomaly threshold: >50% OI change in one day
OI_ANOMALY_CHANGE_PCT: float = 0.50

# Universe (Binance perp format)
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

_DDL = """
CREATE TABLE IF NOT EXISTS open_interest (
    venue          VARCHAR NOT NULL,
    symbol         VARCHAR NOT NULL,
    ts             TIMESTAMP WITH TIME ZONE NOT NULL,
    oi_contracts   DOUBLE,
    oi_usd         DOUBLE,
    oi_pct_change  DOUBLE,
    oi_z_30d       DOUBLE,
    anomaly_flag   BOOLEAN DEFAULT FALSE,
    PRIMARY KEY (venue, symbol, ts)
);
CREATE INDEX IF NOT EXISTS idx_oi_sym_ts
    ON open_interest (symbol, ts);
"""

# ---------------------------------------------------------------------------
# Connection pool
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
# OIStore
# ---------------------------------------------------------------------------

class OIStore:
    """Open interest DuckDB katmanı."""

    def __init__(self, db_path=None) -> None:
        from pathlib import Path
        self.db_path = Path(db_path) if db_path else ALT_DATA_DB_OI
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

    def last_ts(self, venue: str, symbol: str) -> datetime | None:
        try:
            with self._conn() as con:
                row = con.execute(
                    "SELECT MAX(ts) FROM open_interest WHERE venue=? AND symbol=?",
                    [venue, symbol],
                ).fetchone()
        except Exception as exc:
            logger.warning("oi_store.last_ts_fail", extra={"symbol": symbol, "err": str(exc)[:120]})
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
        venue: str = "bybit",
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> pd.DataFrame:
        """OI oku. ts ascending sıralı."""
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
            f"SELECT venue, symbol, ts, oi_contracts, oi_usd, oi_pct_change, oi_z_30d, anomaly_flag "
            f"FROM open_interest WHERE {where} ORDER BY ts ASC"
        )
        with self._conn() as con:
            df = con.execute(sql, params).df()
        if df.empty:
            return df
        df["ts"] = pd.to_datetime(df["ts"], utc=True)
        return df

    def row_count(self) -> dict[str, int]:
        """Her (venue, symbol) için satır sayısı."""
        with self._conn() as con:
            rows = con.execute(
                "SELECT venue, symbol, COUNT(*) FROM open_interest GROUP BY venue, symbol ORDER BY symbol"
            ).fetchall()
        return {f"{r[0]}/{r[1]}": int(r[2]) for r in rows}

    def gap_summary(self, symbol: str, venue: str = "bybit") -> dict[str, Any]:
        """Gap analizi: beklenen vs mevcut günlük bar sayısı."""
        with self._conn() as con:
            row = con.execute(
                "SELECT MIN(ts), MAX(ts), COUNT(*) FROM open_interest WHERE venue=? AND symbol=?",
                [venue, symbol],
            ).fetchone()
        if not row or row[0] is None:
            return {"symbol": symbol, "venue": venue, "status": "empty"}
        min_ts, max_ts, count = row
        if isinstance(min_ts, datetime) and min_ts.tzinfo is None:
            min_ts = min_ts.replace(tzinfo=timezone.utc)
        if isinstance(max_ts, datetime) and max_ts.tzinfo is None:
            max_ts = max_ts.replace(tzinfo=timezone.utc)
        span_d = (max_ts - min_ts).days + 1
        gaps = max(0, span_d - count)
        return {
            "symbol": symbol,
            "venue": venue,
            "min_ts": min_ts.isoformat(),
            "max_ts": max_ts.isoformat(),
            "rows": count,
            "expected_bars": span_d,
            "gap_count": gaps,
            "gap_pct": round(gaps / span_d * 100, 3) if span_d > 0 else 0.0,
        }

    def anomaly_count(self, symbol: str, venue: str = "bybit") -> int:
        with self._conn() as con:
            row = con.execute(
                "SELECT COUNT(*) FROM open_interest WHERE venue=? AND symbol=? AND anomaly_flag=TRUE",
                [venue, symbol],
            ).fetchone()
        return int(row[0]) if row else 0

    def upsert(self, df: pd.DataFrame) -> int:
        """OI satırlarını idempotent upsert yap.

        Ön-hesaplama: oi_pct_change, oi_z_30d, anomaly_flag sıraya göre.
        No forward-fill, no clip.
        """
        if df is None or df.empty:
            return 0
        required = ["venue", "symbol", "ts"]
        missing = [c for c in required if c not in df.columns]
        if missing:
            raise ValueError(f"oi_store.upsert: eksik kolonlar: {missing}")

        df = df.copy()

        # UTC normalize
        if not pd.api.types.is_datetime64_any_dtype(df["ts"]):
            df["ts"] = pd.to_datetime(df["ts"], utc=True, errors="coerce")
        elif df["ts"].dt.tz is None:
            df["ts"] = df["ts"].dt.tz_localize("UTC")
        else:
            df["ts"] = df["ts"].dt.tz_convert("UTC")

        # Numeric coerce (no clip)
        for col in ("oi_contracts", "oi_usd"):
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")

        # oi_pct_change: compute if not present
        if "oi_pct_change" not in df.columns and "oi_contracts" in df.columns:
            df = df.sort_values("ts")
            df["oi_pct_change"] = df.groupby(["venue", "symbol"])["oi_contracts"].pct_change()
        elif "oi_pct_change" in df.columns:
            df["oi_pct_change"] = pd.to_numeric(df["oi_pct_change"], errors="coerce")

        # oi_z_30d: rolling 30-day z-score of oi_contracts (lookahead-free: shift(1))
        if "oi_z_30d" not in df.columns and "oi_contracts" in df.columns:
            df = df.sort_values("ts")
            # Vectorized per-group rolling z-score
            z_parts = []
            for _, grp in df.groupby(["venue", "symbol"], sort=False):
                oi = grp["oi_contracts"]
                lagged = oi.shift(1)
                roll_mean = lagged.rolling(30, min_periods=5).mean()
                roll_std = lagged.rolling(30, min_periods=5).std(ddof=0).replace(0.0, float("nan"))
                z = (oi - roll_mean) / roll_std
                z_parts.append(z)
            if z_parts:
                df["oi_z_30d"] = pd.concat(z_parts).reindex(df.index)
            else:
                df["oi_z_30d"] = float("nan")
        elif "oi_z_30d" not in df.columns:
            df["oi_z_30d"] = float("nan")

        # Anomaly flag: daily OI change > 50% (surface, don't fix)
        if "oi_pct_change" in df.columns:
            df["anomaly_flag"] = (df["oi_pct_change"].abs() > OI_ANOMALY_CHANGE_PCT).fillna(False)
        else:
            df["anomaly_flag"] = False

        if "oi_usd" not in df.columns:
            df["oi_usd"] = float("nan")

        df = df.drop_duplicates(subset=["venue", "symbol", "ts"], keep="last")
        df = df.dropna(subset=["ts"])

        cols = ["venue", "symbol", "ts", "oi_contracts", "oi_usd",
                "oi_pct_change", "oi_z_30d", "anomaly_flag"]
        cols = [c for c in cols if c in df.columns]
        df = df[cols]

        with self._conn() as con:
            con.register("oi_staging", df)
            con.execute("BEGIN")
            try:
                con.execute("""
                    DELETE FROM open_interest
                    USING oi_staging s
                    WHERE open_interest.venue = s.venue
                      AND open_interest.symbol = s.symbol
                      AND open_interest.ts = s.ts;
                """)
                con.execute(f"""
                    INSERT INTO open_interest ({', '.join(cols)})
                    SELECT {', '.join(cols)} FROM oi_staging;
                """)
                con.execute("COMMIT")
            except Exception:
                con.execute("ROLLBACK")
                raise
            finally:
                con.unregister("oi_staging")

        n = len(df)
        logger.bind(rows=n).info("oi_store.upsert")
        return n


# ---------------------------------------------------------------------------
# Fetchers
# ---------------------------------------------------------------------------

def _get_with_retry(
    url: str,
    params: dict,
    *,
    max_retries: int = 4,
    base_backoff: float = 1.0,
    timeout: int = 15,
) -> dict | list | None:
    """HTTP GET + exponential backoff. Returns parsed JSON or None on permanent fail."""
    attempt = 0
    while True:
        try:
            resp = requests.get(url, params=params, timeout=timeout)
            if resp.status_code == 429:
                raise requests.exceptions.HTTPError("429 rate limit")
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:
            attempt += 1
            cls = exc.__class__.__name__.lower()
            transient = any(k in cls for k in ("timeout", "connection", "httperror")) or "429" in str(exc)
            if attempt > max_retries or not transient:
                logger.warning("oi_fetch.fail", extra={"url": url, "err": str(exc)[:200]})
                return None
            delay = base_backoff * (2 ** (attempt - 1))
            logger.warning("oi_fetch.backoff", extra={"attempt": attempt, "delay": delay})
            time.sleep(delay)


def fetch_bybit_oi(
    symbol: str = "BTCUSDT",
    *,
    interval: str = "1d",
    limit: int = 200,
    end_ts_ms: int | None = None,
) -> pd.DataFrame:
    """Bybit v5 open interest history.

    Free: max 200 bars per call (1d → ~6.5 months).
    Supports pagination via end_ts_ms (cursor-based).

    Returns DataFrame: venue, symbol, ts (UTC), oi_contracts
    """
    url = f"{BYBIT_API}/v5/market/open-interest"
    params: dict[str, Any] = {
        "category": "linear",
        "symbol": symbol,
        "intervalTime": interval,
        "limit": str(limit),
    }
    if end_ts_ms:
        params["endTime"] = str(end_ts_ms)

    data = _get_with_retry(url, params)
    if data is None or data.get("retCode") != 0:
        logger.warning("bybit_oi.api_error", extra={"symbol": symbol, "data": str(data)[:200]})
        return pd.DataFrame()

    items = data.get("result", {}).get("list", [])
    if not items:
        return pd.DataFrame()

    rows = []
    for item in items:
        ts_ms = int(item.get("timestamp", 0))
        oi = float(item.get("openInterest", float("nan")))
        rows.append({
            "venue": "bybit",
            "symbol": symbol,
            "ts": pd.Timestamp(ts_ms, unit="ms", tz="UTC"),
            "oi_contracts": oi,
            "oi_usd": float("nan"),  # Bybit OI in contracts, not USD
        })

    df = pd.DataFrame(rows).sort_values("ts").reset_index(drop=True)
    return df


def fetch_bybit_oi_paginated(
    symbol: str = "BTCUSDT",
    *,
    start_dt: datetime | None = None,
    years: int = 5,
    interval: str = "1d",
    page_limit: int = 200,
    sleep_between: float = 0.5,
) -> pd.DataFrame:
    """Bybit OI history maksimum geriye dönük çek (pagination ile).

    Bybit 200-bar limiti nedeniyle cursor paginasyonu:
    Her sayfa için bir öncekinin en eski ts'ini endTime olarak kullan.

    Gerçek limit:
      Bybit'in ücretsiz historical OI kaydı genellikle 2021 ortasına kadar iner.
      Sembol başlatma tarihi öncesine gidemez.
    """
    if start_dt is None:
        start_dt = datetime.now(timezone.utc) - timedelta(days=365 * years)

    all_dfs: list[pd.DataFrame] = []
    end_ts_ms: int | None = None  # start from now, paginate backward

    while True:
        df = fetch_bybit_oi(symbol, interval=interval, limit=page_limit, end_ts_ms=end_ts_ms)
        if df.empty:
            break

        all_dfs.append(df)

        oldest_ts = df["ts"].min()
        if oldest_ts <= pd.Timestamp(start_dt, tz="UTC"):
            break

        # Next page cursor: end at oldest ts from this page minus 1ms
        end_ts_ms = int(oldest_ts.timestamp() * 1000) - 1
        time.sleep(sleep_between)

    if not all_dfs:
        return pd.DataFrame()

    combined = pd.concat(all_dfs, ignore_index=True)
    combined = combined.drop_duplicates("ts").sort_values("ts").reset_index(drop=True)
    # Filter to requested start date
    combined = combined[combined["ts"] >= pd.Timestamp(start_dt, tz="UTC")]
    return combined


def fetch_binance_oi_daily(
    symbol: str = "BTCUSDT",
    *,
    limit: int = 30,
) -> pd.DataFrame:
    """Binance Futures openInterestHist (daily period, ~30 bar free).

    Binance'in tarihsel günlük OI endpoint'i 2023 sonrası kısıtlı.
    Fallback olarak kullanılır. Bybit primary tercih edilir.
    """
    url = f"{BINANCE_FAPI}/futures/data/openInterestHist"
    params = {"symbol": symbol, "period": "1d", "limit": str(limit)}
    data = _get_with_retry(url, params)
    if data is None or not isinstance(data, list):
        return pd.DataFrame()

    rows = []
    for item in data:
        ts_ms = int(item.get("timestamp", 0))
        oi_contracts = float(item.get("sumOpenInterest", float("nan")))
        oi_usd = float(item.get("sumOpenInterestValue", float("nan")))
        rows.append({
            "venue": "binance",
            "symbol": symbol,
            "ts": pd.Timestamp(ts_ms, unit="ms", tz="UTC"),
            "oi_contracts": oi_contracts,
            "oi_usd": oi_usd,
        })

    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows).sort_values("ts").reset_index(drop=True)
    return df


# ---------------------------------------------------------------------------
# Ingest function
# ---------------------------------------------------------------------------

@dataclass
class OIIngestStats:
    symbol: str
    venue: str
    rows_written: int = 0
    date_start: str = ""
    date_end: str = ""
    gap_count: int = 0
    gap_pct: float = 0.0
    anomaly_count: int = 0
    source: str = "bybit"
    error: str | None = None
    note: str = ""


def ingest_symbol_oi(
    *,
    symbol: str,
    years: int = 5,
    store: OIStore,
    sleep_between_pages: float = 0.5,
) -> OIIngestStats:  # pragma: no cover
    """Tek sembol için OI backfill + incremental update.

    Primary: Bybit (200-bar pages, ~6.5 ay per page, paginated).
    Fallback: Binance (~30 son gün).

    5 yıl hedef: Bybit ücretsiz API genellikle 2021'e kadar iner (3-4 yıl).
    Eksik geçmiş için not eklenir, sessizce NaN bırakılır.
    """
    stats = OIIngestStats(symbol=symbol, venue="bybit")

    try:
        start_dt = datetime.now(timezone.utc) - timedelta(days=365 * years)
        last = store.last_ts("bybit", symbol)
        if last is not None:
            # Incremental: sadece eksik günleri çek
            start_dt = last + timedelta(days=1)

        df_bybit = fetch_bybit_oi_paginated(
            symbol, start_dt=start_dt, years=years, sleep_between=sleep_between_pages
        )

        if not df_bybit.empty:
            written = store.upsert(df_bybit)
            stats.rows_written += written
            stats.source = "bybit"
        else:
            # Bybit başarısız → Binance fallback (sadece son ~30 gün)
            logger.warning("oi_ingest.bybit_empty.binance_fallback", extra={"symbol": symbol})
            df_bin = fetch_binance_oi_daily(symbol, limit=30)
            if not df_bin.empty:
                written = store.upsert(df_bin)
                stats.rows_written += written
                stats.source = "binance_fallback"
                stats.note = "Bybit empty; Binance fallback (~30d only)"
            else:
                stats.note = "Both sources empty"

        # Post-ingest stats
        gap_info = store.gap_summary(symbol, venue=stats.source if stats.source != "binance_fallback" else "bybit")
        stats.gap_count = gap_info.get("gap_count", 0)
        stats.gap_pct = gap_info.get("gap_pct", 0.0)
        stats.date_start = gap_info.get("min_ts", "")
        stats.date_end = gap_info.get("max_ts", "")
        stats.anomaly_count = store.anomaly_count(symbol, venue="bybit" if "bybit" in stats.source else "binance")

        # Warn if significant gap coverage (surface don't fix)
        if stats.gap_pct > 5.0:
            logger.warning(
                "oi_ingest.gap_warning",
                extra={"symbol": symbol, "gap_pct": stats.gap_pct,
                       "note": "Free API limit; paid data (Tardis/Coinglass) needed for 5y coverage"},
            )

    except Exception as exc:
        stats.error = str(exc)[:300]
        logger.bind(symbol=symbol, err=stats.error).error("oi_ingest.symbol_fail")

    return stats


def run_universe_ingest(
    *,
    symbols: list[str] | None = None,
    years: int = 5,
    db_path=None,
    sleep_between_symbols: float = 1.0,
) -> list[OIIngestStats]:  # pragma: no cover
    """Tüm universe için OI backfill."""
    sym_list = symbols or UNIVERSE_SYMBOLS
    store = OIStore(db_path)
    results: list[OIIngestStats] = []

    for sym in sym_list:
        logger.bind(symbol=sym).info("oi_ingest.start")
        stats = ingest_symbol_oi(symbol=sym, years=years, store=store)
        results.append(stats)
        logger.bind(
            symbol=sym,
            rows=stats.rows_written,
            gaps=stats.gap_count,
            gap_pct=stats.gap_pct,
            source=stats.source,
            error=stats.error,
        ).info("oi_ingest.done")
        if sleep_between_symbols > 0:
            time.sleep(sleep_between_symbols)

    return results
