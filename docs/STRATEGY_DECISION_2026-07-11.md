# Strateji ve yeni bot programı — 2026-07-11 karar kaydı

## Karar

**Yeni bot üretilmedi.** İncelenen iki timeframe adayı ve yeni XS-carry
mekanizması zorunlu kapıları geçmedi. Çalışan `v15p2` daemon ve açık
pozisyonlar değiştirilmedi; hiçbir aday paper/testnet/live sürecine alınmadı.

Bu sonuç programın başarısız olduğu anlamına gelmez: yanlış pozitif üreten
karşılaştırma hataları kapatıldı ve ekonomik olarak zayıf adaylar botlaşmadan
önce elendi.

## Üretilen canonical timeframe havuzları

| TF | Trade | SHA-256 | Durum |
|---|---:|---|---|
| 30m | 272,459 | `1db8d0da411b9cd81cbb9c9cc61c3bd1ce542a9043707fd11d1a5c86db8df90d` | completeness kontrolleri geçti |
| 1h | 147,836 | `9f91639480a3cd889a9c3f9c0b4500e87c35297b31e255980b2fc8118afed312` | native-1h/SQL parity geçti |
| 4h | 33,238 | `a819ded809cae593decc43adfb4004d567b2ab9f4816657196f5a15bce9f4a24` | completeness kontrolleri geçti |

Builder 15m kaynak barları `30m/1h/4h` kovalarına bar-open etiketiyle toplar
ve eksik kovaları düşürür. `Signal`, manifest normalizasyonu ve backtest zaman
indeksi 30m dahil aynı sözleşmeye getirildi.

## TF taraması ve sağlamlık kararı

İlk ham taramada havuzlar farklı evren/tarih aralıklarına sahipti (5m/15m:
10 sembol; yeni HTF havuzları: 19 sembol). Bu karşılaştırma geçersiz sayıldı.
Runner artık bütün TF'leri sembol kesişimi ve ortak giriş tarihi penceresine
indiriyor; baseline yoksa aday üretemiyor ve ham ekran hiçbir zaman `DEPLOY`
kararı vermiyor.

Adil ham ekranda:

| Strateji | Ham sonuç | Sonraki kapı |
|---|---|---|
| Brooks failed breakout | `STAY 15m` | aday değil |
| Anchored VWAP reversal | `STAY` | aday değil |
| Engulfing continuation | `CANDIDATE 30m` | robustness → **RED** |
| VSA climax | `CANDIDATE 5m` | robustness → **RED** |

Robustness runner ortak 10 sembolü, aynı tarih penceresini ve yalnız tamamlanmış
ortak ayları kullanır. Engulfing-30m'nin post-split mean-R kazancı `%7.14`
olduğu için `%10` eşiğini geçmedi. VSA-5m kazancı `-%40.06` oldu. Her iki
verdict de **RED** ve `deployment_authorized=false`.

Geçmiş veri aday seçiminde zaten kullanıldığı için olumlu sonuçlar artık
`CANDIDATE_PASS` diye adlandırılmaz. Olabilecek en yüksek sonuç
`DESCRIPTIVE_SCREEN_PASS`'tir; bağımsız OOS veya bot üretim yetkisi değildir.
Gerçek terfi için seçim tarihinden sonra başlayan, önceden kaydedilmiş yeni veri
penceresi gerekir.

## XS-carry PRIMARY fizibilitesi

Pre-register edilen haftalık top/bottom-3, spot-hedged funding kitabı yerel
19-sembol verisiyle birebir uygulandı. Yerel evren delisting-inclusive olmadığı
için sonuç her koşulda `FEASIBILITY_NOT_PROMOTION` olarak kilitlidir.

| Metrik | Sonuç | Gate |
|---|---:|---:|
| Net yıllık getiri | `-%13.243` | `>%12` — RED |
| Brüt yıllık getiri | `+%6.626` | tanısal |
| Calendar Sharpe | `-5.951` | `>1.0` — RED |
| Newey-West t | `-10.560` | `>2.0` — RED |
| Equity MaxDD | `%46.393` | `<%15` — RED |
| BTC korelasyonu | `-0.2227` | `|rho|<0.15` — RED |
| OOS Sharpe | `-26.428` | `>0.7` — RED |
| LOSO minimum OOS Sharpe | `-38.719` | `>0.4` — RED |
| %25 borrow stres net yıllık | `-%17.397` | `>%6` — RED |
| Rank permutation p | `0.001996` | `<0.05` — PASS |

Brüt funding dispersiyonu vardır fakat aktif hafta başına `26 bp` full-turnover
işlem maliyeti ve ortalama `14.374 bp` borrow maliyeti ekonomik edge'i siler.
Pre-registered hard-terminate, negatif symbol-out sonuçları nedeniyle tetiklendi.

Raporlar:

- `reports/research/2026-07-11_xs_carry_primary_feasibility.json`
- `reports/research/2026-07-11_xs_carry_primary_weekly.csv`
- `reports/tf_robustness/` altındaki hash'li immutable RED artefaktları

## Yeniden açılma koşulu

Yeni bot programı ancak aşağıdakilerden biriyle yeniden açılır:

1. Önceden kaydedilmiş seçim cutoff'undan sonra toplanan bağımsız veri;
2. Yeni ve ekonomik olarak farklı bir mekanizma;
3. Delisting-inclusive XS-carry evreni ile aynı frozen PRIMARY testinin yeniden
   koşulması.

Kapı eşiği düşürmek, tamamlanmamış ayı eklemek veya daha geniş aday evrenini dar
baseline ile karşılaştırmak yeniden açılma sebebi değildir.
