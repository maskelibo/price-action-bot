"""HYP-NEW-1: VSA Stopping Volume + Wyckoff Spring + Structural Higher-Low (Trap Reversal).

Strateji: Wyckoff Phase C Spring'in tek-bar VSA imzasini (climactic volume + narrow body
+ upper-half close after wick puncture) bir structural multi-test HL icinde yakalayarak
stop-hunt sonrasi kurumsal absorpsiyonu mekanik olarak avlar.

Mekanik kurallar (Long — Spring):
  1. HL Context    : Son 60 barda en az 2 swing low birbirine +-2% yakinlikta (multi-test bottom)
  2. Spring bar    : Bar low < min(2 prior swing lows) — immediate reclaim same bar
                     (close > swing_low_level)
  3. VSA stopping  : Spring bar volume > 2.0*SMA(20) (panik kapitulasyon)
                     AND close > low + 0.6*(high-low)  (ust %40 kapanis)
                     AND |close-open| < 0.4*(high-low)  (dar govde, effort>>result)
  4. Confirmation  : Sonraki bar bullish (close > Spring bar open)
  5. Entry         : Confirmation bar sonraki acilis (long)
  6. SL            : Spring low - 0.5*ATR(14)
  7. TP            : 3R (Wyckoff Phase D LPS hedef)

Mirror (Short — UTAD):
  Yukarida ozetlenen tum kurallarin tam tersi: coklu testten olusan EQH (equal highs)
  + UTAD bar (high > EQH level, close < EQH level) + VSA stopping volume (upper half)
  + dar govde + bearish onay bari => kisa pozisyon.

Orijinal Wyckoff Phase D'dan farki:
  - Phase D: Spring + SOS (confirmation) => daha gec giris (Phase D sonunda)
  - Bu strateji: Phase C Spring'i VSA imzasiyla yakaliyor (daha erken giris)
  - Ek filtre: multi-test HL context => Spring'in "gercek" oldugunu garanti eder
  - VSA stopping volume: dart govde + ust kapanis => effort>>result absorpsiyon imzasi
  - Sonuc: Daha siki kural seti, daha az ama daha kaliteli sinyaller
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from price_action.contracts import Signal
from price_action.logging_config import logger
from price_action.strategies.base import Strategy, StrategyManifest

# Reuse shared helpers from classic_pa
from price_action.strategies.classic_pa import (
    _atr,
    _ema,
    _kaufman_efficiency_ratio,
)


# =====================================================================
# Yardimci fonksiyonlar
# =====================================================================

def _vol_sma(volume: pd.Series, window: int = 20) -> pd.Series:
    """Rolling volume SMA (lookahead-free)."""
    return volume.rolling(window, min_periods=max(5, window // 4)).mean()


def _detect_swing_lows(
    df: pd.DataFrame,
    fractal_n: int = 5,
    lookback: int = 60,
) -> pd.Series:
    """Fractal swing low tespiti (lookahead-free).

    Fractal n=5: bar[i] swing low ise low[i] <= min(low[i-n:i] + low[i+1:i+n+1])
    Lookahead: bar i'nin swing low oldugunu i+n'den sonra bilebiliriz.
    Bu nedenle swing_low_confirmed[i+n] = True seklinde shift ederiz.

    Dondurur: Her index icin o noktada bilinen son 2 confirmed swing low'un
    ortalama seviyeleri ve bireysel degerleri. Yani lookback penceresi icindeki
    swing lowlardan yararlanilir.
    """
    lows = df["low"].to_numpy()
    n = len(df)

    # Fractal swing low tespiti
    swing_low_flags = np.zeros(n, dtype=bool)
    swing_low_vals = np.full(n, np.nan)

    for i in range(fractal_n, n - fractal_n):
        center_low = lows[i]
        left_ok = all(center_low <= lows[i - k] for k in range(1, fractal_n + 1))
        right_ok = all(center_low <= lows[i + k] for k in range(1, fractal_n + 1))
        if left_ok and right_ok:
            # Confirmed at i+fractal_n (right side complete)
            confirm_idx = i + fractal_n
            if confirm_idx < n:
                swing_low_flags[confirm_idx] = True
                swing_low_vals[confirm_idx] = center_low

    return (
        pd.Series(swing_low_flags, index=df.index, name="sw_low_flag"),
        pd.Series(swing_low_vals, index=df.index, name="sw_low_val"),
    )


def _detect_hl_context(
    df: pd.DataFrame,
    sw_low_flags: pd.Series,
    sw_low_vals: pd.Series,
    lookback: int = 60,
    tolerance_pct: float = 0.02,
    min_swing_lows: int = 2,
) -> pd.Series:
    """Multi-test HL context dedektoru.

    Son lookback barda en az 2 swing low birbirine +-tolerance_pct
    yakinlikta ise HL context True.

    Yaklasim: Sliding window icindeki onaylanan swing low'lari topla,
    herhangi iki tanesinin mutlak fark / ortalama <= tolerance_pct ise True.

    Dondurur: Boolean pd.Series (HL context aktif mi).
    """
    flags = sw_low_flags.to_numpy()
    vals = sw_low_vals.to_numpy()
    n = len(df)
    hl_context = np.zeros(n, dtype=bool)

    for t in range(lookback, n):
        # Son lookback barda swing lowlari topla
        window_vals = []
        for j in range(max(0, t - lookback), t):
            if flags[j] and not np.isnan(vals[j]):
                window_vals.append(vals[j])

        if len(window_vals) < min_swing_lows:
            continue

        # Herhangi 2 swing low birbirine yakin mi?
        found = False
        for a in range(len(window_vals)):
            for b in range(a + 1, len(window_vals)):
                va, vb = window_vals[a], window_vals[b]
                avg = (va + vb) / 2.0
                if avg > 0 and abs(va - vb) / avg <= tolerance_pct:
                    found = True
                    break
            if found:
                break
        hl_context[t] = found

    return pd.Series(hl_context, index=df.index, name="hl_context")


def _get_prior_swing_low_level(
    sw_low_flags: pd.Series,
    sw_low_vals: pd.Series,
    lookback: int = 60,
) -> pd.Series:
    """Son lookback barda bilinen en dusuk 2 swing low'un minimumunu dondurur.

    Bu, Spring bar'in altina inmesi gereken seviyedir.
    Lookahead-free: her t icin sadece [0..t-1] swing low'lara bakilir.
    """
    flags = sw_low_flags.to_numpy()
    vals = sw_low_vals.to_numpy()
    n = len(sw_low_flags)
    prior_min = np.full(n, np.nan)

    for t in range(lookback, n):
        window_vals = []
        for j in range(max(0, t - lookback), t):
            if flags[j] and not np.isnan(vals[j]):
                window_vals.append(vals[j])

        if len(window_vals) >= 2:
            # En kucuk 2 swing low'un minimumu
            sorted_vals = sorted(window_vals)
            prior_min[t] = sorted_vals[0]  # absolute minimum
        elif len(window_vals) == 1:
            prior_min[t] = window_vals[0]

    return pd.Series(prior_min, index=sw_low_flags.index, name="prior_sw_low_min")


def _detect_spring_vsa(
    df: pd.DataFrame,
    hl_context: pd.Series,
    prior_sw_low_min: pd.Series,
    vol_sma: pd.Series,
    atr14: pd.Series,
    vol_mult: float = 2.0,
    close_pos_min: float = 0.60,
    body_ratio_max: float = 0.40,
    atr_depth_max: float = 1.0,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Spring + VSA stopping volume tespiti (tek bar, t barinda).

    Kural (lookahead-free, t barinda tum veriler biliniyor):
      - HL context aktif
      - low[t] < prior_sw_low_min (penetrasyon)
      - low[t] > prior_sw_low_min - atr_depth_max * ATR(14)  (cok derin degil)
      - close[t] > prior_sw_low_min  (SAME BAR RECLAIM)
      - volume[t] > vol_mult * vol_sma20
      - close[t] > low[t] + close_pos_min * (high[t]-low[t])  (ust %40 kapanis)
      - |close[t]-open[t]| < body_ratio_max * (high[t]-low[t])  (dar govde)

    Dondurur: spring_flag (bool Series), spring_low_series (Spring bar low),
              confirmation_open (Spring bar open, onay bari icin referans).
    """
    lows = df["low"].to_numpy()
    highs = df["high"].to_numpy()
    opens = df["open"].to_numpy()
    closes = df["close"].to_numpy()
    volumes = df["volume"].to_numpy()
    vsma = vol_sma.to_numpy()
    atr = atr14.to_numpy()
    hl_ctx = hl_context.to_numpy()
    prior_min = prior_sw_low_min.to_numpy()
    n = len(df)

    spring_flags = np.zeros(n, dtype=bool)
    spring_low_arr = np.full(n, np.nan)
    spring_open_arr = np.full(n, np.nan)

    for t in range(1, n):
        # HL context aktif olmali
        if not hl_ctx[t]:
            continue

        pm = prior_min[t]
        if np.isnan(pm) or pm <= 0:
            continue

        atr_t = atr[t]
        if np.isnan(atr_t) or atr_t <= 0:
            continue

        vsma_t = vsma[t]
        if np.isnan(vsma_t) or vsma_t <= 0:
            continue

        low_t = lows[t]
        high_t = highs[t]
        open_t = opens[t]
        close_t = closes[t]
        vol_t = volumes[t]
        bar_range = high_t - low_t

        if bar_range <= 0:
            continue

        # 1. Penetrasyon: low < prior swing low min
        if low_t >= pm:
            continue

        # 2. Derinlik: cok derin degil (< atr_depth_max * ATR)
        if (pm - low_t) > atr_depth_max * atr_t:
            continue

        # 3. Same-bar reclaim: close > prior_sw_low_min
        if close_t <= pm:
            continue

        # 4. VSA stopping volume: volume > vol_mult * vol_sma20
        if vol_t < vol_mult * vsma_t:
            continue

        # 5. Ust kapanis: close > low + close_pos_min * range
        if close_t < low_t + close_pos_min * bar_range:
            continue

        # 6. Dar govde (effort >> result): |close-open| < body_ratio_max * range
        body = abs(close_t - open_t)
        if body >= body_ratio_max * bar_range:
            continue

        # Tum kriterler saglandi — Spring + VSA imzasi
        spring_flags[t] = True
        spring_low_arr[t] = low_t
        spring_open_arr[t] = open_t

    return (
        pd.Series(spring_flags, index=df.index, name="spring_vsa_flag"),
        pd.Series(spring_low_arr, index=df.index, name="spring_vsa_low"),
        pd.Series(spring_open_arr, index=df.index, name="spring_vsa_open"),
    )


def _detect_confirmation_bar(
    df: pd.DataFrame,
    spring_flags: pd.Series,
    spring_open_arr: pd.Series,
) -> pd.Series:
    """Onay bari tespiti: Spring'i takip eden bar bullish mi?

    t+1 barinda: close[t+1] > open[t] (Spring bar open'i asiyorsa bullish konfirmasyon).

    Dondurur: confirmation_flag (bool Series) — sinyal EMIT edilecek bar.
    Sinyal t+1 barinda emit edilir; engine t+2 acilisinda long girer.
    """
    opens_arr = df["open"].to_numpy()
    closes_arr = df["close"].to_numpy()
    sflags = spring_flags.to_numpy()
    s_opens = spring_open_arr.to_numpy()
    n = len(df)

    confirm_flags = np.zeros(n, dtype=bool)
    confirm_spring_low = np.full(n, np.nan)
    confirm_spring_open = np.full(n, np.nan)

    for t in range(n - 1):
        if not sflags[t]:
            continue
        # t+1 bari bullish mi?
        t1 = t + 1
        if t1 >= n:
            break
        spring_open = s_opens[t]
        if np.isnan(spring_open):
            continue
        if closes_arr[t1] > spring_open:
            confirm_flags[t1] = True
            confirm_spring_low[t1] = df["low"].iloc[t]  # Spring bar low
            confirm_spring_open[t1] = spring_open

    return (
        pd.Series(confirm_flags, index=df.index, name="spring_vsa_confirm"),
        pd.Series(confirm_spring_low, index=df.index, name="spring_vsa_sl_ref"),
    )


def _detect_utad_vsa(
    df: pd.DataFrame,
    sw_high_flags: pd.Series,
    sw_high_vals: pd.Series,
    vol_sma: pd.Series,
    atr14: pd.Series,
    lookback: int = 60,
    tolerance_pct: float = 0.02,
    vol_mult: float = 2.0,
    close_pos_max: float = 0.40,
    body_ratio_max: float = 0.40,
    atr_depth_max: float = 1.0,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """UTAD + VSA stopping volume tespiti (kisa taraf mirror).

    Spring'in tam tersi: coklu EQH (equal highs) + UTAD bar penetrasyonu + same-bar reclaim
    + VSA stopping volume + dar govde + alt %40 kapanis.
    """
    highs = df["high"].to_numpy()
    lows = df["low"].to_numpy()
    opens = df["open"].to_numpy()
    closes = df["close"].to_numpy()
    volumes = df["volume"].to_numpy()
    vsma = vol_sma.to_numpy()
    atr = atr14.to_numpy()
    shigh_flags = sw_high_flags.to_numpy()
    shigh_vals = sw_high_vals.to_numpy()
    n = len(df)

    # EQH context: son lookback barda en az 2 swing high birbirine yakin
    eqh_context = np.zeros(n, dtype=bool)
    prior_max = np.full(n, np.nan)

    for t in range(lookback, n):
        window_vals = []
        for j in range(max(0, t - lookback), t):
            if shigh_flags[j] and not np.isnan(shigh_vals[j]):
                window_vals.append(shigh_vals[j])

        if len(window_vals) >= 2:
            # EQH context
            found = False
            for a in range(len(window_vals)):
                for b in range(a + 1, len(window_vals)):
                    va, vb = window_vals[a], window_vals[b]
                    avg = (va + vb) / 2.0
                    if avg > 0 and abs(va - vb) / avg <= tolerance_pct:
                        found = True
                        break
                if found:
                    break
            eqh_context[t] = found
            sorted_vals = sorted(window_vals, reverse=True)
            prior_max[t] = sorted_vals[0]  # maximum of swing highs

    utad_flags = np.zeros(n, dtype=bool)
    utad_high_arr = np.full(n, np.nan)
    utad_open_arr = np.full(n, np.nan)

    for t in range(1, n):
        if not eqh_context[t]:
            continue

        pm = prior_max[t]
        if np.isnan(pm) or pm <= 0:
            continue

        atr_t = atr[t]
        if np.isnan(atr_t) or atr_t <= 0:
            continue

        vsma_t = vsma[t]
        if np.isnan(vsma_t) or vsma_t <= 0:
            continue

        high_t = highs[t]
        low_t = lows[t]
        open_t = opens[t]
        close_t = closes[t]
        vol_t = volumes[t]
        bar_range = high_t - low_t

        if bar_range <= 0:
            continue

        # 1. Penetrasyon: high > prior EQH max
        if high_t <= pm:
            continue

        # 2. Derinlik filtresi
        if (high_t - pm) > atr_depth_max * atr_t:
            continue

        # 3. Same-bar reclaim: close < prior EQH max
        if close_t >= pm:
            continue

        # 4. VSA stopping volume
        if vol_t < vol_mult * vsma_t:
            continue

        # 5. Alt kapanis: close < low + (1 - close_pos_max) * range => close in lower 40%
        if close_t > low_t + (1.0 - close_pos_max) * bar_range:
            continue

        # 6. Dar govde
        body = abs(close_t - open_t)
        if body >= body_ratio_max * bar_range:
            continue

        utad_flags[t] = True
        utad_high_arr[t] = high_t
        utad_open_arr[t] = open_t

    # Confirmation bar for UTAD: t+1 bearish (close < UTAD bar open)
    utad_confirm = np.zeros(n, dtype=bool)
    utad_confirm_hl_ref = np.full(n, np.nan)

    for t in range(n - 1):
        if not utad_flags[t]:
            continue
        t1 = t + 1
        if t1 >= n:
            break
        utad_open = utad_open_arr[t]
        if np.isnan(utad_open):
            continue
        if closes[t1] < utad_open:
            utad_confirm[t1] = True
            utad_confirm_hl_ref[t1] = highs[t]  # UTAD bar high => SL reference

    return (
        pd.Series(utad_confirm, index=df.index, name="utad_vsa_confirm"),
        pd.Series(utad_confirm_hl_ref, index=df.index, name="utad_vsa_sl_ref"),
        pd.Series(prior_max, index=df.index, name="prior_sw_high_max"),
    )


def _detect_swing_highs(
    df: pd.DataFrame,
    fractal_n: int = 5,
) -> tuple[pd.Series, pd.Series]:
    """Fractal swing high tespiti (lookahead-free, confirms at i+fractal_n)."""
    highs = df["high"].to_numpy()
    n = len(df)

    swing_high_flags = np.zeros(n, dtype=bool)
    swing_high_vals = np.full(n, np.nan)

    for i in range(fractal_n, n - fractal_n):
        center_high = highs[i]
        left_ok = all(center_high >= highs[i - k] for k in range(1, fractal_n + 1))
        right_ok = all(center_high >= highs[i + k] for k in range(1, fractal_n + 1))
        if left_ok and right_ok:
            confirm_idx = i + fractal_n
            if confirm_idx < n:
                swing_high_flags[confirm_idx] = True
                swing_high_vals[confirm_idx] = center_high

    return (
        pd.Series(swing_high_flags, index=df.index, name="sw_high_flag"),
        pd.Series(swing_high_vals, index=df.index, name="sw_high_val"),
    )


# =====================================================================
# Default manifest
# =====================================================================

def _default_manifest() -> StrategyManifest:
    raw = {
        "name": "wyckoff_spring_vsa",
        "version": "1.0.0",
        "description": (
            "HYP-NEW-1: VSA Stopping Volume + Wyckoff Spring + Structural HL — "
            "Phase C Spring'i VSA imzasiyla yakalar (multi-test bottom context)"
        ),
        "trend_filter": {"type": "ema", "period": 200, "required": False},
        "signals": {
            "patterns": [
                {
                    "id": "spring_vsa_long",
                    "enabled": True,
                    "weight": 3.0,
                    "params": {
                        "fractal_n": 5,            # Swing low/high tespiti icin fractal
                        "hl_lookback": 60,         # Multi-test HL arama penceresi
                        "hl_tolerance_pct": 0.02,  # Swing lowlar arasi yakinlik toleransi (%2)
                        "min_swing_lows": 2,       # En az 2 swing low gerekli
                        "vol_sma_window": 20,      # VSA hacim SMA penceresi
                        "vol_mult": 2.0,           # Volume > 2.0x SMA (stopping volume)
                        "close_pos_min": 0.60,     # Kapanis en az %60 bar range'inden yukari
                        "body_ratio_max": 0.40,    # Govde < %40 bar range (dar govde)
                        "atr_depth_max": 1.0,      # Penetrasyon derinligi < 1.0 ATR
                        "sl_atr_buffer": 0.5,      # SL = Spring low - 0.5 ATR
                    },
                },
                {
                    "id": "utad_vsa_short",
                    "enabled": True,
                    "weight": 3.0,
                    "params": {
                        "fractal_n": 5,
                        "eqh_lookback": 60,
                        "eqh_tolerance_pct": 0.02,
                        "vol_mult": 2.0,
                        "close_pos_max": 0.40,     # Kapanis en fazla %40 yukari (alt kapanis)
                        "body_ratio_max": 0.40,
                        "atr_depth_max": 1.0,
                        "sl_atr_buffer": 0.5,      # SL = UTAD high + 0.5 ATR
                    },
                },
            ],
            "structure": {
                "swing": {"fractal_n": 5},
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
                "kaufman_er_period": 14,
                "kaufman_er_min": 0.0,
            },
            "confluence": {
                "method": "weighted_sum",
                "min_score": 2.5,
                "bonus_if_at_sr": 0.0,
            },
        },
        "risk": {
            "stop_loss": {"method": "structural", "atr_buffer": 0.5},
            "take_profit": {"method": "r_multiple", "primary_R": 3.0},
            "position_sizing": {"method": "fixed_fractional", "risk_per_trade": 0.01},
        },
        "backtest": {
            "warmup_bars": 80,
            "fees": {"taker": 0.00075, "maker": -0.00010},
            "slippage_bps": 5.0,
            "initial_capital_usdt": 10_000.0,
        },
    }
    return StrategyManifest.model_validate(raw)


# =====================================================================
# Strategy implementation
# =====================================================================

class WyckoffSpringVSAStrategy(Strategy):
    """HYP-NEW-1: VSA Stopping Volume + Wyckoff Spring + Structural HL.

    Uzun taraf  : Multi-test HL + Spring bar (VSA stopping volume imzasi)
                  + bullish confirmation bar => LONG entry at next open
    Kisa taraf  : Multi-test EQH + UTAD bar (VSA stopping volume imzasi)
                  + bearish confirmation bar => SHORT entry at next open
    Giriş       : Confirmation bar'in ardindan gelen bar'in ACILININDA
    Stop        : Spring low - 0.5*ATR  /  UTAD high + 0.5*ATR
    Hedef       : 3R

    Wyckoff Phase D (onceki strateji)'dan farki:
      - Phase D Spring + SOS: 2-event zinciri, daha gec (Phase D sonunda) giris
      - Bu strateji: Phase C Spring'in VSA imzasini + HL context ile yakaliyor
      - Ek kural: dar govde (effort>>result absorpsiyon imzasi)
      - Ek kural: same-bar reclaim (ani eli alimlar)
      - Ek kural: onay bari close > Spring open (gecikme bir bar azaltildi)
    """

    name = "wyckoff_spring_vsa"

    def prepare_features(self, df: pd.DataFrame) -> pd.DataFrame:
        if df.empty:
            return df.copy()
        df = df.sort_values("ts").reset_index(drop=True).copy()

        # --- Temel indikatörler ---
        df["ema50"] = _ema(df["close"], 50)
        df["ema200"] = _ema(df["close"], 200)
        df["atr14"] = _atr(df, 14)
        df["atr_pct"] = df["atr14"] / df["close"]

        # Kaufman ER
        filters_cfg = self.manifest.signals.filters
        er_period = int(getattr(filters_cfg, "kaufman_er_period", 14) or 14)
        df["kaufman_er"] = _kaufman_efficiency_ratio(df["close"], period=er_period)

        # Pattern parametreleri
        long_params = {}
        short_params = {}
        for p in self.manifest.signals.patterns:
            if p.id == "spring_vsa_long":
                long_params = p.params
            elif p.id == "utad_vsa_short":
                short_params = p.params

        fractal_n = int(long_params.get("fractal_n", 5))
        hl_lookback = int(long_params.get("hl_lookback", 60))
        hl_tol = float(long_params.get("hl_tolerance_pct", 0.02))
        min_swing_lows = int(long_params.get("min_swing_lows", 2))
        vol_sma_window = int(long_params.get("vol_sma_window", 20))
        vol_mult = float(long_params.get("vol_mult", 2.0))
        close_pos_min = float(long_params.get("close_pos_min", 0.60))
        body_ratio_max = float(long_params.get("body_ratio_max", 0.40))
        atr_depth_max = float(long_params.get("atr_depth_max", 1.0))

        # VSA hacim SMA
        df["vol_sma20"] = _vol_sma(df["volume"], window=vol_sma_window)

        # --- Long taraf (Spring) ---
        sw_low_flags, sw_low_vals = _detect_swing_lows(df, fractal_n=fractal_n, lookback=hl_lookback)
        df["sw_low_flag"] = sw_low_flags
        df["sw_low_val"] = sw_low_vals

        hl_ctx = _detect_hl_context(
            df, sw_low_flags, sw_low_vals,
            lookback=hl_lookback, tolerance_pct=hl_tol, min_swing_lows=min_swing_lows,
        )
        df["hl_context"] = hl_ctx

        prior_sw_min = _get_prior_swing_low_level(sw_low_flags, sw_low_vals, lookback=hl_lookback)
        df["prior_sw_low_min"] = prior_sw_min

        spring_flags, spring_lows, spring_opens = _detect_spring_vsa(
            df,
            hl_context=hl_ctx,
            prior_sw_low_min=prior_sw_min,
            vol_sma=df["vol_sma20"],
            atr14=df["atr14"],
            vol_mult=vol_mult,
            close_pos_min=close_pos_min,
            body_ratio_max=body_ratio_max,
            atr_depth_max=atr_depth_max,
        )
        df["spring_vsa_flag"] = spring_flags
        df["spring_vsa_low"] = spring_lows
        df["spring_vsa_open"] = spring_opens

        confirm_flags, confirm_sl_refs = _detect_confirmation_bar(
            df, spring_flags, spring_opens,
        )
        df["spring_vsa_confirm"] = confirm_flags
        df["spring_vsa_sl_ref"] = confirm_sl_refs

        # --- Short taraf (UTAD) ---
        sw_high_flags, sw_high_vals = _detect_swing_highs(df, fractal_n=fractal_n)
        df["sw_high_flag"] = sw_high_flags
        df["sw_high_val"] = sw_high_vals

        eqh_lookback = int(short_params.get("eqh_lookback", 60))
        eqh_tol = float(short_params.get("eqh_tolerance_pct", 0.02))
        short_vol_mult = float(short_params.get("vol_mult", 2.0))
        close_pos_max = float(short_params.get("close_pos_max", 0.40))
        short_body_max = float(short_params.get("body_ratio_max", 0.40))
        short_atr_depth = float(short_params.get("atr_depth_max", 1.0))

        utad_confirm, utad_sl_ref, prior_sw_high_max = _detect_utad_vsa(
            df,
            sw_high_flags, sw_high_vals,
            vol_sma=df["vol_sma20"],
            atr14=df["atr14"],
            lookback=eqh_lookback,
            tolerance_pct=eqh_tol,
            vol_mult=short_vol_mult,
            close_pos_max=close_pos_max,
            body_ratio_max=short_body_max,
            atr_depth_max=short_atr_depth,
        )
        df["utad_vsa_confirm"] = utad_confirm
        df["utad_vsa_sl_ref"] = utad_sl_ref
        df["prior_sw_high_max"] = prior_sw_high_max

        return df

    def generate_signals(self, df: pd.DataFrame) -> list[Signal]:
        if df.empty:
            return []
        if "spring_vsa_confirm" not in df.columns:
            df = self.prepare_features(df)

        filters_cfg = self.manifest.signals.filters
        risk_cfg = self.manifest.risk

        primary_R = float(risk_cfg.get("take_profit", {}).get("primary_R", 3.0))
        sl_atr_buf = float(risk_cfg.get("stop_loss", {}).get("atr_buffer", 0.5))
        atr_min_pct = float(getattr(filters_cfg, "atr_min_pct", 0.003) or 0.0)

        # Long params
        long_params = {}
        short_params = {}
        for p in self.manifest.signals.patterns:
            if p.id == "spring_vsa_long":
                long_params = p.params
                long_weight = p.weight
            elif p.id == "utad_vsa_short":
                short_params = p.params
                short_weight = p.weight

        long_sl_buf = float(long_params.get("sl_atr_buffer", sl_atr_buf))
        short_sl_buf = float(short_params.get("sl_atr_buffer", sl_atr_buf))

        venue = str(df["venue"].iloc[0]) if "venue" in df.columns else "unknown"
        symbol = str(df["symbol"].iloc[0]) if "symbol" in df.columns else "UNKNOWN"
        timeframe = str(df["timeframe"].iloc[0]) if "timeframe" in df.columns else "1d"

        closes = df["close"].to_numpy()
        opens = df["open"].to_numpy()
        atr = df["atr14"].to_numpy()
        atr_pct = df["atr_pct"].to_numpy()
        kaufman_er = df["kaufman_er"].to_numpy()
        ema200 = df["ema200"].to_numpy()
        spring_confirm = df["spring_vsa_confirm"].to_numpy()
        spring_sl_ref = df["spring_vsa_sl_ref"].to_numpy()
        utad_confirm = df["utad_vsa_confirm"].to_numpy()
        utad_sl_ref = df["utad_vsa_sl_ref"].to_numpy()
        prior_sw_high_max = df["prior_sw_high_max"].to_numpy()
        hl_ctx = df["hl_context"].to_numpy()

        n = len(df)
        out: list[Signal] = []

        for i in range(n):
            row = df.iloc[i]
            close = float(closes[i])
            atr_i = float(atr[i])
            if atr_i <= 0 or np.isnan(atr_i):
                continue
            if atr_min_pct > 0 and float(atr_pct[i]) < atr_min_pct:
                continue

            ts = pd.Timestamp(row["ts"]).to_pydatetime()

            # --- LONG: Spring VSA confirmation ---
            # Sinyal confirmation bar'inda emit edilir, engine sonraki acilista girer
            if spring_confirm[i]:
                sl_ref = float(spring_sl_ref[i])
                if np.isnan(sl_ref) or sl_ref <= 0:
                    # Fallback
                    sl_ref = close - 2.0 * atr_i
                sl_price = sl_ref - long_sl_buf * atr_i
                sl_price = min(sl_price, close - 0.5 * atr_i)  # en az 0.5 ATR uzakta
                risk = close - sl_price
                if risk <= 0:
                    continue
                tp_price = close + primary_R * risk

                sig = self.emit_signal(
                    ts=ts,
                    venue=venue,
                    symbol=symbol,
                    timeframe=timeframe,
                    direction="long",
                    pattern_id="spring_vsa_long",
                    confluence_score=float(getattr(
                        next((p for p in self.manifest.signals.patterns if p.id == "spring_vsa_long"), None),
                        "weight", 3.0,
                    )),
                    sl_price=float(sl_price),
                    tp_price=float(tp_price),
                    suggested_size_atr=1.0,
                    metadata={
                        "spring_low": sl_ref,
                        "hl_context": bool(hl_ctx[i]),
                        "atr14": atr_i,
                        "ema200": float(ema200[i]) if not np.isnan(ema200[i]) else 0.0,
                        "kaufman_er": float(kaufman_er[i]) if not np.isnan(kaufman_er[i]) else 0.0,
                        "close": close,
                        "r_ratio": primary_R,
                    },
                )
                out.append(sig)

            # --- SHORT: UTAD VSA confirmation ---
            if utad_confirm[i]:
                sl_ref = float(utad_sl_ref[i])
                if np.isnan(sl_ref) or sl_ref <= 0:
                    sl_ref = close + 2.0 * atr_i
                sl_price = sl_ref + short_sl_buf * atr_i
                sl_price = max(sl_price, close + 0.5 * atr_i)
                risk = sl_price - close
                if risk <= 0:
                    continue
                tp_price = close - primary_R * risk

                sig = self.emit_signal(
                    ts=ts,
                    venue=venue,
                    symbol=symbol,
                    timeframe=timeframe,
                    direction="short",
                    pattern_id="utad_vsa_short",
                    confluence_score=float(getattr(
                        next((p for p in self.manifest.signals.patterns if p.id == "utad_vsa_short"), None),
                        "weight", 3.0,
                    )),
                    sl_price=float(sl_price),
                    tp_price=float(tp_price),
                    suggested_size_atr=1.0,
                    metadata={
                        "utad_high": sl_ref,
                        "prior_sw_high_max": float(prior_sw_high_max[i]) if not np.isnan(prior_sw_high_max[i]) else 0.0,
                        "atr14": atr_i,
                        "ema200": float(ema200[i]) if not np.isnan(ema200[i]) else 0.0,
                        "close": close,
                        "r_ratio": primary_R,
                    },
                )
                out.append(sig)

        self._log.bind(n=len(out), bars=len(df)).info("wyckoff_spring_vsa.signals.generated")
        return out
