---
agent: ceo
type: decision
date: 2026-05-29
status: proposed
---

# ADR: Arbitration: critique_vs_endorse_strategy_curator-20260525T164154-lifecycle-2026-w22

## Context
{'topic': 'critique_vs_endorse_strategy_curator-20260525T164154-lifecycle-2026-w22', 'original_doc_id': 'strategy_curator-20260525T164154-lifecycle-2026-w22', 'critique_paths': ['/Users/peyman/price-action-bot/reports/risk/risk_officer-20260525T171658-critique-strategy_curator-20260525t164154-lifecycle-2026-w2.md'], 'endorse_paths': ['/Users/peyman/price-action-bot/reports/risk/risk_officer-20260525T171541-endorse-strategy_curator-20260525t164154-lifecycle-2026-w2.md']}

## Options
Promote / Reject / Wait

## Decision
İki Risk Officer dokümanını da okudum. Sayısal değerlendirme aşağıda.

---

# CEO Arbitrate — Conflict on `strategy_curator-20260525T164154-lifecycle-2026-w22`

## TL;DR
Bu **gerçek bir çatışma değil.** "Endorse" etiketli doc içerik olarak critique formatında — gövdesi tam da critique gibi yazılmış (Claim/Disagreement/Evidence/Alternative). İki Risk Officer çıktısı da aynı dört kalemde birleşiyor. Çözüm: **Curator dokümanını REVIEWED → REJECTED yap, yeniden düzenlettir.** Conservative bias: Risk Officer tarafı.

## 1. Sayısal Gerekçe (Curator raporundan)

| Metrik | Değer | Eşik / Beklenen | Durum |
|---|---|---|---|
| Active strategies | 1 | ≥1 | ✓ |
| Library coverage (active/total) | 1/67 = **%1.5** | — | ⚠️ konsantrasyon |
| `vsa_climax_test` n_obs | **0** | ≥30 | ✗ |
| Sharpe slope | NaN | finite | ✗ |
| `has_tail_analysis` | **false** | true (≥3 stres dönemi) | ✗ |
| Commentary | **DRY RUN — LLM çağrısı yok** | gerçek analiz | ✗ |
| Diversity entropy | hesaplanmamış | hesaplanmalı | ✗ |
| Shelf pool (66) risk snapshot | yok | en az kategori + top-5 corr | ✗ |

7 gate'ten 5'i fail, 1'i uyarı, 1'i ✓. Net karar: rapor substantif değil.

## 2. İki Risk Doc'unun Birleşim Tablosu

| Mesele | Endorse (17:15) | Critique (17:16) | Birleşim |
|---|---|---|---|
| `has_tail_analysis: false` | flagged | flagged | **konsensüs** |
| DRY RUN commentary | flagged | flagged | **konsensüs** |
| n_obs=0 root-cause analizi | flagged | flagged | **konsensüs** |
| %100 tek-strateji konsantrasyonu / diversity | flagged | flagged | **konsensüs** |
| 66-shelf risk snapshot | flagged | flagged | **konsensüs** |
| Confidence | med | high | yüksek tarafa yaslan |

**Gözlem:** "Endorse" filename'inde "endorse" yazıyor; gövde tam critique yapısı. Bu büyük olasılıkla agent emit aşamasında bir etiketleme hatası. İçerikten konuşursak iki doc da `disagree` pozisyonunda. Yani **endorse vs critique split yok** — Risk Officer sinyali tek yönlü.

## 3. Karşı-Hipotez

> "Aktif strateji n_obs=0 ise zaten risk üretmiyor, dolayısıyla tail analysis gereksiz; rapor 'insufficient data' verip geçebilir."

Reddediyorum, üç sebeple:
1. Eğer strateji canlıda **çalışıyor** ve n_obs=0 ise, bu data/ops arızası olasılığı içerir (Risk Officer §2). Bu en az Ops Incident değerinde.
2. Eğer strateji **fiilen pause** ise dokümanda açıkça yazmalı; CEO/Principal "1 aktif strateji" sayısını yanıltıcı okuyor.
3. 66 shelf modülü için onboarding/diversification analizi yapılmaması Curator'ın **görev tanımının kalbi.** "Aktif yok dolayısıyla analiz yok" = role abdication.

## 4. Asimetri

- Reddetme maliyeti: 1 hafta gecikme, Curator + Ops + Adversary Engineer'a iş.
- Onaylama maliyeti: görünmez tail risk + DRY RUN onayını precedent yapmak → bundan sonraki her lifecycle review'un boşalması.

R:R **2.5+** REJECT tarafında. Onaylama, sistem bütünlüğüne kalıcı zarar.

## 5. Kill Criteria (kararımın yanlış olduğunu nasıl anlarım)

- Ops_engineer triage'ı n_obs=0'ı `vsa_climax_test`'in **kasıtlı pause** olduğuna bağlarsa ve Curator bunu doc'a eklerse, **kalan eleştiriler hafifler** (ama tail + diversity hâlâ gerekli).
- Curator'ın DRY RUN'ı runtime bug olduğu kanıtlanır ve commentary alanı gerçek LLM çıktısıyla yeniden üretilirse → REJECT yumuşatılır.

## 6. Karar

**`strategy_curator-20260525T164154-lifecycle-2026-w22` → REVIEWED → REJECTED.** Yeni W22 dokümanı `supersedes` ile yeniden yazılmalı. Aşağıdaki dört madde tamamlanmadan APPROVED'a geçemez:

1. **Ops_engineer triage** (24h): `futures_journal_5m.duckdb` üzerinde `vsa_climax_test` son 30g kayıt sayımı + nedeni belgelenmiş (pause / signal yok / journal yazmıyor). `incident` veya `brief` doc.
2. **Adversary_engineer kill-probe** (72h): `vsa_climax_test` için en az 3 stres senaryosu (LUNA 2022-05, FTX 2022-11, Yen Carry 2024-08). Eşik: MaxDD < %15 ve Sharpe degradation < %50 → pass; aksi PROBATION.
3. **Curator real-LLM rerun**: DRY RUN flag kapatılarak commentary yeniden üretilmeli; eksikse alan `pending` olarak işaretlenip doc `DRAFT` kalır.
4. **Diversity + shelf snapshot**: 66 shelf için kategori dağılımı + top-5 korelasyon çifti + en yüksek marginal-Sharpe adayı (Portfolio Manager ile koordineli).

## 7. İnsan Principal Onayına Sunulan

- [ ] Bu arbitrate kararı (REJECT + 4 koşul) onaylanıyor mu? Onaylanırsa Curator W22 yeniden açılır, 4-hafta sonra (`2026-06-22 W26`) bu ADR revisit edilir.
- [ ] "Endorse vs critique" etiket karışıklığı sistemik bir bug olabilir — `ops_engineer`'a protokol §1 frontmatter `doc_type` doğrulayıcısı kurma direktifi verilsin mi?

---

**Sonraki adım:** Bu ADR `reports/ceo/` altına yazılmalı + critique/endorse doc'ları `supersedes` ile bu ADR'ye bağlanmalı (protocol §5). Karar verilirse o yazma adımını ben atarım.

## Consequences
Re-evaluate in 4 weeks.

## Notes
