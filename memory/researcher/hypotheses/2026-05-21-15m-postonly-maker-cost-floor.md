# Hipotez: HYP-2026-05-21-15m-postonly-maker-cost-floor

**Pre-registration — engine replay ÖNCESİ yazıldı. Immutable.**
Tarih: 2026-05-21 | Researcher | git: feat/pyramid-be-protect

## Bağlam
İki erozyon kaynağı var: (a) round-trip maliyet, (b) tight stop → yüksek R-maliyet.
HYP-wide-stop (a)'yı stop genişletip (b)'yi çözmeye çalışıyor. Bu hipotez
ortogonal koldan gider: maliyetin KENDİSİNİ düşür.

Execution Chief + Analyst bağımsız: post-only maker geçişi taker 15bps'i maker
~5bps (hatta rebate'li negatif) yapar; slippage delta'sı da düşer (limit fill,
piyasa-emir kayması yok). Honest re-baseline +55bps idi (fee 15 + slip 40).
Post-only senaryosu: fee ~5bps + slippage ~10bps = **+15bps round-trip** — yani
maliyet 55→15 bps, 3.7× azalma.

## İddia (H1)
**15m havuzu, post-only maker execution ile (+15bps round-trip, fee 5 + slip 10)
fee-mezardan çıkar; tam havuz (sl_pct filtresiz) honest pool-R pozitife döner VE
wide-stop filtresiyle birleşince engine replay aylık mean ROI ≥ %10 üretir.**

## Null hipotez (H0)
Post-only +15bps maliyet bile 15m tight-stop havuzunu kurtarmaz — median sl_pct
%1.39'da +15bps hâlâ 0.108R/trade maliyet; pool mean R +0.20R'nin yarısı.
VEYA: post-only fill rate < %60 (limit emir dolmaz, fırsat kaçar) → gerçek
canlıda taker fallback'e düşer, +15bps varsayımı geçersiz.
Çürütür: post-only senaryosunda bile pool-sumR ≤ 0 VEYA replay aylık mean < %10.

## Bağımlı değişkenler (pre-registered)
- Honest pool-sumR: +15bps senaryosu vs +55bps senaryosu
- Engine replay aylık mean / medyan, neg ay, max aylık kayıp
- Yıllık compound, top-5 ay HARİÇ
- r-adj, CV, WF OOS neg pencere

## Bağımsız değişkenler
- Maliyet senaryosu: {+15bps post-only, +30bps mixed, +55bps taker}
- sl_pct eşiği: {0.0 (filtresiz), 0.012, 0.018}

## Kabul kriteri (HARD gate)
1. +15bps senaryosunda honest pool-sumR > 0
2. +15bps + sl_pct filtre kombinasyonunda engine replay aylık mean ≥ %10
3. Neg ay ≤ 12/61
4. Top-5 ay HARİÇ yıllık > 0
5. WF OOS neg pencere ≤ %33
6. KRİTİK UYARI: bu hipotez post-only fill rate ≥ %60 VARSAYIMINA bağlı —
   o doğrulanmadan PASS verilemez. Fill rate < %60 ise hipotez "koşullu-PASS"
   en fazla, production'a alınmaz.

## Çoklu test düzeltmesi
3 maliyet × 3 sl_pct = 9 test. Bonferroni α = 0.05/9 = 0.00556.

## Önsel tahmin
+15bps senaryosu pool-sumR'ı kesin yukarı çeker. Filtresiz havuzda bile
muhtemelen pozitife yakın/hafif pozitif. sl_pct≥%1.8 + 15bps ile honest mR
belirgin pozitif (~+0.40-0.50R), replay aylık mean **%10-20 bandı MÜMKÜN**.
AMA: post-only fill rate varsayımı SAVUNMASIZ NOKTA. Execution Chief 15m'de
post-only +%0.5/ay katkı dedi → maker geçişi tek başına yetmez, wide-stop ile
BİRLİKTE gerekir. Verdict tahminim: **KOŞULLU-PASS** — wide-stop + post-only
kombinasyonu %10/ay'ı GEÇEBİLİR, ama fill-rate doğrulaması (paper trade) şart.

## Stop criteria
+15bps senaryosunda bile pool-sumR negatifse → 15m kesin RED, tüm hipotez zinciri kapanır.

---

## SONUÇ — KOŞULLU-PASS (2026-05-22)

H1 kısmen doğrulandı. +15bps post-only maliyet 15m'i belirgin iyileştiriyor:
- FULL pool +15bps: honest sumR **+128.336 R** (POZİTİF — +55bps'te −31.775 R idi),
  aylık mean +13.61%, neg 11/61. Yani post-only TEK BAŞINA bile filtresiz havuzu
  pozitife çeviriyor.
- wide sl≥%1.8 + 15bps: honest sumR +103.586 R, aylık mean +29.37%, neg 4/61.
- Continuous 5y curve wide+15bps: pool sumR +4.193 R, WR %43.5.

**KRİTİK UYARI doğrulandı:** Bu hipotezin tamamı post-only fill rate ≥%60
varsayımına bağlı. Execution Chief'in "15m post-only +%0.5/ay" bulgusu, post-only
tek başına yetmez demek; ama maliyet matematiği gösteriyor ki +55→+15bps geçiş
honest sumR'ı +160k R yukarı çekiyor. Çelişki değil: Execution Chief idealize
(zaten pozitif) tablo üzerinde +%0.5 ölçtü; honest tabloda etki devasa çünkü
maliyet baseline'ı 3.7× düşüyor.

**Verdict: KOŞULLU-PASS** — post-only fill rate ≥%60 paper-trade'de doğrulanırsa
+15bps senaryosu geçerli; doğrulanmazsa +55bps taker senaryosu (HYP-1 wide-stop)
geçerli kalır. İki kol da %10/ay'ı geçiyor — post-only EK güvenlik marjı, wide-stop
ZORUNLU temel. Önsel tahmin (KOŞULLU-PASS) doğru çıktı.
Rapor: `reports/researcher/2026-05-21_15m_honest_edge_hunt.md`.
