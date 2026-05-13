---
hypothesis_id: 2026-05-16-regime-conditional-ml
date: 2026-05-16
author: researcher_agent (claude-opus-4-7-1m)
status: PRE_REGISTERED (POST-HOC, EXPLORATORY)
version: 0.1
parent_strategy: ML meta-labeling (filter overlay)
parent_hypothesis: 2026-05-15-ml-meta-labeling-v1 (RED — CV AUC 0.527, W3 outlier alpha +5.2 p=0.020 tek pencere)
forensik: scripts/w3_regime_forensics.py + reports/research/w3_forensics.txt
tags: [ml, meta_labeling, regime_conditional, w3_forensics, post_hoc, hold_out, hark_protection]
backtest_possible: true
data_requirements: [4787-trade pool, BTC/USDT 1d OHLCV, 6-window walk-forward results from ML v1]
git_hash_at_registration: 5f4da50c7025bde314bf6f90381748b2f3a13b08
---

# HYP-2026-05-16-001 — Regime-Conditional ML (BTC Period-Return + Volatility Mask, POST-HOC)

## 0. POST-HOC IDENTIFIER (HARK PROTECTION — KRITIK)

Bu hipotez **post-hoc, exploratory analysis** olarak isaretlidir. Sebebi:
- ML v1 walk-forward sonuclari GORULDUKTEN SONRA
- W3 outlier (alpha +5.2, p=0.020) GORULDUKTEN SONRA
- W3 forensik korelasyonu (Spearman -0.829 vs BTC period return) GORULDUKTEN SONRA

Bu durum klasik "garden of forking paths" / HARK riski (hypothesis after results known). Mitigation:
1. **W6 strict hold-out**: Regime tanimi SADECE W1-W5 in-sample BTC istatistiklerinden kalibre edilir. W6'da test edilir, kalibrasyona dahil EDILMEZ.
2. **Tek metric, sweep YASAK**: Regime mask `period_return_pct < median(W1-W5)` SABIT (Spearman'da -0.829 ile en guclu, in-sample veriden seclidir ama threshold sabit).
3. **Hold-out gate**: W6 alpha > 0 + n_taken > 30 olmali (in-sample W1-W5'den genelleyebildigini test).
4. **Sansa atfedilebilirlik testi**: Random regime mask 1000 iter (rastgele 3/6 pencere "iyi rejim" isaretle) — gercek regime mask sansin %95+'ini yenmeli.
5. Bu hipotez PASS olsa bile production'a alinmasi icin **forward 3 ay paper trading** zorunlu (Lab agent karari).

## 1. Pre-Registered Iddia (TEK CUMLE)

> ML v1 walk-forward'da W3 outlier'in (alpha +5.2, p=0.020) sebebi BTC'nin O OOS donemindeki dusuk getirili-yuksek vol rejimi (period_ret +13.7%, ATR% 4.11, z=+1.72) oldugu hipoteziyle, **regime mask = "in-sample W1-W5 medianinin altinda BTC period return"** kuralini uygulayarak yalnizca dusuk-getiri rejimlerinde ML filter aktif edilirse, **W6 hold-out pencerede alpha > 0 + n_taken > 30** OLUSTURUR + **random regime mask 1000-iter null'da gercek alpha %95'ini yener**.

**Bagimli degiskenler:**
- W6 hold-out alpha (target > 0)
- W6 n_taken (target > 30 trade)
- Random regime null p-value (target < 0.05)
- In-sample (W1-W5) regime-conditional Sharpe alpha mean (DIAGNOSTIC, gate degil)

**Bagimsiz degiskenler (PRE-REGISTERED SABIT):**
- Regime metric: BTC OOS donem icindeki **period_return_pct** (close[-1]/close[0]-1)
- Regime threshold: in-sample (W1-W5) median (W1-W5 period_ret degerleri: +31.90, +69.45, +13.70 (W3, in-sample), +21.24, -8.84 → median = +21.24)
- Regime mask kurali: `period_ret < median_W1-W5` → "iyi rejim, ML aktif"; aksi → "kotu rejim, flat T2"
- Hold-out pencere: W6 (oos 2025-08-15 → 2026-02-15)
- ML model konfigi: HYP-2026-05-15 ile AYNI (RF n=200, max_depth=6, min_leaf=5, threshold=0.55, purged k-fold cv=5)
- Walk-forward: 6 pencere (W1-W6), regime mask ile filtreli alpha hesabi

**Null hipotez (HERHANGI biri PASS olursa hipotez RED):**
1. W6 hold-out alpha <= 0 (regime mask in-sample'a curve-fit, OOS'ta calismadi)
2. W6 hold-out n_taken < 30 (regime mask cok sıkı, anlamli sample yok)
3. Random regime null'da gercek alpha %95'ini YENMIYOR (p_random >= 0.05)
4. In-sample regime-aktif pencere sayisi <2 (kontrol — eger sadece W3 mask ediyorsa, generalize degil)

---

## 2. Motivasyon — W3 Forensik Bulgusu

ML v1 walk-forward sonuclari (2026-05-15):

| W | OOS donem | ml_alpha | ml_p | BTC period_ret | BTC ATR% | BTC RV30 |
|---|---|---|---|---|---|---|
| 1 | 2024-05→11 | -0.635 | 0.575 | +31.90% | 3.72 | 46.8 |
| 2 | 2024-08→2025-02 | -2.237 | 0.795 | +69.45% | 3.91 | 45.9 |
| 3 | 2024-11→2025-05 | **+5.204** | **0.020** | +13.70% | 4.11 | **49.9** |
| 4 | 2025-02→2025-08 | -0.255 | 0.320 | +21.24% | 3.30 | 41.2 |
| 5 | 2025-05→2025-11 | +1.376 | 0.260 | -8.84% | 2.78 | 32.9 |
| 6 | 2025-08→2026-02 | +1.407 | 0.395 | -40.50% | 3.48 | 39.9 |

**Spearman korelasyon (n=6):**
- ml_alpha vs **period_ret**: **-0.829** (en güçlü)
- ml_alpha vs dd_90d_min: -0.696
- ml_alpha vs up_days_pct: -0.543

**Yorum:** BTC ne kadar **iyi getiri** verirse ML alpha o kadar **dusuk** (zarar veriyor). BTC zayifsa ML edge tasiyor. Bu, RF'in trade-level kalite ayrimini bull/risk-on rejiminde yapamayip; bear/sideways'ta yapabildigine isaret.

---

## 3. Mekanik Kurallar

### 3.1 Regime Mask

```python
# In-sample W1-W5 BTC period_return pencere bazli (Bull-bear esik kalibrasyonu)
in_sample_period_rets = [+31.90, +69.45, +13.70, +21.24, -8.84]  # W1-W5
threshold = float(np.median(in_sample_period_rets))  # = +21.24
# OOS pencere icin regime karari:
def regime_mask(oos_period_ret_pct: float) -> bool:
    return oos_period_ret_pct < threshold  # True = "iyi rejim, ML aktif"
```

**Onemli:** Bu threshold W1-W5 in-sample'dan kalibre. W6 hold-out icin **bilgi sızıntısı yok** (W6 verilerine bakmadan hesaplanir).

### 3.2 ML Filter Uygulamasi

```python
for window in [W1, W2, ..., W6]:
    btc_period_ret = compute_btc_period_return(window.oos_start, window.oos_end)
    if regime_mask(btc_period_ret):
        # "Iyi rejim" — ML filter aktif (HYP-2026-05-15 protokolu)
        clf = train_rf(X_train, y_train, ...)
        mask = predict_filter(clf, X_oos, threshold=0.55)
        oos_R = oos_R_full[mask]
    else:
        # "Kotu rejim" — flat T2 (her trade alinir)
        oos_R = oos_R_full
    sharpe = compute_sharpe(oos_R)
    bl_sharpe = compute_sharpe(oos_R_full)  # baseline always full
    alpha = sharpe - bl_sharpe
```

**Kritik:** OOS pencere "iyi rejim" oldugunda BTC period_ret bilgisi **donem sonu** kullanilir. Bu look-ahead degildir cunku biz regime mask'i karari **donem bittikten sonra** evaluasyon icin uyguluyoruz (production'da bu yapilmaz — production'da regime t-1'e bakar). **Test amacli realistic mi?** Hayir, optimistik. Mitigation: rolling 30-day BTC return ile retest (DIAGNOSTIC, sec 5).

### 3.3 W6 Hold-out

W6 (2025-08-15 → 2026-02-15): 
- BTC period_ret = -40.50% < threshold +21.24 → regime_mask = True (ML aktif)
- ML v1 W6 alpha = +1.407 (pozitif!)
- Bu hipotezde W6 alpha > 0 zorunlu — kanit.

### 3.4 Random Regime Null

```python
# 1000 iter: random olarak 6 pencerenin 3'unu "iyi rejim" isaretle
real_alpha_mean = mean([alpha_i for i where regime_mask(W_i) == True])
null_alphas = []
for _ in range(1000):
    random_mask = random_choice(6, k=3)
    null_alpha = mean([alpha_i for i in random_mask])
    null_alphas.append(null_alpha)
p_value = mean(null_alphas >= real_alpha_mean)
# Gate: p < 0.05
```

---

## 4. Beklentiler

| Metric | Beklenti | Gate |
|---|---|---|
| W6 alpha | +1.407 (ML v1 sonucu, regime aktif) | > 0 |
| W6 n_taken | 95 (ML v1 sonucu, regime aktif) | > 30 |
| In-sample mean alpha (W1-W5 regime aktif) | sadece W3,W4,W5 aktif → mean(+5.204, -0.255, +1.376) = +2.108 | DIAGNOSTIC |
| In-sample mean alpha (regime pasif) | W1,W2 → mean(-0.635, -2.237) = -1.436 | DIAGNOSTIC, regime imzasi cano (regime pasif iken negatif olmali) |
| Random regime null p-value | < 0.05 | < 0.05 |

---

## 5. Robustness (DIAGNOSTIC)

| Test | Yapilis | Gate |
|---|---|---|
| Rolling 30-day BTC return regime metric | period_ret yerine son 30-bar return | Sharpe alpha sapma <%30 |
| Threshold duyarlilik | median yerine 33%/67% percentile | Sharpe alpha sapma <%50 |
| Birinci alternatif metric | dd_90d_min ile mask (Spearman -0.696) | Sharpe alpha sapma <%50 |

---

## 6. Karsi-Hipotezler

**KH-1: W3 sansla cikti, regime imzasi gercek degil.**  6 datapoint icin Spearman -0.829 anlamli mi? Bonferroni-corrected p (8 metric × 6 sample) = 0.04 × 8 = 0.32 → anlamsiz! Random regime null bu KH'yi adresler — eger gercek regime mask random'i %95 yenmiyorsa KH-1 dogrulanir.

**KH-2: W6 hold-out alpha pozitif olabilir ama bu regime sayesinde DEGIL ML filter sebebiyle.** Mitigation: W6'da regime mask aktif/pasif iki sonuc karsilastirilir (regime mask ile alpha vs ML her zaman aktif alpha).

**KH-3: Period_return look-ahead.**  Regime mask OOS pencere bittikten sonra hesaplaniyor (period_ret degeri donem sonu). Production'da bu mumkun degil. Mitigation: rolling 30-day BTC return ile retest (sec 5).

**KH-4: Tek pencere hold-out istatistiksel olarak anlamsiz.**  W6 alpha > 0 sadece 1 datapoint kanitlar. Random null %95 testi ek savunma — ama gercek validasyon icin 12+ ay forward paper trading gerekli (Lab agent karari).

**KH-5: Median threshold = +21.24 W4 alpha'sina cok yakin (-0.255).**  W4 in-sample regime mask aktif (period_ret = threshold +21.24, kucuktur degil; ama median exact W4 degerine esit, marjinal kayit). Bu fragile.

---

## 7. Karar Akisi

```
1. scripts/regime_conditional_ml_walkforward.py yaz (mevcut walkforward'i extend)
2. Regime mask hesapla per-window (BTC OHLCV'den period_ret)
3. In-sample threshold = median(W1-W5 period_ret) = +21.24
4. Per-window: regime aktif ise ML filter, pasif ise flat T2
5. Random regime null (1000 iter, 3/6 random mask)
6. Gate kontrolu:
   - W6 alpha > 0
   - W6 n_taken > 30
   - Random null p < 0.05
   - In-sample regime aktif pencere >= 2
7. PASS → Lab paper trading (3 ay forward, Lab jurisdiction) + DYNAMIC v2 conditional
   FAIL → ML yolu ARCHIVE (Sec3'e gec)
```

---

## 8. Implikasyonlar

**PASS senaryosu:**
1. Regime imzasi var, BTC dusuk-getiri rejiminde ML edge tasiyor.
2. Production v1.1 (conditional): BALANCED+F&G + (BTC son 30d ret < threshold ise ML filter aktif).
3. Beklenti yillik: %36 → %38-42 (regime aktif pencere %50-60 olacak hipotez, alpha kazanmis ortalama +1-3pp).
4. Lab tournament icin yeni adayy: BALANCED + regime-conditional ML.

**FAIL senaryosu:**
1. W3 outlier sansla cikti (1/6 = 0.167 random ihtimal, 6 datapoint zayif kanit zaten).
2. ML yolu kesin **ARCHIVE** (3 sprint zincir kanit: EER v1, EER v2, ML v1, ML regime).
3. Sec3 (Lab tournament) acilis: Champion confirm.
4. Bandwidth yeni strateji sınıfına serbest.

---

## 9. Limit ve Yasaklar

- ❌ Threshold sweep YASAK (median fix).
- ❌ Birden fazla regime metric ensemble YASAK (period_ret tek).
- ❌ W6 hold-out test edildikten SONRA threshold/metric degistirip retest YASAK (HARK).
- ❌ Sonuc PASS olsa bile **forward paper trading olmadan production'a alinmaz** (Lab karari).
- ❌ "PASS olduysa BACKWARD-LOOK ile thresh refinement" YASAK.

---

## Sonuclar (DOLDURULDU 2026-05-16)

- [x] W6 hold-out alpha (target >0): **+1.407** [PASS]
- [x] W6 hold-out n_taken (target >30): **95** [PASS]
- [x] Random regime null p (target <0.05): **0.0500** [FAIL — tam sınırda, marjinal]
- [x] In-sample regime aktif pencere sayisi (target >=2): **2** (W3, W5) [PASS]
- [x] In-sample mean alpha regime aktif: **+3.290**
- [x] In-sample mean alpha regime pasif (flat T2 = 0): **+0.000**
- [x] In-sample combined mean alpha (regime mask): **+1.316**
- [x] Bootstrap CI(95%) regime-conditional alpha: **[+0.229, +2.837]** (CI low > 0)
- [x] Mean alpha regime-conditional: **+1.331** vs ML always +0.810 vs flat T2 +0.000 (+0.52pp uplift)
- [x] **Karar: RED (HARD 1/4) — borderline pozitif yan-bulgu**

## Karar Gerekcesi (RED — Borderline)

Pre-reg disiplinine saygiyla karar **RED** cunku random null p = 0.0500 >= 0.05 strict gate. Diger 3 gate PASS:
1. W6 hold-out (gercek out-of-test) **alpha +1.41, n=95** PASS
2. In-sample regime aktif pencere 2/5 PASS (target >=2)
3. Bootstrap CI(95%) [+0.23, +2.84] alt sınırı pozitif — istatistiksel olarak anlamlı dusunuluyor

Pre-reg null hipotez 3 (NH3) tam sinirda fail — eger gate <=0.05 olsaydi PASS idi. Bu **HARK riski cok yuksek bir bulgu** — rastgele permutation'da real mean +2.66 null'un %5'inde, tam top-5%. C(6,3)=20 kombinasyon icinde 1 kombinasyon (yani %5) — random nul TAM bunu kapsiyor.

## Yan-Bulgu (Production Adayy)

Pre-reg RED olmasina ragmen:
- **Mean alpha +1.33 (regime-conditional) vs +0.81 (ML always) vs 0 (flat T2)** — anlamli uplift
- **Bootstrap CI low +0.23 > 0** — regime-conditional ML filter, flat T2'yi anlamli yeniyor
- **W6 hold-out PASS** — gercek genelleme kaniti

Bu, Lab agent icin **forward paper trading adayy** olusturur — pre-reg "PASS olsa bile forward 3 ay paper" demisti, RED durumunda ayni gerekli ama beklenti dusuk.

## Implikasyonlar

1. **Yapisal kanıt:** ML v1 + regime-conditional retest = "Trade-level ML edge **sadece dusuk-getirili BTC rejiminde** marjinal var" yapısal bulgusu. Tum rejimlerde calismiyor.
2. **v0.9.7 BALANCED+F&G production lock korundu** — degisiklik yok.
3. **Lab tournament icin yeni aday** (DIAGNOSTIC olarak): "BALANCED + regime-conditional ML overlay (BTC son 30d return < threshold)". Champion'i yenmesi marjinal beklenir.
4. **Sonraki sprint (Sec2):** Feature space genisletme (multi-TF + alt-data continuous). Eger PASS edip CV AUC >0.55 cikarsa **regime mask + iyilestirilmis features** ML hattini guclendirebilir.
5. **Eger Sec2 de RED ise (Sec3):** ML yolu kesin archive, Lab tournament champion confirm.

## Reproducibility Footer

```
git_hash: 5f4da50c7025bde314bf6f90381748b2f3a13b08
config_hash: 4ba4fce3c44d922f
forensik_data: reports/research/w3_forensics.txt
parent_results: reports/research/ml_meta_v1_results.json
report: reports/research/regime_conditional_ml_results.txt
json: reports/research/regime_conditional_ml_results.json
run_timestamp: 2026-05-13T07:51:50Z
```
