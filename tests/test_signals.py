"""Pattern detector unit testleri."""
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
from price_action.signals.confluence import emit_signals, score
from price_action.signals.filters import (
    atr_threshold,
    ema_trend_filter,
    volatility_regime,
    volume_zscore,
)
from price_action.signals.structure import atr, ema, support_resistance, swing_highs, swing_lows


# ---------------------------------------------------------------------------
# Pin bar
# ---------------------------------------------------------------------------
def test_bullish_pin_bar_detected(bullish_pin_bar_df: pd.DataFrame) -> None:
    flags = bullish_pin_bar(bullish_pin_bar_df)
    assert bool(flags.iloc[2])
    # diğer barlar False
    assert not bool(flags.iloc[0])
    assert not bool(flags.iloc[1])
    assert not bool(flags.iloc[3])


def test_bullish_pin_bar_negative(bearish_pin_bar_df: pd.DataFrame) -> None:
    """Bearish pin bar varken bullish pin bar tetiklenmemeli."""
    assert not bool(bullish_pin_bar(bearish_pin_bar_df).any())


def test_bearish_pin_bar_detected(bearish_pin_bar_df: pd.DataFrame) -> None:
    flags = bearish_pin_bar(bearish_pin_bar_df)
    assert bool(flags.iloc[2])
    assert not bool(flags.iloc[0])


def test_bearish_pin_bar_param_override() -> None:
    """Çok katı paramlarla algılanan bar elenmeli."""
    df = pd.DataFrame(
        {
            "open": [100.5],
            "high": [110.0],
            "low": [99.5],
            "close": [100.0],
        }
    )
    relaxed = bearish_pin_bar(df, {"upper_wick_to_range_min": 0.6})
    strict = bearish_pin_bar(df, {"upper_wick_to_range_min": 0.99})
    assert bool(relaxed.iloc[0])
    assert not bool(strict.iloc[0])


# ---------------------------------------------------------------------------
# Engulfing
# ---------------------------------------------------------------------------
def test_bullish_engulfing(bullish_engulfing_df: pd.DataFrame) -> None:
    flags = bullish_engulfing(bullish_engulfing_df)
    assert bool(flags.iloc[2])
    assert not bool(flags.iloc[0])
    assert not bool(flags.iloc[1])


def test_bearish_engulfing(bearish_engulfing_df: pd.DataFrame) -> None:
    flags = bearish_engulfing(bearish_engulfing_df)
    assert bool(flags.iloc[2])


def test_engulfing_first_bar_no_signal() -> None:
    """İlk barda prev yok → False olmalı."""
    df = pd.DataFrame({"open": [100], "high": [101], "low": [99], "close": [100.5]})
    assert not bool(bullish_engulfing(df).any())
    assert not bool(bearish_engulfing(df).any())


# ---------------------------------------------------------------------------
# Inside bar / breakout
# ---------------------------------------------------------------------------
def test_inside_bar(inside_bar_df: pd.DataFrame) -> None:
    flags = inside_bar(inside_bar_df)
    # bar index 1 inside (high 108 < 110, low 95 > 90)
    assert bool(flags.iloc[1])
    assert not bool(flags.iloc[0])


def test_inside_bar_breakout(inside_bar_df: pd.DataFrame) -> None:
    out = inside_bar_breakout(inside_bar_df)
    # bar index 2 → long
    assert out.iloc[2] == "long"
    assert out.iloc[0] == "none"
    assert out.iloc[1] == "none"


# ---------------------------------------------------------------------------
# Morning / Evening star
# ---------------------------------------------------------------------------
def test_morning_star(morning_star_df: pd.DataFrame) -> None:
    flags = morning_star(morning_star_df)
    assert bool(flags.iloc[2])


def test_evening_star(evening_star_df: pd.DataFrame) -> None:
    flags = evening_star(evening_star_df)
    assert bool(flags.iloc[2])


def test_morning_star_negative(evening_star_df: pd.DataFrame) -> None:
    """Evening star setinde morning star çıkmamalı."""
    assert not bool(morning_star(evening_star_df).any())


# ---------------------------------------------------------------------------
# Doji
# ---------------------------------------------------------------------------
def test_doji(doji_df: pd.DataFrame) -> None:
    flags = doji(doji_df)
    assert bool(flags.iloc[0])
    assert not bool(flags.iloc[1])


def test_doji_strict_param() -> None:
    df = pd.DataFrame({"open": [100], "high": [101], "low": [99], "close": [100.05]})
    assert bool(doji(df, {"body_to_range_max": 0.05}).iloc[0])
    assert not bool(doji(df, {"body_to_range_max": 0.001}).iloc[0])


# ---------------------------------------------------------------------------
# Structure
# ---------------------------------------------------------------------------
def test_atr_basic(random_ohlcv: pd.DataFrame) -> None:
    a = atr(random_ohlcv, period=14)
    assert len(a) == len(random_ohlcv)
    assert a.iloc[14:].notna().all()
    assert (a.iloc[14:] >= 0).all()


def test_ema_period_validation() -> None:
    s = pd.Series([1.0, 2.0, 3.0, 4.0])
    with pytest.raises(ValueError):
        ema(s, period=0)


def test_swing_highs_lows_simple() -> None:
    """Bilinen pencerede swing tespiti."""
    df = pd.DataFrame(
        {
            "high": [1, 2, 5, 2, 1, 3, 6, 3, 2],
            "low":  [0, 1, 4, 1, 0, 2, 5, 2, 1],
            "open": [0, 1, 4, 1, 0, 2, 5, 2, 1],
            "close":[1, 2, 5, 2, 1, 3, 6, 3, 2],
        }
    )
    sh = swing_highs(df, n=2)
    sl = swing_lows(df, n=2)
    # index 2 ve 6 swing high; index 4 swing low (sol-sağ 2 bar değerlendirilebilir)
    assert bool(sh.iloc[2])
    assert bool(sh.iloc[6])
    assert bool(sl.iloc[4])


def test_support_resistance_returns(random_ohlcv: pd.DataFrame) -> None:
    sr = support_resistance(random_ohlcv, lookback=200, min_touches=2, cluster_atr_mult=0.5)
    assert set(sr.columns) >= {"level", "strength", "last_touch_ts"}


# ---------------------------------------------------------------------------
# Filters
# ---------------------------------------------------------------------------
def test_atr_threshold_off_means_all_true() -> None:
    a = pd.Series([1.0, 2.0, 3.0])
    p = pd.Series([100.0, 100.0, 100.0])
    out = atr_threshold(a, min_pct=0.0, prices=p)
    assert out.all()


def test_volume_zscore_min_zero_passes_all() -> None:
    v = pd.Series(np.random.RandomState(0).normal(1000, 100, size=50))
    out = volume_zscore(v, period=20, min_z=0.0)
    assert out.all()


def test_ema_trend_filter_long(random_ohlcv: pd.DataFrame) -> None:
    out = ema_trend_filter(random_ohlcv["close"], period=20, side="long")
    assert out.dtype == bool
    # En azından bir satır True olmalı
    assert out.any()


def test_volatility_regime_dichotomy(random_ohlcv: pd.DataFrame) -> None:
    a = atr(random_ohlcv, period=14)
    reg = volatility_regime(a, period=30)
    assert set(reg.dropna().unique()).issubset({"high", "low"})


# ---------------------------------------------------------------------------
# Confluence skor + emit
# ---------------------------------------------------------------------------
def test_score_weighted_sum() -> None:
    flags = {
        "a": pd.Series([True, False, True]),
        "b": pd.Series([False, True, True]),
    }
    s = score(flags, {"a": 1.0, "b": 2.0})
    assert list(s) == [1.0, 2.0, 3.0]


def test_emit_signals_minimal(random_ohlcv: pd.DataFrame) -> None:
    """Manifest mini config ile sinyal akışı çalışmalı (sıfır veya pozitif sayıda sinyal)."""
    cfg = {
        "trend_filter": {"type": "ema", "period": 50, "required": False},
        "signals": {
            "patterns": [
                {"id": "bullish_pin_bar", "enabled": True, "weight": 1.0},
                {"id": "bearish_pin_bar", "enabled": True, "weight": 1.0},
            ],
            "structure": {
                "swing": {"fractal_n": 2},
                "support_resistance": {
                    "lookback_bars": 100,
                    "min_touches": 2,
                    "cluster_atr_multiplier": 0.5,
                },
                "require_proximity_to_sr_atr": 5.0,
            },
            "confluence": {"min_score": 0.5, "bonus_if_at_sr": 0.5},
            "filters": {"atr_min_pct": 0.0, "volume_zscore_min": 0.0},
        },
        "risk": {"stop_loss_atr_mult": 1.5, "take_profit_r": 2.0},
    }
    sigs = emit_signals(random_ohlcv, cfg, venue="binance", symbol="TEST/USDT", timeframe="1d")
    # sıfır olabilir; schema kontrolü yeterli
    for s in sigs:
        assert s.confluence_score >= 0.5
        assert s.manifest_hash
        assert s.fingerprint()
        assert s.direction in {"long", "short"}
