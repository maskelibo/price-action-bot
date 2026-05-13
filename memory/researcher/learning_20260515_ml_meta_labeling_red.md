# Learning — ML Meta-Labeling v1.1 RED (2026-05-15)

**Hypothesis:** [HYP-2026-05-15-001](hypotheses/2026-05-15-ml-meta-labeling-v1.md) — RF + purged k-fold + uniqueness weights, threshold=0.55, strategy R-based label, 6 walk-forward pencere

**Verdict:** RED (HARD GATES 6/7)

## Anahtar Sayilar

| Metric | Sonuc | Hedef | Durum |
|---|---|---|---|
| Mean Sharpe alpha | +0.8099 | >=+0.15 | PASS (anlamsiz, CI 0'i kapsiyor) |
| Bootstrap CI(95%) low | -0.9693 | >0 | FAIL |
| Mean CV AUC | 0.5274 | >=0.55 | FAIL |
| Mean overfit gap | +0.2326 | <0.15 | FAIL |
| Survival rate | %16.49 | %20-95 | FAIL |
| Shuffle p<0.05 | 1/6 | >=5/6 | FAIL |
| Bonferroni p<0.00833 | 0/6 | >=3/6 | FAIL |

## Karar Sebepleri

1. **CV AUC ~0.52** = model neredeyse random — 13 lookahead-free feature trade-level R-outcome icin yetersiz signal tasiyor.
2. **W3 outlier (alpha +5.2, p=0.020)** mean'i sisirdi ama tek pencerelik signal genelleme degil. CI [-0.97, +2.72] genis.
3. **Overfit gap +0.23** — RF max_depth=6 + 2800 sample memorize ediyor. v2'de max_depth=3-4 denenir.
4. **Survival %16.5** — threshold=0.55 cogu trade'i kesti, model "iyi trade"i tanimakta basarisiz (uniform 0.50 dolayinda dagilim).

## EER v2 + ML v1 Zincir Kaniti

| Sprint | Yaklasim | Sonuc | Ortak Tani |
|---|---|---|---|
| EER v1 (2026-05-13) | 6-dim bucket + percentile | RED bucket coverage %0 | Bucket key fazla genis |
| EER v2 (2026-05-14) | 4-dim + hierarchical + shrinkage + edge-gate | RED L1 coverage %0, edge ratio 0.39x | Trade pool top/bot R-spread yok |
| ML v1 (2026-05-15) | RF + purged CV + 13 feature + thr=0.55 | RED CV AUC 0.52 | Feature set trade-level kaliteyi predict etmiyor |

**Yapisal cikarim:** 4787 trade pool icinde mevcut feature set'i (bar/lookback/signal/context) ile **trade-level filter edge** yok. Ne bucket-based (EER) ne continuous (ML) cesidi calisiyor.

## v2 Yolu

Iki ana hipotez **birbirini desteklemeyen ipuclari** sundu:

**Yol 1 — Feature space genisletme:** Mevcut 13 feature **trade signal bar'i ve onceki birkac bar'a** odakli (bar/lookback/signal/context). Eksik: multi-TF indicators (1h/4h), alt-data continuous (funding/fng/BTC.D), market microstructure proxy (order book imbalance, taker-maker ratio). Bu feature'lar **trade-level edge** acisindan strateji onceki kararlarinda zaten kapsanmis olabilir, eklenmesi marjinal — ama denenmemis.

**Yol 2 — Regime-conditional ML:** W3 (oos 2024-11-15 -> 2025-05-15) tek pencerede +5.2 alpha. Bu pencerede ne olduguna bakmak gerek (regime, volatility, BTC trend). Eger regime-spesifik pattern varsa, **regime label'i ile koşullu ML** (ornegin BTC bull-trend periyodunda RF kullan, choppy'de skip) edge tasiyabilir.

**Yol 3 (Tavsiye edilmez ama mumkun):** XGBoost + early stopping ile ayni veri uzerinde retest. v1 RF'ti, GBM v0.9.5'te de RED'di — **ayni veri seti farkli model ile patlamaz**, edge yapisal degil tooling.

## Onerilen Sonraki Adim (Researcher)

Acilis hipotezi: **HYP-2026-05-16 — Regime-conditional ML meta-labeling.**

W3 outlier'inin OOS pencere icin BTC regime istatistiklerini topla:
- BTC ATR%, EMA200 streak, 90d DD, return 30d
- Bu pencerenin diger 5 pencereden ne ile ayrildigini cikar
- Regime label tanimi yap (ornegin "BTC bull-trend + dusuk volatilite") ve regime mask uygulayarak ML retrain et

Aksi taktirde: **Ml-yolu archive et**, Lab tournament'a flat T2 ve BALANCED ile gec.

## Robustness Bulgulari (RED'i Pekistiriyor)

| Test | Sonuc | Yorum |
|---|---|---|
| Threshold 0.50/0.55/0.60 | sapma **%532** (gate <%30) | thr=0.60'da alpha -3.5, model fragile |
| Symbol-out CV (11 sym) | max sapma **%162** | SOL drop -> alpha -0.5 (negative); model SOL'a "anchored" |
| Strategy-out CV (10 strat) | max sapma **%129** | brooks_failed_breakout drop -> alpha -0.23; tek strateji bagimli |
| Feature ablation top-5 | swing_distance_atr drop -> **alpha +103%** | Top importance feature drop edince model DAHA IYI - importance noise |
| Look-ahead audit (50) | **PASS 0/50** | Kod causality dogru, leakage yok |
| Triple-barrier sanity (sym 2.0/2.0) | TP %81 | Symmetric barrier ile bile balanced degil (1d data + 20bar holding asiri TP-favoring) |

**Yorum:** Robustness suite, RED'in cunku robust degil dahil 5 ek kanit verdi. Tek pozitif look-ahead PASS — kod implementasyonu causal, leakage yok. Ama model **edge yok ve fragile** — feature importance gurultu (top feature drop -> daha iyi), single-symbol/strategy fragility yuksek.

## Veri/Kod Tracking

- Pre-reg: `memory/researcher/hypotheses/2026-05-15-ml-meta-labeling-v1.md`
- Implementation:
  - `src/price_action/ml/meta_labeling.py` (mevcut, López §3.5/§5.2)
  - `scripts/ml_meta_labeling_baseline.py` (yeni, SECTION 2)
  - `scripts/ml_meta_labeling_walkforward.py` (yeni, SECTION 3+4)
  - `scripts/ml_meta_labeling_robustness.py` (yeni, SECTION 5)
- Sonuc: `reports/research/ml_meta_v1_results.txt` + `.json`
- Robustness: `reports/research/ml_meta_v1_robustness.txt`
- Baseline: `reports/research/ml_meta_v1_baseline.txt`

## Ne Tekrarlanmamali

1. **Pre-reg'de window sayisi yanlis tahmin** — 5y data + 3y train + 6mo OOS + 3mo step = 6 pencere kesin; "13 pencere" CEO standart aspirational. v2 pre-reg'lerinde matematiksel olarak hesaplanmali.
2. **`compute_trade_metrics` per-window total return karsilastirmasi yanlis** — n_taken farkli oldugunda compounded return apple-to-orange. Per-trade Sharpe + mean R kullanilmali.
3. **Triple-barrier pre-reg'de default yapildi**, sonra EDA ile R-based label'a gecildi. Bu HARK degil cunku model fit oncesi EDA, ama pre-reg dosyasinin ilk yazimi data inceledikten sonra yapilmaliydi (baseline once, pre-reg sonra). v2'de baseline EDA ilk adim olmali.
