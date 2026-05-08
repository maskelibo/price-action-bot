---
hypothesis_id: avwap_poc_reversal_v1
created: 2026-05-08
author: researcher_agent
status: pre-registered
strategy_file: src/price_action/strategies/anchored_vwap_reversal.py
---

# Hipotez: Anchored VWAP + Volume Profile POC Reversal

## 1. Iddia (Claim)

Kurum-agirlikli fiyat seviyeleri olan Anchored VWAP (HTF swing anchor'larından
hesaplanan) ile Volume Profile'ın Point of Control (POC) seviyesi birbirine yakın
olduğunda, fiyat bu çift-confluenced bölgeye geri döndüğünde ortalamaya-dönüş
(mean-reversion) sinyali yeterli istatistiksel edge taşır; bu edge mevcut
engulfing_continuation trend-following stratejisiyle düşük korelasyon gösterir
ve portföy olarak birleştirildiğinde risk-adjusted return'ü artırır.

## 2. Gerekçe (Rationale)

### 2a. Harris (Microstructure) perspektifi

Larry Harris'in "Trading and Exchanges" (Bölüm: Informed Traders) çerçevesinde:

- **AVWAP kurumsal referans noktasıdır.** Büyük kurumsal algoritmalar (VWAP,
  TWAP execution sistemleri) pozisyonlarını belirli anchor noktalarından
  hesaplanan VWAP etrafında ölçer. Fiyat bu VWAP'ın altına/üstüne düştüğünde
  kurumsal "rebalance" flow tetiklenir — bu, micro-structure açısından AVWAP'ı
  bir "tekrar ziyaret edilme magneti" yapar.

- **POC, en yüksek-volume fiyat seviyesidir.** Harris'in "informed traders
  absorpsiyon" kavramıyla POC arasında doğrudan bağlantı vardır: en çok işlem
  gerçekleşen fiyat, en çok iki-yönlü absorpsiyonun yaşandığı noktadır.
  Fiyat bu noktanın uzağına gittiğinde, kısa vadede POC'a dönüş baskısı
  istatistiksel olarak yüksektir (value area gravity).

- **Confluence etkisi:** AVWAP ile POC tek ATR tolerans içinde örtüştüğünde
  ikili kurumsal referans noktası oluşur. Harris'in adverse selection modeline
  göre bu seviyelerde gerçek alıcılar/satıcılar (value traders) bulunur;
  momentum/noise trader'ların aksine gerçek value flow reversal yaratır.

### 2b. Kaufman (Adaptive Systems) perspektifi

Kaufman "Trading Systems and Methods" kitabında:

- **Mean-reversion imzası** (Bölüm: System Taxonomy): Win rate %60-75,
  R-multiple 0.5-1.0, Sharpe 1.0-2.0, trade duration 1-10 bar. AVWAP
  reversal bu kategoriye düşer — engulfing_continuation trend-following
  imzasıyla (win rate %30-40, R 2.5-4.0) istatistiksel olarak
  tamamlayıcıdır.

- **Regime-awareness zorunluluğu (Bölüm: Efficiency Ratio):** Kaufman,
  mean-reversion sistemlerinin trending rejimde "catastrophic" çalıştığını
  belirtir. Bu nedenle 200-EMA bias filtresi ve Kaufman Efficiency Ratio (ER)
  filtresi AVWAP sistemine entegre edilmeli; ER < 0.35 (range/choppy rejim)
  koşulunda sistem aktif kalmalı.

- **Decorrelation değeri (Bölüm: Portfolio-Level Diversification):** Kaufman
  rolling 60-day correlation'ın |ρ| > 0.7 olduğu iki sistemin birlikte
  portfolio'da gereksiz olduğunu savunur. Trend-following + mean-reversion
  çifti yapısal düşük korelasyon sağlar — özellikle range-bound kripto
  piyasalarında.

### 2c. VWAP Formülü (Wikipedia kaynaklı)

Standart VWAP formülü:

```
VWAP_t = Σ(P_j × Q_j) / Σ Q_j
```

Burada P_j = işlem fiyatı, Q_j = işlem miktarı. Anchored VWAP (AVWAP),
bu toplamı sabit bir anchor bar'dan başlatarak hesaplar:

```
AVWAP_{t, anchor} = Σ_{i=anchor}^{t} (typical_price_i × volume_i) / Σ_{i=anchor}^{t} volume_i
typical_price_i = (high_i + low_i + close_i) / 3
```

POC (Point of Control) — volume profile ile:

```
price_buckets = linspace(min_low, max_high, n_buckets=50)
bucket_volume[k] = Σ volume_i for all bars i where low_i <= price_buckets[k] <= high_i
POC = price_buckets[argmax(bucket_volume)]
```

## 3. Test Edilebilir Kurallar (Falsifiable Rules)

### 3a. Uzun (Long) giriş koşulları

1. **200-EMA üzeri bias:** `close > ema200` (uzun vadeli trend yukarı)
2. **Swing-low anchored AVWAP mevcut:** Son 60 bar içindeki en düşük `swing_low`
   noktasından AVWAP hesaplanmış
3. **Fiyat AVWAP'ın altına düşüp yukarı dönüyor:** `close_prev < avwap AND close >= avwap`
   (AVWAP'ı aşağıdan yukarıya geçiş / "body rejection")
4. **POC yakınlığı:** `abs(close - poc) <= 1.5 * ATR14`
   (POC tek ATR içinde)
5. **RSI exhaustion (opsiyonel filtre):** `rsi14 < 50` (oversold/neutral bölge)
6. **Kaufman ER < 0.35** VEYA filtre devre dışı (range rejim tercihli ama zorunlu değil)

### 3b. Kısa (Short) giriş koşulları

Simetrik — `close < ema200`, swing-high anchor AVWAP, AVWAP'ı yukarıdan aşağıya
kırılış, POC yakınlığı, RSI > 50.

### 3c. Stop-Loss kuralı

- Long: `sl = recent_swing_low_10bar - 1.0 * ATR14`
  (yapısal stop — AVWAP'a pullback'in anlamı bozuldu)
- Short: `sl = recent_swing_high_10bar + 1.0 * ATR14`

### 3d. Take-Profit kuralı

- Primary TP: 2R (risk × 2.0)
- Logic: AVWAP mean-reversion 1-5 bar içinde tamamlanır; 2R sabiti bu
  dinamiğe uyum sağlar.

### 3e. Pozisyon büyüklüğü

- `risk_per_trade = 1% of equity`
- `notional = (equity × 0.01) / (sl_distance / entry)`

## 4. Gates (Promotion Koşulları)

Pre-registered gate'ler — bu eşikleri geçmeyen sistem reddedilir:

| Metrik                      | Eşik        | Yön    |
|-----------------------------|-------------|--------|
| Sharpe (standalone)         | > 0.8       | >=     |
| MaxDD (standalone)          | < 35%       | <=     |
| Win rate                    | > 50%       | >=     |
| Trade sayısı (3y, 10 sym)   | > 30        | >=     |
| Correlasyon engulfing ile   | < 0.5 (abs) | <=     |
| Portfolio yıllık (kombine)  | engulfing-alone + 5% | >= |

Not: Crypto mean-reversion Kaufman imzasının altında (%55-65) kalabilir
çünkü kripto trend-dominant rejimlere sahiptir. Bu beklenen bir sapma.

## 5. Falsification Koşulları (Ne olursa reddederiz)

1. Win rate < 40% → Sistem edge yoktur
2. MaxDD > 50% → Trend rejiminde catastrophic failure (Kaufman uyarısı)
3. Korelasyon engulfing ile > 0.7 → Decorrelation yok, portföy değeri yok
4. Trade sayısı < 20 (3y) → İstatistiksel olarak anlamsız

## 6. Bias ve Sınırlamalar

- **Survivorship bias:** 10 sembol günümüzde hayatta kalan top kripto;
  delisted projeler dahil değil. Sonuçlar optimistic bias taşıyabilir.
- **AVWAP parametre seçimi (anchor):** Swing low/high anchor seçimi
  subjektif görünse de rule-based (son 60 bar fractal swing) kodlandı.
  Anchor değişikliği performansı etkiler — platform riski.
- **Lookahead riski:** AVWAP ve POC hesaplamaları `shift(1)` ile geriye
  güvenli yapıldı, ancak swing anchor seçimi aynı bar içinde yapıldığı için
  ek dikkat gerekir.
- **Slippage:** 5 bps varsayımı — mean-reversion sistemleri daha fazla
  emir gönderir, gerçek slippage daha yüksek olabilir.

## 7. Kaynaklar

- Harris, L. (2003). *Trading and Exchanges: Market Microstructure for
  Practitioners*. Oxford University Press.
  [Microstructure bölümü: informed traders, POC absorpsiyon, VWAP execution]

- Kaufman, P.J. (2013). *Trading Systems and Methods* (5. baskı). Wiley.
  [Mean-reversion imzası, decorrelation, efficiency ratio, regime-aware
   system design]

- Wikipedia (2024). Volume-weighted average price.
  VWAP formülü: VWAP_t = Σ(P_j × Q_j) / Σ Q_j
  [Kurumsal algorithmic execution referans noktası olarak VWAP]

## 8. İmplementasyon Özeti

- Strateji: `AnchoredVWAPReversalStrategy` in
  `src/price_action/strategies/anchored_vwap_reversal.py`
- Backtest: `scripts/run_avwap_backtest.py`
- Tests: `tests/test_anchored_vwap.py`
- Semboller: 10 USDT, 1d, 3y (DuckDB market.duckdb)
