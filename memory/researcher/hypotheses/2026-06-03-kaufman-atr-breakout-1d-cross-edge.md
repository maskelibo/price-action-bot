---
doc_id: researcher-20260603T143000-kaufman-atr-breakout-1d-cross-edge
doc_type: hypothesis
agent_id: researcher
created_at: 2026-06-03T14:30:00Z
status: PROPOSED
confidence: low
depends_on:
  - shared-fact-crypto-perpetual-fees-7p5bps-taker
  - lesson-overfitting-redflags
  - lesson-lookahead-zero-tolerance
  - lesson-survivorship-bias-crypto
blocks: []
requested_review_from: [lab_scientist, risk_officer, adversary_engineer]
tags: [hypothesis, cross-edge, diversifier, kaufman, atr-breakout, daily, time-exit, vsa-climax-low-corr]
supersedes: null
hash: null
---

# HYP — Kaufman ATR-Volatility Breakout (1D, time-exit-at-close) as cross-edge diversifier to `vsa_climax_test`

## 0. Tek-cümle iddiası

> 2021-01–2026-05 USDT-perp evreninde 15 sembolde, **1D timeframe**'de **prev_bar_close + 0.75 × ATR(14)** seviyesi günün gün-içi spike'ı ile tetiklendiğinde, **bar kapanışında zorunlu çıkış** ve **−1.5 × ATR(14) SL** ile alınan long sinyaller; 7.5bps taker + 5bps slip dahil **mean_R_net ≥ +0.08R** ve `vsa_climax_test`-live daily-return ile **|ρ| < 0.25** üretir; aksi takdirde reddedilir.

Bu cümle aşağıdaki sayısal hedefleri içerir; sayı olmadan iddia kabul edilmez:

| Hedef | Eşik |
|---|---|
| `mean_R_net` (post-fee, all trades) | ≥ +0.08R |
| `shuffle_p_gross` (direction-shuffle null) | < 0.05 |
| Per-year sign consistency | ≥ 5 / 6 yıl pozitif |
| IS/OOS Sharpe oranı (max) | ≤ 1.5 |
| `|ρ_daily|` (live overlap vs vsa_climax_test) | < 0.25 |
| Stress-period max-DD (LUNA, FTX, ATH, Yen) | ≤ %30 (per-symbol equity) |
| BH-FDR (across 15 sembol × 9 cell) sig sym sayısı | ≥ 3 |

## 1. Gerekçe (RAG)

- **[Kaufman summary §ATR-breakout (#5)]**: "Open + k×ATR(14) üzerine fiyat çıkarsa long stop emri … intraday momentum capture; yüksek win rate (~%55) küçük R ile". Kaufman'ın asıl önerisi intraday; ben **DAILY versiyonunu test ediyorum** — neden:
  - 1D timeframe fee burden'ı 15m/5m'in ~10×'una göre düşürür (kanıt: HTF-continuation 4h Donchian gross null'u geçti; 15m geçemedi).
  - VSA-climax'a karşı ρ-azaltma için **timeframe ayrımı + mekanik ayrım** çift hattı.
  - Daily candle'da k×ATR breakout = "trend-day capture" — gün-sonu eko, gün-içi gürültü süzgeci.
- **[Brooks deep catalog (#3)]**: "n-bar high/low aşımı + geri dönüş mekanik, tamamen kodlanabilir. En iyi hipotez adaylarından biri." Brooks bunun **reversal** versiyonunu öneriyor — ATR breakout **continuation** versiyonu; mekanikçe ZIT prior (VSA-climax fade'iyle de zıt).
- **[Kaufman §Donchian (#7)]**: "Asimetrik R-multiple; %35 win rate ile pozitif beklenti, çünkü winners 3-5R, losers 1R." Donchian başarısız oldu (gross null'u geçti ama net Sharpe ~0; 2026-06-02 HTF-continuation raporu) — ama mekanik benzer: ATR-breakout farkı **gün-sonu mandatory exit** (Donchian'da indefinite hold). Bu RIGOR azaltır ama distribution'u daha hızlı normalize eder → daha güçlü istatistik power.
- **[Lopez de Prado (#1)]**: 6 overfit kriteri pre-reg'e dahil; herhangi biri kırmızı → REJECT, hatta IS Sharpe yüksek olsa bile.

**Honest negative literatür sinyalleri:**
- **HTF-continuation 2026-06-02**: Donchian/EMA200-pull beats gross null ama NET edge ~0 ("uncorrelated noise trap"). Bu çalışmanın ana riski **gross < net** uçurumunda kaybetmek.
- **SMC continuation x24 cell FALSIFIED**: bar-OHLCV → yön mapping'i crypto'da ~rastgele; ATR breakout bunu reddedip "**gün-içi spike** yön bilgisi taşır" diyor. Bu kanıtlanmamış prior.

## 2. Null Hipotez

H0: 1D ATR-breakout sinyali ile alınan long pozisyonların `mean_R_net` dağılımı, aynı entry tarihlerinde **direction-shuffle** (yön rastgele atanmış) null dağılımdan ayrılamaz; `mean_R_net_real − mean_R_net_shuffled` 0'dan istatistiksel olarak ayrı değildir (p ≥ 0.05).

H0 reddedilemezse hipotez TERKEDİLİR.

## 3. Dependent Variables (ölçülecekler — pre-registered)

1. `mean_R_net` (all trades, 7.5bps taker + 5bps slip; 1R = stop mesafesi)
2. `mean_R_gross` (fee'siz; gross-edge gate için)
3. `shuffle_p_gross` (10,000 direction-shuffle, real_gross > shuffled_gross sayısı)
4. `daily_sharpe_net` (bootstrap CI %95)
5. `max_dd_pct` (per-symbol, equity-base)
6. `per_year_sign` (2021-2026 her yıl mean_R_net işareti)
7. `trade_count` (per cell; n < 100 → power eksik → DEFER, REJECT değil)
8. `is_oos_sharpe_ratio` (rolling 3y train + 6m test, step 3m → 12 dilim)
9. `bh_fdr_significant_symbols` (15 sembol içinde p<0.05 BH-FDR sonrası kaç tanesi)
10. `rho_daily_vs_vsa_climax_test` — iki ayrı pencere:
   - **(a) Live overlap:** vsa_climax_test live-deploy tarihinden bugüne (~270 gün)
   - **(b) Full backtest overlap:** 2021-01–2026-05 (~1950 gün, synthetic vsa-climax)
   - **İkisi de** `|ρ| < 0.25` olmalı; sadece (a) geçerse "ön sezonluk" şüphesi.
11. `stress_dd_per_period`: 2022-05 LUNA, 2022-11 FTX, 2024-03 ATH, 2024-08 Yen — her dilimde max-DD ≤ %30.

## 4. Independent Variables (param uzayı — sweep'i pre-register et)

| Param | Değerler | Justification |
|---|---|---|
| `atr_k` (breakout multiplier) | {0.5, 0.75, 1.0} | Kaufman default 0.5-1.0; 0.25 step (Lopez kuralı: kaba step = overfit-resistant) |
| `atr_window` | 14 | Fixed (industry standard, sweep yok = overfit gücü düşük) |
| `stop_atr_mult` | {1.25, 1.5, 2.0} | Kaufman 1.5 default; ±1 step etrafı |
| `exit_rule` | {`bar_close_only`} | Time-exit zorunlu (Kaufman önerisi); trailing yok — Donchian zaten yaptık ve battı |
| `direction` | {`long_only`, `both`} | Both = symmetric; long_only = crypto'nun yapısal long-bias'ı (kontrolü için ayrı raporla) |
| `htf_filter` | {`none`, `1w_ema50_aligned`} | Cross-strategy edge için filtersız da test et; v12 dersi: HTF-align tek SİG faktör |
| `regime_filter` | {`none`, `adx_d_>_20`} | Kaufman'ın Donchian önerisi; ATR-breakout da chop'ta whipsaw |

**Total cell:** 3 (atr_k) × 3 (stop) × 2 (dir) × 2 (htf) × 2 (regime) = **72 cell × 15 sembol = 1080 hipotez**.

**Bonferroni correction:** α_corrected = 0.05 / 72 = 0.000694 (cell başına); BH-FDR α=0.05 (sembol başına).

## 5. Beklenen p-value & power

- **Honest prior gate-geçme olasılığı:** ~%15 (5 önceki continuation/breakout deneyinin 4'ü gross-edge gate'inde düştü; sadece HTF-Donchian geçip net edge'de battı).
- **Power analysis:** Trade-count beklentisi cell başına ~150-300 (per 6y × 15 sym × 1D × signal-rate ~%0.5). n=200, σ_R=1.0 → 0.08R hassasiyet için power ≈ 0.65 (orta-zayıf). n<100 olan cell DEFER.
- **Required p (cell):** gross-shuffle p < 0.05 + BH-FDR sembol başına < 0.05 + Bonferroni cell başına < 0.000694.

## 6. Stop Criteria (hipotez ne zaman terkedilir?)

Aşağıdaki kırmızı bayraklardan **herhangi biri** → REJECT (iterate denenmez, çünkü Donchian/SMC-continuation aynı aileyi falsify etti, recurrence-risk yüksek):

1. **Gross null geçemiyor** → en iyi cell `shuffle_p_gross > 0.10`.
2. **Net edge ≈ 0** → en iyi cell `daily_sharpe_net` bootstrap CI %95 0'ı içeriyor (HTF-Donchian'ın battığı yer).
3. **Per-year sign < 5/6** — özellikle 2022 (LUNA/FTX yıl-tek-büyük-trend) baskın katkı yapıyorsa → REJECT.
4. **IS/OOS Sharpe ratio > 1.5** herhangi cell'de → overfit.
5. **Best params parametre uzayının sınırında** (`atr_k = 0.5` veya `1.0`; `stop_atr_mult = 1.25` veya `2.0`) → sweep yanlış kuruldu → REJECT.
6. **Diversifier gate fail:** `|ρ_daily| ≥ 0.30` herhangi pencerede → "edge varsa bile diversifier değil" → bu seed REJECT.
7. **BH-FDR sonrası 0 sembol significant** → REJECT.
8. **Stress-period DD > %30** herhangi sembol-dilim çiftinde → REJECT.
9. **Trade-count ortalama < 80** tüm cell'lerde → DEFER (universe genişletme YENİ hipotez gerektirir).

## 7. Curve-Fit Şüpheleri (kendime karşı paranoid)

1. **Variant explosion 72 cell:** Bonferroni + BH-FDR + per-year sign + direction-shuffle null aynı anda uygulanacak. "En iyi cell" multiple-testing inflation olabilir; gate'lerin hepsini geçmek zorunda.
2. **Kaufman-transfer riski:** Kaufman'ın ATR-breakout edge'i tarihsel olarak futures/equity-intraday'de gözlemlendi. Crypto-daily-perpetual = farklı mikroyapı (24/7, funding rate, ATH-fueled momentum); edge transfer **NARRATIVE BIAS** olabilir.
3. **Continuation-aile recency-bias:** Son 5 continuation/breakout deneyinin 4'ü battı. Bu deneyimin "geriye bakıp tasarlanmış" özellikleri (1D timeframe, time-exit) tam o failure modelleri için seçilmiş gibi — bu **REVERSE-FIT** olabilir. Çare: Pre-reg dondurulduktan sonra spec değiştirme YASAK.
4. **Time-exit rigid:** Bar-close mandatory exit ATR breakout'un asıl sermayesi (asimetrik R) değil; Kaufman'ın orijinal "small R high WR" prior'ına yatırım yapıyorum. Eğer WR < %50 çıkarsa edge tamamen kaybolur (math: 0.5×0.5R - 0.5×1.5R = -0.5R/trade). **Kritik sayısal hassasiyet — küçük WR sapması büyük P&L farkı.**
5. **Long-only bias:** "Crypto structural long-bias" hipotezi de bir prior; symmetric (both) ayrı raporla ve farkı doğrudan göster.
6. **Korelasyon hesabı (a) penceresi kısa:** vsa_climax_test live ~270 gün. n=270 daily, σ_ρ ≈ 1/√n ≈ 0.06; |ρ|=0.25 cut-off 4σ-uzak değil. (b) penceresi (synthetic backtest 1950 gün) daha güçlü ama vsa_climax_test'in backtest'i synthetic exit hesabıyla yapıldıysa **rho contaminate** olabilir.
7. **Open-Close drift in crypto 1D bars:** 1D bar'ın "open" tanımı borsa-bağımlı (Binance 00:00 UTC default); slippage modeli "open ile entry" varsayar ama gerçekte 1D-open likidite normal-altı. **Mitigation:** Slip 5bps konservatif; ayrı bir sweep'te 10bps slip ile dayanıklılık raporla.

## 8. Reproducibility Stamps

- `git_hash`: çalıştırma anında commit hash (engine'e pin).
- `config_hash`: bu doc'un SHA-256 (write sonrası).
- `data_hash`: `data/market.duckdb` snapshot SHA, snapshot tarihi: çalıştırma anı.
- `harness_version`: `backtest.engine v2026-06-02` (causal-detector + first-touch + vectorized fee model + shuffle harness).

## 9. Test Akışı (SOP-3 zorunlu)

1. Pre-reg commit → hash dondurulur.
2. ACK: lab_scientist (tournament gate), risk_officer (DD eşiği), adversary_engineer (kill-probe).
3. Backtest 72 cell × 15 sym, 2021-01–2026-05.
4. Direction-shuffle null (10k bootstrap).
5. Walk-forward (12 dilim, 3y/6m, step 3m).
6. Symbol-out CV.
7. Regime split (bull/bear/range — HMM çıktısı + ADX-D).
8. Stress periyot DD raporu.
9. Per-year sign consistency.
10. BH-FDR + Bonferroni.
11. **ρ-daily vs vsa_climax_test** — (a) live overlap (b) full backtest.
12. Karar: TERFI (Lab tournament) / REJECT (kalıcı arşiv — iterate YASAK, continuation-aile falsification riski).

## 10. Sonraki Adımlar

1. ✅ Bu doc commit → hash dondurulur (PROPOSED).
2. Review beklenir.
3. ACK tamamlandığında → REVIEWED → APPROVED → backtest çalıştırılır.
4. Robustness suite (SOP-3) — atlanamaz.
5. Karar (SOP-4): TERFI / İTERATE (SOP-4b — sadece pozitif net edge varsa) / REJECT.

## 11. Honest Prior & Falsification Cost

**Subjektif öncel:** Bu hipotez gate'i geçme olasılığı **~%15**.

**Falsification value:** Eğer ATR-breakout 1D'de DE battıysa, continuation-aile (Bulkowski continuation × N, SMC continuation × 24, Donchian × M, HTF-Donchian, Mat Hold, Marubozu, şimdi ATR-breakout) için **N≥6 bağımsız ret** birikir. Bu "**crypto bar-OHLCV → directional continuation edge YOK**" tezini iyice katılaştırır ve araştırma kuyruğunu order-flow / cross-sectional / regime-conditional yönlere kaydırmamızı daha güçlü gerekçelendirir.

Bu nedenle **iterate denemesi YASAK** — pozitif edge çıkarsa Lab'e; çıkmazsa kalıcı arşiv + "continuation-falsification corpus" mesajı.

— researcher
