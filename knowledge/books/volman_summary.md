---
source_id: volman_summary
source_type: book
author: Bob Volman
title: Forex Price Action Scalping (notes)
type: reference_only
quality: 5
ingested_date: 2026-05-08
topic_tags: [classic_pa, intraday, setup_taxonomy, breakout, range_break]
---

# Volman — Forex Price Action Scalping (özet notlar)

*Bu doküman Bob Volman'ın "Forex Price Action Scalping" (2011) ve "Understanding Price Action" (2014) kitaplarına ait kavramsal özet ve eğitim amaçlı notlardır; orijinal metin telif hakkı sahibine aittir.*

## Yazarın Çerçevesi

Bob Volman, çağdaş price action literatürü içinde Al Brooks'tan ayrışan bir intraday ekol kurmuştur. Brooks 5-dakikalık bar grafiğinde "her bar bir hikaye" yaklaşımıyla saatlerce data tarayıp swing oluşumu beklerken, Volman zamanı değil **işlem yoğunluğunu** ölçer: **70-tick chart**. Yani grafik her 70 trade'de bir yeni bar üretir; piyasa yavaşken 5 dakika bir bar, London open'da 8 saniye bir bar oluşabilir. Bu mekaniğin felsefi çıktısı şudur: bar sayısı sabit etkinliğe normalize edilir, "sessiz saatlerin" şişirdiği yatay zaman bar'ları otomatik olarak süzülür ve grafik **likidite ekonomisinin gerçek nabzını** verir.

Volman'ın pedagojisinin temel sloganı **"small bars on a small chart"**: küçük tick birimi + dar pip aralıklı setup'lar + sıkı stop. Hedeflediği piyasa neredeyse yalnızca **EUR/USD** ve ikincil olarak GBP/USD; çünkü 70-tick'in matematiksel anlam kazanması için tick frekansı yeterince yüksek, spread yeterince dar olmalıdır. Egzotik ya da düşük likiditeli pariteler bu çerçeveye dahil edilmez.

Volman'ın grafik dünyasının ikinci temel taşı **round numbers**'tır. **00 ve 50 seviyeleri** (örn. 1.3000, 1.3050, 1.2950) kurumsal limit emirlerin, opsiyon strike'larının ve dealing desk'lerin "dürüstçe sevmediği" **manyetik mıknatıslar** olarak işaretlenir. Volman, "büyük katılımcılar yuvarlak rakamların altına/üstüne emir yerleştirmez, **yuvarlak rakamların öteki tarafına oluşturulmuş stop havuzlarını avlar**" tezini savunur; bu nedenle tipik intraday hareket yapısı: yaklaşma → temas → stop hunting (false break) → reversal şeklinde özetlenebilir. Round number filtresi setup'ların hem tetiği hem de retçidir: bir kırılım round number'a çok yakınsa Volman çoğu zaman *almaz* çünkü hedef alanı kısalmıştır ve mıknatıs ters çekiş yaratabilir.

Üçüncü kavramsal taş: **dealing-desk pattern leakage**. Volman, retail platformlardaki "tezgah arkası" katmanın (market makers, liquidity providers) sürekli olarak **tahmin edilebilir defansif örüntüler** ürettiğini söyler — tipik stop-hunt fitilleri, küçük likidite vakum sıçramaları, news event'lerinde ani dealer yayılması. Bu örüntüler chart üzerinde tekrarlayan **küçük structural fingerprint**'lere dönüşür: pin'lerin bittiği tipik mesafeler, 5–7 bar konsolidasyon süreleri, 10-pip "çat çıkış / iki pip uzatma" profili gibi. Volman'ın setup taksonomisi büyük ölçüde bu mikro davranışların kataloglanmasıdır.

EUR/USD intraday yapısı Volman'ın işletim sistemidir: **Asya range** dar/yatay, London open'da (07:00–09:00 UK) ilk gerçek **First Break**, London-NY çakışmasında (12:30–15:00 UK) en yüksek volatilite, NY öğle saatlerinde "lunch lull" ve sonra NY close'a doğru zayıflayan trend. Bu zaman haritası setup uygulanabilirlik penceresini doğrudan belirler.

## Bar Anatomisi ve Tanımlar

Volman'ın bar tanımları Brooks'unkinden daha **operasyonel** ve daha az hermenötiktir; her tanım giriş tetiğine bağlanmıştır.

- **Pin bar (Volman tanımı):** Gövde, bar yüksekliğinin yaklaşık **üçte birinden küçük**; uzun fitil bir tarafta, kısa veya yok diğer tarafta; kapanış fitilin kök tarafında. Brooks "tail/wick" terimini gevşek kullanırken Volman pin'i sadece **reaction bar** olarak görür — yani fiyat gitmeye çalıştı, geri itildi. Pin tek başına setup değildir; ancak round number, EMA temas, range sınırı gibi bir bağlamla **birlikte** tetik olur.

- **Wickless bar (full-body bar):** İki ucundan biri (veya ikisi) neredeyse fitilsiz, sağlam yön kararlılığı gösteren bar. Volman bu barı **momentum imzası** olarak okur; özellikle bir konsolidasyondan ilk wickless bar çıkışı **First Break** sinyali değerini taşır.

- **Inside bar (IB):** Önceki bar'ın yüksek-düşük aralığında **tam kapsanmış** bar. Volman için inside bar tek başına çok zayıftır; ardışık **iki–üç inside bar** anlam kazanır çünkü "denge / sıkışma / pre-break compression" üretir. Dört+ inside bar serisi genellikle **fakeout**'a yol açar (TB veya MTT setup'ları).

- **Doji ve double doji:** Volman'ın doji tanımı sade — açılış ile kapanış neredeyse aynı (gövde, total range'in **% 10–15'inden küçük**). **Double Doji (DD)**: Birbirini takip eden iki doji ya da pin benzeri kararsızlık bar'ı; Volman'ın klasik DD imzası, **iki doji'nin aralığının dar olması** (toplam yaklaşık **5–8 pip range**) ve trend ya da round number civarında oluşmasıdır.

- **Signal bar quality grading:** Volman, bir "signal bar"'ın işe yaraması için şu kriterleri sayar:
  1. **Range** — minimum yaklaşık **3–4 pip** (70-tick EUR/USD); 1–2 pip bar gürültüdür, atlanır.
  2. **Body location** — kapanış, bar'ın yön taraflı **% 60+** kısmında olmalı.
  3. **Context fit** — EMA, round number, trendline veya block kenarına **temas etmiş** olmalı. Bağlamsız signal bar = noise.
  4. **Predecessor structure** — signal bar tek başına okunmaz; öncesindeki 5–10 bar ne anlatıyor? Çekişme, trap, yön belirsizliği varsa skor düşer.

- **Trader's signal vs noise:** Volman'ın merkezi epistemolojik konsepti. Bar'ın "ne dediği" değil, **piyasanın o bar'a verdiği reaksiyon** önemlidir. Pin oluştu ama bir sonraki bar onu yutarsa (engulfing) sinyal anında **invalidate**'tir. Aynı şekilde DD oluştu, kırılım barı tepki bulamadıysa setup geçersizdir.

## Setup Kataloğu

Aşağıdaki yapı her setup için: **Tanım / Bağlam / Giriş / Stop / Hedef / Edge / Failure** şeklinde verilmiştir. Tüm rakamlar EUR/USD 70-tick referans baseline'ıdır.

### DD — Double Doji Break

- **Tanım:** Birbirini izleyen iki doji veya çok dar gövdeli kararsızlık bar'ı; iki bar'ın **toplam aralığı yaklaşık 5–8 pip**.
- **Bağlam:** Genellikle bir mini konsolidasyonun ya da round number temasının ardından; 25-EMA yakınında ya da hafif eğimli bir trend içinde.
- **Giriş:** Çift doji'nin **yüksek + 1 pip** üzerinden long, **düşük – 1 pip** altından short. "Pip extra" Volman'ın yumuşak fakeout filtresidir.
- **Stop:** Setup yapısının **karşı kenarına +1–2 pip**; tipik 7–10 pip.
- **Hedef:** Standart **20 pip / 2R** ya da bir sonraki round number/structure noktası.
- **Edge:** Volatilite sıkışmasından çıkış, kompresif enerji + trend ile aynı yönde. Volman'ın imza setup'ı.
- **Failure:** Kırılımın hemen ardından gelen **2 bar içinde reversal** ⇒ FBR (False Break Reversal) tetikleyici olabilir.

### BB — Block Break (küçük konsolidasyon kırılımı)

- **Tanım:** **5–10 bar** süren dar yatay konsolidasyon "block"; içinde 2–3 dokunuşla onaylı destek/direnç var.
- **Bağlam:** Block, ya bir trendin pullback'i ya da bir reversal noktasının üzerine inşa edilmiş olmalı.
- **Giriş:** Block'un üstüne/altına **+1 pip** ile breakout pending order veya manuel close-confirmation.
- **Stop:** Block'un karşı kenarı **+2 pip**; tipik 8–12 pip.
- **Hedef:** Block'un dikey yüksekliğinin **2x–3x'i**, ya da next round number.
- **Edge:** Sıkışma sonrası direksiyon kararının enerjik olması; spread maliyetinin küçük kalması.
- **Failure:** Kırılım bar'ı round number'ın yanlış tarafında biterse veya volume/momentum desteklemezse — özellikle "tek pip uzayıp geri dönen" bar.

### PR — Trend Pullback Reversal

- **Tanım:** Yerleşik trend (25-EMA eğimi belirgin) içinde, fiyatın 25-EMA'ya **temas edip yön kararlılığını yeniden göstermesi**.
- **Bağlam:** EMA mesafesi tolerance'ı: pullback EMA'ya **0–3 pip** mesafede olmalı, EMA'nın çok ötesine sapmış pullback "fail trend" işaretidir.
- **Giriş:** Pullback'in **son barı yön kararlılığı gösteriyor** (pin, wickless, signal bar) ⇒ bar'ın sınırına **+1 pip** ile giriş.
- **Stop:** Signal bar'ın karşı kenarı veya EMA'nın 2–3 pip ötesi; tipik 10 pip.
- **Hedef:** Önceki swing high/low veya **20 pip / 2R**.
- **Edge:** En yüksek win-rate'li Volman setup'larından biri, çünkü trend + EMA mean-reversion + signal bar üçlü teyit sağlar.
- **Failure:** Pullback derinleşip **EMA'yı 5+ pip aşarsa** ya da signal bar'ın hemen ardı yutulursa.

### RB — Range Break

- **Tanım:** **15–30+ bar** yatay aralık; üstü/altı her iki yönde test edilmiş, kompresyon belirgin.
- **Bağlam:** Asya range, lunch range, post-news range gibi **zaman pencereli range**'ler. Volman, range break'in yönünü çoğu zaman önceki günün bias'ı ya da aktif seansın momentum'u tahmin eder.
- **Giriş:** Range kenarının **+1 pip** ötesi; ideali bir momentum bar'ın range kenarını net geçmesi.
- **Stop:** Range içine **5–8 pip** geri; tipik 10–12 pip.
- **Hedef:** Range yüksekliğinin **1x–1.5x'i**, ya da bir sonraki yapısal düğüm.
- **Edge:** Hesaplanabilir stop havuzları, kurumsal pozisyonlanmanın range kırılımına eşlik etmesi.
- **Failure:** **Round number'ın range kenarına 5 pip içinde** olması — büyük olasılıkla false break. Ayrıca news event range break'leri gerçek değil "spike" yapar.

### FB — First Break

- **Tanım:** Günün ya da seansın **ilk anlamlı yön kararı**; tipik olarak Asya range'inin London open'la kırılması.
- **Bağlam:** **07:00–09:00 UK** penceresi en sık FB zamanıdır; Asya range yapısı net olmalı (3+ test).
- **Giriş:** Asya range kenarının **+1–2 pip** dışı; ya da ilk wickless momentum bar'ın kapanışına manuel.
- **Stop:** Range içine 8–10 pip; tipik 10 pip.
- **Hedef:** Önce **20 pip / 2R**, sonra trail.
- **Edge:** İlk gerçek yön çoğu seansta tüm günün karakterini belirler. Volman bu setup'ı "günün soft kontratı" olarak okur.
- **Failure:** Round number tıkacı, news leakage, ya da ilk break'in 5 bar içinde geri yutulması (sonrası SB veya FBR).

### SB — Second Break

- **Tanım:** First break başarısız olduktan sonra **karşı yöne ya da aynı yöne ikinci deneme**. Fiyat range'e geri çekildi, sonra yeniden kırıyor.
- **Bağlam:** FB'nin "yorgun" olduğu anlar; iki kez denenmiş yön ikincide genelde stop havuzunu temizleyerek gerçek yön olur.
- **Giriş:** İkinci kırılım bar'ının yüksek/düşüğü **+1 pip**.
- **Stop:** Range içine 8–10 pip.
- **Hedef:** 20 pip / 2R; ya da FB'nin ulaşamadığı projeksiyon.
- **Edge:** SB'ler genellikle FB'lerden **daha temiz follow-through** sağlar, çünkü fakeout taraftarları zaten temizlenmiştir.
- **Failure:** Üçüncü break denemesi neredeyse her zaman düşük kalitelidir ⇒ Volman 3+ break setup'larını **almaz**.

### Round Number Probe / Reversal

- **Tanım:** Fiyat round number'a (00/50) yaklaşır, **3–7 bar** içinde temas edip ya kırar ya geri çekilir.
- **Bağlam:** Setup tek başına değil; bir trend reversal'ı veya range kenarı ile çakıştığında alınır. **Probe**: round'a yaklaşıp geri itilen pin/doji + reversal. **Reversal**: round'a temas + 2 bar geri tepki.
- **Giriş:** Reaction bar'ın round'a karşı yönde sınırı **+1 pip**.
- **Stop:** Round'un öteki tarafına **3–5 pip** (round'a yakın stop = stop hunt yemi).
- **Hedef:** **15–20 pip**, çoğu zaman bir önceki structure düğümüne kadar.
- **Edge:** Volman'ın "dealing desk avı" tezinin doğrudan uygulaması; defter taşıma asimetrisi.
- **Failure:** Round'un **kararlı kapanışla geçilmesi** (3+ bar üstte/altta kapanış) ⇒ probe iptal, breakout devamı.

### Pattern Block / Block Trend

- **Tanım:** Trend devamı için bir **mini block** (3–6 bar dar yatay duraksama) içinden çıkış. "Pattern block" Brooks'un "ABC pullback"'inin Volman karşılığıdır ama daha sıkı kompresyon talep eder.
- **Bağlam:** Trend açıkça yerleşmiş (25-EMA eğimli, en az 2 önceki swing onayı); block trend yönünde olmalı.
- **Giriş:** Block kenarı **+1 pip**.
- **Stop:** Block içi 6–8 pip.
- **Hedef:** Block yüksekliğinin 2x'i ya da 20 pip.
- **Edge:** Trend continuation + sıkışma + kısa stop; en iyi R-yapısı.
- **Failure:** Block içinde 7+ bar geçirildiyse momentum sönmüştür; setup'ı geç alma.

### FBR — False Break Reversal

- **Tanım:** Anahtar yapı (range, block, round number, prior swing) **kırılır** ama **2–4 bar içinde geri içeri** alınır; tetik bar yapı kenarına dönüş.
- **Bağlam:** En kuvvetli FBR'ler **round number üzerinde** veya **prior swing high/low** seviyesinde gerçekleşir.
- **Giriş:** Yapı kenarına geri dönüş bar'ının **karşı tarafında +1 pip**; yani long FBR için fiyat aşağı kırdı, geri çıktı, çıkış bar'ının üstü +1 pip.
- **Stop:** Sahte break'in en uç noktasının **2–3 pip** ötesi.
- **Hedef:** Yapının **karşı kenarı** (range içi traverse) veya 20 pip.
- **Edge:** Stop hunt sonrası gerçek yön; yüksek win-rate, çoğu zaman 2R+.
- **Failure:** Sahte break'in geri alımı **çok hızlı (1 bar)** ya da **çok yavaş (5+ bar)** ⇒ setup zayıf.

### MTT — Mid-trend Trap

- **Tanım:** Trend ortasında oluşan **sahte counter-trend signal**; trader'ları yanlış yönde tuzaklayan kısa kompresyon.
- **Bağlam:** Trend hala sağlam (EMA eğimi korunuyor), ama **3–5 bar** counter-trend görünümü oluştu. MTT sonrası gelen trend continuation tipik olarak hızlı.
- **Giriş:** Trap'in çözüldüğü noktada — yani "tuzak bar"'ın ters tarafında trend yönünde signal bar.
- **Stop:** Trap'in karşı uç noktasının 2–3 pip ötesi; tipik 10 pip.
- **Hedef:** Önceki trend swing extreme + 5 pip, ya da 20 pip.
- **Edge:** Counter-trend trader'ların stop'ları besleme alanına dönüşür; Volman'ın "tuzaklanmış zayıf eller" tezi.
- **Failure:** Tuzağın 6+ bar sürmesi → gerçek reversal'a dönüşmüş olabilir.

### IBB — Inside Bar Break

- **Tanım:** **2–3 ardışık inside bar** sonrasında yapının kırılımı.
- **Bağlam:** Inside bar serisi bir mother bar'ın son momentum bar'ından sonra oluşmalı; serideki son inside bar'ın **range'i en küçük** olmalı (gerçek sıkışma).
- **Giriş:** Mother bar'ın yönlü kenarı **+1 pip**, ya da son inside bar'ın yönlü kenarı.
- **Stop:** Inside bar serisinin karşı kenarı; tipik 8–10 pip.
- **Hedef:** 20 pip veya structure projection.
- **Edge:** Volatilite sıkışmasının enerjik çözümü; düşük spread riski.
- **Failure:** 4+ inside bar = yorgun setup; ayrıca round number çok yakınsa kırılım yutulur.

### TB — Pre-Pattern Tease Break

- **Tanım:** Bir setup hazırlanırken (örn. block, range) **erken doğmamış kırılım**; kenarın 1–2 pip ötesine sızıp hemen geri dönen bar.
- **Bağlam:** Tease break **setup'ın iptali değil; tetiği**. Volman, "piyasa erken oyuncuları temizledi, artık gerçek yön mümkün" şeklinde yorumlar.
- **Giriş:** Tease break sonrası yapı **karşı yönde** kırılırsa giriş; yani üst kenar tease edilip iptal olduysa, alt kenar break long olarak değil **short FBR/RB** olarak işlenir.
- **Stop:** Tease'in en uç noktasının 2 pip ötesi; tipik 10 pip.
- **Hedef:** 20 pip; ya da yapının dikey 2x'i.
- **Edge:** Volman'ın FBR ile akraba ama daha hafif kuzeni; "head fake" örüntüsü.
- **Failure:** Tease break'in 3+ bar sürmesi setup'ı yorar; ya da tease ile gerçek break arasında 10+ bar gecikmesi olması.

## Bağlam ve Filtre Kuralları

Volman'ın en sıkı (ve çoğu retail trader'ın atladığı) bölüm budur. Setup tanımak teknik beceri, **uygulamamak** profesyonelliktir.

- **25-EMA pozisyonu:** Volman'ın baseline trend filtresi **25 periyot exponential moving average** (70-tick chart üzerinde). EMA eğimi:
  - Yatay (slope ≈ 0) ⇒ range piyasası ⇒ RB, FBR, round number setups çalışır; PR ve trend continuation **ZAYIF**.
  - Yukarı/aşağı eğimli ⇒ trend piyasası ⇒ PR, BB, pattern block, MTT öne çıkar.
- **Distance-from-EMA tolerance:** Pullback alırken signal bar EMA'ya **0–3 pip** içinde olmalı; **4–6 pip** mesafe sınırda; **7+ pip** counter-trend reaction olarak okunur, trend continuation alınmaz. Trend bar'ı EMA'dan **15+ pip** açıldıysa "ekstansiyon" sayılır ve yeni giriş alınmaz; pullback beklenir.
- **Time-of-day filtreleri:**
  - **00:00–06:00 UK** (Asya): Yalnızca dar range ve range break beklentisi; FB değil.
  - **07:00–09:00 UK** (London open): **FB / SB** ana penceresi; en yoğun volatilite.
  - **09:00–12:00 UK**: Trend continuation, PR, MTT.
  - **12:30–15:00 UK** (NY overlap): Yüksek volatilite ama yüksek false-break riski; özellikle **13:30 UK / 8:30 NY data release** civarı.
  - **15:00–17:00 UK**: NY momentum; trend continuation iyi.
  - **17:00 UK sonrası**: Likidite düşer; setup almama eğilimi.
- **News kara delik kuralı:** Volman'ın katı kuralı: **major news release'ten 15 dakika önce / 30 dakika sonra** **hiçbir setup alınmaz**. Bu pencere içinde oluşan break'ler "data spike" olup price action mantığı çalışmaz. Major'lar listesi: NFP, FOMC, ECB, BOE rate, CPI, GDP, retail sales.
- **Weekend gap behavior:** Pazar açılış gap'i ilk 2–3 saatte normalize olana kadar setup alınmaz. Volman Cuma NY close'a çok yakın setup almama tarafındadır (likidite çekiliyor).
- **Spread filtresi:** EUR/USD spread > **1.5 pip** olduğu anlarda Volman setup almamayı önerir; çünkü 10 pip stop / 20 pip target matematiği bozulur.

## Risk Yönetimi

Volman'ın risk çerçevesi disiplin yoğun ve mekaniktir.

- **Standart yapı: 10-pip stop / 20-pip target.** Bu, **fixed 1:2 R-multiple**'dır. Volman'ın setup taksonomisi bu sabit yapı etrafında inşa edilmiştir. Her setup'ın stop'u 8–12 pip aralığında, target'ı 18–22 pip aralığında değişir. Bu sabitlik, setup başarısının istatistiksel hesabını sadeleştirir.
- **R-multiple consistency:** Her trade tek R birimi risk eder. Volman, dollar veya percent yerine **pip cinsinden risk** anlatır; bu retail trader için pratik mental modeldir. R = 10 pip; aylık P&L = (kazanan trade × 2R) – (kaybeden trade × 1R) – komisyon-spread.
- **Scaling out vs all-in:** Volman'ın tercihi **all-in / all-out**'tur. Yani 20 pip target'ta tüm pozisyon kapanır; trail stop, partial close gibi karmaşıklıklar 70-tick scalping mantığına uygun değildir çünkü bar süresi çok kısa olduğundan trail mekanik gürültü üretir. Bazı bölümlerde **15-pip partial + 25-pip runner** alternatifi sunar ama default değildir.
- **Max 2 simultaneous trades kuralı:** Volman aynı anda en fazla **2 açık pozisyon** önerir; üçüncü setup ne kadar iyi görünürse görünsün atlanır. Sebep: 70-tick chart'ta 3+ trade aynı anda yönetilebilir bilişsel yükün üstündedir.
- **Drawdown discipline:** Üst üste **3 stop-out** olursa Volman o gün için **işlemi keser** (daily stop). Ayda **8 trade kayıp serisi** olursa metodu (kişisel uygulamasını) gözden geçirme zamanı gelmiştir; method değil, uygulayıcı bozulmuş olabilir.
- **Position sizing:** Default %0.5–%1 hesap riski / trade. Volman, setup beklenen win-rate'ine göre size'ı oynatma fikrine **karşıdır**; sabit size + sabit R disiplinin temelidir.

## Statistical / Quantifiable Edge Conditions

Volman, kitabın çeşitli bölümlerinde *yaklaşık* (signed-off değil, eğitsel) edge sayıları verir. Aşağıdaki rakamlar Volman'ın anlatımından çıkarılmış **estimate ranges**'dir; gerçek piyasa şartlarına ve uygulayıcıya göre oynar.

- **Genel edge baseline:** Volman'ın setup'larının **win-rate ≈ % 50–55**, **avg payoff 1.7–1.9R** (1:2 nominal target ama trail / kısmi exit ile reel payoff biraz düşer). Net pozitif beklenti per trade ≈ **+0.3R – +0.5R**.
- **Setup başına yaklaşık beklentiler:**
  - **DD (Double Doji)**: ~%55 win-rate, ~1.8R avg, **en yüksek frekans** (haftada 8–12 sinyal).
  - **PR (Pullback Reversal)**: ~%55–60 win-rate, ~1.7R avg, frekans haftada 5–8.
  - **BB / Block Break**: ~%50 win-rate, ~2.0R avg (target'a daha sık tam ulaşır), haftada 3–5.
  - **RB (Range Break)**: ~%45–50 win-rate (false break riski), ~1.9R avg, haftada 2–4.
  - **FB (First Break)**: ~%50–55 win-rate, ~2.0R avg, **günde 1–2 fırsat** (en kıt).
  - **SB (Second Break)**: ~%55–60 win-rate, ~1.8R avg, haftada 2–3.
  - **FBR (False Break Reversal)**: ~%55–60 win-rate, ~2.0R+ avg, haftada 3–5.
  - **Round Number Probe**: ~%55 win-rate, ~1.7R avg, günde 1–3 fırsat (round number sayısına bağlı).
  - **MTT (Mid-trend Trap)**: ~%60+ win-rate (trap teyit edilince güçlüdür), ~1.8R avg, haftada 1–3.
  - **IBB (Inside Bar Break)**: ~%50 win-rate, ~1.7R avg.
  - **TB (Tease Break)**: ~%55 win-rate, ~1.8R avg.
- **Monthly trade count expectation:** Volman, full-time disiplinli bir uygulayıcının ayda **40–80 trade** alabileceğini söyler; bunun yarısından fazlası DD ve PR'dır. Daha fazla trade = filtreyi gevşetiyorsun demektir.
- **70-tick chart için özel rakamlar:**
  - Tipik bar range: **2–6 pip**; signal bar minimum range **3 pip**.
  - Bar oluşum süresi: London açılışta 5–15 saniye, sessiz saatte 2–5 dakika.
  - Setup'ın "olgunlaşma" penceresi: 10–20 bar süresinde belirir; daha uzunsa konsept zayıflar.
  - 25-EMA pullback derinliği typical: **3–6 pip** EMA-mesafe.
  - Round number proximity zone: **0–8 pip** mesafe içinde "magnet" etkisi belirgin.
- **Beklenti matematiği (örnek):** %55 win, 1.8R avg, 60 trade/ay ⇒ E = 0.55*1.8 – 0.45*1.0 = +0.54R/trade × 60 = **+32R/ay**. R = %0.5 hesap olursa **%16/ay** brüt; spread + komisyon sonrası realistik %8–10/ay. Volman, bu tür sayıları bir hedef değil **ulaşılabilir edge tavanı** olarak sunar.

## Yaygın Hatalar / Pitfalls

- **Counter-trend trap:** Trend bariz biçimde sürerken FBR veya round number reversal kovalamak. Volman'ın kuralı: "Counter-trend setup ancak EMA eğimi yatay veya kararsızsa alınır."
- **Premature entry:** Signal bar daha kapanmadan, "fitil yeterince uzadı" varsayımıyla erken giriş. 70-tick'te bir bar 30 saniyeyi bile bulmaz; **bar kapanışını beklemek** kuraldır.
- **News ignorance:** Major data release'in **15 dakikalık** kara delik kuralını ihlal etmek. Volman bu hatayı en pahalı tek hata olarak gösterir; bir spike tüm haftanın edge'ini siler.
- **Position size escalation in losing series:** "Bu sefer kesin" diyerek size'ı 2x–3x büyütmek (tilt-driven martingale). Volman'ın disiplini: kayıp serisinde size'ı **azaltmaya** veya en azından **sabit tutmaya** zorlar.
- **Setup count maximization:** Disiplinli trader'ı yorgun trader yapan "her doji DD, her pullback PR" semantik gevşemesi. Volman'ın testi: setup'ı bir başkasına 30 saniyede **objektif** olarak anlatabiliyor musun?
- **Round number disrespect:** Target round number'ın hemen ötesine yerleştirip "stop hunt" yemi olmak; ya da round number üstündeki bir setup'ı "biraz daha gitmesini" beklemek.
- **EMA-distance overreach:** EMA'dan 8+ pip uzakta signal bar'a "iyi pin" diye girmek; bu artık counter-trend retracement, trend pullback değil.
- **Recovery trade:** Stop-out sonrası **hemen yeni setup** aramak; emotional re-entry. Volman: stop-out sonrası **en az 2 setup atlanır** (cooling).
- **Three-break overconfidence:** FB başarısız, SB başarısız, "üçüncü kesin" diye TB ya da yeni RB almak. Volman: 3+ break almama kuralı.

## Cross-references

- **Brooks vs Volman setup taksonomisi:**
  - Brooks **5-min** chart, Volman **70-tick**; Brooks tüm bar'ları 1–5 sözcükle anlatır, Volman bar'ı yapı içinde kataloglar.
  - Brooks'un **"Major trend reversal"** ve **"two-legged pullback"** kavramları Volman'ın **PR + MTT** kombinasyonuna karşılık gelir.
  - Brooks'un **"ii / iii"** (inside-inside) Volman'ın **IBB** ile aynı şeydir, isim farkı.
  - Brooks **"failed breakout"** = Volman **FBR**; Brooks daha gevşek, Volman pip-tabanlı sınır koyar.
  - Brooks'ta **R hedefi serbest** (1R, 2R, scale-out); Volman **sabit 1:2** ve all-in/all-out tercih eder.
  - Brooks "scalping" terimini de kullanır ama anlamı **5-min'de 4 puan/ES kontratı**; Volman **forex'te 20 pip**. Konsept aynı: kısa, yüksek frekans, high-discipline.
- **Neden Volman intraday'e Brooks swing'e döner:** Brooks'un metodolojisi 60+ bar'lık structure okumayı gerektirir; bu daily/4H/1H çok rahat çalışır. Volman'ın 70-tick ölçeği 1–4 saatlik bir oturumda 200+ bar üretir; saatler değil **saniyeler** üzerinden setup gelir. İki ekol birbirinin **zaman ölçeği transpozisyonu** gibidir, ama Volman dealer-mikro yapısı + round number'a Brooks'tan **çok daha** ağırlık verir.
- **Wyckoff supply/demand örtüşmeleri:** Volman'ın **range break** mantığı Wyckoff'un **trading range → spring → markup** sekansının intraday minyatürüdür. **FBR**, Wyckoff'un **"upthrust after distribution"** (ya da spring) kavramının pip-leveldeki karşılığıdır. **Round number probe / reversal**, Wyckoff'un "preliminary support / supply" konseptiyle benzerdir — kurumsal aktivitenin yapı kenarında imza bırakması. Volman'ın tezi Wyckoff'un mikro-zaman uygulamasıdır: composite operator artık dealer / liquidity provider olarak yeniden adlandırılmıştır.
- **Diğer ekoller:** Linda Raschke'nin **"Holy Grail"** (20-EMA pullback in trend) Volman PR'ın daha gevşek bir varyantıdır. Steve Nison'ın candlestick taksonomisi Volman bar tanımlarının atasıdır ama Volman context-bound, Nison stand-alone okur.

## Bizim Sistemle Bağlantı

Bizim core sistem **1D / 1W swing** odaklı; Volman 70-tick mikro intraday. Doğrudan setup kopyalama mümkün değil. Ama **konseptlerin scale-up'ı** çok değerli:

**1D'ye doğrudan taşınabilenler:**

- **Round numbers as institutional magnets:** Bizim sistemde de **major round levels** (BTC 100k, EURUSD 1.10, S&P 5000) aynı manyetik etkiyi gösterir, sadece zaman ölçeği farklı. Volman'ın "0–8 pip magnet zone" kuralının 1D karşılığı: **0–%1 round level proximity zone**. Pozisyon planlamasında round level'a **çok yakın target** koymama, **çok yakın stop** koymama disiplini birebir taşınabilir.
- **FBR / False Break Reversal logic:** 1D'de prior swing high/low'un kırılıp **2–4 gün içinde geri alınması** = klasik bull/bear trap. Bizim için **kuvvetli reversal sinyali**; Volman'ın FBR kataloğu bu örüntünün mikro-ispatıdır, 1D'ye uygulanabilir.
- **Range Break / Compression Break logic:** 1D **konsolidasyon + kırılım** mantığı (haftalık range, monthly range) Volman'ın RB'sinin doğal genişlemesidir. Aynı kurallar: range yüksekliği × 1–1.5 hedef projeksiyonu, range içine pip stop yerine **% stop** mantığı.
- **First / Second Break logic:** 1D zamanda **haftanın ilk break'i** (Pazartesi/Salı), **ayın ilk break'i** kavramı kurumsal pozisyon değişimi açısından geçerlidir. SB'nin FB'den daha güvenilir olduğu istatistiği daily timeframe'de de kabaca tutar.
- **News kara delik:** 1D'de NFP / FOMC günlerinde swing pozisyon **açma**ma ya da **size'ı yarıya indirme** kuralı, Volman'ın 15-dakika penceresinin günlük ölçek karşılığıdır.
- **Inside bar serisi (IBB) → daily inside day cluster:** 1D'de 2–3 inside day kompresyonu ardından gelen breakout bizim sistemde **NR4/NR7** ve "coiled spring" konseptiyle birleşir; Volman'ın IBB tetik mantığı (mother bar yönlü kenar +1 tick) aynen çalışır, sadece "+1 pip" yerine "+0.1–0.3%" tolerance.
- **Distance-from-EMA tolerance:** Volman'ın "EMA'dan 8+ pip uzaksa pullback değil" kuralı, 1D'de **20-EMA / 50-EMA mesafe filtresi** olarak yeniden ifade edilir: pullback EMA'dan ATR'nin **% 100'ünden** uzaktaysa "trend yorgun" sinyali.

**Tick chart'a özgü kalıp 1D'ye taşınamayacaklar:**

- **Double Doji'nin pip-tabanlı kompresyon ölçüleri** (5–8 pip range threshold) 1D'de anlamsızdır; doji konsepti var ama Volman'ın aritmetiği değil.
- **70-tick bar oluşum mekaniği** ve **dealer-leakage micro-fingerprint**'ler tick / order-flow seviyesinde yaşar; daily bar bu mikro yapıyı ortadan kaldırır.
- **Sabit 10-pip / 20-pip stop-target geometrisi** swing trade'in volatilitesi ile bağdaşmaz; biz **ATR-tabanlı** ya da **structure-tabanlı** stop kullanırız.
- **Mid-trend Trap (MTT)** ve **Tease Break (TB)** **bar oluşum hızına** çok bağlıdır; daily bar'da bu kadar hızlı whipsaw yapısı seyrek çıkar; haftada en fazla 1–2 örnek.
- **Max 2 simultaneous trades** kuralı 70-tick bilişsel yüküne özgüdür; 1D swing portföyünde **5–10 simultaneous position** kabul edilebilir.
- **All-in / all-out exit** swing'de **sub-optimal**'dır; 1D'de tipik **partial exit + trail** daha üstün getiri/risk profili sunar.

**Sentez:** Volman'ı sistemimize katkısı **mekanik bir setup library** değil, **kavramsal kalibrasyon ve filtre disiplini**dir. Round number duyarlılığı, false-break sezgisi, news-window respect, EMA-distance disiplini ve "setup'ı objektif olarak anlatabilme" testi — bunlar 1D / 1W zaman ölçeğine **upgrade edilmiş hâlleriyle** sistemimizin filtre katmanına yedirilir. Volman'ın asıl mirası, **piyasanın stop havuzlarını avladığı**na dair operasyonel bir paranoyadır; bu paranoyayı doğru dozda taşımak, herhangi bir setup'ın win-rate'ini istatistiksel olarak iyileştirir.
