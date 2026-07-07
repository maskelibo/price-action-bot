---
doc_id: researcher-20260707T060000-xs-carry-funding-dispersion-weekly-dedicated-book
doc_type: hypothesis
agent_id: researcher
created_at: 2026-07-07T06:00:00Z
status: PROPOSED
confidence: low
depends_on:
  - researcher-20260702-funding-extreme-reversal-standalone-falsified  # #6 fast 15m sentiment proxy; carry≈0; RED
  - researcher-20260702-xs-price-relative-value-jegadeesh-titman-falsified  # #7 XS-price-RV panel; RED, orthogonality collapsed
  - researcher-20260602-cross-sectional-rs-d1-dollar-neutral-low-corr-to-vsa  # XS-RETURN based, not carry — mechanical distinct
  - researcher-20260508-funding-rate-mean-reversion  # time-series 8h MR signal for direction; distinct from carry-harvest
requested_review_from: [lab_scientist, risk_officer, adversary_engineer]
tags: [hypothesis, cross_sectional, carry, funding_dispersion, delta_neutral, dollar_neutral, weekly_book, dedicated_book, hedge_required, last_honest_leverage]
supersedes: null
---

# Hypothesis: HYP-2026-07-07-xs-carry-funding-dispersion-weekly

## 0. Neden Şimdi — Ölüm Silsilesinden Sonra Kalan Tek Elde-Veri Kaldıraç

- 2026-07-02 fiyat-only sinyal uzayı TÜKENDİ (7 bağımsız falsifikasyon: detektörler / kombinasyonlar / funding-standalone / XS-price-RV hepsi RED). Ref: `memory/researcher/learning.md` 2026-07-02 kayıtları.
- Kalan tek adanmış (fiyat-yönüne kurgu-gereği DİK) hasat kanalı: **cross-sectional funding dispersion** — YAVAŞ haftalık kitap, sinyal DEĞİL yapısal ödeme akışı.
- #6 falsifikasyonundan mekanik AYRIM: #6 = **fast 15m entry**, 8-saat settlement geçilmiyor → carry ≈ 0 → funding orada sadece sentiment proxy idi. Bu hipotez = **~21 settlement (7d × 3 settlement/gün) hasadı** — carry MEKANİK olarak biriker.
- #7 falsifikasyonundan mekanik AYRIM: #7 = XS-fiyat-momentum/MR; buradaki sinyal fiyat değil, funding-oranı dispersiyonu. Orthogonality kaynağı: gizli-beta panel-korelasyonu değil, spot-hedge ile per-symbol delta-nötr construction.

## 1. Iddia (pre-registered, ölçülebilir — HEPSİ birlikte geçmeli)

Aşağıdaki universe + kurulum + gate seti üzerinde:

**Universe (delisting-inclusive):**
- Binance USDT-perpetual + Binance spot pair mevcut, likidite ≥ $50M/gün 30d rolling median.
- Sample: 2022-01-01 → 2026-06-30 (4.5 yıl; 2024-01 sonrası OOS = 2.5 yıl).
- Beklenen aktif sembol sayısı: 14-24 (delisting'ler dahil; LUNA 2022-05'e kadar, FTT 2022-11'e kadar sayılır).

**Book Construction (haftalık rebalance, Pazartesi 00:00 UTC):**
- Score = trailing 7-gün ortalama funding rate her sembol için.
- Top-k=3 en yüksek funding → SHORT perp + LONG spot hedge (per-symbol equal notional).
- Bottom-k=3 en düşük/en negatif funding → LONG perp + SHORT spot hedge (per-symbol equal notional).
- Toplam: 12 leg, 6 sembol, per-symbol delta-nötr (spot hedge tam eşleşir), portföy dolar-nötr (top-side notional = bottom-side notional).
- Rebalance costs: full turnover varsayımı (worst-case; realistically ~%60-80 sembol devri).

**Cost Modeli (konservatif):**
- Perp taker fee: 5 bps × leg × 2 (giriş+çıkış) = 10 bps/leg/rebalance.
- Spot taker fee: 5 bps × leg × 2 = 10 bps/leg/rebalance.
- Slippage: 3 bps/leg/rebalance (12 leg × 3 = 36 bps/rebalance ek).
- Short-spot borrow: **APR 15% konservatif** (Binance margin ~5-25% aralığı, tail 30%+).
- Funding gelirleri: gerçek tarihsel Binance funding (public API), pozisyon işaretine göre net.

**GATE (hepsi PASS zorunlu):**

| Metrik | Eşik | Gerekçe |
|---|---|---|
| Net annualized return (fee+slip+borrow dahil) | `> 12%` | Gross 26-38% dispersion iddiasından net ~40-45% haircut sonrası anlamlı |
| Net Sharpe (NW-adjusted, calendar-day) | `> 1.0` | Sinyal-uzayı falsifikasyonu sonrası yeni edge için modest ama defansif eşik |
| Newey-West t-stat (52 haftalık return dizisi) | `> 2.0` | Weekly n≈235 üzerinde asymptotic testi geçmeli |
| MaxDD (**equity-base**, NOT cumulative-PnL base) | `< 15%` | CT-RSK-01 audit kuralı; delta-nötr'de DD kaynağı yalnızca dispersion collapse |
| `|ρ_weekly(strategy, BTC)|` | `< 0.15` | Delta-nötr construction'ın doğrulaması; başarısızsa hedge çalışmıyor |
| OOS Sharpe (2024-01→2026-06, 2.5 yıl) | `> 0.7` | Post-2023 rejim (spot-BTC-ETF akışı, funding rejim değişimi) robustness |
| Shuffle-baseline p-value (funding rank permutation, N=500) | `< 0.05` | Null: dispersion yerine rastgele long-short — bu edge'in bu edge olduğunu kanıtla |
| Symbol-out CV (14+ leave-one-out) | `min OOS Sharpe > 0.4` | 1-2 sembol edge'i taşımıyor doğrulaması |
| Borrow-cost stress (APR 25%) | `net_return > 6%` | Borrow tail rejiminde economic viability |

## 2. Gerekçe (RAG referansları — parametric, hikaye değil)

- **[#1 Harris — Funding Rate Arbitrage]**: perp short + spot long ile delta-neutral pozisyon **yıllıklaştırılmış %20-50** (yüksek funding dönemlerinde). Bu iddianın *dispersion-harvest* uzantısı = aynı mekanizmayı hem üstten hem alttan (long ve short taraf) simultane işletmek → single-side sensitivity düşer, gross dispersion (üst-alt fark) hasat edilir.
- **[#5 Harris — Perp Mechanics]**: funding = (premium_index + clamp(interest_rate − premium_index, ±0.05%)), **8 saatte bir** Binance/Bybit. Bu ölçülebilir zaman-kuantumu: 7-gün hold = 21 settlement = weekly rebalance mimarisi mekanik olarak carry-yakalayıcı, sentiment-signal DEĞİL.
- **[#9 Chan — Funding Rate Arb + BTC-ETH Cointegration]**: yüksek pozitif funding (>%0.05/8h) → long spot short perp; Chan burada single-symbol time-series formülasyon veriyor. **XS uzantısı burada özgün**: aynı anda hem long hem short taraf çalıştırılırsa portföy funding-rejim rotasyonuna daha az kırılgan (single-side'da funding regime dönerse edge çöker).
- **[#3 Chan — Cross-Sectional Ranking / Vol-Targeting]**: aylık XS-momentum vol-targeted çerçevesi; buradaki **replikat metodoloji + değişken (funding rank; return değil)** — Chan XS-momentum'un rejim çökme riski (2008 momentum crash homoloğu) burada da geçerli, ancak delta-nötr per-symbol hedge structural crush riskini büyük ölçüde emmelidir (test edilecek).
- **RAG çıkarımı**: 3 bağımsız kaynak funding-arb mekanizmasını (perp-spot anchor) doğruluyor + XS/vol-target çerçevesini onaylıyor. **Dispersion-harvest'ın XS formulasyonuna** birebir referans YOK — bu tam olarak neden test etmeye değer: mekanizma sağlam, spesifik parametrizasyon literatürde açık kalıp (curve-fit olmayan RAG-basis).

## 3. Null Hypothesis (ne olursa çürür)

- H0-A: Weekly rebalanced XS-carry portföy net return ≤ 0 (fee+slip+borrow dahil). — Kabul edilirse hipotez RED.
- H0-B: BTC ile |ρ_weekly| ≥ 0.15. — Kabul edilirse **hedge çalışmıyor**, "delta-nötr" iddiası çürür, hipotez YAPI olarak RED (edge olsa bile fiyat-only riskin gizli beta versiyonu, dik değil).
- H0-C: Shuffle-baseline p ≥ 0.05. — Kabul edilirse funding-rank dispersion iddiası şansla ayırt edilemez, RED.

## 4. Dependent Variables (measured)

- `net_annualized_return_pct` (fee+slip+borrow net)
- `net_sharpe_calendar_day`
- `nw_tstat_weekly`
- `maxdd_equity_base_pct`  (CT-RSK-01)
- `rho_weekly_to_BTC`
- `oos_sharpe_2024_2026`
- `shuffle_baseline_pvalue`
- `symbol_leave_one_out_min_sharpe`
- `borrow_stress_25apr_net_return`
- `avg_realized_gross_dispersion_annualized` (ölçek doğrulama — 26-38% iddiası tutuyor mu?)
- `avg_turnover_per_rebalance_pct`
- `n_active_symbols_weekly_median`

## 5. Independent Variables (pre-registered — post-hoc değil)

**Primary set (asıl test):**
- `k = 3` (top-k = bottom-k = 3)
- `rebalance_freq = 7d`
- `funding_score_lookback = 7d`
- `min_liquidity_usd_30d_median = 50M`

**Sensitivity grid (curve-fit yakalayıcı — asıl testten ayrı raporlanacak):**
- `k ∈ {2, 3, 5}` — sadece k=3 çalışıyorsa RED FLAG.
- `rebalance_freq ∈ {3d, 7d, 14d}` — sadece 7d çalışıyorsa RED FLAG.
- `funding_score_lookback ∈ {3d, 7d, 14d}` — sadece 7d çalışıyorsa RED FLAG.
- `min_liquidity_usd ∈ {20M, 50M, 100M}` — sadece 50M çalışıyorsa RED FLAG.

Multiple testing: 3×3×3×3 = 81 grid; net Sharpe için Bonferroni α=0.05/81=6.17e-4. Primary set testinden **bağımsız** rapor.

## 6. Beklenen p-value

- Primary shuffle-baseline: `p < 0.01` beklenir (dispersion 26-38%/yr iddiası doğruysa).
- NW t-stat: `> 2.5` beklenir (weekly n≈235, edge büyükse).
- Bonferroni sonrası (81 grid): `p < 6.17e-4` primary konfigürasyon için hâlâ geçmeli.

## 7. Stop Criteria (kod başlamadan önce yazılı)

- **In-sample gross return (fee/borrow ÖNCESİ) < 5%/yr** → HARD TERMINATE. Gross carry gate'i altında; net gate'e ulaşmak matematiksel olarak imkânsız.
- **In-sample Sharpe (gross) < 0.3** → HARD TERMINATE. Gross-side edge yok, cost modelini iyileştirmenin faydası yok.
- **Delta-nötr construction fail: `|ρ_weekly_to_BTC| > 0.30`** → HARD TERMINATE. Hedge mekanik yürümüyor, hipotez YAPI olarak yanlış (bu Δnötr değil, gizli-beta).
- **MaxDD (equity-base) > 30% in-sample** → HARD TERMINATE. Dispersion collapse rejimlerinde risk modeli tahmin edilemez → deploy-uygun değil.
- **Borrow-cost 8% APR üstünde net edge kayboluyorsa** → DEFER not TERMINATE. Ekonomik açıdan borrow rejimine bağlı; farklı venue veya funding alternatifleri raporlanır (ör. cross-margin savings, tokenized borrow).
- **Symbol-out CV: 3+ leave-one-out OOS Sharpe < 0** → HARD TERMINATE. Edge küçük bir alt-kümede yoğunlaşmış, replicability yok.

## 8. Curve-Fit Kırmızı Bayrakları (pre-registered — post-test detection)

Aşağıdaki gözlemler test sonrası yapılırsa hipotez **PASS olsa bile RED** işaretlenir:

1. Primary parametre kombinasyonu (k=3, 7d, 7d, $50M) sensitivity grid'de local-max ise ve komşularda edge kaybediliyorsa → RED FLAG (bkz. `memory/shared/lessons/overfit_red_flags.md` madde 2).
2. Regime split içinde bull/bear/range → yalnızca bir rejimde edge → RED FLAG.
3. Yıllık return'ün > %70'i tek bir yıldan geliyorsa (ör. 2022-Q2 LUNA post-crash) → RED FLAG.
4. Trade sayısı N < 100 rebalance × 6 leg → istatistik anlamsız (weekly × 4.5yr × 6 leg = ~1400 leg-obs beklenir; 300'ün altında red flag).
5. In-sample / OOS Sharpe farkı > %50 → RED FLAG.
6. Fee modelinin optimize edilmesi (ör. spot-tier VIP-4 varsayımı) sonucu doğuruyorsa → RED FLAG (konservatif taker fixed 5bps zorunlu).
7. Borrow-cost'un 0 alınması → RED FLAG (short-spot leg gerçek borrow'a maruz).

## 9. Reproducibility Envelope

- `git_hash`: HEAD @ pre-reg tarihi (bu commit'te işaretlenecek).
- `data_hash`: universe manifest + funding history bloklarının SHA256.
- `config_hash`: primary + sensitivity grid YAML SHA256.
- Random seed: 42 (shuffle-baseline için); 200 seed set param perturbation için.
- Backtest engine: `backtest/engine.py` (vectorbt) + `backtest/xs_carry.py` (bu hipotez için yeni modül; kod PR'ı ayrı, insan onayı gerekli).

## 10. Non-Overlap Beyanı (protokol §1 depends_on)

- #6 funding-standalone (2026-07-02 RED): **entry frequency = 15m**, settlement geçilmiyor → carry ≈ 0; bu hipotez = **weekly hold, 21 settlement hasadı**. Mekanik AYRI.
- #7 XS-price-RV (2026-07-02 RED): sinyal = fiyat momentum/MR; bu hipotez = sinyal = funding-oranı dispersion. Sinyal-uzayı AYRI.
- 2026-06-02 XS-RS D1 (PROPOSED): rank kaynağı = 5-bar return; bu hipotez = rank kaynağı = 7-gün funding score. Rank-değişkeni AYRI.
- 2026-05-08 funding MR (PROMOTED — canlı çalışıyor mu ayrıca teyit edilecek): single-symbol time-series MR signal for **price direction**; bu hipotez = **portfolio-level carry-harvest**, sinyal fiyat yönü için DEĞİL. Kullanım AYRI.

## 11. Sonraki Adım (kod öncesi son kapı)

- Data engineer'a data availability check: Binance historical funding rates + spot pairs 2022-01-01'e kadar geriye — data_engineer'dan endorse/critique al.
- Adversary engineer'dan pre-mortem: 2022-05 LUNA + 2022-11 FTX + 2023-03 USDC depeg + 2024-08 Yen carry unwind dönemlerinde bu book'un nasıl davranacağı — özellikle short-spot leg'in likidite çekilmesi ve borrow-APR spike'ları.
- Risk officer'dan gate onayı: MaxDD (equity-base) hesaplaması CT-RSK-01 uyumlu; borrow-stress 25% APR eşiği yeterli mi?
- Lab scientist'ten robustness suite ordering (walk-forward 3y/6m step 3m + regime split + shuffle baseline + Bonferroni-81 confirm).

## 12. Explicit Prior Probability (subjective, calibration için)

Learning notundan (2026-07-02): "p(edge) ~ %25-30." Bu hipotezin **primary gate'in TAMAMI PASS** olma önsel ihtimalim:

- Gross carry edge ihtimali: ~%60 (RAG 3-kaynak mekanizma doğruluyor).
- Net-of-cost edge ihtimali: ~%35 (fee+slip+borrow ağır, %5-20 gross → net dönüştürme kaybı büyük).
- Delta-nötr `|ρ|<0.15` construction başarısı ihtimali: ~%70 (spot-hedge mekanik olarak çalışmalı).
- Sharpe > 1.0 net ihtimali (edge varsa): ~%50.
- **Tüm gate'lerin AYNI ANDA PASS** koşullu ihtimal: %25-30 (learning kaydı ile hizalı; kalibre).

Bu bir "yüksek-güven" iddia değil. Ama fiyat-only uzayı tükendi; **bu bantta hâlâ hasat şansı olan tek dik kanal**.
