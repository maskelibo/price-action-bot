"""Fail-closed lab accept-gate contract tests."""

from __future__ import annotations

from price_action.lab.acceptance_gates import (
    GateStatus,
    enforce_acceptance_contract,
    evaluate_accept_gate,
)


def _result() -> dict:
    return {
        "status": "OK",
        "verdict": "GO",
        "annualized": 42.0,
        "oos_sharpe": 1.4,
        "max_dd": -18.0,
        "mean_R_after_fees": 0.12,
        "n_taken": 220,
        "trades_per_year": 120.0,
        "monthly_roi": 2.1,
        "oos_returns": [1.0, -0.5, 0.8, 0.2],
    }


def test_numeric_gates_are_typed_and_evaluated() -> None:
    result = _result()
    assert evaluate_accept_gate("OOS_Sharpe >= 1.0", result)["passed"] is True
    assert evaluate_accept_gate("max_drawdown_pct < 25", result)["passed"] is True
    assert evaluate_accept_gate("WR >= 70%", result)["passed"] is True
    assert evaluate_accept_gate("profit_factor > 2", result)["passed"] is True


def test_unknown_or_ambiguous_gate_fails_closed() -> None:
    row = evaluate_accept_gate("better than production", _result())
    assert row["status"] == GateStatus.UNSUPPORTED
    assert row["passed"] is False


def test_bare_go_without_independent_evidence_becomes_research_go() -> None:
    result = _result()
    contract = enforce_acceptance_contract(
        ["annualized_return > 25", "OOS_Sharpe >= 1.0", "max_dd < 30"],
        result,
    )
    assert contract["all_requested_gates_passed"] is True
    assert contract["promotion_eligible"] is False
    assert result["raw_verdict"] == "GO"
    assert result["verdict"] == "RESEARCH_GO"
    assert result["evidence_class"] == "DESCRIPTIVE_REUSED_HISTORY"


def test_missing_or_failed_gate_turns_go_into_hold() -> None:
    result = _result()
    contract = enforce_acceptance_contract(["walk_forward", "OOS_Sharpe > 5"], result)
    assert contract["all_requested_gates_passed"] is False
    assert result["verdict"] == "HOLD_GATE_FAILURE"
    assert {row["status"] for row in contract["outcomes"]} == {
        GateStatus.MISSING_EVIDENCE,
        GateStatus.FAIL,
    }


def test_only_explicit_independent_oos_can_be_promotion_eligible() -> None:
    result = _result()
    result["evidence"] = {
        "evidence_class": "INDEPENDENT_OOS",
        "independent_oos": True,
        "deployment_authorized": True,
        "gates": {"walk_forward": {"passed": True}},
    }
    contract = enforce_acceptance_contract(["walk_forward"], result)
    assert contract["promotion_eligible"] is True
    assert result["verdict"] == "PROMOTION_GATE_PASS"


def test_red_verdict_cannot_become_promotion_eligible_from_attached_evidence() -> None:
    result = _result()
    result["verdict"] = "RED"
    result["evidence"] = {
        "evidence_class": "INDEPENDENT_OOS",
        "independent_oos": True,
        "deployment_authorized": True,
        "gates": {"walk_forward": {"passed": True}},
    }

    contract = enforce_acceptance_contract(["walk_forward"], result)

    assert contract["all_requested_gates_passed"] is True
    assert contract["independent_oos_authorized"] is True
    assert contract["promotion_eligible"] is False
    assert result["verdict"] == "RED"
