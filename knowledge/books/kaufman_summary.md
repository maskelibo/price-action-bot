---
source_id: kaufman_summary
source_type: book
author: Perry J. Kaufman
title: Trading Systems and Methods (notes)
type: reference_only
quality: 5
ingested_date: 2026-05-08
topic_tags: [quant_finance, trend_following, momentum, mean_reversion, system_design, walk_forward]
---

# Kaufman — Trading Systems and Methods (özet notlar)

> Telif uyarısı: Bu doküman Perry J. Kaufman'ın "Trading Systems and Methods" (Wiley, 5. ve 6. baskılar) eserinden derlenen özetlenmiş metodoloji notlarıdır; orijinal metnin yerini almaz, eğitim ve dahili RAG referansı amaçlıdır.

## Yazarın Çerçevesi

Perry J. Kaufman'ın çalışması, 1970'lerden bu yana kantitatif trading literatürünün en kapsamlı tek-cilt referansıdır. Kitabın temel felsefesi şu cümleyle özetlenebilir: **"Her sistem bir piyasada çalışır — iş, sistemi piyasaya eşleştirmektir."** Kaufman, evrensel olarak kazandıran bir sistemin var olmadığını, ancak belirli rejimlerde belirli yapıların istatistiksel olarak edge taşıdığını savunur. Bu yaklaşım, modern regime-aware sistem tasarımının atasıdır ve López de Prado'nun meta-labeling, Chan'in regime-switching modelleri için zemin oluşturur.

Kaufman'ın systematic trading felsefesi dört sütun üzerinde durur:

1. **Rule-based**: Her giriş, çıkış ve pozisyon büyüklüğü kararı algoritmik olarak ifade edilebilmelidir. İnsan yargısı sistem dışında — sadece sistem seçimi, parametre robustness testi ve risk override'ı için kullanılmalıdır.
2. **Testable**: Tarihsel veri üzerinde reproducible backtest mümkün olmalı; rastgele seed, slippage ve commission modeli açıkça tanımlanmalıdır. Test edilemeyen kuralın yeri yoktur.
3. **Robust over optimal**: Bir parametre uzayında en yüksek Sharpe'ı veren konfigürasyon, çoğunlukla en iyi out-of-sample performansı vermez. Kaufman tekrar tekrar **"plateau over peak"** ilkesini vurgular: parametre uzayında geniş, düşük-eğimli plato üzerinde duran konfigürasyon, dik tepede oturan konfigürasyondan tercih edilir; çünkü piyasa karakteri kaymaya başladığında peak konfigürasyon hızla çöker.
4. **Survivor bias awareness**: 1970'lerden 2020'lere uzanan onlarca yıllık market gözlemi, Kaufman'a şunu öğretmiştir: bugün başarılı görünen sistemlerin çoğu, kötü dönemlerini gizleyerek hayatta kalmıştır. Performansı raporlanmamış 100 sistem, raporlanmış 10 sistemin ardında saklıdır. Bu yüzden her sistem değerlendirmesinde maksimum drawdown, drawdown süresi ve recovery factor — Sharpe'tan daha açıklayıcıdır.

Kitabın methodology katmanı, sistem geliştirmenin endüstriyel sürecini ortaya koyar: hipotez (market intuition) → kural ifadesi (rule formalization) → backtest → walk-forward → portfolio integration → live paper → live small size → live full size. Her aşama, bir sonraki aşamaya geçmek için niceliksel kapı (Sharpe > X, MAR > Y, drawdown < Z) gerektirir.

Kaufman'ın araştırmacı kimliği, 1971'de Commodities Magazine için yazdığı erken makalelerden 2020 sonrası baskılarına kadar evrim göstermiştir. Erken dönem çalışmaları çoğunlukla **futures markets** üzerine — buğday, soya, petrol, altın. Geç dönem baskılar ise **equities, FX, ve volatility products** dahil eder; crypto bahsi kitapta minimal olsa da framework crypto'ya doğrudan transfer edilebilir. Yazarın 50+ yıllık deneyiminin bize verdiği en değerli ders: **piyasa karakteri tarihsel olarak salınır, ama sistem tasarım principles sabittir**. 1980'lerde işe yarayan trend-following mekanikleri 2010'larda da işe yarar — ancak parametrelerin ve transaction-cost varsayımlarının yeniden kalibre edilmesi şartıyla.

Kaufman'ın bir başka kritik vurgusu: **"Bir sistem, yaratıcısının psikolojik toleransı dahilinde çalıştırılabilmelidir."** Teorik olarak %50 drawdown'a dayanan bir sistem, %30'da panik satışla kapatılırsa expected return realize edilmez. Bu yüzden sistem seçimi sadece istatistiksel değil, **psikolojik fit** sorusudur. Trend-following'in derin DD'lerine dayanamayan trader, mean-reversion'ın yüksek frequency mikro-DD'lerine daha uygundur. Bu felsefe, ekibimizin sistem-portfolyo seçiminde göz önünde tutulmalı.

## System Taxonomy

Kaufman, trading sistemlerini yapısal kategorilere ayırır. Bu taksonomi, kütüphanemizdeki strateji organizasyonu için doğrudan referans olarak kullanılabilir.

### Trend-following

Trendin devamını oynayan sistemler. En eski ve en çok belgelenmiş kategori. Tipik özellikleri: düşük win rate (%30-40), yüksek R-multiple (kazançlar büyük, kayıplar küçük), uzun pozisyon tutma süresi, fat-tailed pozitif return distribution.

- **Dual Moving Average (DMA) crossover**: hızlı MA yavaş MA'yı yukarı keserse long, aşağı keserse short. Klasik parametre: (5, 20), (20, 50), (50, 200).
- **Channel breakout**: N-bar high/low kırılımı. Donchian'ın orijinal 20/55 setpoint'i — Turtle Traders sisteminin temeli.
- **Breakout systems**: yatay konsolidasyondan momentumlu çıkış. Volume confirmation tipik filtre.
- **MACD trend**: histogram zero-line cross veya signal-line cross.

### Momentum

Fiyat değişim hızını ölçer. Trend-following'den farkı: pozisyon yönü oscillator ekstremlerine göre belirlenir, trendin "var olup olmadığı" sorusu sorulmaz.

- **Rate-of-change (ROC)**: `ROC_n = (Close - Close_n) / Close_n × 100`. ROC eşik üzerine çıkarsa long.
- **RSI (Wilder)**: 14-period default; 70 üzeri overbought, 30 altı oversold. Momentum mode'da: RSI > 50 long bias.
- **Stochastic**: %K ve %D çiftleri. Crossover ve divergence iki ana sinyal.

### Mean reversion

Fiyatın istatistiksel ortalamaya geri dönüşünü oynar. Yüksek win rate (%55-70), düşük R-multiple, range-bound rejimlerde mükemmel — trending rejimlerde catastrophic.

- **Bollinger band reversal**: 2σ band touch'ta karşı yönde giriş, orta band'a (20-MA) çıkışta exit.
- **RSI extremes**: RSI < 30 long, RSI > 70 short. Tek başına zayıf — trend filter ile birleştirilmelidir.
- **Z-score reversion**: spread veya residual üzerinde z > 2 short, z < -2 long.

### Pattern recognition

Chart pattern'leri ve candlestick formasyonlarını niceliksel kurala dönüştürür.

- **Chart patterns**: head-and-shoulders, double top/bottom, flag, pennant, triangle. Kaufman bu formasyonların **istatistiksel performansını ölçer** — pattern başarı oranını verir.
- **Candlestick statistics**: engulfing, hammer, doji vb. formasyonların 1/5/20 bar sonraki conditional return dağılımı.

### Volatility-based

Volatilitenin kendisini bir yapısal sinyal olarak kullanır.

- **Volatility breakout**: dünkü ATR'nin %X'i kadar fiyat hareketinden sonra trade tetiklenir (Larry Williams'ın volatility breakout'u).
- **Donchian channel**: pure price range breakout.
- **Keltner channel**: EMA ± k×ATR. Dinamik volatilite-bantlı kanal.

### Spread / pairs trading

Birbirine cointegrated iki enstrümanın spread'ini oynar. Crypto bağlamında: BTC/ETH spread, SOL/AVAX spread, perp/spot basis. Kaufman'ın spread chapter'ı, cointegration testlerine girmese de **rolling correlation** ve **ratio normalization** üzerinden saf bir mean-reversion çerçevesi sunar.

### Seasonal / cyclical

Calendar effect'leri sömürür: ay-içi etkileri, hafta-içi etkileri, sektörel mevsimsellik. Crypto'da daha az belirgin — ancak weekend volatility ve quarterly options expiry etkileri ölçülebilir.

### Arbitrage ve Statistical Arbitrage

Kaufman, klasik intermarket arbitraj (cash-futures basis, calendar spread) ve modern stat-arb (z-score normalized cointegrated pairs) üzerine ayrı bir bölüm ayırır. Crypto'da bu kategori: perp-spot basis trading, cross-exchange arbitraj, funding rate arbitraj. Düşük korelasyon profili portfolio için altın değerinde, ancak gerçek edge ölçülemez biçimde execution-bağımlı.

### Cycle-based Sistemler

Kaufman, John Ehlers'ın MESA (Maximum Entropy Spectral Analysis) çalışmalarına atıfta bulunarak cycle-based sistemlere bir bölüm ayırır. Hilbert transform, sine wave indicator gibi araçlarla dominant cycle period tahmini yapılır; trade decision bu period faz konumuna göre verilir. Pratikte düşük SNR — Kaufman'ın deyişiyle "cycles exist but are unstable"; bu yüzden cycle-based stratejiler genelde ek filter olarak kullanılır, standalone değil.

## Setup Kataloğu

Aşağıdaki setup'lar, **7-block formatta** (Tanım / Bağlam / Giriş / Stop / Hedef / Edge / Failure mode) verilmiştir.

### 1. Donchian Channel Breakout (Turtle-style)

- **Tanım**: 20-bar veya 55-bar high/low kırılımı.
- **Bağlam**: Trending market, ADX > 25 ideal. Yan piyasada whipsaw bombardımanı.
- **Giriş**: Fiyat 20-bar high üzerine kırarsa long; 20-bar low altına kırarsa short. Turtle System 1 default.
- **Stop**: Giriş - 2×ATR(20). Bazı varyantlarda 10-bar opposite channel.
- **Hedef**: Fixed target yok; **trailing exit** — fiyat 10-bar opposite channel'a değerse kapat.
- **Edge**: Asimetrik R-multiple; %35 win rate ile pozitif beklenti, çünkü winners 3-5R, losers 1R.
- **Failure**: Choppy/range-bound rejimde back-to-back whipsaw; kümülatif %20-40 drawdown sıkça görülür.

### 2. Moving Average Crossover (Golden/Death Cross varyantları)

- **Tanım**: İki MA'nın crossover'ı. Golden cross: 50-MA, 200-MA üzerinde. Death cross: tersi.
- **Bağlam**: Long-horizon trend captures. Daily/weekly timeframe ideal; intraday'de gürültü baskın.
- **Giriş**: Hızlı MA yavaş MA'yı kestiği bar'ın kapanışında.
- **Stop**: Yavaş MA altı (long için) — dinamik trailing stop.
- **Hedef**: Crossover reverses → exit. Veya fixed 4×ATR target.
- **Edge**: Düşük frekans, düşük commission yükü. Major trend'leri yakalar.
- **Failure**: Sideways market'te 4-6 ardışık whipsaw. Late entry/late exit yapısal sorun.

### 3. ATR-based Volatility Breakout

- **Tanım**: Önceki bar kapanışından dünkü ATR'nin k katı kadar uzaklaşma → giriş.
- **Bağlam**: Yüksek volatilite ortamı, gap dolu piyasalar. News-driven days.
- **Giriş**: Open + k×ATR(14) üzerine fiyat çıkarsa long stop emri; Open - k×ATR(14) altına inerse short stop. k tipik 0.5-1.0.
- **Stop**: Giriş - 1.5×ATR(14).
- **Hedef**: Bar/gün sonu kapanış; ya da 2×ATR target.
- **Edge**: Intraday momentum capture; yüksek win rate (~%55) küçük R ile.
- **Failure**: Düşük volatilite günlerinde tetiklenmez (zaten istenen); ama trend-day'de erken kâr alır, asimetri kaybolur.

### 4. Bollinger Band Mean Reversion

- **Tanım**: Fiyat 2σ üst banda değerse short, alt banda değerse long. Orta banda exit.
- **Bağlam**: Range-bound rejim, düşük ADX. **Trending rejimde toksik.**
- **Giriş**: Close > Upper Band → next-bar short market; Close < Lower Band → next-bar long.
- **Stop**: Bandın 0.5σ ötesi; ya da 1.5×ATR.
- **Hedef**: 20-MA (orta band) tagi.
- **Edge**: %60-70 win rate, hızlı turnover.
- **Failure**: Trend başlangıcında, fiyat band'ı "walk" ediyorken sürekli karşı yönde girip stop yer; böyle bir periyot R-multiple equity'i hızlı aşındırır.

### 5. RSI Divergence Entry

- **Tanım**: Price ve RSI arasındaki bullish/bearish divergence.
- **Bağlam**: Trend-exhaustion noktaları. Higher-timeframe support/resistance ile birleştir.
- **Giriş**: Bullish divergence (price lower-low, RSI higher-low) → confirmation candle (engulfing, hammer) sonrası long.
- **Stop**: Divergence low'unun altı.
- **Hedef**: Önceki swing high; veya 2-3R fixed.
- **Edge**: Confluence-based; düşük frekans ama yüksek edge per trade.
- **Failure**: Strong trend'de divergence saatlerce/günlerce devam eder ("RSI can stay overbought longer than you can stay solvent"). Filtrelenmemiş tek başına RSI divergence trade'i çoğu zaman zarar üretir.

### 6. Adaptive Moving Average — Kaufman's KAMA (yazarın imzası)

- **Tanım**: Smoothing constant'ı **Efficiency Ratio**'ya göre dinamik adapte olan MA. Trend güçlüyse hızlı, gürültü yüksekse yavaş.
- **Bağlam**: Her piyasa rejimi. Statik MA'ların temel zayıflığını giderir.
- **Giriş**: Fiyat KAMA üzerine kırarsa long; altına kırarsa short. Veya KAMA slope sign change.
- **Stop**: KAMA - 1×ATR (long için).
- **Hedef**: Trend-following exit — KAMA tersi yön sinyali.
- **Edge**: Trend'de hızlı, range'de inert. Whipsaw'ı **istatistiksel olarak** azaltır.
- **Failure**: Çok hızlı rejim değişimi (volatility regime shock) — adaptasyon gecikmesi 5-10 bar.

**Mekanik formül** (aşağıda detaylı):
```
ER_t = |Close_t - Close_{t-N}| / Σ|Close_i - Close_{i-1}| (i=t-N+1..t)
SC_t = [ER_t × (FastSC - SlowSC) + SlowSC]^2
KAMA_t = KAMA_{t-1} + SC_t × (Close_t - KAMA_{t-1})
```
Klasik parametreler: N=10, FastSC = 2/(2+1) = 0.6667, SlowSC = 2/(30+1) = 0.0645.

### 7. Efficiency Ratio Filter (yazarın metric'i)

- **Tanım**: ER, son N bar'daki net price change'in absolute price change toplamına oranı. 0-1 arası: 1 = pure trend, 0 = pure noise.
- **Bağlam**: Bir başka strateji üzerinde **regime gate** olarak kullanılır.
- **Giriş**: ER > 0.30 ise trend-following sistemi aktif; ER < 0.30 ise mean-reversion sistemi aktif.
- **Stop / Hedef**: Üstündeki sistemin kuralları.
- **Edge**: Sistemler arası **automatic switching** — Kaufman'ın en güçlü contribution'larından biri.
- **Failure**: ER threshold'ün kendisinin overfitted olması; rolling rank/percentile kullanmak daha robust.

### 8. Range Expansion (NR4 / NR7 Breakout)

- **Tanım**: NR4 = son 4 bar içindeki en küçük range; NR7 = son 7 bar. Volatility contraction → expansion expected.
- **Bağlam**: Düşük volatilite konsolidasyonu sonrası direksiyon kararsız ama hareket beklentisi yüksek.
- **Giriş**: NR7 bar'ı sonrası, bar high üstüne 1 tick kırılım → long stop emri; bar low altına short stop.
- **Stop**: NR7 bar'ının opposite extreme'i.
- **Hedef**: Expansion bar range'ının 2-3 katı; veya end-of-day exit.
- **Edge**: Yüksek win rate'li volatilite-arbitrage.
- **Failure**: Pre-news günlerde NR pattern'leri yanıltıcı — news direction'ı bilinmediği için her iki yön de stop tetikleyebilir (bracket whipsaw).

### 9. Volatility Contraction — Bollinger Squeeze

- **Tanım**: Bollinger band genişliği N-bar minimum; aynı zamanda Keltner band içinde — sıkışma.
- **Bağlam**: Trend launch kandidasyonu.
- **Giriş**: Squeeze release: BB Keltner dışına çıktığında. Yön için momentum oscillator (Linear Regression slope, MACD).
- **Stop**: Squeeze bar'ının opposite extreme'i.
- **Hedef**: BB width'in N-bar maksimumuna kadar trail.
- **Edge**: Asimetrik payoff; küçük başlangıç riski, büyük expansion potansiyeli.
- **Failure**: Squeeze fake-out — release sonra reversibility yüksektir; yön onayı zayıfsa kayıp.

### 10. Seasonality-based System

- **Tanım**: İstatistiksel olarak anlamlı calendar effect'lere dayalı sistematik long/short.
- **Bağlam**: Equity index'lerinde "Sell in May", commodity'de growing season effects, crypto'da quarterly options expiry. Crypto için weekend illiquidity etkisi de incelenebilir.
- **Giriş**: Calendar tarih (örn. ay-sonu son 5 gün long S&P, T+5 close exit).
- **Stop**: Fixed % stop veya volatility-scaled.
- **Hedef**: Calendar-defined exit.
- **Edge**: Düşük frekans ama düşük korelasyon — portfolio hedge'i.
- **Failure**: Effect'in zamanla erozyonu (alpha decay). Sürekli statistical re-validation gerekli; %95 confidence eşik.

## Adaptive Methods

Kaufman'ın metodolojiye en büyük katkısı **adaptive parameters** kavramıdır. Statik parametreli sistemler, piyasa karakteri değiştiğinde (volatilite rejimi, trend gücü) suboptimal hale gelir. Kaufman'ın çözümü: parametrenin kendisini bir piyasa metric'ine bağlamak.

### Efficiency Ratio (ER)

Kaufman'ın signature metric'i. Trend gücünün niceliksel ölçümü.

```
Net Change = |Close_t - Close_{t-N}|
Sum of Absolute Changes = Σ |Close_i - Close_{i-1}|  (i = t-N+1 ... t)
ER = Net Change / Sum of Absolute Changes
```

- ER → 1: Tüm bar değişimleri aynı yönde, pure trend.
- ER → 0: Bar değişimleri rastgele/karşı yönlü, pure noise.
- Pratik N: 10 (kısa vadeli), 20 (orta vadeli).

ER, rejim sınıflandırma için bizim `regime_classifier` modülümüzde ana feature olarak kullanılabilir. ADX'in alternatifi/tamamlayıcısı olarak değerlendirilmelidir; ER, Wilder ADX'ten daha az smoothed, daha duyarlıdır.

### Adaptive Moving Average — KAMA

ER'yi smoothing constant'a map eder.

```
FastSC = 2 / (FastPeriod + 1)        # default FastPeriod=2 → 0.6667
SlowSC = 2 / (SlowPeriod + 1)        # default SlowPeriod=30 → 0.0645
SC_t = [ER_t × (FastSC - SlowSC) + SlowSC]^2
KAMA_t = KAMA_{t-1} + SC_t × (Close_t - KAMA_{t-1})
```

- Trend güçlü (ER yüksek): SC ≈ 0.44 → hızlı reaksiyon.
- Range rejimi (ER düşük): SC ≈ 0.0042 → neredeyse statik, gürültüyü filtreler.
- Squared term: SC etkisini exponential olarak vurgular — slow rejimde gerçekten yavaşlar.

### Variable-Length Volatility Stops

Aynı mantık stop'a uygulanır: ATR multiplier'ı sabit 2 yerine, ER'ye göre 1.5-3.0 arası adapte edilir. Volatilite yüksek + trend güçlü → daha geniş stop. Volatilite yüksek + range → trade alma (filter).

### Variable-Length Lookback

Bazı sistemler, lookback window'unu volatility'ye bağlar. Yüksek volatilitede daha kısa lookback (hızlı tepki), düşük volatilitede daha uzun lookback (gürültü filtresi). Kaufman bunu rolling standard deviation'ın percentile'ı ile parametrize eder.

### Adaptive Trade Frequency

Bir başka ileri konsept: işlem sıklığını piyasa rejimine göre ayarlamak. Kaufman, range-bound piyasalarda küçük-target high-frequency setup'ları, trending piyasalarda büyük-target low-frequency setup'ları tercih eder. Aynı çekirdek strateji iki "mod" arasında geçiş yapar; mod kararını ER veya ATR percentile gibi rejim metric'i verir. Mod-bazlı parametre setlerinin (range vs trend) ayrı ayrı walk-forward optimize edilmesi gerekir; tek bir blended parametre seti her iki rejimde de suboptimal kalır.

### Adaptive Risk per Trade

Kaufman, fixed fractional sizing'in **rolling Sharpe veya rolling win rate** ile modüle edilebileceğini önerir. Sistem son 30 trade'de %60 win rate'in üzerindeyse normal sizing; %40'ın altındaysa size %50 düşürülür. Bu basit "regime-aware" sizing kuralı, alpha decay periyodlarında sermaye korur. Tabii ki **sample size yeterliliği** kritik — 30 trade'lik pencere noisy kalabilir.

## Walk-Forward / Optimization Discipline

Kaufman, kitabın en kritik bölümlerinden birini overfitting'e karşı savunmaya ayırır. Çekirdek mesaj: **"Eğer 100 kombinasyon test ederseniz, 5'i şans eseri %95 confidence'ta anlamlı görünür."** Bu yüzden disciplined walk-forward zorunludur.

### In-sample / Out-of-sample (IS/OOS) Bölünmesi

- Tipik oran: %70-75 IS, %25-30 OOS. 
- Hiçbir koşulda OOS kararına dayalı parametre değiştirme — bu **OOS kontaminasyonudur**.
- OOS performansı IS'in <%40'ı ise sistem reddedilir.

### Walk-Forward Window Sizing

- **Anchored walk-forward**: IS sürekli büyür, OOS pencere ileri kayar.
- **Rolling walk-forward**: IS sabit uzunlukta, ileri kayar (trading sistemler için tercih edilen).
- IS pencere uzunluğu: en az **trade frequency'nin 100 katı**. Günde 1 trade veren sistem için ~6-12 ay IS.
- OOS pencere: IS'in 1/3 ila 1/4'ü.
- **Minimum 5 walk-forward fold** istatistiksel anlamlılık için.

### Parameter Robustness Testing

- **Plateau test**: optimal parametre etrafında ±%20 perturbation; performans %30'dan fazla düşmemeli.
- **Surrogate data test**: kuralı bozulmuş (shuffled) veri üzerinde çalıştır; orijinal performansla istatistiksel fark yoksa edge yok demektir.
- **Multi-market test**: aynı sistemi 5+ benzer market'te (BTC, ETH, SOL, BNB, AVAX) test et; biri hariç hepsi karlı olmalı.

### Multi-Objective Optimization Trapı

Kaufman uyarısı: "Sharpe + return + drawdown'u aynı anda maksimize etmek imkansızdır." Tek bir compound metric (örn. MAR = CAGR / MaxDD) seçip ona optimize edilmelidir. Veya pareto frontier üzerinden seçim yapılır — ama hiçbir koşulda 5+ metric'in lineer toplamı.

### Out-of-Sample Reuse Problemi

Bir sistemin OOS sonuçlarına bakıp parametre ayarlandığında, OOS de IS olur. Kaufman bunu **"OOS kontaminasyonu"** olarak adlandırır. Pratik kural: OOS bir kez görülür, gözlem sonucu sistem ya kabul ya reddedilir; "biraz değişiklikle tekrar deneyelim" zinciri her başarısız iterasyonla istatistiksel anlamlılığı iptal eder. Disiplinli pratik için **forward-looking OOS reservation** — yıllık birikecek yeni veri biriktirilir, sadece bağımsız doğrulama amacıyla bir kez kullanılır.

### Backtest Survivorship ve Selection Bias

Kaufman'ın araştırma disiplininin en sık unutulan kuralı: **"Test ettiğin 50 sistem versiyonundan en iyisini seçtiğinde, en iyi sistem değil, en şanslı seçim olabilir."** Multiple testing correction (Bonferroni, Benjamini-Hochberg) veya López de Prado'nun **deflated Sharpe ratio**'su uygulanmadan, k denenmiş sistem arasından en iyisinin "anlamlı edge" olarak ilan edilmesi yanlıştır. Pratik kural: 100 backtest'in sonunda en iyisi p < 0.001 göstermiyorsa, gerçekten anlamlı bir edge bulunmamış demektir.

## Risk Yönetimi

### Fixed Fractional Sizing

```
Position Size = (Equity × Risk_Per_Trade) / (Entry - Stop)
```

- Risk_Per_Trade tipik %0.5-2.0.
- %2 = "agressive limit"; sürekli %2 risk eden sistem 10 ardışık kayıpta %18 drawdown yaşar.
- Crypto için Kaufman analoğu: %0.5-1.0 daha güvenli, çünkü volatilite distribution'ı fat-tail.

### Optimal-f Kritiği

Ralph Vince'in optimal-f formülü teorik maksimum geometrik growth rate'i verir. Kaufman'ın eleştirisi:
- Optimal-f, **distribution'ın değişmediğini** varsayar — gerçekte değişir.
- Optimal-f'in %50-75'i ile çalışmak (fractional Kelly) pratikte daha iyi out-of-sample sonuç verir.
- Drawdown tolerance, optimal-f'in onda biri civarındadır; bu yüzden çoğu pratik sistem **0.1f - 0.25f** kullanır.

### Equity Curve Trading

Kaufman'ın özgün katkılarından biri: sistemin **kendi equity curve'ünü trade etmek**. Equity curve N-period MA'nın altına düştüğünde sistem off, üstüne çıkınca sistem on. Drawdown periyodlarında sermaye korunur, recovery periyodunda yeniden devreye girer. Pratikte:
- 20-period equity MA tipik.
- "False dip" riskine karşı re-entry confirmation gerekir.
- Backtest'te equity curve trading drawdown'u %30-50 azaltabilir, ancak total return de azalır.

### Portfolio-Level Diversification

- **Korelasyon matrix**: aktif sistemler arası rolling 60-day correlation. |ρ| > 0.7 olan iki sistem aynı portfolyoda gereksizdir.
- **Strategy diversification**: trend + mean-reversion + volatility breakout kombinasyonu, yapısal düşük korelasyon sağlar.
- **Market diversification**: aynı sistemi 8-15 enstrümanda paralel çalıştırma; tek-market noise idiosyncratic risk olarak diversify olur.
- **Equal-risk weighting**: her sistem/market'a eşit dollar değil, eşit **risk** (volatility-adjusted) ata. Yüksek-volatilite asset'e daha az kapital.

## Statistical / Quantifiable Edge Conditions

Kaufman, kitabın çeşitli yerlerinde sistem kategorilerinin tipik istatistiksel imzalarını verir. Bu imzalar, bir sistemin **kategori-içi normal performans** gösterip göstermediğini ölçmek için referans baseline'dır.

### Trend-following Imza

- Win rate: %30-40
- Average win / Average loss (R ratio): 2.5-4.0
- Profit factor: 1.5-2.5
- Annual Sharpe: 0.5-1.2
- Maximum drawdown: %20-40 (uzun, derin DD'ler kategoriye içkin)
- Recovery factor: 1.5-3.0
- Tipik trade duration: 20-100 bar

### Mean Reversion Imza

- Win rate: %60-75
- Average win / Average loss: 0.5-1.0
- Profit factor: 1.3-2.0
- Annual Sharpe: 1.0-2.0 (smooth equity curve)
- Maximum drawdown: %10-20 normal; %40+ rejim-değişiminde
- Tipik trade duration: 1-10 bar

### Momentum Imza

- Win rate: %45-55
- R ratio: 1.2-2.0
- Profit factor: 1.4-2.0
- Sharpe: 0.8-1.5
- Trade duration: 5-30 bar

### Crypto Bağlamında Uyarlamalar

Kaufman kitabı genel piyasa için yazılmıştır; crypto'ya uyarlama notlarımız:
- Volatilite 2-4× daha yüksek → ATR multiplier'ları 1.5-2× geniş tutulmalı.
- 24/7 trading → "daily" tanımı UTC midnight veya custom session.
- Gap yok ama wick'ler agresif → wick-aware stop conventions (close-based stop > intrabar stop).
- Fat-tail distribution daha extrem → Sharpe yanıltıcı; **Sortino ve Calmar** önceliklenmeli.
- Trend-following crypto'da **tarihsel olarak overperform**: BTC trend systems Sharpe 1.0-1.5, mean-reversion ise mid-cycle'da çöker (parabolic move'larda mean-reversion catastrofik).
- Win rate beklentileri: trend %30-40 (genel literatürle uyumlu), mean reversion %55-65 (genel literatürün altında — crypto trend-dominant).

## Performance Measurement

Kaufman'ın metric stack'i — bir sistemi değerlendirmek için minimum panel:

- **Profit Factor (PF)**: Gross profit / Gross loss. PF > 1.5 acceptable, > 2.0 strong, > 3.0 suspicious (overfit?).
- **Sharpe Ratio**: (Return - Risk-free) / σ. Annual scaling ile rapor. Sharpe > 1 good, > 2 great, > 3 verify-twice.
- **Sortino Ratio**: Sharpe ama denominator olarak downside-only deviation. Asymmetric distribution sistemler için Sharpe'tan üstündür.
- **Calmar Ratio (≈ MAR)**: CAGR / MaxDD. Trader'lar arasında en intuitive metric. Calmar > 0.5 acceptable, > 1.0 good, > 2.0 excellent.
- **MAR Ratio**: CAGR / |Max Drawdown|. Calmar ile yakın akrabası, hesaplama detayı farkı.
- **Recovery Factor**: Net Profit / |Max Drawdown|. Sistemin DD'sini kaç kez kazanca çevirdiği.
- **Average Bars per Trade**: trade horizon'unun ifadesi. Strateji kategorisi tutarlılığı için izlenir.
- **MAE (Maximum Adverse Excursion)**: trade boyunca maksimum unrealized loss. Stop-loss yerleşimini optimize etmek için kritik.
- **MFE (Maximum Favorable Excursion)**: trade boyunca maksimum unrealized gain. Profit-target yerleşimi ve trailing-stop kalibrasyonu için.
- **MAE/MFE oranı**: < 0.5 ideal — trade'in çoğunda düşük adverse, yüksek favorable excursion.
- **Win/Loss streak distribution**: en uzun consecutive loss serisi; risk sizing için psikolojik ve istatistiksel sınır.
- **Pessimistic Return on Margin (PROM)**: kazançların alt sınırı, kayıpların üst sınırı ile hesaplanan worst-case scenario. Kaufman'ın conservatism göstergesi.

Reporting protokolü: Her sistem için bu panel **IS, OOS ve live ayrı sütunlarda** gösterilmeli. IS-OOS sapması %30 üstündeyse ihtimal yüksek overfitting.

## Yaygın Hatalar / Pitfalls

### Curve-Fitting Indicator Parameters

Bir indicator'ün period'unu IS performansı maksimize edecek şekilde optimize etmek, parameterler 14, 13, 15 değil de 17 oluyorsa şüphelendirici. Kaufman'ın tavsiyesi: standart ("kanonik") period'lardan (10, 14, 20, 50, 200) sapma için **istatistiksel anlamlılık testi** zorunlu. Sapma ancak p < 0.05 ile justified.

### Multi-Objective Optimization Trapı

5 metric'i aynı anda iyileştirmeye çalışmak, gerçek bir edge'in yerine algorithm'in metric-cocktail'i optimize etmesine yol açar. Tek metric optimize edilmeli, diğerleri filter constraint olarak kullanılmalı (örn. Sharpe maximize subject to MaxDD < %25).

### Transaction Cost Neglect (Özellikle Düşük Timeframe'de)

5-min sistem, %0.05 round-trip cost ile karlı görünebilir; %0.10 ile (gerçekçi crypto fee + slippage) zarar etmeye başlar. Her backtest:
- Maker/taker fee ayrımı
- Slippage (volatility-scaled, örn. 0.1×ATR)
- Funding cost (perp için)
- Market impact (large size için)
modellemelidir.

### System Failure Mode Neglect

Her sistem **sonunda bozulur**. Kaufman'ın "system death" gözlemi: 5-10 yıllık sistemlerin %70'i sonunda performansını kaybeder (alpha decay). Live monitoring zorunlu:
- Rolling Sharpe drop > %50 → uyarı.
- Rolling drawdown > tarihsel %95 percentile → soğutma.
- Win rate kayma > 1σ → parametre re-validation.

### Survivor Bias in Backtest

Sadece bugün listelenen coin'lerle yapılan crypto backtest, delisted projeleri (LUNA, FTT vb.) atladığı için optimistic bias verir. Mümkünse delisted asset history dahil edilmeli; en azından sonuç bu uyarıyla raporlanmalı.

### Look-Ahead Bias

`shift(-1)` veya future-dependent feature'lar — naive panda sshift hatası. Her feature pipeline'da **causality test** (rastgele permutation sonrası performans çökmesi) yapılmalı.

## Cross-references

### Kaufman ↔ Chan

Ernie Chan'in kitapları (*Quantitative Trading*, *Algorithmic Trading*, *Machine Trading*) Kaufman'ın temellerini Python uygulamalarıyla genişletir. Kaufman sistem **tasarım** filozofisini verir; Chan ise **execution**, latency, statistical arbitrage ve cointegration testlerinin operasyonel detaylarını ele alır. KAMA gibi adaptive moving average kavramı Kaufman'da, Kalman filter ile online parameter estimation Chan'de — aynı problemin iki kuşağı.

### Kaufman ↔ Brooks

Al Brooks'un *Trading Price Action* serisi systematic'in tam karşıtıdır: discretionary, bar-by-bar context-dependent okuma. Kaufman, her formasyonu kurala dönüştürmeye odaklanırken Brooks "her bar'ın binlerce farklı yorumu vardır" der. **Sentez yaklaşımımız**: Brooks'un context taxonomisini (always-in-long, breakout, BTC trading range vb.) Kaufman'ın rule formalization disciplini ile rejim sınıflandırıcı feature'larına çevirmek.

### Kaufman ↔ López de Prado

López de Prado'nun *Advances in Financial Machine Learning* eseri, Kaufman'ın klasik walk-forward'ını **modern ML perspektifinden** delik gösterir: traditional cross-validation finansal verilerde leakage yapar; combinatorial purged cross-validation (CPCV) doğru çözümdür. Kaufman'ın IS/OOS bölümlemesi temel disipline; López de Prado'nun CPCV ve **deflated Sharpe ratio** (multiple-testing correction) modern güvenlik katmanı. **Bizim protokol**: Kaufman walk-forward + López de Prado CPCV + deflated Sharpe.

## Bizim Sistemle Bağlantı

- **Efficiency Ratio (ER)** ve **Adaptive Moving Average (KAMA)**: doğrudan `regime_classifier` modülümüzde feature olarak entegre edilebilir. ER, bizim trend strength score'umuzun bileşeni; KAMA, dinamik baseline olarak Donchian/Bollinger sabitlerinin yerine geçebilir. ER threshold'u (0.30) statik kullanmak yerine **rolling 60-bar percentile** olarak adapte etmemiz, Kaufman'ın "robust over optimal" felsefesiyle uyumludur.

- **Donchian breakout** (20/55): `strategies/` altına `donchian_baseline` olarak bir basit baseline strateji eklenebilir. Tüm yeni stratejiler bu baseline'a karşı **Sharpe ve Calmar farkı** ile karşılaştırılmalıdır; baseline'ı dövemeyen kompleks strateji reddedilmelidir (Kaufman ilkesi: "complexity must be earned").

- **Walk-forward protokolü**: zaten benimsediğimiz IS/OOS yapısı, Kaufman'ın 70/30 ve rolling fold yaklaşımı ile uyumludur. Eklemememiz gereken **plateau test** (optimal etrafında ±%20 perturbation robustness) bir TODO maddesidir.

- **Equity curve trading**: ileri katmanda risk overlay olarak değerlendirilmeli — sistem-of-systems portfolyomuzda her alt-sistemin equity curve'ünün 20-period MA'sı üzerinden auto-shutoff. Drawdown periodlarında sermaye korur.

- **Adaptive ATR multiplier**: stop-loss çarpanlarımızı sabit 2.0 yerine ER-bazlı 1.5-3.0 arasında dinamik yapmak, Kaufman adaptive method'larının doğrudan uygulamasıdır. Sıkı testle yan ve trending rejimde tutarlı iyileşme bekleriz.

- **MAE/MFE telemetrisi**: trade kayıt sistemimize MAE ve MFE eklenmesi (zaten partial olarak var), Kaufman'ın stop ve target placement diagnostic'ini kullanabilmemizi sağlar. Bu data trade-by-trade post-mortem ve parameter calibration için zorunlu girdi.

- **Performans paneli**: dashboard'umuzda Sharpe yanı sıra **Calmar, Sortino, Recovery Factor, Profit Factor** birinci-sınıf metric olarak yer almalıdır; özellikle crypto'nun fat-tail distribution'ı altında Sharpe yalnız başına yanıltıcıdır.

- **Survivor bias kontrolü**: backtest data pipeline'ımızda delisted asset'lerin (özellikle 2022 felaketleri: LUNA, FTT, CEL) tarihsel verisi dahil tutulmalı; salt mevcut top-100 ile yapılan backtest optimistic bias üretir.

- **System death monitoring**: live sistemlerin rolling 60-day Sharpe ve drawdown takibi alarmlı yapılmalı; alpha decay erken tespit, sermayeyi kurtaran tek mekanizmadır.