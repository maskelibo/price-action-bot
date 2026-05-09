---
hypothesis_id: H18
title: "Crypto Fear & Greed Index — Retail Sentiment Edge"
created: 2026-05-09
author: researcher
status: TESTING
tags: [sentiment, mean_reversion, filter, retail_psychology, btc, daily]
---

# H18 — Crypto Fear & Greed Index as Sentiment Edge

## Hipotez Özeti

**Ana tez:** Alternative.me Crypto Fear & Greed Index (F&G), piyasanın retail sentiment'ini özetleyen bir kompozit göstergedir (sosyal medya, volatilite, momentum, dominance, surveys). Aşırı korku (F&G < 20) → satış panik dönemi → istatistiksel olarak alım fırsatı; aşırı açgözlülük (F&G > 80) → dağıtım dönemi → istatistiksel olarak short fırsatı.

**İkinci tez (filtre):** Mevcut engulfing continuation stratejisi, F&G filtresiyle sinyalinin kalitesini artırabilir. Teori: engulfing long sinyali "trend içi pullback" yakalıyor; F&G < 60 koşulunu eklemek "greed zirvesinde trend içi teknik sinyal → erken exit" senaryosunu eliyor.

## Yapısal Farklılık (H1-H17'den ayrışma)

| Kategori | Önceki Hipotezler | H18 |
|---|---|---|
| Price Action | Pin bar, engulfing, pullback | - |
| Volatilite | Vol risk premium, ATR | - |
| On-chain | MVRV, NUPL, exchange flow | - |
| Order Book | Perp imbalance, funding rate | - |
| **Retail Sentiment** | - | **F&G Index** |

F&G, price + volume'dan tamamen bağımsız bir veri kaynağıdır. Bu, gerçek bir diversification potansiyeli taşır.

## Akademik Zemin

### Grimes perspektifi
Grimes kitabında trader psychology bölümünde şunları söyler:
- Recency bias → son 5 trade kaybı → pozisyon küçülme veya setup kaçırma
- Loss aversion → 2x stronger than gain feeling
- "Climax bar" konsepti: ATR'ye göre 2-3 sigma dışında patlayıcı bar + sonrası mean-reversion

F&G bu psikolojik döngülerin agregasyonudur. Aşırı korku = maksimum satış baskısı + stop-out cascade = potansiyel çift-dip veya karşı-hamle; aşırı açgözlülük = FOMO alımları + leverage birikimi = dağıtım zemini.

### Harris perspektifi (market microstructure)
Harris'in "trader taxonomy" çerçevesinden: F&G düşükken "liquidity traders" (gamblers + hedgers) dominant; F&G yüksekken "sentiment traders" ve "asset allocators" dominant. Bu değişim, adverse selection dinamiğini değiştiriyor:

- F&G < 20: Düşük kaliteli informed flow; market maker'lar koruyucu spread genişletir → informed buy order volume artar → reversal edge.
- F&G > 80: Momentum chasers dominant; büyük dağıtım emirleri iceberg olarak çalışıyor → reversal hazırlık.

### Behavioral Finance Zemini
- Thaler & Sunstein: "Predictable irrationality" — retail yatırımcıların sistematik hata kalıpları.
- DeBondt & Thaler (1985): Aşırı tepki hipotezi — extreme performers revert → F&G bunun sentiment proxy'si.
- Baker & Wurgler (2006): Sentiment index anomaly — yüksek sentiment → sonraki dönem düşük getiri.

## Risk Faktörleri

### F&G arbitrajlanmış mı?
**Kritik soru:** F&G index widely tracked (coinmarketcap, trading terminalleri, Twitter/X). Eğer tüm retail F&G'yi izliyorsa ve ona göre hareket ediyorsa, bu hareket zaten fiyata dahil olmuş olabilir.

**Counter-argüman:** Retail yatırımcılar F&G'yi biliyor ama DAVRANMAYI değiştirmiyor (behavioral persistence). Korku döneminde "alın!" denir ama korku düşmeden gerçekten almak zordur. Bu irrasyonellik sürekliyse, arbitraj fırsatı devam eder.

**Test tasarımı:** 2018-2026 arasında edge'in yıl bazında azalıyor mu kontrol edilecek. Eğer 2018-2022'de güçlü, 2022-2026'da zayıfsa → arbitrajlanma kanıtı.

### Lookahead Riski
F&G, günün fiyat + sosyal verilerinden hesaplanır. Bugünün F&G'yi bugünün sinyalinde kullanmak kesinlikle lookahead'dir. Kural: shift(1) zorunlu — dün kapanışta bilinen F&G, bugün sinyal üretmek için kullanılır.

### Veri Kalitesi Riski
Alternative.me API ücretsiz ve informal. 2018 öncesi veri düşük kaliteli olabilir. Backtest dönemini 2018+ ile sınırlandırılacak.

## Test Planı

### Senaryo 1 — F&G Standalone
- Evren: BTC/USDT 1d, 2018-2026 (~3y dönemi için)
- LONG: F&G[t-1] < 25 AND close[t] > close[t-1] (momentumu teyit et)
- SHORT: F&G[t-1] > 75 AND close[t] < close[t-1]
- Exit: F&G 40-60 neutral zone'a girdiğinde
- SL: 10-bar swing low/high + 1 ATR
- TP: 2R primary

### Senaryo 2 — Engulfing + F&G Filtre
- Engulfing LONG sinyali sadece F&G[t-1] < 60 iken aktif
- Engulfing SHORT sinyali sadece F&G[t-1] > 40 iken aktif
- Teori: greed zirvelerinde trend içi engulfing false positive olabilir

### Senaryo 3 — Karşılaştırma Baseline
- Engulfing solo (yıllık +%68 baseline, H4 sonucu)

## Başarı Kriterleri (Gate Eşikleri)

| Kriter | F&G Standalone | F&G Filter |
|---|---|---|
| Yıllık getiri | > %20 | Baseline ±%10 |
| Sharpe | > 0.6 | Baseline +%10 |
| Max Drawdown | < %35 | Baseline ≤ %5 fark |
| Win Rate | > %45 | Baseline +%3 |
| Trade Sayısı | ≥ 30 | Değişim analizi |

## Veri Kaynağı

```
https://api.alternative.me/fng/?limit=2000
```
- JSON format, daily, tarihsel (2018+)
- Skor 0-100, sınıflandırma: Extreme Fear / Fear / Neutral / Greed / Extreme Greed
- Ücretsiz, rate-limit yok (reasonable kullanım)

## Referanslar

- Alternative.me Crypto Fear & Greed Index: https://alternative.me/crypto/fear-and-greed-index/
- Baker & Wurgler (2006) "Investor Sentiment and the Cross-Section of Stock Returns"
- DeBondt & Thaler (1985) "Does the Stock Market Overreact?"
- Grimes (2012) "The Art and Science of Technical Analysis" — psychology bölümü
- Harris (2003) "Trading and Exchanges" — trader taxonomy
