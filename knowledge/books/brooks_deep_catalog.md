---
source_id: brooks_deep_catalog
source_type: book
author: Al Brooks
title: Brooks Deep Pattern Catalog (granular mechanical rules)
type: reference_deep
quality: 5
ingested_date: 2026-05-09
topic_tags: [classic_pa, pattern, pullback, reversal, breakout, bar_type, always_in, structure, hypothesis_candidate]
depends_on: brooks_summary
---

# Brooks Deep Pattern Catalog — 50+ Mekanik Pattern Referansı

Bu doküman, Al Brooks'un üç kitabının (Reading Price Charts Bar by Bar; Trading Price Action: Trends; Trading Price Action: Trading Ranges; Trading Price Action: Reversals) doğrudan bar-seviyesinde, mekanik açıdan en granüler yorumunu içerir. `brooks_summary.md` dosyasındaki 12 temel setup'ın ötesinde, kitaplarda yer alan 50+ özgül pattern'ı tam giriş/çıkış/stop/win-rate/failure-mode formatıyla listeler. Gelecekteki Researcher LLM'ler bu dosyayı hipotez madeni olarak kullanabilir.

**Gösterimde:** Test edilebilirlik skoru 1–5 (1 = tam diskresyoner, 5 = tam mekanik), skoru 4–5 olan pattern'lar **[HYPOTHESIS CANDIDATE]** etiketi ile işaretlenmiştir.

---

## BÖLÜM 1: TREND DEVAM — HIGH PULLBACK SERİSİ

### H1 — Bull Trend İlk Pullback Long

**Tanım (mekanik):** Yükseliş trend dizisinde (en az 2 higher-high + higher-low konfirme) fiyat aşağı çekilir; çekilme 2–6 bar sürer. Çekilmenin son bar'ı, önceki bar'ın high'ını kırmaz (yani bu bar low/close < önceki bar high). Bir sonraki bar bu son "sinyal bar"ın high'ını 1 tick aşarsa H1 tetiklenir.

**Bağlam:** Net bull trend (AI=Long, 20-EMA yukarı eğimli, kapanışların %60+'ı EMA üstünde). En güçlü H1: ilk leg sonrası ilk pullback, EMA'ya kadar veya EMA'ya yakın geriler, ve sinyal bar bull reversal bar veya inside bar. Trading range içinde H1 alınmaz.

**Tetikleyici giriş:** Sinyal bar high + 1 tick üstünde buy stop. Sinyal bar: pullback'in son bar'ı olup body küçük veya bull (close ≥ midpoint), alt kuyruk belirgin (≥ range'in %25).

**Stop yerleşimi:** Sinyal bar low − 1 tick (dar), ya da pullback'in swing low − 1 tick (geniş). Dar stop = daha sık stopped out ama daha iyi R:R. Geniş stop = daha az stopped out ama R:R düşer; sadece strong trend'de geniş stop tercih edilir.

**Hedef:** Önceki swing high test (primary). Measured move (pullback derinliği = yeni leg uzunluğu) secondary. 1R'de yarısı kapat, kalan trailing.

**Brooks'un edge iddiası:** "Strong trend'de H1, consistently profitable" — yaklaşık %60–70 win rate, 2R ortalama; net EV ~+0.6–1.0 R/trade (kitaptaki öyküsel veri).

**Başarısızlık modu:** Sinyal bar high kırılır, fiyat 1–3 bar içinde sinyal bar low'unun altına kapanır → failed H1. Bu sıklıkla L2 short setup'a dönüşür çünkü retailler stopped out, bear açılır. Failed H1, pullback değil reversal işaretidir.

**Confluence güçleri:** EMA dokunuşu + bull reversal bar + HTF bull alignment + önceki SR seviyesi; üçü birden A-grade.

**Test edilebilir mi (skala):** 4 — Entry/stop mekanik; bağlam (AI, trend) yarı-mekanik. Kodlanabilir ama trend filter gerekir.

---

### H2 — Bull Trend İki Bacaklı Pullback Long **[HYPOTHESIS CANDIDATE]**

**Tanım (mekanik):** H1 tetiklendi ama trend devam için yeterli momentum olmadı (ya stopped out, ya 1R altında kaldı). Fiyat ikinci kez pullback yapar — bu ikinci dip A=B veya A<B derinliğindedir (A = ilk pullback derinliği, B = ikinci). İkinci pullback'in son bar'ının high'ını 1 tick aşınca H2 tetiklenir.

**Bağlam:** Trend intact (hiçbir major lower low yok); pullback iki belirgin bacak oluşturmuş, toplam süre 5–15 bar; 20-EMA hala yukarı eğimli. Two-legged pullback, ABC corrective form'dur ve en yaygın retracement türüdür.

**Tetikleyici giriş:** İkinci dip'in sinyal bar high + 1 tick. Sinyal bar tercihen bull trend bar veya lower-tail reversal bar (tail ≥ range'in %40).

**Stop yerleşimi:** İkinci dip'in en düşük low − 1 tick. Alternatif: sinyal bar low − 1 tick (daha dar, stop sıkça alınır).

**Hedef:** Önceki swing high (birincil). Measured move: pullback'in toplam derinliği = yeni yukarı leg uzunluğu. Partial 1R close, trail 2R+.

**Brooks'un edge iddiası:** "H2 en yüksek güvenilirlikli long" — yaklaşık %65–75 win rate, 2R+ RR; EV ~+0.8–1.2 R/trade. Two-legged pullback institutionların mağazayı yeniden doldurduğu yerdir.

**Başarısızlık modu:** İkinci dip, A bacağının low'unu %50'den fazla aşarsa → pullback değil, reversal sinyali; trend kırılmış olabilir. H2 failure + major lower low = M2B kandidatı değil, bear continuation sinyali.

**Confluence güçleri:** EMA retest + B dip ≈ A dip (eşit leg) + önceki SR + günün ilk saatinde (open 2 saat içinde).

**Test edilebilir mi (skala):** 5 — İki pullback bacağı mekanik sayılabilir, swing count algoritmasıyla tam otomasyona uygun. En iyi hypothesis adayı.

---

### H3 — Bull Trend Üç-İtme (Wedge) Long

**Tanım (mekanik):** Aynı trend içinde üçüncü pullback, önceki iki pullback low'undan daha düşük ama her pullback arasındaki büyük trend bar daha küçük (momentum azalıyor). Bar sayısı: üçüncü itme ilk ikisinden genellikle daha kısa veya eşit. Üç açıkça belirgin pullback dip oluşmuştur.

**Bağlam:** Trend olgunlaşmış (3 leg tamamlanmış, fiyat yükseldikçe trend bar gücü azalıyor). H3, hem trend devam hem de exhaustion sinyalidir; ikisi de olası.

**Tetikleyici giriş:** Üçüncü pullback sinyal bar high + 1 tick. Ancak H3 entry size = H1/H2'nin yarısı (daha büyük risk).

**Stop yerleşimi:** Üçüncü pullback low − 1 tick (geniş, yapısal); ya da sinyal bar low − 1 tick.

**Hedef:** Conservative: 1R hızlı scalp then flat (trend exhaustion riski). Aggressive: measured move ama partial kapatma hızı artırılır.

**Brooks'un edge iddiası:** Yaklaşık %50–60 win rate (H1/H2'den düşük); failure reversal setup'a dönüşür ki o setup büyük R verir. Net EV pozitif ama daha düşük.

**Başarısızlık modu:** Üçüncü push lower low oluşturur → bull wedge failure → genellikle güçlü bear reversal (trend exhaustion). Bu, karşı yön M2S için setup olur.

**Confluence güçleri:** Her push'ta trend bar boyutu küçülüyorsa (sayılabilir) + EMA'dan uzaklaşma artıyorsa + 3. itme süresi kısıyorsa, failure olasılığı yükselir.

**Test edilebilir mi (skala):** 3 — Üç pullback sayılabilir ama momentum azalma ölçümü (bar body boyutu karşılaştırması) yarı-mekanik.

---

### H4 ve H5 — Dördüncü ve Beşinci Pullback Long

**Tanım (mekanik):** H3 sonrası trend devam edip dördüncü (H4) ve beşinci (H5) pullback oluşturur. Her ek pullback, önceki pattern'lardan daha az güvenilirdir. H4 ve H5 genellikle zayıf trend'de (trading range içinde trend gibi görünen yapı) oluşur.

**Bağlam:** H4/H5 oluştuğunda trend muhtemelen "late stage" veya zaten range'e geçmiştir. Brooks bu setup'ları anlar ama nadiren önerir; daha çok "counting legs" için referans noktasıdır.

**Tetikleyici giriş:** Her ek pullback son bar high + 1 tick (trend yönünde). Ama bağlam kötüleşmiş olduğundan B-grade veya altı kabul edilir.

**Stop yerleşimi:** Her pullback low − 1 tick.

**Hedef:** Conservative 1R (trend güçsüz). Structural target only if strong follow-through.

**Brooks'un edge iddiası:** H4: ~%45–55, H5: ~%40–50. Brooks bu sayıları explicit vermez; gerçekçi tahmin.

**Başarısızlık modu:** H4/H5 failure → major lower low → trend reversali için teyit. Bu noktada M2B setup araması başlar.

**Confluence güçleri:** HTF trend hala bullish ise H4 daha güvenilir; HTF neutral/bearish ise H4/H5 skip.

**Test edilebilir mi (skala):** 3 — Sayım mekanik ama güvenilirlik bağlama çok bağlı.

---

## BÖLÜM 2: TREND DEVAM — LOW PULLBACK SERİSİ

### L1 — Bear Trend İlk Pullback Short

**Tanım (mekanik):** Bear trend'de (en az 2 lower-low + lower-high konfirme) fiyat yukarı çekilir; çekilme 2–6 bar. Son pullback bar'ı önceki bar low'unu kırmaz. Bir sonraki bar bu "sinyal bar"ın low'unu 1 tick altına geçerse L1 tetiklenir.

**Bağlam:** Net bear trend (AI=Short, 20-EMA aşağı eğimli, kapanışların %60+'ı EMA altında). En güçlü L1: ilk leg sonrası ilk pullback, EMA'ya retest, sinyal bar bear reversal bar veya inside bar.

**Tetikleyici giriş:** Sinyal bar low − 1 tick sell stop.

**Stop yerleşimi:** Sinyal bar high + 1 tick (dar), ya da pullback swing high + 1 tick (geniş).

**Hedef:** Önceki swing low; measured move. 1R'de yarısı, trail kalanı.

**Brooks'un edge iddiası:** ~%60–70 win rate strong bear'de; H1 ile simetrik. EV ~+0.6–1.0 R/trade.

**Başarısızlık modu:** Sinyal bar low kırılır, fiyat sinyal bar high üstüne kapanır → failed L1 → H2 long setup kandidatı.

**Confluence güçleri:** EMA retest + bear reversal bar + HTF bear + günün sabah saatlerinde (trend days).

**Test edilebilir mi (skala):** 4 — H1 ile simetrik; mekanik kodlanabilir.

---

### L2 — Bear Trend İki Bacaklı Pullback Short **[HYPOTHESIS CANDIDATE]**

**Tanım (mekanik):** Bear trend'de two-legged (ABC) yukarı corrective pullback sonrası short. İki belirgin pullback yüksek (A high, B high): B high ≤ A high (B ≤ A). İkinci yükseğin son bar'ının low'u 1 tick kırılınca L2 tetiklenir.

**Bağlam:** Bear trend intact; hiçbir major higher-high yok; pullback toplam süre 5–15 bar. Brooks'un "en favori" short setup'ı olduğunu belirtir.

**Tetikleyici giriş:** İkinci pullback high sinyal bar low − 1 tick sell stop.

**Stop yerleşimi:** İkinci pullback high + 1 tick (yapısal); dar: sinyal bar high + 1 tick.

**Hedef:** Önceki swing low; measured move (pullback derinliği = yeni bear leg). 1R partial, trail.

**Brooks'un edge iddiası:** ~%65–75 win rate; "favorite short" — yüksek güven, büyük institutional short ekleme noktası. EV ~+0.8–1.2 R/trade.

**Başarısızlık modu:** İkinci pullback high, A high'ını aşarsa → reversal devreye girebilir; L2 trade edilmez. Higher-high konfirme = trend değişimi işareti.

**Confluence güçleri:** EMA retest + B ≈ A derinlik (equal legs) + önceki SR (eski destek = yeni direnç) + HTF bear.

**Test edilebilir mi (skala):** 5 — H2 ile simetrik, tam mekanik. Hipotez adayı.

---

### L3 — Bear Trend Üç-İtme (Wedge) Short

**Tanım (mekanik):** Bear trend üç aşağı itme: her itmenin düşük body gücü ile (trend bar body'si küçülerek) üçüncü daha kısa bir down-leg oluşur. Üçüncü LL, wedge yapısı içinde.

**Bağlam:** Bear trend olgunlaşmış, L1 ve L2 tamamlanmış. L3 hem devam hem reversal riski içerir.

**Tetikleyici giriş:** Üçüncü pullback yüksek sinyal bar low − 1 tick. Size = L1/L2'nin yarısı.

**Stop yerleşimi:** Üçüncü pullback swing high + 1 tick.

**Hedef:** Conservative 1R fast; failure ise M2B için watch.

**Brooks'un edge iddiası:** ~%50–60. Failed L3 = bull wedge reversal; M2B için trigger.

**Başarısızlık modu:** Fiyat, üçüncü itme LL'sinin altına gidemez → reversal başlar → M2B / failed L3 long setup.

**Test edilebilir mi (skala):** 3 — Üç itme sayılabilir; momentum ölçümü yarı-mekanik.

---

### L4 ve L5 — Dördüncü/Beşinci Bear Pullback Short

**Tanım (mekanik):** L3 sonrası ek pullback'ler. Her ek bacak daha az güvenilir, bear trend muhtemelen range'e geçiyor veya late stage.

**Bağlam:** Late-stage bear trend veya range içi yapı. Çok düşük edge.

**Test edilebilir mi (skala):** 2 — Sayım mekanik ama edge zayıf ve bağlam-bağımlı.

---

## BÖLÜM 3: BAR YAPISI VE TİPOLOJİ

### ii (Inside-Inside) Konsolidasyon Breakout **[HYPOTHESIS CANDIDATE]**

**Tanım (mekanik):** Üç ardışık bar: bar1 (konteyner), bar2 (bar1 içinde: bar2.high < bar1.high VE bar2.low > bar1.low), bar3 (bar2 içinde: bar3.high < bar2.high VE bar3.low > bar2.low). Yani iki ardışık inside bar. Bar3 kapanmasının ardından: bar3.high + 1 tick (long stop) veya bar3.low − 1 tick (short stop) yerleştirilir; hangisi kırılırsa o yön trade.

**Bağlam:** Trend içinde flag (devam), veya range içinde pivot. Trend içinde ii setup, trend yönündeki break tercih edilir ama OCO (one-cancels-other) bracket ile her iki yön sigortalanabilir.

**Tetikleyici giriş:** bar3.high + 1 tick (long) veya bar3.low − 1 tick (short); ilk kırılan taraf aktive olur, diğer order cancel.

**Stop yerleşimi:** Long entry ise stop = bar3.low − 1 tick (ii'nin diğer tarafı). Short entry ise stop = bar3.high + 1 tick. Stop mesafesi = bar3 range + 2 tick (çok dar).

**Hedef:** Measured move: ii toplam height × 2 (projection). Trend yönünde: önceki swing extreme. En az 3:1 R:R olması gerekir çünkü stop çok dar, ama win rate ~%50–55 standalone.

**Brooks'un edge iddiası:** Win rate tek başına ~%50–55; trend yönünde ~%60–65. Ancak stop çok dar olduğu için R:R yüksek (3:1+), EV pozitif kalır. "ii setup gives tight stop = best mechanical R:R."

**Başarısızlık modu:** Trend yönünde breakout başarısız (1–2 bar ilerler, geri döner) → ters taraftaki stop aktive = ters yön breakout başlar. Failed ii long = ii short setup olur.

**Confluence güçleri:** Trend'e hizalı olması + EMA yakınında + low-volatility (ATR düşük) dönemde + büyük SR öncesi.

**Test edilebilir mi (skala):** 5 — Tamamen mekanik (bar high/low karşılaştırması). En iyi hipotez adayı. Sonuç: standart engulfing'den tamamen bağımsız bir pattern.

---

### iii (Inside-Inside-Inside) Breakout

**Tanım (mekanik):** Dört ardışık bar: bar1 konteyner, bar2 ⊂ bar1, bar3 ⊂ bar2, bar4 ⊂ bar3 (ya da bar3 ⊂ bar2 ⊂ bar1 yeterli — üç ardışık inside). Son inside bar'ın high/low breakout'u tetikler.

**Bağlam:** ii'den daha sıkı konsolidasyon; genellikle büyük bir hareketin öncesi. Olasılıksal olarak ii'den daha güvenilir çünkü belirsizlik daha uzun süre korunmuş = biriken enerji daha yüksek.

**Tetikleyici giriş:** Son inside bar high + 1 tick (long) veya low − 1 tick (short).

**Stop yerleşimi:** Ters uç + 1 tick.

**Hedef:** ii'den büyük; measured move = iii toplam range × 2–3.

**Brooks'un edge iddiası:** ~%55–65 (ii'den biraz yüksek). Stop hala dar, R:R 3:1+.

**Başarısızlık modu:** ii ile aynı — failed iii = ters yön aktive.

**Test edilebilir mi (skala):** 5 — Tamamen mekanik.

---

### iiB (Inside-Inside-Breakout) — Trend Devam

**Tanım (mekanik):** ii formasyonunu takiben üçüncü bar, ii'nin trend yönünde breakout'unu yapar; bu bar güçlü trend bar (body ≥ range'in %60). "iiB" = ii sonrası breakout bar. Breakout bar kapanışı yüksekse, bu bar sinyal bar olarak kabul edilir ve kapanış fiyatı veya bar high + 1 tick giriş noktasıdır.

**Bağlam:** Trend'de flag olarak oluşan ii; breakout bar çok güçlü olduğunda entry doğrudan breakout bar kapanışında yapılabilir (bar kapanmadan önceki buy = market order on close).

**Tetikleyici giriş:** (a) Breakout bar kapanışında market order (aggressive), ya da (b) breakout bar'dan sonraki bar'ın ilk tick'inde (conservative). Stop = ii'nin başlangıç bar'ı opposite extreme.

**Stop yerleşimi:** ii konteyner bar'ının ters ucunun ötesi + 1 tick.

**Hedef:** Measured move (ii genişliği × 2).

**Brooks'un edge iddiası:** Strong trend'de iiB ~%65–70 — breakout bar gücü yüksek olduğunda daha güvenilir.

**Başarısızlık modu:** Breakout bar kapanışından sonra fiyat geri döner ve ii içine girer → false breakout → reverse.

**Test edilebilir mi (skala):** 4 — Bar gücü (body/range oranı) mekanik; timing (kapanışta entry) hafif diskresyoner.

---

### Doji Bar Serisi Konsolidasyon

**Tanım (mekanik):** 2–5 ardışık doji bar (|close − open| < %25 × range). Fiyat mini-range içinde sıkışır. Doji serisi sona erip ardışık güçlü trend bar geldiğinde breakout sayılır.

**Bağlam:** Hem trend içi flag hem de range içi pivot olabilir. Doji serisi sonrası breakout yönü güçlü ise trend yönü; zayıf ise range-içi reversion.

**Tetikleyici giriş:** Doji serisinin yüksek (high) veya alçak (low) kırıldığında, ilk trend bar close'unda veya sonraki bar open'ında.

**Stop yerleşimi:** Doji serisinin ters ucunun ötesi + 1 tick.

**Hedef:** Measured move (doji serisi height × 2 minimum).

**Brooks'un edge iddiası:** Doji cluster sonrası trend bar breakout ~%55–65 (trend yönünde).

**Başarısızlık modu:** Breakout bar reverses aynı kapanış döneminde → ters yöne doji cluster breakout.

**Test edilebilir mi (skala):** 4 — Doji body oranı ve ardışık sayı mekanik.

---

### Trend Bar (Body ≥%50 Range) — Güç Ölçer

**Tanım (mekanik):** Bull trend bar: close > open, body = (close − open) / (high − low) ≥ 0.50, close high ≥ (high − 0.20 × range). Strong: body ≥ 0.70 × range. Bear simetrisi: close < open, body ≥ 0.50, close low ≤ (low + 0.20 × range).

**Bağlam:** Trend bar, trend devam konfirmasyonunda ve setup quality ölçümünde kullanılır. Setup sinyal bar'ı güçlü trend bar ise A-grade; doji ise C-grade.

**Tetikleyici giriş:** Trend bar'ın high (bull) + 1 tick veya low (bear) − 1 tick; follow-through entry.

**Stop yerleşimi:** Trend bar'ın body midpoint altı (bull) — agresif; ya da bar low − 1 tick.

**Hedef:** Momentuma güvenerek measured move. Kısa vadeli: 1R fast.

**Brooks'un edge iddiası:** İzole trend bar tek başına setup değildir; diğer pattern'larla confluence yarattığında A-grade sayılır.

**Başarısızlık modu:** Trend bar sonrası doji veya reversal bar → exhaustion; trend bar'ın tamamı geri alınırsa, o trend bar "climactic" olabilir.

**Test edilebilir mi (skala):** 5 — Tamamen hesaplanabilir oran.

---

### Reversal Bar (Pin Bar / Hammer) — Tek Bar Reversal

**Tanım (mekanik):** Bull reversal bar: bar.low < prev.low (alt tarama, likidite alma), bar.close ≥ (bar.low + 0.50 × bar.range) ve tercihen bar.close > prev.close, alt kuyruk ≥ %50 × bar.range, üst body küçük. Bear reversal bar simetri.

**Bağlam:** Major SR seviyesinde veya trend pullback sonunda ortaya çıktığında değer taşır. Ortada, rastgele bir barda reversal bar = setup değil.

**Tetikleyici giriş:** Reversal bar close yönüne göre: bull reversal bar high + 1 tick. Aggressive: bar kapanışında market.

**Stop yerleşimi:** Reversal bar'ın tail ucu (low, bull için) − 1 tick.

**Hedef:** Önceki swing ters extreme test; partial 1R, trail.

**Brooks'un edge iddiası:** Confluence olmadan ~%50–55. Confluence (major SR + HTF trend) ile ~%65–70.

**Başarısızlık modu:** Stop kırılırsa, tail'in üstündeki likidite tükenmiş = güçlü devam. "Stop-hunt then continuation."

**Test edilebilir mi (skala):** 4 — Kuyruk oranı mekanik; bağlam kısmen diskresyoner.

---

### Outside Bar — İki Yönlü Belirsizlik

**Tanım (mekanik):** bar.high > prev.high VE bar.low < prev.low. Outside bar, iki tarafı da test eder. Kapanış yönü (üst %33 = outside up, alt %33 = outside down) short-term bias verir ama kesin sinyal değildir.

**Bağlam:** Genellikle "confusion" — range içinde ya da trend kırılma noktasında. Brooks, outside bar'ı standalone trade olarak önermez; bağlam içinde ek sinyal olarak kullanır.

**Tetikleyici giriş:** Outside bar'ın kapanış yönünde bir sonraki bar: outside up ise sonraki bar high + 1 tick (long); outside down ise low − 1 tick (short).

**Stop yerleşimi:** Outside bar'ın ters ucu + 1 tick.

**Hedef:** 1R scalp, yapısal hedef değil.

**Brooks'un edge iddiası:** Outside bar tek başına düşük edge (~%45–55). Trend yönünde outside bar sonrası follow-through = devam; zıt kapanış = trap.

**Başarısızlık modu:** Outside bar her iki tarafı da test eder; kapanış yönü yanıltıcı olabilir (false signal).

**Test edilebilir mi (skala):** 3 — Tanım mekanik, bağlam filtresi zayıf.

---

### Climactic Bar — Tükeniş Barı

**Tanım (mekanik):** Bar range ≥ 2.0 × ATR(20). Trend yönünde çok güçlü, "son gaz" bar'ı. Bull climax: büyük bull trend bar, range ≥ 2×ATR, close near high, genellikle gap veya continuation'ı takip eder.

**Bağlam:** Trend son evresi veya news/event sonrası momentum burst. Climactic bar = potential reversal warning değil, kesin reversal değil. İki seçenek: (1) devam (trend güçleniyorsa); (2) exhaustion (trend zayıflıyorsa, wedge içindeyse).

**Tetikleyici giriş:** Climactic bar'a karşı trade edilmez (stop çok geniş). Climax sonrası ilk pullback (H1/L1) giriş için beklenir.

**Stop yerleşimi:** Climactic bar'ın body midpoint (agresif) veya full bar low/high (geniş).

**Hedef:** Climax sonrası H1/L1 trade: önceki swing extreme.

**Brooks'un edge iddiası:** Climax sonrası ilk pullback yüksek olasılık (~%65–70 bir test yapar). Ama "climax" tanımı mekanik değil, bağlam filtreli.

**Başarısızlık modu:** Climax devam eder (5+ bar) → trend güçlü, exhaustion değil, S&C spike phase'e giriyor.

**Test edilebilir mi (skala):** 4 — ATR multiplier mekanik; yorumlama yarı-diskresyoner.

---

### Breakout Bar — SR Ötesi Kapanış

**Tanım (mekanik):** Trading range / consolidation'ın dışına güçlü trend bar ile çıkış. Koşullar: (1) Önceki n=15–20 bar'ın en yüksek high'ını (long) veya en düşük low'unu (short) aşan kapanış; (2) Breakout bar body ≥ %60 × range; (3) Bar range ≥ 1.3 × ATR(20).

**Bağlam:** Range'de (en az 10–20 bar), ardından güçlü çıkış. Breakout bar kalitesi zayıfsa (small body, wick büyük) → olası trap.

**Tetikleyici giriş:** Breakout bar'ın high + 1 tick (long) — eğer breakout bar gücü yeterli değilse, sonraki bar (BO PB) için beklenir.

**Stop yerleşimi:** Range'in eski high/low − 1 tick (yani range içine geri girerse stopped out). Ya da breakout bar midpoint.

**Hedef:** Measured move (range height projection). Range = 20 bar içindeki high − low; projection = breakout yönünde aynı mesafe.

**Brooks'un edge iddiası:** Güçlü breakout bar: ~%55–65 başarı. Zayıf breakout bar: ~%40 (failed BO olasılığı yüksek).

**Başarısızlık modu:** Breakout bar'ın close fiyatı, range içine 1–3 bar içinde geri döner → failed BO → trap setup → ters yöne trade.

**Test edilebilir mi (skala):** 4 — Mekanik kurallar; n bar range high/low sıkça kullanılan algoritmik yapı.

---

## BÖLÜM 4: TREND DEVAM — YAPIASAL PATTERN'LAR

### BO PB (Breakout Pullback) — Kırılış Sonrası Geri Çekilme **[HYPOTHESIS CANDIDATE]**

**Tanım (mekanik):** Güçlü breakout (en az 1 trend bar, body ≥%60, range ≥ 1.3×ATR) ardından pullback. Pullback: breakout seviyesine kadar geri gelir veya kısmen geri çekilir (%38–%62 Fibonacci approximation, Brooks exact oran vermez). Pullback derinliği ≤ breakout bar'ın %75'i tercih edilir (shallow pullback = strong breakout).

**Bağlam:** Başarılı breakout konfirme (en az 1–2 follow-through bar), sonra pullback. Breakout seviyesi artık eski direnç → yeni destek (long) veya eski destek → yeni direnç (short).

**Tetikleyici giriş:** Pullback'in son bar'ı (sinyal bar): bull reversal bar veya inside bar, high + 1 tick (long). Stop = pullback swing low − 1 tick.

**Stop yerleşimi:** Pullback'in en düşük low − 1 tick (yapısal). Narrow: sinyal bar low − 1 tick.

**Hedef:** Measured move: (breakout start - pullback end) × 1, projected from pullback end. Önceki swing extreme + breakout height.

**Brooks'un edge iddiası:** "Highest probability trend continuation" — ~%60–70. Shallow pullback (<50% retrace) = daha güçlü; deep pullback = breakout daha az güçlü.

**Başarısızlık modu:** Pullback, breakout seviyesini kapanış bazında aşarsa (range içine geri girerse) → failed BO → trade exit, ters yön araştır.

**Confluence güçleri:** Breakout yüksek hacimle (opsiyonel), breakout seviyesi önemli SR, HTF alignment.

**Test edilebilir mi (skala):** 5 — Breakout seviyesi + pullback derinliği + sinyal bar mekanik ölçülebilir. İyi hipotez adayı.

---

### Spike and Channel (S&C) — Hız Trendini İzleme

**Tanım (mekanik):** İki fazlı trend yapısı. Spike: 3–7 ardışık güçlü trend bar (body ≥%60, kaçan yön), fiyat hızla ilerler. Channel: spike'ın ardından trend bar density azalır, pullback'ler başlar ama trend hala devam eder; trend channel çizilir (iki trendline). Channel içinde her H1/L1 mantıkla trade edilir.

**Bağlam:** Haberse spike (market-open, gap, breakout from major range). Spike'ı takip etmek yerine channel içi pullback'leri bekle.

**Tetikleyici giriş:** Channel trendline test + H1/L1 setup. Sinyal bar, channel trendline'ı dokunmasından (veya yaklaşmasından) döner → entry.

**Stop yerleşimi:** Channel low/high (yapısal); sinyal bar opposite end (dar).

**Hedef:** Spike origin measured move (spike başlangıcından spike high/low mesafesi = channel'den projection). Brooks: "channel en az spike origin'e test eder (%70+)."

**Brooks'un edge iddiası:** Channel içi H1/L1: ~%60–65; spike origin test: %70+ (zamanla gelir). S&C pattern tanımlandıktan sonra channel çok güvenilir.

**Başarısızlık modu:** Channel trendline güçlü trend bar ile kırılır (ters yönde) → S&C sona erdi. Spike origin'e dönüş başlar.

**Confluence güçleri:** Spike'ın ardından daha küçük bar'lar ve daha yavaş ilerleme = güçlü S&C.

**Test edilebilir mi (skala):** 3 — Spike tanımı mekanik; channel trendline çizimi yarı-diskresyoner.

---

### TBTL (Two-Bar Trend Leg)

**Tanım (mekanik):** İki ardışık güçlü trend bar (her ikisi de body ≥%60 × range, aynı yön). Bu iki bar birlikte tek bir büyük momentum leg sayılır. TBTL sonrası pullback, H1 (bull) veya L1 (bear) giriş noktasıdır.

**Bağlam:** Trend güçlü; TBTL'nin ardından trend devam bekle. TBTL içinde counter-trend trade yasak.

**Tetikleyici giriş:** TBTL tamamlandıktan sonra ilk pullback sinyal bar high/low + 1 tick (H1/L1 mantığı).

**Stop yerleşimi:** Pullback swing extreme + 1 tick.

**Hedef:** TBTL boy kadar ek mesafe (measured move). Önceki swing extreme.

**Brooks'un edge iddiası:** TBTL sonrası H1/L1 = strong trend H1/L1 kalitesiyle özdeş (~%60–70).

**Başarısızlık modu:** TBTL sonrası pullback derin olursa (TBTL'yi tam geri alırsa) → trend zayıf, H2/L2 beklenir.

**Test edilebilir mi (skala):** 4 — İki ardışık güçlü trend bar mekanik.

---

### TTR (Tight Trading Range to Trend Breakout) **[HYPOTHESIS CANDIDATE]**

**Tanım (mekanik):** Dar range: son n=10–15 bar'ın high-low toplam genişliği ≤ 1.5 × ATR(20). Fiyat "sıkışmış" görünüyor. Sıkışmanın ardından trend bar ile çıkış (body ≥%60, range ≥ 1.3×ATR) = TTR breakout. TTR ne kadar uzun sürerse (bar sayısı arttıkça) breakout o kadar güçlü.

**Bağlam:** Range gün içinde veya daha uzun. Dar range sonrası patlama — en öngörülemeyen ama en etkili setup'lardan biri.

**Tetikleyici giriş:** TTR'nin high + 1 tick (long) veya low − 1 tick (short) — OCO bracket.

**Stop yerleşimi:** TTR'nin ters ucu + 1 tick (range'in başlangıç tarafı).

**Hedef:** Measured move: TTR height × 2. Önceki major swing high/low.

**Brooks'un edge iddiası:** TTR breakout başarı: ~%55–65 (yön öngörüsü zor ama yön kararlaştıktan sonra follow-through yüksek). Süre 15+ bar = daha güçlü.

**Başarısızlık modu:** Breakout 1–3 bar ilerler, döner ve TTR içine geri kapanır → failed TTR breakout → reverse setup.

**Confluence güçleri:** HTF trend yönüne hizalı + range kontraksiyon (her bar biraz daha dar) = pending büyük hareket.

**Test edilebilir mi (skala):** 5 — ATR bazlı range genişliği ve breakout bar gücü tamamen mekanik. Hipotez adayı.

---

### Tight TR (Çok Dar Trading Range) Fade

**Tanım (mekanik):** n=5–10 bar genişliği ≤ 1.0 × ATR(20). Range içinde top bar'dan short, bottom bar'dan long. Her iki yön de işlenebilir.

**Bağlam:** Range kesinlikle tanımlanmış olmalı (en az 3 swing high + 3 swing low, benzer seviyeler). Dar range'de fade edge yüksek ama breakout anında (bir bar) tüm kazanç gidebilir.

**Tetikleyici giriş:** Range top'a yakın bar (top − 0.15 × range içinde) → kısa bear reversal bar → sell low − 1 tick. Range bottom'a yakın bar → bull reversal bar → buy high + 1 tick.

**Stop yerleşimi:** Range extreme'in ötesi + 1 tick.

**Hedef:** Range midpoint (1R); range opposite (2R).

**Brooks'un edge iddiası:** Tight TR içi fade ~%65–75; ama R küçük. EV pozitif ama düşük R boyutu nedeniyle scalp.

**Başarısızlık modu:** Range breakout → fade trade stopped. Breakout BO PB setup'a geç.

**Test edilebilir mi (skala):** 4 — ATR bazlı range tespit mekanik.

---

### Final Flag (FF) — Tükeniş Bayrağı Dönüşü

**Tanım (mekanik):** Trend en az 3 leg yapmış, son konsolidasyon (flag) dar, önceki flag'lere göre kısa süreli ve sıkı. FF kriterleri: (1) Trend bar sayısı azalıyor (her leg daha zayıf); (2) Son flag, öncekilerden %30+ daha dar ve kısa süreli; (3) Flag'in trend yönünde breakout olursa follow-through gelmez ve 1–3 bar içinde geri döner → failed FF breakout.

**Bağlam:** Late-stage trend, en az 3 büyük leg. Son flag'in boyutu ve süresi önemli — küçüldükçe güçleniyor.

**Tetikleyici giriş:** (a) Conservative: Flag'in trend yönü breakout → 1R scalp, dikkatli. (b) Reversal: Breakout failure (1–3 bar içinde dönüş) → ters yöne giriş, stop = failed breakout extreme.

**Stop yerleşimi:** (a) Flag opposite end. (b) Failed breakout extreme + 1 tick.

**Hedef:** (a) 1R fast scalp. (b) Trend başlangıcına doğru measured move; 5–10R potansiyel.

**Brooks'un edge iddiası:** "Final Flag failure is one of the most reliable reversal triggers" — reversal trade win rate ~%55–65; ama R:R 5–10:1 olduğunda EV en yüksek seviyelerde. Tespit doğruysa rare ama çok değerli.

**Başarısızlık modu:** "Final Flag" değilmiş — trend devam eder (5+ leg). Bu riski azaltmak için trend leg sayısı ve momentum azalması metriği gerekir.

**Confluence güçleri:** 3 leg + azalan momentum + son flag en dar + HTF overbought/oversold divergence.

**Test edilebilir mi (skala):** 3 — "Son flag en dar" mekanik, ama "final" tespiti bağlam filtreli.

---

## BÖLÜM 5: TREND DÖNÜŞÜ

### M2B (Major Trend Reversal Buy) — İki Sinyal Konfirmasyonu

**Tanım (mekanik):** Bear trend bottom'da major long setup. Mekanik koşullar: (1) Climactic selloff: son down-leg en az 2 büyük bear trend bar, son bar'ın range ≥ 1.5×ATR(20). (2) Güçlü bull reversal bar: bar.low < prev.low (alt tarama), alt kuyruk ≥ %50 × range, close ≥ (low + 0.60 × range), tercihen close > prev.close. (3) Follow-through: reversal bar'ından sonraki bar bull trend bar. M2 = "ikinci sinyal" yani reversal bar + follow-through bar birden.

**Bağlam:** Major support seviyesinde (önceki swing low, daily EMA200, round number). Momentum divergence opsiyonel ama güçlendirir.

**Tetikleyici giriş:** Follow-through bar (ikinci bar) high + 1 tick. Saf reversal bar'ına değil, reversal + follow-through çiftine gir.

**Stop yerleşimi:** Climactic low − 1 tick (geniş, yapısal). Dar: reversal bar low − 1 tick.

**Hedef:** Bear trend'deki son major pullback high test (primary). Measured move: 2× reversal bar setup'ının range'i. 2R minimum hedef.

**Brooks'un edge iddiası:** ~%40–50 win rate (reversal dikkatli) ama R:R 3:1+; EV ~+0.4–1.0 R. Rare setup, yüksek değer.

**Başarısızlık modu:** Reversal bar low kırılır → bear devam, often hard selloff. Failed M2B = bear continuation setup.

**Confluence güçleri:** Major SR + climactic selloff + follow-through bar + HTF support (daily/weekly). Üçü birden = A-grade.

**Test edilebilir mi (skala):** 4 — Climactic koşullar (ATR × 1.5, tail oranı) mekanik; follow-through bar mekanik.

---

### M2S (Major Trend Reversal Sell)

**Tanım (mekanik):** Bull trend top'ta M2B'nin simetriği. (1) Buying climax: son up-leg 2+ güçlü bull trend bar, son bar range ≥ 1.5×ATR. (2) Bear reversal bar: bar.high > prev.high (üst tarama), üst kuyruk ≥ %50 × range, close ≤ (high − 0.60 × range). (3) Follow-through bear bar. M2S = reversal bar + follow-through bear.

**Bağlam:** Major resistance seviyesinde (önceki swing high, daily EMA200, round number). Brooks: "Bull market tops are grinding, not V-top" — bu yüzden M2S birden fazla denemeden sonra çalışır.

**Tetikleyici giriş:** Follow-through bear bar low − 1 tick.

**Stop yerleşimi:** Climactic high + 1 tick.

**Hedef:** Son major pullback low; measured move 2R minimum.

**Brooks'un edge iddiası:** ~%40–50 win rate (ilk M2S denemesi sıkça başarısız, bear trend başlar ama hızla geri döner); multi-attempt gerekebilir. R:R 3:1+.

**Başarısızlık modu:** Reversal high kırılır → bull devam. "Scratching out tops" = çok sayıda failed M2S.

**Test edilebilir mi (skala):** 4 — M2B ile simetrik.

---

### Wedge Top Reversal — Üç-İtme Dönüşü

**Tanım (mekanik):** Bull trend üç ardışık higher-high (push 1, 2, 3): her push daha az trend bar (body gücü azalıyor) veya her push daha kısa süreli. Trend çizgileri daralır. Üçüncü push'tan sonra bear reversal bar (üst tarama + düşük kapanış) → short entry.

**Koşullar:** (1) Üç belirgin yukarı itme konfirme (swing high sayısı=3). (2) Her itme arasındaki ara pullback mevcut (iki ara düzeltme). (3) Üçüncü push, birinci ve ikinci push'tan daha zayıf (trend bar density azalmış, opsiyonel momentum divergence).

**Tetikleyici giriş:** Üçüncü push'tan sonra ilk bear reversal bar low − 1 tick (aggressive); ya da trendline kırılışı sonrası pullback low − 1 tick (conservative).

**Stop yerleşimi:** Üçüncü push high + 1 tick.

**Hedef:** Wedge başlangıcı (full retrace) primary. Minimum: wedge height = üçüncü push − düzeltme dipleri arası mesafe.

**Brooks'un edge iddiası:** "Wedge always works at least once" — en az pullback gelir (>%70). Full reversal: ~%60.

**Başarısızlık modu:** Dördüncü push (four pushes) → wedge fail → trend devam, genellikle büyük move ters yöne.

**Test edilebilir mi (skala):** 3 — Swing high sayısı mekanik; "momentum azalma" yarı-mekanik.

---

### Wedge Bottom Reversal — Üç-İtme Long

**Tanım (mekanik):** Bear trend üç ardışık lower-low (push 1, 2, 3), her push daha az bear momentum. Üçüncü LL'den sonra bull reversal bar high + 1 tick (aggressive), ya da trendline kırılışı pullback'i (conservative).

**Koşullar:** M2B'nin öncüsü genellikle wedge bottom'dır. Üç belirgin lower-low, iki ara yüksek (pullback).

**Tetikleyici giriş:** Üçüncü LL bull reversal bar high + 1 tick.

**Stop yerleşimi:** Üçüncü LL − 1 tick.

**Hedef:** Wedge başlangıcı; momentum gelirse ötesi.

**Brooks'un edge iddiası:** Simetrik wedge top ile. ~%60 first target başarı.

**Başarısızlık modu:** Dördüncü LL → wedge fail → güçlü bear devamı.

**Test edilebilir mi (skala):** 3 — Wedge Top ile aynı.

---

### Failed Breakout / Trap — En Güvenilir Reversal **[HYPOTHESIS CANDIDATE]**

**Tanım (mekanik):** Major level (n=20 bar high/low, prior swing extreme, round number) kırılır ama follow-through gelmez. Koşullar: (1) Bar, level'ı aşar (1 tick üstünde / altında kapanış yeterli). (2) 1–3 bar içinde fiyat level'ın karşı tarafına döner (yani geri gelir). (3) Reversal bar veya strong close ters yönde. Bu "trap" mekanizmasıdır: level kıran retailler trapped (stopped out) + reversal oyuncular aktive.

**Bağlam:** Range içi (range extreme test) veya trend'in son evresi (exhaustion trap). Major round numbers özellikle "trap" noktaları.

**Tetikleyici giriş:** Failed breakout bar (ya da onu takip eden reversal bar) ters ucu + 1 tick. Bull trap (yukarı kırılış başarısız): reversal bar low − 1 tick (short). Bear trap (aşağı kırılış başarısız): reversal bar high + 1 tick (long).

**Stop yerleşimi:** Failed breakout extreme + 1 tick (yani trap'in en uç noktasının ötesi).

**Hedef:** Range opposite (fade için) ya da measured move (trend reversal için). 2–3R.

**Brooks'un edge iddiası:** "Failed breakouts are very high probability" — ~%65–75 win rate, 2–3:1 R:R. Trap mekanizması: two-sided momentum. EV ~+0.8–1.5 R.

**Başarısızlık modu:** Reversal kendisi başarısız → ikinci breakout (gerçek breakout). "Third time is the charm" — Brooks: iki failed BO sonrası üçüncü attempt genellikle başarılı.

**Confluence güçleri:** Önceki önemli SR + overextended trend + reversal bar kalitesi yüksek + HTF opposition.

**Test edilebilir mi (skala):** 5 — n-bar high/low aşımı + geri dönüş mekanik, tamamen kodlanabilir. En iyi hipotez adaylarından biri.

---

### M1 Reversal — İlk Büyük Reversal Bar

**Tanım (mekanik):** Trend son evresi veya major SR'de ilk büyük reversal bar. M1 = "Major 1" = birinci sinyal. Tek reversal bar, henüz follow-through yok. M1'e giriş agresif: reversal bar high/low + 1 tick (trend'e karşı). M2 = M1 sonrası ikinci sinyal (follow-through) = daha güvenilir giriş.

**Bağlam:** M1, riskli ama daha iyi fiyat verir. M2, daha güvenilir ama biraz daha kötü fiyat. Brooks M2'yi tercih eder ama M1'i detaylandırır.

**Tetikleyici giriş:** M1 reversal bar close yönüne göre: bull M1 → bar high + 1 tick (erken entry); stop = bar low − 1 tick.

**Stop yerleşimi:** Reversal bar opposite end + 1 tick.

**Hedef:** M2'nin geleceği varsayılır — M2 teyidi gelince ek pozisyon; başlangıçta 1R scalp.

**Brooks'un edge iddiası:** M1 tek başına ~%40–50. M1 + M2 konfirmasyonu beklenirse ~%55–65.

**Başarısızlık modu:** M1 bar high/low kırılır → trend devam, M1 false reversal. Brooks: "Çoğu M1 başarısız; M2'yi bekle."

**Test edilebilir mi (skala):** 3 — M1 tanımı mekanik; "major SR" bağlam filtresi yarı-diskresyoner.

---

### Two-Legged Pullback (ABC) Reversal — Klasik Geri Çekilme

**Tanım (mekanik):** Trend pullback en yaygın formu: A leg (trend'e karşı), B leg (mini bounce trend yönünde), C leg (trend'e karşı, A'ya yakın derinlik, genellikle A=C). C leg'in sonunda H2/L2 setup oluşur.

**Koşullar:** (1) A leg: 2–5 bar, belirgin trend'e karşı hareket. (2) B leg: 2–4 bar, trend yönünde küçük bounce (tam düzeltme değil). (3) C leg: A leg derinliğinin %75–%125'i kadar (A=C ± %25). (4) C leg sonunda sinyal bar (reversal bar veya inside bar).

**Tetikleyici giriş:** C leg sinyal bar high (bull) / low (bear) + 1 tick.

**Stop yerleşimi:** C leg extreme − 1 tick (bull için); C > A olursa trend kırılmış sayılır.

**Hedef:** Measured move: A leg derinliği = yeni trend leg uzunluğu (C noktasından projection). Bu, H2/L2 hedefiyle özdeş.

**Brooks'un edge iddiası:** Two-legged pullback H2/L2 ile aynı (~%65–75); "en yaygın ve en güvenilir retracement form."

**Başarısızlık modu:** C leg A'yı %125'ten fazla aşarsa → reversal (trend kırılmış). C = A'nın 2 katına ulaşırsa kesin reversal.

**Test edilebilir mi (skala):** 4 — A=C leg hesabı mekanik; C/A oranı backtest'e uygun.

---

### Outside Down Bar at Extreme — Acil Dönüş

**Tanım (mekanik):** Major SR seviyesinde (ya da trend extreme'de) outside bar oluşur ve kapanış düşük (close ≤ low + 0.25 × range). Bu, güçlü short sinyal bar sayılır. Bull market top'ta: bar, hem önceki bar high'ını hem low'unu aşar, close zayıf → bear outside bar.

**Koşullar:** (1) Outside bar koşulu: bar.high > prev.high AND bar.low < prev.low. (2) Kapanış zayıf: close ≤ (low + 0.25 × range). (3) Major SR seviyesinde veya climactic sonrası.

**Tetikleyici giriş:** Outside bar low − 1 tick (short).

**Stop yerleşimi:** Outside bar high + 1 tick.

**Hedef:** 2R primary; yapısal: önceki swing low.

**Brooks'un edge iddiası:** Outside bar + weak close + major SR = confluence reversal ~%60.

**Başarısızlık modu:** Fiyat, outside bar high üstüne döner → bull devam (trend güçlü).

**Test edilebilir mi (skala):** 4 — Outside bar ve kapanış oranı mekanik; SR tanımı yarı-mekanik.

---

### Outside Up Bar at Extreme — Yukarı Dönüş

**Tanım (mekanik):** Major destek seviyesinde outside bar, close güçlü (close ≥ high − 0.25 × range). Bear bottom'da: outside bar, güçlü bull kapanış → bull reversal entry.

**Koşullar:** Outside bar + strong close (top %25) + major support.

**Tetikleyici giriş:** Outside bar high + 1 tick (long).

**Stop yerleşimi:** Outside bar low − 1 tick.

**Hedef:** 2R; önceki swing high.

**Brooks'un edge iddiası:** ~%60 (outside down bar ile simetrik).

**Test edilebilir mi (skala):** 4 — Simetrik.

---

## BÖLÜM 6: RANGE / KONSOLİDASYON PATTERN'LARI

### Range Top Fade (Üst Çift Tepe Short)

**Tanım (mekanik):** Net tanımlanmış trading range (en az 2 swing high benzer seviyede, en az 10 bar süre) içinde range high yakınında (range top'un %85'inden yukarısında) bar oluşur. Bu barda bear reversal bar veya doji + zayıf kapanış → short entry.

**Bağlam:** Trading range kesinlikle tanımlanmış olmalı. Brooks: "range içinde default davranış fade extremes — kanıtlanana kadar breakout bekle."

**Tetikleyici giriş:** Sinyal bar low − 1 tick (short). Sinyal bar, range top'un %85–%100 bandında ve bear karakterli.

**Stop yerleşimi:** Range top + 2 tick (kesin breakout olduğunda stopped).

**Hedef:** Range midpoint (1R); range bottom (2–3R).

**Brooks'un edge iddiası:** ~%65–75 (range varsayımı altında). Partial 1R at midpoint, trail remainder.

**Başarısızlık modu:** Güçlü breakout bar range top'un üstüne kapanır → fade stopped out → breakout trade.

**Test edilebilir mi (skala):** 4 — Range top/bottom mekanik hesap; sinyal bar koşulu mekanik.

---

### Range Bottom Fade (Alt Çift Dip Long)

**Tanım (mekanik):** Range bottom yakınında (range bottom'un %85'inden aşağısında — yani alt %15 bandında) bull reversal bar veya inside bar → long entry.

**Bağlam:** Range top fade ile simetrik. Range tanımlanmış, en az 10 bar.

**Tetikleyici giriş:** Sinyal bar high + 1 tick (long).

**Stop yerleşimi:** Range bottom − 2 tick.

**Hedef:** Range midpoint (1R); range top (2–3R).

**Brooks'un edge iddiası:** ~%65–75 (range top ile simetrik).

**Test edilebilir mi (skala):** 4 — Simetrik.

---

### 50% Range Retest + Continuation

**Tanım (mekanik):** Range belirlendikten sonra fiyat range midpoint'e (50%) yakın bir bar'da durur ve trend yönüne döner. Özellikle range'den breakout sonrası fiyat %50 seviyesine kadar geri çekilip dönerse güçlü continuation setup'ıdır.

**Koşullar:** (1) Range tanımlanmış. (2) Breakout veya trend hareketi var. (3) Fiyat range midpoint ± %10'a geri çekilir. (4) Sinyal bar oluşur.

**Tetikleyici giriş:** Sinyal bar trend yönü breakout + 1 tick.

**Stop yerleşimi:** Midpoint'in ötesi + 1 tick (yani range içine geri girerse stopped).

**Hedef:** Trend yönünde önceki swing extreme.

**Brooks'un edge iddiası:** 50% retest + reversal: ~%55–65. Fibonacci'ye benzer ama Brooks mekanik kullanır.

**Test edilebilir mi (skala):** 4 — Range midpoint hesabı mekanik.

---

### Range Expansion Immediate Reversal

**Tanım (mekanik):** Range içinde fiyat ani genişleme (range'in dışına 1–2 bar ile çıkış) yapar ama hemen geri döner (1–3 bar içinde). Bu, expansion failure / trap setup'ıdır.

**Koşullar:** Bar range ≥ 2.0 × ATR, fiyat range outside kapanır veya dokunur, sonra hızla range içine döner.

**Tetikleyici giriş:** Geri dönüşün ilk reversal bar'ı trend yönünde + 1 tick.

**Stop yerleşimi:** Expansion extreme + 1 tick.

**Hedef:** Range opposite (2–3R).

**Brooks'un edge iddiası:** Range expansion failure ~%60–70 (fake breakout tespit edilirse).

**Test edilebilir mi (skala):** 3 — "Hızla geri dönüş" tanımı için bar sayısı eşiği gerekir.

---

### Pullback to TR Boundary (Range Kenarına Geri Çekilme)

**Tanım (mekanik):** Başarılı breakout sonrası (range'den çıkış), fiyat range'in eski boundary'sine tam olarak geri gelir (yani eski range high = yeni destek, ya da eski range low = yeni direnç). Bu boundary'de sinyal bar oluşursa: BO PB setup.

**Bağlam:** BO PB ile özdeş; fark, pullback'in tam olarak eski range boundary'sine kadar gitmesidir (daha derin pullback).

**Tetikleyici giriş:** Boundary'deki sinyal bar breakout yönünde high/low + 1 tick.

**Stop yerleşimi:** Range boundary'nin içine 1 tick.

**Hedef:** Measured move (range height, breakout yönünde).

**Brooks'un edge iddiası:** Boundary retest: ~%60–70. "Old resistance → new support" güçlü SR flip.

**Test edilebilir mi (skala):** 5 — Boundary seviyesi exact mekanik hesap.

---

## BÖLÜM 7: ALWAYS-IN KAVRAMLARI

### Always-In Long Flip — Yön Değişimi Long'a Geçiş

**Tanım (mekanik):** Piyasa AI=Short'tan AI=Long'a geçer. Flip koşulları: (1) Güçlü bull reversal bar: long lower tail + close ≥ range midpoint + close > önceki kapanış. (2) Follow-through bull bar (kapanış güçlü, trend yönünde). (3) Fiyat 20-EMA üstünde kapanış (ya da çok yakın). Bu üç koşulun konfirmasyonu = AI flip long.

**Bağlam:** AI flip = major event. Flip sonrası counter-trend trade yasak, sadece long setup aranır. Flip işlemi zaman alabilir (3–5 bar teyit).

**Tetikleyici giriş:** Follow-through bar high + 1 tick veya direct market entry on flip bar close.

**Stop yerleşimi:** Flip bar veya reversal bar low − 1 tick.

**Hedef:** Önceki major resistance (önceki bear swing high). Measured move 2R+.

**Brooks'un edge iddiası:** AI flip başarısı: %60–70 (flip teyit edilirse). False flip ise tekrar AI=Short döner — bu ek sinyal verir.

**Başarısızlık modu:** Follow-through gelmez, flip bar low kırılır → false flip → AI=Short devam. False flip sıkça exhaustion noktasında gerçekleşir.

**Test edilebilir mi (skala):** 3 — Body oranı ve EMA koşulu mekanik; "flip teyiti" bağlama bağlı.

---

### Always-In Short Flip — Yön Değişimi Short'a Geçiş

**Tanım (mekanik):** AI=Long'tan AI=Short'a geçiş. (1) Güçlü bear reversal bar: long upper tail + close ≤ range midpoint + close < önceki kapanış. (2) Follow-through bear bar. (3) Fiyat 20-EMA altında kapanış.

**Bağlam:** AI=Long'tan Short'a flip; flip sonrası sadece short setup.

**Tetikleyici giriş:** Follow-through bar low − 1 tick.

**Stop yerleşimi:** Flip bar high + 1 tick.

**Hedef:** Önceki major support. Measured move 2R+.

**Brooks'un edge iddiası:** AI flip short: %60–70 (teyit gerekli). "Two-way trading" döneminde false flip sıkça.

**Test edilebilir mi (skala):** 3 — Long flip ile simetrik.

---

### Strong Always-In — Güçlü Rejim

**Tanım (mekanik):** AI yönü net, şüphe yok. Metrikler: (1) Son 10 bar'ın %70+'ı trend bar trend yönünde; (2) Fiyat 20-EMA'nın trend yönünde %1'den fazla; (3) Hiçbir reversal bar oluşmamış son 5 bar içinde; (4) Son swing pullback < %38 retrace.

**Bağlam:** Strong AI = sadece trend yönünde trade. Counter-trend kesinlikle yasak. Entry: her H1/L1 (strong trend pullback) A-grade.

**Test edilebilir mi (skala):** 4 — Tüm metrikler mekanik hesap.

---

### Weak Always-In — Zayıf Rejim / İki Yönlü

**Tanım (mekanik):** AI yönü belirsiz. Metrikler: (1) Son 10 bar'da trend bar oranı %40–60; (2) Fiyat 20-EMA yakınında (±%0.3); (3) Son 5 bar içinde hem bull hem bear güçlü kapanış var; (4) Pullback depth >%62 retrace.

**Bağlam:** Weak AI = two-way trading. Sadece A-grade setup alınır, size küçük. Range fade setup'ları öne çıkar.

**Test edilebilir mi (skala):** 4 — Oranlar mekanik.

---

## BÖLÜM 8: ÖZEL VE NADIR PATTERN'LAR

### Bear EMA Gap Test (EMA Yukarı Boşluk Testi Short)

**Tanım (mekanik):** Bear trend'de 20-EMA'nın yukarısına pullback yapılır (yani fiyat EMA'yı 1–3 bar boyunca aşar, en fazla %0.5) ama fiyat EMA'da veya hemen üstünde döner. Son pullback bar'ı EMA'ya yakın ve bear reversal bar ise → short entry.

**Bağlam:** Bear trend, EMA pullback, L1/L2 ile çakışır. EMA, dinamik direnç görevi.

**Tetikleyici giriş:** EMA yakınında bear reversal bar low − 1 tick.

**Stop yerleşimi:** Bar high + 1 tick (ya da EMA + 0.5% üstü).

**Hedef:** Önceki swing low; measured move.

**Brooks'un edge iddiası:** EMA test + L1/L2 konfirmasyonu ~%65. "EMA as dynamic resistance in bear trend."

**Test edilebilir mi (skala):** 4 — EMA mesafesi ve bar konumu mekanik.

---

### Bull EMA Gap Test (EMA Aşağı Boşluk Testi Long)

**Tanım (mekanik):** Bull trend'de 20-EMA'nın altına pullback (EMA'yı 1–3 bar boyunca aşar aşağıya, en fazla %0.5) ama döner. EMA yakınında bull reversal bar → long entry. EMA dinamik destek.

**Bağlam:** Bull trend H1/H2 ile çakışır. EMA gap test = two-for-one setup.

**Tetikleyici giriş:** EMA yakınında bull reversal bar high + 1 tick.

**Stop yerleşimi:** Bar low − 1 tick veya EMA − 0.5%.

**Hedef:** Önceki swing high.

**Brooks'un edge iddiası:** ~%65. Bull EMA + H2 = A-grade.

**Test edilebilir mi (skala):** 4 — EMA gap mekanik hesap.

---

### Measured Move (AB=CD) — Eşit Leg Projection

**Tanım (mekanik):** Trend'de birinci leg (A→B, uzunluk = X bar, mesafe = Y puan) ve küçük düzeltme (B→C), ardından ikinci leg (C→D): AB = CD beklentisi (yani D noktası = C + Y). AB=CD, entry hedefi olarak kullanılır; ayrıca "D noktasında" reversal beklentisi oluşturulabilir.

**Bağlam:** Measured move hem hedef hem reversal setup olarak kullanılır. "D noktası" (measured move hedefi) majör SR sayılır.

**Tetikleyici giriş:** C noktasında H2/L2 setup (devam için). D noktasında M2B/M2S setup (reversal için).

**Stop yerleşimi:** (Devam) C − 1 tick. (Reversal) D extreme − 1 tick.

**Hedef:** (Devam) D noktası. (Reversal) Yeni swing extreme.

**Brooks'un edge iddiası:** "Measured move hedefleri çok sık gerçekleşir" — ~%60–70 ilk measured move hedefine ulaşır.

**Test edilebilir mi (skala):** 5 — AB uzunluğu mekanik; CD projeksiyon hesabı mekanik.

---

### Micro Double Top / Bottom Reversal

**Tanım (mekanik):** Küçük double top: trend içinde pullback sırasında iki ardışık bar yüksek (ya da çok yakın high — ±1–2 tick), ama trend devam edemez, fiyat geri döner. "Micro" = iki bar / kısa vadeli. Bull trend'de: pullback sırasında iki yakın high oluşur ve fiyat döner → long devam setup.

**Bağlam:** Pullback içindeki double top/bottom = pullback'in bittiği yer. H2/L2 ile kombine.

**Tetikleyici giriş:** İkinci high/low'dan sonraki reversal bar → trend yönünde giriş.

**Stop yerleşimi:** İkinci high/low + 1 tick (mini double top) ya da − 1 tick (double bottom).

**Hedef:** Önceki swing extreme; measured move.

**Brooks'un edge iddiası:** Micro double top/bottom = mini two-legged pullback = H2/L2 kalitesi (~%65–70).

**Test edilebilir mi (skala):** 4 — İki yakın high/low mekanik (±N tick tolerans).

---

### Opening Range Breakout (ORB) — Gün Açılış Range Kırılışı

**Tanım (mekanik):** İlk 30 dakika (6 bar × 5m) oluşan range (high ve low) ardından güçlü trend bar ile kırılış. ORB high: ilk 30 dak high + 1 tick (long stop). ORB low: ilk 30 dak low − 1 tick (short stop). Breakout bar: body ≥%60 × range, bar range ≥ 1.2 × ATR(5, günlük piyasa bazında).

**Bağlam:** İntraday, özellikle E-mini, döviz, vadeli. Trend day başlangıcı. Brooks: sabah trendin başladığı yer.

**Tetikleyici giriş:** ORB kırılışı; direkt market order veya stop order.

**Stop yerleşimi:** ORB opposite taraf − 1 tick (tüm açılış range kaybedilirse stopped).

**Hedef:** Measured move (ORB height × 2). Günlük major level.

**Brooks'un edge iddiası:** Trend day'lerde ORB: ~%65–70 başarı. Non-trend day'lerde failed ORB sık → fade.

**Test edilebilir mi (skala):** 5 — Tamamen mekanik; zaman bazlı (ilk 30 dak) + bar koşulu.

---

### Gap and Go (Gap Devamı)

**Tanım (mekanik):** Önceki kapanıştan boşlukla açılış (gap: open > prev.high için bull gap; open < prev.low için bear gap). Gap büyüklüğü ≥ %0.5 × ATR(20, daily). Açılıştan sonra gap yönünde trend bar (body ≥%60) oluşursa → gap and go entry.

**Bağlam:** Gap oluştuğunda iki senaryo: (1) Gap and go (devam) — gap dolmaz, trend başlar; (2) Gap fill (fade) — gap kapanır. İlk 3 bar, hangisi olduğunu söyler.

**Tetikleyici giriş:** Gap yönünde ilk güçlü trend bar high (bull) / low (bear) + 1 tick.

**Stop yerleşimi:** Gap başlangıcı (open) yakınında veya güçlü trend bar low − 1 tick.

**Hedef:** Önceki trend yönünde swing extreme + gap mesafesi.

**Brooks'un edge iddiası:** Gap and go: ~%55–65 (gap büyük ve trend güçlü ise). Gap fill (fade): ~%55–65 (gap küçük ise).

**Test edilebilir mi (skala):** 4 — Gap hesabı mekanik; trend bar koşulu mekanik.

---

### Consecutive Close Test — Ardışık Kapanış Testi

**Tanım (mekanik):** Belirli bir SR seviyesi, 2–3 ardışık bar tarafından aynı yönde test edilir ama hiçbiri geçemez (closes are within 0.2 × ATR of the level). Sonunda güçlü breakout veya fade — "market is testing this level repeatedly."

**Bağlam:** Kritik SR seviyesinde momentum testi. 3. bar, seviyeyi ya kırar ya da büyük geri dönüş başlar.

**Tetikleyici giriş:** Üçüncü test'ten sonra: (a) seviye kırılırsa → breakout entry; (b) seviye kırılmazsa ve reversal bar oluşursa → fade entry.

**Stop yerleşimi:** (a) Breakout: seviye − 1 tick. (b) Fade: seviye + 2 tick.

**Hedef:** (a) Measured move. (b) Range opposite.

**Brooks'un edge iddiası:** "Third time test" — üçüncü test sonrası ya break ya güçlü fade; ~%65+ bir yöne.

**Test edilebilir mi (skala):** 3 — Test sayısı ve mesafe mekanik; yön tespiti bağlama bağlı.

---

### Climactic Exhaustion Reversal — Tükeniş Tersine Dönüş

**Tanım (mekanik):** Uzun süredir (en az 5+ bar veya 3+ leg) devam eden trend, bir veya iki bar ile dramatik şekilde hızlanır (climactic bar: range ≥ 2.5 × ATR). Climax sonrası 1–3 bar içinde güçlü reversal bar oluşursa → exhaustion reversal entry.

**Bağlam:** Trend late stage + climax + reversal bar = exhaustion setup. M2B/M2S ile örtüşür ama daha spesifik "bar size" kriterleri içerir.

**Tetikleyici giriş:** Climax bar'ın ters yönündeki reversal bar, high/low + 1 tick.

**Stop yerleşimi:** Climax extreme + 1 tick.

**Hedef:** Minimum: climax bar'ın %50 geri alımı. Büyük reversal: full retrace.

**Brooks'un edge iddiası:** Climax bar ≥ 2.5×ATR + reversal bar: ~%60–70 (en azından kısmi geri alım). Full reversal: %50.

**Test edilebilir mi (skala):** 4 — ATR multiple ve reversal bar koşulları mekanik.

---

### Bar Range Contraction → Expansion Setup

**Tanım (mekanik):** Son 5–8 bar'ın her birinin range'i bir öncekinin %90'ından küçük (yani ardışık küçülen bar'lar). Bu "daralan bant" bekleyen büyük hareketin işaretidir. Ardından ilk bar, önceki bar'ın range'inin %150'sinden büyük olursa → expansion entry.

**Bağlam:** Volatility contraction → expansion setup. Hem trend hem range rejiminde oluşabilir.

**Tetikleyici giriş:** Expansion bar'ın trend yönünde high + 1 tick / low − 1 tick.

**Stop yerleşimi:** Expansion bar opposite end + 1 tick.

**Hedef:** Measured move: expansion bar height × 2.

**Brooks'un edge iddiası:** Contraction → expansion: ~%55–65 yönde follow-through.

**Test edilebilir mi (skala):** 5 — Bar range hesabı tamamen mekanik, ATR bazlı.

---

### Channel Trendline Break — Kanal Kırılışı Reversal

**Tanım (mekanik):** Trend channel (iki paralel trendline) içinde fiyat ilerler. Kanal kırılışı: güçlü trend bar, channel trendline'ı 1+ tick aşarak kapanır (ters yönde). Bu, S&C'nin channel fazının sona erdiği sinyaldir.

**Koşullar:** (1) Channel en az 5 bar sürmüş. (2) Kırılış bar: body ≥%60 × range, ters yönde. (3) Kırılış bar range ≥ 1.3 × ATR.

**Tetikleyici giriş:** Kırılış bar close'unda (agresif) ya da follow-through bar low/high + 1 tick.

**Stop yerleşimi:** Channel trendline yakınında (yani channel içine geri girerse stopped).

**Hedef:** Spike origin; measured move.

**Brooks'un edge iddiası:** Channel break: ~%60–70 spike origin'e test (zamanla). Reversal veya continuation.

**Test edilebilir mi (skala):** 3 — Trendline çizimi yarı-diskresyoner.

---

### Bull Flag / Bear Flag Continuation

**Tanım (mekanik):** Güçlü trend leg ardından küçük, karşı-trend konsolidasyon (3–10 bar). Flag koşulları: (1) Leg: en az 5 güçlü trend bar. (2) Flag: 3–10 bar, küçük karşı-trend hareket (flag derinliği ≤ leg'in %38'i). (3) Flag trend bars zayıf (small body, doji heavy). Trend yönünde flag high/low kırılışı → devam.

**Bağlam:** Trend içi continuation; flag = "institutionlar mola verdi." En sık ve en güvenilir devam setup'larından.

**Tetikleyici giriş:** Flag high (bull) + 1 tick / low (bear) − 1 tick.

**Stop yerleşimi:** Flag low (bull) − 1 tick / flag high (bear) + 1 tick.

**Hedef:** Measured move: leg uzunluğu = yeni leg uzunluğu (flag breakout'tan).

**Brooks'un edge iddiası:** Bull/Bear flag: ~%65–70 devam. "Flag in trend = continuation with high probability."

**Test edilebilir mi (skala):** 4 — Leg ve flag bar sayısı ile derinlik mekanik.

---

### Broad Channel Pullback — Geniş Kanal Geri Çekilme Long/Short

**Tanım (mekanik):** Geniş trend channel (trendline açısı 20–45 derece arası, parallels channel): fiyat channel içinde salınım yapar, channel alt trendline'a her dokunuşta long (bull channel), üst trendline'a her dokunuşta short (bear channel).

**Bağlam:** S&C'nin channel fazıyla benzer; fark — geniş kanalda pullback'ler daha derin, daha zaman alır.

**Tetikleyici giriş:** Alt trendline dokunuşu + bull reversal bar → high + 1 tick (long in bull channel). Üst trendline + bear reversal bar → low − 1 tick (short in bear channel).

**Stop yerleşimi:** Trendline'ın ötesi (channel dışına çıkarsa stopped).

**Hedef:** Kanal opposite trendline (channel'ın tam genişliği).

**Brooks'un edge iddiası:** Broad channel fade: ~%60–65. Kanal kırılırsa S&C terminasyon sinyali.

**Test edilebilir mi (skala):** 3 — Trendline yarı-diskresyoner; dokunuş mekanik.

---

### First Pullback After BO (İlk Geri Çekilme Sonrası Devam) — Aggressive Entry

**Tanım (mekanik):** Breakout'tan sonra ilk pullback 1–2 bar sürer (çok sığ). Bu pullback'in sinyal bar'ı içerde (inside bar) veya doji olursa → trend yönünde agresif giriş (shallow pullback = çok güçlü breakout).

**Bağlam:** BO PB'den daha agresif versiyon — pullback çok sığ, trend çok güçlü. Dar stop ama entry daha zor.

**Tetikleyici giriş:** Sığ pullback sinyal bar high (bull) + 1 tick.

**Stop yerleşimi:** Sinyal bar low − 1 tick (çok dar).

**Hedef:** Measured move (breakout mesafesi × 1.5).

**Brooks'un edge iddiası:** Sığ pullback (<25% retrace) = güçlü trend sinyali; devam ~%70+.

**Test edilebilir mi (skala):** 4 — Retrace oranı mekanik.

---

### Round Number Fade — Yuvarlak Sayı Direnç/Destek

**Tanım (mekanik):** Büyük yuvarlak sayılar (100, 500, 1000, 10000 gibi) kritik SR'dir. Fiyat bu sayıya ilk kez yaklaştığında (±0.2% band): (1) Güçlü trend bar zaten varsa → momentum uzar, pas geç; (2) Reversal bar veya doji varsa → fade entry.

**Bağlam:** E-mini ve majör endekslerde round number ~= floor trader pivot. Brooks explicitly round numbers'ı güçlü S/R olarak anar.

**Tetikleyici giriş:** Round number yakınında reversal bar → ters yöne high/low + 1 tick.

**Stop yerleşimi:** Round number'ın ötesi + 0.1 × ATR.

**Hedef:** Önceki swing extreme; round number'dan ±1 ATR.

**Brooks'un edge iddiası:** Round number ilk test reversal: ~%60–70 (kısmi bounce). Full trend reversal: düşük.

**Test edilebilir mi (skala):** 4 — Round number tanımı mekanik (modulo check); reversal bar mekanik.

---

### Scalp Reversal Bar at First Pullback — İlk Pullback Scalp

**Tanım (mekanik):** Güçlü trend leg'den sonra ilk pullback 1–3 bar. Bu pullback'in son bar'ı çok küçük (doji veya küçük reversal bar). Entry = trend yönünde high/low + 1 tick. Stop çok dar (≤ %50 × ATR). Target = 1R fast scalp.

**Bağlam:** Strong trend, first retracement. Brooks scalp entry'yi "for experienced traders" olarak tanımlar.

**Tetikleyici giriş:** Doji/small bar high (bull) + 1 tick.

**Stop yerleşimi:** Doji low − 1 tick (çok dar; sık durdurulur).

**Hedef:** 1R (momentum yeterli değilse 2R almak zor).

**Brooks'un edge iddiası:** ~%55–65; stop çok dar olduğu için R:R 3:1+ potansiyel.

**Test edilebilir mi (skala):** 4 — Doji/small bar koşulları mekanik.

---

### Prior Day High/Low Test — Önceki Gün Extreme Testi

**Tanım (mekanik):** Önceki günün high (PDH) veya low (PDL) değerleri, güçlü intraday SR görevi görür. Fiyat PDH'ye ilk kez yaklaştığında: (1) Bear reversal bar → short (fade); (2) Güçlü bull bar kapatırsa → long (breakout). Aynı PDL için ters.

**Bağlam:** İntraday E-mini / FX. PDH/PDL, önceki gün en büyük hacmin gerçekleştiği seviyedir (fiyat hafızası).

**Tetikleyici giriş:** Fade: PDH yakınında bear reversal bar low − 1 tick. Breakout: PDH üstü close + bar high + 1 tick.

**Stop yerleşimi:** Fade: PDH + 2 tick. Breakout: PDH − 1 tick.

**Hedef:** Fade: −1R (PDH − target = PDH − ATR); Breakout: Measured move.

**Brooks'un edge iddiası:** PDH/PDL fade: ~%60–65 (ilk test). Breakout: ~%55–60.

**Test edilebilir mi (skala):** 5 — PDH/PDL mekanik hesap; reversal/breakout bar koşulları mekanik.

---

### Three-Bar Reversal Setup — Üç Bar Dönüş Yapısı

**Tanım (mekanik):** (1) Setup bar (trend yönünde güçlü bar). (2) Inside bar veya doji (duraksaması). (3) Reversal bar (setup bar'ın ters yönünde güçlü kapanış, setup bar'ın body'sini %50+ geri alır). Üçüncü bar giriş tetikleyicisidir.

**Bağlam:** Major SR'de veya trend dönüm noktasında. Tek bar reversal'dan daha güvenilir (üç bar teyit).

**Tetikleyici giriş:** Üçüncü (reversal) bar close yönünde high/low + 1 tick.

**Stop yerleşimi:** Setup bar extreme + 1 tick.

**Hedef:** Önceki swing; measured move.

**Brooks'un edge iddiası:** Three-bar reversal: ~%55–65. M2B/M2S ile örtüşür.

**Test edilebilir mi (skala):** 4 — Üç bar koşulları mekanik.

---

### Prior Swing High/Low Test Reentry — Önceki Swing Testi Girişi

**Tanım (mekanik):** Trend'de fiyat önceki büyük swing high'ı (bull) veya low'u (bear) test eder (yaklaşır ±0.3 × ATR), geri çekilir ve sonra tekrar bu seviyeye döner. İkinci dokunuşta reversal bar + eğer kırılırsa → breakout entry.

**Bağlam:** Çift tepe/dip veya SR kırılışı girişimi. İkinci dokunuş, birinciden daha güçlü veya zayıf olmasına göre yön belirlenir.

**Tetikleyici giriş:** Kırılış: swing extreme + 1 tick (long) / − 1 tick (short). Fade: reversal bar ters yönü.

**Stop yerleşimi:** Swing extreme'in ötesi.

**Hedef:** Measured move veya önceki swing yapısı.

**Brooks'un edge iddiası:** İkinci swing test + kırılış: ~%60. Double top/bottom fade: ~%55–65.

**Test edilebilir mi (skala):** 4 — Swing high/low mekanik; yakınlık eşiği ATR bazlı.

---

## BÖLÜM 9: EK PATTERN'LAR VE VARYASYONLAR

### Bear Trend Bar Closing Below Support — Destek Altı Kapanış

**Tanım (mekanik):** Güçlü bear trend bar: body ≥%60 × range, kapanış major support'un altında (önceki n=20 bar low). Bu, confirmed breakout işaretidir. "Close below support" = institutional satış onayı.

**Tetikleyici giriş:** Bar close'unda market order (agresif) ya da close − 1 tick sell limit (konservatif).

**Stop yerleşimi:** Kırılan support seviyesi + 1 tick (yani support üstüne geri kapanırsa stopped).

**Hedef:** Measured move (önceki leg uzunluğu). Next major support.

**Test edilebilir mi (skala):** 5 — Mekanik; n-bar low + body oranı.

---

### Bull Trend Bar Closing Above Resistance — Direnç Üstü Kapanış

**Tanım (mekanik):** Güçlü bull trend bar: body ≥%60, kapanış önceki n=20 bar high üstünde. Confirmed breakout.

**Tetikleyici giriş:** Bar close'unda market order veya close + 1 tick buy limit.

**Stop yerleşimi:** Kırılan resistance − 1 tick.

**Hedef:** Measured move.

**Test edilebilir mi (skala):** 5 — Simetrik.

---

### ii Failed Breakout Reverse — ii Başarısız Kırılış Tersine

**Tanım (mekanik):** ii formasyonu kırılır (trend yönünde), ama 1–3 bar içinde ii içine geri döner. Bu "false ii breakout" → ters yöne setup aktive. Ters yöndeki ii low/high + 1 tick.

**Bağlam:** ii'nin iki yönlü olduğu söylendi; failed ii breakout = ters yön ii breakout. Güçlü ve mekanik.

**Test edilebilir mi (skala):** 5 — Tamamen mekanik.

---

### Bear Gap Fill Then Reverse — Boşluk Dolumu Sonrası Dönüş

**Tanım (mekanik):** Bear gap açılışından (open < prev.low) sonra fiyat yükselir ve gap'i doldurur (prev.low'a ulaşır). Gap dolumu sırasında veya hemen sonra bear reversal bar oluşursa → short entry (gap filled = resistance test).

**Bağlam:** Gap fill oranı ~%65–70 (Brooks explicit). Fill olduğunda resistance aktive.

**Tetikleyici giriş:** Gap fill seviyesinde bear reversal bar low − 1 tick.

**Stop yerleşimi:** prev.low + 1 tick.

**Hedef:** Gap origin (açılış seviyesi).

**Test edilebilir mi (skala):** 4 — Gap seviyesi mekanik; fill tespiti mekanik.

---

### Bull Gap Fill Then Reverse — Boşluk Dolumu Sonrası Long Dönüş

**Tanım (mekanik):** Bull gap (open > prev.high) sonrası gap fill (prev.high'a dönüş). Fill seviyesinde bull reversal bar → long entry.

**Test edilebilir mi (skala):** 4 — Simetrik.

---

### Trend Line Touch Entry — Trendline Dokunuş Girişi

**Tanım (mekanik):** Net trend'de, trendline çizilmiş (en az 3 swing low/high'ı birleştiren). Fiyatın trendline'a dokunuşu (±0.2 × ATR) + bull/bear reversal bar → trend yönünde giriş.

**Bağlam:** S&C channel ile örtüşür; broad channel pullback ile özdeş.

**Tetikleyici giriş:** Trendline dokunuşundaki sinyal bar high/low + 1 tick.

**Stop yerleşimi:** Trendline'ın ötesi + 0.3 × ATR.

**Hedef:** Channel opposite trendline.

**Test edilebilir mi (skala):** 3 — Trendline çizimi yarı-diskresyoner; dokunuş mekanik.

---

### Strong Trend Bar Engulf Rejection — Güçlü Bar Reddi

**Tanım (mekanik):** Güçlü trend bar (body ≥%70) ardından sonraki bar'ın bu güçlü bar'ın body'sini tamamen içine alması (engulf). "Engulf" = sonraki bar'ın body, önceki bar'ın body'sini aşar. Bu, momentum'un tamamen durduğu ve tersine döndüğü sinyalidir.

**Bağlam:** Major SR veya trend late-stage. Single-bar momentum kill.

**Tetikleyici giriş:** Engulf bar close yönünde (ters yön) high/low + 1 tick.

**Stop yerleşimi:** Güçlü trend bar'ın extreme + 1 tick.

**Hedef:** 2R.

**Test edilebilir mi (skala):** 5 — Body engulf tamamen mekanik.

---

## BÖLÜM 10: ÖZET VE HİPOTEZ KANDİDATLARI

### Skala 4–5 Pattern Listesi (Otomasyona En Uygun)

Aşağıdaki pattern'lar hem mekanik olarak tamamen kodlanabilir, hem de mevcut engulfing tabanlı hipotezlerden yapısal olarak bağımsızdır (dekore edilmemiş):

| # | Pattern | Skala | Neden Hypothesis Adayı |
|---|---------|-------|------------------------|
| 1 | **H2 / L2 Two-Legged Pullback** | 5 | Swing count algoritması ile tam mekanik; A=B dip oranı backtest edilebilir; engulfing'den bağımsız |
| 2 | **ii Breakout (Inside-Inside)** | 5 | Bar high/low oranı tam mekanik; OCO bracket ile otomasyon; trend filtresiyle çift güç |
| 3 | **TTR Breakout (Tight Trading Range)** | 5 | ATR bazlı range tespit + breakout bar koşulu; zaman-bağımsız; volatility cycle ile ilişkili |
| 4 | **Failed Breakout / Trap Reverse** | 5 | n-bar high/low aşımı + geri dönüş mekanik; trap mekaniği güçlü ve test edilmiş |
| 5 | **BO PB (Breakout Pullback)** | 5 | Breakout seviyesi + retrace oranı + sinyal bar tümü mekanik; measured move hedefi mekanik |

**Ek güçlü adaylar (skala 4):**
- H1/L1 (strong trend, AI filter gerekli)
- ii Failed Breakout Reverse (tamamen mekanik)
- Prior Day High/Low Test (PDH/PDL mekanik)
- Climactic Bar + First Pullback Entry
- Bar Range Contraction → Expansion

### Mevcut Engulfing Hipotezinden Dekorelasyon Notu

Mevcut sistem engulfing tabanlı hipotezleri test ediyor (büyük bar öncekini tamamen geçer). Yukarıdaki beş aday tamamen farklı mekanizmalar:
- H2/L2 = iki bacak sayısı (swing structure)
- ii = konsolidasyon + volatility compression
- TTR = range genişliği + ATR kontraksiyonu
- Failed BO = breakout failure detection
- BO PB = breakout + retrace oranı

Hiçbiri engulfing geometrisi kullanmaz. Her biri bağımsız hipotez oluşturabilir.

---

## Referans: Brooks Terminoloji Sözlüğü (Mekanik Eşlikler)

| Terim | Mekanik Tanım |
|-------|---------------|
| Always-In (AI) | Eğer pozisyon almak zorunda olsaydım hangi yöne girerdim |
| Strong trend | %60+ trend bar, 3+ HH/LL, fiyat EMA'nın trend yönünde |
| Weak trend | %40–60 trend bar, EMA yakınında, mixed bars |
| Two-way trading | AI belirsiz, doji cluster, EMA ±%0.3 |
| A-grade | Tüm filtreler hizalı (HTF, AI, bar quality, context) |
| B-grade | 1–2 zayıf filtre; yarı size |
| C-grade | Çatışan filtreler; pas geç |
| Signal bar | Setup'ı tetikleyen bar; entry stop'u bu bar'ın extreme'ine dayanır |
| Follow-through | Setup bar'ı takip eden konfirmasyon bar'ı |
| Scratch trade | Entry yakınında exit; ne kazanç ne kayıp |
| Scale out | Pozisyonu kademelerde kapatma (1R → 2R → trail) |
| Measured move | AB = CD veya leg repetition (aynı hareket tekrar) |
| Climactic bar | Range ≥ 2 × ATR; exhaustion sinyali |
| Trap | Failed breakout → ters yöne momentum |
| Channel | Paralel trendlines arası trend yapısı |
| Spike | Ardışık 3–7 güçlü trend bar; S&C'nin ilk fazı |
| Flag | Trend içi kısa karşı-trend konsolidasyon |
| HTF | Higher Time Frame; bias için kullanılan üst zaman dilimi |

---

*Kaynak: Al Brooks, "Reading Price Charts Bar by Bar" (2009); "Trading Price Action: Trends", "Trading Price Action: Trading Ranges", "Trading Price Action: Reversals" (2012). Bu doküman eğitim amaçlı RAG referansıdır; telif materyalin yerini tutmaz.*
