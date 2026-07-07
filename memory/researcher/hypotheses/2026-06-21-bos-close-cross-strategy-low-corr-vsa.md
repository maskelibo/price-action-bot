---
doc_id: researcher-20260621T120000-bos-close-cross-strategy-low-corr-vsa
doc_type: hypothesis
agent_id: researcher
created_at: 2026-06-21T12:00:00Z
status: DRAFT
confidence: med
depends_on: []
blocks: []
requested_review_from: [lab_scientist, risk_officer]
tags: [hypothesis, bos, market_structure, cross_strategy_edge, low_correlation, vsa_climax_companion]
supersedes: null
hash: null
---

# Hipotez: BOS close-based n=3 — vsa_climax_test düşük-korelasyon companion

## 1. Hipotez ID
HYP-2026-06-21-bos-close-cross-strategy-low-corr-vsa
Versiyon: 0.1 (pre-registered, kod yazılmadı)

## 2. İddia (tek cümle, ölçülebilir)

> Tarihi USDT-perpetual evreninde (3y, all_liquid, survivorship-corrected, delisting dahil), **1D timeframe'de close-based n=3 BOS (Break of Structure)** sinyali — yani t-2..t arasında en az 3 close yapısal swing high'ı geçtiyse — bar `t`'de close-confirmation, giriş `t+1` open'da, SL 1.5×ATR(14), TP 3.0×ATR(14) (R:R=2), ATR(14) > median(ATR_180d) volatilite filtresi ile, son 3 yıl backtest'inde **fee 7.5bps taker + 5bps slippage dahil**:
>
> - **Net annualized return > %25** (sermaye=10k, risk_pct=0.5%, max_concurrent=8)
> - **OOS Sharpe > 1.0** (walk-forward 3y/6m, step 3m, 12 dilim)
> - **MaxDD < %30** (account equity tabanlı, daily-rolling)
> - **Profit factor > 1.40**
> - **Trade sayısı OOS ≥ 200** (istatistiksel anlamlılık)
> - **Rolling 90d returns korelasyonu (Pearson) vs vsa_climax_test < 0.30** (mutlak değer)
> - **DSR > 0.5, PBO < 0.5** (Lopez de Prado guardrails)
> - **IS Sharpe / OOS Sharpe < 2.0** (overfit guard)
> - **Shuffle baseline p < 0.05** (returns-shuffled null model)
> - üretir.

## 3. Null Hipotez (H0)

> BOS close-based n=3 sinyali, fee/slip dahil hiçbir pozitif edge üretmez (annualized return ≤ 0 veya Sharpe ≤ 0). Eğer pozitif edge varsa, **vsa_climax_test ile korelasyon ≥ 0.30** olur — yani yapısal olarak farklı görünen sinyal, aslında aynı rejimi (volatility/regime beta) yakalıyordur ve gerçek diversification kazancı vermez.

H0 reddi için **iki şart birlikte** sağlanmalı:
1. Edge gerçek (yukarıdaki metrikler ✓)
2. Korelasyon düşük (|ρ| < 0.30 OOS pencerede)

## 4. Gerekçe ve RAG Referansları

- **[Market Structure & Order Flow — chap. BOS/CHoCH] (RAG #6, score=0.568):**
  BOS close-based n=3 crypto 1D'de "Yüksek" mekanik çalışabilirlik notu almış: "Net kural, backtestable, az parametrik." 1D timeframe'de yeterli hacim verisi ve mum tamamlanma süresi → microstructure noise az. BOS, **trend-continuation** ailesi → vsa_climax_test'in (exhaustion/reversal) **yapısal zıttı**.

- **[Brooks Deep Catalog] (RAG #3, score=0.579):**
  Brooks'un reversal bar kalitesi yüksek + HTF opposition + previous SR vurgusu, BOS'un *zayıf yanını* tanımlıyor (range/whipsaw rejimi). Filtremiz `ATR(14) > median(ATR_180d)` — yani **sadece yüksek-vol rejim** — Brooks'un "trending market"e karşılık geliyor; range'i dışlıyor.

- **[Kaufman Summary — Donchian Breakout] (RAG #7, score=0.563):**
  Donchian 20-bar breakout: %35 win rate, asymmetric R-multiple (winners 3-5R, losers 1R), choppy rejimde %20-40 cumulative DD. BOS close-based ile aynı aile **ama** BOS daha sıkı (close-confirmation, n=3 yapısal); win rate hedefimiz %38-45, payoff 2R sabit. Donchian'ın **failure mode'u (whipsaw)** bizim için tehdit — vol filtresi bunun azaltıcısı.

- **[Lopez de Prado — Backtest Overfitting Guardrails] (RAG #1, score=0.582):**
  DSR < 0.5, PBO > 0.5, IS>3×OOS, parametre/sample > 1/30, walk-forward Sharpe varyansı > ort → red. Bu hipotezde **4 serbest parametre** (BOS_n, ATR_SL_mult, ATR_TP_mult, vol_filter_threshold). 200+ trade hedefi → 200/4 = 50 trade/param → 1/50 > 1/30 ✓ tatmin edici.

- **[Kaufman — MA Crossover] (RAG #4, score=0.577):**
  Long-horizon trend-capture stratejilerinin failure mode'u: "sideways market'te 4-6 ardışık whipsaw." BOS aynı patolojiye açık. Vol filtresi + n=3 close-confirmation bunun teorik panzehri.

## 5. Dependent Variables (önce kaydedildi, optimize EDİLMEZ)

| Variable | Hedef | Test |
|---|---|---|
| Net annualized return | > %25 | fee+slip dahil |
| OOS Sharpe | > 1.0 | walk-forward 12 dilim |
| MaxDD (equity-based) | < %30 | daily-rolling |
| Profit factor | > 1.40 | OOS toplam |
| OOS trade sayısı | ≥ 200 | istatistik |
| Korelasyon vs vsa_climax_test (90d rolling, Pearson, mutlak) | < 0.30 | her 30d step |
| DSR | > 0.5 | Lopez |
| PBO | < 0.5 | Bailey-Lopez |
| IS/OOS Sharpe oranı | < 2.0 | overfit guard |
| Shuffle baseline p | < 0.05 | returns-shuffled null |

## 6. Independent Variables (optimize edilebilir, ama sınırlı)

| Param | Aralık | Adım | Toplam |
|---|---|---|---|
| BOS_n (lookback close sayısı) | {2, 3, 4} | — | 3 |
| ATR_SL_mult | [1.0, 2.5] | 0.5 | 4 |
| ATR_TP_mult | [2.0, 4.0] | 0.5 | 5 |
| vol_filter (× median ATR_180d) | {0.8, 1.0, 1.2, 1.5} | — | 4 |

**Toplam grid:** 3×4×5×4 = **240 kombinasyon**.
**Optuna n_trials cap:** 100 (TPE + Median pruner). **Bonferroni m=100, α=0.05 → α'=0.0005.**

**Curve-fit guardrail:** Best params parametre uzayının **sınırında** olursa (örn. ATR_SL_mult = 1.0 veya 2.5) → hipotez ŞÜPHE; aralığı genişlet ve yeniden test et. Genişletilmiş aralıkta best aynı sınırda kalmaya devam ederse → red (curve-fit kırmızı bayrak #2, learning.md).

## 7. Beklenen p-value

- **Ham (uncorrected):** < 0.01 (vs shuffle baseline)
- **Bonferroni-corrected (m=100 trials):** < 0.05 (yani ham p < 0.0005)
- **DSR (Lopez):** > 0.5

Bu üçü birden geçilemezse — terfi yok.

## 8. Stop Criteria (research budget abort)

Aşağıdakilerden **herhangi biri** olursa araştırmayı **derhal** sonlandır, gerekçeli arşivle:

1. **In-sample Sharpe < 0.5** ilk grid taramasında → edge yok, derinleşme verimsiz.
2. **OOS Sharpe < 0.6** walk-forward 12 dilimden 4+'unda negatif → istikrarsız.
3. **IS/OOS Sharpe > 3.0** → ağır overfit (Lopez kriteri #4 kırmızı).
4. **Korelasyon ≥ 0.50** vsa_climax_test ile → zaten edge'in olsa bile diversification yok, mevcut bota ekleme.
5. **Trade sayısı < 100 OOS** → istatistik anlamsız.
6. **Best params sınırda + genişletilmiş aralıkta da sınırda** → curve-fit.
7. **Stress dilimlerinden (2022-05 LUNA, 2022-11 FTX, 2024-08 Yen) en az 2'sinde MaxDD > %40** → tail-risk kabul edilemez.
8. **Lookahead causality test fail** → kod hatası, hipotez geçersiz (yeni hipotez yaz).

## 9. Curve-fit Şüphe Notları (paranoid self-review)

Bu hipotezin **kendi içindeki riskleri** (yazılırken gözlenenler):

- **🚨 Vol filtresi `median(ATR_180d)` çoklu eşik denemesine (0.8/1.0/1.2/1.5) açık** → yumuşak filtre; sadece **0.8 ve 1.2** ile test edip best'i seçmek free parameter inflation yapar. Bonferroni'ye dahil.
- **🚨 R:R=2 sabit ama TP_mult/SL_mult oranı 4/1.5 = 2.67'den 2.0/2.5 = 0.8'e kadar oynayabilir** → asimetrik exploit'e açık. Kısıt: **TP_mult / SL_mult ∈ [1.5, 2.5]** zorunlu (raporda göster).
- **🚨 n=3 BOS, momentum-flag'lerle (RAG #10 Mat Hold, %74 continuation) overlap eder** — eğer trade'lerin %50+'sı aynı bar/sembolde Mat Hold tetiklerken oluyorsa "BOS edge" değil "trend persistence" edge'i bulduk demektir → trade-level ortogonality testi zorunlu (Mat Hold detector ile overlap < %30).
- **🚨 vsa_climax_test ile düşük korelasyon "anti-zorlanmış" olabilir** — yani BOS-only universe subset'inde test edersek (yüksek vol semboller) artık vsa_climax tetiklenmez ve korelasyon yapay düşük çıkar → korelasyonu **trade-zaman serisinde değil, daily portfolio returns serisinde** ölç (her gün her iki stratejinin pozisyonlu/pozisyonsuz P&L'i).
- **🚨 1D timeframe — 3 yıl = ~1095 bar/sembol** — 30 sembol = 32850 bar; ama BOS sinyali ~%2 bar'da tetiklenirse 657 sinyal → grid başına ~3 sinyal/dilim → çok az. Trade sayısı şişirilirse multi-symbol bias.

Bu 5 risk → robustness suite + raporda **explicit table** olarak göster. Gizleme.

## 10. Reproducibility Stamp Plan

- `git_hash`: backtest commit'inde stampla
- `config_hash`: hipotez YAML'ın SHA256
- `data_hash`: DuckDB tablo modify_ts + symbol-list hash
- Rapor: `reports/research/bos-close-cross-strategy-low-corr-vsa-2026-06-21.html`

## 11. Sonraki Adımlar (sıralı)

1. Bu doc'u commit et — hipotez dondurulur.
2. `configs/strategies/bos_close_cross_strategy.yaml` taslak (sadece grid spec).
3. `backtest/engine.py` çalıştır (240 kombinasyon yok, Optuna 100 trial cap).
4. Walk-forward 3y/6m step 3m (12 dilim).
5. Robustness suite TAMAMI (SOP-3): param perturb, symbol-out CV, regime split, stress, shuffle, Bonferroni.
6. Trade-level Mat Hold overlap testi (özel — bu hipoteze).
7. Daily-returns-based korelasyon zaman serisi vs vsa_climax_test.
8. Karar: terfi / iterate (SOP-4b) / red, gerekçeli.

## 12. Expected Outcome Distribution (kendi tahmin)

- **P(red, edge yok):** %50 — BOS close-based çok denenmiş bir kalıp, eğer 1D'de düz net edge olsaydı literatürde daha güçlü gözlenirdi.
- **P(edge var ama korelasyon yüksek):** %25 — trend rejimi vsa_climax'i de tetikliyor olabilir (climax sonrası fade = trend reversal).
- **P(terfi adayı):** %15 — gate'leri komple geçme olasılığı düşük.
- **P(iterate v2 gerekir):** %10 — pozitif edge ama DD/Sharpe gate'lerinden 1'i fail (SOP-4b kapsamı).

> Kendi tahminime göre **%75 ihtimalle red veya iterate**, **%15 ihtimalle terfi**. Bu sağlıklı; yüksek terfi beklentisi p-hacking endişesi olur.
