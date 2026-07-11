from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
import pytest
import yaml

from price_action.lab import crypto_15m_v15p2_program as program

ROOT = Path(__file__).resolve().parents[1]
PREREG = ROOT / program.CANONICAL_PREREG_RELATIVE


def _config() -> dict[str, Any]:
    return yaml.safe_load(PREREG.read_bytes())


def _write(path: Path, value: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(value, sort_keys=False), encoding="utf-8")
    return path


@dataclass(frozen=True)
class _Intent:
    candidate_id: str
    decision_ts: datetime
    entry_ts: datetime
    symbol: str
    side: str = "long"
    strategy: str = "vsa_climax_test"
    strategy_rank: int = 0
    pattern_id: str = "synthetic"
    confluence_score: float = 0.50
    decision_close: float = 100.0
    entry_reference_price: float = 100.0
    entry_price: float = 100.0
    stop_price: float = 95.0
    take_profit_price: float = 110.0
    decision_stop_distance_pct: float = 0.05
    entry_stop_distance_pct: float = 0.05
    suggested_size_atr: float = 1.0
    signal_manifest_hash: str = "manifest"
    config_sha256: str = program.EXPECTED_CONFIG_SHA256
    audit_value: float = 1.0


@dataclass(frozen=True)
class _Decision:
    emission_index: int
    candidate_id: str
    decision_ts: datetime
    entry_ts: datetime
    symbol: str
    outcome: str
    reason: str
    side: str = "long"
    strategy: str = "vsa_climax_test"
    strategy_rank: int = 0
    pattern_id: str = "synthetic"
    confluence_score: float = 0.50
    decision_close: float = 100.0
    entry_reference_price: float = 100.0
    entry_price: float = 100.0
    stop_price: float = 95.0
    take_profit_price: float = 110.0
    decision_stop_distance_pct: float = 0.05
    entry_stop_distance_pct: float = 0.05
    suggested_size_atr: float = 1.0
    signal_manifest_hash: str = "manifest"
    config_sha256: str = program.EXPECTED_CONFIG_SHA256


@dataclass(frozen=True)
class _SignalBatch:
    candidate_id: str
    config_sha256: str
    decisions: tuple[_Decision, ...]
    intents: tuple[_Intent, ...]


@dataclass(frozen=True)
class _Curve:
    ts: datetime
    nav: float = 10_000.0


@dataclass(frozen=True)
class _Entry:
    entry_ts: datetime
    symbol: str
    entry_price: float


@dataclass(frozen=True)
class _TimedLedger:
    ts: datetime
    symbol: str
    value: float


@dataclass(frozen=True)
class _SyntheticResult:
    scenario: str
    scenario_identity: str
    scenario_is_canonical: bool
    scenario_config: program.V15P2CostScenario
    policy: program.V15P2PortfolioPolicy
    evaluation_start: datetime
    evaluation_end: datetime
    initial_wallet: float
    final_wallet: float
    final_nav: float
    max_drawdown: float
    total_execution_cost_charged: float
    total_funding_cashflow: float
    accrued_terminal_exit_cost: float
    entries: tuple[_Entry, ...]
    exit_fills: tuple[_TimedLedger, ...]
    funding_events: tuple[_TimedLedger, ...]
    journal_rows: tuple[_TimedLedger, ...]
    stop_transitions: tuple[_TimedLedger, ...]
    breaker_transitions: tuple[_TimedLedger, ...]
    risk_decisions: tuple[Any, ...]
    rejections: tuple[Any, ...]
    closed_episodes: tuple[Any, ...]
    curve: tuple[_Curve, ...]
    terminal_positions: tuple[Any, ...]


def _synthetic_frame() -> pd.DataFrame:
    history = pd.date_range(
        program.HISTORY_START,
        program.EVALUATION_START,
        freq="15min",
        inclusive="left",
    )
    # Only two evaluation bars are needed because the engine is mocked.  Their
    # labels prove the runner preserves the exact half-open boundaries.
    index = history.append(
        pd.DatetimeIndex(
            [program.EVALUATION_START, program.EVALUATION_END - pd.Timedelta(minutes=15)]
        )
    )
    return pd.DataFrame(
        {
            "ts": index,
            "open": 100.0,
            "high": 101.0,
            "low": 99.0,
            "close": 100.0,
            "volume": 1.0,
        }
    )


def _install_full_run_mocks(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    source_mutates: bool = False,
    snapshot_mutates: bool = False,
    lineage_mutates: bool = False,
) -> dict[str, list[Any]]:
    trace: dict[str, list[Any]] = {
        "source": [],
        "runtime": [],
        "verify": [],
        "load": [],
        "signal": [],
        "engine": [],
    }
    source_calls = 0

    def fake_source(_prereg: dict[str, Any], _root: Path) -> dict[str, Any]:
        nonlocal source_calls
        source_calls += 1
        trace["source"].append(source_calls)
        digest = "b" * 64 if not source_mutates or source_calls == 1 else "c" * 64
        return {
            "git_commit": "a" * 40,
            "research_source_clean": True,
            "research_source_status": [],
            "missing_source_files": [],
            "file_sha256": {"synthetic.py": digest},
            "reference_source_checks": {"config": {"matches": True, "hash": digest}},
            "exact_reference_source_hashes_match": True,
        }

    runtime_calls = 0

    def fake_runtime(_root: Path) -> dict[str, str]:
        nonlocal runtime_calls
        runtime_calls += 1
        trace["runtime"].append(runtime_calls)
        return {"python": "test", "requirements_lock_sha256": "d" * 64}

    def fake_verify(
        name: str, spec: dict[str, Any], *, repo_root: Path
    ) -> program.SnapshotVerification:
        del repo_root
        trace["verify"].append((name, len(trace["source"])))
        snapshot_calls = sum(
            item_name in {"market", "funding"} for item_name, _source_call in trace["verify"]
        )
        postflight = snapshot_calls > 2
        digest = str(spec["sha256"])
        if snapshot_mutates and postflight and name == "funding":
            digest = "f" * 64
        lineage_calls = sum(item_name == name for item_name, _source_call in trace["verify"])
        if lineage_mutates and name == "v3_build_evidence" and lineage_calls > 1:
            digest = "e" * 64
        return program.SnapshotVerification(
            name=name,
            configured_path=str(spec["path"]),
            resolved_path=str(tmp_path / f"{name}.duckdb"),
            bytes=int(spec["bytes"]),
            sha256=digest,
        )

    frame = _synthetic_frame()

    def fake_market(
        _path: Path,
        _spec: dict[str, Any],
        *,
        symbols: tuple[str, ...],
        start: pd.Timestamp,
        end: pd.Timestamp,
    ) -> program.MarketBundle:
        trace["load"].append("market")
        expected_preflight = [
            *(name for name in program._LINEAGE_FILES_VERIFIED_SEPARATELY),
            "market",
            "funding",
        ]
        assert [name for name, _source_call in trace["verify"]] == expected_preflight
        assert symbols == (*program.PRIMARY_SYMBOLS, program.REFERENCE_SYMBOL)
        assert start == program.HISTORY_START
        assert end == program.EVALUATION_END
        frames = {symbol: frame.copy() for symbol in symbols}
        return program.MarketBundle(
            frames=frames,
            rows_by_symbol={symbol: len(frame) for symbol in symbols},
            first_ts_by_symbol={symbol: program.HISTORY_START for symbol in symbols},
            last_ts_by_symbol={
                symbol: program.EVALUATION_END - pd.Timedelta(minutes=15) for symbol in symbols
            },
        )

    def fake_funding(
        _path: Path,
        _spec: dict[str, Any],
        *,
        symbols: tuple[str, ...],
        venue: str,
        start: pd.Timestamp,
        engine_start: pd.Timestamp,
        end: pd.Timestamp,
    ) -> program.FundingBundle:
        trace["load"].append("funding")
        assert symbols == program.PRIMARY_SYMBOLS
        assert venue == "binance"
        assert (start, engine_start, end) == (
            program.HISTORY_START,
            program.EVALUATION_START,
            program.EVALUATION_END,
        )
        event = {
            "symbol": program.PRIMARY_SYMBOLS[0],
            "ts": program.EVALUATION_START + pd.Timedelta(hours=8),
            "rate": 0.0001,
            "mark_price": 100.0,
        }
        return program.FundingBundle(
            signal_rates={},
            engine_events=(event,),
            rows_by_symbol={symbol: 1 for symbol in symbols},
        )

    pre_intent = _Intent(
        candidate_id=program.FAIR_BASELINE_CANDIDATE_ID,
        decision_ts=(program.EVALUATION_START - pd.Timedelta(minutes=30)).to_pydatetime(),
        entry_ts=(program.EVALUATION_START - pd.Timedelta(minutes=15)).to_pydatetime(),
        symbol=program.PRIMARY_SYMBOLS[0],
    )
    boundary_intent = _Intent(
        candidate_id=program.FAIR_BASELINE_CANDIDATE_ID,
        decision_ts=(program.EVALUATION_START - pd.Timedelta(minutes=15)).to_pydatetime(),
        entry_ts=program.EVALUATION_START.to_pydatetime(),
        symbol=program.PRIMARY_SYMBOLS[0],
    )
    pre_decision = _Decision(
        emission_index=0,
        candidate_id=pre_intent.candidate_id,
        decision_ts=pre_intent.decision_ts,
        entry_ts=pre_intent.entry_ts,
        symbol=pre_intent.symbol,
        outcome="accepted",
        reason="accepted",
    )
    rejected_decision = _Decision(
        emission_index=1,
        candidate_id=program.FAIR_BASELINE_CANDIDATE_ID,
        decision_ts=(program.EVALUATION_START - pd.Timedelta(minutes=15)).to_pydatetime(),
        entry_ts=program.EVALUATION_START.to_pydatetime(),
        symbol=program.PRIMARY_SYMBOLS[1],
        outcome="rejected",
        reason="confidence_below_minimum",
    )
    boundary_decision = _Decision(
        emission_index=2,
        candidate_id=boundary_intent.candidate_id,
        decision_ts=boundary_intent.decision_ts,
        entry_ts=boundary_intent.entry_ts,
        symbol=boundary_intent.symbol,
        outcome="accepted",
        reason="accepted",
    )

    def fake_signals(
        frames: dict[str, pd.DataFrame],
        *,
        config_path: Path,
        config_sha256: str,
    ) -> _SignalBatch:
        trace["signal"].append((tuple(frames), config_path, config_sha256))
        assert tuple(frames) == program.PRIMARY_SYMBOLS
        assert program.REFERENCE_SYMBOL not in frames
        return _SignalBatch(
            candidate_id=program.FAIR_BASELINE_CANDIDATE_ID,
            config_sha256=program.EXPECTED_CONFIG_SHA256,
            decisions=(pre_decision, rejected_decision, boundary_decision),
            intents=(pre_intent, boundary_intent),
        )

    def fake_engine(
        frames: dict[str, pd.DataFrame],
        intents: tuple[_Intent, ...],
        funding: tuple[dict[str, Any], ...],
        daily_returns: pd.DataFrame,
        *,
        scenario: program.V15P2CostScenario,
        policy: program.V15P2PortfolioPolicy,
        evaluation_start: datetime,
        evaluation_end: datetime,
    ) -> _SyntheticResult:
        trace["engine"].append((scenario, id(frames), id(intents), id(funding)))
        assert tuple(frames) == program.PRIMARY_SYMBOLS
        assert all(
            pd.Timestamp(value["ts"].iloc[0]) == program.EVALUATION_START - pd.Timedelta(minutes=15)
            for value in frames.values()
        )
        assert intents == (boundary_intent,)
        assert len(funding) == 1
        assert list(daily_returns.columns) == list(program.PRIMARY_SYMBOLS)
        assert len(daily_returns.loc[daily_returns.index < program.EVALUATION_START].dropna()) >= 90
        assert policy.correlation_min_observations == 90
        assert evaluation_start == program.EVALUATION_START.to_pydatetime()
        assert evaluation_end == program.EVALUATION_END.to_pydatetime()
        start = program.EVALUATION_START.to_pydatetime()
        end_bar = (program.EVALUATION_END - pd.Timedelta(minutes=15)).to_pydatetime()
        return _SyntheticResult(
            scenario=scenario.name,
            scenario_identity=scenario.name,
            scenario_is_canonical=True,
            scenario_config=scenario,
            policy=policy,
            evaluation_start=evaluation_start,
            evaluation_end=evaluation_end,
            initial_wallet=10_000.0,
            final_wallet=10_001.0,
            final_nav=10_001.0,
            max_drawdown=-0.01,
            total_execution_cost_charged=1.0,
            total_funding_cashflow=0.1,
            accrued_terminal_exit_cost=0.0,
            entries=(_Entry(start, program.PRIMARY_SYMBOLS[0], 100.0),),
            exit_fills=(_TimedLedger(end_bar, program.PRIMARY_SYMBOLS[0], 1.0),),
            funding_events=(_TimedLedger(start, program.PRIMARY_SYMBOLS[0], 0.1),),
            journal_rows=(_TimedLedger(start, program.PRIMARY_SYMBOLS[0], -1.0),),
            stop_transitions=(_TimedLedger(start, program.PRIMARY_SYMBOLS[0], 99.0),),
            breaker_transitions=(_TimedLedger(start, program.PRIMARY_SYMBOLS[0], 0.0),),
            risk_decisions=(),
            rejections=(),
            closed_episodes=(),
            curve=(_Curve(start), _Curve(end_bar, 10_001.0)),
            terminal_positions=(),
        )

    monkeypatch.setattr(program, "_source_provenance", fake_source)
    monkeypatch.setattr(program, "_critical_runtime_versions", fake_runtime)
    monkeypatch.setattr(program, "verify_frozen_snapshot", fake_verify)
    monkeypatch.setattr(program, "load_market_snapshot", fake_market)
    monkeypatch.setattr(program, "load_funding_snapshot", fake_funding)
    monkeypatch.setattr(program, "generate_v15p2_signal_batch", fake_signals)
    monkeypatch.setattr(program, "run_v15p2_engine", fake_engine)
    return trace


def test_canonical_prereg_builds_exact_policy_and_scenarios() -> None:
    prereg = program.load_preregistration(PREREG)
    policy = program.build_policy(prereg)
    scenarios = program.build_scenarios(prereg)

    assert policy == program.V15P2PortfolioPolicy(correlation_min_observations=90)
    assert tuple(scenarios) == program.SCENARIO_ORDER
    assert scenarios["B"].fee_bps_per_fill == 4.0
    assert scenarios["B"].spread_slippage_bps_per_fill == 20.0
    assert scenarios["B"].impact_bps_per_fill == 4.5
    assert scenarios["C2"].cost_multiplier == 2.0
    assert scenarios["C2"].funding_multiplier == 2.0
    assert scenarios["H"].positive_price_pnl_multiplier == 0.5
    assert scenarios["H"].negative_price_pnl_multiplier == 1.25
    assert (
        prereg["snapshots"]["market"]["sha256"]
        == (program._EXPECTED_LINEAGE_IDENTITIES["v3_market_database"]["sha256"])
    )
    assert (
        prereg["funding_source_disclosure"]["covered_by_v3_vendor_lock_or_market_build_evidence"]
        is False
    )


def test_v2_prereg_preserves_every_v1_policy_section() -> None:
    predecessor = yaml.safe_load(
        (ROOT / "configs/crypto_15m_v15p2_fair_baseline_prereg.yaml").read_bytes()
    )
    successor = _config()
    unchanged_sections = (
        "invalidated_legacy_headline",
        "universe",
        "time_protocol",
        "audited_live_reference",
        "signal_contract",
        "execution_proxy",
        "risk_and_portfolio_policy",
        "exit_policy",
        "external_live_gate_proxy_policy",
        "cost_and_payoff_scenarios",
        "evidence_contract",
        "fair_improvement_rules_frozen_from_v16",
    )
    for section in unchanged_sections:
        assert successor[section] == predecessor[section], section
    assert successor["snapshots"]["funding"] == predecessor["snapshots"]["funding"]
    for gate in (
        "mutable_live_databases_forbidden",
        "verify_size_and_sha256_before_any_database_open",
        "verify_size_and_sha256_again_after_replay",
    ):
        assert successor["snapshots"][gate] == predecessor["snapshots"][gate]
    assert successor["pre_result_amendments"][2:] == predecessor["pre_result_amendments"]
    assert successor["limitations"][2:] == predecessor["limitations"]

    successor_purpose = dict(successor["purpose"])
    successor_purpose.pop("successor_data_identity_only")
    successor_purpose.pop("strategy_signal_engine_execution_cost_risk_report_policy_changed")
    assert successor_purpose == predecessor["purpose"]

    successor_gap_contract = dict(successor["data_and_gap_contract"])
    for key in (
        "v3_exact_primary_key_rows",
        "v3_exact_missing_vendor_bars",
        "v3_exact_missing_vendor_key_sha256",
        "synthetic_forward_filled_interpolated_or_resampled_rows",
        "exact_vendor_gap_manifest",
    ):
        successor_gap_contract.pop(key)
    assert successor_gap_contract == predecessor["data_and_gap_contract"]

    successor_governance = dict(successor["governance"])
    successor_governance["canonical_prereg_path"] = predecessor["governance"][
        "canonical_prereg_path"
    ]
    successor_governance.pop(
        "predecessor_and_v3_lineage_size_and_sha256_preflight_and_postflight_required"
    )
    assert successor_governance == predecessor["governance"]


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (
            lambda value: value["predecessor_and_v3_lineage"]["v3_success_identity"].update(
                sha256="0" * 64
            ),
            "v3_success_identity",
        ),
        (
            lambda value: value["funding_source_disclosure"].update(
                covered_by_v3_vendor_lock_or_market_build_evidence=True
            ),
            "funding disclosure",
        ),
        (
            lambda value: value["funding_source_disclosure"][
                "pre_prereg_coverage_only_access"
            ].update(primary13_rows=0),
            "funding disclosure",
        ),
    ],
)
def test_successor_lineage_or_funding_disclosure_drift_fails_closed(
    tmp_path: Path, mutation: Any, message: str
) -> None:
    config = _config()
    mutation(config)
    with pytest.raises(ValueError, match=message):
        program.load_preregistration(_write(tmp_path / "prereg.yaml", config))


def test_prereg_loader_rejects_duplicate_yaml_keys(tmp_path: Path) -> None:
    path = tmp_path / "duplicate.yaml"
    path.write_text(
        PREREG.read_text(encoding="utf-8")
        + "\nschema_version: crypto-15m-v15p2-fair-baseline-prereg-v2\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="valid YAML"):
        program.load_preregistration(path)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (
            lambda value: value["risk_and_portfolio_policy"]["correlation_gate"].__setitem__(
                "causal_daily_log_return_lookback_days", 20
            ),
            "correlation_min_observations|portfolio policy drifted",
        ),
        (
            lambda value: value["cost_and_payoff_scenarios"]["cost_scenarios"]["B"].__setitem__(
                "cost_multiplier", 0.0
            ),
            "scenario components drifted",
        ),
        (
            lambda value: value["cost_and_payoff_scenarios"]["bps_per_actual_fill"].__setitem__(
                "fee", 0.0
            ),
            "scenario components drifted",
        ),
    ],
)
def test_policy_or_masquerading_scenario_drift_fails_closed(
    tmp_path: Path, mutation: Any, message: str
) -> None:
    config = _config()
    mutation(config)
    path = _write(tmp_path / "prereg.yaml", config)
    with pytest.raises(ValueError, match=message):
        program.load_preregistration(path)


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (
            lambda value: value["time_protocol"].__setitem__(
                "development", ["2021-07-01T00:00:00Z", "2023-06-01T00:00:00Z"]
            ),
            "development window",
        ),
        (
            lambda value: value["time_protocol"]["expanding_walk_forward"][2].__setitem__(
                1, "2024-11-01T00:00:00Z"
            ),
            "six frozen walk-forward folds",
        ),
        (
            lambda value: value["fair_improvement_rules_frozen_from_v16"]["rule_1"].__setitem__(
                "challenger_H_trimmed_mean_monthly_return_pct_min_formula",
                "baseline_plus_0pp",
            ),
            "rule 1 return formula",
        ),
        (
            lambda value: value["fair_improvement_rules_frozen_from_v16"]["rule_2"].__setitem__(
                "challenger_H_max_MTM_drawdown_reduction_vs_baseline_min_fraction", 0.10
            ),
            "rule 2 drawdown reduction",
        ),
    ],
)
def test_time_folds_and_fair_improvement_contract_drift_fails_closed(
    tmp_path: Path, mutate: Any, message: str
) -> None:
    config = _config()
    mutate(config)
    with pytest.raises(ValueError, match=message):
        program.load_preregistration(_write(tmp_path / "prereg.yaml", config))


def test_runtime_contract_includes_installed_numba_and_pydantic() -> None:
    runtime = program._critical_runtime_versions(ROOT)
    assert runtime["numba"]
    assert runtime["pydantic"]


def test_provenance_scope_tracks_new_io_report_and_strategy_dependencies() -> None:
    expected = {
        "src/price_action/lab/crypto_15m_snapshot_io.py",
        "src/price_action/lab/crypto_15m_v15p2_report.py",
        "src/price_action/strategies/classic_pa.py",
        "src/price_action/contracts.py",
    }
    assert expected.issubset(program._RUNNER_SOURCE_FILES)


def test_loaded_market_requires_every_symbol_to_reach_exact_terminal_bar() -> None:
    base = _synthetic_frame()
    symbols = (*program.PRIMARY_SYMBOLS, program.REFERENCE_SYMBOL)
    frames = {symbol: base.copy() for symbol in symbols}
    broken = program.PRIMARY_SYMBOLS[-1]
    frames[broken] = frames[broken].loc[
        frames[broken]["ts"] < program.EVALUATION_END - pd.Timedelta(minutes=15)
    ]
    bundle = program.MarketBundle(
        frames=frames,
        rows_by_symbol={symbol: len(frame) for symbol, frame in frames.items()},
        first_ts_by_symbol={symbol: program.HISTORY_START for symbol in symbols},
        last_ts_by_symbol={
            symbol: pd.Timestamp(frame["ts"].iloc[-1]) for symbol, frame in frames.items()
        },
    )
    with pytest.raises(ValueError, match="final required evaluation bar"):
        program._validate_loaded_market(bundle)


def test_daily_returns_requires_the_exact_initial_90_dates_for_every_symbol() -> None:
    base = _synthetic_frame()
    frames = {symbol: base.copy() for symbol in program.PRIMARY_SYMBOLS}
    missing_day = program.EVALUATION_START - pd.Timedelta(days=10)
    first = program.PRIMARY_SYMBOLS[0]
    frames[first] = frames[first].loc[frames[first]["ts"].dt.floor("D") != missing_day]
    with pytest.raises(ValueError, match="90 complete common causal returns"):
        program._daily_log_returns(frames)


def test_signal_batch_reconciliation_fails_closed_on_accepted_intent_mismatch() -> None:
    decision_ts = (program.EVALUATION_START - pd.Timedelta(minutes=15)).to_pydatetime()
    entry_ts = program.EVALUATION_START.to_pydatetime()
    intent = _Intent(
        candidate_id=program.FAIR_BASELINE_CANDIDATE_ID,
        decision_ts=decision_ts,
        entry_ts=entry_ts,
        symbol=program.PRIMARY_SYMBOLS[0],
    )
    mismatched = _Decision(
        emission_index=0,
        candidate_id=program.FAIR_BASELINE_CANDIDATE_ID,
        decision_ts=decision_ts,
        entry_ts=entry_ts,
        symbol=program.PRIMARY_SYMBOLS[1],
        outcome="accepted",
        reason="accepted",
    )
    batch = _SignalBatch(
        candidate_id=program.FAIR_BASELINE_CANDIDATE_ID,
        config_sha256=program.EXPECTED_CONFIG_SHA256,
        decisions=(mismatched,),
        intents=(intent,),
    )
    with pytest.raises(RuntimeError, match="do not reconcile"):
        program._reconcile_signal_batch(batch)


def test_dry_plan_never_touches_snapshot_paths(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config = _config()
    path = _write(tmp_path / "prereg.yaml", config)

    def forbidden(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("dry plan accessed a snapshot boundary")

    monkeypatch.setattr(program, "verify_frozen_snapshot", forbidden)
    monkeypatch.setattr(program, "load_market_snapshot", forbidden)
    monkeypatch.setattr(program, "load_funding_snapshot", forbidden)
    monkeypatch.setattr(
        program,
        "_source_provenance",
        lambda *_args: {
            "research_source_clean": False,
            "reason": "dry plan only",
        },
    )
    payload = program.dry_plan(path, repo_root=ROOT)

    assert payload["mode"] == "DRY_PLAN_NO_SNAPSHOT_ACCESS"
    assert payload["snapshots"]["market"]["status"] == "NOT_ACCESSED"
    assert payload["snapshots"]["funding"]["status"] == "NOT_ACCESSED"
    assert all(item["status"] == "NOT_ACCESSED" for item in payload["data_lineage"].values())
    assert payload["policy"]["correlation_min_observations"] == 90
    assert payload["classification"]["result_label"] == "FAIR_LIVE_POLICY_PROXY"
    assert payload["classification"]["exact_live_replay_claim_allowed"] is False
    assert payload["disclosed_limitations"]["required"] is True
    assert payload["disclosed_limitations"]["count"] == len(payload["limitations"])
    assert payload["evaluation_protocol"]["fold_count"] == 6
    assert payload["fair_improvement_rules"]["comparison_scenario"] == "H"


def test_dry_plan_with_output_also_never_touches_snapshot_paths(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root = tmp_path / "repo"
    config = _config()
    prereg = _write(root / program.CANONICAL_PREREG_RELATIVE, config)
    lock = root / "requirements-lock.txt"
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.write_bytes((ROOT / "requirements-lock.txt").read_bytes())
    output = root / "reports/research/dry-plan.json"

    def forbidden(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("dry-plan CLI accessed a snapshot boundary")

    monkeypatch.setattr(program, "verify_frozen_snapshot", forbidden)
    monkeypatch.setattr(program, "load_market_snapshot", forbidden)
    monkeypatch.setattr(program, "load_funding_snapshot", forbidden)
    monkeypatch.setattr(
        program,
        "_source_provenance",
        lambda *_args: {"research_source_clean": False, "reason": "isolated test repo"},
    )
    assert (
        program.main(
            [
                "--dry-plan",
                "--repo-root",
                str(root),
                "--prereg",
                str(prereg),
                "--output",
                str(output),
            ]
        )
        == 0
    )
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["mode"] == "DRY_PLAN_NO_SNAPSHOT_ACCESS"
    assert payload["snapshots"]["market"]["status"] == "NOT_ACCESSED"
    assert payload["snapshots"]["funding"]["status"] == "NOT_ACCESSED"
    assert all(item["status"] == "NOT_ACCESSED" for item in payload["data_lineage"].values())


@pytest.mark.subprocess
def test_real_module_dry_plan_stdout_is_one_json_and_does_not_touch_app_log() -> None:
    app_log = ROOT / "logs/app.log"
    before = (app_log.stat().st_size, app_log.stat().st_mtime_ns) if app_log.exists() else None
    environment = os.environ.copy()
    environment.pop("PA_LOG_QUIET", None)
    environment.pop("PA_DISABLE_FILE_LOG", None)
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "price_action.lab.crypto_15m_v15p2_program",
            "--dry-plan",
            "--repo-root",
            str(ROOT),
            "--prereg",
            str(PREREG),
        ],
        cwd=ROOT,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )

    payload = json.loads(completed.stdout)
    assert payload["mode"] == "DRY_PLAN_NO_SNAPSHOT_ACCESS"
    assert payload["snapshots"]["market"]["status"] == "NOT_ACCESSED"
    assert payload["snapshots"]["funding"]["status"] == "NOT_ACCESSED"
    assert completed.stderr == ""
    after = (app_log.stat().st_size, app_log.stat().st_mtime_ns) if app_log.exists() else None
    assert after == before


def test_full_program_filters_boundary_and_runs_independent_b_c2_h_once(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    trace = _install_full_run_mocks(monkeypatch, tmp_path)
    payload = program.run_program(PREREG, repo_root=ROOT)

    assert trace["source"] == [1, 2]
    assert trace["runtime"] == [1, 2]
    assert [item[0] for item in trace["verify"]] == [
        *program._LINEAGE_FILES_VERIFIED_SEPARATELY,
        "market",
        "funding",
        "market",
        "funding",
        *program._LINEAGE_FILES_VERIFIED_SEPARATELY,
    ]
    assert trace["load"] == ["market", "funding"]
    assert len(trace["signal"]) == 1
    assert [item[0].name for item in trace["engine"]] == ["B", "C2", "H"]
    assert len({id(item[0]) for item in trace["engine"]}) == 3

    assert payload["mode"] == "FULL_FROZEN_PRIMARY13_REPLAY"
    assert payload["evidence_eligible"] is True
    assert set(payload["data_lineage"]) == set(program._LINEAGE_FILES_VERIFIED_SEPARATELY)
    assert all(item["status"] == "VERIFIED" for item in payload["data_lineage"].values())
    assert payload["execution_governance"]["lineage_unchanged_postflight"] is True
    assert payload["market_loading"]["reference_symbol_traded"] is False
    assert payload["signal_stream"]["generation_call_count"] == 1
    assert payload["signal_stream"]["raw_emission_count"] == 3
    assert payload["signal_stream"]["generated_history_intent_count"] == 2
    assert payload["signal_stream"]["evaluation_intent_count"] == 1
    assert len(payload["signal_stream"]["accepted_intents"]) == 2
    assert payload["signal_stream"]["accepted_intents_sha256"] == program._payload_sha256(
        payload["signal_stream"]["accepted_intents"]
    )
    assert len(payload["signal_stream"]["decision_ledger"]) == 3
    assert len(payload["signal_stream"]["decision_ledger_sha256"]) == 64
    assert payload["signal_stream"]["decision_ledger_sha256"] == program._payload_sha256(
        payload["signal_stream"]["decision_ledger"]
    )
    assert payload["signal_stream"]["decision_reason_counts"] == {
        "accepted": 2,
        "confidence_below_minimum": 1,
    }
    reconciliation = payload["signal_stream"]["accepted_intent_reconciliation"]
    assert reconciliation["exact_ordered_reconciliation"] is True
    assert reconciliation["evaluation_exact_ordered_reconciliation"] is True
    assert reconciliation["evaluation_intent_count"] == 1
    assert payload["signal_stream"]["only_signal_eligible_intents_passed_to_engines"] is True
    intent = payload["signal_stream"]["entry_intents"][0]
    assert intent["entry_ts"] == program.EVALUATION_START.isoformat()
    assert tuple(payload["results"]) == program.SCENARIO_ORDER
    for name in program.SCENARIO_ORDER:
        complete = payload["results"][name]["complete_result"]
        assert complete["scenario"] == name
        assert complete["entries"][0]["entry_ts"] == program.EVALUATION_START.isoformat()
        assert complete["curve"][0]["ts"] == program.EVALUATION_START.isoformat()
        assert (
            complete["curve"][-1]["ts"]
            == (program.EVALUATION_END - pd.Timedelta(minutes=15)).isoformat()
        )
        assert "breaker_transitions" in complete
        assert "funding_events" in complete
        assert "terminal_positions" in complete
    program.deterministic_json(payload)


def test_noncanonical_or_dirty_source_fails_before_snapshot_access(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def forbidden(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("snapshot access occurred before governance passed")

    monkeypatch.setattr(program, "verify_frozen_snapshot", forbidden)
    copied = _write(tmp_path / "copied.yaml", _config())
    with pytest.raises(ValueError, match="canonical repo"):
        program.run_program(copied, repo_root=ROOT)

    monkeypatch.setattr(
        program,
        "_source_provenance",
        lambda *_args: {
            "git_commit": "a" * 40,
            "research_source_clean": False,
            "research_source_status": [" M source.py"],
            "missing_source_files": [],
            "file_sha256": {},
            "reference_source_checks": {},
            "exact_reference_source_hashes_match": True,
        },
    )
    monkeypatch.setattr(program, "_critical_runtime_versions", lambda _root: {"python": "test"})
    with pytest.raises(RuntimeError, match="clean exact research"):
        program.run_program(PREREG, repo_root=ROOT)


@pytest.mark.parametrize(
    ("source_mutates", "snapshot_mutates", "lineage_mutates", "message"),
    [
        (True, False, False, "source changed"),
        (False, True, False, "snapshot changed"),
        (False, False, True, "lineage file changed"),
    ],
)
def test_postflight_mutation_is_fatal(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    source_mutates: bool,
    snapshot_mutates: bool,
    lineage_mutates: bool,
    message: str,
) -> None:
    _install_full_run_mocks(
        monkeypatch,
        tmp_path,
        source_mutates=source_mutates,
        snapshot_mutates=snapshot_mutates,
        lineage_mutates=lineage_mutates,
    )
    with pytest.raises(RuntimeError, match=message):
        program.run_program(PREREG, repo_root=ROOT)


def test_strict_json_rejects_nonfinite_values() -> None:
    with pytest.raises(ValueError):
        program.deterministic_json({"bad": float("nan")})


@pytest.mark.subprocess
def test_source_reference_hash_mismatch_is_part_of_clean_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prereg = program.load_preregistration(PREREG)
    provenance = program._source_provenance(prereg, ROOT)
    assert "exact_reference_source_hashes_match" in provenance
    assert len(provenance["reference_source_checks"]) == len(program._REFERENCE_SOURCE_KEYS)
    assert {
        "classic_strategy_indicators",
        "signal_contracts_and_stable_hash",
    }.issubset(provenance["reference_source_checks"])
    for relative in (
        "src/price_action/__init__.py",
        "src/price_action/lab/__init__.py",
        "src/price_action/strategies/__init__.py",
        "src/price_action/logging_config.py",
        "src/price_action/lab/crypto_15m_snapshot_io.py",
        "src/price_action/lab/crypto_15m_v15p2_report.py",
        "src/price_action/strategies/classic_pa.py",
        "src/price_action/contracts.py",
        "tests/test_crypto_15m_v15p2_engine.py",
        "tests/test_crypto_15m_v15p2_program.py",
        "tests/test_crypto_15m_v15p2_report.py",
        "tests/test_crypto_15m_v15p2_signals.py",
        "tests/risk/test_consecutive_loss_counter.py",
    ):
        assert relative in provenance["file_sha256"]
        assert len(provenance["file_sha256"][relative]) == 64
