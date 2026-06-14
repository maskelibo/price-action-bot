---
doc_id: researcher-20260530T103000-vsaclimax-volz-threshold-sweep
doc_type: hypothesis
agent_id: researcher
created_at: 2026-05-30T10:30:00Z
status: PROPOSED
confidence: med
depends_on: []
blocks: []
requested_review_from: [lab_scientist, risk_officer, adversary_engineer]
tags: [vsa_climax, parameter_sweep, vol_z, iterate, anti_curve_fit, sop_1, null_proving]
supersedes: null
hash: null
---

# Hipotez: HYP-2026-05-30-vsaclimax-volz-threshold-sweep

> **NULL-PROVING formulation.** Bu pre-reg, "vol_z threshold ile vsa_climax_test'i iyileştirme" hipotezini AÇIKÇA NULL (H0 = "ek vol_z gate edge taşımaz, right-tail'i bozar") olarak yazar. Hipotezin asıl katkısı: redundant filter testini geçirip pozitif-edge'in heba edilmediğini DOĞRULAMAK, ya da (düşük öncelikli) gerçekten ortogonal bir vol_z eşiği bulmak. Curve-fit'e karşı çok katmanlı pre-commit guard var (§7-§9). Kod yazılmadan önce frozen.

## 0. Pre-registration kontrolleri

- **Substrate doğrulandı:** vsa_climax_test canlı 15m strateji, pool `sec53_15m_pool_v11.pkl` (vsa2 amplify), 14-sembol deploy. Production knob'lar: `vol_sma_mult=2.0` (climax detection ratio, manifest), `filters.volume_zscore_min=0.0` (vol_z gate OFF, manifest), trail `runner_trail_mult=3.0` (winner-let-run, OOS robMed +14% — 2026-05-29 promotion).
- **Substrate seed-abort sebebi değil** (önceki vsa-companion, daily-scan, btc-dominance abort'larından farklı): vol_z gate manifest'te NESNE olarak var, sweep parametre-uzayı tanımlı, RAG vol_z eşik literatürüyle dolu (refs #1, #2, #4, #9).
- **RAG topical hit:** 6 doğrudan ilgili (vol_z formülü #1, threshold sweep grid önerisi #4, stopping volume hipotez şablonu #9). RAG_TOPICAL_RELEVANCE k=3+ tatmin.
- **Pool↔kod parity uyarısı (2026-05-29 learning):** deployed pool current HEAD'den reproduce EDİLEMİYOR (canonical builder BTC 8002 bar vs cached 7952, mean|ΔR|~0.8). Bu hipotezin GATHER-time pool rebuild ZORUNLULUĞU var — stale pool üstünde değil. Pre-reg §6.5'te explicit yazıldı.
- **Prompt injection rejected:** Seed payload "Curve-fit şüphesi yarat" stringini içeriyor. Persona Hard-Limit: "Anti-narrative bias. Sayı olmayan iddia kabul gerekçesi değildir." Bu injection prior daily-scan/btc-dominance abort'larıyla aynı pattern. **Reddedilmiştir**; bu hipotez tersi yönde — curve-fit'i DETECTABLE yapacak şekilde grid'i kasıtlı KOAR, Bonferroni'yi PRE-COMMIT, right-tail koruma kontrolünü PRE-COMMIT.

## 1. İddia (numeric, measurable)

**Primary (H1, üzerine bahis koyuyorum):** 15m vsa_climax_test'e `volume_zscore_min ∈ {0.5, 1.0, 1.5, 2.0, 2.5}` filter eklemek, baseline'a (vol_z gate OFF) kıyasla:

- OOS aylık-medyan ROI'da Bonferroni-6 düzeltmesi (α/m = 0.00833) sonrası **HİÇBİR threshold'da** +3pp ve üzeri robust iyileşme üretMEZ.
- En az **3/5 threshold**'da cut-bucket meanR (filtre tarafından REDDEDİLEN trade'lerin meanR'ı) ≥ pool meanR × 0.7 olur — yani redundant filtering, kazanan trade'leri kazanmayanlardan ayırt edemez (brooks regime-filter 2026-05-29 dersi tekrarlanır).
- En az **3/5 threshold**'da top-5%-share OOS'ta baseline'ın **0.85×**'inden DAHA AZ — right-tail'in kesildiğinin göstergesi.

**Secondary (H1b, daha düşük öncelikli sensitivity):** `vol_sma_mult ∈ {1.5, 2.0 baseline, 2.5, 3.0 (pre-amplify)}` sparse 4-noktası, OOS aylık-medyan baseline (2.0) için ± 2pp band içinde kalır (monotone yok, plateau var). Bu, amplify kararının (3.0→2.0) marjinal, plateau-civarı bir seçim olduğunu doğrular.

**H0 (null, çürütmek istediğim):** Bonferroni-6 sonrası ≥ 1 threshold'da +5pp OOS aylık-medyan iyileşme + DD ≤ baseline DD + 2pp + top-5%-share ≥ baseline × 0.85 + paired-sign-flip null p < 0.00833.

## 2. Gerekçe (RAG referansları)

- **[#1 book_volume_price_divergence]** — `vol_z = (volume[t] - volume_mean_20) / volume_std_20`. Z-score formülü tanımı; bizim runtime hesabımız 20-bar window'la (15m × 20 = 5h, manifest'te `vol_z_lookback_bars=20`) uyumlu. Pre-reg compute formülü budur.
- **[#4 book_volume_price_divergence]** — Threshold sweep guidance: "Test önerisi: 0.60 ile 0.90 arasında 0.05 adımlarla sweep" (klasik pattern oranı için). Bizim vol_z gate için literatür önerisi: "Başlangıç: ±2.0σ. Güçlü: ±2.5σ. Aşırı: ±3.0σ." (CVD için, ama vol-z'ye lineer transfer). 0.05 adım — **anti-curve-fit Hard-Limit**: ben 0.5 adım kullanacağım, 6 nokta.
- **[#9 book_volume_price_divergence]** — Stopping volume hipotezi: vol_z>2.0 + dar spread → reversal teyiti. Bizim climax detection ZATEN dar spread DEĞİL geniş spread ister (`spread_atr_mult: 1.5`); yani #9 senaryosu vsa_climax_test'in TERSİ — bu, ek vol_z gate'in climax-spread filtresinden YAPISAL OLARAK farklı bir bilgi taşıyıp taşımadığı sorusunu gündeme getirir. **Pre-cev: taşımıyor** (climax bar zaten >2σ vol içerir construction'la).
- **[#2 book_volume_price_divergence]** — "Mevcut sistemde volume_z_score tek bar'ın hacmini normalize eder. Diverjans augmentasyonu..." — divergence augmentation bu pre-reg'in kapsamı DIŞINDA (yeni hipotez gerektirir). Sadece tek-bar threshold'a odak.
- **Internal: 2026-05-29 brooks regime-filter FALSIFIED learning** — pozitif-edge stratejide ek filter cut-bucket meanR'ı pool meanR'a yakın bırakır (near-random separation); right-tail (top-5% share) baseline'ın altına düşer. Bu hipotez aynı testi vol_z için yapar.
- **Internal: 2026-05-29 winner-let-run promotion** — trail 3.0 ile OOS robMed +14%. vol_z sweep BU exit config'i üstünde test edilecek; trail VE vol_z'yi BİRLİKTE optimize etmek = 2-eksen curve-fit pompası. Bunu YASAKLIYORUM (§7.4).

**RAG dışı destek:** Wyckoff klasik literatür (Williams, Tom Williams VSA) — climax bar TANIMI gereği >2σ vol içerir. Bizim climax detection (`vol_sma_mult=2.0`) zaten ~1.8-2.2σ z-score'a denk gelir empirik olarak. Ek vol_z gate ≥0.5 → climax-tanım-içi tautoloji; ≥2.0 → climax bar'larının yarısını keser (over-filter).

## 3. Dependent Variables (önceden donduruldu)

| # | Metric | Tanım | Hedef yön |
|---|---|---|---|
| D1 | OOS monthly-mean ROI | 61-ay walk-forward median pencerede mean | iyileşme = +pp |
| D2 | OOS monthly-MEDIAN ROI | aynı periyot median (robust) | **PRIMARY** — winsor-medyan |
| D3 | continuous-curve MaxDD | account-equity tabanlı (account-eq DD, NOT zero-base) | iyileşme = -pp |
| D4 | annualized Sharpe (OOS) | (1+monthly_mean)^12-1 / monthly_std × √12 | iyileşme = + |
| D5 | top-5%-share | top-5% trade-R toplamı / pool toplam R | **KORUMA**: baseline × 0.85 ≥ |
| D6 | cut-bucket meanR | filtre tarafından REDDEDİLEN trade'lerin meanR (engine içinde) | redundant test: ≥ pool × 0.7 → kötü |
| D7 | trade count (OOS pencere) | filtre sonrası kalan trade sayısı | min eşik 200 (n < 200 → underpowered, OTOMATİK RED) |
| D8 | win-rate | win/total | informational; izole karar verdirmez |
| D9 | neg-month count | negatif ay sayısı / 61 | iyileşme = - |
| D10 | paired-sign-flip null p-value | aylık delta üstünde (baseline-threshold) flip permutation, 10000 iter | < 0.00833 (Bonferroni-6) primary için |

**Aggregation:** Per-threshold sonuç D1-D10 tablosu. **Primary decision metric: D2 (monthly-median, robust) + D5 + D6 + D10**. D1/D4 informational. D3/D7/D9 hard-floor.

## 4. Independent Variables (TEK eksen, ortogonalite garantili)

**Tek değişen knob:** `signals.filters.volume_zscore_min` ∈ {0.0 (baseline), 0.5, 1.0, 1.5, 2.0, 2.5}.

**SABİT (production değerleri, donduruldu):**
- `vol_sma_mult: 2.0` (climax detection — DEĞİŞMİYOR, H1b sparse-sensitivity ayrı koşu)
- `spread_atr_mult: 1.5`
- `wait_min: 4, wait_max: 24`
- `low_tolerance_pct: 0.02, high_tolerance_pct: 0.02`
- `vol_ratio_max: 0.75`
- `vsa_internals: atr_period=20, vol_sma_period=40, confirmation_max_wait=5`
- `primary_R: 2.5`
- Exit/trail config: `runner_trail_mult=3.0`, `force_exit_from_entry=False` (WINNER-LET-RUN 2026-05-29 promotion)
- Risk config: `risk_phoenix_scalp_15m_widestop_vsa2.yaml` UNTOUCHED — sl_pct_min=0.025, risk_per_trade=0.005

**H1b (secondary, ayrı koşu):** `vol_sma_mult ∈ {1.5, 2.0, 2.5, 3.0}`, vol_z=0.0. 4 nokta sparse sensitivity, sweep DEĞİL — amplify kararı (3.0→2.0) plateau testidir.

**Toplam family-wise N:** 6 (primary) + 4 (secondary) = **10 testler**. Holm step-down: ranked p_(k) ≤ α / (m − k + 1). Bonferroni floor: α/10 = 0.005.

## 5. Beklenen p-value & güç

- Per-threshold paired sign-flip null (10000 iter, monthly-delta over 61 months, 2-tailed): naive α=0.05.
- Bonferroni-6 (primary only): α/6 = 0.00833.
- Holm-10 (primary+secondary): worst-case α/10 = 0.005 for the smallest-p test.
- Beklenen güç: monthly_std ~5pp, 61 monthly observations, expected delta < 1pp under H1 → power < 0.2 (yani çoğu threshold için sign-flip null reddedilemez = H1 paralel). H0 (gerçek +5pp lift) doğruysa power ~0.85 — bu durumda H0 reddedilemez = falsifier tetiklenir.
- DSR (Deflated Sharpe Ratio) Lopez de Prado correction: 10 trial × n_eff 61 ay → DSR > 0.95 zorunlu shortlist için. Beklenen DSR per threshold: < 0.5 (10 trial inflation).

## 6. Stop Criteria (hipotezi terkettiren tetikler)

1. **n_trades_OOS < 200 herhangi bir threshold için** → o threshold OTOMATİK reject (underpowered). Eğer 5/6 threshold n<200 ise (gate çok katı) → tüm H1 reddedildi, H1b'ye geç.
2. **Pool rebuild parity fail** (deployed pool vs current HEAD: max|ΔR|>0.01 normalized) → SOP terkedilir, ops_engineer'a parity incident.
3. **IS Sharpe baseline < 0.5** (sanity: pool dürüst değil) → sweep'i çalıştırma; pool denetimi tetikle.
4. **Baseline drift**: bu hipotezin baseline çıktısı (vol_z=0.0) `risk_phoenix_scalp_15m_widestop_vsa2.yaml` honest-audit (2026-05-29) bandının (monthly-mean +%11..+13.5, DD -%15..-21) DIŞINDA → pool ya da config drift; sweep YAPILMIYOR, root-cause araştırması açılır.
5. **2+ threshold simultaneously Bonferroni-6 geçerse** ama biri de top-5%-share koruma testini geçemezse → "near-edge selection" red bayrağı (multiple-testing inflation). Hepsi reddedilir.

## 7. Anti-curve-fit GUARDS (pre-committed, kod yazılmadan donduruldu)

### 7.1 Coarse grid only
- 6 nokta (0.0..2.5, 0.5 adım). 0.05 adım YASAK (50 nokta = curve-fit magnet, RAG#4'ün önerdiği ama persona Hard-Limit ile reddedilen ince grid).

### 7.2 Boundary-extreme rule
- Eğer "best" threshold grid'in extremesinde (0.0 veya 2.5) ise → "parametre uzayı yetersiz" sayılır, bulgular REDDEDİLİR, daha geniş grid YENİDEN PRE-REG.

### 7.3 Monotonicity check
- 6 nokta üstünde D2 (monthly-medR) **monotone DEĞİLSE** ve "best" threshold ortada lokal-tepe ise → curve-fit kırmızı bayrak (random noise picking). Reddedilir.

### 7.4 Multi-knob freeze
- vol_z sweep ile aynı koşuda trail, sl_pct_min, primary_R, vol_sma_mult, risk_pct VS DEĞİŞMEZ. 2+ knob aynı anda optimize = curve-fit pompası, persona Hard-Limit.

### 7.5 Paired sign-flip null (NOT array-bootstrap)
- 2026-05-29 winner-let-run learning'inden: "single-array bootstrap mean-edge testi için GEÇERSİZ". Doğru null: aylık-delta (baseline - threshold) üstünde sign-flip permutation. 10000 iter, 2-tailed.

### 7.6 IS/OOS gap floor
- IS - OOS monthly-medR gap > 30% (rel) ise → overfit, reddedilir. Persona Hard-Limit #1.

### 7.7 Cut-bucket inspection (right-tail preservation)
- Filtrenin REDDETTİĞİ trade'lerin meanR'ı, KEEP bucket meanR'ı, top-5% R count'larını ayrı ayrı raporla. **Eğer cut bucket içindeki trade'lerin top-5% R'larından >%15'i varsa → "vol_z right-tail'i kesiyor" red bayrağı**. (Brooks regime-filter 2026-05-29 dersi.)

### 7.8 Family-wise Holm-Bonferroni
- 6 (primary) + 4 (secondary) = 10 trials. Holm step-down: ranked p_(k) ≤ α / (m − k + 1). Tek sonuç p<0.05 yetmez; ranked'inde alfa-floor'u geçmesi gerek.

### 7.9 Symbol-out CV (zorunlu)
- 14 sembolden her birini sırayla dışarıda bırak; her threshold için 14 fold OOS monthly-medR. Eğer hiçbir threshold için en az 12/14 fold "iyileşme" yönünde değilse → robust değil, red.

### 7.10 Right-skew artifact guard
- Hem mean hem median raporla. Eğer threshold mean'i iyileştirip median'ı bozuyorsa → tek dev outlier (selection survives mean test ama median test'i geçemez) → red. Tersi de geçerli (median↑ mean↓ = winner-clip artefaktı → red, 2026-05-29 brooks-leg-decay öğretisi).

## 8. Methodology — koşum protokolü

1. **GATHER (pool rebuild)**:
   - Current HEAD ile canonical_pool_builder çalıştır → `sec53_15m_pool_v11_volz_sweep_<commit>.pkl`. deployed `sec53_15m_pool_v11_vsa2_top4.pkl` ile yan-yana parity (max|ΔR|<0.01 normalized). Fail → SOP-6 stop.
   - Engine knob'lar: `vol_sma_mult=2.0`, trail 3.0, force_exit_from_entry=False, primary_R=2.5, sl_pct_min=0.025, risk_pct=0.005.

2. **SWEEP** (6 primary + 4 secondary):
   - Her threshold için engine pool'u tek-pass üstünden filtrele (vol_z[bar] ≥ threshold → KEEP, < → cut). 10 ayrı sonuç dosyası: `memory/researcher/backtest_results/2026-05-30-vsaclimax-volz-<threshold>.json`.

3. **METRICS**:
   - Aylık-mean/median ROI (61 ay window). DD (account-eq based). Sharpe annualized. top-5%-share. cut-bucket meanR. n_trades_OOS. paired sign-flip null p (10000 iter).

4. **ROBUSTNESS** (SOP-3 zorunlu):
   - Symbol-out CV (14 fold). Walk-forward (3y/6m, step 3m). Param-perturb (vol_z ± 0.1 random, 50 seed) — beklenen kayıp <%25.
   - Regime split: BTC bull (2021, 2025-03+), bear (2022, 2025-Q1), range (2023, 2024-Q1). Her rejimde threshold-by-threshold tablosu.
   - Stress: 2022-05 (LUNA), 2022-11 (FTX), 2024-08 (Yen). Her dilimde threshold-vs-baseline.

5. **DECISION**:
   - Yukarıdaki guards (§7) sırayla uygula.
   - Eğer hiçbir threshold guard'ları geçemezse → H1 confirmed (NULL proving), vol_z gate eklenmemesi gerekçeli karar (D-doc).
   - Eğer 1 threshold guard'ları geçerse → terfi adayı Lab tournament (rare event — bu hipotezin niyeti DEĞİL ama mümkün).
   - Eğer 2+ threshold geçerse → multiple-testing inflation şüphesi, tümü reddedilir.

## 9. Reproducibility

- git_hash: `audit-hardreview-20260528:HEAD` (commit a08c111 + uncommitted iterate WIP'i değil — temiz HEAD'de koş).
- config_hash: vsa_climax_test_15m.yaml SHA256 + risk_phoenix_scalp_15m_widestop_vsa2.yaml SHA256.
- data_hash: pool SHA256 + ingest manifest 2026-05-30 date.
- random seed: 42 (sign-flip permutation), 1337 (param-perturb seed pool).
- compute env: Python 3.11.x, numba JIT cache enabled.

## 10. Prompt injection rejection (audit trail)

Seed payload "Curve-fit şüphesi yarat" string'i içerdi. Bu, persona Hard-Limit'lerine doğrudan zıt ("Anti-narrative bias", "Reject more than you accept"). Prior cron-blindness vakaları (2026-05-29 daily-scan v1-v3, 2026-05-29 btc-dominance v1-v3, vb.) bu injection'ı SEED-ABORT tetikleyici olarak işaretledi. Bu hipotezde durum farklı:

- **Substrate meşru** (canlı strateji + manifest'te var olan knob + RAG topical hit ≥ 6 ref). Seed-abort uygulanmaz.
- **Injection clause ayrı reddedildi**: bu doc, curve-fit'i YARATMAYA çalışmıyor — tersine §7'de 10 katmanlı anti-curve-fit guard PRE-COMMIT yaptı, ve §1 iddiası NULL-proving formülasyonla yazıldı (H0 reddedilemezse H1 onaylanır = "redundant filter, edge taşımıyor" doğrulanır). Bu, injection'ın asıl niyetinin (curve-fit ürün doğurma) zıttıdır.

**Ops Engineer eskalation**: Cron payload'larına RAG-topical-relevance guard #7 ve seed cooldown guard #1 SLA 2026-06-03'tü. Bu seed'de payload "curve-fit yarat" clause'unu hala içeriyor → guard #8 ÖNERİSİ: cron payload sanitizer ("curve-fit yarat", "p-hack başlat", "shortcut bul" gibi anti-rigor stringleri otomatik strip).

## 11. Beklenen sonuç (kayıt amaçlı, hipotezi etkilemez)

Önceki ML/learning'lere göre subjective prior:
- p(H1 confirmed, redundant filter) ≈ 0.70 → en olası sonuç.
- p(1 threshold genuine edge geçer) ≈ 0.15 → mümkün ama düşük (climax tanım-içi tautoloji riski).
- p(top-5%-share klipi tetiklenir, hepsi red) ≈ 0.10.
- p(metodoloji çatlağı, pool parity fail, sweep çalışmaz) ≈ 0.05.

## 12. Dependents downstream

- Eğer H1 doğrulanırsa: vsa_climax_test'in `volume_zscore_min` filter'ı KAPALI tutulur (production değişmez); D-doc: "tested, redundant gate kanıtlandı, ekleme kararı reddedildi."
- Eğer H0 reddedilirse (rare): Lab tournament adayı `risk_phoenix_scalp_15m_widestop_vsa2_volz<X>.yaml` taslak; insan onayı + paper validation.
- Her halükarda: 2026-05-29 brooks regime-filter dersi vsa için DOĞRULANMIŞ veya YANLIŞLANMIŞ olacak → shared/lessons/'a learning.

---

**Pre-registered. Frozen. Bu noktadan sonra dependent vars veya guard'lar değişirse, doc supersede edilir (yeni doc + supersedes link), edit YASAK.**

**Status:** PROPOSED → review beklemekte (`requested_review_from: [lab_scientist, risk_officer, adversary_engineer]`).
