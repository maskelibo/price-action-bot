---
doc_id: researcher-20260620T000000-volatility-regime-sizing-optimization
doc_type: hypothesis
agent_id: researcher
created_at: 2026-06-20T00:00:00Z
status: DRAFT
confidence: med
depends_on: []
blocks: []
requested_review_from: [lab_scientist, risk_officer]
tags: [hypothesis, sizing, volatility_regime, kaufman_regime, lopez_deleveraging, fractional_kelly, sop_1, pre_registration]
supersedes: null
hash: null
---

# Hypothesis: HYP-2026-06-20-volatility-regime-sizing

## 0. Meta
- **Hipotez ID:** HYP-2026-06-20-volatility-regime-sizing
- **Versiyon:** 0.1
- **Pre-registration tarihi:** 2026-06-20 (kod yazılmadan önce)
- **Seed konu:** Volatility regime sizing optimization
- **Bağımsızlık notu:** Bu hipotez sembol-seçim / pattern-detector katmanından ortogonaldir; mevcut promote-edilmiş bir strateji (carrier = Brooks-failed-breakout v8, in-sample champion) üzerinde "sizing wrapper" olarak test edilir. Carrier'ın edge'i sabit kabul edilir; yalnız sizing politikası değişir.

## 1. Iddia (ölçülebilir, tek cümle)

> "USDT-perpetual evreni (all_liquid N≈80 sembol, 3y in-sample 2023-06-20→2026-06-19, 12 ay walk-forward), 1d timeframe, carrier = Brooks-failed-breakout v8 (sabit detektör). Sizing'i 60-bar ATR_pct (ATR_14/close) **terts kantil rejimine** bağlamak — **rejim-düşük (Q0-33) %1.00 risk_per_trade, rejim-orta (Q33-66) %0.70, rejim-yüksek (Q66-100) %0.45** ve López dynamic deleveraging L_t = L* · (1 − D_t/DD_cap)^1 ile çarpmak (DD_cap = %25) — sabit %1 fixed-fractional baseline'a göre, fee=7.5bps taker + slippage=5bps, başlangıç 10k USDT, ayrı in-sample/OOS koşullarda aşağıdaki kriterleri **TÜMÜNÜ** sağlar:
>
> - **ΔSharpe (OOS) ≥ +0.20** (yani baseline OOS Sharpe S₀'a karşı S₁ ≥ S₀+0.20 ve göreceli ≥ %15 artış)
> - **ΔMaxDD (OOS) ≥ %20 mutlak azalış** (ör. baseline −%25 → aday ≤ −%20)
> - **ΔCAGR (OOS) ≥ −%10 göreceli kayıp tavanı** (size küçültme nedeniyle return düşüşü %10'u geçmemeli)
> - **Profit Factor (OOS) Δ ≥ 0** (azalmamalı)
> - **Welch t-test (per-trade r) p < 0.01** ve **DSR (Deflated Sharpe Ratio) p < 0.05** (Bonferroni'ye karşı k = parametre kombinasyon sayısı)"

## 2. Null Hipotez (ne olursa iddia çürür)

> H₀: Regime-aware sizing + López deleveraging, OOS Sharpe / MaxDD / Profit Factor üçlüsünde fixed %1 fractional baseline'ı **istatistiksel anlamlı şekilde yenmez**. Spesifik:
> - Welch t-test per-trade r serisinde p ≥ 0.05, **VEYA**
> - ΔSharpe < +0.10 mutlak (göreceli < %10), **VEYA**
> - ΔMaxDD < %10 mutlak (yani DD azalışı yeterince anlamlı değil), **VEYA**
> - DSR p ≥ 0.05 Bonferroni sonrası

İkisinden biri tutmazsa hipotez **REJECTED**.

## 3. Gerekçe — RAG Referansları

| # | Kaynak | Katkı |
|---|---|---|
| [Kaufman ch. on regime-aware sizing] (RAG chunk #4 score=0.327) | Kaufman: 30-trade rolling WR>%60 → tam size, <%40 → size ÷2. "Sample size noisy" uyarısı: window seçimi kritik. | Regime-tetik **WR** üzerinden değil **volatilite** üzerinden (carrier-orthogonal, sample-size noisy değil), ama yapısal motivasyon Kaufman'dan. |
| [López ch. dynamic leverage] (RAG chunk #5 score=0.323) | L_t = L* · (1 − D_t/DD_max)^α, α≈1–2. "Kayıp halinde küçül" prensibi, real-money fonu ölmekten korur. | DD-tabanlı çarpan ekleyerek path-dependent koruma — α=1 ile başla, α=2 robustness'ta. |
| [Kaufman ch. fractional Kelly] (RAG chunk #6 score=0.312) | Optimal-f distribution-stationarity varsayar; pratikte 0.1f–0.25f kullanılır. | %1 baseline'ın kendisi zaten ~0.25f civarı; rejim-aware ile alt sınır %0.45 (~0.1f) ortalama 0.15f bölgesine çekilir → fractional Kelly literatürüne uyumlu. |
| [Kaufman pos sizing formülü] (RAG chunk #7 score=0.303) | size = (Equity × risk_pct)/(Entry−Stop). Crypto fat-tail için %0.5–1.0. | Sizing aritmetiği değişmiyor; sadece risk_pct rejim koşullu — overhead sıfır, lookahead-safe (volatilite t-1 close'a kadar). |
| [Grimes ch. volatility cycles] (RAG chunk #9 score=0.294) | Volatilite döngüseldir (düşük→yüksek→düşük). NR7 → expansion mantığı. | Volatilite kantilleri stabil değil — rejim sınırları **rolling** olmalı (sembol başına son 252 bar), global değil. |

RAG **off-topic** chunk'lar (#1, #2, #3, #8, #10): batch-size ML, Jane Street gradient calc, SMC/Volman OB — bu hipoteze katkı sıfır.

## 4. Dependent Variables (ölçülecek metrikler)

| Metric | Yön | Birincil? |
|---|---|---|
| OOS Sharpe (per-symbol-aggregate, annualized √252 daily eq return) | maximize | ✓ birincil |
| OOS MaxDD (account equity tabanlı, çift-bonded `audit_risk` CT-RSK-01 düzeltmesi sonrası) | minimize | ✓ birincil |
| OOS CAGR | maximize (constraint: ≥ baseline−%10) | ✓ |
| OOS Profit Factor | ≥ baseline | ✓ |
| OOS Sortino | maximize | secondary |
| OOS Calmar (CAGR / MaxDD) | maximize | secondary |
| Per-trade R serisinin std | minimize | secondary (path stability) |
| Welch t-test p (paired per-trade r vs baseline) | < 0.01 | birincil (anlamlılık) |
| Deflated Sharpe Ratio p (López's DSR) | < 0.05 (post-Bonferroni) | birincil (multiple-testing) |

## 5. Independent Variables (parametre grid'i — KÜÇÜK TUTULDU)

| Param | Değerler | Kombinasyon | Curve-fit notu |
|---|---|---|---|
| `regime_window` (bar) | {60, 90, 120} | 3 | <60 noisy, >120 reaktif değil — literatürle hizalı dar grid |
| `regime_quantiles` | {(0.33, 0.66), (0.25, 0.75)} | 2 | İki sezgisel partition — daha fazla = curve-fit |
| `risk_low/mid/high` | {(1.00, 0.70, 0.45), (1.20, 0.80, 0.40)} | 2 | İkisi de fractional Kelly bandında |
| `lopez_alpha` | {0.5, 1.0, 2.0} | 3 | López'in önerdiği aralık |
| `dd_cap` (% account equity) | {0.20, 0.25} | 2 | Risk officer hard cap = %25 |

**Total grid = 3 × 2 × 2 × 3 × 2 = 72 kombinasyon.**

**Multiple testing düzeltmesi:** Bonferroni α' = 0.05 / 72 = **6.94e-4**. Yani tek-tek param için raw p < 6.94e-4 olmalı; aggregate karar için DSR (López) tercih edilir.

## 6. Curve-Fit ve Lookahead Şüpheleri (kendine karşı paranoya)

1. **Quantile boundary keyfi:** 0.33/0.66 vs 0.25/0.75 — küçük performans farkı bile param sınırına basıyor anlamına gelir → robustness sweep zorunlu.
2. **Volatility ölçütü ATR_pct seçildi**, RV (realized variance) veya Yang-Zhang değil. ATR fat-tail'i emer; RV daha sert. Robustness'ta RV-replication zorunlu.
3. **López α=1 default**; α=2 daha keskin deleveraging. α optimize ediliyor → tek bir α'da pozitif sonuç alıp diğerinde alamamak overfit imzası.
4. **DD_cap %25 risk_officer-set**; in-sample optimize edilmemeli (sızıntı). Eğer best param `dd_cap=0.20` ise gerçek tavan değil — bu in-sample'da random bulunan eşik olabilir.
5. **Carrier sabit (Brooks-failed-breakout v8)**: sizing iyileştirmesi sadece bu carrier'da çalışıyorsa edge sizing'den değil carrier-sizing etkileşiminden gelmiştir → cross-carrier replikasyon (pin-bar, rsi2-extreme-fade gibi 2 ek carrier) zorunlu.
6. **Lookahead test:** `regime_quantile(t)` sadece `t-1 close`'a kadarki bar'lardan hesaplanmalı. CI test `tests/test_lookahead.py::test_sizing_wrapper_lookahead` eklenecek (TODO post-pre-register).
7. **In-sample / OOS Sharpe farkı > %50 ise REJECT** (overfit kırmızı bayrağı, lessons/02-overfit-redflags).
8. **Survivorship:** `data/universe.py::build_universe(t)` delisting-aware (lessons/01-survivorship-bias). Sizing wrapper'ı carrier'ın trade akışına dokunmuyor → survivorship riski carrier'dan miras.

## 7. Backtest Setup (config-hash'i hipoteze çiviler)

```yaml
universe: all_liquid_usdt_perp_delisting_aware
period_in_sample: 2023-06-20 → 2025-06-19
period_oos: 2025-06-20 → 2026-06-19
timeframe: 1d
carrier: brooks_failed_breakout_v8 (frozen, sha = TBD-on-run)
sizing_wrapper: regime_aware_lopez_v01
fees: 7.5bps taker / -1bp maker
slippage: 5bps fixed
initial_equity: 10000 USDT
max_leverage: 3x (risk policy hard cap)
walk_forward: 3y train / 6m test / step 3m (12 dilim)
optuna_trials: 0 (NO bayesian opt — grid 72 sabit, p-hacking blocked)
seeds: [11, 23, 47, 89, 137] (param perturb için)
```

## 8. Robustness Suite (SOP-3 — TÜMÜ zorunlu)

| Test | Pass kriteri |
|---|---|
| Walk-forward 12 dilim | ≥ 8/12 dilimde ΔSharpe > 0 |
| In-sample / OOS Sharpe fark | < %30 (>%50 = REJECT) |
| Param perturb (±%10, 50 seed) | Ort. Sharpe kayıp < %25 |
| Symbol-out CV (leave-one-out) | Min OOS Sharpe ≥ %70 × full-universe Sharpe |
| Regime split (bull/bear/range, ADX+200d-MA) | ≥ 2/3 rejimde ΔSharpe > 0 |
| Stress dönemler (2024-08 Yen carry, 2025-X tail dilimleri) | MaxDD ≤ baseline MaxDD (sizing iyileşmesi tam burada beklenir) |
| Shuffle baseline (per-trade r shuffle × 1000) | p < 0.05 |
| ATR → RV replikasyon | Sharpe Δ < %20 (volatility-proxy invariance) |
| Cross-carrier replication (pin-bar + rsi2-fade carrier'larında) | ≥ 1/2 carrier'da ΔSharpe > +0.10 (carrier-sizing etkileşim değil) |
| Multiple testing | DSR p < 0.05 Bonferroni-72 post |

## 9. Beklenen p-value

- **Raw Welch t-test (paired per-trade r) p < 0.01** (single best-param için)
- **Bonferroni-72 sonrası p < 0.05** (yani raw p × 72 < 0.05 ⇒ raw p < 6.94e-4)
- **DSR (López, # of trials = 72, skewness/kurtosis düzeltmeli) p < 0.05**

Bu 3 koşulun **HEPSİ** sağlanmalı. Bonferroni sonrası anlamlılık kaybedilirse hipotez **REJECTED** (lessons/02-overfit-redflags §7).

## 10. Stop Criteria (erken-terk koşulları)

Backtest çalışırken / sonrasında aşağıdakilerden **herhangi biri** olursa araştırma terkedilir, gerekçeli arşivlenir:

1. **IS Sharpe artışı baseline'a göre < %5** → edge yok, terk.
2. **Best param uzayın sınırında** (örn. risk_low=1.20 set'in üst sınırı seçilirse) → genişletilmiş re-test gerekir; eğer genişletme sonrası da sınırdaysa, kararlı optimum yok = REJECT.
3. **WF dilim varyans CV > %100** → instabil edge, REJECT.
4. **Bonferroni-72 sonrası p ≥ 0.05** → REJECT.
5. **Cross-carrier replication 0/2 carrier'da pozitif** → sizing-carrier etkileşim, generalize etmiyor = REJECT.
6. **Lookahead testi başarısız** → derhal stop, code-level bug fix, yeniden başla (eski sonuçları silmeden).
7. **Regime-yüksek bucket'ında trade < 50** → sample insufficient, conclude inconclusive (REJECT veya DEFERRED).

## 11. Reproducibility

Backtest run'ı şu üçlüyü kaydeder:
- `git_hash` (carrier + sizing wrapper kodu)
- `config_hash` (yaml SHA256)
- `data_hash` (DuckDB snapshot + delisting set SHA)

Aynı üçlü ile bit-identical sonuç üretilmelidir. CI: `tests/test_reproducibility.py::test_sizing_wrapper_v01`.

## 12. Carry-out Plan (kabul edilirse Lab'e ne devredilir)

- `configs/strategies/sizing_wrapper_regime_lopez_v01.yaml` (DRAFT — insan onayı sonrası)
- `reports/research/sizing-regime-lopez-v01-<date>.html`
- Tournament önerisi: carrier-sabit, sizing-değişken champion-challenger (Lab Scientist'in haftalık turnuvasında).

## 13. Çelişki Notu (kendine karşı)

- Bu hipotez ÖNCE bir gerçek **promote edilmiş canlı carrier**'a ihtiyaç duyuyor. Memory state: "Researcher: promote bot YOK" — v48'e kadar abort, lab'de grimes-abc en yakın. Yani backtest için carrier seçimi zorlu: `brooks_failed_breakout_v8` IS-only candidate, OOS gate'i geçmemiş. Çözüm: hipotez **carrier-agnostic** test edilecek, üç IS-candidate (brooks_v8, pin-bar, rsi2-fade) üzerinde paralel. Hiçbiri promoted değil → sonuçlar "sizing wrapper'ın sızıntı varsa veya yoksa edge'i" hakkında konuşur, "canlı sermaye için tavsiye" demez.
- Live v14 carrier'ı için sizing wrapper retro-uygulanmaz (live config insan-onayı gerekir, ADR-002).

---

**Pre-registration hash:** Bu doc commit edildiğinde `git rev-parse HEAD` ile dondurulur. Sonraki herhangi bir değişiklik = yeni doc + `supersedes`.
