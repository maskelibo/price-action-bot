# ARAŞTIRMA PROGRAMI v2 — Edge Arama Uzayının Yeniden Tasarımı

**Tarih:** 2026-07-06 · **Yazar:** Fable 5 (Principal talebi) · **Statü:** Principal onayı bekliyor
**Kural seti:** pre-registration disiplini korunur · mevcut kapılar (DSR/robustness/OOS) GEVŞETİLEMEZ · sayı uydurma yok — bu dokümandaki her sayı dosya-kanıtlıdır.

---

## 1. KANIT: "Uzay tükendi" tezi kendi verimizle sınandı — VE ÇÜRÜDÜ (kısmen)

### 1a. Ret nedenleri frekans tablosu (`memory/researcher/seed_abort_log.jsonl`, 198 kayıt, 28 May → 29 Haz)

| Ret kategorisi | Adet | % |
|---|---:|---:|
| `REJECTED_PRE_TEST` (toplamın) | 193 | **%99.0** |
| — multiple-testing / family-wise-N şişmesi | 94 | %47.5 |
| — persona hard-limit (`NO_Vn_HYPOTHESIS_BODY`) | 93 | %47.0 |
| — prompt-injection tespit+absorbe | 91 | %46.0 |
| — self-throttle / circuit-breaker | 55 | %27.8 |
| — RAG corpus boş/bayat | 47 | %23.7 |
| Backtest aşamasında ölen | **0** | %0 |

**Kritik bulgu:** 198 kaydın tamamı PRE-TEST reddi; yalnızca **35 benzersiz seed** var ve tek bir seed (`cross-strategy-companion`) **87 kez** yeniden ateşlenip reddedilmiş (`learning.md:10-15`). Abort logu bir *arama* değil, **cron'un aynı byte-identical payload'ı self-throttle duvarına çarpması** (spin loop).

### 1b. Kapı-ölüm analizi (`backtest_results/`, 381 dosya)

| Kapı | Öldürdüğü | % |
|---|---:|---:|
| **EXECUTABILITY** — `NOT_EXECUTABLE` (motor yalnız 4 base stratejiyi destekliyor) | 312 | **%81.9** |
| Motora ulaşıp koşan (`status: OK`) | 66 | %17.3 |
| Koşanlardan terfi eden | 0 | — DSR `n_trials=n_trades` bug'ı yüzünden **matematiksel olarak imkânsızdı** (`RESUME_2026-07-02.md:9`); champion'ı +%21.5 geçen vsa-z adayı sırf bundan reddedildi. Bug 2 Tem'de düzeltildi → **ilk promote_candidate hemen çıktı** (grimes-abc). |

### 1c. Gerçek falsifikasyon (frontier programı — bu KISIM sağlam)

`reports/research/2026-06-10_frontier_20pct_README.md`: 13 tur / 41 pre-declared varyant, 3 bağımsız kanıt — **mevcut 4-detektör × 19-sembol ailesinin tavanı ~+%20-23/ay'da doyuyor**; parametre/ağırlık/slot/exit/concurrency vidalamak hedefi açamıyor. Eldeki funding-gate ve funding-carry denemeleri de RED (`README:205-220`).

### 1d. HÜKÜM (üç yorumun skoru)

| Yorum | Destek | Kanıt |
|---|---|---|
| (c) Arama dar/tekrarlı | **GÜÇLÜ — baskın** | 35 seed, 87× recycle, %99 pre-test |
| (b) Kapılar bozuk/aşırı | **GÜÇLÜ — enstrümantasyon artefaktı** | DSR bug'ı = 0 terfi garanti; fix sonrası ilk terfi adayı |
| (a) Gerçekten tükendi | **YALNIZ dar alt-uzayda** | 4 detektörün *parametre uzayı* doymuş (frontier, 3× bağımsız) |

> **Savunulabilir sonuç:** "Fiyat-only 15m uzayı tükendi" İDDİASI VERİYLE DESTEKLENMİYOR. Doğrusu: *4 mevcut detektörün parametre uzayı tükendi; nominal uzayın %82'si (13 detektör) hiç koşturulamadı ve fiyat-dışı modaliteler hiç denenmedi.* Maden bitmedi — kazma kırıktı ve hep aynı 2 metrekare kazıldı.

---

## 2. ENVANTER: Fiyat-dışı modalite hazırlığı

| Modalite | Veri durumu | Tarih aralığı | Araştırmaya hazır mı |
|---|---|---|---|
| **Funding rate** | ✅ 112.859 satır, 19 sym (`funding.duckdb`) | 2021-01 → 2026-06 (5+ yıl) | **KISMEN** — merge.py yanlış DB path'i okuyor (`funding_rates.duckdb` YOK); 1 aylık tazeleme + path fix gerek |
| Open interest | ⚠️ 570 satır, 30 gün | 2026-05 → 2026-06 | HAYIR — şema uyumsuz + tarih çok kısa; backfill şart |
| BTC dominance | ❌ DB hiç üretilmemiş | — | Kod TAM hazır (ingest+filter+test), sadece script koşulmamış |
| Sentiment (F&G) | ❌ DB yok | — | Kod TAM hazır |
| Stablecoin supply | ❌ DB yok | — | Kod TAM hazır |
| On-chain | ❌ DB yok | — | Kod TAM hazır |
| Liquidation | ❌ gerçek veri yok | — | **proxy DB'siz çalışıyor** (`alt_data/liquidation_proxy.py`) |
| Bybit 15m (cross-venue) | ❌ 1 sembol/9 bar | — | HAYIR — büyük backfill gerekir |
| 15m OHLCV (referans) | ✅ 3.5M satır, 19 sym | 2020-05 → bugün | EVET |

**Ana ders:** "Alt-data hattı" aylardır kod olarak hazır bekliyormuş; eksik olan tek şey **ingest script'lerini bir kez çalıştırmak** ve iki path/şema düzeltmesi. Bu, haftalarca değil günlerce iş.

---

## 3. PROGRAM: 3 hipotez AİLESİ

### AİLE 1 — "Kilitli stok": motor köprüsü + hiç koşmamış 13 detektör *(fiyat-only ama BAKİR)*

- **Modalite:** mevcut 15m/1d OHLCV (ek veri işi YOK).
- **Ekonomik rasyonel:** 5 substantive RAG-hipotezi (donchian-20/55, kATR-breakout, TRM-continuation, falling-three, triple-inside) pre-registered halde `NOT_EXECUTABLE` rafında çürüyor. Bunlar 4 doymuş detektörle **düşük korelasyonlu** pattern sınıfları — kaybeden taraf: 4-detektör alanına yığılmış kalabalık; kazanç kaynağı: farklı zaman/yapı ölçeğindeki davranışsal tepkiler (trend-devam ve volatilite-kırılım aileleri).
- **Beklenen sinyal sıklığı:** detektör başına 1d'de ~2-6 sinyal/ay/sembol (Donchian sınıfı); 15m versiyonlarında 10-30×. (Kaynak: hipotez dokümanlarının kendi tahminleri — koşunca doğrulanacak.)
- **Kapılar:** mevcut zincir AYNEN (DSR-fixed, robustness suite, OOS, adversary kill-probe).
- **Gereken iş:** `hypothesis_runner → engine` köprüsü (RESUME'nin kendi teşhisi: "%82 NOT_EXECUTABLE'ın ilacı", `RESUME_2026-07-02.md:40`). Veri işi sıfır; saf mühendislik.

### AİLE 2 — Funding/OI rejim etkileşimi *(ilk gerçek fiyat-dışı modalite)*

- **Modalite:** funding (5y hazır) + OI (backfill gerekli); mevcut detektörlere **koşullandırma katmanı** olarak (yeni detektör değil → AİLE 1'in motor işine bağımlı değil).
- **Ekonomik rasyonel:** funding, kalabalık tarafın ödediği kira. Aşırı funding + OI şişmesi = geç kalmış kaldıraçlı retail pozisyonu; mean-reversion'ın karşı tarafında **funding'i ödeyen** kaybediyor. Sistem geçmişinde tek erken PROMOTED hipotez de buradan (`2026-05-08-funding-rate-mean-reversion.md`). Frontier'ın RED verdiği iki tasarım (15m funding-gate, 3g-trailing carry) bu ailenin yalnızca 2 hücresiydi — rejim-koşullu kullanım (ör. "yalnız funding-ekstrem + OI-artış rejiminde vsa/grimes sinyali al") hiç test edilmedi.
- **Beklenen sinyal sıklığı:** koşullandırma olduğu için mevcut sinyal akışının %20-40'ı (filtre); funding-MR ailesi 1d'de ~1-3 sinyal/hafta/evren.
- **Kapılar:** aynen + frontier'ın RED ettiği 2 hücre pre-registration'da "prior art RED" olarak zorunlu atıf.
- **Gereken veri işi:** merge.py path fix (funding.duckdb'ye yönlendir) · funding 1-ay tazeleme · OI backfill + şema kolonları (`oi_pct_change`, `oi_z_30d`) — OI uzun tarih kaynağı belirsiz (bkz. Principal soruları).

### AİLE 3 — Likidite süpürme + likidasyon-proxy teyidi *(mikroyapı, event-time)*

- **Modalite:** OHLCV + DB'siz çalışan `liquidation_proxy` (+ AİLE 2'nin OI'si geldiğinde teyit katmanı).
- **Ekonomik rasyonel:** swing high/low üstü stop kümeleri süpürüldüğünde (sweep) likidite alan taraf pozisyonunu doldurur, fiyat sıkça geri döner; kaybeden: stop'u süpürülen yönlü trader + geç breakout-alıcısı. Mevcut SMC testlerinden farkı: SMC serisi 1d bar'da genel mekanizma olarak RED'di; burada **proxy-score teyitli + event-time örnekleme** (bar yerine hacim-saati) dar bir tetik test ediliyor — bu kombinasyon repo tarihinde hiç koşmadı.
- **Beklenen sinyal sıklığı:** 15m'de sembol başına ~2-8 sweep/hafta; proxy-teyit filtresi sonrası ~%30'u.
- **Kapılar:** aynen; ek olarak SMC-RED geçmişine zorunlu atıf ve ayrışma gerekçesi.
- **Gereken iş:** sweep detektörü (vektörize, lookahead-testli — signal_chief standartı) + event-time bar üreticisi (orta mühendislik); veri işi yok.

**Bilinçli DIŞARIDA bırakılanlar:** cross-venue (Bybit 15m verisi yok — büyük backfill, düşük öncelik) · tick/footprint (veri erişimi yok) · 4h-native (frontier "çok haftalık ayrı R&D" dedi — AİLE 1-3'ten biri kazanırsa 2. ay gündemi).

---

## 4. FABRİKA EKONOMİSİ

### 4a. Mevcut durum (41 gün, `data/llm_calls.jsonl`, 1.446 çağrı)

- Toplam: **313M input / 6.4M output token**. Researcher tek başına input'un **%67.5'i** — çağrı başına **~609K input** (dev context her seferinde yeniden gönderiliyor).
- API-eşdeğer maliyet (Opus 4.7 $5/$25): ~**$1.200/ay** (41-gün ortalaması). 2 Tem cadence kesimi sonrası son 7 gün: ~$45/hafta ≈ **$200/ay** — yani kesim işe yaradı ama hedefin hâlâ ~1.7×'i. *(Not: fiili fatura CLI/abonelik kanalından — bkz. run_ceo.sh:43; $ rakamları fırsat maliyeti.)*

### 4b. Duraklatma/seyreltme önerileri (hedef ≤$120/ay eşdeğeri)

| Job | Şimdi | Öneri | Gerekçe / kalite şerhi |
|---|---|---|---|
| `researcher_5batch` (02:30) | günlük | **DURDUR** (PROGRAM_V2 aileleri motor+veriyle hazır olana dek) | 41 günde çıktısı: recycled-seed spin loop'u. Kalite kaybı YOK — üretmediği şey kaybedilemez. H2'den itibaren aile-hedefli olarak geri açılır |
| `hypothesis_backtest_runner` (*/30) | 48×/gün | **2 saatte bir + LLM-extract öncesi deterministik executable-filter** | 312 NOT_EXECUTABLE'a extract token'ı yakıldı; filtre 3 satırlık kontrol |
| `daily_lab_tournament` (04:00) | günlük | **challenger-yoksa-skip ön-kontrolü** (deterministik) | Yeni aday yokken Opus'la turnuva raporu = boş tören. lab 443 çağrıyla 2. en büyük kalem |
| `adversary_daily_stress` | günlük | 2 günde bir | Aday akışı yokken günlük stress raporu düşük bilgi; deploy-önerisi geldiğinde otomatik tetik zaten var |
| `researcher_pulse` (06/18) | 2×/gün | KALSIN | Jul-02 kesimi yeterli; aile-hedefli promptla değerli |
| `curator_daily_correlation` | günlük | KALSIN (canlı bot var) | Canlı 2-kol korelasyon takibi GO/NO-GO için gerekli |
| param_sweep / auto_iterate / tf_exploration | çeşitli | dokunma ($ etkisi ~0) | Deterministik CPU; faturaya girmiyor |

**Ek yapısal tasarruf:** researcher çağrı başına 609K input'un ana kaynağı context şişmesi — aile-hedefli promptlarda yalnız İLGİLİ hipotez ailesinin geçmişi verilmeli (boot-context zaten 24K cap'li; sorun ek dosya ekleri). Tahmini etki: researcher input %50-70 ↓ → toplam ~$80-110/ay bandı.

### 4c. RAG'ın hipotez kalitesine katkısı: **SIFIR/NEGATİF (kanıtlı)**

Son 10 hipotezin izi: RAG-zengin 5 substantive hipotez → hepsi `NOT_EXECUTABLE` (motor engeli — RAG'ın suçu değil ama katkısı da ölçülemedi); 5 seed-abort → RAG yalnız "corpus bayat/byte-identical" itirafı olarak geçiyor (meşrulaştırma süsü). Corpus 21 May'den beri DONUK (38+ gün); haftalık refresh cron'u SLA ihlalinde. **Öneri:** (1) refresh'i onar ve AİLE 2/3 literatürü ekle (funding/mikroyapı); (2) hipotez şablonunda RAG atfını "zorunlu bölüm" olmaktan çıkar → "yeni bilgi varsa cite" (süs-atıf ölçümü kirletiyor).

---

## 5. TAKVİM — 4 hafta

| Hafta | İş | Ölçülebilir hafta-sonu çıktısı | Karar noktası |
|---|---|---|---|
| **H1** (7-13 Tem) | Motor köprüsü faz-1 (5 bekleyen substantive detektör) · funding merge path-fix + 1-ay tazeleme · dominance/sentiment/stablecoin ingest'lerini İLK KEZ koştur · researcher_5batch DURDUR + executable-filter | Köprü smoke-test: 5 hipotezden ≥3'ü `status: OK` koşuyor; 4 alt-data DB'si dolu | Köprü çalışmıyorsa → H2 planı revize (Principal'a haber) |
| **H2** (14-20 Tem) | AİLE 1 tam backtest turu (5 hipotez × robustness suite, kapılar aynen) · OI backfill başlat | 5 hipotezin GO/RED tablosu (sistemin İLK gerçek yeni-detektör sonuçları) | ≥1 GO → lab tournament'a; 0 GO → AİLE 1'in kalan 8 detektörüne genişleme kararı |
| **H3** (21-27 Tem) | AİLE 2 pre-registration (3-5 hücre: funding-ekstrem koşullu grimes/vsa + funding-MR 1d) + backtest · RAG corpus refresh + yeni literatür | AİLE 2 verdict tablosu + prior-art (frontier RED) karşılaştırması | Funding-koşullu hücrelerden sinyal-sayısı yeterliliği kontrolü (n≥100 trade) |
| **H4** (28 Tem-3 Ağu) | AİLE 3: sweep detektörü + proxy teyit PoC (event-time varyantı dahil) · ay-sonu ekonomi ölçümü | AİLE 3 ilk backtest + **fatura raporu (hedef ≤$120/ay eşdeğeri)** + "hangi aile 2. aya geçiyor" önerisi | Principal review: program devam/pivot |

Her hafta çıktısı `reports/research/` altına pre-registration disipliniyle; hiçbir kapı gevşetilmez; her aile hipotezi frontier/SMC prior-art'ına zorunlu atıf yapar.

---

## 6. PRINCIPAL'A SORULAR

1. **OI tarihsel veri kaynağı:** Binance OI endpoint'i ~30 günle sınırlı. Uzun tarih için Bybit/Coinalyze/ücretli kaynak araştırması onaylı mı, yoksa AİLE 2 "OI'siz funding-only" mi başlasın?
2. **researcher_5batch DURDUR + hypothesis_runner seyreltme** (4b tablosu) — onay? (Scheduler değişikliği gerektiriyor; bu doküman koda dokunmadı.)
3. **Motor köprüsü** kim/ne zaman: ayrı bir odaklı oturum mu (tahmin: 1-2 gün iş), yoksa H1'de bu oturumların devamı mı?
4. GO/NO-GO forward-test saati **2 Tem'den mi** sayılıyor (config o günden beri değişmedi — P1-5'teki düzeltmeler yorum-only, VERIFY parametreleri aynı)?
5. RAG şablon değişikliği (4c) researcher persona dosyasına işlensin mi?
