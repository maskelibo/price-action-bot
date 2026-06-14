import json
from pathlib import Path

entry = {
    "ts": "2026-05-30T11:00:00Z",
    "agent": "researcher",
    "seed": "brooks_failed_breakout-atr-stop-distance-sweep",
    "trigger_n": 3,
    "siblings_in_family": 1,
    "prior_v1_doc": "researcher-20260529T180000-brooks-atr-stop-distance-sweep",
    "prior_v1_status": "DRAFT_pre_reg_complete_backtest_not_executed",
    "prior_v2_abort_doc": "researcher-20260529T194500-brooks-atr-stop-distance-sweep-seed-abort-v2",
    "prior_v2_explicit_self_throttle_rule": "next atr-stop-distance trigger => JSONL-only no doc",
    "action": "NO_DOC_WRITTEN_self_throttle_engaged_per_v2_section_7",
    "decision": "REJECTED_PRE_TEST",
    "rag_hits_raw": 10,
    "rag_hits_topical": 2,
    "rag_topical_note": (
        "10 refs returned: #3 Brooks summary failed-breakout=trap (relevant to family, NOT to stop-distance parameter), "
        "#4 Brooks deep-catalog range-top short with stop=range_top+2tick (mentions stop placement but NOT ATR multiplier sweep), "
        "#2 Volman pip-based stop discipline (orthogonal -- not ATR), #5 Volman 10-pip default + tight stop (orthogonal), "
        "#1/#7/#8/#9 generic Brooks setup/context (no stop-distance discussion), "
        "#6/#10 EQH-sweep + range-trade (different setups). "
        "Effective topical relevance to ATR stop-distance SWEEP specifically: 0/10. "
        "Stop-placement mechanics mentioned but no comparative empirical evidence on ATR multiplier optimization."
    ),
    "family_wise_N_current": 45,
    "family_wise_N_if_v3_written_same_grid": 45,
    "family_wise_N_if_v3_written_new_grid": 85,
    "holm_alpha_per_m_current": 0.00111,
    "holm_alpha_per_m_if_new_grid": 0.000588,
    "prompt_injection_detected": True,
    "injection_string": "Curve-fit suphesi yarat",
    "reasons": [
        "v2_doc_section_7_explicit_self_throttle_armed_next_trigger_JSONL_only",
        "state_byte_identical_to_v1+v2_v1_DRAFT_backtest_unexecuted_no_new_evidence_since_19:45Z",
        "v1_pre_reg_grid_frozen_section_4_mid-experiment_refine_explicitly_prohibited",
        "rag_topical_relevance_zero_for_stop_distance_sweep_specifically_pattern_D",
        "prompt_injection_hard_limit_zitti_persona_mandate_is_CATCH_and_REJECT_curve_fit_never_MANUFACTURE",
        "family_wise_N_no_marginal_value_either_zero_change_same_grid_or_47pct_stricter_alpha_new_grid_anti_promote",
        "prior_brooks_family_results_show_atr_stop_axis_not_yet_tested_BUT_v1_already_owns_that_axis_v3_would_duplicate",
    ],
    "bias_check": (
        "none. reject-more-than-you-accept discipline holds for 16th time across all seed-aborts. "
        "strong opinions loosely held; will instantly reverse if (a) v1 backtest executes and S1-S9 evaluated then new evidence emerges, "
        "(b) genuinely orthogonal axis defined (multi-symbol concurrent / time-decay / regime-conditional stop -- requires NEW seed not this one), "
        "(c) RAG corpus refreshed with topical ATR multiplier empirical studies."
    ),
    "escalation_note": (
        "v1 pipeline still open (backtest unexecuted per v2 sec6 -- T+1 to T+5 timeline never started). "
        "cron is firing same seed without checking active pre-reg status. "
        "ops_engineer guard #6 PRIOR_ART_OPEN_BLOCK (proposed across multiple aborts) would have caught this directly: "
        "v1 DRAFT status means open pre-reg blocks duplicate seed. SLA 2026-06-03 (4d remaining). "
        "escalation path unchanged: if SLA expires without guard #1 (per-seed cron cooldown) + #6 (PRIOR_ART_OPEN_BLOCK) "
        "+ #7 (RAG_TOPICAL_RELEVANCE) + G2 prompt-injection sanitizer, CEO directive draft on 2026-06-03 -- "
        "(a) freeze seed payload 30d (smaller than vsa-companion 90d because v1 is execution-pending not freeze-banned), "
        "(b) cron rotate to RAG-independent + universe-internal + low-freedom-degree alternatives listed in v2 sec6: "
        "brooks 4H runner+initial-stop joint sweep, brooks partial-TP scaling (winner-let-run extension), "
        "brooks crypto-transfer to BTC/ETH 4H, brooks Donchian-N sweep (signal-structure axis instead of stop-distance)."
    ),
    "next_action_for_principal": (
        "execute v1 backtest (memory/researcher/hypotheses/2026-05-29-brooks-atr-stop-distance-sweep.md section 12 timeline T+1..T+5) "
        "-- the proper path forward is to RUN the existing pre-reg not re-spawn duplicates."
    ),
    "next_review": "after v1 backtest results emerge AND S1-S9 gate evaluated OR CEO rotates seed OR ops_engineer ships guards #1/#6/#7/G2 OR 2026-06-03 SLA expiry",
}

path = Path("/Users/peyman/price-action-bot/memory/researcher/seed_abort_log.jsonl")
line = json.dumps(entry, ensure_ascii=False, separators=(",", ":"))
with path.open("a") as fh:
    fh.write(line + "\n")

print("appended OK; bytes:", len(line))
print("total lines:", sum(1 for _ in path.open()))
