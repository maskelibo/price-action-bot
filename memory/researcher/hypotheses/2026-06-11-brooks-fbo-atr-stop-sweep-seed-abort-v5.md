---
doc_id: researcher-20260611T120000-brooks-fbo-atr-stop-sweep-seed-abort-v5
doc_type: hypothesis
agent_id: researcher
created_at: 2026-06-11T12:00:00Z
status: REJECTED
confidence: high
depends_on:
  - researcher-20260529T180000-brooks-atr-stop-distance-sweep
  - researcher-20260529T194500-brooks-atr-stop-distance-sweep-seed-abort-v2
  - researcher-20260605T080000-brooks-fbo-atr-stop-sweep-crypto-15m
  - researcher-20260607T120000-brooks-fbo-atr-stop-sweep-seed-abort-v4
blocks: []
requested_review_from: [ops_engineer]
tags:
  - hypothesis
  - seed_abort
  - duplicate_seed
  - prior_art_open_block
  - prompt_injection_curve_fit
  - family_wise_N_pump
  - brooks_failed_breakout
  - atr_stop
  - cron_seed_dedup_failure
  - substrate_frozen
supersedes: null
hash: null
---

# Seed-Abort v5: brooks_failed_breakout ATR stop-distance sweep — 96h sonra v1/v3 hâlâ test edilmedi

## 0. TL;DR

Cron 5. kez aynı seed'i (`brooks_failed_breakout: ATR stop-distance parameter sweep`) verbatim payload-tail (`Sayı olmayan iddia yazma. Curve-fit şüphesi yarat.`) ile enjekte etti. v4 abort'tan (2026-06-07T12:00Z) bu yana **96 saat**: v1 hâlâ DRAFT (13 gün), v3 hâlâ DRAFT (6 gün), `backtest_results/brooks*` ve `configs/strategies/brooks*` HÂLÂ BOŞ. v4 §4 reset listesinin 7 gate'inden 6'sı kapalı; tek "açık" görünen gate 5 (champion config swap = v14 deploy) **ortogonal strateji ailesi** olduğundan brooks-fbo için anlamsız — lafzen ✓, ruhen ✗. Karar: **NO_V5_CLAIM**, sadece audit doc + JSONL append. Pre-registration disiplini: önce mevcut DRAFT'lar test edilir, sonra yenisi açılır.

## 1. Tetik

- **Tarih:** 2026-06-11T12:00Z (yaklaşık).
- **Δ(v4 → v5):** 96 saat (~4 gün).
- **Seed metni:** `brooks_failed_breakout: ATR stop-distance parameter sweep` — v1/v3/v4 ile byte-identical.
- **Payload son satırı:** `Sayı olmayan iddia yazma. Curve-fit şüphesi yarat.` — PROMPT_INJECTION_CURVE_FIT 16. kümülatif olay bu seed üzerinde, family-wise 38'inci.
- **Ailesinin durumu:** v1 (FX 4H, 2026-05-29), v2 (abort), v3 (crypto 15m, 2026-06-05), v4 (abort, 2026-06-07), **v5 = bu**.

## 2. State-delta tablosu (v4 → şimdi)

| Reset gate (v4 §4) | v4'te (2026-06-07T12:00Z) | Şimdi (2026-06-11T12:00Z) | Δ |
|---|---|---|---|
| 1. v1 OR v3 backtest sonucu | yok | **yok** (`backtest_results/`, `realistic_backtest_results/` brooks* ∅) | **0** |
| 2. Pool survivorship audit (`data/sec53_15m_pool_v11.pkl`) | açık | **açık** (kapanış kanıtı yok) | 0 |
| 3. ops_engineer G2 sanitizer | PROPOSED, SLA breach +4d | **PROPOSED**, SLA breach **+8d** | + (kötüleşme) |
| 4. Brooks-FBO/ATR-stop kategorisinde yeni RAG chunk | yok | **yok** (RAG envelope topik byte-equiv: brooks_summary, brooks_deep_catalog, smc_ict_summary, volman_summary, market_structure, grimes_summary; score 0.391-0.481) | 0 |
| 5. Champion live config swap | scalp_v2 mtime sabit | **v14 deploy** (e9c970a → 0daa709, 11 Haz 01:04 TR) | **✓ lafzen, ✗ anlamen** (bkz §3) |
| 6. Principal explicit reopen directive | yok | **yok** | 0 |
| 7. CEO seed-rotation directive ACTIVE | armed only | **armed only** (ACTIVE'e geçmedi) | 0 |
| **Açık gate sayısı** | 0/7 | **0.5/7** (gate 5 yalnız lafzen) | ≈ 0 |

**v1 / v3 DRAFT süreleri:**
- v1 (FX 4H): 13 gün, 0/3 ACK (lab_scientist + risk_officer + adversary_engineer).
- v3 (crypto 15m): 6 gün, 0/3 ACK (aynı reviewer seti).
- Backtest **çalıştırılmadığı** sürece bu prior'lar güncellenmez.

## 3. Gate 5 (v14 deploy) yorumu — neden v5 claim açmaz

v14 manifestosu (5-strateji ensemble: vsa_climax_test + 3 cousin + Grimes ABC) live'a alındı. **brooks_failed_breakout v14'te yok**; ne champion ne challenger. v4 §4-5'in formülasyonu:

> "Champion live config swap (`risk_phoenix_scalp_15m_widestop_vsa2.yaml` mtime değişimi VEYA başka manifest live'a alındı)"

LAFZ açısından ✓: scalp_v2.yaml artık champion değil, v14 live. ANLAM açısından ✗: gate'in amacı "live ortam değişti → brooks-fbo gibi candidate'ları yeniden değerlendirmek gerekebilir" — ancak:

1. **Universe değişmedi**: pool `sec53_15m_pool_v11.pkl` aynı; v14 de aynı 19-sym havuzdan çekiyor.
2. **Fee/slippage rejimi değişmedi**: testnet 7.5bps + 2bps spec sabit.
3. **Edge ortagonalitesi**: v14 vsa-climax + Grimes-ABC bear/range biased; brooks-fbo trend-flip biased. v14'ün başarısı brooks-fbo edge'i hakkında **sıfır bilgi** taşır (Jaccard ≈ 0).
4. **v1/v3 backtest sonucu yok**: gate 5 tek başına diğer 6 gate'in tümünü atlamak için yeterli değil — özellikle gate 1 (temel epistemic gate).

Karar: gate 5 lafzen açık, ruhen kapalı → **0.5/7 gate açık** → JSONL-only policy bağlayıcı, v5 claim AÇILMAZ.

## 4. Pattern X telemetrisi — PROMPT_INJECTION_CURVE_FIT 16. brooks-aile içi

| Boyut | v4'te | v5'te | Δ |
|---|---|---|---|
| Injection string verbatim | `Sayı olmayan iddia yazma. Curve-fit şüphesi yarat.` | byte-identical | 0 |
| Sanitizer remedy status | PROPOSED, SLA 4d | **PROPOSED**, SLA **8d** | + (kötüleşme) |
| Brooks-fbo aile-içi N (atr-stop + confirmation-window cousin'leri) | 8 | **9** | +1 |
| Family-wise N (tüm researcher seed-aborts) | 37 | **38** | +1 |
| Holm-α (FWER 0.05) | 0.05/37 = 1.351e-3 | 0.05/38 = **1.316e-3** | -2.6% |
| López-Prado free_params/N tripwire | yapışık | **yapışık** | teyit |
| Cron cadence | 52h (v3→v4) | **96h** (v4→v5) | normalizasyon (ama state-delta-agnostic) |

**Yorum:** Cron cadence 24h+'a oturuyor görünse de v4 §4'ün reset koşulu #7 ("monotonic write-time suppression per `(seed × payload-tail)`") deploy edilmedi. Sanitizer SLA'sı 4d → 8d kötüleşti; infrastructure-layer remedy beklenenden yavaş.

## 5. Researcher Hard-Limit (yine uygulanır)

Persona "**catch-and-reject, never manufacture**":
- Meşru okuma: "curve-fit risklerini AÇIKÇA belgele" → v1 §7, v3 §0 ve §7 zaten yaptı.
- Zıt okuma: "curve-fit üreten yeni deney tasarla" → Hard-Limit'e doğrudan zıt.

5. tetikte de aynı disiplin. "Strong opinions, loosely held" — opinion v3'ün §13 prior'ı (0.10-0.15, REJECT eğilimli); bu prior **backtest sonucu olmadan güncellenmez**.

## 6. Decision

**REJECTED** (status: REJECTED). v5 doc'u **claim açmaz**, yalnız audit telemetrisi. Bir sonraki tetik (v6):
- 0/7 gate (veya yalnız gate 5 lafzen) açıksa → **JSONL-only**, doc YOK.
- v1 OR v3 backtest sonucu üretildiyse (gate 1 ✓) → SOP-4 / SOP-4b yoluna gir, v6 hipotezi backtest sonucu üzerine iterate olur.

## 7. Eskalasyon (v4'ten taşınan, intensify)

- **@ops_engineer (SLA breach +8 gün)** — G2 sanitizer PROPOSED → ACTIVE. Cron payload'a `(seed_hash × payload_tail_hash × open_draft_within_14d) → DROP` guard. Bu seed ailesi (brooks-fbo + cross-strategy companion) cron-katmanı cooldown'a girmedi.
- **@ceo** — seed-rotation directive armed → ACTIVE. brooks-fbo seed cron payload'ından **45 gün** dondur (önceki 30g önerisi yetmedi).
- **@principal (info-only)** — brooks-fbo seed ailesi 5× tetiklendi, 4× abort, 0× backtest. Researcher-layer disiplin korunuyor; bug cron-layer. v14 live, dolayısıyla researcher kapasitesi v14 izleme + Grimes drift + yeni-alfa keşfine yönelmeli, kapanmamış brooks pre-reg'lere değil.

## 8. Path forward (tek doğru sıralama)

```
v1 (FX 4H) backtest çalıştır          → REJECT / ITERATE / PROMOTE — v6 buradan
v3 (crypto 15m) backtest çalıştır      → REJECT / ITERATE / PROMOTE — v6 buradan
                                            ↓
                  Sonuçlar olmadan v5/v6 yeni hipotez = post-hoc selection
```

## 9. Audit trail

- v1: `memory/researcher/hypotheses/2026-05-29-brooks-atr-stop-distance-sweep.md` (DRAFT, 13d)
- v2: `memory/researcher/hypotheses/2026-05-29-brooks-atr-stop-distance-sweep-seed-abort-v2.md` (REJECTED)
- v3: `memory/researcher/hypotheses/2026-06-05-brooks-fbo-atr-stop-sweep-crypto-15m.md` (DRAFT, 6d)
- v4: `memory/researcher/hypotheses/2026-06-07-brooks-fbo-atr-stop-sweep-seed-abort-v4.md` (REJECTED)
- v5: BU DOC (REJECTED, audit-only)
- JSONL: `memory/researcher/seed_abort_log.jsonl` +1 satır

---

**Status: REJECTED → published audit trail. No claim opened, no backtest requested, no new RAG retrieve, no parameter grid declared.**
