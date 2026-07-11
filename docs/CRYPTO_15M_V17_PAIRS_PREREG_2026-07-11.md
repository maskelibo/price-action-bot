# Crypto 15m v17 dynamic-pairs — sonuç öncesi kayıt

## Amaç ve dürüst beklenti

v16 Batch 1'de üç BTC-residual trend ve üç funding-confirmed reversion hücresi
temel maliyette bile negatif kaldı. Yalnız 4 haftalık trendin 36 aylık ham fiyat
edge'i `+$193` idi; aynı işlemlerin execution maliyeti `$2.494` oldu. Bu nedenle
eşik ayarı veya post-hoc sembol/yön filtresi yapılmayacak.

v17 ayrı bir mekanizmayı sınar: aylık seçilen, cointegrated iki varlığın donmuş
spread sapmasını atomik olarak mean-revert etmek. Üç hücre sonuç görülmeden
`configs/crypto_15m_v17_pairs_prereg.yaml` içinde kilitlendi.

`%10–15/ay`, düşük DD ile yıllık yaklaşık `%214–435` bileşik getiri demektir.
Bu seviye düşük devirli market-neutral pairs için makul planlama beklentisi
değildir; zorlayıcı bir falsification kapısıdır. Net `%1–3/ay` ekonomik olarak
güçlü sayılabilir ama bu batch'i GREEN yapmaz.

## Mekanizma

Her hücre ayın ilk Pazartesi günü, yalnız o ana kadar tamamlanmış saatlik
barlarla çalışır. Train ve onu izleyen 28 günlük validation pencereleri seçim
tarihinden önce biter. Normalize fiyat SSD'si en düşük 20 çift Gatev ön
filtresine girer. Getiri korelasyonu, Engle–Granger + Holm, residual half-life,
iki yarı beta stabilitesi, validation mean/std ve BTC-beta kapılarının tamamını
geçen en fazla üç sembol-çakışmasız çift seçilir.

Bir saatlik gözlem dört tam ve bitişik 15m bar ister; close `:45` barının close'u,
volume dört barın toplamıdır. Getiri yalnız tam bir saat aralıklı closeların log
farkıdır. Gatev fiyatı ilk training close'una bölünür ve SSD iki normalize fiyat
farkının ortalama karesidir. Irregular timestampler sıkıştırılıp yan yana
getirilmez: training'de en uzun bitişik saatlik block (eşitlikte en güncel) en az
pencerenin `%95`i; validation'da selection'a bitişik suffix en az `%95` olmalıdır.
AR(1), yalnız bitişik saatlerde
`ε_t=c+φ ε_{t-1}` OLS; half-life `-ln(2)/ln(φ)` olarak hesaplanır. Train ve
validation standard deviation `ddof=0` kullanır; mean touch crossing sayılmaz.

SSD top-20 yalnız eligibility/ranking filtresidir; Holm ailesi bununla
daraltılmaz. Primary'de o ay veri yeterliliğini geçen 78'e kadar unordered
çiftin tamamının Engle–Granger p-değeri aynı cell-month ailesinde düzeltilir.

Regression `log(y)=α+βlog(x)` biçimindedir. `α`, `β`, validation residual
ortalaması ve standard deviation değeri seçim ayı boyunca donar. BTC yalnız risk faktörü
referansıdır ve işlem göremez. Primary seçim yalnız 13 primary sembolde yapılır;
holdout açılırsa aynı algoritma yalnız dört holdout sembolünde sıfırdan çalışır.

İlk implementasyon veya aday sonucu görülmeden istatistik sözleşmesi de
sabitlendi: Engle–Granger `trend='c'`, `maxlag=24`, `autolag='aic'` kullanır.
Pair BTC betası training saatlik getirilerinde
`abs(cov(w_y*r_y-w_x*r_x,r_BTC)/var(r_BTC))` olarak hesaplanır ve `0.15`i
geçemez.

## Causal execution

Entry yalnız saatlik checkpoint'te ve son dört tamamlanmış 15m close aynı yönde
eşik dışında kaldığında doğar. Karar close'da, iki bacak birlikte sonraki
kesintisiz 15m open'da girer; tek bacak eksikse ikisi de reddedilir. Yüksek
spread `short y / long x`, düşük spread tersidir.

Kayıtlardaki `decision_ts`, tamamlandığı anda karar verilen `:45` barının open
etiketidir; gerçek karar anı ve iki bacağın ortak entry barı `decision_ts+15m`
olan `:00` open'dır. Entry z değeri disaster eşiğine ulaşmış veya onu geçmişse
risk paydası pozitif kalmayacağı için işlem reddedilir.

Decision-close intent yalnız provisional'dır. İki gerçek entry open fiyatından
`fill_z` yeniden hesaplanır; aynı spread yönünde entry eşiğinin hâlâ dışında ve
disaster eşiğinin içinde değilse iki leg de reddedilir. Expected edge, ekonomik
kapı ve risk paydası fill-z ile yeniden hesaplanır. Bir leg `%15` capa çarparsa
hedge bozulmaz; iki leg aynı factor ile küçültülür.

Her pair episode NAV'ın `%0.5` riskini kullanır; `%6` DD sonrası yeni risk yarıya
iner. Her leg NAV'ın `%15`iyle, portföy üç çift/altı leg ve `3×` leverage ile
sınırlıdır. Partial, pyramid ve tek-leg taşıma yoktur.

Mean, disaster-z, 48 saatlik structural break, max-hold, monthly deselection ve
data-gap exitleri iki bacağı sonraki open'da birlikte kapatır. Funding her legde
gerçek event cashflow'dur. `H` haircut ayrı bacaklara değil atomik pair fiyat
PnL'ine uygulanır.

## Maliyet edge kapısı

İki bacağın dört fill'i nedeniyle temel maliyet gross exposure'ın `57 bps`i,
`C2` maliyeti `114 bps`idir. Son üç bilinen funding eventinden max-hold boyunca
oluşabilecek kötü ödeme eklenir; olası funding kredisi giriş kararında sıfır
sayılır. Donmuş spreadin mean'e beklenen dönüşü, `C2` ve yarıya kesilmiş pozitif
`H` payoff'ının kötü olanını en az `1.5×` karşılamıyorsa işlem açılmaz.

Funding bilgisinde cutoff `event_ts < entry_ts` biçiminde katıdır; entry ile aynı
`:00` olay kullanılamaz. `C2` entry kapısında funding de `2×` sayılır. Gerçek
cashflow markı varsa event mark, yoksa event anına kadar tamamlanmış son 15m
close'dur; ikisi de yoksa replay geçersizdir.

Funding timestampindeki fractional second UTC tam saniyeye floor edilir; pozisyon
yalnız `entry_ts < event_ts <= exit_ts` ise olayı taşır. Son 30 bilinen eventin en
kısa pozitif cadence'i max-hold event sayısını belirler; iki event yoksa 8 saat
kullanılır. Böylece tarihsel 2/4 saatlik SOL funding rejimleri 8 saat varsayımıyla
eksik sayılmaz. Bare funding sembolü `SOL/USDT` biçimine canonical edilir.

Bu kural Batch 1'de görülen `$0.29` edge / `$3.70` maliyet problemini eşik
oynamadan doğrudan ekonomik seviyede engeller.

## Veri ve doğrulama

- Market SHA-256:
  `071768300daea9170d29bd5e35cc94795b8a500614d6e5ac4b127e459416652d`
- Funding SHA-256:
  `35be9ebae8f9468a6bae819054008cb4c2338ae0eb923910584dea1adc0c6b96`
- Complete aylar: Haziran 2021–Mayıs 2026.
- Pseudo-OOS: Haziran 2023–Mayıs 2026, altı örtüşmeyen 6 aylık metric slice.
- Her çift kendi iki bacak + BTC timestamp kesişiminde hesaplanır; global
  18-sembol kesişimi ve price forward-fill yasaktır.
- B/C2/H path-dependent ve ayrı replay edilir. Ay/fold sınırında NAV, peak,
  açık çift ve state taşınır.
- Bir episode tek trade sayılır; iki leg örneklemi yapay olarak ikiye katlamaz.

`H` MTM yolu episode-final sonuca bırakılmaz: her 15m noktada entry'den beri
kümülatif atomik pair fiyat PnL'i pozitifse `0.50`, negatifse `1.25` ile
çarpılır; exitte final kümülatif fiyat PnL'ine aynı kural uygulanır. Execution ve
funding ayrı kalır. İlk train/validation geçmişi henüz dolmamış aylar silinmez,
sıfır getiri olarak development serisinde kalır.

OOS/IS oranı hücreler arası ortak kullanılabilir pencere olan Ocak 2022–Mayıs
2023 üzerinde hesaplanır; tam 24 aylık development serisi erken sıfır aylarıyla
ayrıca raporlanır. Cutoff'ta açık pair, sample'da kapalı episode sayılmaz fakat
son close MTM ve accrued liquidation maliyetiyle edge/yön/konsantrasyona terminal
pseudo-episode olarak girer.

Sample kapısı pairs mekanizmasına uygun olarak en az 120 kapalı episode, iki
spread yönünde en az 40'ar giriş ve 30 aktif ay ister. Return, stability, DD,
fold, holdout ve multiple-testing eşikleri v16 ile aynı kalır. Primary mutlak
kapıları geçmezse holdout/LOSO çalıştırılmaz ve sonuç RED'dir.

Trimli ortalama her kuyruktan `floor(n×0.10)` gözlem çıkarır; `%15` cap yalnız
aday sıralamasındadır, hard gate getirileri hamdır. Bootstrap üç aylık overlapping
moving block, 20.000 iterasyon ve seed `17`; DSR üç hücrenin H Sharpe dağılımı,
PBO eksiksiz `36×3` H matrisiyle hesaplanır. Holdout sembol PnL'si uydurulmaz:
aynı 36 ayda C2 toplam/retention/DD yanında dört sembolün tamamının ve en az iki
farklı kapalı holdout çiftinin gerçekten işlem görmesi gerekir.

Candidate sign-flip testi 12 adet örtüşmeyen kronolojik üç aylık block'un her
birine bağımsız `±1` işareti verir; p-değeri `(1+null>=observed)/(20000+1)`dir.
v17 içi üç denemeye ek olarak, aynı pseudo-OOS'u görmüş v16 ile toplam dokuz
hücrenin program-wide Holm/DSR/PBO değerleri de aynı eşikleri geçmek zorundadır.

Holdout ayrıca en az 30 kapalı episode ve 18 aktif ay ister. Yalnız primary
kapıları geçenler arasındaki tek kilitli winner önce gerçek LOSO, sonra bir kez
holdout görür; holdout başarısızsa runner-up denenmez. `instruments` tablosu boş
olduğu için quantity continuous fractional proxy'dir; tarihsel tick/lot rounding
yoktur ve v17 sonucu live implementability iddiası taşıyamaz. `3×` leverage,
altı leg × `%15` cap altında erişilmeyen tavandır; fill modeli gerçek submit
gecikmesi değil next-open proxy + gerçek leg notionalında `28.5 bps/fill`dir.

## Ekonomik dayanak ve sınırlar

Klasik pairs trading çalışması, mekanizmanın equity piyasalarında tarihsel
excess return üretebildiğini gösterir; raporlanan ölçek aylık `%10–15` değildir.
[Gatev, Goetzmann ve Rouwenhorst](https://academic.oup.com/rfs/article-abstract/19/3/797/1646694).
Cointegration çerçevesi [Engle ve
Granger](https://doi.org/10.2307/1913236), mean-reverting spread modeli
[Elliott, van der Hoek ve
Malcolm](https://digital.library.adelaide.edu.au/dspace/handle/2440/17846?mode=full)
ve structural-break riski [Gregory ve
Hansen](https://www.sciencedirect.com/science/article/pii/0304407669416857)
tarafından desteklenir.

Kriptodaki büyük arbitrajların önemli bölümü exchange/ülke segmentasyonundan
gelir; tek Binance snapshot'ı bunları içermez. [Makarov ve
Schoar](https://www.sciencedirect.com/science/article/abs/pii/S0304405X19301746).
Bu nedenle v17 için güçlü sonuç garanti veya temel beklenti değildir.

Sonuç geçse bile statik survivor universe nedeniyle yalnız
`FEASIBILITY_NOT_PROMOTION` olabilir. Canlı terfi için cutoff sonrası matched
pair signal/fill kanıtı ve ayrıca fair v15p2 policy proxy karşılaştırması gerekir.
