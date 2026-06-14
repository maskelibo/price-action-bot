---
doc_id: researcher-20260605T000000-golden-death-cross-d1-cross-edge-vsa
doc_type: hypothesis
agent_id: researcher
created_at: 2026-06-05T00:00:00Z
status: PROPOSED
confidence: low
depends_on:
  - lab_scientist-20260602-htf-continuation-diversifier-result
  - researcher-20260602-mat-hold-1d-continuation-cross-edge
  - researcher-20260603-donchian55-regime-gated-1d-cross-edge
requested_review_from:
  - lab_scientist
  - risk_officer
  - adversary_engineer
tags:
  - hypothesis
  - cross_strategy_edge
  - low_correlation
  - trend_following
  - 1d
  - pre_registration
supersedes: null
hash: null
---

# HYP-2026-06-05 — Golden/Death Cross D1 as VSA-Climax Diversifier (Cross-Edge Discovery)

## 0. Seed & Context

- **Seed konu:** Aktif `vsa_climax_test` ile düşük korelasyonlu ek strateji adayı (raftaki 66'dan).
- **Neden bu aday:** Tüm taranan RAG ailelerinden (#2 inside, #3 Brooks rev, #5 Kaufman ATR breakout, #6 SMC BOS/CHoCH, #7 Donchian, #8 Marubozu, #10 Mat Hold) **Golden Cross/Death Cross (RAG#4)** crypto evreninde pre-register edilmemiş tek somut yapısal-farklı aday. Diğer hepsi ya filed (`hypotheses/` listesi 2026-06-01..04) ya da reddedildi (continuation ailesi `learning.md` 2026-06-02 clean-negative).
- **Yapısal düşük-korelasyon argümanı (mekanik):** VSA climax = tek-bar yüksek-hacim exhaustion event'i (sürekli aktif sinyal, 15m'de günde 0-N tetik). Golden/Death cross = 50-SMA × 200-SMA D1 (yılda 2-6 tetik/sembol, pozisyon haftalar tutulur). Tetik frekansı ve tutma süresi **2 mertebe farklı** → return-stream overlap düşük olmak ZORUNDA (matematiksel olarak; teyit gerek).

## 1. İddia (PRE-REGISTERED, ölçülebilir)

> "1D timeframe'de, 15-sembollü crypto-perpetual evreninde (mevcut aktif `vsa_climax_test` evreniyle aynı, survivorship-free), close-based **50-SMA × 200-SMA crossover** sinyali — long sadece 50>200 (golden) tetik bar close'unda, short sadece 50<200 (death) tetik bar close'unda — pozisyon **trailing stop = 50-SMA** ile yönetilir, alternatif exit ters crossover; 7.5bps taker fee + 5bps slippage dahil; 2020-01-01 → 2026-06-01 dönemi (78 ay), aşağıdaki **tüm** koşulları sağlar:
>
> 1. **Gross edge real:** Shuffle baseline (yön random) karşı `p_gross < 0.05` (1000 seed).
> 2. **Net edge real:** Day-Sharpe bootstrap 95% CI **sıfırı içermiyor** (alt sınır > 0).
> 3. **Per-year robustness:** 7 takvim yılının ≥ 5'inde net mean_R > 0.
> 4. **Cross-correlation gate:** `vsa_climax_test` günlük strateji-return'leriyle (mevcut canlı/paper journal son 90g) Pearson |ρ| < 0.20 **VE** çakışan-trade-gün overlap < %25.
> 5. **MaxDD gate:** Net MaxDD ≤ −28% (champion v13 MaxDD −%23 + 5pp pay).
> 6. **Marginal portföy katkısı:** vsa_climax_test (50% ağırlık) + golden-cross (50% ağırlık) basit toplam portföyün daily Sharpe'ı, tek-başına vsa_climax_test daily Sharpe'ından **mutlak +0.05 yüksek** (additive, %15 göreli değil — küçük tutuyorum çünkü diversifikasyon-only iddia ediyorum, alpha değil).
>
> Yukarıdaki 6 koşulun **hepsi** sağlanırsa hipotez kabul edilir; bir tanesi düşerse hipotez reddedilir."

## 2. Null Hipotez (ne olursa çürür)

- H0: Golden/Death cross D1 crypto yönü, direction-shuffle null'dan ayırt edilemez (`p_gross ≥ 0.05`).
- VEYA: p_gross < 0.05 ama net day-Sharpe CI sıfırı içeriyor (gross edge fee'ye yenik — Donchian/EMA200-pull case'in tekrarı, learning.md 2026-06-02).
- VEYA: ρ ≥ 0.20 VSA climax ile (yapısal düşük-korelasyon argümanı çöker → diversifier değil).
- VEYA: Sideways yıllarda (2025?) 4-6 ardışık whipsaw kümülatif MaxDD'yi gate dışına çıkarır (Kaufman'ın açıkça uyardığı failure mode).

## 3. Bağımlı Değişkenler (önceden kayıtlı, sonradan eklenmez)

- `mean_R_net_55bps` (per-trade)
- `daily_sharpe_net` (annualized, bootstrap 95% CI)
- `p_gross_shuffle` (1000 seed)
- `maxdd_net_pct`
- `per_year_net_mean_R` (2020-2026, 7 yıl)
- `corr_pearson_vs_vsa_climax_test_90d`
- `trade_day_overlap_pct_vs_vsa_climax_test_90d`
- `portfolio_marginal_daily_sharpe_delta` (50/50 simple add)
- `n_trades_total` (frequency sanity check)

## 4. Bağımsız Değişkenler (parametre uzayı — DAR tutuluyor, anti-curve-fit)

| Param | Değer | Gerekçe |
|---|---|---|
| fast_ma | **50 (sabit)** | Kaufman canonical, sweep YOK — curve-fit önleme |
| slow_ma | **200 (sabit)** | Kaufman canonical, sweep YOK |
| timeframe | **1D (sabit)** | Kaufman: "intraday'de gürültü baskın" |
| exit | **{trailing fast_ma, opposite cross}** ikisi de raporlanır, ikisi de gate'e tabi | İkili exit → seçenek var, ama önceden taahhüt |
| risk_pct | 0.005 (champion seviyesi) | live ile aynı, ayrı sweep yok |
| symbol_universe | aktif vsa universe (15 sembol) | aynı evren — apples-to-apples |
| fees/slip | 7.5bps + 5bps | konservatif |

**Toplam DoF: 2** (sadece exit-mode seçimi raporlanır). Bonferroni n=2 → adjusted alpha 0.025.

## 5. RAG Gerekçesi (kaynak alıntı)

- **[Kaufman summary §Crossover]** (RAG#4): "Golden/Death cross 50/200 MA; daily/weekly timeframe ideal; intraday'de gürültü baskın. Düşük frekans, düşük commission yükü. Major trend'leri yakalar. Failure: sideways market'te 4-6 ardışık whipsaw, late entry/late exit yapısal sorun."
- **[López overfit gates]** (RAG#1): "DSR<0.5 / PBO>0.5 / IS Sharpe>3·OOS Sharpe → production'a gitmemeli." Bu hipotez 50/200 sabit + tek timeframe + tek evren → DoF=2; PBO için yeterince sığ.
- **[Kaufman Donchian §Failure]** (RAG#7): "Choppy/range-bound rejimde back-to-back whipsaw; kümülatif %20-40 drawdown." — aynı failure mode crossover için de geçerli, MaxDD gate'i bu yüzden −%28'de.

## 6. Beklenen p-value & İstatistik

- **Direction-shuffle null:** 1000 seed → eğer gerçek edge varsa `p_gross < 0.01` beklenir (continuation ailesinin tersine, çünkü tetik nadir + post-cross momentum literatürde belgeli).
- **Multiple testing:** Bu hipotez "raftan tek aday" olarak pre-register ediliyor; **diğer 65 raf adayı bu çalışmada test edilmiyor.** Aksi halde n=66 Bonferroni → adjusted α = 0.00076 olur ki bu çoğu candidate için imkansız bar. Bu hipotezi izole, başına buyruk test ediyorum — **aksi halde kabul kriteri α/66.**
- **DSR (Deflated Sharpe):** sample length 78 ay × ~20 trade/sembol × 15 sembol ≈ 2300 trade → yeterli; trial sayısı 2 (exit mode) → DSR p < 0.05 hesaplanır.

## 7. Stop Criteria (erken iptal)

- **In-sample (2020-2024, 5 yıl) `p_gross > 0.30`** → hipotez TERK, araştırma bitti, OOS koşturma.
- **In-sample net day-Sharpe < 0** → TERK.
- **n_trades_total < 100** → TERK (istatistik geçersiz).

## 8. Curve-Fit / Overfit Şüphe Bayrakları (ZORUNLU ÖZ-ELEŞTİRİ)

🔴 **Yüksek risk noktaları — bu hipotez şüpheli, çünkü:**

1. **Bulkowski rank sayıları stocks-equity, kripto değil.** RAG#10 (Mat Hold) %74 continuation crypto'da reddedildi (already filed `2026-06-02-mat-hold-...`). Aynı failure golden cross için de mümkün.

2. **Continuation/trend-following ailesi crypto OHLCV'de 4 farklı mekanizmayla CLEAN NEGATIVE kapandı** (`learning.md` 2026-06-02: BOS+displacement, Donchian, EMA200-pull, FVG-continuation hepsi p_gross<0.05'i geçemedi veya geçti ama net day-Sharpe sıfırdan ayrılamadı). Golden cross **aynı aileye yapısal olarak çok yakın** — başarısızlık base-rate'i yüksek.

3. **Kaufman'ın kendi failure-mode listesi:** "late entry/late exit yapısal sorun" + "sideways 4-6 whipsaw". 2025 H1 crypto sideways idi → bu yıl tek başına gate'i bozabilir.

4. **Cross-correlation gate (Pearson ρ < 0.20) curve-fit'e açık:** Eğer post-hoc bulduğumuz "düşük korelasyonlu sembol alt-evreni" varsa, evren küçültme ile gate'i geçirme cazibesi olur — **YASAK.** Evren aktif VSA evreniyle aynı, alt-küme YOK.

5. **MaxDD gate −%28 cömert.** Champion −%23, +5pp pay verdim ama sliding sample'de daha kötü çıkabilir; **gerçek tehlike** çift-strateji portföyünde aynı anda DD yaşamak (correlation gate ρ<0.20 olsa bile drawdown-correlation farklı olabilir — robustness'ta `dd_overlap_days_pct` ek raporlanmalı, gate değil ama not).

6. **Survivorship bias hatırlatması** (`shared/lessons/2026-05-08-survivorship-bias`): Universe historical olmalı, delist olanlar pozisyon kapatılır. Mevcut backtest harness bunu zaten yapıyor mu? **Pre-flight check zorunlu.**

7. **Tek-yön bias (long-only golden vs short-also death):** Death cross short'u kripto'da %43 listing bias'lı evrende çalışabilir/çalışmayabilir. Long ve short ayrı raporlanır, ikisi de ayrı ayrı gate.

8. **N_trade = 2300 görünüyor ama haftalar tutulan pozisyon → bağımsız trade sayısı ~200-400.** İstatistiksel güç düşüncesi → CI geniş olabilir, gate'i şanssız geçer veya kalır.

## 9. Beklenen Karar Dağılımı (ön-tahmin)

- P(kabul tüm 6 gate) = **%10-15** (continuation ailesinin tarihsel başarı oranı + base rate düşüklüğü; namuslu ön-tahmin).
- P(p_gross<0.05 ama net day-Sharpe CI sıfır içerir) = **%40** (Donchian/EMA200 case repeat).
- P(p_gross ≥ 0.05, gross edge yok) = **%35**.
- P(rho ≥ 0.20 sürpriz — düşük korelasyon iddiası kırılır) = **%15** (çünkü 1D vsa_climax_test trend filtrasyonu zaten 50-EMA HTF kullanıyor → cross'la mantıklı bir overlap olabilir; teyit gerek).

Bu dağılım **ön kayıt** — sonuç bu dağılımın dışındaysa post-hoc gerekçeleme yasak.

## 10. Sonraki Adım

1. Backtest harness'i hazır mı doğrula (data/market.duckdb 2020-2026 D1 universe coverage check).
2. SOP-3 robustness suite ile koş (walk-forward 3y/6m step3m, symbol-out CV, stress 2022-05 LUNA / 2022-11 FTX / 2024-08 Yen).
3. Sonuç doc'unu `reports/research/golden-death-cross-d1.md` olarak yaz.
4. Karar (terfi/iterate/red) bu doc'un §1 6-gate listesine **mekanik** olarak uygulanır — gözle "iyi görünüyor" YOK.

## 11. Iterate Politikası (SOP-4b)

Eğer p_gross<0.05 + per-year >5/7 + ρ<0.20 ama **net-Sharpe gate** veya **MaxDD gate** düşerse → **REDDETMEK YASAK.** İterate v2:
- v2: long-only (death-cross short'unu kes)
- v3: regime-gate (ADX>20 only, RAG#7 "sideways'da whipsaw" karşı kalkan)
- v4: half-position (risk_pct 0.005 → 0.0025) MaxDD halve
- v5: time-exit (max 60-bar hold, late-exit yapısal sorununu kes)

Eğer p_gross ≥ 0.05 → ÇIPLAK RED (gerçek edge yok, iterate yasak — Fabio order-flow / SMC dersi, `learning.md` 2026-06-01..02).

---

**Bu hipotez bir kez commit'lendiğinde hash dondurulur; parametre değiştirme yasak. Sonuç §1'deki 6 ölçütle mekanik karara bağlanır.**
