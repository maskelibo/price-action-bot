"""SEC55.C / SEC55.D — Engulfing Continuation kernel parity testleri.

SEC55.D eklemeleri (E-16..E-21):
  E-16 test_numpy_sr_proximity_parity_with_python  — numpy path rtol=1e-9 vs Python O(n*m)
  E-17 test_numpy_engulfing_score_parity           — numpy path rtol=1e-9 vs Python O(n)
  E-18 test_numpy_sr_proximity_speedup             — 730-bar benchmark < 1ms
  E-19 test_numpy_engulfing_score_speedup          — 730-bar benchmark < 1ms
  E-20 test_dispatch_default_numpy                 — env var eksikken numpy aktif
  E-21 test_numpy_sr_proximity_multiple_hits       — Birden fazla SR record ayni bar

SEC55.C kategorileri (E-1..E-15):
  E-1  test_sr_proximity_numba_python_parity  — CRITICAL: rtol=1e-9
  E-2  test_engulfing_score_numba_python_parity — CRITICAL: rtol=1e-9
  E-3  test_sr_proximity_no_levels            — SR yok => hepsi False
  E-4  test_sr_proximity_exact_hit            — Bilinan hit senaryosu
  E-5  test_engulfing_score_below_min         — final_score < min_score => 0
  E-6  test_engulfing_score_bonus             — near_sr => bonus eklendi
  E-7  test_engulfing_score_penalty           — not near_sr, prox>0 => -0.25
  E-8  test_sl_structural_used               — struct_sl_long dogru kullaniliyor
  E-9  test_sl_atr_fallback                  — NaN struct_sl => ATR fallback
  E-10 test_no_lookahead_sr                  — SR proximity lookahead audit
  E-11 test_1000_bars_strict                  — 1000-bar rtol=1e-9
  E-12 test_numba_available_flag              — _ENGULF_NUMBA_AVAILABLE import
  E-13 test_python_fallback_path              — use_numba=False, no crash
  E-14 test_determinism                       — Ayni input => ayni output
  E-15 test_zero_atr_skipped                 — ATR=0 => signal yok
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest

import os
import time

from price_action.strategies.engulfing_continuation import (
    _ENGULF_NUMBA_AVAILABLE,
    _sr_proximity_python_fallback,
    _engulfing_score_python_fallback,
    _sr_proximity_numpy,
    _engulfing_score_numpy,
    _run_sr_proximity,
    _run_engulfing_score,
)


# ---------------------------------------------------------------------------
# Yardimcilar
# ---------------------------------------------------------------------------

def _make_arrays(n: int, seed: int = 42):
    rng = np.random.default_rng(seed)
    close = 30_000.0 + rng.normal(0, 500, n)
    atr = np.abs(rng.normal(200, 50, n))
    return close, atr


def _make_score_arrays(n: int, seed: int = 99):
    rng = np.random.default_rng(seed)
    long_score = rng.choice([0.0, 1.5, 2.0], size=n).astype(np.float64)
    short_score = rng.choice([0.0, 1.5, 2.0], size=n).astype(np.float64)
    close, atr = _make_arrays(n, seed)
    struct_sl_long = close - 2.0 * atr
    struct_sl_short = close + 2.0 * atr
    near_sr = rng.integers(0, 2, n).astype(np.float64)
    return long_score, short_score, near_sr, atr, struct_sl_long, struct_sl_short, close


# ---------------------------------------------------------------------------
# E-1: SR proximity parity
# ---------------------------------------------------------------------------

def test_sr_proximity_numba_python_parity():
    n = 500
    rng = np.random.default_rng(1)
    closes, atrs = _make_arrays(n)
    # SR records: 100 kayit
    sr_bar_idx = rng.integers(0, n, 100).astype(np.int64)
    sr_levels_arr = closes[sr_bar_idx] + rng.normal(0, 50, 100)

    py_out = _sr_proximity_python_fallback(closes, atrs, sr_bar_idx, sr_levels_arr, 0.5)

    if _ENGULF_NUMBA_AVAILABLE:
        nb_out = _run_sr_proximity(closes, atrs, sr_bar_idx, sr_levels_arr, 0.5, use_numba=True)
        assert np.allclose(py_out, nb_out, rtol=1e-9, atol=1e-12, equal_nan=True), \
            "SR proximity parity fail"
    else:
        pytest.skip("Numba kurulu degil")


# ---------------------------------------------------------------------------
# E-2: Engulfing score parity
# ---------------------------------------------------------------------------

def test_engulfing_score_numba_python_parity():
    n = 500
    long_s, short_s, near_sr, atr, sl_l, sl_s, close = _make_score_arrays(n)

    py_lf, py_sf, py_sll, py_sls = _engulfing_score_python_fallback(
        long_s, short_s, near_sr, atr, sl_l, sl_s, close,
        bonus=0.5, proximity_atr=0.5, min_score=1.5
    )

    if _ENGULF_NUMBA_AVAILABLE:
        nb_lf, nb_sf, nb_sll, nb_sls = _run_engulfing_score(
            long_s, short_s, near_sr, atr, sl_l, sl_s, close,
            bonus=0.5, proximity_atr=0.5, min_score=1.5, use_numba=True
        )
        assert np.allclose(py_lf, nb_lf, rtol=1e-9, atol=1e-12, equal_nan=True)
        assert np.allclose(py_sf, nb_sf, rtol=1e-9, atol=1e-12, equal_nan=True)
        assert np.allclose(py_sll, nb_sll, rtol=1e-9, atol=1e-12, equal_nan=True)
        assert np.allclose(py_sls, nb_sls, rtol=1e-9, atol=1e-12, equal_nan=True)
    else:
        pytest.skip("Numba kurulu degil")


# ---------------------------------------------------------------------------
# E-3: SR proximity — SR yok
# ---------------------------------------------------------------------------

def test_sr_proximity_no_levels():
    n = 100
    closes, atrs = _make_arrays(n)
    sr_bar_idx = np.empty(0, dtype=np.int64)
    sr_levels_arr = np.empty(0, dtype=np.float64)

    out = _run_sr_proximity(closes, atrs, sr_bar_idx, sr_levels_arr, 0.5, use_numba=False)
    assert out.sum() == 0.0, "SR yok => hepsi False"


# ---------------------------------------------------------------------------
# E-4: SR proximity — Bilinen hit
# ---------------------------------------------------------------------------

def test_sr_proximity_exact_hit():
    n = 50
    closes = np.full(n, 100.0)
    atrs = np.full(n, 10.0)
    # Bar 10'da SR level = 100.0 (tam esit)
    sr_bar_idx = np.array([10], dtype=np.int64)
    sr_levels_arr = np.array([100.0])  # |100 - 100| = 0 <= 0.5 * 10 = 5 => hit

    out = _run_sr_proximity(closes, atrs, sr_bar_idx, sr_levels_arr, 0.5, use_numba=False)
    assert out[10] == 1.0, "Bar 10'da SR hit olmali"
    # Diger barlar 0
    assert out[:10].sum() == 0.0
    assert out[11:].sum() == 0.0


# ---------------------------------------------------------------------------
# E-5: Engulfing score — min_score gate
# ---------------------------------------------------------------------------

def test_engulfing_score_below_min():
    n = 10
    long_s = np.full(n, 1.0)   # weight=1.0 < min_score=1.5
    short_s = np.full(n, 0.0)
    near_sr = np.zeros(n)
    atr = np.full(n, 100.0)
    sl_l = np.full(n, 29_000.0)
    sl_s = np.full(n, 31_000.0)
    close = np.full(n, 30_000.0)

    lf, sf, sll, sls = _run_engulfing_score(
        long_s, short_s, near_sr, atr, sl_l, sl_s, close,
        bonus=0.0, proximity_atr=0.0, min_score=1.5, use_numba=False
    )
    assert lf.sum() == 0.0, "score=1.0 < min_score=1.5 => hic signal olmamali"


# ---------------------------------------------------------------------------
# E-6: Bonus eklenmesi (near_sr=True)
# ---------------------------------------------------------------------------

def test_engulfing_score_bonus():
    n = 5
    long_s = np.full(n, 1.5)   # base score
    short_s = np.zeros(n)
    near_sr = np.ones(n)        # hepsi near_sr
    atr = np.full(n, 100.0)
    sl_l = np.full(n, 29_000.0)
    sl_s = np.full(n, 31_000.0)
    close = np.full(n, 30_000.0)

    lf, _, _, _ = _run_engulfing_score(
        long_s, short_s, near_sr, atr, sl_l, sl_s, close,
        bonus=0.5, proximity_atr=0.5, min_score=1.5, use_numba=False
    )
    # final_score = 1.5 + 0.5 = 2.0 >= 1.5 => all active
    assert (lf > 0).all(), "Bonus ile min_score asilmali"
    assert np.allclose(lf, 2.0), f"Expected 2.0, got {lf}"


# ---------------------------------------------------------------------------
# E-7: Penalty (not near_sr, proximity_atr > 0) => -0.25
# ---------------------------------------------------------------------------

def test_engulfing_score_penalty():
    n = 5
    long_s = np.full(n, 1.5)   # base score
    short_s = np.zeros(n)
    near_sr = np.zeros(n)       # hicbiri near_sr
    atr = np.full(n, 100.0)
    sl_l = np.full(n, 29_000.0)
    sl_s = np.full(n, 31_000.0)
    close = np.full(n, 30_000.0)

    lf, _, _, _ = _run_engulfing_score(
        long_s, short_s, near_sr, atr, sl_l, sl_s, close,
        bonus=0.0, proximity_atr=0.5, min_score=1.5, use_numba=False
    )
    # final_score = 1.5 - 0.25 = 1.25 < 1.5 => hic signal
    assert lf.sum() == 0.0, "Penalty ile 1.25 < 1.5 => signal olmamal"


# ---------------------------------------------------------------------------
# E-8: Structural SL kullaniliyor
# ---------------------------------------------------------------------------

def test_sl_structural_used():
    n = 5
    long_s = np.full(n, 2.0)   # above min_score
    short_s = np.zeros(n)
    near_sr = np.zeros(n)
    atr = np.full(n, 100.0)
    struct_sl_long = np.full(n, 29_500.0)  # distinctif deger
    sl_s = np.full(n, 31_000.0)
    close = np.full(n, 30_000.0)

    lf, _, sll, _ = _run_engulfing_score(
        long_s, short_s, near_sr, atr, struct_sl_long, sl_s, close,
        bonus=0.0, proximity_atr=0.0, min_score=1.5, use_numba=False
    )
    # struct_sl_long = 29500 < close - 0.5*atr = 30000 - 50 = 29950 => min(29500,29950)=29500
    active_mask = lf > 0.0
    assert active_mask.any()
    for i in range(n):
        if lf[i] > 0.0:
            assert abs(sll[i] - 29_500.0) < 1e-6, f"Structural SL kullanilmali: {sll[i]}"


# ---------------------------------------------------------------------------
# E-9: ATR fallback (NaN struct_sl)
# ---------------------------------------------------------------------------

def test_sl_atr_fallback():
    n = 5
    long_s = np.full(n, 2.0)
    short_s = np.zeros(n)
    near_sr = np.zeros(n)
    atr = np.full(n, 200.0)
    sl_l_nan = np.full(n, np.nan)   # NaN => fallback
    sl_s = np.full(n, 31_000.0)
    close = np.full(n, 30_000.0)

    lf, _, sll, _ = _run_engulfing_score(
        long_s, short_s, near_sr, atr, sl_l_nan, sl_s, close,
        bonus=0.0, proximity_atr=0.0, min_score=1.5, use_numba=False
    )
    # Fallback: sl_raw = close - 2*atr = 30000 - 400 = 29600
    # min(29600, close - 0.5*atr) = min(29600, 29900) = 29600
    for i in range(n):
        if lf[i] > 0.0:
            expected = close[i] - 2.0 * atr[i]  # 29600
            assert abs(sll[i] - expected) < 1e-6, f"ATR fallback yanlis: {sll[i]}"


# ---------------------------------------------------------------------------
# E-10: Lookahead — SR proximity
# ---------------------------------------------------------------------------

def test_no_lookahead_sr():
    n = 200
    rng = np.random.default_rng(42)
    closes = 30_000.0 + rng.normal(0, 500, n)
    atrs = np.abs(rng.normal(200, 50, n))
    sr_bar_idx = np.array([10, 50, 100, 150], dtype=np.int64)
    sr_levels_arr = closes[sr_bar_idx]

    out1 = _sr_proximity_python_fallback(closes, atrs, sr_bar_idx, sr_levels_arr, 0.5)

    # Bar 150'yi degistir
    closes2 = closes.copy()
    closes2[150] = closes[150] * 2.0
    out2 = _sr_proximity_python_fallback(closes2, atrs, sr_bar_idx, sr_levels_arr, 0.5)

    # t < 150 etkilenmemeli
    for t in range(149):
        assert out1[t] == out2[t], f"Lookahead leak at t={t}"


# ---------------------------------------------------------------------------
# E-11: 1000-bar strict parity
# ---------------------------------------------------------------------------

def test_1000_bars_strict():
    n = 1000
    long_s, short_s, near_sr, atr, sl_l, sl_s, close = _make_score_arrays(n)

    py_lf, py_sf, py_sll, py_sls = _engulfing_score_python_fallback(
        long_s, short_s, near_sr, atr, sl_l, sl_s, close,
        bonus=0.5, proximity_atr=0.5, min_score=1.5
    )

    if _ENGULF_NUMBA_AVAILABLE:
        nb_lf, nb_sf, nb_sll, nb_sls = _run_engulfing_score(
            long_s, short_s, near_sr, atr, sl_l, sl_s, close,
            bonus=0.5, proximity_atr=0.5, min_score=1.5, use_numba=True
        )
        assert np.allclose(py_lf, nb_lf, rtol=1e-9, atol=1e-12, equal_nan=True)
        assert np.allclose(py_sf, nb_sf, rtol=1e-9, atol=1e-12, equal_nan=True)
        assert np.allclose(py_sll, nb_sll, rtol=1e-9, atol=1e-12, equal_nan=True)
        assert np.allclose(py_sls, nb_sls, rtol=1e-9, atol=1e-12, equal_nan=True)
    else:
        pytest.skip("Numba kurulu degil")


# ---------------------------------------------------------------------------
# E-12: Flag import
# ---------------------------------------------------------------------------

def test_numba_available_flag():
    assert isinstance(_ENGULF_NUMBA_AVAILABLE, bool)


# ---------------------------------------------------------------------------
# E-13: Python fallback
# ---------------------------------------------------------------------------

def test_python_fallback_path():
    n = 100
    long_s, short_s, near_sr, atr, sl_l, sl_s, close = _make_score_arrays(n)
    lf, sf, sll, sls = _run_engulfing_score(
        long_s, short_s, near_sr, atr, sl_l, sl_s, close,
        bonus=0.5, proximity_atr=0.5, min_score=1.5, use_numba=False
    )
    assert isinstance(lf, np.ndarray)


# ---------------------------------------------------------------------------
# E-14: Determinism
# ---------------------------------------------------------------------------

def test_determinism():
    n = 300
    long_s, short_s, near_sr, atr, sl_l, sl_s, close = _make_score_arrays(n)

    lf1, sf1, sll1, sls1 = _run_engulfing_score(
        long_s, short_s, near_sr, atr, sl_l, sl_s, close,
        bonus=0.5, proximity_atr=0.5, min_score=1.5, use_numba=False
    )
    lf2, sf2, sll2, sls2 = _run_engulfing_score(
        long_s, short_s, near_sr, atr, sl_l, sl_s, close,
        bonus=0.5, proximity_atr=0.5, min_score=1.5, use_numba=False
    )

    assert np.array_equal(lf1, lf2)
    assert np.array_equal(sf1, sf2)


# ---------------------------------------------------------------------------
# E-15: Zero ATR => signal yok
# ---------------------------------------------------------------------------

def test_zero_atr_skipped():
    n = 10
    long_s = np.full(n, 2.0)
    short_s = np.full(n, 2.0)
    near_sr = np.ones(n)
    atr = np.zeros(n)   # hepsi 0 => skip
    sl_l = np.full(n, 29_000.0)
    sl_s = np.full(n, 31_000.0)
    close = np.full(n, 30_000.0)

    lf, sf, sll, sls = _run_engulfing_score(
        long_s, short_s, near_sr, atr, sl_l, sl_s, close,
        bonus=0.5, proximity_atr=0.5, min_score=1.5, use_numba=False
    )
    assert lf.sum() == 0.0, "ATR=0 => signal olmamali"
    assert sf.sum() == 0.0


# ---------------------------------------------------------------------------
# SEC55.D yeni testler: E-16..E-21
# ---------------------------------------------------------------------------

# E-16: Numpy SR proximity parity vs Python O(n*m)
def test_numpy_sr_proximity_parity_with_python():
    """SEC55.D: _sr_proximity_numpy, Python O(n*m) ile rtol=1e-9 parity."""
    n = 730
    rng = np.random.default_rng(55)
    closes = 40_000.0 + rng.normal(0, 500, n)
    atrs = np.abs(rng.normal(300, 50, n))
    # Realistic: ~9335 records for 730 bars
    m = 9335
    sr_bar_idx = rng.integers(0, n, m).astype(np.int64)
    sr_levels_arr = closes[sr_bar_idx] + rng.normal(0, 100, m)

    py_out = _sr_proximity_python_fallback(closes, atrs, sr_bar_idx, sr_levels_arr, 0.5)
    np_out = _sr_proximity_numpy(closes, atrs, sr_bar_idx, sr_levels_arr, 0.5)

    assert np.allclose(py_out, np_out, rtol=1e-9, atol=1e-12), \
        f"Numpy sr_proximity parity fail: max_diff={np.abs(py_out - np_out).max()}"


# E-17: Numpy engulfing score parity vs Python O(n)
def test_numpy_engulfing_score_parity():
    """SEC55.D: _engulfing_score_numpy, Python O(n) ile rtol=1e-9 parity."""
    n = 730
    long_s, short_s, near_sr, atr, sl_l, sl_s, close = _make_score_arrays(n, seed=55)
    # Add some NaN struct_sl for fallback path coverage
    sl_l_copy = sl_l.copy()
    sl_l_copy[::10] = np.nan
    sl_s_copy = sl_s.copy()
    sl_s_copy[::15] = np.nan

    py_lf, py_sf, py_sll, py_sls = _engulfing_score_python_fallback(
        long_s, short_s, near_sr, atr, sl_l_copy, sl_s_copy, close,
        bonus=0.5, proximity_atr=0.5, min_score=1.5
    )
    np_lf, np_sf, np_sll, np_sls = _engulfing_score_numpy(
        long_s, short_s, near_sr, atr, sl_l_copy, sl_s_copy, close,
        bonus=0.5, proximity_atr=0.5, min_score=1.5
    )

    both_nan_l = np.isnan(py_sll) & np.isnan(np_sll)
    both_nan_s = np.isnan(py_sls) & np.isnan(np_sls)
    assert np.allclose(py_lf, np_lf, rtol=1e-9, atol=1e-12), "long_final mismatch"
    assert np.allclose(py_sf, np_sf, rtol=1e-9, atol=1e-12), "short_final mismatch"
    assert np.allclose(py_sll[~both_nan_l], np_sll[~both_nan_l], rtol=1e-9), "sl_long mismatch"
    assert np.allclose(py_sls[~both_nan_s], np_sls[~both_nan_s], rtol=1e-9), "sl_short mismatch"
    assert bool(both_nan_l.any()), "NaN fallback coverage bekleniyor (sl_long)"


# E-18: Numpy SR proximity speedup benchmark
def test_numpy_sr_proximity_speedup():
    """SEC55.D: _sr_proximity_numpy, 730-bar / 9335-record icin < 1ms olmali."""
    n = 730
    rng = np.random.default_rng(18)
    closes = 40_000.0 + rng.normal(0, 500, n)
    atrs = np.abs(rng.normal(300, 50, n))
    m = 9335
    sr_bar_idx = rng.integers(0, n, m).astype(np.int64)
    sr_levels_arr = closes[sr_bar_idx] + rng.normal(0, 100, m)

    # Warmup
    _sr_proximity_numpy(closes, atrs, sr_bar_idx, sr_levels_arr, 0.5)

    t0 = time.perf_counter()
    for _ in range(100):
        _sr_proximity_numpy(closes, atrs, sr_bar_idx, sr_levels_arr, 0.5)
    elapsed_ms = (time.perf_counter() - t0) / 100 * 1000

    assert elapsed_ms < 1.0, \
        f"_sr_proximity_numpy too slow: {elapsed_ms:.3f}ms (limit 1ms)"


# E-19: Numpy engulfing score speedup benchmark
def test_numpy_engulfing_score_speedup():
    """SEC55.D: _engulfing_score_numpy, 730-bar icin < 1ms olmali."""
    n = 730
    long_s, short_s, near_sr, atr, sl_l, sl_s, close = _make_score_arrays(n, seed=19)

    # Warmup
    _engulfing_score_numpy(long_s, short_s, near_sr, atr, sl_l, sl_s, close,
                           bonus=0.5, proximity_atr=0.5, min_score=1.5)

    t0 = time.perf_counter()
    for _ in range(1000):
        _engulfing_score_numpy(long_s, short_s, near_sr, atr, sl_l, sl_s, close,
                               bonus=0.5, proximity_atr=0.5, min_score=1.5)
    elapsed_ms = (time.perf_counter() - t0) / 1000 * 1000

    assert elapsed_ms < 1.0, \
        f"_engulfing_score_numpy too slow: {elapsed_ms:.3f}ms (limit 1ms)"


# E-20: Default dispatch numpy (no env var)
def test_dispatch_default_numpy():
    """SEC55.D: PA_ENGULF_NUMBA env var yoksa numpy path aktif olmali."""
    n = 100
    rng = np.random.default_rng(20)
    closes = 30_000.0 + rng.normal(0, 500, n)
    atrs = np.abs(rng.normal(200, 50, n))
    sr_bar_idx = rng.integers(0, n, 50).astype(np.int64)
    sr_levels_arr = closes[sr_bar_idx] + rng.normal(0, 50, 50)

    # Ensure env var absent
    env_backup = os.environ.pop("PA_ENGULF_NUMBA", None)
    try:
        out_dispatch = _run_sr_proximity(closes, atrs, sr_bar_idx, sr_levels_arr, 0.5)
        out_numpy = _sr_proximity_numpy(closes, atrs, sr_bar_idx, sr_levels_arr, 0.5)
        assert np.allclose(out_dispatch, out_numpy, rtol=1e-9), \
            "Default dispatch (no env var) must use numpy path"
    finally:
        if env_backup is not None:
            os.environ["PA_ENGULF_NUMBA"] = env_backup


# E-21: Multiple SR records same bar
def test_numpy_sr_proximity_multiple_hits():
    """SEC55.D: Ayni bar'da birden fazla SR record varsa, herhangi biri hit => near_sr=1."""
    n = 20
    closes = np.full(n, 1000.0)
    atrs = np.full(n, 50.0)
    # Bar 5: 3 record — 2 miss, 1 hit
    sr_bar_idx = np.array([5, 5, 5], dtype=np.int64)
    sr_levels_arr = np.array([2000.0, 3000.0, 1010.0])  # son biri: |1000-1010|=10 <= 0.5*50=25 => hit

    out_np = _sr_proximity_numpy(closes, atrs, sr_bar_idx, sr_levels_arr, 0.5)
    out_py = _sr_proximity_python_fallback(closes, atrs, sr_bar_idx, sr_levels_arr, 0.5)

    assert out_np[5] == 1.0, f"Bar 5 hit olmali (numpy): {out_np[5]}"
    assert out_py[5] == 1.0, f"Bar 5 hit olmali (python): {out_py[5]}"
    assert np.allclose(out_np, out_py, rtol=1e-9), "Parity fail"
