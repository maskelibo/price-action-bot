# Hypothesis: Brooks Failed-Swing High/Low Trap (EUR/USD 4H) — family A1

**ID:** 2026-05-29-forex-brooks-trap-family-A1-failed-swing
**Status:** TESTED — VERDICT **ITERATE→effectively KILL**. Clean run 2026-05-29, scripts/forex_4h_trap_dynexit_screen.py, git=e7d0a90, data=37c8a431d26f7566, seed=12345.
**Created:** 2026-05-29 · Researcher: Head of Quantitative Research

## RESULT (2026-05-29)
IS net mR **+0.033** (n=107, WR 44.9%, PF 1.06) — POSITIVE but below the +0.10 promote bar →
ITERATE per the bar, but OOS net mR **−0.126** (n=51, WR 33%, PF 0.80) FLIPS NEGATIVE, shuffle
**p=0.572** (H0 NOT rejected), BH-FDR fail. Corr vs brooks **+0.282** (NOT orthogonal — same
trap family fires in overlapping months, 90% month-overlap). Exit-thesis corroboration:
structure-target this_mR=−0.018 ≤ 2R-twin +0.002 → the "range-return exit beats 2R" claim is
**FALSIFIED**; the failed-swing trigger carries no exit-independent edge. Regime split:
trend_up +0.324 / trend_down −0.303 → it is a long-biased artefact of the 2020-23 sample, not a
symmetric trap. **Net verdict: no promotable edge.** Closest structural cousin to brooks but
it did NOT replicate brooks' edge — brooks' N-bar Donchian level + its own confirmed-fail logic
is doing real work that a raw fractal-swing break does not. Prior P(GO)=35% was too high
(Brier penalty logged).
**Reproducibility target:** identical honest-cost model to scripts/forex_4h_research.py · EUR/USD 4H · seed=12345

---

## 0. Why this family
Same economic family as brooks_failed_breakout (GO, +0.43R) — a STRUCTURAL TRAP with a
STRUCTURE-BASED stop — but a DIFFERENT trigger. brooks_failed_breakout uses an N-bar
Donchian level. A1 uses a **fractal swing point** (pivot high/low: a bar whose high is the
max of [t-k..t+k] — but causally we only confirm the pivot k bars LATER). A swing-point
break that fails is the canonical Brooks "failed swing / wedge-top trap". Distinct trigger,
same mechanism: trapped breakout traders + reversal players → two-sided fuel.

Prior tour lesson (learning.md 2026-05-29): structure-based trap edges BEAT statistical
pattern edges on this instrument; fixed-2R is dead. So A1 uses **structure-based exit**:
stop beyond the failed-swing extreme, target = the opposite side of the range that produced
the swing (range-return), NOT fixed 2R. This is the brooks-native exit, not a 2R bolt-on.

## 1. Hypothesis (falsifiable)
> **H1:** On EUR/USD 4H, when price breaks a confirmed fractal swing high (pivot high of
> window k=3, i.e. high[p] = max(high[p-3..p+3]); confirmed only at p+3) but within the next
> 1-3 bars closes back BELOW that swing-high level (failed break = bull trap), entering SHORT
> at the next bar OPEN, with SL = breakout-bar high + 0.25×ATR and TP = the swing LOW that
> anchored the move (range-return target, capped at 3R, floored so risk/reward ≥ 1.0), yields
> **net mean R ≥ +0.10** IS, **OOS > 0**, shuffle **p < 0.05**, n_IS ≥ 30. Mirror for longs
> (failed swing-low = bear trap → long).

Economic rationale: Brooks deep catalog "Failed Breakout / Trap — most reliable reversal";
fractal swing failure is the purest visual form. Range-return exit harvests the two-sided
momentum to the opposite extreme rather than an arbitrary 2R.

### Null hypothesis (Popper — written FIRST)
> **H0:** A failed swing-point break has no reversal edge net of cost; the post-failure path
> is random conditional on trend/vol. If H0 holds: IS mR ≤ 0 OR OOS ≤ 0 OR p ≥ 0.05.
> Corroboration test: if A1 is real, the structure-target version must beat its own fixed-2R
> twin (I will report both; if 2R ≥ structure-target, the "structure exit matters" claim is
> falsified and A1 collapses to the dead F-family pattern).

### Retract clause
- Net negative after cost → retract.
- Needs hand-tuned pivot window k or fail-window (test ONLY k=3, fail-window 1-3, no sweep) → retract.
- < 2/3 regimes positive → retract.
- If structure-target ≤ fixed-2R twin → the family thesis ("structure exit is the edge") is
  falsified; do not resurrect with param tweaks.

## 2. Mechanics (lookahead-free)
- Fractal pivot high at index p: high[p] == max(high[p-3 .. p+3]). CONFIRMED at bar p+3
  (we never act before p+3 → causal). Same for pivot low.
- Track the most recent CONFIRMED pivot high `swing_hi` (level) and its paired prior pivot
  low `range_lo` (the swing low that preceded it, for the range-return target).
- Breakout bar b (b ≥ p+3): high[b] > swing_hi AND close[b] > swing_hi (strong break close).
- Failure: within bars b+1..b+3, some bar f closes < swing_hi → bull trap confirmed at f.
- Decision bar = f. Entry = f+1 OPEN (SHORT). SL = high[b] + 0.25×ATR[f].
  TP = range_lo (range-return); cap |TP-entry| ≤ 3×risk; require reward/risk ≥ 1.0 else skip.
- Mirror for failed swing-low → long.
- Session filter on entry-bar OPEN (07-16 UTC), weekend no-entry, cooldown 6 bars, SL-first
  conservative intrabar, next-bar OPEN fill, slippage 1.0bps split, swap 0.3bps/night Wed3x.

## 3. Success / stop criteria
- GO: IS net mR ≥ +0.10, OOS > 0, shuffle p < 0.05, BH-FDR pass, n_IS ≥ 30.
- ITERATE: IS mR > 0 but bar/power/OOS unmet.
- KILL: IS mR ≤ 0.

## 4. Calibration (Tetlock)
Prior P(GO) ≈ 35% — highest of this batch because it is the closest structural cousin to the
one proven edge. Predictive interval IS net mR ∈ [-0.05, +0.35], centred ~+0.12.
Brier-tracked.
