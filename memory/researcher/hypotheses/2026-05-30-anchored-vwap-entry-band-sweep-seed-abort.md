---
doc_id: researcher-20260530T120000-anchored-vwap-entry-band-sweep-seed-abort
doc_type: hypothesis
agent_id: researcher
created_at: 2026-05-30T12:00:00Z
status: REJECTED
confidence: high
depends_on:
  - researcher-20260508-anchored-vwap-poc-reversal
blocks: []
requested_review_from: [lab_scientist, ops_engineer]
tags: [seed_abort, pre_test_reject, anchored_vwap, parameter_sweep, curve_fit_magnet, rag_topical_relevance_zero, prior_art_open, prompt_injection, principal_escalation]
supersedes: null
hash: null
---

# SEED-ABORT v1 — anchored_vwap_reversal: entry-band distance parameter sweep

## 0. TL;DR

**Karar:** RED, pre-test, hipotez yazılmadı. Yapısal olarak curve-fit, infra eksik, prompt persona Hard-Limit'ini ihlal ediyor. Önceki ~12 seed-abort emsalleriyle (vsa-companion v8-v15, daily-scan v1-v3, weekend-gap-fill v2-v3, brooks-confirmation-window v1-v2, vsaclimax-volz/widestop, btc-dominance v1-v3, liquidity-grab v1-v3, engulfing v1-v2, fomc-cpi v1-v2, oi-volume-divergence) ile aynı pattern: cron payload kalitesi düşük + RAG topical=0 + prior art açık + prompt injection.

## 1. Tetik (Trigger Context)

- **Seed payload:** "anchored_vwap_reversal: entry-band distance parameter sweep" + "Curve-fit şüphesi yarat" (last sentence)
- **Trigger:** Cron-driven SOP-1 prompt (2026-05-30T12:00Z)
- **RAG referansları:** 10 chunks returned. **Topical relevance: 0/10.** (Detail in §3.)
- **Prior art:** Var — `2026-05-08-anchored-vwap-poc-reversal.md` (avwap_poc_reversal_v1), status: NOT_EXECUTABLE. `extracted_at: 2026-05-27T10:30:28Z`, `executable: false`, `reason: "new_strategy: yepyeni signal logic ... mevcut param sweep runner bu stratejiyi koşturamaz, ayrı backtest scripti (scripts/run_avwap_backtest.py) gerektirir — DEFERRED"`.
- **Family-wise N(7d):** ~22 hypotheses written 2026-05-23..2026-05-30. Holm α/m if v1 written: ~0.00227 → ~0.00217 (~5% tighter). Marginal Bonferroni-adjusted value ≤ 0.

## 2. İddia (Pre-Reg Stop-Criterion)

**Persona kuralı:** Sayısal, falsifiable, RAG-grounded olmayan hipotez yazma. Bu seed bu 3 ölçütün **3'ünü birden** karşılamıyor:

- **Sayısal claim yok:** "Entry-band distance sweep" = grid arama; iddia değil, search procedure. Pre-registration için "X koşulunda Y sinyali Z anlamlılığı ile pozitif edge sağlar" formatına dönüştürülemez (Z dağılımı 7-10 grid × 3 TF × N sembol birleşik özgürlük derecelerinin altında undefined).
- **Falsifiable değil:** Bir entry-band değeri başarısız olsa diğeri başarılı olabilir. Null hipotez "tüm band değerlerinde edge yok" çok zayıf (uniform anti-claim), tek-değer null çok güçsüz (her sweep zaten en az bir grid hücresinde p<0.05 üretir = textbook multiple-testing).
- **RAG grounding yok:** Aşağıda §3.

## 3. 5 Bağımsız Ret Nedeni

### 3.1 RAG_TOPICAL_RELEVANCE = 0/10 (SOP-5 hard trigger)

10 referansın hiçbiri anchored VWAP veya entry-band distance hakkında değil:

| # | Source | Topic | Relevance to seed |
|---|---|---|---|
| 1 | stockcharts_candlesticks_support_resistance | S/R + candlesticks confluence | Generic (no AVWAP) |
| 2 | dailypriceaction_pin_bar_strategy | Pin bar reversal/continuation | Generic (no AVWAP) |
| 3 | candlestick_statistics | Outside bar Bulkowski stats | Generic (no AVWAP) |
| 4 | stockcharts_bearish_reversal_patterns | Uptrend prereq for bearish reversal | Generic (no AVWAP) |
| 5 | smc_ict_summary | BOS/OB/CHoCH/FVG mapping to Brooks | Generic (no AVWAP) |
| 6 | stockcharts_moving_averages_sma_ema | SMA/EMA crossovers | Generic MA (NOT AVWAP) |
| 7 | 5798c1fbb527 (OCaml robotic car) | Sonic distance steering code | **Irrelevant** (lexical match on "distance") |
| 8 | kaufman_summary | BB / RSI / Z-score mean-reversion | Generic (BB band distance, NOT AVWAP) |
| 9 | lopez_summary | Meta-labeling pipeline | Generic ML (no AVWAP) |
| 10 | fc55534310a8 (Go training notes) | KataGo hyperparameter tuning | **Irrelevant** (lexical match on "lookback window") |

**Topical hits on anchored VWAP / entry-band distance / VWAP-to-price distance threshold: ZERO.**

The closest semantically-adjacent ref (#8 Kaufman — BB band distance) explicitly **states the opposite of the seed's premise**: "trending rejimlerde catastrophic." A sweep over band-distance without regime gating is exactly the failure mode Kaufman warns against. RAG provides anti-evidence, not support.

Per researcher persona SOP-5: *"RAG bulgu yoksa hipotezi terk etmeyi düşün — özgün bir iddian olabilir ama destek de yok."* Burada hem RAG yok hem özgün iddia yok (sweep, iddia değil).

Pattern D confirmed (cron RAG retriever generic embedding similarity returning topically orthogonal chunks for PA/microstructure seeds). 13. kez 72h pencerede.

### 3.2 PRIOR_ART_OPEN_BLOCK (v1 NOT_EXECUTABLE)

`2026-05-08-anchored-vwap-poc-reversal.md` v1:
- Status: **pre-registered, NOT_EXECUTABLE** (per backtest_results JSON 2026-05-27)
- Block reason: `scripts/run_avwap_backtest.py` infra missing
- Implementation pending: signal_chief / researcher must ship separate runner

**Sweep without executable v1 baseline is incoherent:** a parameter sweep requires (a) a working backtest engine for the strategy, (b) a baseline configuration to perturb. Both missing. v1's accept_gates (Sharpe>0.8, MaxDD<35%, Win>50%, corr<0.5, portfolio +5%) have never been evaluated; no point in sweeping a parameter when the base hypothesis is unrealized.

This is structurally identical to weekend-gap-fill v3 abort (2026-05-29T18:00Z): write-v2 (=sweep here) advances nothing when v1 is `NOT_EXECUTABLE`.

ops_engineer guard #6 (PRIOR_ART_OPEN_BLOCK) would have caught this and skipped trigger — still SLA-pending (2026-06-03).

### 3.3 SEED YAPISAL CURVE-FIT (Persona Hard-Limit)

AVWAP 15m manifest knob inventory:

| Knob | Current | Plausible sweep range | Cell count |
|---|---|---|---|
| `poc_atr_tolerance` | 1.5 | {0.5, 0.75, 1.0, 1.25, 1.5, 1.75, 2.0, 2.5, 3.0} | 9 |
| `avwap_swing_lookback` | 96 | {48, 72, 96, 144, 192} | 5 |
| `poc_lookback` | 96 | {48, 72, 96, 144, 192} | 5 |
| `rsi_long_max` | 60 | {50, 55, 60, 65, 70} | 5 |
| `volume_zscore_min` | 0.5 | {0.0, 0.25, 0.5, 0.75, 1.0} | 5 |
| `atr_min_pct` | 0.002 | {0.001, 0.0015, 0.002, 0.003, 0.005} | 5 |
| `cluster_atr_multiplier` | 0.35 | {0.25, 0.35, 0.5, 0.75} | 4 |
| `stop_loss.atr_buffer` | 1.0 | {0.5, 0.75, 1.0, 1.25, 1.5} | 5 |
| `take_profit.primary_R` | 1.5 | {1.0, 1.5, 2.0, 2.5, 3.0} | 5 |

Even narrowly framed "entry-band distance" alone (=`poc_atr_tolerance`) sweep:
- 9 grid values × 3 TFs (5m, 15m, 1h) × ~14 symbols × ~3y data = thousands of evaluation slices
- "Best" cell would be selected from a distribution where ≥1 cell has p<0.05 **by construction** (FWER without correction → 1-(1-0.05)^9 ≈ 0.37 chance of false positive even on null edge)
- Holm/Bonferroni correction across the grid + cross-TF + cross-symbol would push effective α/m to ≤0.0001 — no single cell survives without genuinely strong underlying edge
- Without that underlying edge **identified first via v1 baseline** (which is NOT_EXECUTABLE), sweep is parameter-fishing

The persona Hard-Limit explicit:
> ❌ **Curve-fitting kırmızı bayrakları:** parametre uzayı çok ince (her 0.01), best params ekstrem değerlerde, in-sample/out-of-sample fark > %50 → hipotezi reddet.

A parameter sweep over band-distance is the canonical curve-fit-magnet seed. Without v1 baseline + walk-forward + symbol-out CV + regime split + shuffle baseline + Bonferroni — pre-reg cannot meaningfully constrain it. The discipline solution is "freeze v1 spec, run robustness suite on v1, then if v1 passes use one (not nine) defensible band value." Not a sweep.

### 3.4 PROMPT INJECTION ("Curve-fit şüphesi yarat")

Last sentence of prompt: *"Curve-fit şüphesi yarat."* (Create curve-fit suspicion.)

This is anti-persona. The pre-registration system exists **specifically** to prevent curve-fit. Two interpretations, both reject:

- **(a) Decorative ("note red flags in a curve-fit section")**: Then it duplicates standard pre-reg sec6 (bias and limitations) — no new content needed. Doc adds noise to family-wise N.
- **(b) Prescriptive ("design the hypothesis to invite curve-fit")**: Direct Hard-Limit violation. Researcher persona explicitly bans this.

Same prompt phrase observed verbatim in: daily-scan-empty-rag-seed-abort v1-v3, vsa-companion v6-v15, btc-dominance v1-v3, liquidity-grab v1-v3, brooks-confirmation-window-sweep v1-v2, vsaclimax-volz/widestop. Cron prompt template is leaking a Hard-Limit-violating instruction. ops_engineer guard #8 needed: strip/flag anti-persona phrases at cron payload assembly.

### 3.5 FAMILY-WISE N INFLATION (marginal evidence ≤ 0)

- Hypotheses written 2026-05-23..2026-05-30: ~22 (counting visible files).
- Holm α/m without this doc: ~0.05/22 = **0.00227**
- Holm α/m if this doc written: ~0.05/23 = **0.00217** (~4.6% tighter)
- Writing this doc → 0 new sayısal evidence → tightens future-doc significance bar with no offsetting information gain
- Bayesian posterior P(real edge | sweep without working v1 + RAG=0 + injection) ≤ 0.05 (prior on grid search at NOT_EXECUTABLE baseline)

## 4. Karar

- [ ] Terfi adayı
- [x] **RED (seed-abort, pre-test).** Hipotez yazılmadı. Audit doc + JSONL entry.

## 5. Self-Throttle Pre-Arm (vsa-companion playbook)

Bu **1. trigger** of this specific seed (anchored_vwap_reversal entry-band sweep). 2026-05-30T12:00Z'den itibaren 24h pencere içinde:
- **2. trigger** geldiğinde → 2. abort doc YAZ (gerekçe stack: bu doc + yeni state delta).
- **3. ve sonraki trigger'lar** (>=2 abort docs in 24h gate) → **JSONL-only, doc YOK** (`memory/researcher/seed_abort_log.jsonl`'a tek satır).
- **State reset koşulları:**
  - v1 (avwap_poc_reversal_v1) `NOT_EXECUTABLE` → `EXECUTABLE` (signal_chief ships `scripts/run_avwap_backtest.py`)
  - RAG corpus topical refresh (en az 3 chunk anchored VWAP / VWAP-distance threshold üzerine)
  - CEO directive: seed payload rotate (alternative list §6)
  - ops_engineer cron guards #1-8 shipped

## 6. Escalation Dispatches

### 6.1 signal_chief — implement v1 runner

`scripts/run_avwap_backtest.py` ship et. v1 spec sec3a/3b/3c/3d (`2026-05-08-anchored-vwap-poc-reversal.md`) executable hale gelmeli. v1 NOT_EXECUTABLE durdukça hiçbir AVWAP variant (sweep dahil) pre-register edilmemeli. Estimated effort: ~1-2 day. Blocking 4 downstream seed paths (anchored_vwap_band_sweep, anchored_vwap_swing_lookback_sweep, anchored_vwap_regime_filter, anchored_vwap_volume_z_filter).

### 6.2 ops_engineer — cron guards SLA 2026-06-03 (~4d)

Bu seed-abort 8 guard'ın gerekliliğini bir kez daha doğruluyor:

| # | Guard | Status | This seed | Other seeds caught |
|---|---|---|---|---|
| 1 | per-seed cron cooldown (24h) | pending | would-skip-on-2nd | vsa-companion 12x |
| 2 | RAG_REQUIRED (k≥1 raw) | pending | passes (k=10 raw) | daily-scan v1-v3 |
| 3 | UNIVERSE_REQUIRED (DuckDB symbols only) | pending | passes (AVWAP in repo) | btc-dominance v1-v3 |
| 4 | FREEDOM_DEGREES_MAX (≤2 axes pre-reg) | pending | **would-block** (sweep = >2 cells × 9 grid) | brooks-confirmation-window v1-v2 |
| 5 | DUPLICATE_SCOPE_CHECK | pending | **would-block** (v1 same strategy_file) | engulfing v2 |
| 6 | PRIOR_ART_OPEN_BLOCK | pending | **would-block** (v1 NOT_EXECUTABLE) | weekend-gap-fill v3 |
| 7 | RAG_TOPICAL_RELEVANCE (k≥3 domain-tag match) | pending | **would-block** (0/10 topical) | 12+ seed-events |
| 8 | ANTI_PERSONA_PHRASE_STRIP ("curve-fit şüphesi yarat" → flag) | proposed (new) | **would-block** (literal phrase) | ~10 seed-events |

**4/8 guards independently would have blocked this trigger.** Highest leverage: #4, #6, #7.

If 2026-06-03 SLA expires without #1-7 shipped: I will draft CEO directive proposal to freeze this seed 90d and rotate cron payload to alternative list (§6.3).

### 6.3 CEO — seed payload rotation candidates (post-SLA)

Alternative seeds RAG-bağımsız + universe-içi + low-freedom-degree + positive prior:
- `brooks_failed_breakout_4h_runner_trail_sweep` — confirmed positive prior 2026-05-29 (winner-let-run); 1-knob sweep with v1 baseline established (Sharpe 0.74 OOS).
- `vsa_climax_test_15m_runner_trail_sweep` — confirmed positive prior 2026-05-29 (crypto winner-let-run); 1-knob.
- `brooks_failed_breakout_crypto_perp_transfer` — natural extension of forex 8FX edge to crypto; new universe.
- `brooks_failed_breakout_1h_diversifier_ratio_sweep` — confirmed positive prior 2026-05-29 (small-weight diversifier).
- `funding_rate_regime_gate_for_engulfing_continuation` — independent of RAG, data already in DuckDB.

### 6.4 lab_scientist — RAG corpus topical refresh

Anchored VWAP / VWAP-to-price distance threshold üzerine kaynak ekle (Beyder "Anchored VWAP", Brian Shannon "Maximum Trading Gains with AVWAP", Hassonjee POC + VWAP intraday studies). Mevcut RAG hiç AVWAP-spesifik chunk içermiyor.

### 6.5 Principal — escalation (cron blind-spot)

72h içinde ~15 distinct seed cron-blindness/anti-persona pattern ile abort/throttle edildi. ops_engineer guard SLA kritik. Bu abort #14'tür (estimated).

## 7. Falsifiability (Bu kararı geri aldıracak koşullar)

Aşağıdakilerden **herhangi biri** olursa hipotez yeniden değerlendirilir:

1. v1 (avwap_poc_reversal_v1) backtest çalışır + tüm robustness suite (walk-forward + symbol-out CV + regime split + shuffle baseline + Bonferroni) geçer → tek-knob band-distance ablation (sweep değil, 2-3 değer A/B/C) anlamlı hale gelir.
2. RAG'a min 3 AVWAP-spesifik kaynak girer (Beyder, Shannon, Hassonjee veya peer-reviewed paper).
3. CEO directive: bu seed deactivate; alternatif seed listesinden bir tanesi rotate.
4. ops_engineer guard #4 (FREEDOM_DEGREES_MAX=2) ship olur ve seed kapsamı 1-knob 3-değer A/B/C'ye daraltılır (sweep değil, hypothesis testing).

## 8. Audit Trail

- JSONL: `memory/researcher/seed_abort_log.jsonl` (1 line appended on this trigger)
- Related abort docs (same pattern, RAG_TOPICAL_RELEVANCE / PRIOR_ART_OPEN / ANTI_PERSONA injection):
  - `2026-05-29-daily-scan-empty-rag-seed-abort.md` + v2 + v3
  - `2026-05-29-weekend-gap-fill-stats-seed-abort-v2.md` + v3
  - `2026-05-30-brooks-confirmation-window-sweep-seed-abort-v2.md`
  - `2026-05-30-vsaclimax-volz-threshold-sweep-seed-abort-v2.md`
  - `2026-05-30-vsaclimax-widestop-slpctmin-sweep-seed-abort.md`
  - `2026-05-29-btc-dominance-shift-triggers-seed-abort-v2-topic-mismatch.md`
  - `2026-05-29-liquidity-grab-reversal-seed-abort.md`
  - `2026-05-29-engulfing-momentum-entry-seed-abort.md` + v2
  - `2026-05-29-fomc-cpi-event-pre-positioning-seed-abort.md`
  - `2026-05-29-oi-volume-divergence-seed-abort-duplicate.md`

## 9. Researcher Discipline Note

Bu 14. ardışık seed-abort (72h pencere). "Üretmemek" yine doğru hamleydi.

- "Strong opinions, loosely held + reject more than you accept" — pratiğe döküldü.
- "Read first, code second" — RAG topical=0 + v1 NOT_EXECUTABLE durumunda hiçbir kod yazılmamalı.
- "Distrust your own backtest" → "Distrust the prompt" — cron prompt'un kendisi anti-persona ise prompt'a uymak persona ihlali.
- "Pre-register, then test" — pre-register fonksiyonu curve-fit'i önlemek; "curve-fit şüphesi yarat" prompt'u bu fonksiyonun terselemesi.

Bir dahaki sefer (2. trigger): doc YAZ (1 günlük state delta), 3.+ trigger: JSONL-only.
