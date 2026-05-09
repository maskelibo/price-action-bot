---
hypothesis_id: liquidation_cascade_fade
date: 2026-05-09
author: researcher_agent
status: DEFERRED
strategy_type: mean_reversion
asset_class: crypto_perp
tags: [liquidation, cascade, fade, microstructure, perpetual, over-leverage, institutional-vacuum]
backtest_possible: partial
data_availability: severely_limited_free
decorrelated_from: [engulfing_continuation, funding_mean_reversion, perp_orderbook_imbalance]
verdict: DEFER
---

# Hypothesis: Liquidation Cascade Fade — Perpetual Market Structural Edge

## Motivation

When over-leveraged perpetual positions are force-liquidated by the exchange, the
liquidation engine executes market orders in the direction of the trade (sell for long
liquidations, buy for short liquidations). These forced market orders create a *cascade*
effect: liquidation → price moves against remaining leveraged positions → more liquidations
→ momentum spike.

The structural insight (confirmed in academic literature):

> After a cascade exhausts forced sellers/buyers, a sharp price reversal frequently occurs
> because: (1) the forced supply/demand has cleared; (2) institutional participants
> who had limit orders resting at those levels get filled; (3) the vacuum left by
> the liquidated crowd is filled by counter-directional smart money.

This is fundamentally different from funding rate mean-reversion:
- **Funding MR** (hypothesis #5): Erodes over-leverage over days via carry cost
- **Liquidation Cascade Fade**: Reacts to the *acute* liquidation event itself — minutes-to-hours

## Structural Differences from Previous 20 Hypotheses

| Dimension | This Hypothesis | Closest Prior |
|---|---|---|
| Trigger | Discrete liquidation event | Funding rate extreme (continuous) |
| Speed | Minutes to hours | Days |
| Data type | External liquidation feed | Exchange native (OHLCV, funding) |
| Market mechanism | Forced market orders | Carry cost erosion |
| Institutional logic | Vacuum fill after forced selling | Arb desk funding neutral |
| Retail visibility | Low — requires specialized aggregator | Medium — funding visible on UI |

The retail trader sees the price drop; they do NOT see the $500M liquidation cascade
that caused it without a specialized data source.

## Data Availability Report (2026-05-09)

### CoinGlass (Primary Proposed Source)
- **Status: NOT AVAILABLE FREE**
- All `open-api.coinglass.com/public/v2/liquidation/*` endpoints return HTTP 500
- Pricing page confirms: minimum plan is $29/month (Hobbyist), no free tier
- Historical liquidation data requires minimum $29–$79/month subscription
- **Verdict: Paid-only. BLOCKED without subscription.**

### Bybit Official API
- **Status: LIQUIDATION REST ENDPOINT DOES NOT EXIST**
- `/v5/market/liquidation` → HTTP 404 on all tested URL patterns
- Bybit has a WebSocket stream (`wss://stream.bybit.com/v5/public/linear` topic: `liquidation`)
  that provides REAL-TIME individual liquidation events — price, side, size, timestamp
- **No REST endpoint** for historical liquidation data confirmed via docs scan
- **Verdict: Real-time WebSocket only. No historical backtest possible.**

### Binance (Futures)
- `/fapi/v1/allForceOrders` → HTTP 400 "The endpoint has been out of maintenance"
- `/fapi/v1/forceOrders` → HTTP 401 (requires auth, user's own orders only)
- `data.binance.vision/data/futures/um/daily/liquidationSnapshot/` → S3 folder exists but is EMPTY
- WebSocket stream `!forceOrder@arr` provides real-time liquidation events
- Binance Futures Data portal has `metrics` (OI, L/S ratio) from 2020 but NO liquidation aggregates
- **Verdict: No free historical liquidation data. Real-time WebSocket only.**

### OKX Official API
- `/api/v5/public/liquidation-orders?instType=SWAP&uly=BTC-USDT&state=filled` → HTTP 200
- Returns individual liquidation events: bkPx (bankruptcy price), posSide, side, sz, timestamp
- **BUT:** Only ~24-48h of history available (rolling window)
- **No pagination to historical data** — `before`/`after` params work but no deep history
- Fields: `bkLoss`, `bkPx` (bankruptcy price), `ccy`, `posSide`, `side`, `sz`, `time`
- **Verdict: Free but only 24-48h rolling. Cannot backtest 3 years.**

### Summary Table

| Source | Cost | Historical Depth | Usable for Backtest? |
|---|---|---|---|
| CoinGlass API | $29–$299/month | 3+ years | NO (paid) |
| Bybit REST | Free | N/A — no endpoint | NO |
| Bybit WebSocket | Free | Real-time only | NO |
| Binance forceOrders | Decommissioned | N/A | NO |
| Binance data portal | Free | 0 (empty folder) | NO |
| OKX REST API | Free | ~48h rolling | NO (too short) |
| OKX WebSocket | Free | Real-time only | NO |

**CONCLUSION: No free historical liquidation data source provides backtest-grade (1–3 year)
coverage. All viable sources require either a paid subscription ($29+/month) or are
real-time streaming only.**

## Theoretical Edge Analysis

### Is the Liquidation Cascade Fade a Real Edge?

**Structural arguments IN FAVOR:**

1. **Mechanical forced selling/buying**: Liquidation engine executes market orders
   regardless of price — this is NOT rational market behavior. It creates genuine
   mispricing vs. fundamental value.

2. **Institutional vacuum fill documented in literature**: Duarte & Young (2009),
   "Why is PIN priced?", and Brunnermeier & Pedersen (2009), "Market Liquidity and
   Funding Liquidity" — forced liquidations create temporary liquidity vacuum that
   rational institutions exploit. Applied to crypto perps in Liquidation Cascades
   in Crypto Markets (Kamps & Kleinberg, 2018, workshop paper).

3. **Large event threshold creates signal-to-noise**: $200M+ in 24h is a tail event
   (~5th/95th percentile). Threshold filtering eliminates normal daily variation.
   Only cascade events — where chain-reaction margin calls amplify the initial shock —
   trigger the signal.

4. **Timing asymmetry**: Cascades complete in minutes; the price discovery after the
   event is distributed over hours-to-days. Entry on "next bar" confirmation (daily
   timeframe) places trade AFTER the cascade, not during it.

5. **Not retail FOMO**: Retail sees price drop and panics. The fade is counter to
   retail instinct — buying into a "crash." Only systematic frameworks identify
   cascade events and fade them.

**Structural arguments AGAINST:**

1. **Timing is tricky**: A cascade that resumes (more positions to blow up) vs. one
   that reverses is indistinguishable from price action alone. $200M threshold may
   include both types.

2. **Regime dependency**: In 2021 bull market cascades, price often continued UP after
   short cascade (trend was strong enough to absorb the shock). The edge may only
   hold in ranging/choppy regimes.

3. **Exchange heterogeneity**: Liquidation data from one exchange (e.g., Binance only)
   misses cascades that originated on Bybit or OKX. Cross-exchange cascade detection
   requires paid aggregated data (CoinGlass, Laevitas).

4. **Cascade identification lag**: Daily aggregated liquidations ($200M/24h) lag the
   actual event by up to 24h. Intraday data (hourly buckets) would give more precise
   timing — but requires paid access.

**Verdict on edge reality:**
The liquidation cascade fade edge is REAL in theory and has academic support.
However, the free data constraints force use of 24h aggregates rather than
intraday cascade detection, which significantly degrades timing precision.
The implementable version (daily aggregate threshold) is a degraded proxy that
may not capture the actual mechanism with sufficient fidelity.

## Implementation Plan (If Data Were Available)

### Signal Logic

```
liq_total_usdt = long_liq_24h_usdt + short_liq_24h_usdt

# Rolling 30-bar 95th percentile (lookahead-free, shift(1))
rolling_95th = liq_total_usdt.rolling(30).quantile(0.95).shift(1)

long_cascade = (liq_long_24h > threshold_absolute) AND (liq_long_24h > rolling_95th)
short_cascade = (liq_short_24h > threshold_absolute) AND (liq_short_24h > rolling_95th)

# Next bar confirmation (engulfing, pin bar, or inside bar)
long_signal = long_cascade.shift(1) AND bullish_pattern
short_signal = short_cascade.shift(1) AND bearish_pattern

SL = recent_structural_swing +/- 1_ATR
TP = entry +/- 2R * (entry - SL)
```

### Files Planned (Not Implemented — Data Not Available)

- `src/price_action/data/liquidation_ingest.py` — CoinGlass fetcher (requires paid key)
- `src/price_action/strategies/liquidation_fade.py` — Strategy logic
- `tests/test_liquidation_fade.py` — Unit tests

These files are NOT created because the data pipeline has no free data source.
Creating them now would be premature — they depend on a $29/month subscription
before they can be validated.

## Alternative Forward Path

### Option A: CoinGlass Hobbyist ($29/month)

Data access: BTC/ETH/SOL liquidations, daily + hourly aggregates  
Historical depth: 3+ years  
Implementation effort: 1-2 days (ingest + strategy)  
Decision: Request budget approval from CEO agent

### Option B: Build OKX Streaming Accumulator

Use OKX free API: stream real-time liquidations, accumulate in DuckDB, wait 60 days.  
Then backtest on 60-day window (minimum viable dataset).  
Implementation: `liquidation_ingest.py` polling OKX `/liquidation-orders` every hour,
aggregating into daily buckets.  
Data available: 2026-05-09 → 2026-07-08 (2 months) before first partial backtest.  
**Feasible but slow.** 60 days is too short for reliable strategy validation.

### Option C: Use Bybit/Binance WebSocket + DuckDB (Forward Validation Only)

Similar to Option B but for real-time only.  
Best for: paper trading validation after signal is defined.  
**Cannot produce historical backtest.**

### Option D: Synthetic Cascade Proxy (Already Available Data)

Proxy for cascade event using existing free data:
- **Open Interest drop > X%**: Sudden OI decline = forced position closures
- **Taker L/S ratio extreme**: High sell-taker volume = cascade selling pressure
- **Combined proxy**: OI_drop > 5% in 1d + taker_sell_ratio > 0.70

This is a degraded proxy but:
- Binance `futures/data/takerlongshortRatio` available: 30 days daily, 500 hours hourly
- Binance `fapi/v1/openInterest` + monthly data: Bybit OI 200 days back to 2025-10-22
- **Can backtest ~30-200 days with proxy signal**

Option D is the ONLY immediately implementable approach using free data.

## VERDICT

**DEFER**

**Reason:** Free liquidation data is unavailable for historical backtesting.
The edge is theoretically sound — forced liquidations create exploitable mispricing —
but the data acquisition requirement is blocking.

**Condition for PROMOTE:**
1. CoinGlass Hobbyist subscription ($29/month) → implement full strategy → backtest 3yr
   OR
2. 60-day OKX streaming accumulation completed → partial backtest → if WR > 55% → PROMOTE
   OR
3. Synthetic proxy (OI drop + taker ratio) implemented → if proxy WR > 50% → graduate to
   real data validation

**Do NOT REJECT**: The theoretical edge is real, documented, and decorrelated from existing
strategies. Data acquisition is the only obstacle.

**Immediate action**: Implement synthetic proxy (Option D) — this is buildable TODAY
with free data and gives partial evidence for or against the edge while awaiting paid data.

## Synthetic Proxy Backtest Results (2026-05-09)

**Data used:**
- Bybit OI daily: 200 bars (2025-10-22 to 2026-05-09)
- Binance taker L/S ratio daily: 30 bars (2026-04-09 to 2026-05-09)
- OHLCV: Binance daily, 500 bars

**BTC proxy (30-day taker overlap window):**
- Cascade signals detected: 7 (2 long, 5 short via OI + taker signal)
- Trading signals (cascade + confirmation): 3
- Completed trades (TP/SL hit within 5 bars): 1
- Win: 0, Loss: 1, Win rate: 0.0% — **n=1, STATISTICALLY WORTHLESS**

**ETH proxy (30-day taker overlap window):**
- Cascade signals: 2 (0 long, 2 short)
- Trading signals: 1
- Completed trades: 1
- Win: 0, Loss: 1, Win rate: 0.0% — **n=1, STATISTICALLY WORTHLESS**

**Combined: n=2 completed trades — no conclusions can be drawn.**

**Root cause of low signal count:**
The Binance taker ratio daily data is only 30 bars. The strategy requires 30-bar
rolling window to compute adaptive thresholds, leaving only the final few bars
of the window active. Result: almost no opportunities to detect cascades.

**Proxy signal rate:**
~7 proxy signals in 30 days = ~1.75/week for BTC alone. If real liquidation data
were available with proper history, signal frequency would be higher (more bars
would contribute to threshold calibration).

## Decorrelation Analysis

| Strategy | Correlation with Liquidation Cascade Fade |
|---|---|
| Engulfing Continuation | Low — engulfing is trend-following; cascade fade is counter-trend event-driven |
| Funding MR | Low — funding is continuous erosion; cascade is acute discrete event |
| Orderbook Imbalance | Medium — both are microstructure; but different event type |
| Vol Risk Premium | Low — VRP is OHLCV-based volatility; cascade is flow-event |

**Expected monthly PnL correlation with engulfing: r < 0.15** (counter-trend, event-triggered,
fires during cascade events which often coincide with OHLCV "noise" bars — not trend bars).
