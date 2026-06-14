"""Append seed-abort v2 record for vsaclimax-volz-threshold-sweep (2026-05-30T02:36Z trigger#2)."""
import json
from pathlib import Path

REC = {
    "ts": "2026-05-30T02:36:00Z",
    "seed": "vsa_climax_test: volume-z threshold parameter sweep",
    "trigger_n": 2,
    "siblings_in_family": 1,
    "abort_docs_24h": 1,
    "abort_jsonl_24h": 0,
    "rag_hits": 6,
    "family_wise_N_v1": 10,
    "holm_alpha_v1": 5.0e-3,
    "family_wise_N_if_v2_written": 20,
    "holm_alpha_if_v2": 2.5e-3,
    "v1_doc_id": "researcher-20260530T103000-vsaclimax-volz-threshold-sweep",
    "v1_status": "PROPOSED",
    "reason": (
        "v2 trigger ~2 min after v1 on identical substrate. v1 substantive pre-reg "
        "(NULL-proving, 10-layer anti-curve-fit guards). 4 rejection grounds: "
        "(1) Family-wise N 10->20 halves Holm alpha 0.005->0.0025; "
        "(2) substrate unchanged 2-min window (code/config/manifest/pool/RAG/learning identical); "
        "(3) prompt injection 'curve-fit suphesi yarat' clause already rejected in v1 sec10; "
        "(4) cron blindness matches self-throttle protocol (cross-strategy-companion v7->v8, "
        "daily-scan v2->v3, btc-dominance v2->v3). v2 abort doc written; "
        "self-throttle ARMED for trigger#3+ -> JSONL-only."
    ),
    "action": "DOC_WRITTEN_v2_abort_audit_trail",
    "decision": "REJECTED_PRE_TEST",
    "escalation_note": (
        "ops_engineer guard #1 SLA 2026-06-03. New guard #8 proposal: cron payload sanitizer "
        "(auto-strip anti-rigor strings). New guard #9 proposal: RAG_FRESHNESS_MAX age 7d. "
        "Alternatives: brooks parametric sweep, brooks 7fx runner-trail, brooks crypto transfer, "
        "brooks 1H diversifier, funding-rate regime gate."
    ),
    "self_throttle_armed": True,
    "next_trigger_action": "JSONL_ONLY_NO_DOC",
}

log_path = Path("memory/researcher/seed_abort_log.jsonl")
with log_path.open("a") as f:
    f.write(json.dumps(REC, ensure_ascii=False) + "\n")
print("appended:", log_path)
