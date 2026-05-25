"""NY Open Reversal (12:00 UTC overlap).

Inside London-NY overlap, after a strong directional move (>=1.5 ATR over last 4 bars),
look for reversal pattern (pin bar or engulfing in opposite direction).
"""
from __future__ import annotations

import pandas as pd
import numpy as np

from ..contracts import Signal, price_to_pips
from ..indicators.price_action import bullish_pin_bar, bearish_pin_bar, bullish_engulfing, bearish_engulfing
from .base import Strategy, StrategyManifest


class NyOpenReversalStrategy(Strategy):
    name = "ny_open_reversal"

    def __init__(self, manifest=None):
        super().__init__(manifest or StrategyManifest(
            name=self.name, sessions_allowed=["london_ny_overlap", "ny"],
            sl_atr_mult=1.2, tp_atr_mult=2.4, rr_min=1.5,
            params={"impulse_lookback": 4, "impulse_atr_mult": 1.5},
        ))

    def generate_signals(self, df: pd.DataFrame, pair: str) -> list[Signal]:
        if df.empty:
            return []
        atr14 = df["atr14"]
        lb = self.manifest.params["impulse_lookback"]
        mult = self.manifest.params["impulse_atr_mult"]
        move = df["close"] - df["close"].shift(lb)
        up_impulse = move > mult * atr14
        down_impulse = move < -mult * atr14
        bull_rev = (bullish_pin_bar(df) | bullish_engulfing(df)) & down_impulse
        bear_rev = (bearish_pin_bar(df) | bearish_engulfing(df)) & up_impulse
        sess_ok = df["session"].isin(self.manifest.sessions_allowed)
        bull_rev = bull_rev & sess_ok
        bear_rev = bear_rev & sess_ok
        out = []
        for ts in df.index[bull_rev.fillna(False)]:
            row = df.loc[ts]
            a = atr14.loc[ts]
            if not np.isfinite(a) or a <= 0:
                continue
            entry = float(row["close"])
            sl = float(row["low"] - 0.2 * a)
            tp1 = entry + (entry - sl) * 1.5
            tp2 = entry + (entry - sl) * 3.0
            out.append(self._emit(
                pair, ts, "long", entry, sl, [tp1, tp2], 0.65, row["session"],
                "ny_reversal_bull", price_to_pips(pair, entry - sl),
                meta={"pattern_hit": True, "structure_hit": False, "smc_hit": False,
                      "volume_score": float(row.get("participation", 0.5)) if pd.notna(row.get("participation")) else 0.5,
                      "trend_aligned": row["close"] > row.get("ema200", row["close"])},
            ))
        for ts in df.index[bear_rev.fillna(False)]:
            row = df.loc[ts]
            a = atr14.loc[ts]
            if not np.isfinite(a) or a <= 0:
                continue
            entry = float(row["close"])
            sl = float(row["high"] + 0.2 * a)
            tp1 = entry - (sl - entry) * 1.5
            tp2 = entry - (sl - entry) * 3.0
            out.append(self._emit(
                pair, ts, "short", entry, sl, [tp1, tp2], 0.65, row["session"],
                "ny_reversal_bear", price_to_pips(pair, sl - entry),
                meta={"pattern_hit": True, "structure_hit": False, "smc_hit": False,
                      "volume_score": float(row.get("participation", 0.5)) if pd.notna(row.get("participation")) else 0.5,
                      "trend_aligned": row["close"] < row.get("ema200", row["close"])},
            ))
        return out
