# Hypothesis: Engulfing Continuation — 4h Timeframe (Frequency Upgrade)

**ID**: 2026-05-09-engulfing-4h-frequency  
**Status**: UNDER_TEST  
**Author**: researcher-agent  
**Date**: 2026-05-09  
**Parent hypothesis**: 2026-05-08-engulfing-1d-4h-confluence.md

---

## Motivation

Production engulfing on 1d produced **166 trades / 3y / 10 symbols** (~16.6 trades/sym/yr).
DSR (Deflated Sharpe Ratio) was **0.18** — statistically marginal.
More observations fix the DSR problem: DSR rises with n_obs^0.5.

4h has **6× more bars** than 1d (6 × 365 = 2,190 bars/yr vs 365).
Expected signal yield: ~33 trades/sym/yr → **~990 total trades** over 3y × 10 symbols.
990 vs 166 trades means DSR denominator shrinks substantially.

4h is still an institutional timeframe: major desks, algo funds, and prop shops use it.
It is not noise (5m/15m/1h) — trend/momentum context is structurally valid.

---

## Hypothesis

> The same engulfing-after-pullback pattern that produced positive expectancy on 1d
> will retain edge on 4h, with higher statistical significance (DSR > 0.35),
> at the cost of modestly lower per-trade win rate (target: ≥40%) due to higher noise.

---

## Parameter Adaptations (1d → 4h)

| Parameter | 1d value | 4h value | Rationale |
|-----------|---------|----------|-----------|
| EMA-200 lookback | 200 bars | 1200 bars | 200 × (24/4) = 1200 → same ~200 calendar days |
| EMA-50 lookback | 50 bars | 300 bars | Same 50-day trend window |
| EMA-20 lookback (pullback) | 20 bars | 120 bars | Same 20-day mean reversion |
| Kaufman ER period | 14 bars | 84 bars | 14 × 6 = 84 → same 14-day efficiency window |
| Pullback window | 10 bars | 60 bars | 10 × 6 = 60 → 10-day lookback |
| ATR period | 14 bars | 14 bars | Keep as-is (4h ATR is proper range measure) |
| Body ratio min | 0.60 | 0.60 | No change — pattern definition unchanged |

---

## Expected Metrics

| Metric | 1d Baseline | 4h Target | Notes |
|--------|------------|----------|-------|
| Trades (3y, 10 sym) | 166 | ~600–1200 | Conservative: 50–100% signal density ratio |
| Win rate | ~44% | ≥38% | Noise penalty |
| Sharpe (avg per sym) | 0.37 | ≥0.30 | Volume of trades offsets lower per-trade quality |
| Max DD (avg) | ~18% | ≤25% | Tighter SL distances cut DD per trade |
| CAGR (avg) | +68%/yr | ≥+30%/yr | Conservative — fees eat more |
| DSR | 0.18 | ≥0.35 | Primary improvement goal |

---

## Risks

1. **Noise amplification**: 4h bars include more intra-day noise; engulfing bars may be less "meaningful" than daily equivalents.
2. **Fee drag**: taker 0.075% × 2 sides = 0.15%/trade. At 6× more trades, annual fee load rises ~6×. If edge per trade is thin, fees dominate.
3. **Funding rate impact**: futures positions held for 4h-24h pay funding every 8h at variable rates. Net funding drag vs 1d (held 2-7 days) unclear — needs empirical measurement.
4. **Slippage ratio**: 4h swings are tighter than 1d; slippage_bps=5 is a higher percentage of the risk per trade.
5. **Overfitting risk**: EMA periods scaled by 6 feel mechanical — real 4h market structure may not respect 120-EMA as well as 20-EMA on 1d.

---

## Data Requirements

- 4h OHLCV: 10 symbols, 3 years = ~2,190 bars/sym/yr × 3 = ~6,570 bars/sym
- Verified available: `SELECT timeframe, COUNT(*) FROM ohlcv WHERE timeframe='4h'` → 65,700 rows ✓

---

## Success Criteria (PROMOTE)

- DSR ≥ 0.35 (statistically significant with more samples)
- Win rate ≥ 38%
- Sharpe ≥ 0.30 (per-symbol average)
- CAGR ≥ +25%/yr
- MaxDD ≤ 30%

## Failure Criteria (REJECT / supplement-only)

- Win rate < 35% (noise dominates)
- Net CAGR < 0 after fees
- DSR < 0.20 (no improvement over 1d)
- MaxDD > 40%

---

## Actual Backtest Results (2026-05-09)

**Engine fix required:** pandas 3.0 deprecated `"4H"` freq alias; fixed to `"4h"` in backtest engine.

| Metric | 1d Baseline (ref) | 1d Live Run | 4h Strategy |
|--------|------------------|-------------|-------------|
| Trades (3y, 10 sym) | 166 | 166 | 145 |
| Win rate | 44.0% | 44.0% | **33.8%** |
| Avg Sharpe | 0.37 | 0.371 | **-0.109** |
| Avg MaxDD | -18.0% | -4.8% | -5.9% |
| Annualized | +68.0% | +0.0%* | **-0.3%** |
| DSR | 0.18 | 0.9939† | **0.0000** |

*1d live CAGR low due to per-symbol $10K sizing, not compound.
†1d DSR high because Sharpe 0.371 with n_obs=1095 bars.

**Signal count explanation:** Expected ~990 signals, got **145**. Reasons:
1. EMA-1200 warmup requires 1200 bars before first trade (≈200 days), leaving only 5370 active bars
2. Kaufman ER period=84 on 4h is highly restrictive (slow to warm up, filters choppy regimes)
3. S/R proximity filter (require_proximity_to_sr_atr=0.5) culls many signals

**Yearly breakdown (4h):**
- 2023: 24 trades, +$1,032 net, 50% win (only profitable year)
- 2024: 64 trades, -$773 net, 31.2% win
- 2025: 46 trades, -$593 net, 30.4% win
- 2026: 11 trades, -$257 net, 27.3% win (partial year)

**Combined portfolio (1d + 4h, shared $10K):** 311 trades, 39.2% win, +$4,384 net, +12.9%/yr, -19.8% MaxDD. Positive but worse than pure 1d due to 4h drag.

---

## Verdict

**REJECT — noise wins, 4h edge insufficient**

DSR = 0.0000 (negative Sharpe makes it statistically worthless). Win rate dropped from 44% → 33.8% — below the 38% threshold. Only 2023 was profitable; 2024-2026 showed consistent losses as crypto volatility regime changed.

**Critical finding on DSR hypothesis:** The hypothesis that "more samples → higher DSR" failed. 4h produced 145 trades (not even more than 1d's 166 due to filter warmup). Even if signal count were 990, the Sharpe is negative, so DSR = ~0 regardless of sample count. DSR improvement requires **edge per trade** to exist first — sample count only narrows the standard error.

**Fee drag:** At 145 trades × 0.15% round-trip = ~21.75% of capital in fees over 3y. Combined with 33.8% win rate on 2R:1R trades (EV = 0.338×2 − 0.662×1 = -0.014R per trade), fees make the strategy structurally losing.

**Recommendation:** Keep 1d engulfing as primary. Do NOT run 4h engulfing live. Investigate whether a less restrictive pullback/EMA-period scaling (e.g., keep 20/50-EMA periods unchanged at 20/50 on 4h, accepting shorter calendar windows) would recover win rate.
