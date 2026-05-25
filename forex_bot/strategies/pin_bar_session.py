"""Pin bar at session high/low with trend alignment."""
from __future__ import annotations

import pandas as pd
import numpy as np

from ..contracts import Signal, price_to_pips
from ..indicators.price_action import bullish_pin_bar, bearish_pin_bar
from .base import Strategy, StrategyManifest


class PinBarSessionStrategy(Strategy):
    name = "pin_bar_session"

    def __init__(self, manifest=None):
        super().__init__(manifest or StrategyManifest(
            name=self.name, sessions_allowed=["london", "london_ny_overlap", "ny"],
            sl_atr_mult=0.8, tp_atr_mult=1.8, rr_min=1.5,
            params={"trend_filter": True, "ema_for_trend": 50},
        ))

    def generate_signals(self, df: pd.DataFrame, pair: str) -> list[Signal]:
        if df.empty:
            return []
        atr14 = df["atr14"]
        ema_t = df.get(f"ema{self.manifest.params['ema_for_trend']}", df["close"])
        sess_ok = df["session"].isin(self.manifest.sessions_allowed)
        bull = bullish_pin_bar(df) & sess_ok
        bear = bearish_pin_bar(df) & sess_ok
        if self.manifest.params["trend_filter"]:
            bull = bull & (df["close"] > ema_t)
            bear = bear & (df["close"] < ema_t)
        out = []
        for ts in df.index[bull.fillna(False)]:
            row = df.loc[ts]
            a = atr14.loc[ts]
            if not np.isfinite(a) or a <= 0:
                continue
            entry = float(row["close"])
            sl = float(row["low"] - 0.15 * a)
            tp1 = entry + (entry - sl) * 1.5
            tp2 = entry + (entry - sl) * 3.0
            out.append(self._emit(
                pair, ts, "long", entry, sl, [tp1, tp2], 0.62, row["session"],
                "pinbar_bull_trend", price_to_pips(pair, entry - sl),
                meta={"pattern_hit": True, "structure_hit": False, "smc_hit": False,
                      "volume_score": float(row.get("participation", 0.5)) if pd.notna(row.get("participation")) else 0.5,
                      "trend_aligned": True},
            ))
        for ts in df.index[bear.fillna(False)]:
            row = df.loc[ts]
            a = atr14.loc[ts]
            if not np.isfinite(a) or a <= 0:
                continue
            entry = float(row["close"])
            sl = float(row["high"] + 0.15 * a)
            tp1 = entry - (sl - entry) * 1.5
            tp2 = entry - (sl - entry) * 3.0
            out.append(self._emit(
                pair, ts, "short", entry, sl, [tp1, tp2], 0.62, row["session"],
                "pinbar_bear_trend", price_to_pips(pair, sl - entry),
                meta={"pattern_hit": True, "structure_hit": False, "smc_hit": False,
                      "volume_score": float(row.get("participation", 0.5)) if pd.notna(row.get("participation")) else 0.5,
                      "trend_aligned": True},
            ))
        return out
