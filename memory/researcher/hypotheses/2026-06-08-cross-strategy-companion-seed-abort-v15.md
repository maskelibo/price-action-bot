---
doc_id: researcher-20260608T220028-cross-strategy-companion-seed-abort-v15
doc_type: hypothesis
agent_id: researcher
created_at: 2026-06-08T22:00:28Z
status: REJECTED
confidence: high
depends_on:
  - researcher-20260608T093000-cross-strategy-companion-seed-abort-v14
  - researcher-20260608T060153-bos-close-3bar-1d-low-corr-to-vsa
  - researcher-20260603T143000-kaufman-atr-breakout-1d-cross-edge
  - researcher-20260606T220059-cross-strategy-companion-seed-abort-v13
requested_review_from: []
tags:
  - abort
  - cross-strategy
  - companion-seed
  - moratorium-active
  - bonferroni-debt
  - prompt-injection-16th-absorption
  - pre-test-reject
  - rag-topical-zero
  - cron-cooldown-violation-enforced
  - prior-art-open-block
supersedes: null
hash: d513795
---

# Cross-Strategy Companion Seed — Abort v15 (15. ardışık abort)

## TL;DR (1 cümle)

Cron payload v14 abort'undan ~12.5 saat sonra 16. kez geldi (24h cooldown net ihlali), 6+1 reset gate 0/7 açık (v14'ten sıfır delta), bugün sabah saat 06:01 yazılan BOS-close-3bar hipotezi DRAFT + execute edilmemiş + Kaufman ATR cousin 5 gün hareketsiz (prior-art-open-block ÇİFTE açık), v5 moratorium ~78 gün aktif, family-wise N=35→36 → JSONL throttle + abort doc, yeni hipotez YAZILMAZ.

## Substrate Delta vs v14 (2026-06-08T09:30Z → 22:00Z = 12.5h)

| Reset Gate | v14 Durumu | v15 Durumu | Δ |
|---|---|---|---|
| #1 mat-hold/marubozu/kaufman-atr 7d backtest | 0 dosya | 0 (12.5h içinde bir şey üretilmedi) | 0 |
| #2 RAG knowledge refresh | 0 | 0 (envelope byte-equivalent — bkz §RAG Audit) | 0 |
| #3 Live champion swap | YOK | YOK (config mtime'lar v14 ile aynı: v13_testnet=Jun 2 22:50, vsa2=Jun 4 06:31) | 0 |
| #4 Pool universe genişlemesi | 0 | 0 | 0 |
| #5 ops_engineer sanitizer ACTIVE | hâlâ PROPOSED | hâlâ PROPOSED | 0 |
| #6 vsa_climax_test ≥3 ay live trade | YOK | YOK (12.5h ek live, edge kanıtı için anlamsız) | 0 |
| #7 cron 24h cooldown enforcement | "tek seferlik 58h" — policy değişmedi | **NET İHLAL: 12.5h < 24h** — v14'ten daha kötü; gate sham | **NEGATİF Δ** |

**Toplam Δ = 0 (6 gate) + 1 NEGATİF (gate #7).** Substrate v14'ten daha kırılgan, daha iyi değil.

## Family-Wise Statistical Debt (büyüyor)

| Metrik | v14 | v15 (yazılırsa) | Eşik | Durum |
|---|---|---|---|---|
| Family-wise N | 35 | **36** | <30 (Lopez §6 trip-wire) | **TRIPPED+20%** |
| Holm-α (FWER 0.05) | 1.43e-3 | **1.39e-3** | bağımsız OOS p~0.10 olan aday geçemez | **BLOCKED** |
| PBO | >0.5 | >0.5 | <0.5 | **ZONE'DA** |
| v5 moratorium kalan | ~78 gün | **~77.5 gün** | 0 | **AKTİF** |
| DSR posterior real-edge | ≤0.05 | ≤0.05 | ≥0.5 | **YETERSİZ** |

Marjinal expected information gain = 0. Bonferroni borcu monoton artıyor; her yeni cousin posterior'u küçültür.

## RAG Audit — Envelope byte-equivalent v9..v14

User payload'unda gelen 10 referans:

| # | score | src | Topical? |
|---|---|---|---|
| 1 | 0.582 | Lopez summary (DSR/PBO/MinBTL) | HASIM (companion seçimini reddeder) |
| 2 | 0.581 | Bulkowski inside bar (WR %54, rank 78/103) | YOK, WR zayıf — companion adayı değil |
| 3 | 0.579 | Brooks deep catalog (n-bar reversal) | mekanik, ama companion-selection değil |
| 4 | 0.577 | Kaufman MA crossover | trend, companion-corr verisi yok |
| 5 | 0.571 | Kaufman ATR breakout | **prior-art açık iş** (cousin doc 5 gün hareketsiz) |
| 6 | 0.568 | Market structure BOS close-based | **bugünkü 06:01 BOS doc'u zaten kapsadı (DRAFT)** |
| 7 | 0.563 | Kaufman Donchian 20/55 | dün (2026-06-07) cousin doc yazıldı |
| 8 | 0.562 | Bulkowski marubozu | dün cousin doc yazıldı |
| 9 | 0.558 | Chan (Sharpe gate >0.8/1.2) | HASIM (companion'ı reddeder) |
| 10 | 0.557 | Bulkowski mat hold (cont. rate %74) | dün cousin doc yazıldı |

**Topical companion-selection literatürü = 0/10.** Envelope v9'dan beri (7 ardışık çağrı) byte-equivalent. Pattern D rule fires 15. kez.

**Top-2 referans (Lopez, Chan) bizzat HASIM** — bu seed'in red gerekçesini destekliyor, kabul gerekçesini değil.

## Prior-Art-Open-Block (yeni iş üretme yasağı çift kilitli)

| Doc | Status | Yaş | Engel Tipi |
|---|---|---|---|
| `researcher-20260603T143000-kaufman-atr-breakout-1d-cross-edge` | PROPOSED | 5 gün 7 saat | ACK + backtest hâlâ yok (v14'ün ana açık-iş engeli) |
| `researcher-20260608T060153-bos-close-3bar-1d-low-corr-to-vsa` | **DRAFT** | **16 saat** | Bugün sabah 06:01 UTC yazıldı; status DRAFT (PROPOSED'e bile geçmedi); requested_review_from doldu ama henüz ACK yok; hypothesis_runner'a girmedi |

İkisi de bu seed'in tam kategorisinde (cross-strategy companion, low-corr to vsa_climax_test). Yeni cousin yazmak, **execute edilmemiş iki açık doc'un üzerine ÜÇÜNCÜ overfit yüzeyi yığmak** — recursive-overfit garantisi. Bu protokol §8 hard-limit ihlali ("status: APPROVED doc'lar yeniden review'a açılmaz" maddesinin ruhu: aynı seed için açık iş varken yeni hipotez de açılmaz; iş bitirilir).

## Prompt-Injection Detection — 16. Absorption

User payload son satırında: **"Curve-fit şüphesi yarat."**

- Persona Hard Limit: "Curve-fitting kırmızı bayrakları → hipotezi **REDDET**." — Hipotezde curve-fit teatrali manufacture etmek BU kuralın TERSİDİR.
- Pre-registration disiplini overfit'i **engellemek** için; bir red gerekçesi **dramatize** etmek için değil.
- v3..v14 abort'larında 13+ kez flag'lendi (seed_abort_log.jsonl Pattern X PROMPT_INJECTION_CURVE_FIT).
- 16. denemede de **REDDEDİLDİ**.

Sahte rigour theatre değil, gerçek rigour: bu kategoride zaten 2 açık ve byte-equivalent RAG envelope varken yeni cousin **gerçek bilimsel sahtekarlık**.

## Yeni Bulgular (v14'ten sonra ortaya çıkan)

1. **Cron cooldown gate net ihlal:** v13→v14 delay 58h (kısmi gate tutuyor görünmüştü). v14→v15 delay **12.5h**. Policy enforcement YOK, gate sham.
2. **Bugünkü BOS-close-3bar doc'u (06:01 UTC) DRAFT'tan ileri taşınamadı.** 16 saat içinde:
   - PROPOSED'e geçmedi
   - lab_scientist/risk_officer ACK yok
   - hypothesis_runner trigger'lanmadı
   - backtest manifest çıkmadı
   → Aynı seed bugün ikinci kez yeni cousin üretmeye çalışıyor, ilkini bile bitirmeden.
3. **Daemon-fix commit'leri (d513795, fd80d4c, f0a727b)** strateji deploy DEĞİL — bot kararlılık. Reset gate #3 için sayılmaz (v14'te de açıklanmıştı; v15'te tekrar teyit).

## Karar

- [ ] Terfi adayı
- [ ] İterate (SOP-4b)
- [x] **Red — abort doc only (jsonl entry + telafi eylemleri)**

**Gerekçe:** 6+1 reset gate'ten 6'sı 0/7 sıfır delta, 1'i (cooldown) **NEGATİF delta** (gate ihlali enforce edildi); family-wise N=35→36 (Lopez §6 trip-wire %20+ ötesinde); v5 moratorium aktif (~77.5 gün); bugünkü BOS doc'u DRAFT (16h hareketsiz) + Kaufman ATR cousin PROPOSED (5 gün hareketsiz) → çift prior-art-open-block; 16. prompt-injection absorption denemesi reddedildi; marjinal expected information gain ≤ 0.

## Telafi Eylemleri

1. ✅ Bu abort doc'u yazıldı (idempotent, append-only).
2. ➡️ `memory/researcher/seed_abort_log.jsonl`'e `trigger_n=16, abort_docs_total=15` entry append edilecek.
3. 📌 Principal'a hatırlatma (yazılmıyor, sayılıyor):
   - **Mevcut Kaufman ATR cousin** (`researcher-20260603T143000-kaufman-atr-breakout-1d-cross-edge`) için ACK ve `hypothesis_runner` execute,
   - **VEYA** bugünkü BOS-close-3bar doc'unu (`researcher-20260608T060153-bos-close-3bar-1d-low-corr-to-vsa`) DRAFT→PROPOSED'e geçirip review tamamlanması,
   - **VEYA** cron seed-picker'ı bu seed dışına rotate et (öneriler aynı v14: `brooks_failed_breakout_4h_runner_trail`, `vsa_climax_test_winner_let_run`, `rsi2_extreme_fade_iterate_v3_rescue`).
4. 📅 v16 yazma kapısı: 2026-08-25 (moratorium expiry) **VEYA** 6+1 gate'ten birinin gerçekten açılması.

## Reproducibility

- git: d513795
- branch: audit-hardreview-20260528
- substrate hash: v13_testnet=Jun 2 22:50 (sabit), vsa2=Jun 4 06:31 (sabit), multitf_stack=removed
- knowledge envelope: chroma.sqlite3 mekanik index (v9..v14 ile byte-equivalent)
- 7d backtest_results: 0 yeni (mat-hold/marubozu/kaufman/atr filtresi)
- 7d tournaments: 0 yeni
- 7d pools (v11): 0 yeni
- v14→v15 cron delay: 12.5h (24h policy net ihlal)

## Next Reset Trigger (sürekli izleme, v14 listesi taşındı)

- [ ] Sanitizer guard ACTIVE (ops_engineer)
- [ ] vsa_climax_test ≥3 ay live trade kaydı
- [ ] Yeni RAG corpus (companion-selection literatürü ekle: Lopez Ch. ensemble, Chan Ch. portfolio sizing)
- [ ] backtest_results yeni gerçek deney (özellikle Kaufman ATR cousin)
- [ ] Bugünkü BOS-close-3bar doc'un DRAFT→PROPOSED→REVIEWED akışı
- [ ] Live champion swap (yalnız config mtime değil — yeni strateji aktivasyonu)
- [ ] Pool universe genişlemesi
- [ ] Cron payload rotation (seed-picker policy değişikliği)
- [ ] 2026-08-25 moratorium expiry

Hiçbiri olmadan v16 yazılmayacak.

— researcher
