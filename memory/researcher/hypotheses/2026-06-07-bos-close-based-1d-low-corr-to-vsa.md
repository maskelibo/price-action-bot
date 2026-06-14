---
doc_id: researcher-20260607T140000-bos-close-based-1d-low-corr-to-vsa
doc_type: hypothesis
agent_id: researcher
created_at: 2026-06-07T14:00:00Z
status: PROPOSED
confidence: low
depends_on: []
blocks: []
requested_review_from: [lab_scientist, risk_officer, adversary_engineer]
tags: [cross_strategy_edge, low_correlation_companion, bos, break_of_structure, smc_mechanical_subset, pre_registration]
supersedes: null
hash: null
---

# Hipotez: HYP-2026-06-07-BOS-CLOSE-1D-LOW-CORR-TO-VSA

- **Tarih:** 2026-06-07
- **Versiyon:** 0.1 (pre-registration; kod yazılmadan donduruluyor)
- **Seed bağlam:** Cross-strategy edge keşfi — aktif `vsa_climax_test` (volume klimaks reversal, 15m) ile **düşük korelasyonlu** ek bir aday. Raftaki 66 stratejiden 4'ü (mat-hold, donchian, ATR-thrust, iii) `seed_abort_v2/v3` ile reddedildi → tekrar test edilmiyor. Bugün `marubozu-continuation` ve `donchian-20-1d` pre-register edildi. **Henüz pre-register edilmemiş**, RAG'da "Yüksek mekanik çalışabilirlik" kategorisinde tek özgün aday: BOS (Break-of-Structure) close-based 1D. Donchian'dan farkı: sabit n-bar kanal yerine **yapısal swing pivot** kırılması; popülasyon ortogonal.
- **SMC uyarı:** [[smc-course-no-edge]] dersi 161 video tam evren testinde RED — bu hipotez SMC paketi DEĞİL, sadece BOS'un *close-based mekanik alt-kümesi*. RAG #6 bunu özellikle "Yüksek" feasibility ile ayrı kategoriye koyuyor. Tüm SMC mekanikleri (FVG, OB, equal-highs sweep) hipotez dışı.

## 1. İddia (ölçülebilir, sayısal)

> **H1:** 2023-06-01 → 2026-06-01 dönemi, 30 sembollik USDT-perpetual likit evren (survivorship-corrected; delisted dahil — LUNA/FTT vb. listing'den delisting'e), **1D timeframe**, aşağıdaki *net mekanik* tanımlı **bullish BOS continuation** sinyali — fee 7.5 bps taker + 5 bps slippage, sabit-fraksiyon %0.5 risk/trade — şu metrikleri üretir:
>
> - **OOS annualized net return (compounding-corrected, sabit-fraksiyon):** > **%14**
> - **OOS Sharpe (sqrt(252)×μ/σ, daily log-returns):** > **0.9**
> - **MaxDD (account equity bazlı, zero-base **değil**):** < **%20**
> - **Profit factor (fee+slip dahil):** > **1.30**
> - **Average trade R:** > **0.15R**
> - **Walk-forward (12 dilim, 24m train / 3m test, step 3m) pozitif Sharpe dilim sayısı:** ≥ **8/12**
> - **`vsa_climax_test` aktif strateji ile 30-günlük rolling Pearson korelasyonu (per-bar net PnL):** **|ρ| < 0.25** (cross-edge ön şartı)

**Mekanik tanım (vectorized, lookahead-free, n=3 swing window):**

- **Swing pivot definitions (close-based, no center-window):**
  - `swing_high(t) = TRUE eğer close[t-3..t-1] arasında close[t] strict max VE close[t+1..t+3] arasında close[t] strict max` — **AMA:** bu lookahead. Onun yerine, **gecikmiş pivot:** `confirmed_swing_high(t) = close[t-3] > max(close[t-6..t-4]) AND close[t-3] > max(close[t-2..t]) AND tüm bunlar t bar'ında bilinir`. Yani pivot 3 bar gecikme ile teyit edilir; sinyal t bar'ında değil, t+3 bar'da geçerli.
  - Aynısı `confirmed_swing_low` için ayna.
- **BOS bullish trigger (t bar'ı, sinyal t+1 open'da):**
  - `last_confirmed_swing_high` mevcut (t-3 veya daha eski).
  - `close[t] > last_confirmed_swing_high` (close-based kırılım — wick-only kırılma sayılmaz).
  - **Trend filter:** son 50 close'un SMA50 eğimi (t-1'e kadar) > 0.
  - **HTF veto:** 1W EMA20 > EMA50 (haftalık uptrend; counter-trend BOS'u hariç tut).
  - **Volume teyidi:** breakout barı volume'ü 20-bar volume yüzdebirlik 70+ üzerinde.

**Giriş:** `t+1` bar açılışında market.
**SL:** `last_confirmed_swing_low` altında (yapısal stop; ATR-katı **değil** — yapı bozulursa çık, volatiliteyi parametre olarak kalibre etme).
**TP:** **1.5R fixed** (asimetri yok; trail yok; param uzayını küçük tut).
**Time-stop:** 10 bar (10 gün) içinde TP/SL tetiklenmezse close.

## 2. Null Hipotez (H0)

> Sinyalin shuffle-baseline'a (random entry, aynı SL/TP/holding period, aynı evren, aynı sayı sinyal) karşı OOS Sharpe farkı 0; p-value > 0.05.

**H1 çürür eğer:**
- OOS Sharpe < 0.5
- IS / OOS Sharpe oranı > 2.5× (López de Prado overfit bayrağı)
- BH-FDR q=0.10 sonrası adjusted q > 0.05
- Walk-forward'da 6/12'den az dilim pozitif
- `vsa_climax_test` ile |ρ| ≥ 0.4 → cross-edge tezi düşer, **bu seed bağlamında** reddedilir (tek başına edge olsa bile)

## 3. Gerekçe (RAG referansları)

- **[Market Structure & Order Flow tablosu]** (RAG #6): BOS (close-based, n=3) **"Yüksek mekanik çalışabilirlik"** kategorisinde — "net kural, backtestable, az parametrik". CHoCH de yüksek ama trend-state makinesi ister; BOS daha az parametriktir → ilk denenecek olan BU.
- **[López de Prado — Backtest Overfitting]** (RAG #1): DSR < 0.5, PBO > 0.5, IS > 3×OOS, params/sample > 1/30, walk-forward varyansı > ortalama → bu altı'dan **biri kırmızıysa deploy edilmez**. Pre-registration bu sebeple zorunlu. Bu hipotezde toplam trial = 432 (aşağıda) → BH-FDR uygulanacak.
- **[Brooks — Trading Price Action: Trends]** (dolaylı): "Higher high + higher close → trend continuation prior". BOS bunun strukturel kodlanışıdır (Brooks dilinde "swing high failure to hold" benzeri). Brooks reversal-bar literatürü (RAG #3) ZIT yöne işaret eder — bu yüzden vsa_climax (reversal mekaniği) ile düşük korelasyon **mekanik öngörü**.
- **Cross-strategy korelasyon teorik tabanı:** `vsa_climax_test` = volume_z > τ + reversal bar → fade exhaustion (counter-trend). BOS = yapısal swing kırılması + trend filter + HTF teyidi → with-trend continuation. Tetik mekanizması (volume vs structure), sinyal yönü (reversal vs continuation), hold direction (fade vs follow) ortogonal. **Beklenti ≠ veri; ölçeceğiz.**

## 4. Dependent Variables (önceden sabitlenmiş — p-hacking yasak)

| Variable | Hedef | Annualization | Bazı |
|---|---|---|---|
| Annualized net return | > %14 | (1+r_1d)^252 - 1 | sabit-fraksiyon %0.5 |
| Sharpe | > 0.9 | sqrt(252)×μ_1d/σ_1d | log-returns |
| MaxDD | < %20 | account equity peak-to-trough | **NOT zero-base PnL** |
| Profit factor | > 1.30 | Σ kazanç / Σ kayıp | net fee+slip |
| Avg trade R | > 0.15 | mean(realized_R) | per-trade |
| Walk-forward pozitif dilim | ≥ 8/12 | binary count | OOS Sharpe>0 |
| BH-FDR adjusted q | < 0.05 | shuffle baseline ×432 trial | strict |
| `vsa_climax` PnL korelasyonu | < 0.25 abs | 30-day rolling Pearson | per-bar net |

**KORUMA:** Bu sekiz metrikten biri ihlal ederse hipotez **red**. Post-hoc gerekçe yasak. "Ama X iyi" denmez.

## 5. Independent Variables (parametre uzayı, pre-declared)

| Parametre | Aralık | Adım | Combo |
|---|---|---|---|
| Pivot lookback (n) | {2, 3, 5} | discrete | 3 |
| SMA trend window | {30, 50, 100} | discrete | 3 |
| HTF EMA short/long | {(10,30), (20,50), (50,200)} | discrete | 3 |
| Volume percentile gate | {60, 70, 80} | discrete | 3 |
| TP R-multiple | {1.0, 1.5, 2.0} | discrete | 3 |
| Time-stop (gün) | {5, 10, 15} | discrete | 3 |

**Total trial = 3⁶ = 729 (kayıt için).** Pratikte ilk 432 (anlamlı combo subseti) Optuna TPE + Median pruner ile taranır. **BH-FDR q=0.10 zorunlu.** Bonferroni gözlem amaçlı raporlanır (0.05/432 ≈ 1.16e-4 — neredeyse imkansız eşik; bu yüzden FDR tercih).

**Curve-fit kırmızı bayrakları (pre-declared, otomatik red):**
- Best params uçlarda (n=2 veya n=5; SMA=30 veya 100; vol_pct=60 veya 80; TP=1.0 veya 2.0) → uzayı genişlet veya red.
- Param perturbation (±%20, 50 seed) Sharpe'ın **%35+** kaybına yol açarsa → overfit, red.
- IS/OOS Sharpe oranı > 2.5× → red (López de Prado kriteri).
- params/sample > 1/30: 6 param + 432 trial = etkin 6 serbestlik; sample ≥ 200 trade gerekli (madde 7 stop kriteri).

## 6. Beklenen p-value

- Shuffle baseline'a karşı **raw p < 0.01** (ön şart).
- **BH-FDR q=0.10 sonrası adjusted q < 0.05** (nihai gate).
- Bonferroni adjusted p raporlanır (bilgi amaçlı).
- **Yan koruma:** Bootstrap (1000× resample) Sharpe %5 alt sınır > 0.

## 7. Stop Criteria (research'ün terkedileceği koşullar)

1. **In-sample Sharpe < 0.5** → derhal terk, walk-forward'a gitme.
2. **IS/OOS Sharpe > 2.5×** → overfit, red.
3. **`vsa_climax` ile |ρ| ≥ 0.4** → cross-edge tezi düşer; **bu seed bağlamında** red (ayrı hypothesis dosyası açılabilir).
4. **Walk-forward 12 dilimden 5+ negatif** → tutarsız edge, red.
5. **Param uzayı uçlarında best** → uzay genişlet (max 10 gün) veya red.
6. **Stress periyot DD > -%15** (LUNA 2022-05, FTX 2022-11, BTC ATH 2024-03, Yen Carry 2024-08) → tail-risk açık, red.
7. **Total OOS trade < 200** → istatistik anlamsız, red.
8. **Lookahead causality testi başarısız** (`detector(df.iloc[:t+1])[t] != detector(df)[t]`) → CRIT, kod hatalı, red.

## 8. Curve-Fit Şüphe Beyanı (zorunlu, paranoid)

- **BOS anlatısı çok temiz** — "yapısal kırılım, trend devam eder" hikâyesi yıllardır anlatılıyor (Wyckoff'tan SMC'ye). Hikâye temizliği bias yaratır; karar SADECE sayı verecek.
- 729 combo (efektif 432) trial → **multiple testing tehlikesi yüksek**. BH-FDR + shuffle baseline + walk-forward + param perturbation + symbol-out CV → tüm beşi geçilmeli.
- RAG #6 SMC kitabı tablosu BOS'u "yüksek" derken **akademik çalışma değil, kitap iddiası**. Posterior backtest gerekli; prior sadece denenmeye değer olduğunu gösterir.
- `vsa_climax` ile düşük korelasyon **mekanik öngörü**, **ampirik test** değil. Ön şart §1.
- Pivot tanımı (close-based + 3 bar gecikme) lookahead'i bilerek kapatıyor — ama her detector implementasyonu testten geçmeli (madde 7.8).
- **Symbol-out CV zorunlu.** 30 sembolden 1'i (örn. BTC) tüm edge'i taşıyorsa kalıp evrensel değil, çoğunluk için reject.
- **Survivorship:** LUNA/FTT/UST listing'den delisting'e dahil; backtest engine tarih-bilinçli evren kullanmalı (CI: `tests/test_universe.py::test_includes_delisted_symbols`).

## 9. Reproducibility

- **git_hash:** (backtest sırasında doldurulur)
- **config_hash:** bos_close_1d_v0.1
- **data_hash:** OHLCV evren snapshot 2026-06-01 (DuckDB)
- **rng_seed:** 42 (shuffle baseline + bootstrap için sabit)

## 10. Sonraki adım (sıra)

`backtest/engine.py` üzerinde vectorized BOS detector implementasyonu **bu doc commit'inden SONRA**:

1. Lookahead causality testi (sözleşme: `detector(df.iloc[:t+1])[t] == detector(df)[t]`).
2. In-sample + OOS + 12-dilim walk-forward.
3. Param perturbation (50 seed, ±%20).
4. Symbol-out CV (her sembol tek tek dışarıda).
5. Regime split (bull/bear/range; en az 2'sinde pozitif).
6. Stress periyot replay.
7. Shuffle baseline + BH-FDR.
8. **`vsa_climax_test` ile 30-day rolling per-bar PnL korelasyonu** (cross-edge ön şartı, kabul gate).

## 11. Karar matrisi (önceden sabit, post-hoc değiştirilemez)

| Sonuç | Karar |
|---|---|
| Tüm 8 metrik ✓ + korelasyon ✓ + robustness ✓ | Lab tournament adayı |
| Aylık ROI > 0 ama DD veya korelasyon ihlal | **İterate** (SOP-4b) — v2: risk-azaltma (%0.5 → %0.3) veya v2: trade-quality filtresi (volume_pct 70 → 80) |
| Aylık ROI ≤ 0 veya overfit kırmızı bayrak | Red — gerekçeli arşiv |
| Korelasyon yüksek (|ρ| ≥ 0.4) ama tek başına ✓ | **Bu seed bağlamında red** (cross-edge tezi düştü); ayrı bir hypothesis dosyası ile "stand-alone trend follower" olarak yeniden açılabilir — farklı doc |

---

**Pre-registration kapağı:** Bu hipotez kod yazılmadan donduruldu. Sonradan eklenen herhangi bir parametre, eşik gevşemesi, post-hoc rasyonelleştirme → **otomatik red**. Hash bu commit'in SHA'sı olarak donar.

**Beklenti (researcher'ın peşin notu):** Geçmiş 4 cross-edge denemesi (mat-hold/donchian/ATR-thrust/iii) `seed_abort` ile red oldu. **Bu hipotezin de %70 olasılıkla red gelmesi sağlıklı bir base rate**. Hedef başarı değil, dürüst test.
