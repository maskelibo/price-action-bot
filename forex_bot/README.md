# forex_bot

Forex sibling of the `src/price_action/` crypto trading bot. Mirrors the same agent + module hierarchy, with forex-native adaptations.

## Highlights
- **10 majör/minör pair**: EURUSD, GBPUSD, USDJPY, AUDUSD, USDCAD, NZDUSD, USDCHF, EURJPY, GBPJPY, EURGBP
- **15m primary timeframe** with optional 1m intra-bar refinement
- **Dukascopy** primary data source (`.bi5` tick stream → 15m bars)
- **Session-aware signals**: Asia / London / London-NY overlap / NY tagging + per-pair session quality score
- **News guard**: ForexFactory high-impact event blackout window (±30dk)
- **Smart Money Concepts**: order blocks, FVG, liquidity sweeps, BOS, CHoCH, premium/discount
- **Volume proxy**: tick volume z-score + range expansion + spread widening → participation score
- **Realistic cost model**: pair × session dynamic spread, $7/lot commission, swap (long/short), market/stop slippage, weekend gap
- **Walk-forward** 6m/3m + **Monte Carlo** trade-shuffle + **OOS** last 12 months hold-out

## Klasör yapısı

```
forex_bot/
├── contracts.py                Signal, RiskedOrder, Fill, Position, TradeRecord
├── settings.py                 paths, PAIRS, timeframes
├── data/                       Dukascopy, DuckDB+Parquet store, quality, synthetic
├── indicators/                 OHLC, price action, SMC, volume proxy, confluence
├── session/                    tagger, volatility regime
├── news/                       calendar (ForexFactory + cached CSV), guard
├── signals/                    SignalGenerator (session+news filtered)
├── strategies/                 8 forex-native price action strategies
├── risk/                       sizing, breaker, correlation, RiskOfficer
├── portfolio/                  allocator
├── execution/                  broker_base, paper, MT5/OANDA/cTrader stubs, idempotency, router
├── backtest/                   engine, costs, walk_forward, monte_carlo
├── reporting/                  metrics, breakdown, html_report, compare_crypto
├── agents/                     persona docs (data_ingestion, signal, risk, ...)
├── configs/                    risk_forex.yaml, sessions.yaml, costs.yaml, correlation.yaml, pairs/*.yaml
├── scripts/                    download_data, run_backtest, walk_forward, monte_carlo, smoke_run, compare_with_crypto
└── tests/                      indicators, session, news, risk, costs, backtest, smoke
```

## Kurulum

```bash
# Mevcut repo'nun bağımlılıklarını kullanır (pandas, numpy, duckdb, pyyaml, requests).
pip install pandas numpy duckdb pyyaml requests
```

## 1) Data ingestion (Dukascopy 4-5 yıl)

```bash
# Tek pair
python -m forex_bot.scripts.download_data --pair EURUSD --start 2021-01-01 --end 2026-01-01 --tf 15m

# 10 pair toplu (saat saat çekim — uzun sürebilir, off-hours önerilir)
python -m forex_bot.scripts.download_data --all --start 2022-01-01 --end 2026-01-01 --tf 15m
```

Veri DuckDB'ye + Parquet partition'a yazılır: `data/forex/forex.duckdb`, `data/forex/parquet/{pair}/{tf}/year=YYYY/month=MM/data.parquet`.

## 2) Backtest

```bash
# Tek pair, gerçek data
python -m forex_bot.scripts.run_backtest --pair EURUSD --start 2022-01-01 --end 2026-01-01

# Hızlı smoke — synthetic data (bağımlılıksız)
python -m forex_bot.scripts.run_backtest --pair EURUSD --start 2024-01-01 --end 2025-01-01 --use-synthetic

# Tüm 10 pair
python -m forex_bot.scripts.run_backtest --all --start 2022-01-01 --end 2026-01-01
```

Çıktı: `reports/forex/forex_{pair}_{ts}.html` + `reports/forex/forex_all_kpis_{ts}.json`.

## 3) Walk-forward + Monte Carlo

```bash
python -m forex_bot.scripts.walk_forward --pair EURUSD --start 2022-01-01 --end 2026-01-01 --use-synthetic
python -m forex_bot.scripts.monte_carlo  --pair EURUSD --start 2022-01-01 --end 2026-01-01 --use-synthetic --iter 1000
```

## 4) Smoke test (no external deps)

```bash
python -m forex_bot.scripts.smoke_run
```

3 pair × 1 yıl synthetic OHLCV → tüm pipeline → HTML + JSON rapor.

## 5) Crypto vs Forex karşılaştırma

```bash
python -m forex_bot.scripts.compare_with_crypto \
    --forex-kpis reports/forex/forex_all_kpis_<ts>.json \
    --crypto-kpis reports/champion_kpis.json
```

## Performance hedefi & gerçeklik
Hedef: yıllık ROI ≥ kripto botu (≈%1800), max DD ≤ kripto, WR ≥ kripto.

**Forex'in yapısal sınırı**:
- Major spot pair'lerinin yıllık vol'u ≈ %5–12 (BTC ≈ %60–80).
- Aynı edge ile forex ROI yaklaşık 5–15× daha düşük.
- Spread + komisyon + swap drag, tipik hareket aralığında daha büyük yer kaplar.
- %1800/yıl forex'te ancak 1:200+ leverage (offshore pro) + %3 risk/trade + agresif compounding ile yaklaşılabilir.

**Retail tier 1:30, %1.5 risk/trade ile gerçekçi band**: %30–150/yıl ROI, %15–25 DD.

Hedef tutturulamıyorsa `scripts/compare_with_crypto.py` farkı kantitatif olarak raporlar.

## Live trading (Phase 7+)
Şu aşamada **paper-only**. `execution/{mt5,oanda,ctrader}_iface.py` interface'leri tanımlı; gerçek hookup `MetaTrader5`, `oandapyV20`, `cTrader Open API` paketleri ile Phase 7 sonrasında.

## Testler

```bash
python -m pytest forex_bot/tests/ -v
```

## Faz gate'leri
| Faz | Gate | Eşik |
|---|---|---|
| 0 | Veri kalitesi | Eksik mum < %0.5 |
| 1 | Unit test | Coverage ≥ %85 |
| 2 | 3y backtest | ROI ≥ %500 OR honest postmortem |
| 3 | Walk-forward | %70+ pencere pozitif |
| 4 | Monte Carlo | P5 ROI > 0 |
| 5 | OOS son 12 ay | Sharpe drop ≤ %25 |
| 6 | Paper 4 hafta | P&L sapma < %30 |
| 7 | Mikro live | Manuel onay sonrası |
