---
adr_id: ADR-006
title: Production Konfig Kilitlendi — Engulfing v1 (R%2 lev 1-5x dinamik)
status: accepted
date: 2026-05-08
author: ceo
tags: [production, strategy, engulfing, risk, paper_trading, faz_6]
---

# ADR-006 — Production Konfig Kilitlendi (v0.5.0)

## Bağlam

12 saatlik yoğun backtest + rafine sürecinden sonra production-aday strateji finalize oldu. Bugün test edilen hipotez ve konfigler:

- **classic_pa** (5 pattern + EMA50): yıllık +%2.4 baseline, +%7-8 BTC'de — yetersiz
- **engulfing_continuation** (post-pullback to 20EMA, body engulf strict): yıllık +%10.4 baseline, lev 5x dinamik ile +%68 → **PROMOTE**
- **smc_orderblock**: REJECT (mekanik implementasyon edge yok, win rate %26 vs community %60-70 claim)
- **wyckoff_phase_d**: REJECT (1d crypto'da signal frequency çok düşük, 7 trade)
- **ML meta-labeling**: ABANDON (n=99 yetersiz, OOS precision 0)

## Karar

**Production aday: engulfing_continuation**, aşağıdaki konfigle kilitlendi:

```yaml
strategy: engulfing_continuation
risk_per_trade: 0.02  # %2 of current equity
leverage: dynamic 1x-5x  # confidence-based per-trade
confidence_tiers:
  - {min: 0.00, max: 0.32, leverage: 1}
  - {min: 0.32, max: 0.42, leverage: 2}
  - {min: 0.42, max: 0.52, leverage: 3}
  - {min: 0.52, max: 0.58, leverage: 4}
  - {min: 0.58, max: 1.01, leverage: 5}
confidence_formula: 0.35*confluence_norm + 0.25*kaufman_er + 0.25*rolling_sharpe_norm + 0.15*body_ratio
breakers:
  daily: 0.05    # %5
  weekly: 0.10   # %10
  monthly: 0.15  # %15
filters:
  kaufman_er_min: 0.20  # chop reject
  bear_regime_size_factor: 0.5  # 200-EMA altında long size %50
universe: [BTC, ETH, SOL, BNB, XRP, DOGE, ADA, AVAX, LINK, DOT] /USDT
timeframe: 1d (decision after close)
max_concurrent: 5 positions
fees: taker 0.075% / maker -0.01%
slippage: 5 bps
```

## Beklenen sonuç (3y backtest, $10K base)

| Metrik | Değer |
|---|---|
| Yıllık net (compound) | +%67.97 |
| 3y compound | +%374 ($47,392) |
| MaxDD | -%65 |
| Walk-forward pozitif oran | %83 (5/6 pencere) |
| Walk-forward Sharpe | 1.13 |
| DSR (López) | 0.18 (marjinal) |
| Lab gate | 2/3 PASS (PROMOTE) |
| Win rate | %44 |
| Profit Factor | 1.69 |

## Mikro-canlı projeksiyonu ($200 başlangıç)

- 3 yıl sonra: ~$946 (compound, sapma yokken)
- Realistic %20 sapma ile: ~$680-750
- Aylık ortalama: ~$15-20

## Sonuç

- ✅ Faz 2 ROI gate (yıllık %70) hedefini neredeyse tutturdu (%67.97)
- ✅ Walk-forward consistency güçlü (5/6 pozitif)
- ✅ Risk officer breaker integrasyonu test edildi
- ✅ Paper trading orchestrator (Faz 6) hazır, deployment tek-tıkla
- ✅ LLM brief + Telegram alarm (Faz 5) hazır
- ⚠️ DSR 0.18 marjinal — 5y+ data ile düzeltilebilir (paper trading sırasında biriktirilecek)
- ⚠️ DD %65 yüksek — psikolojik olarak zor, ama crypto'da kabul edilebilir
- ⚠️ 2024 yıl dilimi -%29 zayıf (W4) — gelecekte de görebilir

## Sıradaki adımlar (Faz 6 → 7)

1. Binance testnet API key + Telegram bot token (kullanıcı setup'ı)
2. Paper trading watchdog 4 hafta gözlem
3. Sapma %20 altıysa Faz 7 mikro canlı $200
4. İlk 2 hafta her gün CEO brief insan tarafından kontrol edilecek

## Alternatifler (red edilen production aday)

1. **classic_pa Aşama B** — yıllık %2.4, çok zayıf
2. **engulfing R%3 lev 3x fix** — yıllık %70, DD %58, lev "kitlenmesin" prensibine ters
3. **engulfing R%3 lev 1-5x** — yıllık %132, DD %84 (likidasyon hattı, çok riskli)
4. **engulfing R%2 lev 1-3x DD-scale** — yıllık %52, kabul edilebilir ama A'dan zayıf

## Referans

- `src/price_action/strategies/engulfing_continuation.py`
- `configs/risk.yaml` (max_leverage 5, confidence_tiers)
- `scripts/run_real_backtest.py`, `scripts/walk_forward_a_config.py`
- `scripts/paper_trading_loop.py` (Faz 6 deployment)
- `scripts/llm_orchestrator.py` (Faz 5)
- `tests/` 361 passing test
- Git tag `v0.5.0` (snapshot)
