# Autonomy Phase 5/6 Status — 2026-07-11

## Decision

- Phase 5 forex runtime is **code-ready but operationally DEFERRED**. It is
  permanently `SIGNAL_ONLY_PAPER`, reads only local `forex_market.duckdb`, and
  has no external-broker, order, exchange, or network path.
- Phase 6 multi-timeframe feature factory is **ready for descriptive discovery**.
  Its output can seed a new hypothesis but cannot authorize shadow or live
  promotion.
- Phase 6 offline agent-output harness is implemented, but the currently
  selected real hypothesis is **QUALITY_GATE_FAIL**. The harness itself does
  not authorize promotion, deployment, orders, or live operation.

## Roadmap closure and V18 interaction

Phase 3–6 code paths are complete for their deliberately bounded scope:
descriptive discovery, paper-only readiness, deterministic evaluation and
fail-closed promotion gates. They are not a mandate to keep searching until a
profitable result appears.

The governed V18 program exercised that contract on four preregistered 15m
cells. All four failed 24–25 primary gates, ranking remained empty and no
true-LOSO, shadow, paper or live job was created. This is the expected autonomy
behavior: an agent may generate and test a hypothesis, but cannot lower gates,
reinterpret a RED result or create execution authority.

The primary reporter's non-finite diagnostic serialization failure also
stopped publication fail-closed. A future-only `null` serializer repair is
tested separately; it does not mutate the sealed run. The technical report is
a source-backed summary of the sealed incident, not a substitute primary
evidence artifact.

No additional scheduler, credential, private exchange reader, daemon or
testnet account was activated by the V18 work.

## Phase 5 — observed local evidence

Real commands:

- `.venv/bin/python scripts/forex_readiness.py --require-ready`
- `.venv/bin/python scripts/forex_paper_signal.py`

Observed decision:

- Readiness: `DEFER` (exit code 2)
- Runner: `DEFER_READINESS` (exit code 3)
- Local runner capability: content-pinned and ready
- Deterministic local paper-broker capability: content-pinned and ready
- Feed capability: unavailable
- Observed spread schema: missing (`spread_bps` required)
- EUR/USD, GBP/USD and USD/JPY 4H last bar open: `2025-12-31T20:00:00Z`
- Observed open-market age at check: `3290h` (allowed `10h`)
- Signal journal mutated by the blocked run: `false`
- Paper-broker DB mutated by the blocked run: `false`
- Active signal/paper-broker DB paths after the blocked run: both absent
- Signals written by the blocked run: `0`
- Order path: `false`
- Network path: `false`
- Deployment evidence: `false`
- Historical EUR/USD 4H research result counts as deployment evidence: `false`
- Safety-lock types are exact: YAML strings and numeric `0/1` cannot impersonate
  boolean paper/live/order policy fields.

Synthetic/local acceptance tests prove next-closed-bar paper entry, observed
spread application, conservative same-bar `SL_FIRST`, idempotent replay, a
separate journal and weekly signal/trade KPIs. Activation still requires a fresh
point-in-time local FX feed with observed spread. The paper-only lock remains
permanent after that dependency is supplied.

The coordinator is registered in the existing scheduler at `8 */4 * * *`.
That is a readiness-gated local paper tick, not a launchd service or external
process bootstrap. While readiness is `DEFER`, it does not create or mutate the
signal or broker databases.

## Phase 6 — full real-data run

Real command: `.venv/bin/python scripts/feature_sweep.py`

- Universe: 18 Binance symbols
- Timeframes: `1h`, `4h`, `1d`
- Produced features: 113 for BTC, 118 for other symbols
- Tests in one global Benjamini-Yekutieli family: `18,963`
- Vol-normalized targets: 3 per timeframe
- Chronological 70/30 OOS-consistent descriptive discoveries: `11`
- `1h`: 11; `4h`: 0; `1d`: 0
- Active v2 queue records after strict reload: 11 accepted, 0 quarantined
- Every record: `promotion_eligible=false`
- OOS scheme: `CHRONOLOGICAL_70_30_CONFIRMATION_NOT_PROMOTION_HOLDOUT`

Auxiliary coverage is explicit:

| Family | Status | Evidence |
|---|---|---|
| Funding | AVAILABLE | 5 causal features; 6,124 max rows/symbol |
| Sentiment | AVAILABLE | 5 causal features; 2,000 observed daily rows |
| Cross-sectional | AVAILABLE | 8 same-close universe features |
| Calendar event-time | AVAILABLE | 4 deterministic UTC features |
| Open interest | UNAVAILABLE_INSUFFICIENT_HISTORY | 62 max rows/symbol (<500) |
| BTC dominance | UNAVAILABLE_INSUFFICIENT_HISTORY | 90 rows (<500) |
| Stablecoin supply | UNAVAILABLE_INSUFFICIENT_HISTORY | empty table |
| Scheduled macro events | UNAVAILABLE_NO_SOURCE_CONFIGURED | no point-in-time local source |

No unavailable family generated synthetic values.

## Phase 6 — offline agent-output evaluation

Real read-only command:
`.venv/bin/python scripts/agent_output_eval.py --no-report --as-of 2026-07-11T00:00:00Z`

- Harness golden contract: PASS
- Selected real artifact: `QUALITY_GATE_FAIL`
- Score: `0.700758` (required `0.90`)
- Pass rate: `0.0` (required `1.0`)
- Numeric citation binding: `0/27`
- Parsed accept gates: `0` (required at least `2`)
- Critical failures: metadata schema, required sections, numeric citation
  binding, accept-gate parseability
- Promotion/deployment/live/order authorization: all `false`

The harness is offline and deterministic. It proves that the evaluator can
reject weak stored outputs; it does **not** prove that current agent output
quality has passed. It is not yet wired as a scheduler or CI gate.

## Remaining external dependency

Phase 5 remains blocked on a fresh local FX feed/adaptor, observed spread, and
ongoing freshness monitoring. The implemented “broker” is a deterministic
local simulator, not an external broker connector. No credential, VPS,
launchd/process bootstrap, network client, exchange integration, or live
execution path was added in this phase. Phase 6 also remains blocked on better
point-in-time auxiliary datasets and on bringing real agent artifacts into the
offline quality contract.

## Verification

- Combined Phase 3–6 regression: `208 passed, 1 skipped`
- TF pool/OOS/promotion/signal-shadow suite: `94 passed`
- Phase 5 focused suite: `43 passed, 1 optional yfinance module skipped`
- Offline agent-output eval suite: `27 passed`
- Ruff, Python compile, YAML/JSON parse and capability-content hashes: PASS
