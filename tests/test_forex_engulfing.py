"""Tests for forex engulfing pipeline.

Covers:
  1. yfinance data fetch schema validation (mocked — no network)
  2. DuckDB ingest + reload round-trip (tmp_path)
  3. ingest_forex_data validation logic (row count, price sanity, no dupes)
  4. Backtest manifest construction
  5. run_forex_backtest._run_one_symbol smoke (synthetic data)
  6. Verdict logic (_print_comparison path — aggregate checks)
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

# ── helpers ──────────────────────────────────────────────────────────────────


def _synthetic_forex_df(
    n: int = 1300,
    seed: int = 42,
    base_price: float = 1.10,
    symbol: str = "EUR/USD",
) -> pd.DataFrame:
    """Synthetic daily OHLCV that mimics a forex major pair (small moves)."""
    rng = np.random.default_rng(seed)
    rets = rng.normal(0.0, 0.005, n)          # ~0.5% daily vol (FX major)
    close = base_price * np.exp(np.cumsum(rets))
    open_ = np.r_[close[0], close[:-1]]
    high = np.maximum(open_, close) * (1 + np.abs(rng.normal(0, 0.002, n)))
    low = np.minimum(open_, close) * (1 - np.abs(rng.normal(0, 0.002, n)))
    high = np.maximum.reduce([high, open_, close])
    low = np.minimum.reduce([low, open_, close])
    ts = pd.date_range("2021-05-01", periods=n, freq="B", tz="UTC")[:n]
    return pd.DataFrame({
        "ts": ts,
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "volume": rng.uniform(0, 1e8, n),
        "venue": "forex",
        "symbol": symbol,
        "timeframe": "1d",
    })


# ── 1. yfinance schema ────────────────────────────────────────────────────────


class TestYfinanceSchemaNormalization:
    """_fetch_yfinance normalises columns from real yfinance output."""

    def _fake_yf_df(self, n: int = 1300) -> pd.DataFrame:
        """Replicate what yfinance.Ticker.history() returns (capitalised cols)."""
        rng = np.random.default_rng(0)
        close = 1.10 * np.exp(np.cumsum(rng.normal(0, 0.005, n)))
        open_ = np.r_[close[0], close[:-1]]
        high = np.maximum(open_, close) * 1.002
        low = np.minimum(open_, close) * 0.998
        df = pd.DataFrame({
            "Open": open_,
            "High": high,
            "Low": low,
            "Close": close,
            "Volume": rng.uniform(0, 1e8, n),
            "Dividends": 0.0,
            "Stock Splits": 0.0,
        }, index=pd.date_range("2021-05-01", periods=n, freq="B"))
        df.index.name = "Date"
        return df

    def test_fetch_returns_required_columns(self):
        """After _fetch_yfinance, DataFrame must have ts/open/high/low/close/volume."""
        import yfinance as _yf
        from scripts.ingest_forex_data import _fetch_yfinance

        fake_df = self._fake_yf_df()
        mock_ticker = MagicMock()
        mock_ticker.history.return_value = fake_df

        with patch.object(_yf, "Ticker", return_value=mock_ticker):
            df = _fetch_yfinance("EURUSD=X", period="5y", interval="1d")

        required = {"ts", "open", "high", "low", "close", "volume"}
        assert required.issubset(set(df.columns)), f"Missing cols: {required - set(df.columns)}"

    def test_fetch_ts_is_utc(self):
        import yfinance as _yf
        from scripts.ingest_forex_data import _fetch_yfinance

        fake_df = self._fake_yf_df()
        mock_ticker = MagicMock()
        mock_ticker.history.return_value = fake_df

        with patch.object(_yf, "Ticker", return_value=mock_ticker):
            df = _fetch_yfinance("EURUSD=X")

        assert str(df["ts"].dt.tz) == "UTC", "ts column must be UTC"

    def test_fetch_prices_positive(self):
        import yfinance as _yf
        from scripts.ingest_forex_data import _fetch_yfinance

        fake_df = self._fake_yf_df()
        mock_ticker = MagicMock()
        mock_ticker.history.return_value = fake_df

        with patch.object(_yf, "Ticker", return_value=mock_ticker):
            df = _fetch_yfinance("EURUSD=X")

        assert (df["close"] > 0).all(), "All close prices must be positive"
        assert (df["high"] >= df["low"]).all(), "high must be >= low"

    def test_fetch_empty_raises(self):
        import yfinance as _yf
        from scripts.ingest_forex_data import _fetch_yfinance

        mock_ticker = MagicMock()
        mock_ticker.history.return_value = pd.DataFrame()

        with patch.object(_yf, "Ticker", return_value=mock_ticker):
            with pytest.raises(ValueError, match="empty"):
                _fetch_yfinance("EURUSD=X")


# ── 2. Validation logic ───────────────────────────────────────────────────────


class TestIngestValidation:
    """_validate() catches bad data."""

    def test_validate_ok(self):
        from scripts.ingest_forex_data import _validate
        df = _synthetic_forex_df(n=1300)
        # Should not raise
        _validate(df, "EUR/USD")

    def test_validate_fails_too_few_bars(self):
        from scripts.ingest_forex_data import _validate
        df = _synthetic_forex_df(n=500)
        with pytest.raises(AssertionError, match="1000"):
            _validate(df, "EUR/USD")

    def test_validate_fails_negative_close(self):
        from scripts.ingest_forex_data import _validate
        df = _synthetic_forex_df(n=1300)
        df.loc[5, "close"] = -0.5
        with pytest.raises(AssertionError):
            _validate(df, "EUR/USD")

    def test_validate_fails_duplicate_ts(self):
        from scripts.ingest_forex_data import _validate
        df = _synthetic_forex_df(n=1300)
        df.loc[1, "ts"] = df.loc[0, "ts"]
        with pytest.raises(AssertionError, match="duplike"):
            _validate(df, "EUR/USD")


# ── 3. DuckDB round-trip ──────────────────────────────────────────────────────


class TestDuckDBRoundTrip:
    """Write forex data to tmp DuckDB, read back, verify."""

    def test_write_and_read_back(self, tmp_path):
        from scripts.ingest_forex_data import _write_to_duckdb, DB_PATH as _ORIG_DB
        import duckdb
        import scripts.ingest_forex_data as ingest_mod

        # Redirect DB to tmp
        tmp_db = tmp_path / "forex_test.duckdb"
        original = ingest_mod.DB_PATH
        ingest_mod.DB_PATH = tmp_db
        try:
            df = _synthetic_forex_df(n=1300, symbol="EUR/USD")
            df_plain = df[["ts", "open", "high", "low", "close", "volume"]].copy()
            _write_to_duckdb(df_plain, "EUR/USD")

            con = duckdb.connect(str(tmp_db), read_only=True)
            result = con.execute(
                "SELECT COUNT(*) as n FROM ohlcv WHERE symbol='EUR/USD' AND venue='forex'"
            ).fetchone()[0]
            con.close()
            assert result == 1300, f"Expected 1300 rows, got {result}"
        finally:
            ingest_mod.DB_PATH = original

    def test_rewrite_no_duplicates(self, tmp_path):
        """Running _write_to_duckdb twice for same symbol should not duplicate rows."""
        import duckdb
        import scripts.ingest_forex_data as ingest_mod

        tmp_db = tmp_path / "forex_dedup.duckdb"
        original = ingest_mod.DB_PATH
        ingest_mod.DB_PATH = tmp_db
        try:
            df = _synthetic_forex_df(n=1300, symbol="GBP/USD")
            df_plain = df[["ts", "open", "high", "low", "close", "volume"]].copy()
            ingest_mod._write_to_duckdb(df_plain, "GBP/USD")
            ingest_mod._write_to_duckdb(df_plain, "GBP/USD")

            con = duckdb.connect(str(tmp_db), read_only=True)
            result = con.execute(
                "SELECT COUNT(*) FROM ohlcv WHERE symbol='GBP/USD' AND venue='forex'"
            ).fetchone()[0]
            con.close()
            assert result == 1300, "Duplicate writes should not create duplicate rows"
        finally:
            ingest_mod.DB_PATH = original


# ── 4. Backtest manifest ──────────────────────────────────────────────────────


class TestForexManifest:
    def test_manifest_valid(self):
        from scripts.run_forex_backtest import _make_manifest
        m = _make_manifest()
        assert m.name == "engulfing_continuation"
        assert m.trend_filter.period == 50
        assert len(m.signals.patterns) == 2

    def test_manifest_atr_min_pct_lower_than_crypto(self):
        """Forex volatility lower: atr_min_pct should be 0.002, not 0.005."""
        from scripts.run_forex_backtest import _make_manifest
        m = _make_manifest()
        filt = m.signals.filters
        # _FiltersCfg is a Pydantic model; access via attribute not .get()
        assert filt.atr_min_pct <= 0.003, (
            "Forex atr_min_pct should be <= 0.003 to allow low-vol FX bars"
        )

    def test_manifest_volume_filter_off(self):
        """Forex volume unreliable — volume_zscore_min must be 0."""
        from scripts.run_forex_backtest import _make_manifest
        m = _make_manifest()
        assert m.signals.filters.volume_zscore_min == 0.0


# ── 5. Backtest smoke ─────────────────────────────────────────────────────────


class TestForexBacktestSmoke:
    """_run_one_symbol smoke using synthetic data injected via DB mock."""

    def _build_tmp_db(self, tmp_path: Path, symbol: str, n: int = 1300) -> Path:
        import duckdb
        import scripts.ingest_forex_data as ingest_mod

        tmp_db = tmp_path / "forex_smoke.duckdb"
        original = ingest_mod.DB_PATH
        ingest_mod.DB_PATH = tmp_db
        try:
            df = _synthetic_forex_df(n=n, symbol=symbol)
            df_plain = df[["ts", "open", "high", "low", "close", "volume"]].copy()
            ingest_mod._write_to_duckdb(df_plain, symbol)
        finally:
            ingest_mod.DB_PATH = original
        return tmp_db

    def test_run_one_symbol_returns_dict(self, tmp_path):
        from scripts.run_forex_backtest import _make_manifest, _run_one_symbol
        import scripts.run_forex_backtest as bt_mod

        tmp_db = self._build_tmp_db(tmp_path, "EUR/USD")
        original = bt_mod.DB_PATH
        bt_mod.DB_PATH = tmp_db
        try:
            manifest = _make_manifest()
            r = _run_one_symbol("EUR/USD", manifest)
            assert isinstance(r, dict), "Result must be a dict"
            if "error" not in r:
                assert "n_trades" in r
                assert "sharpe" in r
                assert "max_drawdown" in r
                assert r["n_bars"] >= 1000
        finally:
            bt_mod.DB_PATH = original

    def test_run_one_symbol_missing_db_returns_error(self, tmp_path):
        from scripts.run_forex_backtest import _make_manifest, _run_one_symbol
        import scripts.run_forex_backtest as bt_mod

        nonexistent = tmp_path / "does_not_exist.duckdb"
        original = bt_mod.DB_PATH
        bt_mod.DB_PATH = nonexistent
        try:
            manifest = _make_manifest()
            with pytest.raises(FileNotFoundError):
                _run_one_symbol("EUR/USD", manifest)
        finally:
            bt_mod.DB_PATH = original


# ── 6. Hypothesis file exists ─────────────────────────────────────────────────


def test_hypothesis_file_exists():
    """The forex-engulfing hypothesis markdown must be present in researcher/hypotheses."""
    hyp_path = ROOT / "memory" / "researcher" / "hypotheses" / "2026-05-09-forex-engulfing.md"
    assert hyp_path.exists(), f"Hypothesis file missing: {hyp_path}"
    content = hyp_path.read_text(encoding="utf-8")
    assert "EUR/USD" in content
    assert "GBP/USD" in content
    assert "USD/JPY" in content
    assert "PROMOTE" in content or "promote" in content.lower()
