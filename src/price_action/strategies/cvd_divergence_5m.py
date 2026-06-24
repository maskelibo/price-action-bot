"""5m CVD Divergence strategy (HYP-2026-05-17-scalp-05).

Port of Phoenix 1d cvd_spike_fade with intraday-tightened confirmation:
  - OBV z-score (60-bar = 5h) > +2.0 spike
  - Price higher-high (10-bar lookback) with OBV lower-high (bearish divergence)
  - RSI(14) > 65 overbought confirmation
  -> SHORT entry (fade exhaustion)

Symmetric LONG: OBV z < -2.0 + price LL + OBV HH + RSI < 35.

References:
  - Phoenix 1d cvd_spike_fade.py (production v2.0.4)
  - Granville (1963) OBV
  - Wyckoff/Williams (1993) Volume Spread Analysis effort-vs-result
  - Brian Shannon (2008) intraday divergence
  - Wilder (1978) + Cardwell RSI extremes

Lookahead-free contract:
  - OBV from t-1 sign vs t volume (causal). z-score over [t-60..t] window.
  - Divergence: price/OBV rolling_max over [t-window..t] vs prev window.
  - All signals fire at bar t close; engine fills t+1 open.

Configuration (manifest params):
  obv_lookback     : 60 (5h on 5m TF)
  zscore_thresh    : 2.0
  div_window       : 10 (50min lookback for HH/LH comparison)
  rsi_thresh_high  : 65 (overbought confirm)
  rsi_thresh_low   : 35 (oversold confirm)
  atr_sl_mult      : 1.2
  tp_r             : 0.8 (quick scalp) — runner extension to 1.5R via partial mgmt
  hold_max_bars    : 18 (90 min)
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from price_action.contracts import Signal
from price_action.strategies.base import Strategy, StrategyManifest
from price_action.strategies.classic_pa import _atr
from price_action.strategies.cvd_spike_fade import _obv, _obv_zscore
from price_action.strategies.anchored_vwap_reversal import _rsi


# =====================================================================
# Divergence detection
# =====================================================================

def _price_obv_divergence(df: pd.DataFrame, window: int = 10) -> tuple[pd.Series, pd.Series]:
    """Detect bearish/bullish divergence at bar t.

    Bearish (SHORT signal at t):
      - high[t] == rolling_max(high, window)[t] (current bar makes HH)
      - high[t] > rolling_max(high, window).shift(window)[t] (HH vs prev window)
      - obv[t] < rolling_max(obv, window).shift(window)[t] (LH on OBV vs prev window)

    Bullish symmetric.

    Returns (bear_div, bull_div) bool Series.
    Lookahead-free: all rolling/shift over PAST window.
    """
    high = df["high"]
    low = df["low"]
    obv = df["obv"]

    high_max = high.rolling(window, min_periods=window).max()
    low_min = low.rolling(window, min_periods=window).min()
    obv_max = obv.rolling(window, min_periods=window).max()
    obv_min = obv.rolling(window, min_periods=window).min()

    prev_high_max = high_max.shift(window)
    prev_low_min = low_min.shift(window)
    prev_obv_max = obv_max.shift(window)
    prev_obv_min = obv_min.shift(window)

    # Bearish: price makes HH, OBV doesn't confirm
    price_hh = (high == high_max) & (high > prev_high_max)
    obv_lh = obv < prev_obv_max
    bear_div = (price_hh & obv_lh).fillna(False)

    # Bullish: price makes LL, OBV doesn't confirm (price weaker low, OBV stronger)
    price_ll = (low == low_min) & (low < prev_low_min)
    obv_hh = obv > prev_obv_min
    bull_div = (price_ll & obv_hh).fillna(False)

    return bear_div, bull_div


# =====================================================================
# Default manifest
# =====================================================================

def _default_manifest() -> StrategyManifest:
    raw = {
        "name": "cvd_divergence_5m",
        "version": "1.0.0",
        "description": (
            "5m OBV z>2 spike + price/OBV divergence + RSI confirm -> fade. "
            "Port of Phoenix 1d cvd_spike_fade with tighter intraday confirmation."
        ),
        "trend_filter": {"type": "none", "period": 50, "required": False},
        "signals": {
            "patterns": [
                {
                    "id": "cvd_div_short",
                    "enabled": True,
                    "weight": 2.0,
                    "params": {
                        "obv_lookback": 60,
                        "zscore_thresh": 2.0,
                        "div_window": 10,
                        "rsi_thresh_high": 65.0,
                        "rsi_thresh_low": 35.0,
                    },
                },
                {
                    "id": "cvd_div_long",
                    "enabled": True,
                    "weight": 2.0,
                    "params": {
                        "obv_lookback": 60,
                        "zscore_thresh": 2.0,
                        "div_window": 10,
                        "rsi_thresh_high": 65.0,
                        "rsi_thresh_low": 35.0,
                    },
                },
            ],
            "structure": {
                "swing": {"fractal_n": 2},
                "support_resistance": {
                    "lookback_bars": 120,
                    "cluster_atr_multiplier": 0.5,
                    "min_touches": 2,
                    "max_age_bars": 120,
                },
                "require_proximity_to_sr_atr": 0.0,
            },
            "filters": {
                "atr_min_pct": 0.001,
                "volume_zscore_min": 0.0,
            },
            "confluence": {
                "method": "weighted_sum",
                "min_score": 1.5,
                "bonus_if_at_sr": 0.0,
            },
        },
        "risk": {
            "stop_loss": {"method": "atr", "atr_mult": 1.2},
            "take_profit": {"method": "r_multiple", "tp_r": 0.8},
            "position_sizing": {"method": "fixed_fractional", "risk_per_trade": 0.01},
        },
        "backtest": {
            "warmup_bars": 80,
            "fees": {"taker": 0.00040, "maker": -0.00010},
            "slippage_bps": 10.0,
            "initial_capital_usdt": 10_000.0,
        },
    }
    return StrategyManifest.model_validate(raw)


# =====================================================================
# Strategy
# =====================================================================

class CVDDivergence5mStrategy(Strategy):
    """5m OBV divergence + RSI confirm fade."""

    name = "cvd_divergence_5m"

    @property
    def _cfg(self) -> dict[str, Any]:
        for p in self.manifest.signals.patterns:
            return p.params
        return {}

    @property
    def _obv_lookback(self) -> int:
        return int(self._cfg.get("obv_lookback", 60))

    @property
    def _zscore_thresh(self) -> float:
        return float(self._cfg.get("zscore_thresh", 2.0))

    @property
    def _div_window(self) -> int:
        return int(self._cfg.get("div_window", 10))

    @property
    def _rsi_high(self) -> float:
        return float(self._cfg.get("rsi_thresh_high", 65.0))

    @property
    def _rsi_low(self) -> float:
        return float(self._cfg.get("rsi_thresh_low", 35.0))

    @property
    def _atr_sl_mult(self) -> float:
        return float(self.manifest.risk.get("stop_loss", {}).get("atr_mult", 1.2))

    @property
    def _tp_r(self) -> float:
        return float(self.manifest.risk.get("take_profit", {}).get("tp_r", 0.8))

    @property
    def _atr_min_pct(self) -> float:
        return float(getattr(self.manifest.signals.filters, "atr_min_pct", 0.001) or 0.001)

    # ----- prepare_features -----
    def prepare_features(self, df: pd.DataFrame) -> pd.DataFrame:
        if df.empty:
            return df.copy()
        self.apply_tf_manifest(df)
        df = df.sort_values("ts").reset_index(drop=True).copy()

        df["atr14"] = _atr(df, 14)
        df["atr_pct"] = df["atr14"] / df["close"].replace(0, np.nan)

        df["obv"] = _obv(df)
        df["obv_zscore"] = _obv_zscore(df["obv"], lookback=self._obv_lookback)
        df["rsi14"] = _rsi(df["close"], 14)

        bear_div, bull_div = _price_obv_divergence(df, window=self._div_window)
        df["bear_div"] = bear_div
        df["bull_div"] = bull_div

        return df

    # ----- generate_signals -----
    def generate_signals(self, df: pd.DataFrame) -> list[Signal]:
        if df.empty:
            return []
        if "obv_zscore" not in df.columns:
            df = self.prepare_features(df)

        required = ["obv_zscore", "rsi14", "bear_div", "bull_div", "atr14"]
        for col in required:
            if col not in df.columns:
                return []

        venue = str(df["venue"].iloc[0]) if "venue" in df.columns else "unknown"
        symbol = str(df["symbol"].iloc[0]) if "symbol" in df.columns else "UNKNOWN"
        timeframe = str(df["timeframe"].iloc[0]) if "timeframe" in df.columns else "5m"

        z_thresh = self._zscore_thresh
        rsi_h = self._rsi_high
        rsi_l = self._rsi_low
        atr_sl = self._atr_sl_mult
        tp_r = self._tp_r
        atr_min_pct = self._atr_min_pct

        out: list[Signal] = []
        for i in range(1, len(df) - 1):
            row = df.iloc[i]
            atr = float(row.get("atr14") or 0.0)
            close = float(row["close"])
            if atr <= 0 or np.isnan(atr) or close <= 0:
                continue
            if atr / close < atr_min_pct:
                continue

            z = float(row.get("obv_zscore") or 0.0)
            rsi = float(row.get("rsi14") or 50.0)
            if np.isnan(z) or np.isnan(rsi):
                continue

            # SHORT: bearish divergence + OBV spike + overbought
            if bool(row.get("bear_div", False)) and z >= z_thresh and rsi >= rsi_h:
                sl_price = close + atr_sl * atr
                risk = sl_price - close
                if risk <= 0:
                    continue
                tp_price = close - tp_r * risk
                ts = pd.Timestamp(row["ts"]).to_pydatetime()
                sig = self.emit_signal(
                    ts=ts, venue=venue, symbol=symbol, timeframe=timeframe,
                    direction="short", pattern_id="cvd_div_short",
                    confluence_score=1.5 + min(0.5, (z - z_thresh) * 0.25),
                    sl_price=float(sl_price), tp_price=float(tp_price),
                    suggested_size_atr=atr_sl,
                    metadata={"obv_z": z, "rsi": rsi, "atr14": atr, "bar_idx": i},
                )
                out.append(sig)

            # LONG: bullish divergence + OBV spike (negative) + oversold
            elif bool(row.get("bull_div", False)) and z <= -z_thresh and rsi <= rsi_l:
                sl_price = close - atr_sl * atr
                risk = close - sl_price
                if risk <= 0:
                    continue
                tp_price = close + tp_r * risk
                ts = pd.Timestamp(row["ts"]).to_pydatetime()
                sig = self.emit_signal(
                    ts=ts, venue=venue, symbol=symbol, timeframe=timeframe,
                    direction="long", pattern_id="cvd_div_long",
                    confluence_score=1.5 + min(0.5, (abs(z) - z_thresh) * 0.25),
                    sl_price=float(sl_price), tp_price=float(tp_price),
                    suggested_size_atr=atr_sl,
                    metadata={"obv_z": z, "rsi": rsi, "atr14": atr, "bar_idx": i},
                )
                out.append(sig)

        return out


def build_strategy(overrides: dict[str, Any] | None = None) -> CVDDivergence5mStrategy:
    manifest = _default_manifest()
    if overrides:
        raw = manifest.model_dump()
        raw.update(overrides)
        manifest = StrategyManifest.model_validate(raw)
    return CVDDivergence5mStrategy(manifest)


__all__ = [
    "CVDDivergence5mStrategy",
    "build_strategy",
    "_default_manifest",
    "_price_obv_divergence",
]
