---
hypothesis_id: H22
title: "Stablecoin Supply Growth as Crypto Liquidity Proxy"
created: 2026-05-09
author: researcher
status: TESTING
tags: [stablecoin, liquidity, macro, filter, usdt, usdc, capital_flows, btc, alts, daily]
---

# H22 — Stablecoin Supply Growth as Crypto Liquidity Proxy

## Hipotez Özeti

**Ana tez:** USDT + USDC toplam piyasa değerinin 30 günlük büyümesi, kripto piyasasına giren/çıkan "kuru toz" (dry powder) miktarını ölçer. Stable coin arzı büyüyorsa yeni fiat sermayesi sisteme giriyor demektir; stable supply'ı düşüyorsa (redemption) sermaye çıkıyor demektir.

**Filtre tezi:** Engulfing LONG sinyali sadece stablecoin arzı 30 günde büyümüş iken al. Sermaye yoksa alım fırsatı dahi olsa baskı yetersiz kalır.

```
stable_growth_30d = (supply_today - supply_30d_ago) / supply_30d_ago
LONG filtre geç: stable_growth_30d[t-1] > 0
SHORT filtre geç: her zaman (stable supply düşüşü bearish ama short için spesifik eşik araştırılacak)
```

## Yapısal Farklılık (H1-H21'den ayrışma)

| Kategori          | Önceki Hipotezler               | H22                    |
|-------------------|---------------------------------|------------------------|
| Price Action      | Pin bar, engulfing, pullback    | —                      |
| Volatilite        | Vol risk premium, ATR           | —                      |
| On-chain          | MVRV, NUPL, exchange flow       | —                      |
| Order Book        | Perp imbalance, funding rate    | —                      |
| Retail Sentiment  | F&G Index                       | —                      |
| **Makro Likidite** | —                              | **Stablecoin supply**  |

Stablecoin supply, fiyat verisinden ve retail psikolojisinden tamamen bağımsız bir makro likidite göstergesidir. MVRV veya F&G ile korelasyonu düşük olması beklenir — bu da bileşik filtre gücünü artırır.

## Akademik / Piyasa Zemini

### Sermaye Akışı Teorisi
Kripto piyasası, stable coin'leri hazır nakit rezervi olarak kullanır. Bir kurum USDT mint ettiğinde (= Tether'a fiat gönderdiğinde), bu rezerv BTC/altcoin almak için bekler. Toplu mint = bullish potansiyel. Toplu redemption = satış veya risk-off.

### Glassnode Dashboards Riski (HONEST assessment)
Stablecoin supply growth, Glassnode ve CryptoQuant gibi platformlarda yaygın biçimde takip edilir:
- Glassnode: "Stablecoin Supply Ratio" (SSR) — market cap / stable supply
- CryptoQuant: "Stablecoin Supply Ratio Oscillator"
- CoinGlass, Nansen, vb. platformlarda public dashboardlar mevcut

**Bu bilginin yaygın olması şu soruyu doğurur:**
Eğer tüm profesyonel kullanıcılar bu veriyi izliyorsa, bu sinyal zaten fiyata dahil olmuş mudur?

**Counter-argüman:** Makro likidite değişimleri yavaş (haftalar-aylar); anlık arbitraj zor. Stablecoin büyümesi öncü gösterge gibi davranabilir, ancak öncülük süresi net değil. Test sonucuna bırakılmış kritik soru.

### Tether Karşı Taraf Riski
USDT, Tether'ın borcudur. 2021-2022'deki attests şüpheleri ve USDC'nin SVB bank run'ı (Mart 2023) gibi spesifik olaylar supply'ı fiyattan bağımsız etkiledi. Bu outlier dönemlerin backtest'i kirletme riski var.

### USDT+USDC vs. Tüm Stablecoin Evreni
BUSD kapatıldı (2023). FRAX, TUSD, USDP gibi küçük stablelar gürültü ekler. USDT+USDC = piyasa payı %80-85. Temiz signal için ikili toplam yeterli.

## Test Planı

### Senaryo 1 — Engulfing Solo (Baseline)
Engulfing continuation, filtre yok.

### Senaryo 2 — Engulfing + F&G Filter
H18'den gelen mevcut sonuç (F&G < 60 for longs).

### Senaryo 3 — Engulfing + F&G + BTC.D Filter
H20 veya mevcut compound filter (BTC dominance sinyali varsa).

### Senaryo 4 — Engulfing + F&G + BTC.D + Stable Supply Filter
Stable growth[t-1] > 0 ek koşulu. Compound layered test.

**Kaldıraç hipotezi:** Her katman bağımsızsa ve gerçek sinyal taşıyorsa, compound win rate lineer'den fazla artmalı (synergistic filtering).

## Başarı Kriterleri (Gate Eşikleri)

| Kriter            | Solo Baseline | F&G Filter | Compound (F&G+Stable) |
|-------------------|---------------|------------|-----------------------|
| Win Rate          | ref           | +%3 min    | +%5 min               |
| Sharpe            | ref           | +%10       | +%15                  |
| Max Drawdown      | ref           | ≤ ref +2%  | ≤ ref +3%             |
| Trade Sayısı      | ref           | ≥ 30% ref  | ≥ 25% ref             |

**PROMOTE eşiği:** Compound (Senaryo 4) win rate ≥ Baseline + 5pp VE trade sayısı ≥ Baseline × 0.3.

**REJECT eşiği:** Compound win rate < Baseline + 2pp VEYA trade sayısı < Baseline × 0.2 (sinyal kuruluğu).

## Veri Kaynağı

```
USDT: https://api.coingecko.com/api/v3/coins/tether/market_chart?vs_currency=usd&days=1095
USDC: https://api.coingecko.com/api/v3/coins/usd-coin/market_chart?vs_currency=usd&days=1095
```
- `market_caps` array: `[[timestamp_ms, market_cap_usd], ...]`
- Ücretsiz, API key gerektirmez, 30 req/min limit
- 3 yıl geçmiş (~1095 gün)
- Daily normalize edilecek (birden fazla nokta varsa son gün değeri)

## SVBEK Dönem Riski

Mart 2023: USDC depeg olayı (SVB iflas). USDC supply hızla düştü ama bu BTC fiyat düşüşüyle eş zamanlı değildi. Bu dönem false negative üretebilir.

Mayıs 2022: LUNA/UST çöküşü. Stablecoin supply büyük dalgalanma. Bu dönem ekstra noise ekler.

Olası çözüm: Bu spesifik outlier dönemler için flag ekleyip sensitivity test.

## Referanslar

- CoinGecko Free API: https://api.coingecko.com/api/v3/
- Glassnode Stablecoin Supply Ratio: https://glassnode.com/metrics/stablecoins/supply-ratio
- CryptoQuant Stablecoin Supply: https://cryptoquant.com/asset/usdt/chart/market-data/stablecoin-supply
- Tether Transparency: https://tether.to/en/transparency/
- Circle Reserve Reports: https://www.circle.com/en/transparency
- Wilkins & Zelmer (2019) "Liquidity in financial markets" — general liquidity proxy theory
