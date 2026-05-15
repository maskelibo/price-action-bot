---
name: hyp-2026-05-14-vol-d2-sow-effort-down
description: VSA Effort-to-Move-Down (Sign of Weakness / SOW) — wide-spread down bar + 3-bar low breakdown + climactic-zone volume + lower-quartile close → short trend continuation. Bearish mirror of HYP-D1.
metadata: { type: hypothesis, status: pre-registered, author: researcher, date: 2026-05-14, sprint: SEC25, track: D, supersedes: null }
---

# HYP-2026-05-14-VOL-D2 — VSA Effort-to-Move-Down (SOW)

## Pre-Registration Disclosure (SOP-1)

**Çağrılma kararı:** SEC25 Track D — bearish trend continuation ayağı. SEC14.1/15.3
öğrenmesi: short trade'ler (n=3747, mR+0.247) long'tan 1.66× daha karlı. Mevcut
short envanteri:
- `three_black_crows`, `crows_buying_climax`, `morning_evening_star` (klasik candle)
- `wyckoff_spring_vsa` UTAD short (EQH context gerektiriyor — sıkı)
- `obv_engulfing_confluence` bearish leg (2-pivot divergence)
ama **VSA klasik SOW** (geniş aşağı bar + alt kapanış + 3-bar düşük breakdown +
hacim) **standalone yok**. SOS'un (HYP-D1) tam simetriği — ayrı hipotez çünkü
short edge yapısal farklı olabilir.

## İddia (testable, ölçülebilir)

**H1 (alternative):** Crypto 1d × 11 sym × 5y veride, VSA "Effort-to-Move-Down"
patterni (geniş aşağı bar + alt çeyrek kapanış + 3-bar low breakdown + climactic-zone
volume) bearish trend continuation edge sağlar. Pre-registered hard gates:

- n ≥ 200
- mR (honest clip) ≥ +0.10
- WR ≥ 45%
- shuffle p < 0.05 (n=2000)
- max_R < 10 (artifact gate)
- Symbol-out CV: max |dev| < 30%
- Per-symbol pozitif mR: en az 6/11
- **OOS validation:** IS=2021-2023, OOS=2024-2025; OOS mR ≥ +0.05 ve sign aynı

**H0 (null):** Pattern crypto 1d'de short edge taşımıyor; mR ≤ 0 veya p ≥ 0.05.

**Counter-hypothesis (önemli):**
1. Crypto **bull-biased asset class** — long-side patterns historik olarak daha
   güvenilir. SOW bull market'ta sahte sinyal üretebilir (özellikle 2021 Q1-Q4 ve
   2024 Q1-Q2 BTC ralleri). Per-year breakdown'da 2021/2024 mR negatif gelirse,
   pattern crypto cycle ile uyumsuz. Sec14.1 short avantajı **mean-reversion**
   (DD recovery) kaynaklı olabilir, trend continuation kaynaklı değil.
2. SOW = climactic vol + wide down bar = **Selling Climax öncüsü** (VSA §4.2).
   Pattern fade etmeli (long) yerine continuation (short) açıyoruz. Eğer kripto'da
   SC sıklığı yüksekse, SOW gerçekten "satılığın sonuna giriş" olur ve WR < 40%
   verir.
3. `three_black_crows` (TOP_11) zaten bearish-continuation üretiyor; correlation
   > 0.6 = pure overlap.

## Mekanik (entry/exit/filter)

**TF:** 1d daily UTC.

**Setup (SHORT only — SOW hep bearish):**
- `down_bar`: close[t] < open[t]
- `spread`: (high[t] - low[t]) > 1.2 × ATR(20)[t-1]
- `lower_close`: close[t] < low[t] + 0.30 × (high[t] - low[t]) — alt çeyrek
- `breakdown`: low[t] < min(low[t-3:t]) — last 3 bar's low (NOT including current)
- `climactic_zone_vol`: volume[t] > 1.5 × SMA(volume, 20)[t-1]
- ATR(20)[t-1] / close[t-1] > 0.005
- Cooldown: 5 bar same direction same symbol

**Setup gating (anti-overlap):**
- `prior_bar_not_already_breakdown`: low[t-1] >= min(low[t-4:t-1])
- **No-Capitulation Filter (HYP-D2-specific):** skip if last 5 bars cumulative
  loss > 15% (avoid catching SC bottom): `close[t]/close[t-5] > 0.85`

**Entry:** market close[t] (engine: t+1 open).

**Exits:**
- SL: high[t] + 0.30 × ATR(20)
- TP1: 1.0R — close 50%
- TP2: 2.0R — close 30%
- Runner: 20% (engine default 1.5× trail, time exit 30 bar)
- Time exit: 12 bar no progress to 1R → flat

**Lookahead audit hooks:** Aynı HYP-D1 — `.shift(1)` on rolling, ATR Wilder causal.

## Test Planı

| Parametre | Değer |
|---|---|
| Symbols | 11 |
| TF | 1d |
| Window | 5y |
| IS / OOS split | IS=2021-2023, OOS=2024-2025 |
| Fees / Slippage | aynı HYP-D1 |
| R-clip | hold>60d → R<=1.0 |
| Shuffle | n=2000, seed=42 |

**Parametre grid (≤ 9 cell):**
- spread_atr_mult ∈ {1.0, 1.2, 1.5}
- vol_sma_mult ∈ {1.5, 2.0, 2.5}

Toplam 3×3 = 9. Bonferroni alpha = 0.00556.

**Robustness suite:**
1. IS-only gate
2. OOS gate
3. Symbol-out CV
4. Stress periods (özellikle 2022-05 LUNA, 2022-11 FTX — short pozitif beklenir)
5. **Per-year regime breakdown zorunlu** (bull vs bear yıl ayrımı)

## Pass / Red Kriterleri

Aynı HYP-D1 yapısı, sadece **anti-capitulation filter** SOW'a özel.

## Beklenen Sonuç (Bayesian prior)

- **Beklenti:** n ~200-350, mR +0.10-0.18, WR 45-50%. Crypto bear yıllarda
  (2022, 2024 H2) güçlü; bull yıllarda zayıf. Per-year breakdown çok değişken
  beklenir.
- **Sürpriz alanı:** anti-capitulation filter olmadan WR < 35% ise pattern crypto
  için SC-bottom catching (yapısal yanlış yön).
- **Beklenen yan-bulgu:** symbol-out CV'de alt-coin'ler (ADA, AVAX, MATIC, DOGE)
  positive bias gösterirse, SOW alt-coin bear cycle'larda daha güvenilir.

## Implementation Notu

- Yeni dosya: `src/price_action/strategies/vsa_sow_effort_down.py`
- Module-level: `STRATEGY_CLASS = 'trend_continuation'`
- Manifest pattern_id: `vsa_sow_short`
- 1 yön (short)

## Mevcut Pool Orthogonality Beklentisi

| Strategy | Beklenti | Sebep |
|---|---|---|
| `three_black_crows` (TOP_11) | **ρ ~ 0.3-0.5** | Both bearish continuation; SOW single-bar, 3BC 3-bar sequence |
| `wyckoff_spring_vsa` UTAD | ρ ~ 0.0-0.2 | UTAD multi-test EQH context, SOW salt single-bar |
| `engulfing_continuation` bear | ρ ~ 0.1-0.3 | Different trigger |
| `vsa_climax_test` BC | ρ ~ 0.1-0.2 | BC reversal, SOW continuation — opposite logic |
| `donchian_breakout` short | ρ ~ 0.2-0.4 | Both breakdown, different horizon |

**ORTHOGONALITY SUCCESS:** `ρ(vsa_sow, three_black_crows) < 0.5`.

## Reproducibility

- Script: `scripts/sec25_volume_standalone.py`
- Strategy: `src/price_action/strategies/vsa_sow_effort_down.py`
- Data: 5y 11 sym
- Seed: 42, n_perm 2000

## Kaynaklar

- [VSA §4.14 Effort to Move Down — `knowledge/books/vsa_volume_spread_analysis.md`](`knowledge/books/vsa_volume_spread_analysis.md`)
- [Williams, *Master the Markets* (1993) — SOW bölümü](https://www.amazon.com/Master-Markets-Tom-Williams/dp/B000RQE3DC)
- [SEC14.1 short trade analizi — `memory/MEMORY.md` Sec14.1+SEC13.4 STACK](`memory/MEMORY.md`)
- [Sec23 RSI2 RED OOS — selection bias dersi](`reports/researcher/2026-05-14_sec23_rsi2_oos_validation.md`)
