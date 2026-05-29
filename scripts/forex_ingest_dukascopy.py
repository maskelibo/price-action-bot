"""Forex CLEAN ingest — Dukascopy -> data/forex_market.duckdb.

WHY THIS EXISTS
---------------
Previous forex ingest used yfinance (scripts/ingest_forex_data.py) and was
PROVEN BROKEN: EUR/USD had open==close on 959/1300 daily bars (~74%), which
destroys any body-based price-action pattern detection. yfinance forex bars
are synthetic/snapshot quotes, not real OHLC.

Dukascopy publishes tick-level bid/ask history (15-20y) and is the free
"gold standard" for FX. We pull both BID and ASK sides, build a MID OHLC for
analysis, and KEEP the spread (ask-bid) so a downstream cost model can use it.

HARD RULES (Data Engineering contract)
--------------------------------------
- Separate DB file: data/forex_market.duckdb. NEVER touch crypto DBs
  (market.duckdb, futures_journal*.duckdb, etc.).
- All timestamps UTC, tz-aware. Dukascopy serves GMT/UTC; we verify.
- NO forward-fill, NO winsorize, NO clip. Surface anomalies, keep raw data.
- Fail loud: if a fetch returns empty for the full range, raise.

SCHEMA (compatible with crypto market.duckdb `ohlcv`)
-----------------------------------------------------
ohlcv(venue, symbol, timeframe, ts, open, high, low, close, volume,
      bid_close, ask_close, spread)
  - open/high/low/close = MID (mean of bid & ask side)
  - bid_close / ask_close = per-side close
  - spread = ask_close - bid_close  (in price units; *1e4 = pips for EUR/USD)
  - volume = Dukascopy tick volume (sum of bid+ask side volume)

Run:
    PYTHONPATH=src python scripts/forex_ingest_dukascopy.py
    PYTHONPATH=src python scripts/forex_ingest_dukascopy.py --years 10
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import duckdb
import pandas as pd

import dukascopy_python as dp
from dukascopy_python.instruments import INSTRUMENT_FX_MAJORS_EUR_USD

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "forex_market.duckdb"

# Guard: never let this script open a crypto DB by accident.
_FORBIDDEN_DB_SUBSTR = ("market.duckdb", "futures_journal", "paper_journal", "pyramid_store")
assert DB_PATH.name == "forex_market.duckdb", "DB path must be forex_market.duckdb"
for bad in _FORBIDDEN_DB_SUBSTR:
    if bad in DB_PATH.name and DB_PATH.name != "forex_market.duckdb":
        raise SystemExit(f"Refusing to touch crypto DB: {DB_PATH}")

# Hosts the dukascopy-python lib talks to. We preflight these so we FAIL LOUD
# with a clear diagnosis instead of hanging forever (the lib's requests.get has
# NO timeout -> on a DPI/SNI-censored network it blocks indefinitely).
#
# KNOWN ENVIRONMENT ISSUE (observed 2026-05-29 from this host):
#   *.dukascopy.com is blocked by SNI-based DPI. TCP connects, but the TLS
#   ClientHello with a dukascopy SNI is RST ("Connection reset by peer"); ISP
#   DNS also hijacks the names to a single block-page IP (195.175.254.2) with a
#   self-signed cert. Run this script from an un-censored network / VPN.
_PREFLIGHT_URL = "https://freeserv.dukascopy.com/2.0/index.php?path=common/instruments"

VENUE = "dukascopy"
SYMBOL = "EUR/USD"
TIMEFRAME = "4h"
INSTRUMENT = INSTRUMENT_FX_MAJORS_EUR_USD
INTERVAL = dp.INTERVAL_HOUR_4

# The freeserv JSON API paginates internally via a `last_update` cursor with a
# 30000-row limit. For 4H bars, 10y ~= 22000 bars < 30000, so a single fetch()
# call covers the whole range (it auto-paginates if needed). We do NOT chunk by
# year -- that would multiply slow round-trips for no benefit. fetch() handles
# pagination + exponential-ish retry (sleep 1s, max_retries) internally.
MAX_RETRIES = 7


def preflight() -> None:
    """Verify Dukascopy is reachable. Fail loud (not hang) if censored/down."""
    import requests

    try:
        r = requests.get(
            _PREFLIGHT_URL,
            headers={"User-Agent": "Mozilla/5.0", "Host": "freeserv.dukascopy.com"},
            timeout=15,  # the upstream lib has NO timeout; we enforce one here
        )
        r.raise_for_status()
    except Exception as e:  # noqa: BLE001 - surface everything
        raise SystemExit(
            "FAIL LOUD: cannot reach Dukascopy (freeserv.dukascopy.com).\n"
            f"  error: {type(e).__name__}: {str(e)[:200]}\n"
            "  Likely cause: SNI/DNS censorship or block on *.dukascopy.com from\n"
            "  this network (observed: TLS RST + ISP DNS hijack to 195.175.254.2).\n"
            "  Fix: run from an un-censored network / VPN, then re-run this script.\n"
            "  DO NOT silently fall back to yfinance (proven broken: ~74% open==close)."
        ) from e


def _normalize(df: pd.DataFrame, side: str) -> pd.DataFrame:
    """Return tidy frame: ts(UTC), open/high/low/close/volume for one side."""
    if df is None or df.empty:
        return pd.DataFrame(columns=["ts", "open", "high", "low", "close", "volume"])
    out = df.copy()
    out = out.reset_index()
    # index is the bar timestamp; its name varies ("timestamp" / "index")
    ts_col = out.columns[0]
    out = out.rename(columns={ts_col: "ts"})
    out.columns = [str(c).lower() for c in out.columns]
    out["ts"] = pd.to_datetime(out["ts"], utc=True)
    keep = ["ts", "open", "high", "low", "close", "volume"]
    for c in keep:
        if c not in out.columns:
            out[c] = pd.NA
    out = out[keep].sort_values("ts").reset_index(drop=True)
    out = out.add_suffix(f"_{side}").rename(columns={f"ts_{side}": "ts"})
    return out


def _fetch_side(side_const: str, side: str, start: datetime, end: datetime) -> pd.DataFrame:
    """Fetch one offer side across the full range (single auto-paginated call)."""
    print(f"  [{side}] fetch {start.date()} -> {end.date()} ...", flush=True)
    df = dp.fetch(INSTRUMENT, INTERVAL, side_const, start, end, max_retries=MAX_RETRIES)
    n = 0 if df is None else len(df)
    print(f"  [{side}] rows={n}", flush=True)
    if not n:
        return pd.DataFrame()
    out = _normalize(df, side)
    out = out.drop_duplicates(subset=["ts"]).sort_values("ts").reset_index(drop=True)
    return out


def fetch_mid(start: datetime, end: datetime) -> pd.DataFrame:
    """Fetch BID and ASK, join on ts, build MID + spread. No fill/clip."""
    bid = _fetch_side(dp.OFFER_SIDE_BID, "bid", start, end)
    ask = _fetch_side(dp.OFFER_SIDE_ASK, "ask", start, end)
    if bid.empty and ask.empty:
        raise RuntimeError(
            "FAIL LOUD: Dukascopy returned ZERO rows for both bid and ask "
            f"over {start.date()}..{end.date()}. Check connectivity / instrument."
        )
    # Inner join on bar timestamp. We do NOT forward-fill missing sides.
    m = pd.merge(bid, ask, on="ts", how="outer").sort_values("ts").reset_index(drop=True)

    # MID OHLC = mean(bid, ask) per field. If one side missing -> NaN (surfaced).
    for f in ("open", "high", "low", "close"):
        m[f] = (m[f"{f}_bid"] + m[f"{f}_ask"]) / 2.0
    m["volume"] = m[["volume_bid", "volume_ask"]].sum(axis=1, skipna=True)
    m["bid_close"] = m["close_bid"]
    m["ask_close"] = m["close_ask"]
    m["spread"] = m["ask_close"] - m["bid_close"]

    out = m[
        ["ts", "open", "high", "low", "close", "volume", "bid_close", "ask_close", "spread"]
    ].copy()
    out.insert(0, "timeframe", TIMEFRAME)
    out.insert(0, "symbol", SYMBOL)
    out.insert(0, "venue", VENUE)
    return out


def write_db(df: pd.DataFrame) -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(DB_PATH))
    try:
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS ohlcv (
                venue      VARCHAR NOT NULL,
                symbol     VARCHAR NOT NULL,
                timeframe  VARCHAR NOT NULL,
                ts         TIMESTAMP WITH TIME ZONE NOT NULL,
                open       DOUBLE,
                high       DOUBLE,
                low        DOUBLE,
                close      DOUBLE,
                volume     DOUBLE,
                bid_close  DOUBLE,
                ask_close  DOUBLE,
                spread     DOUBLE,
                PRIMARY KEY (venue, symbol, timeframe, ts)
            )
            """
        )
        con.register("df_in", df)
        # Idempotent upsert: delete overlapping keys then insert. No silent merge.
        con.execute(
            """
            DELETE FROM ohlcv o
            USING df_in d
            WHERE o.venue=d.venue AND o.symbol=d.symbol
              AND o.timeframe=d.timeframe AND o.ts=d.ts
            """
        )
        con.execute("INSERT INTO ohlcv SELECT * FROM df_in")
        con.unregister("df_in")
    finally:
        con.close()


def quality_report(df: pd.DataFrame) -> dict:
    """Surface problems. NO correction."""
    n = len(df)
    rep: dict = {"n_bars": n}
    if n == 0:
        return rep
    rep["date_min"] = df["ts"].min().isoformat()
    rep["date_max"] = df["ts"].max().isoformat()

    # tz / UTC check
    rep["tz"] = str(df["ts"].dt.tz)

    # open==close (the yfinance breakage signature) on MID
    eq = (df["open"] == df["close"]).sum()
    rep["open_eq_close"] = int(eq)
    rep["open_eq_close_pct"] = round(100.0 * eq / n, 4)

    # NaN per column
    rep["nan"] = {c: int(df[c].isna().sum()) for c in df.columns if c != "ts"}

    # duplicates on key
    dup = df.duplicated(subset=["venue", "symbol", "timeframe", "ts"]).sum()
    rep["duplicate_keys"] = int(dup)

    # OHLC sanity violations
    bad_hl = (df["high"] < df["low"]).sum()
    bad_hi = (df["high"] < df[["open", "close"]].max(axis=1)).sum()
    bad_lo = (df["low"] > df[["open", "close"]].min(axis=1)).sum()
    rep["ohlc_high_lt_low"] = int(bad_hl)
    rep["ohlc_high_below_body"] = int(bad_hi)
    rep["ohlc_low_above_body"] = int(bad_lo)

    # spread stats (pips for EUR/USD = price * 1e4)
    sp = df["spread"].dropna()
    if len(sp):
        rep["spread_pips_median"] = round(float(sp.median()) * 1e4, 4)
        rep["spread_pips_p95"] = round(float(sp.quantile(0.95)) * 1e4, 4)
        rep["spread_negative_count"] = int((sp < 0).sum())

    # weekend gap distribution: consecutive bar dt gaps
    g = df.sort_values("ts")
    dt_hours = g["ts"].diff().dt.total_seconds() / 3600.0
    rep["gap_hours_expected"] = 4
    rep["gap_count_gt_5h"] = int((dt_hours > 5).sum())  # any non-4h gap
    rep["gap_count_weekend_like_48_72h"] = int(((dt_hours >= 48) & (dt_hours <= 80)).sum())
    rep["gap_hours_max"] = round(float(dt_hours.max()), 2)

    # price-action usability verdict
    rep["usable_for_price_action"] = bool(rep["open_eq_close_pct"] < 2.0)
    return rep


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--years", type=int, default=10, help="years of history to pull")
    ap.add_argument("--end", type=str, default=None, help="end date YYYY-MM-DD (UTC), default now")
    args = ap.parse_args()

    end = (
        datetime.fromisoformat(args.end).replace(tzinfo=timezone.utc)
        if args.end
        else datetime.now(timezone.utc)
    )
    start = end - timedelta(days=365 * args.years)
    print(f"Ingest EUR/USD 4H  {start.date()} -> {end.date()}  ({args.years}y)", flush=True)

    preflight()
    df = fetch_mid(start, end)
    print(f"Fetched {len(df)} merged bars.", flush=True)
    write_db(df)
    print(f"Wrote -> {DB_PATH}", flush=True)

    rep = quality_report(df)
    import json

    print("=== QUALITY REPORT ===", flush=True)
    print(json.dumps(rep, indent=2, default=str), flush=True)


if __name__ == "__main__":
    main()
