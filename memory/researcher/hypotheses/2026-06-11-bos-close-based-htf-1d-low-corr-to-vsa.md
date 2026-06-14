---
doc_id: researcher-20260611T000000-bos-close-based-htf-1d-low-corr-to-vsa
doc_type: hypothesis
agent_id: researcher
created_at: 2026-06-11T00:00:00Z
status: PROPOSED
confidence: med
depends_on: []
blocks: []
requested_review_from: [lab_scientist, risk_officer]
tags: [hypothesis, cross_strategy, low_corr, bos, market_structure, 1d, vsa_diversifier]
supersedes: null
hash: null
---

# HYP-2026-06-11 — BOS (Break of Structure, close-based, n-swing, 1D) as Low-Correlation Diversifier to `vsa_climax_test`

## 1. Seed & Motivation

Aktif strateji `vsa_climax_test` **volume-fade / mean-reversion** sınıfından. Portföye eklenecek diversifier'ın **structurally orthogonal** olması şart; aksi halde DSR-shrinkage'i kötüleştirir ve effective N düşer. Klasik orthogonal aday: **trend-continuation, swing-structure trigger, volume bağımsız**. BOS bunu mekanik olarak karşılar (RAG #6: "BOS close-based, n=3 → mechanical workability: HIGH").

## 2. Hypothesis (pre-registered, fixed before any code run)

> **Iddia:** 2022-01-01 → 2025-06-30 in-sample / 2025-07-01 → 2026-06-10 out-of-sample, 19-sembol all-liquid USDT-perpetual evreninde, **1D timeframe** üzerinde, BOS-long sinyali (kapanış > son n-bar swing high, n ∈ {3,5,7,10}) + ATR-stop (k×ATR(14), k ∈ {1.5, 2.0, 2.5}) + 10-bar opposite swing trailing exit konfigürasyonu, fee=7.5bps + slip=5bps dahil:
>
> 1. **OOS net annualized return** ≥ **+18 %/yıl** (sabit-fraksiyon %1 risk/trade, non-compounding ölçüm)
> 2. **OOS Sharpe** ≥ **0.80** (Chan retail-realistic single-asset eşiği, RAG #9)
> 3. **OOS MaxDD** ≤ **20 %** (account-equity-base, trade-MC bantlı)
> 4. **|Spearman ρ(BOS daily PnL, vsa_climax_test daily PnL)|** < **0.30** (rolling 90d, OOS dilimi)
> 5. **DSR (Lopez)** > **0.50** ve **PBO** < **0.50**
> 6. **Profit factor** > **1.3**, **trade sayısı** ≥ **120** (her semboldeki ortalama ≥ 6 trade)

**Tek bir madde dahi sağlanmazsa hipotez REDDEDİLİR — terfi adayı çıkmaz.**

## 3. Null Hypothesis & Falsification

- **H0:** BOS-long sinyali, fee+slip sonrası, shuffle-baseline'a göre istatistiksel anlamlı edge üretmez (shuffle p ≥ 0.05).
- **H0' (correlation):** BOS PnL serisi vsa_climax_test PnL serisiyle |ρ| ≥ 0.30 — yani diversifier sıfatını hak etmez.
- **Falsification koşulları (her biri tek başına yeter):**
  - IS Sharpe < 0.5 → araştırma derhal terk edilir (Lopez red flag → IS bile geçemiyorsa OOS umut yok)
  - IS/OOS Sharpe oranı > 3.0 → curve-fit (Lopez red flag #4) → red
  - Walk-forward dilim oranı pozitif/toplam < 60 % → unstable edge → red
  - Stress dilim (LUNA 2022-05, FTX 2022-11, USDC depeg 2023-03, Yen carry 2024-08) içinde MaxDD > 25 % → tail-fragile → red
  - Shuffle-baseline p ≥ 0.05 → şans → red
  - Bonferroni-corrected p ≥ 0.00417 (= 0.05 / 12 trial) → multiple-testing inflation → red
  - Trade sayısı < 100 → underpowered → red

## 4. Independent Variables (grid — coarse, 12 nokta, no sweeping past this)

| Param | Grid | Adım | Toplam |
|---|---|---|---|
| `swing_n` (BOS lookback) | {3, 5, 7, 10} | discrete | 4 |
| `atr_sl_mult` (k) | {1.5, 2.0, 2.5} | 0.5 | 3 |
| Toplam kombinasyon | | | **12** |

**Curve-fit guardrails (pre-committed):**
- Grid 0.01-adımlı değil, **0.5-adımlı**. Daha ince grid REDdir (overfit).
- Best-params grid sınırında çıkarsa (`swing_n=3` veya `=10`, `k=1.5` veya `=2.5`) → bayrak: kalıp asıl değerini kanıtlamadı, grid'i tek seferlik genişletmek YASAK (pre-reg ihlali). Hipotez red.
- Bonferroni: n=12 trial → corrected p_threshold = 0.05/12 = **0.00417**.

## 5. Dependent Variables (pre-registered metrics)

| Metric | Hedef (OOS) | Hesap | Kaynak |
|---|---|---|---|
| Annualized net return | ≥ +18 % | trade NetPnL Σ / (365.25 × N_yıl) × 365.25 / equity_base | gate |
| Sharpe ratio | ≥ 0.80 | daily-PnL μ/σ × √365 | Chan RAG #9 |
| MaxDD (account-equity base) | ≤ 20 % | rolling peak-trough on equity curve | gate |
| Profit factor | ≥ 1.3 | Σ wins / Σ |losses| | gate |
| Trade count | ≥ 120 | tüm sembol × tüm OOS | power |
| Spearman ρ vs vsa_climax | < 0.30 | rolling 90d daily PnL | diversifier |
| DSR (Lopez) | > 0.50 | Bailey-Lopez formula | red flag |
| PBO | < 0.50 | combinatorial CV | red flag |
| IS/OOS Sharpe oranı | < 2.0 | IS_Sharpe / OOS_Sharpe | curve-fit |
| Walk-forward (+) dilim oranı | ≥ 60 % | pos-slice count / total | stability |

## 6. Expected p-values

- **Shuffle-baseline:** p < 0.01 (target)
- **Bonferroni-corrected (n=12):** p < 0.00417 (target)
- **Beklenti:** ham p ≤ 0.005 ürettiğinde Bonferroni hâlâ p < 0.06 — yani sıkı eşiği geçmesi için gerçek + güçlü edge gerek. Beklentim **düşük güven (med-low)**: BOS klasik trend kalıbı, 1D kripto'da ADX-yüksek rejim oranı düşük (Donchian zayıflığıyla aynı failure mode — RAG #7: "choppy/range-bound rejimde back-to-back whipsaw").

## 7. Stop Criteria (early-abort, sırayla kontrol)

1. **Veri hazırlık aşamasında:** OHLCV gap'leri > %1 toplam barlar veya delisting'siz universe → çalışmayı başlatma.
2. **In-sample backtest sonrası:**
   - IS Sharpe < 0.5 → ABORT, gerekçeli arşiv `learning.md`'ye.
   - Trade sayısı IS'de < 80 → underpowered → ABORT.
3. **OOS / walk-forward:**
   - IS/OOS Sharpe oranı > 3.0 → ABORT (curve-fit teşhisi).
   - Walk-forward pos-slice < 60 % → ABORT.
4. **Stress test:**
   - Herhangi bir stress dilimde drawdown > 25 % → ABORT (tail-fragile).
5. **Correlation gate:**
   - |ρ vs vsa_climax_test| ≥ 0.30 → ABORT (diversifier hipotezinin temel iddiası çürür; alfa olsa bile bu hipotez kapsamında değil).
6. **Final Bonferroni:**
   - p_corrected ≥ 0.00417 → ABORT (multiple-testing inflation).

Her ABORT noktasında: 3-satır gerekçe + `seed_abort_log.jsonl`'a kayıt. **Geri dönüp grid'i genişletmek pre-reg ihlalidir** (re-research yeni doc_id ile başlar).

## 8. Reproducibility Anchors

- `git_hash`: <pre-commit fix at submission>
- `config_hash`: `bos_close_n3-10_atr1.5-2.5_1d_19sym.yaml`
- `data_hash`: sec53_pool_v11 (19-sym, survivorship-safe) — manifest hash test-day captured.
- `universe`: `data.universe.build_universe(date)` ile zaman-bilinçli (delisting'ler dahil).
- `seed`: 42 (Optuna deterministic) — sadece tek seed; param search değil, **grid sweep** olduğu için seed tek tur yeterli.

## 9. RAG Refs (kullanılanlar)

- **#1 (Lopez de Prado):** 6-kriter red-flag listesi (DSR/PBO/MinBTL/IS-OOS-Sharpe/param-sample/walk-forward-variance). Bu hipotezin 3., 5., guardrail bölümleri buraya dayanır.
- **#3 (Brooks):** n-bar high/low aşımı + reversal mekanik tanımı; BOS bunun "kapanış" varyantıdır (reversal değil, continuation).
- **#6 (Market Structure):** BOS close-based, n=3 → "High" mechanical workability tag — bu hipotezin teknik temeli.
- **#7 (Kaufman Donchian):** %35 WR + 3-5R winners + choppy-rejim whipsaw failure modu → expected-edge çerçevesi ve risk farkındalığı.
- **#9 (Chan):** OOS Sharpe ≥ 0.8 single-asset gate threshold'ı.

## 10. RAG Refs (bilerek kullanılmayanlar)

- **#2 (Inside bar) / #8 (Bear Marubozu) / #10 (3-bar consolidation):** Bunlar candle-based, mean-reversion/continuation karışık; vsa_climax_test ile yapısal benzeşim riski var (volume/candle-form çakışması). Diversifier hipotezi için zayıf seçim.
- **#4 (MA crossover) / #5 (volatility breakout):** Aynı gün başka hipotezler bunları zaten araştırıyor (`ma-crossover-50-200`, `kaufman-volatility-breakout-1h`). Tekrar değil orthogonal aday lazım.

## 11. Curve-Fit Şüphesi (kendi paranoyam, pre-commit)

- 12 kombinasyon **çok az değil ama az** — Bonferroni geçmesi için ham p ≤ 0.004 lazım, bu BOS gibi klasik kalıp için **muhtemelen geçilemez**. Beklenti: RED.
- BOS-long kalıbı tek başına 2022 boğa + 2023-Q4 / 2024-Q1 + 2025-Q1 trendlerinden kâr alabilir; bu **regime-conditional edge** — düz dilimlerde whipsaw birikir. Eğer pozitif edge sadece 2-3 dilimden geliyorsa "regime split" testi kıracaktır (regime-split sahnesinde bull dilim ✓, range dilim ✗).
- **Beklenen sonuç:** İyi senaryo → red ama "regime-conditional edge" notuyla, gelecek "trend-regime gated" hipoteze yön gösterir. Kötü senaryo → IS de zayıf, BOS-only 1D kripto'da diversifier olarak ölmüş.

## 12. Decision Frame (önceden yazılı)

```
1. RAG'den ne öğrendim? → BOS close-based n=3 mechanically clean, ama trend-rejim bağımlı.
2. Hipotezim ne? → 18%/yıl OOS + Sharpe 0.8 + ρ<0.30 + DSR>0.5, 12-grid.
3. Null ne? → shuffle p≥0.05 veya |ρ|≥0.30.
4. Pre-registered metrikler: §5 tablosu.
5. Backtest sonucu: <çalıştırıldığında doldurulur>
6. Robustness suite: <çalıştırıldığında doldurulur>
7. Karar: REDDET / TERFİ / İTERATE (SOP-4b)
8. Gerekçe: ...
```

## 13. Iterate Politikası (SOP-4b uyarınca)

Eğer backtest pozitif aylık ROI üretir AMA DD veya başka gate kötüyse → **RED YASAK**, en az 1 iterate v2 hipotezi açılır. Olası iterate yolları (önceden listelendiği için pre-reg ihlali değil):

1. **Risk reduction:** risk_pct 1% → 0.5%, max_concurrent cap.
2. **Trend-regime filter:** HTF EMA200 slope > 0 (1W) — sadece major uptrend.
3. **Stop trailing tightening:** 1R sonrası BE-protect.
4. **Symbol subset:** sadece BTC + 2 düşük korelasyonlu alt (boğa-rejim duyarsız).

Her iterate, v2/v3/v4 doc_id ile **ayrı** pre-registration olur — bu doc onları kapsamaz.

## 14. Sign-off Beklentisi

- Lab_scientist: tournament setup'ı kabul ediyor mu (gate uyumlu mu)?
- Risk_officer: 1D timeframe + BOS sinyali leverage/correlation gate'leriyle uyumlu mu?

İki ACK gelmeden backtest engine tetiklenmez.
