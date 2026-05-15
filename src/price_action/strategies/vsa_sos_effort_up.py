"""VSA Effort-to-Move-Up (Sign of Strength / SOS) — long trend continuation.

Referans: `knowledge/books/vsa_volume_spread_analysis.md` §4.7, §10
Pre-reg : `memory/researcher/hypotheses/2026-05-14-vol-d1-sos-effort-up.md`

Konsept (Tom Williams / VSA):
  Effort to Move Up = geniş yukarı bar + üst çeyrek kapanış + 3-bar high breakout
  + climactic-zone hacim. "Effort" (hacim) ve "result" (fiyat hareketi) UYUMLU
  — kurumsal alıcı momentum. SOS = Sign of Strength.

Mekanik kurallar (lookahead-free):
  1. up_bar          : close[t] > open[t]
  2. wide_spread     : (high[t] - low[t]) > spread_atr_mult × ATR(20)[t-1]
  3. upper_close     : close[t] > low[t] + close_pos_min × (high[t] - low[t])
                       — yani close en az %70 yukarıda
  4. breakout_3bar   : high[t] > rolling_max(high, 3).shift(1)[t]
                       — prior 3 bar'in high'ını kırar (current bar haric)
  5. high_volume     : volume[t] > vol_sma_mult × rolling_mean(volume, 20).shift(1)[t]
  6. atr_min_pct     : ATR(20)[t-1] / close[t-1] > 0.005 (chop reject)
  7. anti-overlap    : prior bar should NOT already be a 3-bar breakout
                       (high[t-1] <= rolling_max(high[t-4:t-1]))

Lookahead audit:
  - ATR(20) ile spread compare: ATR shift(1) (causal — strategy bar t için
    ATR_{t-1} kullanır)
  - Volume SMA(20).shift(1) — prior 20 bar SMA, current hariç
  - rolling(3).max().shift(1) — prior 3 bar high, current hariç
  - Entry bar t close decision → engine t+1 open fill (decision_after_close)

Hedefler:
  - SL: low[t] − 0.30 × ATR(20)[t-1]
  - TP1: 1.0R close 50%, TP2: 2.0R close 30%, runner 20% trail
  - Time exit: engine runner_force_exit_bars=30 default

NOT: SOS yapısal olarak LONG-ONLY. Bearish simetri ayrı hipotez (HYP-D2 SOW).
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
STRATEGY_CLASS = "trend_continuation"


def _default_manifest() -> StrategyManifest:
    raw = {
        "name": "vsa_sos_effort_up",
        "version": "1.0.0",
        "description": (
            "VSA Effort-to-Move-Up (SOS): wide-spread up bar + 3-bar high breakout "
            "+ upper-quartile close + climactic-zone volume -> long trend continuation."
        ),
        "trend_filter": {"type": "ema", "period": 50, "required": False},
        "signals": {
            "patterns": [
                {
                    "id": "vsa_sos_long",
                    "enabled": True,
                    "weight": 2.0,
                    "params": {
                        "atr_window": 20,
                        "spread_atr_mult": 1.2,        # spread > 1.2 * ATR
                        "vol_sma_window": 20,
                        "vol_sma_mult": 1.5,           # volume > 1.5 * SMA(20)
                        "close_pos_min": 0.70,         # close at top 30% of range
                        "breakout_lookback": 3,        # 3-bar high breakout
                        "anti_overlap_lookback": 4,    # prior bar not already breakout
                        "sl_atr_mult": 0.30,
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


class VSASoSEffortUpStrategy(Strategy):
    """VSA Effort-to-Move-Up (SOS) — long trend continuation strategy."""

    name = "vsa_sos_effort_up"

    def _get_param(self, key: str, default: Any) -> Any:
        for p in self.manifest.signals.patterns:
            if p.id == "vsa_sos_long":
                return p.params.get(key, default)
        return default

    def prepare_features(self, df: pd.DataFrame) -> pd.DataFrame:
        if df.empty:
            return df.copy()
        df = df.sort_values("ts").reset_index(drop=True).copy()

        atr_win = int(self._get_param("atr_window", 20))
        vol_win = int(self._get_param("vol_sma_window", 20))
        bo_lb = int(self._get_param("breakout_lookback", 3))
        anti_lb = int(self._get_param("anti_overlap_lookback", 4))

        # Causal ATR (Wilder) — strategy needs ATR_{t-1} for thresholds
        df["atr20"] = _atr(df, atr_win)
        df["atr20_lag1"] = df["atr20"].shift(1)
        df["atr_pct_lag1"] = (df["atr20"].shift(1) / df["close"].shift(1)).replace(0, np.nan)

        # Volume SMA causal: prior 20-bar mean (current EXCLUDED via shift(1))
        df["vol_sma20_lag1"] = df["volume"].rolling(vol_win, min_periods=max(5, vol_win // 4)).mean().shift(1)

        # Prior N-bar high (current EXCLUDED via shift(1))
        df["hh_prior_bo"] = df["high"].rolling(bo_lb, min_periods=bo_lb).max().shift(1)

        # Anti-overlap: prior bar's anti_lb-bar high lookup
        # high[t-1] vs max(high[t-anti_lb-1 .. t-2])
        # = rolling(anti_lb-1).max().shift(2)  (because high[t-1] should be NEW BO marker)
        # Simpler: prior_bar_max_anti = rolling(anti_lb).max().shift(2)
        # If high.shift(1) > prior_bar_max_anti, prior bar already was a breakout
        df["hh_prior_anti"] = df["high"].rolling(max(1, anti_lb - 1), min_periods=1).max().shift(2)

        # Bar geometry
        df["bar_range"] = (df["high"] - df["low"]).clip(lower=1e-9)
        df["close_pos"] = (df["close"] - df["low"]) / df["bar_range"]
        df["is_up_bar"] = (df["close"] > df["open"]).astype(int)

        # EMA50 trend filter context (metadata)
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

        spread_mult = float(self._get_param("spread_atr_mult", 1.2))
        vol_mult = float(self._get_param("vol_sma_mult", 1.5))
        close_pos_min = float(self._get_param("close_pos_min", 0.70))
        sl_mult = float(self._get_param("sl_atr_mult", 0.30))
        tp_r = float(self._get_param("tp_r_multiple", 2.0))
        atr_min_pct = float(getattr(filters, "atr_min_pct", 0.005) or 0.005)
        cooldown = int(self._get_param("cooldown_bars", 5))

        long_w = next((p.weight for p in signals_cfg.patterns if p.id == "vsa_sos_long"), 2.0)

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
        hh_bo = df["hh_prior_bo"].to_numpy(dtype=float)
        hh_anti = df["hh_prior_anti"].to_numpy(dtype=float)
        close_pos = df["close_pos"].to_numpy(dtype=float)
        ts_arr = df["ts"].to_numpy()
        n_bars = len(df)

        out: list[Signal] = []
        last_long_ts = -99

        # Need ATR warmup + vol SMA warmup + breakout lookback
        start_idx = max(25, 20 + 5)

        for t in range(start_idx, n_bars):
            atr_t = atr_lag[t]
            if np.isnan(atr_t) or atr_t <= 0:
                continue
            if atr_min_pct > 0 and (np.isnan(atr_pct_lag[t]) or atr_pct_lag[t] < atr_min_pct):
                continue
            if np.isnan(vol_sma_lag[t]) or vol_sma_lag[t] <= 0:
                continue
            if np.isnan(hh_bo[t]):
                continue

            o, h, l, c, v = opens[t], highs[t], lows[t], closes[t], vols[t]

            # Cooldown
            if t <= last_long_ts + cooldown:
                continue

            # --- VSA SOS LONG ---
            # 1. up bar
            if c <= o:
                continue
            # 2. wide spread
            spread = h - l
            if spread <= spread_mult * atr_t:
                continue
            # 3. upper-quartile close
            if close_pos[t] < close_pos_min:
                continue
            # 4. 3-bar high breakout (high > prior 3 max)
            if h <= hh_bo[t]:
                continue
            # 5. high volume
            if v <= vol_mult * vol_sma_lag[t]:
                continue
            # 6. anti-overlap: prior bar should NOT already be a breakout
            if not np.isnan(hh_anti[t]):
                # high[t-1] check: is prior bar's high above its own prior-N max?
                prior_high = highs[t - 1] if t - 1 >= 0 else np.nan
                if not np.isnan(prior_high) and prior_high > hh_anti[t]:
                    # prior bar was already breakout — this is multi-bar continuation
                    # Strategy targets the SINGLE-BAR SOS pattern; skip.
                    continue

            # All conditions met — emit LONG signal
            sl_price = l - sl_mult * atr_t
            entry_ref = c
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
                pattern_id="vsa_sos_long",
                confluence_score=float(score),
                sl_price=float(sl_price),
                tp_price=float(tp_price),
                suggested_size_atr=1.0,
                metadata={
                    "spread_atr": float(spread / atr_t) if atr_t > 0 else None,
                    "vol_ratio": float(v / vol_sma_lag[t]) if vol_sma_lag[t] > 0 else None,
                    "close_pos": float(close_pos[t]),
                    "breakout_dist_atr": float((h - hh_bo[t]) / atr_t) if atr_t > 0 else None,
                    "atr20": float(atr_t),
                },
            )
            out.append(sig)
            last_long_ts = t

        self._log.bind(n=len(out), bars=len(df)).info("vsa_sos_effort_up.signals.generated")
        return out
