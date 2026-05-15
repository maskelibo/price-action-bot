---
name: hyp-2026-05-14-three-push-wedge-fade
description: Brooks "Wedges and Three-Push Reversal Patterns" — 3 ascending pushes within convergent trend channel, 3rd push exhaustion bar → fade. Pure mean-reversion structural pattern.
metadata: { type: hypothesis, status: pre-registered, author: researcher, date: 2026-05-14, sprint: sec22, class: mean_reversion }
---

# HYP-2026-05-14-THREE-PUSH-WEDGE-FADE

## Kaynak (RAG / literatür)

- Al Brooks — "Trading Price Action Reversals" (Wiley 2012), **Chapter 5: Wedges and Other Three-Push Reversal Patterns**. ([O'Reilly online](https://www.oreilly.com/library/view/trading-price-action/9781118172308/OEBPS/9781118172308_epub_ch_05.htm))
- [Brooks Trading Course — 10 Best Patterns](https://www.brookstradingcourse.com/price-action/10-best-price-action-trading-patterns/) — three-push wedge among top patterns; "first target is the beginning of the pattern, next a measured move".
- [Wiley Online — Ch5 abstract](https://onlinelibrary.wiley.com/doi/abs/10.1002/9781119202622.ch5)
- Connors mean-reversion principle: 3 consecutive higher closes / lower closes precede reversal (statistical edge).

## Hipotez (pre-registered)

**İddia:** 1D crypto'da, 3 ardışık swing-high (her biri öncekinden marjinal olarak yüksek, wedge angle convergent) + 3rd-push exhaustion bar (küçük gövdeli + büyük üst kuyruk) tetiklenen bar-sembol kombolarında **SHORT** yönlü; mirror **LONG**. Beklenen mR > +0.20 (climax pattern Brooks claim'i + Connors 3-consecutive edge).

**Null:** mR ≤ +0.10 VEYA shuffle p ≥ 0.05.

## Mekanik kurallar (vektörize)

**Swing pivots (fractal, lookahead-free):**
- `pivot_high[i] = (high[i] == high[i-2:i+3].max()) AND (high[i] > high[i-1]) AND (high[i] > high[i+1])` — 5-bar fractal (n=2). Sadece bar i+2 kapandıktan sonra confirmed.
- Equivalent for pivot_low.

**Bearish 3-Push Wedge (SHORT setup):**

Önkoşul (bar t — current confirmation bar):
- En son 3 confirmed pivot_high'ları bul: `PH3 (oldest), PH2, PH1 (newest)` within last `lookback=30` bar.
- Ascending sequence: `PH1 > PH2 > PH3`
- Marjinal yükseliş (climax characteristic, NOT strong impulse):
  - `(PH1 - PH2) / PH2 in [0.005, 0.05]` (between 0.5% and 5% — bigger = parabolic impulsive, not exhaustion)
  - `(PH2 - PH3) / PH3 in [0.005, 0.05]`
- Wedge convergence: pivot_low'ları da bul (PL2 between PH3-PH2, PL1 between PH2-PH1):
  - `PL1 > PL2` (rising lows — wedge bottom angle UP)
  - Wedge angle: trend channel line slope (PH3→PH1) > base line slope (PL2→PL1) — pattern converging.
  - Simplified: `(PH1-PH3)/n_bars_PH3_PH1 < (PL1-PL2)/n_bars_PL2_PL1` (top slope softening relative to bottom = exhaustion proxy)

Trigger (bar t — at or just after PH1):
- `t - idx(PH1) ∈ [0, 3]` (within 3 bars after PH1)
- Exhaustion bar criteria at t:
  - Body ratio `|close[t]-open[t]| / (high[t]-low[t]) < 0.40` (small body)
  - Upper wick ratio `(high[t] - max(open,close)) / (high[t]-low[t]) > 0.40` (rejection)
  - `close[t] < PH1` (failed to close at the high)
- ATR%(14) ≥ 0.5%
- Cooldown 10 bar same direction

**Bullish 3-Push (LONG, mirror):** 3 descending pivot_lows (PL3 > PL2 > PL1 each by 0.5-5%), descending pivot_highs forming wedge, small-body upper rejection-wick bar at/after PL1.

**Entry / exits:**
- Entry: bar t+1 open
- SL:
  - SHORT: high[t] + 0.5 × ATR(14) (above exhaustion bar high)
  - LONG: low[t] - 0.5 × ATR(14)
- TP1: PH3 (oldest push) — "first target is the beginning of the pattern" Brooks rule, partial 50%
- TP2: 2.0R primary, partial 30%
- Runner: 20%, engine default trail
- Cooldown: same symbol same side 10 bar

**Lookahead-free audit:**
- Pivots use 5-bar fractal (n=2): pivot at bar i is detected at bar i+2 (after the 2 right bars). So pivot_high.shift(2) effectively means PH1 must be confirmed = i+2 closed.
- We require `t >= idx(PH1) + 2` for PH1 confirmation.
- Window-iterative `last_3_pivot_highs` scanned from bars `[t-30, t-2]` (always confirmed).

## Beklenen edge

- Standalone mR: +0.20 ile +0.35 — Brooks climax claim güçlü.
- n tahmini: rare pattern. 5y × 11 sym × ~10-15 valid 3-push/yıl/sym ≈ 550-825 raw. After all filters (wedge convergence, body ratio, marjinal yükselish) %50-70 azalır → 200-400 net.
  - Risk: n<150 olabilir → HARD gate FAIL.
- Mevcut'la overlap: Brooks H2/L2 single-bar, failed_BO trade-of-day single-bar. Bu MULTI-BAR pattern, orthogonal.

## Fail kriterleri

**HARD:** n<150, WR≤0.35, mR≤+0.10, shuffle p≥0.05, max_R≥10.

**SOFT:**
1. ≥80% trade single-side (regime bias risk)
2. Hold > 20d median (slow exhaustion → reversal kuvvetsiz)
3. Symbol-out CV dev > 30%
4. Margin gain bar count > 0 (lookahead-free audit fail)

## Test planı

1. `src/price_action/strategies/three_push_wedge_fade.py` — vektörize pivot detection + multi-bar pattern scan
2. Standalone gather 5y × 11 sym
3. Robustness:
   - lookback {20, 30, 40}
   - marginal_gain_max {0.03, 0.05, 0.08}
   - body_ratio_max {0.30, 0.40, 0.50}
4. Shuffle baseline 200 perm
5. Hold dist + max_R audit
6. **NO ensemble retest** — Engineering slot fix sonrası

## Beklenen sonuç olasılığı

- Standalone PASS: ~%45 (Brooks claim strong ama vektörize pivot detection daha az "subjective", filtre setup'a tam uymayabilir)
- Ensemble PASS: ~%20 (multi-bar pattern, daha az tetik, slot rekabeti daha az — relatif şansı normal)
- Final aday production: ~%12

**Yapısal risk:** Pattern subjective klasik trader pattern; vektörize implement orijinal "trader gözünden gördüğü" wedge'lerin sadece %30-50'sini yakalar. False positives muhtemel.

## STRATEGY_CLASS

```python
STRATEGY_CLASS = 'mean_reversion'  # Engineering SEC21 taxonomy
```
