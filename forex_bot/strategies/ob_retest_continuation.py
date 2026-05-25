"""Order Block retest continuation: enter on retest of recent OB in trend direction."""
from __future__ import annotations

import pandas as pd
import numpy as np

from ..contracts import Signal, price_to_pips
from ..indicators.smc import bullish_order_block, bearish_order_block
from .base import Strategy, StrategyManifest


class OBRetestContinuationStrategy(Strategy):
    name = "ob_retest_continuation"

    def __init__(self, manifest=None):
        super().__init__(manifest or StrategyManifest(
            name=self.name, sessions_allowed=["london", "london_ny_overlap", "ny"],
            sl_atr_mult=1.0, tp_atr_mult=2.5, rr_min=2.0,
            params={"max_age_bars": 24},
        ))

    def generate_signals(self, df: pd.DataFrame, pair: str) -> list[Signal]:
        if df.empty:
            return []
        bull_ob = bullish_order_block(df)
        bear_ob = bearish_order_block(df)
        atr14 = df["atr14"]
        max_age = self.manifest.params["max_age_bars"]
        sess_ok = df["session"].isin(self.manifest.sessions_allowed)
        out = []
        # bullish: a bull OB at bar j; entry at bar t (j < t <= j+max_age) where low <= prior bearish candle high (the OB zone)
        for j_idx, j in enumerate(df.index[bull_ob.fillna(False)]):
            ob_high = df["open"].shift(1).loc[j]  # bearish open is OB top approx
            ob_low = df["close"].shift(1).loc[j]  # bearish close is OB bottom
            j_pos = df.index.get_loc(j)
            end_pos = min(j_pos + max_age, len(df) - 1)
            window = df.loc[j: df.index[end_pos]]
            ret = window[(window.index > j) & (window["low"] <= ob_high) & (window["close"] > ob_low)]
            for ts in ret.index[:1]:
                if not sess_ok.loc[ts]:
                    continue
                a = atr14.loc[ts]
                if not np.isfinite(a) or a <= 0:
                    continue
                row = df.loc[ts]
                entry = float(row["close"])
                sl = float(ob_low - 0.2 * a)
                if entry - sl <= 0:
                    continue
                tp1 = entry + (entry - sl) * 2.0
                tp2 = entry + (entry - sl) * 4.0
                out.append(self._emit(
                    pair, ts, "long", entry, sl, [tp1, tp2], 0.7, row["session"],
                    "bull_ob_retest", price_to_pips(pair, entry - sl),
                    meta={"pattern_hit": False, "structure_hit": True, "smc_hit": True,
                          "volume_score": float(row.get("participation", 0.5)) if pd.notna(row.get("participation")) else 0.5,
                          "trend_aligned": row["close"] > row.get("ema50", row["close"])},
                ))
        for j_idx, j in enumerate(df.index[bear_ob.fillna(False)]):
            ob_low = df["open"].shift(1).loc[j]
            ob_high = df["close"].shift(1).loc[j]
            j_pos = df.index.get_loc(j)
            end_pos = min(j_pos + max_age, len(df) - 1)
            window = df.loc[j: df.index[end_pos]]
            ret = window[(window.index > j) & (window["high"] >= ob_low) & (window["close"] < ob_high)]
            for ts in ret.index[:1]:
                if not sess_ok.loc[ts]:
                    continue
                a = atr14.loc[ts]
                if not np.isfinite(a) or a <= 0:
                    continue
                row = df.loc[ts]
                entry = float(row["close"])
                sl = float(ob_high + 0.2 * a)
                if sl - entry <= 0:
                    continue
                tp1 = entry - (sl - entry) * 2.0
                tp2 = entry - (sl - entry) * 4.0
                out.append(self._emit(
                    pair, ts, "short", entry, sl, [tp1, tp2], 0.7, row["session"],
                    "bear_ob_retest", price_to_pips(pair, sl - entry),
                    meta={"pattern_hit": False, "structure_hit": True, "smc_hit": True,
                          "volume_score": float(row.get("participation", 0.5)) if pd.notna(row.get("participation")) else 0.5,
                          "trend_aligned": row["close"] < row.get("ema50", row["close"])},
                ))
        return out
