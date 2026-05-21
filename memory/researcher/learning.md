---
agent: researcher
type: learning
created: 2026-05-08
---

# Researcher Learning

## Format

```
### YYYY-MM-DD — <slug>
- **Hipotez:** ...
- **Sonuç:** terfi / red / belirsiz
- **Ne öğrendim:** ...
- **Hangi bias'a düştüm:** confirmation / narrative / recency / ...
- **Bir dahaki sefer:** ...
```

---

### 2026-05-08 — Boot
- Ders defterinin başlangıcı. İlk hipotezden itibaren doldurulacak.

---

### 2026-05-13 — EER-Score v1 RED (ama yan-bulgu önemli)

- **Hipotez:** 180-gün rolling 6-dim bucket avg_R percentile (EER), CONF tier sizing'e karşı OOS Sharpe %20+ uplift verir.
- **Sonuç:** RED (3/5 pre-registered gate FAIL).
  - Bucket coverage %0 (sample_min=30 ile hiç bucket dolmuyor).
  - Shuffle null 0/6 pencerede p<0.05 (etiket permutation Sharpe'i değiştirmedi).
  - Top-vs-bottom Welch t-test imkânsız (top/bottom tier boş).
- **Ne öğrendim:**
  1. 6-dim bucket key (1772 unique bucket / 4787 trade = 2.7 trade/bucket avg) **fazla geniş**. Karşı-hipotez 1 (bucket clustering bias) **pre-registered olarak yazılmıştı ve doğrulandı**. Önemli: karşı-hipotezi yazmasaydım sonucu "edge bulundu" diye yutardım çünkü Mean ΔSharpe +0.26 PASS gibi görünüyor.
  2. **Paradox bulgu (KRİTİK):** EER fallback davranışı (tüm trade T2'de %2 risk + 2x lev) CONF-based sizing'i (T4'te %78 sinyal, %4 risk + 3x lev) +0.26 Sharpe uplift verdi. Bu EER mekaniğinin edge'i değil — **CONF'un bozuk olması ortaya çıktı** (DYNAMIC v0.9.8 felaketi yeniden gözlendi). Yan-aday: "flat T2 sizing" baseline as Lab W3 tournament challenger.
  3. Pre-registration disiplini Phase 1'i kurtardı — eğer karşı-hipotez yazmasaydım "Sharpe uplift +0.26 = PASS" rapor edip Lab'e gönderirdim, oradan tournament zaman/efor kaybı.
- **Hangi bias'a düşmedim:** Confirmation bias riski yüksekti — pozitif Mean ΔSharpe gözlemlemek mıknatıs gibi. Karşı-hipotez 1 önceden yazılmıştı, sonuç ona bakınca düştü.
- **Hangi bias'a düştüm:** **Combinatorial naivety** — 10 strat × 11 sym × 3 × 3 × 3 × 5 = 14850 bucket olabileceğini hesapladım ama pratikte 4787 trade'i dağıttığında bucket başına ortalama 2.7 düşeceğini hesabıma katmadım. Sample size matematiğini sadece n>=30 düzeyinde aldım, kombinatorik dağılımı değil.
- **Bir dahaki sefer:**
  - Pre-registration'a "expected n_trades_per_bucket" hesap koy: 4787/14850 = 0.32 (zaten %1 olabilirdi). Mathematicaly impossible'ı önceden gör.
  - Hierarchical bucket fallback: spesifik bos → parent (strategy+symbol+regime) → grand mean.
  - Bayesian shrinkage: avg_R = (n_bucket * avg_bucket + sample_min * grand_mean) / (n_bucket + sample_min). Smooth transition fallback'tan tahmine.
  - Bucket dimensionality 4'ten fazlaya çıkmamalı (3-4 olmalı).

### 2026-05-13 — 3 ikincil hipotez quick backtest (single 3y window)

- **HYP-1 funding-oi-divergence:** FAIL. n=4 trade. Sebep: OI verisi yok, funding-only proxy yetersiz triple-confluence vermiyor. **Ders:** Data Engineer'a "OI fetch" işemri verilmesi gerekiyor; bu hipotez backtest edilemez.
- **HYP-2 compression-breakout-nr7:** FAIL. n=67 trade, WR %38.8, avg_R +0.06, Sharpe 0.24 (gate >0.5). **Ders:** Crabel'in S&P futures'taki edge'i (WR %58, avg_R 1.4) 1d crypto'ya transfer edilmedi. Crypto volatilitesi compression-breakout için "yeterli sessizlik öncesi fırtına" mekaniğini yıkıyor — sürekli vol-clustering ile NR7 anlamını kaybediyor.
- **HYP-3 correlation-cluster-throttle:** PARTIAL. DD +33.9pp iyileşti ama return +%3145 → +%120 çakıldı (1797/2754 trade blocked, %65 skip rate). **Ders:** rho=0.70 + cluster_cap=2 fazla sıkı; cluster eşiği 0.80 veya cluster_cap=3 ile retest gerekli. Hipoteze göre skip_rate >%25 RED gate'i zaten ihlal edildi (%65).

### 2026-05-14 — Sec19 sprint: 3 yeni PA stratejisi (QM, HTF, IDF) hepsi RED

- **HYP-2026-05-14-QM (Quasimodo 5-pivot reversal):** **RED — fantasy R artifact.** Standalone'da mR +0.501 göründü ama median R -0.257, hold > 60d trade'lerde mR +1.647 (dataset-end clip), hold ≤ 15d trade'lerde mR -0.005 (gerçek edge yok). Honest clip (held>30d → R cap=1.0): mR +0.051, shuffle p=0.060. WF'da yıllık **-%172pp** kaybettiriyor (engine sermayeyi 1500+ gün bağlıyor). **Ders:** Engine `trail_activate_stage=2` default'u stage<2 trade'lerde force-exit'i devre dışı bırakıyor → uzun-hold loss trade'leri dataset-end clip ile fantasy R üretiyor. **SEC11a postmortem 2. defa üretildi** — bu engine limitation dokümante edilmeli, "long-hold strategy" tasarımı için engine seviyesi düzeltme gerek.
- **HYP-2026-05-14-HTF (High-Tight Flag, O'Neil/Bulkowski):** **RED — n=35 yetersiz.** Bulkowski rank #1 chart pattern claim'i crypto 5y × 11 sym'de replike olmadı: sadece 35 trigger, mR +0.083 (gate altı), shuffle p=0.40 (null'dan farkı yok). **Ders:** Crypto'da O'Neil 100% pole eşiği çok seyrek; 60% gevşek eşik bile yetersiz n üretiyor. Pattern doğru olsa bile istatistiksel anlamlılığa yetecek örneklem yok. Backlog: pole_return_min 0.40 ile retest + alt-coin only universe.
- **HYP-2026-05-14-IDF (Inside Day Failure, Tom Dante):** **RED-MARGINAL** (V1 standalone HARD fail, V3 PASS ama ensemble MARGINAL). V1 base (body≥0.30): n=481, mR +0.088 (gate 0.10 altı), shuffle p=0.080. V3 (body≥0.50): n=207, mR +0.240, p=0.060 — **standalone PASS** ama WF +IDF V3 ensemble katkısı sadece +0.3pp / +0.008 r-adj (production gate +0.05 altı). **Ders:**
  1. Trend filter eklemek IDF'yi BOZUYOR (V2 mR -0.033, V4 +0.045) — failure pattern'ler doğal "trend dışı". Adam Grimes orijinal hipoteziyle uyumlu.
  2. Body ratio güçlü filtre (0.30→0.50): mR 0.088→0.240 (+2.7x). Rejection candle kalitesi gerçek edge'in kaynağı.
  3. Slot bottleneck onayı (5. defa): standalone edge'in PASS olması ensemble'da +%2pp katkıya çevrilemiyor. Sec4/sec15.2/EER/ML/sec19 hepsi aynı yapısal sonuç.
- **Hangi bias'a düşmedim:** Pre-registered HARD/SOFT gate'leri sprintten önce yazıldı; QM mR +0.501 görünce "winner!" demek yerine doğrudan audit yaptım (hold time histogram). Honest clip ile fantasy R'ı yakaladım. **Pre-registration + paranoid audit ikilisi sprintteki en değerli savunma.**
- **Hangi bias'a düştüm:** QM standalone'da BacktestEngine default'larıyla geliyor — `trail_activate_stage=2` artifaktını sec11a'da gördüm, sec19'da TEKRAR yakaladım. **Engineering note alma alışkanlığı yok**: önceki sprint postmortem'ini hipotez yazarken kontrol etmeli, engine sınırlamasını üstlere belirtmeliyim. Aksi halde her sprint aynı artifact'a takılıyoruz.
- **Bir dahaki sefer:**
  1. Yeni strateji eklerken **standalone metric audit ZORUNLU**: median R, hold time histogram, R distribution percentile, "tail event check". Mean R'a kanma.
  2. Pre-reg gate'lere "honest mR (held>30d clip)" ekle — engine artifact'ından bağımsız metric.
  3. Slot bottleneck için "ensemble katkı eşiği" pre-reg'e yaz: standalone PASS bile olsa ensemble delta_yillik > +%2pp ya da delta_r-adj > +0.05 gate'i mandatory.
  4. Engine `trail_activate_stage=1` ile retest sprint için **Engineering ticket** aç — bu engine semantic değişikliği prod scope dışı ama R&D scope için stage=1 variant kullan.

### 2026-05-14 — SEC24 Turtle Soup 20D Failed BO Fade RED + PA Mastery Gap analizi

- **HYP-2026-05-14-TURTLE-SOUP-V2 (Raschke/Connors "Street Smarts" 1996):** **HARD RED.**
  Standalone n=475, mR=+0.026, WR=46.5%, p_shuffle=0.318. 3/7 hard gate FAIL (mR,
  p, symout dev=%79.5 ETH+BNB konsantre). 18-config parametre grid sweep (lookback ×
  body_min × atr_min) Bonferroni alpha=0.05/18=0.00278: **0/18 PASS**; en iyi
  config (lb=15/body=0.50) p=0.103 naive p<0.05 gate'in bile uzağında.
- **Yapısal bulgular:**
  1. **Orthogonality KANITLANDI:** donchian_breakout ile overlap=0 (jaccard=0.000),
     failed_bo_bos ve equal_highs ile jaccard < 0.05 — Turtle Soup yapısal olarak
     donchian sinyalinin tam tersi gün tetikleniyor. Pre-reg "yapısal inverse"
     hipotezi doğrulandı AMA edge yok. **"Orthogonal but no edge" = retire için
     temiz argüman, ileri çalışma için ortagonal benchmark olarak değerli.**
  2. **Regime split:** bear/range yıllar (2022/2023/2025) mR pozitif (+0.05 ile
     +0.27), bull yıllar (2021/2024/2026) mR negatif (-0.0 ile -0.36). Crypto bull
     regime'inde failed-BO candle = GERÇEK continuation (fade kaybeder). Regime-
     conditional variant backlog.
  3. **Asymmetric edge YOK** (pre-reg counter-hyp 4 RED): short-only n=275 mR=+0.074
     p=0.170 — gate altı + p uzak. Production tek-yön variant adaylığı reddedildi.
- **Hangi bias'a düştüm:** **Literatür-kaynaklı autorite bias'ı.** Bayesian
  prior'da "klasik 30 yıl Raschke/Connors → PASS-CANDIDATE yüksek ihtimal"
  yazdım, sonuç HARD RED. Yapısal sebep: orijinal evren US equities/FX 1990s,
  crypto 24/7 + perp leverage cascade microstructure tamamen farklı.
  **Ders:** "stocks/FX'te çalıştı" iddiası crypto için max +%30 Bayesian prior
  weight'i hak ediyor; veri belirlesin. SEC22 BB extreme RED paraleli.
- **Hangi bias'a düşmedim:** Pre-registered Bonferroni alpha + symout CV gate
  ne kadar pozitif görünen "best config" (lb=15/body=0.50 mR=+0.131) görsem de
  RED verdirdi. Counter-hyp asymmetric edge sınandı ve reddedildi pre-reg
  disipliniyle. **SEC23 OOS paradigmasından gelen "selection bias bottom-half
  check" buraya da uygulandı** (best config grid'de PASS olsa bile OOS hold-out
  zorunlu olacaktı). Hiç PASS olmadığı için OOS gerek bile kalmadı.
- **Yan-bulgu:** Effective dimensionality measurement — atr_min ∈ {0.005, 0.010}
  identical sonuç verdi (zaten 0.5% gate alt). Effective 9 unique config; Bonf
  alpha=0.05/9=0.0056. Yine 0 PASS. SEC23'te aynı yöntem RSI2 lb={3,5,7}
  identical sonuç tespit etmişti — aynı yapısal "fake dimensionality"
  hatırlatması.
- **Sprint ayrıca üretti:** (1) PA Mastery Gap raporu (56-setup envanteri
  kanonik PA otoritelerinden, mean-rev class'ta 7 NOT_TESTED + 2 PRE-REG
  kanonik aday belirlendi). (2) İki ek pre-reg hipotez yazıldı — Adam Grimes
  Failure Test ve Vol-z Spike Fade (backlog, sonraki sprintte test).
- **Bir dahaki sefer:**
  1. Literatür autorite bias'ı için Bayesian prior'da max +%30 weight ile cap
     uygula. Crypto-spesifik microstructure'da çalışmadığı kanıtlanmış pattern
     ailesi (BB 2.5σ extreme, RSI2, Turtle Soup) — bu 3'ü "stocks/FX
     mean-rev mekanik crypto'da CONTINUATION" yapısal grupta bir araya geliyor.
     Bu desen art arda 3. defa görüldü (sec22 BB, sec23 RSI2, sec24 TS) —
     pattern-class düzeyinde "crypto-uyumsuz mean-rev family" formal yan-bulgu.
  2. Yeni mean-rev hipotezler için pre-reg'e "crypto-microstructure-fit
     argument" zorunlu olsun (yapısal sebep + literatür sapması). Pure
     literatür replikası yetmiyor; crypto'ya neden uyacak hipotez yazılmalı.
  3. Engineering SEC21 slot allocation finalize edildiğinde mean-rev class
     slot'una standalone PASS-MARGINAL adaylar (IDF v3, vsa_climax_test,
     naked_poc_mr, microstructure_proxy) **mevcut FVG ile birlikte ensemble
     retest** — bu sprint scope dışı ama planlı.

### 2026-05-14 — SEC25 Track D Volume Microstructure 4/4 RED (1 v2 ADAY)

- **Hipotezler:** VSA SOS (D1, long trend cont), VSA SOW (D2, short trend cont),
  VSA Bag Holding (D3, long MR), Weis Wave Divergence (D4, both reversal).
- **Sonuç:** **4/4 HARD RED** pre-reg disiplini. HYP-D2 v2 ADAY işaretli.
- **Detay:**
  - D1: IS n=123 mR=+0.273 p=0.0195, OOS mR=-0.047 **sign flip** → RED
  - D2: IS 5/8 gate fail, OOS mR=+0.533 p=0.0015 (Bonferroni geçer post-hoc),
    AVAX hariç bile OOS robust (CI [+0.19, +0.82], 11/11 sym pozitif) →
    RED-pre-reg / v2 ADAY
  - D3: n=15 toplam (pattern crypto 1d'de yapısal olarak ender) → RED
  - D4: IS n=183 mR=+0.114 p=0.13, OOS mR=-0.046 sign-flip + sym-out 48% → RED
- **Ne öğrendim:**
  1. **RAG-first > web-first** — `knowledge/books/vsa_volume_spread_analysis.md`
     ve `volume_price_divergence.md` zaten 10 mekanik VSA pattern + 6 HYP taslağı
     içeriyor. WebSearch atlandı, token tasarrufu + reproducibility win-win.
  2. **Lokal optimum hipotezi 5. teyit** — mevcut pool zaten 6 hacim stratejisi
     (TOP_11'in %25'i) içeriyor; yeni hacim açıları sample yetersiz veya
     mevcut pool overlap. SEC4+SEC22+SEC23+SEC24+SEC25 zinciri.
  3. **Single-bar pattern selection-bias-prone** — D1, D4 IS→OOS sign-flip.
     Multi-bar / multi-event pattern'lar (turtle_soup 4-bar) daha robust olurdu.
  4. **HYP-D2 SOW asymmetry**: IS bull-heavy (2021-2023), OOS bear/range-heavy
     (2024-2026). Short pattern'ları regime-dependent → IS fail, OOS pass.
     SEC14.1 short trade 1.66× karlılık bulgusuyla uyumlu yan-teori.
- **Hangi bias'a düşmedim:** Confirmation bias (D2 OOS güçlü görünmesine
  rağmen pre-reg HARD gate fail → promote etmedim). Counter-hypothesis'leri
  önceden yazdığım için sample-frekansı (D3) ve volume_expansion overlap (D1)
  gibi tuzakları erken yakaladım.
- **Hangi bias'a düştüm:** **Sample frequency estimation bias** — pre-reg'de D3
  için "sample riski yüksek" not yazdım ama "yüksek" ne kadar bilemedim (15 trade).
  Pre-reg'e **expected_n estimation** (geçmiş benzer pattern frekansından
  enstrümante) ekle.
- **Bir dahaki sefer:**
  1. Hipotez başına pre-reg'e expected n estimation (sym-year başına frekans tahmini)
  2. v2 önerisi HYP-D2 SOW için: 3y rolling WF + 20 sym + EMA200 trend filter +
     halving cycle stratifikasyon
  3. Hacim sınıfı kapatılır; sonraki sprint açıları: data_engineer alt-data,
     4h proper sprint, cross-asset/forex

### 2026-05-14 — SEC25 PA-trend (Brooks DB Bull Flag, trend_cont): RED

- **HYP-2026-05-14-BROOKS-DB-BULL-FLAG:** **RED — n bottleneck + Bonferroni FAIL.**
  Default n=31 (gate ≥200 FAIL), 18-config grid Bonferroni α=0.00278: 0/18 PASS.
  C0 (eq=0.03/fb=3/body=0.30) honest hold>30 clip n=109 mR=+0.342 p=0.008 — 6/7
  gate PASS, sadece n<200 FAIL (multiple testing penalty).
- **Ne öğrendim (yapısal):**
  1. **Pattern gerçek edge VAR ama yetersiz n** — 5/6 yıl pozitif (sec24 TS 3/6,
     sec22 BB 0/11 sym positive), short-edge dominant (default short mR=+0.829 vs
     long +0.292; crypto bull bias TERSİ ilginç asymmetric bulgu).
  2. **Orthogonality MÜKEMMEL KANITLI** — engulfing jaccard=0.011 + donchian
     jaccard=0.000 (CH-2 ve CH-3 pre-reg gate'leri PASS). N yeter olsaydı
     ensemble slot-bottleneck atlatabilir aday potansiyeli vardı (SEC11e FVG paralel).
  3. **Trend_cont class crypto-fit POZİTİF prior güncellemesi** — sec22-24 mean-rev
     RED zincirinin counter-prior'ı. **Class-class crypto-fit matrix oluştu:**
     mean_rev RED (4-zincir kanıtı) | trend_cont PASS-MARGINAL+ (DB 5/6 yıl) |
     structural PASS (production). Sonraki sprint planlamasını yönlendirir.
  4. **SEC11a engine artifact 3. defa** — standalone test'lerde `runner_force_exit_bars=30`
     manifest override edilmiyor; default no-clip mR=+0.638, hold>30 clip mR=+0.240
     (-62% fantasy R erosion). Engineering ticket önerisi 3. defa (SEC22, SEC24,
     SEC25 zincir).
  5. **Compound multi-pivot pattern n bottleneck 3. defa** — SEC22 three-push
     n_max=77, SEC19 HTF n=35, SEC25 DB default n=31. Compound 3+ condition pattern
     crypto 1d × 11 sym'de yapısal yetersiz.
- **Hangi bias'a düşmedim:** mR=+0.638 + p=0.001 "PASS-looking" görünce hold>30
  clip + Bonferroni α=0.00278 multi-gate ile RED kararı verdim. 18-config grid
  pre-reg'de "k≥10 → Bonferroni" protokolü uygulandı. Orthogonality CH-2/CH-3
  pre-reg'de yazılıydı, jaccard=0.011/0.000 yan-bulgu olarak topla(n)dı.
- **Hangi bias'a düştüm:** **Sample size pre-estimation optimistik (SEC22 paraleli)**
  — pre-reg "n beklenti 550-1400" yazdım, gerçek 31. **Default parametre
  literatür-only** — equal_pct=0.03 Brooks stocks calibration, crypto vol-ölçeği
  için strikt. Pre-reg'de "crypto-microstructure-fit argument" yazdım AMA
  default'ta uygulamadım.
- **Bir dahaki sefer:**
  1. Compound pattern için pre-reg n estimate formula: `n_expected = 5y × n_sym ×
     annual_freq × recall=0.3` (Brooks DB ~5-15 trigger/sym × 0.3 = 60-200 beklenti).
  2. **Universe expansion sprint backlog:** DB Bull Flag 20+ sym standalone-only
     (sec13.3 ensemble RED ders → ensemble değil, standalone-only test).
  3. **4h timeframe variant backlog:** Compound pattern pivot artışı sample
     bottleneck'i çözebilir.
  4. **Trend_cont crypto-fit pozitif prior sırası:** Adam Grimes ABC two-leg
     pullback (pre-reg yazılı SEC25 backlog), ICT Breaker Block, Brooks Channel
     Line Third Touch Reversal, Minervini VCP (PA mastery gap NOT_TESTED listesi).
  5. **Class-class crypto-fit Bayesian prior matrix** memory'ye konsolide edilecek
     (sonraki sprint): `memory/researcher/class_crypto_fit_matrix.md`.

### 2026-05-22 — 15m honest edge hunt: wide-stop filter PASS (3 hipotez)

- **Hipotezler:** HYP-15m-wide-stop (PASS), HYP-15m-vsa-conviction (PARTIAL/superseded),
  HYP-15m-postonly-maker (KOŞULLU-PASS).
- **Sonuç:** 15m'de dürüst ≥%10/ay MÜMKÜN — sl_pct ≥ %1.8 wide-stop filtresiyle.
- **Ne öğrendim (yapısal):**
  1. **Fee-mezarın mekaniği R-cinsinden:** honest extra cost = `extra_bps / (sl_pct
     × 10000)`. Median sl_pct %1.39 → +55bps = 0.40R/trade. Pool mean R +0.20R'yi
     siler. ÇÖZÜM stop'u genişletmek DEĞİL (engine'deki stop sabit) — havuzun
     zaten geniş-stop olan alt-kümesini SEÇMEK. sl_pct entry'de ATR'den biliniyor
     → causal filtre. Tight-stop kuyruğu (sl<%1.2, 147k trade) honest −105k R;
     wide-stop kuyruğu (sl≥%1.8, 122k trade) honest +78k R. Aynı havuz, iki ekonomi.
  2. **Wide-stop trade'leri sadece düşük-maliyet değil, GROSS daha iyi:** IDEAL
     (pre-cost) mean_R wide +0.471 vs tight −0.046, WR %49 vs %44.4. Yani ATR-implied
     stop genişken sinyaller de gerçekten daha kaliteli. Çift kazanç.
  3. **SHUFFLE NULL'U YANLIŞ KULLANMAK — KRİTİK DERS:** R-permutation shuffle
     (trade'ler arası R'yi karıştır) p=1.0 FAIL verdi. Panik anı. AMA: R-shuffle
     bir SELECTION filtre için yanlış null — wide-stop R-multiset'ini koruyup
     sadece zaman sırasını bozar; pozitif-mean fat-tail dağılım her sırada iyi
     compound eder. **SELECTION filtre için doğru null = FULL pool'dan eşit-boy
     random subset.** O test: random +4.54%/mo, gerçek +21.72%/mo, p=0.0000 PASS.
     Ders: null hipotezi, test edilen edge'in TÜRÜNE göre seçilmeli — time-edge
     için R-shuffle, selection-edge için random-subset. Yanlış null yanlış RED üretir.
  4. **Per-month-mean vs continuous-curve artefaktı:** 61 bağımsız $10k replay
     ortalaması (+21.7%/mo) sürekli-eğriden sistematik yüksek (equity reset +
     multi-month DD kaçışı). Continuous curve +2.5M% gibi fizik-dışı sayı verir
     (compound artefaktı). DÜRÜST METRİK: pool sumR (compound-bağımsız) + per-month
     EXPECTATION + DD. Mutlak compound sayısı asla verme.
- **Hangi bias'a düştüm:** **Pre-reg büyüklük tahmini fazla karamsar** — "%4-9,
  %10 geçmez, RED-BORDERLINE" dedim, gerçek +21.7%/mo PASS. Reject-rate'i (engine
  %96 atıyor) gördüm ama kalan trade'lerin filtre-sonrası per-trade R artışını
  küçümsedim. Bu masada 8 ardışık RED'den sonra anti-recency bias da olabilir.
- **Hangi bias'a düşmedim:** Shuffle FAIL'de durup "RED" yazmadım — null'un
  yanlış olduğunu fark edip doğru null'u kurdum. Pre-reg gate "shuffle p<0.05"
  idi; FAIL görünce mekanizmayı sorguladım, gate'i mekanik körlükle uygulamadım.
- **Bir dahaki sefer:**
  1. Pre-reg'e null-tipi seçimini AÇIK yaz: "selection filter → random-subset null,
     time-edge → R-shuffle null". İkisini karıştırma.
  2. Wide-stop filtre HYP-1 production candidate — Lab paper trade + post-only
     fill-rate doğrulaması ile. Önce DD −41% throttle/sizing ile düşürülmeli.
  3. Per-month-mean raporlarken HER ZAMAN continuous-curve DD + pool-sumR yanına koy.

---

> Hafta sonu konsolidasyonu Lab tarafından.
