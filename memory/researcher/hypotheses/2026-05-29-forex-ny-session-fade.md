# Hypothesis: NY-Session Over-Extension Fade (EUR/USD 4H)

**ID:** 2026-05-29-forex-ny-session-fade (family F2)
**Status:** TESTED — VERDICT **KILL**. Clean run 2026-05-29, scripts/forex_4h_newfamilies_screen.py, git=e7d0a90, data=37c8a431d26f7566.

## RESULT (2026-05-29)
IS net mR **−0.069** (n=301), OOS **−0.091** (n=144). Negative both halves → KILL. H0 NOT rejected (shuffle p=0.887, BH fail). Slippage-stress worsens to −0.152 (cost-fragile, target=mid is thin). Corr vs brooks +0.097. H0 (no reversion edge at 16:00) stands: over-extension into the NY bar continued as often as it reverted, net of cost. Mechanism dead on EUR/USD 4H.

**Created:** 2026-05-29
**Researcher:** Head of Quantitative Research
**Reproducibility target:** identical honest-cost model to scripts/forex_4h_research.py · data forex_market.duckdb EUR/USD 4H · seed=12345

---

## 0. Why a NEW edge family
Mean-reversion at a *specific session boundary* — distinct from brooks failed-breakout (structural trap) and from F1 (momentum). Fires at the 16:00 UTC bar only → distinct arrival timing → expected low correlation.

## 1. Hypothesis (falsifiable)
> **H1:** On EUR/USD 4H, when the European session (08:00 + 12:00 UTC bars) produces an over-extended directional move (cumulative |return| over those two bars ≥ 1.0×ATR), the 16:00 UTC bar (late-NY, liquidity fading) tends to **revert**. Fading that extension — short after a stretched up-move / long after a stretched down-move, entered at the 16:00 bar OPEN, stop beyond the session extreme, target = midpoint of the extension (≈1R+) — yields **net mean R ≥ +0.10** IS, **OOS > 0**, shuffle **p < 0.05**.

Economic rationale: intraday FX mean-reversion concentrates at session handoffs as London liquidity withdraws and positions are unwound into the NY afternoon (Ranaldo 2009 intraday FX seasonality; classic "London fix" reversion). Over-extension before a low-liquidity window reverts more often than it continues.

### Null hypothesis (Popper — written FIRST)
> **H0:** No reversion edge at the 16:00 bar; over-extension has no predictive sign for the next bar net of cost. If H0 holds: IS mR ≤ 0 OR OOS ≤ 0 OR p ≥ 0.05.

### Retract clause
- Net flips negative after cost → retract.
- Edge depends on a hand-picked extension threshold → retract (test ONLY the pre-registered 1.0×ATR; no sweep).
- <2/3 regimes positive → retract.

## 2. Mechanics (lookahead-free)
- Compute ATR14 at the 12:00 bar close.
- Extension = (close[12:00] - open[08:00]) measured over the two completed European bars.
- If extension ≥ +1.0×ATR → fade SHORT at 16:00 OPEN; if ≤ -1.0×ATR → fade LONG.
- SL: beyond the session extreme (high of the two bars for shorts, low for longs) + 0.25×ATR buffer.
- TP: entry ± distance to midpoint of the two-bar range (reversion target), capped so R is computable; primary 1.0R structural, else mid.
- Entry bar opens 16:00 UTC (in session). Weekend no-entry, cooldown 6 bars.

## 3. Success / stop criteria
- GO: IS net mR ≥ +0.10, OOS > 0, p < 0.05, n_IS ≥ 30.
- ITERATE / KILL as F1.

## 4. Calibration
Prior P(GO) ≈ 20%. Predictive interval IS net mR ∈ [-0.08, +0.18], centred ~+0.03. Fade edges are fragile to trend days; likely ITERATE or KILL.
