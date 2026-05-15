"""VSA Effort-to-Move-Down (Sign of Weakness / SOW) — short trend continuation.

Referans: `knowledge/books/vsa_volume_spread_analysis.md` §4.14
Pre-reg : `memory/researcher/hypotheses/2026-05-14-vol-d2-sow-effort-down.md`

Konsept (Tom Williams / VSA):
  Effort to Move Down = geniş aşağı bar + alt çeyrek kapanış + 3-bar düşük
  breakdown + climactic-zone hacim. "Effort" (hacim) ve "result" (fiyat hareketi)
  AŞAĞI yönde UYUMLU — kurumsal satıcı momentum. SOW = Sign of Weakness.

Mekanik kurallar (lookahead-free, HYP-D1 SOS'un mirror'ı):
  1. down_bar          : close[t] < open[t]
  2. wide_spread       : (high[t] - low[t]) > spread_atr_mult × ATR(20)[t-1]
  3. lower_close       : close[t] < low[t] + (1 - close_pos_min) × range
                         — yani close en üst %30 değil, alt %30 altında
  4. breakdown_3bar    : low[t] < rolling_min(low, 3).shift(1)[t]
  5. high_volume       : volume[t] > vol_sma_mult × SMA(volume, 20).shift(1)[t]
  6. atr_min_pct       : ATR(20)[t-1] / close[t-1] > 0.005
  7. anti-overlap      : prior bar should NOT already be a 3-bar breakdown
  8. anti-capitulation : close[t] / close[t-5] > 0.85 (avoid catching SC bottom)

NOT: SOW yapısal olarak SHORT-ONLY. SOS (HYP-D1) ayrı hipotez (long-only).
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
        "name": "vsa_sow_effort_down",
        "version": "1.0.0",
        "description": (
            "VSA Effort-to-Move-Down (SOW): wide-spread down bar + 3-bar low "
            "breakdown + lower-quartile close + high volume -> short trend cont."
        ),
        "trend_filter": {"type": "ema", "period": 50, "required": False},
        "signals": {
            "patterns": [
                {
                    "id": "vsa_sow_short",
                    "enabled": True,
                    "weight": 2.0,
                    "params": {
                        "atr_window": 20,
                        "spread_atr_mult": 1.2,
                        "vol_sma_window": 20,
                        "vol_sma_mult": 1.5,
                        "close_pos_max": 0.30,        # close at bottom 30% of range
                        "breakdown_lookback": 3,
                        "anti_overlap_lookback": 4,
                        "anti_capitulation_bars": 5,
                        "anti_capitulation_max_drop": 0.15,  # close[t]/close[t-5] > 0.85
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


class VSASoWEffortDownStrategy(Strategy):
    """VSA Effort-to-Move-Down (SOW) — short trend continuation."""

    name = "vsa_sow_effort_down"

    def _get_param(self, key: str, default: Any) -> Any:
        for p in self.manifest.signals.patterns:
            if p.id == "vsa_sow_short":
                return p.params.get(key, default)
        return default

    def prepare_features(self, df: pd.DataFrame) -> pd.DataFrame:
        if df.empty:
            return df.copy()
        df = df.sort_values("ts").reset_index(drop=True).copy()

        atr_win = int(self._get_param("atr_window", 20))
        vol_win = int(self._get_param("vol_sma_window", 20))
        bd_lb = int(self._get_param("breakdown_lookback", 3))
        anti_lb = int(self._get_param("anti_overlap_lookback", 4))
        cap_bars = int(self._get_param("anti_capitulation_bars", 5))

        df["atr20"] = _atr(df, atr_win)
        df["atr20_lag1"] = df["atr20"].shift(1)
        df["atr_pct_lag1"] = (df["atr20"].shift(1) / df["close"].shift(1)).replace(0, np.nan)

        df["vol_sma20_lag1"] = df["volume"].rolling(vol_win, min_periods=max(5, vol_win // 4)).mean().shift(1)

        # Prior N-bar low (current EXCLUDED)
        df["ll_prior_bd"] = df["low"].rolling(bd_lb, min_periods=bd_lb).min().shift(1)

        # Anti-overlap: prior bar's anti_lb-bar low
        df["ll_prior_anti"] = df["low"].rolling(max(1, anti_lb - 1), min_periods=1).min().shift(2)

        # Anti-capitulation: close[t] / close[t-cap_bars]
        df["cap_ratio"] = df["close"] / df["close"].shift(cap_bars)

        # Bar geometry
        df["bar_range"] = (df["high"] - df["low"]).clip(lower=1e-9)
        df["close_pos"] = (df["close"] - df["low"]) / df["bar_range"]
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

        spread_mult = float(self._get_param("spread_atr_mult", 1.2))
        vol_mult = float(self._get_param("vol_sma_mult", 1.5))
        close_pos_max = float(self._get_param("close_pos_max", 0.30))
        sl_mult = float(self._get_param("sl_atr_mult", 0.30))
        tp_r = float(self._get_param("tp_r_multiple", 2.0))
        atr_min_pct = float(getattr(filters, "atr_min_pct", 0.005) or 0.005)
        cooldown = int(self._get_param("cooldown_bars", 5))
        cap_min_ratio = 1.0 - float(self._get_param("anti_capitulation_max_drop", 0.15))

        short_w = next((p.weight for p in signals_cfg.patterns if p.id == "vsa_sow_short"), 2.0)

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
        ll_bd = df["ll_prior_bd"].to_numpy(dtype=float)
        ll_anti = df["ll_prior_anti"].to_numpy(dtype=float)
        cap_ratio = df["cap_ratio"].to_numpy(dtype=float)
        close_pos = df["close_pos"].to_numpy(dtype=float)
        ts_arr = df["ts"].to_numpy()
        n_bars = len(df)

        out: list[Signal] = []
        last_short_ts = -99

        start_idx = max(25, 20 + 5)

        for t in range(start_idx, n_bars):
            atr_t = atr_lag[t]
            if np.isnan(atr_t) or atr_t <= 0:
                continue
            if atr_min_pct > 0 and (np.isnan(atr_pct_lag[t]) or atr_pct_lag[t] < atr_min_pct):
                continue
            if np.isnan(vol_sma_lag[t]) or vol_sma_lag[t] <= 0:
                continue
            if np.isnan(ll_bd[t]):
                continue

            o, h, l, c, v = opens[t], highs[t], lows[t], closes[t], vols[t]

            if t <= last_short_ts + cooldown:
                continue

            # --- VSA SOW SHORT ---
            # 1. down bar
            if c >= o:
                continue
            # 2. wide spread
            spread = h - l
            if spread <= spread_mult * atr_t:
                continue
            # 3. lower-quartile close
            if close_pos[t] > close_pos_max:
                continue
            # 4. 3-bar low breakdown
            if l >= ll_bd[t]:
                continue
            # 5. high volume
            if v <= vol_mult * vol_sma_lag[t]:
                continue
            # 6. anti-overlap
            if not np.isnan(ll_anti[t]):
                prior_low = lows[t - 1] if t - 1 >= 0 else np.nan
                if not np.isnan(prior_low) and prior_low < ll_anti[t]:
                    continue
            # 7. anti-capitulation: don't short into 5-day capitulation
            if not np.isnan(cap_ratio[t]) and cap_ratio[t] < cap_min_ratio:
                continue

            sl_price = h + sl_mult * atr_t
            entry_ref = c
            risk = sl_price - entry_ref
            if risk <= 0:
                continue
            tp_price = entry_ref - tp_r * risk
            score = short_w
            if score < min_score:
                continue

            sig = self.emit_signal(
                ts=pd.Timestamp(ts_arr[t]).to_pydatetime(),
                venue=venue, symbol=symbol, timeframe=timeframe,
                direction="short",
                pattern_id="vsa_sow_short",
                confluence_score=float(score),
                sl_price=float(sl_price),
                tp_price=float(tp_price),
                suggested_size_atr=1.0,
                metadata={
                    "spread_atr": float(spread / atr_t) if atr_t > 0 else None,
                    "vol_ratio": float(v / vol_sma_lag[t]) if vol_sma_lag[t] > 0 else None,
                    "close_pos": float(close_pos[t]),
                    "breakdown_dist_atr": float((ll_bd[t] - l) / atr_t) if atr_t > 0 else None,
                    "cap_ratio_5d": float(cap_ratio[t]) if not np.isnan(cap_ratio[t]) else None,
                    "atr20": float(atr_t),
                },
            )
            out.append(sig)
            last_short_ts = t

        self._log.bind(n=len(out), bars=len(df)).info("vsa_sow_effort_down.signals.generated")
        return out
