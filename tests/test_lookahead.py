"""Lookahead bias testleri.

Bir detector future-leak'siz çalışıyorsa, bir bar `t` için verilen sonuç,
bütün serideki hesaplama vs. sadece `iloc[:t+1]` ile yapılan hesaplamada
aynı olmalı.

NOT: `swing_highs` / `swing_lows` BU TESTİN KAPSAMI DIŞINDA. Bunlar fractal
gereği `t+n` anına kadar bilinmez (etiket geçmişe doğru atanır). Confluence
kodu bu yüzden swing'i mevcut anki bar için sinyal şartı olarak KULLANMAZ.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

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
from price_action.signals.filters import (
    atr_threshold,
    ema_trend_filter,
    volume_zscore,
)
from price_action.signals.structure import atr, ema


def _bool_eq(a, b) -> bool:
    av = bool(a) if not (isinstance(a, float) and np.isnan(a)) else False
    bv = bool(b) if not (isinstance(b, float) and np.isnan(b)) else False
    return av == bv


@pytest.fixture
def synthetic_long() -> pd.DataFrame:
    """Yeterince uzun, OHLC sane sentetik seri."""
    rng = np.random.default_rng(123)
    n = 250
    rets = rng.normal(0, 0.015, size=n)
    close = 50 * np.exp(np.cumsum(rets))
    high = close * (1 + rng.uniform(0.001, 0.02, size=n))
    low = close * (1 - rng.uniform(0.001, 0.02, size=n))
    open_ = np.empty(n)
    open_[0] = close[0]
    open_[1:] = close[:-1]
    high = np.maximum.reduce([high, open_, close])
    low = np.minimum.reduce([low, open_, close])
    volume = rng.uniform(100, 500, size=n)
    return pd.DataFrame(
        {
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
        }
    )


_DETECTORS = [
    ("bullish_pin_bar", lambda d: bullish_pin_bar(d)),
    ("bearish_pin_bar", lambda d: bearish_pin_bar(d)),
    ("bullish_engulfing", lambda d: bullish_engulfing(d)),
    ("bearish_engulfing", lambda d: bearish_engulfing(d)),
    ("inside_bar", lambda d: inside_bar(d)),
    ("inside_bar_breakout", lambda d: inside_bar_breakout(d)),
    ("morning_star", lambda d: morning_star(d)),
    ("evening_star", lambda d: evening_star(d)),
    ("doji", lambda d: doji(d)),
]


@pytest.mark.parametrize("name, fn", _DETECTORS)
def test_detector_no_lookahead(synthetic_long: pd.DataFrame, name: str, fn) -> None:
    """Tüm seri üzerindeki sonuç ve `iloc[:t+1]` üzerindeki sonuç bar `t`'de eşit olmalı."""
    full = fn(synthetic_long)
    # Birkaç t test et (uçlardan ve ortadan)
    t_indices = [3, 10, 50, 100, 199, len(synthetic_long) - 1]
    for t in t_indices:
        partial = fn(synthetic_long.iloc[: t + 1])
        # iloc[t] eşit olmalı (object/bool tipleri için karşılaştırma)
        a = full.iloc[t]
        b = partial.iloc[t]
        if isinstance(a, (bool, np.bool_)) or isinstance(b, (bool, np.bool_)):
            assert _bool_eq(a, b), f"{name} lookahead mismatch at t={t}: full={a}, partial={b}"
        else:
            assert a == b, f"{name} lookahead mismatch at t={t}: full={a}, partial={b}"


def test_atr_no_lookahead(synthetic_long: pd.DataFrame) -> None:
    full = atr(synthetic_long, period=14)
    for t in [20, 100, len(synthetic_long) - 1]:
        partial = atr(synthetic_long.iloc[: t + 1], period=14)
        a = full.iloc[t]
        b = partial.iloc[t]
        if np.isnan(a) and np.isnan(b):
            continue
        assert np.isclose(a, b), f"ATR lookahead mismatch at t={t}: full={a}, partial={b}"


def test_ema_no_lookahead(synthetic_long: pd.DataFrame) -> None:
    full = ema(synthetic_long["close"], period=20)
    for t in [25, 100, len(synthetic_long) - 1]:
        partial = ema(synthetic_long["close"].iloc[: t + 1], period=20)
        a = full.iloc[t]
        b = partial.iloc[t]
        if np.isnan(a) and np.isnan(b):
            continue
        assert np.isclose(a, b), f"EMA lookahead mismatch at t={t}"


def test_filters_no_lookahead(synthetic_long: pd.DataFrame) -> None:
    a = atr(synthetic_long, period=14)
    full = atr_threshold(a, 0.005, synthetic_long["close"])
    full2 = ema_trend_filter(synthetic_long["close"], period=20, side="long")
    full3 = volume_zscore(synthetic_long["volume"], period=20, min_z=0.5)
    for t in [25, 100, len(synthetic_long) - 1]:
        sub = synthetic_long.iloc[: t + 1]
        a_sub = atr(sub, period=14)
        p1 = atr_threshold(a_sub, 0.005, sub["close"])
        p2 = ema_trend_filter(sub["close"], period=20, side="long")
        p3 = volume_zscore(sub["volume"], period=20, min_z=0.5)
        assert _bool_eq(full.iloc[t], p1.iloc[t])
        assert _bool_eq(full2.iloc[t], p2.iloc[t])
        assert _bool_eq(full3.iloc[t], p3.iloc[t])
