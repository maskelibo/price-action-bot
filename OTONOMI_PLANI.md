# TAM OTONOMİ PLANI — Güncel Gerçekleşen Durum

**İlk plan:** 2026-07-07
**Son doğrulama:** 2026-07-11
**Değişmez insan kapısı:** gerçek para ve herhangi bir canlı emir yetkisi yalnız Principal

Bu belge artık hedefleri olmuş gibi anlatmıyor. Aşağıda çalışan kod, testle
kanıtlanan sınırlar ve henüz kapanmayan veri/operasyon bağımlılıkları ayrı
gösterilir.

## 1. Yönetici özeti

| Faz | Güncel durum | Gerçekte çalışan sınır |
|---|---|---|
| Faz 2 — strateji köprüsü | **TAMAMLANDI** | Raf stratejileri çoklu TF backtest yoluna bağlandı; yazılı kabul kapıları tipli ve fail-closed. Tarihsel `GO`, bağımsız OOS olmadan terfi yetkisi vermez. |
| Faz 3 — TF keşif + bağımsız OOS | **KOD HAZIR / ADAY YOK** | 5m, 15m, 30m, 1h ve 4h keşfi config-driven. Terfi öncesi prospektif preregistration, gelecekteki holdout ve içerik-hash zinciri zorunlu. Gerçek taramalardaki adaylar RED; aktif preregistration veya yetkili OOS kanıtı yok. |
| Faz 4 — shadow | **SİNYAL-ONLY ALTYAPI HAZIR / ORİJİNAL TESTNET HEDEFİ YAPILMADI** | Geçerli bağımsız OOS kanıtından config + ayrı DuckDB journal + kuyruk kaydı üretilebilir. Süreç, launchd, testnet ve emir yolu üretilmez. Yerel scheduler tick’i ancak ayrıca yetkilendirilmiş kuyruk satırını çalıştırır. |
| Faz 5 — Forex | **KOD HAZIR / OPERASYONEL DEFER** | Kalıcı paper-only readiness, sinyal journal’ı ve deterministik yerel paper broker hazır. Feed donuk ve observed spread yok; bu yüzden journal/broker mutasyonu başlamaz. |
| Faz 6 — feature factory | **DESCRIPTIVE HAZIR / TERFİ YETKİSİ YOK** | 1h/4h/1d üzerinde 100+ feature ve tek global BY-FDR ailesi çalıştı. 11 descriptive discovery var; tamamı `promotion_eligible=false`. |
| Faz 6 — agent-output eval | **HARNESS HAZIR / MEVCUT ÇIKTI FAIL** | Offline kalite harness’i çalışıyor ve golden kontratı geçiyor. Seçili gerçek hipotez; eksik `Accept Gates`, düşük sayısal-atıf bağı ve parse edilemeyen kapılar nedeniyle kalite eşiğini geçmedi. |

Sonuç: araştırma ve paper güvenlik zinciri entegre; sistem **canlı bot veya
otomatik testnet süreç hazırı değildir**. Bu, bilinçli olarak korunmuş bir yetki
sınırıdır ve veri/kanıt yokken “hazır” sayılmaz.

## 2. Faz 2 — strateji rafından motora

Yapılanlar:

- `hypothesis_runner` yeni strateji sınıfını çözüp çoklu TF verisiyle
  çalıştırabiliyor.
- Sonuçlarda `bridge_version=2` bulunuyor; eski `DEFERRED` kayıtlar kontrollü
  olarak bir kez yeniden deneniyor, sonsuz retry yok.
- `accept_gates` artık yalnız metin değil. Desteklenmeyen, eksik veya non-finite
  kanıt otomatik başarısız oluyor.
- Tarihsel sonuçtaki ham `GO`, bağımsız kanıt yoksa yalnız `RESEARCH_GO`; kapı
  başarısızsa `HOLD_GATE_FAILURE` olur.

Kalan sınır:

- Bu köprü bağımsız OOS değildir ve tek başına shadow/live terfi üretemez.

## 3. Faz 3 — TF keşfi ve bağımsız OOS

### Yapılanlar

- Keşif evreni `configs/tf_expansion_targets.yaml` içinde tanımlı:
  4 strateji × `{5m,15m,30m,1h,4h}`.
- 30m, 1h ve 4h canonical pool/robustness çalışmaları tamamlandı.
- Scheduler sırası:
  - `04:30` TF keşfi — yalnız `PA_RESEARCH_AUTOPILOT=1` iken;
  - `04:40` bağımsız OOS değerlendirmesi — her zaman kayıtlı;
  - kanıt → signal-only spec tüketicisi bağımsız bir cron değildir; `04:40`
    OOS değerlendirmesi gerçekten tamamlandıktan sonra aynı coroutine tarafından
    çağrılır. Yalnız `SPEC_READY_NOT_RUNNING` + `auto_start=false`
    config/kuyruk kaydı üretir, adayı çalıştırmaz.
- `tf-independent-oos-v2` sözleşmesi şunları preregistration anında dondurur:
  seçim cutoff’u, pool prefix/file hash’leri, ham veri ve builder provenance’ı,
  strateji modülü, protokol, evaluator wrapper + modül hash’leri ve parametre
  varyantları.
- Holdout yalnız preregistration sonrasındaki satırlardan oluşur. Minimum 90
  takvim günü, aday/baseline trade sayısı, symbol-out, walk-forward, rejim,
  ortak ay, permutation + Bonferroni ve parametre varyant kapıları fail-closed.
- Geçerli kanıt promotion tüketicisinde canonical evaluator replay ile yeniden
  üretilmeden kabul edilmez.
- Legacy pool pickle’ları yalnız pandas Timestamp ve gerekli `datetime`
  sınıflarını kabul eden restricted unpickler ile açılır; arbitrary pickle
  import/code execution reddedilir. Bu hardening evaluator hash’ini değiştirdi.
  Gerçek preregistration sayısı sıfır olduğu için aktif bir kanıt zinciri
  geçersizleşmedi; ilk preregistration güncel hash’i pinleyecek.

### Gerçek sonuç

- Mevcut 30m/1h/4h adaylarının robustness sonucu RED.
- Mevcut üç descriptive pool, bağımsız OOS giriş kontratını henüz karşılamıyor:
  `regime` alanı ve `.provenance.json` zinciri yok; ayrıca preregister edilecek
  içerik-ayrı parametre varyant pool’ları gerekli.
- `reports/tf_oos/prereg` altında gerçek preregistration sayısı `0`.
- Bu nedenle prospektif preregistration, bağımsız OOS evidence veya shadow spec
  oluşmadı. “Kod hazır” ile “strateji geçti” aynı şey değildir.

## 4. Faz 4 — signal-only shadow

### Yapılanlar

- Yalnız `PROMOTION_AUTHORIZED` + `INDEPENDENT_OOS` +
  `SIGNAL_ONLY_SHADOW` kapsamlı, içerik-adresli kanıt kabul edilir.
- Üretilen varlıklar yalnız şunlardır:
  - `_approved-shadow-*` hipotez kaydı;
  - `configs/shadow/*.yaml` signal-only config;
  - aday başına ayrı `data/shadow/*.duckdb` journal;
  - manifest ve namespaced deploy-queue satırı.
- Config sınırı: `sim_only=true`, `signal_only=true`, exchange/credential/private
  market-data/order/cancel kapalı, `auto_start=false`, launchd bootstrap ve
  daemon restart kapalı.
- Yerel strateji modülü allowlist + AST capability taraması + kaynak hash’i ile
  pinlenir. Çalışma anında network/socket/subprocess/thread/filesystem-write
  yetenekleri de engellenir.
- Scheduler `:11/:26/:41/:56` tick’i yalnız kuyrukta
  `SHADOW_ACTIVE_AUTHORIZED` ve ayrı tarihli authorization bulunan adayı yerel
  kapanmış barlarla değerlendirir. Emir veya exchange I/O yoktur.
- OOS-tamamlanınca çağrılan promotion tüketicisi ile `:11/:26/:41/:56`
  runtime tick’i ayrı kapılardır: `SPEC_READY_NOT_RUNNING` satırı scheduler
  tarafından çalıştırılmaz. Kod/spec hazır olması aktif çalışma yetkisi
  anlamına gelmez.

### Yapılmayanlar

- Orijinal plandaki `bot_factory → launchd → ayrı testnet bot process` zinciri
  kurulmadı.
- Otomatik süreç başlatma, testnet API, canlı market API veya emir yolu yok.
- Geçmiş aday geçmediği için bugün aktif/çalışan bir TF shadow adayı da yok.

## 5. Faz 5 — Forex kalıcı paper-only

### Yapılanlar

- `forex_market.duckdb` yalnız `read_only=True` ile inceleniyor.
- YFinance/Yahoo FX kaynağı kod seviyesinde reddediliyor; trusted venue
  `histdata`.
- Readiness; güncel seri, OHLC bütünlüğü, observed `spread_bps`, piyasa-açık
  zamanına göre freshness ve içerik-pinli yerel runner/paper-broker
  yeteneklerini birlikte istiyor.
- Güvenlik alanları exact boolean: string veya `0/1` boolean yerine geçemez.
- Paper broker yalnız sentetik USD notional kullanır; sonraki kapanmış bar
  açılışı, observed spread ve aynı-bar belirsizliğinde konservatif `SL_FIRST`
  uygular. Tekrar koşum idempotenttir ve haftalık KPI üretir.
- Scheduler coordinator `8 */4 * * *` ritminde kayıtlıdır. Bu bir launchd veya
  dış süreç autostart’ı değildir; readiness `DEFER` iken sinyal/paper DB’si
  oluşturmaz veya değiştirmez.
- Kalıcı sınır: paper-only; credential, network, exchange, testnet ve order
  yüzeyi yok.

### Gerçek blokaj

- EUR/USD, GBP/USD ve USD/JPY 4H son gözlenen barı
  `2025-12-31T20:00:00Z`.
- Feed capability kapalı ve `spread_bps` şeması mevcut değil.
- Son gerçek readiness sonucu `DEFER`; paper coordinator
  `DEFER_READINESS`. Bloklanan koşum sinyal veya broker DB’sini mutate etmedi.

## 6. Faz 6 — feature factory ve agent-output kalite kapısı

### Feature factory

- 18 Binance sembolü × `{1h,4h,1d}` × 113–118 feature × 3
  volatility-normalized hedef çalıştı.
- Tüm seçili TF/sembol/feature/hedef kombinasyonları **tek** global
  Benjamini–Yekutieli ailesinde düzeltildi: `18,963` test.
- Kronolojik 70/30 bölüm descriptive confirmation’dır; bağımsız promotion
  holdout değildir.
- Gerçek tam koşum: 11 discovery (`1h=11`, `4h=0`, `1d=0`); strict v2 kuyruğa
  11 kayıt, eski 196 kayıt quarantine. Bütün v2 kayıtlar
  `promotion_eligible=false`.
- Mevcut yardımcı aileler: funding, sentiment, cross-sectional ve takvim
  event-time. Eksikler açıkça işaretli; sentetik doldurma yok:
  - open interest: yetersiz tarih;
  - BTC dominance: yetersiz tarih;
  - stablecoin supply: boş;
  - scheduled macro: point-in-time kaynak yok.

### Agent-output eval harness

- Offline ve deterministik; LLM/ağ/emir çağrısı yok.
- Zorunlu metadata/bölümler, sayısal iddia-atıf bağı, tipli accept-gate,
  forbidden içerik, yetki ihlali ve novelty ölçülüyor.
- Harness’in golden kontratı PASS.
- Seçili gerçek XS-carry hipotezi `QUALITY_GATE_FAIL`:
  skor `0.700758 < 0.90`, pass-rate `0`, sayısal atıf bağı `0/27`, parse edilen
  accept gate `0`. Bu kalite sonucu hiçbir deployment/promotion/live yetkisi
  vermez.

## 7. Kalan iş ve gerçek kapanış ölçütleri

1. **TF kanıtı:** Yeni bir aday önce descriptive robustness’u geçmeli; sonra
   preregister edilip yalnız gelecekte oluşan en az 90 günlük bağımsız OOS
   penceresini tamamlamalı.
2. **Shadow saha kanıtı:** Yetkili OOS kanıtı oluşursa operator yalnız yerel
   signal-shadow tick yetkisi verir; journal/KPI penceresi temiz kapanmadan
   yeni yetki tartışılmaz.
3. **Otomatik testnet süreç:** Orijinal Faz 4 hedefi hâlâ backlog’dur. Ayrı
   process/launchd/testnet kapsamı, kill criteria ve Principal onayı olmadan
   eklenmeyecek.
4. **Forex veri:** Güvenilir, point-in-time, güncel local feed + observed spread
   adaptörü ve sürekli freshness alarmı gerekli. Sağlanınca mevcut coordinator
   yalnız yerel paper akışını başlatabilir.
5. **Feature kapsamı:** OI/dominance/stablecoin/macro için yeterli ve
   point-in-time kaynak gerekli; bulunan descriptive kayıtlar bağımsız OOS
   protokolüne girmeden kullanılamaz.
6. **Agent çıktıları:** Üretici formatı harness’in zorunlu `Accept Gates` ve
   kaynak-bağlama kontratına taşınmalı; gerçek örnekler PASS olmadan kalite
   halkası kapanmış sayılmaz. Harness henüz scheduler/CI terfi kapısına bağlı
   değildir; bu bağlantı yapılırken yine yalnız kalite kapısı olarak kalmalıdır.
7. **Altyapı:** VPS/failover ve tek-makine SPOF çözümü bu kod tesliminde
   yapılmadı.

## 8. Değişmez koruma rayları

1. Descriptive araştırma hiçbir zaman bağımsız OOS veya deployment kanıtı
   sayılmaz.
2. Kapı/hashes/provenance eksikliği `HOLD/DEFER/REJECT`; varsayılan geçiş yok.
3. Shadow config’leri signal-only ve `auto_start=false`; gerçek para daima
   Principal kapısında.
4. Forex kalıcı paper-only; testnet ve live da yasak.
5. Feature ve agent-output sonuçları yalnız araştırma/kalite girdisidir; terfi
   yetkisi değildir.
6. Scheduler kaydı yetki genişletmez: her tüketici kendi içerik, kapsam ve
   authorization kapısını yeniden doğrular.

## 9. Son yerel doğrulama — 2026-07-11

- Birleşik Faz 3–6 regresyonu: **208 passed, 1 optional-dependency skip**.
- TF pool/prereg/OOS/promotion/signal-shadow zinciri: **94 test collected/passed**.
- Forex readiness/signal/paper-broker/scheduler: **43 test collected/passed**;
  `yfinance` gerektiren eski engulfing modülü opsiyonel dependency yokluğunda
  collection sırasında **1 skip** verdi ve kalıcı HistData-only paper yolunun
  kanıtına dahil edilmedi.
- Offline agent-output eval: **27 test collected/passed**; gerçek seçili çıktı
  ayrıca `QUALITY_GATE_FAIL` (beklenen fail-closed sonuç).
- Ruff, Python compile, YAML/JSON parse ve Forex capability content-hash
  doğrulaması: PASS.
- Restricted pool decoder gerçek 4h legacy pool'daki **33,238** kaydı yalnız
  minimal allowlist ile açtı; kötü niyetli pickle regression’ı code execution
  üretmeden reddedildi.
