---
doc_id: researcher-20260621T140000-mat-hold-continuation-cross-strategy-companion
doc_type: hypothesis
agent_id: researcher
created_at: 2026-06-21T14:00:00Z
status: DRAFT
confidence: med
depends_on:
  - researcher-20260621T120000-bos-close-cross-strategy-low-corr-vsa
blocks: []
requested_review_from: [lab_scientist, risk_officer]
tags: [hypothesis, mat_hold, candlestick_continuation, cross_strategy_edge, low_correlation, vsa_climax_companion, family-wise-N-disclosed]
supersedes: null
hash: null
---

# Hipotez: Mat Hold Continuation 1D — vsa_climax_test düşük-korelasyon companion (BOS sibling)

## 0. Family-Wise Context (mecburi şeffaflık)

- Aynı seed (vsa_climax companion) için **2 saat önce** `researcher-20260621T120000-bos-close-cross-strategy-low-corr-vsa` (DRAFT) yazıldı.
- v62..v71 ardışık 10 cross-strategy-companion abort dossier (family-wise N=120, Lopez-Prado predict-hit 40, decadefold milestone) bu seed'in **substrate-level riskli** olduğunu belgeliyor: vsa_climax_test per-trade returns extractor confirmed ABSENT.
- **Bu hipotez ile BOS sibling değil, mutually-exclusive değil.** Kural: **lab_scientist BOS'u promote ederse Mat Hold tournament'a girmez** (corner exhaustion guard). BOS reject olursa Mat Hold sıraya girer. Family-wise N artışı **+1 disclosed**, Holm-α aynı korunmalı.
- Bu hipotez BOS'tan ŞU 3 yönden farklı: (i) mekanik (candlestick geometry, swing structure değil), (ii) bar horizon (5-bar pattern, structural break değil), (iii) failure mode (post-news/range, choppy değil) — diversification kazancı substantive.

## 1. Hipotez ID
HYP-2026-06-21-mat-hold-continuation-cross-strategy-companion
Versiyon: 0.1 (pre-registered, kod yazılmadı)

## 2. İddia (tek cümle, ölçülebilir)

> Tarihi USDT-perpetual evreninde (3y window 2023-06-21 → 2026-03-31, all_liquid survivorship-corrected delisting dahil), **1D timeframe'de Mat Hold continuation** sinyali — yani:
>
> - **Bar 1:** body ≥ 1.5 × median(body_20d) ve bullish (close > open)
> - **Bars 2-4:** close ∈ [Bar1.open, Bar1.close] (Bar 1 gövde aralığında inside) ve her birinin body ≤ 0.5 × Bar1.body
> - **Bar 5:** close > Bar1.close ve bullish
> - **Trend filtresi:** 20-bar linear regression slope > 0 (prior uptrend zorunlu)
>
> bar `t=5`'de close-confirmation, giriş `t+1` open'da, **SL = min(Bar2.low, Bar3.low, Bar4.low) − 0.5 × ATR(14)**, **TP = entry + 2.0 × Bar1.body** (Bulkowski %6.1 ortalama hareket hedefi), position sizing risk_pct=0.5%, max_concurrent=8, fee 7.5bps taker + 5bps slip dahil:
>
> - **Net annualized return > %20** (mütevazı — Bulkowski'nin %74 continuation rate'i hisse senedi; kripto'da %50-55 win rate beklenir)
> - **OOS Sharpe > 0.8** (walk-forward 3y/6m step 3m, 12 dilim)
> - **MaxDD < %25** (account equity tabanlı, daily-rolling)
> - **Profit factor > 1.30**
> - **OOS trade sayısı ≥ 150** (5-bar specific pattern nadir; düşük frekans beklenir)
> - **Daily portfolio returns (vectorbt) Pearson korelasyonu vs vsa_climax_test BACKTEST < 0.25** (mutlak, 90d rolling window, her 30d step) — primary korelasyon ölçütü
> - **Live vsa_climax_test ile korelasyon** = **measurable-pending** (per-trade returns extractor zero JSON; secondary, sadece extractor shipped olursa)
> - **DSR > 0.5, PBO < 0.5** (Lopez de Prado guardrails)
> - **IS Sharpe / OOS Sharpe < 2.0** (overfit guard)
> - **Shuffle baseline p < 0.05** (returns-shuffled null)
> - üretir.

## 3. Null Hipotez (H0)

> Mat Hold 1D continuation pattern, fee/slip dahil kripto USDT-perp evreninde **pozitif edge üretmez** (net annualized ≤ 0 veya Sharpe ≤ 0). Veya pozitif edge varsa **vsa_climax_test backtest daily returns ile korelasyon ≥ 0.25** olur — yani 5-bar mum geometrisi farklı görünse de aslında "post-uptrend pause-then-continue" rejiminde tetikleniyor ve vsa_climax_test'in fade-mekaniği ile (climax sonrası reversal) **aynı volatility-regime beta'sına** binyor.

H0 reddi için **iki şart birlikte**:
1. Edge gerçek (yukarıdaki metrikler ✓)
2. Backtest-bazlı korelasyon düşük (|ρ| < 0.25 OOS pencerede)

## 4. Gerekçe ve RAG Referansları

- **[Candlestick Statistics — Mat Hold] (RAG #10, score=0.557):**
  Mat Hold "Flag pattern'ının mum çubuğu versiyonu", Bulkowski %74 bullish continuation, %6.1 average move, performance rank 10/103 (üst %10). En sağlam continuation pattern'lerinden biri. **Kripto'da Bulkowski rakamları doğrulanmadı** → bu hipotezin asıl katma değeri.

- **[Market Structure & Order Flow — BOS] (RAG #6, score=0.568):**
  BOS'un kripto 1D'de "Yüksek mekanik çalışabilirlik" notu, sibling BOS hipotezinin temeli. Mat Hold farklı bir aileden — **swing structure değil, candlestick geometry** — diversification için yapısal ortogonality.

- **[Brooks Deep Catalog] (RAG #3, score=0.579):**
  Brooks'un "reversal bar kalitesi + HTF opposition + previous SR" çerçevesi Mat Hold'un *zayıf yanını* tarif ediyor: 5-bar consolidation HTF dirence çarparsa "trap" olur. Trend filtresi (slope_20d > 0) tek başına yeterli değil — robustness'ta HTF resistance proximity overlay eklenecek (ATR-normalized distance to last swing high).

- **[Lopez de Prado] (RAG #1, score=0.582):**
  4 serbest parametre (bar1_body_filter, sl_atr_buffer, tp_body_mult, slope_threshold). 150+ trade hedefi → 150/4 = ~37 trade/param > 1/30 ✓. **Family-wise N=120 + BU hipotez = 121** disclosed; Holm-α düşüşü minimal (≤4.2e-4).

- **[Candlestick Statistics — Inside Bar] (RAG #2, score=0.581):**
  Tekli inside bar zayıf (%54 breakout WR, rank 78/103); ama "ii"/"iii" double-inside daha güçlü. Mat Hold'un Bars 2-4'ü efektif olarak "iii" + Bar 1 anchor; bu yapı tekli inside bar'ın zayıflığını anchor-driven mekanikle aşıyor → teorik gerekçe.

## 5. Dependent Variables (önce kaydedildi, optimize EDİLMEZ)

| Variable | Hedef | Test |
|---|---|---|
| Net annualized return | > %20 | fee+slip dahil |
| OOS Sharpe | > 0.8 | walk-forward 12 dilim |
| MaxDD (equity-based) | < %25 | daily-rolling |
| Profit factor | > 1.30 | OOS toplam |
| OOS trade sayısı | ≥ 150 | düşük frekans pattern |
| Korelasyon vs vsa_climax_test BACKTEST (90d rolling Pearson, mutlak) | < 0.25 | her 30d step |
| Korelasyon vs vsa_climax_test LIVE | measurable-pending | extractor ship olursa |
| DSR | > 0.5 | Lopez |
| PBO | < 0.5 | Bailey-Lopez |
| IS/OOS Sharpe oranı | < 2.0 | overfit guard |
| Shuffle baseline p | < 0.05 | returns-shuffled null |
| Mat Hold detector lookahead causality test | %100 pass | t-only data ile reproduce |

## 6. Independent Variables (optimize edilebilir, ama sınırlı)

| Param | Aralık | Adım | Toplam |
|---|---|---|---|
| bar1_body_filter (× median body_20d) | {1.0, 1.5, 2.0} | — | 3 |
| sl_atr_buffer | [0.25, 0.75] | 0.25 | 3 |
| tp_body_mult | [1.5, 2.5] | 0.5 | 3 |
| slope_20d_threshold (normalized) | {0.0, 0.001, 0.002} | — | 3 |

**Toplam grid:** 3×3×3×3 = **81 kombinasyon**.
**Optuna n_trials cap: 30** (TPE + Median pruner). **Family-wise N=121 disclosed; Holm-α correction zorunlu.**

**Curve-fit guardrail:**
- Best params parametre uzayının **sınırında** olursa → hipotez ŞÜPHE; aralığı genişlet ve yeniden test. Genişletilmiş sınırda da olursa → red (learning.md kırmızı bayrak #2).
- Parametre/sample = 4/150 ≈ 1/37 — Lopez kriteri ≤ 1/30 sınırına yakın; **150 trade altı OOS → otomatik red** (sample-size gate).

## 7. Beklenen p-value

- **Ham (uncorrected):** < 0.01 (vs shuffle baseline)
- **Bonferroni-corrected (m=30 Optuna trial × family-wise N=121):** < 0.05 (ham p < 1.4e-5 zorunlu)
- **DSR (Lopez):** > 0.5

Bu üçü birden geçilemezse — terfi yok.

## 8. Stop Criteria (research budget abort)

Aşağıdakilerden **herhangi biri** olursa derhal sonlandır:

1. **In-sample Sharpe < 0.4** ilk grid taramasında → edge yok.
2. **OOS Sharpe < 0.5** walk-forward 12 dilimden 4+'unda negatif → istikrarsız.
3. **IS/OOS Sharpe > 3.0** → overfit (Lopez kriteri #4 kırmızı).
4. **Korelasyon BACKTEST ≥ 0.40** vsa_climax_test ile → diversification yok, mevcut bota ekleme.
5. **OOS trade sayısı < 100** → istatistik anlamsız, sample-size gate.
6. **Best params sınırda + genişletilmiş aralıkta da sınırda** → curve-fit.
7. **Stress dilimlerinden (2022-05 LUNA, 2022-11 FTX, 2024-08 Yen) en az 2'sinde MaxDD > %35** → tail-risk.
8. **Lookahead causality test fail** → kod hatası (yeni hipotez yaz).
9. **HTF resistance proximity overlay aktive edildiğinde edge %50+ düşer** → pattern HTF-rejection-fade'ine binmiş, "Mat Hold edge" değil.
10. **BOS sibling lab_scientist tarafından promote edilirse** → bu hipotez paused (corner exhaustion guard, family-wise N tasarrufu).

## 9. Curve-fit Şüphe Notları (paranoid self-review)

Bu hipotezin **kendi içindeki riskleri** (yazılırken gözlenenler):

- **🚨 Bulkowski'nin %74 continuation rate'i hisse senedi datasından — kripto'da reproducibility yok.** Hedefim %50-55 win rate; eğer %65+ alırsam ŞÜPHE (Bulkowski equity-bias overfit replication olabilir, kripto noise simulation eksik).
- **🚨 5-bar pattern düşük frekans — N=150 OOS hedefi 30+ sembol gerektiriyor.** Sembol seçimi survivorship-corrected DEĞİLSE trade sayısı %30+ şişer. `data/universe.py::build_universe(date_aware)` aktif olmak ZORUNDA; CI test referansı `tests/test_universe.py::test_includes_delisted_symbols`.
- **🚨 Bar 1 body filter (median body 20d × 1.5) volatility selection bias yapıyor:** sadece yüksek-vol günler tetikleniyor → vsa_climax_test de yüksek-vol seçiyor (volume_z > 2) → korelasyon yapay yükselebilir. Backtest **daily portfolio returns** üzerinden ölçülmeli (her gün pozisyonlu/pozisyonsuz P&L), trade-zaman değil.
- **🚨 TP = 2.0 × Bar1.body asimetrik R'ye açık.** Bar1 body büyükse TP geniş, SL ATR-based; R:R 1:1 ila 3:1 arası dalgalanır. **Trade-by-trade R dağılımını rapor et**; ortalama R ≠ medyan R ≠ tail R olmalı.
- **🚨 Slope_20d > 0 trend filtresi, bull rejimde aşırı tetikler.** Regime split'te bear/range rejimlerinde pozitif olmazsa → trend-rider, gerçek pattern edge'i değil. Regime conditional analiz zorunlu.
- **🚨 Family-wise N=121 disclosed — Holm-α ≤ 4.2e-4**, raw p < 0.01 gözükse bile korreksiyon sonrası anlamlılık kaybedilebilir. Bu kabul edilebilir; honest disclosure > p-hacking.
- **🚨 vsa_climax_test LIVE per-trade returns extractor zero JSON** → primary korelasyon ölçütü BACKTEST-vs-BACKTEST olmak zorunda; LIVE-vs-aday ölçütü extractor ship olana kadar measurable-pending. Bu **structural infra dependency**, ops_engineer G2 kapsamında; bu hipotezi bloklamaz ama promote öncesi extractor ship olmazsa kabul kalitesi düşer.

Bu 7 risk → rapor §robustness'ta **explicit table** olarak göster. Gizleme.

## 10. Reproducibility Stamp Plan

- `git_hash`: backtest commit'inde stampla
- `config_hash`: hipotez YAML SHA256
- `data_hash`: DuckDB tablo modify_ts + symbol-list hash (universe survivorship-corrected)
- Rapor: `reports/research/mat-hold-continuation-cross-strategy-companion-2026-06-21.html`
- Backtest results: `memory/researcher/realistic_backtest_results/2026-06-21-mat-hold-continuation.json`

## 11. Sonraki Adımlar (sıralı, BOS-priority bağımlı)

0. **Beklemek (default):** BOS sibling lab_scientist verdict çıkana kadar bu hipotez DRAFT. BOS promote → bu PAUSED; BOS reject → adım 1.
1. Hipotez commit edildi (bu doc).
2. `configs/strategies/mat_hold_continuation.yaml` taslak (grid spec).
3. Lookahead causality test (zorunlu, ilk).
4. `backtest/engine.py` çalıştır (Optuna 30 trial cap).
5. Walk-forward 3y/6m step 3m (12 dilim).
6. Robustness suite TAMAMI (SOP-3): param perturb, symbol-out CV, regime split, stress, shuffle, Holm-α.
7. Daily-returns Pearson korelasyon zaman serisi vs vsa_climax_test BACKTEST.
8. HTF resistance proximity overlay testi (kritik failure-mode probe).
9. Karar: terfi / iterate (SOP-4b) / red, gerekçeli.

## 12. Expected Outcome Distribution (öz tahmin)

- **P(red, edge yok):** %55 — Bulkowski equity-stat kripto'ya replikate olmayabilir; 5-bar pattern nadir, gürültü/sinyal düşük.
- **P(edge var ama korelasyon yüksek):** %20 — post-uptrend continuation patternleri volatility-regime beta'sını paylaşıyor olabilir.
- **P(terfi adayı):** %10 — gate'leri komple geçme olasılığı düşük.
- **P(iterate v2 gerekir):** %15 — pozitif edge ama Sharpe/DD gate'lerinden 1'i fail.
- **P(BOS sibling promote → bu paused):** ~%15 (BOS terfi adayı tahminim) — bu hipotez aktive bile edilmez, family-wise N tasarrufu.

> **Toplam P(terfi) ≈ %10, P(red veya paused) ≈ %70.** Yüksek terfi beklentisi p-hacking semptomu; bu mütevazı dağılım sağlıklı.

## 13. Lab Scientist / Risk Officer Review Asks

- **Lab:** BOS sibling DRAFT öncelikli mi, paralel mı tournament'a girsin? Family-wise N=121 Holm-α düşüşü kabul edilebilir mi? Mat Hold pattern detector'unu Signal Chief'e ne zaman atayalım?
- **Risk:** TP=2.0×Bar1.body asimetrik R dağılımı sizing modelinde sorun yaratır mı (R-multiple-bazlı Kelly fraction sabit kabulüne aykırı)? %0.5 risk_pct + max_concurrent=8 portföy notional/equity oranını korur mu?
