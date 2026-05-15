---
name: hyp-2026-05-14-vol-d4-weis-wave-divergence
description: Weis Wave volume divergence — consecutive same-direction bars aggregated into "waves"; if wave-N price extends higher (or lower) than wave-(N-1) but wave-N volume < 0.70 × wave-(N-1) volume, fade signal (countertrend reversal).
metadata: { type: hypothesis, status: pre-registered, author: researcher, date: 2026-05-14, sprint: SEC25, track: D, supersedes: null }
---

# HYP-2026-05-14-VOL-D4 — Weis Wave Volume Divergence

## Pre-Registration Disclosure (SOP-1)

**Çağrılma kararı:** SEC25 Track D — reversal/divergence ayağı. David Weis (Wyckoff
student)'in dalga-agregasyon teorisini test eder. `knowledge/books/vsa_volume_spread_analysis.md`
§5.5 ve `volume_price_divergence.md` §1 (Çok-Bar mantığı). Klasik tek-pivot OBV
divergence (`obv_engulfing_confluence`) zaten production'da; bu hipotez **dalga
toplam hacmi** (Weis) ile çalışır — yapısal olarak farklı veri agregasyonu.

**Edge persistence değerlendirmesi (`volume_price_divergence.md` §8):**
> "Weis Wave divergence — çok düşük retail kalabalığı, custom kodlama gerekli,
> edge görece korunmuş."

## İddia (testable, ölçülebilir)

**H1 (alternative):** Crypto 1d × 11 sym × 5y veride, Weis Wave Volume Divergence
patterni (ardışık eş-yönlü dalga toplam hacmi, ikinci dalga first dalga toplam
hacminin altında + yön devamı) reversal edge sağlar (both long ve short).

Pre-registered hard gates:
- n ≥ 200 (uygulamada beklenti ~250-450; iki yön kombineli)
- mR (honest clip) ≥ +0.10
- WR ≥ 45%
- shuffle p < 0.05 (n=2000)
- max_R < 10 (artifact gate)
- Symbol-out CV: max |dev| < 30%
- Per-symbol pozitif mR: en az 6/11
- Long/short ayrı: her yön n ≥ 80, her yön mR > 0
- **OOS validation:** IS=2021-2023, OOS=2024-2025; OOS mR ≥ +0.05

**H0 (null):** Pattern crypto 1d'de edge taşımıyor; mR ≤ 0 veya p ≥ 0.05.

**Counter-hypothesis (önemli):**
1. **OBV vs Weis Wave aynı bilgi — Weis hesabı eşdeğer.** `obv_engulfing_confluence`
   bir nevi bar-bar OBV divergence; Weis Wave dalga-bazında OBV divergence. Eğer
   matematiksel olarak yüksek korelasyon varsa, Weis sadece OBV'nin alt-örneklemesi
   olur — yeni edge yok.
2. Wave tanımı (ardışık eş-yönlü bar) kripto 1d'de **2-3 bar ortalama**. Bu çok
   kısa horizon — Weis literatürünün 5-15 bar dalga hedefinin altı. Wave size
   parametrik olarak değiştirilemezse (mekanik fix), pattern crypto için yanlış
   timeframe.
3. Divergence sinyalleri (klasik 2-pivot HH/LL) edge erozyonu yüksek — wholesale
   retail bilinç (`volume_price_divergence.md` §8: "Klasik MACD/RSI/MFI divergence
   minimal edge"). Weis Wave de bu sınıfa girebilir.

## Mekanik (entry/exit/filter)

**TF:** 1d daily UTC.

**Wave definition (causal):**
- Bar t bullish: `close[t] > close[t-1]` → wave_dir = +1
- Bar t bearish: `close[t] < close[t-1]` → wave_dir = -1
- Bar t flat: wave_dir = same as t-1 (or 0 if start)
- Wave aggregation: consecutive bars with same wave_dir grouped into one wave.
- Each wave has: `start_idx`, `end_idx`, `dir`, `price_high` (max high in wave),
  `price_low` (min low in wave), `total_volume` (sum of bar volumes), `n_bars`.

**Setup (SHORT — bearish divergence at top):**
- Find two consecutive UP waves W1 (older) and W2 (newer).
- `wave_high(W2) > wave_high(W1)` — fiyat yeni HH
- `total_volume(W2) < 0.70 × total_volume(W1)` — hacim divergence
- Wave size constraint: `n_bars(W1) >= 2` AND `n_bars(W2) >= 2` (avoid 1-bar
  "waves")
- Distance constraint: wave W2 ended at bar T (most recent bar); W1 ended at
  most 30 bars ago.
- Confirmation bar T+1: `close[T+1] < close[T]` (bearish — wave broke)
- Cooldown: 10 bar same direction same symbol

**Setup (LONG — bullish divergence at bottom):** mirror with DOWN waves;
`wave_low(W2) < wave_low(W1)` + `total_volume(W2) < 0.70 × total_volume(W1)` +
T+1 bullish confirmation.

**Entry:** market close[T+1] (engine: T+2 open).

**Exits:**
- SL (SHORT): `wave_high(W2) + 0.50 × ATR(20)[T-1]`
- SL (LONG): `wave_low(W2) - 0.50 × ATR(20)[T-1]`
- TP1: 1.0R — close 50%
- TP2: 2.0R — close 30%
- Runner: 20% (engine default)
- Time exit: 15 bar no progress to 1R → flat

**Lookahead audit hooks:**
- Wave aggregation pure causal (close[t] vs close[t-1])
- Wave W1 ve W2 oluşumu tamamen bar T'de bilinir (T-1 close)
- Entry on T+1 close, fill T+2 open

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
- vol_ratio_max ∈ {0.60, 0.70, 0.80} (divergence sıkılığı)
- min_wave_bars ∈ {2, 3, 4} (wave minimum boyutu)

Toplam 3×3 = 9. Bonferroni alpha = 0.00556.

**Robustness suite:**
1. IS-only gate
2. OOS gate
3. Symbol-out CV
4. Stress periods: 2022-05 LUNA, 2022-11 FTX, 2024-03 BTC ATH, 2021-04/11
   (klasik divergence periyotları)
5. **Long-side vs short-side ayrı raporlama** (yapısal yan etki kontrolü)
6. **Wave size distribution check:** ortalama wave_bars ve dağılım — eğer wave
   ortalama < 2.5 ise pattern çok kısa horizon, geçersiz

## Pass / Red Kriterleri

Aynı şablon. Ek RED-spesifik:
- **RED-OVERLAP:** ρ(weis_wave, obv_engulfing_confluence) > 0.7 → archive
  ("OBV alt-örneklemesi").
- **RED-WAVE-SIZE:** ortalama wave_bars < 2.5 ise → archive (pattern timeframe
  uyumsuz).

## Beklenen Sonuç (Bayesian prior)

- **Beklenti:** n ~200-400 (her iki yön), mR +0.08-0.15, WR 47-53% (reversal
  klasik yüksek-WR low-mR profili).
- **Sürpriz alanı:** counter-hyp #1 doğrulanırsa (OBV overlap > 0.7), Weis Wave
  yeni edge sunmaz — RED.
- **Beklenen yan-bulgu:** crypto 1d'de wave ortalama boyutu 2-4 bar; literatür
  Weis 5-15 bar dalga önerir. Crypto için 2-4 bar uygun mu? Wave size dağılımı
  buna açıklık getirir.

## Implementation Notu

- Yeni dosya: `src/price_action/strategies/weis_wave_divergence.py`
- Module-level: `STRATEGY_CLASS = 'reversal'` (yeni sınıf değil; mevcut taxonomy
  desteklemiyorsa `mean_reversion` kullan)
- Manifest pattern_ids: `weis_wave_div_long`, `weis_wave_div_short`
- Vectorized: wave grouping `np.cumsum(np.diff(sign).astype(bool))` ile pure
  vector; ama wave aggregation (sum) için groupby zorunlu — küçük for-loop ile
  wave_id türetilecek (n_bars × 11 sym küçük; performance acil değil)
- 2-bar pattern (wave T-end + confirmation T+1)

## Mevcut Pool Orthogonality Beklentisi

| Strategy | Beklenti | Sebep |
|---|---|---|
| `obv_engulfing_confluence` | **ρ ~ 0.3-0.5** | Both volume divergence, ama OBV bar-bar, Weis dalga-bazında |
| `cvd_spike_fade` | ρ ~ 0.1-0.3 | Spike fade tek bar; Weis çok bar |
| `three_push_wedge_fade` (RED) | ρ ~ 0.2-0.4 | Both 3-push exhaustion logic, ama Weis volume-centric, 3-push price-centric |
| `bb_extreme_reversal` (RED) | ρ ~ 0.0 | Different mechanism |
| `wyckoff_spring_vsa` | ρ ~ 0.0-0.2 | Spring penetration single-event; Weis sustained |

**ORTHOGONALITY SUCCESS:** `ρ(weis_wave, obv_engulfing) < 0.6`.

## Reproducibility

- Script: `scripts/sec25_volume_standalone.py`
- Strategy: `src/price_action/strategies/weis_wave_divergence.py`
- Data: 5y 11 sym
- Seed: 42, n_perm 2000

## Kaynaklar

- [VSA §5.5 Weis Wave Divergence — `knowledge/books/vsa_volume_spread_analysis.md`](`knowledge/books/vsa_volume_spread_analysis.md`)
- [Diverjans §1 Çok-Bar mantığı — `knowledge/books/volume_price_divergence.md`](`knowledge/books/volume_price_divergence.md`)
- [Diverjans §8 Weis Wave edge persistence — `knowledge/books/volume_price_divergence.md`](`knowledge/books/volume_price_divergence.md`)
- [David Weis, *Trades About to Happen* (2013)](https://www.amazon.com/Trades-About-Happen-Modern-Adaptation/dp/0470487801)
- [Sec23 RSI2 RED OOS — selection bias dersi](`reports/researcher/2026-05-14_sec23_rsi2_oos_validation.md`)
