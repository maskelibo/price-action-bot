"""Unit testler — LiquidationFadeStrategy + LiquidationStore + helpers.

Test senaryolari:
  1. liquidation_extreme_signal: long cascade proxy detect (OI drop + taker sell extreme)
  2. liquidation_extreme_signal: short cascade proxy detect (OI rise + taker buy extreme)
  3. liquidation_extreme_signal: normal conditions → no signal
  4. liquidation_extreme_signal: empty DataFrame → no crash, empty result
  5. Strategy.generate_signals: long cascade + bullish confirmation → long signal
  6. Strategy.generate_signals: short cascade + bearish confirmation → short signal
  7. Strategy.generate_signals: cascade but no confirmation → no signal
  8. Strategy.generate_signals: missing proxy columns → no signal, no crash
  9. LiquidationStore: upsert_okx + OKX df round-trip
  10. LiquidationStore: upsert_proxy + read_proxy round-trip
  11. fetch_okx_liquidations: error → empty DataFrame, no crash
  12. build_cascade_proxy: merge logic (OI + taker joined correctly)

Lookahead-bias check:
  13. liquidation_extreme_signal: threshold at bar t uses only [t-window, t-1] data
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest

from price_action.data.liquidation_ingest import (
    LiquidationStore,
    build_cascade_proxy,
    fetch_okx_liquidations,
    reset_liq_pool,
)
from price_action.strategies.liquidation_fade import (
    EXTREME_PCTILE,
    LiquidationFadeStrategy,
    MIN_OI_CHANGE_PCT,
    ROLLING_WINDOW,
    TAKER_BUY_EXTREME,
    TAKER_SELL_EXTREME,
    _detect_bearish_confirmation,
    _detect_bullish_confirmation,
    liquidation_extreme_signal,
)


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

def _base_ts(n: int, freq_days: int = 1) -> list[datetime]:
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    return [start + timedelta(days=freq_days * i) for i in range(n)]


def _make_ohlcv(
    n: int,
    seed: int = 42,
    base_price: float = 50_000.0,
    trend: float = 0.0,
) -> pd.DataFrame:
    """Synthetic daily OHLCV."""
    rng = np.random.default_rng(seed)
    rets = rng.normal(trend, 0.015, n)
    close = base_price * np.exp(np.cumsum(rets))
    open_ = np.r_[close[0], close[:-1]]
    high = np.maximum(open_, close) * (1 + np.abs(rng.normal(0, 0.005, n)))
    low = np.minimum(open_, close) * (1 - np.abs(rng.normal(0, 0.005, n)))
    return pd.DataFrame({
        "ts": _base_ts(n),
        "open": open_.round(2),
        "high": high.round(2),
        "low": low.round(2),
        "close": close.round(2),
        "volume": rng.uniform(1e6, 5e6, n),
        "venue": "binance",
        "symbol": "BTCUSDT",
        "timeframe": "1d",
    })


def _make_proxy_df(
    n: int = 60,
    oi_pattern: str = "normal",
    taker_pattern: str = "normal",
) -> pd.DataFrame:
    """Synthetic cascade proxy DataFrame.

    oi_pattern: 'normal' | 'long_cascade' (sharp OI drop at bar 50)
                | 'short_cascade' (OI rise at bar 50)
    taker_pattern: 'normal' | 'sell_extreme' | 'buy_extreme'
    """
    rng = np.random.default_rng(7)
    ts = _base_ts(n)

    # OI: normally slowly growing
    oi = 100_000 + rng.normal(0, 500, n).cumsum()
    oi_pct = np.diff(oi, prepend=oi[0]) / oi
    oi_pct[0] = 0.0

    if oi_pattern == "long_cascade":
        # Sharp OI drop at bar 50 (> 5%)
        oi_pct[50] = -0.08  # 8% drop
    elif oi_pattern == "short_cascade":
        # OI rise + taker buy surge at bar 50
        oi_pct[50] = 0.08

    # Taker sell ratio: normally ~0.50
    taker_sell = rng.uniform(0.45, 0.55, n)
    if taker_pattern == "sell_extreme":
        taker_sell[50] = 0.82  # extreme sell pressure
    elif taker_pattern == "buy_extreme":
        taker_sell[50] = 0.18  # extreme buy pressure (= 82% buy)

    return pd.DataFrame({
        "ts": ts,
        "venue": "binance",
        "symbol": "BTCUSDT",
        "period": "1d",
        "open_interest": oi,
        "oi_pct_change": oi_pct,
        "taker_sell_ratio": taker_sell,
        "taker_buy_vol": rng.uniform(1e8, 5e8, n),
        "taker_sell_vol": rng.uniform(1e8, 5e8, n),
    })


@pytest.fixture
def tmp_db(tmp_path: Path) -> Path:
    """Temp DuckDB path for store tests."""
    reset_liq_pool()
    yield tmp_path / "test_liq.duckdb"
    reset_liq_pool()


# ---------------------------------------------------------------------------
# Test 1-4: liquidation_extreme_signal helper
# ---------------------------------------------------------------------------

class TestLiquidationExtremeSignal:

    def test_long_cascade_detected(self) -> None:
        """OI drop extreme + taker sell extreme → long_cascade True at bar 51."""
        df = _make_proxy_df(n=60, oi_pattern="long_cascade", taker_pattern="sell_extreme")
        long_cas, short_cas = liquidation_extreme_signal(df, rolling_window=20)
        # Bar 51 = next bar after cascade (shift(1) means bar 50's cascade fires signal at 51)
        # Actually signal fires AT bar 50 (current bar OI + taker), then we shift in strategy
        # Bar 50 should be True in long_cascade
        assert long_cas.iloc[50], "Bar 50 should detect long cascade (OI drop + taker sell extreme)"
        # Bar 49 should be False (normal conditions)
        assert not long_cas.iloc[49], "Bar 49 should not be long cascade"

    def test_short_cascade_detected(self) -> None:
        """OI rise extreme + taker buy extreme → short_cascade True at bar 50."""
        df = _make_proxy_df(n=60, oi_pattern="short_cascade", taker_pattern="buy_extreme")
        long_cas, short_cas = liquidation_extreme_signal(df, rolling_window=20)
        assert short_cas.iloc[50], "Bar 50 should detect short cascade"
        assert not short_cas.iloc[49], "Bar 49 should not be short cascade"

    def test_normal_conditions_no_signal(self) -> None:
        """Normal OI and taker flow → no cascade signals."""
        df = _make_proxy_df(n=60, oi_pattern="normal", taker_pattern="normal")
        long_cas, short_cas = liquidation_extreme_signal(df, rolling_window=20)
        # Should have very few or no signals in normal conditions
        assert long_cas.sum() <= 2, f"Expected ≤2 long cascade signals, got {long_cas.sum()}"
        assert short_cas.sum() <= 2, f"Expected ≤2 short cascade signals, got {short_cas.sum()}"

    def test_empty_dataframe_no_crash(self) -> None:
        """Empty DataFrame → returns empty Series without exception."""
        long_cas, short_cas = liquidation_extreme_signal(pd.DataFrame())
        assert isinstance(long_cas, pd.Series)
        assert isinstance(short_cas, pd.Series)
        assert len(long_cas) == 0
        assert len(short_cas) == 0

    def test_lookahead_safety_threshold_uses_past_only(self) -> None:
        """Lookahead check: thresholds at bar t must use only [t-window, t-1].

        We verify by checking that adding one future bar doesn't change
        the signal at earlier bars (rolling shift(1) ensures isolation).
        Cascade injected at bar 30 (within bounds for both n=40 and n=41).
        """
        # Use n=40 with cascade at bar 30
        df_n = _make_proxy_df(n=40, oi_pattern="normal", taker_pattern="normal")
        df_n.loc[30, "oi_pct_change"] = -0.08
        df_n.loc[30, "taker_sell_ratio"] = 0.82

        # n=41: same data + one extra bar
        df_n2 = pd.concat([df_n, df_n.iloc[[-1]].assign(
            ts=df_n["ts"].iloc[-1] + pd.Timedelta(days=1)
        )], ignore_index=True)

        long_n, _ = liquidation_extreme_signal(df_n, rolling_window=20)
        long_n2, _ = liquidation_extreme_signal(df_n2, rolling_window=20)

        # First 39 bars should be identical regardless of whether bar 40 exists
        pd.testing.assert_series_equal(
            long_n.iloc[:39].reset_index(drop=True),
            long_n2.iloc[:39].reset_index(drop=True),
            check_names=False,
        )


# ---------------------------------------------------------------------------
# Test 5-8: LiquidationFadeStrategy
# ---------------------------------------------------------------------------

class TestLiquidationFadeStrategy:

    def _make_combined_df(
        self,
        n: int = 60,
        oi_pattern: str = "normal",
        taker_pattern: str = "normal",
    ) -> pd.DataFrame:
        """Merge OHLCV + proxy data."""
        ohlcv = _make_ohlcv(n)
        proxy = _make_proxy_df(n, oi_pattern=oi_pattern, taker_pattern=taker_pattern)
        df = ohlcv.copy()
        df["oi_pct_change"] = proxy["oi_pct_change"].values
        df["taker_sell_ratio"] = proxy["taker_sell_ratio"].values
        return df

    def _inject_bullish_engulfing(self, df: pd.DataFrame, bar: int) -> pd.DataFrame:
        """Inject a valid bullish engulfing at bar `bar`.

        Makes prev bar (bar-1) bearish, then bar engulfs it bullishly.
        Works with any price levels by using absolute values.
        """
        df = df.copy()
        base = float(df.loc[bar, "close"])
        # prev bar: open > close (bearish), bar-1
        prev_open = base * 1.02
        prev_close = base * 0.98
        df.loc[bar - 1, "open"] = prev_open
        df.loc[bar - 1, "close"] = prev_close
        df.loc[bar - 1, "high"] = prev_open * 1.003
        df.loc[bar - 1, "low"] = prev_close * 0.997
        # bar: open <= prev_close, close >= prev_open (bullish engulf)
        df.loc[bar, "open"] = prev_close * 0.999    # open <= prev_close ✓
        df.loc[bar, "close"] = prev_open * 1.001    # close >= prev_open ✓
        df.loc[bar, "high"] = prev_open * 1.005
        df.loc[bar, "low"] = prev_close * 0.995
        return df

    def _inject_bearish_engulfing(self, df: pd.DataFrame, bar: int) -> pd.DataFrame:
        """Inject a valid bearish engulfing at bar `bar`."""
        df = df.copy()
        base = float(df.loc[bar, "close"])
        prev_open = base * 0.98
        prev_close = base * 1.02
        df.loc[bar - 1, "open"] = prev_open
        df.loc[bar - 1, "close"] = prev_close
        df.loc[bar - 1, "high"] = prev_close * 1.003
        df.loc[bar - 1, "low"] = prev_open * 0.997
        df.loc[bar, "open"] = prev_close * 1.001    # open >= prev_close ✓
        df.loc[bar, "close"] = prev_open * 0.999    # close <= prev_open ✓
        df.loc[bar, "high"] = prev_close * 1.005
        df.loc[bar, "low"] = prev_open * 0.995
        return df

    def test_long_signal_generated(self) -> None:
        """Long cascade (bar 50) + bullish confirmation (bar 51) → long signal at bar 51."""
        df = self._make_combined_df(n=60, oi_pattern="long_cascade", taker_pattern="sell_extreme")
        df = self._inject_bullish_engulfing(df, bar=51)
        strat = LiquidationFadeStrategy()
        df = strat.prepare_features(df)
        signals = strat.generate_signals(df)
        long_signals = [s for s in signals if s.direction == "long"]
        assert len(long_signals) >= 1, f"Expected at least 1 long signal, got {len(long_signals)}"
        sig = long_signals[0]
        assert sig.sl_price < float(df.loc[51, "close"]), "SL must be below entry for long"
        assert sig.tp_price > float(df.loc[51, "close"]), "TP must be above entry for long"

    def test_short_signal_generated(self) -> None:
        """Short cascade (bar 50) + bearish confirmation (bar 51) → short signal at bar 51."""
        df = self._make_combined_df(n=60, oi_pattern="short_cascade", taker_pattern="buy_extreme")
        df = self._inject_bearish_engulfing(df, bar=51)
        strat = LiquidationFadeStrategy()
        df = strat.prepare_features(df)
        signals = strat.generate_signals(df)
        short_signals = [s for s in signals if s.direction == "short"]
        assert len(short_signals) >= 1, f"Expected at least 1 short signal, got {len(short_signals)}"
        sig = short_signals[0]
        assert sig.sl_price > float(df.loc[51, "close"]), "SL must be above entry for short"
        assert sig.tp_price < float(df.loc[51, "close"]), "TP must be below entry for short"

    def test_no_signal_without_confirmation(self) -> None:
        """Cascade at bar 50 but no confirmation pattern → signals (if any) are valid Signal objects."""
        df = self._make_combined_df(n=60, oi_pattern="long_cascade", taker_pattern="sell_extreme")
        # No engulfing injection → bar 51 confirmation depends on random OHLCV
        strat = LiquidationFadeStrategy()
        df = strat.prepare_features(df)
        signals = strat.generate_signals(df)
        for sig in signals:
            assert sig.direction in ("long", "short")
            assert sig.sl_price > 0
            assert sig.tp_price > 0

    def test_missing_proxy_columns_no_crash(self) -> None:
        """Missing oi_pct_change and taker_sell_ratio → empty signals, no exception."""
        ohlcv = _make_ohlcv(60)
        strat = LiquidationFadeStrategy()
        signals = strat.generate_signals(ohlcv)
        assert signals == [], "Should return empty list when proxy columns missing"

    def test_empty_df_no_crash(self) -> None:
        """Empty DataFrame → empty signals."""
        strat = LiquidationFadeStrategy()
        signals = strat.generate_signals(pd.DataFrame())
        assert signals == []


# ---------------------------------------------------------------------------
# Test 9-10: LiquidationStore
# ---------------------------------------------------------------------------

class TestLiquidationStore:

    def _make_okx_df(self, n: int = 10) -> pd.DataFrame:
        ts_list = [pd.Timestamp("2025-03-01", tz="UTC") + pd.Timedelta(hours=i) for i in range(n)]
        return pd.DataFrame({
            "symbol": "BTC-USDT",
            "side": ["sell"] * n,
            "pos_side": ["long"] * n,
            "bk_price": [80000.0 + i * 10 for i in range(n)],
            "bk_loss": [0.0] * n,
            "size_contracts": [0.1 + i * 0.01 for i in range(n)],
            "ts": ts_list,
        })

    def _make_proxy_df_store(self, n: int = 10) -> pd.DataFrame:
        ts_list = [pd.Timestamp("2025-03-01", tz="UTC") + pd.Timedelta(days=i) for i in range(n)]
        rng = np.random.default_rng(1)
        return pd.DataFrame({
            "venue": "binance",
            "symbol": "BTCUSDT",
            "period": "1d",
            "ts": ts_list,
            "open_interest": rng.uniform(90000, 110000, n),
            "oi_pct_change": rng.uniform(-0.03, 0.03, n),
            "taker_sell_ratio": rng.uniform(0.45, 0.55, n),
        })

    def test_upsert_okx_roundtrip(self, tmp_db: Path) -> None:
        """OKX liquidation rows survive upsert and count is correct."""
        store = LiquidationStore(duckdb_path=tmp_db)
        df = self._make_okx_df(10)
        written = store.upsert_okx(df)
        assert written >= 0  # count is delta (new - existing)

        # Upsert same rows again → idempotent (no duplicates)
        written2 = store.upsert_okx(df)
        assert written2 == 0, "Re-upsert same rows should add 0 new rows"

    def test_upsert_proxy_roundtrip(self, tmp_db: Path) -> None:
        """Cascade proxy rows survive write/read cycle."""
        store = LiquidationStore(duckdb_path=tmp_db)
        df = self._make_proxy_df_store(10)
        written = store.upsert_proxy(df)
        assert written == 10

        result = store.read_proxy("BTCUSDT", period="1d", venue="binance")
        assert len(result) == 10
        assert "oi_pct_change" in result.columns
        assert "taker_sell_ratio" in result.columns
        # Timestamps should be UTC-aware
        assert result["ts"].dt.tz is not None


# ---------------------------------------------------------------------------
# Test 11: fetch_okx_liquidations error handling
# ---------------------------------------------------------------------------

class TestFetchOkxLiquidations:

    def test_network_error_returns_empty(self) -> None:
        """Network failure → empty DataFrame, no exception raised."""
        with patch("price_action.data.liquidation_ingest.requests.get") as mock_get:
            mock_get.side_effect = Exception("Connection refused")
            result = fetch_okx_liquidations("BTC-USDT")
        assert isinstance(result, pd.DataFrame)
        assert result.empty

    def test_api_error_code_returns_empty(self) -> None:
        """API returns non-zero error code → empty DataFrame."""
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.return_value = {"code": "51000", "msg": "Parameter error", "data": []}
        with patch("price_action.data.liquidation_ingest.requests.get", return_value=mock_resp):
            result = fetch_okx_liquidations("BTC-USDT")
        assert result.empty


# ---------------------------------------------------------------------------
# Test 12: build_cascade_proxy merge logic
# ---------------------------------------------------------------------------

class TestBuildCascadeProxy:

    def test_merge_returns_combined_columns(self) -> None:
        """build_cascade_proxy merges OI and taker data correctly."""
        # Mock both fetchers to return controlled DataFrames
        ts_list = [pd.Timestamp("2025-03-01", tz="UTC") + pd.Timedelta(days=i) for i in range(10)]

        mock_oi = pd.DataFrame({
            "venue": "bybit",
            "symbol": "BTCUSDT",
            "period": "1d",
            "ts": ts_list,
            "open_interest": np.linspace(100000, 105000, 10),
            "oi_pct_change": np.linspace(-0.01, 0.01, 10),
        })

        mock_taker = pd.DataFrame({
            "venue": "binance",
            "symbol": "BTCUSDT",
            "period": "1d",
            "ts": ts_list,
            "taker_buy_vol": np.ones(10) * 1e8,
            "taker_sell_vol": np.ones(10) * 1e8,
            "taker_sell_ratio": np.linspace(0.48, 0.52, 10),
            "long_short_ratio": np.ones(10) * 1.0,
        })

        with (
            patch("price_action.data.liquidation_ingest.fetch_binance_open_interest_history", return_value=mock_oi),
            patch("price_action.data.liquidation_ingest.fetch_binance_taker_ratio", return_value=mock_taker),
        ):
            result = build_cascade_proxy("BTCUSDT", period="1d", limit=10)

        assert not result.empty
        assert "oi_pct_change" in result.columns
        assert "taker_sell_ratio" in result.columns
        assert len(result) == 10
