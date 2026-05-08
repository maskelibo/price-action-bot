---
hypothesis_id: vol_risk_premium_fade
date: 2026-05-09
status: TESTING
author: researcher-agent
strategy_file: src/price_action/strategies/vol_risk_premium.py
backtest_script: scripts/run_vol_premium_backtest.py
tests_file: tests/test_vol_risk_premium.py
---

# Volatility Risk Premium Fade — Hipotez Dokümanı

## Özet

Kriptoda gerçekleşmiş volatilite (Realized Volatility, RV) yüksek kalıcılık (vol clustering)
ve ortalamaya dönüş (mean-reversion) özelliği sergiler. RV 95. yüzdeliğe (%+2σ) ulaştığında
— ve bir sonraki bar fiyat hareketi daraldığında (inside-bar veya doji) — piyasa "korku
premium"unu fiyatlamıştır; gerçekleşmiş vol büyük olasılıkla yakın vadede küçülecektir.
Bu strateji: spike'a karşı yön, volatilite geri dönene kadar tutma.

## Teorik Temel

### Euan Sinclair — Volatility Trading Prensipleri

Sinclair'in merkezi tezi: piyasa, gelecekteki volatiliteyi sistematik olarak aşırı fiyatlar
(Volatility Risk Premium, VRP). Bunun kripto ortamındaki uzantısı:

- Spot/perp piyasalarında "implied vol" proxy'si: anlık fonlama oranı ve opsiyon yoksa
  ATR%'nin 30-bar ortalamasına oranı.
- RV sürekli olarak implied vol'un altındadır (istatistiksel bulgular: BTC'de ~%15-25
  VRP median, yüksek korku dönemlerinde %40-60'a ulaşır).
- Bu premium, vol satıcısına uzun vadede sistematik pozitif beklenti sağlar.

### Larry Harris — Mikroyapı Bağlantısı

Harris'in spread-volatilite ilişkisi (inventory cost ∝ σ²): bir vol spike'ında market maker'lar
spread'i agresif genişletir. Bu genişleme, spread daralmasına (normalizasyona) yaklaşıldıkça
tersine döner. Harris'in "News-Driven Spread Blowout Fade" (Setup 4) vol-fade hipotezimizin
mikroyapı gerekçesidir: aşırı vol → aşırı spread → normalleşme → fiyat ve volatilite geri döner.

### Ernest Chan — GARCH / Vol Clustering

Chan'in Setup 7 (Volatility Breakout): yüksek vol sonrası düşük vol olasılığı artar (GARCH etkisi).
Bizim hipotezimiz Setup 7'nin tersidir: vol spike (yüksek GARCH rejimi girişi) → ortalamaya dönüş
beklentisi. Chan'in "Volatility-Momentum" bölümünde: "Yüksek VIX → mean-reversion çalışır" tezi
doğrudan hipotezimizi destekler.

### Kriptoya Özgü Dinamikler

1. **Vol Clustering (GARCH):** BTC/ETH 1d veride GARCH(1,1) parametreleri: α+β ≈ 0.95-0.98 —
   güçlü kalıcılık ama mean-reversion de güçlü (uzun vadeli ortalamaya çekilme).
2. **Likidite rejimi:** Vol spike'larında Harris'in "liquidity withdrawal" mekanizması devreye girer
   (HFT market maker'ları çekilir, spread patlar). Normalleşme ~2-5 günde gerçekleşir.
3. **Leverage over-extension:** Perp piyasalarında vol spike, çoğunlukla büyük tasfiyelerle
   (liquidations) eş zamanlıdır. Tasfiye tamamlandıktan sonra yön baskısı azalır.
4. **Round-number magnet:** Spike sonrası fiyat bir sonraki yapısal destekte/dirençte durur;
   bu nokta ATR normalizasyonu ile çakışır.

## AVWAP/TPO'dan Fark — Neden Farklı Mekanizma?

AVWAP Reversal (REJECTED): Fiyatın AVWAP'a geri dönüşünü umuyor. Sorun: güçlü trend rejimlerinde
fiyat AVWAP'a dönmez; değer merkezi kayar.

TPO Value Area (REJECTED): Fiyatın value area'ya geri dönüşünü umuyor. Sorun: aynı sorun.
Fiyat dağılımı shift ediyor.

**Vol Risk Premium Fade:** Volatilite dağılımını alınıyor — fiyatı değil. Kritik ayrım:

- Fiyat mean-reversion: Fiyat A'ya gidip B'ye döner. Crypto trend'de bu çalışmaz.
- Volatilite mean-reversion: ATR(%) X'e çıkıp ortalamasına döner. Bu çalışır çünkü vol
  clustering + GARCH ortalamaya çekilme matematiksel olarak kanıtlanmış.

Yani: fiyat yönü önemli değil. Fiyat spike yönünde devam edebilir — ancak ATR'nin büyüklüğü
küçülür. Biz bu küçülmeden para kazanıyoruz.

## Açık Riskler

1. **Trend riski:** Spike gerçek bir kırılımın başlangıcıysa (trend change), vol küçülmeyebilir.
   Azaltma: Contraction bar (inside-bar/doji) confirmation zorunluluğu.
2. **Küçük R hedefi (1.5R):** Vol fade hızlıdır ama price move devam edebilir → trend'e karşı.
   Azaltma: Sıkı SL (structural + 1 ATR), TP 1.5R (aggressive exit).
3. **Sample size:** Vol spike 95. yüzdelik nadir bir olaydır; 3 yıl 10 sembol ~50-100 sinyal.
   Bu sayı, istatistiksel anlamlılık için yeterli ama marginaldir.
4. **Slippage spike döneminde:** Harris: vol spike = spread blowout. Spike anında execution
   maliyeti normalin 3-5x'idir. Mitigation: entry bir sonraki barın AÇILIŞINDA (contraction
   confirmation bar kapanışından sonra — gecikme kaçınılmaz ama daha temiz fill).
5. **Yanlış contraction:** Inside-bar bazen "breath before next leg" (devam hareketi öncesi
   nefes alma) demektir. Bu en büyük hata kaynağıdır.

## Sinyal Mantığı

```
Bar T-1: ATR%(T-1) > 2x median30 → SPIKE BAR
Bar T  : inside-bar(T, T-1) OR doji(T) → CONTRACTION CONFIRMATION
Entry  : T+1 açılışında, spike yönünün tersi
SL     : spike extreme + 1 ATR buffer (yapısal)
TP     : 1.5R (vol fade hızlı ama sınırlı)
```

Bullish spike (büyük yeşil bar) → SHORT (fade)
Bearish spike (büyük kırmızı bar) → LONG (fade)

## Hipotez Puanı (Backtest Öncesi Beklenti)

- Win rate beklentisi: %52-60 (vol ortalamaya her zaman döner, ama hız ve miktar değişir)
- R hedefi: 1.5R (düşük — vol fade hızlı ama fiyat momentum devam edebilir)
- Beklenen Sharpe: 0.6-1.0 (price-based mean rev'den yüksek olmalı, trend-following'den düşük)
- Trade frekansı: az (95. yüzdelik spike + contraction = nadir = ~30-60 trade/3y/sembol)
- Failure modu: BTC boğa dönemlerinde büyük yeşil barlar sistematik devam eder → kısa pozisyon
  zincirleme zarar üretir. Bu yüzden: RSI > 80 filtresini değerlendir (overbought olmayan spike'larda
  daha iyi çalışır).

## Karar Kriterleri

- PROMOTE: Avg Sharpe > 1.0, Win rate > 52%, MaxDD < 25%
- DEFER:   Sharpe 0.5-1.0, refinement gerekiyor
- REJECT:  Sharpe < 0.5 veya win rate < 48% (random)
