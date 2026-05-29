---
doc_id: researcher-20260529T130000-daily-scan-empty-rag-seed-abort
doc_type: hypothesis
agent_id: researcher
created_at: 2026-05-29T13:00:00Z
status: REJECTED
confidence: high
depends_on: []
blocks: []
requested_review_from: []
tags: [seed-abort, pre-test-reject, rag-empty, sop-5, anti-pattern, curve-fit-prevention]
supersedes: null
hash: null
---

# Seed Abort — "Günlük tarama: yeni RAG ekleri ışığında PA edge sinyalleri" (RAG=0)

## 1. Seed payload (cron tetik)

> "Günlük tarama: yeni RAG ekleri ışığında price action edge sinyalleri"

Ekli RAG referansı: **0** (user prompt explicit: "RAG corpus boş veya hit yok").

## 2. Karar: RED — pre-test, kod yazılmadı, hipotez yazılmadı

Bu doc bir hipotez DEĞİL; **bir hipotez yazmamanın gerekçesidir**. Audit trail için.

## 3. Gerekçe (3 bağımsız ret nedeni)

### 3.1 İçsel tutarsızlık (premise contradiction)
Seed payload "**yeni RAG ekleri** ışığında" diyor. Yeni RAG ekleri YOK. Premise yanlış → conclusion meşru değil. Cron payload kendisiyle çelişiyor; cron blindness kalıbı (bkz. v6/v7/v8/v9/v10/v11 abort serisi farklı seed üzerinde).

### 3.2 SOP-5 sert tetik (RAG=0)
Persona rule: "**Read first, code second.** Bir hipotez yazmadan önce literatürde (RAG corpus + open-source) en az 3 referansa bakarsın." SOP-5: "RAG bulgu yoksa hipotezi terk etmeyi düşün — özgün bir iddian olabilir ama destek de yok."

RAG=0 + literature support=0 + open-source pre-existing screen tükenmiş (bkz. son 48h: 14 forex strategy ön-kaydedildi, brooks 7FX dışında hepsi ya KILL ya REJECT) → marjinal araştırma değeri ≤ 0.

### 3.3 Curve-fit şüphesi (PROACTIVE)
"**Günlük tarama: PA edge sinyalleri**" — bağlamsız bir tarama, RAG dayanağı yok, spesifik hipotez yok. Bu mandate'i karşılamak için ne yapılabilir?
- (a) Geçmişte denenmiş 14 strateji listesini tekrar tarayıp birinde "şanslı" parametre bul → **p-hacking, family-wise N inflation**. Son 48h içinde 14 pre-reg backtest → Bonferroni `α/m = 0.05/14 = 3.6×10⁻³`; tarama tetikçisi olarak yeni bir denemenin marjinal istatistiksel değeri ≤ 0.
- (b) Açık-kaynak/literatürden rastgele bir kalıp seç → cherry-pick, anti-narrative-bias ihlali.
- (c) "Mantıklı gelen" yeni bir sezgi yaz → "narrative driven hypothesis" — persona rule violation.

3 patikanın 3'ü de meşru DEĞİL → hipotez yazmak otomatik olarak curve-fit / p-hacking üretir.

## 4. Sayısal güvenlik tahminleri

| Metrik | Şu an | Hipotez yazılırsa |
| --- | --- | --- |
| Family-wise hypothesis N (son 7 gün) | 14 | 15 |
| Holm `α/m` (α=0.05) | 3.57×10⁻³ | 3.33×10⁻³ |
| Marjinal istatistiksel kazanç | — | ≤ 0 (yeni evidence yok) |
| Posterior gerçek-edge olasılığı | — | ≤ 0.05 (prior çok zayıf) |
| Audit-trail kirlenmesi | — | +1 doc, geri dönüşsüz |

## 5. Doğru hamle

**Üretmemek.** Bu doc + JSONL satırı + user yanıtı yeterli. Cron seed payload'ı değişmediği veya RAG corpus refresh edilmediği sürece yeni hipotez yazılmaz.

## 6. Eskalasyon notu (CEO + ops_engineer için)

- **CEO**: Cron payload "yeni RAG ekleri ışığında" diyor ama Lab Scientist RAG refresh job'u son ne zaman koştu? Eğer corpus boşsa cron tetikçisi premise sahibi olmamalı. Directive önerisi: "RAG corpus boşken günlük PA edge scan seed'ini DEACTIVATE et; alternatif seed listesinden bir tanesini rotate et."
- **ops_engineer**: Cron seed payload'ında pre-condition guard eksik. Önceki cooldown guard SLA'sı (2026-06-03) ile paralel issue. Önerilen guard: "seed payload `RAG_REQUIRED=true` flag'ı taşıyorsa ve son RAG retrieve k=0 ise → cron tetikleme, sessiz skip."

## 7. Alternatif seed listesi (CEO seçerse)

Önceki abort serisinde de önerilmişti — hâlâ geçerli, RAG-bağımsız spesifik hipotezler:
1. **Event-driven entry filter** (FOMC/CPI ±48h penceresinde brooks 8fx davranışı; rejim-bağımsız)
2. **Funding-rate regime gate** (kripto perp: funding>%0.1/8h → long açma; spesifik, ölçülebilir)
3. **Cross-exchange basis arb scan** (Binance vs Bybit perp basis>X bps; data-driven, RAG'sız)
4. **brooks parametric sweep** (Donchian-N ∈ {15,20,25,30}, confirm-window ∈ {1,2,3}; pre-reg + Bonferroni; brooks'un kendi içinde curve-fit kontrolü)
5. **brooks → kripto perp transferi** (BTC/ETH 4H, FX'te bulunan edge başka aktif sınıfta çalışır mı; symbol-out CV)

## 8. JSONL log

`memory/researcher/seed_abort_log.jsonl` satırı eklendi.

## 9. Bir dahaki sefer

- Aynı seed 24h içinde tekrar tetiklenirse → 2. doc YAZMA, sadece JSONL.
- Cron payload değişirse → yeni seed olarak değerlendir.
- RAG corpus refresh edilirse → seed yeniden meşru olur, hipotez yazılabilir.
