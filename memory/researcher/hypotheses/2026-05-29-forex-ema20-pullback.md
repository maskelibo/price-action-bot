# Hypothesis: EMA20 Trend Pullback Continuation (EUR/USD 4H)

**ID:** 2026-05-29-forex-ema20-pullback (family F3)
**Status:** TESTED — VERDICT **KILL**. Clean run 2026-05-29, scripts/forex_4h_newfamilies_screen.py, git=e7d0a90, data=37c8a431d26f7566.

## RESULT (2026-05-29)
IS net mR **−0.113** (n=140, WR 39%, PF 0.80), OOS −0.007 (n=67, ~breakeven). KILL. H0 NOT rejected (shuffle p=0.827). Corr vs brooks **−0.234** (most orthogonal of the five — opposite economic sign as predicted) but a losing edge can't diversify. The literature-favored pullback (Brooks H2/L2, Grimes) did NOT survive honest cost at 4H 2R: EMA20 touch + resumption follow-through was a coin flip net of spread/swap. Most-likely-GO prior (30%) was wrong; trend-continuation needs either tighter trend filter or a runner/trailing exit, not a fixed 2R — but that is a NEW hypothesis, not a param-tweak of this one (would require fresh pre-reg).

**Created:** 2026-05-29
**Researcher:** Head of Quantitative Research
**Reproducibility target:** identical honest-cost model to scripts/forex_4h_research.py · EUR/USD 4H · seed=12345

---

## 0. Why a NEW edge family
Classic trend-following pullback (Brooks H2/L2 / Grimes "pullback to value"). Trend-CONTINUATION, opposite economic sign to brooks_failed_breakout (which fades failed breakouts). Reuses the conceptual detector in src/.../three_bar_reversal.py and brooks_h2_l2.py but tested standalone on FX with honest cost.

## 1. Hypothesis (falsifiable)
> **H1:** On EUR/USD 4H in an established trend (EMA50 > EMA200 for longs), after price pulls back to touch the EMA20 (low ≤ EMA20 ≤ prior-bar range) and then prints a bar that closes back above EMA20 (resumption), entering at the next bar OPEN with a stop below the pullback swing low (−0.5×ATR) and 2R target yields **net mean R ≥ +0.10** IS, **OOS > 0**, shuffle **p < 0.05**. Symmetric for shorts.

Economic rationale: trend persistence + the EMA20 as a dynamic value zone where trend-followers re-enter (Grimes 2012 ch. on pullbacks; Brooks always-in continuation). FX majors trend in monetary-policy-divergence regimes (e.g. 2022 USD bull).

### Null hypothesis (Popper — written FIRST)
> **H0:** EMA20 touch + resumption has no continuation edge net of cost; the resumption bar's follow-through is random conditional on trend. If H0 holds: IS mR ≤ 0 OR OOS ≤ 0 OR p ≥ 0.05.

### Retract clause
- Net negative after cost → retract.
- Requires hand-tuned EMA-touch tolerance to work → retract (use fixed 0.25×ATR touch band, no sweep).
- <2/3 regimes positive → retract.

## 2. Mechanics (lookahead-free)
- Trend at bar t close: EMA50 > EMA200 → long-only context (symmetric short).
- Pullback: bar t low within [EMA20 − 0.25ATR, EMA20] (touched value from above) AND prior 1-3 bars net counter-trend.
- Resumption trigger: bar t closes > EMA20 AND close > open (bullish), confirming bounce.
- Entry: bar t+1 OPEN. SL: min(low over pullback window) − 0.5×ATR. TP: 2R.
- Session filter on entry bar OPEN (07-16 UTC), weekend no-entry, cooldown 6 bars.

## 3. Success / stop criteria
- GO: IS net mR ≥ +0.10, OOS > 0, p < 0.05, n_IS ≥ 30.
- ITERATE / KILL as standard.

## 4. Calibration
Prior P(GO) ≈ 30% (pullback is the most literature-supported of the five). Predictive interval IS net mR ∈ [-0.05, +0.25], centred ~+0.08.
