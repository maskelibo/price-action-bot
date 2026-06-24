# ML Hatti Archive (2026-05-17)

Bu klasor 3 sprint zincirini takip eden ML meta-labeling denemelerinin scriptlerini icerir.

## Kapanis Kararı

3 sprint zincir kanit:
1. **HYP-2026-05-15-001 (ML v1)**: RF + 13 feature + thr=0.55 → RED (CV AUC 0.527, overfit gap +0.23)
2. **HYP-2026-05-16-001 (Regime-conditional)**: BTC period_return median mask → RED-borderline (3/4 PASS, random null p=0.0500 marjinal)
3. **HYP-2026-05-17-001 (Feature space v2)**: + 5 feature (4h/1h/funding/fng) → RED (HARD 5/8) — alpha overfit-driven (mean +1.95, CI low +1.05) ama shuffle null 0/6, gerçek istatistiksel anlamlılık yok

Yapısal sonuc: 4787 trade pool + mevcut feature seti + RF/regime-mask/MTF-altdata
kombinasyonlarinin hicbiri yıllık %36 BALANCED+F&G uzerine anlamli alpha
katmiyor. Trade-level filter edge yok bu setup'ta.

## Korunan Bilesenler

- `src/price_action/ml/*` (meta_labeling.py, features.py, features_v2.py, inference.py, train_filter.py)
  → ileride yeni feature/regime denemeleri icin kullanilabilir
- `data/v095_*.pkl, data/mtf_*.pkl` → trade pool + MTF cache
- `data/alt_data/funding_*.csv, fng_daily.csv` → alt-data
- `reports/research/ml_meta_*.txt` + `.json` → tum sonuclar (analytics icin)
- `memory/researcher/hypotheses/2026-05-1[5-7]-*` → pre-reg hipotezler ve postmortemler

## Yeni Sprint Yolu

ML hatti yerine:
1. **Lab W3 tournament** — Champion (BALANCED+F&G) confirm
2. **Yeni strateji sınıfı arama** — futures basis, mean-reversion, vol overlay
3. **Mevcut stratejilerin fine-tuning** — parametre optimizasyonu

## Retrieval

Eger ileride ML denemesi tekrar gerekirse:
```
git mv archive/ml_attempts/ml_meta_v2_walkforward.py scripts/
```
veya benzer.
