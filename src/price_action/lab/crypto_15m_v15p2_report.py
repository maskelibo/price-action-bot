"""Fail-closed reporting for the frozen v15p2 fair-baseline replay.

The reporter consumes the JSON evidence produced by
``crypto_15m_v15p2_program``.  It does not open snapshots, generate signals, or
run a replay.  Percentage values in the public report are percentage points
(``10.0`` means ten percent).
"""

from __future__ import annotations

import argparse
import bisect
import hashlib
import json
import math
import os
import re
import statistics
import tempfile
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

REPORT_SCHEMA = "crypto-15m-v15p2-fair-baseline-report-v2"
RAW_SCHEMA = "crypto-15m-v15p2-fair-baseline-run-v2"
FULL_REPLAY_MODE = "FULL_FROZEN_PRIMARY13_REPLAY"
VERDICT = "BASELINE_MEASURED_NO_DEPLOYMENT"
SCENARIO_ORDER = ("B", "C2", "H")
HISTORY_START = pd.Timestamp("2021-02-21T00:00:00Z")
EVALUATION_START = pd.Timestamp("2021-06-01T00:00:00Z")
DEVELOPMENT_END = pd.Timestamp("2023-06-01T00:00:00Z")
EVALUATION_END = pd.Timestamp("2026-06-01T00:00:00Z")
BAR = pd.Timedelta(minutes=15)
EXPECTED_CONFIG_SHA256 = "78025a394aecb807c32aeba737823bd565f0f19e72ec133352d63f697036ea82"
EXPECTED_PREREG_SHA256 = "7a6180312bcbb1b1f9644d26dbce8bd8ac57ea4eb13fc0aa783025f069ddd511"
CANONICAL_PREREG_RELATIVE = "configs/crypto_15m_v15p2_fair_baseline_v2_prereg.yaml"
EXPECTED_REQUIREMENTS_LOCK_SHA256 = (
    "30c4321e616138e342d8c67143eff43b490566e594a86d4277c1445c90b261f5"
)
EXPECTED_SNAPSHOT_IDENTITIES = {
    "market": {
        "configured_path": "data/backups/20260711_v15p2_v3_usdm/market.duckdb",
        "bytes": 181_415_936,
        "sha256": "50e5b240e6babeb3b7ceadc0ae007ededc0ae589cba931e3603d233cec693eb8",
    },
    "funding": {
        "configured_path": "data/backups/20260711/funding.duckdb",
        "bytes": 17_575_936,
        "sha256": "35be9ebae8f9468a6bae819054008cb4c2338ae0eb923910584dea1adc0c6b96",
    },
}
EXPECTED_DATA_LINEAGE_IDENTITIES = {
    "predecessor_preregistration": {
        "configured_path": "configs/crypto_15m_v15p2_fair_baseline_prereg.yaml",
        "bytes": 33_623,
        "sha256": "695fb5b7a07fc0bb54c0a69b10f0893d246926a4339a17b5e8705802800f9c22",
    },
    "predecessor_coverage_failure": {
        "configured_path": "configs/crypto_15m_v15p2_fair_baseline_v1_coverage_failure.json",
        "bytes": 3_073,
        "sha256": "34a844100497bab4ee6edc6cba5efea26bdf6d9ce7278bf384a86fb9d58fab76",
    },
    "predecessor_coverage_failure_supplement": {
        "configured_path": (
            "configs/crypto_15m_v15p2_fair_baseline_v1_coverage_failure_"
            "supplemental_attestation.json"
        ),
        "bytes": 15_550,
        "sha256": "1254512f1238f1e4bc3a58d0b2331ffad6d5c3e2f995c42d138aa998562c2e03",
    },
    "v2_coverage_diagnosis": {
        "configured_path": "configs/crypto_15m_v15p2_usdm_snapshot_v2_coverage_diagnosis.json",
        "bytes": 8_036,
        "sha256": "b2a50fdb00c055aef8ec09b1c81e662160917878ac797b2dae966e661b745e91",
    },
    "v3_protocol": {
        "configured_path": "configs/crypto_15m_v15p2_usdm_snapshot_v3_build_protocol.json",
        "bytes": 8_125,
        "sha256": "e6995f2fa22158d9133b9d3a45caeb0ba3de01ad70e77239d99bb13331bef3c8",
    },
    "v3_reservation": {
        "configured_path": (
            "configs/crypto_15m_v15p2_usdm_snapshot_v3_build_attempt_001_started.json"
        ),
        "bytes": 1_387,
        "sha256": "5c28272dc96d6e14eb471a37e8b4e7bd97cee3983f22c62e5c6e4cf6241ae404",
    },
    "v3_success_identity": {
        "configured_path": (
            "configs/crypto_15m_v15p2_usdm_snapshot_v3_build_attempt_001_success_identity.json"
        ),
        "bytes": 14_258,
        "sha256": "8e73f05d87106ea9df635e3ae0d3996ec5679da48f83bff77856b065059972d3",
    },
    "v3_build_evidence": {
        "configured_path": "data/backups/20260711_v15p2_v3_usdm/build_evidence.json",
        "bytes": 1_095_568,
        "sha256": "1ac74ceb61c197fad4bc27783eadaed4e88504e3a751257d8c735bc9eece9b34",
    },
}
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
SIGNAL_STRATEGY_ORDER = ("vsa_climax_test", "grimes_abc_pullback")
EXPECTED_SIGNAL_MANIFEST_HASHES = {
    "vsa_climax_test": "ebddc62d495cc790",
    "grimes_abc_pullback": "33653e0c52e34338",
}
EXPECTED_RUNTIME_VERSIONS = {
    "python": "3.12.13",
    "python_implementation": "CPython",
    "requirements_lock_sha256": EXPECTED_REQUIREMENTS_LOCK_SHA256,
    "duckdb": "1.5.3",
    "loguru": "0.7.3",
    "numba": "0.61.2",
    "numpy": "2.2.6",
    "pandas": "3.0.3",
    "pydantic": "2.13.4",
    "pydantic_settings": "2.14.2",
    "python_dotenv": "1.2.2",
    "pyyaml": "6.0.3",
    "scipy": "1.17.1",
    "statsmodels": "0.14.6",
}
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
_EXPECTED_REFERENCE_SOURCES = {
    "config": (
        "configs/risk_phoenix_scalp_15m_v15p2.yaml",
        "78025a394aecb807c32aeba737823bd565f0f19e72ec133352d63f697036ea82",
    ),
    "wrapper": (
        "scripts/futures_daemon_v14.py",
        "3ceae474207e4bcc52643b1d3fc90b9bb14fc429a6519e349e7c7983b23b190b",
    ),
    "wrapper_patch_source": (
        "scripts/futures_daemon_v13.py",
        "2bec4f8d7d380610283551d846ad2bb5c930f35f0c04c5921d8ec85ddcc55ef1",
    ),
    "daemon": (
        "scripts/futures_daemon.py",
        "dc9e7f2741bd200ce904089b28024365cc942820acfeaec61149820ae3f58114",
    ),
    "scanner": (
        "scripts/futures_trade_15m.py",
        "144d6ea877460d5b2e66c6fc26adc23ed58c2fd049f7c0ae4143f2fafb040119",
    ),
    "canonical_protection_orders": (
        "scripts/futures_trade_daily.py",
        "b0fa562fc01ca54117f6ab6a3b7010bad958fbaee4c1e93eff47850200343e53",
    ),
    "live_account_adapter": (
        "scripts/lib/risk_integration.py",
        "14466e7f19d1512f04ed5d27c629f9e316df1709e39decdf467746d416c4461b",
    ),
    "classic_strategy_indicators": (
        "src/price_action/strategies/classic_pa.py",
        "9c7b93f1aa95a371cdd428c260ffd21dac07fe4fb3767cbe7a1500b8aec71aea",
    ),
    "signal_contracts_and_stable_hash": (
        "src/price_action/contracts.py",
        "2482bc8bb10872da1117ef03a05aed2f0eeaaca79069bcac4e0a7c25527edd04",
    ),
    "strategy_base": (
        "src/price_action/strategies/base.py",
        "56131288ab54d57b3054b01f4230a86ccf69f4439f78e065fb149fee58a0f1e8",
    ),
    "strategy_manifest_loader": (
        "src/price_action/strategies/manifest_loader.py",
        "9b3fe5459b16f8a1cdfdf70d77999a804bee210c04437883f17bd112a8663ddd",
    ),
    "vsa_strategy": (
        "src/price_action/strategies/vsa_climax_test.py",
        "2de255a5b84ffce6fdaae5ef88bd95fad35c528fb8eed3fe8c90ff5fe71c321b",
    ),
    "vsa_15m_overlay": (
        "src/price_action/strategies/manifests/vsa_climax_test_15m.yaml",
        "b403803d39b75a201f11ceda93045a8f90ac741b7912414e4ed9644c061407ac",
    ),
    "grimes_strategy": (
        "src/price_action/strategies/grimes_abc_pullback.py",
        "b46a7c86aee2df9c4b243132cc78e837c8d767c1d6df2bf1485a29157b1bbcd1",
    ),
    "risk_sizing": (
        "src/price_action/risk/sizing.py",
        "1ff0379f9abde04bb535e7d076731e5e1f44324bf90aff9419554ab1ac15d929",
    ),
    "risk_gates": (
        "src/price_action/risk/gates.py",
        "f9b5e77cc861b828f61612a4cb1ca72bd383d4fcc35ba1c890d2e1b9ef228440",
    ),
    "stop_distance_normalizer": (
        "src/price_action/risk/vol_target.py",
        "2019b12af282b64a1a32e93a3a32647ad00224deb8a44834e967e4d6e669d763",
    ),
    "breaker": (
        "src/price_action/risk/breaker.py",
        "e725f46c35e78edb2633b1d3b064617a3e7c7d5fe201d3794a0c82f5fea09e68",
    ),
    "realized_breaker_ledger": (
        "src/price_action/execution/trade_journal.py",
        "a2b3c1139d9c790cfc6d0a3a2f31f1327406c46ab9ae3462ccded12296e4785a",
    ),
}
_REQUIRED_RUNNER_SOURCE_FILES = (
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
_EXPECTED_TOP_LEVEL_FIELDS = {
    "schema_version",
    "mode",
    "evidence_eligible",
    "evidence_ineligible_reasons",
    "classification",
    "limitations",
    "disclosed_limitations",
    "external_live_gate_proxy_policy",
    "evaluation_protocol",
    "fair_improvement_rules",
    "fair_improvement_rules_sha256",
    "preregistration",
    "candidate_id",
    "scenario_order",
    "policy",
    "policy_sha256",
    "scenarios",
    "scenarios_sha256",
    "runtime_versions",
    "source_provenance",
    "universe",
    "time_range_utc",
    "data_lineage",
    "snapshots",
    "execution_governance",
    "market_loading",
    "funding",
    "daily_returns",
    "signal_stream",
    "results",
}
SIGNAL_REASON_ORDER = (
    "accepted",
    "confidence_below_minimum",
    "decision_stop_distance_below_minimum",
    "missing_next_bar",
    "duplicate_signal_fingerprint",
)
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_GIT_COMMIT = re.compile(r"^[0-9a-f]{40}$")
FOLD_WINDOWS = tuple(
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

_EXPECTED_SCENARIOS: dict[str, dict[str, float | str]] = {
    "B": {
        "name": "B",
        "fee_bps_per_fill": 4.0,
        "spread_slippage_bps_per_fill": 20.0,
        "impact_bps_per_fill": 4.5,
        "cost_multiplier": 1.0,
        "funding_multiplier": 1.0,
        "positive_price_pnl_multiplier": 1.0,
        "negative_price_pnl_multiplier": 1.0,
    },
    "C2": {
        "name": "C2",
        "fee_bps_per_fill": 4.0,
        "spread_slippage_bps_per_fill": 20.0,
        "impact_bps_per_fill": 4.5,
        "cost_multiplier": 2.0,
        "funding_multiplier": 2.0,
        "positive_price_pnl_multiplier": 1.0,
        "negative_price_pnl_multiplier": 1.0,
    },
    "H": {
        "name": "H",
        "fee_bps_per_fill": 4.0,
        "spread_slippage_bps_per_fill": 20.0,
        "impact_bps_per_fill": 4.5,
        "cost_multiplier": 1.0,
        "funding_multiplier": 1.0,
        "positive_price_pnl_multiplier": 0.50,
        "negative_price_pnl_multiplier": 1.25,
    },
}

_EXPECTED_EXTERNAL_PROXY_POLICY = {
    "FNG_dependent_filters_when_value_is_missing": "no_rejection_fail_open_proxy",
    "FNG_history_in_frozen_snapshots": False,
    "bias_direction_known": False,
    "exchange_state_stale_and_API_rate_limit_rejections": "not_simulated",
    "historical_exchange_rounding_and_margin_tiers": "not_simulated",
    "historical_mark_L1_and_queue_state_in_frozen_snapshots": False,
    "limitation_disclosure_required_in_every_result": True,
    "post_only_maker_fill_assumption": "not_used",
    "wrapper_header_fixed_starting_equity_comment_is_not_runtime_sizing_authority": True,
}

_EXPECTED_FAIR_IMPROVEMENT_RULES = {
    "absolute_challenger_hard_gates_still_required": True,
    "comparison_scenario": "H",
    "exact_legacy_rule_labels": {
        "better_rule_1": (
            "H_trimmed_return_at_least_max_10pct_or_v15p2_plus_1p5pp_and_DD_no_more_than_1pp_worse"
        ),
        "better_rule_2": "H_return_within_1pp_of_v15p2_and_DD_at_least_25pct_lower",
        "negative_months_and_worst_month_may_not_be_worse": True,
    },
    "old_21p36_headline_may_not_substitute_for_this_baseline": True,
    "pass_logic": "rule_1_or_rule_2_and_stability_noninferiority",
    "rule_1": {
        "challenger_H_max_MTM_drawdown_may_be_at_most_pp_worse": 1.0,
        "challenger_H_trimmed_mean_monthly_return_pct_min_formula": (
            "max_10pct_or_baseline_plus_1p5pp"
        ),
    },
    "rule_2": {
        "challenger_H_max_MTM_drawdown_reduction_vs_baseline_min_fraction": 0.25,
        "challenger_H_trimmed_mean_monthly_return_must_be_within_pp_of_baseline": 1.0,
    },
    "same_snapshot_universe_period_execution_costs_and_metric_code_required": True,
    "stability_noninferiority": {
        "challenger_H_negative_month_count_may_not_be_worse": True,
        "challenger_H_worst_month_may_not_be_worse": True,
    },
}

_EXPECTED_RAW_LIMITATIONS = (
    "funding_snapshot_not_rebuilt_under_v3_vendor_lineage",
    "four_symbols_retain_two_official_vendor_gap_windows_without_synthetic_rows",
    "static_survivor_primary_universe",
    "no_historical_tick_lot_or_margin_tier_replay",
    "no_historical_order_book_queue_or_submission_latency",
    "no_point_in_time_FNG_snapshot",
    "no_exchange_state_stale_or_rate_limit_path",
    "next_open_is_a_research_execution_proxy_not_a_fill_claim",
    "deployed_VSA_confirmation_close_plus_minus_2ATR_fallback_is_preserved_not_corrected",
    "inert_YAML_exit_engine_differs_from_live_wrapper_30_30_40_authority",
    "no_historical_availableBalance_or_exchange_margin_state",
    "no_exact_historical_L1_rounding_trailing_or_time_stop_mark_sampling",
    "replay_time_stop_is_unconditional_after_30_bars_but_live_rechecks_1R_mark",
    "historical_pseudo_OOS_is_not_genuine_prospective_evidence",
)

_EXPECTED_RAW_CLASSIFICATION = {
    "result_label": "FAIR_LIVE_POLICY_PROXY",
    "strategy": "FAIR_LIVE_POLICY_PROXY",
    "execution": "NEXT_OPEN_BAR_EXECUTION_PROXY",
    "exact_live_replay_claim_allowed": False,
    "deployment_decision_authorized": False,
    "historical_pseudo_oos_is_independent_prospective_evidence": False,
}

_EXPECTED_DECISION = {
    "verdict": VERDICT,
    "measurement_label": "FAIR_LIVE_POLICY_PROXY",
    "execution_label": "NEXT_OPEN_BAR_EXECUTION_PROXY",
    "winner_declared": False,
    "challenger_comparison_performed": False,
    "holdout_run_by_reporter": False,
    "paper_authorized": False,
    "live_deployment_authorized": False,
    "baseline_measurement_is_not_a_deployment_decision": True,
}

_RESULT_LISTS = (
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

_REQUIRED_LIMITATIONS = (
    {
        "code": "funding_snapshot_not_rebuilt_under_v3_vendor_lineage",
        "detail": (
            "Funding uses the independently frozen v1 snapshot; it was not rebuilt or "
            "vendor-checksum-audited by the V3 market-data process."
        ),
    },
    {
        "code": "official_vendor_gaps_preserved",
        "detail": (
            "SOL, ZEC, NEAR, and FIL retain two official vendor gap windows; no synthetic, "
            "interpolated, resampled, or forward-filled bars were added."
        ),
    },
    {
        "code": "repaired_scanner_not_running_pid_history",
        "detail": (
            "Replay identity includes the repaired completed-window scanner, exact-correlation/"
            "journal, and protective-stop risk sources; it is not an exact historical replay "
            "of the already-running pre-repair PID image."
        ),
    },
    {
        "code": "fng_missing_fail_open_proxy",
        "detail": (
            "Point-in-time Fear & Greed is absent, so F&G-dependent gates allow rather than "
            "reject; the direction of this bias is unknown."
        ),
    },
    {
        "code": "deployed_vsa_stop_fallback",
        "detail": (
            "VSA preserves the deployed confirmation-close plus/minus 2 ATR fallback instead "
            "of claiming a repaired structural stop."
        ),
    },
    {
        "code": "inert_yaml_exit_authority_drift",
        "detail": (
            "The YAML exit_engine block is inert for the deployed wrapper; the replay follows "
            "the wrapper's authoritative 30/30/40 partial-exit path."
        ),
    },
    {
        "code": "next_open_execution_proxy",
        "detail": "Next-bar open plus fixed costs is a research proxy, not an exchange fill claim.",
    },
    {
        "code": "l1_queue_latency_unavailable",
        "detail": "Historical L1, order queue, post-only fallback, and submission latency are absent.",
    },
    {
        "code": "rounding_and_margin_tiers_unavailable",
        "detail": "Historical tick/lot rounding, minimum-notional changes, and margin tiers are absent.",
    },
    {
        "code": "available_balance_proxy",
        "detail": (
            "Historical exchange availableBalance is absent; wallet and margin availability are "
            "modelled by the preregistered portfolio proxy."
        ),
    },
    {
        "code": "trail_and_time_stop_proxy",
        "detail": (
            "Trailing-stop and runner time-stop decisions use completed bars, not the live "
            "intrabar mark sampling path."
        ),
    },
)


class BaselineReportContractError(ValueError):
    """Input evidence does not satisfy the frozen baseline report contract."""


@dataclass(frozen=True, slots=True)
class JsonArtifact:
    path: Path
    payload: dict[str, Any]
    file_bytes: int
    sha256: str

    def provenance(self) -> dict[str, Any]:
        return {
            "path": str(self.path),
            "file_bytes": self.file_bytes,
            "sha256": self.sha256,
        }


@dataclass(frozen=True, slots=True)
class _Curve:
    timestamps: tuple[pd.Timestamp, ...]
    navs: tuple[float, ...]
    wallets: tuple[float, ...]
    gross_unrealized: tuple[float, ...]
    adjusted_unrealized: tuple[float, ...]
    accrued_exit_costs: tuple[float, ...]
    open_counts: tuple[int, ...]


def _reject_json_constant(value: str) -> None:
    raise BaselineReportContractError(f"non-finite JSON constant is forbidden: {value}")


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise BaselineReportContractError(f"duplicate JSON key is forbidden: {key!r}")
        result[key] = value
    return result


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def load_json_artifact(path: Path) -> JsonArtifact:
    """Load strict UTF-8 JSON and preserve its byte identity."""

    try:
        resolved = path.resolve(strict=True)
    except FileNotFoundError as exc:
        raise BaselineReportContractError(f"input does not exist: {path}") from exc
    if not resolved.is_file() or resolved.suffix.lower() != ".json":
        raise BaselineReportContractError("input must be a regular .json file")
    encoded = resolved.read_bytes()
    try:
        payload = json.loads(
            encoded.decode("utf-8"),
            parse_constant=_reject_json_constant,
            object_pairs_hook=_unique_object,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BaselineReportContractError(f"invalid UTF-8 JSON input: {resolved}") from exc
    if not isinstance(payload, dict):
        raise BaselineReportContractError("input JSON must be a top-level object")
    return JsonArtifact(
        path=resolved,
        payload=payload,
        file_bytes=len(encoded),
        sha256=_sha256_bytes(encoded),
    )


def _mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise BaselineReportContractError(f"{name} must be a JSON object")
    return value


def _list(value: Any, name: str) -> list[Any]:
    if not isinstance(value, list):
        raise BaselineReportContractError(f"{name} must be a JSON array")
    return value


def _finite(value: Any, name: str, *, positive: bool = False, nonnegative: bool = False) -> float:
    if isinstance(value, bool):
        raise BaselineReportContractError(f"{name} must be numeric")
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise BaselineReportContractError(f"{name} must be numeric") from exc
    if not math.isfinite(parsed):
        raise BaselineReportContractError(f"{name} must be finite")
    if positive and parsed <= 0.0:
        raise BaselineReportContractError(f"{name} must be > 0")
    if nonnegative and parsed < 0.0:
        raise BaselineReportContractError(f"{name} must be >= 0")
    return parsed


def _integer(value: Any, name: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise BaselineReportContractError(f"{name} must be an integer >= {minimum}")
    return value


def _utc(value: Any, name: str) -> pd.Timestamp:
    try:
        timestamp = pd.Timestamp(value)
    except (TypeError, ValueError) as exc:
        raise BaselineReportContractError(f"{name} must be a UTC timestamp") from exc
    if timestamp.tzinfo is None or timestamp.utcoffset() != pd.Timedelta(0):
        raise BaselineReportContractError(f"{name} must be timezone-aware UTC")
    return timestamp.tz_convert("UTC")


def _assert_json_tree(value: Any, name: str = "payload") -> None:
    if value is None or isinstance(value, str | bool):
        return
    if isinstance(value, int):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise BaselineReportContractError(f"{name} contains a non-finite number")
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _assert_json_tree(item, f"{name}[{index}]")
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise BaselineReportContractError(f"{name} contains a non-string key")
            _assert_json_tree(item, f"{name}.{key}")
        return
    raise BaselineReportContractError(f"{name} contains a non-JSON value: {type(value).__name__}")


def _canonical_hash(value: Any) -> str:
    try:
        encoder = json.JSONEncoder(sort_keys=True, separators=(",", ":"), allow_nan=False)
        digest = hashlib.sha256()
        for chunk in encoder.iterencode(value):
            digest.update(chunk.encode("utf-8"))
    except (TypeError, ValueError) as exc:
        raise BaselineReportContractError("evidence is not canonical strict JSON") from exc
    return digest.hexdigest()


def _same(left: float, right: float, name: str) -> None:
    if not math.isclose(left, right, rel_tol=1e-10, abs_tol=1e-7):
        raise BaselineReportContractError(f"{name} reconciliation failed: {left!r} != {right!r}")


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise BaselineReportContractError(f"{name} must be a non-empty string")
    return value


def _sha256_text(value: Any, name: str) -> str:
    digest = _text(value, name)
    if not _SHA256.fullmatch(digest):
        raise BaselineReportContractError(f"{name} must be a lowercase SHA-256 digest")
    return digest


def _git_commit_text(value: Any, name: str) -> str:
    commit = _text(value, name)
    if not _GIT_COMMIT.fullmatch(commit):
        raise BaselineReportContractError(f"{name} must be a lowercase 40-character commit")
    return commit


def _exact_scenario(value: Any, scenario: str, name: str) -> None:
    actual = _mapping(value, name)
    expected = _EXPECTED_SCENARIOS[scenario]
    if set(actual) != set(expected):
        raise BaselineReportContractError(f"{name} fields differ from canonical {scenario}")
    for key, expected_value in expected.items():
        actual_value = actual[key]
        if isinstance(expected_value, str):
            if actual_value != expected_value:
                raise BaselineReportContractError(f"{name}.{key} is not canonical")
        else:
            _same(_finite(actual_value, f"{name}.{key}"), expected_value, f"{name}.{key}")


def _exact_keys(value: Mapping[str, Any], expected: set[str], name: str) -> None:
    if set(value) != expected:
        missing = sorted(expected.difference(value))
        extra = sorted(set(value).difference(expected))
        raise BaselineReportContractError(
            f"{name} fields drifted; missing={missing}, extra={extra}"
        )


def _validate_runtime_versions(value: Any, name: str) -> Mapping[str, Any]:
    runtime = _mapping(value, name)
    if runtime != EXPECTED_RUNTIME_VERSIONS:
        raise BaselineReportContractError(f"{name} differs from the frozen runtime versions")
    return runtime


def _validate_source_provenance(value: Any, name: str) -> Mapping[str, Any]:
    source = _mapping(value, name)
    _exact_keys(
        source,
        {
            "git_commit",
            "research_source_clean",
            "research_source_status",
            "missing_source_files",
            "file_sha256",
            "reference_source_checks",
            "exact_reference_source_hashes_match",
        },
        name,
    )
    _git_commit_text(source.get("git_commit"), f"{name}.git_commit")
    if source.get("research_source_clean") is not True:
        raise BaselineReportContractError(f"{name}.research_source_clean must be true")
    if source.get("research_source_status") != []:
        raise BaselineReportContractError(f"{name}.research_source_status must be empty")
    if source.get("missing_source_files") != []:
        raise BaselineReportContractError(f"{name}.missing_source_files must be empty")
    if source.get("exact_reference_source_hashes_match") is not True:
        raise BaselineReportContractError(
            f"{name}.exact_reference_source_hashes_match must be true"
        )

    source_hashes = _mapping(source.get("file_sha256"), f"{name}.file_sha256")
    required_files = set(_REQUIRED_RUNNER_SOURCE_FILES).union(
        path for path, _digest in _EXPECTED_REFERENCE_SOURCES.values()
    )
    if set(source_hashes) != required_files:
        raise BaselineReportContractError(f"{name}.file_sha256 source scope drifted")
    for relative, digest in source_hashes.items():
        _sha256_text(digest, f"{name}.file_sha256[{relative!r}]")
    if source_hashes.get(CANONICAL_PREREG_RELATIVE) != EXPECTED_PREREG_SHA256:
        raise BaselineReportContractError(f"{name} is not bound to the frozen preregistration")
    if source_hashes.get("requirements-lock.txt") != EXPECTED_REQUIREMENTS_LOCK_SHA256:
        raise BaselineReportContractError(f"{name} requirements lock identity drifted")

    checks = _mapping(source.get("reference_source_checks"), f"{name}.reference_source_checks")
    if set(checks) != set(_REFERENCE_SOURCE_KEYS):
        raise BaselineReportContractError(f"{name}.reference_source_checks scope drifted")
    for key in _REFERENCE_SOURCE_KEYS:
        check = _mapping(checks[key], f"{name}.reference_source_checks.{key}")
        _exact_keys(
            check,
            {"path", "expected_sha256", "actual_sha256", "matches"},
            f"{name}.reference_source_checks.{key}",
        )
        expected_path, expected_digest = _EXPECTED_REFERENCE_SOURCES[key]
        if check.get("path") != expected_path:
            raise BaselineReportContractError(f"{name}.{key} reference path drifted")
        if check.get("expected_sha256") != expected_digest:
            raise BaselineReportContractError(f"{name}.{key} expected reference hash drifted")
        if check.get("actual_sha256") != expected_digest or check.get("matches") is not True:
            raise BaselineReportContractError(f"{name}.{key} reference hash did not match")
        if source_hashes.get(expected_path) != expected_digest:
            raise BaselineReportContractError(f"{name}.{key} file hash reconciliation failed")
    return source


def _canonical_repo_root(prereg_path: str) -> str:
    path = Path(prereg_path)
    if not path.is_absolute() or path.name != Path(CANONICAL_PREREG_RELATIVE).name:
        raise BaselineReportContractError("preregistration path is not absolute/canonical")
    if path.parent.name != "configs":
        raise BaselineReportContractError("preregistration path is not under canonical configs")
    return os.path.normpath(str(path.parent.parent))


def _verify_current_source_identity(source: Mapping[str, Any], prereg_path: str) -> None:
    """Reject reporting through a source tree that differs from the replay tree."""

    repo_root = Path(_canonical_repo_root(prereg_path))
    source_hashes = _mapping(source.get("file_sha256"), "source_provenance.file_sha256")
    for relative, expected_digest in source_hashes.items():
        candidate = repo_root / relative
        try:
            encoded = candidate.read_bytes()
        except OSError as exc:
            raise BaselineReportContractError(
                f"current reporter source is missing or unreadable: {relative}"
            ) from exc
        actual_digest = _sha256_bytes(encoded)
        if actual_digest != expected_digest:
            raise BaselineReportContractError(
                f"current reporter source differs from replay provenance: {relative}"
            )


def _validate_snapshot_set(value: Any, prereg_path: str, name: str) -> Mapping[str, Any]:
    snapshots = _mapping(value, name)
    if set(snapshots) != {"market", "funding"}:
        raise BaselineReportContractError(f"{name} must contain exact market/funding")
    repo_root = _canonical_repo_root(prereg_path)
    for snapshot_name, expected in EXPECTED_SNAPSHOT_IDENTITIES.items():
        snapshot = _mapping(snapshots[snapshot_name], f"{name}.{snapshot_name}")
        _exact_keys(
            snapshot,
            {"name", "configured_path", "resolved_path", "bytes", "sha256", "status"},
            f"{name}.{snapshot_name}",
        )
        if snapshot.get("name") != snapshot_name or snapshot.get("status") != "VERIFIED":
            raise BaselineReportContractError(f"{name}.{snapshot_name} is not VERIFIED")
        if snapshot.get("configured_path") != expected["configured_path"]:
            raise BaselineReportContractError(f"{name}.{snapshot_name} configured path drifted")
        expected_resolved = os.path.normpath(
            os.path.join(repo_root, str(expected["configured_path"]))
        )
        resolved = _text(snapshot.get("resolved_path"), f"{name}.{snapshot_name}.resolved_path")
        if not os.path.isabs(resolved) or os.path.normpath(resolved) != expected_resolved:
            raise BaselineReportContractError(f"{name}.{snapshot_name} resolved path drifted")
        if (
            _integer(snapshot.get("bytes"), f"{name}.{snapshot_name}.bytes", minimum=1)
            != (expected["bytes"])
        ):
            raise BaselineReportContractError(f"{name}.{snapshot_name} byte size drifted")
        if (
            _sha256_text(snapshot.get("sha256"), f"{name}.{snapshot_name}.sha256")
            != (expected["sha256"])
        ):
            raise BaselineReportContractError(f"{name}.{snapshot_name} SHA-256 drifted")
    return snapshots


def _validate_data_lineage(value: Any, prereg_path: str, name: str) -> Mapping[str, Any]:
    lineage = _mapping(value, name)
    if set(lineage) != set(EXPECTED_DATA_LINEAGE_IDENTITIES):
        raise BaselineReportContractError(f"{name} lineage scope drifted")
    repo_root = _canonical_repo_root(prereg_path)
    for artifact_name, expected in EXPECTED_DATA_LINEAGE_IDENTITIES.items():
        artifact = _mapping(lineage[artifact_name], f"{name}.{artifact_name}")
        _exact_keys(
            artifact,
            {"name", "configured_path", "resolved_path", "bytes", "sha256", "status"},
            f"{name}.{artifact_name}",
        )
        if artifact.get("name") != artifact_name or artifact.get("status") != "VERIFIED":
            raise BaselineReportContractError(f"{name}.{artifact_name} is not VERIFIED")
        if artifact.get("configured_path") != expected["configured_path"]:
            raise BaselineReportContractError(f"{name}.{artifact_name} configured path drifted")
        expected_resolved = os.path.normpath(
            os.path.join(repo_root, str(expected["configured_path"]))
        )
        resolved = _text(artifact.get("resolved_path"), f"{name}.{artifact_name}.resolved_path")
        if not os.path.isabs(resolved) or os.path.normpath(resolved) != expected_resolved:
            raise BaselineReportContractError(f"{name}.{artifact_name} resolved path drifted")
        if (
            _integer(artifact.get("bytes"), f"{name}.{artifact_name}.bytes", minimum=1)
            != (expected["bytes"])
        ):
            raise BaselineReportContractError(f"{name}.{artifact_name} byte size drifted")
        if (
            _sha256_text(artifact.get("sha256"), f"{name}.{artifact_name}.sha256")
            != (expected["sha256"])
        ):
            raise BaselineReportContractError(f"{name}.{artifact_name} SHA-256 drifted")
    return lineage


def _validate_loaded_inputs(raw: Mapping[str, Any]) -> None:
    governance = _mapping(raw.get("execution_governance"), "execution_governance")
    mutation = _mapping(governance.get("input_mutation_checks"), "input_mutation_checks")

    market = _mapping(raw.get("market_loading"), "market_loading")
    _exact_keys(
        market,
        {
            "symbols",
            "tradable_symbols",
            "reference_symbol",
            "reference_symbol_traded",
            "alignment",
            "global_intersection_performed",
            "forward_fill_performed",
            "history_rows_by_symbol",
            "first_ts_by_symbol",
            "last_ts_by_symbol",
            "engine_validation_start_inclusive",
            "engine_rows_by_symbol",
        },
        "market_loading",
    )
    all_symbols = (*PRIMARY_SYMBOLS, REFERENCE_SYMBOL)
    if market.get("symbols") != list(all_symbols):
        raise BaselineReportContractError("market_loading.symbols identity drifted")
    if market.get("tradable_symbols") != list(PRIMARY_SYMBOLS):
        raise BaselineReportContractError("market_loading tradable symbols drifted")
    if market.get("reference_symbol") != REFERENCE_SYMBOL:
        raise BaselineReportContractError("market_loading reference symbol drifted")
    expected_market_flags = {
        "reference_symbol_traded": False,
        "alignment": "INDEPENDENT_SYMBOL_FRAMES",
        "global_intersection_performed": False,
        "forward_fill_performed": False,
    }
    for key, expected in expected_market_flags.items():
        if market.get(key) != expected:
            raise BaselineReportContractError(f"market_loading.{key} drifted")
    if (
        _utc(
            market.get("engine_validation_start_inclusive"),
            "market_loading.engine_validation_start_inclusive",
        )
        != EVALUATION_START - BAR
    ):
        raise BaselineReportContractError("market engine validation start drifted")

    history_rows = _mapping(
        market.get("history_rows_by_symbol"), "market_loading.history_rows_by_symbol"
    )
    first_timestamps = _mapping(
        market.get("first_ts_by_symbol"), "market_loading.first_ts_by_symbol"
    )
    last_timestamps = _mapping(market.get("last_ts_by_symbol"), "market_loading.last_ts_by_symbol")
    for label, values in (
        ("history_rows_by_symbol", history_rows),
        ("first_ts_by_symbol", first_timestamps),
        ("last_ts_by_symbol", last_timestamps),
    ):
        if set(values) != set(all_symbols):
            raise BaselineReportContractError(f"market_loading.{label} scope drifted")
    for symbol in all_symbols:
        _integer(history_rows[symbol], f"market history rows {symbol}", minimum=1)
        first = _utc(first_timestamps[symbol], f"market first timestamp {symbol}")
        last = _utc(last_timestamps[symbol], f"market last timestamp {symbol}")
        if not HISTORY_START <= first <= last < EVALUATION_END:
            raise BaselineReportContractError(f"market timestamp range for {symbol} drifted")
        if (first - HISTORY_START) % BAR or (last - HISTORY_START) % BAR:
            raise BaselineReportContractError(f"market timestamp grid for {symbol} drifted")
        if symbol in PRIMARY_SYMBOLS and last != EVALUATION_END - BAR:
            raise BaselineReportContractError(f"market primary tail for {symbol} drifted")

    engine_rows = _mapping(
        market.get("engine_rows_by_symbol"), "market_loading.engine_rows_by_symbol"
    )
    frame_hashes = _mapping(
        mutation.get("engine_frames_sha256_by_symbol"),
        "input_mutation_checks.engine_frames_sha256_by_symbol",
    )
    if set(engine_rows) != set(PRIMARY_SYMBOLS):
        raise BaselineReportContractError("market engine row scope drifted")
    if set(frame_hashes) != set(PRIMARY_SYMBOLS):
        raise BaselineReportContractError("market engine-frame mutation hash scope drifted")
    for symbol in PRIMARY_SYMBOLS:
        rows = _integer(engine_rows[symbol], f"engine rows {symbol}", minimum=2)
        if rows > _integer(history_rows[symbol], f"history rows {symbol}", minimum=2):
            raise BaselineReportContractError(f"engine rows exceed history rows for {symbol}")
        _sha256_text(frame_hashes[symbol], f"engine frame hash {symbol}")

    funding = _mapping(raw.get("funding"), "funding")
    _exact_keys(
        funding,
        {
            "source",
            "symbols",
            "event_count",
            "rows_by_symbol_including_history",
            "raw_fractional_timestamps_preserved",
            "invalid_mark_price_falls_back_in_engine",
        },
        "funding",
    )
    if funding.get("source") != "OBSERVED_FROZEN_FUNDING_EVENTS":
        raise BaselineReportContractError("funding source identity drifted")
    if funding.get("symbols") != list(PRIMARY_SYMBOLS):
        raise BaselineReportContractError("funding symbol identity drifted")
    if funding.get("raw_fractional_timestamps_preserved") is not True:
        raise BaselineReportContractError("funding raw timestamp contract drifted")
    if funding.get("invalid_mark_price_falls_back_in_engine") is not True:
        raise BaselineReportContractError("funding mark fallback contract drifted")
    _integer(funding.get("event_count"), "funding.event_count")
    funding_rows = _mapping(
        funding.get("rows_by_symbol_including_history"),
        "funding.rows_by_symbol_including_history",
    )
    if set(funding_rows) != set(PRIMARY_SYMBOLS):
        raise BaselineReportContractError("funding history-row scope drifted")
    for symbol in PRIMARY_SYMBOLS:
        _integer(funding_rows[symbol], f"funding rows {symbol}", minimum=1)
    _sha256_text(mutation.get("funding_events_sha256"), "funding mutation hash")

    returns = _mapping(raw.get("daily_returns"), "daily_returns")
    _exact_keys(
        returns,
        {"construction", "minimum_initial_common_observations", "row_count", "columns", "sha256"},
        "daily_returns",
    )
    if returns.get("construction") != "COMPLETE_CAUSAL_UTC_DAYS_ONLY":
        raise BaselineReportContractError("daily-return construction identity drifted")
    if returns.get("minimum_initial_common_observations") != 90:
        raise BaselineReportContractError("daily-return minimum observation identity drifted")
    _integer(returns.get("row_count"), "daily_returns.row_count", minimum=90)
    if returns.get("columns") != list(PRIMARY_SYMBOLS):
        raise BaselineReportContractError("daily-return columns/order drifted")
    returns_hash = _sha256_text(returns.get("sha256"), "daily_returns.sha256")
    if mutation.get("daily_returns_sha256") != returns_hash:
        raise BaselineReportContractError("daily-return mutation hash mismatch")


def _validate_top_level(raw: Mapping[str, Any]) -> None:
    _assert_json_tree(raw)
    _exact_keys(raw, _EXPECTED_TOP_LEVEL_FIELDS, "raw payload")
    if raw.get("schema_version") != RAW_SCHEMA:
        raise BaselineReportContractError(f"schema_version must be {RAW_SCHEMA!r}")
    if raw.get("mode") != FULL_REPLAY_MODE:
        raise BaselineReportContractError("only the full frozen primary13 replay is reportable")
    if raw.get("evidence_eligible") is not True:
        raise BaselineReportContractError("raw replay is not evidence eligible")
    if raw.get("evidence_ineligible_reasons") != []:
        raise BaselineReportContractError("evidence_ineligible_reasons must be empty")
    if raw.get("scenario_order") != list(SCENARIO_ORDER):
        raise BaselineReportContractError("scenario order must be exactly B, C2, H")
    if raw.get("candidate_id") != "v15p2_fair_baseline":
        raise BaselineReportContractError("candidate_id must be the frozen fair baseline")

    classification = _mapping(raw.get("classification"), "classification")
    if classification != _EXPECTED_RAW_CLASSIFICATION:
        raise BaselineReportContractError("raw classification differs from the frozen proxy labels")
    if (
        _mapping(raw.get("external_live_gate_proxy_policy"), "external_live_gate_proxy_policy")
        != _EXPECTED_EXTERNAL_PROXY_POLICY
    ):
        raise BaselineReportContractError("external live-gate proxy policy drifted")
    improvement = _mapping(raw.get("fair_improvement_rules"), "fair_improvement_rules")
    if improvement != _EXPECTED_FAIR_IMPROVEMENT_RULES:
        raise BaselineReportContractError("fair-improvement rules drifted")
    if raw.get("fair_improvement_rules_sha256") != _canonical_hash(improvement):
        raise BaselineReportContractError("fair_improvement_rules_sha256 mismatch")

    preregistration = _mapping(raw.get("preregistration"), "preregistration")
    _exact_keys(
        preregistration,
        {"path", "sha256", "schema_version", "status", "live_deployment_authorized"},
        "preregistration",
    )
    if preregistration.get("schema_version") != ("crypto-15m-v15p2-fair-baseline-prereg-v2"):
        raise BaselineReportContractError("preregistration schema identity drifted")
    if preregistration.get("status") != "PREREGISTERED_NO_RESULTS_SEEN":
        raise BaselineReportContractError("preregistration is not frozen pre-result evidence")
    if preregistration.get("live_deployment_authorized") is not False:
        raise BaselineReportContractError("preregistration improperly authorizes deployment")
    preregistration_sha256 = _sha256_text(preregistration.get("sha256"), "preregistration.sha256")
    if preregistration_sha256 != EXPECTED_PREREG_SHA256:
        raise BaselineReportContractError("preregistration SHA-256 is not the frozen baseline")
    prereg_path = _text(preregistration.get("path"), "preregistration.path")
    _canonical_repo_root(prereg_path)

    time_range = _mapping(raw.get("time_range_utc"), "time_range_utc")
    if _utc(time_range.get("history_start_inclusive"), "history_start") != HISTORY_START:
        raise BaselineReportContractError("history start drifted")
    if _utc(time_range.get("evaluation_start_inclusive"), "evaluation_start") != EVALUATION_START:
        raise BaselineReportContractError("evaluation start drifted")
    if _utc(time_range.get("end_exclusive"), "evaluation_end") != EVALUATION_END:
        raise BaselineReportContractError("evaluation end drifted")

    protocol = _mapping(raw.get("evaluation_protocol"), "evaluation_protocol")
    expected_protocol_fields = {
        "development",
        "pseudo_oos",
        "walk_forward_folds",
        "fold_count",
        "fold_months_each",
        "interval_semantics",
    }
    if set(protocol) != expected_protocol_fields:
        raise BaselineReportContractError("evaluation protocol differs from exact 24/36/6x6 plan")
    development = _list(protocol.get("development"), "evaluation_protocol.development")
    pseudo = _list(protocol.get("pseudo_oos"), "evaluation_protocol.pseudo_oos")
    raw_folds = _list(protocol.get("walk_forward_folds"), "evaluation_protocol.walk_forward_folds")
    if len(development) != 2 or tuple(
        _utc(value, "evaluation_protocol.development") for value in development
    ) != (EVALUATION_START, DEVELOPMENT_END):
        raise BaselineReportContractError("development window differs from exact 24 months")
    if len(pseudo) != 2 or tuple(
        _utc(value, "evaluation_protocol.pseudo_oos") for value in pseudo
    ) != (DEVELOPMENT_END, EVALUATION_END):
        raise BaselineReportContractError("pseudo-OOS window differs from exact 36 months")
    parsed_folds: list[tuple[pd.Timestamp, pd.Timestamp]] = []
    for index, value in enumerate(raw_folds):
        window = _list(value, f"evaluation_protocol.walk_forward_folds[{index}]")
        if len(window) != 2:
            raise BaselineReportContractError("every walk-forward fold must have two endpoints")
        parsed_folds.append(
            (
                _utc(window[0], f"fold {index + 1} start"),
                _utc(window[1], f"fold {index + 1} end"),
            )
        )
    if (
        tuple(parsed_folds) != FOLD_WINDOWS
        or protocol.get("fold_count") != 6
        or protocol.get("fold_months_each") != [6, 6, 6, 6, 6, 6]
        or protocol.get("interval_semantics") != "half_open_start_inclusive_end_exclusive"
    ):
        raise BaselineReportContractError("evaluation protocol differs from exact 24/36/6x6 plan")

    scenarios = _mapping(raw.get("scenarios"), "scenarios")
    if tuple(scenarios) != SCENARIO_ORDER or set(scenarios) != set(SCENARIO_ORDER):
        raise BaselineReportContractError("top-level scenarios must be exact ordered B/C2/H")
    for scenario in SCENARIO_ORDER:
        _exact_scenario(scenarios[scenario], scenario, f"scenarios.{scenario}")
    if raw.get("scenarios_sha256") != _canonical_hash(scenarios):
        raise BaselineReportContractError("scenarios_sha256 mismatch")

    policy = _mapping(raw.get("policy"), "policy")
    if raw.get("policy_sha256") != _canonical_hash(policy):
        raise BaselineReportContractError("policy_sha256 mismatch")

    governance = _mapping(raw.get("execution_governance"), "execution_governance")
    _exact_keys(
        governance,
        {
            "canonical_prereg_path",
            "canonical_prereg_semantic_match",
            "canonical_prereg_preflight_sha256",
            "canonical_prereg_postflight_sha256",
            "clean_source_preflight_before_snapshot_access",
            "exact_reference_source_hashes_preflight",
            "source_unchanged_postflight",
            "runtime_unchanged_postflight",
            "lineage_reverified_postflight",
            "lineage_unchanged_postflight",
            "snapshots_reverified_postflight",
            "snapshots_unchanged_postflight",
            "preflight_source",
            "postflight_source",
            "preflight_runtime",
            "postflight_runtime",
            "postflight_data_lineage",
            "postflight_snapshots",
            "input_mutation_checks",
        },
        "execution_governance",
    )
    if governance.get("canonical_prereg_path") != prereg_path:
        raise BaselineReportContractError("execution governance preregistration path mismatch")
    for key in (
        "canonical_prereg_semantic_match",
        "clean_source_preflight_before_snapshot_access",
        "exact_reference_source_hashes_preflight",
        "source_unchanged_postflight",
        "runtime_unchanged_postflight",
        "lineage_reverified_postflight",
        "lineage_unchanged_postflight",
        "snapshots_reverified_postflight",
        "snapshots_unchanged_postflight",
    ):
        if governance.get(key) is not True:
            raise BaselineReportContractError(f"execution_governance.{key} must be true")
    mutation = _mapping(governance.get("input_mutation_checks"), "input_mutation_checks")
    _exact_keys(
        mutation,
        {
            "engine_frames_sha256_by_symbol",
            "signal_decision_ledger_sha256",
            "signal_batch_intents_sha256",
            "entry_intents_sha256",
            "funding_events_sha256",
            "daily_returns_sha256",
            "all_unchanged",
        },
        "input_mutation_checks",
    )
    if mutation.get("all_unchanged") is not True:
        raise BaselineReportContractError("engine input mutation checks did not pass")
    for key in (
        "canonical_prereg_preflight_sha256",
        "canonical_prereg_postflight_sha256",
    ):
        if _sha256_text(governance.get(key), f"execution_governance.{key}") != (
            preregistration_sha256
        ):
            raise BaselineReportContractError(f"execution_governance.{key} mismatch")

    universe = _mapping(raw.get("universe"), "universe")
    if universe.get("tradable_symbols") != list(PRIMARY_SYMBOLS):
        raise BaselineReportContractError("tradable universe must be exact ordered primary13")
    if universe.get("non_traded_reference_symbol") != REFERENCE_SYMBOL:
        raise BaselineReportContractError("BTC reference symbol identity drifted")
    if universe.get("holdout_symbols_accessed") != []:
        raise BaselineReportContractError("holdout access is forbidden")
    if universe.get("reference_symbol_traded") is not False:
        raise BaselineReportContractError("BTC reference symbol must not be traded")

    raw_limitations = _list(raw.get("limitations"), "limitations")
    if tuple(raw_limitations) != _EXPECTED_RAW_LIMITATIONS:
        raise BaselineReportContractError("raw limitations differ from the preregistered set")
    disclosed = _mapping(raw.get("disclosed_limitations"), "disclosed_limitations")
    if disclosed.get("required") is not True:
        raise BaselineReportContractError("limitation disclosure is not marked required")
    if disclosed.get("count") != len(_EXPECTED_RAW_LIMITATIONS):
        raise BaselineReportContractError("disclosed limitation count drifted")
    if disclosed.get("items") != raw_limitations:
        raise BaselineReportContractError("disclosed limitations differ from raw limitations")
    if disclosed.get("sha256") != _canonical_hash(raw_limitations):
        raise BaselineReportContractError("disclosed limitations hash mismatch")

    source = _validate_source_provenance(raw.get("source_provenance"), "source_provenance")
    _verify_current_source_identity(source, prereg_path)
    runtime = _validate_runtime_versions(raw.get("runtime_versions"), "runtime_versions")
    data_lineage = _validate_data_lineage(raw.get("data_lineage"), prereg_path, "data_lineage")
    snapshots = _validate_snapshot_set(raw.get("snapshots"), prereg_path, "snapshots")
    if (
        _validate_source_provenance(
            governance.get("preflight_source"), "execution_governance.preflight_source"
        )
        != source
    ):
        raise BaselineReportContractError("preflight source differs from top-level source")
    if (
        _validate_source_provenance(
            governance.get("postflight_source"), "execution_governance.postflight_source"
        )
        != source
    ):
        raise BaselineReportContractError("postflight source differs from top-level source")
    if (
        _validate_runtime_versions(
            governance.get("preflight_runtime"), "execution_governance.preflight_runtime"
        )
        != runtime
    ):
        raise BaselineReportContractError("preflight runtime differs from top-level runtime")
    if (
        _validate_runtime_versions(
            governance.get("postflight_runtime"), "execution_governance.postflight_runtime"
        )
        != runtime
    ):
        raise BaselineReportContractError("postflight runtime differs from top-level runtime")
    if (
        _validate_data_lineage(
            governance.get("postflight_data_lineage"),
            prereg_path,
            "postflight_data_lineage",
        )
        != data_lineage
    ):
        raise BaselineReportContractError("postflight data lineage differs from top-level lineage")
    if (
        _validate_snapshot_set(
            governance.get("postflight_snapshots"), prereg_path, "postflight_snapshots"
        )
        != snapshots
    ):
        raise BaselineReportContractError("postflight snapshots differ from top-level snapshots")
    _validate_loaded_inputs(raw)


_SIGNAL_DECISION_FIELDS = (
    "emission_index",
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
    "outcome",
    "reason",
)
_SIGNAL_INTENT_FIELDS = tuple(
    field
    for field in _SIGNAL_DECISION_FIELDS
    if field not in {"emission_index", "outcome", "reason"}
)
_SIGNAL_FINGERPRINT_FIELDS = (
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


def _validate_exact_fields(row: Mapping[str, Any], expected: Sequence[str], name: str) -> None:
    if set(row) != set(expected):
        missing = sorted(set(expected) - set(row))
        extra = sorted(set(row) - set(expected))
        raise BaselineReportContractError(
            f"{name} fields drifted; missing={missing}, extra={extra}"
        )


def _validate_signal_core(
    row: Mapping[str, Any], name: str, *, allow_missing_entry: bool
) -> tuple[pd.Timestamp, pd.Timestamp | None]:
    if row.get("candidate_id") != "v15p2_fair_baseline":
        raise BaselineReportContractError(f"{name}.candidate_id is foreign")
    decision_ts = _utc(row.get("decision_ts"), f"{name}.decision_ts")
    if not HISTORY_START <= decision_ts < EVALUATION_END:
        raise BaselineReportContractError(f"{name}.decision_ts escapes loaded history")
    if (decision_ts - HISTORY_START) % BAR != pd.Timedelta(0):
        raise BaselineReportContractError(f"{name}.decision_ts is off the 15m grid")

    entry_raw = row.get("entry_ts")
    entry_ts = None if entry_raw is None else _utc(entry_raw, f"{name}.entry_ts")
    entry_price_raw = row.get("entry_price")
    entry_distance_raw = row.get("entry_stop_distance_pct")
    entry_fields_are_null = (
        entry_ts is None and entry_price_raw is None and entry_distance_raw is None
    )
    entry_fields_are_complete = (
        entry_ts is not None and entry_price_raw is not None and entry_distance_raw is not None
    )
    if not (entry_fields_are_null or entry_fields_are_complete):
        raise BaselineReportContractError(f"{name} has a partial next-entry tuple")
    if not allow_missing_entry and entry_fields_are_null:
        raise BaselineReportContractError(f"{name} intent is missing its next entry bar")
    if entry_ts is not None and (entry_ts - decision_ts != BAR or entry_ts >= EVALUATION_END):
        raise BaselineReportContractError(f"{name}.entry_ts is not the next half-open 15m bar")

    symbol = _text(row.get("symbol"), f"{name}.symbol")
    if symbol not in PRIMARY_SYMBOLS:
        raise BaselineReportContractError(f"{name}.symbol is outside primary13")
    side = _text(row.get("side"), f"{name}.side")
    if side not in {"long", "short"}:
        raise BaselineReportContractError(f"{name}.side is invalid")
    strategy = _text(row.get("strategy"), f"{name}.strategy")
    if strategy not in SIGNAL_STRATEGY_ORDER:
        raise BaselineReportContractError(f"{name}.strategy is outside frozen v15p2")
    rank = _integer(row.get("strategy_rank"), f"{name}.strategy_rank")
    if rank != SIGNAL_STRATEGY_ORDER.index(strategy):
        raise BaselineReportContractError(f"{name}.strategy_rank drifted")
    _text(row.get("pattern_id"), f"{name}.pattern_id")

    _finite(row.get("confluence_score"), f"{name}.confluence_score")
    decision_close = _finite(row.get("decision_close"), f"{name}.decision_close", positive=True)
    reference = _finite(
        row.get("entry_reference_price"), f"{name}.entry_reference_price", positive=True
    )
    stop_price = _finite(row.get("stop_price"), f"{name}.stop_price", positive=True)
    _finite(row.get("take_profit_price"), f"{name}.take_profit_price", positive=True)
    _finite(row.get("suggested_size_atr"), f"{name}.suggested_size_atr", positive=True)
    decision_distance = _finite(
        row.get("decision_stop_distance_pct"),
        f"{name}.decision_stop_distance_pct",
        nonnegative=True,
    )
    _same(reference, decision_close, f"{name} decision reference")
    _same(
        decision_distance,
        abs(decision_close - stop_price) / decision_close,
        f"{name} decision stop distance",
    )
    if entry_ts is not None:
        entry_price = _finite(entry_price_raw, f"{name}.entry_price", positive=True)
        entry_distance = _finite(
            entry_distance_raw, f"{name}.entry_stop_distance_pct", nonnegative=True
        )
        _same(
            entry_distance,
            abs(entry_price - stop_price) / entry_price,
            f"{name} entry stop distance",
        )

    if row.get("signal_manifest_hash") != EXPECTED_SIGNAL_MANIFEST_HASHES[strategy]:
        raise BaselineReportContractError(f"{name}.signal_manifest_hash drifted")
    if row.get("config_sha256") != EXPECTED_CONFIG_SHA256:
        raise BaselineReportContractError(f"{name}.config_sha256 drifted")
    return decision_ts, entry_ts


def _validate_signal_decision(row: Mapping[str, Any], index: int) -> None:
    name = f"signal_stream.decision_ledger[{index}]"
    _validate_exact_fields(row, _SIGNAL_DECISION_FIELDS, name)
    if _integer(row.get("emission_index"), f"{name}.emission_index") != index:
        raise BaselineReportContractError("signal emission indexes are not contiguous")
    _, entry_ts = _validate_signal_core(row, name, allow_missing_entry=True)
    score = _finite(row.get("confluence_score"), f"{name}.confluence_score")
    distance = _finite(
        row.get("decision_stop_distance_pct"),
        f"{name}.decision_stop_distance_pct",
        nonnegative=True,
    )
    if score < 0.25:
        expected_reason = "confidence_below_minimum"
    elif distance < 0.025:
        expected_reason = "decision_stop_distance_below_minimum"
    elif entry_ts is None:
        expected_reason = "missing_next_bar"
    else:
        expected_reason = "accepted"
    reason = row.get("reason")
    if reason not in SIGNAL_REASON_ORDER:
        raise BaselineReportContractError(f"{name}.reason is outside the frozen taxonomy")
    if reason == "duplicate_signal_fingerprint":
        if expected_reason != "accepted":
            raise BaselineReportContractError(
                f"{name} duplicate reason bypasses an earlier eligibility gate"
            )
    elif reason != expected_reason:
        raise BaselineReportContractError(f"{name}.reason violates frozen gate order")
    expected_outcome = "accepted" if reason == "accepted" else "rejected"
    if row.get("outcome") != expected_outcome:
        raise BaselineReportContractError(f"{name}.outcome and reason disagree")


def _validate_signal_intent(row: Mapping[str, Any], index: int) -> None:
    name = f"signal_stream.entry_intents[{index}]"
    _validate_exact_fields(row, _SIGNAL_INTENT_FIELDS, name)
    _, entry_ts = _validate_signal_core(row, name, allow_missing_entry=False)
    if entry_ts is None or not EVALUATION_START <= entry_ts < EVALUATION_END:
        raise BaselineReportContractError(f"{name} is not an evaluation intent")
    if _finite(row.get("confluence_score"), f"{name}.confluence_score") < 0.25:
        raise BaselineReportContractError(f"{name}.confluence_score is below the signal gate")
    if (
        _finite(
            row.get("decision_stop_distance_pct"),
            f"{name}.decision_stop_distance_pct",
            nonnegative=True,
        )
        < 0.025
    ):
        raise BaselineReportContractError(f"{name}.decision_stop_distance_pct is below the gate")


def _signal_fingerprints(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [{field: row[field] for field in _SIGNAL_FINGERPRINT_FIELDS} for row in rows]


def _signal_bucket_counts(rows: Sequence[Mapping[str, Any]], field: str) -> dict[str, Any]:
    labels = sorted({_text(row.get(field), f"signal.{field}") for row in rows})
    return {
        label: {
            "raw_emissions": sum(row[field] == label for row in rows),
            "accepted": sum(
                row[field] == label and row.get("outcome") == "accepted" for row in rows
            ),
            "rejected": sum(
                row[field] == label and row.get("outcome") == "rejected" for row in rows
            ),
        }
        for label in labels
    }


def _validate_signal_stream(
    raw: Mapping[str, Any],
) -> tuple[dict[str, Any], list[Mapping[str, Any]]]:
    stream = _mapping(raw.get("signal_stream"), "signal_stream")
    _exact_keys(
        stream,
        {
            "generation_call_count",
            "raw_emission_count",
            "generated_history_intent_count",
            "evaluation_intent_count",
            "pre_evaluation_intents_excluded",
            "decision_reason_counts",
            "decision_ledger",
            "decision_ledger_sha256",
            "accepted_intent_reconciliation",
            "only_signal_eligible_intents_passed_to_engines",
            "accepted_intents",
            "accepted_intents_sha256",
            "entry_intents",
            "entry_intents_sha256",
            "reference_or_holdout_intents",
        },
        "signal_stream",
    )
    if _integer(stream.get("generation_call_count"), "signal_stream.generation_call_count") != 1:
        raise BaselineReportContractError("signal generation must run exactly once")
    if stream.get("only_signal_eligible_intents_passed_to_engines") is not True:
        raise BaselineReportContractError("non-eligible signals may have reached the engines")
    if (
        _integer(
            stream.get("reference_or_holdout_intents"), "signal_stream.reference_or_holdout_intents"
        )
        != 0
    ):
        raise BaselineReportContractError("signal stream contains reference or holdout intents")

    decisions = [
        _mapping(value, f"signal_stream.decision_ledger[{index}]")
        for index, value in enumerate(
            _list(stream.get("decision_ledger"), "signal_stream.decision_ledger")
        )
    ]
    for index, row in enumerate(decisions):
        _validate_signal_decision(row, index)
    if _integer(stream.get("raw_emission_count"), "signal_stream.raw_emission_count") != len(
        decisions
    ):
        raise BaselineReportContractError("raw signal emission count mismatch")
    decision_hash = _canonical_hash(decisions)
    if (
        _sha256_text(stream.get("decision_ledger_sha256"), "signal_stream.decision_ledger_sha256")
        != decision_hash
    ):
        raise BaselineReportContractError("signal decision ledger hash mismatch")

    reason_counts = dict(sorted(Counter(str(row["reason"]) for row in decisions).items()))
    if stream.get("decision_reason_counts") != reason_counts:
        raise BaselineReportContractError("signal decision reason counts mismatch")
    accepted = [row for row in decisions if row["outcome"] == "accepted"]
    evaluation_decisions = [
        row
        for row in decisions
        if (
            row["entry_ts"] is not None
            and EVALUATION_START
            <= _utc(row["entry_ts"], "evaluation decision entry_ts")
            < EVALUATION_END
        )
        or (
            row["entry_ts"] is None
            and EVALUATION_START
            <= _utc(row["decision_ts"], "evaluation decision decision_ts")
            < EVALUATION_END
        )
    ]
    evaluation_reason_counts = dict(
        sorted(Counter(str(row["reason"]) for row in evaluation_decisions).items())
    )
    evaluation_accepted = [
        row
        for row in accepted
        if EVALUATION_START <= _utc(row["entry_ts"], "accepted.entry_ts") < EVALUATION_END
    ]
    if _integer(
        stream.get("generated_history_intent_count"),
        "signal_stream.generated_history_intent_count",
    ) != len(accepted):
        raise BaselineReportContractError("history intent count does not equal accepted decisions")
    if _integer(
        stream.get("pre_evaluation_intents_excluded"),
        "signal_stream.pre_evaluation_intents_excluded",
    ) != len(accepted) - len(evaluation_accepted):
        raise BaselineReportContractError("pre-evaluation excluded intent count mismatch")

    accepted_intents = [
        _mapping(value, f"signal_stream.accepted_intents[{index}]")
        for index, value in enumerate(
            _list(stream.get("accepted_intents"), "signal_stream.accepted_intents")
        )
    ]
    for index, row in enumerate(accepted_intents):
        name = f"signal_stream.accepted_intents[{index}]"
        _validate_exact_fields(row, _SIGNAL_INTENT_FIELDS, name)
        _validate_signal_core(row, name, allow_missing_entry=False)
        if _finite(row.get("confluence_score"), f"{name}.confluence_score") < 0.25:
            raise BaselineReportContractError(f"{name}.confluence_score is below the signal gate")
        if (
            _finite(
                row.get("decision_stop_distance_pct"),
                f"{name}.decision_stop_distance_pct",
                nonnegative=True,
            )
            < 0.025
        ):
            raise BaselineReportContractError(
                f"{name}.decision_stop_distance_pct is below the signal gate"
            )
    expected_accepted_intents = [
        {field: row[field] for field in _SIGNAL_INTENT_FIELDS} for row in accepted
    ]
    if accepted_intents != expected_accepted_intents:
        raise BaselineReportContractError(
            "accepted_intents do not exactly reconcile to all accepted decision rows"
        )
    accepted_intents_hash = _canonical_hash(accepted_intents)
    if (
        _sha256_text(stream.get("accepted_intents_sha256"), "signal_stream.accepted_intents_sha256")
        != accepted_intents_hash
    ):
        raise BaselineReportContractError("accepted_intents_sha256 mismatch")

    intents = [
        _mapping(value, f"signal_stream.entry_intents[{index}]")
        for index, value in enumerate(
            _list(stream.get("entry_intents"), "signal_stream.entry_intents")
        )
    ]
    for index, row in enumerate(intents):
        _validate_signal_intent(row, index)
    if _integer(
        stream.get("evaluation_intent_count"), "signal_stream.evaluation_intent_count"
    ) != len(intents):
        raise BaselineReportContractError("evaluation intent count mismatch")
    intents_hash = _canonical_hash(intents)
    if (
        _sha256_text(stream.get("entry_intents_sha256"), "signal_stream.entry_intents_sha256")
        != intents_hash
    ):
        raise BaselineReportContractError("evaluation entry-intent hash mismatch")
    mutation_checks = _mapping(
        _mapping(raw.get("execution_governance"), "execution_governance").get(
            "input_mutation_checks"
        ),
        "input_mutation_checks",
    )
    if mutation_checks.get("signal_decision_ledger_sha256") != decision_hash:
        raise BaselineReportContractError(
            "post-engine mutation proof differs from the signal decision ledger"
        )
    if mutation_checks.get("signal_batch_intents_sha256") != accepted_intents_hash:
        raise BaselineReportContractError(
            "post-engine mutation proof differs from all accepted signal intents"
        )
    if mutation_checks.get("entry_intents_sha256") != intents_hash:
        raise BaselineReportContractError(
            "post-engine mutation proof differs from the evaluation intent stream"
        )

    expected_intents = [
        row
        for row in accepted_intents
        if EVALUATION_START <= _utc(row["entry_ts"], "accepted intent entry_ts") < EVALUATION_END
    ]
    if expected_intents != intents:
        raise BaselineReportContractError(
            "evaluation accepted signal rows do not exactly reconcile to engine intents"
        )

    reconciliation = _mapping(
        stream.get("accepted_intent_reconciliation"),
        "signal_stream.accepted_intent_reconciliation",
    )
    expected_reconciliation_values = {
        "accepted_decision_count": len(accepted),
        "intent_count": len(accepted),
        "exact_ordered_reconciliation": True,
        "evaluation_accepted_decision_count": len(evaluation_accepted),
        "evaluation_intent_count": len(intents),
        "evaluation_exact_ordered_reconciliation": True,
    }
    for key, expected in expected_reconciliation_values.items():
        if reconciliation.get(key) != expected:
            raise BaselineReportContractError(f"signal reconciliation.{key} mismatch")
    accepted_fingerprint_hash = _canonical_hash(_signal_fingerprints(accepted))
    for key in (
        "accepted_decision_fingerprints_sha256",
        "intent_fingerprints_sha256",
    ):
        if _sha256_text(reconciliation.get(key), f"signal reconciliation.{key}") != (
            accepted_fingerprint_hash
        ):
            raise BaselineReportContractError(f"signal reconciliation.{key} mismatch")
    evaluation_fingerprint_hash = _canonical_hash(_signal_fingerprints(evaluation_accepted))
    if (
        _sha256_text(
            reconciliation.get("evaluation_fingerprints_sha256"),
            "signal reconciliation.evaluation_fingerprints_sha256",
        )
        != evaluation_fingerprint_hash
    ):
        raise BaselineReportContractError("evaluation signal fingerprint hash mismatch")

    summary = {
        "generation_call_count": 1,
        "ledger_scope": {
            "history_start_inclusive": HISTORY_START.isoformat(),
            "evaluation_end_exclusive": EVALUATION_END.isoformat(),
            "includes_feature_history_emissions": True,
        },
        "raw_emission_count": len(decisions),
        "accepted_history_intent_count": len(accepted),
        "rejected_history_emission_count": len(decisions) - len(accepted),
        "evaluation_intent_count": len(intents),
        "evaluation_raw_emission_count": len(evaluation_decisions),
        "evaluation_rejected_emission_count": sum(
            row["outcome"] == "rejected" for row in evaluation_decisions
        ),
        "pre_evaluation_intent_count": len(accepted) - len(intents),
        "decision_reason_counts": reason_counts,
        "evaluation_decision_reason_counts": evaluation_reason_counts,
        "outcome_counts": {
            "accepted": len(accepted),
            "rejected": len(decisions) - len(accepted),
        },
        "by_strategy": _signal_bucket_counts(decisions, "strategy"),
        "by_side": _signal_bucket_counts(decisions, "side"),
        "by_symbol": _signal_bucket_counts(decisions, "symbol"),
        "decision_ledger_sha256": decision_hash,
        "evaluation_entry_intents_sha256": intents_hash,
        "accepted_rows_exactly_reconciled_to_engine_intents": True,
        "reference_or_holdout_intents": 0,
    }
    return summary, intents


def _validate_timestamped_ledger(
    rows: list[Any],
    *,
    name: str,
    timestamp_key: str,
    allow_end: bool = False,
) -> list[Mapping[str, Any]]:
    result: list[Mapping[str, Any]] = []
    for index, value in enumerate(rows):
        row = _mapping(value, f"{name}[{index}]")
        timestamp = _utc(row.get(timestamp_key), f"{name}[{index}].{timestamp_key}")
        upper_ok = timestamp <= EVALUATION_END if allow_end else timestamp < EVALUATION_END
        if timestamp < EVALUATION_START or not upper_ok:
            raise BaselineReportContractError(f"{name}[{index}] lies outside the half-open window")
        result.append(row)
    return result


def _validate_curve(rows: list[Any], scenario: str) -> _Curve:
    timestamps: list[pd.Timestamp] = []
    navs: list[float] = []
    wallets: list[float] = []
    gross_values: list[float] = []
    adjusted_values: list[float] = []
    accrued_values: list[float] = []
    open_counts: list[int] = []
    previous: pd.Timestamp | None = None
    for index, value in enumerate(rows):
        row = _mapping(value, f"results.{scenario}.curve[{index}]")
        timestamp = _utc(row.get("ts"), f"results.{scenario}.curve[{index}].ts")
        if not EVALUATION_START <= timestamp < EVALUATION_END:
            raise BaselineReportContractError(f"{scenario} curve escapes its half-open window")
        if (timestamp - EVALUATION_START) % BAR != pd.Timedelta(0):
            raise BaselineReportContractError(f"{scenario} curve timestamp is off the 15m grid")
        if previous is not None and timestamp <= previous:
            raise BaselineReportContractError(
                f"{scenario} curve timestamps are not strictly increasing"
            )
        wallet = _finite(row.get("wallet_balance"), f"{scenario}.curve.wallet")
        gross = _finite(row.get("gross_unrealized_price_pnl"), f"{scenario}.curve.gross")
        adjusted = _finite(row.get("adjusted_unrealized_price_pnl"), f"{scenario}.curve.adjusted")
        accrued = _finite(
            row.get("accrued_exit_cost"), f"{scenario}.curve.accrued", nonnegative=True
        )
        nav = _finite(row.get("nav"), f"{scenario}.curve.nav", positive=True)
        count = _integer(row.get("open_position_count"), f"{scenario}.curve.open_count")
        _same(nav, wallet + adjusted - accrued, f"{scenario} curve NAV identity")
        timestamps.append(timestamp)
        navs.append(nav)
        wallets.append(wallet)
        gross_values.append(gross)
        adjusted_values.append(adjusted)
        accrued_values.append(accrued)
        open_counts.append(count)
        previous = timestamp
    if not timestamps:
        raise BaselineReportContractError(f"{scenario} curve is empty")
    if timestamps[0] != EVALUATION_START:
        raise BaselineReportContractError(f"{scenario} curve must start at evaluation_start")
    if timestamps[-1] != EVALUATION_END - BAR:
        raise BaselineReportContractError(f"{scenario} curve must end at the last 15m label")
    for month_start in pd.date_range(EVALUATION_START, EVALUATION_END, freq="MS", inclusive="left"):
        month_end = month_start + pd.offsets.MonthBegin(1)
        left = bisect.bisect_left(timestamps, month_start)
        right = bisect.bisect_left(timestamps, month_end)
        if left == right:
            raise BaselineReportContractError(
                f"{scenario} curve has no point in {month_start:%Y-%m}"
            )
    return _Curve(
        timestamps=tuple(timestamps),
        navs=tuple(navs),
        wallets=tuple(wallets),
        gross_unrealized=tuple(gross_values),
        adjusted_unrealized=tuple(adjusted_values),
        accrued_exit_costs=tuple(accrued_values),
        open_counts=tuple(open_counts),
    )


def _validate_result(
    raw: Mapping[str, Any], scenario: str
) -> tuple[Mapping[str, Any], _Curve, dict[str, list[Mapping[str, Any]]]]:
    results = _mapping(raw.get("results"), "results")
    if tuple(results) != SCENARIO_ORDER or set(results) != set(SCENARIO_ORDER):
        raise BaselineReportContractError("results must contain exact ordered B/C2/H")
    wrapper = _mapping(results[scenario], f"results.{scenario}")
    complete = _mapping(wrapper.get("complete_result"), f"results.{scenario}.complete_result")
    if wrapper.get("complete_result_sha256") != _canonical_hash(complete):
        raise BaselineReportContractError(f"{scenario} complete_result_sha256 mismatch")
    if complete.get("scenario") != scenario or complete.get("scenario_identity") != scenario:
        raise BaselineReportContractError(f"{scenario} result identity drifted")
    if complete.get("scenario_is_canonical") is not True:
        raise BaselineReportContractError(f"{scenario} result is not a canonical scenario")
    _exact_scenario(complete.get("scenario_config"), scenario, f"{scenario}.scenario_config")
    if complete.get("policy") != raw.get("policy"):
        raise BaselineReportContractError(f"{scenario} result policy differs from top-level policy")
    if _utc(complete.get("evaluation_start"), f"{scenario}.evaluation_start") != EVALUATION_START:
        raise BaselineReportContractError(f"{scenario} evaluation_start drifted")
    if _utc(complete.get("evaluation_end"), f"{scenario}.evaluation_end") != EVALUATION_END:
        raise BaselineReportContractError(f"{scenario} evaluation_end drifted")
    _finite(complete.get("initial_wallet"), f"{scenario}.initial_wallet", positive=True)
    _finite(complete.get("final_wallet"), f"{scenario}.final_wallet")
    _finite(complete.get("final_nav"), f"{scenario}.final_nav", positive=True)
    _finite(complete.get("max_drawdown"), f"{scenario}.max_drawdown")
    _finite(
        complete.get("total_execution_cost_charged"),
        f"{scenario}.execution_cost",
        nonnegative=True,
    )
    _finite(complete.get("total_funding_cashflow"), f"{scenario}.funding")
    _finite(
        complete.get("accrued_terminal_exit_cost"),
        f"{scenario}.terminal_cost",
        nonnegative=True,
    )

    lists: dict[str, list[Any]] = {}
    for key in _RESULT_LISTS:
        lists[key] = _list(complete.get(key), f"results.{scenario}.{key}")
    curve = _validate_curve(lists["curve"], scenario)

    ledgers: dict[str, list[Mapping[str, Any]]] = {}
    ledgers["entries"] = _validate_timestamped_ledger(
        lists["entries"], name=f"{scenario}.entries", timestamp_key="entry_ts"
    )
    for key in ("exit_fills", "funding_events", "journal_rows", "breaker_transitions"):
        ledgers[key] = _validate_timestamped_ledger(
            lists[key], name=f"{scenario}.{key}", timestamp_key="ts"
        )
    for key in ("risk_decisions", "rejections"):
        ledgers[key] = _validate_timestamped_ledger(
            lists[key], name=f"{scenario}.{key}", timestamp_key="entry_ts"
        )
    ledgers["stop_transitions"] = _validate_timestamped_ledger(
        lists["stop_transitions"],
        name=f"{scenario}.stop_transitions",
        timestamp_key="calculated_ts",
    )
    ledgers["closed_episodes"] = _validate_timestamped_ledger(
        lists["closed_episodes"],
        name=f"{scenario}.closed_episodes",
        timestamp_key="exit_ts",
    )
    ledgers["terminal_positions"] = _validate_timestamped_ledger(
        lists["terminal_positions"],
        name=f"{scenario}.terminal_positions",
        timestamp_key="cutoff_ts",
    )
    candidate_ledgers = (
        "entries",
        "exit_fills",
        "funding_events",
        "journal_rows",
        "stop_transitions",
        "risk_decisions",
        "rejections",
        "closed_episodes",
        "terminal_positions",
    )
    for ledger_name in candidate_ledgers:
        for index, row in enumerate(ledgers[ledger_name]):
            if row.get("candidate_id") != "v15p2_fair_baseline":
                raise BaselineReportContractError(
                    f"{scenario}.{ledger_name}[{index}] has a foreign candidate_id"
                )
    for index, row in enumerate(ledgers["entries"]):
        decision = _utc(row.get("decision_ts"), f"{scenario}.entries[{index}].decision_ts")
        entry = _utc(row.get("entry_ts"), f"{scenario}.entries[{index}].entry_ts")
        if decision >= entry or decision < EVALUATION_START - BAR:
            raise BaselineReportContractError(f"{scenario}.entries[{index}] decision/entry drifted")
    for index, row in enumerate(ledgers["closed_episodes"]):
        entry = _utc(row.get("entry_ts"), f"{scenario}.closed_episodes[{index}].entry_ts")
        exit_ts = _utc(row.get("exit_ts"), f"{scenario}.closed_episodes[{index}].exit_ts")
        if not EVALUATION_START <= entry <= exit_ts < EVALUATION_END:
            raise BaselineReportContractError(
                f"{scenario}.closed_episodes[{index}] escapes the half-open window"
            )
    cutoff = curve.timestamps[-1]
    for index, row in enumerate(ledgers["terminal_positions"]):
        entry = _utc(row.get("entry_ts"), f"{scenario}.terminal_positions[{index}].entry_ts")
        row_cutoff = _utc(row.get("cutoff_ts"), f"{scenario}.terminal_positions[{index}].cutoff_ts")
        if not EVALUATION_START <= entry <= row_cutoff or row_cutoff != cutoff:
            raise BaselineReportContractError(
                f"{scenario}.terminal_positions[{index}] has invalid entry/cutoff timing"
            )
    return complete, curve, ledgers


def _signal_entry_key(row: Mapping[str, Any], *, engine_entry: bool) -> tuple[Any, ...]:
    return (
        _utc(row.get("decision_ts"), "entry signal decision_ts").isoformat(),
        _utc(row.get("entry_ts"), "entry signal entry_ts").isoformat(),
        _text(row.get("symbol"), "entry signal symbol"),
        _text(row.get("side"), "entry signal side"),
        _text(row.get("strategy"), "entry signal strategy"),
        _text(row.get("pattern_id"), "entry signal pattern_id"),
        _finite(row.get("entry_price"), "entry signal entry_price", positive=True),
        _finite(
            row.get("initial_stop" if engine_entry else "stop_price"),
            "entry signal stop_price",
            positive=True,
        ),
        _text(row.get("signal_manifest_hash"), "entry signal manifest"),
        _text(row.get("config_sha256"), "entry signal config"),
    )


def _validate_engine_entries_are_signal_intents(
    evaluation_intents: Sequence[Mapping[str, Any]],
    validated: Mapping[str, tuple[Mapping[str, Any], _Curve, dict[str, list[Mapping[str, Any]]]]],
) -> None:
    available = Counter(_signal_entry_key(row, engine_entry=False) for row in evaluation_intents)
    for scenario in SCENARIO_ORDER:
        remaining = available.copy()
        entries = validated[scenario][2]["entries"]
        for index, row in enumerate(entries):
            key = _signal_entry_key(row, engine_entry=True)
            if remaining[key] <= 0:
                raise BaselineReportContractError(
                    f"{scenario}.entries[{index}] does not originate from an evaluation intent"
                )
            remaining[key] -= 1


def _baseline_index(curve: _Curve, start: pd.Timestamp) -> int | None:
    index = bisect.bisect_left(curve.timestamps, start) - 1
    return index if index >= 0 else None


def _window_end_index(curve: _Curve, end: pd.Timestamp) -> int:
    index = bisect.bisect_left(curve.timestamps, end) - 1
    if index < 0:
        raise BaselineReportContractError("window has no NAV strictly before its end")
    return index


def _window_endpoints(
    curve: _Curve, initial_wallet: float, start: pd.Timestamp, end: pd.Timestamp
) -> tuple[float, pd.Timestamp | None, float, pd.Timestamp]:
    baseline_index = _baseline_index(curve, start)
    if baseline_index is None:
        if start != EVALUATION_START:
            raise BaselineReportContractError("non-initial window lacks a strict pre-start NAV")
        baseline_nav = initial_wallet
        baseline_ts = None
    else:
        baseline_nav = curve.navs[baseline_index]
        baseline_ts = curve.timestamps[baseline_index]
        if baseline_ts >= start:
            raise AssertionError("strict pre-window baseline invariant failed")
    end_index = _window_end_index(curve, end)
    if curve.timestamps[end_index] < start:
        raise BaselineReportContractError("window contains no NAV observation")
    return baseline_nav, baseline_ts, curve.navs[end_index], curve.timestamps[end_index]


def _activity_months(curve: _Curve, ledgers: Mapping[str, list[Mapping[str, Any]]]) -> set[str]:
    active = {
        timestamp.strftime("%Y-%m")
        for timestamp, count in zip(curve.timestamps, curve.open_counts, strict=True)
        if count > 0
    }
    timestamp_fields = {
        "entries": "entry_ts",
        "exit_fills": "ts",
        "funding_events": "ts",
    }
    for ledger, field in timestamp_fields.items():
        for row in ledgers[ledger]:
            active.add(_utc(row[field], f"{ledger}.{field}").strftime("%Y-%m"))
    return active


def _trimmed_mean(values: Sequence[float]) -> tuple[float, int]:
    if not values:
        raise BaselineReportContractError("monthly statistic window is empty")
    trim_each_side = math.floor(len(values) * 0.10)
    ordered = sorted(values)
    kept = ordered[trim_each_side : len(ordered) - trim_each_side or None]
    return statistics.fmean(kept), trim_each_side


def _monthly_rows(
    curve: _Curve,
    initial_wallet: float,
    active_months: set[str],
    start: pd.Timestamp,
    end: pd.Timestamp,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for month_start in pd.date_range(start, end, freq="MS", inclusive="left"):
        month_end = min(month_start + pd.offsets.MonthBegin(1), end)
        baseline, baseline_ts, end_nav, end_ts = _window_endpoints(
            curve, initial_wallet, month_start, month_end
        )
        pnl = end_nav - baseline
        return_pct = pnl / baseline * 100.0
        label = month_start.strftime("%Y-%m")
        is_active = label in active_months
        if not is_active:
            _same(pnl, 0.0, f"inactive month {label} PnL")
            pnl = 0.0
            return_pct = 0.0
        rows.append(
            {
                "month": label,
                "start_inclusive": month_start.isoformat(),
                "end_exclusive": month_end.isoformat(),
                "baseline_nav": baseline,
                "baseline_source": (
                    "initial_wallet_immediately_before_evaluation_start"
                    if baseline_ts is None
                    else "last_curve_nav_strictly_before_month_start"
                ),
                "baseline_timestamp_strictly_before_start": (
                    baseline_ts.isoformat() if baseline_ts is not None else None
                ),
                "end_nav": end_nav,
                "end_nav_timestamp": end_ts.isoformat(),
                "pnl": pnl,
                "return_pct": return_pct,
                "active": is_active,
            }
        )
    return rows


def _drawdown(
    curve: _Curve, initial_wallet: float, start: pd.Timestamp, end: pd.Timestamp
) -> dict[str, Any]:
    baseline, baseline_ts, _, _ = _window_endpoints(curve, initial_wallet, start, end)
    left = bisect.bisect_left(curve.timestamps, start)
    right = bisect.bisect_left(curve.timestamps, end)
    running_peak = baseline
    running_peak_ts = baseline_ts
    peak_observation = -1
    trough_observation = -1
    worst = 0.0
    worst_peak = baseline
    worst_peak_ts = baseline_ts
    worst_trough_ts: pd.Timestamp | None = None
    for observation, index in enumerate(range(left, right)):
        nav = curve.navs[index]
        timestamp = curve.timestamps[index]
        if nav > running_peak:
            running_peak = nav
            running_peak_ts = timestamp
            peak_observation = observation
        drawdown = nav / running_peak - 1.0
        if drawdown < worst:
            worst = drawdown
            worst_peak = running_peak
            worst_peak_ts = running_peak_ts
            worst_trough_ts = timestamp
            trough_observation = observation
            worst_peak_observation = peak_observation
    if worst_trough_ts is None:
        return {
            "max_drawdown_pct": 0.0,
            "peak_nav": baseline,
            "trough_nav": baseline,
            "peak_ts": baseline_ts.isoformat() if baseline_ts is not None else None,
            "trough_ts": None,
            "recovered": True,
            "recovery_ts": None,
            "observations_peak_to_trough": 0,
            "observations_trough_to_recovery": 0,
            "calendar_days_to_recovery": 0.0,
            "recovery_status": "NO_DRAWDOWN",
        }
    trough_index = left + trough_observation
    recovery_index: int | None = None
    for index in range(trough_index + 1, right):
        if curve.navs[index] >= worst_peak - max(abs(worst_peak) * 1e-12, 1e-9):
            recovery_index = index
            break
    recovery_ts = curve.timestamps[recovery_index] if recovery_index is not None else None
    trough_nav = curve.navs[trough_index]
    peak_to_trough = trough_observation - worst_peak_observation
    trough_to_recovery = recovery_index - trough_index if recovery_index is not None else None
    return {
        "max_drawdown_pct": -worst * 100.0,
        "peak_nav": worst_peak,
        "trough_nav": trough_nav,
        "peak_ts": worst_peak_ts.isoformat() if worst_peak_ts is not None else None,
        "trough_ts": worst_trough_ts.isoformat(),
        "recovered": recovery_index is not None,
        "recovery_ts": recovery_ts.isoformat() if recovery_ts is not None else None,
        "observations_peak_to_trough": peak_to_trough,
        "observations_trough_to_recovery": trough_to_recovery,
        "calendar_days_to_recovery": (
            (recovery_ts - worst_trough_ts).total_seconds() / 86400.0
            if recovery_ts is not None
            else None
        ),
        "recovery_status": "RECOVERED" if recovery_index is not None else "NOT_RECOVERED",
    }


def _window_metrics(
    curve: _Curve,
    initial_wallet: float,
    active_months: set[str],
    start: pd.Timestamp,
    end: pd.Timestamp,
) -> dict[str, Any]:
    monthly = _monthly_rows(curve, initial_wallet, active_months, start, end)
    values = [row["return_pct"] for row in monthly]
    trim, trim_count = _trimmed_mean(values)
    baseline, baseline_ts, end_nav, end_ts = _window_endpoints(curve, initial_wallet, start, end)
    return {
        "start_inclusive": start.isoformat(),
        "end_exclusive": end.isoformat(),
        "month_count": len(monthly),
        "monthly": monthly,
        "mean_monthly_return_pct": statistics.fmean(values),
        "median_monthly_return_pct": statistics.median(values),
        "trimmed_10pct_symmetric_mean_monthly_return_pct": trim,
        "trimmed_observations_each_side": trim_count,
        "negative_month_count": sum(value < 0.0 for value in values),
        "months_below_minus_1pct_count": sum(value < -1.0 for value in values),
        "worst_month_pct": min(values),
        "best_month_pct": max(values),
        "inactive_month_count": sum(not row["active"] for row in monthly),
        "baseline_nav": baseline,
        "baseline_timestamp_strictly_before_start": (
            baseline_ts.isoformat() if baseline_ts is not None else None
        ),
        "end_nav": end_nav,
        "end_nav_timestamp": end_ts.isoformat(),
        "continuous_pnl": end_nav - baseline,
        "continuous_return_pct": (end_nav / baseline - 1.0) * 100.0,
        "drawdown_and_recovery": _drawdown(curve, initial_wallet, start, end),
    }


def _safe_ratio(numerator: float, denominator: float) -> float | None:
    if math.isclose(denominator, 0.0, rel_tol=0.0, abs_tol=1e-15):
        return None
    return numerator / denominator


def _bucket_summary(
    entries: Sequence[Mapping[str, Any]],
    episodes: Sequence[Mapping[str, Any]],
    entry_field: str,
    episode_field: str,
) -> dict[str, Any]:
    entry_count: defaultdict[str, int] = defaultdict(int)
    entry_notional: defaultdict[str, float] = defaultdict(float)
    episode_count: defaultdict[str, int] = defaultdict(int)
    episode_net: defaultdict[str, float] = defaultdict(float)
    for row in entries:
        label = _text(row.get(entry_field), f"entry.{entry_field}")
        entry_count[label] += 1
        entry_notional[label] += _finite(
            row.get("entry_notional"), "entry_notional", nonnegative=True
        )
    for row in episodes:
        label = _text(row.get(episode_field), f"episode.{episode_field}")
        episode_count[label] += 1
        episode_net[label] += _finite(row.get("net_pnl"), "episode.net_pnl")
    labels = sorted(set(entry_count) | set(episode_count))
    total_notional = sum(entry_notional.values())
    total_abs_net = sum(abs(value) for value in episode_net.values())
    rows = []
    for label in labels:
        rows.append(
            {
                "label": label,
                "entry_count": entry_count[label],
                "entry_notional": entry_notional[label],
                "entry_notional_share_pct": (
                    entry_notional[label] / total_notional * 100.0 if total_notional else 0.0
                ),
                "closed_episode_count": episode_count[label],
                "closed_episode_net_pnl": episode_net[label],
                "absolute_net_pnl_share_pct": (
                    abs(episode_net[label]) / total_abs_net * 100.0 if total_abs_net else 0.0
                ),
            }
        )
    notional_weights = (
        [value / total_notional for value in entry_notional.values()] if total_notional else []
    )
    pnl_weights = (
        [abs(value) / total_abs_net for value in episode_net.values()] if total_abs_net else []
    )
    return {
        "buckets": rows,
        "max_entry_notional_share_pct": max(
            (row["entry_notional_share_pct"] for row in rows), default=0.0
        ),
        "entry_notional_hhi": sum(value * value for value in notional_weights),
        "max_absolute_net_pnl_share_pct": max(
            (row["absolute_net_pnl_share_pct"] for row in rows), default=0.0
        ),
        "absolute_net_pnl_hhi": sum(value * value for value in pnl_weights),
    }


def _month_key(row: Mapping[str, Any], timestamp_field: str) -> str:
    return _utc(row.get(timestamp_field), timestamp_field).strftime("%Y-%m")


def _concentration(
    entries: Sequence[Mapping[str, Any]], episodes: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    enriched_entries = [dict(row, _month=_month_key(row, "entry_ts")) for row in entries]
    enriched_episodes = [dict(row, _month=_month_key(row, "exit_ts")) for row in episodes]
    return {
        "side": _bucket_summary(enriched_entries, enriched_episodes, "side", "side"),
        "strategy": _bucket_summary(enriched_entries, enriched_episodes, "strategy", "strategy"),
        "symbol": _bucket_summary(enriched_entries, enriched_episodes, "symbol", "symbol"),
        "entry_or_exit_month": _bucket_summary(
            enriched_entries, enriched_episodes, "_month", "_month"
        ),
        "basis_note": (
            "Entry concentration uses filled entry notional; PnL concentration uses absolute "
            "closed-episode net PnL attributed descriptively to final-exit month."
        ),
    }


def _financial_summary(
    complete: Mapping[str, Any], curve: _Curve, ledgers: Mapping[str, list[Mapping[str, Any]]]
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    scenario = str(complete["scenario"])
    scenario_config = _mapping(complete.get("scenario_config"), "scenario_config")
    cost_multiplier = _finite(scenario_config.get("cost_multiplier"), "cost_multiplier")
    funding_multiplier = _finite(scenario_config.get("funding_multiplier"), "funding_multiplier")
    positive_multiplier = _finite(
        scenario_config.get("positive_price_pnl_multiplier"), "positive_multiplier"
    )
    negative_multiplier = _finite(
        scenario_config.get("negative_price_pnl_multiplier"), "negative_multiplier"
    )
    entries = ledgers["entries"]
    exits = ledgers["exit_fills"]
    funding = ledgers["funding_events"]
    episodes = ledgers["closed_episodes"]
    terminal = ledgers["terminal_positions"]

    entry_fee = entry_spread = entry_impact = entry_cost = 0.0
    gross_turnover = 0.0
    entry_by_position_key: dict[tuple[str, str, str], Mapping[str, Any]] = {}
    for row in entries:
        symbol = _text(row.get("symbol"), f"{scenario}.entry.symbol")
        _text(row.get("strategy"), f"{scenario}.entry.strategy")
        side = _text(row.get("side"), f"{scenario}.entry.side")
        if side not in {"long", "short"}:
            raise BaselineReportContractError(f"{scenario}.entry.side is invalid")
        if row.get("scenario") != scenario:
            raise BaselineReportContractError(f"{scenario}.entry scenario identity drifted")
        fee = _finite(row.get("fee"), f"{scenario}.entry.fee", nonnegative=True)
        spread = _finite(row.get("spread_slippage"), f"{scenario}.entry.spread", nonnegative=True)
        impact = _finite(row.get("impact"), f"{scenario}.entry.impact", nonnegative=True)
        cost = _finite(row.get("execution_cost"), f"{scenario}.entry.cost", nonnegative=True)
        notional = _finite(
            row.get("entry_notional"), f"{scenario}.entry.notional", nonnegative=True
        )
        price = _finite(row.get("entry_price"), f"{scenario}.entry.price", positive=True)
        quantity = _finite(
            row.get("original_quantity"), f"{scenario}.entry.quantity", positive=True
        )
        initial_stop = _finite(
            row.get("initial_stop"), f"{scenario}.entry.initial_stop", positive=True
        )
        wallet_before = _finite(row.get("wallet_before_entry"), f"{scenario}.entry.wallet_before")
        wallet_after = _finite(row.get("wallet_after_entry"), f"{scenario}.entry.wallet_after")
        effective_risk = _finite(
            row.get("effective_initial_stop_risk"),
            f"{scenario}.entry.effective_initial_stop_risk",
            nonnegative=True,
        )
        _finite(row.get("dynamic_leverage"), f"{scenario}.entry.dynamic_leverage", positive=True)
        _finite(row.get("risk_budget"), f"{scenario}.entry.risk_budget", nonnegative=True)
        _same(notional, price * quantity, f"{scenario} entry notional")
        _same(wallet_after, wallet_before - cost, f"{scenario} entry wallet movement")
        _same(
            effective_risk,
            quantity * abs(price - initial_stop),
            f"{scenario} effective initial stop risk",
        )
        _same(cost, fee + spread + impact, f"{scenario} entry cost components")
        component_scale = notional * cost_multiplier / 10_000.0
        _same(fee, component_scale * 4.0, f"{scenario} entry fee rate")
        _same(spread, component_scale * 20.0, f"{scenario} entry spread rate")
        _same(impact, component_scale * 4.5, f"{scenario} entry impact rate")
        entry_fee += fee
        entry_spread += spread
        entry_impact += impact
        entry_cost += cost
        gross_turnover += notional
        position_key = (
            symbol,
            side,
            _utc(row.get("entry_ts"), f"{scenario}.entry.entry_ts").isoformat(),
        )
        if position_key in entry_by_position_key:
            raise BaselineReportContractError(f"{scenario} has duplicate entry position identity")
        entry_by_position_key[position_key] = row

    exit_fee = exit_spread = exit_impact = exit_cost = 0.0
    adjusted_realized = gross_realized = 0.0
    nonfinal_partial = sub_full_fills = 0
    for row in exits:
        _text(row.get("symbol"), f"{scenario}.exit.symbol")
        _text(row.get("strategy"), f"{scenario}.exit.strategy")
        side = _text(row.get("side"), f"{scenario}.exit.side")
        if side not in {"long", "short"}:
            raise BaselineReportContractError(f"{scenario}.exit.side is invalid")
        price = _finite(row.get("price"), f"{scenario}.exit.price", positive=True)
        quantity = _finite(row.get("quantity"), f"{scenario}.exit.quantity", positive=True)
        fee = _finite(row.get("fee"), f"{scenario}.exit.fee", nonnegative=True)
        spread = _finite(row.get("spread_slippage"), f"{scenario}.exit.spread", nonnegative=True)
        impact = _finite(row.get("impact"), f"{scenario}.exit.impact", nonnegative=True)
        cost = _finite(row.get("exit_execution_cost"), f"{scenario}.exit.cost", nonnegative=True)
        adjusted = _finite(row.get("adjusted_price_pnl"), f"{scenario}.exit.adjusted")
        gross = _finite(row.get("gross_price_pnl"), f"{scenario}.exit.gross")
        payoff = _finite(row.get("payoff_multiplier"), f"{scenario}.exit.payoff")
        allocated = _finite(
            row.get("allocated_entry_cost"),
            f"{scenario}.exit.allocated_entry_cost",
            nonnegative=True,
        )
        net = _finite(row.get("net_pnl_excluding_funding"), f"{scenario}.exit.net_ex_funding")
        _same(cost, fee + spread + impact, f"{scenario} exit cost components")
        component_scale = price * quantity * cost_multiplier / 10_000.0
        _same(fee, component_scale * 4.0, f"{scenario} exit fee rate")
        _same(spread, component_scale * 20.0, f"{scenario} exit spread rate")
        _same(impact, component_scale * 4.5, f"{scenario} exit impact rate")
        expected_payoff = (
            positive_multiplier if gross > 0.0 else negative_multiplier if gross < 0.0 else 1.0
        )
        _same(payoff, expected_payoff, f"{scenario} exit payoff multiplier")
        _same(adjusted, gross * payoff, f"{scenario} exit adjusted PnL")
        _same(net, adjusted - cost - allocated, f"{scenario} exit net identity")
        is_final = row.get("is_final")
        if not isinstance(is_final, bool):
            raise BaselineReportContractError(f"{scenario}.exit.is_final must be boolean")
        fraction = _finite(
            row.get("fraction_of_original"), f"{scenario}.exit.fraction", positive=True
        )
        if fraction > 1.0 + 1e-10:
            raise BaselineReportContractError(f"{scenario}.exit.fraction exceeds one")
        nonfinal_partial += not is_final
        sub_full_fills += fraction < 1.0 - 1e-10
        exit_fee += fee
        exit_spread += spread
        exit_impact += impact
        exit_cost += cost
        adjusted_realized += adjusted
        gross_realized += gross
        gross_turnover += price * quantity

    funding_total = 0.0
    for row in funding:
        side = _text(row.get("side"), f"{scenario}.funding.side")
        if side not in {"long", "short"}:
            raise BaselineReportContractError(f"{scenario}.funding.side is invalid")
        notional = _finite(row.get("notional"), f"{scenario}.funding.notional", nonnegative=True)
        mark_price = _finite(row.get("mark_price"), f"{scenario}.funding.mark_price", positive=True)
        remaining_quantity = _finite(
            row.get("remaining_quantity"),
            f"{scenario}.funding.remaining_quantity",
            positive=True,
        )
        rate = _finite(row.get("rate"), f"{scenario}.funding.rate")
        multiplier = _finite(row.get("multiplier"), f"{scenario}.funding.multiplier")
        cashflow = _finite(row.get("cashflow"), f"{scenario}.funding.cashflow")
        _same(multiplier, funding_multiplier, f"{scenario} funding multiplier")
        direction = 1.0 if side == "long" else -1.0
        _same(notional, mark_price * remaining_quantity, f"{scenario} funding notional")
        _same(
            cashflow,
            -direction * notional * rate * multiplier,
            f"{scenario} funding cashflow",
        )
        funding_total += cashflow

    episode_net = 0.0
    completed_position_keys: list[tuple[str, str, str]] = []
    for row in episodes:
        symbol = _text(row.get("symbol"), "episode.symbol")
        _text(row.get("strategy"), "episode.strategy")
        side = _text(row.get("side"), "episode.side")
        if side not in {"long", "short"}:
            raise BaselineReportContractError("episode.side is invalid")
        adjusted = _finite(row.get("adjusted_price_pnl"), "episode.adjusted")
        entry = _finite(
            row.get("total_entry_execution_cost"), "episode.entry_cost", nonnegative=True
        )
        exit_value = _finite(
            row.get("total_exit_execution_cost"), "episode.exit_cost", nonnegative=True
        )
        funding_value = _finite(row.get("funding_cashflow"), "episode.funding")
        net = _finite(row.get("net_pnl"), "episode.net")
        _same(net, adjusted - entry - exit_value + funding_value, "closed episode identity")
        position_key = (
            symbol,
            side,
            _utc(row.get("entry_ts"), "episode.entry_ts").isoformat(),
        )
        source_entry = entry_by_position_key.get(position_key)
        if source_entry is None:
            raise BaselineReportContractError("closed episode has no matching entry fill")
        _same(
            _finite(row.get("entry_price"), "episode.entry_price", positive=True),
            _finite(source_entry.get("entry_price"), "source entry price", positive=True),
            "closed episode entry price",
        )
        _same(
            _finite(row.get("initial_stop"), "episode.initial_stop", positive=True),
            _finite(source_entry.get("initial_stop"), "source initial stop", positive=True),
            "closed episode initial stop",
        )
        _same(
            _finite(row.get("original_quantity"), "episode.original_quantity", positive=True),
            _finite(
                source_entry.get("original_quantity"), "source original quantity", positive=True
            ),
            "closed episode original quantity",
        )
        _same(
            entry,
            _finite(source_entry.get("execution_cost"), "source entry cost", nonnegative=True),
            "closed episode entry cost",
        )
        completed_position_keys.append(position_key)
        episode_net += net

    terminal_rows: list[dict[str, Any]] = []
    terminal_gross = terminal_adjusted = terminal_cost = terminal_contribution = 0.0
    terminal_position_keys: list[tuple[str, str, str]] = []
    for row in terminal:
        symbol = _text(row.get("symbol"), "terminal.symbol")
        side = _text(row.get("side"), "terminal.side")
        if side not in {"long", "short"}:
            raise BaselineReportContractError("terminal.side is invalid")
        entry_price = _finite(row.get("entry_price"), "terminal.entry_price", positive=True)
        mark_price = _finite(row.get("mark_price"), "terminal.mark_price", positive=True)
        quantity = _finite(
            row.get("remaining_quantity"), "terminal.remaining_quantity", positive=True
        )
        gross = _finite(row.get("gross_unrealized_price_pnl"), "terminal.gross")
        adjusted = _finite(row.get("adjusted_unrealized_price_pnl"), "terminal.adjusted")
        cost = _finite(row.get("accrued_exit_cost"), "terminal.cost", nonnegative=True)
        contribution = _finite(row.get("accrued_nav_contribution"), "terminal.contribution")
        payoff = _finite(row.get("payoff_multiplier"), "terminal.payoff")
        position_key = (
            symbol,
            side,
            _utc(row.get("entry_ts"), "terminal.entry_ts").isoformat(),
        )
        source_entry = entry_by_position_key.get(position_key)
        if source_entry is None:
            raise BaselineReportContractError("terminal position has no matching entry fill")
        _same(
            entry_price,
            _finite(source_entry.get("entry_price"), "terminal source entry price", positive=True),
            "terminal entry price",
        )
        original_quantity = _finite(
            source_entry.get("original_quantity"),
            "terminal source original quantity",
            positive=True,
        )
        if quantity > original_quantity + max(original_quantity * 1e-10, 1e-10):
            raise BaselineReportContractError("terminal remaining quantity exceeds original entry")
        direction = 1.0 if side == "long" else -1.0
        _same(gross, direction * (mark_price - entry_price) * quantity, "terminal gross PnL")
        expected_payoff = (
            positive_multiplier if gross > 0.0 else negative_multiplier if gross < 0.0 else 1.0
        )
        _same(payoff, expected_payoff, "terminal payoff multiplier")
        _same(adjusted, gross * payoff, "terminal adjusted PnL")
        expected_terminal_cost = mark_price * quantity * cost_multiplier * 28.5 / 10_000.0
        _same(cost, expected_terminal_cost, "terminal accrued execution cost")
        _same(contribution, adjusted - cost, "terminal accrual identity")
        terminal_gross += gross
        terminal_adjusted += adjusted
        terminal_cost += cost
        terminal_contribution += contribution
        terminal_rows.append(dict(row))
        terminal_position_keys.append(position_key)

    result_execution_cost = _finite(
        complete.get("total_execution_cost_charged"), "total_execution_cost_charged"
    )
    result_funding = _finite(complete.get("total_funding_cashflow"), "total_funding")
    initial_wallet = _finite(complete.get("initial_wallet"), "initial_wallet", positive=True)
    final_wallet = _finite(complete.get("final_wallet"), "final_wallet")
    final_nav = _finite(complete.get("final_nav"), "final_nav", positive=True)
    _same(result_execution_cost, entry_cost + exit_cost, "total charged execution cost")
    _same(result_funding, funding_total, "total funding cashflow")
    _same(
        final_wallet,
        initial_wallet + adjusted_realized - entry_cost - exit_cost + funding_total,
        "final wallet identity",
    )
    _same(
        terminal_cost,
        _finite(complete.get("accrued_terminal_exit_cost"), "terminal cost"),
        "terminal cost total",
    )
    _same(final_nav, final_wallet + terminal_adjusted - terminal_cost, "final NAV identity")
    _same(final_wallet, curve.wallets[-1], "last curve wallet")
    _same(final_nav, curve.navs[-1], "last curve NAV")
    _same(terminal_gross, curve.gross_unrealized[-1], "terminal gross unrealized")
    _same(terminal_adjusted, curve.adjusted_unrealized[-1], "terminal adjusted unrealized")
    _same(terminal_cost, curve.accrued_exit_costs[-1], "terminal accrued exit cost")
    if Counter(entry_by_position_key.keys()) != Counter(
        completed_position_keys + terminal_position_keys
    ):
        raise BaselineReportContractError(
            "entry identities do not reconcile exactly to closed plus terminal positions"
        )
    if sum(row.get("is_final") is True for row in exits) != len(episodes):
        raise BaselineReportContractError("final exit fill count does not reconcile to episodes")
    if curve.open_counts[-1] != len(terminal):
        raise BaselineReportContractError("terminal open count does not match final curve")

    computed_dd = _drawdown(curve, initial_wallet, EVALUATION_START, EVALUATION_END)
    raw_dd = _finite(complete.get("max_drawdown"), "max_drawdown")
    _same(raw_dd, -computed_dd["max_drawdown_pct"] / 100.0, "raw max drawdown")

    mean_nav = statistics.fmean(curve.navs)
    turnover = {
        "filled_gross_turnover": gross_turnover,
        "arithmetic_mean_15m_nav": mean_nav,
        "filled_gross_turnover_over_arithmetic_mean_15m_nav": gross_turnover / mean_nav,
        "terminal_accrual_excluded_from_filled_turnover": True,
    }
    costs = {
        "entry": {
            "fee": entry_fee,
            "spread_slippage": entry_spread,
            "impact": entry_impact,
            "execution_cost": entry_cost,
        },
        "exit": {
            "fee": exit_fee,
            "spread_slippage": exit_spread,
            "impact": exit_impact,
            "execution_cost": exit_cost,
        },
        "total_execution_cost_charged": result_execution_cost,
        "terminal_exit_cost_accrued_not_charged": terminal_cost,
        "funding_event_count": len(funding),
        "total_funding_cashflow": funding_total,
        "gross_realized_price_pnl": gross_realized,
        "scenario_adjusted_realized_price_pnl": adjusted_realized,
    }
    identities = {
        "all_passed": True,
        "execution_cost_equals_entry_plus_exit_components": True,
        "funding_equals_event_cashflows": True,
        "final_wallet_equals_initial_plus_adjusted_realized_minus_charged_costs_plus_funding": True,
        "final_nav_equals_final_wallet_plus_terminal_adjusted_pnl_minus_terminal_exit_cost": True,
        "last_curve_point_equals_reported_terminal_state": True,
        "closed_episode_rows_reconcile": True,
        "exit_fill_rows_reconcile": True,
    }
    terminal_summary = {
        "open_position_count": len(terminal),
        "gross_unrealized_price_pnl": terminal_gross,
        "adjusted_unrealized_price_pnl": terminal_adjusted,
        "accrued_exit_cost": terminal_cost,
        "accrued_nav_contribution": terminal_contribution,
        "excluded_from_closed_episode_sample": True,
        "positions": terminal_rows,
    }
    sample = {
        "entry_fill_count": len(entries),
        "exit_fill_count": len(exits),
        "nonfinal_partial_exit_fill_count": nonfinal_partial,
        "sub_full_quantity_exit_fill_count": sub_full_fills,
        "final_exit_fill_count": sum(row.get("is_final") is True for row in exits),
        "closed_episode_count": len(episodes),
        "terminal_open_position_count": len(terminal),
        "closed_episode_net_pnl": episode_net,
    }
    return turnover, costs, identities, {"sample": sample, "terminal": terminal_summary}


def _scenario_report(
    complete: Mapping[str, Any], curve: _Curve, ledgers: Mapping[str, list[Mapping[str, Any]]]
) -> dict[str, Any]:
    initial = _finite(complete["initial_wallet"], "initial_wallet", positive=True)
    active = _activity_months(curve, ledgers)
    full = _window_metrics(curve, initial, active, EVALUATION_START, EVALUATION_END)
    development = _window_metrics(curve, initial, active, EVALUATION_START, DEVELOPMENT_END)
    pseudo = _window_metrics(curve, initial, active, DEVELOPMENT_END, EVALUATION_END)
    turnover, costs, identities, sample_terminal = _financial_summary(complete, curve, ledgers)
    return {
        "windows": {
            "full": full,
            "development": development,
            "pseudo_oos": pseudo,
        },
        "sample": sample_terminal["sample"],
        "turnover": turnover,
        "costs_and_funding": costs,
        "financial_identities": identities,
        "terminal_open_accrual": sample_terminal["terminal"],
        "concentration": _concentration(ledgers["entries"], ledgers["closed_episodes"]),
        "curve_observation_count": len(curve.timestamps),
    }


def _fold_reports(curve: _Curve, initial_wallet: float, active: set[str]) -> list[dict[str, Any]]:
    result = []
    for index, (start, end) in enumerate(FOLD_WINDOWS, start=1):
        metrics = _window_metrics(curve, initial_wallet, active, start, end)
        if metrics["month_count"] != 6:
            raise BaselineReportContractError(f"H fold {index} does not contain exactly six months")
        result.append(
            {
                "fold": index,
                "start_inclusive": start.isoformat(),
                "end_exclusive": end.isoformat(),
                "continuous_return_pct": metrics["continuous_return_pct"],
                "continuous_pnl": metrics["continuous_pnl"],
                "mean_monthly_return_pct": metrics["mean_monthly_return_pct"],
                "negative_month_count": metrics["negative_month_count"],
                "max_drawdown_pct": metrics["drawdown_and_recovery"]["max_drawdown_pct"],
                "monthly_returns_pct": [row["return_pct"] for row in metrics["monthly"]],
            }
        )
    return result


def build_report(
    raw: Mapping[str, Any], *, input_provenance: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    """Validate one raw replay payload and build a deterministic report mapping."""

    if not isinstance(raw, dict):
        raise BaselineReportContractError("raw payload must be a JSON object")
    _validate_top_level(raw)
    signal_summary, evaluation_intents = _validate_signal_stream(raw)
    scenario_reports: dict[str, Any] = {}
    validated: dict[str, tuple[Mapping[str, Any], _Curve, dict[str, list[Mapping[str, Any]]]]] = {}
    for scenario in SCENARIO_ORDER:
        validated[scenario] = _validate_result(raw, scenario)
        scenario_reports[scenario] = _scenario_report(*validated[scenario])
        window_counts = {
            name: scenario_reports[scenario]["windows"][name]["month_count"]
            for name in ("full", "development", "pseudo_oos")
        }
        if window_counts != {"full": 60, "development": 24, "pseudo_oos": 36}:
            raise BaselineReportContractError(
                f"{scenario} report windows are not exact 60/24/36 complete months"
            )
    _validate_engine_entries_are_signal_intents(evaluation_intents, validated)

    h_complete, h_curve, h_ledgers = validated["H"]
    h_initial = _finite(h_complete["initial_wallet"], "H.initial_wallet", positive=True)
    h_active = _activity_months(h_curve, h_ledgers)
    folds = _fold_reports(h_curve, h_initial, h_active)
    if len(folds) != 6 or sum(len(row["monthly_returns_pct"]) for row in folds) != 36:
        raise BaselineReportContractError("H pseudo-OOS must be exactly six 6-month folds")
    h_development = scenario_reports["H"]["windows"]["development"]
    h_pseudo = scenario_reports["H"]["windows"]["pseudo_oos"]
    if h_pseudo["month_count"] != 36:
        raise BaselineReportContractError("H pseudo-OOS must contain exactly 36 months")
    dev_return = h_development["continuous_return_pct"]
    pseudo_return = h_pseudo["continuous_return_pct"]
    dev_dd = h_development["drawdown_and_recovery"]["max_drawdown_pct"]
    pseudo_dd = h_pseudo["drawdown_and_recovery"]["max_drawdown_pct"]

    source_provenance = _mapping(raw.get("source_provenance"), "source_provenance")
    snapshots = _mapping(raw.get("snapshots"), "snapshots")
    data_lineage = _mapping(raw.get("data_lineage"), "data_lineage")
    raw_limitations = _list(raw.get("limitations"), "limitations")
    report = {
        "schema_version": REPORT_SCHEMA,
        "deterministic": True,
        "evidence_eligible": True,
        "decision": dict(_EXPECTED_DECISION),
        "classification": dict(_EXPECTED_RAW_CLASSIFICATION),
        "evaluation_window": {
            "start_inclusive": EVALUATION_START.isoformat(),
            "end_exclusive": EVALUATION_END.isoformat(),
            "development": [EVALUATION_START.isoformat(), DEVELOPMENT_END.isoformat()],
            "pseudo_oos": [DEVELOPMENT_END.isoformat(), EVALUATION_END.isoformat()],
            "continuous_replay_no_month_or_fold_resets": True,
        },
        "scenario_order": list(SCENARIO_ORDER),
        "signal_evidence": signal_summary,
        "scenarios": scenario_reports,
        "H_summary": {
            "pseudo_oos_mean_monthly_return_pct": h_pseudo["mean_monthly_return_pct"],
            "pseudo_oos_median_monthly_return_pct": h_pseudo["median_monthly_return_pct"],
            "pseudo_oos_trimmed_10pct_symmetric_mean_monthly_return_pct": h_pseudo[
                "trimmed_10pct_symmetric_mean_monthly_return_pct"
            ],
            "pseudo_oos_negative_month_count": h_pseudo["negative_month_count"],
            "pseudo_oos_months_below_minus_1pct_count": h_pseudo["months_below_minus_1pct_count"],
            "pseudo_oos_worst_month_pct": h_pseudo["worst_month_pct"],
            "full_max_drawdown_pct": scenario_reports["H"]["windows"]["full"][
                "drawdown_and_recovery"
            ]["max_drawdown_pct"],
        },
        "H_folds": folds,
        "H_development_vs_pseudo_oos": {
            "development_return_pct": dev_return,
            "pseudo_oos_return_pct": pseudo_return,
            "development_max_drawdown_pct": dev_dd,
            "pseudo_oos_max_drawdown_pct": pseudo_dd,
            "development_return_over_pseudo_oos_return": _safe_ratio(dev_return, pseudo_return),
            "pseudo_oos_return_over_development_return": _safe_ratio(pseudo_return, dev_return),
            "development_drawdown_over_pseudo_oos_drawdown": _safe_ratio(dev_dd, pseudo_dd),
            "pseudo_oos_drawdown_over_development_drawdown": _safe_ratio(pseudo_dd, dev_dd),
        },
        "limitations": {
            "raw_preregistered": raw_limitations,
            "raw_preregistered_exact_match": tuple(raw_limitations) == _EXPECTED_RAW_LIMITATIONS,
            "required_disclosures": list(_REQUIRED_LIMITATIONS),
        },
        "governance": {
            "raw_backtest_or_snapshot_access_by_reporter": False,
            "raw_contract_validated_fail_closed": True,
            "strict_finite_json_required": True,
            "holdout_accessed_by_reporter": False,
            "winner_or_deployment_verdict_possible": False,
        },
        "provenance": {
            "raw_payload_sha256": _canonical_hash(raw),
            "input_artifact": dict(input_provenance) if input_provenance is not None else None,
            "raw_git_commit": source_provenance.get("git_commit"),
            "snapshots": {
                name: {
                    "bytes": _integer(
                        _mapping(snapshots.get(name), f"snapshots.{name}").get("bytes"),
                        f"snapshots.{name}.bytes",
                        minimum=1,
                    ),
                    "sha256": str(_mapping(snapshots[name], f"snapshots.{name}").get("sha256")),
                }
                for name in ("market", "funding")
            },
            "data_lineage": {
                name: {
                    "bytes": _integer(
                        _mapping(data_lineage.get(name), f"data_lineage.{name}").get("bytes"),
                        f"data_lineage.{name}.bytes",
                        minimum=1,
                    ),
                    "sha256": str(
                        _mapping(data_lineage[name], f"data_lineage.{name}").get("sha256")
                    ),
                }
                for name in EXPECTED_DATA_LINEAGE_IDENTITIES
            },
            "raw_complete_result_sha256": {
                scenario: _mapping(raw["results"][scenario], f"results.{scenario}")[
                    "complete_result_sha256"
                ]
                for scenario in SCENARIO_ORDER
            },
        },
    }
    _assert_json_tree(report, "report")
    _canonical_hash(report)
    return report


def generate_report(input_path: Path) -> dict[str, Any]:
    """Load an artifact and produce its validated report."""

    artifact = load_json_artifact(input_path)
    return build_report(artifact.payload, input_provenance=artifact.provenance())


def _validate_frozen_report_header(report: Mapping[str, Any]) -> None:
    if report.get("schema_version") != REPORT_SCHEMA:
        raise BaselineReportContractError("output requires the frozen baseline report schema")
    decision = _mapping(report.get("decision"), "decision")
    if decision != _EXPECTED_DECISION:
        raise BaselineReportContractError(
            f"baseline report verdict must remain {VERDICT} with no deployment authority"
        )
    if _mapping(report.get("classification"), "classification") != (_EXPECTED_RAW_CLASSIFICATION):
        raise BaselineReportContractError(
            "baseline report classification must remain the exact raw six-field proxy label"
        )


def deterministic_json(report: Mapping[str, Any]) -> str:
    """Render stable strict JSON bytes."""

    _validate_frozen_report_header(report)
    _assert_json_tree(report, "report")
    return (
        json.dumps(
            report,
            sort_keys=True,
            indent=2,
            ensure_ascii=False,
            allow_nan=False,
        )
        + "\n"
    )


def _format(value: Any, *, suffix: str = "", digits: int = 2) -> str:
    if value is None:
        return "N/A"
    return f"{float(value):.{digits}f}{suffix}"


def render_markdown(report: Mapping[str, Any]) -> str:
    """Render a compact deterministic Turkish baseline readout."""

    _validate_frozen_report_header(report)
    decision = _mapping(report.get("decision"), "decision")
    scenarios = _mapping(report.get("scenarios"), "scenarios")
    lines = [
        "# Crypto 15m v15p2 — adil baseline raporu",
        "",
        "## Karar",
        "",
        f"**{decision['verdict']}**",
        "",
        "Bu çıktı yalnızca ölçülmüş `FAIR_LIVE_POLICY_PROXY` baseline'ıdır; kazanan ilanı, "
        "holdout, paper veya canlı deployment yetkisi vermez.",
        "",
        "## Senaryo özeti",
        "",
        "| Senaryo | Tam getiri | Tam DD | H-pencere trim/ay | Negatif ay | Kötü ay | "
        "Kapalı episode | Partial fill | Turnover | Maliyet | Funding | Terminal açık |",
        "|:---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for name in SCENARIO_ORDER:
        scenario = _mapping(scenarios[name], f"scenarios.{name}")
        full = scenario["windows"]["full"]
        pseudo = scenario["windows"]["pseudo_oos"]
        sample = scenario["sample"]
        lines.append(
            "| "
            + " | ".join(
                (
                    name,
                    _format(full["continuous_return_pct"], suffix="%"),
                    _format(full["drawdown_and_recovery"]["max_drawdown_pct"], suffix="%"),
                    _format(pseudo["trimmed_10pct_symmetric_mean_monthly_return_pct"], suffix="%"),
                    str(pseudo["negative_month_count"]),
                    _format(pseudo["worst_month_pct"], suffix="%"),
                    str(sample["closed_episode_count"]),
                    str(sample["nonfinal_partial_exit_fill_count"]),
                    _format(
                        scenario["turnover"]["filled_gross_turnover_over_arithmetic_mean_15m_nav"],
                        suffix="x",
                    ),
                    _format(
                        scenario["costs_and_funding"]["total_execution_cost_charged"],
                        suffix=" USDT",
                    ),
                    _format(
                        scenario["costs_and_funding"]["total_funding_cashflow"],
                        suffix=" USDT",
                    ),
                    str(sample["terminal_open_position_count"]),
                )
            )
            + " |"
        )
    signal = _mapping(report.get("signal_evidence"), "signal_evidence")
    reason_counts = _mapping(signal.get("decision_reason_counts"), "decision_reason_counts")
    lines.extend(
        [
            "",
            "## Ham sinyal karar kanıtı",
            "",
            f"- Ham strateji emisyonu (özellik geçmişi dahil): `{signal['raw_emission_count']}`",
            f"- Değerlendirme aralığı ham emisyonu: `{signal['evaluation_raw_emission_count']}`",
            f"- Uygun geçmiş intenti: `{signal['accepted_history_intent_count']}`",
            f"- Reddedilen emisyon: `{signal['rejected_history_emission_count']}`",
            f"- Motora verilen değerlendirme intenti: `{signal['evaluation_intent_count']}`",
            "- Karar nedenleri: `"
            + ", ".join(f"{key}={value}" for key, value in sorted(reason_counts.items()))
            + "`",
            f"- Karar ledger SHA-256: `{signal['decision_ledger_sha256']}`",
            "- Kabul edilen karar satırları değerlendirme intentleriyle eksiksiz ve sıralı "
            "olarak uzlaştırıldı.",
        ]
    )
    h = report["H_summary"]
    lines.extend(
        [
            "",
            "## H pseudo-OOS istikrarı",
            "",
            f"- Ortalama ay: `{_format(h['pseudo_oos_mean_monthly_return_pct'], suffix='%')}`",
            f"- Medyan ay: `{_format(h['pseudo_oos_median_monthly_return_pct'], suffix='%')}`",
            "- %10 simetrik trimli ay: "
            f"`{_format(h['pseudo_oos_trimmed_10pct_symmetric_mean_monthly_return_pct'], suffix='%')}`",
            f"- Negatif ay: `{h['pseudo_oos_negative_month_count']}/36`",
            f"- `< -%1` ay: `{h['pseudo_oos_months_below_minus_1pct_count']}/36`",
            f"- En kötü ay: `{_format(h['pseudo_oos_worst_month_pct'], suffix='%')}`",
            f"- Tam dönem 15m MTM DD: `{_format(h['full_max_drawdown_pct'], suffix='%')}`",
            "",
            "## Altı kesintisiz H dilimi",
            "",
            "| Fold | Dönem | Getiri | DD | Negatif ay |",
            "|---:|:---|---:|---:|---:|",
        ]
    )
    for fold in report["H_folds"]:
        lines.append(
            f"| {fold['fold']} | {fold['start_inclusive'][:7]}–{fold['end_exclusive'][:7]} | "
            f"{_format(fold['continuous_return_pct'], suffix='%')} | "
            f"{_format(fold['max_drawdown_pct'], suffix='%')} | "
            f"{fold['negative_month_count']} |"
        )
    lines.extend(["", "## Ham önkayıt sınırları (12/12)", ""])
    for item in report["limitations"]["raw_preregistered"]:
        lines.append(f"- `{item}`")
    lines.extend(["", "## Ayrıntılı zorunlu açıklamalar", ""])
    for item in report["limitations"]["required_disclosures"]:
        lines.append(f"- `{item['code']}`: {item['detail']}")
    provenance = report["provenance"]
    lines.extend(
        [
            "",
            "## Kanıt",
            "",
            f"- Raw payload SHA-256: `{provenance['raw_payload_sha256']}`",
            f"- Market snapshot SHA-256: `{provenance['snapshots']['market']['sha256']}`",
            f"- Funding snapshot SHA-256: `{provenance['snapshots']['funding']['sha256']}`",
            "- B/C2/H finansal kimlikleri ve terminal tahakkukları yeniden hesaplanıp geçti.",
            "- Aylık baseline her ay başlangıcından kesin olarak önceki son 15m NAV'dır; "
            "ay/fold sermaye reseti yoktur.",
            "",
        ]
    )
    return "\n".join(lines)


def _validate_output_paths(
    input_path: Path, json_output: Path | None, markdown_output: Path | None
) -> tuple[Path | None, Path | None]:
    resolved_input = input_path.resolve()
    outputs = [path.resolve() for path in (json_output, markdown_output) if path is not None]
    if len(set(outputs)) != len(outputs):
        raise BaselineReportContractError("JSON and Markdown outputs must be distinct")
    for output in outputs:
        if output == resolved_input:
            raise BaselineReportContractError("an output may not overwrite the input")
        if output.exists() or output.is_symlink():
            raise FileExistsError(f"refusing to overwrite existing output: {output}")
    if json_output is not None and json_output.suffix.lower() != ".json":
        raise BaselineReportContractError("--json-output must end in .json")
    if markdown_output is not None and markdown_output.suffix.lower() not in {".md", ".markdown"}:
        raise BaselineReportContractError("--markdown-output must end in .md or .markdown")
    return (
        json_output.resolve() if json_output is not None else None,
        markdown_output.resolve() if markdown_output is not None else None,
    )


def _write_exclusive(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary = handle.name
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        # Same-filesystem hard-link publication is atomic and preserves the
        # no-overwrite contract: an existing final path raises FileExistsError.
        os.link(temporary, path)
        Path(temporary).unlink()
        temporary = None
    finally:
        if temporary is not None:
            Path(temporary).unlink(missing_ok=True)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--json-output", type=Path)
    parser.add_argument("--markdown-output", type=Path)
    parser.add_argument("--stdout", choices=("json", "markdown"), default="markdown")
    args = parser.parse_args(argv)
    json_output, markdown_output = _validate_output_paths(
        args.input, args.json_output, args.markdown_output
    )
    report = generate_report(args.input)
    rendered_json = deterministic_json(report)
    rendered_markdown = render_markdown(report)
    created: list[Path] = []
    try:
        if json_output is not None:
            _write_exclusive(json_output, rendered_json)
            created.append(json_output)
        if markdown_output is not None:
            _write_exclusive(markdown_output, rendered_markdown)
            created.append(markdown_output)
    except BaseException:
        for path in created:
            path.unlink(missing_ok=True)
        raise
    print(rendered_json if args.stdout == "json" else rendered_markdown, end="")
    return 0


__all__ = [
    "RAW_SCHEMA",
    "REPORT_SCHEMA",
    "VERDICT",
    "BaselineReportContractError",
    "JsonArtifact",
    "build_report",
    "deterministic_json",
    "generate_report",
    "load_json_artifact",
    "main",
    "render_markdown",
]


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
