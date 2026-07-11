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
from collections.abc import Iterable
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import pandas as pd
import typer

from price_action.data.quality import run_quality_checks, write_daily_manifest
from price_action.data.store import OHLCVStore, checkpoint_and_close_pool_for_path
from price_action.data.universe import build_universe
from price_action.logging_config import logger
from price_action.settings import get_settings

app = typer.Typer(add_completion=False, help="OHLCV ingest CLI")


# FIX 2026-05-30: Saatlik delta ingest evreni — CANLI trading universe
# (configs/risk_phoenix_scalp_15m_widestop_vsa2.yaml strategy_portfolio.symbols
# + scripts/futures_trade_15m.py ile aynı 14 sembol; BTC regime için zaten dahil).
# Geniş all_liquid backfill (3538 sembol) saatlik DEĞİL — ayrı/manuel iş.
# Override: env PA_INGEST_HOURLY_SYMBOLS="binance:BTC/USDT,binance:ETH/USDT,..."
_HOURLY_TRADING_SYMBOLS: tuple[str, ...] = (
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
    # DEPLOY 2026-05-30: trading evreni 19'a çıktı; saatlik 1d/1w ingest de
    # paralel güncellendi (audit_data CT-DAT-01 bu boşluğu yakaladı).
    "TRX/USDT",
    "UNI/USDT",
    "ATOM/USDT",
    "AAVE/USDT",
    "ALGO/USDT",
)


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
        dt = dt.replace(tzinfo=UTC)
    return int(dt.timestamp() * 1000)


def _build_ccxt(
    venue: str, *, market_type: str = "future"
) -> Any:  # pragma: no cover - integration
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


# FIX 2026-05-28 (audit-A8): symbol-bazlı circuit breaker state.
# Önceki kod: max_retries=5 (default) → 16s max wait. Borsa API storm'unda
# (3x liq, volatile event) >60s 429 yaşanır → ingest hard-fail, gelecek
# saat tekrar dener (1h gap). Şimdi: max_retries=10 (512s max), +
# 3 ardışık fail → o sembolü 1h skip et (diğerlerini etkilemez).
_CB_FAILURE_COUNT: dict[str, int] = {}
_CB_SKIP_UNTIL: dict[str, float] = {}


def _fetch_with_retry(
    exchange: Any,
    symbol: str,
    timeframe: str,
    since_ms: int,
    limit: int = 1000,
    *,
    max_retries: int = 10,
    base_backoff: float = 1.0,
) -> list[list[Any]]:  # pragma: no cover - integration
    """`fetch_ohlcv` rate-limit guard + exponential backoff + circuit breaker.

    FIX 2026-05-28 (audit-A8):
    - max_retries 5 → 10 (16s → 512s max wait, borsa storm dayanıklı)
    - Symbol-bazlı circuit breaker: 3 ardışık fail → 1h skip
    - Başarı → CB sayacı reset
    """
    import time as _t

    cb_key = f"{getattr(exchange, 'id', 'unknown')}:{symbol}:{timeframe}"

    # Circuit breaker check
    _skip_until = _CB_SKIP_UNTIL.get(cb_key, 0.0)
    if _skip_until > _t.time():
        _rem = int(_skip_until - _t.time())
        logger.bind(symbol=symbol, tf=timeframe, remaining_s=_rem).warning(
            "ingest.circuit_open_skip"
        )
        raise RuntimeError(f"circuit breaker open: {cb_key} (3+ ardışık fail, {_rem}s kaldı)")

    attempt = 0
    while True:
        try:
            result = exchange.fetch_ohlcv(symbol, timeframe=timeframe, since=since_ms, limit=limit)
            # Başarı → CB sayacı sıfırla
            _CB_FAILURE_COUNT[cb_key] = 0
            return result
        except Exception as exc:
            cls = exc.__class__.__name__.lower()
            transient = "ratelimit" in cls or "timeout" in cls or "ddos" in cls or "network" in cls
            attempt += 1
            if attempt > max_retries or not transient:
                # Final fail → CB sayacı artır, threshold'da 1h skip
                _CB_FAILURE_COUNT[cb_key] = _CB_FAILURE_COUNT.get(cb_key, 0) + 1
                if _CB_FAILURE_COUNT[cb_key] >= 3:
                    _CB_SKIP_UNTIL[cb_key] = _t.time() + 3600  # 1h skip
                    logger.bind(
                        symbol=symbol,
                        tf=timeframe,
                        consecutive_fails=_CB_FAILURE_COUNT[cb_key],
                    ).error("ingest.circuit_open_armed")
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
        return pd.DataFrame(
            columns=["venue", "symbol", "timeframe", "ts", "open", "high", "low", "close", "volume"]
        )
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
        # FIX 2026-05-28 (audit-A7): overlap pattern — last_ts'den 50 bar geri.
        # Önceki bug: last + 1*tf'den başlıyordu, ccxt herhangi bir bar'ı miss
        # ederse (rate-limit, network, exchange) gap kalıcı oluyordu (5 MISSED
        # bar log'da görüldü). Quality check gap'i tespit ediyor ama backfill
        # yapmıyordu. 50 bar overlap → PK dedupe ile (DELETE+INSERT pattern)
        # otomatik gap doldurma. Network maliyeti: her incremental ingest'te
        # ~50 row ekstra (negligible). İlk backfill (last is None) değişmedi.
        _overlap_bars = 50
        since = last - timedelta(milliseconds=_TF_MS[timeframe] * _overlap_bars)
    else:
        since = datetime.now(UTC) - timedelta(days=365 * years)
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


def _snapshot_file_fingerprint(path) -> dict[str, int | bool]:
    """Return an lstat fingerprint without following symlinks."""

    import os
    import stat
    from pathlib import Path

    candidate = Path(path)
    try:
        info = os.lstat(candidate)
    except FileNotFoundError:
        return {
            "exists": False,
            "inode": 0,
            "is_regular": False,
            "is_symlink": False,
            "mtime_ns": 0,
            "size": 0,
        }
    return {
        "exists": True,
        "inode": int(info.st_ino),
        "is_regular": stat.S_ISREG(info.st_mode),
        "is_symlink": stat.S_ISLNK(info.st_mode),
        "mtime_ns": int(info.st_mtime_ns),
        "size": int(info.st_size),
    }


def _snapshot_source_pair_fingerprint(path) -> dict[str, dict[str, int | bool]]:
    """Fingerprint the source DB and WAL as one consistency boundary."""

    from pathlib import Path

    source = Path(path)
    pair = {
        "db": _snapshot_file_fingerprint(source),
        "wal": _snapshot_file_fingerprint(Path(f"{source}.wal")),
    }
    db = pair["db"]
    wal = pair["wal"]
    if not db["exists"] or not db["is_regular"] or db["is_symlink"] or db["size"] <= 0:
        raise RuntimeError(f"SNAPSHOT_SOURCE_INVALID db={db}")
    if wal["exists"]:
        raise RuntimeError(f"SNAPSHOT_SOURCE_WAL_PRESENT wal={wal}")
    return pair


def _validate_read_only_snapshot(path) -> tuple[int, str | None]:
    """Open the temporary DB read-only and validate its canonical OHLCV table."""

    import duckdb

    con = duckdb.connect(str(path), read_only=True)
    try:
        table = con.execute(
            """SELECT COUNT(*)
               FROM information_schema.tables
               WHERE table_schema = 'main'
                 AND table_name = 'ohlcv'
                 AND table_type = 'BASE TABLE'"""
        ).fetchone()
        if table is None or int(table[0]) != 1:
            raise RuntimeError("SNAPSHOT_VALIDATE_FAIL canonical ohlcv table missing")
        row = con.execute("SELECT COUNT(*), MAX(ts) FROM ohlcv").fetchone()
        if row is None or int(row[0]) <= 0:
            raise RuntimeError("SNAPSHOT_VALIDATE_FAIL ohlcv table empty")
        return int(row[0]), str(row[1]) if row[1] is not None else None
    finally:
        con.close()


def _snapshot_ingest_to_consumer(ingest_path, consumer_path) -> dict[str, Any]:
    """Publish a validated, race-detected ingest snapshot atomically.

    The caller that owns the writer must checkpoint and close its pool first.
    The hourly backstop may race another writer, so the source DB+WAL lstat
    fingerprint is compared before and after copy/validation. Any mutation,
    WAL, invalid temporary DB, or competing publisher preserves the existing
    consumer. Only a fully validated same-directory temporary file reaches
    ``os.replace``.
    """

    import fcntl
    import os
    import shutil
    import tempfile
    from pathlib import Path

    source = Path(ingest_path)
    consumer = Path(consumer_path)
    result: dict[str, Any] = {
        "snapshotted": False,
        "bytes": 0,
        "newest_bar": None,
        "rows": 0,
        "error": None,
    }
    tmp_path: Path | None = None
    backup_tmp: Path | None = None
    lock_file = None
    try:
        consumer.parent.mkdir(parents=True, exist_ok=True)
        lock_path = consumer.parent / f".{consumer.name}.snapshot.lock"
        lock_file = lock_path.open("a+b")
        try:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError(f"SNAPSHOT_PUBLISH_BUSY lock={lock_path}") from exc

        before = _snapshot_source_pair_fingerprint(source)
        fd, raw_tmp = tempfile.mkstemp(
            prefix=f".{consumer.name}.snapshot.",
            suffix=".duckdb",
            dir=consumer.parent,
        )
        os.close(fd)
        tmp_path = Path(raw_tmp)
        shutil.copyfile(source, tmp_path)
        if tmp_path.stat().st_size != int(before["db"]["size"]):
            raise RuntimeError(
                "SNAPSHOT_COPY_SIZE_MISMATCH "
                f"expected={before['db']['size']} actual={tmp_path.stat().st_size}"
            )
        with tmp_path.open("rb") as copied:
            os.fsync(copied.fileno())

        rows, newest_bar = _validate_read_only_snapshot(tmp_path)
        after = _snapshot_source_pair_fingerprint(source)
        if after != before:
            raise RuntimeError(f"SNAPSHOT_SOURCE_CHANGED before={before} after={after}")

        # Keep the previous consumer as a cheap same-filesystem hard-link. A
        # backup failure is warning-only because the validated temp still makes
        # publication safe; the original consumer remains until os.replace.
        if consumer.is_file():
            bak_path = consumer.with_suffix(consumer.suffix + ".bak")
            backup_tmp = consumer.parent / f".{consumer.name}.bak.{os.getpid()}"
            try:
                backup_tmp.unlink(missing_ok=True)
                os.link(consumer, backup_tmp)
                os.replace(backup_tmp, bak_path)
                backup_tmp = None
            except Exception as backup_exc:  # pragma: no cover - filesystem defensive path
                logger.bind(err=str(backup_exc)[:200]).warning("ingest.snapshot_bak_fail")

        snapshot_bytes = tmp_path.stat().st_size
        os.replace(tmp_path, consumer)
        tmp_path = None
        result.update(
            {
                "snapshotted": True,
                "bytes": snapshot_bytes,
                "newest_bar": newest_bar,
                "rows": rows,
            }
        )
        try:
            directory_fd = os.open(consumer.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except OSError as fsync_exc:  # publication already happened; report truthfully
            logger.bind(err=str(fsync_exc)[:200]).warning("ingest.snapshot_dir_fsync_fail")
        logger.bind(
            bytes=result["bytes"],
            newest_bar=result["newest_bar"],
            rows=result["rows"],
        ).info("ingest.snapshot_done")
    except Exception as exc:
        result["error"] = str(exc)[:500]
        logger.bind(err=result["error"]).error("ingest.snapshot_fail")
    finally:
        for artifact in (tmp_path, backup_tmp):
            if artifact is not None:
                with suppress(OSError):
                    artifact.unlink(missing_ok=True)
        if lock_file is not None:
            try:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
            finally:
                lock_file.close()
    return result


async def run_hourly() -> dict[str, Any]:
    """Saatlik delta ingest — scheduler tarafından çağrılır.

    FIX 2026-05-28 (Faz 14.27): Önceki sürümde bu fonksiyon YOKTU. Scheduler
    `_job_ingest_data` `hasattr(ingest_ccxt, "run_hourly")` False alıp **silent
    skip** ediyordu → market.duckdb 6 GÜN güncellenmedi → bot stale data ile
    backtest/regime check yapıyordu.

    FIX 2026-05-28 (depo-ayirma): Ingest artık market.duckdb'ye DEĞİL,
    market_ingest.duckdb'ye yazar (force_write=True → read-only env'i bypass).
    Ingest bittiğinde atomik FILE-kopya snapshot ile market.duckdb tazeленir.
    Bu, CEO daemon read-only env çakışmasını ("Cannot DELETE on read-only")
    kökten çözer: yazıcı ve okuyucu artık AYRI dosyada.

    FIX 2026-05-30 (alarm-temizlik): Önceden `_resolve_symbols(None)` →
    `build_universe()` = **3538 all_liquid sembol × 2 TF = 7076 ingest/saat**,
    her biri 5 yıllık. Bot sadece 14 sembol trade ediyor → 3500+ illiquid/
    delisted sembol per-symbol fail (24h'de ~20k `ingest.symbol_fail`) + iş
    saatlerce sürüp CEO restart'ında `CancelledError` ile düşüyordu. Saatlik
    ingest'in işi CANLI veriyi taze tutmak (trading evreni + regime), evren-
    çapında backfill DEĞİL (o ayrı/manuel/tek-seferlik bir iş). Şimdi:
    trading evreniyle sınırlı (env `PA_INGEST_HOURLY_SYMBOLS` ile override).

    Returns:
        {"symbols": N, "tfs": M, "ingested": K, "snapshot": {...}}
    """
    import asyncio
    import os

    s = get_settings()
    # Saatlik delta yalnızca CANLI-ilgili semboller (trading evreni + regime
    # için BTC). Geniş araştırma backfill'i ayrı bir işin sorumluluğu.
    _hourly_csv = os.environ.get("PA_INGEST_HOURLY_SYMBOLS", "").strip()
    if _hourly_csv:
        pairs = _resolve_symbols(_hourly_csv)
    else:
        pairs = _resolve_symbols(",".join(_HOURLY_TRADING_SYMBOLS))
    timeframes = s.timeframes_list
    # depo-ayirma: ayrı yazılabilir dosya + read-only env bypass
    store = OHLCVStore(path=s.ingest_duckdb_path, force_write=True)
    n_done = 0
    failures: list[str] = []
    checkpoint_error: str | None = None
    # Reuse one sequential CCXT limiter/market cache per venue.  Constructing
    # a client for every symbol×timeframe caused repeated exchange metadata
    # loads and made the hourly job's effective rate budget fragmented.
    exchange_by_venue: dict[str, Any] = {}
    try:
        for v, sy in pairs:
            for t in timeframes:
                try:
                    exchange = exchange_by_venue.get(v)
                    if exchange is None:
                        exchange = _build_ccxt(v, market_type="future")
                        exchange_by_venue[v] = exchange
                    # Sync ingest_symbol — async loop'u bloklamamak için thread'e at
                    stat = await asyncio.to_thread(
                        ingest_symbol,
                        venue=v,
                        symbol=sy,
                        timeframe=t,
                        years=s.pa_backtest_years,
                        store=store,
                        exchange=exchange,
                    )
                    logger.bind(**stat.__dict__).info("ingest.symbol_done")
                    if stat.error is not None:
                        failures.append(f"{v}:{sy}:{t}: {stat.error}")
                    else:
                        n_done += 1
                except Exception as exc:
                    failures.append(f"{v}:{sy}:{t}: {exc}")
                    logger.bind(venue=v, symbol=sy, tf=t, err=str(exc)[:200]).warning(
                        "ingest.symbol_fail"
                    )
    finally:
        # Detach the long-lived CEO writer pool, issue a strict CHECKPOINT and
        # close the handle before any filesystem snapshot. Cancellation also
        # passes through this boundary and therefore cannot leak the lock.
        try:
            await asyncio.to_thread(
                checkpoint_and_close_pool_for_path,
                s.ingest_duckdb_path,
            )
        except Exception as exc:
            checkpoint_error = str(exc)[:300]
            logger.bind(err=checkpoint_error).error("ingest.checkpoint_close_fail")

    if failures or checkpoint_error is not None:
        reasons: list[str] = []
        if failures:
            reasons.append(f"SNAPSHOT_SUPPRESSED_PARTIAL_INGEST failures={len(failures)}")
        if checkpoint_error is not None:
            reasons.append(f"SNAPSHOT_SUPPRESSED_CHECKPOINT_CLOSE error={checkpoint_error}")
        reason = "; ".join(reasons)
        snap: dict[str, Any] = {
            "snapshotted": False,
            "bytes": 0,
            "newest_bar": None,
            "rows": 0,
            "error": reason,
        }
        logger.bind(err=reason).error("ingest.snapshot_suppressed")
    else:
        # Successful ingest boundary only: publish through the validated,
        # fingerprinted atomic helper used by the independent hourly backstop.
        snap = await asyncio.to_thread(
            _snapshot_ingest_to_consumer,
            s.ingest_duckdb_path,
            s.duckdb_path,
        )
    return {
        "symbols": len(pairs),
        "tfs": len(timeframes),
        "ingested": n_done,
        "errors": failures,
        "snapshot": snap,
    }


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
            stat = ingest_symbol(venue=v, symbol=sy, timeframe=t, years=n_years, store=store)
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
