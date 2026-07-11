---
doc_id: INC-2026-07-11-binance-testnet-rate-ban
doc_type: incident
agent_id: ops_engineer
created_at: '2026-07-10T22:56:28Z'
updated_at: '2026-07-11T03:08:50Z'
status: ACTIVE_CODE_FIXED_DEPLOY_BLOCKED
confidence: high
depends_on: []
tags: [incident, binance-testnet, rate-limit, v15p2, operations]
---

# Incident: Binance testnet HTTP 418 / `-1003` IP ban

## Etki ve son durum

- `logs/futures_daemon_v15p2.log` içinde 11 Temmuz 03:08 UTC itibarıyla **38**
  adet 418/`-1003` cevap satırı var. Hatalar `POS_CHECK`, breaker ve orphan/algo
  yollarında private REST görünürlüğünü aralıklı kaybettirdi.
- Son yeni cevap `2026-07-11T02:30:16Z`; aynı ban cevabındaki deadline
  `2026-07-11T03:00:58.690Z` (`06:00:58.690 TR`). Buna rağmen 02:45 ve 03:00
  UTC doğal turları yeniden `2 pos / 6 algo` doğruladı. Testnet deadline
  davranışı bu nedenle yalnız server cevabı olarak kaydedilir; erken recovery
  “ban bitti” garantisi değildir.
- Çalışan PID `34731` açık NEAR short ve ZEC long nedeniyle restart edilmedi.
  Diskteki düzeltmeler bu process image'ında aktif değildir.

## Timeline

| UTC | Olay | Kanıt |
|---|---|---|
| 8–10 Tem | Tekrarlayan 418/`-1003` | v15p2 daemon logu |
| 11 Tem 01:30:15 | Yeni POS_CHECK banı | deadline `01:42:59.352Z` |
| 11 Tem 01:45 ve 02:00 | Geçici recovery | `2 pos / 6 algo` |
| 11 Tem 02:15:17 | Yeni POS_CHECK banı | deadline `03:00:58.690Z` |
| 11 Tem 02:30:15–16 | Aynı ban POS_CHECK + breaker'da görüldü | toplam cevap satırı `38` |
| 11 Tem 02:45:21 | Doğal tur recovery | `2 pos / 6 algo`; yeni 418 yok |
| 11 Tem 03:00:15–28 | İkinci doğal recovery turu | scan + `2 pos / 6 algo`; yeni 418 yok |
| 11 Tem | DMS/request-weight/client-fanout denetimi ve disk fixleri | testli, deploy bekliyor |

## Doğrulanan kök katkılar

1. Çalışan eski DMS her 20 saniyede account + positions çağırıyor. Son 24 saat
   DB kanıtında 4,266 heartbeat satırının yaklaşık 4,170'i background cycle;
   tahmini 7,886–8,340 private HTTP/24 saat (`329–348/saat`). Bu, yerel private
   request adedinin yaklaşık `%90+` bölümüdür.
2. Aynı DMS thread'i heartbeat dosyasını kendi tazelediği için ana-loop stall'ini
   maskeliyor. 550 heartbeat satırı `equity=0,n_positions=0,status=alive`; exchange
   okuması başarısızken de “alive” üretildi.
3. Steady-state symbolsüz `openOrders` + `openAlgoOrders` çağrıları CCXT
   metadata'sında `40+40` weight/bar; yaklaşık `320 weight/saat`. Request adedi
   düşük olsa da yerel ağırlığın diğer büyük kaynağıdır.
4. Stale scanner fallback'i 18 sembolde paralel yeni client, canonical ingest
   ise 19 sembolde 19 client kuruyordu. Private testnet ile aynı endpoint değil,
   fakat limiter/cache parçalanması ve ortak egress burst'ü yaratıyordu.

Bu katkılar kesin kanıttır; **418'in tek nedeni oldukları kanıtlanmamıştır**.
Testnet'in gerçek kotası, response-header geçmişi ve aynı public IP'deki repo dışı
trafik bilinmiyor. Standart production limitleriyle repo trafiği tek başına banı
tam açıklamıyor; testnet-özel kota veya ortak NAT olasılığı açıktır.

## Diskte tamamlanan mitigasyon

- 15m DMS `external_heartbeat=True`: heartbeat yalnız başarılı ana bar döngüsü
  ping'inden gelir; 20 saniyelik background account/positions polling yok.
- Shared, atomik ve prosesler-arası ban deadline guard'ı; ilk 418'den sonra ban
  süresince yeni factory request'i ağdan önce kesilir.
- DMS emergency flatten aktif cooldown'u “attempt” saymaz; deadline geçince
  finite retry bütçesini koruyarak devam eder. Dict/list algo response, cancel
  hatası ve tek alarm semantiği testlidir.
- `fetch_futures_state` global order endpointlerini kaldırdı. Journal + entry WAL
  + protection-finalize queue + açık pozisyon kapsamı sembol bazlı okunur;
  kapsam okunamazsa order state `UNKNOWN`, entry/mutation fail-closed.
- Normal 15m main loop process-long tek private client kullanır; DMS emergency
  client ayrıdır ve background polling yapmaz.
- Orphan `positionRisk` ikinci okuması yalnız gerçek orphan adayı varsa yapılır.
- Scanner stale veride direct CCXT fallback açmaz. Canonical ve hourly ingest
  venue başına tek sequential client kullanır; OHLC fetch sayısı değişmez.
- Whitelist response headerları `RATE_BUDGET` satırında case-insensitive ve
  non-finite-safe loglanır.
- CEO `PA_DISABLE_PRIVATE_EXCHANGE_API=1` ile credential/client/network öncesi
  fail-closed; incident boyunca unloaded. Dashboard yalnız yerel logdan aktif
  banı ve 48 saat kapısını gösterir.

## Deploy kararı

**Restart yok.** Açık pozisyonların exchange korumalarıyla doğal kapanışı
beklenir. Bu sırada CEO, `_pnl_status_now.py`, reconcile/order-check ve diğer
manuel private sorgular çalıştırılmaz. Dashboard, ingest, E13 ve Bybit
liquidation collector çalışabilir.

## Kapanış kriterleri

1. Pozisyonlar flat olduğunda yerel journal/log kanıtı alınır ve v15p2 tek güvenli
   bakım restartıyla commit edilmiş kodu yükler.
2. Startup logunda DMS `source=external_main_loop`, background REST `OFF`, config
   paritesi ve protection rebuild görünür.
3. Heartbeat hacmi yaklaşık `178/saat`ten `4/saat`e iner.
4. Her bar `RATE_BUDGET`, `POS_CHECK`, breaker/equity ve protection sayıları
   tutarlı kalır.
5. Restart sınırından sonra **48 saat** yeni 418/`-1003` yoktur. Shared ban
   oluşursa deadline boyunca factory HTTP çıkışı sıfır olduğu kanıtlanır.
6. Bu kapılar geçince guarded CEO ayrıca açılır; private işler fail-closed kalır.

## Tekrar etme riski

**Yüksek — deploy bekliyor.** Kod ve `3059 passed` tam regresyon hazırdır; canlı
PID hâlâ eski DMS/order/client davranışını taşır. 48 saatlik saha penceresi güvenli
restarttan önce başlatılmaz.
