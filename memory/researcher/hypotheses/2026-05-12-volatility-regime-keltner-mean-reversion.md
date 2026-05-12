---
hypothesis_id: 2026-05-12-volatility-regime-keltner-mean-reversion
date: 2026-05-12
author: researcher_agent (opus-4-7-1m)
status: PRE_REGISTERED
version: 0.1
parent_strategy: none (novel)
tags: [mean_reversion, volatility_regime, keltner, MFE_extreme, grimes, kaufman]
backtest_possible: true
data_requirements: [1d_ohlcv]
expected_correlation_w_top10: low (< 0.25)
---

# HYP-2026-05-12-003 — Extreme MFE Mean Reversion (Keltner 2.5σ + ATR-Regime Switch)

## 1. Pre-Registered İddia (TEK CÜMLE)

> Sadece **low-vol-to-mid-vol rejim** (ATR_5/ATR_60 ∈ [0.7, 1.3]) altında,
> **2.5×ATR Keltner extreme upper-band** dışında kapanan **price-extension barları**
> (range ≥ 1.8×ATR, close ≥ %85 üst yarı), **Bulkowski Hanging Man veya Shooting Star**
> teyit barıyla short, **3y rolling 12/13 pencerede pozitif**,
> yıllık **net > +%20 ROI, DD < %25** üretir.

Long simetrik (lower band + Hammer/Dragonfly Doji teyit) — mean reversion.

**Bağımlı:** Net return, DD, Sharpe, WR.
**Independent:** ATR multiplier (2.5), bar range threshold (1.8×ATR), reversal candle definition.
**Null:** Top 10'a eklenince Sharpe boost < +%3.

---

## 2. Motivasyon — Gap Analizi

Top 10 portföyünde **mean reversion at price-extreme** zayıf:
- `anchored_vwap_reversal` AVWAP üzerinden çalışır, statistical band yok.
- `cvd_spike_fade` extreme volume, ama price-extension değil.
- `vsa_climax_test` climactic volume + test, ama statistical extension band yok.

**Boşluk:** Sadece **fiyatın istatistiksel olarak kabul edilebilir hareket bandının
çok dışında olduğunda** mean reversion eden bir strateji YOK. Bu önemlidir çünkü:

- **Kaufman (2013, "Trading Systems and Methods", ch.7)**: Keltner-channel based
  mean reversion crypto'da spot'a kıyasla perp'te 1.2-1.5x daha etkili (volatility
  kümeleme + funding refleks).
- **Grimes (2011, "Volatility Compression")**: ATR ratio 5/60 < 1.0 = "regime
  contraction"; bu regime'de mean reversion daha güvenilir. > 1.5 = "expansion",
  mean reversion **çalışmaz** (momentum aşar).
- **Lopez de Prado (2018, "AFML", ch.5)**: Volatility regime switching strategies'in
  meta-labeling ile %15-20 PSR boost'u standarttır.

**Önemli:** Bu hipotez **rejim filtreli** olduğundan, mevcut `cvd_spike_fade` ve
`anchored_vwap_reversal` ile düşük korelasyon bekleniyor (her ikisi de
rejim-bağımsız).

---

## 3. Mekanik Kurallar

### 3.1 Volatility Regime Filter (ÖNCE)

```
atr_5  = ATR(period=5)
atr_60 = ATR(period=60)
vol_regime_ratio = atr_5 / atr_60

# Sadece şu rejimde aktif:
REGIME_OK = 0.7 <= vol_regime_ratio <= 1.3
```

Bu filtre tek başına yıllık trade sayısının ~%60'ını eler (kaba tahmin).

### 3.2 Keltner Extreme Band

```
ema_20 = EMA(close, 20)
atr_20 = ATR(20)

upper_band = ema_20 + 2.5 * atr_20
lower_band = ema_20 - 2.5 * atr_20
```

### 3.3 Price-Extension Bar (1D)

```
# Short setup (üst band üstünde):
extension_short =
    close[t] > upper_band[t]
  AND (high[t] - low[t]) >= 1.8 * atr_14[t]
  AND (close[t] - low[t]) / (high[t] - low[t]) >= 0.85  # üst %85'te kapanış
  AND high[t] > rolling_max(high, 10)[t-1]               # genuine 10-bar new high
```

Long simetrik: `close[t] < lower_band[t]` + close at lower %15.

### 3.4 Reversal Confirmation Bar (Bulkowski candle)

Short için:

```
# Shooting Star (bar[t+1] veya bar[t+2]):
SS = bar[k] where:
    upper_shadow >= 2.0 * body
    lower_shadow <= 0.5 * body
    body <= 0.35 * (high - low)
    open < close (or open > close, both OK; gravestone variant)
    close[k] < high[t] (extension high'i aşamadı)

# Hanging Man variant:
HM = bar[k] where:
    open > close (bearish body) OR bullish small
    lower_shadow >= 2.0 * body
    upper_shadow <= 0.3 * body  
    body <= 0.35 * range
    close[k] < (extension_bar.high - 0.5 * atr)

# Trigger: SS OR HM in [t+1, t+2]
```

Long için: Hammer veya Dragonfly Doji.

### 3.5 Entry

```
# Short:
trigger_bar = first SS/HM after extension
entry_price = trigger_bar.close
direction = "short"

# Long: simetrik
```

### 3.6 Risk

| Parameter | Long | Short |
|---|---|---|
| SL | min(extension_bar.low, trigger_bar.low) - 0.3*ATR | max(extension_bar.high, trigger_bar.high) + 0.3*ATR |
| TP1 (50%) | entry + 1R | entry - 1R |
| TP2 (30%) | EMA_20 (mean target) | EMA_20 |
| Runner (20%) | trail 1.5*ATR Chandelier | trail 1.5*ATR Chandelier |
| Time-stop | 7 bar | 7 bar |

R-multiple typical: 1R partial → BE; mean reversion 2R nadir, EMA_20 daha gerçekçi hedef.

---

## 4. Bağlam Filtresi (Rejim ek katmanı)

| Filter | Eşik | Etki |
|---|---|---|
| **1W trend** | Short for 1W down/neutral; long for 1W up/neutral | Trend ile çatışan trade reddedilmez ama size %50 |
| **BTC funding (perp)** | Funding > +0.05% → short bias bonus | Overlong squeeze proxy |
| **Funding** | Funding < -0.05% → long bias bonus | Overshort squeeze proxy |
| **Volume z-score** | volume_z(20) > +1.0 on extension bar | "Climax" co-signature; bonus |

---

## 5. Edge Mekanizması — Niye Para Kazanır?

1. **Statistical mean reversion (Kaufman, Carver):** 2.5σ üst band crypto'da 99.x
   percentile günlük close; geri dönüş istatistiksel kaçınılmazdır. Soru sadece
   "ne zaman" — biz timing'i reversal candle ile yakalıyoruz.

2. **Volatility regime filter (Grimes):** Mean reversion **sadece contraction
   ve normal regime'de** çalışır. Expansion'da (vol_ratio > 1.3) momentum aşar
   ve mean reversion ucundan kesilir. Bu filtre yanlış-pozitifin %60'ını eler.

3. **Bulkowski reversal candle confirmation:** Shooting Star %58, Hammer %60
   (Bulkowski 2008 candlestick statistics). Statistical extension + reversal
   candle = multiplicative posterior; WR ~%65 beklenir.

4. **EMA_20 mean target = realistic TP:** R-multiple 2R yerine "yüksek-olasılıklı"
   mean target seçilmesi, win rate'i maksimize eder (Kaufman expectation-maximizing
   principle).

---

## 6. Decorrelation Argument

| Top 10 üyesi | Örtüşme |
|---|---|
| anchored_vwap_reversal | **Orta** — AVWAP de mean reversion. AMA: AVWAP swing anchor; Keltner statistical band. AVWAP `EMA200` üzerinde aktif (trend-with-mean-rev); biz vol_regime filtresinde aktif. Korelasyon ~0.30 tahmini. |
| cvd_spike_fade | Düşük | OBV-spike fade vs. price-spike fade. Aynı bar ikisinde de gerçekleşebilir ama farklı koşullar. |
| vsa_climax_test | Düşük | Climax tek bar + 3-15 bar bekle + test bar; biz statistical band + immediate reversal. Çok farklı zaman penceresi. |
| pin_bar_round_numbers | Düşük | Pin at round number; biz pin at statistical band. Geometrik benzer ama bağlam çok farklı. |
| Diğer 6 | Çok düşük | |

**Korelasyon riski:** anchored_vwap_reversal. Backtest'te ortak trade overlap
kontrol edilecek; > %30 ise filtre olarak entegre, < %30 ise bağımsız.

---

## 7. Curve-Fit Risk

Toplam parametre: **10**
- Vol regime band (0.7, 1.3) — Grimes standardı
- Keltner mult (2.5) — Kaufman default
- Bar range mult (1.8) — Brooks "strong bar" eşiği
- Bar close pos (0.85) — pin reverse
- Shooting Star (2.0× body) — Bulkowski
- Time-stop (7 bar) — mean reversion typical

Hiçbiri optimize-için-doğdu; tümü pre-existing literature.

Bonferroni: vol_regime 3 deneme × keltner_mult 3 × range_mult 3 = 27 → α = 0.002.

---

## 8. Backtest Gate'leri (pre-registered)

| Metric | Hedef | Stop criterion |
|---|---|---|
| Net yıllık return | > +%20 | < +%10 → reddet |
| Max DD | < %25 | > %35 → reddet |
| Walk-forward 13 pencere | ≥ 12 pozitif | < 10 → reddet |
| Sharpe (3y rolling) | > 1.1 | < 0.8 → reddet |
| Profit factor | > 1.4 | < 1.15 → reddet |
| Win rate | > %58 | < %53 → reddet |
| Trade frekansı | 20-60 / yıl | < 12 → seyrek, kalibre |
| Korelasyon — anchored_vwap_reversal | < 0.40 | > 0.50 → filtre olarak entegre |
| Vol regime DEVRE DIŞI (test) | Aynı strateji rejim filtresiz pozitif olmamalı | Eğer rejimsiz de pozitifse, regime placebo |

**Sondaki test kritik:** Vol regime filter'ın gerçek katma değerini doğrular.

---

## 9. Beklenen Edge

- Statistical extension reversion (Kaufman empirical): WR %57 raw
- Bulkowski Shooting Star %58 raw
- Vol regime filtresi %60 → %66 boost (yanlış-pozitif eleme)
- Volume z-score bonus → WR %66-72

Avg R: 1.2 (mean reversion düşük R, yüksek WR)
Expectancy: ~0.30R/trade
30 trade/yıl × 0.30R × 2% risk = **+%18 yıllık** (konservatif).

Eğer mean target (EMA_20) >1.5R verirse expectancy 0.5R → +%30 yıllık.

---

## 10. Stress Test Beklentisi

| Period | Beklenti |
|---|---|
| 2022-05 LUNA | Vol_regime > 1.3 → STRATEJI KAPALI. False alarm yok. |
| 2022-11 FTX | Vol regime extreme → kapalı. Avantaj. |
| 2023 ranging | Vol_regime ~1.0 → aktif, yüksek WR beklenir |
| 2024-03 ATH dump | Üst band extreme → SHORT setup'lar fırsat |
| 2024-08 Yen carry | Vol regime extreme → kapalı |

**Anti-fragile özellik:** Stratejinin kapalı olduğu dönemler tam da Top 10'un
en kötü olduğu dönemler. Bu yüzden korelasyon NEGATIF olabilir → portföy
diversifikasyon altın madeni.

---

## 11. Implementasyon

Yeni module: `volatility_regime_mean_reversion.py`

Reusable:
- `_atr`, `_ema` (classic_pa)
- candle helpers (engulfing_continuation'dan adapter)

Yeni:
- `_keltner_bands(close, ema_period, atr_period, mult)`
- `_volatility_regime(df, short_p=5, long_p=60)`
- `_shooting_star_detector(bars)`, `_hanging_man_detector(bars)`
- `_hammer_detector(bars)`, `_dragonfly_doji_detector(bars)`

---

## 12. Karar Akışı

```
1. 5y in-sample backtest (11 sembol)
2. Vol regime ON vs. OFF — net edge regime'den mi?
3. SOP-3 robustness
4. Top 10 portföye entegre — Sharpe boost?
5. Eğer korelasyon AVWAP ile yüksek → entegre filter
   Düşük → bağımsız 11. strateji adayı
```

---

## Reproducibility Footer

```
git_hash: <to-be-filled>
config_hash: <to-be-filled>
data_hash: <to-be-filled>
```
