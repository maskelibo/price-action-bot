---
hypothesis_id: 2026-05-17-feature-space-v2
date: 2026-05-17
author: researcher_agent (claude-opus-4-7-1m)
status: PRE_REGISTERED
version: 0.1
parent_strategy: ML meta-labeling (filter overlay)
parent_hypothesis: 2026-05-15-ml-meta-labeling-v1 (RED CV AUC 0.527 — 13 feature yetersiz)
companion_hypothesis: 2026-05-16-regime-conditional-ml (RED-borderline — regime mask marjinal +0.52pp)
tags: [ml, meta_labeling, multi_tf, alt_data, feature_engineering, leakage_audit]
backtest_possible: true
data_requirements: [v095_trades_cache.pkl, mtf_4h_cache.pkl, mtf_1h_cache.pkl, alt_data/funding_BTCUSDT.csv, alt_data/fng_daily.csv]
git_hash_at_registration: 57837545c29084aa2440fb9151be671e93aa8c58
---

# HYP-2026-05-17-001 — Feature Space v2 (Multi-TF + Alt-Data Continuous, RF Filter)

## 1. Pre-Registered Iddia (TEK CUMLE)

> ML v1'in CV AUC 0.527 (random) sonucu **13 feature trade-level kalite icin yetersiz** demek; v2'de MEVCUT 13 feature'a **5 yeni feature** (4h ATR%, 4h RSI, 1h vol_z, funding_z_24h, fng_value) eklendiginde, ayni RF konfigurasyonuyla (n=200, max_depth=6, min_leaf=5, threshold=0.55, purged k-fold cv=5) **walk-forward 6 pencerede mean Sharpe alpha >= +0.15** + **shuffle null p<0.05 >= 5/6** + **Bonferroni p<0.00833 >= 3/6** + **Bootstrap CI low > 0** + **mean CV AUC >= 0.55** OLUSTURUR.

**Bagimli degiskenler:**
- OOS Sharpe alpha (ML_v2_filter - flat_T2)
- Mean CV AUC (gate >=0.55)
- Mean overfit gap (gate <0.15)
- Survival rate
- Shuffle null p, Bonferroni p, Bootstrap CI

**Bagimsiz degiskenler (PRE-REGISTERED SABIT, sweep YASAK):**
- 13 mevcut feature (HYP-2026-05-15 ile ayni)
- 5 yeni feature:
  1. **atr_pct_4h** — trade signal_ts'in en son tamamlanmis 4h bar'inin atr14/close oranı
  2. **rsi_14_4h** — trade signal_ts'in en son tamamlanmis 4h bar'inin RSI(14)
  3. **vol_z_1h** — trade signal_ts'in en son 24 1h bar'inin volume z-score
  4. **funding_z_24h** — trade signal_ts'in son 24h funding rate z-score (60-day rolling)
  5. **fng_value** — trade signal_ts'in en son tamamlanmis daily FnG (0-100 raw)
- RF konfig: n=200, max_depth=6, min_leaf=5, class_weight=balanced
- Threshold: 0.55
- Purged k-fold: n_folds=5, embargo_bars=5
- Walk-forward: 6 pencere (3y train + 6mo OOS + 3mo step)
- Label: y = (R > 0).astype(int) (HYP-2026-05-15 v1.1 ile ayni)
- Baseline: flat T2 (her trade %2 risk + 2x lev)

**Null hipotez (HERHANGI biri PASS olursa hipotez RED):**
1. Mean OOS Sharpe alpha < +0.15
2. Bootstrap CI(95%) low <= 0
3. Shuffle p<0.05 < 5/6 pencere
4. Bonferroni p<0.00833 < 3/6 pencere
5. Mean CV AUC < 0.55
6. Mean overfit gap > 0.15
7. Trade survival rate < %20 OR > %95
8. **Yeni:** Yeni 5 feature'in mean importance toplami < %25 (mevcut feature'lardan daha kotu = degersiz)

---

## 2. Motivasyon — ML v1 Postmortem

ML v1 RED ana sebebi (CV AUC 0.527) ve robustness:
- 13 feature **trade signal bar + 5-60 bar onceki window** odakli
- **Multi-TF eksik:** 1h/4h indicators yok (intraday momentum proxy)
- **Alt-data eksik:** funding/fng/BTC.D yok (rejim/sentiment proxy)
- **Microstructure eksik:** order book imbalance, taker-maker ratio yok

EER v2 funding/fng'yi bucket fitting probleminden cikarmisti — ML continuous feature olarak guvenli (bucket coverage degil, feature importance).

Regime-conditional ML (HYP-2026-05-16) "BTC dusuk-getiri rejiminde edge var" buldugu icin **rejim sinyali proxy'leri** (funding, fng, vol) modele eklenince ayni signal continuous feature olarak yakalanabilir.

---

## 3. Mekanik Kurallar — Yeni 5 Feature

### 3.1 4h Features (atr_pct_4h, rsi_14_4h)

```python
def get_4h_feature(trade_signal_ts: pd.Timestamp, df_4h: pd.DataFrame, kind: str):
    # En son tamamlanmis 4h bar (signal_ts'den one)
    completed = df_4h[df_4h["ts"] < trade_signal_ts]
    if completed.empty:
        return np.nan
    last_bar_ts = completed["ts"].iloc[-1]
    if kind == "atr_pct_4h":
        return atr14(df_4h up to last_bar_ts) / close(last_bar_ts)
    elif kind == "rsi_14_4h":
        return rsi14(df_4h up to last_bar_ts)
```

**Causality:** `ts < trade_signal_ts` strict — trade decision bar'indan one en son tamamlanmis 4h bar.

### 3.2 1h Vol Z (vol_z_1h)

```python
def get_vol_z_1h(trade_signal_ts, df_1h):
    # Son 24 1h bar (signal_ts'den one)
    completed = df_1h[df_1h["ts"] < trade_signal_ts]
    last_24 = completed.tail(24)
    if len(last_24) < 24:
        return np.nan
    vol_now = last_24["volume"].iloc[-1]
    vol_mean = last_24["volume"].mean()
    vol_std = last_24["volume"].std() or 1e-9
    return (vol_now - vol_mean) / vol_std
```

### 3.3 Funding Z (funding_z_24h)

```python
def get_funding_z(trade_signal_ts, df_funding):
    # Son 24h funding (BTCUSDT, 8h funding intervals -> 3 funding/day)
    completed = df_funding[df_funding["ts"] < trade_signal_ts]
    last_24h_window = completed.tail(3)  # 3 funding events / day
    if last_24h_window.empty:
        return np.nan
    fr_now = last_24h_window["fundingRate"].iloc[-1]
    # 60-day rolling z (180 funding events)
    last_60d = completed.tail(180)
    fr_mean = last_60d["fundingRate"].mean()
    fr_std = last_60d["fundingRate"].std() or 1e-9
    return (fr_now - fr_mean) / fr_std
```

### 3.4 FnG Value (fng_value)

```python
def get_fng_value(trade_signal_ts, df_fng):
    # En son daily FnG (signal_ts'den one)
    completed = df_fng[df_fng["ts"] < trade_signal_ts]
    if completed.empty:
        return 50.0  # neutral fallback
    return float(completed["value"].iloc[-1])
```

### 3.5 NaN Handling

Tum yeni feature'lar median imputation (column-wise, in-sample dilim) ile NaN doldurulur. Train/OOS arasinda median **train-only** hesaplanir (causality).

---

## 4. Walk-Forward Protokolu (HYP-2026-05-15 ile ayni)

- 6 pencere (3y train + 6mo OOS + 3mo step)
- Per-window: train_rf -> predict_filter (thr=0.55) -> ML filter trades vs flat T2
- Shuffle null 200 iter/pencere
- Bootstrap CI 2000 iter

---

## 5. Robustness (DIAGNOSTIC)

| Test | Yapilis | Gate |
|---|---|---|
| Yeni feature ablation | 5 yeni feature'i tek tek drop | Sharpe alpha sapma <%50 |
| Eski-only retest | 13 mevcut feature ile RF (HYP v1 sonucu) | v2 alpha > v1 alpha + %50 |
| Feature importance dist | Top-10 importance | Yeni feature'lardan en az 1'i top-10'da |
| MTF-only retest | Sadece 4h/1h feature (alt-data drop) | sapma <%50 vs v2 |
| Alt-data-only retest | Sadece funding/fng (4h/1h drop) | sapma <%50 vs v2 |
| Look-ahead audit | 50 random trade yeni feature timestamp | %100 causal |

---

## 6. Karsi-Hipotezler

**KH-1: Yeni 5 feature mevcut 13'in icinde zaten yansiyor.**  4h ATR% / 1d ATR% korelasyon yuksek olabilir (~0.7+). RSI 4h vs 1d benzer. Funding/fng yeni gerçek bilgi tasiyor ama edge veriyor mu belirsiz. Beklenti: marjinal AUC artisi (0.527 -> 0.55-0.57).

**KH-2: Look-ahead riski cok artiyor.**  4h/1h timestamps'in trade signal_ts ile dogru align edilmesi kritik. **5. madde gereği 50 random trade audit edilir** + `ts < trade_signal_ts` strict.

**KH-3: NaN explosion (early data + funding pre-2021).**  Funding 2021-05-13'te basliyor, trade pool 2021-05-15'te basliyor → ilk birkac trade NaN olur, median impute yardimci ama signal kaybi. Mitigation: ilk trade'lerin %5'inde median impute kabul edilir.

**KH-4: Overfit ek 5 feature ile artar.**  18 feature x 2800 sample/window = 0.0064 ratio (ML v1'de 0.0046). Marjinal artis. RF max_depth=6 sabit, kontrol altinda.

**KH-5: HARK riski.**  Bu 5 feature daha onceki ekipler tarafindan onerildi (alt-data agent v0.9.4). Pre-reg sayisi sabit, sweep yasak — HARK kontrolu altinda.

---

## 7. Karar Akisi

```
1. data/mtf_4h_cache.pkl + mtf_1h_cache.pkl hazir (Sec2.1 fetch)
2. src/price_action/ml/features_v2.py (5 yeni feature, lookahead-free)
3. scripts/ml_meta_v2_walkforward.py (mevcut harness extend, feature_cols += 5)
4. 6 pencere walk-forward + shuffle null + bootstrap CI
5. Gate kontrolu (8 NH)
6. PASS -> Lab tournament aday + DYNAMIC v2 (regime-conditional + ML v2)
   FAIL -> Sec3 (archive + tournament)
```

---

## 8. Implikasyonlar

**PASS:**
1. ML hatti yeniden acilis. Yeni feature seti ile trade-level edge var.
2. Production v1.1 onerisi: BALANCED+F&G + ML v2 filter (regime-conditional optional).
3. Beklenti yillik %36 -> %38-42.

**FAIL:**
1. Yapisal kanit kesin: 4787 trade pool'u trade-level filter ile iyilestirilemez.
2. ML hatti **tamamen archive**.
3. Sec3 acilis: Lab tournament, champion confirm, yeni strateji sınıfı arama.

---

## 9. Limit ve Yasaklar

- ❌ 5'ten fazla yeni feature ekleme YASAK.
- ❌ Hiperparametre sweep YASAK.
- ❌ Threshold sweep YASAK (0.55 sabit).
- ❌ NaN imputation strategy degisikligi YASAK (median sabit).
- ❌ Multi-TF feature timestamp align degisikligi (`< trade_signal_ts` strict).

---

## Sonuclar (DOLDURULDU 2026-05-17)

- [x] Mean Sharpe alpha (target >=+0.15): **+1.9528** [PASS, v1 +0.81 → v2 +1.95 = +1.14 uplift]
- [x] Mean CV AUC (target >=0.55): **0.5310** [FAIL]
- [x] Mean overfit gap (target <0.15): **+0.2590** [FAIL]
- [x] Survival rate (target %20-95): **%18.22** [FAIL — marjinal]
- [x] Shuffle p<0.05 (target >=5/6): **0/6** [FAIL]
- [x] Bonferroni p<0.00833 (target >=3/6): **0/6** [FAIL]
- [x] Bootstrap CI low (target >0): **+1.0492** [PASS — POZITIF VE BUYUK]
- [x] Yeni 5 feature mean importance (target >=%25): **%34.69** [PASS]
- [x] **Karar: RED (HARD 5/8) — alpha pozitif ama overfit-driven**

## Karar Gerekcesi (RED)

Pre-reg disipline saygiyla karar **RED** cunku 5/8 gate fail. Ama yan-bulgular cok onemli:

**3/8 PASS (cok guclu):**
1. Mean Sharpe alpha **+1.95** (v1 +0.81'den **+1.14 uplift**)
2. **Tum 6 pencere pozitif alpha** (v1'de 3/6 negatifti)
3. Bootstrap CI(95%) **[+1.05, +2.86]** — CI low pozitif ve buyuk
4. v2 yeni 5 feature importance %35 → MTF/funding/fng feature'lar model tarafindan **gerçekten kullaniliyor**

**5/8 FAIL:**
1. CV AUC 0.531 < 0.55 → model hala neredeyse random
2. Overfit gap +0.26 > 0.15 → derin overfit
3. Survival %18 < %20 → marjinal
4. Shuffle 0/6 → permuted label'larda bile model alpha cikartiyor
5. Bonferroni 0/6 → istatistiksel anlamlilik yok

## Yapısal Yorum: Overfit-Driven Alpha

Cok ilginç çelişki: **bootstrap CI [+1.05, +2.86]** gerçek bir alpha gösteriyor, ama **shuffle null da yüksek** (alpha p=0.090-0.515). Bu, modelin gerçek edge yerine **noise'i memorize ettiğine** isaret. RF max_depth=6 + 18 feature + ~2800 sample ile **overfit alpha** üretiyor.

Sebep: Yeni 5 feature **fragility ekledi**. Model bu feature'larin patterns'ini öğreniyor ama bu paturnler trade outcome'unu yansıtmıyor — sadece data'daki gürültü.

## ML Hatti — 3 Sprint Zincir Kanit

| Sprint | Yaklasim | Sonuc | CV AUC | Mean alpha | CI low |
|---|---|---|---|---|---|
| ML v1 (2026-05-15) | RF + 13 feature + thr=0.55 | RED | 0.527 | +0.81 | -0.97 |
| Regime cond (2026-05-16) | BTC period_return mask | RED-bord | - | +1.33 (regime) | +0.23 |
| ML v2 (2026-05-17) | + 5 feature (MTF + alt-data) | RED | 0.531 | +1.95 | +1.05 |

**Yapisal cikarim:** Trade-level ML edge bu pool/feature/model setup'inda yapısal olarak **overfit-driven**. Gerçek statistical significance (shuffle null & Bonferroni) hiçbir varyantta sağlanmadı. Bootstrap CI ve mean alpha "öyleymiş gibi" görünüyor ama RANDOM PERMUTATION da aynı seviye → overfit.

## Implikasyonlar

A. **ML hatti KAPANIR** — Sec3 archive + Lab tournament. ML scriptleri archive/ml_attempts/'e tasinir.

B. **Production lock korundu** — v0.9.7 BALANCED+F&G yıllık +%36 / DD -%30 (degisiklik yok).

C. **Regime-conditional v2'ye sebep yok** — ML v2 zaten bütün rejimlerde alpha üretti (regime-conditional v1.1 marjinal +0.52pp uplift, v2 +1.14 uplift). Ama shuffle null ile geçmedikleri için ikisi de overfit.

D. **Lab W3 tournament** acilis: BALANCED+F&G (champion) vs Flat T2 (challenger A) vs BALANCED-no-F&G (challenger B). %95 ihtimal champion confirmed.

E. **Bandwidth açilir** — yeni strateji sınıfı arama veya parametre fine-tuning sprint'leri.

## Ne Tekrarlanmamali

1. **Shuffle null testi olmadan alpha guvenmemeli** — bootstrap CI ve mean alpha overfit'in tetikleyebilecegi metric'ler. Shuffle null + Bonferroni, gerçek edge'in altın standardı.
2. **CV AUC <0.55 + overfit gap >0.15** kombinasyonu = "model overfit alpha üretir" — bunu erken fark edip sprint kestirmek lazim.

## Reproducibility Footer

```
git_hash: 57837545c29084aa2440fb9151be671e93aa8c58
config_hash: 67c755149a62b19e
data_hash: 4787 trade + 11 sym × 5y × 4h (10946-bar) + 1h (43777-bar) + funding 5475 event + fng 2000 day
run_timestamp: 2026-05-13T08:18:00Z
elapsed: 882.4s
report: reports/research/ml_meta_v2_results.txt
json: reports/research/ml_meta_v2_results.json
```
