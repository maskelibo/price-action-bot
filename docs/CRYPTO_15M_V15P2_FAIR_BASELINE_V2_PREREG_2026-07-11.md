# v15p2 adil baseline V2 — V3 snapshot köprüsü

Bu belge bir strateji değişikliği değildir. V1 ön-kaydının sinyal, motor,
maliyet, risk, portföy, rapor, evren ve zaman sözleşmeleri aynı kimlikle
korunur. V2 yalnızca kapsama nedeniyle çalışamayan eski OHLCV dosyasını,
başarıyla üretilmiş ve bağımsız olarak denetlenmiş Binance USD-M 15m V3
snapshot'ına bağlar.

Makine sözleşmesi
`configs/crypto_15m_v15p2_fair_baseline_v2_prereg.yaml` dosyasındadır. V1
ön-kayıt, V1 kapsama başarısızlığı ve ek attestasyon değiştirilmemiştir. V2
onları tam byte ve SHA-256 kimlikleriyle predecessor olarak kullanır. Bu köprü
yazılırken baseline replay, sinyal üretimi, engine, ROI, drawdown veya aylık
getiri hesabı çalıştırılmadı; alpha sonuç denemesi sayısı sıfır kaldı.

## Donmuş V3 piyasa verisi

- Protokol: `e6995f2fa22158d9133b9d3a45caeb0ba3de01ad70e77239d99bb13331bef3c8`
- Rezervasyon: `5c28272dc96d6e14eb471a37e8b4e7bd97cee3983f22c62e5c6e4cf6241ae404`
- Başarı kimlik mührü: `8e73f05d87106ea9df635e3ae0d3996ec5679da48f83bff77856b065059972d3`
- Build evidence: `1ac74ceb61c197fad4bc27783eadaed4e88504e3a751257d8c735bc9eece9b34`
- Market DB: `50e5b240e6babeb3b7ceadc0ae007ededc0ae589cba931e3603d233cec693eb8`,
  `181.415.936` byte ve `2.586.624` benzersiz primary-key satırı.

V3 hiçbir resmi boşluğu doldurmaz. SOL, ZEC, NEAR ve FIL için iki resmi vendor
boşluğu aynen korunur: `[2022-02-26, 2022-03-01)` ve
`[2022-04-01, 2022-04-03)` UTC. Toplam eksik anahtar sayısı `1.920`'dir.
Sinyal sözleşmesi her timestamp kopuşunda özellik state'ini sıfırlar ve yeniden
500 kesintisiz 15m bar bekler. Forward-fill, interpolasyon, resample veya
sentetik bar yoktur.

## Funding ayrımı ve sınırlama

Funding snapshot V3 market builder tarafından üretilmedi. V1'deki bağımsız
donmuş dosya aynı kimlikle korunur:
`data/backups/20260711/funding.duckdb`, SHA-256
`35be9ebae8f9468a6bae819054008cb4c2338ae0eb923910584dea1adc0c6b96`,
`17.575.936` byte. Dosya replay öncesi ve sonrasında ayrıca doğrulanır ve yalnız
read-only açılır.

Bu funding dosyası için V3 vendor-lock, arşiv checksum'u veya yeniden üretim
lineage'i iddia edilmez. Raw kesirli event timestamp'leri korunur; market
kapsaması doğrulanmadan funding veritabanı açılmaz. Her sonuç bu sınırlamayı
`funding_snapshot_not_rebuilt_under_v3_vendor_lineage` etiketiyle açıklamak
zorundadır.

V2 ön-kayıt dondurulmadan önce funding dosyası yalnız read-only
schema/count/min-max/duplicate/nonfinite aggregate kapsam denetimi için açıldı.
Değerlendirme penceresindeki primary-13 toplamı `71.289` satırdır; ilk event
`2021-06-01T00:00:00.001Z`, son event `2026-05-31T16:00:00.004Z`'dir.
Duplicate symbol-timestamp `0`, nonfinite funding rate `0`, geçerli mark-price
bulunmadığı için engine fallback'ı gerektiren satır `34.486`'dır. Hiçbir tekil
funding-rate veya mark değeri görülmedi; sinyal, trade, return, ROI, drawdown,
aylık metrik veya scenario sonucu üretilmedi. Bu aggregate denetim funding
serisinin eksiksiz olduğu iddiası değildir ve hiçbir politika seçimini
değiştirmedi.

V2 coverage diagnosis kimliği doğrudan
`b2a50fdb00c055aef8ec09b1c81e662160917878ac797b2dae966e661b745e91`
olarak bağlanır. Vendor lock ve builder kaynak zinciri ayrıca V3 başarı mührü
üzerinden transitive olarak korunur.

## Yetki sınırı

Bu ön-kayıt deploy, live veya shadow yetkisi vermez. Baseline sonucu tek başına
deployment kararı olamaz. V3 protokolü, rezervasyonu, başarı mührü, build
evidence'i, market DB ve funding DB kimlikleri herhangi bir DB bağlantısından
önce ve replay sonrasında yeniden doğrulanmadan sonuç kanıt kabul edilemez.
