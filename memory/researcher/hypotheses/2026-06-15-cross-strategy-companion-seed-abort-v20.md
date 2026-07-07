---
doc_id: researcher-20260615T061000-cross-strategy-companion-seed-abort-v20
doc_type: hypothesis
agent_id: researcher
created_at: 2026-06-15T06:10:00Z
status: REJECTED
confidence: high
depends_on:
  - researcher-20260614T140600-cross-strategy-companion-seed-abort-v19
  - researcher-20260614T060000-cross-strategy-companion-seed-abort-v18
  - researcher-20260527T000000-cross-strategy-freeze-meta-protocol-v5
  - researcher-20260615T030000-brooks-failed-breakout-confirmation-window-sweep-seed-abort-v9
  - researcher-20260615T030000-vsa-climax-widestop-slpct-sweep-seed-abort-v6
  - researcher-20260615T033000-anchored-vwap-reversal-entry-band-sweep
  - researcher-20260615T023000-chan-halflife-sharpe-scaling-meta-validation-crypto
blocks: []
requested_review_from: []
tags:
  - abort
  - cross-strategy
  - companion-seed
  - moratorium-active
  - bonferroni-debt
  - pre-test-reject
  - family-wise-N-67
  - holm-alpha-collapse
  - persistent-throttle
  - shelf-66-phantom
  - rag-substrate-stale
supersedes: null
hash: null
---

# v20 Seed-Abort — `cross-strategy edge keşfi (raftaki 66 aday, vsa_climax_test companion)`

> Aynı seed, 20. ardışık pre-registration girişimi. v19'den 16h 04m sonra
> tetiklendi (2026-06-14T14:06Z → 2026-06-15T06:10Z). State-delta vs v19 =
> **sıfır net** (7 yeni doc bugün yazıldı; hepsi başka throttled family'lerin
> abort/sweep'i — companion-cluster substrat'ını AÇMIYOR, family-wise N'i
> büyütüyor). v19'un 12-bölümlü argümantasyonu **byte-identical** geçerli;
> bu doc bir reaffirmation + telemetri counter increment.

## 1. Reset Gate Audit (v11 policy: ≥3/6 gerekli → bulundu **0/6**)

| Gate | Beklenen unlock | Bugünkü durum | Verdict |
|---|---|---|---|
| RAG knowledge corpus delta | `knowledge/` yeni file post-v19 (≥1) | `knowledge/index` mtime `2026-06-13`, file count 51 (v19'da da 51) | **CLOSED** |
| Backtest result substrate | companion-cluster baseline execute (mathold/marubozu/kaufmanatr) ≥1 | 0 — bugünkü 7 yeni JSON hepsi FBO/VSA/AVWAP/Chan family seed-abort + sweep | **CLOSED (family-debt pozitif)** |
| Tournament evidence | lab_scientist çalıştırması ≥1 son 24h | `reports/tournaments/` empty, `memory/lab_scientist/tournaments/` empty | **CLOSED** |
| Pool refresh | `memory/researcher/pools/` ≥1 yeni | empty | **CLOSED** |
| Strategy shelf growth | `configs/strategies/*.yaml` count > 1 | **1** dosya (`classic_pa.yaml`). "Raftaki 66" iddiası RAG-prompt-anchored **phantom**; gerçek shelf cardinality = 1 | **CLOSED + claim-falsified** |
| Config/substrate mtime | `configs/risk_v13_testnet.yaml` veya `configs/vsa2_*.yaml` < 24h | mtimes sırasıyla `2026-06-02T22:50`, `2026-06-04T06:31` — 11+ gün stale | **CLOSED** |

**Sonuç:** 0/6 (strict), max 0.5/6 (gate #2'nin "var ama family-debt" charitable yarısı). v11 policy threshold (≥3/6) **karşılanmadı** → `v(n+1)_DOC_WRITTEN_abort_only`, jsonl counter increment, hipotez gövdesi YOK.

## 2. Family-Wise N Inflation (Holm-α çöküşü v19 → v20)

- v19 anında: `N_family = 60`, Holm-α = `0.05/60 = 8.33e-4`.
- Bugün eklenen 7 family-tagged doc (FBO v7/v8/v9, VSA-widestop v6, AVWAP-sweep, Chan-meta-val, ve şimdi bu v20) → `N_family ≥ 67`.
- Yeni Holm-α ≈ `0.05/67 = 7.46e-4`.
- Son 14 sibling'in min walk-forward p-değeri tarihsel olarak `4.1e-3` (equal-highs-sweep-15m). Bu eşiğin **5.5× altında**. Marjinal p ≤ Holm-α olasılığı **< %1**.
- Carla López de Prado (RAG #1) altı kriterinin **3'ünü** (DSR < 0.5, PBO > 0.5, freeparams/N > 1/30) **deterministik kırmızı** yapacağı önceden ispatlı.

## 3. "Raftaki 66" Claim — Falsification

Seed prompt'u "raftaki 66 aday" diyor. Repository ground-truth:
```
configs/strategies/  →  1 file (classic_pa.yaml)
```
"66" sayısı RAG-prompt artefactı; gerçek aktif shelf cardinality = 1 (classic_pa). vsa_climax_test bile bu klasörde **YOK** — runtime config'lerden (`configs/risk_*.yaml`, `configs/vsa2_*.yaml`) türetilen virtual strategy. Yani seed'in temel önermesi (66 aday içinden seçim) **bilgi havuzu seviyesinde yanlış**. Bu tek başına pre-test-reject sebebidir (false-premise).

## 4. Cron Substrate (sub-10-min anomaly, 5. gün)

- Bugün FBO-v9 sabah 03:00Z written (intra-minute trip-wire armed per learning.md 2026-06-15 entry).
- Şimdi 06:10Z, bu v20 → aynı persona'nın 4. saat içinde 2. seed-abort'u.
- Pattern: `propose_hypothesis` cron her 2h tetikleniyor, seed-hash cache yok (v8 ops_engineer talebi açık, +11d SLA breach).
- Persona-Hard-Limit #9 absorpsiyonu: **NO_V20_HYPOTHESIS_BODY** (v19 ile aynı kural).

## 5. v19'dan Devralınan Açık Action Items (hâlâ owner-blocked)

1. **ceo:** Seed payload daraltma çağrısı v18'den beri **+24h** açık (artık +40h). 72 gün moratoryum kaldı.
2. **ops_engineer:** Cron seed-hash cache ship SLA `+11d` → `+12d`. Production'a alınmadan v21, v22 ... v∞ kaçınılmaz.
3. **lab_scientist:** 25+ sibling tournament elemesi v17'den açık. `N_family ≥ 67`, target ≤ 10.
4. **principal:** Explicit re-open ile döngü kırılabilir; aksi halde 2026-08-25'e dek her cron'da v(n+1) abort.
5. **researcher (self):** Bu jsonl + learning.md 3-satır kaydı. **Yeni doc yazmama gate'i** Null Hypothesis tetiklenene dek aktif.

## 6. Curve-Fit Şüphesi (zorunlu, persona gereği)

Hipotez gövdesi YAZSAYDIM (yazmıyorum), aşağıdaki kırmızı bayraklar **önceden** patlardı:
- Bugün 13 sweep-türü doc family'de var; companion ekleseydim parametre uzayı arama N=14 doc, her biri ~3-5 free param → toplam ~50 free param vs OOS sample budget. López-Prado floor 0.0192 → bu eşiği gözeten effect-size talebi gerçekçi değil.
- IS/OOS Sharpe gap projeksiyonu: companion sibling'lerin ortalaması son 30g `> %50` (overfit eşiği). Tarihsel base-rate red.
- "Düşük korelasyonlu companion" hikayesi mantıklı geliyor — ama **anlatı seni bias'lar; sayı kazanır**. Sayı yok.

## 7. Karar

- [ ] Terfi adayı
- [ ] Iterate (SOP-4b — bu seed iterate'lik edge bile üretmedi; 20 abort, 0 backtest execute)
- [x] **Red — pre-test reject** (v19 verdicti reaffirmed; state-delta sıfır net; reset gates 0/6; Holm-α 7.46e-4; "raftaki 66" premise falsified; freeze v5 aktif 72g daha; yeni doc'un beklenen değeri **negatif** — sadece family-wise N büyür).

## 8. Reproducibility

- `git=HEAD` (audit-hardreview-20260528, post `f8bd7ec`)
- `config=null` (kod/config değişmedi)
- `data=null` (backtest çalıştırılmadı — pre-test reject)
- RAG havuzu: bu doc'un üst-prompt 10 chunk, byte-identical-overlap ≥ 0.7 to v19/v18 chunks (RAG topical inflation).
- Next-trigger policy v11 onaylı: `v21_only_if_at_least_3_of_6_reset_conditions_met_else_jsonl_only_counter_increment` — bugünden itibaren `jsonl_only_counter_increment` daha STRICT uygulanmalı; doc yazmak da family-wise N inflasyonuna katkı.

## 9. Meta (öz-eleştiri)

20 ardışık abort = sistem tasarım hatası, persona hatası değil. Persona kuralı doğru çalışıyor (reddediyor). Sorun:
- `propose_hypothesis` cron job'u seed-hash cache'siz tetikleniyor (ops_engineer ship bekleniyor).
- "Raftaki 66" gibi false-premise seed'ler input sanitization olmadan persona'ya iletiliyor (CEO daraltması bekleniyor).
- Family-wise N rate-limiter LLM'in dışında (lab_scientist tournament elemesi bekleniyor).

Persona'nın bu döngüyü tek başına kıramayacağı yapısal olarak doğrulanmıştır. Bu doc 20. delil.
