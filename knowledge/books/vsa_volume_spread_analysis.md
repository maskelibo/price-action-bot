---
source_id: vsa_volume_spread_analysis
source_type: synthesis
author: Tom Williams / Anna Coulling / Richard Wyckoff / David Weis
title: Volume Spread Analysis — Kapsamlı Referans
type: reference_only
quality: 5
ingested_date: 2026-05-09
topic_tags: [volume_analysis, vsa, effort_vs_result, smart_money, accumulation_distribution, crypto_adaptation]
---

# Volume Spread Analysis (VSA) — Kapsamlı Referans

> Bu doküman Tom Williams'ın *Master the Markets*, Anna Coulling'in *A Complete Guide to Volume Price Analysis*, Richard Wyckoff'un orijinal çalışmaları ve David Weis'ın dalga-tabanlı VSA uzantısından damıtılmış bir sentezdir. Telif hakkı orijinal yazarlara aittir; bu doküman dahili RAG kullanımı için referans niteliğindedir.

---

## 1. Yazarın Çerçevesi — Tarihçe ve Temel Prensipler

### VSA'nın Soyu: Wyckoff → Williams → Coulling

Volume Spread Analysis, Richard D. Wyckoff'un 1910–1930 döneminde geliştirdiği **effort vs result** (çaba vs sonuç) ilkesinin modern ve bilgisayar uyumlu bir formülasyonudur. Wyckoff, piyasanın fiyat ve hacim dışındaki hiçbir türev göstergeyle anlaşılamayacağını savundu. Ona göre her fiyat hareketinin arkasında büyük, organize para bulunur; bu paranın izini fiyat ve hacmin birlikte okunmasıyla sürmek mümkündür.

Tom Williams, Wyckoff'un öğrencisi Richard Ney'in çalışmalarından ve kendi pit trading deneyiminden hareketle 1990'larda **VSA** adını verdiği sistematik bir metodoloji geliştirdi. Williams'ın katkısı, Wyckoff'un kavramsal çerçevesini **bar bazında operasyonel kurallara** dönüştürmektir: her mum, üç boyutta tanımlanır — spread (range), kapanış pozisyonu ve hacim. Bu üçlü kombinasyon belirli pattern'lar üretir ve her pattern yorumlanabilir.

Anna Coulling, Williams'ın çerçevesini 2013'te yayımladığı *A Complete Guide to Volume Price Analysis* ile hem akademik okuyuculara hem pratisyen trader'lara ulaştırdı. Coulling'in katkısı ikiye ayrılır: birinci katkısı, VSA kavramlarını **Forex ve Commodities piyasaları** için uyarlamasıdır. İkinci katkısı, **hacim ve fiyat ilişkisini divergence çerçevesinde** sistematik olarak kategorize etmesidir — "anormal" hacim nedir, "sürpriz yok" hacim nedir, fark ne anlama gelir. Coulling ayrıca Wyckoff'un yarı-öznel pattern okumalarını daha **mekanik eşiklerle** destekler.

David Weis ise hacim analizine **dalga agregasyonu** boyutunu katar: aynı yönde hareket eden ardışık barların hacimleri toplanarak "Weis Dalgaları" oluşturulur. İki ardışık eş yönlü dalganın hacmi karşılaştırıldığında faz geçişlerini niceliksel olarak tespit etmek mümkün olur. Weis dalgası, klasik OBV'den yapısal olarak daha hassastır ve Wyckoff'un Sebep-Sonuç Yasası'nı hacim bağlamında görselleştirir.

### Effort vs Result — VSA'nın Çekirdek İlkesi

VSA'nın tüm yapısını ayakta tutan tek ilke şudur:

> **Hacim "çaba"dır, fiyat hareketi "sonuç"tur. İkisi uyumsuzsa piyasa önemli bir şey söylüyor demektir.**

Bu uyumsuzluk dört temel formda görünür:

| Çaba (Hacim) | Sonuç (Fiyat Hareketi) | Yorum |
|---|---|---|
| Yüksek | Büyük (beklenti yönünde) | Momentum — trend devam eder |
| Yüksek | Küçük / Ters yönde | **Absorpsiyon / Climax** — dönüş yakın |
| Düşük | Küçük | Normal — kimse ilgilenmiyor |
| Düşük | Büyük | **Dikkat** — az dirençle büyük hareket; trend sağlıklı ama kırılabilir |

Buradaki kritik gözlem: yüksek hacmin *her zaman* yükseliş sinyali olmadığıdır. Yüksek hacimle dar bir bar oluşuyorsa büyük para *karşı tarafı* emiyor demektir — bu, dönüşün öncülüdür. VSA, hacmi fiyat hareketiyle birlikte okumanın sistematik biçimidir.

### Smart Money / Composite Operator Kavramı

Williams ve Wyckoff aynı kavramı farklı isimlerle kulanır. Wyckoff'ta **Composite Man** (veya Composite Operator), Williams'ta **Smart Money** ya da **Professional Money**. Her ikisi de aynı kurguyu ifade eder: büyük kurumsal oyuncular (prime brokerlar, hedge fonlar, merkez bankaları için Williams döneminde büyük bankalar ve müzayedeciler), kalabalığın panik ya da açgözlülükle pozisyon açtığı yerde ters konum alır. Bu aktörler:

- Düşüşlerin dibinde sessizce alım yapar (accumulation)
- Yükselişlerin tepesinde satış yapar ve kısa pozisyon alır (distribution)
- Shakeout ve up-thrust hareketleri ile likiditeyi avlar
- Hareketi başlatmadan önce düşük hacimli test barlarıyla arzı/talebi yoklar

VSA'nın amacı bu büyük oyuncuların **ayak izlerini hacim barlarında tespit etmektir**. Retail trader tek tek hareket eder ve piyasayı etkileyemez; ancak büyük hacim hareketleri, büyük paranın giriş-çıkışını gizleyemez.

### Kurumsal Accumulation / Distribution Göstergeleri

VSA bağlamında kurumsal para şu durumlarla kendini ele verir:

- **Climactic volume** + narrow spread: Para giriyor ama fiyat hareket etmiyor → absorpsiyon
- **Ultra-low volume** retest: Kimse satmıyor → supply tükendi → yukarı yol açık
- **High volume up-bar + close lower than open**: Büyük para yükselişi satıyor → distribution
- **High volume down-bar + close near top**: Büyük para düşüşü alıyor → accumulation
- **No demand**: Düşük hacimli up-bar → kurumlar katılmıyor → ralli yapay

---

## 2. Bar Anatomisi — Spread (Range) Sınıflaması

Her VSA analizi, önce barın **spread**'ini (yüksek-düşük farkını) bağlamsal olarak sınıflandırır. Bu sınıflandırma mutlak değil **relatif**'tir — son N barlık ortalamayla kıyaslama yapılır.

### Spread Kategorileri

| Kategori | Tanım | Oran (N-bar ortalamasına göre) | VSA İmzası |
|---|---|---|---|
| **Wide spread** (geniş bar) | Olağanüstü büyük range | > 1.5× ortalama | Momentum veya climax — hacimle birlikte değerlendirilir |
| **Average spread** (normal bar) | Tipik günlük range | 0.7×–1.5× ortalama | Nötr — tek başına sinyal üretmez |
| **Narrow spread** (dar bar) | Normalin altı | < 0.7× ortalama | No-demand, no-supply veya sıkışma — kontekste göre yorumlanır |
| **Ultra-narrow spread** | Neredeyse doji | < 0.3× ortalama | Karar noktası; hacim düşükse absorpsiyon tamamlandı |

### Kapanış Pozisyonu Sınıflaması

Spread'in yanı sıra barın içinde kapanışın nerede olduğu da kritiktir:

- **Üst çeyrek kapanış** (close > barın %75'i): Boğa baskısı, alıcılar kontrolde
- **Orta–üst bant** (%50–75): Hafif boğa eğilimi
- **Orta bant** (%25–75): Belirsiz, tarafsız
- **Orta–alt bant** (%25–50): Hafif ayı eğilimi
- **Alt çeyrek kapanış** (close < barın %25'i): Ayı baskısı, satıcılar kontrolde

VSA'da "alt fitil" ve "üst fitil" ayrımı önemlidir: uzun alt fitil reddetmeyi, uzun üst fitil kabul etmemeyi simgeler. Spread + kapanış pozisyonu + hacim üçlüsü bir arada yorumlanmazsa VSA eksik kalır.

---

## 3. Volume Sınıflaması

VSA'da hacim kategorileri, son N barın ortalamasına göre **relatif** olarak hesaplanır. Williams ve Coulling N=20 veya N=14'ü önerir; sisteme göre kalibre edilebilir.

| Kategori | Oran (N-bar SMA'ya göre) | Yüzde Eşik | Crypto 1D Yorumu |
|---|---|---|---|
| **Ultra-low** | < 0.5× SMA | < %50 ortalama | No-demand veya no-supply en güçlü formu; arz/talep tamamen tükendi |
| **Low** | 0.5×–0.8× SMA | %50–%80 | Test barları, küçük geri çekilmeler — sağlıklı konsolidasyon |
| **Average** | 0.8×–1.5× SMA | %80–%150 | Normal katılım — tek başına sinyal vermez |
| **High** | 1.5×–3.0× SMA | %150–%300 | Kurumsal katılım: SOS, SOW, absorpsiyon dönemi |
| **Climactic (Ultra-high)** | > 3.0× SMA | > %300 | Selling Climax, Buying Climax — trend yorgunluğu zirvesi |

### Volume Z-Score ile İlişki

Mevcut sistemimizde `volume z-score (20)` hesaplanmaktadır. VSA kategorileri bu z-score'a şöyle eşlenir:

```
z < -1.0  →  Ultra-low / Low volume (no-demand / no-supply bölgesi)
-1.0 ≤ z < 0.5  →  Average
0.5 ≤ z < 1.5  →  High
z ≥ 1.5  →  Climactic
```

Bu eşleme mekanik VSA testleri için doğrudan kullanılabilir.

---

## 4. Kore VSA Pattern Kataloğu

Aşağıdaki her pattern yedi başlık altında verilmiştir: **Tanım, Bağlam, Bar Kriterleri, Hacim Kriteri, Sinyal Gücü, Failure Modu, Test Edilebilirlik.**

**TEST EDİLEBİLİR** ibaresi, kripto 1D OHLCV verisinde mekanik olarak tanımlanabilen patternları işaretler.

---

### BULLISH VSA PATTERNS

---

#### 4.1 Stopping Volume (Kapitülasyon Durdurma)

**Tanım:** Düşüş trendi sırasında tek bir barda çok yüksek hacimle karşılaşılır ama fiyat hareketi buna orantısız kalır — wide-spread down bar oluşur fakat kapanış barın üst yarısına yakındır. Bu, büyük paranın panik satışlarını absorbe ettiğinin VSA imzasıdır.

**Bağlam:** Aşağı trendde, ardışık düşüş barlarından sonra. Wyckoff'ta Phase A başına (PS / SC) denk gelir. Fiyat önemli bir destek seviyesine yakın olabilir ama zorunlu değildir.

**Bar Kriterleri:**
- Aşağı bar (kapanış < açılış)
- Spread geniş veya çok geniş (> 1.2× N-bar ortalama range)
- Kapanış barın üst %40'ında — alt fitil uzun

**Hacim Kriteri:** Climactic (> 2.5× SMA) veya yüksek (> 1.5× SMA). Düşük hacimli stopping volume VSA'da tanımsızdır.

**Sinyal Gücü:** Orta-güçlü. Tek başına al sinyali değil; sonraki 2–3 barda yukarı dönüş teyidi gerekir. Takip eden barın close'u stopping volume barının close'unu aşıyorsa teyit alınır.

**Failure Modu:** Sonraki bar aynı veya daha düşük hacimle yeni dip yaparsa stopping volume başarısız olmuştur — trend devam eder.

**TEST EDİLEBİLİR** — Mekanik kural:
```
down_bar AND spread > 1.2 * atr_n AND
close > (low + 0.6 * (high - low)) AND
volume > 2.0 * volume_sma_20
```

---

#### 4.2 Selling Climax (SC — Klimaktik Satış)

**Tanım:** Düşüş trendi sonunda aşırı hacimle gelen geniş aşağı bar. Fiyat günün dibine yakın kapanmaz — uzun alt fitil veya orta-üst kapanış görülür. Bu, son panikçilerin satışının kurumsal alımla absorbe edildiğinin sinyalidir. Wyckoff Accumulation Phase A'sının omurgasıdır.

**Bağlam:** Uzun süreli düşüş trendi sonunda. Haberlerin en kötü olduğu, perakende panikle sattığı dönem. Hacmin ortalamanın 2x–4x üzerinde olması karakteristiktir.

**Bar Kriterleri:**
- Wide-spread aşağı bar
- Kapanış barın üst %50'sinde (alt fitil mevcut)
- Önceki 5 barın en düşük low'u (son yerel dip)

**Hacim Kriteri:** Ultra-high / Climactic (> 2.5× SMA). Williams'ta "hayatta gördüğün en yüksek hacim barı" ifadesi sık geçer; abartı değil, gerçekten klimaktik eşik.

**Sinyal Gücü:** Güçlü — Wyckoff accumulation zincirinin en kritik event'i. SC + AR + ST üçlüsü tamamlandığında Phase B onaylanır.

**Failure Modu:** SC sonrası 3–5 bar içinde yeni dip yapılırsa SC gerçek değildir; kapitülasyon sürmektedir. "Failed SC" olarak etiketlenir.

**TEST EDİLEBİLİR** — Mekanik kural:
```
down_bar AND spread > 1.5 * atr_n AND
close > (low + 0.5 * (high - low)) AND
volume > 2.5 * volume_sma_20 AND
low == rolling_min(low, 5)
```

---

#### 4.3 No Demand (Talepsiz Yükseliş — Üst Uyarısı)

**Tanım:** Düşük hacimli ve dar spreadli yukarı bar. Fiyat yükseliyor ama katılım yok — büyük para bu ralliyi desteklemiyor. Üstte uyarı sinyali; özellikle bir yükseliş trendinde veya direnç yakınında belirirse trend yorgunluğuna işaret eder.

**Bağlam:** Yukarı trendde veya range içinde relief rally sırasında. Distribution range'lerinde tipik görünüm; Phase B'nin no-demand yapısı UTAD teyitinden önce sıkça gelir.

**Bar Kriterleri:**
- Yukarı bar (kapanış > açılış)
- Spread narrow (< 0.7× ortalama range)
- Kapanış barın üst %50'si veya altında da olabilir (geri dönüş korkusu yok)

**Hacim Kriteri:** Low veya ultra-low (< 0.7× SMA). Yüksek hacimli yukarı dar bar, no-demand değil absorpsiyon (farklı yorumlanır).

**Sinyal Gücü:** Zayıf-orta. Tek başına giriş değil — uyarıdır. Art arda 2–3 no-demand bar gelirse uyarı güçlenir.

**Failure Modu:** Sonraki bar yüksek hacimle yukarı giderse no-demand iptal; kurumlar katıldı demektir.

**TEST EDİLEBİLİR** — Mekanik kural:
```
up_bar AND spread < 0.7 * atr_n AND volume < 0.7 * volume_sma_20
```

---

#### 4.4 Bag Holding / Absorpsiyon (Yük Teslim Alımı)

**Tanım:** Aşağı bar, narrow spread, yüksek hacim. Fiyat düşüyor ama büyük para sessizce alım yapıyor — piyasa satışını emip fiyatı tutmaya çalışıyor. Dar spread + yüksek hacim kombinasyonu absorpsiyon imzasıdır. Wyckoff'ta Phase B accumulation'ının karakteristik yapısıdır.

**Bağlam:** Düşüş trendinde destek bölgesinde veya accumulation range'i içinde. Fiyat düşmesine rağmen hacim artıyorsa (ama hareket küçükse) absorpsiyon düşünülür.

**Bar Kriterleri:**
- Aşağı bar (kapanış < açılış veya doji)
- Spread dar veya orta (< 1.2× ortalama range)
- Kapanış barın alt yarısında bile olabilir — düşük tutulmuş ama hareket sınırlı

**Hacim Kriteri:** High (> 1.5× SMA). Yüksek hacimli bir aşağı bar "neden düşmüyor?" sorusunu doğurur — cevap absorpsiyondur.

**Sinyal Gücü:** Orta. Tek bar yeterli değil; devam eden barların da görece düşük hacimli olması ve fiyatın destekte tutunması gerekir.

**Failure Modu:** Hacim yüksek kalmaya devam ederken fiyat belirgin düşüyorsa absorpsiyon değil, baskı altındaki satış (SOW benzeri) var demektir.

**TEST EDİLEBİLİR** — Mekanik kural:
```
down_bar AND spread < 1.0 * atr_n AND volume > 1.5 * volume_sma_20 AND
abs(close - open) < 0.4 * (high - low)
```

---

#### 4.5 Test Bar (Düşük Hacimli Geri Test) **TEST EDİLEBİLİR**

**Tanım:** SC veya Spring sonrası, fiyat önceki diplere geri döner ama hacim çok düşüktür ve yeni dip oluşmaz. Bu, "satıcı yok" sinyalidir — supply tükendi. Wyckoff'ta Phase C testinin klasik formudur.

**Bağlam:** SC veya Spring'den 1–7 bar sonra. Fiyat SC/Spring low'una yaklaşır ama kırmaz (veya minimal olarak kırar ve hızla reclaim). Hacim çok düşük — normal günlük seviyelerin yarısının altı.

**Bar Kriterleri:**
- Low, önceki SC veya Spring low'una ≤ 1 ATR mesafede
- Kapanış barın üst %60'ında (reddetme mevcut)
- Spread dar (< 0.8× ortalama)

**Hacim Kriteri:** Ultra-low (< 0.6× SMA). Bu pattern'ın kalbi düşük hacimdir — "kimse satmıyor" mesajı burada.

**Sinyal Gücü:** Güçlü — Spring ile birlikte değerlendirildiğinde Wyckoff'un en güvenilir onay sinyali. Test bar sonrası SOS gelirse kurulum tamamdır.

**Failure Modu:** Test barı düşük hacimle gelir ama yeni düşük yapar ve kapanış da alt yarıda kalırsa test başarısız — supply tükenmedi.

**TEST EDİLEBİLİR** — Mekanik kural:
```
low <= prev_swing_low * 1.005 AND
close > (low + 0.5 * (high - low)) AND
volume < 0.6 * volume_sma_20 AND
spread < 0.8 * atr_n
```

---

#### 4.6 Successful Test (Başarılı Test + Yukarı Onayı)

**Tanım:** Test Bar'ın bir adım ilerideki versiyonu. Test Bar'ın kapanış günü veya hemen ertesi bar, yukarı yönde yüksek hacimli (veya en azından ortalama hacimli) bir bar gelir ve önceki direnç seviyelerini temizler. Test + hızlı yukarı bar kombinasyonu Spring onayının mekanik teyididir.

**Bağlam:** Test Bar'dan 0–2 bar sonra. Range içinde ya da Phase D başında.

**Bar Kriterleri (kombinasyon):**
- Bar 1: Test Bar kriterleri (düşük hacim, düşük swing'e yakın, üst kapanış)
- Bar 2: Yukarı bar, spread orta-geniş, close > barın %65'i, volume ≥ ortalama

**Hacim Kriteri:** Bar 1 ultra-low, Bar 2 ≥ average (0.8× SMA). Hacim kontrastı önemlidir.

**Sinyal Gücü:** Güçlü. İki barlı bir pattern olduğu için tek bar sinyallerinden daha güvenilir.

**Failure Modu:** Bar 2 yüksek hacimle gelmez ya da spread dar kalırsa Successful Test değil, No Demand var demektir.

---

#### 4.7 Effort to Move Up (Yukarı Hareket Çabası) **TEST EDİLEBİLİR**

**Tanım:** Geniş spread, yukarı bar, yüksek hacim ve üst çeyrek kapanış kombinasyonu. Hem çaba hem sonuç beklentiye uygun — yüksek hacim gerçek alımla eşleşiyor. SOS veya LPS'in fiyat onayıdır.

**Bağlam:** Spring + Test sonrası Phase D'de ya da range kırılması sırasında. Yukarı trende geçişin hacim teyididir.

**Bar Kriterleri:**
- Yukarı bar, close > barın %70'i (üst çeyrek veya üst üçte biri)
- Spread geniş (> 1.2× ortalama)
- Önceki 3 barın high'ını kırar (momentum teyidi)

**Hacim Kriteri:** High veya climactic (> 1.5× SMA).

**Sinyal Gücü:** Güçlü. Effort + result uyumu var. Bu bar sonrası LPS bekleyişine girilir.

**Failure Modu:** Sonraki barlar aynı veya daha yüksek hacimle geri çekilirse climax olabilir — effort-to-move-up değil buying climax başlamış olabilir.

**TEST EDİLEBİLİR** — Mekanik kural:
```
up_bar AND spread > 1.2 * atr_n AND
close > (low + 0.7 * (high - low)) AND
high > rolling_max(high, 3).shift(1) AND
volume > 1.5 * volume_sma_20
```

---

#### 4.8 Shakeout (Sert Düşüş + Ani Dönüş)

**Tanım:** Fiyat destek seviyesinin altına sert iner (genellikle geniş aşağı bar, yüksek hacim), hemen aynı bar veya 1 bar içinde range içine geri döner. Wyckoff'un Spring kavramıyla örtüşür ama VSA bağlamında bar içi manipülasyon parmak izidir.

**Bağlam:** Trading range'in alt sınırında veya önemli bir destek seviyesinin hemen altında. Retail stop-loss hasat çalışması.

**Bar Kriterleri:**
- Aşağı bar, low önceki swing low'un altında
- Kapanış barın üst %50'sinde (güçlü reddetme)
- Önceki swing low'u aşan penetrasyon < 1 ATR (çok derin shakeout gerçek breakdown'a dönüşebilir)

**Hacim Kriteri:** High veya climactic (> 1.5× SMA). Düşük hacimli shakeout daha zayıf sinyaldir.

**Sinyal Gücü:** Güçlü — özellikle hızlı reclaim ile birleştiğinde. ICT'nin "stop hunt" kavramıyla aynı mekanik.

**Failure Modu:** Penetrasyon büyükse (> 2 ATR) veya reclaim gecikmeli/zayıf kalırsa breakdown devam ediyor demektir.

---

#### 4.9 Bullish Hammer + High Volume

**Tanım:** Klasik hammer mum kalıbı (uzun alt fitil, küçük gövde, az veya sıfır üst fitil) + ortalama üzeri hacim. VSA'da bu kombinasyon "büyük para düşüşleri alıyor" şeklinde okunur. Williams, hammer'ı tek başına değil hacimle birlikte anlam taşıyan bir kalıp olarak ele alır.

**Bağlam:** Destek bölgesi, düşüş trendi sonu veya Phase A/C.

**Bar Kriterleri:**
- Alt fitil ≥ barın %55'i
- Gövde ≤ barın %25'i
- Üst fitil ≤ barın %15'i (neredeyse yok)
- Kapanış barın üst %30'unda

**Hacim Kriteri:** High veya climactic (> 1.3× SMA). Düşük hacimli hammer VSA'da zayıf; sadece "kimse satmıyor" der, "biri alıyor" demez.

**Sinyal Gücü:** Orta. Hacim desteğiyle birlikte güçlü olur. Sonraki barın onayı gerekir.

**Failure Modu:** Hacim yüksek ama sonraki bar yeni dip yaparsa hammer başarısız.

---

#### 4.10 Pseudo Up Thrust (Yanlış Kırılış Habercisi) + Düşük Hacim

**Tanım:** Fiyat direnç seviyesinin üzerine az miktarda geçer ama kapanış direnç altında kalır ve hacim düşüktür. Williams buna "test without strength" der — büyük para bu kırılışı desteklemiyor, muhtemelen zayıf ellerin son hareketi. Pseudo Up Thrust yükselişin bitmekte olduğunu söyler ama henüz tam bir bearish signal değildir.

**Bağlam:** Önemli direnç seviyesine yakın, range üst sınırında veya önceki swing high'da.

**Bar Kriterleri:**
- High, önceki direnç seviyesini geçer (minimal penetrasyon)
- Kapanış direnç seviyesinin altında
- Spread orta veya dar

**Hacim Kriteri:** Ultra-low veya low (< 0.7× SMA). Düşük hacim "gerçek breakout yok" der.

**Sinyal Gücü:** Zayıf-orta. Uyarı niteliğinde; tam Up Thrust (bearish) ile karıştırılmamalı.

**Failure Modu:** Sonraki bar yüksek hacimle direnç üzerinde kapanırsa gerçek breakout var — pseudo tanımı iptal.

---

### BEARISH VSA PATTERNS

---

#### 4.11 Buying Climax (BC — Klimaktik Alım) **TEST EDİLEBİLİR**

**Tanım:** Yükseliş trendi sırasında aşırı hacimli geniş yukarı bar, ama kapanış üst fitil içinde veya barın alt yarısında. Retail FOMO ile giren son alıcılar, kurumsal dağıtımı finanse ediyor. Wyckoff Distribution Phase A'sının omurgasıdır.

**Bağlam:** Uzun yükseliş trendi sonunda, haberlerin en iyimser olduğu dönem. Kripto'da altcoin season zirveleri, BTC yeni ATH'ları.

**Bar Kriterleri:**
- Wide-spread yukarı bar
- Kapanış barın alt %50'sinde (üst fitil uzun)
- Son 5 barın en yüksek high'ı (son yerel zirve)

**Hacim Kriteri:** Ultra-high / Climactic (> 2.5× SMA).

**Sinyal Gücü:** Güçlü — özellikle AR ve ST ile teyit edildiğinde.

**Failure Modu:** Kapanış üst çeyrekte ise BC değil; trend devamı var ve distribution henüz başlamadı.

**TEST EDİLEBİLİR** — Mekanik kural:
```
up_bar AND spread > 1.5 * atr_n AND
close < (low + 0.5 * (high - low)) AND
volume > 2.5 * volume_sma_20 AND
high == rolling_max(high, 5)
```

---

#### 4.12 Up Thrust (Yalancı Yükseliş) **TEST EDİLEBİLİR**

**Tanım:** Fiyat direnç seviyesinin üzerinde açılır veya geçer ama gün içinde sert şekilde geri döner. Kapanış direnç seviyesinin altındadır. Williams'ın en fazla vurguladığı bearish signal; UTAD'ın mini formudur.

**Bağlam:** Direnç bölgesi, range üst sınırı veya önceki yüksek. Yükseliş trendi veya distribution range içinde.

**Bar Kriterleri:**
- High önceki swing high'ı veya direnç seviyesini geçer
- Kapanış direnç seviyesinin altında (reddetme net)
- Spread geniş (penetrasyon büyük)
- Uzun üst fitil oluşur

**Hacim Kriteri:** Yüksek hacim (> 1.5× SMA) ile gelen Up Thrust daha güçlü sinyaldir; ama düşük hacimli Up Thrust da geçerlidir (kurumlar test ediyor, ilgi yok demek).

**Sinyal Gücü:** Güçlü. Williams'ın "professional selling" tanımına girer. Sonraki bar kapanış altında kapanırsa teyit alınır.

**Failure Modu:** Kapanış direnç üzerinde kalırsa Up Thrust iptal, gerçek breakout var.

**TEST EDİLEBİLİR** — Mekanik kural:
```
high > rolling_max(high, 5).shift(1) AND
close < rolling_max(high, 5).shift(1) AND
(high - close) > 0.5 * (high - low) AND
volume > 1.3 * volume_sma_20
```

---

#### 4.13 No Supply (Arzı Olmayan Düşüş)

**Tanım:** Düşük hacimli ve dar spreadli aşağı bar. Fiyat düşüyor ama satıcı yok — bu bir gerçek satış değil, alıcı yokluğundan kaynaklanan geçici düşme. Williams'a göre bu, bir yükseliş öncesindeki temizlik hareketinin tipik görünümüdür.

**Bağlam:** Düşüş trendinde destek bölgesine yakın, ya da accumulation range'i içinde relief rally sonrasında pullback sırasında.

**Bar Kriterleri:**
- Aşağı bar (kapanış < açılış)
- Spread narrow (< 0.7× ortalama range)
- Kapanış barın alt yarısında da olabilir (zorunlu değil)

**Hacim Kriteri:** Ultra-low (< 0.6× SMA). Bu düşük hacim "arzın bittiği" mesajını verir — supply exhaustion.

**Sinyal Gücü:** Orta-güçlü. Test Bar ile benzer mantık; ikisi birlikte geldiğinde çok güçlü.

**Failure Modu:** Düşük hacimli aşağı bar sonrası bir sonraki bar da aşağı giderse ve hacim artarsa no-supply değil, gerçek satış baskısı var demektir.

---

#### 4.14 Effort to Move Down (Aşağı Hareket Çabası)

**Tanım:** Geniş spread, aşağı bar, yüksek hacim ve alt çeyrek kapanış kombinasyonu. Hem çaba hem sonuç uygun — büyük para gerçekten satıyor. SOW'un klasik formudur; trend değişiminin güçlü habercisi.

**Bağlam:** Distribution range'inden çıkış, UTAD sonrası veya Phase D aşağı ivmelenme.

**Bar Kriterleri:**
- Aşağı bar, close < barın %30'unda (alt çeyrek kapanış)
- Spread geniş (> 1.2× ortalama)
- Önceki 3 barın low'unu kırar

**Hacim Kriteri:** High veya climactic (> 1.5× SMA).

**Sinyal Gücü:** Güçlü — effort + result uyumu. SOS'un ayı simetriği.

**Failure Modu:** Sonraki barlar hızla kapanışın üzerine çıkarsa climax ve reversal var; effort-to-down değil selling climax.

---

#### 4.15 Distribution Candle (Dağıtım Mumu)

**Tanım:** Yüksek hacimli yukarı bar ama kapanış gün içinde oluşan yüksekten çok uzak; uzun üst fitil, alt kapanış. Gün boyunca büyük para satıyor ve fiyatı aşağı çekiyor. Williams bunu "professional selling during the day" olarak tanımlar.

**Bağlam:** Trend zirvesi yakınında veya distribution range içinde. Önceki birkaç bar yukarı trend oluşturmuş olmalı.

**Bar Kriterleri:**
- Açılış düşük, high'e yakın bir yerde fiyat zirve yapar
- Kapanış düşük (barın alt %35'inde)
- Üst fitil uzun; gövde küçük veya ters çevrilmiş (shooting star tipi)

**Hacim Kriteri:** High (> 1.5× SMA). Hacim çok yüksek ama fiyat orada kapanmıyor — çelişki = dağıtım.

**Sinyal Gücü:** Güçlü. Coulling bu kalıbı "the definitive sign of distribution" olarak niteler.

**Failure Modu:** Ertesi gün fiyat günün highinın üzerinde kapanırsa distribution değil devam hareketi var.

---

#### 4.16 Bearish Pseudo Test

**Tanım:** Yukarı testin bearish versiyonu. Fiyat destek seviyesinin altına az miktarda iner ama düşük hacimle; kapanış destek üstünde. Büyük para bu testi yapmıyor — sadece zayıf ellerin geçici bir kıpırtısı. Gücü yoktur ama bir sonraki bearish hareketin habercisi olabilir.

**Bağlam:** Distribution range'i içinde, önceki swing low'a yakın.

**Bar Kriterleri:**
- Low, önceki swing low'u biraz geçer (< 0.5 ATR penetrasyon)
- Kapanış destek üzerinde
- Spread dar

**Hacim Kriteri:** Ultra-low veya low (< 0.7× SMA).

**Sinyal Gücü:** Zayıf. Uyarı niteliğinde; tam SOW veya Effort-to-Move-Down beklenmeli.

---

#### 4.17 Hidden Up Thrust (Gizli Yukarı İtme)

**Tanım:** Klasik Up Thrust kadar dramatik değil; fiyat direnç seviyesini net geçmez ama güne yukarıda açılır, güçlü görünür ve tüm kazanımları geri verir. Kapanış açılışın önemli ölçüde altındadır. Williams bunu "buying drying up at the top" olarak tanımlar.

**Bağlam:** Yükseliş trendi veya relief rally sonunda. Direnç seviyesine yakın değil bile olabilir.

**Bar Kriterleri:**
- Açılış günün yakın yükseklerinde (veya bir gap up)
- Kapanış açılışın > %60 altında (geriye verme)
- Gün içi high belirsiz — dramatik penetrasyon yok

**Hacim Kriteri:** High (> 1.3× SMA). Yüksek açılış hacmi düşerse confirmation güçlenir.

**Sinyal Gücü:** Orta. Tek başına güçlü değil; trend bağlamı ve ardından gelen barlarla anlam kazanır.

**Failure Modu:** Sonraki bar güçlü yukarı bar olursa Hidden UT iptal.

---

## 5. Volume Divergence Konseptleri

Volume divergence, VSA'nın en güçlü sinyal üretim mekanizmasıdır. Ana formlar:

### 5.1 Fiyat Yukarı, Hacim Aşağı → Zayıflık

Fiyat yeni yüksekler yapıyor ama her yeni yüksek öncekinden daha düşük hacimle geliyor. Hareketin arkasında kurumsal para yok — perakende momentum var. Bu klasik "price-volume divergence" yükseliş trendinin sonunu haberlemenin en güvenilir yoludur.

Mekanik test: `price.rolling(5).max()` yeni high yapıyor ama `volume.rolling(5).max()` yeni high yapmıyor → divergence bayrağı.

### 5.2 Fiyat Aşağı, Hacim Aşağı → Arz Yok (No Supply)

Fiyat düşüyor ama hacim de azalıyor. Satıcılar bitmekte; büyük para satmıyor. Bu, genellikle düşüşün son aşamasıdır ve bir test / dönüş için zemin hazırlanıyor demektir. Wyckoff Spring'inden önceki Phase B sonunun karakteristik görüntüsüdür.

### 5.3 Fiyat Aşağı, Hacim Yukarı → Güç (Effort Mevcut)

Büyük para aşağı satıyor — trend devamı kuvvetle. Eğer bu sırada spread geniş ve kapanış alt çeyrekteyse SOW; eğer spread daralıyorsa absorpsiyon (fiyat düşüyor ama yavaş, birisi emme yapıyor).

### 5.4 Fiyat Yukarı, Hacim Yukarı → Sağlıklı Trend

En basit ve sağlıklı kombinasyon. Hem çaba hem sonuç uyumlu — momentum güçlü. Ama bu kombinasyon klimaktik seviyelere ulaşırsa (climactic volume) artık buying climax alanına giriliyor.

### 5.5 Weis Dalga Divergence

Weis'ın katkısı: ardışık yukarı dalganın hacimlerini karşılaştır.
- Dalga 1 yukarı: 1000 coin hacim, +3% hareket
- Dalga 2 yukarı: 700 coin hacim, +2% hareket
- Dalga 3 yukarı: 400 coin hacim, +0.8% hareket

→ Her dalga hem daha az hacim hem daha az hareket üretiyor → trend güç kaybediyor → dönüş yakın.

Bu kümülatif dalga analizi, bar bazı okumadan daha az gürültülüdür ve trend sonlarını erken tespit eder.

---

## 6. Multi-Timeframe VSA

### 6.1 Hiyerarşi Prensibi

VSA en güçlü şekilde **yüksek timeframe bağlam + düşük timeframe giriş** kombinasyonuyla çalışır:

| Timeframe | Kullanım Amacı |
|---|---|
| **Haftalık (W)** | Makro accumulation/distribution fazı; major SC/BC bölgeleri |
| **Günlük (1D)** | Birincil VSA sinyalleri; pattern tanımlama |
| **4 Saatlik (4H)** | Giriş zamanlaması; günlük sinyalin sub-pattern teyidi |
| **1 Saatlik (1H)** | İnce giriş ve stop yönetimi |

### 6.2 Haftalık Bağlam → Günlük Sinyal

Haftalıkta Selling Climax gördüyseniz günlük Test Bar sinyali çok daha güvenilirdir. Haftalıkta No Demand görüyorsanız günlük Up Thrust beklenir. Timeframe uyumu, sinyal kalitesini doğrudan artırır.

### 6.3 Volume Normalizasyon Sorunu

Farklı timeframe'lerde hacmi nasıl karşılaştırırsınız? Çözüm: her timeframe kendi N-bar SMA'sına göre normalize edilir. 4H hacim z-score'u ayrı hesaplanır; 1D z-score'undan bağımsızdır. Konfluans: hem 1D hem 4H'ta climactic volume varsa sinyal kuvveti katlanır.

---

## 7. Quantifiable Test Rules — Mekanik Eşikler

Aşağıdaki eşikler, BTC/USDT 1D spot OHLCV verisine kalibre edilmiştir. Altcoin ve düşük likidite piyasaları için eşikler genişletilmelidir.

| Pattern | Spread Eşik | Hacim Eşik | Kapanış Pozisyonu | Lookback |
|---|---|---|---|---|
| Selling Climax | > 1.5× ATR(20) | > 2.5× SMA(20) | > %50 (üst yarı) | Low = 5-bar min |
| Buying Climax | > 1.5× ATR(20) | > 2.5× SMA(20) | < %50 (alt yarı) | High = 5-bar max |
| Stopping Volume | > 1.2× ATR(20) | > 2.0× SMA(20) | > %60 (üst) | Aşağı bar |
| Up Thrust | Herhangi | > 1.3× SMA(20) | < Direnç seviyesi | High > 5-bar max |
| Test Bar | < 0.8× ATR(20) | < 0.6× SMA(20) | > %50 | Low ≈ prev_low ±1% |
| No Demand | < 0.7× ATR(20) | < 0.7× SMA(20) | Herhangi | Yukarı bar |
| No Supply | < 0.7× ATR(20) | < 0.6× SMA(20) | Herhangi | Aşağı bar |
| Effort to Move Up | > 1.2× ATR(20) | > 1.5× SMA(20) | > %70 | Yukarı bar |
| Bag Holding | < 1.0× ATR(20) | > 1.5× SMA(20) | body_ratio < 0.4 | Aşağı bar |

**Volume SMA Penceresi:** Williams 20 barı önerir; Coulling 14 kullanır. Kripto 1D için 20 makuldür — weekends dahil, daha stabil.

**ATR Penceresi:** 14 veya 20 bar. ATR normalize range hesaplaması için kullanılır; mutlak spread yerine ATR-normalized spread daha robust.

---

## 8. Bizim Sistemle Bağlantı

### 8.1 Mevcut Volume Z-Score Feature

`src/price_action/ml/features.py` içinde `volume z-score (20)` zaten hesaplanmaktadır. Bu doğrudan VSA hacim kategorilerine eşlenir:

```python
# Mevcut feature → VSA kategori mapping (signals/vsa.py adayı)
def vsa_volume_category(volume_zscore: float) -> str:
    if volume_zscore < -1.0:
        return "ultra_low"
    elif volume_zscore < -0.3:
        return "low"
    elif volume_zscore < 0.7:
        return "average"
    elif volume_zscore < 1.5:
        return "high"
    else:
        return "climactic"
```

### 8.2 VSA Filter Overlay on Engulfing

Mevcut bullish/bearish engulfing patternları, VSA hacim filtresiyle zenginleştirilebilir:

```
# Güçlü bullish engulfing: VSA Effort-to-Move-Up onayı
bullish_engulfing AND volume_zscore > 0.7  →  HIGH confidence
bullish_engulfing AND volume_zscore < -0.3  →  NO DEMAND (sahte sinyal riski)

# Güçlü bearish engulfing: VSA Effort-to-Move-Down onayı
bearish_engulfing AND volume_zscore > 0.7  →  HIGH confidence
bearish_engulfing AND volume_zscore < -0.3  →  NO SUPPLY (sahte sinyal riski)
```

Bu iki kural tek başına win-rate'i önemli ölçüde artırabilir — hacim onayı olmayan engulfing sinyallerini filtreler.

### 8.3 Standalone VSA Strategy Candidates

Birincil test adayları (mekanik + BTC 1D'de yeterli frekans):

1. **SC Detector:** `volume > 2.5×SMA` + `wide down bar` + `close upper 50%` → Phase A uzun vadeli long sinyal
2. **Test Bar System:** Spring/SC tespiti sonrası `low ≈ prev_low` + `volume < 0.6×SMA` → Phase C giriş
3. **No Demand Filter:** `up_bar + narrow + low_vol` → mevcut long sinyalleri için negatif filtre
4. **Up Thrust Short:** `high > prev_high` + `close < prev_high` + `volume > 1.3×SMA` → short sinyal

### 8.4 Effort vs Result Feature

Mevcut `volume z-score` ve fiyat hareketinin z-score'u birleştirilerek yeni bir feature üretilebilir:

```python
# Effort vs Result Divergence Index
effort = volume_zscore  # çaba
result = abs(price_change_zscore)  # sonuç
evr_divergence = effort - result  # pozitif = effort > result = absorpsiyon sinyali
```

Yüksek `evr_divergence` (çok hacim, az hareket) absorpsiyon bölgesi; negatif (az hacim, büyük hareket) düşük direnç ortamı.

---

## 9. Yaygın Hatalar

### 9.1 Volume Context vs Absolute Volume Karışıklığı

Kripto piyasasında hacim mutlak değerleri yanlış yorumlanır. Bitcoin 2021'de ortalama günlük spot hacmi 30 milyar dolar iken 2024'te farklı olabilir. **Mutlak hacim karşılaştırması anlamsızdır** — her zaman N-bar SMA'ya göre relatif değerlendirme yapılmalıdır. "Yüksek hacim günü" her zaman bağlama göre tanımlanır.

### 9.2 VSA İlliquid Piyasalarda Güvenilmezdir

Düşük likidite altcoinlerde (günlük hacim < 1M dolar), tek bir balina işlemi tüm VSA pattern'ları bozabilir. Wash trading ve manipüle hacim, VSA sinyallerini tamamen geçersiz kılar. VSA analizinin güvenilir olması için:
- Minimum günlük spot hacim: > 50M dolar (BTC/ETH için sorun yok)
- Exchange hack veya liste olayları hariç tutulmalı
- Birden fazla borsanın agregat hacmi tercih edilmeli

### 9.3 Kripto 24/7 vs Forex/Equity Session Sorunu (Detaylı Kritik Değerlendirme — bkz. Bölüm 10)

VSA orijinal olarak NYSE ve CME gibi piyasalarda, **session bazlı** hacim yapısıyla geliştirildi. Forex ve equity VSA analizinde açılış-kapanış hacimleri, hafta sonu boşlukları ve sezon örüntüleri önemli referans noktalarıdır. Kripto'da bunlar yoktur.

### 9.4 Tek Bar Analizine Aşırı Güvenmek

Bir bar mükemmel SC gibi görünebilir ama bağlamı yoksa anlamsızdır. SC bir düşüş trendinin ardından gelir; boğa piyasasının ortasında gelen climactic hacimli aşağı bar farklı yorumlanır. Her pattern, önceki 20–50 barlık bağlamın içinde değerlendirilmelidir.

### 9.5 No Demand'ı Her Zaman Düşüş Habercisi Sanmak

No demand (düşük hacimli up bar) bir düşüş öncesinde görülür — ama aynı zamanda trend sürerken **küçük konsolidasyon** sırasında da görülür. Trend bağlamı olmadan no demand, yanlış short sinyaline yol açar. Trendin yönü belirlenmeden no demand yorumlamak tehlikelidir.

### 9.6 Perpetual Futures Hacmini VSA Analizinde Kullanmak

Kripto perpetual futures hacmi, spot hacminin 5–10 katı olabilir. Ayrıca funding rate kaynaklı hacim surge'leri gerçek kurumsal alım/satım değildir. VSA **spot exchange hacmi** üzerinde yapılmalıdır. Perpetuals sadece sentiment göstergesi olarak (funding rate) kullanılabilir.

---

## 10. Kritik Değerlendirme: VSA Kripto 24/7 Ortamında

### Temel Sorun: Session Yokluğu

Geleneksel VSA, NYSE/CME veya Londra/New York Forex sessionlarının sağladığı **doğal ritim** üzerine kuruludur:
- Açılış hacim spike'ları → gün boyunca dinginleşme → kapanış re-test
- Hafta içi vs hafta sonu davranış farkı
- "Smart money London session, retail NY session" gibi zaman bazlı katman ayrımı

Kripto'da bu katmanlar yoktur. Sonuçlar:
- **Klimaktik hacim eşiği kalibrasyonu** daha zor — doğal bir "günlük açılış spike" baseline yok
- **Hafta sonu hacim** doğal olarak düşüktür; Pazar kapanışı "low volume" yanılgısı yaratır
- Asia, Europe, US sessionlarının toplam agregat hacmi kullanıldığında, timezone bazlı kurumsal hareket gömülü kalır

### Kripto Özelinde Hangi VSA Patterns Güçlü Çalışır?

**Güçlü çalışan (Önerilen Test):**

1. **Selling Climax + Test Bar kombinasyonu** — BTC major bottomlarında (2018 Aralık, 2020 Mart, 2022 Kasım) mükemmel çalıştı. Volume z-score > 2.5 + lower wick recovery kripto'da son derece güvenilir.

2. **Up Thrust** — BTC major toplarında (2021 Nisan, 2021 Kasım, 2024 Mart) güçlü. Kripto wick hunting kültürü bu sinyali daha sık üretiyor.

3. **No Demand Filter** — Mevcut long sinyallerine filtre olarak kullanımı değerli. Hacim teyidi olmayan ralliler kripto'da sıklıkla başarısız oluyor.

4. **Test Bar** — SC/Spring sonrası test, kripto büyük taban oluşumlarında güçlü. Low volume retest kripto'da açık ve mekanik.

5. **Effort to Move Up (SOS)** — BTC bull market re-accumulation kırılımlarında güçlü; hacim + geniş bar + kapanış üst çeyrek kombinasyonu güvenilir.

**Zayıf veya Uyarlanması Gereken:**

- **Buying Climax → Immediate Short:** Kripto bull market'ta BC sonrası drop olur ama birkaç ay içinde yeni ATH görülür. BC tek başına short için yeterli değil; distribution teyidi (AR + ST + UTAD zinciri) gerekir.

- **No Supply (standalone):** Düşük hacimli aşağı bar, kripto'da Pazar düşüşleriyle karıştırılır. Bağlam filtresi olmadan sinyal üretimi fazla gürültülüdür.

- **Phase B Pattern Fades:** 24/7 ortamda range sınırları daha sık test edilir ve "fake breakout" daha yaygındır. Phase B fades kripto'da daha düşük win rate gösterir.

- **Hidden Up Thrust:** Gün içi manipülasyonu kripto'da çok yaygın; bu pattern sahte sinyale açıktır. Günlük timeframe'de daha güvenilir, 4H ve altında gürültü fazla.

### Adaptasyon Önerileri Kripto için

1. **Volume SMA penceresini büyüt:** 20 bar yerine 30 bar — haftalık seasonal etkiyi azaltır
2. **Hafta sonu barlarını düşük ağırlıkla işle:** Pazar hacim verisi naturally düşük; Saturday-Sunday barlar z-score hesaplamasında downweight edilebilir
3. **Exchange aggregate volume kullan:** Binance + Coinbase + OKX spot toplam hacmi, tek exchange'den daha güvenilir
4. **Climax eşiğini yükselt:** Kripto yüksek volatilite nedeniyle 2.5× yerine 3.0× SMA daha az yanlış sinyal üretir
5. **On-chain whale flows ile teyit:** Exchange inflow/outflow, gerçek kurumsal hareketi hacim filtresinden daha iyi gösterir

### Net Sonuç

VSA kripto'da çalışır ama birebir import edilemez. Pattern mantığı geçerlidir (effort vs result evrensel), ancak:
- Session bazlı yorumlar geçersiz
- Eşikler yeniden kalibre edilmeli
- On-chain data ile entegrasyon VSA'nın zayıflığını telafi eder
- Test edilebilir mekanik kurallar (SC, Up Thrust, Test Bar, Effort-to-Move) spot 1D'de validate edilmeli

**En yüksek güven sırasıyla test önerisi:** Selling Climax → Test Bar → Up Thrust → Effort to Move Up → No Demand Filter.

---

## Özet — Pattern Referans Tablosu

| # | Pattern | Yön | Hacim | Spread | TEST EDİLEBİLİR |
|---|---|---|---|---|---|
| 4.1 | Stopping Volume | Bullish | Climactic | Wide | Evet |
| 4.2 | Selling Climax | Bullish | Climactic | Wide | **Evet** |
| 4.3 | No Demand | Bearish uyarı | Ultra-low | Narrow | Evet |
| 4.4 | Bag Holding / Absorpsiyon | Bullish | High | Narrow | Evet |
| 4.5 | Test Bar | Bullish | Ultra-low | Narrow | **Evet** |
| 4.6 | Successful Test | Bullish | Düşük→Orta | Dar→Normal | Hayır (2-bar) |
| 4.7 | Effort to Move Up | Bullish | High | Wide | **Evet** |
| 4.8 | Shakeout | Bullish | High | Wide | Hayır (reclaim timing) |
| 4.9 | Bullish Hammer + Vol | Bullish | High | High | Hayır (candle library) |
| 4.10 | Pseudo Up Thrust Low Vol | Bearish uyarı | Ultra-low | Normal | Hayır |
| 4.11 | Buying Climax | Bearish | Climactic | Wide | **Evet** |
| 4.12 | Up Thrust | Bearish | High | Wide | **Evet** |
| 4.13 | No Supply | Bullish uyarı | Ultra-low | Narrow | Hayır |
| 4.14 | Effort to Move Down | Bearish | High | Wide | Evet |
| 4.15 | Distribution Candle | Bearish | High | Wide | Evet |
| 4.16 | Bearish Pseudo Test | Bearish uyarı | Ultra-low | Narrow | Hayır |
| 4.17 | Hidden Up Thrust | Bearish | High | Normal | Hayır |

**Test Edilebilir Toplam: 10 / 17 pattern**

**İlk 5 Öncelikli Test (Kripto 1D):**
1. Selling Climax (4.2) — BTC major bottom indicator
2. Up Thrust (4.12) — BTC major top + short trigger
3. Test Bar (4.5) — Spring confirmation, giriş sinyali
4. Effort to Move Up (4.7) — SOS teyidi, trend başlangıcı
5. No Demand Filter (4.3) — mevcut long sinyallerine negatif filtre

---

## Cross-References

- **wyckoff_summary.md:** Phase A-E döngüsü, Spring/UTAD, P&F hedefler — VSA'nın yapısal çerçevesi
- **smc_ict_summary.md:** Liquidity grab ≈ Shakeout / Spring; order block ≈ LPS/LPSY
- **brooks_summary.md:** No demand/no supply ≈ Brooks'un "weak bar" konsepti; climactic volume ≈ "climax reversal"
- **features.py:** volume z-score (20) — VSA kategori eşlemesi için hazır feature
- **candles.py:** bullish/bearish engulfing — VSA hacim filtresiyle overlay için

---

*Bu doküman dahili RAG (Retrieval Augmented Generation) sistemi için üretilmiştir. Ticari yayın veya yeniden dağıtım için orijinal kaynaklara başvurunuz.*
