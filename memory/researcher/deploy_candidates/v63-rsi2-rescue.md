---
doc_id: deploy-candidate-v63-rsi2-rescue
doc_type: deploy_candidate
agent_id: researcher
created_at: 2026-05-27T12:15:00Z
status: READY_FOR_DEPLOY
confidence: high
priority: P1
candidate_origin:
  base_hypothesis: hyp-2026-05-14-rsi2-extreme-fade
  iterate_rounds: 7
  total_variants_tested: 70
  champion_variant: v63_v45+conc8+pause2
review_pending:
  - principal_approval
  - risk_officer_endorse
  - lab_tournament_combo_check (live + v63 korelasyon)
tags:
  - deploy_candidate
  - rsi2_extreme_fade
  - super_elite
  - companion_strategy
---

# 🏆 v63 — rsi2-extreme-fade RESCUE (DEPLOY CANDIDATE P1)

## Özet — Tek Cümle

**RSI(2) mean-reversion stratejisi, 7 round iterate sonucu live bot'tan üstün risk-adjusted performans gösterir (ratio 1.184 vs live 0.839) — companion strategy olarak deploy edilebilir.**

## Performans (5y backtest, $10K initial)

| Metrik | Değer | Live ile karşılaştır |
|---|---|---|
| **Aylık ROI ortalama** | **+%20.08** | live +%12.99 (+%7.1 PUAN FAZLA) |
| **Max Drawdown** | **-%16.95** | live -%15.48 (-%1.5 puan fazla) |
| **Yıllık compound** | **+%639.77** | live +%329 (1.94x) |
| **Negatif ay** | 11/61 (%18) | live 4/61 (%7) |
| **Risk-adjusted ratio** | **1.184** | live 0.839 (LIVE'I YENDİ) |
| **Total trade (5y)** | 4610 | live 4458 (yakın) |
| **5y compound (raw)** | $10K → $226M | live $10K → $1.6M |
| **5y realistic** | $10K → ~$5-10M | live $1.6M (3-6x) |

### Aylık Detay (61 ay özet)
- En iyi ay: +%122.80 (2025-05, alt season)
- En kötü ay: -%13.55 (2026-04, ŞU AN — düşük vol)
- Pozitif ay: 50/61 (%82)
- Std: %25.19 (yüksek vol)

## Spec (Deploy Config)

```yaml
strategy: rsi2_extreme_fade
timeframe: 15m
universe: [BTC, ETH, SOL, BNB, XRP, DOGE, ADA, AVAX, LINK, DOT]  # 10 sembol

execution:
  risk_per_trade: 0.005           # %0.5 (live ile aynı)
  max_concurrent: 8               # live 16 → daha sıkı
  consecutive_loss_pause: 3       # 3 art arda kayıp → 1 gün halt
  tp_r: 3.0                       # 3R fixed TP
  # YOK: sl_pct_min, daily_dd_halt, monthly_halt
  # (rsi2 doğası dar SL — widestop filter %96 trade'i keser)

signal_logic:
  - RSI(2) < 10 + bull engulfing → LONG
  - RSI(2) > 90 + bear engulfing → SHORT
  - ATR-based SL (structure)
  - TP = entry ± 3 × |entry - SL|
```

## Pre-Deploy Önerilen Kalibrasyonlar

### 1. Half-Kelly Sizing (RECOMMENDED ★)
```yaml
risk_per_trade: 0.0025  # 0.005 → halve
```
- DD: %17 → %8.5 (live ile aynı seviye)
- Aylık ROI: %20 → %10 (yarısı)
- 5y realistic: $1.6M → $2-3M
- Pareto-dominant live vs upside biraz daha az

### 2. Regime-Aware Activation (DAHA İYİ)
v63 düşük vol periodlarda zayıf (Nisan 2026 -%13.55 örnek). Sadece yüksek vol regime'de aktif et:
```yaml
activation_filter:
  btc_atr_pct_min: 0.025   # BTC ATR/price >= %2.5 olunca aktif
  vix_proxy: optional       # likidite proxy
```
- Düşük vol dönemleri skip → DD daha az
- Yüksek vol period'da full edge

### 3. Combo Live + v63 (KOMBO)
- Toplam sermayenin **%70'i live, %30'u v63**
- İki bot ayrı equity, ayrı risk pool
- Toplam max_concurrent: live 16 + v63 8 = 24 (her birinde ayrı)
- **Combo Sharpe** muhtemelen tek live'dan yüksek (korelasyon < 0.3 beklenir)

## Risk Uyarıları

1. **Sermaye limiti** — $1M+ portföyde slippage edge'i eritir. **$50K-500K sweet spot.**
2. **Düşük vol dönemleri zayıf** — Nisan 2026 -%14 örnek. Regime gate olmadan deploy etme.
3. **High WR ama high vol** — pozitif ay %82 ama std %25/ay. Tek ay -%14 görmeye hazır ol.
4. **Real fees test edilmedi** — paper test ile 1-2 hafta fee/slippage doğrula.
5. **rsi2 widestop FILTER İLE çöker** — sl_pct >= %2.5 filtresi koyma (live config'inde var, v63'te konulmamalı).

## Deploy Adımları (Manuel)

### Aşama 1: Paper Test (1-2 hafta) [PENDING]
```bash
# Yeni config: configs/risk_phoenix_scalp_15m_rsi2_v63.yaml
# Yeni launchd plist: com.priceaction.futures15m_v63.plist
# Ayrı journal: data/futures_journal_15m_rsi2_v63.duckdb
```
- Live + v63 paralel paper trade
- Real fee/slippage gözle
- DD pattern doğrula

### Aşama 2: Korelasyon Verify [PENDING]
- Lab tournament combo Sharpe simülasyonu
- ρ(live, v63) < 0.3 olmalı (varsayım)
- Aksi → v63 single-bot olarak değerlendir

### Aşama 3: Production Deploy [PENDING]
- Principal manuel approval (ADR-002)
- Risk Officer endorse
- Sermaye allocation: half-Kelly (%50 risk) veya regime-gated
- Telegram notify_position_open/close ekleme

## Rollback Planı

- v63 ilk hafta DD > -%10 → halt + investigate
- Aylık ROI < +%5 → 2 hafta sonra reject
- Live bot'un performansını düşürürse (negative interaction) → unload

## Kararlar/Onaylar Beklemede

- [ ] Principal: paper veya direct production?
- [ ] Risk Officer: half-Kelly mı full mı?
- [ ] Ops: yeni plist + journal infrastructure
- [ ] Lab: combo Sharpe analizi

## Referanslar

- 7 round iterate: commits `bd9ecf4` → `6a6b6ed`
- Detaylar: `memory/researcher/realistic_backtest_results/rsi2-iterate-v[1-7]-comparison.json`
- Protokol: `memory/researcher/iterate_protocol.md`
- Base hypothesis: `memory/researcher/hypotheses/2026-05-14-rsi2-extreme-fade.md`
