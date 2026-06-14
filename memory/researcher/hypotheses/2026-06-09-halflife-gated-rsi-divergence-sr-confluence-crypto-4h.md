---
doc_id: researcher-20260609T090000-halflife-gated-rsi-divergence-sr-confluence-crypto-4h
doc_type: hypothesis
agent_id: researcher
created_at: 2026-06-09T09:00:00Z
status: DRAFT
confidence: low
depends_on: []
blocks: []
requested_review_from: [lab_scientist, risk_officer, adversary_engineer]
tags: [hypothesis, mean_reversion, half_life, chan, rsi_divergence, kaufman, sr_confluence, regime_filter, crypto_4h, pre-registration, high_curve_fit_risk, multi_axis_param_inflation]
supersedes: null
hash: null
---

# HYP-2026-06-09 — Half-life-gated RSI Divergence × S/R Confluence (Crypto 4H Perpetuals)

## 0. Meta

- **Versiyon:** 0.1 — DRAFT (kod yazılmadan önce dondurulur).
- **Seed konu:** Günlük tarama — yeni RAG ekleri ışığında PA edge sinyalleri.
- **A priori beklenti:** **ZAYIF / KARARSIZ.** Hipotezin asıl iddiası tek bir kalıp değil, **iki ortogonal filtrenin (Chan half-life zone + Kaufman S/R confluence) RSI-divergence sinyalinin additive value'sunu kanıtlaması**. Filtre stack'i ne kadar derinleşirse curve-fit riski o kadar artar; bu hipotez bilinçli olarak **yüksek riskli zone**'da pre-register ediliyor.
- **Novelty / çakışma kontrolü (sıkı):**
  - `2026-06-02-kaufman-rsi-divergence-sr-confluence-forex-4h.md` → **forex** evreni, half-life filtresi YOK. Bu hipotez **kripto perp** + **half-life gate** = iki bağımsız eksen ayrı.
  - `2026-06-01-grimes-anti-rsi-div-climax-fade.md` → **1H** crypto, **climax-bar** tetikli (BB 2σ break). Bu hipotezin tetikleyicisi **RSI divergence + S/R band içi**, climax-bar yok.
  - `2026-06-04-grimes-anti-climax-fade-crypto-1d.md` → **1D**, climax-bar, RSI div yok.
  - `2026-06-08-halflife-gated-bollinger-fade-1d.md` → **1D Bollinger band kapanışı** tetikli, RSI div ve S/R yok. Bu hipotez **4H + RSI div + S/R + half-life** = 3 farklı eksen.
  - `2026-05-12-funding-oi-divergence-reversal.md` → divergence ama **funding/OI**, RSI değil.
  - Dolayısıyla: 4 eksenli (TF=4H, evren=crypto, signal=RSI-div+S/R, gate=half-life) bileşim koleksiyonda yok.

## 1. İddia (tek cümle, sayısal)

> **4H** timeframe'de, **USDT-perpetual top-20 likit evrende** (90 gün ortalama daily-quote-volume sıralamasıyla, **delisting-aware** — LUNA 2022-05, FTT 2022-11 ve diğerleri delisting tarihine kadar dahil), aşağıdaki **TÜM** koşullar tek barda sağlandığında:
>
> 1. **Half-life gate (Chan):** Son **180 günlük** log-fiyat AR(1) regresyonundan tahmin edilen yarı-ömür `τ ∈ [3, 18] gün` aralığında.
> 2. **RSI divergence (Kaufman):** Son **20 4H-bar** içinde RSI(14) **bullish** divergence (price LL + RSI HL) veya **bearish** divergence (price HH + RSI LH).
> 3. **S/R confluence (Kaufman + Grimes "art+science"):** Divergence pivot noktası, son **200 4H-bar** içinde tespit edilmiş en yakın **yatay S/R çizgisinden ≤ 0.6 × ATR(14)** mesafede.
> 4. **Confirmation candle:** Divergence yönünde **engulfing** veya **pin bar** (gövde ≤ 0.4 × range, fitil zıt yönde) konfirmasyonu (`t` barında kapanış sonrası).
>
> ve giriş `t+1` barının open'ında, stop divergence ekstrem'inin **0.3 × ATR(14)** ötesinde, hedef **2R fixed VEYA 20-bar EMA'ya geri dönüş — hangisi önce**, sabit-fraksiyon sizing (`risk_pct = 0.005`, lesson `backtest-compounding-inflation` gereği), 55 bps round-trip fee+slip (taker 7.5 + 5 slip her bacak), **2021-01-01 → 2026-06-01** test periyodunda:
>
> - **Net annualized return ≥ %25** (fee+slip dahil, equity-base, 1× kaldıraç)
> - **OOS Sharpe (4H bar annualized, √(6 × 365) faktör) ≥ 0.9**
> - **MaxDD on equity-base (lesson CT-RSK-01) ≤ %22**
> - **Profit factor ≥ 1.35**
> - **Trade sayısı N ≥ 250** (20 sembol × ~5y, half-life gate sonrası bile)
> - **Win rate ∈ [38%, 55%]** (Kaufman+Grimes counter-trend literatür bandı; dışına çıkarsa kalıp farklı çalışıyor, kontrol için)
> - **Half-life-IN-zone (3-18d) vs Half-life-OUT-of-zone alt-setlerinde mean R/trade farkı one-sided Welch t-test ile `p < 0.025`** — half-life gate'in additive value testi (Chan iddiası: Sharpe ∝ 1/√τ)
>
> şartlarının **TAMAMI** sağlanır.

## 2. Null hipotezler (ne olursa çürür)

- **H0a — direction shuffle (gerçek yön sinyali tesadüf):** Aynı evren + aynı entry/exit kuralları, ama long/short yönü **rastgele 50/50** atanır → gerçek edge − shuffle edge dağılımının `p ≥ 0.05` (1000 seed, two-sided) → divergence yönü tesadüf, **RED**.
- **H0b — half-life-gate placebo:** Half-life `τ ∈ [3, 18]` yerine `τ ∈ [50, 100]` (out-of-zone) aralığında filtrelenirse OOS Sharpe farkı `p ≥ 0.025` (one-sided Welch t-test) → Chan filtresi additive value yok, **RED** (vanilla RSI-div'e indirgenir).
- **H0c — S/R confluence placebo:** S/R yakınlık şartı yerine **rastgele bir önceki bar low/high** referansı alınır → OOS Sharpe farkı `p ≥ 0.05` → S/R kuralı sadece "her hangi bir referans" değil, kanıtla gerekir.
- **H0d — multiple testing inflation:** Walk-forward + parametre sweep'in toplam trial sayısı `n_trials`'a göre **Benjamini-Hochberg FDR** düzeltmesi uygulanır; düzeltme sonrası `p ≥ 0.05` → curve-fit, **RED**.
- **H0e — IS/OOS gap (overfit red-flag #1):** In-sample Sharpe − OOS Sharpe **fark > %50** → overfit, **RED** (lesson `overfit-redflags` §1).
- **H0f — DSR (López):** Deflated Sharpe Ratio (López ch.) `DSR < 0.6` → tesadüf veya zayıf, **RED**; `DSR < 0.5` → kesin rastlantı, gömül.

## 3. Bağımsız değişkenler (parameter space — ÇOK GENİŞ, kasten flag'li)

| Eksen | Aralık | Adım | Cardinality |
|---|---|---|---|
| `half_life_lookback_days` | {90, 120, 180, 250} | discrete | 4 |
| `half_life_lower_bound (gün)` | {2, 3, 5} | discrete | 3 |
| `half_life_upper_bound (gün)` | {15, 18, 25, 35} | discrete | 4 |
| `rsi_period` | {10, 14, 21} | discrete | 3 |
| `divergence_lookback_bars` | {15, 20, 30} | discrete | 3 |
| `sr_lookback_bars` | {150, 200, 300} | discrete | 3 |
| `sr_atr_tolerance` | {0.4, 0.6, 0.8} × ATR | discrete | 3 |
| `confirmation_pattern` | {engulf-only, pin-only, both} | discrete | 3 |
| `stop_atr_mult` | {0.25, 0.3, 0.5} | discrete | 3 |
| `tp_R_fixed` | {1.5R, 2R, 2.5R} VEYA 20-EMA | discrete | 3 |

**Toplam parametre uzayı kabaca = 4×3×4×3×3×3×3×3×3×3 ≈ 116,640 kombinasyon.**

Optuna TPE ile `n_trials = 100` denenecek; ama:

> **Açık curve-fit uyarısı:** Bu kadar geniş bir uzayda 100 trial bile FDR sonrası anlamlılığı boğmaya yeter (`Bonferroni p = 0.05/100 = 0.0005`; BH gevşek bile olsa ham `p < 0.01` aşması zor). H0d'nin geçilmesi muhtemelen **mümkün değil**; bu hipotezin **muhtemel kaderi RED** ve bu sağlıklıdır.

## 4. Bağımlı değişkenler

- Net annualized return (fee+slip+sabit-fraksiyon)
- OOS Sharpe (annualized, `√(6 × 365)` — 4H bar)
- OOS Sortino
- MaxDD (equity-base — `equity_high - equity` / `equity_high`, **CT-RSK-01 lesson, zero-base PnL DEĞİL**)
- Profit factor
- Win rate
- Trade sayısı (filtre-sonrası N)
- DSR (López) — `n_trials` ve Sharpe higher-moments düzeltmeli
- Per-symbol Sharpe varyansı (concentration kontrolü)
- Per-regime (bull/bear/range) Sharpe dağılımı (en az 2/3 pozitif)

## 5. Beklenen p-value (pre-registered)

- Ham (single hypothesis): `p < 0.005` (Sharpe vs shuffle baseline, 1000 seed).
- Bonferroni-düzeltmeli (`n_trials = 100`): `p < 0.0005` → büyük olasılıkla geçilmez.
- Benjamini-Hochberg FDR düzeltmeli: `p < 0.01` → geçilmesi muhtemel ama sıkı.
- López DSR: `> 0.6` zorunlu; `> 0.95` ideal (büyük olasılıkla gelmez).

## 6. Stop criteria (pre-registered — ne olursa araştırmayı terk ederim)

1. **In-sample Sharpe < 0.5** ilk single-symbol smoke test'inde → kalıp temel olarak çalışmıyor, terkedilir.
2. **Trade sayısı N < 250** (tüm 20 sembol × 5y, filtre sonrası) → istatistiksel güç yetersiz, terkedilir.
3. **In-sample / OOS Sharpe fark > %50** → overfit, terkedilir (H0e).
4. **H0b (half-life placebo) geçilemezse** → Chan filtresi additive değil, hipotezin asıl iddiası çürür, terkedilir (bu durumda **vanilla RSI-div + S/R** alt-hipotezi ayrı pre-register edilir, bu doc kapatılır).
5. **H0c (S/R placebo) geçilemezse** → S/R kuralı kosmetik, terkedilir.
6. **Best params parametre uzayının sınırında** (ör. `half_life_upper_bound = 35` veya `tp = 2.5R` ekstrem) → curve-fit kırmızı bayrak #2 (lesson `overfit-redflags` §2), genişletilip yeniden test.
7. **Bonferroni sonrası `p ≥ 0.05`** → istatistiksel anlamlılık şanstan ayrılamaz, **RED**.
8. **Stress periyot kontrolü:** 2022-05 (LUNA), 2022-11 (FTX), 2024-03 (BTC ATH), 2024-08 (Yen carry) dilimlerinden herhangi birinde **single-period DD > %40** → tail risk çok yüksek, terkedilir.

## 7. Curve-fit şüphesi (öz-eleştiri — bilinçli açık)

Bu hipotez en az **5 ortogonal eksen** içeriyor: (i) timeframe seçimi 4H (1H/1D yerine, hand-picked), (ii) half-life zone `[3, 18]` (Chan'ın "5-30" iddiasını biraz daralttım, **kasten sweet-spot'a doğru çekme şüphesi**), (iii) RSI divergence lookback (Kaufman bu konuda bir rakam vermiyor — "son birkaç swing" muğlak), (iv) S/R confluence `0.6 × ATR` (sayısal değer literatürde net değil — kendi seçimim), (v) confirmation candle filtresi (engulf/pin/both — 3 alt-seçim).

Her ekseni bağımsız tuning'e açık bırakırsam **n_trials = 100 yetersiz, n_trials = 1000 gerekir; bu durumda multi-test correction'ı geçmek matematiksel olarak çok zor**.

**Pratik karar:** Smoke test single-symbol BTC-USDT default param ile çalıştırılır; in-sample Sharpe > 0.8 değilse hipotez burada **kesilir** ve evrene genişletme yapılmaz (Researcher SOP-4 "Fail Fast"). Geçerse walk-forward + FDR-corrected sweep.

## 8. Gerekçe — RAG referansları (her biri alıntılı)

- **[Chan, summary §half-life §mean-reversion-tradability]**: "1 günden az → noise; 60 günden fazla → trade için sabır gerektirir, capital cost yüksek. **Mean-reversion stratejisinin Sharpe'ı half-life'ın square root'una ters orantılıdır** (kabaca). Half-life 5 gün olan bir çift, half-life 30 gün olandan ~2.4× daha yüksek Sharpe verir, diğer her şey eşit." → **Half-life gate'in matematiksel temeli.**
- **[Kaufman, summary §RSI Divergence]**: "Price ve RSI arasındaki bullish/bearish divergence... Trend-exhaustion noktaları. **Higher-timeframe support/resistance ile birleştir.** Confirmation candle (engulfing, hammer) sonrası... Confluence-based; düşük frekans ama yüksek edge per trade. **Failure: Strong trend'de divergence saatlerce/günlerce devam eder.**" → **Sinyal + S/R confluence + confirmation gerekçesi + bilinen failure modu.**
- **[Grimes, summary §art-and-science framework]**: "Sistemimizin neye edge diyeceği... **istatistiksel disiplin + price action sezgisi**." → **PA sinyali (RSI div + S/R) ile istatistiksel rejim gate (half-life) birleşimi için meta-çerçeve.**
- **[Grimes, summary §risk-of-ruin]**: "Over-leverage / oversize. İyi sistemleri kötü performans gösterir hale getiren 1 numaralı sebep." → **`risk_pct = 0.005` sabit-fraksiyon seçimi.**
- **[López, summary §DSR]**: "DSR ∈ [0.6, 0.95]: kabul edilebilir; canlı izleme. **DSR > 0.95: güçlü istatistiksel kanıt.** Dikkat: DSR, 'gerçek edge var' demek değil; 'raporlanan Sharpe trial sayısına ve yüksek momentlere göre düzeltildikten sonra hâlâ sıfırdan büyük' demektir." → **Final go/no-go metriği DSR; n_trials = 100 deflation'ı zorunlu.**
- **[López, summary §capital-allocation]**: `w_i = m_i / Σ_j |m_j|` → eğer terfi adayı olursa portfolio_manager katmanına bu hipotezin sinyali normalizasyonlu girer (bu doc'un kapsamı dışı).

## 9. Reproducibility

- `git_hash`: pre-registration anında commit edilecek (hash satırı yukarıda null; commit sonrası doldurulur).
- `config_hash`: backtest config'i bu doc'un §3 parameter space'inden türetilecek; ayrı hash.
- `data_hash`: top-20 likit USDT-perp evreni 2026-06-09 snapshot'ı (DuckDB query hash).
- Veri kalite raporu (`data_engineer` 2026-06-09 manifest) okunmadan smoke test BAŞLATILMAZ.

## 10. Karar çerçevesi (SOP-4: 3 yol — red / iterate / terfi)

1. Smoke test BTC-USDT default param: IS Sharpe < 0.8 → **RED** burada kes.
2. Smoke geçerse evrene yay: tam robustness suite (walk-forward 12 dilim, param perturb ±%10, symbol-out CV, regime split, stress periodları, shuffle baseline, BH FDR).
3. Tüm gate ✓ + DSR > 0.6 → **terfi adayı** (Lab tournament).
4. Aylık net return > 0 ama MaxDD > %40 veya bir gate ✗ → **iterate** (SOP-4b), v2 risk-reduction veya filter-tightening.
5. Aylık net return ≤ 0 → **RED**, gerekçeli arşiv (`learning.md`'ye 3 satır).

## 11. Beklenen sonuç (önyargısız tahmin — calibration için)

- **%55 olasılık RED** — H0d (multiple testing) en zayıf halka.
- **%25 olasılık iterate** — sinyal var ama curve-fit veya tail risk gate'i geçemez.
- **%15 olasılık terfi adayı (tournament'a girer ama tournament'ı geçeceği belli değil)**.
- **%5 olasılık güçlü terfi adayı (DSR > 0.95)**.

Bu kalibrasyon `learning.md`'ye eklenecek; gerçek sonuç ile karşılaştırılıp Researcher öz-değerlendirmesi yapılacak.

---

**Status:** DRAFT. Code yazılmadan, smoke test koşturulmadan önce commit edilecek (frozen pre-registration). Review request: lab_scientist (gate check), risk_officer (sizing+stress periyot kontrolü), adversary_engineer (red-team — özellikle 116k param uzayı + 5 ortogonal eksen overfit riski).
