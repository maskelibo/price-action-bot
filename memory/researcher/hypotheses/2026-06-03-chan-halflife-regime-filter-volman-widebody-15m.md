---
doc_id: researcher-20260603T100000-chan-halflife-regime-filter-volman-widebody-15m
doc_type: hypothesis
agent_id: researcher
created_at: 2026-06-03T10:00:00Z
status: DRAFT
confidence: low
depends_on: []
blocks: []
requested_review_from: [lab_scientist, risk_officer, adversary_engineer]
tags: [volman, wide_body, continuation, chan_halflife, regime_filter, hurst, ablation, high_curve_fit_risk]
supersedes: null
hash: null
---

# HYP-2026-06-03 — Chan Half-Life Regime Filter for Volman Wide-Body Continuation (15m USDT-perp)

## 0. Pre-registration kimliği
- ID: `chan-halflife-regime-filter-volman-widebody-15m`
- Versiyon: **0.1 — DRAFT** (parametre uzayı bu commit ile DONDURULUR)
- Author: researcher
- RAG seed: günlük tarama 2026-06-03 — Volman wide-range body + Chan half-life regime classification + Lopez DSR gate

## 1. İddia (ölçülebilir, tek cümle)
> **15m** timeframe'de, top-15 USDT-perp survivorship-clean evrende, son **3 yıl** (2023-06-03 → 2026-06-03), **Volman tipi wide-body bar** (body/range > 0.65, close > prior 20-bar high for long / close < prior 20-bar low for short) sinyali, **Chan tipi 60-bar OLS half-life regime filtresi** ile **τ > 30 bar** (long-half-life, trending rejim) olduğunda ALINIR, **τ ≤ 30 bar** olduğunda BLOKLANIR. ATR(14)×1.5 stop, fixed **1.5R** TP, 55 bps round-trip fee, 5 bps slip, %0.2 risk/trade ile:
>
> **(A) FİLTRELİ (τ>30) subset:**
> - Mean R per trade (gross) > 0.12R
> - Shuffle baseline p_gross < 0.05
> - Per-year sign consistency ≥ 4/6 yıl pozitif
> - Trade N ≥ 250
> - Sharpe (annualized 252×96 bar) > 0.6 OOS
>
> **(B) FİLTRESİZ baseline'a göre lift:**
> - Mean R(filtered) − Mean R(unfiltered) ≥ +0.05R (mutlak)
> - Sharpe lift ≥ +0.3 (mutlak)
>
> üretir. **(A) ve (B) birlikte sağlanmazsa hipotez REJECT** — yarım kabul yok.

## 2. Null hipotez (ne olursa çürür)
- **H0a:** Unfiltered wide-body continuation zaten mean_R ≤ 0 (önceki testlerle uyumlu: marubozu/mat-hold/engulfing-continuation HEPSİ shuffle p_gross<0.05 geçemedi) → half-life filtresi sıfır × herhangi = sıfır; ROI imkânsız.
- **H0b:** Filtreli subset shuffle baseline'ı yenmiyor (p_gross ≥ 0.20) → half-life regime ayrımı bilgi taşımıyor.
- **H0c:** Filtreli vs filtresiz mean_R farkı < 0.02R → filter etkisi gürültü içinde.
- **H0d:** Per-symbol leave-one-out'ta median Sharpe filtreli ≤ filtresiz → tek-sembol artefakt.
- **H0e:** IS/OOS Sharpe farkı > %50 → overfit (3y/6m split).
- **H0f:** Half-life τ eşiği grid sınırında (τ ∈ {10,20,30,40,60} dene; best=60 ise → uzay yetersiz, genişlet veya reject).

## 3. Gerekçe (RAG referansları)
- **[Volman 2014 — Understanding Price Action, ch.4 "double-pressure"]** (RAG #2): wide-range body bar that closes through a recent extreme = "double-pressure" — losing side trapped, fresh momentum. Body/range ≥ ~0.65 Volman'ın operasyonel eşiği. Bizim 15m crypto evreninde wide-body sıklığı yüksek (≈%8-12 bar) — istatistik için yeterli.
- **[Chan 2013 — Algorithmic Trading, ch.2 "Half-Life"]** (RAG #5): mean-reversion stratejilerinin Sharpe'ı half-life ≤ 30-60 bar olduğunda en yüksek; **trend-following stratejilerinin** edge'i tersi — uzun half-life (regime persistent, anti-mean-revert). Continuation pattern = trend-following → uzun τ regime'de daha iyi çalışmalı.
- **[Lopez DSR]** (RAG #9): grid 3 × 2 × 2 = 12 trial, DSR > 0.6 minimum (parametre azlığı sayesinde DSR penalty küçük olacak).
- **[Grimes — Transaction Cost]** (RAG #4): 55 bps round-trip + 5 bps slip konservatif; backtest bu seviyenin altında çıkmaz.
- **[Lopez — N-concurrent sizing]** (RAG #7): w_i = m_i / Σ|m_j| ileride iterate için not — bu hipotezde flat %0.2 risk, henüz kullanılmıyor.

## 4. Dependent variables (önceden taahhüt)
| Metric | Eşik (filtreli subset) | Yön | Notu |
|---|---|---|---|
| Mean R per trade (gross) | > 0.12R | büyük iyi | shuffle vs |
| Mean R per trade (net 55bps) | > 0.0R | büyük iyi | survival |
| Sharpe (OOS, annualized) | > 0.6 | büyük iyi | OOS only |
| **Sharpe LIFT (filtered − unfiltered)** | ≥ +0.3 | büyük iyi | KRİTİK |
| **Mean R LIFT (filtered − unfiltered)** | ≥ +0.05R | büyük iyi | KRİTİK |
| MaxDD on equity-base | < %25 | küçük iyi | |
| Profit factor | > 1.2 | büyük iyi | |
| Trade N (filtered) | ≥ 250 | büyük iyi | istatistik gücü |
| Per-year positive | ≥ 4/6 | sign-consistency | overfit detector |
| Shuffle p_gross | < 0.05 | küçük iyi | direction null |
| DSR (Lopez) | > 0.6 | büyük iyi | trial-adjusted |
| Per-symbol leave-one-out median Sharpe | > 0 | sign-stability | tek-sembol artefakt |

## 5. Independent variables (parametre uzayı — DONDURULDU)
| Param | Range | Adım | Cardinality |
|---|---|---|---|
| body/range threshold | {0.60, 0.65, 0.70} | — | 3 |
| breakout lookback (prior swing high/low) | {15, 20, 25} | — | 3 |
| half-life window (OLS lookback) | {60, 90} bar | — | 2 |
| half-life threshold τ* | {20, 30, 40} bar | — | 3 |
| ATR stop multiplier | {1.5} | sabit | 1 |
| TP (fixed R) | {1.5} | sabit | 1 |

**Toplam grid:** 3 × 3 × 2 × 3 = **54 kombinasyon**. ATR stop ve TP **bilinçli olarak sabit** — değişken parametre sayısını minimum tutuyorum (curve-fit yüzeyini küçültmek için).

**BH-FDR eşiği:** q = 0.05 / 54 ≈ 9.3e-4 (Bonferroni); BH-FDR step-up daha gevşek (raw p sıralaması). Beklenen p-ön-taahhüdü: en iyi filtreli config raw p_gross < 0.005.

## 6. Beklenen p-value
- Filtered shuffle baseline (gross, full grid): raw p < 0.01
- Bonferroni (n=54): p < 9.3e-4 → eğer geçemezse BH-FDR q<0.05 minimum
- Lift testi (filtered vs unfiltered): paired bootstrap p < 0.05 (10 000 resample)

## 7. Stop criteria (araştırmayı bırakma)
- **A.** Unfiltered baseline (kontrol) mean_R gross > 0.05R çıkarsa → "filter yararı" hipotezi anlamsız (zaten edge var, filtre fuzuli olur ya da ablation gösterir). Strateji yeniden çerçevelenmeli.
- **B.** Filtered subset trade N < 100 → setup çok nadir, istatistik yok → REJECT.
- **C.** Lift < 0.02R **ve** Sharpe lift < 0.1 → filter etkisi gürültü içinde → REJECT.
- **D.** Best τ* grid sınırında (20 veya 40 max) → uzay yetersiz, **1 kez** genişlet (10/15/20/30/40/50/60) → hâlâ sınırda → REJECT.
- **E.** Lookahead causality testi başarısız (`detector(df[:t+1])[t] != detector(df)[t]`) → reject + kod hatası incele.
- **F.** Per-symbol leave-one-out'ta tek sembol P&L'in > %35'ini taşıyor → tek-sembol artefakt → REJECT.
- **G.** Half-life hesabı `t` barında **`t` bar fiyatını** içerirse → micro-lookahead → reject + yeniden vektörize et.

## 8. İterate niyeti (SOP-4b — proaktif)
Eğer **ROI > 0 ama gate'i tam geçemedi** (örn lift sağlandı ama Sharpe < 0.6) → REDDETME, ITERATE:
- **v2:** Half-life yerine **Hurst exponent** (R/S analizi) regime classifier dene; H > 0.55 = trending → continuation lehine.
- **v3:** + **vol_z** filter (sadece üstü-medyan volatilite barları) — wide-body düşük-vol'da gürültü.
- **v4:** + **htf_1d_aligned** trend filtre (VSA'da işe yarayan tek filter — Volman wide-body için de uygulanabilir).
- **v5:** TP'yi 1.5R yerine **1R partial + 2R runner** (trail-from-TP1) → fee erozyonunu dengele.
- **v6:** Position sizing'i Lopez N-concurrent (w_i = m_i/Σ|m_j|) ile değiştir → portfolio-level karşılaştırma.

**Iterate budget:** Maks 5 versiyon. Sonra "edge gerçek değil, half-life regime filter continuation için yetersiz" olarak deferred-arşiv.

## 9. Curve-fit kırmızı bayrakları (SELF-FLAG — proaktif)
**Bu hipotezde overfit riski ORTA-YÜKSEKtir. Sebepler:**

1. **Continuation ailesi crypto 15m OHLCV'de TEKRAR TEKRAR REDDEDİLDİ** (`learning.md`: mat-hold, marubozu, engulfing-continuation, BOS-close, SMC trend-continuation hepsi shuffle p_gross<0.05 geçemedi). Filtrenin "no-edge × filter = edge" yaratması teorik olarak **imkânsız** — filter ancak edge varsa konsantre eder.
2. Bu nedenle hipotez aslında **iki şeyi aynı anda test ediyor**: (a) wide-body continuation gerçekten edge var mı (önceki testlere göre HAYIR), (b) half-life regime filter bu edge'i konsantre ediyor mu. (a) düşerse (b) test edilemez — clean negative beklenmeli.
3. **Half-life** hesabı 60-bar OLS — düşük örnekleme, gürültülü tahmin; eşik τ* küçük örneklem hatasıyla seçildiyse fragile.
4. **Lookahead riski:** half-life hesabında `t` barını dahil edersek micro-leak; `t-1` close ile bitirilmeli, kesinlikle test edilmeli.
5. **"Continuation" trend tanımı** — prior 20-bar high'ın üstüne kapanmak crypto'da yine *sıklıkla* (FOMO bar) ardından mean-reverse oluyor; "trend" tanımı yetersiz.
6. Grid 54 — küçük ama 0 değil; BH-FDR uygulanmalı.

**3+ bayrak yakalanırsa** + lift gate fail → REJECT (curve-fit).

## 10. Reproducibility çapaları
- Universe snapshot: `data/universe/2026-06-03_top15_usdtperp.parquet` (build_universe(date='2026-06-03'))
- Data hash: TBD (run-time)
- Code hash: TBD (commit-time)
- Config hash: TBD
- Random seed: 42 (shuffle + bootstrap)

## 11. Robustness suite checklist (SOP-3 — tamamı zorunlu)
- [ ] Walk-forward 3y/6m, step 3m → 8 dilim, ≥ 5/8 pozitif (filtered)
- [ ] Param perturb ±%10 (body_th, τ*): 50 seed, mean Sharpe loss < %25
- [ ] Symbol-out CV (15 fold): min OOS Sharpe filtered > 0
- [ ] Regime split (bull 2023-Q4, bear 2024-Q3, range 2025-Q2): ≥ 2/3 pozitif
- [ ] Stress periods: 2024-03 (ATH spike), 2024-08 (Yen carry), 2025-05 (USTC-benzeri olay varsa)
- [ ] Shuffle baseline p_gross < 0.05
- [ ] BH-FDR (n=54), q < 0.05
- [ ] Lookahead causality test (CRITICAL — half-life için)
- [ ] **Ablation:** (i) sadece wide-body, (ii) sadece half-life filter on random bars, (iii) tam stack — lift sırası net görülmeli
- [ ] Per-year sign consistency (6 yıl, ≥ 4 pozitif)

## 12. Karar matrisi (önceden tanımlı)
| Sonuç | Karar |
|---|---|
| (A) ve (B) gate'leri tam geçti + robustness ✓ | TERFI → Lab tournament |
| (A) geçti, (B) düşük lift | REJECT — filter etkisi yok, alternatif iterate (v2 Hurst) |
| (A) düşük ama lift > 0 | İTERATE (SOP-4b v3-v6) |
| Shuffle p_gross ≥ 0.20 | REJECT — yön bilgisi yok |
| Lookahead bulundu | REJECT — kod hatası |
| Trade N < 100 (filtered) | REJECT — setup nadir |
| 3+ kırmızı bayrak | REJECT — yapı sorunlu |

## 13. İmza
Pre-registered by: researcher (2026-06-03 10:00 UTC)
Hash freeze: bu doc commit edildikten sonra parametre uzayı kilitlenir; değişirse v0.2 + `supersedes`.

---

**NOT (kendime, brutal honest):** Continuation ailesinin crypto 15m'de 5 kez resmi olarak red olduğunu biliyorum. Bu hipotezin %80+ ihtimal REJECT olacağını şimdiden tahmin ediyorum. **Bunu yine de pre-register ediyorum çünkü:** (1) half-life regime classifier daha önce VSA dışı bir continuation pattern üstünde formal olarak test edilmedi — clean negative bile değerli kayıt; (2) eğer ablation lift gösterirse, **VSA-widestop için iterate v-half-life** olarak aktarılabilir (transfer learning); (3) negatif sonuç `learning.md`'ye "regime classifier continuation pattern'in negatif edge'ini POZITIFE çeviremedi" şeklinde sistemik ders olur.
