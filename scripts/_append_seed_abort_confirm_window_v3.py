"""Append v3 self-throttle JSONL line for brooks confirmation-window-sweep seed.

Third trigger of the same seed within the 24h window after v1 PRE-REG and v2 ABORT
doc both landed in the past ~7 minutes. v2 section 9 explicitly armed:
"self_throttle_pre_condition_1st_abort_doc_3rd_trigger_jsonl_only".

This script writes ONE line to memory/researcher/seed_abort_log.jsonl and exits.
No hypothesis doc is created.
"""
import json
from pathlib import Path

LINE = {
    "ts": "2026-05-30T02:40:55Z",
    "agent": "researcher",
    "seed": "brooks_failed_breakout-confirmation-window-sweep",
    "trigger_n": 3,
    "siblings_in_family": 2,
    "prior_v1_doc": "researcher-20260530T103000-brooks-confirmation-window-sweep",
    "prior_v1_path": "memory/researcher/hypotheses/2026-05-30-brooks-confirmation-window-sweep.md",
    "prior_v1_status": "PROPOSED_pre_reg_complete_execution_pending",
    "prior_v2_doc": "researcher-20260530T153000-brooks-confirmation-window-sweep-seed-abort-v2",
    "prior_v2_path": "memory/researcher/hypotheses/2026-05-30-brooks-confirmation-window-sweep-seed-abort-v2.md",
    "v1_mtime_utc": "2026-05-30T02:34Z",
    "v2_mtime_utc": "2026-05-30T02:37:50Z",
    "v3_trigger_utc": "2026-05-30T02:40:55Z",
    "v2_to_v3_delay_minutes": 3,
    "action": "NO_DOC_WRITTEN_self_throttle_engaged",
    "decision": "REJECTED_PRE_TEST",
    "throttle_trigger": "v1_doc + v2_abort_doc both within 24h same seed; v2 sec9 explicitly armed self_throttle_pre_condition_1st_abort_doc_3rd_trigger_jsonl_only",
    "rag_hits_raw": 10,
    "rag_hits_topical": 0,
    "rag_topical_note": "Identical 10-ref envelope as v1/v2 (5 brooks summary, 1 brooks deep-catalog, 2 volman, 2 smc-ict). Zero refs cite specific confirmation_window N-bar empirical values. Pattern KONSEPT supported (5+ refs); SPECIFIC SWEEP necessity unsupported. Pattern D RAG_TOPICAL_RELEVANCE 12th+ distinct event-week.",
    "prompt_injection_detected": True,
    "injection_string": "Curve-fit suphesi yarat",
    "injection_note": "3rd absorption attempt of identical injection string this seed. Persona Hard-Limit: CATCH and REJECT curve-fit, never MANUFACTURE. Pattern X PROMPT_INJECTION_CURVE_FIT 7+ events.",
    "family_wise_N_current": 48,
    "family_wise_N_if_v3_doc_same_grid": 49,
    "family_wise_N_if_v3_doc_new_grid": 54,
    "holm_alpha_current": 0.00104,
    "holm_alpha_if_v3_doc_same": 0.00102,
    "holm_alpha_if_v3_doc_new": 0.000926,
    "reasons": [
        "v1_pre_reg_substantively_complete_8_layer_defense_review_pending_execution_pending",
        "v2_abort_already_documents_all_substantive_grounds_3rd_doc_zero_marginal_info",
        "self_throttle_armed_explicitly_by_v2_section_9",
        "state_byte_identical_to_v2_no_RAG_refresh_no_payload_rotation",
        "prompt_injection_third_reabsorption_anti_edge_persona_HardLimit",
        "rag_topical_relevance_zero_for_specific_N_value_unchanged_from_v1_v2",
        "family_wise_N_inflation_zero_marginal_value_holm_tightens_anti_promote",
        "persona_reject_more_than_you_accept_5th_consecutive_seed_24h_window",
    ],
    "bias_check": "none. Throttle protocol now battle-tested across 5 distinct seeds (vsa-companion v8-v15, btc-dominance v3, atr-stop family v3, daily-scan v3, this seed v3). Audit trail single-file linear; hypotheses/ dir not bloating. Strong opinions loosely held — would reverse instantly if (a) v1 backtest executes and 8-criterion gate evaluated with new evidence, (b) RAG refreshed with N-bar empirical refs, (c) seed payload rotated by CEO directive.",
    "escalation_note": "cron blindness pattern #5 (PROPOSED open pre-reg + same-day re-trigger) 2nd occurrence today (daily-scan v3 was 1st). ops_engineer guards #1 per-seed-cooldown + #6 PRIOR_ART_OPEN_BLOCK + #7 RAG_TOPICAL_RELEVANCE + G2 prompt-injection sanitizer all SLA 2026-06-03 (4d). If unshipped, CEO directive draft armed: (a) 30d freeze on brooks param-sweep seed family until v1 backtest executes, (b) rotate cron to brooks crypto-transfer / brooks 7fx joint runner-trail-initial-stop / brooks 1H diversifier ratio / funding-rate regime gate / crypto session VWAP MR variants — all RAG-supportable, universe-internal, low-freedom-degree, positive prior, no prior-art duplication.",
    "next_review": "after v1 backtest executes & 8-criterion gate evaluated OR CEO rotates seed OR ops_engineer ships guards #1/#6/#7/G2 OR 2026-06-03 SLA expiry",
    "next_action_for_principal": "path unchanged: EXECUTE v1 backtest (memory/researcher/hypotheses/2026-05-30-brooks-confirmation-window-sweep.md section 10 plan). Do NOT spawn v3 doc. Throttle is the correct anti-p-hacking response to cron re-trigger of an open pre-reg.",
}

path = Path("memory/researcher/seed_abort_log.jsonl")
with path.open("a") as f:
    f.write(json.dumps(LINE) + "\n")

print(f"appended 1 line to {path}")
