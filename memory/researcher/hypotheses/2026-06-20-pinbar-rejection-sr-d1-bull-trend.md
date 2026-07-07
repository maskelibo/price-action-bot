---
doc_id: researcher-20260620T000000-pinbar-rejection-sr-d1-bull-trend
doc_type: hypothesis
agent_id: researcher
created_at: 2026-06-20T00:00:00Z
status: DRAFT
confidence: med
depends_on: []
blocks: []
requested_review_from: [lab_scientist, risk_officer]
tags: [hypothesis, pin_bar, support_resistance, daily, with_trend, pre_registration]
supersedes: null
---

# Hypothesis — Pin Bar Rejection at Horizontal S/R, D1 With-Trend Bullish

- **ID:** HYP-2026-06-20-pinbar-sr-d1-bull-trend
- **Tarih:** 2026-06-20
- **Versiyon:** 0.1 (pre-registration; backtest öncesi LOCK)
- **Yazar:** researcher
- **Reproducibility:** git=<stamp@run>, config_hash=<sha256 of frozen grid>, data=<duckdb ohlcv-1d manifest @ run>

---

## 1. İddia (tek cümle, ölçülebilir)

D1 timeframe'de, **1W EMA50 üzerinde** (with-trend filter), önceki **90 D1-bar penceresinde** tanımlanmış horizontal S/R kümesinin (≥3 swing-touch, ≤0.5 ATR(14) tolerans) en yakın seviyesine **≤ 0.5 ATR(14)** yakınlıkta oluşan **bullish pin bar** (kriter: `wick_lower ≥ 0.66 × range`, `|close − open| ≤ 0.33 × range`, close üst 1/3 dilim içinde, `wick_upper ≤ 0.25 × range`) için "bar kapanışı kararı + bir sonraki bar açılışında market entry, **SL = pin_low − 0.15 × ATR(14)**, **TP = entry + 2.0R**" kuralıyla; 2022-01-01 → 2025-12-31 dört-yıllık USDT-perpetual evreninde (≥25 sembol, survivorship-bias düzeltilmiş, delisting'ler dahil), 7.5 bps taker + 5 bps slippage modeliyle, sabit-fraksiyonel **%1 risk/trade** altında:

- **Net annualized return ≥ %15** (fee+slip dahil, equity-base)
- **Annualized Sharpe ≥ 0.8** (günlük log-return)
- **MaxDD ≤ %22** (equity-base; cumulative-PnL DEĞİL — CT-RSK-01 disiplini)
- **Profit factor ≥ 1.3**
- **N_trades ≥ 150** (istatistiksel güç tabanı)
- **Shuffle-baseline p < 0.01** (returns reshuffle, 1000 iter)

**Primary metric:** Sharpe (return tek başına curve-fit yem'i).

---

## 2. Null Hipotez (H0)

Pin-bar-at-S/R sinyali, aynı evren + aynı SL/TP kuralı + **random-bar-entry** baseline'a karşı net Sharpe açısından istatistiksel olarak ayırt edilemez (**Welch's t-test, α = 0.01**, Bonferroni post-correction n = 4 dependent metric için).

H0 reddedilemezse → hipotez reddedilir, iterate denenmez.

---

## 3. Gerekçe — RAG referansları

- **[Grimes summary §"Pin Bar"]** — wick:body ≥ 2:1, kapanış aksi 1/3 içinde; en yüksek beklenti "with-trend pullback bittiğine işaret eden pin bar."
- **[Daily Price Action pin bar strategy §"validity factors"]** — pin bar geçerliliği `key level × trend alignment × room-to-move` çarpan etkisinde; daily TF intraday'den daha güvenilir.
- **[Daily Price Action pin bar SL placement]** — SL pin bar tail ucunun 0.1-0.2 ATR ötesi, premature stop-out koruması.
- **[Brooks deep catalog]** — standalone pin bar (grafik ortasında) edge'siz; S/R + prior swing zorunlu confluence.

RAG fundamentalleri pin-bar'ı **with-trend + S/R kontekst** olmadan satmıyor; bu hipotez exact o intersection'ı test ediyor.

---

## 4. Dependent Variables (pre-registered, kasten az)

| Metric | Target | Yön |
|---|---|---|
| Net annual return (equity-base) | ≥ %15 | max |
| Sharpe (daily, annualized) | ≥ 0.8 | max (primary) |
| MaxDD (equity-base) | ≤ %22 | min |
| Profit factor | ≥ 1.3 | max |
| Win rate | info-only | — |
| Avg R-multiple | info-only | — |

Kasten 4 ölçülebilir hedef (Bonferroni n=4). "Kitchen sink metric panel" curve-fit yem'idir.

---

## 5. Independent Variables — parametre uzayı KASTEN DAR

| Param | Değerler | Nokta sayısı | Gerekçe |
|---|---|---|---|
| `pin_wick_min` | {0.60, 0.66, 0.70} | 3 | Grimes 2:1 ile Daily PA 2/3 sınırı |
| `pin_body_max` | {0.30, 0.33} | 2 | tail dominance kriteri |
| `sr_proximity_atr` | {0.3, 0.5, 0.7} | 3 | "near level" operasyonel tanımı |
| `swing_lookback_d` | {60, 90, 120} | 3 | mevsimsellik tamponu |
| `trend_filter` | {1W_EMA50, 1W_EMA200, NONE} | 3 | filter etkisini izole eder (NONE = ablation) |
| `atr_period` | {14} | 1 (sabit) | Wilder konvansiyon |
| `sl_buffer_atr` | {0.15} | 1 (sabit) | tail ucu ötesi |
| `tp_R` | {1.5, 2.0, 2.5} | 3 | farklı R hedefleri |

**Toplam grid = 3·2·3·3·3·3 = 486 config.**
**Bonferroni α_per_config = 0.01 / 486 = 2.06e-5.** Bu eşiği geçemeyen hiçbir config "anlamlı" sayılmaz.

**Adım granülaritesi kasten kalın** (0.01 değil 0.33-0.5 jump); ince grid curve-fit alarmı.

---

## 6. Beklenen p-value (pre-committed)

- Shuffle-baseline returns: **p < 0.01**
- Bonferroni-corrected (n=486): **p_adj < 0.05**
- Walk-forward 12 dilimden **≥ 8 pozitif Sharpe** (binom p < 0.05)

---

## 7. Stop Criteria — derhal terk

Aşağıdakilerden BİRİ tetiklendiğinde **hipotez derhal terkedilir** (iterate yok, gerekçeli arşiv):

1. `tests/test_lookahead.py` REJECT — lookahead/leakage var.
2. Universe survivorship-bias'lı (delisted dahil değil).
3. **In-sample Sharpe < 0.4** — robustness'a girmeye değmez.
4. **Best config parametre uzayı sınırında** (örn. `tp_R = 2.5` en üstte): grid darmış, kalıbın gerçek optimumu görünmüyor.
5. **IS−OOS Sharpe farkı > %50** (relative): overfit.
6. **Walk-forward dilim CV > 1.0**: rejim-fragil.
7. **N_trades < 100**: güç yok.
8. **2022-05 (LUNA) + 2022-11 (FTX) stress dilimlerinde MaxDD > %30 her ikisinde**: tail-fragil.

---

## 8. Iterate Bütçesi (SOP-4b)

Eğer aylık ROI > 0 ama yukarıdaki bir terfi gate'i kıl payı kaçırılırsa (örn. MaxDD %25 — %22 hedefini 3pt aştı), TEK iterate izinli:
- `risk_pct 0.01 → 0.005`
- `+ confluence_score ≥ 2` filter (S/R + trend + room-to-move skoru)

İterate de gate'i geçemezse RED. Maks 1 iterate — pin-bar literatürü zaten kalıbı önemli ölçüde "geliştirilmiş" şeklinde değil "var/yok" şeklinde tanımlıyor.

---

## 9. Robustness Suite (SOP-3 zorunlu)

- Walk-forward 3y/6m, step 3m, 12 dilim
- IS/OOS Sharpe Δ < %30
- Random param perturbation ±%10, 50 seed → mean Sharpe loss < %25
- Symbol-out leave-one-out CV
- Regime split: bull / bear / range → ≥ 2'sinde pozitif Sharpe
- Stress dilimleri: 2022-05 LUNA, 2022-11 FTX, 2023-03 USDC depeg, 2024-03 BTC-ATH, 2024-08 Yen-carry
- Shuffle baseline p < 0.01
- Bonferroni FDR (n=486)

---

## 10. Reproducibility Stamp (backtest run anında)

```
git_hash:    <head sha @ engine.run>
config_hash: <sha256 of FROZEN param grid yaml>
data_hash:   <duckdb ohlcv_1d manifest snapshot>
universe:    historical (build_universe(date), delisted dahil)
fees:        7.5 bps taker / -1 bps maker
slip:        5 bps konservatif (executions worst-side)
initial:     10,000 USDT
risk:        sabit-fraksiyonel %1 / trade
```

---

## 11. Beklenen sonuç dağılımı (kalibrasyon)

- ~%60 RED — klasik pattern fee+slip altında zayıflar, özellikle kripto'da S/R "level" gürültülü
- ~%25 iterate-then-RED veya iterate-then-marginal
- ~%15 promote-aday (Lab tournament'a sevk)

Bu dağılım researcher persona KPI'ı "%20-40 terfi oranı" altında ama pre-registered iyi bir hipotez için gerçekçi. **Yüksek RED ihtimali itiraf etmek, hipotezi terk etmek için bahane değildir; honest prior'dur.**

---

## 12. Açık curve-fit endişeleri (kendime not)

- Grid 486 nokta — Bonferroni sıkı ama trial sayısı yine de bir saldırı yüzeyi. Eğer "best config'in en yakın 5 komşusu" Sharpe içinde değil, lokal pik → REJECT.
- `trend_filter ∈ {EMA50, EMA200, NONE}` — NONE olması bekleniyor (with-trend Grimes/Brooks fundamentali), ama eğer best NONE çıkarsa hipotez yapısal yanlış demek, REJECT.
- 2022-2025 dönemi BTC-domine ralli + ayı bandı içeriyor; D1 trend filter rejim-leak yapabilir. Walk-forward + symbol-out bunu yakalamalı.

---

**STATUS:** DRAFT — pre-registration commit'i için Principal onayı bekleniyor. Onay sonrası `config_hash` dondurulur, `backtest/engine.py` config'i türetilir, robustness suite zincire girer.

**Reviewer'lar (requested_review_from):**
- `lab_scientist` — promotion gate uyumu, tournament uygunluğu
- `risk_officer` — MaxDD equity-base hesap doğrulaması (CT-RSK-01), sizing %1 onay
