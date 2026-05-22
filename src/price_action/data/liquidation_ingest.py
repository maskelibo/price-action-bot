"""Liquidation data ingest — free data sources only.

## Data Availability Summary (researched 2026-05-09)

PAID (blocked):
  - CoinGlass: $29+/month, best historical coverage, 3yr liquidation aggregates
  - Tardis.dev: $200+/month, tick-level

FREE (partial):
  - OKX REST `/api/v5/public/liquidation-orders`: real-time/48h only, no historical depth
  - Bybit WebSocket `liquidation` topic: real-time only, no REST historical
  - Binance `forceOrders` REST: decommissioned (HTTP 400 "out of maintenance")
  - Binance data.binance.vision/liquidationSnapshot: S3 folder exists but is empty

SYNTHETIC PROXY (free, usable):
  - Binance `takerlongshortRatio`: taker buy/sell volume ratio (30d daily, 500h hourly)
  - Bybit/Binance open interest history: OI drops → proxy for forced closures
  - Combined: OI_drop + taker_sell_extreme = cascade proxy signal

This module implements:
  1. OKX real-time liquidation fetcher (for forward accumulation / paper trading)
  2. Synthetic cascade proxy (open interest + taker flow, for backtesting today)

CLI:
    pa-liq-ingest --mode okx-poll     # poll OKX and accumulate in DuckDB
    pa-liq-ingest --mode synthetic    # fetch and store synthetic proxy data
"""
from __future__ import annotations

import time
import threading
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator

import duckdb
import pandas as pd
import requests
import typer

from price_action.logging_config import logger
from price_action.settings import get_settings

app = typer.Typer(add_completion=False, help="Liquidation / cascade proxy ingest CLI")


# ---------------------------------------------------------------------------
# DDL
# ---------------------------------------------------------------------------

_OKX_LIQ_DDL = """
CREATE TABLE IF NOT EXISTS okx_liquidations (
    venue        VARCHAR NOT NULL DEFAULT 'okx',
    symbol       VARCHAR NOT NULL,
    side         VARCHAR NOT NULL,  -- 'buy' (short liq) | 'sell' (long liq)
    pos_side     VARCHAR NOT NULL,  -- 'long' | 'short'
    bk_price     DOUBLE NOT NULL,   -- bankruptcy price
    bk_loss      DOUBLE,
    size_contracts DOUBLE NOT NULL,
    ts           TIMESTAMP WITH TIME ZONE NOT NULL,
    fetched_at   TIMESTAMP WITH TIME ZONE NOT NULL,
    PRIMARY KEY (symbol, ts, bk_price, size_contracts)
);
"""

_PROXY_DDL = """
CREATE TABLE IF NOT EXISTS cascade_proxy (
    venue        VARCHAR NOT NULL,
    symbol       VARCHAR NOT NULL,
    period       VARCHAR NOT NULL DEFAULT '1d',
    ts           TIMESTAMP WITH TIME ZONE NOT NULL,
    open_interest   DOUBLE,         -- raw OI (contracts)
    oi_pct_change   DOUBLE,         -- 1-bar OI % change (negative = closures)
    taker_buy_vol   DOUBLE,
    taker_sell_vol  DOUBLE,
    taker_sell_ratio DOUBLE,        -- sell / (buy + sell), range [0,1]
    long_short_ratio DOUBLE,        -- L/S account ratio
    PRIMARY KEY (venue, symbol, period, ts)
);
"""


# ---------------------------------------------------------------------------
# Connection pool (thread-safe, same pattern as funding_ingest)
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


def reset_liq_pool() -> None:
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
# LiquidationStore — DuckDB persistence layer
# ---------------------------------------------------------------------------

class LiquidationStore:
    """Liquidation + cascade proxy DuckDB katmanı."""

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
            con.execute(_OKX_LIQ_DDL)
            con.execute(_PROXY_DDL)

    def upsert_okx(self, df: pd.DataFrame) -> int:
        """OKX liquidation rows — idempotent insert."""
        if df is None or df.empty:
            return 0
        required = ["symbol", "side", "pos_side", "bk_price", "size_contracts", "ts"]
        missing = [c for c in required if c not in df.columns]
        if missing:
            raise ValueError(f"okx_liquidations eksik kolon: {missing}")
        df = df.copy()
        if "venue" not in df.columns:
            df["venue"] = "okx"
        if "bk_loss" not in df.columns:
            df["bk_loss"] = float("nan")
        if "fetched_at" not in df.columns:
            df["fetched_at"] = pd.Timestamp.now(tz="UTC")
        for col in ("ts", "fetched_at"):
            if not pd.api.types.is_datetime64_any_dtype(df[col]):
                df[col] = pd.to_datetime(df[col], utc=True, errors="coerce")
            elif df[col].dt.tz is None:
                df[col] = df[col].dt.tz_localize("UTC")
        df = df.drop_duplicates(subset=["symbol", "ts", "bk_price", "size_contracts"], keep="last")
        df = df.dropna(subset=["ts", "bk_price", "size_contracts"])
        before = self._count_okx(df["symbol"].iloc[0] if len(df) > 0 else "")
        with self._conn() as con:
            con.register("okx_liq_staging", df)
            con.execute("BEGIN")
            try:
                con.execute("""
                    DELETE FROM okx_liquidations
                    USING okx_liq_staging s
                    WHERE okx_liquidations.symbol = s.symbol
                      AND okx_liquidations.ts = s.ts
                      AND okx_liquidations.bk_price = s.bk_price
                      AND okx_liquidations.size_contracts = s.size_contracts;
                """)
                con.execute("""
                    INSERT INTO okx_liquidations
                        (venue, symbol, side, pos_side, bk_price, bk_loss, size_contracts, ts, fetched_at)
                    SELECT venue, symbol, side, pos_side, bk_price, bk_loss, size_contracts, ts, fetched_at
                    FROM okx_liq_staging;
                """)
                con.execute("COMMIT")
            except Exception:
                con.execute("ROLLBACK")
                raise
            finally:
                con.unregister("okx_liq_staging")
        after = self._count_okx(df["symbol"].iloc[0] if len(df) > 0 else "")
        return after - before

    def _count_okx(self, symbol: str) -> int:
        try:
            with self._conn() as con:
                row = con.execute(
                    "SELECT COUNT(*) FROM okx_liquidations WHERE symbol=?", [symbol]
                ).fetchone()
            return int(row[0]) if row else 0
        except Exception:
            return 0

    def upsert_proxy(self, df: pd.DataFrame) -> int:
        """Cascade proxy rows — idempotent insert."""
        if df is None or df.empty:
            return 0
        required = ["venue", "symbol", "ts"]
        missing = [c for c in required if c not in df.columns]
        if missing:
            raise ValueError(f"cascade_proxy eksik kolon: {missing}")
        df = df.copy()
        if "period" not in df.columns:
            df["period"] = "1d"
        for col in ("ts",):
            if not pd.api.types.is_datetime64_any_dtype(df[col]):
                df[col] = pd.to_datetime(df[col], utc=True, errors="coerce")
            elif df[col].dt.tz is None:
                df[col] = df[col].dt.tz_localize("UTC")
        df = df.drop_duplicates(subset=["venue", "symbol", "period", "ts"], keep="last")
        df = df.dropna(subset=["ts"])
        cols = [c for c in [
            "venue", "symbol", "period", "ts",
            "open_interest", "oi_pct_change",
            "taker_buy_vol", "taker_sell_vol", "taker_sell_ratio",
            "long_short_ratio",
        ] if c in df.columns]
        df = df[cols]
        with self._conn() as con:
            con.register("proxy_staging", df)
            con.execute("BEGIN")
            try:
                con.execute("""
                    DELETE FROM cascade_proxy
                    USING proxy_staging s
                    WHERE cascade_proxy.venue = s.venue
                      AND cascade_proxy.symbol = s.symbol
                      AND cascade_proxy.period = s.period
                      AND cascade_proxy.ts = s.ts;
                """)
                con.execute(f"""
                    INSERT INTO cascade_proxy ({', '.join(cols)})
                    SELECT {', '.join(cols)} FROM proxy_staging;
                """)
                con.execute("COMMIT")
            except Exception:
                con.execute("ROLLBACK")
                raise
            finally:
                con.unregister("proxy_staging")
        return len(df)

    def read_proxy(self, symbol: str, *, period: str = "1d", venue: str = "binance") -> pd.DataFrame:
        """DuckDB'den cascade proxy oku."""
        try:
            with self._conn() as con:
                df = con.execute(
                    """
                    SELECT * FROM cascade_proxy
                    WHERE venue=? AND symbol=? AND period=?
                    ORDER BY ts ASC
                    """,
                    [venue, symbol, period],
                ).df()
            if "ts" in df.columns and not df.empty:
                df["ts"] = pd.to_datetime(df["ts"], utc=True)
            return df
        except Exception as exc:
            logger.warning("liq_store.read_proxy_fail", extra={"err": str(exc)[:200]})
            return pd.DataFrame()


# ---------------------------------------------------------------------------
# OKX Fetcher — real-time liquidations (48h rolling window)
# ---------------------------------------------------------------------------

OKX_LIQ_URL = "https://www.okx.com/api/v5/public/liquidation-orders"
OKX_SYMBOLS = {
    "BTC": "BTC-USDT",
    "ETH": "ETH-USDT",
}


def fetch_okx_liquidations(symbol_uly: str = "BTC-USDT") -> pd.DataFrame:
    """OKX'ten son ~48h liquidation event'lerini çek.

    Returns DataFrame with columns:
        symbol, side, pos_side, bk_price, bk_loss, size_contracts, ts

    Free API, no key. Only ~48h of history available.
    Suitable for: real-time accumulation, paper trading signal confirmation.
    NOT suitable for: historical backtesting (too short).
    """
    params = {
        "instType": "SWAP",
        "uly": symbol_uly,
        "state": "filled",
        "limit": "100",
    }
    try:
        resp = requests.get(OKX_LIQ_URL, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        logger.warning("okx_liq.fetch_fail", extra={"symbol": symbol_uly, "err": str(exc)[:200]})
        return pd.DataFrame()

    if data.get("code") != "0":
        logger.warning("okx_liq.api_error", extra={"code": data.get("code"), "msg": data.get("msg")})
        return pd.DataFrame()

    details_list = data.get("data", [])
    if not details_list:
        return pd.DataFrame()

    rows = []
    for entry in details_list:
        for detail in entry.get("details", []):
            rows.append({
                "symbol": symbol_uly,
                "side": detail.get("side", ""),
                "pos_side": detail.get("posSide", ""),
                "bk_price": float(detail.get("bkPx", 0)),
                "bk_loss": float(detail.get("bkLoss", 0) or 0),
                "size_contracts": float(detail.get("sz", 0)),
                "ts": pd.Timestamp(int(detail.get("ts", 0)), unit="ms", tz="UTC"),
            })

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)
    return df


# ---------------------------------------------------------------------------
# Synthetic Cascade Proxy — Binance free public data
# ---------------------------------------------------------------------------

BINANCE_FAPI = "https://fapi.binance.com"
BINANCE_PERIOD_MAP = {"1d": "1d", "1h": "1h"}
BINANCE_SYMBOLS = ["BTCUSDT", "ETHUSDT"]


def fetch_binance_taker_ratio(
    symbol: str = "BTCUSDT",
    period: str = "1d",
    limit: int = 30,
) -> pd.DataFrame:
    """Binance futures taker buy/sell volume ratio.

    Free, no auth. Returns up to 30 daily or 500 hourly bars.

    Fields: buySellRatio, buyVol, sellVol, timestamp
    """
    url = f"{BINANCE_FAPI}/futures/data/takerlongshortRatio"
    try:
        resp = requests.get(url, params={"symbol": symbol, "period": period, "limit": limit}, timeout=10)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        logger.warning("binance_taker.fetch_fail", extra={"symbol": symbol, "err": str(exc)[:200]})
        return pd.DataFrame()

    if not isinstance(data, list):
        return pd.DataFrame()

    rows = []
    for item in data:
        ts_ms = int(item.get("timestamp", 0))
        buy_vol = float(item.get("buyVol", 0))
        sell_vol = float(item.get("sellVol", 0))
        total_vol = buy_vol + sell_vol
        rows.append({
            "venue": "binance",
            "symbol": symbol,
            "period": period,
            "ts": pd.Timestamp(ts_ms, unit="ms", tz="UTC"),
            "taker_buy_vol": buy_vol,
            "taker_sell_vol": sell_vol,
            "taker_sell_ratio": sell_vol / total_vol if total_vol > 0 else float("nan"),
            "long_short_ratio": float(item.get("buySellRatio", float("nan"))),
        })

    return pd.DataFrame(rows) if rows else pd.DataFrame()


def fetch_binance_open_interest_history(
    symbol: str = "BTCUSDT",
    period: str = "1d",
    limit: int = 200,
) -> pd.DataFrame:
    """Bybit open interest history (free, up to 200 bars ~6.5 months 1d).

    Uses Bybit endpoint as Binance OI history API is more limited.
    Falls back to Binance for 1h (500 bars).

    Returns DataFrame with: venue, symbol, period, ts, open_interest
    """
    # Bybit has better OI history for daily (200 bars)
    if period == "1d":
        url = "https://api.bybit.com/v5/market/open-interest"
        bybit_sym = symbol.replace("USDT", "") + "USDT"  # BTCUSDT stays BTCUSDT
        params = {
            "category": "linear",
            "symbol": bybit_sym,
            "intervalTime": "1d",
            "limit": str(limit),
        }
        try:
            resp = requests.get(url, params=params, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            if data.get("retCode") == 0:
                rows = []
                for item in data["result"]["list"]:
                    rows.append({
                        "venue": "bybit",
                        "symbol": bybit_sym,
                        "period": period,
                        "ts": pd.Timestamp(int(item["timestamp"]), unit="ms", tz="UTC"),
                        "open_interest": float(item["openInterest"]),
                    })
                if rows:
                    df = pd.DataFrame(rows).sort_values("ts").reset_index(drop=True)
                    df["oi_pct_change"] = df["open_interest"].pct_change()
                    return df
        except Exception as exc:
            logger.warning("bybit_oi.fetch_fail", extra={"symbol": bybit_sym, "err": str(exc)[:200]})

    # Fallback: Binance hourly OI (limited to recent 500h)
    url = f"{BINANCE_FAPI}/futures/data/openInterestHist"
    try:
        resp = requests.get(
            url, params={"symbol": symbol, "period": period, "limit": str(limit)}, timeout=10
        )
        resp.raise_for_status()
        data = resp.json()
        if not isinstance(data, list):
            return pd.DataFrame()
        rows = []
        for item in data:
            rows.append({
                "venue": "binance",
                "symbol": symbol,
                "period": period,
                "ts": pd.Timestamp(int(item.get("timestamp", 0)), unit="ms", tz="UTC"),
                "open_interest": float(item.get("sumOpenInterest", 0)),
            })
        if not rows:
            return pd.DataFrame()
        df = pd.DataFrame(rows).sort_values("ts").reset_index(drop=True)
        df["oi_pct_change"] = df["open_interest"].pct_change()
        return df
    except Exception as exc:
        logger.warning("binance_oi.fetch_fail", extra={"symbol": symbol, "err": str(exc)[:200]})
        return pd.DataFrame()


def build_cascade_proxy(
    symbol_binance: str = "BTCUSDT",
    period: str = "1d",
    limit: int = 200,
) -> pd.DataFrame:
    """OI + taker flow verilerini birleştirerek cascade proxy sinyali üret.

    Cascade proxy definition:
        cascade_long = oi_pct_change < -oi_drop_threshold AND taker_sell_ratio > sell_ratio_threshold
        → proxy for long liquidation cascade (OI drops + sellers dominate)
        cascade_short = oi_pct_change > +oi_drop_threshold AND taker_buy_ratio > buy_ratio_threshold
        → proxy for short liquidation cascade (OI drops + buyers dominate)

    Bu fonksiyon sadece veriyi birleştirir. Threshold uygulaması strategy katmanında yapılır.
    """
    oi_df = fetch_binance_open_interest_history(symbol_binance, period=period, limit=limit)
    taker_df = fetch_binance_taker_ratio(symbol_binance, period=period, limit=30 if period == "1d" else 500)

    if oi_df.empty and taker_df.empty:
        return pd.DataFrame()

    if oi_df.empty:
        return taker_df

    if taker_df.empty:
        return oi_df

    # Merge on nearest timestamp (both are period-aligned)
    oi_df = oi_df.sort_values("ts").reset_index(drop=True)
    taker_df = taker_df.sort_values("ts").reset_index(drop=True)

    # Use taker_df as base (shorter history), merge OI
    merged = pd.merge_asof(
        taker_df.sort_values("ts"),
        oi_df[["ts", "open_interest", "oi_pct_change"]].sort_values("ts"),
        on="ts",
        direction="nearest",
        tolerance=pd.Timedelta("2D" if period == "1d" else "2h"),
    )
    merged = merged.sort_values("ts").reset_index(drop=True)
    return merged


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

@app.command("run")
def run(
    mode: str = typer.Option(
        "synthetic",
        "--mode",
        help="okx-poll | synthetic",
    ),
    symbols: str = typer.Option(
        "BTCUSDT,ETHUSDT",
        "--symbols",
        help="Binance-format symbol listesi.",
    ),
    period: str = typer.Option("1d", "--period", help="1d | 1h"),
    limit: int = typer.Option(200, "--limit", help="History bars to fetch (max per exchange)."),
) -> None:  # pragma: no cover - CLI integration
    store = LiquidationStore()
    sym_list = [s.strip() for s in symbols.split(",") if s.strip()]

    if mode == "okx-poll":
        for sym in sym_list:
            okx_uly = sym.replace("USDT", "") + "-USDT"
            df = fetch_okx_liquidations(okx_uly)
            if df.empty:
                logger.info("liq_ingest.okx.empty", extra={"symbol": okx_uly})
                continue
            written = store.upsert_okx(df)
            logger.info("liq_ingest.okx.done", extra={"symbol": okx_uly, "rows": written})

    elif mode == "synthetic":
        for sym in sym_list:
            df = build_cascade_proxy(sym, period=period, limit=limit)
            if df.empty:
                logger.info("liq_ingest.proxy.empty", extra={"symbol": sym})
                continue
            written = store.upsert_proxy(df)
            logger.info("liq_ingest.proxy.done", extra={"symbol": sym, "rows": written})

    else:
        raise typer.BadParameter(f"Bilinmeyen mod: {mode}. Geçerli: okx-poll, synthetic")


def main() -> None:  # pragma: no cover
    """Entry-point: pa-liq-ingest."""
    app()


if __name__ == "__main__":  # pragma: no cover
    main()
