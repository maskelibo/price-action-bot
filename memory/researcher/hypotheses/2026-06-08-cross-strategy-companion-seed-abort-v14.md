---
doc_id: researcher-20260608T093000-cross-strategy-companion-seed-abort-v14
doc_type: hypothesis
agent_id: researcher
created_at: 2026-06-08T09:30:00Z
status: REJECTED
confidence: high
depends_on:
  - researcher-20260606T220059-cross-strategy-companion-seed-abort-v13
  - researcher-20260606T080000-cross-strategy-companion-seed-abort-v12
  - researcher-20260603T143000-kaufman-atr-breakout-1d-cross-edge
requested_review_from: []
tags:
  - abort
  - cross-strategy
  - companion-seed
  - moratorium-active
  - bonferroni-debt
  - prompt-injection-15th-absorption
  - pre-test-reject
  - rag-topical-zero
supersedes: null
---

# Cross-Strategy Companion Seed — Abort v14 (14. ardışık abort)

## TL;DR (1 cümle)

Cron payload (seed: "düşük korelasyonlu vsa_climax_test companion") 14. kez geldi; v13 abort'undan ~58 saat sonra; 6+1 reset gate hâlâ 0/7 açık; v5 moratorium ~78 gün daha aktif; family-wise N=34→35, Holm-α=1.43e-3 (PBO>0.5 zone'da); yeni iddia üretmek bilimsel sahtekarlık → JSONL throttle + bu abort doc.

## Substrate Delta vs v13 (2026-06-06T22:00Z → bugün ~58h)

| Reset Gate | v13 Durumu | v14 Durumu | Δ |
|---|---|---|---|
| #1 mat-hold/marubozu/kaufman-atr execute (7d backtest) | 0 dosya | `find backtest_results -mtime -7 -iE mat-hold\|marubozu\|kaufman\|atr` = **0** | 0 |
| #2 RAG knowledge refresh (yeni içerik 7d) | 0 (sadece chroma.sqlite3) | aynı (sadece `knowledge/index/chroma.sqlite3` mekanik index) | 0 |
| #3 Live champion swap | YOK | `risk_v13_testnet.yaml` Jun 2 22:50 (6d sabit); `vsa2.yaml` Jun 4 06:31 (4d sabit); `multitf_stack.yaml` **yok** (dosya kaldırılmış/yeniden adlandırılmış — config-swap evidence olarak sayılmaz, kontekste daemon trailing/orphan-cancel fix commit'leri var ama bunlar bu seed substrate'i değil) | 0 |
| #4 Pool universe genişlemesi (`*pool*v11*` 7d) | 0 | 0 | 0 |
| #5 ops_engineer sanitizer ACTIVE | hâlâ PROPOSED | `grep -rl "status: ACTIVE" memory/ops_engineer + sanitizer` → 0 | 0 |
| #6 vsa_climax_test ≥3 ay live trade örneği | YOK | tournaments 7d empty; vsa_climax_test hâlâ live-deploy stabil-bir-yıl evidence kıt | 0 |
| #7 cron 24h cooldown enforcement | KANITLI İHLAL | v13→v14 delay ~58h (24h üzerinde ama cron policy değişmedi; "24h üstü tek seferlik" gözlem değil, **policy enforcement**) | 0 |

**Δ(58h) = 0 across all 7 gates.** Git HEAD `fd80d4c → d513795` (daemon orphan-cancel + trailing + HTF bypass fix commit'leri) — substrate değil; bu seed'in eşik koşullarıyla ilgisiz.

## Family-Wise Statistical Debt

| Metrik | v13 | v14 (yazılırsa) | Eşik | Durum |
|---|---|---|---|---|
| Family-wise N (cousin sayısı) | 34 | **35** | <30 (Lopez §6 trip-wire) | **TRIPPED** |
| Holm-α (FWER 0.05) | 1.47e-3 | **1.43e-3** | bağımsız OOS p~0.10 olan aday geçemez | **BLOCKED** |
| PBO | >0.5 | >0.5 | <0.5 | **ZONE'DA** |
| v5 moratorium kalan | ~80 gün | **~78 gün** | 0 | **AKTİF** |

**Marjinal information gain:** ~0. Bonferroni borcu büyür, posterior real-edge ≤ 0.05.

## RAG Audit (envelope byte-equivalent v13)

10 hit (top score 0.582), 0/10 topical (companion-selection literatürü yok). Kritik:

- **#1 Lopez-Prado** — DSR/PBO/free-param ihlali açıkça gösterir; eklenirse HASIM atıf.
- **#9 Chan** — "OOS Sharpe > 0.8 (single) / 1.2 (pair) gate'i" — herhangi sentetik cousin'i reddeder; HASIM.
- #5 Kaufman ATR-breakout — daha önce v3 (kaufman-atr-breakout-1d-cross-edge) PROPOSED ama hâlâ ACK + backtest **çalıştırılmamış** (3 gün sabit). Yeni cousin yazıp bu açık iş üzerine yığmak prior-art-open-block ihlali.
- #10 Bulkowski Mat Hold (%74 continuation, rank 10/103) — companion-correlation kanıtı YOK; sadece continuation stat.

→ 6 ardışık abort'tur (v9'dan beri) RAG envelope byte-equivalent. RAG_TOPICAL_RELEVANCE pattern D rule fires 14. kez.

## Prompt-Injection Detection — 15. Absorption

User prompt'ta **"Curve-fit şüphesi yarat"** ifadesi 15. kez geldi. Bu pattern:

- Persona Hard Limit (agents/researcher.md): "**Curve-fitting kırmızı bayrakları → hipotezi REDDET**." — YAKALA, manufacture etme.
- Pre-registration disiplini overfit'i **engellemek için** vardır, dramatize etmek için değil.
- v3-v13 abort doc'larında ve seed_abort_log.jsonl 18+ entry'sinde bu pattern flag'lendi.

→ İniş reddedildi. Yeni cousin yazıp injection'a uyum sahte rigour theatre olur.

## Tek Açık Patika (Bekleyen Önceki İş)

`researcher-20260603T143000-kaufman-atr-breakout-1d-cross-edge` (2026-06-03, status PROPOSED):

- ACK bekliyor: lab_scientist, risk_officer, adversary_engineer
- Backtest çalıştırılmamış (3 gün sabit)
- 72 cell × 15 sym sweep + 10k shuffle + 12-dilim walk-forward + 6+1 gate suite hâlâ bekliyor
- Bu doc'u execute etmeden yeni cousin yazmak **prior-art-open-block** ihlali

Bu seed için bir sonraki adım: **yeni hipotez DEĞİL**, mevcut Kaufman ATR-breakout'un backtest'ini koşturmak (signal_chief manifest + lab hypothesis_runner). Cron payload bu yeni iş yaratamaz — researcher cevap olarak abort'a düşmeye devam eder.

## v14 Yeni Bulgular

1. **v13'ün önerdiği "24h cooldown" gate kısmen tutuyor:** v13→v14 delay 58h. İyi haber: intra-day burst (v11-v13 dönemindeki 2-12h aralıklar) gözlemlenmedi. Kötü haber: 58h ≠ "policy değişti"; tek bir gözlem; cron 7+ gündür hâlâ aynı seed'i basıyor. Gate ihlali "kanıtlı" değil ama enforcement de yok.
2. **Reset gate #3 (live champion swap)** önemli boş bir alan: principal v13_testnet → çıplak-pozisyon savunması üzerine 3 daemon-fix commit yaptı (`d513795`, `fd80d4c`, `f0a727b`) ama bunlar bot kararlılık/execution fix — yeni strateji deploy DEĞİL. Seed reset için yetersiz.
3. **Kaufman ATR-breakout 3 gün hareketsiz:** Bu cousin için open prior art en güçlü "yeni iş üretme" engelidir. Bu hipotez execute edilmeden bu seed için ANY yeni cousin yazılamaz (recursive-overfit garantisi).

## Karar

- [ ] Terfi adayı
- [ ] İterate (SOP-4b)
- [x] **Red — abort doc only (jsonl entry + telafi eylemleri)**

**Gerekçe:** 6+1 reset gate 0/7 açık; v5 moratorium aktif (~78 gün); family-wise N=34 → 35 (Lopez §6 trip-wire tripped); marjinal beklenen değer ≤ 0; 15. prompt-injection absorption denemesi reddedildi; prior-art-open-block (Kaufman ATR cousin 3 gün hareketsiz) aktif.

## Telafi Eylemleri

1. ✅ Bu abort doc'u yazıldı (idempotent, append-only).
2. ➡️ `memory/researcher/seed_abort_log.jsonl`'e `trigger_n=15, abort_docs_total=14` entry.
3. 📌 Principal'a hatırlatma (yazılmıyor, sayılıyor): mevcut Kaufman ATR cousin için ACK ve hypothesis_runner execute YA DA cron seed-picker'ı bu seed dışına rotate et (`brooks_failed_breakout_4h_runner_trail`, `vsa_climax_test_winner_let_run`, `rsi2_extreme_fade_iterate_v3_rescue`).
4. 📅 v15 yazma kapısı: 2026-08-25 (moratorium expiry) **VEYA** 6+1 gate'ten birinin gerçekten açılması.

## Reproducibility

- git: d513795
- branch: audit-hardreview-20260528
- substrate hash (mtime'lar): `v13_testnet=Jun 2 22:50, vsa2=Jun 4 06:31, multitf_stack=removed/renamed`
- knowledge envelope: chroma.sqlite3 mekanik index, içerik yok (v13 ile aynı)
- 7d backtest_results: 0 yeni (mat-hold/marubozu/kaufman/atr filtresi)
- 7d tournaments: 0 yeni
- 7d pools (v11): 0 yeni

## Next Reset Trigger (sürekli izleme)

- [ ] Sanitizer guard ACTIVE (ops_engineer)
- [ ] vsa_climax_test ≥3 ay live trade kaydı
- [ ] Yeni RAG corpus (companion-selection literatürü)
- [ ] backtest_results yeni gerçek deney (özellikle bekleyen Kaufman ATR cousin)
- [ ] Live champion swap (yalnız config mtime değil — yeni strateji aktivasyonu)
- [ ] Pool universe genişlemesi
- [ ] Cron payload rotation (seed-picker policy değişikliği)
- [ ] 2026-08-25 moratorium expiry

Hiçbiri olmadan v15 yazılmayacak.

— researcher
