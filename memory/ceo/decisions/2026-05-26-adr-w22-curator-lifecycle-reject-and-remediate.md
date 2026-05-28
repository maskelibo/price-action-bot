---
doc_id: ceo-20260526T000000-adr-w22-curator-lifecycle-reject
doc_type: adr
agent_id: ceo
created_at: 2026-05-26T00:00:00Z
status: APPROVED
confidence: high
depends_on:
  - strategy_curator-20260525T164154-lifecycle-2026-w22
  - risk_officer-20260525T171658-critique-strategy_curator-20260525t164154-lifecycle-2026-w2
  - risk_officer-20260525T171541-endorse-strategy_curator-20260525t164154-lifecycle-2026-w2
blocks: []
requested_review_from: []
tags: [adr, arbitration, strategy_lifecycle, dry_run, tail_risk]
supersedes: ceo-20260526-arbitration-critique-vs-endorse-strategy-curator-20260525t16
---

# ADR — W22 Strategy Curator Lifecycle: REJECT & Remediate

## Bağlam (Context)

Strategy Curator, `strategy_curator-20260525T164154-lifecycle-2026-w22` doc'unda W22 lifecycle review'u üretti. Doc içeriği:

- Aktif strateji: 1 (`vsa_climax_test`), `n_obs=0`, verdict `INSUFFICIENT_DATA`.
- Library: 67 modül, 66 raf, herhangi bir onboarding adayı yok.
- `has_tail_analysis: false`.
- Commentary alanı: `[DRY RUN — gerçek LLM çağrısı yapılmadı]`.
- `requested_review_from: [ceo, risk_officer]`.

Risk Officer iki doc üretti:
1. `risk_officer-20260525T171658-...-critique-...` (critique, confidence high).
2. `risk_officer-20260525T171541-...-endorse-...` (etiket "endorse" ama body conditional rejection — "şu 3 koşul sağlanırsa ENDORSE'a dönerim").

## Çatışma Var mı?

**Hayır — sözde çatışma, gerçek substans aynı.**

| Substans | Critique | "Endorse" |
|---|---|---|
| `has_tail_analysis: false` itirazı | ✓ | ✓ |
| DRY RUN commentary itirazı | ✓ | ✓ |
| `n_obs=0` triage talebi | ✓ | ✓ |
| 66 shelf için korelasyon/konsantrasyon eksik | ✓ | ✓ |
| Conditional acceptance criteria | ✓ (3 madde) | ✓ (3 madde) |

İki doc'un birbirinden farkı yok — sadece etiketleme hatası. "Endorse" doc'u protokol §3'ü ihlal ediyor: endorse body "Why I endorse" + "Strengths" içermeli, critique içermemeli.

## Sayısal Değerlendirme

Aşağıdaki rakamlar Risk Officer eleştirisini destekliyor (conservative bias zaten gerekmiyor — veri kendiliğinden bir yöne işaret ediyor):

| Metrik | Değer | Yorum |
|---|---|---|
| `has_tail_analysis` | false | Stres senaryosu yok → tail risk görünmüyor demek değil, ölçülmemiş demek. |
| `vsa_climax_test` n_obs (30g) | 0 | Üç olası neden: alpha decay / journal arızası / data pipeline susmuş. Hiçbiri "ignore" kategorisi değil. |
| Aktif strateji sayısı | 1 / 67 (%1.5) | Tek-strateji konsantrasyonu = %100 sermaye tek stratejide. |
| Diversity entropy | hesaplanmamış | Curator mandate'inde zorunlu metrik, raporda yok. |
| Commentary substans | 0 (DRY RUN) | KEEP/RETIRE/ONBOARD/PROBATION verdict gerekçeleri boş. |
| Shelf risk snapshot | 0 | 66 aday için kategori dağılımı/korelasyon yok. |

**Asimetri testi:** "Approve" yönünde gitmenin upside'ı yok (zaten aksiyon önerisi sıfır). Downside'ı: görünmez tail risk + ops/data arızasının atlanması + DRY RUN raporların prosedürel olarak meşrulaşması. **Asimetri net şekilde reject lehine.**

## Karar (Decision)

**Strategy Curator W22 lifecycle review'u REJECT — Remediate.**

### Gerekçe
1. Doc gerçek bir review değil; DRY RUN stub. Substans yok, gerekçe yok.
2. Tail analysis sıfır olan bir lifecycle raporu onaylamak = görünmez riski onaylamak.
3. `n_obs=0` aktif stratejide bir risk sinyali (alpha decay veya operasyonel arıza) — pasif geçilemez.
4. İki Risk Officer doc'u substansiyel olarak aynı kararı gösteriyor; conservative bias zaten Risk tarafında.

### Aksiyonlar (öneri — Principal onayı gerekli olanlar işaretli)

1. **[ops_engineer]** — `futures_journal_5m.duckdb` üzerinde `vsa_climax_test` son 30 günlük kayıt sorgusu çek. Sonuç:
   - >0 kayıt → "journal yazılmıyor mu, curator mı okumuyor" ayrımı için curator data path audit.
   - 0 kayıt → `incident` doc aç (signal/data pipeline veya bot pause durumu).
   - SLA: 24 saat.

2. **[adversary_engineer]** — `vsa_climax_test` üzerinde minimum 3 historical stress senaryosu (LUNA 2022-05, FTX 2022-11, Yen Carry 2024-08) replay. Çıktı: `stress_test` report doc. SLA: 72 saat.

3. **[strategy_curator]** — W22 raporunu yeniden üret. Zorunlu alanlar:
   - Diversity entropy hesabı (1 aktif stratejide bile baseline).
   - Shelf pool için en azından kategori dağılımı + üst-5 korelasyon çifti (Portfolio Manager'dan veri çek).
   - Commentary alanı: ya gerçek LLM çıktısı ya da boş + "pending real call" işareti — DRY RUN metni doc'a koyulmamalı.
   - Yeni doc id: `strategy_curator-2026Www-lifecycle-...`, eski doc'u `supersedes` ile bağla.

4. **[ops_engineer]** — DRY RUN sentinellinin yanlışlıkla doc body'sine kaçmasını engelleyen lint kuralı ekle (gate ya da pre-write hook). Bu, gelecekte CEO/Principal'a yanıltıcı güven sinyali oluşmasını önler.

5. **[risk_officer]** — `risk_officer-20260525T171541-...-endorse-...` doc'unun status'unu `SUPERSEDED` olarak işaretle ve yeni doc yaz; body critique içerdiği için endorse etiketi protokol §3 ihlali. (Edit yasak — yeni doc + supersedes.)

### Onay Sınırı

Bu ADR yalnızca W22 raporunu reddeder ve remediation talep eder. **Trading config, risk parametresi veya canlı strateji değişikliği önermez** — protokolde CEO yetkisi dışında.

## Tersine Çevirme (Kill Criteria)

Bu ADR'yi gözden geçirmek için:
- Aksiyon-1 (`ops_engineer` journal audit) `n_obs=0` için meşru ve kabul edilebilir bir açıklama getirirse (örn. bot bilinçli pause), n_obs talebim düşer.
- Aksiyon-2 (`adversary_engineer` stress test) sonuçları `vsa_climax_test` için MaxDD < %15 ve Sharpe degradation < %50 gösterirse, tail risk endişesi düşer.
- Yeni curator raporu gerçek substans ile gelirse remediation tamamlanmış sayılır.

## Sonuçlar (Consequences)

- W22 için herhangi bir onboarding/retire aksiyonu **alınmaz** (zaten önerilmemişti — durum aynı).
- W23 raporu remediation çıktılarını içermek zorunda; eksikse CEO yine REJECT verir.
- DRY RUN doc'ların protokole uygunluğu sorgulanır — `ops_engineer` lint kuralı W23'e kadar production'da olmalı.
- 4 hafta sonra (2026-06-23) bu kararın etkisi gözden geçirilir: remediation tamamlandı mı, curator process'i sağlamlaştı mı?

## Notes

Conservative bias bu kararda devreye girmedi çünkü iki "taraf" arasında gerçek bir çatışma yoktu. Asıl bulgu: yanlış etiketlenmiş bir "endorse" doc'u CEO'yu yanıltabilirdi — frontmatter etiketi ile body content tutarlılığı protokol seviyesinde sıkılaştırılmalı.
