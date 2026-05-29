"""15m Live Ingest — SEC54.5 (DQ-01).

Her 5 dakikada bir cron ile çalışır; sadece 15m optimize.
Son 10 bar refresh (incremental, idempotent upsert).

Cron (UTC):
    */5 * * * *  python scripts/ingest_15m_live.py

Davranış:
    - Binance USDM Futures (defaultType=future — DQ-04 FIX).
    - Bybit fallback: Binance başarısız olursa Bybit ile dener.
    - Her iki exchange de başarısız → fail loud (exit 1), sessizce devam etme.
    - NaN forward-fill YOK. Eksik bar NaN olarak kalır; downstream kararı.
    - Anomali işaretlenir, ham veri korunur (clip/winsorize YOK).
    - Parquet partition + DuckDB upsert idempotent.
    - Quality manifest güncellenir.

Hard limits (memory disciplin):
    ❌ Forward-fill etme
    ❌ Clip/winsorize
    ❌ Survivorship bias (delisted semboller silinmez)
    ❌ TZ karışıklığı (tüm ts UTC-aware)
"""
from __future__ import annotations

import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from price_action.data.quality import run_quality_checks, write_daily_manifest
from price_action.data.store import OHLCVStore
from price_action.logging_config import logger
from price_action.settings import get_settings

# ── Config ────────────────────────────────────────────────────────────────────

# 14 sembol — futures_trade_daily.py SYMBOLS ile aynı universe.
# 2026-05-29 (deploy): 10 → 14. ZEC/NEAR/FIL/XLM eklendi (config 14 sembol parity).
SYMBOLS: list[str] = [
    "BTC/USDT",
    "ETH/USDT",
    "SOL/USDT",
    "BNB/USDT",
    "ADA/USDT",
    "AVAX/USDT",
    "LINK/USDT",
    "DOT/USDT",
    "DOGE/USDT",
    "XRP/USDT",
    "ZEC/USDT",
    "NEAR/USDT",
    "FIL/USDT",
    "XLM/USDT",
]

TF = "15m"
TF_MS = 15 * 60 * 1000  # 15 dakika ms cinsinden
LOOKBACK_BARS = 10       # son 10 bar → 150 dakika pencere

# Venue priority: Binance önce, Bybit fallback
VENUE_PRIORITY = ["binance", "bybit"]

MAX_RETRIES = 5
BASE_BACKOFF_S = 1.0


# ── Exchange builder ───────────────────────────────────────────────────────────

def _build_exchange(venue: str) -> Any:  # pragma: no cover - integration
    """ccxt futures exchange instance.

    DQ-04: defaultType='future' → USDM perp endpoint.
    """
    import ccxt

    if not hasattr(ccxt, venue):
        raise ValueError(f"ccxt: bilinmeyen venue {venue!r}")
    return getattr(ccxt, venue)({
        "enableRateLimit": True,
        "options": {"defaultType": "future"},
    })


# ── Fetch with retry ──────────────────────────────────────────────────────────

def _fetch_ohlcv(
    exchange: Any,
    symbol: str,
    since_ms: int,
    limit: int,
) -> list[list[Any]]:  # pragma: no cover - integration
    attempt = 0
    while True:
        try:
            return exchange.fetch_ohlcv(symbol, timeframe=TF, since=since_ms, limit=limit)
        except Exception as exc:
            cls = exc.__class__.__name__.lower()
            transient = any(k in cls for k in ("ratelimit", "timeout", "ddos", "network"))
            attempt += 1
            if attempt > MAX_RETRIES or not transient:
                raise
            delay = BASE_BACKOFF_S * (2 ** (attempt - 1))
            logger.bind(symbol=symbol, tf=TF, attempt=attempt, delay=delay).warning(
                "ingest15m.backoff"
            )
            time.sleep(delay)


# ── Ingest single symbol ───────────────────────────────────────────────────────

def ingest_symbol_15m(
    symbol: str,
    store: OHLCVStore,
    exchange: Any,
    venue: str,
) -> int:  # pragma: no cover - integration
    """Son LOOKBACK_BARS bar'ı çek, idempotent upsert.

    Dönen değer: yazılan satır sayısı.
    NaN bırakma politikası:
        - raw[i] tamamen None ise (exchange boş bar dönerse) bu satır korunur,
          downstream'e NaN olarak teslim edilir.
        - Forward-fill YOKTUR.
    """
    import pandas as pd

    # Son barın başlangıç zamanı: şimdi - (LOOKBACK_BARS * 15dk)
    since_ms = int(
        (datetime.now(timezone.utc) - timedelta(minutes=LOOKBACK_BARS * 15)).timestamp() * 1000
    )

    raw = _fetch_ohlcv(exchange, symbol, since_ms, limit=LOOKBACK_BARS)
    if not raw:
        logger.bind(venue=venue, symbol=symbol, tf=TF).warning("ingest15m.empty_response")
        return 0

    rows = list(raw)
    df = pd.DataFrame(rows, columns=["ts_ms", "open", "high", "low", "close", "volume"])
    df["ts"] = pd.to_datetime(df["ts_ms"], unit="ms", utc=True)
    df["venue"] = venue
    df["symbol"] = symbol
    df["timeframe"] = TF
    df = df[["venue", "symbol", "timeframe", "ts", "open", "high", "low", "close", "volume"]]

    # Sayısal kolonlar — NaN korunur, clip/winsorize YOK.
    for col in ("open", "high", "low", "close", "volume"):
        df[col] = pd.to_numeric(df[col], errors="coerce")

    written = store.upsert(df)
    logger.bind(venue=venue, symbol=symbol, tf=TF, written=written).info("ingest15m.done")
    return written


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:  # pragma: no cover - integration
    """15m live ingest entry point.

    - Binance önce.
    - Binance başarısız → Bybit fallback.
    - Her iki exchange de başarısız → fail loud (exit 1).
    - Quality manifest güncellenir.
    """
    t0 = time.perf_counter()
    # DEPO-AYIRMA (2026-05-29): market.duckdb'ye DİREKT YAZMA (lock contention =
    # DMS-kill incident). ingest, market_ingest.duckdb'ye yazar (force_write=True
    # → PA_DUCKDB_READ_ONLY env bypass). Tüketici (daemon) market.duckdb'yi RO okur;
    # scheduler `market_snapshot` job (:05) atomik file-replace ile market.duckdb'yi
    # tazeler. Bu script SADECE writer; snapshot scheduler'ın işi.
    s = get_settings()
    store = OHLCVStore(path=s.ingest_duckdb_path, force_write=True)
    quality_reports = []
    errors: list[str] = []

    for symbol in SYMBOLS:
        written = 0
        last_exc: Exception | None = None

        for venue in VENUE_PRIORITY:
            try:
                exchange = _build_exchange(venue)
                written = ingest_symbol_15m(symbol, store, exchange, venue)
                # Quality check — anomali işaretle, ham veri koru.
                import pandas as pd
                df = store.read(symbol, TF, venue=venue)
                if not df.empty:
                    qr = run_quality_checks(df, venue=venue, symbol=symbol, timeframe=TF)
                    quality_reports.append(qr)
                last_exc = None
                break  # Başarılı, fallback gerekmez.
            except Exception as exc:
                last_exc = exc
                logger.bind(venue=venue, symbol=symbol, tf=TF, err=str(exc)).warning(
                    "ingest15m.venue_fail_try_fallback"
                )

        if last_exc is not None:
            # Her iki venue da başarısız → fail loud.
            msg = f"FAIL LOUD: {symbol} {TF} — tüm venue'lar başarısız: {last_exc}"
            logger.bind(symbol=symbol, tf=TF).error(msg)
            errors.append(msg)

    # Quality manifest güncelle.
    if quality_reports:
        write_daily_manifest(quality_reports)

    elapsed = time.perf_counter() - t0
    logger.bind(
        tf=TF,
        symbols=len(SYMBOLS),
        errors=len(errors),
        elapsed_s=round(elapsed, 2),
    ).info("ingest15m.run_complete")

    if errors:
        # Fail loud — cron job bunu yakalar, alert gönderir.
        print(f"[INGEST-15M] FAIL: {len(errors)} sembol başarısız:\n" + "\n".join(errors))
        sys.exit(1)

    print(f"[INGEST-15M] OK: {len(SYMBOLS)} sembol {elapsed:.1f}s")


if __name__ == "__main__":
    main()
