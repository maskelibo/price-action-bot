"""Microstructure Proxy stratejisi (OHLC-derived buy/sell pressure).

Hipotez (Wyckoff/Brooks-style absorption):
  Taker_buy/total volume oraninin OHLC proxy'si:
     buy_pressure = (close - low) / (high - low)
     0.7+ = aggressive buying (close yakini high) -> potansiyel reversal/continuation
     0.3- = aggressive selling
  3-bar net pressure (rolling 3 sum) extreme + counter-trend bar = reversal sinyal.

Sinyal kurali:

  LONG: yuksek satim baskisi serisi (3-bar avg buy_pressure <= 0.30)
         + bullish trigger bar (close > open, body_ratio >= 0.5,
                                buy_pressure[t] >= 0.70)
         + close > EMA200 (uzun trend filter — tipik bull regime)
         (mean reversion: panic selling absorption sonrasi reflex bounce)

  SHORT: simetrik (yuksek alim baskisi 3-bar + bearish trigger).

Lookahead-bias-free:
  - 3-bar buy_pressure: shift(1) ile [t-3..t-1]
  - Trigger: bar t kapanişinda hesaplanir (close[t], high[t], low[t] bilinir)

Cooldown: 5 bar same_symbol+side.

SL: structural swing (5-bar) +/- atr_buffer
TP: 1.5R primary (mean reversion edge dar, hizli kapat)
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from price_action.contracts import Signal
from price_action.logging_config import logger
from price_action.strategies.base import Strategy, StrategyManifest
from price_action.strategies.classic_pa import _atr, _ema


def _swing_sl(df: pd.DataFrame, direction: str, lookback: int = 5) -> pd.Series:
    if direction == "long":
        return df["low"].shift(1).rolling(lookback, min_periods=1).min()
    return df["high"].shift(1).rolling(lookback, min_periods=1).max()


def _default_manifest() -> StrategyManifest:
    raw = {
        "name": "microstructure_proxy",
        "version": "1.0.0",
        "description": (
            "OHLC buy/sell pressure proxy. 3-bar pressure extreme + counter-trend "
            "trigger = absorption reversal."
        ),
        "trend_filter": {"type": "ema", "period": 200, "required": True},
        "signals": {
            "patterns": [
                {
                    "id": "micro_absorption_long",
                    "enabled": True,
                    "weight": 1.5,
                    "params": {
                        "pressure_window": 3,
                        "low_pressure_max": 0.30,
                        "high_pressure_min": 0.70,
                        "body_min_ratio": 0.50,
                    },
                },
                {
                    "id": "micro_absorption_short",
                    "enabled": True,
                    "weight": 1.5,
                    "params": {
                        "pressure_window": 3,
                        "low_pressure_max": 0.30,
                        "high_pressure_min": 0.70,
                        "body_min_ratio": 0.50,
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
            "stop_loss": {"method": "structural_atr", "swing_lookback": 5,
                          "atr_buffer": 0.5},
            "take_profit": {"method": "r_multiple", "primary_R": 1.5},
            "position_sizing": {"method": "fixed_fractional", "risk_per_trade": 0.01},
        },
    }
    return StrategyManifest.model_validate(raw)


class MicrostructureProxyStrategy(Strategy):
    """OHLC buy/sell pressure proxy — absorption reversal."""

    name = "microstructure_proxy"

    def prepare_features(self, df: pd.DataFrame) -> pd.DataFrame:
        if df.empty:
            return df.copy()
        df = df.sort_values("ts").reset_index(drop=True).copy()

        df["ema50"] = _ema(df["close"], 50)
        df["ema200"] = _ema(df["close"], 200)
        df["atr14"] = _atr(df, 14)
        df["atr_pct"] = df["atr14"] / df["close"]

        # Buy pressure proxy
        rng = (df["high"] - df["low"]).replace(0.0, np.nan)
        df["buy_pressure"] = (df["close"] - df["low"]) / rng
        df["buy_pressure"] = df["buy_pressure"].clip(0.0, 1.0)

        # 3-bar mean (lookahead-free, shift 1)
        pw = 3
        for p in self.manifest.signals.patterns:
            if p.id in ("micro_absorption_long", "micro_absorption_short"):
                pw = int(p.params.get("pressure_window", 3))
                break
        df["pressure_avg_prev"] = df["buy_pressure"].shift(1).rolling(pw, min_periods=pw).mean()

        # Body ratio for trigger
        body = (df["close"] - df["open"]).abs()
        df["body_ratio"] = body / rng

        df["bull_bar"] = df["close"] > df["open"]
        df["bear_bar"] = df["close"] < df["open"]

        # Structural SL
        sl_lb = int(self.manifest.risk.get("stop_loss", {}).get("swing_lookback", 5))
        df["struct_sl_long"] = _swing_sl(df, "long", lookback=sl_lb)
        df["struct_sl_short"] = _swing_sl(df, "short", lookback=sl_lb)

        # Volume z (60-bar)
        vol = df["volume"]
        vmean = vol.rolling(60, min_periods=10).mean()
        vstd = vol.rolling(60, min_periods=10).std(ddof=0)
        df["vol_z"] = (vol - vmean) / vstd.replace(0, np.nan)

        return df

    def generate_signals(self, df: pd.DataFrame) -> list[Signal]:
        if df.empty:
            return []
        if "buy_pressure" not in df.columns:
            df = self.prepare_features(df)

        signals_cfg = self.manifest.signals
        filters_cfg = signals_cfg.filters
        confluence = signals_cfg.confluence

        primary_R = float(self.manifest.risk.get("take_profit", {}).get("primary_R", 1.5))
        atr_buffer = float(self.manifest.risk.get("stop_loss", {}).get("atr_buffer", 0.5))

        venue = str(df["venue"].iloc[0]) if "venue" in df.columns else "unknown"
        symbol = str(df["symbol"].iloc[0]) if "symbol" in df.columns else "UNKNOWN"
        timeframe = str(df["timeframe"].iloc[0]) if "timeframe" in df.columns else "1d"

        long_w = 1.5
        short_w = 1.5
        low_press_max = 0.30
        high_press_min = 0.70
        body_min = 0.50
        for p in signals_cfg.patterns:
            if not p.enabled:
                continue
            if p.id == "micro_absorption_long":
                long_w = p.weight
                low_press_max = float(p.params.get("low_pressure_max", 0.30))
                high_press_min = float(p.params.get("high_pressure_min", 0.70))
                body_min = float(p.params.get("body_min_ratio", 0.50))
            elif p.id == "micro_absorption_short":
                short_w = p.weight

        atr_min = float(getattr(filters_cfg, "atr_min_pct", 0.005) or 0.005)
        min_score = float(confluence.min_score)

        n = len(df)
        out: list[Signal] = []
        cooldown = 5
        last_long_idx = -99
        last_short_idx = -99

        opens = df["open"].to_numpy(dtype=float)
        highs = df["high"].to_numpy(dtype=float)
        lows = df["low"].to_numpy(dtype=float)
        closes = df["close"].to_numpy(dtype=float)
        atrs = df["atr14"].to_numpy(dtype=float)
        atr_pct = df["atr_pct"].to_numpy(dtype=float)
        ema200 = df["ema200"].to_numpy(dtype=float)
        bp_avg = df["pressure_avg_prev"].to_numpy(dtype=float)
        bp_t = df["buy_pressure"].to_numpy(dtype=float)
        body_r = df["body_ratio"].to_numpy(dtype=float)
        sl_long_arr = df["struct_sl_long"].to_numpy(dtype=float)
        sl_short_arr = df["struct_sl_short"].to_numpy(dtype=float)
        ts_arr = df["ts"].to_numpy()

        for i in range(n):
            atr = atrs[i]
            if np.isnan(atr) or atr <= 0:
                continue
            if atr_min > 0 and not np.isnan(atr_pct[i]) and atr_pct[i] < atr_min:
                continue
            close = closes[i]
            opn = opens[i]
            ema = ema200[i]
            if np.isnan(ema) or ema <= 0:
                continue
            if np.isnan(bp_avg[i]) or np.isnan(bp_t[i]) or np.isnan(body_r[i]):
                continue

            # ---- LONG (panic selling absorption -> reflex bounce) ----
            if i > last_long_idx + cooldown:
                if (bp_avg[i] <= low_press_max
                    and close > opn
                    and bp_t[i] >= high_press_min
                    and body_r[i] >= body_min
                    and close > ema  # bull regime
                ):
                    score = long_w
                    if score >= min_score:
                        sl_struct = sl_long_arr[i]
                        if np.isnan(sl_struct) or sl_struct <= 0:
                            sl_price = close - 2.0 * atr
                        else:
                            sl_price = sl_struct - atr_buffer * atr
                        sl_price = min(sl_price, close - 0.5 * atr)
                        if sl_price <= 0:
                            continue
                        risk = close - sl_price
                        if risk <= 0:
                            continue
                        tp_price = close + primary_R * risk
                        sig = self.emit_signal(
                            ts=pd.Timestamp(ts_arr[i]).to_pydatetime(),
                            venue=venue, symbol=symbol, timeframe=timeframe,
                            direction="long",
                            pattern_id="micro_absorption_long",
                            confluence_score=float(score),
                            sl_price=float(sl_price),
                            tp_price=float(tp_price),
                            suggested_size_atr=1.0,
                            metadata={
                                "atr14": atr,
                                "buy_pressure": float(bp_t[i]),
                                "pressure_avg_3": float(bp_avg[i]),
                                "body_ratio": float(body_r[i]),
                            },
                        )
                        out.append(sig)
                        last_long_idx = i
                        continue

            # ---- SHORT (aggressive buying climax -> reversal) ----
            if i > last_short_idx + cooldown:
                if (bp_avg[i] >= 1.0 - low_press_max  # 0.70+
                    and close < opn
                    and bp_t[i] <= 1.0 - high_press_min  # 0.30-
                    and body_r[i] >= body_min
                    and close < ema  # bear regime
                ):
                    score = short_w
                    if score < min_score:
                        continue
                    sl_struct = sl_short_arr[i]
                    if np.isnan(sl_struct) or sl_struct <= 0:
                        sl_price = close + 2.0 * atr
                    else:
                        sl_price = sl_struct + atr_buffer * atr
                    sl_price = max(sl_price, close + 0.5 * atr)
                    risk = sl_price - close
                    if risk <= 0:
                        continue
                    tp_price = close - primary_R * risk
                    if tp_price <= 0:
                        continue
                    sig = self.emit_signal(
                        ts=pd.Timestamp(ts_arr[i]).to_pydatetime(),
                        venue=venue, symbol=symbol, timeframe=timeframe,
                        direction="short",
                        pattern_id="micro_absorption_short",
                        confluence_score=float(score),
                        sl_price=float(sl_price),
                        tp_price=float(tp_price),
                        suggested_size_atr=1.0,
                        metadata={
                            "atr14": atr,
                            "buy_pressure": float(bp_t[i]),
                            "pressure_avg_3": float(bp_avg[i]),
                            "body_ratio": float(body_r[i]),
                        },
                    )
                    out.append(sig)
                    last_short_idx = i

        self._log.bind(n=len(out), bars=n).info("microstructure_proxy.signals.generated")
        return out
