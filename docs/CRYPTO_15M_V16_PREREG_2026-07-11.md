# Crypto 15m v16 araştırması — sonuç öncesi kayıt

## Amaç

Yeni program, 15 dakikalık Binance kripto verisinde long/short çalışan ve canlıya
aktarımı mevcut v15p2'den daha savunulabilir bir motor arar. `%10–15/ay` ve düşük
DD bir optimizasyon hedefi değil, sonuç görüldükten sonra değiştirilemeyen kabul
kapısıdır. `%15` üzerindeki getiriye seçim puanında ek ödül verilmez; istikrar ve
DD öne geçer.

Bu belge aday sonuçları çalıştırılmadan önce yazıldı. Makine sözleşmesi
`configs/crypto_15m_v16_research_prereg.yaml` dosyasındadır.

## Neden mevcut `%21.36/ay` başlığı hedef değil

Eski v15p2 replay'i yeniden üretilebiliyor; fakat eski Haziran trade-pool'larını,
ay başında sıfırlanan sermayeyi ve canlıyla aynı olmayan exit/state yolunu
kullanıyor. Pool sonucu zaten maliyet içerirken ayrıca `57 bps` düşülmesinin
bileşenleri ayrışmıyor. Foldlar örtüşüyor, ay sınırını aşan işlemlerin gelecekteki
R sonucu giriş ayına yazılıyor, evren günümüzün hayatta kalan sembollerinden
oluşuyor ve `instruments` tablosu boş. Son canlı durable snapshot hedefi
geçmediği için backtest rakamı canlı beklenti sayılmaz.

Bu araştırmada yeni aday ancak aynı snapshot, aynı bar-event motoru ve aynı
maliyetlerle yeniden kurulmuş v15p2 kontrolünü Pareto-geçerse “daha iyi” diye
adlandırılabilir.

## Ön kayıtlı iki mekanizma

1. **Residual cross-sectional trend:** Her varlığın getirisi yalnız geçmiş
   barlarla hesaplanan BTC betasından arındırılır. Bir, iki ve dört haftalık
   residual trend sıralamasında ilk/son üç varlık haftalık, dengeli long/short
   kitap olarak açılır. Emir kararı tamamlanmış 15m barında, giriş sonraki
   kesintisiz 15m açılışındadır. Funding alpha değil gerçekleşen maliyettir.
2. **Funding-confirmed residual reversion:** 24 saatlik BTC-residual hareket,
   yalnız aynı yöndeki funding kalabalığıyla birlikte aşırıysa ters yönde işlem
   aranır. `z=2.0/2.5` ve `4h/8h` olmak üzere üç hücre önceden kaydedilmiştir.

Toplam altı hücre vardır. Yeni eşik, post-hoc filtre veya seçilmiş hücre
kombinasyonu bu batch'e eklenemez. Bir ensemble ancak ayrı bir ön kayıtla test
edilebilir.

## Ekonomik dayanak ve karşı kanıt

- Kriptoda güçlü momentum kanıtı esasen haftalık horizonlardadır; bu nedenle
  alpha haftalık, emir zamanı 15m seçildi. [Liu ve Tsyvinski, RFS
  2021](https://doi.org/10.1093/rfs/hhaa113), [Liu, Tsyvinski ve Wu, JF
  2022](https://doi.org/10.1111/jofi.13119).
- Fiyat ve hacim trend bileşenlerinin liquid coinlerde de çalışabildiğini
  bildiren çalışma haftalık yeniden dengeleme kullanır; burada karmaşık ML
  yerine üç sabit residual horizon denenir. [Fieberg vd., JFQA
  2025](https://doi.org/10.1017/S0022109024000747).
- Gerçekçi likidasyon ve maliyet varsayımları altında cross-sectional momentum
  kanıtının kaybolabildiğine dair güçlü karşı kanıt vardır. Bu nedenle sonuçlar
  `B`, iki kat maliyet `C2` ve kazancı yarıya/kaybı büyüten `H` altında birlikte
  geçmek zorundadır. [Han, Kang ve Ryu](https://ssrn.com/abstract=4675565).
- Intraday kriptoda momentum ve reversal aynı anda, jump ve likidite rejimine
  bağlı görülebilir; funding-confirmed reversal bu koşullu mekanizmayı sınırlı
  hücreyle sınar. [Wen vd., 2022](https://doi.org/10.1016/j.najef.2022.101733).
- Funding/basis kalıcı bir risk primi taşısa da kaldıraç ve likidasyon riski
  büyüktür; bu program funding'i tek başına alpha saymaz. [BIS Crypto Carry
  çalışması](https://www.bis.org/publ/work1087.pdf).
- Survivorship ve delisting dönüşleri momentum sonucunu değiştirebilir. Yerel
  evren delisting-inclusive olmadığı için olumlu tarihsel sonuç en fazla
  `FEASIBILITY_NOT_PROMOTION` olabilir. [Liebi'nin survivorship
  çalışması](https://www.sebastianstoeckl.com/publications/wp2022_liebi_survivorship/).

## Donmuş veri ve gizli sembol kontrolü

- OHLCV snapshot SHA-256:
  `071768300daea9170d29bd5e35cc94795b8a500614d6e5ac4b127e459416652d`
- Funding snapshot SHA-256:
  `35be9ebae8f9468a6bae819054008cb4c2338ae0eb923910584dea1adc0c6b96`
- Tam aylar: Haziran 2021–Mayıs 2026.
- İlk 24 ay development; sonraki 36 ay altı örtüşmeyen 6 aylık expanding
  pseudo-OOS fold. Bunlar geçmişte görülmüş veri olduğundan bağımsız OOS diye
  sunulmaz.
- Dört likidite-katmanlı trade holdout'u sonuçtan bağımsız hash kuralıyla
  seçildi: `XLM`, `AAVE`, `TRX`, `XRP`. İlk mekanik seçim üst katmanda BTC idi;
  ancak BTC residual hesabının sabit referansı olduğundan işlem göremez. Sonuç
  çalıştırılmadan yapılan bu görünür amendment ile aynı katmanın sıradaki hash'i
  XRP seçildi; BTC yalnız piyasa referansı olarak kalır.
- Gerçek prospective pencere bu ön kaydın `2026-07-11T03:35:09Z` cutoff'undan
  sonra başlar.

## Dürüst maliyet ve canlı-haircut

Tek bacak round-trip temel maliyet `57 bps`; fee, spread/slippage ve impact ayrı
nakit akışlarıdır. Funding gözlenen eventlerde ayrıca uygulanır. `C2` bütün
maliyetleri ikiye katlar. `H`, temel maliyet altında pozitif trade nakit akışını
`×0.50`, negatif trade nakit akışını `×1.25` yapar. İlk haircut sonuçtan sonra
değiştirilemez; ancak en az altı tam canlı ay ve 100 eşleşmiş kapanıştan sonra
%90 alt güven sınırıyla yeniden tahmin edilebilir ve `0.75` üstüne çıkamaz.

## Kapanış kapısı

Ana `H` kapısı 36 pseudo-OOS ayda `%10` trimli ortalama, `%8` medyan, en fazla
4 negatif ay, en fazla 3 adet `<-%1` ay ve en kötü ay `>=-%6` ister. `C2` altında
trimli ortalama `%8`, medyan `%6`; MTM DD temel senaryoda `%15`, stres/haircut'ta
`%20` tavanındadır. En iyi ay/trade/sembol katkısı, iki yön, leave-one-symbol-out,
holdout, block bootstrap, Holm, DSR ve PBO kapıları da birlikte geçmelidir.

Hard gate geçmezse eşik düşürülmez; sonuç **RED** yazılır. Gate geçse bile bu
yalnız tarihsel fizibilitedir. Canlı kanıt, cutoff sonrasındaki matched signal ve
fill'lerle başlar.
