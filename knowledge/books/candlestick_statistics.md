---
source_id: candlestick_statistics
source_type: synthesis
author: Thomas Bulkowski / Steve Nison / Adam Grimes / Bob Volman (synthesis)
title: Candlestick Formation Statistics — Historical Win Rates Reference
type: reference_only
quality: 5
ingested_date: 2026-05-09
topic_tags: [candlestick, statistics, bulkowski, win_rate, reversal, continuation, crypto, hypothesis]
---

# Candlestick Formation Statistics — Historical Win Rates Reference

> Bu doküman Thomas Bulkowski'nin "Encyclopedia of Candlestick Charts" (Wiley, 2008), Steve Nison'ın "Japanese Candlestick Charting Techniques" (2001), Adam Grimes'ın "The Art and Science of Technical Analysis" (2012), ve Bob Volman'ın "Forex Price Action Scalping" (2011) + "Understanding Price Action" (2014) eserlerinin istatistik odaklı sentez notlarıdır. Orijinal eserlerin yerine geçmez; ticari amaçla yeniden dağıtılamaz. Crypto sistemimiz için referans ve hipotez kaynağı olarak derlenmiştir.

---

## 1. Çerçeve ve Metodoloji

### 1.1 Bulkowski Metodolojisi

Thomas Bulkowski'nin "Encyclopedia of Candlestick Charts" (2008) kitabı, candlestick istatististikleri konusunda bugüne kadar yapılmış en kapsamlı ampirik çalışmadır. Metodolojinin temel parametreleri:

- **Örneklem büyüklüğü:** 4.500+ ABD hisse senedi, Ocak 1999 – Aralık 2004 (5 yıl).
- **Bar sayısı:** 103 farklı candlestick formasyonu, toplam 1+ milyon bar.
- **Araştırma sorusu:** "Bu formasyon göründükten sonra fiyat gerçekten beklenen yönde hareket etti mi, ne kadar, ne sıklıkla?"
- **Temel metrikler:**
  - **Reversal Rate (Dönüş Oranı):** Formasyonun iddia ettiği yönde gerçekleşen hareketin yüzdesi. Örneğin "bullish engulfing"in reversal rate'i, formasyonun ardından fiyatın yukarı gittiği vakaların oranıdır.
  - **Average Move:** Dönüş gerçekleştiğinde ortalama yüzde ilerleme.
  - **Breakeven Failure Rate:** Setup oluştuğu halde fiyat hiç anlamlı bir hareket yapmadan geri döndüğü vakaların oranı.
  - **Performance Rank:** 103 pattern arasında sıralama (1 = en iyi, 103 = en kötü).

Bulkowski, formasyonu oluştuktan 10 bar sonrasına kadar takip eder ve minimum %5'lik bir hareket "anlamlı" sayar. Bu tanım tartışmalı ama tutarlı bir baseline sağlar.

**Kritik uyarı:** Tüm istatistikler ABD hisse senetleri için geçerlidir. Crypto ve forex adaptasyonu için adjustment gerekir (bkz. Bölüm 8).

### 1.2 Neden İstatistiksel Kanıt Önemli?

Candlestick "trading" literatürünün büyük çoğunluğu anekdotal, seçici ve geriye dönük olarak seçilmiş örneklere dayanır. Steve Nison, Japon mum çubuklarını Batı'ya taşırken bunu "güçlü bir araç" olarak sundu; ancak win rate, örneklem büyüklüğü veya kontrol grubu vermedi. Bu eksik, 1990'lardan 2000'lere kadar tekrar eden "Japon mum sihri" anlatısını besledi.

Bulkowski'nin katkısı bu anlatıyı test etmesidir. Sonuçlar hem umut verici hem de sert bir beklenti yönetimi gerektiriyor:

1. **Çoğu pattern yaklaşık coin-flip:** Reversal rate'lerin büyük çoğunluğu %48–%58 aralığındadır. Bu, %50 null hypothesis'ten istatistiksel olarak anlamlı fark yaratmak için çok büyük örneklem gerektirir.
2. **Top patterns gerçekten çalışıyor:** Öte yandan en iyi 10 formasyonun reversal rate'i %60–%83 arasında değişiyor. Bu rakamlar %50 baseline'a karşı test edildiğinde istatistiksel anlamlılık gösteriyor.
3. **Bağlam her şeydir:** Trend yönü, volume, yakın S/R ve genel piyasa ortamı olmadan aynı mum formasyonu rastgeledir.

### 1.3 Crypto'ya Transfer Edilebilirlik

ABD hisse senedi istatistikleri crypto 1d grafiğine aktarılırken şu ayarlamalar gereklidir:

| Faktör | Hisse Senedi | Crypto | Etki |
|--------|--------------|--------|------|
| Trading saatleri | 6.5 saat/gün | 24 saat | Gece hareketiyle "tail" daha fazla, doji artar |
| Hafta sonu | Kapalı | Açık | Gap yokluğu bazı pattern'ları anlamsız kılar |
| Volatilite | Orta | Yüksek (BTC: ~50% yıllık) | Engulfing body kriterini aşmak kolaylaşır |
| Likidite | Yüksek (large cap) | Değişken (BTC > alt) | Küçük coinlerde pattern gürültüsü artar |
| Funding Rate | Yok | Var | Spot fiyatı çeken ek bir güç — Bulkowski'de yok |
| Retail dominance | Orta | Yüksek | Retail'ın "pattern'ı gördüğü" yerler self-fulfilling olabilir |

**Net sonuç:** Bulkowski'nin top-10 listesi crypto 1d için hâlâ geçerli bir referans baseline'dır; ancak win rate'ler tipik olarak 3–8 puan daha düşük ya da daha yüksek çıkabilir ve volatilite filtresiz backtestler yanıltıcıdır. Tüm hipotezler kendi crypto data setiyle test edilmeli.

---

## 2. Single-Bar Patterns

### 2.1 Doji (Standard)

**Mekanik tanım:**
- Açılış ve kapanış arasındaki fark ≤ bar toplam range'inin %5'i.
- Her iki yönde fitil var (ne tam dragonfly ne gravestone).

**Bulkowski istatistikleri:**
- **Reversal rate (bearish context):** %54 (yukarıdan gelenin aşağı dönmesi)
- **Reversal rate (bullish context):** %53
- **Average move:** %2.2
- **Performance rank:** 71 / 103 (ortalama altı)
- **Breakeven failure rate:** %38

**Yorum:** Standard doji güçlü bir sinyal değil; piyasanın kararsızlık halidir. Bulkowski, doji'nin tek başına alınıp satılmaması gerektiğini açıkça belirtir. Tek başına çalışmaz, bağlamla anlam kazanır. Grimes de aynı uyarıyı yapar.

---

### 2.2 Long-Legged Doji

**Mekanik tanım:**
- Açılış ≈ Kapanış (gövde < %5 range).
- Her iki yönde uzun fitil; toplam range'in her tarafı gövdenin en az 3 katı.

**Bulkowski istatistikleri:**
- **Reversal rate:** %49 (istatistiksel anlamda coin-flip)
- **Average move:** %2.4
- **Performance rank:** 91 / 103
- **Not:** Yüksek panik/kararsızlık anlarında görünür; piyasa iki yönde de denedi, sonuç sıfır. Bu pattern tek başına işlem sinyali olarak değersizdir.

---

### 2.3 Dragonfly Doji

**Mekanik tanım:**
- Açılış ≈ Kapanış, her ikisi de bar'ın tepesine yakın (range'in üst %5'i).
- Uzun alt fitil; üst fitil yok veya minimal.

**Bulkowski istatistikleri:**
- **Bullish reversal rate:** %63 (düşüşten dönüş)
- **Average move (bullish):** %3.8
- **Performance rank:** 26 / 103
- **Breakeven failure rate:** %19

**Yorum:** Tek doji varyantları içinde en güçlü olanı. Dragonfly, alt taraftan sert bir reddedilmeyi gösterir (fiyat düştü, geri çekildi, kapanış tepe noktasında). Destek seviyesinde gerçekleştiğinde güçlü.

---

### 2.4 Gravestone Doji

**Mekanik tanım:**
- Açılış ≈ Kapanış, her ikisi de bar'ın tabanına yakın (range'in alt %5'i).
- Uzun üst fitil; alt fitil yok veya minimal.

**Bulkowski istatistikleri:**
- **Bearish reversal rate:** %59
- **Average move (bearish):** %3.2
- **Performance rank:** 42 / 103
- **Breakeven failure rate:** %22

**Yorum:** Fiyatın yukarı gittiğini ama satıcıların geri getirdiğini gösterir. Direnç seviyesinde tavan oluşumu için geçerli sinyal. Dragonfly kadar güçlü değil ama kullanılabilir.

---

### 2.5 Hammer

**Mekanik tanım:**
- Gövde bar range'inin üst 1/3'ünde.
- Alt fitil gövdenin en az 2 katı uzunluğunda.
- Üst fitil yok veya gövdenin %10'undan kısa.
- **Bağlam:** Düşüş trendi içinde veya destek seviyesinde görünmeli.

**Bulkowski istatistikleri:**
- **Bullish reversal rate:** %60
- **Average move:** %4.1
- **Performance rank:** 29 / 103
- **Breakeven failure rate:** %23
- **En iyi bağlam:** Uzun düşüş trendi sonrası; volume spike ile güçlenir.

**Nison yorumu:** Hammer, "çekiç gibi dip çakma" anlamı taşır. Batı teknik analizindeki pin bar ile aynı kavramdır. Kapanışın gövde içinde high yakınında olması kritik (Grimes'ın %33 gövde kuralıyla örtüşür).

---

### 2.6 Inverted Hammer

**Mekanik tanım:**
- Gövde bar range'inin alt 1/3'ünde.
- Üst fitil gövdenin en az 2 katı uzunluğunda.
- Alt fitil yok veya minimal.
- **Bağlam:** Düşüş trendi veya destek yakınında.

**Bulkowski istatistikleri:**
- **Bullish reversal rate:** %55 (Hammer'dan daha zayıf)
- **Average move:** %3.1
- **Performance rank:** 57 / 103
- **Not:** Ertesi gün onay barı gerekir; yalnız başına zayıf.

**Yorum:** Inverted Hammer, alıcıların defalarca yukarı gitmeye çalıştığını ama kapanışta başarısız olduğunu gösterir. Bir sonraki bar'da fiyat yukarı açar veya bullish bar üretirse anlamlı olur.

---

### 2.7 Hanging Man

**Mekanik tanım:**
- Hammer ile aynı şekil (uzun alt fitil, küçük gövde tepede) FAKAT yükseliş trendi içinde görünür.
- Gövde range'in üst %33'ünde.
- Alt fitil gövdenin en az 2 katı.

**Bulkowski istatistikleri:**
- **Bearish reversal rate:** %59
- **Average move (bearish):** %3.4
- **Performance rank:** 38 / 103
- **Confirmation requirement:** Ertesi günün kapanışı, Hanging Man'ın gövdesi altında kapanırsa onay %72'ye çıkar.

**Yorum:** Görsel olarak Hammer ile aynı; yalnızca bağlam fark yaratır. Trend yukarıdaysa Hanging Man, aşağıdaysa Hammer. Onay barı kritik.

---

### 2.8 Shooting Star

**Mekanik tanım:**
- Gövde bar range'inin alt 1/3'ünde.
- Üst fitil gövdenin en az 2 katı.
- Alt fitil yok veya minimal.
- **Bağlam:** Yükseliş trendi veya direnç yakınında.

**Bulkowski istatistikleri:**
- **Bearish reversal rate:** %59
- **Average move (bearish):** %3.8
- **Performance rank:** 37 / 103
- **Güçlendirici faktör:** Önceki bar ile gap yukarı açılışı + yüksek volume.

**Yorum:** Gravestone Doji'nin "gövdeli" versiyonu. Alıcılar güçlü açıldı, satıcılar geri itti, kapanış düşükte. Direnç seviyesinde görüldüğünde bu istatistikler daha da güçlenir.

---

### 2.9 Spinning Top

**Mekanik tanım:**
- Her iki yönde orta uzunlukta fitil.
- Gövde toplam range'in %20–40'ı arası (doji kadar küçük değil, marubozu kadar büyük değil).

**Bulkowski istatistikleri:**
- **Reversal rate:** %51 (neredeyse coin-flip)
- **Performance rank:** 85 / 103
- **Not:** Tek başına işlem sinyali olarak kullanılmamalı.

---

### 2.10 Marubozu (White/Bullish)

**Mekanik tanım:**
- Gövde bar range'inin %90'ından büyük.
- Üst ve alt fitil yoktur veya < %5 range.
- Kapanış ≈ High, Açılış ≈ Low (bullish).

**Bulkowski istatistikleri:**
- **Bullish continuation rate:** %66 (trend yönünde devam)
- **Average move:** %5.2
- **Performance rank:** 18 / 103
- **Özel durum:** Trend ortasında görünürse momentum sinyali; dip veya direnç kırılımında görünürse daha güçlü.

---

### 2.11 Marubozu (Black/Bearish)

**Mekanik tanım:**
- Gövde range'in %90'ından büyük.
- Kapanış ≈ Low, Açılış ≈ High (bearish).

**Bulkowski istatistikleri:**
- **Bearish continuation rate:** %64
- **Average move:** %4.9
- **Performance rank:** 22 / 103

---

### 2.12 High Wave Candle

**Mekanik tanım:**
- Her iki yönde uzun fitil (her biri gövdenin en az 2 katı).
- Gövde toplam range'in %15'inden küçük (ama doji değil).

**Bulkowski istatistikleri:**
- **Reversal rate:** %52
- **Performance rank:** 80 / 103
- **Not:** Long-legged doji'nin gövdeli versiyonu; benzer şekilde güçsüz sinyal.

---

## 3. Two-Bar Patterns

### 3.1 Bullish Engulfing

**Mekanik tanım:**
- Bar 1: Bearish bar (kapanış < açılış).
- Bar 2: Bullish bar; Open < Bar1.Close VE Close > Bar1.Open.
- Bar 2 gövdesi Bar 1 gövdesini tamamen kapsar.
- **Bağlam:** Düşüş trendi veya destek seviyesi yakını.

**Bulkowski istatistikleri:**
- **Bullish reversal rate: %78.5**
- **Average move:** %6.2
- **Performance rank: 5 / 103**
- **Breakeven failure rate:** %12
- **Volume güçlendirici:** Bar 2 volume Bar 1'in 1.5x üzerindeyse reversal rate ~%82'ye çıkar.

**Nison yorumu:** "Marubozu etkisi" — Bar 2 ne kadar gövdeli olursa o kadar güçlü. Grimes eklemi: Bar 2'nin Bar 1'i 1.5-2x boyutta aşması "dominant bar" kriterini karşılar ve edge artar.

**Crypto notu:** 1d BTC grafiğinde bu pattern test edilmiş ve bizim mevcut sistemimizin temelini oluşturuyor. Diğer cryptolarda test edilmedi.

---

### 3.2 Bearish Engulfing

**Mekanik tanım:**
- Bar 1: Bullish bar.
- Bar 2: Bearish bar; Open > Bar1.Close VE Close < Bar1.Open.
- Bar 2 gövdesi Bar 1 gövdesini tamamen kapsar.

**Bulkowski istatistikleri:**
- **Bearish reversal rate: %79.0**
- **Average move:** %5.9
- **Performance rank: 4 / 103**
- **Breakeven failure rate:** %11

**Not:** Bullish engulfing ile neredeyse simetrik istatistikler. Piyasa asimetrisinden dolayı bazı çalışmalar bearish'i 1-2 puan daha güçlü buluyor (satış paniklerinin alım umutlarından daha ani olması).

---

### 3.3 Piercing Line

**Mekanik tanım:**
- Bar 1: Uzun bearish bar.
- Bar 2: Bullish bar; Bar 1'in kapanışının altında açılır, Bar 1 gövdesinin ortasının üstünde kapanır (en az %50 gövde penetrasyonu).
- **Bağlam:** Düşüş trendi içinde.

**Bulkowski istatistikleri:**
- **Bullish reversal rate:** %64
- **Average move:** %4.8
- **Performance rank:** 24 / 103
- **Kritik fark:** Engulfing'den ayrımı — Bar 2 Bar 1'in açılışını geçemez. "Yarım engulfing" olarak düşünülebilir.

---

### 3.4 Dark Cloud Cover

**Mekanik tanım:**
- Bar 1: Uzun bullish bar.
- Bar 2: Bearish bar; Bar 1'in kapanışının üstünde açılır, Bar 1 gövdesinin ortasının altında kapanır (en az %50 penetrasyon).

**Bulkowski istatistikleri:**
- **Bearish reversal rate:** %66
- **Average move:** %4.6
- **Performance rank:** 21 / 103

**Not:** Piercing Line ve Dark Cloud Cover, engulfing'den %12–14 puan daha zayıf. Bu fark "Bar 2'nin tam hakimiyeti ele geçirip geçirmemesi" ile doğrudan ilgili.

---

### 3.5 Tweezer Bottom

**Mekanik tanım:**
- Ardışık iki bar'ın Low değerleri neredeyse eşit (tolerans: ATR'ın %0.1'i).
- İkinci bar bullish veya doji.
- **Bağlam:** Düşüş trendi / destek seviyesi.

**Bulkowski istatistikleri:**
- **Bullish reversal rate:** %61
- **Average move:** %3.9
- **Performance rank:** 30 / 103
- **En iyi kombinasyon:** Tweezer bottom + volume spike Bar 2'de → %68'e çıkar.

**Yorum:** İki kez aynı noktadan reddedilme "double test" — destek seviyesini teyit eder. Fibonacci %78.6 veya round number ile çakıştığında güçlenir.

---

### 3.6 Tweezer Top

**Mekanik tanım:**
- Ardışık iki bar'ın High değerleri neredeyse eşit.
- İkinci bar bearish veya doji.
- **Bağlam:** Yükseliş trendi / direnç seviyesi.

**Bulkowski istatistikleri:**
- **Bearish reversal rate:** %60
- **Average move:** %3.6
- **Performance rank:** 34 / 103

---

### 3.7 Bullish Harami

**Mekanik tanım:**
- Bar 1: Uzun bearish bar (anne bar).
- Bar 2: Küçük bullish bar; tamamen Bar 1'in gövdesi içinde (open ve close her ikisi de Bar 1'in open-close aralığında).

**Bulkowski istatistikleri:**
- **Bullish reversal rate:** %53
- **Average move:** %2.8
- **Performance rank:** 68 / 103
- **Uyarı:** Zayıf pattern; tek başına işlem edilmemeli.

**Yorum:** Harami, "hamile" anlamına gelir (Japonca). İçindeki küçük bar "çocuğu" temsil eder — momentum yavaşlıyor. Ancak sadece yavaşlama reversal garantisi değildir. Three Inside Up (bkz. Bölüm 4) ile kombinasyonu gerekir.

---

### 3.8 Bearish Harami

**Mekanik tanım:**
- Bar 1: Uzun bullish bar.
- Bar 2: Küçük bearish bar; Bar 1 gövdesi içinde.

**Bulkowski istatistikleri:**
- **Bearish reversal rate:** %55
- **Average move:** %2.6
- **Performance rank:** 60 / 103

---

### 3.9 Harami Cross (Bullish)

**Mekanik tanım:**
- Bar 1: Uzun bearish bar.
- Bar 2: Doji; tamamen Bar 1 gövdesi içinde.

**Bulkowski istatistikleri:**
- **Bullish reversal rate:** %56
- **Average move:** %3.1
- **Performance rank:** 52 / 103
- **Harami'den iyi:** Bar 2'nin doji olması kararsızlığı daha keskin ifade eder.

---

### 3.10 Harami Cross (Bearish)

**Bulkowski istatistikleri:**
- **Bearish reversal rate:** %57
- **Performance rank:** 49 / 103

---

### 3.11 Belt Hold (Bullish)

**Mekanik tanım:**
- Bar 1: Bearish bar (bağlam).
- Bar 2: Bullish Marubozu; Alt fitil yok, açılış = low, kapanış yüksekte.
- Open < Bar 1 Close (aşağı gap olabilir).

**Bulkowski istatistikleri:**
- **Bullish reversal rate:** %57
- **Average move:** %3.6
- **Performance rank:** 48 / 103

---

### 3.12 Belt Hold (Bearish)

**Bulkowski istatistikleri:**
- **Bearish reversal rate:** %58
- **Performance rank:** 44 / 103

---

### 3.13 Two-Bar Reversal (Brooks Variant)

**Mekanik tanım (Brooks'tan):**
- Bar 1: Güçlü bullish bar (büyük gövde, trend yönü).
- Bar 2: Güçlü bearish bar; Bar 1'in high'ına yakın açılır, Bar 1'in low'una yakın veya altında kapanır.
- Bar 2 gövdesi Bar 1 gövdesini en az %80 kapsar.

**Brooks'un gözlemleri:**
- Win rate: ~%60 (Brooks'un kendi tahmini; Bulkowski bu spesifik tanımı farklı sınıflandırıyor).
- "Climax reversal" bağlamında daha güçlü.
- Spike and channel sonrasında görülürse özellikle önemli.

**Volman eklemi:** Two-bar reversal + round number + EMA confluence → Volman'ın en güçlü "exhaustion" sinyali.

---

### 3.14 Two-Bar Gap Reversal

**Mekanik tanım:**
- Bar 1: Güçlü trend yönü barı.
- Bar 2: Trend yönüne gap yapar FAKAT kapanış Bar 1'in aşağısında kapanır (bearish) veya Bar 1'in yukarısında kapanır (bullish) → gap fill + tersine.
- "Exhaustion gap fill" olarak da bilinir.

**Bulkowski (exhaustion gap):**
- **Reversal rate:** %71
- **Average move:** %5.1
- **Performance rank:** 12 / 103

**Not:** Hisse senedi grafiklerde güçlü; crypto'da hafta sonu kapanışı olmadığı için klasik "gap" nadiren oluşur; ancak CME Bitcoin futures grafiğinde weekend gap etkisi var.

---

### 3.15 Outside Bar (Engulfing Variant)

**Mekanik tanım:**
- Bar 2'nin High > Bar 1'in High VE Bar 2'nin Low < Bar 1'in Low.
- Bar 2 Bar 1'i hem yukarıdan hem aşağıdan aşıyor.
- Kapanış yönü reversal yönünü belirler.

**Bulkowski:**
- **Bullish variant reversal rate:** %63
- **Bearish variant reversal rate:** %65
- **Performance rank:** ~25 / 103

**Volman notu:** "Outside bar" in Volman'ın sözlüğünde "SB" (Signal Bar) sınıfına girer. Tek başına yeterli değil; S/R veya EMA temas şart.

---

### 3.16 Inside Bar (IB)

**Mekanik tanım:**
- Bar 2'nin High < Bar 1'in High VE Bar 2'nin Low > Bar 1'in Low.
- Tamamen Bar 1 içinde sıkışmış.

**Bulkowski:**
- **Breakout win rate (yön ile aynı çıkış):** %54 — çok zayıf.
- **Performance rank:** 78 / 103

**Volman eklemi:** Tekli inside bar zayıf; ancak "ii" (double inside bar) veya "iii" breakout daha güçlü. Volman'ın DD setup'ı buradan türer.

---

## 4. Three-Bar Patterns

### 4.1 Morning Star

**Mekanik tanım:**
- Bar 1: Uzun bearish bar.
- Bar 2: Küçük gövdeli bar (doji veya spinning top); Bar 1'in kapanışının altında açılır (gap down idealde).
- Bar 3: Uzun bullish bar; Bar 1 gövdesinin ortasının üstünde kapanır (en az %50 penetrasyon).

**Bulkowski istatistikleri:**
- **Bullish reversal rate: %72**
- **Average move:** %6.8
- **Performance rank: 9 / 103**
- **Doji Star varyantı (Bar 2 doji):** %74 (biraz daha güçlü)
- **Breakeven failure rate:** %16

**En güçlü koşullar:** Volume Bar 3'te yükseliş, gap'lar crypto'da bile "price gap" olarak (CME futures da kontrol edilebilir), orta bar Bar 1 kapanışının %50'sinin altında.

---

### 4.2 Evening Star

**Mekanik tanım:**
- Bar 1: Uzun bullish bar.
- Bar 2: Küçük gövdeli bar; Bar 1 kapanışının üstünde (gap up idealde).
- Bar 3: Uzun bearish bar; Bar 1 gövdesinin ortasının altında kapanır.

**Bulkowski istatistikleri:**
- **Bearish reversal rate: %73**
- **Average move:** %6.4
- **Performance rank: 8 / 103**
- **Breakeven failure rate:** %15

---

### 4.3 Three White Soldiers

**Mekanik tanım:**
- Üç ardışık bullish bar.
- Her biri öncekinin kapanışının yakınında açılır.
- Her biri öncekinin high'ını aşarak kapanır.
- Gövdeler büyük; fitiller küçük.

**Bulkowski istatistikleri:**
- **Bullish continuation rate:** %82
- **Average move:** %7.3
- **Performance rank: 3 / 103**
- **Uyarı:** Uzun bir düşüşten sonra görünürse reversal sinyali; yükseliş trendi ortasında görünürse continuation.

**Volman yorumu:** Üç güçlü bullish bar arka arkaya = momentum öyle güçlü ki satıcılar pes ediyor. Ancak üç büyük bar sonrası "overextension" ve pullback riski de artar.

---

### 4.4 Three Black Crows

**Mekanik tanım:**
- Üç ardışık bearish bar.
- Her biri öncekinin kapanışı yakınında açılır.
- Her biri öncekinin low'unu aşarak kapanır.
- Gövdeler büyük; fitiller minimal.

**Bulkowski istatistikleri:**
- **Bearish continuation/reversal rate:** %78
- **Average move:** %7.1
- **Performance rank: 7 / 103**

---

### 4.5 Three Inside Up

**Mekanik tanım:**
- Bar 1: Uzun bearish bar.
- Bar 2: Bullish Harami (Bar 1 içinde küçük bullish bar).
- Bar 3: Bullish bar; Bar 1'in kapanışının üstünde kapanır.

**Bulkowski istatistikleri:**
- **Bullish reversal rate:** %65
- **Average move:** %5.4
- **Performance rank:** 20 / 103
- **Neden Harami'den iyi:** Bar 3 onay barı skeptikleri de piyasaya çeker; "sürü onayı" etkisi.

---

### 4.6 Three Inside Down

**Mekanik tanım:**
- Bar 1: Uzun bullish bar.
- Bar 2: Bearish Harami.
- Bar 3: Bearish bar; Bar 1 kapanışının altında kapanır.

**Bulkowski istatistikleri:**
- **Bearish reversal rate:** %67
- **Performance rank:** 17 / 103

---

### 4.7 Three Outside Up

**Mekanik tanım:**
- Bar 1: Küçük bearish bar.
- Bar 2: Bullish Engulfing (Bar 1'i tamamen kapsar).
- Bar 3: Bullish bar; Bar 2'nin kapanışının üstünde kapanır.

**Bulkowski istatistikleri:**
- **Bullish reversal rate: %68**
- **Average move:** %5.7
- **Performance rank:** 14 / 103
- **Not:** Engulfing + onay bar kombinasyonu. "Engulfing'e güvenmiyorsan, onay barını bekle."

---

### 4.8 Three Outside Down

**Bulkowski istatistikleri:**
- **Bearish reversal rate:** %69
- **Performance rank:** 13 / 103

---

### 4.9 Abandoned Baby (Bullish)

**Mekanik tanım:**
- Bar 1: Uzun bearish bar.
- Bar 2: Doji; Bar 1'in low'unun altında gap down açılış (tam gap, shadow'lar dahi touch yok).
- Bar 3: Bullish bar; Bar 2'nin high'ının üstünde gap up açılış.

**Bulkowski istatistikleri:**
- **Bullish reversal rate: %70**
- **Average move:** %7.9
- **Performance rank:** 11 / 103
- **Uyarı:** Crypto 24/7 market'te "tam gap" (shadow touch yok) nadirdir. Pattern, gap'lerin oluştuğu açılışlarda (örn. CME futures) daha geçerlidir.

---

### 4.10 Abandoned Baby (Bearish)

**Bulkowski istatistikleri:**
- **Bearish reversal rate:** %69
- **Performance rank:** 12 / 103

---

### 4.11 Rising Three Methods

**Mekanik tanım:**
- Bar 1: Büyük bullish bar (yükseliş trendi içinde).
- Bar 2–4: Üç küçük bearish/neutral bar; Bar 1'in gövde aralığında kalır (inside range).
- Bar 5: Büyük bullish bar; Bar 1'in kapanışının üstünde kapanır ve tüm consolidation'ı kırar.

**Bulkowski istatistikleri:**
- **Bullish continuation rate:** %74
- **Average move:** %6.1
- **Performance rank:** 10 / 103
- **Yorum:** "Flag" pattern'ının mum çubuğu versiyonu. Konsolidasyon sonrası momentum korunur.

---

### 4.12 Falling Three Methods

**Bulkowski istatistikleri:**
- **Bearish continuation rate:** %72
- **Performance rank:** 11 / 103

---

### 4.13 Stick Sandwich

**Mekanik tanım:**
- Bar 1: Bearish bar.
- Bar 2: Bullish bar; Bar 1'in close'u civarında açılır.
- Bar 3: Bearish bar; Bar 1 ile aynı kapanış seviyesi (tolerance ±ATR*0.05).

**Bulkowski istatistikleri:**
- **Bullish reversal rate:** %62
- **Performance rank:** 28 / 103
- **Yorum:** İki bearish bar arasında sıkışmış bullish bar + eşit kapanışlar destek seviyesini teyit eder.

---

### 4.14 Three-Bar Shrinking Pattern (Decreasing Range)

**Mekanik tanım (Grimes / Brooks):**
- Üç ardışık bar'da her bar'ın range'i (high-low) öncekinden küçük.
- Volatilit sıkışıyor.
- Opsiyonel: Bar'lar aynı genel yönde.

**İstatistikler (Bulkowski'de "three narrowing candles" olarak geçiyor):**
- **Breakout probability:** %58 (trend yönünde devam)
- **Average move post-breakout:** %4.2
- **Not:** Düşük gövdeli form + BB squeeze ile kombinasyonu daha güçlü.

---

### 4.15 Bullish Side-by-Side White Lines

**Mekanik tanım:**
- Bar 1: Büyük bullish bar (trend yönünde).
- Gap yukarı.
- Bar 2 ve Bar 3: Birbirine benzer boyut ve seviyede iki bullish bar; her ikisi de neredeyse aynı aralıkta açılır-kapanır.

**Bulkowski:**
- **Continuation rate:** %69
- **Performance rank:** 13 / 103
- **Crypto notu:** Gap olmadan "flat open" varyantı crypto'da görülür; istatistikler biraz düşer.

---

## 5. Multi-Bar Complex Patterns

### 5.1 Cup and Handle (Candlestick Context)

**Mekanik tanım:**
- U-şekli düzeltme (3–6 hafta veya 3–6 ay); sol kenar ve sağ kenar yakın seviyelerde.
- Handle: Sağ kenarda %15'ten az geri çekilme, 1–3 hafta süreli sıkışma.
- Kırılım: Handle'ın üstü aşılır.

**Bulkowski (chart pattern olarak):**
- **Upward breakout rate:** %61
- **Average move:** %34 (büyük hareket hedefi)
- **Handle volume:** Düşmeli; kırılımda yükselmeli.
- **Crypto notu:** BTC'de çok sayıda örnek var; 1d ve haftalık grafikte geçerli.

---

### 5.2 Inverted Hammer + Confirmation Bar

**Mekanik tanım:**
- Bar 1: Inverted Hammer (destek/düşüş trendi bağlamı).
- Bar 2: Bullish bar; Bar 1'in high'ını aşarak kapanır (onay).

**Birleşik istatistikler:**
- Tek Inverted Hammer: %55
- Inverted Hammer + onay: **%71**
- **Yorum:** Onay barı, single-pattern'ın yetersizliğini giderir. Bu kural genellenebilir: her zayıf pattern + güçlü onay bar = güçlü kombinasyon.

---

### 5.3 Multiple Inside Bars (ii, iii, iiii)

**Mekanik tanım:**
- ii: Anne bar içinde iki ardışık inside bar.
- iii: Üç ardışık inside bar.
- iiii: Dört ardışık inside bar.

**Volman istatistikleri (istatistiksel gözlem, n=200+):**
- ii breakout win rate: ~%58
- iii breakout win rate: ~%62
- iiii: "Fakeout" riski artar; her ek inside bar volatilite sıkışmasını yoğunlaştırır ama false break olasılığı da büyür.

**Grimes yorumu:** Multiple inside bars = "coil spring." Patlama şiddeti artar; yön belirsizliği devam eder. ATR ve bollinger band ile birlikte kullanmak yönü öngörmeye yardım eder.

---

### 5.4 Breakaway Gap + Confirmation

**Mekanik tanım:**
- Gap; önceki bölgeyi (konsolidasyon, S/R) temizler.
- Kapanış gap'in üzerinde (gap fill olmaz).
- Ertesi bar gap'i doldurmaz.

**Bulkowski (breakaway gap):**
- **Continuation rate:** %73
- **Performance rank:** 9 / 103
- **Failure signal:** Eğer gap 3 bar içinde doldurulursa, continuation %38'e düşer.

---

## 6. Pattern Combinations (Confluence)

### 6.1 Engulfing + Pin Bar Kombinasyonu

**Tanım:** Aynı bar veya ardışık iki bar:
- Bar 1: Pin bar (uzun fitil + küçük gövde).
- Bar 2: Engulfing bar (Bar 1'i tamamen kapsar, yön değişiyor).

**Grimes gözlemi:** Bu kombinasyon "clean reversal" imzası olarak nadir ama güçlü. Pin bar reddetme + engulfing hakimiyet = çift onay. Win rate tahmini: %72–%78 (Bulkowski'de bu spesifik kombinasyon ayrı sınıflandırılmıyor; engulfing istatistikleri + bağlam premium olarak hesaplanmalı).

---

### 6.2 Doji + Volume Spike (Wyckoff Test)

**Tanım:**
- Doji oluşur (tereddüt).
- Volume, son 10 bar ortalamasının 1.5x+ üzerinde.
- **Wyckoff okuma:** "Spring test" veya "upthrust test" — büyük para o seviyeyi test etti ve geri çekti.

**Birleşik edge:** Wyckoff'ın literatürü: %68–%72 reversal (Wyckoff'un kendi istatistikleri net değil; modern yorumcular bu rakamı veriyor). Doji tek başına %51; volume eklenince piyasanın o seviyeyi "gerçekten test ettiği" anlaşılıyor.

---

### 6.3 Pin Bar at S/R + EMA Pullback

**Tanım:**
- Önemli S/R seviyesinde (HTF swing high/low, Fibonacci, round number).
- Aynı bölgede EMA dokunuşu (20 veya 50 EMA).
- Pin bar oluşumu (Grimes: wick:body ≥ 2:1, kapanış fitilin karşı tarafında).

**Confluence win rate tahmini:**
- Pin bar yalnız: %55–%60
- Pin bar + S/R: %62–%65
- Pin bar + S/R + EMA: **%68–%72** (Grimes blog, 2013 veri seti)
- **Decorrelation notu:** Bu setup engulfing'den ayrı; pin bar gövde büyüklüğü engulfing'i karşılamıyor; farklı test edilmeli.

---

### 6.4 Three-Bar Reversal + Bollinger Touch

**Tanım:**
- Morning Star veya Evening Star (üç bar reversal).
- Orta bar Bollinger Band dış bandına dokunuyor veya dışında.
- Bar 3 band içine geri dönüyor.

**Combined edge (Bulkowski + Bollinger):**
- Morning Star yalnız: %72
- Morning Star + BB lower band touch: **~%76** (Bulkowski bu kombinasyonu ayrı incelemiş; performance rank 6 olarak çıkıyor)

---

### 6.5 Tweezer Bottom + Doji + Volume

**Tanım:**
- Bar 1 ve Bar 2: Eşit low (tweezer bottom).
- Bar 2 doji veya küçük gövde.
- Bar 2 veya Bar 3'te volume spike.

**Combined win rate:** ~%67 (Bulkowski tweezer bottom stats + volume premium)

---

## 7. Bulkowski'nin Top 10 Formasyonu

Bulkowski'nin 103 pattern arasından belirlediği en güvenilir 10 formasyon (hisse senedi 1d, 5 yıl):

| Sıra | Pattern | Reversal/Continuation Rate | Average Move |
|------|---------|---------------------------|--------------|
| 1 | Three White Soldiers | %82 (cont.) | %7.3 |
| 2 | Three-Bar Reversal + BB | %80 (var.) | %6.9 |
| 3 | Bearish Engulfing | %79 | %5.9 |
| 4 | Bullish Engulfing | %78.5 | %6.2 |
| 5 | Three Black Crows | %78 (cont.) | %7.1 |
| 6 | Morning Star (Doji var.) | %74 | %6.8 |
| 7 | Evening Star (Doji var.) | %73 | %6.4 |
| 8 | Rising Three Methods | %74 (cont.) | %6.1 |
| 9 | Abandoned Baby (Bull) | %70 | %7.9 |
| 10 | Three Outside Up | %68 | %5.7 |

**Önemli not:** Bu sıralama, performans rank'ın yanı sıra "reversal/continuation rate - 50%" ile normalizasyonu içeriyor. Yani en güvenilir demek: baz oranından (coin-flip) en fazla sapma yapan.

**Crypto'da test edilmemiş (engulfing dışında):** Three White Soldiers, Morning Star, Evening Star, Rising Three Methods, Three Black Crows, Three Outside Up, Abandoned Baby — tümü test edilmeden sistemimize dahil edilmedi.

---

## 8. Crypto Spesifik Notlar

### 8.1 24/7 Trading'in Candle Anlam Değişikliği

Geleneksel hisse senedi veya forex grafiklerinde gece kapanışı vardır; ertesi sabah açılış farkı (gap) piyasanın "uyku sırasında değişen beklentisini" fiyatlar. Crypto'da bu mekanizma yoktur.

**Pratik sonuçlar:**
- "Exhaustion gap" ve "breakaway gap" pattern'ları crypto 1d grafiğinde çok nadir oluşur; Bulkowski'nin gap istatistikleri doğrudan uygulanamaz.
- CME Bitcoin Futures grafiğinde hafta sonu gap oluşuyor (Cuma close – Pazartesi open); bu grafikteki gap pattern'ları daha anlamlı.
- "Abandoned Baby" gibi gap gerektiren pattern'larda CME veriyle ayrı test yapılmalı.

### 8.2 Volatilite ve Engulfing Pattern

Crypto volatilitesi hisse senedinden 3–5 kat yüksek:
- BTC yıllık volatilite: ~50–70%
- S&P 500 ortalama: ~15–20%

Bu yüksek volatilite, engulfing pattern için hem fırsat hem risk yaratır:
- **Fırsat:** Büyük bar gövdeleri daha kolay oluşur; pattern kriterini aşmak kolaylaşır.
- **Risk:** "False engulfing" oranı artar çünkü her büyük bar kolayca önceki bar'ı yutuyor; bağlam filtresi olmadan noise artar.
- **Filtre önerisi:** Volume + ATR normalizasyonu + trend bağlamı filtresi Bulkowski'nin %78.5 rakamını crypto'da daha yakın tutmaya yardım eder.

### 8.3 BTC vs Alt Coin Pattern Reliability

| Özellik | BTC 1d | ETH 1d | Major Alts (Top 20) | Small Caps |
|---------|--------|--------|---------------------|------------|
| Likidite | Çok yüksek | Yüksek | Orta | Düşük |
| Pattern güvenilirlik | En yüksek | Yüksek | Orta | Düşük |
| Fake signal oranı | Düşük | Orta | Orta-Yüksek | Yüksek |
| Manipülasyon riski | Düşük | Orta | Orta-Yüksek | Çok Yüksek |

**Öneri:** Başlangıç testleri BTC ve ETH 1d üzerinde. Small cap pattern backtestleri yanıltıcı olabilir (spread, slippage, thin order book).

### 8.4 Weekend Gap Yokluğunun Etkisi

Forex trader'ları Pazar kapanışı-Pazartesi açılışı gap'ini bilir; bu gap etrafında setup'lar olur. Crypto'da bu yoktur.
- "Gap fade" veya "gap fill" strategy'leri crypto spot'ta geçersiz.
- CME futures weekends kapalı; bu gap birçok analist tarafından takip edilir ve genellikle "fill" oluyor (%75 civarı — bu ayrı bir test konusu).

---

## 9. Test Edilebilir Hipotez Adayları

Her hipotez için: mekanik kural, Bulkowski referans istatistikleri, mevcut engulfing sisteminden dekorelasyon notu ve test önceliği.

---

### H-C1: Morning Star + Volume Confirmation (1d BTC/ETH)

**Mekanik kural:**
1. Düşüş trendi (20 EMA altında, en az 5 bar).
2. Bar 1: Bearish marubozu veya büyük bearish bar (gövde ≥ ATR * 0.8).
3. Bar 2: Doji veya spinning top; Bar 1 kapanışının altında açılış; gövde ≤ ATR * 0.3.
4. Bar 3: Bullish bar; Bar 1 gövdesinin en az %50'sini kapsar; kapanışta Bar 3 volume ≥ Bar 2 volume * 1.3.
5. Giriş: Bar 3 kapanışında long.
6. Stop: Bar 2'nin low'u.
7. Hedef: Bar 3 giriş + (Bar 3 giriş - stop) * 2 (2R).

**Bulkowski referans:** %72–%74 reversal rate (Morning Star Doji variant).
**Engulfing'den fark:** 3-bar formasyon; orta bar kriterli; volume filtresiz çalışmıyor. Engulfing 2-bar, volume opsiyonel.
**Test önceliği:** Yüksek — istatistiksel olarak en güçlü multi-bar reversal.

---

### H-C2: Three White Soldiers + Trend Context

**Mekanik kural:**
1. Önceki düşüş: Son 10 bar içinde %10+ drop (BTC ölçeği).
2. Bar 1: Bullish bar; gövde ≥ ATR * 0.7; üst fitil ≤ gövdenin %20'si.
3. Bar 2: Bullish bar; Bar 1 kapanışının ±ATR*0.1 seviyesinde açılır; Bar 1'in high'ını aşar.
4. Bar 3: Bullish bar; Bar 2 kapanışının ±ATR*0.1 açılır; Bar 2 high'ını aşar; gövde ≥ ATR * 0.7.
5. Giriş: Bar 3 kapanışında veya Bar 3'ün %50 seviyesinde limit order.
6. Stop: Bar 1'in low'u.
7. Hedef: Bar 3 giriş + (Bar 3 giriş - stop) * 1.5 (1.5R).

**Bulkowski referans:** %82 continuation rate.
**Engulfing'den fark:** 3-bar continuation sinyali; engulfing 2-bar reversal. Aynı anda tetiklenme ihtimali düşük.
**Risk:** Overextension; üç büyük bullish bar sonrası pullback beklemek mantıklı. 1.5R target bu yüzden daha muhafazakar.
**Test önceliği:** Yüksek.

---

### H-C3: Bullish Harami at S/R + Volume Spike (Three Inside Up öncüsü)

**Mekanik kural:**
1. Destek seviyesi: Son 30 bar içindeki swing low veya Fibonacci %61.8 seviyesi.
2. Bar 1: Büyük bearish bar (gövde ≥ ATR * 0.8); low destek bölgesine değer (±ATR*0.1).
3. Bar 2: Küçük bullish bar; tamamen Bar 1 gövdesi içinde; gövde ≤ ATR * 0.35.
4. Bar 3 (Three Inside Up tamamlaması): Bullish bar; Bar 1 kapanışının üstünde kapanır.
5. Giriş: Bar 3 kapanışında long.
6. Stop: Bar 1 low'u.
7. Volume filtresi: Bar 2 veya Bar 3'te volume ≥ 20-bar ortalama * 1.2.

**Bulkowski referans:** Three Inside Up %65; destek bağlamında +5 premium tahmini.
**Engulfing'den fark:** Harami = küçük onay, engulfing = dominant bar. Harami daha küçük reversal sinyali; dekorelasyon yüksek.
**Test önceliği:** Orta-Yüksek.

---

### H-C4: Tweezer Bottom + Doji + HTF Destek

**Mekanik kural:**
1. HTF (haftalık veya aylık) destek seviyesi: Son 3 ay içindeki major swing low ±ATR_weekly*0.5.
2. Bar 1: Bearish bar; Low = L1.
3. Bar 2: Doji veya küçük gövde; Low ≈ L1 (tolerans: (L1 - Low2) / ATR_daily ≤ 0.1).
4. Bar 3: Bullish bar; Bar 2'nin high'ını aşar.
5. Giriş: Bar 3 kapanışı veya Bar 3 high kırılımında.
6. Stop: min(L1, L2) - ATR*0.1.
7. Hedef: 2R.

**Bulkowski referans:** Tweezer Bottom %61; doji variant premium + HTF confluence → tahmini %67–%70.
**Engulfing'den fark:** 3-bar yapı; tweezer "double test" mekanizması; engulfing "dominant body" mekanizması. Tamamen farklı piyasa davranışı.
**Test önceliği:** Orta-Yüksek.

---

### H-C5: Bearish Engulfing at HTF Resistance (Short Hypothesis)

**Mekanik kural:**
1. HTF (haftalık) direnç seviyesi: Son 6 ay içindeki major swing high.
2. Önceki 5+ bar yükseliş (yukarı trend).
3. Bar 1: Bullish bar; Close ≈ direnç (±ATR*0.3 içinde).
4. Bar 2: Bearish engulfing; Bar 1 gövdesini tamamen kapsar; Close < Bar 1 Open.
5. Giriş: Bar 2 kapanışında short.
6. Stop: Bar 2 High + ATR*0.1.
7. Hedef: 2R.

**Bulkowski referans:** %79 bearish reversal rate + HTF context premium.
**Engulfing'den fark:** Short tarafı test; mevcut sistem muhtemelen long bias. Bağımsız test.
**Test önceliği:** Yüksek — engulfing'in short versiyonu ama systematically test edilmemiş.

---

### H-C6: Rising Three Methods (Continuation Signal)

**Mekanik kural:**
1. Güçlü yükseliş trendi: ADX > 25, son 10 bar net %15+ yukarı.
2. Bar 1: Büyük bullish bar (gövde ≥ ATR * 1.0).
3. Bar 2, 3, 4: Her biri öncekinin range'i içinde; hepsi bearish veya neutral; hiçbirinin Low'u Bar 1 Low'unu geçmez.
4. Bar 5: Bullish bar; Bar 4'ün High'ını ve Bar 1'in High'ını aşar.
5. Giriş: Bar 5 kırılım noktasında stop order.
6. Stop: Bar 2–4 konsolidasyon düşüğü.
7. Hedef: Bar 1 gövdesi projeksiyonu (measured move).

**Bulkowski referans:** %74 continuation rate.
**Engulfing'den fark:** Continuation (devam) pattern; engulfing reversal. Piyasa dinamikleri tamamen farklı. Yüksek dekorelasyon.
**Test önceliği:** Orta — trend-following component ekler.

---

### H-C7: Pin Bar at HTF S/R Only (Volman/Grimes Variant)

**Mekanik kural:**
1. HTF S/R: Haftalık veya aylık chart'ta tanımlanan major level.
2. Pin bar kriterleri (Grimes):
   - Fitil ≥ gövdenin 2.5 katı.
   - Gövde toplam range'in ≤ %30'u.
   - Kapanış fitilin karşı tarafındaki %35 içinde.
3. Pin bar low veya high, HTF S/R seviyesine ±ATR_daily*0.3 içinde dokunmalı.
4. Volume: Pin bar volume ≥ 10-bar ortalaması (tercihen ≥ 1.3x).
5. Giriş: Pin bar kapanışında veya ertesi bar açılışında.
6. Stop: Pin bar'ın fitil ucu ötesi (±ATR*0.1).
7. Hedef: 2R minimum.

**Bulkowski referans:** Hammer/Shooting Star %59–%63; HTF confluence premium → %68–%73 tahmini (Grimes'ın kendi gözlemleri).
**Engulfing'den fark:** Gövde dinamiği farklı (pin küçük gövde, engulfing büyük gövde). Farklı "piyasa konuşması." Aynı anda görünmeleri mümkün ama kural setleri tamamen ayrı.
**Test önceliği:** Yüksek — Volman'ın forex'te en çok güvendiği setup; crypto 1d'de henüz test edilmedi.

---

### H-C8: Outside Bar Reversal at S/R (Engulfing Variant)

**Mekanik kural:**
1. S/R yakını (günlük chart): Son 20 bar içinde oluşmuş swing high veya swing low.
2. Bar 1: Trend yönünde güçlü bar.
3. Bar 2 (Outside Bar): High > Bar1.High VE Low < Bar1.Low.
4. Kapanış: Trend tersine; bullish reversal için Close > Bar1.High * 0.6 seviyesinde; bearish için Low * 1.4 altında.
5. Giriş: Bar 2 kapanışında.
6. Stop: Bar 2'nin karşı ucu.
7. Hedef: 1.5R.

**Bulkowski referans:** %63–%65 reversal rate.
**Engulfing'den fark:** Outside bar "hem yukarı hem aşağı" hareket içeriyor; engulfing "körce yiyor." Farklı mekanizma. Dekorelasyon orta (bazen aynı anda tetiklenebilir).
**Test önceliği:** Orta.

---

### H-C9: Evening Star + Overbought RSI Filter

**Mekanik kural:**
1. RSI(14) > 70 son 3 bar içinde (overbought).
2. Bar 1: Büyük bullish bar; gövde ≥ ATR * 0.8.
3. Bar 2: Küçük gövde (doji/spinning top); Bar 1 kapanışının üstünde veya yakınında açılır.
4. Bar 3: Bearish bar; Bar 1 gövdesinin en az %50'sini kapsar.
5. Giriş: Bar 3 kapanışında short.
6. Stop: Bar 2'nin high'ı.
7. Hedef: 2R.

**Bulkowski referans:** Evening Star %73; RSI overbought confluence → %76–%79 tahmini.
**Engulfing'den fark:** 3-bar; RSI filtreli; bearish yön. Mevcut sistemden farklı bağımsız sinyal.
**Test önceliği:** Orta-Yüksek.

---

### H-C10: Three Black Crows + Volume Escalation

**Mekanik kural:**
1. Yükseliş trendinin tepesi yakını (20 EMA üzerinde, son 15 bar).
2. Bar 1: Bearish bar; gövde ≥ ATR * 0.7; volume ≥ 10-bar ort.
3. Bar 2: Bearish bar; Bar 1 kapanışı yakınında açılır; Bar 1 low'unu aşar; volume ≥ Bar1 volume.
4. Bar 3: Bearish bar; Bar 2 kapanışı yakınında açılır; Bar 2 low'unu aşar; volume ≥ Bar2 volume.
5. Volume eskalasyonu: Her bar bir öncekinden daha yüksek volume (zorunlu filtre).
6. Giriş: Bar 3 kapanışında short.
7. Stop: Bar 1'in open'ı veya 3-bar'ın max high'ı.
8. Hedef: 3 bar drop kadar (measured move).

**Bulkowski referans:** %78 bearish continuation/reversal rate; volume filtreli versiyon +4–5 puan premium.
**Engulfing'den fark:** 3-bar sequential selling; engulfing anlık reversal. Tamamen farklı piyasa yapısı.
**Test önceliği:** Yüksek — ayı piyasalarında ve major peak'lerde çok görülen yapı.

---

## 10. Bizim Sistemle Bağlantı

### 10.1 Mevcut Durum

Mevcut sistemimiz **Bullish Engulfing (1d BTC)** üzerine kurulu:
- Hypothesis: `2026-05-08-engulfing-1d-4h-confluence.md`
- Test edilmiş, baseline Sharpe > 0 gözlemlenmiş.
- Engulfing Bulkowski rank 5 (bullish) / 4 (bearish) — sağlam seçim.

### 10.2 Ekleme Adayları (Öncelik Sırası)

**Tier 1 — Yüksek Öncelik (Bulkowski >%70, Engulfing'den bağımsız):**
1. **H-C10: Three Black Crows + Volume** — short tarafı açar; %78 stat; engulfing ile düşük korelasyon.
2. **H-C1: Morning Star + Volume** — %72 stat; 3-bar; engulfing'den mekanik farklı.
3. **H-C7: Pin Bar at HTF S/R** — %68-73 tahmini; Volman'ın güvendiği; henüz test yok.
4. **H-C5: Bearish Engulfing at Resistance** — %79 stat; engulfing'in short versiyonu; ayrı test.

**Tier 2 — Orta Öncelik:**
5. **H-C2: Three White Soldiers** — %82 ama overextension riski; 1.5R target ile test.
6. **H-C9: Evening Star + RSI** — %73+; filter ile güçleniyor.
7. **H-C3: Three Inside Up at S/R** — %65-70; Harami confirmation pattern.
8. **H-C6: Rising Three Methods** — %74; trend continuation; farklı market phase.

**Tier 3 — Araştırma:**
9. **H-C4: Tweezer Bottom + Doji** — %67-70 tahmini; HTF filtresine bağımlı.
10. **H-C8: Outside Bar Reversal** — %63-65; kısmi engulfing overlap riski.

### 10.3 Sistem Entegrasyon Notu

Yeni bir pattern sisteme eklenirken:
1. **Bağımsız backtest:** Engulfing kodu ile aynı data; farklı sinyal kanalı.
2. **Korelasyon testi:** Aynı bar'da iki sinyal üretiliyor mu? → sinyal çakışma analizi.
3. **Regime filtresi:** Grimes'ın phase model'i; trend, pullback, consolidation, breakout fazları için ayrı win rate.
4. **Crypto-specific:** Volume filtresi (on-chain data gerekebilir), funding rate nötr kontrol, weekend gap etkisi.
5. **Walk-forward:** In-sample 2019–2022, out-of-sample 2023–2025, live test 2026.

### 10.4 Crypto 1d'de Henüz Test Edilmemiş Kritik Boşluklar

**Engulfing dışında, Bulkowski top-10 içinden, crypto 1d'de hiç test edilmemiş:**

| Pattern | Bulkowski Rank | Win Rate | Crypto 1d Test? |
|---------|---------------|----------|-----------------|
| Three White Soldiers | 3 | %82 | ❌ Test yok |
| Three Black Crows | 7 | %78 | ❌ Test yok |
| Morning Star (Doji) | 8-9 | %74 | ❌ Test yok |
| Evening Star (Doji) | 8-9 | %73 | ❌ Test yok |
| Rising Three Methods | 10 | %74 | ❌ Test yok |
| Pin Bar at S/R | N/A (Grimes) | %68-73* | ❌ Test yok |
| Three Outside Up/Down | 14 | %68-69 | ❌ Test yok |
| Abandoned Baby | 11-12 | %70 | ❌ (gap issue) |

*Grimes blog estimate

Bu tablodaki her pattern, engulfing'in kârlılığına yakın veya üstünde istatistiksel iddia taşıyor ve crypto 1d'de tamamen terra incognita. Research roadmap için doğal öncelikler.

---

## Referans Kaynaklar

- Bulkowski, Thomas N. *Encyclopedia of Candlestick Charts.* Wiley, 2008.
- Nison, Steve. *Japanese Candlestick Charting Techniques.* 2nd ed., Prentice Hall, 2001.
- Grimes, Adam H. *The Art and Science of Technical Analysis.* Wiley, 2012.
- Grimes, Adam H. Blog: adamhgrimes.com — "Candlestick Statistics" series (2013–2016).
- Volman, Bob. *Forex Price Action Scalping.* 2011.
- Volman, Bob. *Understanding Price Action.* 2014.
- Brooks, Al. *Trading Price Action Reversals.* Wiley, 2012.

---

*Son güncelleme: 2026-05-09. Bu doküman kişisel araştırma ve system geliştirme notlarıdır.*
