"""VSA Bag Holding / Absorpsiyon — long mean-reversion.

Referans: `knowledge/books/vsa_volume_spread_analysis.md` §4.4
Pre-reg : `memory/researcher/hypotheses/2026-05-14-vol-d3-bag-holding-absorption.md`

Konsept (Williams / Coulling):
  Bag Holding (absorpsiyon) = aşağı bar + dar spread + yüksek hacim + dar gövde.
  "Effort >> Result" — büyük para sessizce satışları emiyor, fiyat hareket etmez.
  Wyckoff Phase B accumulation imzası. Confirmation bar (T+1) bullish kapanış
  → long mean-reversion entry.

Mekanik kurallar (lookahead-free):
  Bar T (absorpsiyon):
    1. down_bar          : close[T] < open[T]
    2. narrow_spread     : (high[T] - low[T]) < narrow_spread_mult × ATR(20)[T-1]
    3. high_volume       : volume[T] > vol_sma_mult × SMA(volume, 20)[T-1]
    4. small_body        : |close[T] - open[T]| < 0.40 × (high[T] - low[T])
    5. atr_min_pct       : ATR(20)[T-1] / close[T-1] > 0.005

  Bar T+1 (confirmation):
    6. bullish_close     : close[T+1] > close[T]
    7. range_hold        : low[T+1] > low[T]
    Cooldown 5 bar

Entry: bar T+1 close → engine T+2 open.

SL: low[T] - 0.50 * ATR(20)[T-1]
TP: 2R primary, 1R partial, runner.

NOT: LONG-ONLY (mean reversion). Short mirror (no-supply rally) yapısal olarak
çok yakın bag-holding'e — ayrı hipotez tutmadık (overlap riski yüksek).

Lookahead audit:
  - Tüm threshold'lar T-1 SMA/ATR (shift(1))
  - Confirmation bar T+1 close kullanılır, sinyal T+1 close anında emit
  - Engine T+2 open fill (decision_after_close=True convention)
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
        "name": "vsa_bag_holding",
        "version": "1.0.0",
        "description": (
            "VSA Bag Holding / Absorption: narrow-spread down bar + high volume + "
            "small body + next-bar bullish confirmation -> long mean-reversion."
        ),
        "trend_filter": {"type": "none", "period": 50, "required": False},
        "signals": {
            "patterns": [
                {
                    "id": "vsa_bag_holding_long",
                    "enabled": True,
                    "weight": 2.0,
                    "params": {
                        "atr_window": 20,
                        "vol_sma_window": 20,
                        "narrow_spread_mult": 1.0,   # spread < 1.0 * ATR
                        "vol_sma_mult": 1.5,         # vol > 1.5 * SMA
                        "body_ratio_max": 0.40,      # body < 0.40 * range
                        "sl_atr_mult": 0.50,
                        "tp_r_multiple": 2.0,
                        "atr_min_pct": 0.005,
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


class VSABagHoldingStrategy(Strategy):
    """VSA Bag Holding / Absorption — long mean-reversion strategy (2-bar pattern)."""

    name = "vsa_bag_holding"

    def _get_param(self, key: str, default: Any) -> Any:
        for p in self.manifest.signals.patterns:
            if p.id == "vsa_bag_holding_long":
                return p.params.get(key, default)
        return default

    def prepare_features(self, df: pd.DataFrame) -> pd.DataFrame:
        if df.empty:
            return df.copy()
        df = df.sort_values("ts").reset_index(drop=True).copy()

        atr_win = int(self._get_param("atr_window", 20))
        vol_win = int(self._get_param("vol_sma_window", 20))

        df["atr20"] = _atr(df, atr_win)
        df["atr20_lag1"] = df["atr20"].shift(1)
        df["atr_pct_lag1"] = (df["atr20"].shift(1) / df["close"].shift(1)).replace(0, np.nan)

        df["vol_sma20_lag1"] = df["volume"].rolling(vol_win, min_periods=max(5, vol_win // 4)).mean().shift(1)

        # Bar geometry (T = current bar — used for "absorption" diagnostic)
        df["bar_range"] = (df["high"] - df["low"]).clip(lower=1e-9)
        df["body_abs"] = (df["close"] - df["open"]).abs()
        df["body_ratio"] = df["body_abs"] / df["bar_range"]
        df["is_down_bar"] = (df["close"] < df["open"]).astype(int)

        df["ema50"] = _ema(df["close"], 50)

        return df

    def generate_signals(self, df: pd.DataFrame) -> list[Signal]:
        if df.empty:
            return []
        if "atr20_lag1" not in df.columns:
            df = self.prepare_features(df)

        signals_cfg = self.manifest.signals
        filters = signals_cfg.filters
        min_score = float(signals_cfg.confluence.min_score)

        narrow_mult = float(self._get_param("narrow_spread_mult", 1.0))
        vol_mult = float(self._get_param("vol_sma_mult", 1.5))
        body_max = float(self._get_param("body_ratio_max", 0.40))
        sl_mult = float(self._get_param("sl_atr_mult", 0.50))
        tp_r = float(self._get_param("tp_r_multiple", 2.0))
        atr_min_pct = float(getattr(filters, "atr_min_pct", 0.005) or 0.005)
        cooldown = int(self._get_param("cooldown_bars", 5))

        long_w = next((p.weight for p in signals_cfg.patterns if p.id == "vsa_bag_holding_long"), 2.0)

        venue = str(df["venue"].iloc[0]) if "venue" in df.columns else "unknown"
        symbol = str(df["symbol"].iloc[0]) if "symbol" in df.columns else "UNKNOWN"
        timeframe = str(df["timeframe"].iloc[0]) if "timeframe" in df.columns else "1d"

        opens = df["open"].to_numpy(dtype=float)
        highs = df["high"].to_numpy(dtype=float)
        lows = df["low"].to_numpy(dtype=float)
        closes = df["close"].to_numpy(dtype=float)
        vols = df["volume"].to_numpy(dtype=float)
        atr_lag = df["atr20_lag1"].to_numpy(dtype=float)
        atr_pct_lag = df["atr_pct_lag1"].to_numpy(dtype=float)
        vol_sma_lag = df["vol_sma20_lag1"].to_numpy(dtype=float)
        body_r = df["body_ratio"].to_numpy(dtype=float)
        ts_arr = df["ts"].to_numpy()
        n_bars = len(df)

        out: list[Signal] = []
        last_long_ts = -99

        start_idx = max(25, 20 + 5)

        # We need T (absorption bar) and T+1 (confirmation). Emit on bar t=T+1.
        # Loop variable: t = T+1 (confirmation bar)
        for t in range(start_idx, n_bars):
            T = t - 1  # absorption bar index
            if T < start_idx - 1:
                continue

            # Threshold parameters reference ATR/vol_sma at bar T's t-1 (= T-1)
            # which in array index is atr_lag[T] (since atr_lag is shift(1))
            atr_t = atr_lag[T]
            if np.isnan(atr_t) or atr_t <= 0:
                continue
            if atr_min_pct > 0 and (np.isnan(atr_pct_lag[T]) or atr_pct_lag[T] < atr_min_pct):
                continue
            if np.isnan(vol_sma_lag[T]) or vol_sma_lag[T] <= 0:
                continue

            o_T, h_T, l_T, c_T, v_T = opens[T], highs[T], lows[T], closes[T], vols[T]

            if t <= last_long_ts + cooldown:
                continue

            # --- Absorption bar (T) conditions ---
            # 1. down bar
            if c_T >= o_T:
                continue
            # 2. narrow spread
            spread_T = h_T - l_T
            if spread_T >= narrow_mult * atr_t:
                continue
            # 3. high volume
            if v_T <= vol_mult * vol_sma_lag[T]:
                continue
            # 4. small body
            if body_r[T] >= body_max:
                continue

            # --- Confirmation bar (T+1 = t) conditions ---
            # 5. bullish close: close[t] > close[T]
            if closes[t] <= c_T:
                continue
            # 6. range hold: low[t] > low[T]
            if lows[t] <= l_T:
                continue

            # All conditions met — LONG signal on bar t (T+1) close
            sl_price = l_T - sl_mult * atr_t
            entry_ref = closes[t]
            risk = entry_ref - sl_price
            if risk <= 0:
                continue
            tp_price = entry_ref + tp_r * risk
            score = long_w
            if score < min_score:
                continue

            sig = self.emit_signal(
                ts=pd.Timestamp(ts_arr[t]).to_pydatetime(),
                venue=venue, symbol=symbol, timeframe=timeframe,
                direction="long",
                pattern_id="vsa_bag_holding_long",
                confluence_score=float(score),
                sl_price=float(sl_price),
                tp_price=float(tp_price),
                suggested_size_atr=1.0,
                metadata={
                    "absorption_bar_idx": int(T),
                    "spread_atr": float(spread_T / atr_t) if atr_t > 0 else None,
                    "vol_ratio": float(v_T / vol_sma_lag[T]) if vol_sma_lag[T] > 0 else None,
                    "body_ratio_T": float(body_r[T]),
                    "confirm_close_above": float((closes[t] - c_T) / atr_t) if atr_t > 0 else None,
                    "atr20": float(atr_t),
                    "absorption_low": float(l_T),
                },
            )
            out.append(sig)
            last_long_ts = t

        self._log.bind(n=len(out), bars=len(df)).info("vsa_bag_holding.signals.generated")
        return out
