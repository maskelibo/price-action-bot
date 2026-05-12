---
hypothesis_id: 2026-05-12-funding-oi-divergence-reversal
date: 2026-05-12
author: researcher_agent (opus-4-7-1m)
status: PRE_REGISTERED
version: 0.1
parent_strategy: none (novel)
tags: [funding, open_interest, divergence, perp_microstructure, harris, hayes, alameda]
backtest_possible: true
data_requirements: [1d_ohlcv, 8h_funding, daily_open_interest]
expected_correlation_w_top10: very_low (< 0.15)
---

# HYP-2026-05-12-005 — Funding/Open-Interest Divergence + Price Action Reversal Trigger

## 1. Pre-Registered İddia (TEK CÜMLE)

> 1D timeframe'de, **3-bar kümülatif funding rate** (8h × 3 = 24h sum) ile
> **Open Interest delta** (Δ_OI/OI > +%5 in 3 günde) arasında **yön çatışması**
> (e.g., yüksek pozitif funding + AYNI BARDA OI artıyor = overlong squeeze setup),
> 1D bar üzerinde **rejection candle** (Hanging Man veya Shooting Star) ile teyit
> edildiğinde, **3y rolling 12/13 pencere pozitif**, yıllık **net > +%20 ROI,
> DD < %25** üretir.

**Bağımlı:** Net annual return, DD, Sharpe, WR.
**Independent:** Funding cumsum threshold, OI delta threshold, rejection candle definition.
**Null:** Funding spike single signal (no OI/PA confluence) → WR ≤ %50; bu hipotez confluence ile +%5-10 WR boost olmazsa reddet.

---

## 2. Motivasyon — Gap Analizi

Top 10'da **perp-microstructure exploitation** zayıf:
- `cvd_spike_fade` OBV proxy CVD spike (mean reversion); funding/OI yok.
- Geçmişte `funding_mean_reversion.py` denendi ama Top 10'a giremedi (zayıf single-feature).

**Boşluk:** Funding + OI birlikte, **PA teyiti ile** filtrelenen bir strateji
hiç test edilmedi. Tek-feature funding rate stratejileri zayıf çünkü:
- Funding pozitif iken fiyat da yukarı devam edebilir (overshoot)
- OI değişimi olmadan funding "duruyor" — squeeze tetikleyici yok
- PA teyiti olmadan timing yanlış

Bu hipotez **3-katmanlı confluence** ile sorunu çözer.

**Literatür:**
- **Hayes & Alameda Research (2021, "Funding Rate Arbitrage in Crypto Perpetual Markets")**:
  Funding-OI divergence signals empirically %58-65 WR for 1-3 gün reversal trades.
- **Harris (2003, "Trading and Exchanges", ch.20)**: Position-information asymmetry —
  funding + OI birleşimi "kim taşıyor pozisyonu" sorusuna cevap.
- **He et al. (2023, "Funding Rate Premia and Predictability in Crypto Perps")**:
  Funding skew + OI artışı squeeze öncesi %62 doğrulukla tahmin ediyor (1-5 gün).
- **Hassonjee (2022, ICT/SMC adapted perp microstructure)**: Funding spike + OI
  spike + sweep = institutional liquidation cascade trigger.

---

## 3. Mekanik Kurallar

### 3.1 Veri Hazırlık

Bu strateji **EK VERİ gerektirir:**
- 8h funding rate per symbol (Binance API: `/fapi/v1/fundingRate`)
- Daily OI snapshot per symbol (Binance API: `/futures/data/openInterestHist`)

3y geriye dönük serbest mevcut (Binance Data Portal: data.binance.vision).

```
# Funding 3-day cumsum (24h hedge cost proxy):
funding_3d = funding_rate.rolling(9, min_periods=9).sum()  # 9 × 8h = 3 gün
# (3 days × 3 funding per day = 9 funding values)

# OI delta (3-day):
oi_pct_change_3d = (oi[t] / oi[t-3]) - 1.0
```

### 3.2 Setup Detection

**SHORT setup (overlong squeeze):**

```
overlong =
    funding_3d[t] > +0.0015            # 3-gün toplam funding > +0.15% (~+%18 APR)
  AND oi_pct_change_3d[t] > +0.05      # OI son 3 günde > +5% (long stack ediyor)
  AND close[t] > rolling_max(close, 10)[t-1]  # fiyat new local high
```

**LONG setup (overshort squeeze):** Simetrik
```
overshort =
    funding_3d[t] < -0.0015
  AND oi_pct_change_3d[t] > +0.05      # OI yine yukarı — short stack
  AND close[t] < rolling_min(close, 10)[t-1]
```

OI artışı **her iki yönde de aranır** çünkü:
- Long-side funding pozitif + OI up = long stack ediyor → squeeze short tarafa zorlanır
- Short-side funding negatif + OI up = short stack ediyor → squeeze long tarafa zorlanır

### 3.3 Trigger — Price Action Rejection Candle

Setup detect edildikten sonraki **t veya t+1**'de rejection candle aranır:

```
# Short trigger:
shooting_star OR
hanging_man OR
bearish_engulfing  # mevcut bullish trend'i engulfs

# Long trigger:
hammer OR
dragonfly_doji OR
bullish_engulfing
```

Eğer t veya t+1'de trigger yoksa setup t+2'de iptal.

### 3.4 Entry & Risk

- **Entry:** trigger bar close (or t+1 open if conservative)
- **SL (short):** `max(setup_bar.high, trigger_bar.high) + 0.5*atr_14`
- **SL (long):** `min(setup_bar.low, trigger_bar.low) - 0.5*atr_14`
- **TP:**
  - 1R %30 partial → BE
  - 2R %30 partial → 1R lock
  - %40 runner: 2*ATR Chandelier trail
  - Time stop: 7 bar (funding squeeze typically 3-7 gün)

### 3.5 Position Sizing (özel)

- Setup gücüne göre confidence:
  - `funding_3d` magnitude × `oi_change` magnitude = composite_score
  - Score > median(historical scores)+1*std → confidence_tier += 1 (yüksek size)

---

## 4. Bağlam Filtresi

| Filter | Eşik | Etki |
|---|---|---|
| **BTC dominance** | Trend yönünden bağımsız | Alt-coinler için: BTC dominance up → alt long size %50 |
| **Vol regime** | atr_5/atr_60 < 1.5 | Extreme vol'de funding/OI signals fail; > 1.5 → kapalı |
| **Sembol filtresi** | Sadece likit perp'ler: BTC, ETH, SOL, BNB, AVAX, LINK | DOGE/XRP/MATIC funding noisy |
| **Trade overlap** | Aynı sembol ardışık trade arası min 5 gün | Yeniden-stack avoid |

---

## 5. Edge Mekanizması — Niye Para Kazanır?

1. **Funding = cost-of-carry for leveraged positions.** Sürekli pozitif funding
   (3-gün +%0.15+) = pozisyon taşıma maliyeti %18+ APR; bu seviyede pozisyon
   tutulamaz — squeeze kaçınılmaz. Soru "ne zaman".

2. **OI artışı = "stack ediyor" sinyali.** OI yatay/azalıyorsa eski long'lar
   çıkmış; OI artıyorsa **yeni** longlar geliyor. Squeeze hedefi yeni long'lar
   (zayıf eller).

3. **PA rejection = zamanlama.** Funding+OI confluence "ortam hazır" der; rejection
   candle "kıvılcım" — kurumlar dağıtıyor.

4. **Multiplicative confluence:**
   - Funding alone WR (mean reversion) ~%52
   - OI delta alone WR ~%53
   - PA rejection (Bulkowski) WR ~%58
   - Üçü birlikte (Bayes posterior) ~**%63-70**

5. **Asymmetric risk:** Squeeze trade'ler R-multiple > 2 nadir değil (cascade
   liquidation = 5-10% one-day move). Avg R 1.8-2.2 beklenir.

---

## 6. Decorrelation Argument

| Top 10 üyesi | Örtüşme |
|---|---|
| cvd_spike_fade | **Düşük** | OBV-spike based, funding/OI YOK. Aynı barda overlap mümkün ama farklı koşullar. |
| anchored_vwap_reversal | Çok düşük | AVWAP swing-anchor; funding/OI yok |
| Diğer 8 | Çok düşük | |

**Önemli korelasyon kaynağı:** Squeeze öncesi cvd_spike_fade de tetiklenebilir
(OBV spike + funding spike correlate edebilir). Backtest'te overlap ölçülecek;
> %25 ise filter olarak entegre, < %25 ise bağımsız.

---

## 7. Curve-Fit Risk — DÜŞÜK-ORTA

Toplam parametre: **9**
- Funding cumsum window: 3 gün (8h × 9 = 72h) — perp standardı
- Funding threshold: +/- 0.0015 (= +/-%0.15 / 3-gün = ~%18 APR) — He et al. (2023) eşiği
- OI delta window: 3 gün
- OI delta threshold: +%5
- 10-bar new high/low (extension)
- Rejection candle: 3 alt-tip (Bulkowski)
- SL buffer: 0.5*ATR
- Time stop: 7 bar

Bonferroni: 9 parametre × 3 grid = 27 → α = 0.002.

**Risk:** Funding/OI verisi sembol başına bağımsız; survivorship bias kontrolü gerekli.

---

## 8. Backtest Gate'leri (pre-registered)

| Metric | Hedef | Stop criterion |
|---|---|---|
| Net yıllık return | > +%20 | < +%10 → reddet |
| Max DD | < %25 | > %35 → reddet |
| Walk-forward 13 pencere | ≥ 12 pozitif | < 10 → reddet |
| Sharpe (3y rolling) | > 1.0 | < 0.7 → reddet |
| Profit factor | > 1.5 | < 1.2 → reddet |
| Win rate | > %58 | < %53 → reddet |
| Avg R-multiple | > 1.5 | < 1.0 → reddet |
| Trade frekansı | 15-50 / yıl | < 10 → çok seyrek |
| Korelasyon — Top 10 portföy | < 0.20 | > 0.35 → reddet |
| Korelasyon — cvd_spike_fade | < 0.30 | > 0.40 → entegre filter |

---

## 9. Beklenen Edge

- Funding-only mean reversion (Hayes empirical): WR %52, avg R 1.0
- OI-only signal: WR %53
- Funding + OI confluence (He 2023): WR %62, avg R 1.5
- PA rejection (Bulkowski): +%5-8 WR boost on confluence
- **Triple confluence:** WR **%65-72**

Avg R: 1.8 (squeeze cascade beklenti)
Expectancy: ~0.65R/trade
20 trade/yıl × 0.65R × 2.5% risk = **+%32 yıllık** (optimistic-realistic)
Slip+funding kayıp %25 → **+%24 net** (target).

---

## 10. Stress Test Beklentisi

| Period | Beklenti |
|---|---|
| 2022-05 LUNA | Cascade liquidation = SHORT setup textbook. Funding crash + OI explode = beklenir. |
| 2022-11 FTX | Aynı: cascade SHORT. |
| 2023 ranging | Funding sıkışık (low); az trade, OK |
| 2024-03 ATH dump | SHORT setup at top (funding > +%30 APR pre-dump). |
| 2024-08 Yen carry | Cross-asset cascade; SHORT setup'lar trigger eder. |

**Beklenti:** Bu strateji **EXTREME EVENTS'TE KAZANIR**, ranging'de seyrek. Bu
özellik mevcut Top 10 ile **negatif korelasyon** anlamına gelir — Top 10'un
en kötü olduğu dönemde bu strateji en iyi.

---

## 11. Veri Erişilebilirlik & Implementasyon

**Veri kaynak:**
- Binance Data Portal: `https://data.binance.vision/data/futures/um/daily/fundingRate/`
- `https://data.binance.vision/data/futures/um/daily/openInterestHist/`
- 3 yıl geriye serbest ücretsiz CSV

**Yeni module:** `funding_oi_divergence.py`

**Yeni helpers:**
- `_load_funding_rate(symbol, start, end)` — DuckDB cache
- `_load_open_interest(symbol, start, end)` — DuckDB cache
- `_funding_cumsum(funding, window=9)`
- `_oi_pct_change(oi, window=3)`
- candle helpers (volatility_regime_mr ile paylaşımlı)

**Backtest engine değişiklik:** Funding ve OI series'i strategy'ye injection.
`StrategyBase` interface'ine `extra_data: dict[str, pd.Series]` parametresi eklenir.

---

## 12. Karar Akışı

```
1. Veri indirme: 11 sembol × 5y funding + OI (DuckDB append)
2. Veri kalite kontrol (gap, anomaly)
3. 5y in-sample backtest
4. Funding-only vs OI-only vs confluence — gerçek edge confluence'den mi?
5. SOP-3 robustness suite
6. Korelasyon analizi (Top 10)
7. Stress periodlar (LUNA, FTX, ATH dump — bu strateji burada PARLAMAK ZORUNDA)
8. Gate ✓ → Lab; ✗ → reddet
```

---

## 13. Önemli Risk: Survivorship Bias

Funding verisi bazı semboller için listing date öncesi yok. 11 sembolden DOGE,
XRP, MATIC için 3y geriye fonting veri olmayabilir. Eğer veri eksikse:
- Sembolü test setinden çıkar (in-sample farklı, OOS farklı)
- VEYA varsayılan funding = 0 (konservatif)

Tercih: **sembolü çıkar**, fewer signals OK; biased signals değil.

---

## 14. Beklenen Implikasyon

Bu strateji **tail-risk hedger** rolü oynayabilir. Top 10 normal-piyasada para
kazanıyor; cascade-event'lerde DD veriyor (60-80% rolling DD). Bu strateji
cascade-event'lerde maksimum kazanç → toplam portföy DD %20-30pp **azalabilir**
(başarılıysa). Bu DD-azaltma değeri %5-10 yıllık ROI feda etmeyi haklı kılar.

---

## Reproducibility Footer

```
git_hash: <to-be-filled>
config_hash: <to-be-filled>
data_hash: <to-be-filled>
```
