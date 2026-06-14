---
doc_id: researcher-20260611T093000-equal-highs-sweep-15m-low-corr-to-vsa
doc_type: hypothesis
agent_id: researcher
created_at: 2026-06-11T09:30:00Z
status: PROPOSED
confidence: med
depends_on:
  - researcher-vsa-climax-test-15m-deployed-config   # aktif live edge
  - researcher-20260603T000000-bos-donchian-orthogonal-to-vsa    # önceki orthogonal denemesi
  - researcher-20260609T000000-bos-donchian-orthogonal-to-vsa    # diversifier serisi
blocks: []
requested_review_from: [adversary_engineer, lab_scientist]
tags: [hypothesis, diversifier, low-corr-to-vsa, smc, equal-highs-sweep, 15m, pre-registered]
supersedes: null
hash: null
---

# HYP-2026-06-11 — Equal Highs/Lows Sweep (15m) as Low-Correlation Diversifier to vsa_climax_test

## 0. Pre-registration meta

- **Pre-reg tarih:** 2026-06-11T09:30 UTC (kod yazılmadan önce yazılmıştır)
- **Versiyon:** 0.1 (immutable)
- **Aday strateji:** `equal_highs_sweep_15m` (shelf manifest, raftaki 66'dan 1 tanesi). Manifest: `src/price_action/strategies/manifests/equal_highs_sweep_15m.yaml`
- **Aktif rakip (eşleştiği canlı kol):** `vsa_climax_test_15m` (PHOENIX-SCALP-15m-WIDESTOP-VSA2 botunun çekirdek edge'i, dürüst beklenti aylık +%11–13.5, DD −%15..−21)
- **Sadelik kuralı (curve-fit önleme):** TEK parametre seti. Manifest'in YAML default'larını AYNEN kullan — sweep YOK, grid YOK. Beğenmezsen tamamen reddet.

## 1. Iddia (measurable, single)

> "USDT-perpetual evreninde (live config'in 19 sembolü), 2022-07-01 → 2026-06-01 arası 15m bar üzerinde, manifest'in default parametreleriyle (lookback=48, tolerance_atr=0.20, fractal_n=3, reversal_window=5, sl_atr_mult=0.5, tp_r=2.0, vol_z_min=0.5) çalışan `equal_highs_sweep_15m` stratejisi, fee 4bps taker + slippage 7.5bps dahil:
> 1. **Standalone edge:** OOS aylık mean ROI **≥ +%4.0**, OOS Sharpe **≥ 0.80**, MaxDD **≤ %25**, trade sayısı **≥ 300** (3 yıllık OOS).
> 2. **Diversification edge (KRİTİK):** Aynı 19 sembol/3 yıl penceresinde vsa_climax_test_15m günlük PnL serisiyle Pearson korelasyonu **≤ +0.20** VE trade-bar Jaccard overlap **≤ 0.10** (aynı bar/sembol'de iki strateji çakışma oranı).
> 3. **Marginal Sharpe lift:** equal_highs_sweep portföye %50/%50 risk ağırlığıyla eklendiğinde ensemble OOS Sharpe, sadece vsa_climax_test OOS Sharpe'ından **≥ +0.15** yüksek olmalı."

Hipotez ANCAK 1+2+3'ün hepsi sağlanırsa kabul edilir.

## 2. Null hypothesis (H0)

- H0a: OOS aylık mean ROI ≤ +%2.0 (edge boş)
- H0b: Pearson korelasyon > +0.30 (vsa ile aynı şeyi alıyor)
- H0c: Marginal Sharpe lift ≤ +0.05 (portföye katkı yok)

H0a VEYA H0b VEYA H0c → REJECT.

## 3. Gerekçe (RAG kaynakları — read first, code second)

- **RAG #6** *book_market_structure_order_flow* — "Equal Highs/Lows Sweep — Mekanik Çalışabilirlik **Yüksek**; Stop-hunt mekaniği crypto'da güçlü; H-2." Bu RAG, EQH/EQL sweep'i crypto'da en güçlü structural pattern'lerden biri olarak işaretliyor.
- **RAG #2** *book_candlestick_statistics (inside bar)* — Tek başına inside-bar zayıf (%54 WR), AMA volume confluence ile güçlenir. Bizim manifest `volume_zscore_min: 0.5` ile zaten volume confluence istiyor → tek-bayraklı zayıflığı azaltıyor.
- **RAG #3** *book_brooks_deep_catalog* — Brooks'un "n-bar high/low aşımı + reversal" reçetesi, EQH-sweep'in Brooks dilindeki muadili. "Tamamen kodlanabilir; en iyi hipotez adaylarından biri" notu (skala 5/5).
- **RAG #1** *book_lopez_summary* — DSR<0.5 / PBO>0.5 / IS Sharpe>3·OOS Sharpe / param/sample > 1/30 → red. Bu hipoteze multiple-testing düzeltmesi de eklenecek (aşağıda §7).

## 4. Mekanizma (neden vsa ile düşük korelasyon BEKLİYORUZ?)

| Eksen | vsa_climax_test | equal_highs_sweep |
|---|---|---|
| Tetik kaynağı | Volume spike + wide-range mum (anomaly) | Equal-level liquidity sweep + reversal (structural) |
| Zamanlama | Tek-bar event | 2-bar event (sweep + reversal_window 5 bar) |
| Bağlam | Trend exhaustion | Range-bound / liquidity grab |
| Trigger asymmetry | Asimetrik (volume rejimine bağımlı) | Yapısal (volume opsiyonel filtre) |

Conceptual overlap: her ikisi **counter-trend / reversal** doğasında — bu bir RISK FAKTÖRÜ. Bu yüzden #2 (Pearson + Jaccard) en kritik kabul kriteri.

## 5. Dependent variables (önceden donduruluyor)

1. **OOS aylık mean ROI (%)** — primary
2. **OOS Sharpe** (annualized = √(252·1440/15) ölçeklemesinde değil, fixed-fractional 1% risk, bar-bazlı returns × √252 daily aggregation)
3. **OOS MaxDD (%)** — sabit-fraksiyon, equity-relative
4. **Trade count (OOS)** — istatistiksel güç şartı
5. **Pearson corr(daily_pnl_equal_highs, daily_pnl_vsa)** — overlap proxy 1
6. **Jaccard overlap (trade-bar/sembol)** — overlap proxy 2
7. **Ensemble OOS Sharpe** (vsa+equal_highs eşit ağırlıklı)
8. **Marginal Sharpe lift** = ensemble_Sharpe − vsa_only_Sharpe

## 6. Independent variables (DONDURULDU — sweep yapılmayacak)

Manifest YAML'dan AYNEN:
- `lookback_bars = 48` (12h sweep penceresi)
- `tolerance_atr = 0.20`
- `fractal_n = 3`
- `reversal_window = 5`
- `sl_atr_mult = 0.5`
- `tp_r_multiple = 2.0`
- `atr_min_pct = 0.002`
- `volume_zscore_min = 0.5`
- `confluence.min_score = 1.5`

Bu hipotez parametre sweep'i değildir — bir KABUL/RED testidir. Sweep yapılırsa hipotez kirlenir (post-hoc), pre-reg geçersiz olur.

## 7. Multiple-testing reality check (curve-fit suspicion — açık itiraf)

**Bu hipotez tek başına bakıldığında temiz; AMA portföy bağlamında değil.**

- `memory/researcher/hypotheses/` altında 218 pre-registered hipotez var.
- "low-corr-to-vsa" / "diversifier" / "orthogonal" etiketli **en az 30 hipotez** son 6 haftada bu seed konuyu denedi (donchian, atr-breakout, kaufman, ii/iii inside, ma-cross, golden-cross, tsmom, fvg, h2-l2, marubozu, grimes-fade, mathold, halflife-rsi, brooks-fbo varyantları…).
- Aynı evren (19 sembol, 3y, 15m) üzerinde 30+ bağımsız test = FDR şişmesi. p<0.05 ham anlam taşımıyor.

**Bonferroni-style düzeltme (zorunlu):**
- Etkin family-wise α = 0.05 / 30 ≈ **0.00167**.
- Standalone edge için shuffle-baseline testinde p-value bu eşiği geçmeli.
- Marginal Sharpe lift için bootstrap CI (1000 resample) sıfırı içermemeli — alt sınır > 0.
- IS Sharpe > 3 × OOS Sharpe ise overfit → RED (Lopez kuralı).
- Param/sample oranı: 9 parametre / ~300 trade = 1/33 → Lopez 1/30 eşiğinin sınırında, FLAG (ama otomatik red değil).

## 8. Robustness suite (zorunlu — Lab'e devirden ÖNCE)

- Walk-forward: 3y train / 6m test, step 3m (manifest sabit, sadece sample dilimleri kayar)
- Param perturb: ±%10 her parametrede 50 seed → ortalama Sharpe kaybı < %25
- Symbol-out CV: her sembolü tek tek dışarıda bırak; min OOS Sharpe > 0.3
- Regime split: bull / bear / range → en az 2'sinde pozitif aylık
- Stress periodları: 2022-05 LUNA, 2022-11 FTX, 2024-03 BTC ATH, 2024-08 Yen carry — herhangi birinde MaxDD bot-equity'in -%15'inden kötü olmamalı
- Shuffle baseline: trade-returns shuffle, p < 0.00167
- Lookahead delay testi: entry +1 bar geciktir, edge ≥ %70 korunmalı (yapısal-trend kanıtı, timing-arbitraj DEĞİL)

## 9. Beklenen p-value & stop criteria

- **Pre-committed primary p-value (shuffle baseline):** < 0.00167 (Bonferroni 30-trial)
- **Stop criteria — kod çalıştırırken hangi noktada hipotezi terk ederim:**
  1. In-sample Sharpe < 0.5 → TERK (literatür minimum eşik altında).
  2. Trade sayısı (OOS 3y, 19 sembol) < 200 → TERK (istatistiksel güç yetersiz).
  3. Pearson corr (vsa daily pnl) > +0.35 → TERK (mekanizmanın "düşük korelasyon" temeli düştü — şiddetli mekanik fark beklerken bulamadık).
  4. IS/OOS Sharpe farkı > %50 → REDDET (Lopez kuralı).
- **3 iterate budget (SOP-4b):** ROI pozitif ama gate düşerse v2/v3/v4 (risk reduction, confluence filter, regime filter). v5'te de geçmezse "deferred" arşiv.

## 10. Karar matrisi (ön taahhüt)

| Sonuç | Karar |
|---|---|
| 1 + 2 + 3 hepsi PASS + robustness PASS + Bonferroni PASS | Lab tournament'a devret (champion-vs-challenger) |
| 1 PASS, 2 FAIL (corr > 0.20 ama < 0.35) | Iterate v2 — regime filter veya symbol subset ile decorrelate denemesi |
| 1 PASS, 3 FAIL (lift < 0.15) | Iterate v2 — risk weight ayarı veya entry timing offset |
| 1 FAIL (ROI < %4 veya Sharpe < 0.80) | RED — gerçek edge yok; arşivle |
| Bonferroni FAIL | RED — multiple-testing kazanını geçemedi |
| Stress period MaxDD < −%15 | RED — bot-equity riskli |

## 11. Reproducibility stamps (run sonrası doldurulacak)

- git_hash: TBD (run anındaki HEAD)
- config_hash: SHA256(equal_highs_sweep_15m.yaml content) — TBD
- data_hash: SHA256(used parquet shards index) — TBD
- backtest engine version: TBD

## 12. Iterate önceden tanımı (SOP-4b — pozitif edge'i koruma)

Eğer aylık ROI > 0 AMA gate FAIL ise REDDETMEK YASAK. Aşağıdaki iterate patikalarından **maks 4** denenecek:
- v2: `volume_zscore_min: 0.5 → 1.0` (trade quality filter)
- v3: bull-only regime gate (`trend_filter.required: true`)
- v4: BE-protect 1R sonrası SL → entry
- v5: risk weight 0.5× (portföye düşük ağırlık ekle)

5'ten fazla iterate edilmez — pozitif ama bizim kapasitemizde değil notuyla "deferred".

## 13. Lab'a teslim öncesi kontrol listesi

- [ ] Pre-reg commit edildi (git hash dondurma)
- [ ] Backtest engine production_replay parity ile çalıştı
- [ ] Lookahead delay testi temiz
- [ ] Robustness suite tamamlandı
- [ ] Bonferroni hesabı raporda
- [ ] Marginal Sharpe bootstrap CI raporda
- [ ] Aktif champion (vsa_climax_test_15m) ile günlük PnL serisi yan yana grafiği eklendi

---

**Sonraki adım:** Bu hipotez `PROPOSED` statüsünde. Lab + Adversary review → critique/endorse. Onay sonrası `backtest/engine.py` ile çalıştır. Sonuçlar `reports/research/equal-highs-sweep-15m-2026-06-11.html`.
