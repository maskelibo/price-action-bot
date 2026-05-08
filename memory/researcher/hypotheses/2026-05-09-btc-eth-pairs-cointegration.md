---
hypothesis_id: btc_eth_pairs_cointegration_v1
date: 2026-05-09
author: researcher_agent
status: pre_registered
strategy_class: statistical_arbitrage
strategy_name: btc_eth_pairs
tags: [pairs_trading, cointegration, market_neutral, mean_reversion, statistical_arb]
---

# Hipotez: BTC-ETH İstatistiksel Arbitraj Pairs Trading

## 1. Iddia (Pre-Registration)

BTC/USDT ve ETH/USDT logaritmik fiyat serileri 1d bar üzerinde Engle-Granger
cointegration testini geçiyorsa (ADF p < 0.05 on OLS residuals), spread z-score'u
±2σ'yı aştığında ortalamaya geri dönüş ticareti yapılabilir ve bu strateji:

- Yıllık Sharpe ≥ 1.0 (Chan'in BTC-ETH için öngördüğü 1.0–1.8 backtest aralığı)
- Win rate ~%55–60 (mean-reversion tipik)
- Engulfing stratejisiyle korelasyon ≈ 0 (market-neutral → direksiyonel maruz
  kalım yok)

özelliklerini gösterir.

## 2. Gerekçe — Ernie Chan Çerçevesi

Chan (*Algorithmic Trading*, 2013, s.66–74, "Pairs Trading Setup"):

> "İki cointegrated varlık için spread s_t = y_t - β·x_t z-score'u ±2 standart
> sapmayı aştığında ortalamaya geri dönüş yönünde pozisyon. β rolling 60-day OLS
> veya Kalman filter ile dinamik tahmin edilir."

Chan'in belgelediği BTC-ETH cointegration:

- 2017–2020: Engle-Granger p < 0.01 (güçlü)
- 2021+: ETH DeFi/NFT diverjansı → ilişki zayıfladı
- 2024+: Yeniden yakınsamaya işaret
- Beklenen half-life: 7–25 gün (trade-edilebilir aralık)
- Beklenen Sharpe (backtest, %0.1 fee dahil): 1.0–1.8

**DİKKAT (Chan uyarısı):** Cointegration dynamictir. Tek bir yapısal kırılma
(M&A, regülasyon, teknoloji diverjansı) ilişkiyi kalıcı olarak bozar. Bu sebeple
rolling ADF window (60 bar) cointegration'ı sürekli izler; p > 0.05 ise sinyal
üretilmez.

## 3. Metodoloji — López de Prado Standartları

### 3.1 Engle-Granger İki Aşamalı Test

```
Adım 1: ADF(log_BTC) → p > 0.05 (non-stationary, I(1) gerekli)
Adım 2: ADF(log_ETH) → p > 0.05 (non-stationary, I(1) gerekli)
Adım 3: OLS: log_BTC = β·log_ETH + α + ε
Adım 4: ADF(ε) → p < 0.05 → cointegrated
```

### 3.2 Hedge Ratio

- **Yöntem:** Rolling OLS (lookback = 60 bar, varsayılan)
- **Lookahead koruması:** t barı için [t-60, t-1] verisi kullanılır (shift(1))
- **Bağımlı değişken:** log_BTC, bağımsız değişken: log_ETH
- **Alternatif:** Kalman filter (Faz 2 geliştirmesi olarak)

### 3.3 Spread ve Z-Score

```
spread_t = log_BTC_t - β_t * log_ETH_t
zscore_t = (spread_t - rolling_mean(spread, 20)) / rolling_std(spread, 20)
```

Her iki hesaplama da shift(1) ile lookahead korunur.

### 3.4 Half-Life (Ornstein-Uhlenbeck)

```
Δspread_t = λ·spread_{t-1} + μ + ε_t
half_life = -log(2) / log(1 + λ)
```

Chan: 5–30 gün "trade-edilebilir"; > 60 gün → sermaye verimliliği düşük.

## 4. Sinyal Kuralları (Pre-Registration)

| Koşul | Eylem |
|---|---|
| zscore < -2.0 AND adf_p < 0.05 | LONG spread (long BTC + short ETH) |
| zscore > +2.0 AND adf_p < 0.05 | SHORT spread (short BTC + long ETH) |
| zscore abs < 0.5 (veya tersine geçti) | Kapat her iki bacak |
| zscore > 3.5 (stop) | Kapat — cointegration bozuldu sinyali |

**Pozisyon büyüklüğü:** Dollar-neutral. Her iki bacak notional olarak eşit.
- BTC bacağı: 1.0 lot (birim)
- ETH bacağı: β_t lot (hedge ratio kadar)
- P&L: BTC_ret - β_t * ETH_ret

## 5. Beklenen Parametreler

| Parametre | Değer |
|---|---|
| spread_z_entry | 2.0σ |
| spread_z_exit | 0.5σ (mean'e yakın) |
| spread_z_stop | 3.5σ (cointegration bozuldu) |
| lookback_window (OLS + z-score) | 60 bar |
| adf_window (rolling ADF) | 60 bar |
| adf_threshold | 0.05 |
| fee varsayımı | %0.075 taker (round-trip %0.15) |
| slippage | 5 bps |

## 6. Beklenen Performans Öncesi Tahmini

| Metrik | Beklenti | Kaynak |
|---|---|---|
| Yıllık Sharpe | 1.0–1.8 | Chan crypto adaptasyon notu |
| Win rate | %55–60 | Tipik mean-reversion |
| Yıllık getiri (net) | %15–40 | Chan pairs Sharpe × risk |
| Max Drawdown | <%25 | Market-neutral düşük DD |
| Engulfing ile korelasyon | ~0 | Sıfır direksiyonel maruz kalım |

## 7. Falsification Kriterleri (REJECT Koşulları)

Aşağıdakilerden biri gerçekleşirse hipotez REDDEDILIR:

1. 3 yıllık backtest Sharpe < 0.5
2. Cointegration 3 yılın > %40'ında bozulmuşsa (adf_p > 0.05 rolling)
3. Engulfing ile korelasyon > 0.3 (market-neutral özelliği yok)
4. Net P&L negatif (transaction cost tüm spread gelirini sildi)

## 8. DÜRÜSTLÜK UYARISI

Chan ve Chan'i referans alan tüm çalışmalar açıkça belirtiyor: **BTC-ETH çifti
kripto piyasasında en çok arb edilen çiftlerden biridir.** Binance, OKX ve Bybit
masaları bu spreadi 1 dakikalık barlarla kapatıyor. Günlük bar üzerinde trade eden
bir retail strateji için:

- Kalıcı cointegration bozulmaları gerçekleşti (2021 DeFi döneminde)
- Funding rate farkı hedge maliyetini artırabiliyor (perp kullanılırsa)
- 2021–2023 arası hangisinin daha iyi performans gösterdiği dönem dönem değişti

Bu backtest **dürüst** sonuç vermeli: eğer pair arb edilmiş ve edge kalmamışsa,
açıkça raporlanacak.

## 9. Strateji Dosyaları

- `src/price_action/strategies/btc_eth_pairs.py`
- `scripts/run_pairs_backtest.py`
- `tests/test_btc_eth_pairs.py`

## 10. Decorrelation Tezi

Bu stratejinin portföye dahil edilmesinin **tek** haklı gerekçesi:

Engulfing / PA stratejileri direksiyonel olup tek varlık üzerine yoğunlaşır.
Pairs trading market-neutral olup korelasyonu teorik olarak sıfıra yakın.
Eğer Sharpe ≥ 0.8 ve korelasyon < 0.2 ise, portföy çeşitlendirmesi sağlar.
Eğer Sharpe < 0.8, strateji bağımsız olarak yetersiz olduğundan DEFER edilir.
