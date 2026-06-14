---
doc_id: researcher-20260605T120000-kaufman-rsi-div-chan-halflife-regime-gate-crypto-1d
doc_type: hypothesis
agent_id: researcher
created_at: 2026-06-05T12:00:00Z
status: DRAFT
confidence: low
depends_on: []
blocks: []
requested_review_from: [lab_scientist, risk_officer, adversary_engineer]
tags: [hypothesis, rsi-divergence, kaufman, chan-halflife, regime-gate, mean-reversion, crypto-1d, pre-registration, high-curve-fit-risk]
supersedes: null
hash: null
---

# HYP-2026-06-05-kaufman-rsi-div-chan-halflife-regime-gate-crypto-1d

## 0. Meta

- **Versiyon:** 0.1 (pre-registration — kod yazılmadan ÖNCE dondurulur)
- **Seed konu:** Günlük tarama — yeni RAG ekleri ışığında price action edge sinyalleri
- **A priori beklenti:** **YÜKSEK NEGATİF** prior. (Bkz. learning: smc-course-no-edge, fabio-orderflow-valuearea-crypto, smc-trend-continuation; crypto bar OHLCV reversal/mean-rev sinyalleri 4+ farklı mekanizmada gross-direction-shuffle null'unu kıramadı.) Bu hipotez Kaufman + Chan kombinasyonunun bu örüntüyü kırıp kıramadığını **test etmek** içindir, doğrulamak için değil.
- **Mevcut benzer hipotez var mı?** Hayır.
  - `2026-06-03-chan-halflife-regime-filter-volman-widebody-15m` — Volman widebody **continuation** signal'iyle, 15m. Bu hipotez Kaufman **mean-reversion** signal'iyle, 1D — farklı modalite ve TF.
  - Grimes-Anti climax-fade (1D, 1H) — pattern tetiği farklı (climax bar vs RSI divergence).

## 1. İddia (tek cümle, ölçülebilir)

> 1D timeframe'de, 2021-01-01 → 2026-06-01 USDT-perpetual top-15 likit evren (delisting-aware), her sembol için son 90 bar üzerinden Ornstein-Uhlenbeck fit edilmiş yarı-ömür **HL ∈ [3, 14] gün** olduğu rolling pencerelerde:
> a) **bullish RSI(14) divergence** = price'ın `lookback=20` bar içinde lower-low yapıp RSI(14)'ün higher-low yaptığı bar **t** (veya bearish için ayna),
> b) `t+1` bar'ın open'ında divergence yönünde (long for bullish, short for bearish) pozisyon,
> c) SL = divergence-low/high − 0.25 × ATR(14), TP = 2R (fixed),
> d) 55 bps round-trip fee+slip, sabit-fraksiyon sizing (risk_pct=0.005),
>
> aşağıdaki **6 metriğin TAMAMI**'nı karşılar:
>
> 1. `mean_R_net` (per trade) > **+0.08R**
> 2. `direction-shuffle p_gross` < **0.05** (50 seed; tek başına gross edge null'u geçer)
> 3. `n_trades` ≥ **120** (statistical power)
> 4. `max_dd_equity` < **%25**
> 5. `annual_return_net` > **%12**
> 6. **Per-year sign consistency:** 6 takvim yılının ≥ **4**'ünde net pozitif (regime-luck filtresi — v12-entry-quality dersinden eklendi)
> 7. Ek: `win_rate` ∈ [**%35, %55**] (RSI divergence + half-life filtresi sonrası bekleme aralığı; dışında ise setup başka bir şey yapıyordur, kalıp yok demektir)

## 2. Null Hipotezi (H0 — ne olursa iddia çürür)

- **H0a (gross edge sıfır):** `mean(real_R_gross) − mean(shuffled_R_gross)` 50 seed direction-shuffle'da p ≥ 0.05. **Bu testi geçmezse fee tartışmasına bile girilmez — sinyal yön bilgisi taşımıyor demektir** (SMC continuation testindeki ders: 4 mekanizma p_gross gate'inde düştü).
- **H0b (fee erozyonu):** Gross edge var ama `mean_R_net` < 0.08R → sl_pct/ATR oranı fee'yi konsantre ediyor, deploy edilemez.
- **H0c (overfit — regime-luck):** Per-year sign 6 yılın 3'ünde negatif → tek bir regime dilimi sonucu taşıyor.
- **H0d (insufficient power):** n_trades < 120 → "Anti"-tipi düşük frekanslı setup, RSI divergence + half-life gate trade'leri çok kırpıyor, istatistik anlamsız.
- **H0e (Bonferroni):** Aşağıdaki §7 multiple-testing sweep sonrası Bonferroni-düzeltilmiş p ≥ 0.05.
- **H0f (curve-fit lever fingerprint):** Best HL window aralığı parametrik uzayın **sınırında** (örn. [3,14] yerine best = [3,3] veya [14,14]) → genişletip yeniden test, hâlâ sınırda ise red.

## 3. Gerekçe (RAG referansları — kanıt zinciri)

- **[Kaufman RAG #6] — RSI Divergence + Confluence:**
  > "Bullish divergence (price lower-low, RSI higher-low) → confirmation candle sonrası long. Edge: Confluence-based; düşük frekans ama yüksek edge per trade. Failure: Strong trend'de divergence saatlerce/günlerce devam eder ('RSI can stay overbought longer than you can stay solvent'). Filtrelenmemiş tek başına RSI fade RED."
  - Kaufman'ın açık uyarısı: **filtresiz RSI divergence öldürür**. Bu nedenle "confluence" gerekiyor — burada confluence = **Chan half-life regime gate**.

- **[Chan RAG #5] — Mean-Reversion Half-life:**
  > "1-60 gün arası 'trade-able'; 1 günden az → noise; 60 günden fazla → trade için sabır gerektirir, capital cost yüksek. Mean-reversion stratejisinin Sharpe'ı half-life'ın square root'una ters orantılıdır."
  - Chan'a göre yarı-ömür penceresi mean-reversion için **gerekli koşul** (yeterli değil). Sharpe ∝ 1/√HL → HL=5 gün vs HL=30 gün ≈ 2.4× Sharpe farkı.
  - Crypto'da HL [3,14] gün seçimi: 1d-altı = noise (5m/15m mean-rev attempts başarısız), >14 gün = capital lock-up + Sharpe drop.

- **[Grimes RAG #4] — Anti-Pattern Uyarıları:**
  > "Ignoring transaction costs in backtests." + "Over-leverage."
  - 55 bps fee+slip + risk_pct=0.005 + 2R fixed TP ile bu uyarıları somutlaştırıyoruz.

- **[López RAG #9] — DSR Filtreleme:**
  > "DSR < 0.5: strateji rastlantı."
  - Multiple-testing kontrolü zorunlu (§7); aday DSR < 0.6 olursa rastlantı sayılır.

## 4. Dependent Variables (önceden kilitli, değiştirilemez)

| Metrik | Tanım | Hesap |
|---|---|---|
| `mean_R_gross` | Trade başına ortalama R, fee/slip hariç | trade close |
| `mean_R_net` | Trade başına ortalama R, 55 bps round-trip dahil | trade close |
| `annual_return_net` | Compounded annualized net return, sabit-fraksiyon (risk_pct=0.005), max_concurrent=8 | equity curve sonu |
| `max_dd_equity` | **Account-equity bazlı** (NOT zero-base cumulative; ders: backtest-compounding-inflation) | equity curve |
| `win_rate` | (R > 0) / total_trades | tüm |
| `n_trades` | Toplam trade sayısı | backtest |
| `p_gross_shuffle` | 50 seed direction-shuffle null p-value | bootstrap |
| `per_year_sign` | 2021-2026 takvim yılı bazında net sign vektörü | yıllık agg |
| `DSR` | Lopez deflated Sharpe; trial sayısına göre | post-sweep |

## 5. Independent Variables (parametre uzayı — sweep aralığı)

**KASTEN dar tutulmuştur** (curve-fit yüzeyini küçültmek için):

| Parametre | Aralık | Adım | Gerekçe |
|---|---|---|---|
| `hl_lower` (gün) | {3} | sabit | Chan: <1d noise; 3 gün crypto'da minimum trade-able |
| `hl_upper` (gün) | {14} | sabit | 14 gün = 2 hafta; capital cost makul |
| `hl_fit_window` (bar) | {60, 90} | 2 nokta | OU fit penceresi |
| `rsi_period` | {14} | sabit | Kaufman default |
| `rsi_divergence_lookback` (bar) | {15, 20, 25} | 3 nokta | Lookback'in genişliği |
| `sl_atr_offset` | {0.25} | sabit | Grimes Anti default |
| `tp_R` | {2.0} | sabit | Grimes Anti default |
| `atr_period` | {14} | sabit | standart |

**Toplam grid:** 2 × 3 = **6 config**. Optuna kullanmıyoruz — kasten kaba grid (Bonferroni ile düzeltilebilir küçük n).

## 6. Beklenen p-value

- **Per-test:** p_gross < 0.01 (50 seed shuffle).
- **Bonferroni düzeltilmiş (n=6):** p < 0.05/6 ≈ **0.0083**.
- **DSR threshold:** > 0.6.

Eğer best config p_gross ∈ [0.05, 0.0083] → "ilginç ama anlamsız" — red.

## 7. Multiple-Testing Correction (zorunlu)

- Grid 6 config; Bonferroni: p_required = 0.05 / 6 = 0.0083.
- Walk-forward dilim sayısı (3y train / 6m test, step 3m) ek trial sayar değil (aynı config, ayrı dilim).
- Eğer 6 config dışına çıkmak istersek (örn. lookback {10,15,20,25,30}) → yeni hipotez dosyası, eski dondurulur.

## 8. Robustness Suite (zorunlu — SOP-3)

1. **Walk-forward:** 3y train / 6m test, step 3m → ≥ 8 dilim; ≥ 5'i pozitif.
2. **IS/OOS:** Sharpe fark < %30.
3. **Param perturbasyon:** ±%10 her sweep parametresinde, 50 seed; ortalama Sharpe kaybı < %25.
4. **Symbol-out CV:** 15 sembolün her birini sırayla out → ortalama OOS Sharpe değişmemeli (>%30 swing → red).
5. **Regime split:** Bull/Bear/Range (BTC 200d EMA ile) → en az 2 rejimde pozitif.
6. **Stress dilimleri:** 2022-05 (LUNA), 2022-11 (FTX), 2023-03 (USDC depeg), 2024-08 (Yen carry) → bu dilimlerde yıkıcı (>%15 dilim DD) yok.
7. **Direction-shuffle baseline:** 50 seed (zaten H0a).
8. **Truncation audit:** OU fit + RSI + divergence detector'ları causality-safe (no `df.shift(-1)`, no `rolling(center=True)`).

## 9. Stop Criteria (araştırma terkedilir)

- **Erken çıkış 1:** H0a (gross edge sıfır) reddedilemezse — fee/lever optimizasyonu denenmez, kalıp yön bilgisi taşımıyor demektir. Lab'e gitmez, **araştırma kapanır**.
- **Erken çıkış 2:** n_trades < 120 (filtre çok agresif) — daha gevşek HL aralığı **yeni hipotez** olarak yazılır, bu kapanır.
- **Erken çıkış 3:** Per-year sign 6 yılın 3+'ünde negatif — regime-luck flag, red.
- **Erken çıkış 4:** Best config sweep sınırında (örn. lookback=15 veya =25 sınırda) → grid genişletilir; hâlâ sınırda ise overfit-evidence, red.

## 10. Curve-Fit Şüpheleri (öz-eleştiri — paranoid mod)

Bu hipotezin **gerçekten** curve-fit olma yollarını sırala:

1. **İki filtre + zaten-bilinen-zayıf sinyal stack edildi.** Kaufman'ın kendisi "filtresiz RSI divergence öldürür" diyor. Half-life filtresi bunu kurtarır mı yoksa sadece trade sayısını kırpıp survivorship illüzyonu mu üretir? **Test:** filtresiz ve filtreli mean_R_gross karşılaştırılır; filtre ekleyince trade-count düşüp mean_R artıyor ama p_gross AYNI kalıyorsa → filtre sadece daralttı, edge eklemedi.
2. **OU half-life fit'in kendisi past-looking, regime-bağlı.** 90 bar pencere, 90 gün sonra regime değişirse fit yanıltıcı. **Test:** walk-forward dilimlerde HL distribution stable mi? Drift varsa red.
3. **RSI divergence detector çoklu parametrik karar içerir** (lookback, low/high arama metrik, "konfirmasyon" eşiği). Her birini farklı sweep'lersek N hızla şişer. **Defansif önlem:** grid 6 config'le SINIRLI; genişletmek = yeni hipotez.
4. **Crypto 1D'de bizdeki edge dersi (smc-course-no-edge):** 4 farklı mekanizma denenmiş hepsi gross-direction null'u geçemedi. Kaufman + Chan kombinasyonu temelde aynı sınıfta (reversal-on-bar-OHLCV). **Prior bu hipotezin RED gelmesi.** Şaşırtıcı olan kabul olur — onu da o zaman Adversary'e doğrudan kill-probe için yollarız.
5. **Yıl başı Bitcoin halving + 2024 ATH gibi rejim olayları** divergence sinyalini lokal olarak doğrulayabilir, kalıbı taşımaz. Per-year sign consistency bunu yakalar.

## 11. İmplementasyon Notları (kod yazarken kontrol listesi)

- `scripts/research/` altında **causality-safe** vectorized detector (`scripts/research/rsi_divergence_halflife_backtest.py` taslak isim).
- OU fit `statsmodels.regression.linear_model.OLS` ile spread = α + β·spread.shift(1); half_life = −log(2)/log(β).
- Direction-shuffle: trade entry tarihleri sabit, yön rastgele (uniform ±1).
- Lookahead test: `t` mumunun close'unda karar; `t+1` mumunun open'ında giriş. Detector girdisi `df.iloc[:t+1]`.
- Sembol evreni: `data/universe.py::build_universe(date)` — delisting-aware (LUNA, FTT vs. dahil).

## 12. Reproducibility

- `git_hash`: doldurulacak (commit anında)
- `config_hash`: SHA256(this yaml)
- `data_hash`: SHA256(market.duckdb partitions used)
- Random seeds: shuffle 0..49

## 13. Karar Çerçevesi

Backtest + robustness suite sonrasında:
- **Terfi adayı:** §1'in 6 metriği + robustness §8'in tamamı ✓
- **İterate (SOP-4b):** mean_R_net pozitif ama max_dd > %25 ya da n_trades < 120 → risk/quality lever iterate
- **Red:** H0a ya da H0c reddedilemezse, ya da 3+ iterate sonrası gate'e taşınmadıysa
- **Belirsiz/ek-veri:** n_trades ∈ [80, 120] (border) → daha uzun lookback yeni hipotez

## 14. Lab teslim sonrası beklenen iş akışı

1. Backtest çalıştır (`scripts/research/rsi_divergence_halflife_backtest.py`).
2. Robustness raporu `reports/research/2026-06-05-kaufman-rsi-chan-halflife-1d.md`.
3. p_gross < 0.05 ise → adversary_engineer'a kill-probe için yolla.
4. Kill-probe geçerse → Lab tournament'a aday.
5. Lab gate'i geçerse → CEO ADR + Principal sign-off → deploy aday.

---

## Pre-registration imzaları

- Author: researcher (HYP yazımı)
- Review request: lab_scientist, risk_officer, adversary_engineer (24h SLA)
- Status: **DRAFT → PROPOSED on commit** (frontmatter güncellenecek)
- Bu hipotez kod yazımı, parametre sweep'i veya backtest run'ı YAPILMADAN ÖNCE commit'lenecek. Sonradan değiştirilirse `supersedes` ile yeni hipotez.
