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

## Sonuçlar (boş — backlog)

- [ ] Backtest planlanmış sprint: TBD (SEC25 sonrası)
- [ ] Standalone metrics
- [ ] Orthogonality (H2/L2)
- [ ] Per-symbol / per-year breakdown

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
