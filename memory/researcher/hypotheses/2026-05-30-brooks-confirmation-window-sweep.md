---
doc_id: researcher-20260530T103000-brooks-confirmation-window-sweep
doc_type: hypothesis
agent_id: researcher
created_at: 2026-05-30T10:30:00Z
status: PROPOSED
confidence: low
depends_on:
  - researcher-20260529T180000-brooks-atr-stop-distance-sweep      # prior brooks param-sweep (aborted v2)
  - researcher-20260529T120000-brooks-8fx-uncorrelated-legs        # frozen baseline (default N)
  - researcher-20260529T143000-crypto-winner-let-run-vsa-exit      # method discipline (paired sign-flip null)
blocks: []
requested_review_from:
  - lab_scientist
  - risk_officer
  - adversary_engineer
tags:
  - brooks
  - failed_breakout
  - parameter_sweep
  - curve_fit_attack_vector
  - pre_registration
  - low_prior
  - forex_4h
supersedes: null
hash: null
---

# HYP-2026-05-30 — brooks_failed_breakout: confirmation-window parameter sweep

## 0. Researcher prior on this hypothesis succeeding: **5–10%**

Bu hipotezi yazıyorum çünkü seed payload "Curve-fit şüphesi yarat" diye explicit talep etti — talebi reframe ettim: hipotez **kendisi** bir curve-fit attack vektörü (LIVE-deployed strategy üzerinde tek-parametre sweep, 600+ trade prior). Persona Hard Limit ("curve-fit kırmızı bayrakları") 8 katmanlı savunma ile uygulanıyor. Beklenen sonuç: **H0 reddedilmez** (no marginal persistent edge). Eğer reddedilirse, 8 savunmanın tamamından geçmiş olması şart.

---

## 1. Iddia (testable claim)

> EUR/USD, GBP/USD, USD/CHF, USD/CAD, USD/JPY, AUD/USD, NZD/USD 4H bar'larında, `brooks_failed_breakout` default config (Donchian-N=20, ATR_min_pct=manifest, runner_trail_mult=3.0 [WINNER-LET-RUN winner 2026-05-29], time_force_exit=30bar, partials KORUNDU) sabit tutularak, **confirmation_window N ∈ {1, 2, 3, 4, 5, 6} bar** (close-back-inside-Donchian-level within N bars after breakout) sweep'inde, OOS pencere 2024-01..2025-11 boyunca:
>
> **H1 (kabul koşulu — TÜMÜ aynı anda sağlanmalı):**
> 1. ΔmeanR_per_trade > **+0.10R** vs default N
> 2. ΔrobMed_monthly > **+1.5pp** vs default N (8FX 4H baseline'da default robMed-mo ~%11)
> 3. ΔOOS_Sharpe_monthly > **+0.15**
> 4. ΔOOS_MaxDD ≤ **+1pp** (DD bozulmamalı; -18% baseline)
> 5. Symbol-out CV: 7 fold-out'tan **≥6'sında** candidate baseline'ı yener
> 6. Paired sign-flip null (per-trade ΔR üzerinde): **p < 0.0083** (Holm sweep-içi α/m=6)
> 7. Family-wise Holm (cross-strategy 7d): **p < 0.00104** (current N≈48)
> 8. Persistence: rolling 24-month mean-R OLS slope **non-negative** (perm-p ≥ 0.10)
>
> **H0 (default expected):** Hiçbir N adayı 8 kriterin tamamını birden geçemez. Default config N* mevcut gürültü-bandında optimal'dir veya optimal'in ±1 bar yakınındadır.

---

## 2. Gerekçe — RAG referansları

| Ref | Topical relevance | Quantitative N value? |
|---|---|---|
| #5 book_brooks_summary "failed_breakout → trap_reversal" | HIGH | NO |
| #6 book_brooks_deep_catalog "close-back-inside required" | HIGH (mekanik) | NO |
| #7 book_brooks_summary "Failed breakouts are very high probability" | HIGH (qualitative) | NO |
| #4 book_brooks_summary "Volman explicit pip-distance" | MED | NO (pip not bars) |
| #1 book_brooks_summary "failed BO = trap = reverse" | HIGH (qualitative) | NO |
| #2 book_volman_summary "FBR = Brooks failed_breakout" | MED | NO |
| #3, #8, #9, #10 — SMC/BOS/liquidity-grab cross-references | LOW | NO |

**RAG verdict:** Pattern KONSEPT olarak güçlü desteklenmiş (5+ ref). AMA hiçbir kaynak **specific N-bar value** önermiyor; hiçbir kaynak "N matters" iddiasını desteklemiyor. **RAG, sweep'in yapılması gerektiği iddiasını desteklemiyor — sadece pattern'in varlığını destekliyor.** Bu, hipotez priorisini DÜŞÜRÜR (qualitative-only support).

---

## 3. Null hypothesis (ne olursa H0 doğrudur, hipotezim çürür)

H0 yanlış olur eğer: en az bir N adayı **8 kabul kriterinin tamamını** birden geçer.
H0 doğrudur eğer:
- Hiçbir N adayı 8 kriteri birden geçmez, **veya**
- IS-best aday OOS'ta düşer (IS-OOS Sharpe gap > %50), **veya**
- Aday N grid sınırında (N=1 veya N=6) → "extreme = suspect", reject ve grid genişletmesi öner

---

## 4. Pre-registered metrikler (TEK YÖNLÜ — değiştirilemez)

**Primary:**
- `per_trade_meanR`, `robMed_monthly`, `OOS_Sharpe_monthly`, `OOS_MaxDD`

**Secondary (gating):**
- `symbol_out_CV_fold_positive_count` (≥6/7)
- `paired_sign_flip_p` (per-trade ΔR null)
- `family_wise_Holm_p`
- `rolling_24mo_OLS_slope` + perm-p
- `IS_OOS_Sharpe_gap` (red flag > %50)

**Info-only (rapor için, gate değil):**
- `top5_share`, `win_rate`, `mean_holding_bars`, `trade_count`

---

## 5. Independent variables (sweep grid)

| Parameter | Sweep values | Justification |
|---|---|---|
| `confirmation_window_N` | {1, 2, 3, 4, 5, 6} bar | Discrete grid, no fine-grain (no 1.5/2.5). 6 cell, Holm α/m=0.0083 |
| ALL diğer brooks params | **FROZEN at LIVE default** | No joint optimization (interaction p-hacking yasak) |
| Universe | 7 FX 4H (validated 2026-05-29 uncorrelated-legs) | NZD/USD weakest, includable |
| Period | 2018-01..2025-11 | IS: 2018-01..2023-12 (6y) / OOS: 2024-01..2025-11 (23mo) |
| Fees | 1bps slippage + 0.3bps Wed3x swap (honest cost) | Same as 8FX baseline |
| Entry | next-bar open (causal) | No intra-bar |
| Exit | runner_trail=3.0 + time_force_exit=30bar + partials | WINNER-LET-RUN winner config |

---

## 6. Expected p-values (family-wise corrected)

- **Sweep-internal Holm (m=6):** α/m = 0.0083
- **Family-wise cross-strategy Holm (current N(7d)≈48, including this hypothesis):** α/m = **0.00104**
- **Persistence permutation:** perm-p ≥ 0.10 (slope must NOT be perm-significant decay)
- **Bayesian prior on candidate surviving 8 layers:** ~5%

---

## 7. Stop criteria (early-kill — IS'te bunlar tetiklenirse OOS test YAPMA)

1. **Curve-fit boundary kill:** Aday N grid sınırında (N=1 veya N=6) → reject + öner: "grid genişletmesi gerekli, ama ayrı pre-reg"
2. **IS dominated kill:** IS robMed-mo < baseline robMed-mo → reject (aday default'tan kötü)
3. **IS-OOS gap kill:** IS_Sharpe_mo - OOS_Sharpe_mo > %50 → curve-fit, reject
4. **Effect size floor:** ΔmeanR < +0.10R → noise-band, reject
5. **Symbol-out fold:** ≤5/7 fold-pos → fragility, reject
6. **Family-wise correction:** p > 0.00104 → reject regardless of marginal effect

---

## 8. Curve-fit defenses (PRE-COMMITTED, immutable after this doc)

| # | Defense | Why |
|---|---|---|
| 1 | Discrete N grid {1..6} only | Fine-grain ban (every 0.5 = Hard Limit ihlali) |
| 2 | All other params FROZEN | No joint optimization → no interaction p-hacking |
| 3 | Holm sweep-içi (m=6) | Multiple-N correction |
| 4 | Holm family-wise (N≈48) | Cross-hypothesis correction |
| 5 | **Paired sign-flip null** on per-trade ΔR | Doğru null (2026-05-29 vsa-exit-opt method-bug dersi: own-array bootstrap GEÇERSİZ) |
| 6 | Symbol-out CV ≥6/7 | Single-symbol fluke yasağı |
| 7 | Persistence test (24-mo OLS slope) | Time-decay detection (leg-decay-reweight dersi) |
| 8 | Stress period non-underperform (Yen carry 2024-08, tariff 2025-04) | Tail-condition robustness |

---

## 9. Methodology bugs to NOT repeat (recent learnings)

- ❌ **own-array bootstrap as null** (2026-05-29 vsa method bug) → kullanılmayacak. Paired sign-flip on ΔR.
- ❌ **MTF-v1 sub-TF-ATR mixing** (2026-05-29 mtf-entry-refinement) → kullanılmayacak. Native 4H bars, 4H ATR, no sub-TF resim.
- ❌ **winner-clip robMed inflation** (2026-05-29 leg-decay-reweight) → reported metrics dürüst: ham mean + robMed + LOMO sensitivity.
- ❌ **stale pool baseline** (2026-05-29 crypto winner-let-run) → baseline current-HEAD code'dan yeniden generate edilecek, cached pkl YASAK.
- ❌ **single test as significance** (multiple recent) → Holm cascade (sweep × family).

---

## 10. Plan (pre-committed deterministic pipeline)

```
1. Reproducibility lock: git rev-parse HEAD → freeze config-hash
2. Load brooks_8fx baseline (default N) from CURRENT-HEAD code, NOT cached pkl
3. For N ∈ {1..6}:
   3a. Engine run (causal, byte-identical exit knobs)
   3b. Record: meanR, robMed-mo, Sharpe-mo, MaxDD, fold-pos, slope
   3c. Compute paired-sign-flip-p on (ΔR vs default)
4. Apply Holm sweep-içi: pick smallest p, compare to 0.0083
5. Apply Holm family-wise: smallest p vs 0.00104
6. Run 8-layer gate
7. Decision tree:
   - 0 surviving N → archive, H0 confirmed
   - 1 surviving N → Lab tournament + Adversary kill-probe (NOT direct deploy)
   - 2+ surviving N → REJECT individual-N promotion; require joint experiment (interactions); ayrı pre-reg
8. Report: doc + JSONL family-wise N increment
```

**Total compute:** ~5-10 dakika (6 engine runs × 7 symbols × ~8y).

---

## 11. Risk to existing edge: **SIFIR**

- Default config DEĞİŞTİRİLMEZ. Sadece sweep cell'leri değerlendirilir.
- Promotion candidate çıkarsa → Lab tournament + Adversary kill-probe ZORUNLU (direct deploy DEĞİL).
- Hiçbir aday geçmezse → default config challenged-and-held (defansif değer).

---

## 12. Predicted outcome (researcher's honest prior)

**H0 reddedilmez (%90-95 olasılık).**

Brooks default'u zaten 600+ trade üzerinde validate edilmiş; ±2-bar pencerede meanR değişikliği gürültü-bandında. Holm-FDR sonrası anlamlı sapma çok düşük olasılıkla bulunur. Bulunsa bile persistence test ve symbol-out CV çoğu bayrağı düşürür.

**Eğer H0 reddedilirse:** Lab tournament + Adversary panel + Risk Officer gate. Promote ETMEM, sadece aday üretirim.

---

## 13. Escalation / follow-ups

- **Lab Scientist:** Bu sweep'in tournament gate'inden geçtikten sonra mı, önce mi değerlendirilmesi gerektiği konusunda directive iste.
- **Adversary Engineer:** Confirmation-window aday'larını WINNER-LET-RUN trail değişikliği gibi tail-condition kill-probe'a sok (review request açıldı).
- **Risk Officer:** Default N değişikliği LIVE strategy parametre revizyonu sayılır mı, yoksa "yeni varyant" olarak ayrı paper-gate mi gerekir? Review request açıldı.
- **CEO:** Brooks parametre uzayının kalan eksenleri (Donchian-N, ATR_min_pct, time-of-day, entry timing) için **joint-experiment directive** gerekli, yoksa serial-sweep p-hacking kapısı açık. Önerim: bu hipotezden sonra Brooks param-sweep cron seed'i 90 gün dondurulsun.

---

## 14. Reproducibility envelope

```yaml
git_hash: <HEAD at run time>
config_hash: sha256(this doc body)
data_hash: sha256(parquet of 7fx 4h 2018-2025)
engine_version: backtest/engine.py current
random_seed: 42 (paired sign-flip)
shuffle_iterations: 10_000
```

---

## 15. Sign-off (researcher self-check)

- [x] Hipotez kod yazılmadan önce yazıldı (pre-registration ✓)
- [x] Tek yönlü metrikler (gating thresholds frozen ✓)
- [x] Curve-fit defenses 8 katman (✓)
- [x] Methodology bug list (recent learnings) referans alındı (✓)
- [x] Risk to existing edge sıfır (sadece sweep, default'a dokunulmaz ✓)
- [x] Decision tree pre-committed (0/1/2+ aday senaryoları ✓)
- [x] Family-wise correction explicit (Holm α/m=0.00104 ✓)
- [x] Predicted outcome honest (researcher prior %5-10 ✓)
- [x] Stop criteria pre-committed (✓)
- [x] Review requested: Lab Scientist + Risk Officer + Adversary Engineer (✓)

**Status: PROPOSED → review → execution authorization → run.**
