# Hipotez: HYP-2026-05-29-brooks-7fx-uncorrelated-legs

**Pre-registered BEFORE running 5-new-symbol backtests. Vol-targeting paranoia ON.**

## 0. Bağlam / Önceki Ders
- 3-FX brooks portföyü (EUR/USD, GBP/USD, USD/JPY): eff_r=3% → medyan +10.1%/ay, ama
  MC_medDD -41%, OOS medyan +0.0% (neg-ay %50). Sağ-çarpık, OOS'ta zayıf.
- Vol-targeting (HYP-2026-05-29-3fx-voltarget): H0 NOT REJECTED. Sizing overfit. RED.
- **Takeaway (learning.md):** lever sizing DEĞİL — UNCORRELATED positive-edge legs.
  Bağımsız aylık çarpıklıklar birbirini dengeler → std düşer → Sharpe artar.

## 1. İddia (ölçülebilir)
"brooks_failed_breakout'u 8 FX 4H sembolünde standalone çalıştırıp, SADECE kendi-başına
pozitif-edge (full net mR > 0 VE shuffle p<0.05 BH-FDR sonrası) VE düşük-korelasyonlu
sembollerden bir alt-küme seçip risk-parity portföy kurarsam; 7-bacaklı portföyün aylık-R
std'si 3-bacaklıdan DÜŞÜK, aylık Sharpe'ı YÜKSEK olur ve aynı MC_medDD'de medyan getirisi
artar. Hedef: bir eff_r seviyesinde medyan %15-20/ay VE MC_medDD ≤ -30% VE OOS-tutarlı."

## 2. Null Hipotez (Popper — ne olursa çürür)
- H0-a: Yeni 5 sembolün çoğu standalone NEGATİF veya shuffle-fail → eklenecek temiz bacak yok.
- H0-b: Bacak eklemek aylık-R std'sini DÜŞÜRMEZ (rho beklenenden yüksek; legs aynı USD makro
  faktörüne binmiş → effektif çeşitlenme yok). port_std/sum_std ratio 3fx≈0.642'den İYİLEŞMEZ.
- H0-c: 7fx Sharpe ≤ 3fx Sharpe (matched MC_medDD'de medyan free-lunch artmaz).
- H0-d: OOS'ta portföy edge'i ÇÖKER (IS-OOS Sharpe gap > %30) veya symbol-out CV bir sembole
  bağımlı (o sembolü çıkarınca portföy negatife döner) → diversification illüzyon.
- **Bunlardan herhangi biri tutarsa: 7fx genişletme REDDEDİLİR veya gerçekçi tavan raporlanır.**

## 3. Bağımsız Değişkenler
- Sembol seti (8): EUR/USD, GBP/USD, USD/JPY, AUD/USD, USD/CHF, EUR/GBP, USD/CAD, NZD/USD.
- Risk-parity ağırlık: her bacak eşit risk katkısı. AUD/USD+NZD/USD (+0.89 korel) TEK risk
  birimi → ikisinin per-trade risk'i yarıya bölünür (combined ≈ 1 bacak), ÇİFT sayılmaz.
- eff_r grid: {1,1.5,2,2.5,3,4}%.

## 4. Bağımlı Değişkenler (pre-registered metrikler)
- Standalone: full net mR, IS mR, OOS mR, shuffle p, BH-FDR pass.
- Portföy aylık: mean, MEDİAN, STD (asıl hedef — dağılım genişliği), min/max-ay, neg-ay%,
  continuous MaxDD, MC_medDD, MC_ruin, aylık Sharpe (mean_mo/std_mo).
- Çeşitlenme: 8x8 aylık-R korelasyon matrisi, mean pairwise rho, port_std/sum_std ratio.

## 5. Beklenti / Calibration (Tetlock)
- %60 ihtimal: 5 yeni sembolün ≥3'ü standalone pozitif-edge geçer (brooks USD-trap geneldir).
- %55 ihtimal: 7fx port_std/sum_std ratio < 0.642 (3fx'ten daha iyi çeşitlenme).
- %40 ihtimal: matched -30% MC_medDD'de 7fx medyanı 3fx'i ≥ +2pp geçer.
- %25 ihtimal: medyan %15-20 VE MC_medDD ≤ -30% AYNI eff_r'de ULAŞILIR (yüksek bar; tahminim
  gerçekçi tavan ~%10-13 medyan @ -30% civarı; %15-20 muhtemelen -40%+ DD ister).
- %70 ihtimal: OOS Sharpe IS'in en az yarısı (gap < %50) — brooks her sembolde GO ise.
- Predictive interval (7fx medyan @ matched -30% MC_medDD): [+8%, +15%], merkez +11%.

## 6. Stop Criteria
- Standalone IS net mR < 0 → o sembol portföye GİRMEZ (zarar eden bacak çeşitlendirmez, F-serisi dersi).
- shuffle p ≥ 0.05 (BH-FDR sonrası) → portföye GİRMEZ.
- Symbol-out CV'de bir sembol çıkınca portföy medyanı negatife dönerse → "tek-bacak bağımlı", overfit şerhi.
- IS-OOS Sharpe gap > %50 → OOS-fragile, gerçekçi tavanı OOS sayılarıyla raporla.

## 7. Yöntem (lookahead-paranoia)
- symbol_trades() = fx.gather VERBATIM (aynı session/swap/slippage/atr filtreleri). NO param search.
- IS=[2020,2024) frozen, OOS=[2024,2026). Standalone seçim SADECE full+shuffle ile (OOS'a bakmadan select).
- Risk-parity replay: production_replay, AUD/NZD blok için per-trade risk yarı.
- Robustluk: WF (2y train/6m test/3m step), symbol-out CV, shuffle baseline OOS.
- Reproducibility: git_hash, data_hash, seed=12345.

## 8. Karar Kuralı
- Tüm seçili bacaklar standalone-pozitif + shuffle-pass + 7fx ratio < 3fx ratio + matched-DD medyan
  3fx'i geçer + symbol-out CV robust + OOS gap<%50 → "7fx genişletme GO, terfi adayı".
- Aksi → gerçekçi tavan + dürüst overfit şerhi ile raporla, RED veya PARTIAL.
