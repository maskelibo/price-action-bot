"""Causality and preregistration tests for crypto 15m residual signals."""

from __future__ import annotations

from datetime import UTC

import numpy as np
import pandas as pd
import pytest

from price_action.lab.crypto_15m_residual_signals import (
    FundingReversionCell,
    ResidualTrendCell,
    compute_causal_residual_features,
    generate_funding_confirmed_residual_reversion_intents,
    generate_residual_cross_sectional_trend_intents,
    validate_aligned_utc_15m_frames,
)


def _frame(index: pd.DatetimeIndex, returns: np.ndarray) -> pd.DataFrame:
    close = 100.0 * np.exp(np.cumsum(returns))
    opened = np.r_[close[0], close[:-1]]
    high = np.maximum(opened, close) * 1.002
    low = np.minimum(opened, close) * 0.998
    return pd.DataFrame(
        {
            "ts": index,
            "open": opened,
            "high": high,
            "low": low,
            "close": close,
            "volume": np.full(len(index), 1000.0),
        }
    )


def _frames(n: int = 900) -> dict[str, pd.DataFrame]:
    index = pd.date_range("2024-01-01", periods=n, freq="15min", tz=UTC)
    x = np.arange(n, dtype=float)
    btc = 0.0004 * np.sin(x / 11.0) + 0.0002 * np.cos(x / 29.0)
    return {
        "BTC/USDT": _frame(index, btc),
        "LONG/USDT": _frame(index, btc + 0.0008 + 0.0001 * np.sin(x / 7.0)),
        "SHORT/USDT": _frame(index, btc - 0.0008 + 0.0001 * np.cos(x / 7.0)),
        "MID/USDT": _frame(index, btc + 0.0001 * np.sin(x / 5.0)),
    }


def test_validation_rejects_non_utc_duplicates_and_misalignment() -> None:
    frames = _frames(40)
    bad_tz = {key: value.copy() for key, value in frames.items()}
    bad_tz["MID/USDT"]["ts"] = bad_tz["MID/USDT"]["ts"].dt.tz_convert("Europe/Istanbul")
    with pytest.raises(ValueError, match="UTC"):
        validate_aligned_utc_15m_frames(bad_tz)

    duplicate = {key: value.copy() for key, value in frames.items()}
    duplicate["MID/USDT"].loc[2, "ts"] = duplicate["MID/USDT"].loc[1, "ts"]
    with pytest.raises(ValueError, match="unique"):
        validate_aligned_utc_15m_frames(duplicate)

    misaligned = {key: value.copy() for key, value in frames.items()}
    misaligned["MID/USDT"] = misaligned["MID/USDT"].iloc[:-1]
    with pytest.raises(ValueError, match="aligned"):
        validate_aligned_utc_15m_frames(misaligned)

    shifted = {key: value.copy() for key, value in frames.items()}
    for frame in shifted.values():
        frame["ts"] = frame["ts"] + pd.Timedelta(minutes=7)
    with pytest.raises(ValueError, match="quarter-hour"):
        validate_aligned_utc_15m_frames(shifted)


def test_beta_is_shifted_one_bar_and_current_return_only_changes_residual() -> None:
    frames = _frames(100)
    features = compute_causal_residual_features(frames, beta_lookback_bars=20, atr_period=5)
    ts = features["LONG/USDT"].index[60]
    btc_ret = frames["BTC/USDT"]["close"].pct_change(fill_method=None)
    alt_ret = frames["LONG/USDT"]["close"].pct_change(fill_method=None)
    expected = alt_ret.iloc[40:60].cov(btc_ret.iloc[40:60]) / btc_ret.iloc[40:60].var()
    assert features["LONG/USDT"].loc[ts, "beta"] == pytest.approx(expected)

    changed = {key: value.copy() for key, value in frames.items()}
    changed["LONG/USDT"].loc[60:, ["open", "high", "low", "close"]] *= 1.2
    changed_features = compute_causal_residual_features(
        changed, beta_lookback_bars=20, atr_period=5
    )
    assert changed_features["LONG/USDT"].loc[ts, "beta"] == pytest.approx(
        features["LONG/USDT"].loc[ts, "beta"]
    )
    assert changed_features["LONG/USDT"].loc[ts, "residual_return"] != pytest.approx(
        features["LONG/USDT"].loc[ts, "residual_return"]
    )


def test_trend_prefix_invariance_holdouts_schedule_and_deterministic_sides() -> None:
    frames = _frames(900)
    cell = ResidualTrendCell(
        "TEST_TREND",
        formation_bars=20,
        beta_lookback_bars=20,
        hold_bars=40,
        long_k=1,
        short_k=1,
        atr_period=5,
    )
    kwargs = {"trade_holdouts": frozenset({"BTC/USDT", "MID/USDT"}), "warmup_bars_after_gap": 100}
    full = generate_residual_cross_sectional_trend_intents(frames, cell, **kwargs)
    prefix_frames = {key: frame.iloc[:700].copy() for key, frame in frames.items()}
    prefix = generate_residual_cross_sectional_trend_intents(prefix_frames, cell, **kwargs)

    cutoff = prefix_frames["BTC/USDT"]["ts"].iloc[-1].to_pydatetime()
    assert [intent for intent in full if intent.decision_ts <= cutoff] == prefix
    assert full
    assert {(intent.symbol, intent.side) for intent in full} == {
        ("LONG/USDT", "long"),
        ("SHORT/USDT", "short"),
    }
    assert all(
        intent.decision_ts.weekday() == 0
        and intent.decision_ts.hour == 0
        and intent.decision_ts.minute == 0
        for intent in full
    )


def test_btc_is_reference_only_even_when_not_listed_as_holdout() -> None:
    n = 900
    index = pd.date_range("2024-01-01", periods=n, freq="15min", tz=UTC)
    x = np.arange(n, dtype=float)
    btc = 0.0004 * np.sin(x / 11.0) + 0.0002 * np.cos(x / 29.0)
    frames = {
        "BTC/USDT": _frame(index, btc),
        "A/USDT": _frame(index, btc + 0.0009 + 0.0001 * np.sin(x / 5.0)),
        "B/USDT": _frame(index, btc + 0.0006 + 0.0001 * np.cos(x / 7.0)),
        "C/USDT": _frame(index, btc + 0.0003 + 0.0001 * np.sin(x / 9.0)),
    }
    cell = ResidualTrendCell("TEST_REFERENCE", 20, 20, 40, 1, 1, 5, 4.0)

    intents = generate_residual_cross_sectional_trend_intents(
        frames, cell, trade_holdouts=frozenset(), warmup_bars_after_gap=100
    )

    assert intents
    assert all(intent.symbol != "BTC/USDT" for intent in intents)


def test_trend_rank_uses_volatility_normalized_residual_not_raw_sum() -> None:
    n = 720
    decision_i = 672
    index = pd.date_range("2024-01-01", periods=n, freq="15min", tz=UTC)
    x = np.arange(n, dtype=float)
    btc = 0.0004 * np.sin(x / 13.0) + 0.0002 * np.cos(x / 31.0)
    high_vol = 0.0002 * np.sin(x / 3.0)
    steady = 0.0002 * np.cos(x / 5.0)
    negative = -0.0002 + 0.0001 * np.sin(x / 7.0)
    window = slice(decision_i - 19, decision_i + 1)
    high_vol[window] = 0.0015 + np.tile([0.010, -0.010], 10)
    steady[window] = 0.0008 + 0.0001 * np.sin(np.arange(20))
    negative[window] = -0.0008 + 0.0001 * np.cos(np.arange(20))
    frames = {
        "BTC/USDT": _frame(index, btc),
        "HIGH_RAW/USDT": _frame(index, btc + high_vol),
        "STEADY/USDT": _frame(index, btc + steady),
        "NEG/USDT": _frame(index, btc + negative),
    }
    cell = ResidualTrendCell("TEST_VOLNORM", 20, 60, 40, 1, 1, 5, 4.0)
    features = compute_causal_residual_features(frames, beta_lookback_bars=60, atr_period=5)
    ts = index[decision_i]
    raw_high = features["HIGH_RAW/USDT"]["residual_return"].rolling(20).sum().loc[ts]
    raw_steady = features["STEADY/USDT"]["residual_return"].rolling(20).sum().loc[ts]

    intents = generate_residual_cross_sectional_trend_intents(
        frames, cell, trade_holdouts=frozenset(), warmup_bars_after_gap=100
    )
    decision = [item for item in intents if item.decision_ts == ts.to_pydatetime()]

    assert raw_high > raw_steady
    assert ("STEADY/USDT", "long") in {(item.symbol, item.side) for item in decision}
    assert ("HIGH_RAW/USDT", "long") not in {(item.symbol, item.side) for item in decision}


def test_future_values_cannot_mutate_existing_trend_intents() -> None:
    frames = _frames(900)
    cell = ResidualTrendCell("TEST_TREND", 20, 20, 40, 1, 1, 5, 4.0)
    base = generate_residual_cross_sectional_trend_intents(
        frames, cell, trade_holdouts=frozenset({"BTC/USDT"}), warmup_bars_after_gap=100
    )
    changed = {key: value.copy() for key, value in frames.items()}
    for frame in changed.values():
        frame.loc[750:, ["open", "high", "low", "close"]] *= np.linspace(1.0, 4.0, 150)[:, None]
    mutated = generate_residual_cross_sectional_trend_intents(
        changed, cell, trade_holdouts=frozenset({"BTC/USDT"}), warmup_bars_after_gap=100
    )
    cutoff = frames["BTC/USDT"]["ts"].iloc[749].to_pydatetime()
    assert [item for item in base if item.decision_ts <= cutoff] == [
        item for item in mutated if item.decision_ts <= cutoff
    ]


def test_funding_reversion_requires_matching_crowding_sign() -> None:
    frames = _frames(400)
    decision_i = 320  # Thursday 08:00 UTC
    for offset in range(decision_i - 3, decision_i + 1):
        frames["LONG/USDT"].loc[offset:, ["open", "high", "low", "close"]] *= 0.97
        frames["SHORT/USDT"].loc[offset:, ["open", "high", "low", "close"]] *= 1.03
        frames["MID/USDT"].loc[offset:, ["open", "high", "low", "close"]] *= 1.03
    index = pd.DatetimeIndex(frames["BTC/USDT"]["ts"])
    funding = {
        "LONG/USDT": pd.Series(-0.001, index=index),
        "SHORT/USDT": pd.Series(0.001, index=index),
        "MID/USDT": pd.Series(-0.001, index=index),  # wrong sign for positive residual
    }
    cell = FundingReversionCell(
        "TEST_REV",
        1.5,
        16,
        beta_lookback_bars=20,
        formation_bars=4,
        z_lookback_bars=40,
        long_k=1,
        short_k=1,
        atr_period=5,
    )
    intents = generate_funding_confirmed_residual_reversion_intents(
        frames,
        funding,
        cell,
        trade_holdouts=frozenset({"BTC/USDT"}),
        warmup_bars_after_gap=50,
    )
    at_decision = [
        item for item in intents if item.decision_ts == index[decision_i].to_pydatetime()
    ]
    assert {(item.symbol, item.side) for item in at_decision} == {
        ("LONG/USDT", "long"),
        ("SHORT/USDT", "short"),
    }
    assert all(item.symbol != "BTC/USDT" for item in intents)
    assert all(
        item.decision_ts.hour in {0, 8, 16} and item.decision_ts.minute == 0 for item in intents
    )


def test_gap_blocks_signals_for_500_bars_then_recovers() -> None:
    frames = _frames(2200)
    frames = {
        key: pd.concat([frame.iloc[:1300], frame.iloc[1304:]], ignore_index=True)
        for key, frame in frames.items()
    }
    cell = ResidualTrendCell("TEST_GAP", 20, 20, 40, 1, 1, 5, 4.0)
    intents = generate_residual_cross_sectional_trend_intents(
        frames,
        cell,
        trade_holdouts=frozenset({"BTC/USDT"}),
        warmup_bars_after_gap=500,
    )
    times = {item.decision_ts for item in intents}
    suppressed = pd.Timestamp("2024-01-15T00:00:00Z").to_pydatetime()
    recovered = pd.Timestamp("2024-01-22T00:00:00Z").to_pydatetime()
    assert suppressed not in times
    assert recovered in times


def test_gap_invalidates_cross_gap_return_and_rolling_beta_window() -> None:
    frames = _frames(160)
    frames = {
        key: pd.concat([frame.iloc[:80], frame.iloc[84:]], ignore_index=True)
        for key, frame in frames.items()
    }

    features = compute_causal_residual_features(frames, beta_lookback_bars=20, atr_period=5)
    after_gap = features["LONG/USDT"].iloc[80:]

    assert pd.isna(after_gap["asset_return"].iloc[0])
    assert after_gap["beta"].iloc[:21].isna().all()
    assert np.isfinite(after_gap["beta"].iloc[21])


def test_holdout_policy_must_be_explicit_at_public_generator_boundary() -> None:
    frames = _frames(100)
    cell = ResidualTrendCell("TEST_EXPLICIT", 20, 20, 40, 1, 1, 5, 4.0)

    with pytest.raises(ValueError, match="explicitly"):
        generate_residual_cross_sectional_trend_intents(frames, cell)
