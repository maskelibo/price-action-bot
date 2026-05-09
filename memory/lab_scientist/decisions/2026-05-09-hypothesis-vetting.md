---
agent: lab_scientist
type: hypothesis_vetting
date: 2026-05-09
scope: all hypotheses with date 2026-05-08 or 2026-05-09
total_hypotheses_reviewed: 16
method: pre-backtest statistical scrutiny
status: FINAL
---

# Lab Scientist — Hypothesis Vetting Report
**Date:** 2026-05-09  
**Scope:** 16 hypothesis documents (8 from 2026-05-08, 8 from 2026-05-09)  
**Goal:** Rank + screen before expensive compute is spent

---

## Scoring Rubric (each 1–5, max 25)

| Dimension | 5 | 1 |
|---|---|---|
| **Novelty** | Completely new mechanism vs existing 25+ | Duplicate or minor variant |
| **Mechanical clarity** | Zero discretion, fully rule-based | Requires manual judgment |
| **Decorrelation** | Orthogonal to engulfing (different trigger, regime, direction) | Near-identical to engulfing |
| **Sample expectation** | ≥ 150 trades / 3y / 10 sym (≥ 15/sym) | < 30 total trades |
| **Curve-fit risk** | Deterministic parameters, no optimization | Multi-parameter sweep, in-sample only |

---

## Individual Hypothesis Scorecards

---

### H-001: Pin Bar @ S/R + Trend Filter
**File:** `2026-05-08-baseline-pinbar-sr-trend.md`  
**Status in doc:** Pre-registered (not yet backtested)

| Dimension | Score | Notes |
|---|---|---|
| Novelty | 3 | Pin bar + S/R is classical; S/R cluster rule-based definition is the novel element |
| Mechanical clarity | 4 | Fully rule-based (shadow ≥ 60%, body ≤ 33%, S/R proximity = 0.5 ATR). Edge case: how S/R levels are detected (min_touches=2) could be borderline discretionary |
| Decorrelation | 3 | Different pattern (pin bar vs engulfing) but same EMA trend filter and 1D crypto universe; some overlap expected |
| Sample expectation | 3 | Pin bar at S/R with strict geometry (shadow ≥ 60%) will be rare; 3y × 10 sym likely 40–80 trades — borderline |
| Curve-fit risk | 4 | Parameters are literature-sourced (Brooks, Volman), not optimized; pre-registered gates defined |
| **TOTAL** | **17/25** | |

**Critical issues:** Pin bar geometry filters are strict enough that signal count could drop below 30. HOD filter section: 1D bars all open at 00:00 UTC so HOD is trivially null (already flagged in day-of-week doc — same issue here). **No lookahead identified.** No parameter sweep flagged. DSR gate NOT mentioned — should be added before backtest.

---

### H-005: Donchian 55 + Bollinger Squeeze Breakout
**File:** `2026-05-08-donchian-bollinger-breakout.md`  
**Status in doc:** Pre-registered (not yet backtested)

| Dimension | Score | Notes |
|---|---|---|
| Novelty | 4 | Combining Donchian 55-bar channel with Bollinger Squeeze filter is a meaningful structural extension of vanilla turtle; the squeeze-as-pre-condition is novel in this codebase |
| Mechanical clarity | 5 | Fully algorithmic: rolling N-bar max, BB within KC flag, ER ≥ 0.30 — zero discretion |
| Decorrelation | 4 | Strong decorrelation: breakout entry (vs pullback entry), trailing exit (vs 2R fixed), squeeze pre-filter (vs no compression requirement). Engulfing buys early pullback; this buys late breakout — genuinely different timing |
| Sample expectation | 4 | 55-bar Donchian fires on true breakouts; crypto is volatile enough. 3y × 10 sym should yield 60–120 trades — comfortably above 30 |
| Curve-fit risk | 4 | 55 and 20 bar periods are Turtle-canonical (literature-sourced). Squeeze threshold (BB within KC at 1.5×ATR) is a single fixed parameter. ER ≥ 0.30 is Kaufman's canonical value. Low over-fit risk |
| **TOTAL** | **21/25** | |

**Critical issues:**  
- **Lookahead check:** `donchian55_high = rolling 55-bar high.shift(1)` — correctly uses shift(1). `squeeze_active.rolling(5).max()` — uses past 5 bars on a past-computed indicator. CLEAN.  
- **Multiple testing:** No parameter sweep described — single configuration. No Bonferroni needed.  
- **DSR gate:** NOT stated. Should add DSR ≥ 0.35 gate given crypto single-cycle data.  
- **Recommendation:** PROMOTE — strong candidate.

---

### H-005 (Funding Rate MR): Funding Rate Mean-Reversion v2.0
**File:** `2026-05-08-funding-rate-mean-reversion.md`  
**Status in doc:** DEFER (pending live data re-run; synthetic sweep done)

| Dimension | Score | Notes |
|---|---|---|
| Novelty | 5 | Perpetual funding rate as mean-reversion signal is crypto-native; not present in any prior hypothesis; structural carry mechanism, not pattern-based |
| Mechanical clarity | 5 | Rule-based: adaptive 95th/5th pctile threshold, ER < 0.30 regime filter, reversal bar confirmation — zero discretion |
| Decorrelation | 5 | By construction orthogonal: counter-trend (vs engulfing trend-following), fires in low-ER regimes (vs engulfing high-ER), 8h timeframe (vs 1D). Empirical r = -0.087 confirmed |
| Sample expectation | 4 | v2.0 produced 84 trades in 3y (5 symbols). Meets ≥ 30 threshold; marginal for DSR power but acceptable |
| Curve-fit risk | 3 | v2.0 introduces adaptive threshold (rolling 95th pctile) — this is a good design but the ER < 0.30 cutoff and v2 changes were motivated by v1.0 failure. Risk of post-hoc parameter fitting on same dataset. v1.0 real-data result was -5.7% |
| **TOTAL** | **22/25** | |

**Critical issues:**  
- **CRITICAL — v1.0 vs v2.0 data leakage risk:** v1.0 baseline was run on REAL data (-5.7%). v2.0 improvements (adaptive threshold, ER filter, BNB exclusion) were designed AFTER seeing v1.0 failure, then validated on a "synthetic 3-year sweep" NOT on the same real data. This is classic in-sample parameter fitting disguised as improvement. **The v2.0 result of +25.8% has NOT been validated on live DuckDB real data.** This must be the first step before PROMOTE.  
- **Lookahead check:** `funding_z = z-score over rolling 90-period window` — must confirm shift(1) is applied. Doc mentions shift(1) in feature engineering — CLEAN.  
- **DSR gate:** With n=84 trades and Sharpe ~0.58 (combined), DSR should be computed explicitly.  
- **Flag for fix:** Re-run v2.0 on real DuckDB data before PROMOTE — synthetic sweep result is not sufficient evidence.

---

### AVWAP + POC Reversal
**File:** `2026-05-08-anchored-vwap-poc-reversal.md`  
**Status in doc:** Pre-registered (not yet backtested)

| Dimension | Score | Notes |
|---|---|---|
| Novelty | 4 | AVWAP + POC confluence as mean-reversion trigger is novel in this codebase; Harris microstructure grounding is legitimate |
| Mechanical clarity | 3 | Mostly rule-based, but swing anchor selection ("last 60-bar fractal swing low") can be ambiguous. POC bucket size (50 buckets) is a free parameter. RSI < 50 filter is listed as "optional" |
| Decorrelation | 4 | Mean-reversion vs trend-following: structurally different. BUT same crypto universe and EMA regime filter could generate overlapping trade timing |
| Sample expectation | 3 | AVWAP cross + POC within 1.5 ATR simultaneously is a conjunction of rare events. 3y × 10 sym could yield < 40 trades — borderline |
| Curve-fit risk | 3 | Swing lookback (60 bar), ATR multiplier (1.5), RSI threshold (50), ER cutoff (0.35) — 4 parameters. ER cutoff matches Kaufman canonical; others are free choices. Medium risk |
| **TOTAL** | **17/25** | |

**Critical issues:**  
- **Lookahead risk (POTENTIAL BUG):** "swing anchor seçimi aynı bar içinde yapıldığı için ek dikkat gerekir" — the doc itself flags this. The swing_low anchor must use shift(1) to avoid the anchor being determined by information including bar T. **Verify implementation before backtest.**  
- **RSI "optional" filter:** Any filter that is toggled on only when it helps is a form of overfitting. Must pre-register whether RSI is in or out.  
- **DSR gate:** Not mentioned. Add before backtest.

---

### Engulfing 1D + 4H Confluence (MTF)
**File:** `2026-05-08-engulfing-1d-4h-confluence.md`  
**Status in doc:** IN_TEST (not yet backtested in this session)

| Dimension | Score | Notes |
|---|---|---|
| Novelty | 2 | This is a direct variant of the existing engulfing strategy with a 4h confirmation layer. Not a new mechanism |
| Mechanical clarity | 4 | Brooks always-in flip definition (3 of 4-6 bars in trend direction + new high/low) is rule-based |
| Decorrelation | 1 | Same strategy, same universe, same EMA filter — this is a SUPPLEMENT not a new hypothesis. Decorrelation score = N/A; penalized for using portfolio slot |
| Sample expectation | 2 | 4h filter expected to reject 20–40% of 1D signals; starting from 166 trades → ~100–130 trades. Acceptable but not generous |
| Curve-fit risk | 3 | "4–6 bars" window for always-in and "3 of N bars" are partially free parameters. Moderate risk |
| **TOTAL** | **12/25** | |

**Critical issues:**  
- **Lookahead risk:** "1d bar N kapandığında, son tam 4h bar da kapanmış olmalı" — UTC alignment must be verified in code. 4h bars close at 00:00, 04:00, 08:00, 12:00, 16:00, 20:00 UTC. 1D bar closes at 00:00 UTC. At 1D close, the last complete 4h bar ended at 20:00 UTC (4h bar T-1). This means 4h data used is from bars ending at 20:00 UTC on the 1D bar's day — this is CORRECT and NOT lookahead. But code must be checked.  
- This hypothesis should be DEFERRED — the 4H standalone test (below) already REJECTED pure 4H. MTF confluence adds complexity without a standalone proven mechanism.

---

### Engulfing 4H Frequency Upgrade
**File:** `2026-05-09-engulfing-4h-frequency.md`  
**Status in doc:** REJECT (backtested, failed)

| Dimension | Score | Notes |
|---|---|---|
| Novelty | 2 | Timeframe scaling of existing strategy |
| Mechanical clarity | 4 | Same rules as 1D, EMA periods scaled by 6x |
| Decorrelation | 1 | Same strategy as engulfing 1D |
| Sample expectation | 1 | Produced only 145 trades (less than 1D's 166 due to EMA-1200 warmup) |
| Curve-fit risk | 3 | Parameters are mechanically scaled — no optimization — but the warmup problem reveals parameter mismatch |
| **TOTAL** | **11/25** | |

**Critical issues:**  
- **Already backtested and REJECTED.** DSR = 0.0000. Win rate 33.8% (below 38% threshold). Only 2023 profitable. -0.3% annualized.  
- **Key learning:** DSR improvement via sample size ONLY works if per-trade edge exists. The hypothesis that "more bars → higher DSR" failed because 4H has negative Sharpe. This is a fundamental insight: DSR ∝ Sharpe × sqrt(T), not just sqrt(T).  
- **No further backtest compute needed.** CONFIRMED REJECT.

---

### Fear & Greed Sentiment Filter (H18)
**File:** `2026-05-09-fear-greed-sentiment.md`  
**Status in doc:** TESTING (being actively tested per doc date)

| Dimension | Score | Notes |
|---|---|---|
| Novelty | 4 | F&G as filter on top of engulfing is a new data source (sentiment, not price/volume); first retail psychology proxy in this codebase |
| Mechanical clarity | 5 | F&G threshold (< 60 for longs, > 40 for shorts) is a single number; shift(1) explicitly required |
| Decorrelation | 3 | As a filter ON TOP of engulfing, it is not independent; it modifies the existing strategy rather than adding a new one |
| Sample expectation | 4 | F&G < 60 is a relatively loose filter; should preserve 60–80% of engulfing signals — ≥ 100 trades expected |
| Curve-fit risk | 3 | The 60/40 thresholds are not deeply literature-justified — they are chosen heuristically. If tested across multiple thresholds, requires Bonferroni. |
| **TOTAL** | **19/25** | |

**Critical issues:**  
- **Lookahead risk (EXPLICIT FLAG):** Doc itself states: "Bugünün F&G'yi bugünün sinyalinde kullanmak kesinlikle lookahead'dir. Kural: shift(1) zorunlu." This is identified — must verify implementation enforces shift(1). **Pre-backtest verification required.**  
- **Multiple testing correction:** If F&G threshold is swept (e.g., tested at 50, 55, 60, 65, 70), Bonferroni correction is mandatory. If single threshold pre-registered → no correction needed. **Must confirm single-threshold design.**  
- **DSR gate:** Not mentioned. Add.  
- F&G API data quality risk (2018+ only; informal source) — acceptable caveat.

---

### Forex Engulfing (EUR/USD, GBP/USD, USD/JPY)
**File:** `2026-05-09-forex-engulfing.md`  
**Status in doc:** DEFER (data quality issue — yfinance open==close on 74% of bars)

| Dimension | Score | Notes |
|---|---|---|
| Novelty | 3 | Testing existing crypto strategy on FX is asset-class extension; the mechanism is identical |
| Mechanical clarity | 5 | Same rule-based engulfing — no new discretion |
| Decorrelation | 4 | FX universe is structurally uncorrelated with crypto; different macro drivers |
| Sample expectation | 1 | ZERO signals due to data bug. yfinance open==close on 74% of bars — body detection impossible |
| Curve-fit risk | 4 | Parameters unchanged from crypto baseline (no additional fitting) |
| **TOTAL** | **17/25** | |

**Critical issues:**  
- **Data bug CONFIRMED:** yfinance 1.3.0 returns open==close on ~74% of FX daily bars. This is a known yfinance issue for forex daily data. Body ratio = 0 on 74% of bars → engulfing fires 0 times. **Hypothesis cannot be tested until data source is changed.**  
- **Recommended fix:** Switch to OANDA REST API, Alpha Vantage FX (free 20y daily), or Dukascopy. Lower body_ratio_min from 0.6 → 0.3 for forex.  
- **Score reflects blocked state.** If data fixed: re-score sample expectation at 3, total would be ~19. Worth pursuing.

---

### Perpetual Orderbook Imbalance (Forward Validation)
**File:** `2026-05-09-perp-orderbook-imbalance.md`  
**Status in doc:** FORWARD VALIDATION PENDING (4-week paper trading)

| Dimension | Score | Notes |
|---|---|---|
| Novelty | 5 | Real-time orderbook bid/ask imbalance as confirmation filter — genuinely new data source (L2 microstructure); not present in any prior hypothesis |
| Mechanical clarity | 4 | Imbalance formula is deterministic; threshold (|imbalance| > 0.6) is pre-defined |
| Decorrelation | 3 | Applied ON TOP of engulfing signals — not standalone. But the microstructure data source is orthogonal to all other inputs |
| Sample expectation | 2 | Forward-only (no historical backtest possible). 4 weeks × 10 symbols × ~3 signals/week = 30 target (very optimistic); 10–15 more realistic. n < 20 likely → statistically inconclusive |
| Curve-fit risk | 5 | Prospective forward data — zero risk of backtest overfitting by design |
| **TOTAL** | **19/25** | |

**Critical issues:**  
- **No lookahead by design** — real-time data only. Clean.  
- **Statistical power concern:** 4 weeks is almost certainly insufficient (10–15 trades vs 30 minimum needed). Should plan for 8–12 week accumulation period.  
- **Spoofing risk:** Large limit orders may be cancelled before fill — REST snapshot may capture phantom imbalance. Must monitor spoof_count.  
- **This hypothesis is structurally sound but chronologically blocked** until forward data accumulates. No backtest compute needed yet.

---

### Vol Risk Premium Fade
**File:** `2026-05-09-vol-risk-premium-fade.md`  
**Status in doc:** TESTING (not yet backtested)

| Dimension | Score | Notes |
|---|---|---|
| Novelty | 5 | Volatility (not price) mean-reversion via spike + contraction confirmation; completely different mechanism from all existing hypotheses; Sinclair VRP framework applied to crypto |
| Mechanical clarity | 4 | ATR% > 2× median30 (spike) + inside-bar or doji (contraction) are clear algorithmic rules. "OR doji" introduces slight ambiguity — define doji precisely (e.g., body < 10% of range) |
| Decorrelation | 5 | Counter-directional (short after bullish spike, long after bearish spike) — opposite to engulfing which is trend-following. Fires on vol spikes; engulfing fires on EMA pullbacks. Near-zero overlap |
| Sample expectation | 3 | 95th percentile vol spike is rare by definition (~5% of bars). 3y × 10 sym ≈ 1095 bars × 10 × 5% = ~547 spike bars; with contraction confirmation: ~100–200 signals. Borderline but likely ≥ 30 |
| Curve-fit risk | 4 | Spike threshold (2× median) is Sinclair-canonical; 30-bar median window is literature-standard. 95th percentile is self-adaptive. Few free parameters |
| **TOTAL** | **21/25** | |

**Critical issues:**  
- **Lookahead check:** `ATR%(T-1) > 2x median30` — must use rolling median of T-2 to T-31 (not including T-1 in the median) to avoid T-1 inflating its own comparison window. Specifically: `median_30 = ATR%.shift(1).rolling(30).median()` then compare `ATR%.shift(1) > 2 * median_30`. **Verify shift alignment in implementation.**  
- **"OR doji" definition:** Doji needs a precise rule before coding. Suggest: body ≤ 10% of high-low range.  
- **RSI > 80 filter** mentioned as "değerlendir" (consider) — must pre-register whether it is included or not. If swept → Bonferroni.  
- **DSR gate:** Not mentioned. Add (target ≥ 0.35 given ~100–200 trade count).  
- Strong candidate — pursue.

---

### BTC-ETH Pairs Cointegration (Statistical Arb)
**File:** `2026-05-09-btc-eth-pairs-cointegration.md`  
**Status in doc:** Pre-registered (not yet backtested)

| Dimension | Score | Notes |
|---|---|---|
| Novelty | 5 | Market-neutral pairs trading is a completely different strategy class from all directional hypotheses; statistically sophisticated (Engle-Granger, Ornstein-Uhlenbeck half-life) |
| Mechanical clarity | 4 | Mostly algorithmic; rolling OLS hedge ratio and ADF test are standard. "Dollar-neutral sizing" is well-defined |
| Decorrelation | 5 | Market-neutral by construction → zero directional exposure → theoretical correlation ≈ 0 with all directional strategies. Unique portfolio diversification value |
| Sample expectation | 4 | ±2σ spread entry with 7–25 day half-life on a liquid pair should generate 20–50 trades/year; 3y = 60–150 trades. Acceptable |
| Curve-fit risk | 3 | Rolling OLS window (60 bar) and z-score window (20 bar) are partially free. ADF threshold (0.05) is canonical. Two lookback windows could be over-fit if swept |
| **TOTAL** | **21/25** | |

**Critical issues:**  
- **Lookahead check (CRITICAL):** Rolling OLS hedge ratio β must use only [t-60, t-1] data — explicitly stated and shift(1) mentioned. Z-score rolling mean/std must also be on shifted spread. **Verify: `spread_t = log_BTC_t - β_t * log_ETH_t` where β_t is estimated from [t-60, t-1] — this is correct only if β uses shift(1) lookback.** The doc states this explicitly — CLEAN in design, must verify in code.  
- **Cointegration stationarity issue:** 2021 ETH DeFi/NFT divergence broke BTC-ETH cointegration. The 3-year window (2023–2026) may or may not include another breakage. Rolling ADF guard (p > 0.05 → no signal) is the correct mitigation — verify it is enforced.  
- **Multiple testing:** OLS window (60 bar) and z-score window (20 bar) are single pre-registered values — no sweep → no Bonferroni needed. If window is optimized → must correct.  
- **DSR gate:** Not stated. Add. Target Sharpe ≥ 1.0 (Chan reference) implies DSR ≥ 0.5 is achievable.  
- **High value hypothesis** — market-neutral + high expected Sharpe + zero correlation with existing book.

---

### Day-of-Week Calendar Effects
**File:** `2026-05-09-day-of-week-effects.md`  
**Status in doc:** REJECT (backtested, failed)

| Dimension | Score | Notes |
|---|---|---|
| Novelty | 2 | Calendar effects are widely documented and tested; not novel in crypto literature |
| Mechanical clarity | 5 | Fully algorithmic; Bonferroni-corrected Fisher exact test is methodologically correct |
| Decorrelation | 2 | Analysis of EXISTING trades — not a new signal |
| Sample expectation | 1 | ALREADY TESTED: 0/7 days passed Bonferroni-corrected threshold. n = 23.7/day → power < 5% |
| Curve-fit risk | 5 | No parameters (analysis only); correct multiple testing correction applied |
| **TOTAL** | **15/25** | |

**Critical issues:**  
- **Already tested and REJECTED.** Statistical power analysis confirms: detecting 10% WR difference requires n = 623/day — 26× more than available. Verdict was correctly REJECT.  
- **Methodological note:** The pre-registration + Bonferroni correction is the right approach. Lab Scientist commends the methodology even though the result is null. This is good science.  
- **No further compute needed.**

---

### Halving Cycle Phase Macro Sizing
**File:** `2026-05-09-halving-cycle-phase.md`  
**Status in doc:** Candidate (pre-backtest)

| Dimension | Score | Notes |
|---|---|---|
| Novelty | 4 | Using deterministic halving phases as a position-sizing modifier is novel in this codebase; no other hypothesis uses macro cycle timing |
| Mechanical clarity | 5 | Fully deterministic: halving dates are public, phase computation is date arithmetic — zero discretion, zero lookahead |
| Decorrelation | 4 | A sizing modifier does not conflict with any signal-generating hypothesis; it is orthogonal by design |
| Sample expectation | 1 | **CRITICAL:** 4 halvings × 4 phases = 16 global data points. The 3-year backtest window covers only 2 phases (Phase C ending + Phase A beginning). One cycle. Zero statistical power |
| Curve-fit risk | 2 | Phase boundaries (12/30/45/48 months) and size factors (1.0/0.5/0.75/1.0) are manually chosen. With 16 global samples and 4 parameters, degrees of freedom are exhausted |
| **TOTAL** | **16/25** | |

**Critical issues:**  
- **Statistical impossibility:** With n = 2 phases in the 3-year window, any apparent improvement in Phase A is inseparable from the 2024–2025 bull cycle effect. This is narrative fit, not statistical evidence.  
- **DSR gate is irrelevant here** — the fundamental problem is not sample count within the backtest, it's the number of independent cycle observations.  
- **Recommendation:** DEFER (not REJECT) — the mechanism is sound. Can be used as a "regime awareness" layer once 2+ full cycles are observable. Next test window: 2028+ after next halving. Track and revisit.

---

### BTC Dominance → Altcoin Rotation Filter (H22-A)
**File:** `2026-05-09-btc-dominance-altrotation.md`  
**ID conflict note:** This file assigns H22 but stablecoin supply also claims H22. Naming collision — must be resolved.

| Dimension | Score | Notes |
|---|---|---|
| Novelty | 4 | BTC.D slope as alt-season filter is a macro capital-flow signal not present in existing hypotheses; captures cross-asset rotation mechanism |
| Mechanical clarity | 4 | `btcd_slope = linear slope of BTC.D over trailing 30 bars (shift(1))` — fully algorithmic |
| Decorrelation | 4 | Applies only to altcoin longs (BTC excluded by design); does not change the base engulfing mechanism; decorrelated at data source level |
| Sample expectation | 3 | Depends on BTC.D data availability. Free API has 90-day limit per call; 3-year history requires multi-call workaround. Signal rejection rate expected 20–60% — not zero. Alt long signals still ~50–80 over 3y |
| Curve-fit risk | 3 | 30-bar slope window is a free parameter; different lookback might give different results. Single-cycle (2023–2026 bull) data means regime-specific overfitting risk |
| **TOTAL** | **18/25** | |

**Critical issues:**  
- **ID collision with stablecoin supply (both H22):** Must be renamed before implementation. Suggest H22-BTC.D and H22-StableSupply.  
- **Data API limitation:** CoinGecko free API limits 3-year BTC.D history to 90-day chunks with rate limiting. Multi-call workaround is documented but adds implementation complexity.  
- **Single-cycle non-stationarity (SELF-FLAGGED in doc):** 2023–2026 covers ONE bull cycle; BTC.D patterns are regime-specific. Cannot claim general validity.  
- **Correlated with F&G and 200-EMA trend filter:** BTC.D falling correlates with risk-on periods which also correlate with F&G < 60 filter and 200-EMA regime. The marginal information content may be low.  
- **Lookahead check:** shift(1) explicitly stated — CLEAN.  
- **DSR gate:** Not mentioned. Add.

---

### Stablecoin Supply Growth Liquidity Proxy (H22-B)
**File:** `2026-05-09-stablecoin-supply-liquidity.md`  
**ID conflict:** Also labelled H22 — see naming collision above.

| Dimension | Score | Notes |
|---|---|---|
| Novelty | 5 | Macro liquidity proxy via USDT+USDC total supply growth is a unique data source — no other hypothesis in this codebase uses on-chain stablecoin issuance data |
| Mechanical clarity | 5 | `stable_growth_30d = (supply_today - supply_30d_ago) / supply_30d_ago > 0` — fully binary, zero discretion |
| Decorrelation | 4 | Capital-flow data (on-chain issuance) is structurally different from price action, sentiment (F&G), orderbook, or funding rate. Low overlap expected |
| Sample expectation | 4 | Growth > 0 filter is loose enough to pass most bull-market signals. Likely 60–80% pass rate on long signals → preserves most trade count |
| Curve-fit risk | 4 | Single threshold (> 0 for growth) is the simplest possible choice; 30-day lookback is canonical. BUSD/LUNA contamination periods are acknowledged risks |
| **TOTAL** | **22/25** | |

**Critical issues:**  
- **Lookahead:** `stable_growth_30d[t-1] > 0` — shift(1) explicitly stated. CLEAN.  
- **SVBEK/LUNA outlier events (SELF-FLAGGED):** March 2023 USDC depeg and May 2022 LUNA collapse produce outlier supply data. Recommend: flag these 30-day windows and run sensitivity test (with/without). Not a blocker — just risk management.  
- **Correlation with F&G and BTC.D:** Stablecoin growth rises during risk-on (bull markets), which also coincides with F&G < 60 filter passing and BTC.D falling. **Multiple correlated filters layered together may not provide additive value.** Test marginal contribution of stable supply filter GIVEN F&G already applied (Scenario 4 vs Scenario 2 in doc).  
- **ID naming collision** — fix before implementation.  
- **DSR gate:** Not mentioned. Add.  
- **High value hypothesis** — novel data source, mechanically clean, passes sample test.

---

### Liquidation Cascade Fade
**File:** `2026-05-09-liquidation-cascade-fade.md`  
**Status in doc:** DEFER (data unavailability confirmed)

| Dimension | Score | Notes |
|---|---|---|
| Novelty | 5 | Event-driven strategy triggered by acute liquidation cascades — genuinely new mechanism; different from funding rate (continuous) and orderbook (snapshot) |
| Mechanical clarity | 4 | If data were available: cascade threshold (absolute + rolling 95th pctile) is algorithmic. Proxy version is also rule-based |
| Decorrelation | 5 | Counter-trend event-driven vs trend-following engulfing; fires during cascade events (chaotic bars) vs structured pullbacks. Expected correlation r < 0.15 |
| Sample expectation | 1 | **Data unavailable.** Proxy (OI drop + taker ratio) only covers 30 days (Binance taker ratio limit). n = 2 completed trades — statistically worthless |
| Curve-fit risk | 4 | Rolling 95th percentile is self-calibrating; avoids fixed threshold. Good design if data existed |
| **TOTAL** | **19/25** | |

**Critical issues:**  
- **Data availability is the only blocker.** CoinGlass requires $29/month. No free historical source provides 1–3 year liquidation data.  
- **Synthetic proxy n=2** — zero conclusions possible.  
- **Recommended path:** Implement OKX streaming accumulator (Option B from doc) to start building history NOW. In parallel, request CEO approval for $29/month CoinGlass Hobbyist if budget allows.  
- **DO NOT BACKTEST** until either: real historical data acquired OR 60+ days of OKX streaming data accumulated.  
- **Lookahead:** Proxy signal uses `liq_total.rolling(30).quantile(0.95).shift(1)` — correctly shifted. CLEAN in design.

---

## Summary Ranking Table

| Rank | Hypothesis | Total Score | Status | Critical Issue |
|---|---|---|---|---|
| 1 | Funding Rate MR v2.0 | 22/25 | DEFER (pending real-data re-run) | Post-hoc parameter fitting — re-run on live data required |
| 1 | Stablecoin Supply Liquidity | 22/25 | TESTING | ID naming collision; test marginal contribution vs F&G alone |
| 3 | Vol Risk Premium Fade | 21/25 | TESTING | Verify spike median shift alignment; pre-register doji definition |
| 3 | Donchian 55 + BB Squeeze | 21/25 | Pre-registered | Add DSR gate before backtest |
| 3 | BTC-ETH Pairs Cointegration | 21/25 | Pre-registered | Verify rolling OLS shift(1); rolling ADF guard enforcement |
| 6 | F&G Sentiment Filter (H18) | 19/25 | TESTING | Confirm shift(1) in implementation; confirm single threshold |
| 6 | Liquidation Cascade Fade | 19/25 | DEFER (data) | No backtest until CoinGlass or 60d OKX streaming |
| 6 | Perp Orderbook Imbalance | 19/25 | Forward validation | 4 weeks → extend to 8–12 weeks for statistical power |
| 9 | BTC.D Alt Rotation Filter | 18/25 | TESTING | H22 ID collision; single-cycle overfitting risk |
| 10 | AVWAP + POC Reversal | 17/25 | Pre-registered | Swing anchor lookahead risk — verify shift(1) in code |
| 10 | Pin Bar @ S/R + Trend | 17/25 | Pre-registered | Add DSR gate; signal count may be < 30 |
| 10 | Forex Engulfing | 17/25 | DEFER (data) | yfinance FX data bug — open==close on 74% of bars |
| 13 | Halving Cycle Phase Sizing | 16/25 | Candidate | n = 2 phases in 3y window; narrative fit risk; defer to 2028 |
| 14 | Day-of-Week Effects | 15/25 | REJECT (confirmed) | Already tested and rejected. No further compute needed |
| 15 | Engulfing 1D+4H Confluence | 12/25 | IN_TEST | Low novelty; same mechanism variant; check 4H UTC alignment |
| 16 | Engulfing 4H Frequency | 11/25 | REJECT (confirmed) | Already tested and rejected. DSR = 0. No further compute needed |

---

## Top 5 — PROMOTE for Implementation

These five hypotheses should receive backtest compute priority in this order:

### 1. Stablecoin Supply Liquidity (H22-B) — Score 22/25
**Why:** Novel data source (on-chain macro liquidity) orthogonal to all existing inputs. Mechanically clean binary filter. Expected to preserve ≥ 60% of trade count. CoinGecko free API available. Fix ID naming collision first.  
**Action:** Rename to H23 → run Scenario 4 backtest immediately.

### 2. Vol Risk Premium Fade — Score 21/25
**Why:** Completely different mechanism (volatility MR vs price trend-following). High decorrelation from engulfing. Sinclair-grounded with crypto-specific GARCH evidence. Expected 100–200 signals over 3y.  
**Action:** Pre-register doji definition → verify shift alignment in spike detection → run backtest → add DSR gate (target ≥ 0.35).

### 3. BTC-ETH Pairs Cointegration — Score 21/25
**Why:** Market-neutral → zero directional correlation with existing book. Only hypothesis that could add Sharpe without adding directional risk. Chan estimates Sharpe 1.0–1.8.  
**Action:** Verify rolling OLS uses shift(1) → verify rolling ADF guard fires correctly → run backtest → add DSR gate (target ≥ 0.5).

### 4. Donchian 55 + BB Squeeze Breakout — Score 21/25
**Why:** Turtle-canonical parameters (no overfitting). Strong decorrelation from engulfing (late breakout entry vs early pullback entry; trailing exit vs fixed 2R). Well-defined mechanical rules.  
**Action:** Add DSR gate (target ≥ 0.35) → run backtest → check signal correlation with engulfing < 0.35.

### 5. Funding Rate MR v2.0 — Score 22/25
**Why:** Highest structural edge — crypto-native mechanism (carry cost creates mechanical mean-reversion). Near-orthogonal to engulfing (r = -0.087). Counter-trend in low-ER regimes complements engulfing perfectly.  
**Action:** Re-run v2.0 on REAL DuckDB funding data (NOT synthetic). If win rate ≥ 55% and Sharpe ≥ 0.5 on real data → PROMOTE.

---

## Bottom 5 — DEFER or REJECT

### 1. Engulfing 4H Frequency — REJECT (Confirmed, Score 11/25)
DSR = 0, win rate 33.8%, negative Sharpe. 4H warmup period consumed expected signal advantage. Do not revisit without fundamentally different parameter design.

### 2. Day-of-Week Calendar Effects — REJECT (Confirmed, Score 15/25)
0/7 days passed Bonferroni-corrected test. Power analysis: need 623 trades/day vs 23.7 available. Do not revisit unless trade count increases 26×.

### 3. Halving Cycle Phase Sizing — DEFER until 2028 (Score 16/25)
Only 2 phases observable in 3-year window. 4 halvings × 4 phases = 16 global data points. Cannot claim statistical validity. Revisit after 2028 halving OOS data available.

### 4. Engulfing 1D+4H Confluence — DEFER (Score 12/25)
Low novelty (same mechanism). 4H standalone already rejected. If pursued, must show 4H confirmation actually improves win rate above baseline — unclear value-add after 4H REJECT.

### 5. Forex Engulfing — DEFER until data fixed (Score 17/25, conditionally)
yfinance data bug (open==close on 74% FX bars) makes testing impossible. Not a REJECT of the hypothesis — REJECT of the data source. Re-run with OANDA or Alpha Vantage FX data.

---

## Bugs Flagged — Fix Before Backtest

### BUG-001: AVWAP Swing Anchor Potential Lookahead
**File:** `anchored-vwap-poc-reversal.md`  
**Description:** The anchor bar selection ("last 60-bar fractal swing low") must use shift(1) so that bar T's anchor cannot be influenced by bar T itself. Doc self-flags this but no verification exists.  
**Required fix:** In `anchored_vwap_reversal.py`, confirm that `swing_low_anchor = low.rolling(60).idxmin().shift(1)` (or equivalent) — not `idxmin()` on window including current bar.

### BUG-002: F&G Lookahead Risk
**File:** `fear-greed-sentiment.md`  
**Description:** F&G index for day T is computed from day T's price and social data. If `fng_data[today]` is used for `signal[today]`, this is lookahead. Doc explicitly flags this and mandates shift(1).  
**Required fix:** Verify in implementation: `fg_score_shifted = fg_score.shift(1)` before comparison. Any join on timestamp must ensure FG data is from (T-1) not T.

### BUG-003: Vol Risk Premium Spike Median Alignment
**File:** `vol-risk-premium-fade.md`  
**Description:** `ATR%(T-1) > 2x median30` — the 30-bar median window must NOT include bar T-1 in its own comparison. Correct: `median30 = ATR%.shift(1).rolling(30).median()` THEN `spike = ATR%.shift(1) > 2 * median30`. If instead `rolling(30).median()` is computed on the original series then shifted, bar T-1 participates in its own threshold — subtle lookahead.  
**Required fix:** Verify the rolling median uses `rolling(30, min_periods=15).median().shift(1)` on the ATR% series, compared against `ATR%.shift(1)`.

### BUG-004: H22 ID Naming Collision
**Files:** `btc-dominance-altrotation.md` (H22) and `stablecoin-supply-liquidity.md` (H22)  
**Description:** Two hypothesis documents claim the same ID (H22). This will cause database key collision if both are stored in any indexed system.  
**Required fix:** Rename BTC Dominance hypothesis to H23 or H22-BTCD; rename Stablecoin hypothesis to H22-STABLE or assign clean sequential IDs.

---

## Multiple Testing Correction Assessment

| Hypothesis | Parameter Sweep? | Bonferroni Required? | Note |
|---|---|---|---|
| Donchian 55 + BB Squeeze | Single pre-registered config | NO | Turtle-canonical values |
| Funding Rate MR v2.0 | v1→v2 design changes after seeing failure | PARTIAL | Re-run on fresh data counts as OOS validation |
| Vol Risk Premium Fade | RSI > 80 filter "değerlendir" (consider) | YES if RSI swept | Pre-register RSI on/off before backtest |
| F&G Sentiment | Single threshold (60/40) | YES if threshold swept | Confirm single pre-registered value |
| BTC-ETH Pairs | OLS window 60-bar single value | YES if window swept | Confirm single config |
| BTC.D Alt Rotation | 30-bar slope single window | YES if swept | Confirm single config |
| Stablecoin Supply | 30-day growth > 0 (binary) | NO | Single threshold, binary |
| Day-of-Week (done) | 7 groups tested | YES — already applied Bonferroni ✓ | Correctly handled |

---

## DSR Gate Status

All new hypotheses should include a Deflated Sharpe Ratio gate before PROMOTE decision.
Based on the 1D engulfing baseline (DSR = 0.18, n=166 trades, Sharpe=0.371):

| Hypothesis | Expected N trades | Target DSR | Note |
|---|---|---|---|
| Donchian Breakout | 60–120 | ≥ 0.35 | Higher N → higher DSR ceiling |
| Funding MR v2.0 | 84 | ≥ 0.30 | Tested; compute after real-data re-run |
| Vol Risk Premium Fade | 100–200 | ≥ 0.35 | DSR improves with N |
| BTC-ETH Pairs | 60–150 | ≥ 0.40 | Higher target due to lower variance (market-neutral) |
| Stablecoin Supply | 100–130 (filter) | ≥ 0.30 | Filter layer — baseline DSR carries over |
| F&G Sentiment | 100–130 (filter) | ≥ 0.30 | Same rationale |
| AVWAP + POC | 30–60 | ≥ 0.25 | Lower N → lower achievable DSR |
| Pin Bar @ S/R | 40–80 | ≥ 0.25 | Same |

Formula reference: `DSR = (Sharpe - E_max_Sharpe) / StdDev_Sharpe` where `E_max_Sharpe` accounts for the number of trials. Minimum bar: DSR ≥ 0.25 for any PROMOTE decision.

---

## Executive Decisions

| Decision | Rationale |
|---|---|
| PROMOTE: Stablecoin Supply, Vol Risk Premium, BTC-ETH Pairs, Donchian Breakout | High score, novel mechanisms, sufficient sample expectation |
| CONDITIONAL PROMOTE: Funding Rate MR | Must re-run v2.0 on real data first; synthetic sweep insufficient |
| DEFER: Halving Phase, Forex Engulfing, Orderbook Imbalance, Liquidation Cascade | Data/statistical blocking — revisit when conditions met |
| DEFER: AVWAP + POC, BTC.D Alt Filter, Pin Bar @ S/R | Pre-backtest bugs or medium confidence — fix then backtest |
| REJECT (confirmed): 4H Frequency, Day-of-Week | Already tested, failed gates |
| DEFER (low novelty): 1D+4H Confluence | Until 4H shows merit in a different configuration |

---

*Report generated: 2026-05-09*  
*Lab Scientist Agent — Price Action Trading Co.*  
*Next review: After top-5 backtests complete*
