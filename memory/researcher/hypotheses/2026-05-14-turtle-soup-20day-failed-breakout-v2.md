---
name: hyp-2026-05-14-turtle-soup-20day-failed-breakout-v2
description: Linda Raschke/Connors Turtle Soup — fade new 20-day high/low reclaim within 1-2 bars. Mean-reversion strategy (SEC24 enriched pre-reg).
metadata: { type: hypothesis, status: pre-registered, author: researcher, date: 2026-05-14, sprint: SEC24, supersedes: 2026-05-14-turtle-soup-20day-failed-breakout.md }
---

# HYP-2026-05-14-TURTLE-SOUP-V2 — 20-Day Failed Breakout Fade

## Pre-Registration Disclosure (SOP-1)

**Çağrılma kararı:** SEC24 sprint, PA Mastery Gap analizinde mean-reversion class
açık alan #1 önceliği. Raschke/Connors 1996 "Street Smarts" pattern'i, repo'da
**donchian_breakout** (production) MEVCUT — Turtle Soup o stratejinin yapısal
ters'i; yüksek anti-correlation beklentisi ensemble katkı potansiyelinin
mekaniğini güçlü tutuyor.

**Önceki versiyon farkı:** v1 (`2026-05-14-turtle-soup-20day-failed-breakout.md`)
lab-scientist tarafından oluşturulmuş ama test çalıştırılmamış. v2 SEC22 mean-rev
sprint öğretileri (max_R artifact gate, honest clip hold>60d, shuffle p threshold)
ve SEC23 OOS validation (selection bias paranoyası) ile enriched.

## İddia (testable, ölçülebilir)

**H1 (alternative):** Crypto 1d × 11 sym × 5y veride, "yeni 20-bar high/low ama
aynı bar prior 20-bar range içine reclaim + body-rejection candle" pattern'i
mean-reversion edge sağlar. Pre-registered hard gates:

- n ≥ 200 (uygulamada beklenti ~300-500 trigger)
- mR (honest, hold>60d clip 1.0) ≥ +0.10
- WR ≥ 45%
- shuffle p < 0.05 (n=2000 perm)
- max_R < 10 (artifact gate; SEC22 RSI2 dersi)
- Symbol-out CV: max |dev| < 30% (regime stability)
- Per-symbol pozitif mR: en az 6/11

**H0 (null):** Pattern crypto 1d'de edge taşımıyor; mR ≤ 0 veya p ≥ 0.05.

**Counter-hypothesis (önemli, pre-registered):**
1. Donchian breakout edge'i crypto'da bittiyse, Turtle Soup da düşük edge gösterebilir
   (çift kapı tetiklenir bir alt-pattern yapısal ama kazanç yapısı yatay). Eğer
   donchian_breakout 2024-2025 OOS mR çökmüşse (TBD), Turtle Soup OOS da çöker.
2. `equal_highs_sweep` benzer "sweep + fail" mantığı kullanıyor; correlation > 0.7
   ise pure overlap (Sec5 öğrenmesi). Standalone PASS olsa bile ensemble katkısı
   ~0 olabilir.
3. Crypto'da 20D high/low breakout = strong-trend signal (BTC 2021 Ekim ATH örneği).
   Failure beach-case değil baseline olabilir (false_break_continuation > false_break_reversal).
   WR < 40% olur ise pattern crypto için yapısal uyumsuz.

## Mekanik (entry/exit/filter)

**TF:** 1d daily UTC.

**Setup (SHORT — bearish Turtle Soup):**
- `high[t] > max(high[t-20:t-1])` — yeni 20-bar high
- `close[t] < max(high[t-20:t-1])` — kapanış prior 20D range içine geri
- body-rejection filter: `|close[t]-open[t]| / (high[t]-low[t]) > 0.30` AND
  (`close[t] < open[t]` OR `(high[t]-max(open[t],close[t]))/(high[t]-low[t]) > 0.50`)
- ATR(14) > 0.5% (chop reject)
- Cooldown: 3 bar same direction
- **Skip if strong-impulse t**: `close[t] >= close[t-1] + 2 × ATR(14)` (gerçek
  momentum break, fade etme — recovery pattern değil)

**Setup (LONG — bullish Turtle Soup):** mirror with 20-bar low.

**Entry:** market close[t] (engine convention = t+1 open).

**Exits:**
- SL (SHORT): `high[t] + 0.25 × ATR(14)` — sıkı stop, single-bar pattern
- SL (LONG): `low[t] - 0.25 × ATR(14)`
- TP1: 1.0R — close 50%
- TP2: 20D range midpoint OR 2.0R (whichever first) — close 30%
- Runner: 20% — engine default trail
- Time exit: 7 bar no progress to 1R → flat (Raschke original "if it ain't moving by day 5, exit")

**Lookahead audit hooks (pre-registered):**
- `.rolling(20).max().shift(1)` ile prior 20-bar high (NOT including current bar)
- Tüm filtreler t-1 close kullanır, entry t+1 open
- ATR(14) Wilder, causal

## Test Planı

| Parametre | Değer |
|---|---|
| Symbols | 11 (BTC/ETH/SOL/BNB/ADA/AVAX/LINK/DOT/DOGE/XRP/MATIC USDT) |
| TF | 1d |
| Window | 5y (2021-01 → 2026-05) |
| Fees | taker 0.075% / maker -0.010% |
| Slippage | 5 bps |
| R-clip | hold>60d → R<=1.0 (honest convention) |
| Shuffle | n=2000 perm, seed=42 |

**Standalone backtest:**
1. n, mR, WR, max_R, median_R, sumR, hold_d_median/p90
2. Per-symbol breakdown (anti-cherry-pick)
3. Per-year breakdown (regime stability)
4. Top/bottom 5 trade inspection (artifact check — SEC19 QM dersi)
5. Correlation vs `donchian_breakout` pool (orthogonality kanıtı)
6. Long-only vs short-only split (crypto 2021 bull vs 2022 bear bias)

**Parametre grid (selection bias guarded — pre-registered ESNEK aralıklar):**
- lookback ∈ {15, 20, 25} (Raschke orijinal 20)
- body_ratio_min ∈ {0.30, 0.40, 0.50}
- atr_min ∈ {0.005, 0.010}

Toplam 3×3×2 = 18 config. Bonferroni alpha = 0.05/18 = 0.00278.

**Robustness suite (SOP-3):**
1. Walk-forward 3y/3m step (SEC22 minimal subset)
2. In-sample/OOS Sharpe fark < 30%
3. Symbol-out CV
4. Stress periods: 2022-05 LUNA, 2022-11 FTX, 2024-03 ATH

## Pass / Red Kriterleri

**PASS-PRODUCTION (rare):** Tüm 7 gate ✓ + WF 3y rolling 13 pencerede ≥10 pozitif
+ ensemble katkı +%2pp yıllık + DD ≤ baseline +%3pp.

**PASS-CANDIDATE (likely best-case):** Standalone 5-7 gate ✓ + per-sym 6+/11
pozitif → Engineering SEC21 slot fix sonrası ENSEMBLE retest aday.

**RED (likely):** Standalone ≤4 gate ✓ veya per-sym < 5/11 pozitif veya
correlation w/ equal_highs_sweep > 0.7 → archive, gerekçeli kapanış.

**RED-OOS-SELECTION-BIAS (paranoid kontrol):** Eğer 18-config grid'in birden
fazla config'i borderline PASS gösterirse, OOS hold-out 2024-2025 validation
zorunlu (SEC23 paradigm). In-sample best config OOS'ta gate fail'lerse → RED-archive.

## Beklenen Sonuç (Bayesian prior)

- **Beklenti:** standalone n=300-500, mR +0.15-0.25, WR 47-52% — PASS-CANDIDATE
  yüksek ihtimal (mekanik temiz, klasik 30 yıl).
- **Sürpriz alanı:** crypto 1d'de Donchian breakout = momentum signal değil, fake-out
  signal (zaten failed_breakout strategy var ve TOP_10 production). Bu durumda
  Turtle Soup edge zaten failed_breakout'a ait olmuş olabilir. Korelasyon > 0.7
  ile çakışırsa RED.
- **Beklenen yan-bulgu:** body_ratio threshold rejection candle kalitesini ölçer;
  SEC22 IDF v3 öğrenmesi (body≥0.50 sweet spot) Turtle Soup'ta da görülürse
  pattern detection rationale güçlenir.

## Implementation Notu

- Yeni dosya: `src/price_action/strategies/turtle_soup_20d.py`
- Module-level: `STRATEGY_CLASS = 'mean_reversion'` (Engineering SEC21 hook)
- Vectorized: `rolling(20).max().shift(1)`, `rolling(20).min().shift(1)`
- Manifest pattern_ids: `turtle_soup_long`, `turtle_soup_short`
- Backtest script: `scripts/sec24_turtle_soup_standalone.py` (sec22 pattern kopya)

## Mevcut Pool Orthogonality Beklentisi

| Strategy | Beklenti | Sebep |
|---|---|---|
| `donchian_breakout` (TOP_10) | **ρ < -0.2** | Yapısal inverse — Turtle Soup donchian'ın failure'ı |
| `failed_bo_bos_reclaim` | ρ ~ +0.3-0.5 | Both "failed BO + reclaim" mantığı, ama failed_bo_bos S/R level + BOS yapısal; Turtle Soup salt Donchian extremes |
| `equal_highs_sweep` | ρ ~ +0.2-0.4 | Both sweep+fail ama different level type (donchian rolling vs equal-highs cluster) |
| `inside_day_failure` (IDF) | ρ ~ 0.0 | Different bar count (IDF 1-bar inside, TS 20-bar extreme) |
| `fvg_fill_reversal` | ρ ~ 0.0 | Yapısal independent |

**ORTHOGONALITY SUCCESS CRITERION:** `ρ(turtle_soup, equal_highs_sweep) < 0.5`
ve `ρ(turtle_soup, donchian_breakout) < 0`.

## Reproducibility

- Script: `scripts/sec24_turtle_soup_standalone.py` (yazılacak)
- Strategy: `src/price_action/strategies/turtle_soup_20d.py` (yazılacak)
- Data: `data/market.duckdb` (binance 11 sym 1d 2021-05 → 2026-05)
- Seed: 42 (numpy default_rng)
- n_perm: 2000

## Kaynaklar

- [Raschke & Connors — Street Smarts (1996), Turtle Soup chapter](https://www.amazon.com/Street-Smarts-Surviving-Strategies-Markets/dp/0965046109)
- [Linda Raschke — Turtle Soup Strategy original explanation (Traders Mastermind)](https://tradersmastermind.com/turtle-soup-trading-strategy-rules/)
- [New Trader U — Turtle Soup Rules Summary](https://www.newtraderu.com/2021/06/05/the-turtle-soup-stock-trading-strategy/)
- [Sec22 RSI2 RED OOS — SEC23 paradigm](`reports/researcher/2026-05-14_sec23_rsi2_oos_validation.md`)
- [SEC19 QM RED-artifact lesson](`memory/researcher/hypotheses/2026-05-14-quasimodo-reversal.md`)
