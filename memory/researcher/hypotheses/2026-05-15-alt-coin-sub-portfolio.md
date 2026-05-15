# HYP-2026-05-15-alt-coin-sub-portfolio — Alt-Coin Sub-Portfolio Standalone Manifest

**Tarih (pre-reg):** 2026-05-15
**Sprint:** SEC27
**Class prior:** PASS-CANDIDATE (SEC26 forensik mekanik destek)
**Status:** COMPLETED — **VERDICT: REJECT** (pre-reg disiplini, hard gate fail)
**Sonuc:** Tüm V1-V4 variantları yıllık-delta CI_low > 0 hard gate'ini sağlamadı (p<0.0001 negatif Δ_ann). YAN-BULGU: V1/V3 r-adj +0.95/+1.17 ve DD %50 iyileşmesi (Δ_dd +17.6pp) — conservative LP variant adayı (preset variant level, production değil). Detay: [2026-05-15_sec27_alt_coin_subportfolio.md](../../../reports/researcher/2026-05-15_sec27_alt_coin_subportfolio.md) + [learning_20260515_sec27_alt_coin_reject.md](../learning_20260515_sec27_alt_coin_reject.md)

---

## 1. İddia

SEC26 forensik bulgu: **alt-coin avg mR (DOT/ADA/SOL/AVAX/MATIC) = +0.335 vs BTC mR = +0.104 = 3.22x.** Bu, sembol seçiminin alpha kaynağı olduğunu ima ediyor. Eğer trade pool'unu sadece alt-coin'lerle veya alt-coin ağırlıklı sub-universe ile filtrelersek, BALANCED champion (v2.0.3) baseline'ı **yıllık return veya r-adj** ekseninde yenebilir.

**Test:** Cached pool (`data/_sec13_4_cache/pool_baseline_v1_3.pkl`, n=6650) sembole göre filtrele. Aynı production_replay (configs/risk_balanced.yaml + halt + F&G + funding + drop_pairs + monthly_dd=0.06 hibrit) altında WF 3y rolling (13 pencere) replay et. Hard gate:

- **PASS = yıllık return Δ ≥ +10pp VEYA r-adj Δ ≥ +0.30**, ve **DD bozulma ≤ +10pp** (mutlak).
- **REJECT = aksi (concentration risk DD'yi ağırlaştırır, r-adj çakılır).**

**Bonferroni:** k=4 variant × 1 hard gate = α_adj = 0.05/4 = **0.0125** (bootstrap CI low pozitif gerek).

---

## 2. Null Hipotez

H0: Sub-universe filter (alt-only, alt+anchor) ile BALANCED baseline arasındaki yıllık return ve r-adj **istatistiksel olarak eşit** (p ≥ 0.0125 Bonferroni sonrası). **SEC13.3 (20-sym universe) RED zincir kanıtı**: alt-coin sayısını artırmak portfolio'ya seyreltici etki yapar; alt-coin sayısını azaltmak (sub-universe) **diversifikasyon kaybı** ile DD'yi şişirir. **Concentration risk** edge üstün gelir.

---

## 3. Karşı-Hipotez (H_anti)

**H_anti:** Alt-coin overweight bir manifest **DD'yi ağırlaştırır** (alt-coin'ler korelasyonu yüksek: SOL/ADA/DOT/AVAX bear regime'da senkron çakılır), r-adj **çakılır**. BTC korelasyon anchor'ı diversifikasyon yararı sağlar. **SEC13.3 ile zincir uyum**: BTC-anchor'lı 11-sym yapısal optimum.

Karşı-hipotez kanıt kriteri: V1/V2 (BTC-yok) varyantları V0 baseline'ın **DD'sini >+10pp ağırlaştırır** ama yıllık improvement <+10pp.

---

## 4. Sub-Universe Variantları

| ID | Label | Symbols | Mantık |
|----|---|---|---|
| V0 | baseline | BTC ETH SOL ADA DOT AVAX MATIC LINK BNB XRP DOGE (11) | Mevcut champion |
| V1 | alt5_only | SOL ADA DOT AVAX MATIC (5) | SEC26'da 3.22x avg mR çıkan grup |
| V2 | alt7_plus_eth | SOL ADA DOT AVAX MATIC LINK DOGE ETH (8) | BTC çıkarıldı, alt-heavy |
| V3 | alt5_btc_anchor | SOL ADA DOT AVAX MATIC + BTC (6) | Alt-heavy ama BTC korelasyon anchor |
| V4 | top_volume_5 | BTC ETH SOL BNB XRP (5) | Objektif avg-volume top-5 (alt-bias değil) |

---

## 5. Pre-Registered Metrikler (her variant için)

- yıllık return (mean, median, min, max) — 3y rolling 13 pencere, 2y train + 3mo OOS + 1mo step
- max DD (mean, median)
- r-adj = yıllık / |DD|
- negatif_pencere_sayısı
- min_pencere_yıllık (worst-case)
- n_trade
- Δ_yıllık vs V0
- Δ_r-adj vs V0
- Bootstrap 95% CI (yıllık delta, B=2000)
- p-value (paired bootstrap)

---

## 6. Hard Gate Karar Kuralı

| Variant | Δ yıllık | Δ r-adj | Δ DD (mutlak) | Bonf p-adj | Verdict |
|----|---|---|---|---|---|
| Vi | ≥+10pp **veya** ≥+0.30 | (eşlik) | ≤+10pp | <0.0125 (CI low > 0) | PASS |
| Vi | aksi | aksi | aksi | aksi | REJECT |

---

## 7. Pre-Registered Engine/Risk Konfigürasyonu

- `configs/risk_balanced.yaml` (BALANCED champion)
- monthly_dd=0.06 hibrit (long_dd=0.10 / short_dd=0.05, **mdd Hİbrit aktif değil bu sprint'te** — Champion `risk_balanced.yaml` config'i bozulmayacak; SEC15.4 side-cond mdd zaten yamanmış halde)
- BTC capitulation halt aktif (compute_btc_capitulation_halt)
- F&G short-skip ≤20 aktif (v0.9.7)
- Funding filter (00:00_only)
- DROP_PAIRS aktif (v0.9.7)
- Engine defaults: tp1_R=1.0, tp2_R=1.5, runner_trail_mult=1.5, runner_force_exit_method='time', runner_force_exit_bars=30, trail_activate_stage=2

---

## 8. Reproducibility

- Pool: `data/_sec13_4_cache/pool_baseline_v1_3.pkl` (n=6650, BTC ETH SOL ADA DOT AVAX MATIC LINK BNB XRP DOGE × 5y × TOP_11)
- Replay: `production_replay(trades, cfg)` from `src/price_action/backtest/lab.py`
- Script: `scripts/sec27_alt_coin_subportfolio.py`
- ProductionConfig: `risk_balanced.yaml` + override (drop_symbols ile sub-universe filter)

---

## 9. Stop Criteria (kod-öncesi)

- V0 baseline replay yıllık SEC11 sonucundan (+%51 → güncel +%116-136) **±15pp dışında** çakarsa, replay parity bozuk → abort + reproducibility analizi
- Bootstrap n_resample < 500 yetersiz → revise
- Tüm V1-V4 H_anti'yi doğrularsa (DD>+10pp ve yıllık<+10pp), **SEC13.3 ile zincir kanıt** olarak archive: "BTC-anchor'lı 11-sym crypto için yapısal optimum"

---

## 10. Decision Window

Sprint sonunda tablo + bootstrap CI + verdict. Eğer V1/V2 PASS:
- `configs/risk_alt_focused.yaml` (alt preset variant) yazılır
- CEO onayı + Lab tournament için aday
- Production'a CADDE eklenmez bu sprint'te

Eğer hepsi REJECT:
- `memory/researcher/learning_20260515_sec27_alt_coin_reject.md` postmortem
- `pattern_crypto_winner_anatomy.md` "diversification BTC-anchor'lı 11-sym yapısal optimum" satırı eklenir
- PA mastery gap raporu güncelleme

---

## 11. Önceki Zincir Kanıtlar (Hipotez Bağlamı)

- **SEC13.3 RED**: 20-sym universe yıllık -51pp (yeni alt-coin'ler standalone POZITIF ama portfolio'ya seyreltici, mc-12 doyumlu)
- **SEC14.0 cap probe RED**: concentration cap 0.20 → 0.30 = DD -%85.8 (felaket)
- **SEC26 forensik PASS**: alt-coin mR 3.22x BTC (mekanik destek)
- **H7 Pool Orthogonality**: max jaccard < 0.08 (alt-only filter pool çeşitliliği keser mi? Test edilecek)

Bu sprint **mekanik (mR ratio) vs sistem (DD/portfolio) çatışmasını** test ediyor.
