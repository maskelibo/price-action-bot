# Hipotez: HYP-2026-05-29-brooks-8fx-leg-decay-causal-reweight

**Pre-registered BEFORE writing reweight code. Lookahead/overfit paranoia ON. Combo-C.**

## 0. Bağlam / Önceki Dersler
- brooks 8-FX risk-parity portföy (EUR/USD, GBP/USD, USD/JPY, AUD/USD, USD/CHF, EUR/GBP,
  USD/CAD, NZD/USD), honest cost, netUSD<=3 cap, block-bootstrap MC. Eşit-ağırlık baseline.
- Teşhis (IS->OOS standalone mR): USD/CHF +0.677->+0.222, EUR/GBP +0.609->+0.141,
  USD/JPY +0.495->+0.321 ZAYIFLADI; AUD/CAD/NZD GÜÇLENDİ. Bazı bacaklar "decay" gösteriyor.
- **Önceki ders (regime-filter FALSIFIED, learning.md):** F5 statik decay-downweight
  (USD/CHF & EUR/GBP'ye 0.5x) IS'te baseline'ı düşürdü — ÖLDÜ. O bir LOOKAHEAD seçimdi
  (tam-örnekteki decay'e bakıp bacak seçti). Sağ-çarpık edge'te downweight = kazanan-katliam riski.
- **Bu hipotez farklı:** statik post-hoc seçim DEĞİL, her noktada SADECE geçmiş (trailing)
  performansa göre ağırlık. Nedensel. Geleceğe bakmıyor.

## 1. İddia (ölçülebilir)
"Her çeyrek (quarter) rebalans noktasında, her bacağın portföy ağırlığını SADECE trailing-Nay
(N in {12,18}) rolling performansına (mean-R veya rolling-Sharpe, taban=0) orantılı belirlersem
(zayıflayan bacak otomatik küçülür, lookahead YOK); nedensel-reweight portföy, eşit-ağırlık
portföyüne kıyasla OOS'ta robust-medyan veya aylık-Sharpe'ı İYİLEŞTİRİR (ΔrobMed >= +1pp VEYA
ΔmoSharpe >= +0.05, neg-ay artmadan, DD kötüleşmeden)."

## 2. Null Hipotez (Popper — ne olursa çürür)
- H0-a (decay GÜRÜLTÜ): USD/CHF/EUR/GBP/USD/JPY'nin rolling mean-R eğimi istatistiksel anlamlı
  DEĞİL — küçük-n sağ-kuyruk varyansı. Rolling-Sharpe slope CI sıfırı kapsıyor; OLS slope p>=0.05.
  Decay gerçek bir trend değilse, ona göre reweight yapmak gürültüyü kovalamaktır.
- H0-b (reweight YARDIM ETMEZ): Nedensel-reweight portföyün OOS robMed'i & moSharpe'ı
  eşit-ağırlığı GEÇMEZ (ΔrobMed < +1pp VE ΔmoSharpe < +0.05). Trailing performans gelecek
  performansı predict etmiyor (no persistence) -> reweight = gürültü transformu.
- H0-c (reweight ZARARLI): Reweight neg-ay'ı artırır VEYA DD'yi kötüleştirir VEYA medyanı düşürür
  -> aktif kötüleşme (trailing-momentum chasing forex-mean-reversion'da ters tepebilir).
- **Herhangi biri tutarsa: nedensel reweight REDDEDİLİR; eşit-ağırlık+netUSD-cap yeterli ilan edilir.**

## 3. Bağımsız Değişkenler
- Rebalans frekansı: quarterly (3 ay). (Aylık de yan-test edilebilir.)
- Trailing pencere: N in {12, 18} ay.
- Skor: (i) trailing mean-R, (ii) trailing rolling-Sharpe (mean/std). Taban=0 (negatif skor -> ağırlık 0).
- Ağırlık tahsisi: skor-orantılı (skor/sum_skor), normalize. AUD/NZD blok yine 0.5 risk-parity.
- KARŞILAŞTIRMA bazı: eşit-ağırlık risk-parity (mevcut baseline).

## 4. Bağımlı Değişkenler (pre-registered)
- (a) DECAY GERÇEKLİĞİ: her bacağın yıl-yıl mean-R, rolling-12ay mean-R trend, OLS slope + p-value,
  rolling-Sharpe slope. Permütasyon/shuffle ile slope null. (Falsifiable: küçük-n varyansı mı?)
- (b) Portföy aylık: robust medyan (winner-stripped), STD, continuous MaxDD, block-bootstrap medDD,
  neg-ay%, aylık Sharpe. IS + OOS AYRI.
- (c) NET: ΔrobMed(OOS), ΔmoSharpe(OOS), ΔDD(OOS) reweight - eşit.
- (d) STATİK DROP (referans, LOOKAHEAD'li — sadece tavan): en zayıf 1-2 bacağı tam çıkarınca.

## 5. Beklenti / Calibration (Tetlock)
- %35 ihtimal: en az bir decayed bacağın OLS rolling-Sharpe slope'u p<0.05 anlamlı (yani decay GERÇEK).
  (Tahminim: çoğu "decay" küçük-n varyansı; n_OOS bacak başına 60-130 trade, 2 yıl = dar.)
- %25 ihtimal: nedensel-reweight OOS robMed'i eşit-ağırlığı >=+1pp geçer.
- %20 ihtimal: nedensel-reweight OOS moSharpe'ı >=+0.05 geçer.
- %55 ihtimal: H0-b tutar (reweight gürültü transformu, OOS'ta nötr/negatif) — forex-mean-reversion'da
  trailing-momentum genelde persist ETMEZ; reweight ekstra serbestlik derecesi getirir, gain getirmez.
- %15 ihtimal: reweight aktif ZARARLI (H0-c).
- Predictive interval (ΔrobMed OOS reweight - eşit): [-2pp, +1.5pp], merkez ~-0.2pp (nötr-hafif negatif).

## 6. Stop Criteria
- Decay slope hiçbir bacakta p<0.05 değilse -> "decay gürültü" ilan, reweight zayıf-gerekçeli ama yine test.
- Nedensel reweight IS'te bile eşit-ağırlığı geçmiyorsa (ΔrobMed_IS < 0) -> OOS'a taşıma, RED.
- Reweight serbestlik derecesi (N, freq, skor tipi) içinde en iyi varyant OOS'ta seçilirse = p-hacking;
  bunun yerine TÜM varyantlar raporlanır, multiple-testing not edilir, "best OOS" deploy önerisi YAPILMAZ.

## 7. Yöntem (lookahead-paranoia)
- Trade'ler /tmp/rt_trades.pkl (brooks_portfolio_7fx.gather VERBATIM, honest cost). Yeni gather YOK.
- Reweight CAUSAL: rebalans noktası t'de ağırlık = SADECE [t-N ay, t) trade'lerinden. Entry bar t dahil değil.
- Ağırlık trade'in R'ine çarpan (risk_pct'e eşdeğer fixed-fractional). production_replay engine-faithful.
- IS=[2020,2024) frozen, OOS=[2024,2026). Reweight kuralı IS'te tune EDİLMEZ (parametresiz heuristik grid, hepsi raporlanır).
- Statik drop SADECE referans tavan; deploy önerisi değil (lookahead'li, açıkça etiketli).
- Reproducibility: git_hash, data_hash(pkl), seed=12345.
