# Pattern Crypto Winner Anatomy — Production Edge'in Yapisal Kaynaklari

**Tarih:** 2026-05-14
**Sprint:** SEC26 — Production Winner Forensic
**Pool:** TOP_10 + FVG (v1.2 / v2.0.3 baseline), n=6650 trade, 5y x 11 sym, 1d
**Kaynak rapor:** [reports/researcher/2026-05-14_sec26_production_winner_forensic.md](../../reports/researcher/2026-05-14_sec26_production_winner_forensic.md)

Bu kalici meta-memory: 10+ RED sprint'in NEDEN'lerini belgeledikten sonra (`pattern_crypto_mean_rev_continuation.md`, `learning_compound_pattern_bottleneck.md`, vb), 1 PRODUCTION'ın *NEDEN*'i. Gelecekteki researcher (insan/AI) bu dosyayi okuduğunda "production crypto trend-cont edge'inin mikroyapısal kaynakları" mental modelini kazansin.

---

## TL;DR — 9 Hipotez, Hepsi Sayilarla Destekli

| # | Hipotez | Olcum | Sonuc |
|---|---|---|---|
| H1 | Right-tail fat tails edge'i tasiyor | Top 10% trade = sumR'in **%154**'u | KANITLI (extreme power-law) |
| H2 | SHORT edge LONG'tan baskin | short mR +0.247 / long mR +0.149 = **1.66x** | KANITLI (SEC12 ile parite) |
| H3 | Alt-coin'lerde edge 3-4x BTC'den buyuk | DOT/ADA/SOL/AVAX/MATIC avg mR +0.335 vs BTC +0.104 = **3.22x** | KANITLI |
| H4 | Sequential dependency var (cool-down justified) | delta_WR (after_win - after_loss) = **+13.9pp** | KANITLI |
| H5 | High-vol regime edge'i besleniyor | high_vol mR +0.269 / low_vol +0.159 = **1.69x** | KANITLI |
| H6 | BTC<EMA50 mR > BTC>EMA50 mR (counter-intuitive) | below +0.239 / above +0.172 (delta +0.067) | KANITLI |
| H7 | Production pool yapisal olarak orthogonal | Max jaccard < 0.08, median ~0.01 | KANITLI |
| H8 | Mean-rev'in tek skalable carrier'i FVG | FVG sumR +267 (mean-rev class'in **%69**'u) | KANITLI |
| H9 | Brooks trap mekanizmasi crypto'da equity'den guclu | brooks_failed_bo sumR +370 (pool'un **%27**'si) | KANITLI |

---

## 1. Production Pool Envanteri (Class Distribution)

11 strateji, 3 class. Trade kontribusyonu:

| Class | n_strats | n_trades | trade_share | mean_mR | sumR |
|---|---:|---:|---:|---:|---:|
| trend_continuation | 5 | 3267 | 49.1% | +0.255 | **+834.6** |
| mean_reversion | 4 | 2934 | 44.1% | +0.133 | +388.9 |
| structural | 2 | 449 | 6.8% | +0.298 | +133.7 |

**Yapısal gozlem:** Class CONCENTRATION pool'da homogen değil — trend_continuation **trade sayisinda hakim** (49.1%), mean_reversion **edge yogunluk olarak düşük** (mR 0.133). Structural sınıfı (Wyckoff + EQH sweep) **rare ama yüksek mR** (0.298, 2x trend_cont). Bu **edge concentration hierarchy** crypto-spesifik:

- **trend_continuation = volume edge** (sik trigger, orta mR, kazananlardan yaşar)
- **structural = high-conviction edge** (nadir trigger, buyuk mR, fat-tail yakalar)
- **mean_reversion = uncorrelated edge** (orta volum, dusuk mR, **pool'a diversifikasyon ekliyor**, sec11e FVG +%8.7 yillik)

---

## 2. Per-Strategy Edge Hierarchy (sumR'a gore)

| Rank | Strategy | n | mR_raw | sumR | Class | Edge tipi |
|---:|---|---:|---:|---:|---|---|
| 1 | brooks_failed_breakout | 1545 | +0.240 | +370.4 | trend_cont | Trap mekanizmasi (en buyuk sumR kaynagi) |
| 2 | fvg_fill_reversal | 1863 | +0.144 | +267.3 | mean_rev | Microstructure gap reclaim |
| 3 | brooks_h2_l2 | 816 | +0.238 | +194.4 | trend_cont | Two-legged pullback continuation |
| 4 | engulfing_continuation | 350 | +0.463 | +161.9 | trend_cont | Klasik engulfing + always-in |
| 5 | wyckoff_phase_d | 170 | +0.511 | +86.9 | structural | Smart-money accumulation pivot |
| 6 | obv_engulfing_confluence | 167 | +0.423 | +70.7 | trend_cont | Volume divergence + engulfing |
| 7 | anchored_vwap_reversal | 948 | +0.073 | +69.3 | mean_rev | AVWAP+POC mean-rev (marjinal) |
| 8 | equal_highs_sweep | 279 | +0.168 | +46.8 | structural | SMC liquidity grab |
| 9 | vsa_climax_test | 30 | +1.257 | +37.7 | mean_rev | RARE ama POWERFUL (n=30) |
| 10 | pin_bar_round_numbers | 389 | +0.096 | +37.2 | trend_cont | Round number magnet (marjinal) |
| 11 | cvd_spike_fade | 93 | +0.157 | +14.6 | mean_rev | OBV z-score fade (marjinal) |

**3 strateji (Brooks failed BO + FVG + Brooks H2L2) pool sumR'in %61'ini uretiyor.** Bunlar TOP_10+FVG ensemble'in OMURGA stratejileri.

---

## 3. Crypto Microstructure WHY — Yapisal Sentez

### Mekanizma #1: Leverage Cascade → Right-Tail Fat Tails

**Olcum:** Top 10% trade'ler (n=665) sumR'in **%154**'unu uretiyor. Bot 10% sumR'in **-%52**'sini, mid 80% sadece **-%3** (≈noise). Bu **extreme power-law** distribution.

**Anlamı:** Edge **sayıca** değil **magnitude'ce** geliyor. Sistemin hayatta kalması "küçük kayıpları aşmak" değil, **"buyuk kazananı kaçırmamak"** odaklı olmali.

**Engine implication:**
- `tp1_R=1.0, tp2_R=1.5, runner_trail_mult=1.0, time_exit=30bar` (v1.5 stack) tam bu fat-tail'i yakalamak icin.
- SEC11a A artifact (mult=2.0, no force-exit) fantasy R uretti (max R=657!) — runner'i sermayeye bağlamadan kaçıran trade.
- SEC13.4 A6 force-exit'in cozmesi: max R=15.7 (gercek), trade kapanıyor, sermaye yeniden döneme giriyor.

**Crypto mikrokaynak:** BTC %5 yükselişte → futures funding pozitif → arbitrage long → likidasyon havuzu daralma → trapped shortlar coverleniyor → %5 → %15-25. Equity'de S&P trend-follower'lar (Trout, Dunn — Covel 2007) benzer pattern gosterir ama crypto'da magnitude **>2x** daha sert (equity top decile katki ~30-40%, crypto ~%154).

### Mekanizma #2: Asymmetric SHORT Edge (1.66x) — Counter-Intuitive

**Olcum (regime x side breakdown):**

| Regime | LONG mR | SHORT mR | SHORT/LONG |
|---|---:|---:|---:|
| bull | +0.198 | +0.196 | 0.99x |
| bear | +0.113 | +0.214 | 1.89x |
| range | +0.053 | +0.245 | **4.62x** |

**Sürpriz:** SHORT edge en güçlü RANGE rejiminde (4.62x), bull'da değil. **Mekanik:** range tepelerinde short'lar likidasyon riskine giriyor → sıkışan retail → counter-trend short edge'i besleniyor. equal_highs_sweep, brooks_failed_breakout pattern'leri bu mekanizmayi tasiyor.

**Production'a yansıma:**
- SEC15.6 PURE side-cond mdd (long_dd=0.15, short_dd=0.05) bu bulguya tam uyumlu — short trade'leri sıkı stop, long trade'lere alan ver.
- v0.9.7 F&G ≤20 short-skip ekstrem-fear bottoming filtresi — losing-tail short'ları engelliyor, big-winner short universe temiz kalıyor.

### Mekanizma #3: Alt-Coin Edge 3-4x BTC

**Olcum:**

| Sym | mR | sumR | n |
|---|---:|---:|---:|
| DOT | +0.378 | +239.3 | 633 |
| ADA | +0.363 | +231.3 | 637 |
| SOL | +0.339 | +206.9 | 611 |
| AVAX | +0.265 | +157.4 | 595 |
| MATIC | +0.328 | +129.3 | 394 |
| **alt avg** | **+0.335** | | |
| BTC | +0.104 | +68.8 | 662 |
| ETH | +0.113 | +76.6 | 678 |

**alt mR / BTC mR = 3.22x**.

**Mekanik:** BTC/ETH deep liquidity + tight spread = pattern degisikligi az, edge sıkıştırılmış. Alt-coin'lerde likidite parcalı + retail-driven + leverage'a daha hızlı reaksiyon → fat-tail hareketler daha sık. Aynı pattern (engulfing, FVG, Brooks) **alt-coin'lerde 2-3x daha karli mR/trade**.

**Production'a yansıma:**
- concentration_max_per_symbol_pct=0.20 + max_concurrent=12 bu alt-coin dispersyonunu portfolyo riskine cevirmeden yakalamak için tasarlanmis.
- SEC13.3 (20-sym universe) RED'i tam burada bulunan optimumu konfirme etti: yeni alt-coin'ler standalone POZITIF ama portfolyo'ya seyreltici etki (mc-12 doyumlu).

### Mekanizma #4: Sequential Dependency (Markov-1 Clustering)

**Olcum:** Base WR %50.9.
- After WIN: WR %57.6 (mR +0.371)
- After LOSS: WR %43.7 (mR +0.005)
- **delta_WR = +13.9pp**

**Anlamı:** Trade outcome'lari clustered — kazananlardan sonra %57.6 WR. Mekanik: regime/vol-cluster effect. Yuksek-vol gunlerde trade'ler ardısık trigger → seri kazanan/seri kayipli zincir.

**Production'a yansıma:** `consecutive_losses=3 → 5gun cool-down` (v0.9.1) bu mekanizmanin matematiksel korumasi. 5gun sırasında regime degisiyor → reset → fresh sample.

### Mekanizma #5: High-Vol Edge (Counter-Conventional)

**Olcum (BTC ATR% tercile):**

| Vol regime | n | WR | mR | sumR |
|---|---:|---:|---:|---:|
| low_vol | 2130 | 49.9% | +0.159 | +338.2 |
| mid_vol | 2294 | 50.5% | +0.183 | +420.7 |
| **high_vol** | 2226 | **52.2%** | **+0.269** | **+598.4** |

**high_vol mR / low_vol = 1.69x**. Bu **counter-conventional** — geleneksel risk management high-vol'da position küçültmeyi onerir. Crypto'da tersi: **high_vol = trend cascade aktif = trend_continuation edge besleniyor + brooks_failed_breakout trap daha sık trigger**.

**AMA dikkat:** Analyst HYP-capitulation-halt (ATR%≥6 + EMA200 streak + 90d-DD≤-25%) **EKSTREM** high-vol'da halt yapar. Yani "high-vol iyi" doğru ama LUNA/FTX-tier ekstrem high-vol toxic. Bu nuanced relationship Analyst sprint'in production'a kattıği değer.

### Mekanizma #6: BTC<EMA50 Counter-Intuitive Edge

**Olcum:** BTC>EMA50 mR +0.172 (n=3498), BTC<EMA50 mR +0.239 (n=3152). delta = +0.067.

**Yorum:** Naive intuition "BTC trend with -> long bias kazanır" — yanlış. Pool'un short asymmetry'siyle uyumlu: BTC<EMA50 = bear/range = SHORT edge baskın = sumR yüksek.

**Yan-bulgu:** Production'da BTC<EMA50 HARD filter eklemenin **alpha eklemeyecegi** beklenti — pool zaten strateji-içi trend filter'lar ile dolaylı olarak balanced. Yine de OOS pre-reg test backlog adayı.

### Mekanizma #7: Setup Orthogonality — Pool Yapisal Olarak Sağlam

**Olcum:** Tum 55 strateji çiftinin jaccard co-occurrence (aynı gün + sym'de birlikte trigger) < 0.08. Max: brooks_failed_breakout × fvg_fill_reversal = 0.076. Median: ~0.01.

**Anlamı:** Pool **yapisal olarak orthogonal**. Bu redundancy kontrolu sec11e LiquiditySweep RED'in niye `priority-out` olduğunu açıklıyor: TOP_10 slot'lar zaten doluyor → yeni overlapping signal = +0pp marjinal. Slot bottleneck (sec14.0 max_concurrent 8→12) ancak orthogonality var olunca konsisten yarar sağlar.

### Mekanizma #8: Mean-Rev'in Tek Skalable Carrier'i FVG

**Olcum:** mean_reversion class (4 strateji) sumR dağılımı:
- fvg_fill_reversal: **+267.3** (class'in %69'u, n=1863) — DOMINANT
- anchored_vwap_reversal: +69.3 (n=948) — MARJINAL
- vsa_climax_test: +37.7 (n=30) — RARE/POWERFUL
- cvd_spike_fade: +14.6 (n=93) — MARJINAL

**Mekanik:** Crypto'da klasik "extreme RSI/Bollinger fade" pattern'leri **işlemiyor**. SEC22 zincir RED'leri kanıt: bb_extreme_reversal HARD RED (+2.5σ CONTINUATION, not fade), rsi2_extreme_fade MARGINAL, three_push CONDITIONAL, htf_retest hepsi RED.

**FVG farklı:** order-flow gap → reclaim, exchange-agnostic 3-bar imbalance. **Microstructure inefficiency** mekanizmasi, **klasik mean-rev** değil. Bu yüzden sec11e WF'da +%8.7 yıllık ekledi, özellikle alt-coin'lerde (ADA mR +0.59, XRP +0.47).

**Yapısal sonuç:** "Mean-rev crypto'da olmaz" yanlış. "Klasik istatistiksel mean-rev olmaz; mikroyapısal gap-fill mean-rev olur" doğru.

### Mekanizma #9: Brooks Trap Mekanizmasi Crypto'da Equity'den Guçlu

**Olcum:** brooks_failed_breakout sumR +370.4 (n=1545, mR +0.240) — pool'un **EN BUYUK sumR** kaynağı (%27.3 katkı).

**Mekanik:** N-bar BO + 1-3 bar reclaim → trapped retail + reversal oyuncular. Brooks "her piyasada calisir" demis (Trading Price Action TRENDS Ch.10), crypto'da DOZ daha güçlü çünkü:
1. **Leverage seviyesi yüksek** (5x-100x retail) → trap kaybi liquidation'a hızla çevriliyor
2. **24/7 piyasa** → trap mekanizmasi geceyi/hafta sonunu kullanıp cascade
3. **Funding cycle 8h** → trapped pozisyon funding-cost karsı çalısıyor → exit baskı

Bu **crypto-spesifik edge amplification**.

---

## 4. Hold-Days / Edge Density Hierarchy

| Strategy | hold_median | Edge tipi |
|---|---:|---|
| cvd_spike_fade | 3.0d | Hızlı reversal (1-3 gun) |
| pin_bar_round_numbers | 4.0d | Pin bar reversal |
| brooks_h2_l2 | 4.0d | Two-legged continuation |
| fvg_fill_reversal | 4.0d | Gap fill |
| equal_highs_sweep | 5.0d | Liquidity grab |
| brooks_failed_breakout | 9.0d | Trap reversal |
| obv_engulfing_confluence | 12.0d | Volume divergence |
| engulfing_continuation | 13.0d | Klasik continuation |
| anchored_vwap_reversal | 14.0d | AVWAP mean-rev |
| wyckoff_phase_d | 30.5d | Smart-money accumulation |
| vsa_climax_test | 32.5d | VSA phase A |

**Yapı:** Mean-rev/hızlı reversal = 3-9 gun. trend_continuation = 9-13 gun. Structural (Wyckoff + VSA climax) = 30+ gun.

**vsa_climax_test ozellikle dikkat:** %43.3'u 30 gun ustu hold, ama n=30 (RARE). Wyckoff phase_d benzer (%30.6 long-hold, mR +0.511). **Bu uzun-hold structural trade'ler sermayeyi bağlıyor ama right-tail karşılığını veriyor** — `time_exit=30bar` runner force-exit (v1.5) bu trade'leri opsiyonel olarak kesip sermayeyi recylce ediyor; per-strategy edge ile tradeoff.

---

## 5. Asset Class Transfer Bias — Pattern Selection Filtresi

SEC23/24/25 RED bulgularını entegre eder:
- "Equity pattern X crypto'da calisir mi?" sorusu **default: ya çalışmaz ya da invert eder**.
- Pre-screening kriteri: Pattern crypto microstructure (24/7, no overnight gap, retail leverage cascade, FVG order-flow imbalance) **ile uyumlu mu?**

**Çalışanlar (production):**
- Brooks failed BO/H2-L2 → trap + continuation cascade ile uyumlu
- Engulfing continuation/OBV confluence → trend persistence ile uyumlu
- Wyckoff Phase D / VSA climax → 24/7 accumulation/distribution cycle ile uyumlu (RARE)
- ICT FVG → exchange-agnostic gap reclaim → uyumlu (NEW, sec11e WIN)

**Çalışmayanlar (RED zincir):**
- Bollinger extreme reversal (SEC22) → +2.5σ crypto'da CONTINUATION, not fade
- HTF retest (Beggs SEC22) → crypto 1d yapısal yetersiz
- High-tight flag (O'Neil/Bulkowski SEC14) → n bottleneck (crypto consolidation rare)
- Turtle Soup (SEC24) → 20-day failed BO crypto'da continuation
- Inside-day failure (SEC14) → trend filter kombo edge'i bozuyor

---

## 6. Engine Discipline — Why Production Engine Settings Are Optimal

Forensik bulgular engine config kararlarini matematiksel olarak destekliyor:

| Engine param | Value | Forensik gerekçe |
|---|---|---|
| `tp1_R` | 1.0 | Sequential dependency (Markov-1 cluster) + 50% WR ortaminda early lock-in |
| `tp2_R` | 1.5 | SEC11b sweep: 2.0 fantasy R, 1.5 optimal (right-tail capture + realistic exit) |
| `runner_trail_mult` | 1.0 | Right-tail dominance: top 10% trades carries portfolio |
| `time_exit_bars` | 30 | SEC13.4 A6: artifact-free; long-hold trade'leri (>30d) kesip sermaye recycle |
| `trail_activate_stage` | 2 | Stage<2 force-exit guard (SEC11a/sec22 quasimodo artifact bulgusu) |
| `consecutive_losses` | 3→5d cool-down | Markov-1 delta_WR -13.9pp; cool-down regime reset |
| `max_concurrent` | 12 | Slot bottleneck WIN (sec14.0); orthogonal pool yararı yapısal |
| `max_per_symbol_pct` | 0.20 | Alt-coin dispersion **konsantrasyona** çevirmemek; 0.30 felaket (sec14.0) |
| `monthly_dd_long/short` | 0.15/0.05 | Asymmetric short edge → short trade'ler sıkı stop, long alanlı |
| `regime_filter.atr_pct>=6 + EMA200 streak + DD90<=-25` | halt | Ekstrem high-vol (LUNA/FTX) toxic — H5 ile uyumlu |
| `alt_data.fng_short_skip<=20` | true | F&G fear bottoming → losing-tail short engellenir |

---

## 6.5. Universe Size Optimum — SEC27 Test Sonucu (eklendi 2026-05-15)

**HYP-BACKLOG-003 (SEC26 tetikli) TEST EDİLDİ:**
- V1 alt5_only (SOL ADA DOT AVAX MATIC) → yıllık -%37.6pp (CI95 [-50.56, -27.13], p<0.0001) **REJECT**
- V2 alt7_plus_eth (BTC çıkarıldı) → -%20.8pp **REJECT**
- V3 alt5+BTC anchor → -%27.6pp **REJECT** (ama r-adj +1.17, DD -%18.4 — conservative LP profili)
- V4 top_volume_5 → -%75.0pp **REJECT**

**Mekanik:** Alt-coin mR boost (3.22x) **gerçek ama sumR yetersiz** çünkü n=2870 (V0 43%'i). Slot allocation universe size-aware değil (max_concurrent=12 sabit), 5-sym'de slot'lar yarı dolu. Pencere korelasyonu V0/V1 = +0.845 → V1 V0'ın deflated version'u, right-tail explosion (V0 max +169.3%) alt-only'de yakalanmıyor (V1 max +81.2%).

**H_anti sürprizi:** "Alt-only DD ağırlaşır" beklendi → DD %50 **iyileşti** (-34.5 → -16.8). Crypto'da alt-coin korelasyon clustering yüksek → 11-sym diversification benefit'i marjinal. BTC/ETH stress'te (LUNA/FTX) alt-coin'lerden DAHA HIZLI çakılıyor (V1 LUNA mR +0.969 vs V0 +0.465 = 2.08x stress-hedge).

**Yapısal optimum:** 11-sym BTC-anchor universe **mutlak return için lokal optimumda kilitli**. SEC13.3 (20-sym RED) + SEC27 (5-sym REJECT) zincir kanıt.

**Yan-bulgu (V3 conservative LP profile):** $10k → 5y compound: BALANCED $2.7M (DD -%34) vs V3 alt5+BTC $1.7M (DD -%18). Risk-averse LP utility'de cazip — pre-reg gate'i revize edilebilirse PASS olabilir.

---

## 7. Yan-Bulgu Pre-Reg Backlog (SEC26-Tetikli)

1. **HYP-BACKLOG-001**: BTC>EMA50 hard filter (entry-day) **alpha ekler mi?** Pool zaten balanced görünüyor (Section H6). Test: WF replay BTC>EMA50 trade-only subset vs ALL. Beklenti: marginal / negatif (zaten dolaylı filtreli).
2. **HYP-BACKLOG-002**: SHORT 1.66x edge'in kaynağı stress periodlarından mı geliyor? Test: 2022-05 (LUNA), 2022-11 (FTX), 2024-03 (BTC ATH reject), 2024-08 (Yen carry) **exclude** edip replay; SHORT/LONG ratio nasıl değişir? Stress-dışı subset'te ratio 1.0-1.2x'e dusersse edge'in fat-tail-driven olduğu kanıtlanır.
3. **HYP-BACKLOG-003**: Alt-coin (DOT/ADA/SOL/AVAX/MATIC) sub-portfolio özel filtre / sub-universe manifest hak ediyor mu? Bu coinler **avg mR +0.335** vs BTC +0.104 — özel risk_alt.yaml ile +50% sermaye taşıması test edilebilir.
4. **HYP-BACKLOG-004**: Sequential dependency (Markov-1) **3+ ardışık WIN'den sonra** (run-up regime) trade kalitesi azalır mı? Eğer evet, win-streak cap (3 win → cool-down) ek alfa katar. Sayisal: after_win_mR +0.371 — ama 3+ ardışık win sub-sample test gerekli.
5. **HYP-BACKLOG-005**: VSA climax + Wyckoff phase D'nin **rare yüksek-mR** edge'inin standalone position-size bump'ı yatkın mı? Tier sizing zaten conf-based; bu strat-bazlı bump farklı, "structural class boost" gibi.

> Bu adaylar PRE-REG DEGIL — pre-reg sonraki sprint'te formal yapılır.

---

## 8. Kalici Mental Model (PA Mastery Distillation)

Researcher gelecekte yeni hipotez yazarken bu 9 mekanizmayi referans alir:

**Crypto'da PA edge yapısal kuralları:**
1. Edge magnitude'ce gelir, sayıca değil → engine **let-runners-run** disiplinli olmali (right-tail).
2. Short edge long'tan baskindir → halt asymmetric (short_dd siki, long_dd gevsek).
3. Alt-coin'lerde edge daha guclu → concentration cap (per-sym %20) corkuk.
4. Sequential clustering var → cool-down (3 LOSS → 5gun) korunmali.
5. High-vol edge kaynagı AMA ekstrem high-vol toxic → capitulation halt (Analyst HYP).
6. BTC<EMA50 short-friendly → naive trend filter ekleme.
7. Pool orthogonal olunca slot fix iyilik getirir → mc 8→12 (sec14.0).
8. Klasik mean-rev (RSI/Bollinger extreme) crypto'da CONTINUATION; mean-rev sadece microstructure gap (FVG-style) ile çalışır → SEC22 zincir RED ortakkanitı.
9. Brooks trap mekanizmasi crypto'da equity'den guçlü (leverage + 24/7 + funding cycle).
10. **Universe size optimum: 11-sym BTC-anchor** (SEC13.3 RED 20-sym + SEC27 REJECT 5-sym zincir) — sub-universe alt-only DD iyileştirir ama mutlak return %35-50 kaybeder (slot bottleneck universe size-bağlı, alt-coin mR boost realize olmuyor). Conservative LP variant cazip ama mutlak hedef BALANCED ile uyumsuz.

**Yeni hipotez kontrolü:**
- "Pattern X crypto-spesifik mikroyapısal mekanizmadan mi besleniyor?" → 24/7, retail leverage, funding 8h cycle, order-flow gap reclaim
- "Edge magnitude (mR) mi sayisi (n) ile mi geliyor?" → magnitude > sayi
- "Long mı short mı dominant?" → default short bias
- "Asset class transfer mi yoksa native crypto pattern mi?" → transfer **kanıt yükü** üzerinde

---

## 9. Reproducibility

- Pool: `data/_sec13_4_cache/pool_baseline_v1_3.pkl` (n=6650)
- BTC regime: `data/market.duckdb` (ohlcv BTC/USDT 1d binance)
- Script: `scripts/sec26_winner_forensic.py`
- Ham veri: `reports/researcher/sec26_forensic_data.json`, `sec26_per_strategy_breakdown.csv`, `sec26_regime_breakdown.csv`
- Rapor: `reports/researcher/2026-05-14_sec26_production_winner_forensic.md`
