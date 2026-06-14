---
doc_id: researcher-20260601T020000-fabio-orderflow-mechanical-skeleton-forex
doc_type: hypothesis
agent_id: researcher
created_at: 2026-06-01T02:00:00Z
status: pre-registered
confidence: low
depends_on: []
blocks: []
requested_review_from:
  - lab_scientist
  - signal_chief
tags:
  - forex
  - order_flow_proxy
  - session_filter
  - support_resistance_rejection
  - infeasibility_disclosure
  - paper_only_spk_blocked
  - mechanical_skeleton
supersedes: null
---

# HYP-2026-06-01 — Fabio order-flow scalper: MEKANİK İSKELET (order-flow YOK) forex'te edge taşıyor mu?

## 0. Feasibility disclaimer (önce bu yazılır — Feynman: kendini kandırma)

Video'nun ASIL edge'i **order flow**: delta, absorption, footprint, volume profile (VAH/VAL/POC).
Bunlar **bizim verimizden ÜRETİLEMEZ**:

1. **Forex decentralized → konsolide gerçek hacim YOK.** DuckDB `ohlcv.volume` kolonu **6 yılın TAMAMINDA 0.0** (438k×15m + 109k×1h + 77k×4h + 219k×30m barın hepsi sıfır hacim — `SELECT sum(volume)` = 0). Tick-volume bile yok. Footprint/delta/absorption/CVD bu satırdan TÜRETİLEMEZ. Nokta.
2. **Volume profile (VAH/VAL/POC) gerçek hacme dayanır** → yok. Proxy olarak **önceki-gün H/L + round-number** psikolojik seviyeler kullanılacak (bu order-flow DEĞİL, sadece yatay-seviye proxy).

**Bu yüzden test edilen şey Fabio'nun edge'i DEĞİL — onun edge'inin ISKELETI:**
seans-filtreli + yatay-seviye reddi + sıkı stop (seviye ötesi) + R:R hedef + breakeven/trailing.
Order-flow onayı (edge'in beyni) OLMADAN. Soru net: **iskelet TEK BAŞINA edge taşıyor mu, yoksa edge tamamen order-flow'da mıydı?**

Beklenti (Tetlock kalibrasyon): **P(iskelet shuffle'ı net-of-cost geçer) ≈ %20.** Order-flow'suz bir S/R-reddi scalp'inin spread+komisyonu net pozitif aşması forex intraday'de tarihsel olarak nadir. Bu hipotezin %80 ölme beklentisi yüksek.

## 1. İddia (pre-registered, ölçülebilir)

"2020-01→2026-01, EUR/USD + GBP/USD + USD/JPY (intraday verisi olan 3 major), 15m TF'de,
**aktif seans içinde** (London 07:00–11:00 UTC veya NY 13:00–17:00 UTC),
**önceki-gün H/L veya round-number seviyesinin 0.25×ATR(14) yakınında** oluşan
**rejection bar** (seviyeye dokunup ters kapanış: bullish için low≤level≤? & close geri döner; gövde/fitil kuralı aşağıda),
sinyali; girişte seviyenin **0.3×ATR ötesine sıkı stop**, hedef **bir sonraki yatay seviye veya 1.5R** (hangisi yakınsa),
1R'de breakeven, sonra 1.0×ATR trailing — **gerçekçi forex maliyeti sonrası (spread+komisyon) net pozitif beklenen-R taşır.**"

### Pre-registered kabul kapıları
- mean_R_after_cost > 0 (sıfırdan anlamlı, t-test p<0.05)
- **Shuffle baseline'ı geçer:** gerçek mean_R, 1000 shuffle'ın %95 persantilinin üstünde (p<0.05).
- net win% ölçülür (bilgi amaçlı, gate değil).
- en az 2 seans/parite kombinasyonunda pozitif (regime-robustness proxy).
- walk-forward: yıllık OOS dilimlerinin ≥%50'sinde mean_R_after_cost > 0.
- n_trades ≥ 200 (parite başına ≥ 50; istatistik gücü).

### Null hipotez (Popper — önce çürüteni yaz)
**H0:** Mekanik iskelet, order-flow onayı olmadan, net-of-cost mean_R = 0 (edge yok); gözlenen herhangi bir pozitiflik shuffle-rastlantısıyla ayırt edilemez.
**H0 doğruysa şunlar OLMAMALI ama beklerim:** shuffle p>0.05, mean_R_after_cost ≤ 0, walk-forward dilimlerinin yarısından çoğu negatif.
**Bunlardan biri bile gerçekleşirse iskelet TEK BAŞINA edge taşımıyor → REJECT, "order-flow olmadan kopyalanamaz" notu.**

## 2. Bağımsız değişkenler (sabit tutulur, NO tuning — overfit kalkanı)
- TF: 15m (intraday scalp; video order-flow scalp).
- S/R proxy: önceki-gün (UTC takvim günü) H/L + round-number (EUR/USD,GBP/USD: 0.0050 grid; USD/JPY: 0.50 grid).
- proximity: 0.25×ATR(14).
- stop: seviye ± 0.3×ATR.
- TP: min(sonraki seviye, 1.5R), 1R BE + 1.0×ATR trail.
- rejection bar: gövde ≤ %50 range, ters-yön fitil ≥ %40 range, kapanış seviyenin doğru tarafında.
**Bu parametreler video kurallarından ve mevcut crypto base'lerden TÜRETİLDİ — grid-search YOK.** Tek bir konfig koşulur. Sweep yapılırsa Holm/BH düzeltmesi raporlanır.

## 3. Bağımlı değişkenler
mean_R_after_cost, net win%, MaxDD (R cinsi equity), monthly ROI (sabit-risk %1), n_trades, Sharpe (takvim-günü, ŞİŞİRME YOK), shuffle-p.

## 4. Maliyet modeli (KONSERVATİF tarafta)
- spread: EUR/USD 0.8 pip, GBP/USD 1.3 pip, USD/JPY 1.0 pip (round-trip giriş+çıkış'ta yarısı her bacakta, toplam 1× spread/trade).
- komisyon: 0.5 pip-eşdeğeri/trade (ECN ~$7/lot ≈ 0.7 pip; konservatif 0.5).
- toplam maliyet ≈ spread + 0.5 pip her trade'de R'den düşülür. Slippage stop'ta +0.2 pip.
- pip değeri: EUR/USD,GBP/USD pip=0.0001; USD/JPY pip=0.01.

## 5. Lookahead garantileri (paranoyak)
- Tüm feature'lar (ATR, önceki-gün H/L, seviyeler, rejection geometri) **t-1 close** itibariyle bilinir.
- Sinyal t-1 kapanışında üretilir; giriş **t bar OPEN**'ında.
- `shift(-1)` / `center=True` / future-rolling YOK. Önceki-gün H/L = strictly < bugünün ilk barı.
- Çıkış: stop/TP bar-içi konservatif sıra (önce stop, sonra TP — aynı barda ikisi de tetiklenirse stop sayılır).

## 6. Stop criteria
mean_R_after_cost ≤ 0 VEYA shuffle p>0.05 → terkedilir, "iskelet edge taşımıyor" arşivi.

## 7. Reproducibility
- git_hash: audit-hardreview-20260528 HEAD
- data: data/forex_market.duckdb ohlcv (volume=0 doğrulandı)
- detector + backtest: scripts/research/fabio_orderflow_skeleton_forex.py (bu doc sonrası kodlanır)
- seed: 42 (shuffle).

## 8. Bias check
Persona "%80 reject normal". Bu hipoteze prior düşük (%20 geçer). Feasibility disclaimer en başta — order-flow kopyalanamaz, bu sadece iskelet testi. SPK-bloklu → paper/research only, deploy YOK.
