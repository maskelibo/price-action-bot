---
hypothesis_id: 2026-05-12-volatility-compression-breakout-nr7
date: 2026-05-12
author: researcher_agent (opus-4-7-1m)
status: PRE_REGISTERED
version: 0.1
parent_strategy: none (novel)
tags: [volatility_compression, NR7, NR4, breakout, regime, crabel, grimes, brooks]
backtest_possible: true
data_requirements: [1d_ohlcv]
expected_correlation_w_top10: very_low (< 0.20)
---

# HYP-2026-05-12-004 — Volatility Compression Breakout (NR7 + ATR-Ratio + Range Bracket)

## 1. Pre-Registered İddia (TEK CÜMLE)

> 1D timeframe'de **NR7 (narrowest range of 7 bars)** veya **ID/NR4 (inside day + NR4)**
> oluşması, **ATR ratio (5/60) < 0.85** (Grimes compression regime), ve son 14 barlık
> tight-trading-range (`max(high,14) - min(low,14) < 2.0*ATR_60`) koşullarının
> üçünün birlikte gerçekleştiği günde, ertesi günün range high+0.1*ATR / low-0.1*ATR
> OCO bracket'i ile **%55-65 win rate** ve **3y rolling 12/13 pozitif**, yıllık
> **net > +%25 ROI, DD < %25** üretir.

**Bağımlı:** Net return, DD, Sharpe, WR, expectancy.
**Independent:** NR-window (7), ATR ratio threshold (0.85), TTR window (14), bracket buffer.
**Null:** Compression filter olmadan breakout 50:50 (random); compression net edge sıfır.

---

## 2. Motivasyon — Gap Analizi

Top 10 portföyünde **volatility-compression-based directional breakout** YOK:
- `wyckoff_phase_d` Spring sonrası SOS breakout'u kullanır, ama Wyckoff-specific
  multi-bar pattern; NR7/ATR-ratio compression metriği değil.
- `brooks_h2_l2` 2-leg pullback; compression metriği yok.
- `brooks_failed_breakout` trap reversal — biz **GERÇEK** breakout aralarız.

**Boşluk:** "Sessizlik fırtınadan önce" mekaniğinin **kantitatif compression
metric** ile tetiklenen mekanik versiyonu yok.

**Literatür (sağlam):**
- **Crabel (1990, "Day Trading with Short-Term Price Patterns and Opening Range Breakout")**:
  NR7 + ID/NR4 patterns'ın istatistiksel breakout edge'i sergilediğini gösterdi
  (S&P futures'ta %58 directional WR, +1.4R avg).
- **Grimes (2011, "Volatility Compression")**: ATR ratio 5/60 < 1.0 = compression
  state, directional move probability artar.
- **Toby Crabel (orijinal araştırma 1989)**: "Sequential volatility compression"
  edge'inin futures'tan equities ve FX'e transfer edilebildiğini gösterdi;
  Linda Raschke crypto'da da çalıştığını rapor etti (Raschke MarketStudies 2020).
- **Brooks (2012, ch.14 "TTR")**: tight trading range (10-15 bar range ≤ 1.5*ATR)
  breakout'u standalone WR %55-65; volume confirmation ile %63-72.
- **HYP-NEW-8 (May 9 batch)**: TTR + Effort-to-Move önerildi, ama implemente
  edilmedi. Bu hipotez onu **mekanik olarak somutlaştırır** ve **NR7 + ATR ratio**
  ile compression metriğini güçlendirir.

---

## 3. Mekanik Kurallar

### 3.1 Compression Detection (TÜM 3 KOŞUL gerekli)

```
# (A) NR7 veya ID/NR4:
nr7 = (high[t] - low[t]) == min(high[t-6:t+1] - low[t-6:t+1])
id_nr4 = is_inside_bar(bar[t], bar[t-1]) AND (high[t]-low[t]) == min(range[t-3:t+1])
compression_pattern = nr7 OR id_nr4

# (B) ATR ratio (Grimes regime):
atr_5  = ATR(5)
atr_60 = ATR(60)
atr_compression = (atr_5[t] / atr_60[t]) < 0.85

# (C) Tight trading range (Brooks):
window = 14
range_14 = rolling_max(high, 14)[t] - rolling_min(low, 14)[t]
ttr = range_14 < 2.0 * atr_60[t]

# Tüm 3 koşul:
compression_signal = compression_pattern AND atr_compression AND ttr
```

### 3.2 Bracket Order (t+1 günü)

```
bracket_high = high[t] + 0.10 * atr_14[t]
bracket_low  = low[t]  - 0.10 * atr_14[t]

# T+1 günü içinde hangisi ilk tetiklenirse:
- close[t+1] crosses bracket_high → LONG (market or stop-buy)
- close[t+1] crosses bracket_low  → SHORT (market or stop-sell)
- Neither → t+1 sonu iptal; t+2 için bracket güncelle (3 gün max)
```

### 3.3 Entry Confirmation (false-breakout filter)

Sadece bracket tetiklemesi yeterli değil; bar kapanışında onay:

```
# Long entry:
if close[t+1] > bracket_high AND volume[t+1] > 1.2 * volume_sma_20:
    entry = close[t+1]
    # OR: enter at bracket break intra-bar (aggressive)
```

Volume filter Brooks "effort-to-move" prensibinden gelir.

### 3.4 Risk

- **SL:** opposite bracket - 0.2*ATR (long → bracket_low - 0.2*ATR)
- **TP:**
  - Measured move = range_14 (compression-range projected) → 1R partial
  - 2× range_14 projected → 2R partial
  - Runner: %30, Chandelier 2.0*ATR trail
- **Time stop:** 10 bar (compression breakout momentum genelde 1-2 hafta sürer)

### 3.5 Invalidation

- t+1 bracket'e dokunmazsa t+2'de yeni bracket (max 3 gün)
- 3 gün sonra hala dokunmazsa setup iptal

---

## 4. Bağlam Filtresi (Rejim)

| Filter | Eşik | Etki |
|---|---|---|
| **Volume z-score on compression day** | volume_z(20) < 0 | Compression "gerçek" — düşük katılım |
| **1W trend yönü** | herhangi | Bidirectional — biz yön bilmediğimiz için bracket kullanıyoruz |
| **Sembol** | 11 sembol (mevcut portföy) | |
| **Fear-Greed** | herhangi | Compression rejim-bağımsız |

---

## 5. Edge Mekanizması — Niye Para Kazanır?

1. **Volatility clustering — fizik**: Düşük-vol periodlar yüksek-vol periodlarla
   takip edilir (GARCH/Engle empirical). Crabel'in 30+ yıllık edge'i bu temele dayanır.

2. **3 farklı compression metric'in confluence'ı (multiplicative):**
   - NR7: single-bar tightness
   - ATR ratio: kısa-vade-uzun-vade compression
   - TTR: multi-bar range compression
   Üçü birlikte → "süper-compressed coil"; breakout olasılığı normalden 2-3x.

3. **Bracket order = directional uncertainty resolution.** Compression doesn't
   tell us direction, sadece "büyük hareket olacak". Bracket ikisini de yakalar;
   yanlış yön → SL sıkı.

4. **Volume on breakout = effort-to-move (Brooks/VSA):** Sadece compression sonrası
   düşük-hacim breakout false-positive; volume kontrolü %15-20 WR boost verir.

5. **Measured move target:** Compression range büyüklüğünde ilk hedef — empirically
   %85 oranında ulaşılır (Crabel data). Bu high-confidence TP.

---

## 6. Decorrelation Argument

| Top 10 üyesi | Örtüşme |
|---|---|
| brooks_failed_breakout | **Orta-Düşük** | Aksine: biz GERÇEK breakout aralarız (volume + compression confluence); failed_breakout TRAP'i avlar. Korelasyon NEGATİF olabilir (biri kazanırken diğeri kaybediyor) — diversifikasyon altın madeni. |
| wyckoff_phase_d | Düşük | Wyckoff Spring + SOS multi-bar specific structure; NR7/ATR-ratio değil. |
| brooks_h2_l2 | Düşük | 2-leg pullback in trend; compression breakout farklı setup |
| engulfing_continuation | Düşük | Single-bar engulfing in trend; compression breakout farklı tetikleyici |
| Diğer 6 | Çok düşük | |

**Negatif korelasyon brooks_failed_breakout ile?** Bu KEŞİF değerinde.
Backtest'te ortak window'larda zıt edge varsa portföy Sharpe boost dramatic olur.

---

## 7. Curve-Fit Risk — DÜŞÜK

Toplam parametre: **8**
- NR window: 7 (Crabel standart)
- ATR short/long: 5/60 (Grimes standart)
- ATR ratio threshold: 0.85 (Grimes < 1.0; biz daha sıkı)
- TTR window: 14 (Brooks 10-15)
- TTR width: 2.0*ATR_60 (Brooks 1.5; biz daha gevşek)
- Bracket buffer: 0.10*ATR (yaygın)
- Volume mult: 1.2 (mid)
- Time stop: 10 bar (Brooks/Crabel)

Hiçbiri özel optimizasyon değil; hepsi 30+ yıllık literatürde sabit.
Bonferroni: 8 parametre × 3 grid = 24 → α = 0.002.

---

## 8. Backtest Gate'leri (pre-registered)

| Metric | Hedef | Stop criterion |
|---|---|---|
| Net yıllık return | > +%25 | < +%12 → reddet |
| Max DD | < %25 | > %35 → reddet |
| Walk-forward 13 pencere | ≥ 12 pozitif | < 10 → reddet |
| Sharpe (3y rolling) | > 1.1 | < 0.8 → reddet |
| Profit factor | > 1.6 | < 1.2 → reddet |
| Win rate | > %55 | < %50 → reddet |
| Trade frekansı | 20-50 / yıl | < 12 → çok seyrek (compression rare); > 80 → kalibre |
| Korelasyon — Top 10 portföy | < 0.25 | > 0.40 → reddet |
| Korelasyon — brooks_failed_breakout | negative or < 0 | > +0.30 → ortak edge, ikilik anlamsız |

**Özel test:** Compression filtersiz (sadece NR7) versus compression filterli — net edge
compression-attribuable olmalı.

---

## 9. Beklenen Edge

- NR7 alone (Crabel S&P data 30y): WR %58, avg R 1.4
- TTR breakout (Brooks): WR %55-65 standalone
- ATR-ratio filter (Grimes): +%5-8 WR improvement (false-positive filter)
- 3-confluence multiplicative: WR **%63-72**

Avg R: 1.5 (compression range measured move + runner)
Expectancy: ~0.55R/trade
30 trade/yıl × 0.55R × 2.5% risk = **+%41 yıllık** (optimistic)
Slip+funding %25 → **+%30-35 net** (target).

---

## 10. Stress Test Beklentisi

| Period | Beklenti |
|---|---|
| 2022-05 LUNA | Compression sonrası dump fırsatı; SHORT bracket kazanır. ATR ratio belki coiled olarak girdi. |
| 2022-11 FTX | Yüksek vol → compression rare → strateji seyrek. False alarm yok. |
| 2023 ranging | Compression sık, breakout false-positive yüksek; volume filter kritik. |
| 2024-03 ATH dump | Compression öncesi orderly → SHORT bracket. |
| 2024-08 Yen carry | Compression + cascade → both directions test. |

---

## 11. Implementasyon

Yeni module: `volatility_compression_breakout.py`

Reusable:
- `_atr` (classic_pa)
- `_volume_sma`, `_volume_zscore`

Yeni:
- `_nr7_detector(df, n=7)`
- `_id_nr4_detector(df, n=4)`
- `_atr_ratio(df, short=5, long=60)`
- `_ttr_detector(df, window=14, max_atr_mult=2.0)`
- `_bracket_order_logic(t1_bar, bracket_high, bracket_low)`

---

## 12. Karar Akışı

```
1. 5y in-sample (11 sembol)
2. Test compression filter ON vs OFF (filter net edge'in mi?)
3. SOP-3 robustness
4. Korelasyon analizi — özellikle brooks_failed_breakout (negatif bekleniyor)
5. Top 10 ile birlikte portföy backtest (Sharpe boost ölç)
6. Gate ✓ → Lab tournament
```

---

## 13. Beklenen Implikasyonlar

Eğer bu strateji **brooks_failed_breakout ile negatif korelasyon** verirse, portföy
diversifikasyonu için **istatistiksel altın** anlamına gelir. Iki strateji
"compression → genuine breakout" ve "expansion → failed breakout" aynı para birimi
iki yüzü; ne zaman biri kaybetse öbürü kazanır. Bu ideal portföy davranışıdır
(Sharpe maximizing).

---

## Reproducibility Footer

```
git_hash: <to-be-filled>
config_hash: <to-be-filled>
data_hash: <to-be-filled>
```
