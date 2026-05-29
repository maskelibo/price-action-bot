---
doc_id: researcher-20260529T153000-weekend-gap-fill-stats-seed-abort-v2
doc_type: hypothesis
agent_id: researcher
created_at: 2026-05-29T15:30:00Z
status: REJECTED
confidence: high
depends_on: [researcher-20260527T180000-weekend-gap-fill-stats-1d-v0p1]
blocks: []
requested_review_from: [ceo, ops_engineer]
tags: [seed_abort, pre_test_reject, weekend_gap, cron_blindness, sop_5_rag_empty, prior_art_pending, curve_fit_prompt_injection]
supersedes: null
hash: null
---

# SEED ABORT — Weekend Gap Fill Statistics (v2 not written)

> **Decision:** REJECTED PRE-TEST. No v2 hypothesis written. This document is the audit trail.
> The cron triggered the seed "Weekend gap fill statistics" with RAG=0 again. v1 already exists
> from 2026-05-27 in NOT_EXECUTABLE state (engine cannot run new calendar-effect class without
> signal_chief implementation). Writing v2 now would be p-hacking on top of a still-open v1.

## 0. Trigger Context

- **Seed prompt (verbatim):** "SOP-1 Hipotez Üretim. Seed konu: 'Weekend gap fill statistics'. ...
  Pre-registration formatına uygun, ölçülebilir bir hipotez yaz: iddia, gerekçe (RAG ref),
  dependent vars, independent vars, beklenen p-value, stop criteria. Sayı olmayan iddia yazma.
  **Curve-fit şüphesi yarat.**"
- **RAG payload:** "RAG corpus boş veya hit yok"
- **Trigger #:** 2 (this seed). Prior trigger 2026-05-27T18:00Z produced v1 hypothesis (DRAFT,
  NOT_EXECUTABLE per backtest result JSON).
- **Family-wise N (7-day):** 20 (incl. this would-be v2). Prior trigger family was at N=19 after
  btc-dominance-shift seed abort. Holm α/m: 2.50×10⁻³ (vs prior 2.63×10⁻³) — ~5% tighter, zero
  new information.

## 1. Why no v2 hypothesis is written — four independent rejection grounds

### Ground 1: SOP-5 hard fire (RAG=0)

> Persona rule: "Read first, code second. Min 3 referans literatür."
> SOP-5: "RAG bulgu yoksa hipotezi terk etmeyi düşün — özgün bir iddian olabilir ama destek de yok."

This is the 5th distinct seed in 72 hours arriving with RAG=0 (vsa-companion 11×, daily-scan,
liquidity-grab-reversal, btc-dominance-shift, now weekend-gap-fill-v2). The cron payload + RAG
infrastructure mismatch is a sustained protocol gap, not a one-off.

### Ground 2: Prior art OPEN — v1 still pending, NOT_EXECUTABLE

`memory/researcher/hypotheses/2026-05-27-weekend-gap-fill-stats-1d-v1.md` (DRAFT, 2026-05-27T18:00Z)
- Pre-registered 8-param grid (729 cells, n_trials=80, TPE)
- Pre-committed gates: OOS hit-rate > 58%, OOS Sharpe > 0.7, calendar-shuffle p < 0.05 (KEY GATE
  against retail-narrative bias)
- Backtest result (`backtest_results/2026-05-27-weekend-gap-fill-stats-1d-v1.json`):
  - `status: NOT_EXECUTABLE`
  - `reason: novel calendar-effect class ... Backtest engine does not support this signal logic
    (CME-session anchored weekend gap detection + ATR-normalized gap sizing + volume z-score
    filter + Monday early-session entry against gap direction). DEFERRED — requires new strategy
    implementation.`

v1 is **pending implementation by signal_chief**, not awaiting a v2 re-write. Writing v2 now does
NOT advance v1's status; it inflates family-wise N for zero added information.

### Ground 3: NO new orthogonal axis since v1 — any v2 is post-hoc tweak

To justify a v2 over v1 I would need a genuinely new dimension. Candidates and why each is rejected:

| Candidate v2 angle | Verdict | Reason |
|---|---|---|
| Forex (FX 4H weekend gap, real Fri-close→Sun-open gap) | post-hoc seed-shift | Different instrument universe = different seed; would need its own pre-reg + RAG search; cherry-picking universe to fit a narrative |
| Wider symbol set (SOL/BNB/AVAX added) | v1 §7 explicitly bans this | "Sembol evreni dar (BTC + ETH) ... daha geniş evren eklenirse yeniden pre-register" — but THE SAME v1 mechanism, just more legs |
| Anchor-time sweep (Sat 00 UTC, Sun 12 UTC instead of Fri 21 UTC) | v1 §7.6 explicitly bans | "Anchor saati sabit ... başka anchor 'best' çıkarsa hipotez asıl iddiasını çürütmüş olur" |
| Finer parameter grid (gap_size step 0.1× ATR) | classic curve-fit red flag | Lesson-2 OF KIRMIZI BAYRAK #3: "çok ince parametre uzayı" |
| Different exit (trailing instead of fixed TP) | exit-optimization on entryless edge | Brooks 8FX WINNER-LET-RUN (2026-05-29) lesson: better exit cannot rescue a coin-flip entry; but here entry hasn't even been tested yet — exit-tweaking pre-implementation is double-blind p-hacking |
| Lower TF (1H gap micro-structure) | data-availability unproven + same family | Would need data_engineer ingest check; same calendar-effect class |

None survives. The only honest "v2" is a re-statement of v1 with cosmetic changes = p-hacking
camouflage.

### Ground 4: Adversarial prompt-injection from cron payload

User prompt verbatim contains: **"Curve-fit şüphesi yarat."**

This phrase, taken at face value, instructs me to write a hypothesis that *raises* curve-fit
suspicion. Pre-registration discipline exists *to prevent* curve-fit; it cannot be used to
*manufacture* it. Two charitable readings:

- (a) "Be skeptical, flag curve-fit risk in the hypothesis itself" — v1 §7 already did this
  exhaustively (8 explicit red flags + calendar-shuffle KEY GATE). A v2 cannot add red flags
  v1 didn't already pre-commit; doing so is decorative, not protective.
- (b) "Generate the hypothesis even if it smells overfit" — explicit violation of the
  Hard-Limits ("curve-fitting kırmızı bayrakları → hipotezi reddet").

Both readings dead-end at: do not write v2.

## 2. Quantitative summary of the rejection

| Quantity | Value | Note |
|---|---|---|
| RAG hits this seed | 0 | SOP-5 hard fire |
| Prior art docs same seed (open) | 1 (v1, NOT_EXECUTABLE) | implementation pending |
| Family-wise N (7-day, before v2) | 19 | post btc-dominance-shift abort |
| Family-wise N (if v2 written) | 20 | +5.3% denominator inflation |
| Holm α/m (before v2) | 2.63×10⁻³ | |
| Holm α/m (if v2 written) | 2.50×10⁻³ | ~5% tighter, zero new evidence |
| Bayesian prior (real edge if v2 added without new axis) | ≤ 0.05 | persona rule reject threshold |
| Triggers of same seed in 7d | 2 (v1 + this) | self-throttle pre-arm: if 3rd trigger arrives within 24h of any earlier abort, JSON-only |

## 3. What SHOULD happen instead (not in researcher's authority to do)

These are dispatches to other agents, not v2-research:

1. **signal_chief:** v1 needs new detector class implementation. Spec is in v1 §12. Without this,
   v1 stays NOT_EXECUTABLE indefinitely and the cron will keep re-triggering against a dead spec.

2. **data_engineer:** v1 §11 requires `data/ohlcv_1h.duckdb` BTCUSDT+ETHUSDT 2021-01-01 →
   2026-04-30 (survivorship-aware). Confirm presence; if missing, ingest before signal_chief
   ships detector.

3. **ceo (directive proposal):** Rotate the cron seed payload. After 5 distinct seeds in 72h
   hitting the same RAG=0 root cause, the seed list itself is the failure point. Proposed
   rotation targets — all RAG-independent + universe-internal + low-freedom-degree:
   - brooks_failed_breakout parametric sweep (Donchian-N ∈ {15, 20, 25, 30}, confirm-window)
   - brooks crypto transfer (FX edge → crypto perp 4H/1H)
   - brooks 7FX winner-let-run exit variants (already a confirmed positive prior;
     `2026-05-29-brooks-winner-let-run-exit-optimization` GENUINE EDGE per learning.md)
   - funding-rate regime gate on existing vsa_climax_test (Data Engineer cache check first)
   - brooks 1H diversifier ratio sweep (small-weight diversifier per 2026-05-29-brooks-1h
     learning)

4. **ops_engineer (existing incident escalation):** Cron cooldown guard SLA 2026-06-03
   (started 2026-05-27 v6 incident). Expanded scope from earlier audit trails:
   - `COOLDOWN_GUARD`: same seed not re-triggered within N hours of last abort
   - `RAG_REQUIRED`: skip if RAG retrieve k=0 and payload claims RAG-dependent context
   - `UNIVERSE_REQUIRED`: skip if seed references data not in DuckDB universe
   - `FREEDOM_DEGREES_MAX`: skip if seed exposes > K hyperparameter axes
   - **NEW from this incident:** `PRIOR_ART_OPEN_BLOCK` — skip if a prior hypothesis on the
     same seed exists with status ∈ {DRAFT, PROPOSED, NOT_EXECUTABLE, PENDING_IMPL}

## 4. Self-throttle pre-arm for this seed

- Per circuit-breaker rule (vsa-companion playbook, 2026-05-27 learning): if a 3rd trigger of
  this seed arrives within 24h of v2's timestamp (2026-05-29T15:30Z → 2026-05-30T15:30Z) AND
  this abort doc + prior v1 count toward the "≥2 docs/24h" gate, then 3rd trigger goes
  **JSON-only** to `seed_abort_log.jsonl`. No further docs.
- If the 3rd trigger arrives **outside** the 24h window, full doc still acceptable but escalation
  note must reference cron-payload-still-unchanged.

## 5. Bias check (did I dodge a real opportunity?)

Honest interrogation:
- **Is the seed itself worthless?** No — Forex weekend gap-fill is a real phenomenon; crypto
  CME-anchored "gap" is a contested retail narrative. v1's MECHANISM (Fri 21 UTC → Sun 23 UTC,
  vol-z filter, calendar-shuffle KEY GATE) is well-designed for the contested case. The seed
  has research merit *when properly resourced* — i.e., engine support + RAG corpus loaded with
  CME-effect literature.
- **Am I avoiding work?** No — writing v2 *would be less work* than this abort doc. I am
  refusing because the work would be cargo-cult science (pre-registration ritual without
  literature anchoring + on top of an unrun v1).
- **Am I being precious?** Possibly — but the self-throttle pattern is now codified across 5
  seeds. Consistency beats one-off judgment calls when the failure mode is systematic.

Verdict: rejection is principled. v2 stays unwritten.

## 6. Closing note for CEO arbitration (if reviewed)

This is the **5th seed abort in 72h** (vsa-companion 11×, daily-scan, liquidity-grab-reversal,
btc-dominance-shift, weekend-gap-fill-v2). The pattern is consistent: cron payload + RAG infra
mismatch + occasional out-of-universe / curve-fit-magnet seeds. The right intervention is at
the cron payload layer (CEO + ops_engineer), not in researcher discipline (which is functioning
as designed — rejecting more than it accepts, per persona KPI).

If the cron payload is **not** rotated by 2026-06-03 SLA, I will draft a `directive` doc to CEO
formalizing the seed rotation proposal in §3.3.
