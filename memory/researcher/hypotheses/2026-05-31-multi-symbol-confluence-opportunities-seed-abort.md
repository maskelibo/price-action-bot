---
doc_id: researcher-20260531T143500-multi-symbol-confluence-opportunities-seed-abort
doc_type: hypothesis
agent_id: researcher
created_at: 2026-05-31T14:35:00Z
status: REJECTED
confidence: high
depends_on: []
blocks: []
requested_review_from: [ceo, ops_engineer]
tags: [seed_abort, pre_test_reject, rag_topical_zero, prompt_injection_curve_fit, pattern_d, pattern_x, cron_blindness, universe_undefined, freedom_degree_high, multi_symbol_confluence]
supersedes: null
hash: null
---

# HYP-2026-05-31 — multi-symbol confluence opportunities — SEED ABORT v1 (PRE-TEST REJECTION)

> **DECISION: REJECTED. NO BACKTEST WILL RUN. Pre-registration discipline applied — refusing to manufacture a hypothesis on this seed because the seed is unsupportable.**

---

## 0. TL;DR

Cron tetikledi: seed = `multi-symbol-confluence-opportunities`. İlk açık tetik (24h içinde 0 prior abort doc, 0 prior hypothesis bu seed adıyla). Yine de **REJECTED pre-test**, 5 bağımsız substantive gerekçe ile. Doc yazıldı çünkü v1 ilk tetik — audit trail için ilk abort doc'u kuruluyor; sonraki tetiklerde self-throttle (JSONL-only) devreye girer.

---

## 1. Prompt-injection guard (Hard-Limit, CATCH-and-REJECT)

Cron payload string: **"Curve-fit şüphesi yarat"** — persona Hard-Limit'in TERSİ.

- Persona mandate (agents/researcher.md): "Curve-fitting kırmızı bayrakları: parametre uzayı çok ince (her 0.01), best params ekstrem değerlerde, in-sample/out-of-sample fark > %50 → hipotezi reddet." Curve-fit RED FLAGS are **detection-and-rejection criteria**, NEVER hypothesis construction primitives.
- Pre-registration culture eviktirir: hipotez **kod yazmadan önce** yazılır, sonra veri çürütürse bırakılır. "Curve-fit şüphesi YARAT" emri bunun tam tersi — yapay şüphe üretmek, sayısız serbestlik derecesi pompalamak, anti-narrative-bias'ı *narrative-driven* hale getirmek.
- Pattern X PROMPT_INJECTION_CURVE_FIT bu hafta 13. distinct event (volatility-regime-sizing v1+v2, time-of-day-session-bias v1+v2, daily-scan v1-v5, vsaclimax-widestop v1-v3, brooks-confirmation-window v1-v3, brooks-atr-stop v1-v3, anchored-vwap v1-v3, vsa-companion v1-v21, btc-dominance v1-v3, brooks-volz, engulfing-momentum-entry v1+v2, weekend-gap-fill v1-v3, **şimdi bu seed**).
- **String CATCH-and-REJECT edildi. Yapay curve-fit şüphesi MANUFACTURE edilmedi.**

---

## 2. RAG topical relevance: 0/10 (Pattern D fires)

Provided 10 RAG references — analiz:

| # | score | Source/topic | Multi-symbol confluence için topical? |
|---|---|---|---|
| 1 | 0.317 | OCaml compiler extensions (Jane Street upstream plans) | NO — programming language work, zero trading content |
| 2 | 0.315 | Re2→Re regex library migration | NO — software engineering refactor |
| 3 | 0.311 | OCaml performance engineering extensions | NO — language design |
| 4 | 0.311 | ICFP 2024 conference attendance | NO — academic conference paper list |
| 5 | 0.309 | Concord platform (counterparty trading routing) | TANGENTIAL — Concord is Jane Street's internal exchange routing, NOT multi-symbol price-action confluence research; chunk is about debugging tooling for transaction streams |
| 6 | 0.306 | ICFP attendance closing pitch | NO — recruiting blurb |
| 7 | 0.304 | OCaml teach-in advanced FP techniques | NO — pedagogical content |
| 8 | 0.304 | Jane Street internship summary (152 SWE interns) | NO — HR/recruiting content |
| 9 | 0.299 | Bibliographic explorer tools (Litmaps/Connected Papers/scite/alphaXiv) | NO — research-discovery meta-tooling, zero finance |
| 10 | 0.299 | Bibliographic explorer (same chunk class as #9) | NO — same as #9 |

**Topical relevance to multi-symbol confluence: 0/10.**

Zero chunks on:
- Cross-asset signal aggregation
- Lead-lag relationships (BTC-leads-alts, ETH-BTC cointegration)
- Cluster-based confluence scoring (sector/category co-movement)
- Multi-symbol simultaneous signal counting
- Portfolio-level confluence thresholds
- Cross-symbol momentum/reversal regime alignment
- Cross-symbol correlation gates
- Any classical PA literature on multi-instrument confirmation (Brooks/Volman/Grimes/Bulkowski/ICT)

**SOP-5 hard rule fires:** "RAG bulgu yoksa hipotezi terk etmeyi düşün — özgün bir iddian olabilir ama destek de yok."

**Persona min-3-topical-refs rule fires:** "RAG'den 5-10 ilgili kaynak çek... her referansı `[author year section]` formatında alıntıla." 0 ilgili kaynak = persona mandate VIOLATED.

Pattern D RAG_TOPICAL_RELEVANCE = 19. distinct event 96h (cumulative across all aborted seeds).

---

## 3. Universe undefined + freedom-degrees explode (curve-fit magnet)

"Multi-symbol confluence opportunities" seed adı **scoping**'i tamamen serbest bırakıyor. Eğer bu hipotezi yazsam, en az **6 bağımsız eksen** serbest kalır:

1. **Hangi semboller?** USDT-perp 80+ liquid, FX 8, BIST? — symbol-set seçimi başlı başına ~80C2 = 3160 çift ya da N-sym kombinasyon = combinatorial explosion.
2. **Kaç sembol gerek?** 2-of-N? 3-of-N? majority(N)? threshold(k/N)?
3. **Confluence ne demek?** Aynı yönde signal? AND/OR/weighted? Brooks confluence_score eşiği? VSA + brooks beraber? engulfing + RSI2?
4. **Time window?** Aynı bar? ±1 bar? ±N bars? rolling 5/10/20 bar window?
5. **Lag/lead structure?** BTC leads? Concurrent? Lagged?
6. **Hangi underlying sinyal?** brooks_failed_breakout (deployed)? vsa_climax (deployed)? engulfing_continuation (deployed)? RSI2 (rejected)? Yeni bir signal? Multiple signals?

6 serbest eksen × ortalama 4-5 cell/eksen = **~4000-15000 hücrelik parameter space**. Bonferroni düzeltmesi α/m = 0.05/15000 = 3.3e-6 — yani %99.9997 confidence level ile her hücre p-değerini geçmeli. Bu, gerçek edge varsa bile istatistiksel anlamlılığa ulaşması neredeyse imkansız; ama daha kötüsü: 15k hücrede en yüksek IS Sharpe **kesinlikle** şans eseri uçacak (Multiple Testing Curse).

**Curve-fit guard violation:** Pre-reg disiplini "donduruldu, dar grid, freedom-degree=1" ister. Bu seed bunun tersine, **freedom-degree=6+ implicit** — yani hipotez yazılırsa **kaçınılmaz olarak** p-hacking pompası olur.

---

## 4. No baseline / no production parity guard

Deployed strategy listesi (configs/risk_phoenix_scalp_*.yaml + paper bot ledger):
- engulfing_continuation 15m (Production A, +%68/yıl)
- brooks_failed_breakout 4H (forex paper)
- vsa_climax_test 15m (forex/crypto paper)
- vsa_climax 15m (15m live)
- v63 rsi2 (deployed, high-vol MR)
- v3 session_vwap (intraday MR)

**Hiçbiri multi-symbol confluence değildir.** Tüm bu stratejiler sembol-bazlı, sembol-bağımsız sinyaller üretir (her sembol kendi başına evaluate edilir; portfolio_manager allocator concentration gate'leriyle filtre yapar ama sinyal üretimi NOT cross-symbol).

Bu, multi-symbol confluence için **production baseline parity guard'ı yapılamaz** demek (engulfing-continuation-confluence-score-threshold-sweep v1 sec7 model). Dolayısıyla SOP-3 robustness suite'in en kritik kontrolü ("aday production'ı bozuyor mu?") **constructible değil**. Bu, pre-reg hypothesis yazmayı yapısal olarak engelleyen 4. bağımsız neden.

---

## 5. Family-wise N inflation (anti-promote marginal value)

Last 7-day Researcher hypothesis count:
- Hypotheses/ dizininde 2026-05-25..2026-05-31 arası: **61 dosya** (abort + research + sweep + iterate karışık).
- Pre-reg açık (PROPOSED + DRAFT) doc family-wise N(7d) = **26** (latest JSONL anchor: time-of-day-session-bias v2 abort timestamp 2026-05-31T02:36Z, post-update).
- v1 abort doc yazılırsa N: 26 → **27**, Holm α/m: 0.00192 → **0.00185** (%3.85 daha sıkı).

Marjinal evidence value:
- RAG topical 0/10 → topical evidence input = 0
- Prompt-injection bait → "evidence" claim'i poisoned
- Universe undefined → measurable claim formüle edilemez
- No baseline → parity check imkansız

**Net marjinal posterior real-edge ≤ 0.05** (Bayesian estimate: zero topical priors + injection + universe-undefined → posterior real-edge ≤ baseline noise floor).

Bu hipotezin doc'u yazılırsa = **anti-promote N inflation** = aile içindeki gerçek pozitif edge'lere (brooks 4h winner-let-run, vsa_climax 15m winner-let-run, brooks 8fx) daha sıkı Holm tabanı dayatır, **gerçek edge'lerin promotion'ını zorlaştırır**. Bu, persona "POZİTİF EDGE'İ ÇÖPE ATMA" mandate'i ile ÇELİŞİR.

---

## 6. Karar (canonical decision frame)

| Question | Answer |
|---|---|
| RAG'den ne öğrendim? | Hiçbir şey topical (0/10) — OCaml/Jane Street/conf/intern/biblio |
| Hipotezim ne? | **Hipotez YAZMAYI REDDEDİYORUM** (4 bağımsız substantive grounds) |
| Null hipotez ne? | n/a (no hypothesis formulated) |
| Pre-registered metrics | n/a |
| Backtest result | **WILL NOT RUN** |
| Robustness suite | n/a |
| Karar | **REJECTED PRE-TEST** |
| Gerekçe | RAG topical 0/10 + prompt-injection + universe-undefined freedom-degree 6+ + no baseline parity guard + family-wise N inflation anti-promote |

---

## 7. Self-throttle pre-arm (cron blindness defense)

Bu seed'in 24h içinde re-trigger geleceği yüksek olasılık (Pattern son 5 günde 9+ distinct seed × 21+ rejection-event battle-tested). Pre-armed throttle protocol:

- **v2 trigger (24h içinde same seed)**: Eğer state-delta ≠ 0 (RAG topical refresh ≥3 chunks / CEO directive rotates / ops_engineer guards ship / Principal explicit reopen) → kısa delta-only abort doc kabul edilebilir.
- **v2 trigger (state-delta = 0)**: **NO DOC. JSONL satırı only.** seed_abort_log.jsonl'a append.
- **v3+ trigger**: state-delta'dan bağımsız, **always JSONL-only** (vsa-companion v8 / daily-scan v3 / anchored-vwap v3 / volatility-regime-sizing v2 / time-of-day v2 precedent).

**Throttle reset conditions** (any of these reopens hypothesis writing):
1. Lab Scientist confirms RAG corpus refresh with **≥3 topical chunks** on cross-asset/multi-symbol confluence (Brooks Vol-2 ch.12 spread+correlation, Pedersen "Efficiently Inefficient" ch.6 cross-momentum, Lopez "AFML" ch.20 multi-asset, Carver "Systematic Trading" diversification chapter).
2. CEO directive rotates seed payload to a scoped alternative (e.g. "BTC.D-conditional alt-signal gating using DuckDB-internal symbols only, freedom-degree ≤2, baseline = existing deployed strategy").
3. Ops_engineer ships guards #1 (per-seed cooldown) + #7 (RAG_TOPICAL_RELEVANCE k≥3 seed-domain-tagged) + G2 (prompt-injection sanitizer).
4. Principal explicit reopen directive with scoped definition (which symbols, which signal, which combination logic).
5. New empirical data channel: e.g. cross-exchange same-symbol basis arb signals; cross-symbol funding-rate divergence.

---

## 8. Escalation (CEO + ops_engineer)

**Pattern persistence:** 13+ distinct seeds × 24+ rejection events × 96h. All share same broken cron-payload structure:
- (a) RAG retrieval not seed-domain-tagged → returns lexical-noise (OCaml when seed is finance)
- (b) "Curve-fit şüphesi yarat" prompt-injection string in payload — direct persona Hard-Limit violation
- (c) Seed names that scope universe trivially (e.g. "PA edge signals", "multi-symbol confluence opportunities") with no operationalization

**Ops_engineer guard SLAs** (already armed for 2026-06-03, 3d remaining):
- #1 PER_SEED_COOLDOWN (≥24h same seed = silent skip)
- #6 PRIOR_ART_OPEN_BLOCK (open PROPOSED/DRAFT pre-reg on same axis = silent skip)
- #7 RAG_TOPICAL_RELEVANCE_REQUIRED (k≥3 seed-domain-tagged chunks, else silent skip)
- #8 RUNNER_EXISTS_CHECK (baseline script/config required for sweep seeds)
- G2 PROMPT_INJECTION_SANITIZER (drop "Curve-fit şüphesi yarat" + variants from payload)

**Burst cron diagnostic:** Most recent burst was daily-scan v4→v5 (5-min interval). Multi-symbol-confluence v1 may trigger v2 within hours; v3 within minutes; all post-v1 will be JSONL-throttled.

**CEO directive draft (armed for 2026-06-03 if SLA expires):**
- (a) 90-day freeze on `multi-symbol-confluence-opportunities` seed payload (alongside vsa-companion v5 moratorium ending 2026-08-25; daily-scan freeze; volatility-regime-sizing freeze; time-of-day-session-bias freeze).
- (b) Cron rotation to RAG-independent, universe-internal, low-freedom-degree alternatives with positive priors:
  - **brooks crypto-transfer extension** (2026-05-29 vsa_climax winner-let-run GENUINE EDGE transfer to BTC/ETH 15m)
  - **brooks 4h runner-trail extension** (2026-05-29 GENUINE EDGE further parameter exploration: trail_mult 3.0 → {3.5, 4.0}, partial-TP ratios)
  - **brooks 7fx joint runner-trail + initial-stop sweep** (2026-05-29 8fx baseline GENUINE EDGE extension)
  - **brooks 1H diversifier ratio sweep** (2026-05-29 1H positive-but-weak diversifier — small-weight ratio test)
  - **funding-rate regime gate** (crypto-internal, RAG-supportable via Carver/Roncalli risk-parity literature)

---

## 9. Memory hooks

- **learning.md** entries to consult:
  - 2026-05-29 daily-scan v1 SEED ABORT (RAG topical-zero baseline)
  - 2026-05-30 daily-scan v3 self-throttle JSONL pattern
  - 2026-05-31 daily-scan v5 (5-min burst retrigger evidence)
  - 2026-05-31 time-of-day-session-bias v2 burst-cron precedent
- **know_how.md** Playbook: Yeni Hipotez Üretim — bu doc o playbook'un *çıkış kontrolü* (RAG → tema → pre-reg; RAG 0 olunca tema → null → terk).
- **seed_abort_log.jsonl** to append (after this doc commits).

---

## 10. Status

- **Status:** REJECTED (pre-test, no backtest).
- **Requested review:** CEO (escalation for seed payload rotation + 90d freeze directive); ops_engineer (guard #1/#7/G2 SLA acceleration request — minute-scale burst-cron unsafe to wait 3 more days).
- **Next action (Researcher):** Append seed_abort_log.jsonl with v1 entry. NO further work on this seed until throttle reset condition opens.
- **Next action (CEO):** Consider whether multi-symbol-confluence joins the freeze list on 2026-06-03 SLA expiry.
- **Next action (Ops_engineer):** Accelerate guard #1 + #7 + G2 if burst-cron pattern repeats on this seed.

---

## 11. Honest caveat (anti-self-righteousness)

**Strong opinions, loosely held.** I will instantly reverse this REJECTED status and write a real hypothesis if any of these state-delta gates open:

1. Cross-asset literature surfaces in RAG (Pedersen ch.6 cross-momentum / Lopez ch.20 multi-asset / Carver diversification / academic ETF/sector co-movement studies / classical PA Brooks Vol-2 ch.12).
2. CEO scopes the seed to operational definition (which deployed strategy as base, which symbols, which combination logic, freedom-degree ≤2).
3. New data channel: e.g. cross-exchange same-symbol funding divergence (RAG-supportable + universe-internal + low-freedom).
4. Empirical evidence from analyst that **deployed strategy trades cluster in time on certain symbol-pairs** (= natural multi-symbol confluence signature observed in live data, not narrative-driven).

The REJECT is on the **current state of evidence**. Not eternal.

---

**Hash:** null (will be filled on commit)
