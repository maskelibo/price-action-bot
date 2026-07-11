"""Causality and preregistration tests for v17 dynamic pair signals."""

from __future__ import annotations

import math
from dataclasses import replace
from datetime import UTC, datetime

import numpy as np
import pandas as pd
import pytest

from price_action.lab import crypto_15m_pairs_signals as pairs


def _frame(index: pd.DatetimeIndex, close: np.ndarray, volume: float = 1_000.0) -> pd.DataFrame:
    opened = np.r_[close[0], close[:-1]]
    return pd.DataFrame(
        {
            "ts": index,
            "open": opened,
            "high": np.maximum(opened, close) * 1.001,
            "low": np.minimum(opened, close) * 0.999,
            "close": close,
            "volume": volume,
        }
    )


def _selection_frames() -> dict[str, pd.DataFrame]:
    index = pd.date_range("2023-12-10", "2024-01-04", freq="15min", tz=UTC)
    step = np.arange(len(index), dtype=float)
    common_return = 0.0015 * np.sin(step / 11.0) + 0.0010 * np.cos(step / 29.0)
    log_x = math.log(100.0) + np.cumsum(common_return)
    residual = 0.001 * np.sin(step / 18.0)
    log_y = 0.03 + log_x + residual
    log_btc = math.log(30_000.0) + np.cumsum(common_return * 1.1)
    return {
        "BTC/USDT": _frame(index, np.exp(log_btc), 5_000.0),
        "A/USDT": _frame(index, np.exp(log_y), 1_000.0),
        "B/USDT": _frame(index, np.exp(log_x), 2_000.0),
    }


def _selection_cell() -> pairs.PairCell:
    return pairs.PairCell("TEST_SELECTION", 240, 168, 2.5, 0.5, 4.5, 1.0, 100.0, 168, 48)


def _manual_model(*, validation_std: float = 0.02) -> pairs.PairModel:
    return pairs.PairModel(
        candidate_id="TEST_ENTRY",
        pair_id="A/USDT|B/USDT",
        selection_ts=datetime(2024, 1, 1, tzinfo=UTC),
        y_symbol="A/USDT",
        x_symbol="B/USDT",
        alpha=0.0,
        beta=1.0,
        validation_mean=0.0,
        validation_std=validation_std,
        engle_granger_p=0.001,
        holm_adjusted_p=0.001,
        normalized_price_ssd=0.1,
        training_correlation=0.99,
        half_life_hours=24.0,
        pair_btc_beta=0.01,
        gross_weight_y=0.5,
        gross_weight_x=0.5,
        train_start=datetime(2023, 10, 1, tzinfo=UTC),
        train_end=datetime(2023, 12, 4, tzinfo=UTC),
        validation_start=datetime(2023, 12, 4, tzinfo=UTC),
        validation_end=datetime(2024, 1, 1, tzinfo=UTC),
    )


def _entry_cell() -> pairs.PairCell:
    return pairs.PairCell("TEST_ENTRY", 240, 168, 2.5, 0.5, 4.5, 1.0, 100.0, 8, 2)


def _entry_frames(*, spread: float = 0.06) -> dict[str, pd.DataFrame]:
    index = pd.date_range("2023-12-31T20:00:00Z", "2024-01-01T14:00:00Z", freq="15min")
    x_close = np.full(len(index), 100.0)
    log_spread = np.zeros(len(index))
    high = (index >= pd.Timestamp("2024-01-01T00:00:00Z")) & (
        index < pd.Timestamp("2024-01-01T05:00:00Z")
    )
    low = (index >= pd.Timestamp("2024-01-01T08:00:00Z")) & (
        index < pd.Timestamp("2024-01-01T13:00:00Z")
    )
    log_spread[high] = spread
    log_spread[low] = -spread
    y_close = x_close * np.exp(log_spread)
    return {
        "BTC/USDT": _frame(index, np.full(len(index), 30_000.0), 10_000.0),
        "A/USDT": _frame(index, y_close, 1_000.0),
        "B/USDT": _frame(index, x_close, 2_000.0),
    }


def _zero_funding() -> dict[str, pd.Series]:
    index = pd.date_range("2023-12-29", "2024-01-01", freq="8h", inclusive="left", tz=UTC)
    return {
        "A/USDT": pd.Series(0.0, index=index),
        "B/USDT": pd.Series(0.0, index=index),
    }


def _fake_candidate(first: str, second: str, cell: pairs.PairCell, selection: pd.Timestamp):
    pair_id = "|".join(sorted((first, second)))
    train_end = selection - pd.Timedelta(hours=cell.validation_hours)
    return pairs._PairCandidate(
        pair_id=pair_id,
        y_symbol=first,
        x_symbol=second,
        alpha=0.0,
        beta=1.0,
        validation_mean=0.0,
        validation_std=0.02,
        engle_granger_p=0.001,
        normalized_price_ssd=1.0,
        training_correlation=0.99,
        half_life_hours=24.0,
        pair_btc_beta=0.01,
        gross_weight_y=0.5,
        gross_weight_x=0.5,
        beta_relative_change=0.01,
        validation_mean_shift=0.01,
        validation_std_ratio=1.0,
        validation_crossings=10,
        train_start=(train_end - pd.Timedelta(hours=cell.train_hours)).to_pydatetime(),
        train_end=train_end.to_pydatetime(),
        validation_start=train_end.to_pydatetime(),
        validation_end=selection.to_pydatetime(),
    )


def test_holm_adjustment_is_step_down_and_validates_values() -> None:
    adjusted = pairs.holm_adjusted_pvalues({"a": 0.01, "b": 0.03, "c": 0.04})
    assert adjusted == pytest.approx({"a": 0.03, "b": 0.06, "c": 0.06})
    with pytest.raises(ValueError, match=r"\[0, 1\]"):
        pairs.holm_adjusted_pvalues({"bad": 1.1})


def test_engle_granger_uses_frozen_statsmodels_arguments(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, object] = {}

    def fake_coint(y, x, **kwargs):
        observed.update(kwargs)
        assert len(y) == len(x)
        return -4.0, 0.01, np.array([-3.0, -2.0, -1.0])

    monkeypatch.setattr(pairs, "coint", fake_coint)
    pvalue = pairs._engle_granger_p(np.arange(40.0), np.arange(40.0) + 1.0)

    assert pvalue == pytest.approx(0.01)
    assert observed == {"trend": "c", "maxlag": 24, "autolag": "aic"}


def test_holm_family_contains_all_data_eligible_pairs_before_gatev_top20(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    universe = tuple(f"S{i}/USDT" for i in range(7))  # 21 unordered pairs
    selection = pd.Timestamp("2024-01-01T00:00:00Z")
    cell = _selection_cell()
    observed: list[int] = []
    original_holm = pairs.holm_adjusted_pvalues

    def fake_candidate(_frames, first, second, passed_cell, passed_selection, **_kwargs):
        return _fake_candidate(first, second, passed_cell, passed_selection)

    def capture_holm(pvalues):
        observed.append(len(pvalues))
        return original_holm(pvalues)

    monkeypatch.setattr(pairs, "_candidate_from_pair", fake_candidate)
    monkeypatch.setattr(pairs, "holm_adjusted_pvalues", capture_holm)
    selected = pairs._select_at_normalized(
        {},
        universe,
        cell,
        selection,
        snapshot_sha256="a" * 64,
        btc_symbol="BTC/USDT",
        minimum_completeness=0.95,
    )

    assert observed == [21]
    assert len(selected) == 3


def test_deterministic_tie_hash_drives_nonoverlap_selection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    universe = tuple(f"S{i}/USDT" for i in range(6))
    selection = pd.Timestamp("2024-01-01T00:00:00Z")
    cell = _selection_cell()

    def fake_candidate(_frames, first, second, passed_cell, passed_selection, **_kwargs):
        return _fake_candidate(first, second, passed_cell, passed_selection)

    monkeypatch.setattr(pairs, "_candidate_from_pair", fake_candidate)
    first = pairs._select_at_normalized(
        {},
        universe,
        cell,
        selection,
        snapshot_sha256="b" * 64,
        btc_symbol="BTC/USDT",
        minimum_completeness=0.95,
    )
    second = pairs._select_at_normalized(
        {},
        tuple(reversed(universe)),
        cell,
        selection,
        snapshot_sha256="b" * 64,
        btc_symbol="BTC/USDT",
        minimum_completeness=0.95,
    )

    assert first == second
    assert len({symbol for model in first for symbol in (model.y_symbol, model.x_symbol)}) == 6


def test_selection_diagnostics_terminate_every_pair_with_specific_reason(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    universe = tuple(f"S{i}/USDT" for i in range(6))
    selection = pd.Timestamp("2024-01-01T00:00:00Z")
    cell = _selection_cell()

    def fake_candidate(_frames, first, second, passed_cell, passed_selection, **_kwargs):
        return _fake_candidate(first, second, passed_cell, passed_selection)

    monkeypatch.setattr(pairs, "_candidate_from_pair", fake_candidate)
    models, decisions = pairs._select_at_normalized_with_diagnostics(
        {},
        universe,
        cell,
        selection,
        snapshot_sha256="f" * 64,
        btc_symbol="BTC/USDT",
        minimum_completeness=0.95,
    )

    assert len(models) == 3
    assert len(decisions) == 15
    assert sum(decision.status == "selected" for decision in decisions) == 3
    assert {decision.reason for decision in decisions} <= {
        "SELECTED",
        "SYMBOL_OVERLAP_WITH_HIGHER_RANKED_PAIR",
        "MAX_SELECTED_PAIRS_REACHED",
    }
    assert len({decision.pair_id for decision in decisions}) == 15


def test_selection_diagnostics_bind_data_and_statistical_rejection_stages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    selection = pd.Timestamp("2024-01-01T00:00:00Z")
    cell = _selection_cell()

    monkeypatch.setattr(pairs, "_candidate_from_pair", lambda *_args, **_kwargs: None)
    _models, decisions = pairs._select_at_normalized_with_diagnostics(
        {},
        ("A/USDT", "B/USDT"),
        cell,
        selection,
        snapshot_sha256="a" * 64,
        btc_symbol="BTC/USDT",
        minimum_completeness=0.95,
    )
    assert decisions[0].reason == "DATA_WINDOW_INELIGIBLE"

    def low_correlation(_frames, first, second, passed_cell, passed_selection, **_kwargs):
        candidate = _fake_candidate(first, second, passed_cell, passed_selection)
        return replace(candidate, training_correlation=0.50)

    monkeypatch.setattr(pairs, "_candidate_from_pair", low_correlation)
    _models, decisions = pairs._select_at_normalized_with_diagnostics(
        {},
        ("A/USDT", "B/USDT"),
        cell,
        selection,
        snapshot_sha256="a" * 64,
        btc_symbol="BTC/USDT",
        minimum_completeness=0.95,
    )
    assert decisions[0].reason == "TRAINING_CORRELATION_BELOW_0P75"


def test_selection_is_prefix_causal_and_uses_previous_45_bar_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    frames = _selection_frames()
    cell = _selection_cell()
    selection = datetime(2024, 1, 1, tzinfo=UTC)
    monkeypatch.setattr(pairs, "_engle_granger_p", lambda _y, _x: 0.001)
    base = pairs.select_pairs_at_timestamp(
        frames, ["A/USDT", "B/USDT"], cell, selection, snapshot_sha256="c" * 64
    )
    assert base

    changed = {symbol: frame.copy() for symbol, frame in frames.items()}
    future = changed["A/USDT"]["ts"] >= pd.Timestamp(selection)
    changed["A/USDT"].loc[future, ["open", "high", "low", "close"]] *= 3.0
    same = pairs.select_pairs_at_timestamp(
        changed, ["A/USDT", "B/USDT"], cell, selection, snapshot_sha256="c" * 64
    )
    assert same == base

    with pytest.raises(ValueError, match="first Monday"):
        pairs.select_pairs_at_timestamp(
            frames,
            ["A/USDT", "B/USDT"],
            cell,
            datetime(2024, 1, 2, tzinfo=UTC),
            snapshot_sha256="c" * 64,
        )


def test_unrelated_symbol_gap_does_not_remove_pair_local_hours(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    frames = _selection_frames()
    cell = _selection_cell()
    selection = datetime(2024, 1, 1, tzinfo=UTC)
    monkeypatch.setattr(pairs, "_engle_granger_p", lambda _y, _x: 0.001)
    base = pairs.select_pairs_at_timestamp(
        frames, ["A/USDT", "B/USDT"], cell, selection, snapshot_sha256="d" * 64
    )
    frames["C/USDT"] = frames["A/USDT"].iloc[::8].reset_index(drop=True)
    with_unrelated_gap = pairs.select_pairs_at_timestamp(
        frames,
        ["A/USDT", "B/USDT", "C/USDT"],
        cell,
        selection,
        snapshot_sha256="d" * 64,
    )

    assert base
    assert with_unrelated_gap == base


def test_hourly_formation_requires_all_four_bars_sums_volume_and_keeps_real_time() -> None:
    index = pd.date_range("2024-01-01", periods=8, freq="15min", tz=UTC)
    frames = {
        "BTC/USDT": _frame(index, np.full(8, 30_000.0), 10.0),
        "A/USDT": _frame(index, np.arange(100.0, 108.0), 2.0),
        "B/USDT": _frame(index, np.arange(200.0, 208.0), 3.0),
    }
    frames["B/USDT"] = frames["B/USDT"].drop(index=1).reset_index(drop=True)
    clean = pairs.normalize_pair_frames(frames)
    hourly = pairs._pair_hourly_window(
        clean,
        "A/USDT",
        "B/USDT",
        "BTC/USDT",
        start=pd.Timestamp("2024-01-01T00:00:00Z"),
        end=pd.Timestamp("2024-01-01T02:00:00Z"),
    )

    assert list(hourly.index) == [pd.Timestamp("2024-01-01T01:45:00Z")]
    assert hourly.iloc[0]["A/USDT:close"] == pytest.approx(107.0)
    assert hourly.iloc[0]["A/USDT:volume"] == pytest.approx(8.0)
    assert hourly.iloc[0]["B/USDT:volume"] == pytest.approx(12.0)


def test_longest_hourly_block_tie_uses_latest_and_validation_must_reach_cutoff() -> None:
    index = pd.DatetimeIndex(
        [
            "2024-01-01T00:45:00Z",
            "2024-01-01T01:45:00Z",
            "2024-01-01T04:45:00Z",
            "2024-01-01T05:45:00Z",
        ]
    )
    frame = pd.DataFrame({"value": range(4)}, index=index)
    longest = pairs._longest_exact_hour_block(frame)
    suffix = pairs._exact_hour_suffix(frame, expected_last=pd.Timestamp("2024-01-01T05:45:00Z"))
    missing_cutoff = pairs._exact_hour_suffix(
        frame, expected_last=pd.Timestamp("2024-01-01T06:45:00Z")
    )

    assert list(longest.index) == list(index[-2:])
    assert list(suffix.index) == list(index[-2:])
    assert missing_cutoff.empty


def test_validation_mean_crossings_ignore_zero_touches_and_nonadjacent_hours() -> None:
    index = pd.DatetimeIndex(
        [
            "2024-01-01T00:45:00Z",
            "2024-01-01T01:45:00Z",
            "2024-01-01T02:45:00Z",
            "2024-01-01T03:45:00Z",
            "2024-01-01T05:45:00Z",
            "2024-01-01T06:45:00Z",
        ]
    )
    values = np.array([-1.0, 1.0, 0.0, -1.0, 1.0, -1.0])

    crossings = pairs._mean_crossings(values, 0.0, index)

    # 00:45 -> 01:45 and 05:45 -> 06:45 are the only strict, adjacent flips.
    # The zero touch and the two-hour gap deliberately do not bridge a sign.
    assert crossings == 2


def test_early_formation_month_is_explicitly_empty_not_shifted() -> None:
    frames = _selection_frames()
    selections = pairs.select_pairs_monthly(
        frames,
        ["A/USDT", "B/USDT"],
        pairs.PairCell("EARLY", 2_160, 672, 2.5, 0.5, 4.5, 1.0, 100.0, 168, 48),
        start=datetime(2024, 1, 1, tzinfo=UTC),
        end=datetime(2024, 2, 1, tzinfo=UTC),
        snapshot_sha256="e" * 64,
    )
    assert selections == {datetime(2024, 1, 1, tzinfo=UTC): ()}


def test_high_and_low_spread_sides_no_btc_and_next_open_timestamp() -> None:
    model = _manual_model()
    intents = pairs.generate_pair_entry_intents(
        _entry_frames(),
        _zero_funding(),
        _entry_cell(),
        {model.selection_ts: (model,)},
    )
    sides = {(intent.y_side, intent.x_side) for intent in intents}

    assert ("short", "long") in sides
    assert ("long", "short") in sides
    assert all("BTC/USDT" not in {intent.y_symbol, intent.x_symbol} for intent in intents)
    assert all(intent.decision_ts.minute == 45 for intent in intents)
    assert all(
        intent.entry_ts - intent.decision_ts == pd.Timedelta(minutes=15) for intent in intents
    )
    assert all(intent.entry_abs_z == pytest.approx(2.5) for intent in intents)


def test_economic_gate_rejects_insufficient_edge_and_disaster_entry() -> None:
    low_scale_model = _manual_model(validation_std=0.01)
    low_edge = pairs.generate_pair_entry_intents(
        _entry_frames(spread=0.03),
        _zero_funding(),
        _entry_cell(),
        {low_scale_model.selection_ts: (low_scale_model,)},
    )
    disaster = pairs.generate_pair_entry_intents(
        _entry_frames(spread=0.10),
        _zero_funding(),
        _entry_cell(),
        {_manual_model().selection_ts: (_manual_model(),)},
    )
    assert low_edge == ()
    assert disaster == ()
    assert pairs.economic_entry_requirement(0.0) == pytest.approx(0.0171)
    assert pairs.economic_entry_requirement(0.01) == pytest.approx(0.0471)


def test_funding_cutoff_excludes_same_entry_event_and_prefix_intents_are_stable() -> None:
    model = _manual_model()
    entry_ts = pd.Timestamp("2024-01-01T01:00:00Z")
    history = pd.DatetimeIndex(
        [
            "2023-12-31T00:00:00Z",
            "2023-12-31T08:00:00Z",
            "2023-12-31T16:00:00Z",
            entry_ts,
        ]
    )
    funding = {
        "A/USDT": pd.Series([0.0, 0.0, 0.0, -0.50], index=history),
        "B/USDT": pd.Series([0.0, 0.0, 0.0, 0.50], index=history),
    }
    adverse = pairs.adverse_funding_for_entry(
        funding,
        model,
        entry_ts=entry_ts,
        y_side="short",
        x_side="long",
        max_hold_hours=8,
    )
    assert adverse == pytest.approx(0.0)

    bare_adverse = pairs.adverse_funding_for_entry(
        {"A": funding["A/USDT"], "B": funding["B/USDT"]},
        model,
        entry_ts=entry_ts,
        y_side="short",
        x_side="long",
        max_hold_hours=8,
    )
    assert bare_adverse == pytest.approx(adverse)

    frames = _entry_frames()
    base = pairs.generate_pair_entry_intents(
        frames, _zero_funding(), _entry_cell(), {model.selection_ts: (model,)}
    )
    cutoff = pd.Timestamp("2024-01-01T07:00:00Z")
    changed = {symbol: frame.copy() for symbol, frame in frames.items()}
    future = changed["A/USDT"]["ts"] >= cutoff
    changed["A/USDT"].loc[future, ["open", "high", "low", "close"]] *= 1.5
    mutated = pairs.generate_pair_entry_intents(
        changed, _zero_funding(), _entry_cell(), {model.selection_ts: (model,)}
    )
    assert [intent for intent in base if intent.entry_ts <= cutoff.to_pydatetime()] == [
        intent for intent in mutated if intent.entry_ts <= cutoff.to_pydatetime()
    ]


def test_adverse_funding_uses_normalized_strict_cutoff_and_per_leg_min_cadence() -> None:
    model = _manual_model()
    entry_ts = pd.Timestamp("2024-01-01T01:00:00Z")
    funding = {
        "A/USDT": pd.Series(
            [-0.001, -0.001, -0.001, -1.0],
            index=pd.DatetimeIndex(
                [
                    entry_ts - pd.Timedelta(hours=12),
                    entry_ts - pd.Timedelta(hours=8),
                    entry_ts - pd.Timedelta(hours=4),
                    entry_ts + pd.Timedelta(milliseconds=900),
                ]
            ),
        ),
        "B/USDT": pd.Series(
            [0.002, 0.002, 0.002, 1.0],
            index=pd.DatetimeIndex(
                [
                    entry_ts - pd.Timedelta(hours=24),
                    entry_ts - pd.Timedelta(hours=16),
                    entry_ts - pd.Timedelta(hours=8),
                    entry_ts + pd.Timedelta(milliseconds=500),
                ]
            ),
        ),
    }
    adverse = pairs.adverse_funding_for_entry(
        funding,
        model,
        entry_ts=entry_ts,
        y_side="short",
        x_side="long",
        max_hold_hours=8,
    )

    # Y cadence 4h -> two events: .5 * .001 * 2. X cadence 8h -> one:
    # .5 * .002 * 1. Fractional events floor to entry_ts and remain excluded.
    assert adverse == pytest.approx(0.002)
