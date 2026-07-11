# Crypto 15m V18 — primary RED ve raporlama olayı

## Teknik özet

**Yeni bot adayı çıkmadı.** Dört önkayıtlı hücrenin tamamı gerçekçi H
senaryosunda negatif kaldı, 36/36 ayı negatif kapattı ve `%60,52–%79,74`
arasında pseudo-OOS MTM drawdown üretti. En az kötü hücre
`C4_VSA_HTF50` olsa da trimli aylık getirisi `-%2,53`; hedef `+%10–15` idi.
Ranking boştur, kazanan yoktur ve true-LOSO çalıştırılmaz.

12 shard ve manifest eksiksiz/eligible üretildi. Kanonik reporter bütün
finansal, sinyal, provenance ve gate kontrollerini tamamladı; ancak tüm
adaylarda pozitif H ay PnL toplamı sıfır olduğu için iki konsantrasyon payı
`+inf` oldu. Gate bu değerleri zaten fail-closed reddetti, fakat strict JSON
yayını `inf` kabul etmedi. Bu nedenle kanonik primary JSON/Markdown
oluşturulmadı. Olay sonucu iyileştirmez; tersine kanıt statüsünü daha
muhafazakâr yapar.

## H pseudo-OOS sonucu hedefin açıkça altında

| Hücre | Kapalı trade | Trimli ay | Medyan ay | Bootstrap alt sınır | Negatif ay | En kötü ay | MTM DD | Gate |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| `C1_VSA_ONLY` | 1.773 | -%4,324 | -%3,965 | -%4,786 | 36/36 | -%7,956 | %79,744 | RED |
| `C2_GRIMES_ONLY` | 1.797 | -%2,935 | -%2,675 | -%3,469 | 36/36 | -%8,502 | %68,532 | RED |
| `C3_DUAL_HTF50` | 1.828 | -%3,753 | -%3,745 | -%4,282 | 36/36 | -%8,463 | %75,918 | RED |
| `C4_VSA_HTF50` | 962 | -%2,532 | -%2,498 | -%2,828 | 36/36 | -%5,292 | %60,525 | RED |

Baseline H de trimli `-%5,39`, medyan `-%5,01`, 36/36 negatif ay ve tam
dönemde `%98,27` DD üretti. Filtreler kaybı ve DD'yi azalttı; ekonomik edge'i
pozitife çeviremedi. “Baseline'dan daha az kötü” olmak yeni bot üretmek için
yeterli değildir.

## Kararı tek bir metrik değil, çok sayıda bağımsız kapı taşıyor

Her hücre; H trim/medyan/bootstrap, negatif ay, C2 getiri, B ve stres DD,
walk-forward fold, ekonomik edge, long/short yön, trade/ay konsantrasyonu ve
çoklu-test kapılarının büyük bölümünü kaybetti. İlk üç hücre 25, C4 24 ayrı
kontrolde başarısız oldu. Dolayısıyla `+inf` temsil sorunu giderilse bile
ranking boş ve karar yine `RED_NO_PRIMARY_CELL_PASSED` olur.

## Ölçüm kapsamı ve yöntem

- Evren: 13 Binance USD-M araştırma proxy sembolü, 15 dakikalık barlar.
- Kesintisiz replay: `[2021-06-01, 2026-06-01)`; development 24 ay,
  historical pseudo-OOS 36 ay.
- H maliyet modeli: fill başına 28,5 bp; pozitif fiyat PnL `0,50×`, negatif
  fiyat PnL `1,25×`; gözlenen funding olayları dahil.
- Adaylar: VSA-only, Grimes-only, dual+nedensel günlük SMA50 ve
  VSA+nedensel günlük SMA50.
- Çoklu seçim kontrolü: seed 18 sign-flip, yerel/cumulative Holm, 13-deneme
  DSR floor ve 6-slice CSCV/PBO.
- Bundle: 12 bağımsız replay, tek market/funding load, tek baseline sinyal
  üretimi, manifest-last yayın.

## Sınırlama ve sağlamlık yorumu

Bu tarihsel dönem daha önceki araştırmalarda görüldüğü için bağımsız
prospective OOS değildir. Next-open ve sabit maliyet modeli gerçek order-book
queue/latency replay'i değildir. Buna rağmen sonuç sınırda değil: bütün
adaylarda tüm aylar negatif ve DD çok yüksektir. Daha gerçekçi canlı friksiyon
bu sonucu hedefe doğru çevirecek bir mekanizma sunmaz.

Kanonik report serialization başarısızlığı ayrı bir yazılım kusurudur.
Immutable bundle eligibility'sini bozmaz, fakat kanonik report evidence'ını
oluşmadan bırakır; bu yüzden karar yalnız daha muhafazakâr olabilir, asla
promotion'a dönemez.

## Sonraki karar

1. V18 için true-LOSO, prospective shadow, paper ve live süreçleri açılmaz.
2. `v15p2` canlı daemon bu araştırma nedeniyle değiştirilmez veya restart
   edilmez.
3. Non-finite konsantrasyon değeri gelecekte strict JSON-safe `null` olarak
   temsil edilirken gate'in fail-closed davranışı korunmalıdır; bu düzeltme
   V18 sonucunu yeniden yorumlama veya yeni trial sayılmaz.
4. Yeni araştırma ancak ekonomik olarak farklı bir mekanizma ve yeni önkayıtla
   başlatılır; eşik düşürme ya da bu dört hücreyi yeniden karıştırma yapılmaz.
