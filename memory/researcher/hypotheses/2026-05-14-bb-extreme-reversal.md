---
name: hyp-2026-05-14-bb-extreme-reversal
description: Bollinger Bands 2.5-sigma extreme close-outside-then-back-inside reversal with rejection wick. Pure mean-reversion volatility extreme pattern.
metadata: { type: hypothesis, status: pre-registered, author: researcher, date: 2026-05-14, sprint: sec22, class: mean_reversion }
---

# HYP-2026-05-14-BB-EXTREME-REVERSAL

## Kaynak (RAG / literatür)

- John Bollinger — "Bollinger on Bollinger Bands" (2001). Mean-reversion principle: 95% of price action falls within ±2σ; close outside = statistical extreme.
- [StockCharts ChartSchool — Bollinger Band Squeeze](https://chartschool.stockcharts.com/table-of-contents/trading-strategies-and-models/trading-strategies/bollinger-band-squeeze) — band excursions and reversal mechanics.
- [Aurra Markets — 3 Proven BB Strategies (Bounce/Squeeze/Trend)](https://www.aurra.markets/academy/advanced-guides/3-proven-bollinger-bands-strategies-bounce-squeeze-and-trend) — "bounce" strategy: close outside followed by reversion to middle.
- [GoCharting BB Bands Standard Deviation](https://gocharting.com/docs/orderflow/vwapbands) — ±2.5 to ±3σ as "extreme" zones for mean-reversion entry.
- Pre-existing repo: `bollinger_squeeze_breakout` is OPPOSITE (low vol → breakout direction). This is HIGH vol extreme → reversion direction.

## Hipotez (pre-registered)

**İddia:** 1D crypto'da, bar t-1 close > BB(20, 2.5σ) upper VEYA close < BB(20, 2.5σ) lower (extreme statistical excursion), bar t close back inside band + rejection wick (upper-wick > %40 range for short / lower-wick > %40 range for long), tetiklenen bar-sembol kombolarında mean-reversion mR > +0.15.

**Null:** mR ≤ +0.10 VEYA shuffle p ≥ 0.05.

## Mekanik kurallar (vektörize)

**Indicators (lookahead-free, all on past close):**
- `BB_mid20 = close.rolling(20).mean()`
- `BB_std20 = close.rolling(20).std(ddof=0)`
- `BB_upper25 = BB_mid20 + 2.5 * BB_std20`
- `BB_lower25 = BB_mid20 - 2.5 * BB_std20`
- `BB_upper20 = BB_mid20 + 2.0 * BB_std20` — orta band (TP1 hedef)
- `BB_lower20 = BB_mid20 - 2.0 * BB_std20`
- `ATR14 = _atr(df, 14)`

**Bearish BB Extreme Reversal (SHORT):**
- Bar t-1: `close[t-1] > BB_upper25[t-1]` (extreme excursion, t-1 already closed)
- Bar t: `close[t] < BB_upper25[t]` (close back inside extreme band) AND `close[t] < high[t-1]` (rejection)
- Rejection wick at t: `(high[t] - max(open[t], close[t])) / (high[t] - low[t]) > 0.40`
- Body bearish: `close[t] < open[t]` (extra rejection confirmation; alternative: close < mid_bar)
- ATR%(14) ≥ 0.5%
- BB Width (BB_upper25 - BB_lower25) / BB_mid20 > 0.04 — band gerçekten geniş olmalı (squeeze değil, expansion mid'i)
- Cooldown same direction 7 bar

**Bullish BB Extreme Reversal (LONG, mirror):**
- Bar t-1: `close[t-1] < BB_lower25[t-1]`
- Bar t: `close[t] > BB_lower25[t]` AND `close[t] > low[t-1]`
- Lower wick: `(min(open[t], close[t]) - low[t]) / (high[t] - low[t]) > 0.40`
- Body bullish: `close[t] > open[t]`
- ATR%, BB width same.

**Entry / exits:**
- Entry: bar t+1 open
- SL:
  - SHORT: high[t-1] + 0.25 × ATR(14) (above the extreme excursion bar high)
  - LONG: low[t-1] - 0.25 × ATR(14)
- TP1: BB_mid20[t] (reversion to mean — classic BB mean-rev), partial 50%
- TP2: 2.0R, partial 30%
- Runner: 20%, engine default trail

**Lookahead-free audit:**
- BB at bar t computed from rolling 20 closes ending at t (causal). BB_upper25[t-1] used for t-1 extreme check is from data up to t-1. All shifts are explicit `.shift(1)` or indexing `[t-1]`. Pattern bar t evaluated at close[t], entry t+1 open.

## Beklenen edge

- Standalone mR: +0.15 ile +0.30 — BB mean-rev classical edge well documented stocks/FX. Crypto'da 2-σ-plus extreme excursion'lar nadirden çok değil (haftalık 1-2 bar/sym).
- n tahmini: 5y × 11 sym × ~10-20 valid setup/yıl/sym ≈ 550-1100 raw. After rejection wick + body confirm filters ~ %50 azalır → 300-550 net trade. Bol n.
- Mevcut'la overlap:
  - `bollinger_squeeze_breakout`: ZIT yön (squeeze → breakout). Bu expansion → fade. Mekanik orthogonal.
  - `anchored_vwap_reversal`: AVWAP+POC structural, RSI14 filtre — bu BB statistical extreme. Tetik bar farklı.
  - `fvg_fill_reversal`: 3-bar imbalance gap. Bu 2-bar excursion+reversion. Pattern orthogonal.

## Fail kriterleri

**HARD:** n<150, WR≤0.35, mR≤+0.10, shuffle p≥0.05, max_R≥10.

**SOFT:**
1. Long/short asymmetry > 3x (extreme bull-cycle bias)
2. Median R < -0.5 + max_R yüksek = unstable
3. Hold time median > 15 bar (mean-rev fast olmali)
4. Symbol-out CV dev > 30%

## Test planı

1. `src/price_action/strategies/bb_extreme_reversal.py` (vektörize)
2. Standalone gather 5y × 11 sym
3. Robustness:
   - BB σ {2.0, 2.5, 3.0}
   - Wick threshold {0.30, 0.40, 0.50}
   - Body confirmation ON/OFF
4. Shuffle baseline 200 perm
5. Hold dist + max_R + median_R audit
6. **NO ensemble retest** — Engineering slot fix sonrası

## Beklenen sonuç olasılığı

- Standalone PASS: ~%65 (BB mean-rev edge well documented, classical pattern, n bol)
- Ensemble PASS: ~%30
- Final aday production: ~%20

**Yapısal risk:** Crypto sustained-trend rejimlerinde (2024 bull) extreme close > +2.5σ trade'leri SHORT yapmak bull-trend yenmek demek; EMA200/dominance filtresi olmadan losing streaks. Bu sprint'te trend filter eklemiyoruz (saf BB mean-rev'i test ederiz), ama postmortem'de regime breakdown gereği değerlendirilir.

## STRATEGY_CLASS

```python
STRATEGY_CLASS = 'mean_reversion'  # Engineering SEC21 taxonomy
```
