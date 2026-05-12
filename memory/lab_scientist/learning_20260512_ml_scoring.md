---
agent: lab_scientist
type: learning / experiment_negative_result
created: 2026-05-12
tags: ml, scoring, filter, overfitting, negative_result, sanity_check
scope: scripts/v095_ml_trade_scoring.py + src/price_action/backtest/lab.py
status: COMPLETED (negative result — ML filter genel kullanima onerilmiyor)
---

# v0.9.5 ML Trade Scoring Filter — Sonuc: NEGATIF

## Hipotez

4787 geçmiş trade'in her birine BTC OHLCV + sembol bazlı + zaman + konsantrasyon
feature'ları eklendi. `GradientBoostingClassifier` ile `win = (R > 0)` tahmin
edilirse, `predict_proba` threshold'unun üstündeki trade'leri tutarak baseline
yıllık ROI'sini artırıp DD'sini düşürebilir miyiz?

## Pipeline

- Trade kaynağı: `_gather` × `TOP_10` × 11 sembol → **4787 trade** (2021-05 → 2026-05).
- Feature sayısı: **38** (17 numeric + 10 strategy one-hot + 11 symbol one-hot).
  - `conf`, `vol_z`, `sl_pct`
  - BTC: `atr_pct`, `ema200_streak`, `dd_90d`, `ret_7`, `ret_30`
  - Sembol: `atr_pct`, `vol_z_20`, `ret_20`, `ema200_streak`
  - Zaman: `month`, `weekday`
  - Konsantrasyon: `conc_same_side`, `conc_total`
- Target: `win = int(R > 0)`. Base WR = **0.504** (neredeyse dengeli).
- Model: `GradientBoostingClassifier(n_estimators=80, max_depth=3, lr=0.05,
  min_samples_leaf=30, max_features='sqrt')`.
- Walk-forward: 3y train / 6mo test / 3mo slide. 8 fold, OOF coverage 1892/4787.
- Pass-through: OOF score'u olmayan trade'ler (ilk 3y) filter'dan otomatik geçer.

## Anahtar Bulgular

### 1) Sanity checks — model gerçek edge bulamadı

| Test | Sonuç | Yorum |
|---|---|---|
| Overfit gap (train vs test pred-WR) | 69.6% vs 49.0% (gap +20.6pp) | Eşik altında ama yüksek |
| Shuffle null (target rasgele) | Null WR 50.7%, Real WR 50.4% | **Edge -0.29pp = sıfır** |
| Permutation importance top | `conc_total` +2.55pp, `btc_ema200_streak` +1.47pp | Zayıf sinyaller |

**Yorum:** Shuffle null testinde real model, rasgele etiket alınan modelle aynı
performansı veriyor. Bu **istatistiksel olarak edge yok** demek. Model
overfitting yapıyor + price-action paterninin kendisi WR=0.50 üretiyor (kompleksiyon
yok).

### 2) 3y rolling stress — ML filter ROI'yi düşürüyor

| Config | yıllık % | DD % | r-adj | min | max |
|---|---|---|---|---|---|
| **BASELINE** (no ML) | **+34.71%** | -39.5% | **0.879** | +2.8 | +85.4 |
| ML thr=0.50 | +38.24% | -41.8% | 0.916 | +6.3 | +87.1 |
| ML thr=0.55 | +21.63% | -39.6% | 0.547 | -5.0 | +85.3 |
| ML thr=0.60 | +17.91% | -40.0% | 0.448 | -7.4 | +88.7 |
| ML thr=0.65 | +20.97% | -39.2% | 0.535 | -4.4 | +88.7 |
| ML thr=0.70 | +22.65% | -39.2% | 0.577 | -2.8 | +88.7 |
| BALANCED + ML thr=0.55 | +23.76% | -28.3% | 0.840 | +7.3 | — |
| R-regressor q=0.50 | +22.38% | -39.4% | 0.567 | -2.8 | +85.8 |

**Yorum:** Tek "pozitif" senaryo thr=0.50 (+3.53pp ROI uplift). Bu eşik %50 win
olasılığı demek — yani filter NEREDEYSE HİÇ trade atmıyor (n.mean 116 vs baseline
~250 için adjusted, ama baseline n=89 OOF range single-window'da). thr ≥ 0.55
olur olmaz ROI çöküyor.

### 3) Feature ablation — hangi grup önemli?

| Feature set | yıllık % | DD% | r-adj |
|---|---|---|---|
| conf + strategy only | +19.07% | -39.9% | 0.478 |
| BTC only | +17.53% | -40.5% | 0.433 |
| All features | +21.63% | -39.6% | 0.547 |

Hiçbiri baseline'ı (+34.71%) geçemiyor. ML kombinasyonu en iyi haliyle bile
ROI tahrip ediyor.

### 4) Permutation importance top 10 (delta-WR pp)

```
conc_total                      +2.55
btc_ema200_streak               +1.47
btc_ret_30                      +0.80
btc_atr_pct                     +0.60
btc_ret_7                       +0.30
month                           +0.27
strat_brooks_failed_breakout    +0.20
strat_brooks_h2_l2              +0.20
weekday                         +0.17
is_long                         +0.17
```

En önemli feature `conc_total` (concurrent open positions) — bu zaten
`max_concurrent=8` ile sınırlanan bir şey. ML "kalabalıkken trade aç" diyor,
ki bu eski concurrency limit'in tersine.

## Neden ML Filter Bu Sistemde İşe Yaramıyor

1. **Base WR çok dengeli (0.504).** Trade'ler zaten 50/50 yapı — alpha yok ki
   filtre çıkarsın.
2. **Strateji-level edge already extracted.** TOP_10 zaten içeri kalan en iyi
   stratejiler, sırf adverse selection için sıra.
3. **OHLCV feature'lar leak/lookback yetersiz.** Daha güçlü mikro-yapı feature'ları
   gerekirdi (orderbook imbalance, funding rate, OI delta) ama bunlar 1d TF'te
   yeterli sinyal vermiyor.
4. **Multi-target TP engine zaten cherry-picking yapıyor.** Sistem küçük loser'ları
   ve büyük winner'ları üretmek için kurulmuş. ML "küçük loser" trade'lerini
   filtre ediyor → büyük winner'ların önündeki "free option" da gidiyor.
5. **Concurrency gate'ler katmanlı (cool-down, max_concurrent, conc_per_symbol).**
   ML'in "skip" sinyali zaten manuel gate'lerle örtüşüyor → marjinal değer yok.

## Tavsiye — Production Action Items

| Aksiyon | Karar |
|---|---|
| **ML filter'ı production'a dahil et?** | **HAYIR.** Edge yok, sadece variance üretiyor. |
| `score_filter` parametresi (lab.py) kalsın mı? | EVET — gelecek deneyler için altyapı hazır. |
| Tekrar denenmesi gereken yön | (a) Funding+OI feature seti; (b) 4h-resampled feature; (c) per-strategy ML (her stratejiyi ayrı eğit, daha az gürültü). |
| Sanity-check protokolü | Shuffle null **MUTLAKA** yapılsın — bu test bize "ML edge yok" sonucunu sağladı, hafta kayıp ederdik. |

## Bonus — lab.py Genişlemesi

`ProductionConfig.score_filter: dict[(symbol, entry_ts) -> proba] | None` +
`score_threshold: float` eklendi. Backward-compat: default `None` → eski davranış.
Gelecek ML deneyleri bu altyapı üzerinde çalışabilir.

## Sayılarla Net Özet

> **ML filter at threshold 0.55**: yıllık **baseline +34.71% → +21.63% (delta -13.08pp)**,
> **DD -39.5% → -39.6% (delta -0.1pp, fark yok)**, r-adj 0.879 → 0.547.
>
> **Tek pozitif senaryo** thr=0.50: yıllık +34.71% → +38.24% (**+3.53pp**), DD -39.5%
> → -41.8% (**+2.3pp DD daha kötü**). Bu noise sınırında; istatistiksel olarak null.
>
> **Sonuç: ML scoring filter v0.9.5 ile production'a alınmıyor.** Negative result.
> Altyapı (lab.py score_filter) gelecek deneyler için duruyor.

## Files

- Script: `scripts/v095_ml_trade_scoring.py`
- Report: `reports/v095_ml_results.txt`
- Lab extension: `src/price_action/backtest/lab.py` (`score_filter`, `score_threshold` alanları)
- Trade cache: `data/v095_trades_cache.pkl`, `data/v095_ohlcv_cache.pkl`
