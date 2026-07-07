---
doc_id: researcher-20260623T140123-eqh-eql-liquidity-sweep-reversal-cross-strategy-vsa-companion
doc_type: hypothesis
agent_id: researcher
created_at: 2026-06-23T14:01:23Z
status: DRAFT
confidence: med
depends_on: []
blocks: []
requested_review_from: [lab_scientist, risk_officer]
tags: [hypothesis, cross-strategy, low-correlation, liquidity-sweep, eqh, eql, market-structure, vsa-companion, curve-fit-watch]
supersedes: null
hash: bb3eda1
---

# Hipotez: HYP-2026-06-23-eqh-eql-sweep-reversal-vsa-companion

- **Tarih:** 2026-06-23
- **Versiyon:** 0.1 (pre-registration, kod yazılmadan önce)
- **Reproducibility:** git=bb3eda1, config=tbd, data=tbd

## 1. Motivasyon

Aktif portföyde tek canlı strateji **vsa_climax_test** (volume climax + WRB test, reversal/fade ailesi). Bu portföyün **single-edge konsantrasyonu** vsa_climax_test'in rejim dışına çıktığı dilimlerde sermayeyi savunmasız bırakır.

Raftaki 66 adayın taranmasında, mevcut companion grid'i çoğunlukla **trend-continuation** (donchian, mat-hold, marubozu, iii, atr-volbreakout, golden-cross, bos) veya **fakeout-fade** (brooks-failed-breakout) aileleri olarak kayıtlı. RAG corpus'ta `book_market_structure_order_flow` (RAG #6) **Equal Highs/Lows Sweep** mekaniğini "High" (4'üncü ailedeki en yüksek skor) olarak işaretliyor — kripto perpetual'larda stop-hunt mikroyapısı doğal aday — ama bu sinyal companion grid'imde **henüz pre-register edilmemiş**. Boşluğu kapatıyorum.

VSA climax (hacim ekseni) ile EQH sweep (likidite/yapı ekseni) iki **farklı tetik kaynağı** kullanır — beklenen sonuç düşük getiri korelasyonu.

## 2. İddia (pre-registered, ölçülebilir)

**Iddia:** 1D timeframe'de, USDT-perpetual evrenimde (Data dept'in liquid universe v3, son 3y, delisting-inclusive), aşağıdaki mekanik kuralla tanımlanan **EQH/EQL liquidity sweep reversal** sinyali:

**Mekanik (EQH örneği — short setup; EQL simetrik):**
1. **EQH tespiti:** Son `lookback_bars ∈ {30, 50, 80}` bar içinde, bireysel high'ları `cluster_tol_atr ∈ {0.15, 0.25, 0.35}` × ATR(14) toleransıyla **en az 2** tepenin kümelendiği seviye.
2. **Sweep:** `t` mumunun high'ı EQH seviyesinin `sweep_depth_atr ∈ {0.10, 0.20, 0.35}` × ATR(14) üzerine çıkar.
3. **Rejection:** `t` mumu EQH seviyesinin **altında** kapanır (yani close < EQH).
4. **Giriş:** `t+1` mumunun open'ında short.
5. **SL:** Sweep wick (`t` high) + `0.25` × ATR.
6. **TP:** 1.5R sabit veya en yakın BOS seviyesi (önce hangisine değerse).
7. **Hold cap:** 5 bar (1D ⇒ 5 gün); süre dolarsa MOC kapanış.

aşağıdaki **kontratları aynı anda** karşılar (3y full sample, fee+slip dahil):

| Metrik | Eşik | Kaynak / Gerekçe |
|---|---|---|
| **Annualized net return** | > **22%** (mütevazı — climax değil, complementary) | Curve-fit anti-pattern: çok yüksek hedef koymuyorum |
| **Sharpe (OOS, walk-forward ort.)** | > **0.8** | Chan retail-realistic single-asset gate (RAG #9) |
| **MaxDD** | < **25%** | Risk dept kabaca eşleşmesi için |
| **Profit factor** | > **1.35** | Düşük frekans için kabul edilebilir taban |
| **Trade sayısı (3y)** | ≥ **150** | López de Prado 4 free-param ⇒ N/k>30 ⇒ N>120 (RAG #1); +25% emniyet |
| **Korelasyon (returns) vs vsa_climax_test** | **|ρ_pearson| < 0.30** ve **|ρ_spearman| < 0.30** | "Companion" iddiasının özü — bu kırmızıysa hipotez red |
| **Trade arrival overlap (gün bazında)** | ortak trade-günü < **%20** | Diversification mantığı: aynı günlerde tetiklenmemeli |

## 3. Null Hipotez (H0)

EQH/EQL sweep reversal sinyali, **fee + slippage düşüldükten sonra**, shuffle baseline'a göre **istatistiksel olarak ayırt edilemez** (p ≥ 0.05) VEYA companion iddiasını **karşılamaz** (ρ ≥ 0.30 ile vsa_climax_test).

Null'u reddetmek için **her iki** koşul birden geçilmeli: edge anlamlı **ve** companion düşük korelasyonlu.

## 4. Literatür / RAG Referansları

- **[book_market_structure_order_flow, Tablo]:** "Equal Highs/Lows Sweep — Mechanical Workability (Crypto 1D): **High**. Stop-hunt mechanic crypto'da güçlü; H-2 (en yüksek skor)." Mekanizmanın kodlanabilirliği için birincil gerekçe (RAG #6).
- **[book_brooks_deep_catalog]:** "n-bar high/low aşımı + geri dönüş mekanik, tamamen kodlanabilir. En iyi hipotez adaylarından biri (Test edilebilir skala: 5/5)." Brooks'un failed-breakout taksonomisinde aynı mekaniğin kuzeni — onaylayıcı çapraz referans (RAG #3).
- **[book_lopez_summary]:** 6 curve-fit kırmızı bayrağı; bu hipotez bunlardan **3'üne karşı önceden savunma** kuruyor (free-param/sample, IS/OOS Sharpe oranı, parametre eşitsizliği). (RAG #1).
- **[book_chan_summary]:** Yeni stratejiler için OOS Sharpe > 0.8 single-asset gate'i. Hedef eşiği buradan geliyor (RAG #9).
- **[book_candlestick_statistics — inside bar]:** Karşı-örnek olarak okudum: rank 78/103, win rate %54. EQH sweep'in mum-anchor'ı tek inside bar'a indirgenmemeli — patern **yapısal** (multi-bar EQH + sweep), tek-bar candlestick değil (RAG #2).

## 5. Bağımlı Değişkenler (Dependent variables)

Önceden belirlenen ölçüm metrikleri (sonradan eklemiyorum — p-hacking yasak):
- `net_annual_return` (fee+slip dahil)
- `sharpe_oos_walkforward_mean` (12 dilimin ortalaması)
- `sharpe_oos_walkforward_std` (varyans testi için)
- `max_drawdown_pct` (peak-to-trough, account equity tabanlı)
- `profit_factor`
- `trade_count_3y`
- `corr_returns_vs_vsa_climax_test` (Pearson ve Spearman, aynı bar grid'inde)
- `joint_trade_day_overlap_pct`
- `regime_split_sharpe` (bull / bear / range)
- `stress_period_pnl_pct` (LUNA, FTX, USDC depeg, Yen carry)
- `shuffle_baseline_p_value`
- `dsr_lopez_de_prado`
- `pbo_lopez_de_prado` (combinatorially-symmetric)

## 6. Bağımsız Değişkenler (Independent variables, kasıtlı **az**)

Curve-fit yüzeyini düşük tutmak için **4 free parametre** ile sınırlı:
- `lookback_bars` ∈ {30, 50, 80}
- `cluster_tol_atr` ∈ {0.15, 0.25, 0.35}
- `sweep_depth_atr` ∈ {0.10, 0.20, 0.35}
- `min_eqh_touches` ∈ {2, 3}

**Toplam grid: 3 × 3 × 3 × 2 = 54 kombinasyon.** Sweep depth'i 0.01 adımıyla değil 3 ayrık nokta ile testliyorum (curve-fit savunması). Optuna **kullanmıyorum** — ham 54-noktalı tam grid + Holm-Bonferroni düzeltmesi (α / 54).

**Eşit-tutulan (frozen) parametreler — bilinçli karar:**
- ATR(14), risk %1/trade, leverage 3x cap, fee 7.5 bps taker, slip 5 bps
- SL 0.25 × ATR ek (sabit, optimize edilmedi)
- TP 1.5R (sabit, optimize edilmedi)
- Hold cap 5 bar (sabit)
- USDT-perpetual evreni: liquid v3, delisting-inclusive

## 7. Beklenen p-value & Anlamlılık Eşiği

- **Pre-Bonferroni hedef:** p < 0.01 (shuffle baseline vs. gerçek getiriler)
- **Holm-Bonferroni düzeltmesi:** 54 grid noktası ⇒ minimum p anlamlılığı için α/54 ≈ 9.3e-4 (en küçük p < 9.3e-4 olmalı)
- **DSR (Deflated Sharpe Ratio):** > 0.50 (López de Prado tablosu — RAG #1)
- **PBO (Probability of Backtest Overfitting):** < 0.50

Eğer pre-Bonferroni p < 0.01 ama Holm sonrası anlamsız ⇒ hipotez **reddedilir** ("bir grid noktası şanslı çıktı" deme).

## 8. Stop Criteria (önceden bağlayıcı — sonradan oynamıyorum)

Bu kriterlerden **bir tanesi** kırmızıysa hipotez **araştırma terkedilir**, iterate'e gitmez:

1. **In-sample Sharpe < 0.5** ⇒ edge yok, dur.
2. **IS Sharpe / OOS Sharpe > 1.5** ⇒ López de Prado #4, klasik overfit.
3. **Trade sayısı < 100** (3y full sample) ⇒ istatistik anlamsız, dur.
4. **Best parametreler grid sınırında** (lookback=30 veya 80, cluster_tol=0.15 veya 0.35) ⇒ optimum tablonun dışında, dur.
5. **Walk-forward Sharpe varyansı > ortalaması** ⇒ López de Prado #6, edge tutarsız.
6. **Symbol-out CV'de min Sharpe < 0** ⇒ tek-sembol baskınlığı (LUNA 2022-05 gibi).
7. **Korelasyon vsa_climax_test ile |ρ| ≥ 0.30** ⇒ companion iddiası çürür, hipotez yanlış soruyu cevaplıyor.
8. **Joint trade-day overlap ≥ 30%** ⇒ aynı günlerde tetikleniyor, diversification yok.

**Iterate kararı ASLA yapılmaz** eğer:
- Edge gerçek değilse (stop #1, #2, #3)
- Companion değilse (stop #7, #8) — bu hipotezin **konusu** companion; konu çürüyorsa iterate konu kayması olur.

**Iterate yapılabilir** (SOP-4b kapsamında) eğer:
- Edge gerçek (aylık ROI > 0, p < 0.01)
- Companion ✓
- AMA DD veya başka bir risk metriği gate'i geçmiyor ⇒ v2/v3 risk-reduction patikası.

## 9. Curve-Fit Şüphesi — Önceden Beyan

Bu hipotezde **kasıtlı olarak şu curve-fit risklerini bilerek üstleniyorum** ve önceden savunma:

| Risk | Savunma |
|---|---|
| 4 free param × 54 nokta ⇒ multiple testing inflation | Holm-Bonferroni (α/54), DSR/PBO zorunlu |
| Liquidity-sweep mekaniği "anlatımsal olarak güzel" — narrative bias | Anlatı reddedilir; sayı ister. Shuffle baseline p < 0.01 + DSR > 0.5 olmadan kabul yok |
| EQH cluster_tol'un seçimi subjektif | 3 ayrık nokta (0.15, 0.25, 0.35), 0.01 adımıyla değil; symbol-out CV ile per-symbol bias kontrolü |
| Crypto'da stop-hunt rejim-bağlı olabilir (yüksek lev sezonlarında) | Regime split zorunlu (bull/bear/range); en az 2 rejimde pozitif olmalı |
| **Companion korelasyon overlap'i 3y full sample'da düşük ama recent 6m'de yüksek olabilir (drift)** | Walk-forward'da **her dilimde** ρ ölçülür; son 3 dilimin ortalaması da < 0.30 olmalı |
| Survivorship | Delisting-inclusive universe v3 (Data dept) zorunlu |

## 10. Robustness Suite (zorunlu — SOP-3)

Tamamı koşulacak, hiçbiri atlanmayacak:
1. **Walk-forward** 3y/6m, step 3m (toplam 12 dilim)
2. **Param perturbation** 50 seed × ±%10 jitter ⇒ ortalama Sharpe kaybı < %25
3. **Symbol-out CV** (her sembol tek tek dışarıda) ⇒ min OOS Sharpe > 0
4. **Regime split** (HMM rejim çıktısı) — en az 2 rejimde pozitif
5. **Stress periodları:** 2022-05 LUNA, 2022-11 FTX, 2023-03 USDC depeg, 2024-03 BTC ATH, 2024-08 Yen carry — bu dönemlerde -10%'dan fazla kayıp yok
6. **Shuffle baseline** (returns shuffle null) ⇒ p < 0.01
7. **Multiple testing correction:** Holm-Bonferroni (k=54)
8. **DSR & PBO** (López de Prado, combinatorially-symmetric)
9. **Lookahead causality test:** `detector(df.iloc[:t+1])[t] == detector(df)[t]` her t için
10. **Companion overlap test:** vsa_climax_test ile aynı bar grid'inde getiri korelasyonu + trade-day overlap

## 11. Bağlayıcı Karar Kuralı

```
1. Stop criteria (§8) hiç tetiklendi mi? → EVET ⇒ RED
2. Robustness suite (§10) tamam mı? → HAYIR ⇒ RED veya iterate-eligible değil
3. Tüm §2 kontrat metrikleri ✓ mı? → HAYIR ⇒ §8'e göre iterate (yalnız edge gerçekse)
4. ρ < 0.30 ve overlap < 20% ✓ mı? → HAYIR ⇒ RED (companion değil; konu kayması yasak)
5. DSR > 0.5, PBO < 0.5 ✓ mı? → HAYIR ⇒ RED (overfit şüphesi)
6. Hepsi ✓ ⇒ TERFİ ADAYI (Lab tournament'a gönder)
```

## 12. Gelecek Adımlar (sırasıyla)

1. Detector'ı `signal_chief`'e teslim — vectorized, pure-function, lookahead testi geçecek
2. Backtest config'i `configs/research/eqh_eql_sweep_v01.yaml` taslak
3. `backtest.engine.run(config)` 3y full sample
4. Robustness suite (§10)
5. Karar yaz: `reports/research/eqh-eql-sweep-reversal-2026-06-23.html`
6. Terfi adayıysa Lab'e tournament için aday teslim; değilse `learning.md`'ye 3 satır gerekçe

## 13. Not — Anti-narrative beyan

Hipotezi yazarken "kripto'da stop-hunt yaygın" ve "MM'ler EQH'leri avlar" gibi anlatılar **hipotezi kanıtlamaz**. Bu hipotez sadece §2'deki sayıları geçerse kabul edilir. Anlatı reddedilir; sayı ister. Şu an iddia *henüz kanıtlanmadı* — sadece **test edilmeye değer**.

Eğer §8 herhangi bir stop tetiklenirse 3-satırlık red gerekçesi `memory/researcher/learning.md`'ye yazılacak; bu hipotez aynı slug ile tekrar pre-register edilmeyecek (recurrence guard).
