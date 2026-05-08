---
source_id: harris_summary
source_type: book
author: Larry Harris
title: Trading and Exchanges - Market Microstructure for Practitioners (notes)
type: reference_only
quality: 5
ingested_date: 2026-05-08
topic_tags: [market_microstructure, order_flow, liquidity, market_makers, slippage, execution]
---

# Harris — Trading and Exchanges (özet notlar)

> Bu doküman Larry Harris'in "Trading and Exchanges" kitabının fikirlerini özetleyen dahili çalışma notlarıdır; orijinal metinden alıntı içermez ve ticari kullanım amaçlı değildir. Tüm telif hakları yazara/yayıncıya aittir.

## Yazarın Çerçevesi

Larry Harris'in kitabı, mikroyapı (microstructure) literatürünün pratisyenlere yönelik en kapsamlı eseri olarak kabul edilir. Harris'in temel mesajı kitabın ilk bölümlerinden itibaren tekrarlanır: "her trader mikroyapıyı anlamalıdır; aksi takdirde mikroyapıyı anlayanlara spread öder." Bu bakış açısı, retail trading literatürünün büyük çoğunluğunun (chart pattern kitapları, indikatör ansiklopedileri, "100% kazandıran sistem" vaatleri) tamamen üstünden atladığı bir gerçeği vurgular: piyasada bir emir verdiğinizde, o emrin karşı tarafında kim olduğu, niyeti ne olduğu, ve sizin emrinizin fiyatı nasıl etkileyeceği — bunlar, hangi indikatörü kullandığınızdan çok daha belirleyicidir.

Harris'in kitabı yapısal olarak üç katmanlı bir taksonomi sunar: (1) piyasa katılımcıları (kim trade ediyor, neden trade ediyor), (2) piyasa mekanizmaları (emirler nasıl eşleşiyor, fiyat nasıl oluşuyor), (3) piyasa kalitesi (likidite, etkinlik, adillik). Bu üçlü çerçeve, retail trader için bile son derece pratik bir mental modeldir: çünkü her trade, bu üç katmanın kesişiminde gerçekleşir.

Bizim sistemimiz açısından Harris'in çerçevesi şu şekilde değerlidir: backtest sonuçlarındaki teorik edge'ler, gerçek piyasada slippage, market impact, ve adverse selection nedeniyle çok büyük oranda erozyona uğrar. Harris'in framework'ü, bu erozyonu sayısal olarak modellemenin ve buna göre pozisyon büyüklüğünü ayarlamanın yolunu sunar. Kitabın çıkış noktası şudur: piyasa, bilgi asimetrisi ve likidite ihtiyacının kesiştiği bir mübadele mekanizmasıdır; trader'ın işi, bu kesişimde kendi pozisyonunu doğru tarafa yerleştirmektir.

## Trader Taxonomy

Harris'in en ünlü katkılarından biri, piyasa katılımcılarını davranışsal motivasyonlarına göre sınıflandırmasıdır. Bu taksonomi, order flow analizi için temel bir mental modeldir.

**Informed Traders (Bilgi-Avantajlı Trader'lar):**
- *Insider traders:* Yasal veya yasadışı içeriden bilgi sahibi olanlar. Order flow imzaları: belirli zamanlamalarda anormal hacim, haber öncesi pozisyon alma.
- *Value traders:* Fundamental değerleme yapan ve mispricing arayan kurumsal yatırımcılar. İmza: uzun vadeli birikim, fiyat düşüşlerinde alım, sabırlı limit emirleri.
- *News traders:* Haber gelir gelmez tepki verenler. İmza: olay-pencereleri içinde patlayan hacim ve volatilite.
- *Technical traders:* Fiyat ve hacim örüntülerinden trade edenler. İmza: kırılım seviyelerinde kümelenen emirler.
- *Sentiment traders:* Piyasa duyarlılığını okuyup pozisyon alanlar. İmza: trend takibi ve momentum.

**Liquidity Traders (Likidite Talep Edenler):**
- *Gamblers:* Eğlence amaçlı trade edenler; uzun vadede negatif beklenti.
- *Hedgers:* Mevcut riskini kapatmak için trade eden ticari katılımcılar.
- *Asset allocators:* Portföy dengeleme için trade eden kurumlar; fiyat-duyarsız.

**Profit-Motivated (Kâr Odaklı Profesyoneller):**
- *Dealers:* Sürekli iki yönlü kotasyon veren, spread'den kazanan oyuncular.
- *Arbitrageurs:* Aynı veya ilişkili varlıklar arasındaki fiyat farklılıklarını kapatanlar.
- *Market makers:* Likidite sağlayıcıları; envanter yönetimi yaparlar.
- *Position traders:* Fiyat hareketlerinden kâr eden direksiyonel oyuncular.

**Utilitarian (Faydacı):**
- *Investors:* Uzun vadeli sermaye değer artışı arayanlar.
- *Borrowers:* Sermaye temini için varlık satanlar.
- *Hedgers:* Üretim/tüketim risklerini kapatanlar (özellikle emtia piyasalarında).

Harris'in vurguladığı kritik nokta: her trader bu kategorilerin bir karışımıdır, ve order flow okumak demek, anlık olarak hangi kategorinin baskın olduğunu çıkarsamak demektir. Örneğin volatil bir kırılımda hızla artan hacim genellikle informed + technical karışımıdır; düşük hacimli yatay konsolidasyon ise asset allocator + market maker baskınlığını işaret eder. Bu çıkarsama, retail trader için bile yapılabilir: time & sales, depth of market, ve volume profile araçları bu sinyalleri verir.

## Market Maker Economics

Harris'in spread teorisi, mikroyapının kalbinde yer alır. Bid-ask spread'i üç bileşene ayrıştırır:

**S = inventory_cost + processing_cost + adverse_selection_cost**

**1. Inventory Holding Costs:** Market maker, kotasyon verdiğinde envanter biriktirir. Bu envanteri taşımak risk barındırır (fiyat ters gidebilir), ve bu riskin maliyeti vardır. Volatilite arttıkça envanter taşıma maliyeti artar — dolayısıyla yüksek volatilite dönemlerinde spread'ler genişler. Matematiksel olarak: inventory_cost ∝ σ² × position_size × holding_time.

**2. Order Processing Costs:** Sabit operasyonel maliyetler — exchange fee'leri, teknoloji altyapısı, personel, regülatif uyum. Bu bileşen tipik olarak küçüktür ve hacimle ters orantılıdır (yüksek hacimde amortize edilir).

**3. Adverse Selection Costs (Kyle Modeli Sezgisi):** Bu, spread'in en derin ve en önemli bileşenidir. Market maker, karşısında kimin olduğunu tam olarak bilemez — gelen emir uninformed (likidite trader'ı) olabilir veya informed (bilgi-avantajlı) olabilir. Eğer karşı taraf informed ise, market maker sistematik olarak yanlış tarafa pozisyon alır. Bu beklenen kaybı kompanse etmek için spread'i genişletir.

**Kyle's Lambda (λ) intuisyonu:**
- λ = informed_var / total_var (informed flow oranı arttıkça lambda büyür)
- λ büyük → her birim emir hacmi fiyatı daha çok hareket ettirir → market impact yüksek
- λ küçük → derin likidite, düşük market impact
- Pratik sonuç: haber öncesi/sonrası dönemler yüksek λ'ya sahiptir; sakin trend'siz piyasalar düşük λ'ya sahiptir.

**Spread'lerin neden genişlediği — bileşenlere göre tepki:**
- Volatilite şoku → inventory_cost yükselir → spread genişler
- Beklenmedik haber → adverse_selection riski artar → spread agresif şekilde genişler (bazen 5-10x)
- Likidite çekilmesi (örn. açılış/kapanış öncesi, hafta sonları) → tüm bileşenler artar
- Düşük hacim dönemleri → processing_cost amortismanı azalır → spread göreli olarak büyür

Bu çerçeve, bizim sistemimiz için doğrudan uygulanabilir: spread genişlemesi, sadece bir maliyet değil aynı zamanda bir bilgi sinyalidir. Spread aniden genişlediğinde, market maker'lar adverse selection riski algılıyor demektir — bu, gelmekte olan bir bilgi/haber anomalisi için erken uyarıdır.

## Order Types & Their Strategic Use

Harris emir türlerini sadece teknik tanımlarıyla değil, stratejik kullanımlarıyla ele alır. Her emir türü farklı bir "talep-arz" pozisyonu temsil eder:

- **Market Order (MO):** Anlık likidite talebi; spread öder, fill garantisi var, fiyat garantisi yok. Retail için en pahalı; ancak bilgi avantajlıysan ve hız önemliyse mantıklıdır.
- **Limit Order (LO):** Likidite arzı; spread kazanır, fill garantisi yok, fiyat garantisi var. Adverse selection riski taşır (size dolmuyorsa fiyat genelde yanına doğru gidiyordur — sizden daha akıllı biri var).
- **Stop Order:** Tetiklendiğinde market order'a dönüşür. Kullanım: trend takibi giriş, stop-loss çıkış. Risk: stop-hunt'ler ve gap'lerde kötü fill.
- **Stop-Limit:** Tetiklendiğinde limit order'a dönüşür. Kötü fill riskini azaltır ama no-fill riskini ekler. Volatil piyasalarda stop-loss için tehlikeli olabilir.
- **Iceberg / Hidden:** Görünür kısım küçük, asıl size gizli. Kurumsal kullanımdır; piyasa etkisini minimize eder. Retail trader için tespit etmek edge'dir (volume burst + price impact disconnect).
- **Peg Orders:** Bid'e/ask'a/mid'e bağlı dinamik limit. Market maker'ların ana enstrümanıdır.
- **Fill-or-Kill (FOK):** Tamamı anında dolmazsa iptal. Büyük blok için kullanılır.
- **Immediate-or-Cancel (IOC):** Anında dolanı al, kalanı iptal. Likidite tarama için ideal.
- **Time-in-Force (GTC, IOC, FOK, GTD):** Emrin yaşam süresi.

**Retail vs Institutional perspektifi:**
- Retail: Genellikle market order ve basit limit kullanmalı; karmaşık emir türleri çoğunlukla yanlış konfigüre edilir. Stop-loss her zaman zorunlu, stop-limit volatil piyasalarda tehlikeli.
- Institutional: Iceberg, peg, ve algorithmic execution (TWAP, VWAP, POV) standarttır. Amaç: piyasa etkisini minimize etmek.

## Liquidity Concepts

Harris likiditeyi tek boyutlu bir kavram olarak ele almaz; dört boyutta ölçer:

**1. Depth (Derinlik):** Verilen bir fiyat seviyesinde ne kadar hacim alıp satılabilir. Ölçüm: order book'ta top-10 seviyenin toplam volume'u. Yüksek depth = büyük emirler az slippage ile geçer.

**2. Breadth (Genişlik):** Piyasanın aktif hisse/varlık sayısı ve katılımcı çeşitliliği. Breadth düşükse, birkaç büyük oyuncu piyasayı domine eder ve manipülasyon riski artar.

**3. Resilience (Esneklik):** Bir likidite şokundan sonra piyasanın eski derinliğine ne kadar hızlı dönmesi. Ölçüm: büyük bir emir spread'i genişlettikten sonra spread'in mean-reversion hızı. Yüksek resilience = market maker'lar agresif şekilde tekrar kotasyon veriyor.

**4. Immediacy (Anındalık):** Bir trader'ın emrini ne kadar hızlı doldurabildiği. Market order için bu trivial olarak hızlıdır; ama "size'lı" emir için (örn. 1000 BTC) immediacy düşer çünkü bu kadar likidite anlık olarak yoktur.

**Crypto vs Equity karşılaştırması (Harris yazsaydı eklerdi):**
- Crypto exchange'leri: Shallow depth (göreceli olarak), ancak yüksek resilience (HFT market maker'ları çok aktif). 7/24 işlem, fragmentation yüksek.
- Equity exchange'leri: Deep depth (özellikle large-cap), ama daha yavaş resilience (market maker'lar daha az agresif). Auction-based açılış/kapanış. Sınırlı işlem saatleri.
- Pratik sonuç: BTC/ETH'de 100K USD'lik bir trade slippage olarak ~5-15bp ödetir; SPY'de aynı boyut ~1-3bp ödetir. Ancak crypto'da bu likidite hızlıca yenilenir.

## Setup Kataloğu (Microstructure Edge Sources)

Aşağıda Harris'in çerçevesinden türetilebilecek 9 mikroyapı edge'i, sistematik 7-blok formatta sunulmuştur.

### 1. Stop-Hunting Fade

- **Tanım:** Bilinen stop kümelerinin (örn. yuvarlak sayılar, swing low/high'lar, prior day low) altına/üstüne ani fitil ile fiyat çıkar, stop'lar tetiklenir, ardından fiyat hızla geri döner.
- **Bağlam:** Düşük likidite saatleri (Asya seansı, hafta sonu açılışı), önemli teknik seviyeler.
- **Giriş:** Fitil oluştuktan ve önceki kapanışın iç tarafına dönülmesinden sonra, yön reverting tarafa.
- **Stop:** Fitilin uç noktasının ötesi (genelde 0.3-0.5 ATR).
- **Hedef:** Stop kümesinin oluştuğu seviyenin orijinal yapısı (R:R minimum 2:1).
- **Edge:** Market maker'lar ve large traders, likidite topladıktan sonra fiyatı geri çevirir (Kyle modeline uygun olarak).
- **Failure:** Eğer fitil sonrası fiyat reverting olmuyorsa, gerçek bir kırılımdır — çıkış yapılmalı.

### 2. Liquidity Sweep / Iceberg Detection

- **Tanım:** Görünmeyen büyük emirler, hacim patlaması ile ortaya çıkar; price impact disproportionate biçimde küçük olur.
- **Bağlam:** Konsolidasyon bölgelerinde, özellikle round-number'larda.
- **Giriş:** Yüksek hacim + düşük price impact tespit edildikten sonra, iceberg'in yönüne paralel pozisyon.
- **Stop:** Iceberg seviyesinin diğer tarafı.
- **Hedef:** Bir sonraki yapısal seviye veya iceberg'in tükenmesinin işareti (hacim normalleşmesi).
- **Edge:** Iceberg, kurumsal absorpsiyon demektir; bu absorpsiyon biter bitmez fiyat tipik olarak iceberg'in yönüne kırılır.
- **Failure:** Iceberg yanlış tespit edilmişse (hacim haberle açıklanabilirse), tipik mean-reversion gözlenmez.

### 3. Closing Auction Imbalance

- **Tanım:** Kapanış müzayedesinde imbalance bilgisi (alış ya da satış fazlalığı) yayınlanır; bu bilgi son birkaç dakikada fiyatı yönlendirir.
- **Bağlam:** Equity piyasalarında günün son 10 dakikası (NYSE/NASDAQ closing auction).
- **Giriş:** Imbalance açıklandığında, imbalance yönüne pozisyon (örn. büyük alış imbalance → long).
- **Stop:** Imbalance tahmin yanlışsa hızlı çıkış (1-2 dakika içinde).
- **Hedef:** Kapanış fiyatına yakın likiditeyi kullanarak müzayede sonrası exit.
- **Edge:** Imbalance, ETF rebalancing ve indeks arbitrajı nedeniyle güvenilir bir sinyaldir.
- **Failure:** Aynı gün önemli bir haber varsa imbalance bilgisi yanıltıcı olabilir.

### 4. News-Driven Spread Blowout Fade

- **Tanım:** Önemli haber sonrası spread aşırı genişler; ilk birkaç saniyede fiyat aşırı tepki verir, ardından normalleşme olur.
- **Bağlam:** Earnings, FOMC, CPI gibi planlanmış haber olayları sonrası ilk 30-120 saniye.
- **Giriş:** Initial spike sonrasında, mean-reversion'a doğru limit order.
- **Stop:** Spike'ın uç noktasının ötesi.
- **Hedef:** Pre-news fiyatın %50 düzeltmesi.
- **Edge:** Adverse selection cost geçici olarak şişer; market maker'lar normalleştikçe spread daralır ve fiyat reverting olur.
- **Failure:** Haber gerçek bir paradigma değişikliğiyse (örn. unbeklenen rate hike), reversion gerçekleşmez.

### 5. Rebate Arbitrage (Maker-Taker Exploitation)

- **Tanım:** Maker rebate veren exchange'lerde, limit order ile likidite sağlayarak rebate kazanma; aynı pozisyon tekrar kapatılır.
- **Bağlam:** Sürekli bir piyasa, yeterli volatilite.
- **Giriş:** Bid'in üstünde limit order; doldurulduktan sonra ask'ın altında satış.
- **Stop:** Pozisyonun teknik invalidation seviyesi.
- **Hedef:** Spread + rebate kâr.
- **Edge:** Yapısal bir edge'dir; ancak HFT bunu agresif şekilde kovalar — retail için marjinal.
- **Failure:** Adverse selection: limit order doluyorsa, fiyat genellikle yanına gider.

### 6. Latency Arbitrage (Bağlamsal — Retail için DOĞRUDAN uygulanabilir DEĞİL)

- **Tanım:** Aynı varlığın iki farklı venue'da fiyat farkından yararlanma; mikrosaniyeler içinde gerçekleşir.
- **Bağlam:** HFT firmalarının domain'i; retail trader'ın doğrudan uygulayabileceği bir strateji değildir.
- **Önemli olan:** Retail trader'ın bilmesi gereken şudur — eğer venue'nuzda spread bir anda anormal şekilde dar veya geniş oluyorsa, bu HFT'nin başka bir venue'daki bilgiyi sizin venue'nuza taşımasıdır. Yani siz HFT'nin "yavaşlatılmış" tarafındasınız.
- **Edge yok, ama dikkat:** Saniye altı işlemler yapmaya çalışan retail strategy'leri sistematik olarak HFT'ye spread öder.

### 7. Order Book Imbalance Signal

- **Tanım:** Top-N seviyelerde bid-side hacim ask-side hacimden belirgin biçimde fazlaysa (oran > 0.6), kısa vadeli yukarı yönlü baskı vardır.
- **Bağlam:** Top of book imbalance, özellikle low-volatility regime'de güvenilir.
- **Giriş:** OBI = (bid_vol - ask_vol) / (bid_vol + ask_vol), |OBI| > 0.6 olduğunda yöne pozisyon.
- **Stop:** Sıkı; sinyal kısa-vadelidir, 1-5 dakika.
- **Hedef:** 1-3 tick veya OBI sinyali tersine döndüğünde exit.
- **Edge:** Order flow'un kısa-vadeli direksiyonel tahmin gücü (literatürde de kanıtlanmıştır — Cont, Kukanov, Stoikov 2014).
- **Failure:** Iceberg veya spoof'ing sinyali bozar; "fake" OBI sinyalleri.

### 8. Round-Number Liquidity Magnet

- **Tanım:** Yuvarlak sayılarda (örn. BTC için 50000, 60000) emir kümelenir; fiyat bu seviyelere "manyetik" olarak çekilir, sonra tepki verir.
- **Bağlam:** Trend'siz veya zayıf trendli piyasalar.
- **Giriş:** Yuvarlak sayıya yaklaşıldığında touch ve reversal pattern bekle; reversal teyidiyle gir.
- **Stop:** Yuvarlak sayının ötesi (0.2-0.3 ATR).
- **Hedef:** Önceki konsolidasyon orta noktası.
- **Edge:** Behavioral finance ve emir kümelenme sinyali; market maker'lar bu seviyelerde likiditeyi kullanır.
- **Failure:** Güçlü trend rejiminde yuvarlak sayılar magnet değil, hızla aşılan seviyelerdir.

### 9. Funding-Rate Arb (Crypto Perp-Spot — Harris yazsaydı eklerdi)

- **Tanım:** Perpetual futures funding rate aşırı pozitif (ya da negatif) olduğunda, perp short + spot long (ya da tersi) ile delta-neutral pozisyon ile funding kazanma.
- **Bağlam:** Funding rate > 0.05% (8h) gibi aşırı durumlar; piyasa aşırı bull veya aşırı bear sentiment.
- **Giriş:** Eşzamanlı perp short + spot long; kapital ihtiyacı: ~2x notional.
- **Stop:** Funding normalleşene kadar tut; ya da basis riski yönetilemez hale gelirse çık.
- **Hedef:** Funding birikimi ile yıllıklaştırılmış %20-50 (yüksek funding dönemlerinde).
- **Edge:** Yapısal; perp-spot arasında anchor mekanizması.
- **Failure:** Exchange counterparty risk, basis blowout, funding rate aniden tersine dönerse pozisyon ters çalışır.

## Slippage Modeling

Harris'in slippage çerçevesi iki ana boyutta düşünür: temporary impact (geçici, emir bittikten sonra geri döner) ve permanent impact (kalıcı, bilgi içeriği ima eder).

**Linear vs Square-Root Impact Functions:**

- **Linear model:** slippage ∝ Q (emir büyüklüğü ile doğrusal). Sadece çok küçük emirler için doğru olur.
- **Square-root model:** slippage ≈ k × σ × sqrt(Q/ADV)
  - k: piyasa-spesifik sabit (~0.5-1.5 tipik)
  - σ: günlük volatilite
  - Q: emir büyüklüğü
  - ADV: average daily volume
  - Bu, ampirik olarak en sağlam modeldir (Almgren, Chriss, Kissell çalışmalarıyla doğrulanmış).

**Pratik örnekler:**
- BTC için σ ≈ %3 günlük, ADV ≈ 30B USD spot. 1M USD'lik market order:
  - slippage ≈ 1.0 × 0.03 × sqrt(1M/30B) ≈ 0.03 × 0.0058 ≈ 17bp
- ETH için σ ≈ %4, ADV ≈ 15B. 1M USD market order: ≈ 33bp
- Liquid altcoin (örn. SOL) için σ ≈ %5, ADV ≈ 2B. 500K USD market order: ≈ 79bp

**Temporary vs Permanent Impact:**
- Temporary: Likidite tüketimi nedeniyle anlık fiyat etkisi; emir biter bitmez fiyat genelde geri çekilir.
- Permanent: Bilgi içeriği nedeniyle kalıcı fiyat etkisi; informed flow olduğunu işaret eder.
- Tipik dağılım: total impact'in %30-50'si permanent, kalan kısmı temporary.

**VWAP execution neden market order'ı yener (size için):**
- Market order: tüm Q'yu anlık olarak basar; slippage = k × σ × sqrt(Q/ADV)
- VWAP over T saat: emir T süreye yayılır; her dilim için slippage = k × σ × sqrt(Q/T/ADV)
- Toplam beklenen impact, kabaca 1/sqrt(T) ile azalır
- Pratik: 1M USD'lik bir emir bir saatte VWAP ile yapıldığında, tek seferdeki market order'a göre slippage'ı ~%50-70 azaltabilir (ancak timing risk ekler).

**ADV yüzdesine göre slippage tahmini (BTC örneği):**
- %0.01 ADV: <2bp
- %0.1 ADV: ~5-10bp
- %1 ADV: ~30-50bp
- %5 ADV: ~80-150bp (bu boyutta artık VWAP/iceberg zorunlu)

## Auction Mechanisms

Equity piyasalarının iki kritik anı vardır: opening auction ve closing auction. Bu anlar mikroyapı bakımından özeldir çünkü continuous trading mekanizmasından farklı çalışırlar.

**Opening Auction:**
- Pre-market'te biriken emirler, açılışta tek bir uniform fiyatta eşleştirilir.
- Bu fiyat, emirleri en çok eşleyen (maximum executable volume) fiyattır.
- Açılış fiyatı, gece boyunca biriken bilginin (overnight news, foreign markets) kondansatörüdür.
- Pratik: Gap up/down açılışlar, overnight informed flow miktarını gösterir.

**Closing Auction:**
- Günün son anında benzer bir mekanizma; ETF NAV hesaplaması ve indeks rebalancing için kritik.
- Imbalance bilgisi: Son 10 dakikada periodically yayınlanır (NYSE: 3:50 PM ITF). Bu bilgi, hangi yönde fazla emir olduğunu gösterir.
- Closing fiyatı genellikle "official" fiyat olarak kabul edilir (mark-to-market, ETF NAV, options settlement).

**Print'i okumak:**
- Yüksek closing volume + büyük imbalance = kurumsal flow + indeks rebalancing.
- Düşük closing volume + dengeli imbalance = retail-dominant gün.
- Imbalance yönü ile kapanış öncesi son fiyat hareketi tutarsızsa, market maker'lar agresif tepki vermiş demektir.

Crypto piyasalarında auction mekanizması yoktur (sürekli işlem); ancak bazı exchange'ler (örn. Binance) "settlement" anlarında perp funding hesaplaması yapar, bu da benzer bir "özel an" yaratır.

## High-Frequency vs Low-Frequency Trading

Harris'in framework'ünde hız, mikroyapının üçüncü boyutudur (zaman boyutu). Speed dimension'ı şöyle parçalanabilir:

**HFT (High-Frequency Trading) ne yapar:**
- Market making (yarı-pasif likidite sağlama)
- Statistical arbitrage (pairs, triplets, baskets)
- Latency arbitrage (cross-venue)
- Event-driven (microsecond reaction to news APIs)
- Order anticipation (büyük emirleri önden satın alma — kısmen tartışmalı)

**HFT'nin mikroyapıdaki etkisi:**
- Spread'leri daraltır (çünkü inventory turnover yüksek, riski hızla pas eder).
- Volatil dönemlerde likiditeyi geri çeker (HFT'ler riski sevmez, en kritik anda kaçabilirler — örn. Flash Crash, May 6 2010).
- Resilience'ı artırır (normal koşullarda).

**Retail neden HFT'den izole edilebilir (1D timeframe):**
- 1 günlük bar içinde HFT'nin oluşturduğu mikro-noise tamamen yıkanır.
- Daily entry/exit'lerde HFT, sadece spread kaybı (1-3bp typical) olarak hissedilir.
- Aksine: 1-5 dakika timeframe'de retail trader sürekli HFT karşısında çıkıyor demektir; bu tehlikelidir.

**Execution venue choice retail için neden hâlâ önemli:**
- Aynı varlık farklı venue'larda farklı spread, depth, ve fee yapısına sahiptir.
- Crypto'da: Binance (deep, 0bp maker rebate), Coinbase (yüksek spread, regulated), Kraken (orta).
- Equity'de: NYSE, NASDAQ, BATS, IEX (slow market). IEX retail için en az adverse-selection'lı.

## Crypto-Specific Microstructure (Harris yazsaydı)

Harris'in kitabı 2003'te yazıldı, dolayısıyla crypto bahsi yok. Ancak çerçevesi crypto'ya doğal bir uzantıdır:

**Perpetual Swap Funding Mechanics:**
- Funding rate = (premium_index + clamp(interest_rate - premium_index, ±0.05%))
- Genellikle 8 saatte bir tahsil edilir (Binance, Bybit) veya 1 saatte bir (FTX, dYdX)
- Pozitif funding → long'lar short'lara öder → bull bias kompanse edilir
- Funding rate, perp ile spot fiyatı arasındaki anchor mekanizmasıdır
- Aşırı funding rate'ler informed flow ve over-leverage işaret eder

**Exchange Fragmentation Arbitrage:**
- Aynı altcoin 5-10 farklı exchange'de listelenebilir; spread'ler ve depth farklılık gösterir.
- Cross-exchange arbitrage: BTC fiyatı Binance'da $50,000, Kraken'de $50,030 ise, market neutral arb yapılabilir.
- Ancak transfer süreleri (BTC ~10 dakika, ETH ~3 dakika) büyük risk yaratır; bu yüzden gerçek arb genelde "her exchange'de yeterli envanter" stratejisiyle yapılır.

**On-Chain Settlement Effects:**
- Büyük transfer'ler (whale movement) on-chain monitor edilebilir; bu informed flow için erken işaret olabilir.
- Stablecoin mint/burn events likidite şokları yaratır.
- Mining/validator rewards günlük supply baskısını etkiler.

**Market-Maker Programs:**
- Binance, OKX, Bybit gibi exchange'ler MM'lere rebate ve VIP program sunar.
- VIP-level fee structure: BTC için maker fee'leri -0.005% (rebate) ile +0.02% arasında değişir.
- Retail trader bu rebate'leri alamaz; ama bilmek ki MM'ler agresif fiyatlama yapabilir, retail'in beklediği "doğal" spread'in çok altında.

## Statistical / Quantifiable Edge Conditions

Harris çerçevesinden türetilen sayısal eşikler (operasyonel kullanım için):

**Tipik bid-ask spread'ler (% fiyat olarak):**
- BTC spot (Binance, top-tier): 0.5-1.5 bp
- BTC perp (Binance): 0.5-1.0 bp
- ETH spot: 1-3 bp
- ETH perp: 0.5-2 bp
- Top-10 altcoin spot: 5-20 bp
- Mid-cap altcoin: 20-100 bp
- Long-tail altcoin: 100bp+
- SPY (equity): 0.5-1 bp
- AAPL: 1-2 bp

**Order book depth eşikleri:**
- Healthy: top-10 levels'da, 1% price impact için >50K USD (BTC için >5M USD)
- Marjinal: top-10'da 1% impact için 10-50K USD; trade boyutu küçültülmeli
- Tehlikeli: top-10'da 1% impact için <10K USD; piyasa likidite gate'i tetiklemeli

**Slippage estimates (% ADV bazlı):**
- 0.01% ADV: <2 bp expected slippage
- 0.1% ADV: 5-10 bp
- 1% ADV: 30-50 bp (single-shot market order)
- 1% ADV with VWAP over 1h: 15-25 bp
- 5% ADV: 80-150 bp single-shot, 40-70 bp VWAP
- >5% ADV: artık discretionary execution + iceberg zorunlu

**Order Book Imbalance threshold (top-5 levels):**
- |OBI| > 0.6: güçlü direksiyonel baskı
- |OBI| > 0.8: aşırı; ya gerçek absorption var ya da spoof tehlikesi
- |OBI| < 0.2: dengeli; sinyal yok
- Holding period: 30-300 saniye

**Spread blowout threshold:**
- Normal spread'in 3x üstüne çıkıyorsa: news/event yaklaşıyor demektir
- Normal spread'in 5x üstü: strict liquidity gate; yeni pozisyon açma
- Normal spread'in 10x üstü: piyasa "broken"; mevcut pozisyonlar bile gözden geçirilmeli

## Yaygın Hatalar / Pitfalls

Harris'in implicit (ve bazen explicit) uyardığı hatalar:

**1. Backtesting without realistic spread:** En yaygın hata. Mid-price ile fill almak, retail trader'ın gerçek piyasada deneyimleyemediği bir senaryodur. Backtest'te her trade'e en azından (spread/2 + commission) eklemeli.

**2. Ignoring market impact for size:** Stratejinin %1 ADV'lik bir emir verdiği varsayılırsa ve bu boyutta market impact %50bp ise, backtest'te tüm trade'lerden 50bp düşürülmeli. Çoğu retail backtester bunu yapmaz.

**3. Using mid-price for fills:** Mid-price'a girmek/çıkmak, market maker olduğunuzu varsayar ki retail için gerçekçi değildir. Realistic fill: market order için ask (long) / bid (short); limit order için %30-50 fill rate varsayımı.

**4. Neglecting funding rate carry:** Crypto perp pozisyonlarında funding rate kümülatif olarak büyük etki yapar. Yıllıklaştırılmış %20+ funding kostunu görmezden gelen long-bias bir strateji, yıl sonunda %20 alpha'sını kaybeder.

**5. Latency assumption errors:** "Sinyal oluştuğu anda gir" varsayımı, retail için gerçekçi değildir. Sinyal hesaplama + order routing + fill = minimum 500ms-2s gecikme. 1 dakika timeframe'de bu bile %2-5 fark yaratabilir.

**6. Liquidity gate ignorance:** Düşük likidite saatlerinde (Asya seansı sonu, ABD tatilleri) backtest'te güzel görünen sinyaller, gerçek piyasada execute edilemez veya 3-5x slippage öder.

**7. Adverse selection on limit orders:** "Limit order ile spread'i kazanırım" yaklaşımı, sistematik olarak adverse selection riskini ihmal eder. Limit emirleriniz dolduğunda, fiyat genelde sizin aleyhinize gitmektedir.

**8. Stop-loss as market order in volatile gaps:** Gap'lerde stop-loss market order'a dönüşür ve beklenenden çok kötü fill alabilir. Stop-limit ise tetiklenmeyebilir. Çözüm: pozisyon büyüklüğünü tail risk'e göre boyutlamak.

**9. Auction print misinterpretation:** Closing print'i gün-içi sinyalle aynı şekilde yorumlamak. Auction print farklı bir mekanizmadır ve farklı analitik gerektirir.

**10. Cross-venue price discovery confusion:** Tek venue'dan baktığınız fiyat, "gerçek" fiyat olmayabilir. Özellikle crypto'da farklı venue'lar farklı fiyatlar gösterir; consolidated price feed kullanmak önemlidir.

## Cross-references

**Harris ↔ Chan:**
- Chan ML-first yaklaşır: feature engineering, backtest, statistical inference. Mikroyapı detayları daha az.
- Harris mechanism-first yaklaşır: önce piyasa nasıl çalışır, sonra edge nereden gelir.
- Sentez: Chan'in metodolojisi Harris'in fiziksel anlayışıyla beslenmelidir; aksi takdirde feature'lar mikroyapıdan kopuk istatistiksel illüzyonlar olur.

**Harris ↔ Brooks:**
- Brooks'un "always-in" reads, "two-legged pullback" gibi pattern'leri Harris'in framework'ünde institutional positioning olarak yorumlanabilir.
- Brooks: "Bu noktada güçlü alıcılar var" — tanımlayıcı.
- Harris: "Bu noktada market maker'lar pozisyon kapatıyor / informed traders absorpsiyon yapıyor" — açıklayıcı.
- Brooks pattern'ler "ne" der, Harris "neden" der.

**Harris ↔ Wyckoff:**
- Wyckoff'un Composite Operator (CO) kavramı, Harris'in informed trader + market maker karışımının erken bir versiyonudur.
- Accumulation / distribution: Harris terminolojisinde "informed flow building inventory in low-impact phase".
- Spring / upthrust: stop-hunting fade'in Wyckoff'çu adı.
- Markup / markdown: informed flow tarafından başlatılan, momentum trader'lar tarafından devam ettirilen direksiyonel hareket.

**Harris ↔ Lopez de Prado:**
- Lopez ML/AI tarafında derinleşir; meta-labeling, fractional differentiation gibi araçlar.
- Harris bu araçların altında yatan piyasa mekanizmasını sağlar.
- Volume bars / dollar bars (Lopez) doğrudan Harris'in volume-time hipotezi üzerine kuruludur.

**Harris ↔ Volman/Grimes:**
- Volman ve Grimes pure price action eğitimi yaparlar; mikroyapı bahsetmezler.
- Harris açısından, onların setup'ları "informed flow + technical trader confluence" örnekleridir.
- Pratik kullanım: Volman/Grimes setup'ı tetikleniyor + Harris'in liquidity koşulları sağlanıyor → güvenli giriş.

## Bizim Sistemle Bağlantı

Harris'in çerçevesi, bizim otonom trading sisteminde birden fazla noktada doğrudan kullanılabilir:

**1. Liquidity Gate (`risk.yaml::liquidity_gate`) doğrulaması:**
- Harris'in dört-boyutlu likidite kavramı (depth, breadth, resilience, immediacy) bizim mevcut liquidity_gate'imizi kavramsal olarak doğrular.
- Mevcut gate muhtemelen sadece volume veya spread bakıyor; Harris'in çerçevesine göre depth + spread + resilience kombinasyonu gerekli.
- Öneri: gate'e order book depth metriği ve spread normalizasyonu eklenmeli.

**2. Slippage Modeli rafinasyonu:**
- Mevcut slippage assumption muhtemelen sabit (örn. 5bp).
- Harris'e göre slippage = k × σ × sqrt(Q/ADV) formülüne geçilmeli.
- Backtest'te bu formülün canlı volatilite ve günlük hacme göre dinamik hesaplanması, daha gerçekçi sonuç verecektir.

**3. Order Book Imbalance Signal eklenmesi:**
- `signals/` dizinine OBI feature'ı eklenebilir: top-5 levels bid_vol / ask_vol oranı, 30-300 saniye holding period.
- Mikroyapı-tabanlı bir feature olarak teknik sinyallerle birleştirildiğinde alpha katkısı sağlayabilir.
- Özellikle range-bound rejimde güvenilirdir.

**4. Funding-Rate Arb Faz 3+ stratejisi:**
- Crypto perp-spot funding-rate arb, delta-neutral bir stratejidir.
- Mevcut sistemde direksiyonel pozisyonlar var; Faz 3+'da delta-neutral leg eklenebilir.
- Operasyonel: 2x kapital ihtiyacı, perp short + spot long, funding harvest.

**5. Spread blowout monitor:**
- Risk modülüne "spread anomaly detector" eklenebilir.
- Spread normal ortalamasının 3x üstüne çıkıyorsa: yeni giriş bloke; 5x üstüne çıkıyorsa: mevcut pozisyon hedge sinyali.

**6. Auction-aware execution:**
- Equity tarafında stratejimiz olursa (Faz 4+), opening/closing auction'ı ayrı execution venue olarak ele almalıyız.
- Crypto için "settlement window" (funding tahsil anları) benzer şekilde ele alınmalı: o anlarda artan volatilite ve likidite şoku riski.

**7. Trader taxonomy via order flow:**
- Volume profile + time & sales analizi ile gün-içi "kim trade ediyor" çıkarsaması yapılabilir.
- Yüksek hacim + dar spread + sürdürülen yön = informed flow → trend takip et
- Yüksek hacim + geniş spread + hızlı reversal = liquidity sweep → fade et
- Düşük hacim + sürdürülen yön = absorption (iceberg olabilir) → trend takip et ama küçük size ile

**8. Latency-realistic backtesting:**
- Sinyalden order'a geçiş gecikmesi (500ms-2s) backtest'e dahil edilmeli.
- Özellikle yüksek frekanslı stratejiler için bu kalibrasyon kritiktir.

**Sonuç:** Harris'in framework'ü, retail-quant bir sistem için "dış görünüş" ile "iç mekanizma" arasındaki uçurumu kapatan en önemli teorik kaynaktır. Bizim sistemimizin her bileşeni — sinyal üretimi, risk yönetimi, execution, position sizing — Harris'in mikroyapı çerçevesine göre ayrı ayrı kalibre edilmelidir. Aksi takdirde, backtest sonuçlarımız teorik olarak güzel görünse bile gerçek piyasada slippage, adverse selection, ve impact maliyetleri tarafından sistematik olarak erozyona uğrayacaktır. Harris'in tek cümlesi bu işin özüdür: "her trader mikroyapıyı anlamalı, ya da onu anlayanlara spread ödemeli."
