"""Turtle Soup (Raschke/Connors 1996) — 20-Day Failed Breakout Reversal.

Konsept (Linda Raschke & Laurence Connors "Street Smarts" 1996):
  - Original Turtle system (Dennis/Eckhardt 1983) buys/sells 20-day breakouts.
  - Pattern is widely-followed → stops cluster just BEYOND 20D extremes.
  - When price ticks beyond extreme but closes back inside range (failure),
    it is a stop-run that traps breakout traders → smart-money fades.
  - Structural INVERSE of donchian_breakout (which is in production pool).

Bearish Turtle Soup (SHORT):
  - high[t] > max(high[t-20:t-1])         (new 20-day high made)
  - close[t] < max(high[t-20:t-1])        (closed BACK INSIDE prior 20D range)
  - body_ratio = |close-open|/(high-low) > 0.30  (rejection candle, not doji)
  - Bearish close (close < open) OR upper-wick > 50% of bar range
  - ATR%(14) >= 0.5%
  - Skip if strong-impulse t-bar: close[t] >= close[t-1] + 2 × ATR  (real momentum break, not failure)
  - Cooldown 3 bar same side

Bullish Turtle Soup (LONG, mirror): 20-day low + reclaim + body rejection.

Targets:
  - SL: SHORT: high[t] + 0.25 * ATR(14); LONG: low[t] - 0.25 * ATR(14)
  - TP1: 1.0R (close 50%)
  - TP2: 2.0R (close 30%)
  - Runner: 20% — engine default trail
  - Implicit time exit: engine runner_force_exit_bars=30 default

Lookahead-free audit:
  - rolling(20).max().shift(1) / rolling(20).min().shift(1) → prior 20D extremes
    EXCLUDING current bar
  - All filters use t-1 close or t-bar OHLC (current-bar OHLC known at close[t])
  - Entry decided at close[t], executed t+1 open (decision_after_close=True)
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from price_action.contracts import Signal
from price_action.logging_config import logger
from price_action.strategies.base import Strategy, StrategyManifest
from price_action.strategies.classic_pa import _atr, _ema


# Engineering SEC21 taxonomy hook
STRATEGY_CLASS = "mean_reversion"


def _default_manifest() -> StrategyManifest:
    raw = {
        "name": "turtle_soup_20d",
        "version": "1.0.0",
        "description": (
            "Raschke/Connors 1996 Turtle Soup: fade 20-day high/low breakout that "
            "reclaims back inside prior range with body-rejection candle. Mean-rev."
        ),
        "trend_filter": {"type": "ema", "period": 50, "required": False},
        "signals": {
            "patterns": [
                {
                    "id": "turtle_soup_short",
                    "enabled": True,
                    "weight": 2.0,
                    "params": {
                        "lookback_bars": 20,
                        "body_ratio_min": 0.30,
                        "upper_wick_min_ratio": 0.50,
                        "sl_atr_mult": 0.25,
                        "tp_r_multiple": 2.0,
                        "impulse_atr_mult": 2.0,
                        "atr_min_pct": 0.005,
                        "cooldown_bars": 3,
                    },
                },
                {
                    "id": "turtle_soup_long",
                    "enabled": True,
                    "weight": 2.0,
                    "params": {
                        "lookback_bars": 20,
                        "body_ratio_min": 0.30,
                        "lower_wick_min_ratio": 0.50,
                        "sl_atr_mult": 0.25,
                        "tp_r_multiple": 2.0,
                        "impulse_atr_mult": 2.0,
                        "atr_min_pct": 0.005,
                        "cooldown_bars": 3,
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


class TurtleSoup20DStrategy(Strategy):
    """Raschke/Connors Turtle Soup: 20-day failed BO fade (mean-reversion)."""

    name = "turtle_soup_20d"

    def _get_param(self, pattern_id: str, key: str, default: Any) -> Any:
        for p in self.manifest.signals.patterns:
            if p.id == pattern_id:
                return p.params.get(key, default)
        return default

    def prepare_features(self, df: pd.DataFrame) -> pd.DataFrame:
        if df.empty:
            return df.copy()
        df = df.sort_values("ts").reset_index(drop=True).copy()

        lb = int(self._get_param("turtle_soup_short", "lookback_bars", 20))

        df["atr14"] = _atr(df, 14)
        df["atr_pct"] = df["atr14"] / df["close"]
        df["ema50"] = _ema(df["close"], 50)

        # Prior 20D extremes EXCLUDING current bar (shift(1))
        df["hh20_prior"] = df["high"].rolling(lb, min_periods=lb).max().shift(1)
        df["ll20_prior"] = df["low"].rolling(lb, min_periods=lb).min().shift(1)

        # Bar geometry helpers
        df["bar_range"] = (df["high"] - df["low"]).clip(lower=1e-9)
        df["body"] = (df["close"] - df["open"]).abs()
        df["body_ratio"] = df["body"] / df["bar_range"]
        # upper wick: distance from MAX(open,close) to high
        max_oc = np.maximum(df["open"].to_numpy(), df["close"].to_numpy())
        min_oc = np.minimum(df["open"].to_numpy(), df["close"].to_numpy())
        df["upper_wick_ratio"] = (df["high"].to_numpy() - max_oc) / df["bar_range"].to_numpy()
        df["lower_wick_ratio"] = (min_oc - df["low"].to_numpy()) / df["bar_range"].to_numpy()

        # Strong-impulse skip: close gain/drop > 2 * ATR
        df["impulse_up"] = (df["close"] - df["close"].shift(1)) / df["atr14"]
        df["impulse_dn"] = (df["close"].shift(1) - df["close"]) / df["atr14"]

        return df

    def generate_signals(self, df: pd.DataFrame) -> list[Signal]:
        if df.empty:
            return []
        if "atr14" not in df.columns:
            df = self.prepare_features(df)

        signals_cfg = self.manifest.signals
        filters = signals_cfg.filters
        min_score = float(signals_cfg.confluence.min_score)

        lb = int(self._get_param("turtle_soup_short", "lookback_bars", 20))
        body_min = float(self._get_param("turtle_soup_short", "body_ratio_min", 0.30))
        upper_wick_min = float(self._get_param("turtle_soup_short", "upper_wick_min_ratio", 0.50))
        lower_wick_min = float(self._get_param("turtle_soup_long", "lower_wick_min_ratio", 0.50))
        sl_mult = float(self._get_param("turtle_soup_short", "sl_atr_mult", 0.25))
        tp_r = float(self._get_param("turtle_soup_short", "tp_r_multiple", 2.0))
        impulse_mult = float(self._get_param("turtle_soup_short", "impulse_atr_mult", 2.0))
        cooldown = int(self._get_param("turtle_soup_short", "cooldown_bars", 3))
        atr_min_pct = float(getattr(filters, "atr_min_pct", 0.005) or 0.005)

        short_w = next((p.weight for p in signals_cfg.patterns if p.id == "turtle_soup_short"), 2.0)
        long_w = next((p.weight for p in signals_cfg.patterns if p.id == "turtle_soup_long"), 2.0)

        venue = str(df["venue"].iloc[0]) if "venue" in df.columns else "unknown"
        symbol = str(df["symbol"].iloc[0]) if "symbol" in df.columns else "UNKNOWN"
        timeframe = str(df["timeframe"].iloc[0]) if "timeframe" in df.columns else "1d"

        highs = df["high"].to_numpy(dtype=float)
        lows = df["low"].to_numpy(dtype=float)
        opens = df["open"].to_numpy(dtype=float)
        closes = df["close"].to_numpy(dtype=float)
        atrs = df["atr14"].to_numpy(dtype=float)
        atr_pct = df["atr_pct"].to_numpy(dtype=float)
        hh20p = df["hh20_prior"].to_numpy(dtype=float)
        ll20p = df["ll20_prior"].to_numpy(dtype=float)
        body_r = df["body_ratio"].to_numpy(dtype=float)
        upper_w = df["upper_wick_ratio"].to_numpy(dtype=float)
        lower_w = df["lower_wick_ratio"].to_numpy(dtype=float)
        impulse_up = df["impulse_up"].to_numpy(dtype=float)
        impulse_dn = df["impulse_dn"].to_numpy(dtype=float)
        ts_arr = df["ts"].to_numpy()
        n_bars = len(df)

        out: list[Signal] = []
        last_long_ts = -99
        last_short_ts = -99

        # Need ATR warmup (~14 bars) and rolling-20 warmup (20 bars).
        # Start at index 25 for safety.
        start_idx = max(lb + 5, 25)

        for t in range(start_idx, n_bars):
            atr_t = atrs[t]
            if np.isnan(atr_t) or atr_t <= 0:
                continue
            if atr_min_pct > 0 and not np.isnan(atr_pct[t]) and atr_pct[t] < atr_min_pct:
                continue
            if np.isnan(hh20p[t]) or np.isnan(ll20p[t]):
                continue

            o, h, l, c = opens[t], highs[t], lows[t], closes[t]

            # ----- SHORT: Turtle Soup bearish (new 20D high + reclaim back inside) -----
            if t > last_short_ts + cooldown:
                if (h > hh20p[t] and                       # new 20D high
                    c < hh20p[t] and                       # closed back inside prior 20D range
                    body_r[t] > body_min and               # decisive rejection bar
                    (c < o or upper_w[t] > upper_wick_min)  # bearish close OR upper wick prominence
                    ):
                    # Skip strong-impulse t bar
                    imp = impulse_up[t] if not np.isnan(impulse_up[t]) else 0.0
                    if imp < impulse_mult:
                        sl_price = h + sl_mult * atr_t
                        entry_ref = c
                        risk = sl_price - entry_ref
                        if risk > 0:
                            tp_price = entry_ref - tp_r * risk
                            score = short_w
                            if score >= min_score:
                                sig = self.emit_signal(
                                    ts=pd.Timestamp(ts_arr[t]).to_pydatetime(),
                                    venue=venue, symbol=symbol, timeframe=timeframe,
                                    direction="short",
                                    pattern_id="turtle_soup_short",
                                    confluence_score=float(score),
                                    sl_price=float(sl_price),
                                    tp_price=float(tp_price),
                                    suggested_size_atr=1.0,
                                    metadata={
                                        "hh20_prior": float(hh20p[t]),
                                        "penetration_atr": float((h - hh20p[t]) / atr_t) if atr_t > 0 else None,
                                        "reclaim_distance": float(hh20p[t] - c),
                                        "body_ratio": float(body_r[t]),
                                        "upper_wick_ratio": float(upper_w[t]),
                                        "impulse_z": float(imp),
                                    },
                                )
                                out.append(sig)
                                last_short_ts = t

            # ----- LONG: Turtle Soup bullish (new 20D low + reclaim back inside) -----
            if t > last_long_ts + cooldown:
                if (l < ll20p[t] and                        # new 20D low
                    c > ll20p[t] and                        # closed back inside prior 20D range
                    body_r[t] > body_min and                # decisive rejection bar
                    (c > o or lower_w[t] > lower_wick_min)  # bullish close OR lower wick prominence
                    ):
                    # Skip strong-impulse (down) bar
                    imp = impulse_dn[t] if not np.isnan(impulse_dn[t]) else 0.0
                    if imp < impulse_mult:
                        sl_price = l - sl_mult * atr_t
                        entry_ref = c
                        risk = entry_ref - sl_price
                        if risk > 0:
                            tp_price = entry_ref + tp_r * risk
                            score = long_w
                            if score >= min_score:
                                sig = self.emit_signal(
                                    ts=pd.Timestamp(ts_arr[t]).to_pydatetime(),
                                    venue=venue, symbol=symbol, timeframe=timeframe,
                                    direction="long",
                                    pattern_id="turtle_soup_long",
                                    confluence_score=float(score),
                                    sl_price=float(sl_price),
                                    tp_price=float(tp_price),
                                    suggested_size_atr=1.0,
                                    metadata={
                                        "ll20_prior": float(ll20p[t]),
                                        "penetration_atr": float((ll20p[t] - l) / atr_t) if atr_t > 0 else None,
                                        "reclaim_distance": float(c - ll20p[t]),
                                        "body_ratio": float(body_r[t]),
                                        "lower_wick_ratio": float(lower_w[t]),
                                        "impulse_z": float(imp),
                                    },
                                )
                                out.append(sig)
                                last_long_ts = t

        self._log.bind(n=len(out), bars=len(df)).info("turtle_soup_20d.signals.generated")
        return out
