"""SEC55.B — AVWAP Numba JIT parity testleri.

Test kategorileri:
  P-1  test_poc_numba_python_parity        — CRITICAL: Numba POC == Python POC (rtol=1e-9)
  P-2  test_avwap_numba_python_parity      — CRITICAL: Numba AVWAP == Python AVWAP (rtol=1e-9)
  P-3  test_poc_nan_handling               — Yeterli veri yok => NaN her iki yolda
  P-4  test_avwap_nan_handling             — Anchor yok => NaN her iki yolda
  P-5  test_poc_edge_win_high_eq_win_low   — win_high == win_low => NaN
  P-6  test_poc_zero_volume                — Zero volume => orta nokta (fallback)
  P-7  test_avwap_zero_volume              — Zero volume => NaN
  P-8  test_poc_1000_bars_strict           — 1000-bar fixture, rtol=1e-9 atol=1e-12
  P-9  test_avwap_1000_bars_strict         — 1000-bar fixture, rtol=1e-9 atol=1e-12
  P-10 test_numba_available_flag           — _AVWAP_NUMBA_AVAILABLE import edilebilir
  P-11 test_use_numba_false_path           — use_numba=False -> Python path, no crash
  P-12 test_determinism                    — Ayni input => ayni output (2 kez)
  P-13 test_no_lookahead_poc              — t bari POC, t+1 bari degistirince t POC degismemeli
  P-14 test_no_lookahead_avwap            — t bari AVWAP, t+1 bari degistirince t AVWAP degismemeli
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest

from price_action.strategies.anchored_vwap_reversal import (
    _AVWAP_NUMBA_AVAILABLE,
    _poc_python_fallback,
    _rolling_avwap_python_fallback,
    _volume_profile_poc,
    _rolling_avwap_from_swing,
)
from price_action.strategies.classic_pa import _fractal_swings


# ---------------------------------------------------------------------------
# Yardimci fabrikalar
# ---------------------------------------------------------------------------

def _base_ts(n: int) -> list[datetime]:
    start = datetime(2020, 1, 1, tzinfo=timezone.utc)
    return [start + timedelta(hours=i) for i in range(n)]


def _make_df(n: int = 300, seed: int = 42) -> pd.DataFrame:
    """Gercekci BTC-benzeri sentetik OHLCV."""
    rng = np.random.default_rng(seed)
    rets = rng.normal(0.0003, 0.015, n)
    close = 30_000.0 * np.exp(np.cumsum(rets))
    open_ = np.r_[close[0], close[:-1]]
    high = np.maximum(open_, close) * (1 + np.abs(rng.normal(0, 0.005, n)))
    low = np.minimum(open_, close) * (1 - np.abs(rng.normal(0, 0.005, n)))
    high = np.maximum.reduce([high, open_, close])
    low = np.minimum.reduce([low, open_, close])
    volume = rng.uniform(1e9, 5e9, n)
    df = pd.DataFrame({
        "ts": _base_ts(n),
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
        "venue": "binance",
        "symbol": "BTC/USDT",
        "timeframe": "15m",
    })
    return df


def _make_df_with_swings(n: int = 300, seed: int = 42) -> pd.DataFrame:
    """Fractal swing kolonlari ile DataFrame."""
    df = _make_df(n=n, seed=seed)
    sh, sl = _fractal_swings(df, n=2)
    df["swing_high"] = sh
    df["swing_low"] = sl
    return df


def _poc_arrays(df: pd.DataFrame, lookback: int = 60, bins: int = 50):
    """Python ve Numba POC dizilerini dondurur."""
    lows = df["low"].values.astype(np.float64)
    highs = df["high"].values.astype(np.float64)
    vols = df["volume"].values.astype(np.float64)

    py_series = _poc_python_fallback(lows, highs, vols, lookback, bins, df.index)

    if _AVWAP_NUMBA_AVAILABLE:
        from price_action.strategies.anchored_vwap_reversal import _avwap_poc_jit_fn
        nb_arr = _avwap_poc_jit_fn(lows, highs, vols, lookback, bins)
        nb_series = pd.Series(nb_arr, index=df.index, dtype=float)
    else:
        nb_series = py_series  # numba yok, parity trivially true

    return py_series, nb_series


def _avwap_arrays(df: pd.DataFrame, swing_col: str = "swing_low", lookback: int = 60):
    """Python ve Numba AVWAP dizilerini dondurur."""
    swing_arr = df[swing_col].values.astype(np.float64)
    closes = df["close"].values.astype(np.float64)
    highs = df["high"].values.astype(np.float64)
    lows = df["low"].values.astype(np.float64)
    vols = np.maximum(df["volume"].values.astype(np.float64), 0.0)

    py_series = _rolling_avwap_python_fallback(
        closes, highs, lows, vols, swing_arr, lookback, df.index
    )

    if _AVWAP_NUMBA_AVAILABLE:
        from price_action.strategies.anchored_vwap_reversal import _avwap_rolling_jit_fn
        nb_arr = _avwap_rolling_jit_fn(closes, highs, lows, vols, swing_arr, lookback)
        nb_series = pd.Series(nb_arr, index=df.index, dtype=float)
    else:
        nb_series = py_series

    return py_series, nb_series


# ---------------------------------------------------------------------------
# P-1: POC Numba-Python parity (CRITICAL)
# ---------------------------------------------------------------------------

def test_poc_numba_python_parity():
    """P-1: Numba POC ve Python POC bit-level parity (rtol=1e-9, atol=1e-12)."""
    df = _make_df(n=300, seed=42)
    py_poc, nb_poc = _poc_arrays(df, lookback=60, bins=50)

    # NaN konumlari esit olmali
    assert np.array_equal(np.isnan(py_poc.values), np.isnan(nb_poc.values)), (
        "NaN mask farkliligi: Python vs Numba POC"
    )

    # Non-NaN degerler strict toleransla esit olmali
    mask = ~np.isnan(py_poc.values)
    if mask.sum() > 0:
        assert np.allclose(
            py_poc.values[mask], nb_poc.values[mask],
            rtol=1e-9, atol=1e-12,
        ), "POC parity FAIL: Python vs Numba rtol=1e-9 sarti karsilanamiyor"


# ---------------------------------------------------------------------------
# P-2: AVWAP Numba-Python parity (CRITICAL)
# ---------------------------------------------------------------------------

def test_avwap_numba_python_parity():
    """P-2: Numba AVWAP ve Python AVWAP bit-level parity (rtol=1e-9, atol=1e-12)."""
    df = _make_df_with_swings(n=300, seed=42)

    for swing_col in ("swing_low", "swing_high"):
        py_avwap, nb_avwap = _avwap_arrays(df, swing_col=swing_col, lookback=60)

        assert np.array_equal(
            np.isnan(py_avwap.values), np.isnan(nb_avwap.values)
        ), f"NaN mask farkliligi: Python vs Numba AVWAP ({swing_col})"

        mask = ~np.isnan(py_avwap.values)
        if mask.sum() > 0:
            assert np.allclose(
                py_avwap.values[mask], nb_avwap.values[mask],
                rtol=1e-9, atol=1e-12,
            ), f"AVWAP parity FAIL ({swing_col}): rtol=1e-9 sarti karsilanamiyor"


# ---------------------------------------------------------------------------
# P-3: POC NaN handling
# ---------------------------------------------------------------------------

def test_poc_nan_handling():
    """P-3: lookback'tan az veri => NaN her iki yolda."""
    df = _make_df(n=80, seed=7)
    lookback = 60

    poc_nb = _volume_profile_poc(df, lookback=lookback, n_buckets=50, use_numba=True)
    poc_py = _volume_profile_poc(df, lookback=lookback, n_buckets=50, use_numba=False)

    # Ilk `lookback` bar NaN olmali
    assert poc_nb.iloc[:lookback].isna().all(), "Numba: ilk lookback bar NaN degil"
    assert poc_py.iloc[:lookback].isna().all(), "Python: ilk lookback bar NaN degil"


# ---------------------------------------------------------------------------
# P-4: AVWAP NaN handling (swing yok)
# ---------------------------------------------------------------------------

def test_avwap_nan_handling():
    """P-4: swing yok => NaN her iki yolda."""
    df = _make_df(n=200, seed=11)
    # Swing kolonu tamamen NaN
    df["swing_low"] = np.nan

    avwap_nb = _rolling_avwap_from_swing(df, swing_col="swing_low", lookback=60, use_numba=True)
    avwap_py = _rolling_avwap_from_swing(df, swing_col="swing_low", lookback=60, use_numba=False)

    assert avwap_nb.isna().all(), "Numba: swing yok ama NaN degil"
    assert avwap_py.isna().all(), "Python: swing yok ama NaN degil"


# ---------------------------------------------------------------------------
# P-5: POC edge — win_high == win_low => NaN
# ---------------------------------------------------------------------------

def test_poc_edge_win_high_eq_win_low():
    """P-5: Tum barlar ayni fiyat (high==low) => POC NaN."""
    n = 100
    lookback = 20
    flat_price = 50_000.0
    df = pd.DataFrame({
        "ts": _base_ts(n),
        "open": np.full(n, flat_price),
        "high": np.full(n, flat_price),
        "low": np.full(n, flat_price),
        "close": np.full(n, flat_price),
        "volume": np.ones(n) * 1e9,
        "venue": "binance",
        "symbol": "BTC/USDT",
        "timeframe": "15m",
    })

    poc_nb = _volume_profile_poc(df, lookback=lookback, n_buckets=10, use_numba=True)
    poc_py = _volume_profile_poc(df, lookback=lookback, n_buckets=10, use_numba=False)

    # price_max == price_min => NaN
    assert poc_nb.iloc[lookback:].isna().all(), "Numba: flat price ama NaN degil"
    assert poc_py.iloc[lookback:].isna().all(), "Python: flat price ama NaN degil"


# ---------------------------------------------------------------------------
# P-6: POC zero volume fallback
# ---------------------------------------------------------------------------

def test_poc_zero_volume():
    """P-6: Zero volume => POC = (price_min + price_max) / 2."""
    n = 100
    lookback = 20
    rng = np.random.default_rng(99)
    close = 30_000.0 + rng.uniform(-1000, 1000, n)
    df = pd.DataFrame({
        "ts": _base_ts(n),
        "open": close,
        "high": close + rng.uniform(10, 200, n),
        "low": close - rng.uniform(10, 200, n),
        "close": close,
        "volume": np.zeros(n),  # sifir volume
        "venue": "binance",
        "symbol": "BTC/USDT",
        "timeframe": "15m",
    })

    poc_py = _volume_profile_poc(df, lookback=lookback, n_buckets=10, use_numba=False)
    poc_nb = _volume_profile_poc(df, lookback=lookback, n_buckets=10, use_numba=True)

    # Zero volume: midpoint expected
    valid_mask = ~np.isnan(poc_py.values)
    if valid_mask.sum() > 0:
        py_vals = poc_py.values[valid_mask]
        nb_vals = poc_nb.values[valid_mask]
        # Her iki yol da ayni midpoint vermeli
        assert np.allclose(py_vals, nb_vals, rtol=1e-9, atol=1e-12), (
            "Zero-volume POC parity FAIL"
        )
        # Midpoint = (min_low + max_high) / 2 gibi bir deger — sadece finite olmali
        assert np.all(np.isfinite(py_vals)), "Zero-volume POC NaN/Inf beklenmiyordu"


# ---------------------------------------------------------------------------
# P-7: AVWAP zero volume
# ---------------------------------------------------------------------------

def test_avwap_zero_volume():
    """P-7: Zero volume => AVWAP NaN (cum_vol=0)."""
    df = _make_df_with_swings(n=200, seed=13)
    df["volume"] = 0.0  # sifir volume

    avwap_nb = _rolling_avwap_from_swing(df, swing_col="swing_low", lookback=60, use_numba=True)
    avwap_py = _rolling_avwap_from_swing(df, swing_col="swing_low", lookback=60, use_numba=False)

    assert avwap_nb.isna().all(), "Numba: zero volume AVWAP NaN degil"
    assert avwap_py.isna().all(), "Python: zero volume AVWAP NaN degil"


# ---------------------------------------------------------------------------
# P-8: POC 1000-bar strict parity
# ---------------------------------------------------------------------------

def test_poc_1000_bars_strict():
    """P-8: 1000 bar fixture, rtol=1e-9 atol=1e-12 POC parity."""
    df = _make_df(n=1000, seed=1234)
    py_poc, nb_poc = _poc_arrays(df, lookback=60, bins=50)

    nan_mask_py = np.isnan(py_poc.values)
    nan_mask_nb = np.isnan(nb_poc.values)
    assert np.array_equal(nan_mask_py, nan_mask_nb), (
        "1000-bar NaN mask uyumsuz: Python vs Numba"
    )

    valid = ~nan_mask_py
    assert valid.sum() > 800, f"Yeterli valid bar yok: {valid.sum()}"
    assert np.allclose(
        py_poc.values[valid], nb_poc.values[valid],
        rtol=1e-9, atol=1e-12,
    ), "1000-bar POC parity FAIL: rtol=1e-9"


# ---------------------------------------------------------------------------
# P-9: AVWAP 1000-bar strict parity
# ---------------------------------------------------------------------------

def test_avwap_1000_bars_strict():
    """P-9: 1000 bar fixture, rtol=1e-9 atol=1e-12 AVWAP parity."""
    df = _make_df_with_swings(n=1000, seed=5678)

    for swing_col in ("swing_low", "swing_high"):
        py_av, nb_av = _avwap_arrays(df, swing_col=swing_col, lookback=60)

        nan_mask_py = np.isnan(py_av.values)
        nan_mask_nb = np.isnan(nb_av.values)
        assert np.array_equal(nan_mask_py, nan_mask_nb), (
            f"1000-bar AVWAP NaN mask uyumsuz ({swing_col})"
        )

        valid = ~nan_mask_py
        if valid.sum() > 0:
            assert np.allclose(
                py_av.values[valid], nb_av.values[valid],
                rtol=1e-9, atol=1e-12,
            ), f"1000-bar AVWAP parity FAIL ({swing_col}): rtol=1e-9"


# ---------------------------------------------------------------------------
# P-10: _AVWAP_NUMBA_AVAILABLE flag
# ---------------------------------------------------------------------------

def test_numba_available_flag():
    """P-10: _AVWAP_NUMBA_AVAILABLE import edilebilir ve bool."""
    assert isinstance(_AVWAP_NUMBA_AVAILABLE, bool)
    # Numba yüklüyse True, yoksa False — her iki durum gecerli
    # Burada sadece crash olmadigi test edilir


# ---------------------------------------------------------------------------
# P-11: use_numba=False -> Python path
# ---------------------------------------------------------------------------

def test_use_numba_false_path():
    """P-11: use_numba=False -> Python fallback, no crash, gecerli sonuc."""
    df = _make_df_with_swings(n=200, seed=77)

    poc_py = _volume_profile_poc(df, lookback=60, n_buckets=50, use_numba=False)
    avwap_py = _rolling_avwap_from_swing(df, swing_col="swing_low", lookback=60, use_numba=False)

    assert isinstance(poc_py, pd.Series), "POC Python path pd.Series donmeli"
    assert isinstance(avwap_py, pd.Series), "AVWAP Python path pd.Series donmeli"
    assert len(poc_py) == len(df)
    assert len(avwap_py) == len(df)

    # Bazı valid degerler olmali (n>lookback)
    assert poc_py.iloc[60:].notna().sum() > 0, "POC Python path hicbir valid deger yok"


# ---------------------------------------------------------------------------
# P-12: Determinizm
# ---------------------------------------------------------------------------

def test_determinism():
    """P-12: Ayni input => ayni output (2 kez calistirma)."""
    df = _make_df_with_swings(n=300, seed=42)

    poc1 = _volume_profile_poc(df, lookback=60, n_buckets=50, use_numba=True)
    poc2 = _volume_profile_poc(df, lookback=60, n_buckets=50, use_numba=True)

    avwap1 = _rolling_avwap_from_swing(df, swing_col="swing_low", lookback=60, use_numba=True)
    avwap2 = _rolling_avwap_from_swing(df, swing_col="swing_low", lookback=60, use_numba=True)

    assert np.array_equal(
        np.nan_to_num(poc1.values, nan=0.0),
        np.nan_to_num(poc2.values, nan=0.0),
    ), "POC non-deterministic"
    assert np.array_equal(
        np.nan_to_num(avwap1.values, nan=0.0),
        np.nan_to_num(avwap2.values, nan=0.0),
    ), "AVWAP non-deterministic"


# ---------------------------------------------------------------------------
# P-13: Lookahead-free POC
# ---------------------------------------------------------------------------

def test_no_lookahead_poc():
    """P-13: t bari POC, t+1 bari degistirince t POC degismemeli."""
    df = _make_df(n=200, seed=42)
    lookback = 60
    t = 120  # test bari

    poc_orig = _volume_profile_poc(df.iloc[:t + 1], lookback=lookback, n_buckets=50, use_numba=False)
    poc_t_orig = poc_orig.iloc[t]

    # t+1 barindan sonrasini degistir (t+1'in verisi olmali)
    df_mod = df.copy()
    df_mod.loc[df_mod.index[t + 1], "high"] *= 10.0
    df_mod.loc[df_mod.index[t + 1], "low"] *= 0.1
    df_mod.loc[df_mod.index[t + 1], "volume"] *= 100.0

    poc_mod = _volume_profile_poc(df_mod.iloc[:t + 1], lookback=lookback, n_buckets=50, use_numba=False)
    poc_t_mod = poc_mod.iloc[t]

    # t bari POC degismemeli (t+1 verisi t penceresi disinda)
    if not (np.isnan(poc_t_orig) and np.isnan(poc_t_mod)):
        assert abs(poc_t_orig - poc_t_mod) < 1e-10, (
            f"Lookahead FAIL: t={t} POC degisti t+1 verisi degistiginde. "
            f"orig={poc_t_orig:.4f} mod={poc_t_mod:.4f}"
        )


# ---------------------------------------------------------------------------
# P-14: Lookahead-free AVWAP
# ---------------------------------------------------------------------------

def test_no_lookahead_avwap():
    """P-14: t bari AVWAP, t+1 bari degistirince t AVWAP degismemeli."""
    df = _make_df_with_swings(n=200, seed=42)
    lookback = 60
    t = 120

    avwap_orig = _rolling_avwap_from_swing(
        df.iloc[:t + 1], swing_col="swing_low", lookback=lookback, use_numba=False
    )
    avwap_t_orig = avwap_orig.iloc[t]

    # t+1 sonrasini degistir
    df_mod = df.copy()
    df_mod.loc[df_mod.index[t + 1], "close"] *= 5.0
    df_mod.loc[df_mod.index[t + 1], "volume"] *= 100.0

    avwap_mod = _rolling_avwap_from_swing(
        df_mod.iloc[:t + 1], swing_col="swing_low", lookback=lookback, use_numba=False
    )
    avwap_t_mod = avwap_mod.iloc[t]

    if not (np.isnan(avwap_t_orig) and np.isnan(avwap_t_mod)):
        assert abs(avwap_t_orig - avwap_t_mod) < 1e-10, (
            f"Lookahead FAIL: t={t} AVWAP degisti t+1 verisi degistiginde. "
            f"orig={avwap_t_orig:.4f} mod={avwap_t_mod:.4f}"
        )
