"""Focused tests for the fail-closed raw-pool TF robustness gate."""

from __future__ import annotations

import json
import pickle
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pandas as pd
from scripts.tf_robustness_runner import (
    RobustnessThresholds,
    align_pair_to_common_sample,
    evaluate_candidate,
    render_markdown,
    split_chronologically,
    write_reports,
)


def _trade(
    entry_ts: datetime,
    r_value: float,
    *,
    symbol: str,
    strategy: str = "brooks_failed_breakout",
) -> dict:
    return {
        "entry_ts": entry_ts,
        "exit_ts": entry_ts + timedelta(hours=2),
        "R": r_value,
        "symbol": symbol,
        "strategy": strategy,
    }


def _write_pool(path: Path, rows: list[dict]) -> Path:
    with path.open("wb") as handle:
        pickle.dump(rows, handle)
    return path


def _passing_pools(tmp_path: Path) -> tuple[Path, Path]:
    """Create two years of varied, low-correlation monthly OOS evidence."""

    symbols = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "ADA/USDT", "XRP/USDT", "BNB/USDT"]
    candidate: list[dict] = []
    baseline: list[dict] = []

    # Pre-split evidence: distributed across the same six symbols and positive.
    is_start = datetime(2023, 1, 1, tzinfo=UTC)
    for idx in range(120):
        entry = is_start + timedelta(days=idx * 2)
        candidate.append(_trade(entry, 0.8 if idx % 4 else -0.4, symbol=symbols[idx % 6]))
        baseline.append(_trade(entry, 0.5 if idx % 3 else -0.4, symbol=symbols[idx % 6]))

    # OOS: ten trades per month. Candidate monthly totals are always positive
    # but vary independently from the alternating baseline totals.
    for month_index, month in enumerate(
        pd.date_range("2024-01-01", periods=24, freq="MS", tz="UTC")
    ):
        candidate_boost = (month_index % 5) * 0.06
        baseline_boost = 0.18 if month_index % 2 else -0.04
        for trade_index in range(10):
            entry = month.to_pydatetime() + timedelta(days=trade_index * 2)
            candidate_r = (0.9 + candidate_boost) if trade_index < 7 else -0.45
            baseline_r = (0.65 + baseline_boost) if trade_index < 6 else -0.50
            symbol = symbols[(month_index + trade_index) % len(symbols)]
            candidate.append(_trade(entry, candidate_r, symbol=symbol))
            baseline.append(_trade(entry, baseline_r, symbol=symbol))

    return (
        _write_pool(tmp_path / "candidate_1h_pool.pkl", candidate),
        _write_pool(tmp_path / "baseline_15m_pool.pkl", baseline),
    )


def test_evaluate_candidate_passes_all_gates_and_never_deploys(tmp_path: Path) -> None:
    candidate, baseline = _passing_pools(tmp_path)

    result = evaluate_candidate(
        strategy="brooks_failed_breakout",
        candidate_tf="1h",
        candidate_pool=candidate,
        baseline_tf="15m",
        baseline_pool=baseline,
        permutations=4_000,
        seed=7,
    )

    assert result["verdict"] == "DESCRIPTIVE_SCREEN_PASS"
    assert result["independent_oos"] is False
    assert result["deployment_authorized"] is False
    assert result["failed_gates"] == []
    assert result["candidate"]["is"]["n_trades"] == 120
    assert result["candidate"]["oos"]["n_trades"] == 230
    assert result["data_quality"]["oos_comparison_sample"][
        "trailing_partial_month_excluded"
    ] is True
    assert set(result["candidate"]["per_year_oos"]) == {"2024", "2025"}
    assert result["statistical_tests"]["trade_sign_test_diagnostic"]["defined"] is True
    assert result["statistical_tests"]["monthly_block_sign_permutation"]["p_value"] <= 0.05
    assert "Deployment authorized: **NO**" in render_markdown(result)


def test_chronological_split_purges_boundary_crossing_trade() -> None:
    split = pd.Timestamp("2024-01-01", tz="UTC")
    rows = pd.DataFrame(
        [
            {
                "entry_ts": split - pd.Timedelta(days=2),
                "exit_ts": split - pd.Timedelta(hours=1),
                "R": 1.0,
                "symbol": "BTC/USDT",
                "strategy": "s",
            },
            {
                "entry_ts": split - pd.Timedelta(hours=1),
                "exit_ts": split + pd.Timedelta(hours=1),
                "R": 10.0,
                "symbol": "ETH/USDT",
                "strategy": "s",
            },
            {
                "entry_ts": split,
                "exit_ts": split + pd.Timedelta(hours=2),
                "R": -1.0,
                "symbol": "SOL/USDT",
                "strategy": "s",
            },
        ]
    )

    in_sample, out_of_sample, purged = split_chronologically(rows, split)

    assert len(in_sample) == 1
    assert len(out_of_sample) == 1
    assert len(purged) == 1
    assert purged.iloc[0]["R"] == 10.0


def test_missing_required_field_fails_closed(tmp_path: Path) -> None:
    candidate, baseline = _passing_pools(tmp_path)
    with candidate.open("rb") as handle:
        rows = pickle.load(handle)
    rows[0].pop("exit_ts")
    _write_pool(candidate, rows)

    result = evaluate_candidate(
        strategy="brooks_failed_breakout",
        candidate_tf="1h",
        candidate_pool=candidate,
        baseline_tf="15m",
        baseline_pool=baseline,
        permutations=100,
    )

    assert result["verdict"] == "RED"
    assert result["data_quality"]["valid"] is False
    assert result["failed_gates"] == ["data_quality"]
    assert "exit_ts" in result["data_quality"]["errors"][0]
    assert result["deployment_authorized"] is False


def test_duplicate_trade_fails_closed(tmp_path: Path) -> None:
    candidate, baseline = _passing_pools(tmp_path)
    with candidate.open("rb") as handle:
        rows = pickle.load(handle)
    rows.append(dict(rows[0]))
    _write_pool(candidate, rows)

    result = evaluate_candidate(
        strategy="brooks_failed_breakout",
        candidate_tf="1h",
        candidate_pool=candidate,
        baseline_tf="15m",
        baseline_pool=baseline,
        permutations=100,
    )

    assert result["verdict"] == "RED"
    assert result["failed_gates"] == ["data_quality"]
    assert "duplicate" in result["data_quality"]["errors"][0]


def test_invalid_config_returns_red_artifact(tmp_path: Path) -> None:
    candidate, baseline = _passing_pools(tmp_path)

    bad_split = evaluate_candidate(
        strategy="brooks_failed_breakout",
        candidate_tf="1h",
        candidate_pool=candidate,
        baseline_tf="15m",
        baseline_pool=baseline,
        split_date="not-a-date",
    )
    bad_permutations = evaluate_candidate(
        strategy="brooks_failed_breakout",
        candidate_tf="1h",
        candidate_pool=candidate,
        baseline_tf="15m",
        baseline_pool=baseline,
        permutations=0,
    )

    assert bad_split["verdict"] == "RED"
    assert "invalid split timestamp" in bad_split["data_quality"]["errors"][0]
    assert bad_permutations["verdict"] == "RED"
    assert "permutations" in bad_permutations["data_quality"]["errors"][0]


def test_pool_filename_timeframe_mismatch_fails_closed(tmp_path: Path) -> None:
    candidate, baseline = _passing_pools(tmp_path)

    result = evaluate_candidate(
        strategy="brooks_failed_breakout",
        candidate_tf="4h",
        candidate_pool=candidate,
        baseline_tf="15m",
        baseline_pool=baseline,
        permutations=100,
    )

    assert result["verdict"] == "RED"
    assert "timeframe mismatch" in result["data_quality"]["errors"][0]


def test_concentrated_candidate_is_red(tmp_path: Path) -> None:
    candidate, baseline = _passing_pools(tmp_path)
    with candidate.open("rb") as handle:
        rows = pickle.load(handle)
    for row in rows:
        if row["entry_ts"] >= datetime(2024, 1, 1, tzinfo=UTC):
            row["symbol"] = "BTC/USDT"
    _write_pool(candidate, rows)

    result = evaluate_candidate(
        strategy="brooks_failed_breakout",
        candidate_tf="1h",
        candidate_pool=candidate,
        baseline_tf="15m",
        baseline_pool=baseline,
        permutations=1_000,
        seed=5,
    )

    assert result["verdict"] == "RED"
    assert "candidate_oos_symbol_count" in result["failed_gates"]
    assert "top_symbol_trade_share" in result["failed_gates"]
    assert "symbol_out_oos_minimum" in result["failed_gates"]


def test_reports_write_strict_json_and_markdown(tmp_path: Path) -> None:
    candidate, baseline = _passing_pools(tmp_path)
    result = evaluate_candidate(
        strategy="brooks_failed_breakout",
        candidate_tf="1h",
        candidate_pool=candidate,
        baseline_tf="15m",
        baseline_pool=baseline,
        thresholds=RobustnessThresholds(min_correlation_periods=6),
        permutations=500,
        seed=11,
    )
    json_path = tmp_path / "report.json"
    markdown_path = tmp_path / "report.md"

    write_reports(result, json_path, markdown_path)

    parsed = json.loads(json_path.read_text(encoding="utf-8"))
    assert parsed["verdict"] in {"DESCRIPTIVE_SCREEN_PASS", "RED"}
    assert parsed["deployment_authorized"] is False
    assert markdown_path.read_text(encoding="utf-8").startswith("# TF Robustness")


def test_candidate_must_outperform_baseline_mean_r(tmp_path: Path) -> None:
    candidate, baseline = _passing_pools(tmp_path)
    with candidate.open("rb") as handle:
        rows = pickle.load(handle)
    for row in rows:
        if row["entry_ts"] >= datetime(2024, 1, 1, tzinfo=UTC):
            row["R"] *= 0.10
    _write_pool(candidate, rows)

    result = evaluate_candidate(
        strategy="brooks_failed_breakout",
        candidate_tf="1h",
        candidate_pool=candidate,
        baseline_tf="15m",
        baseline_pool=baseline,
        permutations=1_000,
        seed=19,
    )

    assert result["verdict"] == "RED"
    assert "candidate_vs_baseline_oos_mean_R_gain" in result["failed_gates"]
    assert result["candidate_vs_baseline"]["oos_mean_R_gain_pct"] < 0


def test_pair_alignment_uses_common_symbols_and_window() -> None:
    candidate = pd.DataFrame(
        [
            {
                "entry_ts": pd.Timestamp("2023-12-01", tz="UTC"),
                "exit_ts": pd.Timestamp("2023-12-02", tz="UTC"),
                "R": 1.0,
                "symbol": "SOL/USDT",
                "strategy": "s",
            },
            {
                "entry_ts": pd.Timestamp("2024-01-02", tz="UTC"),
                "exit_ts": pd.Timestamp("2024-01-03", tz="UTC"),
                "R": 1.0,
                "symbol": "BTC/USDT",
                "strategy": "s",
            },
            {
                "entry_ts": pd.Timestamp("2024-02-01", tz="UTC"),
                "exit_ts": pd.Timestamp("2024-02-02", tz="UTC"),
                "R": 1.0,
                "symbol": "BTC/USDT",
                "strategy": "s",
            },
        ]
    )
    baseline = pd.DataFrame(
        [
            {
                "entry_ts": pd.Timestamp("2024-01-01", tz="UTC"),
                "exit_ts": pd.Timestamp("2024-01-02", tz="UTC"),
                "R": 0.5,
                "symbol": "BTC/USDT",
                "strategy": "s",
            },
            {
                "entry_ts": pd.Timestamp("2024-01-15", tz="UTC"),
                "exit_ts": pd.Timestamp("2024-01-16", tz="UTC"),
                "R": 0.5,
                "symbol": "BTC/USDT",
                "strategy": "s",
            },
            {
                "entry_ts": pd.Timestamp("2024-03-01", tz="UTC"),
                "exit_ts": pd.Timestamp("2024-03-02", tz="UTC"),
                "R": 0.5,
                "symbol": "ETH/USDT",
                "strategy": "s",
            },
        ]
    )

    candidate_aligned, baseline_aligned, provenance = align_pair_to_common_sample(
        candidate, baseline, label="OOS"
    )

    assert provenance["common_symbols"] == ["BTC/USDT"]
    assert provenance["entry_start"].startswith("2024-01-02")
    assert provenance["entry_end"].startswith("2024-01-15")
    assert len(candidate_aligned) == 1
    assert len(baseline_aligned) == 1
