# Operations / DR pending — 2026-07-11

Bu kayıt kodla uydurulamayacak dış bağımlılıkları görünür tutar. Aşağıdaki iki
kalem kapanmadan sistemin disaster-recovery durumu **DEGRADED** kabul edilir.

## 1. Healthchecks dış dead-man — PENDING

- launchd job ve sağlık-koşullu ping script'i kurulu.
- `HEALTHCHECKS_PING_URL` yapılandırılmadığında script her koşuda `INERT` yazar;
  dashboard WARN gösterir. Daemon/emir davranışı değişmez.
- Sahte URL eklenmez. URL, dış hesap ve bildirim hedefi Principal tarafından
  oluşturulmalıdır.

Kapanış kanıtı:

1. URL `.env` içine değeri loglanmadan eklenir.
2. Job'ın başarılı ping'i dış servis ekranında görülür.
3. Canlı daemon durdurulmadan, kontrollü test check'i susturularak grace süresi
   sonunda gerçek e-posta/push alarmı alınır.
4. Test sonrası normal ping tekrar görülür ve dashboard WARN kalkar.
5. Alarm teslim kanıtından sonra `.env` içine UTC ISO-8601 değeriyle
   `HEALTHCHECKS_ALARM_DRILL_VERIFIED_AT` yazılır. Bu marker yok/geçersizse
   endpoint ping'i başarılı olsa bile dashboard WARN kalır.

## 2. Şifreli off-site backup — PENDING

- Günlük DuckDB backup'ları şu anda kaynakla aynı fiziksel disktedir.
- Repo içinde rclone/restic/S3/Backblaze veya eşdeğer bir taşıma job'ı yoktur.
- Yerel checksum manifesti bit-rot/değişiklik tespiti sağlar; disk kaybına karşı
  koruma sağlamaz.

Kapanış kanıtı:

1. Principal hedef sağlayıcıyı ve credential saklama yöntemini seçer.
2. Client-side şifreli, append/retention kontrollü aktarım job'ı eklenir.
3. En az bir backup yalnız off-site kaynaktan geçici dizine indirilir.
4. Checksum doğrulaması ve tüm DuckDB tablolarında tam `COUNT(*)` restore drill'i
   geçer; tarih, süre ve hash rapora kaydedilir.

## Kod tarafında kapatılanlar

- Backup canlı prosesi durdurmaz veya kaynak DB'ye ikinci DuckDB bağlantısı
  açmaz. DB+varsa WAL'i gizli stage'e kopyalar; yalnız bu izole kopyada
  `CHECKPOINT` + tüm base-table `COUNT(*)` doğrulamasını en fazla üç kez dener.
  Kopya öncesi/sonrası kaynak çiftinin existence/type/inode/size/mtime_ns
  fingerprint'i exact aynı ve stage boyutları pre-capture ile eşit olmalıdır.
  Yalnız tüm DB'ler geçince atomik yayınlar, WAL'siz SHA256 manifest üretir ve
  newest-3 tutar. Torn/değişen pair doğrulanmazsa önceki backup korunur.
- Restore güncel v15p2 yanında `e13`, eski `futures15m`, `_v11`, `_v63`, `5m`,
  `multitf` ve v14 dahil bilinen restart-capable DB kullanıcıları bootout ise
  ilerler. `lsof` kontrolü onay öncesi/sonrası ve replace sınırında tekrarlanır.
- Manifestte listelenmiş DB/WAL artifact'i eksikse restore checksum kapısında
  fail-closed durur; eksik WAL sessizce atlanmaz.
- Restore staging + WAL checkpoint + tam tablo okuma + atomik replace + rollback
  akışına sahiptir.
- Dashboard günlük backup'ın last-exit ve log tazeliğini kontrol eder; idle PID'yi
  otomatik başarı saymaz.
- Health ping, daemon/log sağlıksızlığında ağ isteğini atlar ve non-zero
  döner; endpoint teslim hatası da non-zero'dur. URL ve başarılı ping tek başına
  dashboard'u yeşile çevirmez; gerçek dış alarm drill timestamp'i de gerekir.
- CI Bandit scanner hatası/boş taraması false-green olamaz.

## 3. Binance testnet 418 / `-1003` — DEPLOYED, 48H OBSERVATION ACTIVE

- 23:49 TR yerel log sayımında geniş 418/`-1003` eşleşmesi `66` satırdır.
  Son olay `19:00:22Z / 22:00:22 TR` sırasında ZEC eski stop iptalinde
  görülmüştür. Sonraki `20:45Z` turu `1 pos / 3 algo` ile tamamlandı ve stop
  `514.44` seviyesine taşındı; bu recovery deploy veya 48 saat kanıtı sayılmaz.
- Kök katkılar sayısallaştırıldı: eski DMS yaklaşık `329–348` private HTTP/saat
  ve yerel private request adedinin `%90+` bölümünü üretiyor; symbolsüz
  regular+algo order state de `40+40 weight/bar` tüketiyor.
- Disk fixleri: external-main-loop DMS, shared cooldown, cooldown-aware flatten,
  symbol-scoped order state, gerçek orphan-aday kapısı, process-long main client,
  stale scanner fail-closed, venue-başına tek ingest client ve whitelist
  `RATE_BUDGET` header telemetrisi.
- CEO wrapper/plist'i `PA_DISABLE_PRIVATE_EXCHANGE_API=1`; guard credential,
  client ve network öncesi çalışır. CEO olay boyunca unloaded kalır.
- NEAR ve ZEC doğal kapandı; journal/log `0 pozisyon / 0 algo`, open signal `0`
  ve nonterminal protection `0` doğruladı.
- Tek güvenli restart `2026-07-11T23:58:26Z` sınırında yapıldı. Eski PID
  `34731`, yeni PID `53783`; yeni image `23:59:56Z` anında başladı.
- Startup `VERIFY_OK`, DMS `external_main_loop`, background REST `OFF`,
  process-long ana client ve flat protection rebuild kapılarını geçti.
- İlk doğal bar `00:00:05Z`: `0 pozisyon / 0 algo`, wallet/equity `$4958.43`,
  `RATE_BUDGET used_weight_1m=437`. Rate olay sayısı `66 → 66`.
- 48 saatlik kapanış penceresi `2026-07-13T23:59:56Z`
  (`14 Temmuz 02:59:56 TR`) anında dolar; o zamana kadar incident açık kalır.
- Incident kaydı:
  `memory/shared/incidents/INC-2026-07-11-binance-testnet-rate-ban.md`.

Kalan kapanış: DMS heartbeat yaklaşık `178/saat → 4/saat`; her bar
`RATE_BUDGET` + protection tutarlılığı; başarılı startup sonrası 48 saat sıfır
yeni 418 ve cooldown boyunca factory HTTP çıkışı sıfır. Doğrulama amacıyla ek
manuel REST çağrısı yapılmaz.

## 4. CEO scheduler — INTENTIONALLY UNLOADED

- CEO araştırma/rapor görevleri kod olarak hazırdır fakat aktif rate olayı ve
  eski trade PID'i varken ikinci private okuyucu başlatılmaz.
- Guarded plist/wrapper deploy edilir fakat launchd job, trade daemon güvenli
  restart + ilk temiz bar doğrulamasından önce load edilmez.
- Guarded CEO açıldığında private account/position/income isteyen işler
  fail-closed; yerel araştırma ve rapor işleri çalışmaya devam eder.

## Yerel backup saha kanıtı — PASS (2026-07-11 02:38 TR)

- Gerçek günlük script 39/39 DB için staged CHECKPOINT + tam base-table okuması
  geçti; sürekli açık `market_ingest.duckdb` de canlı prosesi durdurmadan geçti.
- Yayımlanan `20260711/backup_manifest.sha256` 39 satır ve tamamı `shasum -c`
  ile doğrulandı; yayımlanmış sette WAL yok.
- Retention tam `20260709`, `20260710`, `20260711`; `20260708` prune edildi.
  Yerel backup toplamı 10,974 MB, disk %85 dolu / 32 GiB boş.

## Dashboard collector saha kanıtı — PASS / WARN VISIBLE (2026-07-11)

- Dashboard trading daemon'a dokunulmadan güvenli restart edildi. `/api/snapshot`
  yerel DB backup `OK / manifest var`, healthping `WARN / INERT URL yok`,
  off-site `WARN / PENDING` ve Binance private REST için `38 event`, son event,
  ban deadline, `active/recent_48h` alanlarını yalnız yerel logdan gösterdi.
- Collector hiçbir exchange client kurmaz; aktif-ban dashboard satırı
  `WARN` kalır ve genel sağlık false-green olamaz.

## Otomatik ingest→consumer→E13 saha kanıtı — PASS

- Doğal ingest run `766`: `19/19`, exit `0`, strict checkpoint/close sonrası
  atomik snapshot; `1,637,363,712` bayt, `10,611,632` satır,
  `newest_bar=2026-07-11T02:00:00Z`.
- Source/consumer `COUNT(*)` + `MAX(ts)` exact eşleşti; WAL/tmp kalmadı.
- Sonraki doğal E13 run `15`: `status=OK`, `bars_applied=1`, `issues=[]`,
  `exchange_calls=0`, `network_calls=0`.

## İlk saha kanıtı bekleyen diğer kod değişiklikleri

- Restore akışının canlı DB'lere dokunmadan hazırlanmış kopya üzerinde bakım
  penceresi drill'i. Açık pozisyon varken canlı daemon stop/restart edilmez.
