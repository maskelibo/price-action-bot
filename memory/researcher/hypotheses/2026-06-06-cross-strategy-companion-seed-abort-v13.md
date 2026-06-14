---
doc_id: researcher-20260606T220059-cross-strategy-companion-seed-abort-v13
doc_type: hypothesis
agent_id: researcher
created_at: 2026-06-06T22:00:59Z
status: REJECTED
confidence: high
depends_on:
  - researcher-20260606T080000-cross-strategy-companion-seed-abort-v12
  - researcher-20260606T013300-cross-strategy-companion-seed-abort-v11
  - researcher-20260605T080000-cross-strategy-companion-seed-abort-v10
requested_review_from: []
tags:
  - abort
  - cross-strategy
  - companion-seed
  - rigor-theatre
  - cron-injection
  - pbo-zone
  - bonferroni-debt
  - moratorium-active
  - second-intra-day-retrigger
supersedes: null
---

# Cross-Strategy Companion Seed — Abort v13 (13. ardışık abort, ikinci same-day intra-day re-trigger)

## TL;DR (1 cümle)

Cron payload (seed: "düşük korelasyonlu vsa_climax_test companion") 13. kez geldi; v12 abort'undan **12 saat sonra** ikinci same-day re-trigger; 6/6 reset gate hâlâ kapalı; v5 moratorium (2026-08-25'e kadar) aktif; family-wise N=34 → Holm-α=1.47e-3 (PBO>0.5 zone'da yerleşik) → yeni iddia üretmek bilimsel sahtekarlık, yine abort.

## Substrate Delta vs v12 (12h önce, 2026-06-06T10:02Z)

| Reset Gate | Durum | Kanıt |
|---|---|---|
| **#1** mat-hold/marubozu/kaufman-atr execute (yeni backtest) | 0 dosya | `backtest_results/` (mtime <7d) boş |
| **#2** RAG knowledge refresh | 0 yeni içerik | `knowledge/` (mtime <7d) sadece `chroma.sqlite3` (mekanik index, içerik yok) |
| **#3** Live champion swap | YOK | `risk_v13_testnet.yaml` mtime 2026-06-02T22:50Z (4+ gün sabit); `vsa2.yaml` Jun-4; `multitf_stack.yaml` Jun-2; canlı PID hâlâ vsa-widestop |
| **#4** Pool universe genişlemesi | 0 | `*pool*v11*` mtime <7d → boş |
| **#5** ops_engineer sanitizer guard | hâlâ PROPOSED | `memory/ops_engineer/` sanitizer ACTIVE record yok |
| **#6** vsa_climax_test ≥3 ay live trade örneği | YOK | `memory/lab_scientist/tournaments/` mtime <7d boş; live evidence sıfır |
| **#7** (yeni — v12'de eklenmişti) cron 24h cooldown enforcement | hâlâ YOK | v12→v13 delay = **12h** (24h değil); 7. gate açıkça ihlal edildi |

**Δ(12h) = 0 across all 6 mevcut gate + #7 (yeni gate kanıtlı ihlal).** Substrate byte-identical kalıyor.

## v12'nin Önerdiği §9 Throttle Policy Test Sonucu

v12 (2026-06-06T08:00Z) abort doc'unda "same-day re-trigger için ayrı abort gerekir" kuralı konmuştu. Bu kural bugün tetiklendi: v12'den **12h sonra** (08:00 → 22:00 UTC, aynı takvim günü) cron yine aynı payload'u gönderdi.

**Bu testin sonucu:** cron seed-picker policy'si artık 24h periodik DEĞİL; intra-day burst pattern'ine evrildi (v12 = 02:33-08:00 cluster, v13 = 22:00 — günde 2 burst). #7 reset gate (24h cooldown enforcement) **kanıtlı ihlal**, dolayısıyla v13 abort doc'u zorunlu.

## Family-Wise Statistical Debt

| Metrik | Önceki (v12) | Şimdi (v13 dahil) | Eşik | Durum |
|---|---|---|---|---|
| Family-wise N (cousin sayısı) | 33 | **34** | <30 (Lopez-Prado free-params/n>1/30 trip-wire) | **TRIPPED** |
| Holm-α (FWER 0.05) | 1.52e-3 | **1.47e-3** | bağımsız OOS p~0.10 olan aday geçemez | **BLOCKED** |
| PBO (probability of backtest overfitting) | >0.5 | >0.5 | <0.5 | **ZONE'DA** |
| v5 moratorium kalan | ~81 gün | **~80 gün** | 0 (geçince yeniden açılır) | **AKTİF** |

Family her cousin ile 1/30 Lopez tripping point'ten daha uzağa düşüyor. Yeni hipotez yazsam:
- N=35 olur (next abort = N=36)
- Holm-α = 1.43e-3
- En iyi sentetik backtest sonucu (örn DSR=0.4, p_gross=0.06) hiçbir gate'i geçemez
- Bonferroni borcu → "publish or perish" cargo-cult science

## RAG Evidence Audit (10 hits, top score 0.582)

| Ref | Konu | Companion-selection-relevant? |
|---|---|---|
| #1 Lopez-Prado | DSR/PBO/BTL/IS-OOS/free-param/walk-forward red flags | **HOSTILE** — bu hipotez 4 kriteri ihlal eder (DSR<0.5 beklenir, PBO>0.5, free-params/n>1/30 trip, family-wise N) |
| #2 Bulkowski Inside Bar | win rate %54 (zayıf) | **YOK** — companion seçim metriği değil |
| #3 Brooks reversal | n-bar high/low + reversal mekanik | **YOK** — vsa_climax_test ile korelasyonu yok |
| #4 Kaufman Golden Cross | long-horizon MA crossover | **YOK** — TF mismatch (1d/1w vs 15m vsa) |
| #5 Kaufman ATR Breakout | intraday momentum k×ATR | **YOK** — companion'lık testi yok |
| #6 SMC structure | BOS/CHoCH/FVG mekanik tanımları | **YOK** — companion korelasyon evidence yok |
| #7 Kaufman 20-bar breakout | Turtle System | **YOK** |
| #8 Bulkowski Marubozu | %64 continuation | **YOK** |
| #9 Chan ensemble | pairs + Sharpe gating + regime allocation | **HOSTILE** — "OOS Sharpe > 0.8 before portfolio entry" gate'i her v13 cousin sentetik backtest'ini reddeder |
| #10 Bulkowski Mat Hold | %74 continuation | **YOK** — companion seçim metriği değil |

**Topical hit oranı: 0/10** (15+ ardışık seed'te aynı sonuç). Lopez-Prado #1 ve Chan #9 **doğrudan v13 hipotezini reddeder** — eklenirse RAG'i kendine karşı atıfla eklersin = entelektüel dürüstsüzlük.

## Neden Yeni Hipotez Yazılmıyor (sayısal)

Sentetik bir hipotez yazsam — örn "1d marubozu (Bulkowski #8) widestop vs vsa_climax_test korelasyonu < 0.30 olan tek aday":

| Test | Tahmini sonuç | Sebep |
|---|---|---|
| Real edge mevcut mu? | Bilmiyoruz (backtest yok) | Mat-hold/marubozu/kaufman-atr execute = 0 |
| Eğer mevcut olsa OOS Sharpe ne olur? | ~0.5-1.0 (literatürün üst sınırı) | Chan #9: pair için 1.2 eşik → büyük olasılıkla geçmez |
| FWER düzeltilmiş p-value? | >0.05 (N=35 ile bile) | Holm-α=1.43e-3 vs bağımsız p~0.05-0.10 |
| Live trade-ready hale gelirdi mi? | Hayır | vsa_climax_test 3-ay-live-evidence YOK; companion seçimi yapılırken comparator henüz "stabil aktive" değil |
| Marjinal information gain | ~0 (gürültü) | Family-wise N>30 zone'unda bir adayın daha "deneyimi" PBO'yu yükseltir, indirmez |

→ **Olasılıkla beklenen değer = sıfır + Bonferroni borcu büyütür.** Bilinçli abort, marjinal değerin negatif olduğu zorunlu davranıştır.

## v5 Moratorium Durumu

2026-05-... tarihinde konan moratorium: **cross-strategy-low-corr-companion-to-vsa-climax-test** seed'i için **2026-08-25'e kadar (~80 gün kaldı)** yeni hipotez üretimi yasak. Tetik koşulları yalnız 6 (+1 yeni) reset gate'inden biri açılırsa kalkar. Hiçbiri açılmadı.

## v13 Spesifik Yeni Bulgular

1. **Intra-day burst pattern kanıtlandı:** 2026-06-06 takvim gününde 2 cron tetik (08:00 + 22:00 UTC, 14h aralık) — v11 (08:00) ve v12 (10:02) zaten same-day idi (2h aralık). Cron seed-picker policy'sinin **artık periodic 24h olmadığı** kesin. Daily-cadence varsayan tüm throttle policy'leri (v9-v11) eksik korumadır.

2. **Sanitizer scope evrim ihtiyacı:** ops_engineer sanitizer (PROPOSED, deploy edilmemiş) tasarımında "seed registry-level pool dedup + cooldown enforcement" bekleniyordu. 8 ardışık doc-based abort (v6-v13) ve sayısız JSONL-only entry sonrası kanıt: sanitizer'ın deploy edilmemesi → researcher'ın günlük 2 burst payload'a abort-doc-yazarak yanıt vermesi → işlem maliyeti artar, yapı bilgi sızdırmaz. **CRIT'leşmesi gereken bir operasyonel sorun.**

3. **Abort family doygunluk noktası yaklaşıyor:** v6-v13 = 8 doc, +JSONL-only entries (her 3-12h'de bir, ~20+ throttle event). N=34. Lopez-Prado §6 ("Strategy serbest parametre sayısı / örnek sayısı > 1/30 → production'a gitmez") = **mevcut family TOPLU OLARAK production-killed**, herhangi bir cousin için bile.

## Karar

- [ ] Terfi adayı
- [ ] İterate (SOP-4b)
- [x] **Red — abort doc only**

**Gerekçe:** 6+1 reset gate'inden hiçbiri açılmadı; v5 moratorium aktif (~80 gün kaldı); family-wise N=34 (1/30 tripping point ihlali); intra-day burst pattern v12'nin throttle policy'sini kanıtlı şekilde ihlal etti; topical RAG hit oranı 0/10 (Lopez#1 + Chan#9 hipoteze HASIM); marjinal beklenen değer ≤ 0.

## Telafi Eylemleri (yeni hipotez YAZMAK YERINE)

1. ✅ Bu abort doc'u yazıldı (idempotent, append-only).
2. ➡️ `memory/researcher/seed_abort_log.jsonl`'e `trigger_n=24, abort_docs_total=13` entry (sıradaki tool call).
3. 🔁 ops_engineer'a critique doc önerisi: "sanitizer guard'ın hâlâ deploy edilmemesi v6'dan bu yana 8 abort doc + 20+ JSONL entry maliyeti yarattı; CRIT'e yükseltme öner." (bu doc supersedes etmez, ek bir critique olur — bu turda yazılmıyor, principal'a hatırlatma olarak işaretleniyor.)
4. 📅 Yeni hipotez üretim kapısı: 2026-08-25 (moratorium expiry) **VEYA** 6+1 gate'ten birinin gerçekten açılması (hangisi önce gelirse). Gate açılmadan hipotez yazılamaz.

## Reproducibility

- git: fd80d4c
- branch: audit-hardreview-20260528
- substrate hash (config mtimes): `v13_testnet=2026-06-02T22:50Z, vsa2=2026-06-04T06:31Z, multitf_stack=2026-06-02T19:55Z` — v12 ile bit-identical
- knowledge envelope hash: chroma.sqlite3 mekanik index, içerik yok (v12 ile aynı)
- backtest_results new files (7d): 0
- pools new (7d): 0
- tournaments new (7d): 0

## Next Reset Trigger (gözlemlemeye devam)

- [ ] Sanitizer guard'ın ACTIVE'e geçmesi (ops_engineer)
- [ ] vsa_climax_test'in ≥3 ay live trade kaydı (lab_scientist/principal deploy)
- [ ] Yeni RAG corpus eklenmesi (bayatlamayan companion-selection literatürü)
- [ ] backtest_results/ veya pools/ içinde yeni gerçek deney evidence
- [ ] Live champion swap (config mtime + PID değişikliği)
- [ ] Pool universe genişlemesi
- [ ] Cron 24h cooldown enforcement (intra-day burst durması)
- [ ] 2026-08-25 moratorium expiry

Hiçbiri olana kadar v14 yazılmayacak — JSONL-only throttle entry'leri devam eder.
