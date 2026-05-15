"""Connors 2-Period RSI Extreme Fade — Mean-Reversion strategy.

Konsept (Larry Connors / Cesar Alvarez 2008 "Short Term Trading Strategies"):
  - 2-period RSI is hyper-sensitive to short-term reversals (much more than RSI14).
  - In an uptrend (close > EMA200), RSI(2) < 10 + close < 5d-low marks "buy the
    extreme dip"; mean-reverts toward EMA10.
  - Mirror in downtrend.

Bullish RSI2 Fade (LONG):
  - close[t] > EMA200[t]            (long-term bias bullish)
  - RSI2[t] < 10                    (extreme short-term oversold)
  - close[t] < LL5[t-1] (5-bar low excluding today)
  - ATR%(14) >= 0.5%
  - Cooldown 5 bar same side

Bearish RSI2 Fade (SHORT, mirror):
  - close[t] < EMA200[t]
  - RSI2[t] > 90
  - close[t] > HH5[t-1]
  - ATR%, cooldown same.

Targets:
  - SL: LONG: low[t] - 1.0 * ATR(14); SHORT: high[t] + 1.0 * ATR(14)
  - TP1: EMA10[t] (close-to-reversion target) — partial 50%
  - TP2: 2.0R — partial 30%
  - Runner: 20%, engine default trail

Lookahead-free:
  - RSI(2) computed using Wilder method on closes up to and including bar t.
  - EMA200 causal.
  - LL5/HH5 use rolling(5, min_periods=5).{min,max}().shift(1) — so window
    is [t-5, t-1] excluding t (no peek).
  - Entry at t+1 open (engine convention decision_after_close=True).
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from price_action.contracts import Signal
from price_action.logging_config import logger
from price_action.strategies.base import Strategy, StrategyManifest
from price_action.strategies.classic_pa import _atr, _ema


# Engineering SEC21 taxonomy
STRATEGY_CLASS = "mean_reversion"


def _rsi(close: pd.Series, period: int = 2) -> pd.Series:
    """Wilder RSI — vektörize, lookahead-free."""
    delta = close.diff()
    up = delta.clip(lower=0.0)
    down = -delta.clip(upper=0.0)
    # Wilder smoothing = EMA with alpha = 1/period
    avg_up = up.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()
    avg_dn = down.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()
    rs = avg_up / avg_dn.replace(0, np.nan)
    rsi = 100.0 - (100.0 / (1.0 + rs))
    return rsi.fillna(50.0)  # neutral fill for warmup


def _default_manifest() -> StrategyManifest:
    raw = {
        "name": "rsi2_extreme_fade",
        "version": "1.0.0",
        "description": (
            "Connors 2-period RSI extreme fade + EMA200 trend filter + 5d-low/high. "
            "Long oversold-dip in uptrend, short overbought-pop in downtrend."
        ),
        "trend_filter": {"type": "ema", "period": 200, "required": True},
        "signals": {
            "patterns": [
                {
                    "id": "rsi2_long",
                    "enabled": True,
                    "weight": 2.0,
                    "params": {
                        "rsi_period": 2,
                        "rsi_oversold": 10.0,
                        "ema_trend_period": 200,
                        "low_lookback": 5,
                        "sl_atr_mult": 1.0,
                        "tp_r_multiple": 2.0,
                        "cooldown_bars": 5,
                    },
                },
                {
                    "id": "rsi2_short",
                    "enabled": True,
                    "weight": 2.0,
                    "params": {
                        "rsi_period": 2,
                        "rsi_overbought": 90.0,
                        "ema_trend_period": 200,
                        "high_lookback": 5,
                        "sl_atr_mult": 1.0,
                        "tp_r_multiple": 2.0,
                        "cooldown_bars": 5,
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


class RSI2ExtremeFadeStrategy(Strategy):
    """Connors 2-period RSI extreme mean-reversion (LONG + SHORT)."""

    name = "rsi2_extreme_fade"

    def _get_param(self, pattern_id: str, key: str, default: Any) -> Any:
        for p in self.manifest.signals.patterns:
            if p.id == pattern_id:
                return p.params.get(key, default)
        return default

    def prepare_features(self, df: pd.DataFrame) -> pd.DataFrame:
        if df.empty:
            return df.copy()
        df = df.sort_values("ts").reset_index(drop=True).copy()

        rsi_period = int(self._get_param("rsi2_long", "rsi_period", 2))
        ema_period = int(self._get_param("rsi2_long", "ema_trend_period", 200))
        low_lb = int(self._get_param("rsi2_long", "low_lookback", 5))
        high_lb = int(self._get_param("rsi2_short", "high_lookback", 5))

        df["ema_trend"] = _ema(df["close"], ema_period)
        df["ema10"] = _ema(df["close"], 10)
        df["atr14"] = _atr(df, 14)
        df["atr_pct"] = df["atr14"] / df["close"]
        df["rsi2"] = _rsi(df["close"], rsi_period)

        # LL5 / HH5 exclude current bar (shift(1))
        df["ll5"] = df["close"].rolling(low_lb, min_periods=low_lb).min().shift(1)
        df["hh5"] = df["close"].rolling(high_lb, min_periods=high_lb).max().shift(1)

        return df

    def generate_signals(self, df: pd.DataFrame) -> list[Signal]:
        if df.empty:
            return []
        if "rsi2" not in df.columns:
            df = self.prepare_features(df)

        signals_cfg = self.manifest.signals
        filters = signals_cfg.filters
        min_score = float(signals_cfg.confluence.min_score)

        long_oversold = float(self._get_param("rsi2_long", "rsi_oversold", 10.0))
        short_overbought = float(self._get_param("rsi2_short", "rsi_overbought", 90.0))
        sl_mult = float(self._get_param("rsi2_long", "sl_atr_mult", 1.0))
        tp_r = float(self._get_param("rsi2_long", "tp_r_multiple", 2.0))
        cooldown = int(self._get_param("rsi2_long", "cooldown_bars", 5))

        long_w = next((p.weight for p in signals_cfg.patterns if p.id == "rsi2_long"), 2.0)
        short_w = next((p.weight for p in signals_cfg.patterns if p.id == "rsi2_short"), 2.0)
        atr_min_pct = float(getattr(filters, "atr_min_pct", 0.005) or 0.005)

        venue = str(df["venue"].iloc[0]) if "venue" in df.columns else "unknown"
        symbol = str(df["symbol"].iloc[0]) if "symbol" in df.columns else "UNKNOWN"
        timeframe = str(df["timeframe"].iloc[0]) if "timeframe" in df.columns else "1d"

        highs = df["high"].to_numpy(dtype=float)
        lows = df["low"].to_numpy(dtype=float)
        closes = df["close"].to_numpy(dtype=float)
        atrs = df["atr14"].to_numpy(dtype=float)
        atr_pct = df["atr_pct"].to_numpy(dtype=float)
        rsi2 = df["rsi2"].to_numpy(dtype=float)
        ema_t = df["ema_trend"].to_numpy(dtype=float)
        ema10 = df["ema10"].to_numpy(dtype=float)
        ll5 = df["ll5"].to_numpy(dtype=float)
        hh5 = df["hh5"].to_numpy(dtype=float)
        ts_arr = df["ts"].to_numpy()
        n = len(df)

        out: list[Signal] = []
        last_long_ts = -99
        last_short_ts = -99

        for t in range(200, n):  # need EMA200 warmup
            atr_t = atrs[t]
            if np.isnan(atr_t) or atr_t <= 0:
                continue
            if atr_min_pct > 0 and not np.isnan(atr_pct[t]) and atr_pct[t] < atr_min_pct:
                continue
            if np.isnan(ema_t[t]) or np.isnan(rsi2[t]):
                continue

            # ----- LONG: RSI2 oversold in uptrend -----
            if t > last_long_ts + cooldown:
                if (closes[t] > ema_t[t] and
                    rsi2[t] < long_oversold and
                    not np.isnan(ll5[t]) and closes[t] < ll5[t]):

                    sl_price = lows[t] - sl_mult * atr_t
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
                                pattern_id="rsi2_long",
                                confluence_score=float(score),
                                sl_price=float(sl_price),
                                tp_price=float(tp_price),
                                suggested_size_atr=1.0,
                                metadata={
                                    "rsi2": float(rsi2[t]),
                                    "ema_trend": float(ema_t[t]),
                                    "ema10": float(ema10[t]) if not np.isnan(ema10[t]) else None,
                                    "ll5": float(ll5[t]),
                                    "dip_atr": float((entry_ref - ll5[t]) / atr_t) if atr_t > 0 else None,
                                },
                            )
                            out.append(sig)
                            last_long_ts = t

            # ----- SHORT: RSI2 overbought in downtrend -----
            if t > last_short_ts + cooldown:
                if (closes[t] < ema_t[t] and
                    rsi2[t] > short_overbought and
                    not np.isnan(hh5[t]) and closes[t] > hh5[t]):

                    sl_price = highs[t] + sl_mult * atr_t
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
                                pattern_id="rsi2_short",
                                confluence_score=float(score),
                                sl_price=float(sl_price),
                                tp_price=float(tp_price),
                                suggested_size_atr=1.0,
                                metadata={
                                    "rsi2": float(rsi2[t]),
                                    "ema_trend": float(ema_t[t]),
                                    "ema10": float(ema10[t]) if not np.isnan(ema10[t]) else None,
                                    "hh5": float(hh5[t]),
                                    "pop_atr": float((hh5[t] - entry_ref) / atr_t) if atr_t > 0 else None,
                                },
                            )
                            out.append(sig)
                            last_short_ts = t

        self._log.bind(n=len(out), bars=len(df)).info("rsi2_extreme_fade.signals.generated")
        return out
