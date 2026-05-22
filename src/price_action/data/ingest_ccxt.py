"""Binance + Bybit OHLCV ingest — ccxt unified API.

CLI:
    pa-ingest --venue binance --tf 1d --years 3 --symbols BTC/USDT,ETH/USDT
    pa-ingest                                 # tüm konfig defaults

Davranış:
    - Yoksa son N yıl backfill, varsa son `last_ts`'ten itibaren.
    - 500/1500 bar limitlerini paginate eder.
    - 429 hatasında exponential backoff.
    - DuckDB upsert + parquet write.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

import pandas as pd
import typer

from price_action.data.quality import run_quality_checks, write_daily_manifest
from price_action.data.store import OHLCVStore
from price_action.data.universe import build_universe
from price_action.logging_config import logger
from price_action.settings import get_settings

app = typer.Typer(add_completion=False, help="OHLCV ingest CLI")


_TF_MS: dict[str, int] = {
    "1m": 60_000,
    "5m": 5 * 60_000,
    "15m": 15 * 60_000,
    "1h": 60 * 60_000,
    "4h": 4 * 60 * 60_000,
    "1d": 24 * 60 * 60_000,
    "1w": 7 * 24 * 60 * 60_000,
}


@dataclass
class IngestStats:
    venue: str
    symbol: str
    timeframe: str
    rows_written: int
    fetched_pages: int
    error: str | None = None


def _to_utc_ms(dt: datetime) -> int:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


def _build_ccxt(venue: str, *, market_type: str = "future") -> Any:  # pragma: no cover - integration
    """ccxt exchange instance kur.

    DQ-04 FIX (SEC54.5): Futures endpoint zorunlu.
    Spot endpoint'e istek atılırsa funding_rate / oi / perp-specific
    fieldlar gelmiyor; liquidation threshold / tick_size hatalı olabilir.
    market_type="future" → defaultType=future (USDM perp).
    market_type="spot"   → geriye dönük compat (test ingest).
    """
    import ccxt

    if not hasattr(ccxt, venue):
        raise ValueError(f"ccxt: bilinmeyen venue {venue}")
    opts: dict = {"enableRateLimit": True}
    if market_type == "future":
        opts["options"] = {"defaultType": "future"}
    return getattr(ccxt, venue)(opts)


def _fetch_with_retry(
    exchange: Any,
    symbol: str,
    timeframe: str,
    since_ms: int,
    limit: int = 1000,
    *,
    max_retries: int = 5,
    base_backoff: float = 1.0,
) -> list[list[Any]]:  # pragma: no cover - integration
    """`fetch_ohlcv` rate-limit guard + exponential backoff."""
    attempt = 0
    while True:
        try:
            return exchange.fetch_ohlcv(symbol, timeframe=timeframe, since=since_ms, limit=limit)
        except Exception as exc:
            cls = exc.__class__.__name__.lower()
            transient = "ratelimit" in cls or "timeout" in cls or "ddos" in cls
            attempt += 1
            if attempt > max_retries or not transient:
                logger.bind(symbol=symbol, tf=timeframe, err=str(exc)).error("ingest.fetch_fail")
                raise
            delay = base_backoff * (2 ** (attempt - 1))
            logger.bind(symbol=symbol, tf=timeframe, attempt=attempt, delay=delay).warning(
                "ingest.backoff"
            )
            time.sleep(delay)


def _ohlcv_to_df(
    raw: Iterable[list[Any]],
    *,
    venue: str,
    symbol: str,
    timeframe: str,
) -> pd.DataFrame:
    rows = list(raw)
    if not rows:
        return pd.DataFrame(columns=["venue", "symbol", "timeframe", "ts", "open", "high", "low", "close", "volume"])
    df = pd.DataFrame(rows, columns=["ts_ms", "open", "high", "low", "close", "volume"])
    df["ts"] = pd.to_datetime(df["ts_ms"], unit="ms", utc=True)
    df["venue"] = venue
    df["symbol"] = symbol
    df["timeframe"] = timeframe
    return df[["venue", "symbol", "timeframe", "ts", "open", "high", "low", "close", "volume"]]


def ingest_symbol(
    *,
    venue: str,
    symbol: str,
    timeframe: str,
    years: int,
    store: OHLCVStore,
    exchange: Any | None = None,
    page_limit: int = 1000,
    sleep_between_pages_s: float = 0.0,
) -> IngestStats:  # pragma: no cover - integration heavy
    """Tek sembol/tek timeframe için backfill + incremental güncelle."""
    if timeframe not in _TF_MS:
        raise ValueError(f"Bilinmeyen timeframe: {timeframe}")
    if exchange is None:
        # DQ-04: futures endpoint (perp OHLCV, doğru tick/liq data)
        exchange = _build_ccxt(venue, market_type="future")

    last = store.last_ts(venue, symbol, timeframe)
    if last is not None:
        since = last + timedelta(milliseconds=_TF_MS[timeframe])
    else:
        since = datetime.now(timezone.utc) - timedelta(days=365 * years)
    since_ms = _to_utc_ms(since)

    pages = 0
    total_rows = 0
    error: str | None = None
    try:
        while True:
            raw = _fetch_with_retry(exchange, symbol, timeframe, since_ms, limit=page_limit)
            if not raw:
                break
            df = _ohlcv_to_df(raw, venue=venue, symbol=symbol, timeframe=timeframe)
            written = store.upsert(df)
            total_rows += written
            pages += 1
            last_ms = int(raw[-1][0])
            next_ms = last_ms + _TF_MS[timeframe]
            if next_ms <= since_ms:
                break
            since_ms = next_ms
            if len(raw) < page_limit:
                break
            if sleep_between_pages_s > 0:
                time.sleep(sleep_between_pages_s)
    except Exception as exc:
        error = str(exc)
        logger.bind(venue=venue, symbol=symbol, tf=timeframe, err=error).error("ingest.symbol_fail")

    return IngestStats(
        venue=venue,
        symbol=symbol,
        timeframe=timeframe,
        rows_written=total_rows,
        fetched_pages=pages,
        error=error,
    )


def _resolve_symbols(symbols_csv: str | None) -> list[tuple[str, str]]:
    """venue,symbol çiftlerini çöz. None → universe."""
    if symbols_csv:
        out: list[tuple[str, str]] = []
        for tok in symbols_csv.split(","):
            tok = tok.strip()
            if not tok:
                continue
            if ":" in tok:
                v, s = tok.split(":", 1)
                out.append((v.strip(), s.strip()))
            else:
                out.append(("binance", tok))
        return out
    instruments = build_universe()
    return [(i.venue, i.symbol) for i in instruments]


@app.command("run")
def run(
    venue: str = typer.Option("", "--venue", help="binance|bybit; boşsa universe."),
    tf: str = typer.Option("", "--tf", help="1d|1w; boşsa settings.timeframes_list."),
    years: int = typer.Option(0, "--years", help="0 → settings.pa_backtest_years"),
    symbols: str = typer.Option("", "--symbols", help="virgüllü; ör. 'BTC/USDT,ETH/USDT'"),
    quality_manifest: bool = typer.Option(True, "--quality-manifest/--no-quality-manifest"),
) -> None:  # pragma: no cover - CLI integration
    s = get_settings()
    venues = [venue] if venue else None
    timeframes = [tf] if tf else s.timeframes_list
    n_years = years or s.pa_backtest_years

    pairs = _resolve_symbols(symbols or None)
    if venues:
        pairs = [(v, sy) for (v, sy) in pairs if v in venues]
    store = OHLCVStore()

    reports = []
    for v, sy in pairs:
        for t in timeframes:
            stat = ingest_symbol(
                venue=v, symbol=sy, timeframe=t, years=n_years, store=store
            )
            logger.bind(**stat.__dict__).info("ingest.symbol_done")
            df = store.read(sy, t, venue=v)
            reports.append(run_quality_checks(df, venue=v, symbol=sy, timeframe=t))

    if quality_manifest and reports:
        write_daily_manifest(reports)


def main() -> None:  # pragma: no cover
    """Entry-point: pa-ingest."""
    app()


if __name__ == "__main__":  # pragma: no cover
    main()
