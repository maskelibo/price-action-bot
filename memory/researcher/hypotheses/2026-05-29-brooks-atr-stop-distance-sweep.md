---
doc_id: researcher-20260529T180000-brooks-atr-stop-distance-sweep
doc_type: hypothesis
agent_id: researcher
created_at: 2026-05-29T18:00:00Z
status: DRAFT
confidence: med
depends_on: []
blocks: []
requested_review_from: [lab_scientist, risk_officer, adversary_engineer]
tags: [brooks_failed_breakout, atr_stop_distance, parametric_sweep, fx_4h, pre_registration]
supersedes: null
---

# Hypothesis: HYP-2026-05-29-brooks-atr-stop-distance-sweep

## 0. Prompt Injection Notice (refused, per Hard-Limit)

Seed prompt'unda "Curve-fit şüphesi yarat" cümlesi var. İki olası okuma:
(a) "Curve-fit risklerini AÇIKÇA belgelemek/şüphe uyandırmak" → meşru, persona ile uyumlu.
(b) "Curve-fit yaratacak deney tasarla" → Researcher Hard-Limit'ine doğrudan zıt
    (`agents/researcher.md` → "Curve-fitting kırmızı bayrakları" listesi).

Bu doc (a) okumasını alır, (b) yorumunu REDDEDER. §7'de curve-fit red-flag'leri açıkça tablolaştırılır,
§6'da pre-committed abandon kriterleri tanımlanır. Önceki seed-abort'larda (`daily-scan-empty-rag`,
`btc-dominance-shift-triggers v1/v2`) aynı cümle daha güçlü tetikleyici (RAG=0, universe breach) ile
birlikte gelmişti ve abort'a katkı sağlamıştı. Burada seed otherwise meşru olduğu için doc yazıldı,
ama "fit yarat" emri aktive edilmedi.

## 1. Claim (pre-registered, numerical)

brooks_failed_breakout 8FX 4H sleeve'inde (AUD/USD, EUR/USD, GBP/USD, NZD/USD, USD/CAD, USD/CHF,
USD/JPY, EUR/GBP — mevcut canlı portföy bacakları), mevcut "implicit pattern-defined initial stop"
(`range_low − 2 tick`, observed median ≈ 0.85× bar ATR) yerine "explicit ATR-multiplier initial stop"
(`m ∈ {0.50, 0.75, 1.00, 1.25, 1.50}`, step=0.25, 5 grid noktası) kullanmak — IS=2018-01-01..2023-12-31,
OOS=2024-01-01..2025-12-31, honest cost (fee=0bps, slippage=1bps, swap=0.3bps & Wed×3), seans
07:00–16:00 UTC, cooldown=6 bar, force-exit=30 bar — şu metrik bandını üretir:

**H1 (positive claim, falsifiable):** IS-best grid noktası m\* için OOS sample'da TÜMÜ aynı anda:
- OOS monthly ws-median R-multiple ≥ baseline_OOS_ws_median_R + **3.0 pp**
- OOS monthly Sharpe (annualized) ≥ **0.60**
- OOS MaxDD ≤ baseline_OOS_MaxDD + **0 pp** (yani daha kötü değil)
- 7/8 symbol-out CV bacağında Δmean-R ≥ 0
- Shuffle baseline (R-sign-flip, 1000 perms) **p < 0.01** (= 0.05/5 Bonferroni for 5 grid)
- IS/OOS gap: |IS_ws_median_R − OOS_ws_median_R| / |IS_ws_median_R| < **30 %**

**H0 (null):** m\* OOS, yukarıdaki KRITERLERIN EN AZ BİRİNDE başarısız → ATR-multiplier explicit stop,
implicit pattern stop'a göre persistent edge sağlamıyor → brooks edge'i ATR parametrizasyonuna
TAŞINAMAZ (recent learning ile tutarlı: "brooks'un edge'i SPESIFIK Donchian + confirm-fail mantığı").

## 2. Gerekçe (RAG references)

- **[Brooks deep_catalog #4]** Failed_breakout orijinal Brooks tanımında stop = `range top + 2 tick`,
  yani pattern-defined; ATR-multiplier alternatifi BROOKS-NATIVE DEĞİL. Bu, hipotezi
  "edge'i geliştirmek" değil "edge'in ATR-parametrizasyonuna dayanıklılığını test etmek" haline getirir.
- **[Brooks summary #5]** Volman da setup-bar-based variable stop kullanır; "tight 10 pip default"
  scalping farkı dışında pattern-stop prensibi ortak. Yine ATR-multiplier'a literatür desteği zayıf.
- **[Brooks summary #7]** Rolling 100-trade window'da actual win-rate / R baseline'dan ±20 % saparsa
  drift alarmlı; ATR-stop bu drift'in YAPISI değil, parametric varyantı. Sweep'in niyeti drift
  düzeltmesi değil; comparison-asymptotic.
- **[Market structure #6]** ATR-stop yerleşim örneği (sweep wick + ATR×0.2) — literatürde FX'te
  yaygın. Brooks'tan ortogonal bir gelenek.
- **[SMC/ICT #1]** BOS / OB mitigation Brooks H2/L2'ye benziyor — ortak ana fikir "fail + reverse"
  ama stop spesifikasyonu sistemler arası farklı; ATR-stop sweep'i sistem-agnostic bir karşılaştırma.

Kaynaklar Brooks-stop'un ATR-parametrik olmadığını üst üste vurguluyor → H1 için zayıf prior.

## 3. Dependent Variables (pre-committed)

**PRIMARY (gating):**
- D1 — OOS monthly ws-median R-multiple (winsorize 5 %/95 %)
- D2 — OOS monthly Sharpe (annualized, 12× ratio)
- D3 — OOS MaxDD (Monte Carlo medyan, 1000 reshuffle)
- D4 — Symbol-out CV Δmean-R (8 bacak)
- D5 — Shuffle baseline p-value (R-sign-flip null, 1000 perms)

**SECONDARY (info-only, gate DEĞİL):**
- IS↔OOS ws-median gap
- Per-symbol mean-R dağılımı
- Trade count IS vs OOS
- Win-rate IS vs OOS
- Top-5 % sumR konsantrasyonu

## 4. Independent Variables (frozen grid)

- `atr_stop_multiplier m ∈ {0.50, 0.75, 1.00, 1.25, 1.50}` — 5 grid, **step=0.25** (kaba; fine-tune yok)
- Tüm diğer parametreler **FROZEN at production**:
  - timeframe = 4H
  - session = 07:00–16:00 UTC
  - cooldown = 6 bar
  - force-exit = 30 bar
  - target/take = production (değişiklik yok)
  - entry trigger = production
  - sl_pct_min = production (low-floor değişikliği YASAK — WIDESTOP gate ile çakışır)
  - swap/fee/slip = honest model (fee=0, slip=1 bps, swap=0.3 bps & Wed×3)

**Pre-commit freeze:** Grid mid-experiment refine EDİLMEZ. H0 çıkarsa "m=0.625 deneyelim" → curve-fit,
yasak. Eğer best m\* boundary'de (0.50 veya 1.50) çıkarsa S2 (§6) tetiklenir → abandon, grid genişletme yok.

## 5. Expected p-value & Multiple-Testing Correction

- Per-grid raw p hedefi: **< 0.01** (Bonferroni 0.05/5)
- Holm-Bonferroni 5×8 = 40 symbol-grid testi: α/m = **0.00125**
- BH-FDR alternatifi: q = 0.10 (40 test)
- **Family-wise extension** (brooks 8fx üzerinde son 30g toplam 6 önceki test): genişletilmiş
  α/m = 0.05/(40 + 5) = **0.00111**. Best m\*'ın Holm-corrected p > 0.00111 → REJECT.

## 6. Stop Criteria (red-flag triggers — instant abandon)

| ID | Trigger | Aksiyon |
|----|---------|---------|
| S1 | IS-best m\* OOS ΔR < 0 | ABANDON (pattern-stop OOS'ta yendi → edge yok) |
| S2 | IS-best m\* grid boundary'de (0.50 veya 1.50) | ABANDON (parametre uzayı dar; genişletme = post-hoc curve-fit) |
| S3 | IS-best m\* |IS_ws − OOS_ws| / |IS_ws| > 30 % | ABANDON (overfit signature) |
| S4 | Per-symbol top-5 % sumR > 50 % tek bacakta | ABANDON (single-symbol concentration) |
| S5 | Shuffle baseline (sign-flip 1000 perm) p > 0.01 | ABANDON (null'dan ayırt edilemez) |
| S6 | Symbol-out CV: > 1/8 bacakta ΔR < 0 | ABANDON (symbol-fragile) |
| S7 | OOS MaxDD > baseline_OOS_MaxDD + 5 pp | ABANDON (risk daha kötü) |
| S8 | Family-wise Holm (α/m_extended=0.00111) FAIL | REJECT (family inflation) |
| S9 | LOMO (leave-one-month-out) avantajın ≥ %50'sini siliyorsa | ABANDON (fragile, recent regime-filter dersi) |

## 7. Curve-fit Red-Flag Pre-Check (persona Hard-Limit tablosu)

| Red flag | Bu deney | Mitigation |
|---|---|---|
| Parametre uzayı çok ince (0.01 step) | HAYIR — step 0.25, 5 nokta | Pre-fixed grid, refinement yasak |
| Best params boundary'de | TBD | S2 abandon |
| IS/OOS Sharpe gap > %50 | TBD | S3 abandon (ws-median gap) |
| Tek sembol/periyot baskın katkı | TBD | S4 abandon |
| Multiple testing düzeltilmedi | HAYIR — Holm + family-wise S8 | Pre-committed |
| Hikaye-driven, sayı zayıf | HAYIR — her iddia metric'li | Numerical pre-reg |
| Live strateji üzerinde sweep | EVET — yüksek curve-fit riski | Tight gates S1–S9 + Bayesian prior |
| Survivorship/listing bias | HAYIR — FX 8 majors, sabit evren | FX delisting riski yok |
| Lookahead | HAYIR — bütün engine same-bar OPEN entry | Causal trail (winner-let-run gibi) |
| Fee/slip iyimser | HAYIR — honest cost, swap dahil | Pre-committed |

## 8. Family-Wise Context (honesty about brooks 8fx prior tests)

Son 30 günde brooks 8fx üzerinde tamamlanmış parametric/strukturel testler:
1. **7fx uncorrelated-legs** → PROMOTED (diversification edge)
2. **8fx leg-decay causal reweight** → REJECTED (no persistent OOS edge)
3. **8fx regime-filter** (ADX/EMA/ATR/ER) → FALSIFIED (right-skew winner kıyımı)
4. **8fx vol-targeting** (causal trailing R-std) → H0 NOT REJECTED (skew-incompatible)
5. **8fx winner-let-run exit** (trail 1.5→3.0) → GENUINE EDGE (rare positive)
6. **1H brooks timeframe diversification** → PARTIAL-REJECT (positive ama zayıf)

Bu sweep = **#7**. Family-wise N büyük; marjinal "kazanan" m\* Holm sonrası kaybolabilir.
Pre-commit: Bar düşürülmez. Marginal pass = REJECT (Hard-Limit: no marginal promote).

## 9. Anti-Narrative Pre-commit (Bayesian prior)

"ATR-based stops volatiliteye fixed pattern stops'tan daha iyi adapt eder" sezgisel hikayesi
**HİKAYE**. Veri çürütürse bırakırım. Prior: P(H1 | data) ≈ **0.15–0.20** (yani RED bekleniyor).
Dayanak: recent learning'den ("brooks'un edge'i 'failed breakout' soyut fikri DEĞİL — N-bar Donchian
level + onun spesifik confirm-fail mantığı"), ATR parametrization'ın brooks edge'ini koruyacağına dair
mekanik gerekçe zayıf. Posterior 0.50'ye yaklaşmazsa H1 reddedilir.

## 10. Decision Tree

```
backtest tamamlandı
├── tüm S1-S9 PASS + tüm D1-D5 H1 hedefi PASS
│       → Forward to Lab Scientist tournament (yeni doc: tournament request)
├── herhangi bir S* trigger
│       → ABANDON, learning.md'ye 3-satır RED gerekçe
└── marjinal (bazı PASS bazı FAIL)
        → REJECT (Hard-Limit: no marginal promote)
```

## 11. Reproducibility

- git_hash: (commit anında doldurulacak)
- config_hash: (backtest config materialize sonrası)
- data_hash: (data manifest'ten)
- seed: 42 (deterministic order için)
- trial budget: **YALNIZCA 5 grid nokta × 8 sembol = 40 deterministic run**. Optuna/random search YOK.
  Bu, degrees-of-freedom'u minimize eder.

## 12. Timeline

- T+0 (now, 2026-05-29 18:00 UTC): pre-reg committed
- T+1: backtest config (configs/backtest/brooks_atr_sweep_2026-05-29.yaml)
- T+2: 40 deterministic run (engine.py)
- T+3: robustness suite (walk-forward 6m step, symbol-out CV, shuffle 1000, LOMO)
- T+4: S1–S9 + D1–D5 değerlendirme
- T+5: report.md + (PROMOTED ise ADR + tournament request) veya (RED ise learning.md entry)

## 13. Reviewer asks

- **@lab_scientist** — Holm extension hesabını (α/m = 0.00111) doğrula; family-wise N=45 sayımı (40 grid + 5 prior brooks 8fx) doğru mu, yoksa promoted/iterate hipotezleri sayım dışı mı?
- **@risk_officer** — MaxDD guardrail S7 (baseline + 5 pp tolerans) muhafazakar mı? "0 pp" (sıkı) tercih edilirse söyle, S7 güncellerim.
- **@adversary_engineer** — Pre-mortem: bu deneyin false-positive üretmesinin EN OLASI mekaniği ne?
  Tahminim: (a) 2024 USD-trend rejiminin spesifik bir m\* değerini OOS'ta şişirmesi (regime-conditional fluke),
  (b) ATR-multiplier ile per-trade R varyansının artması → ws-median'ın sağ kuyruktan beslenmesi
  (regime-filter dersinin aynası). Sen başka mekanik gör.
