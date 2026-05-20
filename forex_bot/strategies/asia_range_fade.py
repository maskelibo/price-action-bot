"""Asia Range Fade.

In the Asia session, fade extremes of the rolling 4-hour range using pin bar reversals.
Low-volatility mean reversion. Best for: AUDUSD, NZDUSD, USDJPY (active Asia).
"""
from __future__ import annotations

import pandas as pd
import numpy as np

from ..contracts import Signal, price_to_pips
from ..indicators.price_action import bullish_pin_bar, bearish_pin_bar
from .base import Strategy, StrategyManifest


class AsiaRangeFadeStrategy(Strategy):
    name = "asia_range_fade"

    def __init__(self, manifest=None):
        super().__init__(manifest or StrategyManifest(
            name=self.name, sessions_allowed=["asia"],
            sl_atr_mult=0.8, tp_atr_mult=1.6, rr_min=1.5,
            params={"range_lookback": 16},  # 4 hours of 15m bars
        ))

    def generate_signals(self, df: pd.DataFrame, pair: str) -> list[Signal]:
        if df.empty:
            return []
        lb = self.manifest.params["range_lookback"]
        rh = df["high"].rolling(lb, min_periods=lb).max().shift(1)
        rl = df["low"].rolling(lb, min_periods=lb).min().shift(1)
        atr14 = df["atr14"]
        at_high = df["high"] >= rh
        at_low = df["low"] <= rl
        bear = bearish_pin_bar(df) & at_high & (df["session"] == "asia")
        bull = bullish_pin_bar(df) & at_low & (df["session"] == "asia")
        out = []
        for ts in df.index[bull.fillna(False)]:
            row = df.loc[ts]
            a = atr14.loc[ts]
            if not np.isfinite(a) or a <= 0:
                continue
            entry = float(row["close"])
            sl = float(row["low"] - 0.2 * a)
            tp1 = entry + (entry - sl) * 1.3
            tp2 = entry + (entry - sl) * 2.5
            out.append(self._emit(
                pair, ts, "long", entry, sl, [tp1, tp2], 0.6, "asia",
                "asia_fade_bull", price_to_pips(pair, entry - sl),
                meta={"pattern_hit": True, "structure_hit": True, "smc_hit": False,
                      "volume_score": float(row.get("participation", 0.4)) if pd.notna(row.get("participation")) else 0.4,
                      "trend_aligned": False},
            ))
        for ts in df.index[bear.fillna(False)]:
            row = df.loc[ts]
            a = atr14.loc[ts]
            if not np.isfinite(a) or a <= 0:
                continue
            entry = float(row["close"])
            sl = float(row["high"] + 0.2 * a)
            tp1 = entry - (sl - entry) * 1.3
            tp2 = entry - (sl - entry) * 2.5
            out.append(self._emit(
                pair, ts, "short", entry, sl, [tp1, tp2], 0.6, "asia",
                "asia_fade_bear", price_to_pips(pair, sl - entry),
                meta={"pattern_hit": True, "structure_hit": True, "smc_hit": False,
                      "volume_score": float(row.get("participation", 0.4)) if pd.notna(row.get("participation")) else 0.4,
                      "trend_aligned": False},
            ))
        return out
