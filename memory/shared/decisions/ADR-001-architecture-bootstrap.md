---
adr: 001
title: Architecture Bootstrap
status: accepted
date: 2026-05-08
authors: [human_principal, ceo_agent]
---

# ADR-001 — Architecture Bootstrap

## Context
Sıfırdan kurulan otonom price action swing trading sistemi. Kripto MVP, 1D + 1W timeframe, klasik price action (engulfing, pin bar, S/R). Backtest 3 yıl, tüm USDT-perp + spot evreni (likidite filtreli).

## Decision
- Şirket benzeri 10 departman.
- 4 LLM-şefli departman (CEO / Researcher / Analyst / Lab Scientist) + 6 deterministik (Data / Signal / Risk / Portfolio / Execution / Ops).
- Hibrit zekâ: deterministik kod emir verir, LLM yalnızca araştırma + raporlama.
- Stack: Python (pandas, ccxt, vectorbt, FastAPI, Claude Agent SDK).
- Memory: per-agent identity/know_how/learning + shared facts/lessons/decisions.
- RAG: ChromaDB lokal, `knowledge/seeds.yaml` ile seed.
- Faz gate'leri sayısal: yıllık net > %70, Sharpe > 1.5, MaxDD < %20 (Faz 2).

## Alternatives Considered
1. **TypeScript stack** — backtest kütüphanesi olgunluğu zayıf; reddedildi.
2. **Tek LLM agent her şey yapar** — sorumluluk konsantrasyonu, debug zor; reddedildi.
3. **LLM emir verir** — model halüsinasyonu trade riskine direkt bağlanır; reddedildi.

## Consequences
- Pozitif: net sorumluluk, izlenebilir kararlar, anti-overfit kültür, sermaye koruması önce.
- Negatif: mimari karmaşıklığı artıyor, başlangıçta daha fazla iskelet kodu.
- Risk: LLM agent'ların etkisinin ölçülmesi — hangi rapor karar etkiledi?

## Follow-ups
- Faz 2 sonu re-evaluate — gate düşerse araştırma yöntemini revize et.
- 6 ay sonra LLM cost-benefit analizi (Lab tarafından).
