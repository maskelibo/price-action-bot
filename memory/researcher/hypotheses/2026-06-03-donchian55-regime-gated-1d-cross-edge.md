---
doc_id: researcher-20260603T093000-donchian55-regime-gated-1d-cross-edge
doc_type: hypothesis
agent_id: researcher
created_at: 2026-06-03T09:30:00Z
status: DRAFT
confidence: low
depends_on:
  - researcher-20260602T120000-htf-continuation-diversifier
  - researcher-20260602T130000-smc-trend-continuation-final-smc-test
  - learning-2026-06-02-htf-continuation-falsified
blocks: []
requested_review_from: [lab_scientist, risk_officer]
tags: [hypothesis, cross-strategy, diversifier, donchian, turtle-system2, regime-conditional, curve-fit-risk-high]
supersedes: null
---

# HYP-2026-06-03: Donchian-55 Regime-Conditional Breakout (1D) — Cross-Edge to vsa_climax_test

## Önemli Önsöz (Curve-Fit Şüphesi — Önceden İlan)

Bu hipotez aşağıdaki nedenlerle **curve-fit'e yüksek meyilli**:

1. **Önceki htf-continuation testinde 1D Donchian/EMA200-pull gross-null'u yendi (p_gross<0.05) AMA net edge 0'dan ayırt edilemedi (bootstrap day-Sharpe CI 0'ı içeriyor).** Şimdi "rejim gate ekleyince düzelecek" iddiası klasik post-hoc-narrative — **iki ek serbest parametre** (ADX_eşik, BTC.D_state) ekleniyor. Lopez de Prado §1 kuralı (`serbest_param / örnek > 1/30`) tetiklenme riski yüksek.
2. **Filtre eklemek "edge'i konsantre etti gibi gelmek" tuzağı**: SMC/SFP iter-2'de (2026-06-02) "high-conviction" selectivity gross edge'i NEGATİF yapmıştı. Aynı tuzak burada da kurulabilir.
3. **Lookback (55) sweep'lenebilir**: 20 vs 55 vs 100 tek bir IS pencere üzerinde best seçilmemeli; tüm sweep'in walk-forward sonucu raporlanmalı.
4. **BTC.D state binary dichotomy** — kolay overfit. Trend-up tanımı (örn 30D-slope>0) tek seçimle sayılır; alternatif tanımlar (50D-slope, BB-position, vs.) **dahil edilmeli ve worst-case rapor edilmeli**.

Bu önsözü dondurulmuş (pre-registered) bırakıyorum ki red kararını veride değil önyargıda aramayalım.

---

## 1. İddia (Pre-Registered, Tek Cümle)

> **1D timeframe'de, 7 majör USDT-perpetual (BTC, ETH, BNB, SOL, XRP, ADA, DOGE)** evreninde, 2021-01-01 → 2026-04-30 (5y3m), `close > Donchian_high(55)` kırılımı **AND** `ADX_14_1D > 25` **AND** `BTC.D_30d_slope < 0` (BTC dominance düşüş rejimi = alt majors lehine sermaye akışı proxy'si) koşullarında entry, `1.5 × ATR_14_1D` SL, `3R` TP, 55bps round-trip fee + 5bps slip dahil olarak:
> - **NET mean_R ≥ +0.15** (per trade)
> - **Shuffle (direction-randomized) null'u p_gross < 0.05 ile yener** (gross-edge gate, fee-bağımsız)
> - **Daily P&L Sharpe BCa-bootstrap %95 CI alt sınırı > 0**
> - **ρ(daily-returns, vsa_climax_test daily-returns) ≤ 0.15** (cross-edge gate — düşük korelasyon zorunlu, yoksa diversifier değil)
> - **Trade sayısı N(filtered) ≥ 80** (Lopez minimum power gate; <80 ise istatistik anlamsız → red)

## 2. Gerekçe (RAG Referansları)

- **RAG #7** (Kaufman): "Channel Breakout — 20-bar veya 55-bar high/low kırılımı. Bağlam: Trending market, ADX > 25 ideal. Yan piyasada whipsaw bombardımanı. Asimetrik R-multiple; %35 win rate ile pozitif beklenti." → Turtle System 2 baseline; **ADX>25 gate'i Kaufman'ın kendi tavsiyesi**, post-hoc icat değil.
- **RAG #6** (Market Structure / Order Flow): "BOS (close-based, n=3) — Mekanik Çalışabilirlik (Crypto 1D): Yüksek." → 1D yapısal kırılımlar kripto'da mekanik olarak test edilebilir; volume-bağımsız (VSA'dan ortogonal kaynak).
- **RAG #1** (Lopez de Prado): "Strategy serbest parametre sayısı / örnek sayısı > 1/30 → red." → Hipotez 3 serbest parametre içeriyor (lookback=55, ADX_th=25, BTC.D_window=30). N≥80 gate'i 80/3=26.7 → **1/30 marjı kıl payı geçilir**; N<80 ise otomatik red.
- **RAG #9** (Chan): "Yeni stratejiler portföye girmeden önce out-of-sample Sharpe > 0.8 eşiğini geçmeli." → Chan'in tek-asset eşiği bizim DSR gate'imizle uyumlu; cross-edge için ek olarak ρ≤0.15 zorunlu.

**Önceki dersler (depends_on):**
- htf-continuation-diversifier (2026-06-02): Donchian generic versiyonu gross-null'u geçti ama net=0. Bu hipotez **rejim gate'in 0→pozitif yapıp yapmadığını** test ediyor — null hipotez "gate hiçbir şey değiştirmez".

## 3. Null Hipotez (Ne Olursa İddia Çürür)

Aşağıdakilerden HERHANGİ BİRİ → REJECT:
- N(filtered) < 80 → istatistik gücü yetersiz, red (rejection reason: insufficient_power)
- p_gross ≥ 0.05 (shuffle null'u yenememiş) → red (rejection reason: no_gross_edge)
- net mean_R < +0.05 → red (fee-erosion, rejection reason: fee_kills_edge)
- daily Sharpe BCa CI'ın alt sınırı ≤ 0 → red (rejection reason: noise_indistinguishable)
- ρ(vsa_climax) > 0.30 → diversifier değil, red (rejection reason: correlated_redundant)
- 2022 + 2023 + 2024 + 2025 yıllarından **≥ 2'sinde** yıl bazında net negatif → regime-dependent fragile, red (rejection reason: regime_fragile)
- ADX threshold sweep ([20, 22, 25, 28, 30]) içinde 25 best değilse, ama 25 raporlanırsa → cherry-pick, red (rejection reason: parameter_cherry_pick)

## 4. Bağımlı Değişkenler (Dependent — Ölçülecekler)

| Metrik | Ölçü |
|---|---|
| net mean_R (per trade) | 55bps+5slip dahil |
| gross mean_R | 0bps |
| p_gross (vs direction-shuffle null) | 200 perm |
| daily Sharpe (NET) + BCa %95 CI | 5000 boot |
| MaxDD (account equity bazlı, not cum_pnl bazlı) | % |
| Trade count N(filtered) | int |
| Win rate | % |
| Profit factor | gross+/gross- |
| ρ(daily-returns, vsa_climax_test) | Pearson, 90d rolling median |
| Year-by-year net mean_R | 2021..2026 split |
| Symbol-out CV (leave-one-out) | min/median/max Sharpe |
| IS/OOS net mean_R ratio | 2021-2024 IS vs 2025-2026 OOS |
| ADX threshold sensitivity | [20,22,25,28,30] sweep |

## 5. Bağımsız Değişkenler (Independent — Sabit veya Sweep'lenecek)

**Sabit (pre-registered):**
- Universe: BTC, ETH, BNB, SOL, XRP, ADA, DOGE USDT-perpetual (2021-01-01'de listelenmiş; survivorship NOT — 7'si de 2026-04-30 hâlâ canlı, post-survivor bias FLAG)
- Period: 2021-01-01 → 2026-04-30
- TF: 1D (close = 00:00 UTC)
- Entry: t bar kapanışta sinyal → t+1 bar açılışta market entry
- Fees: 7.5bps taker round-trip × 2 = 15bps + 5bps slip = ~20bps her ayak, ≈55bps round-trip
- SL: 1.5 × ATR_14_1D
- TP: 3R fixed
- Risk per trade: %1 equity
- max_concurrent: 4

**Sweep (sensitivity, raporlanacak — best seçilmeyecek):**
- Donchian lookback: [20, 34, 55, 89] (Fibonacci grid; best raporlanır ama 55 pre-registered)
- ADX threshold: [20, 22, 25, 28, 30]
- BTC.D slope window: [20d, 30d, 50d]

**Multiple-testing düzeltmesi:** 4×5×3 = 60 kombinasyon → Benjamini-Hochberg FDR q=0.05 zorunlu.

## 6. Beklenen p-value

- Gross-edge gate: p_gross < 0.05 (ham), Bonferroni 60-test sonrası < 0.0008 — **bu gerçekçi değil**, gerçek beklenti p_gross_raw ≈ 0.02-0.08 aralığında. Hipotez kabulü için **pre-registered 55-lookback** spesifik koşulun BH-FDR sonrası q<0.10 olması yeterli; diğer (sweep) noktalar BH altında düşse de **post-hoc** raporlanır.

## 7. Stop Criteria (Araştırmayı Terk)

- IS dilimi (2021-2024) net mean_R < 0 → durdur, hipotezi terk.
- ADX>25 + BTC.D<0 koşulu IS'de N_filtered < 30 (toplam 7 sembol × ~1500 gün) → koşul "imkânsız iyimser", red, terk.
- Shuffle baseline p_gross > 0.30 → null hipotez güçlü, tester'ı durdur, "no edge" yaz.

## 8. Robustness Suite (SOP-3 zorunlu)

1. **Walk-forward**: 3y train / 6m test, step 3m → 7-9 dilim, her dilimde net mean_R + Sharpe rapor.
2. **Param perturbation**: lookback ±10%, ADX_th ±10%, BTC.D_window ±10% → 50 seed, ortalama Sharpe kayıp < 25%.
3. **Symbol-out CV**: 7 sembol × leave-one-out, min Sharpe pozitif olmalı.
4. **Regime split**: Bull (2021, 2024 H2, 2025), Bear (2022, 2025 H2?), Range (2023 H1, 2024 H1) → en az 2 rejimde net pozitif.
5. **Stress periodları**: 2022-05 (LUNA), 2022-11 (FTX), 2024-08 (Yen carry), 2025-Q? — yıkıcı kayıp (>3R single trade) yok.
6. **Shuffle baseline**: 200 permutation, direction-randomized, p_gross < 0.05.
7. **BH-FDR**: 60 sweep noktası üzerinden q=0.05.
8. **Cross-correlation gate**: vsa_climax_test daily-returns ile rolling 90d ρ medyanı ≤ 0.15.
9. **Compounding sanity check**: hem fixed-fraction (önerilen) hem compounding raporlanır; backtest-compounding-inflation dersi gereği (memory/) compounding'in IRL ~10× şişirdiği biliniyor — fixed-fraction baseline mutlak referans.

## 9. Karar Eşiği (Promotion / Iterate / Reject)

| Sonuç | Aksiyon |
|---|---|
| Tüm gate ✓ + tüm robustness ✓ + ρ≤0.15 | **Promotion candidate** → Lab tournament'a teslim |
| Pozitif mean_R AMA DD > 2× vsa_widestop DD | **Iterate (SOP-4b)** → risk_pct/max_concurrent/regime tighten v2 |
| Pozitif gross AMA net~0 (htf-continuation pattern'ı tekrar ediyorsa) | **Reject (clean negative)** — "ADX+BTC.D gate de net edge yaratmadı" |
| N_filtered < 80 | **Reject (underpowered)** |
| ρ(vsa_climax) > 0.30 | **Reject (redundant)** |

## 10. Reproducibility

- git_hash: `<doldurulacak: backtest commit'i>`
- data_hash: `data/market.duckdb` SHA256 @ 2026-06-03
- config_hash: `<backtest config dosyası kaydedilecek>`
- seed: 42 (perturbation), 1337 (shuffle), 7 (boot)

## 11. Önceden Açıklanan Confirmation Bias Şüpheleri (Honest Self-Doubt)

- "Donchian rejim gate ile düzelir" hikâyesi son 4 haftada **4 ailede çürüdü** (SFP, SMC-rev, SMC-cont, htf-cont generic). Prior: bu hipotezin **REJECT olma olasılığı > %70**. Pre-register ediyorum ki sonuç negatifse "aslında bilmiyordum" demem.
- VSA-widestop'un live performansı (cached) bile yeniden hesapta net +0.08 R/trade @ -42% DD çıktı (entry-quality öğrenmesi). Cross-edge için ρ≤0.15 gate'i **bu kalitesi-değişken referansa karşı** ölçülüyor. Diversifier olarak terfi ederse, vsa'nın yeniden-doğrulanmış live numarasına karşı ölçüm tekrarlanmalı.
- Mat-hold (1D, 2026-06-02), Kaufman ATR breakout (1D, 2026-06-03), AVWAP-sweep (2026-06-03), Chan-halflife (2026-06-03), iii-compression, marubozu, golden cross, ORB — **8 cross-edge hipotezi son 3 günde test edildi**. Bu, multiple-testing alanını sessizce büyütüyor; tüm 8+1 hipotezin **ortak BH-FDR** havuzuna alınması Lab'in görevi olarak işaretleniyor.

## 12. Pre-Registration İmzası

Bu doc commit edilmeden önce **hiçbir backtest çalıştırılmamıştır**. İlk koşu sonrası bu doc edit edilirse (statu güncelleme dışında), SUPERSEDED işaretlenir ve yeni doc açılır.
