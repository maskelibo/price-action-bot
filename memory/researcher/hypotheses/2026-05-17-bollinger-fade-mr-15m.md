# HYP-2026-05-17-bollinger-fade-mr-15m

**Pre-registered:** 2026-05-17 (kod öncesi)
**Sprint:** SEC-S5 MR pool (15m R4 ensemble diversification)
**Owner:** Researcher

## 1. Bağlam ve Motivasyon

15m R4 (vsa+brooks_fb+vwap+engulfing) walk-forward yıllık +%735 / DD -29.6%
/ r-adj 21.83 / 34/34 pozitif (production-class) bulundu. Per-ay analizinde:

- Mean +%17.33, **CV %223**
- 9 negatif ay
- **20 sıfır-trade ay** (capitulation halt yakalanan range/dip rejimleri)

Pool **trend-continuation ağırlıklı**. Bull rejimde patlama, range/bear
rejimde sıfır. Vol-target sweep yapıldı → FAIL (kök neden regime-concentration,
vol noise değil).

**Hipotez (Yol D):** Pool'a **Mean-Reversion (MR)** ekleyerek:
- Sıfır ayları doldur (mid-vol range rejim)
- Negatif ayları telafi et (trend-cont stop hit → MR fade catch)
- Hedef: CV ≤ %100, mean ≥ %20, sıfır+neg ≤ 10/61, yıllık ≥ +%400

## 2. İddia (Falsifiable)

**H1:** 15m timeframe'de, Bollinger Band (period=20, std=2.0) **outer band
touch** + RSI(14) ekstrem (>70 short / <30 long) + **range regime** (ADX(14)
< 20) koşulunda **fade reversion** girişi pozitif edge üretir:

- Standalone mean R ≥ **+0.10** (gate)
- p-value (shuffle null, n=100) < **0.10**
- Sharpe (per-symbol) > 0.30
- WR ≥ %48 (1.2R target ile breakeven %45 → %48 buffer)

**H0 (null):** Pool R dağılımı shuffle null'dan ayırt edilemez (p ≥ 0.10),
veya mean R < +0.10.

## 3. Literatür Dayanağı

1. **Bollinger (1980s, 2002):** "Bollinger on Bollinger Bands" — outer band
   touch + momentum osc divergence Bollinger'in temel fade kurulumu.
2. **Connors & Alvarez (2009):** "Short-term Trading Strategies That Work" —
   RSI(2) < 5 / > 95 + 5-bar TF'de mean reversion edge dokümante.
3. **Wilder (1978):** "New Concepts in Technical Trading" — ADX < 20 = trendsiz
   rejim (mean reversion için optimal koşul).
4. **Kaufman (2013):** "Trading Systems and Methods" §15 — BB squeeze + reversion
   crypto-like high-vol asset'lerde dokümante.
5. **Phoenix iç deneyim:** SEC4 vol_risk_premium (mR +1.80, n=düşük), Sec4
   naked_poc_mr (mR +0.35) MR sınıfında izole edge olduğunu gösteriyor.

## 4. Strateji Kuralları

### Pattern

**Long (Fade Oversold):**
1. Bar(t-1) low ≤ BB_lower (close-based, std=2.0)
2. RSI(14) at t-1 < 30
3. ADX(14) at t-1 < 20 (range rejim)
4. Bar(t-1) bullish reversal: close > open ya da lower-wick > 2× body
5. Filter: ATR%_pct ≥ 0.003 (15m noise tabanı)
6. **Entry:** bar(t) open (t-1 close sonrası karar)

**Short (Fade Overbought):**
1. Bar(t-1) high ≥ BB_upper
2. RSI(14) at t-1 > 70
3. ADX(14) at t-1 < 20
4. Bar(t-1) bearish reversal: close < open ya da upper-wick > 2× body
5. Filter: ATR%_pct ≥ 0.003
6. **Entry:** bar(t) open

### Risk

- **SL:** structural — uzaklık entry'den 1.5× ATR(14)
  - Long: min(swing_low(10), entry - 1.5×ATR)
  - Short: max(swing_high(10), entry + 1.5×ATR)
- **TP:** 1.2R (15m scalp short hedef, fee-aware)
- **Confluence score:** 2.0 base + 0.5 bonus (BB touch + RSI ekstrem confluence)

## 5. Bağımsız Değişkenler (parametre uzayı — sabitlenmiş)

| Param | Değer | Gerekçe |
|---|---|---|
| BB period | 20 | Bollinger standart |
| BB std | 2.0 | Standart 2σ |
| RSI period | 14 | Wilder standart |
| RSI oversold | 30 | Connors var ama 30 daha tutucu, fewer-but-stronger |
| RSI overbought | 70 | Simetri |
| ADX period | 14 | Wilder standart |
| ADX threshold | 20 | Wilder range rejim eşiği |
| ATR period | 14 | Standart |
| ATR multiplier (SL) | 1.5 | 15m scalp R4 ile aynı |
| Primary R (TP) | 1.2 | 15m fee-grave hızlı realizasyon (R4 ile aynı) |
| Wick ratio (reversal confirm) | 2.0 | Hammer/inverted-hammer literatür |

**Curve-fitting bayrağı:** parametreler **literatürden** alındı, optimization
yok. Tek-pass test.

## 6. Bağımlı Değişkenler

- Pool stats: n trade, mean R, sumR, WR%
- Per-symbol Sharpe ve mean R (10 sym leave-one-out)
- Per-regime split (2022 bear, 2024 bull, 2025 range)
- Shuffle null p-value (n=100)
- Walk-forward 34-pencere positive ratio (ensemble retest sonrası)

## 7. Pre-Registered Gate (KARAR)

**Standalone PASS koşulları (HEPSİ):**
- [ ] n trade ≥ 1000 (sample density)
- [ ] mean R ≥ **+0.10**
- [ ] WR ≥ **%48**
- [ ] Shuffle p-value < **0.10**
- [ ] En az 2/3 regime split'te pozitif mR (bull/range/bear)
- [ ] Symbol-out alpha sapma ≤ %50 (en kötü leave-one-out)

**RED koşulları (HERHANGİ BİRİ):**
- Yukarıdakilerden biri FAIL
- Curve-fit kırmızı bayrak (sample concentration tek symbolde)
- Look-ahead audit FAIL

## 8. Robustness Planı

1. Shuffle null × 100 iterasyon — mR alpha p < 0.10
2. Symbol-out 10× CV — en kötü leave-one-out mR sapma
3. Regime split: 2022 (bear), 2024 (bull), 2025-2026 (range/mixed)
4. Stress: 2022-05 (LUNA), 2022-11 (FTX), 2024-08 (Yen carry)

## 9. Beklenen Sonuç

**Base case (60% prob):** Standalone mR +0.10 ile +0.20 arası, p<0.10 PASS.
Range rejimde güçlü, bull/bear'de marjinal pozitif.

**Bull case (20% prob):** mR +0.20+, ensemble retest CV %223 → ~%100 düşüş.

**Bear case (20% prob):** mR < +0.10 (RED). Range rejimi 15m'de fee-grave (entry
tetiklendiği anda momentum cont devam ediyor — fade erken).

## 10. Stop Criteria (peşin)

Standalone n < 500 ya da mR < +0.05 → **kod ile uğraşma, archive**.
Ensemble retest yıllık < +%400 ise (15m R4 baseline'dan %50+ kayıp) →
combined RED, alternatif Yol E (1h pivot) ya da Yol F (re-weight) öner.

## 11. Reproducibility

- git_hash: (sprint başında commit gerekli)
- config: `configs/risk_phoenix_scalp_15m_mr_combined.yaml` (oluşturulacak)
- data_hash: `data/sec31_15m_pool.pkl` (MR strategies için ek collect)
- output: `reports/researcher/2026-05-17_sec_s5_mr_pool_results.md`
