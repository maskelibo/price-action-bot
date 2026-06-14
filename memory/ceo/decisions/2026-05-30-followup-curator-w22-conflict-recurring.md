---
doc_id: ceo-20260530T080000-followup-curator-w22-conflict-recurring
doc_type: adr
agent_id: ceo
created_at: 2026-05-30T08:00:00Z
status: APPROVED
confidence: high
depends_on:
  - strategy_curator-20260525T164154-lifecycle-2026-w22
  - risk_officer-20260525T171541-endorse-strategy_curator-20260525t164154-lifecycle-2026-w2
  - risk_officer-20260525T171658-critique-strategy_curator-20260525t164154-lifecycle-2026-w2
  - ceo-20260529-arbitration-critique-vs-endorse-strategy-curator-20260525t16
  - ceo-20260528-arbitration-critique-vs-endorse-strategy-curator-20260525t16
  - ceo-20260527-arbitration-critique-vs-endorse-strategy-curator-20260525t16
  - ceo-20260527-adr-w22-curator-remediation-sla-breach
  - ceo-20260526-arbitration-critique-vs-endorse-strategy-curator-20260525t16
blocks: []
requested_review_from: [human_principal]
tags: [arbitrate, follow-up, systemic-bug, conflict-resolver, sla-breach, principal_escalation]
supersedes: null
---

# CEO Follow-up — Tekrar Eden W22 Curator Çatışması (5. tetikleme)

## TL;DR
Bu çatışma 2026-05-26'dan beri **her gün** SOP-4 ile tetikleniyor; orijinal arbitrate (2026-05-29 ADR) net karar verdi (REJECT + 4 koşul) ama doc statüleri ve resolver davranışı güncellenmedi. **Yeni sayısal bilgi yok.** Yeni ADR üretmiyorum; mevcut ADR'yi yeniden onaylıyorum ve **sistemik bug eskalasyonu** açıyorum.

## 1. Tekrarlama Kanıtı

| Tarih | ADR / Doc | Yeni içerik? |
|---|---|---|
| 2026-05-26 | arbitration-critique-vs-endorse-strategy-curator-... | İlk karar |
| 2026-05-27 | arbitration + adr-w22-curator-remediation-sla-breach | SLA aşımı tespiti |
| 2026-05-28 | arbitration-critique-vs-endorse-... | Tekrar, içerik aynı |
| 2026-05-29 | arbitration-critique-vs-endorse-... | Tam sayısal arbitrate (7-gate tablosu, kill criteria) |
| **2026-05-30** | **(bu doc)** | **Yeni veri yok — sistemik bug** |

5 günlük arbitrate, **0 status değişimi** (Curator doc hâlâ PROPOSED, critique/endorse hâlâ PROPOSED). Bu, conflict resolver'ın "ADR yazıldı mı" değil "doc status REVIEWED/APPROVED/REJECTED oldu mu" kontrol etmesi gerektiğini gösteriyor.

## 2. Mevcut Karar (2026-05-29 ADR'sini ratify ediyorum)

Orijinal arbitrate (`memory/ceo/decisions/2026-05-29-arbitration-critique-vs-endorse-strategy-curator-20260525t16.md`) geçerli:

- `strategy_curator-20260525T164154-lifecycle-2026-w22` → **REJECTED.**
- 4 remediation koşulu sabit:
  1. Ops_engineer triage — `vsa_climax_test` n_obs=0 root cause.
  2. Adversary_engineer kill-probe — 3 stres senaryosu (LUNA / FTX / Yen Carry).
  3. Curator real-LLM rerun (DRY RUN flag kapalı).
  4. Diversity + 66-shelf snapshot.

## 3. Conservative Bias Kontrolü (her gün yeniden doğruluyorum)

| Soru | Cevap |
|---|---|
| Risk Officer endorse + critique split var mı? | Hayır — etiket bug; iki doc da disagree pozisyonunda. |
| Curator raporu substantif mi? | Hayır — 7-gate'in 5'i fail (tail false, n_obs=0, DRY RUN, diversity hesaplanmamış, shelf snapshot yok). |
| REJECT'in maliyeti vs APPROVE'un maliyeti? | APPROVE = precedent bug (her lifecycle review boşalır). REJECT = 1 hafta gecikme. R:R 2.5+ REJECT tarafında. |
| Yeni veri/argüman geldi mi? | **Hayır.** Yeni Curator/Ops/Adversary doc yok (Curator dizininde 25 Mayıs'tan sonra W22 supersede yazılmamış). |

Karar değişmez. Conservative bias zaten REJECT'i destekliyor.

## 4. Sistemik Bug — Acil Eskalasyon

Bu çatışmanın tekrarlaması iki yapısal sorunu gösteriyor:

**Bug-1: doc_type etiket karışıklığı.** `risk_officer-20260525T171541-endorse-...` dosya adında "endorse" geçiyor, frontmatter `doc_type: endorse`, ama gövde tam critique formatı (Claim/Disagreement/Evidence/Alternative + "APPROVE etmek görünmez riski onaylamak demektir" cümlesi). Conflict resolver bunu critique-vs-endorse split sanıyor → her gün CEO'yu çağırıyor.

**Bug-2: ADR sonrası status mutation eksik.** ADR `REJECTED` öneriyor ama doc statüsünü değiştirecek bir adım yok. Append-only protokol (§8) edit yasakladığı için ADR yalnız öneri — orijinal doc'un `agent_id` sahibi (strategy_curator) `SUPERSEDED` yapmalı; yapmadığı için pending kuyruğunda kalıyor.

### Önerilen düzeltmeler (Principal onayına)

| # | Düzeltme | Sahip | SLA |
|---|---|---|---|
| F-1 | Conflict resolver "doc status APPROVED/REJECTED/SUPERSEDED ise tetiklenme" guard'ı eklemeli | ops_engineer | 48h |
| F-2 | `doc_type` heuristic validator: gövdede `## Disagreement` varsa frontmatter `endorse` ise reddet/uyarı | ops_engineer | 72h |
| F-3 | ADR `directive` blokları için "owner agent statüyü değiştirsin" otomatik task açma | ops_engineer + ceo | 1 hafta |
| F-4 | strategy_curator W22 doc'unu `SUPERSEDED` durumuna geçir (manuel — Principal/Curator) | strategy_curator | 24h |

## 5. Asimetri (sistemik bug için)

- Düzeltmeme maliyeti: her gün CEO LLM çağrısı (bugün dahil **5 kez** aynı arbitrate). Token bütçesi israfı + gerçek konularda CEO dikkati azalır + audit_ops bunu "alarm SNR" bulgusu olarak flag'ler.
- Düzeltme maliyeti: ops_engineer 1-2 günlük iş.

R:R çok yüksek düzeltme tarafında.

## 6. Onaya Sunulan (human_principal)

- [ ] **F-1..F-4 düzeltme paketi onaylanıyor mu?** (audit_ops Seed CT-OPS-02 "silent cron / loop noise" kapsamına girer.)
- [ ] **Curator W22 dokümanını manuel olarak SUPERSEDED'a çekme yetkisi:** Bot kendisi statüsünü değiştirmediği için bir kez Principal/Curator manuel intervention gerekli. Onay verilirse strategy_curator agent'a "yeni W22 doc + supersede" görevi yazılır.

## 7. Bu Doc'un Status'u

Bu ADR `APPROVED` olarak işaretlendi (CEO arbitrate yetkisi, protocol §5). Conflict resolver bunu gördüğünde aynı orijinal `depends_on` için yeni arbitrate tetiklememeli. Eğer **yeni** critique/endorse doc gelirse (yeni `created_at`) o zaman yeni arbitrate açılır.

---

**Sonraki adım:** Principal onayı (F-1..F-4) → ops_engineer'a sistemik bug task. Yeni Curator W22 üretilene kadar `vsa_climax_test` capital allocation %0 olarak işaretlenmeli (zaten n_obs=0 olduğu için pratik etki yok ama doc'a yazmak hesap verebilirlik için gerekli).
