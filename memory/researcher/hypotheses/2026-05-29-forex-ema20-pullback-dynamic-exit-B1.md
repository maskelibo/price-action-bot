# Hypothesis: EMA20 Pullback Continuation — DYNAMIC EXIT (EUR/USD 4H) — family B1

**ID:** 2026-05-29-forex-ema20-pullback-dynamic-exit-B1
**Status:** TESTED — VERDICT **KILL**. Clean run 2026-05-29, scripts/forex_4h_trap_dynexit_screen.py, git=e7d0a90, data=37c8a431d26f7566, seed=12345.

## RESULT (2026-05-29)
IS net mR **−0.070** (n=145, WR 44%, PF 0.85), OOS **−0.036** (n=67, PF 0.93), shuffle p=0.763.
The dynamic exit (BE@+1R → trail prior-bar swing ±0.5ATR runner) BEAT the fixed-2R twin on the
SAME entries (this_mR=−0.059 vs 2R-twin=−0.078 full period) — so the exit thesis was DIRECTIONALLY
correct (the runner is less bad than 2R), BUT it only moved the needle from −0.078 to −0.059:
**the entry has no continuation edge to harvest.** A better exit cannot rescue a coin-flip entry.
This corroborates and STRENGTHENS the original F3 KILL: it was never the exit, it was the entry.
Corr vs brooks −0.275 (most orthogonal, as F3 predicted — opposite economic sign) but a losing
edge cannot diversify. Regime: all three regimes negative (pos_regimes=0). **KILL — and the
"exit was the problem" hypothesis is itself FALSIFIED.** Per retract clause: do NOT try more
exit variants this tour (would be exit p-hacking). EMA20-pullback continuation is dead on EUR/USD
4H under honest cost, full stop. Prior P(GO)=20% — correctly low; small Brier reward.
**Created:** 2026-05-29 · Researcher: Head of Quantitative Research
**Supersedes:** nothing. The original F3 (2026-05-29-forex-ema20-pullback) stays KILL.
  This is a NEW hypothesis with a DIFFERENT exit mechanism, not a param-tweak resurrection.
**Reproducibility target:** identical honest-cost model to scripts/forex_4h_research.py · EUR/USD 4H · seed=12345

---

## 0. Why a NEW (not patched) hypothesis
F3 KILLed under FIXED 2R (IS −0.113). The F3 post-mortem explicitly flagged: "trend-
continuation needs a runner/trailing exit, not a fixed 2R — but that is a NEW hypothesis."
B1 tests that EXACT claim. The ENTRY logic is byte-identical to F3 (no entry re-tuning =
no p-hacking on the entry); ONLY the exit changes. This isolates the exit variable.

## 1. Hypothesis (falsifiable)
> **H1:** With the IDENTICAL F3 entry (trend EMA50/200 + EMA20 touch + resumption close), but
> replacing the fixed-2R exit with a **structure trailing stop** — initial SL at pullback
> swing ±0.5×ATR; once price reaches +1R, move SL to breakeven; thereafter trail under each
> new completed-bar swing low (long) / above swing high (short) by 0.5×ATR (a "runner") —
> yields **net mean R ≥ +0.10** IS, **OOS > 0**, shuffle **p < 0.05**, n_IS ≥ 30.

Economic rationale: trend continuation pays in the tail (a few large runners), which a 2R cap
truncates; a BE-protected trailing runner keeps the right tail while capping losers near 1R.

### Null hypothesis (Popper — written FIRST)
> **H0:** The dynamic exit does not rescue F3; the entry has no continuation edge regardless
> of exit. If H0 holds: IS mR ≤ 0 OR OOS ≤ 0 OR p ≥ 0.05.
> Corroboration: B1 must BEAT the dead F3 2R-twin (I will report both on the SAME entries; if
> trailing ≤ 2R, the "exit was the problem" claim is FALSIFIED and B1 dies with F3).

### Retract clause
- Net negative after cost → retract.
- Requires tuning the trail multiplier / BE trigger (test ONLY BE@+1R, trail 0.5×ATR under
  swing; no sweep) → retract.
- < 2/3 regimes positive → retract.
- If trailing ≤ 2R-twin → exit thesis falsified, retract (do not try more exit variants this
  tour — that becomes exit p-hacking).

## 2. Mechanics (lookahead-free)
- Entry: EXACTLY F3 (sig_f3_ema20_pullback) — unchanged.
- Exit state machine, evaluated per completed bar after entry (all info ≤ that bar's close;
  fills next-bar conservative / intrabar SL-first):
  1. Initial SL = pullback-window swing ±0.5×ATR (same as F3 SL).
  2. When intrabar high (long) reaches entry + 1×initial_risk → set SL = entry (breakeven),
     checked from the NEXT bar onward (no same-bar look-ahead on the trigger bar's own low).
  3. Each subsequent completed bar: candidate trail = most recent confirmed swing low − 0.5×ATR
     (long) / swing high + 0.5×ATR (short); SL = max(SL, candidate) for long (monotone).
  4. Exit when SL hit (intrabar) or weekend force-close. No fixed TP (pure runner).
- Same session/weekend/cooldown/cost/SL-first as the screen.

## 3. Success / stop criteria
- GO: IS net mR ≥ +0.10, OOS > 0, shuffle p < 0.05, BH-FDR pass, n_IS ≥ 30, AND trailing > 2R-twin.
- ITERATE / KILL standard.

## 4. Calibration (Tetlock)
Prior P(GO) ≈ 20% (the entry itself was a coin-flip in F3; exit may not be enough; WR will
DROP with a runner — needs a fat right tail to compensate). Predictive interval IS net mR ∈
[-0.10, +0.30], centred ~+0.05. Brier-tracked.
