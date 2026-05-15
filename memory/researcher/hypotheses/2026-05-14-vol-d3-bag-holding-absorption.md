---
name: hyp-2026-05-14-vol-d3-bag-holding-absorption
description: VSA Bag Holding / Absorpsiyon — narrow-spread down bar + climactic volume + small body (effort>>result absorption signature) + next-bar bullish confirmation → long mean-reversion.
metadata: { type: hypothesis, status: pre-registered, author: researcher, date: 2026-05-14, sprint: SEC25, track: D, supersedes: null }
---

# HYP-2026-05-14-VOL-D3 — Bag Holding / Absorpsiyon (Long MR)

## Pre-Registration Disclosure (SOP-1)

**Çağrılma kararı:** SEC25 Track D — mean-reversion ayağı. SEC22 mean-rev sprintinde
*pattern-only* mean-rev (rsi2/three-push/BB) RED bulundu; **hacim-confirmed** mean-rev
açısı henüz test edilmedi. `knowledge/books/vsa_volume_spread_analysis.md` §4.4 Bag
Holding: "Aşağı bar + dar spread + yüksek hacim + body < %40 range → absorpsiyon
imzası". Mekanik temiz, mevcut envanterde yok.

Wyckoff Spring (`wyckoff_spring_vsa`) bag holding'in **çok-bar versiyonudur**
(multi-test HL + Spring penetration). Bag Holding **tek-bar** versiyondur ve
range içinde / destek altında değil, destek **üzerinde** olabilir (Phase B
accumulation içi). Bu yapısal fark hipotezi Spring'den dekorele yapar.

## İddia (testable, ölçülebilir)

**H1 (alternative):** Crypto 1d × 11 sym × 5y veride, VSA Bag Holding patterni
(dar spread + yüksek hacim + küçük body + down bar) + next-bar bullish confirmation
bar, long mean-reversion edge sağlar. Pre-registered hard gates:

- n ≥ 200
- mR (honest clip) ≥ +0.10
- WR ≥ 45%
- shuffle p < 0.05 (n=2000)
- max_R < 10 (artifact gate)
- Symbol-out CV: max |dev| < 30%
- Per-symbol pozitif mR: en az 6/11
- **OOS validation:** IS=2021-2023, OOS=2024-2025; OOS mR ≥ +0.05

**H0 (null):** Pattern crypto 1d'de edge taşımıyor; mR ≤ 0 veya p ≥ 0.05.

**Counter-hypothesis (önemli):**
1. **Yüksek hacim + dar spread + aşağı bar** = klasik VSA **stopping volume** ve
   **distribution candle** ile örtüşür. Stopping volume bullish (reversal), distribution
   bearish (continuation) — **aynı bar shape iki yöne yorumlanabilir**. Yön ayrımı
   bağlam'a bağlı (Phase A/B accumulation = absorpsiyon, Phase D distribution =
   bear). Bağlamsız mekanik kullanım → karışık sample, edge sıfırlanabilir.
2. `wyckoff_spring_vsa` zaten "VSA stopping volume + Spring" üretiyor; korelasyon
   yüksek olabilir (ρ > 0.5).
3. Crypto 1d'de "dar spread" tanımı kalibrasyon hassas — VSA §10 "spread < 0.7×ATR"
   önerir ama kripto yüksek vol için "narrow" tanımı sweep edilmeli.
4. **next-bar bullish confirmation** beklemek = 2-bar gecikme. Mean-rev sinyallerinde
   2-bar gecikme entry'yi reversal'ın ortasında yakalar, edge azalır.

## Mekanik (entry/exit/filter)

**TF:** 1d daily UTC.

**Setup (LONG MR only):**

Bar T (absorpsiyon bar):
- `down_bar`: close[T] < open[T]
- `narrow_spread`: (high[T] - low[T]) < 1.0 × ATR(20)[T-1]
- `high_vol`: volume[T] > 1.5 × SMA(volume, 20)[T-1]
- `small_body`: |close[T] - open[T]| < 0.4 × (high[T] - low[T])
- ATR(20)[T-1] / close[T-1] > 0.005

Bar T+1 (confirmation bar):
- `bullish_close`: close[T+1] > close[T]
- `not_below_T_low`: low[T+1] > low[T] (range hold)
- Cooldown: 5 bar same direction same symbol

**Entry:** market close[T+1] (engine: T+2 open).

**Exits:**
- SL: low[T] − 0.50 × ATR(20)[T-1]
- TP1: 1.0R — close 50%
- TP2: 2.0R — close 30%
- Runner: 20% (engine default)
- Time exit: 10 bar no progress to 1R → flat (mean-rev kısa horizon)

**Lookahead audit hooks:**
- ATR(20)[T-1] tüm threshold için (shift(1) causal)
- volume SMA(20)[T-1] (shift(1) causal)
- Confirmation `close[T+1] > close[T]` — strategy emit on bar T+1 close, entry T+2 open

## Test Planı

| Parametre | Değer |
|---|---|
| Symbols | 11 |
| TF | 1d |
| Window | 5y |
| IS / OOS split | IS=2021-2023, OOS=2024-2025 |
| Fees / Slippage | standart 5bps |
| R-clip | hold>60d → R<=1.0 |
| Shuffle | n=2000, seed=42 |

**Parametre grid (≤ 9 cell):**
- narrow_spread_mult ∈ {0.7, 1.0, 1.3}
- vol_sma_mult ∈ {1.5, 2.0, 2.5}

Toplam 3×3 = 9. Bonferroni alpha = 0.00556.

**Robustness suite:**
1. IS-only gate
2. OOS gate
3. Symbol-out CV
4. Stress periods (özellikle 2022-05/11 — destek bölgelerinde absorpsiyon beklenir)
5. **Direction bias kontrol:** sadece long — short mirror (no-supply rally) yok
   (çünkü no-supply VSA §4.13 sample süreklilik yetersiz, ayrı hipotez olamayacak
   kadar yakın bag-holding'e)

## Pass / Red Kriterleri

Aynı şablon. Ek RED-spesifik:
- **RED-CORR:** ρ(bag_holding, wyckoff_spring_vsa) > 0.6 → archive ("aynı edge").

## Beklenen Sonuç (Bayesian prior)

- **Beklenti:** n ~150-300 (dar spread + yüksek hacim NADİR kombinasyon — sample
  riski yüksek; n_min=200 gate tetiklenebilir). mR +0.08-0.18, WR 48-55% (mean-rev
  doğal yüksek-WR low-mR).
- **Sürpriz alanı:** counter-hyp #1 doğrulanırsa (distribution overlap), WR ~50%
  ama mR ~0 olur — karışık sample.
- **Beklenen yan-bulgu:** narrow_spread_mult sweep'inde 0.7 ile 1.0 fark
  çok büyükse, "dar spread" tanımı çok-hassas, robust değil → güvensiz pattern.

## Implementation Notu

- Yeni dosya: `src/price_action/strategies/vsa_bag_holding.py`
- Module-level: `STRATEGY_CLASS = 'mean_reversion'`
- Manifest pattern_id: `vsa_bag_holding_long`
- 1 yön (long)
- Confirmation bar zorunlu — 2-bar pattern

## Mevcut Pool Orthogonality Beklentisi

| Strategy | Beklenti | Sebep |
|---|---|---|
| `wyckoff_spring_vsa` long | **ρ ~ 0.4-0.6** | Both VSA stopping volume + reclaim, ama Spring multi-test HL + penetration; Bag Holding single-bar + Phase B |
| `vsa_climax_test` long | ρ ~ 0.2-0.4 | SC + Test Bar 2-event, Bag Holding 2-bar but no SC requirement |
| `obv_engulfing_confluence` | ρ ~ 0.1-0.2 | OBV 2-pivot, Bag Holding tek-bar |
| `bb_extreme_reversal` (RED) | ρ ~ 0.0 | Different mechanism |
| `naked_poc_mr` | ρ ~ 0.0-0.1 | Volume profile mechanism, no direct overlap |

**ORTHOGONALITY SUCCESS:** `ρ(bag_holding, wyckoff_spring_vsa) < 0.5`.

## Reproducibility

- Script: `scripts/sec25_volume_standalone.py`
- Strategy: `src/price_action/strategies/vsa_bag_holding.py`
- Data: 5y 11 sym
- Seed: 42, n_perm 2000

## Kaynaklar

- [VSA §4.4 Bag Holding / Absorpsiyon — `knowledge/books/vsa_volume_spread_analysis.md`](`knowledge/books/vsa_volume_spread_analysis.md`)
- [Williams, *Master the Markets* (1993) — Bag Holding bölümü](https://www.amazon.com/Master-Markets-Tom-Williams/dp/B000RQE3DC)
- [Coulling, *A Complete Guide to Volume Price Analysis* (2013)](https://www.amazon.com/Complete-Guide-Volume-Price-Analysis/dp/1491249390)
- [SEC22 mean-rev RED sprint — `reports/researcher/2026-05-14_sec22_summary.md`](`reports/researcher/2026-05-14_sec22_summary.md`)
- [Sec23 RSI2 RED OOS — selection bias dersi](`reports/researcher/2026-05-14_sec23_rsi2_oos_validation.md`)
