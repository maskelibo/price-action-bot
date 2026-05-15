"""Bollinger Bands Extreme-Excursion Reversal — Mean-Reversion volatility extreme.

Konsept (Bollinger 2001 + Aurra/StockCharts BB bounce strategy):
  - BB(20, 2.5sigma) — ~99% of price action falls within +/-2.5sigma. Close OUTSIDE
    this band on bar t-1 = extreme statistical excursion.
  - Bar t closes BACK INSIDE band (revert) + rejection wick (>40% range) +
    bearish/bullish body = mean-reversion trigger.

  NOTE: This is OPPOSITE direction of bollinger_squeeze_breakout (which is LOW vol
  squeeze + breakout). This is HIGH vol expansion + fade — orthogonal mechanic.

Bearish BB Extreme Reversal (SHORT):
  - Bar t-1: close[t-1] > BB_upper25[t-1]   (extreme excursion above upper band)
  - Bar t: close[t] < BB_upper25[t]          (closed back inside extreme band)
           AND close[t] < high[t-1]          (rejection vs t-1 high)
  - Bar t upper wick: (high[t] - max(open,close)[t]) / (high[t]-low[t]) > 0.40
  - Body bearish: close[t] < open[t]
  - ATR%(14) >= 0.5%
  - BB width / mid > 0.04 (expansion regime, not squeeze)
  - Cooldown same side 7 bar

Bullish BB Extreme Reversal (LONG, mirror):
  - Bar t-1: close[t-1] < BB_lower25[t-1]
  - Bar t: close[t] > BB_lower25[t] AND close[t] > low[t-1]
  - Lower wick: (min(open,close)[t] - low[t]) / (high[t]-low[t]) > 0.40
  - Body bullish: close[t] > open[t]

Targets:
  - SL: SHORT: high[t-1] + 0.25 * ATR(14); LONG: low[t-1] - 0.25 * ATR(14)
  - TP1: BB_mid20[t] (revert to mean) partial 50%
  - TP2: 2.0R primary, partial 30%
  - Runner: 20%, engine default trail

Lookahead-free:
  - BB at bar t computed from rolling(20).{mean,std}() ending at close[t] (causal).
  - BB_upper25[t-1] used in t-1 extreme check is from data up to t-1 only.
  - All shifts explicit.
  - Entry t+1 open.
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from price_action.contracts import Signal
from price_action.logging_config import logger
from price_action.strategies.base import Strategy, StrategyManifest
from price_action.strategies.classic_pa import _atr, _ema


# Engineering SEC21 taxonomy
STRATEGY_CLASS = "mean_reversion"


def _default_manifest() -> StrategyManifest:
    raw = {
        "name": "bb_extreme_reversal",
        "version": "1.0.0",
        "description": (
            "Bollinger Bands 2.5sigma extreme close-outside-then-back-inside "
            "reversal with rejection wick. Mean-reversion volatility extreme."
        ),
        "trend_filter": {"type": "ema", "period": 50, "required": False},
        "signals": {
            "patterns": [
                {
                    "id": "bb_extreme_short",
                    "enabled": True,
                    "weight": 2.0,
                    "params": {
                        "bb_period": 20,
                        "bb_sigma_extreme": 2.5,
                        "bb_sigma_mid": 2.0,
                        "wick_ratio_min": 0.40,
                        "bb_width_min": 0.04,
                        "sl_atr_mult": 0.25,
                        "tp_r_multiple": 2.0,
                        "cooldown_bars": 7,
                    },
                },
                {
                    "id": "bb_extreme_long",
                    "enabled": True,
                    "weight": 2.0,
                    "params": {
                        "bb_period": 20,
                        "bb_sigma_extreme": 2.5,
                        "bb_sigma_mid": 2.0,
                        "wick_ratio_min": 0.40,
                        "bb_width_min": 0.04,
                        "sl_atr_mult": 0.25,
                        "tp_r_multiple": 2.0,
                        "cooldown_bars": 7,
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


class BBExtremeReversalStrategy(Strategy):
    """Bollinger Bands 2.5sigma extreme close-back-inside reversal."""

    name = "bb_extreme_reversal"

    def _get_param(self, pattern_id: str, key: str, default: Any) -> Any:
        for p in self.manifest.signals.patterns:
            if p.id == pattern_id:
                return p.params.get(key, default)
        return default

    def prepare_features(self, df: pd.DataFrame) -> pd.DataFrame:
        if df.empty:
            return df.copy()
        df = df.sort_values("ts").reset_index(drop=True).copy()

        period = int(self._get_param("bb_extreme_short", "bb_period", 20))
        sigma_x = float(self._get_param("bb_extreme_short", "bb_sigma_extreme", 2.5))

        df["atr14"] = _atr(df, 14)
        df["atr_pct"] = df["atr14"] / df["close"]
        df["ema50"] = _ema(df["close"], 50)

        bb_mid = df["close"].rolling(period, min_periods=period).mean()
        bb_std = df["close"].rolling(period, min_periods=period).std(ddof=0)
        df["bb_mid"] = bb_mid
        df["bb_std"] = bb_std
        df["bb_upper_x"] = bb_mid + sigma_x * bb_std
        df["bb_lower_x"] = bb_mid - sigma_x * bb_std
        df["bb_width"] = (df["bb_upper_x"] - df["bb_lower_x"]) / bb_mid.replace(0, np.nan)

        return df

    def generate_signals(self, df: pd.DataFrame) -> list[Signal]:
        if df.empty:
            return []
        if "bb_mid" not in df.columns:
            df = self.prepare_features(df)

        signals_cfg = self.manifest.signals
        filters = signals_cfg.filters
        min_score = float(signals_cfg.confluence.min_score)

        wick_min = float(self._get_param("bb_extreme_short", "wick_ratio_min", 0.40))
        bb_width_min = float(self._get_param("bb_extreme_short", "bb_width_min", 0.04))
        sl_mult = float(self._get_param("bb_extreme_short", "sl_atr_mult", 0.25))
        tp_r = float(self._get_param("bb_extreme_short", "tp_r_multiple", 2.0))
        cooldown = int(self._get_param("bb_extreme_short", "cooldown_bars", 7))

        short_w = next((p.weight for p in signals_cfg.patterns if p.id == "bb_extreme_short"), 2.0)
        long_w = next((p.weight for p in signals_cfg.patterns if p.id == "bb_extreme_long"), 2.0)
        atr_min_pct = float(getattr(filters, "atr_min_pct", 0.005) or 0.005)

        venue = str(df["venue"].iloc[0]) if "venue" in df.columns else "unknown"
        symbol = str(df["symbol"].iloc[0]) if "symbol" in df.columns else "UNKNOWN"
        timeframe = str(df["timeframe"].iloc[0]) if "timeframe" in df.columns else "1d"

        opens = df["open"].to_numpy(dtype=float)
        highs = df["high"].to_numpy(dtype=float)
        lows = df["low"].to_numpy(dtype=float)
        closes = df["close"].to_numpy(dtype=float)
        atrs = df["atr14"].to_numpy(dtype=float)
        atr_pct = df["atr_pct"].to_numpy(dtype=float)
        bb_mid = df["bb_mid"].to_numpy(dtype=float)
        bb_upper_x = df["bb_upper_x"].to_numpy(dtype=float)
        bb_lower_x = df["bb_lower_x"].to_numpy(dtype=float)
        bb_width = df["bb_width"].to_numpy(dtype=float)
        ts_arr = df["ts"].to_numpy()
        n = len(df)

        out: list[Signal] = []
        last_long_ts = -99
        last_short_ts = -99

        for t in range(25, n):  # need 20-bar BB warmup
            atr_t = atrs[t]
            if np.isnan(atr_t) or atr_t <= 0:
                continue
            if atr_min_pct > 0 and not np.isnan(atr_pct[t]) and atr_pct[t] < atr_min_pct:
                continue
            if np.isnan(bb_mid[t]) or np.isnan(bb_upper_x[t]):
                continue
            if np.isnan(bb_width[t]) or bb_width[t] < bb_width_min:
                continue

            # Range / wick characteristics at t
            rng_t = highs[t] - lows[t]
            if rng_t <= 0:
                continue
            upper_wick = (highs[t] - max(opens[t], closes[t])) / rng_t
            lower_wick = (min(opens[t], closes[t]) - lows[t]) / rng_t

            # ----- SHORT: prev close > upper25, today close back inside + rejection -----
            if t > last_short_ts + cooldown:
                prev_close = closes[t - 1]
                prev_upper = bb_upper_x[t - 1]
                if (not np.isnan(prev_upper) and prev_close > prev_upper and
                    closes[t] < bb_upper_x[t] and
                    closes[t] < highs[t - 1] and
                    upper_wick > wick_min and
                    closes[t] < opens[t]):

                    sl_price = highs[t - 1] + sl_mult * atr_t
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
                                pattern_id="bb_extreme_short",
                                confluence_score=float(score),
                                sl_price=float(sl_price),
                                tp_price=float(tp_price),
                                suggested_size_atr=1.0,
                                metadata={
                                    "bb_mid": float(bb_mid[t]),
                                    "bb_upper_x": float(bb_upper_x[t]),
                                    "prev_excursion_atr": float((prev_close - prev_upper) / atr_t) if atr_t > 0 else None,
                                    "upper_wick": float(upper_wick),
                                    "bb_width": float(bb_width[t]),
                                    "mid_target": float(bb_mid[t]),
                                },
                            )
                            out.append(sig)
                            last_short_ts = t

            # ----- LONG: prev close < lower25, today close back inside + rejection -----
            if t > last_long_ts + cooldown:
                prev_close = closes[t - 1]
                prev_lower = bb_lower_x[t - 1]
                if (not np.isnan(prev_lower) and prev_close < prev_lower and
                    closes[t] > bb_lower_x[t] and
                    closes[t] > lows[t - 1] and
                    lower_wick > wick_min and
                    closes[t] > opens[t]):

                    sl_price = lows[t - 1] - sl_mult * atr_t
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
                                pattern_id="bb_extreme_long",
                                confluence_score=float(score),
                                sl_price=float(sl_price),
                                tp_price=float(tp_price),
                                suggested_size_atr=1.0,
                                metadata={
                                    "bb_mid": float(bb_mid[t]),
                                    "bb_lower_x": float(bb_lower_x[t]),
                                    "prev_excursion_atr": float((prev_lower - prev_close) / atr_t) if atr_t > 0 else None,
                                    "lower_wick": float(lower_wick),
                                    "bb_width": float(bb_width[t]),
                                    "mid_target": float(bb_mid[t]),
                                },
                            )
                            out.append(sig)
                            last_long_ts = t

        self._log.bind(n=len(out), bars=len(df)).info("bb_extreme_reversal.signals.generated")
        return out
