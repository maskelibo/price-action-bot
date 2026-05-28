---
doc_id: ceo-20260527T230200-adr-w22-curator-remediation-sla-breach
doc_type: adr
agent_id: ceo
created_at: 2026-05-27T23:02:00Z
status: APPROVED
confidence: high
depends_on:
  - strategy_curator-20260525T164154-lifecycle-2026-w22
  - strategy_curator-20260526T174243-lifecycle-2026-w22
  - risk_officer-20260525T171658-critique-strategy_curator-20260525t164154-lifecycle-2026-w2
  - risk_officer-20260525T171541-endorse-strategy_curator-20260525t164154-lifecycle-2026-w2
  - ceo-20260526T000000-adr-w22-curator-lifecycle-reject
blocks: []
requested_review_from: []
tags: [adr, arbitration, strategy_lifecycle, dry_run, sla_breach, escalation]
supersedes: ceo-20260526T000000-adr-w22-curator-lifecycle-reject
---

# ADR — W22 Strategy Curator Lifecycle: SLA Breach + Escalate

## Bağlam (Context)

Aynı çatışma (`critique_vs_endorse_strategy_curator-20260525T164154-lifecycle-2026-w22`) üçüncü kez arbitrate çağrısı olarak geldi. 2026-05-26 tarihli ADR (`ceo-20260526T000000-...-reject`) **REJECT & Remediate** kararı vermişti ve şu aksiyonları talep etmişti:

1. ops_engineer → `futures_journal_5m.duckdb` üzerinde `vsa_climax_test` 30g audit (SLA 24h, bitiş ~2026-05-27 00:00 UTC).
2. adversary_engineer → 3 historical stress (LUNA/FTX/Yen Carry) replay (SLA 72h, bitiş ~2026-05-29 00:00 UTC).
3. strategy_curator → W22 raporunu gerçek substansla yeniden üret (DRY RUN sentinel doc'a girmesin, diversity entropy + shelf korelasyon zorunlu).
4. ops_engineer → DRY RUN sentinel lint/gate kuralı.
5. risk_officer → yanlış etiketli "endorse" doc'u SUPERSEDED işaretle.

## Remediation Durumu (2026-05-27 23:00 UTC itibarıyla)

| Aksiyon | SLA | Durum | Kanıt |
|---|---|---|---|
| ops `vsa_climax_test` 30g journal audit | 24h ✗ AŞILDI | YAPILMADI | `reports/ops/` altında sadece `token-report-*` doc'ları var; `vsa_climax_test` / `journal-audit` doc'u yok. |
| adversary stress (LUNA/FTX/Yen Carry) | 72h (henüz aktif) | YAPILMADI | `reports/adversary/` altında 2026-05-25→26 arası 30+ stress doc var ama hepsi `futures5m` / `futures15m` üzerinde; `vsa_climax_test` adlı hedef hiç yok. |
| curator W22 yeniden üret | implicit | KISMEN — same stub | `strategy_curator-20260526T174243-lifecycle-2026-w22`: `n_obs` 0→3 yükseldi ama commentary hala `[DRY RUN — gerçek LLM çağrısı yapılmadı]`. Diversity entropy yok, shelf korelasyon yok, tail analysis yok. |
| DRY RUN lint/gate | implicit | YAPILMADI | Bir sonraki curator raporunda da DRY RUN sentinel doc body'sinde. |
| risk_officer endorse SUPERSEDED | implicit | YAPILMADI | Endorse doc hala `status: PROPOSED`. |

**Net:** 5 aksiyonun 5'i de yapılmamış. 24h SLA breach kesin (ops). 72h aktif. Lint/curator aksiyonları kanıt üretmemiş.

## Sayısal Yeniden Değerlendirme

Yeni curator raporu (2026-05-26T17:42) önceki ile karşılaştırma:

| Metrik | 2026-05-25 doc | 2026-05-26 doc | Δ |
|---|---|---|---|
| `n_obs` | 0 | 3 | +3 (hala min=30 altında) |
| Mean Sharpe | nan | nan | — |
| Verdict | INSUFFICIENT_DATA | INSUFFICIENT_DATA | — |
| Commentary substans | DRY RUN | DRY RUN | — |
| Diversity entropy | yok | yok | — |
| Shelf korelasyon | yok | yok | — |
| Tail analysis | yok | yok | — |

Tek değişiklik `n_obs` 0→3. Bu sıfırdan iyi (ops/data pipeline tamamen ölü değil) ama hâlâ `INSUFFICIENT_DATA` eşiğinin altında ve hâlâ alpha decay / signal frequency sorunu açıklanmamış.

## Karar (Decision)

**Önceki ADR (REJECT & Remediate) yürürlükte kalır — bu ADR onu supersedes ile yenilemekten çok ESCALATE eder.**

### Eskalasyon

1. **[human_principal — onay/aksiyon gerekli]** — SLA breach bildirimi: ops_engineer 24h audit aksiyonunu kaçırdı. Otomatik orchestrator'ın CEO arbitrate'i her gün tetiklemesi, gerçek remediation olmadan aynı conflict'i çevrime sokuyor. Principal eylemleri:
   - (a) Ops/Curator/Adversary agent'larının inbox'larında bu ADR'ye karşılık gelen "in-flight job" var mı kontrol et.
   - (b) Job yoksa elle tetikle veya scheduler'a inject et.
   - (c) Job varsa neden çıktı üretmediğini incele (LLM çağrısı başarısız mı, gate mi tıkıyor, dry-run modu mu aktif).

2. **[ops_engineer — tekrar talep, sertleştirilmiş]** — `futures_journal_5m.duckdb` SELECT COUNT(*) WHERE strategy='vsa_climax_test' AND ts > now()-30d. Çıktı: `incident` veya `brief` doc. **Yeni SLA: 6 saat (Risk Officer SLA seviyesi).**

3. **[strategy_curator — DRY RUN moduna karşı]** — Curator'ın LLM çağrısının neden yapılmadığını ops_engineer ile birlikte audit et. Olası nedenler:
   - (a) Cost guard token bütçesini kesiyor — `ops_engineer-*-token-report-*` raporlarına bak.
   - (b) Curator orchestrator'ı dry-run flag ile çalışıyor.
   - (c) LLM API erişim hatası loglanmamış.
   Bu üçünden hangisi olduğu bilinene kadar W23 lifecycle raporu da aynı stub'la gelecek.

4. **[risk_officer]** — Yanlış etiketli endorse doc'u (`risk_officer-20260525T171541-...`) SUPERSEDED işaretle. Bu yapılmadığı sürece orchestrator `_check_conflicts()` her gün CEO'yu aynı yapay çatışma için tetikleyecek. **Bu en kolay aksiyon; öncelikli.**

5. **[orchestrator-level]** — `_check_conflicts()` aynı `original_doc_id` için 24h içinde ikinci kez CEO arbitrate çağırmamalı (idempotency). Aksi takdirde her gün gereksiz CEO doc enflasyonu olur. Bu, `ops_engineer`'a config önerisi olarak gider.

### Onay Sınırı

CEO konfig veya kod yazmaz; yalnızca öneri üretir. Aksiyon 1 (Principal eskalasyonu) ve aksiyon 5 (orchestrator idempotency) **Principal onayı** gerektirir.

## Tersine Çevirme (Kill Criteria)

- Ops audit gelirse + curator gerçek substansla yeniden raporlarsa + risk_officer endorse SUPERSEDED işaretlerse → bu ADR `COMPLETED` olur.
- Bir hafta içinde (2026-06-03'e kadar) hiçbir aksiyon gelmezse → W23 raporu için CEO `directive` yazıp curator'ı tamamen `PAUSE` etmeyi önerir; gereksiz stub raporlar üretmektense susmak daha dürüst.

## Sonuçlar (Consequences)

- Aynı çatışma 4. kez gelirse otomatik bir `incident` doc tetiklensin (orchestrator önerisi).
- W22 için herhangi bir trading aksiyonu zaten yoktu, durum değişmedi.
- DRY RUN curator raporlarının protokol gereği `status: DRAFT` veya `confidence: low` olarak işaretlenmesi gerekiyor; `confidence: med` ile yayınlanması yanıltıcı.
- 2026-06-03 revisit; remediation yoksa curator agent'ı duraklatma önerisi Principal'a sunulacak.

## Telegram Özeti (Principal'a CRIT-soft push)

> URGENT-soft: W22 curator çatışması 3. kez arbitrate çağrıldı. Önceki ADR'nin (2026-05-26) 5 aksiyonundan 0'ı yapılmadı; ops 24h SLA breach. Curator raporu hala DRY RUN. En kolay düzeltme: risk_officer'ın endorse doc'unu SUPERSEDED işaretlemek — bu yapılmadığı sürece orchestrator her gün CEO'yu tetikliyor. Detay: `memory/ceo/decisions/2026-05-27-adr-w22-curator-remediation-sla-breach.md`.

## Notes

Asıl problem strateji değil **prosedürel**: yapay çatışma (mislabeled endorse) + aksiyonsuz remediation + idempotent olmayan orchestrator = CEO context kirliliği. Trading riski sıfır (zaten aksiyon önerilmemiş), operasyonel/güven riski yüksek (DRY RUN raporları meşrulaşıyor görüntüsü).
