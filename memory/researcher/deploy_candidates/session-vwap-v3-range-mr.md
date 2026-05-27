---
doc_id: deploy-candidate-session-vwap-v3-range-mr
doc_type: deploy_candidate
agent_id: researcher
created_at: 2026-05-27T13:55:00Z
status: READY_FOR_DEPLOY
confidence: high
priority: P2
candidate_origin:
  base_strategy: session_vwap_mean_reversion
  iterate_rounds: 1
  variants_tested: 8
  champion_variant: v3_concurrent4_pause3
discovery_context: |
  User talebi 'düşük vol bot' arayışında. Low-vol filter edge'i öldürdü
  (BTC ATR<%2 günleri sadece %3); ancak session_vwap MR aslında TÜM
  günlerde çalışıyor → intraday range mean reversion. v3 ELITE.
review_pending:
  - principal_approval
  - risk_officer_endorse
  - korelasyon test (live + v63 + v3 üçlü)
tags:
  - deploy_candidate
  - session_vwap_mean_reversion
  - elite
  - companion_strategy
  - range_mean_rev
---

# ⭐ session_vwap_v3 — Intraday Range Mean Reversion (DEPLOY CANDIDATE P2)

## Performans (5y backtest)

| Metrik | v3 (ELITE) | v4 (SAFE) | Live |
|---|---|---|---|
| Aylık ROI | **+%15.28** | +%5.77 | +%12.99 |
| Max DD | -%21.87 | **-%9.36** | -%15.48 |
| Yıllık | +%414 | +%95 | +%329 |
| Neg ay | 7/61 | 7/61 | 4/61 |
| Trade sayısı (5y) | 12,758 | 12,758 | 4,458 |
| Risk-adj ratio | 0.699 | 0.617 | 0.839 |

**v3 versus Live:**
- Aylık ROI **+%2.3 puan fazla**
- DD %6.4 puan fazla (kabul edilebilir)
- Yıllık **1.26x daha hızlı compound**
- Neg ay live'a çok yakın (7 vs 4)

**v4 versus Live (half-Kelly):**
- DD **%6 puan DAHA AZ** (pareto-dominant risk tarafında)
- Aylık ROI yarıda (5.77 vs 12.99)
- Companion strategy olarak ideal — risk artırmıyor, getiri ekliyor

## Spec

```yaml
strategy: session_vwap_mean_reversion
timeframe: 15m

# v3 ELITE
v3:
  risk_pct: 0.005
  max_concurrent: 4
  consecutive_loss_pause: 3
  tp_r: 1.5

# v4 SAFE (half-Kelly)
v4:
  risk_pct: 0.002
  max_concurrent: 4
  consecutive_loss_pause: 3
  daily_dd_halt: 0.02
  tp_r: 1.5

# YOK: vol regime filter (edge'i öldürür)
# YOK: sl_pct_min (session_vwap dar SL stratejisi)
```

## Strateji Mantığı

**Session VWAP Mean Reversion:**
- Her gün (UTC) VWAP hesaplanır (volume-weighted avg price)
- Fiyat VWAP'tan X% (örn %1) sapınca → geri dönüş bekle
- Engulfing veya doji bar confirmation → entry
- Target: VWAP'a dönüş veya 1.5R
- Hold time: ~1-6 saat

**Hangi koşulda?**
- ✅ Intraday range/normal piyasa (en çok)
- ✅ Düşük-orta volatilite
- ❌ Trending market (fiyat VWAP'a dönmüyor)
- ❌ Aşırı yüksek vol (VWAP kullanışsız)

## 3-Bot Combo Portföyü

| Bot | Strateji | Aktif Olduğu | Risk Pool |
|---|---|---|---|
| 🟢 Live (vsa) | Trend climax | Yüksek vol + trend | %50 |
| 👑 v63 (rsi2) | RSI extreme | Yüksek vol + range | %30 |
| ⭐ v3 (vwap) | VWAP MR | Intraday range | %20 |

Toplam Sharpe = Σ(weighted Sharpe) + (1 - ρ ortalama) × diversification bonus.
ρ < 0.3 ise combo Sharpe **tek bot'tan FAZLA**.

## Risk Uyarıları

1. **High-vol crash dönemlerinde tetiklenir** — büyük sapma → "geri dönüş" beklerken trend devam → loss. Loss_pause yardımcı ama tam koruma değil.
2. **Likidite çok önemli** — 12,758 trade × ortalama $5-50 = yüksek slippage riski.
3. **Session değişimleri** — Asia/EU/US session değişimlerinde VWAP reset bug riski. Test edilmeli.
4. **Trade frekansı yüksek** — 5y'da 12K trade = günde ~7 trade = fee birikimi.

## Deploy Adımları

### Aşama 1: Combo Sharpe Testi [PENDING]
- live + v63 + v3 üçlü korelasyon hesap
- Combo Sharpe simülasyon
- ρ matrix < 0.3 ise → 3-bot deploy

### Aşama 2: Paper Test (1-2 hafta) [PENDING]
- v3 spec ile paper trade
- Real fee/slippage gözle (yüksek trade frekansı → fee birikimi)

### Aşama 3: Production [PENDING]
- Principal approval (ADR-002)
- futures15m_session_vwap_v3 daemon
- Ayrı journal: data/futures_journal_15m_vwap.duckdb

## Referans

- 8 varyant comparison: `memory/researcher/realistic_backtest_results/session_vwap_iterate.json`
- Iterate script: `scripts/iterate_session_vwap.py`
- Düşük-vol survey: `scripts/low_vol_strategy_test.py`
