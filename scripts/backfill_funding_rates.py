"""Backfill Binance USDM-Futures funding rate history — 19-symbol champion universe.

Endpoint: GET https://fapi.binance.com/fapi/v1/fundingRate
  - Returns up to 1000 records per call (8h intervals = 3/day)
  - No explicit rate-limit headers returned, but Binance docs: 500 weight/min IP limit
  - Each fundingRate call weight = 1; we sleep 150ms between pages, 300ms between symbols

OI Note: fapiPublicGetOpenInterestHist (futures/data/openInterestHist) only returns
  the last ~30 days rolling window and rejects any startTime param outside that window.
  OI hist is therefore stored as a supplementary 30-day snapshot, not a deep history.

Output:
  data/funding.duckdb
    - Table: funding_rates  (venue, symbol, ts TIMESTAMPTZ, funding_rate, mark_price)
    - Table: oi_snapshot    (venue, symbol, ts TIMESTAMPTZ, open_interest, oi_value_usdt)

Quality manifest written to data/quality/funding_backfill_YYYY-MM-DD.json

Usage:
    /Users/peyman/price-action-bot/.venv/bin/python scripts/backfill_funding_rates.py
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path

import duckdb
import pandas as pd
import requests

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "funding.duckdb"
QUALITY_DIR = ROOT / "data" / "quality"
QUALITY_DIR.mkdir(parents=True, exist_ok=True)

BINANCE_FUNDING_URL = "https://fapi.binance.com/fapi/v1/fundingRate"
BINANCE_OI_URL = "https://fapi.binance.com/futures/data/openInterestHist"

# Champion 19-symbol universe (configs/risk_phoenix_scalp_15m_widestop_vsa2.yaml)
SYMBOLS_19 = [
    "BTC", "ETH", "SOL", "BNB", "ADA", "AVAX", "LINK", "DOT", "DOGE", "XRP",
    "ZEC", "NEAR", "FIL", "XLM", "TRX", "UNI", "ATOM", "AAVE", "ALGO",
]

# 2021-01-01 00:00 UTC — confirmed earliest available for all 19 symbols
START_MS = 1609459200000

# Inter-page sleep (ms → s). Keeps us well under 500 weight/min.
PAGE_SLEEP_S = 0.15
SYMBOL_SLEEP_S = 0.30


# ---------------------------------------------------------------------------
# DDL
# ---------------------------------------------------------------------------
DDL = """
CREATE TABLE IF NOT EXISTS funding_rates (
    venue        VARCHAR NOT NULL,
    symbol       VARCHAR NOT NULL,
    ts           TIMESTAMPTZ NOT NULL,
    funding_rate DOUBLE,
    mark_price   DOUBLE,
    PRIMARY KEY (venue, symbol, ts)
);

CREATE TABLE IF NOT EXISTS oi_snapshot (
    venue          VARCHAR NOT NULL,
    symbol         VARCHAR NOT NULL,
    ts             TIMESTAMPTZ NOT NULL,
    open_interest  DOUBLE,
    oi_value_usdt  DOUBLE,
    PRIMARY KEY (venue, symbol, ts)
);
"""


def init_db(db_path: Path) -> duckdb.DuckDBPyConnection:
    con = duckdb.connect(str(db_path))
    con.execute(DDL)
    return con


# ---------------------------------------------------------------------------
# Fetch helpers
# ---------------------------------------------------------------------------
def fetch_funding_history(symbol: str) -> pd.DataFrame:
    """Paginate all funding records from START_MS to now for one symbol."""
    end_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    fapi_sym = f"{symbol}USDT"

    all_rows: list[dict] = []
    cur_start = START_MS
    page = 0
    consecutive_empty = 0

    while cur_start < end_ms:
        params = {
            "symbol": fapi_sym,
            "startTime": cur_start,
            "endTime": end_ms,
            "limit": 1000,
        }
        try:
            r = requests.get(BINANCE_FUNDING_URL, params=params, timeout=30)
            if r.status_code == 429:
                wait = int(r.headers.get("Retry-After", 60))
                print(f"    429 rate-limit — sleeping {wait}s")
                time.sleep(wait)
                continue
            r.raise_for_status()
            data = r.json()
        except requests.RequestException as exc:
            raise RuntimeError(f"funding fetch error page {page} sym={symbol}: {exc}") from exc

        if not data:
            consecutive_empty += 1
            if consecutive_empty >= 3:
                break
            time.sleep(PAGE_SLEEP_S)
            continue

        consecutive_empty = 0
        all_rows.extend(data)
        last_ts = int(data[-1]["fundingTime"])
        if last_ts <= cur_start:
            # No forward progress — safety exit
            break
        cur_start = last_ts + 1
        page += 1

        if len(data) < 1000:
            # Last page
            break

        time.sleep(PAGE_SLEEP_S)

    if not all_rows:
        return pd.DataFrame(columns=["ts", "funding_rate", "mark_price"])

    df = pd.DataFrame(all_rows)
    df["ts"] = pd.to_datetime(df["fundingTime"].astype(int), unit="ms", utc=True)
    df["funding_rate"] = pd.to_numeric(df["fundingRate"], errors="coerce")
    df["mark_price"] = pd.to_numeric(df["markPrice"], errors="coerce")
    df = (
        df[["ts", "funding_rate", "mark_price"]]
        .drop_duplicates(subset=["ts"])
        .sort_values("ts")
        .reset_index(drop=True)
    )
    return df


def fetch_oi_snapshot(symbol: str) -> pd.DataFrame:
    """Fetch last-30-days OI (1d) for one symbol. Binance cap: ~30d window only."""
    fapi_sym = f"{symbol}USDT"
    params = {"symbol": fapi_sym, "period": "1d", "limit": 30}
    try:
        r = requests.get(BINANCE_OI_URL, params=params, timeout=30)
        r.raise_for_status()
        data = r.json()
    except requests.RequestException as exc:
        print(f"    OI snapshot error sym={symbol}: {exc}")
        return pd.DataFrame(columns=["ts", "open_interest", "oi_value_usdt"])

    if not isinstance(data, list) or not data:
        return pd.DataFrame(columns=["ts", "open_interest", "oi_value_usdt"])

    df = pd.DataFrame(data)
    df["ts"] = pd.to_datetime(df["timestamp"].astype(int), unit="ms", utc=True)
    df["open_interest"] = pd.to_numeric(df["sumOpenInterest"], errors="coerce")
    df["oi_value_usdt"] = pd.to_numeric(df["sumOpenInterestValue"], errors="coerce")
    df = (
        df[["ts", "open_interest", "oi_value_usdt"]]
        .drop_duplicates(subset=["ts"])
        .sort_values("ts")
        .reset_index(drop=True)
    )
    return df


# ---------------------------------------------------------------------------
# Upsert helpers
# ---------------------------------------------------------------------------
def upsert_funding(con: duckdb.DuckDBPyConnection, symbol: str, df: pd.DataFrame) -> int:
    """Upsert funding_rates; return rows inserted."""
    if df.empty:
        return 0
    df = df.copy()
    df["venue"] = "binance"
    df["symbol"] = symbol
    df = df[["venue", "symbol", "ts", "funding_rate", "mark_price"]]

    con.execute("CREATE TEMP TABLE IF NOT EXISTS _fr_stage AS SELECT * FROM funding_rates LIMIT 0")
    con.execute("DELETE FROM _fr_stage")
    con.register("_fr_df", df)
    con.execute("INSERT INTO _fr_stage SELECT * FROM _fr_df")

    # Delete-then-insert for idempotent upsert (DuckDB < 0.10 has no INSERT OR REPLACE for TIMESTAMPTZ PK)
    con.execute("""
        DELETE FROM funding_rates
        WHERE (venue, symbol, ts) IN (
            SELECT venue, symbol, ts FROM _fr_stage
        )
    """)
    rows = con.execute("SELECT count(*) FROM _fr_stage").fetchone()[0]
    con.execute("INSERT INTO funding_rates SELECT * FROM _fr_stage")
    return rows


def upsert_oi(con: duckdb.DuckDBPyConnection, symbol: str, df: pd.DataFrame) -> int:
    if df.empty:
        return 0
    df = df.copy()
    df["venue"] = "binance"
    df["symbol"] = symbol
    df = df[["venue", "symbol", "ts", "open_interest", "oi_value_usdt"]]

    con.execute("CREATE TEMP TABLE IF NOT EXISTS _oi_stage AS SELECT * FROM oi_snapshot LIMIT 0")
    con.execute("DELETE FROM _oi_stage")
    con.register("_oi_df", df)
    con.execute("INSERT INTO _oi_stage SELECT * FROM _oi_df")

    con.execute("""
        DELETE FROM oi_snapshot
        WHERE (venue, symbol, ts) IN (
            SELECT venue, symbol, ts FROM _oi_stage
        )
    """)
    rows = con.execute("SELECT count(*) FROM _oi_stage").fetchone()[0]
    con.execute("INSERT INTO oi_snapshot SELECT * FROM _oi_stage")
    return rows


# ---------------------------------------------------------------------------
# Quality checks
# ---------------------------------------------------------------------------
def quality_check_funding(df: pd.DataFrame, symbol: str) -> dict:
    """Return per-symbol quality metrics."""
    if df.empty:
        return {
            "symbol": symbol,
            "status": "EMPTY",
            "records": 0,
            "start_date": None,
            "end_date": None,
            "gaps_8h": 0,
            "duplicates": 0,
            "rate_mean": None,
            "rate_std": None,
            "rate_min": None,
            "rate_max": None,
            "sign_flip_pct": None,
            "positive_pct": None,
        }

    ts_sorted = df["ts"].sort_values().reset_index(drop=True)

    # Gap detection: expected 8h intervals
    expected_interval_ns = 8 * 3600 * 1_000_000_000
    diffs_ns = ts_sorted.diff().dropna().astype(int)
    # Allow ±5 minutes tolerance (Binance sometimes drifts slightly)
    tolerance_ns = 5 * 60 * 1_000_000_000
    gaps = int((diffs_ns > (expected_interval_ns + tolerance_ns)).sum())

    # Duplicates
    dupes = int(df["ts"].duplicated().sum())

    # Rate stats
    rates = df["funding_rate"].dropna()
    sign_flips = int((rates.shift(1) * rates < 0).sum()) if len(rates) > 1 else 0
    sign_flip_pct = round(sign_flips / max(len(rates) - 1, 1) * 100, 2)
    positive_pct = round((rates > 0).mean() * 100, 2)

    return {
        "symbol": symbol,
        "status": "OK" if gaps == 0 and dupes == 0 else "WARN",
        "records": len(df),
        "start_date": str(ts_sorted.iloc[0]),
        "end_date": str(ts_sorted.iloc[-1]),
        "gaps_8h": gaps,
        "duplicates": dupes,
        "rate_mean": round(float(rates.mean()), 8) if len(rates) else None,
        "rate_std": round(float(rates.std()), 8) if len(rates) else None,
        "rate_min": round(float(rates.min()), 8) if len(rates) else None,
        "rate_max": round(float(rates.max()), 8) if len(rates) else None,
        "sign_flip_pct": sign_flip_pct,
        "positive_pct": positive_pct,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    print("=" * 70)
    print("FUNDING RATE BACKFILL — 19-symbol champion universe")
    print(f"DB: {DB_PATH}")
    print("=" * 70)

    run_ts = datetime.now(timezone.utc)
    con = init_db(DB_PATH)

    quality_results: list[dict] = []
    total_funding_rows = 0
    total_oi_rows = 0

    for idx, sym in enumerate(SYMBOLS_19, 1):
        print(f"\n[{idx:02d}/{len(SYMBOLS_19)}] {sym}USDT")

        # --- Funding rates ---
        print(f"  fetching funding history...", end=" ", flush=True)
        t0 = time.time()
        fdf = fetch_funding_history(sym)
        elapsed = time.time() - t0
        print(f"{len(fdf)} records in {elapsed:.1f}s")

        rows_upserted = upsert_funding(con, sym, fdf)
        total_funding_rows += rows_upserted
        print(f"  upserted {rows_upserted} rows into funding_rates")

        qc = quality_check_funding(fdf, sym)
        quality_results.append(qc)

        if qc["status"] == "WARN":
            print(f"  WARN: gaps={qc['gaps_8h']}, dupes={qc['duplicates']}")
        if qc["records"] > 0:
            print(f"  range: {qc['start_date'][:10]} -> {qc['end_date'][:10]}  "
                  f"mean_rate={qc['rate_mean']:.6f}  "
                  f"positive={qc['positive_pct']}%  sign_flip={qc['sign_flip_pct']}%")

        # --- OI snapshot ---
        print(f"  fetching OI snapshot (last 30d)...", end=" ", flush=True)
        odf = fetch_oi_snapshot(sym)
        oi_rows = upsert_oi(con, sym, odf)
        total_oi_rows += oi_rows
        print(f"{len(odf)} records, upserted {oi_rows}")

        time.sleep(SYMBOL_SLEEP_S)

    # Final DB dedup verification
    print("\n" + "=" * 70)
    print("POST-INGEST QUALITY VERIFICATION")
    print("=" * 70)

    dup_check = con.execute("""
        SELECT symbol, ts, count(*) as cnt
        FROM funding_rates
        GROUP BY symbol, ts
        HAVING cnt > 1
    """).fetchdf()

    if len(dup_check) > 0:
        print(f"FAIL: {len(dup_check)} duplicate (symbol, ts) pairs detected!")
        print(dup_check.head(10))
    else:
        print("Duplicate check: PASS — 0 duplicate (symbol, ts) pairs")

    total_in_db = con.execute("SELECT count(*) FROM funding_rates").fetchone()[0]
    oi_in_db = con.execute("SELECT count(*) FROM oi_snapshot").fetchone()[0]
    print(f"Total funding_rates rows in DB: {total_in_db}")
    print(f"Total oi_snapshot rows in DB:   {oi_in_db}")

    # Coverage table
    coverage = con.execute("""
        SELECT
            symbol,
            min(ts) as earliest,
            max(ts) as latest,
            count(*) as records,
            max(ts) - min(ts) as span
        FROM funding_rates
        GROUP BY symbol
        ORDER BY symbol
    """).fetchdf()
    print("\nCoverage per symbol:")
    print(coverage.to_string(index=False))

    # Write quality manifest
    manifest = {
        "run_ts": run_ts.isoformat(),
        "db_path": str(DB_PATH),
        "table_funding_rates": "funding_rates",
        "table_oi_snapshot": "oi_snapshot",
        "endpoint": BINANCE_FUNDING_URL,
        "oi_endpoint": BINANCE_OI_URL,
        "oi_note": "OI history limited to last ~30 days rolling window; startTime rejected by API for older dates",
        "total_funding_rows_in_db": int(total_in_db),
        "total_oi_rows_in_db": int(oi_in_db),
        "symbols": quality_results,
    }
    manifest_path = QUALITY_DIR / f"funding_backfill_{run_ts.strftime('%Y-%m-%d')}.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, default=str))
    print(f"\nQuality manifest: {manifest_path}")

    con.close()
    print("\nDone.")


if __name__ == "__main__":
    main()
