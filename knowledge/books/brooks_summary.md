---
source_id: brooks_summary
source_type: book
author: Al Brooks
title: Reading Price Charts Bar by Bar (notes)
type: reference_only
quality: 5
ingested_date: 2026-05-08
topic_tags: [classic_pa, pattern, structure, breakout, pullback, trend]
---

# Brooks — Reading Price Charts Bar by Bar (özet notlar)

Bu doküman Al Brooks'un "Reading Price Charts Bar by Bar" ve "Trading Price Action: Trends / Trading Ranges / Reversals" üçlemesinin metodolojik özetidir; eğitim amaçlı RAG referansıdır, telif materyalin yerini tutmaz, kitapların yerine geçmez.

## Yazarın Çerçevesi

Brooks'un temel iddiası şudur: her bar (mum) piyasada o anki alıcı-satıcı savaşının tam bir hikayesini anlatır; trader'ın görevi göstergeye değil, bu hikayeye bakmaktır. Brooks, indikatörleri (RSI, MACD, Stoch, MA crossover) prensip olarak reddetmez ama "lagging" olduklarını ve fiyatın kendisinden zaten türetildiğini söyler — yani indikatörden alınan sinyal, aynı bilgiyi bardan okumayı bilen trader için her zaman geç gelir. Birincil zaman dilimi 5 dakikalık bar (E-mini S&P futures için) veya işlem enstrümanına göre eşdeğer ölçektir; daha kısa zaman dilimleri "noise" olarak kabul edilir, daha uzunlar (60m, daily) bağlam (HTF context) için kullanılır.

Brooks'un en sık alıntılanan istatistiği: piyasalar zamanın yaklaşık %80'inde trading range (yatay), %20'sinde trend rejimindedir. Bu oran fix değildir — günlük bazda değişir — ama trader davranışını şekillendirir: default rejim "range"dir, bu nedenle default davranış "fade extremes" (uçları sat / al), trend kanıtlanana kadar trend takip etmek değildir. Trend rejimi başladığında ise tam tersi: pullback'lerde trend yönünde gir, range varsayımına dön, asla ters yöne dönme deneme.

Brooks, "Always In" (AI) konseptini özellikle vurgular: her an piyasa ya AI Long ya AI Short'tur — yani eğer trader o saniye pozisyon almak zorunda kalsa hangi yöne gireceğine dair net bir cevabı olmalıdır. AI yön belirsizse setup almaya değmez; bu durumda piyasa "two-way trading" rejimindedir ve sadece A-grade setup'lar alınır. AI flip (yönün değişmesi), Brooks için majör bir olaydır ve genellikle strong reversal bar + follow-through ile teyit edilir.

Institutional vs. retail bias: Brooks, fiyatın institutional (büyük) oyuncular tarafından sürüklendiğini, retail'in genellikle yanlış noktada (top'ta long, bottom'da short) işlem açtığını varsayar. Bu yüzden Brooks "obvious" görünen seviyelerdeki breakout'lara şüpheyle yaklaşır: round number'da ya da gün öncesi high'ta breakout olduğunda failure (trap) olasılığı yüksektir; başarısız breakout, sonraki büyük hareket için en güvenilir sinyallerden biridir (Brooks'un dilinde "failed breakouts are very reliable setups").

Bar-by-bar logic'in indikatörden üstün olmasının nedeni: indikatör, n-bar ortalamasını alır ve smoothing nedeniyle bilgi siler; bar-by-bar, her bar'ın açılış/kapanış/high/low ilişkisini, önceki bar ile overlap'ını, body/range oranını kullanarak tüm mikro yapıyı korur. Brooks'a göre yeterince bar okuyabilen trader, herhangi bir indikatöre ihtiyaç duymaz — fakat moving average (özellikle 20-EMA) zayıf bir trend filtresi ve dynamic support/resistance olarak izlenebilir.

## Bar Anatomisi ve Tanımlar

Brooks'un setup'ları bar tipi tanımlarına dayanır. Aşağıdaki eşikler kitapta açıkça verilen veya çıkarsanan değerlerdir.

**Trend Bar (Bull / Bear):** Body, bar range'in %50'sinden büyüktür ve trend yönünde kapanır. Strong trend bar = body, range'in %70'inden büyüktür ve close, bar high'ına (bull) ya da low'una (bear) yakın (close-to-extreme oranı, range'in %20'si içinde). Brooks, "strong close" terimini bu duruma kullanır: bull trend bar'da close, bar'ın üst %20'sinde olmalıdır.

**Doji:** Body, bar range'in %25'inden küçüktür (bazı pasajlarda %20-30 aralığı; çıkarsama: %25 default). Doji, "one-bar trading range"dir — alıcı ve satıcı dengededir. Doji clusters (üst üste 2+ doji) genellikle trading range işaretidir. Trend bar ile doji arasındaki ara form "weak trend bar" veya "small bar" olarak adlandırılır.

**Reversal Bar (Pin Bar / Hammer / Shooting Star):** Brooks "reversal bar" terimini tercih eder. Bull reversal bar: bar low, önceki bar low'unun altında (alttan likidite alır), close ise önceki bar high'ının veya en azından midpoint'inin üstünde, ve bar üst yarıda kapanır; alt kuyruk (lower tail) bar range'in %50'sinden büyüktür. Bear reversal bar simetriktir. Pin bar = upper/lower wick, body'nin en az 2 katı; bar range'in en az %66'sı tek tarafta wick. İdeal reversal bar: long tail + small body + close opposite end.

**Inside Bar (ii):** Bar high < önceki bar high VE bar low > önceki bar low. Tek inside bar = "ii" değil; "ii" iki ardışık inside bar formasyonudur (bar 2 ve bar 3, bar 1 içinde). "iii" = üç ardışık inside bar. Inside bar, momentum'un duraksaması demektir; tek başına yön sinyali vermez, breakout yönü önemlidir.

**Outside Bar:** Bar high > önceki bar high VE bar low < önceki bar low. Outside bar, hem alıcının hem satıcının test edildiği iki yönlü hareket içerir. Brooks, outside bar'ı genellikle confusion / two-way trading olarak yorumlar; outside bar'ın kapanış yönü (üst veya alt) "always-in" yönü için ipucu verir, ama tek başına setup değildir. Outside up bar (close near high) bullish; outside down bar (close near low) bearish.

**Breakout Bar:** Trading range'in veya önemli bir swing'in dışına strong trend bar ile çıkış. Genellikle range'in son n bar'ının (n=10-20) yapısının dışına 1+ ATR'lik kapanış. Breakout bar, body büyük, wick küçük, range >= 1.5x average bar range. "Climactic" breakout bar (2-3 ATR) ise genellikle exhaustion sinyali — yani başarısız olma olasılığı, devam etme olasılığından yüksektir; Brooks bunu "buying climax / selling climax" olarak tanımlar.

**ii setup:** İki ardışık inside bar (bar 2 ve bar 3, bar 1 içinde sıkışır). Trader, bar 3 high'ının 1 tick üstüne (long) veya low'unun 1 tick altına (short) buy/sell stop koyar. Stop, ii'nin ters tarafında (bar 3'ün diğer ucu) durur. ii, low-volatility breakout setup'ıdır, range çok dar olduğu için tight stop sağlar.

**iii setup:** Üç ardışık inside bar; ii'den daha güvenilirdir çünkü konsolidasyon daha sıkıdır. Aynı buy stop / sell stop mantığı uygulanır.

**Close-to-Open / High / Low Ratios (operasyonel eşikler):**
- Strong bull trend bar: close > open + 0.7 * (high - low) (yani close, range'in üst %30'unda).
- Weak trend bar: 0.3 < (close-low)/(high-low) < 0.7 — ne yön belirgindir.
- Doji: |close - open| < 0.25 * (high - low).
- Signal bar (trend yönünde): bull setup için close > open AND close, range'in üst yarısında; bear setup için tersi.
- Reversal bar quality: tail length / range > 0.5 ve close, opposite end'in %25 yakınında.

## Setup Kataloğu

Aşağıdaki her setup için 7 blok: Tanım / Bağlam / Giriş / Stop / Hedef / Edge / Failure mode.

### H1 (High 1) — Bull trend'de ilk pullback long

- **Tanım:** Yükseliş trendinde, fiyat birkaç bar (genellikle 2-4 bar) düşüş yaptıktan sonra bir bar high'ı yapar ve bir sonraki bar bu high'ı kırar. H1, trend yönündeki ilk pullback giriş noktasıdır.
- **Bağlam:** Net bullish trend (en az 2 higher high + higher low veya AI=Long). 20-EMA yukarı eğimli ve fiyat EMA üstünde veya EMA'ya geri çekilmiş. Trading range içinde H1 alınmaz — sadece trend rejiminde.
- **Giriş:** Setup bar'ı (pullback'in son bar'ı, genellikle bull reversal bar veya inside bar) high'ının 1 tick üstünde buy stop.
- **Stop:** Setup bar low'unun 1 tick altı (alternatif: önceki swing low + 1 tick).
- **Hedef:** En yakın HH (önceki swing high), ya da measured move; partial 1R'de, trail remainder.
- **Edge:** Brooks H1'i "trend boyunca tekrarlanabilir, en güvenilir long" olarak tanımlar. Strong trend'de H1 win rate ~60-70% (çıkarsama, Brooks "consistently profitable" diyor; rakam yaklaşıktır), R:R 2:1+.
- **Failure:** H1 bar'ının üstüne çıkıldıktan sonra dönüp setup low'un altına kapanış → failed H1; bu, sıklıkla L2 short setup'ına dönüşür (failure of H1 = setup for opposite side).

### H2 — Bull trend'de ikinci pullback long

- **Tanım:** H1 başarısız olduktan veya yetersiz devam ettikten sonra ikinci pullback. Pullback'te ikinci kez bar high kırılır.
- **Bağlam:** Trend hala intact (henüz major lower low yok). H2, H1'den daha güvenilirdir çünkü "two-legged pullback" genellikle ABC corrective pattern'i tamamlar.
- **Giriş:** İkinci pullback'in en son setup bar'ının high'ının üstünde buy stop.
- **Stop:** Setup bar low veya pullback low.
- **Hedef:** Önceki swing high'ı en az test, measured move (pullback A leg = pullback C leg projection).
- **Edge:** Brooks'a göre H2, H1'den daha yüksek win rate'e sahiptir (~65-75% strong trend'de, çıkarsama). Çift dip / two-legged pullback istatistik olarak en sık görülen retracement formudur.
- **Failure:** Setup bar low altında kapanış + lower low → trend kırıldı, possible reversal; H2 failure çoğu kez M2B (major reversal) sinyalidir.

### H3 — Bull trend'de üçüncü pullback long (üçüncü itme)

- **Tanım:** Aynı pullback yapısı içinde üçüncü low test (three-push). Genellikle wedge formu.
- **Bağlam:** H1 ve H2 zaten oluşmuş, trend hala alive. H3, "üçüncü ve son" pullback'tir; sonrasında ya breakout (yeni trend leg) ya da trend exhaustion gelir.
- **Giriş:** Üçüncü pullback'in setup bar high'ı üstü.
- **Stop:** Üçüncü pullback low altı.
- **Hedef:** Aynı, fakat hedef daha küçük olabilir çünkü trend olgunlaşmıştır; partial 1R, fast trail.
- **Edge:** H3, H1/H2'den daha düşük win rate (~50-60%, çıkarsama) ama failure'ı kuvvetli wedge top reversal sinyalidir; failed H3 = M2B kandidatı.
- **Failure:** Lower low → wedge bottom failure → genellikle güçlü reversal başlar.

### L1, L2, L3 — Aynı yapı, short tarafta

L1: Bear trend'de ilk pullback short. Pullback yukarı, son bar low kırılınca short stop.
- Giriş: Setup bar low altı 1 tick.
- Stop: Setup bar high üstü.
- Hedef: Önceki LL.
- Edge: Strong bear trend'de win rate L1 ~60-70% (çıkarsama).

L2: İkinci pullback (two-legged retracement), genellikle ABC up correction sonrası. Brooks'un "favorite" short setup'larından biri; en yüksek edge.
- Edge: ~65-75% (çıkarsama).

L3: Üçüncü itme, wedge top kandidatı. Failed L3, M2S (long reversal) sinyali.
- Edge: ~50-60%.

Genel kural: Strong trend'de **counter-trend setup almak yasaktır** — yani strong bear'de H setup almak Brooks'un en çok uyardığı hatadır. Sadece major reversal teyidi (M2B/M2S) sonrası karşı yön düşünülür.

### M2B (Major Trend Reversal Buy)

- **Tanım:** Bear trend bottom'da major reversal long setup. Genellikle: (1) climactic selloff (selling climax bar — 2+ ATR bear bar), (2) güçlü bull reversal bar (long lower tail + close üst yarıda), (3) follow-through bar (ikinci bull trend bar yön teyidi). M2B = "Major 2 Buy" — second signal in a reversal sequence.
- **Bağlam:** Aşağı trendin son 1-3 bar'ı climactic; major support seviyesi (önceki swing low, daily 200-EMA, round number); momentum divergence (alttan ilk leg ile son leg arasında).
- **Giriş:** Reversal bar'dan sonraki bull bar'ın high'ı üstünde buy stop (M2 = ikinci sinyal teyidi). Saf reversal bar'a değil, reversal + follow-through'ya girilir.
- **Stop:** Reversal bar low altında veya climactic bar low altında.
- **Hedef:** Bear trend boyunca yapılan son major pullback high'ı veya measured move; risk büyük olduğu için 2R+ hedef şart.
- **Edge:** Brooks'a göre major reversal setup'ları rare ama yüksek R:R'lı; win rate ~40-50% ama R:R 3:1+ olduğu için EV pozitif. Reversal bar quality (long tail) ne kadar yüksekse win rate o kadar yüksek.
- **Failure:** Reversal bar low'unun kırılması → reversal başarısız → trend devam, often hard selloff. Failed M2B çoğu kez büyük continuation breakout'tur.

### M2S (Major Trend Reversal Sell)

- M2B'nin simetriği. Bull trend top'ta selling climax (2+ ATR bull bar), bear reversal bar (upper tail + low close), follow-through bear bar. Aynı kurallar.
- Edge: Brooks bull market top'ta M2S'in dikkatli alınması gerektiğini söyler — bull markets exhibit "scratching out tops" (yavaş, multi-test top'lar), bear markets ise "V-bottoms" yapar; bu yüzden M2S genellikle çok denemeden sonra çalışır, ilk M2S'ler sıkça başarısız olur.

### FF (Final Flag)

- **Tanım:** Strong trend'in son bayrağı (consolidation). Trend birkaç leg yapmış, son flag formasyonundan sonra son bir push gelir, ardından flag failure veya breakout failure majör reversal başlatır.
- **Bağlam:** Trend olgunluğu (en az 3-4 leg, wedge / channel terminal, exhaustion bar). Final flag genellikle daha küçük, daha sıkı ve daha kısa süreli olur (önceki flag'lere göre).
- **Giriş:** İki yol: (a) Final flag'in trend yönündeki breakout'u → küçük continuation trade (1R'de partial); (b) Final flag breakout'unun failure'ı (en güvenilir) → ters yöne reversal entry.
- **Stop:** Flag'in dış tarafı.
- **Hedef:** (a) measured move (küçük); (b) trend'in başlangıcına kadar — yani büyük R:R.
- **Edge:** Brooks "Final Flag failure"u en güvenilir reversal trigger'larından biri olarak tanımlar; başarılı tespit edildiğinde 5-10R hareket potansiyeli vardır. Win rate orta (~50%) ama R çok büyük.
- **Failure:** Final flag, sadece "looks final" olabilir; gerçekte trend devam edebilir. Bu yüzden FF reversal trade'i her zaman yapısal teyit (lower low / higher high reversal) ile alınır, predictive değildir.

### BO PB (Breakout Pullback)

- **Tanım:** Trading range veya consolidation breakout sonrası, breakout yönünde ilk pullback. Pullback çoğu zaman breakout level'a (eski direnç → yeni destek) test ederek gelir, ama her zaman değil — bazen partial pullback yapar.
- **Bağlam:** Net breakout (strong trend bar(s), >1.5x ATR), breakout follow-through (en az 1-2 bar continuation), sonra pullback. Pullback derinliği breakout büyüklüğünün %38-62'si idealdir (çıkarsama, Fibonacci-ish ama Brooks Fib kullanmaz; eyeball).
- **Giriş:** Pullback'in setup bar'ı (genellikle reversal bar veya H1/L1) high/low + 1 tick.
- **Stop:** Setup bar opposite end veya pullback extreme.
- **Hedef:** Measured move (breakout başlangıcı ile pullback sonu arasındaki mesafe = yeni leg projection). Partial 1R, trail remainder.
- **Edge:** Brooks BO PB'yi "highest probability trend continuation" olarak tanımlar. Win rate 60-70%, R:R 2:1+. Özellikle "successful breakout" + "shallow pullback" kombinasyonu en güçlü.
- **Failure:** Pullback breakout level'ı kapanış olarak geri kırarsa → failed breakout → genellikle range içine geri dönüş ve karşı yön trade.

### Wedge / Three-Push Pattern

- **Tanım:** Üç ardışık higher high (bull wedge top, exhaustion) veya üç ardışık lower low (bear wedge bottom). Her itme bir öncekinden daha az momentum içerir (smaller bars, smaller leg). Trend lines daralır.
- **Bağlam:** Wedge, trend'in son evresidir; ya reversal ya da measured move ile yeni leg. Brooks "wedge always works at least once" der — yani wedge sonrası en az pullback gelir, %50+ olasılıkla reversal başlar.
- **Giriş:** Üçüncü push'tan sonra ilk reversal bar veya trendline kırılışı. Aggressive: third push reversal bar low altı (bull wedge top'ta short). Conservative: trendline break + pullback.
- **Stop:** Üçüncü push extreme + 1 tick.
- **Hedef:** Wedge'in başlangıcı (full retrace) veya minimum measured move (wedge yüksekliği = projection).
- **Edge:** Brooks'a göre wedge reversal win rate ~60% (ilk hedefe kadar, çıkarsama), R:R 2:1. Wedge'in "loss" durumu, ek dördüncü push (then five — power of three breaks down) gelmesidir.
- **Failure:** Dördüncü itme → wedge fail → genellikle güçlü continuation, ters yöne büyük hareket başlar.

### Spike and Channel (S&C)

- **Tanım:** Trend yapısı: ilk birkaç bar çok güçlü trend bar serisi ("spike", climactic momentum), ardından daha yavaş ve daha açılı bir kanal (channel) içinde devam. S&C pattern, Brooks'un en sık gördüğü trend yapısıdır.
- **Bağlam:** Spike, breakout ile başlar (genellikle gap, news, range exit). Spike sonrası bar'lar daha küçük olmaya başlar fakat trend devam eder — bu channel.
- **Giriş:** Channel içinde trend yönündeki pullback'lerde H1/L1 mantığıyla; channel trendline'ın test edilmesi giriş tetiği.
- **Stop:** Channel low (long) / channel high (short) altında veya setup bar opposite.
- **Hedef:** Spike'ın başlangıcı + spike length (measured move). Brooks: S&C'de fiyat spike low'a (channel başlangıcı) test eder %70+ olasılıkla; ardından ya breakout ya da reversal.
- **Edge:** S&C trend yapısı reliable continuation sağlar; channel içi pullback long'lar 60-65% win rate (çıkarsama).
- **Failure:** Channel trendline'ın güçlü break'i (strong trend bar ters yöne) → S&C bitti, çoğu kez spike origin'e dönüş veya yeni trend.

### Two-Legged Pullback (ABC)

- **Tanım:** Pullback'in standart formu: A leg (down in bull market), B leg (small bounce up), C leg (down again, often equal to A). Brooks bu yapıyı Elliott terminolojisi kullanmadan tarif eder ama benzer.
- **Bağlam:** Trend, en kısa pullback formu olarak iki bacaklı düzeltme yapar; tek bacaklı pullback nadirdir, üçten fazla zaten wedge'dir.
- **Giriş:** C leg sonunda H2 (bull) veya L2 (bear) setup'ı. Setup bar high/low + 1 tick.
- **Stop:** C leg extreme + 1 tick.
- **Hedef:** Measured move (A leg uzunluğu = yeni leg projection from C low).
- **Edge:** Two-legged pullback, Brooks'un en yüksek confidence setup'ıdır; H2/L2 trade'i içerir, win rate 65-75% (çıkarsama).
- **Failure:** C leg, A leg low'unu önemli ölçüde aşar (yani retrace > 100% relative to expected) → pullback değil reversal; trend kırılmış olabilir.

### Failed Breakout / Trap

- **Tanım:** Major bir level'ın (range high/low, swing high/low, round number, prior day H/L) breakout'u başarısız olur — fiyat level'ı geçer, follow-through gelmez, level'ın altına/üstüne geri kapanır. Bu, Brooks'a göre en yüksek olasılıklı reversal sinyalidir.
- **Bağlam:** Range içinde range top/bottom'da breakout denemesi, veya net trend'de last leg breakout exhaustion. Failed breakout için "1-2 bars beyond level then close back inside" şartı.
- **Giriş:** Breakout bar'ın opposite extreme'i kapanışla aşıldığında reversal entry. Daha agresif: failed breakout reversal bar high/low + 1 tick.
- **Stop:** Failed breakout extreme + 1 tick (yani trap'in en uç noktası).
- **Hedef:** Range'in karşı tarafı (range fade) veya measured move (failure'ın başlangıcından itibaren).
- **Edge:** Brooks failed breakout'u en güvenilir setup olarak vurgular; win rate 65-75%, R:R 2-3:1 (çıkarsama). Trap mekanizması: breakout taraflıları stopped out + reversal taraflıları aktif → momentum karşı yöne ikiye katlanır.
- **Failure:** Reversal kendisi başarısız olabilir → second breakout (ikinci kez aynı yöne) genellikle başarılı olur ("third time is the charm" — Brooks).

### ii / iii Consolidation Breakouts

- **Tanım:** ii (two consecutive inside bars) veya iii (three) sonrası breakout. Konsolidasyon ne kadar sıkıysa breakout o kadar güçlü.
- **Bağlam:** Trend içinde flag (continuation) veya range'de potential pivot. ii içinde alt-üst hangi yönde olursa olsun, breakout yönünde gir.
- **Giriş:** ii/iii'in en üst high + 1 tick (long stop) veya en alt low - 1 tick (short stop). OCO bracket: hangi taraftan kırılırsa o yön.
- **Stop:** ii/iii'in opposite tarafı (entry bar diğer ucu). Tight stop = high R:R.
- **Hedef:** Measured move (ii/iii yüksekliği projection) veya trend yapısı hedefi (next swing high/low).
- **Edge:** ii setup, küçük stop nedeniyle yüksek R:R'lı; win rate 50-55% (çıkarsama, ii standalone) ama trend yönünde çekildiğinde 60-65%. iii setup daha güvenilir çünkü konsolidasyon daha uzun.
- **Failure:** Breakout direction sahte (1-2 bar ilerler, döner) → opposite side breakout sıklıkla başarılı; bu yüzden ii failed breakout = ters yöne aynı setup.

### Reversal Bar at Major S/R

- **Tanım:** Önemli destek/direnç seviyesinde (önceki swing high/low, daily 200-EMA, round number, prior day H/L, weekly range edges) güçlü reversal bar (long tail + opposite end close).
- **Bağlam:** Level'a ilk dokunuş (en güvenilir), ya da level'ın test edildiği ikinci/üçüncü kez (bu durumda momentum divergence destekli).
- **Giriş:** Reversal bar high (bull) / low (bear) + 1 tick.
- **Stop:** Reversal bar opposite end + 1 tick.
- **Hedef:** En yakın opposite swing extreme; partial 1R, trail.
- **Edge:** Tek başına reversal bar setup'ı orta güç (~50-55%). Confluence (multiple S/R + momentum divergence + climactic preceding bar) ile 65-70%'e çıkar.
- **Failure:** Reversal bar low/high kırılırsa setup invalid; bu çoğu kez breakout'un asıl yönüdür (level kırıldı, devam edecek).

### Trading Range Top/Bottom Fades

- **Tanım:** Net trading range içinde, range top'a yakın bar'larda short (bear setup), range bottom'a yakın bar'larda long (bull setup). Fade = "uçtan dön" işlem.
- **Bağlam:** Range tanımlanmış olmalı (en az 2 swing high + 2 swing low, benzer seviyelerde, en az 10-20 bar süre). %80 range varsayımı altında default davranış.
- **Giriş:** Range high'a yakın bear reversal bar low - 1 tick (short); range low'a yakın bull reversal bar high + 1 tick (long).
- **Stop:** Range high (short için) / range low (long için) + birkaç tick (yani trader'ı sadece range breakout stopped out eder).
- **Hedef:** Range mid (1R) ve range opposite (full R:R, genellikle 3-4R).
- **Edge:** Range fade'leri %80 range varsayımı sayesinde yüksek win rate (~65-75%, çıkarsama) ama small avg R çünkü partial 1R'de kapatılır. EV pozitif kalır.
- **Failure:** Range breakout (level'ın üstüne/altına net trend bar kapanışı) → fade trade stopped, opposite breakout trade açılır.

## Bağlam ve Filtre Kuralları

Brooks setup'lar listelerken sürekli vurgular: **setup, bağlam olmadan hiçbir şeydir.** Aynı setup, farklı bağlamlarda farklı edge verir.

**Higher Time Frame (HTF) Trend Confirmation:** İşlem zaman dilimi (örn. 5m) setup verir, ama HTF (örn. 60m, daily) setup'ın "trend yönünde" olup olmadığını belirler. Brooks: 5m H1 setup'ı, 60m bull trend'de alınır; 60m bear trend'de alınmaz veya sadece A-grade ile alınır. HTF bias = setup multiplier.

**"Always-In" Determination:** Her bar için "şu an pozisyon olsam ne olurdu" sorusu. AI long ise sadece long setup'lar; AI short ise sadece short. AI flip (yön değişimi) genellikle major reversal bar + follow-through ile teyit edilir. AI belirsizse trade alma — bu durum "two-way trading" rejimidir, range içi.

**Signal Quality Grading (A/B/C):**
- **A-grade:** Tüm filtreler aynı yönde — HTF trend, AI direction, signal bar quality (strong trend bar / clean reversal), context (after pullback in trend, or at major S/R), confluence (multiple levels). A-grade size 1.0x.
- **B-grade:** Çoğu filtre aynı yön ama 1-2 zayıf nokta (örn. signal bar weak, ya da HTF mixed). Size 0.5x veya skip.
- **C-grade:** Çatışan filtreler (örn. setup HTF trend'e karşı, signal bar weak). Skip — Brooks: C-grade trade her zaman uzun vadede zarar.

**Counter-Trend Ban in Strong Trends:** Strong trend = 3+ HH (HL) sequence + close beyond 20-EMA + 60%+ trend bars. Bu rejimde counter-trend setup yasak (sadece scalp 1R fade, asla swing). Brooks: "Strong trend'de top/bottom yakalama deneme — kaybedersin."

**Trading Range Expansion vs Contraction:** Range içinde fiyat ya genişler (range edges expand, volatility artar — soon breakout) ya da daralır (range edges contract, bar size shrinks — wedge / triangle, pending decisive move). Genişleme rejiminde fade riskli; daralma rejiminde fade hala iyi ama breakout her an mümkün, partial early.

**Time of Day (intraday):** Brooks 5m E-mini için open (first 30 min) trend potansiyeli yüksek; mid-day (lunch hour) range, low edge; close (last 1 hour) trend continuation veya reversal. Setup'lar zaman dilimine göre filtrelenir; lunch hour'da setup quality grading 1 kademe düşer.

## Risk Yönetimi

Brooks'un risk kuralları setup tipine değil, hesap büyüklüğüne ve setup grade'ine göre belirlenir.

**Per-Trade Risk:** Brooks açıkça % vermez ama "küçük tut, ölme" der. Standart implementation: A-grade %1, B-grade %0.5, C-grade trade alma. Hesap drawdown'ı %10'u geçtiğinde size yarıya in (drawdown defense).

**R:R Minimum 2:1:** Setup, en az 2R hedef vermiyorsa alma. Brooks bunu sıkı uygular: 1R hedef her zaman partial close, 2R+ hedef remaining position için. Eğer setup yapısal olarak 2R verecek alan sunmuyorsa (örn. çok yakın S/R), trade'i atla.

**Partial Close at 1R:** Pozisyonun yarısı 1R'de kapatılır (otomatik take profit). Bu, kalan yarım için stop'u entry'ye çekmeyi (breakeven) güvenli kılar — yani 1R sonrası worst case scratch trade. Brooks bu pratiği "scaling out" olarak tanımlar.

**Trailing on Remainder:** Kalan yarım pozisyon trail edilir — genellikle bar low (long) / bar high (short) takip eder, veya 2-bar trail (önceki 2 bar'ın low/high). Trail yöntemi trend güçlüyse "swing high/low" (geniş trail), zayıfsa "bar-by-bar" (sıkı trail).

**Scaling-In vs Scaling-Out Preference:** Brooks scaling-in (pozisyona ekleme) konusunda çekincelidir — çünkü scaling-in, ters giderse kaybı katlar. Scaling-out (pozisyondan çıkış) ise default. Tek istisna: net trend gün içinde, A-grade pullback setup'larına 0.5x size, sonraki teyitle 0.5x ekle (toplam 1x). Bu "trend day" davranışıdır, range günde uygulanmaz.

**Kayıp Serisinde:** 3 ardışık kayıp (3-loss-streak) — Brooks: dur, chart oku, A-grade bekle, size'ı yarıya in. 5 kayıp — gün kapat. Hesap %10 drawdown — strateji review, paper trade dön. Bu kurallar Brooks'ın açıkça verdiği rakamlar değildir (çıkarsama) ama metodun ruhuna uyar.

**Kontekst Mismatch'te:** Setup teknik olarak doğru ama HTF / AI ile çatışıyor — pas geç. Brooks: "missed trade, lost trade'den iyidir." Sabırlı bekleme, edge'in bir parçası.

## Statistical / Quantifiable Edge Conditions

Aşağıdaki rakamlar Brooks'un kitaplarından alıntılanan veya çıkarsanan değerlerdir; gerçek piyasa testinde varyasyon vardır.

| Setup | Win Rate | Avg R:R | EV (R/trade) | Notlar |
|---|---|---|---|---|
| H1/L1 (strong trend) | 60-70% | 2:1 | +0.6 to +1.0 R | İlk pullback en güvenilir |
| H2/L2 (two-legged pullback) | 65-75% | 2:1+ | +0.8 to +1.2 R | En yüksek confidence |
| H3/L3 (third push) | 50-60% | 2:1 | +0.2 to +0.6 R | Failure önemli reversal |
| M2B/M2S (major reversal) | 40-50% | 3:1+ | +0.4 to +1.0 R | Rare ama büyük R |
| FF reversal | ~50% | 4-6:1 | +1.0 to +2.5 R | Tespit zor, R büyük |
| BO PB | 60-70% | 2:1 | +0.6 to +1.0 R | Trend continuation default |
| Wedge reversal | ~60% | 2:1 | +0.4 to +0.8 R | "Always works at least once" |
| S&C channel pullback | 60-65% | 2:1 | +0.4 to +0.8 R | Channel'da H/L1 mantığı |
| Failed Breakout / Trap | 65-75% | 2-3:1 | +0.8 to +1.5 R | En güvenilir reversal |
| ii breakout | 50-55% (standalone) | 3:1+ | +0.3 to +0.8 R | Çok tight stop |
| iii breakout | 55-60% | 3:1+ | +0.5 to +1.0 R | ii'den daha güvenilir |
| Reversal bar at major S/R | 50-55% (alone), 65-70% (confluent) | 2:1 | +0.0 to +0.8 R | Confluence şart |
| Range top/bottom fade | 65-75% | 1:1 to 2:1 | +0.3 to +0.8 R | %80 range varsayımı |

**Açıkça Brooks'tan alıntı (yaklaşık dilden):**
- "60% wins at 2R" — H1/H2 ortalama, strong trend.
- "Failed breakouts are very high probability" — fade reversal'larda en yüksek edge.
- "Strong trend'de countertrend trade alma; %70+ olasılıkla zarar."
- "Wedge always works at least once" — wedge sonrası en az pullback %70+.

**Önemli:** Win rate ve R:R sayıları piyasa rejimine, enstrümana, zaman dilimine ve tüccarın disiplinine göre büyük değişir. Brooks'un kitapları E-mini S&P 5m bağlamında yazılmıştır; FX, crypto, equity için kalibrasyon gerekir.

## Yaygın Hatalar / Pitfalls

1. **Trend'de top/bottom yakalama denemesi:** En yaygın acemi hatası. Strong bull trend'de "yeterince yükseldi" diye short alma, %70+ olasılıkla zarar. Çözüm: AI yön belirleme + counter-trend ban kuralı.

2. **Bağlamsız setup alma:** "H1 var, alıyorum" — ama HTF bear, AI short, signal bar weak. Setup formu doğru, bağlam yanlış = zarar. Çözüm: A/B/C grading her trade öncesi.

3. **Indikatör bağımlılığı:** RSI overbought diyor diye trend'de short. Brooks: indikatör fiyatın türevidir, bar zaten her şeyi söyler. Çözüm: indikatörü filter olarak değil, bar yapısını birincil olarak oku.

4. **Over-optimizing entry:** "Tam tepe noktasında girersem 0.5R daha kazanırım" → setup bar form'unu kaçırır. Brooks: signal bar high/low + 1 tick yeterli; tam tepe avlama EV'yi düşürür çünkü çoğu kez setup'ı kaçırırsın.

5. **Fixed targets:** Her trade için 2R hedef koyma. Bazı setup yapısı 5R verir, erken kapatırsan EV bırakırsın. Çözüm: partial 1R, trail remainder, structure-based exits.

6. **Stop atlama (no stop):** "Geri gelir" beklentisi. Brooks: stop her zaman setup bar opposite end + 1 tick, asla atlama, asla genişletme. Genişletilmiş stop, küçük zarar yerine büyük zarar.

7. **Range / Trend rejim karıştırma:** Range içinde trend setup'ı (H1, BO PB) almak — range içinde breakout %30 başarılı, %70 fade. Çözüm: rejim tespit önce, setup sonra.

8. **Aşırı işlem (overtrading):** Brooks 5m E-mini'de "iyi gün" 2-4 trade der. 10+ trade overtrading'dir, edge tükenir. Çözüm: A-grade only, sabır, missed trade > lost trade.

9. **Failed breakout'u trend devamı sanmak:** Range high'tan breakout, follow-through yok, range içine kapanış — bu reversal sinyalidir, "henüz erken, devam edecek" diye long tutmak büyük zarar. Çözüm: failed BO = trap = reverse trade.

10. **Zaman diliminde tutarsızlık:** 5m'de setup, 1m'de stop trail, 60m'de bias — karmaşa. Brooks: tek ana zaman dilimi (genellikle 5m), bir HTF (60m bias için), bar-by-bar disiplin.

11. **Climactic bar'a pozisyon ekleme:** 3 ATR trend bar gördükten sonra "momentum güçlü, ekle" → exhaustion noktasında ekleme genellikle zarar. Climactic bar = potential reversal warning, scaling-out fırsatı, scaling-in değil.

12. **Wedge'i yok sayma:** Three-push pattern net görünüyor ama trend devam ediyor diye long tutmak — wedge yarısından fazla en az pullback ile reversal yapar. Partial alıp trail etmek yeterli; tam pozisyon tutma.

## Cross-references

**Volman ile farklar:** Volman (Bob Volman, "Forex Price Action Scalping" ve "Understanding Price Action") Brooks'un FX-tarafı paraleli sayılabilir; aynı bar-by-bar felsefe, aynı pullback / breakout / failure odağı. Farklar: (1) Volman 70-tick range bar kullanır, Brooks 5m time bar; (2) Volman setup adlandırması farklıdır (ARB = ascending range break, BB = block break, vs.) ama mekanik benzer; (3) Volman daha tight stop disiplinine sahip (10 pip default), Brooks setup-bar-based variable; (4) Volman scalping odaklı (2-5 pip target), Brooks swing intraday (2R+); (5) Volman explicit risk per trade (~%1, 10 pip stop ile küçük kalır), Brooks size grade'e göre.

**Wyckoff ile örtüşen kavramlar:** Wyckoff'un accumulation / distribution / spring / upthrust kavramları Brooks'un major reversal + failed breakout'larıyla yapısal olarak örtüşür. Spring (Wyckoff) = failed breakdown + reversal up = Brooks'un Failed BO long setup'ı. Upthrust (Wyckoff) = failed breakout up + reversal down = Brooks'un Failed BO short setup'ı. Wyckoff volume'a Brooks'tan daha fazla ağırlık verir; Brooks volume'u secondary tutar (fiyat zaten her şeyi söyler). Phase analysis (Wyckoff) Brooks'ta yok, ama "trading range vs trend rejimi" benzer.

**Grimes ile kıyas:** Grimes (Adam Grimes, "Art and Science of Technical Analysis") Brooks'tan daha akademik / istatistiksel yaklaşır. Grimes momentum ve mean reversion ayrımını netleştirir, edge'i ölçer (her setup için backtest expectations); Brooks edge'i öyküsel verir, rakamlar approximate. Grimes 4-step trade plan (kontekst, setup, entry, exit) Brooks'un implicit metodunun explicit hali. Pullback / failure setup'ları neredeyse birebir aynı; isim ve framing farkı.

**Lopez (de Prado) ile kıyas:** Lopez (Marcos Lopez de Prado, "Advances in Financial ML") tamamen kantitatif tarafta; Brooks'un setup'ları Lopez framework'ünde feature engineering input'u olur (her bar için bar type, setup tipi, A/B/C grade kategorik feature). Brooks edge'i öyküsel + heuristic; Lopez framework'ü o edge'i ML modelinde ölçer ve generalize eder. İkisi orthogonal, complementary.

## Bizim Sistemle Bağlantı

Brooks'un kuralları otonom trade sistemimizde şu modüllere haritalanır:

**`signals/candles.py` (pattern detection):** Brooks bar tanımları doğrudan kod karşılığı bulur:
- `is_trend_bar(bar)`: body / range > 0.5 (strong: > 0.7), close in trend extreme %20.
- `is_doji(bar)`: |close - open| / range < 0.25.
- `is_reversal_bar(bar, direction)`: tail length / range > 0.5, close in opposite end %25, prior bar low/high broken.
- `is_inside_bar(bar, prev)`: bar.high < prev.high AND bar.low > prev.low.
- `is_outside_bar(bar, prev)`: bar.high > prev.high AND bar.low < prev.low.
- `is_ii(bars[-3:])`: bars[-1] inside bars[-2] inside bars[-3].
- `is_iii(bars[-4:])`: aynı, üç inside.

**`signals/structure.py` (swing logic):** H1/H2/H3 ve L1/L2/L3 detection:
- `count_pullback_legs(swings, trend_dir)`: trend yönünde son swing extreme'dan sonraki opposite-direction leg sayısı; H1=1, H2=2, H3=3.
- `is_strong_trend(swings, bars)`: 3+ HH/HL (bull) veya LL/LH (bear), 60%+ trend bars son n.
- `always_in_direction(bars, ema)`: AI long (close > ema, bullish trend bars majority) veya short.
- `find_failed_breakout(level, bars)`: level beyond 1-2 bar, sonra close back inside → trap.
- `wedge_detect(swings)`: 3 ardışık HH (LL), her itme küçülen amplitude ile.

**`strategies/classic_pa.yaml` (confluence skoru):** Setup detection sonucu A/B/C grading'e dönüştürülür:
```yaml
score_components:
  setup_type: {H2: 1.0, H1: 0.9, BO_PB: 0.95, M2B: 0.85, ii: 0.7, ...}
  htf_alignment: {trend_match: 1.0, neutral: 0.5, counter: 0.0}
  always_in_match: {match: 1.0, neutral: 0.5, against: 0.1}
  signal_bar_quality: {strong_trend: 1.0, weak_trend: 0.6, doji: 0.3}
  context: {after_pullback_in_trend: 1.0, range_edge_fade: 0.8, mid_range: 0.4}
  confluence_count: {3plus: 1.0, 2: 0.7, 1: 0.4}
grade_thresholds:
  A: total >= 0.85, no_zero_components
  B: 0.65 <= total < 0.85
  C: total < 0.65 → skip
size_multiplier: {A: 1.0, B: 0.5, C: 0.0}
risk_pct_per_trade: {A: 0.01, B: 0.005}
target_R: {min: 2.0, prefer: 2.5}
partial_exit_R: 1.0
trail_method: bar_by_bar  # alternative: swing_low_high
```

**Filtre / regime detection:** `regime/detector.py`'de range vs trend rejim tespit edilir; range rejiminde fade setup'ları (range top/bottom) bias, trend rejiminde continuation setup'ları (H1/H2, BO PB). Counter-trend ban: strong_trend=True ise opposite direction setup'lar grade C'ye düşürülür otomatik.

**Failure handler:** Brooks'un her setup için failure → opposite trade prensibi `failure_to_setup` mapper'ında tanımlı: failed_H1 → L2 candidate, failed_breakout → trap_reversal entry, failed_M2B → strong_continuation. Bu, kazanan trade'leri kaybedenlere göre türetmeyi sağlar.

**Backtest validation:** Yukarıdaki edge tablosu (H1 60-70%, H2 65-75%, vs.) baseline expectation; canlı veri üzerinde rolling 100-trade window ile her setup için actual win rate / R hesaplanıp baseline'dan ±20% sapma alarmlı. Sapma → setup parameter drift veya regime shift; strateji review tetiklenir.
