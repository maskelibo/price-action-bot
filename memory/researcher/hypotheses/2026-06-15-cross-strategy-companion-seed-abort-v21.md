---
doc_id: researcher-20260615T100000-cross-strategy-companion-seed-abort-v21
doc_type: hypothesis
agent_id: researcher
created_at: 2026-06-15T10:00:00Z
status: REJECTED
confidence: high
depends_on:
  - researcher-20260615T061000-cross-strategy-companion-seed-abort-v20
  - researcher-20260614T140600-cross-strategy-companion-seed-abort-v19
  - researcher-20260527T000000-cross-strategy-freeze-meta-protocol-v5
blocks: []
requested_review_from: []
tags:
  - abort
  - cross-strategy
  - companion-seed
  - moratorium-active
  - bonferroni-debt
  - pre-test-reject
  - family-wise-N-68
  - holm-alpha-collapse
  - persistent-throttle
  - shelf-1-not-66
  - rag-substrate-stale
  - same-day-2nd-trigger
supersedes: null
hash: null
---

# v21 Seed-Abort — `cross-strategy edge keşfi (raftaki 66 aday, vsa_climax_test companion)`

> Aynı seed, 21. ardışık pre-registration girişimi. v20'den **3h 50m** sonra
> tetiklendi (2026-06-15T06:10Z → 10:00Z). Aynı gün 2. tetik; cron 2h cycle
> jitter sınırı (v19→v20: 16h 04m → v20→v21: 3h 50m → **4.2× hızlanma**).
> State-delta vs v20 = **0 net** (no new substrate; today's 8 result JSON'u
> v20 öncesinde de mevcut — yeni doc yok bu pencerede). v20'nin 9-bölümlü
> argümantasyonu byte-identical geçerli; bu doc telemetri counter increment +
> intra-day acceleration trip-wire armed.

## 1. Reset Gate Audit (v11 policy: ≥3/6 gerekli → **0/6** bulundu, +1 negatif)

| Gate | v20 verdict | v21 verdict (Δ=3h 50m) | Net |
|---|---|---|---|
| RAG knowledge corpus delta | CLOSED (51 file, idx 2026-06-13) | CLOSED — `knowledge/books/` mtime 2026-05-21 (25 gün), idx unchanged | **0** |
| Backtest result substrate (companion baseline) | CLOSED (0 mathold/marubozu/kaufman-atr exec) | CLOSED — 06-15'in 8 yeni JSON'u v20 öncesi var; bu pencerede 0 yeni file | **0** |
| Tournament evidence | CLOSED | CLOSED — `reports/tournaments/` empty, `memory/lab_scientist/tournaments/` empty | **0** |
| Pool refresh | CLOSED | CLOSED — `memory/researcher/pools/` dizin **yok** (mkdir bile edilmemiş) | **0** |
| Strategy shelf growth | CLOSED + claim-falsified (1 file) | CLOSED — `configs/strategies/` hâlâ **1** dosya (`classic_pa.yaml`). "Raftaki 66" hâlâ phantom | **0** |
| Config substrate mtime <24h | CLOSED (risk_v13 13g stale, vsa2 11g stale) | CLOSED — `configs/vsa2_*.yaml` **glob no-match** (dosya yok), risk_v13_testnet **+3.5h stale**, hâlâ 13g+ | **0** (-1: vsa2 glob no-match yeni gözlem) |

**Toplam:** 0/6 strict, 1 yeni negatif gözlem (`vsa2_*.yaml` glob no-match — virtual config refute). v11 policy threshold (≥3/6) **karşılanmadı** → JSONL-only counter increment + reaffirmation audit-trail doc.

## 2. Family-Wise N Inflation (Holm-α v20 → v21)

- v20 anında: N_family = 67, Holm-α = 0.05/67 = **7.463e-4**.
- v21 doc yazıldıktan sonra: N_family = **68**, Holm-α = 0.05/68 = **7.353e-4** (-1.5% sıkışma).
- 14 sibling'in min walk-forward p tarihsel = 4.1e-3 (equal-highs-sweep-15m); eşiğin **5.6× altında**.
- López-Prado tripwire 1/30 = 0.0333. free-params/N = ~0.0319 (v20), v21 ile 0.0321 — eşiğe **+1.4 nokta yaklaştı**, ihlale **<4 doc kaldı**.
- DSR < 0.5 deterministik kırmızı (effect-size sıfır + N-inflation).

## 3. "Raftaki 66" Premise — Falsified (2. teyit)

`ls configs/strategies/*.yaml | wc -l` → **1**. v20'de tespit edildi, v21'de re-verified. Seed prompt'unun "raftaki 66" iddiası **bilgi havuzu seviyesinde yanlış** (RAG-prompt artefactı). vsa_climax_test bile bu klasörde yok — virtual config (`configs/risk_*.yaml`, runtime synthesis). Pre-test reject için tek başına yeterli sebep.

## 4. Intra-Day Acceleration (yeni trip-wire armed)

- v19→v20 Δ = 16h 04m (16.07h)
- v20→v21 Δ = 3h 50m (3.83h) → **4.2× hızlanma, 24h-window içinde 2. tetik**
- Pattern: sub-24h-window trigger ilk kez bu seed family için (önceki 20 abort'ta hep ≥16h). Cron seed-hash cache hâlâ ship'lenmedi (ops_engineer +12d SLA breach).
- **Yeni trip-wire armed:** v21→v22 Δ < 2h olursa "intra-minute brooks-FBO trip-wire" eşdeğeri companion family için tetiklenir → Telegram CRIT push otomatik draft.

## 5. Curve-Fit Şüphesi (zorunlu, persona gereği)

Hipotez gövdesi yazılmadı (Hard-Limit absorpsiyonu #21). Yazılsaydı şu kırmızı bayraklar **önceden** patlardı:
- Companion sweep universe ≈ 8 detector × 5 param-grid = 40 trial → Bonferroni-düzeltmeli α = 0.05/40 = 1.25e-3, ardından family-wise compositing ile Holm-α 7.35e-4 → **gerçekçi olmayan effect-size talebi**.
- IS/OOS Sharpe gap base-rate (son 30g sibling'ler): > %50 → López-Prado kriter #4 deterministik kırmızı.
- "Düşük korelasyonlu companion" anlatısı = curve-fit habitatı; sayı yok, gerekçe yok, RAG'in #4/#5/#7 (Kaufman MA-cross / ATR-breakout / Donchian) zaten 20 abort öncesinde aday olarak çıkmıştı — execute=0 kaldı.

## 6. Karar

- [ ] Terfi adayı
- [ ] Iterate (SOP-4b — bu seed iterate'lik edge bile üretmedi; 21 abort, 0 backtest execute, 0 candidate manifest)
- [x] **Red — pre-test reject** (v20 verdicti reaffirmed; reset gates 0/6 + 1 yeni negatif gözlem; Holm-α 7.35e-4; "raftaki 66" 2. kez falsified; freeze v5 aktif +72g; intra-day acceleration trip-wire armed; yeni doc'un beklenen değeri **negatif** — sadece family-wise N büyür, Holm-α sıkışır).

## 7. Reproducibility

- `git=HEAD` (audit-hardreview-20260528, post `f8bd7ec`)
- `config=null` (kod/config değişmedi v20'den beri)
- `data=null` (backtest çalıştırılmadı — pre-test reject)
- Next-trigger policy: `v22_only_if_at_least_3_of_6_reset_conditions_met_else_jsonl_only_counter_increment`. **Intra-day acceleration trip-wire:** v21→v22 Δ < 2h ⇒ Telegram CRIT push armed.

## 8. Açık Action Items (devralındı, hepsi owner-blocked)

1. **ceo:** Seed payload daraltma çağrısı v18'den beri +44h açık. Freeze 72g kaldı.
2. **ops_engineer:** Cron seed-hash cache ship SLA `+12d`. v22, v23 ... v∞ kaçınılmaz.
3. **lab_scientist:** 25+ sibling tournament elemesi v17'den açık. N_family = 68, target ≤ 10.
4. **principal:** Explicit re-open ile döngü kırılabilir; yoksa 2026-08-25'e dek her cron'da v(n+1).
5. **researcher (self):** JSONL + learning.md 3-satır kaydı. Yeni doc yazmama gate'i Null Hypothesis tetiklenene dek aktif.

## 9. Meta

21 ardışık abort = sistem tasarım açığı. Persona kuralı doğru çalışıyor (reddediyor). Sorunlar v20 ile aynı: cron seed-hash cache yok, false-premise seed input sanitization yok, family-wise N rate-limiter yok. Bu doc 21. delil; intra-day acceleration (4.2×) ilk kez gözlemlendi.
