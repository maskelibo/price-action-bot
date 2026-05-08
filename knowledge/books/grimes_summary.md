---
source_id: grimes_summary
source_type: book
author: Adam Grimes
title: The Art and Science of Technical Analysis (notes)
type: reference_only
quality: 5
ingested_date: 2026-05-08
topic_tags: [classic_pa, statistical_edge, trading_psychology, market_phase, mean_reversion]
---

# Grimes — The Art and Science of Technical Analysis (özet notlar)

> Telif uyarısı: Bu doküman Adam Grimes'ın "The Art and Science of Technical Analysis" (Wiley, 2012) adlı eserinin ve adamhgrimes.com blog yazılarının kişisel çalışma notlarıdır; orijinal metnin yerine geçmez, ticari amaçla yeniden dağıtılamaz.

## Yazarın Çerçevesi

Adam Grimes'ın çalışmasının özünde iki sloganla özetlenebilecek bir epistemoloji vardır: **"The market is mostly random, but not entirely"** ve **"Edges exist, but they must be proven statistically"**. Bu iki ifade, kitap boyunca hem retorik hem yöntemsel bir çapa görevi görür. Grimes, fiyat hareketinin büyük bölümünün gürültü olduğunu kabul eder; teknik analiz literatüründeki şekil, formasyon ve "kalıp" zenginliğinin önemli kısmının istatistiksel olarak rastgeleden ayırt edilemeyeceğini açıkça söyler. Buna karşılık, gürültünün içinde küçük ama tutarlı sapmalar ("edges") vardır ve bunların varlığı ancak yeterli örneklem, doğru kontrol ve dikkatli istatistikle gösterilebilir.

Bu çift düstur, Grimes'ı klasik price action öğretisinden iki yönde farklılaştırır. Birincisi, "şekiller işe yarar çünkü kitabımda öyle yazıyor" tipi otoriter bir teknik analiz anlayışını reddeder. Bir formasyonu, koşullarını, taban oranını (base rate) ve regime hassasiyetini gösteremiyorsak; piyasaya o formasyonla girmek, kumarhaneye stratejisi olmadan girmekle eşdeğerdir. İkincisi, Grimes saf "siyah kutu" niceliksel yaklaşımı da yetersiz bulur: ham veri madenciliğiyle bulunmuş kurallar, market mikro yapısı veya likidite rejimi değiştiğinde sessizce çürür; tüccarın bunu fark etmesi için piyasanın "sanat" tarafında — context, narrative, order flow — eğitimli bir kavrayış gerekir.

Bu yüzden kitabın başlığı tesadüfi değildir: **art** + **science**. Sanat tarafı, deneyimli bir tüccarın tek bir grafik karesine baktığında sezgisel olarak okuduğu konteksttir — bir trendin yorgun mu, sağlıklı mı olduğu, geri çekilmenin "korkulu" mu yoksa "tedirgin alıcıların kâr alması" mı olduğu. Bilim tarafı ise her sezginin, gerçek parayla ifade edilmeden önce backtest, walk-forward ve monte carlo dirençlerinden geçirilmesi gerektiği disiplinidir. Grimes, kariyerinin başında saf diskresyoner pit-trader olarak başlamış, sonra hedge fund / proprietary kuantifiye dünyada çalışmış bir profil olarak bu iki kültürü doğrudan içselleştirmiştir; yazıları bu sentezi yansıtır.

Why most patterns are noise: Grimes'ın temel argümanlarından biri, "ben bunu chart'ta gördüm" gözleminin ne kadar güçlü hissettirse de bilimsel statüde sıfır olduğudur. İnsan beyni, rastgele dizilerde yapı arayan bir örüntü-bulma motorudur (apophenia). Pareidolia, hindsight bias ve confirmation bias birleştiğinde, herkes geriye dönük "iyi çalışan" formasyonlar bulur. Bir formasyonun gerçek bir edge taşıdığını söyleyebilmek için: (1) operasyonel kural önceden yazılmış olmalı, (2) yeterli sample (Grimes pratikte 100 işlem altını ciddiye almamayı önerir, 200+ tercih edilir), (3) baseline / null hypothesis üzerinden anlamlılık, (4) farklı sembol ve farklı regimelerde robustness gösterilmiş olmalıdır. Bunların yokluğunda gözlenen "pattern" varsayım olarak rastgele kabul edilir.

Trader olarak Grimes'ın tarzını şöyle özetleyebiliriz: küçük, doğrulanabilir avantajlar; yüksek frekansta tekrar; sıkı risk yönetimi; ve duygusal performansı veriyle disipline eden bir günlükleme alışkanlığı. Bu çerçeve, otonom bir trading sistemi için doğal bir entelektüel zemin sağlar; çünkü onun "edge ispatı" testleri bizim backtesting ve regime-classification katmanımızın doğrudan ön çalışmasıdır.

## Market Phase Modeli

Grimes'ın belki de en pratikte kullanılabilir katkısı, piyasayı dört faz altında modellemesidir. Bu, Wyckoff'tan ve klasik Dow teorisinden ilham alır ama Grimes'ın versiyonu istatistiksel olarak ölçülebilir tanımlar getirir. Dört faz:

**1. Trend.** Yön sahibi, momentumlu hareket. Yüksek-yüksekler ve yüksek-düşükler (yukarı trendde) düzenli olarak yapılır. ATR'a göre normalize edilmiş net hareket, lateral hareketten istatistiksel olarak anlamlı şekilde farklıdır. Volatilite genelde orta seviyelerdedir; "telaş" kadar yüksek değil, "ölü piyasa" kadar düşük değil. Trend fazında uygun setup kategorileri: pullback to moving average, "buy the second pullback", continuation flag/wedge.

**2. Pullback.** Trend içinde ters yönlü, kısa süreli, düzeltici hareket. Bu Grimes için ayrı bir faz olarak kritiktir çünkü en zengin entry fırsatları burada doğar. Pullback'in tanımı: ana trend yönünün karşısına 1-3 swing bar boyunca süren, ATR-cinsinden mevcut trendin ortalama ilerleyişinin altında kalan retracement. Tipik retracement seviyesi %38-62 (Fibonacci aralığı sadece referans, mistik olarak ele alınmaz) ve önceki swing low/high'a yakın MA'lar (20 ve 50 SMA) bu fazda confluence merkezi olur. Setup'lar: pin bar at MA, failure test of prior swing, breakout above pullback high.

**3. Consolidation (Range / Konsolidasyon).** Belirgin bir yön yok, fiyat dar bir yatay kanalda salınıyor. Volatilite tipik olarak sıkışmış (Bollinger band genişliği daralıyor, ATR düşüyor). Grimes konsolidasyonu "potansiyel enerji depolama" olarak görür: sıkışma uzadıkça kırılma olasılığı ve şiddeti artar. Setup'lar: range fade (top/bottom rejection), failure test inside range, "first false break".

**4. Breakout / Volatilite Expansion.** Konsolidasyonun veya küçük bir korelasyon yapısının kırılması; volatilitenin patlaması. Burada en kritik istatistik şudur: **çoğu breakout başarısızdır**. Grimes'ın blog'unda en sık vurguladığı sayılardan biri, hisse senedi günlük zaman diliminde "klasik tanımlı" breakoutların net edge'inin oldukça düşük (sıklıkla %50 etrafında win-rate, ortalama R düşük) olduğudur. Bu yüzden breakout fazında en kârlı setup paradoksal biçimde "failed breakout" — kırılmanın hemen ters çevrilip, çoğunluğun kapanına kapatılması — olabilir. True breakouts daha çok prior trend yönüyle aynı yöndeyken ve volatilite zaten yükselmeye başlamışken çalışır.

Her fazın istatistiksel imzası vardır:
- ADX yükseliyorsa ve fiyat MA üzerinde / altında kalıyorsa: trend olasılığı yüksek.
- ADX düşüyorsa, BB genişliği daralıyorsa: konsolidasyon.
- Birkaç gün içindeki ATR sıçraması + range out break: breakout fazına geçiş.
- Trend içinde ATR-normalize 0.5-1.0 aralığında karşı yönlü hareket: pullback.

Grimes'ın altını çizdiği kural: **setup ile faz uyumlu olmalıdır.** Bir mean-reversion (range fade) setup'ını trend fazında uygulamak, sistematik kayıp üretir. Bu yüzden phase classification, herhangi bir tetik kuralının önüne yerleştirilmesi gereken bir zorunlu filtredir. Bizim sistemimizdeki `regime_classifier` modülünün entelektüel atası budur.

## Bar Anatomisi ve Tanımlar

Grimes, mum/bar formasyonlarına Japon mum çubukları kitaplarındaki "exotic name" yaklaşımıyla değil, ölçülebilir geometrik tanımlarla yaklaşır. Üç temel yapı:

**Pin Bar (Reversal Bar / Rejection Bar).** Grimes'ın imza setup'ının yapı taşı. Tanım kriterleri:
- Bar'ın gövdesi (|close − open|) toplam range'in (high − low) en fazla **1/3'ü**.
- Bir tarafta uzun fitil (wick), bu fitil gövdenin **en az 2 katı** uzunluğunda. Grimes'ın blog'unda sıkça verdiği wick:body oranı için minimum eşik **2:1** civarındadır; daha katı taramalar 3:1 veya bağlam koşullarıyla birleşir.
- Bar'ın kapanışı, fitilin tersi taraftaki üçte birlik dilimde (yani satışın geri çevrildiği bir bar için kapanış range'in üst 1/3'ünde).
- Lokasyon: rastgele yerde değil; önemli S/R, prior swing high/low, MA, trend kanalı sınırı veya measured-move hedefi yakınında olmalı. Grimes'a göre lokasyon yoksa pin bar yoktur — sadece düşük gövdeli bir bardır.

**Doji.** Açılış ≈ kapanış (range içinde gövde %5'ten az). Grimes doji'yi tek başına bir entry sinyali olarak değil, sadece "tereddüt" göstergesi olarak ele alır. Trend yorgunluğu veya konsolidasyona geçiş ipucu sağlar; ama doji üzerine kuru entry kurmak, blog'unda sıkça eleştirdiği bir hatadır.

**Engulfing Bar.** Bullish engulfing: bullish bar'ın gövdesi önceki bearish bar'ın gövdesini tamamen kapsar (open önceki close'un altında, close önceki open'ın üstünde). Grimes burada **reference bar size** kriterini kritik bulur:
- Önceki bar küçükse engulfing önemsizdir; sadece düşük volatiliteli bir tek-bar gürültüsünü kapsamış olur.
- Reference bar, son N bar (genelde 5-10) ortalama range'inin en az %80'i kadar olmalıdır.
- Engulfing bar, son N bar maksimum range'inin en az %120'si seviyesinde olmalı, yani gerçek bir momentum patlaması göstermeli.
- En güçlü engulfing'ler trend dönüşlerinden çok pullback sonrası continuation'da çıkar.

**Inside-Outside-Inside (IOI).** Üç bar dizilimi: inside bar (önceki bar'ın range'i içinde), sonra outside bar (önceki bar'ın range'ini aşan), sonra tekrar inside. Bu yapı sıkışma + yanlış kırılma + sıkışma anlamına gelir ve Grimes bunu "bir sonraki güçlü hareketin kapı eşiği" olarak değerlendirir. Outside bar'ın yönü genelde son hareketin yönüne göre yorumlanır; IOI sonrası inside bar'dan dışa kırılma yönü, çoğunlukla devam eden trendi onaylar.

Diğer yapısal terimler: **inside bar** (range önceki bar'ın range'i içinde, sıkışma sinyali), **outside bar** (range önceki bar'ı kapsar, expansiyon sinyali), **two-bar reversal** (iki bar üst üste, ilk bir yönde güçlü, ikinci tam tersi güçlü kapanış), **NR4/NR7** (last-N bar içinde en dar range — volatilite expansiyon adayı).

Grimes ayrıca **"climax bar"** kavramına ağırlık verir: ATR'ye göre 2-3 sigma dışında, hacimle desteklenen tek bir patlayıcı bar. Climax bar genelde trend ucudur; arkadan gelen ilk pullback'i fade etmek (yani trend yönünde tekrar pozisyon almak yerine karşı taraftan deneme yapmak) çoğu zaman karlıdır, çünkü climax bar trendin son alıcılarını veya satıcılarını piyasaya çekmiştir.

## Setup Kataloğu

Aşağıda Grimes'ın eserlerindeki ana setup'ların 7-block formatında özeti yer alıyor (tetik / lokasyon / kontekst koşulu / stop / hedef / risk-ödül beklentisi / istatistiksel imza).

### 1) Pin Bar at S/R (Grimes'ın imza setup'ı)
- **Tetik:** Yukarıda tanımlı pin bar (wick:body ≥ 2:1, kapanış aksi 1/3 içinde) önemli yatay S/R, prior swing veya MA seviyesinde basıyor.
- **Lokasyon:** Daily ya da 4H grafik, prior swing high/low veya 20/50 SMA, round number; tek başına grafik ortasında pin bar setup değildir.
- **Kontekst:** En az iki confluence (örn. yatay seviye + MA, veya MA + trend kanalı). Trend yönüyle aynı taraflı pin bar (pullback bittiğine işaret eden) Grimes için en yüksek beklentiye sahip versiyonudur.
- **Stop:** Pin bar fitil ucunun bir miktar (genelde 0.1-0.25 ATR) ötesi.
- **Hedef:** İlk hedef: bir önceki swing seviyesi ya da 1R; ikinci hedef: measured move (önceki dalga boyu kadar projeksiyon).
- **R-Beklentisi:** Grimes'ın blog'unda standalone pin bar için verdiği rakamlar yaklaşık **%50 win rate, ortalama R 1.0-1.2**. Confluence + trend uyumlu versiyonda **%58-62 win rate, ortalama R 1.4-1.6** seviyelerine çıkar; bu da kayda değer bir edge'dir.
- **İstatistiksel imza:** Bağımsız değişken olarak "S/R'ye temas + pin bar geometrisi + trend yönü" alındığında, daily timeframe'de likit hisse evreninde pozitif beklenti üretir.

### 2) Failure Test (Wyckoff Spring / Upthrust adaptasyonu)
- **Tetik:** Fiyat önemli bir desteğin altına (veya direncin üstüne) kısa süreliğine kırılır, ardından hızla seviyenin diğer tarafına geri döner ve önceki bar'ın range'i içinde kapanır.
- **Lokasyon:** Konsolidasyonun alt/üst sınırı, prior swing low/high, range bottom/top.
- **Kontekst:** İdeal olarak konsolidasyon fazında veya trend pullback'inin uç noktasında. Hacim eşliği (eğer veri varsa) güçlendirici faktör — Wyckoff'un spring konseptiyle birebir örtüşür.
- **Stop:** Failure noktası dışındaki en uç fiyatın hemen ötesi (1 ATR ya da 0.25 ATR pad).
- **Hedef:** Range'in karşı sınırı; trend pullback versiyonunda prior trend hedefi.
- **R-Beklentisi:** Grimes failure test'i en yüksek expected-value setup'larından biri olarak işaretler. Tipik **%55-65 win rate, ortalama R 1.5-2.0**.
- **İstatistiksel imza:** Likit enstrümanlarda failure test, "stop hunt" mikro yapısının doğal sonucu; piyasa yapıcıların stopları topladıktan sonra ters yöne hareket etmeye eğilimi nedeniyle istatistiksel olarak anlamlı bir kalıntı edge taşır.

### 3) Pullback to Moving Average (20/50 SMA confluence)
- **Tetik:** Trend fazında, fiyat 20 ya da 50 SMA'ya geri çekilir, MA'ya temas eden bir pin bar / engulfing / küçük bar serisi sonrası prior bar'ın aksi yönüne kapanış.
- **Lokasyon:** 20 SMA için "yakın temas" 0.5 ATR içinde olmalı; 50 SMA için 1 ATR'ye kadar tolere edilebilir. Önceki swing low/high ile çakışma idealdir.
- **Kontekst:** Belirgin trend (en az 3-4 swing high+low'lik yapı), ADX > 20 tipik filtre. İlk pullback bazen erken; Grimes "**buy the second pullback**" kuralını öne çıkarır (aşağıda).
- **Stop:** MA'nın diğer tarafı + 0.5-1 ATR; ya da setup mum'unun aksi ucu.
- **Hedef:** Önceki swing high/low (trend yönündeki); ikinci hedef measured move.
- **R-Beklentisi:** Saf MA pullback %50 win rate civarında; trend gücü filtresi + bar kalitesi eklenince **%55-60 win, R 1.3-1.7**.
- **İstatistiksel imza:** MA seviyesinin "kendi başına" anlamı düşüktür; ama trend yapısı ile birleştiğinde retrace + continuation için doğal toplanma noktası işlevi görür.

### 4) Anti — Counter-trend Mean Reversion
- **Tetik:** Trend yönünde aşırı uzayan ("overextended") hareket sonrası ilk küçük pullback başlangıcında trend yönünde değil, KARŞI yönde küçük bir kontre pozisyon almak. İsim: "Anti".
- **Lokasyon:** Trendin ölçüsüz uzaması — örneğin Bollinger band dışına 2 sigma+ basan bar; climax bar; ATR'nin 2 katından büyük günlük hareket.
- **Kontekst:** Bu setup Grimes için zor ve yüksek-iskontolu bir setup; sadece deneyimli traderlar için. Win rate düşük (~%40-45), ama R büyük (2-3R) olabilir; expected value hafifçe pozitif kalır.
- **Stop:** Climax/extension high/low'unun ötesi.
- **Hedef:** İlk anlamlı destek/direnç, MA, ya da prior swing.
- **R-Beklentisi:** Düşük win rate, yüksek R; net ortalama beklenti **0.2-0.4R/işlem**.
- **İstatistiksel imza:** Mean reversion tarafında zaman dilimi seçimi kritik; günlük TF'de iyi çalışır, daha yüksek TF'de bozulur.

### 5) Continuation Pattern Entries (flag, wedge, triangle)
- **Tetik:** Trend içinde küçük korelasyonel sıkışma (flag = paralel kanal, wedge = daralan üçgen). Kırılım trend yönünde olur.
- **Lokasyon:** Önceki impulsif hareketin ardından oluşan 5-15 barlık consolidation.
- **Kontekst:** Flagpole (pre-flag impulse) güçlü olmalı (ATR'ye göre 2x+); flag'in sürmesi 1/3 ila 1/2 oranında flagpole süresi içinde sınırlı.
- **Stop:** Flag'in karşı tarafı.
- **Hedef:** Measured move — flagpole boyunun flag breakout noktasından projeksiyonu.
- **R-Beklentisi:** Saf chart-pattern olarak mütevazı; kalite filtreleriyle (impulse strength, time-in-flag) **%55 win, R 1.3-1.5**.
- **İstatistiksel imza:** Flag'lerin başarı oranı, prior trend gücü ile pozitif korelasyondadır; bu ilişki Grimes'ın blog test serilerinde tutarlı görünür.

### 6) Trend-Following: "Buy the Second Pullback"
- **Tetik:** Yeni trendde ilk pullback'i ATLAYIP, ikinci pullback'i giriş için kullanmak.
- **Lokasyon:** İlk pullback prior swing high'ın üstüne taze bir HH yaptıktan sonra geri çekilen ikinci dalga.
- **Kontekst:** Grimes'ın çok defalar tekrarladığı kural: "Trendin ilk pullback'i tuzaktır — eski trend yönünden gelen alıcılar zaten yorgundur, yeni trend ise henüz pozisyonunu kurmamıştır. İkinci pullback en yüksek olasılıklı entry'dir." Bu, klasik price action sezgisinin niceliksel doğrulamasıdır.
- **Stop:** İkinci pullback'in low/high'ının altı/üstü.
- **Hedef:** Measured move + trailing stop ile trend yönünde uzatma.
- **R-Beklentisi:** En yüksek beklentili setup'lardan biri Grimes'ın testlerinde. **%58-65 win rate, ortalama R 1.6-2.0**.
- **İstatistiksel imza:** Yeni trendin ikinci pullback'inde erken-bağlanma alıcıları + breakout traderları + stop-out olmuş eski yön traderları aynı yönde birleşir; bu mikro yapı, niceliksel olarak en saf "edge" üretir.

### 7) Range Trade Fades (top/bottom rejection)
- **Tetik:** Konsolidasyon fazında range üst veya alt sınırına temas + rejection bar (pin/engulfing).
- **Lokasyon:** Belirgin yatay range; üst ve alt sınırlar en az 2-3 kez test edilmiş.
- **Kontekst:** Range fazı doğrulanmış (ADX düşük, BB sıkışık). Range break tehlikesi varsa setup riskli — Grimes "range trader has to be ready to be wrong" der.
- **Stop:** Range sınırının ötesi + 0.3-0.5 ATR.
- **Hedef:** Range orta noktası (1. hedef), karşı sınır (2. hedef).
- **R-Beklentisi:** **%55-60 win, R 1.0-1.5**; range break olduğunda büyük loser olur, bu yüzden disiplin kritik.
- **İstatistiksel imza:** Mean-reversion setup'ları range'lerde pozitif edge taşır; trend fazında aynı kuralın net beklentisi NEGATİFTİR — bu yüzden phase filter şart.

### 8) Volatility Expansion / Contraction Transitions
- **Tetik:** N gün içinde en dar range (NR7 vs.) sonrası ilk yön kırılışı (volatility expansion) ya da tersine, çok geniş range serisinden sonra inside bar (contraction'a geçiş).
- **Kontekst:** Volatilite döngüseldir — düşük volatilite yüksek volatiliteye, yüksek de düşüğe geri döner. Bu setup volatilite rejimi geçişini avlar.
- **R-Beklentisi:** Volatilite genişlemesi setupları ortalama %50 win civarında ama R büyür; expected value hafif pozitif. Volatilite daralma + iyi pozisyonlanmış stop, asimetrik fırsat sunar.

### 9) News-Driven Gap Fade vs Continuation
- **Tetik:** Açılış gap'i sonrası ilk bir saat-iki saatlik price action.
- **Kural:** Grimes blog'unda klasik "gap fade istatistiği" ile "gap and go istatistiği"ni ayrıştırır. Küçük gap'ler (ATR'nin altı) **fade etmeye eğilimli**, büyük gap'ler (1-2 ATR+) **devam etmeye eğilimli**. Trend yönünde gap + güçlü ilk-saat momentum = continuation; karşı yönde küçük gap + early reversal = fade.
- **R-Beklentisi:** İyi sınıflandırılmış gap sınıflarında **%55-60 win**, ham gap istatistiği rastgeleye çok yakın.

## Bağlam ve Filtre Kuralları

Grimes'ın metodolojisinde "kontekst" boş bir kelime değildir; ölçülebilir filtreler topluluğudur. Bunların başlıcaları:

**Minimum trade sample.** Bir setup'ın "edge'i var" diyebilmek için Grimes en az **birkaç yüz işlemli** historik örneklem ister. 30-50 işlem çıktısı ile karar vermek, istatistiksel olarak "pozitif görünen rastgele örneklem" tehlikesi taşır. Pratikte 200+ işlem ve farklı sembol/sektör setlerinde tekrarlanmış sonuçlar bekler.

**Monte Carlo simulation.** Geriye dönük backtest sonucu tek bir "ortalama" değil, **dağılım** olarak değerlendirilmelidir. Trade sırasını rastgele permüte ederek (Monte Carlo bootstrap) maksimum drawdown dağılımını çıkarmak kritik. Sistemin ortalama %8 drawdown'u olabilir ama %95 percentil drawdown'u %20 ise, ruh sağlığı / sermaye yönetimi planında %20'yi tolere edebilmelisiniz. Grimes "**plan for the worst Monte Carlo path, not the average path**" der.

**Regime sensitivity ("regime is everything").** Bir sistemin son 5 yılda iyi çalışması, gelecekteki rejimde de çalışacağı anlamına gelmez. Grimes regime'i şöyle anlar: volatilite seviyesi, korelasyon yapısı, monetary policy ortamı, sektör rotasyonu rejimi. Bir trend-following sistem, düşük-volatilite + yatay rejimde sürekli kayıp verir; bunu önceden bilmek, drawdown anında sistemi terk etmemizi engeller. Sistemin hangi rejimde iyi, hangi rejimde kötü çalıştığı backtest'in başlıca çıktısı olmalıdır.

**Volatility-normalized entry/stop.** Sabit pip / sabit dolar stoplar Grimes'a göre yanlıştır; çünkü farklı semboller ve farklı dönemler farklı volatilite seviyelerine sahiptir. Stop ve hedefler **ATR cinsinden** ifade edilmelidir (örn. stop = 1.5 ATR, hedef = 2 ATR). Bu, sembol değiştiğinde de, volatilite rejimi değiştiğinde de tutarlı risk-ödül oranı sağlar.

**Confluence skoru.** Tek sinyal nadiren yeterlidir; Grimes en az 2-3 bağımsız faktörün üst üste binmesini ister: bar pattern + S/R + trend yönü + MA + zaman dilimi uyumu. Confluence sayısının istatistiksel etkisini test ederek "kaç confluence olduğunda win-rate ne kadar artıyor" tablosunu çıkarmak gerekir.

**Time-of-day / time-of-week filtreleri.** Intraday için saat etkisi belirgindir; Grimes günlük TF'de bile haftaiçi-vs-haftasonu, ay başı-vs-ay sonu, FED açıklama günleri gibi takvim filtrelerini test etmeyi önerir.

**Symbol heterogeneity testi.** Bir kuralı tek hisse / tek sembolle bulup uygulamak overfit'tir. Aynı kural en az 20+ sembolde robust olarak çalışmalı.

## Risk Yönetimi

Grimes risk yönetimini setup seçiminden ÖNDE tutar — bunu kitabında ve blog'unda defalarca vurgular: "**Risk management is not a defense, it is the offense.**"

**Position sizing matematiği.** Sabit fraksiyon yöntemi (fixed fractional): her işlemde portföyün %X'ini riske et. Tipik X değerleri Grimes için %0.5-1.0 (profesyonel düzey), perakende için ≤ %1. Pozisyon boyutu = (hesap × risk yüzdesi) / (entry − stop, dolar cinsinden). Volatilite-normalize edilmiş stop bu hesabın ön koşuludur; aksi halde sembolden sembole risk dengesizleşir.

**Expected Value (EV) hesabı.** Her setup için:
EV = (win_rate × ortalama kazanç) − ((1 − win_rate) × ortalama kayıp).
Bir setup'ın trade edilmeye değer olabilmesi için EV > 0 olmalı; ayrıca işlem maliyetleri (komisyon, spread, slippage) düşüldükten sonra hala pozitif kalmalıdır. Grimes'ın blog'unda gösterdiği bir nokta: backtest sonuçlarının slippage olmadan değerlendirilmesi, sistemleri yapay olarak iyimser göstermenin en yaygın yoludur.

**Kelly formülü konusunda kuşku.** Klasik Kelly fraksiyonu: f* = (bp − q) / b. Grimes Kelly'ye doğrudan güvenmemeyi öğretir. Sebepler: (1) win-rate ve ortalama R-multiple gerçek değerleri tam olarak bilinmez, sadece tahmin edilir; (2) tahmin hatası küçük olsa bile Kelly'nin kendisi "üstte" ölçeklendiğinde drawdown'u patlatır; (3) Kelly variansı ihmal eder, ancak gerçek hayatta drawdown yolu önemlidir. Pratik öneri: **fractional Kelly (genellikle 1/4 ila 1/2 Kelly)** kullanmak ya da daha güvenli olan sabit-fraksiyon yöntemine bağlı kalmak.

**Drawdown psikolojisi.** Grimes drawdown'u sayıdan çok deneyimden ele alır. %20 drawdown matematiksel olarak %25 toparlanma gerektirir; ama duygusal olarak ve özellikle başkasının parasını yönetiyorsanız çok daha yıkıcıdır. Drawdown'da insan beyni "kuralları değiştirme" baskısı uygular; istatistiksel olarak yanlış hareket. Drawdown yaşanmadan önce "bu drawdown beklenen Monte Carlo dağılımı içindeyse devam, dışındaysa dur" kuralı yazılı olmalı.

**"Consistency over occasional grand slam."** Grimes'ın en sıkça tekrarlanan ilkesidir. Tek büyük kazanç hayalleri kuran tüccar, sıkı kuralları gevşetir; risk yönetiminde gevşeme kaçınılmaz biçimde tail risk'i ısırılmaya götürür. Profesyonel performans, küçük edge'lerin yüksek frekansla ve sıkı disiplinle tekrarlanmasıdır. Bu prensip, grand slam'i kovalayan retail kültürünün doğrudan eleştirisidir.

**Risk-of-ruin hesabı.** Bir sistemin EV'si pozitif olsa bile, çok büyük position sizing ile kullanılırsa "bir kötü streak'te hesabı sıfırlama" olasılığı (risk of ruin) anlamlı bir değere çıkar. Grimes risk-of-ruin'i %0.5 altında tutmayı önerir; bu da position sizing'i fractional Kelly'den bile aşağıda tutmayı gerektirir.

**Correlation-aware sizing.** Aynı yönde 5 trade açıyorsanız ve hepsi yüksek korele varlıklarsa, gerçek risk %5 değil %4'e yakındır (varlıklar korele çünkü). Sistem bunu hesaba katmazsa "kağıt üzerinde" %1 riskli görünen pozisyonlar gerçek bir tail event'te %4-5 silinir. Risk modelinde korelasyon matrisi tutmak zorunlu.

## Statistical / Quantifiable Edge Conditions

Grimes'ın blog ve kitabında verilen somut sayılardan derleme (yaklaşık değerler, kendi backtestlerini tekrar etmeniz şart):

**Pin Bar (standalone, S/R filtresi olmadan):** Win rate **~%50**, ortalama R-multiple **1.0-1.2**. Net edge sıfıra yakın; hatta komisyon/slippage sonrası negatif olabilir.

**Pin Bar + S/R + trend yönü uyumu (full confluence):** Win rate **~%58-62**, ortalama R **1.4-1.6**. Net pozitif beklenti; tradable edge.

**Engulfing (standalone):** Win rate **~%48-52**, ortalama R **1.0**. Tek başına edge'siz.

**Engulfing + reference bar size criteria + trend continuation:** Win rate **~%55-60**, ortalama R **1.3-1.5**. Pozitif.

**Failure test at range / swing:** Win rate **~%55-65**, ortalama R **1.5-2.0**. Grimes'ın en yüksek beklentili setup'larından biri.

**MA pullback (20/50 SMA):** Saf hali %50 civarı win rate. Trend strength + bar quality filtresiyle **~%55-60** win, R **1.3-1.7**.

**Buy the second pullback:** **~%58-65** win rate, ortalama R **1.6-2.0**.

**Range fade (range fazı doğrulanmış):** **~%55-60** win, R **1.0-1.5**. Range break'te büyük loser; sample integrity için range break dışlanmamalı, içinde hesaplanmalı.

**Classical breakout (rastgele tetik):** **~%50** win, R **0.9-1.1**. Net edge yok; "failed breakout fade" çoğunlukla daha iyi.

**Climax bar reversal (next day fade):** Win rate **~%55**, R **1.2-1.5**.

**Genel kural:** Grimes'ın istatistik tablolarında ortak motif: tetik (bar pattern) tek başına neredeyse hiçbir zaman %50 win-rate'in anlamlı şekilde üstüne çıkmaz; edge **bağlam filtreleriyle** kazanılır. Bu, "indicator simulation" tipi mekanik backtestin neden çoğunlukla başarısız olduğunun istatistiksel açıklamasıdır.

**Sample size uyarısı:** Yukarıdaki rakamlar Grimes'ın kendi backtestlerinden anılır; farklı veri seti, farklı zaman dilimi, farklı sembol evreni ile bu değerler kayar. Kendi sistemimizde bu sayıları doğrudan import etmek yerine, kendi backtestlerimizle yeniden üretmek zorundayız — Grimes'ın kendisi de bunu söyler: "**Don't trust my numbers, run your own.**"

## Trader Psikolojisi (Grimes'ın bilimsel yaklaşımı)

Grimes psikolojiyi popüler "trade your edge with calm mind" söylemleri olmaktan çıkarıp, bilişsel yanılsamaların somut listesine indirger:

**Confirmation bias.** Bir setup'a inandıktan sonra trader, onu doğrulayan göstergeleri arar, çürüten verileri görmezden gelir. Çare: önyargılı olmayan rapor şablonu — her trade öncesi "bu trade'in işe yaramayacağına dair en güçlü kanıt nedir?" sorusunu yazılı olarak yanıtlamak.

**Hindsight bias.** "O dönüşü görebilirdim" hissi, geriye dönük bakıldığında sinyalin belirgin görünmesinden kaynaklanır. Aslında o sinyal, gerçek zamanlı 50 olası alternatif sinyal arasından sonradan seçilmiştir. Çare: real-time sinyal log tutmak (Grimes'ın "deliberate practice journal" dediği şey); sonra geriye dönüp gerçek zamanda neyi gördüğümüzü kanıtlayabilmek.

**Illusion of control.** Trader, bir sistem üstünde "ufak ayar" yaparak performansı iyileştirebileceğine inanır. Genelde bu, kontrol illüzyonu — küçük örneklemde gözlenen rastgele varyans gerçek bir parametre etkisi sanılır. Çare: her parametre değişikliğini formal A/B testle, tercihen out-of-sample veride değerlendirmek.

**Recency bias.** Son 5 trade'in sonucu, bir sonraki trade'in beklentisini orantısız etkiler. 3 ardışık kayıp sonrası tüccar pozisyon boyutunu küçültür ya da setup'ı atlar — kayıt dışı disiplinsizlik. Çare: pozisyon boyutu kuralı yazılı, mekanik; psikolojik durum girişi yasak.

**Loss aversion.** Aynı miktarda kayıp, kazançtan ~2x daha fazla hissedilir. Bu, kötü kararlara yol açar: "biraz daha bekleyeyim, dönecek" tipi stop genişletmesi. Çare: stop önceden konur, asla genişletilmez (Grimes'ın katı kuralı: "**stops only get tighter, never looser**").

**Why journaling is mandatory.** Tüccarın bilişsel zaaflarına karşı yegane sistematik savunma, dış-bellek sistemidir. Grimes'ın önerdiği günlük şablonu: trade öncesi (setup, neden bu sembol, neden şimdi, beklentim, alternatif senaryo), trade sırasında (duygusal not), trade sonrası (sonuç, kuralı bozdum mu, nerede, ne öğrendim). Haftalık review'de pattern'lar belirir — kurallarımızı en sık nerede ihlal ettiğimiz, hangi setup'ta gerçekten edge'imiz olup olmadığı.

**Deliberate practice.** Grimes, Anders Ericsson'un "deliberate practice" kavramını trading'e uyarlar: gelişigüzel screen-time sayma değil, tanımlı zorluk seviyesinde, anlık feedback ile, hata düzeltme döngüsünde tekrar. Pratikte bu: belirli setup'ı tek başına izole edip 100+ historik örnek üzerinde "real-time gibi" karar verme talimi; sonra sonuçları kıyaslama. Bu uygulama, sezginin (sanat tarafı) eğitilmiş hale gelmesinin tek yoludur.

**Fixed mindset vs growth mindset.** Trading'de "ben iyi bir trader'ım" sabit kimliği, ilk büyük drawdown'da kırılır. Bunun yerine "her trade benim için bir veri noktası, ben sürekli kalibre ettiğim bir sistem operatörüyüm" çerçevesi, drawdown'da bile öğrenmeye devam etmeyi sağlar.

## Yaygın Hatalar / Pitfalls

Grimes'ın blog'unda ve kitabında uyardığı en kritik tuzaklar:

**"Trading the chart instead of the data."** Grafik üstünde sezgisel olarak "güzel görünen" işlemler yapmak, niceliksel doğrulamadan kaçmak. Bu, kariyer sonu hatasıdır; kazançlı dönemler talihten gelir, zararlı dönemler kaçınılmazdır.

**Over-fitting one-shot patterns.** Tek bir hisse / tek bir dönemde "harika çalışan" bir kuralı yakalamak ve onu sistem haline getirmek. Out-of-sample'da kural çöker. Çare: test setini başından ikiye böl (in-sample / out-of-sample) ve kural sadece in-sample'da geliştir.

**Ignoring base rate.** Bir formasyonun tek başına olasılık dağılımı (base rate) bilinmeden, formasyon-sonrası beklenti hesaplanamaz. "Pin bar yukarı dönüş demek" değil; "pin bar görüldükten sonra X bar içinde Y hareket olma olasılığı %Z; bu, Z'nin null hipotezindeki rastgele rate ile farkı budur" demek.

**Strategy switching after losing streak.** En öldürücü hata: sistem 5 trade kaybediyor, tüccar "bu sistem artık çalışmıyor" diyerek başka sisteme geçiyor. Yeni sistem de zaten kötü streak'in tipik sonu olduğu için iyi başlıyor; tüccar yeni sisteme inanıyor; o da kaybetmeye başladığında bir sonraki sisteme atlıyor. Bu döngü, **survivorship'in gözlemcisi olmak yerine kurbanı olmak**.

**Adding to losers.** Pozisyon kötüye gittiğinde "ortalamayı düzeltme" bahanesiyle pozisyon büyütmek. Grimes net: bu kural, beklenen değer açısından bile pozitif olsa bile, drawdown ve risk-of-ruin yapısında negatif. Sadece "scaling-in" planlanmış sistemde, önceden tanımlı seviyelerde, izin verilebilir.

**Over-leverage / oversize.** İyi sistemleri kötü performans gösterir hale getiren 1 numaralı sebep. Sistem matematiksel olarak iyi; ama %5 risk per trade'de, kaçınılmaz drawdown trader'ı zihinsel olarak kırar; kuralları bozar; sistem ölür.

**Ignoring transaction costs in backtests.** Sıfır komisyon, sıfır slippage backtest'leri, gerçekçi olarak çalışan birçok sistemi yapay olarak başarılı gösterir. Daily TF'de bile küçük slippage edge'in büyük kısmını silebilir.

**Curve fitting via too many parameters.** Sistemde 6+ optimize edilmiş parametre varsa, neredeyse kesinlikle overfit'tir. Grimes "az parametre, sağlam parametre" der.

**Confusing "I followed the rules" with "rules are good."** Disiplin başlı başına edge sağlamaz. Disiplinli bir şekilde negatif-EV sistemi tradeleyebilirsiniz. Disiplin, ÖN-ŞART; ama edge ispatı bağımsız bir şart.

**Forgetting opportunity cost.** Bir stratejinin %10 yıllık getirisi varsa ama paranızın 6 ayını drawdown'da tutuyorsa, opportunity cost yüksek. Sermaye verimliliği (deployment ratio) raporlanmalı.

## Cross-references

**Brooks ile karşılaştırma.** Al Brooks (özellikle "Trading Price Action" üçlemesi) ile Grimes'ın çakıştığı çok nokta var: bar-bar okuma, trend / range / breakout fazları, swing yapısı. Ancak Brooks belirgin biçimde **diskresyoner** — tek tek bar etrafındaki sezgisel okumayı kuralın önüne koyar; setup sayısı 60+ ile çok zengindir ve formal istatistik nadirdir. Grimes ise **istatistiksel** — daha az setup, ama her birinin tablo halinde edge ispatı vardır. Pratikte: Brooks'tan setup vokabüleri ve bar okuma sezgisi alınır; Grimes'tan filtreleme, doğrulama ve risk yönetimi alınır. Birlikte tamamlayıcıdır.

**Volman ile karşılaştırma.** Bob Volman (özellikle 70-tick / 5-min FX) **intraday + scalping** odağında çalışır; setup'ları 5 dakikalık çubuklarda yoğunlaşmıştır (ARB, BB, DD, vb.). Grimes ise daha üst zaman dilimlerini (4H / daily / weekly) tercih eder. Bu yüzden ikisinin setup'ları çoğu zaman aynı geometriye sahip ama farklı zaman dilimlerinde uygulanır. Volman'ın setup yapı taşları Grimes'ın bar tanımlarıyla uyumludur (pin bar, engulfing, inside bar). Multi-timeframe sistem kurarken Volman intraday giriş, Grimes daily trend bağlamı sunar.

**Lopez de Prado ile çakışma noktaları.** Marcos Lopez de Prado (özellikle "Advances in Financial Machine Learning") tamamen kuantitatif/akademik perspektifte yazar; ML, walk-forward, purged k-fold cross-validation, deflated Sharpe, fractional differentiation gibi araçlar getirir. Grimes ile ortak nokta: **istatistiksel sıkılığın** trading'de tek savunulabilir yol olduğu. Lopez de Prado'nun "deflated Sharpe" konsepti, Grimes'ın "Monte Carlo with permutation testing" pratiğinin akademik formalleştirilmesidir. Lopez de Prado'nun "backtest overfitting" kavramı, Grimes'ın "over-fitting one-shot patterns" uyarısının matematiksel versiyonudur. Lopez de Prado çok daha derin teknik araçlar sunar; Grimes ise pratikte kullanılabilir, daha az katı bir versiyondur. İkisi birlikte: niceliksel altyapı (Lopez de Prado) + price action özel uygulamaları (Grimes) + diskresyoner sezgi (Brooks) bütünlüklü bir araç takımı oluşturur.

**Wyckoff ile bağlantı.** Grimes'ın failure test setup'ı Wyckoff'un spring/upthrust kavramının doğrudan modern uygulamasıdır. Phase modeli (Trend / Pullback / Consolidation / Breakout) Wyckoff'un (Accumulation / Markup / Distribution / Markdown) döngüsüyle yapısal olarak çakışır. Grimes Wyckoff'un volume-spread analysis tarafına daha az ağırlık verir; çünkü modern futures/equity verisinde volume sinyali eskisi kadar temiz değildir.

## Bizim Sistemle Bağlantı

Grimes'ın metodolojisi, otonom trading sistemimize neredeyse modüler olarak haritalanır:

**Market Phase modeli → `regime_classifier` modülü.** Grimes'ın 4-fazlı sınıflandırması (Trend / Pullback / Consolidation / Breakout), `regime_classifier`'ın çıkış sınıflarıyla doğrudan eşleşir. ADX, BB-width, ATR-based normalize edilmiş momentum, swing-structure (HH/HL veya LH/LL sayımı) gibi feature'lar, fazları niceliksel olarak ayırt etmemizi sağlar. Sistemimizde her bar için bir aktif faz tahmini üretilir; aşağı akış setup'ları sadece uygun fazda aktive olur.

**Setup kuralları → `setup_engine` taraması.** Grimes'ın 9 ana setup'ı (pin bar at S/R, failure test, MA pullback, anti, continuation, second pullback, range fade, volatility transition, gap classification) `setup_engine`'in başlangıç kütüphanesi olarak kodlanır. Her biri için: tetik koşulu (geometrik, ATR-normalize), bağlam filtresi (faz uyumu + confluence), stop/hedef formülü (ATR cinsinden), R-beklentisi tablosu.

**Confluence skoru → Grimes'ın "context everything" yaklaşımının kodlanması.** Sistemimizde her potansiyel sinyal, çoklu faktörlerden (S/R seviyesi, MA, trend yönü, time-of-day, volatility regime) bir confluence puanı alır. Grimes'ın tablolarındaki "1 confluence vs 3 confluence win-rate farkı" doğrudan bu puana ağırlık vermenin gerekçesidir. Eşik altı confluence'lı sinyaller filtrelenir.

**Statistical edge testlerimiz → Monte Carlo + walk-forward yaklaşımıyla uyumlu.** Backtest motorumuzda her setup için: in-sample optimizasyon, out-of-sample validation, Monte Carlo permutation testi (drawdown distribution), walk-forward analysis. Grimes'ın blog'unda anlattığı "her sayıyı kendi verinizle yeniden üretin" disiplini, sistemimizin değerlendirme protokolünün temelidir. Setup ancak bu testleri geçtikten sonra canlıya alınır.

**Risk yönetimi → fractional Kelly + ATR-normalize sizing.** Grimes'ın "fractional Kelly veya sabit-fraksiyon" tavsiyesi, position sizing modülümüzde 1/4 Kelly (cap'li) olarak uygulanır. Stop'lar ATR cinsinden, hedefler R cinsinden. Korelasyon-aware exposure cap'i (aynı yönde, aynı sektörde maksimum risk yüzdesi) Grimes'ın "correlation-aware sizing" prensibini kodlar.

**Drawdown / regime alarmı → Monte Carlo dağılımı dışında uyarı.** Sistem canlı çalışırken, gerçek drawdown'u her gün Monte Carlo backtest dağılımındaki yerine göre değerlendirir. %95 percentil dışına çıkıldığında otomatik **risk-off** moduna geçer (pozisyon boyutu yarıya); %99 percentil dışında trading'i tamamen durdurur. Bu, Grimes'ın "drawdown önceden planla" prensibinin operasyonelleştirilmesidir.

**Journaling otomasyonu.** Grimes'ın günlük şablonu, sistem-üretimli journal kayıtlarına haritalanır: her trade için kontekst (faz, confluence, setup), beklenen R, çıkış sonucu, sapmalar (stop kayması, slippage), retrospektif analiz alanı. Haftalık review, setup-bazlı performans dashboard'una otomatik beslenir.

**"Edge ispatı" iş akışı.** Yeni bir setup kütüphaneye eklenmek istendiğinde, Grimes-tarzı checklist: (1) operasyonel kural önceden yazılmış; (2) en az 200 işlem örneklemi; (3) Monte Carlo permutation testi; (4) farklı sembol setlerinde robustness; (5) farklı volatilite rejimlerinde stabilite; (6) işlem maliyetleri sonrası net pozitif EV; (7) risk-of-ruin %0.5 altında. Bu kapı eşiklerinden geçmeyen setup, canlıya çıkmaz.

**"Sanat" tarafının disiplinli alanı.** Sistem büyük ölçüde mekaniktir, ancak Grimes'ın savunduğu sezgisel-yetkinlik için bir "manual override" katmanı bırakılabilir: kararı ölçen ve kayda geçiren, ancak override edildiğinde sonraki review'da o kararın istatistiğini hesaplayan bir log. Bu, ne saf siyah-kutu ne de saf diskresyoner olmamayı, Grimes'ın art-and-science sentezini yaşatmayı sağlar.

**Sonuç.** Grimes'ın metodolojisi, otonom trading sistemimizin felsefi omurgasıdır. Brooks bize bar-bar okuma sezgisini, Volman intraday hassasiyetini, Wyckoff supply-demand bağlamını, Lopez de Prado kuantitatif sıkılığı verir; ama Grimes bu farklı katmanları birbirine bağlayan **istatistiksel disiplin + price action sezgisi** çerçevesini sunar. Sistemimizin neye "edge" diyeceği, neyi rejim olarak izleyeceği, riski nasıl ölçeceği ve kuralları ne zaman değiştireceği konusundaki tüm doktrin, doğrudan veya dolaylı olarak Grimes'ın "art and science" çerçevesinden türetilmiştir.
