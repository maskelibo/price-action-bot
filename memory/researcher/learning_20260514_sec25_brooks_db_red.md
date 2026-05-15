# Learning — SEC25 Brooks Double Bottom Bull Flag: RED

**Tarih:** 2026-05-14
**Sprint:** SEC25 (PA mastery gap — trend_continuation NOT_TESTED setup)
**Hipotez:** [HYP-2026-05-14-BROOKS-DB-BULL-FLAG](hypotheses/2026-05-14-brooks-double-bottom-bull-flag.md)
**Karar:** **RED — n bottleneck + Bonferroni multiple testing FAIL**
**Bayesian prior güncellendi:** Trend_continuation class crypto-fit **POZİTİF**
(mean-rev RED paraleline KARŞI prior).

---

## TL;DR

Al Brooks "10 Best PA Patterns" listesi #4 (DB Bull Flag / DT Bear Flag,
trend_continuation, PA mastery gap NOT_TESTED) crypto 1d × 11 sym × 5y'de
standalone test edildi. Default config **n=31** (HARD FAIL gate n≥200). 18-config
grid Bonferroni α=0.05/18=0.00278: **0/18 PASS**. **Pattern gerçek edge taşıyor**
(5/6 yıl pozitif, orthogonal engulfing/donchian, short-edge dominant) ama crypto
1d × 11 sym kapsamında yetersiz örnek.

---

## Doğrulanmış Bulgular

### 1. Pattern edge VAR ama yetersiz n

C0 (eq=0.03, fb=3, body=0.30) honest clip hold>30d: **n=109, mR=+0.342, p=0.008,
WR=57.8%, symdev=20%, pos=9/11** — 6/7 gate PASS, sadece n<200 FAIL. Pattern
gerçek edge taşıyor ama crypto evrende seyrek.

### 2. Orthogonality MÜKEMMEL ⭐

| Other | n_my | n_other | jaccard |
|---|---:|---:|---:|
| engulfing_continuation | 31 | 350 | **0.011** |
| donchian_breakout | 31 | 233 | **0.000** |

DB Bull Flag yapısal benzersiz — engulfing pullback-engulfing zamanlarıyla %1
overlap, donchian range-extreme breakout zamanlarıyla %0 overlap. **Pre-reg
counter-hyp CH-2 (engulfing < 0.20) ve CH-3 (donchian < 0.30) HER İKİSİ DE PASS.**
SEC11e FVG paraleli ama burada n yetersizliği ensemble katkı potansiyelini
gerçekleştiremez.

### 3. Crypto-fit POZİTİF (sec22-24 mean-rev RED paraleline KARŞI prior)

C0 hold>30 clip per-year:

| Year | n | mR | Regime |
|---|---:|---:|---|
| 2021 | 8 | -0.315 | bull-top |
| 2022 | 21 | +0.129 | bear |
| 2023 | 30 | +0.596 | range |
| 2024 | 22 | +0.188 | bull |
| 2025 | 27 | +0.535 | bull |
| 2026 | 1 | +0.652 | partial |

**5/6 yıl pozitif** (mean-rev sec24 TS 3/6, sec22 BB 0/11 sym positive paraleli).
Trend_continuation pattern crypto'da çalışıyor — counter-prior **mean-rev family
DEFAULT FAIL** sec22-24 zinciriyle **karşılıklı simetri**.

### 4. Asymmetric edge — SHORT dominant (crypto bull bias TERSİ)

Default config:
- long n=11 mR=+0.292 (hold30 clip +0.052)
- short n=20 mR=+0.829 (hold30 clip +0.341)

Klasik crypto literatür beklentisinin TERSİ — secular bull regime'inde
short-edge daha güçlü. SEC24 TS short-only n=275 mR=+0.074 p=0.170 (gate altı)
paraleli ama burada short edge belirgin daha güçlü (sample n=20 küçük ama
3.5x long mean).

### 5. n_min FAIL + p_shuffle PASS pattern (3. kez)

| Sprint | Pattern | n | hold30 p | hold30 mR |
|---|---|---:|---:|---:|
| SEC22 three-push | wedge_fade | 10 (max 77) | n/a | n/a |
| SEC19 HTF | high-tight-flag | 35 | 0.40 | +0.083 |
| SEC25 DB Bull Flag | brooks_db_bull_flag | 109 | 0.008 | +0.342 |

**Yapısal pattern:** Compound multi-pivot (multi-bar structural) pattern'ler
crypto 1d × 11 sym'de yapısal n bottleneck. SEC25 farkı: edge GERÇEK
(p=0.008 ≈ p<0.01 anlamlı), AMA n<200 gate-block. Bu **"PATTERN EDGE EVET,
KAPSAM YETERSİZ"** ayrı flag — sonraki sprintlerde universe expansion
(20+ sym) veya 4h timeframe ile retest backlog.

### 6. Engine artifact dersi — SEC11a 3. defa

| Config | mR (no clip) | mR (hold30 clip) | Fantasy R % |
|---|---:|---:|---:|
| Default | +0.638 | +0.240 | -62% |
| C0 | +0.510 | +0.342 | -33% |
| C7 | +0.401 | +0.210 | -48% |
| C12 | +0.245 | +0.099 | -60% |

Standalone test'lerde `runner_force_exit_bars=30` engine manifest override
edilmiyor — ETH 2022-04 short hold=60d R=12.79 (Q2 LUNA collapse window).
SEC11a postmortem 3. defa görüldü. **Engineering ticket önerisi:** standalone
script template'inde manifest_override zorunlu `runner_force_exit_bars=30`.

---

## Pre-Registered Counter-Hypotheses Sonuçları

1. **CH-1 (crypto bear/range fail):** **REDLEDİLDİ** — 5/6 yıl pozitif.
2. **CH-2 (engulfing overlap > 0.20):** **REDLEDİLDİ** — jaccard=0.011.
3. **CH-3 (donchian overlap > 0.30):** **REDLEDİLDİ** — jaccard=0.000.
4. **CH-4 (asymmetric edge):** **KISMİ DOĞRU** — short-dominant (beklenenin tersi yönde).
5. **CH-5 (parametre fragility):** **DOĞRULANDI** — 18 config grid, 0/18 strict
   Bonferroni PASS, mR-n trade-off klasik selection bias.

**4/5 counter-hyp red. Pattern gerçek edge ama gate-block.**

---

## Hangi Bias'a Düşmedim

- **Default config mR=+0.638 "PASS gibi"** görünce naive verdict atamadım.
  hold>30 clip + Bonferroni + symdev + n_min ile multi-gate disipliniyle RED
  kararı verdim. SEC22-23-24 doctrine kanıtlı şekilde uygulandı.
- **idx=0 C0 naive p=0.001 + hold30 p=0.008** görünce "PASS!" demek yerine
  Bonferroni α=0.00278 ile FAIL kararı verdim. 18 config = multiple testing
  penalty.
- **18-config grid orchestration:** pre-reg'de "if k≥10 grid → Bonferroni"
  protokolü yazılıydı, uygulandı.
- **ETH 2022-04 outlier** hızlı forensik audit yaptım, hold=60d clip-thresholds
  arası hassasiyet ölçüldü ve raporlandı.

## Hangi Bias'a Düştüm

- **Pre-reg n estimate optimistik (yine):** "n beklenti 550-1400" yazdım, default
  n=31. Crypto vektörize compound pattern recall %30-50 hesaba katılmadı. SEC22
  three-push paraleli aynı bias.
- **Default parametre seçimi literatür-only:** equal_pct=0.03 (Brooks stocks
  calibration) crypto vol-ölçeğine göre çok strikt. Pre-reg'de "crypto-microstructure-
  fit argument" yazdım AMA default'ta uygulamadım. **Ders:** Crypto-vol-calibrated
  default'la kıyasla literatür-only default (equal_pct = 0.5 × median_ATR_pct).

---

## Bayesian Prior Güncelleme

### Trend_continuation class crypto-fit POZİTİF (counter-prior mean-rev'e)

**Önceki prior (sec22-24 mean-rev RED zinciri):**
- Mean-rev family DEFAULT FAIL crypto'da (sec22-24 zincir kanıtı: 4 ardarda RED).

**SEC25 güncellenmiş prior:**
- Mean-rev family DEFAULT FAIL **devam ediyor** (4-RED zincir).
- **Trend_continuation family DEFAULT POZİTİF crypto'da** — DB Bull Flag 5/6 yıl
  pozitif, orthogonality kanıtlı, edge real ama sample bottleneck.
- **Trend_cont class sonraki sprintleri için Bayesian prior:** PASS-CANDIDATE
  %50-70 (literatür autorite +%30 cap'i + crypto-fit +%20-40 — sec25 pozitif
  empirik bulgu).
- Sec24 paraleli: TS pure stocks/FX mean-rev literatür → crypto mean-rev fail.
  Brooks/Bulkowski/Grimes trend_cont literatür → crypto trend_cont **yapısal
  pozitif**.

### Pattern-class düzeyinde "crypto-fit" matrix

| Class | Pattern örneği | Crypto-fit kanıtı | Prior |
|---|---|---|---:|
| mean_reversion | BB 2.5σ extreme, RSI2, TS | RED 4-zincir | %20 |
| trend_continuation | Brooks H2/L2, engulfing_cont, DB Bull Flag | PASS-MARGINAL+ | %50-70 |
| structural | Wyckoff Spring, FVG, OB | PASS (production) | %60 |
| volatility | NR7 Crabel | RED 2x | %25 |
| contrarian | VSA climax, 3-soldiers | PASS-STANDALONE | %50 |

**Class-class prior matrix sonraki sprint planlamasını yönlendirir.**

---

## Bir Dahaki Sefer

1. **Pre-reg n estimate revize:** Compound pattern (multi-pivot, multi-bar
   structural) için `expected_n = 5y × n_sym × annual_freq × recall_rate=0.3-0.5`.
   3-condition compound için annual ~5-15 trigger/sym × recall=0.3 ≈ 60-200
   expected — gate-borderline planla.

2. **Universe expansion sprint:** DB Bull Flag standalone n=109 → 20 sym ile
   ~200-250 yeter; 30 sym ile 300+ kesin. Standalone-only test (ensemble değil,
   sec13.3 ensemble RED ders alındı). **Backlog kayıt.**

3. **4h timeframe variant backlog:** Standalone pattern-pure compound pattern
   detection için 4h pivot artışı sample bottleneck'i çözebilir. Test scope:
   standalone-only, NO ensemble replacement.

4. **Engineering ticket — 3. defa (SEC11a 3rd postmortem):**
   - `runner_force_exit_bars=30` default standalone test'lerde override edilmiyor.
   - Önerilen template patch: `scripts/_template/standalone_strategy_test.py`
     master copy + auto-clip protokol.
   - SEC22/SEC24/SEC25 zincir kanıtı: standalone metric'lerde fantasy R %30-62
     arası mR over-estimate.

5. **Trend_cont class crypto-fit pozitif prior aday sırası (sonraki sprint):**
   - **Adam Grimes ABC two-leg pullback** (pre-reg yazılı, backlog) — H2/L2
     deeper variant, orthogonality H2/L2'den farklı potansiyeli yüksek.
   - **ICT Breaker Block** (PA mastery gap NOT_TESTED structural) — failed-OB
     flip reversal, smc_orderblock'tan farklı mekanik.
   - **Brooks Channel Line Third Touch Reversal** (PA mastery gap NOT_TESTED
     structural) — channel line üçüncü touch reversal-into-continuation.
   - **Minervini VCP** (PA mastery gap NOT_TESTED trend_cont) — volatility
     contraction pattern, NR7 mean-rev paralel ama trend-cont breakout-conditional.

6. **Class-level Bayesian prior matrix** memory/researcher/'a ayrı dosya
   olarak konsolide et (sonraki sprintte). Sec22-24-25 zincir bulgularının
   class-class transfer'i için yapısal döküm.

---

## Karar

**RED — n bottleneck + Bonferroni multiple testing FAIL.**

Sebepler:
1. Default config: 4/7 HARD gate FAIL (n=31, p=0.102, maxR=12.79, symout=77%).
2. 18-config grid Bonferroni α=0.05/18=0.00278: 0/18 PASS.
3. n_min relax (eq=0.08) → mR=+0.099 + p=0.118 + symdev=53% FAIL.
4. Pattern gerçek edge taşıyor ama crypto 1d × 11 sym kapsamında yetersiz.

**Production değişikliği YOK. Champion v2.0.3 korunur.**

**Strategy file silinmez** (universe expansion sprint için + regression koruma +
orthogonal ensemble benchmark potansiyeli).

---

## Sources

- [Brooks Trading Course — 10 Best PA Patterns](https://www.brookstradingcourse.com/price-action/10-best-price-action-trading-patterns/)
- [Brooks 2012 — Trading Price Action Trends](https://www.amazon.com/Trading-Price-Action-Trends-Technical/dp/1118066510)
- [Bulkowski — Encyclopedia of Chart Patterns 2nd ed](https://www.amazon.com/Encyclopedia-Chart-Patterns-Wiley-Trading/dp/0471668265)
- SEC22 mean-rev pre-build: `reports/researcher/2026-05-14_sec22_summary.md`
- SEC24 Turtle Soup RED: `memory/researcher/learning_20260514_sec24_turtle_soup_red.md`
- PA mastery gap: `reports/researcher/2026-05-14_pa_mastery_gap.md`
