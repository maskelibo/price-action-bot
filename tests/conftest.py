"""Pytest fixtures + global configuration.

`@pytest.mark.integration` ile işaretli testler default'ta atlanır
(network olmadığından).
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

# `src/` layout için path ayarı (kurulu değilken testler çalışsın)
_ROOT = Path(__file__).resolve().parents[1]
_SRC = _ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "integration: dış servis gerektirir")
    config.addinivalue_line("markers", "slow: yavaş test")
    config.addinivalue_line("markers", "live: gerçek borsa")


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Default'ta integration ve live testleri atla."""
    skip_integration = pytest.mark.skip(reason="integration tests skipped by default")
    skip_live = pytest.mark.skip(reason="live exchange tests skipped by default")
    run_integration = bool(os.environ.get("PA_RUN_INTEGRATION"))
    for item in items:
        if "integration" in item.keywords and not run_integration:
            item.add_marker(skip_integration)
        if "live" in item.keywords:
            item.add_marker(skip_live)


# ---------------------------------------------------------------------------
# Synthetic OHLCV fixtures
# ---------------------------------------------------------------------------
def _make_bar(o: float, h: float, l: float, c: float, v: float = 1000.0) -> dict:
    return {"open": o, "high": h, "low": l, "close": c, "volume": v}


@pytest.fixture
def random_ohlcv() -> pd.DataFrame:
    """Sentetik OHLCV — 1d, 200 bar, deterministik seed."""
    rng = np.random.default_rng(42)
    n = 200
    start = datetime(2023, 1, 1, tzinfo=timezone.utc)
    ts = pd.date_range(start, periods=n, freq="1D", tz="UTC")
    rets = rng.normal(0.0, 0.02, size=n)
    close = 100.0 * np.exp(np.cumsum(rets))
    high = close * (1 + rng.uniform(0.001, 0.02, size=n))
    low = close * (1 - rng.uniform(0.001, 0.02, size=n))
    open_ = np.empty(n)
    open_[0] = close[0] * (1 + rng.uniform(-0.005, 0.005))
    open_[1:] = close[:-1] * (1 + rng.uniform(-0.005, 0.005, size=n - 1))
    # OHLC sanity garantile: high = max(o,c,h), low = min(o,c,l)
    high = np.maximum.reduce([high, open_, close])
    low = np.minimum.reduce([low, open_, close])
    volume = rng.uniform(500, 1500, size=n)
    df = pd.DataFrame(
        {
            "ts": ts,
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
            "venue": "binance",
            "symbol": "TEST/USDT",
            "timeframe": "1d",
        }
    )
    return df


@pytest.fixture
def bullish_pin_bar_df() -> pd.DataFrame:
    """Tek bullish pin bar içeren manuel kurgu OHLCV (5 bar)."""
    bars = [
        _make_bar(100, 101, 99, 100),  # nötr
        _make_bar(100, 102, 98, 101),  # nötr
        # bullish pin: range=10, body=1, lower_wick=8, upper_wick=1
        _make_bar(o=99.5, h=100.5, l=90, c=100),
        _make_bar(101, 102, 100.5, 101.5),
        _make_bar(101.5, 102, 101, 101.8),
    ]
    ts = pd.date_range("2024-01-01", periods=len(bars), freq="1D", tz="UTC")
    df = pd.DataFrame(bars)
    df["ts"] = ts
    return df


@pytest.fixture
def bearish_pin_bar_df() -> pd.DataFrame:
    """Tek bearish pin bar (uzun üst fitil)."""
    bars = [
        _make_bar(100, 101, 99, 100),
        _make_bar(100, 102, 99, 101),
        _make_bar(o=100.5, h=110, l=99.5, c=100),  # bearish pin
        _make_bar(99, 100, 98, 98.5),
        _make_bar(98.5, 99, 97, 97.5),
    ]
    ts = pd.date_range("2024-01-01", periods=len(bars), freq="1D", tz="UTC")
    df = pd.DataFrame(bars)
    df["ts"] = ts
    return df


@pytest.fixture
def bullish_engulfing_df() -> pd.DataFrame:
    """Bullish engulfing örneği (3 bar)."""
    bars = [
        _make_bar(100, 101, 99, 100),       # nötr
        _make_bar(100, 100.5, 95, 96),      # bearish: open 100, close 96
        _make_bar(95, 102, 95, 101),        # bullish engulfing: open 95<=96, close 101>=100
    ]
    ts = pd.date_range("2024-01-01", periods=len(bars), freq="1D", tz="UTC")
    df = pd.DataFrame(bars)
    df["ts"] = ts
    return df


@pytest.fixture
def bearish_engulfing_df() -> pd.DataFrame:
    bars = [
        _make_bar(100, 101, 99, 100),
        _make_bar(100, 105, 99, 104),       # bullish: open 100, close 104
        _make_bar(105, 105.5, 95, 99),      # bearish engulfing: open 105>=104, close 99<=100
    ]
    ts = pd.date_range("2024-01-01", periods=len(bars), freq="1D", tz="UTC")
    df = pd.DataFrame(bars)
    df["ts"] = ts
    return df


@pytest.fixture
def inside_bar_df() -> pd.DataFrame:
    """3 bar: ilk normal, ikinci inside, üçüncü inside-bar long-breakout."""
    bars = [
        _make_bar(100, 110, 90, 105),                 # geniş "mother" bar
        _make_bar(o=104, h=108, l=95, c=103),         # inside: 108<110 & 95>90
        _make_bar(o=104, h=115, l=104, c=112),        # close > prev_high (108 değil—mother bar değil. Inside bar'ın high'ı 108 → close 112 > 108 long break)
    ]
    ts = pd.date_range("2024-01-01", periods=len(bars), freq="1D", tz="UTC")
    df = pd.DataFrame(bars)
    df["ts"] = ts
    return df


@pytest.fixture
def morning_star_df() -> pd.DataFrame:
    """Morning star üç-bar örneği."""
    bars = [
        # bar -2: belirgin bearish (range 10, body 8)
        _make_bar(o=110, h=110.5, l=100, c=101),
        # bar -1: küçük gövde
        _make_bar(o=100.5, h=101, l=99.5, c=100.0),
        # bar 0: bullish, midpoint(110+101)/2=105.5 üstü close
        _make_bar(o=100.5, h=108, l=100, c=107),
    ]
    ts = pd.date_range("2024-01-01", periods=len(bars), freq="1D", tz="UTC")
    df = pd.DataFrame(bars)
    df["ts"] = ts
    return df


@pytest.fixture
def evening_star_df() -> pd.DataFrame:
    bars = [
        _make_bar(o=100, h=110, l=99.5, c=109),    # belirgin bullish, midpoint 104.5
        _make_bar(o=109.5, h=110, l=109, c=109.6), # küçük gövde
        _make_bar(o=109, h=109.5, l=100, c=101),   # bearish; close 101 < midpoint 104.5
    ]
    ts = pd.date_range("2024-01-01", periods=len(bars), freq="1D", tz="UTC")
    df = pd.DataFrame(bars)
    df["ts"] = ts
    return df


@pytest.fixture
def doji_df() -> pd.DataFrame:
    bars = [
        _make_bar(100, 101, 99, 100.05),     # doji: gövde 0.05, range 2 → ratio 0.025
        _make_bar(100, 105, 99, 104),        # değil
    ]
    ts = pd.date_range("2024-01-01", periods=len(bars), freq="1D", tz="UTC")
    df = pd.DataFrame(bars)
    df["ts"] = ts
    return df


@pytest.fixture
def gap_ohlcv() -> pd.DataFrame:
    """1d serisinde 2 bar eksik (gap)."""
    days = pd.to_datetime(
        ["2024-01-01", "2024-01-02", "2024-01-05", "2024-01-06"], utc=True
    )
    rng = np.random.default_rng(7)
    n = len(days)
    close = 100 + np.cumsum(rng.normal(0, 1, n))
    df = pd.DataFrame(
        {
            "ts": days,
            "open": close - 0.5,
            "high": close + 0.5,
            "low": close - 1.0,
            "close": close,
            "volume": rng.uniform(500, 1500, size=n),
            "venue": "binance",
            "symbol": "GAP/USDT",
            "timeframe": "1d",
        }
    )
    return df


@pytest.fixture
def duplicate_ohlcv() -> pd.DataFrame:
    days = pd.to_datetime(
        ["2024-01-01", "2024-01-02", "2024-01-02", "2024-01-03"], utc=True
    )
    return pd.DataFrame(
        {
            "ts": days,
            "open": [100, 101, 101, 102],
            "high": [102, 103, 103, 104],
            "low": [99, 100, 100, 101],
            "close": [101, 102, 102, 103],
            "volume": [1000, 1100, 1100, 1200],
            "venue": "binance",
            "symbol": "DUP/USDT",
            "timeframe": "1d",
        }
    )


# ---------------------------------------------------------------------------
# Analytics / ML / API fixtures (Analytics+ML+API+CLI alt sistemi)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session", autouse=True)
def _isolate_test_env():
    """Test sürerken ENV'i izole et — gerçek Postgres'e bağlanmaması için
    DuckDB/SQLite fallback kullan."""
    os.environ.setdefault("LOG_LEVEL", "WARNING")
    os.environ.setdefault("LOG_FORMAT", "plain")
    # `scripts.seed_data` paketini import edebilmek için ROOT'u sys.path'e al
    if str(_ROOT) not in sys.path:
        sys.path.insert(0, str(_ROOT))
    yield


@pytest.fixture
def synthetic_trades_df() -> pd.DataFrame:
    """Sentetik trade DataFrame — analytics testleri için."""
    from scripts.seed_data import generate_trades

    return generate_trades(n=80, seed=7)


@pytest.fixture
def synthetic_ohlcv_df() -> pd.DataFrame:
    from scripts.seed_data import generate_ohlcv

    return generate_ohlcv(n=400, seed=11)


@pytest.fixture
def in_memory_journal(tmp_path):
    """Postgres yerine SQLite-file tabanlı Journal."""
    from price_action.analytics.journal import Journal

    db_url = f"sqlite:///{tmp_path / 'journal.sqlite'}"
    return Journal(db_url=db_url)
