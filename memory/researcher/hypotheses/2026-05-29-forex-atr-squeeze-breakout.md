# Hypothesis: ATR-Contraction Squeeze Breakout (EUR/USD 4H)

**ID:** 2026-05-29-forex-atr-squeeze-breakout (family F5)
**Status:** TESTED — VERDICT **KILL-UNDERPOWERED** (design flaw). Clean run 2026-05-29, scripts/forex_4h_newfamilies_screen.py, git=e7d0a90, data=37c8a431d26f7566.

## RESULT (2026-05-29)
Only **12 trades total** (n_IS=4, n_OOS=8) → statistically void; reported as KILL. IS net mR −0.059, OOS −0.369. Root cause is a **design contradiction**, confirmed by diagnostic: a Donchian-20 breakout IS a volatility expansion, so requiring the breakout bar to still be in a contraction regime (ATR14 ≤ 0.7×median50) is near-self-excluding — only 21 of 9568 bars satisfy both (squeeze bars = 2.9%; squeeze∩breakout = 21). The squeeze should gate the SETUP (pre-breakout coil) and the breakout should be allowed to expand vol, i.e. check squeeze at t-1..t-3 and breakout at t. That is a corrected NEW hypothesis (fresh pre-reg required); do NOT silently patch this one. H0 not testable at this n.

**Created:** 2026-05-29
**Researcher:** Head of Quantitative Research
**Reproducibility target:** identical honest-cost model to scripts/forex_4h_research.py · EUR/USD 4H · seed=12345

---

## 0. Why a NEW edge family
Volatility-regime breakout (NR-style contraction → expansion). Distinct mechanism from all above: conditioned on a *volatility* state, not a session or a structural trap. Reuses donchian_breakout.py / nr7_breakout concept, FX-recalibrated, NO volume (FX spot volume==0).

## 1. Hypothesis (falsifiable)
> **H1:** On EUR/USD 4H, when realized volatility contracts (current ATR14 ≤ 0.7× its own 50-bar median = squeeze regime), the first close beyond the prior 20-bar Donchian channel (high→long / low→short) marks a volatility-expansion breakout. Entering next bar OPEN with stop at the opposite 20-bar Donchian extreme and 2R target yields **net mean R ≥ +0.10** IS, **OOS > 0**, shuffle **p < 0.05**.

Economic rationale: volatility clusters and mean-reverts; a low-vol coil precedes an expansion (Kaufman ch.7 squeeze; Chan ch.6 volatility breakout). Conditioning the breakout on a contraction regime filters the many false breaks that occur in already-elevated vol. FX policy-event coils (pre-NFP/CPI/ECB) fit this.

### Null hypothesis (Popper — written FIRST)
> **H0:** Donchian breakouts after a vol-squeeze have no edge net of cost; squeeze does not predict directional expansion. If H0 holds: IS mR ≤ 0 OR OOS ≤ 0 OR p ≥ 0.05.

### Retract clause
- Net negative after cost → retract.
- Edge needs hand-tuned squeeze ratio / channel length (test ONLY 0.7×median, 20-bar Donchian; no sweep) → retract.
- <2/3 regimes positive → retract.

## 2. Mechanics (lookahead-free)
- ATR14 at bar t; vol_median = rolling 50-bar median of ATR14 (bars ≤ t). Squeeze = ATR14[t] ≤ 0.7×vol_median.
- Donchian20 high/low using bars [t-20 .. t-1] (shift(1), no current bar).
- Breakout: close[t] > donchian20_high (long) / close[t] < donchian20_low (short), AND squeeze active at t.
- Entry: bar t+1 OPEN. SL: opposite Donchian20 extreme. TP: 2R.
- Session filter on entry bar OPEN, weekend no-entry, cooldown 6 bars.

## 3. Success / stop criteria
- GO: IS net mR ≥ +0.10, OOS > 0, p < 0.05, n_IS ≥ 30.
- ITERATE / KILL standard.

## 4. Calibration
Prior P(GO) ≈ 25%. Predictive interval IS net mR ∈ [-0.05, +0.22], centred ~+0.06. Breakout-with-wide-Donchian-stop can have <40% WR but high R; n may be thin after squeeze filter → watch power.
