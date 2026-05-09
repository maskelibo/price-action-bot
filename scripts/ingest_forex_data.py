"""Forex major pairs ingest — yfinance -> data/forex_market.duckdb.

Pairs: EUR/USD (EURUSD=X), GBP/USD (GBPUSD=X), USD/JPY (JPY=X)
Timeframe: 1D, 5 years
Schema: ts, open, high, low, close, volume — same as market.duckdb

AYRI dosya: data/forex_market.duckdb (crypto data'ya dokunma!)

Calistirma:
    PYTHONPATH=src python scripts/ingest_forex_data.py
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

DB_PATH = ROOT / "data" / "forex_market.duckdb"

# (display_name, yfinance_ticker, internal_symbol)
FOREX_PAIRS = [
    ("EUR/USD", "EURUSD=X", "EUR/USD"),
    ("GBP/USD", "GBPUSD=X", "GBP/USD"),
    ("USD/JPY", "JPY=X",    "USD/JPY"),
]

VENUE = "forex"
TIMEFRAME = "1d"


def _fetch_yfinance(ticker: str, period: str = "5y", interval: str = "1d") -> pd.DataFrame:
    """yfinance'den OHLCV cek, schema normalize et."""
    import yfinance as yf

    raw = yf.Ticker(ticker).history(period=period, interval=interval)
    if raw.empty:
        raise ValueError(f"yfinance returned empty DataFrame for ticker={ticker!r}")

    raw = raw.reset_index()

    # Kolon adlarini normalize et (yfinance version farkliliklari)
    raw.columns = [c.lower() for c in raw.columns]

    # Tarih kolonu: 'date' veya 'datetime'
    date_col = "date" if "date" in raw.columns else "datetime"
    raw = raw.rename(columns={date_col: "ts"})

    # ts -> UTC datetime
    raw["ts"] = pd.to_datetime(raw["ts"], utc=True)

    # Volume: yfinance forex icin bazen 0 veya NaN — 0 ile doldur
    if "volume" not in raw.columns:
        raw["volume"] = 0.0
    raw["volume"] = raw["volume"].fillna(0.0).astype(float)

    out = raw[["ts", "open", "high", "low", "close", "volume"]].copy()
    out = out.dropna(subset=["open", "high", "low", "close"])
    out = out.sort_values("ts").reset_index(drop=True)
    return out


def _validate(df: pd.DataFrame, symbol: str) -> None:
    """Temel kalite kontrolleri."""
    assert not df.empty, f"{symbol}: DataFrame bos"
    n = len(df)
    # 5 yil ~ 260 is gunu/yil * 5 = 1300; 1000 minimum bar bekle
    assert n >= 1000, f"{symbol}: Beklenen >= 1000 bar, gelen {n}"
    # Fiyatlar pozitif olmali
    assert (df["close"] > 0).all(), f"{symbol}: Negatif/sifir close var"
    assert (df["high"] >= df["low"]).all(), f"{symbol}: high < low var"
    # Duplikasyon yok
    dupes = df["ts"].duplicated().sum()
    assert dupes == 0, f"{symbol}: {dupes} duplike ts var"
    print(f"    [VALIDATE OK] {symbol}: {n} bars, {df['ts'].iloc[0].date()} -> {df['ts'].iloc[-1].date()}")


def _write_to_duckdb(df: pd.DataFrame, symbol: str) -> None:
    """DuckDB'ye yaz (upsert — tekrar calistirmada duplikasyon olmaz)."""
    import duckdb

    con = duckdb.connect(str(DB_PATH))
    try:
        con.execute("""
            CREATE TABLE IF NOT EXISTS ohlcv (
                ts        TIMESTAMPTZ NOT NULL,
                venue     VARCHAR     NOT NULL,
                symbol    VARCHAR     NOT NULL,
                timeframe VARCHAR     NOT NULL,
                open      DOUBLE      NOT NULL,
                high      DOUBLE      NOT NULL,
                low       DOUBLE      NOT NULL,
                close     DOUBLE      NOT NULL,
                volume    DOUBLE      NOT NULL,
                PRIMARY KEY (venue, symbol, timeframe, ts)
            )
        """)

        # Mevcut kayitlari sil (temiz yeniden yukle)
        con.execute(
            "DELETE FROM ohlcv WHERE venue=? AND symbol=? AND timeframe=?",
            [VENUE, symbol, TIMEFRAME],
        )

        df_insert = df.copy()
        df_insert["venue"] = VENUE
        df_insert["symbol"] = symbol
        df_insert["timeframe"] = TIMEFRAME

        con.execute("""
            INSERT INTO ohlcv (ts, venue, symbol, timeframe, open, high, low, close, volume)
            SELECT ts, venue, symbol, timeframe, open, high, low, close, volume
            FROM df_insert
        """)

        count = con.execute(
            "SELECT COUNT(*) FROM ohlcv WHERE venue=? AND symbol=? AND timeframe=?",
            [VENUE, symbol, TIMEFRAME],
        ).fetchone()[0]
        print(f"    [DB] {symbol}: {count} rows yazildi -> {DB_PATH.name}")
    finally:
        con.close()


def main() -> int:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    print(f"=== Forex Data Ingest — yfinance 5y 1D ===")
    print(f"    Target DB: {DB_PATH}\n")

    errors: list[str] = []
    summary: list[dict] = []

    for display, ticker, symbol in FOREX_PAIRS:
        print(f"  [{display}] ticker={ticker}")
        try:
            df = _fetch_yfinance(ticker, period="5y", interval="1d")
            _validate(df, symbol)
            _write_to_duckdb(df, symbol)
            summary.append({
                "symbol": symbol,
                "ticker": ticker,
                "n_bars": len(df),
                "first": str(df["ts"].iloc[0].date()),
                "last": str(df["ts"].iloc[-1].date()),
                "status": "ok",
            })
        except Exception as exc:
            msg = f"{symbol}: {type(exc).__name__}: {exc}"
            print(f"    [ERROR] {msg}")
            errors.append(msg)
            summary.append({"symbol": symbol, "ticker": ticker, "status": "error", "error": str(exc)})

    print("\n" + "=" * 60)
    print("INGEST OZET")
    print("=" * 60)
    for s in summary:
        if s["status"] == "ok":
            print(f"  {s['symbol']:<10} {s['n_bars']:>5} bars  {s['first']} -> {s['last']}  OK")
        else:
            print(f"  {s['symbol']:<10} ERROR: {s.get('error', '')}")

    if errors:
        print(f"\n  {len(errors)} hata olustu.")
        return 1

    print(f"\n  Tum {len(FOREX_PAIRS)} pair basariyla yuklendi.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
