# Hypothesis: ATR-Squeeze Breakout — CORRECTED GATING + DYNAMIC EXIT (EUR/USD 4H) — family B2

**ID:** 2026-05-29-forex-atr-squeeze-breakout-fixed-gating-dynamic-exit-B2
**Status:** TESTED — VERDICT **ITERATE-UNDERPOWERED → effectively KILL**. Clean run 2026-05-29, scripts/forex_4h_trap_dynexit_screen.py, git=e7d0a90, data=37c8a431d26f7566, seed=12345.

## RESULT (2026-05-29)
The corrected gate (coil at t-1..t-3, breakout bar expands) raised the trade count from F5's 12
to only **12 again** (n_IS=5, n_OOS=7) — STILL underpowered. The 3-consecutive-bar coil
(each ATR14 ≤ 0.7×median50) is very rare on EUR/USD 4H: low-vol regimes that also then produce a
clean Donchian-20 close-break are scarce. IS net mR +0.116 (WR 60%, PF 7.34) looks tempting but
n_IS=5 is statistically void; OOS −0.165 (n=7). shuffle p=0.609. Per pre-reg: n_IS<30 →
ITERATE-underpowered, NOT a forced GO; I will NOT promote on 5 trades (that is exactly the
"best params at extreme/thin sample" curve-fit red flag). Exit-thesis: runner −0.048 ≈ 2R-twin
−0.053 (marginally beats, both negative/tiny n). **Effectively KILL: the family is simply too
rare on this instrument to ever power a sleeve at 4H.** A lower TF (1H/15m) or a looser coil
definition would be a fresh hypothesis, but the F5→B2 lineage has now spent its two attempts;
moratorium on this family per the "don't keep re-trying a structurally rare setup" discipline.
Prior P(GO)=22% — the miss was on POWER not direction; calibration note logged.
**Supersedes:** nothing. Original F5 (2026-05-29-forex-atr-squeeze-breakout) stays
  KILL-UNDERPOWERED. B2 fixes the documented DESIGN FLAW (self-excluding gate) AND swaps the
  exit. This is a NEW hypothesis (fresh pre-reg), per the F5 post-mortem instruction.
**Created:** 2026-05-29 · Researcher: Head of Quantitative Research
**Reproducibility target:** identical honest-cost model to scripts/forex_4h_research.py · EUR/USD 4H · seed=12345

---

## 0. Why a NEW (not patched) hypothesis
F5 had only 12 trades because it required the BREAKOUT bar to still be in a squeeze regime —
self-contradictory (a breakout IS vol expansion). The F5 post-mortem prescribed: gate the
SETUP (coil at t-1..t-3) and let the breakout bar EXPAND. B2 implements exactly that, plus a
dynamic exit (squeeze breakouts trend or fail fast — a fixed 2R both truncates winners and
mis-sizes against a far Donchian stop).

## 1. Hypothesis (falsifiable)
> **H1:** On EUR/USD 4H, define a SQUEEZE COIL = each of bars t-1, t-2, t-3 had ATR14 ≤
> 0.7×its 50-bar median (pre-breakout contraction). The BREAKOUT bar t is NOT required to be
> in squeeze (it should expand): close[t] > Donchian20_high (long) / < Donchian20_low (short),
> using bars t-20..t-1. Entry t+1 OPEN. Exit = **trailing/structure**: initial SL = opposite
> Donchian20 extreme; on reaching +1R move to breakeven; then trail under prior-bar swing
> ±0.5×ATR (runner, no fixed TP). This yields **net mean R ≥ +0.10** IS, **OOS > 0**, shuffle
> **p < 0.05**, n_IS ≥ 30.

Economic rationale: a multi-bar coil stores energy; the first decisive close beyond the
channel releases it (NR-style expansion, Kaufman ch.7). A runner harvests the expansion leg;
BE-stop caps the false-break cost. Corrected gate should yield a usable n (coils are common).

### Null hypothesis (Popper — written FIRST)
> **H0:** Post-coil Donchian breakouts have no directional edge net of cost; the coil does not
> predict expansion direction. If H0 holds: IS mR ≤ 0 OR OOS ≤ 0 OR p ≥ 0.05.
> Corroboration: must beat shuffle; the corrected gate must yield n_IS ≥ 30 (else the family
> is simply too rare on this instrument — report as ITERATE-underpowered, not forced GO).

### Retract clause
- Net negative after cost → retract.
- Needs tuned squeeze ratio / coil length / channel length (fix 0.7×median, 3-bar coil,
  Donchian20; no sweep) → retract.
- < 2/3 regimes positive → retract.
- n_IS < 30 → ITERATE-underpowered.
- If runner ≤ 2R-twin AND both negative → exit not the issue, retract.

## 2. Mechanics (lookahead-free)
- ATR14[t], vol_median = 50-bar rolling median of ATR14 (bars ≤ t).
- Coil gate: ATR14[t-1] ≤ 0.7×med[t-1] AND ATR14[t-2] ≤ 0.7×med[t-2] AND ATR14[t-3] ≤ 0.7×med[t-3].
- Donchian20 hi/lo from bars t-20..t-1 (shift(1)). Breakout: close[t] beyond channel.
- Entry t+1 OPEN. Exit state machine identical structure to B1 (initial SL = opposite Donchian
  extreme; BE@+1R; trail prior-bar swing ±0.5×ATR; intrabar SL-first; weekend force-close).
- Same session/weekend/cooldown/cost as the screen.

## 3. Success / stop criteria
- GO: IS net mR ≥ +0.10, OOS > 0, shuffle p < 0.05, BH-FDR pass, n_IS ≥ 30.
- ITERATE (incl. underpowered) / KILL standard.

## 4. Calibration (Tetlock)
Prior P(GO) ≈ 22%. Predictive interval IS net mR ∈ [-0.10, +0.30], centred ~+0.06. Main risk:
even corrected, post-coil breakouts on EUR/USD 4H may be 50/50 net of a wide Donchian stop.
Brier-tracked.
