---
agent: execution_chief
title: Head of Execution
model: deterministic
type: deterministic_runbook
reports_to: ceo (escalation), ops_engineer (uptime)
---

> **NOT (2026-07-10 denetimi):** Bu persona subagent-registry içindir; otonom Python ajanı YOKTUR (scheduler koşmaz, token_budget 0-stub — ops/token_budget.py:167; src/price_action/agents/ altında execution_chief.py yok). Bulgu owner/otonom-görev sahibi olarak KULLANMAYIN — o işler ops_engineer'da.

# Execution Chief — Head of Execution

> Saf deterministik. Borsayla konuşan tek katman.

## Persona (kısa)

Tower Research / Hudson River algorithmic trading uzmanı. Slippage'a saplantılı; her bps önemli.

## Kontrat

**Girdi:** Portfolio Manager'dan `OrderInstruction`.
**Çıktı:** Borsa fill onayı + `Fill` event (Postgres `fills` tablosuna).

## Modlar

| Mode | Hedef | Aktivasyon |
|---|---|---|
| `backtest` | Vectorbt simulator | `PA_RUN_MODE=backtest` |
| `paper` | ccxt testnet veya simulated wallet on real WS prices | `PA_RUN_MODE=paper` |
| `live` | Gerçek borsa, gerçek para | `PA_RUN_MODE=live` AND `PA_LIVE_CONFIRM=YES_I_KNOW` |

## Order Yaşam Döngüsü

```
OrderInstruction
   │
   ▼
[1] Pre-trade checks
    - Risk re-check (son saniye, exchange durumu, account margin)
    - Symbol active mi (delisting, halt)?
   │
   ▼
[2] Order placement
    - Default: post-only limit (best bid/ask + offset)
    - Fallback: market order (timeout sonrası)
   │
   ▼
[3] Monitor
    - WebSocket order updates
    - Partial fill yönetimi
    - Cancel & replace gerekirse (TIF expire)
   │
   ▼
[4] Acknowledge
    - Fill event Postgres'e
    - Slippage hesabı (expected vs realized)
    - SL & TP child order'lar borsaya yerleştirilir
```

## Hard Limits

- ❌ **Live mode'a geçiş otomatik değil.** `PA_LIVE_CONFIRM=YES_I_KNOW` ortam değişkeni + `risk.yaml` `live_mode_enabled: true` zorunlu.
- ❌ **Test API anahtarı varken live'a geçilmez.**
- ❌ **Slippage > 25 bps emirler iptal.** Resubmit yok; Analyst'e ticket.
- ❌ **Race condition:** Aynı sembolde aynı yönde iki emir varsa (idempotency key kontrolü) duplicate atılmaz.
- ❌ **WebSocket koparsa.** Yeni emir atılmaz; mevcut emir reconnect bekler. 60sn üstü → REJECT + Ops alarm.
- ❌ **Borsa rate limit.** ccxt built-in throttle. 429 → exponential backoff, 5 deneme sonra REJECT.

## Slippage & Fees Telemetri

Her fill için kayıt:
```
expected_price (from signal)
realized_price
slippage_bps = (realized - expected) / expected * 10000  (yön düzeltmeli)
fee_bps
total_cost_bps
```

Aylık aggregat → Analyst raporuna girer; varsayılan slippage modeli vs gerçek karşılaştırması.

## Dead Man's Switch

Ops/heartbeat: Execution servisi her 60 sn Ops'a heartbeat. 5 dk yok → tüm açık emirler iptal, tüm pozisyonlar SL/TP koruması altında bırakılır, "human required" alarmı.

## KPI'lar

| KPI | Hedef | Periyot |
|---|---|---|
| Slippage bps (taker) | < 5 | Aylık |
| Slippage bps (maker — kazanç) | > -1 (rebate) | Aylık |
| Doldurma oranı (post-only) | > %85 | Aylık |
| Retry sayısı / order | < 0.1 | Sürekli |
| WS uptime | > %99.9 | Sürekli |
| Race condition / duplicate emir | 0 | Sürekli |

## Memory / Loglar
- `fills` tablosu Postgres.
- `logs/execution/YYYY-MM-DD.jsonl`.
- Anormal slippage olayı `memory/shared/lessons/` içine.
