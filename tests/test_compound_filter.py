"""Compound F&G + MVRV Filter testleri — H19.

Test grupları:
    T01: Compound logic — her iki filtre geçmeli (both must pass)
    T02: F&G fail → reddedilmeli (fng reason)
    T03: MVRV fail → reddedilmeli (mvrv reason)
    T04: Her iki fail → "both" reason
    T05: Rejection reason tracking — RejectedSignal metadata dogrulamasi
    T06: MVRV unavailable for alt → F&G only applied (skip MVRV gate)
    T07: MVRV unavailable for BTC → F&G still applied
    T08: Lookahead-free — her iki metrik shift(1) kullanir
    T09: CompoundFilterStats toplam sayilar tutarli
    T10: Bos sinyal listesi → bos doner, crash yok
    T11: F&G NaN (tarih yok) → konservatif gecir
    T12: MVRV NaN (tarih yok) → konservatif gecir
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

import sys
ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


# ---------------------------------------------------------------------------
# Fixtures
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


@pytest.fixture
def sample_fng_df() -> pd.DataFrame:
    """50 günlük deterministik F&G verisi (value sabit 50 — neutral)."""
    days = pd.date_range("2023-06-01", periods=60, freq="1D", tz="UTC")
    return pd.DataFrame({
        "ts": days,
        "value": [50] * 60,  # neutral — geçer
        "classification": ["Neutral"] * 60,
    })


@pytest.fixture
def high_fng_df() -> pd.DataFrame:
    """F&G = 80 (greed) — long sinyali reddetmeli."""
    days = pd.date_range("2023-06-01", periods=60, freq="1D", tz="UTC")
    return pd.DataFrame({
        "ts": days,
        "value": [80] * 60,
        "classification": ["Extreme Greed"] * 60,
    })


@pytest.fixture
def low_fng_df() -> pd.DataFrame:
    """F&G = 15 (fear) — short sinyali reddetmeli."""
    days = pd.date_range("2023-06-01", periods=60, freq="1D", tz="UTC")
    return pd.DataFrame({
        "ts": days,
        "value": [15] * 60,
        "classification": ["Extreme Fear"] * 60,
    })


@pytest.fixture
def low_mvrv_df() -> pd.DataFrame:
    """MVRV = 1.2 (bottom zone) — long geçer, short reddeder."""
    days = pd.date_range("2023-06-01", periods=60, freq="1D", tz="UTC")
    return pd.DataFrame({
        "ts": days,
        "CapMVRVCur": [1.2] * 60,
        "asset": ["btc"] * 60,
    })


@pytest.fixture
def high_mvrv_df() -> pd.DataFrame:
    """MVRV = 3.5 (top zone) — long reddeder, short geçer."""
    days = pd.date_range("2023-06-01", periods=60, freq="1D", tz="UTC")
    return pd.DataFrame({
        "ts": days,
        "CapMVRVCur": [3.5] * 60,
        "asset": ["btc"] * 60,
    })


@pytest.fixture
def mid_mvrv_df() -> pd.DataFrame:
    """MVRV = 2.0 (mid range) — neutral, geçer."""
    days = pd.date_range("2023-06-01", periods=60, freq="1D", tz="UTC")
    return pd.DataFrame({
        "ts": days,
        "CapMVRVCur": [2.0] * 60,
        "asset": ["btc"] * 60,
    })


# ---------------------------------------------------------------------------
# T01: Compound logic — neutral FNG + mid MVRV → her iki filtre geçer
# ---------------------------------------------------------------------------

def test_T01_both_filters_pass(sample_fng_df, mid_mvrv_df):
    """Neutral F&G ve mid MVRV: sinyal geçmeli."""
    from price_action.strategies.compound_sentiment_filter import compound_filter_engulfing

    sig = _make_signal(direction="long", ts="2023-06-15")
    filtered, stats, rejections = compound_filter_engulfing(
        [sig], fng_df=sample_fng_df, mvrv_df=mid_mvrv_df,
        fng_long_max=60.0, mvrv_long_max=2.5,
    )
    assert len(filtered) == 1, "Her iki filtre geçince sinyal hayatta olmali"
    assert stats.n_rejected == 0
    assert len(rejections) == 0


# ---------------------------------------------------------------------------
# T02: F&G fail → fng reason
# ---------------------------------------------------------------------------

def test_T02_fng_fail_rejects_long(high_fng_df, mid_mvrv_df):
    """F&G=80 >= long_max=60: long sinyal reddedilmeli, reason='fng'."""
    from price_action.strategies.compound_sentiment_filter import compound_filter_engulfing

    sig = _make_signal(direction="long", ts="2023-06-15")
    filtered, stats, rejections = compound_filter_engulfing(
        [sig], fng_df=high_fng_df, mvrv_df=mid_mvrv_df,
        fng_long_max=60.0, mvrv_long_max=2.5,
    )
    assert len(filtered) == 0, "Yuksek F&G long'u reddetmeli"
    assert stats.rejected_fng == 1
    assert stats.rejected_mvrv == 0
    assert stats.rejected_both == 0
    assert len(rejections) == 1
    assert rejections[0].reason == "fng"


def test_T02b_fng_fail_rejects_short(low_fng_df, mid_mvrv_df):
    """F&G=15 <= short_min=40: short sinyal reddedilmeli."""
    from price_action.strategies.compound_sentiment_filter import compound_filter_engulfing

    sig = _make_signal(direction="short", ts="2023-06-15")
    filtered, stats, rejections = compound_filter_engulfing(
        [sig], fng_df=low_fng_df, mvrv_df=mid_mvrv_df,
        fng_short_min=40.0, mvrv_short_min=1.5,
    )
    assert len(filtered) == 0
    assert stats.rejected_fng == 1
    assert rejections[0].reason == "fng"


# ---------------------------------------------------------------------------
# T03: MVRV fail → mvrv reason
# ---------------------------------------------------------------------------

def test_T03_mvrv_fail_rejects_long(sample_fng_df, high_mvrv_df):
    """MVRV=3.5 >= long_max=2.5: long sinyal reddedilmeli, reason='mvrv'."""
    from price_action.strategies.compound_sentiment_filter import compound_filter_engulfing

    sig = _make_signal(direction="long", ts="2023-06-15")
    filtered, stats, rejections = compound_filter_engulfing(
        [sig], fng_df=sample_fng_df, mvrv_df=high_mvrv_df,
        fng_long_max=60.0, mvrv_long_max=2.5,
    )
    assert len(filtered) == 0, "Yuksek MVRV long'u reddetmeli"
    assert stats.rejected_mvrv == 1
    assert stats.rejected_fng == 0
    assert rejections[0].reason == "mvrv"


def test_T03b_mvrv_fail_rejects_short(sample_fng_df, low_mvrv_df):
    """MVRV=1.2 <= short_min=1.5: short sinyal reddedilmeli, reason='mvrv'."""
    from price_action.strategies.compound_sentiment_filter import compound_filter_engulfing

    sig = _make_signal(direction="short", ts="2023-06-15")
    filtered, stats, rejections = compound_filter_engulfing(
        [sig], fng_df=sample_fng_df, mvrv_df=low_mvrv_df,
        fng_short_min=40.0, mvrv_short_min=1.5,
    )
    assert len(filtered) == 0
    assert stats.rejected_mvrv == 1
    assert rejections[0].reason == "mvrv"


# ---------------------------------------------------------------------------
# T04: Her iki fail → "both" reason
# ---------------------------------------------------------------------------

def test_T04_both_fail_reason_both(high_fng_df, high_mvrv_df):
    """F&G=80 ve MVRV=3.5 — her ikisi de fail: reason='both'."""
    from price_action.strategies.compound_sentiment_filter import compound_filter_engulfing

    sig = _make_signal(direction="long", ts="2023-06-15")
    filtered, stats, rejections = compound_filter_engulfing(
        [sig], fng_df=high_fng_df, mvrv_df=high_mvrv_df,
        fng_long_max=60.0, mvrv_long_max=2.5,
    )
    assert len(filtered) == 0
    assert stats.rejected_both == 1
    assert stats.rejected_fng == 0
    assert stats.rejected_mvrv == 0
    assert rejections[0].reason == "both"


# ---------------------------------------------------------------------------
# T05: Rejection reason tracking — metadata dogrulamasi
# ---------------------------------------------------------------------------

def test_T05_rejection_metadata_populated(high_fng_df, mid_mvrv_df):
    """RejectedSignal.fng_value ve mvrv_value dolu olmali."""
    from price_action.strategies.compound_sentiment_filter import compound_filter_engulfing

    sig = _make_signal(direction="long", ts="2023-06-15")
    _, stats, rejections = compound_filter_engulfing(
        [sig], fng_df=high_fng_df, mvrv_df=mid_mvrv_df,
        fng_long_max=60.0, mvrv_long_max=2.5,
    )
    assert len(rejections) == 1
    rej = rejections[0]
    # fng_value: high_fng=80, lag-1 → 80 (tum gunler 80)
    assert rej.fng_value is not None, "fng_value None olmamali"
    assert rej.fng_value > 0, f"fng_value {rej.fng_value} pozitif olmali"
    # mvrv_value: mid=2.0 → gecti, metadata yine dolu
    assert rej.signal is sig, "Orijinal sinyal referansi korunmali"
    assert rej.reason == "fng"


# ---------------------------------------------------------------------------
# T06: MVRV unavailable for alt → F&G only applied (btc_only_mvrv=True)
# ---------------------------------------------------------------------------

def test_T06_alt_symbol_skips_mvrv_gate(high_mvrv_df, sample_fng_df):
    """Alt coin (ETH/USDT): MVRV=3.5 ama MVRV gate skip edilir — F&G alone."""
    from price_action.strategies.compound_sentiment_filter import compound_filter_engulfing

    # F&G neutral (50), MVRV yüksek ama alt'lar için skip
    sig = _make_signal(direction="long", ts="2023-06-15", symbol="ETH/USDT")
    filtered, stats, rejections = compound_filter_engulfing(
        [sig], fng_df=sample_fng_df, mvrv_df=high_mvrv_df,
        fng_long_max=60.0, mvrv_long_max=2.5,
        btc_only_mvrv=True,
    )
    assert len(filtered) == 1, "Alt coin: MVRV gate skip edilince sinyal geçmeli"
    assert stats.mvrv_skipped >= 1, "mvrv_skipped sayaci artmali"
    assert stats.rejected_mvrv == 0, "Alt coin MVRV ile reddedilmemeli"


# ---------------------------------------------------------------------------
# T07: MVRV mevcut değilse BTC için F&G hala çalışır
# ---------------------------------------------------------------------------

def test_T07_mvrv_none_btc_fng_still_applies(high_fng_df):
    """MVRV=None iken BTC long sinyali F&G ile reddedilmeli."""
    from price_action.strategies.compound_sentiment_filter import compound_filter_engulfing

    sig = _make_signal(direction="long", ts="2023-06-15", symbol="BTC/USDT")
    filtered, stats, rejections = compound_filter_engulfing(
        [sig], fng_df=high_fng_df, mvrv_df=None,
        fng_long_max=60.0, mvrv_long_max=2.5,
    )
    assert len(filtered) == 0, "MVRV=None iken F&G alone reddetmeli"
    assert stats.rejected_fng == 1


# ---------------------------------------------------------------------------
# T08: Lookahead-free — shift(1) kontrol
# ---------------------------------------------------------------------------

def test_T08_lookahead_free_fng_lookup():
    """build_fng_lookup: her tarihin lagı, önceki günün değeri olmalı."""
    from price_action.strategies.compound_sentiment_filter import build_fng_lookup

    days = pd.date_range("2023-06-01", periods=5, freq="1D", tz="UTC")
    values = [10, 20, 30, 40, 50]
    fng_df = pd.DataFrame({"ts": days, "value": values, "classification": ["X"] * 5})

    lookup = build_fng_lookup(fng_df)

    # Day 0 (2023-06-01): lag=NaN (no previous day)
    d0 = pd.Timestamp("2023-06-01", tz="UTC").normalize()
    d1 = pd.Timestamp("2023-06-02", tz="UTC").normalize()
    d2 = pd.Timestamp("2023-06-03", tz="UTC").normalize()

    # d1's lag should be d0's value (10)
    assert lookup.get(d1, None) == 10.0, f"d1 lag beklenen 10, got {lookup.get(d1)}"
    # d2's lag should be d1's value (20)
    assert lookup.get(d2, None) == 20.0, f"d2 lag beklenen 20, got {lookup.get(d2)}"
    # d0 lag = NaN (first row has no previous)
    assert pd.isna(lookup.get(d0, np.nan)), "d0 lag NaN olmali (ilk satir)"


def test_T08b_lookahead_free_mvrv_lookup():
    """build_mvrv_lookup: her tarihin MVRV lag'ı önceki günün değeri olmalı."""
    from price_action.strategies.compound_sentiment_filter import build_mvrv_lookup

    days = pd.date_range("2023-06-01", periods=5, freq="1D", tz="UTC")
    mvrv_vals = [1.0, 1.5, 2.0, 2.5, 3.0]
    mvrv_df = pd.DataFrame({"ts": days, "CapMVRVCur": mvrv_vals, "asset": ["btc"] * 5})

    lookup = build_mvrv_lookup(mvrv_df)

    d1 = pd.Timestamp("2023-06-02", tz="UTC").normalize()
    d3 = pd.Timestamp("2023-06-04", tz="UTC").normalize()

    assert lookup.get(d1, None) == 1.0, f"d1 MVRV lag beklenen 1.0, got {lookup.get(d1)}"
    assert lookup.get(d3, None) == 2.0, f"d3 MVRV lag beklenen 2.0, got {lookup.get(d3)}"


# ---------------------------------------------------------------------------
# T09: CompoundFilterStats toplam sayılar tutarlı
# ---------------------------------------------------------------------------

def test_T09_stats_counts_consistent(high_fng_df, high_mvrv_df, sample_fng_df, mid_mvrv_df):
    """Stats: total = passed + n_rejected, n_rejected = fng + mvrv + both."""
    from price_action.strategies.compound_sentiment_filter import compound_filter_engulfing

    signals = [
        _make_signal(direction="long", ts="2023-06-15"),   # both fail (high_fng + high_mvrv)
        _make_signal(direction="long", ts="2023-06-16"),   # both fail
        _make_signal(direction="short", ts="2023-06-17"),  # short: high_fng passes (80>40 ✓), high_mvrv passes (3.5>1.5 ✓)
    ]
    filtered, stats, rejections = compound_filter_engulfing(
        signals, fng_df=high_fng_df, mvrv_df=high_mvrv_df,
        fng_long_max=60.0, fng_short_min=40.0,
        mvrv_long_max=2.5, mvrv_short_min=1.5,
    )

    assert stats.total == 3
    assert stats.passed + stats.n_rejected == stats.total, (
        f"total={stats.total} != passed={stats.passed} + n_rejected={stats.n_rejected}"
    )
    assert stats.n_rejected == stats.rejected_fng + stats.rejected_mvrv + stats.rejected_both


# ---------------------------------------------------------------------------
# T10: Boş sinyal listesi → boş döner, crash yok
# ---------------------------------------------------------------------------

def test_T10_empty_signals_no_crash(sample_fng_df, mid_mvrv_df):
    """Bos sinyal listesi: bos doner, exception yok."""
    from price_action.strategies.compound_sentiment_filter import compound_filter_engulfing

    filtered, stats, rejections = compound_filter_engulfing(
        [], fng_df=sample_fng_df, mvrv_df=mid_mvrv_df
    )
    assert filtered == []
    assert stats.total == 0
    assert rejections == []


def test_T10b_none_data_no_crash():
    """F&G ve MVRV None: sinyal olduğu gibi gecer (her iki gate disabled)."""
    from price_action.strategies.compound_sentiment_filter import compound_filter_engulfing

    sig = _make_signal(direction="long", ts="2023-06-15")
    filtered, stats, _ = compound_filter_engulfing([sig], fng_df=None, mvrv_df=None)
    assert len(filtered) == 1, "Her iki veri None: konservatif gecir"
    assert stats.n_rejected == 0


# ---------------------------------------------------------------------------
# T11: F&G NaN (tarih yok) → konservatif geçir
# ---------------------------------------------------------------------------

def test_T11_fng_nan_date_passes_conservatively(mid_mvrv_df):
    """Sinyal tarihi F&G lookup'ta yok → NaN → konservatif gecir."""
    from price_action.strategies.compound_sentiment_filter import compound_filter_engulfing

    # F&G starts at 2023-07-01 but signal is at 2023-06-15 (before F&G data)
    future_fng = pd.DataFrame({
        "ts": pd.date_range("2023-07-01", periods=30, freq="1D", tz="UTC"),
        "value": [80] * 30,  # would reject if found
        "classification": ["Extreme Greed"] * 30,
    })
    sig = _make_signal(direction="long", ts="2023-06-15")
    filtered, stats, _ = compound_filter_engulfing(
        [sig], fng_df=future_fng, mvrv_df=mid_mvrv_df,
        fng_long_max=60.0, mvrv_long_max=2.5,
    )
    # F&G unknown date → passes (conservative)
    assert len(filtered) == 1, "F&G tarihi bilinmeyince konservatif gecir"


# ---------------------------------------------------------------------------
# T12: MVRV NaN (tarih yok) → konservatif geçir
# ---------------------------------------------------------------------------

def test_T12_mvrv_nan_date_passes_conservatively(sample_fng_df):
    """MVRV lookup'ta tarihin karsiligi yok → NaN → konservatif gecir."""
    from price_action.strategies.compound_sentiment_filter import compound_filter_engulfing

    # MVRV data starts after signal date
    future_mvrv = pd.DataFrame({
        "ts": pd.date_range("2023-07-01", periods=30, freq="1D", tz="UTC"),
        "CapMVRVCur": [4.0] * 30,  # would reject if found
        "asset": ["btc"] * 30,
    })
    sig = _make_signal(direction="long", ts="2023-06-15", symbol="BTC/USDT")
    filtered, stats, _ = compound_filter_engulfing(
        [sig], fng_df=sample_fng_df, mvrv_df=future_mvrv,
        fng_long_max=60.0, mvrv_long_max=2.5,
    )
    assert len(filtered) == 1, "MVRV tarihi bilinmeyince konservatif gecir"
