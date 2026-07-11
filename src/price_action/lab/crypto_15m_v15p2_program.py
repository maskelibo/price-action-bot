"""Audit-grade frozen-data runner for the v15p2 fair baseline.

The runner is intentionally a narrow IO boundary around the pure signal and
portfolio modules.  Execute mode is locked to the canonical preregistration,
requires a clean scoped source tree, verifies both immutable DuckDB snapshots
before either can be opened, and repeats every provenance check after replay.

``dry_plan`` performs schema, policy, scenario, runtime, and source inspection
without resolving, stat-ing, hashing, or opening either configured snapshot.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import platform
import re
import subprocess
import tempfile
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import asdict, fields, is_dataclass
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as package_version
from itertools import pairwise
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml
from yaml.constructor import ConstructorError

# Evidence CLI output must remain machine-readable, and a research replay must
# not create unrelated runtime log files as an import side effect.
os.environ["PA_LOG_QUIET"] = "1"
os.environ["PA_DISABLE_FILE_LOG"] = "1"
os.environ["PA_TESTING"] = "1"

from price_action.lab.crypto_15m_snapshot_io import (
    FundingBundle,
    MarketBundle,
    SnapshotVerification,
    load_funding_snapshot,
    load_market_snapshot,
    sha256_file,
    verify_frozen_snapshot,
)
from price_action.lab.crypto_15m_v15p2_engine import (
    V15P2CostScenario,
    V15P2PortfolioPolicy,
    V15P2PortfolioResult,
    run_v15p2_engine,
)
from price_action.lab.crypto_15m_v15p2_signals import (
    EXPECTED_CONFIG_SHA256,
    FAIR_BASELINE_CANDIDATE_ID,
    generate_v15p2_signal_batch,
)

PROGRAM_SCHEMA = "crypto-15m-v15p2-fair-baseline-run-v2"
PREREG_SCHEMA = "crypto-15m-v15p2-fair-baseline-prereg-v2"
FROZEN_STATUS = "PREREGISTERED_NO_RESULTS_SEEN"
SCENARIO_ORDER = ("B", "C2", "H")
CANONICAL_PREREG_RELATIVE = "configs/crypto_15m_v15p2_fair_baseline_v2_prereg.yaml"
CANONICAL_CONFIG_RELATIVE = "configs/risk_phoenix_scalp_15m_v15p2.yaml"
PRIMARY_SYMBOLS = (
    "ETH/USDT",
    "SOL/USDT",
    "BNB/USDT",
    "ADA/USDT",
    "AVAX/USDT",
    "LINK/USDT",
    "DOT/USDT",
    "DOGE/USDT",
    "ZEC/USDT",
    "NEAR/USDT",
    "FIL/USDT",
    "ATOM/USDT",
    "ALGO/USDT",
)
REFERENCE_SYMBOL = "BTC/USDT"
HOLDOUT_SYMBOLS = ("XLM/USDT", "AAVE/USDT", "TRX/USDT", "XRP/USDT")
HISTORY_START = pd.Timestamp("2021-02-21T00:00:00Z")
EVALUATION_START = pd.Timestamp("2021-06-01T00:00:00Z")
EVALUATION_END = pd.Timestamp("2026-06-01T00:00:00Z")
DEVELOPMENT_END = pd.Timestamp("2023-06-01T00:00:00Z")
_EXPECTED_FOLDS = tuple(
    (
        pd.Timestamp(start),
        pd.Timestamp(end),
    )
    for start, end in (
        ("2023-06-01T00:00:00Z", "2023-12-01T00:00:00Z"),
        ("2023-12-01T00:00:00Z", "2024-06-01T00:00:00Z"),
        ("2024-06-01T00:00:00Z", "2024-12-01T00:00:00Z"),
        ("2024-12-01T00:00:00Z", "2025-06-01T00:00:00Z"),
        ("2025-06-01T00:00:00Z", "2025-12-01T00:00:00Z"),
        ("2025-12-01T00:00:00Z", "2026-06-01T00:00:00Z"),
    )
)
_BAR = pd.Timedelta(minutes=15)
_SHA256 = re.compile(r"^[0-9a-f]{64}$")

_EXPECTED_LINEAGE_IDENTITIES = {
    "predecessor_preregistration": {
        "path": "configs/crypto_15m_v15p2_fair_baseline_prereg.yaml",
        "bytes": 33_623,
        "sha256": "695fb5b7a07fc0bb54c0a69b10f0893d246926a4339a17b5e8705802800f9c22",
    },
    "predecessor_coverage_failure": {
        "path": "configs/crypto_15m_v15p2_fair_baseline_v1_coverage_failure.json",
        "bytes": 3_073,
        "sha256": "34a844100497bab4ee6edc6cba5efea26bdf6d9ce7278bf384a86fb9d58fab76",
    },
    "predecessor_coverage_failure_supplement": {
        "path": (
            "configs/crypto_15m_v15p2_fair_baseline_v1_coverage_failure_"
            "supplemental_attestation.json"
        ),
        "bytes": 15_550,
        "sha256": "1254512f1238f1e4bc3a58d0b2331ffad6d5c3e2f995c42d138aa998562c2e03",
    },
    "v2_coverage_diagnosis": {
        "path": "configs/crypto_15m_v15p2_usdm_snapshot_v2_coverage_diagnosis.json",
        "bytes": 8_036,
        "sha256": "b2a50fdb00c055aef8ec09b1c81e662160917878ac797b2dae966e661b745e91",
    },
    "v3_protocol": {
        "path": "configs/crypto_15m_v15p2_usdm_snapshot_v3_build_protocol.json",
        "bytes": 8_125,
        "sha256": "e6995f2fa22158d9133b9d3a45caeb0ba3de01ad70e77239d99bb13331bef3c8",
    },
    "v3_reservation": {
        "path": "configs/crypto_15m_v15p2_usdm_snapshot_v3_build_attempt_001_started.json",
        "bytes": 1_387,
        "sha256": "5c28272dc96d6e14eb471a37e8b4e7bd97cee3983f22c62e5c6e4cf6241ae404",
    },
    "v3_success_identity": {
        "path": (
            "configs/crypto_15m_v15p2_usdm_snapshot_v3_build_attempt_001_success_identity.json"
        ),
        "bytes": 14_258,
        "sha256": "8e73f05d87106ea9df635e3ae0d3996ec5679da48f83bff77856b065059972d3",
    },
    "v3_build_evidence": {
        "path": "data/backups/20260711_v15p2_v3_usdm/build_evidence.json",
        "bytes": 1_095_568,
        "sha256": "1ac74ceb61c197fad4bc27783eadaed4e88504e3a751257d8c735bc9eece9b34",
    },
    "v3_market_database": {
        "path": "data/backups/20260711_v15p2_v3_usdm/market.duckdb",
        "bytes": 181_415_936,
        "sha256": "50e5b240e6babeb3b7ceadc0ae007ededc0ae589cba931e3603d233cec693eb8",
    },
}
_LINEAGE_FILES_VERIFIED_SEPARATELY = tuple(
    key for key in _EXPECTED_LINEAGE_IDENTITIES if key != "v3_market_database"
)
_EXPECTED_FUNDING_IDENTITY = {
    "path": "data/backups/20260711/funding.duckdb",
    "bytes": 17_575_936,
    "sha256": "35be9ebae8f9468a6bae819054008cb4c2338ae0eb923910584dea1adc0c6b96",
}
_FUNDING_LINEAGE_LIMITATION = "funding_snapshot_not_rebuilt_under_v3_vendor_lineage"


class _UniqueKeyLoader(yaml.SafeLoader):
    """Safe YAML loader that rejects shadowed keys at every mapping depth."""


def _construct_unique_mapping(
    loader: _UniqueKeyLoader, node: yaml.MappingNode, deep: bool = False
) -> dict[Any, Any]:
    mapping: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        try:
            duplicate = key in mapping
        except TypeError as exc:
            raise ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                "found an unhashable mapping key",
                key_node.start_mark,
            ) from exc
        if duplicate:
            raise ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                f"found duplicate key {key!r}",
                key_node.start_mark,
            )
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


_UniqueKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_unique_mapping,
)

_REFERENCE_SOURCE_KEYS = (
    "config",
    "wrapper",
    "wrapper_patch_source",
    "daemon",
    "scanner",
    "canonical_protection_orders",
    "live_account_adapter",
    "classic_strategy_indicators",
    "signal_contracts_and_stable_hash",
    "strategy_base",
    "strategy_manifest_loader",
    "vsa_strategy",
    "vsa_15m_overlay",
    "grimes_strategy",
    "risk_sizing",
    "risk_gates",
    "stop_distance_normalizer",
    "breaker",
    "realized_breaker_ledger",
)
_RUNNER_SOURCE_FILES = (
    CANONICAL_PREREG_RELATIVE,
    "configs/crypto_15m_v15p2_fair_baseline_prereg.yaml",
    "configs/crypto_15m_v15p2_fair_baseline_v1_coverage_failure.json",
    ("configs/crypto_15m_v15p2_fair_baseline_v1_coverage_failure_supplemental_attestation.json"),
    "configs/crypto_15m_v15p2_usdm_snapshot_v2_coverage_diagnosis.json",
    "configs/crypto_15m_v15p2_usdm_snapshot_v3_build_protocol.json",
    "configs/crypto_15m_v15p2_usdm_snapshot_v3_build_attempt_001_started.json",
    ("configs/crypto_15m_v15p2_usdm_snapshot_v3_build_attempt_001_success_identity.json"),
    "docs/CRYPTO_15M_V15P2_FAIR_BASELINE_PREREG_2026-07-11.md",
    "docs/CRYPTO_15M_V15P2_FAIR_BASELINE_V2_PREREG_2026-07-11.md",
    "requirements-lock.txt",
    "src/price_action/__init__.py",
    "src/price_action/lab/__init__.py",
    "src/price_action/strategies/__init__.py",
    "src/price_action/logging_config.py",
    "src/price_action/settings.py",
    "src/price_action/runtime_paths.py",
    "src/price_action/lab/crypto_15m_v15p2_engine.py",
    "src/price_action/lab/crypto_15m_v15p2_program.py",
    "src/price_action/lab/crypto_15m_snapshot_io.py",
    "src/price_action/lab/crypto_15m_v15p2_report.py",
    "src/price_action/lab/crypto_15m_v15p2_signals.py",
    "src/price_action/strategies/classic_pa.py",
    "src/price_action/contracts.py",
    "tests/test_crypto_15m_snapshot_io.py",
    "tests/test_crypto_15m_v15p2_engine.py",
    "tests/test_crypto_15m_v15p2_program.py",
    "tests/test_crypto_15m_v15p2_report.py",
    "tests/test_crypto_15m_v15p2_signals.py",
    "tests/execution/test_sec58_duckdb_conflict_fix.py",
    "tests/execution/test_sec58_medium_batch.py",
    "tests/risk/test_consecutive_loss_counter.py",
    "tests/risk/test_monthly_breaker_journal_feed.py",
    "tests/test_corr_matrix_syms_a1_04.py",
    "tests/test_risk.py",
)
_CRITICAL_RUNTIME_DISTRIBUTIONS = {
    "duckdb": "duckdb",
    "loguru": "loguru",
    "numba": "numba",
    "numpy": "numpy",
    "pandas": "pandas",
    "pydantic": "pydantic",
    "pydantic_settings": "pydantic-settings",
    "python_dotenv": "python-dotenv",
    "pyyaml": "PyYAML",
    "scipy": "scipy",
    "statsmodels": "statsmodels",
}


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be a mapping")
    return value


def _number(value: Any, label: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{label} must be numeric")
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be numeric") from exc
    if not math.isfinite(parsed):
        raise ValueError(f"{label} must be finite")
    return parsed


def _integer(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{label} must be an integer")
    return value


def _expect(actual: Any, expected: Any, label: str) -> None:
    if actual != expected:
        raise ValueError(f"{label} must remain {expected!r}; got {actual!r}")


def _pct(value: Any, label: str) -> float:
    return _number(value, label) / 100.0


def _window(value: Any, label: str) -> tuple[pd.Timestamp, pd.Timestamp]:
    if not isinstance(value, list) or len(value) != 2:
        raise ValueError(f"{label} must be a two-element list")
    start = _utc(value[0], f"{label} start")
    end = _utc(value[1], f"{label} end")
    if start >= end:
        raise ValueError(f"{label} must be increasing")
    return start, end


def _utc(value: Any, label: str) -> pd.Timestamp:
    try:
        stamp = pd.Timestamp(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} is not a timestamp") from exc
    if stamp.tzinfo is None:
        raise ValueError(f"{label} must be timezone-aware UTC")
    stamp = stamp.tz_convert(UTC)
    return stamp


def _jsonable(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return _jsonable(asdict(value))
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, tuple | list | set | frozenset):
        items = sorted(value) if isinstance(value, set | frozenset) else value
        return [_jsonable(item) for item in items]
    if isinstance(value, datetime | pd.Timestamp):
        stamp = pd.Timestamp(value)
        if stamp.tzinfo is None:
            raise ValueError("evidence timestamps must be timezone-aware")
        return stamp.tz_convert(UTC).isoformat()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, np.generic):
        return value.item()
    return value


def _payload_sha256(value: Any) -> str:
    encoded = json.dumps(
        _jsonable(value), sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _dataframe_sha256(frame: pd.DataFrame) -> str:
    """Pinned-runtime content fingerprint used only for mutation detection."""

    digest = hashlib.sha256()
    digest.update(json.dumps([str(column) for column in frame.columns]).encode())
    digest.update(json.dumps([str(dtype) for dtype in frame.dtypes]).encode())
    digest.update(pd.util.hash_pandas_object(frame, index=True).to_numpy().tobytes())
    return digest.hexdigest()


def _critical_runtime_versions(repo_root: Path) -> dict[str, str]:
    lock_path = repo_root / "requirements-lock.txt"
    if not lock_path.is_file():
        raise RuntimeError("requirements-lock.txt is required for baseline replay")
    locked: dict[str, str] = {}
    for raw_line in lock_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "==" not in line:
            continue
        distribution, pinned = line.split("==", 1)
        locked[distribution.strip().casefold()] = pinned.strip()
    result = {
        "python": platform.python_version(),
        "python_implementation": platform.python_implementation(),
        "requirements_lock_sha256": sha256_file(lock_path),
    }
    for label, distribution in _CRITICAL_RUNTIME_DISTRIBUTIONS.items():
        expected = locked.get(distribution.casefold())
        if expected is None:
            raise RuntimeError(f"{distribution} must be exactly pinned in requirements-lock.txt")
        try:
            installed = package_version(distribution)
        except PackageNotFoundError as exc:
            raise RuntimeError(f"critical package is not installed: {distribution}") from exc
        if installed != expected:
            raise RuntimeError(
                f"critical runtime mismatch for {distribution}: "
                f"installed={installed}, locked={expected}"
            )
        result[label] = installed
    return result


def load_preregistration(path: Path) -> dict[str, Any]:
    """Load and fail-closed validate the frozen v15p2 control contract."""

    try:
        loaded = yaml.load(path.read_bytes(), Loader=_UniqueKeyLoader)
    except OSError as exc:
        raise ValueError(f"cannot read preregistration: {path}") from exc
    except yaml.YAMLError as exc:
        raise ValueError("preregistration is not valid YAML") from exc
    if not isinstance(loaded, dict):
        raise ValueError("preregistration must be a YAML mapping")
    _expect(loaded.get("schema_version"), PREREG_SCHEMA, "schema_version")
    _expect(loaded.get("status"), FROZEN_STATUS, "status")
    _expect(loaded.get("live_deployment_authorized"), False, "live_deployment_authorized")
    _expect(loaded.get("promotion_eligible"), False, "promotion_eligible")
    _expect(
        loaded.get("snapshot_replay_performed_by_this_change"),
        False,
        "snapshot_replay_performed_by_this_change",
    )

    purpose = _mapping(loaded.get("purpose"), "purpose")
    _expect(purpose.get("strategy_classification"), "FAIR_LIVE_POLICY_PROXY", "strategy class")
    _expect(
        purpose.get("execution_classification"),
        "NEXT_OPEN_BAR_EXECUTION_PROXY",
        "execution class",
    )
    _expect(purpose.get("one_fixed_control_only"), True, "one_fixed_control_only")
    _expect(purpose.get("alpha_trial_count"), 0, "alpha_trial_count")
    _expect(purpose.get("successor_data_identity_only"), True, "successor data identity")
    _expect(
        purpose.get("strategy_signal_engine_execution_cost_risk_report_policy_changed"),
        False,
        "successor policy-change gate",
    )

    lineage = _mapping(loaded.get("predecessor_and_v3_lineage"), "predecessor_and_v3_lineage")
    expected_lineage_fields = {
        *_EXPECTED_LINEAGE_IDENTITIES,
        "predecessor_files_preserved_unchanged",
        "predecessor_attempt_produced_performance_result",
        "predecessor_and_successor_alpha_result_trials",
        "verify_every_identity_before_any_database_open",
        "verify_every_identity_again_after_replay",
    }
    _expect(set(lineage), expected_lineage_fields, "lineage fields")
    for name, expected in _EXPECTED_LINEAGE_IDENTITIES.items():
        spec = _mapping(lineage.get(name), f"predecessor_and_v3_lineage.{name}")
        _expect(dict(spec), expected, f"predecessor_and_v3_lineage.{name}")
    _expect(
        lineage.get("predecessor_files_preserved_unchanged"),
        True,
        "predecessor preservation",
    )
    _expect(
        lineage.get("predecessor_attempt_produced_performance_result"),
        False,
        "predecessor performance-result disclosure",
    )
    _expect(
        lineage.get("predecessor_and_successor_alpha_result_trials"),
        0,
        "successor alpha-result trials",
    )
    _expect(
        lineage.get("verify_every_identity_before_any_database_open"),
        True,
        "lineage preflight gate",
    )
    _expect(
        lineage.get("verify_every_identity_again_after_replay"),
        True,
        "lineage postflight gate",
    )

    snapshots = _mapping(loaded.get("snapshots"), "snapshots")
    _expect(snapshots.get("mutable_live_databases_forbidden"), True, "mutable DB gate")
    _expect(
        snapshots.get("verify_size_and_sha256_before_any_database_open"),
        True,
        "snapshot preflight gate",
    )
    _expect(
        snapshots.get("verify_size_and_sha256_again_after_replay"),
        True,
        "snapshot postflight gate",
    )
    for name in ("market", "funding"):
        spec = _mapping(snapshots.get(name), f"snapshots.{name}")
        digest = str(spec.get("sha256", "")).lower()
        if not _SHA256.fullmatch(digest):
            raise ValueError(f"snapshots.{name}.sha256 is invalid")
        size = spec.get("bytes")
        if isinstance(size, bool) or not isinstance(size, int) or size <= 0:
            raise ValueError(f"snapshots.{name}.bytes must be an integer > 0")
    market_spec = _mapping(snapshots["market"], "snapshots.market")
    expected_market = _EXPECTED_LINEAGE_IDENTITIES["v3_market_database"]
    for key in ("path", "bytes", "sha256"):
        _expect(market_spec.get(key), expected_market[key], f"V3 market snapshot {key}")
    _expect(market_spec.get("table"), "ohlcv", "V3 market snapshot table")
    _expect(market_spec.get("venue"), "binance", "V3 market snapshot venue")
    _expect(market_spec.get("timeframe"), "15m", "V3 market snapshot timeframe")
    funding_spec = _mapping(snapshots["funding"], "snapshots.funding")
    for key, expected in _EXPECTED_FUNDING_IDENTITY.items():
        _expect(funding_spec.get(key), expected, f"funding snapshot {key}")
    _expect(funding_spec.get("table"), "funding_rates", "funding snapshot table")

    funding_disclosure = _mapping(
        loaded.get("funding_source_disclosure"), "funding_source_disclosure"
    )
    expected_funding_disclosure = {
        "identity_inherited_unchanged_from_v1": True,
        "built_or_modified_by_v3_market_snapshot_process": False,
        "covered_by_v3_vendor_lock_or_market_build_evidence": False,
        "independent_frozen_file_identity_required_preflight_and_postflight": True,
        "database_connection_must_be_read_only": True,
        "source_classification": "LEGACY_FROZEN_OBSERVED_FUNDING_SNAPSHOT",
        "venue": "binance",
        "table": "funding_rates",
        "primary13_rows_are_loaded_only_after_market_coverage_validation": True,
        "raw_fractional_event_timestamps_are_preserved": True,
        "historical_source_reconstruction_or_vendor_checksum_lineage_claim_allowed": False,
        "limitation_required_in_every_result": _FUNDING_LINEAGE_LIMITATION,
        "pre_prereg_coverage_only_access": {
            "database_opened": True,
            "connection_mode": "read_only",
            "exact_access_timestamp_available": False,
            "query_scope": "schema_count_min_max_duplicate_and_nonfinite_aggregates_only",
            "evaluation_window_start_inclusive_utc": "2021-06-01T00:00:00Z",
            "evaluation_window_end_exclusive_utc": "2026-06-01T00:00:00Z",
            "primary13_rows": 71_289,
            "first_event_ts_utc": "2021-06-01T00:00:00.001Z",
            "last_event_ts_utc": "2026-05-31T16:00:00.004Z",
            "duplicate_symbol_timestamp_rows": 0,
            "nonfinite_funding_rate_rows": 0,
            "mark_price_fallback_needed_rows": 34_486,
            "individual_funding_rate_or_mark_values_seen": False,
            "signals_trades_returns_ROI_drawdown_monthly_metrics_or_scenarios_seen": False,
            "funding_completeness_claimed": False,
            "values_used_for_strategy_threshold_universe_execution_risk_or_deployment_choice": (
                False
            ),
        },
    }
    _expect(dict(funding_disclosure), expected_funding_disclosure, "funding disclosure")

    universe = _mapping(loaded.get("universe"), "universe")
    _expect(universe.get("tradable_partition"), "primary13_only", "tradable partition")
    _expect(tuple(universe.get("primary_symbols", ())), PRIMARY_SYMBOLS, "primary symbols")
    _expect(universe.get("non_traded_reference_symbol"), REFERENCE_SYMBOL, "reference symbol")
    _expect(
        tuple(universe.get("holdout_symbols_forbidden", ())),
        HOLDOUT_SYMBOLS,
        "forbidden holdout symbols",
    )
    _expect(
        universe.get("holdout_feature_or_trade_access_forbidden"),
        True,
        "holdout access gate",
    )

    protocol = _mapping(loaded.get("time_protocol"), "time_protocol")
    _expect(
        _window(protocol.get("complete_months_utc"), "complete_months_utc"),
        (EVALUATION_START, EVALUATION_END),
        "complete window",
    )
    _expect(
        _window(protocol.get("development"), "development"),
        (EVALUATION_START, DEVELOPMENT_END),
        "development window",
    )
    _expect(
        _window(protocol.get("pseudo_oos"), "pseudo_oos"),
        (DEVELOPMENT_END, EVALUATION_END),
        "pseudo-OOS window",
    )
    raw_folds = protocol.get("expanding_walk_forward")
    if not isinstance(raw_folds, list):
        raise ValueError("expanding_walk_forward must be a list")
    folds = tuple(_window(value, f"fold {index + 1}") for index, value in enumerate(raw_folds))
    _expect(folds, _EXPECTED_FOLDS, "six frozen walk-forward folds")
    _expect(protocol.get("development_months"), 24, "development months")
    _expect(protocol.get("pseudo_oos_months"), 36, "pseudo-OOS months")
    _expect(protocol.get("folds"), 6, "fold count")
    _expect(protocol.get("fold_months"), 6, "fold months")
    _expect(
        protocol.get("interval_semantics"),
        "half_open_start_inclusive_end_exclusive",
        "interval semantics",
    )
    _expect(protocol.get("one_continuous_replay_per_cost_scenario"), True, "continuous replay")
    _expect(protocol.get("state_or_capital_reset_at_month_or_fold_boundary"), False, "reset gate")

    evidence = _mapping(loaded.get("evidence_contract"), "evidence_contract")
    _expect(evidence.get("pseudo_oos_H_months_must_equal"), 36, "evidence OOS months")
    _expect(
        evidence.get("fold_months_must_equal"),
        [6, 6, 6, 6, 6, 6],
        "evidence fold lengths",
    )

    improvement = _mapping(
        loaded.get("fair_improvement_rules_frozen_from_v16"), "fair improvement rules"
    )
    _expect(improvement.get("comparison_scenario"), "H", "comparison scenario")
    _expect(
        improvement.get("same_snapshot_universe_period_execution_costs_and_metric_code_required"),
        True,
        "fair comparison identity gate",
    )
    _expect(
        improvement.get("absolute_challenger_hard_gates_still_required"),
        True,
        "challenger hard-gate requirement",
    )
    _expect(
        improvement.get("pass_logic"),
        "rule_1_or_rule_2_and_stability_noninferiority",
        "fair improvement pass logic",
    )
    rule_1 = _mapping(improvement.get("rule_1"), "fair improvement rule 1")
    _expect(
        rule_1.get("challenger_H_trimmed_mean_monthly_return_pct_min_formula"),
        "max_10pct_or_baseline_plus_1p5pp",
        "rule 1 return formula",
    )
    _expect(
        _number(
            rule_1.get("challenger_H_max_MTM_drawdown_may_be_at_most_pp_worse"),
            "rule 1 drawdown tolerance",
        ),
        1.0,
        "rule 1 drawdown tolerance",
    )
    rule_2 = _mapping(improvement.get("rule_2"), "fair improvement rule 2")
    _expect(
        _number(
            rule_2.get("challenger_H_trimmed_mean_monthly_return_must_be_within_pp_of_baseline"),
            "rule 2 return tolerance",
        ),
        1.0,
        "rule 2 return tolerance",
    )
    _expect(
        _number(
            rule_2.get("challenger_H_max_MTM_drawdown_reduction_vs_baseline_min_fraction"),
            "rule 2 drawdown reduction",
        ),
        0.25,
        "rule 2 drawdown reduction",
    )
    stability = _mapping(improvement.get("stability_noninferiority"), "stability noninferiority")
    _expect(
        stability.get("challenger_H_negative_month_count_may_not_be_worse"),
        True,
        "negative-month noninferiority",
    )
    _expect(
        stability.get("challenger_H_worst_month_may_not_be_worse"),
        True,
        "worst-month noninferiority",
    )
    labels = _mapping(improvement.get("exact_legacy_rule_labels"), "legacy rule labels")
    _expect(
        labels.get("better_rule_1"),
        "H_trimmed_return_at_least_max_10pct_or_v15p2_plus_1p5pp_and_DD_no_more_than_1pp_worse",
        "rule 1 exact label",
    )
    _expect(
        labels.get("better_rule_2"),
        "H_return_within_1pp_of_v15p2_and_DD_at_least_25pct_lower",
        "rule 2 exact label",
    )
    _expect(
        labels.get("negative_months_and_worst_month_may_not_be_worse"),
        True,
        "stability exact label",
    )
    _expect(
        improvement.get("old_21p36_headline_may_not_substitute_for_this_baseline"),
        True,
        "legacy headline exclusion",
    )

    gaps = _mapping(loaded.get("data_and_gap_contract"), "data_and_gap_contract")
    _expect(gaps.get("v3_exact_primary_key_rows"), 2_586_624, "V3 primary-key rows")
    _expect(gaps.get("v3_exact_missing_vendor_bars"), 1_920, "V3 missing vendor bars")
    _expect(
        gaps.get("v3_exact_missing_vendor_key_sha256"),
        "bfd80250c7ae2b5b242f80b2170c47c872b771100f88b7e1ed64d0eaad29287d",
        "V3 missing-key identity",
    )
    _expect(
        gaps.get("synthetic_forward_filled_interpolated_or_resampled_rows"),
        0,
        "V3 synthetic-row count",
    )
    expected_gaps = [
        {
            "start_inclusive_utc": "2022-02-26T00:00:00Z",
            "end_exclusive_utc": "2022-03-01T00:00:00Z",
            "bars_per_affected_symbol": 288,
            "affected_symbols": ["SOL/USDT", "ZEC/USDT", "NEAR/USDT", "FIL/USDT"],
        },
        {
            "start_inclusive_utc": "2022-04-01T00:00:00Z",
            "end_exclusive_utc": "2022-04-03T00:00:00Z",
            "bars_per_affected_symbol": 192,
            "affected_symbols": ["SOL/USDT", "ZEC/USDT", "NEAR/USDT", "FIL/USDT"],
        },
    ]
    _expect(gaps.get("exact_vendor_gap_manifest"), expected_gaps, "V3 vendor gap manifest")
    history = _mapping(gaps.get("replay_history_load"), "replay_history_load")
    _expect(
        _utc(history.get("load_history_start_utc"), "history start"),
        HISTORY_START,
        "history start",
    )
    _expect(
        _utc(history.get("evaluation_start_utc"), "history evaluation start"),
        EVALUATION_START,
        "history evaluation start",
    )
    _expect(history.get("correlation_daily_log_returns_min"), 90, "correlation history")

    governance = _mapping(loaded.get("governance"), "governance")
    _expect(
        governance.get("canonical_prereg_path"),
        CANONICAL_PREREG_RELATIVE,
        "canonical preregistration path",
    )
    for key in (
        "execute_mode_must_use_canonical_repo_prereg_path_and_contents",
        "source_clean_preflight_before_snapshot_access",
        "source_commit_and_every_research_file_sha256_required",
        "prereg_sha256_required",
        "predecessor_and_v3_lineage_size_and_sha256_preflight_and_postflight_required",
        "snapshot_size_and_sha256_preflight_and_postflight_required",
        "source_commit_and_file_hashes_must_match_preflight_after_replay",
        "holdout_run_forbidden",
        "live_or_paper_daemon_mutation_forbidden",
    ):
        _expect(governance.get(key), True, f"governance.{key}")
    _expect(governance.get("holdout_access_authorized"), False, "holdout authorization")
    _expect(
        governance.get("deployment_decision_from_this_replay_forbidden"),
        True,
        "deployment decision gate",
    )

    references = _mapping(loaded.get("audited_live_reference"), "audited_live_reference")
    for key in _REFERENCE_SOURCE_KEYS:
        spec = _mapping(references.get(key), f"audited_live_reference.{key}")
        relative = Path(str(spec.get("path", "")))
        if relative.is_absolute() or ".." in relative.parts or not str(relative):
            raise ValueError(f"audited_live_reference.{key}.path must be repo-relative")
        digest = str(spec.get("sha256_at_prereg", "")).lower()
        if not _SHA256.fullmatch(digest):
            raise ValueError(f"audited_live_reference.{key}.sha256_at_prereg is invalid")
    config_reference = _mapping(references["config"], "audited_live_reference.config")
    _expect(config_reference.get("path"), CANONICAL_CONFIG_RELATIVE, "canonical config path")
    _expect(
        str(config_reference.get("sha256_at_prereg", "")).lower(),
        EXPECTED_CONFIG_SHA256,
        "canonical config SHA256 binding",
    )
    _expect(
        references.get("source_hashes_are_reference_identity_not_permission_to_import_live_state"),
        True,
        "reference source identity gate",
    )
    limitations = loaded.get("limitations")
    if (
        not isinstance(limitations, list)
        or not limitations
        or any(not isinstance(item, str) or not item.strip() for item in limitations)
    ):
        raise ValueError("limitations must be a non-empty list of strings")
    if _FUNDING_LINEAGE_LIMITATION not in limitations:
        raise ValueError("funding V3-lineage limitation must be disclosed")
    live_proxy = _mapping(
        loaded.get("external_live_gate_proxy_policy"), "external_live_gate_proxy_policy"
    )
    _expect(
        live_proxy.get("limitation_disclosure_required_in_every_result"),
        True,
        "limitation disclosure gate",
    )

    # These builders validate every frozen numerical policy/scenario value.
    build_policy(loaded)
    build_scenarios(loaded)
    return loaded


def build_policy(prereg: Mapping[str, Any]) -> V15P2PortfolioPolicy:
    """Construct the sole admissible policy and reject any prereg drift."""

    signal = _mapping(prereg.get("signal_contract"), "signal_contract")
    gaps = _mapping(prereg.get("data_and_gap_contract"), "data_and_gap_contract")
    risk = _mapping(prereg.get("risk_and_portfolio_policy"), "risk policy")
    execution = _mapping(prereg.get("execution_proxy"), "execution_proxy")
    exits = _mapping(prereg.get("exit_policy"), "exit_policy")
    tp1 = _mapping(exits.get("TP1"), "exit_policy.TP1")
    tp2 = _mapping(exits.get("TP2"), "exit_policy.TP2")
    runner = _mapping(exits.get("runner"), "exit_policy.runner")
    normalizer = _mapping(risk.get("stop_distance_normalizer"), "stop normalizer")
    throttle = _mapping(risk.get("drawdown_throttle"), "drawdown throttle")
    margin = _mapping(risk.get("initial_margin_gate"), "initial margin gate")
    liquidation = _mapping(
        risk.get("stop_liquidation_margin_safety_gate"), "liquidation safety gate"
    )
    correlation = _mapping(risk.get("correlation_gate"), "correlation gate")
    breakers = _mapping(risk.get("breakers"), "breakers")
    daily = _mapping(breakers.get("daily"), "daily breaker")
    weekly = _mapping(breakers.get("weekly"), "weekly breaker")
    monthly = _mapping(breakers.get("monthly_combined"), "monthly breaker")
    long_breaker = _mapping(breakers.get("monthly_long"), "long breaker")
    short_breaker = _mapping(breakers.get("monthly_short"), "short breaker")
    consecutive = _mapping(breakers.get("consecutive_losses"), "consecutive breaker")
    history = _mapping(gaps.get("replay_history_load"), "replay history")

    _expect(signal.get("timeframe"), "15m", "signal timeframe")
    _expect(
        tuple(signal.get("strategy_order", ())),
        ("vsa_climax_test", "grimes_abc_pullback"),
        "strategy order",
    )
    _expect(execution.get("initial_wallet_usdt"), 10_000.0, "initial wallet")
    _expect(execution.get("entry_fill"), "next_exact_contiguous_bar_open", "entry fill")
    _expect(execution.get("one_net_position_per_symbol"), True, "one position per symbol")
    _expect(execution.get("pyramid"), False, "pyramid")

    policy = V15P2PortfolioPolicy(
        initial_wallet=_number(execution.get("initial_wallet_usdt"), "initial wallet"),
        base_risk_per_trade=_pct(risk.get("base_risk_per_trade_pct"), "base risk"),
        stop_normalizer_target=_pct(normalizer.get("target_pct"), "normalizer target"),
        stop_normalizer_min=_number(normalizer.get("factor_min"), "normalizer min"),
        stop_normalizer_max=_number(normalizer.get("factor_max"), "normalizer max"),
        minimum_stop_distance_pct=_number(
            signal.get("decision_reference_stop_distance_pct_min"),
            "minimum decision-reference stop distance",
        ),
        minimum_confluence=_number(signal.get("confidence_min"), "minimum confluence"),
        dd_throttle_threshold=_pct(throttle.get("threshold_pct"), "DD threshold"),
        dd_throttle_multiplier=_number(throttle.get("new_entry_risk_multiplier"), "DD multiplier"),
        max_symbol_notional_pct=_pct(
            risk.get("max_notional_per_symbol_pct_current_wallet"), "symbol cap"
        ),
        max_open_positions=_integer(risk.get("max_open_positions"), "max open positions"),
        max_same_side_positions=_integer(
            risk.get("max_same_side_open_positions"), "max same-side positions"
        ),
        max_portfolio_notional_x=_number(
            risk.get("max_portfolio_notional_x_current_wallet"), "portfolio cap"
        ),
        leverage=_number(risk.get("leverage_for_margin_proxy"), "leverage"),
        initial_margin_buffer=_number(margin.get("margin_safety_buffer_ratio"), "margin buffer"),
        stop_liquidation_safety_ratio=_number(
            liquidation.get("margin_safety_ratio"), "liquidation safety"
        ),
        cooldown_days=_number(signal.get("same_symbol_side_cooldown_days"), "cooldown"),
        correlation_lookback_days=_integer(
            correlation.get("causal_daily_log_return_lookback_days"), "correlation lookback"
        ),
        correlation_min_observations=_integer(
            history.get("correlation_daily_log_returns_min"), "correlation observations"
        ),
        correlation_reduce_above=_number(
            correlation.get("max_pairwise_correlation"), "correlation reduce threshold"
        ),
        correlation_block_at=_number(correlation.get("hard_block_at"), "correlation block"),
        correlation_reduction_factor=_number(
            correlation.get("risk_reduction_factor"), "correlation reduction"
        ),
        tp1_r=_number(tp1.get("trigger_R"), "TP1 R"),
        tp2_r=_number(tp2.get("trigger_R"), "TP2 R"),
        tp1_fraction=_number(tp1.get("fraction_of_original_quantity"), "TP1 fraction"),
        tp2_fraction=_number(tp2.get("fraction_of_original_quantity"), "TP2 fraction"),
        runner_fraction=_number(runner.get("fraction_of_original_quantity"), "runner fraction"),
        trail_pct=_number(runner.get("trail_pct"), "trail percentage"),
        runner_time_bars_after_tp1=_integer(
            runner.get("time_stop_bars_after_first_TP1_fill"), "runner time bars"
        ),
        daily_loss_pct=_pct(daily.get("loss_pct"), "daily loss"),
        daily_halt_days=_number(daily.get("halt_days"), "daily halt"),
        weekly_loss_pct=_pct(weekly.get("loss_pct"), "weekly loss"),
        weekly_halt_days=_number(weekly.get("halt_days"), "weekly halt"),
        monthly_combined_loss_pct=_pct(monthly.get("loss_pct"), "monthly loss"),
        monthly_halt_days=_number(monthly.get("halt_days"), "monthly halt"),
        monthly_long_loss_pct=_pct(long_breaker.get("loss_pct"), "long monthly loss"),
        monthly_short_loss_pct=_pct(short_breaker.get("loss_pct"), "short monthly loss"),
        consecutive_loss_count=_integer(consecutive.get("count"), "consecutive count"),
        consecutive_loss_lookback_days=_integer(
            consecutive.get("lookback_days"), "consecutive lookback"
        ),
        consecutive_pause_days=_number(consecutive.get("pause_days"), "consecutive pause"),
        bar_minutes=_integer(runner.get("time_stop_clock_bar_minutes"), "bar minutes"),
        gap_max_minutes=_integer(gaps.get("maximum_contiguous_gap_minutes"), "gap maximum"),
        minimum_notional=_number(risk.get("static_min_notional_usdt"), "static minimum notional"),
    )
    frozen = V15P2PortfolioPolicy(
        correlation_min_observations=90,
        minimum_notional=10.0,
    )
    if policy != frozen:
        differences = {
            field.name: (getattr(policy, field.name), getattr(frozen, field.name))
            for field in fields(V15P2PortfolioPolicy)
            if getattr(policy, field.name) != getattr(frozen, field.name)
        }
        raise ValueError(f"preregistered portfolio policy drifted: {differences}")
    return policy


def build_scenarios(prereg: Mapping[str, Any]) -> dict[str, V15P2CostScenario]:
    """Build exact B/C2/H models; scenario names alone never grant trust."""

    raw = _mapping(prereg.get("cost_and_payoff_scenarios"), "cost scenarios")
    bps = _mapping(raw.get("bps_per_actual_fill"), "bps_per_actual_fill")
    raw_scenarios = _mapping(raw.get("cost_scenarios"), "cost_scenarios")
    _expect(tuple(raw_scenarios), SCENARIO_ORDER, "scenario order")
    result: dict[str, V15P2CostScenario] = {}
    for name in SCENARIO_ORDER:
        spec = _mapping(raw_scenarios.get(name), f"scenario {name}")
        result[name] = V15P2CostScenario(
            name=name,  # type: ignore[arg-type]
            fee_bps_per_fill=_number(bps.get("fee"), "fee bps"),
            spread_slippage_bps_per_fill=_number(
                bps.get("spread_and_slippage"), "spread/slippage bps"
            ),
            impact_bps_per_fill=_number(bps.get("impact"), "impact bps"),
            cost_multiplier=_number(spec.get("cost_multiplier"), f"{name} cost multiplier"),
            funding_multiplier=_number(
                spec.get("funding_multiplier"), f"{name} funding multiplier"
            ),
            positive_price_pnl_multiplier=_number(
                spec.get("positive_price_pnl_multiplier"), f"{name} positive payoff"
            ),
            negative_price_pnl_multiplier=_number(
                spec.get("negative_price_pnl_multiplier"), f"{name} negative payoff"
            ),
        )
    expected = {
        "B": V15P2CostScenario(name="B"),
        "C2": V15P2CostScenario(name="C2", cost_multiplier=2.0, funding_multiplier=2.0),
        "H": V15P2CostScenario(
            name="H", positive_price_pnl_multiplier=0.50, negative_price_pnl_multiplier=1.25
        ),
    }
    if result != expected:
        raise ValueError("preregistered B/C2/H scenario components drifted")
    return result


def _canonical_preregistration(
    prereg: Mapping[str, Any], *, prereg_path: Path, repo_root: Path
) -> Path:
    canonical = (repo_root / CANONICAL_PREREG_RELATIVE).resolve()
    if prereg_path.resolve() != canonical:
        raise ValueError("execute requires the canonical repo baseline preregistration path")
    if not canonical.is_file():
        raise ValueError(f"canonical preregistration is missing: {canonical}")
    if prereg != load_preregistration(canonical):
        raise ValueError("execute preregistration differs from the canonical repo contract")
    return canonical


def _lineage_specs(prereg: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    lineage = _mapping(prereg.get("predecessor_and_v3_lineage"), "predecessor_and_v3_lineage")
    return {
        name: _mapping(lineage[name], f"predecessor_and_v3_lineage.{name}")
        for name in _LINEAGE_FILES_VERIFIED_SEPARATELY
    }


def _verify_lineage_files(
    prereg: Mapping[str, Any], repo_root: Path
) -> dict[str, SnapshotVerification]:
    """Verify every non-DB predecessor/V3 identity at the snapshot boundary."""

    return {
        name: verify_frozen_snapshot(name, spec, repo_root=repo_root)
        for name, spec in _lineage_specs(prereg).items()
    }


def _reference_specs(prereg: Mapping[str, Any]) -> dict[str, dict[str, str]]:
    references = _mapping(prereg.get("audited_live_reference"), "audited_live_reference")
    return {
        key: {
            "path": str(_mapping(references[key], key)["path"]),
            "expected_sha256": str(_mapping(references[key], key)["sha256_at_prereg"]).lower(),
        }
        for key in _REFERENCE_SOURCE_KEYS
    }


def _source_provenance(prereg: Mapping[str, Any], repo_root: Path) -> dict[str, Any]:
    references = _reference_specs(prereg)
    relative_files = tuple(
        dict.fromkeys((*_RUNNER_SOURCE_FILES, *(item["path"] for item in references.values())))
    )
    existing = tuple(relative for relative in relative_files if (repo_root / relative).is_file())
    missing = sorted(set(relative_files).difference(existing))
    hashes = {relative: sha256_file(repo_root / relative) for relative in existing}
    reference_checks = {
        key: {
            **spec,
            "actual_sha256": hashes.get(spec["path"]),
            "matches": hashes.get(spec["path"]) == spec["expected_sha256"],
        }
        for key, spec in references.items()
    }
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        status = subprocess.run(
            ["git", "status", "--porcelain", "--", *relative_files],
            cwd=repo_root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        commit = "UNAVAILABLE"
        status = "UNAVAILABLE"
    references_match = all(check["matches"] for check in reference_checks.values())
    clean = status == "" and not missing and references_match
    return {
        "git_commit": commit,
        "research_source_clean": clean,
        "research_source_status": status.splitlines(),
        "missing_source_files": missing,
        "file_sha256": hashes,
        "reference_source_checks": reference_checks,
        "exact_reference_source_hashes_match": references_match,
    }


def _daily_log_returns(frames: Mapping[str, pd.DataFrame]) -> pd.DataFrame:
    """Create causal returns only from complete, exact UTC calendar days."""

    expected = pd.Timedelta(minutes=15)
    columns: dict[str, pd.Series] = {}
    for symbol in PRIMARY_SYMBOLS:
        frame = frames[symbol].loc[:, ["ts", "close"]].copy()
        timestamps = pd.DatetimeIndex(frame["ts"])
        if timestamps.tz is None:
            raise ValueError(f"{symbol}: market timestamps must be UTC")
        frame["ts"] = timestamps.tz_convert(UTC)
        complete_closes: dict[pd.Timestamp, float] = {}
        for day, group in frame.groupby(frame["ts"].dt.floor("D"), sort=True):
            ordered = group.sort_values("ts")
            index = pd.DatetimeIndex(ordered["ts"])
            if (
                len(index) == 96
                and index[0] == day
                and index[-1] == day + pd.Timedelta(hours=23, minutes=45)
                and (len(index) == 1 or (index[1:] - index[:-1] == expected).all())
            ):
                complete_closes[pd.Timestamp(day)] = float(ordered["close"].iloc[-1])
        ordered_days = sorted(complete_closes)
        returns: dict[pd.Timestamp, float] = {}
        for previous, current in pairwise(ordered_days):
            if current - previous != pd.Timedelta(days=1):
                continue
            value = math.log(complete_closes[current] / complete_closes[previous])
            if not math.isfinite(value):
                raise ValueError(f"{symbol}: non-finite daily return")
            returns[current] = value
        columns[symbol] = pd.Series(returns, dtype=float)
    result = pd.DataFrame(columns).sort_index()
    required_initial_index = pd.date_range(
        EVALUATION_START - pd.Timedelta(days=90),
        EVALUATION_START - pd.Timedelta(days=1),
        freq="D",
        tz="UTC",
    )
    available_initial_index = result.index.intersection(required_initial_index)
    if not available_initial_index.equals(required_initial_index):
        raise ValueError("primary universe lacks 90 complete common causal returns before replay")
    initial = result.loc[required_initial_index, list(PRIMARY_SYMBOLS)]
    if not np.isfinite(initial.to_numpy(dtype=float)).all():
        raise ValueError("primary universe lacks 90 complete common causal returns before replay")
    return result


def _validate_loaded_market(bundle: MarketBundle) -> None:
    expected_symbols = (*PRIMARY_SYMBOLS, REFERENCE_SYMBOL)
    if tuple(bundle.frames) != expected_symbols and set(bundle.frames) != set(expected_symbols):
        raise ValueError("market loader did not return exactly primary13 plus BTC reference")
    required_tail = pd.date_range(
        EVALUATION_START - 500 * _BAR,
        EVALUATION_START - _BAR,
        freq=_BAR,
        tz="UTC",
    )
    for symbol in PRIMARY_SYMBOLS:
        frame = bundle.frames[symbol]
        timestamps = pd.DatetimeIndex(frame["ts"])
        before = timestamps[timestamps < EVALUATION_START]
        if len(before) < 500 or not before[-500:].equals(required_tail):
            raise ValueError(f"{symbol}: missing exact 500-bar warmup at evaluation start")
        evaluation_rows = timestamps[
            (timestamps >= EVALUATION_START) & (timestamps < EVALUATION_END)
        ]
        if len(evaluation_rows) == 0 or evaluation_rows[-1] != EVALUATION_END - _BAR:
            raise ValueError(
                f"{symbol}: does not reach the final required evaluation bar "
                f"{(EVALUATION_END - _BAR).isoformat()}"
            )


def _frame_hashes(frames: Mapping[str, pd.DataFrame]) -> dict[str, str]:
    return {symbol: _dataframe_sha256(frames[symbol]) for symbol in sorted(frames)}


def _signal_reconciliation_fingerprint(row: Any) -> dict[str, Any]:
    """Common immutable identity shared by accepted decisions and intents."""

    fields = (
        "candidate_id",
        "decision_ts",
        "entry_ts",
        "symbol",
        "side",
        "strategy",
        "strategy_rank",
        "pattern_id",
        "confluence_score",
        "decision_close",
        "entry_reference_price",
        "entry_price",
        "stop_price",
        "take_profit_price",
        "decision_stop_distance_pct",
        "entry_stop_distance_pct",
        "suggested_size_atr",
        "signal_manifest_hash",
        "config_sha256",
    )
    missing = [name for name in fields if not hasattr(row, name)]
    if missing:
        raise RuntimeError(f"signal reconciliation row is missing fields: {missing}")
    return {name: _jsonable(getattr(row, name)) for name in fields}


def _reconcile_signal_batch(batch: Any) -> dict[str, Any]:
    """Independently prove accepted decision rows exactly equal batch intents."""

    if getattr(batch, "candidate_id", None) != FAIR_BASELINE_CANDIDATE_ID:
        raise RuntimeError("signal batch emitted a foreign candidate ID")
    if getattr(batch, "config_sha256", None) != EXPECTED_CONFIG_SHA256:
        raise RuntimeError("signal batch config identity drifted")
    if not hasattr(batch, "decisions") or not hasattr(batch, "intents"):
        raise RuntimeError("signal batch omitted decisions or intents")
    decisions = tuple(batch.decisions)
    intents = tuple(batch.intents)
    if tuple(getattr(row, "emission_index", None) for row in decisions) != tuple(
        range(len(decisions))
    ):
        raise RuntimeError("signal decision ledger indexes are not contiguous and deterministic")
    accepted_rows = tuple(row for row in decisions if getattr(row, "outcome", None) == "accepted")
    accepted_fingerprints = tuple(_signal_reconciliation_fingerprint(row) for row in accepted_rows)
    intent_fingerprints = tuple(_signal_reconciliation_fingerprint(row) for row in intents)
    if accepted_fingerprints != intent_fingerprints:
        raise RuntimeError("accepted signal decisions do not reconcile exactly to intents")
    evaluation_accepted = tuple(
        row
        for row in accepted_rows
        if EVALUATION_START.to_pydatetime() <= row.entry_ts < EVALUATION_END.to_pydatetime()
    )
    evaluation_intents = tuple(
        row
        for row in intents
        if EVALUATION_START.to_pydatetime() <= row.entry_ts < EVALUATION_END.to_pydatetime()
    )
    evaluation_accepted_fingerprints = tuple(
        _signal_reconciliation_fingerprint(row) for row in evaluation_accepted
    )
    evaluation_intent_fingerprints = tuple(
        _signal_reconciliation_fingerprint(row) for row in evaluation_intents
    )
    if evaluation_accepted_fingerprints != evaluation_intent_fingerprints:
        raise RuntimeError("evaluation accepted decisions do not reconcile to engine intents")
    return {
        "accepted_decision_count": len(accepted_rows),
        "intent_count": len(intents),
        "exact_ordered_reconciliation": True,
        "accepted_decision_fingerprints_sha256": _payload_sha256(accepted_fingerprints),
        "intent_fingerprints_sha256": _payload_sha256(intent_fingerprints),
        "evaluation_accepted_decision_count": len(evaluation_accepted),
        "evaluation_intent_count": len(evaluation_intents),
        "evaluation_exact_ordered_reconciliation": True,
        "evaluation_fingerprints_sha256": _payload_sha256(evaluation_accepted_fingerprints),
    }


def _base_plan(
    prereg: Mapping[str, Any],
    prereg_path: Path,
    *,
    repo_root: Path,
    source: Mapping[str, Any] | None = None,
    runtime: Mapping[str, str] | None = None,
    prereg_sha256: str | None = None,
) -> dict[str, Any]:
    policy = build_policy(prereg)
    scenarios = build_scenarios(prereg)
    snapshots = _mapping(prereg["snapshots"], "snapshots")
    lineage = _lineage_specs(prereg)
    return {
        "schema_version": PROGRAM_SCHEMA,
        "mode": "DRY_PLAN_NO_SNAPSHOT_ACCESS",
        "evidence_eligible": False,
        "evidence_ineligible_reasons": ["REPLAY_NOT_EXECUTED"],
        "classification": {
            "result_label": "FAIR_LIVE_POLICY_PROXY",
            "strategy": "FAIR_LIVE_POLICY_PROXY",
            "execution": "NEXT_OPEN_BAR_EXECUTION_PROXY",
            "exact_live_replay_claim_allowed": False,
            "deployment_decision_authorized": False,
            "historical_pseudo_oos_is_independent_prospective_evidence": False,
        },
        "limitations": list(prereg["limitations"]),
        "disclosed_limitations": {
            "required": True,
            "count": len(prereg["limitations"]),
            "items": list(prereg["limitations"]),
            "sha256": _payload_sha256(prereg["limitations"]),
        },
        "external_live_gate_proxy_policy": _jsonable(prereg["external_live_gate_proxy_policy"]),
        "evaluation_protocol": {
            "development": _jsonable(prereg["time_protocol"]["development"]),
            "pseudo_oos": _jsonable(prereg["time_protocol"]["pseudo_oos"]),
            "walk_forward_folds": _jsonable(prereg["time_protocol"]["expanding_walk_forward"]),
            "fold_count": 6,
            "fold_months_each": [6, 6, 6, 6, 6, 6],
            "interval_semantics": "half_open_start_inclusive_end_exclusive",
        },
        "fair_improvement_rules": _jsonable(prereg["fair_improvement_rules_frozen_from_v16"]),
        "fair_improvement_rules_sha256": _payload_sha256(
            prereg["fair_improvement_rules_frozen_from_v16"]
        ),
        "preregistration": {
            "path": str(prereg_path.resolve()),
            "sha256": prereg_sha256 or sha256_file(prereg_path.resolve()),
            "schema_version": prereg["schema_version"],
            "status": prereg["status"],
            "live_deployment_authorized": False,
        },
        "candidate_id": FAIR_BASELINE_CANDIDATE_ID,
        "scenario_order": list(SCENARIO_ORDER),
        "policy": _jsonable(policy),
        "policy_sha256": _payload_sha256(policy),
        "scenarios": _jsonable(scenarios),
        "scenarios_sha256": _payload_sha256(scenarios),
        "runtime_versions": dict(runtime or _critical_runtime_versions(repo_root)),
        "source_provenance": dict(source or _source_provenance(prereg, repo_root)),
        "universe": {
            "tradable_symbols": list(PRIMARY_SYMBOLS),
            "non_traded_reference_symbol": REFERENCE_SYMBOL,
            "holdout_symbols_accessed": [],
            "reference_symbol_traded": False,
        },
        "time_range_utc": {
            "history_start_inclusive": HISTORY_START.isoformat(),
            "evaluation_start_inclusive": EVALUATION_START.isoformat(),
            "end_exclusive": EVALUATION_END.isoformat(),
        },
        "data_lineage": {
            name: {
                "configured_path": str(spec["path"]),
                "expected_bytes": int(spec["bytes"]),
                "expected_sha256": str(spec["sha256"]),
                "status": "NOT_ACCESSED",
            }
            for name, spec in lineage.items()
        },
        "snapshots": {
            name: {
                "configured_path": str(_mapping(snapshots[name], name)["path"]),
                "expected_bytes": int(_mapping(snapshots[name], name)["bytes"]),
                "expected_sha256": str(_mapping(snapshots[name], name)["sha256"]),
                "status": "NOT_ACCESSED",
            }
            for name in ("market", "funding")
        },
    }


def dry_plan(prereg_path: Path, *, repo_root: Path | None = None) -> dict[str, Any]:
    """Validate the plan without touching either configured snapshot path."""

    root = (repo_root or Path(__file__).resolve().parents[3]).resolve()
    path = prereg_path.resolve()
    prereg = load_preregistration(path)
    return _base_plan(prereg, path, repo_root=root)


def _assert_result_window(
    result: V15P2PortfolioResult,
    scenario: str,
    *,
    scenario_config: V15P2CostScenario,
    policy: V15P2PortfolioPolicy,
) -> None:
    required_ledgers = (
        "entries",
        "exit_fills",
        "funding_events",
        "journal_rows",
        "stop_transitions",
        "breaker_transitions",
        "risk_decisions",
        "rejections",
        "closed_episodes",
        "curve",
        "terminal_positions",
    )
    missing_ledgers = [name for name in required_ledgers if not hasattr(result, name)]
    if missing_ledgers:
        raise RuntimeError(f"engine result omitted required evidence ledgers: {missing_ledgers}")
    if result.scenario != scenario:
        raise RuntimeError(f"engine returned {result.scenario!r} for scenario {scenario}")
    if getattr(result, "scenario_identity", None) != scenario:
        raise RuntimeError("engine did not attest the canonical scenario identity")
    if getattr(result, "scenario_is_canonical", None) is not True:
        raise RuntimeError("engine classified the replay scenario as custom/noncanonical")
    if getattr(result, "scenario_config", None) != scenario_config:
        raise RuntimeError("engine result scenario components differ from the preregistration")
    if getattr(result, "policy", None) != policy:
        raise RuntimeError("engine result policy differs from the preregistration")
    result_start = getattr(result, "evaluation_start", None)
    result_end = getattr(result, "evaluation_end", None)
    if result_start is None or result_end is None:
        raise RuntimeError("engine result lacks its bound half-open evaluation window")
    if pd.Timestamp(result_start) != EVALUATION_START or pd.Timestamp(result_end) != EVALUATION_END:
        raise RuntimeError("engine result evaluation window drifted")
    if not result.curve:
        raise RuntimeError("engine returned an empty evaluation curve")
    if pd.Timestamp(result.curve[0].ts) != EVALUATION_START:
        raise RuntimeError("curve starts before or after evaluation_start")
    if pd.Timestamp(result.curve[-1].ts) != EVALUATION_END - _BAR:
        raise RuntimeError("curve does not end at the last expected 15-minute bar")
    for ledger_name in ("entries", "exit_fills", "funding_events", "curve"):
        for item in getattr(result, ledger_name):
            timestamp = item.entry_ts if ledger_name == "entries" else item.ts
            if not (EVALUATION_START <= pd.Timestamp(timestamp) < EVALUATION_END):
                raise RuntimeError(f"{ledger_name} contains an event outside evaluation range")


def run_program(prereg_path: Path, *, repo_root: Path) -> dict[str, Any]:
    """Run the canonical primary13 baseline once per independent B/C2/H path."""

    root = repo_root.resolve()
    path = prereg_path.resolve()
    prereg = load_preregistration(path)
    canonical = _canonical_preregistration(prereg, prereg_path=path, repo_root=root)
    policy = build_policy(prereg)
    scenarios = build_scenarios(prereg)
    snapshots = _mapping(prereg["snapshots"], "snapshots")

    # All source/config/runtime governance finishes before verify/load can lead
    # to a DuckDB connection.  Tests pin this ordering explicitly.
    prereg_hash_pre = sha256_file(canonical)
    runtime_pre = _critical_runtime_versions(root)
    source_pre = _source_provenance(prereg, root)
    if not source_pre["research_source_clean"]:
        raise RuntimeError(
            "baseline execute requires clean exact research/reference source before snapshot "
            f"access: {source_pre['research_source_status']}"
        )
    if not source_pre["exact_reference_source_hashes_match"]:
        raise RuntimeError("an audited live reference source hash does not match preregistration")

    verified_lineage_pre = _verify_lineage_files(prereg, root)
    verified_pre = {
        name: verify_frozen_snapshot(name, snapshots[name], repo_root=root)
        for name in ("market", "funding")
    }
    market_spec = _mapping(snapshots["market"], "market snapshot")
    market = load_market_snapshot(
        Path(verified_pre["market"].resolved_path),
        market_spec,
        symbols=(*PRIMARY_SYMBOLS, REFERENCE_SYMBOL),
        start=HISTORY_START,
        end=EVALUATION_END,
    )
    _validate_loaded_market(market)
    funding = load_funding_snapshot(
        Path(verified_pre["funding"].resolved_path),
        _mapping(snapshots["funding"], "funding snapshot"),
        symbols=PRIMARY_SYMBOLS,
        venue=str(market_spec["venue"]),
        start=HISTORY_START,
        engine_start=EVALUATION_START,
        end=EVALUATION_END,
    )

    signal_frames = {symbol: market.frames[symbol] for symbol in PRIMARY_SYMBOLS}
    config_path = (root / CANONICAL_CONFIG_RELATIVE).resolve()
    signal_batch = generate_v15p2_signal_batch(
        signal_frames,
        config_path=config_path,
        config_sha256=EXPECTED_CONFIG_SHA256,
    )
    batch_reconciliation = _reconcile_signal_batch(signal_batch)
    all_intents = tuple(signal_batch.intents)
    all_decisions = tuple(signal_batch.decisions)
    intents = tuple(
        intent
        for intent in all_intents
        if EVALUATION_START.to_pydatetime() <= intent.entry_ts < EVALUATION_END.to_pydatetime()
    )
    if any(intent.candidate_id != FAIR_BASELINE_CANDIDATE_ID for intent in intents):
        raise RuntimeError("signal adapter emitted a foreign candidate ID")
    if any(intent.symbol not in PRIMARY_SYMBOLS for intent in intents):
        raise RuntimeError("signal adapter emitted a non-primary or reference/holdout trade")

    # The one validation bar permits an entry exactly at evaluation_start to
    # prove its decision close; engine execution remains explicitly half-open.
    validation_start = EVALUATION_START - _BAR
    engine_frames = {
        symbol: frame.loc[
            (frame["ts"] >= validation_start) & (frame["ts"] < EVALUATION_END)
        ].reset_index(drop=True)
        for symbol, frame in signal_frames.items()
    }
    if any(frame.empty for frame in engine_frames.values()):
        raise ValueError("every primary engine frame must contain evaluation bars")
    daily_returns = _daily_log_returns(signal_frames)

    frame_hashes_pre = _frame_hashes(engine_frames)
    decisions_payload = _jsonable(all_decisions)
    decisions_hash_pre = _payload_sha256(decisions_payload)
    all_intents_payload = _jsonable(all_intents)
    all_intents_hash_pre = _payload_sha256(all_intents_payload)
    intents_payload = _jsonable(intents)
    intents_hash_pre = _payload_sha256(intents_payload)
    funding_payload = _jsonable(funding.engine_events)
    funding_hash_pre = _payload_sha256(funding_payload)
    returns_hash_pre = _dataframe_sha256(daily_returns)

    results: dict[str, Any] = {}
    for name in SCENARIO_ORDER:
        result = run_v15p2_engine(
            engine_frames,
            intents,
            funding.engine_events,
            daily_returns,
            scenario=scenarios[name],
            policy=policy,
            evaluation_start=EVALUATION_START.to_pydatetime(),
            evaluation_end=EVALUATION_END.to_pydatetime(),
        )
        _assert_result_window(
            result,
            name,
            scenario_config=scenarios[name],
            policy=policy,
        )
        serialized = _jsonable(result)
        # Strict finite serialization is an evidence precondition, not merely
        # a presentation concern.
        result_sha256 = _payload_sha256(serialized)
        results[name] = {
            "complete_result": serialized,
            "complete_result_sha256": result_sha256,
        }

    if _frame_hashes(engine_frames) != frame_hashes_pre:
        raise RuntimeError("engine mutated its market-frame input")
    if _payload_sha256(_jsonable(signal_batch.decisions)) != decisions_hash_pre:
        raise RuntimeError("signal decision ledger changed during replay")
    if _payload_sha256(_jsonable(signal_batch.intents)) != all_intents_hash_pre:
        raise RuntimeError("signal batch intents changed during replay")
    if _payload_sha256(_jsonable(intents)) != intents_hash_pre:
        raise RuntimeError("engine mutated the generated intent stream")
    if _payload_sha256(_jsonable(funding.engine_events)) != funding_hash_pre:
        raise RuntimeError("engine mutated the observed funding stream")
    if _dataframe_sha256(daily_returns) != returns_hash_pre:
        raise RuntimeError("engine mutated the causal daily-return input")

    verified_post = {
        name: verify_frozen_snapshot(name, snapshots[name], repo_root=root)
        for name in ("market", "funding")
    }
    verified_lineage_post = _verify_lineage_files(prereg, root)
    source_post = _source_provenance(prereg, root)
    runtime_post = _critical_runtime_versions(root)
    prereg_hash_post = sha256_file(canonical)
    source_unchanged = (
        source_post["research_source_clean"]
        and source_post["git_commit"] == source_pre["git_commit"]
        and source_post["file_sha256"] == source_pre["file_sha256"]
        and source_post["reference_source_checks"] == source_pre["reference_source_checks"]
    )
    snapshots_unchanged = all(
        asdict(verified_post[name]) == asdict(verified_pre[name]) for name in ("market", "funding")
    )
    lineage_unchanged = all(
        asdict(verified_lineage_post[name]) == asdict(verified_lineage_pre[name])
        for name in _LINEAGE_FILES_VERIFIED_SEPARATELY
    )
    if not source_unchanged:
        raise RuntimeError("research/reference source changed during baseline replay")
    if runtime_post != runtime_pre:
        raise RuntimeError("critical runtime provenance changed during baseline replay")
    if prereg_hash_post != prereg_hash_pre:
        raise RuntimeError("canonical preregistration changed during baseline replay")
    if not snapshots_unchanged:
        raise RuntimeError("a frozen snapshot changed during baseline replay")
    if not lineage_unchanged:
        raise RuntimeError("a predecessor/V3 lineage file changed during baseline replay")

    payload = _base_plan(
        prereg,
        path,
        repo_root=root,
        source=source_post,
        runtime=runtime_post,
        prereg_sha256=prereg_hash_pre,
    )
    payload.update(
        {
            "mode": "FULL_FROZEN_PRIMARY13_REPLAY",
            "evidence_eligible": True,
            "evidence_ineligible_reasons": [],
            "data_lineage": {name: asdict(value) for name, value in verified_lineage_pre.items()},
            "snapshots": {name: asdict(value) for name, value in verified_pre.items()},
            "execution_governance": {
                "canonical_prereg_path": str(canonical),
                "canonical_prereg_semantic_match": True,
                "canonical_prereg_preflight_sha256": prereg_hash_pre,
                "canonical_prereg_postflight_sha256": prereg_hash_post,
                "clean_source_preflight_before_snapshot_access": True,
                "exact_reference_source_hashes_preflight": True,
                "source_unchanged_postflight": source_unchanged,
                "runtime_unchanged_postflight": runtime_post == runtime_pre,
                "lineage_reverified_postflight": True,
                "lineage_unchanged_postflight": lineage_unchanged,
                "snapshots_reverified_postflight": True,
                "snapshots_unchanged_postflight": snapshots_unchanged,
                "preflight_source": source_pre,
                "postflight_source": source_post,
                "preflight_runtime": runtime_pre,
                "postflight_runtime": runtime_post,
                "postflight_snapshots": {
                    name: asdict(value) for name, value in verified_post.items()
                },
                "postflight_data_lineage": {
                    name: asdict(value) for name, value in verified_lineage_post.items()
                },
                "input_mutation_checks": {
                    "engine_frames_sha256_by_symbol": frame_hashes_pre,
                    "signal_decision_ledger_sha256": decisions_hash_pre,
                    "signal_batch_intents_sha256": all_intents_hash_pre,
                    "entry_intents_sha256": intents_hash_pre,
                    "funding_events_sha256": funding_hash_pre,
                    "daily_returns_sha256": returns_hash_pre,
                    "all_unchanged": True,
                },
            },
            "market_loading": {
                "symbols": [*PRIMARY_SYMBOLS, REFERENCE_SYMBOL],
                "tradable_symbols": list(PRIMARY_SYMBOLS),
                "reference_symbol": REFERENCE_SYMBOL,
                "reference_symbol_traded": False,
                "alignment": "INDEPENDENT_SYMBOL_FRAMES",
                "global_intersection_performed": False,
                "forward_fill_performed": False,
                "history_rows_by_symbol": market.rows_by_symbol,
                "first_ts_by_symbol": _jsonable(market.first_ts_by_symbol),
                "last_ts_by_symbol": _jsonable(market.last_ts_by_symbol),
                "engine_validation_start_inclusive": validation_start.isoformat(),
                "engine_rows_by_symbol": {
                    symbol: len(frame) for symbol, frame in engine_frames.items()
                },
            },
            "funding": {
                "source": "OBSERVED_FROZEN_FUNDING_EVENTS",
                "symbols": list(PRIMARY_SYMBOLS),
                "event_count": len(funding.engine_events),
                "rows_by_symbol_including_history": funding.rows_by_symbol,
                "raw_fractional_timestamps_preserved": True,
                "invalid_mark_price_falls_back_in_engine": True,
            },
            "daily_returns": {
                "construction": "COMPLETE_CAUSAL_UTC_DAYS_ONLY",
                "minimum_initial_common_observations": 90,
                "row_count": len(daily_returns),
                "columns": list(daily_returns.columns),
                "sha256": returns_hash_pre,
            },
            "signal_stream": {
                "generation_call_count": 1,
                "raw_emission_count": len(all_decisions),
                "generated_history_intent_count": len(all_intents),
                "evaluation_intent_count": len(intents),
                "pre_evaluation_intents_excluded": len(all_intents) - len(intents),
                "decision_reason_counts": dict(
                    sorted(Counter(decision.reason for decision in all_decisions).items())
                ),
                "decision_ledger": decisions_payload,
                "decision_ledger_sha256": decisions_hash_pre,
                "accepted_intent_reconciliation": batch_reconciliation,
                "only_signal_eligible_intents_passed_to_engines": True,
                "accepted_intents": all_intents_payload,
                "accepted_intents_sha256": all_intents_hash_pre,
                "entry_intents": intents_payload,
                "entry_intents_sha256": intents_hash_pre,
                "reference_or_holdout_intents": 0,
            },
            "results": results,
        }
    )
    # One final recursive strict-JSON proof covers the complete evidence tree.
    _payload_sha256(payload)
    return payload


def deterministic_json(payload: Mapping[str, Any]) -> str:
    """Render deterministic strict JSON; NaN and Infinity are forbidden."""

    return json.dumps(_jsonable(payload), sort_keys=True, indent=2, allow_nan=False) + "\n"


def _validated_output_path(raw: Path, *, repo_root: Path, prereg_path: Path) -> Path:
    output = raw.resolve()
    reports_root = (repo_root / "reports/research").resolve()
    if reports_root not in output.parents or output.suffix.lower() != ".json":
        raise ValueError("output must be a .json file under reports/research")
    if output.exists() or output.is_symlink():
        raise FileExistsError(f"output already exists: {output}")
    load_preregistration(prereg_path.resolve())
    protected = {prereg_path.resolve()}
    protected.update((repo_root / item).resolve() for item in _RUNNER_SOURCE_FILES)
    # Never resolve/stat configured snapshot paths here.  Dry-plan with an
    # output file has the same zero-snapshot-access guarantee, while the
    # reports-root constraint already prevents collision with data/backups.
    if output in protected:
        raise ValueError("output may not overwrite a frozen input or source")
    return output


def _write_json_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: str | None = None
    encoder = json.JSONEncoder(sort_keys=True, indent=2, allow_nan=False)
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary = handle.name
            # run_program/dry_plan already return JSON-native trees.  Avoid a
            # second full-tree copy when the evidence contains three complete
            # multi-year 15-minute curves.
            for chunk in encoder.iterencode(payload):
                handle.write(chunk)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temporary, path)
        Path(temporary).unlink()
        temporary = None
    finally:
        if temporary is not None:
            Path(temporary).unlink(missing_ok=True)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prereg", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--dry-plan", action="store_true")
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[3])
    args = parser.parse_args(argv)
    root = args.repo_root.resolve()
    prereg = args.prereg or root / CANONICAL_PREREG_RELATIVE
    output = (
        None
        if args.output is None
        else _validated_output_path(args.output, repo_root=root, prereg_path=prereg)
    )
    if not args.dry_plan and output is None:
        parser.error("full replay requires --output to avoid printing a very large result")
    payload = (
        dry_plan(prereg, repo_root=root) if args.dry_plan else run_program(prereg, repo_root=root)
    )
    if output is None:
        print(deterministic_json(payload), end="")
    else:
        _write_json_atomic(output, payload)
    return 0


__all__ = [
    "CANONICAL_PREREG_RELATIVE",
    "EVALUATION_END",
    "EVALUATION_START",
    "HISTORY_START",
    "PRIMARY_SYMBOLS",
    "PROGRAM_SCHEMA",
    "REFERENCE_SYMBOL",
    "SCENARIO_ORDER",
    "FundingBundle",
    "MarketBundle",
    "SnapshotVerification",
    "build_policy",
    "build_scenarios",
    "deterministic_json",
    "dry_plan",
    "load_preregistration",
    "main",
    "run_program",
]


if __name__ == "__main__":
    raise SystemExit(main())
