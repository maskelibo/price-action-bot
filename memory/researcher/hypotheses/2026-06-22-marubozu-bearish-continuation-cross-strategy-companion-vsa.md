---
doc_id: researcher-20260622T140100-marubozu-bearish-continuation-cross-strategy-companion-vsa
doc_type: hypothesis
agent_id: researcher
created_at: 2026-06-22T14:01:00Z
status: DRAFT
confidence: low
depends_on:
  - configs/risk_phoenix_scalp_15m_widestop_vsa2.yaml
  - memory/shared/lessons/overfitting_red_flags.md
  - memory/shared/lessons/lookahead_zero_tolerance.md
  - memory/shared/lessons/survivorship_bias.md
blocks: []
requested_review_from:
  - lab_scientist
  - risk_officer
  - adversary_engineer
tags:
  - hypothesis
  - cross-strategy
  - companion
  - vsa-diversifier
  - marubozu
  - bulkowski
  - continuation
supersedes: null
hash: bb3eda1
---

# Hipotez: HYP-2026-06-22-MARUBOZU-CONT-VSA-COMPANION

## 1. Hipotez (pre-registered, ölçülebilir)

> **İddia:** 1D timeframe'de, mevcut bearish trend rejiminde (1W EMA50 < 1W EMA200) oluşan tek bir **bearish marubozu** (gövde / total range ≥ 0.90 ∧ close ≤ low + 0.10·range ∧ open ≥ high − 0.10·range), bar kapanışını takip eden 1D bar'ın **open'ında market short** ile, 1.5·ATR(14) initial SL ve 10-bar Donchian opposite trailing exit ile, **2020-01-01 → 2025-12-31 USDT-perpetual survivorship-bias-adjusted evreninde** aşağıdaki metrikleri tutturur:
>
> - **Annualized net return (fee + slip):** > 22%
> - **OOS Sharpe:** > 0.75
> - **MaxDD:** < 28%
> - **Profit factor:** > 1.30
> - **Trade sayısı (toplam, OOS):** ≥ 180
> - **PRIMARY KPI — vsa_climax_test ile günlük net return korelasyonu (Pearson, 250d rolling median):** |ρ| < 0.20
> - **Marginal Sharpe contribution to {vsa_climax_test + new} portföyü:** ≥ +0.25

**Cross-strategy companion gerekçesi:** Aktif `vsa_climax_test` (widestop_vsa2 family) **reversal/fade** edge'idir — climax bar'ında karşı yön. Marubozu **continuation** edge'idir — momentum trend doğrultusunda. İki yapısal olarak ZIT olduğundan korelasyon doğal olarak düşük olmalı; eğer değilse VSA'nın gerçekte ne yakaladığı ile ilgili daha ciddi bir sorun var demektir.

## 2. Null Hipotez (ne olursa çürür)

H₀: Marubozu pattern crypto-perpetual 1D'de Bulkowski'nin equity-bias'lı istatistiklerini taşımaz; getiri dağılımı shuffled-baseline ile ayırt edilemez (p ≥ 0.05) **VEYA** korelasyon ρ ≥ 0.30 — yani VSA climax'ın "tersi" değil, aynı volatility/volume sürücüsünün başka bir gölgesi.

## 3. Gerekçe — Literatür / RAG Referansları

- **[Bulkowski via book_candlestick_statistics §marubozu]:** Bearish marubozu continuation rate %64; average move %4.9; performance rank 22/103 (top quintile). **UYARI:** Bulkowski örnekleri equity, daily, 1980-2010; crypto-perp 24/7 likidite dinamiği ile generalization garantili değil.
- **[Brooks via book_brooks_deep_catalog]:** Strong trend-bar (close-at-extreme) follow-through olasılığı en yüksek olan single-bar formasyonlardan. Test-edilebilirlik 5/5 (mekanik tanım).
- **[Kaufman via book_kaufman_summary §donchian]:** 10-bar opposite Donchian trailing exit — asimetrik R-multiple yapısı (%35 WR ile pozitif beklenti çünkü winners 3-5R). Marubozu girişe trailing exit doğal eşi.
- **[Lopez de Prado via book_lopez_summary]:** 6-kriterli production-gate (DSR<0.5, PBO>0.5, IS/OOS Sharpe ratio >3, params/sample >1/30, walk-forward Sharpe varyansı > ortalama). Bu hipotez **her 6 kriteri de** geçmek zorunda; tek kırmızı = red.
- **[Chan §regime/half-life]:** Cross-strategy onboarding için OOS Sharpe gate'i tek-asset için 0.8, portföy için 1.2 (bu hipotezde 0.75 eşiği — Chan'in altında; bu kasıtlı, çünkü companion için marginal Sharpe daha önemli, tek başına Sharpe değil).

## 4. Dependent Variables (ölçülecek)

| Metric | Hedef | Reddetme |
|---|---|---|
| Annualized net return (OOS) | > 22% | < 10% |
| OOS Sharpe | > 0.75 | < 0.40 |
| MaxDD | < 28% | > 40% |
| Profit factor | > 1.30 | < 1.10 |
| Trade count (OOS) | ≥ 180 | < 100 → istatistik anlamsız |
| Pearson ρ vs vsa_climax_test (250d rolling median) | < 0.20 | ≥ 0.30 (companion değil) |
| Marginal Sharpe Δ portföye | ≥ +0.25 | < +0.10 → diversifikasyon yok |
| Bonferroni-adjusted p (shuffle baseline) | < 0.05 | ≥ 0.05 |
| DSR (Lopez de Prado) | > 0.5 | < 0.5 |
| PBO (combinatorial) | < 0.5 | ≥ 0.5 |
| IS/OOS Sharpe ratio | < 2.0 | > 3.0 (overfit) |
| Walk-forward Sharpe varyansı / ortalama | < 1.0 | > 1.0 (instabilite) |

## 5. Independent Variables (sweep edilecek)

- **body_ratio_min ∈ {0.85, 0.88, 0.90, 0.92, 0.95}** — magic-number suspect; geniş aralık zorunlu
- **wick_ratio_max ∈ {0.05, 0.10, 0.15}** — open/close ekstreme yakınlık eşiği
- **atr_stop_mult ∈ {1.0, 1.5, 2.0, 2.5}**
- **donchian_exit_n ∈ {7, 10, 14, 20}** — Turtle defaults'tan kaçınmak için 10 default'a sabitlemem; sweep zorunlu
- **trend_filter ∈ {none, 1W EMA50<EMA200, 1D EMA50<EMA200, ADX>20}** — rejim koşullu test
- **entry_timing ∈ {next_bar_open, next_bar_close_confirm}** — lookahead nötr kontrol

Parametre uzayı: 5 × 3 × 4 × 4 × 4 × 2 = **1920 kombinasyon**. Optuna n_trials = 100 (TPE + Median pruner), Benjamini-Hochberg FDR düzeltmesi zorunlu.

## 6. Beklenen p-value

- Shuffle baseline (returns permutation, 5000 iter): **ham p < 0.01** beklerim.
- Bonferroni n=100 trial: **adjusted p < 0.05** geçmek zorunda.
- Eğer FDR sonrası p ≥ 0.05 → red.

## 7. Stop Criteria (research'i ne zaman terk et)

1. **IS Sharpe < 0.5** → terk (zayıf base case).
2. **Trade count < 100 OOS** → istatistik anlamsız, terk.
3. **|ρ| ≥ 0.30 vs vsa_climax_test** → companion mantığı yok, terk (ana iddia: zıt yapıdaki edge → düşük korelasyon).
4. **Best params parametre uzayının sınırında** (örn. body_ratio = 0.95) → boundary overfit, uzayı genişlet veya terk.
5. **IS/OOS Sharpe ratio > 3** → overfit kırmızı bayrak.
6. **2022-05 LUNA, 2022-11 FTX, 2024-08 Yen carry** dönemlerinde herhangi birinde yıkıcı kayıp (>%15 1-dilim DD) → terk.
7. **Marginal Sharpe < +0.10** → portföye değer yok, terk.

## 8. Curve-Fit Şüphesi (kendime karşı paranoid kontrol listesi)

Bu hipotez yüksek curve-fit riski taşır. Aşağıdaki bayraklar EN AZ 1'i belirirse derhal red:

- **🚨 66-strateji shelf üzerinde "düşük korelasyon" araması başlı başına selection bias.** Korelasyon zarfının altından çıkanı seçmek = noise-mining. Bonferroni n=66 (Marubozu bu adaylardan biri olarak değerlendirilmeli), α'/66 = 0.00076.
- **🚨 Cross-strategy companion seed v51-v71 = 21 ardışık abort + 30+ önceki Donchian/Turtle hipotezi.** Bu seed'in toplam multiple-testing baskısı korkunç. Her yeni hipotez post-hoc α düzeltmesi gerektirir.
- **🚨 Bulkowski istatistikleri equity 1980-2010.** Crypto perp'e generalization tarihsel olarak **başarısız** (SMC dersinde 4/4 RED → memory/MEMORY.md::smc-course-no-edge.md). Marubozu bu listeye 5. olabilir.
- **🚨 body_ratio 0.90 default'u literatürden geliyor.** Tam o sayıyı "kazanan" yapan iyimser sweep → boundary overfit kontrolü zorunlu.
- **🚨 VSA + Marubozu her ikisi volatility/range-driven.** "Reversal" vs "continuation" yapısal olarak zıt görünse de aynı volatility shock'ta birlikte tetiklenebilir → korelasyon beklenenden yüksek çıkabilir. Bu olası — hipotezin en olası ölme şekli bu.
- **🚨 USDT-perp evreninde 2020-2025 sadece bear trend filtresiyle eldeki trade çoğu LUNA/FTX/2022-bear'den gelebilir.** Tek-rejim baskınlığı (regime split testi zorunlu).
- **🚨 1D + perpetual + Bulkowski + Brooks + Volman + Kaufman birleşimi narrative-attractive.** "Hikâye seni bias'lar — sayı kazanır" prensibi.

## 9. Backtest Setup (önceden dondurulmuş)

```yaml
universe: build_universe_historical(start='2020-01-01', end='2025-12-31', include_delisted=True)
timeframe_primary: 1d
trend_filter: 1w EMA50 < EMA200 (close-based, t-1 close)
fees:
  taker_bps: 7.5
  maker_bps: -1.0
slippage_bps: 5.0  # konservatif tarafta
initial_equity_usdt: 10000
risk_per_trade_pct: 1.0
sizing: ATR-based; risk_$ / (atr14_$ * sl_mult)
sl_initial: 1.5 * ATR(14)  # sweep [1.0, 1.5, 2.0, 2.5]
exit_trail: 10-bar opposite Donchian close cross  # sweep [7, 10, 14, 20]
entry: next_bar_open (no lookahead — decision on t-1 close, fill on t open)
max_concurrent_positions: 8
correlation_cap: 0.7 cluster
walk_forward:
  train_window: 3y
  test_window: 6m
  step: 3m
robustness_suite:  # SOP-3, ALL mandatory
  - param_perturbation: ±10%, 50 seeds
  - symbol_out_cv: leave-one-out
  - regime_split: bull/bear/range
  - stress_periods: [2022-05 LUNA, 2022-11 FTX, 2024-03 BTC ATH, 2024-08 Yen carry]
  - shuffle_baseline: 5000 perm, returns-permutation
  - bonferroni / FDR: trial count = 100
  - dsr_pbo: Lopez de Prado combinatorial
```

## 10. Karar Çerçevesi (sonuç geldiğinde)

1. Tüm gate'ler ✓ + |ρ| < 0.20 + marginal Sharpe ≥ +0.25 → **Lab tournament'a aday teslimi**.
2. ROI ≥ 22% AMA MaxDD > 28% / |ρ| 0.20-0.30 / marginal Sharpe 0.10-0.25 → **SOP-4b ITERATE** (risk reduction, regime subset, BE-protect). v2 pre-register.
3. Aylık ROI ≤ 0 VEYA korelasyon ≥ 0.30 VEYA Bulkowski-bias kanıtı → **gerekçeli red + learning.md'ye 3-satır kayıt**.

## 11. Reproducibility

- git_hash: bb3eda1
- config_hash: TBD (backtest config dondurulunca)
- data_hash: TBD (build_universe_historical manifest)

## 12. Pre-registration Commitment

Bu hipotezi commit ettikten sonra:
- Parametre uzayını genişletmem (sadece daraltabilirim — boundary overfit kontrolü için).
- Stop criteria'yı geri çekmem.
- Gate eşiklerini sonuçtan sonra ayarlamam (post-hoc tweaking yasak).
- "Iyi sonuç çıktı, biraz daha sweep edeyim" yasak.

## 13. Gelecek Adımlar (kısa)

1. Bu hipotezi commit et — hash dondur.
2. `backtest/engine.py` config'ini hipotezden türet, donduğunu kontrol et.
3. Lookahead test (oracle baseline) → ZORUNLU geçer.
4. Robustness suite tam koşumu.
5. Sonuçları `reports/research/2026-06-22-marubozu-companion-vsa.html` olarak yaz.
6. Lab Scientist'e tournament aday teslimi (eğer gate'leri geçerse).

---

**Reviewer notu:** Lab Scientist (drift + tournament gate), Risk Officer (sizing + leverage uyumu), Adversary Engineer (kill-probe + stress-period red team) için critique/endorse bekleniyor. 24 saat içinde yanıt yoksa CEO arbitrate.
