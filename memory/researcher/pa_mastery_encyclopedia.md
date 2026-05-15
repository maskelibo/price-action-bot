---
name: pa-mastery-encyclopedia
description: Crypto 1d × ALL_11 evreninde PA edge-landscape'in tam haritası — 28-sprint zincir sentezi (SEC4 → SEC27)
metadata:
  type: project
  audience: future-researcher, future-claude, principal, lab-scientist
  consolidation_sprint: SEC28
  source_sprints: [SEC4, SEC5, SEC6, SEC11e, SEC13.2, SEC13.3, SEC14.0, SEC14.1, SEC15.2, SEC19, SEC21, SEC22, SEC23, SEC24, SEC25, SEC26, SEC27]
---

# PA Mastery Encyclopedia — Crypto 1d Edge Landscape

> **Bu dokümanın amacı:** Bu dosyayı okuyan bir researcher (gelecekteki Claude, Principal veya yeni analizci) crypto 1d × ALL_11 evrenindeki PA edge-landscape'in TAM haritasını tek dosyadan alabilmeli. Yeni bir hipotez yazmadan önce: (a) hangi pattern class'ının ne prior'a sahip olduğunu, (b) hangi setup'ın TEST EDİLDİĞINI ve hangi sonucu verdiğini, (c) crypto'ya özgü hangi mikroyapısal mekanizmaların edge'i şekillendirdiğini bu dosyadan tek bakışta görebilmeli.
>
> **Bu doküman backtest sonucu değil sentezdir.** Yeni veri yok — 28 sprint'in (SEC4 → SEC27) tortusu.

---

## §0 Yönetici Özeti

### §0.1 Production Champion (v2.0.3 BALANCED + funding + F&G + halt)

| Boyut | Değer |
|---|---|
| Pool | TOP_10 + FVG (11 strateji) — 3 trend_cont omurga + 4 mean_rev + 2 structural + 2 marjinal |
| Universe | BTC ETH SOL ADA DOT AVAX MATIC LINK BNB XRP DOGE (11 sym × 5y × 1d) |
| Yıllık return (3y rolling WF, 13 pencere) | +%239.5 (SIM = HONEST_BE, matematiksel doğrulanmış) |
| Drawdown | -%38.7 |
| Risk-adjusted | 6.189 |
| Negatif pencere | 0 / 13 |
| Compound 5y ($10k başlangıç) | $2.7M (HIBRIT side-cond DD: long 0.15, short 0.05) |
| Engine config | tp1_R=1.0, tp2_R=1.5, runner_trail_mult=1.0, time_exit=30bar, trail_activate_stage=2, mc=12, per_sym=0.20, cooldown=3→5d, side-cond DD, capitulation halt, F&G≤20 short-skip, funding both-side filter |
| LIVE durumu | Backtest doğrulandı, paper trading devam ediyor (SEC20+SEC26.B live wiring kapandı, paper 90g sayacı işliyor) |

### §0.2 Test Edilen Pattern Envanteri (SEC22 + SEC24 + SEC25 + SEC26 sentezi)

| Durum | Sayı | Notlar |
|---|---:|---|
| TESTED-PASS-PRODUCTION | 11 | Production pool envanteri (§2) |
| TESTED-PASS-STANDALONE (ensemble null) | ~14 | Slot bottleneck reddiyle pool'a giremedi |
| TESTED-RED / TESTED-ARCHIVE | 12+ | Mean-rev family, compound multi-pivot, asset-class transfer fails |
| PRE-REG (UNTESTED) | 8 | Wyckoff Phase D LPS, ICT OB+LiqGrab, S/R flip retest, Grimes ABC, Grimes Failure Test, Vol-z spike, CME gap fade, alt-data 4 strateji |
| NOT_TESTED (literatür) | ~10 | Brooks channel line third touch, Wyckoff UTAD/LPSY, ICT Breaker/Mitigation, Minervini VCP, Crabel ID/NR4 kombosu, Three Drives harmonic, Connors 80/20 bar, BB %b mid-fade |
| SCOPE_OUT (intraday/scalping) | 4 | Volman DD/BB, ICT PO3 — 1d/swing scope dışı |

### §0.3 En Önemli 5 Meta-Bulgu (top of mind)

1. **Crypto'da edge MAGNITUDE'ce gelir, SAYICA değil** — top 10% trade'ler total sumR'in %154'ünü üretiyor (extreme power-law). Engine **let-runners-run** dizayn edilmeli; DD breaker'lar **çok tutucu = felaket** (right-tail keser).
2. **Mean-reversion family DEFAULT FAIL** — BB extreme, RSI2, Turtle Soup, three-push wedge, HTF retest, Quasimodo: 6-sprint zincir RED. Tek skalable mean-rev edge **FVG-style microstructure gap reclaim** (mean_rev class sumR'in %69'u). Klasik RSI/Bollinger extreme crypto'da CONTINUATION (counter-mechanism).
3. **Compound multi-pivot pattern'lar n bottleneck** — three-push (max n=77), HTF (n=35), Brooks DB (default n=31), Wyckoff phase_d (n=170). 5y × 11 sym × 1d kapsamında 3+ koşul gerektiren pattern'ler **standalone n_min=200 gate'i yapısal yetersiz**. Universe expansion (20+ sym) veya 4h timeframe lazım, AMA universe expansion zaten denendi (SEC13.3 RED), 4h pivot da denendi (SEC6 RED).
4. **11-sym BTC-anchor lokal optimumda kilitli** — SEC4 (yeni strat sınıfı), SEC5 (manifest gap), SEC6 (4h pivot), SEC13.3 (20-sym ekleme), SEC27 (5-sym daraltma): 5-sprint zincir kanıtı. Universe size'da herhangi bir sapma return'ü öldürüyor (alt-only DD iyileştirir ama mutlak return %35-50 kaybeder).
5. **Slot bottleneck mit'i çürütüldü (SEC21)** — 6-sprint zinciri (ML v1/v2, regime-conditional, EER v1/v2, sec4, sec19) "slot dolu, yeni strateji giremiyor" hipotezini öne çıkardı. SEC21 per-strategy slot allocation testi: yıllık +136% → +131% (-5pp). **Gerçek sebep**: trend_continuation right-tail asimetrisi mean_reversion'dan ağır, FIFO doğru policy.

### §0.4 Crypto'da NE ÇALIŞMAZ

| Class | Örnekler | RED gerekçesi |
|---|---|---|
| **Klasik mean-reversion** | BB 2.5σ extreme (mR=-0.288, 0/11 sym pozitif), RSI2 extreme (OOS RED, selection-bias), Turtle Soup 20D (Bonferroni 0/18), three-push wedge fade (n bottleneck) | Crypto'da +2.5σ excursion CONTINUATION, mean-rev counter-mechanism. Vol persistence > vol reversion. |
| **Volatility class** | NR7 (2x RED), BB squeeze breakout (RED), HTF (Bulkowski) | Crypto'da vol contraction sonrası breakout asymmetric değil; trigger rare; pattern stocks-equities native. |
| **Compound multi-pivot rare** | Quasimodo 5-pivot, three-push wedge, HTF, Brooks DB | Standalone n_max < 200; 5y × 11 sym kapsamında yapısal seyrek. Engine artifact (`runner_force_exit_bars=30` standalone override eksikliği) fantasy R üretiyor (SEC11a-22-24-25 3x postmortem). |
| **Asset-class transfer naive** | Stocks/FX'te kanıtlı pattern → crypto'da TERS edge | Raschke/Connors 1996 (US equities/FX), Bulkowski (US stocks), Crabel 1990. Crypto'da 24/7 + perp leverage + funding cycle mikroyapı tamamen farklı. |
| **Funding/OI/onchain alt-data signal** | funding_mean_reversion (zero trade), liquidation_fade, onchain_signals | External data dependency, manifest'te zero-trade üretiyor; SEC5 gap inceleme bulgusu. Data Engineer SEC25 reaktivasyon backlog. |
| **4h primary timeframe** | SEC6 pivot — yıllık +%14.4 (1d champion %33.6 → 2.5x daha iyi) | 4h pool n 3.39x büyük ama trade başına fee/slippage R ağır. |

### §0.5 Crypto'da NE ÇALIŞIR

| Class | Production örnekler | Mekanizma |
|---|---|---|
| **Trend continuation (5/11 pool)** | brooks_failed_breakout (sumR +370, %27 katki), brooks_h2_l2 (sumR +194), engulfing_continuation (sumR +162, mR +0.463), obv_engulfing_confluence (sumR +71, mR +0.423), pin_bar_round_numbers (marjinal) | Leverage cascade + 24/7 + Brooks trap mekanizmasi crypto'da equity'den GÜÇLÜ — trapped retail liquidation katlanır. |
| **FVG microstructure gap (1/11 pool, OMURGA)** | fvg_fill_reversal (sumR +267, mean_rev class'in %69'u) | ICT 3-bar imbalance reclaim = order-flow gap. Exchange-agnostic, stop-hunt sonrası reclaim. **Klasik mean-rev DEĞIL — microstructure mean-rev.** Alt-coin'lerde özellikle güçlü (ADA mR +0.59, XRP +0.47). |
| **Structural rare/powerful (2/11 pool)** | wyckoff_phase_d (mR +0.511, n=170, hold med 30.5d), equal_highs_sweep (mR +0.168, n=279), vsa_climax_test (mR +1.257, n=30 RARE) | Smart-money accumulation/distribution cycle. 24/7 crypto cycle ile uyumlu. Hold uzun, fat-tail karşılığı. |
| **AVWAP marjinal (mean_rev support)** | anchored_vwap_reversal (mR +0.073, n=948) | Mean-rev to institutional fair-value. Marjinal AMA pool'a diversification ekler. |

### §0.6 Karşı-Sezgisel Bulgular (SEC26 forensik)

| Bulgu | Sayı | Naive intuition | Crypto-spesifik mekanizma |
|---|---|---|---|
| **BTC<EMA50 mR > BTC>EMA50 mR** | +0.239 vs +0.172 (delta +0.067) | "BTC trend with → long bias kazanır" | Pool short asymmetry'siyle uyumlu — BTC<EMA50 = bear/range = SHORT edge baskın |
| **High-vol mR > Low-vol mR** | +0.269 vs +0.159 (1.69x) | "High-vol pozisyon küçült" | High-vol = trend cascade aktif = trend_cont + Brooks trap trigger artar; AMA LUNA/FTX-tier ekstrem high-vol toxic (Analyst capitulation halt) |
| **SHORT mR > LONG mR** | +0.247 vs +0.149 (1.66x) | "Crypto secular bull → long dominant" | Short capitulation moves (LUNA, FTX, ATH reject) big-R yarıyor; F&G≤20 short-skip losing-tail short engelliyor |
| **RANGE rejiminde SHORT/LONG = 4.62x** | range short +0.245 vs long +0.053 | "Range = mean-rev = simetrik" | Range tepelerinde short likidasyon riski → sıkışan retail → counter-trend short edge |
| **Right-tail %154 katki** | Top 10% trade sumR'in 1.54x'i | "DD breaker sıkı tut" | Mid 80% trade noise (-%3), bot 10% kayıp (-%52); engine **let-runners-run** zorunlu |
| **Alt-coin 3.22x BTC mR ama universe REJECT** | alt5 avg mR +0.335 vs BTC +0.104 | "Alt-only sub-portfolio kazandırır" | Sub-universe slot bottleneck (mc=12 sabit, n_sym=5 slot'lar yarı dolu); BTC-anchor lokal optimum |

---

## §1 Pattern Class Taxonomy + Crypto-Fit Matrix

Pattern class düzeyinde Bayesian prior — yeni hipotez yazarken ilk filtre.

| Class | Production katki | Crypto-fit prior | Kanıt sprint zinciri | WHY mekaniği |
|---|---|---:|---|---|
| **trend_continuation** | 5 strateji, sumR +834.6 (%61), avg mR +0.255 | **%50-70 PASS** | SEC25 (Brooks DB), SEC26 forensik 5/6 yıl pozitif | Leverage cascade + 24/7 + Brooks trap. Trend kendi yakıtında yanıyor: BTC %5 → funding+arb → likidasyon zinciri → %15. Equity trend-follower'lardan magnitude 2x ağır. |
| **microstructure mean-rev (FVG-style)** | 1 strateji (FVG OMURGA), sumR +267 (%19.7) | **%50-60 PASS** | SEC11e (FVG WIN +%8.7pp WF), SEC26 jaccard 0.076 BFB-FVG | Order-flow gap reclaim. Exchange-agnostic 3-bar imbalance. Stop-hunt sonrası reclaim, manipulation candle reset. Alt-coin'lerde 3-4x güçlü. |
| **structural (Wyckoff + SMC)** | 2 strateji + ICT/SMC, sumR +133.7 (rare ama powerful) | **%60 PASS** | SEC26 wyckoff_phase_d mR +0.511, vsa_climax_test mR +1.257 (n=30 RARE), equal_highs_sweep mR +0.168 | Smart-money accumulation/distribution cycle. 24/7 cycle ile uyumlu. ICT order-block + liquidity grab native crypto pattern. |
| **mean_reversion klasik (RSI/BB/wedge fade)** | 0 production | **%15-25 FAIL DEFAULT** | SEC22 (3 RED: BB, RSI2, three-push), SEC23 (RSI2 OOS RED), SEC24 (Turtle Soup HARD RED), SEC25 vol micro (4 RED) | Crypto'da +2.5σ excursion CONTINUATION; vol persistence > reversion. Klasik 30+ yıl stocks/FX kanıtı crypto'ya transfer FAIL. |
| **volatility (NR7, BB squeeze, HTF)** | 0 production | **%20-30 FAIL** | SEC11/15.2 NR7 2x RED, SEC22 BB squeeze RED, SEC19/22 HTF RED kalıcı archive | Crypto vol contraction asymmetric değil; pattern rare + trigger orijinal universe (US equities) için tasarlanmış. |
| **contrarian (climax, 3-soldiers)** | 1 strateji rare (vsa_climax_test) | **%40-50 NEUTRAL** | SEC26 vsa n=30 mR +1.257, three_white_soldiers/black_crows standalone PASS ensemble null | RARE ama yüksek-mR; tetik climactic vol-spike + reversal bar; sequential pattern detection. |
| **compound multi-pivot rare** | 0 (n bottleneck) | **%10-20 FAIL n-bound** | SEC22 three-push, SEC19/22 HTF, SEC25 Brooks DB | 3+ koşul compound = recall %30-50; 5y × 11 sym kapsamında n_max=30-100 < 200 gate. **Universe expansion sub-class** — ama universe expansion zaten lokal optimumun dışında. |

> **Pre-screening kullanımı:** Yeni hipotezin class'ını taxonomy ile eşle. Mean-reversion klasik veya volatility veya compound-rare class'ında ise prior %15-25 — Bayesian güncellenebilir ama veri yükü ağır. Trend-continuation veya microstructure veya structural class'ında ise prior %50-70 — class kapsamı doygun mu (TOP_11 ile orthogonality jaccard ölçüldü mü) onu sor.

---

## §2 Production Winners — Formal Anatomy

11-strateji production pool (TOP_10 + FVG, configs/risk_balanced.yaml). Veri kaynağı: `reports/researcher/sec26_per_strategy_breakdown.csv` (n=6650 trade, 5y × 11 sym).

### §2.1 Edge Hierarchy (sumR'a göre, top 3 omurga %61)

| # | Strategy | Class | Canonical kaynak | n | WR | mR_raw | mR_clip60d3R | sumR | mean_R_win | mean_R_loss | W/L ratio | hold_med | Pool katki % |
|---:|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | **brooks_failed_breakout** | trend_cont | Brooks Ch.10 Reversals/Failed Breakouts | 1545 | 52.1% | +0.240 | +0.217 | **+370.4** | +1.390 | -1.012 | 1.37 | 9.0d | **27.3%** ⭐ OMURGA |
| 2 | **fvg_fill_reversal** | mean_rev | ICT FVG / SMC knowledge/books/smc.md | 1863 | 52.0% | +0.144 | +0.120 | **+267.3** | +1.231 | -1.035 | 1.19 | 4.0d | **19.7%** ⭐ OMURGA |
| 3 | **brooks_h2_l2** | trend_cont | Brooks Ch.5 Trading PA TRENDS | 816 | 49.4% | +0.238 | +0.193 | **+194.4** | +1.532 | -1.024 | 1.50 | 4.0d | **14.3%** ⭐ OMURGA |
| 4 | engulfing_continuation | trend_cont | Brooks Ch.7 Always-in + Bulkowski Engulfing | 350 | 56.9% | +0.463 | +0.391 | +161.9 | +1.581 | -1.012 | 1.56 | 13.0d | 11.9% |
| 5 | wyckoff_phase_d | structural | Wyckoff knowledge/books/wyckoff_method.md | 170 | 55.9% | +0.511 | +0.348 | +86.9 | +1.714 | -1.011 | 1.69 | 30.5d | 6.4% RARE |
| 6 | obv_engulfing_confluence | trend_cont | Granville OBV (1963) + Brooks Engulfing | 167 | 59.9% | +0.423 | +0.423 | +70.7 | +1.381 | -1.007 | 1.37 | 12.0d | 5.2% |
| 7 | anchored_vwap_reversal | mean_rev | Harris (2003) + Volume Profile (Steidlmayer) | 948 | 45.0% | +0.073 | +0.050 | +69.3 | +1.362 | -0.984 | 1.39 | 14.0d | 5.1% MARGINAL |
| 8 | equal_highs_sweep | structural | SMC / ICT Liquidity Pools knowledge/books/smc.md | 279 | 49.5% | +0.168 | +0.168 | +46.8 | +1.385 | -1.024 | 1.35 | 5.0d | 3.4% |
| 9 | vsa_climax_test | mean_rev | Williams VSA Master the Markets Ch.4 | 30 | 70.0% | +1.257 | +0.868 | +37.7 | +2.229 | -1.009 | 2.21 | 32.5d | 2.8% RARE/POWERFUL |
| 10 | pin_bar_round_numbers | trend_cont | Volman Forex PA Scalping + Bulkowski Pin Bar | 389 | 46.8% | +0.096 | +0.080 | +37.2 | +1.373 | -1.027 | 1.34 | 4.0d | 2.7% MARGINAL |
| 11 | cvd_spike_fade | mean_rev | Granville OBV + CVD lit (knowledge/volume_price_divergence.md) | 93 | 48.4% | +0.157 | +0.157 | +14.6 | +1.424 | -1.032 | 1.38 | 3.0d | 1.1% MARGINAL |

**Top 3 (Brooks failed BO + FVG + Brooks H2/L2) = pool sumR'in %61'i.** Diğer 8 strateji uncorrelated diversifikasyon.

### §2.2 Class Distribution (Trade Kontribüsyonu)

| Class | n_strats | n_trades | trade_share | mean_mR | sumR |
|---|---:|---:|---:|---:|---:|
| trend_continuation | 5 | 3267 | 49.1% | +0.255 | +834.6 |
| mean_reversion (FVG dominated) | 4 | 2934 | 44.1% | +0.133 | +388.9 |
| structural | 2 | 449 | 6.8% | +0.298 | +133.7 |

**Yapısal gözlem:** Class concentration homogen değil — trend_cont trade sayısında hakim (49.1%, sumR'in %61), mean_rev edge yoğunluk düşük (mR 0.133), structural rare ama yüksek mR (0.298, 2x trend_cont).

### §2.3 Setup Orthogonality (Jaccard Co-Occurrence)

55 strateji çiftinin tümünde jaccard < 0.08. Top high-jaccard:

| Strat A | Strat B | Jaccard |
|---|---|---:|
| brooks_failed_breakout | fvg_fill_reversal | 0.0759 |
| anchored_vwap_reversal | fvg_fill_reversal | 0.0570 |
| anchored_vwap_reversal | brooks_failed_breakout | 0.0519 |
| brooks_failed_breakout | brooks_h2_l2 | 0.0512 |
| engulfing_continuation | obv_engulfing_confluence | 0.0508 |

Top lowest-jaccard (en orthogonal): vsa_climax_test çiftleri 0.0019-0.0036, engulfing × wyckoff_phase_d 0.0019, fvg × vsa_climax 0.0022.

**Anlam:** Pool yapısal orthogonal. Bu sayede slot fix (mc 8→12, SEC14.0) konsistent yarar getirdi (+%7.6pp yıllık).

### §2.4 Engine Config Defaults — Matematiksel Gerekçeler (SEC26 Forensik Sentezi)

| Engine param | Value | Forensik gerekçe | Sprint |
|---|---|---|---|
| `tp1_R` | 1.0 | Sequential dependency (Markov-1 delta_WR +13.9pp) + 50% WR ortamında early lock-in | SEC11b, SEC26 H7 |
| `tp2_R` | 1.5 | SEC11b sweep: 2.0 fantasy R (runner over-extends), 1.5 optimal right-tail/realistic exit denge | SEC11b |
| `runner_trail_mult` | 1.0 | Right-tail dominance: top 10% trade sumR'in %154'ünü taşır; trail mult 2.0 fantasy R (SEC11a A artifact), 1.0 captures real tail | SEC11a, SEC13.4-A6 |
| `time_exit_bars` | 30 | SEC13.4 A6: A artifact-free, max R=15.7 (önce 657 fantasy); sermaye recycle, long-hold (>30d) trade kesilir | SEC13.4 |
| `trail_activate_stage` | 2 | Stage<2 force-exit guard (SEC11a/SEC22 quasimodo fantasy R artifact bulgusu) | SEC11a, SEC22 |
| `consecutive_losses` | 3→5d cool-down | Markov-1 cluster reset: base WR %50.9, after_loss %43.7 (-13.9pp); 5g regime değişimi için yeterli | SEC26 H7 |
| `max_concurrent` | 12 | Slot bottleneck WIN sec14.0 (8→12 +%7.6pp); orthogonal pool yararı yapısal | SEC14.0 |
| `max_per_symbol_pct` | 0.20 | Alt-coin dispersion (3.22x mR boost) konsantrasyona çevirmemek; 0.30 felaket DD -%85 | SEC14.0 |
| `monthly_dd_long/short` | 0.15/0.05 | Asymmetric short edge (1.66x) → short trade'ler sıkı stop, long alanlı; pure side-cond +%136 / hibrit +%116 (DD koruması tercih) | SEC14.1, SEC26 H4 |
| `regime_filter.capitulation_halt` (ATR%≥6 + EMA200 streak + 90d-DD≤-25%) | true | Ekstrem high-vol (LUNA/FTX) toxic; high-vol genel edge'i ama LIMIT'li | Analyst HYP, SEC26 H8 |
| `alt_data.fng_short_skip` (F&G ≤20) | true | F&G fear bottoming → losing-tail short engellenir; +%19pp uplift WF 13 pencere | v0.9.7, SEC26 H4 |
| `alt_data.funding_filter` (both-side) | true | Funding > +0.0001 long-skip + < -0.0001 short-skip = +%18pp uplift worst-window +21pp | v0.9.5 alt-data filters |

---

## §3 Reddedilmiş Aday Envanteri (56-Setup Gap Tablosu)

Kanonik PA otoritelerinin setup'larından test edilenler. Tam matris: `reports/researcher/2026-05-14_pa_mastery_gap.md` (56 satır).

### §3.1 Brooks (Reading Price Charts Bar by Bar / Trading PA Trends-Reversals-Ranges / Brooks 10-Best)

| # | Setup | Class | Durum | Sebep |
|---|---|---|---|---|
| 1 | H2 / L2 single-bar continuation | trend_cont | **PRODUCTION** (mR +0.238, n=816, sumR +194) | Pool omurga (top 3) |
| 2 | 10-bar failed breakout | trend_cont | **PRODUCTION OMURGA** (mR +0.240, n=1545, sumR +370, pool %27) | Trap mekanizmasi crypto'da equity'den GÜÇLÜ |
| 3 | Three-push wedge fade | mean_rev | **TESTED-RED-CONDITIONAL** | SEC22 n bottleneck (max 77 < 150), pattern crypto-rare |
| 4 | Double bottom bull flag / DT bear flag | trend_cont | **TESTED-RED** | SEC25 default n=31, 18-config Bonferroni 0/18; pattern edge VAR ama n yetersiz (5/6 yıl pozitif, orthogonality jaccard 0.011 engulfing) |
| 5 | Channel line third touch reversal | structural | NOT_TESTED | brookstradingcourse.com |
| 6 | Climactic reversal (vol-spike + reversal bar) | contrarian | TESTED-PASS-STANDALONE | vsa_climax_test overlap (production) |

### §3.2 Wyckoff / Evans / VSA / Williams

| # | Setup | Class | Durum | Sebep |
|---|---|---|---|---|
| 10 | Phase D Spring + SOS + LPS | structural | **PRODUCTION RARE** (mR +0.511, n=170, sumR +87, hold_med 30.5d) | Smart-money accumulation; long-hold ama right-tail yakalar |
| 11 | UTAD (distribution upthrust) | structural | NOT_TESTED | Short-side LPSY eksik |
| 12 | LPSY (Last Point of Supply) | structural | NOT_TESTED | Distribution short |
| 33 | VSA climax test (Williams Ch.4) | contrarian/mean_rev | **PRODUCTION RARE/POWERFUL** (mR +1.257, n=30, sumR +38, hold_med 32.5d) | RARE ama 2.21 W/L ratio |
| 34-D1 | VSA SOS (effort-up) | trend_cont | **TESTED-RED** (SEC25) | IS→OOS sign-flip |
| 34-D2 | VSA SOW (effort-down) | trend_cont (short) | **TESTED-RED-pre-reg / v2 ADAY** | IS gate fail, OOS post-hoc dramatik (mR +0.533 11/11 sym poz). Regime-conditional v2 backlog. |
| 34-D3 | VSA Bag Holding (absorption) | mean_rev | **TESTED-RED** (SEC25) | n=15 yetersiz (5y × 11 sym yapısal rare) |
| 34-D4 | Weis Wave volume divergence | mean_rev | **TESTED-RED** (SEC25) | IS→OOS sign-flip + symout 48% |

### §3.3 Adam Grimes (Art and Science of TA)

| # | Setup | Class | Durum | Sebep |
|---|---|---|---|---|
| 13 | Failure Test (false break + reclaim at swing) | mean_rev | **NOT_TESTED** (PRE-REG var SEC24) | Wyckoff spring vektörize eşdeğeri; pre-reg `2026-05-14-grimes-failure-test.md` |
| 14 | Two-legged pullback ABC | trend_cont | **PRE-REG (UNTESTED)** | `2026-05-14-grimes-abc-two-leg-pullback.md` SEC25 backlog; brooks_h2_l2 deeper variant |
| 15 | Complex consolidation breakout (multi-contraction) | trend_cont | NOT_TESTED | adamhgrimes.com |

### §3.4 ICT / SMC

| # | Setup | Class | Durum | Sebep |
|---|---|---|---|---|
| 25 | Order Block | structural | TESTED-PASS-STANDALONE | smc_orderblock.py + ob_mitigation_strict.py |
| 26 | Fair Value Gap fill | mean_rev | **PRODUCTION OMURGA** (mR +0.144, n=1863, sumR +267, mean_rev class %69) | 3-bar imbalance reclaim, alt-coin'lerde 3-4x |
| 27 | Liquidity Sweep (single-swing) | structural | **PRODUCTION** (equal_highs_sweep mR +0.168, n=279) | SMC stop-hunt; LiqSweep v2 redundant |
| 28 | Breaker Block (failed OB → flip) | structural | NOT_TESTED | innercircletrader.net; smc_orderblock orthogonal |
| 29 | Mitigation Block (OB return continuation) | structural | NOT_TESTED | innercircletrader.net |
| 30 | PO3 (AMD intraday cycle) | structural | SCOPE_OUT | Intraday-only |
| 31 | Quasimodo (HH-HL-HH-LL-LH 5-pivot) | mean_rev | **TESTED-ARCHIVE** | SEC19 fantasy-R artifact RED |

### §3.5 Raschke / Connors / Crabel / Bulkowski / O'Neil / Minervini

| # | Setup | Class | Durum | Sebep |
|---|---|---|---|---|
| 17 | High-Tight Flag (4-8w pole + tight consol + BO) | trend_cont | **TESTED-ARCHIVE** | SEC19 n=35, SEC22 retest 10/10 config RED; pattern Bulkowski US small-cap stocks native, crypto'da uyumsuz |
| 19 | NR4 / NR7 / Inside Day | volatility | **TESTED-RED** (2x) | nr7_breakout_v2 2x RED + SEC15.2 v3 RED |
| 20 | ID/NR4 double-compression combo | volatility | NOT_TESTED | Crabel "best 1-2 setup" |
| 21 | Minervini VCP | trend_cont | NOT_TESTED | traderlion.com; volatility-contraction breakout-conditional |
| 22 | **Turtle Soup (20D failed BO inverse)** | mean_rev | **TESTED-HARD-RED** (SEC24) | n=475 mR +0.026 p=0.318; Bonferroni 0/18; symout dev 79.5% (ETH+BNB konsantre); orthogonality jaccard 0.000 donchian (mükemmel inverse), AMA edge yok |
| 23 | RSI(2) extreme fade | mean_rev | **TESTED-ARCHIVE** (SEC22+23) | OOS RED, selection-bias (27-config grid, en iyi rsi=5 OOS collapse) |
| 24 | Connors "80/20" bar | mean_rev | NOT_TESTED | rsi2 yakın akrabası, retry argümanı zayıf |

### §3.6 Tom Dante / Lance Beggs / Volman

| # | Setup | Class | Durum | Sebep |
|---|---|---|---|---|
| 7 | Volman 70-tick DD/BB scalping | scalping | SCOPE_OUT | Intraday-only |
| 8 | Dante Inside Day Failure | mean_rev | **TESTED-PASS-STANDALONE** (SEC19 V3) | mR +0.240 p=0.060, ensemble null (slot bottleneck), trend filter kombo edge bozuyor (failure pattern doğal trend-dışı) |
| 9 | Dante Swing Failure Pattern (SFP) | structural | NOT_TESTED | x.com/Trader_Dante swing-level farklı, LiqSweep yakın ama tam değil |
| 16 | Beggs Trapped Trader | mean_rev | NOT_TESTED | Brooks failed_breakout %80 overlap, orthogonality zayıf |

### §3.7 Volume / Bollinger / Volatility

| # | Setup | Class | Durum | Sebep |
|---|---|---|---|---|
| 37 | BB squeeze breakout | volatility | **TESTED-RED** | SEC15.2 v3 RED + nr7 zinciri |
| 38 | BB 2.5σ extreme reversal | mean_rev | **TESTED-HARD-ARCHIVE** | SEC22: mR=-0.288, 0/11 sym pozitif; crypto'da +2.5σ excursion CONTINUATION (mean-rev counter-mechanism) |
| 39 | BB %b mid-band fade | mean_rev | NOT_TESTED | StockCharts ChartSchool variant; BB extreme RED yakın yapısal retry argümanı zayıf |
| 49 | ATR / volatility z-spike fade | mean_rev | **PRE-REG (UNTESTED)** (SEC24) | `2026-05-14-vol-z-spike-fade.md` Engle GARCH temelli vol-clustering inverse |

### §3.8 CME / Microstructure / Cross-asset

| # | Setup | Class | Durum | Sebep |
|---|---|---|---|---|
| 53 | CME weekend gap fade (BTC/ETH) | mean_rev | **PRE-REG (UNTESTED)** | `2026-05-14-cme-gap-fade-btc-eth.md`; n bottleneck riski (5y × 4 sym × ~12 trigger = ~240, borderline) |
| 52 | Cross-sectional momentum/reversal | trend_cont | NOT_TESTED | Dobrynskaya SSRN portfolio strategy, single-sym engine'e uyumsuz |
| 32 | Three Drives Pattern (Fib-symmetry exhaustion) | mean_rev | NOT_TESTED | LiteFinance; Fib tolerance tuning kompleks, n yıllık 3-5/sym rare |

### §3.9 Alt-Data (funding / OI / onchain / sentiment / F&G)

| # | Setup | Class | Durum | Sebep |
|---|---|---|---|---|
| - | funding_mean_reversion (manifest signal) | alt-data | SEC5 RED zero trade | `funding_rate_lag1` external data dependency, manifest gap |
| - | liquidation_fade (manifest signal) | alt-data | SEC5 RED zero trade | Liquidation feed OHLCV'ye merge edilmemiş |
| - | btc_eth_pairs (manifest signal) | alt-data | SEC5 RED zero trade | Cross-asset feed eksik |
| - | onchain_signals (manifest signal) | alt-data | SEC5 RED zero trade | Glassnode/Santiment feed eksik |
| - | funding-OI divergence (HYP-2026-05-12-005) | alt-data signal | **TESTED-FAIL** | n=4 trade quick check, OI veri yok funding-only proxy yetersiz |
| - | **F&G ≤20 short-skip** (filter not signal) | alt-data | **PRODUCTION FILTER** | v0.9.7 +%19pp uplift, +%3pp WIN-WIN final BALANCED |
| - | **funding both-side filter** (filter not signal) | alt-data | **PRODUCTION FILTER** | v0.9.5 +%18pp uplift worst-window +21pp |

> **Yapısal mesaj:** Alt-data **filter olarak güçlü** (F&G, funding), **signal generator olarak zayıf** (manifest signal'lar zero trade veya quick-fail). Bu bir özellik, bug değil — alt-data düşük SNR raw signal verir, edge **filter etmekte** çıkar.

---

## §4 Meta-Pattern Bulguları (Transferable Knowledge)

Bu bölüm yeni hipotez yazarken **pre-screening prior**'lar üretir. Her bulgu sprint zincirinden gelir; her birinin (a) ne kanıtladığı, (b) WHY mekaniği, (c) yeni hipotezde nasıl uygulanacağı yazılıdır.

### §4.1 Mean-Rev Family RED Prior (4-Sprint Zincir)

**Kanıt zinciri:**
- SEC22 — bb_extreme_reversal HARD RED (mR -0.288, 0/11 sym pozitif), rsi2_extreme_fade PASS-MARGINAL (selection-bias), three_push_wedge_fade RED-CONDITIONAL (n bottleneck)
- SEC23 — RSI2 OOS RED (selection-bias forensik)
- SEC24 — Turtle Soup HARD RED (n=475 mR +0.026 p=0.318, Bonferroni 0/18)
- SEC25 — VSA SOS/SOW/BagHolding/Weis 4/4 RED

**WHY mekaniği (mikroyapısal):**
Crypto'da +2.5σ excursion = momentum başlangıcı, NOT exhaustion. Vol persistence > vol reversion. Klasik istatistiksel mean-rev (RSI/Bollinger extreme) crypto'da CONTINUATION mekanizmasına dönüşür. Sebep: 24/7 + retail leverage cascade → trend kendi yakıtında yanar (BTC %5 → funding+arb → likidasyon → %15). Equity'de overnight gap fade etmek mantıklı, crypto'da gap yok.

**FVG istisna:** Mean_rev class sumR'in %69'u FVG-style microstructure gap reclaim. Bu **klasik mean-rev değil** — order-flow gap (3-bar imbalance), exchange-agnostic, stop-hunt sonrası reclaim mekanizmasıyla çalışır. Crypto-spesifik mikroyapısal.

**Nasıl uygula:** Yeni hipotezin "extreme RSI / BB / oscillator fade" formunda mı? → Prior %15-25 FAIL. **Tek sınırlı PASS yolu**: mikroyapısal mekanik (order-flow gap, microstructure inefficiency) kanıtla; klasik istatistiksel mean-rev gerekçesi yetersiz. Mean-rev family yeni hipotezi yazmadan önce: "Bu pattern crypto'da CONTINUATION yapar mı?" sorusuna explicitly cevap ver.

### §4.2 Compound Multi-Pivot N Bottleneck (3-Sprint Zincir)

**Kanıt zinciri:**
- SEC19 — High-Tight Flag n=35 (Bulkowski US small-cap stocks native)
- SEC22 — three-push wedge_fade n_max=77 (45 sweep config)
- SEC25 — Brooks Double Bottom Bull Flag n=31 default; honest clip hold>30 n=109 mR +0.342 p=0.008 (edge VAR ama n<200 gate)
- SEC19 — Quasimodo (5-pivot) RED-ARTIFACT (fantasy R, hold>60d trade'lerde mR +1.647 vs hold<=15d mR -0.005)

**WHY mekaniği:**
Compound pattern (3+ pivot + 3+ condition) crypto 1d × 11 sym × 5y kapsamında **yapısal seyrek**. Vektörize implement original "trader gözünden gördüğü" pattern'in %30-50'sini yakalar (recall problemi). 5y × 11 sym × annual_freq=5-15 × recall=0.3-0.5 ≈ 60-200 expected. Gate n_min=200 + Bonferroni multiple testing FAIL.

**Universe expansion test edildi:** SEC13.3 20-sym RED (yeni 9 alt-coin standalone POZITIF ama ensemble seyreltici), SEC27 5-sym REJECT (alt-only sub-universe slot bottleneck). Yapısal optimum 11-sym BTC-anchor (§4.3).

**Nasıl uygula:** Pre-reg'de `n_target = 5y × 11_sym × annual_trigger_rate × recall(0.3-0.5)` hesapla. Compound 3+ koşul → expected n=60-200 → **gate-borderline** planla. Pre-reg gate'i pure mR yerine **honest-clip + p<0.05 + symout < 30% + Bonferroni** ile sıkı bağla; n<200 gate'inde ARGUE etme (literatur autorite + edge VAR çekiciliği bias üretiyor).

### §4.3 11-Sym BTC-Anchor Lokal Optimum (5-Sprint Zincir)

**Kanıt zinciri:**
- SEC4 — Yeni strategy class survey 4 standalone POZITIF (vol_risk_premium, naked_poc_mr, ii_breakout, failed_bo_bos_reclaim) ama ensemble null (TOP_10 doygun)
- SEC5 — Manifest gap inceleme; 4 alt-data sıfır-sinyal stratejisi external data dependency
- SEC6 — 4h primary timeframe pivot RED (yıllık +%14.4 vs 1d +%33.6; trade fee ağır)
- SEC13.3 — 20-sym universe genişletme RED (yıllık +%67.8 → +%16.4, yeni alt-coin'ler seyreltici)
- SEC27 — 5-sym alt-only sub-universe REJECT (V1 -%37pp Δ_ann, AMA DD %50 iyileşti — conservative LP variant adayı)

**WHY mekaniği:**
production_replay sermaye dağıtımı (max_concurrent=12, max_per_sym=0.20, cooldown=3g) **universe size'a duyarsız sabit**. n_sym=5 → slot'lar yarı dolu; n_sym=20 → yeni sym'ler düşük conf trade'leri yüksek conf BTC/ETH'i scheduler'da dışlıyor (mc=12 sabit, FIFO). Alt-coin mR boost 3.22x doğru AMA sumR yetersiz (V1 alt5 n=2870, V0 11-sym n=6650).

**Pencere korelasyonu V0/V1 = +0.845** → alt-only V0'ın deflated version'u, right-tail explosion (V0 max +169% pencere) alt-only'de yakalanmıyor (V1 max +81%).

**H_anti sürprizi (SEC27):** Naive intuition "alt-only DD ağırlaşır" yanlış — alt-only DD %50 **iyileşti** (-34.5 → -16.8). Çünkü crypto'da alt-coin korelasyon clustering yüksek → 11-sym diversification benefit marjinal. BTC/ETH stress'te (LUNA/FTX) alt-coin'lerden DAHA HIZLI çakılıyor (V1 LUNA mR +0.969 vs V0 +0.465 = 2.08x stress-hedge).

**Nasıl uygula:** Universe size sweep ile sub-universe arama YAPMA — 11-sym BTC-anchor optimum yapısal. **Yan-bulgu**: V3 (alt5+BTC) conservative LP variant cazip (yıllık +%77 / DD -%18 / r-adj 4.196), Lab strategic discussion ile preset variant olabilir AMA mutlak hedef BALANCED champion ile uyumsuz.

### §4.4 Slot Bottleneck YÜZÜNDEN DEĞIL, Right-Tail Asimetrisi YÜZÜNDEN (SEC21 Refutation)

**Kanıt:**
6 sprint zinciri "slot doymuş, yeni strateji giremiyor" hipotezini öne çıkardı:
- ML v1 + v2 (meta-labeling RED, feature space RED)
- Regime-conditional ML (border-RED)
- EER v1 + v2 (Expected Edge Rank RED, bucket coverage %0)
- SEC4 yeni strategy class survey (4 standalone PASS ensemble null)
- SEC19 (HTF + IDF + QM 3 standalone PASS ensemble null)

**SEC21 falsification:** Per-strategy slot allocation eklendi (`configs/strategy_taxonomy.yaml`: 5 sinif, 53 strateji). Replay sonucu: yıllık +136% → +131% (-5pp). **Default OFF korundu.**

**WHY (gerçek mekanik):** trend_continuation strategy'lerinin right-tail asimetrisi (top 10% trade %154 sumR katki) mean_reversion'dan AĞIR. Slot kotası shifting net **NEGATIF** çünkü trend_cont right-tail'i kesip yerine mean_rev marjinal mR koyuyor. FIFO doğru policy.

**Nasıl uygula:** "Slot bottleneck yüzünden ensemble null" gerekçesini yeni hipotezde kullanma — SEC21 reddedildi. Doğru gerekçe: pool yapısal orthogonal (jaccard < 0.08) ve trend_cont right-tail dominant. Yeni aday slot'a girmek için MR/sumR'da trend_cont omurgasını YENMELI.

> **Slot bottleneck reframe**: Empirik gözlem (yeni standalone PASS ensemble null) doğru AMA **mekanik yorum yanlıştı**. Gerçek sebep: aday strateji right-tail asimetrisinde production omurgayla rekabet edemiyor. Yorum güncellemesi: `memory/learning_slot_bottleneck_refutation.md` (Engineering).

### §4.5 Asset-Class Transfer Bias

**Kanıt zinciri:**
- SEC22 — BB 2.5σ extreme stocks/FX'te kanıtlı, crypto'da TERS (mR -0.288)
- SEC22/SEC19 — HTF Bulkowski US small-cap stocks native, crypto'da n=35 RED
- SEC24 — Turtle Soup Raschke 1996 US equities/FX, crypto'da HARD RED
- SEC25 — Brooks DB Bull Flag (stocks-derived) n=31 RED ama 5/6 yıl pozitif (edge VAR yetersiz n)
- SEC19 — High-Tight Flag O'Neil/Weinstein US growth stocks 70-yıl edge, crypto 1d 11-sym kapsamında ölü

**WHY mekaniği:**
Crypto 24/7 + perp leverage cascade + 8h funding cycle + low-Sunday-liquidity Monday spike microstructure'ı stocks/FX 1990s'den TAMAMEN farklı. "Klasik 30 yıl edge" iddiası crypto'ya **direkt transfer etmeye** yetmez. Bayesian prior'da literatür-kaynaklı autorite bias +%30 max (gerisini veri belirler).

**Nasıl uygula:** Yeni hipotez stocks/FX literatür-kaynaklı mı? → Pattern'in crypto microstructure (24/7, retail leverage, funding 8h cycle, order-flow gap reclaim) mekanizmalarından hangisi ile besleneceği SOMUT olarak yazılmalı. Eğer SOMUT bir crypto-spesifik mekanizma kanıtlanamıyorsa prior %20-30.

### §4.6 Asymmetric Short-Edge (1.66x LONG; RANGE 4.62x)

**Kanıt (SEC26 forensik):**
- LONG: n=2903, WR 50.4%, mR +0.149, sumR +432.0
- SHORT: n=3747, WR 51.3%, mR +0.247, sumR +925.2
- SHORT mR / LONG mR = **1.66x**
- RANGE rejiminde SHORT mR (+0.245) / LONG mR (+0.053) = **4.62x**

**WHY mekaniği:**
Crypto secular bull bias varsayımı yanlış. SHORT capitulation moves (LUNA 2022-05, FTX 2022-11, mart 2024 BTC ATH reject, 2024-08 Yen carry) tek seferlik buyuk R yaratıyor. RANGE rejiminde range tepelerinde short'lar likidasyon riskine giriyor → sıkışan retail → counter-trend short edge'i besleniyor (equal_highs_sweep + brooks_failed_breakout mekanizmasi).

**Production'a yansıma:**
- SEC15.6 PURE side-cond mdd (long_dd=0.15, short_dd=0.05): yıllık +%136
- HIBRIT (combined_dd=0.06 korundu) tercih: yıllık +%116 (DD korumayı tercih)
- v0.9.7 F&G ≤20 short-skip (ekstrem fear bottoming): losing-tail short engellenir, big-winner short universe temiz kalır

**Nasıl uygula:** Yeni hipotez "long-only" mu yoksa "short variant default test"i içeriyor mu? Default'a short variant ekle. Asymmetric DD breaker (long gevşek, short sıkı) sistemde mevcut — yeni strateji bu mekanizmaya uyumlu olmalı (örn. ekstrem fear gunlerinde short emit etme).

### §4.7 Right-Tail Dominance %154 (DD Breaker Tutucu = Felaket)

**Kanıt (SEC26 forensik):**
- Total sumR: +1357.3
- Top 10% trade (n~665): sumR +2093.7 (**154.3% of total**)
- Mid 80% trade (n~5320): sumR -36.5 (-%2.7, ≈noise)
- Bot 10% trade (n~665): sumR -699.9 (-%51.6)
- Max R (single trade): +28.90 (vs SEC11a-fantasy +657 reddedilen artifact)
- Min R (single trade): -1.19

**WHY mekaniği:**
Extreme power-law distribution. Equity'de S&P trend-follower'lar (Trout, Dunn — Covel 2007) benzer pattern ama crypto'da magnitude **>2x daha sert** (equity top decile katki ~30-40%, crypto ~%154). Sebep: leverage cascade + 24/7 + funding cycle = trapped retail liquidation katlanır.

**Engine implication:**
- tp1_R=1.0, tp2_R=1.5, runner_trail_mult=1.0, time_exit=30bar — fat-tail capture + early lock-in denge
- SEC11a A artifact (mult=2.0, no force-exit): fantasy R=657 — runner sermayeyi bağlayıp gerçek edge yakalamadı
- SEC13.4 A6 force-exit: gerçek max R=15.7 (artifact-free), sermaye recycle

**Nasıl uygula:** DD breaker tasarımında "küçük kayıpları aşmak" değil **"büyük kazananı kaçırmamak"** mental modeli. Daily/weekly/monthly DD breaker eşikleri grid-sweep edildi (SEC10): monthly 0.15→0.08 = yıllık +%4 / DD -%0.8 / r-adj +0.15 WIN (SEC12 daha sıkı 0.06 = +%9pp uplift). 0.05 altına inmek right-tail keser → defansif overshooting felaket.

### §4.8 Engineering Artifact: Standalone `runner_force_exit_bars=30` Manifest Override Eksik (SEC22/24/25 3x Postmortem)

**Kanıt zinciri:**
- SEC22 — three_push_wedge_fade standalone hold_median 45-60d, gate threshold runner_force_exit etkin değil
- SEC24 — Turtle Soup standalone max_R 4.82 OK (n=475 trade'lerin hold dağılımı OK), ama bazı 60+ gün hold edge fantasy R üretiyor (SEC11a postmortem 2.)
- SEC25 — Brooks DB Bull Flag standalone default mR +0.638 (no clip), hold>30 clip sonra +0.240 = **-62% fantasy**

**Mekanizma:**
Standalone test'lerde engine `runner_force_exit_bars=30` manifest override edilmiyor (default manifest config'i yüklenmemiş). ETH 2022-04 short hold=60d R=12.79 (Q2 LUNA collapse window) gibi trade'ler standalone'da çıkmıyor; honest clip (hold>30d → R cap=1.0) sonrası fantasy R %30-62 arası mR over-estimate düzeliyor.

**Nasıl uygula:** Yeni strategy standalone testlerinde:
1. **Honest clip zorunlu** (hold>30 → R cap=1.0 veya hold>60 → R cap=3.0; SEC22/24 disipliniyle)
2. Slippage erosion 0.06R/trigger eklensin (SEC16 düzeltme)
3. Engineering ticket önerisi: `scripts/_template/standalone_strategy_test.py` master copy + auto-clip protokol (SEC11a postmortem 3.)
4. Default mR fantasy vs honest_clip mR delta'sını raporla (transparency).

---

## §5 Forensik Manifesto: Yeni Hipotez Pre-Registration Checklist

Yeni PA hipotezi yazan herkes için 12 madde — her hipotezin pre-reg dokümanına `class_prior: PASS|FAIL|NEUTRAL` field'ı eklensin:

1. **Pattern class taxonomy ile eşle** (§1).
   - Mean-reversion klasik / volatility / compound-rare → DEFAULT FAIL prior (%15-25)
   - Trend-continuation / microstructure / structural → DEFAULT PASS prior (%50-70)
   - Hangi class'ta? Class-prior çoğunluğu çürütmek için kanıt yükü kim üzerinde?

2. **Asset-class transfer assumption explicitly test et**.
   - Stocks/FX literatür-kaynaklı mı?
   - Pattern crypto-spesifik mikroyapısal mekanizmalardan (24/7, retail leverage cascade, funding 8h cycle, order-flow gap reclaim) hangisi ile besleniyor? SOMUT yaz.
   - Bayesian prior'a literatür-autorite +%30 max weight.

3. **Compound multi-pivot ise n_target tahmin et** (§4.2).
   - `n_target = 5y × 11_sym × annual_trigger_rate × recall(0.3-0.5)`
   - Compound 3+ koşul → expected n=60-200 → gate-borderline planla.
   - Pre-reg'de "expected n bottleneck" alanı.

4. **Universe size sweep yapma**.
   - 11-sym BTC-anchor lokal optimum (§4.3). 5-sym REJECT, 20-sym RED, 4h pivot RED.
   - Sub-universe variant test ederken pre-reg gate'i mutlak return ≥ +10pp **VE** Bonferroni CI low > 0 (SEC27 disiplini).

5. **Bonferroni multiple testing correction**.
   - k = parametre sweep config sayısı. α_adj = 0.05/k.
   - 18-config grid → α = 0.00278 (SEC24/25 disiplini).
   - FDR-BH q=0.10 marjinal kullanım için.
   - Effective dimensionality (parametre kombinasyonlarının trade-redirect etmediği) ölçülmeli (SEC23 yöntem).

6. **Counter-hypothesis yaz (H_anti) — spesifik**.
   - H_anti'nin DOĞRULANMASI testin nasıl olacağını yaz.
   - Örnek: "alt-only DD ağırlaşır" (SEC27 H_anti partial yanlış çıktı — DD iyileşti).
   - Pre-reg disiplini: H_anti partial doğru/yanlış AYRI raporlanır.

7. **Honest hold clip + slippage erosion** (§4.8).
   - hold>30 → R cap=1.0 (SEC22/24 strict) veya hold>60 → R cap=3.0 (SEC26 standart).
   - Slippage 0.06R/trigger (SEC16 düzeltme).
   - Default mR fantasy vs honest_clip mR delta'yı raporla.

8. **Symbol-out CV gate (per-sym dev ≤ %50)**.
   - Tek-symbol konsantrasyon yakala (SEC24 TS ETH+BNB %79.5 dev).
   - Eşik %30 SOP, %50 borderline.

9. **Shuffle baseline p ≤ 0.05** (n_perm ≥ 1000).
   - Null model: trigger zamanları rastgele permutasyon.
   - Bonferroni sonrası p < α/k.

10. **WF rolling 3y (13 pencere) + OOS hold-out 2024+**.
    - Selection bias guard (SEC23 RSI2 OOS RED ders).
    - IS=2021-2023, OOS=2024-2026. Sign-flip yakala.

11. **Pre-reg dokümanına `class_prior` alanı**.
    ```yaml
    hypothesis_id: HYP-YYYY-MM-DD-<slug>
    class: trend_continuation | mean_reversion | structural | volatility | contrarian | compound_multi_pivot | alt_data
    class_prior: PASS-CANDIDATE | FAIL-DEFAULT | NEUTRAL
    class_prior_evidence: §1 taxonomy + sprint zinciri referansı
    expected_n: <hesaplama>
    counter_hypothesis: <spesifik H_anti>
    ```

12. **Short variant default test (asymmetric edge, §4.6)**.
    - Crypto'da SHORT 1.66x edge → yeni strateji long-only mu yoksa short variant'ı da emit ediyor mu?
    - Long-only ise asymmetric DD breaker (long_dd=0.15, short_dd=0.05) ile **uyumlu** olmalı.
    - F&G ≤20 short-skip + funding both-side filter zaten production'da — yeni strateji bu filter'lara binmeli (skip eden günleri tanıyıp emit etmeyecek).

---

## §6 Open Questions (PA Mastery Hâlâ İnceleyici)

Pre-reg yazılı ama henüz backtest çalıştırılmamış / forensik yan-bulgu adayları. Her birinin priority puanı (1-5): **kanıt-base × prior × deliverability**.

| # | Hipotez | Class | Pre-reg | Kanıt-base | Prior | Deliverability | Priority |
|---|---|---|---|---:|---:|---:|---:|
| Q1 | **Wyckoff Phase D LPS Entry** (Spring + SOS + LPS, 1D crypto) | structural | `2026-05-08-wyckoff-phase-d-spring-sos-lps.md` | 5 (wyckoff_phase_d production'da mR +0.511 — LPS pre-reg deeper variant) | 5 (structural class %60 prior + production yakın) | 4 (vectorize orta-kompleks, swing pivot tracking) | **4.7** ⭐ TOP |
| Q2 | **ICT Order Block + Liquidity Grab** (1D crypto) | structural | `2026-05-08-smc-ob-liquidity-grab-1d-crypto.md` | 4 (equal_highs_sweep production'da, smc_orderblock standalone PASS — kombinasyon farklı) | 4 (structural prior + microstructure-flavor crypto-fit) | 3 (vectorize kompleks BOS tracking) | **3.7** ⭐ |
| Q3 | **S/R Flip Retest After Structural Break** (1D crypto short) | structural | `2026-05-08-sr-flip-retest-structural-break-1d.md` | 4 (failed_bo_bos_reclaim PASS-STANDALONE — yakın akraba) | 4 (structural short-bias §4.6 ile uyumlu) | 4 (vectorize orta) | **4.0** ⭐ |
| Q4 | **Adam Grimes ABC Two-Leg Pullback** (1D, brooks_h2_l2 deeper variant) | trend_cont | `2026-05-14-grimes-abc-two-leg-pullback.md` SEC25 backlog | 4 (brooks_h2_l2 production OMURGA — ABC deeper) | 4 (trend_cont prior + crypto-fit pozitif SEC25 paralel) | 3 (vectorize kompleks 3-swing pivot tracking + Fib) | **3.7** |
| Q5 | **Adam Grimes Failure Test** (false break + reclaim at swing) | mean_rev | `2026-05-14-grimes-failure-test.md` SEC24 | 3 (Wyckoff spring vektörize eşdeğeri — wyckoff_phase_d production'da) | 3 (mean-rev family genel FAIL ama yapısal structural-mean-rev microstructure-flavor) | 4 (vectorize basit-orta) | **3.3** |
| Q6 | **Vol-z Spike Fade** (ATR-z > 2.5 single-bar excursion mean-revert) | mean_rev | `2026-05-14-vol-z-spike-fade.md` SEC24 | 2 (Engle GARCH lit. akademik; ama bb_extreme RED ile yakın retry argümanı zayıf) | 2 (mean-rev class %15-25 + crypto continuation karşı-kanıt) | 5 (vectorize basit) | **3.0** — düşük |
| Q7 | **CME Weekend Gap Fade** (BTC/ETH spot proxy Monday open vs Friday close) | mean_rev | `2026-05-14-cme-gap-fade-btc-eth.md` | 3 (CME gap fill rate 77% akademik destek; n borderline 240 trade) | 3 (mean-rev class düşük ama microstructure-flavor mekanizmasi) | 5 (vectorize basit, sadece BTC/ETH) | **3.7** |
| Q8 | **Alt-data 4 strateji reaktive** (funding_mean_rev, liquidation_fade, btc_eth_pairs, onchain_signals) | alt-data | SEC5 manifest gap | 4 (Data Engineer SEC25 ingest hazır — funding/OI feed mevcut) | 4 (alt-data filter güçlü; signal generator'a evolve etme potansiyel) | 3 (signal generator vs filter mantığı yeniden dizayn) | **3.7** |
| Q9 | **Conservative LP V3 Manifest** (alt5+BTC sub-universe, yıllık +%77 / DD -%18 / r-adj 4.196) | preset variant | SEC27 yan-bulgu | 5 (SEC27 zaten test edildi, r-adj +1.17 CI [+0.85, +1.49] kanıtlı) | 4 (mutlak hedef BALANCED ile uyumsuz, risk-averse LP utility'de cazip) | 2 (Lab strategic discussion + preset variant level, production manifest değil) | **3.7** — Lab kararı |
| Q10 | **HYP-D2 SOW v2 (Regime-Conditional Short)** | trend_cont (short) | SEC25 v2 backlog | 4 (OOS post-hoc mR +0.533, 11/11 sym pozitif, AVAX-bağımsız) | 3 (single-bar selection-bias-prone; regime-conditional variant yeni hipotez) | 3 (3y rolling WF + universe extend + EMA200 filter + halving stratify) | **3.3** |

**Top 3 sıralama (kanıt × prior × deliverability):**
1. **Q1 — Wyckoff Phase D LPS Entry** (4.7) — production yakın deeper variant, structural class, kanıt base 5/5
2. **Q3 — S/R Flip Retest After Structural Break** (4.0) — failed_bo_bos_reclaim yakın akraba + asymmetric short edge
3. **Q2 — ICT OB + Liquidity Grab / Q4 — Grimes ABC / Q7 — CME Gap Fade / Q8 — Alt-data reactive / Q9 — Conservative LP V3** (3.7 tie)

> **Stratejik öneri:** Q1 (Wyckoff LPS) ve Q3 (S/R Flip) priority 4+'da kümeleniyor. İkisi de **structural class** ve production yakın akraba — yeni hipotezde sprint paralleletilebilir. Q9 (Conservative LP V3) Lab tournament strategic discussion'a paralel.

---

## §7 Bibliyografya + Kanonik Kaynaklar

### §7.1 Brooks Trilogy + 10-Best Patterns

- Al Brooks — *Reading Price Charts Bar by Bar* (Wiley 2009)
- Al Brooks — *Trading Price Action TRENDS / REVERSALS / RANGES* (Wiley 2012, 3-volume)
- Brooks Trading Course — [10 Best Price Action Trading Patterns](https://www.brookstradingcourse.com/price-action/10-best-price-action-trading-patterns/)
  - H2/L2 (Ch.5 TRENDS), Brooks failed breakout (Ch.10 REVERSALS), 3-push wedge (Ch.5 TRENDS), Double Bottom Bull Flag (10-best #4), Channel line third touch reversal, Climactic reversal (Ch.4 REVERSALS)

### §7.2 Bob Volman

- Bob Volman — *Forex Price Action Scalping* (Light Tower Publishing 2011)
- Bob Volman — *Understanding Price Action* (Light Tower Publishing 2014)
  - Pin bar round numbers, Double Doji Break (DD), Block Break (BB) — 70-tick SCOPE_OUT for 1d

### §7.3 Adam Grimes

- Adam Grimes — *The Art and Science of Technical Analysis* (Wiley 2012)
- [adamhgrimes.com — Failure Test](https://www.adamhgrimes.com/failure-test-2/)
- [adamhgrimes.com — How to Trade Pullbacks](https://www.adamhgrimes.com/trade-pullbacks/)
  - Failure Test (Wyckoff spring vektörize), Two-legged pullback ABC, Complex consolidation breakout multi-contraction

### §7.4 Tom Dante

- Tom Dante — Twitter [@Trader_Dante](https://x.com/Trader_Dante)
  - [Inside Day Failure](https://x.com/Trader_Dante/status/1045012059627442176) — IDF (production-aday SEC19 V3 PASS-STANDALONE)
  - [Swing Failure Pattern original](https://x.com/Trader_Dante/status/1541724360519680002) — SFP swing-level

### §7.5 Wyckoff / Evans / VSA / Williams

- Richard Wyckoff (1931) — *The Wyckoff Method* (Phase A/B/C/D analysis)
- Hank Pruden / Henry Pruden / David Weis — *The Three Skills of Top Trading* (Wiley 2007)
- Tom Williams — *Master the Markets* (VSA) — knowledge/books/vsa_volume_spread_analysis.md, Ch.4 climax test
- Anna Coulling — *A Complete Guide to Volume Price Analysis*
- [Wyckoff Analytics — Wyckoff Method](https://www.wyckoffanalytics.com/wyckoff-method/)
- [Last Point of Supply (LPSY): Wyckoff Entry Guide — Aron Groups](https://arongroups.co/forex-articles/wyckoff-entry-guide/)
  - Phase D Spring + SOS + LPS (production wyckoff_phase_d), UTAD (NOT_TESTED), LPSY (NOT_TESTED), VSA climax test (production)

### §7.6 Lance Beggs (YTC)

- Lance Beggs — *YTC Price Action Trader* (studylib.net/YTC-PAT)
- [Trapped Trader Strategy — Lance Beggs YTC](https://studylib.net/doc/28032923/trapped-traders--lance-beggs---ytc-)
  - Trapped Trader (NOT_TESTED, Brooks failed_breakout %80 overlap)

### §7.7 Thomas Bulkowski

- Thomas Bulkowski — *Encyclopedia of Chart Patterns* 2nd ed. (Wiley 2005)
- [Bulkowski on High and Tight Flags](https://thepatternsite.com/htf.html)
  - High-Tight Flag rank #1 (SEC19+SEC22 RED kalıcı archive), Pin bar pattern (production), Engulfing (production)

### §7.8 Linda Raschke + Larry Connors

- Linda Raschke & Larry Connors — *Street Smarts: High Probability Short-Term Trading Strategies* (M. Gordon Publishing 1996)
- [Turtle Soup — Traders Mastermind](https://tradersmastermind.com/turtle-soup-trading-strategy-rules/)
- [New Trader U — Turtle Soup Rules](https://www.newtraderu.com/2021/06/05/the-turtle-soup-stock-trading-strategy/)
  - Turtle Soup (TESTED-HARD-RED SEC24), RSI(2) extreme fade (TESTED-ARCHIVE SEC22+23), "80/20" bar (NOT_TESTED)

### §7.9 Larry Connors

- Larry Connors & Cesar Alvarez — *Short Term Trading Strategies That Work* (TradingMarkets 2009) — RSI(2)
- Larry Connors — *How Markets Really Work*
- [QuantifiedStrategies — RSI Trading Strategy](https://www.quantifiedstrategies.com/rsi-trading-strategy/)

### §7.10 Mark Minervini + William O'Neil

- Mark Minervini — *Trade Like a Stock Market Wizard* (McGraw-Hill 2013) — VCP
- William O'Neil — *How to Make Money in Stocks* — High-Tight Flag origin
- [Mastering the Volatility Contraction Pattern — TraderLion](https://traderlion.com/technical-analysis/volatility-contraction-pattern/)
- [High Tight Flag Chart Pattern — TraderLion](https://traderlion.com/technical-analysis/high-tight-flag-pattern/)
  - VCP (NOT_TESTED, NR7 mean-rev paralel ama trend-cont breakout-conditional), HTF (TESTED-ARCHIVE)

### §7.11 Toby Crabel

- Toby Crabel — *Day Trading with Short Term Price Patterns and Opening Range Breakout* (Traders Press 1990)
- [Narrow Range 4, 7, and Inside Days — Toby Crabel](https://time-price-research-astrofin.blogspot.com/2023/09/nr4-nr7-narrow-range-4-7-id-inside-days.html)
- [NR7ID Powerful Double-Compression Setup](https://tradingstrategiesdaily.com/p/nr7id-toby-crabel)
  - NR4/NR7 (TESTED-RED 2x), ID/NR4 kombosu (NOT_TESTED)

### §7.12 ICT / SMC (Inner Circle Trader / Smart Money Concepts)

- Michael J. Huddleston (ICT) — innercircletrader.net + knowledge/books/smc.md
- [ICT Breaker Block Trading](https://innercircletrader.net/tutorials/ict-breaker-block-trading/)
- [ICT Mitigation Block Explained](https://innercircletrader.net/tutorials/ict-mitigation-block-explained/)
  - Order Block (TESTED-PASS-STANDALONE smc_orderblock), Fair Value Gap (PRODUCTION OMURGA fvg_fill_reversal), Liquidity Sweep / Equal Highs Sweep (PRODUCTION), Breaker Block (NOT_TESTED), Mitigation Block (NOT_TESTED), PO3 (SCOPE_OUT intraday), Quasimodo (TESTED-ARCHIVE artifact)

### §7.13 Harmonic / Volume Profile / Anchored VWAP

- Scott Carney — *Harmonic Trading Vol I & II* (Gartley, Three Drives)
- Peter Steidlmayer — Market Profile / Volume Profile
- Brian Shannon — Anchored VWAP
- Larry Harris — *Trading and Exchanges* (2003)
  - Three Drives (NOT_TESTED rare), TPO Value Area (PASS-STANDALONE), Anchored VWAP reversal (PRODUCTION marjinal)

### §7.14 Quantitative / Akademik

- Joseph Granville — *New Strategy of Daily Stock Market Timing for Maximum Profit* (1976) — OBV
- Robert F. Engle (1982) — [ARCH](https://www.jstor.org/stable/1912773)
- Tim Bollerslev (1986) — [Generalized ARCH](https://doi.org/10.1016/0304-4076(86)90063-1)
- Dobrynskaya — [Cryptocurrency Momentum and Reversal](https://conference.hse.ru/files/download_file_ex?hash=FAE0AB2DC7A67656E89A0B1CB27D8C7D&id=3B5EE9A5-0B18-458A-9458-B4ED0F6C6664) (SSRN)
- [QuantPedia — Trend-following and Mean-reversion Strategies in Bitcoin](https://quantpedia.com/revisiting-trend-following-and-mean-reversion-strategies-in-bitcoin/)
- [Phemex — CME Gap Crypto Explained](https://phemex.com/academy/cme-futures-gap) — 77% fill rate within 1 week
- [Whaleportal — Bitcoin CME Gaps Strategy](https://whaleportal.com/blog/bitcoin-cme-gaps-and-cme-trading-strategy-explained/)

### §7.15 Repo Internal Knowledge Base

- `knowledge/books/smc.md` — SMC/ICT integrated reference (FVG, OB, BOS, CHOCH, liquidity)
- `knowledge/books/wyckoff_method.md` — Phase A/B/C/D/E + Spring + SOS + LPS
- `knowledge/books/vsa_volume_spread_analysis.md` — VSA 10 mechanical patterns
- `knowledge/books/volume_price_divergence.md` — OBV + CVD + divergence taxonomy

---

## §8 Sprint Zinciri Kronolojisi (Hızlı Referans)

Bu Encyclopedia'nın temel aldığı sprint kanıt zinciri (2026-05-08 → 2026-05-15):

| Sprint | Tema | Sonuç | Production etki |
|---|---|---|---|
| Pre-SEC4 (v0.9.7) | BALANCED + funding + F&G + halt | yıllık +%33.6 / DD -%33 / r-adj 1.029 | v1.1 Champion |
| SEC4 | Yeni strategy class survey | RED (4 standalone PASS ensemble null) | Lokal optimum 1. teyit |
| SEC5 | Manifest gap inceleme | RED (4 alt-data zero-trade) | Lokal optimum 2. teyit |
| SEC6 | 4h primary timeframe pivot | RED (yıllık +%14.4 vs 1d +%33.6) | Lokal optimum 3. teyit |
| SEC10 | Recent regime guard DD breaker grid | WIN (monthly_dd 0.15→0.08 +%4pp) | v1.1 |
| SEC11 | Parallel agent sprint | WIN (FVG +%8.7 + tp2_R 2.0→1.5) | v1.2 (+%51 / DD -%34) |
| SEC11e | FVG WIN + LiqSweep RED + NR7 RED | FVG WIN | v1.2 production |
| SEC12 | DD breaker further sweep | WIN (monthly 0.08→0.06, halt 30→21g) | v1.3 (+%60 / r-adj 1.802) |
| SEC13.2 | Yeni signal naked_poc + vol_expansion | NET 0 (slot bottleneck) | — |
| SEC13.3 | 20-sym universe genişletme | RED (-%51pp dilution) | Lokal optimum 4. teyit |
| SEC13.4 | Engine force-exit A6 | WIN | v1.5 |
| SEC14.0 | Slot bottleneck fix mc 8→12 | WIN (+%7.6pp) | v1.4 |
| SEC14.1 | Side-conditional DD long/short ayrı | WIN (+%48.5pp HIBRIT) | v1.5 (+%116 / DD -%35) |
| SEC15.2 | 3 yeni signal v3 | RED ensemble (standalone 2/3 PASS) | Slot bottleneck onayı |
| SEC15.6 | Pure side-cond mdd | WIN ama HIBRIT tercih | v2.0 (+%242 SIM=HONEST_BE) |
| SEC16 | QA + CEO review + look-ahead fix | -%2.7pp | v2.0.3 (+%239.5) |
| SEC19 | 3 yeni strategy (HTF/IDF/QM) standalone | RED ensemble | Production değişiklik YOK |
| SEC20 | Live wiring (`_job_execute_orders`) | PASS 29/29 test | Production live-ready |
| SEC21 | Engine engineering (slot allocation, force_exit_from_entry) | RED | Slot bottleneck refutation |
| SEC22 | Mean-rev class pre-build (3 yeni strateji) | RED 3/3 (BB, RSI2, three-push) | Mean-rev family RED prior 1. teyit |
| SEC23 | RSI2 OOS validation | RED (selection-bias forensik) | Mean-rev family RED 2. teyit |
| SEC24 | Turtle Soup standalone + PA mastery gap | HARD RED | Mean-rev RED 3. teyit + asset-class transfer bias |
| SEC25 | Brooks DB Bull Flag + Volume micro (D1-D4) | RED 5/5 (DB n bottleneck + D1-D4 RED) | Hacim lokal optimum 5. teyit |
| SEC26 | Production winner forensic | POZITIF (9 hipotez ölçüldü) | `pattern_crypto_winner_anatomy.md` |
| SEC27 | Alt-coin sub-portfolio | REJECT (conservative LP yan-bulgu) | Universe optimum 5. teyit |

**Genel istatistik (SEC4 → SEC27, 24 sprint):**
- WIN sprint (production değiştiren): 7 (SEC10, SEC11, SEC11e, SEC12, SEC13.4, SEC14.0, SEC14.1)
- RED sprint (production değiştirmeyen ama bilgi kazandıran): 14
- POZITIF (forensik): 1 (SEC26)
- Live wiring: 2 (SEC20, SEC26.B)

**Win rate**: %29 — sağlıklı. Robust strateji geliştirmek için **çoğunluk hipotezin RED gelmesi normal** (researcher SOP).

---

## §9 Reproducibility + Maintenance

### §9.1 Bu Encyclopedia'nın Kaynak Dosyaları

- `memory/researcher/pattern_crypto_winner_anatomy.md` — SEC26 forensik kalıcı meta-memory (9 hipotez sayısal kanıt)
- `memory/researcher/learning_2026{0512..0515}_*.md` — Sprint postmortem'leri (alt_data_filters, sec22_mean_rev_prebuild, sec24_turtle_soup, sec25_brooks_db, sec25_volume_microstructure, sec26_winner_forensic, sec27_alt_coin_reject)
- `reports/researcher/2026-05-14_pa_mastery_gap.md` — 56-setup envanter tablosu (gap analizi)
- `reports/researcher/2026-05-14_pa_literature_scan.md` — 30 setup adayı (literatür tarama)
- `reports/researcher/2026-05-14_sec26_production_winner_forensic.md` — Ana forensik raporu
- `reports/researcher/sec26_per_strategy_breakdown.csv` — Per-strategy WR/R metrikleri
- `reports/researcher/sec26_regime_breakdown.csv` — Per-regime breakdown
- `reports/researcher/sec27_variants_metrics.csv` — Sub-universe WF replay sonuçları
- `reports/researcher/2026-05-{14,15}_sec{22,24,25,26,27}_*.md` — Sprint summary'ler
- `reports/ceo/2026-05-14_master_plan_post_sec23.md` — Cross-track CEO master plan
- `memory/researcher/hypotheses/` — 40+ pre-registered hipotez dosyası

### §9.2 Maintenance Protocol

Bu Encyclopedia **kalıcı meta-memory**. Güncellenmesi:
- Yeni production strateji eklenirse §2.1 hierarchy + §2.4 engine config tablosuna ekle
- Yeni sprint sonucu pattern class prior'ı (§1) değiştirirse §4 meta-bulgu güncellenir
- Yeni open question pre-reg yazılırsa §6 tablosuna eklenir (priority hesabıyla)
- Sprint zinciri uzarsa §8 kronolojisi 1 satır pointer ile genişletilir

**Major rewrite trigger:** Production champion'da +%20pp uplift (yıllık return) veya class prior fundamental shift (örn. ML hattı reaktive olursa, regime ML PASS gelirse).

### §9.3 Çelişki Çözüm Protokolü

Bu Encyclopedia ile alt-memory dosyaları arasında çelişki olursa:
- Sayısal veri için `reports/researcher/sec26_*.csv` + `reports/researcher/*_summary.md` BU dokümana üstün
- Pattern class prior için `pattern_crypto_winner_anatomy.md` + bu Encyclopedia birlikte
- Production config için `configs/risk_balanced.yaml` (canonical) > bu Encyclopedia

---

> **Son söz:** Bu doküman 28-sprint zincir kanıtının distilasyonu. Yeni hipotez yazan herkes okuduğunda: "Crypto 1d × 11-sym evrende neyin neden çalıştığını ve neyin neden çalışmadığını biliyorum. Sıradaki hipotezimi tasarlarken bu çerçeveyi kullanırım." Bu pre-screening prior'ları size %15-25 PASS prior class'larda BACKTEST ÇALIŞTIRMADAN red'i öngörmenizi sağlar — zaman+token tasarrufu + selection-bias guard.
