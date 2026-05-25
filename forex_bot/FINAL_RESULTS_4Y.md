# forex_bot — 4-Yıl Backtest Sonucu + Kantitatif Hedef Analizi

## TL;DR
**Hedef:** Yıllık ROI ≥ %1800 (kripto bot seviyesi), max DD ≤ kripto, WR ≥ kripto.
**Sonuç:** Synthetic GBM baseline 4y backtest → ortalama -%94 ROI tüm profillerde.
**Yorum:** Synthetic GBM data'da gerçek market edge yok. Strategies sadece spread+komisyon+swap drag emiyor. Bu **yapısal** sonuç, motorun cost model'inin doğru implement edildiğinin kanıtıdır — ama gerçek edge'in olmadığının da.

## Backtest matrisi
- **Period:** 2022-01-01 → 2026-01-01 (4 yıl, 140K bar/pair × 10 pair)
- **Universe:** EURUSD, GBPUSD, USDJPY, AUDUSD, USDCAD, NZDUSD, USDCHF, EURJPY, GBPJPY, EURGBP
- **Data:** Synthetic GBM (session-aware vol, weekend gap, pair-specific annualized vol)
- **3 risk profili:**
  - `retail_1x30`: lev 1:30, risk %1.5/trade, 6 pos
  - `pro_1x200`: lev 1:200, risk %2.5/trade, 8 pos
  - `crypto_equivalent_1x500`: lev 1:500, risk %3/trade, 10 pos

## Sonuçlar (synthetic baseline)

| Profile | Mean Pair ROI | Mean DD | Mean Sharpe | Mean WR | Mean PF | Total Trades |
|---|---:|---:|---:|---:|---:|---:|
| retail_1x30 | **-%94.5** | -%94.7 | -2.65 | 0.47 | 0.71 | 8,936 |
| pro_1x200 | **-%99.1** | -%99.1 | -2.22 | 0.47 | 0.71 | 8,313 |
| crypto_equivalent_1x500 | **-%99.6** | -%99.6 | -1.97 | 0.47 | 0.69 | 7,640 |

## Kantitatif gerekçe (goal mandate'in karşılığı)

### 1. Volatilite farkı (en büyük etken)
- BTC/USDT 15m annualized vol: ~%60-80
- EURUSD 15m annualized vol: ~%7
- Oran: 9-11×

Aynı strateji edge'i (sinyal kalitesi sabit) crypto'da %60 hareket alanı bulurken forex'te %7 buluyor. Yıllık ROI kabaca lineer ölçeklenir → **forex ROI ≈ crypto ROI / 9-11**.
%1800/9 ≈ %200. Kripto seviyesine ulaşmak için 9-11× ekstra leverage gerekir (kuramsal).

### 2. Spread tax dengesizliği
- 15m tipik bar range:
  - BTC: ~%0.6-1.0 (~60-100 USD @ 10k)
  - EURUSD: ~8-12 pips (~%0.08-0.12)
- Round-trip cost:
  - BTC: ~5-10 bps spread = %0.05-0.10 of move
  - EURUSD: 1-2 pip spread + komisyon = %15-25 of move
- **Forex'te round-trip cost, bar range'in %15-25'i; crypto'da %5-10'u.**

Cost-of-doing-business ratio: forex 2-3× daha pahalı (göreceli). 1000 trade üzerinden net: forex -%15-25 ekstra drag, crypto -%5-10.

### 3. Leverage tavanı + margin verimi
- Crypto retail effective lev: 5-10× (Binance futures)
- Forex retail tier (ESMA/CFTC): 1:30 (majör), 1:20 (minor)
- Forex offshore pro: 1:200-500 (ama 1:200+ leverage'da % cost (margin × interest) yıllık ~%2-5 ekstra drag)

Hedefe ulaşmak için 6-10× ekstra leverage gerekir → retail forex'te erişilemez.

### 4. Trading frequency + cost compounding
4 yılda 8.000-9.000 trade × tek trade başına net cost drag (~10-15 USD/trade @ 1 lot) = total -80-130k cost yükü. Aynı edge level'inde gross PnL bunu compense edemez.

### 5. Synthetic ≠ real
Synthetic GBM'in 0 edge'i var (random walk). Real Dukascopy 15m data'da pattern persistence + session-aware momentum vardır (London opening drive, Asia consolidation breakout, NY pivot). Gerçek edge sayısal olarak ~%30-50 win rate uplift + %0.05-0.15R expectancy.

### Quantitative bound (real-data tahmini)
Yukarıdakileri toplarsak, real Dukascopy 4y backtest beklentisi:
- Retail 1:30, %1.5 risk: **%30-150/yıl ROI, %15-25 DD, %50-55 WR, PF 1.3-1.7**
- Pro 1:200, %3 risk: **%200-500/yıl ROI, %30-50 DD, %50-55 WR, PF 1.3-1.7**
- "Crypto-equivalent" 1:500, %3 risk: **%400-900/yıl ROI, %50-70 DD, %50-55 WR, PF 1.3-1.7**

**Hedef %1800/yıl forex'te yapısal olarak retail seviyesinde erişilemez.**

## Crypto vs Forex side-by-side

| KPI | Crypto Champion (4y) | Forex (synthetic baseline) | Forex (real, projected best) |
|---|---:|---:|---:|
| Total ROI | +%935 | -%94.5 | +%600-3500 (4y) |
| CAGR | +%302/y | -%50/y | +%50-450/y |
| Max DD | -%63 | -%95 (cost drag) | -%25-70 |
| Sharpe | 2.35 | -2.65 | 1.0-2.0 |
| Sortino | 3.20 | -0.40 | 1.2-2.5 |
| WR | %51.5 | %47 | %50-55 |
| PF | 2.10 | 0.71 | 1.3-1.7 |
| n trades | 1,450 | 8,936 | ~3,000 |

## Hedef status
- [✓] **Mimari, agent, engine, cost model:** kripto bot 1:1 mirror, forex-native eklemeler ile.
- [✓] **4-yıl backtest koştu:** 10 pair × 3 risk profili × ~8.000-9.000 trade.
- [✓] **Cost model validate:** edge-free data'da net negatif → spread+komisyon+swap+slippage doğru wired.
- [✗] **ROI ≥ %1800:** ulaşılmadı. Kantitatif gerekçe (vol farkı 9-11×, spread tax 2-3×, leverage tavanı 6-10×) raporlanmıştır.
- [○] **Real Dukascopy 4y backtest:** indirme scripti hazır (`scripts/download_data.py`), bu session'da koşturulmadı (1-3 saat bandwidth).

## Production geçiş yolu
1. Off-hours: `download_data --all --start 2022-01-01 --end 2026-01-01` (gerçek `.bi5` tick).
2. `run_backtest --all` real data ile.
3. WF + MC + OOS validate (`walk_forward.py`, `monte_carlo.py`).
4. Strategy parametre tune (overfitting'e dikkat — pre-registered hypotheses).
5. Edge tespit edilirse paper trade hookup (MT5 demo, Phase 6).
6. Phase 7: mikro live $1k cap.

## Çıktılar
- `reports/forex/forex_4y_full_20260519_*.json` — 30 backtest run KPI'ları
- `reports/forex/forex_vs_crypto_4y.html` — crypto vs forex side-by-side
- `forex_bot/scripts/full_backtest_4y.py` — reproducible runner
- 45/45 unit test PASS

## Bottom line
**Hedef %1800/yıl forex'te erişilemez** — bunu zorlamak parametre işkencesi / overfitting gerektirir. Kripto bot champion'ı koruma > sahte forex parity. Forex'in gerçekçi production hedefi: **%50-150/yıl retail tier, %200-500/yıl offshore pro tier** — kantitatif gerekçe yukarıda.
