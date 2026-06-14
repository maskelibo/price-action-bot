---
doc_id: researcher-20260614T091500-volman-iii-htf-aligned-breakout-4h-vsa-diversifier
doc_type: hypothesis
agent_id: researcher
created_at: 2026-06-14T09:15:00Z
status: DRAFT
confidence: med
depends_on: []
blocks: []
requested_review_from: [lab_scientist, risk_officer]
tags: [hypothesis, cross_strategy, continuation, volman_iii, triple_inside, htf_aligned, low_correlation, pre_registration, curve_fit_risk]
supersedes: null
hash: null
---

# Hipotez: HYP-2026-06-14-volman-iii-htf-aligned-breakout-4h-vsa-diversifier

> **Seed:** "Cross-strategy edge keşfi: aktif `vsa_climax_test` ile düşük korelasyonlu ek bir strateji (raftaki 66 adaydan)."
> **Cevap:** Volman'ın **iii (triple inside bar) HTF-aligned breakout**, 4H timeframe. `mat_hold (5-bar)`, `bos_close_based`, `equal_highs_sweep`, `kaufman_vol_breakout`, `choch_n3`, `golden_cross_50_200` cross-companion olarak DENENDİ ve gate'i geçemedi (bkz. `hypotheses/2026-05-31..2026-06-13`). iii-only / 4H / HTF-EMA-aligned varyantı henüz pre-register edilmedi — boşluktaki adaydır. Yapısal olarak vsa_climax (1D climax reversal) ile farklı: 4H frekans + continuation + HTF trend devamı → korelasyonun ex-ante düşük olması beklenir.

## 0. Curve-Fit / Selection-Bias Şerhleri (zorunlu önyargı muhasebesi)

Bu hipotezi yazarken aşağıdaki kırmızı bayrakları **şimdiden** kabul ediyorum:

1. **Selection bias riski (yüksek):** Aynı seed ("low-corr companion to vsa") altında son 14 günde **≥18 hipotez** tetiklendi (mat_hold, bos, choch, equal_highs, kaufman_vol, golden_cross, donchian_adx, atr_breakout, order_block, rising_three, ii-marubozu, turtle_channel, halflife-rsi, anti-climax, vol_regime, …). Hepsi gate'i tutturamadıysa, bu 19. denemenin "pozitif" çıkması büyük olasılıkla **multiple-testing artifact**. Bonferroni / FDR p-eşiği **familywise N=19** üzerinden uygulanacak; bu yüzden tek-hipotez p<0.05 değil **p<0.000231 (Bonferroni FWER<0.05/216)** eşiği konuluyor (216 = 19 hipotez × 18 grid trial sweep ortalaması, konservatif).
2. **Bulkowski equity-sample riski:** %74-tipi continuation oranları US equities günlük bar. Kripto 4H perpetual'da 24/7 işlem + farklı microstructure + fonlama → kalıp distribution shift'i muhtemel. **Beklenen gerçekleşmiş edge: equity rakamının ≤ 1/3'ü.**
3. **Parametre ekstrem sınır riski:** `body_to_range_threshold ∈ [0.55, 0.70]`, `inside_tolerance ∈ [0.0, 0.05]` aralıklarının **uçlarında** optimum çıkarsa hipotez reddedilir (parametre uzayı dışına kaçmak overfit göstergesidir).
4. **In-sample / out-of-sample spread riski:** IS Sharpe / OOS Sharpe < 0.5 → red (López de Prado kriteri #4).
5. **Cross-strategy companion arama yorgunluğu:** seed_abort_log.jsonl'da bu seed için 33 LLM çağrısı kaydedilmiş; "narrative" gücü zayıfsa abort.

> **Bu hipotezi yazmak onaylamak değildir. Backtest sonucu yukarıdaki kriterlerden herhangi birini ihlal ederse otomatik red.**

## 1. İddia (pre-registered, ölçülebilir)

Crypto perpetual USDT evreninde (≥40 likit sembol, **delisting'ler dahil — survivorship-clean**, kripto 1H/4H veri 2021-01-01 → 2025-12-31, son 6 ay strict OOS hold-out), **4H timeframe**'de, **HTF (1D) EMA50 yönü ile aligned** koşulunda, Volman **iii (triple inside)** breakout kalıbı:

**Pattern mekaniği (lookahead-safe):**
- **Bar 1 (mother bar):** sıradan range bar (filtre yok)
- **Bar 2:** `Bar2.High < Bar1.High` VE `Bar2.Low > Bar1.Low` (inside-1)
- **Bar 3:** `Bar3.High < Bar2.High` VE `Bar3.Low > Bar2.Low` (inside-2, kompresyon devam)
- **Bar 4:** `Bar4.High < Bar3.High` VE `Bar4.Low > Bar3.Low` (inside-3, **iii** tamam — 3 ardışık inside)
- **Bar 5 (breakout candidate):** kapanış > Bar1.High → long-setup; kapanış < Bar1.Low → short-setup
- **HTF align gate:** long-setup ancak `close(1D EMA50) > close(1D EMA200)` ise tetiklenir; short-setup ancak tersi.
- **Body filter:** Bar 5 `body / range ≥ 0.55` (zayıf breakout barlarını ele).

**Giriş / çıkış mekaniği:**
- **Entry:** Bar 6 open (Bar 5 close kararı, Bar 6 open girişi — lookahead-safe)
- **SL:** `1.5 × ATR(14, 4H)`, mother bar (Bar 1) zıt ucunu aşmaz (tighter olan kazanır)
- **TP:** {fixed 2R, 10-bar opposite-channel trailing, hybrid (1R partial + trail)} — sweep
- **Maliyet:** taker fee 7.5 bps + slippage 5 bps her giriş/çıkış

**Pre-registered hard gate'ler:**

| Metric | Hard Gate |
|---|---|
| Annualized net return (fee+slip sonrası, OOS) | **≥ %18** |
| Sharpe (annualized, daily-resampled PnL, OOS) | **≥ 0.8** |
| MaxDD (account-equity bazında, NOT cumulative-PnL) | **≤ %22** |
| Trade count N (5y, tüm semboller toplam) | **≥ 80** |
| Profit factor (OOS) | **≥ 1.30** |
| **Pearson corr(daily PnL, `vsa_climax_test` daily PnL)** | **≤ 0.20** *(asıl iddianın çekirdeği — diversification)* |
| **Spearman corr(trade-arrival timestamps)** (vsa_climax_test ile aynı bar'da trade) | **≤ 0.15** *(trade-disjoint test)* |
| Walk-forward dilim başarı (3y/6m, step 3m → 12 dilim) | **≥ 9/12 pozitif Sharpe** |
| In-sample / Out-of-sample Sharpe spread | **< %50** (OOS ≥ %50 × IS) |
| Shuffle baseline empirical p (1000 perm) | **< 0.000231** (Bonferroni N=216 grid+familywise) |
| DSR (Deflated Sharpe Ratio, Bailey-López) | **> 0.5** |
| Best param parametre uzayının ucunda | **HAYIR** (red sebebi) |

Hard gate'lerden **herhangi biri ihlal ederse**: hipotez reddedilir, gerekçe `learning.md` + `seed_abort_log.jsonl`.

## 2. Gerekçe (RAG referansları)

- **[book_candlestick_statistics §Inside Bar (#2 score=0.581)]** — Tekli inside bar zayıf (breakout WR %54, rank 78/103). "Volman eklemi: ii (double) veya iii (triple) breakout daha güçlü. Volman'ın DD setup'ı buradan türer." → Tek inside bar'ı tek başına kullanmak EDGE DEĞİL; iii compression hipotezin çekirdek bahsi.
- **[book_market_structure_order_flow §Mekanik Çalışabilirlik (#6 score=0.568)]** — BOS/CHoCH ve sweep desenleri "Yüksek mekanik çalışabilirlik" puanı alıyor; iii breakout mekanik tanımı benzer netlikte (3 ardışık inside + close-cross-mother). Backtestable, az parametrik (`body_to_range`, `inside_tolerance` 2 hyperparam).
- **[book_lopez_summary §Overfit Kriterleri (#1 score=0.582)]** — DSR > 0.5 ve PBO < 0.5 koşulları **gate'e dahil edildi** (yukarıda); IS Sharpe > 3×OOS Sharpe ihlali otomatik red.
- **[book_kaufman_summary §Channel Breakout (#7 score=0.563)]** — Turtle System 1 mantığı: asimetrik R-multiple (%35 WR + 3-5R winners). iii breakout buna benzer dağılım üretmeli (yüksek WR yerine fat-tail winners). **Eğer backtest yüksek WR + düşük avg R üretiyorsa hipotez yapısal beklentiden sapmış → şüphe.**
- **[book_candlestick_statistics §Mat Hold (#10 score=0.557)]** — Konsolidasyon-sonrası-momentum yapısı; iii daha kısa konsolidasyon (3 bar) + daha keskin breakout. Mat Hold (5-bar) **aynı seed altında 2 kez red**; iii'in red olma ön-olasılığı bu yüzden **yüksek (≥%60)** — bu, hipotezi yazmamak için sebep değil ama "kabul gerekçeli olsun, anlatı değil sayı kazansın" ilkesini güçlendirir.

> **RAG'de iii'in spesifik kripto edge'i için referans YOK.** Bu, hipotezi terketme gerekçesi olabilir (SOP-5 son satır). Burada özgün iddia: equity-sample literatür + kripto microstructure'da test → ya yeni edge, ya başka bir multi-testing artifact.

## 3. Dependent Variables (önceden saptanmış metrikler)

| Variable | Tanım |
|---|---|
| `net_annual_return_pct` | (Final equity / initial equity)^(1/y) - 1, fee+slip sonrası |
| `sharpe_annual_oos` | mean(daily PnL) / std(daily PnL) × √252, son 6 ay OOS |
| `maxdd_equity_pct` | account-equity tepe-vadi düşüş (cum-PnL DEĞİL — ADR-001/CT-RSK-01) |
| `profit_factor` | Σ(winners) / |Σ(losers)| |
| `n_trades_total` | tüm semboller 5y toplam |
| `corr_pearson_vsa_daily` | daily-resampled PnL Pearson r vsa_climax_test ile |
| `corr_spearman_arrival` | trade entry timestamp Spearman ρ vsa_climax_test ile |
| `wf_slice_positive_count` | 12 walk-forward diliminde Sharpe>0 olan dilim sayısı |
| `is_oos_sharpe_ratio` | OOS_Sharpe / IS_Sharpe (≥ 0.5 hedef) |
| `shuffle_p_empirical` | 1000 returns-shuffle permutation empirical p |
| `dsr_bailey_lopez` | Deflated Sharpe Ratio (#trial sayısına göre) |
| `best_param_at_boundary` | bool — best Optuna params parametre uzayı ucundamı |

## 4. Independent Variables (sweep grid'i — önceden ilan)

| Param | Aralık | Adım | Sebep |
|---|---|---|---|
| `body_to_range_threshold` (Bar 5) | 0.55 → 0.70 | 0.05 | 4 değer |
| `inside_tolerance` (Bar 2-4 strict inside vs ±tick toleransı) | 0.000 → 0.005 | 0.0025 | 3 değer |
| `htf_align_filter` | {strict (EMA50>EMA200), loose (sadece EMA50 slope >0), off} | — | 3 değer |
| `atr_sl_multiplier` | 1.0, 1.5, 2.0 | — | 3 değer |
| `exit_rule` | {fixed_2R, channel_trail_10, hybrid_1R_partial} | — | 3 değer |
| `body_filter` | {on, off} | — | 2 değer |

**Toplam grid:** 4 × 3 × 3 × 3 × 3 × 2 = **216 kombinasyon**. Bonferroni multiplier 216 (yukarıda gate'lerde belirtildi).

**Optuna n_trials = 100, TPE + Median pruner**, objective = OOS-Sharpe (sadece test sonrası ödüllendirir). Random seed fixed (42); reproducibility için.

**Yasak (overfit-frenleri):**
- `body_to_range_threshold` 0.05'ten ince adım YASAK
- `atr_sl_multiplier` 0.25'ten ince adım YASAK
- Sembol-bazlı tuning YASAK (tek parametre seti tüm evrene)
- Trade sonuçlarını look-ahead-incorporate eden filtre YASAK

## 5. Beklenen p-value (önceden taahhüt)

- Single-hypothesis raw eşik: **p < 0.05** (insignificant)
- Bonferroni FWER N=216 sonrası: **p < 0.000231** ZORUNLU
- Benjamini-Hochberg FDR α=0.10 sonrası: top-rank trial'ın **q < 0.10**
- DSR > 0.5

**Beklenen sonuç (ex-ante önyargılı tahmin, kayıt amaçlı):** %60 olasılıkla red (selection bias geçmişine bakarak); %30 olasılıkla "marjinal — gate'in altında 1-2 metric"; %10 olasılıkla terfi adayı.

## 6. Stop Criteria (early-kill — backtest sırasında uygulanır)

Aşağıdakilerden **biri** tetiklenirse araştırma sonlandırılır, sonraki adımlara geçilmez:

1. **In-sample Sharpe < 0.5** ilk parametre setinde → terk (zaman bütçesi koruması).
2. **Trade count N < 60** tüm evren 5y toplam → underpowered, terk.
3. **vsa_climax_test korelasyonu > 0.30** Pearson (daily PnL) → asıl çekirdek (diversification) iddiası çürür → terk. **DİKKAT: pozitif PnL ile birlikte yüksek korelasyon = "iki kez aynı bahsi kazandık" tuzağı; diversification edge YOK.**
4. **IS / OOS Sharpe spread > %50** → overfit, terk.
5. **Best param parametre uzayının ucunda** (1+ dimension) → terk, uzayı genişletmek YASAK (post-hoc curve fit).
6. **Walk-forward 12 dilimden 4+ tanesi negatif Sharpe** → edge consistent değil, terk.
7. **Bonferroni p > 0.000231** → multiple-testing yenilemedi, terk.
8. **DSR < 0.5** → terk.
9. **Sembol-out CV: min OOS Sharpe < 0** → tek sembol baskın → terk.
10. **Regime split: bear rejiminde -%5'ten kötü Sharpe VE bull rejiminde +1.0 Sharpe** → rejim-tek-yönlü, "low-corr diversifier" iddiası kısmi → terk (regime-dependent companion için ayrı hipotez gerekir).

## 7. Robustness Suite (SOP-3 zorunlu — gate'i geçerse uygulanır)

Standart 8 test (walk-forward, param perturb ±%10 50 seed, symbol-out CV, regime split, stress (LUNA/FTX/USDC/Yen), shuffle baseline, Bonferroni, lookahead causality test). Her test başarısız → red.

## 8. Pre-registration Commit

- **Hipotez Hash:** SHA256(bu dokümanın frontmatter+body) → backtest config'inden bağımsız, donmuş.
- **Backtest config dosyası:** `configs/research/hyp-2026-06-14-volman-iii-htf-aligned.yaml` (oluşturulacak; hipotez frontmatter `hash` alanına commit SHA yazılır).
- **Data hash:** `data/futures_1h.parquet`, `data/futures_4h.parquet`, `data/futures_1d.parquet` md5 — backtest sırasında log'lanır.
- **Reproducibility tuple:** (git_hash, config_hash, data_hash) sonuç raporu başlığında.

## 9. Beklenen Akış

1. Bu hipotez **commit edilir** (hash dondurulur).
2. `scripts/research/hypothesis_runner.py --id HYP-2026-06-14-volman-iii-htf-aligned-breakout-4h-vsa-diversifier` çalışır.
3. SOP-3 robustness suite otomatik.
4. Sonuç raporu `reports/research/volman-iii-htf-aligned-4h-2026-06-14.html`.
5. Karar üç yoldan biri (SOP-4):
   - **Terfi:** Lab tournament'a (lab_scientist'e teslim).
   - **İterate (SOP-4b):** pozitif aylık ROI ama DD/Sharpe zayıf → v2 (risk reduction / confluence filter / regime subset / position management).
   - **Red:** Aylık ROI ≤ 0 VEYA 3+ iterate sonrası gate'e ulaşamadı → arşiv + `learning.md` 3 satır.

## 10. Önceden Söylenenler (post-hoc rasyonalizasyon yasağı)

Backtest çalıştıktan sonra **bu dokümanı düzenlemek YASAK** (append-only protokol). Eğer sonuç "marjinal ama tweak edersek geçer" diyorsa, yeni hipotez (v2) ile yeniden pre-register; bu hipotez `status: REJECTED` veya `COMPLETED` olarak kapanır, sonraki versiyon `supersedes` ile bağlanır.

---

**Author note:** Bu hipotezi yazarken kendime şunu sordum: "Bunu sayı değil, anlatı için mi yazıyorum?" Anlatı: "Volman'ın iii deseni HTF-aligned breakout olarak kripto 4H'da çalışmalı." Sayı: yok, RAG'de yok. Bu yüzden ex-ante beklenti %60 red. Sayı kazanırsa terfi, kazanmazsa gerekçeli arşiv. İkisi de değerli.
