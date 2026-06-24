# HYP-2026-05-17-rsi-extreme-mr-15m

**Pre-registered:** 2026-05-17 (kod öncesi)
**Sprint:** SEC-S5 MR pool (15m R4 ensemble diversification)
**Owner:** Researcher

## 1. Bağlam ve Motivasyon

15m R4 walk-forward yıllık +%735.73 / DD -29.61% / r-adj 21.83 / 34/34 pozitif
ama:
- Mean +%17.33, CV %223
- 9 negatif ay, **20 sıfır-trade ay**

Pool trend-continuation ağırlıklı. **Mid-vol range rejimde MR alpha gerek.**

**Bu hipotez (Strategy #2 of 3):** Saf RSI(14) ekstrem + range rejim
(ATR%-pct düşük) + reversal candle confirm. BB-fade'in **alternatifi/komplementeri**.
BB band-extension RSI'dan farklı bir bilgi → multi-feature confluence yerine
**farklı detector ile ek trade pool**.

## 2. İddia (Falsifiable)

**H1:** 15m TF'de, RSI(14) < 25 (oversold) ya da RSI(14) > 75 (overbought) +
ATR%-percentile düşük (son 200 barın %30 percentile altı = range) + reversal
candle (hammer/shooting-star) → fade reversion pozitif edge:

- Standalone mean R ≥ **+0.10**
- p-value (shuffle null) < **0.10**
- WR ≥ %48

**H0:** RSI ekstrem + range filter pool R dağılımı shuffle null'dan ayırt
edilemez (p ≥ 0.10) ya da mean R < +0.10.

## 3. Literatür Dayanağı

1. **Wilder (1978):** "New Concepts in Technical Trading" — RSI orijinal,
   70/30 standart, ekstrem 80/20.
2. **Connors & Alvarez (2009):** "Short-term Trading Strategies That Work" —
   RSI(2) <5 / >95 + 5-bar TF MR edge (RSI(14) için 25/75 muadili).
3. **Cardwell (1999):** "Trading with Connors VIX Reversals" — RSI 25/75 daha
   az false signal, 30/70'den daha güçlü filter.
4. **Bulkowski (2008):** "Encyclopedia of Candlestick Charts" — hammer/inverted-
   hammer reversal probability +%55-60.
5. **Sec4 naked_poc_mr içsel deneyim:** MR sınıfında izole edge (+0.35 mR)
   bulundu, RSI tabanlı versiyonu test edilmedi.

## 4. Strateji Kuralları

### Pattern

**Long (Fade Oversold):**
1. RSI(14) at t-1 < **25** (ekstrem oversold)
2. ATR%(t-1) ≤ percentile_30(ATR%, lookback=200) — **range rejim**
3. Bar(t-1) hammer-like:
   - lower_wick ≥ 1.5 × body_abs
   - upper_wick ≤ 0.5 × body_abs
   - close > open (bullish body)
4. Bar(t-1) close > prev_low (recovery confirm)
5. Filter: ATR%_pct ≥ 0.003 (15m noise tabanı — `if too low: skip`)
6. **Entry:** bar(t) open

**Short (Fade Overbought):**
1. RSI(14) at t-1 > **75**
2. ATR%(t-1) ≤ percentile_30(ATR%, lookback=200)
3. Bar(t-1) shooting-star-like:
   - upper_wick ≥ 1.5 × body_abs
   - lower_wick ≤ 0.5 × body_abs
   - close < open
4. Bar(t-1) close < prev_high
5. Filter: ATR%_pct ≥ 0.003
6. **Entry:** bar(t) open

### Risk

- **SL:** structural — uzaklık entry'den 1.5× ATR(14)
  - Long: min(low(t-1) - 0.3×ATR, entry - 1.5×ATR)
  - Short: max(high(t-1) + 0.3×ATR, entry + 1.5×ATR)
- **TP:** 1.2R
- **Confluence score:** 2.0

## 5. Bağımsız Değişkenler (sabit)

| Param | Değer | Gerekçe |
|---|---|---|
| RSI period | 14 | Wilder standart |
| RSI oversold | 25 | Cardwell ekstrem (30'dan daha güvenli) |
| RSI overbought | 75 | Simetri |
| ATR period | 14 | Standart |
| ATR%-percentile lookback | 200 | ~2 gün 15m (regime estimation) |
| ATR%-percentile threshold | 0.30 | İlk 30%-tile = range |
| Wick ratio (hammer) | 1.5 | Bulkowski standart |
| ATR multiplier (SL) | 1.5 | R4 aynı |
| Primary R (TP) | 1.2 | R4 aynı |

**Curve-fitting bayrağı:** parametreler literatürden, optimization yok.

## 6. Pre-Registered Gate

**Standalone PASS:**
- [ ] n trade ≥ 1000
- [ ] mean R ≥ **+0.10**
- [ ] WR ≥ **%48**
- [ ] Shuffle p-value < **0.10**
- [ ] En az 2/3 regime split'te pozitif mR
- [ ] Symbol-out alpha sapma ≤ %50

**RED:** yukarıdakilerden biri FAIL.

## 7. Robustness Planı

Aynı: shuffle ×100, symbol-out 10× CV, regime split, stress periods.

## 8. Beklenen Sonuç

**Base case (50% prob):** Standalone mR +0.08 ile +0.18 arası. Range filter
ile entry frekansı düşer ama edge konsantre olur. p<0.10 PASS olabilir.

**Bull case (20% prob):** mR +0.18+, BB-fade'den farklı bar'larda tetiklenir
→ ensemble retest pool çeşitlendirici.

**Bear case (30% prob):** RSI 14 + range filter 15m'de geç tetik. Hammer
sonrası downward continuation devam edebilir → RED.

## 9. Stop Criteria

Standalone n < 500 ya da mR < +0.05 → archive.

## 10. Reproducibility

- output: `reports/researcher/2026-05-17_sec_s5_mr_pool_results.md`
