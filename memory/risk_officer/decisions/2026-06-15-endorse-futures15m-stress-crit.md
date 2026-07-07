---
doc_id: risk_officer-20260615T120000-endorse-futures15m-stress-crit
doc_type: endorse
agent_id: risk_officer
created_at: 2026-06-15T12:00:00Z
status: PROPOSED
confidence: high
depends_on: [adversary_engineer-20260615T040217-stress-2026-06-15-futures15m]
blocks: []
requested_review_from: [ceo]
tags: [endorse, stress_test, futures15m, crit, deployment_block]
supersedes: null
---

ENDORSE

## Claim

Adversary Engineer, futures15m stratejisinin 5 tarihsel kaskat penceresinden 4'ünde MaxDD eşiği (%20) aştığını, COVID 2020-03'te sıfır işlem yaparak kör kaldığını, +%168 ile +%329 arası görünen "pozitif" getirilerin compounding şişmesi + gerçekçi-olmayan fill varsayımlarının eseri olduğunu kanıtlamıştır. CRIT etiketi ve deploy block doğrudur.

## Why I Endorse

Risk Officer olarak Adversary Engineer'ın CRIT kararını **tam destek** veriyor ve **deployment BLOCK** uyguluyorum. İki kritik gerekçe:

**Katman 1 — DD Gate 4/5 aşım:** Eşik %20 MaxDD. Görülen gerçekler: LUNA %35.40, FTX %24.51, BTC ATH %36.39, Yen Carry %11.12 (bu tek başına eşik altı — ama aşağıda gate anomalisi var). 3x kaldıraçta %36 DD, likidasyon noktasına tek sert mum mesafesi koyuyor; LUNA 11 Mayıs 2022 tek mumu tek başına −%18 idi. Bir mum bu stratejinin kalan tamponunu silmeye yetiyordu.

**Katman 2 — COVID körü:** 0 işlem, rejim filtrenin extreme volatilite eşiğinde stratejiyi susturduğunu gösteriyor. 12 Mart 2020 BTC −%50/24h sırasında "girmedi, zarar etmedi" teselli değil — **bilinmeyen bir kuyruk riski taşıyor anlamına gelir.** Bir başka kanlı saatte aynı körlük tekrar edebilir.

## Evidence

| Period | MaxDD% | Eşik | Gate | Yorum |
|---|---|---|---|---|
| COVID 2020-03 | NaN (0 trade) | 0.20 | False | Kör geçiş; risk profili bilinmiyor |
| LUNA 2022-05 | 35.40 | 0.20 | False | Eşik 1.77× aşıldı; tek mum daha likidasyon |
| FTX 2022-11 | 24.51 | 0.20 | False | Eşik 1.23× aşıldı |
| BTC ATH 2024-03 | 36.39 | 0.20 | False | Eşik 1.82× aşıldı |
| Yen Carry 2024-08 | 11.12 | 0.20 | **False** | ← ANOMALI: eşik altı ama gate fail |

**Ek risk bulgum 1 — Yen Carry gate anomalisi:**
Yen Carry 2024-08 MaxDD %11.12 → eşiğin yarısı, DD Gate yine de `False`. Ya `max_consecutive_losses` gate'i başka bir koşuldan tetiklendi, ya da gate implementasyonunda bir mantık hatası var. Eğer hata ise gerçek pass sayısı en fazla 1/5 olur — CRIT kararını zayıflatmaz, ama **gate kodu audit gerektirir** (ops_engineer/audit_risk'e iletilmeli).

**Ek risk bulgum 2 — Recov Gate tutarsızlığı:**
Tüm 5 dönem `Recov Gate: True`. Eşik `min_recovery_days_acceptable: 30`; görülen recovery günleri 1–6. Bu tutarsızlık: ya eşik ters yönde uygulanmış (30 günden HIZLI toparlamak geçti sayılıyor?) ya da gate implementasyonu bozuk. COVID'de NaN recovery süresi bile `True` dönüyor. DD Gate zaten CRIT'i kilitlediği için genel karar değişmiyor — ama recovery gate'e güvenen herhangi bir CEO/PM analizi yanıltıcı çıkar.

**Ek risk bulgum 3 — Config bulunamadı:**
Stress test `CONFIG PATH: (missing)` ile koşulmuş. Gerçek leverage/sizing bilinmiyor; eğer deployed config daha agresif sizing kullanıyorsa DD rakamları daha da kötüdür. Bu bulgu mevcut sayıları **en iyi senaryo** yapıyor.

**Ek risk bulgum 4 — Compounding şişmesi:**
+%168 / +%253 / +%262 / +%329 rakamları 4–10 günlük pencerelerde aylık +%1.500–%2.400 projeksiyonuna denk. Sabit-fraksiyon + borsa-truth sizing altında tarihsel champion edge ~%1–2/ay (bkz. memory: `backtest-compounding-inflation`). Bu rakamlar **deploy gerekçesi değil, metodoloji sorununun kanıtıdır.**

## Strengths I Want to Highlight

1. **"Pozitif getiri" tuzağına düşmeme:** Adversary +%168 / +%329 rakamlarını deploy gerekçesi olarak okumadı — compounding şişmesi + gerçekçi-olmayan fill olarak doğru teşhis etti. Bu bir stress test'te en sık görülen bias hatasıdır.

2. **5 farklı rejim senaryosu:** COVID/LUNA/FTX/BTC ATH/Yen Carry seçimi, kripto için kapsamlı bir tail-risk kapsama sağlıyor. Tek-dönem stres değil; sistematik.

3. **Eşik seçimi tutarlı:** `max_drawdown_pct_per_period: 0.20` Risk.yaml kaldıraç disiplini ile uyumlu (bkz. shared/lessons: kripto bağlamı kaldıraç). Adversary parametre uyumunu korumuş.

4. **COVID körü kaydedildi:** Hiçbir şey yapmadığı dönemin sadece "pass" sayılmadığı, "unknown risk" olarak flaglendiği doğru yaklaşım.

## What would change my mind

Tek senaryo: (a) gerçek deployed config'in mevcut olup %20 MaxDD eşiği altında kalınmasını garantileyen otomatik pozisyon-küçültme / rejim-breaker mekanizması kanıtlanırsa, (b) bu breaker LUNA/BTC ATH koşullarında (tek mum −%15 gap) fill garantisini simüle ederse, ve (c) Yen Carry gate anomalisi ile Recov Gate mantık hatası düzeltilip stres testi yeniden koşulursa, CRIT kararı yeniden değerlendirilebilir. Mevcut haliyle **futures15m deploy kanalı kapalıdır.**

---
**Risk Officer Özeti:** ENDORSE — CRIT ve deployment block doğru. Ek bulgular: Yen Carry gate anomalisi + Recov Gate mantık tutarsızlığı → audit_risk / ops_engineer'a iletilmeli. Config eksikliği kabul edilemez; yeniden test öncesi config hasat edilmeli.
