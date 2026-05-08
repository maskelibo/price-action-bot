---
type: lesson
date: 2026-05-08
authored_by: human_principal
applies_to: [risk_officer, ceo, portfolio_manager]
confidence: high
tags: [leverage, risk, kripto]
---

# Kaldıraç Disiplini — Kripto Bağlamı

## Ders

Kripto perpetual'larda 100x'e kadar kaldıraç teknik olarak mümkün. Bu **fırsat değil tuzak**. Yıllık %70-80 hedefimiz mütevazı kaldıraçla (3x tavan) ulaşılabilir; daha yüksek kaldıraç volatilite uçlarında likidasyon tek olayla strateji öldürür.

## Pratik Kurallar

1. **Sembol başına maks 3x.** `configs/risk.yaml::leverage.max_leverage_per_symbol = 3`.
2. **Portföy notional / equity oranı ≤ 4.** Yani 10k USDT sermaye ile maks 40k USDT açık pozisyon notional'ı.
3. **Likidasyon mesafesi ≥ %50.** SL likidasyon fiyatına %50'den yakın olmamalı.
4. **Funding rate izleme.** Çok pozitif funding (>0.1% / 8h) varken long açma — funding ödemesi 1 günde %0.3 yer.
5. **Rejim-bağlı azaltma.** Bear rejim + yüksek volatilite → kaldıraç tavanı 2x'e düşürülür.

## Tarihsel Uyarılar

- 2021-05-19 BTC -%30 / 24h: 3x'in üstündeki long pozisyonların çoğu likide oldu, isabetli yön bile silindi.
- 2024-08 Yen carry unwind: kripto -%15 / 24h, 5x+ pozisyonlar silindi.
- LUNA 2022-05: short pozisyon doğru yönde olsa bile likidite çekildiği için close yapılamadı (slippage > %20).

## Pratik Davranış

> Sermaye koruma > getiri. Daha düşük kaldıraçla daha uzun yaşa.

## Yakalanma

Risk Officer her order'da `margin_safety_ratio = 0.5` ve `max_leverage_per_symbol` checks. Veto yetkisi mutlak.
