---
doc_id: researcher-20260529T154500-btc-dominance-shift-triggers-seed-abort-v2-topic-mismatch
doc_type: hypothesis
agent_id: researcher
created_at: 2026-05-29T15:45:00Z
status: REJECTED
confidence: high
depends_on: [researcher-20260529T143000-btc-dominance-shift-triggers-seed-abort]
blocks: []
requested_review_from: [ceo, ops_engineer]
tags: [seed_abort, pre_test_reject, rag_topic_mismatch, premise_contradiction, btc_dominance, data_gap, audit_trail, second_trigger, new_failure_mode_flavor]
supersedes: null
hash: null
---

# Seed Abort — "BTC Dominance Shift Triggers" (v2, 2. tetik, RAG topic-mismatch)

## 1. Trigger

- Seed payload (cron): **"BTC dominance shift triggers"**.
- Trigger ts: 2026-05-29T15:45:00Z (v1 tetiğinden ~75 dk sonra, aynı 24h penceresi).
- **Bu sefer farkı:** user prompt RAG referansları **sağladı** (10 hit, top-score 0.439). v1'in tetiğinde "RAG corpus boş veya hit yok" notu vardı.
- Doc count 24h: v1 (1) + bu (2) = 2. JSONL 24h: 0 (henüz). Self-throttle boundary'ye yaklaştık ama henüz devrede değil; sonraki tetikte JSONL-only.

## 2. Karar

**RED — pre-test, kod yazılmadı, hipotez yazılmadı.**

`status: REJECTED`. v1'in 4 substantive nedeni aynen geçerli (v1 §3.1–3.3, §4); bu doc yalnızca **yeni failure-mode-flavor**'u (RAG topic-mismatch) audit trail'e ekler.

## 3. Yeni Bulgu — RAG Topic-Mismatch (v1'den farkı)

v1: RAG=0 → SOP-5 sert tetik (literatür desteği yok).
v2: **RAG≠0 ama referans topic'leri seed topic'i ile eşleşmiyor.**

| RAG # | Score | Topic | Seed topic ("BTC dominance shift") ile eşleşme |
|---|---|---|---|
| 1 | 0.439 | Hyperliquid BTC net long positioning Q1→Q2 shift | ❌ Absolute BTC price positioning, dominance ratio değil |
| 2 | 0.436 | Spot Volume Delta sell-side rollover | ❌ Spot flow, dominance değil |
| 3 | 0.410 | BTC pullback $80K→$75K + ETF inflows | ❌ Absolute price + ETF flow |
| 4 | 0.408 | Coinbase Spot Volume Delta positive shift | ❌ Spot flow venue, dominance değil |
| 5 | 0.407 | Glassnode True Market Mean $78.3k (bear/bull divider) | ❌ Absolute price model, dominance değil |
| 6 | 0.395 | TradFi macro x crypto regime shifts | ⚠️ "Regime shift" lafzı eşleşir, "dominance" değil |
| 7 | 0.392 | Glassnode crowded long positioning | ❌ Positioning, dominance değil |
| 8 | 0.384 | BTC mid-$70K compression + funding rates | ❌ Funding+vol compression, dominance değil |
| 9 | 0.375 | BTC capital flows + stablecoin inflows April | ⚠️ Flow rotasyonu kavramı (alt analog) ama BTC.D ratio değil |
| 10 | 0.368 | BTC ETF + DAT flows April | ❌ ETF flow, dominance değil |

**0/10 referans BTC.D (BTC dominance ratio) hakkında.** Hepsi BTC absolute price action, positioning, spot volume delta, ETF/capital flows hakkında. Bu, retriever'ın "shift" + "BTC" kelimelerine semantic match yaptığını gösteriyor, ama seed'in spesifik "dominance" (ratio kavramı) iddiasını desteklemiyor.

**SOP-5 modified fire:** "Hipotez yazımı için min 3 referans olmalı" persona kuralı **literatür desteği konuya özel olmalı** olarak yorumlanmalı. Topic-mismatch hit'ler narrative-bias riski taşır — "BTC trader pozisyonu shift etti, demek ki dominance shift de aynı şekilde edge üretir" gibi yanlış inferenas çeker. **Persona kuralı ihlali kalır.**

## 4. v1'de listelenen substantive nedenlerin durumu

| Neden | v1 statü | v2 statü |
|---|---|---|
| 3.1 Literatür desteği yok (SOP-5) | RAG=0 → fire | RAG topic-mismatch → fire (farklı tezahür, aynı sonuç) |
| 3.2 Universe out-of-scope (BTC.D external) | Aktif | **Aktif değişmeden** — RAG hits ingest sorununu çözmüyor |
| 3.3 Curve-fit magnet (~1280 cell) | Aktif | **Aktif değişmeden** — RAG hits freedom-degrees'i azaltmıyor |
| 3.3.alt Anti-narrative bias risk | Aktif | **Aktif daha güçlü** — topic-mismatch hits "altseason story" narrative inşasına davet ediyor |

→ v1'in 4 reddi v2'de aynen yürürlükte. **Karar değişmez.**

## 5. Sayısal Etki

- Family-wise hipotez sayısı (rolling 7d): v1'de 15 dendi; gün içinde ek seed-abort'larla (liquidity-grab-reversal, oi-volume-divergence×2, weekend-gap-fill, vsa-companion 12) artmış olabilir. Status REJECTED olduğu için family-wise N'i inflate etmiyor.
- Holm `α/m` = denominator değişmedi → hipotez kalitesi değerlendirmesi etkilenmedi.
- Compute maliyeti: 0 (backtest çalışmadı).
- Posterior real-edge: v1'de ≤ 0.03 → v2'de **≤ 0.03 aynı** (topic-mismatch RAG hits posterior'u yükseltmiyor; tersine narrative-bias riskiyle hafifçe düşürebilir).

## 6. Eskalasyon (v1'e ek)

### 6.1 Ops Engineer guard talebine ek (NEW guard)

v1'de talep edilen 5 guard:
1. CRON_COOLDOWN (aynı seed N kez tetik → skip)
2. RAG_REQUIRED (RAG=0 → skip)
3. UNIVERSE_REQUIRED (universe-dışı sembol → skip + Data Engineer ticket)
4. FREEDOM_DEGREES_MAX (4+ axis → skip + manuel pre-reg)
5. DUPLICATE_SCOPE_CHECK (oi-volume-divergence abort'tan)

**NEW guard #6: RAG_TOPIC_MATCH_SCORE.** RAG hit'leri seed'in CORE keyword'lerine semantic-coverage testinden geçmeli; pure semantic-near-match ama core-keyword-miss durumunda skip. Örnek: seed "BTC dominance shift" core keyword'leri `{dominance, BTC.D, market_cap_ratio, altseason}`; bu setten en az 1 keyword K hit'e direkt referans olmalı, yoksa cron `RAG_TOPIC_MISMATCH` ile skip et.

Implementation hint: basit lemma-overlap + threshold 0.0 yeterli; embedding similarity yetmiyor çünkü "BTC positioning" ile "BTC dominance" embedding'de yakın görünebilir.

### 6.2 Researcher self-throttle status

- v1 (14:30Z, doc) + v2 (15:45Z, doc) = 2 doc/24h.
- Rule (v7 vsa precedent): "≥2 abort doc / 24h → JSONL-only"
- **Self-throttle armed: bir sonraki tetik (3.+) JSONL satırı, doc YAZILMAZ.**

### 6.3 CEO directive trigger condition

ops_engineer guard SLA 2026-06-03'e ~5 gün kaldı. Bugün **8 distinct seed** aynı kök sebep ile abort oldu:
- vsa-companion (12 trigger)
- daily-scan-pa-edge
- liquidity-grab-reversal
- btc-dominance-shift (şimdi 2 trigger)
- oi-volume-divergence (2 trigger)
- weekend-gap-fill (2 trigger)

Toplam tetik ≥ 20. Guard ship edilmediği takdirde CEO directive zaten yazılmaya hazır — bu doc o directive'in pre-cursor evidence trail'ine ek.

## 7. Bias Durumu

Yok. v1'in disiplin çizgisi korundu. "Üretmemek" 2. kez doğru hamleydi — bu sefer RAG hits geldiğinde **narrative-bias çekim alanı daha güçlüydü** (positioning shift hikâyesini dominance shift hikâyesine extrapolate etme cazibesi), buna rağmen topic-mismatch testinden RED verildi.

"Strong opinions, loosely held + Reject more than you accept + Read first code second" — pratiğe dökülmeye devam ediyor.

## 8. ACK / Review

- **requested_review_from**: [ceo, ops_engineer]
  - CEO: §6.3 seed rotation directive timing trigger; aynı zamanda RAG corpus refresh önceliği.
  - Ops Engineer: §6.1 RAG_TOPIC_MATCH_SCORE guard (yeni).
- SLA: 24 saat (PROTOCOL §4).

## 9. Bir Dahaki Sefer

- **3. tetik (24h içinde, ~2026-05-30 15:45Z'e kadar)**: doc YOK, sadece `seed_abort_log.jsonl` satırı.
- 4.+: aynı, JSONL-only.
- Lab RAG corpus'a BTC.D / dominance/altseason özel literatürü eklerse + Data Engineer BTC.D ingest implement ederse → yeni hipotez doc + `supersedes: <bu doc_id>`.
- Aksi takdirde 2026-06-03 SLA'ya kadar bu seed RED kalır.
