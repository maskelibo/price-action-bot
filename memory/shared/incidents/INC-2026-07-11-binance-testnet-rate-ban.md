---
doc_id: INC-2026-07-11-binance-testnet-rate-ban
doc_type: incident
agent_id: ops_engineer
created_at: '2026-07-10T22:56:28Z'
updated_at: '2026-07-12T00:03:55Z'
status: MITIGATION_DEPLOYED_48H_OBSERVATION_ACTIVE
confidence: high
depends_on: []
tags: [incident, binance-testnet, rate-limit, v15p2, operations]
---

# Incident: Binance testnet HTTP 418 / `-1003` IP ban

## Etki ve son durum

- Restart öncesi geniş 418/`-1003` sayımı **66** idi; son olay
  `2026-07-11T19:00:22Z` sırasında ZEC eski stop iptal yolunda görüldü.
- NEAR ve ZEC doğal olarak kapandı; son orphan algo emri temizlendikten sonra
  log ve journal `0 pozisyon / 0 algo`, open signal `0`, nonterminal protection
  `0` doğruladı.
- Eski PID `34731` `2026-07-11T23:58:26Z` anında graceful SIGTERM aldı. Yeni
  PID `53783` `23:59:56Z` anında commit `b152f0c` kaynaklarıyla başladı.
- İlk doğal bar `00:00:05Z`: `0 pozisyon / 0 algo`, DMS
  `source=external_main_loop`, background REST `OFF`, equity `$4958.43` ve
  `RATE_BUDGET used_weight_1m=437`. Rate sayımı `66 → 66`; yeni olay yok.
- Incident artık deploy-blocked değildir; **48 saatlik saha gözlemi aktiftir**.
  Kapanış deadline'ı `2026-07-13T23:59:56Z` (`14 Temmuz 02:59:56 TR`).

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
| 11 Tem 22:30–23:30 | ZEC kapandı, orphan temizlendi, flat teyit edildi | `0 pos / 0 algo`; journal kapalı |
| 11 Tem 23:58:26 | Güvenli restart sınırı | PID `34731` graceful SIGTERM |
| 11 Tem 23:59:56 | Yeni image başladı | PID `53783`, V15P2 `VERIFY_OK` |
| 12 Tem 00:00:05–06 | İlk sağlıklı bar | `0/0`, equity `$4958.43`, rate budget `437` |

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

**Mitigasyon deploy edildi.** Flat bakım kapısından sonra tek güvenli restart
tamamlandı. Guarded CEO bu kanıt anında unloaded kalır; manuel private
reconcile/order-check ile 48 saatlik pencere kirletilmez. Dashboard, ingest, E13
ve Bybit liquidation collector yerel/public sınırlarında çalışabilir.

İlk wrapper denemesinde geniş `pgrep -f` orkestrasyon shell'indeki daemon dosya
adını yanlış eşleştirdi ve exit `1` verdi. İkinci Python daemon veya emir yan
etkisi oluşmadı; KeepAlive sonraki denemede doğru PID'i başlattı. Wrapper gerçek
Python ucomm + exact argv selectorüyle sertleştirildi ve `13` focused test geçti.

## Kapanış kriterleri

1. **PASS:** Flat journal/log ve tek güvenli restart.
2. **PASS:** DMS `source=external_main_loop`, background REST `OFF`, config
   paritesi, flat protection rebuild.
3. **OBSERVING:** Heartbeat hacmi yaklaşık `178/saat → 4/saat`; tam saat örneği
   henüz oluşmadı.
4. **FIRST BAR PASS / OBSERVING:** `RATE_BUDGET`, `POS_CHECK`, breaker/equity ve
   protection tutarlı.
5. **PENDING TIME GATE:** Başarılı startup sınırından **48 saat** yeni
   418/`-1003` yok. Deadline `2026-07-13T23:59:56Z`.
6. **DEFERRED:** Bu kapılar geçince guarded CEO ayrıca değerlendirilir; private
   işler fail-closed kalır.

## Tekrar etme riski

**Orta — mitigasyon canlı, gözlem tamamlanmadı.** Yeni PID doğru
DMS/order/client davranışını taşır ve ilk bar temizdir. Tekrar riski ancak 48 saat
sıfır yeni rate olayı ve beklenen heartbeat hacmi görüldüğünde düşürülecektir.

Makine-okunur restart kimliği:
`configs/v15p2_safe_restart_evidence_20260712.json`.
