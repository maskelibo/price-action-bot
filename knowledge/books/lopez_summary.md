---
source_id: lopez_summary
source_type: book
author: Marcos López de Prado
title: Advances in Financial Machine Learning (notes)
type: reference_only
quality: 5
ingested_date: 2026-05-08
topic_tags: [ml_for_trading, quant_finance, statistical_methodology, backtest_overfit, meta_labeling, fractional_differentiation]
---

# López de Prado — Advances in Financial Machine Learning (özet notlar)

> Telif uyarısı: Bu doküman yalnızca dahili araştırma amaçlı bir özet/notlar koleksiyonudur; orijinal eserin yerine geçmez. Tüm haklar Marcos López de Prado ve yayıncılarına aittir.

---

## Yazarın Çerçevesi

Marcos López de Prado, 2018'de yayımlanan *Advances in Financial Machine Learning* (AFML) ve 2020'deki *Machine Learning for Asset Managers* (MLAM) ile modern kuantitatif trading araştırmasının metodolojik standardını yeniden yazmıştır. Citadel, AQR, Cornell ve Lawrence Berkeley National Lab'daki rolleri sayesinde hem üretim ortamında hem akademik düzlemde test edilmiş bir çerçeve sunar. Kitabın iki ana mesajı, modern kuant kültüründe sloganlaşmıştır:

1. **"%95 of backtests are wrong because of methodology"** — Yayımlanan ya da dahili olarak üretilen Sharpe rakamlarının çoğu *selection bias*, *multiple testing*, *leakage*, *non-IID artefacts* nedeniyle gerçekte var olmayan bir edge'i raporlar. Sorun model değil, deneysel tasarımdır.
2. **"ML cannot fix bad data labeling"** — Hangi modeli (XGBoost, LSTM, transformer) kullandığınız önemsizdir; *label* yanlış tanımlanmışsa model gürültü ezberler. Finansal etiketleme; barlama, etiketleme, örnekleme ve ağırlıklandırma adımlarının ayrı bir disiplin olmasını gerektirir.

López'in temel epistemolojik tezi şudur: *finansal veri IID değildir.* Standart ML literatürü (vision, NLP) IID gözlem varsayımına dayanır; bu varsayım finansta dört yönden ihlâl edilir:

- **Serial dependence:** ardışık fiyat hareketleri otokorele.
- **Heteroscedasticity & regime shifts:** volatilite, korelasyon ve risk premia rejim bağımlı.
- **Overlapping samples:** *t* zamanındaki etiket ile *t+1* zamanındaki etiket aynı geleceği paylaşır → bilgi sızıntısı.
- **Non-stationarity:** mean, variance, drift zamanla değişir; "fit once" yaklaşımı çöker.

Bu nedenlerle López, doğrudan ML uygulamak yerine bir *pipeline reform* önerir: (i) doğru bar yapısı, (ii) doğru etiketleme, (iii) doğru CV, (iv) doğru bet sizing, (v) doğru backtest istatistikleri. AFML, modern quant trading literatüründe en çok atıf alan tek kitap konumundadır ve "ML for trading" alanında *de facto* metodolojik referanstır.

Bir başka kritik vurgu: López, "büyük model" yerine "küçük disiplinli pipeline" felsefesini savunur. Onun tezine göre bir *random forest* ya da *gradient boosting* model dahi, doğru bar / label / weight / CV altyapısıyla, çok daha sofistike (ve yorumlanması zor) deep learning mimarilerinin önüne geçer. Sebep basit: finansal veri *low signal-to-noise* ortamıdır; yüksek kapasite modeller gürültüyü ezberler. Disiplinsiz bir transformer, disiplinli bir ridge regresyondan rutin olarak kötüdür. López'in "ML cannot fix bad data labeling" mottosunun pratik karşılığı budur — model seçimi değil, sample tasarımı belirleyicidir.

---

## Data Structure Innovations

López'in en orijinal katkılarından biri, ML için kullanılan girdi serilerinin nasıl oluşturulduğuna dair klasik varsayımı kırmasıdır. Standart finansal seriler "1 dakikalık bar", "günlük bar" gibi *time-based* sampling kullanır; López bunun ML açısından üç problemi olduğunu söyler:

1. **Bilgi geliş hızı düzensizdir.** Avrupa açılışı + ABD açılışı arasındaki saatte 1 dakikalık bar olağanüstü bilgi yoğun, gece yarısı boş.
2. **Returns IID değildir.** Time bars'ın return dağılımı kalın kuyruklu ve heteroskedastiktir; bu da ML'in düşman ortamıdır.
3. **Olay zamanı vs takvim zamanı farkı.** Piyasa "olay" bazlı çalışır; takvim bazlı sampling yapay yapısal kırılmalar üretir.

Çözüm olarak **information-driven bars** önerir.

### 2.1 Tick Bars

Her *N* tick'te bir bar kapatılır. Likidite arttıkça bar daha sık doğar; bilgi yoğunluğu eşitlenir. Avantaj: heteroscedasticity önemli ölçüde azalır. Dezavantaj: HFT spam'ı veya iceberg orderlar tick sayısını yapay şişirebilir.

### 2.2 Volume Bars

Her *V* lot işlem hacminde bir bar kapatılır. Tick bars'a göre HFT spam'ına dirençlidir. Volume bars'ın return distribution'ı time bars'dan **daha** *Gaussian*'a yakın çıkar — Mandelbrot-Clark'ın "subordinated process" teorisi ile uyumludur.

### 2.3 Dollar Bars

Her *D* dolar nominal hacimde bir bar kapatılır (price × volume). López'in *favorisidir.* Sebepler:

- Stock split, fiyat değişimi vb. structural breaklerden bağımsızdır.
- Volatilite arttıkça bar üretim hızı volume bar'a göre daha doğru ölçeklenir.
- Cross-asset karşılaştırma için en sağlıklı normalize edilmiş bar yapısıdır.

D* (eşik dolar miktarı) seçimi için López, hedef günlük bar sayısı (ör. 50–100 bar/gün) verip exponentially weighted moving average ile uyarlamalı eşik kullanmayı önerir.

### 2.4 Information-Driven Bars

Bar üretimini *bilgi akışı* ile tetiklemek için iki gelişmiş tip:

- **Imbalance Bars (TIB / VIB / DIB):** her tick'in işaretiyle (b_t ∈ {-1,+1}) imbalance birikimini izler. Eşik aşıldığında bar kapanır:

  θ_T = Σ_{t=1..T} b_t · v_t,  bar kapat: |θ_T| ≥ E_0[T]·|2P[b=1]−1|·E[v]

  Asymmetric order flow geldiğinde hızlı, dengeli akışta yavaş bar üretir. ML için ideal çünkü her bar "olay-yoğun".

- **Runs Bars:** ardışık aynı işaretli tick run'larını izler. Trend rejiminde hızlı, mean-reverting rejimde yavaş bar üretir.

ML pipeline'ında ham tick verisinden çıkarılacak ilk dönüşüm budur. Faz 0 önemindedir: yanlış bar = sonraki tüm istatistikler bozulur.

### 2.5 Fractional Differentiation

López'in *signature* kavramlarından. Klasik dilemma:

- Ham fiyat serisi non-stationary → ML modelleri patlar.
- Tek tam fark (return) stationary ama *memory*'yi yok eder → "trend" "regime" "mean-reversion" sinyalleri kaybolur.

Çözüm: kesirli (fractional) fark, d ∈ (0,1):

(1−L)^d X_t = Σ_{k=0..∞} ω_k · X_{t−k}

ağırlıklar:  ω_0 = 1,  ω_k = ω_{k−1} · −(d − k + 1)/k

d = 1: tüm hafıza silinir (return).
d = 0: hiçbir şey değişmez (raw price).
d ∈ (0,1): kısmi hafıza korunur **ve** seri stationary olabilir.

**d* seçim prosedürü (López):**

1. d ∈ {0.0, 0.1, 0.2, …, 1.0} ızgarasında dolaş.
2. Her d için Augmented Dickey-Fuller (ADF) testi uygula.
3. ADF p-değeri < 0.05 olan **en küçük** d'yi seç → minimum hafıza kaybı + stationarity.
4. Pratikte tipik çıkış: d* ≈ 0.3–0.5 (eşitsel, hisse), 0.4–0.6 (FX), 0.6–0.8 (vol-rejimli emtia).

Pencere kesme: |ω_k| < τ olduğunda kes (τ = 1e-4 yaygın). Bu, sabit-genişlikte *Fixed-Width Window Fractional Differentiation* (FFD) yaratır ve real-time pipeline'a uygundur.

---

## Labeling Methodology

ML modelinin öğrendiği şey *label*'dır. Klasik finansal ML "next bar return > 0?" ya da "next 5 bar return sign?" gibi *fixed-time-horizon* etiketler kullanır. López bunun yanlışlığını şöyle özetler:

> "Returns over fixed-time horizons are not what traders actually trade."

Trader, hedef ve stop ile pozisyon açar; pozisyon ya stop'a, ya hedefe, ya da zaman aşımına çıkar. Etiket de bu yapıyı yansıtmalıdır.

### 3.1 Triple-Barrier Labeling

Bar t'de bir trade hipotezi için üç bariyer tanımla:

- **Üst bariyer:** profit-take, fiyat düzeyi  +pt · σ_t
- **Alt bariyer:** stop-loss, fiyat düzeyi  −sl · σ_t
- **Dikey bariyer:** maksimum tutma süresi  T

İlk hangisine değerse etiket o:

- üst bariyer önce ↦ y = +1
- alt bariyer önce ↦ y = −1
- vertical önce ↦ y = sign(return) ya da 0 (parametrik)

σ_t için López **rolling exponentially weighted standard deviation of returns** önerir; barriers böylece volatiliteye göre normalleşir. Bu, label'ın rejim değişikliğine dayanıklı olmasını sağlar.

### 3.2 Trend-Scanning Labeling

MLAM'de tanıtılan alternatif: ML'e *yön* vermek yerine *eğilim varlığı* öğret. Her bar t için ileri pencere [t, t+L]'deki linear regression t-statistic'inin *maksimum mutlak değerine* sahip pencereyi bul:

L*(t) = argmax_L |t-stat(β_L)|

Etiket = sign(β_{L*}). Bu yöntemde label gürültüden temizlenmiş "anlamlı trend" işaretidir; trend olmayan bölgeler düşük |t-stat| ile filtrelenebilir.

### 3.3 Neden Fixed-Time-Horizon Yanlış

Sabit ufuklu return etiketi (ör. "next 10 bar return > 0?") şunu yapar: trade'in stop'a çoktan değdiği durumlarda bile pozitif label üretebilir. Bu *path-blind* etiket gerçek PnL ile uyumsuzdur. ML model oradan path-blind sinyaller üretir → backtestte stop tetiklenir, model iyi göründüğü halde para kaybeder.

### 3.4 Meta-Labeling

López'in en parlak fikirlerinden biri. İki aşamalı sistem:

- **Primary model:** yön sinyali üretir (long/short/flat). Bu basit bir teknik kural (ör. crossover, pin bar, breakout) olabilir.
- **Secondary (meta) model:** primary sinyalin **doğru** olup olmayacağını tahmin eder; output: trade etmemek (0) veya etmek (1) + position size.

Meta-model'in label'ı: primary sinyalin gerçekleştiği barlar üzerinde, triple-barrier sonucu kazanç=1 / kayıp=0. Yani meta-model bir *binary classifier of primary's correctness*.

Avantajlar:

- Primary'yi insan-anlaşılır tutar (whitebox); meta katmanı blackbox olabilir.
- Precision-recall trade-off'u meta katmanında kontrol edilir → false positive'leri kesip Sharpe'ı yükseltir.
- Position size meta-model'in P(correct) çıktısıyla doğrudan ayarlanır.

Bu yaklaşımın bizim sistemdeki karşılığı doğrudan **Faz 4 ML signal filter**'dır.

### 3.5 Sample Weights

Finansal etiketler örtüşür: bar t'nin label'ı [t, t+T]'deki return'e bağlıdır; bar t+1'in label'ı [t+1, t+T+1]'deki return'e bağlıdır → büyük örtüşme. ML model'inin bu örnekleri *bağımsız* sayması leakage'dir.

López iki ağırlık önerir:

- **Uniqueness weight (u_i):** label i'nin diğer labellarla örtüşmediği fraksiyon. c_t = bar t'yi içeren label sayısı; u_i = (1/(t1_i − t0_i)) · Σ_{t in [t0_i, t1_i]} 1/c_t.
- **Return-attribution weight (w_i):** label'ın büyüklüğü ile orantılı: w_i ∝ |Σ_t r_t / c_t| over [t0_i, t1_i]. Yani büyük PnL'li nadir olaylar daha çok ağırlık alır.

Final ağırlık: ŵ_i = u_i · w_i. Bu sklearn-style `sample_weight` argümanına geçilir; training'de tüm gradient/loss bu ağırlıklarla çarpılır.

---

## Backtest Overfitting Detection

López'in en sert eleştirisi şuna yönelik: araştırmacılar yüzlerce strateji dener, en iyisini raporlar, ama p-değerini *1-trial* gibi hesaplarlar. Bu **selection bias under multiple testing**. Çözümü iki tane formel araç:

### 4.1 Deflated Sharpe Ratio (DSR)

**Sezgi:** N strateji denendiyse, "en iyi" Sharpe'in dağılımı tek strateji Sharpe'ından daha yüksektir; bu yüzden raporlanan Sharpe'ı *deflate* etmeliyiz.

**Formül zinciri:**

1. **Probabilistic Sharpe Ratio (PSR):** gözlenen Sharpe SR_obs'un belirli bir benchmark SR* (genelde 0)'ı aştığına olan olasılık:

   PSR(SR*) = Φ( (SR_obs − SR*) · √(T−1) / √(1 − γ_3·SR_obs + ((γ_4 − 1)/4)·SR_obs²) )

   - T: gözlem sayısı (örnekler, bar değil; trade veya periyot)
   - γ_3: return skewness
   - γ_4: return kurtosis (excess + 3)
   - Φ: standart normal CDF

2. **Expected maximum Sharpe under N trials:**

   E[SR_max] ≈ √(Var[SR_n]) · ( (1−γ) · Φ⁻¹(1 − 1/N) + γ · Φ⁻¹(1 − 1/(N·e)) )

   - γ ≈ 0.5772 (Euler-Mascheroni)
   - Var[SR_n]: trial'lardaki Sharpe varyansı

3. **DSR = PSR(SR* = E[SR_max])**

   DSR = Φ( (SR_obs − E[SR_max]) · √(T−1) / √(1 − γ_3·SR_obs + ((γ_4 − 1)/4)·SR_obs²) )

   Kompakt form: **DSR = E[SR] / √(Var[SR_max])** sezgisi ile uyumludur — gözlenen Sharpe, çoklu deneme altında beklenen maksimumun standart sapmasına göre normalleştirilir.

**Yorum:**

- DSR < 0.5: strateji rastlantı.
- DSR ∈ [0.5, 0.6]: kararsız; daha çok veri.
- DSR ∈ [0.6, 0.95]: kabul edilebilir; canlı izleme.
- DSR > 0.95: güçlü istatistiksel kanıt.

Dikkat: DSR, "gerçek edge var" demek değil; "raporlanan Sharpe trial sayısına ve yüksek momentlere göre düzeltildikten sonra hâlâ sıfırdan büyük" demektir.

### 4.2 Probability of Backtest Overfitting (PBO)

**Sezgi:** N strateji içinden in-sample (IS) en iyi olanın out-of-sample (OOS) sıralaması nedir? Eğer overfitting yoksa IS-best, OOS'da da iyi olmalı.

**Combinatorial CV bazlı PBO algoritması:**

1. T uzunluğundaki return matrisini M tane disjoint blok'a böl.
2. M bloktan S tanesini IS, kalan M−S tanesini OOS olarak seç. C(M, S) kombinasyon var.
3. Her kombinasyon için:
   - IS verisinde N stratejinin Sharpe'ını hesapla, en iyi index n* bul.
   - Aynı n* OOS'da hangi sıraya geliyor?
   - Logit dönüşüm: λ_c = log(r̄ / (1 − r̄)), r̄ = OOS rank / (N+1).
4. **PBO = Pr(λ_c < 0)** — yani OOS'da bottom-half'a düşme olasılığı.

**Yorum:**

- PBO < 0.2: minimal overfit, güvenli.
- PBO ∈ [0.2, 0.5]: kabul edilebilir, ama dikkat.
- PBO > 0.5: strateji muhtemelen gürültü.

### 4.3 Minimum Backtest Length (MinBTL)

Bir strateji için *yeterli* tarihsel veri uzunluğu:

**MinBTL = (variance / target_sharpe)²** (López'in basitleştirilmiş kuralı)

Genişletilmiş form:

MinBTL ≈ ( (Z_{1−α})² · (1 − γ_3·SR + ((γ_4 − 1)/4)·SR²) ) / SR²

Pratik kuraltır:

- SR_target = 1, normal dağılım, tek trial → MinBTL ≈ 2 yıl.
- SR_target = 0.5, fat-tail (γ_4 = 6) → MinBTL ≈ 8–10 yıl.
- N = 100 trial → effective MinBTL × log(N), yani 4–5 yıl ek.

### 4.4 Ne Zaman Strateji Reddedilmeli (Sharpe ne olursa olsun)

- DSR < 0.5,
- PBO > 0.5,
- T < MinBTL,
- IS Sharpe > 3·OOS Sharpe,
- Strategy serbest parametre sayısı / örnek sayısı > 1/30,
- Walk-forward'da Sharpe varyansı ortalamadan büyük.

Bu altı kriterden bir tanesi kırmızıysa strateji production'a gitmemeli; "Sharpe = 2.1 var, deploy edelim" yaklaşımının bilimsel temeli yoktur.

---

## Cross-Validation for Time Series

Standart *k-fold CV* finansal veride yanlıştır çünkü:

1. **Shuffling:** zaman sırası bozulur → gelecekten geçmişe bilgi sızar.
2. **Overlapping labels:** train ve test örneği aynı geleceği paylaşır.
3. **No stationarity:** rejim değişikliği train/test ayrımına yansıtılmaz.

López üç kademe çözüm sunar.

### 5.1 Walk-Forward (Anchored / Rolling)

- **Anchored:** train başlangıcı sabit, test sürekli ileri kayar.
- **Rolling:** train penceresi sabit uzunluk, ileri kayar.
- Üretim ortamına en yakın validation'dır ama tek yol = az örnek = yüksek varyans.

### 5.2 Purged k-Fold CV

- Train ve test foldları arasında *purge* uygula: test fold'una dokunan label'ları (label aralığı [t0,t1] test'le örtüşenleri) train'den çıkar.
- *Embargo* periyodu ekle: test fold sonrasında belirli bir süre (López önerisi: **test periyodunun %1–%5'i**) veriyi train'e dahil etme. Bu, serial correlation'ın leakage yaratmasını önler.

Embargo formülü:

embargo_h = ⌈ p · T_test ⌉,  p ∈ [0.01, 0.05]  (varsayılan p = 0.05)

### 5.3 Combinatorial Purged Cross-Validation (CPCV)

López'in *en güçlü* validation aracı. Klasik k-fold sadece k tane train/test split üretir. CPCV C(N, k) split üretir:

1. Veri N gruba bölünür.
2. Her seferinde k grup test, kalan N−k grup train.
3. C(N, k) kombinasyon → C(N, k)·k/N tane bağımsız backtest path.
4. Her split için purge + embargo uygulanır.

Örnek: N=10, k=2 → C(10,2)=45 kombinasyon, 9 path. 45 farklı performans noktasıyla DSR ve PBO doğrudan hesaplanır.

**Avantaj:** tek bir walk-forward'in varyansını çok küçültür; PBO'yu hesaplamak için doğal altyapı sağlar.

**Dezavantaj:** computasyonel maliyet C(N,k)·model_fit_time. Ama gradient boosting bazlı modeller için tractable.

### 5.4 Embargo Pratik

- Yüksek frekanslı stratejide embargo 0.5–1 saat yeterli.
- Daily stratejide embargo 5–10 işlem günü.
- Triple-barrier label'da embargo ≥ vertical bariyer süresi olmalı; aksi halde label leakage kesin.

---

## Feature Engineering & Selection

ML başarısı feature'lara bağlıdır; finansta feature kümesi sıklıkla yüksek collinearity ve düşük signal-to-noise içerir. López dört aracı vurgular.

### 6.1 Mean Decrease Impurity (MDI)

Tree-based modellerde her feature'ın splitlerde sağladığı impurity azalmasının normalize edilmiş ortalaması:

MDI(X_j) = (1 / N_trees) · Σ_t Σ_{n: split var = j} p(n) · ΔI(n)

- p(n): node n'e düşen örnek oranı.
- ΔI(n): Gini ya da entropy azalması.

**Pitfall:** correlate edilmiş feature'lar arasında MDI rastgele dağılır; "X_1 ve X_2 hemen aynı" ise MDI ikisini de düşük gösterebilir. Bu yüzden *clustered MDI* kullanılır.

### 6.2 Mean Decrease Accuracy (MDA)

Out-of-sample yaklaşım: feature j'nin değerlerini permüte et, modelin OOS skoru ne kadar düşüyor?

MDA(X_j) = E_OOS[score(model)] − E_OOS[score(model | X_j permuted)]

**Avantaj:** model-agnostic, OOS-bazlı, leakage'i yansıtır.
**Pitfall:** correlate edilmiş feature'larda permuted bir feature'ın bilgisi diğerinden geliyor olabilir → MDA underestimates.

### 6.3 Single Feature Importance (SFI)

Her feature'ı *tek başına* kullanan model fit et, OOS skoru kaydet. Rank sırasını verir; correlation problemi yok ama interaction kaybı var.

### 6.4 Clustered MDI / MDA

López'in MLAM'deki çözümü:

1. Feature korelasyon matrisini distance metriğine çevir: d_ij = √(0.5 · (1 − ρ_ij)).
2. Hierarchical clustering uygula (Ward linkage tipik).
3. Cluster sayısını ONC (Optimal Number of Clusters) algoritması ile seç.
4. Her cluster için *cluster-MDI* hesapla: cluster üyelerinin toplam MDI'i.

Bu, "iki collinear feature'in importance'ı yarıya bölündü" hatasını önler. Bizim PA feature'larında (ATR, range, body, body/range) bu adım kritik çünkü çok korelasyon var.

### 6.5 Pratik Pipeline

1. Ham feature → frac-diff stationarize.
2. Feature kümesini hierarchical cluster yap.
3. Her cluster'dan en yüksek SFI'lı bir feature seç (compression).
4. Geri kalan feature'larla MDA çalıştır → düşük MDA'lıları at.
5. Final model'i CPCV ile valide et.

---

## Setup Kataloğu (Konsept Seviyesi)

López, klasik bir "şu kalıpta gir, şu kalıpta çık" tarayıcısı sunmaz; onun setupları metodolojiyi yansıtır. Aşağıdaki altı meta-strateji bizim sistemde *uyarlanabilir blueprint*'tir. Her biri için 7 blok: tetikleme, giriş, stop, hedef, bet sizing, exit, edge condition.

### 7.1 Triple-Barrier Sized Trade

- **Tetikleme:** primary signal (rule-based, ör. EMA crossover, breakout).
- **Giriş:** sinyal barının kapanışı.
- **Stop:** −sl · σ_t altında (sl = 1.0–2.0).
- **Hedef:** +pt · σ_t üstünde (pt = sl × R, R = 1.0–3.0).
- **Bet sizing:** meta-model P(correct) çıktısı sigmoid mapping'le pozisyon büyüklüğüne çevrilir.
- **Exit:** üst bariyer / alt bariyer / dikey bariyer (T = 5–20 bar) hangisi önce.
- **Edge condition:** OOS triple-barrier hit oranı > 0.55 + DSR > 0.6.

### 7.2 Trend-Scanning Labeled Trades

- **Tetikleme:** trend-scanning |t-stat| > 4 olan bar.
- **Giriş:** label sign yönünde, bar kapanışında.
- **Stop:** L* bar boyunca regression residual'ın 2σ'sı.
- **Hedef:** L*-bar projection × 0.7 (kısmi mean reversion).
- **Bet sizing:** |t-stat| ile orantılı (cap at 3σ).
- **Exit:** L* dolduğunda, ya da residual rejected olduğunda.
- **Edge condition:** filtered hit > 0.6, PBO < 0.3.

### 7.3 Frac-Diff Momentum Signal

- **Tetikleme:** d* ≈ 0.4 ile frac-diff serisi ADF stationary; serinin EMA z-score > 1.5 (long) / < −1.5 (short).
- **Giriş:** sinyal yönünde, gelecek bar açılışı.
- **Stop:** ATR(14) × 1.5 zıt yönde.
- **Hedef:** ATR(14) × 3.0 lehte.
- **Bet sizing:** |z-score| × base_size, cap'lı.
- **Exit:** z-score sıfırı geçer, ya da hedef/stop.
- **Edge condition:** hafıza korunmuş seri varyans > raw return varyansı × 1.2 (bilgi koruma testi).

### 7.4 Meta-Label Filter on Existing PA Signals

(Bizim sistemimize en doğrudan uyan setup.)

- **Tetikleme:** mevcut PA sinyali (ör. pin bar, bullish engulfing, support break-retest).
- **Giriş:** sinyal koşulu + meta-model P(win) > eşik (0.55–0.65).
- **Stop:** PA'nın doğal stop'u (pin bar low – 1 ATR vs.).
- **Hedef:** PA'nın doğal hedefi (1R, 2R, swing high).
- **Bet sizing:** P(win) − 0.5 ölçeklenmiş; calibration eğrisi izlenmeli.
- **Exit:** standart PA exit + opsiyonel meta-model P(win) < 0.4 olduğunda erken kapatma.
- **Edge condition:** meta-model precision OOS > 0.6, DSR > 0.6 üstüne baseline > +0.5 SR yükseltmeli.

### 7.5 Purged-CPCV Validated Mean Reversion

- **Tetikleme:** rolling Bollinger %B < 0.05 (oversold) + frac-diff < −2σ.
- **Giriş:** sinyal sonrası ilk yeşil bar kapanışı.
- **Stop:** son swing low altında.
- **Hedef:** mean (SMA20) reversion.
- **Bet sizing:** Kelly-cap'lı (max ¼ Kelly).
- **Exit:** mean'a değme ya da 10 bar timeout.
- **Edge condition:** CPCV ortalama Sharpe > 1.0, std < 0.5; PBO < 0.2.

### 7.6 Information-Driven Bar Breakout

- **Tetikleme:** dollar-imbalance bar büyük asimetri ile kapanır (|θ_T| > 2·E_0[θ]).
- **Giriş:** breakout barının kapanışı.
- **Stop:** breakout barının orta noktası.
- **Hedef:** bar range × 2.
- **Bet sizing:** imbalance büyüklüğü ile orantılı.
- **Exit:** range tamamlanır ya da iki imbalance bar ters kapanır.
- **Edge condition:** time-bar baseline'dan +0.4 SR fark, PBO < 0.3.

---

## Bet Sizing & Optimal Leverage

López, ML modelinin output'unu binary sinyal yerine *probabilistic forecast* olarak kullanır ve bunu pozisyon büyüklüğüne çevirir.

### 8.1 Signal-Based Bet Size

Probability p ∈ [0,1] çıktısı için:

z = (p − 0.5) / √(p · (1 − p))

m = 2 · Φ(z) − 1   ∈ [−1, +1]

m, hedef *bet size* (-1 = full short, +1 = full long, 0 = flat). Bu sigmoid-benzeri eşleme tutarsız olasılıkları ezer, kalibre edilmiş olasılıkları ödüllendirir.

### 8.2 Concurrent-Bet Aware Sizing

Eş zamanlı *N* aktif trade varsa her trade'in büyüklüğü 1/N'ye orantılı kısılır; capital allocation matrisi şöyle:

w_i = m_i / Σ_j |m_j|

Bu, açık pozisyonların volatiliteye katkısı sınırını korur. *Discretization* katmanı: çok küçük w_i'leri 0'a yuvarla (turnover azaltır).

### 8.3 Drawdown-Controlled Leverage

Hedef Sharpe × hedef volatilite = annualized return target:

L* = vol_target / vol_strategy

López ek olarak **dynamic deleveraging** önerir: rolling drawdown D_t, max kabul edilebilir drawdown DD_max'a yaklaştığında:

L_t = L* · (1 − D_t / DD_max)^α,  α ≈ 1–2

Bu, "kayıp halinde küçül" davranışını otomatize eder ve real-money path'lerinde fonun ölmesini önler.

### 8.4 Kelly Cap

Tam Kelly volatilite ekstrem; López ¼–½ Kelly cap önerir. Meta-label P(win) verildiğinde:

f* = (P(win) · b − P(loss)) / b,  b = avg_win/avg_loss

f_cap = min(f*, 0.25)

---

## Sequential Bootstrap

Bootstrap, ML'de güven aralıkları ve ensemble (random forest) için temel araçtır. Standart bootstrap **uniform sampling with replacement**'tır → IID varsayar. Finansta label'lar örtüşür → naive bootstrap aşırı duplicate üretir.

López'in çözümü **Sequential Bootstrap**:

1. Her örneğin uniqueness'ı u_i = (1/(t1_i − t0_i))·Σ_t 1/c_t hesaplanır.
2. İlk örnek uniform seçilir.
3. Her sonraki seçimde, daha önce seçilmemiş ya da örtüşmesi düşük örneklerin ağırlıkları yükselir.
4. Sonuç: bootstrap örnek setinde *ortalama uniqueness* maksimize edilir.

Pseudocode:

```
def sequential_bootstrap(indM, sLength):
    phi = []
    while len(phi) < sLength:
        avgU = pd.Series(0.0, index=indM.columns)
        for i in indM:
            avgU.loc[i] = uniqueness_if_added(indM, phi, i)
        prob = avgU / avgU.sum()
        phi.append(np.random.choice(indM.columns, p=prob))
    return phi
```

Etki: random forest gibi bagging tabanlı modellerin diversity'si artar; effective sample size leak'i kapanır. Bu adım **uniqueness weighting + sequential bootstrap** olarak çift şekilde uygulanır.

**Pratik gözlem:** Naive bootstrap'la kurulmuş bir random forest, finansal veride tipik olarak *out-of-bag* skoru gerçek OOS skorundan çok daha iyimser raporlar; çünkü bootstrap setleri arası örtüşme yüksektir, OOB her ağaç için "yarı-IS" olur. Sequential bootstrap bu sapmayı belirgin şekilde azaltır; OOB ile gerçek OOS arasındaki uyum genelde 2–3 kat iyileşir. Bu, model güveni metriklerinin (feature importance, OOB error, calibration) güvenilirliğini doğrudan artırır.

Ek olarak López, *ortalama uniqueness*'ı bağımsız bir *data quality* metriği olarak izlemeyi tavsiye eder: ū = (Σ u_i)/N. ū < 0.3 ise bar/label seçimi fazla örtüşmeli, label horizon T çok uzun veya bar frekansı çok yüksek demektir; pipeline parametreleri (T düşür, bar büyüt) ayarlanmalıdır. ū > 0.7 ideal — örnekler yaklaşık IID gibi davranır.

---

## Statistical / Quantifiable Edge Conditions

Strateji canlıya gitmeden önce karşılaması gereken sayısal eşikler:

| Metrik | Minimum kabul | Güçlü |
|---|---|---|
| DSR | 0.6 | > 0.95 |
| PBO | < 0.5 | < 0.2 |
| OOS Sharpe / IS Sharpe | > 0.5 | > 0.7 |
| CPCV Sharpe std | < 0.5 × mean | < 0.3 × mean |
| Sample uniqueness (mean) | > 0.5 | > 0.7 |
| Meta-label precision (OOS) | > 0.55 | > 0.65 |
| MinBTL coverage | T_avail > MinBTL | T_avail > 2·MinBTL |
| Frac-diff information loss | corr(frac, raw) > 0.6 | > 0.85 |

**MinBTL kuralı (özet):**

MinBTL = (variance / target_sharpe)²

Genişletilmiş yıllık form:

MinBTL_yıl ≈ (1 / SR_target²) · (1 − γ_3·SR + ((γ_4−1)/4)·SR²) / 252

Pratik:

- SR=1, normal: ~0.5 yıl bar bazlı, 2 yıl trade bazlı.
- SR=0.5, fat tail: ~8 yıl trade bazlı.
- N=100 trial → bu sürelerin × log(100) ≈ ×4.6 ölçeklenmesi.

**Bilgi sıkıştırma kayıp tahmini:** bar compression ratio C = (eski bar sayısı / yeni bar sayısı). Beklenen information loss:

I_loss ≈ 1 − ρ²(returns_eski, returns_aggregated)

C × ρ² ≈ 1 olmalı; aksi halde anlamlı bilgi kaybediliyordur.

---

## Yaygın Hatalar / Pitfalls

López'in kitabı, başlıca yedi metodolojik hatayı sürekli vurgular:

1. **Selection bias in published Sharpe:** "100 strateji denedik, en iyisi şu" → DSR olmadan rapor edilen Sharpe yanıltıcıdır. Çözüm: trial sayısını açıklayan deflation.
2. **Multiple testing without correction:** Bonferroni, Benjamini-Hochberg, ya da DSR uygulanmadan p-değerleri yarı-değersizdir.
3. **Label leakage in time series:** train/test ayrımı zamanı keser ama label aralığı zaman çizgisini aşar → embargo yoksa leakage. Çözüm: purging + embargo (test periyodunun %5'i kuralı).
4. **Training on too few unique samples:** 10 yıl saatlik veri = 60k bar ama overlapping triple-barrier label uniqueness ortalaması 0.2 → effective sample = 12k. Sklearn'in `n_samples` numarası model güveni için yanıltıcıdır.
5. **Ignoring sample weights:** uniqueness × return-attribution ağırlıkları olmadan model yüksek-örtüşmeli olayları ezberler. *Always pass sample_weight.*
6. **Fixed-time-horizon labeling:** path-blind etiket; trade'in stop'a değdiğini görmez. Çözüm: triple-barrier ya da trend-scanning.
7. **Standard k-fold CV:** zaman serisinde anlamsız; CPCV ya da purged walk-forward kullanılmalı.
8. **Time bars in non-stationary regime:** information-driven bar (dollar imbalance) olmadan ML feature'ları rejim drifti ile kayar.
9. **Backtest leverage / position sizing miscalibration:** Sharpe abartılır çünkü sizing post-hoc tunning'le güzelleştirilmiştir; bet sizing pipeline'ın bir parçası olmalı, sonradan eklenen vernik değil.
10. **Insufficient MinBTL:** 1 yıllık veriyle SR=2 demek matematiksel olarak çoğunlukla rastlantıdır.

---

## Cross-references

**López ↔ Chan:** Ernie Chan (*Algorithmic Trading*, *Quantitative Trading*) pratik mean reversion ve momentum stratejilerinde derin; López ondan istatistik olarak çok daha titizdir. Chan'ın "Sharpe > 1 olunca canlıya geçer" sezgisini López DSR ile bilimselleştirir. Chan'ın stratejilerini López filtresinden geçirmek standart bir yükseltme yoludur.

**López ↔ Kaufman:** Perry Kaufman (*Trading Systems and Methods*) rule-based, geniş gözlem tabanlı, ML-öncesi bir çerçevedir; López ML-first ve istatistik-first. İkisi rakip değil tamamlayıcıdır: Kaufman primary signal kütüphanesini sağlar (yüzlerce klasik kural); López bunlara meta-label katmanı ekler.

**López ↔ Brooks:** Al Brooks (*Reading Price Action Trends*) tamamen discretionary, "trader hisseder" geleneğindendir; López bu tarzı kuşkuyla karşılar — discretionary edge'in DSR'ı genellikle düşük çıkar çünkü trial sayısı belirsiz ve sample bias büyük. Yine de Brooks'un setup taksonomisi (pin bar, breakout retrace, double top) López'in primary model'i olarak kullanılabilir; *meta-label* katmanı discretionary edge'i quantize eder.

**López ↔ Lo / Pedersen / Grinold-Kahn:** Andrew Lo'nun adaptive markets ve Pedersen'in efficiently inefficient çerçevesi rejim değişikliği ve risk premia tarafında akademik temel sağlar; Grinold-Kahn'ın *Active Portfolio Management* IR tabanlı düşüncesi López'in bet sizing katmanıyla uyumludur. López, bu klasiklerin pratik / mikroyapı / ML köprüsüdür.

**López ↔ Tsay / Hamilton:** Time series ekonometrisi (Tsay, Hamilton) frac-diff ve ADF testlerinin temelini sağlar; López, ekonometri araçlarını ML pipeline'ına taşıyandır.

---

## Bizim Sistemle Bağlantı

Bizim Price Action sisteminde López'in metodolojisi doğrudan dört yere bağlanır:

### Faz 4: ML Signal Filter ↔ Meta-Labeling

Bizim **Faz 4** olarak konumlandırdığımız "ML signal filter" tam olarak López'in *meta-labeling* önerisidir. Pipeline:

1. **Faz 1–3:** rule-based PA detektörü (pin bar, engulfing, break-retest, support/resistance) primary sinyal üretir.
2. **Faz 4:** her primary sinyalin geçmiş trade sonuçlarına (triple-barrier ile etiketlenmiş) meta-model fit edilir.
3. Real-time: primary tetiklenir → meta-model P(win) > eşik ise giriş; aksi halde skip.
4. Position size: P(win)'in sigmoid mapping'i.

Bu mimari, raw rule-based sistem üzerine ekstra istatistiksel filtre koyar; tipik beklenti: hit oranı 0.45'ten 0.55–0.62'ye, trade sayısı yarıya ama Sharpe 0.4–0.6 yükselir.

### Faz 2 Gate'i: DSR & PBO Standardizasyonu

Faz 2 (strateji backtest gate'i) için **DSR ≥ 0.6 ve PBO ≤ 0.3** zorunlu kabul kriteri olmalı. Sharpe veya hit oranı kabul kriteri olarak yetersiz; her backtest raporu şu üçlüyü taşımalı: SR_obs, DSR, PBO, MinBTL coverage. Pipeline output'u olarak `metrics.json` içinde standardize edilmeli:

```json
{
  "sharpe": 1.42,
  "dsr": 0.71,
  "pbo": 0.18,
  "minbtl_years": 3.4,
  "data_years": 8.0,
  "trial_count": 45,
  "uniqueness_mean": 0.61
}
```

Bu metriklerden biri kırmızıysa strateji prod'a açılmaz.

### Backtest Engine'in Label Producer'ı: Triple-Barrier

Mevcut backtest motorumuz fixed-time-horizon return label'ı kullanıyorsa, bunu **triple-barrier label producer**'a çevirmek bir mimari refactor'dir. Faydaları:

- Stop'un model değerlendirmesinde düzgün yansıması.
- Volatilite-normalize edilmiş etiket → cross-symbol portability.
- Meta-label katmanına doğal arayüz.

Implementasyon: `label_producer.py` modülü, σ_t (EWMA std), pt (profit factor), sl (stop factor), T (vertical bariyer) parametreleriyle her trade hipotezi için (label, t1) üretir.

### CPCV Walk-Forward Yükseltmesi

Faz 2'deki walk-forward'ı **CPCV** ile değiştirmek tek başına en yüksek kalite kazancını veren değişiklik olabilir:

- Tek walk-forward: 1 backtest path, yüksek varyans.
- CPCV (N=10, k=2): 9 path, 45 split → DSR ve PBO doğal hesaplanır, PBO için ekstra altyapı gerekmez.
- Computation: walk-forward'a göre × 5–10 kat, ama parallelize edilebilir.

CPCV ek olarak hyperparameter tuning'i de dürüstleştirir: tuning her split'te tekrar yapılır, leakage yok.

### Frac-Diff Feature Hattı

Bizim ATR, range, body, range/ATR gibi feature'larımız genelde return-bazlı (stationary ama hafızasız). Frac-diff hattı eklemek:

- Her sembol için d* otomatik bul (ADF + grid).
- Frac-diff fiyat serisi → "memory-preserving" feature olarak ML pipeline'ına ekle.
- Beklenti: regime/trend duyarlı feature'lar; meta-label modelinin precision'ını yükseltir.

### Sample Weight Standartı

ML training pipeline'ımızda her örneğe `weight = uniqueness × |return_attribution|` ataması zorunlu olmalı; sklearn `sample_weight` argümanı; PyTorch ise loss çarpanı. Bu küçük değişikliğin sebep olduğu Sharpe düzelmesi tipik olarak +0.2–0.4 SR.

### Information-Driven Bar Opsiyonu

Yüksek frekanslı stratejilerimiz için (1m, 5m) **dollar imbalance bar** alternatifi düşünülmeli. Time bar'a göre bilgi-yoğun bar yapısı, ML feature'larının signal-to-noise oranını yükseltir; backtest path'inin kalbidir.

### Yol Haritası (Özet)

| Sıra | Aksiyon | Modül | Beklenen Etki |
|---|---|---|---|
| 1 | Triple-barrier label producer | `core/labels.py` | Doğru etiket → tüm ML kalitesi |
| 2 | Sample weights (uniqueness + attribution) | `core/sample_weights.py` | +0.2–0.4 SR |
| 3 | DSR + PBO standardizasyonu Faz 2 gate'inde | `validation/metrics.py` | Selection bias kontrol |
| 4 | CPCV walk-forward yerine | `validation/cpcv.py` | PBO doğal hesap, varyans düşer |
| 5 | Meta-label katmanı (Faz 4) | `models/meta_label.py` | Precision boost, hit rate ↑ |
| 6 | Frac-diff feature hattı | `features/fracdiff.py` | Memory-preserving feature'lar |
| 7 | Information-driven bar pipeline (opsiyonel) | `data/bars.py` | HFT stratejileri için |

Bu sıralama, en yüksek leverage'lı (low effort × high impact) değişikliklerden başlayıp sistemin metodolojik kökünü López standardına çıkarır. Sonuç olarak: López bizim için "model nasıl seçilir" değil, "deneyin tasarımı nasıl bilimsel hale getirilir" sorusunun standart cevabıdır; sistem bu standarda uydurulduğunda raporlanan istatistiklerin canlı performansa dönüşme oranı dramatik biçimde yükselir.
