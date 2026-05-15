---
name: hyp-2026-05-14-cme-gap-fade-btc-eth
description: BTC/ETH spot weekend "gap" fade on Monday — fade large Sun/Mon open vs Friday close, expecting partial mean-reversion within 1-3 days.
metadata: { type: hypothesis, status: pre-registered, author: lab-scientist, date: 2026-05-14 }
---

# HYP-2026-05-14-cme-gap-fade-btc-eth: CME-Style Weekend Gap Fade (BTC/ETH spot proxy)

## Kaynak
- Phemex Academy: "CME Gap Crypto Explained" — historical fill rate ~77% within 1 week. https://phemex.com/academy/cme-futures-gap (accessed 2026-05-14)
- Whaleportal: "How to Trade Bitcoin CME Gaps" — gap defined as Friday close vs Sunday/Monday open differential. https://whaleportal.com/blog/bitcoin-cme-gaps-and-cme-trading-strategy-explained/ (accessed 2026-05-14)
- Pattern: CME BTC futures close Fri 17:00 ET → Sun 18:00 ET. Spot keeps trading; gap forms.

## Hipotez
Beklenen edge: weekend, kurumsal likidite yokken spot fiyatı haftasonu drift eder (low-volume regime). Monday US open'da kurumsal akış geri döndüğünde fiyat Friday-close-anchor'a doğru ortalamaya döner. Edge market microstructure: futures-spot basis tamamlanma + liquidation cascade likelihood (Sunday'de stop hunt sonrası Monday'de yapısal mean-revert).

Crypto 1d için spot proxy: Monday açılışında (UTC 00:00 Mon) "weekend_return" hesapla = (Mon_open - Fri_close) / Fri_close. |weekend_return| > eşik (örn. %2) ise FADE et — pozisyon yönü = -sign(weekend_return).

## Mekanik kurallar (entry/exit/filter)
- TF: 1d (daily UTC)
- Entry day-of-week: yalnızca **Monday** bar (gün-içi yeni 1d bar açıldığında karar)
- Gap definition (1d crypto, spot proxy):
  - friday_close = close[t-3] (Pazartesi t bar'ı için Cuma kapanışı 3 bar önce; Cmt+Pzr ara)
  - mon_open = open[t]
  - gap_pct = (mon_open - friday_close) / friday_close
- Long signal: gap_pct < -GAP_THRESHOLD (örn. -%2.5) → fade short-side weekend = LONG
- Short signal: gap_pct > +GAP_THRESHOLD → fade long-side weekend = SHORT
- Filter (mandatory, anti-trend-trap):
  - 1W EMA(8) eğimi gap yönünün TERSI (Monday open EMA8 üstündeyse short setup geçerli; aksi long); eğer gap aynı yönde HTF trend ile ise SKIP (gerçek breakout olabilir)
  - ATR(14, 1d) > 0.5% — quiet regime'de gap-fade zayıf
  - Lookahead-safe: gap, indicator, all features t-1 close ile hesaplanır, entry Mon open'da
- Stop loss: gap'in ÇIFTINE (entry'den (gap_pct) × 1.0 ATR daha karşı yönde; tipik SL = entry ± 1.5 × ATR14)
- Take profit / exit:
  - TP1: Friday close seviyesi (gap-fill) — %50 close at TP1
  - Time exit: 3 bar (3 gün) içinde gap-fill yoksa flat çıkış (force exit)
  - Trail: yok, time-based

## Test planı
- Asset: BTC, ETH (ana likit, CME futures var). Plus: SOL, AVAX (en likit alt-coin, weekend gap behavior'ı genişletmek için).
- TF: 1d UTC
- Window: 5y (2021-01 → 2026-05)
- Baseline karşılaştırma: v2.0.3 BALANCED+F&G+pyramid (yıllık +%239.5, DD -%38.6, r-adj 6.189)
- Backtest:
  1. Standalone signal frequency: kaç Monday'de gap > %2.5? Beklenen: BTC ~%15-25 Monday'ler.
  2. Standalone mR: n ≥ 80 (5y × 52 Mon × 4 sym × 0.20 trigger ≈ 200)
  3. Ensemble integration: signal_chief'a yeni strateji olarak ekle, max_concurrent=12 slot rekabeti
  4. Walk-forward 3y rolling, 13 pencere

## Pass kriterleri
- Standalone: n_trade ≥ 80, mR ≥ +0.10, WR ≥ %45, sumR > +10 (5y'de)
- Ensemble katkısı: yıllık +%2pp uplift VE DD ≤ baseline +%3pp absolute
- 13 pencerenin en az 9'unda pozitif yıllık katkı
- Effect size vs random shuffle baseline: p < 0.05

## Karşı-hipotez (RED kriteri)
- |gap_pct| büyük olduğunda zaten momentum break (gerçek news catalyst) ve fade kaybeder → mR < 0 veya WR < %42.
- Bull market'te (BTC quadrant 2-3) gap-up'lar dolmuyor, fade short kaybediyor; rejim conditioning şart.
- Gap-fill 77% statistic CME futures (lower liquidity), spot 24/7 piyasada bu rate düşebilir → mR borderline.
- Eğer pass-rate < 9/13 ise RED-CONDITIONAL (yalnızca low-vol regime'de).

## Implementation notu
- src/price_action/strategies/cme_gap_fade.py — yeni dosya
- Signal class: CMEGapFadeStrategy(BaseStrategy)
- DAY_OF_WEEK = Monday (UTC 00:00 bar)
- Lookahead: gap_pct hesaplamada t-1 close (Friday) + t open (Monday) → entry açılışta ve close[t]'de execute (engine yapısı close-based entry, açılışı yaklaşıklamak gerekiyor — ya da open[t] kullan)

## Mevcut havuzla orthogonality beklentisi
- pin_bar / engulfing trend-cont ağırlıklı → gap-fade SAF mean-reversion ve gün-spesifik (Mon only) → korelasyon düşük beklenir (<0.3)
- naked_poc_mr ile çakışma olabilir (her ikisi de mean-reversion) — partial correlation eklenmeli, ensemble'da slot rekabeti
