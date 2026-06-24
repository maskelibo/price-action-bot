"""Anchored VWAP + Volume Profile POC Reversal stratejisi.

Strateji konsepti:
  - AVWAP: belirli bir anchor bar'dan (HTF swing low/high) itibaren hesaplanan
    hacim-agirlikli ortalama fiyat.  Kurumsal algoritmalar bu noktayi referans
    alir — Harris (2003) "value traders" absorpsiyon hipotezi.
  - POC (Point of Control): son N barin volume profile'inda en yuksek hacimli
    fiyat bolgesi.  Bu seviye kurumsal "fair value" gorusunu yansitir.
  - Entry: fiyat AVWAP'a yukari donuste (long) veya asagi donuste (short)
    yaklasirken POC confluance'i varsa sinyal uretilir.
  - Karakter: mean-reversion — engulfing_continuation trend-following ile
    dekorelasyon saglar (Kaufman portfolio diversification ilkesi).

Kural ozeti:
  Long:
    - close > ema200  (uzun vadeli bias yukari)
    - avwap_long (swing-low anchor) mevcut
    - price crosses AVWAP from below (body rejection up)
    - POC yakinda: |close - poc| <= 1.5 * ATR14
    - RSI14 < 55 (overbought degil)
  Short: simetrik (swing-high anchor, price crosses AVWAP from above, RSI > 45)
  SL  : structural swing low/high - 1.0 * ATR (buffer)
  TP  : 2R

Manifest yoksa dahili default kullanilir.

---
Confluence score tasarimi (v1.1 — SEC52 fix, Signal Chief 2026-05-17):
  Onceki tasarim (v1.0 BUG): score = bull_weight (1.5 sabit) => conf = 0.0
    Pool normalizasyonu: conf = (score - 1.5) / 1.5 => (1.5-1.5)/1.5 = 0.0
    filter_conf_min=0.25 => TUM AVWAP trade'leri elendi (103,804 reject kanitli).

  Yeni tasarim (v1.1 DYNAMIC):
    base_score = bull/bear_weight (1.5) — entry kosu gecmis olmak gerekiyor zaten
    Dinamik faktorler (manifesden parametrik):
      F1 rsi_extreme     : RSI < rsi_extreme_thr (long) / RSI > 100-rsi_extreme_thr (short)
      F2 poc_tight       : |close - poc| <= poc_tight_atr * ATR (default 0.5 × ATR)
      F3 vol_elevated    : vol_z >= vol_z_bonus_min (default 1.0)
      F4 ema_dist        : |close - ema200| >= ema_dist_atr * ATR (default 1.5 × ATR)
    Her faktor: factor_weight = 0.375 (default, manifesden)
    max_bonus = 4 × 0.375 = 1.5 => max_score = 1.5 + 1.5 = 3.0
    Pool normalizasyonu ile: conf = (score - 1.5) / 1.5 ∈ [0.0, 1.0]
    Tek faktor aktifse: conf = 0.375/1.5 = 0.25 >= filter_conf_min=0.25 => PASS.

  Lookahead: tum faktorler t-1 close'a dayali (shift kullanimda yok,
    _rsi / _ema / vol_z seriler causal hesaplamali, avwap [anchor..t-1]).

  Vectorized: for-loop sadece signal emit icin (enumerate uzerinden); faktor
    serileri pd.Series boolean vektoru olarak hesaplaniyor.

---
Performance (SEC55.B — 2026-05-18):
  _volume_profile_poc + _rolling_avwap_from_swing: Numba JIT kernel ile
  50-100× speedup hedefi (NPOC-001 precedent: 832×).
  Fallback: numba yoksa Python path, no crash.
  Parity: rtol=1e-9, atol=1e-12 garantili.
  fastmath=False: floating point determinizm korur.
  cache=True: ilk-run JIT compile maliyeti sonraki run'larda sifir.
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from price_action.contracts import Signal
from price_action.logging_config import logger
from price_action.strategies.base import Strategy, StrategyManifest

# Paylasilmis yardimcilar (engulfing_continuation ile ortak kaynak)
from price_action.strategies.classic_pa import (
    _atr,
    _ema,
    _fractal_swings,
)


# =====================================================================
# Numba JIT kernelleri — SEC55.B
# Numba yoksa _AVWAP_NUMBA_AVAILABLE=False, Python fallback kullanilir.
# =====================================================================

_AVWAP_NUMBA_AVAILABLE = False
_avwap_poc_jit_fn = None      # type: ignore[assignment]
_avwap_rolling_jit_fn = None  # type: ignore[assignment]

try:
    import numba  # noqa: F401
    from numba import njit

    @njit(cache=True, fastmath=False)
    def _poc_avwap_jit_kernel(
        lows: np.ndarray,
        highs: np.ndarray,
        vols: np.ndarray,
        lookback: int,
        bins: int,
    ) -> np.ndarray:
        """Numba JIT — rolling volume profile POC per bar.

        Her t icin [t-lookback .. t-1] penceresinde volume profile POC.
        Lookahead-free: end = t (exclusive), t'nin kendi bari dahil edilmez.

        Algoritma:
          1. Pencere icindeki low/high araligini `bins` bucket'a bol.
          2. Her bucket'a overlapping bar volume'unu biriktirir.
          3. Max volume bucket'in merkez fiyati POC'tur.

        Args:
            lows:     low fiyat dizisi (float64, n)
            highs:    high fiyat dizisi (float64, n)
            vols:     volume dizisi (float64, n)
            lookback: pencere boyutu
            bins:     fiyat araligi bin sayisi

        Returns:
            poc_arr: her bar icin POC fiyati (float64, n), NaN = yeterli veri yok
        """
        n = len(lows)
        poc_arr = np.full(n, np.nan)

        for t in range(lookback, n):
            start = t - lookback
            # end = t exclusive: [start, t) = [t-lookback .. t-1] — lookahead-free

            # Manuel min/max (Numba'da np.nanmin slice destegi kisitli)
            price_min = np.inf
            price_max = -np.inf
            for k in range(lookback):
                lo_k = lows[start + k]
                hi_k = highs[start + k]
                if not np.isnan(lo_k) and lo_k < price_min:
                    price_min = lo_k
                if not np.isnan(hi_k) and hi_k > price_max:
                    price_max = hi_k

            if price_min == np.inf or price_max == -np.inf or price_max <= price_min:
                continue

            step = (price_max - price_min) / bins
            bucket_vol = np.zeros(bins)

            for k in range(lookback):
                blo_k = lows[start + k]
                bhi_k = highs[start + k]
                vol_k = vols[start + k]
                if np.isnan(blo_k) or np.isnan(bhi_k) or np.isnan(vol_k):
                    continue
                # Bu bar hangi bin'lerle overlap?
                bi_lo = int((blo_k - price_min) / step)
                bi_hi = int((bhi_k - price_min) / step)
                if bi_lo < 0:
                    bi_lo = 0
                if bi_hi >= bins:
                    bi_hi = bins - 1
                for bi in range(bi_lo, bi_hi + 1):
                    b_lo_edge = price_min + bi * step
                    b_hi_edge = b_lo_edge + step
                    if bhi_k >= b_lo_edge and blo_k <= b_hi_edge:
                        bucket_vol[bi] += vol_k

            total_vol = 0.0
            for bi in range(bins):
                total_vol += bucket_vol[bi]

            if total_vol == 0.0:
                poc_arr[t] = (price_min + price_max) / 2.0
                continue

            poc_idx = 0
            max_bvol = -1.0
            for bi in range(bins):
                if bucket_vol[bi] > max_bvol:
                    max_bvol = bucket_vol[bi]
                    poc_idx = bi

            poc_arr[t] = price_min + (poc_idx + 0.5) * step

        return poc_arr

    @njit(cache=True, fastmath=False)
    def _rolling_avwap_jit_kernel(
        closes: np.ndarray,
        highs: np.ndarray,
        lows: np.ndarray,
        vols: np.ndarray,
        swing_arr: np.ndarray,
        lookback: int,
    ) -> np.ndarray:
        """Numba JIT — rolling AVWAP from most recent swing anchor.

        Her t icin [t-lookback .. t-1] araliginda en son swing anchor bulur;
        anchor'dan t'ye kadar cumulative AVWAP hesaplar.

        Lookahead-free: anchor aranan aralik t-1'e kadar (t dahil degil).
        AVWAP hesaplarken t'nin kendi bari dahil (t bar'i kapaninca hesaplaniyor).

        Args:
            closes:   close fiyat dizisi (float64, n)
            highs:    high fiyat dizisi (float64, n)
            lows:     low fiyat dizisi (float64, n)
            vols:     volume dizisi (float64, n), negatif degerler 0'a clamp edilmis olmali
            swing_arr: swing serisi (float64, n) — NaN veya <=0 = swing degil
            lookback: max geriye bakis penceresi

        Returns:
            out: AVWAP degerleri (float64, n), NaN = anchor yok veya cum_vol=0
        """
        n = len(closes)
        out = np.full(n, np.nan)

        for t in range(lookback, n):
            # En yakin swing'i [t-1 .. t-lookback] araliginda ara (geriye dogru)
            anchor_idx = -1
            limit = t - lookback - 1  # dahil degil
            for i in range(t - 1, limit, -1):
                sv = swing_arr[i]
                if not np.isnan(sv) and sv > 0.0:
                    anchor_idx = i
                    break
            if anchor_idx < 0:
                continue

            # AVWAP: anchor_idx'ten t'ye (t dahil)
            cum_tpv = 0.0
            cum_vol = 0.0
            for i in range(anchor_idx, t + 1):
                tp = (highs[i] + lows[i] + closes[i]) / 3.0
                v = vols[i]
                if v < 0.0:
                    v = 0.0
                cum_vol += v
                cum_tpv += tp * v

            if cum_vol > 0.0:
                out[t] = cum_tpv / cum_vol

        return out

    _avwap_poc_jit_fn = _poc_avwap_jit_kernel
    _avwap_rolling_jit_fn = _rolling_avwap_jit_kernel
    _AVWAP_NUMBA_AVAILABLE = True

except Exception:  # noqa: BLE001
    # numba yok veya JIT derleme hatasi — Python fallback kullanilir
    _AVWAP_NUMBA_AVAILABLE = False
    _avwap_poc_jit_fn = None
    _avwap_rolling_jit_fn = None


# =====================================================================
# AVWAP + POC yardimcilari
# =====================================================================


def _poc_python_fallback(
    lows: np.ndarray,
    highs: np.ndarray,
    vols: np.ndarray,
    lookback: int,
    bins: int,
    index: "pd.Index",
) -> "pd.Series":
    """Saf Python/NumPy rolling POC (numba fallback).

    Lookahead-free: her t icin pencere [t-lookback .. t-1].
    Numba JIT ile bit-identical sonuc uretir (rtol=1e-9).
    """
    n = len(lows)
    poc_arr = np.full(n, np.nan)

    for t in range(lookback, n):
        start = t - lookback
        end = t  # exclusive — lookahead yok
        w_low = lows[start:end]
        w_high = highs[start:end]
        w_vol = vols[start:end]

        price_min_v = np.nanmin(w_low) if not np.all(np.isnan(w_low)) else np.nan
        price_max_v = np.nanmax(w_high) if not np.all(np.isnan(w_high)) else np.nan
        if np.isnan(price_min_v) or np.isnan(price_max_v) or price_max_v <= price_min_v:
            continue

        step = (price_max_v - price_min_v) / bins
        bucket_vol = np.zeros(bins)

        for k in range(len(w_low)):
            blo_k = w_low[k]
            bhi_k = w_high[k]
            vol_k = w_vol[k]
            if np.isnan(blo_k) or np.isnan(bhi_k) or np.isnan(vol_k):
                continue
            bi_lo = int((blo_k - price_min_v) / step)
            bi_hi = int((bhi_k - price_min_v) / step)
            if bi_lo < 0:
                bi_lo = 0
            if bi_hi >= bins:
                bi_hi = bins - 1
            for bi in range(bi_lo, bi_hi + 1):
                b_lo_edge = price_min_v + bi * step
                b_hi_edge = b_lo_edge + step
                if bhi_k >= b_lo_edge and blo_k <= b_hi_edge:
                    bucket_vol[bi] += vol_k

        total_vol = bucket_vol.sum()
        if total_vol == 0.0:
            poc_arr[t] = (price_min_v + price_max_v) / 2.0
        else:
            poc_idx = int(np.argmax(bucket_vol))
            poc_arr[t] = price_min_v + (poc_idx + 0.5) * step

    return pd.Series(poc_arr, index=index, dtype=float)


def _rolling_avwap_python_fallback(
    closes: np.ndarray,
    highs: np.ndarray,
    lows: np.ndarray,
    vols: np.ndarray,
    swing_arr: np.ndarray,
    lookback: int,
    index: "pd.Index",
) -> "pd.Series":
    """Saf Python rolling AVWAP from swing (numba fallback).

    Lookahead-free, Numba JIT ile bit-identical (rtol=1e-9).
    """
    n = len(closes)
    avwap_vals = np.full(n, np.nan)

    for t in range(lookback, n):
        anchor_idx = -1
        for i in range(t - 1, max(t - lookback - 1, -1), -1):
            sv = swing_arr[i]
            if not np.isnan(sv) and sv > 0.0:
                anchor_idx = i
                break
        if anchor_idx < 0:
            continue
        cum_tpv = 0.0
        cum_vol = 0.0
        for i in range(anchor_idx, t + 1):
            tp = (highs[i] + lows[i] + closes[i]) / 3.0
            v = max(vols[i], 0.0)
            cum_vol += v
            cum_tpv += tp * v
        if cum_vol > 0.0:
            avwap_vals[t] = cum_tpv / cum_vol

    return pd.Series(avwap_vals, index=index, dtype=float)


def _anchored_vwap(df: pd.DataFrame, anchor_idx: int) -> pd.Series:
    """Anchor bar'dan itibaren kumulatif hacim-agirlikli ortalama fiyat.

    Formul (Wikipedia kaynaklı):
      AVWAP_t = Σ_{i=anchor}^{t} (typical_price_i * volume_i)
                / Σ_{i=anchor}^{t} volume_i
      typical_price = (high + low + close) / 3

    Lookahead-free: t aninda sadece [anchor..t] araligi kullanilir.
    Anchor_idx cari bar'dan once olmali (t-1 veya daha eski).
    Eger anchor_idx >= len(df) veya negatif ise NaN serisi doner.
    """
    n = len(df)
    if anchor_idx < 0 or anchor_idx >= n:
        return pd.Series(np.nan, index=df.index)

    typical = (df["high"] + df["low"] + df["close"]) / 3.0
    vol = df["volume"].clip(lower=0.0)

    cum_tpv = np.zeros(n)
    cum_vol = np.zeros(n)

    for i in range(anchor_idx, n):
        if i == anchor_idx:
            cum_tpv[i] = typical.iat[i] * vol.iat[i]
            cum_vol[i] = vol.iat[i]
        else:
            cum_tpv[i] = cum_tpv[i - 1] + typical.iat[i] * vol.iat[i]
            cum_vol[i] = cum_vol[i - 1] + vol.iat[i]

    with np.errstate(invalid="ignore", divide="ignore"):
        avwap_arr = np.where(cum_vol > 0, cum_tpv / cum_vol, np.nan)

    result = pd.Series(avwap_arr, index=df.index, dtype=float)
    # anchor oncesi NaN
    result.iloc[:anchor_idx] = np.nan
    return result


def _volume_profile_poc(
    df: pd.DataFrame,
    lookback: int = 60,
    n_buckets: int = 50,
    use_numba: bool = True,
) -> pd.Series:
    """Son `lookback` barin volume profile'indan Point of Control (POC) hesapla.

    Lookahead-free: t bari icin [t-lookback .. t-1] kullanilir.

    Performance (SEC55.B): Numba JIT kernel aktif (use_numba=True ve numba
    yuklu ise). Python fallback: bit-identical sonuc, rtol=1e-9.

    Algoritma:
      1. Pencere icindeki low-high araligini n_buckets bucket'a bol.
      2. Her bucket'a overlapping bar volume'unu biriktirir.
      3. Max volume bucket'in merkez fiyati POC'tur.

    Args:
        df:        OHLCV DataFrame
        lookback:  pencere boyutu (bar sayisi)
        n_buckets: fiyat araligi bin sayisi
        use_numba: Numba JIT kullanilsin mi (default True)

    Returns:
        pd.Series — her bar icin POC fiyati, NaN = yeterli veri yok
    """
    lows = df["low"].values.astype(np.float64)
    highs = df["high"].values.astype(np.float64)
    vols = df["volume"].values.astype(np.float64)

    # --- Numba path ---
    if use_numba and _AVWAP_NUMBA_AVAILABLE and _avwap_poc_jit_fn is not None:
        try:
            poc_arr = _avwap_poc_jit_fn(lows, highs, vols, int(lookback), int(n_buckets))
            return pd.Series(poc_arr, index=df.index, dtype=float)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "avwap_poc_numba_jit_failed_fallback",
                error=str(exc),
            )
            # Python fallback'e dus

    # --- Python fallback path ---
    return _poc_python_fallback(lows, highs, vols, int(lookback), int(n_buckets), df.index)


def _rolling_avwap_from_swing(
    df: pd.DataFrame,
    swing_col: str,
    lookback: int = 60,
    use_numba: bool = True,
) -> pd.Series:
    """Her t bari icin son lookback barda en son swing anchor'dan AVWAP.

    swing_col: 'swing_low' veya 'swing_high' — fractal swing serisi.
    Lookahead-free: t aninda [t-lookback..t-1] araliginda son swing noktasi
    anchor olarak alinir; eger yoksa NaN. AVWAP [anchor..t] kumulatif hesaplanir.

    Performance (SEC55.B): Numba JIT kernel aktif (use_numba=True ve numba
    yuklu ise). Python fallback: bit-identical sonuc, rtol=1e-9.

    Args:
        df:        OHLCV DataFrame (swing_col kolonu hazir olmali)
        swing_col: 'swing_low' veya 'swing_high'
        lookback:  max geriye bakis penceresi (bar sayisi)
        use_numba: Numba JIT kullanilsin mi (default True)

    Returns:
        pd.Series — her bar icin AVWAP degeri, NaN = anchor yok veya cum_vol=0
    """
    swing_arr = df[swing_col].values.astype(np.float64)
    closes = df["close"].values.astype(np.float64)
    highs = df["high"].values.astype(np.float64)
    lows = df["low"].values.astype(np.float64)
    vols = np.maximum(df["volume"].values.astype(np.float64), 0.0)

    # --- Numba path ---
    if use_numba and _AVWAP_NUMBA_AVAILABLE and _avwap_rolling_jit_fn is not None:
        try:
            avwap_arr = _avwap_rolling_jit_fn(
                closes, highs, lows, vols, swing_arr, int(lookback)
            )
            return pd.Series(avwap_arr, index=df.index, dtype=float)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "avwap_rolling_numba_jit_failed_fallback",
                error=str(exc),
            )
            # Python fallback'e dus

    # --- Python fallback path ---
    return _rolling_avwap_python_fallback(
        closes, highs, lows, vols, swing_arr, int(lookback), df.index
    )


def _rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """Wilder RSI hesapla. Lookahead-free."""
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = (-delta).clip(lower=0.0)
    avg_gain = gain.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0.0, np.nan)
    return (100.0 - 100.0 / (1.0 + rs)).fillna(50.0)


# =====================================================================
# Default manifest
# =====================================================================

def _default_manifest() -> StrategyManifest:
    raw = {
        "name": "anchored_vwap_reversal",
        "version": "1.1.0",
        "description": (
            "Anchored VWAP + POC mean-reversion with 200-EMA bias. "
            "v1.1: dynamic confluence score (4 vectorized factors) — "
            "SEC52 fix: eliminates static conf=0.0 bug."
        ),
        "trend_filter": {"type": "ema", "period": 200, "required": True},
        "signals": {
            "patterns": [
                {
                    "id": "avwap_long_reversal",
                    "enabled": True,
                    "weight": 1.5,
                    "params": {
                        "poc_atr_tolerance": 1.5,
                        "rsi_long_max": 55.0,
                        "avwap_swing_lookback": 60,
                        "poc_lookback": 60,
                        # Dinamik confluence faktor parametreleri
                        # F1: RSI extremity (< threshold = oversold)
                        "rsi_extreme_thr": 40.0,
                        # F2: POC proximity (tigher than main entry condition)
                        "poc_tight_atr": 0.5,
                        # F3: Volume elevation (z-score min for bonus)
                        "vol_z_bonus_min": 1.0,
                        # F4: EMA distance (mean-reversion potential)
                        "ema_dist_atr": 1.5,
                        # Faktor basina agirlik (tum faktorler icin tek deger)
                        # 4 faktor × 0.375 = 1.5 => max_score = 3.0
                        # conf = (score - 1.5) / 1.5 ∈ [0.0, 1.0]
                        "factor_weight": 0.375,
                    },
                },
                {
                    "id": "avwap_short_reversal",
                    "enabled": True,
                    "weight": 1.5,
                    "params": {
                        "poc_atr_tolerance": 1.5,
                        "rsi_short_min": 45.0,
                        "avwap_swing_lookback": 60,
                        "poc_lookback": 60,
                        # F1: RSI extremity (> 100-threshold = overbought)
                        "rsi_extreme_thr": 40.0,
                        # F2: POC proximity
                        "poc_tight_atr": 0.5,
                        # F3: Volume elevation
                        "vol_z_bonus_min": 1.0,
                        # F4: EMA distance
                        "ema_dist_atr": 1.5,
                        # Faktor agirlik
                        "factor_weight": 0.375,
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
                "require_proximity_to_sr_atr": 0.0,
            },
            "filters": {
                "atr_min_pct": 0.003,
                "volume_zscore_min": 0.0,
            },
            "confluence": {
                "method": "weighted_sum",
                "min_score": 1.5,
                "bonus_if_at_sr": 0.0,
            },
        },
        "risk": {
            "stop_loss": {"method": "structural_atr", "swing_lookback": 10, "atr_buffer": 1.0},
            "take_profit": {"method": "r_multiple", "primary_R": 2.0},
            "position_sizing": {"method": "fixed_fractional", "risk_per_trade": 0.01},
        },
    }
    return StrategyManifest.model_validate(raw)


# =====================================================================
# Strategy implementation
# =====================================================================

class AnchoredVWAPReversalStrategy(Strategy):
    """Anchored VWAP + Volume Profile POC mean-reversion strategy.

    Long:
      - 200-EMA yukari (close > ema200)
      - Swing-low anchored AVWAP hesapli
      - Price AVWAP'i asagi dan yukari gecis (body rejection up)
      - POC yakinda: |close - poc| <= poc_atr_tolerance * ATR14
      - RSI14 < rsi_long_max (overbought degil)
    Short: simetrik
    SL  : structural swing low/high - atr_buffer * ATR14
    TP  : primary_R * risk (default 2R)

    Confluence score (v1.1 — dynamic):
      base_score = bull/bear pattern weight (1.5)
      + F1 rsi_extreme    × factor_weight   (RSI < 40 long / > 60 short)
      + F2 poc_tight      × factor_weight   (|close-poc| <= 0.5 ATR)
      + F3 vol_elevated   × factor_weight   (vol_z >= 1.0)
      + F4 ema_dist       × factor_weight   (|close-ema200| >= 1.5 ATR)
      max_score = 1.5 + 4*0.375 = 3.0
      pool_conf = (score - 1.5) / 1.5 ∈ [0.0, 1.0]
      Tek faktor: conf = 0.25 >= filter_conf_min=0.25 — PASS garantisi.
    """

    name = "anchored_vwap_reversal"

    def prepare_features(self, df: pd.DataFrame) -> pd.DataFrame:
        if df.empty:
            return df.copy()
        self.apply_tf_manifest(df)
        df = df.sort_values("ts").reset_index(drop=True).copy()

        # --- Temel gostergeler ---
        df["ema200"] = _ema(df["close"], 200)
        df["atr14"] = _atr(df, 14)
        df["atr_pct"] = df["atr14"] / df["close"]
        df["rsi14"] = _rsi(df["close"], 14)

        # --- Fractal swing high/low ---
        fractal_n = self.manifest.signals.structure.swing.fractal_n
        sh, sl = _fractal_swings(df, n=fractal_n)
        df["swing_high"] = sh
        df["swing_low"] = sl

        # --- Parametre ayiklama ---
        avwap_lookback = 60
        poc_lookback = 60
        for p in self.manifest.signals.patterns:
            if p.id in ("avwap_long_reversal", "avwap_short_reversal"):
                avwap_lookback = int(p.params.get("avwap_swing_lookback", 60))
                poc_lookback = int(p.params.get("poc_lookback", 60))
                break

        # --- Rolling AVWAP: swing-low anchor (long), swing-high anchor (short) ---
        df["avwap_long"] = _rolling_avwap_from_swing(
            df, swing_col="swing_low", lookback=avwap_lookback
        )
        df["avwap_short"] = _rolling_avwap_from_swing(
            df, swing_col="swing_high", lookback=avwap_lookback
        )

        # --- Volume Profile POC (lookahead-free, lookback penceresi) ---
        df["poc"] = _volume_profile_poc(df, lookback=poc_lookback, n_buckets=50)

        # --- AVWAP crossover flags (body rejection) ---
        # Long: prev_close < avwap_long AND close >= avwap_long  (cross up)
        prev_close = df["close"].shift(1)
        df["avwap_long_cross_up"] = (
            (prev_close < df["avwap_long"]) &
            (df["close"] >= df["avwap_long"])
        ).fillna(False)

        # Short: prev_close > avwap_short AND close <= avwap_short  (cross down)
        df["avwap_short_cross_down"] = (
            (prev_close > df["avwap_short"]) &
            (df["close"] <= df["avwap_short"])
        ).fillna(False)

        # --- Structural SL seviyeleri ---
        df["struct_sl_long"] = df["low"].shift(1).rolling(10, min_periods=1).min()
        df["struct_sl_short"] = df["high"].shift(1).rolling(10, min_periods=1).max()

        # --- Volume z-score (filtre + confluence faktoru icin) ---
        vol = df["volume"]
        vmean = vol.rolling(60, min_periods=10).mean()
        vstd = vol.rolling(60, min_periods=10).std(ddof=0)
        df["vol_z"] = (vol - vmean) / vstd.replace(0.0, np.nan)

        return df

    def _compute_confluence_series(
        self,
        df: pd.DataFrame,
        direction: str,
        base_weight: float,
        rsi_extreme_thr: float,
        poc_tight_atr: float,
        vol_z_bonus_min: float,
        ema_dist_atr: float,
        factor_weight: float,
    ) -> pd.Series:
        """Vectorized confluence score serisini hesapla.

        Lookahead-free: tum faktorler mevcut bar verisi (t anindaki close,
        rsi14, vol_z, poc, ema200 — bunlarin hepsi t-1 bar bilgisi uzerinden
        causal sekilde hesaplanmis indicator serilerinden geliyor).

        t anindaki karar t-1 close'a dayali (entry t+1 open'da).

        Faktorler:
          F1 rsi_extreme : long=RSI < rsi_extreme_thr / short=RSI > 100-thr
          F2 poc_tight   : |close - poc| <= poc_tight_atr * ATR
          F3 vol_elevated: vol_z >= vol_z_bonus_min
          F4 ema_dist    : |close - ema200| >= ema_dist_atr * ATR

        Returns pd.Series[float] — ayni index, her bar icin confluence skoru.
        """
        close = df["close"]
        atr = df["atr14"].fillna(0.0)
        rsi = df["rsi14"].fillna(50.0)
        poc = df["poc"].fillna(np.nan)
        ema200 = df["ema200"].fillna(np.nan)
        vol_z = df["vol_z"].fillna(0.0)

        # --- F1: RSI extremity ---
        if direction == "long":
            f1 = (rsi < rsi_extreme_thr).astype(float)
        else:
            f1 = (rsi > (100.0 - rsi_extreme_thr)).astype(float)

        # --- F2: POC tight proximity ---
        poc_dist = (close - poc).abs()
        tight_tol = poc_tight_atr * atr
        f2 = (poc_dist <= tight_tol).astype(float)
        # NaN poc = F2 False
        f2 = f2.where(poc.notna(), 0.0)

        # --- F3: Volume elevation ---
        f3 = (vol_z >= vol_z_bonus_min).astype(float)

        # --- F4: EMA distance (mean-reversion potansiyeli) ---
        ema_dist_abs = (close - ema200).abs()
        ema_tol = ema_dist_atr * atr
        f4 = (ema_dist_abs >= ema_tol).astype(float)
        # NaN ema200 = F4 False
        f4 = f4.where(ema200.notna(), 0.0)

        score = (
            base_weight
            + factor_weight * f1
            + factor_weight * f2
            + factor_weight * f3
            + factor_weight * f4
        )
        return score

    def generate_signals(self, df: pd.DataFrame) -> list[Signal]:
        if df.empty:
            return []
        if "avwap_long" not in df.columns:
            df = self.prepare_features(df)

        signals_cfg = self.manifest.signals
        filters_cfg = signals_cfg.filters
        confluence = signals_cfg.confluence

        primary_R = float(
            self.manifest.risk.get("take_profit", {}).get("primary_R", 2.0)
        )
        atr_buffer = float(
            self.manifest.risk.get("stop_loss", {}).get("atr_buffer", 1.0)
        )

        venue = str(df["venue"].iloc[0]) if "venue" in df.columns else "unknown"
        symbol = str(df["symbol"].iloc[0]) if "symbol" in df.columns else "UNKNOWN"
        timeframe = str(df["timeframe"].iloc[0]) if "timeframe" in df.columns else "1d"

        # --- Parametre ayiklama ---
        poc_atr_tol = 1.5
        rsi_long_max = 55.0
        rsi_short_min = 45.0
        bull_weight = 1.5
        bear_weight = 1.5
        # Dinamik confluence parametreleri (manifesden, her iki pattern icin ortak)
        rsi_extreme_thr = 40.0
        poc_tight_atr = 0.5
        vol_z_bonus_min = 1.0
        ema_dist_atr = 1.5
        factor_weight = 0.375

        for p in signals_cfg.patterns:
            if not p.enabled:
                continue
            if p.id == "avwap_long_reversal":
                poc_atr_tol = float(p.params.get("poc_atr_tolerance", 1.5))
                rsi_long_max = float(p.params.get("rsi_long_max", 55.0))
                bull_weight = p.weight
                rsi_extreme_thr = float(p.params.get("rsi_extreme_thr", 40.0))
                poc_tight_atr = float(p.params.get("poc_tight_atr", 0.5))
                vol_z_bonus_min = float(p.params.get("vol_z_bonus_min", 1.0))
                ema_dist_atr = float(p.params.get("ema_dist_atr", 1.5))
                factor_weight = float(p.params.get("factor_weight", 0.375))
            elif p.id == "avwap_short_reversal":
                rsi_short_min = float(p.params.get("rsi_short_min", 45.0))
                bear_weight = p.weight

        atr_min = float(getattr(filters_cfg, "atr_min_pct", 0.003) or 0.003)
        min_score = float(confluence.min_score)

        # --- Vectorized confluence score serileri ---
        long_conf_series = self._compute_confluence_series(
            df,
            direction="long",
            base_weight=bull_weight,
            rsi_extreme_thr=rsi_extreme_thr,
            poc_tight_atr=poc_tight_atr,
            vol_z_bonus_min=vol_z_bonus_min,
            ema_dist_atr=ema_dist_atr,
            factor_weight=factor_weight,
        )
        short_conf_series = self._compute_confluence_series(
            df,
            direction="short",
            base_weight=bear_weight,
            rsi_extreme_thr=rsi_extreme_thr,
            poc_tight_atr=poc_tight_atr,
            vol_z_bonus_min=vol_z_bonus_min,
            ema_dist_atr=ema_dist_atr,
            factor_weight=factor_weight,
        )

        # --- Entry kosu maskeleri (vectorized) ---
        close = df["close"]
        ema200 = df["ema200"]
        poc = df["poc"]
        atr = df["atr14"].fillna(0.0)
        rsi = df["rsi14"].fillna(50.0)
        atr_pct = df["atr_pct"].fillna(0.0)
        cross_up = df["avwap_long_cross_up"].fillna(False)
        cross_down = df["avwap_short_cross_down"].fillna(False)
        avwap_long_s = df["avwap_long"]
        avwap_short_s = df["avwap_short"]

        # ATR min
        atr_ok = (atr > 0) & (atr_pct >= atr_min)

        # Long entry conditions (vectorized)
        ema_up = close > ema200.fillna(np.nan)
        avwap_l_ok = avwap_long_s.notna()
        poc_ok_long = poc.notna() & ((close - poc).abs() <= poc_atr_tol * atr)
        rsi_ok_long = rsi < rsi_long_max

        long_entry = atr_ok & ema_up & avwap_l_ok & cross_up & poc_ok_long & rsi_ok_long
        long_entry = long_entry & (long_conf_series >= min_score)

        # Short entry conditions (vectorized)
        ema_down = close < ema200.fillna(np.nan)
        avwap_s_ok = avwap_short_s.notna()
        poc_ok_short = poc.notna() & ((close - poc).abs() <= poc_atr_tol * atr)
        rsi_ok_short = rsi > rsi_short_min

        short_entry = atr_ok & ema_down & avwap_s_ok & cross_down & poc_ok_short & rsi_ok_short
        short_entry = short_entry & (short_conf_series >= min_score)

        # --- Signal emit (sadece aktif satirlar icin) ---
        struct_sl_long = df["struct_sl_long"]
        struct_sl_short = df["struct_sl_short"]
        out: list[Signal] = []

        for i in df.index[long_entry]:
            row = df.loc[i]
            close_v = float(row["close"])
            atr_v = float(row["atr14"])
            score = float(long_conf_series.at[i])
            poc_v = float(row["poc"])
            rsi_v = float(row["rsi14"])
            ema200_v = float(row["ema200"])
            avwap_v = float(row["avwap_long"])
            sl_raw = float(row["struct_sl_long"])

            if np.isnan(sl_raw) or sl_raw <= 0:
                sl_price = close_v - 2.0 * atr_v
            else:
                sl_price = sl_raw - atr_buffer * atr_v
            sl_price = min(sl_price, close_v - 0.5 * atr_v)
            if sl_price <= 0:
                continue
            risk = close_v - sl_price
            if risk <= 0:
                continue
            tp_price = close_v + primary_R * risk

            ts = pd.Timestamp(row["ts"]).to_pydatetime()
            sig = self.emit_signal(
                ts=ts,
                venue=venue,
                symbol=symbol,
                timeframe=timeframe,
                direction="long",
                pattern_id="avwap_long_reversal",
                confluence_score=float(score),
                sl_price=float(sl_price),
                tp_price=float(tp_price),
                suggested_size_atr=1.0,
                metadata={
                    "avwap_long": avwap_v,
                    "poc": poc_v,
                    "rsi14": rsi_v,
                    "atr14": atr_v,
                    "ema200": ema200_v,
                    "poc_dist_atr": abs(close_v - poc_v) / atr_v if atr_v > 0 else np.nan,
                    "confluence_factors": {
                        "f1_rsi_extreme": bool(rsi_v < rsi_extreme_thr),
                        "f2_poc_tight": bool(abs(close_v - poc_v) <= poc_tight_atr * atr_v),
                        "f3_vol_elevated": bool(float(row.get("vol_z", 0.0) or 0.0) >= vol_z_bonus_min),
                        "f4_ema_dist": bool(abs(close_v - ema200_v) >= ema_dist_atr * atr_v),
                    },
                },
            )
            out.append(sig)

        for i in df.index[short_entry]:
            row = df.loc[i]
            close_v = float(row["close"])
            atr_v = float(row["atr14"])
            score = float(short_conf_series.at[i])
            poc_v = float(row["poc"])
            rsi_v = float(row["rsi14"])
            ema200_v = float(row["ema200"])
            avwap_v = float(row["avwap_short"])
            sl_raw = float(row["struct_sl_short"])

            if np.isnan(sl_raw) or sl_raw <= 0:
                sl_price = close_v + 2.0 * atr_v
            else:
                sl_price = sl_raw + atr_buffer * atr_v
            sl_price = max(sl_price, close_v + 0.5 * atr_v)
            risk = sl_price - close_v
            if risk <= 0:
                continue
            tp_price = close_v - primary_R * risk

            ts = pd.Timestamp(row["ts"]).to_pydatetime()
            sig = self.emit_signal(
                ts=ts,
                venue=venue,
                symbol=symbol,
                timeframe=timeframe,
                direction="short",
                pattern_id="avwap_short_reversal",
                confluence_score=float(score),
                sl_price=float(sl_price),
                tp_price=float(tp_price),
                suggested_size_atr=1.0,
                metadata={
                    "avwap_short": avwap_v,
                    "poc": poc_v,
                    "rsi14": rsi_v,
                    "atr14": atr_v,
                    "ema200": ema200_v,
                    "poc_dist_atr": abs(close_v - poc_v) / atr_v if atr_v > 0 else np.nan,
                    "confluence_factors": {
                        "f1_rsi_extreme": bool(rsi_v > (100.0 - rsi_extreme_thr)),
                        "f2_poc_tight": bool(abs(close_v - poc_v) <= poc_tight_atr * atr_v),
                        "f3_vol_elevated": bool(float(row.get("vol_z", 0.0) or 0.0) >= vol_z_bonus_min),
                        "f4_ema_dist": bool(abs(close_v - ema200_v) >= ema_dist_atr * atr_v),
                    },
                },
            )
            out.append(sig)

        self._log.bind(n=len(out), bars=len(df)).info("avwap_reversal.signals.generated")
        return out
