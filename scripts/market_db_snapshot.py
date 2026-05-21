"""market_replica.duckdb — Parquet arşivinden read-only replica üretici.

PROBLEM
-------
Canlı daemon (futures_daemon.py) market.duckdb'yi Windows exclusive lock ile
tutar. shutil.copy2 dahil hiçbir dış process bu dosyayı açamaz veya kopyalayamaz.
DuckDB 1.2.1 / Windows: DuplicateHandle semantiği nedeniyle SHARE_READ verilmiyor.

ÇÖZÜM  (Tercih A — Parquet-to-DuckDB Replica)
----------------------------------------------
data/parquet/{venue}/{symbol}/{tf}/year=YYYY/month=MM/data.parquet
dosyaları daemon tarafından ZATEn yazılıyor ve daemon'dan BAĞIMSIZ — daemon
bunları lock'lamıyor (OHLCVStore._write_parquet her partition dosyasını kısa
sürede açıp kapatıyor, uzun süreli lock YOK).

Bu script Parquet arşivini okuyarak data/market_replica.duckdb'yi sıfırdan
veya incrementally yeniler. Replica tamamen daemon-bağımsız, read_only=True
ile herhangi bir process/thread tarafından paralel okunabilir.

VERİ TAZELIĞI
-------------
- Daemon her bar kapanışında Parquet'a yazar (OHLCVStore.upsert → _write_parquet).
- Snapshot bu scriptle alınırsa replica en fazla son bar latency + script runtime
  kadar stale olur (~1-5 dakika).
- --schedule modunda 30 dakikada bir otomatik yenileme yapılır.

ÇIKTI
-----
- data/market_replica.duckdb   ← Lab/Researcher bu dosyayı okur
- data/quality/replica_manifest.json

KULLANIM (Lab / Researcher — tek satır)
----------------------------------------
    import duckdb
    con = duckdb.connect("data/market_replica.duckdb", read_only=True)

ÇALIŞMA
-------
    python scripts/market_db_snapshot.py              # tek seferlik
    python scripts/market_db_snapshot.py --schedule   # 30 dakika loop
    python scripts/market_db_snapshot.py --interval 600  # 10 dakika loop
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import duckdb
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
PARQUET_ROOT = ROOT / "data" / "parquet"
REPLICA = ROOT / "data" / "market_replica.duckdb"
MANIFEST = ROOT / "data" / "quality" / "replica_manifest.json"
SNAPSHOT_INTERVAL_SEC = 30 * 60  # 30 dakika

_OHLCV_DDL = """
CREATE TABLE IF NOT EXISTS ohlcv (
    venue       VARCHAR NOT NULL,
    symbol      VARCHAR NOT NULL,
    timeframe   VARCHAR NOT NULL,
    ts          TIMESTAMPTZ NOT NULL,
    open        DOUBLE,
    high        DOUBLE,
    low         DOUBLE,
    close       DOUBLE,
    volume      DOUBLE,
    PRIMARY KEY (venue, symbol, timeframe, ts)
);
"""

_INSTRUMENTS_DDL = """
CREATE TABLE IF NOT EXISTS instruments (
    venue           VARCHAR NOT NULL,
    symbol          VARCHAR NOT NULL,
    market_type     VARCHAR NOT NULL,
    base            VARCHAR,
    quote           VARCHAR,
    listing_date    TIMESTAMPTZ,
    delisting_date  TIMESTAMPTZ,
    tick_size       DOUBLE,
    lot_step        DOUBLE,
    min_notional_usdt DOUBLE,
    is_active       BOOLEAN DEFAULT TRUE,
    PRIMARY KEY (venue, symbol, market_type)
);
"""


def _sha256(path: Path, chunk: int = 8 * 1024 * 1024) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            block = f.read(chunk)
            if not block:
                break
            h.update(block)
    return h.hexdigest()


def _load_parquet_combo(venue_dir: Path, sym_dir: Path, tf_dir: Path) -> pd.DataFrame | None:
    """Tek (venue, symbol, timeframe) için tüm partition'ları birleştir."""
    frames = []
    for year_dir in sorted(tf_dir.iterdir()):
        if not year_dir.is_dir():
            continue
        for month_dir in sorted(year_dir.iterdir()):
            if not month_dir.is_dir():
                continue
            f = month_dir / "data.parquet"
            if f.exists():
                try:
                    frames.append(pd.read_parquet(f))
                except Exception as exc:
                    print(f"  [WARN] Parquet oku hatası {f}: {exc}", flush=True)
    if not frames:
        return None
    df = pd.concat(frames, ignore_index=True)
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    df = df.sort_values("ts").reset_index(drop=True)
    return df


def _ensure_utc_col(df: pd.DataFrame, col: str = "ts") -> pd.DataFrame:
    if col not in df.columns:
        return df
    s = df[col]
    if not pd.api.types.is_datetime64_any_dtype(s):
        s = pd.to_datetime(s, utc=True, errors="coerce")
    elif s.dt.tz is None:
        s = s.dt.tz_localize("UTC")
    else:
        s = s.dt.tz_convert("UTC")
    df = df.copy()
    df[col] = s
    return df


def build_replica(verbose: bool = True) -> dict:
    """Parquet arşivinden market_replica.duckdb oluştur. Manifest dict döner."""
    if not PARQUET_ROOT.exists():
        raise FileNotFoundError(f"Parquet kökü bulunamadı: {PARQUET_ROOT}")

    now_utc = datetime.now(timezone.utc)
    tmp_path = REPLICA.with_suffix(".duckdb.tmp")

    # ── 1. Tmp replica oluştur ─────────────────────────────────────────
    if tmp_path.exists():
        tmp_path.unlink()
    con = duckdb.connect(str(tmp_path))
    con.execute(_OHLCV_DDL)
    con.execute(_INSTRUMENTS_DDL)
    con.execute(
        "CREATE INDEX IF NOT EXISTS idx_ohlcv_lookup "
        "ON ohlcv (venue, symbol, timeframe, ts);"
    )

    total_rows = 0
    combos_loaded = 0
    combos_skipped = 0

    # ── 2. Parquet walk ────────────────────────────────────────────────
    venue_dirs = sorted(d for d in PARQUET_ROOT.iterdir() if d.is_dir())
    for venue_dir in venue_dirs:
        venue = venue_dir.name
        sym_dirs = sorted(d for d in venue_dir.iterdir() if d.is_dir())
        for sym_dir in sym_dirs:
            # ADA_USDT → ADA/USDT
            symbol = sym_dir.name.replace("_", "/", 1)
            tf_dirs = sorted(d for d in sym_dir.iterdir() if d.is_dir())
            for tf_dir in tf_dirs:
                timeframe = tf_dir.name
                df = _load_parquet_combo(venue_dir, sym_dir, tf_dir)
                if df is None or df.empty:
                    combos_skipped += 1
                    continue
                # Kolon denetimi — ohlcv schema
                needed = ["venue", "symbol", "timeframe", "ts", "open", "high", "low", "close", "volume"]
                for col in ["venue", "symbol", "timeframe"]:
                    if col not in df.columns:
                        df[col] = {"venue": venue, "symbol": symbol, "timeframe": timeframe}[col]
                missing = [c for c in needed if c not in df.columns]
                if missing:
                    if verbose:
                        print(f"  [SKIP] {venue}/{symbol}/{timeframe} — eksik kolon: {missing}", flush=True)
                    combos_skipped += 1
                    continue
                df = _ensure_utc_col(df, "ts")
                df = df[needed].drop_duplicates(
                    subset=["venue", "symbol", "timeframe", "ts"], keep="last"
                )
                # Batch insert
                con.register("_batch", df)
                con.execute("BEGIN")
                try:
                    con.execute(
                        "DELETE FROM ohlcv USING _batch b "
                        "WHERE ohlcv.venue=b.venue AND ohlcv.symbol=b.symbol "
                        "  AND ohlcv.timeframe=b.timeframe AND ohlcv.ts=b.ts"
                    )
                    con.execute(
                        "INSERT INTO ohlcv SELECT venue,symbol,timeframe,ts,"
                        "open,high,low,close,volume FROM _batch"
                    )
                    con.execute("COMMIT")
                except Exception:
                    con.execute("ROLLBACK")
                    raise
                finally:
                    con.unregister("_batch")
                total_rows += len(df)
                combos_loaded += 1
                if verbose:
                    print(
                        f"  [load] {venue}/{symbol}/{timeframe}: {len(df):,} bar", flush=True
                    )

    con.close()

    if verbose:
        print(
            f"\n[snapshot] Toplam {total_rows:,} satır, {combos_loaded} combo yüklendi "
            f"({combos_skipped} atlandı)",
            flush=True,
        )

    # ── 3. Atomic rename: tmp → replica ───────────────────────────────
    if REPLICA.exists():
        REPLICA.unlink()
    tmp_path.rename(REPLICA)

    if verbose:
        print(f"[snapshot] Replica: {REPLICA.name} ({REPLICA.stat().st_size // (1024*1024)} MB)", flush=True)

    # ── 4. SHA256 ──────────────────────────────────────────────────────
    sha = _sha256(REPLICA)

    # ── 5. ts range doğrulama ──────────────────────────────────────────
    ts_min, ts_max = None, None
    try:
        verify_con = duckdb.connect(str(REPLICA), read_only=True)
        row = verify_con.execute("SELECT MIN(ts), MAX(ts) FROM ohlcv").fetchone()
        verify_con.close()
        if row:
            ts_min = str(row[0])
            ts_max = str(row[1])
    except Exception as exc:
        print(f"[snapshot] ts range doğrulama hatası: {exc}", flush=True)

    # ── 6. Manifest ────────────────────────────────────────────────────
    manifest = {
        "replica_path": str(REPLICA.relative_to(ROOT)),
        "source": "parquet",
        "parquet_root": str(PARQUET_ROOT.relative_to(ROOT)),
        "snapshot_utc": now_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "sha256": sha,
        "size_bytes": REPLICA.stat().st_size,
        "duckdb_version": duckdb.__version__,
        "row_counts": {"ohlcv": total_rows},
        "combos_loaded": combos_loaded,
        "combos_skipped": combos_skipped,
        "ts_range": {"min": ts_min, "max": ts_max},
    }
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(json.dumps(manifest, indent=2, default=str), encoding="utf-8")

    if verbose:
        print(
            f"[snapshot] DONE  sha256={sha[:16]}...\n"
            f"           ts_min={ts_min}  ts_max={ts_max}\n"
            f"           manifest -> {MANIFEST.relative_to(ROOT)}",
            flush=True,
        )
    return manifest


def run_scheduler(interval_sec: int = SNAPSHOT_INTERVAL_SEC) -> None:
    print(f"[snapshot-scheduler] Her {interval_sec}s'de bir yenileniyor. Ctrl-C ile dur.", flush=True)
    while True:
        t0 = time.monotonic()
        try:
            build_replica(verbose=True)
        except Exception as exc:
            print(f"[snapshot-scheduler] HATA: {exc}", flush=True)
        elapsed = time.monotonic() - t0
        wait = max(0, interval_sec - elapsed)
        print(f"[snapshot-scheduler] Sonraki snapshot {wait/60:.1f} dk sonra.", flush=True)
        time.sleep(wait)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="market_replica.duckdb — Parquet-to-DuckDB snapshot")
    parser.add_argument(
        "--schedule",
        action="store_true",
        help=f"Her INTERVAL saniyede bir otomatik yenile",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=SNAPSHOT_INTERVAL_SEC,
        help="--schedule ile kullanılır, saniye cinsinden (default: 1800)",
    )
    args = parser.parse_args()

    if args.schedule:
        run_scheduler(args.interval)
    else:
        try:
            build_replica(verbose=True)
            sys.exit(0)
        except Exception as exc:
            print(f"[snapshot] FAIL: {exc}", flush=True)
            sys.exit(1)
