---
name: hyp-2026-05-14-inside-day-failure
description: Tom Dante Inside Day Failure — Bar t-1 = Inside Day. Bar t low < ID_low (false breakdown) AND close > ID_low (reclaim). LONG; mirror SHORT.
metadata: { type: hypothesis, status: pre-registered, author: researcher, date: 2026-05-14, sprint: sec19 }
---

# HYP-2026-05-14-INSIDE-DAY-FAILURE (IDF)

## Kaynak (RAG / literatür)

- Tom Dante (@Trader_Dante) X post: "Inside Day Failure: break below ID low close back above low, sets up target of other side of ID. The pattern is only 'valid' at end of day but can be pre-empted during the day with a good setup." https://x.com/Trader_Dante/status/1045012059627442176 (accessed 2026-05-14)
- Notes on Trading using Tom Dante's teachings — philoinvestor.com: SFP (swing failure pattern) parent concept; IDF is structural inside-day version.
- Adam Grimes "The Failure Test" — adamhgrimes.com — same logic: price ticks beyond known S/R (here Inside Day high/low) and reverses on same bar; "best entry the simplest — short on bar close with stop above the high". https://www.adamhgrimes.com/failure-test-2/
- Brooks "Trading Price Action Reversals" — failed breakouts as the dominant edge in range-bound markets.

## Hipotez (pre-registered)

**Iddia:** 1D crypto'da, Inside Day Failure (ID + sonraki barda false break + reclaim) tetiklenen bar-sembol kombolarında, **R-multiple beklenen değer > +0.15** ile edge sağlar. Mevcut `ii_breakout` (Inside-of-Inside breakout) ile **structural olarak TERSI** (breakout değil, fail) → ensemble'da uncorrelated.

**Null hipotez:** IDF, random entry'den anlamlı edge sağlamaz (mR ≤ +0.10 VEYA shuffle p ≥ 0.10).

## Mekanik kurallar (vektörize)

**Bar t-1 = Inside Day:**
- high[t-1] < high[t-2] AND low[t-1] > low[t-2]
- ID_high = high[t-1], ID_low = low[t-1]
- ID_range = ID_high - ID_low

**Bullish IDF (LONG, false breakdown reclaim):**
- low[t] < ID_low (false breakdown ticks below ID low)
- close[t] > ID_low (reclaim — close above ID low)
- close[t] > open[t] (bullish bar body — extra confirmation; alternatif: close > (high+low)/2 mid-bar)
- |close[t] - open[t]| / (high[t] - low[t]) > 0.30 (rejection bar, not doji)

**Bearish IDF (SHORT, mirror):**
- high[t] > ID_high (false breakout above ID high)
- close[t] < ID_high (reclaim)
- close[t] < open[t] (bearish body)
- |close[t] - open[t]| / (high[t] - low[t]) > 0.30

**Entry / exits:**
- Entry: bar t+1 open
- SL:
  - LONG: low[t] - 0.25 × ATR(14)  (or ID_low - 0.5 × ATR if low[t] very close to ID_low)
  - SHORT: high[t] + 0.25 × ATR(14)
- TP1: ID range opposite side → for LONG: ID_high; for SHORT: ID_low — close 50% there
- TP2: 2.0R fixed → close 30%
- Runner: 20%, trail engine default

**Filtreler:**
- ATR(14) / close ≥ 0.5% (regime gate)
- ID_range / ATR(14) ≤ 1.5 (ID gerçekten dar olmalı — geniş ID = mevcut volatilite, failure anlamlı değil)
- Trend filter (SOFT, opsiyonel parametre):
  - LONG: close[t] > EMA50[t] (LONG only in uptrend) — test ON/OFF
  - SHORT: close[t] < EMA50[t]
- Cooldown: same symbol same direction 5 bar

**Lookahead-free:**
- ID tespiti bar t-1'de tamamen biliniyor (t-2 ve t-1 kapanış)
- Failure trigger bar t close ile değerlendirilir
- Entry t+1 open

## Beklenen edge

- Standalone mR: +0.10 ile +0.25 arası (Adam Grimes "failure tests require larger losses on subset" - 1.5R primary TP kontrolü).
  - WR ~%50 + 1.5R / -1.0R = mR ≈ +0.25
- n_trade tahmini: 5y × 11 sym × ~25 IDF/yıl/sym ≈ 1400 trade. Filtre sonrası 400-700. Bol n.
- Ensemble katkı: orta-yüksek (mevcut II breakout tersi, mevcut Brooks failed BO 10-bar kapsamından farklı bar-count → orthogonal trigger zaman)

## Fail kriterleri

**HARD (anyone → RED):**
1. n_trade < 50
2. WR ≤ 0.35
3. mR ≤ +0.10
4. shuffle p ≥ 0.10
5. WF negatif pencere > 4

**SOFT (≥2 fail → RED-conditional):**
1. Symbol-out CV mean dev > 25%
2. Trend filter ON/OFF arası mR farkı: eğer SADECE ON varyantı pozitif AND ensemble null → trend filter mandatory yapılsın
3. IS/OOS Sharpe drop > %50
4. Ensemble retest delta < 0pp

## Test planı

1. `src/price_action/strategies/inside_day_failure.py`
2. Standalone gather 5y × 11 sym
3. 3 varyant test:
   - V1: base (no trend filter)
   - V2: trend filter ON (LONG only > EMA50, SHORT only < EMA50)
   - V3: tight body ratio 0.50 (daha seçici rejection)
4. Edge gate (her varyant)
5. En iyi varyant ile WF 3y rolling 13 pencere
6. Robustness: ATR mult {0.15, 0.25, 0.40}; body ratio {0.20, 0.30, 0.50}; trend ON/OFF
7. Symbol-out CV (11 sym)
8. Multiple testing: Bonferroni 3 candidate × 3 varyant = 9 test; alpha 0.05/9 ≈ 0.0056

## Beklenen sonuç olasılığı

- Standalone PASS: ~%65 (PA community + Brooks failure test güçlü prior, n bol)
- Ensemble PASS (delta yıllık > +%2pp veya r-adj > +0.05): ~%30 (slot bottleneck yüksek — sık tetikler, mevcut günlere denk gelme olasılığı yüksek)
- Final aday production: ~%20

**Yapısal risk:** Çok sık tetikleyen → conf-tier sızıntısı + slot kapma. Mitigation: trend filter ON ile %50 azalır, alt-koz olarak conf-tier integration.
