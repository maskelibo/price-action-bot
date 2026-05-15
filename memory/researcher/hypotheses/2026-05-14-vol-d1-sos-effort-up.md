---
name: hyp-2026-05-14-vol-d1-sos-effort-up
description: VSA Effort-to-Move-Up (Sign of Strength / SOS) — wide-spread up bar + 3-bar high breakout + climactic-zone volume + upper-quartile close → long trend continuation.
metadata: { type: hypothesis, status: pre-registered, author: researcher, date: 2026-05-14, sprint: SEC25, track: D, supersedes: null }
---

# HYP-2026-05-14-VOL-D1 — VSA Effort-to-Move-Up (SOS)

## Pre-Registration Disclosure (SOP-1)

**Çağrılma kararı:** SEC25 Track D — hacim mikroyapısı sprintinin trend-continuation
ayağı. `knowledge/books/vsa_volume_spread_analysis.md` §4.7 ve §10 (kripto için
"En yüksek güven sırasıyla test önerisi" listesinde **#4 Effort to Move Up** olarak
geçiyor). Mevcut envanterde:
- `volume_expansion` (vol > 1.5×median, basit continuation)
- `obv_engulfing_confluence` (2-pivot OBV divergence)
mevcut, ama **klasik VSA SOS** (geniş spread + üst kapanış + yatay direnç breakout
+ hacim) **standalone yok**. Bu hipotez SOS'un mekanik formunu test eder.

## İddia (testable, ölçülebilir)

**H1 (alternative):** Crypto 1d × 11 sym × 5y veride, VSA "Effort-to-Move-Up" patterni
(geniş yukarı bar + üst çeyrek kapanış + 3-bar high breakout + climactic-zone volume)
trend continuation edge sağlar. Pre-registered hard gates:

- n ≥ 200 (uygulamada beklenti ~250-450 trigger)
- mR (honest, hold>60d clip 1.0) ≥ +0.10
- WR ≥ 45%
- shuffle p < 0.05 (n=2000 perm, seed=42)
- max_R < 10 (artifact gate, SEC19/SEC22 dersi)
- Symbol-out CV: max |dev| < 30%
- Per-symbol pozitif mR: en az 6/11
- **OOS validation (SEC23 dersi):** IS=2021-2023, OOS=2024-2025 split; OOS mR ≥ +0.05 ve sign aynı

**H0 (null):** Pattern crypto 1d'de edge taşımıyor; mR ≤ 0 veya p ≥ 0.05.

**Counter-hypothesis (önemli, pre-registered):**
1. `volume_expansion` zaten "vol>1.5×median + trend-aligned bar" sinyali üretiyor.
   SOS bu sinyalin alt-seti olabilir (correlation > 0.7 = pure overlap).
   Standalone PASS ama ensemble katkı ~0.
2. Crypto'da geniş yukarı bar + climactic vol = **buying climax tepesinin** öncüsü
   olabilir (VSA §10: "BC sonrası kripto bull market'ta drop olur ama yeni ATH gelir").
   WR < 40% ise SOS aslında early-BC fade pattern.
3. Mevcut donchian_breakout (TOP_10 production) ile orthogonality riski:
   3-bar HH ≈ short-Donchian. ρ > 0.5 ise ensemble nötr.

## Mekanik (entry/exit/filter)

**TF:** 1d daily UTC.

**Setup (LONG only — SOS hep bullish):**
- `up_bar`: close[t] > open[t]
- `spread`: (high[t] - low[t]) > 1.2 × ATR(20)[t-1]   *(ATR shift(1) causal)*
- `upper_close`: close[t] > low[t] + 0.70 × (high[t] - low[t])
- `breakout`: high[t] > max(high[t-3:t]) — last 3 bar's high (NOT including current)
- `climactic_zone_vol`: volume[t] > 1.5 × SMA(volume, 20)[t-1]
- ATR(20)[t-1] / close[t-1] > 0.005 (chop reject)
- Cooldown: 5 bar same direction same symbol

**Setup gating (anti-overlap with volume_expansion):**
- `prior_bar_not_already_breakout`: high[t-1] <= max(high[t-4:t-1]) — bu single-bar
  breakout, multi-bar trend continuation değil

**Entry:** market close[t] (engine convention: t+1 open).

**Exits:**
- SL: low[t] − 0.30 × ATR(20)
- TP1: 1.0R — close 50%
- TP2: 2.0R — close 30%
- Runner: 20% — engine default trail (1.5× runner trail, time exit 30 bar)
- Time exit: 12 bar no progress to 1R → flat

**Lookahead audit hooks (pre-registered):**
- `.rolling(20).mean().shift(1)` ile SMA hacim (t-1 dahil ama t hariç)
- `.rolling(3).max().shift(1)` ile prior 3-bar high
- ATR(20) Wilder, shift(1) (causal — strategy uses ATR_{t-1} for thresholds on bar t)
- Entry filter triggers tamamen t close + t-1 history

## Test Planı

| Parametre | Değer |
|---|---|
| Symbols | 11 (BTC/ETH/SOL/BNB/ADA/AVAX/LINK/DOT/DOGE/XRP/MATIC USDT) |
| TF | 1d |
| Window | 5y (2021-01 → 2026-05) |
| IS / OOS split | IS=2021-2023, OOS=2024-2025 (selection bias gate) |
| Fees | taker 0.075% / maker -0.010% |
| Slippage | 5 bps (10 bps round-trip) |
| R-clip | hold>60d → R<=1.0 (honest convention) |
| Shuffle | n=2000 perm, seed=42 |

**Parametre grid (SEC23 dersi: ≤ 9 cell):**
- spread_atr_mult ∈ {1.0, 1.2, 1.5}
- vol_sma_mult ∈ {1.5, 2.0, 2.5}

Toplam 3×3 = 9 config. Bonferroni alpha = 0.05/9 = **0.00556**.

**Robustness suite (SOP-3 minimal):**
1. IS-only standalone gate (full 8 gate)
2. OOS hold-out 2024-2025 validation (selection bias gate)
3. Symbol-out CV
4. Stress periods: 2022-05 LUNA, 2022-11 FTX, 2024-03 BTC ATH, 2024-08 Yen carry
5. Long-side only (SOS by definition — no short mirror; not bias, structural)

## Pass / Red Kriterleri

**PASS-CANDIDATE (best-case):** Tüm 8 IS gate ✓ + 9 grid'in default config'i (1.2/2.0/0.70) OOS gate'leri geçiyor → Lab ensemble retest aday.

**PASS-CONDITIONAL:** IS gates ≥6/8 ama OOS mR ≥ +0.05 + per-sym 6/11 → archive RED-borderline, v2 önerisi.

**RED:** IS gate < 5/8 veya OOS mR ≤ 0 veya correlation w/ `volume_expansion` > 0.7 veya per-sym < 5/11 → archive.

**RED-SELECTION-BIAS:** 9 config'ten birden fazla borderline PASS gösterirse, OOS default config (orta cell 1.2/2.0/0.70) gate fail'lerse → RED-archive.

## Beklenen Sonuç (Bayesian prior)

- **Beklenti:** n ~250-400, mR +0.10-0.20 in-sample, WR 47-53%. SOS klasik VSA pattern; literatür uzun süre güçlü olmuş, ama crypto'da arbitraj baskısı düşük (custom logic).
- **Sürpriz alanı:** correlation w/ `volume_expansion` > 0.6 ise edge zaten production'da yakalanmış olabilir, ensemble retest sıfır katkı verir.
- **Beklenen yan-bulgu:** spread_atr_mult sweep'inde sweet spot 1.2-1.5 olmazsa, "climactic volume" tanımı kripto için kalibre edilemiyor demektir.

## Implementation Notu

- Yeni dosya: `src/price_action/strategies/vsa_sos_effort_up.py`
- Module-level: `STRATEGY_CLASS = 'trend_continuation'` (Engineering SEC21 hook)
- Vectorized: spread/vol/breakout/close-pos pure pandas, no for-loop
- Manifest pattern_id: `vsa_sos_long`
- Backtest script: `scripts/sec25_volume_standalone.py` (4-strategy batch)
- 1 yön (long) — short simetri ayrı hipotez (HYP-D2 SOW)

## Mevcut Pool Orthogonality Beklentisi

| Strategy | Beklenti | Sebep |
|---|---|---|
| `volume_expansion` (TOP_11) | **ρ ~ 0.4-0.6** | Both vol > N×SMA + trend-aligned bar; SOS daha sıkı (close-pos + breakout) |
| `donchian_breakout` (TOP_10) | ρ ~ 0.2-0.4 | Different breakout horizon (3-bar vs 20-bar Donchian) |
| `obv_engulfing_confluence` | ρ ~ 0.0-0.2 | OBV divergence 2-pivot, SOS single-bar |
| `engulfing_continuation` | ρ ~ 0.1-0.3 | Both trend cont, different trigger |
| `htf_momentum` (RED standalone) | ρ ~ 0.2 | Different timeframe logic |

**ORTHOGONALITY SUCCESS CRITERION:** `ρ(vsa_sos, volume_expansion) < 0.5`.

## Reproducibility

- Script: `scripts/sec25_volume_standalone.py` (yazılacak)
- Strategy: `src/price_action/strategies/vsa_sos_effort_up.py` (yazılacak)
- Data: `data/market.duckdb` (binance 11 sym 1d 2021-05 → 2026-05)
- Seed: 42 (numpy default_rng)
- n_perm: 2000

## Kaynaklar

- [VSA §4.7 Effort to Move Up — `knowledge/books/vsa_volume_spread_analysis.md`](`knowledge/books/vsa_volume_spread_analysis.md`)
- [VSA §10 — Kripto'da öncelikli test sırası, #4 Effort to Move Up](`knowledge/books/vsa_volume_spread_analysis.md`)
- [Williams, *Master the Markets* (1993) — SOS bölümü](https://www.amazon.com/Master-Markets-Tom-Williams/dp/B000RQE3DC)
- [Sec23 RSI2 RED OOS — selection bias dersi](`reports/researcher/2026-05-14_sec23_rsi2_oos_validation.md`)
- [SEC19 QM RED-artifact lesson](`memory/researcher/hypotheses/2026-05-14-quasimodo-reversal.md`)
