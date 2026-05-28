---
agent: ceo
type: decision
date: 2026-05-25
status: proposed
---

# ADR: Arbitration: critique_vs_endorse_strategy_curator-20260525T164154-lifecycle-2026-w22

## Context
{'topic': 'critique_vs_endorse_strategy_curator-20260525T164154-lifecycle-2026-w22', 'original_doc_id': 'strategy_curator-20260525T164154-lifecycle-2026-w22', 'critique_paths': ['/Users/peyman/price-action-bot/reports/risk/risk_officer-20260525T171658-critique-strategy_curator-20260525t164154-lifecycle-2026-w2.md'], 'endorse_paths': ['/Users/peyman/price-action-bot/reports/risk/risk_officer-20260525T171541-endorse-strategy_curator-20260525t164154-lifecycle-2026-w2.md']}

## Options
Promote / Reject / Wait

## Decision
Dosya yazma izni yok — kararı doğrudan brief formatında sunuyorum.

---

# ADR — Arbitration: Strategy Curator W22 Lifecycle Review

## TL;DR
Çatışma görünür, gerçekte yok. Risk Officer "endorse" etiketli dosyada da aslında critique yazmış (Claim/Disagreement/Evidence/Alternative formatında). Her iki doc aynı tarafta: Curator W22 raporu yetersiz. **Karar: REJECT Curator W22 + 3 paralel remediasyon + endorse dosyası protokol ihlali olarak flag.**

## 1. Veri (Sayısal Gerekçe)

### Curator W22 raporunun durumu
| Alan | Değer | Yorum |
|---|---|---|
| Active strategies | 1 | %100 tek-strateji konsantrasyonu |
| `vsa_climax_test` n_obs | **0** | Aktif strateji 0 gözlem üretmiş |
| Verdict | INSUFFICIENT_DATA | n_obs=0 < min=30 |
| `has_tail_analysis` | **false** | Stres senaryosu yok |
| Commentary | "[DRY RUN — gerçek LLM çağrısı yapılmadı]" | Substantif kısım boş |
| Diversity entropy | Hesaplanmamış | Curator görev tanımında zorunlu |
| Marginal Sharpe (66 shelf) | Hesaplanmamış | Onboarding sıralaması yok |

### İki Risk Officer dokümanı
| Boyut | "endorse" (171541, conf: med) | "critique" (171658, conf: high) |
|---|---|---|
| Etiketlenmiş tip | endorse | critique |
| İçerik yapısı | 5-alanlı critique (Disagreement, Evidence, …) | 5-alanlı critique |
| `has_tail_analysis: false` itirazı | ✓ | ✓ |
| DRY RUN commentary itirazı | ✓ | ✓ |
| n_obs=0 triage talebi | ✓ | ✓ |

**Sonuç:** "endorse" dosyası içerikte critique. Gerçek çatışma yok; PROTOCOL §3 ihlali (yanlış `doc_type` etiketi).

## 2. Karşı-Hipotez Testi
"Pasif geçmek de bir karardır; n_obs=0 → aksiyon yok, rapor kabul edilebilir." → **Reddediliyor.** `n_obs=0`'ın nedeni bilinmeden "pasif" denemez: (a) alpha decay (b) journal arızası (c) data pipeline susması — (b) ve (c) Ops Incident gerektirir. Shared Lesson: "Eksik tail analizi olan lifecycle review APPROVE etmek = görünmez riski onaylamak."

## 3. Asimetri
- **Reject downside:** 1 hafta onboarding gecikir. Aktif portföy zaten %100 tek strateji + 0 gözlem → getiri etkisi ~0.
- **Approve downside:** DRY RUN + tail-blind rapor baseline olur. Aylar sonra düzeltilemeyen düşük standart. Kalıcı süreç hasarı.
- **Conservative bias (SOP-4):** Risk her iki docda da REJECT. CEO know-how: "çatışmada Risk/Lab tarafına yaslan."

R:R asimetrik olarak REJECT lehine.

## 4. Karar

### 4.a Curator W22 raporu: **REJECTED**
PROPOSED → REJECTED. Üç koşul karşılanmadan yeni doc PROPOSED'a geçemez:
1. **Gerçek LLM modu zorunlu** — Commentary `[DRY RUN ...]` ibaresi içeremez. DRY RUN ise status DRAFT kalmalı.
2. **Tail analizi** — `has_tail_analysis: true`; en az 3 stres dönemi (LUNA 2022-05, FTX 2022-11, Yen Carry 2024-08).
3. **n_obs=0 triage** — `futures_journal_5m.duckdb` son 30 gün doğrulanmalı; (b) veya (c) → Ops Incident.

### 4.b Paralel görevlendirmeler

| Agent | Görev | SLA |
|---|---|---|
| `adversary_engineer` | `vsa_climax_test` kill-probe — LUNA/FTX/Yen Carry 3 stres | 48 saat |
| `ops_engineer` | `vsa_climax_test` son 30 gün gözlem triage; bulgu `incident`/`brief` | 24 saat |
| `portfolio_manager` | 66 shelf strategy kategori dağılımı + üst-5 korelasyon çifti | 72 saat |
| `strategy_curator` | Üç girdi geldikten sonra W22 yeniden üret (gerçek LLM modu) | bağımlı |

### 4.c Protokol ihlali
`risk_officer-20260525T171541-endorse-...` → PROTOCOL §3 ihlali. Aksiyon: `ops_engineer` `protocol_violation` tag'li incident açsın. İçerik critique olduğu için doc fiilen `...171658-critique-...` ile birleşmiş sayılır; "endorse" SUPERSEDED. Risk Officer için label disiplini uyarısı.

## 5. Kill Criteria (bu karar yanlışsa nasıl anlarız?)
- Adversary kill-probe `vsa_climax_test` için MaxDD < %10 + Sharpe degradation < %30 → tail-blind itirazı zayıflar (DRY RUN yasağı kalır).
- Ops triage `n_obs=0` = "kasıtlı pause, beklenen" konfirme ederse → o kalem düşer; tail + DRY RUN gerekçeleri yeterli.

## 6. Onaya Sunulan (Principal)
- [ ] Bu ADR'nin APPROVED → ACTIVE geçişi
- [ ] `endorse` dosyasının SUPERSEDED işaretlenmesi (sadece Principal yetkisi)
- [ ] **Yapısal düzeltme önerisi:** Orchestrator'a DRY RUN gate'i — DRY RUN commentary içeren doc otomatik DRAFT, asla PROPOSED yayını yok

## 7. Revisit
4 hafta sonra (2026-06-22): Curator W22 yeniden üretildi mi? Kill-probe geldi mi? DRY RUN gate eklendi mi?

---

**Özet:** Risk Officer aslında oybirliğiyle REJECT diyor (etiket karışıklığı dışında). Conservative bias zaten Risk tarafında — çatışma yok, ittifak var. Curator W22 reddedildi, üç paralel remediasyon ve bir protokol ihlali incident'i öneriliyor. Asıl yapısal sorun: orchestrator DRY RUN doc'ları PROPOSED olarak yayımlıyor — bu durdurulmalı.

## Consequences
Re-evaluate in 4 weeks.

## Notes
