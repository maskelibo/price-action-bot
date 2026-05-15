# Data Engineer Learning — 2026-05-14 Alt-Data Pipeline (SEC25 Track C)

## Yapılanlar

- `src/price_action/data/alt_data/` Python paketi oluşturuldu (4 modül + `__init__.py`).
- `src/price_action/data/alt_data/funding_rate_ingest.py` — Dedicated `FundingRateStore`
  (funding_rates.duckdb, market.duckdb'den bağımsız). 11 sym × 5y backfill.
  anomaly_flag kolonu: |funding_rate| > 1% per 8h → True (ham veri korunur).
- `src/price_action/data/alt_data/open_interest_ingest.py` — `OIStore` (open_interest.duckdb).
  Primary: Bybit v5 (200-bar/page, paginated). Fallback: Binance (~30d).
  Hard limit tespit: **5y OI ücretsiz API ile mevcut değil** (Bybit ~2021'e iner).
- `src/price_action/data/alt_data/liquidation_proxy.py` — OHLCV+ATR+volume_z proxy.
  DB gerektirmez. `liq_proxy_long`, `liq_proxy_short`, `liq_proxy_score` kolonları.
- `src/price_action/data/alt_data/merge.py` — LEFT JOIN merge helpers.
  `merge_all_alt_data(ohlcv_df, symbol)` → tek çağrıda tüm alt-data eklenir.
- `scripts/sec25_alt_data_ingest.py` — CLI runner (--mode funding/oi/quality/all).

## Mevcut Veri (SEC25 öncesi)

| Dataset | Dosya | Satır | Tarih Aralığı | Not |
|---|---|---|---|---|
| BTC Funding (8h CSV) | data/alt_data/funding_BTCUSDT.csv | 5476 | 2021-05-13 → 2026-05-12 | BTC only |
| F&G daily | data/alt_data/fng_daily.csv | 2001 | 2020-11-19 → 2026-05-12 | 1 gap |

SEC25 sonrası hedef: funding_rates.duckdb (11 sym) + open_interest.duckdb (11 sym, max free depth).

## API Limit Gerçeği (surface don't hide)

| Kaynak | Endpoint | Ücretsiz Limit | 5y Backfill |
|---|---|---|---|
| Binance Funding | /fapi/v1/fundingRate | 1000/call, tam geçmiş | MÜMKÜN (2019+) |
| Bybit OI | /v5/market/open-interest | 200 bar/call (paginate) | KISMI (~2021'e kadar) |
| Binance OI | /futures/data/openInterestHist (1d) | ~30 bar | HAYIR |
| CoinGlass OI | paid | $29+/ay | MÜMKÜN (3y+) |
| BTC forceOrders | deprecated | HTTP 400 | YOK |
| OKX liquidations | REST | 48h | HAYIR |

## 4 Strateji Reaktive Durumu

| Strateji | Bağımlılık | Durum |
|---|---|---|
| funding_mean_reversion | funding_rate_lag1 (8h) | HAZIR — FundingRateStore + merge_funding_to_ohlcv_1d() |
| liquidation_fade | oi_pct_change + taker_sell_ratio | OI HAZIR; taker_sell_ratio 30d limit (proxy ile aşılabilir) |
| btc_eth_pairs | btc_close + eth_close (OHLCV) | HAZIR — alt-data gerekmez |
| onchain_signals | CapMVRVCur + nupl_proxy | HAZIR — CoinMetrics Community API, on-demand |

## Hard Limits Uyumu
- [x] No forward-fill (NaN bırakılır, downstream karar)
- [x] No clip/winsorize (anomaly_flag ile işaret)
- [x] UTC consistent (tüm ts TIMESTAMP WITH TIME ZONE)
- [x] Idempotent upsert (aynı run = aynı satır sayısı)
- [x] Fail loud (her iki kaynak boşsa exception, sessiz NaN yok)
- [x] Survivorship: hiçbir sembol silinmez, delisting_date ile etiket

## Sonraki Adım
`python scripts/sec25_alt_data_ingest.py` çalıştırıldığında:
1. data/funding_rates.duckdb → 11 sym × 5y (~49,000 satır hedef)
2. data/open_interest.duckdb → 11 sym × max free (~2021+ Bybit)
3. data/quality/YYYY-MM-DD_alt_data.json manifest yazılır
