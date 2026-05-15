"""High-Tight Flag (HTF) — O'Neil/Bulkowski momentum breakout pattern.

Konsept (LONG only — pattern doğal long-side):
  Adım 1 — POLE: son `pole_window_days` (default 35d) icinde lowest_low LL,
           pole_high_idx = highest_high index, pole_return = (HH - LL)/LL >= 0.60.
  Adım 2 — FLAG: pole_high_idx'ten bar t'ye dar consol.
           flag_len = t - pole_high_idx in [14, 35]
           flag_low = min(low over [pole_high_idx+1, t-1])
           flag_pullback = (pole_high - flag_low) / pole_high in [0.05, 0.30]
           flag_range / ATR <= 5.0 (consol tight)
  Adım 3 — BREAKOUT: close[t] > pole_high * 0.995 AND vol[t] > 1.3 * 60-bar median vol.

Exit:
  SL = flag_low - 0.5 * ATR(14)
  TP1 = 1.0R partial 50%
  TP2 = pole_high + (pole_high - flag_low) (measured move) partial 30%
  Runner 20% trail engine default.
  Cooldown same symbol 14 bar.

Filtreler:
  - ATR%(14) >= 1.0 (alt-coin parabolik dönem doğal yüksek vol)

Lookahead-free: tüm hesaplamalar bar `t` dahil ve geriye dönük. Pole high
arandığı window pole_window_days. Flag pullback hesabı [pole_high_idx+1, t-1]
— current bar (t) dışında. Breakout bar `t` close — entry t+1 open.
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
        "name": "high_tight_flag",
        "version": "1.0.0",
        "description": (
            "O'Neil/Bulkowski High-Tight Flag: pole (60%+ in ~5w) + tight flag "
            "(<=30% pullback in 2-5w) + breakout above pole_high. LONG only."
        ),
        "trend_filter": {"type": "ema", "period": 50, "required": False},
        "signals": {
            "patterns": [
                {
                    "id": "htf_breakout_long",
                    "enabled": True,
                    "weight": 2.0,
                    "params": {
                        "pole_window_days": 35,
                        "pole_return_min": 0.60,
                        "flag_len_min": 14,
                        "flag_len_max": 35,
                        "flag_pullback_min": 0.05,
                        "flag_pullback_max": 0.30,
                        "flag_range_atr_max": 5.0,
                        "vol_mult_min": 1.3,
                        "sl_atr_mult_below_flag_low": 0.5,
                        "tp_r_multiple_primary": 1.0,
                        "cooldown_bars": 14,
                    },
                },
            ],
            "filters": {
                "atr_min_pct": 0.010,
                "volume_zscore_min": 0.0,
            },
            "confluence": {
                "method": "weighted_sum",
                "min_score": 1.5,
                "bonus_if_at_sr": 0.0,
            },
        },
        "risk": {
            "take_profit": {"primary_R": 1.0},
        },
    }
    return StrategyManifest.model_validate(raw)


class HighTightFlagStrategy(Strategy):
    """O'Neil/Bulkowski High-Tight Flag (LONG only)."""

    name = "high_tight_flag"

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

        # Volume median 60-bar (used for confirmation threshold)
        df["vol_med60"] = df["volume"].rolling(60, min_periods=10).median()

        return df

    def generate_signals(self, df: pd.DataFrame) -> list[Signal]:
        if df.empty:
            return []
        if "vol_med60" not in df.columns:
            df = self.prepare_features(df)

        signals_cfg = self.manifest.signals
        filters = signals_cfg.filters
        min_score = float(signals_cfg.confluence.min_score)

        pole_window = int(self._get_param("htf_breakout_long", "pole_window_days", 35))
        pole_ret_min = float(self._get_param("htf_breakout_long", "pole_return_min", 0.60))
        flag_len_min = int(self._get_param("htf_breakout_long", "flag_len_min", 14))
        flag_len_max = int(self._get_param("htf_breakout_long", "flag_len_max", 35))
        flag_pb_min = float(self._get_param("htf_breakout_long", "flag_pullback_min", 0.05))
        flag_pb_max = float(self._get_param("htf_breakout_long", "flag_pullback_max", 0.30))
        flag_range_max = float(self._get_param("htf_breakout_long", "flag_range_atr_max", 5.0))
        vol_mult_min = float(self._get_param("htf_breakout_long", "vol_mult_min", 1.3))
        sl_mult = float(self._get_param("htf_breakout_long", "sl_atr_mult_below_flag_low", 0.5))
        tp_r_primary = float(self._get_param("htf_breakout_long", "tp_r_multiple_primary", 1.0))
        cooldown = int(self._get_param("htf_breakout_long", "cooldown_bars", 14))

        long_w = next((p.weight for p in signals_cfg.patterns if p.id == "htf_breakout_long"), 2.0)
        atr_min_pct = float(getattr(filters, "atr_min_pct", 0.010) or 0.010)

        venue = str(df["venue"].iloc[0]) if "venue" in df.columns else "unknown"
        symbol = str(df["symbol"].iloc[0]) if "symbol" in df.columns else "UNKNOWN"
        timeframe = str(df["timeframe"].iloc[0]) if "timeframe" in df.columns else "1d"

        highs = df["high"].to_numpy(dtype=float)
        lows = df["low"].to_numpy(dtype=float)
        closes = df["close"].to_numpy(dtype=float)
        vols = df["volume"].to_numpy(dtype=float)
        atrs = df["atr14"].to_numpy(dtype=float)
        atr_pct = df["atr_pct"].to_numpy(dtype=float)
        vol_med60 = df["vol_med60"].to_numpy(dtype=float)
        ts_arr = df["ts"].to_numpy()
        n = len(df)

        out: list[Signal] = []
        last_emit_ts = -99

        # Daily 1d bars: pole_window already in bars
        min_start = max(pole_window + flag_len_max, 60)
        for t in range(min_start, n):
            atr_t = atrs[t]
            if np.isnan(atr_t) or atr_t <= 0:
                continue
            if atr_min_pct > 0 and not np.isnan(atr_pct[t]) and atr_pct[t] < atr_min_pct:
                continue
            if t <= last_emit_ts + cooldown:
                continue

            # ----- Pole search window: [t-pole_window, t-flag_len_min] -----
            # Pole high index within that window
            search_start = max(0, t - pole_window)
            search_end = t - flag_len_min  # exclusive of recent flag
            if search_end <= search_start + 5:
                continue
            window_highs = highs[search_start:search_end]
            window_lows = lows[search_start:search_end]
            if len(window_highs) == 0:
                continue
            pole_high_idx_rel = int(np.argmax(window_highs))
            pole_high_idx = search_start + pole_high_idx_rel
            pole_high = window_highs[pole_high_idx_rel]
            # Lowest low BEFORE pole high (the base of the pole)
            if pole_high_idx <= search_start:
                continue
            pre_pole_lows = lows[search_start:pole_high_idx]
            if len(pre_pole_lows) == 0:
                continue
            pole_low = float(np.min(pre_pole_lows))
            if pole_low <= 0:
                continue
            pole_return = (pole_high - pole_low) / pole_low
            if pole_return < pole_ret_min:
                continue

            # ----- Flag check -----
            flag_len = t - pole_high_idx
            if flag_len < flag_len_min or flag_len > flag_len_max:
                continue
            # Flag low: min(low over [pole_high_idx+1, t-1])  (exclude current bar t)
            if pole_high_idx + 1 >= t:
                continue
            flag_lows = lows[pole_high_idx + 1 : t]
            flag_highs = highs[pole_high_idx + 1 : t]
            if len(flag_lows) == 0:
                continue
            flag_low = float(np.min(flag_lows))
            flag_high = float(np.max(flag_highs))
            flag_pullback = (pole_high - flag_low) / pole_high
            if flag_pullback < flag_pb_min or flag_pullback > flag_pb_max:
                continue
            flag_range_atr = (flag_high - flag_low) / atr_t if atr_t > 0 else np.inf
            if flag_range_atr > flag_range_max:
                continue

            # ----- Breakout trigger at bar t -----
            if closes[t] < pole_high * 0.995:
                continue
            # Volume confirmation
            vm60 = vol_med60[t]
            if np.isnan(vm60) or vm60 <= 0:
                continue
            if vols[t] < vm60 * vol_mult_min:
                continue

            # ----- Signal -----
            sl_price = flag_low - sl_mult * atr_t
            entry_ref = closes[t]
            risk = entry_ref - sl_price
            if risk <= 0:
                continue
            tp_price = entry_ref + tp_r_primary * risk  # engine uses tp_R for partial
            score = long_w
            if score < min_score:
                continue

            sig = self.emit_signal(
                ts=pd.Timestamp(ts_arr[t]).to_pydatetime(),
                venue=venue, symbol=symbol, timeframe=timeframe,
                direction="long",
                pattern_id="htf_breakout_long",
                confluence_score=float(score),
                sl_price=float(sl_price),
                tp_price=float(tp_price),
                suggested_size_atr=1.0,
                metadata={
                    "pole_return": float(pole_return),
                    "pole_high": float(pole_high),
                    "pole_low": float(pole_low),
                    "pole_high_idx": int(pole_high_idx),
                    "flag_len": int(flag_len),
                    "flag_low": float(flag_low),
                    "flag_pullback": float(flag_pullback),
                    "flag_range_atr": float(flag_range_atr),
                    "vol_mult": float(vols[t] / vm60),
                    "measured_move_target": float(pole_high + (pole_high - flag_low)),
                },
            )
            out.append(sig)
            last_emit_ts = t

        self._log.bind(n=len(out), bars=len(df)).info("high_tight_flag.signals.generated")
        return out
