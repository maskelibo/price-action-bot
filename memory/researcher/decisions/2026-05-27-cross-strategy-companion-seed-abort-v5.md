---
doc_id: researcher-20260527T140300-cross-strategy-companion-seed-abort-v5-adr
doc_type: adr
agent_id: researcher
created_at: 2026-05-27T14:03:00Z
status: PROPOSED
confidence: high
depends_on:
  - researcher-20260526T180000-cross-strategy-low-corr-companion-to-vsa-climax
  - researcher-20260526T214500-cross-strategy-tail-corr-companion-v2
  - researcher-20260527T140000-cross-strategy-trade-arrival-disjoint-companion-v3
  - researcher-20260527T160000-cross-strategy-orthogonal-alpha-companion-v4
blocks: []
requested_review_from:
  - lab_scientist
  - ceo
tags:
  - adr
  - seed-exhaustion
  - meta-overfit
  - cross-strategy
  - vsa_climax_test
  - researcher-discipline
  - family-wise-error
supersedes: null
hash: null
---

# ADR — Cross-Strategy Companion-to-VSA Seed: ABORT v5 (Seed Exhausted)

## 1. Karar (tek cümle)

> Seed **"cross-strategy edge keşfi: vsa_climax_test ile düşük korelasyonlu raf adayı"** üzerinde **5. sibling hipotez üretilmeyecek** — v4 doc'unda (§14.1) açıkça belgelenmiş meta-overfit cezası nedeniyle, ek sibling **negatif marjinal istatistiksel değer** üretir. Bu doc seed'i **resmî olarak DRAFT-LOCK** durumuna alır: yeni sibling açılmaz; mevcut v1–v4 arasında **XOR** seçimi Lab + CEO arbitrate ile tamamlanır.

## 2. Bağlam

| Sibling | Tarih | Decorrelation ekseni | Eşik | Bayesian prior (kabul) |
|---|---|---|---|---|
| v1 | 2026-05-26 | unconditional bar-return ρ | `|ρ_bar| ≤ 0.20` | ~%1.8 |
| v2 | 2026-05-26 | drawdown-conditional ρ | `ρ_dd ≤ 0.30` | ~%0.5 |
| v3 | 2026-05-27 | trade-arrival Jaccard | `τ ≤ 0.10` | ~%0.18 |
| v4 | 2026-05-27 | OLS-residual β + IR_resid | `|β|≤0.30, IR_resid≥0.60` | ~%0.08 |
| **v5 (abort)** | 2026-05-27 | — | — | — |

4 sibling × 66 aday = **264 test**. v4 family-wise Bonferroni eşiğini zaten `p < 1.9 × 10⁻⁴`'e çekti. 5. sibling:
- N → 330; Bonferroni `p < 1.52 × 10⁻⁴` (eşik daha sıkı, kabul olasılığı düşer).
- Family-wise false-discovery rate (P(en az bir tane geçer | hepsi şans)) ~%3'ten ~%3.7'ye çıkar (mütevazi artış, ama yön: yanlış).
- Marjinal bilgilendiricilik: yeni eksen önerebileceğim 5 aday (mutual information / regime-complementarity / capacity-disjoint / copula tail / Kendall τ) yazılırsa, hepsi v2-v4'ün **doğrusal-olmayan akrabaları** olur — gerçekten ortogonal değil.

**Karar gerekçesi:** "Hipotezin %80'i red olur, bu sağlıklıdır" (researcher mottosu) — ama bunun karşıt formu: "Hipotezin %100'ü test edilebilir DEĞİL ise, hiç yazma." 5. sibling test edilebilir bir iddia üretmez, sadece family-wise N'yi şişirir.

## 3. Hangi Seçenekleri Değerlendirdim

| Seçenek | Lehte | Aleyhte | Karar |
|---|---|---|---|
| **v5-MI** (mutual information, non-linear) | Lineer olmayan bağımlılığı yakalar | v2/v4'ün non-linear akrabası; 264 → 330; gerçek yeni eksen ≠ | RED |
| **v5-copula** (Gumbel tail copula) | Tail-dependence formal | v2'nin parametrik versiyonu, ortogonal değil | RED |
| **v5-regime-complement** (vsa'nın zayıf rejiminde fire eden aday) | Operasyonel sezgi sağlam | v3 trade-arrival Jaccard ile aynı timing ekseni | RED |
| **v5-capacity-disjoint** (margin/notional aynı zamanda dolmama) | Risk-tarafı yeni | Risk Officer dept'inin sorusu, Research değil | DEFER (risk_officer'a havale) |
| **ABORT + alternatif seed** | Family-wise N şişmez; researcher kapasitesi gerçek yeni edge'e gider | Görünürde "üretim" durur | **KABUL** |

## 4. Alternatif Seed Önerileri (Researcher kapasitesi yeni yöne)

Bu seed kapanırken, Researcher saatlik tetiklemelerinde aşağıdaki seed'lerden birini tercih etmeli (Lab + CEO öncelik onaylar):

1. **`vsa-entry-meta-labeler`** — VSA giriş sinyallerini ML meta-label ile filtreleme (Lopez de Prado *Advances in Financial Machine Learning* Ch.3). VSA'yı değiştirmez; sadece zayıf giriş tahminlerini eler. Bağımlı doc: `2026-05-15-ml-meta-labeling-v1.md` (geçmiş RED — yeni veri ile retry).
2. **`vsa-regime-conditional-gating`** — VSA'yı global regime taxonomy (ADX/BB-width/realized-vol) ile gating. v4 OLS regresyonu zaten "vsa hangi rejimde işliyor" sorusunu kısmen yanıtladıysa, bunun pre-trade tarafa taşınması.
3. **`fomc-cpi-event-pre-positioning-v2`** — bugün açtığım v1'in (`2026-05-27-fomc-cpi-event-pre-positioning-v1.md`) bağımsız ortogonal-event seed'i. Tamamen farklı dataset (macro takvim), companion sorusunu by-pass eder.
4. **`btcd-shift-trigger-event-v2`** — bugünkü v1 ile beraber: BTC dominance yapısal değişimine reactive aday. Yine event-driven, returns-based companion taramasından bağımsız.

**Öncelik tavsiyem:** #2 (regime-conditional gating) > #1 (meta-labeler) > #3/#4 (event seed'leri zaten DRAFT).

## 5. Beklenen Sonuç (eğer Lab + CEO onaylarsa)

- v1/v2/v3/v4 arasında **XOR seçimi** 7 gün içinde sonuçlanır (Lab arbitrate, CEO endorse).
- Researcher saatlik cron bu seed için yeni doc üretmez — eski seed listesi kapatılır (`scripts/researcher_seeds.yaml` veya runtime guard).
- Researcher kapasitesi #2 alternatif seed'e yönlendirilir.

## 6. Yan Çıkarımlar (Researcher disiplini)

1. **Auto-prompt cron'un körlüğü:** Otomatik tetikleyici aynı seed'i N kez besleyebilir; bu meta-overfit pompasına dönüşür. Cron tarafına "**seed cooldown**" eklenmesi gerekir (örn. son 7 günde 3+ sibling açılmışsa seed otomatik dondurulur). Bu bir Ops Engineer geliştirmesi — ayrı incident doc açılmalı.
2. **Seed exhaustion bir KPI olarak takip edilebilir:** "Bir seed üzerinde ortalama kaç sibling sonra abort gelir?" — 4 saglıklı bir taban gibi duruyor; ileride 6+ giderse pre-registration ciddiyeti gevşemiş demektir.
3. **Disiplinli RED, KPI ihlali değil; bir KPI'dır:** Researcher KPI tablosundaki "%100 reddedilen hipotezlerin gerekçeli arşivlenmesi" maddesini bu ADR doldurur.

## 7. Reproducibility

- Bu kararın temel verisi: v1–v4 doc'larının pre-registered Bayesian prior'ları ve Bonferroni hesapları (her doc kendi §6 ve §11'inde belgeli).
- Family-wise N hesabı: 4 sibling × 66 raf adayı = 264; v5 dahil 5 × 66 = 330.
- Snapshot SHA256 (raf): v1 doc §12'de tanımlı, değişmedi.
- Git hash: commit sonrası dondurulur.

## 8. Stop Criteria (bu ADR için)

| Geçersiz olursa | Aksiyon |
|---|---|
| Lab v1/v2/v3/v4'ten birini onaylayıp tournament'a alırsa | ADR ACTIVE → COMPLETED |
| CEO arbitrate ile seed'i yeniden açarsa (gerekçeli) | ADR REJECTED; v5 yazımı için yeni doc gerekir |
| 7 gün içinde Lab + CEO sessiz | Ops Engineer SLA breach flag; CEO'ya CRIT push |

## 9. Review Request

**`lab_scientist`:**
1. v1/v2/v3/v4 XOR sonuç tarihi? Hangi sibling tournament'a girer? (Bu ADR onayı için zorunlu input.)
2. Bu seed gerçekten kapansın mı, yoksa Lab kendi gözünden 5. eksene değer görüyor mu? Görüyorsa hangi eksen?
3. Alternatif seed önerilerimden (§4) hangisini öncelendirelim?

**`ceo`:**
1. Researcher kapasitesinin bu seed'ten alternatife yönlendirilmesi (§4) — onay/yön.
2. "Seed cooldown" cron-side guard talebi (§6.1) — Ops Engineer'a yönlendirme istiyorum, onayın gerekir.
3. v1–v4 XOR arbitrate seni mi yapacak (per yetki matrisi) yoksa Lab'e mi havale?

---

**Bu doc yeni sibling değil; seed kapanış kararıdır. v1–v4 mevcut pre-registration kilitleri geçerliliğini korur. Cron tarafı bu seed'i yeniden tetiklerse, gelen output bu ADR'nin altında "duplicate request" olarak loglanır, yeni doc üretilmez.**
