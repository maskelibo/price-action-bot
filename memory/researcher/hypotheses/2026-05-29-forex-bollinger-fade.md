# Hypothesis: Bollinger 2σ Band Fade Mean-Reversion (EUR/USD 4H)

**ID:** 2026-05-29-forex-bollinger-fade (family F4)
**Status:** TESTED — VERDICT **KILL**. Clean run 2026-05-29, scripts/forex_4h_newfamilies_screen.py, git=e7d0a90, data=37c8a431d26f7566.

## RESULT (2026-05-29)
IS net mR **−0.154** (n=217, WR 27.6% — worst of the five), OOS −0.104 (n=104). KILL, decisively. H0 NOT rejected (shuffle p=0.942). The "fresh pierce not band-walk" filter did NOT save it: 2σ pierces on EUR/USD 4H continued more than they reverted, and the 1R-to-midline target is too thin to overcome cost (27% WR needs >2.7 PF on winners; got 0.79). Corr vs brooks +0.173. Pure stat band-fade is dead on this instrument/TF.

**Created:** 2026-05-29
**Researcher:** Head of Quantitative Research
**Reproducibility target:** identical honest-cost model to scripts/forex_4h_research.py · EUR/USD 4H · seed=12345

---

## 0. Why a NEW edge family
Pure statistical mean-reversion (Bollinger band fade), NOT structural. Distinct from brooks failed-breakout and from the F2 session fade (F4 has no session-boundary condition, fires anytime in window). Reuses bollinger_fade_mr.py concept, FX-recalibrated.

## 1. Hypothesis (falsifiable)
> **H1:** On EUR/USD 4H, when a bar closes beyond the 2σ Bollinger band (20-period, 2.0σ) AND the prior bar was inside the band (fresh pierce, not a band-walk), fading back toward the 20-SMA midline — short on upper-band pierce / long on lower-band pierce, entered next bar OPEN, stop beyond the pierce extreme + 0.5×ATR, target = midline (≈1R) — yields **net mean R ≥ +0.10** IS, **OOS > 0**, shuffle **p < 0.05**.

Economic rationale: EUR/USD has lower trend autocorrelation than crypto; 2σ excursions on a non-trending major over-shoot and revert (Bollinger 2001; Chan ch. on band reversion). The "fresh pierce, not band-walk" condition is the key filter that avoids fading a strong trend.

### Null hypothesis (Popper — written FIRST)
> **H0:** 2σ pierces have no reversion edge net of cost; the pierce continues as often as it reverts. If H0 holds: IS mR ≤ 0 OR OOS ≤ 0 OR p ≥ 0.05.

### Retract clause
- Net negative after cost → retract.
- Edge only with hand-tuned σ or period (test ONLY 20/2.0; no sweep) → retract.
- <2/3 regimes positive → retract. (Expect this to die in trend regimes — needs range to survive.)

## 2. Mechanics (lookahead-free)
- BB(20, 2.0) on close, computed using only bars ≤ t.
- Upper pierce: close[t] > upper AND close[t-1] ≤ upper[t-1] (fresh). → SHORT.
- Lower pierce: close[t] < lower AND close[t-1] ≥ lower[t-1] (fresh). → LONG.
- Entry: bar t+1 OPEN. SL: (high[t] for short / low[t] for long) ± 0.5×ATR. TP: midline (SMA20) → R = (entry-mid)/(SL-entry).
- Session filter on entry bar OPEN, weekend no-entry, cooldown 6 bars.

## 3. Success / stop criteria
- GO: IS net mR ≥ +0.10, OOS > 0, p < 0.05, n_IS ≥ 30.
- ITERATE / KILL standard.

## 4. Calibration
Prior P(GO) ≈ 20%. Predictive interval IS net mR ∈ [-0.10, +0.20], centred ~+0.04. Band fades are seductive but cost-fragile (target=1R, thin); likely ITERATE.
