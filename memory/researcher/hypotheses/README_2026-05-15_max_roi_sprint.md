---
sprint_id: max_roi_2026_05_15
date: 2026-05-15
author: researcher_agent (claude-opus-4-7-1m)
ceo_brief: max_roi_sprint — v2.0.3 production champion (3y rolling +%239.5 / DD -%38.7 / r-adj 6.190) üzerine ROI maksimizasyon + DD minimizasyon
git_hash_at_registration: 3da3344b2e69992f45e3acd8c40d4b399808e14f
status: PRE_REGISTERED (5 paralel HYP)
multiple_testing: BONFERRONI n=5, alpha_adj = 0.05 / 5 = 0.010 per HYP
backtest_status: HENÜZ ÇALIŞTIRILMADI (sadece pre-reg)
---

# Max ROI Sprint — 2026-05-15 — 5 Paralel HYP Pre-Registration

## Çerçeve

Bu sprint, v2.0.3 production champion'u **ROI uplift + DD smoothing** yönünde maksimize etmeyi hedefler. 5 yeni boyut paralel olarak pre-registered edildi. Her HYP **kodu yazılmadan önce** dosyalandı (Renaissance/De Shaw disiplini).

### v2.0.3 Champion Baseline (KORUNAN)
- 3y rolling 13 pencere: **yıllık +%239.5 / DD -%38.7 / risk-adj 6.190**
- 5y in-sample: %97.6 / -%59 (sansa bağımlı, daha az ağırlıklı)
- TOP_11 strateji + FVG + pyramid (1.0R/2.0R: 50/30) + multi-target (1R/2R: 30/30/40, trail 1.0 ATR) + BALANCED preset (r%4, DD breakers, cap 0.30, halt + F&G binary fear-skip)

### Sprint Disiplini

1. **Renaissance/De Shaw paranoia** — Walk-forward 3y/6mo/3mo (n=13), Bonferroni n=5 (α_adj=0.010), bootstrap CI low > 0, shuffle null p<0.05 zorunlu, look-ahead audit.
2. **Pre-registration kuralı** — Tüm hipotezler bu README'de listelenen 5 HYP ile sabit. Yeni HYP eklenmek isteniyorsa **kod yazımı öncesi** dosya açılır.
3. **Strict scope guards (HARK koruması)** — Aşağıdaki üç sınıf hipotezlerden uzak durulur:
   - ❌ Mean-reversion sınıfı (SEC22 RED + EER + ML zinciri kanıtı, 6 sprint)
   - ❌ Trade-level ML filter (SEC15-17 ML zinciri, 3 sprint RED)
   - ❌ 4h primary timeframe (SEC6 r-adj 0.414 vs 1d 1.029)
   - ❌ Yeni strategy detector standalone (Sec4 + sec19 kanıtı: TOP_10+FVG saturation, ensemble katkı 0)
4. **Yeni boyut prensibi** — Sizing / leverage / TP-trail / volume confluence / correlation graduated — **mevcut framework'e ek katman**, yeni detector değil.

---

## 5 Hipotezin Sıralaması (ROI-Impact × P(Success))

| # | HYP | Sınıf | ROI Impact (beklenen alpha) | P(success) | Score | Pre-Reg Dosyası |
|---|---|---|---|---|---|---|
| 1 | **DD-Aware Dynamic Leverage** | Risk Overlay | +%5pp - +%25pp + DD -3pp ile -7pp | 0.65 | **0.85** | [2026-05-15-dd-aware-dynamic-leverage.md](./2026-05-15-dd-aware-dynamic-leverage.md) |
| 2 | **Alt-Data Continuous RII Sizer** | Regime/Sentiment | +%4pp - +%13pp | 0.50 | **0.65** | [2026-05-15-alt-data-continuous-regime-intensity-sizer.md](./2026-05-15-alt-data-continuous-regime-intensity-sizer.md) |
| 3 | **Correlation Graduated Sizing** | Portfolio Exposure | +%3pp - +%30pp (DD risk var) | 0.55 | **0.60** | [2026-05-15-correlation-graduated-sizing.md](./2026-05-15-correlation-graduated-sizing.md) |
| 4 | **VSA Volume Confluence Sizer** | Quality 5th Dim | +%2pp - +%15pp | 0.40 | **0.50** | [2026-05-15-vsa-volume-confluence-sizer.md](./2026-05-15-vsa-volume-confluence-sizer.md) |
| 5 | **Vol-Pct Multi-Target TP v2** | Engine Conditional | +%2pp - +%12pp | 0.40 | **0.45** | [2026-05-15-vol-percentile-aware-multi-target-tp-v2.md](./2026-05-15-vol-percentile-aware-multi-target-tp-v2.md) |

### Score Hesaplama Mantığı
- `Score = (ROI impact mid-point / max ROI in sprint) × P(success)`
- DD smoothing katkısı +%5 ek skor (HYP-001 yaltırdı)
- Combo orthogonality bonusu (her HYP diğer 4'le bağımsız çalışabilir): HYP-001/002/003 orthogonal layer set

---

## Sırasıyla Özet

### HYP-001 — DD-Aware Dynamic Leverage (priority 1)
**Kısa iddia:** Portfolio rolling-14d equity DD %5 üstü → leverage scalar 1.00x → 0.50x → 0.33x (saturating floor), DD bittikten 7g sonra 1.00x'e dön.

**Neden #1:**
- DD smoothing v2.0.3'ün en bariz açığı (DD -%38.7 worst pencere ~-%55 tahmin)
- Ralph Vince + Thorp + Lo + López de Prado birleşik literatür kanıtı güçlü
- Mevcut SEC26.B-1 side-cond DD breaker'ın doğal portfolio-equity continuous extension'ı
- v0.9.4 capitulation halt zaten regime-level binary kanıtladı bu yolu açtı
- Implementation basit, replay parity için byte-identical default (enabled: false)

**Hassas nokta:** KH-1 (bull-trend recovery rally kaçırma); regime split bull-dilim alpha pozitif olmalı.

### HYP-002 — Alt-Data Continuous RII Sizer (priority 2)
**Kısa iddia:** F&G binary fear-skip yerine 4-feature continuous Regime Intensity Index (F&G + funding_z + OI delta + RV percentile) → sizing scalar [0.5, 1.5].

**Neden #2:**
- F&G binary zaten kanıtlı (+%3pp B3 sweep WIN-WIN); continuous yumuşatma marjinal ama orthogonal feature'lar ek edge potansiyeli
- "Vs F&G binary" karşılaştırması zorunlu — RII overengineering riski açık
- HYP-2026-05-12-funding-oi-divergence RED'i OI data yokluğundan; bu HYP OI ingest sonrası revival
- Per-trade scalar 0.5x-1.5x range, recovery agresif

**Hassas nokta:** OI 5y historical ingestion **BLOKLAYICI** (data engineer prereq). KH-1: 4 feature'ın 3'ü gürültü, sadece F&G katkı sağlar (feature ablation gate).

### HYP-003 — Correlation Graduated Sizing (priority 3)
**Kısa iddia:** Mevcut binary corr_gate (reduction_factor=0.5 + hard_block=0.9) yerine graduated cluster sizing (1st: 1.00x, 2nd: 0.50x, 3rd: 0.25x, 4+: blocked).

**Neden #3:**
- v0.9.9 drop_pairs etkisiz olduğu için (halt + F&G zaten dolaylı filtreliyor) bu HYP **rolling correlation** ile dynamic versiyon dener
- HYP-REGIME-cluster-throttle PARTIAL (rho=0.70 fazla sıkı); graduated yumuşatma fix
- Capital utilization artışı %35 → %43 doluluk hedefli
- Slot bottleneck "mit"ini (SEC21) graduated exposure ile aşar — farklı bir yol

**Hassas nokta:** KH-1 (graduated = cluster içi 1.5x exposure → DD artar). DD bozulması tolerance +%2pp HARD. KH-4 (slot doldurma kötü pair'lar girer).

### HYP-004 — VSA Volume Confluence Sizer (priority 4)
**Kısa iddia:** Confluence_score 4-dim'e 5. dim ekle: VSA 4-component (climax + no-supply/no-demand + effort-vs-result) volume layer → sizing scalar [0.80, 1.20].

**Neden #4:**
- Anna Coulling + Tom Williams + Wyckoff literatür güçlü ama crypto 1d perpetual'da edge yokluk riski yüksek
- Mevcut volume strategy'leri (vsa_climax_test, obv_engulfing, cvd_spike_fade) edge gösterdi → underlying volume signal var
- Q4-Q1 mean_R spread ≥ +0.10 HARD gate (gürültü mü gerçek edge mi?)
- Sizing modulator olarak slot saturation'ı bypass eder (yeni detector değil)

**Hassas nokta:** KH-2 (daily TF VSA gürültülü). KH-3 (4-component aşırı parametrik). KH-7 (per-window Q4-Q1 CI geniş).

### HYP-005 — Vol-Pct Multi-Target TP v2 (priority 5)
**Kısa iddia:** TP1=1.0R/TP2=1.5R/trail=1.0 ATR sabit yerine, per-symbol 14d RV 90d-percentile linear → TP1=0.6R-1.4R, TP2=1.0R-2.0R, trail=0.5-1.5 ATR.

**Neden #5:**
- v0.8 multi-target engine'in (HYP-2026-05-09-009) doğrudan extension'ı (+%6.5pp baseline)
- v1.2 sec11b primary_R sweep (2.0 → 1.5 +%9.5pp) zaten lokal optimum gösterdi; dynamic conditioning marjinal
- Turtle + Carver + Raschke literatürü vol-conditional exits
- Engine framework değişikliği orta-büyük (place_protection_orders dynamic param)
- HYP-002 RII'nin RV-feature ile combo decomposition gerekli (same feature, different layer)

**Hassas nokta:** KH-1 (v2.0.3 zaten optimize, marjinal). KH-7 (partial oranlar UNCHANGED — v2 sweep için bırakıldı).

---

## Combo Test Matrisi (Sprint Sonu, FAIL Olmayanlar İçin)

5 HYP orthogonal layer'larda yer alıyor:
- **HYP-001:** Portfolio equity → leverage scalar (entry)
- **HYP-002:** Macro regime → risk_pct scalar (entry)
- **HYP-003:** Cross-symbol exposure → risk_pct scalar (entry)
- **HYP-004:** Per-trade volume confluence → risk_pct scalar (entry)
- **HYP-005:** Per-trade vol regime → TP/trail (exit)

Eğer ≥ 2 HYP PASS olursa, **decomposition combo testleri**:
- Ablation matrix: 2^k senaryo (k = PASS sayısı)
- Per-HYP marginal alpha
- Synergistic / antagonistic effect kontrolü

**Combo gate:** combo alpha ≥ sum(individual alpha) × 0.6 olmalı (orthogonality sağlam — overlap < %40).

---

## Veri ve Reproducibility

```
sprint_id: max_roi_2026_05_15
git_hash_at_registration: 3da3344b2e69992f45e3acd8c40d4b399808e14f
data_window: 2021-01-01 → 2026-05-15 (5y)
universe: BTC, ETH, SOL, BNB, ADA, AVAX, LINK, DOT, DOGE, XRP, MATIC (11 sym)
strategies: TOP_11 + FVG (mevcut champion)
walk_forward: 3y train / 6mo OOS / 3mo step → 13 pencere
multiple_testing: bonferroni n=5, alpha_adj = 0.010
baseline_ref: v2.0.3 BALANCED+pyramid+halt+F&G binary fear-skip (configs/risk_balanced.yaml @ 3da3344)
prereq:
  - HYP-001: NONE (mevcut data)
  - HYP-002: OI 5y historical (data engineer ingest — BLOCKING)
  - HYP-003: NONE (mevcut ohlcv → 90d corr)
  - HYP-004: NONE (mevcut volume kolonu)
  - HYP-005: NONE (mevcut RV computable)
```

---

## Karar Akışı

```
Phase 1 — Pre-Reg DONE (bu README + 5 HYP dosyası)
Phase 2 — Backtest Engine Setup
   - HYP-001: kod yazılır + ablation set
   - HYP-002: BLOCKED until OI ingest
   - HYP-003: kod yazılır + ablation set
   - HYP-004: kod yazılır + ablation set
   - HYP-005: kod yazılır + engine framework hazır
Phase 3 — 13-Window Walk-Forward Run (paralel)
Phase 4 — Shuffle Null + Bootstrap CI + Bonferroni
Phase 5 — Robustness Suite (7-8 test per HYP)
Phase 6 — PASS / RED Karar (HYP başına)
Phase 7 — PASS olanlar için Combo Test Matrix
Phase 8 — Lab tournament: champion vs combo candidate(s)
Phase 9 — Production gate: paper trade 30g → live enable
```

---

## Sınırlar ve Yasaklar

- ❌ Bu README'deki 5 HYP **sabit**. Yeni HYP eklemek için ayrı pre-reg dosyası gerekli.
- ❌ HYP backtest sonucu görülmeden parametre güncellemesi YASAK (HARK).
- ❌ FAIL durumda learning log olmadan v2 pre-reg yazılmaz.
- ❌ Multi-testing correction bypass YASAK — Bonferroni p<0.010 zorunlu.
- ❌ Combo testleri sadece individual PASS sonrası yapılır; FAIL HYP'leri combo'ya çekme YASAK.
- ❌ Production'a (configs/strategies veya configs/risk_balanced.yaml final) **insan onayı + Lab kabulü** gerekli; Researcher sadece aday üretir.

---

## Memory Index

- DD-Aware Leverage: `memory/researcher/hypotheses/2026-05-15-dd-aware-dynamic-leverage.md`
- RII Sizer: `memory/researcher/hypotheses/2026-05-15-alt-data-continuous-regime-intensity-sizer.md`
- Correlation Graduated: `memory/researcher/hypotheses/2026-05-15-correlation-graduated-sizing.md`
- VSA Confluence: `memory/researcher/hypotheses/2026-05-15-vsa-volume-confluence-sizer.md`
- Vol-Pct Multi-Target: `memory/researcher/hypotheses/2026-05-15-vol-percentile-aware-multi-target-tp-v2.md`
- Bu README: `memory/researcher/hypotheses/README_2026-05-15_max_roi_sprint.md`

---

## Sprint Sonuçları (DOLDURULACAK)

| # | HYP | Status | Mean Alpha | DD Delta | Robustness | Karar |
|---|---|---|---|---|---|---|
| 1 | DD-Aware Leverage | PRE_REG | __ | __ | __/7 | __ |
| 2 | RII Sizer | PRE_REG (blocked) | __ | __ | __/8 | __ |
| 3 | Correlation Graduated | PRE_REG | __ | __ | __/7 | __ |
| 4 | VSA Confluence | PRE_REG | __ | __ | __/7 | __ |
| 5 | Vol-Pct Multi-Target | PRE_REG | __ | __ | __/7 | __ |

**Combo test (PASS olanlar):** __

**Lab tournament champion vs combo candidate(s):** __

**Production aday (insan onayı + Lab kabulü sonrası):** __
