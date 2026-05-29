# Hypothesis: London-Open Breakout Continuation (EUR/USD 4H)

**ID:** 2026-05-29-forex-london-open-breakout (family F1)
**Status:** TESTED — VERDICT **KILL** (IS net mR<0). Clean run 2026-05-29, script scripts/forex_4h_newfamilies_screen.py, git=e7d0a90, data_hash=37c8a431d26f7566.

## RESULT (2026-05-29)
IS net mR **−0.098** (n=171, WR 38%, PF 0.82) → KILL per pre-reg stop criterion (IS mR≤0, NO param iterate = no p-hacking). Notable but NOT acted upon: OOS net mR +0.115 (n=78, PF 1.26). H0 NOT rejected — shuffle p=0.66, BH-FDR fail. The IS/OOS sign flip is regime-dependent (2024-25 USD-weak trend favored London continuation), not evidence of a stable edge. **I refuse to resurrect this by peeking at the favorable OOS — that is the exact data-snooping the protocol forbids.** Monthly-R corr vs brooks = −0.065 (nicely orthogonal) but a negative-IS edge has no portfolio value. Slippage-stress mR −0.047. Retract clause triggered (gross also negative IS).

**Created:** 2026-05-29
**Researcher:** Head of Quantitative Research
**Reproducibility target:** git=<branch audit-hardreview-20260528> · data=forex_market.duckdb EUR/USD 4H (9630 bar 2020-2025) · seed=12345 · honest-cost model identical to scripts/forex_4h_research.py (fee 0, slip 1.0bps round-trip, swap 0.3bps/night Wed3x, session bar-OPEN filter, weekend no-entry, cooldown 6 bars)

---

## 0. Why a NEW edge family (portfolio mandate)
Principal wants to scale portfolio to +10%/mo; single brooks_failed_breakout (GO, +0.43R) is not enough. We need **uncorrelated** edges. London-open breakout is a *trend-following / session-momentum* mechanism — economically distinct from brooks failed-breakout (which is a reversal/trap mechanism). Distinct trade arrival timing (only fires on the post-London bar) → expected low overlap with brooks.

## 1. Hypothesis (falsifiable)
> **H1:** On EUR/USD 4H, the London-session bar (opens 08:00 UTC) sets an opening range. When the *next* bar (12:00 UTC, NY/London overlap, highest FX liquidity) breaks the 08:00 bar's high (long) or low (short) in the direction of the 4H trend (EMA50 vs EMA200), entered at the breakout bar's OPEN-confirmed level with a structural stop at the 08:00 bar's opposite extreme and 2R target, produces **net mean R ≥ +0.10** in-sample (2020-2023), **OOS net mR > 0** (2024-2025), beating a label-shuffle null at **p < 0.05**.

Economic rationale: London open is the single largest FX liquidity injection of the day; directional order flow that survives into the NY overlap tends to continue (intraday momentum / Bjornson-Hansen session-flow literature; Breedon & Ranaldo 2013 on intraday FX returns showing positive momentum into the overlap). On a *trend-aligned* day this continuation is strongest.

### Null hypothesis (Popper — written FIRST)
> **H0:** The London-open range break has no continuation edge net of cost; the 12:00 bar's direction relative to the 08:00 range is a coin flip conditional on trend. If H0 holds: IS net mR ≤ 0 OR OOS ≤ 0 OR shuffle p ≥ 0.05.

### Retract clause (adversarial)
- If edge exists gross but spread+swap flips net negative → retract.
- If it only works with a hand-tuned breakout buffer (curve-fit) → retract.
- If positive in <2 of 3 regimes → regime-fragile, retract.

## 2. Mechanics (lookahead-free)
- Trend filter at the 08:00 bar close: EMA50 > EMA200 → longs only; EMA50 < EMA200 → shorts only.
- Range = [high, low] of the 08:00-UTC-open bar (fully closed before decision).
- Entry: 12:00-UTC bar. Long trigger if its OPEN or intrabar high crosses 08:00 high; we enter at max(open, range_high) i.e. breakout level on the 12:00 bar (next-bar execution, no peeking at 12:00 close).
- SL: opposite extreme of the 08:00 range. TP: entry + 2R.
- Session: entry bar opens 12:00 UTC (in 07-16 window). Weekend no-entry. Cooldown 6 bars.

## 3. Success / stop criteria (pre-reg)
- GO candidate: IS net mR ≥ +0.10 AND OOS net mR > 0 AND shuffle p < 0.05 AND n_IS ≥ 30.
- ITERATE: IS mR in (0, 0.10) OR p ≥ 0.05 with positive sign.
- KILL: IS net mR ≤ 0 (no param iterate — no p-hacking).

## 4. Calibration (Tetlock)
Prior P(GO) ≈ 25%. Predictive interval IS net mR ∈ [-0.05, +0.20], centred ~+0.05 (session momentum is real but thin at 4H; most likely ITERATE).
