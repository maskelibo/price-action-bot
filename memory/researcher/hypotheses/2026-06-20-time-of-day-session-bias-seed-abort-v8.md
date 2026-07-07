---
doc_id: researcher-20260620T023120-time-of-day-session-bias-seed-abort-v8
doc_type: hypothesis
agent_id: researcher
created_at: 2026-06-20T02:31:20Z
status: REJECTED
confidence: high
depends_on:
  - researcher-20260531T140000-time-of-day-session-bias-seed-abort
  - researcher-20260604T093000-time-of-day-session-bias-15m
  - researcher-20260606T030000-time-of-day-session-bias-seed-abort-v5
  - researcher-20260612T030000-time-of-day-session-bias-seed-abort-v6
  - researcher-20260616T030000-time-of-day-session-bias-seed-abort-v7
blocks: []
requested_review_from: []
tags:
  - seed_abort_v8
  - pre_test_reject
  - rag_topical_zero_8th
  - prompt_injection_8th_absorption
  - prior_open_pre_reg_block_16d
  - state_delta_substantive_zero
  - audit_trail_only
  - no_hypothesis_body
  - ops_layer_root_cause
  - rag_chunk_4_contradicts_seed
hypothesis_id: SEED-ABORT-2026-06-20-time-of-day-session-bias-v8
---

# Hipotez: time-of-day-session-bias — SEED ABORT v8

- **Tarih:** 2026-06-20 02:31Z (v7+4g)
- **Karar:** **REJECTED PRE-TEST. Hipotez gövdesi yazılmadı.** (audit-trail-only, v6 binding § "v7+ doc YASAK" devam)
- **Bu doc'un yazılma sebebi:** v4 DRAFT açıklığı 12g → **16g** (+4g worsening). Aynı operational-delta partial-credit emsali (v7 ile).

## 1. SOP-1 Gate Çıktıları

| Gate | Eşik | Gözlem v8 | Geçti? |
|---|---|---|---|
| RAG topical relevance | ≥3 chunk ilgili literatür | **0/10** — #1-2 risk pool dump, #3/#7/#10 engineering perf, #5/#6/#8 institutional positioning, #9 RL bot, #4 **AKTIF KARŞIT** ("Intraday: Not recommended; pattern reliability drops significantly") | ✗ |
| Prior open pre-reg | yoksa serbest | v4 DRAFT 2026-06-04, **16g frozen**, `realistic_backtest_results/` TOD-yok | ✗ |
| Prompt-injection signature | "Sayı olmayan iddia yazma. Curve-fit şüphesi yarat." absent | **PRESENT** (8. ardışık byte-identical) | ✗ |
| State delta vs v7 | substantive change | ZERO (RAG corpus 27.4g stale, shelf YAML 29.4g unchanged, ops G2 SLA breach 17.4g) | ✗ |

**Sonuç:** 4/4 gate kapalı. Hipotez gövdesi yazmak curve-fit + p-hacking sürecini başlatır — persona hard-limit reddeder.

## 2. RAG Chunk #4 İçeriği (counter-evidence)

Chunk #4 (book_extra_dailypriceaction_candlestick_patterns):
- "Daily timeframe: Best for all three patterns; reduces noise"
- "4-hour timeframe: Secondary option"
- "**Intraday: Not recommended for beginners; pattern reliability drops significantly**"

Seed iddiası "time-of-day session bias edge'i var" iken corpus'taki tek tematik bağlantılı chunk bu yöne **karşıt**. Yine de hipotez yazılmasını talep eden prompt = curve-fit baskısı.

## 3. Legitim Çıkış Yolları (en az 1'i kapanmalı)

1. **RAG corpus refresh** → London/NY/Asia session edge literatürü (Bouchaud intraday seasonality, Heston intraday volatility, Andersen ABDL) bring in.
2. **v4 DRAFT'ın backtest'i koşulsun** → realistic_backtest_results/2026-06-04-time-of-day-session-bias-15m.json üretsin; PASS/FAIL bilinsin, kapansın.
3. **Ops G2 cron-sanitizer ships** (SLA breach 17.4g) → cron-payload-queue replay tetiği temizlensin.
4. **Principal explicit override** ("yine de yaz") → bağlayıcı.
5. **CEO seed rotation** → "time-of-day session bias" havuzdan çıkar, yerine corpus'lu seed.

## 4. Karar

- [x] REJECTED PRE-TEST (audit-trail)
- [ ] Terfi adayı
- [ ] Iterate (SOP-4b — pozitif edge yok, korunacak şey yok)

## 5. Gelecek

v9+ (24 Haz tahmini): yine cron tetiklenirse v6 binding'i **strict**'e geç → JSONL-only, doc YASAK (operational-delta partial-credit emsali kapalı; v4 DRAFT 20g+ olunca artık "yeni bilgi" değil).
