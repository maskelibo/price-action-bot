# Hypothesis: BTC Dominance → Altcoin Rotation Timing Filter

**ID:** H22
**Date:** 2026-05-09
**Researcher:** Autonomous Research Agent
**Status:** IN_TEST

---

## Hypothesis Statement

When BTC Dominance (BTC.D = BTC market cap / total crypto market cap) is in a
**30-bar falling trend**, capital is rotating OUT of BTC into altcoins ("alt season").
Engulfing LONG signals on altcoins during this regime should have a higher win rate
than during BTC-dominant regimes when alts underperform.

**Filter rule:**
- Compute `btcd_slope` = linear slope of BTC.D over trailing 30 bars (shift(1) applied)
- `btcd_slope < 0` → BTC.D falling → alt rotation regime → ALLOW alt long signals
- `btcd_slope >= 0` → BTC.D rising → BTC dominant regime → BLOCK alt long signals
- **BTC itself is NEVER filtered** — BTC dominance rising means BTC is outperforming,
  so BTC long signals should pass unconditionally

---

## Data Source

- **API:** CoinGecko free API (no key required, 30 req/min)
- **Current snapshot:** `GET /api/v3/global` → `data.market_cap_percentage.btc`
- **Historical (3y):** `GET /api/v3/coins/bitcoin/market_chart?vs_currency=usd&days=N`
  gives BTC market cap; total market from global endpoint snapshots
- **Fallback:** Synthetic BTC.D constructed from BTC_mcap / sum(top_coin_mcaps)
- **Storage:** DuckDB `data/dominance.duckdb`, table `btc_dominance_daily`
- **Lookback:** ~1095 days (3 years, May 2023 → May 2026)

### Free API Limitations
- `global/market_cap_chart?days=1095` → **401 Unauthorized** (requires CoinGecko Pro)
- `coins/bitcoin/market_chart?days=1095` → **401 Unauthorized** on demo tier
- **Practical maximum per call:** ~90 days on free demo key (or 365 with delays)
- **Workaround:** Multi-call with 90-day windows + rate limit sleep, or mock fallback

### Non-Stationarity Warning (CRITICAL)
The 3-year window (2023-2026) covers:
- 2023: BTC recovery / macro-crypto correlation high
- 2024: BTC ETF approval, BTC Halving (April 2024) → massive BTC dominance surge
- 2025-2026: Potential alt season phase

This is effectively **one bull cycle**. BTC.D trends are regime-specific and may not
generalize across bear markets or new macro regimes. Results must be interpreted as
cycle-specific, not universal.

---

## Mechanism

```
Alt capital flow:
  BTC.D ↑ → BTC outperforms → alt underperform → long alt signals noisy
  BTC.D ↓ → Alts outperform → long alt signals higher quality

Filter application:
  For each engulfing LONG signal on symbol S:
    if S == BTC: PASS unconditionally
    elif btcd_slope[t-1] < btcd_trend_max (0.0): PASS
    else: BLOCK
```

---

## Metrics & Null Hypothesis

**H0:** BTC.D trend has no effect on altcoin engulfing long win rate
**H1:** Alt engulfing long win rate is higher when BTC.D is in a 30-bar downtrend

**Gates (alt long signals only):**
- Win rate uplift ≥ +2pp vs unfiltered baseline
- Signal rejection rate between 20-60% (if < 20%: filter too loose; > 60%: too restrictive)
- Annualized return delta ≥ -5pp vs F&G filtered baseline (filter should not destroy returns)
- Sharpe ratio non-decreasing vs F&G baseline

---

## Scenarios

| Scenario | Description |
|----------|-------------|
| S1       | Engulfing solo (baseline) |
| S2       | Engulfing + F&G filter only |
| S3       | Engulfing + F&G + BTC.D filter (alt-only) |

BTC/USDT is included in all scenarios but the BTC.D filter is NEVER applied to it.
The delta S3 vs S2 isolates the contribution of the BTC.D filter.

---

## Prior Knowledge

- BTC Dominance cycles are well-documented: ~2017-2018 alt season, ~2020-2021 alt season
- Within a single cycle, dominance trends can persist for weeks to months
- The "alt season index" (blockchaincenter.net) uses 75% of top-50 alts outperforming
  BTC over 90d — related but different metric
- Risk: The filter may simply capture the same information as price momentum already
  embedded in the 50-EMA trend filter of the engulfing strategy

---

## Expected Outcome

**Likely DEFER or marginal PROMOTE:**
- 3-year single-cycle data is insufficient to claim statistical significance
- BTC.D regime tends to be correlated with macro risk-on/off (already partially
  captured by F&G index)
- The filter adds a market-structure layer F&G does not capture, but may overfit
  to the 2023-2026 cycle's specific alt rotation pattern

**Tradeable if:**
- Win rate uplift > +3pp on alts specifically (not masked by BTC noise)
- Rejection rate 25-45% (meaningful but not too aggressive)
- Result stable across at least ETH, SOL, BNB, XRP (4+ alts showing consistent sign)
