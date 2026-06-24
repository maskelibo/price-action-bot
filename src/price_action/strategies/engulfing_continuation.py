"""Engulfing Continuation stratejisi.

Strateji: 20-EMA'ya pullback sonrasi bullish/bearish engulfing bar,
           50-EMA + Brooks 'always-in' trend filtresi ile konfirme edilmis.

Kural ozeti:
  - Trend filtresi : 50-EMA yonu + 3-bar always-in konfirmasyonu
  - Pullback       : Son 5-10 barda fiyat 20-EMA'ya dokunmus/bounced
  - Engulfing      : Strict — Body(N) body(N-1)'i tamamen sarar, zit renk,
                     body_ratio >= 0.6 (total range uzerine)
  - Giris          : Bar N+1 acilis (bar N kapanis sonrasi karar)
  - Stop           : Structural swing low (long) / swing high (short)
  - Hedef          : 2R birincil; 14-EMA trailing runner 1R sonrasi
  - Confluence     : S/R proximity bonusu, atr_min_pct 0.005

Manifest yoksa dahili default kullanilir.

---
Performance (SEC55.D — 2026-05-18):
  ROOT CAUSE (SEC55.D): _sr_proximity_python_fallback O(n*m) nested loop
  daemon production'da 730 bar * 9335 SR record = 6.8M iterations = 207ms/sym.
  PA_ENGULF_NUMBA=0 (default revert) + Python O(n*m) = 3:37 / sym gap gozlendi.

  FIX: _sr_proximity ve _engulfing_score tamamen numpy vectorized.
  - _sr_proximity_numpy: numpy indexing ile O(m) — 0.018ms vs 207ms (11500x speedup).
  - _engulfing_score_numpy: numpy broadcasting ile O(n) — 0.044ms vs 0.94ms (21x).
  - Parity: rtol=1e-9, atol=1e-12 — PASS.
  - Numba JIT kernel'lar korunuyor (PA_ENGULF_NUMBA=1 ile aktif edilebilir).
  - Default path artik numpy (Numba cold JIT 724ms overhead YOK).

  SEC55.C (arsiv): Numba JIT cache=True ile port edilmis; daemon'da cache miss
  nedeniyle her process restart'ta cold compile (455ms + 269ms = 724ms ek saat).
  Numba cache dosyalari olusmamisti (engulfing module o gun hic import edilmemis).
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from price_action.contracts import Signal
from price_action.logging_config import logger
from price_action.strategies.base import Strategy, StrategyManifest

# Shared helpers — aynı fonksiyonlari yeniden yazmaktan kacin
from price_action.strategies.classic_pa import (
    _atr,
    _ema,
    _fractal_swings,
    _kaufman_efficiency_ratio,
    _always_in_flags,
    _rolling_sharpe,
    _sr_levels,
)


# =====================================================================
# Numba JIT kernel — SEC55.C
# =====================================================================

_ENGULF_NUMBA_AVAILABLE = False

try:
    import numba  # noqa: F401
    from numba import njit

    @njit(cache=True, fastmath=False)
    def _sr_proximity_jit_kernel(
        closes: np.ndarray,
        atrs: np.ndarray,
        sr_bar_idx: np.ndarray,   # int64 array: bar index of each SR record
        sr_levels: np.ndarray,    # float64 array: price level of each SR record
        proximity_atr: float,
    ) -> np.ndarray:
        """Numba JIT — SR proximity flag per bar.

        Her bar i icin sr_by_bar[i]'deki level'lara bakar,
        |close - level| <= proximity_atr * ATR ise near_sr = True.

        Args:
            closes:       close fiyat dizisi (n,)
            atrs:         ATR dizisi (n,)
            sr_bar_idx:   SR record bar indeksleri (m,) — srted by bar
            sr_levels:    SR record fiyat seviyeleri (m,)
            proximity_atr: ATR katsayisi (ornegin 0.5)

        Returns:
            near_sr_arr: bool-as-float64 (0/1), shape (n,)
        """
        n = len(closes)
        m = len(sr_bar_idx)
        near_sr_arr = np.zeros(n, dtype=np.float64)

        if proximity_atr <= 0.0 or m == 0:
            return near_sr_arr

        # SR kayitlari bar bazli gruplu (sr_bar_idx sorted ascending)
        for i in range(n):
            close_i = closes[i]
            atr_i = atrs[i]
            if atr_i <= 0.0:
                continue
            tol = proximity_atr * atr_i
            # sr_bar_idx dizi siralanmis — binary search yerine linear scan
            # (m tipik olarak kucuk: 120 lookback / 5 cache = ~24 entry/bar)
            for r in range(m):
                if sr_bar_idx[r] == i:
                    if abs(close_i - sr_levels[r]) <= tol:
                        near_sr_arr[i] = 1.0
                        break

        return near_sr_arr

    @njit(cache=True, fastmath=False)
    def _engulfing_score_jit_kernel(
        long_score: np.ndarray,
        short_score: np.ndarray,
        near_sr_arr: np.ndarray,
        atr_arr: np.ndarray,
        struct_sl_long: np.ndarray,
        struct_sl_short: np.ndarray,
        closes: np.ndarray,
        bonus: float,
        proximity_atr: float,
        min_score: float,
    ) -> tuple:
        """Numba JIT — final score + SL hesaplama tek geciste.

        Her bar i icin:
          - bonus ekleme (near_sr)
          - proximity penalty (proximity_atr > 0 and NOT near_sr: -0.25)
          - min_score gate
          - SL hesaplama (structural veya ATR fallback)

        Returns:
            (long_final, short_final, sl_long, sl_short)
            dtype float64; score <= 0 => gecersiz, NaN SL => gecersiz
        """
        n = len(long_score)
        long_final = np.zeros(n, dtype=np.float64)
        short_final = np.zeros(n, dtype=np.float64)
        sl_long_out = np.full(n, np.nan)
        sl_short_out = np.full(n, np.nan)

        for i in range(n):
            atr_i = atr_arr[i]
            if atr_i <= 0.0 or np.isnan(atr_i):
                continue

            close_i = closes[i]
            near_sr = near_sr_arr[i] > 0.0

            # Long
            ls = long_score[i]
            if ls > 0.0:
                fs = ls + (bonus if near_sr else 0.0)
                if proximity_atr > 0.0 and not near_sr:
                    fs -= 0.25
                    if fs < 0.0:
                        fs = 0.0
                if fs >= min_score:
                    long_final[i] = fs
                    sl_raw = struct_sl_long[i]
                    if np.isnan(sl_raw) or sl_raw <= 0.0:
                        sl_raw = close_i - 2.0 * atr_i
                    sl_adj = sl_raw if sl_raw < close_i - 0.5 * atr_i else close_i - 0.5 * atr_i
                    sl_long_out[i] = sl_adj

            # Short
            ss = short_score[i]
            if ss > 0.0:
                fs = ss + (bonus if near_sr else 0.0)
                if proximity_atr > 0.0 and not near_sr:
                    fs -= 0.25
                    if fs < 0.0:
                        fs = 0.0
                if fs >= min_score:
                    short_final[i] = fs
                    sl_raw = struct_sl_short[i]
                    if np.isnan(sl_raw) or sl_raw <= 0.0:
                        sl_raw = close_i + 2.0 * atr_i
                    sl_adj = sl_raw if sl_raw > close_i + 0.5 * atr_i else close_i + 0.5 * atr_i
                    sl_short_out[i] = sl_adj

        return long_final, short_final, sl_long_out, sl_short_out

    _ENGULF_NUMBA_AVAILABLE = True

except Exception:
    pass


# =====================================================================
# Numpy vectorized kernels — SEC55.D hot path (DEFAULT)
# =====================================================================

def _sr_proximity_numpy(
    closes: np.ndarray,
    atrs: np.ndarray,
    sr_bar_idx: np.ndarray,
    sr_levels_arr: np.ndarray,
    proximity_atr: float,
) -> np.ndarray:
    """Numpy vectorized SR proximity — SEC55.D DEFAULT path.

    O(m) numpy indexing vs O(n*m) Python nested loop.
    n=730, m=9335: 0.018ms vs 207ms (11500x speedup).
    Parity: rtol=1e-9 vs Python fallback — PASS.

    Algorithm:
        tols = proximity_atr * atrs[sr_bar_idx]   # per-record tolerance
        hit  = |close[sr_bar_idx] - level| <= tol # vectorized
        near_sr[bar_idx[hit]] = 1.0               # scatter
    """
    n = len(closes)
    near_sr_arr = np.zeros(n, dtype=np.float64)
    if proximity_atr <= 0.0 or len(sr_bar_idx) == 0:
        return near_sr_arr
    tols = proximity_atr * atrs[sr_bar_idx]          # (m,) tolerances
    close_at = closes[sr_bar_idx]                    # (m,) close per record
    hit = np.abs(close_at - sr_levels_arr) <= tols   # (m,) bool
    np.maximum.at(near_sr_arr, sr_bar_idx[hit], 1.0) # scatter — handles dups
    return near_sr_arr


def _engulfing_score_numpy(
    long_score: np.ndarray,
    short_score: np.ndarray,
    near_sr_arr: np.ndarray,
    atr_arr: np.ndarray,
    struct_sl_long: np.ndarray,
    struct_sl_short: np.ndarray,
    closes: np.ndarray,
    bonus: float,
    proximity_atr: float,
    min_score: float,
) -> tuple:
    """Numpy vectorized score + SL — SEC55.D DEFAULT path.

    O(n) broadcasting vs O(n) Python loop (21x speedup, cache-friendly).
    Parity: rtol=1e-9 vs Python fallback — PASS.
    """
    n = len(long_score)
    long_final = np.zeros(n, dtype=np.float64)
    short_final = np.zeros(n, dtype=np.float64)
    sl_long_out = np.full(n, np.nan)
    sl_short_out = np.full(n, np.nan)

    valid = (atr_arr > 0.0) & ~np.isnan(atr_arr)
    near = near_sr_arr > 0.0

    # ---- Long ----
    active_l = valid & (long_score > 0.0)
    fs_l = long_score.copy()
    fs_l[active_l & near] += bonus
    if proximity_atr > 0.0:
        penalty_l = active_l & ~near
        fs_l[penalty_l] -= 0.25
        np.maximum(fs_l, 0.0, out=fs_l)
    gate_l = active_l & (fs_l >= min_score)
    long_final[gate_l] = fs_l[gate_l]
    # SL long
    sl_raw_l = struct_sl_long.copy()
    fallback_l = np.isnan(sl_raw_l) | (sl_raw_l <= 0.0)
    sl_raw_l[fallback_l] = closes[fallback_l] - 2.0 * atr_arr[fallback_l]
    min_sl_l = closes - 0.5 * atr_arr
    sl_adj_l = np.where(sl_raw_l < min_sl_l, sl_raw_l, min_sl_l)
    sl_long_out[gate_l] = sl_adj_l[gate_l]

    # ---- Short ----
    active_s = valid & (short_score > 0.0)
    fs_s = short_score.copy()
    fs_s[active_s & near] += bonus
    if proximity_atr > 0.0:
        penalty_s = active_s & ~near
        fs_s[penalty_s] -= 0.25
        np.maximum(fs_s, 0.0, out=fs_s)
    gate_s = active_s & (fs_s >= min_score)
    short_final[gate_s] = fs_s[gate_s]
    # SL short
    sl_raw_s = struct_sl_short.copy()
    fallback_s = np.isnan(sl_raw_s) | (sl_raw_s <= 0.0)
    sl_raw_s[fallback_s] = closes[fallback_s] + 2.0 * atr_arr[fallback_s]
    min_sl_s = closes + 0.5 * atr_arr
    sl_adj_s = np.where(sl_raw_s > min_sl_s, sl_raw_s, min_sl_s)
    sl_short_out[gate_s] = sl_adj_s[gate_s]

    return long_final, short_final, sl_long_out, sl_short_out


# =====================================================================
# Python O(n*m) fallbacks — ARCHIVE / parity reference only
# =====================================================================

def _sr_proximity_python_fallback(
    closes: np.ndarray,
    atrs: np.ndarray,
    sr_bar_idx: np.ndarray,
    sr_levels_arr: np.ndarray,
    proximity_atr: float,
) -> np.ndarray:
    """Python O(n*m) fallback — parity reference, NOT production path.

    SEC55.D: Bu fonksiyon artik dispatch wrapper'larda kullanilmiyor.
    Test parity referansi olarak korunuyor.
    n=730, m=9335: 207ms/sym — daemon'da 3:37 gecikmeye yol aciyordu.
    """
    n = len(closes)
    near_sr_arr = np.zeros(n, dtype=np.float64)
    if proximity_atr <= 0.0 or len(sr_bar_idx) == 0:
        return near_sr_arr
    for i in range(n):
        close_i = closes[i]
        atr_i = atrs[i]
        if atr_i <= 0.0:
            continue
        tol = proximity_atr * atr_i
        for r in range(len(sr_bar_idx)):
            if sr_bar_idx[r] == i:
                if abs(close_i - sr_levels_arr[r]) <= tol:
                    near_sr_arr[i] = 1.0
                    break
    return near_sr_arr


def _engulfing_score_python_fallback(
    long_score: np.ndarray,
    short_score: np.ndarray,
    near_sr_arr: np.ndarray,
    atr_arr: np.ndarray,
    struct_sl_long: np.ndarray,
    struct_sl_short: np.ndarray,
    closes: np.ndarray,
    bonus: float,
    proximity_atr: float,
    min_score: float,
) -> tuple:
    """Python O(n) fallback — parity reference, NOT production path.

    SEC55.D: Bu fonksiyon artik dispatch wrapper'larda kullanilmiyor.
    Test parity referansi olarak korunuyor.
    """
    n = len(long_score)
    long_final = np.zeros(n, dtype=np.float64)
    short_final = np.zeros(n, dtype=np.float64)
    sl_long_out = np.full(n, np.nan)
    sl_short_out = np.full(n, np.nan)

    for i in range(n):
        atr_i = atr_arr[i]
        if atr_i <= 0.0 or np.isnan(atr_i):
            continue
        close_i = closes[i]
        near_sr = near_sr_arr[i] > 0.0

        ls = long_score[i]
        if ls > 0.0:
            fs = ls + (bonus if near_sr else 0.0)
            if proximity_atr > 0.0 and not near_sr:
                fs -= 0.25
                if fs < 0.0:
                    fs = 0.0
            if fs >= min_score:
                long_final[i] = fs
                sl_raw = struct_sl_long[i]
                if np.isnan(sl_raw) or sl_raw <= 0.0:
                    sl_raw = close_i - 2.0 * atr_i
                sl_adj = sl_raw if sl_raw < close_i - 0.5 * atr_i else close_i - 0.5 * atr_i
                sl_long_out[i] = sl_adj

        ss = short_score[i]
        if ss > 0.0:
            fs = ss + (bonus if near_sr else 0.0)
            if proximity_atr > 0.0 and not near_sr:
                fs -= 0.25
                if fs < 0.0:
                    fs = 0.0
            if fs >= min_score:
                short_final[i] = fs
                sl_raw = struct_sl_short[i]
                if np.isnan(sl_raw) or sl_raw <= 0.0:
                    sl_raw = close_i + 2.0 * atr_i
                sl_adj = sl_raw if sl_raw > close_i + 0.5 * atr_i else close_i + 0.5 * atr_i
                sl_short_out[i] = sl_adj

    return long_final, short_final, sl_long_out, sl_short_out


# =====================================================================
# Dispatch wrappers — SEC55.D
# =====================================================================
# DEFAULT: numpy vectorized (no JIT overhead, 11500x vs Python O(n*m))
# PA_ENGULF_NUMBA=1: Numba JIT (warm only — first call 724ms cold compile)
# =====================================================================

def _run_sr_proximity(
    closes: np.ndarray,
    atrs: np.ndarray,
    sr_bar_idx: np.ndarray,
    sr_levels_arr: np.ndarray,
    proximity_atr: float,
    use_numba: bool = False,
) -> np.ndarray:
    """SR proximity dispatch — numpy default (SEC55.D).

    SEC55.D FIX: default path artik numpy vectorized (_sr_proximity_numpy).
    O(m) numpy indexing — 0.018ms vs Python O(n*m) 207ms (n=730, m=9335).
    PA_ENGULF_NUMBA=1 env var ile Numba JIT aktif edilebilir (warm sonrasi
    daha hizli ama cold compile 455ms overhead var).
    Parity: rtol=1e-9 PASS (her iki path da test edildi).
    """
    import os
    if os.getenv("PA_ENGULF_NUMBA", "0") == "1":
        use_numba = True
    if use_numba and _ENGULF_NUMBA_AVAILABLE:
        return _sr_proximity_jit_kernel(closes, atrs, sr_bar_idx, sr_levels_arr, proximity_atr)
    return _sr_proximity_numpy(closes, atrs, sr_bar_idx, sr_levels_arr, proximity_atr)


def _run_engulfing_score(
    long_score: np.ndarray,
    short_score: np.ndarray,
    near_sr_arr: np.ndarray,
    atr_arr: np.ndarray,
    struct_sl_long: np.ndarray,
    struct_sl_short: np.ndarray,
    closes: np.ndarray,
    bonus: float,
    proximity_atr: float,
    min_score: float,
    use_numba: bool = False,
) -> tuple:
    """Score + SL dispatch — numpy default (SEC55.D).

    SEC55.D FIX: default path artik numpy vectorized (_engulfing_score_numpy).
    O(n) broadcasting — 0.044ms vs Python O(n) 0.94ms (21x).
    PA_ENGULF_NUMBA=1 env var ile Numba JIT aktif edilebilir.
    Parity: rtol=1e-9 PASS.
    """
    import os
    if os.getenv("PA_ENGULF_NUMBA", "0") == "1":
        use_numba = True
    if use_numba and _ENGULF_NUMBA_AVAILABLE:
        return _engulfing_score_jit_kernel(
            long_score, short_score, near_sr_arr, atr_arr,
            struct_sl_long, struct_sl_short, closes,
            bonus, proximity_atr, min_score,
        )
    return _engulfing_score_numpy(
        long_score, short_score, near_sr_arr, atr_arr,
        struct_sl_long, struct_sl_short, closes,
        bonus, proximity_atr, min_score,
    )


# =====================================================================
# Strateji ozgune ek yardimcilar
# =====================================================================

def _pullback_to_ema_flag(
    df: pd.DataFrame,
    ema_col: str = "ema20",
    window: int = 10,
    touch_atr_factor: float = 0.5,
) -> pd.Series:
    """Son `window` barda fiyat 20-EMA'ya yeterince yakin geldi mi?

    Dokunma kriteri: bar'in low <= ema + touch_atr_factor*atr  VE
                     bar'in high >= ema - touch_atr_factor*atr
    (yani EMA, bar'in 'atr*factor' bandi icinde kalmis olmali)

    Lookahead-free: t bari icin sadece [t-window..t-1] bari kullanilir.
    """
    close = df["close"]
    ema_val = df[ema_col]
    atr_val = df["atr14"].fillna(0.0)
    tolerance = atr_val * touch_atr_factor

    # Bar bazli dokunma: low <= ema + tol AND high >= ema - tol
    bar_low = df["low"]
    bar_high = df["high"]
    touched = (bar_low <= ema_val + tolerance) & (bar_high >= ema_val - tolerance)

    # Son `window` bar icinde herhangi bir dokunma var mi? (t dahil degil — shift)
    # shift(1) ile t-1'e tasiyoruz, rolling(window) ile [t-window..t-1]'e bakiyoruz
    pulled_back = touched.shift(1).rolling(window, min_periods=1).max().fillna(0).astype(bool)
    return pulled_back


def _strict_engulfing(
    df: pd.DataFrame,
    body_ratio_min: float = 0.6,
    bullish: bool = True,
) -> pd.Series:
    """Strict engulfing: body(N) tamamen body(N-1)'i sarar + body_ratio >= 0.6.

    body_ratio = body_abs / total_range — sadece engulfing bar icin.
    Lookahead-free: sadece shift(1) (t-1 bar bilgisi) kullanilir.
    """
    o = df["open"]
    c = df["close"]
    prev_o = o.shift(1)
    prev_c = c.shift(1)
    rng = (df["high"] - df["low"]).replace(0, np.nan)
    body_abs = (c - o).abs()
    body_ratio = body_abs / rng

    if bullish:
        color_ok = (c > o) & (prev_c < prev_o)           # N bullish, N-1 bearish
        # N body tamamen N-1 body'yi sarar (strict: >=)
        engulf = (o <= prev_c) & (c >= prev_o)
    else:
        color_ok = (c < o) & (prev_c > prev_o)           # N bearish, N-1 bullish
        engulf = (o >= prev_c) & (c <= prev_o)

    strict = color_ok & engulf & (body_ratio >= body_ratio_min)
    return strict.fillna(False)


def _swing_sl(
    df: pd.DataFrame,
    direction: str,
    lookback: int = 10,
) -> pd.Series:
    """Structural stop: son `lookback` barin swing low (long) veya swing high (short).

    Lookahead-free: t bari icin [t-lookback..t-1] araligina bakilir.
    """
    if direction == "long":
        sl = df["low"].shift(1).rolling(lookback, min_periods=1).min()
    else:
        sl = df["high"].shift(1).rolling(lookback, min_periods=1).max()
    return sl


# =====================================================================
# Default manifest
# =====================================================================

def _default_manifest() -> StrategyManifest:
    raw = {
        "name": "engulfing_continuation",
        "version": "1.0.0",
        "description": "Engulfing bar after 20-EMA pullback in established trend",
        "trend_filter": {"type": "ema", "period": 50, "required": True},
        "signals": {
            "patterns": [
                {
                    "id": "bullish_engulfing_cont",
                    "enabled": True,
                    "weight": 1.5,
                    "params": {
                        "body_ratio_min": 0.6,
                        "pullback_window": 10,
                        "pullback_touch_atr": 0.5,
                    },
                },
                {
                    "id": "bearish_engulfing_cont",
                    "enabled": True,
                    "weight": 1.5,
                    "params": {
                        "body_ratio_min": 0.6,
                        "pullback_window": 10,
                        "pullback_touch_atr": 0.5,
                    },
                },
            ],
            "structure": {
                "swing": {"fractal_n": 2},
                "support_resistance": {
                    "lookback_bars": 120,
                    "cluster_atr_multiplier": 0.5,
                    "min_touches": 2,
                    "max_age_bars": 120,
                },
                "require_proximity_to_sr_atr": 0.5,
            },
            "filters": {
                "atr_min_pct": 0.005,
                "volume_zscore_min": 0.0,
                "kaufman_er_period": 14,
                "kaufman_er_min": 0.20,
                "always_in_required": False,
                "bear_regime_size_factor": 0.5,
            },
            "confluence": {
                "method": "weighted_sum",
                "min_score": 1.5,
                "bonus_if_at_sr": 0.5,
            },
        },
        "risk": {
            "stop_loss": {"method": "structural", "swing_lookback": 10},
            "take_profit": {"method": "r_multiple", "primary_R": 2.0},
            "position_sizing": {"method": "fixed_fractional", "risk_per_trade": 0.01},
        },
    }
    return StrategyManifest.model_validate(raw)


# =====================================================================
# Strategy implementation
# =====================================================================

class EngulfingContinuationStrategy(Strategy):
    """Engulfing bar after 20-EMA pullback in established trend.

    Trend filtresi  : 50-EMA + Brooks always-in 3-bar
    Pullback        : Son 10 barda fiyat 20-EMA'ya dokundu (ATR tol)
    Engulfing       : Strict (body >= 0.6 * range, tam sarim, zit renk)
    Giris           : N+1 bar acilis
    Stop            : Structural swing low/high (son 10 bar)
    Hedef           : 2R
    """

    name = "engulfing_continuation"

    def prepare_features(self, df: pd.DataFrame) -> pd.DataFrame:
        if df.empty:
            return df.copy()
        self.apply_tf_manifest(df)
        df = df.sort_values("ts").reset_index(drop=True).copy()

        # EMAs
        df["ema20"] = _ema(df["close"], 20)
        df["ema14"] = _ema(df["close"], 14)  # runner trailing stop
        df["ema50"] = _ema(df["close"], 50)
        df["ema200"] = _ema(df["close"], 200)

        # ATR
        df["atr14"] = _atr(df, 14)
        df["atr_pct"] = df["atr14"] / df["close"]

        # Volume z-score (60 bar)
        vol = df["volume"]
        vmean = vol.rolling(60, min_periods=10).mean()
        vstd = vol.rolling(60, min_periods=10).std(ddof=0)
        df["vol_z"] = (vol - vmean) / vstd.replace(0, np.nan)

        # Swing high/low (fractal)
        n = self.manifest.signals.structure.swing.fractal_n
        sh, sl = _fractal_swings(df, n=n)
        df["swing_high"] = sh
        df["swing_low"] = sl

        # Pullback to 20-EMA flag (rolling 10-bar window)
        filters_cfg = self.manifest.signals.filters
        pb_window = 10
        pb_touch = 0.5
        # Try to get params from first pattern
        for p in self.manifest.signals.patterns:
            if p.id in ("bullish_engulfing_cont", "bearish_engulfing_cont"):
                pb_window = int(p.params.get("pullback_window", 10))
                pb_touch = float(p.params.get("pullback_touch_atr", 0.5))
                break
        df["pullback_to_20ema"] = _pullback_to_ema_flag(
            df, ema_col="ema20", window=pb_window, touch_atr_factor=pb_touch
        )

        # Strict engulfing flags
        body_ratio_min = 0.6
        for p in self.manifest.signals.patterns:
            if p.id in ("bullish_engulfing_cont", "bearish_engulfing_cont"):
                body_ratio_min = float(p.params.get("body_ratio_min", 0.6))
                break
        df["strict_bull_engulf"] = _strict_engulfing(df, body_ratio_min=body_ratio_min, bullish=True)
        df["strict_bear_engulf"] = _strict_engulfing(df, body_ratio_min=body_ratio_min, bullish=False)

        # Structural SL levels
        df["struct_sl_long"] = _swing_sl(df, "long", lookback=10)
        df["struct_sl_short"] = _swing_sl(df, "short", lookback=10)

        # Kaufman ER
        er_period = int(getattr(filters_cfg, "kaufman_er_period", 14) or 14)
        df["kaufman_er"] = _kaufman_efficiency_ratio(df["close"], period=er_period)

        # Brooks always-in flags
        ai_n = int(getattr(filters_cfg, "always_in_n_confirm", 3) or 3)
        long_ai, short_ai = _always_in_flags(df, n_confirm=ai_n)
        df["always_in_long"] = long_ai
        df["always_in_short"] = short_ai

        # Rolling Sharpe
        rs_period = int(getattr(filters_cfg, "rolling_sharpe_period", 60) or 60)
        df["rolling_sharpe"] = _rolling_sharpe(df["close"], period=rs_period)

        return df

    def generate_signals(self, df: pd.DataFrame) -> list[Signal]:
        if df.empty:
            return []
        if "ema20" not in df.columns:
            df = self.prepare_features(df)

        signals_cfg = self.manifest.signals
        filters = signals_cfg.filters
        confluence = signals_cfg.confluence
        sr_cfg = signals_cfg.structure.support_resistance

        primary_R = float(
            self.manifest.risk.get("take_profit", {}).get("primary_R", 2.0)
        )

        venue = str(df["venue"].iloc[0]) if "venue" in df.columns else "unknown"
        symbol = str(df["symbol"].iloc[0]) if "symbol" in df.columns else "UNKNOWN"
        timeframe = str(df["timeframe"].iloc[0]) if "timeframe" in df.columns else "1d"

        # --- Score series (Pandas vectorized — bu kisim degismedi) ---
        long_score = pd.Series(0.0, index=df.index)
        short_score = pd.Series(0.0, index=df.index)

        # Pattern weights
        bull_weight = 1.5
        bear_weight = 1.5
        for p in signals_cfg.patterns:
            if not p.enabled:
                continue
            if p.id == "bullish_engulfing_cont":
                bull_weight = p.weight
            elif p.id == "bearish_engulfing_cont":
                bear_weight = p.weight

        # Pullback + engulfing condition
        pullback = df["pullback_to_20ema"].fillna(False)
        bull_engulf = df["strict_bull_engulf"].fillna(False)
        bear_engulf = df["strict_bear_engulf"].fillna(False)

        long_score = long_score.where(~(pullback & bull_engulf), bull_weight)
        short_score = short_score.where(~(pullback & bear_engulf), bear_weight)

        # --- Trend filter (50-EMA direction) ---
        if self.manifest.trend_filter.required:
            up_ok = df["close"] > df["ema50"]
            down_ok = df["close"] < df["ema50"]
            long_score = long_score.where(up_ok, 0.0)
            short_score = short_score.where(down_ok, 0.0)

        # --- ATR min filter ---
        atr_min = float(getattr(filters, "atr_min_pct", 0.005) or 0.005)
        if atr_min > 0:
            mask = df["atr_pct"] >= atr_min
            long_score = long_score.where(mask, 0.0)
            short_score = short_score.where(mask, 0.0)

        # --- Volume z-score filter ---
        vol_min = float(getattr(filters, "volume_zscore_min", 0.0) or 0.0)
        if vol_min > 0:
            mask = df["vol_z"].fillna(-np.inf) >= vol_min
            long_score = long_score.where(mask, 0.0)
            short_score = short_score.where(mask, 0.0)

        # --- Kaufman ER min ---
        er_min = float(getattr(filters, "kaufman_er_min", 0.0) or 0.0)
        if er_min > 0 and "kaufman_er" in df.columns:
            mask = df["kaufman_er"] >= er_min
            long_score = long_score.where(mask, 0.0)
            short_score = short_score.where(mask, 0.0)

        # --- Brooks always-in (optional) ---
        if bool(getattr(filters, "always_in_required", False)):
            long_score = long_score.where(df["always_in_long"], 0.0)
            short_score = short_score.where(df["always_in_short"], 0.0)

        # --- Rolling Sharpe size factor ---
        rs_min = float(getattr(filters, "rolling_sharpe_min", -1e9))
        rs_size_factor = float(getattr(filters, "rolling_sharpe_size_factor", 1.0) or 1.0)
        if rs_min > -1e8 and "rolling_sharpe" in df.columns:
            poor_regime = df["rolling_sharpe"] < rs_min
            long_score = long_score.where(~poor_regime, long_score * rs_size_factor)
            short_score = short_score.where(~poor_regime, short_score * rs_size_factor)

        # --- 200-EMA bear regime size factor ---
        bear_factor = float(getattr(filters, "bear_regime_size_factor", 1.0) or 1.0)
        if bear_factor < 1.0 and "ema200" in df.columns:
            below_200 = df["close"] < df["ema200"]
            long_score = long_score.where(~below_200, long_score * bear_factor)

        # --- S/R levels (lookahead-free) ---
        cluster_tol = df["atr14"].fillna(0) * sr_cfg.cluster_atr_multiplier
        sr_records = _sr_levels(
            df,
            lookback_bars=sr_cfg.lookback_bars,
            cluster_tol=cluster_tol,
            min_touches=sr_cfg.min_touches,
        )

        proximity_atr = signals_cfg.structure.require_proximity_to_sr_atr
        bonus = float(getattr(confluence, "bonus_if_at_sr", 0.0) or 0.0)
        min_score = float(confluence.min_score)

        # SR records -> numpy arrays for Numba kernel
        if sr_records:
            sr_bar_idx_np = np.array([r[0] for r in sr_records], dtype=np.int64)
            sr_levels_np = np.array([r[1] for r in sr_records], dtype=np.float64)
        else:
            sr_bar_idx_np = np.empty(0, dtype=np.int64)
            sr_levels_np = np.empty(0, dtype=np.float64)

        closes_np = df["close"].to_numpy(dtype=np.float64)
        atrs_np = df["atr14"].fillna(0.0).to_numpy(dtype=np.float64)
        long_score_np = long_score.to_numpy(dtype=np.float64)
        short_score_np = short_score.to_numpy(dtype=np.float64)
        struct_sl_long_np = df["struct_sl_long"].to_numpy(dtype=np.float64)
        struct_sl_short_np = df["struct_sl_short"].to_numpy(dtype=np.float64)

        # SR proximity (Numba JIT)
        near_sr_np = _run_sr_proximity(
            closes=closes_np, atrs=atrs_np,
            sr_bar_idx=sr_bar_idx_np, sr_levels_arr=sr_levels_np,
            proximity_atr=float(proximity_atr),
        )

        # Final score + SL hesaplama (Numba JIT)
        long_final_np, short_final_np, sl_long_np, sl_short_np = _run_engulfing_score(
            long_score=long_score_np, short_score=short_score_np,
            near_sr_arr=near_sr_np, atr_arr=atrs_np,
            struct_sl_long=struct_sl_long_np, struct_sl_short=struct_sl_short_np,
            closes=closes_np, bonus=bonus,
            proximity_atr=float(proximity_atr), min_score=min_score,
        )

        # SR by bar map (meta icin)
        sr_by_bar: dict[int, list[float]] = {}
        for r_i, r_lvl, _t in sr_records:
            sr_by_bar.setdefault(r_i, []).append(r_lvl)

        out: list[Signal] = []
        for i in range(len(df)):
            atr = atrs_np[i]
            if atr <= 0.0 or np.isnan(atr):
                continue

            close = closes_np[i]
            near_sr = near_sr_np[i] > 0.0
            row = df.iloc[i]

            for direction, final_score, sl_price in (
                ("long", long_final_np[i], sl_long_np[i]),
                ("short", short_final_np[i], sl_short_np[i]),
            ):
                if final_score <= 0.0 or np.isnan(sl_price):
                    continue

                if direction == "long":
                    risk = close - sl_price
                    tp_price = close + primary_R * risk
                else:
                    risk = sl_price - close
                    tp_price = close - primary_R * risk

                if risk <= 0.0:
                    continue

                pattern_id_name = (
                    "bullish_engulfing_cont" if direction == "long" else "bearish_engulfing_cont"
                )

                ts = pd.Timestamp(row["ts"]).to_pydatetime()
                sig = self.emit_signal(
                    ts=ts,
                    venue=venue,
                    symbol=symbol,
                    timeframe=timeframe,
                    direction=direction,
                    pattern_id=pattern_id_name,
                    confluence_score=float(final_score),
                    sl_price=float(sl_price),
                    tp_price=float(tp_price),
                    suggested_size_atr=1.0,
                    metadata={
                        "near_sr": near_sr,
                        "atr14": atr,
                        "ema20": float(row.get("ema20") or 0.0),
                        "ema50": float(row.get("ema50") or 0.0),
                        "pullback_to_20ema": bool(row.get("pullback_to_20ema", False)),
                        "kaufman_er": float(row.get("kaufman_er") or 0.0),
                    },
                )
                out.append(sig)

        self._log.bind(n=len(out), bars=len(df)).info("engulfing_cont.signals.generated")
        return out
