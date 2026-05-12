---
agent: lab_scientist
type: learning
date: 2026-05-13
tags: [drift_detection, paper_trade, baseline_refresh]
related:
  - memory/lab/decisions/2026-05-12-dynamic-v098-killed.md
  - memory/lab/decisions/2026-05-13-tournament-eer-dynamic-v2.md
  - reports/ceo/2026-05-12-brief.md (4.3.5)
confidence: high
---

# Drift Detection Baseline Refresh — Paper Trade Oncesi

## Tetikleyici

- DYNAMIC v0.9.8 karantinaya alindi (`memory/lab/decisions/2026-05-12-dynamic-v098-killed.md`).
- W1 commit sonrasi yeni champion: **BALANCED+drop_pairs** (BALANCED+F&G + ablation drop_pairs YAML loader, kanit edilmis +%10.81pp uplift).
- Mevcut drift detection baseline'i v0.9.7 BALANCED+F&G (drop_pairs eklenmemis hali) idi — **artik gecersiz**.
- Paper trade ile drift detection canli karsilastirma yapacak; **baseline guncel olmali**, aksi takdirde drift alarm yanlis-alarm bekleniyor.

## Karar (Plan)

W1 commit sonrasi (insan principal onayli) **48 saat icinde**:

1. **Yeni baseline hipotetik dagilimi olustur**: `scripts/v092_build_benchmark.py` ile BALANCED+drop_pairs full 5y in-sample + 3y rolling 13 pencere walk-forward returns serisi.
2. **Baseline artifact yaz**: `memory/lab/drift_baselines/2026-05-13-balanced-drop-pairs-baseline.json`
   - `daily_returns`: tum trade'lerin gunluk equity returns (~1830 nokta)
   - `windowed_30d_returns`: 30-day rolling agrege
   - `meta`: yaml hash, git commit, ann_pct, dd_pct, n_trades
3. **Eski baseline arsivle**: `memory/lab/drift_baselines/_archive/2026-05-07-balanced-fng-baseline.json` (artik canli olarak kullanilmayacak ama replikasyon icin saklanir).
4. **Drift detection script update**: `scripts/breaker_monitor.py` (mevcut) drift baseline path'ini yeniden ayarla — sabit path: `memory/lab/drift_baselines/current.json` (symlink veya direct copy).

## Test Suite (SOP-2'den)

> Bu kismi SOP-2'de oldugu gibi tut. Standard testler degisiyor degil; **baseline degisiyor**.

| Test | Esik | Yorum |
|---|---|---|
| Kolmogorov-Smirnov (dagilim) | p < 0.01 | Canli vs baseline 30g returns dagilimi |
| Welch's t-test (ortalama) | p < 0.01 | Canli vs baseline ortalama gunluk return |
| Levene (varyans) | p < 0.01 | Canli vs baseline varyans |
| 3'unden >=1 PASS | drift uyarisi | Konservatif esik |

**Bootstrap**: canli 30g vs baseline'dan bootstrap 1000 30g dilim ornekleme, p-value empirical.

## Yanlis-Alarm Riskleri (Onceden Listeleme)

1. **Veri kalitesi gap**: 1d OHLCV gap → bot anormal pozisyon — drift'i tetikler. Mitigasyon: data quality manifest (Data Engineer W1 task) + breaker_monitor `data_freshness_check`.
2. **Funding regime shift**: BTC funding 5475 satir ortalamasi dramatik degisirse, alt-data filter signature degisir — drift tetikler. Mitigasyon: aylik funding zar dagilim kontrolu (Lab haftalik refresh log).
3. **Slip / fee anomalisi**: live cost > backtest cost - drift tetikler. Mitigasyon: ExecutionChief raporu, RiskOfficer canli funding entegrasyonu (CEO brief 4 — W3).
4. **Concurrent slot bottleneck**: 8 slot dolarken sinyaller queueda kalir — backtest'e gore "kayip trade" drift. Mitigasyon: paper loop telemetry, log queue depth.
5. **Tek-pencere shock**: BTC capitulation halt tetiklendiyse 1 hafta sifir trade — drift testleri istatistiksel olarak yanlis-alarm verir (sample yetersiz). Mitigasyon: halt event window'da drift testi **sus** (manual mark).

## Cikti Disiplini

- Drift uyarisi (gercek/yanlis) → bu dosyaya append entry.
- Format:

```
### YYYY-MM-DD — drift_uyarisi_ID — gercek/yanlis-alarm
- **Test sonucu**: KS p=..., t p=..., Levene p=...
- **Beklenen kok neden**: data / cost / regime / edge erosion / unknown
- **Aksiyona donen**: rollback / cool-down / monitor 7g / yok
- **Ders**: ...
```

## Tournament Sonrasi Refresh

W3 tournament TERFI ederse (EER-DYNAMIC v2 promoted):
- Yeni baseline: **EER-DYNAMIC v2 walk-forward returns**.
- Eski baseline (BALANCED+drop_pairs) arsivlenir: `memory/lab/drift_baselines/_archive/`.
- Refresh tarihi: **W3 sonu (2026-06-02)** veya tournament kabul tarihi + 48h.

W3 NO-PROMOTE ise: baseline degismez (BALANCED+drop_pairs kalir).

## SOP-2 Baglilik

Bu plan SOP-2'ye **ek** degil, **guncelleme**. SOP-2 her hafta calismaya devam edecek, sadece baseline pointer'i bu plan ile guncellenir. Yanlis-alarm rate KPI hedefi **< %20** ceyrek bazinda; mevcut yanlis-alarm rate kayit altinda (henuz canli yok, paper-pre).

## Sign-off

- Yazan: lab_scientist (LLM)
- Onay tipi: CEO direktif (`reports/ceo/2026-05-12-brief.md` 4.3.5)
- Hash: `lab_drift_refresh_2026-05-13_v1`
- Insan onayi gerekli: yok (operasyonel guncelleme, CEO brief'te onaylanmis)
