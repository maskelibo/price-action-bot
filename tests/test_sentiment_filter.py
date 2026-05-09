"""F&G Sentiment Filter testleri — H18.

Test grupları:
    T01-T03: fetch_fear_greed_history (mock requests)
    T04-T05: merge_fng_to_ohlcv schema + lookahead
    T06-T08: filter_engulfing_with_fng mantik
    T09-T10: SentimentFilterStrategy standalone sinyal uretimi
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest

# src path
import sys
ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_fng_df() -> pd.DataFrame:
    """50 gunluk deterministik F&G verisi."""
    days = pd.date_range("2023-01-01", periods=50, freq="1D", tz="UTC")
    rng = np.random.default_rng(99)
    values = rng.integers(5, 95, size=50)

    def classify(v: int) -> str:
        if v < 25:
            return "Extreme Fear"
        if v < 50:
            return "Fear"
        if v < 75:
            return "Greed"
        return "Extreme Greed"

    return pd.DataFrame({
        "ts": days,
        "value": values,
        "classification": [classify(v) for v in values],
    })


@pytest.fixture
def sample_ohlcv_df() -> pd.DataFrame:
    """50 gunluk OHLCV (BTC-benzeri)."""
    rng = np.random.default_rng(42)
    days = pd.date_range("2023-01-01", periods=50, freq="1D", tz="UTC")
    n = len(days)
    rets = rng.normal(0.001, 0.03, size=n)
    close = 20000.0 * np.exp(np.cumsum(rets))
    high = close * (1 + rng.uniform(0.001, 0.015, size=n))
    low = close * (1 - rng.uniform(0.001, 0.015, size=n))
    open_ = np.empty(n)
    open_[0] = close[0] * 0.999
    open_[1:] = close[:-1] * (1 + rng.uniform(-0.005, 0.005, size=n - 1))
    high = np.maximum.reduce([high, open_, close])
    low = np.minimum.reduce([low, open_, close])
    return pd.DataFrame({
        "ts": days,
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "volume": rng.uniform(1e8, 5e8, size=n),
        "venue": "binance",
        "symbol": "BTC/USDT",
        "timeframe": "1d",
    })


@pytest.fixture
def extreme_fear_ohlcv_df() -> pd.DataFrame:
    """Manuel: F&G extreme fear + upward price confirm sinyali icerir."""
    # Bar 0-3: warm up
    # Bar 4 (t-1): F&G will be injected as extreme fear
    # Bar 5 (t): fiyat yukari gidiyor (close > prev_close) — LONG sinyal beklenir
    days = pd.date_range("2023-01-01", periods=10, freq="1D", tz="UTC")
    base = 20000.0
    data = {
        "ts": days,
        "open": [base] * 10,
        "high": [base * 1.02] * 10,
        "low": [base * 0.98] * 10,
        "close": [
            base, base * 0.99, base * 0.98, base * 0.97, base * 0.96,
            base * 0.98,  # bar5: yukari (vs bar4)
            base * 0.97, base * 0.96, base * 0.97, base * 0.98,
        ],
        "volume": [1e8] * 10,
        "venue": ["binance"] * 10,
        "symbol": ["BTC/USDT"] * 10,
        "timeframe": ["1d"] * 10,
    }
    return pd.DataFrame(data)


@pytest.fixture
def extreme_fear_fng_df() -> pd.DataFrame:
    """Manuel: bar5'in t-1'i (bar4) extreme fear."""
    days = pd.date_range("2023-01-01", periods=10, freq="1D", tz="UTC")
    values = [50, 50, 50, 50, 15, 30, 50, 50, 50, 50]  # bar4=15 (extreme fear)
    return pd.DataFrame({
        "ts": days,
        "value": values,
        "classification": ["Neutral"] * 4 + ["Extreme Fear"] + ["Fear"] + ["Neutral"] * 4,
    })


@pytest.fixture
def extreme_greed_ohlcv_df() -> pd.DataFrame:
    """Manuel: F&G extreme greed + downward price confirm — SHORT sinyal beklenir."""
    days = pd.date_range("2023-01-01", periods=10, freq="1D", tz="UTC")
    base = 20000.0
    data = {
        "ts": days,
        "open": [base] * 10,
        "high": [base * 1.02] * 10,
        "low": [base * 0.98] * 10,
        "close": [
            base * 1.02, base * 1.04, base * 1.06, base * 1.08, base * 1.10,
            base * 1.08,  # bar5: asagi (vs bar4 = 1.10) — SHORT beklenir
            base * 1.07, base * 1.06, base * 1.07, base * 1.08,
        ],
        "volume": [1e8] * 10,
        "venue": ["binance"] * 10,
        "symbol": ["BTC/USDT"] * 10,
        "timeframe": ["1d"] * 10,
    }
    return pd.DataFrame(data)


@pytest.fixture
def extreme_greed_fng_df() -> pd.DataFrame:
    """Manuel: bar5'in t-1'i (bar4) extreme greed."""
    days = pd.date_range("2023-01-01", periods=10, freq="1D", tz="UTC")
    values = [50, 55, 60, 70, 82, 50, 50, 50, 50, 50]  # bar4=82 (extreme greed)
    return pd.DataFrame({
        "ts": days,
        "value": values,
        "classification": ["Neutral"] * 4 + ["Extreme Greed"] + ["Neutral"] * 5,
    })


# ---------------------------------------------------------------------------
# Mock API response
# ---------------------------------------------------------------------------

def _make_api_response(n_days: int = 10) -> dict[str, Any]:
    """Alternative.me API formatini taklit eder — degerler 0-100 araliginda."""
    base_ts = int(datetime(2023, 1, 1, tzinfo=timezone.utc).timestamp())
    data = []
    for i in range(n_days):
        ts = base_ts + i * 86400
        # Sinusoidal pattern, 0-100 araliginda
        import math
        val = int(50 + 45 * math.sin(2 * math.pi * i / max(n_days, 20)))
        val = max(5, min(95, val))  # Kesinlikle 0-100 araliginda kal
        classification = "Fear" if val < 50 else "Greed"
        data.append({
            "timestamp": str(ts),
            "value": str(val),
            "value_classification": classification,
            "time_until_update": "0",
        })
    return {"name": "Fear and Greed Index", "data": data, "metadata": {"error": None}}


# ---------------------------------------------------------------------------
# T01: fetch_fear_greed_history — basarili fetch
# ---------------------------------------------------------------------------

def test_T01_fetch_success_schema():
    """Basarili API fetch: DataFrame schema kontrolu."""
    from price_action.data.sentiment_ingest import fetch_fear_greed_history

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = _make_api_response(30)

    with patch("requests.get", return_value=mock_resp):
        df = fetch_fear_greed_history(limit=30)

    assert not df.empty, "fetch bos DataFrame donmemeli"
    assert set(df.columns) >= {"ts", "value", "classification"}, "Schema hatali"
    assert len(df) == 30, f"30 satir bekleniyor, {len(df)} geldi"
    assert pd.api.types.is_datetime64_any_dtype(df["ts"]), "ts datetime olmali"
    assert df["ts"].dt.tz is not None, "ts timezone-aware olmali"


# ---------------------------------------------------------------------------
# T02: fetch_fear_greed_history — network hatasi bos doner
# ---------------------------------------------------------------------------

def test_T02_fetch_network_error_returns_empty():
    """Network hatasi crash etmez, bos DataFrame doner."""
    from price_action.data.sentiment_ingest import fetch_fear_greed_history

    with patch("requests.get", side_effect=ConnectionError("connection refused")):
        df = fetch_fear_greed_history(limit=10)

    assert df.empty, "Network hatasinda bos DataFrame bekleniyor"
    assert "ts" in df.columns, "Bos DF kolonlari olmali"


# ---------------------------------------------------------------------------
# T03: fetch_fear_greed_history — value range
# ---------------------------------------------------------------------------

def test_T03_fetch_value_range():
    """F&G degerleri 0-100 araliginda olmali."""
    from price_action.data.sentiment_ingest import fetch_fear_greed_history

    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = _make_api_response(50)

    with patch("requests.get", return_value=mock_resp):
        df = fetch_fear_greed_history(limit=50)

    assert (df["value"] >= 0).all(), "F&G 0'in altina dusmemeli"
    assert (df["value"] <= 100).all(), "F&G 100'un ustune cikmamali"


# ---------------------------------------------------------------------------
# T04: merge_fng_to_ohlcv — schema
# ---------------------------------------------------------------------------

def test_T04_merge_schema(sample_ohlcv_df, sample_fng_df):
    """merge_fng_to_ohlcv sonrasi beklenen kolonlar var."""
    from price_action.strategies.sentiment_filter import merge_fng_to_ohlcv

    merged = merge_fng_to_ohlcv(sample_ohlcv_df, sample_fng_df)
    assert "fng_value" in merged.columns, "fng_value kolonu eksik"
    assert "fng_value_lag" in merged.columns, "fng_value_lag kolonu eksik"
    assert "fng_classification" in merged.columns, "fng_classification kolonu eksik"
    assert len(merged) == len(sample_ohlcv_df), "Satir sayisi degismemeli (left join)"


# ---------------------------------------------------------------------------
# T05: merge_fng_to_ohlcv — lookahead-free (shift(1))
# ---------------------------------------------------------------------------

def test_T05_merge_lookahead_free(sample_ohlcv_df, sample_fng_df):
    """fng_value_lag, fng_value'nin shift(1)'i olmali — lookahead yok."""
    from price_action.strategies.sentiment_filter import merge_fng_to_ohlcv

    merged = merge_fng_to_ohlcv(sample_ohlcv_df, sample_fng_df, apply_shift=True)
    # Row i'nin fng_value_lag'i, row i-1'in fng_value'sine esit olmali
    for i in range(1, len(merged)):
        lag = merged["fng_value_lag"].iloc[i]
        prev = merged["fng_value"].iloc[i - 1]
        if not (pd.isna(lag) and pd.isna(prev)):
            assert lag == prev, (
                f"Lookahead hatasi: row {i} fng_value_lag={lag} "
                f"row {i-1} fng_value={prev}"
            )


# ---------------------------------------------------------------------------
# T06: filter_engulfing_with_fng — yuksek FNG long sinyali reddeder
# ---------------------------------------------------------------------------

def test_T06_high_fng_rejects_long(sample_fng_df):
    """F&G >= long_max_fng iken long sinyal reddedilmeli."""
    from price_action.strategies.sentiment_filter import filter_engulfing_with_fng
    from price_action.contracts import Signal

    # F&G degerini 75 yap (>= long_max_fng=60 olacak)
    high_fng = sample_fng_df.copy()
    high_fng["value"] = 75

    # Sahte long sinyal — tarihi fng_df'teki birinci tarihle ayarla
    sig_date = sample_fng_df["ts"].iloc[1].to_pydatetime()  # i=1, lag=i=0'in degeri
    mock_sig = Signal(
        ts=sig_date,
        venue="binance",
        symbol="BTC/USDT",
        timeframe="1d",
        direction="long",
        pattern_id="bullish_engulfing_cont",
        confluence_score=1.5,
        sl_price=19000.0,
        tp_price=21000.0,
        suggested_size_atr=1.0,
    )

    filtered, n_rejected = filter_engulfing_with_fng(
        [mock_sig], high_fng, long_max_fng=60.0, short_min_fng=40.0
    )
    assert n_rejected == 1, f"Yuksek FNG long reddedilmeli, n_rejected={n_rejected}"
    assert len(filtered) == 0, "Filtered liste bos olmali"


# ---------------------------------------------------------------------------
# T07: filter_engulfing_with_fng — dusuk FNG short sinyali reddeder
# ---------------------------------------------------------------------------

def test_T07_low_fng_rejects_short(sample_fng_df):
    """F&G <= short_min_fng iken short sinyal reddedilmeli."""
    from price_action.strategies.sentiment_filter import filter_engulfing_with_fng
    from price_action.contracts import Signal

    low_fng = sample_fng_df.copy()
    low_fng["value"] = 20  # <= short_min_fng=40

    sig_date = sample_fng_df["ts"].iloc[1].to_pydatetime()
    mock_sig = Signal(
        ts=sig_date,
        venue="binance",
        symbol="BTC/USDT",
        timeframe="1d",
        direction="short",
        pattern_id="bearish_engulfing_cont",
        confluence_score=1.5,
        sl_price=21000.0,
        tp_price=19000.0,
        suggested_size_atr=1.0,
    )

    filtered, n_rejected = filter_engulfing_with_fng(
        [mock_sig], low_fng, long_max_fng=60.0, short_min_fng=40.0
    )
    assert n_rejected == 1, "Dusuk FNG short reddedilmeli"
    assert len(filtered) == 0


# ---------------------------------------------------------------------------
# T08: filter_engulfing_with_fng — uygun FNG sinyali gecirer
# ---------------------------------------------------------------------------

def test_T08_neutral_fng_passes_both(sample_fng_df):
    """Neutral F&G (50) hem long hem short'u gecer."""
    from price_action.strategies.sentiment_filter import filter_engulfing_with_fng
    from price_action.contracts import Signal

    neutral_fng = sample_fng_df.copy()
    neutral_fng["value"] = 50  # long_max=60 altinda, short_min=40 ustunde

    sig_date = sample_fng_df["ts"].iloc[1].to_pydatetime()

    long_sig = Signal(
        ts=sig_date, venue="binance", symbol="BTC/USDT", timeframe="1d",
        direction="long", pattern_id="bull_engulf", confluence_score=1.5,
        sl_price=19000.0, tp_price=21000.0, suggested_size_atr=1.0,
    )
    short_sig = Signal(
        ts=sig_date, venue="binance", symbol="BTC/USDT", timeframe="1d",
        direction="short", pattern_id="bear_engulf", confluence_score=1.5,
        sl_price=21000.0, tp_price=19000.0, suggested_size_atr=1.0,
    )

    filtered_long, rej_l = filter_engulfing_with_fng(
        [long_sig], neutral_fng, long_max_fng=60.0, short_min_fng=40.0
    )
    filtered_short, rej_s = filter_engulfing_with_fng(
        [short_sig], neutral_fng, long_max_fng=60.0, short_min_fng=40.0
    )

    assert rej_l == 0, "Neutral FNG long reddedilmemeli"
    assert rej_s == 0, "Neutral FNG short reddedilmemeli"
    assert len(filtered_long) == 1
    assert len(filtered_short) == 1


# ---------------------------------------------------------------------------
# T09: SentimentFilterStrategy — extreme fear long sinyal uretir
# ---------------------------------------------------------------------------

def test_T09_extreme_fear_generates_long(extreme_fear_ohlcv_df, extreme_fear_fng_df):
    """Extreme fear + upward confirm → LONG sinyal beklenir."""
    from price_action.strategies.sentiment_filter import SentimentFilterStrategy

    strategy = SentimentFilterStrategy()
    strategy.set_fng_data(extreme_fear_fng_df)

    df_feats = strategy.prepare_features(extreme_fear_ohlcv_df)
    signals = strategy.generate_signals(df_feats)

    long_sigs = [s for s in signals if s.direction == "long"]
    assert len(long_sigs) >= 1, (
        f"Extreme fear + upward price confirm uzun sinyal uretmeli. "
        f"Uretilen: {[(s.direction, s.ts) for s in signals]}"
    )


# ---------------------------------------------------------------------------
# T10: SentimentFilterStrategy — extreme greed short sinyal uretir
# ---------------------------------------------------------------------------

def test_T10_extreme_greed_generates_short(extreme_greed_ohlcv_df, extreme_greed_fng_df):
    """Extreme greed + downward confirm → SHORT sinyal beklenir."""
    from price_action.strategies.sentiment_filter import SentimentFilterStrategy

    strategy = SentimentFilterStrategy()
    strategy.set_fng_data(extreme_greed_fng_df)

    df_feats = strategy.prepare_features(extreme_greed_ohlcv_df)
    signals = strategy.generate_signals(df_feats)

    short_sigs = [s for s in signals if s.direction == "short"]
    assert len(short_sigs) >= 1, (
        f"Extreme greed + downward price confirm kisa sinyal uretmeli. "
        f"Uretilen: {[(s.direction, s.ts) for s in signals]}"
    )


# ---------------------------------------------------------------------------
# T11: SentimentFilterStrategy — empty FNG graceful
# ---------------------------------------------------------------------------

def test_T11_empty_fng_no_crash(sample_ohlcv_df):
    """Bos F&G verisiyle strateji crash etmemeli."""
    from price_action.strategies.sentiment_filter import SentimentFilterStrategy

    strategy = SentimentFilterStrategy()
    # F&G inject edilmedi — varsayilan bos

    df_feats = strategy.prepare_features(sample_ohlcv_df)
    signals = strategy.generate_signals(df_feats)

    # Bos F&G → sinyal olmayabilir ama hata yok
    assert isinstance(signals, list), "generate_signals liste donmeli"


# ---------------------------------------------------------------------------
# T12: FngStore.upsert + read round-trip
# ---------------------------------------------------------------------------

def test_T12_fng_store_roundtrip(tmp_path, sample_fng_df):
    """FngStore: upsert + read round-trip tutarli olmali."""
    from price_action.data.sentiment_ingest import FngStore, reset_fng_pool

    db = tmp_path / "test_fng.duckdb"
    reset_fng_pool()
    store = FngStore(duckdb_path=db)

    written = store.upsert(sample_fng_df)
    assert written == len(sample_fng_df), f"Yazilan satir {written} != {len(sample_fng_df)}"

    df_read = store.read()
    assert not df_read.empty
    assert len(df_read) == len(sample_fng_df)
    assert set(df_read.columns) >= {"ts", "value", "classification"}

    reset_fng_pool()
