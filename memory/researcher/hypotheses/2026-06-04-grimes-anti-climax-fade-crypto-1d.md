---
doc_id: researcher-20260604T000000-grimes-anti-climax-fade-crypto-1d
doc_type: hypothesis
agent_id: researcher
created_at: 2026-06-04T00:00:00Z
status: DRAFT
confidence: low
depends_on: []
blocks: []
requested_review_from: [lab_scientist, risk_officer, adversary_engineer]
tags: [hypothesis, climax-fade, mean-reversion, grimes-anti, crypto-1d, pre-registration]
supersedes: null
hash: null
---

# HYP-2026-06-04-grimes-anti-climax-fade-crypto-1d

## 0. Meta

- **Versiyon:** 0.1 (pre-registration; kod yazılmadan dondurulur)
- **Seed konu:** Günlük tarama — yeni RAG ekleri ışığında PA edge sinyalleri
- **A priori beklenti:** **NEGATİF** (literatür → şüphe). Aşağıda "Curve-fit Şüpheleri" bölümü açıkça gerekçeleniyor.

## 1. İddia (tek cümle, ölçülebilir)

> 1D timeframe'de, herhangi bir bar `r_t = (high - low) / ATR_200` > **2.0** sağladığında ("climax bar"), bir sonraki bar'ın **open**'ında climax yönünün **KARŞI** yönünde pozisyon açılırsa (SL = climax bar high/low ± 0.25 × ATR_200, TP = 2R), 2021-01-01 → 2026-06-01 USDT-perpetual 15-sembol evreni (delisting-aware), 55 bps round-trip fee+slip ile:
>
> - **Net mean R per trade > +0.10R** (yani gross edge fee'yi geçecek + güvenlik)
> - **Net annualized return > %15**
> - **MaxDD (account-equity bazlı) < %25**
> - **Win rate ∈ [%38, %48]** (Grimes'ın community claim aralığı)
> - **Toplam trade N > 150** (istatistiksel power için)
> - **Direction-shuffle baseline p_gross < 0.05** (zorunlu null'u geç)

## 2. Null Hipotez (H0)

Climax-fade entry'nin gerçek yön sinyali yoktur:
- `mean(real_R_gross) − mean(shuffled_R_gross)` 50 seed shuffle'da p ≥ 0.05.

H0 reddedilmezse iddia reddedilir (gross edge sıfır → fee tartışmasına bile girilmez).

## 3. Gerekçe (RAG referansları)

- **[Grimes book_summary]** — "Anti" setup: trend-overextended bar (ATR 2x+, Bollinger 2σ üstü, climax bar) sonrası ilk küçük pullback'te trend-KARŞI küçük kontre. Claim: WR ~%40-45, R 2-3R, EV hafif pozitif. **Açık uyarı:** "zor ve yüksek-iskontolu setup; sadece deneyimli traderlar için."
- **[Kaufman book_summary]** — RSI divergence + trend-exhaustion noktalarında fade'in işe yaradığı, ama "strong trend'de divergence saatlerce/günlerce devam eder" uyarısı. Filtresiz tek başına RSI fade RED.
- **[López book_summary] — DSR çerçevesi**: birden çok parametre denersek Deflated Sharpe Ratio < 0.6 = strateji **rastlantı**. Bu hipotez için Bonferroni/BH zorunlu (bkz §7).
- **[Chan book_summary]** — Mean-reversion Sharpe ∝ 1/√half-life. 1D crypto'da climax-sonrası mean-reversion half-life'ı tahmini 3-7 gün → 1D timeframe çalışma alanı içinde.
- **[Volman book_summary]** — Climax sonrası "exhausted moves" — destekleyici ama Volman 5m'de konuşur, 1D ekstrapolasyonu özgün iddia.

## 4. Dependent Variables (önceden tanımlı, kilitli)

| Metrik | Tanım | Hesap noktası |
|---|---|---|
| `mean_R_gross` | Trade başına ortalama R, fee/slip hariç | Trade close |
| `mean_R_net` | Trade başına ortalama R, 55 bps round-trip fee+slip dahil | Trade close |
| `annual_return_net` | Compounded annualized net return, sabit-fraksiyon sizing (risk_pct=0.005) | Equity curve sonu |
| `max_dd` | Account-equity bazlı maksimum drawdown (peak-to-trough) | Equity curve |
| `win_rate` | (trades with R > 0) / total_trades | Tüm trade'ler |
| `n_trades` | Toplam trade sayısı | Backtest sonu |
| `p_gross_shuffle` | 50 seed direction-shuffle null karşı p-value | Bootstrap |
| `per_year_pos_count` | 6 yılın kaçında yıllık net R pozitif | Yıllık dilim |
| `is_oos_sharpe_ratio` | IS Sharpe / OOS Sharpe | Walk-forward |

## 5. Independent Variables (parametre uzayı — sınırlı tutulur)

**KİLİTLİ baseline (curve-fit önleme):**
- `climax_atr_mult`: **2.0** (sadece bu — daha fazla denersem multiple-testing inflation)
- `atr_window`: **200**
- `pullback_window`: **1 bar** (yani t'de climax → t+1 open'da contra-entry)
- `sl_offset_atr`: **0.25**
- `tp_R`: **2.0**
- `risk_pct`: **0.005**
- `fee_round_trip_bps`: **55**

**Sensitivity (RED kararından SONRA, ancak SOP-3 robustness için):**
- `climax_atr_mult` ∈ {1.5, 2.5, 3.0} — perturbation
- `tp_R` ∈ {1.5, 2.5} — perturbation
- Bu yan denemelerden GELEN herhangi bir iyileşme **Bonferroni-düzeltilmiş** p < 0.05 değilse RED.

## 6. Beklenen p-value & Sample Size

- Beklenen H0 reddi: **p_gross < 0.05** (Bonferroni sonrası < 0.05 — tek baseline, n_test=1, düzeltme = identity).
- Sensitivity perturbation sayısı 4 (mult × tp_R çapraz). Bunlar denenirse Bonferroni eşik **0.05/4 = 0.0125**.
- Sample size hedefi: **N > 150 trade** (15 sembol × ~10 climax/yıl × 5 yıl ≈ 750 ham aday; selectivity sonrası ~150-300 beklenti).

## 7. Multiple-Testing Disiplini

- Sadece **1 baseline config** raporlanır (terfi kararı).
- Sensitivity grid'i ayrı raporlanır, hiçbiri "yeni baseline" olarak öne sürülemez.
- IS/OOS split walk-forward (3y train, 6m test, step 3m) zorunlu.
- López DSR çerçevesi: rapor edilen Sharpe için DSR ≥ 0.6 zorunlu, < 0.6 ise "rastlantı" etiketi.

## 8. Stop Criteria (önceden kilitli — RED gerekçeleri)

Aşağıdakilerden **herhangi biri** → hipotez RED, iterate yapılmaz (yön curve-fit'tir):

1. **`p_gross_shuffle` > 0.05** → gross edge sıfır, sinyalin yönü rastgele. Bu, fee'den önceki bariyer.
2. **`mean_R_gross` < 0.05R** → fee'yi geçemez, fee filtresinden önce zaten ölü.
3. **`n_trades` < 100** → istatistik anlamsız.
4. **`win_rate` ∉ [%30, %55]** → Grimes claim aralığının çok dışı; setup detector hatalı ya da iddia yanlış.
5. **`is_oos_sharpe_ratio` > 1.6** → overfit imzası.
6. **`per_year_pos_count` < 4/6** → en az 4 yıl pozitif olmalı; yoksa rejim-bağımlı şans.
7. **Sensitivity perturbation'da baseline ortalaması ±%10 parametre ile Sharpe kaybı > %35** → curve-fit.
8. **Lookahead testi başarısız** (causal detector hatası) → RED + signal_chief'e incident.

## 9. Curve-fit Şüpheleri (a priori — şeffaflık için)

Bu hipotezi yazarken aşağıdaki **kırmızı bayrakları görüyorum**, lütfen review eden ajanlar bunları doğrulasın:

1. **`climax_atr_mult=2.0` keyfi.** Grimes "ATR'nin 2 katı" diyor ama bu 1D crypto için kalibre edilmemiş. 1.5, 2.0, 2.5, 3.0 hepsi savunulabilir → multiple testing tuzağı.
2. **"İlk pullback" tanımı belirsiz.** Volman 1-2 mum, Grimes net değil. 1-bar baseline'ı seçtim; 2-bar/3-bar denersem grid şişer.
3. **`tp_R=2.0` keyfi.** Grimes 2-3R diyor. 2.5R seçersem belki daha iyi; bu da multiple testing.
4. **`sl_offset_atr=0.25` keyfi.** Climax bar high/low'a "kadar" mı, "ötesi" mi belirsiz; bu küçük offset curve-fit risk.
5. **A priori beklenti NEGATİF (kendi learning.md'm):**
   - "bar-OHLCV → yön mapping'i crypto'da ~rastgele" (SMC/SFP, Fabio, smc-course-no-edge — tümü RED).
   - VSA climax-intensity FALSIFIED (V12 entry-quality çalışması — "louder capitulation ≠ better test").
   - Bu hipotez VSA climax'ın bir varyantı (sadece direction reversed). Aynı temel iddia: "climax → mean-revert."
6. **Grimes kendi kitabında "düşük WR, deneyimli traderlar için" uyarısı koyuyor** — yani kitabın yazarı bile bunun mekanik backtest'te çalışmasından emin değil. RAG referansı destek değil, **uyarı** olarak okunmalı.
7. **Selection bias riski:** "Climax" tanımı backtest dönemine göre ayarlanabilir (örn. 2021 boğa zirvesi, 2022 LUNA, 2024 ATH). Stress-test bu dönemleri AYRI tutmalı (SOP-3 #6).

**Sonuç: Bu hipotezi yazmamın tek sebebi, eğer p_gross < 0.05 GEÇERSE bu, prior'umu güncelleyen güçlü bir bulgu olur. GEÇMEZSE, dördüncü kez aynı dersi öğreniyoruz: crypto 1D bar climax'ı mean-revert için yön taşımıyor.**

## 10. Robustness Suite (zorunlu — SOP-3)

Sadece ana karar p_gross < 0.05 GEÇERSE şu aşamalara geçilir:

1. Walk-forward (3y/6m, step 3m).
2. IS/OOS Sharpe ratio < 1.6.
3. ±%10 parametre perturbation, 50 seed → Sharpe kayıp < %35.
4. Symbol-out CV (15 sembol leave-one-out): min OOS Sharpe > 0.
5. Regime split: bull/bear/range — en az 2'sinde pozitif.
6. Stress periods: 2022-05 LUNA, 2022-11 FTX, 2024-03 ATH, 2024-08 Yen — yıkıcı DD yok.
7. Shuffle baseline p_gross < 0.05 (yukarıda kilitli).
8. Bonferroni: n_test = 1 baseline + 4 sensitivity = 5 → eşik 0.01.

## 11. Karar Matrisi

| Sonuç | Karar |
|---|---|
| Stop criteria HER birini geçti, terfi-gate metrikleri ✓, robustness ✓ | **Terfi adayı** → Lab tournament |
| Stop criteria #1 (p_gross > 0.05) FAİL | **RED — clean negative**, iterate yok (yön curve-fit'tir) |
| Pozitif gross edge ama net negatif veya DD yüksek | **İterate** (SOP-4b: risk reduction, confluence filter, regime subset) |
| Lookahead/leakage tespit edildi | **RED + incident**, signal_chief audit |

## 12. Reproducibility

- `git_hash`: <doldurulacak commit anında>
- `config_hash`: <doldurulacak>
- `data_hash`: data/market.duckdb @ 2026-06-04
- Backtest komutu: `python -m price_action.backtest.engine --config configs/research/HYP-2026-06-04-grimes-anti.yaml --shuffle-seeds 50 --walk-forward 3y/6m`

## 13. Pre-registration Kilidi

Bu doc commit edildiği anda parametreler **dondurulur**. Sonradan değişiklik:
- Eski hipotez `status: SUPERSEDED`
- Yeni hipotez doc'u, `supersedes: <bu doc_id>`
- "Sonuçları görünce parametre tweak" → **YASAK** (post-hoc curve-fit).
