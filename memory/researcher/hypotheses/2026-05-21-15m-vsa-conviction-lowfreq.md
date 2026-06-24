# Hipotez: HYP-2026-05-21-15m-vsa-conviction-lowfreq

**Pre-registration — engine replay ÖNCESİ yazıldı. Immutable.**
Tarih: 2026-05-21 | Researcher | git: feat/pyramid-be-protect

## Bağlam
Researcher diagnostik (2026-05-21): 15m havuzunda 4 strateji honest mR:
- vsa_climax_test: honest mR **+0.181**, honest sumR **+7.421 R** (TEK pozitif)
- brooks_failed_breakout: honest mR −0.253, honest sumR −55.753 R
- anchored_vwap_reversal: honest mR −0.381, honest sumR −39.552 R
- engulfing_continuation: honest mR −0.227, honest sumR −2.038 R

vsa_climax_test tek başına dürüst pozitif. Geniş-stop ile birleşince:
- vsa + sl_pct ≥ %1.5: honest mR **+0.644**, honest sumR **+14.576 R**, n=22.636
- vsa + sl_pct ≥ %1.8: honest mR **+0.788**, honest sumR **+13.269 R**, n=16.844

Frekans: vsa-only 2.2 trade/sym/gün (full pool 20.5'in 1/10'u) → düşük fee yükü.
Bu, "yüksek konviksiyon + düşük frekans + geniş stop" üçlüsünün somut adayı.

## İddia (H1)
**15m havuzunu yalnız vsa_climax_test stratejisine + sl_pct ≥ %1.5 geniş-stop
filtresine indirgemek, dürüst maliyet (+55bps) altında engine replay'de aylık
mean ROI ≥ %10 üretir — düşük frekans (819 trade/sym/yıl) fee yükünü kırar,
yüksek per-trade R (honest mR +0.64) edge'i taşır.**

## Null hipotez (H0)
vsa+wide-stop alt-kümesi honest pool-R pozitif AMA replay aylık mean < %10 —
düşük frekans aynı zamanda equity compounding fırsatını da kısıyor (az trade =
az bileşik). Çürütür: aylık mean < %10 VEYA WF OOS neg > %33 VEYA shuffle p ≥ 0.05.

## Bağımlı değişkenler (pre-registered)
- Aylık mean / medyan ROI, neg ay (61), max aylık kayıp
- Yıllık compound, top-5 ay HARİÇ yıllık
- r-adj, CV, honest pool-sumR
- WF OOS neg pencere oranı
- Trade frekansı (compound fırsat maliyeti teşhisi)

## Bağımsız değişkenler
- Strateji alt-kümesi: {vsa-only, vsa+brooks-wide, vsa+all-wide}
- sl_pct eşiği: {0.012, 0.015, 0.018}
- risk %: {2%, 3%} (düşük frekansta daha yüksek risk taşınabilir mi)

## Kabul kriteri (HARD gate)
1. Honest pool-sumR > 0
2. Engine replay aylık mean ROI ≥ %10
3. Neg ay ≤ 12/61
4. Top-5 ay HARİÇ yıllık > 0
5. WF OOS neg pencere ≤ %33
6. Shuffle baseline p < 0.05
7. Symbol-out CV: her sembol tek tek çıkarıldığında aylık mean sapma < %30

## Çoklu test düzeltmesi
3 alt-küme × 3 sl_pct × 2 risk = 18 test. Bonferroni α = 0.05/18 = 0.00278.
DSR WF Sharpe'a uygulanır.

## Önsel tahmin
vsa+wide honest pool-R pozitif kalacak (+13-14k R). AMA düşük frekans (n=22k,
full pool'un %6'sı) → engine compound fırsatı kısıtlı. Tahminim aylık mean
**%5-9** — %10 sınırda veya altında. risk %3 ile %10'a yaklaşabilir ama DD de
büyür. Verdict tahminim: **RED-BORDERLINE veya MARGINAL-PASS** — vsa tek geçerli
15m strateji ama tek başına %10/ay zor; en iyi senaryo paper-trade adayı.

## Stop criteria
Honest pool-sumR negatifse anında RED. Aylık mean < %5 ise sweep durdur.

---

## SONUÇ — PARTIAL / SUPERSEDED (2026-05-22)

vsa_climax_test tek başına dürüst pozitif (honest sumR +7.421 R), vsa+wide-stop
honest mR +0.64 doğrulandı. AMA aylık-mean replay'de vsa-only düşük frekans
nedeniyle wide-stop-all'dan DAHA AZ getirir:
- vsa-only honest +55bps: aylık mean düşük, neg ay yüksek (frekans yetersiz).
- vsa + sl≥0.015: pozitif ama wide-stop-all (HYP-1) daha güçlü.

**Bulgu:** vsa konviksiyonu gerçek ama "yalnız vsa" gereksiz kısıtlama —
HYP-1'in sl_pct filtresi zaten tüm stratejilerin wide-stop kuyruğunu seçiyor ve
brooks wide-stop kuyruğu da (honest sumR +13.148 R, sl≥%2.5) pozitif. vsa-only
filtresi compound fırsatını kısıyor. Bu hipotez HYP-1 tarafından SUPERSEDE edildi:
"strateji-agnostik wide-stop filtre" > "tek-strateji konviksiyon filtre".
Önsel tahmin (RED-BORDERLINE/MARGINAL) yön olarak doğru — vsa tek başına %10/ay zor.
