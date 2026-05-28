---
agent: ceo
type: decision
date: 2026-05-26
status: proposed
---

# ADR: Arbitration: critique_vs_endorse_strategy_curator-20260525T164154-lifecycle-2026-w22

## Context
{'topic': 'critique_vs_endorse_strategy_curator-20260525T164154-lifecycle-2026-w22', 'original_doc_id': 'strategy_curator-20260525T164154-lifecycle-2026-w22', 'critique_paths': ['/Users/peyman/price-action-bot/reports/risk/risk_officer-20260525T171658-critique-strategy_curator-20260525t164154-lifecycle-2026-w2.md'], 'endorse_paths': ['/Users/peyman/price-action-bot/reports/risk/risk_officer-20260525T171541-endorse-strategy_curator-20260525t164154-lifecycle-2026-w2.md']}

## Options
Promote / Reject / Wait

## Decision
## Karar Özeti — W22 Curator Lifecycle Arbitrasyonu

**Bulgu:** Gerçek bir çatışma yok. Risk Officer'ın "endorse" etiketli doc'u substansiyel olarak critique ile aynı — body "şu 3 koşulda ENDORSE'a dönerim" diyor, yani şartlı reddediş. Protokol §3 ihlali (endorse body'si critique içeremez).

**Sayısal asimetri:** Original Curator doc'u DRY RUN stub — `has_tail_analysis: false`, `n_obs=0`, commentary boş, 66 shelf strateji için risk snapshot yok. "Approve" yönünde upside sıfır (zaten aksiyon önerisi yok); downside görünmez tail risk + olası ops/data arızası.

**Karar:** **REJECT & Remediate.** Conservative bias devreye bile girmedi — veri kendiliğinden Risk tarafına işaret ediyor.

**Aksiyonlar (öneri):**
1. `ops_engineer` → `futures_journal_5m.duckdb` üzerinde `vsa_climax_test` 30g audit (SLA 24h).
2. `adversary_engineer` → min 3 historical stress (LUNA/FTX/Yen Carry) replay (SLA 72h).
3. `strategy_curator` → W22'yi yeniden üret, diversity entropy + shelf korelasyon snapshot zorunlu, DRY RUN metin doc'a girmesin.
4. `ops_engineer` → DRY RUN sentinel'in doc body'sine kaçmasını engelleyen lint/gate kuralı ekle.
5. `risk_officer` → yanlış etiketli endorse doc'u SUPERSEDED işaretle, yeni doc yaz.

**Sınır:** Bu ADR sadece raporu reddedip remediation talep eder; trading config / risk parametresi değişikliği önermez.

ADR yazıldı: `memory/ceo/decisions/2026-05-26-adr-w22-curator-lifecycle-reject-and-remediate.md`. 4 hafta sonra (2026-06-23) revisit.

## Consequences
Re-evaluate in 4 weeks.

## Notes
