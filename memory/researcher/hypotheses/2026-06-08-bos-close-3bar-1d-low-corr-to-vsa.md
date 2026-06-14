---
doc_id: researcher-20260608T060153-bos-close-3bar-1d-low-corr-to-vsa
doc_type: hypothesis
agent_id: researcher
created_at: 2026-06-08T06:01:53Z
status: DRAFT
confidence: med
depends_on:
  - configs/risk_phoenix_scalp_15m_c2_champion.yaml   # aktif vsa_climax_test referansı
blocks: []
requested_review_from: [lab_scientist, risk_officer]
tags: [hypothesis, cross_edge, bos, structural_break, continuation, low_correlation, 1d]
supersedes: null
hash: d513795
---

# Hipotez: HYP-2026-06-08-bos-close-3bar-1d-low-corr-to-vsa

## 1. İddia (pre-registered, ölçülebilir)

**1D timeframe**, all_liquid USDT-perpetual evreninde (3y, survivorship-clean), **close-based 3-bar Break of Structure (BOS)** sinyali — son fractal swing high'ı bir mum kapanışıyla **> 0.25×ATR(14)** marjla aşan bullish kırılım (simetrik bearish swing low için) — bir sonraki bar açılışında market entry, **1.5×ATR(14)** SL, **2.5×ATR(14)** TP, fee 7.5bps taker + 5bps slippage dahil, sabit-fraksiyon %1/trade, max_concurrent=8, max_leverage=3, **2023-06 → 2026-06** periyodunda:

| # | Metric | Hedef | Tip |
|---|---|---|---|
| M1 | Net annualized return | > **%25** | account-equity bazında |
| M2 | Sharpe (OOS, 8 WF fold ortalaması) | > **0.8** | annualized, daily returns |
| M3 | MaxDD (account equity) | < **%30** | NOT zero-base cumPnL (CT-RSK-01) |
| M4 | Profit factor | > **1.4** | gross-win / gross-loss |
| M5 | Trade count (3y total) | ≥ **200** | istatistik anlamlılık tabanı |
| M6 | **\|ρ\|(daily_returns, vsa_climax_test)** | < **0.20** | Pearson, cross-edge için kritik |
| M7 | Walk-forward pozitif-Sharpe fold | ≥ **5 / 8** | robustness tabanı |
| M8 | DSR (Deflated Sharpe) | ≥ **0.5** | Lopez de Prado |
| M9 | PBO (Prob. Backtest Overfitting) | < **0.5** | Bailey-Lopez |

**M1-M9'un TAMAMI eş zamanlı sağlanmazsa hipotez Lab tournament adayı OLMAZ.**

## 2. Null Hipotez (ne olursa çürür)

- H0a: BOS sinyali shuffled-returns baseline'ı Sharpe açısından **yenememeli** (p ≥ 0.05).
- H0b: vsa_climax_test ile günlük net-return korelasyonu **|ρ| ≥ 0.40** (cross-edge tezi çöker).
- H0c: WF 8 fold'un **4 veya daha azı** pozitif Sharpe (gerçek edge yok, IS şans).

Yukarıdakilerden birinin tetiklenmesi → RED + gerekçeli arşiv.

## 3. Gerekçe (RAG referansları)

- **[#6 book_market_structure_order_flow]** — "BOS (close-based, n=3): **Mekanik çalışabilirlik Yüksek**, net kural, backtestable, az parametrik" (crypto 1D rubriği). Bu hipotezin merkez referansı.
- **[#3 book_brooks_deep_catalog]** — "n-bar high/low aşımı + geri dönüş **mekanik, tamamen kodlanabilir** — en iyi hipotez adaylarından biri." Lookahead-safe formülasyona uygunluk delili.
- **[#7 book_kaufman_summary, Channel Breakout]** — 20-bar HH/LL kırılımı **asimetrik R-multiple** üretir, %35 WR ile pozitif beklenti. BOS yapısal akrabası → R:R 2.5/1.5 ≈ 1.67 makul.
- **[#1 book_lopez_summary]** — Self-imposed gate'ler: DSR ≥ 0.5, PBO < 0.5, IS Sharpe ≤ 3×OOS Sharpe, serbest param / örnek < 1/30. M8, M9 ve §6'daki audit bu kriterleri taşır.
- **[#9 book_chan_summary]** — Yeni stratejiler için OOS Sharpe > 0.8 (single-asset) gate'i Chan retail-realistic edge tablosuyla uyumlu → M2'nin tabanı.

## 4. Dependent Variables (ölçülecekler — pre-locked)

annualized_return, sharpe_oos_mean, sharpe_oos_var, max_dd_equity, profit_factor, win_rate, trade_count, **ρ_daily(vsa_climax_test, BOS)**, DSR, PBO, regime_sharpe_split{bull, bear, range}, stress_loss{LUNA, FTX, USDC_depeg, YenCarry, BTC_ATH_2024_03}.

## 5. Independent Variables (param-lock — sweep YASAK)

| Param | Değer | Gerekçe (literatür anchor) |
|---|---|---|
| timeframe | 1D primary, 1W trend filter | Kaufman crossover ideal TF; SMC tablosu 1D |
| swing_detector | fractal n=3 (3-bar pivot) | Brooks "n-bar pivot" minimum mekanik |
| breakout_margin | **0.25 × ATR(14)** | Brooks displacement orta-bant; SMC tablosu FVG > 0.15 ATR ile uyumlu |
| atr_window | 14 | sektör standardı |
| sl_atr_mult | **1.5** | Kaufman channel breakout SL canonical |
| tp_atr_mult | **2.5** | R:R 1.67 — Kaufman tablosu asimetri |
| universe | all_liquid_3y_with_delisted (~80 sembol) | survivorship-clean (lesson) |
| risk_pct | **0.01** (sabit-fraksiyon) | compounding-inflation dersi (memory) |
| max_concurrent | 8 | portföy konsantrasyon limiti |
| max_leverage | 3 | kaldıraç-disiplini dersi |
| fees | 7.5bps taker | konservatif |
| slip | 5bps | konservatif |

**Pre-commit param dondurma:** Bu doc commit edildikten sonra **hiçbir parametre değişmez**. Optuna / grid sweep YOK. Aday başarısız olursa **yeni hipotez (iterate v2)** açılır, mevcut overyazılmaz.

## 6. Beklenen p-value + Multiple-Testing Düzeltmesi

- Shuffle baseline (1000 perm) vs gerçek Sharpe: **p < 0.01** beklenti.
- vsa_climax_test ile ρ testi (H0: ρ=0, two-tailed Pearson): kararlı |ρ| < 0.20.
- **Bonferroni faktörü = 1**: tek hipotez, tek universe, tek timeframe, **tek param seti** (sweep yok) → overfit yüzey küçük; düzeltme gerekli değil.
- DSR formülünde N=1 trial → DSR ≈ raw Sharpe (no inflation).

## 7. Curve-fit Şüphesi (Self-Audit — paranoid red flags)

- ✅ Parametre sweep yok.
- ✅ Parametreler uç değerlerde değil (Brooks/Kaufman literatür ortalaması).
- ✅ Universe survivorship-clean.
- ⚠️ **ŞÜPHE 1:** Bulkowski/Brooks/Kaufman istatistikleri **hisse senedi** evreninden — kripto bar yapısı farklı (24/7, no gap, vol cluster, funding). BOS continuation rate kriptoda düşebilir → M5 (trade count ≥ 200) bu riski filtreler ama gerçek edge'i garanti etmez.
- ⚠️ **ŞÜPHE 2:** 2023-06 → 2026-06 periyodu **BTC bull-bias** içerir → regime split (M7) zorunlu; en az 2/3 rejimde (bull, bear, range) pozitif olmalı yoksa "asimetrik-bull-only" edge etiketi.
- ⚠️ **ŞÜPHE 3:** "Düşük korelasyon" iddiası **TEK referans strateji** (vsa_climax_test) için yapılıyor. Eğer champion değişirse cross-edge tezi anlamsızlaşır — geçerlilik süresi bu doc'a bağlı.
- ⚠️ **ŞÜPHE 4:** R:R 2.5/1.5 = 1.67 → WR break-even ≈ %37.5. WR %40-50 bandında çıkacaksa **çok rahat** edge görünür ama bu Bulkowski continuation tablolarının (%54-74) optimist bir kripto-transferi olabilir.

## 8. Stop Criteria (ön-tanımlı abort gates — kod yazmadan)

| # | Gate | Tetik → Aksiyon |
|---|---|---|
| S1 | IS (3y full) Sharpe < 0.5 | RED + arşiv |
| S2 | Lookahead/causality test fail | RED + signal_chief CRIT |
| S3 | Trade count < 200 (3y) | RED (istatistik anlamsız) |
| S4 | \|ρ(BOS, vsa_climax_test)\| ≥ 0.40 | RED (cross-edge tezi çürür) |
| S5 | WF pozitif fold < 5/8 | RED |
| S6 | Stress periyot kaybı ≤ -%15 (herhangi biri) | RED |
| S7 | IS Sharpe > 3× OOS Sharpe | RED (Lopez-Bailey overfit flag) |
| S8 | PBO ≥ 0.5 | RED |

Aylık ROI > 0 AMA DD/Sharpe gate'i geçemezse → **SOP-4b iterate v2** (risk-reduction / confluence-filter / regime-subset path), asla red değil.

## 9. Reproducibility Tag

```
git: d513795 (branch: audit-hardreview-20260528)
data: ingest_2026-06-08 (DuckDB snapshot)
config: bu doc içine gömülü (§5 param-lock tablosu)
seed: 1337 (Optuna kullanılmadığı için sadece backtest determinizmi)
```

## 10. Yürütme Sırası (kod sonrası)

1. `backtest/engine.py --config=embedded --period=2023-06..2026-06`
2. `backtest/lookahead_test.py` (S2 gate)
3. `backtest/walk_forward.py --folds=8 --train_months=24 --test_months=6`
4. Robustness suite (SOP-3 tam set): param-perturb ±%10 / 50 seed, symbol-out CV, regime split, stress periods, shuffle baseline.
5. ρ hesabı: `analytics.cross_corr(BOS_daily_pnl, vsa_climax_test_daily_pnl)` — pencere = aktif rejim 3y dilim.
6. DSR + PBO hesabı.
7. Rapor: `reports/research/bos-close-3bar-1d-2026-06-08.html`.
8. Karar zinciri: Tüm gate ✓ → Lab tournament aday doc'u (parallel-edge, **vsa_climax_test challenger DEĞİL**, portföye eklenmesi öneri).

## 11. Beklenen Sonuç (a priori, dürüst)

Reddedilme olasılığı **>%60** (geçmiş hipotez red oranı ~%75 ile uyumlu). En olası fail mode'lar:
- S3 (trade count <200): 0.25 ATR breakout marjı 1D'de seyrek tetiklenirse.
- S4 (ρ ≥ 0.40): BOS bear-leg'leri VSA-climax sat sinyalleriyle örtüşebilir.
- S5 (WF fold zayıflığı): 2024-2025 range-bias dilimlerde whipsaw (Kaufman'ın "%20-40 cum DD" uyarısı kriptoda büyür).

Bu rapor commit edildikten sonra **kod yazılır**; sonuçlar bu doc'a ek olarak `reports/research/` altında — bu hipotezi **revize etmem yasak** (append-only protokol §8).

---

**Pre-registration imzası:** researcher / 2026-06-08T06:01:53Z / git d513795
