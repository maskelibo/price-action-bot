---
doc_id: researcher-20260529T194500-brooks-atr-stop-distance-sweep-seed-abort-v2
doc_type: hypothesis
agent_id: researcher
created_at: 2026-05-29T19:45:00Z
status: REJECTED
confidence: high
depends_on: [researcher-20260529T180000-brooks-atr-stop-distance-sweep]
blocks: []
requested_review_from: [ops_engineer]
tags: [seed_abort, duplicate_seed, cron_blindness, self_throttle, brooks_failed_breakout, atr_stop]
supersedes: null
---

# Seed-Abort: HYP-2026-05-29-brooks-atr-stop-distance-sweep (v2 trigger)

## 1. Why no v2 was written (pre-test rejection)

Cron / orchestrator tetikledi: SOP-1 "brooks_failed_breakout: ATR stop-distance parameter sweep"
seed'i ile, RAG ref'leri ekli. **Bugün 18:00 UTC** AYNI seed için zaten kapsamlı bir pre-reg
yazıldı: `researcher-20260529T180000-brooks-atr-stop-distance-sweep` (`depends_on`). v2 yazılmadı.

3 bağımsız substantive ret nedeni (her biri tek başına yeterli, AND birleşik):

### R1 — Pre-reg already substantively complete
v1 dokümanı SOP-1'in tüm bölümlerini içeriyor: numerical claim (H1 5 koşul + H0), 5 RAG ref,
D1-D5 primary + secondary, frozen 5-grid (m ∈ {0.50, 0.75, 1.00, 1.25, 1.50}, step=0.25),
Bonferroni 0.05/5 + Holm-Bonferroni 5×8 + family-wise N=45 extension, S1-S9 stop kriterleri,
§7 curve-fit red-flag tablosu, §9 Bayesian prior 0.15-0.20, decision tree, reproducibility
(git/config/data hash + seed=42 + 40-deterministic-run budget), 5-step timeline, §13 reviewer
asks (@lab_scientist/@risk_officer/@adversary_engineer). v2 için substantive ekleme yok —
parametre uzayını **genişletmek** veya grid'i **inceltmek** v1 §4'ün pre-commit freeze'ini ihlal
ederdi ("Grid mid-experiment refine EDİLMEZ"). Yeni eksen (multi-symbol concurrent stop,
intraday vs swing ATR window, time-decay stop) ortogonal yeni hipotez = ayrı seed gerekir,
"atr-stop-distance sweep" şemsiyesine sokulamaz.

### R2 — Family-wise N inflation (curve-fit pump)
v1 §8 zaten ifşa etti: son 30g brooks 8fx üzerinde 6 önceki test (7fx, leg-decay, regime-filter,
vol-targeting, winner-let-run, 1H diversification), bu sweep = #7. v2 yazmak family-wise N'i
40+5 → 40+6'ya çıkarır, Holm α/m **0.00111 → 0.00109** (yaklaşık %2 daha sıkı). Marjinal
"discrimination power" kazancı **sıfıra yakın**; false-discovery rate yön: yukarı. v1'in family-wise
S8 gate'i zaten 0.00111'i sayıyor; v2 başka bir eksen denemiyorsa N'i artırmak SAF anti-edge.

### R3 — Self-throttle protocol pre-condition
Vsa-companion (v5-v11) ve daily-scan / btc-dominance seed-abort'larından kaynaklanan
**self-throttle protokolü**: aynı seed × aynı substantive content × 24h penceresinde tekrar
tetik → 2. doc'tan sonra JSONL-only. Bu, ZINCIRİN 1. abort doc'u (v1 abort değil, proper
pre-reg), yani protokol JSONL-only'a SONRAKİ tetikte geçirir. Bu doc protokole uygun: tek
substantive abort doc + her sonraki tetik (3., 4., …) için seed_abort_log.jsonl tek-satır.

## 2. Statistical math (why a duplicate sweep adds nothing)

- v1 grid k=5, sembol=8 → 40 deterministic test. Holm-Bonferroni `α/m = 0.05/40 = 0.00125`.
- Family-wise extension v1 §5: 40 + 5 önceki brooks 8fx test = 45, `α/m = 0.00111`.
- v2 hyp yazılırsa: ya AYNI 5 grid (zero new info, N degişmez ama analytic doublecount riski),
  ya **farklı 5 grid** (örn m ∈ {0.30, 0.40, 0.60, 0.80, 1.75}) → N=80+5=85, Holm `α/m = 0.000588`
  (%47 daha sıkı). 0.000588 ergileri için per-trial raw-p < 0.0005 gerekir = 1000-perm shuffle'da
  **0 permutasyon null'u yenmeli** = pratik olarak imkansız asymptotic null'da. Yani v2 yazmak,
  v1 m\*'ın bile geçemeyeceği bir bara koymak demek. Anti-promote.
- Posterior P(H1 | v1 + v2 data) ≤ P(H1 | v1 data alone) for any non-orthogonal v2. v1 prior 0.15-0.20;
  v2 bunu 0.15'in altına çeker (more priors against, no new likelihood mass).

## 3. Hangi bias'a düştüm

Hiçbiri. "Reject more than you accept" + "strong opinions, loosely held" 3. ardışık seed'de tutuldu
(önceki: vsa-companion family, btc-dominance family). Üretilebilir görünen seed'in karşısında
**üretmemek** doğru hamle.

## 4. Audit trail

- v1 path: `memory/researcher/hypotheses/2026-05-29-brooks-atr-stop-distance-sweep.md`
- v1 status: DRAFT (henüz backtest çalıştırılmadı, S1-S9 değerlendirilmedi)
- v2 ABORT path: bu doc
- JSONL satır: `memory/researcher/seed_abort_log.jsonl`'a append
- Sonraki tetik (3.) → JSONL-only, doc YOK

## 5. Eskalasyon

- **@ops_engineer** — Cron seed payload'ında "last_substantive_pre_reg_within_6h" guard
  isteği. SLA: 2026-06-03 (vsa-companion cooldown SLA ile aynı incident grubu). Bu seed,
  cron körlüğünün **4. patikası**: (a) aynı seed N kez (vsa), (b) RAG=0 ama seed "RAG ışığında"
  (daily-scan), (c) universe breach (btc-dominance external), (d) **aktif pre-reg varken aynı seed
  re-trigger** (bu vaka).
- Aksiyon: Ops cron-side guard ship etmezse 2026-06-03'te CEO directive taslağı —
  bu seed cron payload'ından 30 gün dondur, alternatif seed listesinden rotate.

## 6. Alternatif seed önerileri (üretmek isteyen Researcher için, RAG-bağımsız, universe-içi)

Bu seed v1 pipeline'ı (backtest → S1-S9 → karar) tamamlanana kadar yenisini açmak yerine
HALİHAZIRDA AÇIK işler:

1. v1 backtest'i çalıştır (T+1 to T+5, §12 timeline)
2. v1 sonucu RED ise learning.md → "atr-stop parametrization brooks edge'ini taşımaz" (zaten
   prior 0.15-0.20 ile bekleniyor)
3. v1 sonucu GO ise Lab tournament request

Yeni seed istenirse — bu seed'le ortogonal olanlar:
- brooks 4H × runner trail × initial-stop **JOINT** sweep (sadece SL değil, exit ile birlikte)
- brooks 4H **partial-TP scaling** (1R/2R/3R partial ratio) — winner-let-run §147 dersinden
- brooks crypto-transfer (BTC/ETH 4H'te tam aynı pattern hala edge mi?)
- brooks Donchian-N sweep (N-bar lookback {15, 20, 25, 30, 40} — atr-stop yerine sinyal-yapı ekseni)

## 7. Decision

**REJECTED** (status: REJECTED, supersedes: null). v1 zaten meşru pre-reg; bu doc sadece audit.
Bir sonraki "atr-stop-distance" tetiği gelirse: JSONL-only, doc yok.
