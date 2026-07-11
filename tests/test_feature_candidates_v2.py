"""Feature factory v2: descriptive-only evidence, hygiene and no-lookahead."""

from __future__ import annotations

import copy
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
import pytest
import scripts.feature_sweep as sweep

from price_action.lab.feature_candidates import (
    EVIDENCE_CLASS,
    SCHEMA_VERSION,
    algorithm_code_sha256,
    append_candidate_records,
    load_researcher_candidates,
    make_candidate_record,
    market_snapshot_metadata,
    record_integrity_sha256,
    validate_candidate_record,
)


def _ohlcv(*, periods: int = 650, freq: str = "1h", end: datetime | None = None) -> pd.DataFrame:
    rng = np.random.default_rng(20260711)
    end = end or (datetime.now(UTC) - timedelta(hours=1))
    index = pd.date_range(end=end, periods=periods, freq=freq, tz=UTC)
    close = 100.0 * np.exp(np.cumsum(rng.normal(0.0, 0.006, periods)))
    open_ = close * (1.0 + rng.normal(0.0, 0.001, periods))
    spread = np.abs(rng.normal(0.002, 0.0005, periods))
    high = np.maximum(open_, close) * (1.0 + spread)
    low = np.minimum(open_, close) * (1.0 - spread)
    volume = rng.lognormal(8.0, 0.3, periods)
    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": volume},
        index=index,
    )


def _result() -> dict:
    return {
        "symbol": "BTC/USDT",
        "feature": "ret_4bar",
        "feature_family": "momentum",
        "target": "fwd_volnorm_24h",
        "target_normalization": "TRAILING_REALIZED_VOL_AT_DECISION_BAR",
        "oos_scheme": "CHRONOLOGICAL_70_30_CONFIRMATION_NOT_PROMOTION_HOLDOUT",
        "n_is": 1000,
        "n_oos": 400,
        "is_start_ts": "2020-01-01T00:00:00+00:00",
        "is_end_ts": "2023-12-31T00:00:00+00:00",
        "oos_start_ts": "2024-01-01T00:00:00+00:00",
        "oos_end_ts": "2025-12-31T00:00:00+00:00",
        "effective_independence_bars": 24,
        "ic_is": 0.08,
        "p_is": 0.001,
        "ic_oos": 0.05,
        "fdr_pass": True,
        "fdr_alpha": 0.05,
        "fdr_family_size": 9000,
        "fdr_scope": "ALL_SELECTED_TF_SYMBOL_FEATURE_TARGET_PAIRS_IN_RUN",
    }


def _candidate(now: datetime, *, source_max_ts: datetime | None = None) -> dict:
    frame = _ohlcv(periods=32, end=source_max_ts or (now - timedelta(hours=1)))
    source = market_snapshot_metadata(frame, symbol="BTC/USDT", timeframe="1h")
    return make_candidate_record(
        _result(),
        timeframe="1h",
        source=source,
        generated_at=now,
        code_sha256=algorithm_code_sha256(),
    )


def test_v2_schema_is_explicitly_not_promotion_evidence():
    now = datetime.now(UTC)
    record = _candidate(now)

    assert record["schema_version"] == SCHEMA_VERSION
    assert record["evidence_class"] == EVIDENCE_CLASS == "DESCRIPTIVE_DISCOVERY"
    assert record["promotion_eligible"] is False
    assert record["status"] == "ACTIVE"
    assert record["candidate_key"].startswith("fsv2-")
    assert len(record["source"]["market_snapshot_sha256"]) == 64
    assert len(record["algorithm"]["code_sha256"]) == 64
    assert record["algorithm"]["target_normalization"] == (
        "TRAILING_REALIZED_VOL_AT_DECISION_BAR"
    )
    assert record["algorithm"]["oos_scheme"].endswith("NOT_PROMOTION_HOLDOUT")
    assert record["statistics"]["oos_start_ts"] == "2024-01-01T00:00:00+00:00"
    assert validate_candidate_record(
        record,
        now=now,
        expected_algorithm_sha256=algorithm_code_sha256(),
    ) == []


def test_append_is_key_deduplicated(tmp_path: Path):
    now = datetime.now(UTC)
    record = _candidate(now)
    path = tmp_path / "sweep_candidates_v2.jsonl"

    first = append_candidate_records(
        path,
        [record, record],
        expected_algorithm_sha256=algorithm_code_sha256(),
    )
    second = append_candidate_records(
        path,
        [record],
        expected_algorithm_sha256=algorithm_code_sha256(),
    )

    assert (first.appended, first.duplicates) == (1, 1)
    assert (second.appended, second.duplicates) == (0, 1)
    assert len(path.read_text(encoding="utf-8").splitlines()) == 1


def test_legacy_rows_are_counted_but_never_active(tmp_path: Path):
    legacy_path = tmp_path / "sweep_candidates.jsonl"
    legacy_path.write_text(
        "".join(
            json.dumps(
                {
                    "symbol": "BTC/USDT",
                    "feature": f"legacy_{index}",
                    "target": "fwd_24h",
                    "status": "CANDIDATE",
                }
            )
            + "\n"
            for index in range(195)
        ),
        encoding="utf-8",
    )
    v2_path = tmp_path / "sweep_candidates_v2.jsonl"
    now = datetime.now(UTC)
    append_candidate_records(
        v2_path,
        [_candidate(now)],
        expected_algorithm_sha256=algorithm_code_sha256(),
    )

    loaded = load_researcher_candidates(path=v2_path, legacy_path=legacy_path, now=now)
    legacy_as_primary = load_researcher_candidates(
        path=legacy_path,
        legacy_path=None,
        now=now,
    )

    assert len(loaded.candidates) == 1
    assert loaded.summary["legacy_quarantined_count"] == 195
    assert loaded.summary["reasons"]["legacy_file_quarantined"] == 195
    assert legacy_as_primary.candidates == ()
    assert legacy_as_primary.summary["active_count"] == 0
    assert legacy_as_primary.summary["reasons"]["legacy_or_unknown_schema"] == 195


def test_loader_rejects_stale_source_stale_code_and_tampering(tmp_path: Path):
    now = datetime.now(UTC)
    valid = _candidate(now)
    stale_source = _candidate(now, source_max_ts=now - timedelta(days=10))
    stale_code = copy.deepcopy(valid)
    stale_code["algorithm"]["code_sha256"] = "a" * 64
    stale_code["candidate_key"] = sweep_candidate_key(stale_code)
    stale_code["integrity_sha256"] = record_integrity_sha256(stale_code)
    tampered = copy.deepcopy(valid)
    tampered["source"]["market_snapshot_sha256"] = "b" * 64

    path = tmp_path / "candidates.jsonl"
    path.write_text(
        "\n".join(json.dumps(record) for record in (valid, stale_source, stale_code, tampered))
        + "\n",
        encoding="utf-8",
    )
    loaded = load_researcher_candidates(path=path, legacy_path=None, now=now)

    assert len(loaded.candidates) == 1
    assert loaded.summary["reasons"]["stale_source_snapshot"] == 1
    assert loaded.summary["reasons"]["stale_algorithm_code"] == 1
    assert loaded.summary["reasons"]["candidate_key_mismatch"] == 1
    assert loaded.summary["reasons"]["record_integrity_mismatch"] == 1


def test_loader_can_pin_a_trusted_market_snapshot(tmp_path: Path):
    now = datetime.now(UTC)
    record = _candidate(now)
    path = tmp_path / "candidates.jsonl"
    path.write_text(json.dumps(record) + "\n", encoding="utf-8")

    accepted = load_researcher_candidates(
        path=path,
        legacy_path=None,
        now=now,
        trusted_source_hashes={
            ("BTC/USDT", "1h"): record["source"]["market_snapshot_sha256"]
        },
    )
    rejected = load_researcher_candidates(
        path=path,
        legacy_path=None,
        now=now,
        trusted_source_hashes={("BTC/USDT", "1h"): "c" * 64},
    )

    assert len(accepted.candidates) == 1
    assert rejected.candidates == ()
    assert rejected.summary["reasons"]["untrusted_source_snapshot"] == 1


def sweep_candidate_key(record: dict) -> str:
    """Local indirection keeps the test mutation readable."""

    from price_action.lab.feature_candidates import candidate_key

    return candidate_key(record)


@pytest.mark.parametrize("timeframe,freq", [("1h", "1h"), ("4h", "4h"), ("1d", "D")])
def test_registry_has_more_than_fifty_features_for_each_timeframe(timeframe: str, freq: str):
    frame = _ohlcv(freq=freq)
    features = sweep.build_features(frame, None, None, timeframe=timeframe)

    assert features.index.equals(frame.index)
    assert len(features.columns) >= 50
    assert features.columns.is_unique


@pytest.mark.parametrize("timeframe,freq", [("1h", "1h"), ("4h", "4h"), ("1d", "D")])
def test_feature_registry_is_prefix_invariant(timeframe: str, freq: str):
    frame = _ohlcv(periods=700, freq=freq)
    prefix_len = 575

    full = sweep.build_features(frame, None, None, timeframe=timeframe).iloc[:prefix_len]
    prefix = sweep.build_features(
        frame.iloc[:prefix_len],
        None,
        None,
        timeframe=timeframe,
    )

    pd.testing.assert_frame_equal(full, prefix, check_exact=True)


def test_asof_funding_and_btc_features_do_not_use_future_events():
    frame = _ohlcv(periods=900, freq="1h")
    prefix_len = 700
    funding_index = frame.index[::4]
    funding = pd.Series(
        np.linspace(-0.0002, 0.0003, len(funding_index)),
        index=funding_index,
    )
    btc_close = frame["close"] * np.linspace(0.98, 1.02, len(frame))

    full = sweep.build_features(
        frame,
        funding,
        btc_close,
        timeframe="1h",
    ).iloc[:prefix_len]
    prefix = sweep.build_features(
        frame.iloc[:prefix_len],
        funding,
        btc_close,
        timeframe="1h",
    )

    pd.testing.assert_frame_equal(full, prefix, check_exact=True)


def test_timeframe_targets_and_deoverlap_bars():
    frame_1h = _ohlcv(freq="1h")
    frame_4h = _ohlcv(freq="4h")
    frame_1d = _ohlcv(freq="D")

    assert list(sweep.build_targets(frame_1h, timeframe="1h")) == [
        "fwd_volnorm_4h",
        "fwd_volnorm_24h",
        "fwd_volnorm_72h",
    ]
    assert list(sweep.build_targets(frame_4h, timeframe="4h")) == [
        "fwd_volnorm_12h",
        "fwd_volnorm_24h",
        "fwd_volnorm_72h",
    ]
    assert list(sweep.build_targets(frame_1d, timeframe="1d")) == [
        "fwd_volnorm_1d",
        "fwd_volnorm_7d",
        "fwd_volnorm_30d",
    ]
    assert sweep._target_horizon_bars("fwd_24h", timeframe="1h") == 24
    assert sweep._target_horizon_bars("fwd_24h", timeframe="4h") == 6
    assert sweep._target_horizon_bars("fwd_7d", timeframe="1d") == 7
    assert sweep._target_horizon_bars("fwd_volnorm_7d", timeframe="1d") == 7


def test_target_uses_only_trailing_volatility_at_decision_bar():
    frame = _ohlcv(periods=700, freq="1h")
    targets = sweep.build_targets(frame, timeframe="1h")
    decision = 400
    bars = 4
    returns = frame["close"].pct_change(fill_method=None)
    scale = returns.rolling(20, min_periods=20).std().iloc[decision] * np.sqrt(bars)
    forward = frame["close"].iloc[decision + bars] / frame["close"].iloc[decision] - 1.0

    assert targets["fwd_volnorm_4h"].iloc[decision] == pytest.approx(forward / scale)
    changed = frame.copy()
    changed.iloc[decision + bars + 10 :, changed.columns.get_loc("close")] *= 3.0
    changed_target = sweep.build_targets(changed, timeframe="1h")
    assert changed_target["fwd_volnorm_4h"].iloc[decision] == pytest.approx(
        targets["fwd_volnorm_4h"].iloc[decision]
    )


def test_sweep_result_carries_fdr_and_chronological_oos_provenance(monkeypatch):
    frame = _ohlcv(periods=900, freq="1h")
    features = sweep.build_features(frame, None, None, timeframe="1h")[["ret_4bar"]]
    targets = sweep.build_targets(frame, timeframe="1h")[["fwd_volnorm_4h"]]
    results = sweep.sweep_symbol("BTC/USDT", features, targets, timeframe="1h")
    monkeypatch.setattr(sweep, "FDR_ALPHA", 0.05)
    adjusted = sweep.bh_fdr(results)

    assert adjusted
    row = adjusted[0]
    assert row["feature_family"] == "momentum"
    assert row["target_normalization"] == "TRAILING_REALIZED_VOL_AT_DECISION_BAR"
    assert row["oos_scheme"].endswith("NOT_PROMOTION_HOLDOUT")
    assert pd.Timestamp(row["is_end_ts"]) < pd.Timestamp(row["oos_start_ts"])
    assert row["fdr_method"] == "BENJAMINI_YEKUTIELI"
    assert row["fdr_family_size"] == 1


def test_cross_sectional_features_are_same_close_and_prefix_invariant():
    btc = _ohlcv(periods=700, freq="1h")
    eth = btc.copy()
    eth["close"] *= np.linspace(0.8, 1.2, len(eth))
    eth["open"] = eth["close"] * 0.999
    eth["high"] = eth[["open", "close"]].max(axis=1) * 1.002
    eth["low"] = eth[["open", "close"]].min(axis=1) * 0.998
    full = sweep.build_cross_sectional_features({"BTC/USDT": btc, "ETH/USDT": eth})
    prefix = sweep.build_cross_sectional_features(
        {"BTC/USDT": btc.iloc[:600], "ETH/USDT": eth.iloc[:600]}
    )

    pd.testing.assert_frame_equal(full["BTC/USDT"].iloc[:600], prefix["BTC/USDT"])
    assert len(full["BTC/USDT"].columns) == 8


def test_resampler_keeps_only_complete_higher_timeframe_bars():
    index = pd.date_range("2026-01-01", periods=200, freq="15min", tz=UTC)
    raw = pd.DataFrame(
        {
            "ts": index,
            "venue": "binance",
            "symbol": "BTC/USDT",
            "timeframe": "15m",
            "open": np.arange(200, dtype=float) + 100.0,
            "high": np.arange(200, dtype=float) + 101.0,
            "low": np.arange(200, dtype=float) + 99.0,
            "close": np.arange(200, dtype=float) + 100.5,
            "volume": np.ones(200),
        }
    )
    connection = duckdb.connect(":memory:")
    connection.register("raw", raw)
    connection.execute("CREATE TABLE ohlcv AS SELECT * FROM raw")
    try:
        assert len(sweep._load_ohlcv(connection, "BTC/USDT", "1h")) == 50
        assert len(sweep._load_ohlcv(connection, "BTC/USDT", "4h")) == 12
        assert len(sweep._load_ohlcv(connection, "BTC/USDT", "1d")) == 2
    finally:
        connection.close()


def test_market_snapshot_hash_is_content_sensitive():
    frame = _ohlcv(periods=32)
    first = market_snapshot_metadata(frame, symbol="BTC/USDT", timeframe="1h")
    changed = frame.copy()
    changed.iloc[-1, changed.columns.get_loc("close")] += 0.01
    second = market_snapshot_metadata(changed, symbol="BTC/USDT", timeframe="1h")

    assert first["max_ts"] == second["max_ts"]
    assert first["market_snapshot_sha256"] != second["market_snapshot_sha256"]
