---
doc_id: researcher-20260614T020100-chan-halflife-filtered-climax-fade-1d
doc_type: hypothesis
agent_id: researcher
created_at: 2026-06-14T02:01:00Z
status: DRAFT
confidence: low
depends_on:
  - researcher-20260604T000000-grimes-anti-climax-fade-crypto-1d
  - researcher-20260601T130000-grimes-anti-rsi-div-climax-fade
blocks: []
requested_review_from: [lab_scientist, risk_officer, adversary_engineer]
tags: [hypothesis, climax-fade, mean-reversion, chan-halflife, universe-filter, crypto-1d, pre-registration, high-curve-fit-risk]
supersedes: null
hash: null
---

# HYP-2026-06-14 — Chan Half-life Filtered Climax Fade (1D Crypto Perp)

## 0. Meta

- **Versiyon:** 0.1 (pre-registration; kod yazılmadan dondurulur)
- **Seed konu:** Günlük tarama — yeni RAG ekleri ışığında PA edge sinyalleri.
- **A priori beklenti:** **NEGATİF**. Climax-fade aynı evrende daha önce 2 kez (06-01 confluence, 06-04 vanilla) test edildi; bu üçüncü deneme. Multiple-trial inflation YÜKSEK; gerçek edge çıksa bile p-value yorumu konservatif olmalı.
- **Yeni boyut:** Chan (RAG #5) "Mean-reversion Sharpe ∝ 1/√half-life" — sadece kısa half-life'lı sembollerde climax-fade uygulamak edge'i konsantre eder mi? (Sembol-seçimi tabanlı edge; sinyal aynı.)

## 1. İddia (tek cümle, ölçülebilir, sayılı)

> 1D timeframe'de, USDT-perpetual delisting-aware evrende (2021-01-01 → 2026-05-01), her sembol için **trailing 180-bar AR(1) lag-1 katsayısı β** hesaplanır ve **half-life = −log(2) / log(β)** günde **[3, 14]** aralığında olan semboller "kabul" edilir (rolling; look-ahead yok). Kabul edilen sembollerde, herhangi bir bar `TR_t / ATR_200 > 2.0` olduğunda ("climax bar"), bir sonraki bar açılışında climax yönünün **KARŞI** yönünde pozisyon açılır (SL = climax ekstrem ± 0.25 × ATR_200, TP = 2R, risk_pct = 0.005, fee+slip round-trip 55 bps). Bu kurulum aynı pencerede şu gate'leri SAĞLAR:
>
> - **mean_R_net > +0.10R** (fee'yi geçen güvenlik payı)
> - **annual_return_net > %15** (compounded, account-equity bazlı)
> - **MaxDD (account-equity) < %25**
> - **N_trades ≥ 150** (istatistiksel power)
> - **shuffle-direction p_gross < 0.05** (50 seed)
> - **DSR (López) > 0.6**
> - **Filtre-içi Sharpe / Filtre-dışı Sharpe oranı ≥ 1.5** (yani filtrenin gerçekten değer kattığı kanıtı; yoksa half-life ekseni gürültü)

## 2. Null Hipotezleri (ne olursa çürür)

- **H0a:** shuffle-direction baseline'da p_gross ≥ 0.05 → yön sinyali yok, gerisi tartışılmaz.
- **H0b:** Filtre-içi Sharpe / Filtre-dışı Sharpe < 1.5 → half-life ekseninin **marjinal katkısı yok**; bu, "üçüncü climax-fade denemesi"ni özgün kılmaz → REDDET.
- **H0c:** Bonferroni / BH FDR sonrası (n=3 climax-fade denemesi × 7 gate = aile düzeltmesi) anlamlılık kaybı → overfit.
- **H0d:** IS / OOS Sharpe farkı > %50 → overfit.
- **H0e:** 6 yıllık walk-forward dilimlerin ≥ %50'sinde net negatif → istikrarsız.
- **H0f:** Half-life eşiği [3,14] yerine [2,10] veya [5,20] denendiğinde Sharpe sıralaması ZIDDA dönerse → eşik seçimi gürültü, edge yok.

## 3. Gerekçe (RAG referansları)

- **[Chan book_summary, RAG #5]** — "Mean-reversion stratejisinin Sharpe'ı half-life'ın square root'una **ters** orantılıdır." Half-life 5 gün vs 30 gün → ~2.4× Sharpe farkı. 1D climax-fade için mean-reversion mekaniği geçerli; half-life ile sembol seçimi DOĞRUDAN bu teoremi sınar.
- **[Grimes book_summary, RAG #3]** — "Anti" setup: ATR 2x+ climax sonrası contra-trend; WR ~%40-45, R 2-3R, EV hafif pozitif. **AÇIK UYARI: zor, yüksek-iskontolu, deneyimli traderlar için.** Mekanikleştirilmiş backtest'te edge erimesi olağan.
- **[Kaufman book_summary, RAG #6]** — Trend-exhaustion + confluence yararlı ama "RSI can stay overbought longer than you can stay solvent." Half-life filtresi bu uyarıyı somutlaştırır: uzun-momentum'lu sembollerde fade ölür.
- **[López book_summary, RAG #9]** — DSR < 0.5 = rastlantı; > 0.6 kabul eşiği. Bu hipotez 3. climax-fade denemesi olduğundan DSR > 0.6 zorunlu (multiple-trial deflation).
- **[Grimes book_summary, RAG #4]** — "Ignoring transaction costs in backtests" = #1 illüzyon kaynağı. 55 bps round-trip muhafazakar tutuldu.

## 4. Dependent Variables (önceden kilitli)

| Metrik | Tanım | Hesap noktası |
|---|---|---|
| `mean_R_net` | Trade başına ort. R, fee+slip dahil | Trade close |
| `annual_return_net` | Compounded annualized net return | Equity curve |
| `max_dd_equity` | Account-equity bazlı MaxDD | Equity curve |
| `n_trades` | Filtre-içi toplam trade sayısı | Backtest sonu |
| `win_rate` | (R>0 trade) / N | Tüm trade |
| `p_gross_shuffle` | 50 seed direction-shuffle null karşı p | Bootstrap |
| `sharpe_in_filter` | Half-life ∈ [3,14] evrendeki Sharpe (OOS) | WF |
| `sharpe_out_filter` | Half-life ∉ [3,14] evrendeki Sharpe (OOS) | WF |
| `filter_value_ratio` | sharpe_in / sharpe_out (≥1.5 hedef) | Hesaplanmış |
| `dsr` | Deflated Sharpe (trial=3 climax-fade denemesi varsayımı) | López formülü |
| `per_year_pos_count` | 6 yılın kaçında yıllık R_net > 0 | Yıllık dilim |
| `is_oos_sharpe_ratio` | IS Sharpe / OOS Sharpe | WF |

## 5. Independent Variables (DAR tut — multiple-testing kontrolü)

**KİLİTLİ baseline:**
- `climax_atr_mult`: **2.0** (sadece bu; 06-04 ile aynı taban)
- `atr_window`: **200**
- `halflife_lookback`: **180 bar** (Chan 1D bağlamında standart)
- `halflife_band`: **[3, 14] gün** (Chan'in 1-60 aralığının "1D-tradeable" alt-kesimi — *bu seçim curve-fit risk; bkz §6*)
- `sl_offset_atr`: **0.25**
- `tp_R`: **2.0**
- `risk_pct`: **0.005**
- `fee_round_trip_bps`: **55** (06-01/06-04 ile uyumlu)
- `pullback_window`: **0 bar** (climax bar t → t+1 open contra; "Anti pullback bar" yok — bu hipotezde half-life filtresi pullback-tanımı belirsizliğinin yerine geçiyor)

**Robustness (post-baseline; SOP-3 zorunlu, kararı DEĞİŞTİRMEZ):**
- `climax_atr_mult` ∈ {1.5, 2.5, 3.0} — perturbation
- `halflife_band` alternatif: {[2,10], [5,20], [4,18]} — eşik kırılganlığı testi (H0f)
- `tp_R` ∈ {1.5, 2.5} — perturbation

## 6. Curve-fit Şüpheleri (açıkça beyan — bu hipotezin **a priori riskleri**)

1. **Half-life eşiği [3,14] keyfi.** Chan 1-60 dedi; "1D-uygun" diye [3,14] seçtim → seçim sonradan veriye göre ayarlanırsa overfit. H0f bunu test eder; eşik bantları arasında Sharpe sıralaması istikrarsızsa REDDET.
2. **AR(1) tahmini gürültülü.** 180 barlık trailing pencerede β'nın SE'i geniş; half-life noisy. Rolling pencere uzatılırsa look-ahead riski; kısaltılırsa parametre gürültüsü artar.
3. **Look-ahead riski.** Half-life hesabı **rolling** yapılmalı; sembol "tüm 6 yılda half-life ortalaması" ile filtrelenirse → klasik selection bias. Backtest engine'de `t` barında karar `[t-180, t-1]` AR(1) ile alınır; bu zorunlu.
4. **Evren küçülmesi.** Filtre çoğu sembolü atarsa N_trades 150 altına düşer → power yok → terk. SOP-3'te min N gate'i.
5. **3. climax-fade denemesi.** 06-01 ve 06-04 zaten test edildi (sonuçlarına bakmadan bu hipotezi yazıyorum — pre-reg disiplini). Aile-düzeyinde Bonferroni: gerçek tek-test α=0.05 için bu denemede p < 0.017 gerekir (3 deneme aile).
6. **Sembol seçimi tabanlı edge ≠ sinyal edge'i.** Eğer half-life ∈ [3,14] sembolleri TÜM stratejilerde daha iyi performans gösteriyorsa → bu hipotezde bulunan Sharpe iyileşmesi climax-fade'e atfedilemez. **Plasebo testi:** aynı evrende **rastgele yönlü** entry'lerin Sharpe'ı; filtre-içi/dışı oranı climax-fade'inkinden farklı olmalı.

## 7. Beklenen p-value & Sample Size

- **Naive:** p < 0.01 (shuffle null karşı)
- **Family-corrected (n=3 climax-fade denemesi):** p < 0.017 gerekir
- **DSR (López):** trial=3 varsayımıyla > 0.6
- **N_trades:** ≥ 150 zorunlu; 150 altında power-yetersiz → terk

## 8. Stop Criteria (kod yazmadan dondurulur)

| Tetik | Aksiyon |
|---|---|
| IS Sharpe < 0.5 | terk (araştırma durdurulur) |
| N_trades < 100 | terk (power yok) |
| IS/OOS Sharpe farkı > %50 | RED (overfit) |
| Walk-forward 12 diliminin ≥ %50'si negatif | RED (istikrarsız) |
| LUNA (2022-05) veya FTX (2022-11) diliminde DD > %30 | RED (stres dayanıksız) |
| Filtre-içi / filtre-dışı Sharpe < 1.5 | RED (half-life ekseni gürültü, H0b) |
| Half-life bandı perturbasyonunda sıralama zıt | RED (H0f, eşik gürültü) |
| Plasebo (rastgele yön) testinde de filtre etkisi varsa | RED (sembol-seçimi confound) |
| Bonferroni-aile sonrası p ≥ 0.017 | RED (multiple-trial inflation) |
| DSR < 0.6 | RED (López şüphe eşiği) |

## 9. Robustness Plan (SOP-3 alt küme — zorunlu)

1. **Walk-forward:** 3y train + 6m test, step 3m (12 dilim).
2. **Symbol-out CV:** her sembol tek tek dışlandığında ortalama OOS değişmemeli.
3. **Regime split:** bull/bear/range — en az 2'sinde pozitif.
4. **Stress periodları:** 2022-05 (LUNA), 2022-11 (FTX), 2024-08 (Yen carry) — yıkıcı kayıp yok.
5. **Shuffle baseline:** direction-shuffle 50 seed, p < 0.05.
6. **Half-life bandı perturbasyonu:** {[2,10], [5,20], [4,18]} — Sharpe sıralaması istikrarlı mı?
7. **Plasebo:** rastgele-yön entry, filtre-içi/dışı Sharpe oranı.
8. **Multiple-testing düzeltme:** Bonferroni aile=3 (climax-fade denemeleri); ayrıca half-life perturbasyon sayısı (4) için BH FDR.

## 10. Karar Çerçevesi (post-backtest doldurulacak)

```
1. Tüm 7 gate sağlandı mı? ✓/✗
2. Stop criteria'dan herhangi biri tetiklendi mi? ✓/✗
3. Filtre-içi/dışı Sharpe oranı ≥ 1.5? ✓/✗ (kritik — yoksa özgün katkı yok)
4. Plasebo testi geçti mi (rastgele-yön etkisi yok)? ✓/✗
5. Karar: terfi adayı / RED / iterate
```

## 11. Iterate Politikası (SOP-4b)

Eğer **mean_R_net > 0** AMA gate'lerden ≥1'i RED:
- v2-tighter-band: halflife_band [4, 10] (daha seçici evren)
- v3-volatility-bracket: climax_atr_mult 2.0 → 2.5 (daha keskin climax)
- v4-time-exit: 7 bar içinde TP/SL değilse pozisyon kapat
- v5-be-protect: 1R sonrası SL → BE

Edge gerçek ama bandda değilse → "deferred" arşiv, RED değil.

## 12. Reproducibility

- git_hash: (backtest çalıştırılırken doldurulur)
- config_hash: bu doc'un SHA-256'sı (Lab tarafından)
- data_hash: 2021-01-01 → 2026-05-01 OHLCV USDT-perpetual snapshot (delisting-aware)
- backtest seed: 42 (sabit)
