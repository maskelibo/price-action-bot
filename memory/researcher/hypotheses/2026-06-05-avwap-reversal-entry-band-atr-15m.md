---
doc_id: researcher-20260605T140000-avwap-reversal-entry-band-atr-15m
doc_type: hypothesis
agent_id: researcher
created_at: 2026-06-05T14:00:00Z
status: PROPOSED
confidence: low
depends_on: [researcher-20260603T000000-avwap-reversal-band-sweep]
blocks: []
requested_review_from: [lab_scientist, risk_officer, adversary_engineer]
tags: [hypothesis, avwap, mean_reversion, parameter_sweep, atr_distance, curve_fit_risk, complementary_axis]
supersedes: null
hash: null
---

# HYP-2026-06-05-avwap-reversal-entry-band-atr-15m

## 0. Prior Doküman ile İlişki (override edilemez transparency)

Bu hipotez, `researcher-20260603T000000-avwap-reversal-band-sweep` ile **kasıtlı olarak DAR ÖRTÜŞMEZ**:

| Axis | Prior (2026-06-03) | Bu hipotez (2026-06-05) |
|---|---|---|
| TF | 1h | **15m** |
| Band metric | σ_AVWAP (rolling stddev) | **ATR(14)·k** (volatility-normalize, σ-AVWAP couple yok) |
| Anchor | UTC 00:00 (tek) | UTC 00:00 **VE** son 24h swing-high (iki, sweep'in parçası) |
| k grid | {0.5, 1.0, 1.5, 2.0, 2.5, 3.0} | **{0.75, 1.25, 1.75, 2.25}** (4 değer, kaba) |
| Universe | 15 USDT perp | aynı 15 sembol (paralel ölçüm için) |

Eğer prior PROPOSED→REJECTED olursa bu hipotez **otomatik düşmez**: farklı bant metriği ve farklı TF ayrı bir null testidir. Eğer prior'ın koşumu burayı subset olarak kapsayan bir sonuca ulaşırsa bu doc SUPERSEDED işaretlenir.

## 1. İddia (pre-registered, ölçülebilir)

**H1:** "15m timeframe'de, **anchored VWAP** (anchor = max(UTC 00:00, son 24h swing-high-bar)), fiyatın AVWAP'tan **k · ATR(14)** mesafede reddedilmesi (rejection bar: AVWAP+k·ATR'yi wick'leyip, close AVWAP+k·ATR'nin AÇIK tarafında ve `close < open` short / `close > open` long), bar kapanışında karar, **t+1 open**'da giriş, **ATR-stop = 1.0·ATR**, **R:R = 1.5:1**, 2020-01..2026-06 USDT-perpetual evreninde (15 likit sembol):

- **gross mean_R > 0** ve **shuffle p_gross < 0.05** (yön-shuffle null'u yenmek, **BH-FDR (q=0.05) sonrası**)
- **fee+slippage 55bps sonrası net mean_R > +0.04R**
- **annualized OOS Sharpe > 0.7**
- **MaxDD < %25**
- **profit factor > 1.25**
- **per-year sign consistency**: 6 yıldan en az 5'i pozitif (2020, 2021, 2022, 2023, 2024, 2025)
- **per-anchor independence**: UTC-anchor ve swing-anchor varyantlarının **her ikisi de** ayrı ayrı gross-p<0.05 (aksi halde anchor şansı)"

**Parameter sweep:** k ∈ {0.75, 1.25, 1.75, 2.25} (4) × anchor ∈ {UTC, swing} (2) × direction ∈ {long, short, both} (3) × 15 sembol → **360 koşum**.

## 2. Null Hipotez (H0)

"15m AVWAP-mesafe-rejection sinyali, k ve anchor seçiminden bağımsız olarak, yön-shuffle null'undan **BH-FDR (q=0.05) düzeltmesi sonrası** istatistiksel olarak ayırt edilemez (≥1 survivor zorunlu) VEYA ayırt edilse bile net mean_R (55bps fee+slip sonrası) ≤ 0."

H0 reddedilemezse → hipotez reddedilir. (Çift kriter: gross-edge **VE** net-edge eşzamanlı şart.)

## 3. Gerekçe (RAG + prior tecrübe)

**Olumlu argümanlar (zayıf):**
- [#6 Stockcharts MA] Price-cross-MA mantığı: kısa MA üstünde fiyat → bull, altında → bear. AVWAP, volume-weighted bir MA türevi; k·ATR offset eklemek "tampon" mantığı (whipsaw azaltma). Aynı kaynak: "choppy markets produce false positives" — biz tam tersi bahis: rejection-at-band sadece choppy/balanced rejimde çalışır.
- [#1 Stockcharts confluence] "robust setups combine pre-identified S/R + candlestick + volume" — saf AVWAP-distance tek faktör, confluence'tan yoksun. Bu seed kasıtlı **single-factor stress test**: AVWAP-distance tek başına bilgi taşıyor mu?
- [#3 Bulkowski outside-bar] reversal rate %63-65 ama "Tek başına yeterli değil; S/R veya EMA temas şart." AVWAP **EMA-benzeri** bir line; rejection-at-AVWAP+kATR kavramsal olarak Bulkowski'nin "EMA-touch reversal"'ı.

**Karşı-prior (kuvvetli, başlıca curve-fit alarmı):**
- **`learning.md` 2026-06-01..06-02:** Reversal-at-level family 4 kez crypto bar-OHLCV'de gross-edge gate'inden geçemedi (Fabio order-flow forex, Fabio value-area crypto, SFP iter-2, SMC continuation). Ortak neden: **crypto bar-OHLCV'de yön ~rastgele**. AVWAP-distance da bar-OHLCV-türev → aynı sonucu beklemek apriori-rasyonel.
- **Smaller-TF penalty:** 15m'de bar başına fee_R (sl_pct~0.012, 55bps) yaklaşık 0.92R/round-trip; gross edge gross-mean-R'nin ≥%200'ünü aşmazsa net negatif. Bu, prior 1h hipotezinden (sl_pct~0.020, fee_R~0.55) çok daha sert bir net-eşik. **Bu hipotezin geçmesi prior'dan zor.**

**Yine de tescil ediyoruz çünkü:**
- (a) ATR-distance (σ_AVWAP yerine) AVWAP'tan farklı bir volatility-normalize axis — eğer **prior σ-based** geçer ama **bu ATR-based** geçmezse → "edge AVWAP'tan değil, σ-mesafenin kendisinden geliyor" sonucu çıkar (faydalı negatif bilgi).
- (b) Anchor sweep (UTC vs swing) anchor'ın bilgi taşıyıp taşımadığını ayırır.
- (c) Reddedilirse **5. kanıt** "crypto bar-OHLCV reversal-at-level family deprecated" tezini Lab'ın `learning.md`'sine güçlü gönderecek.

## 4. Dependent Variables (ölçülecek, pre-registered)

| Metric | Hedef | Cut-off |
|---|---|---|
| gross mean_R | > 0 | > 0.015R |
| shuffle p_gross (BH-FDR sonrası) | < 0.05 | < 0.05 |
| BH-FDR (q=0.05) survivor count | ≥ 5 | ≥ 5 / 360 |
| net mean_R (55bps fee+slip) | > 0.04R | > 0.04R |
| OOS Sharpe (annualized) | > 0.7 | > 0.7 |
| MaxDD | < %25 | < %25 |
| profit factor | > 1.25 | > 1.25 |
| per-year positive ratio | ≥ 5/6 | ≥ 5/6 |
| trade count (3y, all syms) | > 1500 | > 1500 (15m'de mecbur) |
| **anchor robustness** | UTC ve swing AYRI AYRI gross-p<0.05 | her iki anchor için ayrı survivor zorunlu |
| **IS/OOS Sharpe ratio** | ≥ 0.7 | ≥ 0.7 (aksi halde fit) |

## 5. Independent Variables (sweep edilecek)

| Variable | Domain | Cardinality | Sweep mi? |
|---|---|---|---|
| k (ATR multiplier) | {0.75, 1.25, 1.75, 2.25} | 4 | EVET |
| anchor | {UTC 00:00, son 24h swing-high} | 2 | EVET |
| direction | {long, short, both} | 3 | EVET |
| symbol | 15 likit USDT perp | 15 | EVET (per-sym ölçüm) |
| **stop_atr_mult** | 1.0 | 1 | **DONDURULDU** |
| **rr** | 1.5 | 1 | **DONDURULDU** |
| **tf** | 15m | 1 | **DONDURULDU** |
| **rejection bar tanımı** | wick + bar close açık tarafta | 1 | **DONDURULDU** |
| **ATR window** | 14 bar | 1 | **DONDURULDU** |

**Toplam koşum:** 4 × 2 × 3 × 15 = **360 backtest**. BH-FDR (q=0.05) tüm 360 p_gross üzerinde.

**Curve-fit guards (önceden taahhüt):**
- Grid kasıtlı kaba (k adımı 0.5, 0.01 değil) — fine-grid p-hacking yok.
- stop_atr_mult, rr, tf, ATR window, rejection-bar tanımı **DONDURULMUŞ** — sweep'in dışında; geri açılırsa **yeni hipotez** zorunlu (bu hipotez SUPERSEDED).
- IS/OOS split **a-priori sabit**: IS=2020-01..2023-12, OOS=2024-01..2026-06. OOS sweep tekrarı yapılmayacak (bir kez ölç, tekrarlama).
- "Best run" tek başına terfiye götürmez — **BH-FDR survivor cluster** + **per-year ≥5/6** zorunlu.

## 6. Beklenen p-value & Multiple Testing Correction

- **Raw p_gross hedefi:** En az 1 koşumda p_gross < 0.000139 (Bonferroni eşik 0.05/360 ≈ 1.39e-4) — bilgi için ölçülecek.
- **BH-FDR (q=0.05) hedefi:** En az **5 survivor** zorunlu (her iki anchor altında en az 1'er tane — anchor şansı reddi).
- **Robustness:** FDR-geçen koşumların per-year sign consistency ≥ 5/6 ve symbol-out CV'de ort. Sharpe değişimi < ±%25.

## 7. Stop Criteria (araştırma terkedilir)

Aşağıdaki HER BİRİ tek başına araştırmayı **REJECT + arşiv** kategorisine alır (iterate denemeden):

1. **Gross-edge ölü:** 360 koşumun >%92'sinde p_gross > 0.5 → reversal-at-level family confirmation **5. kanıt**. `learning.md`'ye yaz, AVWAP family için "no further bar-OHLCV variants" notu.
2. **BH-FDR sonrası 0 survivor.** → null reddedilemedi, hipotez REJECT.
3. **Trade count düşük:** Ort. koşum < 500 trade (3y, 15m'de bu çok kötü) → sinyal çok seyrek, ölçüm gürültülü.
4. **In-sample mucize:** En iyi koşum IS Sharpe > 2.5 ve OOS Sharpe < 0.4 → overfit kanıtı, koy ve reddet (curve-fit case study).
5. **Param edge'de:** Best k = 0.75 veya k = 2.25 (sweep'in kenarı) → optimum dışarıda, anlamsız. **Genişletme yapma**, yeni hipotez yaz.
6. **Anchor şansı:** Sadece UTC veya sadece swing anchor survivor üretti, diğeri tüm runs'ta p>0.5 → anchor cherry-pick, REJECT.
7. **Single-symbol baskın:** Toplam pnl'in >%50'si tek sembolden → evrensellik yok.
8. **Single-year baskın:** Toplam pnl'in >%45'i tek yıldan → rejim şansı.
9. **net mean_R ≤ 0:** Gross pozitif olsa bile fee+slip sonrası negatif → cost-erosion (`widestop-threshold-validated.md` ders #1).
10. **Champion overlap >0.4:** Eğer bu sinyaller mevcut VSA-widestop champion'ı ile günlük-return korelasyonu >0.4 ise terfi adayı değil (diversifier görevi düşer).

## 8. Robustness Suite (zorunlu — SOP-3)

- [ ] Walk-forward: 3y IS / 6m OOS, step 3m, 12 dilim. Her dilim için BH-FDR.
- [ ] Random param perturb: k ±%10, 50 seed → ort. Sharpe kaybı < %30.
- [ ] Symbol-out CV: her sembolü çıkar, ort. OOS Sharpe değişimi < ±%25.
- [ ] Regime split: bull (2020-Q3..2021, 2024) / bear (2022) / range (2023, 2025) — en az **2 rejimde** pozitif (her ikisi de bull olmamalı).
- [ ] Stress periyotları: LUNA 2022-05, FTX 2022-11, BTC-ATH 2024-03, Yen-carry 2024-08 — drawdown < champion bot şu anki MaxDD'si.
- [ ] Shuffle baseline (yön shuffle, 1000 perm) p < 0.05 BH-FDR sonrası.
- [ ] Causality test: `detector(df.iloc[:t+1])[t] == detector(df)[t]` (no lookahead).
- [ ] Survivorship-aware universe (delisting'ler dahil — `lessons/survivorship_kripto.md`).
- [ ] **Flip-test:** Sinyalin tersi (anti-AVWAP-rejection) p_gross > 0.5 olmalı (eğer ters de edge gösteriyorsa = data leakage).

## 9. Curve-fit Şüphesi (explicit flag — gözardı edilirse hipotez geçersiz)

**Bu hipotez 5 yönden curve-fit riskli — explicit pre-commit:**

1. **Parameter sweep size**: 360 koşum → BH-FDR olmadan ~18 false positive bekle (360 × 0.05). FDR uygulanmazsa "best k" anlamsız.
2. **Prior reject mass**: 4 önceki reversal-at-level family redde uğradı; bu seed yine reversal-at-level. Apriori prior **negatif**.
3. **Donmuş axes (stop_atr_mult=1.0, rr=1.5, ATR window=14)** ÖNCE seçildi. Eğer sonradan "1.0 yerine 1.5 stop daha iyi" çıkarsa **bu hipotez geçersiz**, **yeni hipotez** yazılır. Geri tarama yasak.
4. **TF=15m fee penalty**: net gate'i geçmek prior 1h'tan daha zor. Eğer geçerse ekstra şüpheyle robustness suite'i tekrar koş.
5. **Anchor combo "UTC OR son swing"**: çoklu anchor secip "hangisi çalışırsa onu seç" cherry-pick olur. **Önlem**: anchor robustness gate (her iki anchor ayrı ayrı geçecek).

## 10. Reproducibility

- `git_hash`: Backtest koşulduğunda hash dondurulur (raporda).
- `data_hash`: `data/market.duckdb` MD5 raporda.
- `config_hash`: backtest config sha256 raporda.
- Backtest engine: `backtest/engine.py` (vectorized, lookahead-safe).
- Universe: survivorship-aware (delisting tarihleri DB'den).
- Random seed: 42 (perturb için), 1000 perm shuffle.

## 11. Beklenen Sonuç (apriori posterior)

| Senaryo | Prior | Aksiyon |
|---|---|---|
| Tüm sweep p_gross > 0.5 (gross-edge ölü) | **%78** | REJECT + arşiv, family confirmation #5 |
| Bazı koşumlar p<0.0002 ama OOS/per-year/regime düşürür | %15 | REJECT (curve-fit case study) |
| BH-FDR survivor var, OOS/regime/anchor robust ama net mean_R ≤ 0 | %4 | REJECT (cost-erosion, family ölü kanıt) |
| Hepsi geçer (gross + net + robustness + anchor robust) | **%3** | Terfi adayı → Lab tournament; ayrıca shock — gerekçesi araştırılır |

## 12. Stop-criteria özeti (TL;DR)

HERHANGİ BİRİ → REJECT:
- >%92 koşum p_gross > 0.5
- BH-FDR sonrası 0 survivor
- net mean_R ≤ 0
- IS/OOS Sharpe ratio < 0.5
- Best k sweep kenarında (0.75 veya 2.25)
- Sadece bir anchor çalışıyor (UTC veya swing)
- Single sym/year >%50 baskın
- Flip-test edge'i de pozitif (data leakage)
- Champion ile günlük-return korelasyonu > 0.4

## 13. Iterate Politikası (SOP-4b uygulanırsa)

Eğer **gross-edge geçer ama net mean_R DD>2× champion DD** olursa → **REJECT etme**, v2 iterate:
- v2-risk: risk_pct 0.005→0.002, max_concurrent 16→8
- v3-confluence: + EMA50-trend filter (sadece counter-trend rejection)
- v4-time: + session filter (sadece Asya seansı veya sadece US seansı)
- v5-BE-protect: 1R BE shift

**Iterate budget:** 5 versiyon. Hiçbiri tam gate'i geçmezse "edge gerçek ama kapasite dışı" notu + deferred arşiv.

Eğer gross-edge yoksa (stop 1, 2, 9) iterate **YOK** — temelden ölü.

---

**Pre-registration commit notu:** Bu hipotez koşulmadan önce git'e commit'lenir; hash raporda dondurulur. Sonradan parametre eklenmesi/donmuş axis'in açılması bu hipotezi **SUPERSEDED** yapar ve yeni hipotez gerektirir.
