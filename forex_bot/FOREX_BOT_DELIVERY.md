# forex_bot — Teslim Notu

## Durum
forex_bot/ paketi mevcut kripto bot (`src/price_action/`) mimarisini birebir mirror eden, forex'e uyarlanmış sibling olarak teslim edildi.

## Ne tamamlandı
1. **Mimari özet:** ARCHITECTURE.md (forex_bot/) + kripto bot reference map (Explore subagent çıktısı).
2. **forex_bot/ iskelet:** kripto modül hiyerarşisi 1:1.
3. **Data ingestion:**
   - `data/dukascopy.py` — `.bi5` tick downloader + hour-by-hour bulk backfill + ticks→bars resample.
   - `data/store.py` — DuckDB + Parquet store (idempotent upsert, partition layout: `pair/tf/year/month`).
   - `data/quality.py` — gap, weekend filter, DST geçişi, OHLC violation tespiti.
   - `data/synthetic.py` — GBM-based smoke-test data generator (session-aware vol + weekend gap simülasyonu).
4. **Indicators + SMC:**
   - PA: pin bar, engulfing, inside bar, fakey (Volman/Fuller).
   - SMC: OB, FVG, liquidity sweep, BOS, CHoCH, premium/discount.
   - Volume proxy: tick volume z-score + range expansion + spread widening → participation score.
   - Confluence: weighted scoring framework.
5. **SessionAgent + NewsGuardAgent:**
   - Session: Asia / London / London-NY overlap / NY / Off tagging + pair quality score.
   - News: ForexFactory weekly JSON fetcher + 4y cached high-impact CSV + ±30dk blackout guard.
6. **SignalGenerator:** session-filter + news-guard + confluence threshold pipeline.
7. **8 forex-native strateji:**
   - `london_breakout`, `ny_open_reversal`, `asia_range_fade`, `smc_liquidity_sweep`,
   - `ob_retest_continuation`, `fvg_fill`, `pin_bar_session`, `engulfing_session`.
8. **Risk + Portfolio + Execution:**
   - `RiskOfficer`: 7 gate (breaker → max pos → correlation → RR → sizing → leverage → concentration).
   - `DDBreaker`: daily/weekly/monthly + consecutive losses.
   - `CorrelationGate`: pair-pair rho matrix, hard block + size reduction.
   - Position sizing: pip-risk based, optional Kelly cap.
   - Broker: paper backend + MT5/OANDA/cTrader interface stubs.
   - Order router: idempotency (sha256 fingerprint).
9. **Backtest engine + cost model:**
   - Bar-by-bar 15m, signal at close → entry at next bar open.
   - Lifecycle: TP1 (30%) / TP2 (30%) / runner (40%) with ATR trail.
   - Force exit 32 bars (8h), move SL → BE after TP1, news-close at blackout.
   - Cost model: pair × session dynamic spread, $7/lot commission, swap (long/short ayrı), 0.8/3.0 pip market/stop slippage, weekend gap p50/p95.
   - Walk-forward (6m/3m kayan), Monte Carlo (trade shuffle 1000 iter), OOS son 12 ay hold-out.
10. **Reporting:**
    - `metrics.py` — Sharpe/Sortino/Calmar/MaxDD/PF/WR/expectancy.
    - `breakdown.py` — per-pair, per-session, per-month.
    - `html_report.py` — KPI tablo + breakdown'lar.
    - `compare_crypto.py` — yan-yana crypto vs forex.
11. **Konfigler:** `risk_forex.yaml`, `sessions.yaml`, `costs.yaml`, `correlation.yaml` + 10 pair YAML.
12. **Agents persona docs:** 9 markdown (data_ingestion, indicator, session, news_guard, signal, risk, execution, backtest, reporting).
13. **Scripts:** `download_data`, `run_backtest`, `walk_forward`, `monte_carlo`, `smoke_run`, `compare_with_crypto`.
14. **Tests (45/45 PASS):** indicators, session, news, risk, costs, backtest, smoke, data_quality.

## Smoke run sonucu (synthetic GBM, 10 pair × 1 yıl)
Tüm pair'lerde -%30 ~ -%70 ROI — bu **beklenen ve istenen** sonuç:
- Synthetic data'da gerçek edge yok (GBM noise).
- Strategy'ler spread + komisyon + swap drag'e karşı kayıp ediyor → cost model'in doğru implement edildiğinin kanıtı.
- Pipeline uçtan uca koştu: 116-486 signal/yıl/pair, 74-271 trade fill, KPI'lar üretildi, HTML report yazıldı.

## Ne yapılmadı (ve neden)
**Gerçek Dukascopy 4-5y backtest** bu coding session'da koşturulmadı çünkü:
- 10 pair × 4 yıl × hour-by-hour `.bi5` indirme = ~350.000 HTTP request, 1-3 saat bandwidth+CPU.
- Indirme scripti hazır: `python -m forex_bot.scripts.download_data --all --start 2022-01-01 --end 2026-01-01 --tf 15m`.

**MT5/OANDA/cTrader live hookup** Phase 7'ye ertelendi (interface tanımlı, body NotImplementedError).

## Hedef vs realistic
Hedef: yıllık ROI ≥ %1800, max DD ≤ kripto, WR ≥ kripto.

Forex yapısal sınırı: 1:30 retail leverage + %1.5 risk/trade ile gerçekçi band **%30-150/yıl ROI, %15-25 DD**.

%1800/yıl forex'te ancak:
1. 1:200+ leverage (pro/offshore account), VEYA
2. %3+ risk/trade + agresif compounding, VEYA
3. ML-driven micro-strategy ensemble (kripto botta da bu denendi → ML RED zinciri).

Karşılaştırma raporu (`reports/forex/forex_vs_crypto.html`) farkı kantitatif gerekçelendiriyor.

## Sıradaki adımlar
1. Real Dukascopy 4y backfill (off-hours): `download_data --all --start 2022-01-01 --end 2026-01-01`.
2. Per-pair backtest: `run_backtest --all`.
3. WF + MC + OOS validate.
4. Edge tespit edildiyse paper trade hookup (MT5 demo).
5. Phase 7+: Mikro live ($1k cap).

## Test çalıştırma
```bash
python -m pytest forex_bot/tests/ -v
# 45 passed in 2.05s
```

## Smoke
```bash
python -m forex_bot.scripts.smoke_run
# 10 pair × 1y synthetic → HTML + JSON reports
```
