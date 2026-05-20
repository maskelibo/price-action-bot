# Learning — SEC-S5 MR Pool Sprint (2026-05-17)

**Sprint:** Mean-Reversion pool ekleme — 15m R4 ensemble diversification (Yol D).
**Status:** RED — all 3 hypotheses fail pre-registered gate.
**Reports:**
- `reports/researcher/2026-05-17_sec_s5_mr_pool_standalone.md`
- `reports/researcher/2026-05-17_sec_s5_mr_ensemble_retest.md`
- `reports/researcher/2026-05-17_sec_s5_summary.md`

## Hipotez Özeti

**Iddia:** 15m R4 (TOP-4 trend-cont) pool aylık CV %223, 20 sıfır ay, 9 neg
ay — trend-cont ağırlığından. MR pool (BB-fade + RSI-ekstrem + Range-BOF)
eklerse range/bear rejim sıfırları doldurur, neg'leri telafi eder. Hedef:
CV ≤ %100, mean ≥ %20, sıfır+neg ≤ 10/61.

## Standalone Sonuçlar (5y × 10 sym × 15m)

| Strategy | n | mR | WR% | p-value | Verdict |
|---|---:|---:|---:|---:|---|
| bollinger_fade_mr | 513 | **-0.295** | 38.4 | 0.995 | RED |
| rsi_extreme_mr | **9** | -0.501 | 22.2 | 0.800 | RED (n<<1000) |
| range_bo_failure_mr | 19,510 | **-0.169** | 43.8 | 1.000 | RED |

**3/3 standalone RED — yapısal negatif edge.**

## Ensemble Retest (Walk-Forward 34 windows)

| Senaryo | Annual | DD | r-adj | Mean/mo | CV | Zero | Neg |
|---|---:|---:|---:|---:|---:|---:|---:|
| A. R4 baseline | +1076% | -35% | 30.7 | +28.9% | 144% | 0 | 7 |
| B. R4 + BB-fade | +1073% | -35% | 30.7 | +28.9% | 144% | 0 | 7 |
| C. R4 + Range-BOF | +1088% | -35% | 31.0 | +28.1% | 145% | 0 | 7 |
| D. R4 + ALL MR | +1088% | -35% | 31.2 | +28.1% | 145% | 0 | 7 |

**MR pool effect NULL** — engine concentration cap MR trade'leri minimize
ediyor, R4 ana edge çekirdek sinyaller dominant.

## Anomali — Baseline Discrepancy

Bu retest baseline R4 (+1076% / 0 sıfır / 7 neg / CV %144) vs
RESUME.md baseline (+735% / 20 sıfır / 9 neg / CV %223).

**Olasi neden:** Cooldown setting farkı. P0 fix retest cooldown=0 override
ile (RESUME label), bu retest cooldown=15dk YAML default. cooldown=15dk
zero-trade ay sayısını dramatik düşürüyor (cooldown=0'da rapid re-entry
range/bear rejimde stop-stop-stop, cooldown=15dk pause veriyor).

**Action item:** Engineering veya analyst → SEC32 cooldown sensitivity
analizi. Production canonical baseline tekrar doğrulanmalı.

## Yan Bulgu — Directional Flip Edge

`scripts/_sec_s5_directional_flip_check.py`:

| Strategy | mR(fade) | mR(rev, fee adjusted) | WR(rev) |
|---|---:|---:|---:|
| bollinger_fade_mr | -0.295 | **+0.195** | **59.6%** |
| rsi_extreme_mr | -0.501 | +0.401 (n=9) | 66.7% |
| range_bo_failure_mr | -0.169 | +0.069 | 54.4% |

**Insight: 15m crypto'da BB outer touch + RSI extreme + reversal candle =
CONTINUATION sinyali, fade DEĞİL.** Bu Kaufman/Connors MR literatürünün
crypto 15m TF'de geçersiz olduğunu gösteriyor (high-vol intraday momentum
dominance).

**Yol G (next sprint candidate):** BB-fade flip → "BB-band-breakout-continuation"
yeni strategy. Standalone edge varsa (+0.20 mR, WR %60) TOP-4 → TOP-5 olabilir.

## Karar (Pre-Reg Discipline)

1. **3 hipotez ARCHIVE.** Standalone gate FAIL → ensemble'a sokmadan
   bilim. Sokunca da NULL effect doğrulandı.
2. **MR pool RED verdict.** "Yol D" yarın kapanmış.
3. **Yan-bulgu kayıt:** Yol G (BB-band continuation flip) yeni hipotez
   adayı — separate sprint.
4. **Baseline anomaly investigation:** cooldown setting bisik
   replay diff → SEC32 dispatch.

## Yapısal Sonuç

5 sprint zincirinden 4. RED MR aday: SEC4 (vol_risk_premium n düşük),
Sec19 inside-day-failure marjinal, ML v1/v2 RED, **bu SEC-S5 (3 yeni MR
strategy)**. **15m R4 pool trend-cont saturated, MR alpha 15m TF'de
yapısal olarak yok** (fee/slip + intraday momentum dominate).

**User mandate "aylık %25" yolu:**
- Yol D (MR pool) — RED ✗
- Yol E (1h pivot) — denenmedi (alt-TF spike sonrası MR vs trend ayrımı
  saatlik bara genişlerse fee oranı düşer, fade edge çıkabilir)
- Yol F (15m R4 ensemble re-weight) — bu retest baseline %1076 zaten >>%735
  RESUME, eğer doğrulanırsa user mandate zaten karşılanmış olabilir
- Yol G (yeni) — BB-band continuation flip standalone test

## Reproducibility

- git: (sprint commit gerekli)
- code: `src/price_action/strategies/{bollinger_fade_mr,rsi_extreme_mr,range_bo_failure_mr}.py`
- backtest: `scripts/{sec_s5_mr_pool_standalone,sec_s5_mr_ensemble_retest,_sec_s5_directional_flip_check}.py`
- cache: `data/sec_s5_mr_pool.pkl` (3.4 min build)
- hypotheses: `memory/researcher/hypotheses/2026-05-17-{bollinger-fade-mr-15m,rsi-extreme-mr-15m,range-bo-failure-15m}.md`
