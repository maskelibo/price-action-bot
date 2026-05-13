---
hypothesis_id: 2026-05-15-ml-meta-labeling-v1
date: 2026-05-15
author: researcher_agent (claude-opus-4-7-1m)
status: PRE_REGISTERED (v1.1 — post-baseline EDA revision, model fit oncesi)
version: 0.1.1
parent_strategy: none (overlay — trade quality filter)
parent_hypothesis: 2026-05-14-eer-score-v2 (RED — bucket coverage L1=%0, edge ratio 0.39x; structural finding: trade pool top/bot R-spread yok)
parent_attempt: scripts/v095_ml_trade_scoring.py (v0.9.5 RED — aggregate trade scoring, GBM, OOS gain yetersiz)
tags: [ml, meta_labeling, lopez_de_prado, triple_barrier, purged_kfold, walk_forward, leakage_audit, random_forest]
backtest_possible: true
data_requirements: [4787-trade pool (5y Top 10 strat x 11 sym), OHLCV per symbol 1d (cached), funding_BTCUSDT.csv (optional), fng_daily.csv (optional)]
expected_correlation_w_conf: low (target <0.30, since RF features overlap minimally with confluence)
git_hash_at_registration: b98f3ad4db31b559d7409beeba1a1fb8b317b6c5
analyst_input: memory/researcher/hypotheses/2026-05-14-eer-score-v2.md section 11 (Implikasyonlar FAIL → ML meta-labeling alternatif)
ceo_brief_ref: production lock = v0.9.7 BALANCED+F&G (3y rolling +%36.1 / DD -%30); ML filter UPLIFT olmali baseline'in ustune
---

# HYP-2026-05-15-001 — ML Meta-Labeling v1 (Triple-Barrier + Purged CV + Random Forest, Trade-Level Filter)

## 1. Pre-Registered Iddia (TEK CUMLE — v1.1)

> EER v2'nin bucket-based yaklasimi yapısal olarak basarisiz oldugu icin (L1 coverage %0, edge ratio 0.39x), trade-level continuous features uzerine **López de Prado meta-labeling** (RF + purged k-fold CV + uniqueness weights, **strategy R-based binary label** y=1 if R>0 else 0) **threshold=0.55** ile uygulandiginda, **walk-forward 6 pencerede flat T2 baseline'a karsi mean Sharpe alpha >= +0.15** uretir + **shuffle null p<0.05 >= 5/6 pencere** + **Bonferroni-adjusted p<0.05/6 >= 3/6 pencere** + **bootstrap CI(95%) low > 0**.

**v1.1 REVISION (post-baseline EDA, 2026-05-15):**
- `n_windows: 13 -> 6` (5y data + 3y train + 6mo OOS + 3mo step matematiksel sonucu — EER v2 ile ayni de facto durum)
- `label: triple_barrier -> strategy_R_based` (triple-barrier %81 imbalanced + mean_holding 1.48 bar = noise; strategy R-based %50.45 balanced + gercek strateji edge predict)
- Triple-barrier kalir: SECTION 5 robustness/sanity check icin (atr_mult sym 2.0/2.0 ile)
- Gates orantili: shuffle 10/13 -> 5/6, Bonferroni 7/13 -> 3/6 (alpha_adj = 0.05/6 = 0.00833)

**Bagimli degiskenler:**
- OOS Sharpe alpha (ML_filter - flat_T2_baseline) per window
- OOS yillik net return alpha
- Trade survival rate (n_taken / n_total) per window
- CV mean AUC per window (overfit gap = train_acc - cv_acc)
- Shuffle null p-value
- Feature importance distribution

**Bagimsiz degiskenler (pre-registered DEFAULT — sweep YASAK):**
- model = RandomForestClassifier(n_estimators=200, max_depth=6, min_samples_leaf=5, class_weight="balanced", random_state=42)
- threshold = 0.55 (P(win) >= threshold => trade alinir)
- triple_barrier: atr_mult_tp=2.0, atr_mult_sl=1.0, max_holding=20 bar
- purged_kfold: cv=5, embargo_bars=5
- features = engineer_features() default 13: atr_pct, kaufman_er, body_ratio, close_to_ema20_pct, close_above_200ema, volume_z, rolling_5d_return, rolling_20d_return, rolling_5d_vol, confluence_score, near_sr, swing_distance_atr, rolling_60d_sharpe
- uniqueness sample weights = López §3.5 (zaten implementli)
- baseline = flat T2 sizing (her trade %2 risk, 2x lev) — EER v2 ile ayni baseline
- walk-forward = 3y train + 6mo OOS + 3mo step => 13 pencere

**Null hipotez (HERHANGI biri PASS olursa hipotez RED) — v1.1:**
1. Mean OOS Sharpe alpha (ML_filter - flat_T2) < +0.15
2. Bootstrap CI(95%) low <= 0 (Sharpe alpha)
3. Shuffle null pass < 5/6 pencere (p<0.05)
4. Bonferroni-adj pass < 3/6 pencere (p<0.00833 = 0.05/6)
5. Mean CV AUC < 0.55 (model real-edge bulamiyor — random'dan iyi degil)
6. Mean overfit gap (train_acc - cv_acc) > 0.15 (asiri overfit)
7. Trade survival rate < %20 OR > %95 (asiri filtrelendi veya filtre etkisiz)

---

## 2. Motivasyon — EER v2 Postmortem + v0.9.5 ML Postmortem

### EER v2 (2026-05-14) RED bulgulari:
| Bulgu | Karsi-hipotez | ML v1 Cozumu |
|---|---|---|
| L1 bucket coverage = %0 (4-dim hala genis) | Bucket count yapisal sinirli | **Continuous features** — her trade icin ayri RF score, bucket yok |
| Edge ratio 0.39x (top vs bot avg_R) | Top/bot trade arasinda R-spread yok | RF non-linear etkilesim ile **bucket-yapamayan** ayrimi yakalayabilir |
| Tier sizing flat T2'yi -0.185 Sharpe yendi | EER metric kalite skoru degil | RF P(win) **direct binary classification** — sizing degil filter |
| Shuffle p<0.05 = 0/6 pencere | EER ranking gurultu | Uniqueness weights + purged CV ile leakage-free signal |

### v0.9.5 ML (scripts/v095_ml_trade_scoring.py) RED nedenleri:
- GradientBoostingClassifier kullanildi, **purged k-fold YOK** (sequential CV — leakage riski)
- Aggregate trade scoring (her trade ayri sample, **uniqueness weighting YOK** — overlapping label intervals)
- 4787 trade'in butunsel feature engineering — strategy/symbol stratifikasyonu yok
- **López de Prado yontemleri eksikti** — bu pre-reg tam López §3.5 + §5.2 protokolu

### v1 ile farklilik:
- **RF yerine GBM** (zaten yukarida). RF: out-of-bag sample weights + parallel + interpretable feature importance.
- **Triple-barrier labeling** (sl/tp/timeout) — gercek kazanma binary etiketi, raw R degil
- **Purged k-fold CV** — overlapping label intervals problemi cozer (López §5.2)
- **Uniqueness weights** — concurrent samples downweight (López §3.5)
- **Threshold filter** — sizing degil, "take/skip" binary karari (EER tier sizing'in yapisal sinirini bypass eder)

---

## 3. Mekanik Kurallar — v1 Spesifik

### 3.1 Strategy R-Based Labeling (v1.1)

**v1 (deprecated, kept for sanity check):** Triple-barrier (atr_mult_tp=2.0, atr_mult_sl=1.0, max_holding=20). Baseline EDA bulgusu: %81 TP rate, mean_holding 1.48 bar — daily ATR uzerinde 20-bar holding asiri TP-favoring.

**v1.1 (kullanilan label):**
```python
y = (trade_df["R"] > 0).astype(int)
# Class balance: 0.5045 (2415 win / 2372 loss) - perfect balance
```

**Mantik:** Meta-labeling canonical kullanim — strateji zaten karar verdi, biz bu kararin kalitesini predict ediyoruz. Strateji'nin gercek exit logic'i (TP/SL/trail) ile elde edilen R, "bu trade alinmali miydi" sorusunun ground truth'udur. Triple-barrier ayri exit kurallari ile relabel etmek strateji edge'inden uzaklasir.

**Triple-barrier yine de calistirilir:** SECTION 5 robustness icin (atr_mult sym 2.0/2.0 ile balanced retest). Concordance metric raporlanir.

### 3.2 Feature Engineering (lookahead-free, 13 dim)

`engineer_features()` zaten implementli. Kullanilacak feature listesi (TUM SABIT, ekleme YASAK):

| # | Feature | Kategori | Hesap |
|---|---|---|---|
| 1 | atr_pct | Bar | atr14/close |
| 2 | kaufman_er | Bar | Kaufman Efficiency Ratio (14 bar) |
| 3 | body_ratio | Bar | abs(close-open)/(high-low) |
| 4 | close_to_ema20_pct | Bar | (close-ema20)/ema20 |
| 5 | close_above_200ema | Bar | 1/0 boolean |
| 6 | volume_z | Bar | 60-bar volume z-score |
| 7 | rolling_5d_return | Lookback | 5-bar log return |
| 8 | rolling_20d_return | Lookback | 20-bar log return |
| 9 | rolling_5d_vol | Lookback | 5-bar return std |
| 10 | confluence_score | Signal | Strateji metadata |
| 11 | near_sr | Signal | Strateji metadata 1/0 |
| 12 | swing_distance_atr | Signal | (close-sl_price)/atr |
| 13 | rolling_60d_sharpe | Context | 60-bar rolling Sharpe |

**Causality:** Tum feature'lar trade signal_ts bar'inda hesaplanir, sonraki bar'lardan veri YASAK. Mevcut `engineer_features()` implementi bu kuralari saglar (line 186-355).

### 3.3 Purged k-fold CV (López §5.2)

```python
splits = _purged_kfold_splits(
    labels_df=labels,
    n_folds=5,
    embargo_bars=5,
)
```

- Test fold'un [t0_min, t1_max] araligini iceren tum train sample'lari **purge** (drop)
- Test fold'tan sonra `embargo_bars=5` ek bar'i da purge
- Ozellikle multi-symbol pool icin: bir trade'in label window'u (entry_bar to exit_bar) baska bir trade'in feature timestamp'i ile cakisirsa, leakage riski → purge

### 3.4 Uniqueness Sample Weights (López §3.5)

```python
weights[i] = mean(1 / c_t for t in [t0_i, t1_i])
```

c_t = bar t'de overlap eden label sayisi. Concurrent label'lar downweight. Yuksek-konsantre periyodlar (multi-strat ayni tarihte ate$ler) tek sample agirligina cekilir.

### 3.5 Random Forest (Pre-Registered SABIT)

- n_estimators = 200
- max_depth = 6
- min_samples_leaf = 5
- class_weight = "balanced"
- random_state = 42
- n_jobs = -1

**YASAK:** GridSearchCV, RandomizedSearchCV, hiperparametre sweep. Bu pre-reg fix degerler.

### 3.6 Threshold Filter (Pre-Registered)

```python
mask = predict_filter(model, X_oos, threshold=0.55)
# mask True => trade alinir, False => skip
```

threshold=0.55 baseline. Robustness suite icinde 0.50/0.55/0.60 DIAGNOSTIC sweep (default 0.55 ile karar).

---

## 4. Walk-Forward Protokolu

### 4.1 Pencere Yapisi (CEO standart)

- Train: 3 yil
- OOS: 6 ay
- Step: 3 ay
- 5y data => 13 pencere

### 4.2 Per-Window Pipeline

```
for window in 13_windows:
    1. train_signals = trades in [train_start, train_end)
    2. oos_signals   = trades in [train_end, oos_end)
    3. labels_train = triple_barrier_labels(ohlcv_per_sym, train_signals)
    4. X_train      = engineer_features(ohlcv_per_sym, train_signals)
    5. X_oos        = engineer_features(ohlcv_per_sym, oos_signals)
    6. y_train      = (labels_train.label == 1).astype(int)
    7. clf, metrics = train_rf(X_train, y_train, labels_df=labels_train, cv=5)
    8. mask_oos     = predict_filter(clf, X_oos, threshold=0.55)
    9. ml_trades    = oos_signals[mask_oos]
    10. baseline_trades = oos_signals  # all trades, flat T2
    11. record per-window:
        - ml_sharpe, ml_return, ml_dd, n_taken, cv_auc, train_acc
        - baseline_sharpe, baseline_return, baseline_dd
        - sharpe_alpha = ml_sharpe - baseline_sharpe
        - shuffle_null_p (200 iter, label permutation)
```

### 4.3 Shuffle Null

```python
for window:
    real_alpha = ml_sharpe - baseline_sharpe
    null_dist = []
    for _ in range(200):
        y_shuffled = shuffle(y_train)
        clf_null = train_rf(X_train, y_shuffled, ...)
        mask_null = predict_filter(clf_null, X_oos, 0.55)
        null_alpha = sharpe(oos_trades[mask_null]) - baseline_sharpe
        null_dist.append(null_alpha)
    p_value = mean(null_dist >= real_alpha)
```

### 4.4 Bonferroni Adjustment

13 pencere => alpha_adj = 0.05/13 = 0.00385. Per-window p<0.00385 olmali, en az 7/13 pencere.

### 4.5 Bootstrap CI

2000 iter, replacement-with sample. Mean Sharpe alpha (across 13 windows) icin 95% CI alt sinir > 0 olmali.

---

## 5. Robustness Suite (DIAGNOSTIC — Promosyon Icin Degil)

| Test | Yapilis | Gate |
|---|---|---|
| Threshold duyarlilik | 0.50/0.55/0.60 | Sharpe alpha sapma <%30 |
| Symbol-out CV | 11 sym, her birini drop | OOS Sharpe alpha sapma <%30 |
| Strategy-out CV | 10 strat, her birini drop | OOS Sharpe alpha sapma <%30 |
| Feature ablation top-5 | Her birini drop, retrain | Sharpe alpha sapma <%50 |
| Look-ahead audit | 50 random trade, manuel feature timestamp | %100 causal |
| Class imbalance check | y.mean() per window | 0.30 < y.mean() < 0.70 (balanced) |
| Overfit gap | train_acc - cv_mean_acc | < 0.15 (HARD GATE) |

---

## 6. Beklentiler (Sayisal Hedef)

| Metric | Beklenti | Gate |
|---|---|---|
| Mean Sharpe alpha (ML_filter - flat_T2) | +0.20 ile +0.50 | >= +0.15 |
| Mean return alpha | +5pp ile +12pp | >= +3pp |
| Mean trade survival rate | %50-75 | %20-95 |
| Mean CV AUC | 0.58-0.65 | >= 0.55 |
| Mean overfit gap | <0.10 | <0.15 |
| Shuffle p<0.05 windows | 10-13 | >= 10 |
| Bonferroni p<0.00385 windows | 8-13 | >= 7 |
| Bootstrap CI low | >0 | >0 |
| Top-3 feature importance | toplam <%70 | concentration check (asiri tek-feature dominansi yoksa) |

---

## 7. Reproducibility

```
git_hash: b98f3ad4db31b559d7409beeba1a1fb8b317b6c5
config_hash: stable_hash({
    model: "RandomForestClassifier",
    n_estimators: 200,
    max_depth: 6,
    min_samples_leaf: 5,
    class_weight: "balanced",
    random_state: 42,
    threshold: 0.55,
    triple_barrier: {atr_mult_tp: 2.0, atr_mult_sl: 1.0, max_holding: 20},
    purged_kfold: {n_folds: 5, embargo_bars: 5},
    features_used: 13,  # engineer_features default
    walk_forward: {train_y: 3, oos_mo: 6, step_mo: 3, n_windows: 13},
    baseline: "flat_T2_2pct_2x"
})
data_hash: stable_hash(
    v091_trades_2025_2026_detail.csv (4787 trade) +
    OHLCV_11_symbol_1d_5y +
    NOT_USED_v1: funding, fng (continuous feature olarak v2'de denenebilir)
)
```

Implementation:
- `src/price_action/ml/meta_labeling.py` (mevcut — triple_barrier_labels, engineer_features, train_rf, predict_filter)
- `scripts/ml_meta_labeling_walkforward.py` (YENI — bu sprint)
- `tests/test_meta_labeling.py` (mevcut — augment edilebilir)
- Output: `reports/research/ml_meta_v1_results.txt`

---

## 8. Karsi-Hipotezler

**KH-1: Feature leakage (rolling indicators).**  rolling_5d_return, rolling_20d_return, rolling_60d_sharpe — bu indicator'lar **trade entry bar'i dahil** mi yoksa **bir bar onceki kapanis** mi? `engineer_features()` line 226-263 kontrolu: rolling pencerele bar i'deki kapanis fiyati ile hesaplaniyor (sig_ts bar'i AT). Bu causal — gelecek veri yok. **Robustness audit:** 50 random trade icin manuel timestamp dogrulamasi.

**KH-2: Overfit (RF max_depth=6 + 200 trees).**  4787/13 = ~368 trade/pencere train. Her pencerede feature/sample ratio = 13/(368*0.8) = ~0.044. Overfit riski orta. **Gate:** train_acc - cv_acc <0.15. Eger >0.15 ise max_depth=4'e dusurulur (v2 pre-reg).

**KH-3: Class imbalance (TP rate düşük).**  Trade pool R-multiple ortalama +0.026 (HTF momentum quick test). TP=2R/SL=1R triple-barrier ile y=1 (TP hit) orani %30-40 olabilir. class_weight="balanced" bunu telafi eder ama eger y.mean()<0.20 ise SMOTE (López §3.6) v2'ye eklenebilir. **Gate:** 0.30 < y.mean() < 0.70.

**KH-4: Threshold 0.55 anti-edge.**  Eger model baseline AUC=0.55 (zayif) ise threshold 0.55 = "median" filter, hicbir trade elimine edilmez. Robustness 0.60 ile retest. **Gate:** trade survival %20-95 araligi.

**KH-5: Symbol-specific overfit.**  RF tum 11 sembol birlestirilmis trade pool'unda egitilir. Tek sembolun (ornegin BTC) yuksek-trade sayisi modeli o sembole "anchor" eder. Symbol-out CV bu riski olcer. **Gate:** Sharpe alpha sapma <%30 herhangi bir sembol drop ile.

**KH-6: López uniqueness weights yetersiz.**  Multi-strat × multi-sym pool = yuksek concurrent label overlap. _compute_sample_weights c_t hesabi sadece ayni timeline'da overlap'e bakar; cross-symbol farkli timeline ise overlap=0 (her sample uniqueness=1). **Mitigation:** Triple-barrier per-symbol calistirilir (zaten oyle yapilmali — engineer_features sembol bazli ohlcv alir).

**KH-7: v0.9.5 RED tekrarlanir.**  Eger ML_filter Sharpe alpha < +0.15 cikarsa, ek 6 pre-reg degisken ile v2 kapida (XGBoost, multi-TF features, alt-data continuous, etc.). Bu pre-reg v1 sonucuyla ML yolunun tukenmedigini test eder.

---

## 9. Karar Akisi

```
1. SECTION 2: scripts/ml_meta_labeling_baseline.py — pool, label, feature dist (go/no-go raporu)
2. SECTION 3: scripts/ml_meta_labeling_walkforward.py yaz
3. 13 pencere walk-forward calistir
4. Shuffle null (200 iter/pencere)
5. Bootstrap CI (2000 iter, mean Sharpe alpha)
6. Bonferroni p degerleri
7. SECTION 5: Robustness suite (DIAGNOSTIC)
8. Gate kontrolu:
   - Mean Sharpe alpha >= +0.15
   - Shuffle p<0.05 >=10/13 pencere
   - Bonferroni p<0.00385 >=7/13 pencere
   - Bootstrap CI low > 0
   - Mean CV AUC >= 0.55
   - Mean overfit gap <0.15
   - Trade survival %20-95
9. PASS => DYNAMIC v2 sizing'e ML filter entegrasyonu (predict_filter wrap)
   FAIL => learning log + v2 pre-reg (XGBoost veya feature space genisletme)
```

---

## 10. Implikasyonlar (PASS senaryosu)

1. DYNAMIC v2 = flat T2 sizing + ML filter (P(win) >= 0.55 ise trade alinir).
2. v0.9.7 BALANCED+F&G uzerine UPLIFT: yillik %36 -> %42-48 hedef.
3. Trade survival %50-75 ise position count ~yari, capital efficiency artar.
4. Lab W3 tournament: BALANCED (champion) vs flat_T2 (baseline) vs ML_filter (challenger).
5. ML filter v0.9.5 GBM yaklasimini gecerse, **trade-level ML kapisi acik** demek — multi-TF features, alt-data continuous, ensemble v2'ye yol acar.

---

## 11. Implikasyonlar (FAIL senaryosu)

1. Trade pool yapisi ML icin de yetersiz (4787 sample, 13 feature, 5y) — overfit/underfit dengesi tutmuyor.
2. Alternatif yollar (v2'de pre-reg):
   a. **Feature space genisletme** — multi-TF (1h/4h indicators), alt-data (funding/fng/BTC.D continuous), market microstructure proxy
   b. **XGBoost veya LightGBM** — RF yerine gradient boosting
   c. **Ensemble** — RF + GBM + LR + voting
   d. **TabNet veya tabular DL** — son care
3. Lab W3 tournament: sadece flat_T2 baseline vs BALANCED+drop_pairs (ML hatti tukendi).
4. CEO brief'e: "trade-level meta-labeling bu pool icin yapisal sinirli, regime-level filter veya yeni strateji sinifi gerekli" memo.

---

## 12. Limit ve Yasaklar (HARK Koruma)

- ❌ n_estimators, max_depth, min_samples_leaf, threshold, atr_mult, max_holding — TUMU pre-registered SABIT.
- ❌ Feature ekleme (funding/fng/BTC.D v1'de YOK, v2'de pre-reg).
- ❌ Robustness sweep'lerin "en iyi" degerini default secip yeniden test (HARK).
- ❌ Class imbalance icin ek sampling (SMOTE) — v1'de YOK, v2'de pre-reg.
- ❌ Test FAIL oldugunda v2 pre-reg etmeden once **learning log** yazilmali (`memory/researcher/learning_*.md`).
- ❌ predict_filter threshold'unu OOS ile tune etmek YASAK (in-sample CV ile validate edilen tek deger).

---

## Sonuclar (2026-05-15 walk-forward sonrasi DOLDURULDU)

- [x] Mean Sharpe alpha (ML_filter - flat_T2, target >=+0.15): **+0.8099** (PASS yuzde olarak ama CI cok genis)
- [x] Mean return alpha (target >=+0.03): **-138.49** (compounding asimetri — bkz sec 11 not)
- [x] Mean CV AUC (target >=0.55): **0.5274** [FAIL]
- [x] Mean overfit gap (target <0.15): **+0.2326** [FAIL] (RF max_depth=6 + 13 feature memorize)
- [x] Trade survival rate (target %20-95): **%16.49** [FAIL] (threshold=0.55 cok agresif)
- [x] Shuffle p<0.05 windows (target >=5/6): **1/6** [FAIL] (sadece W3 p=0.020)
- [x] Bonferroni p<0.00833 windows (target >=3/6): **0/6** [FAIL]
- [x] Bootstrap CI low (target >0): **-0.9693** [FAIL] (95% CI [-0.97, +2.72] — anlamsiz)
- [x] Class balance per window: 0.50-0.51 (PASS)
- [x] Karar: **RED** (HARD GATES 6/7)

## Karar Gerekcesi (RED)

1. **CV AUC 0.527** — model neredeyse random'dan iyi degil (0.50 baseline). 13 feature trade-level R-outcome icin yetersiz signal tasiyor. Strateji kendi aldigi karari kalitesizlestiren feature'lar yok (veya bu feature setinde okunamiyor).

2. **Overfit gap +0.23** — train_acc 0.75, cv_acc 0.52. RF max_depth=6 + 13 feature + 2800 sample = ezbere ogreniyor. Pre-reg'de max_depth=4 olabilirdi (KH-2'de belirtilmisti) ama HARK'a saygiyla v2'de denenir.

3. **Shuffle 1/6 + Bonferroni 0/6** — sadece W3 (p=0.020) gercek signal gosterdi (alpha +5.2 outlier). Diger 5 pencere null dist icinde sallaniyor. **Tek pencerelik signal genelleme degil.**

4. **Bootstrap CI [-0.97, +2.72]** — mean +0.81 olmasina ragmen CI 0'i kapsiyor. **6 pencerelik sample mean'in standard error'u cok yuksek**, W3 outlier'ini cikar ortalama 0'a duser.

5. **Survival %16.5** — threshold=0.55 ile RF'in hesapladigi P(win) cogu trade icin <0.55. Bu anormal degil (CV AUC 0.52 ile model "trade'in iyi olmasini" tanimiyor, neredeyse uniform 0.50 dolayinda dagiliyor; sadece kuyrukta birkac tane >0.55). Asiri filtreleme ML'in veri tutmaktan korktugunu degil, **edge YOK** demektir.

## Yan-Bulgu (Yapilara Sinyal)

- **W3 (oos 2024-11-15 -> 2025-05-15) tek pencerede +5.2 alpha** — ya gercek bir regime-spesifik edge ya da W3'un baseline'ini sansla yendi. Bu pencere icindeki feature dagilimi v2 inceleme adayi (regime-spesifik conditional ML yolunun ipucu olabilir).
- **Mean return alpha -138.49 anomaly** — `compute_trade_metrics` per-window "total compounded return" hesapliyor. ML version 56-123 trade alirken baseline 444-529 trade. Equal-trade compounded return karsilastirmasi yanlis. v2'de "per-trade Sharpe + per-trade mean R" karsilastirilmali.

## Implikasyonlar

A. **ML meta-labeling v1.1 RED** — 13 feature trade-level kaliteyi predict edecek edge tasimiyor. v0.9.5 GBM atampti ile ayni sonuc (farkli yontem, ayni veriden ayni cevap). **Bu pool icin trade-level RF/GBM yapisal sinirli** demek.

B. **v2 Yol haritasi (KH-7 senaryosu):**
   1. **Feature space genisletme** (yeni pre-reg): multi-TF (1h/4h indicators), alt-data continuous (funding/fng/BTC.D), market microstructure proxy
   2. **XGBoost veya LightGBM** (RF yerine) — ayni feature set, gradient boosting + early stopping
   3. **Ensemble** — RF + GBM + LR + voting
   4. **TabNet veya tabular DL** — son care
   5. **Regime-conditional ML** — W3 outlier ipucu; her regime'de ayri model

C. **Lab W3 tournament adaylari:**
   - **Flat T2** (baseline) — EER v1/v2 sprint sonu zaten kanitlanmisti, ML v1 de bunu kullanmali (ML filter aktif degil)
   - **BALANCED+drop_pairs** (mevcut champion v0.9.7 +%36)

D. **DYNAMIC v2 sizing** — flat T2 + DD breakers + per-symbol cap (ML filter dahil edilmez bu hatta sonra v2 PASS edene kadar)

E. **CEO brief'e:** "Trade-level continuous-feature ML bu pool icin yetersiz, EER v2 RED + ML v1 RED zincir kanit. Sonraki sprint: feature space genisletme (alt-data continuous) veya regime-conditional ML (W3 outlier inceleme)"

## Reproducibility Footer

```
git_hash: b98f3ad4db31b559d7409beeba1a1fb8b317b6c5
config_hash: f8c3d73eda55d4ac
trades_data_hash: b1e992a3f21a8faa
run_timestamp: 2026-05-13T07:19:17Z
elapsed: 873.0s
report: reports/research/ml_meta_v1_results.txt
json: reports/research/ml_meta_v1_results.json
```
