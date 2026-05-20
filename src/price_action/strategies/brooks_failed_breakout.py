"""Brooks Failed Breakout / Trap stratejisi.

Brooks "En Guvenilir Reversal" — Failed BO/Trap Mekanizması:
  - N-bar high/low seviyesi kırılır ama follow-through gelmez.
  - 1-3 bar içinde fiyat level'ın karşı tarafına döner → trap.
  - "Two-sided momentum": trapped retailler + reversal oyuncular.

Kural özeti (SHORT taraf — bull trap):
  1. Breakout bar: high > rolling_N_bar_high (shift(1) → önceki N bar max)
     VE close > shift(1) rolling_N_bar_high (güçlü BO kapanışı)
  2. Failure confirmation: sonraki 1-3 bar içinde close < rolling_N_bar_high
     (level altına kapanış — failed BO onayı)
  3. Giriş: failure bar açılışı (close < level → short entry at open)
  4. SL: breakout bar'ın swing high + sl_atr_factor * ATR
  5. TP: 2R birincil; OR range_center (konservative)

LONG taraf (bear trap) ayna kuralları.

Bağlam filtresi:
  - ATR min PCT (volatil olmayan barlarda sinyal yok)
  - Kaufman ER < er_max_trend (çok güçlü trend'de reversal düşük olasılık)
  - Volume Z-score opsiyonel (breakout bar'da yüksek volume = tuzak olasılığı artar)

Referans: brooks_deep_catalog.md §"Failed Breakout / Trap — En Güvenilir Reversal"
          Edge iddiası: %65-75 win rate, 2-3:1 R:R, EV ~+0.8-1.5R

---
Performance (SEC55.C — 2026-05-18):
  _failed_breakout_flags icindeki O(n*max_bars_to_fail) nested loops Numba JIT ile
  port edildi. BO detection + failure scan tek kernel'da birlestirildi.
  Fallback: numba yoksa Python path (mevcut mantik), no crash.
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

# Paylasilan yardimcilar
from price_action.strategies.classic_pa import (
    _atr,
    _ema,
    _kaufman_efficiency_ratio,
)


# =====================================================================
# Numba JIT kernel — SEC55.C
# =====================================================================

_BROOKS_NUMBA_AVAILABLE = False

try:
    import numba  # noqa: F401
    from numba import njit

    @njit(cache=True, fastmath=False)
    def _failed_bo_jit_kernel(
        closes: np.ndarray,
        highs: np.ndarray,
        lows: np.ndarray,
        nb_high: np.ndarray,
        nb_low: np.ndarray,
        max_bars_to_fail: int,
    ) -> tuple:
        """Numba JIT — BO detection + failure scan tek geciste.

        Bull BO: high > nb_high AND close > nb_high (require_close_beyond=True hardcoded parity)
        Bear BO: low < nb_low  AND close < nb_low

        Failure (bull BO -> short):
          [i-max_bars..i-1]'de bull BO varsa ve bu barda close < nb_high_at_BO
        Failure (bear BO -> long):
          [i-max_bars..i-1]'de bear BO varsa ve bu barda close > nb_low_at_BO

        Lookahead-free: nb_high/nb_low zaten shift(1).rolling().max/min ile hesaplanmis.
        BO bar'i dahil i bari exclude: range(1, max_bars+1) -> bo_idx = i-k (k>=1).

        Returns:
            (bull_failed, bear_failed, bull_extreme, bear_extreme)
            dtype: float64 (0/1 flag, nan for missing extreme)
        """
        n = len(closes)
        bull_failed = np.zeros(n, dtype=np.float64)
        bear_failed = np.zeros(n, dtype=np.float64)
        bull_extreme = np.full(n, np.nan)
        bear_extreme = np.full(n, np.nan)

        # BO bar'larini onceden hesapla (O(n) pass)
        bull_bo_arr = np.zeros(n, dtype=np.float64)
        bear_bo_arr = np.zeros(n, dtype=np.float64)
        for i in range(n):
            nh = nb_high[i]
            nl = nb_low[i]
            if np.isnan(nh) or np.isnan(nl):
                continue
            if highs[i] > nh and closes[i] > nh:
                bull_bo_arr[i] = 1.0
            if lows[i] < nl and closes[i] < nl:
                bear_bo_arr[i] = 1.0

        # Failure scan: her i icin son 1..max_bars_to_fail barda BO ara
        for i in range(1, n):
            # Bull BO -> Short setup
            for k in range(1, max_bars_to_fail + 1):
                bo_idx = i - k
                if bo_idx < 0:
                    break
                if bull_bo_arr[bo_idx] > 0.0:
                    level = nb_high[bo_idx]
                    if not np.isnan(level) and closes[i] < level:
                        bull_failed[i] = 1.0
                        bull_extreme[i] = highs[bo_idx]
                    break  # En yakin BO bar yeterli

            # Bear BO -> Long setup
            for k in range(1, max_bars_to_fail + 1):
                bo_idx = i - k
                if bo_idx < 0:
                    break
                if bear_bo_arr[bo_idx] > 0.0:
                    level = nb_low[bo_idx]
                    if not np.isnan(level) and closes[i] > level:
                        bear_failed[i] = 1.0
                        bear_extreme[i] = lows[bo_idx]
                    break

        return bull_failed, bear_failed, bull_extreme, bear_extreme

    _BROOKS_NUMBA_AVAILABLE = True

except Exception:
    pass


# =====================================================================
# Python fallback
# =====================================================================

def _failed_bo_python_fallback(
    closes: np.ndarray,
    highs: np.ndarray,
    lows: np.ndarray,
    nb_high: np.ndarray,
    nb_low: np.ndarray,
    max_bars_to_fail: int,
) -> tuple:
    """Python fallback — _failed_bo_jit_kernel ile bit-identical."""
    n = len(closes)
    bull_failed = np.zeros(n, dtype=np.float64)
    bear_failed = np.zeros(n, dtype=np.float64)
    bull_extreme = np.full(n, np.nan)
    bear_extreme = np.full(n, np.nan)

    bull_bo_arr = np.zeros(n, dtype=np.float64)
    bear_bo_arr = np.zeros(n, dtype=np.float64)
    for i in range(n):
        nh = nb_high[i]
        nl = nb_low[i]
        if np.isnan(nh) or np.isnan(nl):
            continue
        if highs[i] > nh and closes[i] > nh:
            bull_bo_arr[i] = 1.0
        if lows[i] < nl and closes[i] < nl:
            bear_bo_arr[i] = 1.0

    for i in range(1, n):
        for k in range(1, max_bars_to_fail + 1):
            bo_idx = i - k
            if bo_idx < 0:
                break
            if bull_bo_arr[bo_idx] > 0.0:
                level = nb_high[bo_idx]
                if not np.isnan(level) and closes[i] < level:
                    bull_failed[i] = 1.0
                    bull_extreme[i] = highs[bo_idx]
                break

        for k in range(1, max_bars_to_fail + 1):
            bo_idx = i - k
            if bo_idx < 0:
                break
            if bear_bo_arr[bo_idx] > 0.0:
                level = nb_low[bo_idx]
                if not np.isnan(level) and closes[i] > level:
                    bear_failed[i] = 1.0
                    bear_extreme[i] = lows[bo_idx]
                break

    return bull_failed, bear_failed, bull_extreme, bear_extreme


def _run_failed_bo_kernel(
    closes: np.ndarray,
    highs: np.ndarray,
    lows: np.ndarray,
    nb_high: np.ndarray,
    nb_low: np.ndarray,
    max_bars_to_fail: int,
    use_numba: bool = True,
) -> tuple:
    """Numba varsa JIT kernel, yoksa Python fallback."""
    if use_numba and _BROOKS_NUMBA_AVAILABLE:
        return _failed_bo_jit_kernel(closes, highs, lows, nb_high, nb_low, max_bars_to_fail)
    return _failed_bo_python_fallback(closes, highs, lows, nb_high, nb_low, max_bars_to_fail)


# =====================================================================
# Strateji yardimcilari
# =====================================================================

def _rolling_n_bar_high(df: pd.DataFrame, period: int = 20) -> pd.Series:
    """Önceki N bar'ın en yüksek high'ı (lookahead-free).

    Bar t için [t-period .. t-1] aralığını kullanır (shift(1) + rolling).
    Bu Donchian kanalının high kısmıyla aynı mantık.
    """
    return df["high"].shift(1).rolling(period, min_periods=period).max()


def _rolling_n_bar_low(df: pd.DataFrame, period: int = 20) -> pd.Series:
    """Önceki N bar'ın en düşük low'u (lookahead-free)."""
    return df["low"].shift(1).rolling(period, min_periods=period).min()


def _breakout_bar_flag(
    df: pd.DataFrame,
    n_bar_high: pd.Series,
    n_bar_low: pd.Series,
    require_close_beyond: bool = True,
) -> tuple[pd.Series, pd.Series]:
    """Breakout bar tespiti.

    Bull BO bar: high > prev_N_high VE (opsiyonel) close > prev_N_high
    Bear BO bar: low  < prev_N_low  VE (opsiyonel) close < prev_N_low

    Brooks'a göre: close beyond level = daha güçlü sinyal; sadece wick = zayıf.
    require_close_beyond=True ile sadece close-beyond kabul edilir.

    Returns:
        (bull_bo_bar, bear_bo_bar) — ikisi de pd.Series[bool]
    """
    high = df["high"]
    low = df["low"]
    close = df["close"]

    if require_close_beyond:
        bull_bo = (high > n_bar_high) & (close > n_bar_high)
        bear_bo = (low < n_bar_low) & (close < n_bar_low)
    else:
        bull_bo = high > n_bar_high
        bear_bo = low < n_bar_low

    return bull_bo.fillna(False), bear_bo.fillna(False)


def _failed_breakout_flags(
    df: pd.DataFrame,
    n_bar_high: pd.Series,
    n_bar_low: pd.Series,
    max_bars_to_fail: int = 3,
    use_numba: bool = True,
) -> tuple[pd.Series, pd.Series, pd.Series, pd.Series]:
    """Failed breakout (trap) tespiti — Numba JIT accelerated.

    Logic (SHORT / bull trap):
      Bar B:     bull breakout (high > N_high, close > N_high)
      Bar B+1..B+max_bars_to_fail: close < N_high at time B → failed

    Bu fonksiyon her bar için "bu bar önceki 1..max_bars_to_fail barlardan
    birinde bull BO gerçekleşti ve ŞİMDİ close < o barın N_high seviyesinin
    altına indi mi?" sorusunu cevaplar.

    Returns:
        (bull_failed_flag, bear_failed_flag,
         bull_bo_extreme, bear_bo_extreme)
        bull_failed_flag[i] = True  → SHORT entry bar (bear trap failed)
        bear_failed_flag[i] = True  → LONG entry bar (bull trap failed)
        bull_bo_extreme[i] = failed BO barındaki swing high (SL baz)
        bear_bo_extreme[i] = failed BO barındaki swing low  (SL baz)

    Lookahead-free: sadece geçmişe bakar (shift + rolling mantığı).
    """
    closes = df["close"].to_numpy(dtype=np.float64)
    highs = df["high"].to_numpy(dtype=np.float64)
    lows = df["low"].to_numpy(dtype=np.float64)
    nb_high_arr = n_bar_high.to_numpy(dtype=np.float64)
    nb_low_arr = n_bar_low.to_numpy(dtype=np.float64)

    bull_f, bear_f, bull_ext, bear_ext = _run_failed_bo_kernel(
        closes=closes, highs=highs, lows=lows,
        nb_high=nb_high_arr, nb_low=nb_low_arr,
        max_bars_to_fail=max_bars_to_fail,
        use_numba=use_numba,
    )

    return (
        pd.Series(bull_f.astype(bool), index=df.index, name="bull_trap_short"),
        pd.Series(bear_f.astype(bool), index=df.index, name="bear_trap_long"),
        pd.Series(bull_ext, index=df.index, name="bull_bo_extreme"),
        pd.Series(bear_ext, index=df.index, name="bear_bo_extreme"),
    )


def _range_center(df: pd.DataFrame, period: int = 20) -> pd.Series:
    """N bar range'inin merkezi (hedef için).

    center = (rolling_high + rolling_low) / 2  (shift(1) tabanlı, lookahead-free)
    """
    rh = df["high"].shift(1).rolling(period, min_periods=period).max()
    rl = df["low"].shift(1).rolling(period, min_periods=period).min()
    return (rh + rl) / 2.0


# =====================================================================
# Default manifest
# =====================================================================

def _default_manifest() -> StrategyManifest:
    raw = {
        "name": "brooks_failed_breakout",
        "version": "1.0.0",
        "description": (
            "Brooks Failed Breakout / Trap — N-bar high/low kırılım başarısız, "
            "reversal. %65-75 win rate, 2-3:1 R:R."
        ),
        "trend_filter": {"type": "none", "period": 0, "required": False},
        "signals": {
            "patterns": [
                {
                    "id": "bull_trap_short",
                    "enabled": True,
                    "weight": 2.0,
                    "params": {
                        "lookback_period": 20,
                        "max_bars_to_fail": 3,
                        "require_close_beyond": True,
                        "sl_atr_factor": 0.5,
                        "tp_method": "r_multiple",    # "r_multiple" or "range_center"
                        "primary_R": 2.0,
                    },
                },
                {
                    "id": "bear_trap_long",
                    "enabled": True,
                    "weight": 2.0,
                    "params": {
                        "lookback_period": 20,
                        "max_bars_to_fail": 3,
                        "require_close_beyond": True,
                        "sl_atr_factor": 0.5,
                        "tp_method": "r_multiple",
                        "primary_R": 2.0,
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
                "atr_min_pct": 0.005,
                "volume_zscore_min": 0.0,
                "kaufman_er_period": 14,
                "kaufman_er_max_trend": 0.85,  # çok güçlü trend'de reversal alma
            },
            "confluence": {
                "method": "weighted_sum",
                "min_score": 2.0,
                "bonus_if_at_sr": 0.0,
            },
        },
        "risk": {
            "stop_loss": {"method": "swing_extreme_plus_atr", "atr_factor": 0.5},
            "take_profit": {"method": "r_multiple", "primary_R": 2.0},
            "position_sizing": {"method": "fixed_fractional", "risk_per_trade": 0.01},
        },
    }
    return StrategyManifest.model_validate(raw)


# =====================================================================
# Strategy implementation
# =====================================================================

class BrooksFailedBreakoutStrategy(Strategy):
    """Brooks Failed Breakout / Trap Reversal.

    SHORT (bull trap):
      - N-bar high kırılır (close > N_high)
      - 1-3 bar içinde close < N_high (failure)
      - Entry: failure bar açılışı (short)
      - SL: bull BO bar'ının swing high + 0.5 * ATR
      - TP: 2R

    LONG (bear trap):
      - N-bar low kırılır (close < N_low)
      - 1-3 bar içinde close > N_low (failure)
      - Entry: failure bar açılışı (long)
      - SL: bear BO bar'ının swing low - 0.5 * ATR
      - TP: 2R
    """

    name = "brooks_failed_breakout"

    def prepare_features(self, df: pd.DataFrame) -> pd.DataFrame:
        if df.empty:
            return df.copy()
        self.apply_tf_manifest(df)
        df = df.sort_values("ts").reset_index(drop=True).copy()

        # Parametreler — manifest'ten al
        lookback = 20
        max_fail_bars = 3
        require_close_beyond = True
        for p in self.manifest.signals.patterns:
            if p.id in ("bull_trap_short", "bear_trap_long"):
                lookback = int(p.params.get("lookback_period", 20))
                max_fail_bars = int(p.params.get("max_bars_to_fail", 3))
                require_close_beyond = bool(p.params.get("require_close_beyond", True))
                break

        # ATR
        df["atr14"] = _atr(df, 14)
        df["atr_pct"] = df["atr14"] / df["close"]

        # EMA (bağlam için)
        df["ema20"] = _ema(df["close"], 20)
        df["ema50"] = _ema(df["close"], 50)

        # Rolling N-bar high/low (lookahead-free)
        nb_high = _rolling_n_bar_high(df, period=lookback)
        nb_low = _rolling_n_bar_low(df, period=lookback)
        df[f"rolling_{lookback}b_high"] = nb_high
        df[f"rolling_{lookback}b_low"] = nb_low

        # Breakout flags
        bull_bo, bear_bo = _breakout_bar_flag(
            df, nb_high, nb_low, require_close_beyond=require_close_beyond
        )
        df["bull_bo_bar"] = bull_bo
        df["bear_bo_bar"] = bear_bo

        # Failed breakout flags + extremes (SL baz)
        bull_fail, bear_fail, bull_ext, bear_ext = _failed_breakout_flags(
            df, nb_high, nb_low, max_bars_to_fail=max_fail_bars
        )
        df["bull_trap_short"] = bull_fail   # SHORT signal
        df["bear_trap_long"] = bear_fail    # LONG signal
        df["bull_bo_extreme"] = bull_ext    # BO bar swing high → SL for short
        df["bear_bo_extreme"] = bear_ext    # BO bar swing low  → SL for long

        # Range center (TP alternative)
        df["range_center"] = _range_center(df, period=lookback)

        # Kaufman ER (trend filtresi)
        er_period = int(getattr(self.manifest.signals.filters, "kaufman_er_period", 14) or 14)
        df["kaufman_er"] = _kaufman_efficiency_ratio(df["close"], period=er_period)

        # Volume z-score
        vol = df["volume"]
        vmean = vol.rolling(60, min_periods=10).mean()
        vstd = vol.rolling(60, min_periods=10).std(ddof=0)
        df["vol_z"] = (vol - vmean) / vstd.replace(0, np.nan)

        return df

    def generate_signals(self, df: pd.DataFrame) -> list[Signal]:
        if df.empty:
            return []

        # Feature kontrolü
        if "bull_trap_short" not in df.columns:
            df = self.prepare_features(df)

        filters = self.manifest.signals.filters
        confluence = self.manifest.signals.confluence

        # Parametreler
        lookback = 20
        sl_atr_factor = 0.5
        primary_R = 2.0
        tp_method = "r_multiple"
        for p in self.manifest.signals.patterns:
            if p.id in ("bull_trap_short", "bear_trap_long"):
                lookback = int(p.params.get("lookback_period", 20))
                sl_atr_factor = float(p.params.get("sl_atr_factor", 0.5))
                primary_R = float(p.params.get("primary_R", 2.0))
                tp_method = str(p.params.get("tp_method", "r_multiple"))
                break

        # Override from risk manifest
        primary_R = float(
            self.manifest.risk.get("take_profit", {}).get("primary_R", primary_R)
        )

        atr_min = float(getattr(filters, "atr_min_pct", 0.005) or 0.005)
        vol_min = float(getattr(filters, "volume_zscore_min", 0.0) or 0.0)
        er_max = float(getattr(filters, "kaufman_er_max_trend", 1.0) or 1.0)
        min_score = float(confluence.min_score)

        # Pattern weights
        short_weight = 2.0
        long_weight = 2.0
        for p in self.manifest.signals.patterns:
            if not p.enabled:
                continue
            if p.id == "bull_trap_short":
                short_weight = p.weight
            elif p.id == "bear_trap_long":
                long_weight = p.weight

        nb_high_col = f"rolling_{lookback}b_high"
        nb_low_col = f"rolling_{lookback}b_low"

        venue = str(df["venue"].iloc[0]) if "venue" in df.columns else "unknown"
        symbol = str(df["symbol"].iloc[0]) if "symbol" in df.columns else "UNKNOWN"
        timeframe = str(df["timeframe"].iloc[0]) if "timeframe" in df.columns else "1d"

        out: list[Signal] = []

        for i in range(len(df)):
            row = df.iloc[i]
            close = float(row["close"])
            atr = float(row.get("atr14") or 0.0)

            if atr <= 0 or np.isnan(atr):
                continue

            # ATR min filtresi
            atr_pct = float(row.get("atr_pct") or 0.0)
            if atr_min > 0 and atr_pct < atr_min:
                continue

            # Volume filtresi
            vol_z = float(row.get("vol_z") or 0.0)
            if vol_min > 0 and (np.isnan(vol_z) or vol_z < vol_min):
                continue

            # Kaufman ER trend filtresi (çok güçlü trend = reversal alma)
            er = float(row.get("kaufman_er") or 0.0)
            if er_max < 1.0 and er > er_max:
                continue

            # --- SHORT: bull trap (bull BO başarısız → short) ---
            if bool(row.get("bull_trap_short", False)):
                score = short_weight
                if score < min_score:
                    continue

                # SL: BO bar'ının swing high + sl_atr_factor * ATR
                bo_extreme = float(row.get("bull_bo_extreme") or np.nan)
                if np.isnan(bo_extreme):
                    bo_extreme = close + 2.0 * atr
                sl_price = bo_extreme + sl_atr_factor * atr
                # Ensure SL above close (short trade)
                sl_price = max(sl_price, close + 0.5 * atr)

                risk = sl_price - close
                if risk <= 0:
                    continue

                # TP hesapla
                if tp_method == "range_center":
                    rc = float(row.get("range_center") or np.nan)
                    if not np.isnan(rc) and rc < close:
                        tp_price = rc
                    else:
                        tp_price = close - primary_R * risk
                else:
                    tp_price = close - primary_R * risk

                if tp_price >= close:
                    continue

                ts = pd.Timestamp(row["ts"]).to_pydatetime()
                sig = self.emit_signal(
                    ts=ts,
                    venue=venue,
                    symbol=symbol,
                    timeframe=timeframe,
                    direction="short",
                    pattern_id="bull_trap_short",
                    confluence_score=float(score),
                    sl_price=float(sl_price),
                    tp_price=float(tp_price),
                    suggested_size_atr=1.0,
                    metadata={
                        "atr14": atr,
                        "bo_extreme": float(bo_extreme),
                        "kaufman_er": er,
                        nb_high_col: float(row.get(nb_high_col) or np.nan),
                        "tp_method": tp_method,
                    },
                )
                out.append(sig)

            # --- LONG: bear trap (bear BO başarısız → long) ---
            if bool(row.get("bear_trap_long", False)):
                score = long_weight
                if score < min_score:
                    continue

                # SL: BO bar'ının swing low - sl_atr_factor * ATR
                bo_extreme = float(row.get("bear_bo_extreme") or np.nan)
                if np.isnan(bo_extreme):
                    bo_extreme = close - 2.0 * atr
                sl_price = bo_extreme - sl_atr_factor * atr
                # Ensure SL below close (long trade)
                sl_price = min(sl_price, close - 0.5 * atr)

                risk = close - sl_price
                if risk <= 0:
                    continue

                # TP hesapla
                if tp_method == "range_center":
                    rc = float(row.get("range_center") or np.nan)
                    if not np.isnan(rc) and rc > close:
                        tp_price = rc
                    else:
                        tp_price = close + primary_R * risk
                else:
                    tp_price = close + primary_R * risk

                if tp_price <= close:
                    continue

                ts = pd.Timestamp(row["ts"]).to_pydatetime()
                sig = self.emit_signal(
                    ts=ts,
                    venue=venue,
                    symbol=symbol,
                    timeframe=timeframe,
                    direction="long",
                    pattern_id="bear_trap_long",
                    confluence_score=float(score),
                    sl_price=float(sl_price),
                    tp_price=float(tp_price),
                    suggested_size_atr=1.0,
                    metadata={
                        "atr14": atr,
                        "bo_extreme": float(bo_extreme),
                        "kaufman_er": er,
                        nb_low_col: float(row.get(nb_low_col) or np.nan),
                        "tp_method": tp_method,
                    },
                )
                out.append(sig)

        self._log.bind(n=len(out), bars=len(df)).info("brooks_failed_bo.signals.generated")
        return out
