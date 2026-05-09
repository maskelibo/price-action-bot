---
source_id: market_structure_order_flow
source_type: synthesis
author: Multi-source synthesis (ICT/SMC, Wyckoff, Brooks, Harris, Coulling, Volume Profile)
title: Market Structure & Order Flow — Derin Referans
type: reference_only
quality: 5
ingested_date: 2026-05-09
topic_tags: [market_structure, order_flow, BOS, CHoCH, order_block, liquidity, wyckoff, volume_profile, multi_timeframe, ICT, SMC, brooks, harris_microstructure]
---

# Market Structure & Order Flow — Derin Referans

> Bu doküman, ICT/SMC, Wyckoff, Al Brooks, Larry Harris (mikroyapı), Anna Coulling ve Volume Profile literatürünün sentezi olup dahili RAG kullanımı için hazırlanmıştır. Hiçbir orijinal kaynak doğrudan kopyalanmamıştır; metodolojik özet ve mekanik kural formülasyonu amaçlanmaktadır.

---

## 1. Çerçeve — Yapısal Analiz Nedir?

Yapısal analiz, fiyat hareketini rastgele bir süreç olarak değil, **arz ve talep dengesinin grafiksel izi** olarak okuma girişimidir. Farklı okullar bu izi farklı terimlerle niteler; ancak birkaç temel ilke üzerinde örtüşürler:

**1.1 Fiyat Hareketin Belleği Vardır**

Fiyat bir kez anlamlı bir seviyede "iş gördüyse" — yani o seviyede büyük hacimli emir akışı gerçekleştiyse — o seviye gelecekte de çekim merkezi olmaya devam eder. Wyckoff bunu "sebep birikimi" olarak adlandırır; modern mikroyapı (Harris, "Trading and Exchanges") bunu limit order book'taki gizli likiditenin yeniden aktive olması olarak açıklar; SMC ise "kurumsal order block" olarak etiketler. Terminoloji farklı, mekanizma aynı.

**1.2 Piyasa Yapısı Hiyerarşiktir**

Weekly trend içinde günlük kosolidasyonlar, günlük konsolidasyon içinde saatlik trendler yaşanır. Brooks'un "always-in" kavramı, hangi zaman diliminde bakılırsa bakılsın her an bir "dominant side" olduğunu ifade eder. Bu hiyerarşi göz ardı edildiğinde, alt dilimde trend takip etmek aslında üst dilimde konsolidasyonun ortasında pozisyon almak anlamına gelebilir.

**1.3 Yapısal Analiz = Fiyat Hareketini Etiketlemek Değil, Soru Sormak**

Iyi yapısal analiz şu soruyu sorar: "Bu fiyat neden buraya geldi? Buraya gelmek için hangi emirler gerekiyordu? Arkasında kim vardı?" Etiketleme (HH, HL, OB, BOS...) yalnızca bu soruların çerçevesini oluşturur; tanı koyma değil, hipotez üretme sürecidir. SMC topluluğunun yaygın hatası, etiketlemeyi analize karıştırmaktır — grafik üstüne renkli kutular çizmek, o kutunun ne işe yarayacağını açıklamaz.

**1.4 Mekanik ve Subjektif Arasındaki Gerilim**

Wyckoff'tan Brooks'a, ICT'den Coulling'e kadar bütün structuralist okullar "discretionary" (isteğe bağlı, bağlamsal) unsurlar içerir. Bu durum, kaçınılmaz bir geriliim yaratır: yapıyı güzel tanımlayan kurallar, kaçınılmaz olarak örtüşen veya çelişen sinyaller üretir; bu çelişkileri çözmek için insan yargısına gerek duyulur. Algoritmik sistem kurarken bu gerilimi "mekanik kural + filtre katmanı" mimarisiyle çözmek gerekir: önce mekanik kural üret, sonra yanlış pozitif oranını ölçerek filtre tasarla.

**1.5 Bu Dokümanın Amacı**

Bu referans, basit HH/HL ötesindeki yapısal kavramları, her biri için mekanik tespit kuralları ile birlikte listelemektedir. Sistemdeki `signals/structure.py` modülüne yönelik genişletme önerileri Bölüm 11'de ele alınmaktadır.

---

## 2. Trend Yapısı — Detaylı Taksonomi

### 2.1 Temel Swing Tanımları

**Swing High (Pivot High):** Bar `t`, sol ve sağındaki `n` barda en yüksek high'a sahipse swing high'tır.

```
swing_high(t) = True  iff  max(high[t-n : t-1]) < high[t]  AND  max(high[t+1 : t+n]) < high[t]
```

Sistemdeki `signals/structure.py::swing_highs(df, n=2)` bu tanımı uygular. Standart değerler:
- **n=2:** gürültülü, çok sayıda swing, scalping TF için
- **n=3:** dengeli, intraday (1H, 4H) için yaygın
- **n=5:** az sayıda büyük swing, 1D ve üstü için önerilen

**Önemli:** Swing etiketleri, tanım gereği geriye dönük (`t+n` anında bilinir). Canlı sistemde mevcut bar'ı swing olarak işaretlemek lookahead hatasıdır. Güvenli kullanım: `swing[t]` bayrağı yalnızca `t <= current_bar - n` koşulunda okunabilir.

**Swing Low (Pivot Low):**

```
swing_low(t) = True  iff  min(low[t-n : t-1]) > low[t]  AND  min(low[t+1 : t+n]) > low[t]
```

### 2.2 HH / HL / LH / LL Taksonomi

| Etiket | Açıklama | Koşul |
|--------|----------|-------|
| **HH** (Higher High) | Önceki swing high'dan yüksek | `swing_high[t] > last_swing_high` |
| **HL** (Higher Low) | Önceki swing low'dan yüksek | `swing_low[t] > last_swing_low` |
| **LH** (Lower High) | Önceki swing high'dan düşük | `swing_high[t] < last_swing_high` |
| **LL** (Lower Low) | Önceki swing low'dan düşük | `swing_low[t] < last_swing_low` |

**Uptrend koşulu:** Ardışık HH VE HL serisi (en az 2 HH + 2 HL).
**Downtrend koşulu:** Ardışık LH VE LL serisi.

### 2.3 Equal Highs / Lows (EQH/EQL)

İki swing high "equal" sayılır eğer fiyat farkı ATR'nin %X'inden küçükse:

```
equal_highs(t1, t2) = abs(swing_high[t1] - swing_high[t2]) < ATR(14) * tolerance
```

Önerilen `tolerance = 0.15` (ATR'nin %15'i). Bu eşiğin altındaki çiftler liquidity pool olarak işaretlenir (Bölüm 5).

**Near-equal:** Tolerance %15–30 arasında; bu alan "soft liquidity" bölgesi olarak görülür, kesin hedef değil çekim bölgesidir.

### 2.4 Internal vs External Structure

**External Structure (Macro Swing):** HTF (örneğin 1W veya 1D) zaman diliminin swing high/low'larına karşılık gelir. Büyük lot kurumsal emirlerin gerçekleştiği seviyelerdir.

**Internal Structure (Micro Swing):** LTF (örneğin 4H veya 1H) zaman diliminin kendi içindeki yapısı. External bir HL içinde, internal bir mini downtrend ve ardından toparlanma (LTF BOS) gözlemlenebilir.

**Kurumsal mevkide:** Uzun vadeli trendde LTF internal structure kırılmaları, HTF yapının sağlamlığını test eder. LTF internal CHoCH + HTF OB birleşimi güçlü entry confluence sağlar.

### 2.5 Market Structure Levels (MSL)

MSL, son anlamlı swing low veya swing high'tır — yani bir trendin "artık bu bar aşılırsa trend bozulur" seviyesi. Brooks'un "prior swing high/low" kavramıyla örtüşür.

- **Bullish MSL:** Son confirmed swing low. Bu seviyenin altına close-based kırılma = bearish CHoCH.
- **Bearish MSL:** Son confirmed swing high. Bu seviyenin üstüne close-based kırılma = bullish CHoCH.

MSL seviyeleri, stop-loss yerleştirme için teorik referanstır; risk/reward hesabında kullanılır.

---

## 3. Yapısal Kırılımlar (Structure Breaks)

### 3.1 Break of Structure (BOS) — Trend Devamı

**Tanım:** Trendin mevcut yönünde, son swing high (uptrend) veya swing low (downtrend) kırılmasıdır.

**Mekanik kural:**
```python
# Bullish BOS
bullish_BOS = (close[t] > last_confirmed_swing_high) AND (current_trend == "up")

# Bearish BOS
bearish_BOS = (close[t] < last_confirmed_swing_low) AND (current_trend == "down")
```

**Eşik seçimi:**
- **Close-based BOS (önerilen):** Gürültüye karşı dayanıklı, false break oranı düşük.
- **Wick-based BOS:** Daha hızlı sinyal, ancak %20–35 daha fazla false positive.
- **Body-close BOS (en katı):** `(open[t] < last_high < close[t])` — tüm bar gövdesi bölgeyi aşar. Crypto 1D'de false positive minimizasyonu için tercih edilir.

### 3.2 Change of Character (CHoCH) — Dönüş Sinyali

**Tanım:** Mevcut trendin *karşı yönünde* bir kırılma. Uptrend'de son HL'nin altına kırılma = bearish CHoCH. Downtrend'de son LH'nin üstüne kırılma = bullish CHoCH.

**Mekanik kural:**
```python
# Bearish CHoCH (uptrend'de)
bearish_CHoCH = (close[t] < last_confirmed_swing_low) AND (current_trend == "up")

# Bullish CHoCH (downtrend'de)
bullish_CHoCH = (close[t] > last_confirmed_swing_high) AND (current_trend == "down")
```

**BOS vs CHoCH ayrımı:** Bir trendin ilk karşı-yönlü kırılması daima CHoCH'dir. Ardından yeni trendin kendi yönünde yapılan kırılmalar BOS olur. Bu ayrım trend-state makinesinde (`trend_state` değişkeni) takip edilmelidir.

**Hiyerarşi notu:** CHoCH bir "reversal warning" değil, bir "reversal signal"dır. CHoCH tek başına yeterli giriş koşulu değildir; çoğu sistem CHoCH + geri çekilme (retracement) + LTF BOS üçlüsünü arar.

### 3.3 Liquidity Grab (False Break)

**Tanım:** Fiyat bir önceki swing high/low'u kısa süre geçer (1–3 bar), ardından hızla orijinal bölgenin içine döner. Stop-loss emirlerini tetiklemek üzere tasarlanmış hareket.

**Mekanik tespit:**
```python
liquidity_grab_high = (
    (high[t] > last_swing_high) AND          # penetrasyon
    (close[t] < last_swing_high) AND          # reclaim (aynı bar kapanış)
    (high[t] - close[t]) > (close[t] - open[t]) * 1.5  # uzun üst wick
)
```

**Filtre:** Penetrasyon derinliği ATR(14)'ün %50'sinden az olmalı; daha derin penetrasyon gerçek BOS'a işaret eder.

### 3.4 Inducement (False BOS to Trap)

**Tanım:** Fiyat, bir önceki swing'i kırar, retail trader'ları trend devamına çeker (BOS gibi görünür), ardından sert dönüş yapar. SMC'de "inducement" = kasıtlı tuzak.

**Mekanik tespit:**
```python
inducement = (
    bullish_BOS AND                    # ilk görünüm: BOS
    (close[t+1] < last_swing_high) AND # bir bar sonra reclaim
    (close[t+1] < open[t+1])          # bearish reversal bar
)
```

**Not:** Inducement, liquidity grab'dan farkını BOS büyüklüğüyle ifade eder: liquidity grab çoğu zaman swing'i "dokunur"; inducement swing'i anlamlı biçimde geçer. Aradaki gri bölge belirsizdir — bu SMC'nin en subjektif noktalarından biridir.

**Test edilebilir hipotez (H-1):** "BOS bar'ı ertesi bar içine geri kapatırsa, o BOS'u inducement say ve reversal pozisyonu kur." — Crypto 1D'de bu hipotez Bölüm 10'da ele alınmaktadır.

---

## 4. Order Block Kavramları (15+ Spesifik Tür)

Order block (OB), kurumsal emanet emirlerinin büyük olasılıkla kaldığı fiyat bölgesidir. Aşağıdaki tanımlar mekanik tespit kurallarıyla birlikte verilmiştir.

### 4.1 Bullish Order Block (Bullish OB)

**Tanım:** Güçlü yukarı displacement (sert yükseliş hareketi) öncesindeki **son bearish bar** (veya bearish bar dizisindeki son).

**Mekanik kural:**
```
displacement = range(t+1 to t+3) > ATR(14) * 2.0  AND  close[t+3] > open[t]   # örnek
bullish_OB = last_bearish_bar_before_displacement
OB_zone = [low[t_OB], high[t_OB]]
```

**Giriş:** Fiyat OB bölgesine geri çekildiğinde (mitigation) long giriş.
**Geçersizlik:** Fiyat OB'nin altına close-based kapanırsa OB geçersizdir.

### 4.2 Bearish Order Block (Bearish OB)

**Tanım:** Güçlü aşağı displacement öncesindeki **son bullish bar**.

```
bearish_OB = last_bullish_bar_before_bearish_displacement
OB_zone = [low[t_OB], high[t_OB]]
```

**Giriş:** Fiyat OB bölgesine geri çekildiğinde short giriş.

### 4.3 Mitigation Block

**Tanım:** Fiyatın OB bölgesine girip **ama zayıf reaksiyon göstererek** (küçük body, düşük momentum) çıktığı senaryo. OB ilk testinde mitigation tamamlanmış sayılır ama trend devamı gözlemlenmez. Bu OB artık zayıflamıştır.

**Mekanik etiket:** OB'ye erişim sonrasında 3 bar içinde `close > (OB high + ATR * 0.3)` gerçekleşmezse OB "mitigated" olarak işaretlenir.

### 4.4 Breaker Block

**Tanım:** Fiyatın içinden geçtiği (broke through) ve artık ters yönde destek/direnç görevi gören eski OB. Bullish OB fiyat tarafından kırıldıktan sonra, o bölge bearish breaker'a dönüşür.

```python
bullish_OB_broken = close[t] < OB_low  # fiyat OB'nin altında kapanıyor
bearish_breaker = OB_zone  # artık ters yönlü direnç
```

**Kullanım:** Fiyat bearish breaker'a geri döndüğünde short bias, OB'nin high bölgesinde direnç bekle.

### 4.5 Inversion Fair Value Gap (IFVG)

**Tanım:** Fair Value Gap (FVG), üç bar arasındaki boşluktur: `high[t-1] < low[t+1]` (bullish FVG) veya `low[t-1] > high[t+1]` (bearish FVG). Bu gap doldurulup (mitigated) ardından fiyat karşı yönde hareket ederse, gap artık "inverted" olmuştur — eski destek direnç, eski direnç destek.

```python
# Bullish FVG
fvg_bullish = low[t+1] > high[t-1]
fvg_zone = [high[t-1], low[t+1]]

# IFVG: fvg fill (close < high[t-1]) sonrası bearish move
IFVG_bearish = fvg_bullish AND fill_confirmed AND close_below_fvg_midpoint
```

**FVG tespit eşiği:** `gap_size = low[t+1] - high[t-1] > ATR(14) * 0.1` (çok küçük gaplar anlamsız).

### 4.6 Fair Value Gap (FVG) — Standart

**Bullish FVG:** Three-candle pattern, ortadaki bar momentum'lu bullish, üçüncü bar low > birinci bar high.
**Bearish FVG:** Ortadaki bearish, üçüncü bar high < birinci bar low.

**Gap bölgesi:** `[high[t-1], low[t+1]]` bölgesi "imbalance" alanı — teorik olarak fiyatın geri dönüp dolduracağı bölge.

**Mekanik fill kuralı:** Fiyat gap bölgesinin en az %50'sini yeniden ziyaret etmişse FVG "filled" sayılır.

### 4.7 Volume Imbalance

Bitişik iki bar arasında overlap yoksa (bir bar'ın low'u önceki bar'ın high'ından yüksek) volume imbalance var demektir. FVG ile benzer ama sadece OHLC korelasyonu, hacim verisi gerektirmez.

### 4.8 Consequent Encroachment (CE)

OB veya FVG'nin tam orta noktası (%50). Fiyat bu noktayı dokunmadan geri dönerse "güçlü OB"; CE'yi geçip derin giderse OB zayıflamaktadır. Mekanik: `CE = (OB_high + OB_low) / 2`.

### 4.9 Premium ve Discount Zones (Fibonacci Tabanlı)

Bir swing low (SL) ve swing high (SH) arasında:

```
range_mid = (SH + SL) / 2                  # %50 — equilibrium
premium    = fiyat > range_mid              # pahalı bölge — short bias
discount   = fiyat < range_mid              # ucuz bölge — long bias

OTE_long   = Fib retracement 61.8%–79.0%   # Optimal Trade Entry (long)
OTE_short  = Fib retracement 61.8%–79.0%   # (swing'den aşağı OTE)
```

Fibonacci seviyeleri: 23.6%, 38.2%, 50.0%, 61.8%, 70.5%, 78.6%, 88.6%.

**OTE (Optimal Trade Entry) — spesifik:**
```python
ote_long  = SH - (SH - SL) * 0.618 .. SH - (SH - SL) * 0.786   # %61.8–%78.6 retracement
ote_short = SL + (SH - SL) * 0.618 .. SL + (SH - SL) * 0.786   # %38.2–%21.4 geri yükseliş
```

### 4.10 Rejection Block

Büyük wick bırakan tek bar — gövdesi küçük, gölgesi uzun. Kurumsal reddin kanıtı. Mekanik: `wick_ratio = wick_length / bar_range > 0.7` VE `body < ATR * 0.3`.

### 4.11 Propulsion Block

Bir rally veya selloff içindeki güçlü momentum barı — sonraki geri çekilmelerde destek/direnç görevi üstlenir.

### 4.12 Vacuum Block

İki ardışık güçlü aynı yönlü bar arasında kalan bölge — neredeyse hiç gövde yokken büyük range. Fiyatın hızla geçtiği, later test'te az direnç beklenen bölge.

### 4.13 Daily Open / Weekly Open / Monthly Open Blokları

ICT'de günlük, haftalık, aylık açılış fiyatları yapısal mıknatıs görevi görür. Mekanik: açılış barunun OHLC'si "OB" olarak işaretlenir, hedefe geri çekilme beklenir.

### 4.14 Institutional Candle (Engulfing OB)

Bir önceki birkaç barı tamamen yutan güçlü bir bar — hem OB hem de displacement kanıtı. Sistemdeki `signals/candles.py` içindeki engulfing tespiti bu kategoriye girer.

### 4.15 Reclaimed Order Block

OB, başlangıçta kırılmış (broken) ardından fiyat yeniden orijinal yöne dönerek o bölgeyi reclaim etmiş. Mekanik: breaker block üzerine fiyat döner ve breaker bölgesinin içinde kapanış yapar.

---

## 5. Liquidity Kavramları

### 5.1 Buy-Side Liquidity (BSL)

Fiyatın üzerinde biriken stop-loss emirleri + breakout alıcıları. Pratik lokasyon:
- Swing high'ların üstü
- Equal highs (EQH) dizisinin üstü
- Trendline kanalının üstü
- Round numbers (örn. 100K, 50K, 10K BTC)

### 5.2 Sell-Side Liquidity (SSL)

Fiyatın altında biriken stop-loss + breakout satıcıları:
- Swing low'ların altı
- Equal lows (EQL) dizisinin altı
- Trendline kanalının altı

### 5.3 Equal Highs/Lows as Liquidity Pools

**EQH/EQL tanım (mekanik):**
```python
EQH = abs(swing_high[t1] - swing_high[t2]) < ATR(14) * 0.15  # %15 tolerans
EQL = abs(swing_low[t1] - swing_low[t2]) < ATR(14) * 0.15
```

İki veya daha fazla EQH/EQL, "liquidity pool" oluşturur. Ne kadar çok oluşum, o kadar büyük hedef.

### 5.4 Liquidity Sweep / Raid Mekaniği

**Adımlar:**
1. Fiyat liquidity pool'a yaklaşır.
2. Pool'un üstüne/altına penetrasyon (wick veya close).
3. Stop emirleri tetiklenir.
4. Büyük oyuncu karşı yönde pozisyon doldurur.
5. Fiyat hızla pool bölgesinin içine döner (reclaim).

**Sweep tespiti:**
```python
sweep_bullish = (
    low[t] < EQL_level AND            # SSL altına iniş
    close[t] > EQL_level AND          # aynı bar reclaim
    volume[t] > volume_avg * 1.5      # hacim spike
)
```

**Sweep kalitesi:**
- 1 bar sweep (aynı bar iniş-reclaim): Güçlü
- 2–3 bar sweep: Orta
- 4+ bar sweep: Zayıf (gerçek kırılma olabilir)

### 5.5 Internal vs External Liquidity

**Internal liquidity:** Konsolidasyon range'inin içindeki swing high/low'lar — range içi hedefe ulaşım.

**External liquidity:** Mevcut range'in dışındaki, daha büyük yapının swing'leri — range'den çıkış sonrası uzun vadeli hedef.

Wyckoff çerçevesinde: Phase B'nin iç dönüşleri internal liquidity; Phase C Spring'in hedefi (AR üstü) external liquidity.

---

## 6. Wyckoff Faz Tespiti (Mekanik Kurallar)

Wyckoff döngüsü dört makro faz içerir: **Accumulation → Markup → Distribution → Markdown**. Her iki range fazı (Accumulation ve Distribution) A–E alt fazlarına ayrılır.

### 6.1 Phase A — Düşüşün Durması (Accumulation)

**Sıralı olaylar ve mekanik imzalar:**

| Olay | Mekanik Koşul |
|------|--------------|
| **PS (Preliminary Support)** | Düşüş sürüyor, hacim ortalama > 1.5x, gövde downside; ilk dip |
| **SC (Selling Climax)** | Hacim > 20-bar avg * 2.5 VE range > ATR(14) * 2 VE lower wick > gövde * 0.5 |
| **AR (Automatic Rally)** | SC barından itibaren 3–7 bar içinde %5+ yukarı hareketi (1D için) |
| **ST (Secondary Test)** | SC bölgesine geri iniş, hacim < SC hacminin %70'i, SC low'unu silmiyor |

**Phase A tamamlanma koşulu:** SC + AR + ST üçlüsünün tamamı gözlemlenmeli.

### 6.2 Phase B — Konsolidasyon

**Süre:** 1D'de tipik 20–80 bar (olağandışı durumlarda 120+ bar).

**İmzalar:**
- Hacim azalan trend içinde (konsolidasyon sırasında).
- Range high ve low'ları arasında zig-zag.
- Zaman zaman kısa süreli üst/alt sınır penetrasyonları (erken Spring/UT denemeleri — Wyckoff bunları "minor test" olarak adlandırır).

**Mekanik range tanımı:**
```python
range_high = AR_high
range_low  = SC_low
range_width = range_high - range_low
```

### 6.3 Phase C — Test (Spring / UTAD)

**Spring (Accumulation):** Range low altına penetrasyon + reclaim.

```python
spring = (
    low[t] < range_low AND                    # penetrasyon
    close[t] > range_low AND                   # reclaim
    low[t] > range_low - range_width * 0.15   # çok derin değil (max %15 overshoot)
)
```

**Spring kalitesi:**
- Tip 1: Yüksek hacimli penetrasyon + agresif reclaim → güçlü
- Tip 2: Orta hacim + biraz gecikmeli reclaim (1–2 bar içinde) → orta
- Tip 3: Düşük hacim penetrasyon + yavaş reclaim → zayıf (no-supply Spring)

**UTAD (Upthrust After Distribution):** Distribution range'inde, range high üstüne penetrasyon + reclaim. Spring'in ayna görüntüsü.

```python
UTAD = (
    high[t] > range_high AND
    close[t] < range_high AND
    high[t] < range_high + range_width * 0.15
)
```

### 6.4 Phase D — Trend Başlangıcı

**SOS (Sign of Strength — Accumulation için):** Spring sonrası güçlü hacimle range high'a yükseliş.

```python
SOS = (
    close[t] > range_high AND
    close[t] > open[t] AND                    # bullish bar
    volume[t] > volume_20bar_avg * 1.3 AND    # hacim onayı
    bar after spring within 5–15 bars         # zaman sınırı
)
```

**LPS (Last Point of Support):** SOS sonrası düşük hacimli geri çekilme — ana giriş noktası.

```python
LPS = (
    retracement of SOS rally to 38.2–61.8% Fib AND
    volume[retracement] < volume_avg AND       # düşük hacimli geri çekilme
    no close below range_high                  # range dışında kalıyor
)
```

**SOW (Sign of Weakness — Distribution için):** UTAD sonrası sert düşüş — LPS'nin ayna görüntüsü.

### 6.5 Phase E — Trend (Markup / Markdown)

Phase E'de yapı artık tekrar eden BOS + HL (markup) veya LH + LL (markdown) dizisidir. Wyckoff'un özgün katkısı bu fazda azalır; Brooks ve SMC terminolojisi devralır.

**P&F Hedef Projeksiyonu (Wyckoff):**
```
range_count_boxes = floor(range_width / box_size)
price_target      = range_low + range_count_boxes * box_size * 3   # basitleştirilmiş
```
Modern uygulamada P&F yerine Fibonacci extension (1.618x, 2.0x range) kullanılır.

---

## 7. Volume Profile Yapısı

### 7.1 Temel Kavramlar

**Value Area (VA):** Toplam hacmin %70'inin gerçekleştiği fiyat bölgesi. Standart normal dağılım analogu.

**Value Area High (VAH):** VA'nın üst sınırı.
**Value Area Low (VAL):** VA'nın alt sınırı.
**Point of Control (POC):** Belirli bir dönemde en fazla hacmin gerçekleştiği tek fiyat seviyesi — "adil fiyat" olarak yorumlanır.

### 7.2 Yapısal Kullanım

**VAH/VAL'in direnç/destek rolü:**
- Fiyat aşağıdan VAL'e gelip geri dönerse: VAL direnç → bearish bias.
- Fiyat VAH'ı kırıp içeri girerse: VA'ya "kabul" → orta vadeli bullish.
- Fiyat VA dışına çıkarsa hızla POC'ye çekilme bekle (mean reversion).

**POC'nin çekim kuvveti:**
```python
poc_magnet = abs(current_price - POC) / ATR(14) < 2.0   # POC 2 ATR içinde → mıknatıs aktif
```

### 7.3 Single Prints (Naked Areas)

Sadece bir TPO (Time Price Opportunity) peridounun geçtiği fiyat bölgeleri — "hızlı geçiş" alanları. Fiyat geri döndüğünde çok az direnç — hız tutabilir. Naked POC (hiç test edilmemiş eski POC) ise güçlü çekim noktasıdır.

**Naked POC tespiti:**
```python
naked_poc = POC not revisited since formation  # oluşumdan bu yana fiyat hiç o seviyeye gelmemiş
```

### 7.4 Volume Gaps (Low Volume Node — LVN)

VA içindeki düşük hacim alanları — fiyatın hızla geçeceği boşluklar. Yapısal olarak "vacuum" bölgesidir; stop-hunt veya momentum akışı için zemin sağlar.

### 7.5 TPO Market Profile — Temel Notlar

Market Profile, fiyat-zaman matrisini harf (TPO) notasyonuyla gösterir. Yapısal kullanım için kritik kavramlar:

- **Initial Balance (IB):** İlk 1 saatlik range (geleneksel piyasalarda); günün "baz range"i.
- **IB Extension:** IB dışına çıkış — directional conviction sinyali.
- **Neutral Day:** Hem yukarı hem aşağı IB extension → belirsiz gün.
- **Trending Day:** Tek yönlü extension, D veya b şeklinde profil — güçlü directional move.

Crypto 24/7 piyasada IB kavramı UTC 00:00–01:00 veya NY seansının ilk 1 saati olarak adapt edilebilir.

---

## 8. Multi-Timeframe Yapı

### 8.1 HTF Bias Belirleme (1W / 1D)

1W ve 1D zaman dilimlerinde trend durumu makro biasın temelidir. Kural önceliği:

```
1W trend = "up"  →  1D'de sadece long setup ara
1W trend = "down" →  1D'de sadece short setup ara
1W trend = "range" → 1D'de hem long hem short; VA sınırlarını kullan
```

**1W trend durumu tespiti (mekanik):**
```python
w_swing_high = swing_highs(weekly_df, n=3)
w_swing_low  = swing_lows(weekly_df, n=3)
weekly_trend = "up"    if consecutive_HH_HL >= 2 else
               "down"  if consecutive_LH_LL >= 2 else
               "range"
```

### 8.2 LTF Giriş Yapısı (4H / 1H)

HTF bias belirlendikten sonra LTF'de entry sinyali aranır:

**Senaryo: 1D uptrend + 4H giriş**
1. 4H'de bearish internal structure (LH oluşumu) → pullback.
2. 4H pullback, 1D OB veya FVG bölgesine ulaşır.
3. 4H'de bullish CHoCH + 1H BOS → entry sinyali.
4. Stop: 4H CHoCH seviyesinin altı.
5. Hedef: Sonraki 1D swing high veya external liquidity.

### 8.3 Yapı Hizalanma Gereklilikleri

Güçlü setup için:

| Zaman Dilimi | Koşul |
|-------------|-------|
| 1W | Trend yönü net (HH/HL veya LH/LL serisi ≥2) |
| 1D | HTF OB/FVG bölgesinde |
| 4H | CHoCH + LTF BOS |
| 1H (opsiyonel) | Giriş barı için engulfing veya pin bar |

**Hizalanma skoru:** Her hizalanan dilim +1 puan; 3/4 = minimum entry; 4/4 = "A+ setup".

### 8.4 Inverse Confluence (HTF Range + LTF Trend)

**Senaryo:** 1W piyasa geniş bir range içinde. 1D ve 4H ise sert downtrend yaşıyor (range'in alt sınırına doğru). Analist, LTF'deki düşüşü "short" olarak okuyabilir — ancak gerçekte bu, HTF range'inin alt sınırına yaklaşımdır, yani LTF düşüş HTF alım fırsatı hazırlıyor.

**Kural:** LTF trend sinyali, HTF range sınırından 1 ATR(14D) içindeyse, inverse confluence var sayılır; LTF trend sinyali hafifletilir.

---

## 9. Eleştirel Değerlendirme

### 9.1 SMC/ICT — Akademik Eleştiriler

- **Retroactive identification:** Order block, liquidity grab ve inducement etiketleri büyük ölçüde geriye dönük tanımlanır. Hangi barın "kurumsal OB" olduğunu önceden belirlemek zor; bu, confirmation bias yaratır.
- **Peer-review yokluğu:** SMC terminolojisini kullanan hiçbir çalışma, söz konusu yapıların istatistiksel edge'ini peer-reviewed bir yayında kanıtlamamıştır.
- **"Smart money" operasyonel değil:** CFTC COT raporu kurumsal pozisyonları açıklar; ancak bu verinin günlük/saatlik yapıyla bağlantısı doğrudan değildir. "Smart money" kavramı gözlemlenebilir değil, çıkarımsaldır.
- **Buna karşın faydalı çekirdek:** Likidite havuzları (equal highs/lows üzerindeki stop emirleri), sweep mekaniği ve displacement kavramları Harris'in mikroyapı literatürüyle tutarlıdır; test edilebilir hipotez üretir.

### 9.2 Wyckoff — Zorluklar

- **Faz tespiti sübjektif:** Hangi dip "SC" hangisi "ST"dir, neye göre belirlenir? Volume eşikleri standartlaşmamıştır.
- **Spring vs SOW:** Zaman zaman tek bir bar hem Spring hem UTAD olabilir gibi görünür; bu ambiguity ciddi problem.
- **Crypto'ya adaptasyon sorunu:** Wyckoff 1920–30'larda hisse senetleri üzerine geliştirildi. Crypto'da manipüle exchange'ler, wash trading ve bot aktivitesi, Wyckoff'un ön koşullarını bozar (hacim verisinin güvenilirliği).

### 9.3 Mekanik vs Diskresyonar Dengeleme

Mekanik kural setinin avantajları: backtestable, tekrarlanabilir, bias riskini azaltır.
Dezavantajı: Context-blind — aynı OB yapısı farklı piyasa bağlamlarında tamamen farklı davranır.

Önerilen yaklaşım: Mekanik kural ile sinyal üret → makine öğrenmesi filtresi veya basit hacim filtresi ile yanlış pozitif say → edge ölçümünü titizlikle yap.

### 9.4 Crypto 24/7 Etkisi

- **Session kavramı geçersiz:** Market Profile'ın IB kavramı, "market close" ve "open" varsaydığı için crypto'ya doğrudan uygulanamaz.
- **Volume profil kullanımı:** UTC gün sınırı yeterince net bir "session" oluşturmaz; haftalık profil daha tutarlı.
- **Weekend gapping yok:** Traditional PA analizinde hafta sonu gapping önemli bir bağlam unsuru; crypto'da yok. Bu durum "gap fill" stratejilerini geçersizleştirir.
- **Likidite asimetrisi farklı:** BTC 1D'de likidite en derin; alt coinlerde yüz kat daha az. Küçük hack/whale hareketi equal highs/lows sweep yaratabilir — "kurumsal niyet" yokken sweep gerçekleşir.

---

## 10. Test Edilebilir Hipotez Adayları

Aşağıdaki 8 hipotez, sistemdeki mevcut veri altyapısıyla backtestable olacak şekilde formüle edilmiştir. Her biri için giriş kuralları, stop ve hedef belirlenmiş; decorrelation potansiyeli de değerlendirilmiştir.

---

### H-1: BOS + %50 Retracement Entry (Trend Devamı)

**Hipotez:** "Uptrend'de bullish BOS oluştuktan sonra fiyat %38.2–%61.8 Fibonacci retracement'a çekilirse ve bu bölgede bullish engulfing oluşursa, trend devam eder."

**Mekanik giriş kuralları:**
```
1. n=3 fractal ile swing_high tespit et (BOS seviyesi = last_swing_high).
2. BOS: close[t] > last_swing_high.
3. Retracement bölgesi: [BOS_level - (BOS_level - prior_HL) * 0.618, 
                          BOS_level - (BOS_level - prior_HL) * 0.382]
4. Entry: Bölge içinde bullish engulfing bar (body > prev_body * 1.3, close > open).
5. Stop: prior_HL'nin 0.5 ATR altı.
6. Target: BOS_level * 1.618 (Fib extension).
```

**Neden işe yarayabilir:** BOS trendi onaylar; retracement "discount" bölgesinde OTE oluşturur; engulfing kurumsal alım kanıtı.
**Decorrelation:** Close-based BOS filtresi, false BOS'u elimine eder.

---

### H-2: Equal Highs Sweep + Immediate Reversal

**Hipotez:** "İki veya daha fazla equal high (ATR * %15 tolerans) oluşturan piyasada, fiyat bu pool'u sweep (wick) edip aynı bar içinde kapanışta geri dönerse, sonraki 3–5 bar içinde kayda değer düşüş (≥ 1.0 ATR) yaşanır."

**Mekanik kurallar:**
```
1. EQH: N>=2 swing high, her biri öncekinin ± ATR*0.15 içinde.
2. Sweep: high[t] > max_EQH AND close[t] < max_EQH.
3. Reversal bar: close[t] < open[t] (bearish close).
4. Entry: close[t] (bearish — sweep bar kapanışında short).
5. Stop: high[t] + ATR * 0.2 (sweep wick üstü).
6. Target: Nearest EQL veya sweep_bar_close - 1.5 * ATR.
7. Zaman filtresi: Sweep sonraki 5 bar içinde target'a ulaşmazsa exit.
```

**Neden işe yarayabilir:** Equal highs = kümeli stop emirleri. Sweep bu emirleri tetikler. Büyük short satıcılar kümeli piyasa emriyle pozisyon açar. Anlık satış baskısı artar.

**[YILDIZ HİPOTEZ — BTC 1D için en test edilebilir olanlardan biri]**

---

### H-3: Wyckoff Phase D LPS Scan

**Hipotez:** "Wyckoff accumulation Phase C Spring'i takip eden SOS hareketi ardından, fiyat düşük hacimli geri çekilme (LPS) yaparsa ve bu geri çekilmede close hiçbir zaman range_high'ın altına inmezse, long entry sağlar."

**Mekanik kurallar:**
```
1. Phase A tespiti: SC bar (volume > 20bar_avg * 2.5 VE range > ATR * 2).
2. AR tespiti: SC'den 3–10 bar içinde %5+ rally.
3. Phase C Spring: range_low altına wick + reclaim.
4. SOS: Spring'den 3–15 bar içinde range_high kırılımı (close-based).
5. LPS: SOS'dan sonra 3–10 bar içinde Fib %38.2–%61.8 geri çekilme + volume < 15bar_avg.
6. Entry: LPS bölgesinde bullish pin bar (lower wick > body * 1.5).
7. Stop: Spring low - ATR * 0.3.
8. Target: range_high + range_width * 0.5 (P&F proxy).
```

**[YILDIZ HİPOTEZ — Wyckoff tabanlı en mekanik hali]**

---

### H-4: OB Mitigation Entry (BTC 1D)

**Hipotez:** "BTC 1D chart'ta, güçlü displacement öncesindeki son bearish bar (bullish OB) tanımlanır; fiyat OB bölgesine geri döndüğünde (OB high'ından OB low'una penetrasyon yok) ve LTF (4H) bullish CHoCH varsa, long entry sağlar."

**Mekanik kurallar:**
```
1. Displacement tespit: 3 bar içinde toplam range > ATR(14) * 2.5 AND directional.
2. OB: Displacement öncesi son bearish bar (close < open).
3. OB zone: [low[OB_bar], high[OB_bar]].
4. Mitigation: close[t] >= OB_low AND close[t] <= OB_high (zone içinde kapanış).
5. LTF onayı: 4H chart'ta bearish CHoCH sonrası bullish CHoCH (trend flip).
6. Entry: Mitigation bar close.
7. Stop: OB_low - ATR(14D) * 0.2.
8. Target: Displacement başlangıcı üstü veya external liquidity.
9. Geçersizlik: close < OB_low → OB iptal, trade çıkış.
```

**[YILDIZ HİPOTEZ — sistemin engulfing modülüyle combine edilebilir]**

---

### H-5: Premium Zone Short on Alt Rally

**Hipotez:** "BTC 1D downtrend içinde, bir altcoin BTC dominance düşüşüyle %30+ rally yaparsa ve altcoin kendi swing_high–swing_low range'inin %61.8+ (premium zone) seviyesine ulaşırsa, kısa vadeli geri çekilme (≥ %10 düzeltme 5 bar içinde) ihtimali yüksektir."

**Mekanik kurallar:**
```
1. BTC 1D trend = "down" (son 2 HH/HL yok, LH+LL serisi var).
2. ALT: coin_return_5d > 0.30 (son 5 günde %30+ yükseliş).
3. Premium: close > range_low + (range_high - range_low) * 0.618.
4. Entry: Premium zone'a girişte bearish engulfing veya shooting star.
5. Stop: range_high + ATR * 0.3.
6. Target: range_low + range_width * 0.5 (equilibrium).
7. Universe filtresi: Alt coin hacmi > 50M USD günlük (likidite filtresi).
```

**Neden işe yarayabilir:** BTC downtrend'de alt ralliler geçici "rotation" kaynaklı; premium zone satıcı absorbsiyonu yapar.

---

### H-6: Naked POC Mean Reversion

**Hipotez:** "Haftalık volume profilinde oluşmuş Naked POC (en az 3 hafta test edilmemiş), mevcut fiyattan 2.0–4.0 ATR(1W) uzakta ise fiyat ortalama X hafta içinde Naked POC'ye döner."

**Mekanik kurallar:**
```
1. Haftalık volume profile hesapla (son 20 hafta, her hafta ayrı profil).
2. Naked_POC = geçmiş haftalarda oluşmuş POC, mevcut hafta henüz ziyaret edilmemiş.
3. Filtre: distance = abs(current_price - nPOC) / ATR(1W), 2.0 < distance < 4.0.
4. Entry: Trend yönüne bakma — direkt mean reversion long veya short.
5. Target: nPOC seviyesi.
6. Stop: Entry'den 2.0 * ATR(1W) uzağa.
7. Time stop: 8 hafta içinde target'a ulaşmazsa exit.
```

**[YILDIZ HİPOTEZ — volume profile mean reversion, crypto 1W'de tutarlı görünüyor]**

---

### H-7: CHoCH + FVG Geri Dönüş (LTF Reversal)

**Hipotez:** "4H chart'ta downtrend'de bullish CHoCH oluştuktan sonra, CHoCH hareketi içinde kalan bir bullish FVG tespit edilirse, fiyat bu FVG'yi fill etmeye döndüğünde long entry verir."

**Mekanik kurallar:**
```
1. Downtrend (4H): En az 2 LH + 2 LL serisi.
2. Bullish CHoCH: close > last_LH (close-based).
3. FVG: CHoCH hareketi içinde (aynı yükselen bar dizisinde) bullish FVG var.
   FVG = low[t+1] > high[t-1], gap > ATR * 0.15.
4. Fill: Fiyat FVG bölgesine geri döner (close FVG'nin içinde).
5. Entry: FVG midpoint (CE) yakınında bullish pin bar.
6. Stop: FVG low - ATR * 0.2.
7. Target: CHoCH bar close seviyesi + (CHoCH close - FVG low) * 1.618.
```

---

### H-8: Engulfing + Structure Overlay (Mevcut Sistemin Uzantısı)

**Hipotez:** "Mevcut sistemdeki bullish engulfing sinyali, eş zamanlı olarak 1D bullish BOS ile çakışırsa, tek başına engulfing'e kıyasla edge artıyor mu?"

**Mekanik kurallar:**
```
1. Mevcut engulfing sinyal: signals/candles.py::bullish_engulfing() = True.
2. Structure onay: swing_highs(n=3) kullanılarak son 20 bar içinde BOS var.
   BOS = close > last_swing_high.
3. Confluence score: engulfing AND BOS → score = 2.
4. Baseline: sadece engulfing → score = 1.
5. Backtest: Her iki grubun sonraki 5-bar ve 10-bar forward return dağılımı karşılaştırılır.
```

**[YILDIZ HİPOTEZ — mevcut sistem ile en hızlı entegre edilebilir; baseline mevcuttur]**

---

## 11. Bizim Sistemle Bağlantı

### 11.1 Mevcut `signals/structure.py` Durumu

Mevcut modül şunları içeriyor:
- `swing_highs(df, n)` / `swing_lows(df, n)` — n-bar fractal
- `support_resistance(df, lookback, min_touches, cluster_atr_mult)` — ATR kümeleme
- `trendline(df, window)` — lineer regresyon
- `ema(series, period)` / `atr(df, period)`

**Eksik olanlar (öncelik sırasıyla):**

### 11.2 Önerilen Yeni Fonksiyonlar

**Öncelik 1 — Hemen eklenebilir, H-8 hipotezi için:**

```python
def detect_bos(df: pd.DataFrame, n: int = 3) -> pd.Series:
    """
    Her bar için bullish_BOS (+1) veya bearish_BOS (-1) veya None (0) döner.
    Close-based, lookahead-free.
    """
    sh = swing_highs(df, n=n)
    sl = swing_lows(df, n=n)
    # son confirmed swing high/low'u takip et
    # bullish_BOS: close > last_confirmed_swing_high
    # bearish_BOS: close < last_confirmed_swing_low
    ...

def detect_choch(df: pd.DataFrame, n: int = 3) -> pd.Series:
    """
    Trend state makinesini çalıştır; CHoCH barlarını işaretle.
    """
    ...
```

**Öncelik 2 — H-1, H-7 için:**

```python
def detect_fvg(df: pd.DataFrame, min_gap_atr: float = 0.15) -> pd.DataFrame:
    """
    Three-bar FVG tespiti.
    Returns: DataFrame[ts, fvg_type (bull/bear), fvg_low, fvg_high, filled]
    """
    ...
```

**Öncelik 3 — H-2 için:**

```python
def detect_equal_highs_lows(
    df: pd.DataFrame, n: int = 3, tolerance_atr: float = 0.15
) -> pd.DataFrame:
    """
    EQH/EQL havuzları tespit et.
    Returns: DataFrame[level, type (high/low), touch_count, last_ts]
    """
    ...
```

**Öncelik 4 — H-4 için:**

```python
def detect_order_blocks(
    df: pd.DataFrame,
    displacement_atr_mult: float = 2.0,
    displacement_bars: int = 3,
    n_swing: int = 3,
) -> pd.DataFrame:
    """
    Bullish ve bearish OB tespiti.
    Returns: DataFrame[ts, ob_type (bull/bear), ob_low, ob_high, mitigated]
    """
    ...
```

### 11.3 Engulfing'e Structure Overlay

`signals/candles.py`'daki engulfing sinyali, BOS ve CHoCH bilgisiyle birleştirilebilir:

```python
def engulfing_with_structure(
    df: pd.DataFrame,
    candle_fn,          # bullish_engulfing veya bearish_engulfing
    n_swing: int = 3,
    require_bos: bool = True,
    require_choch: bool = False,
) -> pd.Series:
    """
    Engulfing AND (BOS OR CHoCH) confluence.
    """
    engulfing = candle_fn(df)
    bos = detect_bos(df, n=n_swing)
    choch = detect_choch(df, n=n_swing)

    if require_bos and require_choch:
        return engulfing & (bos != 0) & (choch != 0)
    elif require_bos:
        return engulfing & (bos != 0)
    elif require_choch:
        return engulfing & (choch != 0)
    return engulfing
```

### 11.4 Öncelikli Backtest Planı

```
1. H-8 (Engulfing + BOS): Mevcut veri + mevcut engulfing ile 1–2 gün.
2. H-2 (EQH Sweep):       EQH fonksiyonu ekle, BTC 1D 3 yıl backtest.
3. H-4 (OB Mitigation):   OB fonksiyonu ekle, BTC 1D, LTF 4H onay.
4. H-3 (Wyckoff LPS):     En karmaşık; volume + multi-event state machine gerektirir.
5. H-6 (Naked POC):       Haftalık volume profil altyapısı eklendikten sonra.
```

---

## Kılavuz Tablo — Crypto 1D'de Mekanik Çalışabilirlik

| Kavram | Mekanik Çalışabilirlik (Crypto 1D) | Neden |
|--------|-------------------------------------|-------|
| BOS (close-based, n=3) | **Yüksek** | Net kural, backtestable, az parametrik |
| CHoCH (close-based, n=3) | **Yüksek** | BOS gibi, trend-state makinesi gerektirir |
| Equal Highs/Lows Sweep | **Yüksek** | Stop-hunt mekaniği crypto'da güçlü; H-2 |
| FVG (gap > ATR*0.15) | **Orta** | Tanım net ama fill oranı değişken |
| Bullish/Bearish OB | **Orta** | Displacement eşiği kalibrasyonu gerektirir |
| Wyckoff Phase C Spring | **Orta** | Volume kriterlerine bağlı; crypto hacim verisi gürültülü |
| Naked POC (1W profil) | **Orta-Yüksek** | Mean reversion 1W'de tutarlı görünüyor |
| Breaker Block | **Düşük-Orta** | Retroactive tanım; false positive yüksek |
| IFVG | **Düşük** | Çok katmanlı tanım; aşırı parametrik |
| Wyckoff Faz A-E (tam) | **Düşük** | State machine kompleks; volume güvenilirliği zayıf |
| TPO Market Profile | **Düşük** | 24/7 crypto'da session kavramı geçersiz |
| Premium/Discount OTE | **Orta** | Fibonacci tabanlı; swing seçimi sübjektif |

---

*Bu doküman, `knowledge/books/` altındaki diğer özet dosyalarıyla birlikte RAG sorgularında yapısal analiz referansı olarak kullanılmak üzere hazırlanmıştır. Backtest sonuçları mevcut olduğunda ilgili hipotez bölümleri güncellenmelidir.*
