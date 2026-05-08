"""Engulfing Continuation — 4h Timeframe Variant.

Same pattern as EngulfingContinuationStrategy (1d) but with all period
parameters scaled to preserve equivalent calendar-time windows on 4h bars.

Scaling factor: 24h / 4h = 6x  (6 four-hour bars per calendar day)

Key adaptations vs 1d:
  - EMA-20 (pullback)  -> EMA-120  (same 20-day window)
  - EMA-50 (trend)     -> EMA-300  (same 50-day window)
  - EMA-200 (regime)   -> EMA-1200 (same 200-day regime filter)
  - Kaufman ER period  -> 84       (same 14-day efficiency window)
  - Pullback window    -> 60 bars  (same 10-day lookback)
  - ATR period stays at 14 (4h ATR is a proper range measure)

Pattern detection rules (body_ratio, strict engulf, color) are UNCHANGED.
This makes the 4h variant a true frequency experiment — not a rule change.

DO NOT modify engulfing_continuation.py (1d) — see task constraint.
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from price_action.strategies.base import Strategy, StrategyManifest
from price_action.strategies.engulfing_continuation import (
    EngulfingContinuationStrategy,
    _pullback_to_ema_flag,
    _strict_engulfing,
    _swing_sl,
)
from price_action.strategies.classic_pa import (
    _atr,
    _ema,
    _fractal_swings,
    _kaufman_efficiency_ratio,
    _always_in_flags,
    _rolling_sharpe,
    _sr_levels,
)
from price_action.contracts import Signal
from price_action.logging_config import logger


# =====================================================================
# Scale constants
# =====================================================================

_4H_SCALE = 6  # bars per day on 4h timeframe

# EMA periods scaled by 6
_EMA_PULLBACK = 20 * _4H_SCALE   # 120  — 20-day mean reversion
_EMA_TREND    = 50 * _4H_SCALE   # 300  — 50-day trend
_EMA_REGIME   = 200 * _4H_SCALE  # 1200 — 200-day bull/bear regime
_EMA_TRAILING = 14 * _4H_SCALE   # 84   — runner trailing (14-day)

_KER_PERIOD   = 14 * _4H_SCALE   # 84   — Kaufman efficiency 14-day
_PULLBACK_WIN = 10 * _4H_SCALE   # 60   — pullback window 10-day


# =====================================================================
# Default manifest for 4h
# =====================================================================

def _default_4h_manifest() -> StrategyManifest:
    raw = {
        "name": "engulfing_continuation_4h",
        "version": "1.0.0",
        "description": "Engulfing bar after 120-EMA pullback in established trend (4h timeframe)",
        "trend_filter": {"type": "ema", "period": _EMA_TREND, "required": True},
        "signals": {
            "patterns": [
                {
                    "id": "bullish_engulfing_cont",
                    "enabled": True,
                    "weight": 1.5,
                    "params": {
                        "body_ratio_min": 0.6,
                        "pullback_window": _PULLBACK_WIN,
                        "pullback_touch_atr": 0.5,
                    },
                },
                {
                    "id": "bearish_engulfing_cont",
                    "enabled": True,
                    "weight": 1.5,
                    "params": {
                        "body_ratio_min": 0.6,
                        "pullback_window": _PULLBACK_WIN,
                        "pullback_touch_atr": 0.5,
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
                "require_proximity_to_sr_atr": 0.5,
            },
            "filters": {
                "atr_min_pct": 0.003,         # slightly looser — 4h bars smaller ATR%
                "volume_zscore_min": 0.0,
                "kaufman_er_period": _KER_PERIOD,
                "kaufman_er_min": 0.20,
                "always_in_required": False,
                "bear_regime_size_factor": 0.5,
            },
            "confluence": {
                "method": "weighted_sum",
                "min_score": 1.5,
                "bonus_if_at_sr": 0.5,
            },
        },
        "risk": {
            "stop_loss": {"method": "structural", "swing_lookback": 10},
            "take_profit": {"method": "r_multiple", "primary_R": 2.0},
            "position_sizing": {"method": "fixed_fractional", "risk_per_trade": 0.01},
        },
    }
    return StrategyManifest.model_validate(raw)


# =====================================================================
# Strategy
# =====================================================================

class EngulfingContinuation4HStrategy(Strategy):
    """Engulfing Continuation adapted for 4h timeframe.

    All period parameters are scaled ×6 vs the 1d version so that
    calendar-time lookback windows remain equivalent.

    Pattern rules (engulfing body ratio, color, strict wrap) are UNCHANGED.
    """

    name = "engulfing_continuation_4h"

    def prepare_features(self, df: pd.DataFrame) -> pd.DataFrame:
        if df.empty:
            return df.copy()
        df = df.sort_values("ts").reset_index(drop=True).copy()

        # EMAs — all scaled ×6 vs 1d
        df["ema_pullback"] = _ema(df["close"], _EMA_PULLBACK)   # 120
        df["ema20"] = df["ema_pullback"]                         # alias for downstream compat
        df["ema_trailing"] = _ema(df["close"], _EMA_TRAILING)   # 84
        df["ema14"] = df["ema_trailing"]                         # alias
        df["ema_trend"] = _ema(df["close"], _EMA_TREND)         # 300
        df["ema50"] = df["ema_trend"]                            # alias
        df["ema_regime"] = _ema(df["close"], _EMA_REGIME)       # 1200
        df["ema200"] = df["ema_regime"]                          # alias

        # ATR — keep 14 bars (4h ATR captures intra-day range)
        df["atr14"] = _atr(df, 14)
        df["atr_pct"] = df["atr14"] / df["close"]

        # Volume z-score (360 bars ≈ 60 calendar days on 4h)
        vol = df["volume"]
        vmean = vol.rolling(360, min_periods=10).mean()
        vstd = vol.rolling(360, min_periods=10).std(ddof=0)
        df["vol_z"] = (vol - vmean) / vstd.replace(0, np.nan)

        # Swing high/low (fractal n=2 unchanged)
        n = self.manifest.signals.structure.swing.fractal_n
        sh, sl_col = _fractal_swings(df, n=n)
        df["swing_high"] = sh
        df["swing_low"] = sl_col

        # Pullback to 120-EMA flag (rolling 60-bar window)
        pb_window = _PULLBACK_WIN
        pb_touch = 0.5
        for p in self.manifest.signals.patterns:
            if p.id in ("bullish_engulfing_cont", "bearish_engulfing_cont"):
                pb_window = int(p.params.get("pullback_window", _PULLBACK_WIN))
                pb_touch = float(p.params.get("pullback_touch_atr", 0.5))
                break
        df["pullback_to_20ema"] = _pullback_to_ema_flag(
            df, ema_col="ema_pullback", window=pb_window, touch_atr_factor=pb_touch
        )

        # Strict engulfing flags — SAME logic, just on 4h bars
        body_ratio_min = 0.6
        for p in self.manifest.signals.patterns:
            if p.id in ("bullish_engulfing_cont", "bearish_engulfing_cont"):
                body_ratio_min = float(p.params.get("body_ratio_min", 0.6))
                break
        df["strict_bull_engulf"] = _strict_engulfing(df, body_ratio_min=body_ratio_min, bullish=True)
        df["strict_bear_engulf"] = _strict_engulfing(df, body_ratio_min=body_ratio_min, bullish=False)

        # Structural SL (10 bars — on 4h, 10 bars = ~40h, sufficient for structure)
        df["struct_sl_long"] = _swing_sl(df, "long", lookback=10)
        df["struct_sl_short"] = _swing_sl(df, "short", lookback=10)

        # Kaufman ER — 84 bars = 14-day on 4h
        filters_cfg = self.manifest.signals.filters
        er_period = int(getattr(filters_cfg, "kaufman_er_period", _KER_PERIOD) or _KER_PERIOD)
        df["kaufman_er"] = _kaufman_efficiency_ratio(df["close"], period=er_period)

        # Brooks always-in flags
        ai_n = int(getattr(filters_cfg, "always_in_n_confirm", 3) or 3)
        long_ai, short_ai = _always_in_flags(df, n_confirm=ai_n)
        df["always_in_long"] = long_ai
        df["always_in_short"] = short_ai

        # Rolling Sharpe — 360 bars ≈ 60 trading days on 4h
        rs_period = int(getattr(filters_cfg, "rolling_sharpe_period", 360) or 360)
        df["rolling_sharpe"] = _rolling_sharpe(df["close"], period=rs_period)

        return df

    def generate_signals(self, df: pd.DataFrame) -> list[Signal]:
        """Signal generation — identical logic to 1d, column names are consistent."""
        if df.empty:
            return []
        if "ema_pullback" not in df.columns:
            df = self.prepare_features(df)

        signals_cfg = self.manifest.signals
        filters = signals_cfg.filters
        confluence = signals_cfg.confluence
        sr_cfg = signals_cfg.structure.support_resistance

        primary_R = float(
            self.manifest.risk.get("take_profit", {}).get("primary_R", 2.0)
        )

        venue = str(df["venue"].iloc[0]) if "venue" in df.columns else "unknown"
        symbol = str(df["symbol"].iloc[0]) if "symbol" in df.columns else "UNKNOWN"
        timeframe = str(df["timeframe"].iloc[0]) if "timeframe" in df.columns else "4h"

        long_score = pd.Series(0.0, index=df.index)
        short_score = pd.Series(0.0, index=df.index)

        # Pattern weights
        bull_weight = 1.5
        bear_weight = 1.5
        for p in signals_cfg.patterns:
            if not p.enabled:
                continue
            if p.id == "bullish_engulfing_cont":
                bull_weight = p.weight
            elif p.id == "bearish_engulfing_cont":
                bear_weight = p.weight

        pullback = df["pullback_to_20ema"].fillna(False)
        bull_engulf = df["strict_bull_engulf"].fillna(False)
        bear_engulf = df["strict_bear_engulf"].fillna(False)

        long_score = long_score.where(~(pullback & bull_engulf), bull_weight)
        short_score = short_score.where(~(pullback & bear_engulf), bear_weight)

        # Trend filter using scaled 300-EMA
        if self.manifest.trend_filter.required:
            up_ok = df["close"] > df["ema_trend"]
            down_ok = df["close"] < df["ema_trend"]
            long_score = long_score.where(up_ok, 0.0)
            short_score = short_score.where(down_ok, 0.0)

        # ATR min filter (looser for 4h)
        atr_min = float(getattr(filters, "atr_min_pct", 0.003) or 0.003)
        if atr_min > 0:
            mask = df["atr_pct"] >= atr_min
            long_score = long_score.where(mask, 0.0)
            short_score = short_score.where(mask, 0.0)

        # Volume z-score filter
        vol_min = float(getattr(filters, "volume_zscore_min", 0.0) or 0.0)
        if vol_min > 0:
            mask = df["vol_z"].fillna(-np.inf) >= vol_min
            long_score = long_score.where(mask, 0.0)
            short_score = short_score.where(mask, 0.0)

        # Kaufman ER filter
        er_min = float(getattr(filters, "kaufman_er_min", 0.0) or 0.0)
        if er_min > 0 and "kaufman_er" in df.columns:
            mask = df["kaufman_er"] >= er_min
            long_score = long_score.where(mask, 0.0)
            short_score = short_score.where(mask, 0.0)

        # Brooks always-in (optional)
        if bool(getattr(filters, "always_in_required", False)):
            long_score = long_score.where(df["always_in_long"], 0.0)
            short_score = short_score.where(df["always_in_short"], 0.0)

        # 1200-EMA bear regime size factor
        bear_factor = float(getattr(filters, "bear_regime_size_factor", 1.0) or 1.0)
        if bear_factor < 1.0 and "ema_regime" in df.columns:
            below_regime = df["close"] < df["ema_regime"]
            long_score = long_score.where(~below_regime, long_score * bear_factor)

        # S/R levels (lookahead-free)
        cluster_tol = df["atr14"].fillna(0) * sr_cfg.cluster_atr_multiplier
        sr_records = _sr_levels(
            df,
            lookback_bars=sr_cfg.lookback_bars,
            cluster_tol=cluster_tol,
            min_touches=sr_cfg.min_touches,
        )
        sr_by_bar: dict[int, list[float]] = {}
        for i, lvl, _t in sr_records:
            sr_by_bar.setdefault(i, []).append(lvl)

        proximity_atr = signals_cfg.structure.require_proximity_to_sr_atr
        bonus = float(getattr(confluence, "bonus_if_at_sr", 0.0) or 0.0)
        min_score = float(confluence.min_score)

        out: list[Signal] = []
        for i in range(len(df)):
            row = df.iloc[i]
            close = float(row["close"])
            atr = float(row.get("atr14") or 0.0)
            if atr <= 0 or np.isnan(atr):
                continue

            levels = sr_by_bar.get(i, [])
            near_sr = False
            if levels and proximity_atr > 0:
                tol = proximity_atr * atr
                near_sr = any(abs(close - lvl) <= tol for lvl in levels)

            for direction, score_series, pattern_id_name in (
                ("long", long_score, "bullish_engulfing_cont"),
                ("short", short_score, "bearish_engulfing_cont"),
            ):
                base_score = float(score_series.iat[i])
                if base_score <= 0:
                    continue
                final_score = base_score + (bonus if near_sr else 0.0)
                if proximity_atr > 0 and not near_sr:
                    final_score = max(0.0, final_score - 0.25)
                if final_score < min_score:
                    continue

                # Structural SL
                if direction == "long":
                    sl_price = float(row.get("struct_sl_long") or (close - 2.0 * atr))
                    if np.isnan(sl_price) or sl_price <= 0:
                        sl_price = close - 2.0 * atr
                    sl_price = min(sl_price, close - 0.5 * atr)
                    risk = close - sl_price
                    tp_price = close + primary_R * risk
                else:
                    sl_price = float(row.get("struct_sl_short") or (close + 2.0 * atr))
                    if np.isnan(sl_price) or sl_price <= 0:
                        sl_price = close + 2.0 * atr
                    sl_price = max(sl_price, close + 0.5 * atr)
                    risk = sl_price - close
                    tp_price = close - primary_R * risk

                ts = pd.Timestamp(row["ts"]).to_pydatetime()
                sig = self.emit_signal(
                    ts=ts,
                    venue=venue,
                    symbol=symbol,
                    timeframe=timeframe,
                    direction=direction,
                    pattern_id=pattern_id_name,
                    confluence_score=float(final_score),
                    sl_price=float(sl_price),
                    tp_price=float(tp_price),
                    suggested_size_atr=1.0,
                    metadata={
                        "near_sr": near_sr,
                        "atr14": atr,
                        "ema_pullback": float(row.get("ema_pullback") or 0.0),
                        "ema_trend": float(row.get("ema_trend") or 0.0),
                        "pullback_to_20ema": bool(row.get("pullback_to_20ema", False)),
                        "kaufman_er": float(row.get("kaufman_er") or 0.0),
                    },
                )
                out.append(sig)

        logger.bind(n=len(out), bars=len(df)).info("engulfing_cont_4h.signals.generated")
        return out


def _default_manifest() -> StrategyManifest:
    """Alias for external callers (tests, backtest scripts)."""
    return _default_4h_manifest()
