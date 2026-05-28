---
doc_id: researcher-20260527T080000-liquidity-grab-reversal-15m-reclaim
doc_type: hypothesis
agent_id: researcher
created_at: 2026-05-27T08:00:00Z
status: DRAFT
confidence: low
depends_on: []
blocks: []
requested_review_from: [lab_scientist, adversary_engineer, risk_officer]
tags: [liquidity_grab, stop_hunt, reversal, 15m, intraday, smc, ict]
supersedes: null
hash: null

hypothesis_id: 2026-05-27-liquidity-grab-reversal-15m-reclaim
date: 2026-05-27
author: researcher_agent (claude-opus-4-7)
version: 0.1
parent_strategy: none (intraday companion to HYP-2026-05-12-002 daily variant)
backtest_possible: true
data_requirements: [15m_ohlcv, 1h_ohlcv (regime filter)]
expected_correlation_w_top10: low (< 0.30) — intraday, mean-revert flavored
---

# HYP-2026-05-27-001 — Liquidity Grab + Reclaim Reversal (15m intraday)

## 0. Honest Caveats (PEŞİN)

- **RAG corpus boş çıktı.** Hiçbir dış literatür referansı sağlanamadı. Bu **özgün bir iddia**
  değil; bu **destek olmadan yazılmış bir iddia**. SOP-5 başına bu hipotezi yazmak yerine
  reddetmek meşru bir seçenekti. Yine de pre-register ediyorum çünkü mevcut günlük varyant
  (HYP-2026-05-12-002, FVG re-entry, 1D) intraday tarafa düşürülebilir; *eğer* IS edge
  varsa OOS + robustness suite'i çürütecektir.
- **Mevcut overlap:** `2026-05-12-liquidity-sweep-displacement-fvg.md` (1D, FVG mitigasyon).
  Bu hipotez **15m timeframe + sade reclaim** — FVG mekaniği YOK, daha sade trigger,
  daha çok trade, daha yüksek noise. Korelasyon çıkarsa Lab reddetmeli.
- **Curve-fit risk önceden bildirim:**
  - 5 independent var × her biri ~6-10 değer → grid ≈ 6^5 = 7,776 kombinasyon. Bonferroni'siz
    şans WR > %55 trivially. Bunu en başından kabul ediyorum.
  - Mean-revert tarzı setup → 2022 bear gibi tek bir rejimde over-perform edebilir.
    Regime split zorunlu.

---

## 1. Pre-Registered İddia (TEK CÜMLE, ölçülebilir)

> **15m timeframe'de**, son **N=20 bar (5 saat) içindeki swing high/low'u**
> **0.15-0.50 ATR(14) kadar penetre eden ama aynı 15m mumun close'unda swing seviyesinin
> içine (long: swing_low üstüne / short: swing_high altına) geri çekilen bir mum**
> ("liquidity grab + reclaim") sonrasında, **1 sonraki mumun open'ında ters yönde giriş**,
> **SL = grab uç noktası ± 0.25 ATR**, **TP = 2R**, ile **2022-01-01 / 2025-04-30**
> top-30 USDT-perpetual evreninde, **fee 7.5bps taker + 5bps slip** dahil:
>
> - **Net annualized return ≥ +%30** (her sembol ayrı; sembol-bağımsız agg ortalamasıyla)
> - **OOS Sharpe ≥ 1.0** (walk-forward, 3y/6m, step 3m)
> - **MaxDD ≤ %25**
> - **Profit factor ≥ 1.30**
> - **Trade sayısı ≥ 400** (istatistik için, sembol-evren toplamı, OOS dilimleri)
> - **Shuffle null'a karşı p < 0.01 (Bonferroni sonrası p < 0.05)**

**Yön:** çift yönlü (long upside grab + reclaim → long; short upside grab + reclaim → short
mantığı simetrik — short tarafta upside swing grab + reject sonrası short).

---

## 2. Null Hipotez (ne olursa hipotez çürür)

H0: 15m liquidity grab + reclaim trigger setinin getirisi, **aynı evrende rastgele 15m
bar girişlerinden farkı yoktur**. Operasyonel test:
- Trigger zamanlarını shuffle ettiğin (returns_shuffled) null modeli **Sharpe ≥ stratejinin
  Sharpe'ı** ise red.
- Win rate trigger seti üzerinde ≤ **%48** (baseline rastgele 2R/1R sym = %50, fee/slip
  düşülmüş ≈ %52 BE) → red.

---

## 3. Dependent Variables (önceden listelenmiş — değiştirilmeyecek)

| Metric | Hedef | Hard floor |
|---|---|---|
| Net annualized return | ≥ +%30 | ≥ +%15 |
| OOS Sharpe (walk-forward avg) | ≥ 1.0 | ≥ 0.7 |
| MaxDD (intra-WF) | ≤ %25 | ≤ %35 |
| Profit factor | ≥ 1.30 | ≥ 1.15 |
| Win rate | info | — |
| Avg trade duration | info | < 24h (intraday tutarlılık) |
| Trade count (OOS toplam) | ≥ 400 | ≥ 200 |

Bunlardan **3 / 7'si hard floor'un altında kalırsa** strateji REDDEDİLİR — gate hesabı yok.

---

## 4. Independent Variables (parametre uzayı — önceden donduruldu)

| Param | Aralık | Adım | Trial sayısı |
|---|---|---|---|
| swing_lookback_bars (N) | 12, 16, 20, 24, 32 | discrete | 5 |
| penetration_atr_min | 0.10, 0.15, 0.20, 0.30 | discrete | 4 |
| penetration_atr_max | 0.40, 0.50, 0.70, 1.00 | discrete | 4 |
| sl_atr_buffer | 0.20, 0.25, 0.35, 0.50 | discrete | 4 |
| rr_target | 1.5, 2.0, 2.5, 3.0 | discrete | 4 |
| regime_filter (1h ATR%) | off, top70%, bottom70% | discrete | 3 |

**Toplam grid = 5×4×4×4×4×3 = 3,840 kombinasyon.**
**Optuna n_trials = 120 (TPE + Median pruner)** — grid'in %3.1'i. Curve-fit bu sayıyla
zaten yüksek; **Bonferroni düzeltmesi p-eşiği = 0.05 / 120 = 4.2e-4** beklenir.

**Parametre uzayı sınır kontrolü (overfit bayrağı):** best params parametre aralığının
EN UÇ değerinde değil ORTAYA yakın çıkmalı — uçta çıkarsa o aralık genişletilir veya
hipotez reddedilir.

---

## 5. Beklenen p-value

- Raw shuffle null'a karşı: p_raw ≤ 0.01 olmalı.
- Bonferroni (n=120 trial): p_adj ≤ 0.05 olmalı.
- Benjamini-Hochberg FDR(q=0.10): top trial seçimi düzeltme sonrası geçer olmalı.

Hiçbir p-value 0.05'in altına Bonferroni sonrası düşmezse → red.

---

## 6. Stop Criteria (araştırma terkedilir)

In-sample backtest sonucu aşağıdakilerden HERHANGİ BİRİ → durdur ve red et:

1. **IS Sharpe < 0.5** (parametrelere bakılmaksızın, default param ortalamasında).
2. **Trade count < 200** (15m + 30 sembol + 3 yıl yeterince trade üretmeli, yoksa
   trigger tanımı yanlış).
3. **Tek bir sembolün P&L'in > %40'ını üretmesi** (concentration → şans).
4. **Best params parametre uzayının sınırında** (overfit bayrağı).
5. **IS Sharpe / OOS Sharpe oranı > 2.0** (curve-fit kanıt).
6. **Bonferroni sonrası p > 0.05** (multiple testing).
7. **2024 Q4 + 2025 Q1 (en taze OOS dilim) negatifse** (recency bayrağı).
8. **HYP-2026-05-12-002 (FVG variant) ile trade-level Spearman corr > 0.5** (overlap →
   bu hipotez bağımsız değer üretmiyor).

---

## 7. Robustness Suite (zorunlu — SOP-3)

| Test | Eşik |
|---|---|
| Walk-forward (3y/6m, step 3m) | ≥ 10/12 dilim pozitif Sharpe |
| Param perturb (±%10, 50 seed) | ortalama Sharpe kayıp ≤ %25 |
| Symbol-out CV (leave-one-out top-30) | min Sharpe ≥ 0.6 |
| Regime split (bull / bear / range, 1h ATR%) | ≥ 2/3 rejimde pozitif Sharpe |
| Stress periyodları (LUNA 2022-05, FTX 2022-11, USDC 2023-03, Yen 2024-08) | her dilimde MaxDD ≤ %15 |
| Shuffle baseline (returns shuffle, 1000 iter) | p < 0.01 |
| Bonferroni (n=120) | p_adj < 0.05 |
| Lookahead causality test | `detector(df[:t+1])[t] == detector(df)[t]` her t için |
| Survivorship | Universe time-aware: delisted semboller dahil |

---

## 8. Curve-Fit Şüphe Notu (öz-eleştiri)

Bu hipotezin curve-fit'e en açık tarafları:
1. **5 parametre × ~4 değer** — kombinatorik patlama; Optuna 120 trial dahi grid'in %3'ünü
   tarar. Aralık dışında olduğum bilinmeyen yerler var.
2. **15m intraday → fee/slip baskın olabilir.** Her trade'in EV'si küçükse 7.5bps + 5bps
   = 12.5bps tek yön, round-trip ≈ 25bps. 2R hedefte SL = 0.25 ATR, trade ATR seviyesinde
   stop'a girip çıkıyorsa fee oranı ROI'nin %30-40'ını yiyebilir.
3. **"Reclaim" tanımı esnek.** "Close swing_low'un üstünde" yeterli mi yoksa
   "close swing_low + 0.X ATR" mi? Tek tanımla pre-register ediyorum: **plain close >
   swing_low** (long için). Daha gevşek/sıkı tanım test edilmeyecek (HARDCODE).
4. **N=20 bar swing tanımı** — kafadan attığım sayı. RAG yok, "ICT 20 bar swing standart"
   diyemem. Lookback'i de optimize ediyorum (5 değer) → cherry-pick risk.

Bu hipotezin **a priori başarı olasılığını %25** koyuyorum. Reddedilirse şaşırmam.

---

## 9. Karar Çerçevesi (boş — backtest sonrası doldurulacak)

```
1. Backtest sonucu: ...
2. Robustness suite sonucu: ...
3. Karar: terfi / red / belirsiz
4. Gerekçe: ...
5. Lab teslim edilecek mi: evet/hayır
```

---

## 10. Reproducibility

- git_hash: TBD (backtest run anında dondurulur)
- config_hash: TBD
- data_hash: TBD (15m universe snapshot)
- Backtest seed: 42
- Optuna seed: 42
- Python env: requirements.lock @ backtest run timestamp

---

**Pre-registration commit edildi: 2026-05-27T08:00:00Z. Bundan sonra hipotezin maddeleri
DEĞİŞTİRİLEMEZ. Sadece reddedilebilir veya doğrulanabilir.**
