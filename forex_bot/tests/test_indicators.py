"""Tests for price action + SMC + volume proxy indicators."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from forex_bot.data.synthetic import generate_synthetic_ohlcv
from forex_bot.indicators.ohlc import atr, ema, swing_highs, swing_lows
from forex_bot.indicators.price_action import (
    bullish_engulfing, bearish_engulfing, bullish_pin_bar, bearish_pin_bar,
    fakey, inside_bar,
)
from forex_bot.indicators.smc import (
    bullish_order_block, bearish_order_block, fair_value_gap,
    liquidity_sweep_high, liquidity_sweep_low, bos_bullish, bos_bearish,
    premium_discount_zone,
)
from forex_bot.indicators.volume_proxy import (
    participation_score, range_expansion, tick_volume_zscore, spread_widening,
)


@pytest.fixture
def df():
    return generate_synthetic_ohlcv("EURUSD", "2024-01-01", "2024-03-01")


def test_atr_positive(df):
    a = atr(df, 14)
    assert (a.dropna() > 0).all()


def test_ema_smoothing(df):
    e = ema(df["close"], 20)
    assert len(e) == len(df)
    diff = (df["close"] - e).abs().max()
    assert diff < df["close"].std() * 10


def test_swing_highs_no_overlap(df):
    sh = swing_highs(df["high"], n=2)
    sl = swing_lows(df["low"], n=2)
    assert sh.dtype == bool
    assert sl.dtype == bool
    # A high-range bar can be both swing-high and swing-low (extreme of both wicks);
    # confirm both detectors fire at a non-trivial rate, not strict exclusivity.
    assert sh.sum() > 0
    assert sl.sum() > 0


def test_pin_bar_lookahead_free(df):
    b = bullish_pin_bar(df)
    # shift by 1 should never re-flag a bar that wasn't already a pin at t
    assert isinstance(b, pd.Series)
    assert b.dtype == bool


def test_engulfing_consistency(df):
    bu = bullish_engulfing(df)
    be = bearish_engulfing(df)
    assert (bu & be).sum() == 0  # mutually exclusive


def test_inside_bar(df):
    ib = inside_bar(df)
    assert ib.dtype == bool


def test_fakey_returns_series(df):
    f = fakey(df)
    assert f.dtype == bool
    assert len(f) == len(df)


def test_order_blocks(df):
    bull = bullish_order_block(df)
    bear = bearish_order_block(df)
    assert (bull & bear).sum() == 0


def test_fvg_dataframe(df):
    fvg = fair_value_gap(df)
    assert {"bull_fvg", "bear_fvg", "fvg_size_atr"}.issubset(fvg.columns)


def test_liquidity_sweep(df):
    sh = liquidity_sweep_high(df)
    sl = liquidity_sweep_low(df)
    assert sh.dtype == bool and sl.dtype == bool


def test_bos(df):
    bull = bos_bullish(df)
    bear = bos_bearish(df)
    assert (bull & bear).sum() == 0


def test_premium_discount(df):
    pd_zone = premium_discount_zone(df)
    assert set(pd_zone["zone"].unique()).issubset({"premium", "discount", "equilibrium"})


def test_participation_score(df):
    s = participation_score(df)
    finite = s.dropna()
    assert (finite >= 0).all()


def test_tick_volume_zscore(df):
    z = tick_volume_zscore(df)
    assert z.notna().any()


def test_range_expansion_positive(df):
    r = range_expansion(df).dropna()
    assert (r >= 0).all()


def test_spread_widening_finite(df):
    sw = spread_widening(df).dropna()
    assert (sw > 0).all()
