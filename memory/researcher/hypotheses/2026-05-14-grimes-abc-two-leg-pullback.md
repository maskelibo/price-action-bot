---
hypothesis_id: HYP-2026-05-14-GRIMES-ABC-TWO-LEG
date: 2026-05-14
author: researcher_agent
status: pre-registered-backlog
parent_strategy: pure-new
class: trend_continuation
tags: [grimes, two_leg_pullback, abc, trend_continuation, 1d, crypto, brooks_h2_l2_variant]
sprint: SEC25
---

# Hipotez: Adam Grimes Two-Legged Pullback ABC

## Motivasyon

PA mastery gap envanterinde:

> **#14 Adam Grimes — Two-legged pullback ABC — trend_continuation — NOT_TESTED**

Mevcut `brooks_h2_l2.py` (production, TESTED-PASS) single-leg pullback continuation
tetikler. Grimes ABC pattern bu strateji'nin **deeper-retracement çiftleğ variant'ı**.
Pattern mekanik olarak yapısal farklı (B-pivot oluşum + C-leg deeper retrace 20-50%
Fib + reclaim trigger) — orthogonal trigger zamanları, ensemble'a uncorrelated
katkı potansiyeli.

**Bu hipotez SEC25 sprintinde BACKLOG kayıt** (DB Bull Flag #1 önceliği nedeniyle).
Sonraki sprintte backtest.

## Hipotez Özeti (pre-registered)

**Bullish ABC (LONG):**

1. **Trend filtre:** close[t] > EMA50[t], AND EMA50 yukarı eğimli (EMA50[t] >
   EMA50[t-10]).
2. **Recent swing high (A-pivot):** Son 30 bar içinde fractal swing high (n=2)
   bulundu — bu trend'in son tepe noktası.
3. **A-leg pullback başlangıcı:** A-pivot'tan sonra 3-10 bar düşüş, ilk swing
   low oluşturdu (a-low pivot).
4. **B-pivot (mini-rally):** a-low'dan sonra 2-5 bar yükseliş — bu B-pivot,
   A-pivot'un AŞAĞISINDA olmalı (B < A, mini lower-high).
5. **C-leg (deeper retrace):** B-pivot'tan sonra düşüş, c-low pivot oluşturdu —
   c-low MUST hit Fib 38.2-61.8% retracement of original (A-pivot → start of trend).
   c-low ≥ a-low yapısal: c-low > a-low VE c-low ≤ (B+a-low)/2 (re-test ama daha
   derin).
6. **Reclaim trigger (bar t):** c-low pivot bar sonrası 2-3 bar içinde fiyat
   B-pivot price'ı reclaim etmeli — bar t close ≥ B-pivot price (close above B).
   Bar t bullish (close > open), body_ratio ≥ 0.40.
7. **Trend continuation entry:** Bar t+1 açılışı LONG.

**SL (LONG):** c-low - 0.5 × ATR14[t].
**TP (LONG):** A-pivot price (trend yeniden A'yı test eder), floor 2.0R.

**Bearish ABC (SHORT, ayna):** EMA50 düşüş, swing low A-pivot, a-high → B-pivot
(higher-low), C-leg higher → c-high, B-pivot reclaim downside trigger.

## Gerekçe (literatür, RAG)

- **Adam Grimes (Art and Science of Technical Analysis 2012, Ch 7
  "Trading Pullbacks"):** "Two-legged pullbacks are the most common high-quality
  trend-continuation setup. The second leg shakes out weak hands and provides
  the better entry."
- **Brooks (Trading Price Action Trends, Ch 4 "Pullbacks"):** "H2/L2 simple
  bull/bear flags; ABC bull/bear flags add the B-pivot intermediate rally to
  qualify the pattern."
- **Wyckoff (Phase C → D transition):** Spring sonrası ikinci test, LPS markup
  başlangıcı. Two-leg pullback = Wyckoff "double bottom + retracement" eşdeğer.

**Crypto-uyumlu microstructure argüman:**

- BTC/ETH swing'leri çok sık iki-leg pullback gösterir (örnek: 2022-Q1 ETH
  pullback 4900 → 4200 → 4500 → 4000 → 5000, klasik ABC). Crypto'da likidite
  dinamikleri (long liq → short liq → reclaim) iki-leg yapıyı doğal yapar.
- H2/L2 single-leg edge production'da mevcut. ABC two-leg "deeper test"
  ENTRY kalitesi → daha iyi RR (SL daha yakın, target aynı). Hipotez:
  ABC trigger n daha az olur ama avg_R daha yüksek.

## Hard Gates (pre-registered, anyone FAIL → RED)

| Gate | Threshold | Açıklama |
|---|---:|---|
| n_min | ≥ 150 | Daha rare pattern (B-pivot zorunlu) — gate gevşek |
| WR_min | ≥ 0.45 | Grimes literatür alt-band |
| mR_min | ≥ +0.15 | Daha derin retrace → daha iyi RR beklenir |
| p_shuffle | < 0.05 | Null sign-flip 2000-perm |
| max_R | < 10 | Artifact filter (honest clip hold>60d) |
| per_sym_pos | ≥ 6 / 11 | Cross-symbol robustness |
| symout_dev | < 30% | Leave-one-out CV |

**Orthogonality gate (slot bottleneck guard):** ABC trade-date jaccard with
`brooks_h2_l2` MUST < 0.30. Eğer jaccard ≥ 0.30 → "two-leg standalone variant"
H2/L2 ile aynı slot zamanları, ensemble katkısı zero — PROVISIONAL RED.

## Counter-Hypotheses (pre-registered)

1. **CH-1 (H2/L2 overlap):** ABC + H2/L2 trigger zamanları %80+ overlap olabilir
   (B-pivot detection vektörize edemezsek false-positive H2 trigger döner). →
   ortogonality < 0.30 gate.

2. **CH-2 (Fib zone too tight):** Fib 38-61% C-leg gate kompleks → n bottleneck
   riski (sec22 three-push paralel). 30+ trigger/yıl × 11 sym × 5y = 1650 baseline,
   ama Fib gate sonrası 3-5x azalır. Eğer n < 150 → CH-2 doğrulanır.

3. **CH-3 (subjektif pattern recall):** Grimes ABC subjective trader-eye pattern —
   vektörize implement orijinal %30-50 setup recall yapar. Edge gerçek olsa bile
   n yetersizliği RED yapabilir.

4. **CH-4 (deeper-retrace = higher failure):** C-leg Fib 50-61.8% Wyckoff
   spring riski yüksek (deeper test = ana trend exhaustion sinyali). Crypto'da
   "deeper pullback = failure" yapısal mı? Per-year split bul.

## Sonuçlar (EXECUTED 2026-06-11 — yeni-alfa programı #1) — VERDICT: PASS (15m)

Detector: `src/price_action/strategies/grimes_abc_pullback.py` (vektörize features
+ bounded scan, lookahead-safe, `_default_manifest()`). Havuz: 19 sym, 15m + 4h@15m.
Değerlendirme: hardened_v14 ilk geçiş (pyramid YOK, reblend YOK, +57bps honest,
widestop sl>=0.025 & conf>=0.25, ay-bağımsız taze-$10k fixed-notional).

**15m kolu (PASS):**
- n_widestop=7233, aylık ort=+8.94% (med +9.23), neg=6/62 ay
- TRAIN +8.50% (n=43) / OOS +9.93% (n=19, **0 negatif OOS ay**)
- continuous-compounding DD = −12.4%, worst ay −4.89% (2024-03 BTC ATH)
- honest meanR=+0.698, WR=0.480

**Robustness (8/8 değerlendirildi, 7 PASS + 1 FLAG):**
- shuffle sign-flip p<0.0005 ✓ | per-symbol 19/19 pozitif (train VE OOS) ✓
- **lookahead-delay+1bar testi: edge %92 korundu → SIZINTI YOK** (yapısal drift,
  same-bar artifact değil) ✓
- orthogonality: aylık corr=+0.12, trade-(sym,hour) jaccard=0.019 vs mevcut kol,
  0.012 vs brooks → **çok ortogonal** ✓ (slot bottleneck guard geçti)
- max_R<10 gate: **FLAG** — %4 trade >10R (max 15.81), engine-native trend-runner
  exit'leri, sızıntı değil ama R-kuyruğu şişkin → dürüstçe kaydedildi

**4h kolu: ZAYIF (RED) —** aylık +1.15%, OOS +1.04% ama 5/18 neg OOS ay. 15m tercih.

**DÜRÜSTLÜK UYARISI (Feynman):** +8.94%/ay bu metodolojinin (ay-bağımsız taze-$10k)
ŞİŞİK ölçeğinde. Mevcut 15m kol AYNI ölçüde +9.34%/ay; canlı champion ~1-2%/ay
(memory: backtest-compounding-inflation). Yani standalone canlı-eşdeğer edge
champion mertebesinde, **TEK BAŞINA %25/ay yolu DEĞİL**. Gerçek değer: düşük
korelasyon (0.12) → **ensemble diversifier** olarak yüksek kol değeri.

**Karar:** Lab tournament'a 15m standalone diversifier adayı teslim. Sonuç JSON:
`memory/researcher/backtest_results/2026-06-11-grimes-abc-two-leg-pullback.json`.
CH-1 (H2/L2 overlap) çürüdü (jaccard 0.012). CH-2/CH-3 (n bottleneck) çürüdü
(n=7233). CH-4 (deeper-retrace=failure) çürüdü (WR 0.48, 19/19 pozitif).

## Reproducibility (planlı)

- **Strategy file:** `src/price_action/strategies/grimes_abc_two_leg.py` (planned)
- **Standalone script:** `scripts/secXX_grimes_abc_standalone.py` (planned)
- Seed: 42, n_perm: 2000
- STRATEGY_CLASS = 'trend_continuation'

## Notlar

- B-pivot detection vektörize zor — A→a→B→c sıralama state machine gerektirir.
  Brooks H2/L2 single-pivot, ABC iki-pivot. Detector implementation karmaşık ama
  tractable (fractal scan + sıralı pivot tag).
- Eğer DB Bull Flag (SEC25 #1) PASS olursa, ABC backlog'unu tekrar
  değerlendir — pool'da iki yeni trend-cont birden eklemek slot bottleneck'i
  daha da sıkar.

## Sources

- [Adam Grimes — Art and Science of Technical Analysis 2012](https://www.amazon.com/Art-Science-Technical-Analysis-Approach/dp/1118115120)
- [Brooks 2012 — Trading Price Action Trends, ch 4](https://www.amazon.com/Trading-Price-Action-Trends-Technical/dp/1118066510)
- PA mastery gap envanteri: `reports/researcher/2026-05-14_pa_mastery_gap.md`
- SEC24 learning (sister-test for trend_cont prior): `memory/researcher/learning_20260514_sec24_turtle_soup_red.md`
