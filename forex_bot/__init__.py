"""forex_bot — Forex sibling of price_action crypto bot.

Mirror of src/price_action with forex-specific adaptations:
- Dukascopy data ingestion (15m + 1m + tick)
- Session-aware signals (Asia/London/NY)
- News guard (high-impact events)
- Smart money concepts calibrated for forex microstructure
- Realistic cost model (spread/commission/swap/slippage/weekend gap)
"""

__version__ = "0.1.0"
