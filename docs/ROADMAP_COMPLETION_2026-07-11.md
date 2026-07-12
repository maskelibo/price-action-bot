# Yol haritası kapanışı — 2026-07-11

## Sonuç

Planlanan kod, araştırma ve karar çalışması tamamlandı. Hedeflenen aylık
`+%10–15`, düşük drawdown'lı yeni 15m bot **bulunmadı**; bu yüzden yeni bot
deploy edilmedi. Mühürlü gerçekçi replay'de dört V18 hücresinin tamamı RED'dir.
Sistem kârlı sonuç üretmiş gibi gösterilmeden, zayıf adayları sermayeye
taşımayacak şekilde kapanmıştır.

Mühendislik kapanışı ile saha hazır oluşu ayrıdır: araştırma/karar altyapısı
hazırdır; çalışan eski v15p2 process image'ı, aktif Binance rate incident'ı,
korumalı ZEC pozisyonu ve dış DR bağımlılıkları nedeniyle production operasyonu
tam yeşil değildir.

## Beş iş kaleminin durumu

| İş | Kapanış | Kanıt / dürüst sınır |
|---|---|---|
| Strateji ve yeni bot programı | **KAPANDI — RED** | Adil V2 baseline ile V16, V17 ve dört hücreli V18 programı tamamlandı. Yeni aday hedefi geçmedi. |
| Canlı kanıt | **V18 İÇİN KAPALI / YETKİSİZ** | Primary kazanan olmadığı için true-LOSO, shadow, paper ve live başlatılmadı. Mevcut v15p2 salt-okunur saha kanıtı güncellendi. |
| Operasyon ve kararlar | **MITIGASYON DEPLOYED; 48H GÖZLEM AKTİF** | ZEC flat ve güvenli restart geçti; yeni PID ilk barı doğruladı. 48 saat sıfır yeni rate olayı henüz dolmadı. |
| Git temizliği | **KAPANDI — CLEAN/PUSHED** | Büyük raw/shard kanıtları Git-ignore altında yerelde; manifest, hash, karar, kimlik ve taşınabilir rapor Git kapsamındadır. |
| Otonomi planı | **KAPANDI — SINIRLI YETKİ** | Faz 3–6 discovery/readiness/eval yolları hazır; promotion kilitleri V18'i doğru biçimde reddetti. Yeni scheduler/credential/order yolu açılmadı. |

## Strateji kararının sayısal özeti

V15p2 adil baseline H senaryosu son 36 tam pseudo-OOS ayda trimli aylık
`-%5.39`, `36/36` negatif ay ve `%98.27` maksimum MTM drawdown verdi.

| V18 hücresi | H trimli ay | Negatif ay | H MaxDD | Sonuç |
|---|---:|---:|---:|---|
| C1 VSA-only | `-%4.324` | 36/36 | `%79.744` | RED |
| C2 Grimes-only | `-%2.935` | 36/36 | `%68.532` | RED |
| C3 dual+HTF50 | `-%3.753` | 36/36 | `%75.918` | RED |
| C4 VSA+HTF50 | `-%2.532` | 36/36 | `%60.525` | RED |

Karar `RED_NO_PRIMARY_CELL_PASSED`; ranking ve winner yoktur. Hedefin altında
olduğu için eşikler düşürülmedi ve LOSO çalıştırılmadı.

Kanonik primary reporter, tanımsız pozitif-PnL konsantrasyon paylarını `+inf`
ürettiği için strict JSON yayını fail-closed durdurdu. 12-shard immutable bundle
evidence-eligible, kanonik report evidence'ı ineligible'dır. Gelecek koşular
için JSON-safe `null` düzeltmesi sonucu değiştirmeden ayrı commit edilmiştir.

## Restart öncesi canlı sistem fotoğrafı

11 Temmuz 23:49 TR salt-okunur kontrolü:

- PID `34731`, uptime yaklaşık `1 gün 6 saat`, son scan `23:45 TR`;
- ZEC long `1.534 @ 487.6942`, son log mark `522.2700`, U-PnL `+53.04 USDT`;
- üç exchange-side koruma emri, trailing SL `514.44`;
- consecutive-loss breaker aktif;
- geniş 418/`-1003` sayımı `66`, son olay `22:00:22 TR`;
- caffeinate `-ims` aktif;
- restart, private REST mutabakatı, emir veya pozisyon müdahalesi yapılmadı.

Bu fotoğraf daemon'un çalıştığını gösterir; yeni kodun sahada deploy edildiğini
veya rate incident'ın kapandığını göstermez.

## Restart sonrası güncelleme — 12 Temmuz 03:00 TR

- ZEC doğal kapandı; journal/log ve borsa-tarafı algo görünümü flat oldu.
- Eski PID `34731`, yeni PID `53783`; startup `23:59:56Z`.
- Config `VERIFY_OK`; DMS `external_main_loop`, background REST `OFF`.
- İlk doğal bar `0 pozisyon / 0 algo`, wallet/equity `$4958.43` ve
  `RATE_BUDGET used_weight_1m=437` verdi.
- Rate sayımı `66 → 66`; yeni olay yok.
- 48 saat kapanış deadline'ı `14 Temmuz 02:59:56 TR`.

## Git kanıt kapsamı

Git'e alınan küçük ve denetlenebilir zincir:

- V3 dataset/result prereg ve hash kimlikleri;
- V2 baseline report ve execution lock;
- V18 kodu, testleri, prereg ve result identity;
- evidence-eligible primary bundle manifesti;
- mühürlü RED incident JSON/Markdown;
- gerçek DuckDB SQL'i, report artifact JSON'i, self-contained HTML ve QA notu.

Yerelde tutulan fakat Git'e alınmayan ağır kanıt:

- V2 raw replay: yaklaşık `448 MiB`;
- 12 V18 shard: yaklaşık `1.3 GiB`.

Bu dosyalar silinmedi. Git şişirilmeden manifestteki SHA-256 değerleriyle
bağlıdır; yeniden üretim/veri zinciri dokümantedir.

## Kodla kapatılamayan veya zaman gerektiren saha kapıları

1. **PASS:** ZEC doğal flat ve runbook'a göre tek güvenli daemon restartı.
2. **ACTIVE TIME GATE:** Restarttan sonra 48 saat sıfır yeni 418/`-1003`, tutarlı protection ve
   beklenen DMS heartbeat kanıtı.
3. Gerçek `HEALTHCHECKS_PING_URL` ile dış alarm teslim drill'i.
4. Credential'lı client-side şifreli off-site backup ve yalnız off-site
   kaynaktan restore drill'i.
5. E13 için 40 temiz prospective paired kapanış.
6. Forex için güncel point-in-time feed ve observed spread.
7. Yeni bot araştırması açılacaksa ekonomik olarak farklı mekanizma, yeni
   önkayıt ve seçimden sonra başlayan bağımsız veri.

Bu kalemler sahte endpoint, sentetik kapanış, geriye dönük “OOS” veya açık
pozisyonu kesen restart ile kapatılmaz.

## Doğrulama

- V15/V18 odaklı regresyon: `207 passed`.
- Teknik rapor: 16 block, 2 chart, 3 metric, 1 table; 1440/390 px,
  source-dialog ve klavye etkileşimi PASS.
- SQL kaynağı mühürlü incident'tan tam dört aday satırı döndürdü.
- Bütün repo: `3526 passed, 136 skipped, 0 failed` (`224.00s`). Skip'ler
  opsiyonel dependency, platform ve bilinçli integration/live sınırlarıdır.
- Final Git: bu belgeyi içeren kapanış commit'i
  `origin/audit-hardreview-20260528` branch'ine push edilmiş ve tracked çalışma
  ağacı clean bırakılmıştır.

## Ana dosyalar

- `docs/STRATEGY_DECISION_2026-07-11.md`
- `docs/LIVE_EVIDENCE_2026-07-11.md`
- `docs/OPERATIONS_DECISIONS_2026-07-11.md`
- `docs/OPERATIONS_PENDING_2026-07-11.md`
- `docs/AUTONOMY_PHASE5_6_STATUS_2026-07-11.md`
- `reports/research/CRYPTO_15M_V18_PRIMARY_RED_INCIDENT_2026-07-11.md`
- `reports/research/CRYPTO_15M_V18_TECHNICAL_REPORT.html`
- `configs/crypto_15m_v18_primary_red_result_identity.json`
- `configs/crypto_15m_v18_technical_report_identity.json`
