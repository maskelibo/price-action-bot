---
doc_id: researcher-20260602T143000-cross-sectional-rs-d1-dollar-neutral-low-corr-to-vsa
doc_type: hypothesis
agent_id: researcher
created_at: 2026-06-02T14:30:00Z
status: PROPOSED
confidence: low
depends_on:
  - researcher-20260602-htf-continuation-diversifier   # falsified — explicit next-step pointer to cross-sectional / dollar-neutral
  - researcher-20260601-smc-continuation-baseline      # 4 SMC mechanisms all RED on bar-OHLCV
  - researcher-20260601-fabio-orderflow-valuearea-crypto # OHLCV-proxy direction = ~random
requested_review_from: [lab_scientist, risk_officer, adversary_engineer]
tags: [hypothesis, cross_sectional, dollar_neutral, diversifier, low_corr, vsa]
supersedes: null
---

# Hypothesis: HYP-2026-06-02-xs-rs-d1-dn

## 1. Iddia (pre-registered, measurable)

Üzerinde çalıştığımız 15-sembol kripto evreninde, 1D timeframe'de, **cross-sectional rank-based dollar-neutral mean-reversion** (top quintile = SHORT, bottom quintile = LONG by 5-bar trailing return; haftalık rebalance; her bacak eşit dolar) — son 3 yıllık veri üzerinde aşağıdaki **sayısal eşiklerin TAMAMINI** geçer:

| Metrik | Eşik | Gerekçe |
|---|---|---|
| Gross direction null (per-symbol leg shuffle, 200 seed) | `p_gross < 0.05` | Mekanizma rastgele yön mü? |
| Net mean R per trade (55bps round-trip + 5bps slip per leg) | `mean_R_55 > +0.02` | Modest, leg-bazında pozitif |
| Bootstrap daily-Sharpe 95% CI | **CI lower bound > 0** | "Uncorrelated noise" tuzağına ZORUNLU çift kapı (2026-06-02 learning) |
| Annualized net Sharpe (calendar-day) | `> 0.8` | Dollar-neutral için modest hedef |
| MaxDD (account equity base, NOT cumulative-PnL base) | `< 25%` | CT-RSK-01 audit kuralı |
| `|rho_daily|` to live `vsa_climax_test` (90-day rolling avg) | `< 0.25` | Gerçek diversifier kapısı |
| Walk-forward positive 6m dilim oranı | `≥ 8/12` | Tek dönem baskınlığı yok |
| Top-5% R-share | `< 35%` | Outlier-driven değil |
| BH-FDR survivor (over all config trials) | `≥ 1 config` | Multiple-testing düzeltmesi |

**TÜMÜ geçmeli — tek başarısız metrik = REJECT.**

## 2. Mekanizma + Null (Popper)

**Mekanizma iddiası:** Kripto kısa-ufuk (3-10 gün) cross-section'da **anti-momentum** vardır — son 5 günün en güçlüleri ortalamaya geri döner, en zayıfları ralliye geçer. Bu, tek-sembol VSA climax fade'in yatay genişlemiş hali; ama beta'sı BTC'den izole olduğu için VSA ile düşük korelasyonlu.

**Null hipotezler (her biri ayrı ayrı iddiayı çürütür):**
1. **H0a:** Per-symbol direction shuffle bu sırayı yenmez (`p_gross ≥ 0.05`). → mekanizma yön bilgisi taşımıyor.
2. **H0b:** Gross edge var ama 55bps fee + 5bps slip kazandığı her şeyi yer (`mean_R_55 ≤ 0`).
3. **H0c:** Net positive ama bootstrap day-Sharpe CI 0'ı içerir → "uncorrelated noise" tuzağı (2026-06-02 HTF diversifier dersinin tekrarı). REJECT.
4. **H0d:** Sinyal sadece "long-alts / short-BTC" beta'sı kılığında — BTC-tahmini başka bir hipotez. → BTC-bacağı dışarıda bırakılıp testle: edge >%50 düşerse iddia çürür.
5. **H0e:** `|rho_daily|` to vsa_climax_test > 0.40 → diversifier değil, aynı şeyin başka kılığı.

## 3. RAG Gerekçesi

- **[López de Prado] (#1):** "PBO > 0.5, IS/OOS Sharpe oranı > 3, parametre/örnek > 1/30" — bu hipotezde **N_obs = 15 sym × ~1095 gün = ~16k bar**, parametre uzayı **48 config** (aşağıda), oran 48/16400 ≈ 0.003 << 1/30 → kabul edilebilir; ama PBO testi zorunlu.
- **[Chan] (#9):** "Sharpe-based gating, pair/portfolio için OOS Sharpe > 1.2." Bizim eşik 0.8 (tek-strateji-stand-alone) çünkü amaç **diversifier**, stand-alone değil; ama bootstrap CI 0'ı dışlamalı.
- **[Market Structure Order Flow] (#6):** OB/CHoCH/BOS gibi sinyaller "high mechanik testability"; cross-sectional rank de mekanik (vectorized, deterministik) → lookahead-safe vectorize edilebilir.
- **[Bulkowski candlestick stats] (#2, #8, #10):** Single-bar yön istatistikleri yan piyasada %54-64 — bu da bizim CT'mizin **eşik üstü olmak ZORUNDA olduğu seviye**. Bulkowski oranlarını yenmeyen bir cross-sectional kural pratikte değersiz.
- **[Kaufman] (#7):** Donchian breakout "trending market, choppy'de %20-40 DD" — bu hipotez tam ZIDDI (anti-trend cross-section); Kaufman'ın trend-following whipsaw'unun karşı bacağı.

**Karşı-RAG (kasıtlı):** Bulkowski Mat Hold #10 %74 continuation; eğer bu doğruysa anti-momentum mekanizmamız tam ters yönde olmalı. Bulkowski equity-bazlı, kripto perp'te volatilite + funding asimetrisi farklı; ama eğer cross-section sonuçlarımız "continuation kazanır" derse anti-momentum iddiası çürür → revize edilmeyecek, REJECT edilecek.

## 4. Curve-Fit Şüphesi (KASITLI: prompt gereği)

Bu hipotezi reddetmem için **3 ayrı kırmızı bayrak** halihazırda mevcut — pre-register ediyorum ki sonradan "ben farkındaydım" dememekten kaçınayım:

1. **N=15 sembol cross-section için ÇOK KÜÇÜK.** Top quintile = 3 sym, bottom quintile = 3 sym. Tek-sembol noise quintile compoziyonunu dalgalandırır → "ranking" yarı-gürültü. Akademik cross-section çalışmaları N=500+ ile çalışır. Bu hipotezin pratikte çalışsa bile sınır N etkisi olabilir.
2. **"Low-rho + zero-Sharpe = diversifier" tuzağı taze ders (2026-06-02 HTF).** Bu hipotez tam o yapıdadır (dollar-neutral, BTC'den izole). Bu yüzden gate'e "bootstrap CI lower bound > 0" eklendi. Bu kapı geçmezse YOZGAT REJECT, iterate yok.
3. **Anti-momentum hipotezi Mat Hold/Marubozu continuation Bulkowski istatistikleriyle KARŞIT.** Eğer cross-sectional anti-momentum kazanırsa Bulkowski continuation kuralları kripto'da çürüyor demektir; bu büyük bir iddia. Bayes prior düşük: P(real edge before data) ~ 15%.

**Curve-fit savunması:** Parametre uzayı kasten kaba — 4 lookback × 3 holding × 2 quintile × 2 leg-balance = **48 config**. Optuna kullanılmıyor (fine-grained search yok). 0.01 adımlı parametre yok. Best param'in kenar değerde olmaması zorunlu — kenar değerdeyse REJECT.

## 5. Independent Variables (parametre uzayı — kaba)

| Var | Değerler | n |
|---|---|---|
| `lookback_days` (rank tabanı) | {3, 5, 8, 13} | 4 |
| `holding_days` (rebalance period) | {5, 10, 21} | 3 |
| `quintile_pct` | {0.20 (top/bot 3 sym), 0.33 (top/bot 5 sym)} | 2 |
| `leg_balance` | {equal_$ (true DN), equal_vol (vol-scaled)} | 2 |

**Toplam: 48 config.** BH-FDR ile düzeltme zorunlu. Optuna YASAK.

## 6. Dependent Variables (önceden seçilmiş — değiştirilemez)

Primary: `mean_R_55`, calendar-day Sharpe (bootstrap CI dahil), `|rho_daily|` to vsa_climax_test.
Secondary: MaxDD (equity-base), WF positive-month oranı, top-5% R-share, BH-FDR survivor sayısı.
Artifact-only (karar verici DEĞİL): win rate, hit count, profit factor.

## 7. Beklenen p-value + Tetlock Calibration

- **Pre-registered prediction:** `P(any config passes all gates) = 15%`. P(net edge yok ama gross direction edge var) = 40%. P(gross edge bile yok = clean RED) = 45%.
- **BH-FDR threshold:** 48 trial, q=0.05 → en güçlü trial p < 0.05/48 ≈ 0.001 olmazsa zayıf survivor sayısı düşer.

## 8. Stop Criteria (HARD)

Aşağıdakilerden HERHANGİ BİRİ olursa → backtest derhal durdurulur, REJECT yazılır, iterate AÇILMAZ:

- **S1:** İlk pilot config (lookback=5, holding=10, q=0.20, equal_$) `mean_R_gross < 0` → mekanizma yok, 48 config'i koşturmaya gerek yok.
- **S2:** Best config `p_gross > 0.20` → direction shuffle null'ı yenemiyor.
- **S3:** Hiçbir config'in bootstrap day-Sharpe 95% CI lower bound > 0 (HTF dersinin tekrarı).
- **S4:** Best param `lookback ∈ {3, 13}` ucunda VE Sharpe gradient kenardan kenara monotonik → parametre uzayı yanlış seçilmiş; ya YENİDEN tasarla ya REJECT (iterate sayılır ama hipotezi YENİDEN pre-register et).
- **S5:** BTC-bacağı dışarıda bırakıldığında edge >%50 düşerse → mekanizma "long-alts/short-BTC" beta'sı, anti-momentum değil. REJECT.
- **S6:** `|rho_daily|` to vsa_climax_test > 0.40 → diversifier değil. REJECT (ama mekanizma kendi başına geçerse ayrı bir hipotez yazılabilir, BU hipotez kapanır).

**Iterate budget: 1 versiyon (S4 senaryosunda).** Aksi halde mekanizma çürümüş = arşiv.

## 9. Reproducibility

- git hash: HEAD @ 2026-06-02 (audit-hardreview-20260528 branch)
- data source: `data/futures_perp.duckdb` 1d bars, 15-sym universe, **survivorship-corrected** (delisting tarihinden sonra dahil edilmiyor)
- backtest engine: `src/price_action/backtest/engine.py` vectorize path
- random seeds: `range(200)` for shuffle null, sabit
- output: `reports/research/xs_rs/v1_baseline.md` + `reports/research/xs_rs/v1_dump.json`

## 10. Risk Officer Pre-Check Notları

- Dollar-neutral ≠ risk-neutral. Bir bacak likidite kuruyabilir (delisting). Bu yüzden delisting halinde diğer bacağı OTOMATİK FLATTEN edilmiş varsayım.
- Funding asymmetry: short bacak funding ödüyor olabilir → her gün -0.01% × short_notional fee'ye eklendi (round-trip 55bps üstüne).
- Kaldıraç max 1x (dollar-neutral = 1L + 1S ≈ 2x gross, 0 net) — `configs/risk.yaml::leverage.max_leverage_per_symbol = 3` altında.

## 11. Sonuç Sahibi

- Backtest yürütücü: researcher (kendisi)
- Robustness checks: zorunlu SOP-3 (walk-forward, param perturb ±%10, symbol-out CV, regime split, stress periods, shuffle baseline, BH-FDR)
- Promotion: ASLA bu raporla doğrudan deploy yok; Lab tournament'a aday olarak teslim, drift takibi 30 gün.

## 12. Decision Field (DOLDURULACAK — backtest sonrası)

- [ ] PROMOTE — tüm gate'ler ✓
- [ ] ITERATE — sadece S4 senaryosunda (1 versiyon)
- [ ] REJECT — gerekçe: [doldurulacak]
- [ ] DEFERRED — edge gerçek ama portföy kapasitesinde değil
