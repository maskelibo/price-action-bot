# Crypto 15m V18 challenger önkaydı

Durum: **tasarım kilitli, motor yok, baseline veya challenger sonucu görülmedi**.
Bu belge sonuç üretmez ve canlı/paper işlem yetkisi vermez. Dört aday, adil
v15p2 baseline sonucu açılmadan önce `2026-07-11T17:01:08Z` itibarıyla
sabitlenmiştir.

## Sonuç öncesi bağlayıcı ek

`2026-07-11T17:27:59Z` zamanlı
`baseline_legacy_statistics_and_funding_bindings` eki de herhangi bir baseline
veya challenger sonucu görülmeden kaydedilmiştir. Bu ek dört aday hücreyi,
ekonomik kabul eşiklerini veya sıralama kuralını değiştirmez. Yalnız sonuçtan
önce açık bırakılmaması gereken şu uygulama ayrıntılarını makine-okunur
sözleşmeye bağlar:

- gerçek V2 baseline önkaydı ile program/report kaynaklarının byte ve SHA-256
  kimlikleri;
- baseline'ın tek kanonik çıktı yolları ve sonuç-kimliği mührünün zorunlu
  alanları;
- yeniden üretilebilir dokuz v16/v17 denemesinin exact artifact kimlikleri ve
  JSON field path'leri;
- bootstrap, sign-flip, Holm, Deflated Sharpe ve CSCV/PBO'nun sonuç etkileyen
  bütün algoritmik seçimleri.

Funding aggregate kapsamı ilk V18 `created_at` zamanından sonra öğrenilmiş,
fakat bu ekten önce de hiçbir baseline/challenger performansı açılmamıştır.
Dolayısıyla açıklama veri sınırlamasını netleştirir; sonuçtan seçilmiş bir aday
veya eşik değişikliği değildir.

## Sınanan dört hücre

V18 yeni eşik aramaz. Donmuş v15p2 fair-policy proxy'sinin yalnız iki kontrollü
özelliğini sınar: strateji alt kümesi ve nedensel günlük SMA50 kapısı.

| Hücre | Aktif strateji | Günlük SMA50 |
|---|---|---|
| `C1_VSA_ONLY` | yalnız `vsa_climax_test` | yok |
| `C2_GRIMES_ONLY` | yalnız `grimes_abc_pullback` | yok |
| `C3_DUAL_HTF50` | VSA + Grimes | var |
| `C4_VSA_HTF50` | yalnız VSA | var |

Bunun dışında sinyal parametreleri, rolling-500 davranışı, risk, portföy
kapıları, breaker state'i, next-open execution, `30/30/40` exit ve metrik
semantiği değişemez. Yeni filtre, eşik, hücre, ensemble veya sonuçtan seçilmiş
varyant ancak yeni bir önkayıtla ayrı deneme sayılır.

## Donmuş veri kimliği

Market verisi başarılı ve bağımsız denetimlerden geçmiş V3 bundle'dır:

- `data/backups/20260711_v15p2_v3_usdm/market.duckdb`
- byte: `181415936`
- SHA-256: `50e5b240e6babeb3b7ceadc0ae007ededc0ae589cba931e3603d233cec693eb8`
- satır ve distinct primary key: `2586624`
- sıralı primary-key SHA-256:
  `8fa35b544898ab7f131a0826a2a4bd989aa0d283cc5a2926fb85f962a3e93318`
- V3 success-identity SHA-256:
  `8e73f05d87106ea9df635e3ae0d3996ec5679da48f83bff77856b065059972d3`
- build-evidence SHA-256:
  `1ac74ceb61c197fad4bc27783eadaed4e88504e3a751257d8c735bc9eece9b34`

Resmi vendor verisinde doldurulmayan `1920` bar vardır. SOL, ZEC, NEAR ve FIL
için `[2022-02-26, 2022-03-01)` aralığında sembol başına `288`,
`[2022-04-01, 2022-04-03)` aralığında sembol başına `192` bar eksiktir. Fiyat,
özellik veya semboller arası ortak timestamp doldurma yasaktır.

Funding snapshot'ı `17.575.936` byte ve
`35be9ebae8f9468a6bae819054008cb4c2338ae0eb923910584dea1adc0c6b96`
SHA-256 kimliğindedir. Tam veritabanında 19 sembolde `115006` gözlenen olay,
primary-13 değerlendirme aralığında `71289` olay vardır. Primary sembollerde
non-finite funding rate ve duplicate raw sembol-timestamp yoktur; fakat `34486`
olayda geçerli pozitif mark yoktur ve son nedensel sembol close'u kullanılır.
Bu snapshot zaman aralığını kapsar ama V3 vendor-checksum protokolüyle yeniden
kurulmamıştır. Dolayısıyla her planlı tarihsel olayın bulunduğu iddia edilemez;
yalnız gözlenen olay nakit akışı yaratır, eksik olay uydurulmaz veya interpolate
edilmez.

## Exact V2 baseline kimliği

V18 karşılaştırmasının kanonik baseline'ı aşağıdaki üç sonuç-öncesi girdiden
başka bir prereg, runner veya reporter kullanamaz:

| Girdi | Byte | SHA-256 | Şema |
|---|---:|---|---|
| `configs/crypto_15m_v15p2_fair_baseline_v2_prereg.yaml` | `39694` | `7a6180312bcbb1b1f9644d26dbce8bd8ac57ea4eb13fc0aa783025f069ddd511` | `crypto-15m-v15p2-fair-baseline-prereg-v2` |
| `src/price_action/lab/crypto_15m_v15p2_program.py` | `74553` | `d925ef902d33b01ab7b22487e304ec6a724fb14153a32b73f538c63d79879bcb` | `crypto-15m-v15p2-fair-baseline-run-v2` |
| `src/price_action/lab/crypto_15m_v15p2_report.py` | `135566` | `0417ea087627251cd056655e83a72d7e8b38624c3158763258c830ca0e599f9f` | `crypto-15m-v15p2-fair-baseline-report-v2` |

İlk alpha sonucu açılmadan önceki deneme sayısı `0` olarak kilitlidir. Tek
kanonik çıktılar şunlardır:

- raw JSON:
  `reports/research/crypto_15m_v15p2_fair_baseline_v2_raw.json`;
- report JSON:
  `reports/research/crypto_15m_v15p2_fair_baseline_v2_report.json`;
- Markdown:
  `reports/research/CRYPTO_15M_V15P2_FAIR_BASELINE_V2.md`;
- sonuç kimliği:
  `configs/crypto_15m_v15p2_fair_baseline_v2_result_identity.json`.

Karşılaştırma başlamadan önce sonuç kimliği; prereg/program/report byte ve
SHA-256 kimliklerini, aynı V3 market ve funding kimliğini, raw/report çıktı
yolu+byte+SHA kimliklerini ve execution git commit'ini birlikte bağlamalıdır.
Kaynak ağacı preflight'ta temiz ve postflight'ta değişmemiş, raw ile report
ayrı ayrı `evidence_eligible=true` olmalıdır. Eksik, mükerrer veya uyuşmayan bir
kanonik çıktı varsa “baseline'dan daha iyi” iddiası fail-closed yasaktır.

## Zaman ve nedensellik

Tek kesintisiz replay `[2021-06-01, 2026-06-01)` UTC'dir. İlk 24 ay development,
sonraki 36 ay candidate-locked historical pseudo-OOS'tur. Altı adet 6 aylık fold
yalnız aynı eğrinin metrik dilimleridir; ay veya fold başında wallet, pozisyon,
peak, cooldown ya da breaker sıfırlanmaz. Önceki v16/v17 çalışmaları aynı tarihsel
dönemi gördüğü için buna bağımsız OOS denemez.

SMA50 filtresi her işlem sembolü için ayrı hesaplanır. Bir UTC gününün geçerli
daily close üretebilmesi için `00:00`–`23:45` arasında exact-grid 96 adet 15m bar
gerekir. D günündeki karar yalnız D-1'e kadar tamamlanan günleri kullanır. D-1'de
biten 50 **kesintisiz ve tam** UTC günün kapanışlarının exact aritmetik ortalaması
SMA50'dir:

- long için D-1 close `>` SMA50;
- short için D-1 close `<` SMA50;
- eşitlik, eksik/non-finite değer veya 50 tam günün bulunmaması fail-closed
  rejection'dır.

EMA, yaklaşık pencere, forming-day verisi, eksik gün yerine daha eski gün,
forward-fill ve global sembol intersection yasaktır. Her red sebebi ledger'a
yazılır.

## Execution ve maliyet

Karar tamamlanan 15m sinyal barının close'unda, en erken fill sonraki exact
bitişik 15m barın open'ındadır. Aynı barda stop/target çakışırsa stop önce gelir;
gap stop fill'i open ile stop'un kötü olanıdır. V15p2 fair-policy risk, breaker ve
exit state'i aynen korunur.

Her gerçek fill notionalında `4 bps` fee, `20 bps` spread/slippage ve `4,5 bps`
impact, toplam `28,5 bps` uygulanır. Funding kalan açık notionalda yalnız gözlenen
event nakit akışıdır:

- `B`: temel execution ve funding;
- `C2`: execution ve funding `2×`;
- `H`: temel execution/funding; her pozitif fiyat-PnL dilimi `0,50×`, her
  negatif fiyat-PnL dilimi `1,25×`.

Execution ve funding H haircut'ına ikinci kez sokulmaz. B/C2/H bağımsız,
path-dependent replay edilir.

## Mutlak kabul kapıları

Bir hücrenin sıralamaya girebilmesi için kapıların **tamamını** geçmesi gerekir:

- 36 pseudo-OOS ay; en az 360 kapanmış trade, 60 long, 60 short ve 30 aktif ay.
- H yüzde 10 symmetric-trim aylık ortalama en az `%10`, medyan en az `%8`,
  3 aylık moving-block bootstrap yüzde 90 alt sınırı en az `%6`.
- H negatif ay en fazla 4; `%−1` altı ay en fazla 3; en kötü ay en az `%−6`.
- C2 trimli aylık ortalama en az `%8`, medyan en az `%6`.
- B 15m MTM DD en fazla `%15`; C2 ile H arasındaki kötü değer en fazla `%20`.
- Altı fold'un en az beşi pozitif; en kötü 6 aylık fold en az `%−5`.
- H OOS/development trimli getiri oranı en az `0,50`; DD oranı en fazla `1,50`.
- B pre-cost fiyat-PnL / execution cost en az `1,50`; C2 long ve short neti ayrı
  ayrı pozitif.
- En iyi ay pozitif PnL payı en fazla `%15`, en iyi üç ay toplamı en fazla `%35`;
  en iyi üç ay çıkarılınca aylık ortalama en az `%7`.
- En iyi yüzde 5 trade çıkarılınca net sonuç pozitif.
- Effective symbol count en az 6 ve kazananın tüm gerçek LOSO replay'leri
  pozitif.
- Deflated Sharpe en az `0,95`, PBO en fazla `0,20`; hem yerel dört hücre Holm
  hem aşağıdaki program-floor Holm adjusted p en fazla `0,05`.

Bootstrap ve sign-flip testleri 3 aylık block, `20000` iterasyon ve seed `18`
kullanır. Eksik ay `%0`'dır; 36×4 H matrisi finite ve tam olmak zorundadır.

## Kilitli istatistik algoritmaları

Bu bölüm uygulamaya yorum alanı bırakmayan exact algoritma sözleşmesidir.
Ortak fonksiyon kaynağı
`src/price_action/lab/crypto_15m_validation.py` (`38943` byte,
`6227e9f1e4d3f979dbc539ec0ee2b0e7507437a61962194c5d37a52083b6d9e9`),
v16/v17 program-geneli sign-flip kaynağı ise
`src/price_action/lab/crypto_15m_pairs_validation.py` (`58684` byte,
`9f0eae0bb08f45ceacdb7a3bb9c48ceb1b2f1b3469d21bd2bf572e11ecf6a95b`)
kimliğindedir. Eksik veya non-finite herhangi bir girdi `UNVERIFIABLE` ve
fail-closed sonuç verir.

- Symmetric trim: değerler stabil sayısal artan sıraya konur; her kuyruktan
  `floor(n × 0,10)` değer çıkarılır ve kalanların aritmetik ortalaması alınır.
- Moving-block bootstrap: 36 aydan çıkan tüm 34 overlapping 3-aylık block
  kullanılır. `numpy.random.default_rng`/PCG64 seed `18` ile her iterasyonda
  replacement'lı 12 block indeksi çekilir, block'lar birleştirilip ilk 36 değer
  alınır. `20000` iterasyonun trimli ortalamalarında `numpy.quantile` linear
  yöntemiyle `0,10` quantile raporlanır.
- Sign-flip: 36 ay 12 adet non-overlapping 3-aylık bloğa ayrılır. Aynı PCG64
  seed `18` ile her bloğa bağımsız `−1/+1` işareti verilir; `20000` null trimli
  ortalamanın gözlenen değere eşit veya büyük olanları sayılır. Ham p-değeri
  `(1 + exceedance) / 20001` formülüdür.
- Holm: family order, kanonik aday sırasının ilgili family'ye indirgenmiş
  halidir. Ham p-değerleri artan sıralanır; exact tie'da family sırası korunur.
  Düzeltilmiş değer, sıralı rank boyunca `(family_size − j) × raw_p` değerinin
  cumulative max'ı, `1` cap'i ve sonra özgün family sırasına dönüşüdür.
- Periodic Sharpe: aylık aritmetik ortalama / `ddof=1` sample standard
  deviation'dır. `sqrt(12)` yalnız gösterim annualization'ıdır. Sıfır standard
  sapmada ortalamanın işaretine göre `+inf`, `−inf` veya `0` üretilir.
- Deflated Sharpe: gözlenen adayın exact 36 H aylık yüzde-puan getirisi ve
  kanonik sıradaki exact 13 periodic Sharpe kullanılır; `n_trials=13`,
  `periods_per_year=12`'dir. Skew/kurtosis population standardized central
  moment, Sharpe standard error kaynak fonksiyondaki `n−1` paydalı formül,
  expected-max ise aynı kaynaktaki Euler–Mascheroni normal order-statistic
  formülüdür. Çıktı, standard-normal CDF ile hesaplanır; non-finite trial
  Sharpe sonucu doğrulanamaz yapar.
- CSCV/PBO: yalnız exact finite `36×4` yerel H matrisi, sütunlarda C1–C4
  sırasıyla kullanılır. `numpy.array_split` ile altı eşit kronolojik slice ve
  lexicographic `C(6,3)=20` kombinasyon kurulur. Score `ddof=1` periodic
  Sharpe'dır; in-sample seçim `numpy.argmax` ile exact tie'da ilk sütundur.
  Out-sample rank `pandas` average-rank ascending, relative rank `rank/5`, logit
  `ln(r/(1−r))`; PBO 20 logit içinde `<=0` olanların oranıdır.

Yerel Holm dört V18 hücresinin sign-flip p-değerlerine uygulanır. Cumulative
Holm, aynı kilitli algoritmayla dokuz eski ve dört yeni p-değerini yeniden
hesaplayan tek 13 üyeli family'dir. DSR trial dağılımı da aynı kanonik 13
periodic Sharpe'dır. PBO yalnız dört V18 hücresini kapsar; eski programlarla
karıştırılmaz.

## Deneme sayacı ve seçim

Audit-grade minimum kayıt v16 için 6 ve v17 için 3 hücre olmak üzere önceden 9,
V18'de 4, toplam **en az 13** denemedir. Cumulative Holm ve DSR bu 13 denemenin
yeniden üretilebilir girdileriyle hesaplanır; prior girdi eksikse sonuç
`UNVERIFIABLE` ve fail-closed olur. Daha eski sweep ve legacy araştırma maruziyeti
daha büyüktür fakat exact sayısı yeniden kurulamamaktadır. Bu yüzden 13 gerçek
toplam değil, yalnız denetlenebilir alt sınırdır; olumlu historical sonuç yine de
promotion kanıtı değildir.

Dokuz önceki adayın kanonik sırası ve kaynağı şöyledir:

| Sıra | Aday | Raw artifact |
|---:|---|---|
| 1 | `T1_RESIDUAL_TREND_1W` | `v16_raw_gzip` |
| 2 | `T2_RESIDUAL_TREND_2W` | `v16_raw_gzip` |
| 3 | `T4_RESIDUAL_TREND_4W` | `v16_raw_gzip` |
| 4 | `M1_FUNDING_RESIDUAL_REVERSION_4H_Z2` | `v16_raw_gzip` |
| 5 | `M2_FUNDING_RESIDUAL_REVERSION_8H_Z2` | `v16_raw_gzip` |
| 6 | `M3_FUNDING_RESIDUAL_REVERSION_4H_Z2P5` | `v16_raw_gzip` |
| 7 | `DP1_EG_90D_Z2P5` | `v17_raw_json` |
| 8 | `DP2_EG_180D_Z2P5` | `v17_raw_json` |
| 9 | `DP3_EG_180D_Z3_STRICT` | `v17_raw_json` |

Exact artifact kimlikleri:

| Anahtar | Yol | Byte | SHA-256 |
|---|---|---:|---|
| `v16_prereg` | `configs/crypto_15m_v16_research_prereg.yaml` | `13052` | `bd41fc39b2e65a77b3aa2b396b676b0d4e2d315b9d3addac0e738e6f8b9e0fa3` |
| `v17_prereg` | `configs/crypto_15m_v17_pairs_prereg.yaml` | `21064` | `52d6b0e433e4145e17c588be88d3f82bc7ecb91e281fab12fd5450db12b6cc52` |
| `v16_raw_gzip` | `reports/research/crypto_15m_v16_primary_raw_2026-07-11.json.gz` | `488844` | `7e434d50280dadea4a730a1a8dac0f6436f92e36118082eef164f3638256265d` |
| `v17_raw_json` | `reports/research/crypto_15m_v17_pairs_primary_raw_2026-07-11.json` | `162198487` | `73e92a02131985a8a24c195c54c165b6775decef0ea41e24b6b34991edf4d82a` |
| `v17_raw_gzip_crosscheck` | `reports/research/crypto_15m_v17_pairs_primary_raw_2026-07-11.json.gz` | `7091723` | `6d9ded77ceed025b73259c44b2527caf60a9e0eacc8a21ddeb8c2990563e369d` |
| `v17_report_json` | `reports/research/crypto_15m_v17_pairs_report_2026-07-11.json` | `380701` | `ae234c398ac1390b39ac29210f92698523322687ef332e37c43243d75201a18d` |

V16 gzip açıldığında `1888565` byte ve
`9ebbe8620a7fb5b46eb958ce593e7e772a50f2380f54fc7b857f9cd488063d8e`
JSON SHA-256 kimliğini; V17 gzip ise `162198487` byte ve raw V17 ile aynı
`73e92a...f4d82a` SHA-256 kimliğini vermelidir.

Her eski aday için exact 36 finite H aylık yüzde-puan getirisi kronolojik
`2023-06`–`2026-05` aralığında
`/results/{candidate_id}/H/windows/pseudo_oos/monthly_returns_pct` yolundan
alınır. Yeniden hesaplanan p-değeri ve periodic Sharpe,
`/multiple_testing/program_wide_v16_plus_v17_exact_36x9/candidate_results/{candidate_id}/candidate_sign_flip_pvalue`
ve
`/multiple_testing/program_wide_v16_plus_v17_exact_36x9/candidate_results/{candidate_id}/periodic_monthly_sharpe`
yollarıyla; 9 üyeli Sharpe map'i ise aynı kökteki
`trial_periodic_monthly_sharpes` ile exact deterministic eşleşmelidir. Eksik
aday/ay/path, non-finite değer veya uyuşmazlık tüm cumulative testi
`UNVERIFIABLE` yapar.

Hiçbir hücre mutlak kapıları geçmezse sonuç `RED` olur ve LOSO çalıştırılmaz.
Geçenler H trimli ortalama (sıralamada `%15` cap), sonra düşük H DD, az negatif
ay, iyi worst-month, düşük turnover ve aday kimliğiyle deterministik sıralanır.
Yalnız tek kilitli winner gerçek LOSO alır; LOSO'da kalırsa runner-up denenmez.

## Adil baseline karşılaştırması

Eski `%21,36` pool başlığı baseline değildir. Karşılaştırma baseline'ı da exact
aynı V3 market, funding, primary-13, dönem, policy, execution, maliyet ve metrik
kodu üzerinde üretilmelidir. Challenger mutlak kapıları geçtikten sonra şu iki
yoldan biri ve stability non-inferiority gerekir:

1. H trimli aylık getiri `max(%10, baseline + 1,5 puan)` veya üstü, H MTM DD
   baseline'dan en fazla 1 puan kötü; veya
2. H trimli getiri baseline'ın 1 puan yakınında, H MTM DD en az `%25` düşük.

Her iki yolda H negatif ay sayısı ve en kötü ay baseline'dan kötü olamaz.
Baseline eksik veya evidence-ineligible ise “daha iyi bot” iddiası yapılamaz.

## Prospective kanıt

Historical winner doğrudan canlıya çıkamaz. Kaynak ve policy yeniden dondurulup
eşleşmiş shadow/paper kanıtı, **hem en az 90 takvim günü hem en az 100 kapanmış
trade tamamlanana kadar** sürer. Median gerçekleşen all-in maliyet historical C2
modeled medianını aşamaz; integrity failure sıfır, net sonuç pozitif ve 15m MTM
DD en fazla `%10` olmalıdır. Bu kapı geçse bile otomatik live deploy yasaktır;
ayrı insan risk/deployment kararı gerekir.

Makine-okunur tek otorite:
`configs/crypto_15m_v18_challenger_prereg.yaml`.
