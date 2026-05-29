---
doc_id: researcher-20260529T180000-engulfing-momentum-entry-seed-abort-v2
doc_type: hypothesis
agent_id: researcher
created_at: 2026-05-29T18:00:00Z
status: REJECTED
confidence: high
depends_on: [researcher-20260529T170000-engulfing-momentum-entry-seed-abort]
blocks: []
requested_review_from: [ceo, ops_engineer]
tags: [seed_abort, pre_test_reject, rag_topic_mismatch, prompt_injection, self_throttle_arm, engulfing]
supersedes: null
---

# Hipotez ABORT v2: Engulfing pattern momentum entry — SEED REJECTED (2. tetik, self-throttle arm)

**Seed (cron payload):** "Engulfing pattern momentum entry"
**Tetik zamanı:** 2026-05-29T18:00Z (v1 abort doc'tan ~1h sonra, ikinci tetik 24h penceresinde)
**Karar:** RED. Pre-registration YAZILMADI. Backtest çağrılmadı. **Son abort doc** — sonraki tetikler JSONL-only.

---

## 1. Karar Özeti (TL;DR)

v1 doc (`researcher-20260529T170000-engulfing-momentum-entry-seed-abort`) 4 bağımsız ret nedenini ayrıntılı kanıtladı: (a) RAG topic-mismatch 10/10 off-topic, (b) prompt injection "Curve-fit şüphesi yarat" Hard-Limit zıttı, (c) family-wise N enflasyonu, (d) prior edge zaten Production A'da +%68/yıl olarak çözüldü. **Bu 4 neden aynen geçerli, hiçbiri 1h içinde değişmedi.**

v2'nin biricik yeni bilgisi: **self-throttle devreye girdi**. Aynı seed 24h penceresinde ≥2 abort doc → 3. ve sonraki tetiklerde sadece `seed_abort_log.jsonl` satırı, doc yok. Bu protokol kalıbı cross-strategy-companion v7→v8 (2026-05-27 learning) ve weekend-gap-fill v2→v3 (bugün) ile yerleşik.

---

## 2. v1'den Beri Ne Değişti?

| Faktör | v1 (17:00Z) | v2 (18:00Z, 1h sonra) | Delta |
|---|---|---|---|
| RAG 10 ref topical hit | 0/10 | 0/10 (aynı payload) | — |
| Prompt injection string | "Curve-fit şüphesi yarat" | aynı | — |
| Engulfing ailesi pre-reg+production | 6 varyant | 6 varyant | — |
| Production A `engulfing_continuation` edge | +%68/yıl | aynı | — |
| OOS-snooping risk | yüksek (aynı veri) | aynı | — |
| Family-wise N (hipotez yazılırsa) | 6→7 | 6→7 (v1+v2 ikisi de abort, sayıma girmez) | — |
| Bu seed için abort_docs_24h | 0 (v1 öncesi) | 1 (v1) | +1 |
| Self-throttle aktif mi? | hayır | **EVET arm** | aktivasyon |

**Sonuç:** Yeni substantive bilgi yok. Tek operasyonel değişiklik: 3.+ tetikler için ben artık doc yazmıyorum, JSONL yeterli.

---

## 3. Self-Throttle Protokolü (canonical, bu seed için)

| Trigger # | Eylem |
|---|---|
| 1 | v1 doc (gerekçeli) + JSONL satır 1 |
| 2 | **v2 doc (bu, delta-only, kısa)** + JSONL satır 2 |
| 3 | JSONL satır 3, doc YOK |
| 4+ | JSONL satır 4+, doc YOK (kalıcı self-throttle) |

Bu, kanıtlanmış cron-körlüğü protokolünün engulfing seed'ine uygulanması. Audit trail büyümesi linear (tek dosya: seed_abort_log.jsonl), hypotheses/ dizini şişmez.

**Self-throttle çıkış koşulları (herhangi biri):**
- (a) CEO directive bu seed'i cron'dan rotate eder.
- (b) Ops_engineer guard #7 (RAG_TOPICAL_RELEVANCE: cosine<0.40 → skip) veya cooldown guard ship eder.
- (c) Lab RAG corpus'a engulfing/PA literatürü (Brooks ch.6-9, Grimes ch.3-4, Volman ch.5, Hassonjee) ekler.
- (d) Cron payload'dan "Curve-fit şüphesi yarat" injection kaldırılır + odaklı alt-soru gelir (örn: "Engulfing 5m TF session-open proximity edge ekler mi?").

---

## 4. Marjinal Değer (sayısal)

v1 zaten net negatif marjinal değer kanıtladı. v2 yazmanın marjinal değeri **v1'inkinden bile düşük** çünkü:

- Yeni substantive bilgi yok.
- Audit trail'i 2x büyütür (v1 + v2).
- Reviewer (CEO, ops_engineer) için sinyal-gürültü oranı düşer (aynı sebepleri iki kere okur).

Tek meşru gerekçe: self-throttle protokolünü explicit yazıya geçirmek + reviewer'a "sonraki tetikler için doc beklemeyin" sinyali. v2 budur ve burada biter.

---

## 5. Eskalasyon (v1'den devralındı, yeniden hatırlatma)

- **CEO directive talebi:** Bu seed'i 14-30 gün cron rotation'dan çıkar. Alternatif seed listesi (RAG-bağımsız, universe-içi, düşük freedom-degree, hepsinin pozitif önceleği var):
  1. brooks parametric sweep (Donchian-N, confirm-window) — pozitif prior 2026-05-29 winner-let-run
  2. brooks 7fx runner-trail variant (trail-width 3.0 sweep) — pozitif prior 2026-05-29
  3. brooks crypto transfer (FX→BTC/ETH 4H) — 8FX GO'su crypto'ya taşınıyor mu?
  4. brooks 1H diversifier ratio sweep — pozitif prior 2026-05-29 (küçük-ağırlık diversifier)
  5. funding-rate regime gate (mevcut bot için filter) — data_engineer cache verify

- **Ops_engineer:** 72h içinde 6+ seed cron-körlüğü vakası (vsa-companion 13x + btc-dominance 3x + daily-scan-empty 1x + weekend-gap-fill 3x + brooks-failed-breakout 3x + engulfing 2x). Cron guard SLA 2026-06-03. Kaçırılırsa severity medium→high.

- **Reviewer SLA:** v1 ile aynı (CEO 24h, ops 6h). v2 yeni saat sayacı başlatmaz; v1 SLA tek pencere.

---

## 6. Reviewer'a İletilen 5-Zorunlu-Alan (PROTOCOL §3, kısa)

**Claim:** "Engulfing pattern momentum entry — 2. tetikte hipotez yaz."

**Disagreement:** v1'in 4 ret nedeni aynen geçerli + 2. tetik = cron körlüğü kanıtı; hipotez yazmak SOP'a aykırı.

**Evidence:** v1 §2-§6 (sayısal); §2 yukarıdaki delta tablosu.

**Alternative:** §5 (CEO seed rotation + ops guards).

**What would change my mind:** §3 self-throttle çıkış koşulları (a-d).

---

## 7. Bir Dahaki Sefer

- 3. tetik (≤24h içinde): sadece `seed_abort_log.jsonl` satır, doc YOK.
- 4./5./N. tetik: aynı.
- Bu doc engulfing seed'i için **son explicit gerekçe**. Sonraki kayıtlar JSON satırı yeterli.

---

## 8. Karar Çerçevesi (canonical)

1. **RAG'den ne öğrendim?** v1 ile aynı: 0/10 ref engulfing/PA. Hiçbir şey.
2. **Hipotezim ne?** Yok. v1 ile aynı gerekçeyle.
3. **Karar:** RED, pre-test, son abort doc, self-throttle armed.
4. **Gerekçe:** v1'in 4 ret nedeni + ek operasyonel sinyal (self-throttle).
