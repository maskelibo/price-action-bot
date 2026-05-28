---
doc_id: researcher-20260527T230000-cross-strategy-companion-seed-abort-v7
doc_type: hypothesis
agent_id: researcher
created_at: 2026-05-27T23:00:00Z
status: REJECTED
confidence: high
depends_on:
  - researcher-20260526T180000-cross-strategy-low-corr-companion-to-vsa-climax
  - researcher-20260526T214500-cross-strategy-tail-corr-companion-v2
  - researcher-20260527T140000-cross-strategy-trade-arrival-disjoint-companion-v3
  - researcher-20260527T160000-cross-strategy-orthogonal-alpha-companion-v4
  - researcher-20260527T173000-cross-strategy-freeze-meta-protocol-v5
  - researcher-20260527T220000-cross-strategy-companion-seed-abort-v6
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
  - sibling-v7
  - protocol-violation-prevented
  - escalation-medium
  - final-abort-doc
supersedes: null
hash: null
---

# HYP-2026-05-27-v7 — SEED ABORT (3rd cron tetik / 24h)

## 0. Karar (tek satır)

> Bu seed altında **7. sibling yazılmaz**. v5 freeze §12 hâlâ aktif (moratoryum 2026-08-25'e kadar). v6 ile aynı gerekçe; sayılar değişmedi, sadece **cron körlüğü 3. tura çıktı**. Bu **son** abort doc'tur — ops_engineer cooldown guard implement edene kadar daha fazla abort doc yazmıyorum (bkz §4).

## 1. Tetik

`scheduler.researcher_propose_hypothesis` job:

```
SOP-1 Hipotez Üretim. Seed konu: 'Cross-strategy edge keşfi: aktif
vsa_climax_test ile düşük korelasyonlu ek bir strateji (raftaki 66'dan
adaylar).'.
```

Tarih: 2026-05-27 ~23:00 TR. Aynı seed için **3. çağrı (24 saat içinde)**.
Sıralama: v5 freeze (17:30) → v6 abort (22:00) → **v7 abort (23:00)**.

## 2. Niçin yazılmıyor — değişmeyen sayılar

Tüm matematik [[2026-05-27-cross-strategy-companion-seed-abort-v6]] §2'de mevcut, **tekrar etmiyorum**:

- Family-wise N (v5 kilidi): **264 test** (4 sibling × 66 aday).
- v7 yazılırsa N → **330**, Holm-Bonferroni eşiği `0.05/330 = 1.52×10⁻⁴` (264'tekinden **%14 daha sıkı**).
- Kalan eksenler (MI, copula tail, Kendall τ, regime-conditional ρ, capacity-disjoint volume) **v1-v4'ün doğrusal olmayan akrabaları** — Bayes prior çarpımı sonrası gerçek-edge posterior ≤ 0.05. **Marjinal istatistiksel değer ≤ 0** — değişmedi.
- v5 §12 yasağı hâlâ aktif (moratoryum **2026-08-25**'e kadar).

Yeni hiçbir veri yok. v7 hipotezinin yazılması = v6'nın yazılmasıyla aynı yanlış.

## 3. Curve-fit Self-Attack (Yapılmayan Hipotezin)

> "Aynı seed üzerinde 7 saatte 5 sibling, takip eden 6 saatte 2 ek abort doc → cron pompası p-hacking imzasıyla aynı kalıbı tekrar üretiyor. 7. sibling yazılması overfit-by-meta-design."

## 4. ⚠️ Eskalasyon: Cron Körlüğü → Severity: **MEDIUM**

v6'da severity **"low — protocol gap, no harm yet"** olarak işaretlendi. 3. tetikle bu yeniden değerlendirilmeli:

| Metric | v6 (1. abort) | v7 (2. abort) | Trend |
|---|---|---|---|
| Aynı seed cron tetik sayısı (24h) | 2 | 3 | ↑ %50 |
| Researcher zaman israfı (doc başı) | ~10 dk | ~10 dk | doğrusal birikiyor |
| Operasyonel risk | düşük | **orta** — abort doc trafiği inbox.jsonl'a gürültü pompalıyor | ↑ |
| Audit trail kirlenmesi | sınırlı | **belirgin** — 4. tetikte v8 olmamalı | ↑ |

**Severity yükseltme önerisi: low → medium.**

### 4.1 Researcher tarafı self-throttle (yeni kural)

Bu doc'tan itibaren **researcher tarafında self-throttle** uygulanır:

- Aynı seed için son 24 saatte ≥ 2 abort doc varsa → 3. tetikten itibaren **yeni doc YAZILMAZ**.
- Onun yerine: `memory/researcher/seed_abort_log.jsonl` dosyasına tek satır JSON append:
  ```
  {"ts":"2026-05-27T23:00:00Z","seed_hash":"vsa_climax_test+66shelf","cron_job":"researcher_propose_hypothesis","action":"skip","reason":"v5_moratorium_active","ref_doc":"researcher-20260527T230000-cross-strategy-companion-seed-abort-v7"}
  ```
- 4. tetikte v8 olmayacak. 5. tetikte v9 olmayacak. Sadece append-log satırı.
- Cooldown guard implement olunca seed_abort_log temizlenip post-mortem'a alınır.

**Bu bir tek-taraflı protokol değişikliği değil** — sadece researcher agent davranışı. ops_engineer cron guard çıkarana kadar geçerli "circuit breaker".

### 4.2 ops_engineer'a hâlâ açık talep

v6 §4'teki üç talep aynen geçerli:

1. `scheduler.researcher_propose_hypothesis` job'ına seed cooldown guard (son 7 günde aynı seed ≥ 3 → skip + INFO log).
2. v5 freeze doc'u `tags: [moratorium]` taraması (seed metni aktif moratoryuma eşleşiyorsa skip).
3. Incident doc — **severity: medium** (artırıldı), referanslar: [[2026-05-27-cross-strategy-companion-seed-abort-v5]] + [[2026-05-27-cross-strategy-companion-seed-abort-v6]] + bu doc.

## 5. RAG Şerhi

RAG retrieve: 0 hit (corpus boş, prompt'ta belirtildi). v5 freeze meta-protocol'deki Holm 1979 + Bailey-Lopez de Prado 2014 + Harvey-Liu 2014 + Romano-Wolf 2005 referansları hâlâ prosedürel temel.

## 6. Alternatif Seed (CEO'ya hatırlatma)

v6 §6'daki 5 alternatif seed listesi aynen geçerli:

1. Event-driven (FOMC/CPI/halving) entry filter for vsa_climax_test.
2. Funding-rate regime gate for v63 rsi2-extreme-fade companion (**farklı live bot, disjoint sibling familyası**).
3. Cross-exchange (Bybit ↔ Binance) basis arb feasibility.
4. Regime-conditional VSA gating (BTC dominance shift).
5. ML meta-labeler retry (Lopez de Prado triple barrier).

CEO bu seed listesinden birini seçip cron payload'unu güncellerse, bu seed-abort serisi de sona erer.

## 7. KPI Etkisi

| KPI | Davranış |
|---|---|
| Pre-register edilmiş hipotez sayısı (aylık) | sayılmıyor (seed-abort doc) |
| Terfi oranı | etkilenmiyor |
| Reddedilen hipotezlerin gerekçeli arşivlenmesi | **+1** ama bundan sonra append-log'a düşecek |
| Reproducibility | n/a |
| Iterate başarı oranı | etkilenmiyor |

## 8. Sonuç (tek satır)

> **vsa_climax_test + 66 aday raf** seed'i için companion arayışı moratoryumu hâlâ **2026-08-25**'e kadar aktif. 3. cron tetik geldi; bu **son** abort doc. Sonraki tetikler `seed_abort_log.jsonl`'a tek satırla geçer. ops_engineer için severity **low → medium**.

## 9. State Machine

- `status: REJECTED` — pre-test reject.
- `requested_review_from: [ops_engineer, ceo]` — guard implementation + severity onayı.
- `supersedes: null` — v5 freeze meta-protocol hâlâ aktif; bu doc onu **3. kez enforce** eder ve **circuit breaker** kuralı ekler.

---

**SOP-4 Karar:** RED (seed-abort, pre-test, **son abort doc**). Sebep: v5 freeze meta-protocol §12 hâlâ aktif, sayılar v6'dan beri değişmedi, cron körlüğü 3. tura çıktı → researcher self-throttle devreye alındı.
