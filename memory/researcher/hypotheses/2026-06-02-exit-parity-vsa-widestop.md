# Hypothesis: HYP-2026-06-02-exit-parity-vsa-widestop

- **Type:** Exit-parity / artifact-collapse (NOT a new edge). Backtest-only; no live touch.
- **Date:** 2026-06-02
- **Reproducibility anchor:** git=`0b5527e`, config=`risk_phoenix_scalp_15m_widestop_vsa2.yaml`, data=`data/market.duckdb` (15m, 19 syms, full history). Driver: `scripts/_champ_exit_parity_timestop.py` (REUSES `wlr.gather()` real engine + `production_replay()`; same as §11 `_champ_55bps_exit_compare.py`, do NOT rebuild).

## Claim
"Adding a runner force-exit / time-stop to the LIVE daemon exit structure (4% pct-trail + BE-lock + trail-from-TP1) collapses the +56.8%/mo runner-skew ARTIFACT (top-5% trades = 60.7% of winning R) toward the honest +7-8%/mo BASELINE band, while preserving the live BE-lock benefit. There exists a time-stop in {20,30,40} bars for which the LIVE-exit-with-time-stop is statistically indistinguishable from / >= BASELINE on honest 55bps metrics, with top-5% winning-R share < ~45%."

## Exit variant under test (the ONLY change vs LIVE_DAEMON)
LIVE_DAEMON engine knobs (§11): `runner_trail_pct=0.04, runner_trail_mult=1.5, trail_activate_stage=1, tp1_R=1.0, tp2_R=1.5, tp1_close_pct=0.25, tp2_close_pct=0.25, force_exit_from_entry=False`.
Variant = change `runner_force_exit_method` from `"atr_only"` -> `"time"` and `runner_force_exit_bars` from `None` -> {20, 30, 40}. EVERYTHING else identical (pct-trail, BE-lock, partials). The time-stop counts bars from when the runner trail engages (TP1/+1R) — i.e. a cap on how long the runner may ride.

## Comparators
- (a) LIVE_DAEMON as-is (no time-stop) — the +56.83%/mo artifact.
- (b) BASELINE (trail ATR 1.5, time-stop 30 NOT from entry, TP1/TP2 30%/30%, runner 40%) — the validated honest edge, +7.58%/mo @55bps.

## H0 (null — Popper)
"The runner time-stop does NOT change the LIVE_DAEMON profile: the +56%/mo and top-5%~60% share persist regardless of `runner_force_exit_bars` in {20,30,40}." If H0 holds, the time-stop is irrelevant and the live pct-trail is structurally untradeable at scale.
**Falsifier of the CLAIM:** if even at the tightest time-stop (20 bars) the mean monthly stays > ~+20%/mo OR top-5% share stays > ~50%, the artifact does NOT collapse -> CLAIM rejected, flag the live pct-trail as untrustworthy.

## Pre-registered dependent variables (primary fee = 55bps round-trip)
%positive months, mean & median monthly ROI, mean_R, win%, calendar-day Sharpe (ann √365, honest), continuous-curve MaxDD, **runner-skew diagnostic = top-5% trades' share of total winning R** (want DOWN, target < ~45%), walk-forward positive-month count.

## Pre-registered GATE (CLAIM accepted as "propose live change" only if ALL hold for >=1 time-stop value)
1. Mean monthly ROI lands in **+7-8%/mo band** (accept +6 to +12%/mo as "collapsed to honest"; reject if > +20%/mo = still fantasy).
2. **Top-5% winning-R share < ~45%** (BASELINE is 45.4%; want <= that).
3. MaxDD <= ~ -18% (BASELINE −17.6%).
4. Resulting profile **>= BASELINE** on mean monthly AND Sharpe (or within noise, i.e. not materially worse).
5. Replay total return is NOT physically absurd (BASELINE 5y ~+19,109%; reject if >> that, e.g. 10^6%+).

## Tetlock calibration / priors
- P(some time-stop collapses mean monthly into +6-12% band) = **75%** (the artifact is mechanically a few uncapped runners; capping them must bite).
- P(top-5% share drops below 45% at >=1 time-stop) = **65%**.
- P(LIVE+time-stop strictly beats BASELINE on BOTH mean & Sharpe) = **35%** (BE-lock helps DD, but the pct-trail gives back more than ATR-1.5 on average → expect parity, not dominance).
- P(best time-stop = 20 bars, i.e. tightest wins) = **45%** (tighter caps the artifact harder but also clips legit winners; 30 is the BASELINE-validated value).
- Predictive interval for best variant mean monthly @55bps: **[+5%, +11%]/mo**.

## Stop criteria
- If GATE-1 (collapse to band) fails at ALL three time-stops → reject CLAIM, honest-flag the live pct-trail as untradeable-at-scale, do NOT propose live change.
- Determinism caveat carries from §5 #8 (trade-count off-by-one; R-values stable) — does not block verdict.

## Decision rule
- CLAIM accepted + propose live daemon max-hold/time-stop → only if GATE 1-5 satisfied for >=1 time-stop AND that variant >= BASELINE.
- Otherwise → reject; recommend reverting/hardening toward BASELINE knobs instead of the pct-trail.
