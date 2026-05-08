---
adr: 002
title: LLM Agents Asla Doğrudan Emir Veremez
status: accepted
date: 2026-05-08
authors: [human_principal]
---

# ADR-002 — LLM Agents Asla Doğrudan Emir Veremez

## Context

Otonom trading şirketinde LLM agent'lar (CEO, Researcher, Analyst, Lab Scientist, Ops) yer alıyor. LLM'ler güçlü ama:
- Halüsinasyon riski var.
- Stochastic — aynı girdiye farklı zamanda farklı çıktı.
- Karmaşık talimatlarda tutarsızlık.
- Prompt injection'a kırılgan.

Bir trade'in milyonlarca dolara uzanan etkisi olabilir; bu kararı LLM'e bırakmak kabul edilemez risk.

## Decision

LLM agent'lar **emir veren API'lere erişemez**. Yetkileri:
- ✅ Veri okuma (DuckDB, Postgres, ChromaDB)
- ✅ Rapor yazma (`reports/`)
- ✅ Memory yazma (`memory/`)
- ✅ Strateji manifesto **taslağı** üretme (`configs/strategies/<name>.yaml.draft`)
- ✅ Backtest tetikleme
- ✅ İnsan onayı için öneri

**Yapamayacakları:**
- ❌ Order yerleştirme (Execution layer'a doğrudan çağrı yok)
- ❌ Risk parametrelerini değiştirme (`configs/risk.yaml` write yok)
- ❌ Live mode aktive etme
- ❌ Breaker bypass etme
- ❌ Memory dosyası silme

## Implementation

- LLM Agent base class (`agents/base.py`) tool yetkisini explicit liste ile tanımlar.
- Execution layer LLM API'sinden erişilemez (paket bağımlılık grafiği `agents → execution` değil; `orchestrator → agents`, `orchestrator → execution`).
- `agents/<name>.md` rule dosyaları "Hard Limits" bölümü zorunlu.
- CI testleri import grafiğini doğrular.

## Alternatives Considered

1. **LLM emir verir + insan onayı.** Reddedildi: insan onay sürecinde gecikme + onay yorgunluğu (tüm onayları otomatik tıklanır).
2. **LLM yardımcı + deterministik karar.** Kabul edildi (mevcut karar).
3. **Hiç LLM kullanmama.** Reddedildi: araştırma + raporlama LLM ile çok daha verimli.

## Consequences

- **Pozitif:** Trade riskine LLM hatasının etkisi yok. Audit zinciri net (her trade deterministik koddan geçti).
- **Negatif:** Bazı kararların LLM-otomatize potansiyeli yok; insan onayı gerekiyor.
- **Risk:** LLM önerileri nasıl ölçülür? (Lab takip eder; Faz 5 sonu cost-benefit.)

## Follow-ups

- Faz 5 sonunda LLM önerilerinin pozitif katkı oranı ölçülür.
- LLM cost (token) metriği `pa_llm_tokens_total` ile izlenir.
