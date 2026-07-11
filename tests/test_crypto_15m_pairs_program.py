from __future__ import annotations

import copy
import json
import platform
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import duckdb
import pandas as pd
import pytest
import yaml

from price_action.lab import crypto_15m_pairs_program as program

ROOT = Path(__file__).resolve().parents[1]
BASE_PREREG = ROOT / "configs" / "crypto_15m_v17_pairs_prereg.yaml"


def _base_config() -> dict:
    with BASE_PREREG.open(encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def _write_prereg(path: Path, config: dict) -> Path:
    path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    return path


def _temporary_cli_repo(tmp_path: Path) -> tuple[Path, Path, dict[str, Path]]:
    root = tmp_path / "isolated-repo"
    config = _base_config()
    prereg = root / "configs" / "crypto_15m_v17_pairs_prereg.yaml"
    prereg.parent.mkdir(parents=True)
    _write_prereg(prereg, config)

    lock = root / "requirements-lock.txt"
    lock.write_bytes((ROOT / "requirements-lock.txt").read_bytes())
    protected = {
        "preregistration": prereg,
        "source": root / "src/price_action/lab/crypto_15m_pairs_report.py",
        "market_snapshot": root / str(config["snapshots"]["market"]["path"]),
        "funding_snapshot": root / str(config["snapshots"]["funding"]["path"]),
        "v16_parent": root / str(config["batch1_parent_evidence"]["raw_result_gzip"]),
    }
    for name, path in protected.items():
        if name == "preregistration":
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(f"sentinel:{name}".encode())
    return root, prereg, protected


def _synthetic_portfolio_result(
    start: pd.Timestamp, end: pd.Timestamp
) -> program.PairPortfolioResult:
    return program.PairPortfolioResult(
        episodes=(),
        terminal_episodes=(),
        equity_curve=(
            (start.to_pydatetime(), 10_000.0),
            ((end - pd.Timedelta(minutes=15)).to_pydatetime(), 10_000.0),
        ),
        monthly_returns=(),
        rejections=(),
        initial_equity=10_000.0,
        final_equity=10_000.0,
        max_drawdown=0.0,
        total_execution_cost=0.0,
        accrued_exit_cost=0.0,
        total_funding_cashflow=0.0,
        open_pair_count=0,
        open_leg_count=0,
        quarantined_pairs=(),
        rejection_details=(),
    )


def _install_synthetic_full_run(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    mutation: str | None = None,
) -> dict[str, list]:
    config = _base_config()
    evaluation_start = pd.Timestamp(config["time_protocol"]["complete_months_utc"][0])
    evaluation_end = pd.Timestamp(config["time_protocol"]["complete_months_utc"][1])
    selection_ts = pd.Timestamp("2021-06-07T00:00:00Z").to_pydatetime()
    trace: dict[str, list] = {
        "verify": [],
        "source": [],
        "selector": [],
        "intents": [],
        "simulate": [],
    }

    def fake_verify(name: str, spec: dict, *, repo_root: Path) -> program.SnapshotVerification:
        del repo_root
        trace["verify"].append(name)
        postflight = len(trace["verify"]) > 2
        digest = str(spec["sha256"])
        if mutation == "snapshot" and postflight and name == "funding":
            digest = "f" * 64
        return program.SnapshotVerification(
            name=name,
            configured_path=str(spec["path"]),
            resolved_path=str(tmp_path / f"synthetic-{name}.duckdb"),
            bytes=int(spec["bytes"]),
            sha256=digest,
        )

    source_call_count = 0

    def fake_source(_repo_root: Path) -> dict:
        nonlocal source_call_count
        source_call_count += 1
        trace["source"].append(source_call_count)
        file_digest = "b" * 64
        if mutation == "source" and source_call_count >= 2:
            file_digest = "c" * 64
        return {
            "git_commit": "a" * 40,
            "research_source_clean": True,
            "research_source_status": [],
            "missing_source_files": [],
            "file_sha256": {"synthetic-research-source.py": file_digest},
        }

    def fake_market_loader(
        _path: Path,
        _spec: dict,
        *,
        symbols: tuple[str, ...],
        start: pd.Timestamp,
        end: pd.Timestamp,
    ) -> program.MarketBundle:
        assert start < evaluation_start < end
        frames = {
            symbol: pd.DataFrame(
                {
                    "ts": [evaluation_start],
                    "open": [100.0],
                    "high": [101.0],
                    "low": [99.0],
                    "close": [100.0],
                    "volume": [1.0],
                }
            )
            for symbol in symbols
        }
        return program.MarketBundle(
            frames=frames,
            rows_by_symbol={symbol: 1 for symbol in symbols},
            first_ts_by_symbol={symbol: evaluation_start for symbol in symbols},
            last_ts_by_symbol={symbol: evaluation_start for symbol in symbols},
        )

    def fake_funding_loader(
        _path: Path,
        _spec: dict,
        *,
        symbols: tuple[str, ...],
        venue: str,
        start: pd.Timestamp,
        engine_start: pd.Timestamp,
        end: pd.Timestamp,
    ) -> program.FundingBundle:
        assert venue == "binance"
        assert start < engine_start == evaluation_start < end
        return program.FundingBundle(
            signal_rates={
                symbol: pd.DataFrame(columns=["ts", "funding_rate"]) for symbol in symbols
            },
            engine_events=(),
            rows_by_symbol={symbol: 0 for symbol in symbols},
        )

    def fake_selector(
        _frames: dict[str, pd.DataFrame],
        _symbols: tuple[str, ...],
        cell: program.PairCell,
        **_kwargs,
    ) -> tuple[dict, dict]:
        trace["selector"].append(cell.candidate_id)
        return {selection_ts: ()}, {selection_ts: ()}

    def fake_intents(
        _frames: dict[str, pd.DataFrame],
        _funding: dict[str, pd.DataFrame],
        cell: program.PairCell,
        selections: dict,
        **_kwargs,
    ) -> tuple:
        assert selections == {selection_ts: ()}
        trace["intents"].append(cell.candidate_id)
        return ()

    def fake_simulate(
        _frames: dict[str, pd.DataFrame],
        intents: tuple,
        models: tuple,
        funding_events: tuple,
        cost: program.PairCostModel,
        _policy: program.PairPortfolioPolicy,
        *,
        selection_events: tuple[program.PairSelectionEvent, ...],
        positive_payoff_multiplier: float,
        negative_payoff_multiplier: float,
    ) -> program.PairPortfolioResult:
        assert intents == ()
        assert models == ()
        assert funding_events == ()
        assert len(selection_events) == 1
        event = selection_events[0]
        assert event.selection_ts == selection_ts
        assert event.selected_pair_ids == ()
        trace["simulate"].append(
            (
                event.candidate_id,
                cost.cost_multiplier,
                cost.funding_multiplier,
                positive_payoff_multiplier,
                negative_payoff_multiplier,
            )
        )
        return _synthetic_portfolio_result(evaluation_start, evaluation_end)

    monkeypatch.setattr(program, "verify_frozen_snapshot", fake_verify)
    monkeypatch.setattr(program, "_research_source_provenance", fake_source)
    monkeypatch.setattr(program, "load_market_snapshot", fake_market_loader)
    monkeypatch.setattr(program, "load_funding_snapshot", fake_funding_loader)
    monkeypatch.setattr(program, "select_pairs_monthly_with_diagnostics", fake_selector)
    monkeypatch.setattr(program, "generate_pair_entry_intents", fake_intents)
    monkeypatch.setattr(program, "simulate_pair_portfolio", fake_simulate)
    return trace


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("ETH", "ETH/USDT"),
        ("solusdt", "SOL/USDT"),
        ("BNB-USDT", "BNB/USDT"),
        ("ADA/USDT:USDT", "ADA/USDT"),
    ],
)
def test_normalize_usdt_symbol_accepts_bare_funding_symbols(raw: str, expected: str) -> None:
    assert program.normalize_usdt_symbol(raw) == expected


@pytest.mark.subprocess
def test_dry_and_smoke_do_not_access_configured_snapshots(tmp_path: Path) -> None:
    config = _base_config()
    config["snapshots"]["market"]["path"] = "missing-market.duckdb"
    config["snapshots"]["funding"]["path"] = "missing-funding.duckdb"
    prereg = _write_prereg(tmp_path / "prereg.yaml", config)

    dry = program.dry_run(prereg, repo_root=ROOT)
    smoke = program.smoke_run(prereg, repo_root=ROOT)

    assert dry["mode"] == "DRY_RUN_NO_SNAPSHOT_ACCESS"
    assert smoke["mode"] == "SMOKE_IN_MEMORY_NO_SNAPSHOT_ACCESS"
    assert dry["snapshots"]["market"]["status"] == "NOT_ACCESSED"
    assert smoke["snapshots"]["funding"]["status"] == "NOT_ACCESSED"
    assert smoke["smoke"]["closed_pair_episodes"] == 1
    assert smoke["smoke"]["terminal_open_pair_episodes"] == 0
    assert smoke["smoke"]["reference_symbol_traded"] is False


@pytest.mark.subprocess
def test_dry_run_binds_exact_critical_runtime_versions_and_report_sources() -> None:
    payload = program.dry_run(BASE_PREREG, repo_root=ROOT)
    locked = {}
    for raw_line in (ROOT / "requirements-lock.txt").read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if line and not line.startswith("#") and "==" in line:
            distribution, version = line.split("==", 1)
            locked[distribution.casefold()] = version

    assert payload["runtime_versions"] == {
        "python": platform.python_version(),
        "python_implementation": platform.python_implementation(),
        "duckdb": locked["duckdb"],
        "numpy": locked["numpy"],
        "pandas": locked["pandas"],
        "pyyaml": locked["pyyaml"],
        "scipy": locked["scipy"],
        "statsmodels": locked["statsmodels"],
    }

    required_sources = {
        "requirements-lock.txt",
        "scripts/research/crypto_15m_v17_pairs_report.py",
        "src/price_action/lab/crypto_15m_pairs_report.py",
    }
    provenance = payload["source_provenance"]
    assert required_sources <= set(program._FROZEN_SOURCE_FILES)
    assert required_sources <= set(provenance["file_sha256"])
    assert required_sources.isdisjoint(provenance["missing_source_files"])
    assert {relative: provenance["file_sha256"][relative] for relative in required_sources} == {
        relative: program.sha256_file(ROOT / relative) for relative in required_sources
    }


def test_cli_rejects_output_outside_reports_research_without_modifying_file(
    tmp_path: Path,
) -> None:
    root, prereg, _protected = _temporary_cli_repo(tmp_path)
    output = tmp_path / "outside.json"
    output.write_bytes(b"outside-sentinel")
    before = output.read_bytes()

    with pytest.raises(ValueError, match="under reports/research"):
        program.main(
            [
                "--dry-run",
                "--repo-root",
                str(root),
                "--prereg",
                str(prereg),
                "--output",
                str(output),
            ]
        )

    assert output.read_bytes() == before


def test_cli_rejects_overwriting_every_frozen_input_without_modifying_it(
    tmp_path: Path,
) -> None:
    root, prereg, protected = _temporary_cli_repo(tmp_path)

    for output in protected.values():
        before = output.read_bytes()
        with pytest.raises(ValueError, match="may not overwrite"):
            program.main(
                [
                    "--dry-run",
                    "--repo-root",
                    str(root),
                    "--prereg",
                    str(prereg),
                    "--output",
                    str(output),
                ]
            )
        assert output.read_bytes() == before


@pytest.mark.subprocess
def test_dry_cli_defaults_are_repo_anchored_outside_repo_cwd(tmp_path: Path) -> None:
    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/research/crypto_15m_v17_pairs_program.py"),
            "--dry-run",
        ],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )

    payload = json.loads(completed.stdout)
    assert payload["mode"] == "DRY_RUN_NO_SNAPSHOT_ACCESS"
    assert payload["preregistration"]["path"] == str(BASE_PREREG.resolve())
    assert payload["snapshots"]["market"]["status"] == "NOT_ACCESSED"
    assert payload["snapshots"]["funding"]["status"] == "NOT_ACCESSED"


def test_run_verifies_both_snapshots_before_first_database_loader(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    prereg = BASE_PREREG
    verified: list[str] = []

    def fake_verify(name: str, spec: dict, *, repo_root: Path) -> program.SnapshotVerification:
        del spec, repo_root
        verified.append(name)
        return program.SnapshotVerification(name, name, str(tmp_path / name), 1, "a" * 64)

    class LoaderReachedError(RuntimeError):
        pass

    def fake_market(*args, **kwargs):
        del args, kwargs
        assert verified == ["market", "funding"]
        raise LoaderReachedError

    monkeypatch.setattr(program, "verify_frozen_snapshot", fake_verify)
    monkeypatch.setattr(program, "load_market_snapshot", fake_market)
    monkeypatch.setattr(
        program,
        "_research_source_provenance",
        lambda _root: {
            "git_commit": "a" * 40,
            "research_source_clean": True,
            "research_source_status": [],
            "file_sha256": {},
        },
    )

    with pytest.raises(LoaderReachedError):
        program.run_program(prereg, repo_root=ROOT)


def test_holdout_partition_is_locked_before_snapshot_access(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    prereg = _write_prereg(tmp_path / "prereg.yaml", _base_config())

    def forbidden_verify(*args, **kwargs):
        del args, kwargs
        raise AssertionError("holdout lock must fail before snapshot verification")

    monkeypatch.setattr(program, "verify_frozen_snapshot", forbidden_verify)
    with pytest.raises(ValueError, match="holdout replay is locked"):
        program.run_program(prereg, repo_root=tmp_path, partition="holdout")


def test_execute_rejects_noncanonical_or_dirty_source_before_snapshot_access(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    modified = _base_config()
    modified["risk_and_execution"]["initial_equity"] = 9_999.0
    noncanonical = _write_prereg(tmp_path / "noncanonical.yaml", modified)

    def forbidden_verify(*args, **kwargs):
        del args, kwargs
        raise AssertionError("governance failure must happen before snapshot verification")

    monkeypatch.setattr(program, "verify_frozen_snapshot", forbidden_verify)
    with pytest.raises(ValueError, match="canonical repo"):
        program.run_program(noncanonical, repo_root=ROOT)

    monkeypatch.setattr(
        program,
        "_research_source_provenance",
        lambda _root: {
            "git_commit": "a" * 40,
            "research_source_clean": False,
            "research_source_status": [" M research.py"],
            "file_sha256": {},
        },
    )
    with pytest.raises(RuntimeError, match="clean research source"):
        program.run_program(BASE_PREREG, repo_root=ROOT)


def test_full_synthetic_run_preserves_governance_and_empty_selection_events(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    prereg = BASE_PREREG
    trace = _install_synthetic_full_run(monkeypatch, tmp_path)

    payload = program.run_program(prereg, repo_root=ROOT)

    candidate_ids = [cell["id"] for cell in _base_config()["candidate_cells"]]
    assert trace["verify"] == ["market", "funding", "market", "funding"]
    assert trace["source"] == [1, 2]
    assert trace["selector"] == candidate_ids
    assert trace["intents"] == candidate_ids
    assert trace["simulate"] == [
        scenario
        for candidate_id in candidate_ids
        for scenario in (
            (candidate_id, 1.0, 1.0, 1.0, 1.0),
            (candidate_id, 2.0, 2.0, 1.0, 1.0),
            (candidate_id, 1.0, 1.0, 0.5, 1.25),
        )
    ]
    assert len(trace["simulate"]) == 3 * len(program.SCENARIO_ORDER)

    assert payload["mode"] == "FULL_FROZEN_REPLAY"
    assert payload["evidence_eligible"] is True
    assert payload["evidence_ineligible_reasons"] == []
    governance = payload["execution_governance"]
    assert governance["canonical_prereg_semantic_match"] is True
    assert (
        governance["canonical_prereg_preflight_sha256"]
        == governance["canonical_prereg_postflight_sha256"]
    )
    assert governance["clean_source_preflight"] is True
    assert governance["source_unchanged_postflight"] is True
    assert governance["snapshots_reverified_postflight"] is True
    assert governance["snapshots_unchanged_postflight"] is True
    assert governance["preflight_source_file_sha256"] == governance["postflight_source_file_sha256"]
    assert set(payload["results"]) == set(candidate_ids)
    assert all(
        tuple(payload["results"][candidate_id]) == program.SCENARIO_ORDER
        for candidate_id in candidate_ids
    )
    expected_curve_ledger = [
        ["2021-06-01T00:00:00+00:00", 10_000.0],
        ["2026-05-31T23:45:00+00:00", 10_000.0],
    ]
    for candidate_id in candidate_ids:
        ledger = payload["streams"][candidate_id]["pair_selection_ledger"]
        assert len(ledger) == 1
        assert ledger[0]["selected_pair_ids"] == []
        assert ledger[0]["selected_models"] == []
        assert ledger[0]["pair_decisions"] == []
        for scenario_name in program.SCENARIO_ORDER:
            scenario = payload["results"][candidate_id][scenario_name]
            assert scenario["equity_curve_ledger"] == expected_curve_ledger
            assert scenario["equity_curve_observations"] == len(expected_curve_ledger)
            assert scenario["equity_curve_sha256"] == program._payload_sha256(expected_curve_ledger)

            complete = scenario["windows"]["complete"]
            nav_values = [row[1] for row in expected_curve_ledger]
            assert complete["equity_observations"] == len(nav_values)
            assert complete["nav_observation_sum"] == pytest.approx(sum(nav_values))
            assert complete["arithmetic_mean_15m_nav"] == pytest.approx(
                sum(nav_values) / len(nav_values)
            )
            assert complete["baseline_equity"] == pytest.approx(nav_values[0])
            assert complete["ending_equity"] == pytest.approx(nav_values[-1])


@pytest.mark.parametrize(
    ("mutation", "error"),
    [
        ("source", "research source changed during v17 replay"),
        ("snapshot", "a frozen snapshot changed during v17 replay"),
    ],
)
def test_full_synthetic_run_fails_closed_on_postflight_change(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
    error: str,
) -> None:
    prereg = BASE_PREREG
    trace = _install_synthetic_full_run(monkeypatch, tmp_path, mutation=mutation)

    with pytest.raises(RuntimeError, match=error):
        program.run_program(prereg, repo_root=ROOT)

    assert trace["verify"] == ["market", "funding", "market", "funding"]
    assert trace["source"] == [1, 2]
    assert len(trace["simulate"]) == 3 * len(program.SCENARIO_ORDER)


def test_market_loader_keeps_symbol_frames_independent(tmp_path: Path) -> None:
    path = tmp_path / "market.duckdb"
    timestamps = pd.date_range("2024-01-01T00:00:00Z", periods=3, freq="15min")
    rows = []
    for symbol in ("BTCUSDT", "ETHUSDT"):
        for index, timestamp in enumerate(timestamps):
            if symbol == "ETHUSDT" and index == 1:
                continue
            rows.append(
                (
                    "binance",
                    symbol,
                    "15m",
                    timestamp.to_pydatetime(),
                    100.0,
                    101.0,
                    99.0,
                    100.0,
                    1.0,
                )
            )
    connection = duckdb.connect(str(path))
    try:
        connection.execute(
            """
            CREATE TABLE ohlcv (
                venue VARCHAR, symbol VARCHAR, timeframe VARCHAR, ts TIMESTAMPTZ,
                open DOUBLE, high DOUBLE, low DOUBLE, close DOUBLE, volume DOUBLE
            )
            """
        )
        connection.executemany("INSERT INTO ohlcv VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)
    finally:
        connection.close()

    bundle = program.load_market_snapshot(
        path,
        {"table": "ohlcv", "venue": "binance", "timeframe": "15m"},
        symbols=("BTC/USDT", "ETH/USDT"),
        start=timestamps[0],
        end=timestamps[-1] + pd.Timedelta(minutes=15),
    )

    assert bundle.rows_by_symbol == {"BTC/USDT": 3, "ETH/USDT": 2}
    assert list(bundle.frames["BTC/USDT"]["ts"]) == list(timestamps)
    assert list(bundle.frames["ETH/USDT"]["ts"]) == [timestamps[0], timestamps[2]]


def test_funding_loader_canonicalizes_bare_symbols_preserves_fraction_and_nulls_marks(
    tmp_path: Path,
) -> None:
    path = tmp_path / "funding.duckdb"
    first = datetime(2024, 1, 1, 0, 0, 0, 500_000, tzinfo=UTC)
    second = datetime(2024, 1, 1, 8, 0, 0, 750_000, tzinfo=UTC)
    connection = duckdb.connect(str(path))
    try:
        connection.execute(
            """
            CREATE TABLE funding_rates (
                venue VARCHAR, symbol VARCHAR, ts TIMESTAMPTZ,
                funding_rate DOUBLE, mark_price DOUBLE
            )
            """
        )
        connection.executemany(
            "INSERT INTO funding_rates VALUES (?, ?, ?, ?, ?)",
            [
                ("binance", "ETH", first, 0.0001, None),
                ("binance", "ETH", second, 0.0002, -1.0),
                ("binance", "SOL", first, -0.0001, 123.0),
                ("binance", "SOL", second, -0.0002, float("nan")),
            ],
        )
    finally:
        connection.close()

    bundle = program.load_funding_snapshot(
        path,
        {"table": "funding_rates"},
        symbols=("ETH/USDT", "SOL/USDT"),
        venue="binance",
        start=pd.Timestamp("2024-01-01T00:00:00Z"),
        engine_start=pd.Timestamp("2024-01-01T00:00:00Z"),
        end=pd.Timestamp("2024-01-02T00:00:00Z"),
    )

    assert set(bundle.signal_rates) == {"ETH/USDT", "SOL/USDT"}
    assert bundle.engine_events[0]["ts"].microsecond == 500_000
    marks = {(event["symbol"], event["ts"]): event["mark_price"] for event in bundle.engine_events}
    assert marks[("ETH/USDT", first)] is None
    assert marks[("ETH/USDT", second)] is None
    assert marks[("SOL/USDT", first)] == pytest.approx(123.0)
    assert marks[("SOL/USDT", second)] is None


def test_scenario_models_bind_b_c2_h_cost_and_payoff_contract() -> None:
    scenarios = program._scenario_models(_base_config())

    assert tuple(scenarios) == program.SCENARIO_ORDER
    assert scenarios["B"][0].cost_multiplier == pytest.approx(1.0)
    assert scenarios["B"][0].funding_multiplier == pytest.approx(1.0)
    assert scenarios["C2"][0].cost_multiplier == pytest.approx(2.0)
    assert scenarios["C2"][0].funding_multiplier == pytest.approx(2.0)
    assert scenarios["H"][1:] == pytest.approx((0.5, 1.25))


@pytest.mark.subprocess
def test_deterministic_json_is_strict_and_repeatable(tmp_path: Path) -> None:
    prereg = _write_prereg(tmp_path / "prereg.yaml", copy.deepcopy(_base_config()))
    payload = program.dry_run(prereg, repo_root=ROOT)

    first = program.deterministic_json(payload)
    second = program.deterministic_json(payload)

    assert first == second
    assert json.loads(first)["schema_version"] == program.PROGRAM_SCHEMA
    assert "NaN" not in first
    assert "Infinity" not in first
    with pytest.raises(ValueError):
        program.deterministic_json({"bad": float("nan")})


@pytest.mark.subprocess
def test_streamed_json_writer_is_byte_identical_and_atomic_for_dry_and_curve_payloads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    prereg = _write_prereg(tmp_path / "prereg.yaml", copy.deepcopy(_base_config()))
    dry_payload = program.dry_run(prereg, repo_root=ROOT)
    start = pd.Timestamp("2024-01-01T00:00:00Z")
    end = pd.Timestamp("2024-01-01T00:30:00Z")
    curve_payload = {
        "mode": "SYNTHETIC_CURVE",
        "scenario": program._scenario_payload(
            _synthetic_portfolio_result(start, end),
            windows={"complete": (start, end)},
        ),
    }

    real_link = program.os.link
    link_calls: list[tuple[Path, Path]] = []

    def recording_link(source: str, destination: Path) -> None:
        source_path = Path(source)
        destination_path = Path(destination)
        assert source_path.exists()
        assert source_path.parent == destination_path.parent
        assert source_path.name.startswith(f".{destination_path.name}.")
        assert source_path.suffix == ".tmp"
        assert not destination_path.exists()
        link_calls.append((source_path, destination_path))
        real_link(source, destination)

    monkeypatch.setattr(program.os, "link", recording_link)
    for index, payload in enumerate((dry_payload, curve_payload)):
        output = tmp_path / f"payload-{index}.json"
        program._write_deterministic_json_file(output, payload)

        assert output.read_bytes() == program.deterministic_json(payload).encode()
        assert not list(tmp_path.glob(f".{output.name}.*.tmp"))

    assert [destination for _source, destination in link_calls] == [
        tmp_path / "payload-0.json",
        tmp_path / "payload-1.json",
    ]


def test_existing_output_is_rejected_before_expensive_execute(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, prereg, _protected = _temporary_cli_repo(tmp_path)
    output = root / "reports/research/already-exists.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(b"existing-result-sentinel")
    run_calls: list[Path] = []

    def forbidden_run(prereg_path: Path, **_kwargs) -> dict:
        run_calls.append(prereg_path)
        raise AssertionError("existing output must fail before the frozen replay")

    monkeypatch.setattr(program, "run_program", forbidden_run)
    with pytest.raises(FileExistsError, match="already exists"):
        program.main(
            [
                "--execute",
                "--repo-root",
                str(root),
                "--prereg",
                str(prereg),
                "--output",
                str(output),
            ]
        )

    assert run_calls == []
    assert output.read_bytes() == b"existing-result-sentinel"
