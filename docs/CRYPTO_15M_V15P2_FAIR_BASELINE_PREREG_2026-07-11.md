# v15p2 adil baseline — sonuç öncesi kayıt

## Karar ve kapsam

Bu çalışma mevcut v15p2'yi yeni bir strateji adayı gibi yeniden optimize etmez.
Tek amacı, v16/v17 ve ilerideki 15m adaylarla aynı donmuş veri, dönem, maliyet
ve portföy muhasebesinde karşılaştırılabilir bir kontrol üretmektir. Sonuç sınıfı
`FAIR_LIVE_POLICY_PROXY`, dolum sınıfı `NEXT_OPEN_BAR_EXECUTION_PROXY` olarak
kilitlidir. Bu sınıflar **exact live replay** veya canlı getiri beklentisi
anlamına gelmez.

Makine sözleşmesi
`configs/crypto_15m_v15p2_fair_baseline_prereg.yaml` dosyasındadır. Bu iki
önkayıt dosyası yazılırken snapshot replay'i çalıştırılmadı, holdout görülmedi
ve daemon/deploy durumu değiştirilmedi.

Snapshot erişiminden önceki bağımsız adversarial inceleme, scanner ve replay
proxy'sinde sonuç değiştirebilecek parite farkları buldu. On-disk scanner
tamamlanmış mumları önce filtreleyip sonra tam 500 bar alacak şekilde onarıldı;
çalışan daemon restart edilmedi ve hâlâ eski import edilmiş process image'ını
kullanıyor. Bu baseline sonraki güvenli restart adayı olan
**repaired-scanner source identity**'sine bağlıdır; mevcut PID'in exact geçmiş
replay'i değildir. Aşağıdaki düzeltmeler sonuç görülmeden yapıldı.
Bu turda ayrıca her ham sinyali kabul/ret sonucuyla ledger'layan kanıt yolu,
tam 90 UTC takvim günü correlation şartı ve her primary sembol için son
`2026-05-31 23:45 UTC` bar zorunluluğu eklendi. Günlük realized-PnL adapter'ı,
yalnız partial kapanış bulunan günü wallet-delta fallback'ına düşürmeyecek
şekilde on-disk onarıldı. `classic_pa.py` ile `contracts.py` de executable
source provenance kapsamına alındı. Bunların hiçbiri snapshot sonucu
görülmeden, çalışan daemon restart edilmeden yapıldı.
Son kaynak-parite denetiminde canlı korelasyon kapısının eksik geçmişte
fail-open kalabildiği de bulundu. On-disk `build_returns_df/correlation_gate`
exact önceki 90 UTC takvim return'ünü şart koşup eksik/stale/nonfinite/undefined
çifti reddedecek şekilde onarıldı. Exact-sıfır final PnL de canlı consecutive
counter'da loss değil streak-break oldu. Çalışan PID eski import edilmiş image'da
kaldığı için bu düzeltmeler yalnız sonraki güvenli restart kimliğidir.
Nihai sonuç-öncesi rapor denetimi de preflight/postflight kaynak, runtime,
preregistration ve snapshot kimlikleri ile accepted-intent reconciliation/hash
zincirini zorunlu kıldı. Ardından Ruff, onarılmış scanner'daki dört bitişik SQL
string satırını yalnız mekanik olarak normalize etti; davranış değişmedi ve
scanner'ın audited hash'i son kaynak dondurmasından önce yenilendi. Bu sırada da
snapshot açılmadı, holdout görülmedi ve çalışan daemon restart edilmedi.

## Eski `%21,36/ay` neden geçersiz

Eski v15p2 pool başlığı kayıt amacıyla korunur; fakat adil baseline, canlı
beklenti veya “yeni bot daha iyi” paydası değildir. O sonuç eski trade
pool'larını ve ay başında sıfırlanan sermayeyi kullanıyor, ay sonrasına taşan
işlemin gelecekteki sonucunu giriş ayına yazıyor, bugünkü wrapper exit'ini ve
gözlenen funding'i yeniden oynamıyor, maliyet bileşenlerini denetlenebilir
fill-ledger olarak ayırmıyor ve tam 15m MTM eğri üretmiyor. Evreni de bu
programın primary-13 karşılaştırma evreniyle aynı değil.

Bu nedenle `%21,36` yalnız tarihsel araştırma artefaktıdır. Yeni baseline
tamamlanana kadar v15p2 için karşılaştırmada kullanılabilecek bir getiri sayısı
yoktur.

## Donmuş veri, evren ve zaman

- OHLCV: `data/backups/20260711/market.duckdb`, SHA-256
  `071768300daea9170d29bd5e35cc94795b8a500614d6e5ac4b127e459416652d`,
  `1.636.839.424` byte.
- Funding: `data/backups/20260711/funding.duckdb`, SHA-256
  `35be9ebae8f9468a6bae819054008cb4c2338ae0eb923910584dea1adc0c6b96`,
  `17.575.936` byte.
- İşlem evreni yalnız 13 primary semboldür: ETH, SOL, BNB, ADA, AVAX, LINK,
  DOT, DOGE, ZEC, NEAR, FIL, ATOM ve ALGO. BTC yalnız işlem görmeyen piyasa
  referansı olabilir.
- XLM, AAVE, TRX ve XRP holdout'u yüklemek, özellikte kullanmak veya işlem
  yapmak yasaktır. UNI dışarıdadır.
- Dönem `[2021-06-01, 2026-06-01)` UTC'dir. İlk 24 ay development, sonraki 36
  ay historical pseudo-OOS'tur. Pseudo-OOS altı ayrı 6 aylık fold olarak
  raporlanır; foldlar restart değil tek kesintisiz eğrinin metrik dilimleridir.

Snapshot'ların byte ve SHA kimliği herhangi bir DuckDB bağlantısından önce ve
replay sonrasında tekrar doğrulanır. Canlı/mutable veritabanı kullanılamaz.
Runner feature geçmişini `2021-02-21T00:00:00Z`'den yükler, fakat portföy,
entry ve sonuç eğrisi kesin olarak `2021-06-01T00:00:00Z`'de başlar. Bu 100
takvim günlük lead, ilk değerlendirmeden önce her primary sembolde 500 ardışık
15m mum ile correlation gate için 91 tamamlanmış UTC daily close sağlamalıdır.
91 close tam 90 causal günlük log-return üretir. Sembollerden biri bu başlangıç
geçmişini veremiyorsa replay kanıt üretmeden fail-closed kapanır.
Her primary sembol değerlendirme döneminin son `15m` barına da ulaşmalıdır;
erken biten sembolü eski mark ile cutoff'a kadar taşımak yasaktır.

## Sinyal ve giriş sözleşmesi

Strateji sırası config ve canlı scanner gerçeğiyle aynı şekilde önce
`vsa_climax_test`, sonra `grimes_abc_pullback`'tır. VSA kodu mevcut 15m manifest
overlay'iyle, Grimes mevcut default manifestiyle hash-bağlı çalışır. Legacy
trade pool'u girdi olamaz; sinyaller donmuş barlardan yeniden üretilir.

Karar yalnız tamamlanmış 15m mum kapanışında verilir. Forming candle hiçbir
özelliğe giremez ve en erken dolum sonraki tam, kesintisiz 15m mumun açılışıdır.
Aynı karar zamanındaki intentler sembol lexicographic sırası ve sembol içinde
VSA→Grimes önceliğiyle işlenir. İlk kabul edilen intent o sembol slotunu alır.
Adapter aynı karar anındaki bütün signal-eligible VSA/Grimes intentlerini korur;
üst-priorite intent riskte reddedilirse sıradaki değerlendirilebilir. WIDESTOP
uygunluğu canlı daemon gibi karar mumu close'u ile stop arasından ölçülür ve en
az `%2,5`, confluence en az `0,25` olmalıdır. Next-open ile stop mesafesi seçim
için değil, yalnız dolum sonrası sizing/normalizer/marjin güvenliği içindir.

Repaired scanner önce `ts < target_bar_close` ile forming mumu çıkarır, sonra
tam son 500 tamamlanmış mumu alır. VSA'nın sinyalde kullanılan tüm bağımlılıkları
500'den kesin kısa ve sonlu olduğundan bounded full-block geçişi exact rolling
sonucudur; hesaplanan fakat karar yolunda kullanılmayan EMA200 bu kanıta dahil
değildir. Grimes için EMA50 sonsuz-prefix olduğundan full pass kullanılamaz:
trend ve cooldown'u iki yönde gevşeten yapısal-candidate superset çıkarılır,
sonra yalnız bu endpointlerde taze unmodified strateji exact rolling-500 ile
çalıştırılır. Randomized küçük fixture'da iki gerçek stratejinin her endpointi
naif rolling referansıyla çift yönlü karşılaştırılır. Missing, extra veya alanı
değişmiş tek endpoint sinyali evidence'i fail-closed kapatır. Effective manifest
kimlikleri VSA `1.0.0-15m/ebddc62d495cc790`, Grimes
`1.0.0/33653e0c52e34338` olarak ayrıca doğrulanır.
Her gerçek strateji emission'ı için sonuç defterinde tek satır gerekir. Satır
`accepted`, düşük confidence, karar-close WIDESTOP reddi, eksik next bar veya
mükerrer fingerprint sonucunu açıkça taşır. Accepted satırların sırası ve
kimliği engine'e verilen intent akışıyla birebir uzlaşmazsa replay kanıt olamaz.

Config'deki aynı-sembol/yön cooldown `0,010 gün = 14,4 dakika`dır. Scanner'ın
standalone `run_15m` yardımcı yolu bunu çağırsa da v14 daemon submit yolu
çağırmaz. Replay değeri kimlik için korur; exact 15m giriş gridindeki en kısa
iki entry arası 15 dakika olduğundan bu kapı davranışsal olarak inerttir ve
canlı daemonun kabul sonucunu değiştirmez.

`NEXT_OPEN_BAR_EXECUTION_PROXY`, canlı post-only emir kuyruğunu, 30 saniyelik
fallback'i veya submit gecikmesini bildiğini iddia etmez. Girişin signal close
fiyatında doldurulması yasaktır. Gap-stop, open ile stop seviyesinin daha kötü
olanında; aynı mum stop ve hedefe değerse stop önce işlenir. Fiyat forward-fill
yoktur. Sinyal özelliklerinde exact 15 dakikadan farklı her timestamp adımı yeni
block başlatır; adapter sınırın iki tarafını aynı pencereye koyamaz ve 500 yeni
exact-15m mum birikmeden karar üretmez. Açık pozisyon için ayrı veri-gap kuralı
`>30m`'dir ve ilk işlem gören open'da kötümser çıkış yapar.

Next-open, stop'u koruyucu tarafın ötesine taşıdıysa (long için stop `>= open`,
short için stop `<= open`) order fill varsayılmaz; intent `stop_on_wrong_side`
ile maliyetsiz reddedilir. Canlı RiskOfficer'ın bu güvenlik kontrolü on-disk
kaynağa sonuç görülmeden eklendi; açık pozisyonlu mevcut PID restart edilmedi.

## Güncel-cüzdan risk ve portföy durumu

Başlangıç ölçeği `$10.000` olsa da her intentin risk bütçesi sabit başlangıç
sermayesinden değil, o intentten hemen önceki güncel wallet balance'dan
hesaplanır. Gerçekleşmiş PnL, maliyet ve funding wallet'a girer; açık pozisyonun
unrealized PnL'si canlı `wallet_balance` sizing tabanına girmez. Buna karşılık
performans/DD eğrisi her 15m'de açıkları mark-to-market eder. Temel risk
`%1`'dir. RiskOfficer'ın statik `$10` minimum notional kapısı uygulanır;
tarihsel exchange tick/lot ve zamana bağlı venue min-notional yuvarlaması
simüle edilmez. Stop mesafesi normalizasyonu `0,01 / stop_pct` formülünü `0,20–1,50`
bandına kırpar. Running wallet-balance peak'inden DD `%6`'ya ulaştığında yeni
giriş riski yarıya iner. Wrapper başlığındaki eski “fixed starting equity”
yorumu runtime sizing otoritesi değildir; gerçek RiskOfficer current wallet
kullanır ve proxy de bunu izler.
Peak yalnız bir intent canlı RiskOfficer'ın DD-throttle/sizing aşamasına
ulaştığında gözlenip ratchet edilir. Arada sinyal yokken oluşup geri verilen bir
exit/funding wallet zirvesi canlı state'e hiç yazılmadığından replay peak'ine de
alınmaz.

Tek sembolde tek net pozisyon vardır; pyramid kapalıdır. Sembol notional tavanı
güncel wallet balance'ın `%15`'i, aynı yön tavanı dört pozisyon, config tavanı 16
pozisyondur. Portföy notional tavanı `3×`, sembol leverage tavanı `3×`'tir;
fakat canlı `leverage_gate` gerçek kaldıracı
`min(3, max(1, pre_corr_notional / wallet))` ile hesaplar. `%15` sembol cap'i
nedeniyle bu baseline girişleri fiilen `1×` olur. Sıra canlıyla aynıdır: sizing,
sembol cap, pre-correlation `$10` minimum notional, portföy gate, dinamik
leverage, pre-correlation margin, correlation quantity reduction ve son olarak
stop/liquidation safety. Gerekli initial margin pre-correlation
notional üzerinden hesaplanır ve free margin'in ancak `%90`'ına kadar kabul
edilir; wrapper aynı `%90` kapısını tekrar uygular. Stop mesafesi yaklaşık
likidasyon mesafesinin yarısını aşamaz:
`stop_pct <= (1 / leverage_used) × 0,50`.
Correlation matrisi her kararda entry tarihinden bir gün önce biten **tam 90
UTC takvim tarihini** ve her açık sembol çifti için 90 finite causal
log-return'ü kullanır. Eksik günü daha eski bir satırla tamamlamak yasaktır.
Eksik kolon/gün, nonfinite değer veya tanımsız korelasyon intenti ledger'lı
fail-closed reddeder. Eşik `%0,70` üzerinde final quantity `×0,50`, `%0,90` ve
üzerinde ret olur. On-disk canlı kaynak aynı exact-history/fail-closed kuralına
sonuç görülmeden bağlanmıştır; mevcut PID restart edilmemiştir.

Breaker'lar stateful ve UTC tabanlıdır:

- günlük `%4`: deployed journal timing proxy toplamı; partial satır yalnız
  scenario-adjusted fiyat PnL, final satır bütün episode neti (tüm execution
  maliyeti ve funding dahil) eksi önceden yazılmış partial'lardır;
- haftalık `%8`: Pazartesi 00:00 wallet-balance anchor'ına göre, iki gün duruş;
- combined aylık `%99`: pratik acil tavan, üç gün duruş;
- aylık long `%12` ve short `%4`: ay başı wallet-balance paydasında journal
  partial/final side-PnL; ilk trigger `3 gün` side block kurar, trigger UTC ay
  resetine kadar latch kalarak süreyi yeniden uzatmaz; ay sonundaki eski block
  timestamp'i yeni aya taşabilir;
- beş ardışık negatif **final journal satırı**: consumed-watermark ile bir gün
  duruş; yalnız son 30 UTC günlük journal penceresi sayılır, partial satırlar
  streak'i değiştirmez, exact sıfır final satırı streak'i kırar ve loss sayılmaz.
  Canlı sorgunun eski 20-satır doygunluk limiti sonuç görülmeden kaldırılmıştır;
  30 günlük pencerenin tamamı sayılır.

Daily/weekly/monthly combined kaynakta tek `blocked_combined_until` clock paylaşır
ve öncelik `daily → weekly → monthly` şeklinde `if/elif`'tir. Aktif flag metrik
breached kaldıkça bu tek clock'u ileri yuvarlar ve yeni girişi bloklar. Günlük
journal feed'i final **veya partial** satır bulunan günde journal toplamını
otorite sayar; wallet delta yalnız ikisi de yokken legacy fallback'tır. Tam
Aynı 00:00 timestamp'indeki bütün sembol funding'leri önce taşınan pozisyonlara
tek batch olarak uygulanır, sonra yeni gün/hafta/ay wallet anchor'ı toplam
post-settlement bakiyeden kurulur. Funding final journal satırını da etkiler.
Breaker mevcut pozisyonu zorla kapatmaz; yalnız yeni girişleri bloke eder.
Ay/fold sınırında cüzdan, açık pozisyon, peak, cooldown veya breaker state'i
sıfırlanamaz.

## Canlı wrapper exit'i — YAML drift'ine karşı açık bağ

Exit otoritesi `scripts/futures_daemon_v14.py` wrapper override'ıdır:

- TP1: `1R`'da orijinal miktarın `%30`'u;
- TP2: `1,5R`'da orijinal miktarın `%30`'u;
- runner: `%40`;
- TP1 sonrası break-even kilidi ve `%1,5` fiyat-yüzdesi trail;
- ilk TP1 fill'inden sonra 30 adet 15m bar dolarsa runner time-stop.

Trail, tamamlanmış mumun olumlu ekstreminden ratchet edilir ve yeni seviye
sonraki mumda etkindir. Bu, geçmiş OHLCV'de denetlenebilir causal PCT proxy'dir;
ATR `1,5×` chandelier değildir. Time-stop dolumu sonraki kesintisiz open
proxy'sidir. Canlı daemon 30 bar anında sampled mark'ın hâlâ en az `1R` olmasını
tekrar ister; tarihsel sampled mark bilinmediği için replay 30 tamamlanmış
bardan sonra koşulsuz next-open proxy uygular. Bu nedenle exact time-stop exit
paritesi iddia edilemez.

v15p2 YAML içindeki dead `exit_engine` bloğunun `%25/%25/%50` değerlerini
hiçbir runtime tüketicisi okumaz. Bunlar replay'e alınmayacaktır. Aynı şekilde
YAML yorumları veya inert `take_profit` alanları wrapper'ın canonical
`%30/%30/%40` gerçeğini geçersiz kılamaz. Bu drift hem raw kanıtta hem nihai
raporda limitation olarak yazılacaktır.

## Maliyet ve canlı-haircut

Her gerçek fill notionalında `4 bps` fee, `20 bps` spread/slippage ve `4,5 bps`
impact uygulanır: fill başına `28,5 bps`; tek entry ve tüm miktarın exit'i için
temel round-trip `57 bps`'tir. TP1, TP2, runner, stop, gap, time-stop ve cutoff
liquidation fill'leri kendi miktarlarında ayrı ücretlenir. Funding, olay anında
kalan açık notional ve yön üzerinden gözlenen nakit akışıdır.

Üç senaryo ayrı, path-dependent replay edilir:

- `B`: temel execution ve funding;
- `C2`: execution ve funding `×2`;
- `H`: temel maliyet/funding; her gerçekleşen pozitif fiyat-PnL dilimi `×0,50`,
  negatif dilim `×1,25`.

Haircut execution cost veya funding'e ikinci kez uygulanmaz. Açık terminal
pozisyonlar cutoff markında tahakkuk etmiş liquidation maliyetiyle NAV'a girer,
ama kapalı episode örneklemine yazılmaz.

## Kanıt ve rapor zorunlulukları

`B/C2/H` için her mevcut 15m mumdan sonra açık pozisyon MTM'si ve tahakkuk exit
maliyeti içeren tam eğri gerekir. Aylık return, ay başlangıcından kesin olarak
önceki son NAV'ı baz alır; işlem olmayan ay `%0`'dır. H pseudo-OOS dizisi tam 36
ay, foldlar `6×6` ay olmalıdır.

Raw kanıt en az şunları içerir: her ham sinyalin eligibility sonucu/ret nedeni,
accepted satırların engine intentleriyle birebir uzlaşması, karar/scheduled
entry zamanı, entry ve her partial/final fill, stop ratchet state'i, funding
eventleri, fill başına fee/spread/impact, breaker geçişleri, her intentte
current-wallet risk bütçesi ve cap nedeni, terminal açık pozisyon tahakkuku.
Rapor; aylık mean/median/%10-trim, negatif aylar, `<-%1` aylar, en kötü ay,
15m MTM DD/recovery, altı fold, development/pseudo-OOS oranları, yön-strateji-
sembol-ay konsantrasyonu, sample ve turnover'ı verir.

Execute öncesi research source temiz olmalı. Commit, prereg SHA, replay'e giren
her kaynak dosyanın SHA'sı ve iki snapshot kimliği raw sonuca yazılır. Replay
sonunda kaynak ve snapshot kimliklerinden biri değişmişse sonuç
`INELIGIBLE_EVIDENCE` olur. NaN/Infinity JSON'a sızamaz.
Prereg YAML'ında aynı mapping içinde yinelenen anahtar herhangi bir derinlikte
fail-closed reddedilir. Gerçek `python -m ... --dry-plan` stdout'u tek strict
JSON belgesidir; package importu stdout'a log ekleyemez veya `app.log` dosyasını
değiştiremez. Research CLI `.env` yüklemesini ve bütün log sink'lerini kapatır;
import edilen Loguru, Pydantic Settings ve python-dotenv sürümleri lockfile'a
karşı doğrulanır. Çalışan package init/logging/settings kaynakları ve ilgili
parity testleri de source-clean/hash kapsamındadır. Reporter yalnız exact prereg
ve iki donmuş snapshot kimliğini kabul eder.

## v16'dan donmuş “daha iyi” kuralları

Gelecekte bir challenger ancak aynı snapshot, primary-13, dönem, execution,
maliyet ve metrik kodunda karşılaştırılabilir. Kendi mutlak hard gate'lerini de
geçmek şartıyla aşağıdakilerden biri gerekir:

1. Challenger H trimli aylık getiri `max(%10, baseline + 1,5 puan)` veya üstü
   ve H MTM DD baseline'dan en fazla `1 puan` daha kötü; veya
2. Challenger H trimli aylık getiri baseline'ın `1 puan` yakınında ve H MTM DD
   en az `%25` daha düşük.

Her iki yolda da challenger'ın H negatif ay sayısı ve en kötü ayı baseline'dan
daha kötü olamaz. Eski `%21,36` bu formüllerde baseline yerine kullanılamaz.
Bu karşılaştırma kuralı bir adayın mutlak kabul kapılarını gevşetmez.

## Açık sınırlar ve yetki

Donmuş snapshot'larda point-in-time F&G, mark/L1, order queue, exchange rounding,
margin tier, API-stale ve rate-limit yolları yoktur. F&G değeri gerektiren kapı
eksik olduğunda proxy fail-open/no-rejection davranır ve bu sapmanın yönü
bilinmiyor diye raporlanır. Maker fill varsayılmaz; bütün execution sabit
maliyet proxy'siyle fiyatlanır.

VSA'nın deployed confirmation satırında SC/BC referansı taşınmadığı için mevcut
kaynak documented structural stop yerine fallback confirmation-close ±2 ATR
davranışını üretir. Baseline bunu live-source parity için aynen korur ve nihai
raporda `deployed_vsa_stop_fallback` olarak açıklar; yeni stratejiye düzeltilmiş
VSA sonucu diye sunulamaz. Ayrıca historical exchange `availableBalance`, L1
mark örnekleme anı ve runner time-stop'un canlıdaki anlık mark koşulu bilinmez;
wallet/margin ve completed-bar trail/time-stop davranışları açık proxy'dir.

Bu özellikle iki canlı kapıyı etkiler: F&G `<20` global short-skip ve VSA long
için `F&G<15` ile `BTC 30g return<-%10` birleşik deep-bear skip. F&G tarihçesi
donmuş snapshot'ta bulunmadığından ikisi de eksik değerde `ALLOW` olur. Wrapper
HTF filtresini kaldırır, BTC capitulation halt ve funding-signal filter config'de
kapalıdır; inactive Brooks/engulfing rejim kuralları bu iki stratejili baseline'a
uygulanmaz.

Statik survivor evren ve historical pseudo-OOS nedeniyle olumlu sonuç bile
prospective veya canlı kanıt değildir. Bu prereg holdout erişimi, eşik
değişikliği, paper/live deploy, çalışan daemon restart'ı ya da herhangi bir
borsa işlemi için yetki vermez.
