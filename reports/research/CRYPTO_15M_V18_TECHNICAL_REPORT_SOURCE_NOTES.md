# Crypto 15m V18 teknik rapor — kaynak ve QA notları

## Amaç ve kitle

Bu artefakt teknik inceleme içindir. V18 primary replay'in mühürlü RED kararını
özetler; yeni bir performans sonucu, yeniden koşum veya kanonik primary report
yerine geçmez.

## Veri zinciri

1. Mühürlü karar girdisi:
   `reports/research/crypto_15m_v18_primary_red_incident_2026-07-11.json`
   (`SHA-256 c362860ad37438120734f51bd8399e192ea1254242070359f16cbf0a81fc8c77`).
2. Gerçek DuckDB sorgusu:
   `reports/research/crypto_15m_v18_technical_report_source.sql`
   (`SHA-256 2996f255fb3d2f7eee83d2bc75b272abfd3a4c2c1c1b18371686a1164857c1f2`).
3. Taşınabilir rapor girdisi:
   `reports/research/crypto_15m_v18_technical_report_artifact.json`
   (`SHA-256 473571b47737d9703144732f93768954eb98f49c4cc6194cdd74e5dceb982764`).
4. Self-contained HTML:
   `reports/research/CRYPTO_15M_V18_TECHNICAL_REPORT.html`
   (`SHA-256 0c56627c08b83b2962d41a59ab401fc95da136fde55ea81855133bbb94d87821`).

Primary bundle manifesti ayrıca evidence-eligible'dır:
`reports/research/crypto_15m_v18_primary_bundle/manifest.json`,
`SHA-256 a63ffa22d6420384ecc48fec4cb8e21aac17ceab21cc24bfa9f316836621838a`.
1,3 GiB immutable shard'lar yerelde ve Git-ignore altında tutulur; Git'e yalnız
manifest, karar, kimlik ve okunabilir teknik özet girer.

## Görsel sözleşme

| Görsel | Soru | Kodlama | Karar |
|---|---|---|---|
| H trimli aylık getiri | Her aday +%10 alt sınıra ne kadar uzak? | Aday → x; yüzde-puan → y | Dört değer de negatiftir. |
| H maksimum MTM drawdown | Her aday %15 tavana uyuyor mu? | Aday → x; yüzde-puan → y | En iyi değer bile %60,52'dir. |
| Ayrıntı tablosu | Tam sayısal lookup nedir? | Dört aday × sekiz alan | Grafiklerin exact değerlerini verir. |

Renk kategori taşımadığı için tek seri kullanılır; tablo ve açıklama her grafiğin
hemen yanında kararı söyler. Yüzdeler yüzde puanıdır.

## QA makbuzu

2026-07-11 23:54 TR doğrulaması:

- blok: 16
- grafik: 2
- metrik kartı: 3
- tablo: 1
- viewport: 1440 ve 390 px
- kaynak diyaloğu: PASS
- klavye ile kaynak etkileşimi: PASS
- dış ağ isteği: yok
- yatay taşma: yok

Paketleyicinin masaüstü runtime top-bar'ı klasik scrollbar ortamında `100vw`
nedeniyle 15 px taşmıştır. Veri veya rapor şemasına dokunmadan yalnız üretilen
HTML içinde `.analytics-top-bar` genişliği container'a sabitlenmiş, ardından
resmî portable verifier yeniden çalıştırılmıştır. Son QA yukarıdaki HTML hash'i
içindir.

Gitleaks, self-contained okuyucunun gzip+base64 satır `1773` içindeki rastgele
baytlarını `facebook-page-access-token` olarak sınıflandırdı. Satırın paketlenmiş
runtime blob'u olduğu doğrulandı ve yalnız bu path/rule/line fingerprint'i
`.gitleaksignore` içine alındı; rapor JSON/SQL/Markdown kaynakları normal secret
taramasından geçmeye devam eder.

## Fail-closed sınırlama

Kanonik primary reporter, pozitif aylık PnL toplamı sıfır olduğunda iki tanısal
konsantrasyon payını `+inf` üretmiş ve strict JSON yayını durdurmuştur. Bu yüzden
teknik raporun snapshot durumu `partial` ve kanonik report evidence'ı
ineligible'dır. Immutable 12-shard bundle ve mühürlü RED karar artefaktı
eligible'dır. Serializer'ın gelecekteki koşular için `null` düzeltmesi ayrı bir
commit'tir; V18 sonucu yeniden yazılmamış veya yeniden çalıştırılmamıştır.
