"""Append seed-abort log entry for vsa_climax_test wide-stop sl_pct_min parameter sweep v1.

Pre-test reject. RAG_TOPICAL_RELEVANCE 0/10. Prior art: 2 prior sweep grids + Principal
2026-05-30 decision (0.025 live, 0.02375 vetted not deployed). Curve-fit prompt injection.
First abort for this seed string -> doc + JSONL written; self-throttle armed for next 24h.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOG = ROOT / "memory" / "researcher" / "seed_abort_log.jsonl"

entry = {
    "ts": "2026-05-30T12:00:00Z",
    "agent": "researcher",
    "seed": "vsa_climax_test-wide-stop-sl_pct_min-parameter-sweep",
    "trigger_n": 1,
    "siblings_in_family": 0,
    "abort_docs_24h": 0,
    "abort_jsonl_24h": 0,
    "rag_hits_raw": 10,
    "rag_hits_topical": 0,
    "rag_topical_note": (
        "10 refs returned: #1 SMC liquidity sweep entry+stop=wick+0.2-0.5xATR (different setup); "
        "#2 volume divergence threshold sweep vol_B/vol_A=0.60-0.90 (different parameter); "
        "#3 Lopez Bollinger %B<0.05+frac-diff mean-reversion (different setup); "
        "#4 Brooks SR 3-bar test stop=level-1tick (different mechanism); "
        "#5 Grimes range stop=sinir+0.3-0.5 ATR (different setup); "
        "#6 SMC OB premium/discount (zone-structure confluence not stop mechanics); "
        "#7 Brooks SR reversal bar stop=bar opposite end+1tick (no ATR multi sweep); "
        "#8 SMC HTF+LTF methodology chunk -- ACTIVELY HOSTILE: predicts community claims fall "
        "under deflated-Sharpe+multiple-param-sets+PBO testing, warns marginal/zero net edge; "
        "#9 EQH sweep entry/stop mechanics; "
        "#10 OCaml magic-trace expect tests (embedding garbage). "
        "Effective topical relevance to vsa_climax wide-stop sl_pct_min sweep specifically: 0/10. "
        "Pattern D RAG_TOPICAL_RELEVANCE fires for 12th distinct seed-event this week."
    ),
    "family_wise_N_7d": 16,
    "holm_alpha_per_m_current": 0.00313,
    "holm_alpha_per_m_if_written": 0.00294,
    "prompt_injection_detected": True,
    "injection_string": "Curve-fit suphesi yarat",
    "prior_art": {
        "tur1_2026-05-28": (
            "3-agent paralel (researcher+analyst+adversary) -> KORU consensus, "
            "sl_pct_min=0.025 (15m) / 0.030 (5m); 0.018 contDD -32.7% gate-violation"
        ),
        "tur2_2026-05-30": (
            "0.02375 grid added with 55bps+100bps stress, vetted candidate "
            "(DD -19.4 better than current 0.025), Principal decision: VALID but NOT DEPLOYED "
            "(config 0.025 stays live)"
        ),
        "memory_block": (
            "MEMORY.md top-index entry 'widestop-threshold-validated' marks this as BLOCKED with "
            "explicit re-evaluation gate (3 conditions: live fee <=75bps, 4/4 crisis DD <=+5pt, "
            "synthetic flash-crash replay pass) -- none met"
        ),
        "sweep_grids_consumed": 2,
        "sweep_points_tested": ["0.018", "0.020", "0.022", "0.02375", "0.025", "0.028", "0.030"],
    },
    "reasons": [
        "prior_art_principal_decision_active_2026-05-30_config_0.025_live",
        "rag_topical_relevance_zero_10of10_pattern_D",
        "prompt_injection_hard_limit_zitti_curve_fit_manufacture_request",
        "duplicate_scope_2_prior_sweep_grids_no_new_axis",
        "family_wise_N_inflation_marginal_value_<=0",
        "re_evaluation_gate_3_conditions_none_met_no_new_evidence",
        "ref8_lopez_smc_methodology_actively_hostile_predicts_PBO_failure_on_iterated_sweep",
    ],
    "action": "DOC_WRITTEN_FIRST_ABORT",
    "doc_id": "researcher-20260530T120000-vsaclimax-widestop-slpctmin-sweep-seed-abort",
    "decision": "REJECTED_PRE_TEST",
    "bias_check": (
        "none. reject-more-than-you-accept discipline holds for 10+ consecutive seed-aborts "
        "this week. Strong opinions loosely held; will instantly reverse if "
        "(a) Execution Chief delivers live effective-fee measurement <=75bps (gate 1), "
        "(b) Adversary delivers 4/4 crisis-window low-threshold DD <=+5pt (gate 2), "
        "(c) Principal writes explicit 'reopen this threshold' directive."
    ),
    "self_throttle_armed": True,
    "self_throttle_rule": (
        "next trigger within 24h => JSONL-only no doc per vsa-companion v7=>v8 + "
        "weekend-gap-fill v2=>v3 + brooks-failed-breakout v2=>v3 + engulfing v2=>v3 + "
        "daily-scan v2=>v3 precedents"
    ),
    "escalation": {
        "ops_engineer_sla": "2026-06-03",
        "ops_guards_needed": [
            "#1 per-seed cron cooldown",
            "#5 DUPLICATE_SCOPE_CHECK",
            "#6 PRIOR_ART_OPEN_BLOCK (Principal-decided seeds)",
            "#7 RAG_TOPICAL_RELEVANCE cosine<0.40",
            "G2 prompt-injection sanitizer regex",
        ],
        "ceo_directive_draft_on_SLA_expire": (
            "freeze seed 90d alongside vsa-companion v5 moratorium + rotate cron to "
            "RAG-independent + universe-internal + low-freedom-degree alternatives "
            "(brooks parametric Donchian-N + confirm-window per 2026-05-30 "
            "brooks-confirmation-window-sweep, brooks crypto transfer WINNER-LET-RUN, "
            "brooks 7fx runner-trail, brooks 1H diversifier, funding-rate regime gate)"
        ),
        "execution_chief_query": (
            "live effective-fee measurement from reconciliation log -- if <=75bps then "
            "gate 1 passes and re-evaluation legitimately opens"
        ),
    },
    "next_review": (
        "after Execution Chief live-fee measurement <=75bps OR Adversary 4/4 crisis-window "
        "DD analysis OR Principal explicit reopen directive OR 2026-06-03 ops SLA expiry"
    ),
}


def main() -> None:
    with LOG.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    print(f"appended seed-abort entry for seed={entry['seed']!r} to {LOG}")


if __name__ == "__main__":
    main()
