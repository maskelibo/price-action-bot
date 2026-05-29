# Hypothesis: Wyckoff Spring / Upthrust Trap (EUR/USD 4H) — family A3

**ID:** 2026-05-29-forex-brooks-trap-family-A3-wyckoff-spring-upthrust
**Status:** TESTED — VERDICT **KILL** (worst of batch). Clean run 2026-05-29, scripts/forex_4h_trap_dynexit_screen.py, git=e7d0a90, data=37c8a431d26f7566, seed=12345.
**Created:** 2026-05-29 · Researcher: Head of Quantitative Research

## RESULT (2026-05-29)
IS net mR **−0.222** (n=33, WR 39%, PF 0.62), OOS **−0.524** (n=22, WR 18%, PF 0.33) — the worst
result of the entire batch. shuffle p=0.991 (strongly fails — observed is worse than most random
nulls). On EUR/USD 4H the "spring/upthrust" (intrabar penetration of a 20-bar range extreme +
same-bar reclaim) does the OPPOSITE of the thesis: a single-bar penetration-and-reclaim is far
more often the START of a genuine breakout (continuation through the range extreme on the next
bars) than a trap that traverses back to the opposite extreme. The range-extreme target was
rarely hit; price ran the other way. Exit-thesis: range-return this_mR=−0.343 ≤ 2R-twin −0.245
→ both deeply negative, exit irrelevant. Corr vs brooks +0.124 (low overlap 54%) — orthogonal,
but a strongly-losing edge has zero portfolio value. **KILL, no resurrection.** Lesson: the
"sweep & reclaim → reversal" intuition (ICT/Wyckoff) is NOT a net edge here without an
independent context filter (e.g. only at a higher-TF level); a raw 20-bar-range version is
anti-edge. Prior P(GO)=30% badly miscalibrated.
**Reproducibility target:** identical honest-cost model to scripts/forex_4h_research.py · EUR/USD 4H · seed=12345

---

## 0. Why this family
Wyckoff spring (false break BELOW a trading-range low, then reclaim → long) and upthrust
(false break ABOVE range high, then reclaim → short). Economically IDENTICAL to brooks trap
(stop-run / liquidity grab below support → snap back), but the trigger is a RANGE-bound
context + intrabar penetration + same-bar/next-bar RECLAIM, rather than a momentum-close
breakout-then-fail. This is the "sweep & reclaim" / ICT liquidity-grab cousin. Structure
stop = beyond the spring/upthrust extreme; target = opposite side of the range.

This is the most range-conditioned of the three trap variants → likely lowest correlation
with brooks_failed_breakout (which also fires in trends). Portfolio value = orthogonality.

## 1. Hypothesis (falsifiable)
> **H1:** On EUR/USD 4H, define a trading range over the prior N=20 bars [range_lo, range_hi]
> (using bars t-20..t-1). A SPRING = bar t with low[t] < range_lo (penetration) BUT
> close[t] > range_lo (reclaim, close back inside). Entering LONG at t+1 OPEN, SL = low[t] −
> 0.25×ATR, TP = range_hi (opposite extreme; cap ≤ 3R, reward/risk ≥ 1.0), yields **net mean
> R ≥ +0.10** IS, **OOS > 0**, shuffle **p < 0.05**, n_IS ≥ 30. Mirror UPTHRUST (high>range_hi
> & close<range_hi) → short. Require the range be reasonably tight: (range_hi-range_lo) ≤
> 4×ATR (a real range, not a trend) — fixed, no sweep.

Economic rationale: stops cluster just beyond range extremes; a penetration that fails to
hold sweeps that liquidity and traps breakout traders → snap back across the range. Wyckoff
spring/upthrust; ICT liquidity grab; Brooks failed-breakout in a range context.

### Null hypothesis (Popper — written FIRST)
> **H0:** A failed range-extreme penetration with reclaim has no edge net of cost; reclaim
> does not predict traverse to the opposite extreme. If H0 holds: IS mR ≤ 0 OR OOS ≤ 0 OR
> p ≥ 0.05.
> Corroboration: must beat shuffle; must not need a tuned range length or tightness ratio
> (fixed N=20, tightness ≤ 4×ATR).

### Retract clause
- Net negative after cost → retract.
- Needs tuned N / tightness / penetration depth → retract.
- < 2/3 regimes positive → retract.
- If correlation with brooks ≥ +0.6 (not orthogonal) AND mR < brooks → low portfolio value,
  ITERATE-only (don't promote a redundant sleeve).

## 2. Mechanics (lookahead-free)
- range_hi = max(high[t-20..t-1]); range_lo = min(low[t-20..t-1]). tightness = range_hi-range_lo.
- Gate: tightness ≤ 4×ATR[t] (real range).
- Spring: low[t] < range_lo AND close[t] > range_lo AND close[t] > open[t].
  Entry t+1 OPEN LONG. SL = low[t]-0.25×ATR. TP = range_hi.
- Upthrust: high[t] > range_hi AND close[t] < range_hi AND close[t] < open[t].
  Entry t+1 OPEN SHORT. SL = high[t]+0.25×ATR. TP = range_lo.
- risk/reward ≥ 1.0 else skip; cap TP ≤ 3R.
- Same session/weekend/cooldown/cost/SL-first as A1/A2.

## 3. Success / stop criteria
- GO: IS net mR ≥ +0.10, OOS > 0, shuffle p < 0.05, BH-FDR pass, n_IS ≥ 30.
- ITERATE / KILL standard. Plus: report corr vs brooks (orthogonality gate above).

## 4. Calibration (Tetlock)
Prior P(GO) ≈ 30%. Predictive interval IS net mR ∈ [-0.05, +0.32], centred ~+0.10.
Brier-tracked.
