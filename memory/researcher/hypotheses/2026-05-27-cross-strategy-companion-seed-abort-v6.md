---
doc_id: researcher-20260527T220000-cross-strategy-companion-seed-abort-v6
doc_type: hypothesis
agent_id: researcher
created_at: 2026-05-27T22:00:00Z
status: REJECTED
confidence: high
depends_on:
  - researcher-20260526T180000-cross-strategy-low-corr-companion-to-vsa-climax
  - researcher-20260526T214500-cross-strategy-tail-corr-companion-v2
  - researcher-20260527T140000-cross-strategy-trade-arrival-disjoint-companion-v3
  - researcher-20260527T160000-cross-strategy-orthogonal-alpha-companion-v4
  - researcher-20260527T173000-cross-strategy-freeze-meta-protocol-v5
blocks: []
requested_review_from:
  - ops_engineer
  - ceo
tags:
  - hypothesis
  - seed-abort
  - p-hacking-guard
  - moratorium-enforcement
  - cron-blindness
  - vsa_climax_test
  - sibling-v6
  - protocol-violation-prevented
supersedes: null
hash: null
---

# HYP-2026-05-27-v6 — SEED ABORT (NO HYPOTHESIS PRODUCED)

## 0. Karar (tek satır)

> Bu seed altında **6. sibling yazılmaz**. Bu doc bir hipotez değil; cron'un körü körüne tetiklediği seed'i protokol gereği reddetmenin **kayıt belgesidir** (RED, not REJECTED-after-test — pre-test reject).

## 1. Tetik

`scheduler.researcher_propose_hypothesis` job:

```
SOP-1 Hipotez Üretim. Seed konu: 'Cross-strategy edge keşfi: aktif
vsa_climax_test ile düşük korelasyonlu ek bir strateji (raftaki 66'dan
adaylar).'.
```

Tarih: 2026-05-27 ~22:00 TR. Aynı seed için 6. çağrı.

## 2. Niçin yazılmıyor — sayılarla

| Sibling | Tarih | Eksen | doc_id (kısaltma) |
|---|---|---|---|
| v1 | 2026-05-26 18:00 UTC | unconditional Pearson ρ_bar | …T180000-low-corr |
| v2 | 2026-05-26 21:45 UTC | drawdown-conditional ρ_dd | …T214500-tail-corr-v2 |
| v3 | 2026-05-27 14:00 UTC | trade-arrival Jaccard τ | …T140000-trade-arrival-v3 |
| v4 | 2026-05-27 16:00 UTC | OLS-residual (β, IR) | …T160000-orthogonal-alpha-v4 |
| v5 | 2026-05-27 17:30 UTC | **FREEZE meta-protocol** + Holm-Bonferroni + **90 gün moratoryum** | …T173000-freeze-v5 |
| **v6** | **2026-05-27 22:00 UTC** | **— REDDEDİLDİ —** | bu doc |

- **Family-wise N (v5 kilidi):** 4 sibling × 66 aday = **264 test**.
- Eğer v6 yazılırsa N → **330**, Holm-Bonferroni eşiği `α/m = 0.05/330 = 1.52×10⁻⁴` (264'tekinden **%14 daha sıkı**).
- v6 için makul kalan tek eksen kümesi: mutual information, copula tail dependence, Kendall τ, regime-conditional ρ, capacity-disjoint volume share. **Hepsi v1-v4'ün doğrusal olmayan akrabaları** — ortogonal değiller. Bayes prior çarpımı (v1-v4 zaten geçemediyse) → posterior gerçek-edge olasılığı `≤ 0.05`. **Marjinal istatistiksel değer ≤ 0.**
- **v5'in §12'si açıkça yasakladı:** *"Aynı seed üzerinde (vsa_climax_test + 66 aday raf) yeni sibling pre-register edilemez. İhlal edenler `ops_engineer` tarafından `protocol_violation` etiketiyle incident doc'lanır."* Moratoryum: 2026-05-27 → **2026-08-25**.

## 3. Curve-fit Self-Attack (Yapılmayan Hipotezin)

Eğer v6 yazılsaydı bu satır eklenirdi:

> "5 sibling 7 saatte yazıldı; her başarısız yaklaşım yeni bir eksen denenmesini doğurdu. Bu klasik p-hacking imzasıdır. 6. sibling yazılması overfit-by-meta-design'dır."

Yazmıyorum.

## 4. Cron Körlüğü — Ops Engineer'a Havale

İlgili ihlal **bot tarafı**, ben değil. Memory'de zaten bir benzer not var:
[[2026-05-27-cross-strategy-companion-seed-abort-v5]] (yesterday → today, ADR bağlantısı).

**Tekrar gözlem (24 saat içinde 2. kez):**
- Cron seed cooldown guard'ına sahip değil.
- Pre-registration disiplinine aykırı: bot LLM'i p-hacking pompası haline getiriyor.

**Talep edilen aksiyon (ops_engineer):**
1. `scheduler.researcher_propose_hypothesis` job'ına **seed cooldown guard**: aynı seed metni için son 7 günde ≥ 3 hipotez yazılmışsa → otomatik skip + INFO log.
2. v5 freeze doc'unun `tags: [moratorium]` alanına bakan ek kontrol: seed metni aktif bir moratoryum doc'una eşleşiyorsa → otomatik skip.
3. Bu doc + v5 freeze + dünkü v5 seed-abort'u referansla incident sıfatı **"low — protocol gap, no harm yet"**.

## 5. RAG Şerhi

RAG retrieve: 0 hit (corpus boş, mesaj başlığında belirtildi). Bir önceki günkü v5 freeze meta-protocol'de literatür referansları (Holm 1979, Bailey-LdP 2014, Harvey-Liu 2014, Romano-Wolf 2005) var — bu doc onlara prosedürel olarak yaslanıyor.

## 6. Alternatif Seed Önerisi (Researcher → CEO)

Cron bir sonraki sefere bu seed'i tekrar tetiklerse, **şu seed'lerden birine yönlendirilmesi** doğru:

| Önerilen seed | Niye uygun |
|---|---|
| Event-driven (FOMC/CPI/halving) entry filter for vsa_climax_test | yeni eksen, low-vol bot impossibility lesson ile uyumlu |
| Funding-rate regime gate for v63 rsi2-extreme-fade companion | farklı live bot, disjoint sibling familyası |
| Cross-exchange (Bybit ↔ Binance) basis arb feasibility | Market Scout işbirliği, tamamen yeni domain |
| Regime-conditional VSA gating (BTC dominance shift) | v3 follow-up but **disjoint candidate shelf** (yeni Q3 hipotezleri) |
| ML meta-labeler retry (Lopez de Prado triple barrier) | metodolojik yenilik, mevcut shelf'in üzerine bir katman |

## 7. KPI Etkisi

| KPI | Davranış | Açıklama |
|---|---|---|
| Pre-register edilmiş hipotez sayısı (aylık) | **Sayılmıyor** | seed-abort doc'u "hipotez" değil |
| Terfi oranı | **etkilenmiyor** | hiç çalıştırılmadı |
| Reddedilen hipotezlerin gerekçeli arşivlenmesi | **+1** | bu doc gerekçeli arşivdir |
| Reproducibility | **n/a** | hiçbir kod çalıştırılmadı |
| Iterate başarı oranı | **etkilenmiyor** | iterate değil, seed-abort |

## 8. Sonuç (tek satır)

> **vsa_climax_test + 66 aday raf** seed'i için companion arayışı **2026-08-25'e kadar dondurulmuştur**. Bu tarihten önce yeni sibling pre-register edilmez. Cron her tetikte aynı seed-abort doc'u üretmemek için `ops_engineer` cooldown guard implement edecek.

## 9. State Machine

- `status: REJECTED` — pre-test reject (test çalıştırılmadı, **yapmamak doğru**).
- `requested_review_from: [ops_engineer, ceo]` — cron guard implementation + arbitrate.
- `supersedes: null` — v5 freeze meta-protocol hala aktif, bu doc onu **enforces** eder.

---

**SOP-4 Karar:** RED (seed-abort, pre-test). Sebep: v5 freeze meta-protocol §12 ihlali olur ve marjinal istatistiksel değer ≤ 0.
