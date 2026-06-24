"""Equal Highs / Lows Sweep + Immediate Reversal stratejisi (SMC stop-hunt).

Konsept (H-2 hipotezi):
  - Equal highs (EQH): Son `lookback_bars` içinde en az 2 swing high birbirine
    ±0.15 ATR yakınlıkta → likidite havuzu.
  - Sweep bar: high > equal_highs_max VE close < equal_highs_max (aynı bar reclaim).
  - Reversal: sweep bar'ın kendisi veya sonraki 1-3 bar içinde close < pool_level.
  - Entry SHORT: reversal bar açılışı (sinyal bar kapanışında next-bar-open).
  - SL: sweep bar high + 0.5 ATR.
  - TP: 2.5R.
  - Mirror (LONG): Equal Lows sweep + bullish reversal.

Mekanik kural — lookahead-free (sweep kararı bar kapanışında verilir).
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from price_action.contracts import Signal
from price_action.logging_config import logger
from price_action.strategies.base import Strategy, StrategyManifest
from price_action.strategies.classic_pa import _atr, _ema, _fractal_swings


# =====================================================================
# Yardımcılar
# =====================================================================

def _detect_equal_highs(
    df: pd.DataFrame,
    lookback: int = 30,
    tolerance_atr: float = 0.15,
    n_fractal: int = 3,
) -> tuple[pd.Series, pd.Series]:
    """EQH ve EQL havuz seviyelerini bar-by-bar hesapla (lookahead-free).

    Dönüş:
        eqh_level : pd.Series  — geçerli bar için aktif EQH pool max (NaN = yok)
        eql_level : pd.Series  — geçerli bar için aktif EQL pool min (NaN = yok)
    """
    n = len(df)
    highs = df["high"].to_numpy(dtype=float)
    lows  = df["low"].to_numpy(dtype=float)
    atrs  = df["atr14"].to_numpy(dtype=float)

    sh_flags, sl_flags = _fractal_swings(df, n=n_fractal)
    sh_arr = sh_flags.to_numpy()
    sl_arr = sl_flags.to_numpy()

    eqh_level = np.full(n, np.nan)
    eql_level = np.full(n, np.nan)

    for t in range(lookback, n):
        atr_t = atrs[t]
        if np.isnan(atr_t) or atr_t <= 0:
            continue
        tol = atr_t * tolerance_atr

        # Taranan pencere: [t-lookback .. t-1]  (bar t henüz kapanmamış sayılır)
        window_start = max(0, t - lookback)

        # Swing high'lar (t-n_fractal'a kadar confirmed)
        sh_indices = [
            i for i in range(window_start, t - n_fractal + 1)
            if sh_arr[i]
        ]
        if len(sh_indices) >= 2:
            sh_prices = highs[sh_indices]
            # Tüm eşleşen çiftleri kontrol et
            found_eqh = False
            eqh_max = -np.inf
            for j in range(len(sh_prices)):
                for k in range(j + 1, len(sh_prices)):
                    if abs(sh_prices[j] - sh_prices[k]) <= tol:
                        found_eqh = True
                        eqh_max = max(eqh_max, sh_prices[j], sh_prices[k])
            if found_eqh:
                eqh_level[t] = eqh_max

        # Swing low'lar
        sl_indices = [
            i for i in range(window_start, t - n_fractal + 1)
            if sl_arr[i]
        ]
        if len(sl_indices) >= 2:
            sl_prices = lows[sl_indices]
            found_eql = False
            eql_min = np.inf
            for j in range(len(sl_prices)):
                for k in range(j + 1, len(sl_prices)):
                    if abs(sl_prices[j] - sl_prices[k]) <= tol:
                        found_eql = True
                        eql_min = min(eql_min, sl_prices[j], sl_prices[k])
            if found_eql:
                eql_level[t] = eql_min

    return pd.Series(eqh_level, index=df.index), pd.Series(eql_level, index=df.index)


# =====================================================================
# Default manifest
# =====================================================================

def _default_manifest() -> StrategyManifest:
    raw = {
        "name": "equal_highs_sweep",
        "version": "1.0.0",
        "description": (
            "SMC stop-hunt: Equal highs/lows sweep + immediate reversal. "
            "Short on EQH sweep, Long on EQL sweep."
        ),
        "trend_filter": {"type": "ema", "period": 50, "required": False},
        "signals": {
            "patterns": [
                {
                    "id": "eqh_sweep_short",
                    "enabled": True,
                    "weight": 2.0,
                    "params": {
                        "lookback_bars": 30,
                        "tolerance_atr": 0.15,
                        "fractal_n": 3,
                        "reversal_window": 3,
                        "sl_atr_mult": 0.5,
                        "tp_r_multiple": 2.5,
                    },
                },
                {
                    "id": "eql_sweep_long",
                    "enabled": True,
                    "weight": 2.0,
                    "params": {
                        "lookback_bars": 30,
                        "tolerance_atr": 0.15,
                        "fractal_n": 3,
                        "reversal_window": 3,
                        "sl_atr_mult": 0.5,
                        "tp_r_multiple": 2.5,
                    },
                },
            ],
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
            "take_profit": {"primary_R": 2.5},
        },
    }
    return StrategyManifest.model_validate(raw)


# =====================================================================
# Strategy implementation
# =====================================================================

class EqualHighsSweepStrategy(Strategy):
    """Equal Highs/Lows Sweep + Immediate Reversal (SMC H-2).

    SHORT setup:
      1. EQH havuzu: son 30 bar içinde ≥2 swing high ATR*0.15 toleransla eşit.
      2. Sweep: high[t] > eqh_level VE close[t] < eqh_level (aynı bar geri döndü).
      3. Reversal onayı: sweep veya sonraki 1-3 bar içinde bearish close < eqh_level.
      4. Entry (short): reversal bar açılışı.
      5. SL: sweep bar high + 0.5 ATR.
      6. TP: 2.5R.

    LONG setup (mirror):
      1. EQL havuzu: ≥2 swing low ATR*0.15 toleransla eşit.
      2. Sweep: low[t] < eql_level VE close[t] > eql_level.
      3. Entry (long): reversal bar açılışı.
      4. SL: sweep bar low - 0.5 ATR.
      5. TP: 2.5R.
    """

    name = "equal_highs_sweep"

    # ------------------------------------------------------------------
    # Manifest parsing helpers
    # ------------------------------------------------------------------
    def _get_param(self, pattern_id: str, key: str, default: Any) -> Any:
        for p in self.manifest.signals.patterns:
            if p.id == pattern_id:
                return p.params.get(key, default)
        return default

    # ------------------------------------------------------------------
    # Feature preparation
    # ------------------------------------------------------------------
    def prepare_features(self, df: pd.DataFrame) -> pd.DataFrame:
        if df.empty:
            return df.copy()
        self.apply_tf_manifest(df)
        df = df.sort_values("ts").reset_index(drop=True).copy()

        # Core indicators
        df["ema50"] = _ema(df["close"], 50)
        df["atr14"] = _atr(df, 14)
        df["atr_pct"] = df["atr14"] / df["close"]

        # Volume z-score (60 bar)
        vol = df["volume"]
        vmean = vol.rolling(60, min_periods=10).mean()
        vstd = vol.rolling(60, min_periods=10).std(ddof=0)
        df["vol_z"] = (vol - vmean) / vstd.replace(0, np.nan)

        # Pattern params (use defaults from manifest or hard-coded fallback)
        lookback = int(self._get_param("eqh_sweep_short", "lookback_bars", 30))
        tol_atr = float(self._get_param("eqh_sweep_short", "tolerance_atr", 0.15))
        n_fractal = int(self._get_param("eqh_sweep_short", "fractal_n", 3))

        # EQH / EQL levels (bar-by-bar, lookahead-free)
        eqh, eql = _detect_equal_highs(df, lookback=lookback, tolerance_atr=tol_atr, n_fractal=n_fractal)
        df["eqh_level"] = eqh
        df["eql_level"] = eql

        return df

    # ------------------------------------------------------------------
    # Signal generation
    # ------------------------------------------------------------------
    def generate_signals(self, df: pd.DataFrame) -> list[Signal]:
        if df.empty:
            return []
        if "eqh_level" not in df.columns:
            df = self.prepare_features(df)

        signals_cfg = self.manifest.signals
        filters = signals_cfg.filters
        min_score = float(signals_cfg.confluence.min_score)

        # Pattern params
        reversal_window = int(self._get_param("eqh_sweep_short", "reversal_window", 3))
        sl_atr_mult = float(self._get_param("eqh_sweep_short", "sl_atr_mult", 0.5))
        tp_r_multiple = float(self._get_param("eqh_sweep_short", "tp_r_multiple", 2.5))

        bull_weight = next(
            (p.weight for p in signals_cfg.patterns if p.id == "eqh_sweep_short"), 2.0
        )
        long_weight = next(
            (p.weight for p in signals_cfg.patterns if p.id == "eql_sweep_long"), 2.0
        )

        atr_min_pct = float(getattr(filters, "atr_min_pct", 0.003) or 0.003)

        venue = str(df["venue"].iloc[0]) if "venue" in df.columns else "unknown"
        symbol = str(df["symbol"].iloc[0]) if "symbol" in df.columns else "UNKNOWN"
        timeframe = str(df["timeframe"].iloc[0]) if "timeframe" in df.columns else "1d"

        highs   = df["high"].to_numpy(dtype=float)
        lows    = df["low"].to_numpy(dtype=float)
        opens   = df["open"].to_numpy(dtype=float)
        closes  = df["close"].to_numpy(dtype=float)
        atrs    = df["atr14"].to_numpy(dtype=float)
        atr_pct = df["atr_pct"].to_numpy(dtype=float)
        eqh_arr = df["eqh_level"].to_numpy(dtype=float)
        eql_arr = df["eql_level"].to_numpy(dtype=float)
        ts_arr  = df["ts"].to_numpy()

        n = len(df)
        out: list[Signal] = []

        # Track last emitted to avoid double-signals in reversal window
        last_short_ts: int = -99
        last_long_ts: int = -99

        for t in range(1, n):
            atr_t = atrs[t]
            if np.isnan(atr_t) or atr_t <= 0:
                continue

            # ATR min filter
            if atr_min_pct > 0 and not np.isnan(atr_pct[t]) and atr_pct[t] < atr_min_pct:
                continue

            # ----------------------------------------------------------------
            # SHORT: EQH sweep
            # ----------------------------------------------------------------
            eqh = eqh_arr[t]
            if not np.isnan(eqh) and t > last_short_ts + reversal_window + 1:
                # Check if this bar or any of the last reversal_window bars was the sweep
                for sweep_t in range(max(1, t - reversal_window), t + 1):
                    if sweep_t >= n:
                        break
                    sweep_eqh = eqh_arr[sweep_t]
                    if np.isnan(sweep_eqh):
                        continue
                    # Sweep condition: high > pool AND close < pool (reclaim)
                    if highs[sweep_t] > sweep_eqh and closes[sweep_t] < sweep_eqh:
                        # Reversal confirmation: current close < pool (bearish)
                        if closes[t] < sweep_eqh:
                            # Entry on next bar open (we record signal at bar t)
                            # Prevent re-signaling in same reversal window
                            if t <= last_short_ts + reversal_window:
                                break

                            sweep_high = highs[sweep_t]
                            sl_price = sweep_high + sl_atr_mult * atr_t
                            entry_price = opens[t] if t > sweep_t else closes[t]
                            # Use close as entry proxy for backtest; engine uses next bar open
                            entry_ref = closes[t]
                            risk = sl_price - entry_ref
                            if risk <= 0:
                                break
                            tp_price = entry_ref - tp_r_multiple * risk

                            score = bull_weight
                            if score < min_score:
                                break

                            sig = self.emit_signal(
                                ts=pd.Timestamp(ts_arr[t]).to_pydatetime(),
                                venue=venue,
                                symbol=symbol,
                                timeframe=timeframe,
                                direction="short",
                                pattern_id="eqh_sweep_short",
                                confluence_score=float(score),
                                sl_price=float(sl_price),
                                tp_price=float(tp_price),
                                suggested_size_atr=1.0,
                                metadata={
                                    "eqh_level": float(sweep_eqh),
                                    "sweep_bar_idx": int(sweep_t),
                                    "sweep_high": float(sweep_high),
                                    "atr14": float(atr_t),
                                    "bars_since_sweep": int(t - sweep_t),
                                },
                            )
                            out.append(sig)
                            last_short_ts = t
                            break

            # ----------------------------------------------------------------
            # LONG: EQL sweep (mirror)
            # ----------------------------------------------------------------
            eql = eql_arr[t]
            if not np.isnan(eql) and t > last_long_ts + reversal_window + 1:
                for sweep_t in range(max(1, t - reversal_window), t + 1):
                    if sweep_t >= n:
                        break
                    sweep_eql = eql_arr[sweep_t]
                    if np.isnan(sweep_eql):
                        continue
                    # Sweep: low < pool AND close > pool (reclaim)
                    if lows[sweep_t] < sweep_eql and closes[sweep_t] > sweep_eql:
                        if closes[t] > sweep_eql:
                            if t <= last_long_ts + reversal_window:
                                break

                            sweep_low = lows[sweep_t]
                            sl_price = sweep_low - sl_atr_mult * atr_t
                            entry_ref = closes[t]
                            risk = entry_ref - sl_price
                            if risk <= 0:
                                break
                            tp_price = entry_ref + tp_r_multiple * risk

                            score = long_weight
                            if score < min_score:
                                break

                            sig = self.emit_signal(
                                ts=pd.Timestamp(ts_arr[t]).to_pydatetime(),
                                venue=venue,
                                symbol=symbol,
                                timeframe=timeframe,
                                direction="long",
                                pattern_id="eql_sweep_long",
                                confluence_score=float(score),
                                sl_price=float(sl_price),
                                tp_price=float(tp_price),
                                suggested_size_atr=1.0,
                                metadata={
                                    "eql_level": float(sweep_eql),
                                    "sweep_bar_idx": int(sweep_t),
                                    "sweep_low": float(sweep_low),
                                    "atr14": float(atr_t),
                                    "bars_since_sweep": int(t - sweep_t),
                                },
                            )
                            out.append(sig)
                            last_long_ts = t
                            break

        self._log.bind(n=len(out), bars=len(df)).info("equal_highs_sweep.signals.generated")
        return out
