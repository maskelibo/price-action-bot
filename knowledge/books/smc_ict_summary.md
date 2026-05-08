---
source_id: smc_ict_summary
source_type: book
author: ICT (Michael J. Huddleston) + SMC community synthesis
title: Smart Money Concepts / Inner Circle Trader Methodology (notes)
type: reference_only
quality: 4
ingested_date: 2026-05-08
topic_tags: [structure_smc, order_block, liquidity_grab, fair_value_gap, displacement, market_structure_break]
---

# SMC / ICT — Smart Money Concepts Methodology (özet notlar)

> Telif uyarısı: Bu doküman Michael J. Huddleston'ın (ICT) kamuya açık eğitim materyalleri ve geniş SMC topluluğunun (YouTube, Twitter/X, açık forumlar) yaydığı kavramların sentezidir. Hiçbir korumalı içerik kopyalanmamıştır; yalnızca metodolojik özet ve kritik değerlendirme amaçlıdır.

---

## Yazarın Çerçevesi

Smart Money Concepts (SMC) ve onun ana kaynağı olan Inner Circle Trader (ICT) metodolojisi, fiyat hareketinin "kurumsal sermaye" (smart money — bankalar, fon yöneticileri, market makers) tarafından güdüldüğü ve perakende yatırımcının (retail) bu kurumsal akışın ayak izlerini grafikte okuyabileceği iddiası üzerine kuruludur. Bu çerçevede fiyat hareketleri "rastgele" değil, **likidite hedefli** olarak yorumlanır: piyasa, stop emirlerinin biriktiği bölgelere yönelir, oradaki likiditeyi "süpürür" (sweep / grab / raid), ve sonra gerçek yönüne döner.

Bu felsefenin temelleri:

1. **Likidite asimetrisi:** Büyük oyuncuların pozisyon açabilmesi için karşı tarafta yeterli likidite (stop emirleri, breakout traders' orders, equal highs/lows üstünde birikmiş emirler) bulunmalıdır. Bu nedenle fiyat, "obvious" olan seviyelere yöneltilir, oradaki emirler tetiklenir, sonra trend asıl yönünde devam eder.
2. **Kurumsal niyet (institutional intent):** ICT, fiyatın kurumların açtıkları/kapadıkları bölgelerde "iz" bıraktığını söyler — order block (OB), fair value gap (FVG), breaker block, mitigation block gibi yapılar bu izlerdir.
3. **Fraktallık:** Aynı yapılar her zaman diliminde (1m'den haftalığa) tekrar eder. Ancak HTF (higher timeframe) bias LTF (lower timeframe) yapıların yönünü belirler — "top-down" analiz şarttır.
4. **Algoritmik fiyat dağıtımı:** ICT, modern piyasaların algoritmik olduğunu ve algoritmaların belirli "delivery" desenleri (Power of Three: accumulation → manipulation → distribution) izlediğini öne sürer.

**Kritik perspektif (RAG sorgularında bu uyarıyı koru):** SMC/ICT topluluğunun yaydığı çoğu iddia *peer-reviewed istatistiksel* zeminden yoksundur. "Smart money" kavramı operasyonel olarak gözlemlenebilir değildir (CFTC COT raporu vs. dışında); footprint iddialarının çoğu **retroactive identification** ve **confirmation bias**'a açıktır. Buna rağmen bazı çekirdek kavramlar — likidite havuzları, stop hunting, displacement — akademik mikroyapı literatürüyle (örn. Larry Harris, "Trading and Exchanges") tutarlıdır. Sistemimizde SMC'yi *referans* olarak kullanırız; mekanik kuralları test ederiz, subjektif yorumları dışlarız.

---

## Market Structure Tanımları

SMC'nin temeli market structure (piyasa yapısı) okumasıdır. Wyckoff ve Dow teorisinden devralınan bu kavramlar, SMC'de daha mekanik etiketlerle yeniden tanımlanır.

### Higher High (HH), Higher Low (HL) — Yükseliş Yapısı
Bir uptrend tanımlanmış sayılır eğer fiyat ardışık olarak:
- Önceki swing high'tan daha yüksek bir tepe (HH) yapıyor, ve
- Önceki swing low'dan daha yüksek bir dip (HL) yapıyor ise.

Mekanik tanım: Swing high = en az N bar (tipik N=3 veya 5) sağında ve solunda kendinden düşük high olan bar. Sistem bu noktayı `signals/structure.py` içinde **fractal pivot detection** ile bulabilir.

### Lower High (LH), Lower Low (LL) — Düşüş Yapısı
Tersi geçerlidir: ardışık LH ve LL = downtrend.

### Break of Structure (BOS)
Bir trendin **devam ettiğini** onaylayan kırılma. Yükseliş yapısında: fiyat son HH'yi yukarı yönlü kırarsa (close > previous HH) bullish BOS gerçekleşir. Düşüşte: fiyat son LL'yi aşağı kırarsa bearish BOS.

**Mekanik kural (signal):**
```
bullish_BOS = (close[t] > swing_high[last]) AND (trend_state == "up")
bearish_BOS = (close[t] < swing_low[last]) AND (trend_state == "down")
```
Bazı SMC tradeler "wick break" (sadece high > swing_high) ile yetinir; daha sıkı tanım "body close break" ister. Sistemde **close-based BOS** kullan (daha az false signal).

### Change of Character (CHoCH / ChoCH)
Trendin **döndüğünü** sinyal eden kırılma. Yükseliş trendindeyken fiyat **son HL'yi aşağı kıracak** olursa bearish CHoCH; düşüşte fiyat **son LH'yi yukarı kıracak** olursa bullish CHoCH gerçekleşir.

**Önemli ayırt edici nokta:** BOS = trend-yönünde kırılma. CHoCH = trend-karşıtı kırılma. Bir trendin *ilk* kırılması daima CHoCH'dir; sonraki aynı yönlü kırılmalar BOS sayılır.

### Internal vs External Structure
- **External structure:** HTF (örn. 4H veya günlük) swing pivotları arasında oluşan ana yapı. "Macro" trend.
- **Internal structure:** Bu HTF swingler arasında LTF'de (örn. 15m) oluşan alt yapı.

Pratik kullanım: External BOS HTF trendin devamıdır (yüksek olasılık). Internal CHoCH ise sadece alt-yapı dönüşüdür ve HTF trende göre **pullback fırsatı** olarak değerlendirilir.

### Premium / Discount Zones
Bir swing'in (örn. son major low → son major high) Fibonacci 50% seviyesi referans alınır:
- 50% üstü = **Premium** zone (satış favori)
- 50% altı = **Discount** zone (alım favori)
- 50% civarı = **Equilibrium**

ICT, kurumların discount'ta long, premium'da short biriktirdiğini öne sürer. Bu, basit bir mean-reversion bias'ıdır; istatistiksel olarak HTF trend filtreleriyle birleştirildiğinde anlamlı olabilir, tek başına edge kanıtı yoktur.

---

## Liquidity Concepts

SMC'nin imza kavramı likidite haritalamasıdır. Fiyatın "nereye gitmek istediği" sorusunun cevabı, hangi likidite havuzlarının vurulması gerektiğine bağlanır.

### Buy-side Liquidity (BSL)
Swing high'ların **üstünde** birikmiş likidite. Mantığı: short pozisyonların stop-loss'ları ve breakout long emirleri swing high'ın hemen üzerinde durur. Fiyat oraya çıktığında bu emirler tetiklenir → kurumsal satışa yakıt sağlar.

### Sell-side Liquidity (SSL)
Swing low'ların **altında** birikmiş likidite. Long stop-loss'lar ve breakdown short emirleri burada yığılır.

### Equal Highs / Equal Lows (EQH / EQL)
İki veya daha fazla aynı seviyede high/low (görsel olarak yatay çift veya üçlü tepe/dip). Bu yapılar **resting liquidity pools** olarak görülür — "obvious" stop bölgeleri olduğu için kurumsal akış buralara çekilir. SMC, EQH/EQL'lerin neredeyse her zaman süpürüldüğünü iddia eder.

**Mekanik tanım (önerim):**
```
EQH = |high[i] - high[j]| < tolerance * ATR  AND  i != j  AND
      no higher high between i and j
tolerance ≈ 0.10 (yani %10 ATR aralığı)
```

### Liquidity Grab / Sweep / Raid
Üç terim büyük ölçüde eş anlamlıdır: fiyatın bir likidite havuzunu (swing high/low veya EQH/EQL) **wick ile aşıp gövde ile geri kapanması**. Bu davranış, kurumsal "stop hunt" olarak yorumlanır.

**Mekanik tanım (sistem için):**
```python
def liquidity_grab_bullish(bar, prior_swing_low, atr):
    wick_below = bar.low < prior_swing_low
    close_back_inside = bar.close > prior_swing_low
    sweep_magnitude = (prior_swing_low - bar.low) > 0.25 * atr  # min Y eşiği
    return wick_below and close_back_inside and sweep_magnitude
```
Y parametresi (sweep derinliği) optimize edilmelidir; çok küçük değer noise yakalar, çok büyük değer geçerli sweep'leri kaçırır.

### Stop Hunts as Smart-Money Fueling Event
ICT'nin merkezi narrative'i: kurumlar pozisyon açmak için karşı tarafa likidite yaratmak zorundadır. Bunun en kolay yolu, retail traders' obvious stop bölgelerini "vurmak"tır. Akademik literatürde (Harris, microstructure) bu mekanizma **stop-loss order absorption** olarak geçer ve gerçek bir piyasa fenomenidir — ancak ICT'nin atfettiği frekans ve niyet tartışmalıdır.

---

## Order Blocks (OB)

Order Block, SMC'nin merkezi konseptidir ve "kurumsal emir bölgesi" olarak tanımlanır. Pratik bir özettir: güçlü bir hareketten önceki son ters yönlü mum.

### Bullish Order Block (Bull OB)
**Tanım:** Güçlü bir bullish displacement (yukarı yönlü güçlü hareket) öncesindeki **son bearish (kırmızı) mum**. Bu mumun gövdesi (bazı varyantlar high-low aralığını) bir destek bölgesi olarak işaretlenir.

**Mekanik tespit:**
```python
def find_bullish_ob(bars, i, atr, displacement_threshold=2.0):
    # Bar i'den sonra bullish displacement var mı?
    next_move = max(b.high for b in bars[i+1:i+4]) - bars[i].close
    if next_move < displacement_threshold * atr:
        return None
    # i indisindeki bar bearish mi?
    if bars[i].close >= bars[i].open:
        return None
    return OrderBlock(
        top=bars[i].high,
        bottom=bars[i].low,
        type="bullish",
        time=bars[i].time
    )
```

### Bearish Order Block (Bear OB)
Tersi: güçlü bir bearish displacement öncesindeki son bullish (yeşil) mum.

### Mitigation Entry Rules
Mitigation = fiyatın daha önce oluşturulmuş bir OB'ye geri dönüp test etmesi. ICT mantığı: kurum o bölgede biriktirmediği emirleri "mitigate" eder (kapatmaya gelir). Trader, fiyat OB'ye döndüğünde **fade işlemi** alır (bullish OB'de long, bearish OB'de short).

**Tipik giriş kuralı:**
- Limit emir: OB'nin **top edge'inde** (bullish OB için top, bearish OB için bottom).
- Aggressive: OB'nin **midpoint** (50%) seviyesinde.
- Conservative: LTF'de OB içinde CHoCH veya bullish liquidity grab onayı bekle.

### OB Validation Criteria
Her OB eşit değildir. Yüksek olasılıklı OB için filtreler:
1. **Displacement strength:** OB'den sonraki hareket en az 2-3× ATR olmalı.
2. **FVG presence:** OB'den çıkan hareket bir Fair Value Gap (aşağıda) bırakmalı — "imbalance" kanıtı.
3. **Liquidity sweep before:** OB oluşmadan hemen önce karşı tarafta bir liquidity grab varsa OB daha güçlü.
4. **HTF confluence:** OB, HTF discount/premium zone içinde mi? HTF OB ile çakışıyor mu?
5. **Unmitigated:** OB henüz test edilmemiş olmalı; ilk dokunuş genelde çalışır, sonraki testler zayıflar.

### Breaker Block
Bir OB başarısız olursa (fiyat OB'yi kırıp geçerse), o OB **breaker block**'a dönüşür. Eski bullish OB kırılırsa breaker bearish bir bölge olur (rezistans). Bu, "failed support → resistance" klasik teknik analiz prensibinin SMC versiyonudur.

### Mitigation Block
Bir CHoCH'tan sonra trendin yeni yönünde oluşan ilk pullback'in başlangıç bölgesi. Breaker'a benzer ama tetikleyici farklıdır.

---

## Setup Kataloğu

Aşağıdaki setup'lar SMC/ICT topluluğunda yaygın paylaşılan mekanik (mümkün olduğunca) yapılardır. Her biri için **tanım, bağlam, giriş, stop, hedef, edge, failure mode** ayrımı verilmiştir. **Win rate rakamları "community claim, unverified" — Faz 2 backtest'i ile doğrulanmalı.**

### Setup 1: Liquidity Grab + Reversal Entry
- **Tanım:** Fiyat HTF swing high/low veya EQH/EQL'yi wick ile aşar, mum gövdesi içerde kapanır; takip eden barda dönüş başlar.
- **Bağlam:** En güçlü versiyonu HTF discount/premium zone'da, range extreme'lerinde gerçekleşir.
- **Giriş:** Sweep mumundan sonraki ilk LTF CHoCH onayı; veya sweep mumunun close seviyesinin tekrar test edilmesi.
- **Stop:** Sweep wick'in en uzak ucunun 0.2-0.5× ATR ötesi.
- **Hedef:** Karşı taraftaki en yakın likidite havuzu (genelde range'in diğer ucu) — minimum 2R, sıklıkla 3-5R.
- **Edge:** Microstructure literatürüyle tutarlı (Harris, stop-hunt fade). Community claim: %60-65 win rate (unverified).
- **Failure:** Sweep'in arkasından kapanışın hemen geri vurması; "double tap" — fiyat geri dönüp ikinci kez sweep eder ve bu sefer trend o yönde kalır.

### Setup 2: Order Block Mitigation Entry
- **Tanım:** Trend yönüyle uyumlu bir OB belirlenir; fiyat OB'ye geri döndüğünde fade işlemi alınır.
- **Bağlam:** HTF trend net olmalı; OB henüz test edilmemiş ("unmitigated") olmalı.
- **Giriş:** OB top/bottom edge'de limit; veya OB içinde LTF reversal onayı (CHoCH, engulfing).
- **Stop:** OB'nin karşı edge'inin 0.3-0.5× ATR ötesi.
- **Hedef:** En yakın HTF likidite veya önceki swing.
- **Edge:** Mean-reversion + trend continuation kombinasyonu; Wyckoff'un LPS (Last Point of Support) kavramının analoğu.
- **Failure:** OB body'sini close-through ile delip geçen güçlü bar — bu durumda OB breaker'a dönüşür ve pozisyon ters tarafa flip edilebilir.

### Setup 3: Fair Value Gap (FVG) Fill / Rejection Entry
- **Tanım (FVG):** Üç bar deseninde, bar1 ve bar3 arasında bar2'nin geçtiği ama bar1 high ile bar3 low arasında **dokunulmamış** dikey bir gap kalır. Bullish FVG: `bar1.high < bar3.low` ve aradaki bölge bar2 tarafından çapraz kesilmiş. Bearish FVG: `bar1.low > bar3.high`.
- **Bağlam:** FVG, displacement'ın imbalance kanıtıdır. Fiyatın bu boşlukları "doldurmaya" döneceği iddia edilir.
- **Giriş:** Fiyat FVG'ye girdiğinde, FVG'nin **50% (consequent encroachment)** seviyesinde limit veya rejection onayında market.
- **Stop:** FVG'nin uzak edge'inin ötesi.
- **Hedef:** FVG oluşturan displacement'ın hedef likidite seviyesi.
- **Edge:** Tezahüratçı bir kavram olsa da matematiksel olarak FVG = momentum impulse imzası; reversion-to-imbalance bias'ı yarı-test edilebilirdir.
- **Failure:** FVG tamamen fill olur ve bar 0.5×ATR'den fazla karşı yönde devam ederse setup invalid.

**FVG mekanik kodu:**
```python
def detect_bullish_fvg(b1, b2, b3):
    if b1.high < b3.low:  # gap exists
        return FVG(top=b3.low, bottom=b1.high, type="bullish")
    return None
```

### Setup 4: Break of Structure (BOS) Continuation Entry
- **Tanım:** Trend yönünde swing high/low kırılır; fiyat kırılan seviyeyi retest eder, oradan trend devam.
- **Bağlam:** Net HTF trend, çok belirgin BOS impulsu (displacement).
- **Giriş:** Kırılan swing seviyesinin retest'inde (poliçe: yapı şimdi destek/rezistans).
- **Stop:** Retest swing low/high'ının ötesi.
- **Hedef:** Bir sonraki HTF likidite hedefi.
- **Edge:** Klasik trend-following (Brooks "always-in" prensibinin SMC etiketi).
- **Failure:** BOS sonrası geri dönüş ve **CHoCH** — bu durumda kırılma "stop hunt" olarak yeniden etiketlenir.

### Setup 5: Change of Character (CHoCH) Reversal Entry
- **Tanım:** Var olan trendin son HL/LH'sinin kırılmasıyla trend dönüşü sinyali; ilk pullback'te yeni yöne giriş.
- **Bağlam:** HTF range extreme'inde, liquidity sweep ile birleşmesi tercihli.
- **Giriş:** CHoCH sonrası ilk OB veya FVG mitigation'da.
- **Stop:** CHoCH öncesi swing extreme'inin ötesi.
- **Hedef:** Önceki trendin başlangıç noktası veya HTF zıt likidite havuzu.
- **Edge:** Erken dönüş yakalama; yanlış pozitif riski yüksek.
- **Failure:** CHoCH sahte çıkar, fiyat orijinal trende geri döner — bu durumda "internal CHoCH only" idi denerek trade kapatılır.

### Setup 6: Optimal Trade Entry (OTE)
- **Tanım:** ICT'ye özgü Fibonacci entry zone: bir leg'in **0.62 - 0.79** retracement bölgesi. Tipik olarak 0.705 "sweet spot".
- **Bağlam:** Trend yönünde leg sonrası pullback. HTF bias yön ile uyumlu.
- **Giriş:** OTE bölgesi içinde limit veya LTF reversal onayında market.
- **Stop:** Leg başlangıcının ötesi (yani 1.0 retracement seviyesi + buffer).
- **Hedef:** 0% retracement (leg ucu) ve sonra 1R, 1.5R extension'lar — çoğu zaman -0.27 veya -0.62 Fibonacci extension hedefler.
- **Edge:** Standart pullback-trade'in Fibonacci varyantı; istatistiksel olarak diğer Fib bölgelerinden anlamlı farklı edge kanıtı yok ama tutarlı stop-hedef matematiği sağlar.
- **Failure:** Fiyat 0.79'u aşar ve close eder — leg yapısı geçersiz, trend dönüyor olabilir.

### Setup 7: Premium / Discount Confluence Entry
- **Tanım:** OB veya FVG, HTF range'in premium (sell) veya discount (buy) yarısında oturuyorsa setup confluence kazanır.
- **Bağlam:** Tanımlı HTF range (consolidation veya açık swing).
- **Giriş:** Discount + bullish OB (long) veya premium + bearish OB (short).
- **Stop:** OB'nin karşı edge'i.
- **Hedef:** Range'in zıt extreme'i (BSL/SSL).
- **Edge:** İki bağımsız filtrenin (zone + structure) örtüşmesi false signal'i azaltır — hangi tek filtreden daha iyi olduğu test edilmeli.
- **Failure:** Range break — fiyat range extreme'ini sweep edip geri döner; trade invalid.

### Setup 8: Inducement Liquidity Grab (False Break + Reversal)
- **Tanım:** Açık bir swing seviyesi (görünür stop bölgesi) önce hafifçe sweep edilir, sonra fiyat hızla ters döner. "Inducement" = obvious likidite, kurumun gerçek niyetini gizleyen tuzak.
- **Bağlam:** Range edge'lerinde, EQH/EQL üstünde, ya da major swing high/low altında.
- **Giriş:** Sweep mumunun close-back-inside onayı.
- **Stop:** Sweep wick'inin ötesi.
- **Hedef:** Range'in diğer ucu veya en yakın HTF likidite.
- **Edge:** Liquidity sweep setup'ının özelleşmiş hali; psikolojik trap mekanizması açık.
- **Failure:** Sweep'in arkasından gerçek breakout — close kalıcı olarak dışarıda kalırsa trend o yönde devam ediyor demektir.

### Setup 9: Power of Three (PO3) — Accumulation, Manipulation, Distribution
- **Tanım:** ICT'ye özgü günlük/seans-içi delivery şablonu. Üç faz:
  1. **Accumulation:** Fiyat dar bir range'de tutulur (Asya seansı tipik).
  2. **Manipulation:** Fiyat range bir tarafa süpürülerek likidite alınır (London seansı tipik).
  3. **Distribution:** Asıl trend yönünde gerçek hareket (NY seansı tipik).
- **Bağlam:** Daily candle'ın oluşumu — günün açılışından kapanışına PO3 yapısı izlenir.
- **Giriş:** Manipulation faza'sının sweep'inde, distribution yönünde.
- **Stop:** Manipulation extreme'inin ötesi.
- **Hedef:** Distribution leg'in projeksiyonu (genelde manipulation leg'in 2-3× büyüklüğü).
- **Edge:** Wyckoff schematic'lerinin (accumulation phase A-E) kompakt versiyonu.
- **Failure:** Manipulation gerçek breakout'tu — distribution beklenen yönde gelmez.

### Setup 10: Mitigation Block (Failed OB)
- **Tanım:** Bir OB başarısız olduktan sonra (fiyat üstünden geçer), o bölge zıt yönlü işlem için kullanılır. Genelde kırılan OB seviyesinin retest'inde.
- **Bağlam:** Yapı dönüşü (CHoCH) sonrası eski OB'lerin yeniden tanımlanması.
- **Giriş:** Eski OB seviyesinin retest'inde, yeni trend yönünde.
- **Stop:** OB'nin yeni "trap" tarafının ötesi.
- **Hedef:** Yeni trend yönündeki ilk likidite havuzu.
- **Edge:** "Failed level becomes opposite resistance/support" prensibinin SMC etiketli versiyonu.
- **Failure:** Yapı dönüşü teyit edilmemişti — orijinal trend devam eder.

---

## Time-Based Concepts (ICT-specific)

ICT'nin diğer SMC kaynaklarından farklılaştığı bir alan, zamana atfedilen önemdir.

### Kill Zones
Belirli saat dilimleri yüksek olasılıklı setup pencereleri olarak işaretlenir (NY saat dilimi referans):
- **London Open Kill Zone:** 02:00 - 05:00 NY (07:00-10:00 GMT). London seansının açılış volatilitesi.
- **NY Open Kill Zone:** 07:00 - 10:00 NY. Özellikle 09:30 NYSE açılışı.
- **London Close Kill Zone:** 10:00 - 12:00 NY. London likiditesinin son hareketi.
- **NY PM Kill Zone:** 13:30 - 16:00 NY. Daily close öncesi son distribution hareketleri.
- **Asia Range:** 20:00 - 00:00 NY. Genelde accumulation, dar range.

İddia: setup'lar bu pencerelerde alınırsa win rate ve R:R artar. **Empirik test:** istatistiksel olarak anlamlı edge muhtemelen sadece "high volatility hours" filtresinden gelir; kill zone *spesifik* iddiası ayrıca test edilmeli.

### Why 09:30 NY Open Is "The" Hour
NYSE açılışı en yüksek likidite ve volatilite penceresidir; hem European session devam ediyor hem de US institutional flow başlıyor. ICT bu saati "judas swing" (sahte ilk hareket sonrası gerçek yön) için kullanır.

### Daily Bias Projection
Önceki günün high/low/midpoint seviyeleri ve bugünün açılış seviyesi referans alınarak günün muhtemel "draw on liquidity" yönü belirlenir. Tipik rule:
- Eğer fiyat previous day high'ı sweep ederse → bias bearish (premium discount mantığı).
- Eğer previous day low'u sweep ederse → bias bullish.

### Weekly / Monthly Opening Levels
Haftalık ve aylık open seviyeleri major equilibrium referansı olarak kullanılır. Fiyat bu seviyenin altında ise haftalık bias bearish, üstünde ise bullish — bu HTF biasing kuralı SMC'de yaygındır.

### Session Liquidity Behavior
- **Asya:** Genelde range, likidite biriktirme.
- **London:** İlk büyük hareket; sıklıkla "judas" yön.
- **NY:** Gerçek günlük yön sıklıkla NY açılışından sonra teyit edilir.

Bu paterni mekanikleştirmek istersek: "London leg sweeps Asia range extreme, NY reverses" — backtest edilebilir bir hipotezdir.

---

## Bağlam ve Filtre Kuralları

SMC'nin pratik uygulamasında setup'ı tetiklemekten daha önemli olan **bağlam filtreleridir**.

### HTF Bias
Top-down approach zorunludur:
1. Aylık veya haftalık trend yönü (external structure).
2. Günlük trend yönü.
3. 4H veya 1H structure.
4. LTF (15m, 5m) entry timing.

Kural: LTF setup'ı sadece HTF bias yönünde alınmalı (counter-trend setup'lar daha düşük olasılık).

### Draws on Liquidity (DOL)
"Fiyat nereye gitmek istiyor?" sorusu. Cevap: en yakın major likidite havuzu. Bu havuz, fiyatın "magnetic target"ıdır ve trade'in T1 hedefi olur.

### Confluence Requirement
SMC traders, tek bir kavramla değil **çoklu confluence** ile işlem alır. Yüksek olasılıklı setup tipik olarak şu üç-dört filtreyi birleştirir:
1. HTF zone (premium/discount).
2. Liquidity sweep (DOL hit).
3. OB veya FVG (mitigation point).
4. CHoCH veya BOS (structure confirmation).

Confluence ne kadar fazlaysa win rate o kadar yüksek iddiası vardır — ancak overfitting riski de o kadar büyür. Sistemde her filtreyi ayrı ayrı backtest et, marginal gain'i ölç.

### No-Trade Zones (Chop)
Range-bound, displacement göstermeyen, küçük gövdeli mum dizileri = no-trade. Sistemde ATR-normalized range filtreleri (örn. ATR_5 < 0.7 × ATR_50) ile chop'u tespit et.

---

## Risk Yönetimi

SMC topluluğunun risk vurguları:

- **Tipik R:R hedefi:** Minimum 1:3, çoğu zaman 1:5+. Düşük win rate'i (varsa %50 altı) yüksek R:R ile telafi etme felsefesi.
- **Stop placement:**
  - OB setup: OB'nin karşı edge'inin 0.2-0.5× ATR ötesi.
  - Liquidity grab: sweep wick'inin 0.2-0.3× ATR ötesi.
  - CHoCH: structure point'in ötesi.
- **Partial close:** İlk likidite hedefinde (T1) %50 kapatma; kalan %50 trail ile veya daha uzak likidite hedefine.
- **Scaling out:** Her major likidite seviyesinde kademeli kapanış.
- **Risk per trade:** Topluluk konsensüsü %0.5 - %1 hesap büyüklüğü.
- **No martingale, no averaging down:** Stop kaçınılmaz; eğer hit olursa pozisyon kapatılır.

---

## Statistical / Quantifiable Edge Conditions (eleştirel)

SMC topluluğunun rigorous istatistik çerçevesi yoktur. Topluluğun (forum, YouTube, Twitter) öne sürdüğü tipik rakamlar:

- **Liquidity grab + reversal:** ~%60-65 win rate, ortalama 1:3 R:R **(community claim, unverified)**.
- **Order block mitigation:** ~%55-65 win rate **(community claim, unverified)**.
- **FVG rejection:** ~%50-60 win rate **(community claim, unverified)**.
- **OTE entry:** ~%55-65 win rate **(community claim, unverified)**.
- **PO3 daily setup:** ~%60-70 win rate **(community claim, unverified)**.

Bu rakamların hiçbiri:
- Out-of-sample test edilmemiş,
- Survivorship bias kontrolü yok,
- Look-ahead bias riski yüksek (geçmişte OB'leri görerek seçmek vs. real-time tespit etmek farklıdır),
- Slippage, komisyon, spread modelleri içermiyor,
- Multiple-comparison düzeltmesi yapılmamış (çok sayıda kavramın bazıları şans eseri "iyi görünür").

**Bizim sistemimizde bu setup'lar Faz 2 backtest gate'inde test edilmeli. Sadece tek bir mekanik tanımlı setup (örneğin: "1D HTF bias + LTF liquidity grab + OB mitigation") seçilip 5+ yıllık tarihsel datada gerçek slippage modeliyle test edilmelidir.** Sonuç community claim'in altında çıkarsa (tipik beklenti) setup edge yoktur veya tanım daraltılmalıdır.

---

## Yaygın Hatalar / Pitfalls

SMC'nin metodolojik tehlikeleri:

1. **Fazla subjektivlik:** "Hangi mum OB?" sorusu sıklıkla post-hoc cevaplanır. Mekanik tanım olmadan iki trader aynı grafikten farklı OB'ler çıkarır.
2. **Confirmation bias:** Her hareket retroactive olarak bir OB, FVG, liquidity grab'e bağlanabilir. Fiyat yukarı gitti = bullish OB çalıştı; aşağı gitti = breaker block oldu. Bu unfalsifiable yapı bilimsel açıdan zayıftır.
3. **Curve-fitting on review:** YouTube videolarında geçmişe bakılarak "mükemmel" setup'lar gösterilir; real-time eşdeğeri çok daha gürültülüdür.
4. **Mekanik kural eksikliği:** "Significant displacement" gibi sübjektif eşikler trader'a göre değişir → backtest tekrarlanabilir değil.
5. **Çok sayıda zaman dilimi karıştırma:** HTF bias bullish, LTF bearish CHoCH... hangisi öncelikli? Topluluk "trader sezgisi" der ama bu sistematik edge'i yok eder.
6. **"Smart money" hipostazı:** "Smart money buradan toplayacak" cümlesi gözlemlenebilir veriye değil, narrative'e dayanır.
7. **Kill zone overfitting:** Belirli saatleri "magic window" ilan etmek; istatistiksel dayanak çoğu zaman volatilite filtresinden ibaret.
8. **Win rate over R:R kafa karışıklığı:** Topluluk hem yüksek win rate hem yüksek R:R iddia eder; bu kombinasyon istatistiksel olarak şüphelidir.

---

## Eleştirel Değerlendirme (önemli)

SMC/ICT'nin metodolojik zayıflıkları sistematik olarak listelenmelidir:

**Zayıflıklar:**
1. **Definition ambiguity:** Order block kaç türdür? Bullish OB? Bearish OB? Breaker? Mitigation? Decisional? Bu listenin ucu açıktır ve farklı eğitmenler farklı tanımlar verir.
2. **Retroactive identification:** Order block'lar genelde *sonraki* displacement'tan tanımlanır → real-time signal olarak gecikmeli.
3. **Lookahead bias riski:** Backtest'lerde "displacement göreceğim" bilgisi kullanılırsa edge yapay olarak şişer. Mechanic implementasyon dikkatli olmalı: OB, displacement bittiği barda işaretlenmeli ve sonraki barlar için kullanılabilir hale gelmeli.
4. **No academic backtest:** Hiçbir peer-reviewed dergide ICT/SMC metodolojisinin tam testi yok. Teorinin yapısı falsifiable olarak formüle edilmemiş.
5. **Tautological framing:** "Smart money grabbed liquidity then reversed" → fiyat reverse etmediyse "actually smart money didn't intend that" denir. Karşı kanıt kabul edilmiyor.
6. **Selection bias in education content:** Eğitim videolarında sadece çalışan trade'ler gösterilir; başarısız setup'ların %40-50'si gizlenir.

**Buna rağmen savunulabilir nedenler:**
1. **Likidite kavramı makro olarak doğru:** Larry Harris ("Trading and Exchanges", 2003) microstructure literatüründe stop-hunt, liquidity-driven price moves gerçek bir fenomen olarak belgelenmiştir. SMC'nin bu kavramı popülerleştirmesi katkıdır.
2. **Order block ≈ Wyckoff LPS analoğu:** Wyckoff'un "Last Point of Support" ve "Spring + Test" yapıları SMC'nin OB + sweep yapısına benzer; Wyckoff yüz yıllık trader topluluğu deneyimine dayanır.
3. **BOS ≈ Brooks "always-in flip":** Al Brooks'un trend break tanımı SMC'nin BOS'u ile büyük ölçüde örtüşür; isim değişiyor, mekanik aynı.
4. **CHoCH ≈ klasik trend reversal:** Dow teorisinin standart trend dönüş mekaniği, sadece etiket değişikliği.
5. **FVG ≈ momentum imbalance gap:** Üç-bar gap deseni, klasik continuation gap kavramının formelleştirilmiş versiyonu.

**Sonuç:** SMC/ICT, eski (Dow, Wyckoff, Brooks) kavramların yeni etiketler altında, dijital trader nesline yeniden paketlenmiş halidir. Yeni etiketlerin tek başına edge sağladığı gösterilememiştir, ancak altta yatan eski kavramların edge'i (likidite, breakouts/pullbacks, structure) kısmen testtable ve uygulanabilirdir. Sistemimiz SMC'yi *kavramsal sözlük* olarak kullanır, *kanıtlanmış strateji* olarak değil.

---

## Cross-references

SMC ↔ Diğer methodologies köprüleri:

### SMC ↔ Wyckoff
- **Order Block ≈ Spring + LPS pair:** Wyckoff'un Phase C Spring (sweep) + Phase D LPS (re-test) yapısı, SMC'nin "liquidity grab + bullish OB mitigation" setup'ına neredeyse birebir denk gelir.
- **Liquidity grab = Selling Climax (SC) / Automatic Rally (AR) yapı:** Capitulation low'u SMC'nin major SSL sweep'i.
- **Accumulation Phase B = SMC range, equal lows oluşumu:** Wyckoff'un "absorption" fazı SMC'nin "liquidity buildup" fazı.
- **Phase E markup = SMC distribution leg (PO3 üçüncü faz):** Trend gerçekleştirme.

### SMC ↔ Brooks (price action)
- **BOS = Trend break / always-in flip:** Brooks'un trendin değiştiğine dair signal-bar mantığı SMC'nin BOS'u ile aynı.
- **OB mitigation entry ≈ Brooks "second pullback":** Bir leg sonrası ilk pullback fail olur, ikincisinde giriş — Brooks'un H2/L2 setup'ı SMC'nin OB mitigation'a benzer.
- **CHoCH = Brooks "major trend reversal":** Brooks da trend reversal için iki HL kırılışını arar.
- **FVG ≈ Brooks "gap bar / measuring move impulse":** Hızlı gap'li hareketler her iki sistemde de momentum kanıtı.

### SMC ↔ Harris (microstructure)
- **Liquidity grab = stop-hunt fade:** Harris microstructure literature'ında stop-loss order absorption olarak belgelenir; SMC bu mekanizmaya narrative ekler.
- **BSL/SSL ≈ Harris "iceberg / hidden orders + visible stops":** Görünür stop havuzlarının kurumlar tarafından "harvest" edilmesi.
- **Equal highs/lows = Harris "obvious technical levels with herd stops":** Harris herd behavior ile SMC retail traders' obvious stops aynı şeyi söyler.

### SMC ↔ Volman (price action)
- **OB mitigation ≈ Volman "tested support/resistance trade":** Volman'ın 70-tick mantığı OB testi ile yapısal olarak benzer.
- **Liquidity grab ≈ Volman "false break + reversal":** İkisi de yapı kırılması sonrası reverse setup'tır.

### SMC ↔ López de Prado (rigor)
- **FBM (financial machine learning) bakışıyla:** SMC kavramları feature engineering için ham malzeme sağlar. "OB present in last N bars", "FVG distance to current price", "liquidity sweep flag" gibi özellikler ML modellerine input olabilir.
- **Critique:** López de Prado'nun **multiple testing**, **deflated Sharpe**, **combinatorial cross-validation** uyarıları SMC iddialarına uygulandığında çoğu setup'ın istatistiksel olarak anlamsız olduğu ortaya çıkar. Sistemimiz bu testleri Faz 2'de uygulayacak.

---

## Bizim Sistemle Bağlantı

SMC kavramlarının sistemimize entegrasyonu için yol haritası:

### Mekanik olarak implemente edilebilir (signals/structure.py):

1. **Swing pivot detection** (fractal, N-bar lookback) → HH/HL/LH/LL etiketleme.
2. **BOS / CHoCH detection** → close-based break of last swing, trend state machine.
3. **Order block identification** → displacement threshold (≥2× ATR) + last opposite candle rule.
4. **Fair Value Gap detection** → 3-bar gap pattern, top/bottom/midpoint kayıt.
5. **Liquidity sweep detection** → wick-through-swing + close-back-inside + min depth filter (≥0.25× ATR).
6. **Equal highs/lows clustering** → tolerance-based level grouping.
7. **Premium / Discount zone calculation** → Fibonacci 50% of last major swing.
8. **OTE zone** → 0.62-0.79 retracement bracket.

Tüm bu fonksiyonlar **deterministic, replicable, lookahead-free** olmalı:
- Bar `t`'deki signal sadece `bars[0..t]` kullanmalı.
- OB displacement teyidi için bekleme bar sayısı parametrik olmalı (örn. `confirm_bars=3`).
- Aktif OB listesi ileri sürdürülürken expired OB'ler (mitigated, broken) flag'lenmeli.

### Subjektif kısımlar dışlanmalı:
- "Hangi OB önemli" — sistemden çıkar; tüm OB'leri tut, sonra olasılık modeline filter olarak ekle.
- Kill zone bias — istatistiksel anlamlılık testi geçmeden setup filter'i olarak kullanma.
- "Smart money intent" — gözlemlenemeyen → modelden çıkar.
- Kavramların "esnek" yorumu — her kavram tek matematiksel tanıma kilitli olmalı; varyantlar ayrı feature olarak.

### Faz 2 Backtest planı:
Tek bir, en güçlü olduğu iddia edilen setup seçilmeli ve full rigor ile test edilmeli:
- **Önerilen seçim:** Daily HTF bias (HH/HL veya LH/LL) + LTF (1H veya 15m) liquidity sweep + OB mitigation entry, 1:3 R:R fixed target.
- **Test parameters:**
  - 5+ yıl tarihsel data (out-of-sample 30%).
  - Realistic spread + slippage model.
  - Walk-forward validation.
  - Multiple parameter sets ile **deflated Sharpe** uygulanmalı.
  - Combinatorial Purged CV (López de Prado).
- **Beklenti:** Community claim'i (~%60 win rate, 1:3 R:R) muhtemelen %45-55 win rate'e düşecek; net edge marjinal ya da sıfır olabilir. Bu sonucu kabul et — yanlış pozitif setup'a sermaye bağlamamak için.

### Pozitif kullanım senaryosu:
SMC kavramları **explainability layer** olarak değerli olabilir: model bir long sinyal verdiğinde, o sinyali "discount zone + bullish OB mitigation + LTF CHoCH" olarak human-readable etiketle açıklamak güven artırır. Bu, SMC'yi *strateji* olarak değil *anlatı* olarak kullanmaktır — meşru bir UX katkısı.

---

## Kapanış Notu

SMC/ICT, modern trader topluluğunun en popüler price action dilidir; eski kavramları yeni etiketlerle yeniden paketleyerek erişilebilirlik sağlamıştır. Ancak metodolojik rigor açısından Wyckoff, Brooks, Volman, ya da López de Prado seviyesinde değildir. Sistemimizde:

- SMC kavramlarının **mekanik olarak tanımlanabilir** kısımlarını feature olarak ekleyeceğiz.
- Topluluk iddialarını rigorous backtest ile **doğrulamadan** strateji olarak kabul etmeyeceğiz.
- Subjektif yorumlar ve narrative-based etiketlemeleri sistemden dışlayacağız.
- Cross-reference'lar üzerinden SMC'nin altında yatan klasik kavramlara (Wyckoff Spring, Brooks always-in, Harris microstructure) güveneceğiz.

Quality rating 4 (5 değil) çünkü iddialar ekseriyetle test edilmemiş community lore'una dayanıyor; ama kavramsal sözlük olarak değerli ve cross-reference köprüleri sayesinde sistemimizin diğer parçalarıyla temas eder.
