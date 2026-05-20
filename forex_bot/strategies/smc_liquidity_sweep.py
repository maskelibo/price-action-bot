"""SMC liquidity sweep + reversal.

Detect sweep of prior swing high/low (equal-highs hunt) followed by close back inside;
enter against the sweep direction.
"""
from __future__ import annotations

import pandas as pd
import numpy as np

from ..contracts import Signal, price_to_pips
from ..indicators.smc import liquidity_sweep_high, liquidity_sweep_low, choch_bullish, choch_bearish
from .base import Strategy, StrategyManifest


class SMCLiquiditySweepStrategy(Strategy):
    name = "smc_liquidity_sweep"

    def __init__(self, manifest=None):
        super().__init__(manifest or StrategyManifest(
            name=self.name, sessions_allowed=["london", "london_ny_overlap", "ny"],
            sl_atr_mult=1.0, tp_atr_mult=2.5, rr_min=2.0,
            params={"lookback": 20, "min_choch": True},
        ))

    def generate_signals(self, df: pd.DataFrame, pair: str) -> list[Signal]:
        if df.empty:
            return []
        lb = self.manifest.params["lookback"]
        sweep_h = liquidity_sweep_high(df, lookback=lb)
        sweep_l = liquidity_sweep_low(df, lookback=lb)
        if self.manifest.params["min_choch"]:
            sweep_h = sweep_h & choch_bearish(df)
            sweep_l = sweep_l & choch_bullish(df)
        atr14 = df["atr14"]
        sess_ok = df["session"].isin(self.manifest.sessions_allowed)
        sweep_h = sweep_h & sess_ok
        sweep_l = sweep_l & sess_ok
        out = []
        for ts in df.index[sweep_l.fillna(False)]:
            row = df.loc[ts]
            a = atr14.loc[ts]
            if not np.isfinite(a) or a <= 0:
                continue
            entry = float(row["close"])
            sl = float(row["low"] - 0.2 * a)
            tp1 = entry + (entry - sl) * 2.0
            tp2 = entry + (entry - sl) * 4.0
            out.append(self._emit(
                pair, ts, "long", entry, sl, [tp1, tp2], 0.72, row["session"],
                "smc_sweep_low", price_to_pips(pair, entry - sl),
                meta={"pattern_hit": True, "structure_hit": True, "smc_hit": True,
                      "volume_score": float(row.get("participation", 0.5)) if pd.notna(row.get("participation")) else 0.5,
                      "trend_aligned": row["close"] > row.get("ema50", row["close"])},
            ))
        for ts in df.index[sweep_h.fillna(False)]:
            row = df.loc[ts]
            a = atr14.loc[ts]
            if not np.isfinite(a) or a <= 0:
                continue
            entry = float(row["close"])
            sl = float(row["high"] + 0.2 * a)
            tp1 = entry - (sl - entry) * 2.0
            tp2 = entry - (sl - entry) * 4.0
            out.append(self._emit(
                pair, ts, "short", entry, sl, [tp1, tp2], 0.72, row["session"],
                "smc_sweep_high", price_to_pips(pair, sl - entry),
                meta={"pattern_hit": True, "structure_hit": True, "smc_hit": True,
                      "volume_score": float(row.get("participation", 0.5)) if pd.notna(row.get("participation")) else 0.5,
                      "trend_aligned": row["close"] < row.get("ema50", row["close"])},
            ))
        return out
