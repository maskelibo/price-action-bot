---
doc_id: researcher-20260610T000000-marubozu-bearish-continuation-low-corr-to-vsa
doc_type: hypothesis
agent_id: researcher
created_at: 2026-06-10T00:00:00Z
status: PROPOSED
confidence: low
depends_on:
  - book_candlestick_statistics-bulkowski-belt-hold-rank22
  - book_lopez_summary-dsr-pbo-gates
  - book_market_structure_order_flow-bos-choch-mechanical
blocks: []
requested_review_from:
  - lab_scientist
  - risk_officer
  - adversary_engineer
tags:
  - hypothesis
  - cross_strategy_edge
  - vsa_orthogonal
  - candle_only
  - marubozu
  - belt_hold
  - bearish_continuation
supersedes: null
hash: null
---

# HYP-2026-06-10-marubozu-bearish-continuation-low-corr-to-vsa

## 1. Seed

Aktif `vsa_climax_test` (volume-based reversal/exhaustion) için **düşük korelasyonlu** raf adayı arıyoruz. VSA climax = (a) yüksek hacim, (b) reversal niyeti, (c) wick-driven. Tam ortogonal aday: **hacimsiz, continuation niyetli, body-driven**.

## 2. Iddia (pre-registered, ölçülebilir)

> H1 (pozitif edge): Kripto USDT-perp evreninde (`pool_19sym`, 2022-01-01 → 2025-12-31), 1D timeframe'de, aşağıdaki **bearish marubozu / belt-hold short continuation** stratejisi:
>
> - **Tanım:** Bar t'de `body/range ≥ 0.90`, `(open − close)/range ≥ 0.85` (bearish), `close ≈ low ±0.05·range`. Trend filtresi: `EMA50(close) downsloping (5-bar slope < 0)`. Hacim NÖTRDÜR (filter yok — VSA'ya korelasyon enjekte etmemek için).
> - **Giriş:** t+1 bar açılışında SHORT.
> - **SL:** Bar t'nin high'ı + 0.15·ATR(14).
> - **TP:** 2R fixed.
> - **Time-stop:** 5 bar.
>
> 4 yıllık OOS pencerede (walk-forward 3y train / 6m test, step 3m), **aşağıdaki birleşik gate'i geçer:**
>
> | Metric | Eşik (OOS, fee+slip dahil) |
> |---|---|
> | Net annual return | ≥ %25 |
> | Sharpe (annualized, daily) | ≥ 0.8 |
> | MaxDD | ≤ %22 |
> | Profit factor | ≥ 1.3 |
> | Trade count | ≥ 120 (istatistik için) |
> | **Pearson corr(daily PnL, vsa_climax_test daily PnL)** | **\|ρ\| ≤ 0.25** |
>
> Multi-testing düzeltme: araştırılan raf 66 stratejiden seçildiği için Bonferroni'li hedef p-value < 0.05 / 66 = **0.000758** (shuffle baseline'a karşı).

> H0 (null): Marubozu bearish continuation kripto 1D'de Sharpe ≤ 0 (fee+slip sonrası) **veya** `|ρ| > 0.25` (VSA'ya korelasyon yüksek, ortogonal değil).

## 3. Gerekçe — RAG referansları

- **[Bulkowski, Encyclopedia of Candlestick Charts, "Belt-Hold/Marubozu" — book_candlestick_statistics #8]**
  - Bearish continuation rate **%64** (US stocks, 1990–2010 örneklemi).
  - Average post-signal move **%4.9**.
  - Performance rank **22/103** (orta üst). *Not: Bulkowski stock-cash data; kripto perp HİÇ test edilmedi.*
- **[Lopez de Prado, "Building Diversified Portfolios" — book_lopez_summary #1]**
  - Cross-strategy edge için `|ρ| ≤ 0.30` eşiği (paper 2018, eq. 7). Biz 0.25'e sıkıştırdık.
- **[Hassonjee/order-flow primer — book_market_structure_order_flow #6]**
  - Trend-state continuation sinyalleri (BOS-following) close-based ve mekanik, kripto 1D'de "Yüksek" mekanik-uygulanabilirlik notu. Marubozu = momentum confirmation barı; aynı mantığa düşer.

## 4. Mekanizma (neden VSA'ya ortogonal?)

| Boyut | vsa_climax_test | marubozu_bear_cont (aday) |
|---|---|---|
| Sinyal kaynağı | volume z-score + wick reversal | body/range oranı + EMA50 slope |
| Niyet | reversal (mean revert) | continuation (momentum) |
| Yön | symmetric (long+short climax) | short-only (ilk versiyon) |
| Bar timing | wick-extreme entry | close-of-body entry |
| Volume bağımlılığı | %100 (ana feature) | %0 (kasten yok) |

→ **A priori beklenti:** Returns korelasyonu, EMA50 trend filtresi ortak HTF yapısından dolayı sıfırdan biraz yüksek olabilir; 0.10–0.20 bandı bekliyorum. 0.25 üzerine çıkarsa H0.

## 5. Dependent Variables (ölçeceğim)

1. Net annual return (fee 7.5bps taker + 1 bps maker, slippage 5 bps)
2. Sharpe (daily, ann.)
3. MaxDD (% on equity base, **NOT** cumulative PnL — bkz. CT-RSK-01 dersi)
4. Profit factor
5. Win rate, average winner / loser (R)
6. Trade count
7. Pearson + Spearman corr(daily PnL, vsa_climax_test daily PnL) — **2 metrik** çünkü Pearson tail-kör olabilir
8. Bonferroni-düzeltilmiş p (shuffle baseline'a karşı, N=1000 permütasyon)
9. PBO (Combinatorially Symmetric CV, K=10)

## 6. Independent Variables (donduruyorum — sweep YOK)

- `body_range_ratio_min = 0.90` (literatür default — Bulkowski 0.90+)
- `body_dominance_min = 0.85` ((open−close)/range)
- `close_at_low_tol = 0.05·range`
- `ema_period = 50`
- `ema_slope_lookback = 5 bar`
- `atr_period = 14`
- `sl_atr_buffer = 0.15`
- `tp_R = 2.0`
- `time_stop_bars = 5`

**Bu parametrelerden hiçbirini Optuna ile aramıyorum — ilk pass.** Hipotezi tam mekanik, literatür-default ile test edeceğim. Curve-fit kapısını kapatıyorum.

## 7. Beklenen p-value

- Shuffle baseline (returns-shuffle): **p < 0.001** (raw)
- Bonferroni post 66 raf: **p < 0.000758**
- DSR (Deflated Sharpe): **> 0.7** (Lopez de Prado eq. 9, T=120+)
- PBO (Probability of Backtest Overfitting): **< 0.4**

## 8. Stop Criteria (hipotezi terkettiğim eşikler)

Aşağıdaki BIRI olursa hipotez REDDEDİLİR, iterate de açılmaz:

1. **In-sample Sharpe < 0.5** → erken durdur, OOS'a geçme. (Bulkowski stock %64 WR varsa kripto 1D'de en az 0.5 Sharpe olmalı.)
2. **Trade count < 120 OOS dilimde** → istatistik yetersiz. (Kripto 1D'de marubozu az olabilir — *bu hipotezi öldüren en olası bayrak*.)
3. **\|ρ(PnL, vsa_climax_test)\| > 0.40** → ortogonallik iddiası çürür, "diversifier" değer önerisi sıfırlanır.
4. **MaxDD > %30** → risk profili portföye uymuyor.
5. **In-sample/OOS Sharpe oranı > 2x** → overfit bayrağı (Lopez de Prado kriter #4).
6. **Lookahead test fail** → kod red.

## 9. Curve-fit / Overfit şüphe envanteri (PROACTIVE)

Bu hipotezin kırılma noktalarını ÖNCEDEN sıralıyorum (anti-confirmation):

- ⚠️ **Bulkowski örneklemi US stock 1990–2010** — kripto perp 2022–2025 farklı asset class, farklı rejim, farklı mikro yapı. %64 WR transfer etmeyebilir; %50–55 daha olası.
- ⚠️ **Pattern tanımı 4 parametre içeriyor** (body, dominance, close_at_low_tol, EMA slope). Hiçbirini sweep etmesem bile, *seçim* zaten örtük p-hacking — bu parametre seti zaten Bulkowski'nin geriye-bakan istatistiğinden geliyor.
- ⚠️ **Belt-hold rank 22/103** — top değil, ortalama bir kalıp. Marjinal edge → fee/slip kolayca yutar (kripto taker 7.5 bps × 2 = 15 bps her trade; %4.9 avg move'un %3'ü).
- ⚠️ **Sample-size endişesi:** 19 sembol × 4 yıl × ~365 gün × (body≥0.90 AND dominance≥0.85 AND EMA downsloping) frekansı = tahminen sembol başına yılda 8-15 trade → toplam ~600-1100 trade. Sınırın üstünde ama dilim başına 75-140 → bireysel dilim istatistiği zayıf.
- ⚠️ **VSA korelasyonu sıfırdan büyük olabilir:** EMA50 downsloping filtresi varken VSA'nın "selling climax" bullish reversal sinyalleri aynı bar civarında tetiklenebilir (zıt yönlü ama korelasyonlu). \|ρ\| 0.20–0.30 bandı en olası.
- ⚠️ **Survivorship ve delisting:** Pool 19sym'ın delisting-aware olduğunu *kabul ediyorum*. Değilse marubozu signal'i delist edilmiş semboller bias'lanır (rebound öncesi gibi).
- ⚠️ **Regime split testi muhtemelen bear-only edge gösterir** (downside continuation), bull rejim ve range rejimde negatif olabilir → portföy etkisi mevsimsel.

→ **A priori başarı şansım: %25.** Yani 4 hipotezden 1 geçer beklentisiyle yazıyorum. Geçmezse şaşırmıyorum, lessons.md'ye not düşüyorum.

## 10. Reproducibility

- Git hash: (commit at backtest run)
- Config hash: (sha256 of independent vars block above)
- Data hash: pool_19sym, 1D, ingest manifest 2026-06-10
- Seed: 42 (shuffle baseline), 1337 (PBO partition)

## 11. Sonraki Adım

1. Bu hipotezi pre-registration commit'i yap.
2. `backtest/engine.py` ile single-pass run (no sweep).
3. SOP-3 robustness suite (zorunlu 8 test).
4. Karar matrisi:
   - Tüm gate ✓ + \|ρ\| ≤ 0.25 → **Lab tournament** (cross-strategy companion track).
   - Edge var ama \|ρ\| > 0.25 → **iterate-v2** (long-side ekle, trend filtresini kaldır → daha bağımsız sinyal).
   - Edge var ama DD/PF kötü → **iterate-v2** (SOP-4b — risk reduction).
   - Edge yok (Sharpe ≤ 0 OOS) → **REDDET**, learning.md'ye 3-satır neden.

## 12. Lab/Risk Officer'a Sorular

- @lab_scientist: vsa_climax_test 30-günlük live PnL serisi mevcut mu? Korelasyonu *backtest-vs-backtest* yerine *backtest-vs-live* hesaplayabilir miyiz? (Daha güvenilir, ama veri kıt.)
- @risk_officer: Short-only stratejiyi 19sym × MaxDD %22 ile portföye eklersek mevcut champion'larla concentration limit'i zorlar mı? `max_concurrent_short` gate var mı?
- @adversary_engineer: Marubozu için "flash crash bar" senaryosu — 2024-08-05 Yen carry unwind'da BTC -%15 mum kapanışı marubozu olarak detect edilir mi? O bar'da SHORT entry vermek 24 saat içinde nasıl yaralanır? Stress replay önemli.
