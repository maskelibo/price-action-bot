---
doc_id: researcher-20260615T120000-brooks-fbr-atr-stop-sweep
doc_type: hypothesis
agent_id: researcher
created_at: 2026-06-15T12:00:00Z
status: DRAFT
confidence: low
depends_on: []
blocks: []
requested_review_from: [lab_scientist, risk_officer, adversary_engineer]
tags: [brooks, failed_breakout, fbr, atr_stop, parameter_sweep, curve_fit_risk]
supersedes: null
---

# Hypothesis HYP-2026-06-15-BROOKS-FBR-ATR-STOP-SWEEP

## 0. Curve-Fit Warning (pre-registered)

Bu hipotez **bir parametre süpürmesidir**. Süpürme = otomatik olarak yüksek curve-fit riski. Bu nedenle:

- Sweep edilen TEK parametre `stop_atr_mult`'tır. Diğer tüm parametreler (range tanımı, HTF filter, TP_R, fee/slip) sabit ve **önceden** kilitli.
- 9-noktalı ızgara önceden ilan edildi (aşağıda). Süpürme sırasında nokta eklemek yasak.
- Bonferroni düzeltmesi 9 trial üzerinden uygulanacak (α=0.05/9 ≈ 0.0056).
- "En iyi" ATR çarpanı süpürme aralığının uç noktalarında (0.5 veya 3.0) çıkarsa hipotez **otomatik red**; süpürme aralığını genişletip yeniden test etmek yasak (sonsuz aralık genişletme = klasik p-hacking).
- IS/OOS Sharpe farkı > %35 olan herhangi bir ATR noktası: o nokta için terfi adaylığı yok.

## 1. İddia (measurable, pre-registered)

> **H1:** 2022-01-01 ile 2026-05-31 arası USDT-perpetual evreninde (top-30 hacim, survivorship-bias düzeltilmiş), 1h timeframe'de Brooks tanımlı "failed breakout" (FBR) setup'ı için, ATR(14) tabanlı initial stop mesafesi `k ∈ {0.5, 0.75, 1.0, 1.25, 1.5, 1.75, 2.0, 2.5, 3.0}` üzerinde süpürüldüğünde, **en az bir** `k*` değeri için aşağıdaki metriklerin TAMAMI sağlanır:
>
> - OOS (walk-forward, 3y/6m, step 3m) net annualized return ≥ **%35** (fee 7.5bps taker + slip 5bps dahil)
> - OOS Sharpe ≥ **1.20**
> - OOS MaxDD (equity-base) ≤ **%22**
> - Profit factor (OOS) ≥ **1.45**
> - Trade count (OOS, 4.4y, evrene yayılı) ≥ **400**
> - Shuffle-baseline p-value < **0.0056** (Bonferroni 9-trial)
> - `k*` süpürme aralığının iç bölgesinde (yani `k* ∈ {0.75, 1.0, 1.25, 1.5, 1.75, 2.0, 2.5}`)

**Null hipotez (H0):** Hiçbir `k` değeri yukarıdaki 7 koşulu birlikte sağlamaz. Bu durumda Brooks-FBR setup'ında ATR-tabanlı sabit stop tek başına edge üretmiyor demektir; ek bağlam (HTF, confluence) gerekli.

## 2. Setup Mekanik Tanımı (kilitli)

- **Range tespiti:** Son 50 bar içinde en az 2 swing high, biri diğerinin ±0.15·ATR(14) tolerans bandında. Range süresi ≥10 bar. Range top = swing high'ların mean'i.
- **Failed Breakout bar (t):**
  1. `high[t] > range_top` (breakout)
  2. `close[t] < range_top` (range içine kapanış)
  3. `close[t] < open[t]` (bearish bar) — short FBR; long FBR için ayna versiyonu.
- **HTF filter (sabit, sweep dışı):** 1D EMA(50) — short FBR sadece price < 1D EMA50 iken; long FBR sadece price > 1D EMA50 iken. (Brooks: "context first" — RAG#9.)
- **Giriş:** `t+1` bar açılışında market (bar-close decision, no lookahead).
- **Stop:** `entry_price + k·ATR(14)` (short için yukarı). Sweep parametresi yalnızca `k`.
- **TP:** Fixed `2.0R` (Brooks variable R'yi tercih etse de scalar sweep'e izolasyon için sabit).
- **Time stop:** 96 bar (4 gün) içinde TP/SL hit olmazsa close at market.
- **Pyramid yok, partial yok, BE-protect yok.** (İzole sweep.)

## 3. Gerekçe (RAG referansları)

- **RAG #3 (book_brooks_summary, score 0.470):** "Failed breakout = trap = reverse trade. Range high'tan breakout, follow-through yok, range içine kapanış — bu reversal sinyalidir." Setup'ın mekanik temeli.
- **RAG #4 (book_brooks_deep_catalog, score 0.434):** Range tanımı (≥2 swing high, ≥10 bar) ve "fade extremes default" — range içinde mean-reversion edge'inin Brooks tarafından doğrulanması.
- **RAG #2 (book_volman_summary, score 0.479):** "Brooks failed breakout = Volman FBR; Brooks daha gevşek, Volman pip-tabanlı sınır koyar." → Volman'ın tight-stop disiplini sweep'in alt ucunu (`k=0.5`) test etmemize gerekçe veriyor.
- **RAG #5 (book_brooks_summary, score 0.431):** "Volman daha tight stop disiplinine sahip (10 pip default), Brooks setup-bar-based variable." → Sabit ATR-stop iki ekolün arasında bir köprü; sweep her iki ucu da kapsıyor.
- **RAG #9 (book_brooks_summary, score 0.393):** "Setup, bağlam olmadan hiçbir şeydir." → HTF filter'ı sabit tutmamızın gerekçesi (sweep dışı).

**RAG bulgu sınırı:** Hiçbir kaynak "ATR çarpanı X optimal" demiyor. Bu hipotez literatürün boşluğunu hedefliyor — pozitif veri çıkarsa orijinal bulgu; çıkmazsa Brooks'un "context > parameter" tezini doğrulayan negatif sonuç.

## 4. Dependent Variables (primary endpoint listesi, pre-registered)

| Sıra | Metrik | Yön | Eşik |
|---|---|---|---|
| 1 | OOS net annualized return | ↑ | ≥ %35 |
| 2 | OOS Sharpe | ↑ | ≥ 1.20 |
| 3 | OOS MaxDD (equity-base) | ↓ | ≤ %22 |
| 4 | OOS Profit factor | ↑ | ≥ 1.45 |
| 5 | OOS Trade count | ↑ | ≥ 400 |
| 6 | Shuffle p-value (Bonferroni 9) | ↓ | < 0.0056 |

**Secondary (raporlanır ama gate değildir):** Win rate, avg R, Calmar, recovery factor, exposure %, longest drawdown duration, fee/gross ratio.

## 5. Independent Variables

- **Süpürülen (sweep):** `stop_atr_mult ∈ {0.5, 0.75, 1.0, 1.25, 1.5, 1.75, 2.0, 2.5, 3.0}` — 9 nokta.
- **Sabit (locked, sweep yok):**
  - Range lookback: 50 bar
  - Range tolerance: 0.15 · ATR(14)
  - Range min duration: 10 bar
  - HTF filter: 1D EMA(50)
  - TP_R: 2.0
  - Time stop: 96 bar
  - ATR window: 14
  - Risk/trade: %1 equity
  - Fee: 7.5 bps taker, slip 5 bps
  - Initial equity: 10k USDT

Bu kilit "diğer her şeyi optimize edip stop'u sweep ediyormuşum gibi yapma" çapraz-süpürme tuzağına karşı koruma.

## 6. Beklenen p-value & İstatistiksel Plan

- Trial sayısı: 9 (ATR noktası başına 1).
- Düzeltilmiş anlamlılık eşiği: **α* = 0.05/9 ≈ 0.0056** (Bonferroni). Daha cömert FDR (Benjamini-Hochberg) sekonder olarak raporlanır ama karar Bonferroni'ye göre verilir.
- Shuffle baseline: getiri dizisini 1000 kez karıştır, null Sharpe dağılımı üret. Gerçek Sharpe'ın bu dağılımdaki yüzdelik dilimi p-değeridir.
- Walk-forward: 3y train + 6m test, step 3m → 2022-01'den 2026-05'e ~6 OOS dilim. Her ATR noktası için 6 OOS Sharpe'ın mean ve std'si raporlanır.
- Symbol-out CV: her sembolü tek tek dışarıda bırak; min OOS Sharpe `k*` için ≥ 0.60.

## 7. Stop Criteria (araştırmayı erken sonlandırma)

Aşağıdakilerden herhangi biri tetiklenirse araştırma terkedilir, gerekçeli arşiv:

1. **IS Sharpe (tüm 9 nokta) < 0.5** → setup'ın temelinde edge yok, sweep'in anlamı yok.
2. **Trade count herhangi bir nokta için < 200 (4.4y)** → istatistiksel güç yetersiz.
3. **Best `k*` ∈ {0.5, 3.0} (sınır)** → süpürme aralığı yanlış seçilmiş VEYA edge tablonun dışında. Genişletme YASAK; hipotez red.
4. **Tüm 9 noktada IS-OOS Sharpe farkı > %35** → her seçimde overfit, robust nokta yok.
5. **HTF filter'ı kapattığımızda performans daha iyi** → setup HTF context'e değil tek başına ATR-stop'a bağlı; Brooks tezi çürüyor, bu da kabul edilebilir bir red.
6. **Stress periyotlarında (2022-05 LUNA, 2022-11 FTX, 2024-08 Yen carry) `k*` için DD > %40** → tail risk gate'i kırıyor.

## 8. Beklenen Sonuç Senaryoları (pre-mortem)

- **Senaryo A (%~15 olasılık, prior):** `k* ∈ {1.0, 1.25, 1.5}` aralığında gate geçer → Brooks-FBR + HTF + ATR-stop edge'i gerçek. Lab tournament'a aday gönder.
- **Senaryo B (%~50 olasılık):** Hiçbir k gate'i geçemez ama bir veya iki nokta marjinal ROI pozitif çıkar → **SOP-4b iterate**: confluence_score filter, regime filter, BE-protect ile v2 hipotez.
- **Senaryo C (%~35 olasılık):** Tüm k'ler negatif veya Sharpe < 0.5 → null kabul, Brooks-FBR tek başına edge üretmiyor; **SMC-no-edge dersinin** (memory) bir karşı-doğrulaması olur.

## 9. Reproducibility

- git_hash: doldurulacak (backtest commit'i sonrası)
- config_hash: SHA256 of locked params (yukarıdaki §5)
- data_hash: DuckDB universe snapshot 2026-06-15
- backtest engine: `backtest/engine.py` (vectorbt)
- WF runner: `backtest/walk_forward.py`

## 10. Onay & Sonraki Adım

- Bu doc DRAFT. Lab Scientist + Risk Officer + Adversary Engineer review'undan sonra PROPOSED'a çekilir.
- Onaylanırsa backtest çalıştırma için `scripts/run_hypothesis.py --id HYP-2026-06-15-BROOKS-FBR-ATR-STOP-SWEEP`.
- Sonuç raporu: `reports/research/brooks-fbr-atr-sweep-<date>.html`.

---

**Pre-registration locked at 2026-06-15T12:00:00Z. Bu noktadan sonra herhangi bir parametre/eşik/setup tanımı değişikliği = yeni hipotez doc + supersedes.**
