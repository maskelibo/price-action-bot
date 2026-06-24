# HYP-2026-05-17-bb-continuation-15m

**Pre-registered:** 2026-05-17T15:10:56Z (kod oncesi, timestamp)
**Sprint:** Yol G (SEC-S5 directional flip follow-up)
**Owner:** Researcher
**Predecessor:** HYP-2026-05-17-bollinger-fade-mr-15m (RED) + directional flip yan-bulgu

**Status:** **RED-STANDALONE** (single WR gate miss, mR+p strong) - 2026-05-17 closed
- Result: n=16,340, mR +0.1996, **WR 51.4% < 55% gate**, p=0.000, regime 3/3 pos
- Pre-reg "HEPSI zorunlu" -> ensemble retest YAPILMADI
- Yan-bulgu Lab tournament adayi (Tier-B/relaxed gate)
- Verdict: `reports/researcher/2026-05-17_yol_g_summary.md`

## 1. Baglam ve Motivasyon

SEC-S5 MR pool sprint sonucu (2026-05-17 ogleden once):
- 3/3 MR fade strategy RED (standalone gate fail)
- AMA `_sec_s5_directional_flip_check.py` (fee-adj 10bps RT) gosterdi ki:

| Strategy | n | mR(fade) | WR(fade) | mR(rev, fee-adj) | WR(rev) |
|---|---:|---:|---:|---:|---:|
| bollinger_fade_mr | 513 | -0.295 | 38.4% | **+0.195** | **59.6%** |
| rsi_extreme_mr | 9 | -0.501 | 22.2% | +0.401 | 66.7% (n az) |
| range_bo_failure_mr | 19,510 | -0.169 | 43.8% | +0.069 | 54.4% |

**Insight:** 15m crypto'da BB outer touch + RSI extreme + reversal candle =
**continuation** sinyali (fade DEGIL). Sebep hipotezleri:

1. **Intraday momentum dominance:** 15m crypto'da BB outer break ile gelen
   itki, mean-reversion'dan once devam egilimi gosteriyor.
2. **Fee asimetrisi:** 15m TF'de RT fee (10bps) MR'in zayif edge'ini yutuyor;
   continuation'da exit MFE yuksek oldugu icin fee gomulebiliyor.
3. **Connors/Kaufman MR literaturu 15m crypto'da gecersiz:** orijinal model
   gunluk equity (slow vol) + low fee (~5bps RT) ortami icin tasarlandi.

**Hedef (R4 ensemble mandate gap):**
- Su an: Annual +%1076 PASS, Mean %28.91 PASS, Zero 0 PASS, **Neg 7 (1 fazla)**, **CV 144% (44pp fazla)**
- Beklenen Yol G effect: +5-10pp annual uplift, Neg 7 -> 4-5, CV 144 -> 110-130

## 2. Iddia (Falsifiable)

**H1:** 15m timeframe'de, Bollinger Band (period=20, std=2.0) **outer band
touch** + RSI(14) ekstrem (sikilastirilmis: >75 / <25 ya da >80/<20) +
**ayni yondeki momentum confirm candle** ile **trigger direction'da
continuation** girisi pozitif edge uretir:

- Standalone mean R >= **+0.15** (gate; fade rev raw +0.195'in altinda)
- WR >= **%55** (fade rev raw %59.6'nin altinda - safety margin)
- p-value (shuffle null, n=200) < **0.10**
- n trade >= 500
- >= 2/3 regime split pozitif
- symbol-out worst sapma <= 50%

**H0 (null):** Reverse direction pool R dagilimi shuffle null'dan ayirt
edilemez (p >= 0.10), VEYA mean R < +0.15, VEYA WR < %55.

**Yapisal H_alt (challenge):** Eger threshold sikilastirma (RSI 75/25 yerine
80/20) n'i 500'un altina dusurur ve mR > +0.15 kalmazsa -> rev edge fade'in
basit isaret donusumu degil, gercek "high-quality momentum continuation"
edge'i degil; ham fade pool'unun reverse mirror'i yapay artifact.

## 3. Literatur Dayanagi

1. **Brooks (2012, "Trading Price Action: Trends" ch.16):** Failed breakout
   sonrasi BBR (Brooks Break Reversal) follow-through trend continuation
   icin literaturun kuvvetli adayi - 15m intraday futures.
2. **Adam Grimes (2018, "Art and Science of Technical Analysis" §11):**
   "Trend-with-pullback" entries - BB outer touch HTF trend yonunde
   pullback complete sinyali (continuation, fade degil).
3. **Volman (2013, "Forex Price Action Scalping"):** 15m FX'te BB outer
   + momentum candle close = "kapanis breakout" continuation.
4. **Beggs (2018, "Trading Pullbacks"):** Crypto 15m'de RSI extreme +
   trend direction = momentum exhaust onesinde "last push" sinyali.
5. **Phoenix ic deneyim:**
   - SEC-S5 directional flip check (2026-05-17): mR(rev) +0.195 raw.
   - 15m R4 baseline TOP-4'un 3'u trend-continuation (vsa, brooks_fb,
     anchored_vwap_reversal, engulfing_continuation) - pool zaten
     continuation-friendly.

## 4. Strateji Kurallari

### Pattern v1 (default, primary - n>=500 hedef)

**LONG (Continuation up):**
1. Bar(t-1) close > BB_upper (outer band BREAKING from above - asagi yonden
   asma degil; close-above-upper momentum signal)
2. RSI(14) at t-1 > 75 (sikilastirilmis ekstrem - daha cok kalite)
3. **NO ADX filter** (range/trend agnostik; momentum istegimiz)
4. Bar(t-1) momentum candle: close > open AND body_pct >= 0.5 *
   (high-low) - yani true momentum bar, doji degil
5. Filter: ATR%_pct >= 0.003 (15m noise tabani)
6. **Entry:** bar(t) open

**SHORT (Continuation down):**
1. Bar(t-1) close < BB_lower
2. RSI(14) at t-1 < 25
3. **NO ADX filter**
4. Bar(t-1) momentum candle: close < open AND body_pct >= 0.5 * range
5. Filter: ATR%_pct >= 0.003
6. **Entry:** bar(t) open

### Pattern v2 (alt - sample density check, n_v1 < 500 ise pre-reg fallback)

Eger v1 n<500 ise (cok sikilastirildi), v2 thresholds:
- RSI 70/30 (orijinal default)
- Body_pct >= 0.4

Bu v2 pre-reg edildigi icin post-hoc cherry-pick degil; karar agaci asagidaki
gibi SADECE bir kez yapilir, multiple-testing correction NULL hipotez icin
gerekli degil (PASS gate aciklayicidir).

### Risk

- **SL:** structural - uzaklik entry'den 1.5x ATR(14) (R4 ile ayni)
  - Long: max(swing_low(10), entry - 1.5xATR) - **continuation icin SL
    fade'den farkli yon**: structural floor altinda kalan en yakin swing
  - Short: min(swing_high(10), entry + 1.5xATR)
- **TP:** 1.2R (15m scalp short hedef, R4 ile ayni fee-aware)
- **Confluence:** 2.0 base + 0.5 bonus (BB break + RSI ekstrem + momentum)

## 5. Bagimsiz Degiskenler (parametre uzayi - sabitlenmis)

| Param | v1 deger | v2 deger | Gerekce |
|---|---|---|---|
| BB period | 20 | 20 | Bollinger standart |
| BB std | 2.0 | 2.0 | Standart 2 sigma |
| RSI period | 14 | 14 | Wilder standart |
| RSI oversold (long thr <) | 25 | 30 | v1 sikilastirilmis kalite, v2 default |
| RSI overbought (short thr >) | 75 | 70 | Simetri |
| ADX filter | YOK | YOK | Continuation - regime-agnostik |
| ATR multiplier (SL) | 1.5 | 1.5 | R4 ile ayni |
| Primary R (TP) | 1.2 | 1.2 | 15m fee-grave (R4 ile ayni) |
| Body ratio (momentum confirm) | 0.5 | 0.4 | Body / range; doji elemek |
| BB touch type | close beyond | close beyond | high-quality break (low touch degil) |

**Curve-fitting bayragi:**
- Sadece 2 threshold variant (v1, v2) - post-hoc cherry pick yok.
- Karar agaci: v1 dene, eger n<500 ise v2'ye gec, evaluate v2.
- Optimization yok, literatur thresholdlari.

## 6. Bagimli Degiskenler

- Pool stats: n trade, mean R, sumR, WR%
- Per-symbol mean R (10 sym leave-one-out)
- Per-regime split (2022 bear, 2024 bull, 2025-2026 range)
- Shuffle null p-value (n=200)
- Look-ahead audit (statik kod analizi + ts ordering check)

## 7. Pre-Registered Gate (KARAR)

**Standalone PASS kosullari (HEPSI):**
- [ ] n trade >= **500**
- [ ] mean R >= **+0.15**
- [ ] WR >= **%55**
- [ ] Shuffle p-value < **0.10**
- [ ] En az 2/3 regime split'te pozitif mR (bull/range/bear)
- [ ] Symbol-out worst leave-one-out mR sapma <= %50

**RED kosullari (HERHANGI BIRI):**
- Yukaridakilerden biri FAIL
- Curve-fit kirmizi bayrak (sample tek symbolde >40%)
- Look-ahead audit FAIL
- v1 ve v2 ikisi de fail

**Karar agaci:**
1. v1 run -> n hesapla
2. v1 n >= 500 ise v1 evaluate (tum gate). PASS -> ensemble step.
3. v1 n < 500 ise v2 run, v2 evaluate (tum gate). PASS -> ensemble step.
4. Hicbiri PASS degil -> RED, archive.

## 8. Robustness Plani

1. Shuffle null x 200 iterasyon - mR alpha p < 0.10
2. Symbol-out 10x CV - en kotu leave-one-out mR sapma
3. Regime split: 2022 (bear), 2024 (bull), 2025-2026 (range/mixed)
4. Look-ahead static audit: shift(1) discipline, no t-data leakage
5. Curve-fit guard: top-2 symbol concentration < %60

## 9. Beklenen Sonuc

**Base case (60% prob):** v1 n ~400-800 (sikilastirma sebebiyle borderline),
mR +0.15 ile +0.25 arasi, p<0.10 PASS. v2 daha guvenli n~1500-3000, mR
+0.10 ile +0.20.

**Bull case (20% prob):** v1 mR +0.25+, ensemble retest mandate gap full
kapanir (Neg 7->4, CV 144->110).

**Bear case (20% prob):** v1 ve v2 ikisi de border (mR ~ +0.10-0.12, WR
~%53-54). Rev edge sirf fade pool'un mirror artifact - gercek
continuation-momentum edge'i degil. RED.

## 10. Stop Criteria (pesin)

- v1 n < 200 ise (BB+RSI sikilastirilmis cok daraltti) -> v2'ye dus,
  v2 evaluate.
- v1 OR v2 mR < +0.05 -> tum sprint RED, ensemble retest yapma.
- v1 OR v2 PASS olursa ensemble retest yap; eger ensemble mandate
  improvement < +2pp annual ise yine "ensemble RED, standalone PARTIAL"
  declare.

## 11. Reproducibility

- git_hash: (sprint sonrasi commit)
- config: `configs/risk_phoenix_scalp_15m_pyramid_r3.yaml` (mc=20 override)
- data: `data/sec_s5_mr_pool.pkl` (sembol cache), yeni
  `data/sec_s5_yol_g_bb_cont_pool.pkl` (bu sprint cache)
- code: `src/price_action/strategies/bb_band_continuation.py` (yeni)
- scripts: `scripts/sec_s5_yol_g_standalone.py`,
  `scripts/sec_s5_yol_g_ensemble_retest.py`
- pre-reg: bu dosya (2026-05-17T15:10:56Z)
- reports: `reports/researcher/2026-05-17_yol_g_bb_continuation_standalone.md`,
  `reports/researcher/2026-05-17_yol_g_ensemble_retest.md`,
  `reports/researcher/2026-05-17_yol_g_summary.md`
- learning: `memory/researcher/learning_20260517_yol_g_bb_continuation.md`

## 12. Distincion vs. SEC-S5 fade sprint

| Boyut | Fade (RED) | Continuation (bu) |
|---|---|---|
| Signal direction | BB upper touch -> SHORT | BB upper close-beyond -> LONG |
| RSI thr | 30/70 default | 25/75 v1 (sikilastirilmis) |
| ADX filter | <20 (range only) | YOK (regime-agnostik) |
| Candle confirm | Reversal (hammer / counter-body) | Momentum (continuation body) |
| BB touch type | Wick touches band (low/high) | Close beyond band (true break) |
| Pre-reg hipotez | Fade reversion | Momentum continuation |
| Lit dayanagi | Bollinger/Connors/Wilder MR | Brooks/Grimes/Volman trend-cont |

**Falsifiability key:** Eger continuation edge gercekten varsa, **simetrik
fade nin tam tersi** bir thresholdda ortaya cikmali. Fade testte mR(rev)
+0.195 idi - continuation pre-reg gate +0.15 bunun altinda kasten safety
margin. Eger gate PASS olmaz, hipotez gercekten falsified.
