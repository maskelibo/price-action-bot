---
doc_id: researcher-20260611T140000-vsa-climax-volz-sweep
doc_type: hypothesis
agent_id: researcher
created_at: 2026-06-11T14:00:00Z
status: DRAFT
confidence: low
depends_on: []
blocks: []
requested_review_from: [lab_scientist, risk_officer]
tags: [vsa, volume_climax, parameter_sweep, curve_fit_risk, pre_registration]
supersedes: null
hash: null
---

# HYP-2026-06-11-vsa-climax-volz-sweep

## 0. Curve-fit Pre-warning (kendine not)

Bu hipotez **explicit parameter sweep** içeriyor (5 ayrı vol_z eşiği). Bu, dosya formatımızdaki en riskli desen — "best param" şans eseri yakalanabilir. Bu sebeple:

- Sweep eksen sayısı **tek** (vol_z), diğer parametreler sabit; çoklu eksenli grid yasak.
- Multiple-testing correction (Bonferroni k=5, FDR-BH) **zorunlu**; düzeltme sonrası anlamlılık kaybolursa hipotez ölü.
- Best vol_z eşik **uçta (2.0 veya 3.0)** ise → uzayı genişletmedik demek; **reddedilir** (parametre yetersiz tanımlanmış).
- IS/OOS Sharpe farkı **%30**'u aşarsa overfit kabul edilir → reddedilir (lesson: `lessons/overfitting_red_flags.md`).

## 1. Iddia (pre-registered, ölçülebilir)

**1d timeframe**'de, **USDT-perpetual** evreninde (3 yıl: 2023-01-01 → 2025-12-31, delisting dahil), aşağıdaki kurallarla:

- **VSA Climax tetik:** `vol_zscore[t] > X` (X parametre süpürmesi)
- **Effort/Result dengesizliği:** `bar_range[t] < 0.8 × ATR_20[t]`
- **Belirsizlik kapanışı:** `close[t] ∈ [low[t] + 0.30·range, low[t] + 0.70·range]`
- **Reversal teyit:** `sign(close[t+1] - close[t]) ≠ sign(close[t] - close[t-1])` AND `|close[t+1] - close[t]| > 0.25 × ATR_20[t]` (1-bar içinde teyit; 2-bar bekleme yasak — lookahead-prone)
- **Giriş:** `t+2` barının **open**'ı (close-of-bar karar, next-bar entry)
- **SL:** climax bar (`t`) extreme'i ± 0.2 × ATR
- **TP:** `1.5R`
- **Fees:** 7.5 bps taker, slippage 5 bps
- **Risk:** %1/trade, leverage ≤ 3x

**Parameter sweep (tek eksen):** `X ∈ {2.0, 2.25, 2.5, 2.75, 3.0}` (5 nokta, 0.25 step — ince grid yasak)

**Pre-registered pozitif sonuç tanımı (TÜM koşullar):**

| Metric | Threshold | Type |
|---|---|---|
| OOS Annualized net return | > 25% | hard |
| OOS Sharpe | > 1.0 | hard |
| OOS MaxDD | < 25% | hard |
| Profit factor | > 1.3 | hard |
| Trade sayısı (OOS) | ≥ 150 | hard |
| Walk-forward pozitif dilim oranı | ≥ 8/12 | hard |
| IS/OOS Sharpe drop | ≤ 30% | hard |
| Best X uçta (2.0 veya 3.0) | **NO** (uçta ise reddedilir) | hard |
| ≥ 3/5 X değerinde pozitif OOS Sharpe | **YES** (yoksa şans) | hard |
| Bonferroni-düzeltilmiş p (k=5) | < 0.05 | hard |
| Shuffle baseline p | < 0.05 | hard |

## 2. Gerekçe (RAG referansları)

- **[Synthesis 2026 — Volume-Price Divergence Reference §Stopping Volume]:** Yüksek hacim (Z>2.0) + küçük spread (range < 0.8·ATR) + nötr kapanış kompozisyonu klasik Wyckoff "stopping volume" deseni. Reversal teyiti 1-2 bar içinde beklenir. (RAG #9)
- **[Synthesis 2026 — VPD §Hipotez eşikleri]:** Z-score eşiği için başlangıç ±2.0σ, güçlü ±2.5σ, aşırı ±3.0σ — bu nedenle sweep uzayım 2.0–3.0 (literatür-anchored, post-hoc genişletilmedi). (RAG #4)
- **[Synthesis 2026 — VPD §HYP-03 Stopping Volume]:** mekanik kurallar 1:1 alıntı; SL=climax extreme, TP=1.5R önerisi. (RAG #9)
- **[VPD §vol_z formula]:** `vol_z = (volume[t] - mean_20) / std_20` — mevcut signal lib'inde hazır, yeni indicator inşası gerekmez (lookahead yüzeyi düşük). (RAG #1)

**Counter-evidence aranıyor:** SMC sweep + reclaim deseni (RAG #5, #7) benzer mekanik (hacim spike + reversal) sunuyor; eğer vsa_climax_test edge'i bu desenle **örtüşüyorsa** ortogonal değil → portfolio katkısı sıfır. Jaccard overlap testi zorunlu.

## 3. Null Hipotez

`H_0`: Yukarıdaki kurallarla üretilen sinyallerin getiri dağılımı, **aynı evrende rastgele zamanlanmış girişlerin** dağılımıyla istatistiksel olarak ayırt edilemez (Welch t-test p ≥ 0.05; shuffle baseline'ı yenemiyor).

**Hipotez ölür eğer:**
- IS Sharpe en iyi X için < 0.5 (literatürün vaat ettiğinden uzak)
- Trade sayısı < 100 (istatistik anlamsız)
- Bonferroni sonrası p ≥ 0.05
- En iyi X = sweep uçunda (2.0 veya 3.0)

## 4. Dependent Variables (ölçülecek)

| Variable | Birim |
|---|---|
| `annualized_return_net` (fee+slip dahil) | % |
| `sharpe_oos` | dimensionless |
| `max_drawdown_oos` | % (equity-base, NOT zero-base) |
| `profit_factor_oos` | dimensionless |
| `trade_count_oos` | int |
| `walk_forward_positive_ratio` | k/12 |
| `is_oos_sharpe_drop_pct` | % |
| `bonferroni_p_corrected` | float |
| `shuffle_baseline_p` | float |
| `jaccard_overlap_vs_smc_sweep` | [0,1] |

## 5. Independent Variables (sabit + sweep)

**Sweep:**
- `volume_z_threshold ∈ {2.0, 2.25, 2.5, 2.75, 3.0}` (5 nokta)

**Sabit (locked at pre-reg, kod yazmadan):**
- timeframe = 1d
- atr_window = 20
- spread_atr_ratio_max = 0.8
- close_range_band = [0.30, 0.70]
- reversal_min_atr_move = 0.25
- entry_offset_bars = 2 (close-of-t-bar decision, t+2 open entry)
- sl_atr_buffer = 0.2
- tp_R = 1.5
- fees_bps = 7.5
- slippage_bps = 5
- universe = USDT-perp 3y delisting-aware
- risk_pct = 0.01
- max_leverage = 3

**Sabit kalmazsa:** her ek eksen multiple-testing yükünü 5×N'e çıkarır; Bonferroni eşiği imkansızlaşır. Bu sebeple **tek eksen sweep** disiplini şart.

## 6. Beklenen p-value

- Ham (uncorrected): p < 0.01 (literatür tahmini bunu destekler)
- **Bonferroni (k=5): p < 0.01** zorunlu (= ham p < 0.002)
- Benjamini-Hochberg (FDR=0.05): ≥ 3 X eşiğinde reject H_0

Bu eşiği geçemezse → red. "Yumuşak" yorum yok.

## 7. Stop Criteria (research budget)

- **Erken durdurma:** IS Sharpe (best X) < 0.5 → araştırma derhal terkedilir, OOS'ye geçilmez.
- **Curve-fit alarm:** En iyi X 2.0 veya 3.0 ise → sweep uzayı yetersiz, hipotez **revize edilmez** (post-hoc genişletme p-hacking'tir), reddedilir + yeni hipotez ID'si açılır.
- **Compute budget:** 2 saat (vectorbt). Aşılırsa Lab'ı bilgilendir, ek hibe iste.
- **Jaccard ≥ 0.5 vs smc_sweep_reclaim:** Edge ortogonal değil → portföy katkısı sıfır, terfi adayı **değil** (live olarak ekleme).

## 8. Iterate Politikası (SOP-4b)

Eğer **aylık ROI > 0 AMA MaxDD > %25**:
- v2: risk_pct 0.01 → 0.005
- v3: confluence filter (regime: trend ≥ 1W EMA50)
- v4: BE-protect at 0.75R, trail TP

Iterate budget: 3 versiyon. Hepsi gate'i geçmezse "deferred (edge gerçek, kapasitemiz dışı)" notuyla arşivlenir, red değil.

## 9. Robustness Suite (SOP-3 zorunlu — hiçbirini atlama)

- [ ] Walk-forward 3y/6m, step 3m (12 dilim)
- [ ] Random param perturbation: vol_z ±10%, 50 seed (ortalama Sharpe kaybı < 25%)
- [ ] Symbol-out CV (her sembolü tek tek çıkar)
- [ ] Regime split (bull / bear / range — ≥ 2'sinde pozitif)
- [ ] Stress periodları: 2022-05 LUNA, 2022-11 FTX, 2023-03 USDC, 2024-08 Yen
- [ ] Shuffle baseline (returns shuffle, p < 0.05)
- [ ] Lookahead test (entry +1 bar geciktirme; edge ≤ %15 kayıpla korunmalı — aksi takdirde **timing leak**)
- [ ] Bonferroni k=5 düzeltmesi
- [ ] Jaccard overlap vs aktif smc_sweep_reclaim ve vsa_climax_test (mevcut yaşayan kol)

## 10. Mevcut yaşayan vsa_climax_test ile ilişki

Mevcut aktif `vsa_climax_test` zaten bir vol_z eşiği kullanıyor (kod tarafında sabit). Bu hipotez, **terfi adayı** değil — **mevcut kolun parametre kalibrasyonu** olabilir, eğer:
- Best X mevcut eşikten ≠ ise, **drift** sinyalidir (Lab'in drift detector'ı çalışmalı)
- Best X mevcut eşik ile aynıysa, ek alfa **YOK** — yeni doc açma gereği yok

Yani bu çalışmanın çıktısı 3 daldan biri:
1. **Recal:** Mevcut vol_z eşiğini güncelleme önerisi (CEO/Principal onayı gerek)
2. **No-op:** Mevcut eşik zaten optimal — sadece confirmation, deploy değişmez
3. **Red:** Hiçbir X gate'i geçemedi → vsa_climax_test'in vol_z bileşeni şans, mekanizma sorgulanır

## 11. Reproducibility

- git_hash: <doldur — run anında>
- config_hash: <doldur>
- data_hash: <doldur — duckdb manifest checksum>
- seed: 42 (Optuna ve shuffle baseline için)

## 12. Outputs

- `reports/research/vsa-climax-volz-sweep-2026-06-11.html`
- Decision doc: `memory/researcher/decisions/2026-06-11-vsa-climax-volz-sweep-verdict.md`
- Eğer recal önerilirse: `critique` doc Lab'e, depends_on bu hipotez

---

**Pre-registration commit'i yapılmadan kod yazılmaz. Bu doc DRAFT → PROPOSED'a geçince hash dondurulur ve sweep başlar.**
