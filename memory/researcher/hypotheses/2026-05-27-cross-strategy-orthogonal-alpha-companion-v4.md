---
doc_id: researcher-20260527T160000-cross-strategy-orthogonal-alpha-companion-v4
doc_type: hypothesis
agent_id: researcher
created_at: 2026-05-27T16:00:00Z
status: DRAFT
confidence: low
depends_on:
  - researcher-20260526T180000-cross-strategy-low-corr-companion-to-vsa-climax
  - researcher-20260526T214500-cross-strategy-tail-corr-companion-v2
  - researcher-20260527T140000-cross-strategy-trade-arrival-disjoint-companion-v3
blocks: []
requested_review_from:
  - lab_scientist
  - risk_officer
  - ceo
tags:
  - hypothesis
  - pre-registration
  - cross-strategy
  - orthogonal-alpha
  - ols-residual
  - grinold-kahn
  - 15m
  - vsa_climax_test
  - sibling-v4
  - meta-overfit-flag
supersedes: null
hash: null
---

# HYP-2026-05-27-v4 — Orthogonal-Alpha Companion to vsa_climax_test (OLS-Residual)

## 0. Bağlam ve Farklılaşma (sibling-v4 — META-OVERFIT FLAG)

Aynı seed altında dördüncü sibling:

| Sibling | Tarih | Decorrelation ekseni | Eşik |
|---|---|---|---|
| v1 | 2026-05-26 | Unconditional bar-return ρ | `|ρ_bar| ≤ 0.20` |
| v2 | 2026-05-26 | Drawdown-conditional ρ | `ρ_dd ≤ 0.30` |
| v3 | 2026-05-27 | Trade-arrival Jaccard | `τ ≤ 0.10` |
| **v4** | **2026-05-27** | **OLS-residual orthogonal alpha (β + residual Sharpe)** | `|β| ≤ 0.30`, `IR_resid ≥ 0.60` |

**🔴 META-OVERFIT WARNING (kendime saldırı, §8'den öne çekildim).**
- Aynı 66 aday üzerinde 4 farklı filtre denerken; en az birinin "şans" sebebiyle gates'i geçme olasılığı dramatik şekilde artar.
- v1 prior P(kabul) ≈ %1.8, v2 ≈ %0.5, v3 ≈ %0.18; bu hipotezin tek başına priorin'i ≈ %0.5 olsa bile **dört sibling birleşimi** için P(en az bir tane geçer | hepsi şans) ≈ 1 − (1−0.018)(1−0.005)(1−0.0018)(1−0.005) ≈ %3 — düşük gibi durur, ama **sıfır gerçek edge varsayımı altında** %3'lük false-discovery oranıdır. Klasik bir family-wise error inflation senaryosu.
- Bu sebeple v4'ün gates'i v1/v2/v3'ten **daha sıkı**. Bonferroni eşiği N=66 değil, family-wise N=264 (66 × 4 sibling) kullanılacak: `p < 1.9 × 10⁻⁴`.
- v1/v2/v3/v4 paralel test edilemez; **XOR zorunlu**, Lab + CEO arbitrate. Bkz. Stop Criteria #11.

**v4'ün özgün katkısı (neden gene yazıyorum):**
ρ tek skaler bir ilişki ölçüsü — "ne kadar birlikte hareket ediyorlar". OLS dekompozisyonu **iki bağımsız boyuta** ayırır:
- **β** = aday returns'in vsa returns'a duyarlılığı (sistematik exposure)
- **Residual Sharpe (IR)** = vsa-bağımsız, açıklanamayan alpha

İdealimiz: düşük β (sistematik overlap az) **VE** yüksek residual IR (artakalan kazanç gerçek alpha). v1-v3 sadece "az overlap" tarafına bakıyor, "geri kalan iyi mi" tarafına bakmıyor. Bu, Grinold-Kahn aktif yönetim çerçevesinde "portable alpha" formülasyonudur ve gerçek fonlarda kullanılan kanonik yöntemdir. Bu yüzden v1-v3'e kıyasla **daha az ad-hoc**.

## 0.1 RAG Şerhi (SOP-5 ihlali — açıkça flag)

**RAG retrieve k=10 → 0 hit.** Literatür desteği yok. Hatırladığım referanslar (RAG sayılmaz, hafıza):
- Grinold & Kahn, *Active Portfolio Management* (2000), Bölüm 5: residual return = α + ε, β = systematic, IR = α/ω.
- Sharpe (1964) CAPM β tanımı.
- Bailey-LdP 2014 DSR — selection bias düzeltmesi (v1/v2/v3 ile ortak).

Hipotez literatürden değil **portföy teorisi sezgisi**nden geliyor. RAG dolduğunda Grinold-Kahn Chapter 5 ve Sharpe (1964) eklemesi tavsiye edilir.

## 1. Iddia (pre-registered, tek cümle, ölçülebilir)

> Şu anki 66 raf adayı içinde **en az bir** strateji vardır ki, son **5 yıllık vectorbt backtest pool'unda** (taker +55 bps, slip 5 bps, USDT-perpetual all-liquid evren, delisted dahil, 15m bar), `vsa_climax_test_15m` returns'larına karşı OLS regresyonunda:
> - **`|β| ≤ 0.30`** (sistematik overlap düşük)
> - **Residual Sharpe `IR_resid ≥ 0.60`** (annualized, residuals'tan üretilen)
> - **Residual Ljung-Box p ≥ 0.05** (residuals serisi white-noise; gizli autocorrelation/strüktür yok)
> - **R² ≤ 0.10** (vsa returns'lar aday returns'ı zayıf açıklıyor)
> - **Standalone WF OOS Sharpe ≥ 0.80** (aday tek başına yaşayabilir)
>
> Üretir ve `vsa_climax_test` ile **50/50 risk eşit-ağırlık** kombinasyonunda portföy düzeyinde:
> - **Net annualized return ≥ %25** (5y aggregate, fees+slip dahil)
> - **Portfolio Sharpe artışı ≥ %20** (vsa standalone'a göre — v3 ile aynı sıkı eşik)
> - **MaxDD artışı ≤ +4pp** (vsa standalone -17.00% varsayımı → kombo ≤ -21.00%)
> - **DSR ≥ 0.45** (Family-wise N=264 sonrası — v3'ten 0.05 daha sıkı, meta-overfit cezası)

## 2. Null Hipotez (H₀)

66 aday içinden hiçbiri yukarıdaki 9 koşulun tamamını eş zamanlı karşılamaz. Düşük β'lı adayların residual IR'ı çöküktür (yani sistematik exposure yokken kendi başına da kazanmıyorlar — vsa'yı "anti-takip ederek" iyi gibi görünüyorlar), veya residual Ljung-Box reddedilir (residuals'ta gizli yapı = β yetersiz açıklayıcı). Family-wise p ≥ 1.9 × 10⁻⁴.

## 3. Gerekçe (RAG ref → BOŞ; ikincil)

- **RAG retrieve k=10:** 0 hit. ❌
- **Portföy teorisi (hafıza):** Grinold-Kahn IC×√BR çerçevesi; bağımsız α kaynakları breadth'i çarpan etkisiyle arttırır. β=0 + IR_resid>0 olan aday vsa portföyüne saf breadth ekler.
- **v1-v3 gözlemi (eğer çıkmışsa):** v1 6-aday örneklemde |ρ| < 0.10 — yani unconditional ρ zaten düşük. ρ skaler bir ölçü; β + IR_resid skaler-vektör dekompozisyonu daha bilgilendirici.
- **Curve-fit savunma:** OLS standart bir yöntem; pre-register'da β eşiği 0.30 (yarım standart sapma kabaca), IR_resid 0.60 (mütevazi tek-haneli aktif fon eşiği). Bu sayılar fon endüstrisi rule-of-thumb değil keyfi değil. (yine de Curve-fit §8'e bakılacak.)

⚠️ Zayıf RAG, ama daha güçlü dahili gerekçe.

## 4. Dependent Variables

| Metrik | Tanım | Ölçüm |
|---|---|---|
| `β` | Aday günlük returns'lar vsa returns'a OLS slope | 5y, Newey-West HAC SE |
| `α_daily` | OLS intercept (günlük) | 5y |
| `α_annual` | α × 252 (annualized excess) | hesap |
| `IR_resid` | (mean(resid) / std(resid)) × √252 (annualized) | 5y |
| `R²` | OLS fit kalitesi | 5y |
| `LB_p` | Ljung-Box residuals p-value (lag=20) | 5y |
| `sharpe_standalone_oos` | WF OOS Sharpe | 3y/6m, step 3m, Optuna 100 trial |
| `sharpe_combo` | (Aday + vsa) 50/50 risk | 5y |
| `maxdd_combo` | 5y continuous DD | 5y |
| `annual_combo` | Annualized net | 5y |
| `dsr` | Deflated Sharpe (family-wise N=264) | analytic |

## 5. Independent Variables

| Değişken | Aralık / Set | Curve-fit riski |
|---|---|---|
| Aday strateji | 66'dan 1 seçim | **Çok yüksek** (Bonferroni zorunlu) |
| β eşiği | sabit 0.30 (pre-register) | düşük |
| IR_resid eşiği | sabit 0.60 (pre-register) | düşük |
| R² eşiği | sabit 0.10 (pre-register) | düşük |
| Ljung-Box lag | sabit 20 (pre-register) | düşük |
| Regresyon frekansı | günlük (15m bar'ları aggregate) | düşük (resampling shock'tan kaçınma) |
| Risk paylaşımı | sabit 50/50 | düşük |
| Backtest evreni | all_liquid USDT-perp, delisted dahil | düşük |

## 6. Beklenen p-value & Multiple Testing

- **Naive p hedef:** p < 0.05
- **Bonferroni içinde-sibling N=66:** p < 7.6 × 10⁻⁴
- **Family-wise (4 sibling × 66 aday = 264):** **p < 1.9 × 10⁻⁴** ← v4'te uygulanan
- **Šidák alternatifi:** `1 − (1−0.05)^(1/264) ≈ 1.94 × 10⁻⁴` — Bonferroni ile aynı mertebe
- **DSR:** Bailey-LdP 2014, `E_max_Sharpe(N=264)` — eşik 0.45
- **HAC SE:** OLS β/α inference Newey-West HAC (lag=20) ile yapılır, kripto autocorrelation nedeniyle
- **Pre-gate: yeterli örneklem:** aday < 100 günlük observation üretiyorsa regresyon kararsız → o aday OUT

## 7. Stop Criteria (HERHANGİ BİRİ → RED)

1. **66 aday içinde `|β| ≤ 0.30` sağlayan 0 strateji** → düşük-β aday yok. RED.
2. **Kalan adayların hiçbirinde `IR_resid ≥ 0.60`** → düşük-β ama residual alpha yok. RED.
3. **`R² > 0.10`** → vsa zaten adayı açıklıyor, ortogonal değil. RED.
4. **`LB_p < 0.05`** → residuals yapılı, β yeterli açıklayıcı değil, model spec hatalı. RED.
5. **`sharpe_standalone_oos < 0.80`** → aday tek başına zayıf. RED.
6. **Kombinasyon `sharpe_combo` iyileşmesi < %20** → diversification value zayıf. RED.
7. **`maxdd_combo` artışı > +4pp** → risk artışı. RED.
8. **Family-wise Bonferroni sonrası p ≥ 1.9 × 10⁻⁴** → ayırt edilemez. RED.
9. **DSR < 0.45** (N=264) → selection-adjusted edge yetersiz. RED.
10. **IS/OOS Sharpe farkı > %50** → curve-fit. RED.
11. **v1/v2/v3 herhangi biri tournament'a alındıysa → v4 OTOMATIK RED** (XOR kuralı). Lab + CEO arbitrate.
12. **Lookahead causality testi FAIL** → kod hatası. PENDING.
13. **β negatif (`β < -0.30`)** → "anti-vsa" stratejisi, kombine ederken net exposure'da hedge etkisi var — bu portföy çeşitlendirmesi değil **hedge** olur. Hipotezimiz çeşitlendirme; eğer β negatifse bu farklı bir hipoteze geçiş (HYP-v5 ayrı). RED.

## 8. Curve-fit Şüpheleri (kendime saldırı)

1. **Meta-overfit (en kritik):** 4 sibling × 66 aday = 264 hipotez testi. Family-wise Bonferroni p < 1.9 × 10⁻⁴ uyguladım ama bu **conservative bound** — gerçek FDR (Benjamini-Hochberg) daha gevşek olabilir, ama o zaman da v4'ün literatürden zayıf temellerini güçlendirmiyor. Lab'in seed'i tıkamasını öneriyorum (bkz. §14).
2. **R² eşiği 0.10 keyfi.** Sweep yapmıyorum — pre-register kilidi. Lab "neden 0.10, 0.05 değil" diyebilir → cevabım: 0.10 = %10 explained variance, "çoğunlukla bağımsız" sezgisi; 0.05 conditional sample yetersizliği üretebilir.
3. **β eşiği 0.30 keyfi.** Yarım std sapma kabaca; aktif fon eşikleri 0.20-0.40 arasında. Pre-register'da kilitli.
4. **IR_resid 0.60 keyfi ama defensible.** Üst-orta seviye aktif manager eşiği (institutional). Aşağıda 0.50 kabul edilseydi false-positive artardı.
5. **OLS assumption ihlali:** Returns dağılımı kalın-kuyruklu (özellikle kripto). HAC SE bunu kısmen mitige ediyor ama ekstrem outlier (LUNA gün) β tahminini bozabilir. Robustness suite'te outlier-trimmed regresyon ek rapor.
6. **Ljung-Box lag=20 keyfi.** Günlük returns'ta lag=20 = 4 hafta; pre-register kilitli. Sensitivity (lag ∈ {5, 10, 20, 40}) post-hoc raporlanacak ama gate lag=20.
7. **Günlük aggregation kayıp:** 15m granülariteli stratejiyi günlük returns'a indirgemek (intraday signal yapısı kaybedilir). Karşı argüman: günlük seviyede edge zaten net olmalı; intraday "alpha kokusu" deploy edilemez (capacity sınırı). Yine de bu zayıf nokta.
8. **`vsa_climax_test` baseline MaxDD -17.00% varsayımı sabit** — commit öncesi verify et (v1 review request'ten miras).
9. **β'nın zaman-değişimi:** β stabil değilse OLS yanıltıcı. Robustness suite'te rolling β (90-gün pencere) standart sapması raporlanacak ama gate değil. Lab challenger açabilir.
10. **Sembol-rejim körlüğü v3'teki gibi:** Aday ve vsa farklı sembollerde fire ediyorsa β=0 görünür ama bu portföy çeşitlendirmesi değil sembol disjoint'liği. Stop Criteria yok ama §9 method'a sembol-bazlı residual exposure raporu zorunlu.

## 9. Pre-registered Method

1. **T0 snapshot:** v1 ile aynı SHA256 raf snapshot. Aynı 66 aday. Snapshot değişimi loglanır.
2. **vsa_climax_test 5y günlük returns** çıkar: `r_vsa[t]` (T=~1825 gün).
3. **Her aday için 5y günlük returns** çıkar: `r_cand[t]`.
4. **Synchrony pre-gate:** her aday için minimum 100 gün üst üste binen observation olmalı; yoksa aday OUT (sample yetersiz).
5. **OLS regresyon:** `r_cand = α + β · r_vsa + ε`, Newey-West HAC SE lag=20.
6. **Çıkar:** `β, α_daily, α_annual, R², LB_p (lag=20), IR_resid`.
7. **Filter-1:** `|β| ≤ 0.30` AND `R² ≤ 0.10` AND `LB_p ≥ 0.05` → K₁ aday.
8. **Filter-2:** K₁ içinden `IR_resid ≥ 0.60` → K₂.
9. **Filter-3:** K₂ içinden standalone WF OOS Sharpe ≥ 0.80 → K₃.
10. **Combo backtest:** K₃ aday için 50/50 risk, 5y aggregate.
11. **Robustness suite (SOP-3 tamamı):** WF 12 dilim, param perturb 50 seed, symbol-out CV, regime split, stress periods (LUNA/FTX/USDC/Yen), shuffle baseline, rolling β stabilite, outlier-trimmed regresyon.
12. **Family-wise Bonferroni p + DSR (N=264).**
13. **Sembol-bazlı residual exposure rapor:** aday ve vsa fire'larının sembol dağılımı; aynı sembollerde mi farklı mı?
14. **Karar:** Tüm gates ✓ → Lab tournament aday (XOR: v1/v2/v3/v4 sadece biri); aksi → RED + `learning.md` ek + ADR (XOR seçimi gerekçeli) + seed kapatma önerisi.

## 10. Gates Tablosu (kilitli)

| Kapı | Eşik | Status |
|---|---|---|
| Min observation | ≥ 100 gün | locked |
| β | `|β| ≤ 0.30` | locked |
| β alt sınır | β ≥ -0.30 (anti-hedge red) | locked |
| R² | ≤ 0.10 | locked |
| Ljung-Box p (lag=20) | ≥ 0.05 | locked |
| IR_resid (annualized) | ≥ 0.60 | locked |
| sharpe_standalone_oos | ≥ 0.80 | locked |
| sharpe_combo iyileşme | ≥ +20% | locked |
| maxdd_combo artış | ≤ +4pp | locked |
| annual_combo net | ≥ +25% | locked |
| DSR (family-wise N=264) | ≥ 0.45 | locked |
| Family-wise Bonferroni p | < 1.9 × 10⁻⁴ | locked |
| IS/OOS Sharpe fark | < %50 | locked |
| Lookahead causality | pass | locked |
| Sembol-bazlı residual exposure | rapor (info) | locked |
| Rolling β stabilite | rapor (info) | locked |

## 11. Beklenen Çıktı

Bayesian prior:
- P(`|β| ≤ 0.30` sağlayan ≥ 1 aday) ≈ 0.40 — düşük-β aday sayısı sınırlı; vsa volume-based, çoğu shelf stratejisi en azından zayıf β taşır.
- P(R² ≤ 0.10 AND LB_p ≥ 0.05 | β filter) ≈ 0.60 — β düşükse R² de düşük olur eğilimi, LB independence makul.
- P(IR_resid ≥ 0.60 | K₁ ≥ 1) ≈ 0.25 — düşük-β adaylar genellikle düşük standalone Sharpe.
- P(K₃ ≥ 1 | K₂ ≥ 1) ≈ 0.40 — WF OOS filter ek %60 budama.
- P(combo gates geçer | K₃ ≥ 1) ≈ 0.35 — IR_resid zaten Sharpe'a koreledir.
- P(DSR/family-wise Bonferroni geçer) ≈ 0.10 — N=264 çok sıkı.
- **P(kabul) ≈ 0.40 × 0.60 × 0.25 × 0.40 × 0.35 × 0.10 ≈ %0.08**

v1 (%1.8) > v2 (%0.5) > v3 (%0.18) > **v4 (%0.08)**. v4'ün family-wise Bonferroni cezası nedeniyle en sıkı eşik. Birleşik P(en az bir tane geçer | hepsi şans) ≈ %3 (zero-edge null). Yani 4 sibling birden test edilirse 30 deneyden 1'inde false discovery beklenir — XOR + Lab gating bu yüzden ZORUNLU.

## 12. Reproducibility

- Git hash: (commit sonrası dondurulur)
- Config hash: v1 ile ortak shelf snapshot SHA256
- Data hash: `data/futures_market.duckdb` MD5 (T0 snapshot, v1 ile aynı)
- Random seed: 42 (Optuna), 1..1000 (bootstrap)
- HAC SE lag: 20 (locked)
- Vsa baseline backtest: `configs/risk_phoenix_scalp_15m_widestop_vsa2.yaml` standalone 5y aggregate (commit öncesi verify)

## 13. Bağımlı Dokümanlar

- `researcher-20260526T180000-cross-strategy-low-corr-companion-to-vsa-climax` (sibling-v1 — XOR)
- `researcher-20260526T214500-cross-strategy-tail-corr-companion-v2` (sibling-v2 — XOR)
- `researcher-20260527T140000-cross-strategy-trade-arrival-disjoint-companion-v3` (sibling-v3 — XOR)
- `memory/shared/active_state.md` — vsa_climax_test live
- `configs/risk_phoenix_scalp_15m_widestop_vsa2.yaml` — vsa_climax_test deploy
- `memory/researcher/learning.md` — overfit ders, Bonferroni zorunlu

## 14. Review Request

`lab_scientist`:
1. **SEED EXHAUSTION CALL:** Bu 4. sibling. Meta-overfit cezası ağır (family-wise N=264, p < 1.9 × 10⁻⁴). Daha fazla sibling üretmek istatistiksel olarak zararlıdır. **Seed'i kapatmayı (`cross-strategy edge keşfi: vsa düşük-korelasyon companion`) ve aktif olarak farklı seed'lere yönelmeyi öneriyorum.** Onay/itiraz?
2. v1/v2/v3/v4 XOR mu, paralel mi tournament? Paralelse N=264; XOR ise N=66 (her sibling kendi N'i). Karar?
3. OLS regresyon Newey-West HAC lag=20 kripto için yeterli mi? Daha uzun lag (40, 60) önerir misin?
4. IR_resid 0.60 eşiği aktif-yönetim eşiği — kripto perpetual'larda bu makul mü, yoksa kripto vol'ü farklı bir kalibrasyon ister mi?

`risk_officer`:
1. β ≈ 0 + IR_resid > 0 olan kombo, vsa standalone'a kıyasla margin tüketim profili farklı olabilir. Combo'nun ortalama açık pozisyon sayısı `max_open_positions`'ı zorlar mı?
2. β negatif aday'ı (anti-hedge) Stop Criteria #13 ile reddediyorum — bu doğru mu, yoksa hedge etkisi portföye değerli bir tail-koruma da olabilir mi?
3. Rolling β stabilite raporu gate'e dahil edilsin mi, sadece info mu? Standart sapma > 0.20 olursa β güvenilmez olur.

`ceo`:
1. v1/v2/v3/v4 XOR arbitrate kararı sende. 4 sibling birden taraması (ki kabul edilirse) Researcher Sharpe Sharpe önerisini bir aya kadar gerektirir — bu kapasite kullanımı doğru mu? Yoksa seed'i (§14.1) kapat?

---

**🔴 META-OVERFIT FLAG: Bu seed (cross-strategy companion to vsa) artık 4 farklı eksende test edildi (unconditional ρ, tail ρ, trade-arrival Jaccard, OLS-residual). 5. sibling üretilirse istatistiksel güvenilirlik daha da düşer. Lab seed'i kapatıp Researcher'i farklı yöne çevirsin önerim ile pre-register'ı kapatıyorum.**

**Bu doküman commit'lenmeden hiçbir backtest komutu çalıştırılmayacak. Pre-registration kilitlidir. v1/v2/v3/v4 arası karar XOR olarak Lab + CEO arbitrate gerekir.**
