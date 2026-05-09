---
source_id: volume_price_divergence
source_type: reference_synthesis
author: Synthesis (Wyckoff, Weis, Elder, Arms, Chaikin, Granville, institutional order-flow literature)
title: Volume-Price Divergence — Focused Reference
type: reference_only
quality: 4
ingested_date: 2026-05-09
topic_tags: [volume_analysis, divergence, cvd, obv, vwap, order_flow, crypto_specific, testable_hypotheses]
---

# Volume-Price Divergence — Kapsamlı Referans Notları

> Bu doküman hacim-fiyat diverjansı konusunu tek bir odak noktasında toplar. Kaynaklar: Wyckoff (Çaba-Sonuç Yasası), Tom Williams / VSA literatürü, Alexander Elder (Elder-Ray, Volume Force), Granville (OBV), Marc Chaikin (CMF), Richard Arms (Equivolume), modern order-flow / CVD literatürü ve crypto-spesifik araştırmalar. Tek bir barı inceleyen VSA analizinden farklı olarak bu doküman **çok-bar pattern'larını** esas alır; diverjans tanımı gereği en az iki swing veya iki zirve/dip gerektirir.

---

## 1. Çerçeve — Hacim Neden Fiyatı Doğrular ya da Çürütür?

### Temel Epistemoloji

Fiyat piyasanın **sonucu**dur; hacim ise **çabasıdır**. Bu ikili, Wyckoff'un üçüncü yasasının (Effort vs Result) diverjans mantığını doğrudan kurar: büyük çabaya küçük sonuç eşlik ediyorsa, yapı sürdürülemez. Piyasa mekanik olarak şöyle işler:

- Bir yükseliş trendi içinde her rallinin yeni bir tepe yapması için katılımcıların bunu **desteklemesi** gerekir. Katılım ölçülür: işlem gören kontrat ya da coin adedi artar mı?
- Katılım azalıyor ama fiyat yeni tepe yapıyorsa, bu tepeyi taşıyan artık **geniş kalabalık değil, kaldıraçlı az sayıda aktördür**. Kaldıraç tersine döndüğünde satış hızlanır.
- Bir düşüş trendi içinde her dip için aynı simetrik mantık geçerlidir: yeni düşük fiyatlar düşük hacimle geliyorsa satış baskısı tükeniyor demektir.

### Diverjans vs Konverjans

**Konverjans (sağlıklı piyasa):** Fiyat yeni tepe yaptıkça hacim de yeni tepe yapar; fiyat yeni dip yaptıkça hacim de yeni yüksek yapar (satıcılar aktif). Bu durum trendin devamını destekler.

**Diverjans (uyarı):** Fiyat ve hacim farklı yöne çekilir. İki tipi vardır:

| Tip | Fiyat | Hacim | Anlam |
|---|---|---|---|
| Klasik Bearish Div. | Yeni HH | Daha düşük tepe | Alıcı kalabalığı azalıyor |
| Klasik Bullish Div. | Yeni LL | Daha düşük dip hacim | Satıcı kalabalığı azalıyor |
| Gizli Bullish Div. | HL (uptrend içi) | LL hacim | Trend devamı, düşük-hacimli çekilme |
| Gizli Bearish Div. | LH (downtrend içi) | HL hacim | Trend devamı, yüksek-hacimli rally = dağıtım |

### Çok-Bar Mantığı

VSA tek bir barın hacim + spread + kapanış kombinasyonunu okurken, diverjans analizi **en az iki pivot** karşılaştırır. Bu fark kritiktir:

- VSA: "Bu bar yüksek hacimli ve kapanış ortada → arz girdi"
- Diverjans: "Swing A'da X hacim vardı, Swing B'de (daha yüksek fiyat) Y < X hacim var → dağıtım süreci başlamış olabilir"

Diverjans sinyalleri bu nedenle **erken uyarı** niteliği taşır; VSA sinyalleri ise anlık yapı okumasıdır. İkisi birleştiğinde güç artar.

---

## 2. Klasik Diverjans Kalıpları

Her kalıp için: tanım, mekanik tespit kuralları, geçerlilik koşulları ve bozulma (invalidation) kriteri verilmiştir.

---

### 2.1 Bullish Diverjanslar (Long Sinyali)

#### BULL-1: Fiyat LL + Hacim HL → Bullish Reversal

**Tanım:** Fiyat ardışık iki swing low yapar; ikinci low daha düşüktür. Ama hacim ölçüldüğünde ikinci dip, birinciden **belirgin şekilde daha az hacimle** gerçekleşmiştir.

**Mekanik tespit kuralları:**
1. Swing Low A belirlenir; A'yı çevreleyen N bar içindeki toplam veya tepe hacim kaydedilir (`vol_A`).
2. Fiyat A'nın altına geçen Swing Low B belirlenir (`price_B < price_A`).
3. B'yi çevreleyen aynı uzunluktaki penceredeki hacim kaydedilir (`vol_B`).
4. Koşul: `vol_B < vol_A × 0.75` (eşik: %75 — kalibre edilebilir).
5. B'nin oluştuğu bar'ın veya sonraki 1–3 bar'ın kapanışı A bölgesine doğru **geri döner** (reclaim); bu olmadan sinyal teyitsizdir.

**Geçerlilik koşulları:**
- İki swing arasındaki mesafe en az 5 bar, en fazla 60 bar olmalı (çok kısa: gürültü; çok uzun: piyasa rejimi değişmiş olabilir).
- Arka plan trendi: düşüş trendi veya konsolidasyon içi (yükseliş trendinde bu pattern anlamsızlaşır).
- Çoklu timeframe: daha büyük TF'de destek bölgesiyle çakışıyorsa güç artar.

**Bozulma:** B bar'ının altına kapanış veya B seviyesinin yeni bir düşüş barıyla altına kırılması.

---

#### BULL-2: Fiyat Double-Bottom + Hacim Daralması → Spring Setup

**Tanım:** İki dip yaklaşık aynı seviyededir (±%0.5 fiyat toleransı), ama ikinci dibe giderken hacim belirgin şekilde düşmüştür. Bu Wyckoff Spring'in hacim boyutudur.

**Mekanik tespit kuralları:**
1. İlk dip (D1) belirlenir; D1 ± %0.5 bant içinde kalan ikinci dip (D2) aranır.
2. D1 pencere hacmi: `vol_D1`. D2 pencere hacmi: `vol_D2`.
3. Koşul: `vol_D2 < vol_D1 × 0.70` (satıcı gücsüzlüğü eşiği).
4. D2 sonrası bar'da **kapanış yukarı** (kapanış, D2'nin range'inin üst yarısında) ve ardından ortalama hacme dönüş beklenir.
5. Opsiyonel teyit: D1 ile D2 arasındaki "neckline" (lokal tepe) kırılınca hacim sıçraması — bu breakout-volume onayıdır.

**Geçerlilik koşulları:**
- İki dip arasında en az bir anlamlı rally (en az %2 fiyat hareketi) olmalı; yoksa bu double-bottom değil, flat range'dir.
- Bağlam: yatay konsolidasyon veya major destek bölgesi altında.

**Bozulma:** D2 seviyesi altına kapanış + hacim artışı kombinasyonu.

---

#### BULL-3: Düşüş Trendi + Kümülatif Hacim Düşüşü → No-Supply

**Tanım:** Fiyat birden fazla swing low yaparak aşağı giderken, **kümülatif hacim** (tüm barları toplayan süregelen toplam) ya azalıyor ya da her yeni swing low'u önceki low'undan belirgin şekilde daha düşük hacimle karşılıyor. Wyckoff terminolojisiyle: **no supply** (arz yok) durumu.

**Mekanik tespit kuralları:**
1. Düşüş trendi belirlenir: son 20 bar içinde fiyat net aşağı yönlü (SMA-20 slope negatif).
2. Her swing low için o low ± 3 bar penceresindeki toplam hacim hesaplanır.
3. Ardışık swing low hacimlerinin serisi: `vol[n] < vol[n-1] < vol[n-2]` — en az 3 ardışık azalan.
4. Teyit: ardından gelen ilk yukarı bar, önceki 10 barın ortalama hacminin en az 1.3x'i olmalı.

**Geçerlilik koşulları:**
- Bu setup'ın bozulma riski yüksektir eğer macro düşüş haberi bekleniyorsa (event-driven momentum kümülatif hacmi yanıltır).
- Kripto için: funding rate çok negatifse, short squeeze olasılığı bu pattern'ı güçlendirir.

**Bozulma:** Kümülatif hacim yeniden artışa geçer ve fiyat yeni low yapar.

---

#### BULL-4: Gizli Bullish Diverjans (Hidden Bullish)

**Tanım:** Yükseliş trendi içinde fiyat **higher low** yaparken (pullback normalden daha sığ), hacim **lower low** yapar (çekilme sırasında önceki çekilmeye göre daha az satış). Bu, alıcıların güçlü olduğunu ve trendin devam edeceğini gösterir.

**Mekanik tespit kuralları:**
1. Fiyat: `low[B] > low[A]` — B, A'dan daha yüksek (trend desteği).
2. Hacim: Pullback A sırasındaki max günlük/bar hacim `vol_A`. Pullback B sırasındaki `vol_B < vol_A × 0.85`.
3. Ana trend yönü: 50-bar SMA yukarı eğimli olmalı.
4. Ardından fiyatın ana trend yönünde devam etmesi teyittir.

**Geçerlilik koşulları:**
- Bu pattern yalnızca confirmed uptrend içinde anlamlıdır.
- Momentum oscillator (RSI, MFI) da bull momentumu korumalı.

**Bozulma:** Fiyat pullback A'nın altına geçerse (HL yapısı bozulur).

---

#### BULL-5: OBV Bullish Divergence

**Tanım:** Fiyat yeni düşük yaparken On-Balance Volume (OBV) daha yüksek dip yapar. Bu, alım hacminin gizli birikimini gösterir.

**OBV tanımı:**
```
OBV[t] = OBV[t-1] + Volume[t]  if Close[t] > Close[t-1]
OBV[t] = OBV[t-1] - Volume[t]  if Close[t] < Close[t-1]
OBV[t] = OBV[t-1]              if Close[t] == Close[t-1]
```

**Mekanik tespit kuralları:**
1. Fiyat Swing Low A: `price_A`. OBV değeri: `obv_A`.
2. Fiyat Swing Low B: `price_B < price_A`. OBV değeri: `obv_B > obv_A`.
3. Koşul: `price_B < price_A` VE `obv_B > obv_A`.
4. Lookback: iki pivot arasında 5–40 bar.
5. Teyit: ardışık 2 bar içinde kapanış önceki swing high'ın üstüne geçer.

**Geçerlilik koşulları:**
- OBV raw değeri değil, OBV slope'u veya OBV SMA üzerindeki pozisyonu kullanılabilir.
- Hacim kalitesi: gerçek borsa hacmi (kripto'da wash-trading filtrelemesi önerilir).

**Bozulma:** Fiyat B altına geçer VE OBV da yeni dip yapar.

---

#### BULL-6: VWAP Bullish Divergence

**Tanım:** Oturum bazında fiyat VWAP'ın altında seyrederken, hacim profili gün içinde yukarı ağırlıklı (VWAP yakınında veya üstünde yoğun işlem) oluşmaya başlarsa, kapanışın VWAP'a doğru çekilmesi beklenir.

**Mekanik tespit kuralları:**
1. İntraday: fiyat günün ilk 1/3'ünde VWAP altında.
2. Kümülatif delta (CVD): gün içi CVD pozitife döner (alıcılar ağır basmaya başlar).
3. Fiyat VWAP'ın ±%0.3 band'ına geri döndüğünde entry; VWAP orta nokta hedeftir.
4. SL: günlük düşüğün 1 ATR altı.

**Geçerlilik koşulları:**
- Sadece yüksek likidite oturumlarında geçerli (Londra, NY açılışı gibi).
- Kripto'da: 24h VWAP veya rolling 24h VWAP kullanılır (oturum yoktur).

**Bozulma:** Fiyat yeni günlük düşük yapar + CVD yeniden negatife döner.

---

### 2.2 Bearish Diverjanslar (Short Sinyali)

#### BEAR-1: Fiyat HH + Hacim LH → Distribution Warning

**Tanım:** Fiyat ardışık iki swing high yapar; ikinci high daha yüksektir. Ama hacim, ikinci tepede birinci tepeden belirgin şekilde **daha azdır**.

**Mekanik tespit kuralları:**
1. Swing High A: `price_A`, `vol_A`.
2. Swing High B: `price_B > price_A`, `vol_B < vol_A × 0.75`.
3. B tepesi bar'ının veya sonraki 1–3 bar'ın kapanışı A bölgesine doğru çekilir.
4. Opsiyonel: B bar'ında upper wick var (fiyat yüksekten reddedilmiş).

**Geçerlilik koşulları:**
- Arka plan: yükseliş trendi veya uzun konsolidasyon sonrası tepe.
- Büyük TF'de resistance bölgesi yakınında çalıştığında güç artar.

**Bozulma:** B üstüne kapanış + hacim artışı.

---

#### BEAR-2: Fiyat Double-Top + Hacim Daralması → Upthrust

**Tanım:** İki tepe yaklaşık aynı seviyede (±%0.5), ama ikinci tepeye giderken hacim belirgin azalmıştır. Wyckoff'ta bu **Upthrust After Distribution (UTAD)** yapısının hacim imzasıdır.

**Mekanik tespit kuralları:**
1. T1 (ilk tepe): `vol_T1`. T2 (ikinci tepe): `vol_T2`.
2. Koşul: `|price_T2 - price_T1| / price_T1 < 0.005` (aynı seviye) VE `vol_T2 < vol_T1 × 0.70`.
3. T2 sonrası bar'da kapanış düşük + hacim artışı → satış sinyali.
4. Neckline kırılışında hacim sıçraması → teyit.

**Bozulma:** T2 üstüne kapanış + hacim artışı (gerçek kırılma).

---

#### BEAR-3: Yükseliş Trendi + Kümülatif Hacim Düşüşü → Buying Climax Yaklaşıyor

**Tanım:** Fiyat yeni yüksekler yaparken, toplam işlem hacmi azalıyor. Alıcı kalabalığı seyrelmektedir; bir sonraki büyük hacim sıçraması **Buying Climax** olabilir.

**Mekanik tespit kuralları:**
1. Yükseliş trendi: 20-bar SMA yukarı eğimli, fiyat SMA üstünde.
2. Son 3 swing high için hacim serileri: `vol[n] < vol[n-1] < vol[n-2]`.
3. Trend devam eder ama her rally daha az hacimle gerçekleşir.
4. Uyarı seviyesi: bir sonraki bar'ın hacmi ortalamayı 2x+ geçerse, potansiyel climax — position azalt.

**Geçerlilik koşulları:**
- Bu pattern trend reversal değil, **uyarı** sinyalidir; trend hala yukarıdır.
- Stop-loss'ları sıkılaştırmak için kullanılır, çıkış sinyali olarak değil.

**Bozulma:** Hacim yeniden artışa geçer ve fiyat yeni high yapar (trend sağlıklı).

---

#### BEAR-4: Gizli Bearish Diverjans (Hidden Bearish)

**Tanım:** Düşüş trendi içinde fiyat **lower high** yaparken (rally normalden daha sığ), hacim **higher high** yapar — yani satıcılar rallide aktif.

**Mekanik tespit kuralları:**
1. Fiyat: `high[B] < high[A]` — B, A'dan daha düşük tepe (trend devamı).
2. Hacim: Rally A sırasındaki tepe hacim `vol_A`. Rally B sırasındaki `vol_B > vol_A × 1.15`.
3. Ana trend yönü: 50-bar SMA aşağı eğimli.
4. Ardından fiyatın düşmesi teyittir.

**Bozulma:** Fiyat rally A'nın üstüne geçerse (LH yapısı bozulur).

---

#### BEAR-5: OBV Bearish Divergence

**Tanım:** Fiyat yeni yüksek yaparken OBV daha düşük tepe yapar.

**Mekanik tespit kuralları:**
1. Fiyat Swing High A: `price_A`, `obv_A`.
2. Fiyat Swing High B: `price_B > price_A`, `obv_B < obv_A`.
3. Lookback: 5–40 bar.
4. Teyit: 2 bar içinde kapanış önceki swing low altına geçer.

**Bozulma:** Fiyat B üstüne geçer VE OBV da yeni tepe yapar.

---

## 3. Ölçülebilir İndikatörler

Her indikatör için: formül, hesaplama notu, eşik önerileri.

---

### 3.1 Cumulative Volume Delta (CVD)

**Formül:**
```
Delta[t] = Buy_Volume[t] - Sell_Volume[t]
CVD[t]   = CVD[t-1] + Delta[t]
```

`Buy_Volume`: ask'te gerçekleşen işlem hacmi. `Sell_Volume`: bid'de gerçekleşen işlem hacmi. Tick data yoksa **Tick Rule** kullanılır: `price[t] > price[t-1]` → buy; `price[t] < price[t-1]` → sell.

**Eşik önerileri:**
- CVD diverjansı: Fiyat yeni HH ama CVD daha düşük tepe → bearish. Eşik: CVD önceki tepeden en az -%5 sapma.
- CVD Spike Fade: tek bar'da CVD'nin 20-bar standart sapmasının 2.5x üstüne çıkması → ortalamaya dönüş trade'i.
- **Uyarı:** CVD hesaplama kalitesi veri kaynağına çok bağlıdır; tick data yoksa tahmin gürültülüdür.

---

### 3.2 On-Balance Volume (OBV)

**Formül (Joe Granville, 1963):**
```
OBV[t] = OBV[t-1] + Volume[t]  if Close[t] > Close[t-1]
OBV[t] = OBV[t-1] - Volume[t]  if Close[t] < Close[t-1]
OBV[t] = OBV[t-1]              if Close[t] = Close[t-1]
```

**Kullanım:**
- OBV SMA(20) üstünde: bullish momentum.
- OBV ile fiyat arasındaki diverjans: Section 2'deki BULL-5 / BEAR-5 kuralları.
- OBV trend slope: son 20 barın linear regression slope'u. Pozitif + fiyat dip → bullish div.

**Eşik önerileri:**
- OBV diverjansı için minimum lookback: 10 bar, maksimum: 50 bar.
- OBV slope değişimi (sıfır geçişi): güçlü sinyal; slope pozitife döner ama fiyat hala düşüyorsa → lead sinyal.

---

### 3.3 Volume-Weighted MACD (VW-MACD)

**Standart MACD formülü:**
```
MACD = EMA(price, 12) - EMA(price, 26)
Signal = EMA(MACD, 9)
```

**Volume-Weighted versiyon:**
```
VW_EMA(n)[t] = Σ(price[i] × volume[i]) / Σ(volume[i])  — son n bar üzerinden hacim-ağırlıklı
VW_MACD = VW_EMA(12) - VW_EMA(26)
VW_Signal = EMA(VW_MACD, 9)
```

**Eşik önerileri:**
- VW-MACD sıfır geçişi: alım/satım tetikleyici.
- Histogram artışı + fiyat momentum artışı: konverjans (sağlıklı).
- Histogram düşüşü + fiyat momentum artışı: bearish diverjans uyarısı.
- Birçok platform bunu desteklemediğinden custom hesaplama gerekebilir.

---

### 3.4 Money Flow Index (MFI)

**Formül (Gene Quong & Avrum Soudack, 1989):**
```
Typical_Price[t] = (High + Low + Close) / 3
Raw_Money_Flow[t] = Typical_Price[t] × Volume[t]
Positive_MF = Σ(Raw_MF[t])  for t where TP[t] > TP[t-1]  — son N bar
Negative_MF = Σ(Raw_MF[t])  for t where TP[t] < TP[t-1]
MFR = Positive_MF / Negative_MF
MFI = 100 - (100 / (1 + MFR))
Standart periyot: N = 14
```

**Eşik önerileri:**
- Aşırı satım: MFI < 20. Aşırı alım: MFI > 80.
- Bullish div: Fiyat LL + MFI HL (MFI 20 altından çıkarken).
- Bearish div: Fiyat HH + MFI LH (MFI 80 altında kalırken).
- Güçlü sinyal: MFI 80 üstüne çıkmaz ama fiyat yeni tepe → dağıtım.

---

### 3.5 Chaikin Money Flow (CMF)

**Formül (Marc Chaikin):**
```
Money_Flow_Multiplier[t] = ((Close - Low) - (High - Close)) / (High - Low)
Money_Flow_Volume[t] = MFM[t] × Volume[t]
CMF(N) = Σ(MFV[t], N bar) / Σ(Volume[t], N bar)
Standart periyot: N = 20 veya 21
```

**Eşik önerileri:**
- CMF > 0.05: bullish basınç sürmekte.
- CMF < -0.05: bearish basınç sürmekte.
- Crossover sıfır hattından: yön değişimi onayı.
- Diverjans: Fiyat yeni HH ama CMF daha düşük → dağıtım uyarısı. Eşik: CMF önceki tepeden -%0.10+ sapma.
- CMF kısıtlaması: close konumunu normalize eder ama mutlak hacim farkına duyarsızdır.

---

## 4. Kripto Spesifik Faktörler

Kripto piyasaları, geleneksel hacim-fiyat analizini zorlaştıran ve aynı zamanda zenginleştiren yapısal özellikler taşır.

---

### 4.1 Spot vs Perp Hacim Diverjansı (Kaldıraç Proxy'si)

**Mekanik:**
- Spot hacim: gerçek varlık değişimi — sermaye gerçekten giriyor/çıkıyor.
- Perpetual swap hacmi: kaldıraçlı pozisyon — gerçek sermaye transferi değil, speculative exposure.
- **Ratio:** `Perp_Volume / Spot_Volume`. Bu oran yükseldikçe, fiyat hareketi spekülatif kaldıraca dayanıyor demektir.

**Diverjans sinyalleri:**
- Fiyat yeni tepe + Perp/Spot ratio yüksek (>3x normalin) + Open Interest artıyor: kalabalık long, squeeze riski yüksek → bearish.
- Fiyat yeni dip + Funding rate çok negatif + Spot hacim artıyor: short squeeze + gerçek alım → bullish divergence.

**Eşik önerileri:**
- Perp/Spot ratio Z-score > 2.0: anormal spekülatif oran.
- Funding rate: 8h funding > +0.05% = aşırı long; < -0.05% = aşırı short.

---

### 4.2 DEX vs CEX Hacim İlişkisi

**Mekanik:**
- CEX hacmi anlık ve likit; ancak wash-trading içerebilir.
- DEX hacmi (Uniswap, dYdX vb.) manipüle edilmesi daha zordur; gerçek on-chain settle.

**Diverjans sinyalleri:**
- CEX fiyat rallisi + DEX hacim artmıyor: CEX'te kaldıraçlı oyun, gerçek talep yok → bearish.
- CEX fiyat düşüşü + DEX stablecoin → token swap'ları artıyor: gerçek alım → bullish.
- DEX hacim spike, CEX'ten önce: on-chain sniper veya bilgili para → erken sinyal.

**Veri kaynakları:** Glassnode, Nansen, Dune Analytics, The Block.

---

### 4.3 Stablecoin Hacim — "Taze Sermaye" Proxy'si

**Mekanik:**
- Stablecoin exchange inflows (USDT/USDC borsaya girişi): yeni alım gücü hazırlanıyor → bullish.
- Stablecoin exchange outflows: kar alma / çekilme → risk azalıyor.
- Stablecoin supply artışı (mint): piyasaya yeni para geliyor — boğa cycle'ı yakıtı.

**Diverjans sinyalleri:**
- Fiyat düşüyor ama stablecoin inflows artıyor (alıcılar hazırlanıyor) → dip yakın.
- Fiyat yükseliyor ama stablecoin inflows düşüyor (mevcut sermaye döndürülüyor, yeni para yok) → rally tükeniyor.

**Eşik önerileri:**
- 7-day rolling stablecoin inflow Z-score > 1.5: anormal taze sermaye girişi.
- 30-day stablecoin supply büyüme hızı: yatay veya azalıyorsa likidite azalıyor.

---

## 5. Test Edilebilir Hipotez Adayları

Her hipotez için: pre-registration formatında kurular, entry/SL/TP, ve engulfing sistemiyle dekorrelasyon notu.

---

### HYP-01: OBV Diverjansı + Engulfing Confluence Filter

**Hipotez:** OBV bullish diverjansı tek başına işlem edilmeden, aynı bölgede bullish engulfing konfigürasyonu ile örtüştüğünde anlamlı pozitif beklenti üretir.

**Mekanik kurallar (pre-registration):**
1. Fiyat Swing Low A ve B tespiti: `price_B < price_A`.
2. OBV: `obv_B > obv_A` (Section 2, BULL-5 kuralları).
3. B noktasında veya B'yi izleyen 3 bar içinde: bullish engulfing bar (mevcut sistemin engulfing tanımı geçerli).
4. Engulfing bar'ın kapanışı B low'unun en az 0.5 ATR üstünde.
5. Entry: engulfing bar kapanışı.
6. SL: engulfing bar'ın low'u − 0.3 ATR.
7. TP1: A seviyesi (swing high A ile swing high arasındaki tepe).
8. TP2: 2R.

**Beklenen etki:** OBV div. tek başına yaklaşık %53–55 win-rate (literatür tahmini, düşük edge). Engulfing confluence filter win-rate'i %58–63 bandına taşımalı ve yanlış sinyal filtresi olarak çalışmalı.

**Dekorrelasyon notu:** Engulfing sistemi trend ve yatay kontekste sinyal üretiyor. Bu hipotez, engulfing'i **sadece OBV diverjansının teyitlendiği** noktalarda işler — bu subset, raw engulfing'den istatistiksel olarak bağımsızdır (farklı tetikleyici, farklı giriş mantığı).

**Backtest parametreleri:** Lookback 10–40 bar (optimize et), hacim eşiği OBV slope sign change, minimum 200 trade sample.

---

### HYP-02: CVD Spike Fade — Aşırı Delta Geri Dönüşü

**Hipotez:** Tek bar'da CVD'nin rolling 20-bar standart sapmasının 2.5σ üstüne çıkması, ardından fiyatın ortalamaya dönüşü ile sonuçlanır.

**Mekanik kurallar:**
1. `CVD_zscore[t] = (CVD[t] - CVD_mean_20[t]) / CVD_std_20[t]`.
2. Koşul: `CVD_zscore > 2.5` (bullish spike) → fade için SHORT entry.
3. Koşul: `CVD_zscore < -2.5` (bearish spike) → fade için LONG entry.
4. Entry: spike bar kapanışı.
5. SL: spike bar'ın extreme (high veya low) + 0.5 ATR.
6. TP: 1R veya CVD_zscore < 1.0 olduğunda kapatma.

**Beklenen etki:** Mean-reversion; özellikle likidite tuzakları (liquidity grab) sonrasında etkili. Kaldıraçlı kripto piyasasında spike'ların %60–70'i reversal ile sonuçlanır (varsayım — test edilmeli).

**Dekorrelasyon notu:** Bu strateji momentum/trend engulfing'den tamamen farklıdır; reversal mantığı ile çalışır ve pozitif korelasyon beklenmez.

**Backtest parametreleri:** Tick data veya 1m-bar data gerekli. Kripto için Binance spot ve perp ayrı test edilmeli.

---

### HYP-03: Stopping Volume + Price Reversal (VSA–Diverjans Crossover)

**Hipotez:** Yüksek hacimli (Z-score > 2.0) ama küçük spread'li bar, ardından fiyat geri dönüşü ile sonuçlanır. Bu mevcut `volume_z_score` modülüyle doğrudan entegre edilebilir.

**Mekanik kurallar:**
1. `vol_zscore[t] > 2.0` (anormal hacim).
2. Bar spread: `(High - Low) < 0.8 × ATR_20` (küçük spread — effort ama az result).
3. Kapanış: bar range'inin ortasına yakın (kapanış range'in %30–70 arasında) — net yön yok.
4. Sonraki 2 bar içinde fiyat önceki close'dan farklı yöne kapanırsa → reversal teyiti.
5. Entry: teyit bar'ının kapanışı.
6. SL: stopping volume bar'ının extreme'i.
7. TP: 1.5R veya önceki pivot.

**Beklenen etki:** Wyckoff literatüründe "stopping volume" veya "test" olarak geçen bu yapı, net directional input olmadan büyük hacim absorbsiyonunu gösterir. Edge kaynağı: absorpsiyon tamamlandıktan sonra ters taraf devreye girer.

**Dekorrelasyon notu:** Engulfing bar geniş spread gerektirir; stopping volume küçük spread gerektirir. Bu iki pattern yapısal olarak farklıdır — dekorele.

**Backtest parametreleri:** `volume_z_score` threshold 2.0 ile 3.0 arasında sweep. Spread threshold: 0.5–1.0 ATR.

---

### HYP-04: Perp/Spot Hacim Oranı Extremes + Price Fade (Kripto Spesifik)

**Hipotez:** Perp/Spot hacim oranının 20-günlük ortalamanın 3 standart sapması üstüne çıkması (spekülatif aşırılık), ardından 2–5 bar içinde fiyat geri dönüşü ile sonuçlanır.

**Mekanik kurallar:**
1. `ratio[t] = perp_vol[t] / spot_vol[t]`.
2. `ratio_zscore[t] = (ratio[t] - mean_ratio_20) / std_ratio_20`.
3. Koşul bearish: `ratio_zscore > 3.0` VE `open_interest 5 günde +%15+ artmış`.
4. Koşul bullish: `ratio_zscore < -2.0` VE `funding_rate < -0.04%`.
5. Entry: koşulun oluştuğu günün kapanışı.
6. SL: 3 ATR.
7. TP: 5 bar sonrası piyasa fiyatı (time-based exit) veya ratio normalize olunca.

**Dekorrelasyon notu:** Spot fiyat + on-chain veri kombinasyonu; engulfing sistemiyle doğrudan overlap yok.

**Veri bağımlılığı:** Binance perp ve spot API, Coinglass (OI verileri), Glassnode (funding rates).

---

### HYP-05: MFI Aşırı Satım Diverjansı + Trend Filter

**Hipotez:** MFI < 20 iken fiyat yeni LL yapar ama MFI yeni LL yapmaz (bullish MFI diverjansı), VE arka plan rejimi yatay veya hafif yukarı eğimliyse, uzun entry anlamlı pozitif beklenti üretir.

**Mekanik kurallar:**
1. MFI lookback: 14 bar.
2. Fiyat: `low[B] < low[A]`, A ve B arası 10–30 bar.
3. MFI: `mfi_B > mfi_A` VE `mfi_B < 25` (aşırı satım bölgesi).
4. Regime filter: ADX < 25 (trend yok) VEYA 50-bar SMA slope pozitif.
5. Entry: MFI 25 bandını yukarı geçtiğinde.
6. SL: low[B] − 0.5 ATR.
7. TP: 2R.

**Beklenen etki:** MFI diverjansı tek başına %52–55 win-rate (gürültü fazla). Trend filtresi eklenmesi bu oranı artırmalı. Aşırı satım koşulunun sona ermesi tetikleyici olarak kullanılması, random entry'den üstün olmalı.

**Dekorrelasyon notu:** Engulfing volume + close-based; MFI typical-price × volume tabanlı. Matematiksel olarak farklı hesaplama — korelasyon düşük ama tam bağımsız değil (ikisi de hacim kullanır).

---

### HYP-06 (Bonus): No-Supply Rally + Engulfing (Trend Continuation)

**Hipotez:** Yükseliş trendi içinde kümülatif hacim azalarak gerçekleşen pullback (no-supply), arkasından bullish engulfing ile sonuçlandığında, trend devamı için yüksek kaliteli giriş üretir.

**Mekanik kurallar:**
1. 50-bar SMA yukarı eğimli.
2. Pullback içinde son 3 bar'ın hacmi: azalan seri (`vol[t] < vol[t-1] < vol[t-2]`), her biri < ortalama.
3. Düşük hacimli pullback barları toplamı ≥ 3.
4. Pullback sonunda bullish engulfing (mevcut sistem tanımı).
5. Engulfing bar hacmi: ortalama hacmin en az 1.2x üstünde.
6. Entry: engulfing bar kapanışı.
7. SL: engulfing bar low − 0.3 ATR.
8. TP: 2R.

**Beklenen etki:** "Sağlıklı düzeltme + momentum dönüşü" kombinasyonu. Grimes literatüründe pullback-to-MA setup'ının en güçlü varyantlarından biriyle örtüşür.

**Dekorrelasyon notu:** Bu mevcut engulfing sistemine eklenen bir **ön filtredir** — bağımsız strateji değil, mevcut sistemin alt seti. Ama bu subset'in base engulfing'den istatistiksel olarak farklı olduğu test edilmeli.

---

## 6. Quantifiable Test Suite

Diverjans pattern'larının geriye dönük testinde standartlaştırılmış parametreler.

---

### 6.1 Lookback Windows

| Pattern Tipi | Minimum Bar | Maksimum Bar | Öneri |
|---|---|---|---|
| Klasik diverjans (HH/LL) | 5 | 60 | 10–40 |
| OBV diverjans | 5 | 50 | 10–30 |
| MFI diverjans | 10 | 40 | 14–28 |
| CVD spike | 1 bar | 1 bar | rolling 20-bar std |
| Kümülatif no-supply | 3 bar | 15 bar | 3–8 bar seri |

---

### 6.2 Diverjans Tespit Eşikleri

**Hacim eşiği (klasik pattern):**
- Zayıf: `vol_B < vol_A × 0.90` — çok fazla false positive.
- Orta: `vol_B < vol_A × 0.75` — başlangıç eşiği.
- Güçlü: `vol_B < vol_A × 0.60` — az sinyal, yüksek kalite.
- Test önerisi: 0.60 ile 0.90 arasında 0.05 adımlarla sweep.

**OBV diverjans eşiği:**
- OBV mutlak fark yerine slope kullanılır; slope değişimi: son 5 bar linear regression.
- Minimum eşik: `obv_slope_B > 0` iken `obv_slope_A < 0` veya `obv_B > obv_A × 1.02`.

**CVD Z-score eşiği:**
- Başlangıç: ±2.0σ. Güçlü: ±2.5σ. Aşırı: ±3.0σ.

---

### 6.3 Teyit Bar Kuralları

Her pattern için teyit bar zorunlu tutulmalıdır:

| Pattern | Teyit Tanımı | Maksimum Bekleme |
|---|---|---|
| BULL-1, BULL-2 | Diverjans noktasından sonra yukarı kapanış | 3 bar |
| BULL-5 (OBV) | Önceki swing high kırılması | 5 bar |
| BEAR-1, BEAR-2 | Aşağı kapanış | 3 bar |
| CVD Spike Fade | CVD zscore 1.0 altına düşüş | 5 bar |
| MFI | MFI 25 bandı üstüne geçiş | 5 bar |

Teyit süresi içinde sinyal gelmezse: **geçersiz say ve geç**.

---

### 6.4 Çok Zaman Dilimleri Hizalaması

**Öneri (asgari):**
- Entry TF: işlem yapılan zaman dilimi (örn. 1h).
- Onay TF: 1 üst (örn. 4h).
- Makro TF: 2 üst (örn. 1D).

**Hizalama kuralı:** Onay ve Makro TF'de trend veya structure, Entry TF sinyaliyle çelişmiyor olmalı. Önerilen: 3 TF'nin 2'sinde onay.

**Pratik uygulama:**
- Onay TF'de: büyük destek/resistance bölgesiyle çakışma.
- Makro TF'de: overall regime (trend/range/breakout) Entry TF sinyali ile uyumlu.

---

### 6.5 Minimum Örnek Boyutu ve İstatistiksel Eşik

Grimes standardı esas alınarak:
- Minimum: 100 işlem (güvenilir değil, referans için).
- Tercih edilen: 200+ işlem.
- Güçlü: 500+ işlem, farklı semboller ve periyotlar.

**İstatistiksel anlamlılık:**
- Win rate: p-value < 0.05 binomial test, null = %50.
- Profit factor: > 1.3 (edge olduğuna kanıt olabilecek minimum seviye).
- Sharpe: > 0.5 (risk-adjusted basis için minimum).
- Maksimum drawdown: < geri kazanım için beklenen süre × günlük ortalama gelir.

**Walk-forward zorunlu:** In-sample optimization, out-of-sample validation — en az %30 OOS reserved.

---

## 7. Mevcut Sistemle Bağlantı

---

### 7.1 `volume_z_score` → Diverjans Augmentasyonu

Mevcut sistemde `volume_z_score` tek bar'ın hacmini normalize eder. Diverjans augmentasyonu:

```python
# Mevcut
vol_z = (volume[t] - volume_mean_20) / volume_std_20

# Augmentation: swing-level diverjans skoru
swing_vol_ratio = vol_swing_B / vol_swing_A  # Section 2 eşik: < 0.75 = diverjans
divergence_flag = 1 if swing_vol_ratio < 0.75 else 0
```

Bu iki sinyal **birleştirilebilir:**
- `vol_z` yüksek + `divergence_flag` = 0: normal yüksek hacim, teyit yok.
- `vol_z` düşük + `divergence_flag` = 1: klasik no-supply/no-demand sinyal.

---

### 7.2 Engulfing'e Diverjans Filtresi

Mevcut engulfing sinyalleri üzerine pre-filter olarak:

```
engulfing_signal = True
obv_divergence = True  # HYP-01 kuralları
no_supply_pullback = True  # HYP-06 kuralları

final_signal = engulfing_signal AND (obv_divergence OR no_supply_pullback)
```

Bu filtreleme mevcut sinyal sayısını azaltır ama kalite artışı sağlamalı — backtest ile doğrulanmalı.

---

### 7.3 Standalone Diverjans Strateji Adayları

Mevcut engulfing sisteminden **bağımsız** çalışabilecek:

| Strateji | Bağımlı Veri | Kompleksite |
|---|---|---|
| CVD Spike Fade (HYP-02) | Tick / 1m bar, CVD | Orta |
| Perp/Spot Ratio (HYP-04) | CEX API dual feed | Yüksek |
| OBV + Engulfing (HYP-01) | OHLCV | Düşük |
| Stopping Volume (HYP-03) | OHLCV | Düşük |
| MFI Diverjans (HYP-05) | OHLCV | Düşük |

Düşük kompleksiteli adaylar öncelikle test edilmeli.

---

## 8. Kritik Değerlendirme — Edge Persistent mi, Arbitrajlanmış mı?

Bu bölüm, diverjans indikatörlerinin gerçekten kullanılabilir edge taşıyıp taşımadığını değerlendirir.

---

### Arbitrajlanmış Bölgeler (Dikkat)

**OBV:** 1963'te Granville tarafından tanımlandı. Onlarca yıldır bilinmekte. Standart OBV diverjansının çok geniş kitleler tarafından izlendiği bilinmektedir. Yeterince takipçisi olan bir sinyal, kendi kendini iptal eder — arbitrajcılar erken hareket eder ve sinyal daha az güvenilir hale gelir. Akademik literatür OBV'nin tek başına anlamlı alpha üretmediğini gösteriyor (Granville 1963'ten bu yana pek çok akademik çalışma, OBV'nin raw predictive power'ının zayıf olduğunu ortaya koydu). **Sonuç: OBV tek başına edge'i düşük; filtreleme ile kullanılmalı.**

**MFI / CMF:** Bunlar da yaygın indikatörler. Retail platformlarda standart olarak mevcutlar. Aşırı satım/alım sinyalleri kalabalık işlem yeri. Kalabalık yerlerde edge erozyon hızlıdır. **Sonuç: Standalone kullanımda edge zayıf; bir yapısal seviye veya konfirmasyon ile kombine edilmeli.**

**Klasik Bullish/Bearish Divergence (RSI-Price, MFI-Price):** Finviz, TradingView gibi platformlarda otomatik tarama araçları mevcuttur; bu sinyaller gerçek zamanlı olarak milyonlarca kullanıcıya yayınlanır. Bu durum, sinyalin **kendi kendini yiyen** bir yapıya girmesine neden olur. **Sonuç: Filtresiz kullanım edge'i zayıf; bağlamsal overlay şart.**

---

### Edge'i Persistent Olabilecek Alanlar

**CVD (Cumulative Volume Delta):** Gerçek tick-level data gerektirir. Retail erişimi sınırlı; çoğu platform tahmini CVD sağlar. Tick-accurate CVD hesabı, kurumsal veri altyapısı gerektirir. **Sonuç: Kaliteli veri ile edge olabilir; retail arbitrajı zordur.**

**Perp/Spot Ratio (Kripto):** Bu sinyal DeFi/CEX arasındaki yapısal bilgi asimetrisini kullanır. Mainstream retail ekranlarında standart olarak görüntülenmiyor. Çapraz borsa veri entegrasyonu gerektirir. **Sonuç: Edge henüz daha az arbitrajlanmış; kripto spesifik avantaj.**

**Stablecoin Flow (Kripto):** On-chain veri, blockchain analizi gerektirir. Glassnode, Nansen gibi ücretli veri servisleri; geniş retail kitlesi kullanmıyor. **Sonuç: Edge görece persistent; veri engeli yüksek.**

**Kümülatif No-Supply Serisi (3+ ardışık düşük hacim bar):** Bu kalıp mevcut tüm platformlarda otomatik taranamaz; custom kod gerektirir. Geniş arbitraj baskısı yok. **Sonuç: Edge kısmen korunuyor.**

**Volume-Price Diverjans + Yapısal Seviye (Confluence):** Diverjansın tek başına değil, major destek/resistance, Wyckoff Spring bölgesi, VWAP gibi yapısal seviyelerle örtüştüğünde kullanılması, sinyalin kontekstsiz kullanımından istatistiksel olarak farklılaşır. Confluence filtresi retail kalabalığını eliyor. **Sonuç: Confluence edge'i artırır ve arbitraj baskısını azaltır.**

---

### Özet Değerlendirme Tablosu

| İndikatör / Yöntem | Retail Kalabalığı | Edge Durumu | Öneri |
|---|---|---|---|
| Raw OBV diverjansı | Çok yüksek | Zayıf | Confluence filtresi şart |
| Raw MFI/CMF diverjansı | Yüksek | Zayıf | Bağlamsal overlay ile kullan |
| Klasik MACD diverjansı | Çok yüksek | Minimal | Tek başına işleme |
| CVD (tick-accurate) | Düşük | Orta–İyi | Veri kalitesi kritik |
| Perp/Spot Oranı | Düşük | Orta–İyi | Kripto platformuna özel |
| Stablecoin Flow | Çok düşük | İyi | Swing TF'de anlamlı |
| No-Supply Seri | Düşük | Orta | Custom kodlama gerekli |
| Confluence Diverjans | Orta | İyi | Ana strateji yaklaşımı |

**Ana sonuç:** Diverjans indikatörleri wholesale olarak değil, **filtrelenmiş ve yapısal seviye konfirmasyonlu** kullanıldığında edge koruması sağlanabilir. Ham indikatör sinyali = arbitrajlanmış; yapısal bağlam + hacim kalite filtresi = daha az arbitrajlanmış.
