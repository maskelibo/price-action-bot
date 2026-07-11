from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import numpy as np
import pandas as pd

from price_action.lab.crypto_15m_v15p2_signals import (
    EXPECTED_CONFIG_SHA256,
    EXPECTED_SIGNAL_MANIFEST_HASHES,
    FAIR_BASELINE_CANDIDATE_ID,
    SignalDecisionLedger,
    SignalGenerationResult,
    V15P2SignalIntent,
)
from price_action.lab.crypto_15m_v18_signals import (
    V18_CELL_SPEC_BY_ID,
    adapt_v15p2_signal_batch_to_v18_cells,
    evaluate_v18_cell,
    generate_v18_candidate_batches,
)


def _intent(
    *,
    decision_ts: pd.Timestamp,
    strategy: str = "vsa_climax_test",
    side: str = "long",
    symbol: str = "ETH/USDT",
) -> V15P2SignalIntent:
    rank = 0 if strategy == "vsa_climax_test" else 1
    decision_close = 100.0
    stop = 97.0 if side == "long" else 103.0
    entry = 101.0 if side == "long" else 99.0
    return V15P2SignalIntent(
        candidate_id=FAIR_BASELINE_CANDIDATE_ID,
        decision_ts=decision_ts.to_pydatetime(),
        entry_ts=(decision_ts + pd.Timedelta(minutes=15)).to_pydatetime(),
        symbol=symbol,
        side=side,  # type: ignore[arg-type]
        strategy=strategy,
        strategy_rank=rank,
        pattern_id=f"{strategy}_{side}",
        confluence_score=0.75,
        decision_close=decision_close,
        entry_reference_price=decision_close,
        entry_price=entry,
        stop_price=stop,
        take_profit_price=106.0 if side == "long" else 94.0,
        decision_stop_distance_pct=abs(decision_close - stop) / decision_close,
        entry_stop_distance_pct=abs(entry - stop) / entry,
        suggested_size_atr=1.0,
        signal_manifest_hash=EXPECTED_SIGNAL_MANIFEST_HASHES[strategy],
        config_sha256=EXPECTED_CONFIG_SHA256,
    )


def _decision(intent: V15P2SignalIntent, index: int) -> SignalDecisionLedger:
    return SignalDecisionLedger(
        emission_index=index,
        candidate_id=intent.candidate_id,
        decision_ts=intent.decision_ts,
        entry_ts=intent.entry_ts,
        symbol=intent.symbol,
        side=intent.side,
        strategy=intent.strategy,
        strategy_rank=intent.strategy_rank,
        pattern_id=intent.pattern_id,
        confluence_score=intent.confluence_score,
        decision_close=intent.decision_close,
        entry_reference_price=intent.entry_reference_price,
        entry_price=intent.entry_price,
        stop_price=intent.stop_price,
        take_profit_price=intent.take_profit_price,
        decision_stop_distance_pct=intent.decision_stop_distance_pct,
        entry_stop_distance_pct=intent.entry_stop_distance_pct,
        suggested_size_atr=intent.suggested_size_atr,
        signal_manifest_hash=intent.signal_manifest_hash,
        config_sha256=intent.config_sha256,
        outcome="accepted",
        reason="accepted",
    )


def _batch(*intents: V15P2SignalIntent) -> SignalGenerationResult:
    return SignalGenerationResult(
        candidate_id=FAIR_BASELINE_CANDIDATE_ID,
        config_sha256=EXPECTED_CONFIG_SHA256,
        decisions=tuple(_decision(intent, index) for index, intent in enumerate(intents)),
        intents=intents,
    )


def _daily_frame(
    first_day: str,
    closes: list[float],
    *,
    forming_day_close: float | None = None,
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for offset, close in enumerate(closes):
        day = pd.Timestamp(first_day) + pd.Timedelta(days=offset)
        for ts in pd.date_range(day, periods=96, freq="15min"):
            rows.append({"ts": ts, "close": close})
    if forming_day_close is not None:
        day = pd.Timestamp(first_day) + pd.Timedelta(days=len(closes))
        for ts in pd.date_range(day, periods=96, freq="15min"):
            rows.append({"ts": ts, "close": forming_day_close})
    return pd.DataFrame(rows)


def _row(result: object, index: int = 0):
    return result.decisions[index]  # type: ignore[attr-defined,no-any-return]


def test_exact_sma50_uses_only_d_minus_1_and_ignores_forming_day() -> None:
    decision_ts = pd.Timestamp("2024-03-01T12:00:00Z")
    closes = [100.0 + index for index in range(50)]
    intent = _intent(decision_ts=decision_ts)
    batch = _batch(intent)
    first = _daily_frame("2024-01-11T00:00:00Z", closes, forming_day_close=1.0)
    second = _daily_frame("2024-01-11T00:00:00Z", closes, forming_day_close=1_000_000.0)

    left = evaluate_v18_cell(
        batch,
        {"ETH/USDT": first},
        cell="C3_DUAL_HTF50",
    )
    right = evaluate_v18_cell(
        batch,
        {"ETH/USDT": second},
        cell="C3_DUAL_HTF50",
    )

    assert left.accepted_count == right.accepted_count == 1
    assert _row(left).reason == _row(right).reason == "accepted_htf_long"
    assert _row(left).latest_completed_daily_close == 149.0
    assert _row(left).sma50 == _row(right).sma50 == sum(closes) / 50
    assert _row(left).required_window_start_day == datetime(2024, 1, 11, tzinfo=UTC)
    assert _row(left).required_window_end_day == datetime(2024, 2, 29, tzinfo=UTC)


def test_missing_day_rejects_without_reaching_back_to_an_older_complete_day() -> None:
    decision_ts = pd.Timestamp("2024-03-01T12:00:00Z")
    # Jan 10 is deliberately available, but Jan 25 inside the exact required
    # Jan 11-Feb 29 window is absent.  It may not be used as a replacement.
    frame = _daily_frame("2024-01-10T00:00:00Z", [100.0 + index for index in range(51)])
    frame = frame.loc[frame["ts"].dt.floor("D") != pd.Timestamp("2024-01-25T00:00:00Z")]

    result = evaluate_v18_cell(
        _batch(_intent(decision_ts=decision_ts)),
        {"ETH/USDT": frame},
        cell="C3_DUAL_HTF50",
    )

    assert result.accepted_count == 0
    assert _row(result).reason == "missing_required_utc_day"
    assert _row(result).failed_day == datetime(2024, 1, 25, tzinfo=UTC)
    assert _row(result).complete_day_count == 49


def test_incomplete_exact_grid_day_is_a_distinct_fail_closed_rejection() -> None:
    decision_ts = pd.Timestamp("2024-03-01T12:00:00Z")
    frame = _daily_frame("2024-01-11T00:00:00Z", [100.0 + index for index in range(50)])
    missing_bar = pd.Timestamp("2024-02-10T08:15:00Z")
    frame = frame.loc[frame["ts"] != missing_bar]

    result = evaluate_v18_cell(
        _batch(_intent(decision_ts=decision_ts)),
        {"ETH/USDT": frame},
        cell="C3_DUAL_HTF50",
    )

    assert _row(result).reason == "incomplete_required_utc_day"
    assert _row(result).failed_day == datetime(2024, 2, 10, tzinfo=UTC)
    assert _row(result).complete_day_count == 49


def test_nonfinite_daily_close_rejects_and_is_never_imputed() -> None:
    decision_ts = pd.Timestamp("2024-03-01T12:00:00Z")
    closes = [100.0 + index for index in range(50)]
    frame = _daily_frame("2024-01-11T00:00:00Z", closes)
    frame.loc[frame["ts"] == pd.Timestamp("2024-02-20T23:45:00Z"), "close"] = np.nan

    result = evaluate_v18_cell(
        _batch(_intent(decision_ts=decision_ts)),
        {"ETH/USDT": frame},
        cell="C4_VSA_HTF50",
    )

    assert _row(result).reason == "nonfinite_or_nonpositive_daily_close"
    assert _row(result).failed_day == datetime(2024, 2, 20, tzinfo=UTC)
    assert _row(result).sma50 is None


def test_strict_equality_rejects_both_long_and_short() -> None:
    decision_ts = pd.Timestamp("2024-03-01T12:00:00Z")
    frame = _daily_frame("2024-01-11T00:00:00Z", [100.0] * 50)
    result = evaluate_v18_cell(
        _batch(
            _intent(decision_ts=decision_ts, side="long"),
            _intent(decision_ts=decision_ts, side="short"),
        ),
        {"ETH/USDT": frame},
        cell="C3_DUAL_HTF50",
    )

    assert result.accepted_count == 0
    assert [row.reason for row in result.decisions] == ["sma50_equality"] * 2
    assert all(row.latest_completed_daily_close == row.sma50 == 100.0 for row in result.decisions)


def test_strict_direction_rules_accept_only_the_matching_side() -> None:
    decision_ts = pd.Timestamp("2024-03-01T12:00:00Z")
    rising = _daily_frame("2024-01-11T00:00:00Z", [100.0 + index for index in range(50)])
    falling = _daily_frame("2024-01-11T00:00:00Z", [200.0 - index for index in range(50)])
    batch = _batch(
        _intent(decision_ts=decision_ts, side="long"),
        _intent(decision_ts=decision_ts, side="short"),
    )

    rising_result = evaluate_v18_cell(
        batch,
        {"ETH/USDT": rising},
        cell="C3_DUAL_HTF50",
    )
    falling_result = evaluate_v18_cell(
        batch,
        {"ETH/USDT": falling},
        cell="C3_DUAL_HTF50",
    )

    assert [row.reason for row in rising_result.decisions] == [
        "accepted_htf_long",
        "short_not_below_sma50",
    ]
    assert [row.reason for row in falling_result.decisions] == [
        "long_not_above_sma50",
        "accepted_htf_short",
    ]


def test_four_cell_strategy_subsets_and_no_htf_behavior_are_exact() -> None:
    decision_ts = pd.Timestamp("2024-03-01T12:00:00Z")
    vsa = _intent(decision_ts=decision_ts, strategy="vsa_climax_test")
    grimes = _intent(decision_ts=decision_ts, strategy="grimes_abc_pullback")
    result = adapt_v15p2_signal_batch_to_v18_cells(_batch(vsa, grimes), frames=None)

    assert tuple(result) == tuple(V18_CELL_SPEC_BY_ID)
    assert [row.reason for row in result["C1_VSA_ONLY"].decisions] == [
        "accepted_no_htf",
        "strategy_disabled",
    ]
    assert result["C1_VSA_ONLY"].intents == (vsa,)
    assert [row.reason for row in result["C2_GRIMES_ONLY"].decisions] == [
        "strategy_disabled",
        "accepted_no_htf",
    ]
    assert result["C2_GRIMES_ONLY"].intents == (grimes,)
    assert [row.reason for row in result["C3_DUAL_HTF50"].decisions] == [
        "missing_symbol_frame",
        "missing_symbol_frame",
    ]
    assert [row.reason for row in result["C4_VSA_HTF50"].decisions] == [
        "missing_symbol_frame",
        "strategy_disabled",
    ]
    assert all(cell.source_intent_count == len(cell.decisions) == 2 for cell in result.values())

    runner_result = generate_v18_candidate_batches(None, baseline_batch=_batch(vsa, grimes))
    assert tuple(runner_result) == tuple(result)
    assert [cell.candidate_id for cell in runner_result.values()] == list(runner_result)


@dataclass(frozen=True)
class _LooseIntent:
    candidate_id: str
    config_sha256: str
    decision_ts: datetime
    entry_ts: datetime
    symbol: str
    side: str
    strategy: str


def test_invalid_side_is_a_ledgered_rejection_not_an_exception() -> None:
    decision_ts = datetime(2024, 3, 1, 12, tzinfo=UTC)
    loose = _LooseIntent(
        candidate_id=FAIR_BASELINE_CANDIDATE_ID,
        config_sha256=EXPECTED_CONFIG_SHA256,
        decision_ts=decision_ts,
        entry_ts=decision_ts + timedelta(minutes=15),
        symbol="ETH/USDT",
        side="flat",
        strategy="vsa_climax_test",
    )
    batch = SimpleNamespace(
        candidate_id=FAIR_BASELINE_CANDIDATE_ID,
        config_sha256=EXPECTED_CONFIG_SHA256,
        decisions=(),
        intents=(loose,),
    )

    result = evaluate_v18_cell(batch, None, cell="C1_VSA_ONLY")

    assert result.intents == ()
    assert result.rejected_count == 1
    assert _row(result).reason == "invalid_side"


def test_malformed_symbol_frame_is_fail_closed_but_no_htf_cell_does_not_read_it() -> None:
    decision_ts = pd.Timestamp("2024-03-01T12:00:00Z")
    batch = _batch(_intent(decision_ts=decision_ts))
    malformed = pd.DataFrame({"ts": [pd.Timestamp("2024-01-11")], "close": [100.0]})

    no_htf = evaluate_v18_cell(batch, {"ETH/USDT": malformed}, cell="C1_VSA_ONLY")
    htf = evaluate_v18_cell(batch, {"ETH/USDT": malformed}, cell="C3_DUAL_HTF50")

    assert _row(no_htf).reason == "accepted_no_htf"
    assert _row(htf).reason == "invalid_symbol_frame"


def test_source_identity_drift_is_rejected_before_any_cell_decision() -> None:
    decision_ts = pd.Timestamp("2024-03-01T12:00:00Z")
    valid = _intent(decision_ts=decision_ts)
    batch = SimpleNamespace(
        candidate_id="foreign",
        config_sha256=EXPECTED_CONFIG_SHA256,
        decisions=(),
        intents=(valid,),
    )

    try:
        evaluate_v18_cell(batch, None, cell="C1_VSA_ONLY")
    except ValueError as exc:
        assert "frozen V15.2 baseline" in str(exc)
    else:
        raise AssertionError("foreign batch identity must fail closed")
