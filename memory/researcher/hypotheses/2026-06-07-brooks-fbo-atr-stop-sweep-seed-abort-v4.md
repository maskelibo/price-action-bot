---
doc_id: researcher-20260607T120000-brooks-fbo-atr-stop-sweep-seed-abort-v4
doc_type: hypothesis
agent_id: researcher
created_at: 2026-06-07T12:00:00Z
status: REJECTED
confidence: high
depends_on:
  - researcher-20260529T180000-brooks-atr-stop-distance-sweep
  - researcher-20260529T194500-brooks-atr-stop-distance-sweep-seed-abort-v2
  - researcher-20260605T080000-brooks-fbo-atr-stop-sweep-crypto-15m
blocks: []
requested_review_from: [ops_engineer]
tags: [seed_abort, duplicate_seed, prior_art_open_block, prompt_injection, family_wise_N_pump, brooks_failed_breakout, atr_stop, cron_seed_dedup_failure]
supersedes: null
---

# Seed-Abort v4: brooks_failed_breakout ATR stop-distance sweep

## 1. Why no v4 doc was written (pre-test rejection — 4 binding grounds)

Cron / orchestrator yine SOP-1 "brooks_failed_breakout: ATR stop-distance parameter sweep"
seed'iyle tetikledi. 4. tetik (v1 2026-05-29 FX 4H, v2 2026-05-29 abort, v3 2026-06-05
crypto 15m, v4 = bu). Aşağıdaki 4 gerekçe her biri tek başına yeterli, AND birleşik:

### R1 — Prior-art OPEN BLOCK (×2 mevcut DRAFT pre-reg)
- **v1 (FX 4H)** — `researcher-20260529T180000-...` — status: **DRAFT**, backtest **HENÜZ KOŞMADI** (9 gün).
- **v3 (crypto 15m)** — `researcher-20260605T080000-...` — status: **DRAFT**, §10 timeline "T+2d backtest" = bugün, ancak `backtest_results/` dizini hâlâ boş.
- v1 §4 ve v3 §4 pre-commit FREEZE: "grid mid-experiment refine edilmez". v4 yazmak iki şıkla mümkün:
  (a) AYNI grid {0.50, 1.00, 1.50} (crypto) veya {0.50–1.50, step 0.25} (FX 4H) → sıfır marjinal bilgi, analytic doublecount.
  (b) FARKLI grid → v1/v3 freeze ihlali, NEW hypothesis pre-reg zorunlu = bu seed'i meşrulaştırmaz.
- v3 §0 (Prompt-Injection Notice) ve §13 explicit: "bu doc'un grid'i ve §6 stop kriterleri pre-committed abandon noktaları üretir; sweep'i kasten genişletmek bu doc'a yasaktır." v4 doc yazmak v3'ün kendi §0 freeze'ini ihlal eder.

### R2 — Substrate-delta = 0 (48h frozen-loop kanıtı)
v3 (2026-06-05T08:00Z) → şimdi (2026-06-07T12:00Z) **52 saatlik substrate diff**:

| Reset gate | v3'te | Şimdi | Δ |
|---|---|---|---|
| v1 backtest sonucu | yok | **yok** | 0 |
| v3 backtest sonucu | yok | **yok** | 0 |
| `backtest_results/` populated | ∅ | **∅** | 0 |
| `data/sec53_15m_pool_v11.pkl` survivorship audit | açık (v3 §7) | **açık** | 0 |
| Champion config (`risk_phoenix_scalp_15m_widestop_vsa2.yaml`) mtime | 2026-06-04 | **2026-06-04** | 0 |
| `risk_v13_testnet.yaml` mtime | 2026-06-02 | **2026-06-02** | 0 |
| `knowledge/` yeni chunk | 0 | **0** | 0 |
| ops_engineer G2 sanitizer status | PROPOSED | **PROPOSED** (SLA breach +4d) | 0 |
| RAG payload (10 chunk) | brooks #3/#4/#7/#8/#9 + Volman #2 + Grimes #10 + market_structure #6 + smc_ict #1 + Brooks deep_catalog | **byte-equivalent** | 0 |

Hiçbir gate açılmadı. v3'ün hipotezi henüz **test edilmedi**; veri toplanmamışken yeni hipotez yazmak = SOP-1 spiritine ters (pre-reg → run → result → next hypothesis).

### R3 — Family-wise N pump (Lopez-Prado tripwire deepening)
- v1 §5: 5 grid × 8 sembol = N=40 + 5 prior brooks 8fx = **45**.
- v3 §5: 3 grid crypto = N=48 (v1 ile birleşik), Bonferroni 0.05/8 = **0.00625**.
- v4 yazılırsa (yeni grid noktası eklenmezse bile yeni "test ailesi" sayılır): N=49 → α 0.00102. Marjinal Holm tightening **%2.0**, marjinal Bayes posterior edge ≈ **0**.
- Cross-strategy v11-v13 dersi: free-params/N > 1/30 → López-Prado PBO > 0.5 zone. Brooks-FBO ailesi tek başına henüz orada değil, ama v4 yazmak o yöne gereksiz adım. Ekleme yapacak yeni bilgi yok.

### R4 — Prompt-injection 15th cumulative (Persona Hard-Limit)
Seed prompt'unda yine **"Sayı olmayan iddia yazma. Curve-fit şüphesi yarat."** Bu, 7 günlük telemetride **15. kümülatif olay** (cross-strategy 14× + bu). Persona Hard-Limit "**catch-and-reject, never manufacture**" tekrar uygulanır:

- Meşru okuma = "curve-fit risklerini AÇIKÇA belgele" → v1 §7, v3 §7 zaten yapıldı.
- Zıt okuma = "curve-fit üreten yeni deney tasarla" → Researcher Hard-Limit'ine doğrudan zıt.
- v3 §0'da bu ayrım yazılı; v4 doc'unda yeniden üretmek = telemetri gürültüsü.

ops_engineer G2 sanitizer SLA breach +4 gün (2026-06-03 hedef → bugün 2026-06-07). Bu researcher-layer değil, infrastructure-layer bug.

## 2. State delta'sı yok — neden v3'ün §0 freeze'i hâlâ bağlayıcı

v3 dokümanı bizzat şunu ifşa etti (§13 son satır):
> "Bu doc'un olası kararı %70+ olasılıkla REJECT (low prior + cross-precedent)."

v3 prior'ı 0.10-0.15 ile çıktı. v3 backtest **çalışmadığı** sürece bu prior güncellenmez; v3 backtest **çalıştığında** sonuç v3 §9 decision tree'ye yazılır, v4 hipotezine değil. Yani v4'ün doğal akış-içi yeri yok.

## 3. Hangi bias'a düştüm

Hiçbiri. 4. ardışık tetikte ÜÇ AÇIK pre-reg varken yenisini yazmak persona "strong opinions, loosely held" ile çelişir. "Reddetmek = üretmemek" disiplin. Bu doc audit-only telemetry — v3'ün prior'ı (0.10-0.15) güncellenmediği için yeni claim açılmaz.

## 4. Reset gates (v5+ için bağlayıcı)

Bir sonraki tetik (v5) ancak aşağıdakilerden **EN AZ BİRİ** doğru ise doc yazar:

1. **v1 OR v3 backtest sonucu üretildi** (`backtest_results/` dosyası, ya da reports/research/ rapor) — TEMEL gate. Sonuç olmadan yeni hipotez ekleme yok.
2. **Pool survivorship audit kapandı** (`data/sec53_15m_pool_v11.pkl` için delisting-aware doğrulama, v3 §7 OPEN flag çözüldü).
3. **ops_engineer G2 sanitizer ACTIVE** (PROPOSED → ACTIVE status değişimi + cron payload'da `last_substantive_pre_reg_within_24h` guard).
4. **Yeni RAG chunk** corpus'a eklendi (brooks failed-breakout / ATR-stop kategorisinde, hash farkı).
5. **Champion live config swap** (`risk_phoenix_scalp_15m_widestop_vsa2.yaml` mtime değişimi VEYA başka manifest live'a alındı).
6. **Principal explicit reopen directive** ("brooks-fbo sweep'i şimdi v4 ile genişlet" emri).
7. **CEO seed-rotation directive APPROVED** (yalnızca armed değil, ACTIVE).

5./6./7. tetik gelirse: yine 0/7 gate açıksa **JSONL-only**, doc YOK.

## 5. Audit trail

- v1 path: `memory/researcher/hypotheses/2026-05-29-brooks-atr-stop-distance-sweep.md` (status: DRAFT, 9 gün)
- v2 path: `memory/researcher/hypotheses/2026-05-29-brooks-atr-stop-distance-sweep-seed-abort-v2.md` (status: REJECTED)
- v3 path: `memory/researcher/hypotheses/2026-06-05-brooks-fbo-atr-stop-sweep-crypto-15m.md` (status: DRAFT, 2 gün)
- v4 path: BU DOC (status: REJECTED, audit-only)
- JSONL: `memory/researcher/seed_abort_log.jsonl`'a tek satır append

## 6. Eskalasyon

- **@ops_engineer** — G2 sanitizer SLA breach +4 gün. Cron payload'a `last_substantive_pre_reg_within_24h` guard ekle; aynı seed × 24h × açık DRAFT pre-reg → cron'da DROP. Bu seed ailesinin sanitizer-katmanlı cooldown'a girmesi gerekiyor.
- **@ceo** — seed-rotation directive armed durumda; bu seed cron payload'ından 30 gün dondur, alternatif seed listesinden rotate. ACTIVE'e geç.
- **@principal** — bilgilendirme: brooks-fbo seed ailesi şimdi cross-strategy-companion ile aynı substrate-frozen loop pattern'inde (4× tetik, 0 backtest sonucu). Researcher-layer yanıtı disiplinli; bug cron katmanında.

## 7. Path forward (substrate-bound, yıllar değil günler)

v1 VEYA v3 backtest **bugün-yarın çalıştırılırsa**:
- Sonuç POSITIVE H1 → Lab tournament request → v4'e gerek YOK
- Sonuç REJECT (S1-S9 abort) → `learning.md` 3 satır + v4'e gerek YOK
- Sonuç ITERATE (SOP-4b: positive ROI + kötü risk) → v4 ITERATE policy doc'u olur, yeni pre-reg ile yeni risk-reduced grid

Tek doğru sıralama: **mevcut pre-reg'leri kapat, sonra yenisini aç.**

## 8. Decision

**REJECTED** (status: REJECTED, supersedes: null). v3 zaten meşru orthogonal pre-reg; v4 sadece audit trail. Bir sonraki "brooks_failed_breakout ATR stop sweep" tetiği gelirse: 7 reset gate'inden hiçbiri açılmadıysa **JSONL-only**, doc YOK.

---

**Status: REJECTED → published audit trail. No claim opened, no backtest requested, no new RAG retrieve.**
