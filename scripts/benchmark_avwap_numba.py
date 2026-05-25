"""SEC55.B — AVWAP Numba benchmark.

Olcum:
  - Python fallback (use_numba=False) vs Numba JIT (use_numba=True)
  - _volume_profile_poc ve _rolling_avwap_from_swing ayri ayri
  - 1000-bar ve 5000-bar fixture
  - Speedup ratio (hedef >=10x, ideal 50-100x)

Kullanim:
  python scripts/benchmark_avwap_numba.py

Cikti:
  Tablo: kernel | bars | python_ms | numba_ms | speedup
  Parity check (rtol=1e-9) dahil
"""
from __future__ import annotations

import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

# Proje root'unu sys.path'e ekle
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT / "src"))

from price_action.strategies.anchored_vwap_reversal import (
    _AVWAP_NUMBA_AVAILABLE,
    _poc_python_fallback,
    _rolling_avwap_python_fallback,
    _volume_profile_poc,
    _rolling_avwap_from_swing,
)
from price_action.strategies.classic_pa import _fractal_swings


# ---------------------------------------------------------------------------
# Yardimcilar
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
    ts_start = datetime(2019, 1, 1, tzinfo=timezone.utc)
    ts_list = [ts_start + timedelta(minutes=15 * i) for i in range(n)]
    df = pd.DataFrame({
        "ts": ts_list,
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
        "venue": "binance",
        "symbol": "BTC/USDT",
        "timeframe": "15m",
    })
    sh, sl = _fractal_swings(df, n=2)
    df["swing_high"] = sh
    df["swing_low"] = sl
    return df


def _bench(fn, *args, warmup: int = 1, runs: int = 5, **kwargs) -> float:
    """Fonksiyonu `runs` kez calistir, medyan sure dondur (ms)."""
    for _ in range(warmup):
        fn(*args, **kwargs)
    times = []
    for _ in range(runs):
        t0 = time.perf_counter()
        fn(*args, **kwargs)
        times.append((time.perf_counter() - t0) * 1000)
    return float(np.median(times))


def _parity_check(py_series: pd.Series, nb_series: pd.Series) -> str:
    nan_mask_py = np.isnan(py_series.values)
    nan_mask_nb = np.isnan(nb_series.values)
    if not np.array_equal(nan_mask_py, nan_mask_nb):
        return "FAIL (NaN mask mismatch)"
    valid = ~nan_mask_py
    if valid.sum() == 0:
        return "SKIP (no valid bars)"
    ok = np.allclose(
        py_series.values[valid], nb_series.values[valid],
        rtol=1e-9, atol=1e-12,
    )
    return "PASS (rtol=1e-9)" if ok else "FAIL (rtol=1e-9)"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    print("=" * 72)
    print("SEC55.B — AVWAP Numba JIT Benchmark")
    print(f"Numba available: {_AVWAP_NUMBA_AVAILABLE}")
    print("=" * 72)

    LOOKBACK = 60
    BINS = 50
    RUNS = 5

    results = []

    for n_bars in (1000, 5000):
        df = _make_df(n=n_bars, seed=42)

        lows = df["low"].values.astype(np.float64)
        highs = df["high"].values.astype(np.float64)
        vols = df["volume"].values.astype(np.float64)
        closes = df["close"].values.astype(np.float64)
        swing_arr = df["swing_low"].values.astype(np.float64)
        vols_clip = np.maximum(vols, 0.0)

        # --- POC: Python baseline ---
        py_poc_ms = _bench(
            _poc_python_fallback,
            lows, highs, vols, LOOKBACK, BINS, df.index,
            warmup=1, runs=RUNS,
        )
        py_poc_series = _poc_python_fallback(lows, highs, vols, LOOKBACK, BINS, df.index)

        # --- POC: Numba JIT ---
        if _AVWAP_NUMBA_AVAILABLE:
            from price_action.strategies.anchored_vwap_reversal import _avwap_poc_jit_fn
            # Warmup (JIT compile tetikle)
            _ = _avwap_poc_jit_fn(lows, highs, vols, LOOKBACK, BINS)
            nb_poc_ms = _bench(
                _avwap_poc_jit_fn,
                lows, highs, vols, LOOKBACK, BINS,
                warmup=1, runs=RUNS,
            )
            nb_poc_arr = _avwap_poc_jit_fn(lows, highs, vols, LOOKBACK, BINS)
            nb_poc_series = pd.Series(nb_poc_arr, index=df.index, dtype=float)
            poc_speedup = py_poc_ms / nb_poc_ms if nb_poc_ms > 0 else float("inf")
            poc_parity = _parity_check(py_poc_series, nb_poc_series)
        else:
            nb_poc_ms = float("nan")
            poc_speedup = float("nan")
            poc_parity = "SKIP (no numba)"

        results.append({
            "kernel": "_volume_profile_poc",
            "bars": n_bars,
            "python_ms": round(py_poc_ms, 2),
            "numba_ms": round(nb_poc_ms, 2) if not np.isnan(nb_poc_ms) else "N/A",
            "speedup": f"{poc_speedup:.1f}x" if not np.isnan(poc_speedup) else "N/A",
            "parity": poc_parity,
        })

        # --- AVWAP: Python baseline ---
        py_avwap_ms = _bench(
            _rolling_avwap_python_fallback,
            closes, highs, lows, vols_clip, swing_arr, LOOKBACK, df.index,
            warmup=1, runs=RUNS,
        )
        py_avwap_series = _rolling_avwap_python_fallback(
            closes, highs, lows, vols_clip, swing_arr, LOOKBACK, df.index
        )

        # --- AVWAP: Numba JIT ---
        if _AVWAP_NUMBA_AVAILABLE:
            from price_action.strategies.anchored_vwap_reversal import _avwap_rolling_jit_fn
            # Warmup
            _ = _avwap_rolling_jit_fn(closes, highs, lows, vols_clip, swing_arr, LOOKBACK)
            nb_avwap_ms = _bench(
                _avwap_rolling_jit_fn,
                closes, highs, lows, vols_clip, swing_arr, LOOKBACK,
                warmup=1, runs=RUNS,
            )
            nb_avwap_arr = _avwap_rolling_jit_fn(closes, highs, lows, vols_clip, swing_arr, LOOKBACK)
            nb_avwap_series = pd.Series(nb_avwap_arr, index=df.index, dtype=float)
            avwap_speedup = py_avwap_ms / nb_avwap_ms if nb_avwap_ms > 0 else float("inf")
            avwap_parity = _parity_check(py_avwap_series, nb_avwap_series)
        else:
            nb_avwap_ms = float("nan")
            avwap_speedup = float("nan")
            avwap_parity = "SKIP (no numba)"

        results.append({
            "kernel": "_rolling_avwap_from_swing",
            "bars": n_bars,
            "python_ms": round(py_avwap_ms, 2),
            "numba_ms": round(nb_avwap_ms, 2) if not np.isnan(nb_avwap_ms) else "N/A",
            "speedup": f"{avwap_speedup:.1f}x" if not np.isnan(avwap_speedup) else "N/A",
            "parity": avwap_parity,
        })

    # Tablo ciktisi
    print()
    print(f"{'Kernel':<30} {'Bars':>6} {'Python ms':>10} {'Numba ms':>10} {'Speedup':>10} {'Parity'}")
    print("-" * 90)
    for r in results:
        print(
            f"{r['kernel']:<30} {r['bars']:>6} "
            f"{r['python_ms']:>10} {r['numba_ms']:>10} "
            f"{r['speedup']:>10} {r['parity']}"
        )

    print()
    print("Target: speedup >=10x (ideal 50-100x)")
    print("Parity: rtol=1e-9 atol=1e-12 PASS mandatory")

    # Pass/Fail ozet
    all_parity_pass = all(
        "PASS" in str(r["parity"]) or "SKIP" in str(r["parity"])
        for r in results
    )
    speedup_ok = all(
        "N/A" in str(r["speedup"]) or float(str(r["speedup"]).rstrip("x")) >= 10.0
        for r in results
        if "N/A" not in str(r["speedup"])
    )

    print()
    print(f"Parity verdict: {'PASS' if all_parity_pass else 'FAIL'}")
    print(f"Speedup target (>=10x): {'PASS' if speedup_ok else 'BELOW TARGET'}")

    if not _AVWAP_NUMBA_AVAILABLE:
        print()
        print("NOTE: numba not installed — benchmark ran Python-only paths.")
        print("Install numba to see JIT speedup: pip install numba")


if __name__ == "__main__":
    main()
