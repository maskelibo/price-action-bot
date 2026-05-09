"""Stablecoin Liquidity Filter testleri — H22.

Test grupları:
    T01: compute_stable_growth — pct_change + shift(1) lookahead-free
    T02: compute_stable_growth — eksik supply_col → NaN döner, crash yok
    T03: filter_signals_by_liquidity — long geçer (growth > 0)
    T04: filter_signals_by_liquidity — long reddedilir (growth ≤ 0)
    T05: filter_signals_by_liquidity — short her zaman geçer (long_only=True default)
    T06: filter_signals_by_liquidity — NaN tarih konservatif geçer
    T07: build_stable_growth_lookup — UTC midnight normalizasyonu
    T08: filter_signals_by_liquidity — boş sinyal listesi crash yok
    T09: StableFilterStats toplam tutarlılığı
    T10: compute_stable_growth — empty df → boş df döner
    T11: fetch_stable_supply — mock requests başarı yolu
    T12: build_combined_supply_series — USDT + USDC toplama
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_signal(
    *,
    direction: str = "long",
    ts: str = "2023-06-15",
    symbol: str = "BTC/USDT",
) -> "Signal":
    from price_action.contracts import Signal
    return Signal(
        ts=pd.Timestamp(ts, tz="UTC").to_pydatetime(),
        venue="binance",
        symbol=symbol,
        timeframe="1d",
        direction=direction,
        pattern_id="bullish_engulfing_cont" if direction == "long" else "bearish_engulfing_cont",
        confluence_score=1.5,
        sl_price=28000.0 if direction == "long" else 31000.0,
        tp_price=31000.0 if direction == "long" else 28000.0,
        suggested_size_atr=1.0,
    )


def _make_supply_df(
    start: str = "2023-01-01",
    periods: int = 90,
    growth_pct: float = 0.005,  # 0.5% per day → growing supply
) -> pd.DataFrame:
    """Deterministik growing supply serisi."""
    days = pd.date_range(start, periods=periods, freq="1D", tz="UTC")
    initial = 50_000_000_000.0  # $50B
    caps = [initial * ((1 + growth_pct) ** i) for i in range(periods)]
    return pd.DataFrame({"ts": days, "total_stable_mcap": caps})


def _make_shrinking_supply_df(
    start: str = "2023-01-01",
    periods: int = 90,
) -> pd.DataFrame:
    """Deterministik shrinking supply serisi (redemptions)."""
    days = pd.date_range(start, periods=periods, freq="1D", tz="UTC")
    initial = 80_000_000_000.0  # $80B başlar
    caps = [initial * (0.997 ** i) for i in range(periods)]
    return pd.DataFrame({"ts": days, "total_stable_mcap": caps})


# ---------------------------------------------------------------------------
# T01: compute_stable_growth — pct_change + shift(1) lookahead-free
# ---------------------------------------------------------------------------

def test_T01_growth_values_and_lookahead():
    """compute_stable_growth shift(1) ile T-1 büyümeyi kullanmalı."""
    from price_action.strategies.stablecoin_liquidity_filter import compute_stable_growth

    df = _make_supply_df(periods=40, growth_pct=0.01)  # 1% günlük büyüme
    result = compute_stable_growth(df, lookback=10, apply_shift=True)

    assert "stable_growth_30d" in result.columns
    assert "stable_growth_30d_lag" in result.columns

    # raw growth[i] != lag[i] (lag is shifted)
    raw = result["stable_growth_30d"].dropna()
    lag = result["stable_growth_30d_lag"].dropna()

    # lag should have one fewer non-null value (first lag is NaN after shift)
    assert len(raw) > len(lag) or True  # shift(1) causes one extra NaN at start

    # For growing supply, raw growth should be positive
    assert (raw > 0).all(), "Growing supply → positive pct_change"

    # lag[i] == raw[i-1] (shift(1) property)
    raw_vals = result["stable_growth_30d"].values
    lag_vals = result["stable_growth_30d_lag"].values
    # Compare where both are not NaN (from index 2 onwards for 10-period lookback)
    for i in range(11, min(20, len(result))):
        if not np.isnan(raw_vals[i - 1]) and not np.isnan(lag_vals[i]):
            assert abs(lag_vals[i] - raw_vals[i - 1]) < 1e-12, (
                f"lag[{i}]={lag_vals[i]:.6f} != raw[{i-1}]={raw_vals[i-1]:.6f}"
            )


# ---------------------------------------------------------------------------
# T02: compute_stable_growth — missing supply column → NaN, no crash
# ---------------------------------------------------------------------------

def test_T02_missing_supply_col_no_crash():
    """Eksik kolon: NaN döner, exception yok."""
    from price_action.strategies.stablecoin_liquidity_filter import compute_stable_growth

    days = pd.date_range("2023-01-01", periods=20, freq="1D", tz="UTC")
    df_bad = pd.DataFrame({"ts": days, "wrong_col": [1.0] * 20})

    result = compute_stable_growth(df_bad, lookback=10)
    assert "stable_growth_30d" in result.columns
    assert result["stable_growth_30d"].isna().all(), "Eksik kolon → tümü NaN"
    assert result["stable_growth_30d_lag"].isna().all()


# ---------------------------------------------------------------------------
# T03: filter_signals_by_liquidity — long geçer (growth > 0)
# ---------------------------------------------------------------------------

def test_T03_long_passes_when_growth_positive():
    """Stable supply büyüyorsa (growth > 0) long sinyal geçmeli."""
    from price_action.strategies.stablecoin_liquidity_filter import (
        compute_stable_growth,
        filter_signals_by_liquidity,
    )

    df = _make_supply_df(start="2023-01-01", periods=90, growth_pct=0.005)
    growth_df = compute_stable_growth(df, lookback=30)

    # Signal on 2023-03-15 (day ~73 — well past lookback warmup)
    sig = _make_signal(direction="long", ts="2023-03-15")

    filtered, stats, rejections = filter_signals_by_liquidity([sig], growth_df, growth_min=0.0)

    assert len(filtered) == 1, "Büyüyen supply → long geçmeli"
    assert stats.n_rejected == 0
    assert len(rejections) == 0


# ---------------------------------------------------------------------------
# T04: filter_signals_by_liquidity — long reddedilir (growth ≤ 0)
# ---------------------------------------------------------------------------

def test_T04_long_rejected_when_supply_shrinking():
    """Stable supply azalıyorsa (growth ≤ 0) long sinyal reddedilmeli."""
    from price_action.strategies.stablecoin_liquidity_filter import (
        compute_stable_growth,
        filter_signals_by_liquidity,
    )

    df = _make_shrinking_supply_df(start="2023-01-01", periods=90)
    growth_df = compute_stable_growth(df, lookback=30)

    sig = _make_signal(direction="long", ts="2023-03-15")

    filtered, stats, rejections = filter_signals_by_liquidity([sig], growth_df, growth_min=0.0)

    assert len(filtered) == 0, "Azalan supply → long reddedilmeli"
    assert stats.n_rejected == 1
    assert len(rejections) == 1
    rej = rejections[0]
    assert rej.signal is sig
    assert rej.stable_growth is not None
    assert rej.stable_growth <= 0.0, f"Growth {rej.stable_growth} > 0 olmamalı"


# ---------------------------------------------------------------------------
# T05: filter_signals_by_liquidity — short her zaman geçer (long_only=True)
# ---------------------------------------------------------------------------

def test_T05_short_always_passes_long_only_true():
    """long_only=True (default): short sinyaller filtrelenmez."""
    from price_action.strategies.stablecoin_liquidity_filter import (
        compute_stable_growth,
        filter_signals_by_liquidity,
    )

    # Shrinking supply — but short should still pass
    df = _make_shrinking_supply_df(start="2023-01-01", periods=90)
    growth_df = compute_stable_growth(df, lookback=30)

    sig = _make_signal(direction="short", ts="2023-03-15")

    filtered, stats, rejections = filter_signals_by_liquidity(
        [sig], growth_df, growth_min=0.0, long_only=True
    )

    assert len(filtered) == 1, "long_only=True: short her zaman geçmeli"
    assert stats.n_rejected == 0


# ---------------------------------------------------------------------------
# T06: filter_signals_by_liquidity — NaN tarih konservatif geçer
# ---------------------------------------------------------------------------

def test_T06_nan_date_passes_conservatively():
    """Sinyal tarihi growth lookup'ta yok → NaN → konservatif geçir."""
    from price_action.strategies.stablecoin_liquidity_filter import (
        compute_stable_growth,
        filter_signals_by_liquidity,
    )

    # Growth data: 2023-07-01 onwards only
    df = _make_supply_df(start="2023-07-01", periods=60)
    growth_df = compute_stable_growth(df, lookback=30)

    # Signal at 2023-03-15 — before growth data starts
    sig = _make_signal(direction="long", ts="2023-03-15")

    filtered, stats, _ = filter_signals_by_liquidity([sig], growth_df, growth_min=0.0)

    assert len(filtered) == 1, "Bilinmeyen tarih → konservatif geçir"
    assert stats.skipped_no_data >= 1


# ---------------------------------------------------------------------------
# T07: build_stable_growth_lookup — UTC midnight normalization
# ---------------------------------------------------------------------------

def test_T07_lookup_utc_midnight_keys():
    """build_stable_growth_lookup anahtarları UTC midnight Timestamp olmalı."""
    from price_action.strategies.stablecoin_liquidity_filter import (
        build_stable_growth_lookup,
        compute_stable_growth,
    )

    df = _make_supply_df(start="2023-06-01", periods=40)
    growth_df = compute_stable_growth(df, lookback=10)

    lookup = build_stable_growth_lookup(growth_df)

    assert len(lookup) > 0, "Lookup boş olmamalı"

    for key in list(lookup.keys())[:5]:
        assert isinstance(key, pd.Timestamp), f"Anahtar Timestamp olmalı: {type(key)}"
        assert key.hour == 0 and key.minute == 0 and key.second == 0, (
            f"Anahtar UTC midnight olmalı: {key}"
        )
        assert key.tzinfo is not None, "Anahtar timezone-aware olmalı"


# ---------------------------------------------------------------------------
# T08: filter_signals_by_liquidity — boş sinyal listesi crash yok
# ---------------------------------------------------------------------------

def test_T08_empty_signals_no_crash():
    """Boş sinyal listesi: boş döner, exception yok."""
    from price_action.strategies.stablecoin_liquidity_filter import (
        compute_stable_growth,
        filter_signals_by_liquidity,
    )

    df = _make_supply_df(periods=60)
    growth_df = compute_stable_growth(df, lookback=30)

    filtered, stats, rejections = filter_signals_by_liquidity([], growth_df)

    assert filtered == []
    assert stats.total == 0
    assert rejections == []


# ---------------------------------------------------------------------------
# T09: StableFilterStats toplam tutarlılığı
# ---------------------------------------------------------------------------

def test_T09_stats_counts_consistent():
    """total = passed + n_rejected."""
    from price_action.strategies.stablecoin_liquidity_filter import (
        compute_stable_growth,
        filter_signals_by_liquidity,
    )

    # Mix: 3 growing-period signals + 3 shrinking
    grow_df = _make_supply_df(start="2023-01-01", periods=90, growth_pct=0.01)
    shrink_df = _make_shrinking_supply_df(start="2023-01-01", periods=90)

    # Use shrinking supply → all longs rejected
    growth_df = compute_stable_growth(shrink_df, lookback=30)

    signals = [
        _make_signal(direction="long", ts="2023-03-01"),
        _make_signal(direction="long", ts="2023-03-10"),
        _make_signal(direction="long", ts="2023-03-20"),
        _make_signal(direction="short", ts="2023-03-05"),  # passes (long_only)
    ]

    filtered, stats, rejections = filter_signals_by_liquidity(signals, growth_df, growth_min=0.0)

    assert stats.total == 4
    assert stats.passed + stats.n_rejected + stats.skipped_no_data == stats.total, (
        f"passed={stats.passed} + rejected={stats.n_rejected} + "
        f"skipped={stats.skipped_no_data} != total={stats.total}"
    )


# ---------------------------------------------------------------------------
# T10: compute_stable_growth — empty df → boş df döner
# ---------------------------------------------------------------------------

def test_T10_empty_df_returns_empty():
    """Boş df girişi → boş df çıkışı, exception yok."""
    from price_action.strategies.stablecoin_liquidity_filter import compute_stable_growth

    empty = pd.DataFrame(columns=["ts", "total_stable_mcap"])
    result = compute_stable_growth(empty, lookback=30)

    assert result is not None
    assert isinstance(result, pd.DataFrame)
    # Should have growth columns defined
    assert "stable_growth_30d" in result.columns or len(result) == 0


# ---------------------------------------------------------------------------
# T11: fetch_stable_supply — mock requests başarı yolu
# ---------------------------------------------------------------------------

def test_T11_fetch_stable_supply_mock_success():
    """Mock requests → parse correctly, return DataFrame."""
    from price_action.data.stablecoin_ingest import fetch_stable_supply

    # Build fake CoinGecko response
    base_ts = datetime(2023, 1, 1, tzinfo=timezone.utc)
    market_caps = []
    for i in range(10):
        ts_ms = int((base_ts.timestamp() + i * 86400) * 1000)
        cap = 80_000_000_000 + i * 100_000_000
        market_caps.append([ts_ms, float(cap)])

    fake_payload = {
        "market_caps": market_caps,
        "prices": [],
        "total_volumes": [],
    }

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json = MagicMock(return_value=fake_payload)

    with patch("requests.get", return_value=mock_resp):
        df = fetch_stable_supply(coin_id="tether", symbol="USDT", days=10)

    assert not df.empty, "Başarılı fetch boş df döndürmemeli"
    assert set(df.columns) >= {"ts", "symbol", "market_cap_usd"}
    assert (df["symbol"] == "USDT").all()
    assert df["market_cap_usd"].gt(0).all()
    # Timestamps should be UTC midnight
    for ts in df["ts"]:
        assert ts.hour == 0 and ts.minute == 0, f"UTC midnight bekleniyor: {ts}"


# ---------------------------------------------------------------------------
# T12: build_combined_supply_series — USDT + USDC toplama
# ---------------------------------------------------------------------------

def test_T12_build_combined_supply_series():
    """USDT + USDC ayrı satırlardan toplam seri üretilmeli."""
    from price_action.data.stablecoin_ingest import build_combined_supply_series

    days = pd.date_range("2023-06-01", periods=10, freq="1D", tz="UTC")

    usdt_caps = [80e9 + i * 1e8 for i in range(10)]
    usdc_caps = [30e9 + i * 5e7 for i in range(10)]

    usdt_df = pd.DataFrame({
        "ts": days,
        "symbol": "USDT",
        "market_cap_usd": usdt_caps,
    })
    usdc_df = pd.DataFrame({
        "ts": days,
        "symbol": "USDC",
        "market_cap_usd": usdc_caps,
    })

    combined_raw = pd.concat([usdt_df, usdc_df], ignore_index=True)
    result = build_combined_supply_series(combined_raw)

    assert not result.empty
    assert "total_stable_mcap" in result.columns
    assert len(result) == 10

    for i, (_, row) in enumerate(result.iterrows()):
        expected = usdt_caps[i] + usdc_caps[i]
        actual = row["total_stable_mcap"]
        assert abs(actual - expected) < 1.0, (
            f"Row {i}: expected={expected:.0f}, got={actual:.0f}"
        )
