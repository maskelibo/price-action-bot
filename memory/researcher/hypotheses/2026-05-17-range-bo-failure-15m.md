# HYP-2026-05-17-range-bo-failure-15m

**Pre-registered:** 2026-05-17 (kod öncesi)
**Sprint:** SEC-S5 MR pool (15m R4 ensemble diversification)
**Owner:** Researcher

## 1. Bağlam ve Motivasyon

15m R4 walk-forward +%735 / DD -29.6% / r-adj 21.83 ama CV %223, 20 sıfır ay,
9 negatif ay. Pool **trend-continuation** ağırlıklı.

**Bu hipotez (Strategy #3 of 3):** **Failed breakout (false break + reclaim)**
MR stratejisi. Asıl "trap" pattern'i. Tom Bulkowski "Throwbacks and Pullbacks"
%47-67 başarı oranı kantitatif.

BB-fade ve RSI-extreme statik osilatör/band tabanlı. Bu hipotez **structural**
(range BO failure) — pool'a tamamen farklı bilgi kaynağı katar.

## 2. İddia (Falsifiable)

**H1:** 15m TF'de, Bollinger Squeeze (BB_width < percentile_25, lookback=200) +
1 bar içinde breakout + **3 bar içinde reclaim** (close geri opposite band'a
döner) + reversal candle → fade-direction edge:

- Standalone mean R ≥ **+0.10**
- p-value (shuffle null) < **0.10**
- WR ≥ %48

**H0:** Range BO failure pool R dağılımı shuffle null'dan ayırt edilemez.

## 3. Literatür Dayanağı

1. **Bulkowski (2005):** "Encyclopedia of Chart Patterns" Ch.43 — Throwbacks %48,
   Pullbacks %47-67 reclaim oranı.
2. **Bollinger (2002):** "Bollinger on Bollinger Bands" — Squeeze pattern,
   BB_width contraction → expansion, false expansion sonrasi reclaim sıkı edge.
3. **Linda Raschke & Connors (1995):** "Street Smarts" — "Turtle Soup" setup:
   20-bar HH/LL false break + same-bar reclaim, 71% historic win rate.
4. **Brooks (2012):** "Trading Price Action: Reversals" Ch.4 — Failed breakout
   bar (FBO) yüksek-prob reversal; %60+ WR raporları.
5. **İç stratejiler:** `brooks_failed_breakout` (TOP-4 R4) trend-continuation
   ağırlıklı; bu hipotez **range-filtered** ve **multi-bar reclaim window** ile
   ondan farklılaşır.

## 4. Strateji Kuralları

### Pattern

Hesaplama:
- BB(20, 2.0): upper, lower, width (= upper - lower)
- BB_width_percentile_25 = percentile_25(BB_width, lookback=200)
- Squeeze flag: BB_width(t) ≤ BB_width_percentile_25(t)

**Long (Fade Failed Down-Breakout = Reclaim from Below):**
1. Squeeze t-4 (4 bar önce squeeze aktif)
2. Bar(t-3) close < BB_lower(t-3) (aşağı breakout)
3. 1-3 bar içinde (t-2, t-1, t) — close > BB_lower (reclaim)
4. Bar(t-1) bullish reversal (close > open VE close > prev_close)
5. Filter: ATR%_pct ≥ 0.003
6. **Entry:** bar(t) open

**Short (Fade Failed Up-Breakout = Reclaim from Above):**
1. Squeeze t-4
2. Bar(t-3) close > BB_upper(t-3) (yukarı breakout)
3. 1-3 bar içinde close < BB_upper (reclaim)
4. Bar(t-1) bearish reversal (close < open VE close < prev_close)
5. Filter: ATR%_pct ≥ 0.003
6. **Entry:** bar(t) open

### Risk

- **SL:** structural — entry'den 1.5× ATR(14)
  - Long: failed-BO bar low - 0.3×ATR (ya da entry - 1.5×ATR, hangisi daha sıkı)
  - Short: failed-BO bar high + 0.3×ATR (ya da entry + 1.5×ATR)
- **TP:** 1.2R
- **Confluence score:** 2.5 (Turtle Soup high-prob → daha yüksek base)

## 5. Bağımsız Değişkenler (sabit)

| Param | Değer | Gerekçe |
|---|---|---|
| BB period | 20 | Standart |
| BB std | 2.0 | Standart |
| BB_width percentile lookback | 200 | ~2 gün 15m |
| Squeeze percentile threshold | 0.25 | İlk 25%-tile = squeeze |
| Reclaim window (bars) | 3 | Brooks/Raschke ilk 3 bar guidance |
| ATR period | 14 | Standart |
| ATR multiplier (SL) | 1.5 | R4 aynı |
| Primary R (TP) | 1.2 | R4 aynı |

**Curve-fitting bayrağı:** literatürden, optimization yok.

## 6. Pre-Registered Gate

**Standalone PASS:**
- [ ] n trade ≥ 500 (Squeeze sıkı filter, daha düşük density beklenir)
- [ ] mean R ≥ **+0.10**
- [ ] WR ≥ **%48**
- [ ] Shuffle p-value < **0.10**
- [ ] En az 2/3 regime split'te pozitif mR
- [ ] Symbol-out alpha sapma ≤ %50

**RED:** yukarıdakilerden biri FAIL.

## 7. Robustness Planı

Aynı: shuffle ×100, symbol-out 10× CV, regime split, stress periods.

## 8. Beklenen Sonuç

**Base case (45% prob):** Standalone mR +0.12-0.25, WR %50-55 (Turtle Soup
literature). Squeeze filter sıkı → n=500-2000. PASS muhtemel.

**Bull case (30% prob):** mR +0.25+, WR %55+. Brooks FBO + Raschke Turtle Soup
overlap → güçlü edge.

**Bear case (25% prob):** Reclaim window=3 çok geç. 15m'de momentum 3 bar
boyunca devam edebilir, reclaim trade artık trap'in trap'i olur → RED.

## 9. Stop Criteria

Standalone n < 300 ya da mR < +0.05 → archive.

## 10. Combined Ensemble Beklenti

3 strateji birlikte (BB-fade + RSI-ekstrem + Range-BO-failure):
- 3'ünden 2'si PASS bekleniyor (base case)
- Ensemble retest hedefleri (15m R4 + MR pool):
  - Sıfır ay 20 → ≤ 8
  - Negatif ay 9 → ≤ 6
  - CV %223 → ≤ %100
  - Mean +%17.33 → ≥ %20 korunur ya da artar
  - Yıllık +%735 → ≥ +%400 (azalma kabul, ≥+%400 kırmızı çizgi)

## 11. Reproducibility

- output: `reports/researcher/2026-05-17_sec_s5_mr_pool_results.md`
