"""3-Bar Reversal (Brooks two-legged pullback) stratejisi.

Hipotez (Al Brooks):
  Trend yonunde 3-bar mini-pullback: ardışık 3 bar trend karşıtı kapanir
  (bullish trend için 3 bearish close), sonra reversal trigger:
  4. bar bullish ve close > prev bar high. Pullback tabanı EMA20 yakınında olmalı.

Long sablon:
  - Trend: close > EMA50 ve EMA50 > EMA200 (HH-HL up trend proxy)
  - Pullback: bar[t-3], bar[t-2], bar[t-1] hepsi bearish (close < open)
              VEYA en az 2 tanesi bearish ve sequence net düşüş
  - Pullback alt nokta: low_min(t-3..t-1) <= EMA20[t-1] + touch_atr*ATR (EMA20'ye dokun)
  - Trigger: bar[t] bullish (close > open) ve close[t] > high[t-1]

Short sablon: simetrik (bullish 3-bar + EMA20 dokun + bearish reversal trigger).

Lookahead-bias-free:
  - Tum koşullar bar t kapanişinda hesaplanir.
  - SL: long icin pullback tabani (low_min(t-3..t-1)) - atr_buffer
        short icin pullback tepesi (high_max(t-3..t-1)) + atr_buffer
  - TP: 2R primary

Cooldown: same_symbol+same_side 5 bar.
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
        "name": "three_bar_reversal",
        "version": "1.0.0",
        "description": (
            "Brooks 3-bar pullback to EMA20 + reversal trigger. "
            "Long: 3 bearish bars + EMA20 touch + bullish close > prev high."
        ),
        "trend_filter": {"type": "ema", "period": 50, "required": True},
        "signals": {
            "patterns": [
                {
                    "id": "three_bar_rev_long",
                    "enabled": True,
                    "weight": 1.5,
                    "params": {
                        "min_pullback_bars": 2,   # 3 of 3 bearish too strict; allow 2/3
                        "ema_touch_atr": 1.0,
                        "atr_buffer": 0.5,
                    },
                },
                {
                    "id": "three_bar_rev_short",
                    "enabled": True,
                    "weight": 1.5,
                    "params": {
                        "min_pullback_bars": 2,
                        "ema_touch_atr": 1.0,
                        "atr_buffer": 0.5,
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
            "stop_loss": {"method": "structural_atr", "atr_buffer": 0.5},
            "take_profit": {"method": "r_multiple", "primary_R": 2.0},
            "position_sizing": {"method": "fixed_fractional", "risk_per_trade": 0.01},
        },
    }
    return StrategyManifest.model_validate(raw)


class ThreeBarReversalStrategy(Strategy):
    """3-Bar Brooks-style pullback reversal."""

    name = "three_bar_reversal"

    def prepare_features(self, df: pd.DataFrame) -> pd.DataFrame:
        if df.empty:
            return df.copy()
        df = df.sort_values("ts").reset_index(drop=True).copy()

        df["ema20"] = _ema(df["close"], 20)
        df["ema50"] = _ema(df["close"], 50)
        df["ema200"] = _ema(df["close"], 200)
        df["atr14"] = _atr(df, 14)
        df["atr_pct"] = df["atr14"] / df["close"]

        df["bear_bar"] = df["close"] < df["open"]
        df["bull_bar"] = df["close"] > df["open"]

        # Pullback bar count (last 3 bars)
        df["bear_count_3"] = df["bear_bar"].shift(1).rolling(3, min_periods=3).sum()
        df["bull_count_3"] = df["bull_bar"].shift(1).rolling(3, min_periods=3).sum()

        # Pullback extremes (3 bars before t)
        df["pullback_low"] = df["low"].shift(1).rolling(3, min_periods=3).min()
        df["pullback_high"] = df["high"].shift(1).rolling(3, min_periods=3).max()

        # EMA20 touch
        ema_prev = df["ema20"].shift(1)
        atr_prev = df["atr14"].shift(1)
        df["ema_touch_long"] = (
            df["pullback_low"] <= ema_prev + 1.0 * atr_prev
        )
        df["ema_touch_short"] = (
            df["pullback_high"] >= ema_prev - 1.0 * atr_prev
        )

        # Volume z
        vol = df["volume"]
        vmean = vol.rolling(60, min_periods=10).mean()
        vstd = vol.rolling(60, min_periods=10).std(ddof=0)
        df["vol_z"] = (vol - vmean) / vstd.replace(0, np.nan)

        return df

    def generate_signals(self, df: pd.DataFrame) -> list[Signal]:
        if df.empty:
            return []
        if "ema_touch_long" not in df.columns:
            df = self.prepare_features(df)

        signals_cfg = self.manifest.signals
        filters_cfg = signals_cfg.filters
        confluence = signals_cfg.confluence

        primary_R = float(
            self.manifest.risk.get("take_profit", {}).get("primary_R", 2.0)
        )
        atr_buffer = float(
            self.manifest.risk.get("stop_loss", {}).get("atr_buffer", 0.5)
        )

        venue = str(df["venue"].iloc[0]) if "venue" in df.columns else "unknown"
        symbol = str(df["symbol"].iloc[0]) if "symbol" in df.columns else "UNKNOWN"
        timeframe = str(df["timeframe"].iloc[0]) if "timeframe" in df.columns else "1d"

        long_w = 1.5
        short_w = 1.5
        min_pb = 2
        ema_touch_atr = 1.0
        for p in signals_cfg.patterns:
            if not p.enabled:
                continue
            if p.id == "three_bar_rev_long":
                long_w = p.weight
                min_pb = int(p.params.get("min_pullback_bars", 2))
                ema_touch_atr = float(p.params.get("ema_touch_atr", 1.0))
            elif p.id == "three_bar_rev_short":
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
        ema20 = df["ema20"].to_numpy(dtype=float)
        ema50 = df["ema50"].to_numpy(dtype=float)
        ema200 = df["ema200"].to_numpy(dtype=float)
        bear_cnt = df["bear_count_3"].to_numpy(dtype=float)
        bull_cnt = df["bull_count_3"].to_numpy(dtype=float)
        pb_low = df["pullback_low"].to_numpy(dtype=float)
        pb_high = df["pullback_high"].to_numpy(dtype=float)
        ts_arr = df["ts"].to_numpy()

        for i in range(4, n):
            atr = atrs[i]
            if np.isnan(atr) or atr <= 0:
                continue
            if atr_min > 0 and not np.isnan(atr_pct[i]) and atr_pct[i] < atr_min:
                continue
            close = closes[i]
            high = highs[i]
            low = lows[i]
            opn = opens[i]
            ema20_p = ema20[i - 1]
            ema50_v = ema50[i]
            ema200_v = ema200[i]
            atr_p = atrs[i - 1]
            if np.isnan(ema20_p) or np.isnan(ema50_v) or np.isnan(ema200_v) or np.isnan(atr_p):
                continue

            # ---- LONG ----
            if i > last_long_idx + cooldown:
                if (close > ema50_v and ema50_v > ema200_v
                    and bear_cnt[i] >= min_pb
                    and pb_low[i] <= ema20_p + ema_touch_atr * atr_p
                    and close > opn  # bullish trigger
                    and close > highs[i - 1]
                ):
                    score = long_w
                    if score >= min_score:
                        # SL: pullback low - atr_buffer
                        sl_price = pb_low[i] - atr_buffer * atr
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
                            pattern_id="three_bar_rev_long",
                            confluence_score=float(score),
                            sl_price=float(sl_price),
                            tp_price=float(tp_price),
                            suggested_size_atr=1.0,
                            metadata={
                                "atr14": atr,
                                "ema20_prev": float(ema20_p),
                                "pullback_low": float(pb_low[i]),
                                "bear_count_3": float(bear_cnt[i]),
                            },
                        )
                        out.append(sig)
                        last_long_idx = i
                        continue

            # ---- SHORT ----
            if i > last_short_idx + cooldown:
                if (close < ema50_v and ema50_v < ema200_v
                    and bull_cnt[i] >= min_pb
                    and pb_high[i] >= ema20_p - ema_touch_atr * atr_p
                    and close < opn  # bearish trigger
                    and close < lows[i - 1]
                ):
                    score = short_w
                    if score < min_score:
                        continue
                    sl_price = pb_high[i] + atr_buffer * atr
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
                        pattern_id="three_bar_rev_short",
                        confluence_score=float(score),
                        sl_price=float(sl_price),
                        tp_price=float(tp_price),
                        suggested_size_atr=1.0,
                        metadata={
                            "atr14": atr,
                            "ema20_prev": float(ema20_p),
                            "pullback_high": float(pb_high[i]),
                            "bull_count_3": float(bull_cnt[i]),
                        },
                    )
                    out.append(sig)
                    last_short_idx = i

        self._log.bind(n=len(out), bars=n).info("three_bar_reversal.signals.generated")
        return out
