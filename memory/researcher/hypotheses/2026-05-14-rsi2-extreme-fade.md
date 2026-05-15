---
name: hyp-2026-05-14-rsi2-extreme-fade
description: Connors 2-period RSI extreme + 200-EMA trend filter + 5d-low fade. Mean-reversion. LONG only when oversold in uptrend, SHORT only when overbought in downtrend.
metadata: { type: hypothesis, status: red-oos-selection-bias, author: researcher, date: 2026-05-14, sprint: sec22+sec23, class: mean_reversion, decision: archive }
---

# HYP-2026-05-14-RSI2-EXTREME-FADE

## Kaynak (RAG / literatür)

- Larry Connors & Cesar Alvarez — "Short Term Trading Strategies That Work" (2008). 2-period RSI extreme readings tested across 7000+ stock backtests; classic edge.
- [QuantifiedStrategies — RSI Trading Strategy (91% WR backtest)](https://www.quantifiedstrategies.com/rsi-trading-strategy/) — RSI(2) < 10 with trend filter long edges documented across SPY/QQQ/sector ETFs.
- [Kraken Learn — RSI Divergences](https://www.kraken.com/learn/rsi-divergences-what-they-how-they-work) — extreme RSI readings (>85 / <25) "almost always precede at least a short-term reversal" on daily timeframe.
- [altFINS — Trading RSI and RSI Divergence](https://altfins.com/knowledge-base/trading-rsi-and-rsi-divergence/) — RSI extreme reliability on higher timeframes daily+.

## Hipotez (pre-registered)

**İddia:** 1D crypto'da, 2-period RSI extreme (RSI(2)<10 in uptrend / RSI(2)>90 in downtrend) tetiklediği bar-sembol kombolarında, mean-reversion R-multiple beklenen değeri **mR > +0.15** ile edge sağlar; mevcut mean-rev havuzundan (FVG/AVWAP/IDF/POC) **uncorrelated** çünkü oscillator-based momentum extreme yaklaşımı yapısal olarak farklı.

**Null:** mR ≤ +0.10 VEYA shuffle p ≥ 0.05 → edge anlamsız.

## Mekanik kurallar (vektörize)

**Common indicators (lookahead-free):**
- `RSI2 = pandas_ta.rsi(close, length=2)` (Wilder)
- `EMA200 = close.ewm(span=200, adjust=False).mean()` — long-term trend bias
- `LL5 = close.rolling(5, min_periods=5).min().shift(1)` — last 5 day low (excluding today)
- `HH5 = close.rolling(5, min_periods=5).max().shift(1)` — last 5 day high
- `ATR14 = _atr(df, 14)`

**Bullish RSI2 Fade (LONG):**
- `close[t] > EMA200[t]` (uptrend regime)
- `RSI2[t] < 10` (extreme oversold)
- `close[t] < LL5[t]` (close below 5d low — pulled into deep dip)
- ATR%(14) ≥ 0.5% (regime gate)
- Cooldown same direction 5 bar

**Bearish RSI2 Fade (SHORT, mirror):**
- `close[t] < EMA200[t]`
- `RSI2[t] > 90`
- `close[t] > HH5[t]`
- ATR%(14) ≥ 0.5%

**Entry / exits:**
- Entry: bar t+1 open (decision_after_close=True engine convention)
- SL:
  - LONG: low[t] - 1.0 × ATR(14)
  - SHORT: high[t] + 1.0 × ATR(14)
- TP1: EMA10 (close → reversion target) — partial 50%
- TP2: 2.0R primary — partial 30%
- Runner: 20%, engine default trail (force_exit_bars=30 sufficient — mean-rev fast)

## Beklenen edge

- Standalone mR: +0.15 ile +0.30 arası — Connors equity backtests +0.20-0.35.
  Crypto'da daha geniş tail (high vol) → ATR-normalize SL ile mR korunmalı.
- n tahmini: 5y × 11 sym × ~25 RSI2<10 olayı/yıl ≈ 1375 raw. EMA200 filtre + 5d-low ek koşul %60-70 azaltır → 400-600 net trade. Yeterli.
- Mevcut mean-rev'lerden uncorrelated: oscillator extreme tetik bar-bazlı, FVG/AVWAP/POC mıknatıs setup, IDF Inside-Day yapısal — overlap minimum.

## Fail kriterleri

**HARD (anyone → RED):**
1. n_trade < 150
2. WR ≤ 0.35
3. mR ≤ +0.10
4. shuffle p ≥ 0.05
5. max_R ≥ 10 (fantasy artifact suspect)

**SOFT (≥2 fail → RED-conditional):**
1. Symbol-out CV mean dev > 30%
2. Long/Short asymmetry > 3x mR (one-sided bias = regime overfit risk)
3. Median R çok negatif (-0.5+) + max_R yüksek = unstable distribution
4. Hold time dist median > 20 bar (mean-rev fast olmali, slow hold = artifact)

## Test planı

1. `src/price_action/strategies/rsi2_extreme_fade.py` (vektörize)
2. Standalone gather 5y × 11 sym
3. Edge gate check
4. Robustness:
   - RSI2 threshold {5, 10, 15} (loose-tight)
   - EMA span {150, 200, 300}
   - 5d-low requirement ON/OFF
5. Shuffle baseline 200 perm sign-flip
6. Hold time + median R audit (artifact paranoia)
7. **NO ensemble retest** — Engineering SEC21 sonrası ayrı sprint

## Beklenen sonuç olasılığı

- Standalone PASS: ~%55 (Connors edge equity strong, crypto adaptation belirsiz)
- Ensemble PASS (delta yıllık +%2pp veya r-adj +0.05): %25 (slot bottleneck halen kuvvetli ama Engineering slot fix sonrası %40'a çıkabilir)
- Final aday production: ~%15

**Yapısal risk:** Mean-reversion stratejileri 2021-2024 crypto bull-cycle dominant trend rejimlerinde performansı düşük olabilir. EMA200 trend filtresi bunu kısmen azaltır ama short-side için 2022 bear regime mR boost gerekli.

## STRATEGY_CLASS

```python
STRATEGY_CLASS = 'mean_reversion'  # Engineering SEC21 taxonomy
```

---

## POSTMORTEM — SEC23 OOS Validation (2026-05-14)

**Karar: RED — KALICI ARCHIVE.**

| Sprint | Window | Config | n | mR | p_shuffle | Gate |
|---|---|---|---:|---:|---:|---|
| SEC22 IS | 2021-05 → 2026-05 (full 5y) | rsi=5 ema=150 lb=3 (best of 27 grid) | 356 | +0.144 | 0.045 | PASS-MARGINAL |
| **SEC23 OOS** | **2024-01 → 2025-05 (1.5y hold-out)** | **same selected config** | **118** | **+0.050** | **0.363** | **RED 3/6 FAIL** |

**HARD gate fails:**
- mR=+0.050 < +0.10 (gate)
- p=0.363 >> 0.05 (naive gate)
- p=0.363 >> 0.00185 (Bonferroni α=0.05/27)

**HARD gate passes:**
- n=118 ≥ 100 (proportional ~107 üstü)
- WR=44.1% ≥ 42%
- max_R=5.25 < 10 (artifact temizliği iyi)

**27-config grid OOS rank:** SELECTED config #5/27. Top 3 (rsi=5/ema=200 cluster) bile naive p<0.05 gate'i geçemedi (en iyi p=0.30).

**Selection bias yapısı doğrulandı:** IS'de "best of 27" -> OOS'ta orta sıralarda + tüm grid OOS'ta ölü. Edge %65 çöktü, p-value 8x kötüleşti.

**Falsifikasyon zinciri (çift kapı):**
1. SEC23 OOS RED
2. SEC21 slot bottleneck FALSIFIED (per-strategy slot allocation -%5pp) -> ensemble retest gerekçesi de yok

**Aksiyon:**
- Strategy dosyası silinmedi (test koruma) ama `configs/strategy_taxonomy.yaml` içinde `disabled_strategies` listesine eklenecek (Engineering koordinasyon)
- Ensemble retest sprint **iptal**
- Mean-reversion class araştırması için yön: regime-conditional setup (BTC.D / vol regime overlay) — ayrı hipotez gerekli

**Referans:** `reports/researcher/2026-05-14_sec23_rsi2_oos_validation.md`, `scripts/sec23_rsi2_oos.py`, `reports/researcher/sec23_rsi2_oos.json`.

**Methodological lesson:** 27 nominal config -> 9 effective (lb={3,5,7} OOS'ta identical, RSI<5 filter dar). Bonferroni effective=0.05/9=0.0056 (yine fail). Gelecek grid tasarımı için **effective dimensionality** ölç (unique-result count veya Spearman rank).
