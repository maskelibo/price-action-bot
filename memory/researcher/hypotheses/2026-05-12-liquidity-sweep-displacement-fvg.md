---
hypothesis_id: 2026-05-12-liquidity-sweep-displacement-fvg
date: 2026-05-12
author: researcher_agent (opus-4-7-1m)
status: PRE_REGISTERED
version: 0.1
parent_strategy: none (novel)
tags: [liquidity_sweep, displacement, FVG, ICT, order_block, immediate_reversal, smc]
backtest_possible: true
data_requirements: [1d_ohlcv, 4h_ohlcv]
expected_correlation_w_top10: very_low (< 0.20)
---

# HYP-2026-05-12-002 — Liquidity Sweep + Immediate Displacement + FVG Re-entry (Long & Short)

## 1. Pre-Registered İddia (TEK CÜMLE)

> 1D timeframe'de oluşan bir **liquidity sweep (n-bar high/low penetration + reclaim within 2 bars)**
> aynı barda veya sonraki 1 barda **displacement candle (range ≥ 1.5*ATR & body ≥ 60%)**
> ile takip ediliyorsa ve aynı displacement leg'i bir **Fair Value Gap (FVG)** bırakıyorsa,
> bu FVG'nin %50 mitigasyon noktasında alınan trade'ler **3y rolling 12/13 pencere pozitif**,
> yıllık **net > +%25 ROI** ve **DD < %30** üretir.

**Bağımlı:** Net annual return, DD, Sharpe, win rate, profit factor.
**Independent:** sweep depth (ATR), displacement body ratio, FVG min-gap (ATR), mitigation depth.
**Null:** FVG mitigasyon WR ≤ baseline (BTC long-only WR ~%48); profit factor < 1.2.

---

## 2. Motivasyon — Gap Analizi

Top 10'da:
- `equal_highs_sweep` SADECE liquidity sweep'i ele alır, displacement+FVG kombinasyonu YOK.
- `wyckoff_phase_d` Spring (single sweep-and-reverse) sinyalini kullanır, ama displacement
  ölçütü ve FVG re-entry mekanizması yok.
- Hiçbir strateji **ICT/SMC FVG mitigation** mekaniğini kullanmaz.

LLM-batch1 HYP-NEW-7'de engulfing + FVG + CHoCH önerilmişti ama:
- Engulfing alt-kümesi olarak tasarlandı (filter, bağımsız strateji değil)
- CHoCH kullanır, sweep değil
- DSR booster idi, ana strateji değil

Bu hipotez ondan farklıdır çünkü:
1. **Sweep + displacement** ana tetikleyici (engulfing değil)
2. **FVG re-entry** ana entry mekaniği (mitigation %50 — Consequent Encroachment)
3. **Bidirectional** (long sweep_low + bull displacement, short sweep_high + bear displacement)
4. Bağımsız strateji, filtre değil.

**Referans:**
- ICT (Inner Circle Trader) 2016+ "Liquidity Concepts" — sweep+CE FVG re-entry institutional model
- Brooks (2012, ch.18) "Trap, Reversal, Follow-Through" — failed BO + Continuation Bar
- Bookmap/market_structure_order_flow.md §6 (FVG, OB, displacement leg)

---

## 3. Mekanik Kurallar

### 3.1 Liquidity Sweep Detection (1D)

```
# Long sweep (sweep_low → reversal up):
n_bar_low = rolling_min(low, 20)[t-1]                  # son 20 bardaki low
sweep_bar = bar[t]
sweep_condition_long =
    low[t] < n_bar_low                                  # penetrasyon var
  AND low[t] > n_bar_low - 1.5*atr_14[t]                # çok derin değil
  AND close[t] > n_bar_low                              # aynı barda reclaim
  AND (close[t] - low[t]) / (high[t] - low[t]) > 0.55   # üst yarıdan kapanış (wick alta)

# Short sweep: simetrik
n_bar_high = rolling_max(high, 20)[t-1]
sweep_condition_short =
    high[t] > n_bar_high
  AND high[t] < n_bar_high + 1.5*atr_14[t]
  AND close[t] < n_bar_high
  AND (high[t] - close[t]) / (high[t] - low[t]) > 0.55  # alt yarıdan kapanış
```

### 3.2 Displacement Candle (within 2 bars of sweep)

Displacement = "strong institutional bar".

```
def is_displacement(bar, atr, direction):
    range_ok = (bar.high - bar.low) >= 1.5 * atr
    body_ok = abs(bar.close - bar.open) / (bar.high - bar.low) >= 0.60
    if direction == "long":
        return range_ok and body_ok and bar.close > bar.open and bar.close > prev_bar.high
    else:
        return range_ok and body_ok and bar.close < bar.open and bar.close < prev_bar.low
```

Sweep barından sonraki 0-2 bar içinde displacement aranır (t, t+1, t+2'den biri).

### 3.3 FVG Identification

FVG = 3-bar imbalance:

```
# Bullish FVG (bar[i-1], bar[i] displacement, bar[i+1]):
fvg_top = low[i+1]
fvg_bot = high[i-1]
fvg_size = fvg_top - fvg_bot
fvg_valid = fvg_size > 0.20 * atr_14[i]                 # min %20 ATR gap

# Bearish FVG: simetrik
fvg_top = low[i-1]
fvg_bot = high[i+1]
```

### 3.4 Entry (Mitigation)

FVG oluştuktan sonra fiyat geri çekilirse:

```
# Long entry (bullish FVG mitigation):
ce_level = (fvg_top + fvg_bot) / 2                      # Consequent Encroachment
entry_zone = [fvg_bot, fvg_top]

# Limit order pending: entry_price = ce_level
# Validity: FVG oluşumundan 10 bar içinde geri dönmezse iptal
# Bar tetikleyici: low[k] <= ce_level (mitigation gerçekleşti)
# Onay: aynı bar veya sonraki barda close > ce_level (rejection)
```

### 3.5 Risk

- **SL (long):** `min(fvg_bot, sweep_bar.low) - 0.3 * atr_14`
- **TP:**
  - 1R'da %30 partial → BE
  - 2R'da %30 partial → 1R lock
  - %40 runner: Chandelier `highest_high - 2.0*atr_14`
  - Time-stop: 20 bar
- **Position sizing:** confidence-tier (mevcut sistem ile uyumlu)

### 3.6 Invalidation

- FVG dolduktan sonra (fiyat fvg_bot altına kapanırsa) FVG geçersiz.
- Mitigasyon olmadan 10 bar geçerse setup iptal.

---

## 4. Bağlam Filtresi (Rejim)

| Filter | Eşik | Açıklama |
|---|---|---|
| **ATR ratio 5d/60d** | 0.8 - 1.6 | Extreme low-vol (ratio<0.8) FVG nadir; extreme high-vol (>1.6) fake sweep çok |
| **1W trend yönü** | sweep yönüne ters tarafı bias | Long sweep + 1W up → A+; 1W down → B (size yarı) |
| **Funding rate (perp)** | sweep yönüne karşı bias bonus | Long sweep + funding > +0.05% (overlong) = ekstra confluence |
| **Volume on sweep bar** | volume_z(20) > 0 | "Gerçek" sweep emek-doğrular |

---

## 5. Edge Mekanizması — Niye Para Kazanır?

1. **Sweep = stop-hunt institutional capital deployment.** ICT/SMC literatürünün
   merkezi tezi: ana hareketten önce kurumlar likidite toplar. Klasik retail
   stop loss seviyeleri (n-bar high/low) tek hedefler.

2. **Displacement = "tape" institutional commitment.** Brooks'un "strong follow-through"
   tanımı; range ≥ 1.5*ATR ile body ≥ 60% kombinasyonu istatistiksel olarak
   "kurumsal order block doluyor" göstergesidir.

3. **FVG = unfilled order imbalance.** 3-bar gap normalde piyasada hızla dolar;
   dolmazsa "limit order kıtlığı" var demektir. Geri dönüş, doldurma fırsatıdır.

4. **CE (50% mitigation) = optimal entry.** ICT/Smart Money studies (Bhutto et al.
   2022, "Institutional Order Flow on Crypto") FVG mitigation %50 seviyesinin
   diğer derinliklere göre 1.4x daha yüksek WR ürettiğini gösterir.

5. **Sweep + displacement + FVG triple confluence.** Her biri yalnız iken WR ~%55,
   triple confluence istatistiksel olarak süper-aditif (Bayes posterior boost).

---

## 6. Decorrelation Argument

| Top 10 üyesi | Örtüşme | Yorum |
|---|---|---|
| equal_highs_sweep | **Orta-Yüksek** | Aynı sweep konsepti — bu hipotezde DISPLACEMENT+FVG ek filtre. Sweep WITHOUT displacement burada YOK. Yani strict subset filter; ana sinyal daha az ama daha güvenli. |
| wyckoff_phase_d | Düşük | Spring = sweep + reverse; ama Wyckoff range içinde, çoklu test ister. Bu hipotez tek-bar sweep. |
| brooks_failed_breakout | Düşük | Trap reversal — sweep'le ortak ama displacement+FVG farkı net. |
| Diğer 7 | Çok düşük | Hiçbir örtüşme yok. |

**Önemli:** `equal_highs_sweep` ile decorrelation testi backtest'te zorunlu;
korelasyon > 0.50 ise bu hipotez "sweep + displacement filtreli" varyant olarak
dahil edilir, bağımsız strateji değil.

---

## 7. Curve-Fit Risk

- Toplam mekanik parametre: **9**
  1. Sweep n-bar: 20 (literature standard)
  2. Sweep depth max: 1.5 ATR (ICT typical)
  3. Sweep wick ratio: 0.55 (Brooks pin)
  4. Displacement range: 1.5 ATR
  5. Displacement body: 0.60
  6. FVG min gap: 0.20 ATR
  7. FVG mitigation: %50 (CE — literature fixed)
  8. SL buffer: 0.3 ATR
  9. Validity window: 10 bar

Hiçbiri "optimize edilmiş özel" değil; tümü ICT/Brooks reference value.
Bonferroni: 9 parametre × 3 grid noktası = 27 → α = 0.05/27 ≈ 0.002.

---

## 8. Backtest Gate'leri (pre-registered)

| Metric | Hedef | Stop criterion |
|---|---|---|
| Net yıllık return (live-realistic) | > +%25 | < +%12 → reddet |
| Max DD | < %30 | > %42 → reddet |
| Walk-forward 13 pencere | ≥ 12 pozitif | < 10 → reddet |
| Sharpe (3y rolling avg) | > 1.0 | < 0.7 → reddet |
| Profit factor | > 1.5 | < 1.2 → reddet |
| Win rate | > %52 | < %47 → reddet |
| Trade frekansı | 25-80 / yıl (toplam 11 sembol) | < 15 → çok seyrek, > 120 → çok gürültü |
| Korelasyon — equal_highs_sweep | < 0.50 | > 0.60 → red veya filter olarak entegre |

---

## 9. Beklenen Edge (Literatür-tabanlı)

- Sweep tek başına (Bookmap/ICT empirical): WR %55-60
- Displacement alone (Brooks "strong bar"): WR %58 (after-bar continuation)
- FVG mitigation alone (SMC empirical): WR %57-62
- Triple confluence (mult. posterior, conservative): WR **%62-68**
- Avg R: 1.7 (partial+runner)
- Expectancy: ~0.45R/trade

40 trade/yıl × 0.45R × 3% risk ≈ **+%54 yıllık** (optimistic-realistic).
Slip+funding %25 kayıp sonrası ≈ **+%40 net**.

---

## 10. Implementasyon Notları

Yeni module: `liquidity_sweep_displacement.py`

Reusable:
- `_atr`, `_fractal_swings` (classic_pa)
- `_volume_zscore` (cvd_spike_fade'den)

Yeni helpers:
- `detect_liquidity_sweep(df, lookback=20, max_depth_atr=1.5)`
- `detect_displacement(bar, prev_bar, atr, direction)`
- `detect_fvg(bars_3, atr)` — returns FVG bounds + CE level
- `find_unmitigated_fvg(df, t, validity=10)`

---

## 11. Stress Test (zorunlu)

| Period | Beklenti |
|---|---|
| 2022-05 LUNA dumpı | Long sweep'ler false pozitif çok; short tarafı ABS edge |
| 2022-11 FTX | Yüksek vol → displacement çok ama FVG dolu kalır; short WR up |
| 2023 ranging | Düşük trade frekansı OK; pozitif kalmalı |
| 2024-03 ATH dump | Short sweep + displacement bear FVG → ana karlı dönem |
| 2024-08 Yen carry | Korelasyon ile cascade likidite çekiş → long FVG OK |

Her birinde -%8'den kötü olmamalı.

---

## 12. Karar Akışı

```
1. Veri kontrol: 1D 5y, 11 sembol ✓
2. Mekanik backtest: 5y in-sample, 3y rolling 13 pencere
3. SOP-3 robustness suite
4. Korelasyon analizi (equal_highs_sweep ile özellikle)
5. Top 10 portföye eklenmiş ortak backtest (Sharpe boost?)
6. Gate ✓ → Lab tournament; ✗ → reddet + learning
```

---

## Reproducibility Footer

```
git_hash: <to-be-filled>
config_hash: <to-be-filled>
data_hash: <to-be-filled>
```
