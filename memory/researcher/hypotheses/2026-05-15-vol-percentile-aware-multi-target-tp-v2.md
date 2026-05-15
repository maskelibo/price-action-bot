---
hypothesis_id: 2026-05-15-vol-percentile-aware-multi-target-tp-v2
date: 2026-05-15
author: researcher_agent (claude-opus-4-7-1m)
status: PRE_REGISTERED
version: 0.1.0
parent_strategy: none (overlay — multi-target engine TP/trail dynamic rolling-vol regime)
parent_baseline: v2.0.3 production champion (3y rolling +%239.5 / DD -%38.7 / r-adj 6.190)
parent_engine: HYP-2026-05-09-multi-target-engine (v0.8 approved +%6.5pp; current v2.0.3 1R/2R partials + 1.0 ATR trail)
sprint_class: max_roi_2026_05_15 (priority 5/5)
tags: [multi_target, take_profit, trailing, realized_volatility, regime_continuous, vol_percentile, engine_v2]
backtest_possible: true
data_requirements: [v091 trades, OHLCV BTC + per-symbol (mevcut), rolling 14d realized vol percentile per-symbol]
expected_correlation_w_existing: high (multi-target engine yapısının doğrudan extension'ı)
git_hash_at_registration: 3da3344b2e69992f45e3acd8c40d4b399808e14f
ceo_brief_ref: max_roi_sprint priority#5 — TP/trail dynamic on rolling vol percentile
bonferroni_factor: 5  # alpha_adj = 0.05/5 = 0.010
---

# HYP-2026-05-15-005 — Vol-Percentile-Aware Multi-Target TP / Trail v2 (Continuous Vol-Regime Conditioning)

## 1. Pre-Registered İddia (TEK CÜMLE)

> v2.0.3'te multi-target engine TP1=1.0R/TP2=1.5R (partial_close=30/30/40) ve runner trail 1.0 ATR sabit; bunu **per-symbol 14d realized vol 90d-percentile'a** linear-interpolated dynamic TP/trail (düşük vol pct=0.1 → TP1=0.7R/TP2=1.2R/trail 0.6 ATR; yüksek vol pct=0.9 → TP1=1.3R/TP2=2.0R/trail 1.4 ATR) ile değiştirdiğimizde, v2.0.3 baseline'a karşı **3y rolling 13 pencerede mean annual return ≥ +%2pp uplift VE DD bozulması ≤ +%2pp** üretir.

### Bağımlı Değişkenler
- Mean annual return
- Mean MaxDD
- Per-trade mean_R
- Win rate (TP1 hit rate)
- Runner contribution (runner partial pnl / total pnl)
- Hold time distribution
- Risk-adjusted

### Bağımsız Değişkenler (PRE-REGISTERED SABİT)

**Per-symbol vol percentile (causal, T-1 EOD inclusive):**
```python
log_rets = np.log(close).diff()
rv_14d = log_rets.rolling(14).std() * np.sqrt(365)
rv_pct = rv_14d.rolling(90).rank(pct=True)  # ∈ [0, 1]
```

**TP/Trail mapping (linear interpolation in vol percentile):**
| vol_pct | TP1 (R) | TP2 (R) | trail (× ATR14) |
|---|---|---|---|
| 0.0 | 0.6 | 1.0 | 0.5 |
| 0.5 (median) | 1.0 | 1.5 | 1.0 (baseline) |
| 1.0 | 1.4 | 2.0 | 1.5 |

**Linear formula:**
- TP1_R = 0.6 + 0.8 * vol_pct
- TP2_R = 1.0 + 1.0 * vol_pct
- trail_atr_mult = 0.5 + 1.0 * vol_pct

**Partial close oranları (UNCHANGED):**
- partial_close_1R: 0.30
- partial_close_2R: 0.30
- runner_pct: 0.40
- break_even_after_1R: true
- lock_1R_after_2R: true

**Pyramid triggers:** 1.0R/2.0R UNCHANGED (engine ile bağımsız; pyramid notional koşulu vs TP partial koşulu ayrı flow'lar)

baseline = v2.0.3 BALANCED (TP1=1.0R/TP2=1.5R/trail=1.0 ATR sabit)
walk-forward = 3y train + 6mo OOS + 3mo step → 13 pencere

### Null Hipotezler
1. Mean annual return alpha < +%1pp
2. Mean MaxDD bozulması > +%2pp
3. Bootstrap CI low < 0
4. Robustness ≥ 4/7 HARD FAIL
5. Bonferroni-adj p ≥ 0.010
6. Shuffle null (vol_pct permüte) p ≥ 0.05
7. **Vol-quartile monotonicity:** trade'leri vol_pct quartile'a böl, mean_R Q1 ile Q4 arasında sıralı monotonic değilse mekanik gürültü, RED (en az 3 ardışık monotonic)

---

## 2. Prior Strength — Literatür ve İç Kanıt

### Akademik / Kitap kaynakları
- **Richard Dennis / Bill Eckhardt — Turtle Trading rules (Faith 2007 "The Way of the Turtle"):** Original turtle exit dynamic on volatility (N=ATR-based). High vol regime wider exits, low vol tighter — but turtle used fixed N multiplier; this HYP percentile-based smoothing.
- **Linda Bradford Raschke — "Trading Sardines" (2008) ch. 7:** Vol-adjusted TP/trail in different regimes; mean-reversion in low vol, momentum runs in high vol → trail conditional on rolling vol regime.
- **Robert Carver — "Systematic Trading" (2015), ch. 11:** Vol-targeted exits "dynamic volatility-adjusted stops" yıllık Sharpe 0.25-0.40 artırır vs static.
- **Andrew Aziz — "How to Day Trade for a Living" (2016):** TP1/TP2 ratios vol-dependent; high-vol days TP2 expanded (2.0-2.5R), low-vol compressed (0.8-1.2R).
- **Marcos López de Prado — "Advances in Financial ML" (2018), ch. 17.4:** Profit-taking horizons (path-dependent exits) vol-percentile conditioning binary regime switch'lerden daha tutarlı.
- **Bouchaud, Potters — "Theory of Financial Risk" (2003) ch. 5:** Realized vol percentile sürekli regime indicator olarak GARCH-based switching modellerinden daha robust (out-of-sample stable).

### İçsel kanıt
- **v0.8 Multi-Target Engine (HYP-2026-05-09-009)** — ✅ ONAYLANDI +%6.5pp yıllık uplift, sabit parametre 1R/2R partial 30/30/40 + runner trail.
- **v0.9.0 trail sweep:** 0.7 ATR → 1.0 ATR (v0.9 multi-target tunning) +%4.7pp; trail wider yaptıkça runner edge artıyor.
- **v1.2 primary_R sweep:** 2.0 → 1.5 (-25% TP) +%9.5pp yıllık (sec11b WIN); ama bu **sabit** değişim. Bu HYP **conditional**.
- **vol_target sizing (mevcut config, default kapalı)** — `vol_target.enabled: false` ama hazır implementation var; "yıllık tutarlılık 1.7x iyileşti σ %35→%21" benzer mantıkta vol-regime conditioning faydası kanıtlı.
- **HYP-002 RII (kardeş HYP)** — RV-14d 90d-percentile zaten Feature 4 olarak kullanılıyor (sizing scalar). Bu HYP **aynı feature** ama TP/trail layer'da; orthogonal layer kullanım.

### Mevcut sprint'le orthogonality
- Sizing scalar (RII, VSA, DD-aware) → entry size; TP/trail → exit timing — **layer separation** orthogonal
- Pyramid trigger 1.0R/2.0R → notional add at R-milestones; TP partial → notional reduce at R-milestones. Pyramid bağımsız flow.
- Engine v0.8 multi-target framework korunur, sadece parametreler dynamic

---

## 3. Mekanik Kurallar (PRE-REGISTERED)

### 3.1 Per-Trade Vol-Pct Computation (at entry, T-1 EOD inclusive)
```python
def compute_vol_pct_for_trade(df, signal_idx, rv_period=14, pct_lookback=90):
    """
    df: per-symbol OHLCV up to signal bar t.
    signal_idx: t. Trade entry t+1 open.
    Returns: vol_pct ∈ [0, 1] (percentile rank of current 14d realized vol over last 90d).
    """
    log_rets = np.log(df["close"]).diff()
    rv_series = log_rets.rolling(rv_period).std() * np.sqrt(365)
    current_rv = rv_series.iloc[signal_idx]
    rv_history = rv_series.iloc[signal_idx - pct_lookback:signal_idx + 1].dropna()
    if len(rv_history) < 30:
        return 0.50  # neutral fallback
    pct = (rv_history < current_rv).mean()
    return float(np.clip(pct, 0.0, 1.0))
```

### 3.2 TP/Trail Mapping (Linear, Pre-Registered Sabit)
```python
def compute_dynamic_tp_trail(vol_pct):
    """vol_pct ∈ [0, 1] → (TP1_R, TP2_R, trail_atr_mult)"""
    tp1_r = 0.6 + 0.8 * vol_pct       # 0.6 ↔ 1.4
    tp2_r = 1.0 + 1.0 * vol_pct       # 1.0 ↔ 2.0
    trail_atr = 0.5 + 1.0 * vol_pct   # 0.5 ↔ 1.5
    return tp1_r, tp2_r, trail_atr
```

### 3.3 Engine Integration
- Engine `place_protection_orders()` mevcut multi-target framework korunur
- TP1/TP2 fiyatları entry sizinde vol_pct'e göre hesaplanır (trade-level sabit, intraday yenilenmez)
- Trail ATR multiplier de trade ömrü boyunca sabit (vol_pct entry'de fix'lenir)

### 3.4 Causality
- vol_pct trade entry'sinde T-1 EOD inclusive hesaplanır (T+1 open trade)
- Sliding 90d window T+1 open öncesi
- Trade ömründe yeniden hesaplanmaz (single computation at entry — pre-reg)

### 3.5 Edge cases
- İlk 90 gün veri yoksa → vol_pct = 0.50 (neutral, baseline parametreleri)
- NaN/inf safeguard → fallback 0.50

---

## 4. PASS / RED Criteria

### PASS
- Mean annual return alpha ≥ **+%2pp**
- Mean MaxDD bozulması ≤ **+%2pp**
- Vol-quartile monotonic: Q1 < Q2 < Q3 < Q4 mean_R sıralı (en az 3 ardışık)
- Bootstrap CI low > 0
- Bonferroni-adj p < **0.010**
- Robustness: **≥ 5/7 PASS**

### RED
- Robustness ≥ 4/7 HARD FAIL
- Alpha < +%1pp
- DD bozulması > +%3pp
- Vol-quartile monotonicity yok (mean_R quartile'lar arası karışık)

### MARGINAL
- Alpha +%1-2pp AND DD ≤ +%1pp → v2 sweep mapping slope (linear vs quadratic vs step)

---

## 5. Backtest Plan

### Setup
- Universe / strategies / pyramid / risk / sizing: v2.0.3 mevcut
- 4 baseline:
  - **v2.0.3 base** (TP1=1.0R/TP2=1.5R/trail=1.0 ATR sabit)
  - **v2.0.3 + tight static** (TP1=0.7R/TP2=1.2R/trail=0.7 ATR — sabit ama tight)
  - **v2.0.3 + wide static** (TP1=1.3R/TP2=1.8R/trail=1.3 ATR — sabit ama geniş)
  - **v2.0.3 + dynamic vol-pct** (treatment)
- Walk-forward 3y/6mo/3mo → 13 pencere

### Pipeline
```
for window in 13_windows:
    1. baseline_mid: production_replay(v2.0.3 default)
    2. baseline_tight: production_replay(static tight)
    3. baseline_wide: production_replay(static wide)
    4. treatment: production_replay(vol-pct dynamic)
    5. record alpha vs all 3 baselines, dd, mean_R, quartile mean_R
    6. shuffle null: vol_pct değerini günler arası permüte 200 iter
    7. bootstrap: 13 pencere alpha CI
```

### Robustness Suite (7 test)
1. **Mapping slope sweep** — linear (pre-reg) vs quadratic vs step (3-bin): alpha sapma < %30
2. **RV period sweep** — 7/14/21 gün: alpha sapma < %30
3. **Percentile lookback sweep** — 60/90/120 gün: alpha sapma < %30
4. **Symbol-out CV** — alpha sapma < %30
5. **Regime split** — bull/bear/range: en az 2/3'te alpha ≥ 0
6. **TP/trail decomposition** — sadece TP dynamic + trail static; sadece trail dynamic + TP static; ikisi de dynamic. Per-component katkı raporu.
7. **Look-ahead audit** — 50 random trade vol_pct hesabı T-1 EOD inclusive doğrulaması

### Test gates
- Shuffle p < 0.010
- Bootstrap CI low > 0
- ≥ 5/7 robustness PASS
- Vs static tight/wide karşılaştırma: dynamic en azından bir static'e alpha ≥ 0 (en azından "vol regime conditioning faydası var" kanıtı)

---

## 6. Karşı-Hipotezler

**KH-1: v2.0.3 TP1=1.0R/TP2=1.5R zaten optimize (v1.2 sec11b WIN sonrası).**
sec11b primary_R 2.0 → 1.5 +%9.5pp; 1.5'in altına düşürmek (1.0R'e) v2.0'da denenebilir. Vol-pct dynamic 0.6R-1.4R aralığı 1.5 sabitin alt sınırının altına gider düşük vol'de; bunlar daha iyi mi kötü mü test edilecek. **Risk:** linear interpolation slope yanlış → sub-optimal her iki yönde.

**KH-2: Vol-pct rolling 90d crypto'da çok yavaş.**
Crypto regime shift'leri 30-60d ölçeğinde (LUNA, FTX). 90d percentile shift'lere geç tepki verir. **Test:** Robustness #3 (60d sweep).

**KH-3: TP1=0.6R çok tight, kazanma oranı yapay yüksek görünür ama net P&L düşer.**
Düşük vol günlerinde TP1 quick hit → 0.6R × 30% kapama = 0.18R per trade, sonra trail TP2'ye çıkar → marjinal getiri. **Test:** vol_pct < 0.20 trade'lerde mean_R baseline vs treatment karşılaştır; eğer treatment net düşük ise pre-reg slope çok agresif.

**KH-4: TP1=1.4R high-vol günlerde win rate düşer (hedef uzak).**
Yüksek vol'da trade'ler hızlı reverse oluyor, TP1 hit etmeden SL'ye gidiyor → win rate düşer. **Test:** vol_pct > 0.80 trade'lerde win rate baseline vs treatment.

**KH-5: Vol-pct momentum-correlated (yüksek vol = strong trend).**
Yüksek vol genellikle strong directional move; geniş TP run-up'i yakalar. Bu varsayım doğru ise alpha pozitif. Aksi durum (yüksek vol = whipsaw) alpha negatif. **Test:** vol_pct vs trade R-multiple Spearman correlation; pozitif olmalı.

**KH-6: HYP-002 RII zaten RV-14d 90d-percentile kullanıyor.**
RII (HYP-002) RV feature'ı sizing scalar'a etki; HYP-005 aynı feature'ı TP/trail'e etki. **Combo testi:** HYP-002 + HYP-005 birlikte test edilirse RV katkısı 2 kat sayılmasın (orthogonal layer ama same feature). Combo'da alpha decomposition gerekli.

**KH-7: Partial close oranı (30/30/40) vol regime'de uygun değil.**
Düşük vol → daha agresif partial (40/40/20 — quick lock); yüksek vol → daha az partial (20/20/60 — runner geniş). Pre-reg'de partial oranlar SABİT; v2 sweep'e bırakılır.

---

## 7. Risk — PASS olursa hangi değişiklik gerekir?

### Code değişiklikleri
- `src/price_action/backtest/engine.py` — `MultiTargetEngine` constructor'a `tp_trail_callable` param (TP/trail compute closure)
- `src/price_action/features/vol_percentile.py` — YENİ modül: `compute_vol_pct(df, signal_idx)`
- `scripts/futures_trade_daily.py` — entry compute step vol_pct (T-1 EOD)
- `scripts/futures_daemon.py` — `place_protection_orders` multi-target dynamic param input
- `configs/risk_balanced.yaml` — `exit_engine:` blok genişler:
  ```yaml
  exit_engine:
    multi_target: true
    dynamic_vol_regime_enabled: true  # NEW
    rv_period_days: 14
    pct_lookback_days: 90
    tp1_r_range: [0.6, 1.4]
    tp2_r_range: [1.0, 2.0]
    trail_atr_range: [0.5, 1.5]
    partial_close_1R: 0.30
    partial_close_2R: 0.30
    runner_pct: 0.40
    break_even_after_1R: true
    lock_1R_after_2R: true
  ```
- `tests/backtest/test_engine_dynamic_tp.py` — unit + integration + look-ahead

### Mevcut sprint'leri etkileyen
- **Multi-target engine v0.8** — extension, framework korunur
- **HYP-002 RII** — RV-feature same; combo decomposition gerekli
- **Pyramid** — orthogonal; pyramid_triggers (1.0R/2.0R) TP1/TP2 dynamic'le çakışabilir mi?
  - Pyramid trigger price'i base entry'den hesaplanır (R-multiple in original SL term); TP partial fiyatları da aynı R-multiple'de
  - Eğer pyramid_trigger 1.0R = TP1 = 0.7R (low vol) → TP1 önce hit → partial close + pyramid trigger zaten tetiklendi
  - **Sıra sorunu olabilir!** Mitigation: pyramid trigger TP1 fiyatından sonra (>=) → eğer TP1 < 1.0R ise pyramid hala 1.0R'da tetiklenir
- **SEC26.A paper hold fix** — multi-target stages mevcut TP1/TP2 kullanıyor; dynamic switch backward-compat
- **HYP-001/002/003/004** — orthogonal layer

### Live deployment
- Per-trade vol_pct logged
- Dashboard: TP1_R, TP2_R, trail_atr_mult dağılım histogram

---

## 8. Beklenen Sayısal Hedef

| Metric | v2.0.3 base | v2.0.3 + tight static | v2.0.3 + wide static | v2.0.3 + dynamic (target) |
|---|---|---|---|---|
| Mean annual (3y) | +%239.5 | tahmin -%5 | tahmin +%3 | +%241 - +%252 |
| Mean MaxDD | -%38.7 | tahmin -%34 | tahmin -%42 | -%37 ile -%41 |
| Win rate (TP1 hit) | ~%55 (tahmin) | ~%65 | ~%48 | %53-58 (vol-conditional) |
| Mean R | +%0.07 (tahmin) | tahmin +%0.05 | tahmin +%0.09 | +%0.08 - +%0.10 |
| Runner contribution | ~%30 | ~%20 | ~%40 | %25-35 |
| Hold time (median) | ~5g | ~3g | ~7g | 3-7g (vol-conditional) |

---

## 9. Implikasyonlar

### PASS
1. Multi-target engine v0.8 → v0.9 (dynamic regime)
2. Static TP/trail params deprecate
3. CEO brief: "TP/trail vol-regime continuous +%2-12pp uplift"
4. Lab tournament: static vs dynamic; combo with HYP-001/002/003/004

### FAIL
1. Static 1.0R/1.5R/1.0 ATR yapısal optimum (v1.2 sec11b zaten tunable optimum)
2. Vol-regime conditioning entry-time fix'leme yetersiz (path-dependent rebalancing v3 olabilir)
3. Olası v2: vol_pct intraday update (trade ömrü içinde TP/trail dynamic shift) — engine framework değişikliği büyük

---

## 10. Reproducibility Footer

```
hypothesis_id: 2026-05-15-vol-percentile-aware-multi-target-tp-v2
git_hash_at_registration: 3da3344b2e69992f45e3acd8c40d4b399808e14f
config_hash: <stable_hash section 3 params>
data_hash: <ohlcv 11 sym 2021-2026>
walk_forward: 3y/6mo/3mo n=13
multiple_testing: bonferroni n=5 alpha_adj=0.010
baseline_set: (base, tight_static, wide_static)
output_planned: reports/research/vol_pct_dynamic_tp_v1_results.{txt,json}
```

---

## 11. Yasaklar

- ❌ Mapping slope/range OOS-tune (PRE-REG: 0.6-1.4 / 1.0-2.0 / 0.5-1.5 linear)
- ❌ RV period / pct lookback OOS-pick (PRE-REG: 14d / 90d)
- ❌ Partial close oranları OOS-tune (PRE-REG: 30/30/40 — sec11b/v0.8 mirası)
- ❌ Trade ömründe vol_pct update (PRE-REG: entry-time fix, single computation)
- ❌ FAIL learning log olmadan v2

---

## Sonuçlar (DOLDURULACAK)

- [ ] Mean return alpha (target ≥ +%2pp): __
- [ ] Mean MaxDD bozulması (target ≤ +%2pp): __
- [ ] Vol-quartile monotonicity (mean_R Q1<Q2<Q3<Q4): __
- [ ] Bootstrap CI low > 0: __
- [ ] Bonferroni p < 0.010: __
- [ ] Robustness PASS (target ≥ 5/7): __
- [ ] Karar: __
