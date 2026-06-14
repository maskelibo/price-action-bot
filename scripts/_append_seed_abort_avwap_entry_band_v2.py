"""One-shot: append v2 self-throttle entry for anchored_vwap_entry_band_sweep seed."""
import json
from pathlib import Path

entry = {
    "ts": "2026-05-30T02:45:00Z",
    "seed": "anchored-vwap-entry-band-sweep",
    "trigger_n": 2,
    "siblings_in_family": 1,
    "prior_art_doc": "2026-05-08-anchored-vwap-poc-reversal.md",
    "prior_art_status": "NOT_EXECUTABLE",
    "prior_abort_doc": "2026-05-30-anchored-vwap-entry-band-sweep-seed-abort.md",
    "prior_abort_hours_ago": "intraday",
    "abort_docs_24h": 1,
    "abort_jsonl_24h": 0,
    "rag_hits_raw": 10,
    "rag_hits_topical": 0,
    "rag_topical_note": (
        "identical 10-ref payload to v1 trigger: stockcharts S/R+candlesticks (#1), "
        "dailypriceaction pin bar (#2), candlestick outside-bar stats (#3), "
        "stockcharts bearish reversal (#4), smc/ict summary (#5), stockcharts SMA/EMA (#6), "
        "OCaml sonic-distance robot car (#7 IRRELEVANT lexical match on 'distance'), "
        "kaufman BB/RSI/Z-score mean-reversion (#8 ANTI-evidence: 'trending rejimlerde catastrophic'), "
        "lopez meta-labeling (#9), KataGo hyperparam training (#10 IRRELEVANT lexical match on 'lookback window'). "
        "ZERO chunks on anchored VWAP / VWAP-to-price distance threshold / POC reversal entry band."
    ),
    "family_wise_N_7d": 23,
    "holm_alpha_if_v2": 2.08e-3,
    "reason": (
        "SELF-THROTTLE ARMED per v1 abort doc sec5 (2nd-trigger-writes-doc-with-state-delta protocol). "
        "State delta vs v1 = 0: (a) scripts/run_avwap_backtest.py still MISSING (ls confirmed 2026-05-30T02:44Z), "
        "(b) v1 hypothesis avwap_poc_reversal_v1 still NOT_EXECUTABLE, "
        "(c) RAG topical=0 identical 10-ref payload, "
        "(d) prompt injection phrase 'Curve-fit suphesi yarat' byte-identical to v1, "
        "(e) ops_engineer guards #1-8 still pending SLA 2026-06-03, "
        "(f) no CEO directive. "
        "Writing v2 substantive hypothesis would: (1) SOP-5 fire (RAG topical=0); "
        "(2) violate PRIOR_ART_OPEN_BLOCK (v1 NOT_EXECUTABLE); "
        "(3) direct Hard-Limit violation via prompt injection; "
        "(4) inflate family-wise N 23->24, tighten Holm alpha/m ~4.5% for zero added evidence. "
        "v2 abort doc itself written ONLY to record self-throttle state transition into audit trail "
        "(1st->doc, 2nd->doc+arm, 3rd+->JSONL-only)."
    ),
    "action": "DOC_WRITTEN_audit_trail_for_second_trigger_and_self_throttle_armed",
    "decision": "REJECTED_PRE_TEST",
    "escalation_note": (
        "15th distinct seed-abort in 72h hitting cron-payload root cause "
        "(RAG_TOPICAL_RELEVANCE=0 pattern D + PRIOR_ART_OPEN_BLOCK + ANTI_PERSONA_PHRASE injection). "
        "Dispatches unchanged from v1: "
        "(a) signal_chief ship scripts/run_avwap_backtest.py to unblock v1 EXECUTABLE state -- 2nd reminder; "
        "(b) ops_engineer ship guards #1-8 SLA 2026-06-03 -- 4/8 guards "
        "(#4 FREEDOM_DEGREES_MAX, #6 PRIOR_ART_OPEN_BLOCK, #7 RAG_TOPICAL_RELEVANCE, #8 ANTI_PERSONA_PHRASE_STRIP) "
        "would independently block this trigger; "
        "(c) CEO directive draft post-SLA: 90d freeze + rotate cron payload to "
        "brooks_failed_breakout_4h_runner_trail_sweep / vsa_climax_test_15m_runner_trail_sweep / "
        "brooks_failed_breakout_crypto_perp_transfer / brooks_failed_breakout_1h_diversifier_ratio_sweep / "
        "funding_rate_regime_gate_for_engulfing_continuation "
        "(all RAG-independent + universe-internal + positive prior + 1-knob); "
        "(d) lab_scientist RAG topical refresh on Beyder/Shannon/Hassonjee AVWAP sources."
    ),
    "self_throttle_pre_arm": (
        "3rd+ trigger arriving by 2026-05-31T02:45Z -> JSONL-only continues "
        "(this entry + v1 abort doc + v2 abort doc count toward >=2 docs/24h gate per vsa-companion playbook)."
    ),
    "next_review": (
        "after signal_chief ships run_avwap_backtest.py OR ops_engineer ships guard #6 or #7 OR "
        "CEO rotates seed OR lab_scientist refreshes RAG with AVWAP topical sources OR "
        "same seed retriggers in 24h (continues JSON-only)"
    ),
}

path = Path("memory/researcher/seed_abort_log.jsonl")
with path.open("a", encoding="utf-8") as f:
    f.write(json.dumps(entry, ensure_ascii=False) + "\n")

print(f"Appended 1 line. Path: {path.resolve()}")
print(f"Entry seed={entry['seed']} trigger_n={entry['trigger_n']} action={entry['action']}")
