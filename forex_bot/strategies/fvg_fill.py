"""FVG fill: trade the close of a fair value gap."""
from __future__ import annotations

import pandas as pd
import numpy as np

from ..contracts import Signal, price_to_pips
from ..indicators.smc import fair_value_gap
from .base import Strategy, StrategyManifest


class FVGFillStrategy(Strategy):
    name = "fvg_fill"

    def __init__(self, manifest=None):
        super().__init__(manifest or StrategyManifest(
            name=self.name, sessions_allowed=["london", "london_ny_overlap", "ny"],
            sl_atr_mult=1.0, tp_atr_mult=2.0, rr_min=1.5,
            params={"max_age_bars": 16, "min_size_atr": 0.4},
        ))

    def generate_signals(self, df: pd.DataFrame, pair: str) -> list[Signal]:
        if df.empty:
            return []
        fvg = fair_value_gap(df, min_size_atr=self.manifest.params["min_size_atr"])
        atr14 = df["atr14"]
        max_age = self.manifest.params["max_age_bars"]
        sess_ok = df["session"].isin(self.manifest.sessions_allowed)
        out = []
        # bullish FVG: t-2.high < t.low (gap up); look for fill back into [t-2.high, t.low]
        bull_idx = df.index[fvg["bull_fvg"].fillna(False)]
        for j_pos, j in enumerate(bull_idx):
            gap_top = df["low"].loc[j]
            gap_bot = df["high"].shift(2).loc[j]
            end_pos = min(df.index.get_loc(j) + max_age, len(df) - 1)
            window = df.iloc[df.index.get_loc(j) + 1: end_pos + 1]
            hit = window[(window["low"] <= gap_top) & (window["close"] >= gap_bot)]
            for ts in hit.index[:1]:
                if not sess_ok.loc[ts]:
                    continue
                a = atr14.loc[ts]
                if not np.isfinite(a) or a <= 0:
                    continue
                row = df.loc[ts]
                entry = float(row["close"])
                sl = float(gap_bot - 0.3 * a)
                if entry - sl <= 0:
                    continue
                tp1 = entry + (entry - sl) * 1.5
                tp2 = entry + (entry - sl) * 3.0
                out.append(self._emit(
                    pair, ts, "long", entry, sl, [tp1, tp2], 0.68, row["session"],
                    "fvg_fill_bull", price_to_pips(pair, entry - sl),
                    meta={"pattern_hit": False, "structure_hit": False, "smc_hit": True,
                          "volume_score": float(row.get("participation", 0.5)) if pd.notna(row.get("participation")) else 0.5,
                          "trend_aligned": row["close"] > row.get("ema50", row["close"])},
                ))
        bear_idx = df.index[fvg["bear_fvg"].fillna(False)]
        for j_pos, j in enumerate(bear_idx):
            gap_bot = df["high"].loc[j]
            gap_top = df["low"].shift(2).loc[j]
            end_pos = min(df.index.get_loc(j) + max_age, len(df) - 1)
            window = df.iloc[df.index.get_loc(j) + 1: end_pos + 1]
            hit = window[(window["high"] >= gap_bot) & (window["close"] <= gap_top)]
            for ts in hit.index[:1]:
                if not sess_ok.loc[ts]:
                    continue
                a = atr14.loc[ts]
                if not np.isfinite(a) or a <= 0:
                    continue
                row = df.loc[ts]
                entry = float(row["close"])
                sl = float(gap_top + 0.3 * a)
                if sl - entry <= 0:
                    continue
                tp1 = entry - (sl - entry) * 1.5
                tp2 = entry - (sl - entry) * 3.0
                out.append(self._emit(
                    pair, ts, "short", entry, sl, [tp1, tp2], 0.68, row["session"],
                    "fvg_fill_bear", price_to_pips(pair, sl - entry),
                    meta={"pattern_hit": False, "structure_hit": False, "smc_hit": True,
                          "volume_score": float(row.get("participation", 0.5)) if pd.notna(row.get("participation")) else 0.5,
                          "trend_aligned": row["close"] < row.get("ema50", row["close"])},
                ))
        return out
