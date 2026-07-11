"""Causality and live-policy binding tests for the v15p2 signal adapter."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from datetime import UTC, timedelta
from pathlib import Path
from time import perf_counter
from typing import Any

import numpy as np
import pandas as pd
import pytest
import yaml

from price_action.contracts import Signal
from price_action.lab import crypto_15m_v15p2_signals as v15
from price_action.lab.crypto_15m_v15p2_engine import simulate_v15p2_portfolio
from price_action.strategies.base import StrategyManifest


def _frame(index: pd.DatetimeIndex, *, price: float = 100.0) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "ts": index,
            "open": np.full(len(index), price),
            "high": np.full(len(index), price * 1.01),
            "low": np.full(len(index), price * 0.99),
            "close": np.full(len(index), price),
            "volume": np.full(len(index), 1_000.0),
        }
    )


def _policy() -> v15.V15P2SignalPolicy:
    return v15.load_current_v15p2_signal_policy()


def _manifest(name: str) -> StrategyManifest:
    return StrategyManifest.model_validate({"name": name})


def _fake_strategy_type(
    name: str,
    *,
    score: float,
    stop_distance: float,
    side: str,
    positions: tuple[int, ...] | None,
):
    pattern = "fake_long" if side == "long" else "fake_short"

    class FakeStrategy:
        def __init__(self, manifest: StrategyManifest) -> None:
            self.name = name
            self.manifest = manifest

        def prepare_features(self, frame: pd.DataFrame) -> pd.DataFrame:
            return frame.copy()

        def generate_signals(self, frame: pd.DataFrame) -> list[Signal]:
            selected = range(len(frame)) if positions is None else positions
            output: list[Signal] = []
            for location in selected:
                if location < 0 or location >= len(frame):
                    continue
                entry = float(frame.iloc[location]["open"])
                stop = (
                    entry * (1.0 - stop_distance)
                    if side == "long"
                    else entry * (1.0 + stop_distance)
                )
                take_profit = entry * (1.10 if side == "long" else 0.90)
                output.append(
                    Signal(
                        ts=pd.Timestamp(frame.iloc[location]["ts"]).to_pydatetime(),
                        venue=str(frame.iloc[location]["venue"]),
                        symbol=str(frame.iloc[location]["symbol"]),
                        timeframe="15m",
                        direction=side,  # type: ignore[arg-type]
                        pattern_id=pattern,
                        confluence_score=score,
                        sl_price=stop,
                        tp_price=take_profit,
                        suggested_size_atr=1.0,
                        manifest_hash=self.manifest.hash(),
                    )
                )
            return output

    return FakeStrategy


def _fake_specs(
    *,
    vsa_score: float = 0.25,
    vsa_stop: float = 0.03,
    vsa_side: str = "long",
    grimes_score: float = 0.25,
    grimes_stop: float = 0.03,
    grimes_side: str = "short",
    positions: tuple[int, ...] | None = (499,),
) -> tuple[v15._StrategySpec, ...]:
    vsa_type = _fake_strategy_type(
        "vsa_climax_test",
        score=vsa_score,
        stop_distance=vsa_stop,
        side=vsa_side,
        positions=positions,
    )
    grimes_type = _fake_strategy_type(
        "grimes_abc_pullback",
        score=grimes_score,
        stop_distance=grimes_stop,
        side=grimes_side,
        positions=positions,
    )
    return (
        v15._StrategySpec(
            "vsa_climax_test",
            vsa_type,  # type: ignore[arg-type]
            lambda: _manifest("vsa_climax_test"),
        ),
        v15._StrategySpec(
            "grimes_abc_pullback",
            grimes_type,  # type: ignore[arg-type]
            lambda: _manifest("grimes_abc_pullback"),
        ),
    )


def test_canonical_policy_binds_current_config_and_actual_strategy_apis() -> None:
    policy = _policy()

    assert policy.candidate_id == "v15p2_fair_baseline"
    assert policy.strategy_order == ("vsa_climax_test", "grimes_abc_pullback")
    assert policy.confidence_min == pytest.approx(0.25)
    assert policy.stop_distance_pct_min == pytest.approx(0.025)
    assert policy.warmup_bars == 500
    assert policy.timeframe == "15m"
    assert policy.config_sha256 == v15.EXPECTED_CONFIG_SHA256

    frame = _frame(pd.date_range("2024-01-01", periods=500, freq="15min", tz=UTC))
    frame["symbol"] = "TEST/USDT"
    frame["venue"] = "binance"
    frame["timeframe"] = "15m"
    frame["vol_z_pre"] = 0.0
    specs = v15._strategy_specs()
    assert tuple(spec.name for spec in specs) == policy.strategy_order
    for spec in specs:
        strategy = spec.strategy_type(spec.manifest_factory())
        prepared = strategy.prepare_features(frame.copy())
        signals = strategy.generate_signals(prepared)
        assert strategy.name == spec.name
        assert strategy.manifest.name == spec.name
        assert strategy.manifest.hash() == v15.EXPECTED_SIGNAL_MANIFEST_HASHES[spec.name]
        assert isinstance(signals, list)
        assert all(isinstance(signal, Signal) for signal in signals)
    assert specs[0].strategy_type.__name__ == "VSAClimaxTestStrategy"
    assert specs[1].strategy_type.__name__ == "GrimesABCPullbackStrategy"


def test_config_binding_rejects_hash_drift_and_semantic_strategy_reorder(
    tmp_path: Path,
) -> None:
    with pytest.raises(ValueError, match="does not identify"):
        v15.generate_v15p2_intents(
            {"A/USDT": _frame(pd.date_range("2024-01-01", periods=2, freq="15min", tz=UTC))},
            config_sha256="0" * 64,
        )

    raw = yaml.safe_load(v15.CANONICAL_CONFIG_PATH.read_text(encoding="utf-8"))
    raw["strategies_enabled"] = list(reversed(raw["strategies_enabled"]))
    changed = tmp_path / "changed.yaml"
    changed.write_text(yaml.safe_dump(raw), encoding="utf-8")
    with pytest.raises(ValueError, match="VSA then Grimes"):
        v15.load_current_v15p2_signal_policy(changed, expected_sha256=None)


def test_next_contiguous_open_and_explicit_stop_distances_are_deterministic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(v15, "_strategy_specs", lambda: _fake_specs())
    index = pd.date_range("2024-01-01", periods=501, freq="15min", tz=UTC)
    frame = _frame(index)
    frame.loc[499, "close"] = 101.0
    frame.loc[500, ["open", "high", "low", "close"]] = [123.0, 124.0, 122.0, 123.5]

    intents = v15.generate_current_v15p2_signal_intents({"A/USDT": frame}, policy=_policy())

    assert len(intents) == 1
    intent = intents[0]
    assert intent.candidate_id == "v15p2_fair_baseline"
    assert intent.decision_ts == index[499].to_pydatetime()
    assert intent.entry_ts == index[500].to_pydatetime()
    assert intent.decision_close == pytest.approx(101.0)
    assert intent.entry_reference_price == pytest.approx(101.0)
    assert intent.entry_price == pytest.approx(123.0)
    assert intent.decision_stop_distance_pct == pytest.approx((101.0 - 97.0) / 101.0)
    assert intent.entry_stop_distance_pct == pytest.approx((123.0 - 97.0) / 123.0)
    assert intent.strategy == "vsa_climax_test"
    assert intent.strategy_rank == 0
    assert intent.side == "long"


@pytest.mark.parametrize(
    ("score", "stop_distance", "expected"),
    [
        (0.25, 0.025, 1),
        (0.249999, 0.03, 0),
        (0.25, 0.024999, 0),
    ],
)
def test_confidence_and_decision_close_stop_gates_are_inclusive(
    monkeypatch: pytest.MonkeyPatch,
    score: float,
    stop_distance: float,
    expected: int,
) -> None:
    monkeypatch.setattr(
        v15,
        "_strategy_specs",
        lambda: _fake_specs(
            vsa_score=score,
            vsa_stop=stop_distance,
            grimes_score=0.0,
            positions=(499,),
        ),
    )
    frame = _frame(pd.date_range("2024-01-01", periods=501, freq="15min", tz=UTC))

    intents = v15.generate_current_v15p2_signal_intents({"A/USDT": frame}, policy=_policy())

    assert len(intents) == expected


@pytest.mark.parametrize(
    ("stop_distance", "next_open", "expected"),
    [
        (0.02, 110.0, 0),  # next-open distance passes; live decision-close gate rejects
        (0.03, 98.0, 1),  # next-open distance fails; live decision-close gate accepts
    ],
)
def test_widestop_never_selects_on_the_unknown_next_open(
    monkeypatch: pytest.MonkeyPatch,
    stop_distance: float,
    next_open: float,
    expected: int,
) -> None:
    monkeypatch.setattr(
        v15,
        "_strategy_specs",
        lambda: _fake_specs(
            vsa_stop=stop_distance,
            grimes_score=0.0,
            positions=(499,),
        ),
    )
    frame = _frame(pd.date_range("2024-01-01", periods=501, freq="15min", tz=UTC))
    frame.loc[500, ["open", "high", "low", "close"]] = [
        next_open,
        max(101.0, next_open),
        min(99.0, next_open),
        next_open,
    ]

    intents = v15.generate_current_v15p2_signal_intents({"A/USDT": frame}, policy=_policy())

    assert len(intents) == expected
    if intents:
        assert intents[0].decision_stop_distance_pct == pytest.approx(stop_distance)
        assert intents[0].entry_stop_distance_pct == pytest.approx(
            abs(next_open - (100.0 * (1.0 - stop_distance))) / next_open
        )


def test_grimes_wins_only_when_higher_priority_vsa_fails_a_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        v15,
        "_strategy_specs",
        lambda: _fake_specs(vsa_score=0.249, grimes_score=0.25),
    )
    frame = _frame(pd.date_range("2024-01-01", periods=501, freq="15min", tz=UTC))

    intents = v15.generate_current_v15p2_signal_intents({"A/USDT": frame}, policy=_policy())

    assert len(intents) == 1
    assert intents[0].strategy == "grimes_abc_pullback"
    assert intents[0].strategy_rank == 1
    assert intents[0].side == "short"


def test_all_same_decision_intents_survive_in_strategy_priority_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(v15, "_strategy_specs", lambda: _fake_specs())
    frame = _frame(pd.date_range("2024-01-01", periods=501, freq="15min", tz=UTC))

    intents = v15.generate_current_v15p2_signal_intents({"A/USDT": frame}, policy=_policy())

    assert [(intent.strategy, intent.side, intent.strategy_rank) for intent in intents] == [
        ("vsa_climax_test", "long", 0),
        ("grimes_abc_pullback", "short", 1),
    ]


def test_signal_batch_ledgers_every_raw_emission_and_reconciles(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(v15, "_strategy_specs", lambda: _fake_specs())
    index = pd.date_range("2024-01-01", periods=501, freq="15min", tz=UTC)
    frame = _frame(index)

    batch = v15.generate_v15p2_signal_batch({"A/USDT": frame})

    assert batch.raw_emission_count == 4
    assert batch.accepted_count == 2
    assert batch.rejected_count == 2
    assert [decision.emission_index for decision in batch.decisions] == list(range(4))
    accepted = [decision for decision in batch.decisions if decision.outcome == "accepted"]
    missing = [decision for decision in batch.decisions if decision.reason == "missing_next_bar"]
    assert [decision.strategy for decision in accepted] == list(v15.STRATEGY_ORDER)
    assert [decision.strategy for decision in missing] == list(v15.STRATEGY_ORDER)
    assert [decision.decision_ts for decision in accepted] == [
        index[499].to_pydatetime(),
        index[499].to_pydatetime(),
    ]
    assert [decision.entry_ts for decision in accepted] == [
        index[500].to_pydatetime(),
        index[500].to_pydatetime(),
    ]
    for decision in batch.decisions:
        assert decision.candidate_id == batch.candidate_id
        assert decision.config_sha256 == batch.config_sha256
        assert decision.signal_manifest_hash == _manifest(decision.strategy).hash()
        assert decision.decision_stop_distance_pct == pytest.approx(0.03)
        assert decision.entry_reference_price == decision.decision_close
    for decision in accepted:
        assert decision.entry_price == pytest.approx(100.0)
        assert decision.entry_stop_distance_pct == pytest.approx(0.03)
    for decision in missing:
        assert decision.entry_ts is None
        assert decision.entry_price is None
        assert decision.entry_stop_distance_pct is None

    assert [
        (
            decision.decision_ts,
            decision.entry_ts,
            decision.symbol,
            decision.strategy,
            decision.side,
            decision.pattern_id,
            decision.stop_price,
            decision.take_profit_price,
            decision.signal_manifest_hash,
        )
        for decision in accepted
    ] == [
        (
            intent.decision_ts,
            intent.entry_ts,
            intent.symbol,
            intent.strategy,
            intent.side,
            intent.pattern_id,
            intent.stop_price,
            intent.take_profit_price,
            intent.signal_manifest_hash,
        )
        for intent in batch.intents
    ]
    assert v15.generate_v15p2_intents({"A/USDT": frame}) == batch.intents


@pytest.mark.parametrize(
    ("score", "stop_distance", "reason"),
    [
        (0.249, 0.03, "confidence_below_minimum"),
        (0.25, 0.024, "decision_stop_distance_below_minimum"),
    ],
)
def test_signal_batch_ledgers_confidence_and_decision_widestop_rejections(
    monkeypatch: pytest.MonkeyPatch,
    score: float,
    stop_distance: float,
    reason: str,
) -> None:
    monkeypatch.setattr(
        v15,
        "_strategy_specs",
        lambda: _fake_specs(
            vsa_score=score,
            vsa_stop=stop_distance,
            grimes_score=0.0,
        ),
    )
    frame = _frame(pd.date_range("2024-01-01", periods=501, freq="15min", tz=UTC))

    batch = v15.generate_current_v15p2_signal_batch({"A/USDT": frame}, policy=_policy())

    vsa_decisions = [
        decision for decision in batch.decisions if decision.strategy == "vsa_climax_test"
    ]
    assert len(vsa_decisions) == 2
    assert {decision.outcome for decision in vsa_decisions} == {"rejected"}
    assert {decision.reason for decision in vsa_decisions} == {reason}
    assert vsa_decisions[0].decision_stop_distance_pct == pytest.approx(stop_distance)
    assert vsa_decisions[0].entry_stop_distance_pct == pytest.approx(stop_distance)
    assert vsa_decisions[1].entry_ts is None
    assert vsa_decisions[1].entry_price is None
    assert vsa_decisions[1].entry_stop_distance_pct is None


def test_signal_batch_ledgers_missing_next_bar(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(v15, "_strategy_specs", lambda: _fake_specs())
    index = pd.date_range("2024-01-01", periods=500, freq="15min", tz=UTC)

    batch = v15.generate_current_v15p2_signal_batch({"A/USDT": _frame(index)}, policy=_policy())

    assert batch.raw_emission_count == 2
    assert batch.accepted_count == 0
    assert batch.rejected_count == 2
    assert {decision.reason for decision in batch.decisions} == {"missing_next_bar"}
    assert {decision.decision_ts for decision in batch.decisions} == {index[-1].to_pydatetime()}
    assert all(decision.entry_ts is None for decision in batch.decisions)
    assert all(decision.entry_price is None for decision in batch.decisions)
    assert all(decision.entry_stop_distance_pct is None for decision in batch.decisions)


def test_signal_batch_rejects_duplicate_emissions_without_losing_audit_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        v15,
        "_strategy_specs",
        lambda: _fake_specs(grimes_score=0.0, positions=(499, 499)),
    )
    frame = _frame(pd.date_range("2024-01-01", periods=501, freq="15min", tz=UTC))

    batch = v15.generate_current_v15p2_signal_batch({"A/USDT": frame}, policy=_policy())

    assert batch.raw_emission_count == 8
    assert batch.accepted_count == 1
    assert batch.rejected_count == 7
    duplicates = [
        decision
        for decision in batch.decisions
        if decision.reason == "duplicate_signal_fingerprint"
    ]
    assert len(duplicates) == 1
    assert duplicates[0].strategy == "vsa_climax_test"
    assert duplicates[0].decision_ts == batch.intents[0].decision_ts
    assert duplicates[0].entry_ts == batch.intents[0].entry_ts


def test_signal_batch_fails_closed_on_ledger_or_reconciliation_drift(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(v15, "_strategy_specs", lambda: _fake_specs())
    frame = _frame(pd.date_range("2024-01-01", periods=501, freq="15min", tz=UTC))
    batch = v15.generate_current_v15p2_signal_batch({"A/USDT": frame}, policy=_policy())
    accepted = next(decision for decision in batch.decisions if decision.outcome == "accepted")
    missing = next(
        decision for decision in batch.decisions if decision.reason == "missing_next_bar"
    )

    with pytest.raises(ValueError, match="gate order"):
        replace(accepted, outcome="rejected", reason="missing_next_bar")
    with pytest.raises(ValueError, match="otherwise accepted"):
        replace(missing, reason="duplicate_signal_fingerprint")
    with pytest.raises(ValueError, match="reconcile exactly"):
        replace(batch, intents=())


def test_gap_resets_exact_500_bar_warmup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        v15,
        "_strategy_specs",
        lambda: _fake_specs(grimes_score=0.0, positions=None),
    )
    first = pd.date_range("2024-01-01", periods=501, freq="15min", tz=UTC)
    second = pd.date_range(first[-1] + pd.Timedelta(minutes=30), periods=501, freq="15min")
    index = first.append(second)

    intents = v15.generate_current_v15p2_signal_intents({"A/USDT": _frame(index)}, policy=_policy())

    assert [intent.decision_ts for intent in intents] == [
        first[499].to_pydatetime(),
        second[499].to_pydatetime(),
    ]
    assert [intent.entry_ts for intent in intents] == [
        first[500].to_pydatetime(),
        second[500].to_pydatetime(),
    ]


def test_symbol_frames_are_independent_and_never_globally_intersected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        v15,
        "_strategy_specs",
        lambda: _fake_specs(grimes_score=0.0, positions=(499,)),
    )
    frames = {
        "B/USDT": _frame(pd.date_range("2024-03-01", periods=501, freq="15min", tz=UTC)),
        "A/USDT": _frame(pd.date_range("2024-01-01", periods=501, freq="15min", tz=UTC)),
    }
    before = {symbol: frame.copy(deep=True) for symbol, frame in frames.items()}

    intents = v15.generate_current_v15p2_signal_intents(frames, policy=_policy())

    assert {intent.symbol for intent in intents} == {"A/USDT", "B/USDT"}
    for symbol in frames:
        pd.testing.assert_frame_equal(frames[symbol], before[symbol])


def test_every_historical_endpoint_uses_its_own_rolling_last_500(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The synthetic strategy emits at local row 499.  A fresh rolling-500 scan
    # therefore emits at every global endpoint 499..598, including rolling-only
    # signals absent from a single full-prefix invocation.
    monkeypatch.setattr(
        v15,
        "_strategy_specs",
        lambda: _fake_specs(grimes_score=0.0, positions=(499,)),
    )
    frame = _frame(pd.date_range("2024-01-01", periods=600, freq="15min", tz=UTC))

    intents = v15.generate_current_v15p2_signal_intents({"A/USDT": frame}, policy=_policy())

    assert len(intents) == 100
    assert intents[0].decision_ts == pd.Timestamp(frame.iloc[499]["ts"]).to_pydatetime()
    assert intents[-1].decision_ts == pd.Timestamp(frame.iloc[598]["ts"]).to_pydatetime()


@pytest.mark.parametrize("defect", ["timezone", "duplicate", "off_grid", "geometry"])
def test_frame_validation_fails_closed(defect: str) -> None:
    frame = _frame(pd.date_range("2024-01-01", periods=10, freq="15min", tz=UTC))
    if defect == "timezone":
        frame["ts"] = frame["ts"].dt.tz_convert("Europe/Istanbul")
        match = "UTC"
    elif defect == "duplicate":
        frame.loc[2, "ts"] = frame.loc[1, "ts"]
        match = "unique"
    elif defect == "off_grid":
        frame["ts"] += pd.Timedelta(minutes=1)
        match = "quarter-hour"
    else:
        frame.loc[2, "high"] = 1.0
        match = "geometry"
    with pytest.raises(ValueError, match=match):
        v15.generate_current_v15p2_signal_intents({"A/USDT": frame}, policy=_policy())


def _random_actual_strategy_frame(
    n: int = 2_200,
    *,
    seed: int = 20_260_711,
    return_sigma: float = 0.003,
) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    index = pd.date_range("2024-01-01", periods=n, freq="15min", tz=UTC)
    returns = rng.normal(0.0, return_sigma, n)
    close = 100.0 * np.exp(np.cumsum(returns))
    opened = np.r_[close[0], close[:-1]]
    span = np.maximum(close, opened) * rng.uniform(0.001, 0.008, n)
    frame = pd.DataFrame(
        {
            "ts": index,
            "open": opened,
            "high": np.maximum(close, opened) + span,
            "low": np.minimum(close, opened) - span,
            "close": close,
            "volume": rng.lognormal(7.0, 1.0, n),
            "symbol": "TEST/USDT",
            "venue": "binance",
            "timeframe": "15m",
            "vol_z_pre": 0.0,
        }
    )
    return frame


def _signal_signature(signal: Signal) -> tuple[Any, ...]:
    return (
        pd.Timestamp(signal.ts),
        signal.direction,
        signal.pattern_id,
        signal.confluence_score,
        signal.sl_price,
        signal.tp_price,
        signal.suggested_size_atr,
        signal.manifest_hash,
    )


def test_actual_vsa_and_grimes_full_block_match_live_rolling_500_at_signal_cuts() -> None:
    """Lock the measured equivalence that permits the fast block-level pass.

    This uses no snapshot.  Each actual strategy first sees the whole synthetic
    contiguous block.  At three emitted decisions, its result is compared with
    a fresh live-style invocation on exactly the last 500 completed bars.
    """

    frame = _random_actual_strategy_frame()
    index = pd.DatetimeIndex(frame["ts"])
    for spec in v15._strategy_specs():
        full_strategy = spec.strategy_type(spec.manifest_factory())
        full_signals = full_strategy.generate_signals(full_strategy.prepare_features(frame.copy()))
        eligible = [
            signal
            for signal in full_signals
            if 499 <= index.get_loc(pd.Timestamp(signal.ts)) < len(frame) - 1
        ]
        assert eligible, f"synthetic parity fixture emitted no {spec.name} signals"
        for full_signal in eligible[:3]:
            location = int(index.get_loc(pd.Timestamp(full_signal.ts)))
            rolling = frame.iloc[location - 499 : location + 1].reset_index(drop=True)
            live_strategy = spec.strategy_type(spec.manifest_factory())
            live_signals = live_strategy.generate_signals(
                live_strategy.prepare_features(rolling.copy())
            )
            at_decision = [
                signal for signal in live_signals if pd.Timestamp(signal.ts) == index[location]
            ]
            full_at_decision = [
                signal for signal in full_signals if pd.Timestamp(signal.ts) == index[location]
            ]
            assert [_signal_signature(signal) for signal in full_at_decision] == [
                _signal_signature(signal) for signal in at_decision
            ]


def test_actual_optimized_paths_equal_naive_rolling_at_every_endpoint() -> None:
    """Randomized bounded fixture catches both missing and extra endpoint signals."""

    source = _random_actual_strategy_frame(650, seed=1, return_sigma=0.006)
    block = v15._normalize_symbol_frame(
        "TEST/USDT",
        source.drop(columns=["symbol", "venue", "timeframe", "vol_z_pre"]),
    )
    index = pd.DatetimeIndex(block["ts"])

    for spec in v15._strategy_specs():
        started = perf_counter()
        optimized = v15._rolling_exact_signals(spec, block)
        optimized_seconds = perf_counter() - started
        naive: list[Signal] = []
        for location in range(v15.WARMUP_BARS - 1, len(block)):
            window = block.iloc[location - v15.WARMUP_BARS + 1 : location + 1].reset_index(
                drop=True
            )
            naive.extend(v15._signals_at_endpoint(spec, window))

        optimized_eligible = [
            signal
            for signal in optimized
            if v15.WARMUP_BARS - 1 <= index.get_loc(pd.Timestamp(signal.ts)) < len(block)
        ]
        assert sorted(map(_signal_signature, optimized_eligible)) == sorted(
            map(_signal_signature, naive)
        )
        assert optimized_seconds < 5.0

    grimes_spec = v15._strategy_specs()[1]
    candidates = v15._grimes_candidate_locations(grimes_spec, block)
    assert 0 < len(candidates) < len(block) - v15.WARMUP_BARS


def test_vsa_overlay_missing_or_drifted_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from price_action.strategies import manifest_loader

    monkeypatch.setattr(manifest_loader, "load_manifest_full", lambda *_args, **_kwargs: {})
    frame = _frame(pd.date_range("2024-01-01", periods=501, freq="15min", tz=UTC))

    with pytest.raises(ValueError, match="effective manifest hash"):
        v15.generate_current_v15p2_signal_intents({"A/USDT": frame}, policy=_policy())


def test_real_strategy_intents_satisfy_engine_identity_contract() -> None:
    source = _random_actual_strategy_frame()
    intents = v15.generate_current_v15p2_signal_intents({"TEST/USDT": source}, policy=_policy())
    by_strategy = {intent.strategy: intent for intent in intents}
    assert set(by_strategy) == set(v15.STRATEGY_ORDER)

    for intent in by_strategy.values():
        assert intent.confluence_score == 2.0
        result = simulate_v15p2_portfolio(
            {"TEST/USDT": source},
            [intent],
            evaluation_start=intent.entry_ts,
            evaluation_end=intent.entry_ts + timedelta(minutes=15),
        )
        assert len(result.entries) == 1
        assert result.entries[0].signal_manifest_hash == intent.signal_manifest_hash


def test_repaired_scanner_filters_forming_bar_before_exact_tail_500() -> None:
    from scripts.futures_trade_15m import _completed_strategy_window

    index = pd.date_range("2024-01-01", periods=503, freq="15min", tz=UTC)
    frame = _frame(index)
    before = frame.copy(deep=True)
    target = index[501]

    window = _completed_strategy_window(frame, target, window_bars=500)

    assert len(window) == 500
    assert pd.Timestamp(window.iloc[0]["ts"]) == index[1]
    assert pd.Timestamp(window.iloc[-1]["ts"]) == target - pd.Timedelta(minutes=15)
    assert not (pd.DatetimeIndex(window["ts"]) >= target).any()
    pd.testing.assert_frame_equal(frame, before)


def test_signal_records_are_structurally_immutable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(v15, "_strategy_specs", lambda: _fake_specs(grimes_score=0.0))
    frame = _frame(pd.date_range("2024-01-01", periods=501, freq="15min", tz=UTC))
    batch = v15.generate_current_v15p2_signal_batch({"A/USDT": frame}, policy=_policy())
    intent = batch.intents[0]
    decision = batch.decisions[0]

    with pytest.raises(FrozenInstanceError):
        intent.side = "short"  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        decision.reason = "missing_next_bar"  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        batch.intents = ()  # type: ignore[misc]
    assert not hasattr(intent, "__dict__")
    assert not hasattr(decision, "__dict__")
    assert not hasattr(batch, "__dict__")
