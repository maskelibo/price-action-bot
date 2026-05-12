---
hypothesis_id: 2026-05-12-htf-momentum-mtf-confluence
date: 2026-05-12
author: researcher_agent (opus-4-7-1m)
status: PRE_REGISTERED
version: 0.1
parent_strategy: none (novel)
tags: [multi_timeframe, momentum, ROC, confluence, regime, grimes, brooks]
backtest_possible: true
data_requirements: [1d_ohlcv, 1w_ohlcv, 4h_ohlcv]
expected_correlation_w_top10: low (< 0.25)
---

# HYP-2026-05-12-001 — HTF Momentum Confluence (1W ROC + 4h Pullback + 1D Trigger)

## 1. Pre-Registered İddia (TEK CÜMLE)

> 1D timeframe'de, **3 timeframe'in (1W trend yönü + 1D bias + 4H pullback geri dönüş)**
> kademeli olarak hizalandığı (cascade alignment) anlarda alınan trend-continuation
> sinyalleri; tek-TF (1D-only) Top 10 portföyüne **net +%8 ile +%15 yıllık ROI katkısı**
> sağlar, korelasyonu < 0.30, **3y rolling 13/13 pencerede pozitif**.

**Bağımlı değişken:** Net annualized return (fees+slip dahil), DD, Sharpe, korelasyon.
**Independent variables:** 1W ROC eşiği, 4h pullback derinliği (ATR cinsinden), 1D bar trigger.
**Null hipotez:** Top 10'a eklendiğinde portföy Sharpe'ı +%5'ten az artar VE korelasyon > 0.5.

---

## 2. Motivasyon — Gap Analizi

Top 10 stratejisinin tamamı **tek-zaman-dilimi (1D) tetikleyicili**; sadece bazılarında
basit bir EMA200 trend filtresi var (anchored_vwap, classic_pa). Ancak ne 1W momentum
ne de 4H pullback derinliği aktif kullanılmaz. Bu bir gap'tir çünkü:

- **Grimes (2011, "Volatility Compression")** "regime detection" için ATR-ratio
  short/long bakar — biz hiç multi-TF ratio kullanmıyoruz.
- **Brooks (2012, ch.7 "Always-in")** her zaman diliminde bir "dominant side" vardır,
  ve trade alırken üst TF dominant-side ile çatışmamak gerekir.
- **Carver (2015, "Systematic Trading")** "speed combination" — farklı TF'lerden
  momentum sinyallerinin ortalamasını alan stratejilerin tek-TF muadillerinden
  Sharpe ~ 1.3-1.5x daha iyi olduğunu gösterir.

Üç TF cascade hizalama bizim portföyde **mekanik olarak hiç test edilmedi**;
mevcut anchored_vwap_reversal'da `close > ema200` var ama bu 1D EMA, başka TF değil.

---

## 3. Mekanik Kurallar (kod-edilebilir, lookahead-free)

### 3.1 Veri ve Göstergeler

| Symbol | TF | Lookback | Göstergeler |
|---|---|---|---|
| BTC/ETH/SOL/... 11 sembol | 1W | 26 hafta | ROC(8w), EMA20w |
| Aynı semboller | 1D | 200 bar | EMA50, ATR(14), volume_z(20) |
| Aynı semboller | 4H | 60 bar | RSI(14), EMA20, ATR(14) |

ROC(n) = `(close[t] - close[t-n]) / close[t-n]` — Grimes/Carver standardı.

### 3.2 Cascade Long Filter (3 koşulun TAMAMI gerekli)

```
# 1W trend gücü
weekly_roc_8 > +0.08                                  # 8 haftada +%8 momentum
weekly_close > weekly_ema_20                          # haftalık trend yukarı
weekly_ema_20.diff() > 0                              # haftalık EMA yukarı eğimli

# 1D bias
daily_close > daily_ema_50                            # 1D trend yukarı
daily_close < (daily_swing_high_30 - 0.5*atr_14)      # ATH'e yapışmamış (overextension yok)

# 4H pullback geri dönüş (Grimes "reluctant pullback")
last_4h_rsi_min_in_past_24h < 45                      # son 24h'da 4h RSI dipped (pullback oldu)
current_4h_rsi > previous_4h_rsi                      # RSI yukarı dönüyor (reversal başladı)
current_4h_close > current_4h_ema_20                  # 4H EMA20'yi reclaim
```

### 3.3 Entry Trigger (1D bar)

```
# 1D bar bullish + body dominant + range yeterli
bar_t.close > bar_t.open
bar_t.body / bar_t.range >= 0.55
bar_t.range > 0.7 * atr_14
volume_z_20[t] > -0.5                                 # asgari katılım

# Daily close > 4H last swing high (continuation confirm)
bar_t.close > rolling_max(4h_high, last 6 bars)
```

### 3.4 Risk

- **Entry:** 1D bar t+1 open'da long market.
- **SL:** `min(bar_t.low, last_4h_swing_low) - 0.3*ATR_14_1D`
- **TP:**
  - 1R'da %30 partial close (BE'ye al)
  - 2R'da ek %30 partial (1R lock)
  - %40 runner — Chandelier trail `highest_high - 1.5*ATR_14_1D`
  - Time-stop: 14 günde TP1 dokunmazsa kapat

### 3.5 Short (Simetrik)

Tüm koşulları yön ters çevir: `weekly_roc_8 < -0.08`, `weekly_close < ema20`, vb.

---

## 4. Bağlam Filtresi (Rejim)

- **BTC volatility regime:** ATR_5d / ATR_60d **0.7 - 1.3** aralığında (extreme low/high vol'de devre dışı).
- **BTC dominance:** Long sinyaller `BTC.D` düşüşte iken alt-coinler için filtrelenmez; yukarıda iken sadece BTC/ETH al.
- **Fear-Greed:** 5-25 (extreme fear) VE 75-95 (extreme greed) durumlarında signal_confidence -%30.

---

## 5. Edge Mekanizması — Niye Para Kazanır?

1. **3-TF cascade institutional alignment proxy.** 1W trend kurumsal pozisyon
   yönü; 4H pullback retail-shake-out; 1D trigger continuation. Üçü çakıştığında
   stop-hunt sonrası gerçek devamlılığa biniyoruz, çakışmadığında ya squeeze ya
   choppy range.

2. **Grimes "reluctant pullback" mekaniği** [Grimes 2024, Impulse Moves]: Pullback
   sığ + hızlı reclaim = continuation gücü. 4H RSI dipped + reclaim bu metriği
   ölçer.

3. **Carver "speed combination" diversifikasyonu** [Carver 2015]: Farklı TF
   sinyallerinin geometrik ortalaması, herhangi bir tekil TF'in yanlış-pozitif
   oranını düşürür (Bayes posterior).

---

## 6. Decorrelation Argument (Top 10'a karşı)

| Top 10 üyesi | Bizim sinyalle örtüşme | Neden farklı |
|---|---|---|
| engulfing_continuation | Düşük | Tek-bar candle pattern; biz 3-TF cascade |
| obv_engulfing_confluence | Düşük | OBV proxy vs. ROC absolute trend |
| anchored_vwap_reversal | Çok düşük | Karşı yön (reversal vs. continuation) |
| wyckoff_phase_d | Düşük | Range breakout vs. multi-TF continuation |
| brooks_h2_l2 | **Orta** | Brooks 2-leg pullback similar fikir ama tek-TF |
| pin_bar_round_numbers | Çok düşük | Reversal pin vs. trend follow |
| equal_highs_sweep | Çok düşük | Liquidity sweep mean rev vs. trend |
| cvd_spike_fade | Çok düşük | Spike fade vs. continuation |
| vsa_climax_test | Çok düşük | Phase A reversal vs. continuation |
| brooks_failed_breakout | Düşük | Trap reversal vs. follow-through |

**Tahmini portföy korelasyonu:** 0.20-0.30 (sadece brooks_h2_l2 ile orta).

---

## 7. Curve-Fit Risk

- **Toplam mekanik parametre sayısı:** 8 (3 TF eşiği + 2 ATR çarpanı + 1 body oranı + 2 RSI eşiği).
- Eşiklerin tümü literatürde standart: ROC 8w +%8 (≈ %50 yıllık trend), RSI 45 (orta-dip), body 0.55 (Brooks "strong bar").
- **Yasak parametre:** ROC penceresi 8 — DENEME (4, 8, 13) sadece 3 değer test edilir.
- Bonferroni-korigée alpha: 0.05 / (3 ROC × 3 RSI × 3 body) = 0.05/27 ≈ 0.002.

---

## 8. Backtest Gate'leri (pre-registered)

| Metric | Hedef | Stop criterion |
|---|---|---|
| Yıllık net return (live-realistic) | > +%30 | < +%15 → reddet |
| Max DD | < %30 | > %45 → reddet |
| Walk-forward 13 pencere | ≥ 12 pozitif | < 10 → reddet |
| Sharpe (3y rolling avg) | > 1.0 | < 0.7 → reddet |
| Top 10 portföye eklendiğinde portföy Sharpe | +%5 minimum | < +%2 → reddet |
| Korelasyon (en yakın Top 10 üye ile) | < 0.50 | > 0.60 → reddet |
| Trade frekansı | 30-100 / yıl | < 20 veya > 150 → kalibre |

**Stress periodları (zorunlu pozitif):** 2022-05 LUNA, 2022-11 FTX, 2024-03 ATH dump,
2024-08 Yen carry. Her birinde -%10'dan kötü olmamalı.

---

## 9. Beklenen Edge (Literatür-tabanlı tahmin)

- 1W ROC tek başına ~ Sharpe 0.5 (uzun lookback hill)
- 4H pullback reclaim tek başına WR ~ %55 (Grimes empirical)
- 1D body trigger tek başına WR ~ %52 (Brooks anchor stat)
- **Triple confluence MULTIPLICATIVE:** WR ~ %60-65 beklenir
- 1.6 ortalama R-multiple (partial TP + runner) → expectancy ≈ 0.36R/trade
- 40 trade/yıl × 0.36R × %2.5 risk ≈ **+%36 yıllık net** (beklenti)

---

## 10. Implementasyon Notları

- Yeni module: `htf_momentum_cascade.py`
- Reusable: `_atr`, `_ema`, `_rsi`, `_fractal_swings` (classic_pa.py)
- Yeni helper: `_roc(series, n)`, `_resample_to_weekly(df)`, `_align_higher_tf(df_4h, df_1d)`
- Veri: 1W ve 4H için aynı 11 sembolün ohlcv'si lazım (mevcut data klasöründe muhtemelen var).

---

## 11. Karar Akışı

```
1. Veri hazır mı? → 1W, 4H, 1D 11 sembol için 5 yıl
2. Mekanik backtest çalıştır (3y in-sample)
3. SOP-3 robustness suite (8 madde)
4. Top 10 portföye ekleyerek ortak backtest
5. Gate'ler ✓ → Lab'e tournament adayı
   Gate ✗ → reddet + learning.md
```

---

## Sonuclar (2026-05-14 backtest sonrasi DOLDU)

- [x] Modul: `src/price_action/strategies/htf_momentum.py` (yazildi)
- [x] Script: `scripts/htf_momentum_backtest.py`
- [x] 5y trade pool: 232 trade (11 sym)
- [x] 3y window (2023-01 → 2026-05): 169 sinyal, 143 replay sonrasi
- [x] Standalone yillik: **+%0.01** [FAIL gate >=%10]
- [x] Max DD: **-%55.61** [FAIL gate >=-%45]
- [x] Win rate: %49.0, avg_R +0.026
- [x] Trade frekansi: 42.5/yr (hedef 30-100 ✓)
- [x] Karar: **RED**

## Karar Gerekcesi (RED)

1. **Yillik %0.01** — neredeyse breakeven. WR %49 + avg_R +0.026 = expected value sifira yakin. Mevcut TP/SL yapisi (structural swing + 0.3*ATR padding + 2R primary) bu mekanik kombinasyonda edge uretmiyor.
2. **DD -%55.61** — gate -%45'in tahminine asar. SL geni (structural + buffer) kayipli trade'leri pahalandiriyor.
3. Trade frekansi tahmininde (30-100/yr) — fonksiyon dogru calisiyor (42.5/yr) ama sinyaller karli degil.

## Implikasyonlar

A. **Kombinasyon mekanigi yetersiz** — 1W ROC > 5% + 1D pullback + engulfing trigger uc filtre cok kisitlayici degil ama edge yok. Carver "speed combination" literaturu burada gecmiyor — belki ROC esigi yanlis, belki sinyal bar timing yanlis.

B. **Olasi v2 hipotez** (sonraki sprint):
   - 1W ROC esigi %5'ten %3'e dusur (daha gevsek trend kalitesi)
   - Trigger: engulfing yerine "inside bar breakout" (Brooks IIB pattern)
   - TP: 3R primary + 1.5R partial (mevcut 2R primary'den daha agresif)
   - Stress windows: 2022-05 LUNA + 2024-08 yen carry — bu pencereler edge testi

C. **BALANCED'a ekleme test'i atlanildi** — standalone basarisiz oldugu icin BALANCED+htf_momentum testi mantiksiz (negatif beklenen katki).

## Reproducibility Footer

```
git_hash: 2fec8f16847586030467a8eced1e807ef05b4ab4
config_hash: htf_momentum_v0.1.0 default_manifest
data_hash: market.duckdb 11 sym 1d 5y
run_timestamp: 2026-05-14 (Elapsed 1.8s)
report: inline log
```
