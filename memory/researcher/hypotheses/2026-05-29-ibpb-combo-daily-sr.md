---
doc_id: researcher-20260529T180000-ibpb-combo-daily-sr
doc_type: hypothesis
agent_id: researcher
created_at: 2026-05-29T18:00:00Z
status: PROPOSED
confidence: med
depends_on:
  - researcher-20260508-h001-baseline-pinbar-sr-trend
blocks: []
requested_review_from:
  - lab_scientist
  - risk_officer
tags: [hypothesis, pin_bar, inside_bar, combo, daily, sr, classic_pa, pre_registration]
supersedes: null
hash: null
---

# Hipotez HYP-2026-05-29-IBPB: Inside-Bar → Pin-Bar combo @ Daily S/R

## 0. Bağlam ve H-001 ile Ortogonallik (zorunlu okuma)

- **H-001 (`2026-05-08-baseline-pinbar-sr-trend.md`)** TEK-BAR pin bar @ S/R + 1W EMA50 trend filter setup'ını pre-register etti ve backtest çalıştırıldı (`memory/researcher/backtest_results/2026-05-08-baseline-pinbar-sr-trend.json`).
- Bu hipotez (HYP-IBPB) H-001'in **YERINE GEÇMEZ** ve aynı sinyali tekrar test etmez. RAG #2 (`book_extra_dailypriceaction_pin_bar_strategy`) farklı bir setup tarif ediyor: **Inside Bar bar(t-1) + Pin Bar bar(t)** kombosu, "double consolidation signal before the breakout" iddiasıyla "higher win rates than individual patterns alone".
- Ortogonallik kriteri: H-001'in trade setinin **trade-level Jaccard kesişimi ≤ %20** olmalı. Bu kesişim > %20 ise HYP-IBPB yeni edge testi DEĞİL, H-001'in alt-örneği — anlamlılık ölçütleri H-001'e bağımlı sayılır ve **bağımsız BH-FDR düzeltmesi UYGULANMAZ**, family-wise sayılır.

## 1. Iddia (pre-registered, sayısal)

> **1D timeframe'de, USDT-perpetual likit evrende (son 4 yıl, survivorship-dahil), aşağıdaki 6 koşulun TAMAMINI sağlayan ardışık `(bar_t-1, bar_t)` çiftleri, `bar_{t+1}` açılışında girilirse:**
>
> 1. `bar_{t-1}` **inside bar**: `high_{t-1} < high_{t-2}` AND `low_{t-1} > low_{t-2}`.
> 2. `bar_t` **pin bar** (Grimes mekaniği, RAG #4 + #3):
>    - `body_t = |close_t − open_t| ≤ range_t / 3`
>    - bullish: `lower_wick_t ≥ 2 × body_t` AND `close_t ≥ open_t` AND `close_t > (low_t + 2·range_t/3)`
>    - bearish: simetrik (üst fitil)
> 3. `bar_t`'in **kapanışı `bar_{t-1}` range'i içinde** kalır (RAG #2: "pin bar close contained within inside bar range").
> 4. **Key S/R proximity**: `bar_t`'in fitil ucu, son 200 bar içinde en az 2 dokunuşu olan yatay seviyenin ≤ **0.4 × ATR(14, t-1)** mesafesinde.
> 5. **Entry**: `bar_{t+1}` open, market.
> 6. **Stop**: pin bar fitil ucu ± `0.20 × ATR(14, t-1)` buffer.
> 7. **Target**: sabit **2R** (sabit; trail/runner YOK — pre-commit, exit-optimizasyon p-hacking riski).
>
> İddia: in-sample (2021-01-01 → 2024-06-30) ve out-of-sample (2024-07-01 → 2026-05-15) dilimlerinde **AYNI ANDA** şu eşikleri geçer:
>
> - Annualized net return (fee+slip dahil) > **%40** (her iki dilimde)
> - Sharpe (daily, no-rebalance) > **0.9** (her iki dilimde)
> - MaxDD < **%25** (her iki dilimde)
> - Profit factor > **1.4** (her iki dilimde)
> - Win-rate ∈ [%38, %55] (out-of-range → RR rejimi şüpheli, kırmızı bayrak)
> - Trade sayısı in-sample N ≥ **120** (yetersizse hipotez underpowered, reddedilir)
> - Shuffle-baseline (R-sign flip null, 5000 perm) p < **0.01**
> - H-001 ile **trade-level Jaccard ≤ 0.20**

## 2. Null Hipotezi (ne çürütür)

> H0: IBPB kombo'sunun mean trade-R'si, aynı evrende **random-entry baseline** (her gün rastgele bir long veya short, aynı SL/TP geometrisiyle) dağılımının %95 üst kuyruğunda DEĞİL.
>
> Çürütme yolları (herhangi biri TEK BAŞINA hipotezi reddeder):
> 1. In-sample Sharpe < 0.5 → SOP-1 stop criterion.
> 2. OOS Sharpe IS Sharpe'tan **%40+** düşük → IS-overfit kırmızı bayrak (eşik H-001'in %50'sinden DAHA SIKI çünkü combo pattern serbestlik derecesi daha az).
> 3. IS ya da OOS MaxDD > %30 → reddedilir (risk gate).
> 4. Walk-forward (3y/6m, step 3m) dilim sayısı < N_total, **< %55**'i pozitif → unstable.
> 5. Shuffle-baseline p > 0.01 → edge sıfırdan ayırt edilemiyor.
> 6. H-001 ile Jaccard > %20 → ortogonal değil, reddedilir.

## 3. Gerekçe (RAG — literatür referansları)

| RAG # | Kaynak | İddiaya katkı |
|---|---|---|
| #2 | `book_extra_dailypriceaction_pin_bar_strategy` | IBPB kombosu "daily-only", "key S/R", "pin close within inside range" → spec'in 1+3 maddelerinin birebir kaynağı; "higher win rate than individual patterns alone" iddiasının test edilmesi. |
| #3 | `book_extra_dailypriceaction_pin_bar_strategy` | Pin bar mekanik tanımı: tail ≥ 2/3 range; close near opposite end. |
| #4 | `book_grimes_summary` | Grimes geometric pin bar tanımı: gövde ≤ 1/3 range, wick:body ≥ 2:1; kapanış fitilin ters 1/3'ünde. Spec maddesi 2 birebir Grimes. |
| #1 | `book_extra_dailypriceaction_pin_bar_strategy` | "Confirming factors": well-formed at key levels (madde 4), multi-timeframe alignment — daily-only kararının gerekçesi (sub-daily PA'de IBPB güvenilirliği RAG'e göre düşük). |
| #5 | `book_extra_dailypriceaction_pin_bar_strategy` | Stop = pin bar fitil ucu + 10-20 pip buffer → spec maddesi 6 (kripto'da pip yerine 0.20 ATR kullanıldı). |
| #9 | `book_grimes_summary` | Grimes: pin bar S/R + 20/50 SMA + round number confluence; min 2 confluence şartı — IBPB'de 2 confluence inherent (S/R + IB consolidation). |

**Kaynak boşlukları (dürüst şerh):**
- RAG #2 IBPB için **somut hit-rate sayısı vermiyor**, sadece "higher than individual" iddiası. Bu yüzden iddia eşiklerini H-001 baseline'ından **AŞAĞI** çektim (%50 → %40 annualized; Sharpe 1.0 → 0.9). Eğer literatür sayısı verseydi, ona göre kalibre ederdim; sayı yok → konservatif.
- RAG'de IBPB için cross-validated istatistik (Bulkowski-tarzı reversal rate) **YOK**. RAG #7 outside bar için Bulkowski %63-65 veriyor ama IBPB için yok. Bu, hipotezin literatür-zayıf yanı — bir kırmızı bayrak.

## 4. Bağımlı Değişkenler (pre-registered, sıkı liste)

Ölçülecek ve raporlanacak — gizli metrik ekleme yasak (HARKing önleme):

1. `annualized_net_return` (fee+slip sonrası)
2. `sharpe_ratio` (daily returns, no risk-free)
3. `max_drawdown` (continuous, peak-to-trough)
4. `profit_factor`
5. `win_rate`
6. `expectancy_R`
7. `avg_holding_bars`
8. `trade_count` (IS + OOS ayrı)
9. `shuffle_p` (5000 perm, sign-flip null)
10. `jaccard_overlap_with_H001` (trade-level)
11. `walkforward_positive_slice_pct`

## 5. Bağımsız Değişkenler (DAR grid — pre-commit)

**Kırmızı bayrak önleme:** parametre uzayını dar tut. Her eksende 2-3 değer, KENAR DEĞER seçilirse otomatik red.

| Param | Grid (pre-commit) | Default | Kenar-red kuralı |
|---|---|---|---|
| `wick_body_ratio_min` | {2.0, 2.5, 3.0} | 2.0 | best = 2.0 veya 3.0 → kenar, daha geniş grid + re-test gerekir |
| `body_max_pct_of_range` | {0.30, 0.33} | 0.33 | best = 0.33 → kenar |
| `sr_proximity_atr` | {0.3, 0.4, 0.5} | 0.4 | best = 0.3 veya 0.5 → kenar |
| `sr_min_touches` | {2, 3} | 2 | — (binary, kenar yok) |
| `sr_lookback_bars` | {150, 200, 250} | 200 | best = 150 veya 250 → kenar |
| `atr_period` | {14} | 14 | sabit — opt yok |
| `sl_buffer_atr` | {0.15, 0.20, 0.25} | 0.20 | best = 0.15 veya 0.25 → kenar |
| `tp_R_multiple` | {2.0} | 2.0 | **SABİT, opt YOK** — RR optimize edilirse exit p-hacking |
| `trend_filter` | {none, 1W_EMA50, 1W_EMA200} | 1W_EMA50 | — |

**Toplam parametre kombinasyonu:** 3 × 2 × 3 × 2 × 3 × 1 × 3 × 1 × 3 = **324**.
**Multiple-testing düzeltmesi:** Bonferroni `α_per_test = 0.05 / 324 ≈ 1.54 × 10⁻⁴` (zorunlu).

## 6. Beklenen p-value

- **Shuffle-baseline (sign-flip null, 5000 perm) p < 0.01** — single best config için.
- **Bonferroni-düzeltilmiş best config p < 1.54 × 10⁻⁴** — yoksa "best" bir grid arama artefaktı sayılır.
- **Benjamini-Hochberg FDR @ q=0.10** — IS top-10 config OOS'ta ne kadar dayanıyor; FDR sonrası 0 survivor → red.

## 7. Stop Criteria (kod yazmadan önce taahhüt)

| Tetik | Aksiyon |
|---|---|
| In-sample Sharpe < 0.5 | araştırma terkedilir (SOP-1) |
| OOS Sharpe < 0.6 | RED, gerekçeli arşiv |
| IS / OOS Sharpe farkı > %40 | RED (overfit kırmızı bayrak) |
| Best param grid kenarında | RED + grid genişletme önerisi (yeni hipotez ID gerekir) |
| Trade sayısı IS N < 120 | UNDERPOWERED, deferred (daha uzun veri veya simetri farklı hipotez) |
| Walk-forward < %55 pozitif dilim | RED (unstable) |
| Bonferroni p > 1.54 × 10⁻⁴ | RED (multiple-testing tehdidi yenilemedi) |
| Shuffle-baseline p > 0.01 | RED (random-entry'den ayırt edilemiyor) |
| H-001 ile Jaccard > %20 | RED (ortogonal değil; H-001'in alt-örneği) |
| Aynı pozitif edge **AMA** MaxDD > %25 | **REDDETME** → SOP-4b iterate (risk_pct düşür, partial TP, BE-protect) |

## 8. Curve-Fit Kırmızı Bayrak Pre-Commit Listesi

**Persona Hard-Limit:** "parametre uzayı çok ince, best params ekstrem değerlerde, in-sample/out-of-sample fark > %50 → hipotezi reddet."

Aşağıdaki bayrakların **herhangi biri** post-hoc gözlemlenirse hipotez RED (gate-pass etse bile):

1. ✋ Best `wick_body_ratio_min` ya 2.0 ya 3.0 (kenar).
2. ✋ Best `sr_proximity_atr` ya 0.3 ya 0.5 (kenar).
3. ✋ IS top-1 ve OOS top-1 config'leri **farklı** → instability.
4. ✋ Parametre perturbasyonu (±%10, 50 seed) altında ortalama Sharpe kaybı > %30.
5. ✋ Stress periodlarının (2022-05 LUNA, 2022-11 FTX, 2024-08 Yen) **birinde** -%15+ kayıp.
6. ✋ Tek bir periyot/sembol toplam P&L'in > %40'ını üretiyor → tail-event tabanlı, generalize etmez.
7. ✋ "Sayı zayıf ama hikâye çok mantıklı" → narrative bias self-check, RED.

**Curve-fit şüphesi yaratan mekanizmaları AÇIKÇA kaydet:** bu hipotez 324 grid noktası tarıyor → null hipotezi altında bile ~16 false-positive bekleniyor (α=0.05). Bonferroni düzeltmesi olmadan herhangi bir "best Sharpe" rastlantı sayılır. Bu, multiple-testing kontrolünün NEDEN zorunlu olduğunu gösteren in-design curve-fit riskidir.

## 9. Veri ve Reproducibility

- **Universe:** `configs/symbols.yaml::universe.mode = all_liquid_with_delisted`, 2021-01-01 → 2026-05-15.
- **Survivorship:** delisted semboller delisting tarihine kadar dahil (shared-lesson: survivorship-bias-crypto).
- **Fees:** 7.5 bps taker, -1 bp maker (Binance USDT-perp historic ortalaması).
- **Slippage:** 5 bps base + ATR-scaled add-on (data quality lesson).
- **Funding rate:** dahil (long pozisyonlar pozitif funding'te penalize edilir).
- **git_hash:** `<backtest run sonrası doldurulacak>`
- **config_hash:** `stable_hash(ibpb_combo_v1.yaml + risk.yaml)`
- **data_hash:** `stable_hash(universe + date_range + dataset_version)`

## 10. Sonuçlar (boş — backtest sonrası doldurulacak)

- [ ] In-sample metrikler tablosu
- [ ] Out-of-sample metrikler tablosu
- [ ] Walk-forward (dilim sayısı / pozitif oranı)
- [ ] Robustness suite (8 test SOP-3)
- [ ] Shuffle baseline p
- [ ] Bonferroni-survived count
- [ ] Jaccard vs H-001
- [ ] Curve-fit kırmızı bayrak check
- [ ] Karar: terfi adayı / iterate (SOP-4b) / red

## 11. Notlar

- **Ortogonal değer:** H-001 tek-bar pin bar test ediyor; IBPB iki-bar consolidation+rejection kombosu. RAG #2 "higher win rate than individual" iddiası test edilmemiş.
- **Riskli yan:** RAG'de IBPB için sayısal istatistik yok; iddia eşiklerini konservatif tuttum.
- **Iterate yolu (SOP-4b — zorunlu):** Aylık ROI > 0 ama DD > %25 ise REDDETME → v2 (risk_pct ↓, partial TP 0.5R, BE@1R) açılır. Pozitif edge nadir kaynak.
- **CEO için bağlam:** classic_pa stratejisinin baseline'ı H-001; IBPB onun ortogonal kuzeni olarak portföye ek-bağımsız bacak sağlayabilir. Combo eşik daha sıkı → trade sayısı baseline'dan az olacak; portföy-bağımsızlık değeri Lab tournament tarafından değerlendirilir.
