#!/usr/bin/env python3
"""
Forex OHLCV ingest — HistData.com (free, no API key, no VPN required).

Source: https://www.histdata.com  (ASCII M1 bars)
Why HistData: Dukascopy is DPI/SNI-blocked by Turkish ISP (resets to block-page
IP 195.175.254.2). yfinance is proven broken for EUR/USD (open==close ~74%).
HistData resolves to a real OVH host (51.77.23.84) and is reachable VPN-free.

Pipeline:
  1. For each target year, fetch the download page to obtain a per-request token (tk).
  2. POST to get.php to download the full-year M1 ASCII zip.
  3. Parse ';'-delimited rows: YYYYMMDD HHMMSS;open;high;low;close;volume.
  4. Localize timestamps EST/EDT (US Eastern, HistData's documented tz) -> UTC.
  5. Resample M1 -> 4H, LEFT-labeled, left-closed: bar [t, t+4h).
     open=first, high=max, low=min, close=last, volume=sum (always 0 for FX).
     LOOKAHEAD-CLEAN: a bar labeled t contains only M1s in [t, t+4h).
  6. Upsert into data/forex_market.duckdb (schema mirrors crypto market.duckdb).
  7. Run quality checks; print report. NO forward-fill / clip / winsorize.

HARD LIMITS honored:
  - Does NOT touch crypto DBs; writes only data/forex_market.duckdb.
  - No forward-fill, no clipping, no winsorizing — anomalies surfaced, raw kept.
  - All timestamps UTC, tz-aware.
  - Fails loud if a year download fails (no silent gaps).
"""
from __future__ import annotations

import io
import re
import sys
import time
import zipfile
from pathlib import Path

import duckdb
import pandas as pd
import requests

REPO = Path(__file__).resolve().parents[1]
DB_PATH = REPO / "data" / "forex_market.duckdb"
RAW_DIR = REPO / "data" / "forex_raw"

VENUE = "histdata"
TIMEFRAME = "4h"  # default; overridable via --tf (e.g. 1h). PK isolates timeframes.
SOURCE_TZ = "America/New_York"  # HistData M1 ASCII is US Eastern (EST/EDT)

# Per-symbol contract. Keyed by display symbol (VENUE/SYMBOL/TF/ts is the PK).
#   fxpair    : HistData's pair code (used for URLs + zip filenames).
#   base/quote: stored in instruments dimension.
#   tick_size : smallest price increment. JPY pairs quote to 3 decimals
#               (pip=0.01, tick=0.001); USD-quote majors quote to 5 decimals
#               (pip=0.0001, tick=0.00001).
#   px_lo/px_hi: plausibility band for price-anomaly sanity (raw kept either way).
SYMBOLS = {
    "EUR/USD": {"fxpair": "EURUSD", "base": "EUR", "quote": "USD",
                "tick_size": 0.00001, "px_lo": 0.5, "px_hi": 2.0},
    "GBP/USD": {"fxpair": "GBPUSD", "base": "GBP", "quote": "USD",
                "tick_size": 0.00001, "px_lo": 0.8, "px_hi": 2.5},
    "USD/JPY": {"fxpair": "USDJPY", "base": "USD", "quote": "JPY",
                "tick_size": 0.001, "px_lo": 70.0, "px_hi": 200.0},
    # --- diversification batch (all 5-decimal majors, pip=0.0001, tick=0.00001) ---
    # NOTE: these are USD-quote / cross majors quoting to 5 decimals like EUR/USD,
    # NOT JPY-style 3-decimal. Scale bands are per-pair price levels (2020-2025).
    "AUD/USD": {"fxpair": "AUDUSD", "base": "AUD", "quote": "USD",
                "tick_size": 0.00001, "px_lo": 0.50, "px_hi": 0.85},
    "USD/CHF": {"fxpair": "USDCHF", "base": "USD", "quote": "CHF",
                "tick_size": 0.00001, "px_lo": 0.70, "px_hi": 1.05},
    "EUR/GBP": {"fxpair": "EURGBP", "base": "EUR", "quote": "GBP",
                "tick_size": 0.00001, "px_lo": 0.78, "px_hi": 0.95},
    "USD/CAD": {"fxpair": "USDCAD", "base": "USD", "quote": "CAD",
                "tick_size": 0.00001, "px_lo": 1.15, "px_hi": 1.50},
    "NZD/USD": {"fxpair": "NZDUSD", "base": "NZD", "quote": "USD",
                "tick_size": 0.00001, "px_lo": 0.50, "px_hi": 0.78},
}

BASE = "https://www.histdata.com"
PAGE_FMT = BASE + "/download-free-forex-historical-data/?/ascii/1-minute-bar-quotes/{pair}/{year}"
GET_URL = BASE + "/get.php"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36",
}
BLOCK_PAGE_IP = "195.175.254.2"  # Turkish ISP block-page sentinel


def fetch_year_zip(session: requests.Session, year: int, fxpair: str) -> bytes:
    """Download one full-year M1 ASCII zip. Fails loud on any problem."""
    page_url = PAGE_FMT.format(pair=fxpair.lower(), year=year)
    r = session.get(page_url, headers=HEADERS, timeout=30)
    r.raise_for_status()
    m = re.search(r'name="tk"\s+id="tk"\s+value="([0-9a-f]+)"', r.text)
    if not m:
        raise RuntimeError(f"[{year}] no token (tk) found — page layout changed or blocked")
    tk = m.group(1)

    backoff = 2.0
    for attempt in range(1, 5):
        resp = session.post(
            GET_URL,
            headers={**HEADERS, "Referer": page_url},
            data={
                "tk": tk,
                "date": str(year),
                "datemonth": str(year),
                "platform": "ASCII",
                "timeframe": "M1",
                "fxpair": fxpair,
            },
            timeout=120,
        )
        if resp.status_code == 429:
            print(f"[{year}] 429 rate-limited, backoff {backoff}s")
            time.sleep(backoff)
            backoff *= 2
            continue
        resp.raise_for_status()
        content = resp.content
        if not content[:2] == b"PK":
            raise RuntimeError(
                f"[{year}] response not a zip (got {len(content)}B, "
                f"starts {content[:32]!r}) — possibly blocked/expired token"
            )
        return content
    raise RuntimeError(f"[{year}] exhausted retries (rate limit)")


def parse_zip_to_m1(content: bytes, year: int) -> pd.DataFrame:
    zf = zipfile.ZipFile(io.BytesIO(content))
    csv_name = next(n for n in zf.namelist() if n.lower().endswith(".csv"))
    with zf.open(csv_name) as fh:
        df = pd.read_csv(
            fh,
            sep=";",
            header=None,
            names=["dt", "open", "high", "low", "close", "volume"],
            dtype={"open": "float64", "high": "float64", "low": "float64",
                   "close": "float64", "volume": "float64"},
        )
    # Parse naive timestamps, then localize as US Eastern -> UTC.
    naive = pd.to_datetime(df["dt"], format="%Y%m%d %H%M%S")
    local = naive.dt.tz_localize(
        SOURCE_TZ, ambiguous="NaT", nonexistent="shift_forward"
    )
    df["ts"] = local.dt.tz_convert("UTC")
    n_nat = int(df["ts"].isna().sum())
    if n_nat:
        # DST-fall-back ambiguous minutes -> drop (cannot localize unambiguously).
        # These are <=60 minutes/year and never affect 4H bar OHLC materially.
        print(f"[{year}] dropped {n_nat} DST-ambiguous M1 rows")
        df = df[df["ts"].notna()]
    return df[["ts", "open", "high", "low", "close", "volume"]]


def _pandas_offset(tf: str) -> str:
    """Map our DB timeframe label to a pandas-3.x resample offset alias.

    pandas >=3.0 dropped the bare 'm' minute alias (now reserved for month-end
    'ME'); minutes must use 'min'. Hours ('h') and days ('d') are unchanged.
    The stored DB timeframe label (e.g. '15m') is NOT altered — only the value
    handed to pd.resample(). Fails loud on an unrecognized unit.
    """
    m = re.fullmatch(r"(\d+)([a-zA-Z]+)", tf)
    if not m:
        raise ValueError(f"unparseable timeframe {tf!r}")
    n, unit = m.group(1), m.group(2).lower()
    if unit == "m":
        unit = "min"  # 15m/30m -> 15min/30min (pandas-3 minute alias)
    elif unit not in ("min", "h", "d", "w"):
        raise ValueError(f"unsupported timeframe unit {unit!r} in {tf!r}")
    return f"{n}{unit}"


def resample_tf(m1: pd.DataFrame, tf: str) -> pd.DataFrame:
    """LOOKAHEAD-CLEAN resample to tf. Bar t = OHLCV of M1s in [t, t+tf).

    label="left", closed="left": a bar stamped t aggregates only M1s in [t, t+tf),
    so no future minute ever leaks into the bar's OHLC. Empty buckets (weekends)
    are dropped, never forward-filled.
    """
    s = m1.set_index("ts").sort_index()
    agg = s.resample(_pandas_offset(tf), label="left", closed="left").agg(
        open=("open", "first"),
        high=("high", "max"),
        low=("low", "min"),
        close=("close", "last"),
        volume=("volume", "sum"),
    )
    # Drop empty buckets (weekend gaps) — do NOT forward-fill them.
    agg = agg.dropna(subset=["open", "high", "low", "close"])
    return agg.reset_index()


def ensure_schema(con: duckdb.DuckDBPyConnection) -> None:
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS ohlcv (
            venue     VARCHAR NOT NULL,
            symbol    VARCHAR NOT NULL,
            timeframe VARCHAR NOT NULL,
            ts        TIMESTAMP WITH TIME ZONE NOT NULL,
            open      DOUBLE,
            high      DOUBLE,
            low       DOUBLE,
            close     DOUBLE,
            volume    DOUBLE,
            PRIMARY KEY (venue, symbol, timeframe, ts)
        );
        """
    )
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS instruments (
            venue          VARCHAR NOT NULL,
            symbol         VARCHAR NOT NULL,
            market_type    VARCHAR NOT NULL,
            base           VARCHAR,
            quote          VARCHAR,
            listing_date   TIMESTAMP WITH TIME ZONE,
            delisting_date TIMESTAMP WITH TIME ZONE,
            tick_size      DOUBLE,
            lot_step       DOUBLE,
            is_active      BOOLEAN DEFAULT TRUE,
            PRIMARY KEY (venue, symbol, market_type)
        );
        """
    )


def upsert(con: duckdb.DuckDBPyConnection, bars: pd.DataFrame, symbol: str,
           timeframe: str) -> int:
    df = bars.copy()
    df["venue"] = VENUE
    df["symbol"] = symbol
    df["timeframe"] = timeframe
    df = df[["venue", "symbol", "timeframe", "ts", "open", "high", "low", "close", "volume"]]
    con.register("incoming", df)
    con.execute(
        """
        INSERT INTO ohlcv
        SELECT * FROM incoming
        ON CONFLICT (venue, symbol, timeframe, ts) DO UPDATE SET
            open=excluded.open, high=excluded.high, low=excluded.low,
            close=excluded.close, volume=excluded.volume;
        """
    )
    con.unregister("incoming")
    return len(df)


def quality_report(con: duckdb.DuckDBPyConnection, symbol: str, spec: dict,
                   timeframe: str) -> bool:
    df = con.execute(
        """
        SELECT ts, open, high, low, close, volume FROM ohlcv
        WHERE venue=? AND symbol=? AND timeframe=? ORDER BY ts
        """,
        [VENUE, symbol, timeframe],
    ).fetchdf()
    n = len(df)
    print("\n" + "=" * 64)
    print(f"QUALITY REPORT — {symbol} {timeframe.upper()} (HistData)")
    print("=" * 64)
    if n == 0:
        print("NO ROWS")
        return False
    df = df.sort_values("ts").reset_index(drop=True)
    print(f"bars            : {n}")
    print(f"date range      : {df.ts.iloc[0]}  ->  {df.ts.iloc[-1]}")

    # open==close (yfinance was ~74%; price-action needs this LOW)
    eq = int((df.open == df.close).sum())
    print(f"open==close     : {eq}  ({100*eq/n:.3f}%)   [yfinance was ~74% -> reject]")

    # NaN / dup
    nan_rows = int(df[["open", "high", "low", "close"]].isna().any(axis=1).sum())
    dup = int(df.ts.duplicated().sum())
    print(f"NaN OHLC rows   : {nan_rows}")
    print(f"duplicate ts    : {dup}")

    # OHLC sanity: high>=max(o,c)>=min(o,c)>=low
    bad = df[~(
        (df.high >= df[["open", "close"]].max(axis=1))
        & (df.low <= df[["open", "close"]].min(axis=1))
        & (df.high >= df.low)
    )]
    print(f"OHLC sanity viol: {len(bad)}")

    # Gap distribution: expected `step`; weekday gaps vs weekend
    deltas = df.ts.diff().dropna()
    step = pd.Timedelta(timeframe)
    weekend = int((deltas > pd.Timedelta("12h")).sum())
    intraday_gaps = int(((deltas > step) & (deltas <= pd.Timedelta("12h"))).sum())
    print(f"normal {timeframe} steps : {int((deltas == step).sum())}")
    print(f"weekend gaps    : {weekend}  (expected ~52/yr, FX closed Fri 22:00->Sun 22:00 UTC)")
    print(f"other gaps >{timeframe}  : {intraday_gaps}  (holidays / low-liq; raw kept, NOT filled)")

    # Price anomaly: 1-bar close move >30% (flag only)
    ret = df.close.pct_change().abs()
    big = int((ret > 0.30).sum())
    print(f"price move >30% : {big}  (flagged, raw kept)")

    # Scale-aware price band: catches decimal/scale corruption (e.g. JPY ~150
    # accidentally treated like a 5-decimal major). Flag only — raw kept.
    lo, hi = spec["px_lo"], spec["px_hi"]
    oob = int(((df.close < lo) | (df.close > hi)).sum())
    print(f"price band [{lo},{hi}] : {oob} out-of-band  "
          f"(median close={df.close.median():.5f})")

    # Volume anomaly note (FX M1 from HistData has no real volume)
    vol_zero = int((df.volume == 0).sum())
    print(f"volume==0 bars  : {vol_zero}  (HistData FX has no exchange volume — expected)")
    print("=" * 64)

    verdict_ok = (
        (eq / n < 0.02) and nan_rows == 0 and dup == 0
        and len(bad) == 0 and oob == 0
    )
    print(f"PRICE-ACTION USABLE: {'YES — clean' if verdict_ok else 'REVIEW NEEDED'}")
    print("=" * 64 + "\n")
    return verdict_ok


def ingest_symbol(con: duckdb.DuckDBPyConnection, session: requests.Session,
                  symbol: str, spec: dict, years: list[int],
                  timeframe: str) -> bool:
    fxpair = spec["fxpair"]
    all_bars = []
    for year in years:
        cache = RAW_DIR / f"DAT_ASCII_{fxpair}_M1_{year}.zip"
        if cache.exists() and cache.stat().st_size > 1000:
            print(f"[{symbol} {year}] using cached zip {cache.name}")
            content = cache.read_bytes()
        else:
            print(f"[{symbol} {year}] downloading from HistData...")
            content = fetch_year_zip(session, year, fxpair)
            cache.write_bytes(content)
            print(f"[{symbol} {year}] saved {len(content)} bytes")
            time.sleep(1.0)  # be polite
        m1 = parse_zip_to_m1(content, year)
        bars = resample_tf(m1, timeframe)
        print(f"[{symbol} {year}] M1 rows={len(m1)} -> {timeframe} bars={len(bars)}")
        all_bars.append(bars)

    combined = (
        pd.concat(all_bars, ignore_index=True)
        .drop_duplicates("ts").sort_values("ts")
    )
    n = upsert(con, combined, symbol, timeframe)
    con.execute(
        """
        INSERT INTO instruments (venue, symbol, market_type, base, quote,
            listing_date, delisting_date, tick_size, lot_step, is_active)
        VALUES (?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT (venue, symbol, market_type) DO UPDATE SET
            listing_date=excluded.listing_date, is_active=excluded.is_active;
        """,
        [VENUE, symbol, "forex", spec["base"], spec["quote"],
         combined.ts.iloc[0].to_pydatetime(), None, spec["tick_size"], 1000.0, True],
    )
    print(f"\n[{symbol}] upserted {n} rows ({timeframe}) into {DB_PATH}")
    return quality_report(con, symbol, spec, timeframe)


def main(years: list[int], symbols: list[str], timeframe: str) -> None:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    session = requests.Session()

    con = duckdb.connect(str(DB_PATH))
    ensure_schema(con)
    results = {}
    for symbol in symbols:
        spec = SYMBOLS[symbol]
        results[symbol] = ingest_symbol(con, session, symbol, spec, years, timeframe)
    con.close()

    print("\n" + "#" * 64)
    print("SUMMARY")
    for symbol, ok in results.items():
        print(f"  {symbol:10s} : {'CLEAN' if ok else 'REVIEW NEEDED'}")
    print("#" * 64)


if __name__ == "__main__":
    # Usage: forex_ingest_histdata.py [--symbols EUR/USD,GBP/USD] [years...]
    args = sys.argv[1:]
    syms = ["EUR/USD", "GBP/USD", "USD/JPY"]
    tf = TIMEFRAME
    yrs = []
    i = 0
    while i < len(args):
        if args[i] == "--symbols":
            syms = [s.strip().upper() for s in args[i + 1].split(",")]
            i += 2
        elif args[i] == "--tf":
            tf = args[i + 1].strip().lower()
            i += 2
        else:
            yrs.append(int(args[i]))
            i += 1
    if not yrs:
        yrs = [2020, 2021, 2022, 2023, 2024, 2025]
    for s in syms:
        if s not in SYMBOLS:
            raise SystemExit(f"unknown symbol {s!r}; known: {list(SYMBOLS)}")
    print(f"Target symbols: {syms}")
    print(f"Target years  : {yrs}")
    print(f"Target tf     : {tf}")
    main(yrs, syms, tf)
