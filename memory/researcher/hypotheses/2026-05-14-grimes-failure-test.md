---
name: hyp-2026-05-14-grimes-failure-test
description: Adam Grimes "Failure Test" — fade a single-bar swing pivot penetration that reclaims within 1-2 bars. Wyckoff Spring vectorized analog at daily/swing level.
metadata: { type: hypothesis, status: pre-registered, author: researcher, date: 2026-05-14, sprint: SEC24 }
---

# HYP-2026-05-14-GRIMES-FAILURE-TEST — Swing Pivot Failure Test

## Pre-Registration Disclosure (SOP-1)

**Çağrılma kararı:** PA Mastery Gap analizinde mean-reversion #2 önceliği.
Adam Grimes "The Art and Science of Technical Analysis" (2012) Ch7 setup.
Wyckoff Spring'in vektörize edilebilir basit varyantı — daha geniş timeframe'de
çalışır (Phase D specific accumulation TR gerekmez).

**Mevcut benzer:**
- `wyckoff_spring_vsa.py` (PASS-standalone) — multi-bar Phase D accumulation
  spesifik (TR sıkıştırma + VSA spring), bu daha dar bir setup
- `inside_day_failure.py` (PASS-standalone) — 2-bar inside-day + failure, bu
  daha mikro
- **Grimes Failure Test = single rolling-pivot bar penetration + reclaim** —
  yapısal olarak swing-level (rolling N-bar pivot), spring-spesifik değil

## İddia (testable, ölçülebilir)

**H1 (alternative):** Crypto 1d × 11 sym × 5y veride, "rolling N-bar swing
low/high penetrate eden bar AMA aynı bar (close) veya ertesi bar (close)
swing seviyesini reclaim eden bar" pattern'i mean-reversion edge sağlar.

**Pre-registered hard gates:**
- n ≥ 200
- mR (honest, hold>60d clip 1.0) ≥ +0.10
- WR ≥ 45%
- shuffle p < 0.05 (n=2000 perm)
- max_R < 10 (artifact gate)
- Symbol-out CV: max |dev| < 30%
- Per-symbol pozitif mR: en az 6/11

**H0 (null):** Pattern crypto 1d'de edge taşımıyor.

**Counter-hypothesis (önemli, pre-registered):**
1. `inside_day_failure` ile yapısal yakınlık var (V3 PASS-marginal mR+0.240 p=0.060).
   Eğer Grimes Failure Test trigger zamanları %50+ overlap ediyorsa, edge IDF'den
   geliyor demektir (yeni mekanik değil). Correlation > 0.7 → archive, retry değil.
2. `wyckoff_spring_vsa` (PASS-standalone) Phase D accumulation specific. Grimes
   Failure Test rolling-pivot, accumulation-agnostic. Trigger overlap düşük
   beklenir AMA mR'leri benzer ise (PASS-standalone, ensemble null) yapısal
   slot bottleneck deja vu — yine ensemble katkı ~0.
3. Crypto 1d'de N=20 pivot tabanları/tepeleri çok frequent → trigger > 1000
   beklenir. Edge size düşer (overcommitted detection). N=30-40 daha selective
   olabilir; ama parametre selection bias guard'lı sweep gerek.

## Mekanik (entry/exit/filter)

**TF:** 1d.

**Setup (LONG — swing-low failure test):**
- `low[t] < min(low[t-N:t-1])` — bar t prior N-bar low'u kırdı
- AND (`close[t] > min(low[t-N:t-1])` OR `close[t+0] > swing_low AND close[t] > open[t]`
  → strict: `close[t] > min(low[t-N:t-1])`)
- AND `close[t] > open[t]` — bullish bar close (reclaim confirmation)
- ATR(14) > 0.5%
- Body-rejection filter: lower wick prominence
  `(min(open[t],close[t]) - low[t]) / (high[t] - low[t]) > 0.40` (long lower wick)
- Cooldown: 3 bar same direction
- **Skip if news-strong-impulse**: `|close[t] - close[t-1]| > 3 × ATR(14)`
  (gap day, news catalyst — yapısal failure değil)

**Setup (SHORT — swing-high failure test):** mirror.

**Entry:** market close[t] (engine convention = t+1 open).

**Exits:**
- SL (LONG): `low[t] - 0.10 × ATR(14)` (sıkı, hard rejection bar olduğu için)
- SL (SHORT): `high[t] + 0.10 × ATR(14)`
- TP1: 1.5R — close 50%
- TP2: 3.0R — close 30%
- Runner: 20% — engine default trail
- Time exit: 10 bar no progress to 1R → flat

**Pre-registered parametre defaults:**
- `pivot_lookback = 20` (N=20 rolling pivot, daily-swing)
- `wick_min = 0.40` (Grimes orijinal "long wick" subjective; 0.40 mid-quantile)
- `body_close_above = True` (reclaim STRICT: close > pivot level)

**Lookahead audit hooks:**
- `.rolling(20).min().shift(1)` / `.rolling(20).max().shift(1)` — prior N-bar
  pivot excluding current bar
- ATR Wilder causal
- close[t], open[t], low[t], high[t] all t-bar values — no peek

## Test Planı

| Parametre | Değer |
|---|---|
| Symbols | 11 |
| TF | 1d |
| Window | 5y (2021-01 → 2026-05) |
| Fees | taker 0.075% / maker -0.010% |
| Slippage | 5 bps |
| R-clip | hold>60d → R<=1.0 |
| Shuffle | n=2000 perm, seed=42 |

**Standalone backtest:**
1. n, mR, WR, max_R, median_R, sumR
2. Per-symbol breakdown
3. Per-year breakdown
4. Top/bottom 5 trade inspection
5. Correlation vs `inside_day_failure` and `wyckoff_spring_vsa` pools
6. Long-only vs short-only

**Parametre grid (selection bias guarded):**
- pivot_lookback ∈ {15, 20, 30}
- wick_min ∈ {0.30, 0.40, 0.50}
- body_close_above ∈ {True, False} (strict reclaim vs partial reclaim allowed)

Toplam 3×3×2 = 18 config. Bonferroni alpha = 0.05/18 = 0.00278.

## Pass / Red Kriterleri

Aynı SEC22 standartı: HARD GATE 7 madde. ≥5 PASS + 2 SOFT/FAIL = PASS-CANDIDATE.
≤4 PASS = RED.

**Önemli pre-registered audit:** Eğer standalone PASS olur ama correlation w/
`inside_day_failure` veya `wyckoff_spring_vsa` > 0.6 ise → "edge IDF/WSV'den geliyor"
gerekçesiyle ensemble retest YAPILMAZ, mean-rev class içinde DUPLICATE olarak
ARCHIVE.

## Beklenen Sonuç (Bayesian prior)

- **Beklenti:** n=400-800 (rolling-pivot detection sık), mR +0.08-+0.15 (borderline),
  WR 45-50%. Selection problemi: N=20 standart ama crypto 1d 5y'de selectivity
  düşük olabilir. N=30 daha selective.
- **Sürpriz alanı:** Eğer IDF/WSV ile correlation yüksek çıkarsa, retry argümanı
  tamamen kuruluyor. Ama bu pre-registered RED kriteri.
- **Yan-bulgu beklentisi:** Body close reclaim STRICT vs partial fark çok büyük
  olabilir; partial reclaim crypto'da Type-2 failure (Grimes terminology) signal
  veriyor olabilir.

## Implementation Notu

- Yeni dosya: `src/price_action/strategies/grimes_failure_test.py`
- Module-level: `STRATEGY_CLASS = 'mean_reversion'` (Engineering SEC21 hook)
- Vectorized
- Manifest pattern_ids: `grimes_failure_long`, `grimes_failure_short`
- Backtest script: `scripts/sec24_grimes_failure_standalone.py`

## Mevcut Pool Orthogonality Beklentisi

| Strategy | Beklenti | Sebep |
|---|---|---|
| `inside_day_failure` (IDF) | ρ ~ +0.3-0.5 | Failure mantığı benzer ama trigger bar farklı |
| `wyckoff_spring_vsa` | ρ ~ +0.2-0.4 | Spring = special-case failure test |
| `liquidity_sweep_reversal` | ρ ~ +0.3-0.6 | Both "sweep + reverse" |
| `equal_highs_sweep` | ρ ~ +0.2-0.4 | Cluster vs rolling-pivot |
| `fvg_fill_reversal` | ρ ~ 0.0 | Independent |

**ORTHOGONALITY SUCCESS CRITERION:** Mevcut mean-rev pool ile max correlation < 0.6.

## Reproducibility

- Script: `scripts/sec24_grimes_failure_standalone.py` (yazılacak)
- Strategy: `src/price_action/strategies/grimes_failure_test.py` (yazılacak)
- Data: `data/market.duckdb`
- Seed: 42

## Kaynaklar

- [Adam Grimes — The Failure Test](https://www.adamhgrimes.com/failure-test-2/)
- Adam Grimes, "The Art and Science of Technical Analysis" (2012) Wiley, Ch7
- [Wyckoff Spring vs Failure Test comparison](https://www.adamhgrimes.com/wyckoff-spring/)
- SEC22 IDF V3 öğrenme: `reports/researcher/2026-05-14_sec22_summary.md`
- SEC19 IDF post-mortem: `memory/researcher/hypotheses/2026-05-14-inside-day-failure.md`
