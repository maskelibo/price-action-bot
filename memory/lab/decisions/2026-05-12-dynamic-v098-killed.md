---
adr_id: LAB-ADR-2026-05-12-001
agent: lab_scientist
type: decision
status: ACCEPTED (production-blocking)
date: 2026-05-12
title: "DYNAMIC v0.9.8 preset — KARANTINA (production-blocking)"
supersedes: none
superseded_by: pending (EER-DYNAMIC v2, W3 tournament)
related:
  - reports/ceo/2026-05-12-brief.md (4.3)
  - memory/lab_scientist/learning_20260512_microstructure_inventory.md
  - memory/lab_scientist/learning_20260512_ml_scoring.md
hash: lab_adr_2026-05-12_v1
confidence: high
---

# ADR — DYNAMIC v0.9.8 KILLED + Karantinaya Alindi

## 1. Baglam

v0.9.7 BALANCED+F&G preset 3y rolling 13 pencere ort. yillik **+%36.13**, DD **-%30**,
min pencere **+%22** (13/13 pozitif), production gold. CEO + Lab "guvenli sinyale
buyuk bas" hipoteziyle v0.9.8 DYNAMIC preset onaylandi:

- conf_pct (180g rolling rank) 4 tier: %2 / %4 / %6 / %7 risk
- leverage tiers: 3x / 4x / 5x
- top tier (conf_pct >= 0.90): "10/10 checklist" sinyallere %7 risk + 5x lev
- master flag: `use_confidence_dynamic_sizing: true`

Hipotez: yuksek confluence_score → yuksek out-of-sample edge → yuksek pozisyon.

## 2. Karar (Verdict)

**DYNAMIC v0.9.8 preset production-blocking. KARANTINAYA alindi. Geri donulmemeli.**

- Dosya tasimasi: `configs/risk_dynamic.yaml` -> `configs/_archive/risk_dynamic_v098_killed.yaml` (DONE — bkz. `configs/_archive/`)
- Backtest entegrasyonu: `scripts/v098_dynamic_backtest.py` `_archive` adayidir (silinmesin — replikasyon icin lazim, ama production benchmark uretici scriptlere ASLA tekrar baglanmasin).
- `scripts/v092_build_benchmark.py` yapilandirma listesi: DYNAMIC SATIRI YOK (dogrulandi 2026-05-12 — eklenmemis halde, eklenmesin).

## 3. Sayisal Gerekce

| Metrik | BALANCED (v0.9.7+F&G) | DYNAMIC (v0.9.8) | Delta |
|---|---:|---:|---:|
| 3y rolling 13 pencere mean ann | +%36.13 | **+%2.5** | **-%33.6pp** |
| 3y rolling min ann | +%22.0 | -%1.1 | -%23pp |
| 3y rolling max ann | +%47.6 | +%6.3 | -%41pp |
| r-adjusted (mean/-dd) | 1.200 | **0.109** | -91% |
| n_trade (5y in-sample) | 68 | **21** | -69% |
| Negatif pencere | 0/13 | 7/13 | catastrophic |
| 1y OOS single window (2023-2026 ekstrapole) | +%34-38 (tahmin) | **-%0.28** | RED |

**Sample-size collapse**: 68 -> 21 trade. Bu, varyans tahmininin tek-pozisyon-cikis-aciligi
seviyesinde yetersiz oldugu anlamina geliyor — istatistiksel guc neredeyse sifir.

## 4. Kok Neden (Causal Analysis)

### Birincil neden: confluence_score gercek edge yansitmiyor

- 4787 trade'in **%96.9'u** `[0.30, 0.40)` ham conf bucket'inde.
- 180g rolling percentile rank uygulanca **%77 sinyal "top-tier" (conf_pct >= 0.90)** etiketlendi (yapay yigilma).
- Ust kuyrukta avg_R **%0.013** (neredeyse sifir) — "guvenli sinyaller" sansli sinyaller, edge skoru degil **isaret yogunlugu skoru**.
- Ablation matrisi: conf >= 0.30 vs >= 0.20 delta yillik **0.00pp** (ham conf threshold etkisi sifir).

### Ikincil neden: tier dagilimi yapay (%18/%4/%0/%78)

- Tasarim hedef: %50/%25/%15/%10 sinyal her tier'a.
- Gerceklesen: %18/%4/%0/%78 — **conf yapay sekilde upper tail'e yigilmis**, alt tier'lar bos.
- Bos orta tier'lar = uniform risk = "sizing yok" + top-tier'in nominal kazanci da margin cap'ine tosluyor.

### Ucuncu neden: notional_cap + leverage etkilesimi sinyalleri rejekt ediyor

- %7 risk + 5x leverage tetiklenince notional/equity = ~%175.
- max_notional_pct_equity = 0.30 cap → buyuk sinyaller **reddediliyor**.
- Sonuc: tasarimda "yuksek guvenli sinyale yuksek pozisyon" → gerceklikte "yuksek guvenli sinyaller alinmiyor", **frekans %69 dustu, kalite artmadi**.

## 5. Karar Cercevesi (Lab Scientist standard)

| # | Soru | Cevap |
|---|---|---|
| 1 | Veri ne diyor? | n=21, 7/13 negatif pencere, r-adj 0.109 — istatistiksel red |
| 2 | Effect size yeterli mi? | Evet — **negatif** -33.6pp yillik (kotu yonde buyuk etki) |
| 3 | Coklu test duzeltmesi? | 4 tier x 11 sym x 13 pencere = 572 hipotez — Bonferroni gereksiz; doğrudan red |
| 4 | Aksiyon | **RED — karantina** |
| 5 | Yanlis-pozitif / yanlis-negatif maliyeti | Yanlis-negatif (DYNAMIC aslinda iyiydi): cok dusuk olasilik (sample size collapse + ablation kanit). Yanlis-pozitif maliyeti uygulanmasa sifir |
| 6 | Geri cevrilebilirlik | Var — YAML `_archive/` altinda, replikasyon icin script korundu |

## 6. Implikasyonlar (Production)

1. **Champion v0.9.7 BALANCED+F&G kaldi** (geri donus). Paper trade hipotezi bu config olarak ilerleyecek.
2. **W1 commit**: `risk_balanced.yaml`'a drop_pairs YAML loader eklenecek (kanit edilmis +%10.81pp uplift) — bu CEO commit listesi madde 1.
3. **Tier degisikligi YOK** — EER-Score (Researcher W2 cikti) hazir olana dek mevcut conf threshold (>=0.20 filter, sizing icin etki yok) korunacak.
4. **Yeni dynamic preset uretimi YASAK** — EER-DYNAMIC v2 hazir olana dek (W3 tournament).

## 7. Yapilmayacaklar (Kati Yasak)

- DYNAMIC v0.9.8 yaml'ini "tweak" ile iyilestirmeye calismak (cop, tier dagilimi yapisal sorun, formul oynamasi ile cozulmez).
- Yeni conf-bazli sizing preset onermek (EER hazir olmadan).
- Tournament gate'lerini gevsetmek (DSR p, effect size, MaxDD floor).
- Top-tier'i daraltarak (>=0.95 cut) DYNAMIC'i "kurtarmak" — kanit yetersiz, n daha da dusuk.

## 8. Ogrenilen Ders (learning.md'ye yansiyacak)

> **conf bir kalite metrigi degil, format metrigi.** Sizing'i kalite metrigine baglamadan once metrigin **realized edge** ile korelasyonunu istatistiksel olarak gostermeli. Aksi takdirde "yuksek conf'a yuksek risk" hipotezi tasarim hatasidir, parametre hatasi degil.

**Ileride**: Her sizing preset'i icin onkosul — kalite metrigi sample-size >= 30 her bucket'ta + walk-forward edge p < 0.05 + shuffle null yenilmeli. Bu prensip artik **gate**.

## 9. Sign-off

- Yazan: lab_scientist (LLM)
- Onay tipi: CEO direktif (`reports/ceo/2026-05-12-brief.md` 4.3)
- Insan principal onayi: pending (W1 commit oncesi)
- Hash: `lab_adr_2026-05-12_v1`
