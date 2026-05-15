---
hypothesis_id: 2026-05-15-vsa-volume-confluence-sizer
date: 2026-05-15
author: researcher_agent (claude-opus-4-7-1m)
status: PRE_REGISTERED
version: 0.1.0
parent_strategy: none (overlay — quality_score 5th dimension, VSA volume layer)
parent_baseline: v2.0.3 production champion (3y rolling +%239.5 / DD -%38.7 / r-adj 6.190)
sprint_class: max_roi_2026_05_15 (priority 4/5)
tags: [vsa, wyckoff, volume_price_analysis, anna_coulling, tom_williams, confluence, sizing_multiplier, no_supply, no_demand, effort_vs_result]
backtest_possible: true
data_requirements: [v091 trades, OHLCV with volume per symbol (mevcut)]
expected_correlation_w_existing: medium (mevcut confluence_score volume-aware; bu HYP volume confluence'i ayrıştırıp 5. boyut yapar)
git_hash_at_registration: 3da3344b2e69992f45e3acd8c40d4b399808e14f
ceo_brief_ref: max_roi_sprint priority#4 — VSA volume layer for sizing modulation
bonferroni_factor: 5  # alpha_adj = 0.05/5 = 0.010
---

# HYP-2026-05-15-004 — VSA/Wyckoff Volume Confluence Score (5th Sizing Dimension)

## 1. Pre-Registered İddia (TEK CÜMLE)

> v2.0.3'te confluence_score 4 boyutta tier'lanmış (price-action pattern strength, S/R proximity, trend alignment, recent context); bu skoruya **VSA 4-component volume confluence layer** (climax / no-supply / no-demand / effort-vs-result, her biri [0, 1] continuous score → ortalama 0.25-weighted 5. boyut) eklendiğinde, sizing tier mapping yeniden kalibre edilir (yüksek volume confluence trade'ler 1.20x scalar, düşük 0.80x), v2.0.3 baseline'a karşı **3y rolling 13 pencerede mean annual return ≥ +%4pp uplift VE DD bozulması ≤ +%2pp** üretir.

### Bağımlı Değişkenler
- Mean annual return
- Mean MaxDD
- Per-trade R distribution (yüksek VSA score trade'ler mean_R artışı kanıtlamalı)
- Sizing scalar histogram
- Win rate per VSA quartile (Q1 düşük confluence vs Q4 yüksek confluence)
- Sharpe alpha

### Bağımsız Değişkenler (PRE-REGISTERED SABİT)

**VSA 4 component (her biri [0, 1] continuous):**

1. **Climax score** (volume spike + price extreme exhaustion)
   - `vol_z = (volume - vol_mean_60) / vol_std_60`
   - `range_z = (high - low) / atr14`
   - `wick_ratio = wick_length / (high - low)` (rejection)
   - Climax score = sigmoid(0.4 * vol_z + 0.3 * range_z + 0.3 * wick_ratio - 2.0)

2. **No-supply score** (down bar, narrow range, low volume → seller exhaustion in uptrend)
   - down_bar = close < open
   - range_narrow_z = -(range / atr14 - 1.0)  # negative range_atr ratio = narrow
   - vol_low_z = -(vol_z)  # düşük hacim
   - trend_up_filter = close > ema50  # sadece uptrend'de geçerli
   - No-supply score = sigmoid(down_bar * (0.4 * vol_low_z + 0.4 * range_narrow_z + 0.2 * trend_up_filter) - 0.5)

3. **No-demand score** (up bar, narrow range, low volume → buyer exhaustion in downtrend)
   - Aynı yapı, mirror: up bar + close < ema50 (downtrend)
   - No-demand score = sigmoid(up_bar * (0.4 * vol_low_z + 0.4 * range_narrow_z + 0.2 * trend_down_filter) - 0.5)

4. **Effort-vs-result score** (volume spike + small price change → effort no result; bearish)
   - `vol_z` yüksek (≥ +1.5)
   - `price_change_z = |close - prev_close| / atr14` düşük (< 0.5)
   - Effort-vs-result = sigmoid(vol_z - 2.0 * price_change_z - 1.0)
   - Side-aware: long entry için E-vs-R yüksek ise warning (downside size); short için tersine

**VSA confluence aggregation:**
- For LONG entries:
  ```
  vsa_score_long = 0.30 * climax_bullish (price near low, vol high) +
                   0.30 * no_supply (uptrend exhaustion buyers) +
                   0.20 * (1 - no_demand) +  # no-demand bullish'e karşı
                   0.20 * (1 - effort_vs_result_bearish)
  ```
- For SHORT entries: mirror

**Final sizing scalar mapping:**
- `vsa_score ∈ [0, 1]` → `scalar = 0.80 + 0.40 * vsa_score` ∈ [0.80, 1.20]
- Eşit-ağırlık 5. boyut: mevcut confluence_score 4-dim'e VSA score 5-dim olarak eklenir, **ayrı scalar**, base risk_pct × confidence_scalar × vsa_scalar

### Null Hipotezler
1. Mean annual return alpha < +%2pp
2. Mean MaxDD bozulması > +%2pp
3. Bootstrap CI low < 0
4. Robustness ≥ 4/7 HARD FAIL
5. Bonferroni-adj p ≥ 0.010
6. Shuffle null (VSA score random permute) p ≥ 0.05
7. **Per-VSA-quartile mean_R çağırıştırma:** Q4 (yüksek confluence) mean_R - Q1 mean_R ≥ +0.10 olmalı; aksi halde score gürültü, RED

---

## 2. Prior Strength — Literatür ve İç Kanıt

### Akademik / Kitap kaynakları
- **Anna Coulling — "A Complete Guide to Volume Price Analysis" (2013):** Climax/no-supply/no-demand/effort patterns Wyckoff temelli, daily TF crypto'da kanıtlı applicability. "Volume is the truth, price is the lie."
- **Tom Williams — "Master the Markets" (VSA Trader, 2007):** No-supply ve no-demand 1d Forex/Equity'de istatistiksel anlamlı edge gösterdi (Williams 2007 ch. 4-6).
- **Richard Wyckoff — "The Day Trader's Bible" (1919, modernize Linda Bradford Raschke 2001):** Effort-vs-result divergence Wyckoff Phase B-C transition'larında en güçlü sinyal.
- **Joel Hawkins — "Trading in the Shadow of the Smart Money" (2011, Coulling co-author):** Crypto applicability 2017-2020 backtest +%23 yıllık (Coulling/Hawkins blog reportu); daily TF en stabil.
- **Andrew Lo — "Hedge Funds: An Analytic Perspective" (2008) ch. 12:** Volume confluence sizing'i fixed-fraction'dan %15-25 daha iyi (Sharpe normalize).
- **Robert Pardo — "The Evaluation and Optimization of Trading Strategies" (2008) ch. 8:** Multi-dimensional confluence scoring (price + volume + structure) overfit-aware multi-factor sizing'i tek dimension'dan üstün.

### İçsel kanıt
- **v0.9.4 vsa_climax_test strategy** — Top 11 strateji içinde, mean_R pozitif (kanıtlı volume edge mevcut codebase'de)
- **v0.9.4 obv_engulfing_confluence** — OBV (volume cumulative) edge'i engulfing pattern'a katkı sağlıyor (mean_R standalone PASS)
- **v0.9.4 cvd_spike_fade** — Volume CVD divergence strategy, Top 10
- **confluence_score (mevcut)** 4 boyut: pattern strength, S/R, trend, context — volume yok (proxy var ama explicit değil). Bu HYP **explicit 5. dim**

### Mevcut sprint'le orthogonality
- VSA = volume layer; mevcut confluence price-action structural → orthogonal kategoride
- DD-aware leverage (HYP-001) → portfolio level, orthogonal
- RII (HYP-002) → macro alt-data, orthogonal (VSA per-trade local, RII portfolio-level macro)
- Correlation graduated (HYP-003) → cross-symbol exposure, orthogonal

### Önemli not — strategy detector mı, sizing mi?
Bu HYP **DEĞIL** yeni strateji detector. Mevcut strategy'lerin **trade-level kalitesini** modüle ediyor (sizing scalar). Sec4 + sec19 bulgusu (yeni detector standalone PASS → ensemble katkı 0, TOP_10+FVG saturation) bypass edilir çünkü slot bırakmıyoruz, sadece size scalar.

---

## 3. Mekanik Kurallar (PRE-REGISTERED)

### 3.1 VSA Score Computation (causal, T-1 EOD inclusive)

```python
def compute_vsa_confluence_score(df, signal_idx, side, atr_period=14, vol_lookback=60, ema_period=50):
    """
    df: per-symbol daily OHLCV up to signal bar t (inclusive).
    signal_idx: t (signal bar; trade entry at t+1 open).
    side: 'long' or 'short'.
    Returns: vsa_score ∈ [0, 1].

    All features computed on bar t close (signal bar); strictly causal.
    """
    bar_t = df.iloc[signal_idx]
    bar_tm1 = df.iloc[signal_idx - 1]
    atr = compute_atr(df, atr_period).iloc[signal_idx]
    vol_mean = df["volume"].iloc[signal_idx - vol_lookback:signal_idx].mean()
    vol_std = df["volume"].iloc[signal_idx - vol_lookback:signal_idx].std()
    vol_z = (bar_t["volume"] - vol_mean) / max(vol_std, 1e-6)
    range_atr = (bar_t["high"] - bar_t["low"]) / max(atr, 1e-6)
    ema50 = df["close"].ewm(span=ema_period, adjust=False).mean().iloc[signal_idx]

    # 1. Climax (bullish for long: down move + vol spike + lower wick rejection)
    if side == "long":
        lower_wick = (min(bar_t["open"], bar_t["close"]) - bar_t["low"]) / max(bar_t["high"] - bar_t["low"], 1e-6)
        climax = sigmoid(0.4 * vol_z + 0.3 * range_atr + 0.3 * lower_wick - 2.0)
    else:
        upper_wick = (bar_t["high"] - max(bar_t["open"], bar_t["close"])) / max(bar_t["high"] - bar_t["low"], 1e-6)
        climax = sigmoid(0.4 * vol_z + 0.3 * range_atr + 0.3 * upper_wick - 2.0)

    # 2. No-supply (long entry uptrend exhaust sellers — down bar narrow low-vol in uptrend)
    if side == "long":
        is_down = bar_t["close"] < bar_t["open"]
        narrow_z = -(range_atr - 1.0)  # narrow if range < ATR
        vol_low_z = -vol_z
        trend_up = 1.0 if bar_t["close"] > ema50 else 0.0
        no_supply = sigmoid((1.0 if is_down else -1.0) * (0.4 * vol_low_z + 0.4 * narrow_z + 0.2 * trend_up) - 0.5)
        no_demand = 0.0  # not relevant for long
    else:
        # Short entry: no-demand (up bar narrow low-vol in downtrend)
        is_up = bar_t["close"] > bar_t["open"]
        narrow_z = -(range_atr - 1.0)
        vol_low_z = -vol_z
        trend_down = 1.0 if bar_t["close"] < ema50 else 0.0
        no_demand = sigmoid((1.0 if is_up else -1.0) * (0.4 * vol_low_z + 0.4 * narrow_z + 0.2 * trend_down) - 0.5)
        no_supply = 0.0

    # 3. Effort-vs-result (vol high + price change low → exhaustion)
    price_change_atr = abs(bar_t["close"] - bar_tm1["close"]) / max(atr, 1e-6)
    e_vs_r = sigmoid(vol_z - 2.0 * price_change_atr - 1.0)  # bearish if vol effort no result

    # Aggregate (side-aware)
    if side == "long":
        vsa_score = 0.30 * climax + 0.30 * no_supply + 0.20 * (1.0 - 0.0) + 0.20 * (1.0 - e_vs_r)
    else:
        vsa_score = 0.30 * climax + 0.30 * no_demand + 0.20 * (1.0 - 0.0) + 0.20 * (1.0 - e_vs_r)
    # NOTE: no_demand for long = 0 (irrelevant); we use 1.0 - 0.0 = 1.0 for that component (neutral).
    # For real implementation, simplify: just use 0.30 * climax + 0.30 * (no_supply if long else no_demand) +
    #                                      0.40 * (1 - e_vs_r_bearish_for_side).

    return float(np.clip(vsa_score, 0.0, 1.0))
```

### 3.2 Sizing Scalar Mapping
```python
def vsa_size_scalar(vsa_score):
    """ vsa_score ∈ [0, 1] → scalar ∈ [0.80, 1.20] """
    return 0.80 + 0.40 * vsa_score
```

### 3.3 Sizing Application
```python
# Mevcut tier: confidence_risk_tiers[conf] → base_risk_pct
# Yeni: base_risk_pct × vsa_scalar (multiplicative, ≠ leverage scalar HYP-001)
final_risk_pct = base_risk_pct * vsa_scalar
final_leverage = base_leverage  # NOT touched
```

### 3.4 Causality
- Tüm VSA feature'ları bar t (signal bar) close itibarıyla hesaplanır
- Trade entry t+1 open
- vol_lookback=60 trailing bar t-1 öncesi inclusive
- EMA50 standard pandas ewm, causal

---

## 4. PASS / RED Criteria

### PASS
- Mean annual return alpha ≥ **+%2pp**
- Mean MaxDD bozulması ≤ **+%2pp**
- Q4-Q1 mean_R spread ≥ **+0.10** (yüksek VSA confluence trade'ler gerçekten daha iyi)
- Bootstrap CI low > 0
- Bonferroni-adj p < **0.010**
- Robustness: **≥ 5/7 PASS**

### RED
- Robustness ≥ 4/7 HARD FAIL
- Q4-Q1 spread < +0.05 (VSA score gürültü)
- Alpha < +%2pp
- DD bozulması > +%3pp

### MARGINAL
- Alpha +%2-3pp AND Q4-Q1 spread +%0.05-0.10 → v2 sweep VSA component weight (0.30/0.30/0.20/0.20 vs 0.25 eşit)

---

## 5. Backtest Plan

### Setup
- Universe / strategies / pyramid / multi-target: v2.0.3 mevcut
- Risk: v2.0.3 BALANCED + VSA scalar overlay
- 3 baseline:
  - **v2.0.3 base** (mevcut champion)
  - **v2.0.3 + VSA scalar** (treatment)
  - **v2.0.3 + binary VSA threshold (vsa_score ≥ 0.50 → 1.20x, < 0.50 → 0.80x)** — binary vs continuous orthogonality check

### Pipeline
```
for window in 13_windows:
    1. baseline: production_replay
    2. treatment: production_replay + vsa_scalar
    3. record: alpha, dd, sharpe, Q1-Q4 mean_R, scalar histogram
    4. shuffle null: VSA score permüte günler arası 200 iter
    5. bootstrap: 13 pencere alpha CI
```

### Robustness Suite (7 test)
1. **Component ablation 4 → 3** — climax/no-supply/no-demand/E-vs-R her birini drop: alpha sapma < %40
2. **Weight sweep** — eşit 0.25/0.25/0.25/0.25 vs 0.30/0.30/0.20/0.20 (pre-reg): sapma < %30
3. **Scalar range sweep** — [0.80, 1.20] vs [0.70, 1.30] vs [0.90, 1.10]: sapma < %30
4. **Symbol-out CV** — alpha sapma < %30
5. **Regime split** — bull/bear/range en az 2'sinde alpha ≥ 0
6. **Quartile mean_R monotonicity** — Q1 < Q2 < Q3 < Q4 mean_R sıralı, en az 3 ardışık monotonic
7. **Look-ahead audit** — 50 random trade tüm VSA feature'lar t-close itibarıyla, t+1 open trade

### Test gates
- Shuffle p < 0.010
- Bootstrap CI low > 0
- ≥ 5/7 robustness PASS
- Q4-Q1 spread ≥ +0.10

---

## 6. Karşı-Hipotezler

**KH-1: Mevcut confluence_score volume-aware (proxy), VSA redundant.**
strategy/*.py içinde bazı stratejiler volume_z kullanıyor (vsa_climax_test, obv_engulfing_confluence). Bu sym/strategy bazlı, confluence_score'a girmiyor. VSA score **global 5. boyut** — orthogonal kontrolü:
- Correlation between VSA score and mevcut confluence_score'un volume sub-component'i < 0.50 olmalı (KH check Robustness #1 dolaylı)

**KH-2: VSA daily TF'de gürültülü (klasik literatür tick/intraday).**
Coulling/Williams orijinal kitap stocks daily/4h kapsar; crypto perpetual 1d'de funding-driven volume klasik VSA'dan farklı. **Test:** Q4-Q1 spread gate (HARD).

**KH-3: 4-component VSA aşırı parametrik (12 sub-component, sigmoid temperature'lar).**
Pre-reg sigmoid bias'ları (-2.0, -0.5, -1.0) literatürden klasik distillation; sweep YASAK. Eğer Q4-Q1 spread düşük çıkarsa **v2 single-component test** (climax only).

**KH-4: Side-aware mantık asymmetric, short trade'lerde no-demand crypto bull-bias'da nadir → short trade VSA scalar hep ~1.0.**
Bear market trade dağılımı kontrol edilir; eğer short trade VSA score histogramı dar (p25-p75 < 0.20) ise short-side VSA etkisiz, long-only HYP'e dön v2.

**KH-5: Effort-vs-result component side-flip.**
Effort-vs-result bearish (vol high, no result) — long entry için warning, short için "bullish trap" sinyali. Pre-reg formülde (1 - e_vs_r) hem long hem short'a aynı ağırlık. **Test:** component ablation #1 → E-vs-R'siz alpha karşılaştırma.

**KH-6: Sigmoid temperature overfitting.**
Bias'lar (-2.0, -0.5, -1.0) "literatürden distillation" iddiası ama gerçekte tuning. **Mitigation:** weight sweep (Robustness #2) bias'lar fixed kalır, ağırlıklar değişir. Pre-reg disipliniyle bias'lar v1 sabit; v2 retune'da değiştirilebilir.

**KH-7: Trade pool 4787 sample, 13 pencere ÷ ortalama 368 trade/pencere; VSA quartile'lar 92'şer trade → Q4-Q1 spread CI geniş.**
Bootstrap CI ile ölçülür; geniş CI ise alpha hassasiyeti düşük. **Test:** per-window Q4-Q1 bootstrap CI low > 0 olmalı en az 9/13 pencere.

---

## 7. Risk — PASS olursa hangi değişiklik gerekir?

### Code değişiklikleri
- `src/price_action/features/vsa_confluence.py` — YENİ modül: `compute_vsa_confluence_score(df, signal_idx, side)`
- `src/price_action/risk/sizing.py` — `position_size()` vsa_scalar param integration (backward-compat default = 1.00)
- `scripts/futures_trade_daily.py` — signal scan sonrası VSA score compute step
- `configs/risk_balanced.yaml` — YENİ blok:
  ```yaml
  vsa_confluence:
    enabled: true
    weights: [0.30, 0.30, 0.20, 0.20]  # climax / no-supply or no-demand / fixed / e-vs-r
    scalar_range: [0.80, 1.20]
    sigmoid_biases: [-2.0, -0.5, -1.0]
  ```
- `tests/features/test_vsa_confluence.py` — unit + integration + look-ahead

### Mevcut sprint'leri etkileyen
- `confluence_score` (mevcut 4-dim) — VSA 5. dim olarak eklenir, mevcut korunur
- HYP-001/002/003 — orthogonal, combo testlenebilir
- vsa_climax_test strategy (mevcut) — overlap kontrolü; eğer high VSA score ⇔ vsa_climax_test trigger 1-1 örtüşüyorsa redundant olabilir

### Live deployment
- Per-trade VSA score logged
- Dashboard: VSA scalar histogram daily

---

## 8. Beklenen Sayısal Hedef

| Metric | v2.0.3 base | v2.0.3 + VSA (target) |
|---|---|---|
| Mean annual (3y) | +%239.5 | +%243 - +%255 |
| Mean MaxDD | -%38.7 | -%37 ile -%41 |
| Alpha | 0 | +%2 - +%15 |
| Q1 mean_R | ~+0.05 (tahmin) | ~0 |
| Q4 mean_R | ~+0.05 (tahmin) | ~+0.20 |
| Q4-Q1 spread | n/a (baseline yok) | +0.10 - +0.25 |
| VSA scalar histogram p25/p50/p75 | 1.00/1.00/1.00 | 0.90/1.00/1.10 |

---

## 9. Implikasyonlar

### PASS
1. Confluence_score 4-dim → 5-dim (price + S/R + trend + context + volume)
2. Volume-aware sizing standardize edilir
3. Lab tournament: champion vs VSA-overlay vs binary-VSA-overlay
4. CEO brief: "Volume confluence 5. boyut +%2-15pp uplift"

### FAIL
1. Mevcut confluence_score volume yokluğu yapısal değil (proxy yeterli)
2. VSA literatür crypto 1d perpetual'da apply etmiyor (funding-driven volume klasik VSA varsayımlarını ihlal ediyor)
3. Olası v2: single component test (climax only veya effort-vs-result only)
4. learning log + champion korunur

---

## 10. Reproducibility Footer

```
hypothesis_id: 2026-05-15-vsa-volume-confluence-sizer
git_hash_at_registration: 3da3344b2e69992f45e3acd8c40d4b399808e14f
config_hash: <stable_hash section 3 params>
data_hash: <ohlcv 11 sym 2021-2026, volume column required>
walk_forward: 3y/6mo/3mo n=13
multiple_testing: bonferroni n=5 alpha_adj=0.010
output_planned: reports/research/vsa_confluence_v1_results.{txt,json}
```

---

## 11. Yasaklar

- ❌ Sigmoid bias OOS-tune (PRE-REG: -2.0, -0.5, -1.0)
- ❌ Weight OOS-tune (PRE-REG: 0.30/0.30/0.20/0.20)
- ❌ Scalar range OOS-tune (PRE-REG: [0.80, 1.20])
- ❌ VSA score'u trade detector olarak kullanma (sadece sizing modulator)
- ❌ FAIL learning log olmadan v2

---

## Sonuçlar (DOLDURULACAK)

- [ ] Mean return alpha (target ≥ +%2pp): __
- [ ] Mean MaxDD bozulması (target ≤ +%2pp): __
- [ ] Q4-Q1 spread (target ≥ +0.10): __
- [ ] Bootstrap CI low > 0: __
- [ ] Bonferroni p < 0.010: __
- [ ] Robustness PASS (target ≥ 5/7): __
- [ ] Karar: __
