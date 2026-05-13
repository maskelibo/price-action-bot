"""Bollinger Band Squeeze + Breakout stratejisi.

Hipotez:
  - 20-bar Bollinger Bands width = (BB_upper - BB_lower) / BB_mid
  - Squeeze: bb_width <= squeeze_factor * 60-bar median(bb_width)
            (default squeeze_factor=0.5 -> alt yari)
  - Breakout: squeeze siyrilirken (ilk yon) close > BB_upper -> LONG
              veya close < BB_lower -> SHORT
  - Trend filter: 200-EMA (long sadece close>EMA200, short tersine)

Lookahead-bias-free:
  - bb_width.rolling(60).median() shift(1) ile [t-60..t-1]
  - bb_width[t] kendisi t bar'da bilinir (close[t] kapanmis)
  - squeeze flag t-1 'de hesaplanir (squeeze_prev), trigger t'de

Cooldown: same_symbol+same_side 5 bar

Entry: bar t kapanis sonrasi t+1 acilis (manifest.execution.decision_after_close)
SL   : structural swing low/high (10-bar) - atr_buffer
TP   : 2R primary
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from price_action.contracts import Signal
from price_action.logging_config import logger
from price_action.strategies.base import Strategy, StrategyManifest
from price_action.strategies.classic_pa import _atr, _ema


def _swing_sl(df: pd.DataFrame, direction: str, lookback: int = 10) -> pd.Series:
    """Structural stop: lookahead-free swing low/high."""
    if direction == "long":
        return df["low"].shift(1).rolling(lookback, min_periods=1).min()
    return df["high"].shift(1).rolling(lookback, min_periods=1).max()


def _default_manifest() -> StrategyManifest:
    raw = {
        "name": "bollinger_squeeze_breakout",
        "version": "1.0.0",
        "description": (
            "Bollinger Band Squeeze + Breakout: 20-bar BB width <= 0.5x 60-day median "
            "-> consolidation. Breakout out of band in trend direction."
        ),
        "trend_filter": {"type": "ema", "period": 200, "required": True},
        "signals": {
            "patterns": [
                {
                    "id": "bb_squeeze_breakout_long",
                    "enabled": True,
                    "weight": 1.5,
                    "params": {
                        "bb_period": 20,
                        "bb_std": 2.0,
                        "median_window": 60,
                        "squeeze_factor": 0.5,
                        "breakout_atr_buffer": 0.0,
                    },
                },
                {
                    "id": "bb_squeeze_breakout_short",
                    "enabled": True,
                    "weight": 1.5,
                    "params": {
                        "bb_period": 20,
                        "bb_std": 2.0,
                        "median_window": 60,
                        "squeeze_factor": 0.5,
                        "breakout_atr_buffer": 0.0,
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
            "stop_loss": {
                "method": "structural_atr",
                "swing_lookback": 10,
                "atr_buffer": 0.5,
            },
            "take_profit": {"method": "r_multiple", "primary_R": 2.0},
            "position_sizing": {
                "method": "fixed_fractional",
                "risk_per_trade": 0.01,
            },
        },
    }
    return StrategyManifest.model_validate(raw)


class BollingerSqueezeBreakoutStrategy(Strategy):
    """Bollinger Band Squeeze + Directional Breakout (1d)."""

    name = "bollinger_squeeze_breakout"

    def prepare_features(self, df: pd.DataFrame) -> pd.DataFrame:
        if df.empty:
            return df.copy()
        df = df.sort_values("ts").reset_index(drop=True).copy()

        # Indicators
        df["ema50"] = _ema(df["close"], 50)
        df["ema200"] = _ema(df["close"], 200)
        df["atr14"] = _atr(df, 14)
        df["atr_pct"] = df["atr14"] / df["close"]

        # --- Param extract ---
        bb_period = 20
        bb_std = 2.0
        median_window = 60
        squeeze_factor = 0.5
        for p in self.manifest.signals.patterns:
            if p.id in ("bb_squeeze_breakout_long", "bb_squeeze_breakout_short"):
                bb_period = int(p.params.get("bb_period", 20))
                bb_std = float(p.params.get("bb_std", 2.0))
                median_window = int(p.params.get("median_window", 60))
                squeeze_factor = float(p.params.get("squeeze_factor", 0.5))
                break

        # --- Bollinger Bands ---
        bb_mid = df["close"].rolling(bb_period, min_periods=bb_period).mean()
        bb_std_series = df["close"].rolling(bb_period, min_periods=bb_period).std(ddof=0)
        df["bb_mid"] = bb_mid
        df["bb_upper"] = bb_mid + bb_std * bb_std_series
        df["bb_lower"] = bb_mid - bb_std * bb_std_series
        # Width as fraction of mid (normalize across price levels)
        df["bb_width"] = (df["bb_upper"] - df["bb_lower"]) / bb_mid.replace(0.0, np.nan)

        # LOOKAHEAD-FREE: median of width using only history (shift 1)
        df["bb_width_median"] = (
            df["bb_width"].shift(1).rolling(median_window, min_periods=20).median()
        )
        df["squeeze"] = df["bb_width"] <= squeeze_factor * df["bb_width_median"]
        # Trigger: prev bar in squeeze, current bar breaks out of band
        df["squeeze_prev"] = df["squeeze"].shift(1).fillna(False)

        # Breakout flags
        df["bo_long"] = (df["squeeze_prev"]) & (df["close"] > df["bb_upper"])
        df["bo_short"] = (df["squeeze_prev"]) & (df["close"] < df["bb_lower"])

        # Structural SL
        swing_lookback = int(
            self.manifest.risk.get("stop_loss", {}).get("swing_lookback", 10)
        )
        df["struct_sl_long"] = _swing_sl(df, "long", lookback=swing_lookback)
        df["struct_sl_short"] = _swing_sl(df, "short", lookback=swing_lookback)

        # Volume z (60-bar)
        vol = df["volume"]
        vmean = vol.rolling(60, min_periods=10).mean()
        vstd = vol.rolling(60, min_periods=10).std(ddof=0)
        df["vol_z"] = (vol - vmean) / vstd.replace(0, np.nan)

        return df

    def generate_signals(self, df: pd.DataFrame) -> list[Signal]:
        if df.empty:
            return []
        if "squeeze" not in df.columns:
            df = self.prepare_features(df)

        signals_cfg = self.manifest.signals
        filters_cfg = signals_cfg.filters
        confluence = signals_cfg.confluence

        primary_R = float(
            self.manifest.risk.get("take_profit", {}).get("primary_R", 2.0)
        )
        atr_buffer = float(
            self.manifest.risk.get("stop_loss", {}).get("atr_buffer", 0.5)
        )

        venue = str(df["venue"].iloc[0]) if "venue" in df.columns else "unknown"
        symbol = str(df["symbol"].iloc[0]) if "symbol" in df.columns else "UNKNOWN"
        timeframe = str(df["timeframe"].iloc[0]) if "timeframe" in df.columns else "1d"

        long_w = 1.5
        short_w = 1.5
        for p in signals_cfg.patterns:
            if not p.enabled:
                continue
            if p.id == "bb_squeeze_breakout_long":
                long_w = p.weight
            elif p.id == "bb_squeeze_breakout_short":
                short_w = p.weight

        atr_min = float(getattr(filters_cfg, "atr_min_pct", 0.005) or 0.005)
        min_score = float(confluence.min_score)

        out: list[Signal] = []
        n = len(df)
        cooldown = 5
        last_long_idx = -99
        last_short_idx = -99

        opens = df["open"].to_numpy(dtype=float)
        closes = df["close"].to_numpy(dtype=float)
        atrs = df["atr14"].to_numpy(dtype=float)
        atr_pct = df["atr_pct"].to_numpy(dtype=float)
        ema200 = df["ema200"].to_numpy(dtype=float)
        bo_l = df["bo_long"].to_numpy(dtype=bool)
        bo_s = df["bo_short"].to_numpy(dtype=bool)
        sl_long_arr = df["struct_sl_long"].to_numpy(dtype=float)
        sl_short_arr = df["struct_sl_short"].to_numpy(dtype=float)
        ts_arr = df["ts"].to_numpy()

        for i in range(n):
            atr = atrs[i]
            if np.isnan(atr) or atr <= 0:
                continue
            if atr_min > 0 and not np.isnan(atr_pct[i]) and atr_pct[i] < atr_min:
                continue
            close = closes[i]
            ema = ema200[i]
            if np.isnan(ema) or ema <= 0:
                continue

            # ---- LONG ----
            if bo_l[i] and close > ema and i > last_long_idx + cooldown:
                score = long_w
                if score >= min_score:
                    sl_struct = sl_long_arr[i]
                    if np.isnan(sl_struct) or sl_struct <= 0:
                        sl_price = close - 2.0 * atr
                    else:
                        sl_price = sl_struct - atr_buffer * atr
                    sl_price = min(sl_price, close - 0.5 * atr)
                    if sl_price <= 0:
                        continue
                    risk = close - sl_price
                    if risk <= 0:
                        continue
                    tp_price = close + primary_R * risk
                    sig = self.emit_signal(
                        ts=pd.Timestamp(ts_arr[i]).to_pydatetime(),
                        venue=venue, symbol=symbol, timeframe=timeframe,
                        direction="long",
                        pattern_id="bb_squeeze_breakout_long",
                        confluence_score=float(score),
                        sl_price=float(sl_price),
                        tp_price=float(tp_price),
                        suggested_size_atr=1.0,
                        metadata={
                            "bb_width": float(df["bb_width"].iloc[i]) if not np.isnan(df["bb_width"].iloc[i]) else 0.0,
                            "atr14": atr,
                            "ema200": float(ema),
                        },
                    )
                    out.append(sig)
                    last_long_idx = i
                    continue

            # ---- SHORT ----
            if bo_s[i] and close < ema and i > last_short_idx + cooldown:
                score = short_w
                if score < min_score:
                    continue
                sl_struct = sl_short_arr[i]
                if np.isnan(sl_struct) or sl_struct <= 0:
                    sl_price = close + 2.0 * atr
                else:
                    sl_price = sl_struct + atr_buffer * atr
                sl_price = max(sl_price, close + 0.5 * atr)
                risk = sl_price - close
                if risk <= 0:
                    continue
                tp_price = close - primary_R * risk
                if tp_price <= 0:
                    continue
                sig = self.emit_signal(
                    ts=pd.Timestamp(ts_arr[i]).to_pydatetime(),
                    venue=venue, symbol=symbol, timeframe=timeframe,
                    direction="short",
                    pattern_id="bb_squeeze_breakout_short",
                    confluence_score=float(score),
                    sl_price=float(sl_price),
                    tp_price=float(tp_price),
                    suggested_size_atr=1.0,
                    metadata={
                        "bb_width": float(df["bb_width"].iloc[i]) if not np.isnan(df["bb_width"].iloc[i]) else 0.0,
                        "atr14": atr,
                        "ema200": float(ema),
                    },
                )
                out.append(sig)
                last_short_idx = i

        self._log.bind(n=len(out), bars=n).info("bb_squeeze_breakout.signals.generated")
        return out
