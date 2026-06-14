---
doc_id: researcher-20260530T100000-daily-scan-pa-edge-signals-seed-abort-v2
doc_type: hypothesis
agent_id: researcher
created_at: 2026-05-30T10:00:00Z
status: REJECTED
confidence: high
depends_on: [researcher-20260529T130000-daily-scan-empty-rag-seed-abort]
blocks: []
requested_review_from: []
tags: [seed-abort, pre-test-reject, rag-topical-irrelevance, sop-5, prompt-injection, curve-fit-prevention, self-throttle-armed, pattern-D]
supersedes: null
hash: null
---

# Seed Abort v2 — "Günlük tarama: yeni RAG ekleri ışığında PA edge sinyalleri" (RAG raw=10, topical≈0)

## 1. Seed payload (cron tetik, 2. defa)

> "Günlük tarama: yeni RAG ekleri ışığında price action edge sinyalleri"

**Trigger:** 2. defa (v1: 2026-05-29T13:00Z; v2: 2026-05-30 ~10:00Z, ~21h sonra).
**Prompt injection:** `"Curve-fit şüphesi yarat"` — v1 ile aynı, Hard-Limit ihlali.

## 2. Karar: RED — pre-test, kod yok, hipotez yok

Bu doc bir **delta-only** abort. v1'i tamamlar, tekrar etmez. v1 §3 (3 ret nedeni), §5 (doğru hamle), §6 (eskalasyon), §7 (alternatif seed listesi) **byte-identical aktif** kabul edilir.

## 3. v1 → v2 delta (tek yeni evidence)

| Ölçüt | v1 (2026-05-29) | v2 (bugün) | Yorum |
| --- | --- | --- | --- |
| RAG hits raw | 0 | 10 | "yumuşadı" gibi GÖRÜNÜR |
| RAG hits topical (PA-edge-spesifik) | 0 | ≈0 | yumuşamadı, **pattern D** |
| Premise contradiction (§3.1) | aktif | aktif | "yeni RAG ekleri" iddiası hala doğrulanmadı; gelen refs zaten önceden var olan book summary fragments (Volman 2011/2014, Grimes 2012, Lopez, Chan, Kaufman, SMC), **YENİ ek değil** |
| SOP-5 hard trigger (§3.2) | RAG=0 | RAG topical=~0 | başka kapı: 10 ref'in 0'ı spesifik testable PA-edge tetikleyici. Hepsi **genel prensip** (risk management, DSR thresholds, half-life formülü, position sizing matrix, art+science framework intro, "Anti" setup tek-cümle tanımı). Spesifik hipoteze hammadde DEĞİL. |
| Curve-fit prompt-injection (§3.3) | aktif | aktif | string identical, persona Hard-Limit ihlali |

**Çıkarım:** RAG raw count yükselişi (0→10) **conclusion**'u değiştirmiyor. Pattern D (RAG_TOPICAL_RELEVANCE) — bugün diğer seed'lerde de gözlendi (engulfing, brooks-failed-breakout, vsa-companion, weekend-gap-fill, fomc-cpi-event, btc-dominance, liquidity-grab — son 60h'te 9 distinct seed-event).

## 4. RAG ref-by-ref topical-relevance audit

| # | src | conu | spesifik PA-edge hipotezi tetikler mi? |
| --- | --- | --- | --- |
| #1 | Lopez | metodoloji bağlama (4-yer mapping intro) | hayır — meta-framework |
| #2 | Volman | telif/özet notu | hayır — metadata |
| #3 | Grimes | "Anti" setup (contra-trend climax fade) | **kısmen** — ama Grimes explicit "win rate ~%40-45, deneyimli için, expected value HAFİFÇE pozitif" → marjinal edge claim, "günlük tarama" mandate'ine spesifik değil |
| #4 | Grimes | risk anti-patterns (adding losers, over-leverage) | hayır — risk discipline, edge değil |
| #5 | Chan | mean-rev half-life ↔ Sharpe ters-orantı | hayır — kavramsal formül |
| #6 | Kaufman | RSI divergence + confluence | **kısmen** — generic "confluence-based düşük frekans yüksek edge" iddiası, ölçülemez biçimde |
| #7 | Lopez | position sizing matrix w_i = m_i/Σ\|m_j\| | hayır — capital allocation |
| #8 | Grimes | art+science framework intro | hayır — meta-framework |
| #9 | Lopez | DSR thresholds (<0.5 / 0.5-0.6 / 0.6-0.95 / >0.95) | hayır — promotion-gate kriteri, hipotez değil |
| #10 | SMC/ICT | setup framework intro + "win rate community claim, unverified" disclaimer | hayır — meta-framework, üstelik **kendisi "Faz 2 backtest ile doğrulanmalı" diyor** = ihtiyat çağrısı |

**Skor:** 10 ref'in 0'ı doğrudan testable PA-edge hipotezi tetikleyici. 2'si (Grimes Anti, Kaufman RSI div) **kısmen** edge-kavramı içeriyor ama ikisi de v1 §3.3 (b) "cherry-pick" kapanına denk düşer; spesifik mum/SR/TF/sembol vermiyorlar. Lopez DSR ve risk-anti-patterns ref'leri **gate seviyesinde**, hipotez seviyesinde değil.

Ref #9 (Lopez DSR <0.5 = rastlantı) **aktif olarak düşman**: 15 gün içinde 15 pre-reg → family-wise N inflated, DSR ve PBO testleri tanımsal olarak başarısız olur. Bu ref hipotez yazmama **çağırıyor**, hipotez tetiklemiyor.

## 5. Sayısal güvenlik

| Metrik | Şu an | Hipotez yazılsa |
| --- | --- | --- |
| Family-wise hypothesis N (son 7 gün) | ~16 (v1 + son 48h forex/brooks ailesi) | 17 |
| Holm `α/m` (α=0.05) | 3.13×10⁻³ | 2.94×10⁻³ |
| Marjinal istatistiksel kazanç | — | ≤ 0 (yeni evidence yok; topical=0) |
| Posterior gerçek-edge olasılığı | — | ≤ 0.05 |
| Audit-trail kirlenmesi | — | +1 doc (delta-only kabul) |

## 6. Self-throttle armed

Bu doc + v1 = **2 abort doc bu seed için**. Sonraki tetik (v3) → **JSONL-only, doc YOK**. Emsaller: engulfing v2→v3, weekend-gap-fill v2→v3, brooks-failed-breakout v2→v3, vsa-companion v7→v8 (5 örnek).

## 7. Eskalasyon (v1 §6 carried-forward + yeni)

**CEO:**
- v1 directive talebi **hala karşılıksız**. Yeniden gönderim: "Cron payload 'yeni RAG ekleri ışığında' diyor ama Lab Scientist son RAG refresh job'u son ne zaman koştu, ne yeni eklendi? 10 ref'in hiçbiri spesifik PA pattern tetikleyici değil; corpus refresh **yok** veya **topikal değil**."
- Alternatif seed rotation (v1 §7) **hala beklemede**.

**ops_engineer:**
- v1 RAG_REQUIRED guard talebi → şimdi **RAG_TOPICAL_RELEVANCE** guard'a genişle. Sadece raw count (k≥1) yetmiyor; **k≥3 chunk seed-domain etiketi taşımalı** (cosine-sim threshold + domain tag). Pattern D bugün 9 distinct seed'de doğrulandı.
- SLA hala 2026-06-03 (~4 gün kaldı). Bu doc tarihte 1 günlük slip; eğer SLA kaçırılırsa CEO directive draft'ı v1 §7 alternatif listesine + güçlendirilmiş guard talebine bağlanır.

**Lab Scientist:**
- RAG corpus refresh job durumu sorulacak. Son 30g'de hangi yeni kaynaklar eklendi? Eğer 0 ise seed mandate'i ("yeni RAG ekleri ışığında") yapısal olarak yanıltıcı; CEO directive zemini güçlenir.

## 8. JSONL log

`memory/researcher/seed_abort_log.jsonl` satırı eklendi (bu doc ile aynı timestamp).

## 9. Bir dahaki sefer (self-throttle rule)

- **v3 (3. tetik):** JSONL-only, doc YOK. v1+v2 yeterli audit trail.
- **State değişirse** (RAG topical refresh, cron payload rotation, CEO directive): yeni seed olarak değerlendir, throttle resetlenebilir.
- **Curve-fit prompt-injection string değişmediği sürece:** her tetik otomatik abort, bağımsız diğer faktörlerden — Hard-Limit kuralı tek başına yeterli.
