---
type: facts
topic: exchange_behaviors
last_updated: 2026-05-08
confidence: high
---

# Borsa Davranışları — Pratik Notlar

## Binance
- Rate limit: 1200 weight/dk REST; WebSocket bağlantı başına ayrı limit.
- 429: Exponential backoff zorunlu; 418 (IP ban) → 2-30 dk arası ban.
- Kline endpoint maximum 1500 bar/istek.
- Funding rate `/fapi/v1/fundingRate` (history).
- Testnet adresleri ayrı: `testnet.binancefuture.com`, `testnet.binance.vision`.

## Bybit
- v5 unified API artık standart.
- Rate limit endpoint başına; account başına dakikada ~600 request.
- Testnet: `api-testnet.bybit.com`.

## ccxt
- `unified API` çoğu işi gizler ama tüm exchange'ler tüm metodları desteklemez.
- `fetch_ohlcv` paginate elle yapılmalı (default 500 bar).
- `enableRateLimit: True` her zaman.
- WebSocket için `ccxt.pro` ayrı paket, lisanslı.

## Order Book
- Top 5 BTC pair'leri için ±%1 depth genelde 5-50M USDT.
- Alt coinlerde ±%1 depth 100k-2M USDT — slippage hızla artıyor.

## Slippage Empirik
- BTC market emir 50k USDT: 1-3 bps slippage.
- Top 30 alt coin market emir 50k USDT: 5-15 bps.
- Top 100 alt coin market emir 50k USDT: 15-50 bps.
- Bu sayılar sakin piyasa için; volatilite ×3'te slippage ×2-4.

## Maintenance / Outage
- Binance haftada 1-2 kez kısa maintenance (5-15 dk).
- Bybit ayda ortalama 1 büyük maintenance.
- Major event'lerde (FTX iflası, USDC depeg) WS koparmalar yaşandı.

> Periyodik gözlem; Ops dept güncel tutar.
