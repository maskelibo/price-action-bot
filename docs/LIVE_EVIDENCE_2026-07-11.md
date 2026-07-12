# Canlı Kanıt — 2026-07-11

## Sonuç

Canlı/testnet ölçüm hattı, crash-complete execution lifecycle'ı, otomatik
ingest→consumer snapshotı ve rate-limit azaltımları diskte hazırdır; ancak
performans kapısı **RED**, rate-limit deploy kapısı **PENDING** durumundadır.
Mevcut veri `%10+` getiri kanıtlamaz ve yeni strateji/bot terfisine izin vermez.

ZEC doğal olarak kapandı ve son orphan algo temizlendi. Flat kapısı geçildikten
sonra v15p2 güvenli bakım restartı tamamlandı; execution/rate düzeltmeleri yeni
PID'de aktiftir. Incident 48 saatlik saha gözlemi bitene kadar kapanmış sayılmaz.

## Restart sonrası saha kanıtı — 12 Temmuz 03:00 TR

- Restart sınırı `2026-07-11T23:58:26Z`; eski PID `34731` graceful SIGTERM aldı.
- Yeni PID `53783`, startup `2026-07-11T23:59:56Z`.
- V15P2 `VERIFY_OK`; config SHA kısası `78025a394aecb807`, risk `%1`, SL min
  `%2.5`, pyramid OFF, 18 sembol ve 2 strateji.
- DMS `source=external_main_loop`, background REST `OFF`; process-long ana
  exchange client hazır.
- Startup protection rebuild borsada açık pozisyon bulmadı.
- İlk doğal bar `00:00:05Z`: scan `0`, `POS_CHECK 0 pozisyon / 0 algo`, breaker
  başarılı, equity snapshot `v15p2_15m_20260712T0000Z`.
- Wallet/equity `$4958.42500698`, unrealized `0`; rate budget `437 weight/1m`.
- Geniş 418/`-1003` sayımı restart öncesi/sonrası `66 → 66`.
- 48 saat deadline `2026-07-13T23:59:56Z / 14 Temmuz 02:59:56 TR`.

## Restart öncesi salt-okunur durum — 11 Temmuz 23:49 TR

- PID `34731`, uptime `1 gün 05:52:56`, `STAT=SN`; proses aktiftir.
- Son tarama `20:45:15Z / 23:45:15 TR`; log mtime `23:45:29 TR`.
- Bir açık pozisyon ve üç exchange-side TP/SL algo emri:
  ZEC long `1.534 @ 487.6942`, son log mark `522.2700`, log U-PnL
  `+53.04 USDT`.
- Watchdog aynı turda ZEC stopunu `510.57 → 514.44` taşıdı.
- Consecutive-loss breaker aktiftir; `19:30Z` turunda yeni ADA sinyali
  `dd_breaker_active` ile reddedildi. Günlük/haftalık/aylık breaker'lar false'tur.
- Kümülatif yerel sayaçlar: scan `716`, WIDESTOP `602`, STALE `0`, RISK `13`,
  MISSED `0`, geniş entry/fill regex eşleşmesi `52` (trade sayısı değildir).
- Caffeinate PID `1047`, `/usr/bin/caffeinate -ims`; Mac uyumaz, ekran
  kapanabilir.

Bu fotoğraf yalnız PID ve yerel logdan alındı; yeni private REST mutabakatı,
restart, emir veya pozisyon değişikliği yapılmadı. Yeni V18 adayı primary kapıyı
geçmediği için onun için prospective shadow/paper/live kanıt penceresi
başlatılmadı; bu bir eksik deploy değil, bağlayıcı güvenlik kararıdır.

## Son durable hesap snapshot'ı ve yerel live-log kanıtı

23:12:24 UTC snapshotı (10 Temmuz):

- Journal: `data/futures_journal_v15p2.duckdb`
- Snapshot ID: `da6a953a6d904608`
- Wallet: `4924.07179749 USDT`
- Unrealized PnL: `+8.59904396 USDT`
- Margin balance/equity: `4932.67084145 USDT`
- Available balance: `3422.02193353 USDT`
- Açık pozisyon: `2`
- Açık koruma emri: `6`
- Not: `manual_live_evidence_utc`

11 Temmuz 02:45 ve 03:00 UTC doğal bar turlarında PID `34731` yeniden başarıyla
taradı. Son yerel log kanıtı (`03:00:21Z`):

- NEAR short `394 @ 1.8710`, mark `1.9100`, unrealized `-15.37 USDT`
- ZEC long `1.534 @ 487.6942177`, mark `506.9523`, unrealized `+29.54 USDT`
- Her iki pozisyon için toplam altı TP/SL algo emri açık.

Bu log kanıtı yeni REST çağrısı yapılmadan okundu. 23:12 snapshot equity'si
performans hesabının durable referansıdır; 03:00 mark değerleri yeni bir hesap
snapshotı gibi sunulmaz.

## Performans kanıtı

2 Temmuz 13:07 UTC `4963 USDT` anchor sonrasında borsa income satırları:

- Realized PnL: `-32.68 USDT`
- Commission: `-8.67 USDT`
- Funding: `+2.63 USDT`
- Net realized: `-38.71 USDT`

9 Temmuz 23:13 UTC temiz P1-fix penceresi:

- Üç kapanış
- Realized PnL: `-58.91 USDT`
- Commission: `-1.48 USDT`
- Funding: `-0.01 USDT`
- Net realized: `-60.40 USDT`

Snapshot equity'si anchor'a göre `-30.32915855 USDT` (`-%0.6111`). Bu nedenle
`canlı >= %10` kapısı **FAIL / kanıt yok**.

## XLM matching-engine kanıtı ve onarım

Giriş `entry_70394c106e924cf3`:

- Maker order `543048866`: `538` adet, `104.14604 USDT`
- Taker order `543051193`: kalan miktar
- Toplam: `3845`, `746.46510 USDT`
- Ağırlıklı fill: `0.1941391677503251`
- Arrival: `0.19358`; slippage `+28.8856 bps`
- Komisyon: `0.27775675 USDT`; fee `3.7210 bps`
- Maker oranı: miktarda `%13.9922`, notional'da `%13.9519`
- Son fill zamanı: `2026-07-10 08:45:56.196 UTC`

Stop çıkışı `prot_bfa50f4db8504c03_sl`:

- Algo `1000000131496305`, actual order `544321482`
- Trigger/fill zamanı: `2026-07-10 14:19:25.043 UTC`
- Fill: `3845 @ 0.18870`, notional `725.55150 USDT`
- Trigger: `0.18834`; uzun pozisyonun satış çıkışı için fiyat iyileşmesi
  `-19.1144 bps`
- Komisyon: `0.29022060 USDT`; fee `4.0000 bps`
- Exchange realized PnL: `-20.9136 USDT`
- Tam trade neti: `-21.48157735 USDT` (entry + exit komisyonları dahil)

Execution DB ve v15p2 journal transaction içinde aynı kanıta getirildi. 10
Temmuz execution özeti artık altı fill, iki entry, dört exit, sıfır unknown;
toplam fee `1.46463743 USDT`, alarm `OK`.

Onarım öncesi açılabilir yedekler:

- `data/manual_backups/live_evidence_20260710T231848Z/execution_fills.duckdb`
  SHA-256 `a6900a56c8051e2d48a09a67611d62b35d439c9ef4ab61b21504cc14b07b473e`
- `data/manual_backups/live_evidence_20260710T231848Z/futures_journal_v15p2.duckdb`
  SHA-256 `1dc35a125614f6c999067858991bb232bfb254ede5462af561e0db42e5d5148a`

## Execution güvenliği

- LIMIT/MARKET submit belirsizliği typed metadata ile retry queue'ya gider.
- Timeout veya terminal olarak doğrulanmamış cancel sonrası yeni emir verilmez.
- Queue ana, `_fb`, `-rN` ve explicit client-order-id'leri reconcile eder.
- Fill miktarı/fiyatı yalnız order raw alanı, matching-engine `userTrades` veya
  submit-öncesi baseline'lı position delta ile kabul edilir.
- Kanıt yoksa journal ve protection yazılmaz; durable audit + CRIT üretilir.
- Aynı poll aralığındaki TP1, TP2 ve SL terminal eventleri kronolojik olarak
  ayrı execution fill + journal kaydıyla exact-once işlenir.
- Protection satırı ancak pozisyon flat, bütün terminal event kanıtları durable,
  unprocessed event sayısı sıfır ve final journal close mevcutsa retire edilir.
- Execution DB yazılıp journal yazımı çökerse deterministic replay tracker'ı
  exact-noop geçirir ve eksik journal/event zincirini tamamlar.
- Entry WAL silinmeden önce aynı identity atomik olarak
  `reconcile_only=true` / `entry_submit_allowed=false` olur; missing veya
  ambiguous delete artık raise eder.
- Aynı deterministic fill ID'nin exact/toleranslı replay'i no-op; farklı payload
  CRITICAL + exception üretir.
- Entry maker KPI'sı exit'lerden ayrıdır; mixed maker/taker miktar ve notional
  ağırlıkları korunur.
- Exit slippage işareti gerçek alış/satış execution maliyetine göre hesaplanır.
- DuckDB `TIMESTAMP` yazımları UTC-naive normalize edilir; yerel saat `+3h`
  kayması önlenir.
- Legacy 1d non-dry execution retired; daemon scan-only yüzeyinde özel API veya
  emir döngüsü yoktur.
- Vol-target konfigürasyonu strict ve config-gated'dir; pyramid production
  hard-disabled kalır.

Odaklı execution/rate/ingest/ops seçkisi: `783 passed`; bütün repo regresyonu:
`3059 passed, 136 expected skip`. Execution dizini bağımsız koşumda `535 passed`.
Runtime-safety Ruff, `compileall`, shell/plist, YAML/JSON/TOML parse, Bandit HIGH
ve `git diff --check` temizdir. Repo-geneli Ruff tarihsel araştırma/watch kodunda
`307` informational baseline bulgusu taşır; runtime blocking yüzeyi temizdir.

## E13 exit kanıtı

- Temiz kapanış: `0 / 40`
- Post-cutoff kapanış satırı: `3` (`reconcile_orphan` nedeniyle dışlanan `2`;
  pre-cutoff açılmış trade olduğu için dışlanan `1`)
- Prospective paired örnek: `0 / 40`
- Karar: `HOLD_CLEAN_SAMPLE_REQUIRED`
- Auto-promotion: `false`
- ATR shadow yalnız prospective state ve tamamlanmış yerel 15m barlarla çalışır;
  network ve emir yetkisi yoktur.
- Ingest doğal run `766`, `19/19` sembol ve exit `0` ile strict checkpoint sonrası
  `1,637,363,712` bayt / `10,611,632` satırlık snapshotı atomik yayınladı;
  source/consumer `COUNT(*)` ve `MAX(ts)` birebir eşleşti, WAL/tmp kalmadı.
- Sonraki doğal E13 run `15`, `2026-07-11T02:21:55.200552Z` anında
  `status=OK`, `bars_applied=1`, `issues=[]`, `exchange_calls=0`,
  `network_calls=0` verdi. Böylece saatlik `:05` kopyasına bağımlılık kalktı.

## Açık saha koşulları

- Running daemon yeni process image'ını kullanıyor; startup ve ilk bar kapıları
  geçti.
- Geniş 418/`-1003` eşleşmesi `66` satırdır. Restart sonrası yeni olay yoktur;
  fakat 48 saat dolmadığı için incident hâlâ gözlem durumundadır.
- DMS background private polling'i kaldıran external-main-loop heartbeat, shared
  cooldown, cooldown-aware flatten, symbol-scoped order state, process-long
  client, single-client ingest ve `RATE_BUDGET` telemetrisi yeni PID'in ilk
  barında temel saha kanıtını verdi; süre kapısı devam eder.
- 48 saatlik gözlem `2026-07-11T23:59:56Z` sınırında başladı. CEO bu sırada
  unloaded ve private erişim kapılıdır.
- Performans RED olduğu için yeni bot başlatılmadı ve hiçbir strateji otomatik
  terfi ettirilmedi.
