# V15P2 Binance 418 rate-limit denetimi — 2026-07-11

## Karar

Durum **yüksek riskli fakat bakım restartı için henüz güvenli değil**. Çalışan
PID `34731`, rate-limit düzeltmelerinden önce başlamış eski process image'ıdır.
Diskteki düzeltmeler çalışan sürece yüklenmemiştir. Son yerel kanıtta NEAR short,
ZEC long ve bunları koruyan altı exchange-side algo order vardır. Bu nedenle
pozisyonlar ve korumalar güvenle kapanmadan restart, manuel private sorgu,
order-cancel, IP/VPN değiştirme veya market-flatten yapılmayacaktır.

Bu denetim salt okunur yürütüldü. Borsaya API çağrısı gönderilmedi, daemon
restart edilmedi ve canlı state değiştirilmedi.

## Yerel kanıt zinciri

- PID `34731`, 2026-07-10 14:56 UTC'de; rate-limit düzeltmesi `265cad8` ise
  2026-07-11 03:02 UTC'de oluşturuldu. Çalışan process bu commit'i içeremez.
- 07:30:16 UTC'de HTTP 418 görüldü; sunucu deadline'ı `08:55:58Z` idi
  (`logs/launchd/futures_v15p2.stderr.log`, satır 4917).
- 07:45 tick'inde `2 pos / 6 algo` okunabildi; aynı tick'in ikinci G19/breaker
  state turu tekrar 418 aldı (satırlar 4921 ve 4923).
- 08:00'de deadline dolmadan yeniden private REST denendi ve tekrar 418 alındı
  (satır 4927).
- 08:15'teki son yerel state kanıtı yine NEAR/ZEC ve altı algo order gösterdi
  (satır 4931). Aradaki başarılı cevap banın kesin bittiğini kanıtlamaz.

## Kanıtlanan yerel yük büyütücüler

1. Eski Dead Man's Switch yaklaşık her 20 saniyede account ve positions okuyor.
   Son tam saatte 178 heartbeat'in yaklaşık 174'ü background turudur: yaklaşık
   348 private request/saat.
2. Eski `fetch_futures_state`, symbolsüz `openOrders` ve `openAlgoOrders`
   uçlarını çağırıyor. Kurulu CCXT metadata'sında her ikisinin `noSymbol`
   ağırlığı 40'tır.
3. Aynı 15m tick içinde position-check ve G19/breaker için iki tam state turu
   oluşuyor. Yalnız iki global-order endpoint'i başarılı bir barda yaklaşık
   160 weight, saatte yaklaşık 640 weight üretir.
4. Çağrı yolları ayrı CCXT client'lar kurduğu için client-local limiter ve
   time-sync yükü paylaşılmıyor.
5. 418 iç bloklarda yutuluyor; ana döngü `TICK_DONE` yazıp genel hata sayacını
   sıfırladığı için exponential backoff devreye girmiyor. Eski DMS de exchange
   okuması başarısızken heartbeat'i yenileyerek outage'ı maskeleyebiliyor.

Testnet'in gerçek kota politikası ve aynı public IP'deki repo dışı trafik
bilinmediği için tek-neden iddiası yapılmaz. Buna karşılık yerel self-amplifying
fanout ve ban deadline'ı içinde süren denemeler doğrudan kanıtlıdır.

## Diskte hazır korumalar

`265cad8` ve güncel çalışma ağacında şu mekanizmalar vardır:

- prosesler arası paylaşılan 418/429 deadline circuit-breaker;
- ana daemon için process-long tek CCXT client;
- order okumalarında symbol-scope;
- DMS background REST poll kapalı, ana döngüden beslenen external heartbeat;
- cooldown sırasında private REST'i kesen fail-closed yollar.

Bu kodların varlığı çalışan PID'in korunduğu anlamına gelmez; güvenli bakım
restartı gereklidir.

## Kilitli bakım ve kapanış kapısı

1. Üç ardışık tam state kanıtında `0 pos / 0 algo` görülmeli ve journal iki
   episode'un kapandığını doğrulamalıdır.
2. Yalnız bundan sonra tek kontrollü maintenance restart yapılmalıdır.
3. Yeni startup'ta `external_main_loop`, `background REST poll=OFF`,
   process-long client ve `RATE_BUDGET` imzaları doğrulanmalıdır.
4. Restart sonrası deadline içermeyen 418/429 için `Retry-After` veya kalıcı
   exponential+jitter cooldown ayrıca eklenmelidir.
5. 48 saat boyunca yeni 418 olmadan olay kapatılmamalıdır.
6. Orta vadede position/order state user-data websocket'ten tutulmalı; REST
   startup, websocket reconnect ve düşük frekanslı symbol-scope reconciliation
   ile sınırlandırılmalıdır. Websocket stale olduğunda yeni giriş fail-closed
   olmalı, mevcut exchange-side korumalar otomatik iptal edilmemelidir.

## Operasyonel sınıflandırma

- Yeni giriş güveni: **DEGRADED / fail-closed tercih edilir**
- Mevcut exchange-side korumalar: **yerinde bırak**
- Restart yetkisi: **kapı sağlanana kadar BLOKE**
- Düzeltmenin canlı kanıt durumu: **uygulanmadı**
- Olay kapanış koşulu: **güvenli restart + 48 saat 418'siz çalışma**
