# PRODUCTION BENCHMARK

**Son güncelleme:** 2026-05-12 10:02 UTC
**Git commit:** `c997fe7`
**Kaynak:** `scripts/v092_build_benchmark.py` (canonical `production_replay` üzerinden)

> Bu dosya **tek doğruluk kaynağıdır**. Her commit'te güncellenir.
> Aynı pencere/aynı config = aynı rakam — sapma varsa script bug'ı vardır.

## v0.9.2 Production Config

```
label              : r%3.0_conf0.2_cap0.30_cd3/5d
risk_pct           : 0.03
max_notional_pct   : 0.3 (v0.9.2 cap)
conf_min           : 0.2
consecutive_loss   : 3 -> 5d pause
max_concurrent     : 8
DD breakers (d/w/m): 0.05/0.1/0.15
```

## 1 Yıl Out-of-Sample (2025-05-09 → 2026-05-09)

| Config | n_trade | final $ | toplam % | yıllık % | max DD | WR |
|---|---|---|---|---|---|---|
| v0.9.1 (no cap) | 102 | $32,631 | +226.3% | +226.6% | -82.0% | 63.7% |
| v0.9.2 (cap 0.30) | 100 | $27,090 | +170.9% | +171.1% | -64.3% | 60.0% |
| v0.9.2 + conc 0.20 (live-like) | 32 | $16,885 | +68.9% | +68.9% | -28.7% | 68.8% |
| v0.9.3 AGGRESSIVE preset | 16 | $18,837 | +88.4% | +88.4% | -19.0% | 87.5% |
| v0.9.3 DEFENSIVE preset | 87 | $11,934 | +19.3% | +19.4% | -29.0% | 52.9% |

## 5 Yıl In-Sample (tek pencere)

> ⚠️ Tek pencere; dispersiyon yüksek olabilir. 3y rolling'den daha az güvenilir.

| Config | n_trade | final $ | toplam % | yıllık % | max DD | WR |
|---|---|---|---|---|---|---|
| v0.9.1 (no cap) | 478 | $119,263 | +1092.6% | +64.50% | -74.9% | 49.6% |
| v0.9.2 (cap 0.30) | 453 | $297,592 | +2875.9% | +97.65% | -59.4% | 53.4% |
| v0.9.2 + conc 0.20 (live-like) | 201 | $62,079 | +520.8% | +44.28% | -50.4% | 53.2% |
| v0.9.3 AGGRESSIVE preset | 128 | $174,374 | +1643.7% | +77.54% | -43.1% | 59.4% |
| v0.9.3 DEFENSIVE preset | 366 | $31,513 | +215.1% | +25.92% | -23.2% | 53.0% |

## 3 Yıl Rolling Stress (13 pencere, 60-gün adım)

> ⭐ **ASIL referans** — pencere ortalaması dispersiyona dirençli.

| Config | n_pencere | ort. yıllık | median yıllık | min yıllık | max yıllık | ort. DD | min DD | %50+ | neg |
|---|---|---|---|---|---|---|---|---|---|
| v0.9.1 (no cap) | 13 | +57.39% | +58.17% | +12.5% | +89.3% | -78.3% | -87% | 10/13 | 0 |
| v0.9.2 (cap 0.30) | 13 | +57.12% | +51.42% | +13.8% | +133.7% | -65.2% | -71% | 7/13 | 0 |
| v0.9.2 + conc 0.20 (live-like) | 13 | +34.74% | +35.02% | +2.8% | +85.4% | -39.5% | -50% | 2/13 | 0 |
| v0.9.3 AGGRESSIVE preset | 13 | +42.48% | +34.17% | +3.4% | +102.7% | -36.9% | -45% | 4/13 | 0 |
| v0.9.3 DEFENSIVE preset | 13 | +30.85% | +30.37% | +14.5% | +48.5% | -23.5% | -31% | 0/13 | 0 |

### v0.9.2 Production — 3y rolling pencereleri (tam liste)

| Pencere | n_trade | final $ | yıllık % | DD |
|---|---|---|---|---|
| 2021-05-15 → 2024-05-14 | 230 | $50,561 | +71.70% | -47.5% |
| 2021-07-14 → 2024-07-13 | 264 | $16,584 | +18.38% | -70.5% |
| 2021-09-12 → 2024-09-11 | 313 | $34,687 | +51.42% | -54.2% |
| 2021-11-11 → 2024-11-10 | 309 | $36,455 | +53.95% | -66.1% |
| 2022-01-10 → 2025-01-09 | 344 | $96,244 | +112.82% | -65.5% |
| 2022-03-11 → 2025-03-10 | 271 | $21,921 | +29.93% | -66.7% |
| 2022-05-10 → 2025-05-09 | 267 | $14,739 | +13.81% | -67.1% |
| 2022-07-09 → 2025-07-08 | 355 | $127,359 | +133.67% | -67.5% |
| 2022-09-07 → 2025-09-06 | 309 | $21,827 | +29.74% | -65.5% |
| 2022-11-06 → 2025-11-05 | 337 | $22,966 | +31.96% | -66.2% |
| 2023-01-05 → 2026-01-04 | 324 | $31,215 | +46.18% | -71.5% |
| 2023-03-06 → 2026-03-05 | 326 | $39,099 | +57.59% | -71.5% |
| 2023-05-05 → 2026-05-04 | 341 | $70,015 | +91.39% | -68.0% |

## v0.9.3 PRESETS — İki Production Seçeneği

`configs/risk_aggressive.yaml` ve `configs/risk_defensive.yaml` iki paralel preset.
Production default `configs/risk.yaml` (v0.9.2) — değiştirilmedi.

### Aggressive (Aday A) — `risk_aggressive.yaml`
- Tek değişiklik: `backtest_risk_pct: 0.040`
- Profil: "GETIRI maksimum"
- Beklenti: yıllık +%42, DD -%37, 5y $59K
- Live-realistic (conc 0.20): yıllık +%30, DD -%26, 5y $37K

### Defensive (Aday B = T6 r%3.5) — `risk_defensive.yaml`
- `backtest_risk_pct: 0.035`
- `vol_target.enabled: true`
- `max_same_side_concurrent: 4`
- `drop_strategies: [equal_highs_sweep, cvd_spike_fade, vsa_climax_test]`
- Profil: "TUTARLILIK maksimum"
- Beklenti: yıllık +%31, DD -%24, 5y $38K, **risk-adj 1.31 (en yüksek)**
- Live-realistic (conc 0.20): yıllık ~%22, DD -%19, 5y $27K

### Kullanim
```python
from price_action.backtest.lab import ProductionConfig, production_replay
cfg = ProductionConfig.from_yaml('configs/risk_aggressive.yaml')
# veya 'configs/risk_defensive.yaml'
result = production_replay(trades, cfg)
```

## Yorum — Hangisi 'Gerçek' Beklentidir?

Üç pencere üç ayrı şey ölçer:

- **1y OOS** (`+%170, DD -%64`): Son 12 ayda kripto yükselişinde aşırı iyi performans.
  Single window — dispersiyon yüksek. Live'da tekrar edilmesi şart değil.
- **5y in-sample** (`+%97 yıllık, DD -%59`): Tek pencere, optimizasyon biased.
  Üst sınır olarak görülmeli, gerçek değil.
- **3y rolling 13 pencere** ⭐ (`ort. yıllık +%57, DD -%65`): Pencere-bağımsız
  ortalama — beklenti olarak **bu** kullanılmalı.

**Live trading realistik beklenti** (slip+funding %20 kayıp):
- Yıllık ROI: **+%40-50**
- Max DD: **-%65 ile -%75 arası**
- Best/Worst pencere ROI: +%14 (en kötü) ile +%134 (en iyi) arası bekleyin

> **NOT — 'v0.9.2 + conc 0.20'** kolonu live'a en yakın simulasyon.
> Concentration gate (`%20 per symbol`) RiskOfficer.evaluate'ta uygulanıyor.
> Eski backtest replay'lerde bu gate yoktu; rakamlar burada gerçek live'a daha yakın.

## Reproducibility

Bu rakamları yeniden üretmek için:
```bash
python scripts/v092_build_benchmark.py  # bu dosyayi yeniden uretir
python scripts/v092_parity_check.py     # canonical vs eski replay parity
```
