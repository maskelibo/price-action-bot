"""London Breakout (07:00 UTC).

Asia range = max-min of bars from 21:00 UTC to 07:00 UTC.
At first 15m bar after 07:00 UTC: enter LONG on close > range_high, SHORT on close < range_low.
SL = opposite side of range; TP = 1.5R, 3R.
"""
from __future__ import annotations

import pandas as pd
import numpy as np

from ..contracts import PIP_SIZE, Signal, price_to_pips
from ..session.tagger import tag_session_series
from .base import Strategy, StrategyManifest


class LondonBreakoutStrategy(Strategy):
    name = "london_breakout"

    def __init__(self, manifest=None):
        super().__init__(manifest or StrategyManifest(
            name=self.name, sessions_allowed=["london"],
            sl_atr_mult=1.0, tp_atr_mult=2.0, rr_min=1.5,
            params={"breakout_buffer_atr": 0.10},
        ))

    def generate_signals(self, df: pd.DataFrame, pair: str) -> list[Signal]:
        if df.empty or "session" not in df.columns:
            return []
        idx = pd.DatetimeIndex(df.index)
        # Asia session ranges per UTC date
        sess = df["session"]
        # Identify London-open bar (first bar where session transitions from asia to london)
        is_london = (sess == "london")
        prev_sess = sess.shift(1)
        london_open_bar = is_london & (prev_sess == "asia")
        signals = []
        atr14 = df["atr14"]
        for ts in df.index[london_open_bar.fillna(False)]:
            # Find Asia range: same-day bars before this ts where session == asia OR previous-day asia
            cutoff_start = ts - pd.Timedelta(hours=10)
            window = df.loc[cutoff_start:ts - pd.Timedelta(minutes=1)]
            asia_window = window[window["session"] == "asia"]
            if asia_window.empty:
                continue
            r_high = asia_window["high"].max()
            r_low = asia_window["low"].min()
            row = df.loc[ts]
            a = atr14.loc[ts]
            if not np.isfinite(a) or a <= 0:
                continue
            buf = self.manifest.params["breakout_buffer_atr"] * a
            if row["close"] > r_high + buf:
                entry = float(row["close"])
                sl = float(r_low - 0.2 * a)
                tp1 = entry + (entry - sl) * 1.5
                tp2 = entry + (entry - sl) * 3.0
                sl_pips = price_to_pips(pair, entry - sl)
                signals.append(self._emit(
                    pair, ts, "long", entry, sl, [tp1, tp2], 0.7, "london",
                    "london_breakout_bull", sl_pips,
                    meta={"pattern_hit": True, "structure_hit": True, "smc_hit": False,
                          "volume_score": float(row.get("participation", 0.5)) if pd.notna(row.get("participation")) else 0.5,
                          "trend_aligned": row["close"] > row.get("ema50", row["close"])},
                ))
            elif row["close"] < r_low - buf:
                entry = float(row["close"])
                sl = float(r_high + 0.2 * a)
                tp1 = entry - (sl - entry) * 1.5
                tp2 = entry - (sl - entry) * 3.0
                sl_pips = price_to_pips(pair, sl - entry)
                signals.append(self._emit(
                    pair, ts, "short", entry, sl, [tp1, tp2], 0.7, "london",
                    "london_breakout_bear", sl_pips,
                    meta={"pattern_hit": True, "structure_hit": True, "smc_hit": False,
                          "volume_score": float(row.get("participation", 0.5)) if pd.notna(row.get("participation")) else 0.5,
                          "trend_aligned": row["close"] < row.get("ema50", row["close"])},
                ))
        return signals
