# Moving Averages: Simple and Exponential

**Author:** ChartSchool / StockCharts.com  
**Date:** (continuously updated)  
**Source URL:** https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-overlays/moving-averages-simple-and-exponential  
**Category:** classic_pa, quant_finance  
**Quality:** 5

---

## Overview

A moving average calculates the mean of data points — typically price — over a specific period. The term "moving" reflects how each calculation uses data from the prior X periods. Since moving averages rely on historical data, they smooth price action and create trend-following signals, though they inherently lag behind current prices.

## Key Characteristics

Moving averages serve multiple purposes:
- Identifying trend direction
- Defining support and resistance zones
- Foundation for other technical indicators (Bollinger Bands, MACD, Keltner Channels)

Importantly, they **define** current direction rather than **predict** future movement.

## The Lag Factor

The lag between price and moving average varies based on two factors:

1. **Time period length**: Longer averages lag more. A 10-day average tracks prices closely ("like speedboats"), while a 100-day average moves sluggishly ("like ocean tankers").

2. **Average type**: Exponential moving averages (EMAs) lag less than simple moving averages (SMAs) because EMAs weight recent prices more heavily.

## Simple Moving Average (SMA)

An SMA computes the arithmetic mean of closing prices over a specified number of periods. Each data point carries equal weight.

Example — 5-day SMA with closing prices [11, 12, 13, 14, 15, 16, 17]:
- Day 1: (11+12+13+14+15)÷5 = 13
- Day 2: (12+13+14+15+16)÷5 = 14
- Day 3: (13+14+15+16+17)÷5 = 15

"Old data is dropped as new data becomes available, causing the average to move along the time scale."

## Exponential Moving Average (EMA)

EMAs reduce lag by applying greater weight to recent prices. The calculation:

1. Calculate initial SMA for the period
2. Compute weighting multiplier: 2 ÷ (Time periods + 1)
3. Apply: {Close - EMA(previous)} × multiplier + EMA(previous)

For a 10-period EMA: multiplier = 2/(10+1) = 0.1818 (18.18% weight to current price). Shorter periods carry proportionally higher weights.

**Accuracy note:** "The current EMA value will change depending on how much past data you use." Extending calculations far back historically maximizes accuracy.

## Practical Applications

### Identifying Trends

Moving average direction reveals trend character:
- Rising averages → uptrend
- Falling averages → downtrend
- "A rising long-term moving average reflects a long-term uptrend"

However, trend reversals occur with lag — meaningful price moves may precede directional changes in the average itself.

### Trading Signals

**Moving Average Crossovers:**
- Shorter crosses above longer (golden cross) → bullish signal
- Shorter crosses below longer (death cross) → bearish signal
- Risk: signals arrive late; produce false positives during choppy markets

**Price Crossovers:**
- Price moves above MA → bullish
- Price moves below MA → bearish
- Common approach: 200-day for overall trend direction + 50-day for entry timing

### Support and Resistance

Moving averages function as dynamic support/resistance:
- Support during uptrends (price pulls back to MA then bounces)
- Resistance during downtrends (price rallies to MA then reverses)

"The 200-day moving average may offer support or resistance because it's widely used. It is almost like a self-fulfilling prophecy."

Expect support/resistance **zones** rather than exact price levels.

## Comparative Advantages

| Feature | SMA | EMA |
|---------|-----|-----|
| Lag | Higher | Lower |
| Recent price weight | Equal | Greater |
| Turn timing | Later | Earlier |
| Best use case | Support/resistance zones | Responsive trading signals |

## Common Period Settings

| Period | Character | Use Case |
|--------|-----------|----------|
| 10-day | Fast, reactive | Short-term trading |
| 20-day | Moderate | Swing trading |
| 50-day | Medium-long | Intermediate trend |
| 200-day | Slow, definitive | Long-term trend, institutional reference |

## Key Takeaway

"Moving averages are trend-following, or lagging, indicators that will always be a step behind." They work effectively during sustained trends but produce whipsaws in ranging markets. Most effectively used alongside complementary tools — for instance, combining moving averages with RSI to assess overbought/oversold conditions, or with ATR for volatility context.

---

*Keywords: moving average, SMA, EMA, golden cross, death cross, trend following, support, resistance, Bollinger Bands, MACD, lag, crossover signals, 200-day MA, 50-day MA*
