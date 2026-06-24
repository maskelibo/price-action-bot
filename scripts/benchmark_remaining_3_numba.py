"""SEC55.C — VSA + Brooks + Engulfing Numba benchmark.

Olcum:
  - Python fallback vs Numba JIT (varsa) her strateji icin
  - 1000-bar ve 5000-bar synthetic BTC-like 15m data
  - Per-kernel: Python ms, Numba ms, speedup ratio
  - 10-sym combined scan tahmini

Kullanim:
  python scripts/benchmark_remaining_3_numba.py

Cikti:
  Tablo: kernel | bars | python_ms | numba_ms | speedup
  Parity check (rtol=1e-9) dahil
  Scan latency projection (old: 415s, new: ?)
"""
from __future__ import annotations

import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT / "src"))

from price_action.strategies.vsa_climax_test import (
    _VSA_NUMBA_AVAILABLE,
    _test_bar_python_fallback,
    _confirm_python_fallback,
    _run_test_bar_kernel,
    _run_confirm_kernel,
)
from price_action.strategies.brooks_failed_breakout import (
    _BROOKS_NUMBA_AVAILABLE,
    _failed_bo_python_fallback,
    _run_failed_bo_kernel,
    _rolling_n_bar_high,
    _rolling_n_bar_low,
)
from price_action.strategies.engulfing_continuation import (
    _ENGULF_NUMBA_AVAILABLE,
    _sr_proximity_python_fallback,
    _engulfing_score_python_fallback,
    _run_sr_proximity,
    _run_engulfing_score,
)


# ---------------------------------------------------------------------------
# Yardimci: Synthetic BTC 15m OHLCV
# ---------------------------------------------------------------------------

def _make_df(n: int, seed: int = 42) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    rets = rng.normal(0.0003, 0.015, n)
    close = 30_000.0 * np.exp(np.cumsum(rets))
    open_ = np.r_[close[0], close[:-1]]
    high = np.maximum(open_, close) * (1 + np.abs(rng.normal(0, 0.005, n)))
    low = np.minimum(open_, close) * (1 - np.abs(rng.normal(0, 0.005, n)))
    high = np.maximum.reduce([high, open_, close])
    low = np.minimum.reduce([low, open_, close])
    volume = rng.uniform(1e9, 5e9, n)
    atr = (high - low) * 0.5
    vol_sma = np.full(n, volume.mean())
    ts_start = datetime(2019, 1, 1, tzinfo=timezone.utc)
    ts_list = [ts_start + timedelta(minutes=15 * i) for i in range(n)]
    return pd.DataFrame({
        "ts": ts_list,
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


def _timeit(fn, n_runs: int = 5):
    """Ortalama sure (ms)."""
    times = []
    for _ in range(n_runs):
        t0 = time.perf_counter()
        fn()
        times.append((time.perf_counter() - t0) * 1000)
    return float(np.median(times))


def _fmt_speedup(py_ms: float, nb_ms: float) -> str:
    if nb_ms <= 0:
        return "N/A"
    return f"{py_ms / nb_ms:.1f}x"


def _check_parity(py_out, nb_out, name: str) -> bool:
    if isinstance(py_out, tuple):
        ok = all(
            np.allclose(p, n, rtol=1e-9, atol=1e-12, equal_nan=True)
            for p, n in zip(py_out, nb_out)
        )
    else:
        ok = np.allclose(py_out, nb_out, rtol=1e-9, atol=1e-12, equal_nan=True)
    status = "PASS" if ok else "FAIL"
    print(f"  Parity [{name}]: {status}")
    return ok


# ---------------------------------------------------------------------------
# Main benchmark
# ---------------------------------------------------------------------------

def run_benchmarks():
    print("=" * 72)
    print("SEC55.C — Remaining 3 Strategy Numba Benchmark")
    print(f"VSA Numba: {_VSA_NUMBA_AVAILABLE} | Brooks: {_BROOKS_NUMBA_AVAILABLE} | Engulf: {_ENGULF_NUMBA_AVAILABLE}")
    print("=" * 72)

    results = []

    for n_bars in [1000, 5000]:
        print(f"\n--- {n_bars} bars ---")
        df = _make_df(n_bars)

        lows = df["low"].to_numpy(dtype=np.float64)
        highs = df["high"].to_numpy(dtype=np.float64)
        closes = df["close"].to_numpy(dtype=np.float64)
        opens = df["open"].to_numpy(dtype=np.float64)
        vols = df["volume"].to_numpy(dtype=np.float64)
        atr_arr = df["atr20"].to_numpy(dtype=np.float64)
        vol_sma_arr = df["vol_sma20"].to_numpy(dtype=np.float64)

        rng = np.random.default_rng(0)
        climax_flag = np.zeros(n_bars, dtype=np.bool_)
        climax_flag[rng.integers(0, n_bars, n_bars // 50)] = True

        # ----------------------------------------------------------------
        # 1. VSA — Test Bar kernel
        # ----------------------------------------------------------------
        print("\n[VSA] _test_bar_kernel (SC test bar + confirmation)")
        vsa_kw = dict(
            lows=lows, highs=highs, volumes=vols, closes=closes, opens=opens,
            atr_arr=atr_arr, vol_sma_arr=vol_sma_arr, climax_flag=climax_flag,
            use_low=True, wait_min=3, wait_max=15,
            price_tolerance_pct=0.03, vol_ratio_max=0.75,
            spread_atr_max=0.80, close_pos_threshold=0.50,
        )
        py_ms_vsa = _timeit(lambda: _test_bar_python_fallback(**vsa_kw))
        print(f"  Python: {py_ms_vsa:.1f} ms")

        nb_ms_vsa = 0.0
        py_out_vsa = _test_bar_python_fallback(**vsa_kw)
        if _VSA_NUMBA_AVAILABLE:
            # warmup
            _run_test_bar_kernel(**vsa_kw, use_numba=True)
            nb_ms_vsa = _timeit(lambda: _run_test_bar_kernel(**vsa_kw, use_numba=True))
            print(f"  Numba:  {nb_ms_vsa:.1f} ms  speedup={_fmt_speedup(py_ms_vsa, nb_ms_vsa)}")
            nb_out_vsa = _run_test_bar_kernel(**vsa_kw, use_numba=True)
            _check_parity(py_out_vsa, nb_out_vsa, "VSA test_bar")
        else:
            print("  Numba: NOT AVAILABLE (fallback only)")

        # Confirm kernel (ek)
        trigger_arr = py_out_vsa[0]  # flag_arr
        py_ms_conf = _timeit(lambda: _confirm_python_fallback(closes, opens, trigger_arr, True, 3))
        print(f"  [Confirm] Python: {py_ms_conf:.1f} ms")
        if _VSA_NUMBA_AVAILABLE:
            _run_confirm_kernel(closes, opens, trigger_arr, True, 3, use_numba=True)
            nb_ms_conf = _timeit(lambda: _run_confirm_kernel(closes, opens, trigger_arr, True, 3, use_numba=True))
            print(f"  [Confirm] Numba:  {nb_ms_conf:.1f} ms  speedup={_fmt_speedup(py_ms_conf, nb_ms_conf)}")

        results.append(("VSA test_bar", n_bars, py_ms_vsa, nb_ms_vsa if _VSA_NUMBA_AVAILABLE else None))

        # ----------------------------------------------------------------
        # 2. Brooks — Failed BO kernel
        # ----------------------------------------------------------------
        print("\n[Brooks] _failed_bo_kernel (BO detection + failure scan)")
        nb_high_ser = _rolling_n_bar_high(df, 20)
        nb_low_ser = _rolling_n_bar_low(df, 20)
        nb_high = nb_high_ser.to_numpy(dtype=np.float64)
        nb_low = nb_low_ser.to_numpy(dtype=np.float64)

        py_ms_brooks = _timeit(lambda: _failed_bo_python_fallback(closes, highs, lows, nb_high, nb_low, 3))
        print(f"  Python: {py_ms_brooks:.1f} ms")

        nb_ms_brooks = 0.0
        py_out_brooks = _failed_bo_python_fallback(closes, highs, lows, nb_high, nb_low, 3)
        if _BROOKS_NUMBA_AVAILABLE:
            _run_failed_bo_kernel(closes, highs, lows, nb_high, nb_low, 3, use_numba=True)
            nb_ms_brooks = _timeit(lambda: _run_failed_bo_kernel(closes, highs, lows, nb_high, nb_low, 3, use_numba=True))
            print(f"  Numba:  {nb_ms_brooks:.1f} ms  speedup={_fmt_speedup(py_ms_brooks, nb_ms_brooks)}")
            nb_out_brooks = _run_failed_bo_kernel(closes, highs, lows, nb_high, nb_low, 3, use_numba=True)
            _check_parity(py_out_brooks, nb_out_brooks, "Brooks failed_bo")
        else:
            print("  Numba: NOT AVAILABLE (fallback only)")

        results.append(("Brooks failed_bo", n_bars, py_ms_brooks, nb_ms_brooks if _BROOKS_NUMBA_AVAILABLE else None))

        # ----------------------------------------------------------------
        # 3. Engulfing — SR proximity + score kernel
        # ----------------------------------------------------------------
        print("\n[Engulfing] _sr_proximity + _engulfing_score kernels")
        # SR records simulation
        sr_idx = rng.integers(0, n_bars, n_bars // 5).astype(np.int64)
        sr_lvls = closes[sr_idx] + rng.normal(0, 50, len(sr_idx))
        long_score = rng.choice([0.0, 1.5, 2.0], n_bars).astype(np.float64)
        short_score = rng.choice([0.0, 1.5, 2.0], n_bars).astype(np.float64)
        near_sr_dummy = np.zeros(n_bars, dtype=np.float64)
        sl_long = closes - 2.0 * atr_arr
        sl_short = closes + 2.0 * atr_arr

        # SR proximity
        py_ms_sr = _timeit(lambda: _sr_proximity_python_fallback(closes, atr_arr, sr_idx, sr_lvls, 0.5))
        print(f"  [SR prox] Python: {py_ms_sr:.1f} ms")
        py_sr_out = _sr_proximity_python_fallback(closes, atr_arr, sr_idx, sr_lvls, 0.5)
        if _ENGULF_NUMBA_AVAILABLE:
            _run_sr_proximity(closes, atr_arr, sr_idx, sr_lvls, 0.5, use_numba=True)
            nb_ms_sr = _timeit(lambda: _run_sr_proximity(closes, atr_arr, sr_idx, sr_lvls, 0.5, use_numba=True))
            nb_sr_out = _run_sr_proximity(closes, atr_arr, sr_idx, sr_lvls, 0.5, use_numba=True)
            print(f"  [SR prox] Numba:  {nb_ms_sr:.1f} ms  speedup={_fmt_speedup(py_ms_sr, nb_ms_sr)}")
            _check_parity(py_sr_out, nb_sr_out, "Engulfing SR proximity")
        else:
            nb_ms_sr = 0.0
            print("  Numba: NOT AVAILABLE")

        # Score kernel
        py_ms_score = _timeit(lambda: _engulfing_score_python_fallback(
            long_score, short_score, near_sr_dummy, atr_arr, sl_long, sl_short, closes,
            0.5, 0.5, 1.5
        ))
        print(f"  [Score] Python: {py_ms_score:.1f} ms")
        py_score_out = _engulfing_score_python_fallback(
            long_score, short_score, near_sr_dummy, atr_arr, sl_long, sl_short, closes, 0.5, 0.5, 1.5
        )
        nb_ms_score = 0.0
        if _ENGULF_NUMBA_AVAILABLE:
            _run_engulfing_score(long_score, short_score, near_sr_dummy, atr_arr, sl_long, sl_short, closes, 0.5, 0.5, 1.5, use_numba=True)
            nb_ms_score = _timeit(lambda: _run_engulfing_score(
                long_score, short_score, near_sr_dummy, atr_arr, sl_long, sl_short, closes, 0.5, 0.5, 1.5, use_numba=True
            ))
            nb_score_out = _run_engulfing_score(
                long_score, short_score, near_sr_dummy, atr_arr, sl_long, sl_short, closes, 0.5, 0.5, 1.5, use_numba=True
            )
            print(f"  [Score] Numba:  {nb_ms_score:.1f} ms  speedup={_fmt_speedup(py_ms_score, nb_ms_score)}")
            _check_parity(py_score_out, nb_score_out, "Engulfing score")
        else:
            print("  Numba: NOT AVAILABLE")

        engulf_py_total = py_ms_sr + py_ms_score
        engulf_nb_total = (nb_ms_sr + nb_ms_score) if _ENGULF_NUMBA_AVAILABLE else 0.0
        results.append(("Engulfing (sr+score)", n_bars, engulf_py_total, engulf_nb_total if _ENGULF_NUMBA_AVAILABLE else None))

    # ----------------------------------------------------------------
    # Summary table
    # ----------------------------------------------------------------
    print("\n" + "=" * 72)
    print("BENCHMARK SUMMARY (median of 5 runs)")
    print(f"{'Kernel':<30} {'Bars':>6} {'Python ms':>10} {'Numba ms':>10} {'Speedup':>10}")
    print("-" * 72)
    for kernel, bars, py_ms, nb_ms in results:
        if nb_ms is not None and nb_ms > 0:
            su = f"{py_ms / nb_ms:.1f}x"
            nb_str = f"{nb_ms:.1f}"
        else:
            su = "N/A (no numba)"
            nb_str = "N/A"
        print(f"{kernel:<30} {bars:>6} {py_ms:>10.1f} {nb_str:>10} {su:>10}")

    # ----------------------------------------------------------------
    # Scan latency projection (10 sym)
    # ----------------------------------------------------------------
    print("\n" + "=" * 72)
    print("SCAN LATENCY PROJECTION (10 symbols, 5000-bar data)")
    print("=" * 72)

    # Eski sure referanslari (production olcumu):
    old_vsa_s = 93.0
    old_brooks_s = 66.0
    old_engulf_s = 180.0
    old_avwap_s = 15.0   # SEC55.B sonrasi
    old_overhead_s = 61.0
    old_total_s = old_vsa_s + old_brooks_s + old_engulf_s + old_avwap_s + old_overhead_s

    # 5000-bar sutun (10 sym icin 10x carpim, saniyeye cevirme)
    def find_result(name: str, bars: int):
        for k, b, py_ms, nb_ms in results:
            if k == name and b == bars:
                return py_ms, nb_ms
        return None, None

    vsa_py, vsa_nb = find_result("VSA test_bar", 5000)
    br_py, br_nb = find_result("Brooks failed_bo", 5000)
    eng_py, eng_nb = find_result("Engulfing (sr+score)", 5000)

    def scale(ms_val, n_sym=10):
        if ms_val is None:
            return None
        return ms_val * n_sym / 1000.0  # seconds

    print(f"\nOLD scan (Python loops, production measurement):")
    print(f"  VSA:      {old_vsa_s:.0f}s")
    print(f"  Brooks:   {old_brooks_s:.0f}s")
    print(f"  Engulfing:{old_engulf_s:.0f}s")
    print(f"  AVWAP:    {old_avwap_s:.0f}s (SEC55.B)")
    print(f"  Overhead: {old_overhead_s:.0f}s")
    print(f"  TOTAL:    {old_total_s:.0f}s")

    print(f"\nNEW scan (Numba JIT, 10 sym x 5000-bar estimate):")

    def choose(nb, py):
        return nb if nb is not None else py

    vsa_new = scale(choose(vsa_nb, vsa_py))
    br_new = scale(choose(br_nb, br_py))
    eng_new = scale(choose(eng_nb, eng_py))
    avwap_new = 3.0  # SEC55.B olcumu (15s -> 3s)

    if vsa_new and br_new and eng_new:
        new_total_s = vsa_new + br_new + eng_new + avwap_new + old_overhead_s
        print(f"  VSA:      {vsa_new:.1f}s  (was {old_vsa_s:.0f}s, {old_vsa_s/vsa_new:.0f}x faster)")
        print(f"  Brooks:   {br_new:.1f}s  (was {old_brooks_s:.0f}s, {old_brooks_s/br_new:.0f}x faster)")
        print(f"  Engulfing:{eng_new:.1f}s  (was {old_engulf_s:.0f}s, {old_engulf_s/eng_new:.0f}x faster)")
        print(f"  AVWAP:    {avwap_new:.1f}s  (SEC55.B)")
        print(f"  Overhead: {old_overhead_s:.0f}s  (unchanged)")
        print(f"  TOTAL:    {new_total_s:.1f}s  (vs {old_total_s:.0f}s old)")
        target_ok = new_total_s < 50.0
        print(f"\n  TARGET <50s: {'PASS' if target_ok else 'MISS'} ({new_total_s:.1f}s)")
    else:
        print("  [Numba NOT available — Python path only, no speedup]")
        print(f"  Estimated total (Python): {old_total_s:.0f}s (unchanged)")

    print("=" * 72)


if __name__ == "__main__":
    run_benchmarks()
