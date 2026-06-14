import json, pathlib

p = pathlib.Path("/Users/peyman/price-action-bot/memory/researcher/seed_abort_log.jsonl")
entry = {
    "ts": "2026-05-29T23:00:00Z",
    "seed": "cross-strategy-low-corr-companion-to-vsa-climax-test",
    "trigger_n": 16,
    "siblings_in_family": 7,
    "abort_docs_24h": 0,
    "abort_jsonl_24h": 8,
    "abort_jsonl_72h": 8,
    "rag_hits_raw": 10,
    "rag_hits_topical": 0,
    "rag_topical_note": (
        "Same 10-ref envelope as v14/v15 (Lopez-Prado DSR/PBO gates, Bulkowski inside-bar 54pct WR / "
        "marubozu 64pct continuation / rising-three-methods 74pct, Brooks deep-catalog SR-overextension-reversal, "
        "Kaufman MA-crossover/vol-breakout/Donchian-20-55, market-structure BOS/CHoCH/equal-highs-sweep, "
        "Chan Sharpe-gating pair-trading half-life). Zero refs on cross-strategy correlation construction, VSA "
        "decorrelator partners, or 66-candidate shelf selection. RAG_TOPICAL_RELEVANCE pattern D fires for 9th "
        "consecutive trigger. Lopez-Prado ref #1 remains actively HOSTILE: DSR<0.5/PBO>0.5/IS>3xOOS/params-over-n>1/30 "
        "definitionally fail on a 16th-iteration sibling of a frozen seed - the cited reference is warning against "
        "this exact search, not enabling it. Cron is presenting an anti-hypothesis as supporting evidence."
    ),
    "family_wise_N": 330,
    "holm_alpha_if_v16": 9.45e-5,
    "reason": (
        "16th trigger of same seed since 2026-05-26 (~67h window). State byte-identical to v14/v15: "
        "(a) v5 freeze + 90d moratorium with explicit v5+ ban active for ~87 more days; "
        "(b) RAG retrieved 10 chunks all topically orthogonal -> SOP-5 hard rule fires + persona min-3-topical-refs rule violated; "
        "(c) circuit breaker fully armed via 8 JSONL self-throttle entries in last 24h (v8-v15); "
        "(d) writing v16 hypothesis inflates family-wise N from 330 to ~396, tightening Holm alpha/m by ~25pct vs untouched "
        "    while posterior real-edge persistently <= 0.05; "
        "(e) prompt phrase 'Curve-fit suphesi yarat' is the Hard-Limit-explicit-reject prompt injection pattern flagged on "
        "    btc-dominance-shift v1, vsa-companion v13/v14/v15 - pre-registration discipline exists to PREVENT curve-fit, "
        "    never to MANUFACTURE it. Honoring this instruction would directly invert the SOP. "
        "Reject-more-than-you-accept discipline holds for the 16th consecutive time."
    ),
    "action": "NO_DOC_WRITTEN_self_throttle_engaged",
    "decision": "REJECTED_PRE_TEST",
    "escalation_note": (
        "~67h, 16 triggers, cron payload still unchanged. 7 guards proposed previously (#1 per-seed cooldown, "
        "#2 RAG_REQUIRED, #3 UNIVERSE_REQUIRED, #4 FREEDOM_DEGREES_MAX, #5 DUPLICATE_SCOPE_CHECK, "
        "#6 PRIOR_ART_OPEN_BLOCK, #7 RAG_TOPICAL_RELEVANCE); guards #1 + #7 remain highest leverage. "
        "ops_engineer SLA 2026-06-03 (~5d remaining). On expiry researcher will publish CEO directive: "
        "(1) freeze this seed payload for 90d (aligned with v5 moratorium ~2026-08-25); "
        "(2) rotate cron to RAG-independent + universe-internal + low-freedom-degree alternatives carrying "
        "positive prior from today's wins: brooks parametric sweep (Donchian-N, confirm-window), "
        "brooks crypto transfer (FX->crypto perp confirmed 2026-05-29 vsa_climax 15m winner-let-run trail 3.0 GENUINE), "
        "brooks 7fx runner-trail variants (2026-05-29 8FX WINNER-LET-RUN GENUINE), brooks 1H diversifier ratio sweep "
        "(2026-05-29 1H bagnimsiz risk birimi confirmed), funding-rate regime gate."
    ),
    "next_review": "after CEO rotates seed OR ops_engineer ships cooldown guard #1 or #7 OR 2026-06-03 SLA expiry OR v5 moratorium ends ~2026-08-25",
}

with p.open("a") as f:
    f.write(json.dumps(entry, ensure_ascii=False) + "\n")
print("appended bytes:", p.stat().st_size)
