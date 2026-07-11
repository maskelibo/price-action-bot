# Crypto 15m v17 pairs — batch kapanış kaydı

## Karar

**RED_NO_HOLDOUT**

Üç önkayıtlı hücrenin hiçbiri primary ön-LOSO mutlak kapılarını geçmedi. Hiçbir
hücre çift seçemediği için B, C2 ve H senaryolarında işlem, aktif ay ve getiri
sıfır kaldı. Bu sonuç başarı veya düşük-risk kanıtı değildir; strateji ailesi bu
önkayıt altında uygulanabilir sinyal üretememiştir.

Gerçek LOSO ve holdout çalıştırılmadı. Eşikler sonuç görüldükten sonra
gevşetilmedi; runner-up, ensemble veya post-hoc kombinasyon denenmedi.

## Hücre sonuçları

| Hücre | H trim/ay | H DD | Kapalı çift episode | Aktif ay | Ön-LOSO |
|---|---:|---:|---:|---:|:---:|
| DP1_EG_90D_Z2P5 | 0.00% | 0.00% | 0 | 0 | FAIL |
| DP2_EG_180D_Z2P5 | 0.00% | 0.00% | 0 | 0 | FAIL |
| DP3_EG_180D_Z3_STRICT | 0.00% | 0.00% | 0 | 0 | FAIL |

## Seçim hunisi

Her hücre 60 aylık seçim tarihi × 78 primary çift = 4.680 terminal karar
üretti. Bütün kararlar reddedildi.

| Terminal neden | DP1 | DP2 | DP3 |
|---|---:|---:|---:|
| DATA_WINDOW_INELIGIBLE | 936 | 1.404 | 1.404 |
| NOT_GATEV_TOP20 | 2.784 | 2.436 | 2.436 |
| HOLM_ENGLE_GRANGER_P_ABOVE_0P05 | 952 | 836 | 836 |
| TRAINING_CORRELATION_BELOW_0P75 | 3 | 0 | 0 |
| VALIDATION_MEAN_SHIFT_ABOVE_0P50 | 3 | 2 | 2 |
| BETA_HALF_STABILITY_ABOVE_0P20 | 1 | 2 | 2 |
| VALIDATION_STD_RATIO_OUTSIDE_0P50_TO_1P50 | 1 | 0 | 0 |

DP1 için 48 veri-yeterli ayda 960 Gatev top-20 slotunun 952'si Holm-FWER'da,
kalan sekizi diğer stabilite kapılarında elendi. DP2/DP3 için 42 veri-yeterli
ayda 840 top-20 slotunun 836'sı Holm-FWER'da, kalan dördü stabilite kapılarında
elendi. Dolayısıyla asıl darboğaz, geniş aile üzerinde preregister edilmiş Holm
FWER ile sonraki stabilite kapılarının bileşimidir. Bu gözlem aynı batch içinde
eşik değiştirme yetkisi vermez.

## Kanıt kimlikleri

- Kaynak commit: `ff554e3b572197540f32054f6e801ede2458cf75`
- Raw JSON bytes: `162198487`
- Raw JSON SHA-256: `73e92a02131985a8a24c195c54c165b6775decef0ea41e24b6b34991edf4d82a`
- Deterministik gzip SHA-256: `6d9ded77ceed025b73259c44b2527caf60a9e0eacc8a21ddeb8c2990563e369d`
- Report JSON SHA-256: `ae234c398ac1390b39ac29210f92698523322687ef332e37c43243d75201a18d`
- Deterministik Markdown SHA-256: `0270d860144f91ec96617ee393afab1f012957d61bf097293f7be165f4be57ad`
- Prereg SHA-256: `52d6b0e433e4145e17c588be88d3f82bc7ecb91e281fab12fd5450db12b6cc52`
- Market snapshot SHA-256: `071768300daea9170d29bd5e35cc94795b8a500614d6e5ac4b127e459416652d`
- Funding snapshot SHA-256: `35be9ebae8f9468a6bae819054008cb4c2338ae0eb923910584dea1adc0c6b96`

Gzip decoded SHA-256 değeri raw JSON SHA-256 ile birebir doğrulandı. Raw payload
`evidence_eligible=true`, temiz kaynak, aynı pre/post kaynak hashleri ve aynı
pre/post snapshot kimlikleriyle kapandı. Rapor full 15m equity curve üzerinden
aylık return/PnL, MTM DD, recovery, aktif ay ve turnover'ı yeniden hesapladı.

Git'in 2 MiB pre-commit sınırı nedeniyle 6,8 MiB gzip dört sıralı parçaya
bölündü. Parçalar byte-concatenate edildiğinde yukarıdaki gzip SHA-256 elde
edilir:

| Parça | SHA-256 |
|---|---|
| `.json.gz.part-00` | `f6a79cca268123708500f6d2e10c9a2733aa272a52e03db1f7d3381128d8099f` |
| `.json.gz.part-01` | `81ad64343c35b965b0a5973da34fd156e62c7f6d6bbcdf39c0bdb1f1592bf516` |
| `.json.gz.part-02` | `010e9bd28655e5b4aa6c61c4c6d7e23c1387d3ce2369ef4de6ddb401c7f099c2` |
| `.json.gz.part-03` | `f64603dc38775579656f7c83fda8871ed4114c19124bcd1526ab9886441c2f1f` |

## Doğrulama ve operasyon notu

- Tüm repo: 3.224 passed, 136 skipped.
- V17 pairs hedef suite: 118 passed.
- Final adversarial audit: PASS; açık P0/P1 yok.
- Replay yaklaşık 70 dakika, tek BLAS thread ve `nice=15` ile çalıştı.
- Canlı daemon 07:00/07:15/07:30/08:00 UTC scanlarını yaklaşık 9,9–11,5 saniyede
  tamamladı; replay anlamlı scan gecikmesi üretmedi.
- Canlı position-monitor tarafında replay'den bağımsız Binance 418/IP-ban olayı
  gözlendi. Exchange'e ek manuel sorgu atılmadı ve daemon yeniden başlatılmadı.

## Sonraki izinli adım

Bu v17 çift ailesi başarısız olarak donduruldu. Aynı eşikleri gevşeterek veya
aynı sonuçları yeniden paketleyerek devam etmek yasaktır. Yeni deneme ayrı bir
önkayıt, yeni trial sayımı ve materially farklı hipotez gerektirir. Mevcut
v15p2 bot için adil `FAIR_LIVE_POLICY_PROXY` baseline replay'i de hâlâ
tamamlanmalıdır; bu yapılmadan “yeni bot mevcut bottan daha iyi” denemez.
