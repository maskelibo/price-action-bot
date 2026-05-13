"""NR7 (Narrow Range 7) Breakout v2 — volatility compression breakout.

v1 sprint'te NR7 RED'di (Sharpe 0.24 < 0.5 gate) — parametre dar idi.
Bu v2'de:
  - NR4 ve NR7 ayri pattern (4-bar dar mi, 7-bar dar mi)
  - NR-bar range / ATR ratio esigi (0.7'den dusuk, daha selectif)
  - Breakout bar: SONRAKI bar (signal bar = NR bar, breakout = next bar
    close vs NR.high/low). Bizim mekanigimizde NR bar t-1, signal bar t:
    long  = closes[t] > NR_high  AND  closes[t] > opens[t]
    short = closes[t] < NR_low   AND  closes[t] < opens[t]
  - Trend filtresi opsiyonel (default OFF — NR breakout her iki yonde)
  - Daraltma yonu farketmez (long/short symmetric)

Risk:
  - SL: opposite end of NR-bar +- 0.3*ATR
  - TP: 2.0R

Lookahead-free: NR-bar t-1 kapandiginda hesaplanir; bar t breakout = next bar
close. Bar t kapanir, t+1'de entry.
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from price_action.contracts import Signal
from price_action.logging_config import logger
from price_action.strategies.base import Strategy, StrategyManifest
from price_action.strategies.classic_pa import _atr, _ema


def _default_manifest() -> StrategyManifest:
    raw = {
        "name": "nr7_breakout_v2",
        "version": "2.0.0",
        "description": (
            "NR7 (Narrow Range 7) volatility compression breakout v2. "
            "NR-bar range/ATR threshold + next-bar breakout direction."
        ),
        "trend_filter": {"type": "ema", "period": 50, "required": False},
        "signals": {
            "patterns": [
                {
                    "id": "nr7_breakout_long",
                    "enabled": True,
                    "weight": 2.0,
                    "params": {
                        "nr_window": 7,
                        "max_range_atr": 0.70,
                        "min_break_atr": 0.10,
                        "sl_atr_mult": 0.3,
                        "tp_r_multiple": 2.0,
                    },
                },
                {
                    "id": "nr7_breakout_short",
                    "enabled": True,
                    "weight": 2.0,
                    "params": {
                        "nr_window": 7,
                        "max_range_atr": 0.70,
                        "min_break_atr": 0.10,
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


class NR7BreakoutV2Strategy(Strategy):
    """NR7 volatility compression breakout v2."""

    name = "nr7_breakout_v2"

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

        # Bar range
        df["bar_range"] = df["high"] - df["low"]

        # NR-window: bar[t]'nin range'i son `nr_window` bar icindeki en kucuk mu?
        nw = int(self._get_param("nr7_breakout_long", "nr_window", 7))
        # min over last nw bars (including t)
        rolling_min = df["bar_range"].rolling(nw, min_periods=nw).min()
        # NR bar = bar[t].range == min over [t-nw+1..t]
        df["is_nr_bar"] = (df["bar_range"] == rolling_min) & df["bar_range"].notna()

        # Volume z (60-bar)
        vol = df["volume"]
        vmean = vol.rolling(60, min_periods=10).mean()
        vstd = vol.rolling(60, min_periods=10).std(ddof=0)
        df["vol_z"] = (vol - vmean) / vstd.replace(0, np.nan)

        return df

    def generate_signals(self, df: pd.DataFrame) -> list[Signal]:
        if df.empty:
            return []
        if "is_nr_bar" not in df.columns:
            df = self.prepare_features(df)

        signals_cfg = self.manifest.signals
        filters = signals_cfg.filters
        min_score = float(signals_cfg.confluence.min_score)

        max_range_atr = float(self._get_param("nr7_breakout_long", "max_range_atr", 0.70))
        min_break_atr = float(self._get_param("nr7_breakout_long", "min_break_atr", 0.10))
        sl_atr_mult = float(self._get_param("nr7_breakout_long", "sl_atr_mult", 0.3))
        tp_r = float(self._get_param("nr7_breakout_long", "tp_r_multiple", 2.0))

        long_w = next((p.weight for p in signals_cfg.patterns if p.id == "nr7_breakout_long"), 2.0)
        short_w = next((p.weight for p in signals_cfg.patterns if p.id == "nr7_breakout_short"), 2.0)

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
        bar_range = df["bar_range"].to_numpy(dtype=float)
        is_nr   = df["is_nr_bar"].to_numpy(dtype=bool)
        ts_arr  = df["ts"].to_numpy()
        n = len(df)

        out: list[Signal] = []
        # Cooldown
        last_long_ts = -99
        last_short_ts = -99
        cooldown = 3

        for t in range(1, n):
            atr_t = atrs[t]
            if np.isnan(atr_t) or atr_t <= 0:
                continue
            if atr_min_pct > 0 and not np.isnan(atr_pct[t]) and atr_pct[t] < atr_min_pct:
                continue

            # NR bar = t-1 (bar t = breakout bar)
            nr_idx = t - 1
            if not is_nr[nr_idx]:
                continue
            nr_atr = atrs[nr_idx]
            if np.isnan(nr_atr) or nr_atr <= 0:
                continue
            nr_range = bar_range[nr_idx]
            if nr_range / nr_atr > max_range_atr:
                continue  # NR ama yeterince dar degil

            nr_high = highs[nr_idx]
            nr_low = lows[nr_idx]

            # ----- LONG breakout -----
            if t > last_long_ts + cooldown:
                break_up = closes[t] - nr_high
                if (break_up >= min_break_atr * atr_t and
                    closes[t] > opens[t]):
                    sl_price = nr_low - sl_atr_mult * atr_t
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
                                pattern_id="nr7_breakout_long",
                                confluence_score=float(score),
                                sl_price=float(sl_price),
                                tp_price=float(tp_price),
                                suggested_size_atr=1.0,
                                metadata={
                                    "nr_high": float(nr_high),
                                    "nr_low": float(nr_low),
                                    "nr_range_atr": float(nr_range / nr_atr),
                                    "break_atr": float(break_up / atr_t),
                                    "nr_idx": int(nr_idx),
                                },
                            )
                            out.append(sig)
                            last_long_ts = t
                            continue  # ayni bar'da hem long hem short olmaz

            # ----- SHORT breakout -----
            if t > last_short_ts + cooldown:
                break_down = nr_low - closes[t]
                if (break_down >= min_break_atr * atr_t and
                    closes[t] < opens[t]):
                    sl_price = nr_high + sl_atr_mult * atr_t
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
                                pattern_id="nr7_breakout_short",
                                confluence_score=float(score),
                                sl_price=float(sl_price),
                                tp_price=float(tp_price),
                                suggested_size_atr=1.0,
                                metadata={
                                    "nr_high": float(nr_high),
                                    "nr_low": float(nr_low),
                                    "nr_range_atr": float(nr_range / nr_atr),
                                    "break_atr": float(break_down / atr_t),
                                    "nr_idx": int(nr_idx),
                                },
                            )
                            out.append(sig)
                            last_short_ts = t

        self._log.bind(n=len(out), bars=len(df)).info("nr7_breakout_v2.signals.generated")
        return out
