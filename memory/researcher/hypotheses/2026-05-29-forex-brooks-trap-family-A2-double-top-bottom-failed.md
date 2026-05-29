# Hypothesis: Double-Top/Bottom Failed-Breakout Trap (EUR/USD 4H) — family A2

**ID:** 2026-05-29-forex-brooks-trap-family-A2-double-top-bottom-failed
**Status:** TESTED — VERDICT **KILL**. Clean run 2026-05-29, scripts/forex_4h_trap_dynexit_screen.py, git=e7d0a90, data=37c8a431d26f7566, seed=12345.
**Created:** 2026-05-29 · Researcher: Head of Quantitative Research

## RESULT (2026-05-29)
The pre-reg config produced **0 signals**. Diagnosed (NOT a code bug): 242 valid double-top/
bottom pairs (|hi2-hi1|≤0.5ATR, 3-15 bars apart) and 156 neckline breaks exist, but **142/156
have reward/risk < 1.0** — by the time price closes below the neckline, the structure stop
(top+0.25ATR) sits all the way back above the double top (far), while the measured-move target
(neckline−height) is near. The pre-reg retract clause's RR≥1 floor legitimately rejected them
all. To confirm this is not just a stop-placement artefact, a DIAGNOSTIC run (RR floor removed,
NOT a promotable config, not pre-registered as tradable) gave: measured-move n=65 net_mR
**+0.013** (WR 61.5%, PF 1.05); 2R-twin n=64 net_mR **+0.021** (WR 42.2%) — both flat coin-flips
far below +0.10. So the double-top/bottom PATTERN itself has no edge on EUR/USD 4H net of cost,
independent of the stop geometry. **KILL** (no resurrection: pattern is flat, not just
mis-stopped). shuffle n/a (0 promotable). Prior P(GO)=25% too high.
**Reproducibility target:** identical honest-cost model to scripts/forex_4h_research.py · EUR/USD 4H · seed=12345

---

## 0. Why this family
Brooks trap family, distinct trigger from A1 and from brooks_failed_breakout: a TWO-attempt
failure. Price makes a high, pulls back, retests the SAME high (double top, two highs within
a tolerance band), the second attempt FAILS to break → trapped breakout buyers on attempt-2
+ double-top sellers. Brooks: "second entry" reliability; Bulkowski double-top is one of the
better-documented reversal structures. Structure-based stop (above the higher of the two
tops) and structure target (the intervening pullback trough / neckline → measured move).

## 1. Hypothesis (falsifiable)
> **H1:** On EUR/USD 4H, when two swing highs form within a tolerance band (|hi2 - hi1| ≤
> 0.5×ATR) separated by 3-15 bars with an intervening trough (neckline), and bar t closes
> below the neckline (confirming the double-top breakdown), entering SHORT at t+1 OPEN with
> SL = max(hi1,hi2) + 0.25×ATR and TP = neckline − (max(hi1,hi2) − neckline) (measured-move,
> capped ≤ 3R, reward/risk ≥ 1.0), yields **net mean R ≥ +0.10** IS, **OOS > 0**, shuffle
> **p < 0.05**, n_IS ≥ 30. Mirror double-bottom → long.

Economic rationale: the second failed test traps the breakout cohort; neckline break = regime
flip. Measured-move target is the standard structural objective (Edwards & Magee / Bulkowski).

### Null hypothesis (Popper — written FIRST)
> **H0:** Double-top/bottom neckline breaks carry no edge net of cost on EUR/USD 4H; the
> structure is pareidolia. If H0 holds: IS mR ≤ 0 OR OOS ≤ 0 OR p ≥ 0.05.
> Corroboration test: must beat a random-neckline-break null (shuffle) AND must not depend on
> the equality tolerance — I fix tol=0.5×ATR, no sweep.

### Retract clause
- Net negative after cost → retract.
- Needs tuned equality tolerance / separation window → retract (fixed 0.5×ATR, 3-15 bars).
- < 2/3 regimes positive → retract.
- n_IS < 30 → ITERATE-underpowered, NOT a forced GO.

## 2. Mechanics (lookahead-free)
- Confirmed fractal pivots (window k=3, confirmed at p+3) give swing highs/lows.
- A double top = two consecutive confirmed pivot highs hi1 (older), hi2 (newer), 3-15 bars
  apart, |hi2-hi1| ≤ 0.5×ATR[t]. Neckline = the lowest low between them.
- Trigger bar t (t ≥ confirmation of hi2): close[t] < neckline AND close[t] < open[t].
- Entry t+1 OPEN SHORT. SL = max(hi1,hi2)+0.25×ATR[t]. height = max(hi1,hi2) − neckline.
  TP = neckline − height (measured move). risk = SL − entry; cap TP so |TP-entry| ≤ 3×risk;
  require reward/risk ≥ 1.0 else skip.
- Mirror for double bottom → long.
- Same session/weekend/cooldown/cost/SL-first as A1.

## 3. Success / stop criteria
- GO: IS net mR ≥ +0.10, OOS > 0, shuffle p < 0.05, BH-FDR pass, n_IS ≥ 30.
- ITERATE / KILL standard.

## 4. Calibration (Tetlock)
Prior P(GO) ≈ 25%. Predictive interval IS net mR ∈ [-0.08, +0.30], centred ~+0.08. Risk:
double-tops are rarer → n may be thin (power risk). Brier-tracked.
