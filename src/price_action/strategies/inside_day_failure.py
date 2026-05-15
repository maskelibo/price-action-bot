"""Inside Day Failure (IDF) strategy — Tom Dante / Adam Grimes failure-test on Inside Day.

Konsept (bullish IDF / LONG):
  - Bar t-1 = Inside Day: high[t-1] < high[t-2] AND low[t-1] > low[t-2]
  - Bar t: low[t] < ID_low (false breakdown below ID low)
  - Bar t: close[t] > ID_low (reclaim — kapanis ID low ustunde)
  - Bar t: close[t] > open[t] (bullish bar body)
  - Body ratio |close-open| / (high-low) > 0.30 (rejection bar)

Bearish IDF (SHORT, mirror): high[t] > ID_high AND close[t] < ID_high AND bearish body.

Targets:
  - SL: LONG: low[t] - 0.25 * ATR(14); SHORT: high[t] + 0.25 * ATR(14)
  - TP1: ID range opposite side (LONG: ID_high; SHORT: ID_low) — partial 50%
  - TP2: 2.0R (R-multiple) — partial 30%
  - Runner: 20%, engine default trail

Filtreler:
  - ATR%(14) > 0.5
  - ID range / ATR <= 1.5 (ID gercekten dar olmali)
  - Optional trend filter (manifest param `require_trend`): LONG > EMA50, SHORT < EMA50
  - Cooldown: same side 5 bar

Lookahead-free: ID tespiti bar t-1 (already closed); failure trigger bar t close;
entry bar t+1 open. Engine convention decision_after_close=True.
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
        "name": "inside_day_failure",
        "version": "1.0.0",
        "description": (
            "Inside Day Failure (Tom Dante / Adam Grimes failure test). "
            "Bullish: ID + next bar low<ID_low + close>ID_low + bullish body. Mirror short."
        ),
        "trend_filter": {"type": "ema", "period": 50, "required": False},
        "signals": {
            "patterns": [
                {
                    "id": "idf_long",
                    "enabled": True,
                    "weight": 2.0,
                    "params": {
                        "id_range_atr_max": 1.5,
                        "sl_atr_mult": 0.25,
                        "body_ratio_min": 0.30,
                        "tp1_at_id_high": True,
                        "tp_r_multiple": 2.0,
                        "cooldown_bars": 5,
                        "require_trend": False,
                    },
                },
                {
                    "id": "idf_short",
                    "enabled": True,
                    "weight": 2.0,
                    "params": {
                        "id_range_atr_max": 1.5,
                        "sl_atr_mult": 0.25,
                        "body_ratio_min": 0.30,
                        "tp1_at_id_low": True,
                        "tp_r_multiple": 2.0,
                        "cooldown_bars": 5,
                        "require_trend": False,
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


class InsideDayFailureStrategy(Strategy):
    """Inside Day Failure (Tom Dante / Adam Grimes)."""

    name = "inside_day_failure"

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

        # Inside Day mask (vectorized): bar[t-1] strictly inside bar[t-2]
        # NOTE: applied at bar t-1, used at bar t for failure detection.
        h_prev1 = df["high"].shift(1)
        l_prev1 = df["low"].shift(1)
        h_prev2 = df["high"].shift(2)
        l_prev2 = df["low"].shift(2)
        df["is_id_prev"] = (h_prev1 < h_prev2) & (l_prev1 > l_prev2)
        df["id_high"] = h_prev1
        df["id_low"] = l_prev1
        df["id_range"] = h_prev1 - l_prev1

        # Volume z (60-bar)
        vol = df["volume"]
        vmean = vol.rolling(60, min_periods=10).mean()
        vstd = vol.rolling(60, min_periods=10).std(ddof=0)
        df["vol_z"] = (vol - vmean) / vstd.replace(0, np.nan)

        return df

    def generate_signals(self, df: pd.DataFrame) -> list[Signal]:
        if df.empty:
            return []
        if "is_id_prev" not in df.columns:
            df = self.prepare_features(df)

        signals_cfg = self.manifest.signals
        filters = signals_cfg.filters
        min_score = float(signals_cfg.confluence.min_score)

        id_range_atr_max = float(self._get_param("idf_long", "id_range_atr_max", 1.5))
        sl_atr_mult = float(self._get_param("idf_long", "sl_atr_mult", 0.25))
        body_ratio_min = float(self._get_param("idf_long", "body_ratio_min", 0.30))
        tp_r = float(self._get_param("idf_long", "tp_r_multiple", 2.0))
        cooldown = int(self._get_param("idf_long", "cooldown_bars", 5))
        require_trend = bool(self._get_param("idf_long", "require_trend", False))

        long_w = next((p.weight for p in signals_cfg.patterns if p.id == "idf_long"), 2.0)
        short_w = next((p.weight for p in signals_cfg.patterns if p.id == "idf_short"), 2.0)

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
        ema50_arr = df["ema50"].to_numpy(dtype=float)
        is_id = df["is_id_prev"].to_numpy(dtype=bool)
        id_high_arr = df["id_high"].to_numpy(dtype=float)
        id_low_arr = df["id_low"].to_numpy(dtype=float)
        id_range_arr = df["id_range"].to_numpy(dtype=float)
        ts_arr = df["ts"].to_numpy()
        n = len(df)

        out: list[Signal] = []
        last_long_ts = -99
        last_short_ts = -99

        for t in range(2, n):
            atr_t = atrs[t]
            if np.isnan(atr_t) or atr_t <= 0:
                continue
            if atr_min_pct > 0 and not np.isnan(atr_pct[t]) and atr_pct[t] < atr_min_pct:
                continue
            if not is_id[t]:
                continue
            id_h = id_high_arr[t]
            id_l = id_low_arr[t]
            id_r = id_range_arr[t]
            if np.isnan(id_h) or np.isnan(id_l) or id_r <= 0:
                continue
            if id_r / atr_t > id_range_atr_max:
                continue
            bar_range = highs[t] - lows[t]
            if bar_range <= 0:
                continue
            body = abs(closes[t] - opens[t])
            body_ratio = body / bar_range
            if body_ratio < body_ratio_min:
                continue

            # ----- LONG: false breakdown reclaim -----
            if (t > last_long_ts + cooldown and
                lows[t] < id_l and
                closes[t] > id_l and
                closes[t] > opens[t]):
                if require_trend and closes[t] <= ema50_arr[t]:
                    pass  # skip
                else:
                    sl_price = lows[t] - sl_atr_mult * atr_t
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
                                pattern_id="idf_long",
                                confluence_score=float(score),
                                sl_price=float(sl_price),
                                tp_price=float(tp_price),
                                suggested_size_atr=1.0,
                                metadata={
                                    "id_high": float(id_h),
                                    "id_low": float(id_l),
                                    "id_range_atr": float(id_r / atr_t),
                                    "body_ratio": float(body_ratio),
                                    "sweep_below_atr": float((id_l - lows[t]) / atr_t),
                                },
                            )
                            out.append(sig)
                            last_long_ts = t
                            continue  # one signal per bar

            # ----- SHORT: false breakout reclaim -----
            if (t > last_short_ts + cooldown and
                highs[t] > id_h and
                closes[t] < id_h and
                closes[t] < opens[t]):
                if require_trend and closes[t] >= ema50_arr[t]:
                    pass  # skip
                else:
                    sl_price = highs[t] + sl_atr_mult * atr_t
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
                                pattern_id="idf_short",
                                confluence_score=float(score),
                                sl_price=float(sl_price),
                                tp_price=float(tp_price),
                                suggested_size_atr=1.0,
                                metadata={
                                    "id_high": float(id_h),
                                    "id_low": float(id_l),
                                    "id_range_atr": float(id_r / atr_t),
                                    "body_ratio": float(body_ratio),
                                    "sweep_above_atr": float((highs[t] - id_h) / atr_t),
                                },
                            )
                            out.append(sig)
                            last_short_ts = t

        self._log.bind(n=len(out), bars=len(df)).info("inside_day_failure.signals.generated")
        return out
