"""Typed, fail-closed acceptance gates for autonomous lab results.

Historically ``HypothesisSpec.accept_gates`` was persisted but never checked.
This module turns each requested gate into an auditable outcome.  Unsupported,
ambiguous, missing, or non-finite evidence is a failure, never an implicit
pass.  Passing these research gates still does not constitute independent OOS
promotion evidence.
"""

from __future__ import annotations

import math
import re
from enum import StrEnum
from typing import Any


class GateStatus(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    UNSUPPORTED = "UNSUPPORTED"
    MISSING_EVIDENCE = "MISSING_EVIDENCE"
    INVALID = "INVALID"


REQUIRED_ROBUSTNESS_GATES = frozenset(
    {
        "walk_forward",
        "in_out_of_sample_consistency",
        "param_perturbation",
        "symbol_out_cv",
        "regime_split",
        "stress_periods",
        "shuffle_baseline",
        "multiple_testing_correction",
    }
)

_METRIC_ALIASES = {
    "annualized": "annualized",
    "annualized_return": "annualized",
    "annualized_return_pct": "annualized",
    "annual_net_return": "annualized",
    "annual_return": "annualized",
    "net_annual_return_pct": "annualized",
    "oos_annual_return": "annualized",
    "oos_sharpe": "oos_sharpe",
    "sharpe_oos": "oos_sharpe",
    "sharpe_oos_mean": "oos_sharpe",
    "daily_sharpe_net": "oos_sharpe",
    "max_dd": "max_dd_abs",
    "max_drawdown": "max_dd_abs",
    "max_drawdown_pct": "max_dd_abs",
    "max_dd_equity": "max_dd_abs",
    "oos_maxdd": "max_dd_abs",
    "mean_r_after_fees": "mean_R_after_fees",
    "mean_r": "mean_R_after_fees",
    "mr": "mean_R_after_fees",
    "n_trade": "n_trades",
    "n_trades": "n_trades",
    "min_trades": "n_trades",
    "trades_per_year": "trades_per_year",
    "monthly_roi": "monthly_roi",
    "win_rate": "win_rate",
    "wr": "win_rate",
    "profit_factor": "profit_factor",
}

_GATE_RE = re.compile(
    r"^\s*([A-Za-z0-9_]+)\s*(<=|>=|<|>|==)\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+))\s*(%)?\s*$"
)


def _finite(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _derived_metrics(result: dict[str, Any]) -> dict[str, float | None]:
    returns = result.get("oos_returns")
    clean_returns: list[float] = []
    if isinstance(returns, list):
        for value in returns:
            parsed = _finite(value)
            if parsed is not None:
                clean_returns.append(parsed)
    gross_win = sum(value for value in clean_returns if value > 0)
    gross_loss = -sum(value for value in clean_returns if value < 0)
    n_trades = result.get("n_taken")
    if n_trades is None:
        n_trades = result.get("n_trades_raw")
    max_dd = _finite(result.get("max_dd"))
    return {
        "annualized": _finite(result.get("annualized")),
        "oos_sharpe": _finite(result.get("oos_sharpe")),
        "max_dd_abs": abs(max_dd) if max_dd is not None else None,
        "mean_R_after_fees": _finite(result.get("mean_R_after_fees")),
        "n_trades": _finite(n_trades),
        "trades_per_year": _finite(result.get("trades_per_year")),
        "monthly_roi": _finite(result.get("monthly_roi")),
        "win_rate": (
            sum(value > 0 for value in clean_returns) / len(clean_returns)
            if clean_returns
            else None
        ),
        "profit_factor": gross_win / gross_loss if gross_loss > 0 else None,
    }


def _compare(actual: float, operator: str, threshold: float) -> bool:
    if operator == ">":
        return actual > threshold
    if operator == ">=":
        return actual >= threshold
    if operator == "<":
        return actual < threshold
    if operator == "<=":
        return actual <= threshold
    return actual == threshold


def _named_robustness_gate(name: str, result: dict[str, Any]) -> dict[str, Any] | None:
    canonical = name.strip().lower().replace("-", "_").replace(" ", "_")
    if canonical not in REQUIRED_ROBUSTNESS_GATES and canonical != "independent_oos":
        return None
    evidence = result.get("evidence")
    if not isinstance(evidence, dict):
        status = GateStatus.MISSING_EVIDENCE
        actual = None
    elif canonical == "independent_oos":
        actual = (
            evidence.get("evidence_class") == "INDEPENDENT_OOS"
            and evidence.get("independent_oos") is True
        )
        status = GateStatus.PASS if actual else GateStatus.FAIL
    else:
        gates = evidence.get("gates")
        row = gates.get(canonical) if isinstance(gates, dict) else None
        actual = row.get("passed") if isinstance(row, dict) else None
        status = (
            GateStatus.PASS
            if actual is True
            else GateStatus.FAIL
            if actual is False
            else GateStatus.MISSING_EVIDENCE
        )
    return {
        "requested": name,
        "canonical": canonical,
        "status": status.value,
        "passed": status is GateStatus.PASS,
        "actual": actual,
    }


def evaluate_accept_gate(gate: Any, result: dict[str, Any]) -> dict[str, Any]:
    """Evaluate one strict gate expression or named robustness gate."""

    if not isinstance(gate, str) or not gate.strip():
        return {
            "requested": gate,
            "canonical": None,
            "status": GateStatus.INVALID.value,
            "passed": False,
            "reason": "gate must be a non-empty string",
        }
    named = _named_robustness_gate(gate, result)
    if named is not None:
        return named

    match = _GATE_RE.fullmatch(gate)
    if match is None:
        return {
            "requested": gate,
            "canonical": None,
            "status": GateStatus.UNSUPPORTED.value,
            "passed": False,
            "reason": "unsupported or ambiguous gate syntax",
        }
    raw_metric, operator, threshold_raw, percent = match.groups()
    canonical_metric = _METRIC_ALIASES.get(raw_metric.lower())
    if canonical_metric is None:
        return {
            "requested": gate,
            "canonical": None,
            "status": GateStatus.UNSUPPORTED.value,
            "passed": False,
            "reason": f"unsupported metric: {raw_metric}",
        }
    threshold = float(threshold_raw)
    # win rate is represented as 0..1; explicit percentages are converted.
    if canonical_metric == "win_rate" and percent:
        threshold /= 100.0
    actual = _derived_metrics(result)[canonical_metric]
    if actual is None:
        return {
            "requested": gate,
            "canonical": canonical_metric,
            "operator": operator,
            "threshold": threshold,
            "actual": None,
            "status": GateStatus.MISSING_EVIDENCE.value,
            "passed": False,
        }
    passed = _compare(actual, operator, threshold)
    return {
        "requested": gate,
        "canonical": canonical_metric,
        "operator": operator,
        "threshold": threshold,
        "actual": actual,
        "status": (GateStatus.PASS if passed else GateStatus.FAIL).value,
        "passed": passed,
    }


def enforce_acceptance_contract(
    requested_gates: list[str] | None,
    result: dict[str, Any],
) -> dict[str, Any]:
    """Attach an effective research verdict and promotion-safe gate record."""

    requested = requested_gates if isinstance(requested_gates, list) else []
    outcomes = [evaluate_accept_gate(gate, result) for gate in requested]
    gates_passed = bool(outcomes) and all(row["passed"] is True for row in outcomes)
    evidence = result.get("evidence") if isinstance(result.get("evidence"), dict) else {}
    independent = (
        evidence.get("evidence_class") == "INDEPENDENT_OOS"
        and evidence.get("independent_oos") is True
        and evidence.get("deployment_authorized") is True
    )
    raw_verdict = result.get("verdict")
    raw_go = raw_verdict == "GO"
    if raw_go:
        if not gates_passed:
            effective = "HOLD_GATE_FAILURE"
        elif not independent:
            effective = "RESEARCH_GO"
        else:
            effective = "PROMOTION_GATE_PASS"
        result["raw_verdict"] = raw_verdict
        result["verdict"] = effective
    else:
        effective = str(raw_verdict or result.get("status") or "UNKNOWN")

    contract = {
        "schema_version": "lab-acceptance-v1",
        "requested_count": len(requested),
        "all_requested_gates_passed": gates_passed,
        "independent_oos_authorized": independent,
        "promotion_eligible": bool(raw_go and gates_passed and independent),
        "effective_verdict": effective,
        "outcomes": outcomes,
    }
    result["acceptance_contract"] = contract
    result["promotion_eligible"] = contract["promotion_eligible"]
    result.setdefault("evidence_class", "DESCRIPTIVE_REUSED_HISTORY")
    return contract
