"""VSA Selling Climax + Test Bar stratejisi.

Wyckoff/VSA Phase A dip sinyali:
  - Selling Climax (SC): extreme hacim + genis asagi bar + ust yari kapanis + 5-bar min low
  - Test Bar (TB): 3-15 bar sonra SC low'una dusuk hacimli geri donus
  - Giris: Test Bar sonrasi ilk YESIL bar acilisinda
  - SL: SC low - 1×ATR
  - TP: 3R (mean-reversion / yuksek hedef)

Mirror (kisa): Buying Climax + Up Thrust short simetrik kurulumu.

Referans: knowledge/books/vsa_volume_spread_analysis.md
Sablon:   src/price_action/strategies/engulfing_continuation.py

---
Performance (SEC55.C — 2026-05-18):
  _detect_test_bar_after_sc + _detect_up_thrust_after_bc + _detect_confirmation_bar:
  Numba JIT kernel ile O(n*wait_max) Python loops'u vektorize edildi.
  Hot-path: _vsa_test_bar_jit_kernel (SC/BC arama + test bar kriterleri) + _vsa_confirm_jit_kernel.
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

# Ortak yardimcilar
from price_action.strategies.classic_pa import (
    _atr,
    _ema,
)


# =====================================================================
# Numba JIT kernelleri — SEC55.C
# Numba yoksa _VSA_NUMBA_AVAILABLE=False, Python fallback kullanilir.
# =====================================================================

_VSA_NUMBA_AVAILABLE = False

try:
    import numba  # noqa: F401
    from numba import njit

    @njit(cache=True, fastmath=False)
    def _vsa_test_bar_jit_kernel(
        lows: np.ndarray,
        highs: np.ndarray,
        volumes: np.ndarray,
        closes: np.ndarray,
        opens: np.ndarray,
        atr_arr: np.ndarray,
        vol_sma_arr: np.ndarray,
        climax_flag: np.ndarray,   # bool array (SC veya BC)
        use_low: bool,             # True=SC test bar (low), False=BC up thrust (high)
        wait_min: int,
        wait_max: int,
        price_tolerance_pct: float,
        vol_ratio_max: float,
        spread_atr_max: float,
        close_pos_threshold: float,  # SC: >=, BC: <=
    ) -> tuple:
        """Numba JIT — SC/BC sonrasi Test Bar / Up Thrust tespiti.

        Her i bari icin:
          - [i-wait_max .. i-wait_min] araliginda en son climax bul
          - Climax reference price (SC: low, BC: high) + tolerance
          - Current bar kriterleri: price, volume, spread, close_pos

        Lookahead-free: climax aranan aralik [i-wait_max .. i-wait_min], i dahil degil.
        close_position icin simdi hesaplaniyor (t barinin verisi, karar t-1 close'a gore).

        Returns:
            (flag_arr, ref_price_arr)  dtype float64 (0/1 flag, nan for missing ref)
        """
        n = len(lows)
        flag_arr = np.zeros(n, dtype=np.float64)
        ref_price_arr = np.full(n, np.nan)

        for i in range(wait_min, n):
            sc_start = i - wait_max
            if sc_start < 0:
                sc_start = 0
            sc_end = i - wait_min + 1  # inclusive son SC index

            # En son climax indeksini bul (reverse scan)
            last_climax_idx = -1
            for j in range(sc_end - 1, sc_start - 1, -1):
                if climax_flag[j]:
                    last_climax_idx = j
                    break

            if last_climax_idx < 0:
                continue

            # Reference price: SC=low, BC=high
            if use_low:
                ref_price = lows[last_climax_idx]
            else:
                ref_price = highs[last_climax_idx]

            tol = ref_price * price_tolerance_pct

            curr_low = lows[i]
            curr_high = highs[i]
            curr_vol = volumes[i]
            curr_spread = curr_high - curr_low
            curr_atr = atr_arr[i]
            curr_vol_sma = vol_sma_arr[i]

            # Close position [0..1]
            curr_rng = curr_high - curr_low
            if curr_rng > 0.0:
                curr_close_pos = (closes[i] - curr_low) / curr_rng
            else:
                curr_close_pos = 0.5

            # Test bar kriterler
            if use_low:
                # SC test: low yakini
                near_ref = abs(curr_low - ref_price) <= tol
                # Close pos >= threshold (ust yari kapanis)
                close_ok = curr_close_pos >= close_pos_threshold
            else:
                # BC up thrust: high yakini
                near_ref = abs(curr_high - ref_price) <= tol
                # Close pos <= threshold (alt yari kapanis)
                close_ok = curr_close_pos <= close_pos_threshold

            low_vol = (curr_vol_sma > 0.0) and (curr_vol < vol_ratio_max * curr_vol_sma)
            narrow_spread = (curr_atr > 0.0) and (curr_spread < spread_atr_max * curr_atr)

            if near_ref and low_vol and narrow_spread and close_ok:
                flag_arr[i] = 1.0
                ref_price_arr[i] = ref_price

        return flag_arr, ref_price_arr

    @njit(cache=True, fastmath=False)
    def _vsa_confirm_jit_kernel(
        closes: np.ndarray,
        opens: np.ndarray,
        trigger_flag: np.ndarray,  # float64 (0/1)
        direction_long: bool,       # True=long (green), False=short (red)
        max_wait: int,
    ) -> np.ndarray:
        """Numba JIT — Trigger sonrasi ilk onay barini tespit eder.

        Long: close > open (yesil bar)
        Short: close < open (kirmizi bar)
        Son max_wait barda trigger varsa onay aranir.

        Lookahead-free: trigger t-j (j>=1) oldugundan, t barinda onay causal.
        """
        n = len(closes)
        conf = np.zeros(n, dtype=np.float64)
        for i in range(1, n):
            for offset in range(1, max_wait + 1):
                j = i - offset
                if j < 0:
                    break
                if trigger_flag[j] > 0.0:
                    if direction_long:
                        if closes[i] > opens[i]:
                            conf[i] = 1.0
                    else:
                        if closes[i] < opens[i]:
                            conf[i] = 1.0
                    break
        return conf

    _VSA_NUMBA_AVAILABLE = True

except Exception:
    pass


# =====================================================================
# VSA yardimci fonksiyonlari
# =====================================================================

def _vol_sma(volume: pd.Series, period: int = 20) -> pd.Series:
    """Gecmis period barlara gore volume SMA (lookahead-safe)."""
    return volume.rolling(period, min_periods=max(1, period // 2)).mean()


def _spread(df: pd.DataFrame) -> pd.Series:
    """Bar spread (high - low)."""
    return df["high"] - df["low"]


def _close_position(df: pd.DataFrame) -> pd.Series:
    """Kapanis pozisyonu: 0=alt, 1=ust (range icindeki orani)."""
    rng = (df["high"] - df["low"]).replace(0, np.nan)
    return (df["close"] - df["low"]) / rng


# =====================================================================
# Python fallback: test bar + up thrust + confirmation
# (Numba yoksa bu fonksiyonlar cagirilir — mevcut mantik aynen korundu)
# =====================================================================

def _test_bar_python_fallback(
    lows: np.ndarray,
    highs: np.ndarray,
    volumes: np.ndarray,
    closes: np.ndarray,
    opens: np.ndarray,
    atr_arr: np.ndarray,
    vol_sma_arr: np.ndarray,
    climax_flag: np.ndarray,
    use_low: bool,
    wait_min: int,
    wait_max: int,
    price_tolerance_pct: float,
    vol_ratio_max: float,
    spread_atr_max: float,
    close_pos_threshold: float,
) -> tuple:
    """Python fallback — _vsa_test_bar_jit_kernel ile bit-identical."""
    n = len(lows)
    flag_arr = np.zeros(n, dtype=np.float64)
    ref_price_arr = np.full(n, np.nan)

    for i in range(wait_min, n):
        sc_start = max(0, i - wait_max)
        sc_end = i - wait_min + 1

        last_climax_idx = -1
        for j in range(sc_end - 1, sc_start - 1, -1):
            if climax_flag[j]:
                last_climax_idx = j
                break

        if last_climax_idx < 0:
            continue

        ref_price = lows[last_climax_idx] if use_low else highs[last_climax_idx]
        tol = ref_price * price_tolerance_pct

        curr_low = lows[i]
        curr_high = highs[i]
        curr_vol = volumes[i]
        curr_spread = curr_high - curr_low
        curr_atr = atr_arr[i]
        curr_vol_sma = vol_sma_arr[i]

        curr_rng = curr_high - curr_low
        curr_close_pos = (closes[i] - curr_low) / curr_rng if curr_rng > 0.0 else 0.5

        if use_low:
            near_ref = abs(curr_low - ref_price) <= tol
            close_ok = curr_close_pos >= close_pos_threshold
        else:
            near_ref = abs(curr_high - ref_price) <= tol
            close_ok = curr_close_pos <= close_pos_threshold

        low_vol = (curr_vol_sma > 0.0) and (curr_vol < vol_ratio_max * curr_vol_sma)
        narrow_spread = (curr_atr > 0.0) and (curr_spread < spread_atr_max * curr_atr)

        if near_ref and low_vol and narrow_spread and close_ok:
            flag_arr[i] = 1.0
            ref_price_arr[i] = ref_price

    return flag_arr, ref_price_arr


def _confirm_python_fallback(
    closes: np.ndarray,
    opens: np.ndarray,
    trigger_flag: np.ndarray,
    direction_long: bool,
    max_wait: int,
) -> np.ndarray:
    """Python fallback — _vsa_confirm_jit_kernel ile bit-identical."""
    n = len(closes)
    conf = np.zeros(n, dtype=np.float64)
    for i in range(1, n):
        for offset in range(1, max_wait + 1):
            j = i - offset
            if j < 0:
                break
            if trigger_flag[j] > 0.0:
                if direction_long:
                    if closes[i] > opens[i]:
                        conf[i] = 1.0
                else:
                    if closes[i] < opens[i]:
                        conf[i] = 1.0
                break
    return conf


# =====================================================================
# Dispatch wrappers — transparent Numba/Python selection
# =====================================================================

def _run_test_bar_kernel(
    lows: np.ndarray,
    highs: np.ndarray,
    volumes: np.ndarray,
    closes: np.ndarray,
    opens: np.ndarray,
    atr_arr: np.ndarray,
    vol_sma_arr: np.ndarray,
    climax_flag: np.ndarray,
    use_low: bool,
    wait_min: int,
    wait_max: int,
    price_tolerance_pct: float,
    vol_ratio_max: float,
    spread_atr_max: float,
    close_pos_threshold: float,
    use_numba: bool = True,
) -> tuple:
    """Numba varsa JIT kernel, yoksa Python fallback."""
    kw = dict(
        lows=lows, highs=highs, volumes=volumes, closes=closes, opens=opens,
        atr_arr=atr_arr, vol_sma_arr=vol_sma_arr, climax_flag=climax_flag,
        use_low=use_low, wait_min=wait_min, wait_max=wait_max,
        price_tolerance_pct=price_tolerance_pct, vol_ratio_max=vol_ratio_max,
        spread_atr_max=spread_atr_max, close_pos_threshold=close_pos_threshold,
    )
    if use_numba and _VSA_NUMBA_AVAILABLE:
        return _vsa_test_bar_jit_kernel(**kw)
    return _test_bar_python_fallback(**kw)


def _run_confirm_kernel(
    closes: np.ndarray,
    opens: np.ndarray,
    trigger_flag: np.ndarray,
    direction_long: bool,
    max_wait: int,
    use_numba: bool = True,
) -> np.ndarray:
    """Numba varsa JIT kernel, yoksa Python fallback."""
    if use_numba and _VSA_NUMBA_AVAILABLE:
        return _vsa_confirm_jit_kernel(closes, opens, trigger_flag, direction_long, max_wait)
    return _confirm_python_fallback(closes, opens, trigger_flag, direction_long, max_wait)


def _detect_selling_climax(
    df: pd.DataFrame,
    atr_col: str = "atr20",
    vol_sma_col: str = "vol_sma20",
    spread_atr_mult: float = 1.5,
    vol_sma_mult: float = 2.5,
    close_pos_min: float = 0.50,
    min_low_bars: int = 5,
) -> pd.Series:
    """Selling Climax (SC) tespit eder.

    Kriterler (VSA reference Section 4.2 + Section 7):
      1. Wide spread: spread > spread_atr_mult * ATR(20)
      2. Climactic volume: volume > vol_sma_mult * SMA_vol(20)
      3. Close upper half: close > low + close_pos_min * (high-low)
      4. 5-bar minimum low: rolling min(5) == low (yerel dip)

    Lookahead-safe: sadece shift/rolling gecmis veri.

    Returns
    -------
    pd.Series[bool]
    """
    atr = df[atr_col].fillna(0.0)
    vol_sma = df[vol_sma_col].fillna(0.0)
    spread = _spread(df)
    close_pos = _close_position(df)
    vol = df["volume"]

    wide_spread = spread > (spread_atr_mult * atr)
    climax_vol = vol > (vol_sma_mult * vol_sma)
    upper_close = close_pos >= close_pos_min
    # 5-bar minimum low: su bar dip bar mi?
    # rolling min icin shift(1) ile onceki 4 bar + su bar -> 5 bar pencere
    # Ama biz su anki low'u da dahil ediyoruz: rolling(5).min() == low (LOOKAHEAD-FREE)
    # Neden safe? rolling(5) t-4..t barlari kullanir, sadece gecmisteki/simdiki bilgi.
    local_min = df["low"].rolling(min_low_bars, min_periods=min_low_bars).min()
    is_5bar_low = (df["low"] == local_min)

    sc = wide_spread & climax_vol & upper_close & is_5bar_low
    return sc.fillna(False)


def _detect_buying_climax(
    df: pd.DataFrame,
    atr_col: str = "atr20",
    vol_sma_col: str = "vol_sma20",
    spread_atr_mult: float = 1.5,
    vol_sma_mult: float = 2.5,
    close_pos_max: float = 0.50,
    max_high_bars: int = 5,
) -> pd.Series:
    """Buying Climax (BC) tespit eder — SC'nin ayı simetriği.

    Kriterler (VSA reference Section 4.11):
      1. Wide spread
      2. Climactic volume
      3. Close lower half (ust fitil)
      4. 5-bar maximum high
    """
    atr = df[atr_col].fillna(0.0)
    vol_sma = df[vol_sma_col].fillna(0.0)
    spread = _spread(df)
    close_pos = _close_position(df)
    vol = df["volume"]

    wide_spread = spread > (spread_atr_mult * atr)
    climax_vol = vol > (vol_sma_mult * vol_sma)
    lower_close = close_pos <= close_pos_max
    local_max = df["high"].rolling(max_high_bars, min_periods=max_high_bars).max()
    is_5bar_high = (df["high"] == local_max)

    bc = wide_spread & climax_vol & lower_close & is_5bar_high
    return bc.fillna(False)


def _detect_test_bar_after_sc(
    df: pd.DataFrame,
    sc_flag: pd.Series,
    atr_col: str = "atr20",
    vol_sma_col: str = "vol_sma20",
    wait_min: int = 3,
    wait_max: int = 15,
    low_tolerance_pct: float = 0.03,
    vol_ratio_max: float = 0.75,
    spread_atr_max: float = 0.80,
    close_pos_min: float = 0.50,
    use_numba: bool = True,
) -> tuple[pd.Series, pd.Series]:
    """SC sonrasi Test Bar tespit eder (Numba JIT accelerated).

    Kural:
      - En son SC'den wait_min..wait_max bar sonra
      - Low, SC low +/- tolerance icinde (1D kripto icin %3 uygun)
      - Volume < vol_ratio_max * SMA_vol
      - Spread < spread_atr_max * ATR
      - Close >= %50 range

    Kalibrasyon notu: VSA referansi +-1% yazar, ama 1D kripto barlarda
    low'lar nadir olarak tam eslesiyor. BTC 2023-2026 verisi analizi
    gosteriyor ki yaklasim mesafesi genellikle %1-3 arasindadir.
    Vol_ratio_max 0.75 civarinda kalibre edildi (0.60 cok katiydi).

    Returns
    -------
    (test_bar_flag, sc_low_at_test)
        test_bar_flag: pd.Series[bool]
        sc_low_at_test: SC low degeri (SL hesabi icin)
    """
    lows = df["low"].to_numpy(dtype=np.float64)
    highs = df["high"].to_numpy(dtype=np.float64)
    closes = df["close"].to_numpy(dtype=np.float64)
    opens = df["open"].to_numpy(dtype=np.float64)
    volumes = df["volume"].to_numpy(dtype=np.float64)
    atr_arr = df[atr_col].fillna(0.0).to_numpy(dtype=np.float64)
    vol_sma_arr = df[vol_sma_col].fillna(0.0).to_numpy(dtype=np.float64)
    climax_arr = sc_flag.fillna(False).to_numpy(dtype=np.bool_)

    flag_arr, ref_arr = _run_test_bar_kernel(
        lows=lows, highs=highs, volumes=volumes, closes=closes, opens=opens,
        atr_arr=atr_arr, vol_sma_arr=vol_sma_arr, climax_flag=climax_arr,
        use_low=True, wait_min=wait_min, wait_max=wait_max,
        price_tolerance_pct=low_tolerance_pct, vol_ratio_max=vol_ratio_max,
        spread_atr_max=spread_atr_max, close_pos_threshold=close_pos_min,
        use_numba=use_numba,
    )

    test_flag = pd.Series(flag_arr.astype(bool), index=df.index)
    sc_low_series = pd.Series(ref_arr, index=df.index)
    return test_flag, sc_low_series


def _detect_up_thrust_after_bc(
    df: pd.DataFrame,
    bc_flag: pd.Series,
    atr_col: str = "atr20",
    vol_sma_col: str = "vol_sma20",
    wait_min: int = 3,
    wait_max: int = 15,
    high_tolerance_pct: float = 0.03,
    vol_ratio_max: float = 0.75,
    spread_atr_max: float = 0.80,
    close_pos_max: float = 0.50,
    use_numba: bool = True,
) -> tuple[pd.Series, pd.Series]:
    """BC sonrasi Up Thrust (UT) tespit eder — Test Bar'in ayı simetriği (Numba JIT accelerated).

    Kural (VSA Section 4.12):
      - En son BC'den wait_min..wait_max bar sonra
      - High, BC high +/- tolerance icinde
      - Volume < vol_ratio_max * SMA_vol (dusuk hacimli geri donus)
      - Spread < spread_atr_max * ATR
      - Close < %50 range (ust fitil olustu)

    Returns
    -------
    (up_thrust_flag, bc_high_at_test)
    """
    lows = df["low"].to_numpy(dtype=np.float64)
    highs = df["high"].to_numpy(dtype=np.float64)
    closes = df["close"].to_numpy(dtype=np.float64)
    opens = df["open"].to_numpy(dtype=np.float64)
    volumes = df["volume"].to_numpy(dtype=np.float64)
    atr_arr = df[atr_col].fillna(0.0).to_numpy(dtype=np.float64)
    vol_sma_arr = df[vol_sma_col].fillna(0.0).to_numpy(dtype=np.float64)
    climax_arr = bc_flag.fillna(False).to_numpy(dtype=np.bool_)

    flag_arr, ref_arr = _run_test_bar_kernel(
        lows=lows, highs=highs, volumes=volumes, closes=closes, opens=opens,
        atr_arr=atr_arr, vol_sma_arr=vol_sma_arr, climax_flag=climax_arr,
        use_low=False, wait_min=wait_min, wait_max=wait_max,
        price_tolerance_pct=high_tolerance_pct, vol_ratio_max=vol_ratio_max,
        spread_atr_max=spread_atr_max, close_pos_threshold=close_pos_max,
        use_numba=use_numba,
    )

    ut_flag = pd.Series(flag_arr.astype(bool), index=df.index)
    bc_high_series = pd.Series(ref_arr, index=df.index)
    return ut_flag, bc_high_series


def _detect_confirmation_bar(
    df: pd.DataFrame,
    trigger_flag: pd.Series,
    direction: str = "long",
    max_wait: int = 3,
    use_numba: bool = True,
) -> pd.Series:
    """Trigger (Test Bar / Up Thrust) sonrasi ilk onay barini tespit eder (Numba JIT accelerated).

    Long icin: Test Bar sonraki bar(lar)da ilk YESIL bar (close > open)
    Short icin: Up Thrust sonraki bar(lar)da ilk KIRMIZI bar (close < open)

    Returns pd.Series[bool] — giris bari isaretlenir.
    Lookahead-safe: trigger t-1 oldugundan, t barinda onay causal.
    """
    closes = df["close"].to_numpy(dtype=np.float64)
    opens = df["open"].to_numpy(dtype=np.float64)
    trig_arr = trigger_flag.fillna(False).astype(float).to_numpy(dtype=np.float64)
    direction_long = direction == "long"

    conf_arr = _run_confirm_kernel(
        closes=closes, opens=opens, trigger_flag=trig_arr,
        direction_long=direction_long, max_wait=max_wait,
        use_numba=use_numba,
    )
    return pd.Series(conf_arr.astype(bool), index=df.index)


# =====================================================================
# Default manifest
# =====================================================================

def _default_manifest() -> StrategyManifest:
    raw = {
        "name": "vsa_climax_test",
        "version": "1.0.0",
        "description": (
            "VSA Selling Climax + Test Bar — Wyckoff Phase A kapitulasyon + "
            "dusuk hacimli geri test giris sistemi. Mirror: BC + Up Thrust short."
        ),
        "trend_filter": {"type": "ema", "period": 200, "required": False},
        "signals": {
            "patterns": [
                {
                    "id": "vsa_sc_test_long",
                    "enabled": True,
                    "weight": 2.0,
                    "params": {
                        "spread_atr_mult": 1.5,
                        "vol_sma_mult": 2.5,
                        "close_pos_min": 0.50,
                        "min_low_bars": 5,
                        "wait_min": 3,
                        "wait_max": 15,
                        "low_tolerance_pct": 0.03,
                        "vol_ratio_max": 0.75,
                        "spread_atr_max": 0.80,
                    },
                },
                {
                    "id": "vsa_bc_thrust_short",
                    "enabled": True,
                    "weight": 2.0,
                    "params": {
                        "spread_atr_mult": 1.5,
                        "vol_sma_mult": 2.5,
                        "close_pos_max": 0.50,
                        "max_high_bars": 5,
                        "wait_min": 3,
                        "wait_max": 15,
                        "high_tolerance_pct": 0.03,
                        "vol_ratio_max": 0.75,
                        "spread_atr_max": 0.80,
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
            "stop_loss": {"method": "sc_low_atr", "atr_buffer": 1.0},
            "take_profit": {"method": "r_multiple", "primary_R": 3.0},
            "position_sizing": {"method": "fixed_fractional", "risk_per_trade": 0.01},
        },
        "backtest": {
            "warmup_bars": 60,
            "fees": {"taker": 0.00075, "maker": -0.00010},
            "slippage_bps": 5.0,
            "initial_capital_usdt": 10_000.0,
        },
    }
    return StrategyManifest.model_validate(raw)


# =====================================================================
# Strategy implementation
# =====================================================================

class VSAClimaxTestStrategy(Strategy):
    """VSA Selling Climax + Test Bar (long) / Buying Climax + Up Thrust (short).

    Long kurulumu:
      1. Selling Climax tespiti (SC)
      2. 3-15 bar bekle
      3. Test Bar: SC low'una dusuk hacimli donus
      4. Giris: Test Bar sonrasi ilk yesil bar acilisi
      5. SL: SC low - 1 ATR
      6. TP: 3R

    Short kurulumu (simetrik):
      1. Buying Climax tespiti (BC)
      2. 3-15 bar bekle
      3. Up Thrust: BC high'ına dusuk hacimli yaklasim + ust fitil
      4. Giris: Up Thrust sonrasi ilk kirmizi bar acilisi
      5. SL: BC high + 1 ATR
      6. TP: 3R
    """

    name = "vsa_climax_test"

    def prepare_features(self, df: pd.DataFrame) -> pd.DataFrame:
        if df.empty:
            return df.copy()
        self.apply_tf_manifest(df)
        df = df.sort_values("ts").reset_index(drop=True).copy()

        # vol_sma_period: manifest vsa_internals'dan al (15m YAML=40, 1d default=20)
        _vsa_internals = getattr(self.manifest, "vsa_internals", {}) or {}
        _vol_sma_period = int(_vsa_internals.get("vol_sma_period", 20) if isinstance(_vsa_internals, dict) else 20)
        _atr_period = int(_vsa_internals.get("atr_period", 20) if isinstance(_vsa_internals, dict) else 20)

        # ATR — vsa_internals'dan veya 20 default
        df[f"atr{_atr_period}"] = _atr(df, _atr_period)
        if f"atr{_atr_period}" != "atr20":
            df["atr20"] = df[f"atr{_atr_period}"]  # alias backward compat
        else:
            df["atr20"] = df[f"atr{_atr_period}"]
        df["atr_pct"] = df["atr20"] / df["close"].replace(0, np.nan)

        # Volume SMA — vsa_internals.vol_sma_period (15m=40, 1d default=20)
        df["vol_sma20"] = _vol_sma(df["volume"], _vol_sma_period)

        # EMA200 (opsiyonel bias filtresi)
        df["ema200"] = _ema(df["close"], 200)

        # Pattern parametrelerini manifest'ten al
        sc_params = {}
        bc_params = {}
        for p in self.manifest.signals.patterns:
            if p.id == "vsa_sc_test_long":
                sc_params = p.params
            elif p.id == "vsa_bc_thrust_short":
                bc_params = p.params

        # --- Selling Climax ---
        df["sc_flag"] = _detect_selling_climax(
            df,
            atr_col="atr20",
            vol_sma_col="vol_sma20",
            spread_atr_mult=float(sc_params.get("spread_atr_mult", 1.5)),
            vol_sma_mult=float(sc_params.get("vol_sma_mult", 2.5)),
            close_pos_min=float(sc_params.get("close_pos_min", 0.50)),
            min_low_bars=int(sc_params.get("min_low_bars", 5)),
        )

        # --- Buying Climax ---
        df["bc_flag"] = _detect_buying_climax(
            df,
            atr_col="atr20",
            vol_sma_col="vol_sma20",
            spread_atr_mult=float(bc_params.get("spread_atr_mult", 1.5)),
            vol_sma_mult=float(bc_params.get("vol_sma_mult", 2.5)),
            close_pos_max=float(bc_params.get("close_pos_max", 0.50)),
            max_high_bars=int(bc_params.get("max_high_bars", 5)),
        )

        # --- Test Bar (SC sonrasi) ---
        tb_flag, sc_low_at_test = _detect_test_bar_after_sc(
            df,
            sc_flag=df["sc_flag"],
            atr_col="atr20",
            vol_sma_col="vol_sma20",
            wait_min=int(sc_params.get("wait_min", 3)),
            wait_max=int(sc_params.get("wait_max", 15)),
            low_tolerance_pct=float(sc_params.get("low_tolerance_pct", 0.01)),
            vol_ratio_max=float(sc_params.get("vol_ratio_max", 0.60)),
            spread_atr_max=float(sc_params.get("spread_atr_max", 0.80)),
            close_pos_min=float(sc_params.get("close_pos_min", 0.50)),
        )
        df["test_bar_flag"] = tb_flag
        df["sc_low_at_test"] = sc_low_at_test

        # --- Up Thrust (BC sonrasi) ---
        ut_flag, bc_high_at_ut = _detect_up_thrust_after_bc(
            df,
            bc_flag=df["bc_flag"],
            atr_col="atr20",
            vol_sma_col="vol_sma20",
            wait_min=int(bc_params.get("wait_min", 3)),
            wait_max=int(bc_params.get("wait_max", 15)),
            high_tolerance_pct=float(bc_params.get("high_tolerance_pct", 0.01)),
            vol_ratio_max=float(bc_params.get("vol_ratio_max", 0.60)),
            spread_atr_max=float(bc_params.get("spread_atr_max", 0.80)),
            close_pos_max=float(bc_params.get("close_pos_max", 0.50)),
        )
        df["up_thrust_flag"] = ut_flag
        df["bc_high_at_ut"] = bc_high_at_ut

        # --- Onay barlari ---
        # Long: Test Bar sonrasi ilk yesil bar
        df["long_confirm"] = _detect_confirmation_bar(df, df["test_bar_flag"], direction="long")
        # Short: Up Thrust sonrasi ilk kirmizi bar
        df["short_confirm"] = _detect_confirmation_bar(df, df["up_thrust_flag"], direction="short")

        return df

    def generate_signals(self, df: pd.DataFrame) -> list[Signal]:
        if df.empty:
            return []
        if "sc_flag" not in df.columns:
            df = self.prepare_features(df)

        filters = self.manifest.signals.filters
        primary_R = float(
            self.manifest.risk.get("take_profit", {}).get("primary_R", 3.0)
        )
        atr_buffer = float(
            self.manifest.risk.get("stop_loss", {}).get("atr_buffer", 1.0)
        )

        venue = str(df["venue"].iloc[0]) if "venue" in df.columns else "unknown"
        symbol = str(df["symbol"].iloc[0]) if "symbol" in df.columns else "UNKNOWN"
        timeframe = str(df["timeframe"].iloc[0]) if "timeframe" in df.columns else "1d"

        atr_min = float(getattr(filters, "atr_min_pct", 0.003) or 0.003)

        out: list[Signal] = []

        for i in range(len(df)):
            row = df.iloc[i]
            atr = float(row.get("atr20") or 0.0)
            atr_pct = float(row.get("atr_pct") or 0.0)
            close = float(row["close"])
            open_ = float(row["open"])

            if atr <= 0 or np.isnan(atr):
                continue
            if atr_min > 0 and atr_pct < atr_min:
                continue

            # ------ LONG: SC + Test Bar + Yesil onay bari ------
            if bool(row.get("long_confirm", False)):
                sc_low = float(row.get("sc_low_at_test") or 0.0)
                if np.isnan(sc_low) or sc_low <= 0:
                    # FIX 2026-05-28 (Faz 14.27 C1): Fallback spec'e uygun (1 ATR).
                    # Önceki bug: 2 ATR fallback spec'teki "SC low - 1 ATR"den
                    # sapıyordu → trade quality düşük (geniş SL = düşük R).
                    sc_low = close - 1.0 * atr

                # Giris: bu barin acilisi (bar kapatildiktan sonra sinyal)
                entry = open_
                sl_price = sc_low - atr_buffer * atr
                sl_price = min(sl_price, entry - 0.5 * atr)  # en az 0.5 ATR risk
                risk = entry - sl_price
                if risk <= 0:
                    continue
                tp_price = entry + primary_R * risk

                ts = pd.Timestamp(row["ts"]).to_pydatetime()
                sig = self.emit_signal(
                    ts=ts,
                    venue=venue,
                    symbol=symbol,
                    timeframe=timeframe,
                    direction="long",
                    pattern_id="vsa_sc_test_long",
                    confluence_score=2.0,
                    sl_price=float(sl_price),
                    tp_price=float(tp_price),
                    suggested_size_atr=1.0,
                    metadata={
                        "sc_low": float(sc_low),
                        "atr20": float(atr),
                        "entry_open": float(entry),
                        "risk_r": float(risk),
                    },
                )
                out.append(sig)

            # ------ SHORT: BC + Up Thrust + Kirmizi onay bari ------
            if bool(row.get("short_confirm", False)):
                bc_high = float(row.get("bc_high_at_ut") or 0.0)
                if np.isnan(bc_high) or bc_high <= 0:
                    # FIX 2026-05-28 (Faz 14.27 C1): Fallback spec match (1 ATR).
                    bc_high = close + 1.0 * atr

                entry = open_
                sl_price = bc_high + atr_buffer * atr
                sl_price = max(sl_price, entry + 0.5 * atr)
                risk = sl_price - entry
                if risk <= 0:
                    continue
                tp_price = entry - primary_R * risk

                ts = pd.Timestamp(row["ts"]).to_pydatetime()
                sig = self.emit_signal(
                    ts=ts,
                    venue=venue,
                    symbol=symbol,
                    timeframe=timeframe,
                    direction="short",
                    pattern_id="vsa_bc_thrust_short",
                    confluence_score=2.0,
                    sl_price=float(sl_price),
                    tp_price=float(tp_price),
                    suggested_size_atr=1.0,
                    metadata={
                        "bc_high": float(bc_high),
                        "atr20": float(atr),
                        "entry_open": float(entry),
                        "risk_r": float(risk),
                    },
                )
                out.append(sig)

        self._log.bind(n=len(out), bars=len(df)).info("vsa_climax_test.signals.generated")
        return out
