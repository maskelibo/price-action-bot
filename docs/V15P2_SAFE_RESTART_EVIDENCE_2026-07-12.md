# v15p2 güvenli restart saha kanıtı — 2026-07-12

## Sonuç

Flat bakım kapısı geçtikten sonra v15p2 tek kez yeniden başlatıldı. Eski PID
`34731`, yeni PID `53783` oldu. Yeni process image commit
`b152f0caf508ddcafa8e26908f7ad8164cd23df5` kaynaklarını yükledi.

Restart başarılıdır; rate-limit incident kapanmış sayılmaz. Sıfır yeni
418/`-1003` için 48 saatlik gözlem `2026-07-11T23:59:56Z` anında başladı ve
`2026-07-13T23:59:56Z` (`14 Temmuz 02:59:56 TR`) anında dolacaktır.

## Flat precondition

- Son iki doğal tur: `0 pozisyon / 0 algo orders`.
- Journal open signal: `0`.
- Nonterminal protection row: `0`.
- Closed trade: `16`; kanonik realized PnL `-4.8088211 USDT`.
- Son orphan ZEC algo emri doğal olarak iptal edildi; restart öncesi borsa-tarafı
  koruma artığı kalmadı.

## Restart ve startup

| Alan | Kanıt |
|---|---|
| Restart isteği | `2026-07-11T23:58:26Z` |
| Eski PID | `34731` |
| Yeni startup | `2026-07-11T23:59:56Z` |
| Yeni PID | `53783` |
| Config | `risk_phoenix_scalp_15m_v15p2.yaml`, SHA `78025a394aecb807…` |
| Parite | `VERIFY_OK`, risk `%1`, SL min `%2.5`, 18 sembol, 2 strateji |
| DMS | `source=external_main_loop`, background REST `OFF`, timeout 30 dk |
| Exchange client | Process-long ana client hazır |
| Protection rebuild | Borsada açık pozisyon yok; doğru biçimde atlandı |
| Pyramid | Hard-OFF |

İlk kapanmış bar `00:00:05Z / 03:00:05 TR`:

- scan `0` sinyal;
- `POS_CHECK: 0 pozisyon, 0 algo orders`;
- breaker tick başarılı; yalnız consecutive breaker aktif;
- equity snapshot `v15p2_15m_20260712T0000Z`;
- wallet/equity `4958.42500698 USDT`, unrealized `0`;
- `RATE_BUDGET used_weight_1m=437`;
- toplam 418/`-1003` sayısı restart öncesi/sonrası `66 → 66`.

## Restart sırasında bulunan wrapper kusuru

İlk launchd wrapper denemesi, geniş `pgrep -f` deseninin restart orkestrasyon
shell'indeki dosya adını çalışan daemon sanması nedeniyle exit `1` verdi. Bu
sırada ikinci Python daemon, emir veya pozisyon yan etkisi oluşmadı. KeepAlive
sonraki temiz denemede PID `53783` ile doğru prosesi başlattı.

Wrapper kontrolü gerçek `python*` ucomm ve exact daemon/timeframe argv
eşleşmesine daraltıldı. Shell/compile/inspect komutlarını reddeden iki regresyon
testi eklendi; ilgili ops dosyasında `13 passed`, geniş DMS/rate/ops seçkisinde
`106 passed`.

Eski process graceful shutdown sırasında sekiz semaphore için Python
`resource_tracker` uyarısı yazdı. Yeni daemon startup'ını veya ilk barı
engellemedi; ayrı bir hijyen bulgusu olarak açık tutulur.

## Kalan saha kapısı

48 saat dolana kadar incident durumu
`DEPLOYED_48H_OBSERVATION_ACTIVE` kalır. Her doğal barda `RATE_BUDGET`, DMS
heartbeat, `POS_CHECK`, equity ve protection tutarlılığı izlenir. Guarded CEO bu
kanıt kaydında hâlâ unloaded'dır.

Makine-okunur kimlik:
`configs/v15p2_safe_restart_evidence_20260712.json`.
