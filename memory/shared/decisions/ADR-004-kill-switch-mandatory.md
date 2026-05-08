---
adr: 004
title: Kill-Switch Zorunlu — Çoklu Tetikleyici, Tek Yön
status: accepted
date: 2026-05-08
authors: [human_principal]
---

# ADR-004 — Kill-Switch Zorunlu

## Context

Otonom sistem her an "saçmalama" potansiyeli taşır:
- Veri akışı bozulduğunda yanlış sinyal seli
- Exchange anomalisi (flash crash, halt)
- Bug — risk parametresinin yanlış uygulanması
- LLM önerisi yanlış işlenirse

Bu durumlarda **anında durdurma** zorunlu. Tek bir mekanik ile değil, çoklu yol ile.

## Decision

Kill-switch çok kapılı:
1. **Telegram komutu:** `HALT_TRADING` (whitelisted chat_id'den).
2. **CLI:** `pa ops halt` (lokal makinede).
3. **API:** `POST /admin/halt` (auth header'lı).
4. **Otomatik tetik:** Risk breakers → otomatik halt.
5. **Heartbeat kaybı:** Execution servisi 5 dk heartbeat vermezse → halt + alarm.

## Implementation

- `Redis` veya basit dosya flag: `data/halt_flag` dosyası varsa Execution yeni emir red.
- Resume tek yoldan: `pa ops resume --confirm` (insan onayı zorunlu) + flag silme.
- Mevcut açık pozisyonlar otomatik kapatılmaz; SL/TP child order'lar borsada zaten yerleştirilmiş, korumalı.

## Hard Limit

- ❌ Kill-switch bypass etmek için kod yok. Test dahil.
- ❌ Otomatik resume yok. Daima insan onayı.

## Consequences

- **Pozitif:** Çoklu kapı → hangisinden olursa olsun durdurulabilir.
- **Negatif:** Yanlış tetikleme operasyonel kayıp (bekleyen iyi sinyaller atlanır). Kabul edilebilir.
- **Risk:** Kill-switch komutu chat_id sızdırılırsa kötü niyetli halt. Mitigation: chat_id kısıtlı + 2FA opsiyon.
