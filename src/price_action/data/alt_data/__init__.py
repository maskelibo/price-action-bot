"""Alt-data feed modülleri.

Bu paket OHLCV dışındaki veri kaynaklarını (funding rate, open interest,
liquidation proxy, on-chain) pipeline'a entegre eder.

Modüller:
    funding_rate_ingest  — Binance USDT-perp funding rate → DuckDB
    open_interest_ingest — Binance/Bybit OI history → DuckDB
    liquidation_proxy    — OHLCV + ATR + volume_z → proxy liquidation columns
    merge                — Alt-data → OHLCV LEFT JOIN merge helpers

Her modül bağımsız çalışabilir; merge modülü hepsini birleştirir.
"""
from __future__ import annotations

__all__ = [
    "funding_rate_ingest",
    "open_interest_ingest",
    "liquidation_proxy",
    "merge",
]
