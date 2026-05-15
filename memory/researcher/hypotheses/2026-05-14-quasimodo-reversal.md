---
name: hyp-2026-05-14-quasimodo-reversal
description: Quasimodo (QM) 5-pivot reversal — HEAD swing'i yeni HH yapar (stop run), sonra LL ve LH (HEAD altında close) ile reversal sinyali. Mirror short.
metadata: { type: hypothesis, status: pre-registered, author: researcher, date: 2026-05-14, sprint: sec19 }
---

# HYP-2026-05-14-QUASIMODO-REVERSAL

## Kaynak (RAG / literatür)

- LiteFinance: "Quasimodo Pattern (QM)" — Over-and-Under pattern; series HH-HL-HH-LL-LH (bearish); reversal after structural stop-run on HEAD. https://www.litefinance.org/blog/for-professionals/100-most-efficient-forex-chart-patterns/quasimodo-forex/ (accessed 2026-05-14)
- Aron Groups: "QM in Price Action" — pattern forms when sequence of HH/HL or LL/LH is "interrupted" by a single counter-pivot, creating left-shoulder/head/right-shoulder analogue without horizontal neckline. https://arongroups.co/technical-analyze/quasimodo-pattern/
- HoneyPips, XS Capital, FXOpen — converge on same 5-pivot definition (LL-LH-HH-LL-LH bearish QM).
- Brooks "Trading Price Action Reversals" Ch.4: QM is mathematically a "double-top variation with deeper internal structure" — Brooks doesn't name it QM but acknowledges the topology.

## Hipotez (pre-registered)

**Iddia:** 1D crypto'da, QM bearish formation tetiklenir → 3 günden 30 güne **R-multiple beklenen değer > +0.20** ile SHORT edge sağlar (mirror LONG icin bullish QM). Bu, mevcut `liquidity_sweep_reversal` tek-swing sinyalinden **structural olarak daha derin** (5-pivot zincir) ve `equal_highs_sweep`'ten **mantıksal olarak farklı** (eşit-yüksek değil, YENİ-yüksek + reversal).

**Null hipotez:** QM bearish/bullish setup'ı RANDOM entry'den **anlamlı edge SAĞLAMAZ** (mR ≤ +0.10 VEYA WR ≤ 35% VEYA Sharpe ≤ 0.5 standalone'da; ya da ensemble retest'te delta < 0).

## Mekanik kurallar (vektörize)

**Pivot tespiti:** `fractal_n=2` (her iki yana 2 bar daha düşük/yüksek ise pivot)

**Bearish QM (SHORT signal):**
- Aramayı bar `t`'de yap. Geriye doğru en son 4 pivotu bul: p4, p3, p2, p1 (p1 en yakın geçmişe).
- Sıralama (zaman geçmişten yakına): p4=LL_old, p3=LH_old, p2=HH_new (HEAD = stop run), p1=LL_recent (sonraki dip)
- Koşullar:
  1. p3.high > p4.high → uptrend mevcut (LL → LH)
  2. p2.high > p3.high → HEAD yeni HH yaptı (stop-run / liquidity grab)
  3. p1.low < p3.low → HEAD sonrası geri çekiliş p3 (önceki LH) seviyesinin ALTINA indi — yapısal kırılım
  4. Bar `t` close < p2.high AND close < p3.high → RIGHT SHOULDER zona indi (LH retest)
  5. Bar `t` veya t-1 ya bearish engulf veya bearish pin (basit confirmation gate)
  6. Cooldown: bar t'de tetiklenirse sonraki 10 bar tekrar tetiklenemez
- Entry: bar t+1 open
- SL: p2.high (HEAD üstü) + 0.25 × ATR(14)
- TP1: p1.low (yapısal LL seviyesi) → 0.5R partial close
- TP2: 2.0R (R-based)
- Runner: standart engine trail (mult=1.5)

**Bullish QM (LONG signal):** Mirror image.
- p4=HH_old, p3=HL_old, p2=LL_new (HEAD low stop-run), p1=HH_recent
- Koşullar: p3.low < p4.low AND p2.low < p3.low AND p1.high > p3.high AND close[t] > p2.low AND close[t] > p3.low

**Filtreler (mandatory):**
- ATR(14) / close > 0.5% (regime gate — quiet'te yapısal kalitesiz)
- Pivot zaman aralığı: p4 ile t arası ≥ 10 bar VE ≤ 80 bar (çok eski → S/R hafızası ölü; çok yeni → mikro noise)
- Lookahead-free: tüm pivot tespiti bar `t-3`'e kadar bilinen pivotlarla yapılır (pivot confirm için n=2 bar bekleniyor)

## Beklenen edge

- Standalone mR: +0.20 ile +0.40 arası (kaynaksız PA-community iddiası WR ~60% — 1.5R hedef → mR = 0.6×1.5 - 0.4×1.0 = +0.50; ama biz konservatif tahmin +0.20)
- n_trade tahmini: 5y × 11 sym × ~6 QM/yıl/sym ≈ 300-400 trade. Filtre sonrası 150-250.
- WR > 35% gate kolay aşılır (1.5R primary TP partial); main edge LL'ye kadar ortalama 0.6R.
- Ensemble katkı: orta. QM swing pivotları TOP_10 trend-cont günleriyle bazen örtüşür ama HEAD-confirmation 5-pivot zincir SEYREK günlerde tetikler.

## Fail kriterleri (HARD / SOFT gate eşikleri)

**HARD (anyone → RED):**
1. n_trade < 50 (yetersiz örneklem)
2. WR ≤ 0.35
3. mR ≤ +0.10 (standalone edge)
4. shuffle baseline'a karşı p ≥ 0.10 (50 shuffle, real annualized < shuffle 90th percentile)
5. WF (3y rolling, 13 pencere) — negatif pencere sayısı > 4

**SOFT (≥2 fail → RED-conditional):**
1. IS/OOS Sharpe drop > %50
2. Symbol-out CV: 1 sembol drop ile mean annualized değişimi > %50
3. Ensemble retest: ROI delta < 0 AND DD delta > 0 (her ikisi kötü)
4. Look-ahead audit: pivot tespitinde t+1 ya da t+2 bilgi sızıntısı

## Test planı

1. Strategy implementation: `src/price_action/strategies/quasimodo_reversal.py`
2. Standalone gather: 5y × 11 sym × 1d → trade pool
3. Edge gate (mR>0.10, n>50, WR>0.35)
4. WF 3y rolling 13 pencere (TOP_10 + FVG ensemble vs +QM)
5. Robustness suite: param perturb (pivot lookback ±30%, ATR mult ±25%), symbol-out CV (11 sym), regime split (bull/bear/range), shuffle (50)
6. Multiple testing: Bonferroni (3 candidate sprint) — alpha 0.05/3 = 0.017 per test

## Beklenen sonuç olasılığı

- Standalone PASS: ~%55 (PA community claim güçlü ama crypto-spesifik test yok)
- Ensemble PASS (delta yıllık > +%2pp veya r-adj > +0.05): ~%35 (slot bottleneck risk)
- Final aday production: ~%25
