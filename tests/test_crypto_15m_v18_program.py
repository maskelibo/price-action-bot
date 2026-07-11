from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from price_action.lab import crypto_15m_v18_program as program
from price_action.lab.crypto_15m_v15p2_engine import SCENARIOS, V15P2PortfolioPolicy

ROOT = Path(__file__).resolve().parents[1]
PREREG = ROOT / program.CANONICAL_PREREG_RELATIVE


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
    confluence_score: float = 0.5
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
class _Decision:
    cell_id: str
    reason: str
    outcome: str
    source_intent_index: int = 0


@dataclass(frozen=True)
class _BaselineBatch:
    candidate_id: str
    decisions: tuple[Any, ...]
    intents: tuple[_Intent, ...]


@dataclass(frozen=True)
class _CellBatch:
    candidate_id: str
    decisions: tuple[_Decision, ...]
    intents: tuple[_Intent, ...]

    @property
    def rejections(self) -> tuple[_Decision, ...]:
        return tuple(row for row in self.decisions if row.outcome == "rejected")


def _snapshot_verification(
    name: str, spec: dict[str, Any], tmp_path: Path, *, digest: str | None = None
) -> program.SnapshotVerification:
    return program.SnapshotVerification(
        name=name,
        configured_path=str(spec["path"]),
        resolved_path=str(tmp_path / f"{name}.duckdb"),
        bytes=int(spec["bytes"]),
        sha256=digest or str(spec["sha256"]),
    )


def _frame() -> pd.DataFrame:
    timestamps = pd.DatetimeIndex(
        [
            program.HISTORY_START,
            program.EVALUATION_START - pd.Timedelta(minutes=15),
            program.EVALUATION_START,
            program.EVALUATION_END - pd.Timedelta(minutes=15),
        ]
    )
    return pd.DataFrame(
        {
            "ts": timestamps,
            "open": 100.0,
            "high": 101.0,
            "low": 99.0,
            "close": 100.0,
            "volume": 1.0,
        }
    )


def _prepare_repo(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    root = tmp_path / "repo"
    prereg = root / program.CANONICAL_PREREG_RELATIVE
    prereg.parent.mkdir(parents=True)
    prereg.write_bytes(PREREG.read_bytes())
    prereg_payload = program.load_preregistration(prereg)
    reports = root / "reports/research"
    reports.mkdir(parents=True)
    raw_artifact = root / program.CANONICAL_BASELINE_RAW_RELATIVE
    report_artifact = root / program.CANONICAL_BASELINE_REPORT_RELATIVE
    raw_payload = {
        "schema_version": "crypto-15m-v15p2-fair-baseline-run-v2",
        "evidence_eligible": True,
        "source_provenance": {"git_commit": "b" * 40},
        "runtime_versions": {"python": "test"},
    }
    raw_artifact.write_text(json.dumps(raw_payload, sort_keys=True), encoding="utf-8")
    report_payload = {
        "schema_version": "crypto-15m-v15p2-fair-baseline-report-v2",
        "evidence_eligible": True,
        "provenance": {
            "raw_git_commit": "b" * 40,
            "raw_payload_sha256": program._payload_sha256(raw_payload),
            "input_artifact": {
                "file_bytes": raw_artifact.stat().st_size,
                "sha256": program.sha256_file(raw_artifact),
            },
        },
    }
    report_artifact.write_text(json.dumps(report_payload, sort_keys=True), encoding="utf-8")
    frozen = prereg_payload["frozen_lineage"]
    snapshots = prereg_payload["snapshots"]
    baseline_identity = root / program.CANONICAL_BASELINE_IDENTITY_RELATIVE
    baseline_identity.write_text(
        json.dumps(
            {
                "schema_version": ("crypto-15m-v15p2-fair-baseline-v2-result-identity-v1"),
                "status": "SEALED_ELIGIBLE_BASELINE_MEASUREMENT_NO_DEPLOYMENT",
                "live_or_paper_authorized": False,
                "execution_git_commit": "b" * 40,
                "raw_artifact": {
                    "path": program.CANONICAL_BASELINE_RAW_RELATIVE,
                    "schema_version": "crypto-15m-v15p2-fair-baseline-run-v2",
                    "evidence_eligible": True,
                    "bytes": raw_artifact.stat().st_size,
                    "sha256": program.sha256_file(raw_artifact),
                },
                "report_artifact": {
                    "path": program.CANONICAL_BASELINE_REPORT_RELATIVE,
                    "schema_version": "crypto-15m-v15p2-fair-baseline-report-v2",
                    "evidence_eligible": True,
                    "bytes": report_artifact.stat().st_size,
                    "sha256": program.sha256_file(report_artifact),
                },
                "preregistration": {
                    key: frozen["fair_baseline_v2_contract"][key]
                    for key in ("path", "bytes", "sha256")
                },
                "program_source": {
                    key: frozen["fair_baseline_v2_program_source"][key]
                    for key in ("path", "bytes", "sha256")
                },
                "report_source": {
                    key: frozen["fair_baseline_v2_report_source"][key]
                    for key in ("path", "bytes", "sha256")
                },
                "market_snapshot": {
                    key: snapshots["market"][key] for key in ("path", "bytes", "sha256")
                },
                "funding_snapshot": {
                    key: snapshots["funding"][key] for key in ("path", "bytes", "sha256")
                },
            }
        ),
        encoding="utf-8",
    )
    source_files = {
        relative: {"bytes": 1, "sha256": "a" * 64}
        for relative in program._REQUIRED_LOCKED_SOURCE_FILES
    }
    lock_payload = {
        "schema_version": program.LOCK_SCHEMA,
        "status": "LOCKED_FOR_HISTORICAL_REPLAY_NO_RESULTS_SEEN",
        "performance_result_seen_before_lock": False,
        "historical_replay_authorized": True,
        "live_or_paper_authorized": False,
        "execution_git_commit": "b" * 40,
        "preregistration": {
            "path": program.CANONICAL_PREREG_RELATIVE,
            "bytes": prereg.stat().st_size,
            "sha256": program.sha256_file(prereg),
        },
        "source_files": source_files,
        "baseline_result_identity_contract": {
            "canonical_path": program.CANONICAL_BASELINE_IDENTITY_RELATIVE,
            "bytes": baseline_identity.stat().st_size,
            "sha256": program.sha256_file(baseline_identity),
            "required_before_v18_execute": True,
            "raw_evidence_eligible": True,
            "report_evidence_eligible": True,
        },
        "metric_semantics": program.LOCKED_METRIC_SEMANTICS,
    }
    lock = root / program.CANONICAL_LOCK_RELATIVE
    lock.write_text(json.dumps(lock_payload, sort_keys=True), encoding="utf-8")
    return root, prereg, lock, root / program.CANONICAL_PRIMARY_BUNDLE_RELATIVE


def _install_run_mocks(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    mutate_engine_frame: bool = False,
    source_drift: bool = False,
    snapshot_drift: bool = False,
    fail_engine_call: int | None = None,
) -> dict[str, Any]:
    trace: dict[str, Any] = {
        "verify": [],
        "loads": [],
        "baseline_signal": 0,
        "adapter": 0,
        "engine": [],
        "source": 0,
    }

    def fake_source(_lock: dict[str, Any], _root: Path) -> dict[str, Any]:
        trace["source"] += 1
        digest = "x" if source_drift and trace["source"] == 2 else "a"
        return {
            "runtime_git_commit": "c" * 40,
            "locked_source_commit": "b" * 40,
            "locked_commit_is_runtime_ancestor": True,
            "locked_commit_blobs_match": True,
            "scoped_source_clean": True,
            "scoped_source_status": [],
            "source_identities": {"synthetic.py": {"sha256": digest}},
        }

    verification_counts: dict[str, int] = {}

    def fake_verify(
        name: str, spec: dict[str, Any], *, repo_root: Path
    ) -> program.SnapshotVerification:
        del repo_root
        trace["verify"].append(name)
        verification_counts[name] = verification_counts.get(name, 0) + 1
        digest = str(spec["sha256"])
        if snapshot_drift and name == "funding" and verification_counts[name] == 2:
            digest = "f" * 64
        return _snapshot_verification(name, spec, tmp_path, digest=digest)

    frame = _frame()

    def fake_market(
        _path: Path,
        _spec: dict[str, Any],
        *,
        symbols: tuple[str, ...],
        start: pd.Timestamp,
        end: pd.Timestamp,
    ) -> program.baseline.MarketBundle:
        trace["loads"].append("market")
        assert symbols == (*program.PRIMARY_SYMBOLS, program.REFERENCE_SYMBOL)
        assert (start, end) == (program.HISTORY_START, program.EVALUATION_END)
        return program.baseline.MarketBundle(
            frames={symbol: frame.copy() for symbol in symbols},
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
    ) -> program.baseline.FundingBundle:
        trace["loads"].append("funding")
        assert symbols == program.PRIMARY_SYMBOLS
        assert venue == "binance"
        assert (start, engine_start, end) == (
            program.HISTORY_START,
            program.EVALUATION_START,
            program.EVALUATION_END,
        )
        return program.baseline.FundingBundle(signal_rates={}, engine_events=(), rows_by_symbol={})

    intent = _Intent(
        candidate_id=program.FAIR_BASELINE_CANDIDATE_ID,
        decision_ts=(program.EVALUATION_START - pd.Timedelta(minutes=15)).to_pydatetime(),
        entry_ts=program.EVALUATION_START.to_pydatetime(),
        symbol=program.PRIMARY_SYMBOLS[0],
    )
    baseline_batch = _BaselineBatch(
        candidate_id=program.FAIR_BASELINE_CANDIDATE_ID,
        decisions=({"reason": "accepted"},),
        intents=(intent,),
    )

    def fake_baseline_signals(*_args: Any, **_kwargs: Any) -> _BaselineBatch:
        trace["baseline_signal"] += 1
        return baseline_batch

    batches = {
        cell: _CellBatch(
            candidate_id=cell,
            decisions=(_Decision(cell, "accepted_no_htf", "accepted"),),
            intents=(intent,),
        )
        for cell in program.CELL_ORDER
    }

    def fake_batches(
        frames: dict[str, pd.DataFrame], source: _BaselineBatch
    ) -> dict[str, _CellBatch]:
        trace["adapter"] += 1
        assert tuple(frames) == program.PRIMARY_SYMBOLS
        assert source is baseline_batch
        return batches

    engine_calls = 0

    def fake_engine(
        frames: dict[str, pd.DataFrame],
        intents: tuple[Any, ...],
        funding_events: tuple[Any, ...],
        daily_returns: pd.DataFrame,
        *,
        scenario: Any,
        policy: Any,
        evaluation_start: datetime,
        evaluation_end: datetime,
    ) -> dict[str, Any]:
        nonlocal engine_calls
        engine_calls += 1
        cell = intents[0].cell_id
        trace["engine"].append((cell, scenario.name))
        assert all(intent.candidate_id == program.FAIR_BASELINE_CANDIDATE_ID for intent in intents)
        assert funding_events == ()
        assert list(daily_returns) == list(program.PRIMARY_SYMBOLS)
        assert policy == V15P2PortfolioPolicy(correlation_min_observations=90)
        assert (evaluation_start, evaluation_end) == (
            program.EVALUATION_START.to_pydatetime(),
            program.EVALUATION_END.to_pydatetime(),
        )
        if fail_engine_call == engine_calls:
            raise RuntimeError("synthetic engine failure")
        result = {
            "scenario": scenario.name,
            "entries": [
                {
                    "candidate_id": program.FAIR_BASELINE_CANDIDATE_ID,
                    "symbol": program.PRIMARY_SYMBOLS[0],
                }
            ],
            "curve": [{"ts": program.EVALUATION_START, "nav": 10_000.0}],
        }
        if mutate_engine_frame:
            frames[program.PRIMARY_SYMBOLS[0]].loc[0, "close"] = 999.0
        return result

    returns = pd.DataFrame(
        {symbol: [0.0] for symbol in program.PRIMARY_SYMBOLS},
        index=pd.DatetimeIndex([program.HISTORY_START]),
    )
    monkeypatch.setattr(program, "_source_provenance", fake_source)
    monkeypatch.setattr(
        program.baseline, "_critical_runtime_versions", lambda _root: {"python": "test"}
    )
    monkeypatch.setattr(program, "verify_frozen_snapshot", fake_verify)
    monkeypatch.setattr(program, "load_market_snapshot", fake_market)
    monkeypatch.setattr(program, "load_funding_snapshot", fake_funding)
    monkeypatch.setattr(program.baseline, "_validate_loaded_market", lambda _market: None)
    monkeypatch.setattr(program, "generate_v15p2_signal_batch", fake_baseline_signals)
    monkeypatch.setattr(program, "_candidate_batches", fake_batches)
    monkeypatch.setattr(program.baseline, "load_preregistration", lambda _path: {})
    monkeypatch.setattr(
        program.baseline,
        "build_policy",
        lambda _prereg: V15P2PortfolioPolicy(correlation_min_observations=90),
    )
    monkeypatch.setattr(program.baseline, "build_scenarios", lambda _prereg: SCENARIOS)
    monkeypatch.setattr(program.baseline, "_daily_log_returns", lambda _frames: returns.copy())
    monkeypatch.setattr(program.baseline, "_assert_result_window", lambda *_a, **_kw: None)
    monkeypatch.setattr(program, "run_v15p2_engine", fake_engine)
    monkeypatch.setattr(
        program,
        "_rebuild_primary_report",
        lambda _manifest, *, prereg, root: program._read_json(
            root / program.CANONICAL_PRIMARY_REPORT_RELATIVE,
            "synthetic primary report",
        ),
    )
    return trace


def _write_primary_report(
    root: Path,
    *,
    winner: str | None = "C1_VSA_ONLY",
    verdict: str = "REQUIRES_TRUE_LOSO",
) -> Path:
    manifest_path = root / program.CANONICAL_PRIMARY_BUNDLE_RELATIVE / "manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text('{"status":"COMPLETE"}\n', encoding="utf-8")
    path = root / program.CANONICAL_PRIMARY_REPORT_RELATIVE
    path.parent.mkdir(parents=True, exist_ok=True)
    ranking = [] if winner is None else [{"candidate_id": winner, "rank": 1}]
    path.write_text(
        json.dumps(
            {
                "schema_version": "crypto-15m-v18-primary-report-v1",
                "deterministic": True,
                "evidence_eligible": True,
                "evidence_ineligible_reasons": [],
                "decision": {
                    "verdict": verdict,
                    "locked_winner": winner,
                    "remaining_required_evidence": [
                        "TRUE_LOSO_NOT_YET_EVALUATED",
                        "BASELINE_COMPARISON_NOT_YET_EVALUATED",
                    ],
                    "historical_feasibility_only": True,
                    "paper_authorized": False,
                    "live_deployment_authorized": False,
                },
                "candidate_order": list(program.CELL_ORDER),
                "scenario_order": list(program.SCENARIO_ORDER),
                "ranking": ranking,
                "provenance": {
                    "manifest_path": str(manifest_path.resolve()),
                    "manifest_bytes": manifest_path.stat().st_size,
                    "manifest_sha256": program.sha256_file(manifest_path),
                },
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return path


def _install_loso_engine(
    monkeypatch: pytest.MonkeyPatch,
    *,
    fail_call: int | None = None,
    mutate_returns: bool = False,
) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []

    def fake_engine(
        frames: dict[str, pd.DataFrame],
        intents: tuple[Any, ...],
        funding_events: tuple[Any, ...],
        daily_returns: pd.DataFrame,
        *,
        scenario: Any,
        policy: Any,
        evaluation_start: datetime,
        evaluation_end: datetime,
    ) -> dict[str, Any]:
        missing = tuple(symbol for symbol in program.PRIMARY_SYMBOLS if symbol not in frames)
        assert len(missing) == 1
        excluded = missing[0]
        assert tuple(frames) == tuple(
            symbol for symbol in program.PRIMARY_SYMBOLS if symbol != excluded
        )
        assert tuple(daily_returns.columns) == tuple(frames)
        assert all(intent.symbol != excluded for intent in intents)
        assert all(program._funding_symbol(event) != excluded for event in funding_events)
        assert scenario.name == "H"
        assert policy == V15P2PortfolioPolicy(correlation_min_observations=90)
        assert (evaluation_start, evaluation_end) == (
            program.EVALUATION_START.to_pydatetime(),
            program.EVALUATION_END.to_pydatetime(),
        )
        calls.append(
            {
                "excluded_symbol": excluded,
                "intent_symbols": tuple(intent.symbol for intent in intents),
                "return_columns": tuple(daily_returns.columns),
            }
        )
        if fail_call == len(calls):
            raise RuntimeError("synthetic LOSO engine failure")
        if mutate_returns:
            daily_returns.iloc[0, 0] = 999.0
        entries = [
            {
                "candidate_id": program.FAIR_BASELINE_CANDIDATE_ID,
                "symbol": intent.symbol,
            }
            for intent in intents
        ]
        return {
            "scenario": "H",
            "entries": entries,
            "curve": [{"ts": program.EVALUATION_START, "nav": 10_000.0}],
        }

    monkeypatch.setattr(program, "run_v15p2_engine", fake_engine)
    return calls


def test_dry_plan_has_zero_snapshot_access(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    prereg = tmp_path / "prereg.yaml"
    prereg.write_bytes(PREREG.read_bytes())

    def forbidden(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("dry plan touched a snapshot")

    monkeypatch.setattr(program, "verify_frozen_snapshot", forbidden)
    monkeypatch.setattr(program, "load_market_snapshot", forbidden)
    monkeypatch.setattr(program, "load_funding_snapshot", forbidden)
    plan = program.dry_plan(prereg, repo_root=tmp_path)
    assert plan["mode"] == "DRY_PLAN_ZERO_SNAPSHOT_ACCESS"
    assert plan["expected_independent_replays"] == 12
    assert all(item["status"] == "NOT_ACCESSED" for item in plan["snapshots"].values())

    loso = program.dry_plan(prereg, repo_root=tmp_path, phase="loso")
    assert loso["expected_independent_replays"] == 13
    assert loso["excluded_symbol_order"] == list(program.PRIMARY_SYMBOLS)
    assert loso["primary_report"]["status"] == "NOT_ACCESSED_DRY_PLAN"


def test_prereg_rejects_cell_drift(tmp_path: Path) -> None:
    text = PREREG.read_text(encoding="utf-8").replace("id: C1_VSA_ONLY", "id: C1_CHANGED", 1)
    path = tmp_path / "drift.yaml"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(ValueError, match="candidate cell contract drifted"):
        program.load_preregistration(path)


def test_lock_rejects_missing_metric_binding(tmp_path: Path) -> None:
    _root, _prereg, lock, _bundle = _prepare_repo(tmp_path)
    payload = json.loads(lock.read_bytes())
    payload["metric_semantics"].pop("H_turnover")
    lock.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="metric semantics drifted"):
        program._load_execution_lock(lock)


@pytest.mark.parametrize(
    "relative",
    [
        "src/price_action/strategies/classic_pa.py",
        "src/price_action/settings.py",
        "src/price_action/runtime_paths.py",
        "src/price_action/__init__.py",
        "src/price_action/lab/__init__.py",
        "src/price_action/strategies/__init__.py",
        "requirements-lock.txt",
    ],
)
def test_lock_rejects_omitted_transitive_strategy_source(tmp_path: Path, relative: str) -> None:
    _root, _prereg, lock, _bundle = _prepare_repo(tmp_path)
    payload = json.loads(lock.read_bytes())
    payload["source_files"].pop(relative)
    lock.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="omits required source files"):
        program._load_execution_lock(lock)


def test_baseline_identity_execution_commit_must_match_v18_lock(tmp_path: Path) -> None:
    root, prereg, _lock, _bundle = _prepare_repo(tmp_path)
    identity_path = root / program.CANONICAL_BASELINE_IDENTITY_RELATIVE
    identity = json.loads(identity_path.read_bytes())
    identity["execution_git_commit"] = "c" * 40
    identity_path.write_text(json.dumps(identity, sort_keys=True), encoding="utf-8")
    with pytest.raises(RuntimeError, match="execution commit differs from V18 lock"):
        program._baseline_identity_evidence(
            identity_path,
            root=root,
            prereg=program.load_preregistration(prereg),
            expected_execution_git_commit="b" * 40,
        )


def test_run_rejects_runtime_different_from_sealed_baseline_before_snapshot_access(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root, prereg, lock, bundle = _prepare_repo(tmp_path)
    trace = _install_run_mocks(monkeypatch, tmp_path)
    monkeypatch.setattr(
        program.baseline,
        "_critical_runtime_versions",
        lambda _root: {"python": "different"},
    )

    with pytest.raises(RuntimeError, match="differs from the sealed baseline runtime"):
        program.run_program(
            prereg,
            execution_lock_path=lock,
            bundle_dir=bundle,
            repo_root=root,
        )

    assert trace["verify"] == []
    assert trace["loads"] == []


@pytest.mark.subprocess
def test_source_provenance_rejects_clean_descendant_code_not_in_locked_commit(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo"
    source = root / "source.py"
    root.mkdir()
    subprocess.run(("git", "init", "-q"), cwd=root, check=True)
    subprocess.run(("git", "config", "user.email", "test@example.invalid"), cwd=root, check=True)
    subprocess.run(("git", "config", "user.name", "V18 Test"), cwd=root, check=True)
    source.write_text("VALUE = 'before'\n", encoding="utf-8")
    subprocess.run(("git", "add", "source.py"), cwd=root, check=True)
    subprocess.run(("git", "commit", "-q", "-m", "locked source"), cwd=root, check=True)
    locked_commit = subprocess.run(
        ("git", "rev-parse", "HEAD"),
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    source.write_text("VALUE = 'result-informed'\n", encoding="utf-8")
    subprocess.run(("git", "add", "source.py"), cwd=root, check=True)
    subprocess.run(("git", "commit", "-q", "-m", "clean descendant"), cwd=root, check=True)
    lock = {
        "execution_git_commit": locked_commit,
        "source_files": {
            "source.py": {
                "bytes": source.stat().st_size,
                "sha256": program.sha256_file(source),
            }
        },
    }

    provenance = program._source_provenance(lock, root)

    assert provenance["locked_commit_is_runtime_ancestor"] is True
    assert provenance["scoped_source_clean"] is True
    assert provenance["locked_commit_blobs_match"] is False
    with pytest.raises(RuntimeError, match="exact Git blobs"):
        program._assert_source_ready(provenance)


def test_run_loads_once_orders_twelve_shards_and_publishes_manifest_last(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root, prereg, lock, bundle = _prepare_repo(tmp_path)
    trace = _install_run_mocks(monkeypatch, tmp_path)
    manifest = program.run_program(
        prereg, execution_lock_path=lock, bundle_dir=bundle, repo_root=root
    )
    expected = [
        (cell, scenario) for cell in program.CELL_ORDER for scenario in program.SCENARIO_ORDER
    ]
    assert trace["loads"] == ["market", "funding"]
    assert trace["baseline_signal"] == 1
    assert trace["adapter"] == 1
    assert trace["engine"] == expected
    assert manifest["status"] == "COMPLETE"
    assert len(manifest["shards"]) == 12
    assert (bundle / "manifest.json").is_file()
    assert [(item["candidate_id"], item["scenario"]) for item in manifest["shards"]] == expected
    shard = json.loads((bundle / "C1_VSA_ONLY__B.json").read_bytes())
    assert shard["candidate_id"] == "C1_VSA_ONLY"
    assert (
        shard["candidate_batch_sha256"]
        == manifest["input_hashes"]["candidate_batches_sha256"]["C1_VSA_ONLY"]
    )
    assert shard["complete_result"]["entries"][0]["candidate_id"] == "C1_VSA_ONLY"
    assert shard["engine_candidate_binding"]["candidate_id_rebinding_count"] == 1
    rebound = program._rebind_candidate_ids(
        shard["complete_result"],
        program.FAIR_BASELINE_CANDIDATE_ID,
        source_candidate_id="C1_VSA_ONLY",
    )
    assert (
        program._payload_sha256(rebound)
        == shard["engine_candidate_binding"]["raw_engine_result_sha256"]
    )


def test_engine_input_mutation_fails_before_any_manifest(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root, prereg, lock, bundle = _prepare_repo(tmp_path)
    _install_run_mocks(monkeypatch, tmp_path, mutate_engine_frame=True)
    with pytest.raises(RuntimeError, match="mutated market frames"):
        program.run_program(prereg, execution_lock_path=lock, bundle_dir=bundle, repo_root=root)
    assert not (bundle / "manifest.json").exists()


def test_mid_bundle_failure_leaves_no_manifest(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root, prereg, lock, bundle = _prepare_repo(tmp_path)
    _install_run_mocks(monkeypatch, tmp_path, fail_engine_call=2)
    with pytest.raises(RuntimeError, match="synthetic engine failure"):
        program.run_program(prereg, execution_lock_path=lock, bundle_dir=bundle, repo_root=root)
    assert (bundle / "C1_VSA_ONLY__B.json").is_file()
    assert not (bundle / "manifest.json").exists()


@pytest.mark.parametrize(
    ("source_drift", "snapshot_drift", "message"),
    [
        (True, False, "source changed"),
        (False, True, "snapshot identity changed"),
    ],
)
def test_postflight_drift_leaves_complete_shards_but_no_manifest(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    source_drift: bool,
    snapshot_drift: bool,
    message: str,
) -> None:
    root, prereg, lock, bundle = _prepare_repo(tmp_path)
    _install_run_mocks(
        monkeypatch,
        tmp_path,
        source_drift=source_drift,
        snapshot_drift=snapshot_drift,
    )
    with pytest.raises(RuntimeError, match=message):
        program.run_program(prereg, execution_lock_path=lock, bundle_dir=bundle, repo_root=root)
    assert len(list(bundle.glob("*.json"))) == 12
    assert not (bundle / "manifest.json").exists()


def test_existing_bundle_is_rejected_before_snapshot_access(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root, prereg, lock, bundle = _prepare_repo(tmp_path)
    bundle.mkdir()
    monkeypatch.setattr(
        program,
        "verify_frozen_snapshot",
        lambda *_a, **_kw: pytest.fail("snapshot accessed"),
    )
    with pytest.raises(FileExistsError, match="already exists"):
        program.run_program(prereg, execution_lock_path=lock, bundle_dir=bundle, repo_root=root)


def test_true_loso_runs_exact_thirteen_exclusions_and_manifest_last(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root, prereg, lock, _primary_bundle = _prepare_repo(tmp_path)
    primary_report = _write_primary_report(root)
    trace = _install_run_mocks(monkeypatch, tmp_path)
    calls = _install_loso_engine(monkeypatch)
    bundle = root / program.CANONICAL_LOSO_BUNDLE_RELATIVE

    manifest = program.run_true_loso_replays(
        prereg,
        execution_lock_path=lock,
        primary_report_path=primary_report,
        bundle_dir=bundle,
        repo_root=root,
        primary_report_bytes=primary_report.stat().st_size,
        primary_report_sha256=program.sha256_file(primary_report),
    )

    assert trace["loads"] == ["market", "funding"]
    assert trace["baseline_signal"] == 1
    assert trace["adapter"] == 1
    assert [row["excluded_symbol"] for row in calls] == list(program.PRIMARY_SYMBOLS)
    assert manifest["schema_version"] == program.LOSO_MANIFEST_SCHEMA
    assert manifest["locked_winner"] == "C1_VSA_ONLY"
    assert manifest["runner_up_fallback_used"] is False
    assert len(manifest["shards"]) == 13
    assert (bundle / "manifest.json").is_file()
    for call, spec in zip(calls, manifest["shards"], strict=True):
        excluded = call["excluded_symbol"]
        assert spec["excluded_symbol"] == excluded
        shard = json.loads((bundle / spec["path"]).read_bytes())
        assert shard["excluded_symbol"] == excluded
        assert excluded not in shard["included_symbols"]
        assert shard["scenario"] == "H"
        assert shard["candidate_id"] == "C1_VSA_ONLY"
        assert shard["continuous_replay_window"]["month_or_fold_restarts"] == 0


@pytest.mark.parametrize(
    ("winner", "verdict", "message"),
    [
        (None, "RED_NO_PRIMARY_CELL_PASSED", "does not require true LOSO"),
        ("C9_DRIFT", "REQUIRES_TRUE_LOSO", "locked_winner drifted"),
    ],
)
def test_true_loso_rejects_red_or_winner_drift_before_snapshot_access(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    winner: str | None,
    verdict: str,
    message: str,
) -> None:
    root, prereg, lock, _primary_bundle = _prepare_repo(tmp_path)
    primary_report = _write_primary_report(root, winner=winner, verdict=verdict)
    trace = _install_run_mocks(monkeypatch, tmp_path)
    bundle = root / program.CANONICAL_LOSO_BUNDLE_RELATIVE

    with pytest.raises(RuntimeError, match=message):
        program.run_true_loso_replays(
            prereg,
            execution_lock_path=lock,
            primary_report_path=primary_report,
            bundle_dir=bundle,
            repo_root=root,
            primary_report_bytes=primary_report.stat().st_size,
            primary_report_sha256=program.sha256_file(primary_report),
        )
    assert trace["verify"] == []
    assert not bundle.exists()


def test_true_loso_mid_run_failure_leaves_no_manifest(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root, prereg, lock, _primary_bundle = _prepare_repo(tmp_path)
    primary_report = _write_primary_report(root)
    _install_run_mocks(monkeypatch, tmp_path)
    _install_loso_engine(monkeypatch, fail_call=2)
    bundle = root / program.CANONICAL_LOSO_BUNDLE_RELATIVE

    with pytest.raises(RuntimeError, match="synthetic LOSO engine failure"):
        program.run_true_loso_replays(
            prereg,
            execution_lock_path=lock,
            primary_report_path=primary_report,
            bundle_dir=bundle,
            repo_root=root,
            primary_report_bytes=primary_report.stat().st_size,
            primary_report_sha256=program.sha256_file(primary_report),
        )
    assert len(list(bundle.glob("without__*.json"))) == 1
    assert not (bundle / "manifest.json").exists()


def test_true_loso_rejects_filtered_return_input_mutation(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root, prereg, lock, _primary_bundle = _prepare_repo(tmp_path)
    primary_report = _write_primary_report(root)
    _install_run_mocks(monkeypatch, tmp_path)
    _install_loso_engine(monkeypatch, mutate_returns=True)
    bundle = root / program.CANONICAL_LOSO_BUNDLE_RELATIVE

    with pytest.raises(RuntimeError, match="excluded daily-return universe"):
        program.run_true_loso_replays(
            prereg,
            execution_lock_path=lock,
            primary_report_path=primary_report,
            bundle_dir=bundle,
            repo_root=root,
            primary_report_bytes=primary_report.stat().st_size,
            primary_report_sha256=program.sha256_file(primary_report),
        )
    assert not (bundle / "manifest.json").exists()


def test_true_loso_requires_cli_pinned_primary_report_identity(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root, prereg, lock, _primary_bundle = _prepare_repo(tmp_path)
    primary_report = _write_primary_report(root)
    trace = _install_run_mocks(monkeypatch, tmp_path)
    with pytest.raises(ValueError, match="CLI-pinned primary report"):
        program.run_true_loso_replays(
            prereg,
            execution_lock_path=lock,
            primary_report_path=primary_report,
            bundle_dir=root / program.CANONICAL_LOSO_BUNDLE_RELATIVE,
            repo_root=root,
        )
    assert trace["verify"] == []


def test_true_loso_rejects_forged_valid_cell_winner_by_manifest_recompute(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root, prereg, lock, _primary_bundle = _prepare_repo(tmp_path)
    primary_report = _write_primary_report(root, winner="C2_GRIMES_ONLY")
    trace = _install_run_mocks(monkeypatch, tmp_path)
    rebuilt = json.loads(primary_report.read_bytes())
    rebuilt["decision"]["locked_winner"] = "C1_VSA_ONLY"
    rebuilt["ranking"] = [{"candidate_id": "C1_VSA_ONLY", "rank": 1}]
    monkeypatch.setattr(
        program,
        "_rebuild_primary_report",
        lambda _manifest, *, prereg, root: rebuilt,
    )
    with pytest.raises(RuntimeError, match="does not deterministically derive"):
        program.run_true_loso_replays(
            prereg,
            execution_lock_path=lock,
            primary_report_path=primary_report,
            bundle_dir=root / program.CANONICAL_LOSO_BUNDLE_RELATIVE,
            repo_root=root,
            primary_report_bytes=primary_report.stat().st_size,
            primary_report_sha256=program.sha256_file(primary_report),
        )
    assert trace["verify"] == []
