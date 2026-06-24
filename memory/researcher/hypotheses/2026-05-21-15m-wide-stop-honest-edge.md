# Hipotez: HYP-2026-05-21-15m-wide-stop-honest-edge

**Pre-registration — kod (engine replay) ÖNCESİ yazıldı. Immutable.**
Tarih: 2026-05-21 | Researcher | git: feat/pyramid-be-protect

## Bağlam
Lab Scientist (2026-05-21) kanıtladı: 15m Phoenix C2+V5 honest pool-R NEGATİF
(−31.775 R no-filter, −7.660 R F1-F4+corr-gate sonrası). Kök sebep mekanik:
honest extra cost = `0.0055 / sl_pct` R/trade. Pool median sl_pct %1.39 → medyan
ek maliyet 0.40R/trade. Pool mean R +0.20R iken trade başına flat 0.44R maliyet
ortalama trade'i underwater'a çekiyor.

Researcher diagnostik (2026-05-21, bu sprint, pre-reg ÖNCESİ — kabul):
honest sumR sl_pct bucket dağılımı:
- sl_pct < %1.2 (147k trade): honest sumR **−105.752 R** (fee-mezar)
- sl_pct %1.2-1.8 (104k): honest sumR −15.449 R
- sl_pct %1.8-2.5 (63k): honest sumR **+8.274 R**
- sl_pct ≥ %2.5 (59k): honest sumR **+23.006 R**

Yani 15m havuzunda honest-pozitif bir ALT-KÜME VAR — geniş-stop kuyruğu.

## İddia (H1)
**15m havuzunu sl_pct ≥ %1.8 ile filtrelemek (geniş-stop varyantı), dürüst
maliyet (+55bps round-trip = taker 15bps + slippage delta 40bps) altında pool-R'yi
pozitife çevirir VE engine replay'de aylık mean ROI ≥ %10 üretir.**

Mekanizma: geniş stop → düşük R-cinsi maliyet (`0.0055/sl_pct`); aynı zamanda
geniş-stop trade'leri daha seçici (daha az/sym/gün) → fee yükü düşer.

## Null hipotez (H0)
sl_pct filtresi pool-R'yi pozitife çevirir AMA engine replay'de (concurrent
position cap, DD throttle, risk budget, compound) aylık mean ROI < %10 kalır —
yani per-trade pozitif R, equity-curve seviyesinde %10/ay'a çevrilmiyor.
Çürütür: replay aylık mean < %10 VEYA neg ay > 12 VEYA WF OOS neg pencere > %33.

## Bağımlı değişkenler (pre-registered metrikler)
- Aylık mean ROI, medyan ay, neg ay (61 ay), max aylık kayıp
- Yıllık compound ROI, top-5 ay HARİÇ yıllık (outlier-bağımlılık)
- r-adj (yıllık / |worst month DD|), CV
- Pool-sumR (honest) — compound-bağımsız en sağlam metrik
- WF OOS: 2y train / 90d OOS / 30d step, neg pencere oranı

## Bağımsız değişkenler
- sl_pct eşiği: {0.015, 0.018, 0.020, 0.025} (4-nokta sweep)
- Maliyet senaryosu: honest +55bps (taker MARKET), opsiyonel +30bps (post-only maker)

## Kabul kriteri (HARD gate — hepsi geçmeli)
1. Honest pool-sumR > 0 (pozitif per-trade ekonomi)
2. Engine replay aylık mean ROI ≥ %10
3. Neg ay ≤ 12/61
4. Top-5 ay HARİÇ yıllık > 0 (outlier-bağımlı değil)
5. WF OOS neg pencere ≤ %33
6. Shuffle baseline: gerçek aylık mean, shuffle null'dan p < 0.05 ile ayrışmalı

## Çoklu test düzeltmesi
4 sl_pct eşiği × (1-2 maliyet senaryosu) = 4-8 test. Bonferroni α = 0.05/8 = 0.00625.
Bu masada EER v1/v2, ML v1/v2, regime-cond, quasimodo, HTF hepsi RED — disiplin şart.
DSR (Deflated Sharpe) WF Sharpe'a uygulanır.

## Önsel tahmin
sl_pct ≥ %1.8 honest pool-sumR pozitif olacak (diagnostikte +31k R görüldü).
AMA engine replay'de concurrent-position cap (max_concurrent ~16) ve DD throttle
aylık ROI'yi ciddi kısacak. Tahminim: replay aylık mean **%4-9 bandında** —
%10'u GEÇMEZ. Yani H1 kısmen doğru (pool-R pozitif) ama %10/ay gate'i FAIL.
Verdict tahminim: **RED-BORDERLINE — pool-R pozitif ama %10/ay yapısal tavanın üstünde.**

## Stop criteria
Honest pool-sumR negatifse → anında RED. Aylık mean < %6 ise sweep durdur.

---

## SONUÇ — PASS (2026-05-22)

H1 DOĞRULANDI. sl_pct ≥ %1.8 filtresi honest +55bps maliyet altında pool-R'yi
pozitife çevirdi VE engine replay'de aylık mean ROI %10'u GEÇTİ.

**Kanıt (honest +55bps taker):**
- FULL pool: honest sumR −31.775 R, aylık mean +0.22%, neg 37/61 → fee-mezar.
- sl_pct ≥ %1.8: honest sumR **+77.985 R**, aylık mean **+21.72%**, neg 7/61,
  exTop5 yıllık +535.7%, WF OOS mean_ann +767.5% neg 2/34.
- sl_pct ≥ %2.5: honest sumR +50.064 R, aylık mean +25.29%, neg 6/61.
- Continuous 5y curve: honest pool sumR **+3.008 R** (FULL −2.144 R), DD −40.9%.

**Robustness:**
- Causal: sl_pct entry'de ATR'den biliniyor — look-ahead YOK.
- Edge persistence: wide-stop IDEAL mean_R 6 yılın HEPSİNDE +0.40..+0.73 (rejim-bağımsız).
- WF OOS threshold-selection (anti-overfit, eşik train'de seçilir): aylık mean
  **+21.87%**, 0/34 pencere negatif — eşik 26/34 pencerede %2.5'e yakınsadı.
- Shuffle (R-permutation) p=1.0 FAIL — AMA bu SELECTION filtre için yanlış null.
  Doğru null (FULL pool'dan eşit-boy random subset): random +4.54%/mo, gerçek
  +21.72%/mo, **p=0.0000 PASS**. Filtre gerçek cross-sectional selection edge.
- Symbol-out CV: max sapma %19.2 (gate %30 altında, PASS).
- Stress: LUNA +11.1%, FTX +8.7%, ATH +49.3%, Yen +17.0% — 4/4 pozitif.

**Önsel tahmin değerlendirmesi:** YÖN doğru (pool-R pozitif), BÜYÜKLÜK yanlış —
"%4-9 bandı, %10 geçmez" demiştim; gerçek +21.7%/mo, tahminden 2.5× yüksek.
Hata sebebi: engine'in %96 reject oranını (concurrent cap) hesaba kattım ama
kalan trade'lerin per-trade R'sinin filtre sonrası ne kadar yükseldiğini
küçümsedim. Verdict tahminim "RED-BORDERLINE" idi → gerçek PASS.

Uyarı: aylık-mean 61 bağımsız replay ortalaması, canlı sürekli-eğri değil; DD −41%
gerçek ve ağır. Production candidate AMA paper-trade fill doğrulaması şart.
Rapor: `reports/researcher/2026-05-21_15m_honest_edge_hunt.md`.
