---
doc_id: researcher-20260610T193000-tsmom-sign-lookback-1d-low-corr-to-vsa
doc_type: hypothesis
agent_id: researcher
created_at: 2026-06-10T19:30:00Z
status: PROPOSED
confidence: low
depends_on: []
blocks: []
requested_review_from: [lab_scientist, risk_officer]
tags: [hypothesis, tsmom, low_corr_to_vsa, cross_strategy_edge, academic_baseline, pre_registration]
supersedes: null
hash: null
---

# Hypothesis: tsmom-sign-lookback-1d-low-corr-to-vsa

- **Versiyon**: 0.1 (pre-registration, kod yok)
- **Hipotez ailesi**: cross-strategy companion for active vsa_climax_test
- **Tetik**: Seed konu "Cross-strategy edge keşfi: aktif vsa_climax_test ile düşük korelasyonlu ek bir strateji."
- **Önceki seed_abort kuyruğu**: cross-strategy-companion v14..v16 ardışık abort. Bu hipotez yeni paradigma (akademik time-series momentum, RAG'de dolaysız aday değil).

## 1. İddia (Pre-Registered, Falsifiable)

> 1D timeframe'de USDT-perpetual evreninde, **TSMOM (Time-Series Momentum, Moskowitz/Ooi/Pedersen 2012) sign filter** ile:
> - Long if `sign(close[t] / close[t-L] - 1) > 0` AND `realized_vol_12d(t) > vol_floor`
> - Short if sign < 0 AND aynı vol gate
> - L (lookback) ∈ {28, 63, 91} (sabit grid, 3 ayrı çalıştırma)
> - Bar `t` kapanışta sinyal, bar `t+1` open'da giriş (lookahead-safe)
> - Position sizing: 1% equity/trade, ATR(14)-based 2×ATR initial SL, 3×ATR trailing
> - Holding: trailing stop ya da sign flip → exit
> - Universe: rolling top-30 24h-volume USDT-perp (delisting-inclusive)
> - Window: 2022-01-01 → 2025-12-31 (4 yıl, IS=3y/OOS=1y)
> - Fees: 7.5 bps taker, slippage 5 bps
>
> aşağıdaki metrikleri eşzamanlı üretir:
> 1. **OOS Annualized Net Return ≥ %25**
> 2. **OOS Sharpe ≥ 0.9**
> 3. **OOS MaxDD ≤ %35**
> 4. **OOS Profit Factor ≥ 1.4**
> 5. **30-günlük günlük getiri korelasyonu vs vsa_climax_test < 0.25** (canlı + backtest karışık 30g penceresinde)

**Vurgu**: Bu **akademik baseline** hipotezi — "kripto'da TSMOM hâlâ çalışıyor mu?" sorusunun answer'ı. Beklenti **modest** (Sharpe ~1.0), curve-fit korunması için hiçbir param optimization YAPILMAYACAK; sadece 3 sabit L grid'i çalıştırılır, üçü de bağımsız raporlanır (Bonferroni m=3).

## 2. Gerekçe (RAG + Literatür)

- **[Moskowitz, Ooi, Pedersen 2012]** — "Time Series Momentum", JFE. 58 futures market'inde 12-month TSMOM'un robust pozitif edge'i (Sharpe ~1.2 cross-asset). Bizim hipotezimiz bu sonucu kripto'da test eder; **negative result** da değerli (null'u kanıtlamak).
- **[RAG #9, Chan summary]** — "Regime-conditional ensemble. HMM rejim çıktısına göre Bollinger reversal vs TSMOM ağırlıklarının dinamik allocation'ı; portföy seviyesinde regime-aware meta-strategy oluşturulur." → TSMOM, mean-reverting climax stratejisi ile portföy seviyesinde COMPLEMENTARY rol için referans.
- **[RAG #4, Kaufman]** — Golden cross 50/200 zaten 2026-06-09'da denenmiş; TSMOM, **return-sign** based (price-vs-MA değil) farklı sinyal yapısı. Yine de mekanik akrabası — eğer Golden Cross 1D crypto'da fail ettiyse TSMOM'un da fail etme prior'u yüksek (önceden uyarı).
- **[RAG #7, Kaufman]** — Donchian 20-bar zaten denenmiş. TSMOM lookback-based, channel-based değil → farklı kalıp ama aynı momentum ailesi.
- **[RAG #1, Lopez de Prado]** — Hipoteze uygulanacak gating kriterleri: DSR < 0.5, PBO > 0.5, T < MinBTL, IS Sharpe > 3·OOS Sharpe, free_params/n_obs > 1/30. Bu hipotezde free_params = 0 (sabit grid), curve-fit savunması güçlü.

## 3. Null Hipotez (Ne Olursa Çürür)

H0: "Kripto 1D'de TSMOM sign filter, transaction cost (fee+slippage) sonrası **net negatif** veya **shuffle baseline'dan istatistiksel olarak ayırt edilemez**."

H0 reddedilmesi için her 3 L değerinde de:
- Net OOS Sharpe > 0
- Shuffle baseline'a karşı p < 0.05 (Bonferroni sonrası p < 0.017)

## 4. Dependent Variables (Pre-Registered)

| Metric | Hedef | Kabul Eşiği |
|---|---|---|
| OOS Annualized Net Return | > %25 | gate |
| OOS Sharpe | > 0.9 | gate |
| OOS MaxDD | < %35 | gate |
| OOS Profit Factor | > 1.4 | gate |
| Win Rate | n/a | info only (TSMOM'da %35-45 beklenir; asimetri R-multiple'da) |
| 30g vs vsa_climax_test korelasyonu | < 0.25 | gate (cross-strategy ortogonalite) |
| Shuffle baseline p-value | < 0.05 (Bonferroni m=3 → < 0.017) | gate |
| IS/OOS Sharpe oranı | < 1.7 | gate (overfit alarmı) |
| Walk-forward dilim pozitif oranı | ≥ 8/12 | gate |

## 5. Independent Variables (Sabitlenmiş — Curve-Fit Defense)

- **Lookback L**: {28, 63, 91} — **3 değer, sabit, tuning yok**. Her L bağımsız çalıştırılır, Bonferroni m=3.
- **Vol gate floor**: realized_vol_12d > 0.02 (sabit, kripto'da düşük-vol çürük rejimini eler).
- **Position size**: 1% equity (sabit).
- **SL / Trail**: 2×ATR initial, 3×ATR trail (sabit, Kaufman Turtle benzeri).
- **Universe**: rolling top-30 24h-volume (deterministik, lookahead-safe rolling rank).
- **Rebalance**: Daily bar close → next bar open.

Hiçbir parametre Optuna'ya verilmez. Tek "tuning serbestliği" L grid'idir ve bu literatür-justified (12-month ≈ 252-bar ama crypto vol için 28/63/91 daha uygun).

## 6. Beklenen P-Value

- Shuffle baseline'a karşı (her L için): p < 0.05 hedef.
- Bonferroni m=3 düzeltmesi sonrası: p < 0.017 hedef.
- 3 L'den **en az 2'sinin** düzeltilmiş p < 0.017 olması istenir; aksi halde H0 reddedilemez.

## 7. Stop Criteria (Kod Yazmadan Önce Donduruldu)

Aşağıdakilerden HERHANGİ BİRİ tetiklenirse araştırma TERK EDİLİR, terfi adayı yazılmaz:
1. IS Sharpe < 0.5 (3 L'nin hiçbirinde) → edge yok, çıkış.
2. IS Sharpe > 3 (1+ L'de) → overfit alarm, robustness suite'i bile çalıştırma.
3. IS/OOS Sharpe oranı > 2.5 (1+ L'de) → curve-fit, red.
4. Trade count < 100 (4 yıl × 30 sembol'de) → istatistik anlamsız, red.
5. Toplam P&L'in >%60'ı tek 30-gün dilimine ait → tek-olay edge, red.
6. Walk-forward 12-dilimden 5+'i negatif → drift, red.
7. **vsa_climax_test ile 30g korelasyon ≥ 0.40** → ortogonalite hedefi başarısız, başka aday aranır.
8. 3 L'nin hiçbirinde shuffle baseline'ı Bonferroni-correct p < 0.017'de yenmedi → null reddedilemedi.

## 8. Curve-Fit Şüphesi (Önceden İlan)

> **Bu hipotez akademik literatür-justified ama crypto'da test sonucu BİLİNMİYOR.** Curve-fit'e direnç tasarım gereği:
> - Hiçbir Optuna optimization yok.
> - 3 lookback değeri sabit, post-hoc seçim yapılamaz.
> - SL/trail/sizing parametreleri sabit (Kaufman varsayılanı).
> - Universe rolling (look-forward-free).
>
> **Yine de** kırmızı bayraklar:
> 1. **Kripto'da TSMOM 1D testleri zayıf**: önceki çalışmalar (Bianchi 2020, Liu 2023) BTC'de 12-month TSMOM Sharpe ~0.4-0.6 raporlamış — bizim 0.9 eşiğimiz iyimser.
> 2. **vs vsa_climax_test korelasyonu beklenenden yüksek olabilir**: extreme vol günlerinde her ikisi de aynı yönde tetikleyebilir (TSMOM sign-flip günleri = VSA climax günleri ile çakışır). Test edilmeden bilinmiyor.
> 3. **Univers tilt riski**: top-30 vol rotasyonu, recently-pumped coinleri ekler → mom factor'ı yapay olarak güçlendirebilir. Symbol-out CV bunu yakalamalı.
> 4. **Stress periodlarında risk**: LUNA 2022-05, FTX 2022-11 günlerinde sign-flip whipsaw kümülatif %15-25 DD tek olayda olabilir.
>
> Eğer test pozitif çıkarsa **şüpheyi artırın** — bu strateji tarihte iyi tanımlanmış, kripto'da edge olsa çoktan arbitrajlanmış olması beklenir. Aşırı iyi sonuç = veri/kod hatası prior'u %50.

## 9. Pre-Test Reproducibility

- git_hash: <ölçüm sırasında doldurulur>
- config_hash: <backtest config dondurulur, hash hesaplanır>
- data_hash: <DuckDB snapshot tarihi + sembol listesi hash'i>
- random_seed: 42 (deterministik shuffle baseline için)
- universe_rank_method: rolling 30d mean USDT-volume, t-1 cutoff

## 10. Robustness Suite (SOP-3 — Çalıştırılacak Adımlar)

Sadece IS Sharpe gate (#7 madde 1-3) geçerse aşağıdakiler zorunlu:
1. **Walk-forward**: 3y train + 6m test, step 3m → 12 dilim (3 L için 36 total).
2. **IS/OOS fark**: < 30% Sharpe düşüş (her L için).
3. **Param perturbation**: SL/trail parametrelerine ±%10 perturbation, 50 seed → ort Sharpe kaybı < %25.
4. **Symbol-out CV**: her sembolü tek tek dışarıda bırak → ort OOS Sharpe değişmemeli (±0.2).
5. **Regime split**: bull(2023-Q4..2024-Q1, 2025-Q1+) / bear(2022-H1, 2024-Q3) / range(2023-H1) — en az 2'sinde pozitif.
6. **Stress periodları**: 2022-05 LUNA, 2022-11 FTX, 2023-03 USDC, 2024-08 Yen-carry → her dilimde DD < %15.
7. **Shuffle baseline**: returns'leri shuffle, null model → p < 0.017 (Bonferroni m=3).
8. **Multiple testing correction**: 3 L × 12 walk-forward = 36 test → Benjamini-Hochberg FDR < 0.05.

## 11. Lookahead Test (Zorunlu, Kod Yazılınca İlk Adım)

- `tsmom_signal(df.iloc[:t+1])[t] == tsmom_signal(df)[t]` her t için (causality).
- Bar t kapanışta sinyal, bar t+1 open'da giriş (timing).
- Universe ranking t-1 cutoff (no look-forward).
- Realized vol calculation: `df['close'].pct_change().rolling(12).std()` — pandas `rolling` lookahead-safe (window'da future yok), ama `min_periods` set edilmeli.

## 12. Karar Çerçevesi (Önceden Bağlanmış)

- **Terfi adayı** (Lab tournament'a): tüm 9 gate ✓ + tüm robustness suite ✓.
- **Iterate**: net OOS return > 0 ama MaxDD veya korelasyon gate'i geçemedi → SOP-4b path (risk_pct düşür, regime gate ekle, vs.). Max 5 iterate.
- **Red (gerçek edge yok)**: H0 reddedilemedi (shuffle p ≥ 0.017) → arşivle, learning'e 3 satır.
- **Red (lookahead/data leak)**: causality test fail → blocker, sebep loglanır.

## 13. Sonraki Adım

1. Bu doc PROPOSED → lab_scientist + risk_officer review (24h SLA).
2. Endorse alınırsa backtest config türetilir, hash dondurulur.
3. Çalıştırma sırası: lookahead test → IS backtest (3 L) → gate kontrol → robustness suite → karar.

## 14. Mottos uygulanan

- "Strong opinions, loosely held" — TSMOM kripto'da çalışmaz prior'u güçlü; test çürütürse hemen bırak.
- "Distrust your own backtest" — pre-registered, Bonferroni-correct, sabit grid.
- "Read first, code second" — Moskowitz 2012 + Chan + Kaufman + Bianchi/Liu kripto sonuçları okundu.
- "Reject more than you accept" — null prior'u baskın, kabul eşikleri sıkı.

---

**Not (önceden kayıt için)**: Bu hipotez `cross-strategy-companion seed_abort v14..v16` ardından **yeni paradigma denemesi**. Daha önceki abort'lar continuation/SR-based familyada idi; TSMOM **akademik time-series factor** familyasından ilk deneme. Eğer bu da seed_abort olursa cross-strategy companion arayışı **paradigma değiştirmeli** (örn. cross-sectional momentum, halving-cycle phase, funding-rate dispersion).
