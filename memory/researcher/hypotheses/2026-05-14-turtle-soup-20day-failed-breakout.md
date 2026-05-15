---
name: hyp-2026-05-14-turtle-soup-20day-failed-breakout
description: Linda Raschke Turtle Soup — fade a new 20-day high/low when price reclaims back inside range within 1-2 bars (failed breakout reversal).
metadata: { type: hypothesis, status: pre-registered, author: lab-scientist, date: 2026-05-14 }
---

# HYP-2026-05-14-turtle-soup-20day-failed-breakout: 20-Day Failed Breakout Reversal (Turtle Soup, Raschke-Connors)

## Kaynak
- Linda Raschke & Laurence Connors, "Street Smarts" (1996), strategy: Turtle Soup.
- New Trader U / TraderMastermind summary: short entry ~5-10 cents below prior 20-day high when current bar makes new high but closes back inside range; stop above the day's high; mean-reversion play. https://tradersmastermind.com/turtle-soup-trading-strategy-rules/ (accessed 2026-05-14)
- Liquidity-trap rationale: original "Turtle" 20-day breakout system is widely-known → stops cluster just beyond 20D extremes → sweep + reverse.

## Hipotez
Edge: 20-day high/low breakout is a famous, widely-followed signal → liquidity clusters above/below. When price ticks beyond the extreme but fails to hold (closes back inside), it is a stop-run that traps both breakout traders and tight-stop participants. Smart money fades. **Critical: this is the structural inverse of donchian_breakout (which is already in pool)** — Turtle Soup is the FAILURE of Donchian's exact signal, giving high orthogonality.

## Mekanik kurallar (entry/exit/filter)
- TF: 1d
- Lookback: 20-day high/low rolling, excluding current bar
- Setup (SHORT - bearish Turtle Soup):
  - high[t] > max(high[t-20:t-1]) (new 20-day high made)
  - close[t] < max(high[t-20:t-1]) (closed back inside prior 20D range)
  - body_range_ratio: |close[t] - open[t]| / (high[t] - low[t]) > 0.30 (rejection candle, not doji)
  - close[t] is bearish (close < open) OR upper wick > 2 × body (pin-bar-like rejection)
- Setup (LONG - bullish Turtle Soup): mirror image with 20-day low.
- Entry: market on close[t] (engine convention) → effective entry next bar open
- Stop: SHORT: high[t] + 0.25 × ATR(14); LONG: low[t] - 0.25 × ATR(14)
- TP1: 1.0R (close 50%)
- TP2: prior 20-day high midpoint OR 2.0R, whichever first (close 35%)
- Runner: 15% with trail = 1.5 × ATR after TP2
- Time exit: 5 bar (no progress to 1R within 5 days → flat)
- Filter:
  - Skip if t bar is the FIRST bar of a strong impulse (close >= prior bar close + 2 × ATR14 in direction of breakout — gerçek momentum break, fade etme)
  - Sym list: tüm 11 sym (BTC/ETH/SOL/... — Turtle Soup originally equities, but crypto has clear 20D Donchian followers)

## Test planı
- Asset: 11 production sym (BTC, ETH, SOL, AVAX, DOT, ATOM, LINK, MATIC, NEAR, ADA, XRP)
- TF: 1d
- Window: 5y (2021-01 → 2026-05)
- Baseline: v2.0.3 ensemble
- Tests:
  1. Standalone signal frequency: expected ~5-10 signals/sym/year ≈ 250-500 in 5y
  2. Standalone mR, WR, sumR
  3. Correlation vs donchian_breakout (expected negative — anti-signal)
  4. Ensemble integration with current production stack

## Pass kriterleri
- Standalone: n_trade ≥ 150, mR ≥ +0.20 (yüksek bekleniyor çünkü well-defined liquidity trap), WR ≥ %45, sumR > +50
- Correlation with donchian_breakout returns: ρ < -0.2 (kanıtlanmış orthogonality)
- Ensemble katkısı: yıllık +%3pp uplift VE DD ≤ baseline +%3pp
- 13 pencere walk-forward, en az 10 pencere pozitif

## Karşı-hipotez (RED kriteri)
- Crypto'da Donchian breakout edge bittiyse (HYP-2026-05-08 baseline donchian already in pool), Turtle Soup da kaybetmiş olabilir (false breakout sıkça gerçek breakout) — mR < 0 veya WR < %42 → RED
- Filter (impulse skip) çok agresif olursa n drops below 80 → invalid sample
- equal_highs_sweep stratejisi zaten benzer mantık kullanıyor; pure overlap riski → eğer correlation > 0.7, drop (Sec5 öğrenmesi)

## Implementation notu
- src/price_action/strategies/turtle_soup_20d.py
- TurtleSoup20DStrategy(BaseStrategy)
- Vectorized: high.rolling(20).max(), close < that, candle bearish

## Mevcut havuzla orthogonality beklentisi
- donchian_breakout ile ANTI-CORRELATION beklentisi → ensemble net pozitif
- equal_highs_sweep ile partial overlap (her ikisi de "sweep + fail" mantığı) ama Turtle Soup spesifik 20D (yapısal lookback), equal_highs zone-based → farklı trigger
- naked_poc_mr ile bağımsız (POC vs Donchian level)
