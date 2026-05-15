---
name: hyp-2026-05-14-vol-z-spike-fade
description: ATR z-score spike fade — single-bar volatility spike (ATR-z > 2.5) sonrası ertesi bar yön bağımsız mean-revert. Engle/Bollerslev GARCH vol-clustering inverse.
metadata: { type: hypothesis, status: pre-registered, author: researcher, date: 2026-05-14, sprint: SEC24 }
---

# HYP-2026-05-14-VOL-Z-SPIKE-FADE — ATR z-score spike fade (mean-reversion)

## Pre-Registration Disclosure (SOP-1)

**Çağrılma kararı:** PA Mastery Gap analizinde mean-reversion #3 önceliği.
Engle GARCH (1982) vol-clustering literatürünün **price-direction-agnostic
mean-reversion** uygulaması. Repo'da `vsa_climax_test` volume-based, bu
ATR/range-based (uncorrelated detection).

**Mevcut benzer yapısal:**
- `bb_extreme_reversal` HARD RED — price 2.5σ extreme reverse → crypto'da
  CONTINUATION (yapısal counter-mechanism). Vol-z spike fade FARKLI: range-based
  (high-low), price-extreme-bağımsız.
- `vsa_climax_test` PASS-standalone — volume climax detection, mean-rev pool'da.
- `cvd_spike_fade` PASS-standalone — CVD (cumulative volume delta) spike.

**Bu strateji yeni mekanik:** ATR(t) / mean(ATR[t-N:t]) > 2.5 → ertesi bar
fade in OPPOSITE direction of bar[t] body color. Yön bağımsız değil — bar
body'sinin tersine fade.

## İddia (testable, ölçülebilir)

**H1 (alternative):** Crypto 1d × 11 sym × 5y veride, "tek bar volatilite z-spike
(ATR-z > 2.5) + body decisive (|body|/range > 0.40) sonrası ertesi bar BODY
YÖNÜNÜN TERSİNE fade" pattern'i mean-reversion edge sağlar.

**Pre-registered hard gates:**
- n ≥ 150 (vol-spike rare-event, threshold 2.5 selective)
- mR (honest, hold>60d clip 1.0) ≥ +0.10
- WR ≥ 45%
- shuffle p < 0.05 (n=2000 perm)
- max_R < 10
- Symbol-out CV: max |dev| < 30%
- Per-symbol pozitif mR: en az 6/11

**H0 (null):** Pattern crypto 1d'de edge taşımıyor; mR ≤ 0 veya p ≥ 0.05.

**Counter-hypothesis (önemli, pre-registered):**
1. **Crypto vol-clustering yapısal:** Engle GARCH evidence stocks/FX for; crypto
   24/7 + perp leverage cascade'leri vol-clustering'i FARKLI yapar — vol-spike
   sonrası ertesi bar yine vol-spike (continuation) olabilir. Bu durumda
   fade KAYBEDER (BB extreme reversal RED öğretisinin paraleli).
2. `vsa_climax_test` overlap riski: vol climax = volume spike + reversal bar.
   Vol-z spike fade = ATR spike + body. Korelasyon ~ 0.3-0.5 muhtemel; eğer
   > 0.7 ise pure duplicate, archive.
3. **Threshold sensitivity:** ATR-z>2.5 selective; ama threshold-2.0 daha
   geniş ve cap'in edge'ini sulandırabilir. Selection bias guard'lı.
4. **Bar body color direction-dependence:** Bull bar = sat. Bear bar = al. Bu
   asymmetric — crypto bull bias (2021/2024 BTC parabolik bull) sırasında
   long fade trade'ler kaybeder. Per-side audit zorunlu.

## Mekanik (entry/exit/filter)

**TF:** 1d.

**Vol-z hesaplama (causal):**
- `atr_window = 20`
- `atr_now[t] = ATR(14)[t]`  # Wilder, causal
- `atr_mean[t-1] = mean(ATR(14)[t-21:t-1])`  # 20-bar prior mean
- `atr_std[t-1] = std(ATR(14)[t-21:t-1])`
- `vol_z[t] = (atr_now[t] - atr_mean[t-1]) / atr_std[t-1]`

**Setup (SHORT fade — bull-body vol-spike):**
- `vol_z[t] > 2.5`
- `close[t] > open[t]` — bullish bar
- `body_ratio = (close[t] - open[t]) / (high[t] - low[t]) > 0.40` — decisive bar
- `atr_now[t] > 0` and `atr_pct = atr_now[t]/close[t] > 0.01` (sub-1% ATR çok rare, skip)
- Cooldown: 3 bar same direction
- **Skip if HTF momentum strong:** `close[t] > EMA50[t] AND close[t-5] / close[t-20] - 1 > 0.30`
  (üst-trend güçlüyken bull-body fade momentum-counter, yapısal kaybeder)

**Setup (LONG fade — bear-body vol-spike):** mirror.

**Entry:** market close[t] (engine convention = t+1 open).

**Exits:**
- SL (SHORT): `close[t] + 0.50 × ATR(14)` (spike sonrası geri-spike riski yüksek)
- SL (LONG): `close[t] - 0.50 × ATR(14)`
- TP1: 1.0R — close 50%
- TP2: 2.0R — close 30%
- Runner: 20% engine default trail
- Time exit: 5 bar no progress to 1R → flat (vol-spike rapid mean-revert
  beklentisi, geç çıkış edge çürür)

**Pre-registered parametre defaults:**
- `vol_z_threshold = 2.5`
- `body_ratio_min = 0.40`
- `atr_window = 20`

**Lookahead audit hooks:**
- vol_z hesabı `atr_mean[t-1]`, `atr_std[t-1]` — prior 20-bar excluding current
- HTF momentum filter t-5/t-20 — strict past
- ATR Wilder causal

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
2. Per-side breakdown (long vs short) — asymmetry check
3. Per-year breakdown (regime stability)
4. Top/bottom 5 trade inspection (artifact check)
5. Correlation vs `vsa_climax_test`, `cvd_spike_fade`, `bb_extreme_reversal`

**Parametre grid (selection bias guarded):**
- vol_z_threshold ∈ {2.0, 2.5, 3.0}
- body_ratio_min ∈ {0.30, 0.40, 0.50}
- atr_window ∈ {14, 20, 30}

Toplam 3×3×3 = 27 config. Bonferroni alpha = 0.05/27 = 0.00185.

## Pass / Red Kriterleri

Aynı SEC22 standartı. HARD GATE 7 madde.

**Önemli pre-registered audit:** Long-only ve short-only ayrı raporlanır. Eğer
**bir yön sumR negatif ve diğer yön sumR pozitif AMA combined PASS olursa**, asymmetric
edge — production'a tek yön ile alınabilir (single-side strategy variant).

## Beklenen Sonuç (Bayesian prior)

- **Beklenti:** n=150-300 (vol-z>2.5 + body decisive selective), mR +0.05-+0.15
  borderline, WR 44-50%. Crypto vol-clustering counter-mechanism riski yüksek
  (BB extreme reversal RED paralel) — yapısal RED ihtimali %50.
- **Sürpriz alanı:** Eğer short-fade çalışır (parabolik BTC pullback) ama long-fade
  çalışmaz (bear-trend acceleration), asymmetric edge sürpriz olur ve production
  tek yönlü variant aday.
- **Yan-bulgu:** Vol-z spike + body decisive yine de continuation olabilir.
  Bu durumda strateji TERSİNE çevrilirse (vol-z spike + body = momentum continuation
  signal) trend_continuation class'ında yer alır. Sonraki sprint için yapısal bulgu.

## Implementation Notu

- Yeni dosya: `src/price_action/strategies/vol_z_spike_fade.py`
- Module-level: `STRATEGY_CLASS = 'mean_reversion'` (Engineering SEC21 hook)
- Vectorized
- Manifest pattern_ids: `vol_z_fade_long`, `vol_z_fade_short`
- Backtest script: `scripts/sec24_vol_z_spike_standalone.py`

## Mevcut Pool Orthogonality Beklentisi

| Strategy | Beklenti | Sebep |
|---|---|---|
| `vsa_climax_test` | ρ ~ +0.3-0.5 | Vol+reversal benzer mekanik (ama volume vs ATR) |
| `cvd_spike_fade` | ρ ~ +0.2-0.4 | CVD ≠ ATR ama "spike fade" konsept |
| `bb_extreme_reversal` | ρ ~ +0.1-0.3 | Price 2.5σ vs range-spike — related ama different feature |
| `fvg_fill_reversal` | ρ ~ 0.0 | Independent |
| `naked_poc_mr` | ρ ~ 0.0 | Different level type |

**ORTHOGONALITY SUCCESS:** max correlation < 0.6.

## Reproducibility

- Script: `scripts/sec24_vol_z_spike_standalone.py` (yazılacak)
- Strategy: `src/price_action/strategies/vol_z_spike_fade.py` (yazılacak)
- Data: `data/market.duckdb`
- Seed: 42

## Kaynaklar

- [Engle 1982 — ARCH](https://www.jstor.org/stable/1912773)
- [Bollerslev 1986 — Generalized ARCH](https://doi.org/10.1016/0304-4076(86)90063-1)
- [Quantified Strategies — Mean Reversion + Volatility](https://www.quantifiedstrategies.com/volatility-trading-strategies/)
- SEC22 BB extreme RED lesson: `reports/researcher/2026-05-14_sec22_summary.md`
- SEC22 lookback for vsa_climax_test similarity
