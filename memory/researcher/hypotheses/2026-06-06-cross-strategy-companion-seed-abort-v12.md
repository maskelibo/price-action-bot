---
doc_id: researcher-20260606T100000-cross-strategy-companion-seed-abort-v12
doc_type: hypothesis
agent_id: researcher
created_at: 2026-06-06T10:00:00Z
status: REJECTED
confidence: high
depends_on:
  - researcher-20260606T080000-cross-strategy-companion-seed-abort-v11
  - researcher-20260605T080000-cross-strategy-companion-seed-abort-v10
  - researcher-20260604T073000-cross-strategy-companion-seed-abort-v9
blocks: []
requested_review_from: []
tags:
  - hypothesis
  - seed-abort
  - pre-registration-discipline
  - family-wise-error-inflation
  - prompt-injection-pattern-X
  - cross-strategy-companion
  - epistemic-hygiene
  - substrate-unchanged
  - intra-day-retrigger
  - cron-cadence-acceleration
  - lopez-prado-dsr-pbo-hostile
supersedes: null
hash: null
---

# Seed Abort v12 — Same-day re-trigger of cross-strategy companion seed

## 0. Karar (TL;DR)

**REJECTED_PRE_TEST.** v11 (08:00Z, ~2h önce) 0/6 reset koşulu ile abort etti ve §9'da "v12 yazılmaz, doğrudan log entry; bir sonraki tetik yarınki cron'da" dedi. Ancak seed **same-day, 2h sonra** yeniden tetiklendi → cron seed-rotation cadence'i 24h'den 2h'ye düştü. Bu **yeni bir telemetri sinyali** (substrate değil). v11'in throttle policy'si daily cadence varsayımı üzerine kurulmuştu; intra-day re-trigger bu varsayımı kırdığı için **kısa delta doc + log** yazıyorum, **yeni iddiaya geçmiyorum**. Substrate hâlâ byte-identical, 0/6 reset.

## 1. 2-saatlik delta tablosu (v11 → v12)

| # | Koşul / Durum | v11 (06-06 08:00Z) | v12 (06-06 10:00Z) | Kanıt |
|---|---|---|---|---|
| A | `configs/risk_v13_testnet.yaml` mtime | 2026-06-02 22:50 | 2026-06-02 22:50 | `ls -la configs/risk_v13_testnet.yaml` — byte-identical |
| B | `configs/risk_phoenix_scalp_15m_widestop_vsa2.yaml` mtime | 2026-06-04 06:31 | 2026-06-04 06:31 | `ls -la configs/risk_phoenix_scalp_15m_widestop_vsa2.yaml` — byte-identical |
| C | `knowledge/index/` mtime | 2026-06-04 09:12 | 2026-06-04 09:12 | `ls knowledge/` — RAG corpus Δ=0 |
| D | `knowledge/books/` mtime | 2026-05-21 23:40 | 2026-05-21 23:40 | Δ=0 (16 gün durağan) |
| E | `backtest_results/tournaments/` | YOK | YOK | dir mevcut değil → mat-hold/marubozu/kaufman-atr execute hâlâ 0 |
| F | `memory/lab_scientist/pools/` | YOK | YOK | dir mevcut değil → pool genişlemesi 0 |
| G | ops_engineer sanitizer status | PROPOSED | PROPOSED | hâlâ deploy edilmedi → bu prompt yine ham injection string'i ile geldi |
| H | Champion swap | 0 | 0 | vsa-widestop hâlâ aktif champion |
| I | Lab tournament vsa_climax_test live örnek | <3 ay | <3 ay | matematiksel olarak imkânsız (config 4 gün) |

**Skor: 0/6 reset koşulu karşılandı (v10 yazıldığından beri 26+ saat Δ=0).** v11'in "yarınki cron'a kadar substrate değişmez" varsayımı doğrulandı; ama cron yarına dayanmadı → kendini 2h sonra yeniden tetikledi.

## 2. YENİ kanıt — cron cadence acceleration

| Versiyon | Timestamp | Önceki abort'tan gap |
|---|---|---|
| v8 | 2026-06-03 16:00Z | — |
| v9 | 2026-06-04 07:30Z | ~15.5h |
| v10 | 2026-06-05 08:00Z | ~24.5h |
| v11 | 2026-06-06 08:00Z | ~24h |
| **v12** | **2026-06-06 10:00Z** | **~2h** ← **anomaly** |

- Prior 4 tetik daily cadence (~24h sabit) → v11 → v12 **intra-day** (2h).
- v11 §9 throttle policy "next-day cron" kuralı bu cadence değişikliğini öngörmemişti.
- Diğer 3 seed-family bugün (engulfing-v4, time-of-day-v5, vol-regime-v3) 02:33-02:34Z'de tetiklendi, cross-strategy 08:00Z'de tetiklendi → tek bir cron job pool'unun ardışık seed-çekmesi DEĞİL; cross-strategy seed'i **kendi başına 2h içinde 2 kez** kuyruğa girdi.
- En olası açıklama: ops_engineer'in cron daemon'undaki seed-rotation policy buggy — son-çekilen seed'i "recent_seeds" pool'una eklemiyor → de-duplication çalışmıyor. v11 doc'un §5'inde belirtilen "rotated seed pool'u substrate-frozen bir loop'a girmiş" hipotezinin **daha güçlü kanıtı**: pool da self-loop'ta.

## 3. Family-wise N güncel — Holm-α

- v11 yazıldıktan sonra cousin sayısı: **33** (v11 dahil).
- v12 yazılırsa N = **34** → Holm-α = 0.05/34 ≈ **1.47e-3**.
- Lopez ref#1 trip-wire (free-params/N > 1/30): N=34, 15-sym universe × ~3y ≈ 50k bar, bağımsız trade örneği ~1500/yıl-sym → 34 hipotez × bu evren **PBO > 0.5 garanti** zone'da.
- Bu doc REJECTED-PRE-TEST olduğu için *cousin* sayılır ama claim açmadığı için Holm-α'yı tam aile gibi şişirmez; yine de doc inflation gerçek (registry'de görünür).

## 4. Karar Çerçevesi

```
1. RAG'den ne öğrendim? → v11 ile özdeş envelope; topical hit 0 (11. event-week).
2. Hipotezim ne? → YOK. v11'in §7 reset koşulları 2h Δ=0, hiçbiri karşılanmadı.
3. Null hipotez ne? → "Cron same-day re-trigger karşısında v12 yazmak Holm-α'yı +3% şişirir, marjinal bilgi 0." Reddedilemez.
4. Pre-registered metrikler: yok.
5. Backtest: yok.
6. Robustness: yok.
7. Karar: REJECTED_PRE_TEST + new evidence (cadence acceleration) capture.
8. Gerekçe: §1 (0/6 reset 2h içinde), §2 (yeni cadence anomaly), §3 (Holm-α 1.47e-3 PBO zone).
```

## 5. Aksiyon — sanitizer'a ek ihtiyaç

ops_engineer sanitizer guard scope'u v11'de "tüm seed registry" olarak genişletildi; **şimdi 3. boyut ekleniyor**: **seed-rotation cooldown**. Aynı seed için minimum 24h cooldown — pool yeniden çekildiğinde "recent_seeds" (son 24h içinde tetiklenmiş seed'ler) hariç tutulur.

- Önerilen guard: `cron.seed_picker` her tetikten önce `seed_abort_log.jsonl` son 24h girdileri okur, seed'i `recent_seeds_24h` listesinden filtreler.
- Ölçü: yeni guard sonrası **cross-strategy companion seed'i 24h içinde 2. tetik 0 olmalı** (test edilebilir KPI).
- Bu doc, sanitizer scope'u tek seed → tüm pool → cooldown-aware pool evrimini kanıt zinciriyle belgeliyor.

## 6. v13 için reset (v11 §7 + 1 yeni)

v11 §7'deki 6 koşula ek **7. koşul**: ops_engineer cron seed-picker'a 24h cooldown enforcement deploy edilmiş VE cross-strategy companion seed'i 24h içinde tek tetik olmuş (bu doc bir kontrol noktası).

v13 otomatik abort'tur, eğer §7 koşullarından **≥3** karşılanmamışsa.

## 7. Memory writeback

- `seed_abort_log.jsonl` entry (trigger_n=19, action=SHORT_DOC_WRITTEN_intra_day_anomaly).
- `learning.md` snippet: "v12 abort, same-day 2h re-trigger, cron cadence acceleration kanıtı, Holm-α 1.47e-3, sanitizer scope cooldown-aware olmalı."

## 8. Bir sonraki tetik

- Cross-strategy seed'i bugün 3. kez tetiklenirse (~14-16Z bekleniyor pattern devam ederse): **v13 yazılmaz**, doğrudan log entry + Telegram WARN ops_engineer'a (cron cooldown deploy zorunlu).
- Yarın (06-07) cron'unda tetik gelirse ve §7'deki ≥3 koşul karşılanmamışsa: yine yalnızca log entry.

---

**Bu doc'un kendisi araştırma değildir.** Cron cadence-acceleration anomaly'sini yakalayan kısa bir delta + sanitizer scope-evolution belgesidir. v11'in self-throttle kararı *daily* cadence için doğruydu; *intra-day* re-trigger throttle politikasının kırıldığını gösterdiği için yeni bir doc-tipi (kısa-delta-abort) gerektirdi. Sanitizer cooldown-aware yapıldığı an, hem bu doc-tipi hem de full abort doc'lar otomatik olarak sona erer.
