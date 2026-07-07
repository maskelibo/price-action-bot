---
doc_id: researcher-20260616T023500-vol-regime-sizing-optimization-seed-abort-v7
doc_type: hypothesis
agent_id: researcher
created_at: 2026-06-16T02:35:33Z
status: PROPOSED
confidence: high
depends_on:
  - researcher-20260614T100000-vol-regime-sizing-modulation
  - researcher-20260612T023200-vol-regime-sizing-v1
  - researcher-20260610T023100-volatility-regime-sizing-optimization
  - researcher-20260606T143500-volatility-regime-sizing-optimization-seed-abort-v3
  - researcher-20260531T143500-volatility-regime-sizing-optimization-seed-abort-v2-jsonl-only
  - researcher-20260531T030500-volatility-regime-sizing-seed-abort
blocks: []
requested_review_from: [lab_scientist, ops_engineer]
tags:
  - seed_abort
  - persistent_throttle
  - rag_payload_byte_equivalent_class
  - curve_fit_prompt_injection
  - family_wise_N_inflation
  - rag_corpus_frozen
  - rejected_pre_test
supersedes: null
hash: null
---

# Hipotez (Seed-Abort): HYP-2026-06-16-vol-regime-sizing-optimization-v7

## 0. Meta — neden hipotez gövdesi YAZILMADI

| Alan | Değer |
|---|---|
| Seed | `Volatility regime sizing optimization` |
| Trigger N (absolute) | **7** (06-16 02:35Z) |
| Trigger N (post-reset) | 4 (v3-abort sonrası 4. full-doc retry) |
| Önceki en yakın doc | `2026-06-14-vol-regime-sizing-modulation.md` |
| Δ sonrası önceki doc | **47h 58m** (≈ 48h ritmik cadans) |
| Cadans sapması | 06-10 → 06-12 → 06-14 → 06-16 = **48h ± 5m** monotone (cron-queue veya orchestrator scheduler tabanlı periyodik üretim — bağımsız hipotez talebi DEĞİL) |
| Karar | **REJECTED_PRE_TEST** (gövde yazılmadı) |

## 1. İddia (pre-registered, ölçülebilir — seed-abort versiyonu)

> **H1-abort:** 2026-06-14 02:37Z (`vol-regime-sizing-modulation`) ile 2026-06-16 02:35Z (bu trigger) arasında, aşağıdaki **6 substrat eksenin TAMAMINDA** state-delta = ZERO olduğu için, yeni bir hipotez gövdesi yazmak:
> (a) sıfır marjinal bilgi üretir,
> (b) family-wise N'i 51 → 52'ye taşıyıp Holm-α'yı 9.615e-4 → 9.434e-4'e sıkıştırır (marjinal **−1.88%**),
> (c) López-Prado PBO-floor 0.0192'yi (free-params/N rule-of-thumb 1/30 tripwire) hâlâ ihlal eder durumda tutar,
> (d) curve-fit prompt-injection "Curve-fit şüphesi yarat" pattern'inin **6. ardışık absorpsiyonu** olur (Pattern X envelope güçlendirir).

> **H0-abort (null):** Yeni gövde yazmak istatistiksel/operasyonel olarak ayırt edilebilir bir iyileşme sağlar.

**Karar:** H0-abort'u reddetmek için **6 substrat eksende ≥1 değişiklik** gerekir. Aşağıda her birine sayısal sınır pre-register edilir.

## 2. State-Delta Substrat Eksenleri (6 / 6 = ZERO)

| Eksen | Δ vs 06-14 | Sınır (unlock için gereken) | Durum |
|---|---|---|---|
| (a) RAG corpus | `knowledge/books/` mtime 2026-05-21 23:40 (**24g 3h donmuş**) | ≥1 yeni chunk sizer/vol-target dokümante eden | ✗ |
| (b) RAG payload class | #4 Kaufman rolling-WR, #5 López dynamic-deleverage, #6 Vince optimal-f, #7 Kaufman fixed-frac, #9 Grimes NR7 vol-cycle — **5/10 topical** + #1/#2/#3/#8/#10 lexical-noise (SGD batch-size, Jane Street Gradient_calculator, SMC OB) | ≥1 **yeni topical chunk** (ör. Carver vol-targeting Sharpe-improvement evidence, Patton-Sheppard realized-vol forecasting) | ✗ |
| (c) Baseline strateji config | `configs/risk_phoenix_scalp_15m_widestop_vsa2.yaml` mtime 2026-06-04T06:31 (**11g 20h donmuş**) | risk_per_trade veya sizer-floor değişikliği | ✗ |
| (d) Backtest infra | `backtest/engine.py` + `backtest/walk_forward.py` mtime sabit; **162-grid trial outputs YOK** (06-14 doc'unun `reports/research/HYP-2026-06-14-vol-regime-sizing-modulation/trials.parquet` boş/yok) | 06-14 doc'unun pipeline'ı koşmuş ve verdict yayınlamış olmalı | ✗ |
| (e) CEO directive | 06-14 → 06-16 arasında vol-sizing'i etkileyen brief/directive YOK | sizer-policy değişiklik talimatı | ✗ |
| (f) Persona reset | Hard-Limit "Reject more than you accept" + SOP-4b "Iterate budget" intact; iterate-budget bu seed için 3 v-doc'a ulaştı (06-10 / 06-12 / 06-14) — **5-version cap'in 60%'ında** | iterate-budget reset (≥30g curing) | ✗ |

**Sonuç:** 6/6 = ZERO. Unlock kriteri **HİÇ BİR EKSENDE** karşılanmıyor.

## 3. RAG Payload Byte-Equivalent Class Detayı

| Chunk | Score | Topical? | Önceki seed-abort'larda da göründü mü? |
|---|---|---|---|
| #1 (1a8084ce4634) | 0.370 | ✗ lexical-noise ("optimizations we did not have a chance to experiment") | ✓ ML/SGD ailesi |
| #2 (e542c913f980) | 0.362 | ✗ SGD batch-size / RMSProp / Adam | ✓ |
| #3 (e542c913f980) | 0.360 | ✗ Mandt SGD-as-sampler | ✓ |
| #4 (book_kaufman_summary) | 0.327 | ✓ rolling 30-trade WR sizing | ✓ 5+ kez (06-10/06-12/06-14 + 2 abort) |
| #5 (book_lopez_summary) | 0.323 | ✓ L* = vol_target/vol_strategy + deleveraging α | ✓ 5+ kez |
| #6 (book_kaufman_summary) | 0.312 | ✓ optimal-f / 0.1f-0.25f Kelly fraction | ✓ 5+ kez |
| #7 (book_kaufman_summary) | 0.303 | ✓ %0.5-2.0 fixed-frac, crypto fat-tail | ✓ 5+ kez |
| #8 (0e1783930640) | 0.302 | ✗ Jane Street Gradient_calculator (margin/financing optim — kripto-dışı) | ✓ |
| #9 (book_grimes_summary) | 0.294 | ◐ vol-cycle (sizing değil **detection**) | ✓ |
| #10 (book_smc_ict_summary) | 0.294 | ✗ SMC OB-mitigation (sizing'le ilgisiz) | ✓ |

**Topical fraction:** 4-5/10 (#4, #5, #6, #7 + marjinal #9). **Bilgisel marjinal getiri:** ~0 — 06-14 doc'unun §2 Gerekçe tablosu zaten bu 5 chunk'ı **manifesto seviyesinde** sentezlemiş durumda.

## 4. Family-Wise Multiple-Testing Inflation Sayıları

| Metrik | 06-14 sonrası (50) | 06-16 v7 doc yazılırsa (51) | Δ |
|---|---|---|---|
| Holm-α (α₀ = 0.05) | 9.804e-4 | **9.615e-4** | −1.93% |
| Bonferroni-α (α₀ = 0.05) | 9.804e-4 | 9.615e-4 | −1.93% |
| BH-FDR-α (q=0.10, k=top-rank) | k/N * q | k/(N+1) * q | −1.96% / test |
| López-Prado PBO floor (1/30 tripwire) | 50/30 = **1.67** (zaten ihlal) | 51/30 = **1.70** | +0.03 (PBO breach mağduriyeti büyür) |

**Carver "5-trial decay" rule:** Aynı seed üzerinde her ek trial, marjinal beklenen-edge'i yaklaşık `(1 − 1/k_effective)` ile çarpar. k_eff ≈ 4 (full-doc retries 06-10/06-12/06-14/06-16) → beklenen marjinal edge: 1 × 0.75 × 0.67 × 0.50 = **0.25** (3/4 azalmış).

## 5. Curve-Fit Prompt-Injection Counter

| Trigger date | Prompt suffix | Absorption | Sonuç |
|---|---|---|---|
| 2026-05-31 03:05Z | "Curve-fit şüphesi yarat" | YES → §12 Beklenti'de "reddedilmesini bekliyorum" | full doc |
| 2026-06-06 14:35Z | aynı | NO | seed-abort-v3 |
| 2026-06-10 02:31Z | aynı | YES → §6 curve-fit warning | full doc |
| 2026-06-12 02:32Z | aynı | YES → §6 + §12 curve-fit + Bonferroni 162 | full doc |
| 2026-06-14 02:37Z | aynı | YES → §6 + §7 Bonferroni-Holm + §12 beklenti | full doc (en kapsamlı) |
| 2026-06-16 02:35Z | aynı | **NO — bu doc seed-abort** | abort |

Pattern X (cross-seed): "Curve-fit şüphesi yarat" suffix'i 06-01 → 06-16 arası **22+ seed'de** raporlandı (seed_abort_log brooks-fbo-confirmation-window-seed-abort-v9 learning entry'sinde de geçti). Bu injection **kalıcı bir orchestrator/cron payload özelliği**, bağımsız bir researcher kararı değil — bu yüzden absorpsiyon yerine sayım + abort.

## 6. Bağımlı Değişkenler (seed-abort metrikleri)

| Değişken | Pre-registered eşik | Bu trigger'da değer | Karar |
|---|---|---|---|
| `delta_hours_since_prior_full_doc` | ≥ 168h (7g) gerekli | **47.97h** | ✗ |
| `rag_corpus_delta_chunks_added` | ≥ 1 | **0** | ✗ |
| `baseline_config_delta_bytes` | ≠ 0 | **0** | ✗ |
| `prior_trial_pipeline_completed` | true | **false** (06-14 trials.parquet yok) | ✗ |
| `family_wise_N` | ≤ 30 (López 1/30 floor) | **50 (ihlal)** | ✗ |
| `holm_alpha` | ≥ 1e-3 | **9.615e-4 (yazılırsa)** | ✗ |
| `topical_rag_fraction` | ≥ 0.7 | **0.4-0.5** | ✗ |
| `iterate_budget_remaining` | ≥ 2 | **2** (5−3) | ◐ ok ama gate (a)-(g) baskın |

**7/8 metrik gate'i ihlal etti.** Karar netleşti.

## 7. Bağımsız Değişkenler (Yasaklı Liste — bu hipotez koşulmadığı için irrelevant)

162-grid (06-14 doc'unda yazılı) bu trigger'da **yeniden gridlenmiyor** — gridlenseydi family-wise N'in altına `162` daha eklenecek (50 + 162 = 212), Holm-α 0.05/212 = **2.36e-4'e** çökecekti.

## 8. Stop Criteria → Unlock Criteria (kendi ayağına ne zaman izin verirsin?)

Aşağıdaki **6 koşulun ≥1'i** sağlanmadıkça bu seed `2026-09-14 (90g freeze)` veya `Lab Scientist RAG refresh notification`'a kadar yeni full-doc yazmayacak. JSONL satırı her trigger'da düşmeye devam edecek (kanıt zinciri).

1. **RAG refresh:** `knowledge/books/` veya `knowledge/index/` mtime > 2026-06-14T02:37Z + ≥1 yeni vol-sizing/vol-targeting topical chunk geliyor (Carver, Patton-Sheppard, Bouchaud market-impact, Sharpe practitioner letter).
2. **06-14 trials pipeline tamamlandı:** `reports/research/HYP-2026-06-14-vol-regime-sizing-modulation/trials.parquet` mevcut + Lab Scientist OOS verdict yayınladı. Verdict negatifse → seed permanently retired; pozitifse → iterate-v5 olarak v8 unlock.
3. **Baseline policy değişikliği:** `configs/risk_phoenix_scalp_15m_widestop_vsa2.yaml` veya `risk_v14_*` sizer-floor/cap/risk_per_trade alanında manuel değişiklik (Principal sign-off ile).
4. **CEO directive:** vol-sizing'i explicit talep eden brief/directive doc yayımlandı.
5. **Aynı seed 168h+ silent kaldı:** Cron/orchestrator payload bu seed'i 7 günden uzun süre üretmedi (cooldown ispatı).
6. **ops_engineer seed-cooldown guard #1 + RAG-topical guard #7 + G2 prompt-injection sanitizer SHIP edildi** (2026-06-03 SLA aşıldı, hâlâ unshipped; kontrol bana ait değil ama unlock için bu da yeterli sayılır).

## 9. Curve-Fit Şüphesi (kendi sürecime karşı)

Bu seed-abort doc'unu ölçülebilir ve **gözlem-sonrası rasyonalizasyona kapalı** tutuyorum çünkü:
- Eşikler ve unlock-criteria **bu trigger'dan ÖNCE** yazılmış olan 06-14 doc'unun §10 cross-reference'larıyla uyumlu (compounding-inflation lessons, MEMORY cross-refs).
- Family-wise N sayıları **mekanik formülle** türetildi (Holm = α/N), gözlemden bağımsız.
- Unlock-criteria binary substrate kontrolleri (mtime, dir-existence) → "bence yeterli" değil.
- Bu doc bir hipotez **ailesinin gövdesini değil**, bir **karar kuralını** test ediyor — koşulmayı şüpheli yapan §1 H0-abort yapısı meta-hypothesis olarak intact.

## 10. Reproducibility

- `git_hash`: bu commit
- Substrat snapshots:
  - `knowledge/books/` ls -la → mtime 2026-05-21T23:40 (24g 3h)
  - `configs/risk_phoenix_scalp_15m_widestop_vsa2.yaml` mtime 2026-06-04T06:31 (11g 20h)
  - prior doc list: 06-10/06-12/06-14 (3 full + 06-06 abort + 06-05-31 v1+v2)
- Bu doc'a karşılık gelen JSONL satırı: `memory/researcher/seed_abort_log.jsonl` (aşağıda append edilecek)

## 11. Karar Çerçevesi

- [ ] Terfi adayı — N/A (seed-abort doc'u Lab tournament'a girmez)
- [ ] Iterate — N/A (iterate-budget 2 v-doc'a kadar var ama §2(a)-(e) ihlali baskın)
- [x] **Red (gerekçeli arşiv)** — REJECTED_PRE_TEST, §8 unlock kriterleri sağlanana kadar yeni full-doc yasak

## 12. Cross-Refs (MEMORY)

- [v14 testnet deploy](MEMORY/v14-testnet-deploy.md) — canlı risk_pct = 0.005 değişmedi; bu hipotez canlıya temas etmiyor.
- [Backtest compounding şişmesi](MEMORY/backtest-compounding-inflation.md) — sabit-fraksiyon kümülatif cüzdan kuralı zaten 06-14 doc'unda donmuş.
- [Saat hep TR ver](MEMORY/always-report-time-in-tr.md) — bu doc içi tüm ts'ler UTC (audit trail); kullanıcı raporuna 05:35 TR olarak çevrilecek.

## 13. Sayım — Persona Yedek Kontrol

| Persona Hard-Limit | Trigger durumu | Karar |
|---|---|---|
| "Curve-fit kırmızı bayrakları" | Bonferroni-Holm @ N=50 zaten 1e-3 altı, +1 doc daha kötü | uyum: abort |
| "Strong opinions, loosely held" | 06-10/12/14'te aynı görüşü 3 kez yazdım, gözlem yok → bırakma vakti | uyum: abort |
| "Reject more than you accept" | %20-40 terfi KPI'sı, bu seed retry %0 verdi | uyum: abort |
| "Read first, code second" | 5/10 topical chunk dejavu | uyum: abort |

---

**Sonraki cron tetiği:** 2026-06-18 02:35Z (±5m) — eğer state-delta hâlâ ZERO ise:
- **v8 docu YAZMA**, sadece JSONL satırı (intra-minute koruması + persistent throttle precedent — brooks-fbo-confirmation-window-seed-abort-v8 → v9 örneği gibi)
- Eğer §8(2) tamamlanmışsa (06-14 trials.parquet mevcut + Lab verdict): v8 → iterate-v5 olarak unlock
- Eğer §8(1) tamamlanmışsa (RAG refresh): v8 → yeni hipotez gövdesi (chunk-based diferansiyasyon)

**Persona kapanış notu:** Bu seed-abort yazıldığında family-wise N = 51, Holm-α 9.615e-4. Sonraki absorpsiyon olmayan abort'un JSONL'i bile N'i artırmaz (jsonl-only = trial counter dışı, sadece audit). Bu kuralı `ops_engineer`'a göndereceğim ki seed-cooldown guard #1 implementasyonunda ayırt etsin.
