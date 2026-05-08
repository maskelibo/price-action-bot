---
adr: 005
title: Her Trade ve Backtest Reproducibility Manifesto Taşır
status: accepted
date: 2026-05-08
authors: [human_principal, researcher_agent]
---

# ADR-005 — Reproducibility Manifest

## Context

Backtest sonuçları "tekrarlanabilir" olmalı. Aynı kod + aynı config + aynı veri → bit-identical equity curve. Aksi takdirde:
- Hangi sonuca güveneceğimizi bilemeyiz.
- Hata izleme imkansız.
- Lab tournament'ta "champion vs challenger" karşılaştırması yapılamaz.

## Decision

Tüm önemli artifact'lar (backtest sonucu, trade kaydı, paper fill) `ReproducibilityManifest` taşır:

```python
class ReproducibilityManifest:
    git_hash: str       # her commit'te değişir
    config_hash: str    # config dosyalarının stable hash'i
    data_hash: str      # kullanılan veri snapshot'ının hash'i
    code_hash: str      # paket sürümü + critical dosya hash
    created_at: datetime
```

## Implementation

- `contracts.py::stable_hash()` deterministik JSON-based hash.
- Backtest engine sonuç döndürmeden önce manifest doldurur.
- Execution layer her fill için manifest'i Postgres'e yazar.
- Lab tournament aynı manifest'i tekrar çalıştırarak "bit-identical mi?" testi yapar.

## Hard Limits

- Random seed her yerde sabit (`np.random.seed(42)`) ya da explicit (config'ten).
- Float precision: aynı numpy / pandas sürümü.
- Veri sürümü: `data_hash` veri snapshot'ından — yeni veri eklenirse hash değişir, yeni manifest çıkar.

## Consequences

- **Pozitif:** Tam tekrarlanabilirlik. Audit zinciri net. Tournament sağlam.
- **Negatif:** Performans hafif düşer (her sonuçta hashing). Kabul edilebilir.

## Follow-ups

- CI'da reproducibility testi: aynı config'le iki run → equity curve bit-identical.
