---
source_id: chan_summary
source_type: book
author: Ernest P. Chan
title: Algorithmic Trading - Winning Strategies and Their Rationale (notes)
type: reference_only
quality: 5
ingested_date: 2026-05-08
topic_tags: [quant_finance, mean_reversion, momentum, pairs_trading, kalman_filter, regime_switch, statistical_arbitrage]
---

# Chan — Algorithmic Trading (özet notlar)

> Bu doküman Ernest P. Chan'in "Algorithmic Trading: Winning Strategies and Their Rationale" (2013), "Quantitative Trading" (2009) ve "Machine Trading" (2017) kitaplarındaki metodolojinin sentezlenmiş özetidir; orijinal metin telif altındadır, burada yalnızca yöntemsel notlar tutulur.

## Yazarın Çerçevesi

Chan'in kitap dizisinin omurgasını tek bir ikili düstur taşır: piyasalarda istismar edilebilir iki temel istatistiksel davranış vardır — **mean reversion** (durağanlık etrafında salınım) ve **momentum** (trend süreklilik). Hangisinin "çalıştığı" piyasa **regime**'ine bağlıdır; bir strateji evrensel olarak iyi değildir, yalnızca koşullu olarak iyidir. Bu Chan'i tipik kitap yazarlarından ayıran çekirdek tezdir: edge, "doğru kural"da değil, "doğru kuralı doğru rejimde aktive etmek"tedir.

Chan, retail (perakende) tüccarın yapısal handikapını açıkça koyar: kurumsal masaların düşük gecikmeli istatistiksel arbitraj alanına (HFT mean-reversion, latency arb, market making) erişimi yoktur; dolayısıyla retail için realistic edge alanı **orta-frekans (saatlik–günlük) mean-reversion** ve **çapraz-kesit momentum**'dur. Çoğu retail stratejinin momentum-tabanlı olmasının nedeni psikolojiktir (trend görmek kolaydır), ancak çoğu kurumsal alfa istatistiksel arb / cointegration / market making'den gelir — bu asimetri retail tüccarın "kalabalık trade"den uzak duran mean-reversion fırsatları araması gerektiğini gösterir.

Chan'in çerçevesinde her strateji şu sorulara cevap vermek zorundadır: (1) Hangi istatistiksel özelliği istismar ediyor? (durağanlık? momentum? volatilite asimetrisi?) (2) Bu özellik **stationary** mi (zamanla sabit) yoksa **regime-dependent** mi? (3) Out-of-sample Sharpe ratio backtest Sharpe'inin en az %50–70'ini koruyor mu? (4) Transaction cost ve slippage backtest'e dahil edildikten sonra net Sharpe nedir? Bu dört soruya cevap veremeyen hiçbir strateji canlı paraya geçmez.

Chan ayrıca "automation premium" kavramını öne çıkarır: stratejinin tamamen otomatik (kuralı kodlanabilir, her parametre objektif) olması gerekir; çünkü insan müdahalesi backtest sonuçlarını invalide eder ve ölçeklenemez. Bu felsefe — "her şey kod, her şey reproducible" — Chan'i Kaufman'dan (yarı-mekanik) ve Brooks'tan (tamamen discretionary) ayıran ana yöntem farkıdır.

Chan'in "Quantitative Trading" (2009) kitabı bu çerçeveyi pratik infrastructure üzerinden anlatır: data quality (vendor seçimi, corporate action handling, point-in-time fundamental data), backtesting framework tasarımı (event-driven vs vectorized), execution platform (broker API, order routing, slippage modeling) ve performance attribution (per-strategy P&L decomposition, factor exposure analysis). "Machine Trading" (2017) ise modern ML eklemeleri ile genişler: random forest signal combination, deep learning for time-series prediction, reinforcement learning for execution; ancak Chan ML'ye karşı temkinli — overfitting tehlikesi yüksek, basit doğrusal stratejiler çoğu zaman karmaşık ML'den daha güvenilirdir. Chan ML'yi yeni alpha bulmak için değil, mevcut alphalara ek **filtreleme/sizing** katmanı olarak kullanmayı önerir.

## Mean Reversion Strategies

Chan'in en çok yer ayırdığı strateji ailesi mean-reversion'dır çünkü retail-erişilebilir Sharpe'ler burada en yüksektir (1.5–2.0 aralığı, Chan'e göre).

**Pairs Trading (Cointegration-based).** İki varlık (örn. XLE ve USO) zamanla birbirine bağlı bir lineer kombinasyon oluşturuyorsa (yani `y_t - β·x_t = ε_t` durağansa), bu **cointegration**'dır. β hedge ratio'dur. Spread `ε_t` durağan bir Ornstein-Uhlenbeck süreç gibi davranır; ortalamadan sapınca geri döner. Test prosedürü: önce her iki seri için ADF (Augmented Dickey-Fuller) ile non-stationary olduklarını gösterirsin, sonra OLS rezidüsüne ADF uygulayıp stationary olduğunu gösterirsin (Engle-Granger iki-aşamalı yöntem). Daha sağlam alternatif: Johansen testi — birden fazla cointegration vektörünü aynı anda test eder ve sıralama bağımsızdır.

**ETF Mean Reversion.** XLE (energy ETF) ile USO (oil ETF) — ikisi de petrol fiyatına maruzdur ama farklı yapıdadır. Spread durağan davranır çünkü altta yatan ekonomik bağlantı zorlar. Chan benzer örnekleri sektör ETF çiftleri (XLF–XLK), country ETF çiftleri (EWA–EWC, Avustralya–Kanada commodity-driven), uzun-kısa volatilite (VXX–SVXY) için verir.

**Statistical Arbitrage on Basket.** Tek bir çift yerine, bir varlık vs çoklu varlık sepet kombinasyonu. Örn. AAPL'i (XLK + SPY + QQQ) lineer kombinasyonu ile hedge etmek. Genellikle çok daha düşük volatiliteli rezidü; ancak transaction cost katlanır. Johansen burada zorunlu.

**Bollinger Band Z-score Reversal.** Mean-reversion'in en basit formu: bir varlığın 20-period rolling mean ve std'sini hesapla; fiyat mean'den `2σ` üzerine çıkınca short, `2σ` altına inince long. Tek varlık için "trade-able" olması için varlığın **kendisinin** durağan davranması gerekir (genelde yoktur), ya da spread olarak oluşturulan bir senteti̇k seri olmalı. Chan, Bollinger'ı saf hisseye uygulamanın momentum rejiminde sürekli zarar üreteceğini, dolayısıyla regime filtresi (örn. ADX < 20 veya half-life makul aralıkta) zorunlu olduğunu vurgular.

**Triplet Trades (3-Asset Cointegration).** Üç varlığın doğrusal kombinasyonu durağan olabilir; ikisi olmasa bile. Örn. EWA–EWC–oil futures üçlüsü. Johansen testi `r=2` cointegration vektörü bulabilir; en yüksek mean-reversion hızına (en kısa half-life) sahip vektör seçilir.

**Index Arbitrage (Cash-Futures Basis).** Vadeli endeks fiyatı ile spot endeks (veya replicating ETF basket) arasındaki "fair value" sapması. Theoretical fair = `spot · (1 + r·t/360) - dividend_pv`. Sapma threshold'u aşınca arbitraj. Retail için kapasite sınırlı (kurumsal HFT bu nişi sıkı kapatmıştır), ancak küçük cap futures kontratlarında (E-mini sonrası micro futures, sektör futures) hâlâ küçük edge mümkün.

**ETF-Underlying Component Arbitrage.** Bir ETF'in NAV'si ile market price'ı arasında premium/discount oluşur (özellikle yüksek vol günlerinde, küçük likit ETF'lerde). Premium > 30bp → short ETF, long components; tersi de. Likit ETF'lerde (SPY, QQQ) authorized participants bunu hızla kapatır; küçük sektör ETF'lerinde (XHB, XBI, country-specific) daha geniş edge.

**Mean-Reversion of Forex Pairs.** Cross-currency çiftleri (EUR/GBP, AUD/NZD) genelde major-USD çiftlerinden daha mean-reverting davranır çünkü ortak USD shock'u eler. AUD/NZD özellikle iyi çalışır: her iki ülke commodity-driven, benzer monetary policy. Half-life 10–25 gün tipik.

## Momentum Strategies

Chan'in momentum hakkındaki tutumu temkinlidir: çalışır, ancak Sharpe'lar mean-reversion'dan düşüktür (0.8–1.2) ve drawdown derindir.

**Time-Series Momentum (TSMOM).** Moskowitz–Ooi–Pedersen (2012) makalesinden: bir varlığın son 12 aylık getirisi pozitifse long, negatifse short, sonraki 1 ay tut. Vadeli işlem evreninde (commodity, FX, equity index, bond futures) yaklaşık 0.7–1.0 Sharpe verir, vol-targeted (her pozisyon eşit risk) implementasyonla. Chan bunu retail futures hesabı için en realistic strateji olarak gösterir.

**Cross-Sectional Momentum.** Jegadeesh–Titman (1993) klasiği: hisse evreninde her ayın başında son 12-1 ay (önceki son ay hariç, "skip month") getirisine göre sırala; üst desile long, alt desile short, eşit ağırlık. Equity-market-neutral; ancak crash riski (örn. 2009 momentum crash) ciddi. Chan momentum'u "trend persistence" + "underreaction to news" kombinasyonu olarak yorumlar.

**News-Driven Momentum.** Earnings announcement, FDA approval, merger, guidance gibi olaylardan sonra 30–60 dakika içinde girip kısa süre tutmak. Chan "Quantitative Trading" kitabında bunu Reuters/Bloomberg news feed parsing örnekleri ile anlatır; latency-sensitive ama saniye değil dakika ölçeğinde retail-feasible. Edge: information diffusion gecikmesi.

**Volatility-Momentum (VIX Regime).** Düşük VIX → momentum çalışır (sakin, trending piyasa). Yüksek VIX → mean-reversion çalışır (panik satış sonrası bounce, panik alım sonrası fade). Chan VIX > 30 rejiminde mean-reversion stratejilerini ağırlıklandırmayı, VIX < 15 rejiminde TSMOM'u ağırlıklandırmayı önerir.

**Earnings Drift (PEAD - Post-Earnings Announcement Drift).** Earnings sürpriz pozitif (actual > consensus) → 60 günlük yukarı drift; sürpriz negatif → aşağı drift. Bernard-Thomas (1989) klasik bulgusu, yüzlerce out-of-sample dönemde tekrarlandı. Standardized unexpected earnings (SUE) kullanılır: `(actual - consensus) / std(historical_surprises)`. Üst desile long, alt desile short, 60 gün hold. Earnings revizyonu (analist tahmin değişimi) benzer momentum yaratır.

**52-Week High Momentum.** George-Hwang (2004): hisse 52-hafta high'ına yakın işlem görürken üzerine breakout sonrası güçlü momentum. Cross-sectional momentum'dan farklı olarak path-dependent; "anchor" olarak son 52-hafta high kullanılır.

## Setup Kataloğu

### Setup 1 — Pairs Trading Entry (Cointegrated Pair, Z-score > 2σ)

- **Tanım:** İki cointegrated varlık (Engle-Granger veya Johansen ile doğrulanmış) için spread `s_t = y_t - β·x_t` z-score'u ±2 standart sapmayı aştığında ortalamaya geri dönüş yönünde pozisyon.
- **Bağlam:** Hem `y` hem `x` non-stationary (ADF p > 0.05), spread stationary (ADF p < 0.05). Half-life 5–30 gün aralığında. Uzun vadede ekonomik mantık (aynı sektör, aynı emtia, aynı ülke risk faktörü).
- **Giriş:** z-score > +2 → short `y`, long `β` adet `x`. z-score < -2 → long `y`, short `β` adet `x`. β rolling 60-day OLS veya Kalman filter ile dinamik tahmin edilir.
- **Stop:** z-score sapma genişlerse zarar büyür; Chan iki yaklaşım önerir: (a) z-score > 3.5 olursa stop (rejim değişti, cointegration bozuldu), (b) maksimum tutma süresi = 3 × half-life. Birincisi sert, ikincisi yumuşak çıkış.
- **Hedef:** z-score → 0 (mean'e dönüş). Kısmi çıkış z=1'de, tam çıkış z=0'da.
- **Edge:** Spread'in OU sürecine yakın davranması; reversion hızı `λ` ne kadar büyükse strateji o kadar tutarlıdır.
- **Failure:** Cointegration dynamic — tek bir yapısal kırılma (örn. M&A, regülasyon değişikliği) ilişkiyi kalıcı bozar; spread "drift" eder ve geri dönmez.

### Setup 2 — Bollinger Reversal (Single-Asset Mean Reversion)

- **Tanım:** Tek varlıkta 20-period MA ± 2σ band. Fiyat alt banda dokununca long, üst banda dokununca short.
- **Bağlam:** Yalnızca **range-bound / mean-reverting** rejimde — ADX < 20, ya da varlığın kendisi üzerine ADF testi p < 0.10 (yani mean-reverting). Trend rejiminde devre dışı.
- **Giriş:** Close < lower band → long sonraki bar açılışında. Close > upper band → short sonraki bar açılışında.
- **Stop:** ATR-based (1.5 × ATR(14) carşı yön) ya da banddan `1σ` daha öteye sapma.
- **Hedef:** Middle band (20-MA). Risk-reward yaklaşık 1:1, kazanma oranı yüksek (60–65%) olduğunda profitable.
- **Edge:** Overshoot — kısa süreli arz/talep dengesizliği, reversal probabilistic.
- **Failure:** Trend başlangıcında ardı ardına gelen long sinyallerde sürekli zarar (trend-following rejimde fatal). Filter olmadan kullanılmaz.

### Setup 3 — Time-Series Momentum Entry (12M Return Positive)

- **Tanım:** Aylık veri, varlığın son 12 ay getirisi pozitifse long, negatifse short, 1 ay tut, ay sonunda yeniden hesapla.
- **Bağlam:** Vadeli işlem piyasaları (commodity, FX, bond, index) — equity'de momentum crash riski yüksek olduğundan dikkat. Vol-targeted: her pozisyon `target_vol / asset_vol` ağırlıkla.
- **Giriş:** Ayın ilk işlem günü açılışı.
- **Stop:** Ay sonuna kadar passive tutma, mid-month stop yok. Risk yönetimi vol-targeting üzerinden.
- **Hedef:** Önceden belirlenmiş hedef yok; ay sonunda re-evaluate.
- **Edge:** Underreaction-then-overreaction davranışı; kurumsal yavaş yeniden dengeleme.
- **Failure:** Sharp reversal (2009 ekuity momentum crash, 2020 Mart vadeli crash) — momentum stratejilerinin tail risk'i geniştir.

### Setup 4 — Ranking-Based Cross-Sectional Momentum

- **Tanım:** Hisse evreninde her ayın sonunda son 12-1 ay getirisini sırala; üst %10 long, alt %10 short, eşit dolar ağırlığı.
- **Bağlam:** Likit large-cap evren (S&P 500 üyeleri tarihsel olarak), market-neutral (long ve short eşit dolar).
- **Giriş:** Ay sonu close → bir sonraki ayın ilk işlem gününde rebalance.
- **Stop:** Pozisyon-bazlı stop yok; aylık rebalance.
- **Hedef:** 1 aylık holding; yeniden rank.
- **Edge:** Cross-sectional momentum'un akademik dökümante edilmişliği güçlü; evrensel anomaly.
- **Failure:** Momentum crash — bear market dipinden sonra short'ların güçlü ralli yapması (en kötü-performanslar en hızlı toparlayanlar olur).

### Setup 5 — Kalman Filter Pairs Trading (Dynamic Hedge Ratio)

- **Tanım:** β hedge ratio'su statik OLS yerine Kalman filter ile her bar dinamik güncellenir; "değişen ilişki"yi yakalar.
- **Bağlam:** Cointegration test geçmiş ama ilişki yavaş drift ediyorsa (örn. iki şirket arasındaki büyüklük oranı zaman içinde kayıyor). Kalman state: `[β_t, intercept_t]`, observation: `y_t = β_t · x_t + α_t + ε_t`.
- **Giriş:** Innovation residual `e_t = y_t - β_{t|t-1} · x_t` z-score'u ±2'yi aştığında.
- **Stop:** z-score > 3.5 ya da innovation variance `Q_t` ani fırlama (ilişki bozuluyor sinyali).
- **Hedef:** Innovation z=0.
- **Edge:** Statik OLS β'sının "stale" olması durumlarında; dinamik β stratejinin half-life'ı düşürür ve Sharpe'ı artırır.
- **Failure:** Process noise `Q` ve observation noise `R` parametrelerinin yanlış kalibrasyonu; aşırı reaktif Kalman gürültüye uyar, durağan ilişkiyi kaybeder.

### Setup 6 — Regime-Switching Entry (HMM-based)

- **Tanım:** Hidden Markov Model 2-rejim (mean-reversion vs momentum) tahmin eder; high-confidence rejim olasılığı (>0.7) altında uygun stratejiyi etkinleştir.
- **Bağlam:** Tek strateji yerine iki stratejinin (Bollinger reversal + TSMOM) regime-conditional çalıştırılması.
- **Giriş:** P(mean-reversion regime | observations) > 0.7 → Bollinger sinyallerini al. P(momentum regime) > 0.7 → TSMOM sinyallerini al. Belirsiz rejimde flat.
- **Stop:** Rejim olasılığı ters yöne döndüğünde (örn. mean-rev rejimde iken P(momentum) > 0.6 olur) pozisyonu kapat.
- **Hedef:** Strateji-spesifik (alt strateji ne diyorsa).
- **Edge:** Regime-aware allocation, blind ensemble'dan daha iyi.
- **Failure:** Look-ahead bias — HMM'i tüm tarihçe ile fit edip backtest'te kullanmak invalid; expanding-window fit zorunlu. Ayrıca rejim sayısı (`n_states`) over-parametrizasyon riski.

### Setup 7 — Volatility Breakout (Vol Expansion Regime)

- **Tanım:** Realized volatility uzun bir compression (squeeze) sonrası genişlediğinde momentum yönünde giriş.
- **Bağlam:** ATR(20) son 60 günün en düşük %10 percentile'ında ise compression; ATR ani sıçrama (mevcut bar ATR > 1.5 × 60-day mean) ise expansion sinyali.
- **Giriş:** Compression sonrası ilk expansion barında, breakout yönünde (önceki 20-day high'ı aşan close → long).
- **Stop:** Pre-breakout range'in altında (long için son 20-day low - 0.25 × ATR).
- **Hedef:** Trailing stop: 3 × ATR ya da chandelier exit.
- **Edge:** Volatility clustering (GARCH) — düşük vol periyodu sonrası yüksek vol gelmesi olasılığı yüksek; yön ek olarak compression'dan kurtulma yönünde.
- **Failure:** Whipsaw — expansion bar gelip ertesi gün geri dönmesi (false breakout). Volatility filtresi yön tahmin etmez, sadece harekete hazır olduğunu söyler.

### Setup 8 — Calendar / Seasonal Anomaly Entry

- **Tanım:** Tarihsel istatistiksel olarak güçlü mevsimsel/takvim etkilerine dayalı zamanlanmış pozisyonlar (örn. "Sell in May", Halloween effect, turn-of-the-month, January effect).
- **Bağlam:** En az 30+ yıllık örneklem; istatistiksel anlamlılık (t-stat > 2.5), out-of-sample on geriye kalan periyot.
- **Giriş:** Takvim koşulu sağlandığı tarih (örn. ayın son işlem günü close → ayın ilk 4 işlem günü tutma).
- **Stop:** Pozisyon-bazlı stop genelde yok; takvim-bazlı zaman çıkışı.
- **Hedef:** Takvim sonu.
- **Edge:** Yapısal akışlar (maaş, fund inflow, rebalance), risk premium zamanlaması.
- **Failure:** Anomaly fade — bir kez yayınlandıktan sonra arbitraj edilebilir; yeni regülasyon (T+1 settlement gibi) yapısal etkileri silebilir. Ayrıca tarihsel olarak güçlü olan turn-of-the-month etkisi son 10 yılda zayıflamıştır.

## Kalman Filter Applications

Kalman filter Chan'in imzası tekniktir; mean-reversion stratejilerinde **dinamik hedge ratio** ve **dynamic linear regression coefficients** için kullanılır.

**Problem formülasyonu.** İki varlık arasındaki β oranı zaman içinde sabit değil; piyasa koşulları, şirket büyüklüğü oranı, rejim değiştikçe yavaş drift eder. Statik 60-day rolling OLS bunu yakalar ama **gecikmelidir** ve pencere uzunluğu seçimi keyfidir. Kalman filter Bayesian recursive estimator'dir ve her yeni gözlemde inanç güncelleme yapar.

**State-space model.**
- State vector: `x_t = [β_t, α_t]^T` (hedge ratio ve intercept).
- State transition: `x_t = x_{t-1} + w_t`, `w_t ~ N(0, Q)` (random walk asumsiyonu).
- Observation: `y_t = [x_t (=price_x_t), 1] · x_t + v_t`, `v_t ~ N(0, R)`.

**Mekanik adımlar (yüksek seviye).**
1. **Predict:** `x̂_{t|t-1} = x̂_{t-1|t-1}` (random walk → state aynı kalır), `P_{t|t-1} = P_{t-1|t-1} + Q`.
2. **Innovation:** `e_t = y_t - H_t · x̂_{t|t-1}`, `S_t = H_t · P_{t|t-1} · H_t^T + R`.
3. **Kalman gain:** `K_t = P_{t|t-1} · H_t^T / S_t`.
4. **Update:** `x̂_{t|t} = x̂_{t|t-1} + K_t · e_t`, `P_{t|t} = (I - K_t · H_t) · P_{t|t-1}`.
5. **Trade signal:** Innovation `e_t` standardize edilir (`e_t / sqrt(S_t)`); z-score > 2 → reversion trade.

**Q ve R kalibrasyonu.** Q (process noise) küçük → β yavaş güncellenir (smooth), büyük → reaktif. R (observation noise) gözlem fiyatlarındaki gürültü; genelde rezidü varyansından tahmin. Chan empirical olarak `Q = 1e-4 · I`, `R = 0.001` aralığını başlangıç kabul olarak verir; her çift için optimize edilir.

**Avantaj:** Statik OLS'ye göre yapısal kırılmaları daha hızlı yakalar; ancak P&L için hedge ratio'nun **küçük adımlarla** değişmesi gerek (büyük sıçrama "büyük inanç güncelleme" demek ve trade sinyallerini bozar).

**Diğer Kalman uygulamaları.** Chan ayrıca **dynamic moving average** (Kalman ile gürültüden temizlenmiş trend tahmini), **dynamic regression** (multi-factor model coefficient'larının zamanla evrimi), ve **smoothing filter** (off-line spread temizleme, backward smoother ile tüm tarihçeyi gözden geçirme) için Kalman uygulamalarını gösterir. Hepsinde ortak prensip: **state'i bir random walk + observation gürültü modeli olarak yaz, recursive Bayesian update uygula**. Reinforcement gibi parametrik adaptif filtrelerden farkı: Kalman optimal lineer estimator'dır (Gaussian asumsiyonu altında), parametrik tuning gerektirmez (Q ve R kalibrasyonu hariç).

## Cointegration & Stationarity Testing

**ADF (Augmented Dickey-Fuller).** Null hypothesis: seri unit root içerir (non-stationary). Test istatistiği MacKinnon kritik değerleriyle karşılaştırılır. P-değer < 0.05 ise null reddedilir → seri stationary (mean-reverting).
Pratik uygulama: `from statsmodels.tsa.stattools import adfuller; result = adfuller(spread, maxlag=1)`. ADF lag seçimi BIC veya AIC ile.

**Engle-Granger (iki-aşamalı).**
1. `y` ve `x` her biri için ADF: ikisi de non-stationary olmalı (I(1)).
2. OLS: `y_t = β · x_t + α + ε_t`, rezidü `ε_t` hesapla.
3. ADF on `ε_t`: p < 0.05 → cointegrated.

**Johansen Test.** Çok değişkenli; vector error correction model içinde rank testi. İki istatistik: trace ve max-eigenvalue. Kritik değerler `n` (değişken sayısı) ve trend asumsiyonuna bağlı. Trace istatistiği kritik değer üzerinde ise en az `r` cointegration vektörü vardır.

**Half-Life (Ornstein-Uhlenbeck).** Spread'in mean'e geri dönüş hızı. AR(1) regresyon: `Δs_t = λ · s_{t-1} + μ + ε_t` → `λ < 0` mean-reversion. Half-life formula:
```
half_life = -log(2) / log(1 + λ)
```
Yaklaşık eşdeğer: `half_life ≈ -ln(2) / λ` (log(1+λ) ≈ λ küçük λ için).
Yorum: half-life 5–30 gün arası "trade-able"; 1 günden az → noise; 60 günden fazla → trade için sabır gerektirir, capital cost yüksek.

**Neden önemli?** Mean-reversion stratejisinin Sharpe'ı **half-life'ın square root'una ters orantılıdır** (kabaca). Half-life 5 gün olan bir çift, half-life 30 gün olandan ~2.4× daha yüksek Sharpe verir, diğer her şey eşit.

## Regime Detection

**Hidden Markov Model (HMM) yaklaşımı.** Gözlem (örn. günlük getiri) görünür, gerçek rejim (mean-rev / momentum / yüksek vol / düşük vol) gizli. Model parametreleri:
- Başlangıç olasılıkları `π`.
- Rejimden rejime geçiş matrisi `A`.
- Her rejim için emisyon olasılığı (genelde Gaussian: `μ_k`, `σ_k`).

**Eğitim:** Baum-Welch algoritması (EM). **Tahmin:** Viterbi en olası rejim sekansını verir; forward-backward algoritması her zaman noktası için rejim olasılıklarını verir.

**Kullanım kuralı.** Real-time'da `P(regime_k | observations_1:t)` hesaplanır; yalnızca `P > 0.7` (yüksek güven) olduğunda strateji aktive olur. Belirsiz rejimde flat. Bu approach **expanding-window** fit ister; tüm tarihçeyi backtest başında fit etmek look-ahead bias'tır.

**Drawdown-based regime switch.** HMM'e alternatif basit kural: stratejinin son 30 gün PnL'i drawdown'a girerse rejim değişmiş kabul et, off. PnL recovery > 50% ise rejim geri döndü, on. "Equity curve trading" — Chan bunu güzel bir şekilde "stratejinin kendi performansı en iyi rejim göstergesidir" yorumuyla destekler.

**Volatility regime.** VIX > 30 → high-vol regime → mean-reversion ağırlık. VIX < 15 → low-vol → momentum ağırlık. Realized vol için 20-day std; persantil-bazlı eşik (üst %20 = high).

## Risk Yönetimi

Chan risk yönetiminde **Kelly Criterion** ve **optimal leverage** üzerinden gider; geleneksel "fixed fractional" yöntemlerinden teorik olarak üstün bulduğunu savunur, ama pratikte **half-Kelly** veya daha az kullanmayı önerir (volatility tahmin hatasına dayanıklılık için).

**Kelly leverage formula (continuous, Gaussian return):**
```
f* = μ / σ²
```
Burada `μ` beklenen getirinin (annualized), `σ²` getirilerin variance'ı (annualized). Sharpe ratio cinsinden:
```
f* = SR / σ
```
ve **maksimum büyüme oranı** `g* = μ²/(2σ²) = SR²/2`.

Örnek: yıllık μ=15%, σ=20% → `f* = 0.15 / 0.04 = 3.75x` leverage. Pratik uygulama: half-Kelly = 1.875x; çoğu retail için bu hâlâ agresif; quarter-Kelly daha güvenli.

**Çoklu strateji:** her bir stratejiye kendi Kelly fraction'ı; toplam kullanılan kapital portföy seviyesinde Kelly toplamını aşmamalı. Strateji korelasyonu varsa (genelde vardır), Kelly daha düşük olmalı.

**Drawdown limits.** Chan max drawdown limitini Kelly fraction üzerinden türetir: half-Kelly ile beklenen max drawdown ≈ %25–35 (yıllık), quarter-Kelly ile ≈ %15–20. Sistematik trader için "drawdown trigger" kuralı: %20'yi aşarsan tüm stratejileri durdur, model review yap, yeniden başla — psikolojik dayanıklılık ve sermaye koruma için.

**"Sharpe ratio is the only metric that matters."** Chan bu provokatif iddiayı sistematik trading için savunur çünkü:
1. Sharpe leverage-invariant'tır (gerçek edge'i ölçer).
2. Kelly leverage Sharpe'a doğrudan bağlıdır (`g* = SR²/2`).
3. Kıyaslanabilirlik (cross-strategy, cross-asset) sadece Sharpe ile mümkündür.
Eleştiri: tail risk (skewness, kurtosis) Sharpe'a dahil değil; Sortino, Calmar, MAR ratio tamamlayıcı kullanılmalı. Chan da bunu kabul eder ama "optimal leverage hesabı için Sharpe yeterlidir" der.

## Statistical / Quantifiable Edge Conditions

Chan kitaplarında strategy class'ı başına empirik Sharpe aralıkları paylaşır (post transaction cost, retail-realistic):

- **Pairs trading (cointegrated equity ETF):** Sharpe 1.5–2.0 (en iyi çiftler), 0.8–1.5 (ortalama). Half-life 5–20 gün ideal.
- **Statistical arb (basket, 50+ asset):** Sharpe 2.0–3.0 mümkün ama transaction cost çok ciddi; retail için marjinal.
- **Time-series momentum (futures):** Sharpe 0.7–1.0 (tek varlık), 1.2–1.5 (diversified portfolio across asset classes).
- **Cross-sectional momentum (equity):** Sharpe 0.6–1.0; momentum crash dönemlerinde derin drawdown.
- **Bollinger reversal (filtreli, regime-aware):** Sharpe 1.0–1.5 — eğer regime filter çalışıyorsa.
- **News-driven momentum:** Sharpe 1.5–2.5 mümkün ancak data + execution maliyeti yüksek.
- **Volatility breakout:** Sharpe 0.5–1.0 — yön tahmini olmadığı için zayıf.

**Half-life beklentileri:**
- Trade-edilebilir cointegrated çift: 5–30 gün.
- 30–60 gün: marjinal, capital-tied long.
- > 60 gün: sermaye verimliliği düşük; ya regime-switching ya da daha hızlı çift bul.
- < 1 gün: noise; muhtemelen sahte cointegration.

**Decay.** Chan'in vurguladığı kritik nokta: yayınlanmış akademik anomalies (size, value, momentum) zamanla zayıflar. Out-of-sample Sharpe genelde in-sample'ın %50–70'i; %70'in üzerinde out-of-sample karlılık gerçek edge'in işaretidir, %30'un altı ise overfitting göstergesidir.

## Crypto Adaptasyonu

Chan kitaplarında doğrudan crypto bölümü yoktur (eski sürümler), ancak metodolojisi crypto'ya doğrudan uygulanır.

**BTC-ETH Cointegration.** İki büyük cap kripto arasındaki ilişki 2017–2020 döneminde güçlü cointegration sergiledi (Engle-Granger p < 0.01); 2021 sonrası ETH'nin DeFi/NFT ile diverjansı sebebiyle ilişki zayıfladı, 2024 sonrası tekrar güçlendi. Half-life 7–25 gün aralığı tipik. Sharpe 1.0–1.8 backtest (transaction cost dahil, %0.1 taker fee varsayımı).

**Funding Rate Arbitrage.** Perpetual futures funding rate yüksek pozitif (örn. > %0.05 / 8 saat) → long spot, short perp; funding negatif → ters. Delta-neutral, funding pickup. Sharpe 1.5–3.0 mümkün ama kapasite sınırlı (her exchange'in OI limiti).

**Perp-Spot Basis.** Perp fiyatı spot'tan sapması mean-reverts; sapma > 1% (annualized > 365%) → short perp / long spot. Bu bir tür triangular cointegration.

**Adaptasyon notu.** Crypto'da:
- Cointegration testleri 24/7 piyasa için bar-time uniform (saatlik veya 4 saatlik).
- Survivorship: delist edilen tokenler veri setinden çıkartılmalı; aksi halde performans abartılır.
- Black swan: 2022 Luna/UST, 2022 FTX gibi ani çöküşler → regime detection zorunlu, tek başına cointegration güveni yetmez.
- Funding rate ve implied vol'u regime feature olarak ekle.

## Yaygın Hatalar / Pitfalls

1. **False cointegration (data-snooping).** Yeterince çift testlerseniz biri istatistiksel olarak cointegrated görünür (multiple testing problem). Bonferroni correction veya FDR adjustment yap; ya da economic prior ile çiftleri kısıtla.
2. **Survivorship bias in pair selection.** Sadece bugün yaşayan hisselerle cointegration test etmek M&A, delisting nedeniyle kaybolan hisseleri eler ve performansı abartır.
3. **Backtesting without proper bid-ask.** Mean-reversion stratejilerinde işlem maliyetleri kritik; mid-price üzerinde backtest kazançlı görünüp gerçekte zarar üretebilir. En azından half-spread ekle, her trade için round-trip maliyet `2 × half_spread + commission`.
4. **Transaction cost neglect.** Pairs trading sık trade eder (haftada 1-2 round-trip tipik); günlük ATR'in %0.1-0.3'ü maliyet yıllık Sharpe'tan 0.5+ alabilir.
5. **Look-ahead bias in regime classifier.** HMM'i tüm tarihle fit edip sonra past'taki kararları "rejim p>0.7'di" diye almak invalid. Expanding-window veya rolling-window in-sample fit + walk-forward.
6. **Static hedge ratio when relationship drifts.** OLS β stationarity assumption gerektirir; relationship drift olduğunda Kalman filter veya rolling window kullan.
7. **Overfitting to regime parameters.** HMM'de state sayısı (`n_states`) modeli overfit edebilir; AIC/BIC ile seç ve out-of-sample doğrula.
8. **Kelly over-leverage.** μ ve σ tahmininde 30–50% hata var (sample size sınırlı); full Kelly ruin riskini gerçekleştirir. Half-Kelly veya quarter-Kelly safer.
9. **Ignoring half-life evolution.** Half-life zaman içinde değişir; rolling estimate ile track et, half-life > 60 gün'e çıkarsa stratejiyi pause et.
10. **Crowding.** Aynı stratejiyi (örn. yayınlanmış academic momentum) çok sayıda fund kullanırsa edge sıfırlanır. Vintage paper'a değil, kendi araştırmana güven.

## Cross-references

- **Chan ↔ López de Prado.** Lopez Chan'den daha sıkı istatistiksel duruşa sahiptir: Lopez deflated Sharpe, combinatorial purged CV, multiple-testing corrections konularında Chan'den daha agresiftir. Chan pratik araç kutusu sağlar, Lopez yöntemsel rigor'u zorlar — ikisi tamamlayıcıdır. Lopez "backtest overfitting" kavramını öne çıkarırken Chan "out-of-sample Sharpe" yeterli görür, bu Lopez'i daha tutucu yapar.
- **Chan ↔ Kaufman.** Kaufman ("Trading Systems and Methods") trading sistemleri ansiklopedisi gibidir, çok geniş ama matematiksel derinlik orta; Chan dar bir konu yelpazesi (mean-rev / momentum / pairs) ama matematiksel derinlik yüksek (Kalman, Johansen, HMM). Kaufman pratik mühendis, Chan akademik quant. Birlikte: Kaufman'dan stratejik repertuar, Chan'dan istatistiksel doğrulama.
- **Chan ↔ Brooks.** Brooks ("Reading Price Charts Bar by Bar", "Trading Price Action Trends") tamamen discretionary, bar-by-bar yorumlamaya dayalı; Chan tamamen sistematik, kuralları kodlanmış. Brooks edge'i pattern-recognition + intuition'da arar, Chan istatistiksel anomaly + cointegration'da arar. İkisi farklı epistemolojidir; Chan reproducibility'yi zorunlu görür, Brooks insanın deneyimini vazgeçilmez sayar.

## Bizim Sistemle Bağlantı

- **Regime classifier'a doğrudan kaynak.** Chan'in HMM-based regime detection metodolojisi bizim `regime_classifier` modülünün baseline'ı olabilir. 2-state Gaussian HMM (mean-reverting vs momentum) realized return ve realized vol üzerinde eğitilebilir; expanding-window walk-forward fit. Output: her bar için `P(regime_k)`, `confidence`. `regime_classifier`'da volatility regime + trend regime ayrı ayrı çıkarılıp birleştirilebilir.
- **Strategy library'e Bollinger reversal.** `strategies/` altına `bollinger_reversal` stratejisi olarak Setup 2 eklenebilir; ancak yalnızca regime classifier "mean-reverting" diyorsa aktive olur (`regime_filter=True`). Stop ATR-based, hedef middle band.
- **Pairs trading modülü.** Yeni bir `strategies/pairs/` paketi: cointegration scanner (Engle-Granger + Johansen), Kalman-based dynamic hedge ratio, z-score entry/exit. Universe: BTC-ETH, BTC-SOL, ETH-SOL gibi major-major çiftleri başlangıç.
- **Funding rate arb / perp-spot basis.** Crypto-spesifik extension; `strategies/funding_arb` modülü. Delta-neutral, low-correlation diversifier rolü.
- **Risk module'da Kelly sizing.** Half-Kelly default; her stratejinin walk-forward Sharpe'ından Kelly fraction hesaplanır; portföy seviyesinde toplam leverage cap (örn. 2.0x) zorlanır.
- **Backtest engine'de transaction cost.** Mean-reversion stratejileri için round-trip cost (taker fee + half-spread) zorunlu; mid-price backtest yasaklanmalı. Engine'de `cost_model` parametresi her stratejiye geçilmeli.
- **Half-life monitoring.** Pairs için canlı half-life rolling estimator; half-life > 60 gün eşiğine çıkarsa stratejiyi auto-pause; alert.
- **Sharpe-based strategy gating.** Yeni stratejiler portföye girmeden önce out-of-sample Sharpe > 0.8 (single asset) veya > 1.2 (pair / portfolio) eşiğini geçmeli; bu Chan'in retail-realistic edge tablosuyla uyumlu.
- **Regime-conditional ensemble.** HMM rejim çıktısına göre Bollinger reversal vs TSMOM ağırlıklarının dinamik allocation'ı; portföy seviyesinde "regime-aware meta-strategy" oluşturulur.
