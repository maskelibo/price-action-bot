---
doc_id: researcher-20260607T100000-marubozu-continuation-low-corr-to-vsa
doc_type: hypothesis
agent_id: researcher
created_at: 2026-06-07T10:00:00Z
status: PROPOSED
confidence: low
depends_on: []
blocks: []
requested_review_from: [lab_scientist, risk_officer, adversary_engineer]
tags: [cross_strategy_edge, low_correlation_companion, marubozu, momentum_continuation, candlestick_statistics, pre_registration]
supersedes: null
hash: null
---

# Hipotez: HYP-2026-06-07-MARUBOZU-CONT-LOW-CORR-TO-VSA

- **Tarih:** 2026-06-07
- **Versiyon:** 0.1 (pre-registration; kod yazılmadan donduruluyor)
- **Seed bağlam:** Cross-strategy edge keşfi — aktif `vsa_climax_test` (volume klimaks reversal, 15m) ile **düşük korelasyonlu** ek bir aday. Raftaki 66 stratejiden 4'ü (mat-hold, donchian, ATR-thrust, iii) zaten cross-edge testlerine girip seed_abort_v2/v3 ile reddedildi → tekrar test edilmiyor. Marubozu henüz "low-corr-to-vsa" rafında test edilmedi.

## 1. İddia (ölçülebilir, sayısal)

> **H1:** 2023-06-01 → 2026-06-01 dönemi, 30 sembollik USDT-perpetual likit evren (survivorship-corrected), **15m timeframe**'de, aşağıdaki *net mekanik* tanımlı **bearish Marubozu continuation** sinyali — açılış pozisyonu `t+1` bar açılışında, SL = giriş × (1 + 1.5 × ATR14_pct), TP = 2R fixed, fee 7.5 bps taker + 5 bps slippage — şu metrikleri üretir:
>
> - **OOS annualized net return (compounding-corrected, sabit-fraksiyon %0.5/trade):** > **%12**
> - **OOS Sharpe (252×96 bar/yıl annualization, eşik %0 günlük getiri):** > **0.8**
> - **MaxDD (account equity bazlı, zero-base değil):** < **%18**
> - **Profit factor:** > **1.25**
> - **Average trade R:** > **0.12R**
> - **Walk-forward (12 dilim, 24m train / 3m test, step 3m) pozitif Sharpe oranı:** ≥ **8/12**
> - **`vsa_climax_test` aktif strateji ile 30-günlük rolling Pearson korelasyonu (per-bar PnL):** **|ρ| < 0.25** (cross-edge eşiği)

**Mekanik tanım (vectorized, lookahead-free):**
- `body_pct = abs(close - open) / (high - low)`
- `is_bearish_marubozu = (close < open) AND (body_pct ≥ 0.85)`  ← Bulkowski'nin %90 tanımının 0.05 gevşemesi (kripto'da tam top wick = 0 çok nadir)
- **Trend gate:** son 20 barlık close'ların SMA20 eğimi < 0 (mevcut bar dahil değil, t-1'e kadar)
- **Hacim teyidi:** marubozu barının volume'ü son 20 barın 75. yüzdebirliğinin üzerinde
- **HTF veto:** 1H EMA50 < EMA200 (downtrend filter; kripto'da counter-trend short LUNA-tipi tetiklenmesin diye değil — bu sefer pure with-trend continuation)

**Giriş:** `t+1` bar açılışında market.
**SL:** giriş × (1 + 1.5 × ATR14_pct_at_t).
**TP:** 2R fixed (asimetri trail değil — curve-fit yüzeyini küçük tutmak için).
**Time-stop:** 24 bar (6 saat) içinde TP/SL tetiklenmezse close.

## 2. Null Hipotez (H0)

> Sinyalin shuffle-baseline'a (random entry, aynı SL/TP/holding period, aynı evren) karşı OOS Sharpe farkı 0; p-value > 0.05.

**H1 çürür eğer:**
- OOS Sharpe < 0.5 (in-sample bile zayıfsa konu kapalı)
- IS / OOS Sharpe oranı > 2× (overfit kırmızı bayrağı)
- Bonferroni-corrected p (n=trial sayısı) > 0.05
- Walk-forward'da 6/12'den az dilim pozitif
- `vsa_climax_test` ile |ρ| ≥ 0.4 (korelasyon yüksek → cross-edge tezi düşer; kabul edilmez)

## 3. Gerekçe (RAG referansları)

- **[Bulkowski — Encyclopedia of Candlestick Charts, Marubozu sec.]** (RAG #8): bearish marubozu continuation rate %64, average move %4.9, performance rank **22 / 103**. Top quartile mum kalıbı. Body/range ≥ 0.90 mekanik kural; vectorize edilebilir.
- **[López de Prado — Advances in Financial ML, ch. on Backtest Overfitting]** (RAG #1): DSR < 0.5, PBO > 0.5, IS Sharpe > 3·OOS Sharpe, params/sample > 1/30, walk-forward Sharpe varyansı > ortalama — bu altı kriterden **biri kırmızıysa deploy edilmez**. Pre-registration bu sebeple zorunlu.
- **[Brooks — Trading Price Action: Trends]** (RAG #3, dolaylı): büyük momentum mumu (trend bar) trend yönünde devam olasılığı yüksek; geri dönüş bar'ı (reversal) genellikle aksini gerektirir. Marubozu = saf trend bar.
- **Cross-strategy korelasyon teorik tabanı:** vsa_climax_test mekaniği `volume_z > threshold + reversal bar` → counter-trend exhaustion sinyali. Marubozu mekaniği = with-trend momentum continuation. Sinyal yönü, tetik mekanizması, hold direction ortogonal → korelasyonun *düşük* olması beklenir. Ama beklenti ≠ veri; ölçeceğiz.

## 4. Dependent Variables (önceden sabitlenmiş, p-hacking yok)

| Variable | Hedef | Annualization | Bazı |
|---|---|---|---|
| Annualized net return | > %12 | (1+r_15m)^(252×96)-1 | sabit-fraksiyon |
| Sharpe | > 0.8 | sqrt(252×96)×μ_15m/σ_15m | log-returns |
| MaxDD | < %18 | account equity peak-to-trough | NOT zero-base |
| Profit factor | > 1.25 | Σ kazanç / Σ kayıp | net (fee+slip dahil) |
| Avg trade R | > 0.12 | mean(realized_R) | per-trade |
| Walk-forward pozitif dilim | ≥ 8/12 | binary count | OOS sharpe>0 |
| Bonferroni-corrected p | < 0.05 | shuffle baseline ×N trial | strict |
| vsa_climax PnL korelasyonu | < 0.25 abs | 30-day rolling Pearson | per-bar |

**KORUMA:** Bu metriklerden herhangi biri ihlal edilirse hipotez red — sonradan "ama X iyi" denmez (post-hoc gerekçe yasak).

## 5. Independent Variables (parametre uzayı, pre-declared)

| Parametre | Aralık | Adım | Toplam combo |
|---|---|---|---|
| body_pct eşiği | {0.80, 0.85, 0.90} | discrete | 3 |
| volume yüzdebirlik | {70, 75, 80, 85} | discrete | 4 |
| ATR multiplier (SL) | {1.25, 1.5, 1.75} | discrete | 3 |
| TP R-multiple | {1.5, 2.0, 2.5} | discrete | 3 |
| HTF EMA short/long | {(20,50), (50,200)} | discrete | 2 |
| Time-stop bar | {16, 24, 32} | discrete | 3 |

**Total trial = 3·4·3·3·2·3 = 648 → Bonferroni'da brutal (0.05/648 ≈ 7.7e-5).** Bu zaten curve-fit riskine açık iz bırakıyor — bu yüzden BH-FDR (Benjamini-Hochberg, q=0.10) tercih edilecek, ama yine de raporlanacak.

**Curve-fit kontrol noktaları (pre-declared):**
- Eğer best params **uçlarda** çıkarsa (body 0.80 veya 0.90, vol 70 veya 85) → uzayı dışa genişlet, sinyal henüz olgunlaşmamış.
- Eğer param perturbation (her parametre ±%20, 50 seed) Sharpe'ın **%40+** kaybına yol açarsa → overfit kırmızı bayrak, red.

## 6. Beklenen p-value

- Shuffle baseline'a karşı **raw p < 0.01** (kabul için ön şart).
- BH-FDR q=0.10 sonrası adjusted q < 0.05.
- Bonferroni gözlem amaçlı raporlanacak ama nihai gate BH-FDR.

## 7. Stop Criteria (research'ün terkedileceği koşullar)

1. **In-sample Sharpe < 0.5** → hipotez derhal terk, walk-forward'a gitme.
2. **IS/OOS Sharpe oranı > 3×** → overfit (López de Prado kriterlerinden #4), red.
3. **vsa_climax PnL ile |ρ| ≥ 0.4** → cross-edge tezi düşer; tek başına edge olsa bile bu seed bağlamında reddedilir.
4. **Walk-forward'ın 12 diliminden 5+ negatif** → tutarsız edge, red.
5. **Param uzayı uçlarında best** → ya uzayı genişlet, ya red (10gün limit).
6. **Stress periyotlarından (LUNA 2022-05, FTX 2022-11, BTC ATH 2024-03, Yen Carry 2024-08) herhangi birinde -%15+ DD** → tail-risk açık, red.
7. **Total trade < 200 (OOS)** → istatistik anlamsız, red.

## 8. Curve-Fit Şüphe Beyanı (zorunlu, paranoid)

- Bulkowski stats US equity 1980-2010 verisinden — kripto perp 15m'de **aynen geçerli değil**, sadece prior. Posterior backtest gerekli.
- 648 trial Bonferroni'da false-positive olasılığı yüksek — BH-FDR + shuffle baseline + param perturbation + walk-forward consistency tüm hepsi geçilmeli.
- "Bearish marubozu continuation" anlatısı (downtrend + momentum mumu + with-trend devam) **çok temiz hikâye**. Hikâye temizliği bias yaratır — kararı yalnızca **sayı** verecek.
- vsa_climax_test ile düşük korelasyon **mekanik öngörü**, **ampirik test** değil. Korelasyon ölçülmeden bu hipotez kabul edilmeyecek (ön şart §1).
- Kripto bar veri kalitesi her sembol için aynı değil — symbol-out CV zorunlu.

## 9. Reproducibility

- **git_hash:** (backtest çalıştırılırken doldurulacak)
- **config_hash:** marubozu_cont_v0.1
- **data_hash:** OHLCV evren snapshot 2026-06-01 (DuckDB)

## 10. Sonraki adım

`backtest/engine.py` üzerinde vectorized detector implementasyonu **kod yazılmadan önce** bu doc commit edilir (pre-registration mühürü). Sonra:
1. Lookahead causality testi (`detector(df.iloc[:t+1])[t] == detector(df)[t]`).
2. In-sample + OOS + 12-dilim walk-forward.
3. Param perturbation (50 seed).
4. Symbol-out CV.
5. Regime split (bull/bear/range).
6. Stress periyot replay.
7. Shuffle baseline + BH-FDR.
8. **vsa_climax_test ile rolling 30-day korelasyon** (cross-edge ön şartı).

## 11. Karar matrisi (önceden sabit)

| Sonuç | Kararı |
|---|---|
| Tüm 6 metrik ✓ + korelasyon ✓ + robustness ✓ | Lab tournament adayı |
| Aylık ROI > 0 ama DD veya korelasyon ihlal | **İterate** (SOP-4b) — v2 risk-azaltma veya v2 trade-quality filtresi |
| Aylık ROI ≤ 0 veya overfit kırmızı bayrak | Red — gerekçeli arşiv |
| Korelasyon yüksek (|ρ| ≥ 0.4) ama tek başına ✓ | Red **bu seed bağlamında** (başka bir hypothesis dosyası açılabilir — kategori farklı) |

---

**Pre-registration kapağı:** Bu hipotez kod yazılmadan donduruldu. Sonradan eklenen herhangi bir parametre, eşik gevşemesi, post-hoc rasyonelleştirme → **otomatik red**.
