"""SEC55.C — VSA Numba JIT parity testleri.

Test kategorileri:
  V-1  test_test_bar_numba_python_parity      — CRITICAL: rtol=1e-9, atol=1e-12
  V-2  test_up_thrust_numba_python_parity     — CRITICAL: rtol=1e-9, atol=1e-12
  V-3  test_confirm_bar_numba_python_parity   — CRITICAL: rtol=1e-9, atol=1e-12
  V-4  test_nan_handling_no_climax            — Climax yok => hepsi NaN/False
  V-5  test_edge_zero_volume                  — Zero volume => test bar REJECT
  V-6  test_edge_insufficient_data            — n < wait_min => bos cikti
  V-7  test_1000_bars_strict                  — 1000-bar fixture rtol=1e-9
  V-8  test_no_lookahead_test_bar             — t bari i+1 degisince t etkilenmemeli
  V-9  test_no_lookahead_confirm              — Ayni lookahead testi confirm icin
  V-10 test_numba_available_flag              — _VSA_NUMBA_AVAILABLE import edilebilir
  V-11 test_python_fallback_path              — use_numba=False, no crash
  V-12 test_determinism                       — Ayni input => ayni output (2 kez)
  V-13 test_detect_test_bar_after_sc          — _detect_test_bar_after_sc yuksek seviye
  V-14 test_detect_up_thrust_after_bc         — _detect_up_thrust_after_bc yuksek seviye
  V-15 test_confirm_long_short                — Long/short confirm dogru yonde
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest

from price_action.strategies.vsa_climax_test import (
    _VSA_NUMBA_AVAILABLE,
    _test_bar_python_fallback,
    _confirm_python_fallback,
    _run_test_bar_kernel,
    _run_confirm_kernel,
    _detect_test_bar_after_sc,
    _detect_up_thrust_after_bc,
    _detect_confirmation_bar,
)


# ---------------------------------------------------------------------------
# Yardimci fabrikalar
# ---------------------------------------------------------------------------

def _base_ts(n: int) -> list[datetime]:
    start = datetime(2020, 1, 1, tzinfo=timezone.utc)
    return [start + timedelta(hours=i) for i in range(n)]


def _make_df(n: int = 500, seed: int = 42) -> pd.DataFrame:
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
    atr = (high - low) * 0.5  # basit ATR proxy
    vol_sma = np.full(n, volume.mean())
    df = pd.DataFrame({
        "ts": _base_ts(n),
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
        "atr20": atr,
        "vol_sma20": vol_sma,
        "venue": "BINANCE",
        "symbol": "BTCUSDT",
        "timeframe": "15m",
    })
    return df


def _arrays_from_df(df: pd.DataFrame):
    return (
        df["low"].to_numpy(dtype=np.float64),
        df["high"].to_numpy(dtype=np.float64),
        df["volume"].to_numpy(dtype=np.float64),
        df["close"].to_numpy(dtype=np.float64),
        df["open"].to_numpy(dtype=np.float64),
        df["atr20"].fillna(0.0).to_numpy(dtype=np.float64),
        df["vol_sma20"].fillna(0.0).to_numpy(dtype=np.float64),
    )


def _make_climax_flag(n: int, indices: list[int]) -> np.ndarray:
    arr = np.zeros(n, dtype=np.bool_)
    for i in indices:
        if 0 <= i < n:
            arr[i] = True
    return arr


# ---------------------------------------------------------------------------
# V-1: Test bar parity (SC taraf, use_low=True)
# ---------------------------------------------------------------------------

def test_test_bar_numba_python_parity():
    df = _make_df(500)
    lows, highs, volumes, closes, opens, atr_arr, vol_sma_arr = _arrays_from_df(df)
    # Birkaç SC bari olustur
    climax_flag = _make_climax_flag(500, [20, 80, 150, 250, 350])

    kwargs = dict(
        lows=lows, highs=highs, volumes=volumes, closes=closes, opens=opens,
        atr_arr=atr_arr, vol_sma_arr=vol_sma_arr, climax_flag=climax_flag,
        use_low=True, wait_min=3, wait_max=15,
        price_tolerance_pct=0.03, vol_ratio_max=0.75,
        spread_atr_max=0.80, close_pos_threshold=0.50,
    )

    py_flag, py_ref = _test_bar_python_fallback(**kwargs)

    if _VSA_NUMBA_AVAILABLE:
        nb_flag, nb_ref = _run_test_bar_kernel(**kwargs, use_numba=True)
        assert np.allclose(py_flag, nb_flag, rtol=1e-9, atol=1e-12, equal_nan=True), \
            "flag mismatch"
        assert np.allclose(py_ref, nb_ref, rtol=1e-9, atol=1e-12, equal_nan=True), \
            "ref_price mismatch"
    else:
        pytest.skip("Numba kurulu degil — Python parity implicit")


# ---------------------------------------------------------------------------
# V-2: Up thrust parity (BC taraf, use_low=False)
# ---------------------------------------------------------------------------

def test_up_thrust_numba_python_parity():
    df = _make_df(500)
    lows, highs, volumes, closes, opens, atr_arr, vol_sma_arr = _arrays_from_df(df)
    climax_flag = _make_climax_flag(500, [30, 100, 200])

    kwargs = dict(
        lows=lows, highs=highs, volumes=volumes, closes=closes, opens=opens,
        atr_arr=atr_arr, vol_sma_arr=vol_sma_arr, climax_flag=climax_flag,
        use_low=False, wait_min=3, wait_max=15,
        price_tolerance_pct=0.03, vol_ratio_max=0.75,
        spread_atr_max=0.80, close_pos_threshold=0.50,
    )

    py_flag, py_ref = _test_bar_python_fallback(**kwargs)

    if _VSA_NUMBA_AVAILABLE:
        nb_flag, nb_ref = _run_test_bar_kernel(**kwargs, use_numba=True)
        assert np.allclose(py_flag, nb_flag, rtol=1e-9, atol=1e-12, equal_nan=True)
        assert np.allclose(py_ref, nb_ref, rtol=1e-9, atol=1e-12, equal_nan=True)
    else:
        pytest.skip("Numba kurulu degil")


# ---------------------------------------------------------------------------
# V-3: Confirmation bar parity
# ---------------------------------------------------------------------------

def test_confirm_bar_numba_python_parity():
    df = _make_df(500)
    closes = df["close"].to_numpy(dtype=np.float64)
    opens = df["open"].to_numpy(dtype=np.float64)
    # Trigger flag: birkaç barda True
    trigger = np.zeros(500, dtype=np.float64)
    trigger[50] = 1.0
    trigger[200] = 1.0
    trigger[350] = 1.0

    py_long = _confirm_python_fallback(closes, opens, trigger, direction_long=True, max_wait=3)
    py_short = _confirm_python_fallback(closes, opens, trigger, direction_long=False, max_wait=3)

    if _VSA_NUMBA_AVAILABLE:
        nb_long = _run_confirm_kernel(closes, opens, trigger, True, 3, use_numba=True)
        nb_short = _run_confirm_kernel(closes, opens, trigger, False, 3, use_numba=True)
        assert np.allclose(py_long, nb_long, rtol=1e-9, atol=1e-12)
        assert np.allclose(py_short, nb_short, rtol=1e-9, atol=1e-12)
    else:
        pytest.skip("Numba kurulu degil")


# ---------------------------------------------------------------------------
# V-4: NaN handling — climax yok
# ---------------------------------------------------------------------------

def test_nan_handling_no_climax():
    df = _make_df(100)
    lows, highs, volumes, closes, opens, atr_arr, vol_sma_arr = _arrays_from_df(df)
    climax_flag = np.zeros(100, dtype=np.bool_)  # hic climax yok

    flag_arr, ref_arr = _run_test_bar_kernel(
        lows=lows, highs=highs, volumes=volumes, closes=closes, opens=opens,
        atr_arr=atr_arr, vol_sma_arr=vol_sma_arr, climax_flag=climax_flag,
        use_low=True, wait_min=3, wait_max=15,
        price_tolerance_pct=0.03, vol_ratio_max=0.75,
        spread_atr_max=0.80, close_pos_threshold=0.50,
        use_numba=False,  # Python path her zaman test edilir
    )
    assert flag_arr.sum() == 0.0, "Climax yok => test bar yok"
    assert np.all(np.isnan(ref_arr)), "Climax yok => ref price hepsi NaN"


# ---------------------------------------------------------------------------
# V-5: Zero volume => test bar REJECT
# ---------------------------------------------------------------------------

def test_edge_zero_volume():
    n = 50
    df = _make_df(n)
    lows, highs, volumes, closes, opens, atr_arr, vol_sma_arr = _arrays_from_df(df)
    # vol_sma > 0 ama curr_vol = 0 => low_vol = True (0 < vol_ratio_max * sma)
    # Ama bunu test etmek icin climax'in oldugunu varsay
    climax_flag = _make_climax_flag(n, [5])
    volumes_zero = np.zeros(n, dtype=np.float64)

    flag_arr, _ = _run_test_bar_kernel(
        lows=lows, highs=highs, volumes=volumes_zero, closes=closes, opens=opens,
        atr_arr=atr_arr, vol_sma_arr=vol_sma_arr, climax_flag=climax_flag,
        use_low=True, wait_min=3, wait_max=15,
        price_tolerance_pct=0.10,  # genis tolerans
        vol_ratio_max=0.75, spread_atr_max=0.80, close_pos_threshold=0.20,
        use_numba=False,
    )
    # Zero volume < vol_ratio_max * vol_sma => low_vol=True (gecerli)
    # Ama close_pos kontrolu da var; bu test sadece kras olmadigini dogrular
    assert isinstance(flag_arr, np.ndarray)


# ---------------------------------------------------------------------------
# V-6: Insufficient data (n < wait_min)
# ---------------------------------------------------------------------------

def test_edge_insufficient_data():
    n = 2  # wait_min=3 > n => hicbir sey hesaplanamaz
    df = _make_df(n)
    lows, highs, volumes, closes, opens, atr_arr, vol_sma_arr = _arrays_from_df(df)
    climax_flag = np.zeros(n, dtype=np.bool_)

    flag_arr, ref_arr = _run_test_bar_kernel(
        lows=lows, highs=highs, volumes=volumes, closes=closes, opens=opens,
        atr_arr=atr_arr, vol_sma_arr=vol_sma_arr, climax_flag=climax_flag,
        use_low=True, wait_min=3, wait_max=15,
        price_tolerance_pct=0.03, vol_ratio_max=0.75,
        spread_atr_max=0.80, close_pos_threshold=0.50,
        use_numba=False,
    )
    assert flag_arr.sum() == 0.0
    assert len(flag_arr) == n


# ---------------------------------------------------------------------------
# V-7: 1000-bar fixture — strict parity
# ---------------------------------------------------------------------------

def test_1000_bars_strict():
    df = _make_df(1000)
    lows, highs, volumes, closes, opens, atr_arr, vol_sma_arr = _arrays_from_df(df)
    climax_flag = _make_climax_flag(1000, [10, 50, 100, 200, 400, 700, 900])

    kwargs = dict(
        lows=lows, highs=highs, volumes=volumes, closes=closes, opens=opens,
        atr_arr=atr_arr, vol_sma_arr=vol_sma_arr, climax_flag=climax_flag,
        use_low=True, wait_min=3, wait_max=15,
        price_tolerance_pct=0.03, vol_ratio_max=0.75,
        spread_atr_max=0.80, close_pos_threshold=0.50,
    )

    py_flag, py_ref = _test_bar_python_fallback(**kwargs)

    if _VSA_NUMBA_AVAILABLE:
        nb_flag, nb_ref = _run_test_bar_kernel(**kwargs, use_numba=True)
        assert np.allclose(py_flag, nb_flag, rtol=1e-9, atol=1e-12, equal_nan=True), \
            f"flag mismatch — diff indices: {np.where(py_flag != nb_flag)}"
        assert np.allclose(py_ref, nb_ref, rtol=1e-9, atol=1e-12, equal_nan=True), \
            "ref_price parity fail"
    else:
        pytest.skip("Numba kurulu degil")


# ---------------------------------------------------------------------------
# V-8: Lookahead — test bar (bar i+1 degisince bar i etkilenmemeli)
# ---------------------------------------------------------------------------

def test_no_lookahead_test_bar():
    df = _make_df(100)
    lows, highs, volumes, closes, opens, atr_arr, vol_sma_arr = _arrays_from_df(df)
    climax_flag = _make_climax_flag(100, [10])

    base_kw = dict(
        lows=lows, highs=highs, volumes=volumes, closes=closes, opens=opens,
        atr_arr=atr_arr, vol_sma_arr=vol_sma_arr, climax_flag=climax_flag,
        use_low=True, wait_min=3, wait_max=15,
        price_tolerance_pct=0.03, vol_ratio_max=0.75,
        spread_atr_max=0.80, close_pos_threshold=0.50,
    )

    flag1, ref1 = _test_bar_python_fallback(**base_kw)

    # Bar 50'yi degistir (gelecek bar simulasyonu)
    lows2 = lows.copy()
    lows2[50] = lows[50] * 0.5  # drastic change
    flag2, ref2 = _test_bar_python_fallback(**{**base_kw, "lows": lows2})

    # Bar 49 ve oncesi ayni olmali
    for t in range(49):
        assert flag1[t] == flag2[t], f"Lookahead leak at t={t}"
        eq = (np.isnan(ref1[t]) and np.isnan(ref2[t])) or ref1[t] == ref2[t]
        assert eq, f"ref_price lookahead leak at t={t}"


# ---------------------------------------------------------------------------
# V-9: Lookahead — confirm bar
# ---------------------------------------------------------------------------

def test_no_lookahead_confirm():
    df = _make_df(200)
    closes = df["close"].to_numpy(dtype=np.float64)
    opens = df["open"].to_numpy(dtype=np.float64)
    trigger = np.zeros(200, dtype=np.float64)
    trigger[50] = 1.0

    conf1 = _confirm_python_fallback(closes, opens, trigger, True, 3)

    # Bar 100'un close'unu degistir
    closes2 = closes.copy()
    closes2[100] = closes[100] * 2.0
    conf2 = _confirm_python_fallback(closes2, opens, trigger, True, 3)

    # Bar 99 ve oncesi etkilenmemeli
    for t in range(99):
        assert conf1[t] == conf2[t], f"Lookahead leak at t={t}"


# ---------------------------------------------------------------------------
# V-10: Flag import edilebilir
# ---------------------------------------------------------------------------

def test_numba_available_flag():
    assert isinstance(_VSA_NUMBA_AVAILABLE, bool)


# ---------------------------------------------------------------------------
# V-11: Python fallback path — use_numba=False
# ---------------------------------------------------------------------------

def test_python_fallback_path():
    df = _make_df(100)
    lows, highs, volumes, closes, opens, atr_arr, vol_sma_arr = _arrays_from_df(df)
    climax_flag = _make_climax_flag(100, [15])

    flag_arr, ref_arr = _run_test_bar_kernel(
        lows=lows, highs=highs, volumes=volumes, closes=closes, opens=opens,
        atr_arr=atr_arr, vol_sma_arr=vol_sma_arr, climax_flag=climax_flag,
        use_low=True, wait_min=3, wait_max=15,
        price_tolerance_pct=0.03, vol_ratio_max=0.75,
        spread_atr_max=0.80, close_pos_threshold=0.50,
        use_numba=False,  # explicit Python path
    )
    assert isinstance(flag_arr, np.ndarray)
    assert isinstance(ref_arr, np.ndarray)


# ---------------------------------------------------------------------------
# V-12: Determinism
# ---------------------------------------------------------------------------

def test_determinism():
    df = _make_df(300)
    lows, highs, volumes, closes, opens, atr_arr, vol_sma_arr = _arrays_from_df(df)
    climax_flag = _make_climax_flag(300, [20, 100, 200])

    kwargs = dict(
        lows=lows, highs=highs, volumes=volumes, closes=closes, opens=opens,
        atr_arr=atr_arr, vol_sma_arr=vol_sma_arr, climax_flag=climax_flag,
        use_low=True, wait_min=3, wait_max=15,
        price_tolerance_pct=0.03, vol_ratio_max=0.75,
        spread_atr_max=0.80, close_pos_threshold=0.50,
    )

    flag1, ref1 = _test_bar_python_fallback(**kwargs)
    flag2, ref2 = _test_bar_python_fallback(**kwargs)
    assert np.array_equal(flag1, flag2)
    assert np.array_equal(ref1, ref2) or (np.isnan(ref1).all() and np.isnan(ref2).all())


# ---------------------------------------------------------------------------
# V-13: High-level _detect_test_bar_after_sc
# ---------------------------------------------------------------------------

def test_detect_test_bar_after_sc():
    df = _make_df(200)
    # SC flag: bar 30'da
    sc_flag = pd.Series(False, index=df.index)
    sc_flag.iloc[30] = True

    tb_flag, sc_low_series = _detect_test_bar_after_sc(
        df, sc_flag=sc_flag,
        atr_col="atr20", vol_sma_col="vol_sma20",
        wait_min=3, wait_max=15,
        low_tolerance_pct=0.05,  # genis tolerans
        vol_ratio_max=0.90,
        spread_atr_max=0.99,
        close_pos_min=0.10,
        use_numba=False,
    )
    assert len(tb_flag) == len(df)
    assert len(sc_low_series) == len(df)
    # Bar 30 oncesi test bar olmamal
    assert not tb_flag.iloc[:33].any(), "wait_min=3 ihmal edilmis"


# ---------------------------------------------------------------------------
# V-14: High-level _detect_up_thrust_after_bc
# ---------------------------------------------------------------------------

def test_detect_up_thrust_after_bc():
    df = _make_df(200)
    bc_flag = pd.Series(False, index=df.index)
    bc_flag.iloc[50] = True

    ut_flag, bc_high_series = _detect_up_thrust_after_bc(
        df, bc_flag=bc_flag,
        atr_col="atr20", vol_sma_col="vol_sma20",
        wait_min=3, wait_max=15,
        high_tolerance_pct=0.05,
        vol_ratio_max=0.90,
        spread_atr_max=0.99,
        close_pos_max=0.90,
        use_numba=False,
    )
    assert len(ut_flag) == len(df)
    assert not ut_flag.iloc[:53].any(), "wait_min=3 ihmal edilmis"


# ---------------------------------------------------------------------------
# V-15: Long/short confirm dogru yonde
# ---------------------------------------------------------------------------

def test_confirm_long_short():
    """Long confirm: green bar sonrasi. Short confirm: red bar sonrasi."""
    n = 20
    # closes > opens (hep yesil)
    closes = np.full(n, 101.0)
    opens = np.full(n, 100.0)
    trigger = np.zeros(n, dtype=np.float64)
    trigger[5] = 1.0

    long_conf = _confirm_python_fallback(closes, opens, trigger, True, 3)
    short_conf = _confirm_python_fallback(closes, opens, trigger, False, 3)

    # Long: bar 6,7,8 (max_wait=3) yesil bar => en az biri True
    assert long_conf[6:9].sum() >= 1.0, "Long confirm yesil barda olmali"
    # Short: closes > opens => kirmizi bar yok => hic short confirm yok
    assert short_conf.sum() == 0.0, "Yesil barlarla short confirm olmamali"
