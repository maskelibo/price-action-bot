"""Liquidity Sweep + Reversal v2 (single swing point version).

Konsept:
  Mevcut `equal_highs_sweep` >=2 esit swing high/low gerektiren havuz
  arari. Bu strateji DAHA YALNIZ pattern: tek confirmed swing high/low
  uzerine open + reclaim.

Pattern (SHORT):
  - bar[t-lookback..t-1] icindeki en yuksek confirmed swing high (SH)
  - bar[t]: high > SH (sweep) AND open >= SH AND close < SH
    (yani bar SH ustunde acilip geri SH altina kapandi -> false breakout)
  - Trigger: bar[t] kapanisinda SHORT sinyali

Pattern (LONG): mirror

Ek kosullar:
  - SH yasi >= 2 bar (cok taze swing'e karsi koruma)
  - SH yasi <= max_age_bars (cok eski likidite ilgisiz)
  - Sweep amount: high - SH >= min_sweep_atr * ATR (cok minik wick'e karsi)
  - Reclaim margin: SH - close >= min_reclaim_atr * ATR (gercek reclaim)

Risk:
  - SL: sweep_high + 0.3 * ATR
  - TP: 2.0R

Lookahead-free: SH son `lookback` bar icinde fractal_n=2 ile detect edilir,
bar[t]'ye kadar onceki bar. Bar t henuz kapanmadan karar verilmez.

Mevcut equal_highs_sweep'ten fark:
  - Tek swing point (havuz degil), >50% daha cok aday
  - Open kosulu eklenmis (sweep MUTLAKA same-bar reclaim degil, "open above + close below")
  - Sweep amount esigi var
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from price_action.contracts import Signal
from price_action.logging_config import logger
from price_action.strategies.base import Strategy, StrategyManifest
from price_action.strategies.classic_pa import _atr, _ema, _fractal_swings


def _default_manifest() -> StrategyManifest:
    raw = {
        "name": "liquidity_sweep_reversal",
        "version": "1.0.0",
        "description": (
            "Single swing high/low sweep + same-bar reclaim. "
            "False breakout pattern with sweep+reclaim ATR thresholds."
        ),
        "trend_filter": {"type": "ema", "period": 50, "required": False},
        "signals": {
            "patterns": [
                {
                    "id": "sweep_high_short",
                    "enabled": True,
                    "weight": 2.0,
                    "params": {
                        "lookback_bars": 30,
                        "min_age_bars": 2,
                        "max_age_bars": 30,
                        "min_sweep_atr": 0.10,
                        "min_reclaim_atr": 0.20,
                        "fractal_n": 2,
                        "sl_atr_mult": 0.3,
                        "tp_r_multiple": 2.0,
                    },
                },
                {
                    "id": "sweep_low_long",
                    "enabled": True,
                    "weight": 2.0,
                    "params": {
                        "lookback_bars": 30,
                        "min_age_bars": 2,
                        "max_age_bars": 30,
                        "min_sweep_atr": 0.10,
                        "min_reclaim_atr": 0.20,
                        "fractal_n": 2,
                        "sl_atr_mult": 0.3,
                        "tp_r_multiple": 2.0,
                    },
                },
            ],
            "filters": {
                "atr_min_pct": 0.005,
                "volume_zscore_min": 0.0,
            },
            "confluence": {
                "method": "weighted_sum",
                "min_score": 1.5,
                "bonus_if_at_sr": 0.0,
            },
        },
        "risk": {
            "take_profit": {"primary_R": 2.0},
        },
    }
    return StrategyManifest.model_validate(raw)


class LiquiditySweepReversalStrategy(Strategy):
    """Single swing point sweep + reclaim reversal."""

    name = "liquidity_sweep_reversal"

    def _get_param(self, pattern_id: str, key: str, default: Any) -> Any:
        for p in self.manifest.signals.patterns:
            if p.id == pattern_id:
                return p.params.get(key, default)
        return default

    def prepare_features(self, df: pd.DataFrame) -> pd.DataFrame:
        if df.empty:
            return df.copy()
        df = df.sort_values("ts").reset_index(drop=True).copy()

        df["ema50"] = _ema(df["close"], 50)
        df["atr14"] = _atr(df, 14)
        df["atr_pct"] = df["atr14"] / df["close"]

        n_fractal = int(self._get_param("sweep_high_short", "fractal_n", 2))
        sh, sl = _fractal_swings(df, n=n_fractal)
        df["swing_high_flag"] = sh
        df["swing_low_flag"] = sl

        # Volume z (60-bar)
        vol = df["volume"]
        vmean = vol.rolling(60, min_periods=10).mean()
        vstd = vol.rolling(60, min_periods=10).std(ddof=0)
        df["vol_z"] = (vol - vmean) / vstd.replace(0, np.nan)

        return df

    def generate_signals(self, df: pd.DataFrame) -> list[Signal]:
        if df.empty:
            return []
        if "swing_high_flag" not in df.columns:
            df = self.prepare_features(df)

        signals_cfg = self.manifest.signals
        filters = signals_cfg.filters
        min_score = float(signals_cfg.confluence.min_score)

        lookback = int(self._get_param("sweep_high_short", "lookback_bars", 30))
        min_age = int(self._get_param("sweep_high_short", "min_age_bars", 2))
        max_age = int(self._get_param("sweep_high_short", "max_age_bars", 30))
        min_sweep_atr = float(self._get_param("sweep_high_short", "min_sweep_atr", 0.10))
        min_reclaim_atr = float(self._get_param("sweep_high_short", "min_reclaim_atr", 0.20))
        n_fractal = int(self._get_param("sweep_high_short", "fractal_n", 2))
        sl_atr_mult = float(self._get_param("sweep_high_short", "sl_atr_mult", 0.3))
        tp_r = float(self._get_param("sweep_high_short", "tp_r_multiple", 2.0))

        short_w = next((p.weight for p in signals_cfg.patterns if p.id == "sweep_high_short"), 2.0)
        long_w = next((p.weight for p in signals_cfg.patterns if p.id == "sweep_low_long"), 2.0)

        atr_min_pct = float(getattr(filters, "atr_min_pct", 0.005) or 0.005)

        venue = str(df["venue"].iloc[0]) if "venue" in df.columns else "unknown"
        symbol = str(df["symbol"].iloc[0]) if "symbol" in df.columns else "UNKNOWN"
        timeframe = str(df["timeframe"].iloc[0]) if "timeframe" in df.columns else "1d"

        opens   = df["open"].to_numpy(dtype=float)
        highs   = df["high"].to_numpy(dtype=float)
        lows    = df["low"].to_numpy(dtype=float)
        closes  = df["close"].to_numpy(dtype=float)
        atrs    = df["atr14"].to_numpy(dtype=float)
        atr_pct = df["atr_pct"].to_numpy(dtype=float)
        sh_flag = df["swing_high_flag"].to_numpy(dtype=bool)
        sl_flag = df["swing_low_flag"].to_numpy(dtype=bool)
        ts_arr  = df["ts"].to_numpy()
        n = len(df)

        out: list[Signal] = []
        # Cooldown: ayni yonde art arda emit etme
        last_short_ts = -99
        last_long_ts = -99
        cooldown = 3

        for t in range(lookback + n_fractal, n):
            atr_t = atrs[t]
            if np.isnan(atr_t) or atr_t <= 0:
                continue
            if atr_min_pct > 0 and not np.isnan(atr_pct[t]) and atr_pct[t] < atr_min_pct:
                continue

            window_start = max(0, t - lookback)

            # ----- SHORT: en yuksek SH bul, sweep + reclaim -----
            if t > last_short_ts + cooldown:
                # Confirmed SH (fractal_n bar sonra confirmed). t-n_fractal-min_age'a kadar bak
                best_sh = -np.inf
                best_sh_idx = -1
                for i in range(window_start, t - n_fractal):
                    if not sh_flag[i]:
                        continue
                    age = t - i
                    if age < min_age or age > max_age:
                        continue
                    if highs[i] > best_sh:
                        best_sh = highs[i]
                        best_sh_idx = i
                if best_sh_idx >= 0 and best_sh > 0:
                    # Sweep+reclaim conditions
                    sweep_amt = highs[t] - best_sh
                    reclaim_amt = best_sh - closes[t]
                    open_above = opens[t] >= best_sh
                    if (sweep_amt >= min_sweep_atr * atr_t and
                        reclaim_amt >= min_reclaim_atr * atr_t and
                        open_above):
                        sl_price = highs[t] + sl_atr_mult * atr_t
                        entry_ref = closes[t]
                        risk = sl_price - entry_ref
                        if risk > 0:
                            tp_price = entry_ref - tp_r * risk
                            score = short_w
                            if score >= min_score:
                                sig = self.emit_signal(
                                    ts=pd.Timestamp(ts_arr[t]).to_pydatetime(),
                                    venue=venue, symbol=symbol, timeframe=timeframe,
                                    direction="short",
                                    pattern_id="sweep_high_short",
                                    confluence_score=float(score),
                                    sl_price=float(sl_price),
                                    tp_price=float(tp_price),
                                    suggested_size_atr=1.0,
                                    metadata={
                                        "swing_high": float(best_sh),
                                        "swing_idx": int(best_sh_idx),
                                        "sweep_atr": float(sweep_amt / atr_t),
                                        "reclaim_atr": float(reclaim_amt / atr_t),
                                        "age_bars": int(t - best_sh_idx),
                                    },
                                )
                                out.append(sig)
                                last_short_ts = t

            # ----- LONG: en dusuk SL bul, sweep + reclaim -----
            if t > last_long_ts + cooldown:
                best_sl = np.inf
                best_sl_idx = -1
                for i in range(window_start, t - n_fractal):
                    if not sl_flag[i]:
                        continue
                    age = t - i
                    if age < min_age or age > max_age:
                        continue
                    if lows[i] < best_sl:
                        best_sl = lows[i]
                        best_sl_idx = i
                if best_sl_idx >= 0 and best_sl < np.inf:
                    sweep_amt = best_sl - lows[t]
                    reclaim_amt = closes[t] - best_sl
                    open_below = opens[t] <= best_sl
                    if (sweep_amt >= min_sweep_atr * atr_t and
                        reclaim_amt >= min_reclaim_atr * atr_t and
                        open_below):
                        sl_price = lows[t] - sl_atr_mult * atr_t
                        entry_ref = closes[t]
                        risk = entry_ref - sl_price
                        if risk > 0:
                            tp_price = entry_ref + tp_r * risk
                            score = long_w
                            if score >= min_score:
                                sig = self.emit_signal(
                                    ts=pd.Timestamp(ts_arr[t]).to_pydatetime(),
                                    venue=venue, symbol=symbol, timeframe=timeframe,
                                    direction="long",
                                    pattern_id="sweep_low_long",
                                    confluence_score=float(score),
                                    sl_price=float(sl_price),
                                    tp_price=float(tp_price),
                                    suggested_size_atr=1.0,
                                    metadata={
                                        "swing_low": float(best_sl),
                                        "swing_idx": int(best_sl_idx),
                                        "sweep_atr": float(sweep_amt / atr_t),
                                        "reclaim_atr": float(reclaim_amt / atr_t),
                                        "age_bars": int(t - best_sl_idx),
                                    },
                                )
                                out.append(sig)
                                last_long_ts = t

        self._log.bind(n=len(out), bars=len(df)).info("liquidity_sweep_reversal.signals.generated")
        return out
