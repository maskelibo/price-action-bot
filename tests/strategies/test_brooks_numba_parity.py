"""SEC55.C — Brooks Failed Breakout Numba JIT parity testleri.

Test kategorileri:
  B-1  test_failed_bo_numba_python_parity    — CRITICAL: rtol=1e-9, atol=1e-12
  B-2  test_nan_nb_high                      — NaN nb_high => BO yok
  B-3  test_no_failure_in_time              — BO var ama max_bars icinde fail yok
  B-4  test_bull_trap_detected               — Bilinen bull trap senaryosu
  B-5  test_bear_trap_detected               — Bilinen bear trap senaryosu
  B-6  test_edge_insufficient_data           — n=1 => bos output
  B-7  test_1000_bars_strict                 — 1000-bar rtol=1e-9
  B-8  test_no_lookahead                     — t+1 degisince t etkilenmemeli
  B-9  test_numba_available_flag             — _BROOKS_NUMBA_AVAILABLE import
  B-10 test_python_fallback_path             — use_numba=False, no crash
  B-11 test_determinism                      — Ayni input => ayni output
  B-12 test_failed_breakout_flags_highlevel  — _failed_breakout_flags pd.Series output
  B-13 test_extreme_preserved               — BO bar swing high/low SL baz olarak korunuyor
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest

from price_action.strategies.brooks_failed_breakout import (
    _BROOKS_NUMBA_AVAILABLE,
    _failed_bo_python_fallback,
    _run_failed_bo_kernel,
    _failed_breakout_flags,
    _rolling_n_bar_high,
    _rolling_n_bar_low,
)


# ---------------------------------------------------------------------------
# Yardimcilar
# ---------------------------------------------------------------------------

def _make_df(n: int = 500, seed: int = 42) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    rets = rng.normal(0.0003, 0.015, n)
    close = 30_000.0 * np.exp(np.cumsum(rets))
    open_ = np.r_[close[0], close[:-1]]
    high = np.maximum(open_, close) * (1 + np.abs(rng.normal(0, 0.005, n)))
    low = np.minimum(open_, close) * (1 - np.abs(rng.normal(0, 0.005, n)))
    high = np.maximum.reduce([high, open_, close])
    low = np.minimum.reduce([low, open_, close])
    volume = rng.uniform(1e9, 5e9, n)
    ts_start = datetime(2020, 1, 1, tzinfo=timezone.utc)
    ts_list = [ts_start + timedelta(hours=i) for i in range(n)]
    return pd.DataFrame({
        "ts": ts_list,
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
        "venue": "BINANCE",
        "symbol": "BTCUSDT",
        "timeframe": "15m",
    })


def _nb_arrays(df: pd.DataFrame, lookback: int = 20):
    nb_high = _rolling_n_bar_high(df, lookback)
    nb_low = _rolling_n_bar_low(df, lookback)
    return (
        df["close"].to_numpy(dtype=np.float64),
        df["high"].to_numpy(dtype=np.float64),
        df["low"].to_numpy(dtype=np.float64),
        nb_high.to_numpy(dtype=np.float64),
        nb_low.to_numpy(dtype=np.float64),
    )


# ---------------------------------------------------------------------------
# B-1: Numba vs Python parity
# ---------------------------------------------------------------------------

def test_failed_bo_numba_python_parity():
    df = _make_df(500)
    closes, highs, lows, nb_high, nb_low = _nb_arrays(df)

    py_bf, py_bear, py_bext, py_bearext = _failed_bo_python_fallback(
        closes, highs, lows, nb_high, nb_low, max_bars_to_fail=3
    )

    if _BROOKS_NUMBA_AVAILABLE:
        nb_bf, nb_bear, nb_bext, nb_bearext = _run_failed_bo_kernel(
            closes, highs, lows, nb_high, nb_low, max_bars_to_fail=3, use_numba=True
        )
        assert np.allclose(py_bf, nb_bf, rtol=1e-9, atol=1e-12, equal_nan=True), \
            "bull_failed mismatch"
        assert np.allclose(py_bear, nb_bear, rtol=1e-9, atol=1e-12, equal_nan=True), \
            "bear_failed mismatch"
        assert np.allclose(py_bext, nb_bext, rtol=1e-9, atol=1e-12, equal_nan=True), \
            "bull_extreme mismatch"
        assert np.allclose(py_bearext, nb_bearext, rtol=1e-9, atol=1e-12, equal_nan=True), \
            "bear_extreme mismatch"
    else:
        pytest.skip("Numba kurulu degil")


# ---------------------------------------------------------------------------
# B-2: NaN nb_high => BO yok
# ---------------------------------------------------------------------------

def test_nan_nb_high():
    n = 50
    closes = np.full(n, 100.0)
    highs = np.full(n, 101.0)
    lows = np.full(n, 99.0)
    nb_high = np.full(n, np.nan)
    nb_low = np.full(n, np.nan)

    bf, bear, bext, bearext = _run_failed_bo_kernel(
        closes, highs, lows, nb_high, nb_low, 3, use_numba=False
    )
    assert bf.sum() == 0.0
    assert bear.sum() == 0.0
    assert np.all(np.isnan(bext))
    assert np.all(np.isnan(bearext))


# ---------------------------------------------------------------------------
# B-3: BO var ama max_bars icinde fail yok
# ---------------------------------------------------------------------------

def test_no_failure_in_time():
    """BO bari 10'da, ama sonraki 3 barda close level'a donmuyor."""
    n = 30
    close = np.full(n, 100.0)
    high = np.full(n, 101.0)
    low = np.full(n, 99.0)
    nb_high = np.full(n, 100.0)
    nb_low = np.full(n, 100.0)

    # Bar 10: bull BO (high > nb_high AND close > nb_high)
    close[10] = 101.5  # close > 100 => bull BO
    high[10] = 102.0

    # Bar 11,12,13: close hala 101.5 (level uzzerinde => NO failure)
    close[11:14] = 101.5

    bf, _, _, _ = _run_failed_bo_kernel(
        close, high, low, nb_high, nb_low, 3, use_numba=False
    )
    # failure = close < nb_high_at_BO (100.0) => 101.5 > 100 => hic failure yok
    assert bf.sum() == 0.0


# ---------------------------------------------------------------------------
# B-4: Bilinen bull trap senaryosu
# ---------------------------------------------------------------------------

def test_bull_trap_detected():
    """Bar 10: bull BO (close > nb_high=100). Bar 12: close < 100 => bull trap."""
    n = 30
    close = np.full(n, 99.0)   # hepsi level altinda
    high = np.full(n, 100.0)
    low = np.full(n, 98.0)
    nb_high = np.full(n, 100.0)
    nb_low = np.full(n, 98.0)

    # Bar 10: bull BO
    close[10] = 101.0
    high[10] = 102.0

    # Bar 11,12: close 99 (< 100 => failure)
    close[11] = 99.0
    close[12] = 99.0

    bf, _, bext, _ = _run_failed_bo_kernel(
        close, high, low, nb_high, nb_low, 3, use_numba=False
    )
    # Bar 11 veya 12'de bull_failed = True bekleniyor
    assert bf[11] == 1.0 or bf[12] == 1.0, "Bull trap tespit edilemedi"
    # Extreme: BO bar high = 102
    detected_idx = 11 if bf[11] > 0.5 else 12
    assert abs(bext[detected_idx] - 102.0) < 1e-9, "BO extreme (high) yanlis"


# ---------------------------------------------------------------------------
# B-5: Bilinen bear trap senaryosu
# ---------------------------------------------------------------------------

def test_bear_trap_detected():
    """Bar 15: bear BO (close < nb_low=100). Bar 17: close > 100 => bear trap."""
    n = 40
    close = np.full(n, 101.0)
    high = np.full(n, 102.0)
    low = np.full(n, 100.0)
    nb_high = np.full(n, 102.0)
    nb_low = np.full(n, 100.0)

    # Bar 15: bear BO
    close[15] = 99.0
    low[15] = 98.0

    # Bar 16,17: close 101 (> 100 => failure)
    close[16] = 101.0
    close[17] = 101.0

    _, bear, _, bearext = _run_failed_bo_kernel(
        close, high, low, nb_high, nb_low, 3, use_numba=False
    )
    assert bear[16] == 1.0 or bear[17] == 1.0, "Bear trap tespit edilemedi"
    detected_idx = 16 if bear[16] > 0.5 else 17
    assert abs(bearext[detected_idx] - 98.0) < 1e-9, "BO extreme (low) yanlis"


# ---------------------------------------------------------------------------
# B-6: Yetersiz veri
# ---------------------------------------------------------------------------

def test_edge_insufficient_data():
    n = 1
    closes = np.array([100.0])
    highs = np.array([101.0])
    lows = np.array([99.0])
    nb_high = np.array([np.nan])
    nb_low = np.array([np.nan])

    bf, bear, bext, bearext = _run_failed_bo_kernel(
        closes, highs, lows, nb_high, nb_low, 3, use_numba=False
    )
    assert len(bf) == 1
    assert bf[0] == 0.0


# ---------------------------------------------------------------------------
# B-7: 1000-bar strict parity
# ---------------------------------------------------------------------------

def test_1000_bars_strict():
    df = _make_df(1000)
    closes, highs, lows, nb_high, nb_low = _nb_arrays(df, lookback=20)

    py_bf, py_bear, py_bext, py_bearext = _failed_bo_python_fallback(
        closes, highs, lows, nb_high, nb_low, max_bars_to_fail=3
    )

    if _BROOKS_NUMBA_AVAILABLE:
        nb_bf, nb_bear, nb_bext, nb_bearext = _run_failed_bo_kernel(
            closes, highs, lows, nb_high, nb_low, 3, use_numba=True
        )
        assert np.allclose(py_bf, nb_bf, rtol=1e-9, atol=1e-12, equal_nan=True)
        assert np.allclose(py_bear, nb_bear, rtol=1e-9, atol=1e-12, equal_nan=True)
        assert np.allclose(py_bext, nb_bext, rtol=1e-9, atol=1e-12, equal_nan=True)
        assert np.allclose(py_bearext, nb_bearext, rtol=1e-9, atol=1e-12, equal_nan=True)
    else:
        pytest.skip("Numba kurulu degil")


# ---------------------------------------------------------------------------
# B-8: Lookahead audit
# ---------------------------------------------------------------------------

def test_no_lookahead():
    df = _make_df(200)
    closes, highs, lows, nb_high, nb_low = _nb_arrays(df)

    bf1, bear1, bext1, bearext1 = _run_failed_bo_kernel(
        closes, highs, lows, nb_high, nb_low, 3, use_numba=False
    )

    # Bar 100'u degistir (gelecek simulasyonu)
    closes2 = closes.copy()
    closes2[100] = closes[100] * 2.0
    bf2, bear2, bext2, bearext2 = _run_failed_bo_kernel(
        closes2, highs, lows, nb_high, nb_low, 3, use_numba=False
    )

    # t < 100 icin hicbir degisim olmamali (bar 100 oncesi)
    for t in range(99):
        assert bf1[t] == bf2[t], f"Lookahead leak at t={t} (bull)"
        assert bear1[t] == bear2[t], f"Lookahead leak at t={t} (bear)"


# ---------------------------------------------------------------------------
# B-9: Flag import
# ---------------------------------------------------------------------------

def test_numba_available_flag():
    assert isinstance(_BROOKS_NUMBA_AVAILABLE, bool)


# ---------------------------------------------------------------------------
# B-10: Python fallback
# ---------------------------------------------------------------------------

def test_python_fallback_path():
    df = _make_df(100)
    closes, highs, lows, nb_high, nb_low = _nb_arrays(df)
    bf, bear, bext, bearext = _run_failed_bo_kernel(
        closes, highs, lows, nb_high, nb_low, 3, use_numba=False
    )
    assert isinstance(bf, np.ndarray)
    assert isinstance(bear, np.ndarray)


# ---------------------------------------------------------------------------
# B-11: Determinism
# ---------------------------------------------------------------------------

def test_determinism():
    df = _make_df(300)
    closes, highs, lows, nb_high, nb_low = _nb_arrays(df)

    bf1, bear1, bext1, bearext1 = _run_failed_bo_kernel(
        closes, highs, lows, nb_high, nb_low, 3, use_numba=False
    )
    bf2, bear2, bext2, bearext2 = _run_failed_bo_kernel(
        closes, highs, lows, nb_high, nb_low, 3, use_numba=False
    )

    assert np.array_equal(bf1, bf2)
    assert np.array_equal(bear1, bear2)


# ---------------------------------------------------------------------------
# B-12: High-level _failed_breakout_flags pd.Series output
# ---------------------------------------------------------------------------

def test_failed_breakout_flags_highlevel():
    df = _make_df(200)
    nb_high = _rolling_n_bar_high(df, 20)
    nb_low = _rolling_n_bar_low(df, 20)

    bull_fail, bear_fail, bull_ext, bear_ext = _failed_breakout_flags(
        df, nb_high, nb_low, max_bars_to_fail=3, use_numba=False
    )

    assert isinstance(bull_fail, pd.Series)
    assert isinstance(bear_fail, pd.Series)
    assert isinstance(bull_ext, pd.Series)
    assert isinstance(bear_ext, pd.Series)
    assert len(bull_fail) == len(df)
    # Failure bar'da extreme NaN olmamali
    for idx in bull_fail[bull_fail].index:
        assert not np.isnan(bull_ext.loc[idx]), f"bull_extreme NaN at failure bar {idx}"
    for idx in bear_fail[bear_fail].index:
        assert not np.isnan(bear_ext.loc[idx]), f"bear_extreme NaN at failure bar {idx}"


# ---------------------------------------------------------------------------
# B-13: Extreme preserved (BO bar swing high/low)
# ---------------------------------------------------------------------------

def test_extreme_preserved():
    """BO bar high/low eksiksiz SL baz olarak iletilmeli."""
    n = 20
    close = np.full(n, 99.0)
    high = np.full(n, 100.0)
    low = np.full(n, 98.0)
    nb_high = np.full(n, 100.0)
    nb_low = np.full(n, 98.0)

    # Bull BO bar 5 (high=110 distinctive)
    close[5] = 101.0
    high[5] = 110.0  # distinctive extreme

    # Bar 6: failure (close < 100)
    close[6] = 99.0

    bf, _, bext, _ = _run_failed_bo_kernel(
        close, high, low, nb_high, nb_low, 3, use_numba=False
    )

    assert bf[6] == 1.0, "Failure tespit edilmeli"
    assert abs(bext[6] - 110.0) < 1e-9, f"Extreme preserved olmali: got {bext[6]}"
