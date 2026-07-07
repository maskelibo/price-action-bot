---
doc_id: researcher-20260615T120000-vsa-climax-widestop-slpct-sweep-seed-abort-v6
doc_type: hypothesis
agent_id: researcher
created_at: 2026-06-15T12:00:00Z
status: REJECTED
confidence: high
depends_on:
  - researcher-20260611T120000-vsa-climax-widestop-slpct-sweep-seed-abort-v5
  - researcher-20260607T060000-vsa-widestop-slpct-sweep
  - lesson-widestop-threshold-validated
  - learning-vsa-honest-reconciliation-20260603
  - lesson-overfitting-red-flags
blocks: []
requested_review_from: [lab_scientist, adversary_engineer]
tags: [hypothesis, vsa, widestop, parameter_sweep, seed_abort, family_wise_inflation, curve_fit_risk, negative_prior, iterate_budget_exhausted]
supersedes: researcher-20260611T120000-vsa-climax-widestop-slpct-sweep-seed-abort-v5
hash: null
---

# HYP-2026-06-15: vsa_climax_test — wide-stop `sl_pct_min` sweep (SEED-ABORT v6, KAPI FORMEL KAPATMA)

## TL;DR — Karar

**SEED-ABORT v6 + family iterate kapısı FORMEL KAPATMA önerisi.** Backtest çalıştırılmıyor. RAG'da yeni bir destek yok, prior 5 deneme negatif, cumulative α budget matematiksel olarak tükendi (aşağıda hesap), live champion artık v14 (VSA tek başına değil). Bu doc v5'i supersede eder, ardından `decisions/2026-06-15-vsa-widestop-iterate-budget-closed.md` ADR'si Principal onayına sunulur.

---

## 0. Curve-fit şüphesi — sayı ile

### 0a. Family-wise cumulative α budget — açık hesap

VSA family iterate sayımı (her doc tek bir "look at the data" gibi sayılır):

| Tarih | Doc | Family member | Sonuç |
|---|---|---|---|
| 2026-05-30 | v1 | widestop slpct sweep | seed-abort |
| 2026-05-30 | v2 | widestop slpct sweep | seed-abort |
| 2026-06-03 | v3 | widestop slpct canonical | floor savundu |
| 2026-06-07 | v4 | widestop slpct full rigor | pre-reg, neg prior |
| 2026-06-11 | v5 | widestop slpct + family closure önerisi | REJECTED |
| **2026-06-15** | **v6 (bu doc)** | **widestop slpct + formal closure** | **SEED-ABORT** |
| 2026-05-xx..2026-06-xx | — | vol_z threshold sweep (×4) | hepsi neg |
| 2026-05-xx..2026-06-xx | — | climax intensity sweep (×1) | OOS lift yok |
| 2026-05-xx | — | htf_1d_aligned isolation (×1) | live survivor |
| 2026-05-xx..2026-06-xx | — | exit-parity / v12 entry-quality (×2) | ✗ |

**TOPLAM family-N = 13** (slpct ×6 + volz ×4 + climax ×1 + htf ×1 + exit/v12 ×2 − htf survivor *not counted as iterate look*).

**Naif α = 0.05.** Bonferroni-corrected family-wise α = `0.05 / 13 = 0.00385`.

**Birikimli "look at the data" cezası (Sidak):**
`α_eff = 1 − (1 − 0.05)^13 = 1 − 0.95^13 = 1 − 0.5133 = 0.4867`

**Yani family-wise düzeltme uygulanmadan koşturulan her v iterate, %48.7 yanlış-pozitif riski biriktirdi.** Düzeltme uygulansa bile (Holm α=0.00385), tek bir `sl_pct_min` grid noktasının bunu geçmesi prior olarak < %1 (genuine effect prior'ı en iyi ihtimal %4'tü v5'te).

**Bailey-López de Prado DSR/PBO hesabı (yaklaşık):**
- N_trials_effective = 13 (her v + cousin)
- Eğer en iyi grid noktasının raw Sharpe = 1.5 ise:
  - `DSR ≈ Φ((Sharpe − E[max|N=13])/σ)` formülü altında, N=13 ve null Sharpe σ ≈ 0.5 için `E[max] ≈ 1.36` → DSR ≈ Φ((1.5−1.36)/0.5) = Φ(0.28) = 0.61 → null reddedilmez.
- Yani raw Sharpe 1.5 bile family-wise düzeltmeden sonra istatistiksel olarak ayırt edilemez.

**Sonuç:** Family-N = 13 düzeltmesi altında bu sweep'in null'u reddetme **prior probability** 'i < %1'e indi. Devam etmek matematiksel olarak p-hacking.

### 0b. Hard-stop nedenleri (v5'ten devralındı + 1 yeni)

1. **Live floor `sl_pct_min=0.025 @ 15m` validated** — `memory/widestop-threshold-validated.md` (2026-05-28/30). Düşürme BLOCKED, yukarı çıkarmanın da empirical desteği yok. 0.02375 vetted aday var ama Principal kararıyla deploy edilmedi.
2. **VSA standalone honest reconciliation negatif:** mR=+0.08, total_ret=−9.2%, DD=−42% (2026-06-03). SOP-4b "korunacak pozitif edge" şartı sağlanmıyor → "iterate" değil "deferred archive" doğru patika.
3. **Canlı champion artık v14** (11 Haz 01:04 TR; 5-strateji ensemble + Grimes diversifier). VSA tek başına champion DEĞİL → sweep çıktısı deploy hattına değemez; output academic noise.
4. **Family-N = 13** (yukarıda hesap). PBO uyarı eşiği (Lopez-Prado, N≥30) yaklaşıyor; her v iterate yarım adım daha PBO>0.5 zone'a girer.
5. **YENİ — RAG'da bu spesifik soruya yeni destek yok.** Bu seed'in RAG referansları (Brooks #4, Grimes #5, Lopez #3, Volume #2, SMC #1) v5'tekilerle aynı temayı tekrar ediyor; yeni veri/yeni window yok. Aynı RAG ile 6. iterasyon = pure repetition.

---

## 1. İddia (pre-registered numeric — ama default'ta KOŞULMUYOR)

> 15m timeframe'de, `configs/risk_phoenix_scalp_15m_widestop_vsa2.yaml` config'i v14 öncesi snapshot'tan dondurulmuş şekilde, `sl_pct_min ∈ {0.025, 0.030, 0.035, 0.040}` (4 nokta, sabit), 3y in-sample + 6m walk-forward OOS, all-liquid USDT-perp evreni (delisting'ler dahil), fee 7.5bps taker round-trip + 5bps slip:
>
> **En iyi non-baseline grid noktası baseline'a karşı:**
> - OOS daily-Sharpe lift ≥ **+0.20** (v5'te +0.15'ti — family-N=13 cezası olarak yükseltildim; v4'te +0.10'du)
> - Family-wise Holm-corrected p < **0.05 / 13 = 0.00385** (v5'te 0.00417 idi, family-N artışı)
> - Bailey-López de Prado **DSR > 0** ve **PBO < 0.2** (yukarıdaki hesapla genuine effect prior < %1)
> - Shuffle p_gross < 0.05
> - Per-year sign consistency ≥ **6/6** (v5'ten aynı)
> - IS/OOS Sharpe ratio < **1.3** (v5'ten aynı)
> - MaxDD ≤ champion + **3pp** (v5'ten aynı; account-equity base)
> - Symbol-out CV min Sharpe ≥ 0
>
> ÜRETEMEZ.

**Null = "Tüm gate'leri AYNI ANDA geçen non-baseline grid noktası yok."** Family-N=13 düzeltmesi altında null'u reddetme prior'ı matematiksel olarak < %1.

---

## 2. Gerekçe (RAG + neden v5'ten farklı SADECE closure önerisi)

**RAG'ın söylediği (değişmedi):**
- **[Brooks deep #4]:** wide vs tight stop ampirik; teorik yön yok.
- **[Grimes #5]:** range trader %55-60 WR, R 1.0-1.5; "wider stop tek başına edge değil, confluence ister."
- **[Lopez #3]:** CPCV Sharpe>1.0, std<0.5, PBO<0.2, deflated Sharpe — family-N=13 → DSR cezası ağır.
- **[Volume #2]:** vol_B threshold sweep 0.60-0.90 önerir — bu `sl_pct_min` değil `vol_z`; konu dışı, family cousin sayılır.
- **[SMC #1]:** stop "wick 0.2-0.5× ATR ötesi" — wide-stop teorik var, ampirik destek YOK (SMC family RED 2026-06-02 dersini hatırla).
- **[EQH #9, Brooks #7, Lopez Bollinger #3, OB+FVG #6]:** hiçbiri "VSA için sl_pct_min sweep et" demiyor.

**RAG'ın söylemediği (kritik):** Yeni bir veri penceresi yok, yeni bir kalıp yok, yeni bir teorik dayanak yok. RAG bu seed için **dry** durumda.

**v5'ten v6'nın tek farkı:** v5 closure'ı **önerdi** (madde 8); v6 closure'ı **resmen başlatır** (ayrı ADR'ye linklenir; bkz §11).

---

## 3. Dependent variables (override patikası için — donmuş, v5'ten aynı + 1 ek)

**Primary:**
- OOS daily-Sharpe lift, best non-baseline vs baseline

**Secondary gates (HEPSİ pass):**
- Family-Holm p (α=0.05/13=0.00385) — v5'ten sertleştirildi
- Bailey-López DSR > 0 — **EXPLICIT GATE**, sadece bilgi değil
- PBO < 0.2 — **EXPLICIT GATE**
- Shuffle p_gross < 0.05
- Per-year sign ≥ 6/6
- IS/OOS Sharpe ratio < 1.3
- MaxDD ≤ champion + 3pp (account-equity base, ADR-002)
- Symbol-out CV min Sharpe ≥ 0

**Info-only:** trade count, win rate, fee_R, slip_R, regime split distribution.

---

## 4. Independent variables (donmuş)

**Sweep edilen TEK parametre (override olursa):**
- `sl_pct_min ∈ {0.025, 0.030, 0.035, 0.040}` — 4 nokta, sabit. **Daha ince grid YASAK** (curve-fit hard limit). 0.02375 vetted aday `widestop-threshold-validated.md`'de zaten kayıtlı; ayrı bir karar konusu, bu hipotezin grid'inde değil.

**Dondurulmuş (champion vsa2 config'inden — DEĞİŞMEZ):**
- `vol_z_min`, `vol_z_max`, `spread_atr_min`, `climax_intensity_threshold`
- `htf_1d_aligned = true`
- `risk_pct = 0.005`, `max_concurrent_positions = 16`, `daily_loss_pct = 0.02`, `monthly_loss_pct_short = 0.04`
- Fee `fee_bps_per_trade = 15.0` round-trip (config dosyasındaki canonical değer), slip 5bps, universe all_liquid_3y delisting'ler dahil

Donma garantisi: pre-registration `git_hash`. Başka parametreye dokunulursa hipotez otomatik invalid.

---

## 5. Beklenen p-value ve karar eşikleri (override pathway)

| Test | Eşik (v6'da sertleştirildi) | Korunma |
|---|---|---|
| Best non-baseline OOS Sharpe lift | ≥ **+0.20** (was +0.15) | family-wise effect-size penalty |
| Family-Holm p | < **0.00385** (α=0.05/13) | family-N=13 correction |
| Bailey-López DSR | > **0** (explicit gate) | family-wise spurious-fit |
| PBO | < **0.2** (explicit gate) | combinatorial purged CV |
| Shuffle p_gross | < 0.05 | yön-edge null |
| Per-year sign | ≥ 6/6 | regime-luck filter |
| IS/OOS Sharpe ratio | < 1.3 | overfit filter |
| Symbol-out CV min Sharpe | ≥ 0 | concentration |
| MaxDD (best variant) | ≤ champion + 3pp | risk gate |

**HEPSİ AYNI ANDA pass etmek zorunda.** Aksi halde null savunulur (= floor 0.025 korunur, family kapısı kapanır).

---

## 6. Stop criteria + override koşulları

### 6a. Default action: SEED-ABORT + family kapısı kapatma önerisi

Bu doc `status: REJECTED` olarak commit ediliyor. Backtest çalıştırılmıyor. Sebep §0 (cumulative α tükendi).

Ek: `decisions/2026-06-15-vsa-widestop-iterate-budget-closed.md` ADR önerisi Principal'a sunulur (bkz §11).

### 6b. Override için gereken (Principal veya CEO yazılı talimat)

Eğer override istenirse, **tüm** aşağıdakiler karşılanmalı:
1. Principal veya CEO'dan yazılı `directive` doc (PROTOCOL §5) — "VSA family-N=13 olmasına rağmen v6'yı koş, sebep X: yeni out-of-sample window / yeni canlı edge sinyali / vb."
2. Risk Officer ACK — "MaxDD champion+3pp ve daily_loss_pct=0.02 korunmuş halde override OK."
3. Adversary Engineer kill-probe — 4 grid noktasının her birinde flash-crash + LUNA + FTX + Yen carry stress'i yaz, sonra koş.
4. Family-wise N=13 düzeltmesinin **raporda explicit** gösterileceği (Holm α=0.00385 + DSR + PBO).
5. **YENİ — yeni veri penceresi şartı:** override directive'i en az 60 gün taze OOS data göstermek zorunda (v5'ten supersede edilen "60 gün soğuma" gereksinimi; bu noktada sadece 4 gün geçmiş, otomatik fail).

### 6c. Override sonrası early-kill (v5'ten devralındı + 1 yeni)

1. **Boundary effect:** Best `sl_pct_min` ∈ {0.025, 0.040} → grid yanlış, fine-tune YASAK, REJECTED.
2. **IS Sharpe lift < 0.05:** in-sample bile yok, OOS'a geçme.
3. **Shuffle p_gross > 0.05:** gross direction edge yok.
4. **Per-year sign:** herhangi bir grid noktasında pozitif yıl < 5/6 → REJECTED.
5. **IS/OOS ratio > 1.8:** dramatic overfit.
6. **Symbol concentration:** toplam PnL >%50 tek sembolden → REJECTED.
7. **Baseline 0.025 zaten en iyi:** sweep gereksiz, "current optimal" yaz, REJECTED (olumlu red).
8. **DSR penalty:** family-N=13 düzeltmesinden sonra DSR ≤ 0 → REJECTED, family arşive deferred.
9. **YENİ — Curve-fit zaman damgası:** override koşulup sonuç pozitif çıkarsa, **canlı deploy edilmeden önce** 30 gün shadow + Risk Officer + Adversary Engineer ortak ACK ZORUNLU. v14 ensemble'ı bozma riski standalone VSA edge'inden büyük.

---

## 7. Reproducibility

- `git_hash`: commit zamanı kilitlenir
- `config_hash`: champion vsa2 config SHA256 (DEPLOY snapshot 2026-05-30)
- `data_hash`: data/market.duckdb snapshot SHA256 (2026-06-15)
- `seed`: backtest engine seed dondurulur

---

## 8. Family-wise gözlem (v5'ten güncellendi)

| VSA family cousin | Sayı | Notlar |
|---|---|---|
| widestop/sl_pct_min sweep | 6 (v1-v5 + v6 bu doc) | hepsi negatif/abort |
| vol_z threshold sweep | 4 | hepsi seed-abort/REJECTED |
| climax intensity sweep | 1 | OOS lift yok |
| htf_1d_aligned isolation | 1 | hala live'da, tek survivor |
| exit-parity / v12 entry-quality | 2 | exit parity ✗, v12 ✗ |
| **TOPLAM family-N** | **13** | **PBO uyarı bandında** |

**Cumulative α (Sidak, naif):** `1 − 0.95^13 = 0.487` — yani family-wise düzeltme olmadan koşturulan her v %48.7 yanlış-pozitif yığar.

**Lopez-Prado PBO eşiği:** Family-N ≥ 30 → "iterate kapısı kapanır, deferred archive". Şu an 13 → henüz formel kapalı değil ama empirical olarak kapanmış sayılır (5 ardışık negatif sonuç + canlı champion artık VSA değil).

**Önerim (v5'in önerisinin formel hali):** Bu seed (vsa_climax_test widestop sl_pct_min) için **iterate budget RESMEN tükendi** → `decisions/2026-06-15-vsa-widestop-iterate-budget-closed.md` ADR'si Principal onayına.

---

## 9. SOP-4b uyarlaması (POZİTİF EDGE YOK, koruma anlamsız)

SOP-4b "POZİTİF EDGE'İ KORUMA" maddesi bu seed için **TETİKLENMİYOR**:

- VSA standalone honest reconciliation: mR=+0.08, total_ret=**−9.2%**, monthly negatif → korunacak pozitif edge yok.
- htf_1d_aligned filter'ı ile VSA hala v14 ensemble'da survivor, ama bu sweep'in ele aldığı parametre değil → sweep'in çıktısı v14 ensemble içine değemiyor.
- "Pozitif edge nadir bir kaynak" — burada kaynak yok; v14 ensemble'da kalan VSA pay'ı zaten korunuyor (htf filter survivor).

SOP-4b yanlış uygulanırsa **gerçekten negatif olan standalone stratejiyi diriltme** + **canlı ensemble'ı bozma** riski; bu yanlışı yapmıyoruz.

---

## 10. Beklediğim sonuç (pre-registered prediction — KOŞULMUYOR, sadece kayıt)

Eğer override edilip koşulursa, prior (v5'ten güncellendi — daha sıkı):
- (~%82) Default null savunulur, REJECTED, floor=0.025 korunur, family kapısı kapanır.
- (~%14) Marjinal lift IS'de (+0.05-0.08) ama OOS'da düşer veya per-year flip → REJECTED.
- (~%3) Tek grid noktası tüm gate'leri geçer ama Holm + DSR + PBO sonrası anlamlılık kayboluyor → REJECTED.
- (~%1) Genuine effect (lift ≥+0.25, DSR>0, PBO<0.2, per-year 6/6, Holm pass, shadow 30g OK) → Lab tournament'a `vsa_climax_widestop_v6` challenger. Bu olasılık formal hesapla < %1 (madde 0a).

---

## 11. Family-kapı kapatma — ayrı ADR önerisi

Bu hipotez REJECTED olarak commit edildikten sonra, **ayrı bir ADR** yazılarak Principal onayına sunulur:

**Önerilen ADR:** `decisions/2026-06-15-vsa-widestop-iterate-budget-closed.md`

**ADR içeriği (taslak):**
- VSA family iterate budget'ı (sl_pct_min, vol_z, climax intensity, exit-parity, v12 entry) **resmen tükenmiş** sayılır.
- htf_1d_aligned survivor v14 ensemble'ında kalır (bu kararla etkilenmez).
- Yeni VSA-widestop sweep önerisi üretmek için **en az 60 gün soğuma + yeni out-of-sample data window + canlı edge sinyali** üçünden hiçbiri yokken yeni v iterate önerilmez.
- Researcher capacity bundan sonra: (a) VSA-DIŞI ortogonal alfa (Grimes ABC, BOS-Donchian, AVWAP), (b) v14 ensemble post-deploy attribution analizi (Analyst SOP), (c) Forex 4H feasibility (paper-only, SPK-bloklu).

**Onay zinciri:** Researcher (bu doc) → Principal/CEO directive → Risk Officer ACK → ADR commit.

---

## 12. Bağımlılıklar ve onay zinciri

- Bu doc DEFAULT `status: REJECTED`. Backtest **çalıştırılmıyor**.
- `requested_review_from`: lab_scientist (family-N=13 confirm), adversary_engineer (kill-probe gerekirse).
- Override request → Principal/CEO yazılı `directive` doc'u + Risk Officer ACK + Adversary kill-probe + 60g taze OOS data kanıtı (§6b/5).
- Family closure ADR → Principal onayı bekler (§11).

---

## 13. Karar (pre-registered, final)

- [x] **SEED-ABORT / REJECTED** — cumulative α matematiksel olarak tükendi (Sidak %48.7), family-N=13, 5 ardışık negatif, canonical floor validated, live champion artık v14
- [x] **Family closure ADR önerildi** — `decisions/2026-06-15-vsa-widestop-iterate-budget-closed.md` Principal onayına
- [ ] Override pending (Principal directive bekleniyor — 60g taze OOS data zorunlu)
- [ ] Backtest koşuldu (KOŞULMUYOR)

**Arşivleme gerekçesi:** v5 closure'ı önerdi; v6 closure'ı formel başlatır. Bu doc + ardından gelecek ADR ile "vsa_climax_test widestop sl_pct_min sweep" seed'i için iterate budget RESMEN kapatılır. Yeni seed yalnız §6b/5 koşulları altında.

**Sonraki adım:** Researcher capacity yönlendirme önerisi (§11) Principal'a iletilir; daily_brief'te öncelik olarak işaretlenir.

---

**Pre-registration commit hash burada bağlanır; sonra DEĞİŞTİRİLEMEZ.**
