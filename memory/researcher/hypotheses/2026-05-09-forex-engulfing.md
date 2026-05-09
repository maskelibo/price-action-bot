# Hypothesis: Engulfing Continuation on Forex Majors (1D)

**ID:** 2026-05-09-forex-engulfing  
**Status:** TESTING  
**Created:** 2026-05-09  
**Researcher:** autonomous-researcher  

---

## Hypothesis

The EngulfingContinuation strategy — already evaluated on 10 crypto/USDT pairs — may
exhibit stronger edge on FX major pairs due to structural differences between the asset
classes:

1. **Institutional dominance.** EUR/USD, GBP/USD, USD/JPY daily volume is driven by
   central banks, large commercials, and macro funds that create cleaner mean-reversion
   after over-extension — exactly the regime where an EMA pullback + engulfing pattern
   has theoretical edge.

2. **Volman & Brooks context.** Both "Forex Price Action Scalping" (Volman) and
   "Trading Price Action" (Brooks) were originally written with forex and index futures
   in mind. Engulfing / rejection bars are described as high-probability in these
   institutionally-traded markets.

3. **24/5 continuity, no funding costs.** Unlike crypto, forex does not have an
   overnight funding rate that distorts daily-bar open/close alignment. Weekend gaps
   exist but are small for majors (< 30 pips typical).

4. **Longer history.** yfinance provides 20+ years of daily data for forex; this
   study uses 5 years (2021-2026) to match a comparable macro cycle length.

5. **Mean-reversion tendency.** Major forex pairs exhibit lower autocorrelation of
   daily returns than BTC/ETH in bull cycles, potentially favouring counter-trend
   pullback + continuation entries rather than trend-following.

---

## Test Universe

| Pair    | yfinance ticker | Rationale                              |
|---------|-----------------|----------------------------------------|
| EUR/USD | EURUSD=X        | Most liquid pair, EUR monetary policy  |
| GBP/USD | GBPUSD=X        | High vol, BOE divergence plays         |
| USD/JPY | JPY=X           | Risk-on/off proxy, BOJ policy cycles   |

---

## Parameters (unchanged from crypto baseline)

- Timeframe: 1D
- Data range: 5 years (2021-05 → 2026-05)
- Strategy: `engulfing_continuation` manifest (body_ratio_min=0.6, pullback_window=10)
- Trend filter: 50-EMA required
- ER filter: kaufman_er_min=0.20 (same chop reject)
- Regime filter: bear_regime_size_factor=0.5 (200-EMA proxy)
- Risk: 1% fixed-fractional, 2R TP, structural SL
- Commission: 1.0 pip (0.010% round-trip) — conservative major-pair spread
- Slippage: 2 bps (vs 5 bps crypto; forex ECN is tighter)

---

## Null Hypothesis

H0: Engulfing continuation has no positive expectancy on forex major daily bars.  
Edge (if any observed in crypto) is crypto-specific and does not transfer.

## Alternative Hypothesis

H1: Forex institutional structure produces cleaner engulfing pullback setups, yielding
Sharpe > 0.5 and positive expectancy at the per-trade level even after realistic costs.

---

## Success Criteria (PROMOTE threshold — lower than crypto Faz-2 gate)

| Metric          | Threshold  | Rationale                                     |
|-----------------|------------|-----------------------------------------------|
| Win rate        | >= 45%     | Forex lower vol => tighter RR distribution    |
| Profit factor   | >= 1.1     | Any positive edge qualifies for next step     |
| Avg Sharpe      | >= 0.4     | Lower bar than crypto (3 pairs only)          |
| Avg MaxDD       | <= 25%     | Forex lower vol; allow slightly higher DD%    |
| N trades        | >= 15 (3y) | Minimum statistical sample per symbol          |

---

## Risks & Mitigations

| Risk                                | Mitigation                                      |
|-------------------------------------|-------------------------------------------------|
| yfinance data quality (gaps, adj)   | Validate row count vs expected trading days     |
| Spread varies by broker/time        | Fixed 1-pip conservative estimate               |
| Only 3 pairs — small sample         | Report per-pair + aggregate, flag low N         |
| Crypto edge was limited (weak edge) | If forex also weak, conclude pattern is generic |
| JPY=X ticker inverted (USD per JPY) | Handle in ingest: use JPY=X as USDJPY directly  |

---

## Crypto Baseline (reference)

From `run_engulfing_backtest.py` prior results (10 crypto symbols, 3y, 1D):

- BTC: weak (trending too much, low signal frequency after ER filter)
- ETH/BNB/AVAX/DOT: modest positive edge
- Aggregate: marginal Sharpe, ROI gate FAIL

If forex aggregate Sharpe < crypto aggregate Sharpe → REJECT  
If forex aggregate Sharpe > crypto aggregate Sharpe → PROMOTE to Faz-3 for forex universe

---

## Test Results (2026-05-09)

**Status: DEFER (data quality)**

### Data Quality Finding
yfinance 1.3.0 forex daily data has a critical bug: `open == close` on ~74% of bars
(959 / 1300 bars for EUR/USD). This makes body detection impossible:

- EUR/USD: open==close on 959/1300 bars; raw_bull_engulf=2, raw_bear_engulf=0
- GBP/USD: open==close on similar proportion; total_raw_engulf=5
- USD/JPY: raw_bull_engulf=1, raw_bear_engulf=0

### Why Zero Signals
The strict engulfing requires `body_ratio >= 0.6` (body/range). With open==close,
body=0 so body_ratio=0 on 74% of bars. Even without body_ratio, genuine engulfing
(where current close exceeds previous open) is rare on forex 1D because:
- EUR/USD daily ATR ~0.55% vs BTC/USDT ~3.1%
- Engulfing full previous bar body on 0.55% ATR days is structurally rare

### Root Causes (Two Separate Issues)
1. **Data bug**: yfinance open field corrupted on forex historical data (known issue)
2. **Parameter mismatch**: body_ratio_min=0.6 tuned for crypto is too strict for forex
   even with correct data (forex bodies are naturally smaller relative to range)

### Next Steps (post-test)

Data alternatives to try if hypothesis is re-run:
- OANDA REST API (free account, reliable OHLCV)
- Alpha Vantage forex (free tier, 20y daily)
- Dukascopy historical (highest quality, requires scraping)

If data quality is resolved:
- Lower body_ratio_min to 0.3 for forex
- Test GBP/JPY, AUD/USD (higher vol crosses) for more engulfing frequency
- Consider 4H timeframe: more bars, more engulfing opportunities

### Verdict: DEFER
Cannot fairly test the hypothesis with corrupted open prices.
The engulfing pattern detection is fundamentally broken on yfinance forex data.
Not REJECT — the hypothesis remains open until clean data is obtained.
