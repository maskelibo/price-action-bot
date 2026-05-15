---
hypothesis_id: HYP-2026-05-14-BROOKS-DB-BULL-FLAG
date: 2026-05-14
author: researcher_agent
status: pre-registered
parent_strategy: pure-new
class: trend_continuation
tags: [brooks, double_bottom, bull_flag, double_top, bear_flag, trend_continuation, 1d, crypto]
sprint: SEC25
---

# Hipotez: Brooks Double Bottom Bull Flag / Double Top Bear Flag

## Motivasyon

PA mastery gap envanterinde Brooks 10-best PA patterns listesinden:

> **#4 Brooks (10-best) — Double Bottom Bull Flag / Double Top Bear Flag — trend_continuation — NOT_TESTED**

Brooks'un "10 Best Price Action Patterns" listesinde **Double Bottom Bull Flag**, en yüksek win-rate
sınıflandırılan reversal-into-continuation pattern olarak yer alır:

> "A double bottom bull flag is one of the most reliable bull setups. It usually
> forms in a bull leg as a 2-3 bar pullback, and the second leg down forms a
> double bottom with the first leg. The flag breakout triggers a measured move
> equal to the prior swing." — Brooks Trading Course

SEC22-24 mean-reversion class 4 art arda RED (TS, BB, three-push, rsi2 OOS) sonrası
Bayesian prior **mean-rev family DEFAULT FAIL crypto'da** olarak güncellendi
(memory: pattern crypto mean-rev continuation insight). **Trend-continuation prior
karşı kontrol** olarak DB Bull Flag yüksek-EV — Brooks classics, crypto bull/swing
dynamics ile yapısal uyumlu.

## Hipotez Özeti (pre-registered)

**Bullish Double Bottom Bull Flag (LONG):**

1. **Swing low #1:** Bar t-K (K ∈ [10, 40]) fractal swing low (n=2).
2. **Swing low #2:** Bar t-J (J ∈ [3, 12]) **ikinci swing low** (n=2) — swing #1
   ile fiyat farkı |L1 - L2| / L1 < 0.03 (3% within range, yani "double bottom").
3. **Recovery:** L2'den sonra fiyat L1+L2 high (intermediate pivot M) üzerine
   çıkmış. Bu M-pivot = "neckline".
4. **Tight flag (consolidation):** Son C bar [t-C, t] içinde range (highest_high -
   lowest_low) / atr14 < 4.0 (tight consolidation, max 4×ATR rangewithin C bars,
   C ∈ [3, 8]). Closes flag içinde, neckline üzerinde (M < lowest close in flag).
5. **Trend filter:** close[t] > EMA50[t] (long-term bias bullish).
6. **Breakout trigger:** Bar t kapanışı flag high'ı (rolling C-bar high shift(1))
   üzerine kapanmalı. Bar t bullish (close > open) ve body_ratio ≥ 0.40.

**Entry (LONG):** Bar t+1 açılışı.
**SL (LONG):** L2 (ikinci dip) - 0.5 × ATR14[t].
**TP (LONG):** Brooks measured move = entry + (M - L_avg) × 1.0 (mantar boyu kadar).
              Floor: entry + 2.0R (R = entry - SL).

**Bearish Double Top Bear Flag (SHORT, ayna):**
- Swing high #1, swing high #2 |H1-H2|/H1 < 0.03 → double top
- M = intermediate pivot low
- Tight flag (range tight, closes flag içinde, neckline altında)
- Trend filter: close < EMA50
- Breakout: bar t kapanışı flag low (C-bar rolling low shift(1)) altında, bearish
  body ratio ≥ 0.40
- Entry: bar t+1 açılış SHORT
- SL: H2 + 0.5×ATR
- TP: measured move (H_avg - M), floor 2R

## Gerekçe (literatür, RAG)

- **Brooks (Trading Price Action Trends, 2012, Ch 6, "Double Bottoms & Tops"):**
  "A double bottom is two lows that are approximately equal but separated by a
  small rally. When the second low fails to make a new low, this is a high-probability
  buy setup."
- **Brooks Trading Course "10 Best PA Patterns":** Double bottom bull flag listed
  as #1 most reliable bullish reversal pattern with measured move target.
- **Bulkowski (Encyclopedia of Chart Patterns, 2nd ed., ch 19):** Double bottom
  win rate ~62-70% in equity markets, measured move target hit rate ~58%.
- **Adam Grimes (Art and Science 2012, Ch7):** Two-legged pullback in trend is
  Wyckoff "spring" + Brooks "L2 in bull microchannel" eşdeğer mekanik.
- **Wyckoff (Phase D LPS):** Double bottom + breakout = LPS markup başlangıcı.

**Crypto-uyumlu microstructure argüman (literatür autorite bias guard):**

Crypto'da DB pattern stocks/FX'tekinden FARKLI olabilir mi?
- **Pro:** Crypto 24/7 trade + perp leverage cascade'leri "panic dip + rapid
  recovery" yapar — DB doğal oluşum. BTC swing'leri (2022-Q3 LUNA bottom test, 2023
  Q4 ETH double-bottom, 2024-Q4 SOL DB) gözle görülür.
- **Risk:** SEC22-24 zinciri klasik mean-rev pattern'lerin crypto'da continuation
  mekanik gösterdiğini doğruladı. DB **mean-rev değil** — DB **reversal-followed-by-
  continuation**, ikinci leg breakout trend-following sonuç verir. Trend filter
  (EMA50) ve flag tight consolidation gate'leri "saf reversal değil, breakout
  konfirmasyonlu trend-cont" filtreleme yapar. Crypto-fit pozitif beklenti.

## Hard Gates (pre-registered, anyone FAIL → RED)

| Gate | Threshold | Açıklama |
|---|---:|---|
| n_min | ≥ 200 | Standalone örnek yeterli |
| WR_min | ≥ 0.45 | Brooks/Bulkowski literatür alt-band |
| mR_min | ≥ +0.10 | Edge sınır gate-borderline |
| p_shuffle | < 0.05 | Null sign-flip permutation 2000-perm |
| max_R | < 10 | Artifact filter (honest clip hold>60d) |
| per_sym_pos | ≥ 6 / 11 | Cross-symbol robustness |
| symout_dev | < 30% | Leave-one-out CV stability |

**Bonferroni-aware parametre sweep:** Eğer grid sweep k ≥ 10 config ise
**Bonferroni α=0.05/k** uygula (selection-bias guard, SEC22-23-24 doctrine).

**Honest R clip:** hold_d > 60 → R = min(R_raw, 1.0). SEC19 dataset-end
artifact dersi.

## Counter-Hypotheses (pre-registered)

1. **CH-1 (literatür replikasyon riski):** Brooks DB Bull Flag stocks 30 yıl
   edge ama crypto bear/range yıllarında "DB → continuation failure" oluşabilir
   (sec24 TS bull regime'de fade kaybetti paraleli). Crypto'da DB'nin failure
   modu yüksek olabilir → per-year split bul, en az 3 yıl pozitif olmalı.

2. **CH-2 (engulfing_continuation overlap):** Mevcut `engulfing_continuation`
   pullback to 20EMA + engulfing tetikleme yapar. DB Bull Flag flag-breakout +
   double-bottom struktur — TRIGGER ZAMANLARı engulfing'ten **farklı** olmalı.
   Trade-date jaccard < 0.20 hedef (orthogonality kanıtı). Aksi halde
   ensemble katkısı sıfır olur (slot bottleneck dersi).

3. **CH-3 (donchian_breakout overlap):** DB Bull Flag son aşaması range-high
   breakout — donchian breakout ile yapısal overlap olabilir. Jaccard < 0.30
   hedef.

4. **CH-4 (asymmetric edge):** Crypto secular bull regime'de long-DB > short-DT
   beklenir (long-bias). short_mR < long_mR yüksek ihtimal — eğer short_mR
   negatif AND long_mR < +0.05 → asymmetric edge yok, RED. Eğer long-only
   mR ≥ +0.15 AND short-only mR ≥ 0 → tek-yön production variant açık adaylığı
   olabilir (sec24 paralel).

5. **CH-5 (parametre fragility / overfitting):** Pre-set parametreler
   {K∈[10,40], J∈[3,12], C∈[3,8], rng_atr<4.0, body_ratio≥0.40, dist%<3} 6
   serbestik. 18-config grid sweep planı (K=[20,30] × J=[5,8] × C=[4,6] × rng=[3.0,4.0,5.0]
   ya da bunun reduced versiyonu) çalıştırılırsa Bonferroni α=0.05/k=0.05/18=0.00278.
   Selection bias guard: en iyi config'in identical neighborhood'unda alternatif
   config'ler de PASS olmalı (robust plateau check).

## Sonuçlar (boş — backtest sonrası doldurulacak)

- [ ] Standalone n, mR, WR, p_shuffle
- [ ] Per-symbol pozitif sayısı
- [ ] Symout CV max dev
- [ ] Per-year split
- [ ] Long vs Short breakdown
- [ ] Orthogonality (engulfing_continuation, donchian_breakout)
- [ ] Lookahead audit
- [ ] Final verdict: PASS / MARGINAL / RED

## Reproducibility

- **Strategy file:** `src/price_action/strategies/brooks_db_bull_flag.py`
- **Standalone script:** `scripts/sec25_brooks_db_bull_flag_standalone.py`
- **Pre-reg:** bu dosya
- Seed: 42 (numpy default_rng)
- Honest R clip rule: hold_d > 60 → R ≤ 1.0
- STRATEGY_CLASS = 'trend_continuation' (Engineering SEC21 taxonomy hook)

## Notlar

- Pattern detector vektörize edilecek (Brooks "always-in" subjective değil,
  fractal pivot + price-equality + range-tight + breakout-bar metrics objective).
- "Subjective trader pattern" recall'ı %30-50 olabilir (sec22 three-push paralel).
  False negatives kabul; false positives n_min ile filtre.
- Bu bir **single-aday** sprint (paralel Adam Grimes ABC pre-reg sadece kayıt,
  backtest backlog).

## Sources

- [Brooks Trading Course — 10 Best PA Patterns](https://www.brookstradingcourse.com/price-action/10-best-price-action-trading-patterns/)
- [Brooks 2012 — Trading Price Action Trends, ch 6](https://www.amazon.com/Trading-Price-Action-Trends-Technical/dp/1118066510)
- [Bulkowski — Encyclopedia of Chart Patterns 2nd ed, ch 19](https://www.amazon.com/Encyclopedia-Chart-Patterns-Wiley-Trading/dp/0471668265)
- [Adam Grimes — Two-legged pullback ABC](https://www.adamhgrimes.com/blog/)
- SEC24 Turtle Soup learning: `memory/researcher/learning_20260514_sec24_turtle_soup_red.md`
- PA mastery gap envanteri: `reports/researcher/2026-05-14_pa_mastery_gap.md`
