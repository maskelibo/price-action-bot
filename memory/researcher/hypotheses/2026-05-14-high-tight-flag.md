---
name: hyp-2026-05-14-high-tight-flag
description: O'Neil/Weinstein High-Tight Flag — parabolik pole (~60%+ in 4-8 weeks) ardından dar consol (≤25% pullback in 3-5 weeks) + flag-high breakout LONG.
metadata: { type: hypothesis, status: pre-registered, author: researcher, date: 2026-05-14, sprint: sec19 }
---

# HYP-2026-05-14-HIGH-TIGHT-FLAG (HTF)

## Kaynak (RAG / literatür)

- TraderLion: "What Is The High Tight Flag Chart Pattern?" — O'Neil definition: stock surges 100%+ in 4-8 weeks; consolidates with ≤25% pullback over 3-5 weeks; breakout = flag high. Highest-success momentum continuation pattern (cited ~74-83% follow-through). https://traderlion.com/technical-analysis/high-tight-flag-pattern/ (accessed 2026-05-14)
- Bulkowski Encyclopedia of Chart Patterns: HTF rank #1 of 23 chart patterns for performance; meeting price target rate ~83% for bullish HTF. https://thepatternsite.com/htf.html
- Nasdaq/IBD coverage 2024-25: HTF cited as "rarest and most powerful" growth stock pattern. https://www.nasdaq.com/articles/unlock-momentum-rare-powerful-high-tight-flag-pattern
- Crypto specific: Bitcoinist 2024 cites DOGE HTF formation; Binance Research Expert 2024 same. Crypto'da alt-coin parabolik dönemler doğal HTF konteyneri.

## Hipotez (pre-registered)

**Iddia:** 1D crypto'da, HTF kuralları (pole + tight flag + breakout) tetiklenen sembol-bar kombolarında, **LONG R-multiple beklenen değer > +0.30** ile edge sağlar. Crypto'nun parabolik alt-coin episode'ları (DOGE 2021, SOL 2021, MATIC 2021, AVAX 2021 vb.) için O'Neil/Bulkowski tarihsel %83 follow-through rate'i en az kısmen replike olur (alt-coin'in pull-back genelde DAHA AGRESIF olacağı için pullback %25 eşiğini gevşetmek gerekebilir).

**Null hipotez:** HTF, random entry'den üstün edge sağlamaz (mR ≤ +0.10 VEYA n < 30 VEYA shuffle p ≥ 0.10).

## Mekanik kurallar (vektörize)

**Adım 1 — Pole detection (bar t'de):**
- `pole_window_days = 35` (5-8 hafta arasının orta noktası, 5w=35d) — daha geniş test variantı 28/42
- pole_low = lowest_low over [t-pole_window, t-flag_window]
- pole_high = highest_high over same window
- pole_return = (pole_high - pole_low) / pole_low
- **Şart: pole_return ≥ 0.60** (60%+ pole — crypto adapted, O'Neil orijinal 100%+ stocks için)
- pole_high_idx = argmax of high in pole_window

**Adım 2 — Flag consol detection (bar t'de):**
- `flag_window_days = 21` (3 hafta)
- flag bars = [pole_high_idx, t] (pole high'tan bar t'ye)
- flag_len = t - pole_high_idx
- **Şart: 14 ≤ flag_len ≤ 35** (2-5 hafta consol)
- flag_low = min(low over [pole_high_idx, t-1])
- flag_pullback = (pole_high - flag_low) / pole_high
- **Şart: 0.05 ≤ flag_pullback ≤ 0.30** (alt-coin için %25→%30 gevşek, ama %5 altı = consol yok)
- flag_range_atr_ratio = (max(high over flag) - min(low over flag)) / ATR(14, at t)
- **Şart: flag_range_atr_ratio ≤ 5.0** (consol tight — geniş range = consol değil, devam eden trend)

**Adım 3 — Breakout trigger (bar t):**
- close[t] > pole_high × 0.995 (≤0.5% margin) — flag high'ı kırdı, equal-or-above
- AND volume[t] > vol_z 60-bar median × 1.3 (volume confirmation)

**Setup PASS → LONG signal at bar t+1 open**
- SL: flag_low - 0.5 × ATR(14)
- TP1: 1.0R partial close 50%
- TP2: pole_high + (pole_high - flag_low) = "measured move" target (pole magnitude projected from breakout) → close 30%
- Runner: 20%, trail engine default (mult=1.5)
- Cooldown: same symbol same direction 14 bar (HTF sonrası retest sık olur ama gerçek HTF retrigger seyrektir)

**Filtreler:**
- BTC capitulation halt aktif değilse trade et (mevcut regime filter respected)
- ATR(14) / close > 1.0% (alt-coin parabolik dönemler doğal yüksek vol)
- Symbol universe: 11-sym (alt-coin dominant beklenir — BTC/ETH'te %60 pole zor)

**Lookahead-free:**
- Pole detection bar `t`'deki bilgi (geriye dönük lookback only)
- Flag pullback hesabı [pole_high_idx, t-1]'i kullanır (current bar dahil değil)
- Breakout şartı bar t close — entry bar t+1 open

## Beklenen edge

- Standalone mR: +0.30 ile +0.80 arası (measured move projection 2-3R, WR ~%50 → mR = 0.50×2.0 - 0.50×1.0 = +0.50)
- n_trade tahmini: 5y × 11 sym × ~3 HTF/yıl/sym (sadece parabolik dönem) ≈ 150 trade. Filtre sonrası 60-100. Eğer < 30 → HARD fail.
- WR ~50% gate kolay aşılır
- Ensemble katkı: yüksek potansiyel (uncorrelated trigger — sadece parabolik dönemler, mevcut TOP_10 trend-cont engulfing günlerinden FARKLI bar'larda)

## Fail kriterleri

**HARD (anyone → RED):**
1. n_trade < 30 (yetersiz örneklem — pattern doğal seyrek)
2. WR ≤ 0.40
3. mR ≤ +0.10
4. shuffle p ≥ 0.10
5. WF 3y rolling negatif pencere > 4

**SOFT (≥2 fail → RED-conditional):**
1. Symbol concentration > %60 tek sembol (e.g., DOGE'a aşırı bağımlı)
2. Regime split: bull/range/bear'da yalnız bull'da pozitif (regime-sensitive)
3. IS/OOS Sharpe drop > %50
4. Ensemble retest ROI delta < +%1pp

## Test planı

1. `src/price_action/strategies/high_tight_flag.py`
2. Standalone gather 5y × 11 sym
3. Edge gate
4. WF 3y rolling 13 pencere
5. Robustness: pole_window {28, 35, 42}; pole_return {0.50, 0.60, 0.75}; flag_pullback {0.20, 0.25, 0.30}; (3³=27 grid, FDR Benjamini-Hochberg q=0.10)
6. Symbol-out CV (11 sym)
7. Regime split

## Beklenen sonuç olasılığı

- Standalone PASS: ~%65 (Bulkowski rank #1 chart pattern strong prior; crypto alt-coin natural fit)
- Ensemble PASS: ~%50 (slot bottleneck en düşük — seyrek trigger uncorrelated)
- Final aday production: ~%40

**Yapısal risk:** Crypto 2021 alt-coin parabolic season tek-defa-event; 2022-2024 bear dönem aynı pattern üretmez. Sample bias 2021'e doğru olabilir → regime split'te 2022-23 'de NEG pencereler kabul edilebilir SOFT bound.
