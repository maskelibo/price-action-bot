"""Signal Engineering paketi — pattern detector + structure + confluence."""
from __future__ import annotations

from price_action.signals.candles import (
    bearish_engulfing,
    bearish_pin_bar,
    bullish_engulfing,
    bullish_pin_bar,
    doji,
    evening_star,
    inside_bar,
    inside_bar_breakout,
    morning_star,
)
from price_action.signals.confluence import (
    add_proximity_to_sr,
    emit_signals,
    score,
)
from price_action.signals.filters import (
    atr_threshold,
    ema_trend_filter,
    volatility_regime,
    volume_zscore,
)
from price_action.signals.structure import (
    atr,
    ema,
    support_resistance,
    swing_highs,
    swing_lows,
    trendline,
)

__all__ = [
    # candles
    "bullish_pin_bar",
    "bearish_pin_bar",
    "bullish_engulfing",
    "bearish_engulfing",
    "inside_bar",
    "inside_bar_breakout",
    "morning_star",
    "evening_star",
    "doji",
    # structure
    "swing_highs",
    "swing_lows",
    "support_resistance",
    "trendline",
    "atr",
    "ema",
    # filters
    "atr_threshold",
    "volume_zscore",
    "ema_trend_filter",
    "volatility_regime",
    # confluence
    "score",
    "add_proximity_to_sr",
    "emit_signals",
]
